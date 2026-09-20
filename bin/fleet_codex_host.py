#!/usr/bin/env python3
"""Persistent per-home owner of one public Codex app-server child."""

from __future__ import annotations

import argparse
import hmac
import json
import multiprocessing.connection
import os
import signal
import stat
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from fleet_codex import (
    IPC_PROTOCOL_VERSION,
    MAX_IPC_BYTES,
    _atomic_json,
    _canonical_home,
    _digest,
    _read_key,
)
from fleet_codex_protocol import AppServerClient


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


class Host:
    def __init__(self, *, home: Path, generation: str, endpoint: str,
                 transport: str, app_server_command: list[str],
                 schema_manifest: Path, idle_timeout: float) -> None:
        self.home = _canonical_home(home)
        self.generation = generation
        self.endpoint = endpoint
        self.transport = transport
        self.state_dir = self.home / "state" / "codex"
        self.metadata_path = self.state_dir / "host.json"
        self.encoded_key, self.authkey = _read_key(self.state_dir / "host.key")
        self.app_server_command = app_server_command
        self.idle_timeout = idle_timeout
        self.last_activity = time.monotonic()
        self.stop = threading.Event()
        manifest = json.loads(schema_manifest.read_text(encoding="utf-8"))
        self.schema_digest = manifest["schema_sha256"]
        self.expected_version = manifest["codex_version"]
        self.client: AppServerClient | None = None
        self.listener: multiprocessing.connection.Listener | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "home": str(self.home),
            "generation": self.generation,
            "endpoint": self.endpoint,
            "transport": self.transport,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "heartbeat": time.time(),
            "codex_version": self.expected_version,
            "schema_digest": self.schema_digest,
            "ready": True,
        }

    def run(self) -> int:
        self.client = AppServerClient.start(
            self.app_server_command, cwd=self.home, env=os.environ, timeout=10)
        initialized = self.client.initialize_result
        version = None
        if isinstance(initialized, dict):
            server_info = initialized.get("serverInfo")
            if isinstance(server_info, dict):
                version = server_info.get("version")
        if version != self.expected_version:
            self.client.close()
            raise RuntimeError(
                f"Codex app-server version {version!r} does not match reviewed "
                f"{self.expected_version!r}")
        self.listener = multiprocessing.connection.Listener(
            self.endpoint, family=self.transport, authkey=self.authkey)
        if self.transport == "AF_UNIX":
            Path(self.endpoint).chmod(0o600)
        self.started_at = time.time()
        _atomic_json(self.metadata_path, self.metadata())
        heartbeat = threading.Thread(target=self._heartbeat, daemon=True)
        heartbeat.start()
        try:
            while not self.stop.is_set():
                try:
                    connection = self.listener.accept()
                except (OSError, EOFError, multiprocessing.AuthenticationError):
                    if self.stop.is_set():
                        break
                    continue
                self.last_activity = time.monotonic()
                should_stop = self._serve_connection(connection)
                if should_stop:
                    self.stop.set()
        finally:
            self.stop.set()
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

    def _heartbeat(self) -> None:
        while not self.stop.wait(0.5):
            try:
                _atomic_json(self.metadata_path, self.metadata())
            except OSError:
                self._wake_shutdown("metadata-write-failed")
                return
            if (self.idle_timeout > 0
                    and time.monotonic() - self.last_activity > self.idle_timeout):
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
        }
        try:
            connection = multiprocessing.connection.Client(
                self.endpoint, family=self.transport, authkey=self.authkey)
            try:
                connection.send_bytes(json.dumps(
                    request, separators=(",", ":"), sort_keys=True).encode("utf-8"))
                if connection.poll(1):
                    connection.recv_bytes(MAX_IPC_BYTES)
            finally:
                connection.close()
        except (OSError, EOFError):
            self.stop.set()
            if self.listener is not None:
                self.listener.close()

    def _serve_connection(self, connection: multiprocessing.connection.Connection) -> bool:
        request: dict[str, Any] | None = None
        should_stop = False
        try:
            raw = connection.recv_bytes(MAX_IPC_BYTES)
            decoded = raw.decode("utf-8")
            value = json.loads(decoded)
            if not isinstance(value, dict):
                raise ValueError("IPC request must be an object")
            request = value
            error = self._validate(request)
            if error is not None:
                response = _response(request, ok=False, error=error)
            else:
                method = request["method"]
                payload = request.get("payload", {})
                if method == "ping":
                    result = {"generation": self.generation, "home": str(self.home)}
                elif method == "rpc":
                    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str):
                        raise ValueError("rpc payload is malformed")
                    assert self.client is not None
                    result = self.client.request(
                        payload["method"], payload.get("params", {}),
                        timeout=float(payload.get("timeout", 30)))
                elif method == "host/shutdown":
                    result = {"stopping": True}
                    should_stop = True
                else:
                    raise ValueError("unknown host method")
                response = _response(request, ok=True, result=result)
        except (UnicodeError, json.JSONDecodeError, ValueError, OSError) as exc:
            response = _response(request, ok=False, error=str(exc)[:300])
        try:
            encoded = json.dumps(response, separators=(",", ":"),
                                 sort_keys=True).encode("utf-8")
            connection.send_bytes(encoded)
        except (OSError, EOFError):
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
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            return "invalid operation id"
        if not isinstance(method, str) or not method:
            return "invalid method"
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
    parser.add_argument("--idle-timeout", type=float, default=0.0)
    args = parser.parse_args(argv)
    command = json.loads(args.app_server_command_json)
    if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
        raise SystemExit("invalid app-server command")
    host = Host(
        home=args.home,
        generation=args.generation,
        endpoint=args.endpoint,
        transport=args.transport,
        app_server_command=command,
        schema_manifest=args.schema_manifest,
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
