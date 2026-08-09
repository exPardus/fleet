"""PostCompact hook: fail-silent journal landmark. See docs/SPEC.md sec 7.

Standalone, stdlib only. Never imports bin/fleet.py. Invoked by Claude
Code (per worker-settings.json) as a subprocess, fed hook-event JSON on
stdin AFTER a context compaction. Appends ONE mechanical line to the
worker's own journal (state/journals/<name>.md) so a fresh session sees
where compaction happened. Never blocks, never loud, exit 0 always.

Event name verified real against the installed CLI (claude 2.1.204 ships a
PostCompact hook event; C1 review recorded 2.1.203). The event's stdin
carries session_id + transcript_path + trigger, but NO turn/token field --
those are derived best-effort from the JSONL transcript.

Journals are keyed by worker NAME but the hook receives only session_id, so
it resolves session_id -> name via a READ-ONLY, failure-tolerant read of
state/fleet.json (single-writer invariant 6: hooks never write the
registry). On ANY resolution failure it falls back to a sid-keyed journal
(state/journals/<sid>.md) or, if the sid itself is unsafe, SKIPS -- it
never guesses a name and never writes the wrong worker's journal.
"""
import json
import os
import re
import sys
import time

_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9._~-]+")


def _valid_token(value):
    """Reject anything that isn't a plain, filename-safe token. Guards the
    journal path against traversal via session_id or a malformed registry
    name (e.g. "../secret" or an absolute path)."""
    if not value:
        return False
    if ".." in value:
        return False
    if os.path.basename(value) != value:
        return False
    if not _SAFE_TOKEN_RE.fullmatch(value):
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
                                    path, bin/hooks/postcompact_journal.py -> bin/hooks -> bin -> repo root.
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


def _log_hook_error(session_id, exc, fleet_home=None):
    """Kernel 1: append ONE diagnostic line to state/hook-errors.log so a
    swallowed hook exception is not invisible. Best-effort, no lock, single
    line. Wrapped so a logging failure never changes the exit code."""
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


def _registry_path(fleet_home):
    return os.path.join(fleet_home, "state", "fleet.json")


def _resolve_name(session_id, fleet_home):
    """READ-ONLY sid->name lookup in state/fleet.json. Returns the worker
    NAME whose record carries this session_id, or None on any failure
    (missing/locked/corrupt registry, sid not found, unsafe name). Never
    writes; never raises out."""
    try:
        with open(_registry_path(fleet_home), "r", encoding="utf-8") as f:
            reg = json.load(f)
        # Wrong-shape defense (same as stop_outcome.py::_resolve_name): a
        # syntactically-valid but non-dict document (e.g. a top-level list)
        # would raise AttributeError from .get() below, escape the
        # (OSError, ValueError) net, and skip the landmark write entirely.
        if not isinstance(reg, dict):
            return None
        workers = reg.get("workers", {})
        if not isinstance(workers, dict):
            return None
        for name, rec in workers.items():
            if isinstance(rec, dict) and rec.get("session_id") == session_id:
                # Fix wave 1 (CRIT-1): map a pipe-delimited supervisor BODY
                # name (`sup|<id>|boot`) onto the same `|` -> `~` on-disk
                # stem fleet.name_fs_stem uses (duplicated by necessity:
                # hooks never import fleet.py), BEFORE validation -- the
                # landmark then lands in the journal fleet-side
                # journal_file_path(name) reads. `~` joins _SAFE_TOKEN_RE's
                # charset; the traversal guard still runs on the mapped value.
                stem = name.replace("|", "~") if isinstance(name, str) else name
                return stem if _valid_token(stem) else None
    except (OSError, ValueError):
        return None
    return None


def _transcript_stats(transcript_path):
    """Best-effort (turns, tokens) from the JSONL transcript. turns = count
    of non-empty JSONL records; tokens = sum of input+output tokens across
    usage records. Either is None if the transcript is absent/unreadable or
    carries no usage -- rendered as '?' in the landmark."""
    turns = None
    tokens = None
    if not transcript_path:
        return turns, tokens
    try:
        count = 0
        total = 0
        saw_tokens = False
        # errors="replace" (incident `outcome-surrogate`, 2026-07-28): these
        # stats are BEST-EFFORT ('?' is a legal rendering), but a strict decode
        # of an undecodable transcript raises UnicodeDecodeError -- a
        # ValueError, which `except OSError` below does NOT catch. It escaped
        # main() and took the whole landmark with it: a best-effort number
        # silently killed the mandatory write. Matches stop_outcome.py's
        # _transcript_result, which has always read transcripts this way.
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
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
                            saw_tokens = True
        turns = count
        if saw_tokens:
            tokens = total
    except OSError:
        return None, None
    return turns, tokens


def _journal_path(fleet_home, key):
    return os.path.join(fleet_home, "state", "journals", f"{key}.md")


def main(state=None):
    data = json.load(sys.stdin)
    session_id = data.get("session_id")
    if state is not None:
        state["sid"] = session_id
    if not _valid_token(session_id):
        # unsafe / missing sid -> never guess a name, never traverse: SKIP.
        return

    home = _fleet_home()
    name = _resolve_name(session_id, home)
    # resolved name wins; else fall back to a sid-keyed journal (sid is
    # already validated safe above). Never guess a different worker's name.
    key = name if name is not None else session_id

    turns, tokens = _transcript_stats(data.get("transcript_path"))
    trigger = data.get("trigger")
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = (
        f"- [compact] {ts} "
        f"turns={turns if turns is not None else '?'} "
        f"tokens={tokens if tokens is not None else '?'} "
        f"trigger={trigger if trigger else '?'} "
        f"context compacted here\n"
    )

    path = _journal_path(home, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # errors="replace" (incident `outcome-surrogate`, 2026-07-28): `trigger` is
    # interpolated straight from the hook payload, so an unencodable character
    # there made this write raise and lose the landmark entirely. Same ruling
    # as stop_outcome.py's record append: the write always happens, the
    # offending character is sanitised one-for-one, nothing is truncated.
    with open(path, "a", encoding="utf-8", errors="replace") as f:
        f.write(line)


if __name__ == "__main__":
    _state = {"sid": None}
    try:
        main(_state)
    except Exception as _exc:
        _log_hook_error(_state["sid"], _exc)
    sys.exit(0)
