"""fleet.py -- claude-fleet core logic layer.

Single-file, stdlib-only CLI for one Claude Code "manager" session to spawn,
monitor, steer, and hand off multiple headless "worker" sessions.

This module currently exposes only the pure-logic core (paths, registry,
events, PID liveness, stream-jsonl parsing, prompt composition, permission
mode mapping). Task 2 adds an argparse-based main() with subcommands on top
of these functions -- keep additions below this layer, not mixed into it.

See docs/SPEC.md for the full design (this file implements SPEC sections
2, 4, 5, 6, 8, 11).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (SPEC §3)
# ---------------------------------------------------------------------------

# Single module-global root. Tests monkeypatch this attribute directly
# (fleet.FLEET_HOME = tmp_path) so no test ever touches the real repo's
# state/logs/mailbox directories. Every path helper below re-reads this
# global on each call rather than caching a Path computed at import time,
# so monkeypatching takes effect immediately.
FLEET_HOME = Path(__file__).resolve().parent.parent


def state_dir() -> Path:
    return FLEET_HOME / "state"


def logs_dir() -> Path:
    return FLEET_HOME / "logs"


def mailbox_dir() -> Path:
    return FLEET_HOME / "mailbox"


def journals_dir() -> Path:
    return state_dir() / "journals"


def knowledge_dir() -> Path:
    return FLEET_HOME / "knowledge"


def registry_path() -> Path:
    return state_dir() / "fleet.json"


def events_path() -> Path:
    return state_dir() / "events.jsonl"


def lock_path() -> Path:
    return state_dir() / "fleet.lock"


def now_iso() -> str:
    """Current UTC time, second precision, matching the registry schema."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Registry lock (SPEC §4): atomic-create lock file, retry, stale-break.
# ---------------------------------------------------------------------------

LOCK_TIMEOUT_SECONDS = 5.0
LOCK_STALE_SECONDS = 30.0
LOCK_RETRY_INTERVAL_SECONDS = 0.05


class FleetLockTimeout(Exception):
    """Raised when state/fleet.lock could not be acquired within the timeout."""


@contextmanager
def fleet_lock(timeout: float = LOCK_TIMEOUT_SECONDS):
    """Single-writer lock for state/fleet.json, guarding registry CRUD.

    Acquired by atomic create (os.O_CREAT | os.O_EXCL); a lock file older
    than LOCK_STALE_SECONDS is assumed abandoned (crashed holder) and broken.
    """
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue  # someone else already broke/released it; retry immediately
            if age > LOCK_STALE_SECONDS:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise FleetLockTimeout(f"timed out waiting for lock: {path}")
            time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
    try:
        os.close(fd)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Registry CRUD (SPEC §4)
# ---------------------------------------------------------------------------

NAME_RE = re.compile(r"^[a-z0-9-]+$")


def validate_name(name: str, existing=()) -> None:
    """Raise ValueError unless name matches [a-z0-9-]+ and isn't in `existing`."""
    if not name or not NAME_RE.match(name):
        raise ValueError(f"invalid worker name {name!r}: must match [a-z0-9-]+")
    if name in existing:
        raise ValueError(f"worker name already exists: {name!r}")


def load_registry() -> dict:
    """Load state/fleet.json. Missing or corrupt file -> {"workers": {}}."""
    path = registry_path()
    if not path.exists():
        return {"workers": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {"workers": {}}
    if not isinstance(data, dict):
        return {"workers": {}}
    data.setdefault("workers", {})
    return data


def save_registry(data: dict) -> None:
    """Atomically write state/fleet.json (temp file + os.replace)."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(d), prefix=".fleet.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, str(registry_path()))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def new_worker_record(session_id, cwd, task, mode, model=None, created=None) -> dict:
    """Build a fresh registry record matching the SPEC §4 schema exactly."""
    created = created or now_iso()
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        "task": task[:200],
        "mode": mode,
        "model": model,
        "created": created,
        "status": "working",
        "turn_pid": None,
        "turn_pid_ctime": None,
        "attached_since": None,
        "turns": 0,
        "cost_usd": 0.0,
        "last_activity": created,
    }


# ---------------------------------------------------------------------------
# Events (fleet.py is the only writer of state/events.jsonl)
# ---------------------------------------------------------------------------

def append_event(kind: str, name: str, **fields) -> None:
    """Append one JSON line {"ts", "kind", "name", **fields} to events.jsonl."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), "kind": kind, "name": name}
    record.update(fields)
    with open(events_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# PID liveness (SPEC §4)
# ---------------------------------------------------------------------------

def _default_get_process_info(pid):
    """Return (image_name, creation_time_utc) for a live pid, else None.

    Windows-only, stdlib subprocess route (no third-party deps): asks
    PowerShell's Get-Process for the process name and UTC start time. Kept
    as a single small function so pid_alive()/recompute_status() can accept
    an injected replacement in tests instead of touching real processes.
    """
    try:
        script = (
            f"$p = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
            "if ($p) { \"$($p.ProcessName)|$($p.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss'))\" }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=5,
        )
        line = (result.stdout or "").strip()
        if not line or "|" not in line:
            return None
        name, ctime_str = line.rsplit("|", 1)
        ctime = datetime.strptime(ctime_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        return name, ctime
    except Exception:
        return None


def _parse_iso(ctime_iso: str) -> datetime:
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def pid_alive(pid, ctime_iso, get_process_info=None) -> bool:
    """True iff pid exists, is a claude process, and its creation time matches
    ctime_iso within +/-2s (PID reuse otherwise misclassifies a dead worker
    as working -- SPEC §4)."""
    if pid is None or ctime_iso is None:
        return False
    get_process_info = get_process_info or _default_get_process_info
    info = get_process_info(pid)
    if info is None:
        return False
    name, ctime = info
    if "claude" not in (name or "").lower():
        return False
    try:
        recorded = _parse_iso(ctime_iso)
    except (ValueError, TypeError):
        return False
    return abs((ctime - recorded).total_seconds()) <= 2.0


def _last_line_type(log_path) -> str | None:
    """Return the "type" field of the last well-formed JSON line in log_path."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        return obj.get("type") if isinstance(obj, dict) else None
    return None


def recompute_status(pid, ctime_iso, log_path, get_process_info=None) -> str:
    """working / idle / dead, per SPEC §4: stale PID + trailing result event
    -> idle; stale PID + no trailing result event -> dead."""
    if pid_alive(pid, ctime_iso, get_process_info=get_process_info):
        return "working"
    return "idle" if _last_line_type(log_path) == "result" else "dead"


# ---------------------------------------------------------------------------
# Stream-jsonl parsing (SPEC §6, §5 peek/result rows)
# ---------------------------------------------------------------------------

_TEXT_TRUNCATE = 200
_RESULT_TRUNCATE = 500
_INPUT_TRUNCATE = 150


def _truncate(text, limit) -> str:
    text = text if isinstance(text, str) else str(text)
    return text if len(text) <= limit else text[:limit] + "..."


def _digest_event(obj: dict):
    """Reduce one raw stream-json object to a small peek/result digest dict,
    or None if this event type isn't relevant to peek/result (e.g. system)."""
    etype = obj.get("type")
    if etype == "result":
        text = obj.get("result")
        if text is None:
            text = obj.get("text", "")
        cost = obj.get("total_cost_usd", obj.get("cost_usd"))
        tokens = obj.get("usage") or {}
        return {"kind": "result", "text": _truncate(text, _RESULT_TRUNCATE), "cost_usd": cost, "tokens": tokens}

    if etype in ("assistant", "user"):
        message = obj.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return {"kind": "assistant_text", "text": _truncate(content, _TEXT_TRUNCATE)}
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "tool_use":
                    brief = _truncate(json.dumps(block.get("input", {}), default=str), _INPUT_TRUNCATE)
                    return {"kind": "tool_call", "name": block.get("name", "?"), "input": brief}
                if btype == "text":
                    return {"kind": "assistant_text", "text": _truncate(block.get("text", ""), _TEXT_TRUNCATE)}
        return None
    return None


def tail_events(log_path, n: int = 20) -> list:
    """Defensively parse a worker's stream-json log, returning up to n
    peek/result digest entries (oldest first). Skips non-JSON/junk lines
    and system-only events; tolerates missing or truncated files."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue  # junk line or truncated final line -- skip defensively
        if not isinstance(obj, dict):
            continue
        digest = _digest_event(obj)
        if digest is not None:
            entries.append(digest)

    if n is not None:
        entries = entries[-n:]
    return entries


# ---------------------------------------------------------------------------
# Mailbox drain + prompt composition (SPEC §5 drain rule, §7, §8)
# ---------------------------------------------------------------------------

def drain_mailbox(sid: str) -> str:
    """Read and delete mailbox/<sid>.md, returning its contents ("" if absent
    or empty). Called by every turn launch (spawn/send-resume/respawn)."""
    path = mailbox_dir() / f"{sid}.md"
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return content.strip()


_PREAMBLE_TEMPLATE = """You are fleet worker `{name}` in `{cwd}`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `C:/proga/claude-fleet/state/journals/{name}.md` (create it early; update it at each milestone): goal, done, in-progress, blockers, next steps. It must be enough for a fresh session to continue.
End every turn with a compact result summary: changed, verified, blocked.
Do not leave servers or watchers running past the end of the turn without recording their PIDs in the journal.
"""


def compose_prompt(name: str, cwd, task: str, sid: str, journal_path=None) -> str:
    """preamble (SPEC §8) + drained mailbox + task text (+ journal contents
    when respawning, i.e. when journal_path is given and exists)."""
    parts = [_PREAMBLE_TEMPLATE.format(name=name, cwd=cwd)]

    mail = drain_mailbox(sid)
    if mail:
        parts.append(f"<MANAGER MESSAGE>\n{mail}\n")

    parts.append(task)

    if journal_path is not None:
        journal_path = Path(journal_path)
        if journal_path.exists():
            try:
                journal_text = journal_path.read_text(encoding="utf-8").strip()
            except OSError:
                journal_text = ""
            if journal_text:
                parts.append(f"## Journal from previous session\n{journal_text}\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Permission mode mapping (SPEC §6)
# ---------------------------------------------------------------------------

MODE_FLAGS = {
    "bypass": ["--dangerously-skip-permissions"],
    "accept": ["--permission-mode", "acceptEdits"],
    "dontask": ["--permission-mode", "dontAsk"],
    "plan": ["--permission-mode", "plan"],
    "omit": [],
}


def mode_flags(mode: str) -> list:
    """Map a fleet mode name to its claude CLI argv flags. Raises ValueError
    for unknown mode names."""
    try:
        return list(MODE_FLAGS[mode])
    except KeyError:
        choices = ", ".join(MODE_FLAGS)
        raise ValueError(f"invalid mode {mode!r}: choices are {choices}")
