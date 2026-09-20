"""Synchronous client for Fleet's authenticated, per-home Codex host."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import socket
import stat
import struct
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from fleet_errors import FleetCliError


IPC_PROTOCOL_VERSION = 1
MAX_IPC_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
HOST_LOCK_STALE_SECONDS = 30.0
HOST_HEARTBEAT_STALE_SECONDS = 3.0
IPC_AUTH_CHALLENGE_BYTES = 32
MAX_OPERATION_TIMEOUT_SECONDS = 120.0
SCHEMA_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "codex_app_server" / "0.155.1" / "manifest.json"
)


class UnsafeHostState(FleetCliError):
    """A fixed host path failed its ownership, mode, type, or content check."""


class HostUnavailable(FleetCliError):
    """The authenticated home host could not be reached or started."""


class HostRejected(FleetCliError):
    """The home host refused an invalid or unauthorized operation."""


@dataclass(frozen=True)
class CodexObservation:
    operation_id: str
    generation: str
    payload_digest: str
    result: Any


@dataclass(frozen=True)
class ReconcileReport:
    inspected: int
    observed: int
    uncertain: int
    failed: int
    page: bool
    retried_operations: int = 0


_MUTATING_PUBLIC_METHODS = frozenset({
    "thread/start", "turn/start", "turn/steer", "turn/interrupt",
})
_SENSITIVE_KEYS = frozenset({
    "content", "input", "instructions", "message", "prompt", "reasoning",
    "secret", "text", "transcript",
})


def _canonical_home(home: Path) -> Path:
    lexical = Path(os.path.abspath(os.fspath(home)))
    current = Path(lexical.anchor)
    for part in lexical.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise UnsafeHostState(f"cannot inspect Fleet home path {current}: {exc}") from exc
        if stat.S_ISLNK(info.st_mode):
            raise UnsafeHostState(f"Fleet home path contains a symlink: {current}")
    try:
        resolved = Path(home).resolve(strict=True)
    except OSError as exc:
        raise UnsafeHostState(f"Fleet home does not resolve: {home}") from exc
    if not resolved.is_dir():
        raise UnsafeHostState(f"Fleet home is not a directory: {resolved}")
    return resolved


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _require_owner(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise UnsafeHostState(f"cannot inspect Codex host path {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise UnsafeHostState(f"Codex host path is a symlink: {path}")
    if os.name != "nt" and info.st_uid != os.getuid():
        raise UnsafeHostState(f"Codex host path has the wrong owner: {path}")
    return info


def _require_directory(path: Path, *, create: bool = False) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        if not create:
            raise UnsafeHostState(f"Codex host directory is missing: {path}")
        try:
            path.mkdir(parents=True, mode=0o700)
        except FileExistsError:
            pass
        else:
            if os.name != "nt":
                path.chmod(0o700)
    info = _require_owner(path)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeHostState(f"Codex host path is not a directory: {path}")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o700:
        raise UnsafeHostState(f"Codex host directory mode is not 0700: {path}")


def _require_regular(path: Path, *, mode: int = 0o600) -> os.stat_result:
    info = _require_owner(path)
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeHostState(f"Codex host path is not a regular file: {path}")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) != mode:
        raise UnsafeHostState(
            f"Codex host file mode is not {mode:04o}: {path}")
    return info


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = _require_regular(path)
    if info.st_size > MAX_METADATA_BYTES:
        raise UnsafeHostState(f"Codex host metadata exceeds {MAX_METADATA_BYTES} bytes: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UnsafeHostState(f"Codex host metadata is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise UnsafeHostState(f"Codex host metadata must be an object: {path}")
    return value


def _read_key(path: Path) -> tuple[str, bytes]:
    info = _require_regular(path)
    if info.st_size > 256:
        raise UnsafeHostState(f"Codex host key is oversized: {path}")
    try:
        encoded = path.read_text(encoding="ascii").strip()
        decoded = base64.b64decode(encoded, validate=True)
    except (OSError, UnicodeError, ValueError) as exc:
        raise UnsafeHostState(f"Codex host key is invalid: {path}") from exc
    if len(decoded) != 32:
        raise UnsafeHostState(f"Codex host key has invalid length: {path}")
    return encoded, decoded


def _create_key(path: Path) -> tuple[str, bytes]:
    encoded = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(path), flags, 0o600)
    try:
        os.write(fd, encoded.encode("ascii"))
    finally:
        os.close(fd)
    if os.name != "nt":
        path.chmod(0o600)
    return _read_key(path)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(data) > MAX_METADATA_BYTES:
        raise UnsafeHostState("Codex host metadata exceeds its bound")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if os.name != "nt":
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _validate_fixed_paths(state_dir: Path) -> None:
    if os.name == "nt":
        raise HostUnavailable(
            "native Codex hosting is unsupported on Windows until owner-only "
            "named-pipe DACLs have cross-user acceptance proof")
    home = state_dir.parent.parent
    for parent in (home, home / "state"):
        info = _require_owner(parent)
        if not stat.S_ISDIR(info.st_mode):
            raise UnsafeHostState(f"Codex host parent is not a directory: {parent}")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    home_fd = state_fd = codex_fd = None
    try:
        home_fd = os.open(str(home), directory_flags)
        state_fd = os.open("state", directory_flags, dir_fd=home_fd)
        try:
            os.mkdir("codex", mode=0o700, dir_fd=state_fd)
        except FileExistsError:
            pass
        codex_fd = os.open("codex", directory_flags, dir_fd=state_fd)
        info = os.fstat(codex_fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise UnsafeHostState(
                f"Codex host directory lacks owner-only confinement: {state_dir}")
    except OSError as exc:
        raise UnsafeHostState(
            f"cannot create Codex state below verified home {home}: {exc}") from exc
    finally:
        for descriptor in (codex_fd, state_fd, home_fd):
            if descriptor is not None:
                os.close(descriptor)
    _require_directory(state_dir)
    for path in (state_dir / "host.json", state_dir / "host.key",
                 state_dir / "codex-host.lock"):
        if path.exists() or path.is_symlink():
            _require_regular(path)
    endpoint = state_dir / "ipc.sock"
    if endpoint.exists() or endpoint.is_symlink():
        info = _require_owner(endpoint)
        if os.name != "nt" and not stat.S_ISSOCK(info.st_mode):
            raise UnsafeHostState(f"Codex host endpoint has unsafe type: {endpoint}")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600:
            raise UnsafeHostState(f"Codex host endpoint mode is not 0600: {endpoint}")


@contextmanager
def _host_lock(path: Path, timeout: float) -> Iterator[None]:
    deadline = time.monotonic() + timeout
    identity = _process_identity(os.getpid())
    token = (json.dumps({"pid": os.getpid(), "identity": identity,
                         "nonce": uuid.uuid4().hex}, sort_keys=True) + "\n").encode("ascii")
    while True:
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, token)
            os.close(fd)
            if os.name != "nt":
                path.chmod(0o600)
            break
        except FileExistsError:
            info = _require_regular(path)
            if (time.time() - info.st_mtime > HOST_LOCK_STALE_SECONDS
                    and not _lock_holder_is_live(path)):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise HostUnavailable(f"timed out waiting for Codex host lock: {path}")
            time.sleep(0.025)
    try:
        yield
    finally:
        try:
            if path.read_bytes() == token:
                path.unlink()
        except OSError:
            pass


def _process_identity(pid: int) -> str | None:
    """Return a PID-reuse-resistant Linux identity when public procfs exposes one."""
    if os.name == "nt":
        return None
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        return fields[21]
    except (OSError, IndexError, UnicodeError):
        return None


def _lock_holder_is_live(path: Path) -> bool:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
        pid = value.get("pid")
        identity = value.get("identity")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return True
    if not isinstance(pid, int) or pid <= 0:
        return True
    current = _process_identity(pid)
    if current is not None:
        return isinstance(identity, str) and hmac.compare_digest(current, identity)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Codex host IPC deadline expired")
    return remaining


def _recv_exact(connection: socket.socket, size: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        connection.settimeout(_remaining(deadline))
        chunk = connection.recv(remaining)
        if not chunk:
            raise EOFError("Codex host IPC peer disconnected")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_frame(connection: socket.socket, deadline: float,
                maximum: int = MAX_IPC_BYTES) -> bytes:
    size = struct.unpack("!I", _recv_exact(connection, 4, deadline))[0]
    if size > maximum:
        raise ValueError(f"Codex host IPC frame exceeds {maximum} bytes")
    return _recv_exact(connection, size, deadline)


def _send_frame(connection: socket.socket, payload: bytes, deadline: float) -> None:
    if len(payload) > MAX_IPC_BYTES:
        raise ValueError(f"Codex host IPC frame exceeds {MAX_IPC_BYTES} bytes")
    connection.settimeout(_remaining(deadline))
    connection.sendall(struct.pack("!I", len(payload)) + payload)


def _connect_authenticated(endpoint: str, authkey: bytes,
                           deadline: float) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(_remaining(deadline))
        connection.connect(endpoint)
        challenge = _recv_frame(connection, deadline, IPC_AUTH_CHALLENGE_BYTES)
        if len(challenge) != IPC_AUTH_CHALLENGE_BYTES:
            raise HostUnavailable("Codex host sent an invalid authentication challenge")
        _send_frame(connection, hmac.digest(authkey, challenge, "sha256"), deadline)
        if _recv_frame(connection, deadline, 16) != b"OK":
            raise HostUnavailable("Codex host authentication failed")
        return connection
    except BaseException:
        connection.close()
        raise


def _digest(method: str, payload: Any) -> str:
    canonical = json.dumps(
        {"method": method, "payload": payload},
        separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _public_evidence(value: Any, key: str | None = None) -> Any:
    if key is not None and key.casefold() in _SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(name): _public_evidence(item, str(name))
                for name, item in value.items()}
    if isinstance(value, list):
        return [_public_evidence(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return "<unsupported>"


def _public_method(method: str, payload: Any) -> str | None:
    if method != "rpc" or not isinstance(payload, dict):
        return None
    candidate = payload.get("method")
    return candidate if candidate in _MUTATING_PUBLIC_METHODS else None


class OperationJournal:
    """Owner-only durable intent and public observation for Codex mutations."""

    def __init__(self, home: Path, generation: str) -> None:
        self.home = _canonical_home(home)
        self.generation = generation
        self.state_dir = self.home / "state" / "codex"
        _require_directory(self.state_dir, create=True)
        self.directory = self.state_dir / "operations"
        _require_directory(self.directory, create=True)

    @staticmethod
    def _validate_id(operation_id: object) -> str:
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            raise ValueError("operation_id must be a non-empty bounded string")
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
               for character in operation_id):
            raise ValueError("operation_id contains unsafe path characters")
        return operation_id

    def path(self, operation_id: object) -> Path:
        return self.directory / f"{self._validate_id(operation_id)}.json"

    def load(self, operation_id: object) -> dict[str, Any]:
        path = self.path(operation_id)
        value = _read_json(path)
        if value is None:
            raise HostRejected(f"operation {operation_id} has no prepared intent")
        if value.get("operation_id") != operation_id or value.get("home") != str(self.home):
            raise UnsafeHostState(f"operation journal identity mismatch: {path}")
        return value

    def prepare(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        operation_id = self._validate_id(operation.get("operation_id"))
        method = operation.get("method")
        payload = operation.get("payload", {})
        recovery = operation.get("recovery", {})
        if not isinstance(method, str) or not method:
            raise ValueError("operation method must be a non-empty string")
        if not isinstance(recovery, dict):
            raise ValueError("operation recovery metadata must be an object")
        digest = _digest(method, payload)
        record = {
            "schema": 1,
            "operation_id": operation_id,
            "home": str(self.home),
            "generation": self.generation,
            "method": method,
            "public_method": _public_method(method, payload),
            "payload_digest": digest,
            "recovery": _public_evidence(recovery),
            "state": "prepared",
            "prepared_at": time.time(),
        }
        path = self.path(operation_id)
        data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = self.load(operation_id)
            if existing.get("payload_digest") != digest:
                raise HostRejected(
                    f"operation {operation_id} reused with a different payload digest")
            if existing.get("method") != method or existing.get("recovery") != record["recovery"]:
                raise HostRejected(
                    f"operation {operation_id} reused with different immutable intent")
            if existing.get("generation") != self.generation:
                raise HostRejected(
                    f"operation {operation_id} belongs to another host generation")
            return existing
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if os.name != "nt":
            path.chmod(0o600)
            directory_fd = os.open(str(self.directory), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return record

    def _transition(self, operation_id: str, allowed: set[str], state: str,
                    **updates: Any) -> dict[str, Any]:
        record = self.load(operation_id)
        if record.get("state") == state:
            return record
        if record.get("state") not in allowed:
            raise HostRejected(
                f"operation {operation_id} cannot move from {record.get('state')} to {state}")
        record.update(updates)
        record["state"] = state
        record[f"{state}_at"] = time.time()
        _atomic_json(self.path(operation_id), record)
        return record

    def accept(self, operation_id: str) -> dict[str, Any]:
        return self._transition(operation_id, {"prepared"}, "accepted")

    def observe(self, operation_id: str, result: Any) -> dict[str, Any]:
        return self._transition(
            operation_id, {"accepted"}, "observed",
            result=_public_evidence(result))

    def commit(self, operation_id: str) -> dict[str, Any]:
        return self._transition(operation_id, {"observed"}, "committed")

    def uncertain(self, operation_id: str, reason: str) -> dict[str, Any]:
        return self._transition(
            operation_id, {"accepted", "prepared"}, "uncertain",
            reason=str(reason)[:500])

    def fail(self, operation_id: str, reason: str) -> dict[str, Any]:
        return self._transition(
            operation_id, {"prepared"}, "failed", reason=str(reason)[:500])

    def records(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.directory.glob("*.json")):
            _require_regular(path)
            value = _read_json(path)
            if value is None or value.get("operation_id") != path.stem:
                raise UnsafeHostState(f"operation journal filename mismatch: {path}")
            records.append(value)
        return records

    def has_unresolved(self) -> bool:
        return any(record.get("state") in {
            "prepared", "accepted", "observed", "uncertain"}
                   for record in self.records())

    def unresolved_predecessor(self, operation_id: str) -> dict[str, Any] | None:
        """Return unfinished intent that must settle before a fresh mutation."""
        for record in self.records():
            if (record.get("operation_id") != operation_id
                    and record.get("state") in {
                        "prepared", "accepted", "observed", "uncertain"}):
                return record
        return None


class CodexHostClient:
    def __init__(self, home: Path, metadata: Mapping[str, Any], encoded_key: str,
                 authkey: bytes) -> None:
        self.home = home
        self.state_dir = home / "state" / "codex"
        self.metadata_path = self.state_dir / "host.json"
        self.key_path = self.state_dir / "host.key"
        self.generation = str(metadata["generation"])
        self.schema_digest = metadata.get("schema_digest")
        self.protocol_version = metadata["codex_protocol_version"]
        self._endpoint = metadata["endpoint"]
        self._transport = metadata["transport"]
        self._encoded_key = encoded_key
        self._authkey = authkey
        self._pid = metadata["pid"]
        self._process_identity = metadata["process_identity"]
        self._launched_process: subprocess.Popen[Any] | None = None

    @classmethod
    def connect_existing(cls, home: Path) -> "CodexHostClient":
        """Attach to reviewed exact-home metadata without starting a host."""
        home = _canonical_home(home)
        state_dir = home / "state" / "codex"
        _validate_fixed_paths(state_dir)
        existing = cls._existing(home)
        if existing is None:
            raise HostUnavailable("no ready Codex host exists for this Fleet home")
        return existing

    @classmethod
    def ensure(
        cls,
        home: Path,
        *,
        app_server_command: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        ready_timeout: float = 10.0,
        idle_timeout: float = 0.0,
    ) -> "CodexHostClient":
        home = _canonical_home(home)
        state_dir = home / "state" / "codex"
        _validate_fixed_paths(state_dir)
        existing = cls._existing(home)
        if existing is not None and existing._ping(0.5):
            return existing
        if (existing is not None
                and (not existing._metadata_stale() or existing._owner_live())):
            raise HostUnavailable("Codex host is busy or unresponsive; refusing replacement")

        with _host_lock(state_dir / "codex-host.lock", ready_timeout):
            _validate_fixed_paths(state_dir)
            existing = cls._existing(home)
            if existing is not None and existing._ping(0.5):
                return existing
            if (existing is not None
                    and (not existing._metadata_stale() or existing._owner_live())):
                raise HostUnavailable("Codex host is busy or unresponsive; refusing replacement")
            key_path = state_dir / "host.key"
            if key_path.exists():
                _read_key(key_path)
            else:
                _create_key(key_path)
            endpoint, family = _endpoint_for(home, state_dir)
            if family == "AF_UNIX":
                endpoint_path = Path(endpoint)
                if endpoint_path.exists() or endpoint_path.is_symlink():
                    info = _require_owner(endpoint_path)
                    if not stat.S_ISSOCK(info.st_mode):
                        raise UnsafeHostState(f"Codex host endpoint has unsafe type: {endpoint_path}")
                    endpoint_path.unlink()
            generation = str(uuid.uuid4())
            command = list(app_server_command or
                           ["codex", "app-server", "--listen", "stdio://"])
            host_command = [
                sys.executable,
                str(Path(__file__).with_name("fleet_codex_host.py")),
                "--home", str(home),
                "--generation", generation,
                "--endpoint", endpoint,
                "--transport", family,
                "--app-server-command-json", json.dumps(command),
                "--schema-manifest", str(SCHEMA_MANIFEST),
                "--schema-command-json", json.dumps(["codex"]),
                "--idle-timeout", str(idle_timeout),
            ]
            child_env = dict(os.environ if env is None else env)
            child_env.pop("CLAUDE_CODE_SESSION_ID", None)
            popen_args: dict[str, Any] = {
                "cwd": str(home),
                "env": child_env,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_args["creationflags"] = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0))
            else:
                popen_args["start_new_session"] = True
            process = subprocess.Popen(host_command, **popen_args)
            deadline = time.monotonic() + ready_timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise HostUnavailable(
                        f"Codex host exited before ready ({process.returncode})")
                candidate = cls._existing(home)
                if (candidate is not None and candidate.generation == generation
                        and candidate._ping(0.25)):
                    candidate._launched_process = process
                    return candidate
                time.sleep(0.025)
            raise HostUnavailable("timed out waiting for Codex host readiness")

    @classmethod
    def _existing(cls, home: Path) -> "CodexHostClient | None":
        state_dir = home / "state" / "codex"
        metadata = _read_json(state_dir / "host.json")
        key_path = state_dir / "host.key"
        if metadata is None:
            if key_path.exists() or key_path.is_symlink():
                _read_key(key_path)
            return None
        manifest = json.loads(SCHEMA_MANIFEST.read_text(encoding="utf-8"))
        endpoint, transport = _endpoint_for(home, state_dir)
        required = {
            "schema", "home", "generation", "endpoint", "transport", "ready",
            "ipc_protocol_version", "codex_protocol_version", "codex_version",
            "schema_digest", "heartbeat",
            "pid", "process_identity",
        }
        if not required.issubset(metadata) or metadata.get("home") != str(home):
            raise UnsafeHostState("Codex host metadata has wrong home or missing fields")
        try:
            generation = uuid.UUID(metadata["generation"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise UnsafeHostState("Codex host metadata has invalid generation") from exc
        expected = {
            "schema": 1,
            "endpoint": endpoint,
            "transport": transport,
            "ipc_protocol_version": IPC_PROTOCOL_VERSION,
            "codex_protocol_version": manifest["protocol_version"],
            "codex_version": manifest["codex_version"],
            "schema_digest": manifest["schema_sha256"],
        }
        if generation.version != 4 or str(generation) != metadata["generation"]:
            raise UnsafeHostState("Codex host metadata generation is not canonical UUIDv4")
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise UnsafeHostState("Codex host metadata does not match the reviewed endpoint contract")
        if not isinstance(metadata.get("heartbeat"), (int, float)):
            raise UnsafeHostState("Codex host metadata has invalid heartbeat")
        if (not isinstance(metadata.get("pid"), int)
                or metadata["pid"] <= 0
                or not isinstance(metadata.get("process_identity"), str)
                or not metadata["process_identity"]):
            raise UnsafeHostState("Codex host metadata has invalid process identity")
        if metadata.get("ready") is not True:
            return None
        encoded, decoded = _read_key(key_path)
        return cls(home, metadata, encoded, decoded)

    def _metadata_stale(self) -> bool:
        metadata = _read_json(self.metadata_path)
        heartbeat = metadata.get("heartbeat") if metadata else None
        return (not isinstance(heartbeat, (int, float))
                or time.time() - heartbeat > HOST_HEARTBEAT_STALE_SECONDS)

    def _owner_live(self) -> bool:
        current = _process_identity(self._pid)
        if current is not None:
            return hmac.compare_digest(current, self._process_identity)
        try:
            os.kill(self._pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True

    def _ping(self, timeout: float) -> bool:
        try:
            observation = self.call({"operation_id": f"ping-{uuid.uuid4()}",
                                     "method": "ping", "payload": {}}, timeout=timeout)
            return observation.result == {
                "generation": self.generation,
                "home": str(self.home),
                "endpoint": self._endpoint,
                "transport": self._transport,
                "ipc_protocol_version": IPC_PROTOCOL_VERSION,
                "codex_protocol_version": self.protocol_version,
                "schema_digest": self.schema_digest,
            }
        except (OSError, EOFError, TimeoutError, HostUnavailable, HostRejected):
            return False

    def call(self, operation: Mapping[str, Any], timeout: float) -> CodexObservation:
        if (not isinstance(timeout, (int, float)) or isinstance(timeout, bool)
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be a positive finite number")
        operation_timeout = min(float(timeout), MAX_OPERATION_TIMEOUT_SECONDS)
        operation_id = operation.get("operation_id")
        method = operation.get("method")
        payload = operation.get("payload", {})
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            raise ValueError("operation_id must be a non-empty bounded string")
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        digest = _digest(method, payload)
        public_method = _public_method(method, payload)
        if public_method is not None:
            prepared = OperationJournal(self.home, self.generation).prepare(operation)
            if prepared.get("payload_digest") != digest:
                raise HostRejected(
                    f"operation {operation_id} has a conflicting payload digest")
        envelope = {
            "protocol_version": IPC_PROTOCOL_VERSION,
            "host_generation": self.generation,
            "operation_id": operation_id,
            "method": method,
            "fleet_home": str(self.home),
            "payload": payload,
            "payload_digest": digest,
            "recovery": operation.get("recovery", {}),
            "secret": self._encoded_key,
            "operation_timeout": operation_timeout,
        }
        encoded = json.dumps(envelope, separators=(",", ":"),
                             sort_keys=True, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_IPC_BYTES:
            raise ValueError(f"Codex host request exceeds {MAX_IPC_BYTES} bytes")
        deadline = time.monotonic() + operation_timeout
        try:
            connection = _connect_authenticated(
                self._endpoint, self._authkey, deadline)
        except (OSError, EOFError, TimeoutError, ValueError, HostUnavailable) as exc:
            raise HostUnavailable("authenticated Codex host connection failed") from exc
        try:
            _send_frame(connection, encoded, deadline)
            raw = _recv_frame(connection, deadline)
        except (OSError, EOFError, TimeoutError, ValueError) as exc:
            raise HostUnavailable("Codex host response was lost") from exc
        finally:
            connection.close()
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HostUnavailable("Codex host returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise HostUnavailable("Codex host response is not an object")
        expected = {
            "operation_id": operation_id,
            "host_generation": self.generation,
            "fleet_home": str(self.home),
            "payload_digest": digest,
        }
        if any(response.get(key) != value for key, value in expected.items()):
            raise HostUnavailable("Codex host response correlation mismatch")
        if response.get("ok") is not True:
            raise HostRejected(str(response.get("error") or "Codex host rejected operation"))
        return CodexObservation(operation_id, self.generation, digest,
                                response.get("result"))

    def commit(self, operation_id: str) -> None:
        OperationJournal(self.home, self.generation).commit(operation_id)

    def wait_for_exit(self, timeout: float) -> bool:
        """Wait for a host this process launched, reaping its process handle."""
        if self._launched_process is None:
            return False
        try:
            self._launched_process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True


def _endpoint_for(home: Path, state_dir: Path) -> tuple[str, str]:
    if os.name == "nt":
        raise HostUnavailable(
            "native Codex hosting is unsupported on Windows until owner-only "
            "named-pipe DACLs have cross-user acceptance proof")
    return str(state_dir / "ipc.sock"), "AF_UNIX"


def _uncertainty_reason(observation: Mapping[str, Any]) -> str | None:
    if observation.get("verdict") != "observed":
        return "unknown transport or public observation"
    if observation.get("schema_matches") is not True:
        return "schema mismatch"
    if observation.get("cwd_matches") is not True:
        return "wrong cwd"
    if observation.get("thread_status") == "systemError":
        return "system error"
    new_turns = observation.get("new_turns", 0)
    if not isinstance(new_turns, int) or new_turns > 1:
        return "multiple new turns"
    if not all(observation.get(name) is True for name in
               ("read_complete", "turns_complete", "items_complete")):
        return "paged read/turn/item history incomplete"
    if "result" not in observation:
        return "public observation has no durable result"
    return None


def reconcile_home(home: Path, *, observer=None) -> ReconcileReport:
    """Conservatively classify unfinished durable operations without retrying."""
    home = _canonical_home(home)
    operations_dir = home / "state" / "codex" / "operations"
    if not operations_dir.exists():
        return ReconcileReport(0, 0, 0, 0, False)
    _require_directory(operations_dir)
    # Reconciliation adopts the generation recorded per operation; it never
    # rewrites identity merely because a replacement host has a new generation.
    journal = OperationJournal(home, "reconcile")
    observed_count = uncertain_count = failed_count = 0
    records = journal.records()
    for original in records:
        operation_id = original["operation_id"]
        state = original.get("state")
        # Transition helpers do not use journal.generation after preparation.
        if state == "prepared":
            journal.fail(operation_id, "prepared operation was never accepted")
            failed_count += 1
            continue
        if state == "accepted":
            if original.get("public_method") == "thread/start":
                journal.uncertain(
                    operation_id,
                    "thread/start response lost; public protocol has no reliable correlation")
                uncertain_count += 1
                continue
            if observer is None:
                journal.uncertain(operation_id, "public observer unavailable")
                uncertain_count += 1
                continue
            try:
                evidence = observer(original)
            except Exception as exc:
                journal.uncertain(operation_id, f"unknown transport: {type(exc).__name__}")
                uncertain_count += 1
                continue
            if not isinstance(evidence, Mapping):
                reason = "unknown transport or public observation"
            else:
                reason = _uncertainty_reason(evidence)
            if reason is not None:
                journal.uncertain(operation_id, reason)
                uncertain_count += 1
            else:
                journal.observe(operation_id, evidence["result"])
                observed_count += 1
            continue
        if state in {"observed", "committed"}:
            observed_count += 1
        elif state == "uncertain":
            uncertain_count += 1
        elif state == "failed":
            failed_count += 1
        else:
            journal.uncertain(operation_id, "unknown journal state")
            uncertain_count += 1
    return ReconcileReport(
        inspected=len(records),
        observed=observed_count,
        uncertain=uncertain_count,
        failed=failed_count,
        page=uncertain_count > 0,
        retried_operations=0,
    )


def connect_existing(home: Path) -> CodexHostClient:
    """Return the existing exact-home client; never launch or reconcile a host."""
    return CodexHostClient.connect_existing(home)


__all__ = [
    "CodexHostClient", "CodexObservation", "HostRejected", "HostUnavailable",
    "OperationJournal", "ReconcileReport", "UnsafeHostState", "connect_existing",
    "reconcile_home",
]
