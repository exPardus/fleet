"""Synchronous client for Fleet's authenticated, per-home Codex host."""

from __future__ import annotations

import base64
import ctypes
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
from datetime import datetime
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


def _fleet_state_digest(value: Mapping[str, Any]) -> str:
    """Compare complete JSON claim/row snapshots without copying them to IPC."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
SCHEMA_FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "tests" / "fixtures" / "codex_app_server"
)
REVIEWED_SCHEMA_MANIFESTS = {
    version: SCHEMA_FIXTURES / version / "manifest.json"
    for version in ("0.155.1", "0.160.0", "0.161.0")
}


class UnsafeHostState(FleetCliError):
    """A fixed host path failed its ownership, mode, type, or content check."""


class HostUnavailable(FleetCliError):
    """The authenticated home host could not be reached or started."""


class HostRejected(FleetCliError):
    """The home host refused an invalid or unauthorized operation."""


def failed_client_recovery_barrier(home: Path) -> dict[str, Any] | None:
    """Read the durable recovery fence without repairing or creating state."""
    path = _canonical_home(home) / "state" / "codex" / "failed-client-recovery.json"
    if not path.exists() and not path.is_symlink():
        return None
    _require_regular(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise UnsafeHostState("failed-client recovery barrier exceeds its bound")
    value = _read_json(path)
    if (not isinstance(value, dict) or value.get("schema") != 1
            or value.get("home") != str(_canonical_home(home))
            or value.get("state") not in {
                "prepared", "authorized", "shutdown_sent", "shutdown_ack",
                "exited", "boot_requested", "rebind", "complete",
            }):
        raise UnsafeHostState("failed-client recovery barrier is malformed")
    return value


def authorize_failed_client_recovery_operation(
        home: Path, generation: str, operation_id: str,
        public_method: str, target_thread: str | None = None,
        payload_digest: str | None = None) -> None:
    """Allow only the one staged rebind mutation while a home is fenced."""
    barrier = failed_client_recovery_barrier(home)
    if barrier is None:
        return
    if barrier["state"] == "complete":
        held = barrier.get("held_threads")
        if (not isinstance(held, list)
                or any(not isinstance(item, str) or not item for item in held)):
            raise HostRejected("failed-client held-thread fence is malformed")
        if target_thread is not None and target_thread in held:
            raise HostRejected("failed-client historical thread remains held")
        return
    if (barrier["state"] == "rebind"
            and public_method == "thread/resume"
            and barrier.get("new_generation") == generation
            and barrier.get("current_operation") == operation_id
            and barrier.get("current_thread") == target_thread
            and barrier.get("current_payload_digest") == payload_digest
            and isinstance(payload_digest, str)
            and len(payload_digest) == 64):
        return
    raise HostRejected("failed-client recovery barrier blocks provider mutation")


_FAILED_CLIENT_READ_METHODS = frozenset({
    "thread/read", "thread/turns/list", "thread/items/list", "thread/list",
    "config/read", "configRequirements/read",
})


def authorize_failed_client_recovery_rpc(
        home: Path, generation: str, operation_id: str,
        payload: Any, payload_digest: str) -> None:
    """Fence the entire RPC surface while recovery is staged or held."""
    if failed_client_recovery_barrier(home) is None:
        return
    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str):
        raise HostRejected("failed-client RPC method is malformed")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise HostRejected("failed-client RPC params are malformed")
    method = payload["method"]
    if method in _FAILED_CLIENT_READ_METHODS:
        return
    if method not in _MUTATING_PUBLIC_METHODS:
        raise HostRejected("failed-client recovery blocks unreviewed public RPC")
    authorize_failed_client_recovery_operation(
        home, generation, operation_id, method, params.get("threadId"),
        payload_digest)


def authorize_failed_client_recovery_shutdown(
        home: Path, generation: str, operation_id: str,
        *, method: str = "host/shutdown") -> None:
    """Permit only the staged original-host stop; protect its replacement."""
    barrier = failed_client_recovery_barrier(home)
    if barrier is None:
        return
    old = barrier.get("old_host")
    if (method == "host/shutdown" and barrier.get("state") == "shutdown_sent"
            and isinstance(old, dict)
            and old.get("generation") == generation
            and barrier.get("shutdown_operation") == operation_id):
        return
    raise HostRejected("failed-client recovery blocks host shutdown")


def _reviewed_schema_manifest(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    """Select an explicit reviewed schema from the installed Codex version."""
    if not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("Codex schema command must be a non-empty argv")
    try:
        completed = subprocess.run(
            [*command, "--version"], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise HostUnavailable("could not read installed Codex version") from exc
    words = completed.stdout.strip().split()
    if (completed.returncode != 0 or len(words) != 2
            or words[0] != "codex-cli"):
        raise HostUnavailable("could not parse installed Codex version")
    version = words[1]
    manifest = REVIEWED_SCHEMA_MANIFESTS.get(version)
    if manifest is None:
        raise HostUnavailable(
            f"installed Codex version {version!r} has no reviewed schema")
    return manifest


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
    "thread/start", "thread/resume", "turn/start", "turn/steer", "turn/interrupt",
})
_BLOCKING_SERVER_REQUESTS = frozenset({
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
    "item/permissions/requestApproval",
})
_SIMPLE_APPROVAL_DECISIONS = frozenset({
    "accept", "acceptForSession", "decline", "cancel",
})
_SENSITIVE_KEYS = frozenset({
    "content", "input", "instructions", "message", "prompt", "reasoning",
    "secret", "text", "transcript",
})

INTERFACE_CLAIM_SCHEMA = 1


def _platform():
    """Use Fleet's single OS-selection adapter without importing it at module load."""
    from fleet_platform import PLATFORM
    return PLATFORM


def _linux_stat_identity(raw: str) -> tuple[int, str] | None:
    end = raw.rfind(")")
    if end < 1:
        return None
    fields = raw[end + 2:].split()
    try:
        # fields[0] is stat field 3 (state), [1] is PPID, [19] is starttime.
        return int(fields[1]), fields[19]
    except (IndexError, ValueError):
        return None


def _linux_process_record(pid: int) -> dict[str, Any] | None:
    """Read one PID-reuse-resistant process record from Linux procfs.

    ``stat`` is parsed after the final ``)`` because the command name may
    contain spaces and parentheses.  Callers treat every missing field as an
    authentication failure; there is no kill(0) or same-uid fallback.
    """
    if not _platform().is_linux or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        before = _linux_stat_identity(stat_path.read_text(encoding="ascii"))
        if before is None:
            return None
        ppid, start = before
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
        uid_line = next(line for line in status.splitlines()
                        if line.startswith("Uid:"))
        uid = int(uid_line.split()[1])
        comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
        cwd = str(Path(f"/proc/{pid}/cwd").resolve(strict=True))
        if _linux_stat_identity(stat_path.read_text(encoding="ascii")) != before:
            return None
    except (OSError, StopIteration, IndexError, UnicodeError, ValueError):
        return None
    return {"pid": pid, "ppid": ppid, "start_identity": start,
            "uid": uid, "comm": comm, "cwd": cwd}


def _linux_process_environment(pid: int) -> dict[str, str] | None:
    if not _platform().is_linux:
        return None
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
        result: dict[str, str] = {}
        for entry in raw.split(b"\0"):
            if b"=" not in entry:
                continue
            key, value = entry.split(b"=", 1)
            result[key.decode("utf-8")] = value.decode("utf-8")
        return result
    except (OSError, UnicodeError):
        return None


class _DarwinBsdInfo(ctypes.Structure):
    # sys/proc_info.h: struct proc_bsdinfo (including its alignment).
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "flags", "status", "xstatus", "pid", "ppid", "uid", "gid",
        "ruid", "rgid", "svuid", "svgid", "reserved")]
    _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
    _fields_ += [(name, ctypes.c_uint32) for name in (
        "nfiles", "pgid", "pjobc", "e_tdev", "e_tpgid")]
    _fields_ += [("nice", ctypes.c_int32), ("start_sec", ctypes.c_uint64),
                 ("start_usec", ctypes.c_uint64)]


class _DarwinVinfoStat(ctypes.Structure):
    _fields_ = [
        ("dev", ctypes.c_uint32), ("mode", ctypes.c_uint16),
        ("nlink", ctypes.c_uint16), ("ino", ctypes.c_uint64),
        ("uid", ctypes.c_uint32), ("gid", ctypes.c_uint32),
        *((name, ctypes.c_int64) for name in (
            "atime", "atimensec", "mtime", "mtimensec", "ctime",
            "ctimensec", "birthtime", "birthtimensec", "size", "blocks")),
        ("blksize", ctypes.c_int32), ("flags", ctypes.c_uint32),
        ("gen", ctypes.c_uint32), ("rdev", ctypes.c_uint32),
        ("spare", ctypes.c_int64 * 2),
    ]


class _DarwinVnodeInfoPath(ctypes.Structure):
    _fields_ = [("stat", _DarwinVinfoStat), ("type", ctypes.c_int32),
                ("pad", ctypes.c_int32), ("fsid", ctypes.c_int32 * 2),
                ("path", ctypes.c_char * 1024)]


class _DarwinVnodePathInfo(ctypes.Structure):
    _fields_ = [("cwd", _DarwinVnodeInfoPath),
                ("root", _DarwinVnodeInfoPath)]


def _darwin_proc_pidinfo(pid: int, flavor: int, buffer: Any,
                         *, proc_pidinfo: Any | None = None) -> bool:
    if proc_pidinfo is None:
        try:
            proc_pidinfo = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True).proc_pidinfo
        except (OSError, AttributeError):
            return False
        proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                 ctypes.c_void_p, ctypes.c_int]
        proc_pidinfo.restype = ctypes.c_int
    try:
        return proc_pidinfo(pid, flavor, 0, ctypes.byref(buffer),
                            ctypes.sizeof(buffer)) == ctypes.sizeof(buffer)
    except (OSError, TypeError, ValueError):
        return False


