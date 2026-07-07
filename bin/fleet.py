"""fleet.py -- claude-fleet core logic layer.

Single-file, stdlib-only CLI for one Claude Code "manager" session to spawn,
monitor, steer, and hand off multiple headless "worker" sessions.

This module currently exposes only the pure-logic core (paths, registry,
events, PID liveness, stream-jsonl parsing, prompt composition, permission
mode mapping). Task 2 adds an argparse-based main() with subcommands on top
of these functions -- keep additions below this layer, not mixed into it.

See docs/SPEC.md for the full design (this file implements SPEC sections
2, 4, 5, 6, 8, 11, 14).

Requires Python 3.10+ (dev machine: py -3.13). Stdlib only -- no pip deps
(SPEC §14 / docs/specs/portability.md fixed constraints). Windows is the
only implemented PLATFORM backend for now (see the platform adapter block
below); the module itself is written to the 3.10 floor so a POSIX backend
(Phase 1.5) can run under distro pythons without a language-version bump.
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
import threading
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
#
# SPEC §14 portability: the env var FLEET_HOME wins if set, else FLEET_HOME
# is derived from this file's own location (bin/fleet.py -> parent.parent
# is the repo root). Read once at import into this global -- exactly like
# bin/hooks/*.py's own _fleet_home(), which every hook script duplicates
# standalone (hooks never import fleet.py). Monkeypatching this attribute
# directly (as tests do) always wins over both: it is a later assignment.
FLEET_HOME = (
    Path(os.environ["FLEET_HOME"]) if os.environ.get("FLEET_HOME")
    else Path(__file__).resolve().parent.parent
)


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


def template_settings_path() -> Path:
    """Git-tracked hook-wiring TEMPLATE (SPEC §14): worker-settings.template.json
    at the fleet-home root, with {{PYTHON}}/{{FLEET_HOME}} placeholders.
    `fleet init` renders it into instance_settings_path()."""
    return FLEET_HOME / "worker-settings.template.json"


def instance_settings_path() -> Path:
    """Machine-local, gitignored settings instance (SPEC §14):
    state/worker-settings.json, rendered by `fleet init` from
    template_settings_path(). Every worker turn's --settings argv value
    points here (build_turn_argv's default), never at the template."""
    return state_dir() / "worker-settings.json"


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
# === PLATFORM ADAPTER START (SPEC §14 portability mandate) ===
#
# This is the ONLY section of fleet.py permitted to branch on os.name /
# sys.platform, read subprocess creation flags, or shell out to an
# OS-specific tool (PowerShell Get-Process, taskkill, wt.exe,
# Start-Process). Every other function in this module calls through the
# PLATFORM singleton below instead of doing any of that itself. Windows is
# the only implemented backend for now; the POSIX backend raises
# UnsupportedPlatformError everywhere -- Phase 1.5 fills it in
# (docs/specs/portability.md). A source-scan test (test_steering.py) enforces
# that no other function in this module references os.name/sys.platform.
# ---------------------------------------------------------------------------

class UnsupportedPlatformError(NotImplementedError):
    """Raised by every _PosixPlatform method: there is no POSIX backend yet
    (Phase 1.5, SPEC §14) -- this build only supports Windows."""


class _WindowsPlatform:
    """Windows implementation of every OS-specific fleet operation."""

    def detached_popen_kwargs(self) -> dict:
        """Popen kwargs for a fully detached child (SPEC §6): survives the
        parent CLI invocation exiting and isn't torn down with the parent's
        process group (e.g. a Ctrl-C in the manager's shell)."""
        return {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}

    def get_process_info(self, pid):
        """Return (image_name, creation_time_utc) for a live pid, else None.

        stdlib subprocess route (no third-party deps): asks PowerShell's
        Get-Process for the process name and UTC start time. Kept as a
        single small method so pid_alive()/recompute_status()/launch_turn()
        can accept an injected replacement in tests instead of touching
        real processes.
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

    def kill_process_tree(self, pid, run=subprocess.run) -> bool:
        """`taskkill /PID <pid> /T /F` (SPEC §5 interrupt row): best-effort
        kill of the whole process tree rooted at pid. Returns True iff
        taskkill itself reported success (exit code 0); callers treat
        interrupt as best-effort regardless (the caller still marks the
        worker idle -- a turn that ignored the kill is still not something
        `fleet` can wait on)."""
        try:
            result = run(
                ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def build_attach_argv(self, cwd, sid: str, which=shutil.which) -> list:
        """Argv for `fleet attach` (SPEC §5 attach row, §9): Windows
        Terminal (`wt`) if present on PATH, else a detached PowerShell
        fallback via Start-Process. Both resume with the worker's cwd (the
        --resume cwd-scope invariant, SPEC §2)."""
        cwd = str(cwd)
        if which("wt"):
            return ["wt", "-d", cwd, "--", "claude", "--resume", sid]
        # F2: cwd is interpolated into a PowerShell single-quoted string
        # literal below. An unescaped `'` in cwd (e.g. C:\Users\O'Brien\proj)
        # would terminate that string early -> ParserError -- and this
        # happens silently: no terminal opens, but `fleet attach` still
        # reports success (cmd_attach never checks the detached child's exit
        # code, by design -- see cmd_attach's docstring). Double any embedded
        # `'` per PowerShell single-quoted-string escaping rules. The `wt`
        # branch above is unaffected: list2cmdline double-quotes each argv
        # element, and a `'` is a literal character inside a double-quoted
        # Windows command-line argument.
        ps_cwd = cwd.replace("'", "''")
        ps_command = (
            f"Start-Process powershell -WorkingDirectory '{ps_cwd}' "
            f"-ArgumentList '-NoExit','-Command','claude --resume {sid}'"
        )
        return ["powershell", "-Command", ps_command]


class _PosixPlatform:
    """Stub POSIX backend: every method raises UnsupportedPlatformError.
    Phase 1.5 fills these in (docs/specs/portability.md); Phase 1 targets
    Windows only (SPEC §14)."""

    def _unsupported(self, what: str):
        raise UnsupportedPlatformError(
            f"{what} has no POSIX implementation yet (Phase 1.5, SPEC §14); "
            "this build only supports Windows"
        )

    def detached_popen_kwargs(self) -> dict:
        self._unsupported("detached_popen_kwargs")

    def get_process_info(self, pid):
        self._unsupported("get_process_info")

    def kill_process_tree(self, pid, run=None) -> bool:
        self._unsupported("kill_process_tree")

    def build_attach_argv(self, cwd, sid: str, which=None) -> list:
        self._unsupported("build_attach_argv")


# The one and only os.name branch in this module: selects which adapter
# instance PLATFORM points at. Nothing else in fleet.py may inspect
# os.name or sys.platform (enforced by a source-scan test, test_steering.py).
PLATFORM = _WindowsPlatform() if os.name == "nt" else _PosixPlatform()

# === PLATFORM ADAPTER END ===
# ---------------------------------------------------------------------------


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

def _parse_iso(ctime_iso: str) -> datetime:
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# F-CMD: an npm/claude.cmd install resolves to claude.cmd, which Popen runs
# via cmd.exe -- the pid Python gets back is cmd.exe's (later re-parented to
# node), so the recorded image name is "cmd" or "node", never "claude". The
# recorded-pid + ctime (+/-2s) match below is what actually guards against
# false positives, not this name test, so broadening it is safe (a reused
# pid landing on an unrelated cmd/node/claude process within 2s of the
# recorded ctime is the accepted, vanishingly unlikely residual).
_ALIVE_IMAGE_NAMES = {"claude", "node", "cmd"}


def pid_alive(pid, ctime_iso, get_process_info=None) -> bool:
    """True iff pid exists, is a claude/node/cmd process (F-CMD), and its
    creation time matches ctime_iso within +/-2s (PID reuse otherwise
    misclassifies a dead worker as working -- SPEC §4)."""
    if pid is None or ctime_iso is None:
        return False
    get_process_info = get_process_info or PLATFORM.get_process_info
    info = get_process_info(pid)
    if info is None:
        return False
    name, ctime = info
    name_l = (name or "").lower()
    if not any(candidate in name_l for candidate in _ALIVE_IMAGE_NAMES):
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
    (F7).

    F1 launch-in-flight guard: a "working" record whose turn_pid is still
    None is a pre-claim -- every turn-starting path (cmd_spawn's
    new_worker_record, cmd_send's idle-resume, future respawn) writes
    status="working"/turn_pid=None atomically under fleet_lock BEFORE the
    turn process actually exists, specifically so a concurrent reader
    (another send/attach/status) observes the claim and refuses instead of
    racing a second live `claude` onto the same session (SPEC §6/§9
    one-live-claude invariant). That guarantee only holds if recompute
    refuses to demote this exact window -- so, like "attached", "working"
    with pid is None is returned as-is here, never reinterpreted as
    idle/dead. Scoped tightly to pid is None: a "working" record with a
    real (non-None) pid that turns out to be dead must still demote
    normally (see the regression test pinning this).
    Residual (documented, not fixed): if the `fleet` CLI process itself is
    killed between the pre-claim write and the post-launch pid-stamp, the
    record is pinned "working" forever by this guard (turn_pid stays None,
    so it never re-enters the pid_alive check below) -- rare; the operator
    resolves it with `fleet respawn`.
    """
    if current_status == "attached":
        return "attached"
    if current_status == "working" and pid is None:
        return "working"
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


