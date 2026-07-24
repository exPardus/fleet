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


def _fleet_home():
    """FLEET_HOME env var wins if set; otherwise the fleet root is derived
    from this file's own path: bin/hooks/postcompact_journal.py -> bin/hooks
    -> bin -> repo root (two parents up from the containing directory)."""
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
        with open(transcript_path, "r", encoding="utf-8") as f:
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
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    _state = {"sid": None}
    try:
        main(_state)
    except Exception as _exc:
        _log_hook_error(_state["sid"], _exc)
    sys.exit(0)
