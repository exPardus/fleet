"""fleet.py -- claude-fleet core logic layer.

Single-file, stdlib-only CLI for one Claude Code "manager" session to spawn,
monitor, steer, and hand off multiple headless "worker" sessions.

Layering: pure-logic core (paths, registry, events, PID liveness,
stream-jsonl parsing, prompt composition, permission mode mapping) first,
then the argparse-based main() and its subcommands built on top of those
functions.

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
import ctypes
import json
import math
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
from datetime import datetime, timedelta, timezone
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


def ceilings_dir() -> Path:
    """Kernel 10 (fleet half, F12=M24): dir holding sid-keyed token-ceiling
    files. Path MUST match bin/hooks/stop_mailbox.py's _ceiling_path
    (state/ceilings/<session_id>) -- fleet.py WRITES these on launch; the
    Stop hook only READS them to decide whether to allow a stop despite
    pending mail."""
    return state_dir() / "ceilings"


def ceiling_file_path(sid: str) -> Path:
    return ceilings_dir() / sid


def outcomes_dir() -> Path:
    return state_dir() / "outcomes"


def outcome_path(key: str) -> Path:
    return outcomes_dir() / f"{key}.jsonl"


def tasks_dir() -> Path:
    return state_dir() / "tasks"


def task_file_path(name: str) -> Path:
    return tasks_dir() / f"{name}.md"


def archive_root() -> Path:
    return logs_dir() / "archive"


def pin_pass_path() -> Path:
    return state_dir() / "pin-pass.json"


def is_native(record: dict) -> bool:
    if not isinstance(record, dict):
        return False
    return record.get("dispatch_kind") == "bg"


def refuse_if_legacy(name: str, record: dict, action: str) -> None:
    if not is_native(record):
        raise FleetCliError(
            f"{name}: pre-pivot worker -- {action} unavailable; "
            "kill or clean via legacy path"
        )


def _write_ceiling_file(sid: str, ceiling) -> None:
    """Kernel 10 (fleet half): persist the sid-keyed token ceiling that the
    Stop hook (stop_mailbox.py:_read_ceiling) reads. No-op when ceiling is
    None (no ceiling in force -> the hook keeps its default block-on-mail
    behavior). Atomic (temp + os.replace) so a concurrent hook read never
    sees a half-written file. Best-effort: a ceiling we cannot persist just
    means the hook has no allow-stop signal -- it never breaks a launch."""
    if ceiling is None:
        return
    d = ceilings_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{sid}.tmp"
    tmp.write_text(str(int(ceiling)), encoding="utf-8")
    os.replace(str(tmp), str(ceiling_file_path(sid)))


def knowledge_dir() -> Path:
    return FLEET_HOME / "knowledge"


def registry_path() -> Path:
    return state_dir() / "fleet.json"


def events_path() -> Path:
    return state_dir() / "events.jsonl"


def hook_errors_path() -> Path:
    """Append-only log of swallowed hook exceptions (phase1 kernel 1): hooks
    keep the exit-0-on-any-error invariant (SPEC invariant 2) but record one
    line per swallowed exception here. fleet.py only ever READS it -- `fleet
    status` surfaces a total count, `fleet doctor` shows the tail."""
    return state_dir() / "hook-errors.log"


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


def user_settings_path() -> Path:
    """~/.claude/settings.json -- the ONLY file outside FLEET_HOME that fleet
    ever writes, and only via `fleet init --statusline` (Phase 1.6 D6).
    Separate helper so tests can redirect it without touching a developer's
    real settings."""
    return Path.home() / ".claude" / "settings.json"


def statusline_script_path() -> Path:
    return FLEET_HOME / "bin" / "fleet_statusline.py"


def fleet_home_marker_path() -> Path:
    """~/.claude/fleet-home -- one line: the absolute FLEET_HOME.

    Written by `fleet init`. Exists because the plugin's SessionStart hook may
    run from a MARKETPLACE CACHE COPY of this repo, whose own location is not
    the operator's real fleet home; resolving FLEET_HOME from the script's
    location would make the hook read an empty registry inside the cache while
    the operator's `fleet` CLI writes somewhere else entirely."""
    return Path.home() / ".claude" / "fleet-home"


def _write_fleet_home_marker() -> None:
    """Best-effort: a missing marker degrades the hook, never breaks fleet."""
    path = fleet_home_marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(Path(FLEET_HOME).resolve().as_posix() + "\n", encoding="utf-8")
    except OSError:
        pass


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
        """Three-way probe (F15/M4). Returns:
          * None                 -- the pid does not exist (definitely gone)
          * (image_name, ctime)  -- process exists and its UTC start time was
                                    readable (alive-and-readable)
          * (image_name, None)   -- process exists but its StartTime is
                                    unreadable (Access Denied on an elevated/
                                    system process, or CIM also fails) -- the
                                    "exists-but-unreadable = alive-unknown"
                                    case, which callers must NEVER classify as
                                    dead (never reap a live worker on a probe
                                    hiccup, SPEC §4/F20 three-way probe).

        stdlib subprocess route (no third-party deps): asks PowerShell's
        Get-Process for the process name and UTC start time; the try/catch in
        the script emits a `NAME|ACCESS_DENIED` marker when StartTime throws,
        after one Get-CimInstance (Win32_Process CreationDate) fallback
        attempt. Kept as a single small method so pid_alive()/probe_liveness()/
        recompute_status()/launch_turn() can accept an injected replacement in
        tests instead of touching real processes.
        """
        try:
            script = (
                f"$p = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
                "if ($p) { "
                "  try { "
                "    \"$($p.ProcessName)|$($p.StartTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss'))\" "
                "  } catch { "
                "    try { "
                f"      $c = Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" -ErrorAction Stop; "
                "      \"$($p.ProcessName)|$($c.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss'))\" "
                "    } catch { "
                "      \"$($p.ProcessName)|ACCESS_DENIED\" "
                "    } "
                "  } "
                "}"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=5,
            )
            line = (result.stdout or "").strip()
            if not line or "|" not in line:
                return None
            name, ctime_str = line.rsplit("|", 1)
            if ctime_str == "ACCESS_DENIED":
                # Process exists, StartTime unreadable -> alive-unknown.
                return name, None
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
    # Fuzz-report Finding F2 (HIGH): `data.setdefault("workers", {})` alone
    # only fills in a MISSING "workers" key -- it is a no-op when the key is
    # present but the wrong shape (a list/string/int), which sails through
    # as a "valid" registry and then crashes every subcommand downstream
    # (dict.keys()/.get()/.pop()/`in`/sorted() all raise on a non-dict).
    # Validate the shape explicitly here -- the one place this module reads
    # the registry off disk -- so a malformed "workers" value is quarantined
    # exactly like a decode failure, never allowed to flow downstream.
    workers = data.get("workers", {})
    if not isinstance(workers, dict) or not all(isinstance(v, dict) for v in workers.values()):
        quarantined = _quarantine_registry(path)
        raise RegistryCorruptError(
            f"registry 'workers' was not an object of objects; quarantined to {quarantined}"
        )
    data["workers"] = workers
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


def current_caller_session() -> str | None:
    """The Claude Code session id of whoever is running this CLI, or None when
    fleet is run by a human from a plain shell.

    Provenance for the destructive-command guard (§5.1): a session may retire
    the workers it spawned without ceremony, but must explicitly acknowledge
    (`--yes`) before killing or sweeping someone else's."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return sid or None


def new_worker_record(session_id, cwd, task, mode, model=None, created=None,
                       max_budget_usd=None, setting_sources=None, token_ceiling=None,
                       spawned_by=None, dispatch_kind=None, category=None) -> dict:
    """Build a fresh registry record matching the SPEC §4 schema exactly.

    Phase1 kernel item 7 (F13/M5): max_budget_usd and setting_sources are
    persisted here and recorded at spawn, IMMUTABLE like `mode` -- every
    launch path (spawn, send-when-idle resume, respawn) re-emits them from
    THIS persisted value so a worker steered with N sends stays capped and
    keeps its foreign-hook --setting-sources remedy on turns 2..N, not just
    turn 1. Additive-schema (M1): both default to None, readers everywhere
    use .get(..., None) so a record written before these fields existed
    loads cleanly, and save_registry preserves any unknown fields verbatim
    on write."""
    created = created or now_iso()
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        "task": task[:200],
        "mode": mode,
        "model": model,
        "max_budget_usd": max_budget_usd,
        "setting_sources": setting_sources,
        # Kernel 10 (F12=M24): a TOKEN count (int), immutable like
        # max_budget_usd -- the fleet-side hard cap enforced before a resume
        # launch, and the value cmd_spawn/cmd_respawn persist to the sid-keyed
        # ceiling file the Stop hook reads. Additive-schema: defaults None,
        # readers use .get(..., None).
        "token_ceiling": token_ceiling,
        # Provenance (§5.1 destructive-command guard): the CLAUDE_CODE_SESSION_ID
        # of the session that spawned this worker, or None when spawned by a
        # human shell. Immutable, carried across respawn. Additive-schema (M1):
        # readers default it to None -- and an UNKNOWN owner is treated as
        # FOREIGN, never as "mine", so pre-existing records are protected too.
        "spawned_by": spawned_by,
        "created": created,
        "status": "working",
        "turn_pid": None,
        "turn_pid_ctime": None,
        "attached_since": None,
        # UL1 (item 11 / F31): usage-limit park horizon. limit_reset_at is the
        # ISO-8601 UTC instant the Claude plan window resets (or None when the
        # signal carried no parseable reset time -> parked with an unknown
        # horizon, surfaced for an operator-set reset, never auto-resumed
        # blind); limit_kind is session_5h | weekly | None. Additive-schema
        # (M1): both default None, readers use .get(..., None), save_registry
        # preserves them on round-trip. Only meaningful while status=="limited".
        "limit_reset_at": None,
        "limit_kind": None,
        "turns": 0,
        "cost_usd": 0.0,
        # Task 5 fix wave, Finding 4 (task-5 adversarial review): the
        # amount spent in sessions PRIOR to this one -- recompute_worker
        # adds this to the current (rotated-fresh) log's own trailing
        # result cost so cost_usd stays cumulative across a respawn's
        # fresh session_id/log instead of being overwritten by it. 0.0
        # for a brand-new worker (spawn); cmd_respawn sets it to the
        # carried-forward cost_usd for a respawned one. Missing on old
        # registry records (pre-this-field) is tolerated -- .get(...,
        # 0.0) everywhere it's read.
        "cost_baseline": 0.0,
        "last_activity": created,
        # --- M-B native-substrate fields (spec §5; None/[] on legacy records) ---
        "dispatch_kind": dispatch_kind,      # "bg" = daemon-hosted; None = pre-pivot Popen
        "category": category,                # agents-menu category (spec §5.1.3)
        "native_short_id": None,             # short id from --bg stdout (G6 fallback)
        "last_dispatch_at": None,            # stamped at every dispatch/steer/resume;
                                             # anchor for the fresh-outcome predicate
        "retired_sids": [],                  # prior sids retired by fork-steer/respawn
        "archived_at": None,                 # set by auto-archival; hides from status
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


def probe_liveness(pid, ctime_iso, get_process_info=None) -> str:
    """Three-way liveness probe (F15/M4). Returns one of:
      * "alive"   -- pid exists, is a claude/node/cmd process (F-CMD), and its
                     creation time matches ctime_iso within +/-2s
      * "unknown" -- pid exists and matches the image name, but its start time
                     is unreadable (get_process_info returned (name, None) --
                     the exists-but-unreadable = ALIVE-UNKNOWN case). Callers
                     must NEVER demote this to "dead" (never reap a live worker
                     on a probe hiccup, SPEC §4/F20 three-way probe).
      * "gone"    -- pid is absent, is an unrelated (reused) process, or the
                     recorded ctime is unparseable/does not match (PID reuse
                     otherwise misclassifies a dead worker as alive, SPEC §4).
    """
    if pid is None or ctime_iso is None:
        return "gone"
    get_process_info = get_process_info or PLATFORM.get_process_info
    info = get_process_info(pid)
    if info is None:
        return "gone"
    name, ctime = info
    name_l = (name or "").lower()
    if not any(candidate in name_l for candidate in _ALIVE_IMAGE_NAMES):
        return "gone"
    if ctime is None:
        # Process exists + image name matches, but StartTime unreadable.
        return "unknown"
    try:
        recorded = _parse_iso(ctime_iso)
    except (ValueError, TypeError):
        return "gone"
    return "alive" if abs((ctime - recorded).total_seconds()) <= 2.0 else "gone"


def pid_alive(pid, ctime_iso, get_process_info=None) -> bool:
    """True iff the three-way probe reports "alive" -- i.e. pid exists, is a
    claude/node/cmd process (F-CMD), and its creation time matches ctime_iso
    within +/-2s (PID reuse otherwise misclassifies a dead worker as working
    -- SPEC §4). "unknown"/"gone" both return False here; callers needing the
    alive-unknown distinction (recompute_status) use probe_liveness directly."""
    return probe_liveness(pid, ctime_iso, get_process_info=get_process_info) == "alive"


# Task 5 perf item (SPEC §12): status/wait polling calls _last_line_type /
# tail_events once per worker per poll -- on a multi-hundred-MB stream-json
# log (verbose+stream-json is fat, SPEC §11 "log bloat") a whole-file
# f.readlines() every poll is wasteful. Every real caller in this module
# only ever wants the trailing well-formed line or the trailing N digest
# events (_last_line_type, tail_events(n=...), and recompute_worker's
# tail_events(n=50)) -- all comfortably within a 64KB trailing window for
# any log this fleet actually produces, so reading just the tail is
# behaviorally identical to reading the whole file for every real call
# site, not merely "close enough".
_TAIL_READ_BYTES = 64 * 1024


def _read_tail_lines(log_path) -> list:
    """Return decoded, newline-split lines from the trailing
    _TAIL_READ_BYTES of log_path (or the whole file if it is smaller than
    that window -- identical to the pre-optimization behavior in that
    common case). When the window's start lands mid-line, the partial
    leading fragment is discarded -- exactly like a truncated final line
    was already defensively skipped by every caller's junk-line handling,
    so parser semantics are unchanged; only the byte range considered
    shrinks. Missing/unreadable files return []."""
    log_path = Path(log_path)
    try:
        size = log_path.stat().st_size
    except OSError:
        return []
    try:
        with open(log_path, "rb") as f:
            if size > _TAIL_READ_BYTES:
                f.seek(size - _TAIL_READ_BYTES)
                chunk = f.read()
                nl = chunk.find(b"\n")
                if nl == -1:
                    # Task 5 fix wave, Finding 2 (task-5 adversarial
                    # review): no newline anywhere in the trailing
                    # window -- an oversized final line with no
                    # terminator yet (still being written), or one line
                    # alone spans the whole window. Discarding it as a
                    # "partial leading fragment" would silently drop
                    # real content; fall back to the whole file.
                    f.seek(0)
                    chunk = f.read()
                else:
                    chunk = chunk[nl + 1:]
                    if chunk == b"":
                        # The only newline in the window was the
                        # oversized trailing line's OWN terminator, so
                        # "discard up to and including the first
                        # newline" would drop that entire line -- a real
                        # single stream-json event (e.g. a big result
                        # payload) can exceed 64KB. Fall back to the
                        # whole file so it is never silently lost;
                        # parser semantics are unchanged for every other
                        # shape, only this one edge case is corrected.
                        f.seek(0)
                        chunk = f.read()
            else:
                chunk = f.read()
    except OSError:
        return []
    return chunk.decode("utf-8-sig", errors="replace").splitlines()


def _last_line_type(log_path) -> str | None:
    """Return the "type" field of the last SUBSTANTIVE well-formed JSON line
    in log_path (perf: reads only the trailing window via _read_tail_lines,
    see above).

    SMOKE-A (integration-smoke.md Finding A, live-proven): a completed
    turn's own "result" event is NOT reliably the literal last line written
    to the log -- an async hook's response (observed live: a fresh spawn's
    "SessionStart:startup" hook, a `send`-resumed turn's
    "SessionStart:resume" hook) can race the result line and land after it,
    on every real launch this fleet produced in the integration smoke test.
    Classifying by the literal last line then misreads a healthy,
    result-bearing completed turn as "dead" instead of "idle" (recompute_
    status's rule is keyed on "trailing result event"). Fix: scan backwards
    past any `"type":"system"` line -- hook_started/hook_response/
    hook_progress, and other bookkeeping lines like init/thinking_tokens
    are all type "system" -- and past any junk/non-JSON line, returning the
    type of the first genuinely substantive event found (result/assistant/
    user -- i.e. something the turn's own model loop emitted, not hook or
    system plumbing)."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    for line in reversed(_read_tail_lines(log_path)):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        etype = obj.get("type")
        if etype == "system":
            continue  # hook/system bookkeeping -- not substantive, keep scanning
        return etype
    return None


# Post-testing wave, item 1c (stress-report Finding 1, zombie-escape hatch):
# how long a "working"/turn_pid=None pre-claim is allowed to sit before
# recompute_status stops treating it as a real in-flight launch and demotes
# it to "dead" instead. Every real launcher (launch_turn, called
# synchronously from cmd_spawn/cmd_send/cmd_respawn) stamps the real pid
# within, at most, LAUNCH_DOA_WINDOW_SECONDS (3s) plus one Popen() call --
# so a claim still unstamped after ten minutes did not just lose a race, it
# lost its launcher (the `fleet` CLI process itself crashed, was killed, or
# lost power between the pre-claim write and the post-launch commit).
LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0


def _launch_claim_expired(last_activity_iso) -> bool:
    """True iff a "working"/turn_pid=None pre-claim's last_activity is older
    than LAUNCH_CLAIM_MAX_AGE_SECONDS (or is missing/unparseable -- treated
    as NOT expired, matching the pre-fix behavior of never demoting when
    there's no age information to go on). Shared by recompute_status (the
    general liveness recompute) and cmd_kill's own launch-in-flight guard
    (which intentionally skips a full recompute_worker probe, so it needs
    this check standalone)."""
    if not last_activity_iso:
        return False
    try:
        age = (datetime.now(timezone.utc) - _parse_iso(last_activity_iso)).total_seconds()
    except (ValueError, TypeError):
        return False
    return age > LAUNCH_CLAIM_MAX_AGE_SECONDS


def recompute_status(pid, ctime_iso, log_path, current_status: str | None = None, get_process_info=None,
                     last_activity_iso=None, sleep=time.sleep) -> str:
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

    Zombie escape hatch (post-testing wave, item 1c -- was "Residual
    (documented, not fixed)" above): the guard above is now time-bounded via
    `last_activity_iso` + LAUNCH_CLAIM_MAX_AGE_SECONDS. If the `fleet` CLI
    process itself is killed between the pre-claim write and the
    post-launch pid-stamp -- or the post-launch commit lock is lost for
    good (see `_commit_launched_turn`'s own docstring for the bounded-retry
    mitigation of the common case) -- the record no longer stays pinned
    "working" forever: once `last_activity` is older than
    LAUNCH_CLAIM_MAX_AGE_SECONDS (real launchers stamp the pid within
    seconds), this demotes straight to "dead", making it recoverable through
    every normal dead-worker path (`fleet kill`, `fleet attach --force`,
    `fleet respawn --force`/`fleet respawn`, `fleet clean`) instead of
    requiring manual registry surgery. `last_activity_iso=None` (the
    default, and what every pre-fix caller still passes) preserves the old
    "never demote" behavior -- callers must opt in by passing the record's
    own `last_activity` field.

    SMOKE-D (integration-smoke.md Finding D, live-proven): "dead" set by an
    operator action (`fleet kill`) must be STICKY, mirroring the "attached"
    guard above -- recompute's job is demotion (working/idle -> dead), not
    resurrection. Without this, a killed worker whose log tail legitimately
    ends on a trailing result event (the common "healthy, done" case) would
    recompute straight back to "idle" on the very next status/clean call --
    live-reproduced: `kill` marked it dead, and the immediate next `clean`
    (and a bare `status`) flipped it back to idle, making `kill` non-
    terminal and the worker permanently un-cleanable via the CLI. `fleet
    respawn` is the one recovery lever out of "dead" -- it always starts a
    brand-new record via new_worker_record (status="working"), never by
    demoting through this function, so this guard cannot block a real
    recovery.
    """
    if current_status == "attached":
        return "attached"
    if current_status == "dead":
        return "dead"
    # Phase1 kernel item 7 (F13/M5): "over_budget" is a sticky terminal flag
    # set by cmd_send's cumulative-cost check when a worker's lifetime
    # cost_usd exceeds its persisted max_budget_usd. Like "attached"/"dead",
    # a liveness recompute must never silently revert it to idle/dead -- the
    # operator raises the cap (a fresh respawn record) or retires the worker.
    if current_status == "over_budget":
        return "over_budget"
    # Kernel 10 (F12=M24): "over_ceiling" is the token analog of over_budget
    # -- set by cmd_send's cumulative-token check when a worker's session
    # tokens exceed its persisted token_ceiling. Sticky for the same reason:
    # a liveness recompute must not silently revert it (respawn with a higher
    # ceiling, or retire the worker).
    if current_status == "over_ceiling":
        return "over_ceiling"
    # UL1 (item 11 / F31): "limited" is a plan-usage-limit park, sticky-until-
    # reset exactly as dead/attached are sticky. A liveness recompute must
    # NEVER demote it to dead: a parked worker legitimately holds no live
    # claude (its turn ended at the plan wall, not in a crash), so "no live PID
    # + no result" is the EXPECTED shape here, not a crash signal. The sole
    # exits are a `fleet resume-limited` launch (limited -> working, once
    # now >= limit_reset_at) or `respawn --force` (a fresh new_worker_record).
    if current_status == "limited":
        return "limited"
    if current_status == "working" and pid is None:
        if _launch_claim_expired(last_activity_iso):
            return "dead"
        return "working"
    # F15/M4 three-way probe: "alive" and "unknown" (exists-but-unreadable
    # StartTime) BOTH stay working -- alive-unknown is never demoted to dead,
    # so a live worker whose StartTime is momentarily unreadable is never
    # reaped (SPEC §4/F20). Only a "gone" verdict is a demotion candidate.
    verdict = probe_liveness(pid, ctime_iso, get_process_info=get_process_info)
    if verdict in ("alive", "unknown"):
        return "working"
    if _last_line_type(log_path) == "result":
        return "idle"
    # verdict == "gone" AND no trailing result -> would demote to "dead". For a
    # working record with a real pid, retry the probe ONCE after a short delay
    # (mirroring _DEAD_CONFIRM_DELAY_SECONDS) before committing to dead, so a
    # single transient probe miss cannot reap a live turn.
    if current_status == "working" and pid is not None:
        sleep(_DEAD_CONFIRM_DELAY_SECONDS)
        verdict = probe_liveness(pid, ctime_iso, get_process_info=get_process_info)
        if verdict in ("alive", "unknown"):
            return "working"
        if _last_line_type(log_path) == "result":
            return "idle"
    return "dead"


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
    and system-only events; tolerates missing or truncated files.

    Perf (SPEC §12): reads only the trailing window via _read_tail_lines
    rather than the whole file -- every caller here only ever wants a
    bounded trailing slice of events, so this is behaviorally identical to
    a whole-file read for any log this fleet actually produces (see
    _read_tail_lines's docstring)."""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    lines = _read_tail_lines(log_path)

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
        # F9 (item 8): emit a mail_drained audit event at compose-time drain.
        # fleet.py is the SOLE writer of events.jsonl -- this is a Soak-1 audit
        # record, NOT a DLQ (no retry/redelivery machinery). compose_prompt is
        # only ever called by fleet.py launch paths, so the single-writer
        # registry invariant (6) is preserved.
        append_event("mail_drained", name, sid=sid)

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
                     settings_path: str | None = None, setting_sources: str | None = None) -> list:
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
    ever reaching here).

    setting_sources is a Task 5 audit-gap item (SPEC §6 L125, spec-audit
    gap 5): a raw passthrough string (whatever `claude --setting-sources`
    itself accepts, e.g. "user,project") appended verbatim as
    `--setting-sources <value>` when given -- fleet does not parse or
    validate its contents, only forwards it, so a worker repo's own
    foreign Stop-hook (or other unwanted merged settings) can be excluded
    per spawn without fleet inventing its own mini-grammar for it."""
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
    if setting_sources:
        argv += ["--setting-sources", setting_sources]
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


def _worker_env(name: str) -> dict:
    """Child environment for a worker turn: the parent's, plus FLEET_WORKER.

    Phase 1.6 D5: a globally-enabled fleet plugin fires its SessionStart hook
    in EVERY Claude Code session on this machine, including every worker turn.
    The hook reads FLEET_WORKER and suppresses itself, so a worker never gets
    the manager's fleet briefing injected into its context.

    os.environ is copied explicitly -- passing env= at all replaces the whole
    inherited environment, and a child without PATH cannot launch.

    CLAUDE_CODE_SESSION_ID is STRIPPED (§5.1 provenance): the child `claude`
    stamps its own, and an inherited one would make a worker running
    `fleet kill` look exactly like the manager that spawned it -- so a worker
    could quietly retire its siblings with no confirmation."""
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env["FLEET_WORKER"] = name
    return env


def launch_turn(name: str, cwd, sid: str, prompt: str, mode: str, first: bool = False,
                 model=None, max_budget_usd=None, setting_sources=None,
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
    # Phase1 kernel 4 (cwd preflight): never launch/resume a turn into a
    # vanished directory. Every launch path (spawn, send-resume, respawn)
    # funnels through here, so one guard covers them all -- and raising
    # BEFORE the Popen keeps the launch-sequence contract intact (the caller
    # restores the mailbox claim on any raise, same as a resolve/argv error).
    if not os.path.isdir(cwd):
        raise TurnLaunchError(f"registered cwd no longer exists, refusing to launch {name!r}: {cwd}")

    claude_exe = resolve_claude_executable(which=which)
    argv = build_turn_argv(claude_exe, sid, first, mode, model=model, max_budget_usd=max_budget_usd,
                            setting_sources=setting_sources)

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
                env=_worker_env(name),
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


def _coerce_cost(value):
    """Best-effort coercion of a raw cost value (a `result` event's
    total_cost_usd/cost_usd field, or a registry record's own
    cost_baseline/cost_usd field) to a finite, non-negative float, or None
    if it can't be trusted (fuzz-report Findings F3/F4).

    A string that parses cleanly via float() is accepted (a hand-edited
    registry, or a hostile log line, could hold a numeric string even
    though `claude` itself always emits a JSON number) -- anything that
    doesn't parse cleanly returns None rather than raising. bool is
    rejected even though it's an int subclass (a JSON true/false is never a
    sane cost). NaN/+Infinity/-Infinity -- all of which json.loads accepts
    by default via its non-standard constant parsing -- and any negative
    number are rejected: letting one of those into a running sum would
    permanently poison cost_usd (until the next respawn wipes the log)
    with no crash and no visible warning. Never raises."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _registry_cost(value) -> float:
    """`_coerce_cost` with a 0.0 fallback, for reading a registry record's
    OWN cost_baseline/cost_usd field back off disk (as opposed to a fresh
    value being summed from a log's result events, which must distinguish
    "no valid cost found at all" from "found and it was legitimately
    0.0") -- guards against a previously-poisoned (NaN/Infinity/negative)
    value that got persisted before this hardening existed, or a
    hand-edited registry, from propagating forward forever."""
    coerced = _coerce_cost(value)
    return coerced if coerced is not None else 0.0


