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

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
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


def ctime_to_iso(dt: datetime) -> str:
    """Serialize a process creation-time datetime to the registry's
    turn_pid_ctime format (round-trips through _parse_iso). This is the
    only serializer callers should use to store turn_pid_ctime --
    datetime.isoformat() yields "+00:00" and breaks _parse_iso."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
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
        os.write(fd, token.encode("utf-8"))
        os.close(fd)
        yield
    finally:
        # Compare-and-delete: only unlink if the lock file still holds our
        # token. A successor may have broken our (apparently stale) lock and
        # now owns it -- deleting blindly here would cascade (F1).
        try:
            current = path.read_bytes()
        except (FileNotFoundError, OSError):
            current = None
        if current == token.encode("utf-8"):
            try:
                path.unlink()
            except (FileNotFoundError, OSError):
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


class RegistryCorruptError(Exception):
    """Raised when state/fleet.json exists but cannot be trusted as-is
    (parse failure, non-dict content, or unreadable). Never silently
    degrade to an empty registry in this case -- that would let a later
    save_registry() overwrite live worker records with nothing (F2)."""


def _quarantine_registry(path: Path) -> Path:
    """Rename a corrupt registry aside (best-effort) and emit an event
    (best-effort). Returns the quarantine path regardless of whether the
    rename actually succeeded."""
    quarantined = path.with_name(f"fleet.json.corrupt.{now_iso().replace(':', '')}")
    try:
        path.rename(quarantined)
    except OSError:
        pass
    try:
        append_event("registry_corrupt", "fleet", path=str(quarantined))
    except OSError:
        pass
    return quarantined


def load_registry() -> dict:
    """Load state/fleet.json. Missing file -> {"workers": {}}. An existing
    but corrupt/unreadable file is quarantined (renamed aside) and raises
    RegistryCorruptError -- callers must abort, not catch-and-continue."""
    path = registry_path()
    if not path.exists():
        return {"workers": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        quarantined = _quarantine_registry(path)
        raise RegistryCorruptError(f"corrupt registry quarantined to {quarantined}")
    except OSError:
        raise RegistryCorruptError(f"registry unreadable: {path}")
    if not isinstance(data, dict):
        quarantined = _quarantine_registry(path)
        raise RegistryCorruptError(f"registry was not a JSON object; quarantined to {quarantined}")
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
        with open(log_path, "r", encoding="utf-8-sig", errors="replace") as f:
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


def recompute_status(pid, ctime_iso, log_path, current_status: str | None = None, get_process_info=None) -> str:
    """working / idle / dead, per SPEC §4: stale PID + trailing result event
    -> idle; stale PID + no trailing result event -> dead. If current_status
    is "attached", that state takes priority and is returned immediately --
    liveness recomputation must never clobber an operator's manual attach
    (F7)."""
    if current_status == "attached":
        return "attached"
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
        with open(log_path, "r", encoding="utf-8-sig", errors="replace") as f:
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

def _claimed_path(sid: str) -> Path:
    return mailbox_dir() / f"{sid}.md.claimed.{os.getpid()}"


def claim_mailbox(sid: str) -> tuple[str, Path | None]:
    """Atomically claim mailbox/<sid>.md via os.replace to
    mailbox/<sid>.md.claimed.<pid> (matches the hook protocol, SPEC §7).
    Returns (stripped_content, claim_path); ("", None) if no mail."""
    src = mailbox_dir() / f"{sid}.md"
    if not src.exists():
        return "", None
    claim = _claimed_path(sid)
    try:
        os.replace(str(src), str(claim))
    except OSError:
        return "", None
    try:
        content = claim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        content = ""
    return content.strip(), claim


def finalize_mailbox_claim(claim: Path | None) -> None:
    """Delete the claimed file after the turn process has started. No-op on None."""
    if claim is None:
        return
    try:
        claim.unlink()
    except FileNotFoundError:
        pass


def restore_mailbox_claim(claim: Path | None) -> None:
    """Return an unconsumed claim to mailbox/<sid>.md after a failed launch.
    If newer mail arrived meanwhile, prepend the (older) claimed content. No-op on None."""
    if claim is None:
        return
    target = claim.parent / (claim.name.split(".md.claimed.")[0] + ".md")
    try:
        claimed = claim.read_text(encoding="utf-8", errors="replace")
    except OSError:
        claimed = ""
    if target.exists():
        try:
            newer = target.read_text(encoding="utf-8", errors="replace")
            target.write_text(claimed.rstrip() + "\n\n" + newer, encoding="utf-8")
            claim.unlink()
            return
        except OSError:
            pass
    try:
        os.replace(str(claim), str(target))
    except OSError:
        pass


_PREAMBLE_TEMPLATE = """You are fleet worker `{name}` in `{cwd}`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `C:/proga/claude-fleet/state/journals/{name}.md` (create it early; update it at each milestone): goal, done, in-progress, blockers, next steps. It must be enough for a fresh session to continue.
End every turn with a compact result summary: changed, verified, blocked.
Do not leave servers or watchers running past the end of the turn without recording their PIDs in the journal.
"""


def compose_prompt(name: str, cwd, task: str, sid: str, journal_path=None) -> tuple[str, Path | None]:
    """preamble (SPEC §8) + claimed mailbox + task text (+ journal contents
    when respawning, i.e. when journal_path is given and exists).

    Claims (does not destroy) mailbox/<sid>.md via claim_mailbox() so the
    universal-drain guarantee holds (every compose_prompt call claims the
    mailbox) while leaving recovery to the caller: on a failed launch, call
    restore_mailbox_claim(claim) to put the mail back; on a successful
    launch, call finalize_mailbox_claim(claim) once the turn process has
    started (see SPEC §7 / the launch-sequence contract).
    """
    parts = [_PREAMBLE_TEMPLATE.format(name=name, cwd=cwd)]

    mail, claim = claim_mailbox(sid)
    if mail:
        parts.append(f"<MANAGER MESSAGE>\n{mail}\n")

    parts.append(task)

    if journal_path is not None:
        journal_path = Path(journal_path)
        if journal_path.exists():
            try:
                journal_text = journal_path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                journal_text = ""
            if journal_text:
                parts.append(f"## Journal from previous session\n{journal_text}\n")

    return "\n".join(parts), claim


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


# ---------------------------------------------------------------------------
# Turn launcher (SPEC §6): pure argv builder + detached Popen.
# ---------------------------------------------------------------------------

# worker-settings.json is a single real asset that always lives alongside
# the real repo (SPEC §1: this tool's location is fixed, never relocated
# per-project). Deliberately NOT derived from FLEET_HOME: tests monkeypatch
# FLEET_HOME to isolate state/logs/mailbox, but the settings file argv value
# must stay the one real path every worker turn actually uses -- the same
# convention _PREAMBLE_TEMPLATE already uses for the journal path.
WORKER_SETTINGS_PATH = "C:/proga/claude-fleet/worker-settings.json"


class ClaudeNotFoundError(Exception):
    """Raised when the `claude` executable cannot be resolved on PATH."""


def resolve_claude_executable(which=shutil.which) -> str:
    """Resolve the real claude executable (claude.cmd/claude.exe on Windows)
    via shutil.which -- Popen needs the concrete path, not the bare name."""
    exe = which("claude")
    if not exe:
        raise ClaudeNotFoundError(
            "claude executable not found on PATH (checked via shutil.which('claude'); "
            "expected claude.cmd or claude.exe on this machine)"
        )
    return exe


def build_turn_argv(claude_exe: str, sid: str, first: bool, mode: str,
                     model: str | None = None, max_budget_usd: float | None = None,
                     settings_path: str = WORKER_SETTINGS_PATH) -> list:
    """Pure argv builder for one worker turn (SPEC §6). Raises ValueError
    (via mode_flags) for an unknown mode -- kept a pure function per the
    Task 2 brief so every mode/model/budget combo is unit-testable without
    touching Popen at all."""
    argv = [claude_exe, "-p", "--output-format", "stream-json", "--verbose", "--include-hook-events"]
    argv += ["--session-id", sid] if first else ["--resume", sid]
    argv += ["--settings", settings_path]
    argv += mode_flags(mode)
    if model:
        argv += ["--model", model]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    return argv


class TurnLaunchError(Exception):
    """Raised when Popen() itself fails to start a turn process. Callers
    (cmd_spawn et al) must restore_mailbox_claim() the pending claim on this
    exception -- the mailbox was never consumed by a live turn."""


def launch_turn(name: str, cwd, sid: str, prompt: str, mode: str, first: bool = False,
                 model=None, max_budget_usd=None,
                 popen=subprocess.Popen, get_process_info=None, which=shutil.which) -> dict:
    """Start one detached worker turn (SPEC §6): resolve claude, build argv,
    open per-worker logs (stdout -> logs/<name>.jsonl, stderr -> a separate
    logs/<name>.err so stderr noise never breaks jsonl parsing), Popen
    DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP with the worker's cwd (the
    --resume cwd-scope invariant, SPEC §2), write the prompt on stdin and
    close it (never leave stdin open -- SPEC §6), then query the new
    process's creation time via get_process_info (defaults to
    _default_get_process_info) so the registry can store an unambiguous
    turn_pid_ctime via ctime_to_iso -- the only serializer callers may use
    (F5 bridge).

    Returns {"turn_pid", "turn_pid_ctime", "log_path", "err_log_path"}.

    Raises ClaudeNotFoundError / TurnLaunchError only for failures BEFORE or
    DURING the Popen() call itself -- callers must restore_mailbox_claim()
    the pending claim in that case (the launch-sequence contract). Once
    Popen() has returned a process, everything else here (stdin write,
    process-info query) is best-effort: the turn is already running, so a
    hiccup here must never be reported as a launch failure that would cause
    the caller to re-deliver the same mail into a duplicate turn.
    """
    claude_exe = resolve_claude_executable(which=which)
    argv = build_turn_argv(claude_exe, sid, first, mode, model=model, max_budget_usd=max_budget_usd)

    logs_dir().mkdir(parents=True, exist_ok=True)
    log_path = logs_dir() / f"{name}.jsonl"
    err_path = logs_dir() / f"{name}.err"

    out_f = open(log_path, "ab")
    err_f = open(err_path, "ab")
    try:
        try:
            proc = popen(
                argv,
                cwd=str(cwd),
                stdin=subprocess.PIPE,
                stdout=out_f,
                stderr=err_f,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except OSError as exc:
            raise TurnLaunchError(f"failed to launch claude turn for {name!r}: {exc}") from exc
    finally:
        out_f.close()
        err_f.close()

    # The process has started -- from here nothing is a launch failure.
    try:
        if proc.stdin is not None:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
    except OSError:
        pass

    get_process_info = get_process_info or _default_get_process_info
    ctime_iso = None
    try:
        info = get_process_info(proc.pid)
        if info is not None:
            ctime_iso = ctime_to_iso(info[1])
    except Exception:
        ctime_iso = None

    return {
        "turn_pid": proc.pid,
        "turn_pid_ctime": ctime_iso,
        "log_path": str(log_path),
        "err_log_path": str(err_path),
    }


# ---------------------------------------------------------------------------
# Status recompute helpers (SPEC §4, §5 status row)
# ---------------------------------------------------------------------------

STALE_ATTACH_SECONDS = 3 * 3600  # doctor/status nag threshold (SPEC §9)


def recompute_worker(name: str, record: dict, get_process_info=None) -> dict:
    """Return an updated copy of `record` with status/cost_usd/last_activity
    refreshed from live PID + log-tail state. Never mutates other fields
    (turns, task, mode, ...); never clobbers an "attached" status
    (recompute_status's own guard, F7)."""
    log_path = logs_dir() / f"{name}.jsonl"
    updated = dict(record)
    updated["status"] = recompute_status(
        record.get("turn_pid"), record.get("turn_pid_ctime"), log_path,
        current_status=record.get("status"), get_process_info=get_process_info,
    )
    entries = tail_events(log_path, n=50)
    results = [e for e in entries if e.get("kind") == "result"]
    if results and results[-1].get("cost_usd") is not None:
        updated["cost_usd"] = results[-1]["cost_usd"]
    try:
        mtime = log_path.stat().st_mtime
        updated["last_activity"] = ctime_to_iso(datetime.fromtimestamp(mtime, tz=timezone.utc))
    except OSError:
        pass
    return updated


def _pending_mail_count(sid: str) -> int:
    """0 or 1: whether mailbox/<sid>.md exists and is nonempty (SPEC §5
    status row: "pending-mail count (mailbox file exists+nonempty)" -- a
    single mailbox file per session, so "count" is presence, not a message
    tally)."""
    path = mailbox_dir() / f"{sid}.md"
    try:
        return 1 if path.exists() and path.stat().st_size > 0 else 0
    except OSError:
        return 0


def _attach_age_seconds(record: dict):
    if record.get("status") != "attached" or not record.get("attached_since"):
        return None
    try:
        return (datetime.now(timezone.utc) - _parse_iso(record["attached_since"])).total_seconds()
    except (ValueError, TypeError):
        return None


def _worker_flags(record: dict) -> list:
    flags = []
    if record["status"] == "idle" and _pending_mail_count(record["session_id"]) > 0:
        flags.append("idle+mail")
    if record["status"] == "attached":
        age = _attach_age_seconds(record)
        if age is not None and age > STALE_ATTACH_SECONDS:
            flags.append("stale-attach")
    if record["status"] == "dead":
        flags.append("dead")
    return flags


def hook_events_present(log_path) -> bool:
    """Whether any hook event (PostToolUse/Stop additionalContext, requires
    --include-hook-events at spawn) appears anywhere in the raw log -- the
    alarm `fleet peek` shows for the "settings validation errors are
    swallowed in print mode" silent-failure mode (SPEC §7, §9).

    Deliberately searches for the bare substring "hookEventName" (no
    surrounding quotes): a live captured transcript (`claude -p
    --output-format stream-json --verbose`) shows Claude Code wraps a hook's
    own stdout inside a `system`/`hook_response` event's "output"/"stdout"
    string fields, so the hook's `{"hookSpecificOutput": {"hookEventName":
    ...}}` JSON appears there with its quotes backslash-escaped
    (`\"hookEventName\"`), not as literal top-level `"hookEventName"` text.
    The bare word substring matches either form."""
    log_path = Path(log_path)
    if not log_path.exists():
        return False
    try:
        text = log_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    return "hookEventName" in text


# ---------------------------------------------------------------------------
# CLI: subcommands (SPEC §5)
# ---------------------------------------------------------------------------

class FleetCliError(Exception):
    """User-facing CLI error (bad args, unknown worker, missing dir/file,
    ...) -- caught in main() and reported as a clean one-line message, never
    a raw traceback."""


def _read_task_arg(task: str) -> str:
    """`@file` task syntax (SPEC §5): a task string starting with `@` names
    a file whose contents are the task text."""
    if task.startswith("@"):
        path = Path(task[1:])
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise FleetCliError(f"could not read task file {path}: {exc}") from exc
    return task


def cmd_spawn(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which) -> int:
    """`fleet spawn <name> --dir <path> --task <text|@file> [--mode ...]
    [--model m] [--max-budget-usd x]` (SPEC §5 spawn row).

    Registry mutation (create the record) and event-append happen together
    inside one fleet_lock() -- the append_event/lock-discipline decision for
    Task 2 (see module docstring note below cmd_wait): every event this
    module appends is written while the registry lock for that same
    operation is held, so concurrent `fleet` invocations never interleave
    events with the registry state they describe.
    """
    cwd = Path(args.dir)
    if not cwd.is_dir():
        raise FleetCliError(f"--dir does not exist or is not a directory: {args.dir}")

    task = _read_task_arg(args.task)

    with fleet_lock():
        data = load_registry()
        validate_name(args.name, existing=data["workers"].keys())
        sid = str(uuid.uuid4())
        record = new_worker_record(sid, cwd, task, args.mode, model=args.model)
        data["workers"][args.name] = record
        save_registry(data)
        append_event("spawned", args.name, session_id=sid, cwd=str(cwd), mode=args.mode)

    prompt, claim = compose_prompt(args.name, cwd, task, sid)
    try:
        info = launch_turn(
            args.name, cwd, sid, prompt, args.mode, first=True,
            model=args.model, max_budget_usd=args.max_budget_usd,
            popen=popen, get_process_info=get_process_info, which=which,
        )
        finalize_mailbox_claim(claim)
    except Exception as exc:
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            data["workers"].pop(args.name, None)
            save_registry(data)
            append_event("spawn_failed", args.name, error=str(exc))
        raise

    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(args.name)
        if rec is not None:
            rec["turn_pid"] = info["turn_pid"]
            rec["turn_pid_ctime"] = info["turn_pid_ctime"]
            rec["turns"] = 1
            rec["last_activity"] = now_iso()
            save_registry(data)
        append_event("turn_started", args.name, session_id=sid, turn_pid=info["turn_pid"])

    print(f"{args.name} {sid} {info['log_path']}")
    return 0


def cmd_status(args, get_process_info=None) -> int:
    """`fleet status [name]` (SPEC §5 status row): recompute liveness/cost
    for the named worker (or all workers), persist any transitions, print a
    compact table with anomaly flags."""
    with fleet_lock():
        data = load_registry()
        names = [args.name] if args.name else sorted(data["workers"])
        for n in names:
            if n not in data["workers"]:
                raise FleetCliError(f"unknown worker: {n!r}")
        changed = False
        for n in names:
            before = data["workers"][n]
            after = recompute_worker(n, before, get_process_info=get_process_info)
            if after != before:
                data["workers"][n] = after
                changed = True
                if after["status"] != before["status"]:
                    append_event("status_changed", n, old=before["status"], new=after["status"])
        if changed:
            save_registry(data)

    _print_status_table(data, names)
    return 0


def _print_status_table(data: dict, names) -> None:
    header = f"{'NAME':<20}{'STATUS':<10}{'TURNS':>6}{'COST':>9}{'MIN-AGO':>9}{'MAIL':>6}{'ATTACH':>9}  FLAGS"
    print(header)
    now = datetime.now(timezone.utc)
    for n in names:
        rec = data["workers"][n]
        try:
            mins = (now - _parse_iso(rec["last_activity"])).total_seconds() / 60.0
            mins_s = f"{mins:.0f}"
        except (ValueError, TypeError, KeyError):
            mins_s = "?"
        mail = _pending_mail_count(rec["session_id"])
        attach_age = _attach_age_seconds(rec)
        attach_s = f"{attach_age / 3600:.1f}h" if attach_age is not None else "-"
        flags = ",".join(_worker_flags(rec)) or "-"
        print(
            f"{n:<20}{rec['status']:<10}{rec['turns']:>6}{rec['cost_usd']:>9.2f}"
            f"{mins_s:>9}{mail:>6}{attach_s:>9}  {flags}"
        )


def cmd_peek(args) -> int:
    """`fleet peek <name> [-n 20]` (SPEC §5 peek row): digest of recent
    stream events plus whether fleet hooks have fired."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")

    log_path = logs_dir() / f"{args.name}.jsonl"
    entries = tail_events(log_path, n=args.lines)
    hooks = hook_events_present(log_path)
    print(f"-- {args.name} (hooks: {'seen' if hooks else 'not seen'}) --")
    if not entries:
        print("(no events yet)")
        return 0
    for e in entries:
        kind = e["kind"]
        if kind == "tool_call":
            print(f"[tool] {e['name']}: {e['input']}")
        elif kind == "assistant_text":
            print(f"[text] {e['text']}")
        elif kind == "result":
            cost = e.get("cost_usd")
            cost_s = f"${cost:.2f}" if isinstance(cost, (int, float)) else "?"
            print(f"[result] {cost_s} {e['text']}")
    return 0


def cmd_result(args) -> int:
    """`fleet result <name>` (SPEC §5 result row): final result event text
    of the last completed turn, nothing else."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")

    log_path = logs_dir() / f"{args.name}.jsonl"
    entries = tail_events(log_path, n=None)
    results = [e for e in entries if e["kind"] == "result"]
    if not results:
        print(f"{args.name}: no completed turn result yet")
        return 1
    print(results[-1]["text"])
    return 0


def wait_for_workers(names, mode: str = "all", timeout=None, poll_interval: float = 3.0,
                      get_process_info=None, sleep=time.sleep, clock=time.monotonic):
    """Poll registry-recomputed liveness for `names` (re-reading the
    registry each pass, so a concurrent respawn/interrupt is picked up)
    until the wait condition is met or timeout elapses.

    Returns (finished: dict[name -> final_status], pending: set[name]) --
    pending is empty iff every requested worker (mode="all") or at least one
    (mode="any") finished before the deadline.
    """
    deadline = None if timeout is None else clock() + timeout
    finished: dict = {}
    pending = set(names)
    while True:
        data = load_registry()
        for n in list(pending):
            rec = data["workers"].get(n)
            if rec is None:
                finished[n] = "dead"
                pending.discard(n)
                continue
            log_path = logs_dir() / f"{n}.jsonl"
            status = recompute_status(
                rec.get("turn_pid"), rec.get("turn_pid_ctime"), log_path,
                current_status=rec.get("status"), get_process_info=get_process_info,
            )
            if status != "working":
                finished[n] = status
                pending.discard(n)
        if not pending:
            break
        if mode == "any" and finished:
            break
        if deadline is not None and clock() >= deadline:
            break
        sleep(poll_interval)
    return finished, pending


