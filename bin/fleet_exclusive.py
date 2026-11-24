"""Box-wide exclusive run lock: `fleet exclusive -- CMD`.

Lanes share one host. A full pytest run, a `buf` generation or a docker
database run must not overlap box-wide, and lanes used to coordinate that
with ad-hoc background waiters that `pgrep` other lanes' processes. One lane
waited for hours on a run that had ended long before. This module replaces
those waiters with one fleet-owned lock.

The lock is one JSON file per machine (`~/.claude/fleet-exclusive.json`, or
`$FLEET_EXCLUSIVE_LOCK`), created with O_EXCL. It records the holder (the
lane name from `$FLEET_WORKER`, else the caller), the pid and process
identity of the `fleet exclusive` process, the child pid, the start time, the
TTL, a label and the command. A holder is stale when neither recorded process
is alive (checked by pid and start identity, so a reused pid does not count),
or when it has outlived its TTL; a waiter then takes the lock over. A waiter
polls in the foreground for at most `--wait-max` seconds and then fails with
the holder named, never silently. The command's exit status is returned, and
the lock is released on every exit path, including a signal.
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TTL_SECONDS = 4 * 3600
DEFAULT_WAIT_SECONDS = 1800
MAX_WAIT_SECONDS = 4 * 3600
POLL_SECONDS = 5.0
WAIT_TIMEOUT_EXIT = 75
LOCK_MAX_BYTES = 64 * 1024


def lock_path() -> Path:
    override = os.environ.get("FLEET_EXCLUSIVE_LOCK")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "fleet-exclusive.json"


def _now() -> float:
    return time.time()


def _iso(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _identity(pid: int):
    try:
        from fleet_codex import _process_identity
        return _process_identity(pid)
    except Exception:  # noqa: BLE001 -- identity is a refinement, never required
        return None


def pid_alive(pid, identity=None) -> bool:
    """True when `pid` runs and, if an identity was recorded, is that process."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if not isinstance(identity, str):
        return True
    try:
        from fleet_codex import _process_identities_match
        current = _identity(pid)
        if not isinstance(current, str):
            return True
        match = _process_identities_match(identity, current)
        return True if match is None else bool(match)
    except Exception:  # noqa: BLE001
        return True


def read_holder(path=None):
    """The current holder record, or None when free or unreadable."""
    path = Path(path or lock_path())
    try:
        if path.is_symlink() or path.stat().st_size > LOCK_MAX_BYTES:
            return {"unreadable": "unsafe lock file"}
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError):
        return {"unreadable": "lock file unreadable"}
    return value if isinstance(value, dict) else {"unreadable": "lock file malformed"}


def stale_reason(holder, now=None):
    """Why this holder no longer holds the lock, or None while it does."""
    if holder is None:
        return None
    if "unreadable" in holder:
        return holder["unreadable"]
    now = _now() if now is None else now
    started = holder.get("started_at_epoch")
    ttl = holder.get("ttl_seconds")
    if (isinstance(started, (int, float)) and isinstance(ttl, (int, float))
            and now - started > ttl):
        return f"held {int(now - started)} s, past its {int(ttl)} s TTL"
    owner_alive = pid_alive(holder.get("pid"), holder.get("identity"))
    child_alive = pid_alive(holder.get("child_pid"), holder.get("child_identity"))
    if not owner_alive and not child_alive:
        return f"holder pid {holder.get('pid')} and child {holder.get('child_pid')} are gone"
    return None


def describe(holder, now=None) -> str:
    now = _now() if now is None else now
    if holder is None:
        return "free"
    if "unreadable" in holder:
        return f"unreadable ({holder['unreadable']})"
    started = holder.get("started_at_epoch")
    age = f"{int(now - started)} s" if isinstance(started, (int, float)) else "?"
    return (f"held by {holder.get('holder')} (pid {holder.get('pid')}, "
            f"child {holder.get('child_pid')}) for {age}: "
            f"{holder.get('label') or holder.get('command')}")