def _sum_result_costs(log_path) -> float | None:
    """Sum the cost of every "result" event in the WHOLE log file (not just
    the trailing window), or None if the file is missing/unreadable or has
    no result event at all (caller keeps the prior cost_usd unchanged in
    that case).

    SMOKE-B (integration-smoke.md Finding B, live-proven): cost is reported
    PER-INVOCATION on `--resume` turns, not cumulatively by `claude` itself
    -- observed live across a spawn + two `send`-resumed turns in the same
    session, where the second turn's own result event reported a SMALLER
    total_cost_usd than the first (a fresh per-turn number, not a running
    session total). recompute_worker used to take only `results[-1]`'s
    cost, so a multi-turn `send` sequence within one session (no respawn --
    cost_baseline stays 0.0 there) would silently drop the display back to
    just the latest turn's cost instead of the session's real running
    total. Summing every result event's cost in the current log file fixes
    this; a whole-file read is acceptable here (unlike the hot tail-read
    path used for status/wait polling) because logs rotate to a fresh file
    on every respawn (_rotate_worker_log) and doctor's log-size check warns
    well before a single file could grow unreasonably large."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    try:
        raw = log_path.read_bytes()
    except OSError:
        return None
    total = 0.0
    found = False
    for line in raw.decode("utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or obj.get("type") != "result":
            continue
        cost = obj.get("total_cost_usd", obj.get("cost_usd"))
        if cost is not None:
            coerced = _coerce_cost(cost)
            if coerced is not None:
                total += coerced
                found = True
    return total if found else None


def _sum_result_tokens(log_path) -> int | None:
    """Sum input_tokens+output_tokens across every "result" event's usage in
    the WHOLE log file, or None if the file is missing/unreadable or carries
    no result event with usage at all (caller treats None as "nothing proven
    over ceiling").

    Fleet-side half of kernel 10 (F12=M24): the cumulative session token
    count used to HARD-enforce a worker's token_ceiling before a resume
    launch. Reads the SAME token keys as the Stop hook's _current_tokens
    (input_tokens+output_tokens), best-effort -- but the two halves have
    DIFFERENT enforcement roles, not an identical computation: the Stop hook
    only ever ALLOWS a stop (never blocks -- invariant 2), while fleet hard-
    ENFORCES the refusal here (over_ceiling + a refused resume). FIX-3 aligns
    only the >= boundary so they agree on when tokens == ceiling counts as
    over. A whole-file read is
    acceptable for the same reason _sum_result_costs's is: logs rotate to a
    fresh file on every respawn. Bogus values (bool, negative, non-int) are
    skipped, mirroring _coerce_cost's defensive stance."""
    log_path = Path(log_path)
    if not log_path.exists():
        return None
    try:
        raw = log_path.read_bytes()
    except OSError:
        return None
    total = 0
    found = False
    for line in raw.decode("utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or obj.get("type") != "result":
            continue
        usage = obj.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in ("input_tokens", "output_tokens"):
            val = usage.get(key)
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                continue
            total += val
            found = True
    return total if found else None


# ---------------------------------------------------------------------------
# UL1 usage-limit detection (item 11 / F31) -- CONSERVATIVE FALLBACK.
#
# The exact live turn-end signal a Claude PLAN usage-limit wall emits is
# DEFERRED-TO-KERNEL-PROBE: the real wall cannot be forced on demand (it would
# burn the operator's actual plan usage), and `claude --help` (2.1.204) exposes
# no usage/reset surface. So this is NOT a verified signal -- it is the
# intent-§3-clause-2 fallback the SPEC (F31 detection contract) mandates until
# a real wall confirms the precise pattern: an errored turn (no `result` stream
# event) whose stderr is LIMIT-SHAPED is parked `limited` (surfaced for operator
# confirmation), while a non-limit-shaped errored turn stays the ordinary
# crash-dead path. The regex is deliberately conservative -- a genuine crash
# must never be swallowed as a park.
# ---------------------------------------------------------------------------

# FIX-2 (F-A2): tightened to recognize a CLAUDE PLAN usage-limit wall, never an
# ordinary infra crash. Require a plan/usage-limit NOUN adjacent to "limit"
# (usage|weekly|session|plan|5-hour limit), OR the explicit "limit ... resets
# at <time>" wall shape. Deliberately DROPS the bare `quota` / bare `rate limit`
# / bare `try again later` alternatives that collided with real failures --
# disk-quota (EDQUOT), an upstream MCP `429 rate limit`, a `try again later`
# assertion -- which must stay the crash-dead path (surfaced + journal note),
# not a silent null-horizon park. When unsure, prefer crash-dead.
_LIMIT_STDERR_RE = re.compile(
    r"(?:usage|weekly|session|plan|5-?\s?hour)\s+limit"
    r"|limit\b.{0,40}?\bresets?\s+at",
    re.IGNORECASE | re.DOTALL,
)
# A machine-readable reset instant, IF the (as-yet-unconfirmed) signal carries
# one in ISO-8601 UTC form. Best-effort only; absence -> null horizon.
_LIMIT_RESET_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def _stderr_is_limit_shaped(text: str) -> bool:
    """True iff a turn's stderr tail matches the conservative usage-limit
    pattern (fallback detection -- DEFERRED-TO-KERNEL-PROBE). Empty/None -> not
    limit-shaped (a silent crash is NOT a park)."""
    return bool(text) and bool(_LIMIT_STDERR_RE.search(text))


def _parse_limit_signal(text: str):
    """Best-effort (reset_at, kind) from a limit-shaped stderr tail. reset_at is
    an ISO-8601 UTC string if one is present, else None (park with an unknown
    horizon -- never auto-resumed blind); kind is 'weekly' | 'session_5h' | None
    by keyword. Parser is pinned to the observed signal by the kernel probe
    later; today it stays conservative and returns None where uncertain."""
    reset_at = None
    m = _LIMIT_RESET_RE.search(text or "")
    if m:
        reset_at = m.group(0)
    kind = None
    low = (text or "").lower()
    if "week" in low:
        kind = "weekly"
    elif "5-hour" in low or "5 hour" in low or "session" in low:
        kind = "session_5h"
    return reset_at, kind


def _read_stderr_tail(name: str, limit: int = 4000) -> str:
    """Read the tail of a worker's stderr log (logs/<name>.err) best-effort --
    the classifier's only window onto a limit-shaped turn end. Missing/unreadable
    -> empty string (treated as not limit-shaped)."""
    err = logs_dir() / f"{name}.err"
    try:
        data = err.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-limit:]


def _limit_reset_passed(record: dict) -> bool:
    """True iff a `limited` record's limit_reset_at is set AND now >= it. A null
    horizon returns False (never auto-eligible -- needs an operator-set reset or
    --force-now)."""
    reset = record.get("limit_reset_at")
    if not reset:
        return False
    try:
        return datetime.now(timezone.utc) >= _parse_iso(reset)
    except (ValueError, TypeError):
        return False


def _append_abnormal_turn_note(name: str) -> None:
    """Append a one-line abnormal-turn-end landmark to the worker's journal
    (phase1 kernel 4). Best-effort: a journal we cannot write must never break
    a status recompute, so any OSError is swallowed."""
    try:
        journals_dir().mkdir(parents=True, exist_ok=True)
        journal = journals_dir() / f"{name}.md"
        with open(journal, "a", encoding="utf-8") as f:
            f.write(f"\nturn ended abnormally at {now_iso()}\n")
    except OSError:
        pass


def recompute_worker(name: str, record: dict, get_process_info=None, sleep=time.sleep) -> dict:
    """Return an updated copy of `record` with status/cost_usd/last_activity
    refreshed from live PID + log-tail state. Never mutates other fields
    (turns, task, mode, ...); never clobbers an "attached" status
    (recompute_status's own guard, F7).

    cost_usd = cost_baseline + the SUM of every result event's cost in the
    current log file (Task 5 fix wave, Finding 4 + SMOKE-B). cost_baseline
    carries the prior-sessions total across a respawn's fresh log (Finding
    4); summing every result event in the current file (rather than taking
    only the last one) also carries the running total across multiple
    `send`-resumed turns within one session, since a turn's own result
    event reports only that turn's own per-invocation cost, not a session-
    cumulative figure (SMOKE-B). cost_baseline defaults to 0.0 for records
    that predate this field."""
    log_path = logs_dir() / f"{name}.jsonl"
    updated = dict(record)
    updated["status"] = recompute_status(
        record.get("turn_pid"), record.get("turn_pid_ctime"), log_path,
        current_status=record.get("status"), get_process_info=get_process_info,
        last_activity_iso=record.get("last_activity"), sleep=sleep,
    )
    # Phase1 kernel 4: a turn that WAS "working" with a real (non-None)
    # turn_pid and just classified "dead" is a crashed turn (stale/gone PID +
    # no trailing result). Drop an abnormal-turn-end landmark in the worker's
    # journal so a respawn's carried-forward context knows the last turn did
    # not finish cleanly. Guarded on the working(real pid)->dead transition,
    # so it fires ONCE per crash: once persisted "dead" (which is sticky),
    # the input status is no longer "working" and this is skipped.
    if (record.get("status") == "working" and record.get("turn_pid") is not None
            and updated["status"] == "dead"):
        # UL1 (item 11 / F31): a no-`result` crash-dead turn is NOT
        # unconditionally a crash -- it may be a Claude PLAN usage-limit wall.
        # Test the (conservative, DEFERRED-TO-KERNEL-PROBE) stderr signal FIRST:
        # limit-shaped -> park `limited` (recording the reset horizon if
        # parseable, surfacing for operator confirmation), NOT crash-dead, and
        # DON'T drop the abnormal-turn note (a park is not a crash). A
        # non-limit-shaped errored turn falls through to the ordinary crash-dead
        # landmark -- the fallback never swallows a genuine crash as a park.
        stderr_tail = _read_stderr_tail(name)
        if _stderr_is_limit_shaped(stderr_tail):
            reset_at, kind = _parse_limit_signal(stderr_tail)
            updated["status"] = "limited"
            updated["limit_reset_at"] = reset_at
            updated["limit_kind"] = kind
            append_event("limited_suspected", name, limit_reset_at=reset_at, limit_kind=kind)
        else:
            _append_abnormal_turn_note(name)
    cost_sum = _sum_result_costs(log_path)
    if cost_sum is not None:
        updated["cost_usd"] = _registry_cost(record.get("cost_baseline", 0.0)) + cost_sum
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
    # Kernel 10 (F12=M24): surface the fleet-side token-ceiling refusal in
    # `fleet status`, mirroring how over_budget shows up as its own status.
    if record["status"] == "over_ceiling":
        flags.append("over-ceiling")
    # UL1 (item 11 / F31): surface a parked worker's reset horizon and, once
    # the horizon has passed, its resume-eligibility -- a read-only FLAG only,
    # never an auto-launch (invariant 1 daemonless: status derives views, it
    # does not start turns; the operator runs `fleet resume-limited`).
    if record["status"] == "limited":
        reset = record.get("limit_reset_at")
        flags.append(f"limited (resets {reset})" if reset else "limited (reset unknown)")
        if _limit_reset_passed(record):
            flags.append("resume-eligible")
    return flags


# ---------------------------------------------------------------------------
# Phase 1.6 terminal surface (docs/specs/terminal-surface.md): the single
# read-only derivation every view consumes -- statusline, `status --json
# --stale-ok`, the SessionStart hook, and (later) watchtower / web UI.
#
# D1: no fleet_lock, no PLATFORM.get_process_info, no write. This runs on a
# statusline hot path that refires after every assistant message.
# D4: it must NOT call load_registry() -- that quarantines a corrupt registry
# (a write, and a 10s-refresh loop would shred operator evidence). Views
# report corruption; the next real fleet command quarantines it.
# ---------------------------------------------------------------------------

def _read_registry_readonly() -> tuple:
    """(ok, reason, data). Never writes, never quarantines, never raises.

    reason is None when ok, else "not_initialized" | "unreadable"."""
    path = registry_path()
    if not path.exists():
        return (False, "not_initialized", {"workers": {}})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return (False, "unreadable", {"workers": {}})
    if not isinstance(data, dict):
        return (False, "unreadable", {"workers": {}})
    workers = data.get("workers", {})
    if not isinstance(workers, dict) or not all(isinstance(v, dict) for v in workers.values()):
        return (False, "unreadable", {"workers": {}})
    return (True, None, {"workers": workers})


def status_snapshot(now=None) -> dict:
    """Read-only fleet snapshot. See the module comment above for why this
    exists alongside cmd_status rather than reusing it."""
    if now is None:
        now = datetime.now(timezone.utc)
    ok, reason, data = _read_registry_readonly()
    snap = {
        "ok": ok,
        "reason": reason,
        "generated_at": now_iso(),
        "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}},
        "workers": [],
    }
    if not ok:
        return snap

    rows = []
    by_status: dict = {}
    total_mail = 0
    total_cost = 0.0
    for name in sorted(data["workers"]):
        rec = data["workers"][name]
        sid = rec.get("session_id") or ""
        mail = _pending_mail_count(sid) if sid else 0
        cost = _registry_cost(rec.get("cost_usd"))
        try:
            stale = (now - _parse_iso(rec["last_activity"])).total_seconds()
        except (ValueError, TypeError, KeyError):
            stale = None
        status = rec.get("status", "?")
        by_status[status] = by_status.get(status, 0) + 1
        total_mail += mail
        total_cost += cost
        rows.append({
            "name": name,
            "status": status,
            "turns": rec.get("turns", 0),
            "cost_usd": cost,
            "mail": mail,
            "stale_seconds": stale,
            "limit_reset_at": rec.get("limit_reset_at"),
            "limit_kind": rec.get("limit_kind"),
            "resume_eligible": status == "limited" and _limit_reset_passed(rec),
            "attached_since": rec.get("attached_since"),
        })

    snap["workers"] = rows
    snap["totals"] = {
        "workers": len(rows),
        "mail": total_mail,
        "cost_usd": round(total_cost, 6),
        "by_status": by_status,
    }
    return snap


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


class LogRotationError(FleetCliError):
    """B2 (rotation retry): _rotate_worker_log exhausted its PermissionError
    retries -- a follower or just-killed claude still holds the log handle
    (Windows sharing violation). cmd_respawn catches this to CLEAN-FAIL the
    respawn: _unrotate any partial rename, restore the pre-respawn registry
    snapshot, and raise -- NO new turn, NO sid-swap (invariant 7). A
    FleetCliError subclass so an unexpected escape still surfaces as a clean
    one-line CLI error, not a traceback."""


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


# Post-testing wave, item 1b (stress-report Finding 1, CRITICAL): how many
# times / how long cmd_spawn, cmd_send's idle-resume path, and cmd_respawn
# retry their post-launch commit lock (the one that stamps the real
# turn_pid into the registry) before giving up. Deliberately several times
# the ordinary LOCK_TIMEOUT_SECONDS (5.0s): by the time this lock is
# reached, launch_turn() has ALREADY succeeded -- a real, billable, running
# `claude` process exists and its pid is known -- so losing this race
# forever would strand it as a permanent zombie registry record (status=
# "working"/turn_pid=None, which every recovery lever historically refused
# to touch; item 1c's LAUNCH_CLAIM_MAX_AGE_SECONDS now bounds that too, but
# retrying hard here is the first, much faster line of defense). Total
# backoff across all attempts is ~30s (each attempt itself may also spend
# up to LOCK_TIMEOUT_SECONDS acquiring, so worst case is noticeably more).
LAUNCH_COMMIT_MAX_ATTEMPTS = 6
LAUNCH_COMMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 8.0, 7.0)


def _commit_launched_turn(commit_fn, sleep=time.sleep) -> bool:
    """Run `commit_fn()` -- a zero-argument callable that itself acquires
    `fleet_lock()` and performs a post-launch registry commit (stamping
    turn_pid/turn_pid_ctime/turns/last_activity, matching cmd_spawn/
    cmd_send/cmd_respawn's own shape) -- retrying on FleetLockTimeout with
    backoff (LAUNCH_COMMIT_BACKOFF_SECONDS) up to LAUNCH_COMMIT_MAX_ATTEMPTS
    times.

    Returns True once `commit_fn()` completes without raising
    FleetLockTimeout. Returns False if every attempt timed out -- the
    caller (cmd_spawn/cmd_send/cmd_respawn) MUST NOT abandon the
    already-launched turn on a False return: it must still report the
    launch as successful (raising here would tempt an operator into
    retrying the same `fleet` subcommand, which would launch a SECOND live
    turn on top of the one already running) and instead call
    `_report_stranded_turn` for a loud, actionable warning plus a
    best-effort event."""
    for attempt in range(LAUNCH_COMMIT_MAX_ATTEMPTS):
        try:
            commit_fn()
            return True
        except FleetLockTimeout:
            if attempt == LAUNCH_COMMIT_MAX_ATTEMPTS - 1:
                return False
            sleep(LAUNCH_COMMIT_BACKOFF_SECONDS[attempt])
    return False


def _report_stranded_turn(name: str, sid: str, info: dict) -> None:
    """Post-launch commit lock exhausted every retry in
    `_commit_launched_turn`: a real, already-running turn's pid could not
    be stamped into the registry. Never fail silently -- print a loud,
    actionable stderr message (status/kill/attach/wait are all blind to
    this turn until the record is repaired) and best-effort append an
    event for later forensics. Deliberately does not raise: the calling
    `fleet` subcommand still completes and reports success, since the turn
    genuinely IS running -- raising here would read as "the launch
    failed" and could tempt an operator into retrying, launching a SECOND
    live turn onto the same session."""
    print(
        f"fleet: CRITICAL: {name}: turn launched (pid={info.get('turn_pid')}, "
        f"session {sid}) but the registry commit failed after "
        f"{LAUNCH_COMMIT_MAX_ATTEMPTS} lock-acquisition attempts -- the "
        "record is stuck at status=working/turn_pid=null (the F1 "
        "launch-in-flight state). It will auto-demote to dead after "
        f"LAUNCH_CLAIM_MAX_AGE_SECONDS ({LAUNCH_CLAIM_MAX_AGE_SECONDS:.0f}s) "
        f"of inactivity; recover with `fleet respawn {name} --force` once "
        "that happens, or hand-edit state/fleet.json now to set "
        f"turn_pid={info.get('turn_pid')} directly.",
        file=sys.stderr,
    )
    try:
        append_event("turn_commit_failed", name, session_id=sid, turn_pid=info.get("turn_pid"))
    except OSError:
        pass


def statusline_chain_path() -> Path:
    """state/statusline-chain.json -- delegate statusline commands fleet runs
    above its own row. Machine-local (gitignored), like every other state file."""
    return state_dir() / "statusline-chain.json"


def _capture_statusline_delegate(command: str) -> None:
    """Record a foreign statusline command so fleet's statusline runs it and
    prints its rows above fleet's own (Phase 1.6, --chain).

    Claude Code allows exactly ONE statusLine command, so composing is the only
    way an operator keeps their existing statusline AND gains fleet's."""
    path = statusline_chain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"delegates": [{"command": command, "captured_at": now_iso()}]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Destructive-command guard (§5.1).
#
# On 2026-07-09 a `claude -p "/fleet:status"` probe run -- granted `Bash(fleet:*)`
# by a read-only slash command -- decided four dead workers were untidy, killed
# a fifth that was WORKING, and swept all five journals. It was inside its
# permissions the whole time. Narrowing the grant fixed that command; this
# guard fixes the CLI, so the next over-helpful agent (or a bypassPermissions
# session, which sees no prompt at all) cannot destroy a worker it never owned
# without saying so out loud.
#
# Rules:
#   * A worker you spawned is yours: retire it freely.
#   * A worker spawned by ANOTHER session, or whose owner is unknown, is
#     FOREIGN. Destroying it needs --yes, or an interactive human typing "y".
#   * Non-interactive + foreign + no --yes = refuse, exit 1. Agents run
#     non-interactive, so this is the branch that actually bites.
#   * `interrupt` is exempt: it kills a turn, not a worker, and the transcript
#     survives. Only kill / clean / respawn destroy or rotate state.
# ---------------------------------------------------------------------------

class DestructiveActionRefused(FleetCliError):
    """A destructive action against a foreign worker was not acknowledged."""


def _worker_is_foreign(record: dict, caller: str | None) -> bool:
    """True when this session did not spawn the worker.

    An UNKNOWN owner (`spawned_by` absent -- every record written before this
    field existed) counts as foreign: the guard fails toward asking."""
    owner = record.get("spawned_by")
    if not owner:
        return True
    return owner != caller


def _describe_owner(record: dict) -> str:
    owner = record.get("spawned_by")
    if not owner:
        return "unknown owner (spawned before provenance was recorded, or by a human shell)"
    return f"session {owner[:8]}"


def _confirm_destructive(action: str, names: list, records: dict, assume_yes: bool) -> None:
    """Raise DestructiveActionRefused unless a foreign-worker action is
    acknowledged with --yes. Silent no-op when every named worker belongs to
    this caller.

    The guard applies to CLAUDE SESSIONS only. A human at a plain shell has no
    CLAUDE_CODE_SESSION_ID; fleet has always been a human-driven CLI and
    interposing prompts there would break every existing script for no safety
    gain -- a human typing `fleet clean` meant to type it. The threat model is
    an over-helpful agent, especially one under `bypassPermissions` where no
    permission prompt is ever shown.

    There is deliberately NO interactive prompt. An agent's Bash tool has no
    stdin to answer one with (it gets an EOFError), and `isatty()` cannot tell
    the two apart on Windows anyway: Git Bash's `/dev/null` is `NUL`, a
    CHARACTER DEVICE, so `sys.stdin.isatty()` returns True under
    `fleet kill x < /dev/null`. An agent must pass --yes; there is nothing to
    prompt."""
    caller = current_caller_session()
    if caller is None:
        return
    foreign = [n for n in names if _worker_is_foreign(records.get(n, {}), caller)]
    if not foreign or assume_yes:
        return

    detail = ", ".join(f"{n} ({_describe_owner(records.get(n, {}))})" for n in foreign)
    raise DestructiveActionRefused(
        f"refusing to {action} {len(foreign)} worker(s) this session did not spawn: {detail}. "
        f"Re-run with --yes to confirm. (A worker you spawned needs no confirmation.)"
    )


def _install_statusline(force: bool = False, chain: bool = False) -> None:
    """Merge fleet's statusLine into ~/.claude/settings.json (Phase 1.6 D6).

    A Claude Code plugin cannot ship a statusLine -- plugin settings.json
    accepts only `agent` and `subagentStatusLine` -- so this explicit, opt-in
    step is the only way to install one. It backs up first, merges ONLY the
    statusLine key, and refuses a foreign statusline (an operator running
    ccusage or caveman must not lose it silently).

    `chain=True` COMPOSES instead of refusing: the incumbent command is
    captured into state/statusline-chain.json and fleet's statusline runs it,
    printing its rows above fleet's own. `force=True` overwrites outright."""
    path = user_settings_path()
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise FleetCliError(
                f"refusing to touch an unreadable {path}: {exc} -- fix or move it, then re-run"
            ) from exc
        if not isinstance(settings, dict):
            raise FleetCliError(f"refusing to touch {path}: not a JSON object")

    script = statusline_script_path().resolve().as_posix()
    existing = settings.get("statusLine")
    incumbent = str(existing.get("command", "")) if isinstance(existing, dict) else ""
    # A fleet-owned incumbent is a re-install, never a delegate: chaining it
    # would make fleet's statusline invoke itself, once per refresh, forever.
    foreign = bool(incumbent) and "fleet_statusline.py" not in incumbent

    if foreign:
        if chain:
            _capture_statusline_delegate(incumbent)
            print(f"  chained:     {incumbent}")
        elif not force:
            raise FleetCliError(
                f"statusLine already set to {existing.get('command')!r} in {path} -- "
                "re-run with --chain to keep it and show fleet's row beneath it, "
                "or --force to overwrite it"
            )

    if path.exists():
        backup = path.with_name(f"settings.json.bak.{now_iso().replace(':', '').replace('-', '')}")
        shutil.copy2(path, backup)
        print(f"  backup:      {backup}")

    settings["statusLine"] = {
        "type": "command",
        # Forward slashes: this command string is executed through a shell.
        "command": f"{Path(sys.executable).resolve().as_posix()} {script}",
        "refreshInterval": 10,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"fleet init: installed statusLine into {path}")
    print("  restart Claude Code to see it")


def cmd_home(args) -> int:
    """`fleet home`: print the resolved FLEET_HOME.

    The skill, the slash commands and any collaborator script need the fleet
    root without hardcoding one developer's absolute path (SPEC §14)."""
    print(Path(FLEET_HOME).resolve().as_posix())
    return 0


def _write_text_tolerating_console_encoding(text: str) -> None:
    """Write text to stdout without dying on a cp1252 console.

    A Windows console defaults to cp1252 and cannot encode the arrows, dashes
    and box glyphs the knowledge base is full of; `print()` then raises
    UnicodeEncodeError mid-stream. Prefer real UTF-8, and degrade to
    backslash-escapes rather than failing -- the operator gets slightly ugly
    text instead of a truncated file and a traceback."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError, ValueError):
        pass
    try:
        sys.stdout.write(text)
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))


def cmd_knowledge(args) -> int:
    """`fleet knowledge`: print knowledge/INDEX.md.

    Exists so no surface has to compose a FLEET_HOME path in shell. A slash
    command's inline `!`cmd`` may run under PowerShell, where bash parameter
    expansion (`${FLEET_HOME:-$(cat ...)}`) is meaningless -- the /fleet
    command shipped exactly that and printed garbage."""
    path = knowledge_dir() / "INDEX.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        print(f"(no knowledge index at {path} -- run `fleet init`)")
        return 0
    _write_text_tolerating_console_encoding(text)
    return 0


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

    _write_fleet_home_marker()

    print(f"fleet init: wrote {instance_path}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    print(f"  fleet home:  {Path(FLEET_HOME).resolve().as_posix()}")
    print(f"  marker:      {fleet_home_marker_path()}")

    if getattr(args, "statusline", False):
        _install_statusline(force=getattr(args, "force", False),
                            chain=getattr(args, "chain", False))
    return 0


def cmd_spawn(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which,
              sleep=time.sleep) -> int:
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

    Post-testing wave, item 1b (stress-report Finding 1, CRITICAL): the
    post-launch commit lock below (the one that stamps info["turn_pid"])
    runs through `_commit_launched_turn`'s retry-with-backoff instead of a
    single bare `with fleet_lock():` -- by this point launch_turn() has
    ALREADY started a real, live `claude` process, so losing the ordinary
    5s lock race here must not mean losing the ability to ever track it.
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
        record = new_worker_record(
            sid, cwd, task, args.mode, model=args.model,
            max_budget_usd=args.max_budget_usd, setting_sources=args.setting_sources,
            token_ceiling=args.token_ceiling,
            spawned_by=current_caller_session())
        data["workers"][args.name] = record
        save_registry(data)
        append_event("spawned", args.name, session_id=sid, cwd=str(cwd), mode=args.mode)

    # Kernel 10 (fleet half): write the sid-keyed ceiling file BEFORE the
    # launch so the Stop hook sees it from turn 1 (no-op when unconfigured).
    _write_ceiling_file(sid, record.get("token_ceiling"))

    prompt, claim = compose_prompt(args.name, cwd, task, sid)
    try:
        info = launch_turn(
            args.name, cwd, sid, prompt, args.mode, first=True,
            # F13/M5: source the launch flags from the PERSISTED record, not
            # args, so spawn and every later launch path share one origin.
            model=record.get("model"), max_budget_usd=record.get("max_budget_usd"),
            setting_sources=record.get("setting_sources"),
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

    def _commit():
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(args.name)
            if rec is not None:
                # F-RACE: re-assert "working" here -- a concurrent fleet
                # status/wait landing in the gap between this lock and the
                # create-lock above could have recomputed and persisted
                # "dead" (turn_pid was still None then). The turn has
                # launched by definition at this point, so this
                # authoritatively repairs that spurious transition.
                rec["status"] = "working"
                rec["turn_pid"] = info["turn_pid"]
                rec["turn_pid_ctime"] = info["turn_pid_ctime"]
                rec["turns"] = 1
                rec["last_activity"] = now_iso()
                save_registry(data)
            append_event("turn_started", args.name, session_id=sid, turn_pid=info["turn_pid"])

    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_turn(args.name, sid, info)

    # Phase1 kernel 5: echo the effective model/config at launch so a costly
    # model (or an inherited CLAUDE_CODE_SUBAGENT_MODEL) is visible up front,
    # not discovered on the bill.
    model_line = f"model: {args.model or '(claude default)'}"
    subagent_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if subagent_model:
        model_line += f"; CLAUDE_CODE_SUBAGENT_MODEL={subagent_model}"
    print(model_line)

    print(f"{args.name} {sid} {info['log_path']}")
    return 0


_HOOK_ERROR_TAIL = 5  # doctor/status: how many trailing hook-error lines to show


def _hook_error_lines() -> list:
    """Non-blank lines currently in state/hook-errors.log (phase1 kernel 1),
    or [] if the log is absent/unreadable. Read-only -- fleet.py never writes
    this file (the hooks do)."""
    path = hook_errors_path()
    try:
        if not path.exists():
            return []
        return [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except OSError:
        return []


def _hook_error_count() -> int:
    return len(_hook_error_lines())


def cmd_status(args, get_process_info=None, sleep=time.sleep) -> int:
    """`fleet status [name]` (SPEC §5 status row): recompute liveness/cost
    for the named worker (or all workers), persist any transitions, print a
    compact table with anomaly flags.

    Post-testing wave, item 1a (stress-report Finding 1, CRITICAL): this
    used to recompute (and persist) EVERY worker's liveness inside one
    `with fleet_lock():` block. recompute_worker's probe (get_process_info,
    which defaults to a real PowerShell `Get-Process` subprocess call per
    currently-"working" pid) costs on the order of ~0.3s each -- measured
    directly, a bare `fleet status` over 8 simultaneously-"working" workers
    held the lock for ~2.4s. Several such calls queued back-to-back
    comfortably exceed LOCK_TIMEOUT_SECONDS (5.0s) for anyone else waiting
    on the lock, including a spawn/send/respawn sitting at its own
    post-launch commit lock (_commit_launched_turn) after a real, live
    `claude` turn has ALREADY been started -- which is exactly what
    stranded those turns as permanent zombie registry records under real
    concurrent load.

    Restructured to the same snapshot -> probe (no lock held) -> re-acquire
    -> conditional-commit shape already used by `_interrupt_worker` (F4)
    and `cmd_clean` (review wave 5b) for the identical reason: snapshot the
    named records under the lock, release it, run every recompute_worker
    probe with NO lock held at all, then re-acquire once to merge verdicts
    -- but only for records that still match their pre-probe snapshot
    exactly (a concurrent command that mutated a record while the lock was
    released is left alone, its own write respected, rather than being
    clobbered by a verdict computed against now-stale data)."""
    # Phase 1.6 (D1/D2): --stale-ok is the probe-free, lock-free, write-free
    # read path every view uses. Returns last-COMMITTED status plus
    # stale_seconds; it never asserts liveness it did not probe for.
    if getattr(args, "stale_ok", False):
        snap = status_snapshot()
        if getattr(args, "json", False):
            print(json.dumps(snap, indent=2))
        else:
            _print_snapshot_table(snap, args.name)
        return 0

    with fleet_lock():
        data = load_registry()
        names = [args.name] if args.name else sorted(data["workers"])
        for n in names:
            if n not in data["workers"]:
                raise FleetCliError(f"unknown worker: {n!r}")
        before = {n: data["workers"][n] for n in names}

    # Probe every named worker's liveness with NO lock held (see docstring
    # above) -- this is the (potentially several-seconds-total) expensive
    # part.
    after = {n: recompute_worker(n, before[n], get_process_info=get_process_info, sleep=sleep) for n in names}

    display = {}
    with fleet_lock():
        data = load_registry()
        changed = False
        for n in names:
            current = data["workers"].get(n)
            if current is None or current != before[n]:
                # Removed or mutated by a concurrent command while our lock
                # was released for probing -- spare it, don't overwrite
                # with a verdict computed against now-stale pre-probe data
                # (mirrors cmd_clean's respawned-meanwhile guard). Show
                # whatever is actually there now for the printed table
                # (falling back to the stale snapshot only if it vanished
                # entirely).
                display[n] = current if current is not None else before[n]
                continue
            if after[n] != current:
                data["workers"][n] = after[n]
                changed = True
                if after[n]["status"] != current["status"]:
                    append_event("status_changed", n, old=current["status"], new=after[n]["status"])
            display[n] = data["workers"][n]
        if changed:
            save_registry(data)

    if getattr(args, "json", False):
        # The authoritative path has already persisted its verdicts above, so
        # re-deriving the snapshot from disk yields exactly the recomputed state.
        print(json.dumps(status_snapshot(), indent=2))
    else:
        _print_status_table({"workers": display}, names)
    # Phase1 kernel 1: surface a TOTAL count of swallowed hook errors when
    # nonzero so a silently-failing hook is visible at a glance (`fleet
    # doctor` shows the tail).
    n_hook_errors = _hook_error_count()
    if n_hook_errors:
        print(f"hook-errors: {n_hook_errors} swallowed hook error(s) logged (run `fleet doctor` for the tail)")
    return 0


def _print_snapshot_table(snap: dict, name=None) -> None:
    """Human table for `fleet status --stale-ok` (D2): last-committed status
    with an age column, never a probed one."""
    if not snap["ok"]:
        print("fleet: not initialized" if snap["reason"] == "not_initialized"
              else "fleet: registry unreadable")
        return
    rows = [w for w in snap["workers"] if name is None or w["name"] == name]
    if name is not None and not rows:
        raise FleetCliError(f"unknown worker: {name!r}")
    print(f"{'NAME':<20} {'STATUS':<12}{'TURNS':>6}{'COST':>9}{'AGE':>9}{'MAIL':>6}  FLAGS")
    for w in rows:
        age = "?" if w["stale_seconds"] is None else f"{w['stale_seconds'] / 60:.0f}m"
        flags = []
        if w["status"] == "idle" and w["mail"]:
            flags.append("idle+mail")
        if w["resume_eligible"]:
            flags.append("resume-eligible")
        # A name at or past the column width must never swallow the separator.
        print(
            f"{w['name']:<20} {w['status']:<12}{w['turns']:>6}{w['cost_usd']:>9.2f}"
            f"{age:>9}{w['mail']:>6}  {','.join(flags) or '-'}"
        )
    print("(stale-ok: last-committed state, not probed)")


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


_TOKEN_KEY_ABBREV = (
    ("input_tokens", "in"),
    ("output_tokens", "out"),
    ("cache_creation_input_tokens", "cache_w"),
    ("cache_read_input_tokens", "cache_r"),
)


def _format_tokens(tokens: dict) -> str:
    """Compact "in=X out=Y cache_r=Z" rendering of a result event's usage
    dict for `fleet peek` (spec-audit gap 5: peek shows tokens alongside
    cost, SPEC §5 peek row -- _digest_event already captures "tokens" from
    the raw "usage" field). Falls back to a truncated raw dump for an
    unrecognized/empty shape rather than silently showing nothing."""
    if not tokens:
        return "-"
    parts = [f"{short}={tokens[key]}" for key, short in _TOKEN_KEY_ABBREV if key in tokens]
    if not parts:
        return _truncate(json.dumps(tokens, default=str), 60)
    return " ".join(parts)


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
            tok_s = _format_tokens(e.get("tokens") or {})
            print(f"[result] {cost_s} tokens:{tok_s} {e['text']}")
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
                last_activity_iso=rec.get("last_activity"), sleep=sleep,
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
    one-line result summary per finished worker. Nonzero exit on timeout.

    Post-testing wave, item 4 (live-report scenario 2): `--any` returning
    with `pending` non-empty is the NORMAL, successful outcome of that
    mode (at least one worker finished, the rest are still going) -- it is
    not a timeout, and live testing found the CLI mislabeling it as one
    ("timed out (still working)", exit code 1) even when the wait loop
    returned instantly because `--any` was satisfied, not because the
    deadline elapsed. Distinguish the two: `mode == "any"` with at least
    one `finished` worker is success (exit 0, remaining pending workers
    printed as "still working"); everything else with `pending` non-empty
    (mode=="all" left workers unfinished, or mode=="any" found nothing at
    all before the deadline) is a genuine timeout (exit 1, "timed out
    (still working)")."""
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
                updated = recompute_worker(n, rec, get_process_info=get_process_info, sleep=sleep)
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
        if mode == "any" and finished:
            # --any's own success condition was met (at least one worker
            # finished) -- the loop simply exited before every OTHER
            # worker did too, which is expected, not a timeout.
            for n in pending:
                print(f"{n}: still working")
            return 0
        for n in pending:
            print(f"{n}: timed out (still working)")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI: steering + hybrid commands (SPEC §5 send/interrupt/attach/release
# rows, §9 hybrid interaction model, §14 platform adapter)
# ---------------------------------------------------------------------------

def cmd_send(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which,
             sleep=time.sleep) -> int:
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
        after = recompute_worker(args.name, before, get_process_info=get_process_info, sleep=sleep)
        status = after["status"]
        if status != before["status"]:
            append_event("status_changed", args.name, old=before["status"], new=after["status"])
        if status == "idle":
            # F13/M5 cumulative-cost check: the CLI --max-budget-usd is a
            # PER-TURN cap, so a worker steered with N sends could run turns
            # 2..N and blow past its lifetime budget one turn at a time. This
            # is the worker-lifetime enforcement SPEC §11 documents: before
            # claiming a RESUME launch, compare the persisted cumulative
            # cost_usd against the persisted (immutable) max_budget_usd; if
            # already exceeded, REFUSE the resume and FLAG the worker
            # "over_budget" (a sticky status, see recompute_status) instead
            # of launching an over-cap turn.
            mb = after.get("max_budget_usd")
            spent = _registry_cost(after.get("cost_usd", 0.0))
            if mb is not None and spent > mb:
                after["status"] = "over_budget"
                data["workers"][args.name] = after
                save_registry(data)
                append_event("budget_exceeded", args.name, cost_usd=spent, max_budget_usd=mb)
                raise FleetCliError(
                    f"{args.name}: cumulative cost ${spent:.4f} exceeds max_budget_usd "
                    f"${mb} -- refusing resume (worker flagged over_budget); respawn with a "
                    "higher --max-budget-usd or retire it"
                )
            # Kernel 10 (F12=M24) cumulative-TOKEN check: the token_ceiling is
            # the hard cap the Stop hook only ever ALLOWS against (invariant
            # 2 -- the hook never blocks). Enforcement lives HERE: before a
            # RESUME launch, sum the session's tokens from the log's result
            # events and refuse if already over, flagging the worker
            # over_ceiling (sticky, see recompute_status). Mirrors the
            # over_budget refusal directly above.
            tc = after.get("token_ceiling")
            if tc is not None:
                used = _sum_result_tokens(logs_dir() / f"{args.name}.jsonl") or 0
                # FIX-3 (F-2): >= not > -- the Stop hook (stop_mailbox.py) allows
                # stop at tokens >= ceiling; the fleet-side refusal must use the
                # SAME boundary so tokens == ceiling is treated as over by both
                # halves (at ==, > would let fleet launch a turn the hook would
                # already allow-stop on -- a cross-half disagreement).
                if used >= tc:
                    after["status"] = "over_ceiling"
                    data["workers"][args.name] = after
                    save_registry(data)
                    append_event("ceiling_exceeded", args.name, tokens=used, token_ceiling=tc)
                    raise FleetCliError(
                        f"{args.name}: cumulative tokens {used} reached token_ceiling "
                        f"{tc} -- refusing resume (worker flagged over_ceiling); respawn "
                        "with a higher --token-ceiling or retire it"
                    )
            # F1 pre-claim: atomic decide+claim, same lock, before release.
            after["status"] = "working"
            after["turn_pid"] = None
            # Post-testing wave, item 1c: stamp last_activity to NOW at the
            # moment of the claim (mirroring new_worker_record's
            # created=now_iso() stamp that cmd_spawn/cmd_respawn's own
            # pre-claims get for free) -- recompute_worker's own
            # last_activity refresh just above reflects the log's mtime
            # from BEFORE this claim (e.g. the prior turn's completion,
            # possibly long ago), which would otherwise make
            # recompute_status's new LAUNCH_CLAIM_MAX_AGE_SECONDS guard
            # see this brand-new claim as already stale and wrongly demote
            # a genuinely in-flight launch straight to "dead".
            after["last_activity"] = now_iso()
        data["workers"][args.name] = after
        save_registry(data)
        sid = after["session_id"]
        # F9 (item 8, review M3): for a working/attached worker the mailbox
        # append MUST happen UNDER this same fleet_lock -- not after release.
        # sid was read under the lock, so appending here (still holding it)
        # makes send atomic w.r.t. respawn's drain+sid-swap: a concurrent
        # respawn cannot swap the sid out and drain the old mailbox in the
        # window between reading sid and appending, so no message ever lands
        # in a pre-swap mailbox after the swap (SPEC invariants 3, 7). The
        # mail_sent event is a single-writer audit record (invariant 6), not a
        # DLQ.
        if status in ("working", "attached"):
            append_mailbox(sid, message)
            append_event("mail_sent", args.name, sid=sid, status=status)

    if status == "working":
        print(f"{args.name}: turn running -- message queued to mailbox")
        return 0

    if status == "attached":
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
    # message is never carried both ways. The append is outside the lock here
    # (unlike working/attached above), but that is safe: this branch already
    # pre-claimed status="working"/turn_pid=None under the lock, and a
    # concurrent respawn refuses on a launch-in-flight claim -- so the sid
    # cannot be swapped out from under this append.
    append_mailbox(sid, message)
    append_event("mail_sent", args.name, sid=sid, status="idle")
    prompt, claim = compose_prompt(args.name, after["cwd"], "", sid)
    try:
        info = launch_turn(
            args.name, after["cwd"], sid, prompt, after["mode"], first=False,
            # F13/M5: re-emit the persisted cap + setting-sources on the
            # RESUME launch -- a missing re-pass is the exact failure this
            # closes (turns 2..N ran uncapped, foreign-hook remedy gone).
            model=after.get("model"), max_budget_usd=after.get("max_budget_usd"),
            setting_sources=after.get("setting_sources"),
            popen=popen, get_process_info=get_process_info, which=which,
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

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is not None:
                # Re-assert "working" (F-RACE, matches cmd_spawn's
                # second-lock re-assert): a concurrent status/wait could
                # have recomputed a spurious transition in the gap between
                # the pre-claim above and this stamp.
                r["status"] = "working"
                r["turn_pid"] = info["turn_pid"]
                r["turn_pid_ctime"] = info["turn_pid_ctime"]
                r["turns"] = r.get("turns", 0) + 1
                r["last_activity"] = now_iso()
                save_registry(data)
            append_event("turn_started", args.name, session_id=sid, turn_pid=info["turn_pid"])

    # Post-testing wave, item 1b (stress-report Finding 1, CRITICAL): retry
    # with backoff instead of a single bare lock acquisition -- see
    # cmd_spawn's identical shape and _commit_launched_turn's docstring.
    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_turn(args.name, sid, info)

    print(f"{args.name}: resumed -- {info['log_path']}")
    return 0


def _resume_one_limited(name: str, popen, get_process_info, which, sleep) -> bool:
    """Relaunch a single `limited` worker through the ordinary
    fleet_lock-guarded launch path -- the SAME pre-claim / one-live-claude /
    universal-drain shape cmd_send's idle-resume uses (invariants 6, 7).

    Returns True iff a resume turn was actually launched, False if the worker
    was skipped because it was no longer `limited` when the claiming lock was
    taken (a concurrent resume sweep / respawn --force / send already moved it).

    Under the lock: RE-READ the record and re-validate it is STILL `limited`
    BEFORE pre-claiming (FIX-1/F-A1 -- mirrors cmd_send's idle re-check: the
    caller's eligibility decision was made against a lock-released snapshot, so
    two racing sweeps both snapshot `limited`; without this re-check the second
    clobbers the first's live pre-claim and starts a second `claude --resume`
    on one sid, orphaning the first turn_pid). A vanished worker raises a clean
    FleetCliError, never a raw KeyError. Then pre-claim status="working"/
    turn_pid=None (recompute's launch-in-flight guard then refuses to demote
    this window). Outside the lock: drain mailbox + journal (compose_prompt with
    journal_path -- F31's "mailbox + journal" resume), launch_turn re-passing
    the spawn-recorded max_budget_usd/setting_sources (else the cap and
    foreign-hook remedy vanish on the resumed turn), then commit the turn_pid.
    On failure, restore the mailbox claim and roll the pre-claim back to
    `limited` (the park), never leaving a ghost claim."""
    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is None:
            raise FleetCliError(f"unknown worker: {name!r}")
        # FIX-1 (F-A1, HIGH): re-validate under the claiming lock. The caller
        # decided eligibility against a snapshot taken under a DIFFERENT lock
        # acquisition; a concurrent actor may have already flipped this worker
        # out of `limited` (another sweep resumed it, a respawn --force reset
        # it, ...). Skip rather than pre-claim a second live turn onto the sid.
        if rec.get("status") != "limited":
            return False
        rec["status"] = "working"
        rec["turn_pid"] = None
        # Stamp a fresh last_activity so recompute_status's stale-pre-claim
        # guard (LAUNCH_CLAIM_MAX_AGE_SECONDS) doesn't reap this in-flight
        # launch against the log's old mtime (mirrors cmd_send's idle-resume).
        rec["last_activity"] = now_iso()
        data["workers"][name] = rec
        save_registry(data)
        sid = rec["session_id"]
        cwd = rec["cwd"]
        mode = rec["mode"]
        model = rec.get("model")
        max_budget_usd = rec.get("max_budget_usd")
        setting_sources = rec.get("setting_sources")

    journal_path = journals_dir() / f"{name}.md"
    prompt, claim = compose_prompt(name, cwd, "", sid, journal_path=journal_path)
    try:
        info = launch_turn(
            name, cwd, sid, prompt, mode, first=False,
            model=model, max_budget_usd=max_budget_usd, setting_sources=setting_sources,
            popen=popen, get_process_info=get_process_info, which=which,
        )
        finalize_mailbox_claim(claim)
    except BaseException:
        # BaseException (not Exception): a Ctrl-C mid-launch must still roll the
        # pre-claim back to `limited`, or the record stays a permanently-guarded
        # ghost claim (working+turn_pid=None) and leaks the drained claim file.
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("status") == "working" and r.get("turn_pid") is None:
                r["status"] = "limited"
                save_registry(data)
        raise

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None:
                r["status"] = "working"
                r["turn_pid"] = info["turn_pid"]
                r["turn_pid_ctime"] = info["turn_pid_ctime"]
                r["turns"] = r.get("turns", 0) + 1
                r["last_activity"] = now_iso()
                save_registry(data)
            append_event("limit_resumed", name, session_id=sid, turn_pid=info["turn_pid"])

    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_turn(name, sid, info)
    return True


def cmd_resume_limited(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which,
                       sleep=time.sleep) -> int:
    """`fleet resume-limited [name] [--force-now]` (SPEC §5 resume-limited row,
    UL1 / F31): the RECOMMENDED explicit resume sweep (UL-OQ3) -- NOT an
    automatic status/launch-time side-effect (invariant 1 daemonless forbids a
    read-view from launching turns; no resident process auto-wakes).

    For each `limited` worker whose limit_reset_at has PASSED, relaunch the
    pending work via _resume_one_limited (the fleet_lock-guarded launch path)
    and flip it limited -> working. SKIPS (leaves `limited`, reports why) any
    worker still before its reset horizon, and any with limit_reset_at = null
    (unknown horizon -- needs operator confirmation) UNLESS --force-now
    overrides for that named worker. Named worker -> that worker only; no name
    -> sweep every eligible worker. status/doctor only FLAG resume-eligibility;
    this command is the one lever that actually relaunches."""
    _require_instance_settings()
    force_now = bool(getattr(args, "force_now", False))

    with fleet_lock():
        data = load_registry()
        if args.name:
            if args.name not in data["workers"]:
                raise FleetCliError(f"unknown worker: {args.name!r}")
            names = [args.name]
        else:
            names = sorted(data["workers"])
        # Snapshot the eligibility inputs under the lock; the actual per-worker
        # launch re-reads the record under its own lock (each _resume_one_limited).
        snapshot = {n: dict(data["workers"][n]) for n in names}

    resumed, skipped = [], []
    for name in names:
        rec = snapshot[name]
        if rec.get("status") != "limited":
            skipped.append((name, "not limited"))
            continue
        reset = rec.get("limit_reset_at")
        if not force_now:
            if reset is None:
                skipped.append((name, "reset horizon unknown -- needs --force-now"))
                continue
            if not _limit_reset_passed(rec):
                skipped.append((name, f"still before reset horizon (resets {reset})"))
                continue
        # FIX-1: _resume_one_limited re-validates `limited` under its own lock
        # and returns False if a concurrent actor already moved the worker --
        # report that as a skip, never as a (non-existent) resume.
        if _resume_one_limited(name, popen, get_process_info, which, sleep):
            resumed.append(name)
        else:
            skipped.append((name, "no longer limited (concurrent change)"))

    for name in resumed:
        print(f"{name}: resumed (limited -> working)")
    for name, why in skipped:
        print(f"{name}: skipped -- {why}")
    if not resumed and not skipped:
        print("no limited workers")
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
               kill_process_tree=None, sleep=time.sleep) -> int:
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
      and NO popen. The post-interrupt re-lock (F1, final-review.md) does
      NOT claim unconditionally: _interrupt_worker's "killed" branch
      commits idle and releases ITS OWN lock first, widening a real window
      (the Get-Process/taskkill call can take hundreds of ms) in which a
      concurrent `fleet send` can acquire the lock, observe idle, and
      pre-claim a brand-new working/turn_pid=None launch -- the re-lock
      checks the record's raw status is still exactly what
      _interrupt_worker's own commit left it in (idle, or dead if a
      concurrent `fleet kill` won the race instead) and refuses loudly
      (no claim) otherwise, rather than stamping "attached" over that
      concurrent claim (or a concurrent attach).
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
        after = recompute_worker(args.name, before, get_process_info=get_process_info, sleep=sleep)
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
        #
        # F1 (final-review.md): this re-lock must not claim unconditionally.
        # _interrupt_worker's "killed" branch commits status="idle" and
        # releases ITS lock -- widening a real window (Get-Process/taskkill
        # takes hundreds of ms) in which a concurrent `fleet send`'s own
        # idle-resume can acquire the lock first, observe idle, and
        # pre-claim status="working"/turn_pid=None for a brand-new launch.
        # Re-check the RAW status (not a fresh recompute -- recomputing
        # here could itself demote a legitimate idle to dead on log
        # evidence unrelated to this race and falsely refuse) is still
        # exactly what _interrupt_worker's own commit left it in (idle, or
        # dead if a concurrent `fleet kill` won instead) before writing
        # "attached" over it -- refuse instead of clobbering a concurrent
        # claim (or a concurrent "attached") with our own.
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is None:
                raise FleetCliError(f"unknown worker: {args.name!r}")
            if r.get("status") not in ("idle", "dead"):
                raise FleetCliError(
                    f"{args.name}: worker was claimed concurrently during --force takeover; retry"
                )
            r["status"] = "attached"
            r["attached_since"] = now_iso()
            data["workers"][args.name] = r
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
# CLI: resilience commands (SPEC §5 respawn/kill/clean/doctor rows, §7,
# §11) -- Task 5 / M4.
# ---------------------------------------------------------------------------

# Task 5 fix wave, Finding 3 (task-5 adversarial review): a single
# get_process_info probe returning "not alive" can be a transient failure
# (get_process_info returns None on ANY exception, including a slow
# PowerShell timeout under serial multi-worker probing) rather than a
# genuinely dead process. `fleet kill`'s not-running verdict and `fleet
# clean`'s dead-worker deletion are both hard-to-reverse (kill permanently
# retires the registry entry; clean deletes the logs/mailbox/journal
# outright), so both re-check after this delay and only finalize when
# BOTH probes agree.
_DEAD_CONFIRM_DELAY_SECONDS = 0.5


_ROTATE_RETRY_ATTEMPTS = 5
_ROTATE_RETRY_DELAY_SECONDS = 0.1


def _rotate_worker_log(name: str, sleep=time.sleep) -> None:
    """Rename logs/<name>.jsonl -> logs/<name>.jsonl.1 (and the matching
    .err -> .err.1), overwriting any existing .1 (SPEC §5 respawn row /
    §11 log-bloat handling). Uses os.replace rather than Path.rename:
    Path.rename raises FileExistsError on Windows when the destination
    already exists (e.g. a worker respawned twice), whereas os.replace
    atomically overwrites it. launch_turn opens logs/<name>.jsonl in
    append-binary mode ("ab") -- without this rotation, a respawned turn's
    stdout would tack onto the previous session's transcript instead of
    starting a fresh log.

    B2 (rotation PermissionError retry): a just-killed claude turn, or a
    concurrent follower (`fleet peek`/`result`/`status` reading the tail, or
    the OS still closing the killed child's stdout handle), can hold an open
    handle on logs/<name>.jsonl for a brief window -- on Windows os.replace
    then raises PermissionError (sharing violation). Retry briefly
    (_ROTATE_RETRY_ATTEMPTS with _ROTATE_RETRY_DELAY_SECONDS backoff); on
    continued failure raise LogRotationError naming the likely holder, so
    cmd_respawn can clean-fail the respawn (un-rotate + snapshot restore, no
    new turn, no sid-swap) rather than half-swapping the record. `sleep` is
    injectable so tests exercise the retry without a real delay."""
    d = logs_dir()
    for suffix in (".jsonl", ".err"):
        src = d / f"{name}{suffix}"
        if not src.exists():
            continue
        dst = d / f"{name}{suffix}.1"
        last_exc = None
        for attempt in range(_ROTATE_RETRY_ATTEMPTS):
            try:
                os.replace(str(src), str(dst))
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                if attempt < _ROTATE_RETRY_ATTEMPTS - 1:
                    sleep(_ROTATE_RETRY_DELAY_SECONDS)
        if last_exc is not None:
            raise LogRotationError(
                f"could not rotate {src.name} for {name!r}: still locked after "
                f"{_ROTATE_RETRY_ATTEMPTS} attempts -- a follower or just-killed "
                f"claude turn likely still holds the log handle"
            ) from last_exc


def _unrotate_worker_log(name: str) -> None:
    """Undo _rotate_worker_log: move logs/<name>.jsonl.1 back over
    logs/<name>.jsonl (and the matching .err pair), overwriting whatever
    is currently there. Missing .1 files are tolerated (nothing was
    rotated, or a previous un-rotate already ran) -- a silent no-op, not
    an error.

    Task 5 fix wave, Finding 1 (task-5 adversarial review): cmd_respawn's
    launch-failure rollback restores the registry to the pre-respawn
    snapshot but, without this, never restores the LOG file --
    _rotate_worker_log already ran unconditionally before the failed
    launch, and launch_turn's append-mode open((re-)creates an empty
    logs/<name>.jsonl before the Popen that then raised. Every log-reading
    command (`peek`/`result`/`status` recompute) is keyed by name, so a
    rolled-back-but-not-un-rotated worker would look "dead" (empty log,
    no trailing result) despite the registry correctly reporting its old
    idle/dead state, and a SECOND failed or successful respawn would then
    rotate that empty file over the only surviving copy of the real
    transcript in .1, destroying it. os.replace atomically overwrites the
    empty stub launch_turn created, so the restored worker's log path
    points at its real history again."""
    d = logs_dir()
    for suffix in (".jsonl", ".err"):
        rotated = d / f"{name}{suffix}.1"
        if rotated.exists():
            os.replace(str(rotated), str(d / f"{name}{suffix}"))


def cmd_respawn(args, popen=subprocess.Popen, get_process_info=None, which=shutil.which,
                kill_process_tree=None, sleep=time.sleep) -> int:
    """`fleet respawn <name> [--task <text>] [--force]` (SPEC §5 respawn
    row): the context-reset lever -- a fresh session_id under the same
    name/cwd/mode/model, prompted with the preamble + task (original,
    truncated per the registry schema, or --task's override) + the
    worker's journal (state/journals/<name>.md, labeled, if it exists) +
    the OLD session_id's drained mailbox (consumed via the same
    claim/finalize/restore discipline as every other launch path here --
    never orphaned). Follows the uniform status-claim protocol verbatim
    (task-4-verdict.md "Uniform status-claim protocol", cited by name for
    respawn): pre-claim status="working"/turn_pid=None for the NEW record
    under one fleet_lock, launch strictly outside any lock, conditional
    rollback to the pre-respawn snapshot on BaseException, pid-stamp +
    re-assert "working" on success.

    Refuses while a turn is actively running unless --force, in which case
    it reuses _interrupt_worker's verified-kill contract exactly like
    cmd_attach's --force path (F3/F4): "killed"/"not_running" both mean
    the old turn is no longer alive, so respawn proceeds; "kill_failed"
    aborts loudly with NO registry mutation. A launch-in-flight window
    (status=="working", turn_pid is None -- another spawn/send/respawn/
    attach mid-launch) also refuses loudly under --force, same as
    cmd_attach's Fix-1 guard -- there is no real pid yet to verify-kill.
    An "attached" worker is NOT treated as "turn running" (attach never
    sets turn_pid) -- but it IS a live human TUI holding the name, so (Task
    5 fix wave, Finding 5 / task-5-review.md Important #2) respawn mirrors
    cmd_attach's own working-state guard for it: without --force it refuses
    loudly (FleetCliError, no mutation beyond the recompute persist) rather
    than silently reassigning the name out from under the operator's
    `claude --resume` terminal and rerouting their queued mail into a fresh
    session they never see. With --force it proceeds directly (no kill
    needed -- there is no turn_pid to interrupt), and the takeover releases
    the attach as a side effect: new_worker_record always starts
    attached_since=None, so the old attached TUI is simply orphaned from
    the registry once the new record replaces it -- a documented residual
    (the operator closes the stale terminal manually; nothing in fleet can
    revoke a detached terminal).

    cost_usd is carried over from the pre-respawn snapshot, NOT reset to
    0.0: it tracks total money spent on the NAMED worker across its whole
    lifetime, not per-session -- a respawn is a context reset (fresh
    session_id, fresh turns counter, fresh transcript), not a billing
    reset. turns resets to 0 (then to 1 once the new turn actually
    launches, mirroring cmd_spawn's own 0->1 transition for a first turn).
    The carried cost_usd is also stamped onto the new record's
    cost_baseline (Task 5 fix wave, Finding 4) -- recompute_worker adds
    this baseline to the rotated-fresh log's own trailing result cost,
    so the very next status/wait/send poll after the new session's first
    turn does not clobber the carried total down to just that turn's own
    cost.

    The log is rotated (_rotate_worker_log) once the new record is
    committed, before compose_prompt/launch_turn -- unconditionally,
    matching the SPEC §5 respawn row, since launch_turn's log file is
    opened append-mode and would otherwise tack the new turn's stdout onto
    the old session's transcript regardless of whether the new launch
    itself succeeds.

    NOTE (Task 5 spec-audit gap: cost-accumulation validation): this
    cumulative-cost_usd behavior is asserted by unit tests here against a
    fabricated registry/log fixture, but was NOT validated end-to-end
    against a real 2-turn `claude` invocation (no real claude process is
    ever spawned by this test suite, by design) -- that validation is
    explicitly deferred to the project's manual integration smoke test
    (SPEC §12), not implemented in this task.
    """
    _require_instance_settings()

    task_override = _read_task_arg(args.task) if args.task else None
    new_sid = str(uuid.uuid4())
    needs_force_interrupt = False

    # §5.1: respawn retires the old session id and rotates its log. Ask before
    # doing that to a worker this session did not spawn. Reads the registry
    # WITHOUT the lock (a lock-free read, like `status --stale-ok`) and prompts
    # outside it: a prompt must never block the fleet, and the guard must not
    # perturb the lock-acquisition sequence the launch path depends on.
    _ok, _reason, _snap = _read_registry_readonly()
    if _ok and args.name in _snap["workers"]:
        _confirm_destructive("respawn (retire the session of)", [args.name], _snap["workers"],
                             assume_yes=getattr(args, "yes", False))

    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = data["workers"][args.name]
        after = recompute_worker(args.name, before, get_process_info=get_process_info, sleep=sleep)
        if after["status"] != before["status"]:
            append_event("status_changed", args.name, old=before["status"], new=after["status"])

        old_sid = after["session_id"]
        cwd = after["cwd"]
        mode = after["mode"]
        model = after.get("model")
        # F13/M5: respawn is a launch path too -- carry the persisted cap +
        # setting-sources forward onto the new record (and its launch argv)
        # UNLESS an explicit --max-budget-usd/--setting-sources override is
        # passed (default None -> carry forward).
        max_budget_usd = (args.max_budget_usd if getattr(args, "max_budget_usd", None) is not None
                          else after.get("max_budget_usd"))
        setting_sources = (args.setting_sources if getattr(args, "setting_sources", None) is not None
                           else after.get("setting_sources"))
        # Kernel 10 (F12=M24): respawn is a launch path -- carry the persisted
        # token_ceiling forward onto the new record UNLESS an explicit
        # --token-ceiling override is passed (default None -> carry forward),
        # exactly like max_budget_usd above.
        token_ceiling = (args.token_ceiling if getattr(args, "token_ceiling", None) is not None
                         else after.get("token_ceiling"))
        cost_usd = _registry_cost(after.get("cost_usd", 0.0))
        task_for_record = task_override if task_override is not None else after.get("task", "")

        if after["status"] == "working":
            if not args.force:
                data["workers"][args.name] = after
                save_registry(data)
                raise FleetCliError(
                    f"{args.name}: turn is running -- pass --force to interrupt it first, "
                    "or wait for it to finish"
                )
            if after.get("turn_pid") is None:
                # Same launch-in-flight refusal as cmd_attach's Fix 1:
                # nothing real to verify-kill yet.
                data["workers"][args.name] = after
                save_registry(data)
                raise FleetCliError(
                    f"launch in flight for {args.name}; retry in a few seconds"
                )
            data["workers"][args.name] = after
            save_registry(data)
            needs_force_interrupt = True
            prior_snapshot = None  # filled in below, after the verified kill
        elif after["status"] == "attached" and not args.force:
            # Finding 5 (task-5 adversarial review / task-5-review.md
            # Important #2): mirror cmd_attach's own working-state guard
            # -- a live human TUI owns this name, refuse instead of
            # silently stealing it and rerouting the drained mailbox into
            # a session the operator never sees.
            data["workers"][args.name] = after
            save_registry(data)
            raise FleetCliError(
                f"{args.name}: worker is attached -- release it first "
                f"(`fleet release {args.name}`) or pass --force to take it over"
            )
        else:
            # Not actively running (idle/dead), or attached with --force
            # (the takeover releases the attach as a side effect --
            # new_worker_record always starts attached_since=None) --
            # pre-claim the NEW record right here, atomically with the
            # decision (F1 protocol): status="working"/turn_pid=None
            # until the launch below stamps a real pid.
            prior_snapshot = after
            new_record = new_worker_record(
                new_sid, cwd, task_for_record, mode, model=model,
                max_budget_usd=max_budget_usd, setting_sources=setting_sources,
                token_ceiling=token_ceiling)
            new_record["cost_usd"] = cost_usd  # cumulative -- see docstring
            new_record["cost_baseline"] = cost_usd  # Finding 4 -- see docstring
            # Provenance is IMMUTABLE across respawn (§5.1): respawning someone
            # else's worker must not silently transfer ownership to the
            # respawner, or a single forced respawn launders a foreign worker
            # into a freely-killable one.
            new_record["spawned_by"] = prior_snapshot.get("spawned_by")
            data["workers"][args.name] = new_record
            save_registry(data)
            append_event("respawned", args.name, old_session_id=old_sid, new_session_id=new_sid)

    if needs_force_interrupt:
        outcome = _interrupt_worker(args.name, get_process_info=get_process_info, kill_process_tree=kill_process_tree)
        if outcome == "kill_failed":
            raise FleetCliError(
                f"{args.name}: --force could not verify the running turn was killed -- "
                "aborting respawn (it may still be running)"
            )
        # "killed" or "not_running": the old turn is no longer alive.
        # _interrupt_worker's own "killed" path already committed
        # status="idle" on the (still old_sid) record -- re-read it as the
        # accurate rollback target before overwriting with the new record.
        #
        # F1 (final-review.md): mirror cmd_attach's guard -- the window
        # between _interrupt_worker's idle-commit (its lock release) and
        # this re-lock is exactly where a concurrent `fleet send`'s
        # idle-resume can pre-claim status="working"/turn_pid=None (or a
        # concurrent attach can claim "attached"). Check the RAW status
        # (not a fresh recompute -- recomputing here could itself demote a
        # legitimate idle to dead on log evidence unrelated to this race
        # and falsely refuse) is still exactly what _interrupt_worker's
        # own commit left it in (idle, or dead if a concurrent `fleet
        # kill` won instead) and refuse to overwrite anything else --
        # otherwise the send-launched turn would run orphaned against the
        # old sid while the registry tracks this new one.
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is None:
                raise FleetCliError(f"unknown worker: {args.name!r}")
            if r.get("status") not in ("idle", "dead"):
                raise FleetCliError(
                    f"{args.name}: worker was claimed concurrently during --force takeover; retry"
                )
            prior_snapshot = dict(r)
            new_record = new_worker_record(
                new_sid, cwd, task_for_record, mode, model=model,
                max_budget_usd=max_budget_usd, setting_sources=setting_sources,
                token_ceiling=token_ceiling)
            new_record["cost_usd"] = cost_usd  # cumulative -- see docstring
            new_record["cost_baseline"] = cost_usd  # Finding 4 -- see docstring
            # Provenance is IMMUTABLE across respawn (§5.1): respawning someone
            # else's worker must not silently transfer ownership to the
            # respawner, or a single forced respawn launders a foreign worker
            # into a freely-killable one.
            new_record["spawned_by"] = prior_snapshot.get("spawned_by")
            data["workers"][args.name] = new_record
            save_registry(data)
            append_event("respawned", args.name, old_session_id=old_sid, new_session_id=new_sid)

    # Log rotation (SPEC §5): unconditional, before launch -- see
    # _rotate_worker_log's docstring for why this must happen before
    # launch_turn's append-mode log open.
    #
    # B2 (rotation clean-fail): if the log is still held (a follower or
    # just-killed claude), _rotate_worker_log raises LogRotationError after
    # its retries. At this point the NEW pre-claimed record is already
    # persisted but NO turn has launched and NO mailbox claim exists yet
    # (compose_prompt runs below), so clean-fail here: un-rotate any partial
    # rename, restore the exact pre-respawn snapshot (guarded on the still-
    # unlaunched claim), and raise -- never a half-swapped record (invariant
    # 7). sleep is threaded through so the retry backoff is test-injectable.
    try:
        _rotate_worker_log(args.name, sleep=sleep)
    except LogRotationError as exc:
        _unrotate_worker_log(args.name)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if (r is not None and r.get("session_id") == new_sid
                    and r.get("status") == "working" and r.get("turn_pid") is None):
                data["workers"][args.name] = prior_snapshot
                save_registry(data)
                append_event(
                    "respawn_failed", args.name, error=str(exc),
                    old_session_id=old_sid, attempted_session_id=new_sid,
                )
        raise

    # Kernel 10 (fleet half): the new session gets its own sid-keyed ceiling
    # file (the old sid's is now stale/harmless) so the Stop hook keeps its
    # allow-stop signal across the respawn. Written after the successful
    # rotation, before launch.
    _write_ceiling_file(new_sid, token_ceiling)

    journal_path = journals_dir() / f"{args.name}.md"
    prompt, claim = compose_prompt(args.name, cwd, task_for_record, old_sid, journal_path=journal_path)
    try:
        info = launch_turn(
            args.name, cwd, new_sid, prompt, mode, first=True,
            # F13/M5: carry the persisted (or overridden) cap + setting-sources
            # onto the fresh-session launch argv.
            model=model, max_budget_usd=max_budget_usd, setting_sources=setting_sources,
            popen=popen, get_process_info=get_process_info, which=which,
        )
        finalize_mailbox_claim(claim)
    except BaseException as exc:
        # Conditional rollback (uniform protocol): restore the exact
        # pre-respawn snapshot, but ONLY if the record is still in the
        # precise claim state this call wrote (a concurrent actor may have
        # legitimately moved it on already).
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if (r is not None and r.get("session_id") == new_sid
                    and r.get("status") == "working" and r.get("turn_pid") is None):
                # Finding 1 (task-5 adversarial review): un-rotate the log
                # BEFORE restoring the registry snapshot -- the restored
                # record points at old_sid's history, which the
                # unconditional pre-launch rotation moved to
                # logs/<name>.jsonl.1 and launch_turn's failed-launch
                # append-open then stubbed out with an empty file.
                _unrotate_worker_log(args.name)
                data["workers"][args.name] = prior_snapshot
                save_registry(data)
                append_event(
                    "respawn_failed", args.name, error=str(exc),
                    old_session_id=old_sid, attempted_session_id=new_sid,
                )
        raise

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(args.name)
            if r is not None and r.get("session_id") == new_sid:
                r["status"] = "working"
                r["turn_pid"] = info["turn_pid"]
                r["turn_pid_ctime"] = info["turn_pid_ctime"]
                r["turns"] = 1
                r["last_activity"] = now_iso()
                save_registry(data)
            append_event("turn_started", args.name, session_id=new_sid, turn_pid=info["turn_pid"])

    # Post-testing wave, item 1b (stress-report Finding 1, CRITICAL): retry
    # with backoff instead of a single bare lock acquisition -- see
    # cmd_spawn's identical shape and _commit_launched_turn's docstring.
    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_turn(args.name, new_sid, info)

    print(f"{args.name} {new_sid} {info['log_path']}")
    return 0