def cmd_wait(args, get_process_info=None, sleep=time.sleep, clock=time.monotonic) -> int:
    """`fleet wait <name...> [--any|--all] [--timeout s]` (SPEC §5 wait
    row): block until turn(s) end, persist any status transitions, print a
    one-line result summary per finished worker. Nonzero exit on timeout."""
    with fleet_lock():
        data = load_registry()
        for n in args.names:
            if n not in data["workers"]:
                raise FleetCliError(f"unknown worker: {n!r}")

    mode = "any" if args.any else "all"
    finished, pending = wait_for_workers(
        args.names, mode=mode, timeout=args.timeout,
        get_process_info=get_process_info, sleep=sleep, clock=clock,
    )

    if finished:
        with fleet_lock():
            data = load_registry()
            for n in finished:
                rec = data["workers"].get(n)
                if rec is None:
                    continue
                updated = recompute_worker(n, rec, get_process_info=get_process_info)
                data["workers"][n] = updated
                if updated["status"] != rec["status"]:
                    append_event("status_changed", n, old=rec["status"], new=updated["status"])
            save_registry(data)

    for n, status in finished.items():
        log_path = logs_dir() / f"{n}.jsonl"
        results = [e for e in tail_events(log_path, n=None) if e["kind"] == "result"]
        summary = results[-1]["text"] if results else "(no result event)"
        print(f"{n}: {status} -- {_truncate(summary, 120)}")

    if pending:
        for n in pending:
            print(f"{n}: timed out (still working)")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI: argparse wiring + main()
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet", description="claude-fleet manager CLI (M1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_spawn = sub.add_parser("spawn", help="spawn a new worker session")
    p_spawn.add_argument("name")
    p_spawn.add_argument("--dir", required=True)
    p_spawn.add_argument("--task", required=True)
    # No canonical default mode is specified in SPEC §6; "dontask" ("middle
    # ground: auto-deny outside allowlist rather than stall") is the safest
    # non-hanging, non-blanket-bypass choice, so it is Task 2's default.
    p_spawn.add_argument("--mode", choices=list(MODE_FLAGS), default="dontask")
    p_spawn.add_argument("--model", default=None)
    p_spawn.add_argument("--max-budget-usd", type=float, default=None, dest="max_budget_usd")

    p_status = sub.add_parser("status", help="show worker status table")
    p_status.add_argument("name", nargs="?", default=None)

    p_peek = sub.add_parser("peek", help="digest of recent stream events")
    p_peek.add_argument("name")
    p_peek.add_argument("-n", "--lines", type=int, default=20, dest="lines")

    p_result = sub.add_parser("result", help="final result text of last completed turn")
    p_result.add_argument("name")

    p_wait = sub.add_parser("wait", help="block until turn(s) end")
    p_wait.add_argument("names", nargs="+")
    wait_mode = p_wait.add_mutually_exclusive_group()
    wait_mode.add_argument("--any", action="store_true")
    wait_mode.add_argument("--all", action="store_true")
    p_wait.add_argument("--timeout", type=float, default=None)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "spawn":
            return cmd_spawn(args)
        if args.command == "status":
            return cmd_status(args)
        if args.command == "peek":
            return cmd_peek(args)
        if args.command == "result":
            return cmd_result(args)
        if args.command == "wait":
            return cmd_wait(args)
        parser.error(f"unknown command {args.command!r}")
        return 2
    except RegistryCorruptError as exc:
        print(f"fleet: registry error: {exc}", file=sys.stderr)
        return 1
    except (FleetCliError, ClaudeNotFoundError, TurnLaunchError, ValueError, FleetLockTimeout) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