def append_mailbox(sid: str, message: str) -> None:
    """Append `message` to mailbox/<sid>.md (SPEC §7): a small
    open(..., "a") write, matching the hooks' own append discipline exactly
    -- multiple sends accumulate in one file and the next claim drains all
    of them (`fleet send` while working/attached, SPEC §5 send row)."""
    d = mailbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.md"
    with open(path, "a", encoding="utf-8") as f:
        f.write(message.rstrip("\n") + "\n\n")


_PREAMBLE_TEMPLATE = """You are fleet worker `{name}` in `{cwd}`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `{journal_target}` (create it early; update it at each milestone): goal, done, in-progress, blockers, next steps. It must be enough for a fresh session to continue.
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

    `task` may be empty/omitted (F6: cmd_send's idle-resume path routes the
    triggering message through the mailbox instead, so the drained mail
    already carries it) -- an empty task emits no task section at all
    rather than a blank line.

    SPEC §14: the preamble's journal target is rendered from the live
    journals_dir() (FLEET_HOME-derived) on every call, never a literal
    path -- so it follows FLEET_HOME/env-var overrides and test sandboxes
    exactly like every other path helper in this module.
    """
    journal_target = (journals_dir() / f"{name}.md").as_posix()
    parts = [_PREAMBLE_TEMPLATE.format(name=name, cwd=cwd, journal_target=journal_target)]

    mail, claim = claim_mailbox(sid)
    if mail:
        parts.append(f"<MANAGER MESSAGE>\n{mail}\n")

    if task:
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
                     settings_path: str | None = None) -> list:
    """Pure argv builder for one worker turn (SPEC §6). Raises ValueError
    (via mode_flags) for an unknown mode -- kept a pure function per the
    Task 2 brief so every mode/model/budget combo is unit-testable without
    touching Popen at all.

    settings_path defaults to str(instance_settings_path()) -- resolved
    fresh on every call (not baked into the signature at def-time, SPEC
    §14) so it follows FLEET_HOME/env-var overrides and test sandboxes the
    same way every other path helper in this module does. Callers needing
    the real machine instance must have already run `fleet init`
    (cmd_spawn/cmd_send enforce this via _require_instance_settings before
    ever reaching here)."""
    if settings_path is None:
        settings_path = str(instance_settings_path())
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
    """Raised when Popen() itself fails to start a turn process, OR (F-DOA)
    when the child dies during init before consuming its prompt. Callers
    (cmd_spawn et al) must restore_mailbox_claim() the pending claim on this
    exception -- the mailbox was never consumed by a live turn."""


