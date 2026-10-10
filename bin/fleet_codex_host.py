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
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from fleet_codex import (
    CodexApprovalStore,
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
    _public_uuid7,
    codex_process_source,
    interface_source_matches,
    read_interface_claim,
    _read_key,
    _platform,
    _remaining,
    _send_frame,
    reconcile_home,
)
from fleet_codex_protocol import (
    AppServerClient,
    EVENT_QUEUE_OVERFLOW_MESSAGE,
    RequestNotSent,
    is_event_queue_overflow,
)
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


def _ipc_peer_credentials(connection: socket.socket) -> tuple[int, int]:
    """Return kernel-owned PID and effective UID for a local socket peer."""
    try:
        if _platform().is_linux and hasattr(socket, "SO_PEERCRED"):
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, _gid = struct.unpack("3i", raw)
        elif getattr(_platform(), "is_darwin", False):
            # sys/un.h: SOL_LOCAL=0, LOCAL_PEERPID=2, LOCAL_PEERCRED=1.
            pid_raw = connection.getsockopt(0, 2, struct.calcsize("i"))
            cred_raw = connection.getsockopt(0, 1, 76)  # struct xucred, 16 groups
            if len(pid_raw) != 4 or len(cred_raw) != 76:
                raise HostRejected("could not authenticate Codex IPC peer")
            pid = struct.unpack("=i", pid_raw)[0]
            version, uid = struct.unpack_from("=II", cred_raw)
            if version != 0:  # XUCRED_VERSION
                raise HostRejected("could not authenticate Codex IPC peer")
        else:
            raise HostRejected(
                "Interface mutation authentication is unsupported on this platform")
    except (OSError, struct.error, ValueError) as exc:
        raise HostRejected("could not authenticate Codex IPC peer") from exc
    if pid <= 0 or uid < 0:
        raise HostRejected("could not authenticate Codex IPC peer")
    return pid, uid


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
        self.approvals = CodexApprovalStore(self.home, self.generation)

    def _start_app_server(self, timeout: float) -> None:
        client = AppServerClient.start(
            self.app_server_command, cwd=self.home, env=os.environ,
            timeout=timeout)
        if not self._reviewed_initialize(client.initialize_result):
            client.close()
            raise RuntimeError(
                "Codex app-server initialize result does not match reviewed "
                f"{self.expected_version!r} contract")
        self.client = client
        self.app_server_started_at = time.time()

    def _restart_app_server_after_queue_overflow(self, deadline: float) -> None:
        """Replace only the failed stdio child before read-only recovery."""
        previous = self.client
        if previous is not None:
            self._drain_notifications()
            previous.close()
        self.client = None
        try:
            self._start_app_server(min(10.0, _remaining(deadline)))
            _atomic_json(self.metadata_path, self.metadata())
        except BaseException:
            self.client = None
            raise

    def _recovery_request(self, method: str, params: Mapping[str, Any],
                          deadline: float) -> Any:
        if self.client is None:
            raise ValueError("replacement app-server is unavailable")
        result = self.client.request(
            method, dict(params), timeout=min(10.0, _remaining(deadline)))
        self._drain_notifications()
        return result

    def _recovery_turns(self, thread_id: str, deadline: float) -> list[dict]:
        """Count complete history through small metadata pages after restart."""
        turns: list[dict] = []
        cursor = None
        seen_cursors: set[str] = set()
        seen_ids: set[str] = set()
        for _page in range(4096):
            params: dict[str, Any] = {
                "threadId": thread_id, "limit": 32,
                "sortDirection": "desc", "itemsView": "notLoaded",
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = self._recovery_request("thread/turns/list", params, deadline)
            data = result.get("data") if isinstance(result, dict) else None
            if (not isinstance(data, list) or len(data) > 32
                    or any(not isinstance(turn, dict) for turn in data)):
                raise ValueError("thread/turns/list recovery evidence is malformed")
            for turn in data:
                turn_id = _public_uuid7(turn.get("id"), "recovery turn id")
                if turn_id in seen_ids:
                    raise ValueError("thread/turns/list repeated a turn")
                seen_ids.add(turn_id)
                turns.append(turn)
            cursor = result.get("nextCursor")
            if cursor is None:
                return turns
            if (not isinstance(cursor, str) or not cursor
                    or cursor in seen_cursors or not data):
                raise ValueError("thread/turns/list recovery cursor is malformed")
            seen_cursors.add(cursor)
        raise ValueError("thread/turns/list recovery exceeded 4096 pages")

    def _find_recovery_thread(self, recovery: Mapping[str, Any],
                              deadline: float) -> dict[str, Any]:
        marker = recovery.get("thread_source")
        cwd = recovery.get("canonical_cwd")
        if not isinstance(marker, str) or not marker or not isinstance(cwd, str):
            raise ValueError("thread recovery metadata is incomplete")
        cursor = None
        seen_cursors: set[str] = set()
        matches: list[dict[str, Any]] = []
        for _page in range(64):
            params: dict[str, Any] = {
                "cwd": cwd, "sourceKinds": ["appServer"],
                "sortKey": "created_at", "sortDirection": "desc", "limit": 100,
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = self._recovery_request("thread/list", params, deadline)
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, list) or any(
                    not isinstance(item, dict) for item in data):
                raise ValueError("thread/list recovery evidence is malformed")
            matches.extend(
                item for item in data
                if item.get("threadSource") == marker and item.get("cwd") == cwd)
            cursor = result.get("nextCursor")
            if cursor is None:
                break
            if (not isinstance(cursor, str) or not cursor
                    or cursor in seen_cursors):
                raise ValueError("thread/list recovery cursor is malformed")
            seen_cursors.add(cursor)
        else:
            raise ValueError("thread/list recovery exceeded 64 pages")
        if len(matches) != 1:
            raise ValueError(
                f"thread/start public recovery found {len(matches)} exact "
                "operation-tagged threads")
        _public_uuid7(matches[0].get("id"), "recovered thread id")
        return matches[0]

    def _resume_recovery_thread(self, parent_operation_id: str,
                                thread_id: str, deadline: float) -> Any:
        """Load an exact empty thread under its own durable, one-shot intent."""
        operation_id = "queue-recovery-" + hashlib.sha256(
            parent_operation_id.encode("utf-8")).hexdigest()
        operation = {
            "operation_id": operation_id,
            "method": "rpc",
            "payload": {"method": "thread/resume", "params": {
                "threadId": thread_id, "excludeTurns": True,
            }},
            "recovery": {
                "kind": "queue-overflow-thread-resume",
                "parent_operation_id": parent_operation_id,
                "thread_id": thread_id,
            },
        }
        record = self.journal.prepare(operation)
        if record.get("state") in {"observed", "committed"}:
            return record.get("result")
        if record.get("state") != "prepared":
            raise ValueError("thread/resume recovery intent is unresolved")
        self.journal.accept(operation_id)
        try:
            result = self._recovery_request(
                "thread/resume", {"threadId": thread_id,
                                  "excludeTurns": True}, deadline)
        except BaseException as exc:
            self.journal.uncertain(
                operation_id,
                f"thread/resume recovery outcome unknown: {type(exc).__name__}")
            raise
        self.journal.observe(operation_id, result)
        return self.journal.commit(operation_id).get("result")

    def _recover_spawn_queue_overflow(
            self, operation_id: str, deadline: float) -> Any:
        """Adopt a queue-obscured spawn mutation without replaying it."""
        record = self.journal.load(operation_id)
        recovery = record.get("recovery")
        if record.get("state") != "uncertain" or not isinstance(recovery, dict):
            raise ValueError("operation journal is not an uncertain intent")
        self._restart_app_server_after_queue_overflow(deadline)
        public_method = record.get("public_method")
        if public_method == "thread/start":
            candidate = self._find_recovery_thread(recovery, deadline)
            resumed = self._resume_recovery_thread(
                operation_id, candidate["id"], deadline)
            if not isinstance(resumed, dict) or not isinstance(
                    resumed.get("thread"), dict):
                raise ValueError("thread/resume recovery evidence is malformed")
            resumed = dict(resumed)
            resumed["recoveredThreadId"] = candidate["id"]
            adopted = self.journal.adopt_spawn_queue_overflow(
                operation_id, resumed)
            return adopted["result"]
        if public_method == "turn/start":
            thread_id = recovery.get("thread_id")
            cwd = recovery.get("canonical_cwd")
            watermark = recovery.get("history_watermark")
            _public_uuid7(thread_id, "turn recovery thread id")
            if (not isinstance(cwd, str) or not isinstance(watermark, int)
                    or isinstance(watermark, bool) or watermark < 0):
                raise ValueError("turn recovery metadata is incomplete")
            observed = self._recovery_request(
                "thread/read", {"threadId": thread_id, "includeTurns": False},
                deadline)
            thread = observed.get("thread") if isinstance(observed, dict) else None
            if (not isinstance(thread, dict) or thread.get("id") != thread_id
                    or thread.get("cwd") != cwd):
                raise ValueError("thread/read recovery evidence is malformed")
            turns = self._recovery_turns(thread_id, deadline)
            if len(turns) != watermark + 1:
                raise ValueError(
                    "turn/start public recovery did not find exactly one new turn")
            turn = turns[0]
            _public_uuid7(turn.get("id"), "recovered turn id")
            result = {
                "turn": turn, "threadId": thread_id, "canonicalCwd": cwd,
                "historyWatermark": watermark,
                "observedTurnCount": len(turns),
            }
            adopted = self.journal.adopt_spawn_queue_overflow(
                operation_id, result)
            return adopted["result"]
        raise ValueError(
            f"{public_method or 'unknown'} has no safe queue-overflow adoption path")

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
        self._start_app_server(10)
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
            if "id" in message:
                self.approvals.record_request(message)
            elif message.get("method") == "serverRequest/resolved":
                self.approvals.resolve(message)
            else:
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
                    and not self.journal.has_unresolved()
                    and not self.approvals.has_unresolved()):
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
        mutating_operation_id = None
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
                        try:
                            result = self.client.request(
                                payload["method"], payload.get("params", {}),
                                timeout=rpc_timeout)
                        except Exception as exc:
                            if not is_event_queue_overflow(exc):
                                raise
                            # Reads are replayable, but the failed stdio client
                            # is not. Replace it once, then repeat only the read.
                            self._restart_app_server_after_queue_overflow(deadline)
                            assert self.client is not None
                            result = self.client.request(
                                payload["method"], payload.get("params", {}),
                                timeout=_bounded_rpc_timeout(
                                    payload, float(request["operation_timeout"]),
                                    deadline))
                        self._drain_notifications()
                    else:
                        params = payload.get("params")
                        operation_id = request["operation_id"]
                        mutating_operation_id = operation_id
                        try:
                            if not isinstance(params, dict):
                                raise HostRejected(
                                    "public mutation params must be an object")
                            self._authorize_public_mutation(
                                connection, public_method, payload)
                        except HostRejected as exc:
                            # Shape and authentication checks precede acceptance.
                            # A proved rejection must not leave prepared intent.
                            prepared = self.journal.load(operation_id)
                            if prepared.get("state") == "prepared":
                                reason = ("malformed public mutation params"
                                          if not isinstance(params, dict) else
                                          "authentication rejected")
                                self.journal.fail(
                                    operation_id,
                                    f"{reason} before provider acceptance: {exc}")
                            raise
                        record = self.journal.load(operation_id)
                        if record.get("generation") != self.generation:
                            if record.get("state") in {"accepted", "uncertain"}:
                                raise ValueError(
                                    "operation acceptance is uncertain; reconcile "
                                    "before retry (operation belongs to another "
                                    "host generation)")
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
                            restored_history = self.journal.has_restoration_history_for_thread(
                                params.get("threadId"))
                            if ((predecessor is not None or restored_history)
                                    and not self.journal.permits_observed_resume_policy_restore(
                                        operation_id, payload,
                                        request.get("recovery", {}))
                                    and not self.journal.permits_restored_supervisor_continuation(
                                        operation_id, payload,
                                        request.get("recovery", {}))):
                                if predecessor is not None:
                                    reason = "blocked by unresolved predecessor operation"
                                    detail = ("unresolved predecessor operation "
                                              f"{predecessor.get('operation_id')} "
                                              "blocks mutation")
                                else:
                                    reason = "blocked by missing restored predecessor evidence"
                                    detail = reason
                                self.journal.fail(operation_id, reason)
                                raise HostRejected(detail)
                            self.journal.accept(operation_id)
                            recovered = False
                            failure: Exception | None = None
                            try:
                                result = self.client.request(
                                    payload["method"], payload.get("params", {}),
                                    timeout=rpc_timeout)
                            except RequestNotSent as exc:
                                if is_event_queue_overflow(exc):
                                    # The old client failed before this request
                                    # was written, so replacing it and issuing
                                    # the mutation once is not a replay.
                                    self._restart_app_server_after_queue_overflow(
                                        deadline)
                                    assert self.client is not None
                                    try:
                                        result = self.client.request(
                                            payload["method"],
                                            payload.get("params", {}),
                                            timeout=_bounded_rpc_timeout(
                                                payload,
                                                float(request["operation_timeout"]),
                                                deadline))
                                    except Exception as retry_exc:
                                        failure = retry_exc
                                else:
                                    failure = exc
                            except Exception as exc:
                                failure = exc
                            if failure is not None:
                                self.journal.uncertain(
                                    operation_id,
                                    "public mutation outcome unknown: "
                                    f"{type(failure).__name__}")
                                if is_event_queue_overflow(failure):
                                    try:
                                        result = self._recover_spawn_queue_overflow(
                                            operation_id, deadline)
                                    except Exception as recovery_exc:
                                        raise ValueError(
                                            f"{EVENT_QUEUE_OVERFLOW_MESSAGE}; "
                                            "the mutation was not replayed and exact public "
                                            f"recovery failed: {recovery_exc}; increase "
                                            "FLEET_CODEX_EVENT_QUEUE_MAX (maximum 65536) "
                                            "or reduce concurrent lanes") from recovery_exc
                                    # The recovery helper moved the original
                                    # journal entry to observed from exact public
                                    # evidence. Do not observe it a second time.
                                    record = self.journal.load(operation_id)
                                    if record.get("state") != "observed":
                                        raise ValueError(
                                            "queue-overflow recovery did not settle the journal")
                                    result = record.get("result")
                                    self._drain_notifications()
                                    recovered = True
                                else:
                                    raise ValueError(
                                        "public mutation outcome is uncertain") from failure
                            if not recovered:
                                self.journal.observe(operation_id, result)
                        else:
                            raise ValueError("operation journal has unknown state")
                elif method == "public-evidence/read":
                    if not isinstance(payload, dict):
                        raise ValueError("public evidence payload is malformed")
                    self._drain_notifications()
                    result = self.evidence.read(
                        payload.get("thread_id"), payload.get("turn_id"))
                elif method == "approval/list":
                    if not isinstance(payload, dict):
                        raise ValueError("approval list payload is malformed")
                    thread_id = payload.get("thread_id")
                    turn_id = payload.get("turn_id")
                    result = self.approvals.unresolved(
                        thread_id=thread_id, turn_id=turn_id)
                elif method == "approval/respond":
                    if not isinstance(payload, dict):
                        raise ValueError("approval response payload is malformed")
                    assert self.client is not None
                    self._authorize_public_mutation(
                        connection, "approval/respond", {"params": {
                            "threadId": payload.get("thread_id")}})
                    record, public_response = self.approvals.begin_response(
                        payload.get("request_id"), payload.get("thread_id"),
                        payload.get("turn_id"), payload.get("decision"))
                    try:
                        self.client.respond(record["request_id"], public_response)
                    except BaseException as exc:
                        self.approvals.mark_uncertain(
                            record, f"provider response write uncertain: {type(exc).__name__}")
                        raise ValueError(
                            "approval response consumption is uncertain; it will not be retried") from exc
                    current = self.approvals.mark_responded(record)
                    # A response has no JSON-RPC acknowledgement. Observe the public
                    # resolved notification when it is promptly available, but never
                    # replay merely because the notification is delayed or lost.
                    settle_deadline = min(deadline, time.monotonic() + 1.0)
                    while (current.get("state") == "responded"
                           and time.monotonic() < settle_deadline):
                        self._drain_notifications()
                        candidates = [item for item in self.approvals.records()
                                      if item.get("key") == current.get("key")]
                        current = candidates[0] if len(candidates) == 1 else current
                        if current.get("state") != "responded":
                            break
                        time.sleep(0.01)
                    result = {
                        "request_id": current.get("request_id"),
                        "thread_id": current.get("thread_id"),
                        "turn_id": current.get("turn_id"),
                        "state": current.get("state"),
                    }
                elif method == "host/shutdown":
                    result = {"stopping": True}
                    should_stop = True
                else:
                    raise ValueError("unknown host method")
                response = _response(request, ok=True, result=result)
        except (UnicodeError, json.JSONDecodeError, ValueError, OSError,
                EOFError, TimeoutError,
                FleetCliError) as exc:
            if mutating_operation_id is not None:
                try:
                    current = self.journal.load(mutating_operation_id)
                    if current.get("state") == "accepted":
                        self.journal.uncertain(
                            mutating_operation_id,
                            "post-acceptance host failure: "
                            f"{type(exc).__name__}")
                except (OSError, ValueError, FleetCliError):
                    # The client also reads the journal state. A failed repair
                    # must never turn an accepted write into a rejection.
                    pass
            response = _response(request, ok=False, error=str(exc)[:300])
        try:
            encoded = json.dumps(response, separators=(",", ":"),
                                 sort_keys=True).encode("utf-8")
            if len(encoded) > MAX_IPC_BYTES:
                encoded = json.dumps(_response(
                    request, ok=False,
                    error="host response exceeds MAX_IPC_BYTES; page the request"),
                    separators=(",", ":"), sort_keys=True).encode("utf-8")
            _send_frame(connection, encoded, deadline)
        except (OSError, EOFError, TimeoutError, ValueError):
            pass
        finally:
            connection.close()
        return should_stop

    def _authorize_public_mutation(self, connection: socket.socket,
                                   public_method: str,
                                   payload: Mapping[str, Any]) -> None:
        """Authorize each provider mutation from kernel peer evidence.

        A home without an external Interface claim retains the already reviewed
        supervisor/worker behavior.  Once an Interface is registered, the host
        requires the current process-bound claim for Interface calls.  The
        exact external Interface thread is always an observation target only.
        """
        params = payload.get("params", {})
        target = params.get("threadId") if isinstance(params, dict) else None
        approvals = getattr(self, "approvals", None)
        if (approvals is not None
                and any(record.get("state") == "unknown"
                        for record in approvals.unresolved())):
            raise HostRejected(
                "unknown blocking server request freezes provider mutations")
        claim = read_interface_claim(self.home)
        if claim is None:
            return
        peer_pid, peer_uid = _ipc_peer_credentials(connection)
        source = codex_process_source(peer_pid)
        if peer_uid != os.getuid() or source.get("uid") != peer_uid:
            raise HostRejected("Codex IPC peer uid does not match the host owner")
        if not interface_source_matches(claim, source):
            if not self._exact_home_supervisor_source(source):
                raise HostRejected(
                    "Codex IPC peer does not hold the current Interface or "
                    "exact-home supervisor claim")
        if target == claim.get("thread_id"):
            raise HostRejected(
                f"external Interface thread is observe-only; refusing {public_method}")

    def _exact_home_supervisor_source(self, source: Mapping[str, Any]) -> bool:
        """Allow the genuine current supervisor without weakening cwd binding."""
        path = self.home / "supervisor" / "INCARNATION"
        try:
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid() or info.st_size > 64 * 1024):
                return False
            claim = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(claim, dict):
            return False
        holder = claim.get("holder")
        if (claim.get("provider") != "codex"
                or claim.get("state") not in {"pending", "held", "activating"}
                or not isinstance(holder, dict)
                or holder.get("provider") != "codex"):
            return False
        try:
            source_cwd = Path(source.get("ancestor_cwd", "")).resolve(strict=True)
        except OSError:
            return False
        return (holder.get("thread_id") == source.get("thread_id")
                and source_cwd == self.home)

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
