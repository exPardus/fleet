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

_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._~-]+")

_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


def _atomic_append_bytes(path: Path, data: bytes) -> None:
    """Single-syscall atomic append; mirrors bin/fleet.py's PLATFORM
    adapter exactly (see _WindowsPlatform.atomic_append_bytes for the
    empirical record-loss evidence behind the Win32 path). This hook may
    not import fleet.py (standalone doctrine), so it carries its own
    two-branch copy: FILE_APPEND_DATA handle on Windows, O_APPEND on
    POSIX (where the kernel performs seek+write atomically -- the CRT
    O_APPEND emulation race is Windows-only)."""
    if os.name == "nt":
        _atomic_append_bytes_win32(path, data)
    else:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise OSError(
                    f"short append to {path}: {written}/{len(data)} bytes")
        finally:
            os.close(fd)


def _atomic_append_bytes_win32(path: Path, data: bytes) -> None:
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


_ARGV_HOME_FLAG = "--fleet-home"


def _argv_fleet_home():
    """§5 step 1, for a plane that has no `main()` to apply it in: the
    `--fleet-home` the worker-settings hook command baked into this process's
    own argv (multi-fleet slice (c)).

    STRUCTURALLY UNABLE TO RAISE, and that is the point rather than a nicety.
    SPEC invariant 2 is exit-0 hooks: a hook that raises renders a traceback
    into a worker's session on every tool call. Every operation here is a
    bounds-checked index or a `str` method on a `sys.argv` element, so an
    unknown flag, a missing value, a repeated flag and a nonsense path all
    return a value or `None` -- never an exception.

    Grammar deliberately matches `fleet.strip_global_fleet_home`, which is what
    `bin/fleet.py`'s own `main()` uses on the same option string: both
    `--fleet-home V` and `--fleet-home=V`, and a bare `--` ends the options.

    A REPEATED FLAG WITH TWO DIFFERENT VALUES RETURNS `None`. `fleet.py`
    refuses it outright (*"One invocation names one home"*); a hook has no
    refusal available to it, so it declines the contradictory input and falls
    to the next step -- the same decision, tiered by what the plane can do.
    """
    argv = sys.argv[1:]
    found = None
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            break
        if tok == _ARGV_HOME_FLAG and i + 1 < len(argv):
            value, i = argv[i + 1], i + 2
        elif tok.startswith(_ARGV_HOME_FLAG + "="):
            value, i = tok.split("=", 1)[1], i + 1
        else:
            i += 1
            continue
        if found is not None and value != found:
            return None
        found = value
    return found or None


def _fleet_home() -> Path:
    """§5's resolution order, as much of it as a hook can run.

    step 1  `--fleet-home` argv  -- the home the DISPATCH baked in. New in
                                    multi-fleet slice (c); before it, a hook
                                    could not learn its home at all.
    step 2  sid->home lookup     -- SKIPPED: it costs one registry read per
                                    listed home on every hook firing, and the
                                    argv makes it unnecessary -- dispatch
                                    already knows which home it dispatched for.
    step 3  `FLEET_HOME` env     -- unchanged, and still a WORKING input: the
                                    daemon substitutes environments wholesale,
                                    and interactive sessions and the suite
                                    address a home through it.
    step 4  legacy install root  -- unchanged: derived from this file's own
                                    path, bin/hooks/stop_outcome.py -> bin/hooks -> bin -> repo root.
    step 5  terminus             -- SKIPPED: its content is "mutating verbs
                                    refuse", and this plane cannot refuse.

    ARGV BEATS ENV. On a hosted body the environment is the daemon donor's,
    not this body's -- multi-fleet's cross-fleet interference audit calls those
    values *"donor facts; fenced by hook argv"*. The argv is the fence and the
    env is what it fences. The argv value is NOT validated before it wins:
    validating it and falling through on failure would trade a broken bake for
    a write into the donor's home, which is the exact incident class the fence
    exists to close.
    """
    argv_home = _argv_fleet_home()
    if argv_home:
        return Path(argv_home)
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
        # errors="replace" + a net wider than OSError: this is the REPORTER,
        # and it must not become the next thing that raises. `message` reaches
        # here as repr(exc) today (ASCII-safe), but a future caller passing raw
        # text with a lone surrogate would raise UnicodeEncodeError -- a
        # ValueError, which the old `except OSError` did not catch -- out of
        # the caller's own except block and out of main(), turning a logged
        # diagnostic into a crashed hook. Belt-and-braces only: the fix for the
        # lost record is at the _atomic_append_bytes call in main(), not here.
        with (state / "hook-errors.log").open(
                "a", encoding="utf-8", errors="replace") as f:
            f.write(f"{ts} stop_outcome: {flat}\n")
    except Exception:  # noqa: BLE001 -- the reporter never changes the exit code
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