def cmd_kill(args, get_process_info=None, kill_process_tree=None, sleep=time.sleep) -> int:
    """`fleet kill <name>` (SPEC §5): interrupt the turn if one is alive
    (reusing _interrupt_worker's verified-kill contract), then
    unconditionally mark the worker "dead" and append a "killed" event --
    kill is the terminal, "retire this worker" action, distinct from
    `fleet interrupt` (which only pauses a turn and marks idle). If the
    kill could not be verified ("kill_failed"), the worker is still marked
    dead (kill is meant to be final) but a loud warning is printed and the
    exit code is nonzero so the operator investigates the process
    manually -- unlike `fleet interrupt`, which deliberately leaves status
    alone on kill_failed rather than lie about it, `fleet kill`'s whole
    point is to retire the registry entry regardless.

    Finding 3 (task-5 adversarial review): a single "not_running" verdict
    from _interrupt_worker rests on one pid_alive() probe, and
    get_process_info returns None on ANY exception (a transient
    PowerShell hiccup, not just a genuinely dead process) -- worst case
    that misclassifies a live turn as not-running and permanently marks
    it "dead" while the real process keeps going, untracked. Before
    trusting a "not_running" verdict, wait _DEAD_CONFIRM_DELAY_SECONDS
    and re-run the whole _interrupt_worker check (itself a no-op/no-
    mutation call when it again finds nothing alive, so this is safe to
    repeat): if the process turns out to actually be alive on the second
    pass, this re-run performs the real kill instead of silently
    orphaning it as "dead".

    F2 (final-review.md): attach --force and respawn --force both refuse
    on a launch-in-flight claim (status=="working" and turn_pid is None --
    a spawn/send/attach/respawn pre-claim mid-launch_turn, with no real pid
    yet to verify-kill); kill lacked this guard. Without it, kill would
    snapshot pid=None, pid_alive(None)=False -> "not_running" on both
    probes, and unconditionally mark the worker dead -- either silently
    lying (the launcher's post-launch stamp re-asserts working+pid right
    after, so kill did nothing) or, worse, opening a window for a
    concurrent `fleet clean` to see dead+turn_pid=None (the recompute
    launch-in-flight guard no longer protects it) and delete the logs/
    mailbox of a live, just-launched worker out from under it. Refuse
    loudly instead, like the other two commands.

    Post-testing wave, item 1c: this guard checks the RAW stored status
    directly rather than calling recompute_worker (deliberately, to avoid a
    probe just to decide whether to refuse) -- so it duplicates
    recompute_status's own `_launch_claim_expired` check inline (cheap: it
    only needs the record's own `last_activity`, no subprocess call) rather
    than trusting a possibly-stale persisted status. Without this, an
    EXPIRED claim (last_activity older than LAUNCH_CLAIM_MAX_AGE_SECONDS --
    the fleet CLI died mid-launch and nothing ever re-persisted the demoted
    status) would refuse `fleet kill` forever, since nothing else in this
    command's path calls recompute_worker to flip the raw stored status to
    "dead" first."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]
        if (rec.get("status") == "working" and rec.get("turn_pid") is None
                and not _launch_claim_expired(rec.get("last_activity"))):
            raise FleetCliError(
                f"launch in flight for {args.name}; retry in a few seconds"
            )
        workers_snapshot = {args.name: dict(rec)}

    # §5.1: acknowledge before retiring a worker this session did not spawn.
    # Runs BEFORE _interrupt_worker (refusing after the turn is already dead
    # would help nobody) and OUTSIDE fleet_lock (an interactive prompt must
    # never block every other fleet command on a human's keystroke).
    _confirm_destructive("kill", [args.name], workers_snapshot,
                         assume_yes=getattr(args, "yes", False))

    outcome = _interrupt_worker(args.name, get_process_info=get_process_info, kill_process_tree=kill_process_tree)
    if outcome == "not_running":
        sleep(_DEAD_CONFIRM_DELAY_SECONDS)
        outcome = _interrupt_worker(args.name, get_process_info=get_process_info, kill_process_tree=kill_process_tree)

    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(args.name)
        if rec is not None:
            rec["status"] = "dead"
            rec["turn_pid"] = None
            rec["turn_pid_ctime"] = None
            save_registry(data)
        append_event("killed", args.name, interrupt_outcome=outcome)

    if outcome == "kill_failed":
        print(
            f"fleet: {args.name}: kill attempted but the turn still appears to be running -- "
            "marked dead anyway (kill is a terminal action); investigate the process manually",
            file=sys.stderr,
        )
        return 1
    print(f"{args.name}: killed")
    return 0


def _remove_worker_files(name: str, sid: str) -> list:
    """Delete every on-disk artifact for a removed dead worker: current +
    rotated logs, its mailbox file, any orphaned mailbox/*.claimed.* files
    for that sid (T3-F2, adversarial review deferred finding: a hook
    killed between claim and delete leaves a `.claimed.<pid>` file behind
    -- `fleet clean` sweeps these for the sid it is removing, rather than
    leaving them as permanent litter), and its journal. Best-effort
    (missing files are not an error). Returns the list of paths actually
    removed, for cmd_clean's print-what-was-removed contract."""
    removed = []
    candidates = [
        logs_dir() / f"{name}.jsonl", logs_dir() / f"{name}.jsonl.1",
        logs_dir() / f"{name}.err", logs_dir() / f"{name}.err.1",
        mailbox_dir() / f"{sid}.md",
        journals_dir() / f"{name}.md",
        # FIX-5 (F-4): the sid-keyed token-ceiling file (kernel 10) was never
        # cleaned -> a growing pile of orphaned state/ceilings/<sid> files.
        # Sweep it alongside the other per-worker artifacts.
        ceiling_file_path(sid),
    ]
    candidates += list(mailbox_dir().glob(f"{sid}.md.claimed.*")) if mailbox_dir().exists() else []
    for path in candidates:
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed


def cmd_clean(args, get_process_info=None, sleep=time.sleep) -> int:
    """`fleet clean` (SPEC §5): recompute every worker's status; any that
    resolve to "dead" are removed from the registry along with their logs
    (current + rotated), mailbox file, orphaned mailbox claim files for
    that sid (T3-F2), and journal. Prints one line per removed worker.
    Never touches idle/working/attached workers. A worker whose recompute
    merely changes status (without becoming dead) is persisted like
    `fleet status` does, not removed.

    Finding 3 (task-5 adversarial review): deletion here is irreversible,
    but "dead" rests on a single pid_alive() probe that can misfire on a
    transient get_process_info failure (any exception -> None, not just a
    genuinely dead process). A worker that recomputes to "dead" on the
    first pass is NOT removed on the strength of that alone -- it is
    re-recomputed (from the same pre-clean snapshot) after
    _DEAD_CONFIRM_DELAY_SECONDS, and only removed if the SECOND pass also
    says "dead". If the second pass disagrees, the worker is persisted
    with that (non-dead) status instead, exactly like a normal recompute
    -- the flaky first probe never gets to destroy anything. The delay is
    paid once per `clean` invocation (batched across every dead candidate),
    not once per worker.

    Review wave 5b (re-review of eef1c88): the confirm delay used to run
    INSIDE the single `with fleet_lock()` block, blocking every other
    concurrent fleet command for _DEAD_CONFIRM_DELAY_SECONDS -- `fleet
    kill` already got this right (its sleep sits outside its lock; see
    cmd_kill above). Restructured to mirror that shape: snapshot the dead
    candidates and release the lock, sleep + re-probe with no lock held at
    all, then re-acquire the lock only to merge the second-pass verdicts.
    On that second acquisition, each candidate's registry entry is
    re-checked against its pre-sleep snapshot -- if a concurrent command
    respawned (or otherwise mutated) it while the lock was released, that
    candidate is spared untouched rather than deleted or overwritten with
    a verdict computed against now-stale data.

    Stress residual, Finding N1 (re-review of 550df0a): review wave 5b
    above only moved the CONFIRM DELAY's re-probe outside the lock -- the
    FIRST pass still called recompute_worker's real probe (get_process_info,
    ~0.3s each against a "working" pid) for every worker inside the single
    `with fleet_lock()` block, the same recompute-all-under-lock shape that
    made `fleet status` a stress-critical (see cmd_status's docstring
    above): a concurrent `clean` over a large registry could hold the lock
    for seconds and strand an in-flight spawn/send/respawn commit. Fixed by
    applying the identical snapshot -> probe (no lock held) -> re-acquire
    -> conditional-commit shape cmd_status uses: snapshot every named
    record under the lock, release it, run every first-pass
    recompute_worker probe with no lock held at all, then re-acquire once
    to merge verdicts -- but only for records that still match their
    pre-probe snapshot exactly (full-dict equality), sparing anything a
    concurrent command mutated while the lock was released rather than
    clobbering it with a verdict computed against now-stale data."""
    removed = []  # list of (name, sid)
    pending_confirm = []  # (name, before) -- looked dead on pass 1, lock held
    with fleet_lock():
        data = load_registry()
        names = sorted(data["workers"])
        before = {n: data["workers"][n] for n in names}

    # Probe every worker's liveness with NO lock held (see docstring above)
    # -- this is the (potentially several-seconds-total) expensive part.
    after = {n: recompute_worker(n, before[n], get_process_info=get_process_info, sleep=sleep) for n in names}

    changed = False
    with fleet_lock():
        data = load_registry()
        for n in names:
            current = data["workers"].get(n)
            if current is None or current != before[n]:
                # Removed or mutated by a concurrent command while our lock
                # was released for probing -- spare it, don't act on a
                # verdict computed against now-stale pre-probe data.
                continue
            if after[n]["status"] == "dead":
                pending_confirm.append((n, before[n]))
            else:
                if after[n]["status"] != current["status"]:
                    append_event("status_changed", n, old=current["status"], new=after[n]["status"])
                    changed = True
                data["workers"][n] = after[n]
        if changed:
            save_registry(data)

    if pending_confirm:
        sleep(_DEAD_CONFIRM_DELAY_SECONDS)

    # Second probe: no lock held, mirroring cmd_kill's re-check shape.
    confirmations = [
        (n, before, recompute_worker(n, before, get_process_info=get_process_info, sleep=sleep))
        for n, before in pending_confirm
    ]

    # §5.1: this is the moment `clean` knows exactly which workers it will
    # DELETE (registry entry, logs, mailbox and journal -- irreversible; only
    # the claude session survives, resumable by sid from events.jsonl). Ask
    # before sweeping any worker this session did not spawn. Outside the lock:
    # a prompt must never block the fleet.
    doomed = {n: before for n, before, confirmed in confirmations if confirmed["status"] == "dead"}
    if doomed:
        _confirm_destructive("clean (delete logs + journal of)", sorted(doomed), doomed,
                             assume_yes=getattr(args, "yes", False))

    changed = False
    with fleet_lock():
        data = load_registry()
        for n, before, confirmed in confirmations:
            current = data["workers"].get(n)
            if current != before:
                # Respawned/mutated by someone else while our lock was
                # released -- spare it, don't act on a stale verdict.
                continue
            if confirmed["status"] != before["status"]:
                append_event("status_changed", n, old=before["status"], new=confirmed["status"])
                changed = True
            if confirmed["status"] == "dead":
                removed.append((n, confirmed["session_id"]))
                data["workers"].pop(n, None)
                changed = True
            else:
                data["workers"][n] = confirmed

        if changed:
            save_registry(data)
        for n, sid in removed:
            append_event("cleaned", n, session_id=sid)

    for n, sid in removed:
        _remove_worker_files(n, sid)
        print(f"removed {n} (session {sid})")

    if not removed:
        print("nothing to clean -- no dead workers")
    return 0


# ---------------------------------------------------------------------------
# CLI: doctor (SPEC §5 doctor row, §7 silent-failure alarm, §11) -- each
# check below returns (name, ok, message); cmd_doctor prints one [PASS]/
# [FAIL] line per check and exits nonzero iff any check is not ok.
#
# ASCII [PASS]/[FAIL] rather than literal unicode checkmark/cross glyphs
# (SPEC §5 phrases the requirement as "prints (tick)/(cross)"): some
# Windows console codepages (cp437/cp1252) raise UnicodeEncodeError on
# U+2713/U+2717 when stdout isn't in UTF-8 mode, which would make `fleet
# doctor` itself crash -- exactly the kind of silent-failure-alarm tool
# that must never fail to run. ASCII carries the same ok/not-ok signal
# unambiguously without that risk.
#
# Every check that is explicitly "note-only"/"warn" per the Task 5 brief
# (legacy settings file, stale PIDs, orphaned/pending mailboxes, stale
# attaches, orphaned *.claimed.* files, fleet-unknown claude-agents
# sessions, log sizes) always returns ok=True -- it can inform, never turn
# doctor red. Only genuinely broken infrastructure (claude missing/too
# old, a malformed/backslash-broken/stale settings instance, a hook that
# doesn't fire end-to-end) counts as a hard failure.
# ---------------------------------------------------------------------------

_CLAUDE_MIN_VERSION = (2, 1, 202)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def _parse_claude_version(text: str):
    m = _VERSION_RE.search(text or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _doctor_check_claude_version(which=shutil.which, run=subprocess.run):
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError as exc:
        return ("claude-on-path", False, str(exc))
    try:
        result = run([exe, "--version"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return ("claude-on-path", False, f"claude found at {exe} but --version failed: {exc}")
    version = _parse_claude_version((result.stdout or "") + (result.stderr or ""))
    if version is None:
        return ("claude-on-path", True, f"claude found at {exe} (could not parse --version output)")
    if version < _CLAUDE_MIN_VERSION:
        return ("claude-on-path", False,
                f"claude {'.'.join(map(str, version))} at {exe} is older than the required "
                f"{'.'.join(map(str, _CLAUDE_MIN_VERSION))}")
    return ("claude-on-path", True, f"claude {'.'.join(map(str, version))} at {exe}")


_HOOK_SCRIPT_TOKEN_RE = re.compile(r"\S+\.py\b")


def _extract_hook_commands(settings_data) -> list:
    """Pull every hooks.*.[].hooks[].command string out of a rendered
    worker-settings.json structure, tolerating any malformed/unexpected
    shape (returns [] rather than raising)."""
    commands = []
    hooks = settings_data.get("hooks") if isinstance(settings_data, dict) else None
    if not isinstance(hooks, dict):
        return commands
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for h in group.get("hooks", []) or []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    commands.append(h["command"])
    return commands


def _hook_script_tokens(command: str) -> list:
    """Extract every whitespace-delimited "*.py" token from a hook command
    string, stripping a leading/trailing quote char from each. Rendered
    worker-settings.json commands wrap each path segment in double quotes
    (a prior fix for spaced install paths, e.g. "C:/Users/.../python.exe"
    "C:/.../posttooluse_mailbox.py") -- \\S+\\.py\\b's greedy match includes
    the leading quote (it only stops at a \\b word boundary, which falls
    between the trailing "y" and the closing quote, not before it), so
    without stripping, Path(token).exists() would check a string starting
    with a literal `"` character and always report the real script file
    missing. Live-smoke-tested against this repo's actual rendered
    instance, which caught exactly this bug."""
    return [tok.strip("\"'") for tok in _HOOK_SCRIPT_TOKEN_RE.findall(command)]


def _doctor_check_instance_settings():
    path = instance_settings_path()
    if not path.exists():
        return ("worker-settings-instance", False, f"{path} missing -- run `fleet init`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ("worker-settings-instance", False, f"{path} does not parse as JSON: {exc}")
    commands = _extract_hook_commands(data)
    problems = []
    for cmd in commands:
        if "\\" in cmd:
            problems.append(f"backslash path in hook command: {cmd!r}")
        for script in _hook_script_tokens(cmd):
            if not Path(script).exists():
                problems.append(f"hook script not found: {script}")
    if problems:
        return ("worker-settings-instance", False, "; ".join(problems))
    return ("worker-settings-instance", True,
            f"{path} parses as JSON, hook commands use forward slashes, referenced scripts exist")


def _doctor_check_instance_freshness():
    info = instance_freshness_info()
    if info["stale"]:
        if not info["instance_exists"]:
            return ("instance-freshness", False, "worker-settings.json instance missing -- run `fleet init`")
        return ("instance-freshness", False,
                "worker-settings.json instance is older than the template -- run `fleet init`")
    return ("instance-freshness", True, "instance is up to date with the template")


def _doctor_check_legacy_settings():
    legacy = FLEET_HOME / "worker-settings.json"
    if legacy.exists():
        return ("legacy-settings", True,
                f"legacy {legacy} present -- no longer used (superseded by state/worker-settings.json); safe to delete")
    return ("legacy-settings", True, "no legacy root worker-settings.json present")


_HOOK_SMOKE_SID = "fleet-doctor-smoke"


def _run_hook_smoke(script_path: Path, home: Path, run=subprocess.run):
    mailbox = home / "mailbox"
    mailbox.mkdir(parents=True, exist_ok=True)
    (mailbox / f"{_HOOK_SMOKE_SID}.md").write_text("fleet doctor smoke test\n", encoding="utf-8")
    env = dict(os.environ)
    env["FLEET_HOME"] = str(home)
    payload = json.dumps({"session_id": _HOOK_SMOKE_SID})
    return run([sys.executable, str(script_path)], input=payload, capture_output=True,
               text=True, env=env, timeout=15)


def _doctor_check_posttooluse_hook_smoke(run=subprocess.run):
    """End-to-end smoke test (SPEC §5/§7 silent-failure alarm): fire the
    real PostToolUse hook script as a real subprocess with synthetic
    stdin + a scratch temp FLEET_HOME (mirrors tests/test_hooks.py's own
    technique), assert it emits valid hookSpecificOutput JSON."""
    script = FLEET_HOME / "bin" / "hooks" / "posttooluse_mailbox.py"
    if not script.exists():
        return ("posttooluse-hook-smoke", False, f"{script} not found")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = _run_hook_smoke(script, Path(tmp), run=run)
        except Exception as exc:
            return ("posttooluse-hook-smoke", False, f"failed to invoke hook: {exc}")
    if result.returncode != 0:
        return ("posttooluse-hook-smoke", False, f"exited {result.returncode}: {(result.stderr or '').strip()[:200]}")
    try:
        out = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return ("posttooluse-hook-smoke", False, f"did not emit JSON on stdout: {result.stdout[:200]!r}")
    if not isinstance(out, dict) or "hookSpecificOutput" not in out:
        return ("posttooluse-hook-smoke", False, f"unexpected JSON shape: {out}")
    return ("posttooluse-hook-smoke", True, "fired end-to-end and emitted valid hookSpecificOutput JSON")


def _doctor_check_stop_hook_smoke(run=subprocess.run):
    """Same as _doctor_check_posttooluse_hook_smoke but for the Stop hook
    (SPEC §5/§7): asserts a {"decision": "block", ...} JSON response."""
    script = FLEET_HOME / "bin" / "hooks" / "stop_mailbox.py"
    if not script.exists():
        return ("stop-hook-smoke", False, f"{script} not found")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            result = _run_hook_smoke(script, Path(tmp), run=run)
        except Exception as exc:
            return ("stop-hook-smoke", False, f"failed to invoke hook: {exc}")
    if result.returncode != 0:
        return ("stop-hook-smoke", False, f"exited {result.returncode}: {(result.stderr or '').strip()[:200]}")
    try:
        out = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return ("stop-hook-smoke", False, f"did not emit JSON on stdout: {result.stdout[:200]!r}")
    if not isinstance(out, dict) or out.get("decision") != "block":
        return ("stop-hook-smoke", False, f"unexpected JSON shape: {out}")
    return ("stop-hook-smoke", True, "fired end-to-end and emitted a valid block decision")


def _doctor_check_terminal_launcher(which=shutil.which):
    if which("wt"):
        return ("terminal-launcher", True, "wt (Windows Terminal) found on PATH")
    return ("terminal-launcher", True, "wt not found -- attach falls back to a detached PowerShell window")


def _doctor_check_stale_pids(workers: dict, get_process_info=None):
    stale = [
        name for name, rec in workers.items()
        if rec.get("status") == "working" and rec.get("turn_pid") is not None
        and not pid_alive(rec.get("turn_pid"), rec.get("turn_pid_ctime"), get_process_info=get_process_info)
    ]
    if stale:
        return ("stale-pids", True,
                f"{len(stale)} worker(s) show a stale turn_pid (run `fleet status` to refresh): {', '.join(stale)}")
    return ("stale-pids", True, "no stale turn_pid entries")


def _doctor_check_unreadable_starttime(workers: dict, get_process_info=None):
    """F15 (item 9): surface working workers whose turn process EXISTS but
    whose StartTime is unreadable (probe_liveness -> "unknown", the
    alive-unknown case). These are deliberately never demoted to dead by
    recompute_status, so doctor is where an operator learns the probe could
    not fully confirm them -- note-only (always PASS), never a hard failure."""
    unknown = [
        name for name, rec in workers.items()
        if rec.get("status") == "working" and rec.get("turn_pid") is not None
        and probe_liveness(rec.get("turn_pid"), rec.get("turn_pid_ctime"),
                           get_process_info=get_process_info) == "unknown"
    ]
    if unknown:
        return ("unreadable-starttime", True,
                f"{len(unknown)} working worker(s) with an unreadable process StartTime "
                f"(alive-unknown -- never reaped, verify manually): {', '.join(unknown)}")
    return ("unreadable-starttime", True, "no workers with an unreadable StartTime")


def _doctor_check_mailboxes(workers: dict):
    # F9 (item 8): orphaned mailbox files (sid matches no worker) are now
    # reported by _doctor_check_orphaned_claims (with sid + first-line
    # disposition) -- not duplicated here. This check owns only the
    # undelivered-mail-on-idle-worker signal.
    pending_idle = [
        name for name, rec in workers.items()
        if rec.get("status") == "idle" and _pending_mail_count(rec["session_id"]) > 0
    ]
    if pending_idle:
        return ("mailboxes", True,
                f"{len(pending_idle)} idle worker(s) with undelivered mail: {', '.join(pending_idle)}")
    return ("mailboxes", True, "no undelivered mail on idle workers")


def _doctor_check_stale_attaches(workers: dict):
    stale = [name for name, rec in workers.items()
             if (age := _attach_age_seconds(rec)) is not None and age > STALE_ATTACH_SECONDS]
    if stale:
        return ("stale-attaches", True, f"{len(stale)} worker(s) attached >3h: {', '.join(stale)}")
    return ("stale-attaches", True, "no attaches older than 3h")


def _doctor_check_limited_parks(workers: dict):
    """UL1 (item 11 / F31): NOTE-only surfacing of usage-limit parks. Three
    dispositions (always PASS -- a park is expected state, not a health
    failure): (a) parked PAST its reset horizon without resuming (resume-
    eligible but not yet swept -> prompt to run `fleet resume-limited`); (b)
    a `weekly`-kind park (multi-day horizon, so the operator knows the wait is
    expected, not a stall); (c) a null-horizon park (undetermined reset -- needs
    an operator-set reset before it can resume)."""
    limited = {n: r for n, r in workers.items() if r.get("status") == "limited"}
    if not limited:
        return ("limited-parks", True, "no usage-limit parks")
    past = sorted(n for n, r in limited.items() if _limit_reset_passed(r))
    weekly = sorted(n for n, r in limited.items() if r.get("limit_kind") == "weekly")
    null_h = sorted(n for n, r in limited.items() if r.get("limit_reset_at") is None)
    parts = []
    if past:
        parts.append(f"{len(past)} park(s) past reset -- run `fleet resume-limited`: {', '.join(past)}")
    if weekly:
        parts.append(f"{len(weekly)} weekly park(s) (multi-day horizon, expected): {', '.join(weekly)}")
    if null_h:
        parts.append(f"{len(null_h)} park(s) with unknown horizon (needs operator-set reset): {', '.join(null_h)}")
    if not parts:
        parts.append(f"{len(limited)} usage-limit park(s), none past reset")
    return ("limited-parks", True, " | ".join(parts))


def _mailbox_first_line(path: Path) -> str:
    """The first non-empty line of a mailbox file (best-effort), for the
    orphaned-mailbox disposition -- enough to identify what mail was stranded
    without dumping the whole file."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip():
                return line.strip()
    except OSError:
        pass
    return "(empty/unreadable)"


def _doctor_check_orphaned_claims(workers=None):
    """`fleet doctor` orphaned-mailbox + orphaned-claim check.

    F9 (item 8): "orphaned mailbox" = a mailbox/<sid>.md whose sid matches NO
    registered worker. This EXTENDS the pre-existing orphaned-claim check
    (mailbox/*.claimed.* files a hook left behind mid-claim) rather than
    duplicating it -- both are stranded mailbox artifacts doctor should
    surface. The orphaned-mailbox disposition prints the sid + its first line.
    `workers` defaults to None (skip the sid-matched orphan scans) so callers
    that only care about claim litter can still call it argument-free.

    FIX-5 (F-4): also NOTEs orphaned state/ceilings/<sid> files (a token-ceiling
    file whose sid matches no registered worker) -- EXTENDING this orphaned-sid
    surface rather than duplicating it. `fleet clean` sweeps them for a removed
    worker; this catches any left behind (e.g. a registry edited out-of-band)."""
    parts = []
    mbox_dir = mailbox_dir()
    if mbox_dir.exists():
        # T3-F2 (adversarial review deferred finding): report every orphaned
        # claim, not just ones tied to a dead worker being cleaned -- a hook can
        # die between claim and delete regardless of the worker's current status.
        claims = sorted(p.name for p in mbox_dir.glob("*.claimed.*"))
        if claims:
            parts.append(
                f"{len(claims)} orphaned mailbox/*.claimed.* file(s) (hook killed mid-claim; "
                f"safe to remove manually, or run `fleet clean`): {', '.join(claims)}")
        if workers is not None:
            known_sids = {rec["session_id"] for rec in workers.values()}
            orphans = sorted(p for p in mbox_dir.glob("*.md") if p.stem not in known_sids)
            if orphans:
                disp = "; ".join(f"{p.stem}: {_mailbox_first_line(p)!r}" for p in orphans)
                parts.append(
                    f"{len(orphans)} orphaned mailbox file(s) (sid matches no registered worker): {disp}")
    ceil_dir = ceilings_dir()
    if workers is not None and ceil_dir.exists():
        known_sids = {rec["session_id"] for rec in workers.values()}
        orphan_ceils = sorted(p.name for p in ceil_dir.iterdir()
                              if p.is_file() and not p.name.endswith(".tmp") and p.name not in known_sids)
        if orphan_ceils:
            parts.append(
                f"{len(orphan_ceils)} orphaned ceiling file(s) (state/ceilings/<sid> matching no "
                f"registered worker; run `fleet clean` or remove manually): {', '.join(orphan_ceils)}")
    if parts:
        return ("orphaned-claims", True, " | ".join(parts))
    return ("orphaned-claims", True, "no orphaned *.claimed.*, mailbox, or ceiling files")


def _doctor_check_claude_agents(workers: dict, which=shutil.which, run=subprocess.run):
    """Note-only (SPEC §2/§5): `claude agents --json` may not exist on
    older CLI builds, or may fail for any number of environmental reasons
    -- tolerate its absence/failure entirely rather than fail doctor."""
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError:
        return ("claude-agents", True, "claude not on PATH -- skipped")
    try:
        result = run([exe, "agents", "--json"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return ("claude-agents", True, f"`claude agents --json` unavailable -- skipped ({exc})")
    if result.returncode != 0:
        return ("claude-agents", True, "`claude agents --json` not supported on this CLI -- skipped")
    try:
        agents = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return ("claude-agents", True, "`claude agents --json` did not return JSON -- skipped")
    if not isinstance(agents, list):
        return ("claude-agents", True, "`claude agents --json` returned an unexpected shape -- skipped")
    known_sids = {rec["session_id"] for rec in workers.values()}
    unknown = sorted({
        sid for a in agents if isinstance(a, dict)
        for sid in [a.get("session_id") or a.get("id")]
        if sid and sid not in known_sids
    })
    if unknown:
        return ("claude-agents", True, f"{len(unknown)} claude agent session(s) not tracked by fleet: {', '.join(unknown)}")
    return ("claude-agents", True, "no fleet-unknown claude agent sessions")


_LOG_SIZE_WARN_BYTES = 50 * 1024 * 1024


def _doctor_check_log_sizes():
    big = []
    d = logs_dir()
    if d.exists():
        for path in d.glob("*"):
            try:
                if path.is_file() and path.stat().st_size > _LOG_SIZE_WARN_BYTES:
                    big.append(f"{path.name} ({path.stat().st_size // (1024 * 1024)}MB)")
            except OSError:
                continue
    if big:
        return ("log-sizes", True, f"{len(big)} log file(s) over 50MB: {', '.join(big)}")
    return ("log-sizes", True, "no log files over 50MB")


def _doctor_check_fleet_home_marker():
    """The `~/.claude/fleet-home` marker must exist and point at THIS fleet.

    `_write_fleet_home_marker` is best-effort and swallows OSError, so a failed
    write leaves no trace. A plugin installed from a marketplace cache then
    resolves FLEET_HOME to its own cache copy -- whose `state/` is gitignored
    and empty -- and the SessionStart briefing silently reports a fleet of ZERO
    workers while the real one is running. This check makes that visible."""
    marker = fleet_home_marker_path()
    expected = Path(FLEET_HOME).resolve()
    if not marker.exists():
        return ("fleet-home marker", False,
                f"{marker} is missing -- run `fleet init` (the plugin's SessionStart "
                f"hook cannot find this fleet without it)")
    try:
        recorded = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return ("fleet-home marker", False, f"{marker} unreadable: {exc}")
    if not recorded:
        return ("fleet-home marker", False, f"{marker} is empty -- run `fleet init`")
    recorded_path = Path(recorded)
    if not recorded_path.is_dir():
        return ("fleet-home marker", False,
                f"{marker} points at {recorded}, which does not exist -- run `fleet init`")
    if recorded_path.resolve() != expected:
        return ("fleet-home marker", False,
                f"{marker} points at {recorded_path.resolve().as_posix()}, but this fleet is "
                f"{expected.as_posix()} -- run `fleet init` here to claim it")
    return ("fleet-home marker", True, f"{marker} -> {expected.as_posix()}")


def _doctor_check_hook_errors():
    """Phase1 kernel 1: surface the TAIL of state/hook-errors.log when it is
    nonempty (the swallowed-hook-exception log). Never a hard failure -- a
    logged error means a hook hit an exception but still exited 0 (SPEC
    invariant 2); doctor's job here is to make that visible, not to fail."""
    lines = _hook_error_lines()
    if not lines:
        return ("hook-errors", True, "no swallowed hook errors logged")
    tail = lines[-_HOOK_ERROR_TAIL:]
    return ("hook-errors", True,
            f"{len(lines)} swallowed hook error(s) logged; last {len(tail)}: " + " | ".join(tail))


_KNOWN_HOOK_EVENTS = frozenset({"PostToolUse", "Stop", "PostCompact"})


def _doctor_check_hook_registration():
    """Phase1 kernel 2 (F11): static lint of the rendered worker-settings.json
    hook wiring. Parse the instance, assert every REGISTERED event name is a
    known one (`PostToolUse`/`Stop`/`PostCompact` -- PostCompact is the new
    harden-hooks event this lint has learned), each command's script path
    exists on disk, and the JSON shape is well-formed. Catches the typo'd
    event name / moved script the synthetic hook-smoke check false-greens on.

    Tolerant of a hooks-less instance (returns PASS): the
    `worker-settings-instance` check owns "is anything rendered at all"; this
    lint only validates what IS registered, so a stub `{}` never turns doctor
    red here."""
    path = instance_settings_path()
    if not path.exists():
        return ("hook-registration", False, f"{path} missing -- run `fleet init`")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ("hook-registration", False, f"{path} does not parse as JSON: {exc}")
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if hooks is None:
        return ("hook-registration", True, "no hooks registered (nothing to lint)")
    if not isinstance(hooks, dict):
        return ("hook-registration", False, f"{path} 'hooks' is not a JSON object")
    problems = []
    for event, groups in hooks.items():
        if event not in _KNOWN_HOOK_EVENTS:
            problems.append(
                f"unknown hook event name {event!r} (known: {', '.join(sorted(_KNOWN_HOOK_EVENTS))})")
        if not isinstance(groups, list):
            problems.append(f"hooks.{event} is not a list")
            continue
        for group in groups:
            if not isinstance(group, dict):
                problems.append(f"hooks.{event} contains a non-object entry")
                continue
            for h in group.get("hooks", []) or []:
                cmd = h.get("command") if isinstance(h, dict) else None
                if not isinstance(cmd, str):
                    problems.append(f"hooks.{event} has a hook with no command string")
                    continue
                for script in _hook_script_tokens(cmd):
                    if not Path(script).exists():
                        problems.append(f"hooks.{event} command path not found: {script}")
    if problems:
        return ("hook-registration", False, "; ".join(problems))
    registered = ", ".join(sorted(hooks)) or "none"
    return ("hook-registration", True,
            f"all registered hook events known and command paths exist ({registered})")


def cmd_doctor(args, which=shutil.which, run=subprocess.run, get_process_info=None) -> int:
    """`fleet doctor` (SPEC §5 doctor row, §7 silent-failure alarm): runs
    every health check below and prints one [PASS]/[FAIL] line each;
    exits nonzero iff any check is not ok.

    Snapshots the registry under one fleet_lock() (matching
    _interrupt_worker's snapshot pattern) then runs every check OUTSIDE
    the lock: several checks shell out (claude --version, claude agents
    --json, two real hook-smoke subprocesses) and holding fleet_lock
    across them would starve every concurrent `fleet` command exactly the
    way F4 existed to prevent for _interrupt_worker."""
    with fleet_lock():
        data = load_registry()
    workers = data.get("workers", {})

    checks = [
        _doctor_check_claude_version(which=which, run=run),
        _doctor_check_instance_settings(),
        _doctor_check_instance_freshness(),
        _doctor_check_hook_registration(),
        _doctor_check_legacy_settings(),
        _doctor_check_posttooluse_hook_smoke(run=run),
        _doctor_check_stop_hook_smoke(run=run),
        _doctor_check_terminal_launcher(which=which),
        _doctor_check_stale_pids(workers, get_process_info=get_process_info),
        _doctor_check_unreadable_starttime(workers, get_process_info=get_process_info),
        _doctor_check_mailboxes(workers),
        _doctor_check_stale_attaches(workers),
        _doctor_check_limited_parks(workers),
        _doctor_check_orphaned_claims(workers=workers),
        _doctor_check_claude_agents(workers, which=which, run=run),
        _doctor_check_log_sizes(),
        _doctor_check_fleet_home_marker(),
        _doctor_check_hook_errors(),
        _doctor_check_supervisor_claim(),
        _doctor_check_supervisor_handoff(),
    ]

    all_ok = True
    for name, ok, message in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {message}")
        if not ok:
            all_ok = False
    return 0 if all_ok else 1


# ---------------------------------------------------------------------------
# Outcome store (M-B, spec §5): terminal-outcome records per worker.
# Written by the Stop hook (kind="result") and by fleet-side tombstones
# (kill/interrupt/stop -- G10: an operator stop fires NO Stop hook).
# The outcome discriminator's only data source. JSONL, name-keyed, with a
# sid-keyed fallback file for hooks that could not resolve the name.
# ---------------------------------------------------------------------------

OUTCOME_FRESH_SLACK_SECONDS = 5.0
OUTCOME_RESULT_TEXT_MAX = 20000
TOMBSTONE_KINDS = ("killed", "interrupted", "stopped")


_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


def _atomic_append_bytes(path: Path, data: bytes) -> None:
    """Single-syscall atomic append. Opens the file for FILE_APPEND_DATA
    access ONLY (no GENERIC_WRITE) -- the Win32 kernel documents this access
    mode as giving each WriteFile call atomic append semantics across
    concurrently-open handles/processes, so two writers appending "at the
    same instant" (Stop hook + fleet-side tombstone, see module banner)
    never interleave or clobber each other's line.

    Deliberately NOT `os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)`
    + `os.write`: on Windows that goes through the C runtime's O_APPEND
    emulation, which lseek()s to EOF and write()s as two separate steps per
    call -- a real TOCTOU race between handles that reproducibly drops whole
    clean records under concurrent writers (confirmed empirically: 4
    threads x 250 records via os.open+O_APPEND lost ~17% of records with
    zero JSON-decode errors, i.e. silent loss, not corruption -- the same
    failure mode the CRITICAL finding this fixes originally reported). The
    FILE_APPEND_DATA-only handle below is the actual OS-level fix; verified
    to lose zero of 1000 records under the same test. ctypes/kernel32 only
    -- no platform-detection branch of any kind (this build targets Windows
    only, SPEC §14)."""
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
        if not ok:
            raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")
    finally:
        kernel32.CloseHandle(handle)


def append_outcome(key: str, record: dict) -> None:
    result_text = record.get("result_text")
    if isinstance(result_text, str) and len(result_text) > OUTCOME_RESULT_TEXT_MAX:
        record = dict(record)
        record["result_text"] = result_text[:OUTCOME_RESULT_TEXT_MAX]
    outcomes_dir().mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    _atomic_append_bytes(outcome_path(key), (line + "\n").encode("utf-8"))


def read_outcomes(name: str, sid: str | None = None) -> list[dict]:
    records = []
    paths = [outcome_path(name)]
    if sid and sid != name:
        paths.append(outcome_path(sid))
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(rec, dict):
                records.append(rec)
    if sid is not None:
        records = [r for r in records if r.get("session_id") == sid]
    records.sort(key=lambda r: str(r.get("ts", "")))
    return records


def latest_outcome(name: str, sid: str) -> dict | None:
    recs = read_outcomes(name, sid=sid)
    return recs[-1] if recs else None


def has_fresh_outcome(name: str, sid: str, since_iso: str) -> bool:
    try:
        since = _parse_iso(since_iso)
    except (ValueError, TypeError):
        return False
    threshold = since - timedelta(seconds=OUTCOME_FRESH_SLACK_SECONDS)
    for rec in read_outcomes(name, sid=sid):
        try:
            ts = _parse_iso(str(rec.get("ts", "")))
        except (ValueError, TypeError):
            continue
        if ts >= threshold:
            return True
    return False


def write_tombstone_outcome(name: str, sid: str, kind: str) -> None:
    if kind not in TOMBSTONE_KINDS:
        raise ValueError(f"unknown tombstone kind: {kind}")
    append_outcome(name, {"ts": now_iso(), "session_id": sid, "kind": kind,
                          "result_text": None})


# --------------------------------------------------------------------------
# Native dispatch (M-B, spec §5): single choke point for every --bg launch.
# Task-file bootstrap (G8), short-id capture + sid-prefix roster join (G6
# fallback), fresh -n render per dispatch (G13 / spec §5.1.3).
# --------------------------------------------------------------------------

NATIVE_JOIN_VERIFY_SECONDS = 60.0
NATIVE_JOIN_POLL_SECONDS = 3.0
NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0
DEFAULT_CATEGORY = "fleet"
NATIVE_NAME_HINT_MAX = 40

# · = MIDDLE DOT (the daemon's literal separator glyph). Previously a
# duplicate-codepoint char class `[··]` (same character twice) -- collapsed
# to a single literal, behavior-identical.
_BG_SHORT_ID_RE = re.compile(r"backgrounded\s*·\s*(\S+)\s*·")


class NativeDispatchError(Exception):
    pass


def render_native_name(category, name: str, hint: str) -> str:
    # category gets the same treatment as hint: whitespace-collapsed, then
    # `|` replaced (not stripped, to keep legibility) so a pipe in either
    # field can never corrupt the `cat|name|hint` split("|", 2) convention.
    cat = " ".join(str(category or DEFAULT_CATEGORY).split()).replace("|", "/")
    clean = " ".join((hint or "").split()).replace("|", "/")[:NATIVE_NAME_HINT_MAX]
    return f"{cat}|{name}|{clean}"


def _parse_bg_short_id(stdout_text: str):
    m = _BG_SHORT_ID_RE.search(stdout_text or "")
    return m.group(1) if m else None


def _roster_entry_for(entries, sid):
    for e in entries:
        if isinstance(e, dict) and e.get("sessionId") == sid:
            return e
    return None


def _join_roster_by_short_id(short_id, roster_fetch, sleep,
                             verify_seconds=NATIVE_JOIN_VERIFY_SECONDS,
                             exclude_sids=frozenset(), clock=time.monotonic):
    """Full sid whose prefix is the dispatch-printed short id. Matches done
    entries too -- a fast worker finishes before verify (spec §3).

    `exclude_sids` skips any prefix-matching sid already known before this
    dispatch began (belt-and-braces against joining a foreign, pre-existing
    session that happens to share the short-id prefix -- adversarial trap 1).
    `clock` is injectable so tests never pay the real verify-window wall time.
    """
    deadline = clock() + verify_seconds
    while True:
        ok, payload = roster_fetch()
        if ok:
            for e in payload:
                sid = e.get("sessionId") if isinstance(e, dict) else None
                if (isinstance(sid, str) and sid.startswith(short_id)
                        and sid not in exclude_sids):
                    return sid
        if clock() >= deadline:
            return None
        sleep(NATIVE_JOIN_POLL_SECONDS)


def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
                hint="", resume_sid=None, settings_path=None,
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
                roster_fetch=None, clock=time.monotonic):
    # Defense in depth (adversarial trap 6): every current caller
    # pre-validates `name`, but this is the single choke point for every
    # --bg launch and `task_file_path(name)` is not traversal-safe on its
    # own -- guard here too so a future direct-call path can't escape
    # tasks_dir().
    if not name or not NAME_RE.match(name):
        raise NativeDispatchError(f"invalid worker name: {name!r} (must match {NAME_RE.pattern})")
    if roster_fetch is None:
        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError as exc:
        raise NativeDispatchError(str(exc)) from exc
    settings = Path(settings_path) if settings_path else instance_settings_path()
    try:
        tasks_dir().mkdir(parents=True, exist_ok=True)
        task_path = task_file_path(name)
        task_path.write_text(prompt_body, encoding="utf-8")
    except OSError as exc:
        raise NativeDispatchError(f"task-file write failed: {exc}") from exc
    rendered = render_native_name(category, name, hint)
    tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
    argv = [exe, "--bg"]
    if resume_sid:
        argv += ["--resume", resume_sid]
    argv += ["-n", rendered, "--settings", settings.as_posix()]
    argv += mode_flags(mode)
    if model:
        argv += ["--model", model]
    argv.append(tiny_prompt)
    # Snapshot the roster ONCE before dispatching -- any sid already present
    # (sharing the short-id prefix fleet is about to receive) is excluded
    # from the join below, so a foreign concurrent session can never be
    # mistaken for the one just launched. A snapshot fetch failure never
    # blocks dispatch -- fall back to an empty exclusion set.
    pre_ok, pre_entries = roster_fetch()
    pre_sids = ({e.get("sessionId") for e in pre_entries if isinstance(e, dict)}
                if pre_ok else frozenset())
    try:
        proc = run(argv, cwd=str(cwd), env=_worker_env(name),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=NATIVE_DISPATCH_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeDispatchError(f"--bg dispatch failed: {exc}") from exc
    if proc.returncode != 0:
        raise NativeDispatchError(
            f"--bg dispatch exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
    short_id = _parse_bg_short_id(proc.stdout or "")
    if not short_id:
        raise NativeDispatchError(
            f"could not parse short id from --bg stdout: {(proc.stdout or '').strip()[:400]}")
    sid = _join_roster_by_short_id(short_id, roster_fetch, sleep,
                                   exclude_sids=pre_sids, clock=clock)
    if sid is None:
        raise NativeDispatchError(
            f"dispatched (short id {short_id}) but no roster entry joined "
            f"within {NATIVE_JOIN_VERIFY_SECONDS:.0f}s -- possible DOA; "
            f"recover manually via claude agents")
    return {"session_id": sid, "short_id": short_id, "rendered_name": rendered}


# ---------------------------------------------------------------------------
# Supervisor identity (native-pivot spec §4, milestone M-A)
#
# Soul = git-tracked files (supervisor/GOALS.md operator-owned,
# supervisor/JOURNAL.md append-only). Body claim = supervisor/INCARNATION
# (machine-local, gitignored), written ONLY under fleet_lock, read lock-free
# (atomic os.replace writes make torn reads impossible). HANDSHAKE is a
# separate gitignored file so a claimless handoff successor never touches
# the journal (single-writer, claim-holder-only -- spec §4, no exceptions).
# ---------------------------------------------------------------------------

SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0   # T: handoff wait before abort (spec §4)
SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0   # dispatch -> roster-join window (contract G6 fallback)

SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)

_SUPERVISOR_JOURNAL_SEED = """# Supervisor Journal

Append-only checkpoint log (spec §4). Single writer: the current claim
holder, via `fleet sup-*` commands only. Never edit or delete entries.
Entry header format: `## <utc-iso> <KIND> inc=<incarnation-id> sid=<session-id>`
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.

<!-- entries below -->
"""


def supervisor_dir() -> Path:
    return FLEET_HOME / "supervisor"


def goals_path() -> Path:
    return supervisor_dir() / "GOALS.md"


def incarnation_path() -> Path:
    return supervisor_dir() / "INCARNATION"


def handshake_path() -> Path:
    return supervisor_dir() / "HANDSHAKE"


def supervisor_journal_path() -> Path:
    return supervisor_dir() / "JOURNAL.md"


def handoff_abort_flag_path() -> Path:
    """Doctor-visible flag written by sup-handoff-abort (spec §4 timeout
    branch). Lives in state/ (gitignored runtime), cleared by the next
    sup-handoff-begin or manually by the operator."""
    return state_dir() / "supervisor-handoff-aborted.json"


def _write_json_atomic(path: Path, obj: dict) -> None:
    """Atomic JSON write (temp + os.replace) so lock-free readers (views,
    SessionStart hook) can never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(path))


def read_incarnation() -> dict | None:
    """The current claim, or None when absent/unreadable. Lock-free-safe
    (writes are atomic); mutating callers still re-read under fleet_lock."""
    try:
        data = json.loads(incarnation_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_incarnation(claim: dict) -> None:
    """Caller MUST hold fleet_lock (single-supervisor invariant, spec §4)."""
    _write_json_atomic(incarnation_path(), claim)


def read_handshake() -> dict | None:
    try:
        data = json.loads(handshake_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_handshake(incarnation_id: str, session_id: str) -> None:
    _write_json_atomic(handshake_path(), {
        "incarnation_id": incarnation_id,
        "session_id": session_id,
        "written_at": now_iso(),
    })


def mint_incarnation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"inc-{stamp}-{uuid.uuid4().hex[:4]}"


_SUPERVISOR_ENTRY_RE = re.compile(
    r"^## (?P<ts>\S+) (?P<kind>[A-Z][A-Z-]*) inc=(?P<inc>\S+) sid=(?P<sid>\S+)\s*$")


def parse_supervisor_journal(text: str) -> list:
    """Parse JOURNAL.md into entry dicts {ts, kind, inc, sid, body}. Prose
    outside entry headers is tolerated: lines before the first header are
    the seed doc; lines after a header up to the next header are that
    entry's body (stray human notes ride along in the preceding body)."""
    entries = []
    current = None
    for line in text.splitlines():
        m = _SUPERVISOR_ENTRY_RE.match(line)
        if m:
            if current is not None:
                current["body"] = "\n".join(current["body"]).strip("\n")
                entries.append(current)
            current = {**m.groupdict(), "body": []}
        elif current is not None:
            current["body"].append(line)
    if current is not None:
        current["body"] = "\n".join(current["body"]).strip("\n")
        entries.append(current)
    return entries


def supervisor_journal_entries() -> list:
    try:
        text = supervisor_journal_path().read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_supervisor_journal(text)


def supervisor_journal_latest():
    entries = supervisor_journal_entries()
    return entries[-1] if entries else None


def supervisor_journal_append(kind: str, inc: str, sid: str, body: str) -> None:
    """Append one checkpoint entry. Caller MUST hold fleet_lock and MUST be
    the verified claim holder (enforced by the cmd layer via
    _require_claim_holder) -- spec §4: append-only, single-writer."""
    if kind not in SUPERVISOR_JOURNAL_KINDS:
        raise ValueError(f"unknown journal kind {kind!r}; allowed: {', '.join(SUPERVISOR_JOURNAL_KINDS)}")
    path = supervisor_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_SUPERVISOR_JOURNAL_SEED, encoding="utf-8")
    # Header-injection escape: a body line that itself looks like an entry
    # header (e.g. a quoted/pasted journal excerpt) must never be able to
    # parse back out as a real entry -- prefix it with a space so
    # _SUPERVISOR_ENTRY_RE no longer matches (line no longer starts with "##").
    safe_body = "\n".join(
        f" {line}" if _SUPERVISOR_ENTRY_RE.match(line) else line
        for line in body.rstrip().splitlines()
    )
    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{safe_body}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def _roster_live_sids(entries: list) -> set:
    """Sids whose backing process is LIVE. Contract rule
    (docs/specs/native-substrate.md, roster contract): `status`/`pid` keys
    exist only while the process lives; a lingering `state:"done"` entry
    (observed surviving >=3h21m) must NOT count as live, or a finished
    predecessor would block every successor claim for hours."""
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and e.get("sessionId") and ("status" in e or "pid" in e)
    }


def supervisor_epoch_check(roster_ok: bool, payload):
    """Roster-epoch sanity check, run BEFORE any claim decision (spec §4).
    A failed or empty roster freezes the decision -- a daemon restart (G9)
    must never let a fresh boot seize a claim whose holder is alive."""
    if not roster_ok:
        return (False, f"roster unavailable ({payload}) -- freeze, never decide blind")
    if not payload:
        return (False, "roster is EMPTY -- not even this session is listed; "
                       "daemon restart suspected (G9). Freeze + page operator.")
    return (True, f"roster holds {len(payload)} entr{'y' if len(payload) == 1 else 'ies'}")


def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS):
    """Claim rules at boot (spec §4, verbatim order). Returns (verdict, reason);
    verdict in {"claim","refuse","seize","freeze"}. Pure function -- no IO."""
    if now is None:
        now = datetime.now(timezone.utc)
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    holder_sid = claim.get("session_id")
    if holder_sid in live_sids:
        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "
                          f"(sid {holder_sid}) is live in the roster")
    try:
        beat = _parse_iso(claim["heartbeat_at"])
    except (KeyError, TypeError, ValueError):
        return ("freeze", "claim heartbeat unreadable -- ambiguous; never seize on ambiguity")
    if latest_entry is not None and latest_entry.get("inc") != claim.get("incarnation_id"):
        try:
            entry_ts = _parse_iso(latest_entry["ts"])
        except (KeyError, TypeError, ValueError):
            entry_ts = None
        if entry_ts is not None and entry_ts > beat:
            return ("refuse", f"journal's latest checkpoint is a fresher incarnation "
                              f"({latest_entry.get('inc')}) -- transition in flight")
    age = (now - beat).total_seconds()
    if age > stale_seconds:
        return ("seize", f"holder roster-gone, heartbeat stale ({age:.0f}s > {stale_seconds:.0f}s)")
    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). Never seize on ambiguity.")


def _fetch_agents_roster(which=shutil.which, run=subprocess.run):
    """(ok, entries|reason). Sanctioned surface only: `claude agents --json
    --all` (contract: roster contract). utf-8/replace decoding -- roster
    names may carry emoji/`·` that cp1252 consoles mangle."""
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError:
        return (False, "claude executable not found on PATH")
    try:
        proc = run([exe, "agents", "--json", "--all"], capture_output=True,
                   text=True, encoding="utf-8", errors="replace", timeout=30)
    except Exception as exc:  # noqa: BLE001 -- any spawn failure is one verdict
        return (False, f"`claude agents --json --all` failed: {exc}")
    if proc.returncode != 0:
        return (False, f"`claude agents --json --all` exit {proc.returncode}: "
                       f"{(proc.stderr or '').strip()[:200]}")
    try:
        entries = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        return (False, f"roster JSON unparseable: {exc}")
    if not isinstance(entries, list):
        return (False, f"roster has unexpected shape: {type(entries).__name__}")
    return (True, entries)


def _render_boot_bundle(roster_entries: list, snap: dict, journal_entries: list) -> str:
    """The boot ritual's read set, one string (spec §4: GOALS + JOURNAL tail
    + knowledge INDEX + roster + fleet status). M-A interim reconciliation =
    today's registry verdicts via status_snapshot -- the outcome
    discriminator's inputs don't exist until M-B."""
    out = ["=== SUPERVISOR BOOT BUNDLE ==="]
    try:
        goals = goals_path().read_text(encoding="utf-8").rstrip()
    except OSError:
        goals = "(supervisor/GOALS.md missing)"
    out += ["", "--- supervisor/GOALS.md ---", goals]
    out += ["", "--- supervisor/JOURNAL.md tail (last 5) ---"]
    tail = journal_entries[-5:]
    if tail:
        for e in tail:
            out.append(f"## {e['ts']} {e['kind']} inc={e['inc']} sid={e['sid']}")
            if e["body"].strip():
                out.append(e["body"].rstrip())
    else:
        out.append("(no checkpoints yet)")
    out += ["", "--- knowledge/INDEX.md (first 20 non-blank lines) ---"]
    try:
        idx = [ln for ln in (knowledge_dir() / "INDEX.md")
               .read_text(encoding="utf-8").splitlines() if ln.strip()][:20]
    except OSError:
        idx = ["(missing)"]
    out += idx
    live = _roster_live_sids(roster_entries)
    out += ["", f"--- native roster: {len(roster_entries)} entries, {len(live)} live ---"]
    out += ["", "--- fleet status (M-A interim reconciliation: registry verdicts) ---"]
    if snap.get("ok"):
        t = snap["totals"]
        out.append(f"{t['workers']} worker(s), ${t['cost_usd']:.2f} lifetime, {t['mail']} pending mail")
        for w in snap["workers"]:
            mail = f", {w['mail']} mail" if w["mail"] else ""
            out.append(f"  {w['name']}: {w['status']}, {w['turns']} turns, ${w['cost_usd']:.2f}{mail}")
    else:
        out.append(f"(registry unreadable: {snap.get('reason')})")
    return "\n".join(out)


def cmd_sup_boot(args, which=shutil.which, run=subprocess.run) -> int:
    """`fleet sup-boot [--sid SID] [--handoff-inc INC]` -- the ONE boot code
    path (morning / post-reboot / post-handoff, spec §4). Epoch check runs
    BEFORE the claim decision; the roster subprocess runs OUTSIDE fleet_lock
    (F4 doctrine: never hold the lock across a subprocess)."""
    caller_sid = getattr(args, "sid", None) or current_caller_session()
    if not caller_sid:
        raise FleetCliError("sup-boot: caller session unknown -- run from a Claude "
                            "session or pass --sid")
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    epoch_ok, epoch_reason = supervisor_epoch_check(roster_ok, payload)
    entries = payload if roster_ok else []
    live_sids = _roster_live_sids(entries)

    inc_line = None
    if getattr(args, "handoff_inc", None):
        # Successor mode: claim-pending, holds NO claim, takes no actions
        # (spec §4). Writes HANDSHAKE only -- never the journal.
        with fleet_lock():
            write_handshake(args.handoff_inc, caller_sid)
        verdict = "handshake-written"
        reason = (f"successor {args.handoff_inc} awaiting claim transfer; "
                  f"take NO fleet actions until sup-status shows your incarnation")
        rc = 0
    else:
        with fleet_lock():
            claim = read_incarnation()
            latest = supervisor_journal_latest()
            if not epoch_ok:
                verdict, reason = "freeze", f"epoch check failed: {epoch_reason}"
            else:
                verdict, reason = supervisor_claim_decision(claim, live_sids, latest)
            if verdict == "claim":
                inc = mint_incarnation_id()
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": "fresh"})
                supervisor_journal_append("BOOT", inc, caller_sid, f"fresh claim: {reason}")
                inc_line = inc
            elif verdict == "seize":
                inc = mint_incarnation_id()
                dead = claim.get("incarnation_id", "?")
                try:
                    # Stale-HANDSHAKE hygiene (spec §4): an orphan from a crash
                    # mid-handoff must never receive a claim transfer.
                    handshake_path().unlink()
                except FileNotFoundError:
                    pass
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": "seize"})
                supervisor_journal_append("SEIZED", inc, caller_sid,
                                          f"seized from {dead}: {reason}")
                inc_line = inc
            # refuse / freeze: strictly read-only.
        rc = {"claim": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]

    bundle = _render_boot_bundle(entries, status_snapshot(), supervisor_journal_entries())
    lines = [bundle, "", f"EPOCH: {'ok' if epoch_ok else 'FAIL'} -- {epoch_reason}"]
    if inc_line:
        lines.append(f"INCARNATION: {inc_line}")
    lines.append(f"VERDICT: {verdict} -- {reason}")
    _write_text_tolerating_console_encoding("\n".join(lines) + "\n")
    return rc


def _require_claim_holder(sid_override=None):
    """(claim, caller_sid) iff the caller holds the claim; FleetCliError
    otherwise. Enforces spec §4's journal single-writer rule at the only
    write chokepoint. Caller MUST already hold fleet_lock."""
    claim = read_incarnation()
    if claim is None:
        raise FleetCliError("no supervisor claim exists -- run `fleet sup-boot` first")
    caller = sid_override or current_caller_session()
    if not caller:
        raise FleetCliError("caller session unknown -- pass --sid or run from a Claude session")
    if caller != claim.get("session_id"):
        raise FleetCliError(
            f"caller sid {caller} does not hold the claim (holder: "
            f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
            f"the journal is single-writer, claim-holder-only (spec §4)")
    return claim, caller


def cmd_sup_checkpoint(args) -> int:
    """`fleet sup-checkpoint <body|@file> [--kind CHECKPOINT|PROPOSAL] [--sid S]`.
    Every checkpoint refreshes the heartbeat (spec §4: 'the holder refreshes
    at every checkpoint/beat')."""
    body = _read_task_arg(args.body)
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        supervisor_journal_append(args.kind, claim["incarnation_id"], caller, body)
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"checkpointed ({args.kind}) as {claim['incarnation_id']}; heartbeat refreshed")
    return 0


def cmd_sup_heartbeat(args) -> int:
    """`fleet sup-heartbeat [--sid S]` -- beat without journal spam (GOALS
    frugality: a beat is not an event worth a checkpoint)."""
    with fleet_lock():
        claim, _ = _require_claim_holder(getattr(args, "sid", None))
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"heartbeat refreshed for {claim['incarnation_id']}")
    return 0


def cmd_sup_status(args) -> int:
    """`fleet sup-status [--json]` -- READ-ONLY VIEW (terminal-surface
    doctrine: no lock, no probe, no write). Safe lock-free reads: all
    supervisor state files are written atomically."""
    claim = read_incarnation()
    hs = read_handshake()
    beat_age = None
    if claim is not None:
        try:
            beat_age = (datetime.now(timezone.utc) - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            beat_age = None
    info = {
        "goals_active": supervisor_goals_active(),
        "incarnation": claim,
        "heartbeat_age_seconds": beat_age,
        "handshake": hs,
        "abort_flag": handoff_abort_flag_path().exists(),
        "nag": supervisor_status_line(),
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
    if claim is None:
        print("supervisor: no claim" + (" (GOALS active -- start one: `fleet sup-boot`)"
                                        if info["goals_active"] else ""))
    else:
        age = f"{beat_age:.0f}s ago" if beat_age is not None else "unreadable"
        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
              f"via {claim.get('claimed_via', '?')}, heartbeat {age}")
    if hs is not None:
        print(f"handshake: {hs.get('incarnation_id')} sid={hs.get('session_id')} (handoff in flight)")
    if info["abort_flag"]:
        print(f"WARNING: aborted-handoff flag present ({handoff_abort_flag_path()})")
    return 0


def _render_successor_task(successor_inc: str, old_inc: str) -> str:
    """Successor bootstrap body (task-file bootstrap, contract G8 -- never
    argv for size-unbounded content). Paths rendered .as_posix()."""
    fleet_py = (FLEET_HOME / "bin" / "fleet.py").as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
Your predecessor ({old_inc}) dispatched you mid-handoff (spec docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §4).

Do exactly this, in order:
1. Run: py -3.13 {fleet_py} sup-boot --handoff-inc {successor_inc}
   This prints your boot bundle and writes supervisor/HANDSHAKE. You hold NO claim yet.
2. Take NO spawn/respawn/send/kill/clean actions before claim transfer -- spec §4's double-spawn guard.
3. Poll every ~30s (up to 10 minutes): py -3.13 {fleet_py} sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     py -3.13 {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}"
     then read your boot bundle output and continue the supervisor duty per skills/fleet/supervisor.md.
   - If 10 minutes pass without transfer: the handoff was aborted. STOP -- take no actions,
     end your turn with the final message: HANDOFF-ORPHAN {successor_inc}
"""


def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
                          sleep=time.sleep) -> int:
    """`fleet sup-handoff-begin [--model M] [--permission-mode P] [--sid S]`.
    Checkpoint-then-act: HANDOFF-BEGIN is journaled BEFORE dispatch so a
    crash mid-dispatch leaves evidence. Dispatch + roster polling run
    OUTSIDE fleet_lock (F4 doctrine)."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        successor_inc = mint_incarnation_id()
        task_path = state_dir() / f"supervisor-handoff-{successor_inc}.md"
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(_render_successor_task(successor_inc, claim["incarnation_id"]),
                             encoding="utf-8")
        supervisor_journal_append("HANDOFF-BEGIN", claim["incarnation_id"], caller,
                                  f"successor={successor_inc} task={task_path.as_posix()}")
        try:
            # A new attempt supersedes any previous aborted handoff.
            handoff_abort_flag_path().unlink()
        except FileNotFoundError:
            pass

    exe = resolve_claude_executable(which=which)
    pre_ok, pre_payload = _fetch_agents_roster(which=which, run=run)
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict)}
    name = f"sup|{successor_inc}|successor"
    argv = [exe, "--bg", "-n", name]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    if getattr(args, "permission_mode", None):
        argv += ["--permission-mode", args.permission_mode]
    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
    try:
        proc = run(argv, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise FleetCliError(f"successor dispatch failed: {exc} -- no successor to stop; "
                            f"claim unchanged, duty continues")
    if proc.returncode != 0:
        raise FleetCliError(f"successor dispatch failed (exit {proc.returncode}): "
                            f"{(proc.stderr or '').strip()[:300]} -- no successor to stop; "
                            f"claim unchanged, duty continues")

    # G6 fallback: join by fresh `-n` match within the verify window.
    successor_sid = None
    deadline = time.monotonic() + SUPERVISOR_ROSTER_VERIFY_SECONDS
    while time.monotonic() < deadline:
        ok, payload = _fetch_agents_roster(which=which, run=run)
        if ok:
            fresh = [e for e in payload if isinstance(e, dict)
                     and e.get("name") == name and e.get("sessionId")
                     and e.get("sessionId") not in pre_sids]
            if fresh:
                successor_sid = fresh[0]["sessionId"]
                break
        sleep(3)
    if successor_sid is None:
        print(f"successor DOA: no roster entry named {name!r} appeared within "
              f"{SUPERVISOR_ROSTER_VERIFY_SECONDS:.0f}s (contract G6 fallback). "
              f"Claim unchanged -- duty continues; re-run sup-handoff-begin to retry.")
        return 1

    print(f"SUCCESSOR-INC: {successor_inc}")
    print(f"SUCCESSOR-SID: {successor_sid}")
    print(f"Next: wait for supervisor/HANDSHAKE (timeout "
          f"{SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:.0f}s), then run:\n"
          f"  fleet sup-handoff-complete --expect-inc {successor_inc} --expect-sid {successor_sid}\n"
          f"On timeout/failure instead run:\n"
          f"  fleet sup-handoff-abort --successor-sid {successor_sid}")
    return 0


def cmd_sup_handoff_complete(args) -> int:
    """`fleet sup-handoff-complete --expect-inc I --expect-sid S [--sid ...]`.
    Dual verification (spec §4): the HANDSHAKE must carry EXACTLY the
    incarnation id the old side minted AND the sid it dispatched. Journal
    HANDOFF-COMPLETE first (old is still holder), then transfer."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        hs = read_handshake()
        if hs is None:
            raise FleetCliError("no supervisor/HANDSHAKE -- successor not ready; wait, "
                                "or sup-handoff-abort past the timeout")
        if (hs.get("incarnation_id") != args.expect_inc
                or hs.get("session_id") != args.expect_sid):
            raise FleetCliError(
                f"HANDSHAKE mismatch: found inc={hs.get('incarnation_id')} "
                f"sid={hs.get('session_id')}, expected inc={args.expect_inc} "
                f"sid={args.expect_sid} -- NOT transferring (spec §4 id verification)")
        supervisor_journal_append("HANDOFF-COMPLETE", claim["incarnation_id"], caller,
                                  f"claim -> {args.expect_inc} sid={args.expect_sid}")
        write_incarnation({"incarnation_id": args.expect_inc,
                           "session_id": args.expect_sid,
                           "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                           "claimed_via": "handoff"})
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
    print(f"claim transferred to {args.expect_inc}. This (old) incarnation must now "
          f"EXIT: end the session, take no further fleet actions.")
    return 0


def cmd_sup_handoff_abort(args, which=shutil.which, run=subprocess.run) -> int:
    """`fleet sup-handoff-abort --successor-sid S [--sid ...]` -- spec §4
    timeout branch: old resumes duty, stops the limbo successor (`claude
    stop`, NEVER raw kill -- G10 zombie hazard), removes HANDSHAKE, raises
    the doctor-visible flag. Note contract G10: `claude stop` fires NO Stop
    hook -- nothing will have journaled on the successor's behalf."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
        supervisor_journal_append("HANDOFF-ABORT", claim["incarnation_id"], caller,
                                  f"stopping limbo successor sid={args.successor_sid}")
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "successor_sid": args.successor_sid,
            "holder": claim["incarnation_id"],
        })
        claim["heartbeat_at"] = now_iso()   # old resumes duty
        write_incarnation(claim)
    exe = resolve_claude_executable(which=which)
    try:
        proc = run([exe, "stop", args.successor_sid], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"WARNING: `claude stop {args.successor_sid}` stop failed "
              f"({exc}) -- successor may still be live; stop it manually via the "
              f"agents menu. Abort flag is set either way.")
        return 0
    if proc.returncode != 0:
        print(f"WARNING: `claude stop {args.successor_sid}` stop failed "
              f"(exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}) -- "
              f"successor may still be live; stop it manually via the agents menu. "
              f"Abort flag is set either way.")
    else:
        print(f"limbo successor {args.successor_sid} stopped; duty resumed by "
              f"{claim['incarnation_id']}. Doctor will flag until the abort flag is cleared.")
    return 0


def supervisor_goals_active() -> bool:
    """GOALS.md exists, decodes, and is not parked. Operator parks the nag by
    adding the literal token SUPERVISOR-DORMANT anywhere in GOALS.md.
    ValueError covers UnicodeDecodeError: an undecodable GOALS.md must not
    crash the unguarded read-only callers (cmd_sup_status, views)."""
    try:
        text = goals_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    return "SUPERVISOR-DORMANT" not in text


def supervisor_status_line(now=None):
    """One-line supervisor status/nag for VIEWS (SessionStart hook, doctor,
    sup-status). File-only by mandate (spec §4 nag predicate + terminal-
    surface doctrine): no lock, no roster read, no subprocess -- the
    heartbeat timestamp alone carries liveness, so this may false-fire on a
    live idle supervisor (accepted: the nag is advisory; seizure stays
    gated on roster-gone in sup-boot). Never raises; None = GOALS absent
    or dormant."""
    try:
        if not supervisor_goals_active():
            return None
        if now is None:
            now = datetime.now(timezone.utc)
        claim = read_incarnation()
        if claim is None:
            return ("SUPERVISOR: GOALS active, no claim -- boot one "
                    "(`fleet sup-boot`; see skills/fleet/supervisor.md).")
        inc = claim.get("incarnation_id", "?")
        try:
            age = (now - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
        if age > SUPERVISOR_CLAIM_STALE_SECONDS:
            return (f"SUPERVISOR: claim {inc} heartbeat stale (~{age / 60:.0f}m > "
                    f"{SUPERVISOR_CLAIM_STALE_SECONDS / 60:.0f}m) -- boot a new incarnation.")
        return f"SUPERVISOR: {inc} live, heartbeat {age / 60:.0f}m ago."
    except Exception:  # noqa: BLE001 -- view: never raises
        return None


def _doctor_check_supervisor_claim():
    """Spec §4 nag, doctor surface. ALWAYS ok=True -- the nag is advisory
    (an absent supervisor is a prompt, not a health failure)."""
    line = supervisor_status_line()
    if line is None:
        return ("supervisor-claim", True, "GOALS absent or dormant -- no supervisor expected")
    return ("supervisor-claim", True, line)


def _doctor_check_supervisor_handoff():
    """FAIL on handoff residue needing an operator: the aborted-handoff flag
    (sup-handoff-abort wrote it) or a HANDSHAKE older than the handoff
    timeout (orphan from a crash mid-handoff -- the seize path will delete
    it, but doctor should not wait for a seize to notice)."""
    parts = []
    ok = True
    if handoff_abort_flag_path().exists():
        ok = False
        parts.append(f"aborted-handoff flag present ({handoff_abort_flag_path().name}) -- "
                     f"review supervisor/JOURNAL.md, delete the flag once resolved")
    if handshake_path().exists():
        try:
            age = time.time() - handshake_path().stat().st_mtime
        except OSError:
            age = None
        if age is None or age > SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:
            ok = False
            parts.append("stale supervisor/HANDSHAKE (older than the handoff timeout) -- "
                         "orphan from a crashed handoff; safe to delete manually")
        else:
            parts.append("HANDSHAKE present (handoff in flight)")
    if not parts:
        parts.append("no handoff in flight, no aborted-handoff flag")
    return ("supervisor-handoff", ok, " | ".join(parts))


# ---------------------------------------------------------------------------
# CLI: argparse wiring + main()
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet", description="claude-fleet manager CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("home", help="print the resolved FLEET_HOME path")

    sub.add_parser("knowledge", help="print knowledge/INDEX.md")

    p_init = sub.add_parser("init", help="render the machine-local worker-settings.json instance from the template")
    p_init.add_argument("--statusline", action="store_true",
                        help="also install fleet's statusline into ~/.claude/settings.json")
    p_init.add_argument("--chain", action="store_true",
                        help="with --statusline: keep an existing foreign statusline and print "
                             "fleet's row beneath it")
    p_init.add_argument("--force", action="store_true",
                        help="with --statusline: overwrite an existing foreign statusline")

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
    # Spec-audit gap 5 (SPEC §6 L125): raw passthrough to `claude
    # --setting-sources`, e.g. "user,project" -- restricts which foreign
    # settings sources merge into the worker turn (see SKILL.md doctrine:
    # use this when a repo's own Stop hook fights fleet's turn-end model).
    p_spawn.add_argument("--setting-sources", dest="setting_sources", default=None)
    # Kernel 10 (F12=M24): a cumulative TOKEN ceiling (int) enforced
    # fleet-side before each resume launch, and written to the sid-keyed
    # ceiling file the Stop hook reads to allow-stop despite pending mail. NOT
    # a per-invocation dollar cap (that is --max-budget-usd).
    p_spawn.add_argument("--token-ceiling", type=int, default=None, dest="token_ceiling")

    p_status = sub.add_parser("status", help="show worker status table")
    p_status.add_argument("name", nargs="?", default=None)
    p_status.add_argument("--json", action="store_true",
                          help="print the status snapshot as JSON")
    p_status.add_argument("--stale-ok", dest="stale_ok", action="store_true",
                          help="read-only fast path: no PID probe, no lock, no write "
                               "(last-committed state; used by the statusline)")

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

    p_respawn = sub.add_parser("respawn", help="fresh session for a worker (context-reset lever)")
    p_respawn.add_argument("name")
    p_respawn.add_argument("--task", default=None)
    p_respawn.add_argument("--force", action="store_true")
    p_respawn.add_argument("--yes", action="store_true",
                           help="confirm respawning a worker this session did not spawn")
    # F13/M5: respawn carries the persisted max_budget_usd/setting_sources
    # forward by default; these optional overrides replace them (default None
    # -> carry forward, mirroring the immutable-at-spawn rule for a reset).
    p_respawn.add_argument("--max-budget-usd", type=float, default=None, dest="max_budget_usd")
    p_respawn.add_argument("--setting-sources", dest="setting_sources", default=None)
    # Kernel 10 (F12=M24): carry-forward-or-override, like the two above.
    p_respawn.add_argument("--token-ceiling", type=int, default=None, dest="token_ceiling")

    # UL1 (item 11 / F31): explicit usage-limit resume sweep.
    p_resume = sub.add_parser("resume-limited",
                              help="relaunch limited workers whose reset horizon has passed")
    p_resume.add_argument("name", nargs="?", default=None)
    p_resume.add_argument("--force-now", action="store_true", dest="force_now",
                          help="resume a named worker even before its horizon / with an unknown horizon")

    p_kill = sub.add_parser("kill", help="interrupt (if running) and mark a worker dead")
    p_kill.add_argument("--yes", action="store_true",
                        help="confirm killing a worker this session did not spawn")
    p_kill.add_argument("name")

    p_clean = sub.add_parser("clean", help="remove dead workers and their logs/mailboxes/journals")
    p_clean.add_argument("--yes", action="store_true",
                         help="confirm deleting workers this session did not spawn")

    sub.add_parser("doctor", help="run fleet health checks")

    p_supboot = sub.add_parser("sup-boot", help="supervisor boot ritual: epoch check, claim decision, boot bundle (spec §4)")
    p_supboot.add_argument("--sid", help="override caller session id (default: CLAUDE_CODE_SESSION_ID)")
    p_supboot.add_argument("--handoff-inc", dest="handoff_inc",
                           help="handoff-successor mode: write HANDSHAKE with this incarnation id; no claim action")

    p_supckpt = sub.add_parser("sup-checkpoint", help="append a supervisor journal checkpoint (claim holder only) + refresh heartbeat")
    p_supckpt.add_argument("body", help="checkpoint text, or @file")
    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
    p_supckpt.add_argument("--sid", help="override caller session id")

    p_supbeat = sub.add_parser("sup-heartbeat", help="refresh the supervisor claim heartbeat (no journal write)")
    p_supbeat.add_argument("--sid", help="override caller session id")

    p_supstat = sub.add_parser("sup-status", help="read-only supervisor claim/handshake status")
    p_supstat.add_argument("--json", action="store_true")

    p_suphb = sub.add_parser("sup-handoff-begin", help="dispatch a handoff successor (claim holder only)")
    p_suphb.add_argument("--model", help="model for the successor session")
    p_suphb.add_argument("--permission-mode", dest="permission_mode", help="permission mode for the successor session")
    p_suphb.add_argument("--sid", help="override caller session id")

    p_suphc = sub.add_parser("sup-handoff-complete", help="verify HANDSHAKE and transfer the claim")
    p_suphc.add_argument("--expect-inc", dest="expect_inc", required=True)
    p_suphc.add_argument("--expect-sid", dest="expect_sid", required=True)
    p_suphc.add_argument("--sid", help="override caller session id")

    p_supha = sub.add_parser("sup-handoff-abort", help="abort a handoff: stop the limbo successor, resume duty")
    p_supha.add_argument("--successor-sid", dest="successor_sid", required=True)
    p_supha.add_argument("--sid", help="override caller session id")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "home":
            return cmd_home(args)
        if args.command == "knowledge":
            return cmd_knowledge(args)
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
        if args.command == "respawn":
            return cmd_respawn(args)
        if args.command == "resume-limited":
            return cmd_resume_limited(args)
        if args.command == "kill":
            return cmd_kill(args)
        if args.command == "clean":
            return cmd_clean(args)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "sup-boot":
            return cmd_sup_boot(args)
        if args.command == "sup-checkpoint":
            return cmd_sup_checkpoint(args)
        if args.command == "sup-heartbeat":
            return cmd_sup_heartbeat(args)
        if args.command == "sup-status":
            return cmd_sup_status(args)
        if args.command == "sup-handoff-begin":
            return cmd_sup_handoff_begin(args)
        if args.command == "sup-handoff-complete":
            return cmd_sup_handoff_complete(args)
        if args.command == "sup-handoff-abort":
            return cmd_sup_handoff_abort(args)
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