def _write_new(path: Path, record: dict) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(record, stream, sort_keys=True)
    return True


def _update(path: Path, record: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _take_over(path: Path, holder: dict) -> bool:
    """Move a stale lock aside; only one waiter wins.

    The compare and the rename run under an flock on a sidecar file, so a
    second waiter that judged the same stale holder cannot move aside the
    lock the first waiter has just created.
    """
    aside = path.with_name(f"{path.name}.stale-{uuid.uuid4().hex[:8]}")
    guard = path.with_name(f".{path.name}.guard")
    try:
        import fcntl
    except ImportError:
        fcntl = None
    try:
        fd = os.open(str(guard), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return False
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        if read_holder(path) != holder:
            return False
        os.replace(path, aside)
    except OSError:
        return False
    finally:
        os.close(fd)
    try:
        aside.unlink()
    except OSError:
        pass
    return True


def release(path: Path, token: str) -> bool:
    """Remove the lock only while it is still this token's."""
    holder = read_holder(path)
    if not isinstance(holder, dict) or holder.get("token") != token:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def acquire(record: dict, *, wait_max: float, path=None, sleep=time.sleep,
            clock=time.monotonic, out=None):
    """Hold the lock or return (None, last holder) after `wait_max` seconds."""
    out = sys.stderr if out is None else out
    path = Path(path or lock_path())
    deadline = clock() + max(0.0, wait_max)
    announced = None
    while True:
        if _write_new(path, record):
            return record, None
        holder = read_holder(path)
        reason = stale_reason(holder)
        if reason is not None:
            print(f"fleet exclusive: taking over a stale lock ({reason}): "
                  f"{describe(holder)}", file=out)
            _take_over(path, holder)
            continue
        if holder is None:
            continue
        if announced != holder.get("token"):
            announced = holder.get("token")
            print(f"fleet exclusive: waiting (at most {int(wait_max)} s) -- "
                  f"{describe(holder)}", file=out)
        if clock() >= deadline:
            return None, holder
        sleep(min(POLL_SECONDS, max(0.0, deadline - clock())))


def run(command, *, holder_name, label=None, ttl=DEFAULT_TTL_SECONDS,
        wait_max=DEFAULT_WAIT_SECONDS, path=None, sleep=time.sleep,
        clock=time.monotonic, popen=subprocess.Popen, out=None) -> int:
    """Run `command` while holding the box-wide lock; return its exit code."""
    out = sys.stderr if out is None else out
    if not command:
        raise ValueError("fleet exclusive: give a command after --")
    path = Path(path or lock_path())
    wait_max = min(max(0.0, float(wait_max)), MAX_WAIT_SECONDS)
    started = _now()
    token = uuid.uuid4().hex
    record = {
        "schema": 1, "token": token, "holder": holder_name,
        "pid": os.getpid(), "identity": _identity(os.getpid()),
        "child_pid": None, "child_identity": None,
        "host": socket.gethostname(), "started_at": _iso(started),
        "started_at_epoch": started, "ttl_seconds": int(ttl),
        "label": label, "command": " ".join(command)[:500],
    }
    held, holder = acquire(record, wait_max=wait_max, path=path, sleep=sleep,
                           clock=clock, out=out)
    if held is None:
        print(f"fleet exclusive: gave up after {int(wait_max)} s -- "
              f"{describe(holder)}. Run later, or check `fleet exclusive "
              "--status`.", file=out)
        return WAIT_TIMEOUT_EXIT
    previous = {}

    def stop(signum, _frame):
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if signum is not None:
            try:
                previous[signum] = signal.signal(signum, stop)
            except (ValueError, OSError):
                pass
    child = None
    try:
        child = popen(list(command))
        record["child_pid"] = child.pid
        record["child_identity"] = _identity(child.pid)
        _update(path, record)
        return child.wait()
    finally:
        try:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(10)
                except subprocess.TimeoutExpired:
                    child.kill()
        finally:
            release(path, token)
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass
