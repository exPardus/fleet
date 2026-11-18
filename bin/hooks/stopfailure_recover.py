"""StopFailure hook: hand a turn that ended on an API error to fleet.

Claude Code ends a turn that hits an API error (connection lost mid-response,
overloaded, a 5xx, a usage limit) through StopFailure, not Stop, so the
outcome and mailbox Stop hooks never run and the row reads dead-suspected.
This hook only launches `fleet stream-recover --sid <sid> --wait` detached;
fleet reads the transcript tail, retries a transient stream error in the same
session with bounded backoff, and sends LANE-DEAD when it cannot (SPEC sec 8).
A usage-limit tail is left to the limit park.

Standalone, stdlib only. Never imports bin/fleet.py; reuses the sibling
stop_mailbox.py helpers for home resolution, sid validation and the
hook-errors.log line. Writes nothing itself, never blocks, always exits 0.
The launch is detached (new session / DETACHED_PROCESS), never a shell `&`.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stop_mailbox import _fleet_home, _log_hook_error, _valid_session_id  # noqa: E402


def _known_session(session_id, home):
    """Cheap read-only filter: only a registered session is worth a process."""
    try:
        with open(os.path.join(home, "state", "fleet.json"),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False
    workers = data.get("workers") if isinstance(data, dict) else None
    if not isinstance(workers, dict):
        return False
    return any(isinstance(r, dict) and r.get("session_id") == session_id
               for r in workers.values())


def _launch(session_id, home):
    script = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "fleet.py")
    argv = [sys.executable, script, "--fleet-home", home,
            "stream-recover", "--sid", session_id, "--wait"]
    # No OS branch (SPEC §16.8): the Windows flags are 0 on POSIX, and
    # start_new_session is ignored on Windows.
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "close_fds": True,
              "start_new_session": True,
              "creationflags": (getattr(subprocess, "DETACHED_PROCESS", 0)
                                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))}
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env["FLEET_HOME"] = home
    kwargs["env"] = env
    subprocess.Popen(argv, **kwargs)


def main(state=None):
    data = json.load(sys.stdin)
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if state is not None:
        state["sid"] = session_id
    if not _valid_session_id(session_id):
        return
    home = _fleet_home()
    if not _known_session(session_id, home):
        return
    _launch(session_id, home)


if __name__ == "__main__":
    _state = {"sid": None}
    try:
        main(_state)
    except Exception as _exc:
        _log_hook_error(_state["sid"], _exc)
    sys.exit(0)
