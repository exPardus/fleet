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
PROCESS_TREE_MAX_NODES = 64
PROCESS_TREE_OUTPUT_MAX_BYTES = 16384
PROCESS_TREE_TIMEOUT_SECONDS = 5
PROCESS_TREE_EXECUTABLE_MAX_CHARS = 128


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
            "$ErrorActionPreference='SilentlyContinue';"
            f"$root={int(root_pid)};$limit={PROCESS_TREE_MAX_NODES};"
            f"$outputLimit={PROCESS_TREE_OUTPUT_MAX_BYTES};"
            f"$nameLimit={PROCESS_TREE_EXECUTABLE_MAX_CHARS};"
            "$now=[DateTimeOffset]::UtcNow;"
            "$queue=New-Object 'System.Collections.Generic.Queue[int]';"
            "$seen=New-Object 'System.Collections.Generic.HashSet[int]';"
            "$rows=New-Object 'System.Collections.Generic.List[object]';"
            "$queue.Enqueue($root);[void]$seen.Add($root);"
            "while($queue.Count -gt 0 -and $rows.Count -lt $limit){"
            "$parent=$queue.Dequeue();$remaining=$limit-$rows.Count;"
            "$children=@(Get-CimInstance Win32_Process -Filter "
            "('ParentProcessId = '+$parent)|Select-Object -First $remaining);"
            "foreach($child in $children){$childPid=[int]$child.ProcessId;"
            "if(-not $seen.Add($childPid)){continue};$name=[string]$child.Name;"
            "if($name.Length -gt $nameLimit){$name=$name.Substring(0,$nameLimit)};"
            "$age=$null;if($child.CreationDate){$age=[int]($now-"
            "[DateTimeOffset]$child.CreationDate).TotalSeconds};"
            "[void]$rows.Add([pscustomobject]@{pid=$childPid;age_seconds=$age;"
            "executable=$name});$queue.Enqueue($childPid);"
            "if($rows.Count -ge $limit){break}}};"
            "$json=ConvertTo-Json -Compress -InputObject @($rows);"
            "$bytes=[Text.Encoding]::UTF8.GetBytes($json);"
            "if($bytes.Length -le $outputLimit){[Console]::Out.Write($json)}")
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PROCESS_TREE_TIMEOUT_SECONDS)
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        if len(proc.stdout.encode("utf-8", "replace")) > PROCESS_TREE_OUTPUT_MAX_BYTES:
            return []
        try:
            payload = json.loads(proc.stdout)
        except (TypeError, ValueError):
            return []
        if isinstance(payload, dict):
            payload = [payload]
        rows = []
        for row in (payload[:PROCESS_TREE_MAX_NODES]
                    if isinstance(payload, list) else ()):
            try:
                rows.append({"pid": int(row["pid"]),
                             "age_seconds": float(row["age_seconds"]),
                             "executable": str(row.get("executable") or "")[
                                 :PROCESS_TREE_EXECUTABLE_MAX_CHARS]})
            except (KeyError, TypeError, ValueError):
                continue
        return rows

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
        script = r'''
root=$1
limit=$2
byte_limit=$3
{
    queue=$root
    seen=" $root "
    count=0
    while [ -n "$queue" ] && [ "$count" -lt "$limit" ]; do
        parent=${queue%% *}
        if [ "$queue" = "$parent" ]; then queue=; else queue=${queue#* }; fi
        remaining=$((limit - count))
        children=$(pgrep -P "$parent" 2>/dev/null | head -n "$remaining")
        for pid in $children; do
            case "$pid" in ''|*[!0-9]*) continue ;; esac
            case "$seen" in *" $pid "*) continue ;; esac
            seen="$seen$pid "
            ps -p "$pid" -o pid= -o ppid= -o etime= -o comm= 2>/dev/null | head -n 1
            if [ -n "$queue" ]; then queue="$queue $pid"; else queue=$pid; fi
            count=$((count + 1))
            [ "$count" -ge "$limit" ] && break
        done
    done
} | head -c "$byte_limit"
'''
        proc = subprocess.run(
            ["sh", "-c", script, "fleet-process-tree", str(int(root_pid)),
             str(PROCESS_TREE_MAX_NODES), str(PROCESS_TREE_OUTPUT_MAX_BYTES)],
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=PROCESS_TREE_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            return []
        if len(proc.stdout.encode("utf-8", "replace")) > PROCESS_TREE_OUTPUT_MAX_BYTES:
            return []
        rows = []
        for line in proc.stdout.splitlines()[:PROCESS_TREE_MAX_NODES]:
            parts = line.strip().split(None, 3)
            if len(parts) != 4:
                continue
            try:
                rows.append({"pid": int(parts[0]), "ppid": int(parts[1]),
                             "age_seconds": _parse_elapsed(parts[2]),
                             "executable": parts[3][
                                 :PROCESS_TREE_EXECUTABLE_MAX_CHARS]})
            except ValueError:
                continue
        return rows

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
