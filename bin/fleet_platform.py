"""Shared platform adapter for Fleet core and the standalone Codex host."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

# === PLATFORM ADAPTER START (SPEC §14 portability mandate) ===
# Only this block branches on os.name/sys.platform or uses OS-specific primitives.
# All other code calls PLATFORM; source-scan tests enforce that boundary.

_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


def _process_descendants(rows, root_pid):
    by_parent = {}
    for row in rows:
        by_parent.setdefault(row["ppid"], []).append(row)
    found = []
    pending = list(by_parent.get(root_pid, ()))
    seen = set()
    while pending:
        row = pending.pop()
        pid = row["pid"]
        if pid in seen:
            continue
        seen.add(pid)
        found.append(row)
        pending.extend(by_parent.get(pid, ()))
    return found


def _parse_elapsed(value):
    days = 0
    clock = value.strip()
    if "-" in clock:
        day, clock = clock.split("-", 1)
        days = int(day)
    parts = [int(part) for part in clock.split(":")]
    if len(parts) == 2:
        hours, minutes, seconds = 0, parts[0], parts[1]
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(value)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


class UnsupportedPlatformError(NotImplementedError):
    """A platform operation with no implementation on the current OS.
    main() renders this exception as a concise failure instead of a traceback.
    """


class _WindowsPlatform:
    """Windows implementation of every OS-specific fleet operation."""

    is_windows = True
    is_linux = False

    def memory_available_mb(self) -> int:
        """Windows has no portable MemAvailable implementation in Fleet."""
        raise UnsupportedPlatformError("available memory is unsupported on Windows")

    def process_tree(self, root_pid: int) -> list:
        script = (
            "$now=[DateTimeOffset]::UtcNow; $rows=@(Get-CimInstance Win32_Process | "
            "ForEach-Object {$age=$null; if ($_.CreationDate) {$age=[int]($now-"
            "[DateTimeOffset]$_.CreationDate).TotalSeconds}; [pscustomobject]@{"
            "pid=[int]$_.ProcessId;ppid=[int]$_.ParentProcessId;age_seconds=$age;"
            "command=$(if ($_.CommandLine) {$_.CommandLine} else {$_.Name})}}); "
            "ConvertTo-Json -Compress -InputObject $rows")
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5)
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        payload = json.loads(proc.stdout)
        if isinstance(payload, dict):
            payload = [payload]
        rows = []
        for row in payload if isinstance(payload, list) else ():
            try:
                rows.append({"pid": int(row["pid"]), "ppid": int(row["ppid"]),
                             "age_seconds": float(row["age_seconds"]),
                             "command": str(row.get("command") or "")})
            except (KeyError, TypeError, ValueError):
                continue
        return _process_descendants(rows, int(root_pid))

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Append bytes with one FILE_APPEND_DATA-only WriteFile call.
        Windows CRT O_APPEND performs seek and write separately, risking lost records
        across concurrent handles. The kernel append handle avoids that race;
        a short write raises because a torn JSONL record would otherwise be skipped.
        """
        kernel32 = ctypes.windll.kernel32
        from ctypes import wintypes

        create_file_w = kernel32.CreateFileW
        create_file_w.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        create_file_w.restype = wintypes.HANDLE

        handle = create_file_w(
            str(path), _FILE_APPEND_DATA, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            None, _OPEN_ALWAYS, _FILE_ATTRIBUTE_NORMAL, None,
        )
        if handle in (0, wintypes.HANDLE(-1).value):
            raise OSError(f"CreateFileW failed for {path}: {ctypes.WinError()}")
        try:
            written = wintypes.DWORD(0)
            ok = kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None)
            # A short write tears a JSONL record; raise instead of silently losing it.
            if not ok or written.value != len(data):
                raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")
        finally:
            kernel32.CloseHandle(handle)


class _PosixPlatform:
    """POSIX implementation of every OS-specific fleet operation."""

    is_windows = False
    is_linux = sys.platform.startswith("linux")

    def memory_available_mb(self) -> int:
        """Read Linux MemAvailable; other POSIX platforms are explicit gaps."""
        if not self.is_linux:
            raise UnsupportedPlatformError(
                "available memory is unsupported on this POSIX platform")
        try:
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        except (FileNotFoundError, OSError, ValueError, IndexError, UnicodeError):
            raise UnsupportedPlatformError(
                "Linux MemAvailable is unavailable") from None
        raise UnsupportedPlatformError("Linux MemAvailable is unavailable")

    def process_tree(self, root_pid: int) -> list:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,etime=,args="], capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=5)
        if proc.returncode != 0:
            return []
        rows = []
        for line in proc.stdout.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) != 4:
                continue
            try:
                rows.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                             "age_seconds": _parse_elapsed(parts[2]),
                             "command": parts[3]})
            except ValueError:
                continue
        return _process_descendants(rows, int(root_pid))

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Append bytes with one O_APPEND write, atomically seeking to EOF on POSIX.
        A short write raises because a torn JSONL record would otherwise be skipped.
        """
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise OSError(
                    f"short append to {path}: {written}/{len(data)} bytes")
        finally:
            os.close(fd)


# The one and only os.name branch in this module: selects which adapter
# instance PLATFORM points at. Fleet core and the Codex host do not inspect
# os.name or sys.platform (enforced by a source-scan test, test_steering.py).
PLATFORM = _WindowsPlatform() if os.name == "nt" else _PosixPlatform()

# === PLATFORM ADAPTER END ===
