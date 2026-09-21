#!/usr/bin/env python3
"""Persistent per-home owner of one public Codex app-server child."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from fleet_codex import (
    CodexPublicEvidenceStore,
    IPC_PROTOCOL_VERSION,
    MAX_OPERATION_TIMEOUT_SECONDS,
    MAX_IPC_BYTES,
    HostRejected,
    OperationJournal,
    _atomic_json,
    _canonical_home,
    _digest,
    _recv_frame,
    _public_evidence,
    _public_method,
    _process_identity,
    _read_key,
    _remaining,
    _send_frame,
    reconcile_home,
)
from fleet_codex_protocol import AppServerClient
from fleet_errors import FleetCliError


def _response(request: Mapping[str, Any] | None, *, ok: bool,
              result: Any = None, error: str | None = None) -> dict[str, Any]:
    request = request or {}
    return {
        "ok": ok,
        "operation_id": request.get("operation_id"),
        "host_generation": request.get("host_generation"),
        "fleet_home": request.get("fleet_home"),
        "payload_digest": request.get("payload_digest"),
        "result": result if ok else None,
        "error": error if not ok else None,
    }


def _bounded_rpc_timeout(payload: Mapping[str, Any], operation_timeout: float,
                         deadline: float) -> float:
    requested = payload.get("timeout", min(30.0, operation_timeout))
    if (not isinstance(requested, (int, float)) or isinstance(requested, bool)
            or not math.isfinite(requested) or requested <= 0):
        raise ValueError("rpc timeout must be a positive finite number")
    return min(float(requested), operation_timeout, _remaining(deadline))


class Host:
    def __init__(self, *, home: Path, generation: str, endpoint: str,
                 transport: str, app_server_command: list[str],
                 schema_manifest: Path, schema_command: list[str],
                 idle_timeout: float) -> None:
        self.home = _canonical_home(home)
        self.generation = generation
        self.endpoint = endpoint
        self.transport = transport
        self.state_dir = self.home / "state" / "codex"
        self.metadata_path = self.state_dir / "host.json"
        self.encoded_key, self.authkey = _read_key(self.state_dir / "host.key")
        self.app_server_command = app_server_command
        self.schema_command = schema_command
        self.idle_timeout = idle_timeout
        self.last_activity = time.monotonic()
        self.stop = threading.Event()
        manifest = json.loads(schema_manifest.read_text(encoding="utf-8"))
        self.schema_digest = manifest["schema_sha256"]
        self.expected_version = manifest["codex_version"]
        self.client: AppServerClient | None = None
        self.listener: socket.socket | None = None
        self.journal = OperationJournal(self.home, self.generation)
        self.evidence = CodexPublicEvidenceStore(self.home)

    def metadata(self) -> dict[str, Any]:
        app_server_pid = self.client.process_id if self.client is not None else None
        return {
            "schema": 1,
            "home": str(self.home),
            "generation": self.generation,
            "endpoint": self.endpoint,
            "transport": self.transport,
            "pid": os.getpid(),
            "process_identity": _process_identity(os.getpid()),
            "started_at": self.started_at,
            "app_server_pid": app_server_pid,
            "app_server_process_identity": (
                _process_identity(app_server_pid)
                if isinstance(app_server_pid, int) else None),
            "app_server_started_at": self.app_server_started_at,
            "heartbeat": time.time(),
            "codex_version": self.expected_version,
            "ipc_protocol_version": IPC_PROTOCOL_VERSION,
            "codex_protocol_version": 2,
            "schema_digest": self.schema_digest,
            "ready": True,
        }

    def run(self) -> int:
        self._verify_installed_schema()
        self.client = AppServerClient.start(
            self.app_server_command, cwd=self.home, env=os.environ, timeout=10)
        self.app_server_started_at = time.time()
        initialized = self.client.initialize_result
        if not self._reviewed_initialize(initialized):
            self.client.close()
            raise RuntimeError(
                "Codex app-server initialize result does not match reviewed "
                f"{self.expected_version!r} contract")
        # Classify every old durable intent before this generation can publish
        # ready or accept a fresh mutation. Until the public observer is wired,
        # accepted operations conservatively become uncertain and page-worthy.
        reconcile_home(self.home)
        if self.transport != "AF_UNIX":
            raise RuntimeError("only reviewed AF_UNIX transport is supported")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.endpoint)
        Path(self.endpoint).chmod(0o600)
        self.listener.listen(16)
        self.listener.settimeout(0.2)
        self.started_at = time.time()
        _atomic_json(self.metadata_path, self.metadata())
        heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
        heartbeat.start()
        try:
            while not self.stop.is_set():
                self._drain_notifications()
                try:
                    connection, _ = self.listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop.is_set():
                        break
                    continue
                self.last_activity = time.monotonic()
                should_stop = self._serve_connection(connection)
                if should_stop:
                    self.stop.set()
        finally:
            self.stop.set()
            self._drain_notifications()
            if self.listener is not None:
                self.listener.close()
            if self.client is not None:
                self.client.close()
            if self.transport == "AF_UNIX":
                try:
                    endpoint = Path(self.endpoint)
                    if stat.S_ISSOCK(endpoint.lstat().st_mode):
                        endpoint.unlink()
                except OSError:
                    pass
            heartbeat.join(timeout=1)
        return 0

    def _reviewed_initialize(self, initialized: Any) -> bool:
        if not isinstance(initialized, dict):
            return False
        server_info = initialized.get("serverInfo")
        if server_info is not None:
            return (isinstance(server_info, dict)
                    and server_info.get("version") == self.expected_version)
        user_agent = initialized.get("userAgent")
        codex_home = initialized.get("codexHome")
        configured_home = os.environ.get("CODEX_HOME")
        expected_home = (Path(configured_home).expanduser()
                         if configured_home else Path.home() / ".codex")
        try:
            expected_home = expected_home.resolve(strict=True)
            initialized_home = Path(codex_home).resolve(strict=True) \
                if isinstance(codex_home, str) else None
        except OSError:
            return False
        return (
            isinstance(user_agent, str)
            and user_agent.startswith(f"fleet/{self.expected_version} ")
            and isinstance(codex_home, str)
            and Path(codex_home).is_absolute()
            and initialized_home == expected_home
            and isinstance(initialized.get("platformFamily"), str)
            and bool(initialized["platformFamily"])
            and isinstance(initialized.get("platformOs"), str)
            and bool(initialized["platformOs"])
        )

    def _drain_notifications(self) -> None:
        if self.client is None:
            return
        for message in self.client.notifications():
            self.evidence.record(message)

    def _verify_installed_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fleet-codex-schema-") as directory:
            command = self.schema_command + [
                "app-server", "generate-json-schema", "--out", directory]
            try:
                subprocess.run(
                    command, cwd=self.home, env=os.environ,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE, timeout=15, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError("could not generate installed Codex schema") from exc
            schema = Path(directory) / "codex_app_server_protocol.v2.schemas.json"
            try:
                size = schema.stat().st_size
                if size > 8 * 1024 * 1024:
                    raise RuntimeError("installed Codex schema exceeds size bound")
                actual = hashlib.sha256(schema.read_bytes()).hexdigest()
            except OSError as exc:
                raise RuntimeError("installed Codex schema bundle is missing") from exc
            if not hmac.compare_digest(actual, self.schema_digest):
                raise RuntimeError(
                    "installed Codex schema does not match the reviewed digest")

    def _heartbeat(self) -> None:
        while not self.stop.wait(0.5):
            try:
                _atomic_json(self.metadata_path, self.metadata())
            except OSError:
                self._wake_shutdown("metadata-write-failed")
                return
            if (self.idle_timeout > 0
                    and time.monotonic() - self.last_activity > self.idle_timeout
                    and not self.journal.has_unresolved()):
                self._wake_shutdown("idle-timeout")
                return

    def _wake_shutdown(self, reason: str) -> None:
        """Wake the blocking accept loop through the authenticated endpoint."""
        operation_id = f"host-{reason}"
        payload: dict[str, Any] = {}
        request = {
            "protocol_version": IPC_PROTOCOL_VERSION,
            "host_generation": self.generation,
            "operation_id": operation_id,
            "method": "host/shutdown",
            "fleet_home": str(self.home),
            "payload": payload,
            "payload_digest": _digest("host/shutdown", payload),
            "secret": self.encoded_key,
            "operation_timeout": 1.0,
        }
        from fleet_codex import _connect_authenticated
        try:
            deadline = time.monotonic() + 1
            connection = _connect_authenticated(self.endpoint, self.authkey, deadline)
            try:
                _send_frame(connection, json.dumps(
                    request, separators=(",", ":"), sort_keys=True).encode("utf-8"), deadline)
                _recv_frame(connection, deadline)
            finally:
                connection.close()
        except (OSError, EOFError, TimeoutError, ValueError):
            self.stop.set()
            if self.listener is not None:
                self.listener.close()

    def _serve_connection(self, connection: socket.socket) -> bool:
        request: dict[str, Any] | None = None
        should_stop = False
        accepted_at = time.monotonic()
        deadline = accepted_at + 1.0
        try:
            challenge = os.urandom(32)
            _send_frame(connection, challenge, deadline)
            supplied = _recv_frame(connection, deadline, 32)
            if not hmac.compare_digest(
                    supplied, hmac.digest(self.authkey, challenge, "sha256")):
                raise ValueError("Codex host authentication failed")
            _send_frame(connection, b"OK", deadline)
            raw = _recv_frame(connection, deadline)
            decoded = raw.decode("utf-8")
            value = json.loads(decoded)
            if not isinstance(value, dict):
                raise ValueError("IPC request must be an object")
            request = value
            error = self._validate(request)
            if error is not None:
                response = _response(request, ok=False, error=error)
            else:
                deadline = accepted_at + float(request["operation_timeout"])
                method = request["method"]
                payload = request.get("payload", {})
                if method == "ping":
                    result = {
                        "generation": self.generation,
                        "home": str(self.home),
                        "endpoint": self.endpoint,
                        "transport": self.transport,
                        "ipc_protocol_version": IPC_PROTOCOL_VERSION,
                        "codex_protocol_version": 2,
                        "schema_digest": self.schema_digest,
                    }
                elif method == "rpc":
                    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str):
                        raise ValueError("rpc payload is malformed")
                    rpc_timeout = _bounded_rpc_timeout(
                        payload, float(request["operation_timeout"]), deadline)
                    assert self.client is not None
                    public_method = _public_method("rpc", payload)
                    if public_method is None:
                        result = self.client.request(
                            payload["method"], payload.get("params", {}),
                            timeout=rpc_timeout)
                        self._drain_notifications()
                    else:
                        operation_id = request["operation_id"]
                        record = self.journal.load(operation_id)
                        if record.get("generation") != self.generation:
                            raise ValueError("operation belongs to another host generation")
                        if record.get("payload_digest") != request.get("payload_digest"):
                            raise ValueError("operation payload digest conflicts with journal")
                        if record.get("recovery") != _public_evidence(request.get("recovery", {})):
                            raise ValueError("operation recovery metadata conflicts with journal")
                        state = record.get("state")
                        if state in {"observed", "committed"}:
                            result = record.get("result")
                        elif state in {"accepted", "uncertain"}:
                            raise ValueError("operation acceptance is uncertain; reconcile before retry")
                        elif state == "failed":
                            raise ValueError("operation is terminally failed")
                        elif state == "prepared":
                            predecessor = self.journal.unresolved_predecessor(
                                operation_id)
                            if predecessor is not None:
                                self.journal.fail(
                                    operation_id,
                                    "blocked by unresolved predecessor operation")
                                raise HostRejected(
                                    "unresolved predecessor operation "
                                    f"{predecessor.get('operation_id')} blocks mutation")
                            self.journal.accept(operation_id)
                            try:
                                result = self.client.request(
                                    payload["method"], payload.get("params", {}),
                                    timeout=rpc_timeout)
                            except Exception as exc:
                                self.journal.uncertain(
                                    operation_id,
                                    f"public mutation outcome unknown: {type(exc).__name__}")
                                raise ValueError(
                                    "public mutation outcome is uncertain") from exc
                            self.journal.observe(operation_id, result)
                        else:
                            raise ValueError("operation journal has unknown state")
                elif method == "public-evidence/read":
                    if not isinstance(payload, dict):
                        raise ValueError("public evidence payload is malformed")
                    self._drain_notifications()
                    result = self.evidence.read(
                        payload.get("thread_id"), payload.get("turn_id"))
                elif method == "host/shutdown":
                    result = {"stopping": True}
                    should_stop = True
                else:
                    raise ValueError("unknown host method")
                response = _response(request, ok=True, result=result)
        except (UnicodeError, json.JSONDecodeError, ValueError, OSError,
                EOFError, TimeoutError,
                FleetCliError) as exc:
            response = _response(request, ok=False, error=str(exc)[:300])
        try:
            encoded = json.dumps(response, separators=(",", ":"),
                                 sort_keys=True).encode("utf-8")
            _send_frame(connection, encoded, deadline)
        except (OSError, EOFError, TimeoutError, ValueError):
            pass
        finally:
            connection.close()
        return should_stop

    def _validate(self, request: Mapping[str, Any]) -> str | None:
        if request.get("protocol_version") != IPC_PROTOCOL_VERSION:
            return "wrong protocol version"
        if request.get("host_generation") != self.generation:
            return "wrong host generation"
        if request.get("fleet_home") != str(self.home):
            return "wrong fleet home"
        secret = request.get("secret")
        if not isinstance(secret, str) or not hmac.compare_digest(secret, self.encoded_key):
            return "wrong host secret"
        operation_id = request.get("operation_id")
        method = request.get("method")
        operation_timeout = request.get("operation_timeout")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            return "invalid operation id"
        if not isinstance(method, str) or not method:
            return "invalid method"
        if (not isinstance(operation_timeout, (int, float))
                or isinstance(operation_timeout, bool)
                or not math.isfinite(operation_timeout)
                or operation_timeout <= 0
                or operation_timeout > MAX_OPERATION_TIMEOUT_SECONDS):
            return "invalid operation timeout"
        try:
            expected = _digest(method, request.get("payload", {}))
        except (TypeError, ValueError):
            return "payload is not canonical JSON"
        digest = request.get("payload_digest")
        if not isinstance(digest, str) or not hmac.compare_digest(digest, expected):
            return "wrong payload digest"
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--transport", choices=("AF_UNIX", "AF_PIPE"), required=True)
    parser.add_argument("--app-server-command-json", required=True)
    parser.add_argument("--schema-manifest", type=Path, required=True)
    parser.add_argument("--schema-command-json", required=True)
    parser.add_argument("--idle-timeout", type=float, default=0.0)
    args = parser.parse_args(argv)
    command = json.loads(args.app_server_command_json)
    if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
        raise SystemExit("invalid app-server command")
    schema_command = json.loads(args.schema_command_json)
    if (not isinstance(schema_command, list)
            or not all(isinstance(item, str) and item for item in schema_command)):
        raise SystemExit("invalid schema command")
    host = Host(
        home=args.home,
        generation=args.generation,
        endpoint=args.endpoint,
        transport=args.transport,
        app_server_command=command,
        schema_manifest=args.schema_manifest,
        schema_command=schema_command,
        idle_timeout=args.idle_timeout,
    )
    signal.signal(
        signal.SIGTERM,
        lambda *_: threading.Thread(
            target=host._wake_shutdown, args=("signal",), daemon=True).start(),
    )
    return host.run()


if __name__ == "__main__":
    raise SystemExit(main())
