"""Shared owner-safe file lock; no registry or claim reads/writes."""
from __future__ import annotations

import os
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from fleet_errors import FleetCliError

try:
    import fcntl
except ImportError:  # Windows has no POSIX inode locking.
    fcntl = None

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_STALE_SECONDS = 30.0
LOCK_RETRY_INTERVAL_SECONDS = 0.05


class FleetLockTimeout(Exception):
    """Raised when state/fleet.lock could not be acquired within the timeout."""


def _fleet_lock_live_owner(path: Path) -> bool:
    """A delayed live owner must not be mistaken for a stale crashed owner."""
    try:
        raw = path.read_text(encoding="ascii")
        modern = "|" in raw
        parts = raw.split("|", 2) if modern else raw.split(":", 1)
        pid = int(parts[0])
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, UnicodeError, IndexError):
        return False
    # The original token format contained only PID and nonce. Treat a live
    # PID as ambiguous rather than unlinking a lock that might still be held.
    if not modern or len(parts) != 3:
        return True
    if parts[1] == "unknown":
        return True
    try:
        from fleet_codex import _process_identities_match, _process_identity
        observed = _process_identity(pid)
        if not isinstance(observed, str):
            return True
        matches = _process_identities_match(parts[1], observed)
        return matches is not False
    except Exception:  # noqa: BLE001 -- unknown liveness cannot authorize unlink
        return True


def _fleet_lock_same_file(fd: int, path: Path) -> bool:
    """A pathname may have changed while a contender waited for its inode."""
    try:
        opened = os.fstat(fd)
        named = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISREG(opened.st_mode) and stat.S_ISREG(named.st_mode)
            and (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino))


@contextmanager
def registry_lock(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS, *,
                  stale_seconds=LOCK_STALE_SECONDS,
                  retry_interval=LOCK_RETRY_INTERVAL_SECONDS,
                  live_owner=_fleet_lock_live_owner,
                  same_file=_fleet_lock_same_file, kernel_lock=fcntl):
    """Lock an explicit state path; this module contains no state writers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    from fleet_codex import _process_identity
    identity = _process_identity(os.getpid()) or "unknown"
    token = f"{os.getpid()}|{identity}|{uuid.uuid4().hex}"

    def retry_or_timeout() -> None:
        if time.monotonic() >= deadline:
            raise FleetLockTimeout(f"timed out waiting for lock: {path}")

    while fd is None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            if kernel_lock is not None:
                # Keep a kernel lock on this inode through the whole registry
                # transaction. A stale breaker must acquire the same lock
                # before it may unlink the name. This closes the race between
                # two contenders that both inspected an old stale pathname.
                kernel_lock.flock(fd, kernel_lock.LOCK_EX)
                if not same_file(fd, path):
                    os.close(fd)
                    fd = None
                    retry_or_timeout()
                    continue
        except FileExistsError:
            try:
                info = path.lstat()
            except FileNotFoundError:
                retry_or_timeout()
                continue  # someone else already broke/released it; retry immediately
            if not stat.S_ISREG(info.st_mode):
                raise FleetCliError(f"unsafe non-regular lock path: {path}")
            age = time.time() - info.st_mtime
            if age > stale_seconds and kernel_lock is not None:
                try:
                    stale_fd = os.open(str(path), os.O_RDONLY
                                       | getattr(os, "O_NOFOLLOW", 0)
                                       | getattr(os, "O_NONBLOCK", 0))
                except FileNotFoundError:
                    retry_or_timeout()
                    continue
                try:
                    try:
                        kernel_lock.flock(stale_fd, kernel_lock.LOCK_EX | kernel_lock.LOCK_NB)
                    except BlockingIOError:
                        pass
                    else:
                        if same_file(stale_fd, path):
                            try:
                                current = path.lstat()
                            except FileNotFoundError:
                                current = None
                            if (current is not None
                                    and time.time() - current.st_mtime > stale_seconds
                                    and not live_owner(path)):
                                try:
                                    path.unlink()
                                except FileNotFoundError:
                                    pass
                                retry_or_timeout()
                                continue
                finally:
                    os.close(stale_fd)
            elif age > stale_seconds and not live_owner(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                retry_or_timeout()
                continue
            retry_or_timeout()
            time.sleep(retry_interval)
        except PermissionError as denied:
            # Windows delete-pending lock names can raise PermissionError instead of EEXIST.
            # A present name is contention: poll under the deadline without stale-breaking,
            # because unlink can also be denied. An absent name means directory access failed;
            # re-raise that error instead of reporting a misleading lock timeout.
            try:
                info = path.lstat()
            except FileNotFoundError:
                raise denied
            if not stat.S_ISREG(info.st_mode):
                raise FleetCliError(f"unsafe non-regular lock path: {path}")
            retry_or_timeout()
            time.sleep(retry_interval)
    try:
        os.write(fd, token.encode("utf-8"))
    except OSError:
        # O_EXCL proves this file is ours. On token-write failure, close and remove it
        # so other acquirers are not stranded; cleanup must preserve the original error.
        try:
            if same_file(fd, path):
                path.unlink()
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    try:
        if kernel_lock is None:
            os.close(fd)
        yield
    finally:
        # Compare-and-delete: only unlink if the lock file still holds our
        # token. A successor may have broken our (apparently stale) lock and
        # now owns it -- deleting blindly here would cascade (F1).
        try:
            current = path.read_bytes()
        except (FileNotFoundError, OSError):
            current = None
        if current == token.encode("utf-8"):
            try:
                if kernel_lock is None or same_file(fd, path):
                    path.unlink()
            except (FileNotFoundError, OSError):
                pass
        if kernel_lock is not None:
            os.close(fd)
