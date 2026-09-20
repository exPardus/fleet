"""Synchronous client for Fleet's authenticated, per-home Codex host."""

from __future__ import annotations

import base64
import hashlib
import json
import multiprocessing.connection
import os
import secrets
import stat
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


def _canonical_home(home: Path) -> Path:
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
    finally:
        os.close(fd)
    if os.name != "nt":
        temporary.chmod(0o600)
    os.replace(temporary, path)


def _validate_fixed_paths(state_dir: Path) -> None:
    _require_directory(state_dir, create=True)
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
    token = f"{os.getpid()}:{uuid.uuid4().hex}".encode("ascii")
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
            if time.time() - info.st_mtime > HOST_LOCK_STALE_SECONDS:
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


def _digest(method: str, payload: Any) -> str:
    canonical = json.dumps(
        {"method": method, "payload": payload},
        separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class CodexHostClient:
    def __init__(self, home: Path, metadata: Mapping[str, Any], encoded_key: str,
                 authkey: bytes) -> None:
        self.home = home
        self.state_dir = home / "state" / "codex"
        self.metadata_path = self.state_dir / "host.json"
        self.key_path = self.state_dir / "host.key"
        self.generation = str(metadata["generation"])
        self._endpoint = metadata["endpoint"]
        self._transport = metadata["transport"]
        self._encoded_key = encoded_key
        self._authkey = authkey
        self._launched_process: subprocess.Popen[Any] | None = None

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

        with _host_lock(state_dir / "codex-host.lock", ready_timeout):
            _validate_fixed_paths(state_dir)
            existing = cls._existing(home)
            if existing is not None and existing._ping(0.5):
                return existing
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
        required = {"home", "generation", "endpoint", "transport", "ready"}
        if not required.issubset(metadata) or metadata.get("home") != str(home):
            raise UnsafeHostState("Codex host metadata has wrong home or missing fields")
        if metadata.get("ready") is not True:
            return None
        encoded, decoded = _read_key(key_path)
        return cls(home, metadata, encoded, decoded)

    def _ping(self, timeout: float) -> bool:
        try:
            self.call({"operation_id": f"ping-{uuid.uuid4()}",
                       "method": "ping", "payload": {}}, timeout=timeout)
            return True
        except (OSError, EOFError, TimeoutError, HostUnavailable, HostRejected):
            return False

    def call(self, operation: Mapping[str, Any], timeout: float) -> CodexObservation:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        operation_id = operation.get("operation_id")
        method = operation.get("method")
        payload = operation.get("payload", {})
        if not isinstance(operation_id, str) or not operation_id or len(operation_id) > 160:
            raise ValueError("operation_id must be a non-empty bounded string")
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        digest = _digest(method, payload)
        envelope = {
            "protocol_version": IPC_PROTOCOL_VERSION,
            "host_generation": self.generation,
            "operation_id": operation_id,
            "method": method,
            "fleet_home": str(self.home),
            "payload": payload,
            "payload_digest": digest,
            "secret": self._encoded_key,
        }
        encoded = json.dumps(envelope, separators=(",", ":"),
                             sort_keys=True, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_IPC_BYTES:
            raise ValueError(f"Codex host request exceeds {MAX_IPC_BYTES} bytes")
        try:
            connection = multiprocessing.connection.Client(
                self._endpoint, family=self._transport, authkey=self._authkey)
        except (OSError, EOFError) as exc:
            raise HostUnavailable("authenticated Codex host connection failed") from exc
        try:
            connection.send_bytes(encoded)
            if not connection.poll(timeout):
                raise TimeoutError(f"Codex host operation {operation_id} timed out")
            raw = connection.recv_bytes(MAX_IPC_BYTES)
        except (OSError, EOFError) as exc:
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
        suffix = hashlib.sha256(str(home).encode("utf-8")).hexdigest()[:24]
        return rf"\\.\pipe\fleet-codex-{suffix}", "AF_PIPE"
    return str(state_dir / "ipc.sock"), "AF_UNIX"


__all__ = [
    "CodexHostClient", "CodexObservation", "HostRejected", "HostUnavailable",
    "UnsafeHostState",
]