def _darwin_process_record(pid: int) -> dict[str, Any] | None:
    """Read a complete Darwin process record, rejecting identity changes."""
    if (not getattr(_platform(), "is_darwin", False)
            or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        return None
    before = _darwin_process_identity(pid)
    if before is None or not before.startswith("darwin:"):
        return None  # ps precision is insufficient for caller authentication.
    bsd = _DarwinBsdInfo()
    paths = _DarwinVnodePathInfo()
    if (not _darwin_proc_pidinfo(pid, 3, bsd)
            or not _darwin_proc_pidinfo(pid, 9, paths)):
        return None
    if bsd.pid != pid or bsd.ppid <= 0:
        return None
    try:
        comm = bsd.comm.split(b"\0", 1)[0].decode("utf-8")
        cwd = os.fsdecode(paths.cwd.path.split(b"\0", 1)[0])
        if not cwd or not os.path.isabs(cwd):
            return None
        cwd = str(Path(cwd).resolve(strict=True))
    except (OSError, UnicodeError, ValueError):
        return None
    if not comm or _darwin_process_identity(pid) != before:
        return None
    return {"pid": pid, "ppid": int(bsd.ppid), "start_identity": before,
            "uid": int(bsd.uid), "comm": comm, "cwd": cwd}


def _darwin_process_environment(pid: int, *, sysctl: Any | None = None,
                                owner_uid: int | None = None) -> dict[str, str] | None:
    """Read KERN_PROCARGS2 only for a current same-uid process."""
    if (not getattr(_platform(), "is_darwin", False)
            or not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
        return None
    owner_uid = os.getuid() if owner_uid is None else owner_uid
    bsd = _DarwinBsdInfo()
    if not _darwin_proc_pidinfo(pid, 3, bsd) or bsd.pid != pid or bsd.uid != owner_uid:
        return None
    if sysctl is None:
        try:
            sysctl = ctypes.CDLL(None, use_errno=True).sysctl
        except (OSError, AttributeError):
            return None
        sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
                           ctypes.c_void_p, ctypes.c_size_t]
        sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t()
    try:
        if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            return None
        if not 4 <= size.value <= 4 * 1024 * 1024:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            return None
        raw = buffer.raw[:size.value]
        argc = struct.unpack_from("=i", raw)[0]
        if not 0 <= argc <= 100_000:
            return None
        cursor = 4
        executable_end = raw.find(b"\0", cursor)
        if executable_end < 0:
            return None
        cursor = executable_end + 1
        while cursor < len(raw) and raw[cursor] == 0:
            cursor += 1
        for _ in range(argc):
            end = raw.find(b"\0", cursor)
            if end < 0:
                return None
            cursor = end + 1
        while cursor < len(raw) and raw[cursor] == 0:
            cursor += 1
        result: dict[str, str] = {}
        while cursor < len(raw):
            end = raw.find(b"\0", cursor)
            if end < 0:
                return None
            if end == cursor:
                break
            key, separator, value = raw[cursor:end].partition(b"=")
            if not separator or not key:
                return None
            result[key.decode("utf-8")] = value.decode("utf-8")
            cursor = end + 1
        return result
    except (OSError, UnicodeError, ValueError, struct.error):
        return None


def _process_evidence_readers():
    if _platform().is_linux:
        return _linux_process_record, _linux_process_environment
    if getattr(_platform(), "is_darwin", False):
        return _darwin_process_record, _darwin_process_environment
    raise HostRejected("Codex caller process authentication is unsupported on this platform")


def codex_process_source(pid: int, thread_id: str | None = None) -> dict[str, Any]:
    """Bind a caller thread to its actual Codex ancestor.

    The thread value is read from the socket peer's process environment (or
    checked against it by registration), while the durable process identity
    comes from the nearest executable Codex ancestor.  Both are needed:
    readable thread membership and a UUID-shaped environment value alone are
    replayable.
    """
    process_record, process_environment = _process_evidence_readers()
    peer_before = process_record(pid)
    if peer_before is None:
        raise HostRejected("Codex caller process identity is unavailable")
    environment = process_environment(pid)
    peer_after = process_record(pid)
    if (peer_after is None
            or peer_after["start_identity"] != peer_before["start_identity"]):
        raise HostRejected("Codex caller process identity changed during authentication")
    actual_thread = environment.get("CODEX_THREAD_ID") if environment else None
    if (not isinstance(actual_thread, str) or not actual_thread
            or (thread_id is not None and actual_thread != thread_id)):
        raise HostRejected("Codex caller thread does not match process evidence")
    seen: set[int] = set()
    current = pid
    for _ in range(64):
        if current in seen:
            break
        seen.add(current)
        record = peer_after if current == pid else process_record(current)
        if record is None:
            break
        if record["comm"] == "codex":
            confirmed = process_record(current)
            if (confirmed is None
                    or confirmed["start_identity"] != record["start_identity"]):
                raise HostRejected(
                    "Codex ancestor process identity changed during authentication")
            return {"thread_id": actual_thread,
                    "ancestor_pid": record["pid"],
                    "ancestor_start_identity": record["start_identity"],
                    "ancestor_cwd": record["cwd"], "uid": record["uid"]}
        current = record["ppid"]
        if current <= 1:
            break
    raise HostRejected("Codex caller has no verifiable Codex process ancestor")


def read_interface_claim(home: Path) -> dict[str, Any] | None:
    """Read the exact-home external Interface claim, failing closed on drift."""
    path = _canonical_home(home) / "state" / "interface-codex.json"
    if not path.exists() and not path.is_symlink():
        return None
    value = _read_json(path)
    required = ("thread_id", "ancestor_pid", "ancestor_start_identity",
                "claim_id", "home", "uid")
    if (not isinstance(value, dict)
            or value.get("schema") != INTERFACE_CLAIM_SCHEMA
            or value.get("home") != str(_canonical_home(home))
            or any(not value.get(key) for key in required)):
        raise UnsafeHostState("native Codex Interface claim is malformed")
    try:
        _public_uuid7(value["thread_id"], "Interface claim thread id")
    except ValueError as exc:
        raise UnsafeHostState("native Codex Interface thread id is malformed") from exc
    if (not isinstance(value["ancestor_pid"], int)
            or isinstance(value["ancestor_pid"], bool)
            or value["ancestor_pid"] <= 1
            or not isinstance(value["ancestor_start_identity"], str)
            or not value["ancestor_start_identity"]
            or not isinstance(value["uid"], int)
            or isinstance(value["uid"], bool)
            or value["uid"] < 0):
        raise UnsafeHostState("native Codex Interface process identity is malformed")
    try:
        claim_id = uuid.UUID(value["claim_id"])
    except (ValueError, AttributeError) as exc:
        raise UnsafeHostState("native Codex Interface claim id is invalid") from exc
    if claim_id.version != 4 or str(claim_id) != value["claim_id"]:
        raise UnsafeHostState("native Codex Interface claim id is not canonical UUIDv4")
    return value


def interface_source_matches(claim: Mapping[str, Any], source: Mapping[str, Any]) -> bool:
    """Compare every reusable process/thread component of an Interface claim."""
    return (claim.get("thread_id") == source.get("thread_id")
            and claim.get("ancestor_pid") == source.get("ancestor_pid")
            and hmac.compare_digest(
                str(claim.get("ancestor_start_identity", "")),
                str(source.get("ancestor_start_identity", "")))
            and claim.get("uid") == source.get("uid"))


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
    if not _platform().is_windows and info.st_uid != os.getuid():
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
            if not _platform().is_windows:
                path.chmod(0o700)
    info = _require_owner(path)
    if not stat.S_ISDIR(info.st_mode):
        raise UnsafeHostState(f"Codex host path is not a directory: {path}")
    if not _platform().is_windows and stat.S_IMODE(info.st_mode) != 0o700:
        raise UnsafeHostState(f"Codex host directory mode is not 0700: {path}")


def _require_regular(path: Path, *, mode: int = 0o600) -> os.stat_result:
    info = _require_owner(path)
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeHostState(f"Codex host path is not a regular file: {path}")
    if not _platform().is_windows and stat.S_IMODE(info.st_mode) != mode:
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
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(temporary), flags, 0o600)
        try:
            data = encoded.encode("ascii")
            if os.write(fd, data) != len(data):
                raise OSError("short Codex host key write")
            os.fsync(fd)
        finally:
            os.close(fd)
        if not _platform().is_windows:
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
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
    if not _platform().is_windows:
        temporary.chmod(0o600)
    os.replace(temporary, path)
    if not _platform().is_windows:
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _validate_fixed_paths(state_dir: Path) -> None:
    if _platform().is_windows:
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
        if not _platform().is_windows and not stat.S_ISSOCK(info.st_mode):
            raise UnsafeHostState(f"Codex host endpoint has unsafe type: {endpoint}")
        if not _platform().is_windows and stat.S_IMODE(info.st_mode) != 0o600:
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
            if not _platform().is_windows:
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


class _DarwinTimeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int)]


class _DarwinExternProcPrefix(ctypes.Structure):
    # ``extern_proc.p_un.p_starttime`` is the first field of ``extern_proc``.
    _fields_ = [("p_starttime", _DarwinTimeval)]


class _DarwinKinfoProcPrefix(ctypes.Structure):
    # ``kp_proc`` is the first field of ``kinfo_proc``.  sysctl supplies the
    # complete structure; this prefix names only the public start-time field.
    _fields_ = [("kp_proc", _DarwinExternProcPrefix)]


