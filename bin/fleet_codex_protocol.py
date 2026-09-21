"""Bounded public-protocol client for ``codex app-server`` stdio.

This module owns transport mechanics only.  It deliberately knows nothing
about Fleet homes, registry rows, supervisor claims, or recovery policy.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

from fleet_errors import FleetCliError


DEFAULT_MAX_FRAME_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024
DEFAULT_MAX_EVENTS = 1024


class ProtocolViolation(FleetCliError):
    """The app-server peer sent a malformed or contradictory public frame."""


class TransportLost(FleetCliError):
    """The app-server stdio transport ended before an operation completed."""


@dataclass
class _Pending:
    event: threading.Event
    result: Any = None
    error: BaseException | None = None


_SECRET_RE = re.compile(
    r"(?i)\b(secret|token|authorization|prompt)\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")


def _redact_text(value: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)


def _frame(value: Mapping[str, Any]) -> bytes:
    try:
        return (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation("outbound app-server message is not JSON-serializable") from exc


class AppServerClient:
    """One ordered JSON-lines connection to one public Codex app-server."""

    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        max_frame_bytes: int,
        max_stderr_bytes: int,
        max_events: int,
    ) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise ValueError("app-server process must have stdin/stdout/stderr pipes")
        if min(max_frame_bytes, max_stderr_bytes, max_events) <= 0:
            raise ValueError("protocol bounds must be positive")
        self._process = process
        self._max_frame_bytes = max_frame_bytes
        self._max_stderr_bytes = max_stderr_bytes
        self._pending: dict[int, _Pending] = {}
        self._retired_ids: set[int] = set()
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_events)
        self._state_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._stderr = bytearray()
        self._next_id = 1
        self.initialize_result: Any = None
        self._fatal_error: BaseException | None = None
        self._closing = False
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name="fleet-codex-stdout", daemon=True)
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="fleet-codex-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def process_id(self) -> int:
        """Return the owned app-server PID for exact lifecycle evidence."""
        return self._process.pid

    @classmethod
    def start(
        cls,
        command: Sequence[str] = ("codex", "app-server", "--listen", "stdio://"),
        *,
        cwd: os.PathLike[str] | str | None = None,
        env: Mapping[str, str] | None = None,
        initialize_params: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
        max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
        max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> "AppServerClient":
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("app-server command must contain non-empty strings")
        child_env = dict(os.environ if env is None else env)
        child_env.pop("CLAUDE_CODE_SESSION_ID", None)
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=child_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        client = cls(
            process,
            max_frame_bytes=max_frame_bytes,
            max_stderr_bytes=max_stderr_bytes,
            max_events=max_events,
        )
        params = dict(initialize_params or {
            "clientInfo": {"name": "fleet", "version": "1"},
        })
        try:
            client.initialize_result = client.request("initialize", params, timeout=timeout)
            client._write({"method": "initialized"})
        except BaseException:
            client.close()
            raise
        return client

    @property
    def next_request_id(self) -> int:
        with self._state_lock:
            return self._next_id

    def request(self, method: str, params: Any, timeout: float) -> Any:
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        pending = _Pending(threading.Event())
        with self._state_lock:
            if self._fatal_error is not None:
                raise self._fatal_error
            if self._closing:
                raise TransportLost("app-server client is closed")
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = pending
        try:
            self._write({"id": request_id, "method": method, "params": params})
        except BaseException:
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(timeout):
            with self._state_lock:
                if self._pending.pop(request_id, None) is not None:
                    self._retired_ids.add(request_id)
                    if len(self._retired_ids) > 4096:
                        self._retired_ids = set(sorted(self._retired_ids)[-2048:])
            raise TimeoutError(f"app-server request {request_id} timed out")
        if pending.error is not None:
            raise pending.error
        return pending.result

    def respond(self, request_id: str | int, result: Any) -> None:
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            raise ValueError("server request id must be a string or integer")
        self._write({"id": request_id, "result": result})

    def notifications(self) -> Iterator[dict[str, Any]]:
        """Drain currently queued server notifications and server requests."""
        while True:
            try:
                yield self._events.get_nowait()
            except queue.Empty:
                return

    def stderr_tail(self) -> str:
        """Return bounded, redacted app-server diagnostics."""
        with self._stderr_lock:
            return bytes(self._stderr).decode("utf-8", errors="replace")

    def close(self) -> None:
        with self._state_lock:
            if self._closing:
                return
            self._closing = True
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.error = TransportLost("app-server client closed")
            waiter.event.set()
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        except OSError:
            pass
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1)
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)

    def _write(self, value: Mapping[str, Any]) -> None:
        data = _frame(value)
        if len(data) > self._max_frame_bytes:
            raise ProtocolViolation(
                f"outbound app-server frame exceeds {self._max_frame_bytes} bytes")
        with self._write_lock:
            with self._state_lock:
                fatal = self._fatal_error
                closing = self._closing
            if fatal is not None:
                raise fatal
            if closing:
                raise TransportLost("app-server client is closed")
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(data)
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                failure = TransportLost("app-server stdin is unavailable")
                self._fail(failure)
                raise failure from exc

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                line = self._process.stdout.readline(self._max_frame_bytes + 2)
                if not line:
                    with self._state_lock:
                        closing = self._closing
                    if not closing:
                        self._fail(TransportLost("app-server stdout reached EOF"))
                    return
                if len(line) > self._max_frame_bytes or not line.endswith(b"\n"):
                    self._fail(ProtocolViolation(
                        f"inbound app-server frame exceeds {self._max_frame_bytes} bytes"))
                    return
                try:
                    decoded = line.decode("utf-8")
                    message = json.loads(decoded)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._fail(ProtocolViolation("app-server sent malformed UTF-8 JSON"))
                    return
                if not isinstance(message, dict):
                    self._fail(ProtocolViolation("app-server frame must be a JSON object"))
                    return
                if not self._accept_message(message):
                    return
        except (OSError, ValueError):
            with self._state_lock:
                closing = self._closing
            if not closing:
                self._fail(TransportLost("app-server stdout read failed"))

    def _accept_message(self, message: dict[str, Any]) -> bool:
        has_id = "id" in message
        has_method = isinstance(message.get("method"), str) and bool(message.get("method"))
        has_result = "result" in message
        has_error = "error" in message
        if has_id and not has_method and has_result != has_error:
            request_id = message["id"]
            if not isinstance(request_id, int) or isinstance(request_id, bool):
                self._fail(ProtocolViolation("app-server response id is not a Fleet integer"))
                return False
            with self._state_lock:
                pending = self._pending.pop(request_id, None)
                retired = request_id in self._retired_ids
                if retired:
                    self._retired_ids.discard(request_id)
            if retired:
                return True
            if pending is None:
                self._fail(ProtocolViolation("app-server response has an unknown request id"))
                return False
            if has_error:
                error = message.get("error")
                if not isinstance(error, dict) or not isinstance(error.get("message"), str):
                    pending.error = ProtocolViolation("app-server error response is malformed")
                else:
                    code = error.get("code")
                    pending.error = ProtocolViolation(
                        f"app-server request failed ({code}): {_redact_text(error['message'])}")
            else:
                pending.result = message.get("result")
            pending.event.set()
            return True
        if has_method and not has_result and not has_error:
            try:
                self._events.put_nowait(message)
            except queue.Full:
                self._fail(ProtocolViolation("app-server event queue exceeded its bound"))
                return False
            return True
        self._fail(ProtocolViolation("app-server sent an invalid message shape"))
        return False

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            while True:
                data = self._process.stderr.read(4096)
                if not data:
                    return
                text = data.decode("utf-8", errors="replace")
                redacted = _redact_text(text).encode("utf-8")
                with self._stderr_lock:
                    room = self._max_stderr_bytes - len(self._stderr)
                    if room > 0:
                        self._stderr.extend(redacted[:room])
        except OSError:
            return

    def _fail(self, error: BaseException) -> None:
        with self._state_lock:
            if self._fatal_error is not None or self._closing:
                return
            self._fatal_error = error
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.error = error
            waiter.event.set()


__all__ = ["AppServerClient", "ProtocolViolation", "TransportLost"]
