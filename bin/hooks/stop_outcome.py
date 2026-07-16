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
import re
import sys
import time
from pathlib import Path

RESULT_TEXT_MAX = 20000

_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._-]+")

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
        # Roll-up item 4: same partial-write check as bin/fleet.py's copy --
        # a torn JSONL line is silently skipped by read_outcomes otherwise.
        if not ok or written.value != len(data):
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


def _valid_token(value):
    """Reject anything that isn't a plain, filename-safe token. Ported
    verbatim from postcompact_journal.py::_valid_token (fix wave, T2 review
    "Important" finding: this hook builds out_dir / f"{key}.jsonl" from
    exactly the same two untrusted sources -- a registry-resolved name or a
    raw session_id -- so it needs the same traversal guard, e.g. against
    "../secret" or an absolute path.)"""
    if not value:
        return False
    if ".." in value:
        return False
    if os.path.basename(value) != value:
        return False
    if not _SAFE_TOKEN_RE.fullmatch(value):
        return False
    return True


def _resolve_name(home: Path, sid: str):
    """READ-ONLY registry lookup (invariant 6: hooks never write fleet.json).

    Defensive isinstance guards against a syntactically-valid but
    wrong-shaped fleet.json (top-level document not a dict, "workers" not a
    dict, an individual worker record not a dict) -- adversarial review
    trap 6: without these guards an AttributeError from e.g. `[1,2].items()`
    used to escape this function entirely, unwind into main()'s outer
    handler, and skip the record write altogether for that turn (silent
    outcome loss, worse than a wrong record). Also validates the resolved
    name as a safe path token (see _valid_token) before returning it, same
    as postcompact_journal.py::_resolve_name, so a malformed registry name
    never reaches the outcome path -- callers fall back to sid instead."""
    try:
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        workers = data.get("workers")
        if not isinstance(workers, dict):
            return None
        for name, rec in workers.items():
            if isinstance(rec, dict) and rec.get("session_id") == sid:
                return name if _valid_token(name) else None
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
        # Coerce BEFORE validation/matching so a non-str session_id (e.g. a
        # JSON int) both matches str-typed registry session_ids and lands in
        # the written record as a str (fix wave, adversarial Minor finding).
        sid = str(sid)
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
        # Path-safety parity with postcompact_journal.py: validate BOTH the
        # resolved registry name (done inside _resolve_name) and the raw
        # session_id fallback before using either as a path component. An
        # unsafe sid (e.g. "..\\evil", an absolute path, embedded path
        # separators) must not reach out_dir / f"{key}.jsonl" at all.
        key = _resolve_name(home, sid) or sid
        if not _valid_token(key):
            _log_hook_error(home, f"unsafe outcome path token: {key!r}")
            return 0
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