def _darwin_sysctl_process_identity(
    pid: int, *, sysctl: Any | None = None,
) -> str | None:
    """Read ``KERN_PROC_PID``'s ``kp_proc.p_starttime`` through libc."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if sysctl is None:
        try:
            sysctl = ctypes.CDLL(None, use_errno=True).sysctl
        except (AttributeError, OSError):
            return None
        sysctl.argtypes = [
            ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t,
        ]
        sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 4)(1, 14, 1, pid)  # CTL_KERN, KERN_PROC, KERN_PROC_PID
    size = ctypes.c_size_t()
    try:
        if sysctl(mib, 4, None, ctypes.byref(size), None, 0) != 0:
            return None
        minimum = ctypes.sizeof(_DarwinKinfoProcPrefix)
        if size.value < minimum or size.value > MAX_METADATA_BYTES:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if sysctl(mib, 4, buffer, ctypes.byref(size), None, 0) != 0:
            return None
        if size.value < minimum:
            return None
        process = ctypes.cast(
            buffer, ctypes.POINTER(_DarwinKinfoProcPrefix)).contents
        seconds = int(process.kp_proc.p_starttime.tv_sec)
        microseconds = int(process.kp_proc.p_starttime.tv_usec)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if seconds <= 0 or not 0 <= microseconds < 1_000_000:
        return None
    return f"darwin:{seconds}.{microseconds:06d}"


def _darwin_ps_process_identity(
    pid: int, *, run: Any | None = None,
) -> str | None:
    """Fall back to Darwin ``ps``'s second-resolution kernel start time."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    run = subprocess.run if run is None else run
    environment = dict(os.environ)
    environment.update({"LC_ALL": "C", "LC_TIME": "C"})
    try:
        completed = run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            env=environment, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    fields = completed.stdout.strip().split()
    if len(fields) != 5:
        return None
    weekday, month, day, clock, year = fields
    months = {
        "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
        "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
    }
    if weekday not in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
        return None
    try:
        hour, minute, second = (int(part) for part in clock.split(":"))
        started = datetime(
            int(year), months[month], int(day), hour, minute, second)
    except (KeyError, TypeError, ValueError):
        return None
    return f"darwin-ps:{started:%Y-%m-%dT%H:%M:%S}"


def _darwin_process_identity(pid: int) -> str | None:
    return (_darwin_sysctl_process_identity(pid)
            or _darwin_ps_process_identity(pid))


def _process_identities_match(expected: str, observed: str) -> bool | None:
    """Compare process identities, returning ``None`` when sources differ.

    Darwin's sysctl identity has microsecond precision while the ps fallback
    exposes a local wall-clock value with second precision.  Neither can be
    losslessly converted to the other, so a source transition is unknown
    rather than evidence that a live PID was reused.
    """
    sources = {
        "darwin:": "sysctl",
        "darwin-ps:": "ps",
    }

    def source(value: str) -> str | None:
        return next((name for prefix, name in sources.items()
                     if value.startswith(prefix)), None)

    expected_source = source(expected)
    observed_source = source(observed)
    if (expected_source is not None and observed_source is not None
            and expected_source != observed_source):
        return None
    return hmac.compare_digest(expected, observed)


def _process_identity(pid: int) -> str | None:
    """Return a PID-reuse-resistant identity from the current OS."""
    if _platform().is_windows:
        return None
    if not _platform().is_linux:
        return _darwin_process_identity(pid)
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
        if not isinstance(identity, str):
            return False
        matches = _process_identities_match(identity, current)
        if matches is not None:
            return matches
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


_USAGE_FIELDS = {
    "cacheWriteInputTokens": "cache_write_input_tokens",
    "cachedInputTokens": "cached_input_tokens",
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
    "reasoningOutputTokens": "reasoning_output_tokens",
    "totalTokens": "total_tokens",
}
_TERMINAL_TURN_STATES = frozenset({"completed", "failed", "interrupted"})


def _public_uuid7(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} is missing")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if parsed.version != 7 or str(parsed) != value.lower():
        raise ValueError(f"{label} is not a canonical UUIDv7")
    return value


