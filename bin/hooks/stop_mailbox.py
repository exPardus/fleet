"""Stop hook: turn-end mailbox drain / stop-block. See docs/SPEC.md sec 7.

Standalone, stdlib only. Never imports bin/fleet.py. Invoked by Claude
Code (per worker-settings.json) as a subprocess, fed hook-event JSON on
stdin. Exception-proof: ANY error results in a silent exit 0 (allow the
stop), because an uncaught traceback would surface on stderr as noise in
the worker's transcript.

Honors stop_hook_active politely: it is read but never branched on. No
custom loop counter is implemented here -- if mail is present we block
again regardless of stop_hook_active, and Claude Code's native 8-block
force-allow is what caps a runaway loop (continuation past that also
requires fresh manager mail, so there is nothing left for us to guard).
"""
import json
import os
import re
import sys
import time

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def _valid_session_id(session_id):
    """Reject anything that isn't a plain, filename-safe token. Guards
    against path traversal via session_id (e.g. "../secret" or an
    absolute path) reaching _mailbox_path unvalidated."""
    if not session_id:
        return False
    if ".." in session_id:
        return False
    if os.path.basename(session_id) != session_id:
        return False
    if not _SESSION_ID_RE.fullmatch(session_id):
        return False
    return True


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


def _fleet_home():
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
                                    path, bin/hooks/stop_mailbox.py -> bin/hooks -> bin -> repo root.
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
        return argv_home
    env = os.environ.get("FLEET_HOME")
    if env:
        return env
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _mailbox_path(session_id, fleet_home=None):
    home = fleet_home if fleet_home is not None else _fleet_home()
    return os.path.join(home, "mailbox", f"{session_id}.md")


def _log_hook_error(session_id, exc, fleet_home=None):
    """Kernel 1: append ONE diagnostic line to state/hook-errors.log so a
    swallowed hook exception is not invisible. Best-effort, no lock, single
    line (`timestamp session_id exception-repr`). Wrapped in its own
    try/except so a logging failure NEVER changes the caller's exit code --
    the exit-0-on-any-error invariant is absolute."""
    try:
        home = fleet_home if fleet_home is not None else _fleet_home()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sid = session_id if session_id else "?"
        sid = str(sid).replace("\r", " ").replace("\n", " ")
        rep = repr(exc).replace("\r", " ").replace("\n", " ")
        path = os.path.join(home, "state", "hook-errors.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{ts} {sid} {rep}\n")
    except Exception:
        pass


def _ceiling_path(session_id, fleet_home=None):
    home = fleet_home if fleet_home is not None else _fleet_home()
    return os.path.join(home, "state", "ceilings", session_id)


def _read_ceiling(session_id, fleet_home=None):
    """Kernel 10: read the sid-keyed token ceiling (an integer) written by
    fleet.py's launch path. READ-ONLY. Returns the ceiling int, or None on
    any failure (missing file / unreadable / non-numeric) -- a None ceiling
    means 'no ceiling in force', so the hook keeps its existing behavior."""
    try:
        with open(_ceiling_path(session_id, fleet_home), "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _current_tokens(transcript_path):
    """Kernel 10: best-effort current token count from the JSONL transcript
    (sum of input+output tokens across usage records). Returns an int, or
    None if the transcript is absent/unreadable -- None means 'can't prove
    over-ceiling', so the hook falls through to its conservative existing
    behavior (it never wrongly ALLOWS a stop it can't justify)."""
    if not transcript_path:
        return None
    try:
        total = 0
        # errors="replace": a strict decode raises UnicodeDecodeError (a
        # ValueError, NOT caught by the `except OSError` below), which escapes
        # main() and skips the entire mailbox drain -- pending mail is left
        # undelivered by a failure in a best-effort token count. Same ruling as
        # postcompact_journal.py::_transcript_stats.
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                usage = None
                msg = rec.get("message")
                if isinstance(msg, dict):
                    usage = msg.get("usage")
                if not isinstance(usage, dict):
                    usage = rec.get("usage")
                if isinstance(usage, dict):
                    for key in ("input_tokens", "output_tokens"):
                        val = usage.get(key)
                        if isinstance(val, int):
                            total += val
        return total
    except OSError:
        return None


def _claim(mailbox_file):
    """Atomically claim mailbox_file by renaming it to a pid-suffixed
    sibling so concurrent hook invocations never deliver the same message
    twice. Returns the claimed path, or None if there was nothing to
    claim: the file was missing, another process's claim already won the
    race (FileNotFoundError), or a transient NTFS lock from a concurrent
    append didn't clear even after one retry (PermissionError)."""
    claimed_file = f"{mailbox_file}.claimed.{os.getpid()}"
    try:
        os.replace(mailbox_file, claimed_file)
        return claimed_file
    except FileNotFoundError:
        return None
    except PermissionError:
        time.sleep(0.05)
        try:
            os.replace(mailbox_file, claimed_file)
            return claimed_file
        except OSError:
            return None


def _read_and_discard(claimed_file):
    """Read the claimed file's contents then delete it (best-effort).

    errors="replace" (incident `outcome-surrogate`, 2026-07-28): by the time
    this runs, `_claim` has ALREADY renamed the mailbox and the `finally`
    below will delete it -- so a strict decode raising UnicodeDecodeError does
    not defer the message, it DESTROYS it. Same class as the lost outcome
    record: an irreversible step had already happened when the codec raised.
    A mangled byte costs one character; a strict decode costs the message."""
    try:
        with open(claimed_file, "r", encoding="utf-8", errors="replace") as f:
            contents = f.read()
    finally:
        try:
            os.remove(claimed_file)
        except OSError:
            pass
    return contents


def main(state=None):
    data = json.load(sys.stdin)
    session_id = data.get("session_id")
    if state is not None:
        state["sid"] = session_id
    if not _valid_session_id(session_id):
        return
    # data.get("stop_hook_active") intentionally unused -- see module
    # docstring: no custom loop counter, native force-allow handles it.

    # Kernel 10 (hook-side): if a token ceiling is in force AND the worker is
    # provably over it, ALLOW stop even with mail pending. We return BEFORE
    # touching the mailbox so pending mail is NOT claimed/drained -- it stays
    # visible via idle+mail for the next launch. The hook can only ever ALLOW
    # here; it never gains blocking power from the ceiling. Any doubt (no
    # ceiling / unreadable ceiling / no transcript) falls through to the
    # existing block-on-mail behavior below.
    ceiling = _read_ceiling(session_id)
    if ceiling is not None:
        current = _current_tokens(data.get("transcript_path"))
        if current is not None and current >= ceiling:
            return

    mailbox_file = _mailbox_path(session_id)
    claimed_file = _claim(mailbox_file)
    if claimed_file is None:
        return

    contents = _read_and_discard(claimed_file)
    if not contents.strip():
        return

    print(json.dumps({"decision": "block", "reason": contents}))


if __name__ == "__main__":
    _state = {"sid": None}
    try:
        main(_state)
    except Exception as _exc:
        _log_hook_error(_state["sid"], _exc)
    sys.exit(0)