def _read_stdin_payload() -> str:
    """The hook payload as text, decoded as UTF-8 -- NOT with the process
    locale.

    `sys.stdin.read()` decodes with the locale encoding, which on this
    machine is cp1252. The harness sends UTF-8. Every non-ASCII character in
    the payload therefore arrived double-decoded: U+2014 EM DASH (UTF-8
    `e2 80 94`) was stored in the outcome record as the three characters
    `â€”`. Measured across the 130 live sessions in
    `state/outcomes` on 2026-07-30: of the 124 records whose `result_text`
    was comparable against its own transcript, **76 differed from the
    transcript by exactly this transform and nothing else** -- undoing
    cp1252->utf-8 made them byte-identical.

    That corruption is a defect in its own right (the operator reads a
    mangled report), and it is also what made the transcript-vs-payload
    comparison in `main` impossible to do exactly. Both are fixed here, in
    one place: read BYTES and decode UTF-8 explicitly.

    `errors="replace"` (not strict) keeps the hook's never-crash contract:
    an undecodable payload yields a record with a sanitised character, never
    a lost turn. The `getattr` fallback keeps the function working when
    `sys.stdin` has been replaced by a text object with no `.buffer` (tests
    that drive `main()` in-process)."""
    buf = getattr(sys.stdin, "buffer", None)
    raw = buf.read() if buf is not None else sys.stdin.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return raw


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
    never reaches the outcome path -- callers fall back to sid instead.

    Fix wave 1 (CRIT-1): a supervisor BODY name is pipe-delimited
    (`sup|<id>|boot`, three-tier SS10.1) and `|` is invalid in Windows
    filenames -- apply the SAME `|` -> `~` stem mapping fleet.name_fs_stem
    applies (duplicated here by necessity: hooks never import fleet.py),
    BEFORE the token validation, so the supervisor's outcome lands
    name-keyed exactly where fleet-side read_outcomes(name) looks for it.
    The mapping never widens the traversal guard -- _valid_token still runs
    on the mapped value and `~` joins its charset."""
    try:
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        workers = data.get("workers")
        if not isinstance(workers, dict):
            return None
        for name, rec in workers.items():
            if isinstance(rec, dict) and rec.get("session_id") == sid:
                stem = name.replace("|", "~") if isinstance(name, str) else name
                return stem if _valid_token(stem) else None
    except (OSError, ValueError):
        pass
    return None


def _transcript_result(transcript_path):
    """(text, input_tokens, output_tokens, cache_creation, cache_read, model)
    from the LAST assistant record -- the tail is bookkeeping, never 'read last
    line' (contract).

    three-tier §11.2 (B2): context occupancy is the SUM of the three prompt
    summands input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
    Recording all three (belt-and-braces, additive schema) lets a third party
    read the supervisor's occupancy without being the supervisor."""
    text = tokens_in = tokens_out = cache_creation = cache_read = model = None
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return text, tokens_in, tokens_out, cache_creation, cache_read, model
    # ONE assistant message is written as SEVERAL transcript records -- one per
    # content block (thinking, then tool_use, then text) -- all carrying the
    # same `message.id` and the same `message.usage`. The previous loop tracked
    # `text` and the usage fields INDEPENDENTLY: `text` only advanced on a
    # record that had a text block, while usage advanced on every assistant
    # record. So the returned text and the returned numbers routinely described
    # two DIFFERENT messages, and the caller had no way to tell. Group by
    # `message.id` instead, and reset the text when the id changes, so
    # everything returned describes the LAST assistant message in the file and
    # `main` can check whether that is the message the turn actually ended on.
    last_id = _NO_ID = object()
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
        msg_id = msg.get("id")
        # A new message starts: nothing carried over from the previous one.
        # `None` ids (a transcript shape that omits them) are treated as
        # always-new, which is the conservative reading -- it can only make
        # the text more recent, never staler.
        if last_id is _NO_ID or msg_id is None or msg_id != last_id:
            last_id = msg_id
            text = None
        parts = [c.get("text") for c in msg.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if parts:
            text = "\n".join(parts)
        usage = msg.get("usage")
        if isinstance(usage, dict):
            tokens_in = usage.get("input_tokens")
            tokens_out = usage.get("output_tokens")
            cache_creation = usage.get("cache_creation_input_tokens")
            cache_read = usage.get("cache_read_input_tokens")
        if msg.get("model"):
            model = msg.get("model")
    return text, tokens_in, tokens_out, cache_creation, cache_read, model


def main() -> int:
    home = _fleet_home()
    try:
        payload = json.loads(_read_stdin_payload() or "{}")
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
        tokens_in = tokens_out = cache_creation = cache_read = model = None
        if transcript_path:
            (t_text, tokens_in, tokens_out,
             cache_creation, cache_read, model) = _transcript_result(transcript_path)
            # THE TOKEN COUNTS ARE PUBLISHED ONLY IF THEY CAN BE PROVED TO
            # DESCRIBE THE MESSAGE THE TURN ENDED ON.
            #
            # This hook reads the transcript FILE, which the harness is still
            # appending to: the record for the final assistant message is
            # frequently not there yet when the hook reads. Measured over the
            # 130 live sessions in `state/outcomes` on 2026-07-30, comparing
            # each session's final outcome record against its own completed
            # transcript: 95 of 130 (73%) carried the usage of the
            # SECOND-TO-LAST message, 35 carried the final one. Nothing in the
            # record said which -- so `out=` in `fleet status` was an
            # arbitrary earlier message's output, rendered as this turn's, and
            # the resulting ratio to any real quantity was unbounded and
            # unpatterned (9.5x-89x across four workers).
            #
            # The payload is NOT subject to that race: `last_assistant_message`
            # is handed to the hook by the harness, and over those same 130
            # sessions it matched the transcript's final assistant message in
            # every comparable case (124/124; 5 more were truncated at
            # RESULT_TEXT_MAX and 1 was corrupted beyond comparison by the
            # cp1252 stdin defect `_read_stdin_payload` now fixes). So the
            # payload text is the authority on WHICH message is last, and
            # comparing it against the text of the message the usage came from
            # is an exact test -- no tolerance, no heuristic -- of whether this
            # hook saw the end of the turn.
            #
            # Compare BEFORE the RESULT_TEXT_MAX truncation below, or every
            # report longer than 20,000 characters would fail the check for
            # the wrong reason.
            #
            # Unproved -> the four token fields stay None. Both consumers
            # already handle None correctly and neither needs a change:
            # `_native_token_summary` omits the `out=`/`in=` part entirely
            # (fleet.py: `if outcome.get("output_tokens") is not None`), and
            # `_native_cumulative_tokens` skips non-int values. An absent
            # counter is a true statement; a stale one is not.
            #
            # `model` is deliberately NOT withheld -- see the report; it is
            # not a magnitude and it is stable across the messages of a
            # session, so the previous message's model is still the right
            # answer where the previous message's token count is not.
            if not (isinstance(text, str) and isinstance(t_text, str)
                    and text == t_text):
                tokens_in = tokens_out = cache_creation = cache_read = None
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
                  "cache_creation_input_tokens": cache_creation,
                  "cache_read_input_tokens": cache_read,
                  "model": model, "transcript_path": transcript_path}
        line = json.dumps(record, ensure_ascii=False)
        # errors="replace", not a bare .encode(): `ensure_ascii=False` keeps
        # every character of the report verbatim in `line`, and a worker's
        # result text can contain a LONE SURROGATE -- e.g. U+DC90 inside a
        # mojibake run, a markdown-table arrow mangled by a
        # cp1252/utf-8 round-trip in the worker's own tool output. A strict
        # encode raises UnicodeEncodeError('surrogates not allowed') and the
        # whole record is lost: 2026-07-27, worker `gate-hf-rb` emitted a
        # 14,760-character ESCALATE report carrying a CRITICAL finding, this
        # line raised at offset 7034, the exception was swallowed into
        # hook-errors.log, and `fleet result` reported "no outcome record".
        # PRIORITY: the record is always written; the offending character is
        # sanitised, never truncated (`replace` is one-for-one, so the report's
        # length and every legitimate non-ASCII character survive). This is the
        # SAME convention `_transcript_result` already reads with, not a second
        # one -- and it covers every payload-sourced field in the record
        # (result_text, transcript_path, model), not just the one that failed.
        _atomic_append_bytes(out_dir / f"{key}.jsonl",
                             (line + "\n").encode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001 -- hooks never crash the turn
        _log_hook_error(home, repr(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