def _public_error_code(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and len(value) == 1:
        key = next(iter(value))
        return key if isinstance(key, str) and key else None
    return None


class CodexPublicEvidenceStore:
    """Durable bounded result/usage evidence from public app-server events."""

    def __init__(self, home: Path) -> None:
        self.home = _canonical_home(home)
        self.state_dir = self.home / "state" / "codex"
        _require_directory(self.state_dir, create=True)
        self.directory = self.state_dir / "public-evidence"
        _require_directory(self.directory, create=True)

    def path(self, thread_id: object, turn_id: object) -> Path:
        thread = _public_uuid7(thread_id, "public thread id")
        turn = _public_uuid7(turn_id, "public turn id")
        return self.directory / f"{thread}.{turn}.json"

    def read(self, thread_id: object, turn_id: object) -> dict[str, Any] | None:
        path = self.path(thread_id, turn_id)
        value = _read_json(path)
        if value is None:
            return None
        if (value.get("schema") != 1
                or value.get("thread_id") != thread_id
                or value.get("turn_id") != turn_id):
            raise UnsafeHostState(f"public evidence identity mismatch: {path}")
        return value

    @staticmethod
    def _usage(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("public token usage is malformed")
        result: dict[str, int] = {}
        for public, stored in _USAGE_FIELDS.items():
            number = value.get(public, 0 if public == "cacheWriteInputTokens" else None)
            if (not isinstance(number, int) or isinstance(number, bool)
                    or number < 0):
                raise ValueError("public token usage contains an invalid count")
            result[stored] = number
        return result

    @staticmethod
    def _agent_result(item: Any) -> tuple[str, str, bool] | None:
        if not isinstance(item, dict) or item.get("type") != "agentMessage":
            return None
        item_id = item.get("id")
        text = item.get("text")
        if (not isinstance(item_id, str) or not item_id or len(item_id) > 160
                or not isinstance(text, str)):
            raise ValueError("public agent result is malformed")
        encoded = text.encode("utf-8")
        if len(encoded) > 32 * 1024:
            return item_id, encoded[:32 * 1024].decode("utf-8", "ignore"), True
        return item_id, text, False

    def record(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if method not in {
                "thread/tokenUsage/updated", "item/completed", "turn/completed"}:
            return None
        params = message.get("params")
        if not isinstance(params, dict):
            raise ValueError(f"{method} params are malformed")
        thread_id = _public_uuid7(params.get("threadId"), "event thread id")
        if method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict):
                raise ValueError("turn/completed turn is malformed")
            turn_id = _public_uuid7(turn.get("id"), "event turn id")
        else:
            turn_id = _public_uuid7(params.get("turnId"), "event turn id")
            turn = None
        current = self.read(thread_id, turn_id) or {
            "schema": 1, "thread_id": thread_id, "turn_id": turn_id,
        }
        if method == "thread/tokenUsage/updated":
            token_usage = params.get("tokenUsage")
            last = token_usage.get("last") if isinstance(token_usage, dict) else None
            current["usage"] = self._usage(last)
        elif method == "item/completed":
            result = self._agent_result(params.get("item"))
            if result is not None:
                item_id, text, truncated = result
                current.update({
                    "result_item_id": item_id, "result_text": text,
                    "result_truncated": truncated,
                })
        else:
            assert turn is not None
            status = turn.get("status")
            if status not in _TERMINAL_TURN_STATES:
                raise ValueError("turn/completed status is not terminal")
            current["turn_status"] = status
            error = turn.get("error")
            if error is not None:
                if not isinstance(error, dict):
                    raise ValueError("turn/completed error is malformed")
                code = _public_error_code(error.get("codexErrorInfo"))
                if code is not None:
                    current["error_code"] = code
            items = turn.get("items", [])
            if not isinstance(items, list):
                raise ValueError("turn/completed items are malformed")
            for item in items:
                result = self._agent_result(item)
                if result is not None:
                    item_id, text, truncated = result
                    current.update({
                        "result_item_id": item_id, "result_text": text,
                        "result_truncated": truncated,
                    })
        current["observed_at"] = time.time()
        _atomic_json(self.path(thread_id, turn_id), current)
        return current


def _server_request_id(value: object) -> str | int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("server request id must be a string or integer")
    if isinstance(value, str) and (not value or len(value) > 160):
        raise ValueError("server request id must be a non-empty bounded string")
    if isinstance(value, int) and value < 0:
        raise ValueError("server request id must be non-negative")
    return value


def _approval_key(generation: str, request_id: str | int) -> str:
    encoded = json.dumps(
        {"generation": generation, "request_id": request_id},
        separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_approval_request_params(method: str,
                                      params: Mapping[str, Any]) -> None:
    """Validate required fields that are specific to each reviewed request."""
    def required_started_at() -> None:
        started_at = params.get("startedAtMs")
        if isinstance(started_at, bool) or not isinstance(started_at, int):
            raise ValueError("approval request startedAtMs is invalid")

    if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval"}:
        required_started_at()
        return

    if method == "item/tool/requestUserInput":
        if not isinstance(params.get("isBlocking"), bool):
            raise ValueError("user input request isBlocking is invalid")
        questions = params.get("questions")
        if not isinstance(questions, list):
            raise ValueError("user input request questions are invalid")
        question_ids: set[str] = set()
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError("user input request question is invalid")
            for field in ("header", "id", "question"):
                if not isinstance(question.get(field), str):
                    raise ValueError(f"user input request question {field} is invalid")
            question_id = question["id"]
            if not question_id or question_id in question_ids:
                raise ValueError("user input request question id is invalid")
            question_ids.add(question_id)
            options = question.get("options")
            if options is not None:
                if not isinstance(options, list):
                    raise ValueError("user input request options are invalid")
                for option in options:
                    if (not isinstance(option, dict)
                            or not isinstance(option.get("label"), str)
                            or not isinstance(option.get("description"), str)):
                        raise ValueError("user input request option is invalid")
            for field in ("isOther", "isSecret"):
                if field in question and not isinstance(question[field], bool):
                    raise ValueError(f"user input request question {field} is invalid")
        return

    if method == "mcpServer/elicitation/request":
        server_name = params.get("serverName")
        if not isinstance(server_name, str) or not server_name:
            raise ValueError("MCP elicitation serverName is invalid")
        return

    if method == "item/permissions/requestApproval":
        required_started_at()
        if not isinstance(params.get("cwd"), str):
            raise ValueError("permission request cwd is invalid")
        if not isinstance(params.get("permissions"), dict):
            raise ValueError("permission request permissions are invalid")
        return


def _approval_decision(method: str, decision: Any,
                       params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an explicit response without inventing any omitted choice."""
    if method in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval"}:
        response = {"decision": decision} if isinstance(decision, str) else decision
        if not isinstance(response, dict) or set(response) != {"decision"}:
            raise HostRejected("approval decision must be one explicit decision")
        choice = response["decision"]
        if isinstance(choice, str):
            if choice not in _SIMPLE_APPROVAL_DECISIONS:
                raise HostRejected("approval decision was not offered")
            return response
        if method != "item/commandExecution/requestApproval" or not isinstance(choice, dict):
            raise HostRejected("approval decision was not offered")
        if set(choice) == {"acceptWithExecpolicyAmendment"}:
            proposed = params.get("proposedExecpolicyAmendment")
            body = choice["acceptWithExecpolicyAmendment"]
            amendment = body.get("execpolicy_amendment") if isinstance(body, dict) else None
            if (not isinstance(proposed, list) or amendment != proposed
                    or any(not isinstance(item, str) for item in proposed)):
                raise HostRejected("execpolicy amendment was not offered exactly")
            return response
        if set(choice) == {"applyNetworkPolicyAmendment"}:
            proposed = params.get("proposedNetworkPolicyAmendments")
            body = choice["applyNetworkPolicyAmendment"]
            amendment = body.get("network_policy_amendment") \
                if isinstance(body, dict) else None
            if not isinstance(proposed, list) or amendment not in proposed:
                raise HostRejected("network policy amendment was not offered")
            return response
        raise HostRejected("approval decision was not offered")

    if method == "item/tool/requestUserInput":
        if not isinstance(decision, dict) or set(decision) != {"answers"}:
            raise HostRejected("user input requires an explicit answers object")
        answers = decision["answers"]
        questions = params.get("questions")
        if not isinstance(answers, dict) or not isinstance(questions, list):
            raise HostRejected("user input answers are malformed")
        offered: dict[str, dict[str, Any]] = {}
        for question in questions:
            if not isinstance(question, dict):
                raise HostRejected("user input question is malformed")
            question_id = question.get("id")
            if not isinstance(question_id, str) or not question_id or question_id in offered:
                raise HostRejected("user input question id is invalid")
            offered[question_id] = question
        if set(answers) != set(offered):
            raise HostRejected("user input must answer exactly the offered questions")
        for question_id, answer in answers.items():
            if not isinstance(answer, dict) or set(answer) != {"answers"}:
                raise HostRejected("user input answer is malformed")
            values = answer["answers"]
            if (not isinstance(values, list) or not values
                    or any(not isinstance(value, str) for value in values)):
                raise HostRejected("user input answer values are malformed")
            options = offered[question_id].get("options")
            if isinstance(options, list) and not offered[question_id].get("isOther", False):
                labels = {item.get("label") for item in options if isinstance(item, dict)}
                if any(value not in labels for value in values):
                    raise HostRejected("user input answer was not offered")
        return decision

    if method == "mcpServer/elicitation/request":
        if not isinstance(decision, dict) or not set(decision).issubset(
                {"action", "content", "_meta"}):
            raise HostRejected("MCP elicitation response is malformed")
        action = decision.get("action")
        if action not in {"accept", "decline", "cancel"}:
            raise HostRejected("MCP elicitation action was not offered")
        if action == "accept" and "content" not in decision:
            raise HostRejected("accepted MCP elicitation requires explicit content")
        if action != "accept" and decision.get("content") not in (None, {}):
            raise HostRejected("declined MCP elicitation cannot include content")
        return decision

    if method == "item/permissions/requestApproval":
        if not isinstance(decision, dict) or not set(decision).issubset(
                {"permissions", "scope", "strictAutoReview"}):
            raise HostRejected("permission response is malformed")
        requested = params.get("permissions")
        if not isinstance(requested, dict):
            raise HostRejected("permission request has no permissions object")
        if (not isinstance(decision.get("permissions"), dict)
                or decision["permissions"] != requested):
            raise HostRejected("permission response must grant exactly the requested profile")
        if decision.get("scope", "turn") not in {"turn", "session"}:
            raise HostRejected("permission response scope is invalid")
        strict = decision.get("strictAutoReview")
        if strict is not None and not isinstance(strict, bool):
            raise HostRejected("permission response strictAutoReview is invalid")
        return decision

    raise HostRejected("unknown server request kind is frozen and cannot be answered")


def _approval_response_evidence(method: str, response: Mapping[str, Any]) -> dict[str, Any]:
    """Persist response state without retaining user-input or elicitation values."""
    if method == "item/tool/requestUserInput":
        answers = response.get("answers")
        return {"answered_question_ids": sorted(answers) if isinstance(answers, dict) else []}
    if method == "mcpServer/elicitation/request":
        return {"action": response.get("action"),
                "content_supplied": "content" in response}
    return _public_evidence(response)


class CodexApprovalStore:
    """Owner-only durable app-server requests and exactly-once responses."""

    _UNRESOLVED = frozenset({
        "pending", "responding", "responded", "uncertain", "unknown"})

    def __init__(self, home: Path, generation: str) -> None:
        self.home = _canonical_home(home)
        if not isinstance(generation, str) or not generation:
            raise ValueError("host generation is required")
        self.generation = generation
        self.state_dir = self.home / "state" / "codex"
        _require_directory(self.state_dir, create=True)
        self.directory = self.state_dir / "approvals"
        _require_directory(self.directory, create=True)

    def path(self, request_id: str | int, generation: str | None = None) -> Path:
        request_id = _server_request_id(request_id)
        return self.directory / f"{_approval_key(generation or self.generation, request_id)}.json"

    def _load_path(self, path: Path) -> dict[str, Any]:
        value = _read_json(path)
        try:
            generation = value.get("generation") if isinstance(value, dict) else None
            request_id = _server_request_id(value.get("request_id")) \
                if isinstance(value, dict) else None
            expected_key = (_approval_key(generation, request_id)
                            if isinstance(generation, str) and generation else None)
        except (TypeError, ValueError):
            expected_key = None
        if (value is None or value.get("schema") != 1
                or value.get("home") != str(self.home)
                or value.get("key") != path.stem
                or expected_key != path.stem):
            raise UnsafeHostState(f"Codex approval identity mismatch: {path}")
        return value

    def records(self) -> list[dict[str, Any]]:
        records = []
        for path in sorted(self.directory.glob("*.json")):
            _require_regular(path)
            records.append(self._load_path(path))
        return sorted(records, key=lambda item: item.get("created_at", 0))

    @staticmethod
    def _offered(method: str, params: Mapping[str, Any]) -> list[str]:
        if method in {
                "item/commandExecution/requestApproval",
                "item/fileChange/requestApproval"}:
            offered = ["accept", "acceptForSession", "decline", "cancel"]
            if method == "item/commandExecution/requestApproval":
                if isinstance(params.get("proposedExecpolicyAmendment"), list):
                    offered.append("acceptWithExecpolicyAmendment")
                if isinstance(params.get("proposedNetworkPolicyAmendments"), list):
                    offered.append("applyNetworkPolicyAmendment")
            return offered
        if method == "mcpServer/elicitation/request":
            return ["accept", "decline", "cancel"]
        if method == "item/tool/requestUserInput":
            return ["answers"]
        if method == "item/permissions/requestApproval":
            return ["permissions"]
        return []

    def record_request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        request_id = _server_request_id(message.get("id"))
        method = message.get("method")
        params = message.get("params")
        params_map = params if isinstance(params, dict) else None
        thread_id = params_map.get("threadId") if params_map is not None else None
        turn_id = params_map.get("turnId") if params_map is not None else None
        item_id = params_map.get("itemId") if params_map is not None else None
        known = (isinstance(method, str) and bool(method)
                 and method in _BLOCKING_SERVER_REQUESTS
                 and params_map is not None)
        if params_map is not None:
            try:
                thread_id = _public_uuid7(thread_id, "server request thread id")
                if turn_id is not None:
                    turn_id = _public_uuid7(turn_id, "server request turn id")
                if method != "mcpServer/elicitation/request" and turn_id is None:
                    raise ValueError("server request turn id is missing")
                if method not in {"mcpServer/elicitation/request"}:
                    if not isinstance(item_id, str) or not item_id or len(item_id) > 160:
                        raise ValueError("server request item id is invalid")
                if known:
                    _validate_approval_request_params(method, params_map)
            except ValueError:
                known = False
        safe_params = _public_evidence(params)
        record = {
            "schema": 1, "home": str(self.home),
            "key": _approval_key(self.generation, request_id),
            "generation": self.generation, "request_id": request_id,
            "method": method, "thread_id": thread_id, "turn_id": turn_id,
            "item_id": item_id, "params": safe_params,
            "offered_decisions": self._offered(method, params_map) if known else [],
            "state": "pending" if known else "unknown",
            "created_at": time.time(),
        }
        if not known:
            record["reason"] = "unknown, malformed, or identity-incomplete server request kind"
        # Approval evidence is intentionally bounded below the fixed metadata cap.
        if len(json.dumps(record, ensure_ascii=False).encode("utf-8")) > 48 * 1024:
            record["params"] = {
                key: safe_params.get(key) for key in ("threadId", "turnId", "itemId")
                if isinstance(safe_params, dict) and key in safe_params}
            record["offered_decisions"] = []
            record["state"] = "unknown"
            record["reason"] = "oversized server request was frozen"
        path = self.path(request_id)
        if path.exists() or path.is_symlink():
            existing = self._load_path(path)
            immutable = ("request_id", "generation", "method", "thread_id",
                         "turn_id", "item_id", "params")
            if any(existing.get(key) != record.get(key) for key in immutable):
                raise UnsafeHostState("server request id was reused with different content")
            return existing
        _atomic_json(path, record)
        return record

    def unresolved(self, *, thread_id: str | None = None,
                   turn_id: str | None = None) -> list[dict[str, Any]]:
        result = []
        for record in self.records():
            if record.get("state") not in self._UNRESOLVED:
                continue
            if thread_id is not None and record.get("thread_id") != thread_id:
                continue
            if (turn_id is not None
                    and record.get("turn_id") not in (None, turn_id)):
                continue
            result.append(record)
        return result

    def has_unresolved(self) -> bool:
        return any(record.get("generation") == self.generation
                   for record in self.unresolved())

    def _current(self, request_id: str | int, thread_id: str,
                 turn_id: str) -> dict[str, Any]:
        matches = [record for record in self.unresolved(thread_id=thread_id)
                   if (record.get("turn_id") in {None, turn_id}
                       and str(record.get("request_id")) == str(request_id))]
        current = [record for record in matches
                   if record.get("generation") == self.generation]
        if len(current) == 1:
            return current[0]
        if not current and matches:
            raise HostRejected("approval request belongs to a stale host generation")
        if len(current) != 1:
            raise HostRejected("approval request is missing, stale, or ambiguous")
        return current[0]

    def begin_response(self, request_id: str | int, thread_id: str,
                       turn_id: str, decision: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        record = self._current(request_id, thread_id, turn_id)
        if record.get("state") != "pending":
            raise HostRejected(
                f"approval request was already consumed ({record.get('state')})")
        response = _approval_decision(
            record.get("method", ""), decision,
            record.get("params") if isinstance(record.get("params"), dict) else {})
        record.update({"state": "responding", "response": _approval_response_evidence(
                           record.get("method", ""), response),
                       "responding_at": time.time()})
        _atomic_json(self.path(record["request_id"]), record)
        return record, response

    def mark_responded(self, record: Mapping[str, Any]) -> dict[str, Any]:
        current = self._load_path(self.path(record["request_id"]))
        if current.get("state") != "responding":
            raise HostRejected("approval response state changed before consumption")
        current.update({"state": "responded", "responded_at": time.time()})
        _atomic_json(self.path(current["request_id"]), current)
        return current

    def mark_uncertain(self, record: Mapping[str, Any], reason: str) -> dict[str, Any]:
        current = self._load_path(self.path(record["request_id"]))
        if current.get("state") == "responding":
            current.update({"state": "uncertain", "reason": str(reason)[:300],
                            "uncertain_at": time.time()})
            _atomic_json(self.path(current["request_id"]), current)
        return current

    def resolve(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        params = message.get("params")
        if not isinstance(params, dict):
            raise ValueError("serverRequest/resolved params are malformed")
        request_id = _server_request_id(params.get("requestId"))
        thread_id = _public_uuid7(params.get("threadId"), "resolved request thread id")
        matches = [record for record in self.unresolved(thread_id=thread_id)
                   if record.get("generation") == self.generation
                   and record.get("request_id") == request_id]
        if not matches:
            return None
        if len(matches) != 1:
            raise UnsafeHostState("resolved server request is ambiguous")
        record = matches[0]
        record.update({"state": "resolved", "resolved_at": time.time()})
        _atomic_json(self.path(record["request_id"]), record)
        return record


def read_pending_requests(home: Path, thread_id: str | None, turn_id: str | None = None,
                          current_generation: str | None = None) -> list[dict[str, Any]]:
    """Read durable waits without starting a host, taking a lock, or writing."""
    home = _canonical_home(home)
    directory = home / "state" / "codex" / "approvals"
    if not directory.exists() and not directory.is_symlink():
        return []
    _require_directory(directory)
    rows = []
    for path in sorted(directory.glob("*.json")):
        _require_regular(path)
        value = _read_json(path)
        try:
            generation = value.get("generation") if isinstance(value, dict) else None
            request_id = _server_request_id(value.get("request_id")) \
                if isinstance(value, dict) else None
            expected_key = (_approval_key(generation, request_id)
                            if isinstance(generation, str) and generation else None)
        except (TypeError, ValueError):
            expected_key = None
        if (value is None or value.get("schema") != 1
                or value.get("home") != str(home)
                or value.get("key") != path.stem
                or expected_key != path.stem):
            raise UnsafeHostState(f"Codex approval identity mismatch: {path}")
        if value.get("state") not in CodexApprovalStore._UNRESOLVED:
            continue
        if thread_id is not None and value.get("thread_id") != thread_id:
            continue
        if turn_id is not None and value.get("turn_id") not in (None, turn_id):
            continue
        row = dict(value)
        row["stale"] = (current_generation is not None
                        and row.get("generation") != current_generation)
        rows.append(row)
    return sorted(rows, key=lambda item: item.get("created_at", 0))


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
            if (existing.get("generation") != self.generation
                    and existing.get("state") in {"accepted", "uncertain"}):
                raise HostRejected(
                    f"operation {operation_id} acceptance is uncertain; "
                    "reconcile before retry (another host generation owns it)")
            if existing.get("generation") != self.generation:
                raise HostRejected(
                    f"operation {operation_id} belongs to another host generation")
            return existing
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if not _platform().is_windows:
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

    def commit_handoff_turn_start(
            self, operation_id: str, *, fleet_name: str,
            incarnation_id: str, thread_id: str, turn_id: str,
            canonical_cwd: str, history_watermark: int) -> dict[str, Any]:
        """Settle one accepted supervisor turn from exact public evidence.

        A lost response can leave the original handoff ``turn/start`` uncertain
        even though its sole first turn is publicly visible. This transition is
        intentionally specific: immutable recovery identity, empty-history
        watermark, thread, and returned/observed turn must all agree. It never
        prepares or retries a provider mutation.
        """
        record = self.load(operation_id)
        recovery = record.get("recovery")
        expected = {
            "kind": "supervisor/handoff-turn-start",
            "fleet_name": fleet_name,
            "incarnation_id": incarnation_id,
            "thread_id": thread_id,
            "canonical_cwd": canonical_cwd,
            "history_watermark": history_watermark,
        }
        if (record.get("method") != "rpc"
                or record.get("public_method") != "turn/start"
                or not isinstance(recovery, dict)
                or any(recovery.get(key) != value
                       for key, value in expected.items())
                or history_watermark != 0):
            raise HostRejected(
                f"operation {operation_id} is not the exact handoff turn intent")
        state = record.get("state")
        result = record.get("result")
        if state in {"observed", "committed"}:
            returned_thread = result.get("threadId") \
                if isinstance(result, dict) else None
            returned_turn = result.get("turnId") \
                if isinstance(result, dict) else None
            if returned_turn is None and isinstance(result, dict):
                turn = result.get("turn")
                returned_turn = turn.get("id") if isinstance(turn, dict) else None
            if ((returned_thread is not None and returned_thread != thread_id)
                    or returned_turn != turn_id):
                raise HostRejected(
                    f"operation {operation_id} turn evidence does not match")
        elif state not in {"accepted", "uncertain"}:
            raise HostRejected(
                f"operation {operation_id} cannot be adopted from {state}")
        evidence = {
            "threadId": thread_id,
            "turnId": turn_id,
            "canonicalCwd": canonical_cwd,
            "historyWatermark": history_watermark,
            "adoptedFromPublicRead": True,
        }
        if state in {"accepted", "uncertain"}:
            self._transition(
                operation_id, {"accepted", "uncertain"}, "observed",
                result=evidence)
        if state != "committed":
            return self._transition(
                operation_id, {"observed"}, "committed", result=evidence)
        return record

    def observed_operation(self, operation: Mapping[str, Any]) -> dict[str, Any]:
        """Return a durably observed mutation without sending it again.

        This is the response-loss boundary: the complete immutable intent must
        match the journal, and only an already observed/committed result is
        recoverable.  Prepared, accepted, and uncertain intents remain frozen.
        """
        operation_id = self._validate_id(operation.get("operation_id"))
        method = operation.get("method")
        payload = operation.get("payload", {})
        recovery = operation.get("recovery", {})
        record = self.load(operation_id)
        if (record.get("generation") != self.generation
                or record.get("method") != method
                or record.get("payload_digest") != _digest(method, payload)
                or record.get("recovery") != _public_evidence(recovery)):
            raise HostRejected(
                f"operation {operation_id} does not match its durable intent")
        if record.get("state") not in {"observed", "committed"}:
            raise HostRejected(
                f"operation {operation_id} is {record.get('state')}; exact "
                "provider acceptance is not yet proven")
        if "result" not in record:
            raise HostRejected(
                f"operation {operation_id} has no durable observed result")
        return record

    def worker_turn_id(
            self, operation_id: str, *, fleet_name: str, thread_id: str,
            previous_turn_id: str, canonical_cwd: str) -> str:
        """Read the exact successful worker send; unresolved acceptance stays fenced."""
        record = self.load(operation_id)
        method = record.get("public_method")
        recovery = record.get("recovery")
        expected = {
            "kind": f"worker/{method}", "fleet_name": fleet_name,
            "thread_id": thread_id, "previous_turn_id": previous_turn_id,
            "canonical_cwd": canonical_cwd,
        }
        if (record.get("generation") != self.generation
                or record.get("method") != "rpc"
                or method not in {"turn/start", "turn/steer"}
                or not isinstance(recovery, dict)
                or any(recovery.get(key) != value for key, value in expected.items())
                or record.get("state") not in {"observed", "committed"}):
            raise HostRejected(
                f"operation {operation_id} has no exact successful worker turn result")
        result = record.get("result")
        if not isinstance(result, dict):
            raise HostRejected(f"operation {operation_id} has no worker turn result")
        turn = result.get("turn")
        returned = (turn.get("id") if isinstance(turn, dict) else None
                    ) if method == "turn/start" else result.get("turnId")
        try:
            returned = _public_uuid7(returned, "returned worker turn")
        except ValueError as exc:
            raise HostRejected(f"operation {operation_id} has no genuine returned turn") from exc
        # Never silently prefer one result identity over a conflicting second one.
        identities = [result.get("turnId")]
        if isinstance(turn, dict):
            identities.append(turn.get("id"))
        if (any(value is not None and value != returned for value in identities)
                or (result.get("threadId") is not None
                    and result["threadId"] != thread_id)
                or (method == "turn/steer" and returned != previous_turn_id)
                or (method == "turn/start" and (returned == previous_turn_id
                    or turn.get("status") != "inProgress"))):
            raise HostRejected(f"operation {operation_id} worker turn result conflicts")
        return returned

    def adopt_worker_turn(self, operation_id: str, *, turn_id: str,
                          **identity: Any) -> dict[str, Any]:
        """Commit a proven successful send without replacing its original result.

        Provider history cannot prove an accepted/uncertain send was rejected.
        Only observed/committed success is eligible, and every invocation checks
        the durable returned turn before clearing Fleet's reservation.
        """
        if self.worker_turn_id(operation_id, **identity) != turn_id:
            raise HostRejected(f"operation {operation_id} adopted turn does not match result")
        record = self.commit(operation_id)
        if self.worker_turn_id(operation_id, **identity) != turn_id:
            raise HostRejected(f"operation {operation_id} result changed during adoption")
        return record

    def adopt_spawn_queue_overflow(
            self, operation_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
        """Adopt one spawn mutation from exact post-overflow public evidence.

        This is deliberately narrower than a general ``uncertain -> observed``
        transition.  The host must prove either the operation-tagged empty
        thread and its effective settings, or exactly one turn beyond the
        recorded history watermark.  Nothing here dispatches a provider
        mutation or makes an ambiguous journal entry replayable.
        """
        record = self.load(operation_id)
        recovery = record.get("recovery")
        if (record.get("state") != "uncertain"
                or record.get("method") != "rpc"
                or not isinstance(recovery, dict)
                or not isinstance(result, Mapping)):
            raise HostRejected(
                f"operation {operation_id} is not an uncertain spawn intent")
        public_method = record.get("public_method")
        kind = recovery.get("kind")
        if public_method == "thread/start" and kind == "thread/start":
            thread = result.get("thread")
            expected = recovery.get("expected_effective")
            if not isinstance(thread, Mapping) or not isinstance(expected, dict):
                raise HostRejected(
                    f"operation {operation_id} has incomplete thread evidence")
            approval_policies = expected.get("approval_policies")
            sandbox_types = expected.get("sandbox_types")
            if (not isinstance(approval_policies, list)
                    or not approval_policies
                    or any(not isinstance(value, str)
                           for value in approval_policies)
                    or not isinstance(sandbox_types, list)
                    or not sandbox_types
                    or any(not isinstance(value, str)
                           for value in sandbox_types)):
                raise HostRejected(
                    f"operation {operation_id} has malformed effective settings")
            approval = result.get("approvalPolicy")
            sandbox = result.get("sandbox")
            sandbox_type = sandbox.get("type") if isinstance(sandbox, Mapping) else None
            if (thread.get("id") != result.get("recoveredThreadId")
                    or thread.get("cwd") != recovery.get("canonical_cwd")
                    or result.get("cwd") != recovery.get("canonical_cwd")
                    or thread.get("threadSource") != recovery.get("thread_source")
                    or thread.get("turns") != []
                    or result.get("model") != expected.get("model")
                    or approval not in approval_policies
                    or result.get("approvalsReviewer") != "user"
                    or sandbox_type not in sandbox_types):
                raise HostRejected(
                    f"operation {operation_id} thread evidence does not match intent")
        elif public_method == "turn/start" and kind == "turn/start":
            turn = result.get("turn")
            watermark = recovery.get("history_watermark")
            if (not isinstance(turn, Mapping)
                    or result.get("threadId") != recovery.get("thread_id")
                    or result.get("canonicalCwd") != recovery.get("canonical_cwd")
                    or result.get("historyWatermark") != watermark
                    or not isinstance(watermark, int)
                    or isinstance(watermark, bool)
                    or watermark < 0
                    or result.get("observedTurnCount") != watermark + 1
                    or turn.get("status") not in {
                        "inProgress", "completed", "failed", "interrupted"}):
                raise HostRejected(
                    f"operation {operation_id} turn evidence does not match intent")
        else:
            raise HostRejected(
                f"operation {operation_id} is not a spawn thread/turn intent")
        evidence = _public_evidence(dict(result))
        evidence["adoptedFromQueueOverflow"] = True
        return self._transition(
            operation_id, {"uncertain"}, "observed", result=evidence)

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

    def permits_observed_resume_policy_restore(
            self, operation_id: str, payload: Mapping[str, Any],
            recovery: Mapping[str, Any]) -> bool:
        """Allow only an explicit new resume behind its one observed predecessor.

        The original observation stays observed and is never replayed. The
        caller has already authenticated the mutation; Fleet separately pins
        the held claim, original policy, and public idle turn before dispatch.
        """
        if (not isinstance(payload, dict)
                or payload.get("method") != "thread/resume"
                or not isinstance(payload.get("params"), dict)
                or not isinstance(recovery, dict)
                or recovery.get("kind") != "supervisor/resume-policy-restore"):
            return False
        params = payload["params"]
        original_id = recovery.get("original_resume_operation_id")
        observed_generation = recovery.get("observed_resume_generation")
        if (not isinstance(original_id, str)
                or not original_id.startswith("supervisor-reconcile-")
                or not isinstance(observed_generation, str)
                or observed_generation == self.generation
                or recovery.get("canonical_cwd") != str(self.home)
                or not isinstance(recovery.get("turn_id"), str)
                or params != {
                    "threadId": recovery.get("thread_id"),
                    "excludeTurns": True, "cwd": str(self.home),
                    "model": params.get("model"),
                    "approvalPolicy": "never", "approvalsReviewer": "user",
                    "sandbox": "danger-full-access",
                }
                or not isinstance(params.get("model"), str)
                or not params["model"]):
            return False
        outstanding = [record for record in self.records()
                       if record.get("operation_id") != operation_id
                       and record.get("state") in {
                           "prepared", "accepted", "observed", "uncertain"}]
        if len(outstanding) != 1 or outstanding[0].get("operation_id") != original_id:
            return False
        original = outstanding[0]
        expected_recovery = {
            "kind": "supervisor/thread-resume",
            "fleet_name": recovery.get("fleet_name"),
            "incarnation_id": recovery.get("incarnation_id"),
            "thread_id": recovery.get("thread_id"),
            "previous_host_generation": recovery.get("previous_host_generation"),
            "canonical_cwd": str(self.home),
        }
        expected_digest = _digest("rpc", {"method": "thread/resume", "params": {
            "threadId": recovery.get("thread_id"), "excludeTurns": True}})
        result = original.get("result")
        thread = result.get("thread") if isinstance(result, dict) else None
        sandbox = result.get("sandbox") if isinstance(result, dict) else None
        return (original.get("state") == "observed"
                and original.get("home") == str(self.home)
                and original.get("generation") == observed_generation
                and original.get("method") == "rpc"
                and original.get("public_method") == "thread/resume"
                and original.get("payload_digest") == expected_digest
                and original.get("recovery") == expected_recovery
                and isinstance(thread, dict)
                and thread.get("id") == recovery.get("thread_id")
                and thread.get("cwd") == str(self.home)
                and result.get("cwd") == str(self.home)
                and result.get("model") == params["model"]
                and result.get("approvalPolicy") == "never"
                and result.get("approvalsReviewer") == "user"
                and isinstance(sandbox, dict)
                and sandbox.get("type") == "workspaceWrite")

    def restored_policy_link(
            self, *, fleet_name: str, incarnation_id: str,
            thread_id: str, operation_id: str | None = None) -> dict[str, Any] | None:
        """Prove the committed restoration still has its observed predecessor.

        The committed restoration is the durable anchor. An absent or changed
        original must never make this holder look like an ordinary supervisor.
        """
        records = self.records()
        history = [item for item in records
                   if isinstance(item.get("operation_id"), str)
                   and item["operation_id"].startswith(
                       "supervisor-restore-policy-")
                   and ((isinstance(item.get("recovery"), dict)
                         and item["recovery"].get("thread_id") == thread_id)
                        or (isinstance(item.get("result"), dict)
                            and isinstance(item["result"].get("thread"), dict)
                            and item["result"]["thread"].get("id") ==
                            thread_id))]
        restores = [item for item in history if item.get("state") != "failed"]
        if len(restores) > 1:
            raise HostRejected("restored supervisor has ambiguous restoration history")
        outstanding = [item for item in records
                       if item.get("operation_id") != operation_id
                       and item.get("state") in {
                           "prepared", "accepted", "observed", "uncertain"}]
        if not history and not outstanding:
            return None
        if not restores:
            raise HostRejected("unresolved supervisor intent lacks exact restoration")
        restored = restores[0]
        restore_recovery = restored.get("recovery")
        if not isinstance(restore_recovery, dict):
            raise HostRejected("restored supervisor recovery link is malformed")
        original_id = restore_recovery.get("original_resume_operation_id")
        originals = [item for item in records
                     if item.get("operation_id") == original_id]
        if len(originals) != 1:
            raise HostRejected(
                "restored supervisor committed restoration lost its original resume")
        original = originals[0]
        if len(outstanding) != 1:
            raise HostRejected("restored supervisor has another unresolved intent")
        if outstanding[0] != original:
            raise HostRejected("restored supervisor original is not observed")
        old_recovery = original.get("recovery")
        old_result = original.get("result")
        old_thread = old_result.get("thread") if isinstance(old_result, dict) else None
        old_sandbox = old_result.get("sandbox") if isinstance(old_result, dict) else None
        prior_generation = (old_recovery.get("previous_host_generation")
                            if isinstance(old_recovery, dict) else None)
        expected_old_recovery = {
            "kind": "supervisor/thread-resume", "fleet_name": fleet_name,
            "incarnation_id": incarnation_id, "thread_id": thread_id,
            "previous_host_generation": prior_generation,
            "canonical_cwd": str(self.home),
        }
        if (not isinstance(original_id, str)
                or not original_id.startswith("supervisor-reconcile-")
                or not isinstance(prior_generation, str)
                or not prior_generation
                or original.get("state") != "observed"
                or original.get("home") != str(self.home)
                or not isinstance(original.get("generation"), str)
                or original["generation"] == prior_generation
                or original.get("method") != "rpc"
                or original.get("public_method") != "thread/resume"
                or original.get("payload_digest") != _digest("rpc", {
                    "method": "thread/resume", "params": {
                        "threadId": thread_id, "excludeTurns": True}})
                or old_recovery != expected_old_recovery
                or not isinstance(old_thread, dict)
                or old_thread.get("id") != thread_id
                or old_thread.get("cwd") != str(self.home)
                or old_result.get("cwd") != str(self.home)
                or not isinstance(old_result.get("model"), str)
                or not old_result["model"]
                or old_result.get("approvalPolicy") != "never"
                or old_result.get("approvalsReviewer") != "user"
                or not isinstance(old_sandbox, dict)
                or old_sandbox.get("type") != "workspaceWrite"):
            raise HostRejected("observed predecessor is not the exact old resume")
        turn_id = restore_recovery.get("turn_id")
        model = old_result["model"]
        expected_restore_recovery = {
            "kind": "supervisor/resume-policy-restore",
            "fleet_name": fleet_name, "incarnation_id": incarnation_id,
            "thread_id": thread_id, "turn_id": turn_id,
            "previous_host_generation": prior_generation,
            "observed_resume_generation": original["generation"],
            "original_resume_operation_id": original_id,
            "canonical_cwd": str(self.home),
        }
        restore_payload = {"method": "thread/resume", "params": {
            "threadId": thread_id, "excludeTurns": True,
            "cwd": str(self.home), "model": model,
            "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": "danger-full-access"}}
        restored_result = restored.get("result")
        restored_thread = (restored_result.get("thread")
                           if isinstance(restored_result, dict) else None)
        restored_sandbox = (restored_result.get("sandbox")
                            if isinstance(restored_result, dict) else None)
        restored_profile = (restored_result.get("activePermissionProfile")
                            if isinstance(restored_result, dict) else None)
        if (not isinstance(restored.get("operation_id"), str)
                or not restored["operation_id"].startswith(
                    "supervisor-restore-policy-")
                or restored.get("state") != "committed"
                or restored.get("home") != str(self.home)
                or not isinstance(restored.get("generation"), str)
                or restored["generation"] == original["generation"]
                or restored.get("method") != "rpc"
                or restored.get("public_method") != "thread/resume"
                or restored.get("payload_digest") != _digest(
                    "rpc", restore_payload)
                or restore_recovery != expected_restore_recovery
                or not isinstance(turn_id, str) or not turn_id
                or not isinstance(restored_thread, dict)
                or restored_thread.get("id") != thread_id
                or restored_thread.get("cwd") != str(self.home)
                or restored_result.get("cwd") != str(self.home)
                or restored_result.get("model") != model
                or restored_result.get("approvalPolicy") != "never"
                or restored_result.get("approvalsReviewer") != "user"
                or restored_sandbox != {"type": "dangerFullAccess"}
                or (isinstance(restored_profile, dict)
                    and restored_profile.get("id") == ":workspace")):
            raise HostRejected("committed restoration does not prove exact policy")
        return {
            "original_operation_id": original_id,
            "original_generation": original["generation"],
            "original_digest": _digest("restored-predecessor", original),
            "restore_operation_id": restored["operation_id"],
            "restore_generation": restored["generation"],
            "restore_digest": _digest("committed-restoration", restored),
            "turn_id": turn_id,
            "model": model,
        }

    def has_restoration_history_for_thread(self, thread_id: str) -> bool:
        """Find an anchored restore even if its original is now missing."""
        if not isinstance(thread_id, str) or not thread_id:
            return False
        for record in self.records():
            operation_id = record.get("operation_id")
            if (not isinstance(operation_id, str)
                    or not operation_id.startswith(
                        "supervisor-restore-policy-")):
                continue
            recovery = record.get("recovery")
            result = record.get("result")
            restored_thread = (result.get("thread")
                               if isinstance(result, dict) else None)
            if ((isinstance(recovery, dict)
                 and recovery.get("thread_id") == thread_id)
                    or (isinstance(restored_thread, dict)
                        and restored_thread.get("id") == thread_id)):
                return True
        return False

    def permits_restored_supervisor_continuation(
            self, operation_id: str, payload: Mapping[str, Any],
            recovery: Mapping[str, Any]) -> bool:
        """Allow only a linked restored holder's explicit next mutation."""
        if (not isinstance(payload, dict)
                or not isinstance(payload.get("params"), dict)
                or not isinstance(recovery, dict)
                or not isinstance(recovery.get("restored_predecessor"), dict)
                or recovery.get("canonical_cwd") != str(self.home)):
            return False
        kind = recovery.get("kind")
        method = payload.get("method")
        if kind not in {"supervisor/turn/start", "supervisor/turn/steer",
                        "supervisor/restored-continuation-reattach"}:
            return False
        try:
            link = self.restored_policy_link(
                fleet_name=recovery.get("fleet_name"),
                incarnation_id=recovery.get("incarnation_id"),
                thread_id=recovery.get("thread_id"),
                operation_id=operation_id)
        except HostRejected:
            return False
        if link is None or recovery["restored_predecessor"] != link:
            return False
        params = payload["params"]
        thread_id = recovery.get("thread_id")
        if kind == "supervisor/restored-continuation-reattach":
            return (method == "thread/resume"
                    and link["restore_generation"] != self.generation
                    and recovery.get("previous_host_generation") ==
                    link["restore_generation"]
                    and recovery.get("turn_id") == link["turn_id"]
                    and params == {
                        "threadId": thread_id, "excludeTurns": True,
                        "cwd": str(self.home), "model": link["model"],
                        "approvalPolicy": "never", "approvalsReviewer": "user",
                        "sandbox": "danger-full-access"})
        if method not in {"turn/start", "turn/steer"} or kind != \
                f"supervisor/{method}":
            return False
        if link["restore_generation"] != self.generation:
            reattachments = [item for item in self.records()
                             if item.get("state") == "committed"
                             and item.get("generation") == self.generation
                             and isinstance(item.get("recovery"), dict)
                             and item["recovery"].get("kind") ==
                             "supervisor/restored-continuation-reattach"
                             and item["recovery"].get(
                                 "restored_predecessor") == link]
            if len(reattachments) != 1:
                return False
            reattached = reattachments[0]
            reattached_result = reattached.get("result")
            reattached_thread = (reattached_result.get("thread")
                                 if isinstance(reattached_result, dict) else None)
            if (reattached.get("public_method") != "thread/resume"
                    or reattached.get("home") != str(self.home)
                    or reattached.get("method") != "rpc"
                    or reattached.get("recovery") != {
                        "kind": "supervisor/restored-continuation-reattach",
                        "fleet_name": recovery.get("fleet_name"),
                        "incarnation_id": recovery.get("incarnation_id"),
                        "thread_id": thread_id, "turn_id": link["turn_id"],
                        "previous_host_generation": link["restore_generation"],
                        "canonical_cwd": str(self.home),
                        "restored_predecessor": link}
                    or reattached.get("payload_digest") != _digest(
                        "rpc", {"method": "thread/resume", "params": {
                            "threadId": thread_id, "excludeTurns": True,
                            "cwd": str(self.home), "model": link["model"],
                            "approvalPolicy": "never",
                            "approvalsReviewer": "user",
                            "sandbox": "danger-full-access"}})
                    or not isinstance(reattached_thread, dict)
                    or reattached_thread.get("id") != thread_id
                    or reattached_thread.get("cwd") != str(self.home)
                    or reattached_result.get("cwd") != str(self.home)
                    or reattached_result.get("model") != link["model"]
                    or reattached_result.get("approvalPolicy") != "never"
                    or reattached_result.get("approvalsReviewer") != "user"
                    or reattached_result.get("sandbox") !=
                    {"type": "dangerFullAccess"}
                    or (isinstance(reattached_result.get(
                        "activePermissionProfile"), dict)
                        and reattached_result[
                            "activePermissionProfile"].get("id") ==
                        ":workspace")):
                return False
        bound_turn = link["turn_id"]
        later_turns = [item for item in self.records()
                       if item.get("state") == "committed"
                       and isinstance(item.get("recovery"), dict)
                       and item["recovery"].get("kind") ==
                       "supervisor/turn/start"
                       and item["recovery"].get("fleet_name") ==
                       recovery.get("fleet_name")
                       and item["recovery"].get("incarnation_id") ==
                       recovery.get("incarnation_id")
                       and item["recovery"].get("thread_id") == thread_id
                       and item["recovery"].get("restored_predecessor") == link]
        if later_turns:
            if any(isinstance(item.get("committed_at"), bool)
                   or not isinstance(item.get("committed_at"), (int, float))
                   for item in later_turns):
                return False
            latest = max(later_turns, key=lambda item: item["committed_at"])
            if sum(item["committed_at"] == latest["committed_at"]
                   for item in later_turns) != 1:
                return False
            latest_result = latest.get("result")
            latest_turn = (latest_result.get("turn")
                           if isinstance(latest_result, dict) else None)
            if (not isinstance(latest_turn, dict)
                    or not isinstance(latest_turn.get("id"), str)
                    or not latest_turn["id"]):
                return False
            bound_turn = latest_turn["id"]
        if (params.get("threadId") != thread_id
                or not isinstance(params.get("input"), list)
                or not params["input"]
                or recovery.get("previous_turn_id") != bound_turn):
            return False
        if method == "turn/steer":
            return params.get("expectedTurnId") == recovery["previous_turn_id"]
        return set(params) == {"threadId", "input"}


class CodexHostClient:
    def __init__(self, home: Path, metadata: Mapping[str, Any], encoded_key: str,
                 authkey: bytes) -> None:
        self.home = home
        self.state_dir = home / "state" / "codex"
        self.metadata_path = self.state_dir / "host.json"
        self.key_path = self.state_dir / "host.key"
        self.generation = str(metadata["generation"])
        self.codex_version = metadata.get("codex_version")
        self.schema_digest = metadata.get("schema_digest")
        self.protocol_version = metadata["codex_protocol_version"]
        self._endpoint = metadata["endpoint"]
        self._transport = metadata["transport"]
        self._encoded_key = encoded_key
        self._authkey = authkey
        self._pid = metadata["pid"]
        self._process_identity = metadata["process_identity"]
        self.host_pid = self._pid
        self.host_process_identity = self._process_identity
        self.started_at = metadata["started_at"]
        self.app_server_pid = metadata["app_server_pid"]
        self.app_server_process_identity = metadata[
            "app_server_process_identity"]
        self.app_server_started_at = metadata["app_server_started_at"]
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
        schema_command: Sequence[str] | None = None,
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

        child_env = dict(os.environ if env is None else env)
        child_env.pop("CLAUDE_CODE_SESSION_ID", None)
        schema_command_argv = list(
            ["codex"] if schema_command is None else schema_command)

        with _host_lock(state_dir / "codex-host.lock", ready_timeout):
            _validate_fixed_paths(state_dir)
            existing = cls._existing(home)
            if existing is not None and existing._ping(0.5):
                return existing
            if (existing is not None
                    and (not existing._metadata_stale() or existing._owner_live())):
                raise HostUnavailable("Codex host is busy or unresponsive; refusing replacement")
            schema_manifest = _reviewed_schema_manifest(
                schema_command_argv, env=child_env, cwd=home)
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
                "--schema-manifest", str(schema_manifest),
                "--schema-command-json", json.dumps(schema_command_argv),
                "--idle-timeout", str(idle_timeout),
            ]
            popen_args: dict[str, Any] = {
                "cwd": str(home),
                "env": child_env,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if _platform().is_windows:
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
        endpoint, transport = _endpoint_for(home, state_dir)
        required = {
            "schema", "home", "generation", "endpoint", "transport", "ready",
            "ipc_protocol_version", "codex_protocol_version", "codex_version",
            "schema_digest", "heartbeat",
            "pid", "process_identity", "started_at",
            "app_server_pid", "app_server_process_identity",
            "app_server_started_at",
        }
        if not required.issubset(metadata) or metadata.get("home") != str(home):
            raise UnsafeHostState("Codex host metadata has wrong home or missing fields")
        version = metadata.get("codex_version")
        schema_manifest = (REVIEWED_SCHEMA_MANIFESTS.get(version)
                           if isinstance(version, str) else None)
        if schema_manifest is None:
            raise UnsafeHostState(
                "Codex host metadata names an unreviewed Codex version")
        try:
            manifest = json.loads(schema_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise UnsafeHostState(
                "reviewed Codex schema manifest is unreadable") from exc
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
                or not metadata["process_identity"]
                or not isinstance(metadata.get("started_at"), (int, float))
                or not isinstance(metadata.get("app_server_pid"), int)
                or metadata["app_server_pid"] <= 0
                or not isinstance(
                    metadata.get("app_server_process_identity"), str)
                or not metadata["app_server_process_identity"]
                or not isinstance(
                    metadata.get("app_server_started_at"), (int, float))):
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
            matches = _process_identities_match(self._process_identity, current)
            if matches is not None:
                return matches
        try:
            os.kill(self._pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True

    def _app_server_live(self) -> bool:
        """Conservatively identify the child from the exact host metadata."""
        current = _process_identity(self.app_server_pid)
        if current is not None:
            matches = _process_identities_match(
                self.app_server_process_identity, current)
            if matches is not None:
                return matches
        try:
            os.kill(self.app_server_pid, 0)
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
        if method == "rpc":
            authorize_failed_client_recovery_rpc(
                self.home, self.generation, operation_id, payload, digest)
        elif method in {"host/shutdown", "host/shutdown-restored",
                        "host/shutdown-cancelled-approval"}:
            authorize_failed_client_recovery_shutdown(
                self.home, self.generation, operation_id, method=method)
        public_method = _public_method(method, payload)
        if public_method is not None:
            params = payload.get("params") if isinstance(payload, dict) else None
            target = params.get("threadId") if isinstance(params, dict) else None
            authorize_failed_client_recovery_operation(
                self.home, self.generation, operation_id, public_method, target,
                digest)
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
        def response_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate IPC response key")
                value[key] = item
            return value

        def invalid_constant(_value):
            raise ValueError("non-finite IPC response constant")

        try:
            response = json.loads(raw.decode("utf-8"), object_pairs_hook=response_object,
                                  parse_constant=invalid_constant)
        except (UnicodeError, ValueError) as exc:
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
        if (set(response) != {*expected, "ok", "result", "error"}
                or type(response.get("ok")) is not bool
                or (response["ok"] and response["error"] is not None)
                or (not response["ok"] and (
                    response["result"] is not None
                    or not isinstance(response["error"], str)
                    or not response["error"]
                    or len(response["error"]) > 300))):
            raise HostUnavailable("Codex host response envelope is malformed" + (
                "; mutation outcome is uncertain" if public_method is not None else ""))
        if response["ok"] is False:
            error = response["error"]
            if public_method is not None:
                if error == "host response exceeds MAX_IPC_BYTES; page the request":
                    raise HostUnavailable(error + "; mutation outcome is uncertain")
                try:
                    state = OperationJournal(self.home, self.generation).load(
                        operation_id).get("state")
                except (OSError, ValueError, FleetCliError) as exc:
                    raise HostUnavailable(
                        error + "; mutation journal is unreadable") from exc
                if state not in {"prepared", "failed"}:
                    # The provider write begins only after accepted is durable.
                    # Even a generic host error after that boundary is not a
                    # rejection and must not trigger a handoff rollback.
                    raise HostUnavailable(
                        error + "; mutation outcome is uncertain")
            raise HostRejected(error)
        return CodexObservation(operation_id, self.generation, digest,
                                response.get("result"))

    def config_requirements(self, timeout: float = 10.0) -> Any:
        """Read managed requirements before any provider mutation is prepared."""
        operation = {
            "operation_id": f"config-requirements-{uuid.uuid4()}",
            "method": "rpc",
            "payload": {"method": "configRequirements/read", "params": {}},
        }
        return self.call(operation, timeout=timeout).result

    def pending_approvals(self, thread_id: str,
                          turn_id: str | None = None) -> list[dict[str, Any]]:
        operation = {
            "operation_id": f"approval-list-{uuid.uuid4()}",
            "method": "approval/list",
            "payload": {"thread_id": thread_id, "turn_id": turn_id},
        }
        result = self.call(operation, timeout=5).result
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise HostUnavailable("Codex host returned malformed approval state")
        return result

    def supervisor_approval_reservation_supported(self) -> bool:
        """A running host must itself advertise the approval boundary fence."""
        operation = {
            "operation_id": f"approval-reservation-capability-{uuid.uuid4()}",
            "method": "approval/supervisor-reservation-v1", "payload": {},
        }
        return self.call(operation, timeout=5).result == {"version": 1}

    def respond_approval(self, request_id: str, thread_id: str,
                         turn_id: str, decision: Any,
                         timeout: float = 10.0,
                         supervisor_reservation: Mapping[str, Any] | None = None
                         ) -> dict[str, Any]:
        """Consume one current durable request; the host rejects every replay."""
        operation = {
            "operation_id": f"approval-response-{uuid.uuid4()}",
            "method": "approval/respond",
            "payload": {
                "request_id": request_id, "thread_id": thread_id,
                "turn_id": turn_id, "decision": decision,
            },
        }
        if supervisor_reservation is not None:
            operation["payload"]["supervisor_reservation"] = dict(supervisor_reservation)
        result = self.call(operation, timeout=timeout).result
        if not isinstance(result, dict):
            raise HostUnavailable("Codex host returned malformed approval response state")
        return result

    def commit(self, operation_id: str) -> None:
        OperationJournal(self.home, self.generation).commit(operation_id)

    def recover_observed(self, operation: Mapping[str, Any]) -> CodexObservation:
        """Recover one exact durable result; never contact the provider host."""
        record = OperationJournal(
            self.home, self.generation).observed_operation(operation)
        return CodexObservation(
            record["operation_id"], record["generation"],
            record["payload_digest"], record["result"])

    def commit_handoff_turn_start(self, operation_id: str, **evidence: Any) -> None:
        OperationJournal(self.home, self.generation).commit_handoff_turn_start(
            operation_id, **evidence)

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
    if _platform().is_windows:
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
    "CodexApprovalStore", "CodexHostClient", "CodexObservation", "HostRejected",
    "HostUnavailable", "OperationJournal", "ReconcileReport", "UnsafeHostState",
    "connect_existing", "read_pending_requests", "reconcile_home",
]
