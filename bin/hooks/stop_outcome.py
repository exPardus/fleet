"""Stop hook: append a terminal-outcome record (M-B, spec sec 5 outcome
discriminator). Result text = payload last_assistant_message (feature-detect;
value shape UNOBSERVED at 2.1.207) with transcript-tail fallback (last
type=="assistant" record's message.content[].text -- contract Result/cost).
Never blocks, never prints to stdout, always exits 0. Writes ONLY the outcome
file and hook-errors.log (sanctioned list, spec sec 3 amendment).

Standalone, stdlib only. Never imports bin/fleet.py -- duplicates its own
tiny helpers (_fleet_home, _log_hook_error, _resolve_name) per the
established pattern in stop_mailbox.py / postcompact_journal.py.

The outcome append uses the SAME Win32 FILE_APPEND_DATA-only atomic-append
approach as bin/fleet.py's _atomic_append_bytes (added in the T1 fix wave):
plain open(..., "a") buffered appends lose whole records under concurrent
writers on Windows (TOCTOU race in the CRT's O_APPEND emulation). This hook
and a fleet-side tombstone writer can both append to the same outcome file
"at the same instant", so the atomic single-syscall append is required here
too, not just in fleet.py.
"""
import ctypes
import json
import os
import sys
import time
from pathlib import Path

RESULT_TEXT_MAX = 20000

_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


def _atomic_append_bytes(path: Path, data: bytes) -> None:
    """Single-syscall atomic append; mirrors bin/fleet.py's
    _atomic_append_bytes exactly (see that function's docstring for the
    empirical record-loss evidence this fixes). ctypes/kernel32 only, no
    platform-detection branch (this build targets Windows only, SPEC sec 14)."""
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
        if not ok:
            raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")
    finally:
        kernel32.CloseHandle(handle)


def _fleet_home() -> Path:
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def _log_hook_error(home: Path, message: str) -> None:
    try:
        state = home / "state"
        state.mkdir(parents=True, exist_ok=True)
        flat = " ".join(str(message).split())
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with (state / "hook-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"{ts} stop_outcome: {flat}\n")
    except OSError:
        pass


def _resolve_name(home: Path, sid: str):
    """READ-ONLY registry lookup (invariant 6: hooks never write fleet.json)."""
    try:
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        for name, rec in data.get("workers", {}).items():
            if isinstance(rec, dict) and rec.get("session_id") == sid:
                return name
    except (OSError, ValueError):
        pass
    return None


def _transcript_result(transcript_path):
    """(text, input_tokens, output_tokens, model) from the LAST assistant
    record -- the tail is bookkeeping, never 'read last line' (contract)."""
    text = tokens_in = tokens_out = model = None
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return text, tokens_in, tokens_out, model
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        parts = [c.get("text") for c in msg.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if parts:
            text = "\n".join(parts)
        usage = msg.get("usage")
        if isinstance(usage, dict):
            tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("output_tokens")
        if msg.get("model"):
            model = msg.get("model")
    return text, tokens_in, tokens_out, model


def main() -> int:
    home = _fleet_home()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        sid = payload.get("session_id")
        if not sid:
            return 0
        transcript_path = payload.get("transcript_path")
        text = payload.get("last_assistant_message")
        if not isinstance(text, str):
            text = None
        tokens_in = tokens_out = model = None
        if transcript_path:
            t_text, tokens_in, tokens_out, model = _transcript_result(transcript_path)
            if text is None:
                text = t_text
        if isinstance(text, str) and len(text) > RESULT_TEXT_MAX:
            text = text[:RESULT_TEXT_MAX]
        key = _resolve_name(home, sid) or sid
        out_dir = home / "state" / "outcomes"
        out_dir.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "session_id": sid, "kind": "result", "result_text": text,
                  "input_tokens": tokens_in, "output_tokens": tokens_out,
                  "model": model, "transcript_path": transcript_path}
        line = json.dumps(record, ensure_ascii=False)
        _atomic_append_bytes(out_dir / f"{key}.jsonl", (line + "\n").encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 -- hooks never crash the turn
        _log_hook_error(home, repr(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