# F-DOA/F-BLOCK: bounded window, after Popen() returns, during which
# launch_turn watches for a child that dies before consuming its prompt.
# Long enough to catch a fast init crash (bad --settings, MCP startup
# failure, auth/license error, invalid --resume sid); short enough to never
# meaningfully delay the manager for a healthy launch (the writer thread
# below typically finishes -- and this window is exited -- almost
# immediately for any launch that isn't actually wedged).
LAUNCH_DOA_WINDOW_SECONDS = 3.0
_DOA_POLL_INTERVAL_SECONDS = 0.05


def _write_prompt_and_close_stdin(proc, prompt: str, error_box: list) -> None:
    """Daemon-thread target (F-BLOCK): write the prompt to proc.stdin and
    close it, off the calling thread. The Windows anonymous-pipe buffer is
    ~4 KB and claude only reads the prompt after booting, so a synchronous
    write on the caller's thread would block fleet spawn/send for the
    child's entire boot (or indefinitely if it wedges pre-read). A
    BrokenPipeError here means the child's read end already closed -- i.e.
    it died before consuming the prompt (F-DOA) -- and is captured into
    error_box for launch_turn to inspect; any other OSError is best-effort
    (matches the pre-fix behavior for a hiccup on an already-started
    process) and is swallowed."""
    try:
        if proc.stdin is not None:
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
    except BrokenPipeError as exc:
        error_box.append(exc)
    except OSError:
        pass


