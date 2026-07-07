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


def _fleet_home():
    """FLEET_HOME env var wins if set; otherwise the fleet root is derived
    from this file's own path: bin/hooks/stop_mailbox.py -> bin/hooks ->
    bin -> repo root (two parents up from the containing directory)."""
    env = os.environ.get("FLEET_HOME")
    if env:
        return env
    here = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def _mailbox_path(session_id, fleet_home=None):
    home = fleet_home if fleet_home is not None else _fleet_home()
    return os.path.join(home, "mailbox", f"{session_id}.md")


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
    """Read the claimed file's contents then delete it (best-effort)."""
    try:
        with open(claimed_file, "r", encoding="utf-8") as f:
            contents = f.read()
    finally:
        try:
            os.remove(claimed_file)
        except OSError:
            pass
    return contents


def main():
    data = json.load(sys.stdin)
    session_id = data.get("session_id")
    if not _valid_session_id(session_id):
        return
    # data.get("stop_hook_active") intentionally unused -- see module
    # docstring: no custom loop counter, native force-allow handles it.

    mailbox_file = _mailbox_path(session_id)
    claimed_file = _claim(mailbox_file)
    if claimed_file is None:
        return

    contents = _read_and_discard(claimed_file)
    if not contents.strip():
        return

    print(json.dumps({"decision": "block", "reason": contents}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