def launch_turn(name: str, cwd, sid: str, prompt: str, mode: str, first: bool = False,
                 model=None, max_budget_usd=None,
                 popen=subprocess.Popen, get_process_info=None, which=shutil.which) -> dict:
    """Start one detached worker turn (SPEC §6): resolve claude, build argv,
    open per-worker logs (stdout -> logs/<name>.jsonl, stderr -> a separate
    logs/<name>.err so stderr noise never breaks jsonl parsing), Popen
    PLATFORM.detached_popen_kwargs() (the platform adapter, SPEC §14) with
    the worker's cwd (the --resume cwd-scope invariant, SPEC §2), hand the
    prompt write-and-close to a daemon thread (F-BLOCK -- never block the
    calling thread on the child's stdin) and watch for a DOA child within a
    bounded window (F-DOA), then query the new process's creation time via
    get_process_info (defaults to PLATFORM.get_process_info) so the registry
    can store an unambiguous turn_pid_ctime via ctime_to_iso -- the only
    serializer callers may use (F5 bridge).

    Returns {"turn_pid", "turn_pid_ctime", "log_path", "err_log_path"}.

    Raises ClaudeNotFoundError / TurnLaunchError for failures BEFORE or
    DURING the Popen() call itself, OR (F-DOA) when the child is detected to
    have died during init before consuming its prompt -- callers must
    restore_mailbox_claim() the pending claim in either case (the
    launch-sequence contract). Once launch_turn returns rather than raises,
    the turn is considered launched and the caller finalizes the claim and
    records turn_pid. This finalize-vs-restore decision stays entirely in
    the caller (cmd_spawn et al), keyed only on whether this function
    returned or raised.
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
                **PLATFORM.detached_popen_kwargs(),
            )
        except OSError as exc:
            raise TurnLaunchError(f"failed to launch claude turn for {name!r}: {exc}") from exc
    finally:
        out_f.close()
        err_f.close()

    # Popen() succeeded -- hand the prompt write off to a daemon thread
    # (F-BLOCK) so a slow/wedged reader can never block this thread, then
    # watch for a DOA child within a bounded window (F-DOA): either the
    # writer sees the read end already closed (BrokenPipeError) or poll()
    # reports a nonzero exit before the window elapses. Both are launch
    # failures; the caller's except path restores the mailbox claim and
    # rolls back the registry. A poll() of 0 is a legitimate ultra-fast
    # completed turn, not a failure. If the writer is still blocked when the
    # window elapses (a wedged pre-read child that never dies), this is
    # accepted as success -- irreducible without an unbounded wait, and it
    # self-surfaces later as a no-progress `working` worker.
    writer_error: list = []
    writer = threading.Thread(
        target=_write_prompt_and_close_stdin, args=(proc, prompt, writer_error), daemon=True,
    )
    writer.start()

    deadline = time.monotonic() + LAUNCH_DOA_WINDOW_SECONDS
    while True:
        writer.join(_DOA_POLL_INTERVAL_SECONDS)
        if writer_error:
            raise TurnLaunchError(
                f"claude turn for {name!r} closed its stdin before consuming the prompt "
                f"(child exited during init): {writer_error[0]}"
            )
        rc = proc.poll()
        if rc is not None:
            if rc != 0:
                raise TurnLaunchError(
                    f"claude turn for {name!r} exited with code {rc} during its launch "
                    "window, before consuming its prompt"
                )
            break  # rc == 0: legitimate ultra-fast completed turn -- success
        if not writer.is_alive():
            break  # writer finished (wrote+closed, or a best-effort OSError)
                   # and the process has not exited -- healthy launch
        if time.monotonic() >= deadline:
            break  # bounded window elapsed with the writer still blocked --
                   # accepted as success (see docstring residual above)

    get_process_info = get_process_info or PLATFORM.get_process_info
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
# Portability: worker-settings template render + instance freshness (SPEC §14)
#
# worker-settings.template.json (git-tracked, repo root) carries
# {{PYTHON}}/{{FLEET_HOME}} placeholders; `fleet init` (below, in the CLI
# section) renders it into instance_settings_path() (gitignored,
# machine-local). Both helpers here are pure/read-only so they are testable
# without touching cmd_init's file I/O.
# ---------------------------------------------------------------------------

_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")


def render_worker_settings_template(template_text: str, python_exe, fleet_home) -> str:
    """Pure render step for `fleet init` (SPEC §14): substitute
    {{PYTHON}} -> absolute forward-slash path to python_exe and
    {{FLEET_HOME}} -> absolute forward-slash path to fleet_home.

    Forward slashes only (matches SPEC §7's hook-command rule: Git Bash's
    `sh -c` eats backslashes in unquoted strings on Windows; POSIX shells
    are unaffected by forward slashes either way).

    Raises ValueError if any `{{NAME}}` placeholder remains unrendered
    after both substitutions -- a typo'd or new placeholder in the template
    must fail loudly at `fleet init` time, not silently render a broken
    settings file (SPEC §7: print-mode `claude` invocations swallow invalid
    --settings JSON silently, so this is the only alarm before a worker
    turn actually runs with dead hooks).
    """
    python_path = Path(python_exe).resolve().as_posix()
    fleet_home_path = Path(fleet_home).resolve().as_posix()
    rendered = template_text.replace("{{PYTHON}}", python_path).replace("{{FLEET_HOME}}", fleet_home_path)
    leftover = _TEMPLATE_PLACEHOLDER_RE.search(rendered)
    if leftover:
        raise ValueError(
            f"unrendered placeholder {leftover.group(0)!r} in worker-settings template "
            "-- only {{PYTHON}} and {{FLEET_HOME}} are supported"
        )
    return rendered


def instance_freshness_info() -> dict:
    """Read-only probe comparing the rendered instance
    (instance_settings_path()) against the git-tracked template it was
    rendered from (template_settings_path()) -- built for Task 5's `fleet
    doctor` freshness check (not wired into any command in this task).

    Returns a dict:
      - "template_exists" / "instance_exists": bool
      - "template_mtime" / "instance_mtime": raw st_mtime float, or None if
        the respective file is absent
      - "stale": True if the instance is missing (nothing to compare, and
        nothing for a worker turn to use -- SPEC §14's "run fleet init"
        error), or if both files exist and the template's mtime is newer
        than the instance's (edited after the last `fleet init`).
        A missing TEMPLATE with an existing instance is not flagged stale
        here (there is nothing to compare against) -- doctor may still
        want to warn about that separately; that policy lives in Task 5,
        not here.
    """
    template_path = template_settings_path()
    instance_path = instance_settings_path()

    template_exists = template_path.exists()
    instance_exists = instance_path.exists()
    template_mtime = template_path.stat().st_mtime if template_exists else None
    instance_mtime = instance_path.stat().st_mtime if instance_exists else None

    if not instance_exists:
        stale = True
    elif template_exists:
        stale = template_mtime > instance_mtime
    else:
        stale = False

    return {
        "template_exists": template_exists,
        "instance_exists": instance_exists,
        "template_mtime": template_mtime,
        "instance_mtime": instance_mtime,
        "stale": stale,
    }


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


def _require_instance_settings() -> None:
    """Fail fast with a clear, actionable error (SPEC §14) if the
    machine-local worker-settings.json instance hasn't been rendered yet --
    checked at spawn/send time, before any registry mutation or Popen call,
    so a missing instance never leaves a half-created worker record or a
    consumed mailbox claim behind. Without this check, a turn would still
    launch (build_turn_argv's --settings default just points at a
    nonexistent path) and `claude` would silently ignore the bad
    --settings value in print mode (SPEC §7) -- fleet hooks would simply
    never fire, with no error anywhere."""
    if not instance_settings_path().exists():
        raise FleetCliError(
            f"worker settings instance missing ({instance_settings_path()}) -- run `fleet init` first"
        )


def cmd_init(args) -> int:
    """`fleet init` (SPEC §14, §5 command surface): render the
    machine-local worker-settings.json instance from the git-tracked
    template. Idempotent -- always safe to re-run (e.g. after editing the
    template or moving the repo); never refuses. Uses sys.executable as
    {{PYTHON}} -- the absolute path of the interpreter running `fleet init`
    itself, which is what every worker turn's hook subprocess must invoke
    (hooks run outside fleet.py, spawned by `claude`, so they cannot fall
    back to a bare `py`/`python3` on PATH)."""
    template_path = template_settings_path()
    if not template_path.exists():
        raise FleetCliError(
            f"worker-settings template not found: {template_path} -- expected it at the fleet-home root"
        )
    template_text = template_path.read_text(encoding="utf-8")
    rendered = render_worker_settings_template(template_text, sys.executable, FLEET_HOME)

    instance_path = instance_settings_path()
    instance_path.parent.mkdir(parents=True, exist_ok=True)
    instance_path.write_text(rendered, encoding="utf-8")

    print(f"fleet init: wrote {instance_path}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    print(f"  fleet home:  {Path(FLEET_HOME).resolve().as_posix()}")
    return 0


def cmd_spawn(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which) -> int:
    """`fleet spawn <name> --dir <path> --task <text|@file> [--mode ...]
    [--model m] [--max-budget-usd x]` (SPEC §5 spawn row).

    Registry mutation (create the record) and event-append happen together
    inside one fleet_lock() -- the append_event/lock-discipline decision for
    Task 2 (see module docstring note below cmd_wait): every event this
    module appends is written while the registry lock for that same
    operation is held, so concurrent `fleet` invocations never interleave
    events with the registry state they describe.

    SPEC §14: refuses before any mutation if the worker-settings instance
    hasn't been rendered yet (_require_instance_settings) -- `fleet init`
    must run once per machine before the first spawn.
    """
    _require_instance_settings()

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
    except BaseException as exc:
        # Task-4-verdict re-review, Fix 2: same shape as cmd_send/cmd_attach
        # -- a Ctrl-C during launch must still pop the just-created record
        # and restore the drained mailbox claim, not leave a permanently
        # ghost-claimed "working"+turn_pid is None record behind.
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
            # F-RACE: re-assert "working" here -- a concurrent fleet
            # status/wait landing in the gap between this lock and the
            # create-lock above could have recomputed and persisted "dead"
            # (turn_pid was still None then). The turn has launched by
            # definition at this point, so this authoritatively repairs
            # that spurious transition.
            rec["status"] = "working"
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
# CLI: steering + hybrid commands (SPEC §5 send/interrupt/attach/release
# rows, §9 hybrid interaction model, §14 platform adapter)
# ---------------------------------------------------------------------------

def cmd_send(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which) -> int:
    """`fleet send <name> <text|@file>` (SPEC §5 send row, §9 attach
    asymmetry), rewritten under the uniform status-claim protocol (F1+F6,
    review wave 3):

    - working -> append the message to mailbox/<sid>.md (small
      open(...,"a") write); the running turn's hooks pick it up mid-turn or
      at Stop.
    - idle -> atomically pre-claim status="working"/turn_pid=None in the
      SAME fleet_lock that recomputed and observed "idle" (F1 -- mirrors
      new_worker_record's shape; recompute_status's launch-in-flight guard
      then refuses to demote this window, so a concurrent
      send/attach/status sees "working" and refuses instead of racing a
      second live turn onto this session). Outside the lock: append the
      new message to the mailbox, THEN compose_prompt with an empty task
      (F6 -- the message flows through the mailbox drain uniformly with any
      prior mail, not through compose_prompt's task argument, so it is
      never doubled and never silently dropped), then launch_turn. On
      success, re-acquire the lock once to stamp turn_pid/turn_pid_ctime/
      turns/last_activity and re-assert status="working" (matches
      cmd_spawn's second-lock re-assert, F-RACE). On failure,
      restore_mailbox_claim() the drained mail (so the new message
      survives) and conditionally roll the pre-claim back to "idle" (only
      if the record is still in the exact claim state this path wrote --
      status=="working" and turn_pid is None -- a concurrent actor may have
      legitimately moved it on already).
    - attached -> append to the mailbox like "working", but also print the
      attach-asymmetry warning (SPEC §9): the attached TUI runs without
      --settings, so hooks don't fire and the mail queues untouched until
      the next headless turn.
    - dead -> a clear error suggesting `fleet respawn`, never a silent no-op.

    SPEC §14: refuses up front (_require_instance_settings) if the
    worker-settings instance is missing -- checked unconditionally even
    though only the idle-resume branch below actually launches a turn,
    because `fleet spawn` (the only way a worker could exist at all) already
    requires the instance, so a real fleet never reaches this check with it
    absent; simplicity wins over branch-specific placement here.
    """
    _require_instance_settings()

    message = _read_task_arg(args.message)

    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = data["workers"][args.name]
        after = recompute_worker(args.name, before, get_process_info=get_process_info)
        status = after["status"]
        if status != before["status"]:
            append_event("status_changed", args.name, old=before["status"], new=after["status"])
        if status == "idle":
            # F1 pre-claim: atomic decide+claim, same lock, before release.
            after["status"] = "working"
            after["turn_pid"] = None
        data["workers"][args.name] = after
        save_registry(data)

    sid = after["session_id"]

    if status == "working":
        append_mailbox(sid, message)
        print(f"{args.name}: turn running -- message queued to mailbox")
        return 0

    if status == "attached":
        append_mailbox(sid, message)
        print(
            f"{args.name}: attached -- message queued to mailbox, but the attached "
            "terminal runs without --settings so fleet hooks don't fire there; it "
            "will not be delivered until the next headless turn (SPEC §9)"
        )
        return 0

    if status == "dead":
        raise FleetCliError(f"{args.name}: worker is dead -- run `fleet respawn {args.name}` first")

    # idle -> resume-turn launch. F6: append the new message to the mailbox
    # FIRST, then let compose_prompt drain the mailbox uniformly (prior mail
    # + this message, in order) -- task is intentionally empty so the
    # message is never carried both ways.
    append_mailbox(sid, message)
    prompt, claim = compose_prompt(args.name, after["cwd"], "", sid)
    try:
        info = launch_turn(
            args.name, after["cwd"], sid, prompt, after["mode"], first=False,
            model=after.get("model"), popen=popen, get_process_info=get_process_info, which=which,
        )
        finalize_mailbox_claim(claim)
    except BaseException:
        # Task-4-verdict re-review, Fix 2: BaseException (not Exception) --
        # a Ctrl-C landing mid-launch must still run this rollback. An
        # except Exception here would let KeyboardInterrupt skip straight
        # past it, pinning the pre-claim ("working"+turn_pid is None) as a
        # permanently-guarded ghost claim (recompute_status's launch-in-
        # flight guard never demotes it) and leaking the drained
        # mailbox's ".claimed" file forever.
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is not None and r.get("status") == "working" and r.get("turn_pid") is None:
                r["status"] = "idle"
                save_registry(data)
        raise

    with fleet_lock():
        data = load_registry()
        r = data["workers"].get(args.name)
        if r is not None:
            # Re-assert "working" (F-RACE, matches cmd_spawn's second-lock
            # re-assert): a concurrent status/wait could have recomputed a
            # spurious transition in the gap between the pre-claim above
            # and this stamp.
            r["status"] = "working"
            r["turn_pid"] = info["turn_pid"]
            r["turn_pid_ctime"] = info["turn_pid_ctime"]
            r["turns"] = r.get("turns", 0) + 1
            r["last_activity"] = now_iso()
            save_registry(data)
        append_event("turn_started", args.name, session_id=sid, turn_pid=info["turn_pid"])

    print(f"{args.name}: resumed -- {info['log_path']}")
    return 0


def _interrupt_worker(name: str, get_process_info=None, kill_process_tree=None) -> str:
    """Kill the running turn for `name`, if one is verifiably still alive
    (ctime-checked via pid_alive -- PID reuse must never kill an innocent
    process, SPEC §4). Shared by cmd_interrupt and cmd_attach's --force
    path.

    Returns one of three outcomes (F3+F4 uniform contract):
      - "killed": the turn was alive, kill_process_tree() was invoked, and
        a post-kill pid_alive() re-check confirms it is now gone -- the
        registry is committed to status="idle" and an "interrupted" event
        is appended.
      - "not_running": nothing was alive to kill (a friendly no-op, not an
        error -- the operator may race a turn that already finished); no
        mutation.
      - "kill_failed": the turn was alive, a kill was attempted, but the
        pid is STILL alive afterward. The registry is left untouched --
        marking idle here (the pre-fix defect) would let a caller launch a
        second live `claude` onto a session whose turn is still running.
        Callers must treat this as a hard failure, not a silent demotion.

    F4: the subprocess-shaped work (pid_alive's PowerShell Get-Process,
    kill_process_tree's taskkill) runs OUTSIDE fleet_lock -- both can take
    several seconds and LOCK_TIMEOUT_SECONDS is only 5.0, so holding the
    lock across them would make every concurrent `fleet` command fail with
    FleetLockTimeout. Shape: snapshot turn_pid/ctime under lock -> release
    -> probe/kill/re-verify outside the lock -> re-acquire only to commit
    "killed" (status write + its event stay under the same lock, preserving
    that ordering).

    F5 residual (documented, not fixed): Windows can reuse `pid` between
    the pre-kill pid_alive check and the taskkill call (TOCTOU) -- in the
    accepted, vanishingly unlikely worst case taskkill could hit an
    unrelated process that reused the pid within that window. The
    immediate pre-kill and post-kill pid_alive re-checks bound this to one
    subprocess-spawn latency; they do not close it.

    kill_process_tree defaults to PLATFORM.kill_process_tree (the platform
    adapter, SPEC §14) but is injectable so tests exercise the state
    machine without shelling out to a real taskkill.
    """
    kill_process_tree = kill_process_tree or PLATFORM.kill_process_tree

    with fleet_lock():
        data = load_registry()
        if name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {name!r}")
        rec = data["workers"][name]
        pid = rec.get("turn_pid")
        ctime_iso = rec.get("turn_pid_ctime")

    if not pid_alive(pid, ctime_iso, get_process_info=get_process_info):
        return "not_running"

    kill_process_tree(pid)

    if pid_alive(pid, ctime_iso, get_process_info=get_process_info):
        return "kill_failed"

    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is not None:
            rec["status"] = "idle"
            data["workers"][name] = rec
            save_registry(data)
        append_event("interrupted", name, turn_pid=pid)
    return "killed"


def cmd_interrupt(args, get_process_info=None, kill_process_tree=None) -> int:
    """`fleet interrupt <name>` (SPEC §5 interrupt row): ctime-verify the
    registered turn_pid, kill its whole process tree via the platform
    adapter, re-verify the kill (F3), mark idle, append an event.
    Not-running is a friendly no-op. A verified-failed kill is a loud
    warning and a nonzero exit -- the registry is deliberately left as-is
    (never marked idle while the turn may still be alive)."""
    outcome = _interrupt_worker(args.name, get_process_info=get_process_info, kill_process_tree=kill_process_tree)
    if outcome == "killed":
        print(f"{args.name}: interrupted")
        return 0
    if outcome == "not_running":
        print(f"{args.name}: no turn running -- nothing to interrupt")
        return 0
    print(
        f"fleet: {args.name}: kill attempted but the turn still appears to be running -- "
        "not marked idle; retry or investigate before attaching/sending",
        file=sys.stderr,
    )
    return 1


def cmd_attach(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which,
               kill_process_tree=None) -> int:
    """`fleet attach <name> [--force]` (SPEC §5 attach row, §9 hybrid
    model), rewritten under the uniform status-claim protocol (F1) plus the
    verified-kill contract (F3/F4, review wave 3):

    - already attached -> print a no-op warning.
    - working, no --force -> refuse (FleetCliError).
    - working, --force, turn_pid is None -> refuse loudly (FleetCliError,
      task-4-verdict re-review Fix 1). This is a turn-starter's own
      pre-claim window (spawn/send's launch-in-flight write, still lasting
      the whole launch_turn duration) -- there is no real pid yet, so
      _interrupt_worker would see pid=None, pid_alive(None)=False, and
      report "not_running", which used to read as clear-to-proceed and
      would race a second live claude onto the session against the
      concurrent starter. No registry write beyond the recompute persist,
      no popen.
    - working, --force, turn_pid set -> interrupt via _interrupt_worker
      OUTSIDE any lock held by this function (F4 -- taskkill/Get-Process
      must never run under fleet_lock). "killed" or "not_running" both mean
      the turn is no longer alive, so attach proceeds to the claim below;
      "kill_failed" (F3 -- the turn is still verifiably alive after the
      kill attempt) aborts loudly via FleetCliError with NO registry write
      and NO popen.
    - idle (or otherwise attachable) -> atomically pre-claim
      status="attached"/attached_since in the SAME fleet_lock that observed
      the attachable state (F1 -- status="attached" already survives
      recompute via the existing F7 guard, so this needs no new guard,
      only the ordering flip: claim before popen, never after). The
      terminal is then launched via PLATFORM.build_attach_argv (wt, else a
      detached PowerShell fallback -- F2 escapes any `'` in cwd for the PS
      fallback) OUTSIDE the lock, resumed in the worker's cwd (the
      --resume cwd-scope invariant, SPEC §2). If popen() itself raises, the
      claim is rolled back to idle (conditionally -- only if the record is
      still exactly "attached" that this call wrote). The attach terminal
      is intentionally detached, so its exit code is deliberately never
      probed (see build_attach_argv's docstring) -- correctness here comes
      from the claim ordering and the escaping fix, not from watching a
      detached child.
    """
    needs_force_interrupt = False

    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = data["workers"][args.name]
        after = recompute_worker(args.name, before, get_process_info=get_process_info)
        if after["status"] != before["status"]:
            append_event("status_changed", args.name, old=before["status"], new=after["status"])

        if after["status"] == "attached":
            data["workers"][args.name] = after
            save_registry(data)
            print(f"{args.name}: already attached")
            return 0

        if after["status"] == "working":
            if not args.force:
                data["workers"][args.name] = after
                save_registry(data)
                raise FleetCliError(
                    f"{args.name}: turn is running -- pass --force to interrupt it first, "
                    "or wait for it to finish"
                )
            if after.get("turn_pid") is None:
                # Task-4-verdict re-review, Fix 1: this is a turn-starter's
                # pre-claim window (status=="working", turn_pid is None --
                # see recompute_status's launch-in-flight guard above),
                # lasting the whole launch_turn duration. There is no real
                # pid yet to verify-kill: _interrupt_worker would snapshot
                # pid=None, pid_alive(None)=False, and return "not_running"
                # -- which cmd_attach would otherwise treat as clear-to-
                # proceed, popen-ing a second live claude while the
                # concurrent starter brings its own up. Refuse loudly
                # instead of racing it. Non-force already refuses on
                # "working" above; this only closes the --force hole.
                data["workers"][args.name] = after
                save_registry(data)
                raise FleetCliError(
                    f"launch in flight for {args.name}; retry in a few seconds"
                )
            # --force: persist the recompute and release -- the kill itself
            # (F4) must happen outside this lock.
            data["workers"][args.name] = after
            save_registry(data)
            needs_force_interrupt = True
        else:
            # Attachable (idle): claim atomically in this same lock (F1).
            after["status"] = "attached"
            after["attached_since"] = now_iso()
            data["workers"][args.name] = after
            save_registry(data)
            append_event("attached", args.name)

    cwd = after["cwd"]
    sid = after["session_id"]

    if needs_force_interrupt:
        outcome = _interrupt_worker(args.name, get_process_info=get_process_info, kill_process_tree=kill_process_tree)
        if outcome == "kill_failed":
            raise FleetCliError(
                f"{args.name}: --force could not verify the running turn was killed -- "
                "aborting attach (it may still be running)"
            )
        # "killed" or "not_running": the turn is no longer alive (or never
        # was); claim "attached" now, in a fresh lock.
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is None:
                raise FleetCliError(f"unknown worker: {args.name!r}")
            r["status"] = "attached"
            r["attached_since"] = now_iso()
            save_registry(data)
            append_event("attached", args.name)

    argv = PLATFORM.build_attach_argv(cwd, sid, which=which)
    try:
        popen(argv, cwd=str(cwd), **PLATFORM.detached_popen_kwargs())
    except BaseException:
        # Task-4-verdict re-review, Fix 2: BaseException so a Ctrl-C during
        # the popen call still rolls the "attached" pre-claim back to
        # idle -- except Exception would let KeyboardInterrupt through and
        # leave the worker permanently (and falsely) marked "attached".
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is not None and r.get("status") == "attached":
                r["status"] = "idle"
                r["attached_since"] = None
                save_registry(data)
        raise

    print(f"{args.name}: attached -- {argv[0]}")
    return 0


def cmd_release(args) -> int:
    """`fleet release <name>` (SPEC §5 release row): attached -> idle,
    clearing attached_since; a friendly no-op warning if not attached."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]
        if rec["status"] != "attached":
            print(f"{args.name}: not attached -- nothing to release")
            return 0
        rec["status"] = "idle"
        rec["attached_since"] = None
        data["workers"][args.name] = rec
        save_registry(data)
        append_event("released", args.name)
    print(f"{args.name}: released")
    return 0


# ---------------------------------------------------------------------------
# CLI: argparse wiring + main()
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet", description="claude-fleet manager CLI (M1)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="render the machine-local worker-settings.json instance from the template (SPEC §14)")

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

    p_send = sub.add_parser("send", help="send a message to a worker (mailbox or resume)")
    p_send.add_argument("name")
    p_send.add_argument("message")

    p_interrupt = sub.add_parser("interrupt", help="kill a worker's running turn")
    p_interrupt.add_argument("name")

    p_attach = sub.add_parser("attach", help="attach an interactive terminal to a worker")
    p_attach.add_argument("name")
    p_attach.add_argument("--force", action="store_true")

    p_release = sub.add_parser("release", help="release an attached worker back to idle")
    p_release.add_argument("name")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return cmd_init(args)
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
        if args.command == "send":
            return cmd_send(args)
        if args.command == "interrupt":
            return cmd_interrupt(args)
        if args.command == "attach":
            return cmd_attach(args)
        if args.command == "release":
            return cmd_release(args)
        parser.error(f"unknown command {args.command!r}")
        return 2
    except RegistryCorruptError as exc:
        print(f"fleet: registry error: {exc}", file=sys.stderr)
        return 1
    except (FleetCliError, ClaudeNotFoundError, TurnLaunchError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
