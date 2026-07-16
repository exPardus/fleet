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
import functools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


def record_pin_pass(claude_version: str) -> None:
    """T12's pin-test suite calls this on a green run (SPEC re-verification
    doctrine): stamps the CLI version the native contract was last verified
    against, so `fleet doctor`'s pin-version check can flag drift.

    M-B T11 fix wave: normalizes through _parse_claude_version at write
    time (defense on the write end, to complement the read-end
    normalization in _doctor_check_pin_version) so a caller passing the
    raw, unparsed `claude --version` stdout (e.g. "2.1.207 (Claude
    Code)\\n") is stored in the same bare "X.Y.Z" shape doctor compares
    against, rather than propagating formatting noise into a permanent
    false FAIL. If the string doesn't parse as a version at all, it is
    stored as-is -- _doctor_check_pin_version treats an unparseable
    pinned value as an invalid pin record (PASS-note), never a crash."""
    parsed = _parse_claude_version(claude_version)
    normalized = ".".join(map(str, parsed)) if parsed is not None else claude_version
    _write_json_atomic(pin_pass_path(), {"claude_version": normalized, "passed_at": now_iso()})


def read_pin_pass() -> dict | None:
    """Lock-free tolerant read: missing file, unreadable file, or non-JSON
    content all resolve to None rather than raising -- doctor is the only
    consumer and must never crash on a corrupt/absent pin-pass record."""
    try:
        data = json.loads(pin_pass_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


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


def refuse_if_archived(name: str, record: dict, action: str) -> None:
    """M-B T9 (spec §5.1.2): a tombstoned (archived_at set) worker is
    history-only -- every native mutating command refuses it up front
    rather than silently reanimating or re-touching a retired record.
    `fleet clean` is deliberately exempt (it is the only sanctioned
    deleter of an archived record) and never calls this guard."""
    if isinstance(record, dict) and record.get("archived_at") is not None:
        raise FleetCliError(
            f"{name}: archived -- history only (fleet clean to delete)"
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
    template_settings_path(). Every worker dispatch's --settings argv value
    points here (dispatch_bg's default), never at the template."""
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

class AutocleanTaskQueryError(Exception):
    """schtasks could not say whether the autoclean task exists (F3:
    transient failure, access denied, timeout). Callers fail CLOSED --
    treating this as "task absent" would let a /Create /F clobber a
    foreign task of the same name on a hiccup."""


class UnsupportedPlatformError(NotImplementedError):
    """Raised by every _PosixPlatform method: there is no POSIX backend yet
    (Phase 1.5, SPEC §14) -- this build only supports Windows."""


class _WindowsPlatform:
    """Windows implementation of every OS-specific fleet operation."""

    def autoclean_task_query(self, task_name: str, run=subprocess.run):
        """None ONLY when the task is definitively absent; its command
        string when installed ("" if the XML is unparseable); raises
        AutocleanTaskQueryError when existence cannot be determined (F3:
        callers must fail CLOSED -- reading a transient failure as
        "absent" licensed /Create /F over a foreign task).

        Two locale-safe steps: existence via the full `/FO CSV` listing
        (a targeted /TN query's not-found error string is locale-
        translated and indistinguishable from access-denied by exit code;
        the listing's exit code + name presence are not), then the
        command via `/XML` (element names are not translated either)."""
        try:
            listing = run(["schtasks", "/Query", "/FO", "CSV"],
                          capture_output=True, text=True, timeout=30)
        except Exception as exc:
            raise AutocleanTaskQueryError(f"schtasks listing failed: {exc}")
        if listing.returncode != 0:
            raise AutocleanTaskQueryError(
                f"schtasks listing exit {listing.returncode}: "
                f"{(listing.stderr or '').strip()[:200]}")
        if f'"\\{task_name}"' not in (listing.stdout or ""):
            return None  # definitively absent
        try:
            proc = run(["schtasks", "/Query", "/TN", task_name, "/XML"],
                       capture_output=True, text=True, timeout=15)
        except Exception as exc:
            raise AutocleanTaskQueryError(f"schtasks XML query failed: {exc}")
        if proc.returncode != 0:
            raise AutocleanTaskQueryError(
                f"schtasks XML query exit {proc.returncode}: "
                f"{(proc.stderr or '').strip()[:200]}")
        xml = proc.stdout or ""
        parts = []
        for tag in ("Command", "Arguments"):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
            if m:
                text = m.group(1).strip()
                for ent, ch in (("&quot;", '"'), ("&lt;", "<"),
                                ("&gt;", ">"), ("&amp;", "&")):
                    text = text.replace(ent, ch)
                parts.append(text)
        return " ".join(p for p in parts if p)

    def autoclean_task_install(self, task_name: str, command: str,
                               interval_hours: int, run=subprocess.run):
        """(ok, message). `/F` makes re-install idempotent -- the caller is
        responsible for the refuse-foreign-task check BEFORE calling this."""
        try:
            proc = run(["schtasks", "/Create", "/F", "/TN", task_name,
                        "/TR", command, "/SC", "HOURLY", "/MO", str(int(interval_hours))],
                       capture_output=True, text=True, timeout=30)
        except Exception as exc:
            return (False, str(exc))
        if proc.returncode != 0:
            return (False, (proc.stderr or proc.stdout or "").strip()[:300])
        return (True, "")

    def autoclean_task_remove(self, task_name: str, run=subprocess.run):
        """(ok, message). Missing task counts as failure -- the caller
        reports it; nothing here raises."""
        try:
            proc = run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                       capture_output=True, text=True, timeout=30)
        except Exception as exc:
            return (False, str(exc))
        if proc.returncode != 0:
            return (False, (proc.stderr or proc.stdout or "").strip()[:300])
        return (True, "")


class _PosixPlatform:
    """Stub POSIX backend: every method raises UnsupportedPlatformError.
    Phase 1.5 fills these in (docs/specs/portability.md); Phase 1 targets
    Windows only (SPEC §14)."""

    def _unsupported(self, what: str):
        raise UnsupportedPlatformError(
            f"{what} has no POSIX implementation yet (Phase 1.5, SPEC §14); "
            "this build only supports Windows"
        )

    def autoclean_task_query(self, task_name: str, run=None):
        self._unsupported("autoclean_task_query")

    def autoclean_task_install(self, task_name: str, command: str,
                               interval_hours: int, run=None):
        self._unsupported("autoclean_task_install")

    def autoclean_task_remove(self, task_name: str, run=None):
        self._unsupported("autoclean_task_remove")


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
    except OSError:
        # Debt roll-up item 6: a failed token write (ENOSPC) used to leak
        # the fd AND strand a token-less lock file that blocked every
        # acquirer until the stale-break window. Close and remove what we
        # just created (O_EXCL guarantees it is ours; no successor can have
        # legitimately claimed it inside the stale window) before re-raising.
        # Fix-wave F4: the close itself is guarded -- if it also raised, the
        # unlink was skipped (stranding the lock file anyway) and the close
        # error masked the original write error on the way out.
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            path.unlink()
        except OSError:
            pass
        raise
    try:
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

# Sids are the daemon's session UUIDs; archive evidence files are named
# `<sid>.jsonl`/`<sid>.md`, so a UUID-shaped stem under logs/archive/*/ is
# a sid fleet once owned (_archive_dir_sids). Shared with validate_name's
# F6 refusal so worker names can never collide with that keyspace.
_SID_SHAPE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def validate_name(name: str, existing=()) -> None:
    """Raise ValueError unless name matches [a-z0-9-]+ and isn't in `existing`.

    F6 (adversarial review): uuid-shaped names are refused outright. Names
    and session ids share keyspaces in several stores (name-keyed AND
    sid-keyed outcome files, archive evidence basenames, `read_outcomes`'
    dual lookup), and `_archive_dir_sids` harvests sid-SHAPED stems as
    owned evidence -- a worker named exactly a foreign session's uuid would
    make that foreign session husk-rm-eligible after archival. Rejecting
    at the single creation choke point makes the whole conflation class
    unrepresentable instead of patching one reader at a time."""
    if not name or not NAME_RE.match(name):
        raise ValueError(f"invalid worker name {name!r}: must match [a-z0-9-]+")
    if _SID_SHAPE_RE.match(name):
        raise ValueError(
            f"invalid worker name {name!r}: uuid-shaped names are reserved "
            f"for session ids (F6)")
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


def _append_event_quiet(kind: str, name: str, **fields) -> None:
    """Best-effort append_event for use INSIDE a commit_fn retried by
    `_commit_launched_turn` (debt fix-wave F1). That helper retries OSError,
    and an event-append OSError escaping AFTER save_registry already made
    the mutation durable would re-run a NON-idempotent commit body: the
    fork-steer retry reloads, sees session_id already restamped, and falls
    into its orphaned branch (misreporting a committed steer and skipping
    the ceiling write); the legacy resume shape double-increments `turns`.
    The registry commit is the retried atomic core -- a lost forensics line
    must never re-run or misreport it, so log the failure loudly and move
    on."""
    try:
        append_event(kind, name, **fields)
    except OSError as exc:
        # Fix-wave N1: the notice itself must never raise back into the
        # retried commit_fn (EPIPE is an OSError; a closed stderr raises
        # ValueError). Fix-wave micro: include the fields payload -- for a
        # lost turn_started/steered the sid in there IS what the forensics
        # line exists to preserve.
        try:
            payload = json.dumps(fields, default=str)
            print(f"fleet: WARNING: event {kind!r} for {name} not recorded "
                  f"({exc}) -- fields {payload} -- registry commit unaffected",
                  file=sys.stderr)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Timestamp parsing (registry ISO format)
# ---------------------------------------------------------------------------

def _parse_iso(ctime_iso: str) -> datetime:
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# Task 5 perf item (SPEC §12): transcript-tail readers (native peek,
# transcript_limit_scan) only ever want a bounded trailing slice -- on a
# multi-hundred-MB transcript a whole-file read would be wasteful, and a
# 64KB trailing window covers every real call site.
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


# Post-testing wave, item 1c (stress-report Finding 1, zombie-escape hatch):
# how long a "working" pre-claim (session_id=None) is allowed to sit before
# a recompute stops treating it as a real in-flight dispatch and demotes it
# to "dead" instead. Every real dispatch path (cmd_spawn/cmd_send/
# cmd_respawn via dispatch_bg) stamps the real sid synchronously -- so a
# claim still unstamped after ten minutes did not just lose a race, it lost
# its launcher (the `fleet` CLI process itself crashed, was killed, or lost
# power between the pre-claim write and the post-dispatch commit).
LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0


def _launch_claim_expired(last_activity_iso) -> bool:
    """True iff a "working" pre-claim's (session_id=None) last_activity is older
    than LAUNCH_CLAIM_MAX_AGE_SECONDS (or is missing/unparseable -- treated
    as NOT expired, matching the pre-fix behavior of never demoting when
    there's no age information to go on). Shared by the native recompute
    (`recompute_worker_native`, `_dispatch_grace_active`) and cmd_kill's
    own launch-in-flight guard."""
    if not last_activity_iso:
        return False
    try:
        age = (datetime.now(timezone.utc) - _parse_iso(last_activity_iso)).total_seconds()
    except (ValueError, TypeError):
        return False
    return age > LAUNCH_CLAIM_MAX_AGE_SECONDS


# ---------------------------------------------------------------------------
# Stream-jsonl parsing (SPEC §6, §5 peek/result rows)
# ---------------------------------------------------------------------------

def _truncate(text, limit) -> str:
    text = text if isinstance(text, str) else str(text)
    return text if len(text) <= limit else text[:limit] + "..."


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


def compose_prompt(name: str, cwd, task: str, sid: str | None, journal_path=None) -> tuple[str, Path | None]:
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

    M-B T4: sid=None (a fresh native spawn has no sid until join -- the
    pre-claim record's session_id is still None at compose time) skips the
    mailbox claim entirely -- there is no <sid>.md to claim yet, only
    <name>.md could exist and that channel is not wired for pre-claim
    spawns -- and returns (prompt, None), matching the no-mail shape.
    """
    journal_target = (journals_dir() / f"{name}.md").as_posix()
    parts = [_PREAMBLE_TEMPLATE.format(name=name, cwd=cwd, journal_target=journal_target)]

    claim = None
    if sid is not None:
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
# Claude executable resolution + worker environment (shared by dispatch_bg).
# ---------------------------------------------------------------------------

class ClaudeNotFoundError(Exception):
    """Raised when the `claude` executable cannot be resolved on PATH."""


def resolve_claude_executable(which=shutil.which) -> str:
    """Resolve the real claude executable (claude.cmd/claude.exe on Windows)
    via shutil.which -- subprocess.run needs the concrete path, not the bare
    name."""
    exe = which("claude")
    if not exe:
        raise ClaudeNotFoundError(
            "claude executable not found on PATH (checked via shutil.which('claude'); "
            "expected claude.cmd or claude.exe on this machine)"
        )
    return exe


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


def _native_cumulative_tokens(name: str) -> int:
    """Sum input_tokens+output_tokens across every kind=="result" outcome
    record for this native worker (all past sids/turns) -- the lifetime-
    cumulative token sum (native has no logs/<name>.jsonl to read), used
    by cmd_send's fork-steer path for the token_ceiling refusal check
    (Kernel 10, M-B T7). Bogus values (bool, negative, non-int) are
    skipped; missing/no records -> 0 (never None -- 0 correctly compares
    as under any positive ceiling)."""
    total = 0
    for rec in read_outcomes(name):
        if not isinstance(rec, dict) or rec.get("kind") != "result":
            continue
        for key in ("input_tokens", "output_tokens"):
            val = rec.get(key)
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                continue
            total += val
    return total


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

# A machine-readable reset instant, IF the (as-yet-unconfirmed) signal carries
# one in ISO-8601 UTC form. Best-effort only; absence -> null horizon.
_LIMIT_RESET_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


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


def find_transcript_path(name: str, sid: str):
    """Path to sid's transcript JSONL, or None. Reading
    `~/.claude/projects/*/<sid>.jsonl` is sanctioned (native-substrate.md
    "Result/cost" contract) -- read-only, never a mutation.

    Prefers the `transcript_path` the Stop hook captured on an EARLIER
    turn of this sid: scans read_outcomes(name, sid=sid) newest-first (it
    already merges the name-keyed file with the sid-keyed fallback file --
    see _fast_completion_sid's docstring for why that fallback file can
    exist) for the latest record whose transcript_path is set and still
    exists. A tombstone record carries transcript_path=None and is skipped
    naturally by the truthiness check -- it is never mistaken for a path
    donor. `name` may be None (a caller with only a sid on hand) -- the
    outcome-store lookup is skipped entirely in that case, falling straight
    to the glob below.

    Falls back to globbing every project dir for `<sid>.jsonl` -- the ONLY
    path available for a sid whose limit-walled turn fired no Stop hook at
    all (G11: a limit wall is silent, no outcome record exists yet). When
    the same sid shows up under more than one project dir (a worktree
    moved, or a stale duplicate left behind), the candidate with the
    freshest `st_mtime` wins (T6 fix wave, High finding) -- NOT the
    lexicographically-first path string, which is pure alphabetical
    accident of the project-dir name and has no relationship to which
    copy is actually current. A candidate whose `stat()` itself raises
    OSError is skipped from the mtime comparison (never crashes the
    lookup); if every candidate is unstatable (or ties), falls back to
    `sorted()[0]` for determinism. None if nothing exists either way."""
    if not sid:
        return None
    if name:
        for rec in reversed(read_outcomes(name, sid=sid)):
            tp = rec.get("transcript_path")
            if tp and Path(tp).exists():
                return Path(tp)
    try:
        candidates = sorted(Path.home().glob(f".claude/projects/*/{sid}.jsonl"))
    except OSError:
        return None
    if not candidates:
        return None
    statable = []
    for c in candidates:
        try:
            statable.append((c.stat().st_mtime, c))
        except OSError:
            continue
    if statable:
        return max(statable, key=lambda pair: pair[0])[1]
    return candidates[0]


def transcript_limit_scan(sid: str, transcript_path=None):
    """(is_limit, reset_at, kind) from sid's transcript tail (G11 / Known
    hazards: a rate-limit 429 fires NO Stop hook and leaves the roster
    looking like a healthy idle/working entry -- the only sanctioned-
    surface evidence is a synthetic 429 assistant record inside the
    transcript itself).

    A record is limit-shaped IFF it is a parseable JSON object with
    `isApiErrorMessage` truthy AND (`apiErrorStatus == 429` OR
    `error == "rate_limit"`) -- the structured gate observed verbatim in
    the G7 evidence. Structured gate ONLY: conversation TEXT about rate
    limits, an upstream MCP 429, or a disk-quota EDQUOT must never park
    (mirrors the legacy UL1 stderr classifier's own load-bearing
    negatives, TestFix2, ported here for the transcript-tail path).

    Scans the tail window (`_read_tail_lines` -- perf: bounded bytes, no
    whole-file parse) newest-first, first match wins. Horizon/kind reuse
    `_parse_limit_signal` verbatim against the record's
    `message.content[].text` -- the observed real signal carries a
    LOCAL-format time, not ISO, so reset_at is usually None (park with an
    unknown horizon; `resume-limited --force-now` is the realistic
    recovery). Never raises: a missing/unreadable transcript or an
    unparseable line both fall through to (False, None, None).

    transcript_path may be given directly (the discriminator's own call
    site resolves it once via find_transcript_path(name, sid) and hands
    it in here, since this function only has a sid to work with); when
    omitted, falls back to find_transcript_path(None, sid) -- the
    sid-glob path only, since there is no name to key an outcome-store
    lookup on from here.

    Newest-first scanning discipline (T6 fix wave C2): the tail is walked
    backward looking for the FIRST record that is either API-error-shaped
    (`isApiErrorMessage` truthy) or substantive (type assistant/user with
    real message content) -- bookkeeping records (attachment/system/
    summary types, or anything with neither signal) are transparently
    skipped. Once that first qualifying record is found, it is
    authoritative: limit-shaped -> park; anything else -> (False, ...)
    immediately, WITHOUT walking further back. A stale older 429 sitting
    behind a newer, non-matching error (e.g. a 529) or behind ordinary
    newer chatter must never win -- the wall is only the reason for
    silence if it is the LAST substantive thing that happened.

    Never raises (T6 fix wave C1): the ENTIRE transcript access path --
    path resolution, the existence check, the open + tail read -- is
    wrapped in try/except OSError. `Path.exists()` only swallows a narrow
    allowlist of errno/winerror values and re-raises everything else
    (notably ERROR_SHARING_VIOLATION / winerror 32, the ordinary Windows
    error for "another process has this file open" -- ourselves, mid
    --bg write, easily included); a missing/unreadable/locked transcript
    or an unparseable line all fall through to (False, None, None)."""
    try:
        path = Path(transcript_path) if transcript_path else find_transcript_path(None, sid)
        if path is None or not path.exists():
            return False, None, None
        lines = _read_tail_lines(path)
    except OSError:
        return False, None, None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        is_error = bool(rec.get("isApiErrorMessage"))
        if not is_error and not _is_substantive_transcript_record(rec):
            continue  # bookkeeping record -- keep walking backward
        if is_error and (rec.get("apiErrorStatus") == 429 or rec.get("error") == "rate_limit"):
            msg = rec.get("message") or {}
            parts = [c.get("text", "") for c in (msg.get("content") or [])
                     if isinstance(c, dict) and c.get("type") == "text"]
            reset_at, kind = _parse_limit_signal("\n".join(parts))
            return True, reset_at, kind
        # First qualifying (error-shaped or substantive) record does not
        # match the limit shape -- it is the authoritative "last thing
        # that happened" and the scan stops here, never mind an older
        # stale wall further back.
        return False, None, None
    return False, None, None


def _is_substantive_transcript_record(rec: dict) -> bool:
    """True iff rec is a type assistant/user transcript record carrying
    real message content (non-empty text, or a tool_use/tool_result/image
    part) -- as opposed to bookkeeping records (attachment/system/summary
    types, or an assistant/user record with empty/absent content).
    Used by transcript_limit_scan's newest-first stopping discipline
    (T6 fix wave C2)."""
    if rec.get("type") not in ("assistant", "user"):
        return False
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return True
                if part.get("type") in ("tool_use", "tool_result", "image"):
                    return True
            elif isinstance(part, str) and part.strip():
                return True
    return False


# ---------------------------------------------------------------------------
# Native outcome discriminator (M-B T5): recompute_worker_native replaces
# PID probing for dispatch_kind:"bg" records -- there is no OS pid to probe,
# liveness comes from the roster (joined by sid) plus the Stop-hook outcome
# store. `_limit_scan_hook` is a module-level seam (transcript_limit_scan,
# installed below, T6) so the no-fresh-outcome branch can resolve to
# `limited` instead of always falling to `dead-suspected`.
# ---------------------------------------------------------------------------

_limit_scan_hook = transcript_limit_scan  # T6: rehomed to the transcript-tail scan

NATIVE_TERMINAL_STATUSES = {"idle", "dead", "dead-suspected", "limited",
                            "over_ceiling", "interrupted"}
# dead-suspected is deliberately NOT sticky -- it is a verdict, not a state,
# re-evaluated every recompute so a late-arriving outcome record can flip it
# back to idle (task-5-brief.md, "Fix the sticky-guard logic").
_NATIVE_STICKY = ("dead", "over_budget", "over_ceiling", "limited",
                  "interrupted", "attached")


def _dispatch_grace_active(record: dict) -> bool:
    """Live finding 2026-07-16 (FLEET_LIVE pin suite RED 3/6): a freshly
    dispatched --bg session's roster entry carries STATE ONLY
    ({'state':'working'}, no `status`, no `pid`) for its first seconds --
    `status`+`pid` appear only once the process attaches (empirically
    confirmed: the same entry later showed status:'idle' + pid and the
    outcome landed PIN-OK). The contract's field-presence rule reads
    state-only as dead, so without a grace window the no-outcome
    investigation verdicted a healthy 1.5-second-old worker dead-suspected
    and `fleet wait` (dead-suspected is NATIVE_TERMINAL) returned
    instantly.

    Same principle as the sid=None dispatch-in-flight guard, and
    deliberately the SAME window (`LAUNCH_CLAIM_MAX_AGE_SECONDS`, via
    `_launch_claim_expired`): both cases are "the launch machinery is
    still getting this session onto its feet -- never demote on absent
    evidence inside that budget," and one shared constant beats a second
    magic number. Anchored on `last_dispatch_at` (falling back to
    `created`, which every record carries) -- the same stamp every
    dispatch/steer/resume refreshes. A genuinely dead-at-birth session
    still surfaces dead-suspected once the window lapses; that verdict is
    advisory-only (never auto-respawned), so a delayed true-positive is
    cheap where the 1.5s false-positive broke `fleet wait` and the pin
    suite. Missing/unparseable anchor => grace stays active (the
    never-demote-without-age-information rule `_launch_claim_expired`
    already implements)."""
    anchor = record.get("last_dispatch_at") or record.get("created")
    return not _launch_claim_expired(anchor)


def _investigate_no_outcome(name: str, record: dict, updated: dict) -> dict:
    """No fresh outcome record for the current sid: limit wall (silent,
    G11), startup transient, or genuinely dead. Scans the transcript tail
    via `_limit_scan_hook` (module-level seam, `transcript_limit_scan` in
    production, swappable in tests); limit-shaped -> park `limited` (never
    auto-respawned before the horizon); else, within the dispatch grace
    window (`_dispatch_grace_active` -- the state-only startup transient,
    or an outcome that simply hasn't flushed yet) -> stay `working`; else
    -> `dead-suspected` (surfaced, never auto-respawned, re-evaluated
    every recompute). The grace check lives HERE, once, so both of
    `recompute_worker_native`'s call sites (roster-idle and
    roster-dead-or-gone) share it rather than duplicating the window.

    Resolves the transcript path itself via find_transcript_path(name,
    sid) -- the record may live under either the outcome store's NAME key
    or its sid-fallback key (see find_transcript_path's docstring) -- and
    hands sid + the resolved path to the hook, so transcript_limit_scan's
    own signature can stay (sid, transcript_path=None) as documented."""
    scan = _limit_scan_hook
    if scan is not None:
        sid = record.get("session_id")
        path = find_transcript_path(name, sid)
        is_limit, reset_at, kind = scan(sid, transcript_path=path)
        if is_limit:
            updated["status"] = "limited"
            updated["limit_reset_at"] = reset_at
            updated["limit_kind"] = kind
            return updated
    if _dispatch_grace_active(record):
        updated["status"] = "working"
        return updated
    updated["status"] = "dead-suspected"
    return updated


def recompute_worker_native(name: str, record: dict, roster_entries: list) -> dict:
    """Verdict engine for dispatch_kind:"bg" records (task-5-brief.md,
    binding verdict order):

    1. Sticky statuses (`_NATIVE_STICKY`) pass through unchanged.
    2. `session_id is None` (dispatch in flight): stay `working` while the
       pre-claim hasn't aged past `_launch_claim_expired`, else `dead`.
    3. Roster entry present and live (carries `status` or `pid` -- `state`
       alone is never live, contract field-presence table): `busy`/
       `waiting` -> `working` (`waiting` also flags `waiting_for_permission`
       for `_worker_flags`); `idle` -> fresh-outcome check against
       `last_dispatch_at` (falls back to `created`) -- fresh -> `idle`,
       else -> investigate.
    4. Roster entry present but dead (`state`-only), or roster-gone
       entirely: same fresh-outcome check as the idle branch above (covers
       `stopped`/`failed`/`done`-reaped).

    Both no-outcome paths route through `_investigate_no_outcome`, which
    (live finding 2026-07-16) holds the verdict at `working` while the
    dispatch grace window is active -- a freshly dispatched session's
    roster entry is state-only for its first seconds, which is
    indistinguishable from dead by field presence alone.

    Anchoring the fresh-outcome check on `last_dispatch_at` (never on the
    outcome record's mere presence) is what stops a dead predecessor's
    outcome record -- or this session's OWN prior turn's outcome record --
    from vouching for the current turn (`has_fresh_outcome` filters by sid
    AND timestamp)."""
    updated = dict(record)
    updated.pop("waiting_for_permission", None)

    status = record.get("status")
    if status in _NATIVE_STICKY:
        updated["status"] = status
        return updated

    sid = record.get("session_id")
    if sid is None:
        if not _launch_claim_expired(record.get("last_activity")):
            updated["status"] = "working"
        else:
            updated["status"] = "dead"
        return updated

    since = record.get("last_dispatch_at") or record.get("created")
    entry = _roster_entry_for(roster_entries, sid)
    live = entry is not None and ("status" in entry or "pid" in entry)
    if live:
        rstatus = entry.get("status")
        if rstatus in ("busy", "waiting"):
            updated["status"] = "working"
            if rstatus == "waiting":
                updated["waiting_for_permission"] = True
            return updated
        # idle: the turn ended -- did the Stop hook record an outcome for
        # THIS sid at or after this dispatch began?
        if has_fresh_outcome(name, sid, since):
            updated["status"] = "idle"
            return updated
        return _investigate_no_outcome(name, record, updated)

    # Roster entry is dead (state-only) or the sid is gone from the roster
    # entirely -- same fresh-outcome test as the idle branch.
    if has_fresh_outcome(name, sid, since):
        updated["status"] = "idle"
        return updated
    return _investigate_no_outcome(name, record, updated)


def native_epoch_suspicious(roster_ok: bool, entries: list, workers: dict) -> bool:
    """G9 epoch-freeze predicate (mirrors supervisor_epoch_check): the
    roster fetch failed, OR it came back empty while some native worker's
    own last-committed record still says `working` with a real sid -- a
    fresh daemon boot (or a transient CLI failure shaped like an empty
    list) must never be read as "everything died". Callers freeze: no
    native record is recomputed or written while this is true."""
    if not roster_ok:
        return True
    if entries:
        return False
    return any(
        is_native(rec) and rec.get("status") == "working" and rec.get("session_id")
        for rec in workers.values() if isinstance(rec, dict)
    )


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
    # M-B T5: dead-suspected is a native-only, non-sticky verdict -- surface
    # it as an operator prompt to look, never an auto-respawn trigger.
    if record["status"] == "dead-suspected":
        flags.append("investigate: no outcome record")
    # M-B T5: recompute_worker_native sets this transient field (never part
    # of new_worker_record's base schema) when the roster reports the native
    # session paused on a permission prompt.
    if record.get("waiting_for_permission"):
        flags.append("waiting-permission")
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
    # M-B T9 (spec §5.1.2): archived_at survives on a tombstoned record
    # regardless of its (frozen) status -- flag it distinctly rather than
    # letting it masquerade as a live idle/dead/interrupted row.
    if record.get("archived_at"):
        flags.append("archived")
    return flags


# ---------------------------------------------------------------------------
# Phase 1.6 terminal surface (docs/specs/terminal-surface.md): the single
# read-only derivation every view consumes -- statusline, `status --json
# --stale-ok`, the SessionStart hook, and (later) watchtower / web UI.
#
# D1: no fleet_lock, no liveness probe, no write. This runs on a
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


def status_snapshot(now=None, include_archived: bool = False) -> dict:
    """Read-only fleet snapshot. See the module comment above for why this
    exists alongside cmd_status rather than reusing it.

    M-B T9 (spec §5.1.2): rows whose `archived_at` is set are EXCLUDED by
    default (a tombstoned worker is history, not a live-fleet row) --
    `include_archived=True` (wired from `fleet status --all`) puts them
    back, each carrying its own `archived_at` timestamp so the caller can
    flag it distinctly."""
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
        if rec.get("archived_at") and not include_archived:
            continue
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
            # T5 fix wave (Minor: snapshot cost render): additive field,
            # file-only derivation (no roster fetch -- this view never
            # probes, per CLAUDE.md's view-isolation rule) so
            # _print_snapshot_table can render native rows' cost as "-"
            # like _print_status_table's G3 convention, without needing
            # is_native's full record shape.
            "dispatch_kind": rec.get("dispatch_kind"),
            "archived_at": rec.get("archived_at"),
        })

    snap["workers"] = rows
    snap["totals"] = {
        "workers": len(rows),
        "mail": total_mail,
        "cost_usd": round(total_cost, 6),
        "by_status": by_status,
    }
    return snap


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
    dispatch (dispatch_bg's --settings default just points at a
    nonexistent path) and `claude` would silently ignore the bad
    --settings value in print mode (SPEC §7) -- fleet hooks would simply
    never fire, with no error anywhere."""
    if not instance_settings_path().exists():
        raise FleetCliError(
            f"worker settings instance missing ({instance_settings_path()}) -- run `fleet init` first"
        )


# Post-testing wave, item 1b (stress-report Finding 1, CRITICAL): how many
# times / how long cmd_spawn, cmd_send's fork-steer path, and cmd_respawn
# retry their post-dispatch commit lock (the one that stamps the real
# sid into the registry) before giving up. Deliberately several times
# the ordinary LOCK_TIMEOUT_SECONDS (5.0s): by the time this lock is
# reached, dispatch_bg() has ALREADY succeeded -- a real, billable, running
# `claude` session exists and its sid is known -- so losing this race
# forever would strand it as a permanent zombie registry record (status=
# "working"/session_id=None, which every recovery lever historically refused
# to touch; item 1c's LAUNCH_CLAIM_MAX_AGE_SECONDS now bounds that too, but
# retrying hard here is the first, much faster line of defense). Total
# backoff across all attempts is ~30s (each attempt itself may also spend
# up to LOCK_TIMEOUT_SECONDS acquiring, so worst case is noticeably more).
LAUNCH_COMMIT_MAX_ATTEMPTS = 6
LAUNCH_COMMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 8.0, 7.0)


def _commit_launched_turn(commit_fn, sleep=time.sleep) -> bool:
    """Run `commit_fn()` -- a zero-argument callable that itself acquires
    `fleet_lock()` and performs a post-dispatch registry commit (stamping
    session_id/native_short_id/turns/last_activity, matching cmd_spawn/
    cmd_send/cmd_respawn's own shape) -- retrying on FleetLockTimeout with
    backoff (LAUNCH_COMMIT_BACKOFF_SECONDS) up to LAUNCH_COMMIT_MAX_ATTEMPTS
    times.

    Returns True once `commit_fn()` completes without raising
    FleetLockTimeout. Returns False if every attempt timed out -- the
    caller (cmd_spawn/cmd_send/cmd_respawn) MUST NOT abandon the
    already-dispatched session on a False return: it must still surface the
    dispatch as real (raising raw would tempt an operator into retrying the
    same `fleet` subcommand, which would double-dispatch a SECOND live
    session on top of the one already running) and instead call
    `_report_stranded_native_turn` for a loud, actionable warning plus a
    best-effort event.

    Debt roll-up item 3: a NON-lock OSError out of `commit_fn()` (ENOSPC
    on save_registry, a Windows PermissionError from a concurrent reader
    holding fleet.json open, ...) is handled the same way, cross-cutting
    at this helper so every call site is covered at once: retried with
    the same backoff (Windows sharing violations are transient), and on
    exhaustion reported to stderr and folded into the same False return
    -- the turn is just as launched, and letting the OSError escape raw
    would read as a failed launch and tempt the same double-launch retry.

    CONTRACT (fix-wave F1): because OSError now retries the WHOLE
    commit_fn, a commit_fn must not raise OSError after save_registry has
    made its mutation durable -- a retry would re-run a non-idempotent
    body against already-committed state (fork-steer's reload lands in
    its orphaned branch). Concretely: post-save event appends inside a commit_fn go
    through `_append_event_quiet`, and mailbox migration is best-effort
    by construction (_migrate_residual_mailbox swallows OSError). Every
    step before save_registry is safely retryable -- save itself is
    atomic (temp file + os.replace), so a failed save left nothing
    committed."""
    for attempt in range(LAUNCH_COMMIT_MAX_ATTEMPTS):
        try:
            commit_fn()
            return True
        except (FleetLockTimeout, OSError) as exc:
            if attempt == LAUNCH_COMMIT_MAX_ATTEMPTS - 1:
                if not isinstance(exc, FleetLockTimeout):
                    print(f"fleet: post-launch registry commit raised {exc!r} "
                          "on the final attempt", file=sys.stderr)
                return False
            sleep(LAUNCH_COMMIT_BACKOFF_SECONDS[attempt])
    return False


def _report_stranded_native_turn(name: str, sid: str, short_id: str) -> None:
    """T4 fix wave (Critical C2): stranded-dispatch report for cmd_spawn's
    post-dispatch stamp lock -- reached only after
    dispatch_bg already returned a real, joined sid (a live `claude --bg`
    session genuinely exists) but every `_commit_launched_turn` retry
    timed out acquiring fleet_lock() to stamp it into the registry.

    There is no OS pid fallback here -- native
    sids come entirely from `claude` itself, never fleet -- so `sid`/
    `short_id` are the ONLY recovery handles that exist anywhere once this
    stack frame unwinds. Never fail silently: print a loud, actionable
    stderr message and best-effort append an event. Deliberately does not
    raise -- the caller (cmd_spawn) reports this as a failure via its own
    nonzero return, but must NOT let the exception escape raw (that would
    read as an ordinary dispatch failure and could tempt a retry, which
    would double-dispatch a second live session onto the same name)."""
    print(
        f"fleet: CRITICAL: {name}: native session {sid} (short id {short_id}) "
        "was dispatched and joined but the registry stamp failed after "
        f"{LAUNCH_COMMIT_MAX_ATTEMPTS} lock-acquisition attempts -- the "
        "record is stuck at status=working/session_id=null (the native "
        "pre-claim state). It will auto-demote to dead after "
        f"LAUNCH_CLAIM_MAX_AGE_SECONDS ({LAUNCH_CLAIM_MAX_AGE_SECONDS:.0f}s) "
        "of inactivity -- DO NOT re-run `fleet spawn` for this name before "
        "then, that would double-dispatch a second live session. Recover "
        f"by hand-editing state/fleet.json to set session_id={sid!r} and "
        f"native_short_id={short_id!r} directly, or track the session via "
        "`claude agents` in the meantime.",
        file=sys.stderr,
    )
    try:
        append_event("turn_commit_failed", name, session_id=sid, native_short_id=short_id)
    except OSError:
        pass


def _short_id_from_notes(exc: BaseException):
    """T4 fix wave (Ctrl-C short-id loss): dispatch_bg's join-phase wrapper
    stashes `fleet_short_id=<id>` onto an escaping exception's __notes__
    (BaseException.add_note, 3.11+) when a short id is known at that
    point. Pulls it back out, or returns None if absent/malformed."""
    for note in getattr(exc, "__notes__", None) or ():
        if isinstance(note, str) and note.startswith("fleet_short_id="):
            return note.partition("=")[2] or None
    return None


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
    back to a bare `py`/`python3` on PATH).

    N1 (re-review, MED): the home guards are evaluated BEFORE anything is
    written. Previously the marker (and settings) were stamped first and
    `_install_autoclean_task`'s marker-mismatch guard then compared against
    a marker this very invocation had just repointed -- it could never fire
    on the real init path, and a worktree `fleet init` left the machine's
    SessionStart/statusline reading the worktree's empty registry (a
    dangling marker once the worktree was deleted). Now: with --autoclean,
    a guard problem refuses the WHOLE init before any write; without it,
    the worktree-local settings render (legitimate for testing) but the
    GLOBAL marker stamp is skipped, loudly. --force overrides both."""
    marker_problems = _marker_guard_problems()
    force = getattr(args, "force", False)
    if getattr(args, "autoclean", False) and marker_problems and not force:
        raise FleetCliError(
            "fleet init --autoclean refused before writing anything (N1): "
            + "; ".join(marker_problems)
            + " -- run from the canonical fleet home, or rerun with --force")

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

    if marker_problems and not force:
        marker_line = "NOT stamped (N1): " + "; ".join(marker_problems) + " (--force to override)"
    else:
        _write_fleet_home_marker()
        marker_line = str(fleet_home_marker_path())

    print(f"fleet init: wrote {instance_path}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    print(f"  fleet home:  {Path(FLEET_HOME).resolve().as_posix()}")
    print(f"  marker:      {marker_line}")

    if getattr(args, "statusline", False):
        _install_statusline(force=getattr(args, "force", False),
                            chain=getattr(args, "chain", False))
    if getattr(args, "autoclean", False):
        _install_autoclean_task(getattr(args, "autoclean_interval_hours", None),
                                force=getattr(args, "force", False))
    if getattr(args, "autoclean_remove", False):
        _remove_autoclean_task()
    return 0


def cmd_spawn(args, run=subprocess.run, which=shutil.which, sleep=time.sleep,
              clock=time.monotonic) -> int:
    """`fleet spawn <name> --dir <path> --task <text|@file> [--mode ...]
    [--model m] [--category c] [--token-ceiling n]` (SPEC §5 spawn row,
    M-B T4: native `--bg` dispatch replaces detached Popen).

    Launch contract (M-B spec §3): pre-claim a registry record under
    fleet_lock with session_id=None (a launch-in-flight claim --
    _launch_claim_expired bounds it via last_activity), dispatch
    outside the lock via dispatch_bg, then re-lock to stamp the real sid/
    short id, OR roll back -- EXCEPT when a fast worker already finished
    (an outcome record for this name newer than the pre-claim) even though
    the roster join itself expired: that commits as "idle" with the
    outcome's sid instead of rolling back a completed task (never lose a
    finished turn to a slow/missed roster join).

    Registry mutation (create the record) and event-append happen together
    inside one fleet_lock() (F4): every event this module appends is
    written while the registry lock for that same operation is held, so
    concurrent `fleet` invocations never interleave events with the
    registry state they describe.

    SPEC §14: refuses before any mutation if the worker-settings instance
    hasn't been rendered yet (_require_instance_settings) -- `fleet init`
    must run once per machine before the first spawn.

    G3: USD budgets are refused outright for native dispatch (`--bg` does
    not carry cost information) -- `--token-ceiling` is the only fleet-side
    cap available; `--max-budget-usd` stays in the parser only because
    respawn/legacy paths still reference the attr.

    G6: the sid-keyed ceiling file is written AFTER the sid is known (the
    real sid does not exist before roster join), a seconds-wide gap versus
    the legacy pre-launch write -- accepted; the Stop hook has no ceiling
    signal for that narrow window and falls back to its default
    block-on-mail behavior, never a launch failure.

    `clock` is injectable (forwarded to dispatch_bg, T4 addition beyond the
    brief's stated signature) so join-expiry tests never pay the real
    NATIVE_JOIN_VERIFY_SECONDS wall-clock wait -- see task-4-report.md
    deviations.

    T4 fix wave (Critical C2): the post-dispatch stamp lock (after
    dispatch_bg already returned a real, joined sid) is wrapped in
    `_commit_launched_turn`'s retry+backoff, same as the legacy launch
    path -- an ordinary FleetLockTimeout there must not stand a permanent
    chance of stranding an already-live session. On exhaustion, this
    returns nonzero (unlike the legacy path's rc==0: native has no OS pid
    fallback, so the operator-facing signal here has to be louder) after
    `_report_stranded_native_turn` prints the sid/short_id needed to
    recover by hand -- it does NOT pop the pre-claim record (a live
    session exists; popping would orphan it beyond even the stranded-turn
    recovery instructions) and does NOT raise raw.
    """
    _require_instance_settings()

    cwd = Path(args.dir)
    if not cwd.is_dir():
        raise FleetCliError(f"--dir does not exist or is not a directory: {args.dir}")

    if getattr(args, "max_budget_usd", None) is not None:
        raise FleetCliError(
            "no USD budget under native dispatch (contract G3) -- use --token-ceiling"
        )

    task = _read_task_arg(args.task)

    with fleet_lock():
        data = load_registry()
        validate_name(args.name, existing=data["workers"].keys())
        record = new_worker_record(
            None, cwd, task, args.mode, model=args.model,
            setting_sources=args.setting_sources, token_ceiling=args.token_ceiling,
            spawned_by=current_caller_session(),
            dispatch_kind="bg", category=args.category)
        record["last_dispatch_at"] = now_iso()
        data["workers"][args.name] = record
        save_registry(data)
        append_event("spawned", args.name, cwd=str(cwd), mode=args.mode)

    pre_claim_at = record["last_dispatch_at"]

    # sid=None (pre-claim, no real sid exists yet) -- compose_prompt skips
    # the mailbox claim entirely and always returns a None claim here.
    prompt, _claim = compose_prompt(args.name, cwd, task, None)

    try:
        result = dispatch_bg(
            args.name, cwd, prompt, args.mode, model=args.model,
            category=args.category, hint=task,
            setting_sources=record.get("setting_sources"),
            run=run, which=which, sleep=sleep, clock=clock,
        )
    except NativeDispatchError as exc:
        # T4 fix wave (Critical C1): forward the short id the exception
        # carries (join-expiry raises always know it) so the fast-
        # completion scan can also find the Stop hook's sid-keyed
        # fallback file, not just a name-keyed one that production never
        # produces during this exact race (see _fast_completion_sid).
        fast_sid = _fast_completion_sid(args.name, pre_claim_at,
                                        short_id=getattr(exc, "short_id", None))
        if fast_sid is not None:
            with fleet_lock():
                data = load_registry()
                rec = data["workers"].get(args.name)
                if rec is not None and rec.get("session_id") is None:
                    rec["session_id"] = fast_sid
                    rec["native_short_id"] = fast_sid.partition("-")[0] or fast_sid[:8]
                    rec["status"] = "idle"
                    rec["turns"] = 1
                    rec["last_activity"] = now_iso()
                    save_registry(data)
                    # Fix-wave N2: post-save, same class as the retried
                    # commit_fns -- a raw OSError here crashed the CLI after
                    # the commit was durable, skipping the ceiling write and
                    # success line (committed fast-completion read as a
                    # failed spawn).
                    _append_event_quiet("turn_started", args.name, session_id=fast_sid)
            _write_ceiling_file(fast_sid, record.get("token_ceiling"))
            print(f"{args.name} {fast_sid} (native bg, fast completion before join)")
            return 0

        # DOA rollback: re-lock, pop the pre-claim ONLY if still unclaimed
        # (session_id is None) -- a concurrent mutation (e.g. a fast_sid
        # commit that raced in from elsewhere) must never be clobbered.
        # T4 fix wave (Minor): the spawn_failed event is appended ONLY
        # when the pop actually happened -- previously unconditional, so a
        # concurrently-stamped (still-alive) worker got a misleading
        # "spawn_failed" event in its own audit trail even though nothing
        # failed.
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(args.name)
            if rec is not None and rec.get("session_id") is None:
                data["workers"].pop(args.name, None)
                save_registry(data)
                append_event("spawn_failed", args.name, error=str(exc))
        raise FleetCliError(f"{args.name}: native spawn failed -- {exc}") from exc
    except BaseException as exc:
        # T4 deviation, carrying forward a documented precedent (legacy
        # Task-4-verdict re-review Fix 2): a Ctrl-C or any other unexpected
        # exception escaping dispatch_bg must not leave a ghost
        # "working"+session_id=None pre-claim behind, pinned forever by
        # the recompute launch-in-flight guard. Same guarded-pop shape
        # as the NativeDispatchError branch above; re-raised verbatim
        # (not wrapped in FleetCliError) so e.g. KeyboardInterrupt still
        # propagates as itself.
        #
        # T4 fix wave (Ctrl-C short-id loss): dispatch_bg's join-phase
        # wrapper stashes the short id onto the exception's __notes__ when
        # a live session was already dispatched before the interrupt --
        # recover it here so the spawn_failed event (an operator's only
        # trace of the orphaned session once this process exits) carries
        # it, instead of an empty str(KeyboardInterrupt()).
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(args.name)
            if rec is not None and rec.get("session_id") is None:
                data["workers"].pop(args.name, None)
                save_registry(data)
                append_event("spawn_failed", args.name, error=str(exc),
                            short_id=_short_id_from_notes(exc))
        raise

    sid = result["session_id"]
    short_id = result["short_id"]

    def _commit_native_stamp():
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(args.name)
            # T4 fix wave (Minor M1, event-append symmetry): append_event
            # now lives inside the same `if rec is not None:` guard as the
            # mutation, matching the fast-completion commit block above --
            # previously this fired unconditionally even if a concurrent
            # kill/clean had already removed the record in the inter-lock
            # gap.
            if rec is not None:
                rec["session_id"] = sid
                rec["native_short_id"] = short_id
                rec["status"] = "working"
                rec["turns"] = 1
                rec["last_activity"] = now_iso()
                save_registry(data)
                _append_event_quiet("turn_started", args.name, session_id=sid)

    if not _commit_launched_turn(_commit_native_stamp, sleep=sleep):
        _report_stranded_native_turn(args.name, sid, short_id)
        return 1

    # G6: sid-keyed ceiling file written post-join by necessity (the sid
    # does not exist before now) -- see docstring.
    _write_ceiling_file(sid, record.get("token_ceiling"))

    # Phase1 kernel 5: echo the effective model/config at launch so a costly
    # model (or an inherited CLAUDE_CODE_SUBAGENT_MODEL) is visible up front,
    # not discovered on the bill.
    model_line = f"model: {args.model or '(claude default)'}"
    subagent_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if subagent_model:
        model_line += f"; CLAUDE_CODE_SUBAGENT_MODEL={subagent_model}"
    print(model_line)

    print(f"{args.name} {sid} (native bg, short id {short_id})")
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


def cmd_status(args) -> int:
    """`fleet status [name]` (SPEC §5 status row): recompute liveness/cost
    for the named worker (or all workers), persist any transitions, print a
    compact table with anomaly flags.

    Shape (stress-report Finding 1 / F4 doctrine): snapshot the named
    records under one fleet_lock, release it, run the roster fetch and
    every recompute with NO lock held, then re-acquire once to merge
    verdicts -- but only for records that still match their pre-probe
    snapshot exactly (a concurrent command that mutated a record while the
    lock was released is left alone, its own write respected, rather than
    being clobbered by a verdict computed against now-stale data)."""
    # Phase 1.6 (D1/D2): --stale-ok is the probe-free, lock-free, write-free
    # read path every view uses. Returns last-COMMITTED status plus
    # stale_seconds; it never asserts liveness it did not probe for.
    # M-B T9 (spec §5.1.2): an explicit named query always finds its worker
    # (archived or not) -- the default-hides-archived rule only governs the
    # unfiltered bulk listing, matched via `--all`.
    include_archived = getattr(args, "all", False) or args.name is not None
    if getattr(args, "stale_ok", False):
        snap = status_snapshot(include_archived=include_archived)
        if getattr(args, "json", False):
            print(json.dumps(snap, indent=2))
        else:
            _print_snapshot_table(snap, args.name)
        return 0

    with fleet_lock():
        data = load_registry()
        requested = [args.name] if args.name else sorted(data["workers"])
        for n in requested:
            if n not in data["workers"]:
                raise FleetCliError(f"unknown worker: {n!r}")
        before_all = {n: data["workers"][n] for n in requested}
        all_workers = data["workers"]  # snapshot for the epoch check (G9)

    names = [n for n in requested if include_archived or not before_all[n].get("archived_at")]
    before = before_all

    # M-B T9: an archived native record is frozen history -- its evidence
    # files (outcomes/journal/task) have already been moved to the archive
    # dir, so recompute_worker_native would have nothing fresh to read and
    # could misfire into dead-suspected/limited. Never recompute it; just
    # carry its last-committed record forward unchanged.
    active_names = [n for n in names if not before[n].get("archived_at")]

    # ONE roster fetch per invocation, outside the lock (F4 doctrine), only
    # when a live worker is actually being asked about.
    roster_entries = []
    epoch_frozen = False
    if active_names:
        roster_ok, payload = _fetch_agents_roster()
        roster_entries = payload if roster_ok else []
        epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, all_workers)

    # Recompute every named worker's verdict with NO lock held (see
    # docstring above).
    after = {}
    for n in names:
        if n not in active_names or epoch_frozen:
            # Archived: frozen, never recomputed. Epoch-frozen (G9): roster
            # suspicious -- no record is recomputed or written this
            # invocation; display whatever is last-committed.
            after[n] = before[n]
        else:
            after[n] = recompute_worker_native(n, before[n], roster_entries)

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
            # T5 fix wave (Important I1): waiting_for_permission is
            # transient -- recomputed fresh from the roster every call,
            # never enumerated in new_worker_record's baseline schema like
            # every other optional field. Strip it from the dict compared
            # against/written to the registry so it never lands in
            # fleet.json; the printed table below still gets the full
            # (flag-included) dict via `display[n] = after[n]` so
            # `_worker_flags`'s "waiting-permission" flag keeps working.
            persisted_after = dict(after[n])
            persisted_after.pop("waiting_for_permission", None)
            if persisted_after != current:
                data["workers"][n] = persisted_after
                changed = True
                if persisted_after["status"] != current["status"]:
                    append_event("status_changed", n, old=current["status"], new=persisted_after["status"])
                    # M-B T5: a verdict landing on limited/dead-suspected
                    # also gets its own named event -- guarded on the same
                    # old!=new transition above, so a dead-suspected record
                    # that stays dead-suspected across reruns never re-fires.
                    if persisted_after["status"] == "limited":
                        append_event("limited_suspected", n,
                                    limit_reset_at=persisted_after.get("limit_reset_at"),
                                    limit_kind=persisted_after.get("limit_kind"))
                    elif persisted_after["status"] == "dead-suspected":
                        append_event("dead_suspected", n)
            display[n] = after[n]
        if changed:
            save_registry(data)

    if epoch_frozen:
        print("EPOCH: roster suspicious -- verdicts frozen (G9); rows show last-committed state")

    if getattr(args, "json", False):
        # The authoritative path has already persisted its verdicts above, so
        # re-deriving the snapshot from disk yields exactly the recomputed state.
        print(json.dumps(status_snapshot(include_archived=include_archived), indent=2))
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
        if w.get("archived_at"):
            flags.append("archived")
        # T5 fix wave (Minor: snapshot cost render): G3 says USD cost is
        # dead for native dispatch -- render "-" here too, matching
        # _print_status_table, instead of a stale/always-zero dollar
        # figure. Nativeness comes from the row's own dispatch_kind field
        # (no roster fetch -- this view is file-only, per CLAUDE.md).
        cost_s = f"{'-':>9}" if w["dispatch_kind"] == "bg" else f"{w['cost_usd']:>9.2f}"
        # A name at or past the column width must never swallow the separator.
        print(
            f"{w['name']:<20} {w['status']:<12}{w['turns']:>6}{cost_s}"
            f"{age:>9}{w['mail']:>6}  {','.join(flags) or '-'}"
        )
    print("(stale-ok: last-committed state, not probed)")


def _native_token_summary(name: str, rec: dict) -> str:
    """"tokens:in=X out=Y" from the latest outcome record for this native
    worker's current sid, or "" if there is none yet / it carries no token
    fields (G3: USD cost is refused for native dispatch, so this is the
    status table's only per-worker usage signal)."""
    sid = rec.get("session_id")
    if not sid:
        return ""
    outcome = latest_outcome(name, sid)
    if not outcome:
        return ""
    parts = []
    if outcome.get("input_tokens") is not None:
        parts.append(f"in={outcome['input_tokens']}")
    if outcome.get("output_tokens") is not None:
        parts.append(f"out={outcome['output_tokens']}")
    return "tokens:" + " ".join(parts) if parts else ""


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
        flag_list = _worker_flags(rec)
        if is_native(rec):
            # G3: USD cost is REFUTED-for-contract under native dispatch --
            # render "-", never a stale/zero dollar figure.
            cost_s = f"{'-':>9}"
            tok = _native_token_summary(n, rec)
            if tok:
                flag_list = flag_list + [tok]
        else:
            cost_s = f"{rec['cost_usd']:>9.2f}"
        flags = ",".join(flag_list) or "-"
        print(
            f"{n:<20}{rec['status']:<10}{rec['turns']:>6}{cost_s}"
            f"{mins_s:>9}{mail:>6}{attach_s:>9}  {flags}"
        )


def _render_native_peek_lines(rec: dict) -> list:
    """Rendered display lines for one substantive transcript record
    (`_is_substantive_transcript_record` already gated the caller's
    selection): assistant records emit one `[text]` line per non-empty text
    part (first 200 chars) and one `[tool] <name>` line per `tool_use` part;
    user records emit one `[user]`/`[user:meta]` line (first 120 chars,
    `isMeta` distinguishes a synthetic/hook-injected turn from a real
    operator message). Anything else renders as no lines -- the caller's
    substantive-record filter already excludes bookkeeping types, so this
    is defensive, not a real path."""
    rtype = rec.get("type")
    content = (rec.get("message") or {}).get("content")
    parts = content if isinstance(content, list) else []
    lines = []
    if rtype == "assistant":
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    lines.append(f"[text] {_truncate(text, 200)}")
            elif part.get("type") == "tool_use":
                lines.append(f"[tool] {part.get('name', '?')}")
    elif rtype == "user":
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                p.get("text", "") for p in parts
                if isinstance(p, dict) and p.get("type") == "text"
            )
        if text.strip():
            tag = "[user:meta]" if rec.get("isMeta") else "[user]"
            lines.append(f"{tag} {_truncate(text, 120)}")
    return lines


def _cmd_peek_native(name: str, sid, n: int) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_peek` (M-B T8):
    render the last `n` SUBSTANTIVE records (`_is_substantive_transcript_
    record`) from the current sid's transcript tail (`_read_tail_lines` --
    bounded bytes, works mid-turn since the daemon writes the transcript
    live). Tolerant parsing: an unparseable/non-dict line is skipped, never
    a crash (mirrors `transcript_limit_scan`'s own discipline). No sid
    (launch-in-flight) or no resolvable transcript both exit 1 with a hint
    rather than printing an empty digest that could be misread as "nothing
    happened yet"."""
    if sid is None:
        print(f"{name}: no transcript yet -- dispatch may still be in flight", file=sys.stderr)
        return 1
    path = find_transcript_path(name, sid)
    if path is None:
        print(f"{name}: no transcript found for session {sid} -- try `fleet status {name}`",
              file=sys.stderr)
        return 1
    records = []
    for line in _read_tail_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict) and _is_substantive_transcript_record(rec):
            records.append(rec)
    records = records[-n:] if n else records

    print(f"-- {name} ({sid[:8]}) --")
    if not records:
        print("(no substantive transcript records yet)")
        return 0
    for rec in records:
        for line in _render_native_peek_lines(rec):
            print(line)
    return 0


def cmd_peek(args) -> int:
    """`fleet peek <name> [-n 20]` (SPEC §5 peek row): digest of recent
    substantive transcript records via `_cmd_peek_native` -- the digest
    comes from the sid's own transcript tail (daemon-hosted sessions have
    no fleet-owned stdout log)."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]

    return _cmd_peek_native(args.name, rec.get("session_id"), args.lines)


def _cmd_result_native(name: str, sid) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_result` (M-B T8):
    the latest outcome record for the CURRENT sid (`latest_outcome` is
    already the newest-by-ts record for that sid -- no separate filter
    step is needed, its own `kind` tells the story). `kind == "result"`
    prints `result_text` alone on stdout (purity: scripts consume it) plus
    one token/model info line on stderr; any other kind (a tombstone --
    killed/interrupted/stopped) means the turn did not end with a result at
    all, and no record means nothing has completed for this sid yet (or
    the worker is dead-suspected) -- both exit 1 with a distinct reason.
    `result_text is None` (a Stop hook that wrote a null payload) is
    treated the same as "no result", never printed as an empty line with
    exit 0 -- the trap named in the T8 contract."""
    if sid is None:
        print(f"{name}: no outcome record for current session -- "
              "worker may be dead-suspected (fleet status)", file=sys.stderr)
        return 1
    outcome = latest_outcome(name, sid)
    if outcome is None:
        print(f"{name}: no outcome record for current session -- "
              "worker may be dead-suspected (fleet status)", file=sys.stderr)
        return 1
    kind = outcome.get("kind")
    text = outcome.get("result_text")
    if kind != "result" or text is None:
        print(f"{name}: last turn ended by {kind} -- no result", file=sys.stderr)
        return 1
    print(text)
    print(
        f"-- tokens in={outcome.get('input_tokens')} out={outcome.get('output_tokens')} "
        f"model={outcome.get('model')}",
        file=sys.stderr,
    )
    return 0


def cmd_result(args) -> int:
    """`fleet result <name>` (SPEC §5 result row): final result event text
    of the last completed turn, nothing else -- result text lives in the
    Stop-hook outcome store (`latest_outcome`)."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]

    return _cmd_result_native(args.name, rec.get("session_id"))


def wait_for_workers(names, mode: str = "all", timeout=None, poll_interval: float = 3.0,
                      sleep=time.sleep, clock=time.monotonic):
    """Poll registry-recomputed liveness for `names` (re-reading the
    registry each pass, so a concurrent respawn/interrupt is picked up)
    until the wait condition is met or timeout elapses.

    Returns (finished: dict[name -> final_status], pending: set[name]) --
    pending is empty iff every requested worker (mode="all") or at least one
    (mode="any") finished before the deadline.

    T9 fix wave (finding I-4a): an `archived_at`-set record is frozen
    history -- its evidence files are gone (moved into the archive dir), so
    `recompute_worker_native` would have nothing fresh to read and could
    misfire into `dead-suspected`. It never reaches recompute here; its
    last-committed (frozen) status resolves the wait immediately, exactly
    like `cmd_status`'s own "never recompute an archived native record"
    rule.
    """
    deadline = None if timeout is None else clock() + timeout
    finished: dict = {}
    pending = set(names)
    while True:
        data = load_registry()
        workers = data["workers"]

        # M-B T5: one roster fetch per poll shared by every name still
        # pending (not per-name) -- and the same epoch-freeze discipline as
        # cmd_status: a suspicious roster this poll means no verdict is
        # trusted this poll (they simply stay pending). T9: an archived
        # record never consults the roster either.
        live_pending = [n for n in pending
                        if n in workers and not workers[n].get("archived_at")]
        roster_entries = []
        epoch_frozen = False
        if live_pending:
            roster_ok, payload = _fetch_agents_roster()
            roster_entries = payload if roster_ok else []
            epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, workers)

        for n in list(pending):
            rec = workers.get(n)
            if rec is None:
                finished[n] = "dead"
                pending.discard(n)
                continue
            if rec.get("archived_at") is not None:
                finished[n] = rec.get("status")
                pending.discard(n)
                continue
            if epoch_frozen:
                continue
            status = recompute_worker_native(n, rec, roster_entries)["status"]
            if status in NATIVE_TERMINAL_STATUSES:
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


def cmd_wait(args, sleep=time.sleep, clock=time.monotonic) -> int:
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
        args.names, mode=mode, timeout=args.timeout, sleep=sleep, clock=clock,
    )

    # T5 fix wave (Minor: print-vs-persist race): the persist step below
    # re-derives each finished native worker's verdict from ITS OWN fresh
    # roster fetch, separate from the one wait_for_workers's poll loop used
    # to decide `finished` in the first place. If the two disagree (a fresh
    # outcome record lands, or the roster changes, in the narrow window
    # between them), the summary line printed below must reflect what
    # actually got persisted -- never the earlier, possibly-stale poll
    # verdict. Populated only for names the persist step actually
    # recomputed and wrote; anything else (persist skipped by an epoch
    # freeze, or `finished` itself empty) falls back to the poll verdict,
    # which is the only one that exists for it.
    persisted_status: dict = {}
    epoch_frozen = False
    if finished:
        # M-B T5: wait_for_workers already picked the terminal verdict for
        # any name in `finished` via recompute_worker_native.
        # Re-derive the same way here for the persist step, one more roster
        # fetch outside the lock (F4), so a worker that flips into
        # `limited`/`dead-suspected` gets its horizon fields and its named
        # event, exactly like cmd_status.
        # T9 fix wave (finding I-4a): an archived record is frozen history --
        # `wait_for_workers` already resolved it from its last-committed
        # status alone (no recompute), and this persist step must not
        # re-derive or overwrite it either. Without this exclusion, an
        # unconditional recompute_worker_native here would misread the
        # already-moved-away evidence files as "no fresh outcome" and demote
        # the tombstone to `dead-suspected`, appending a spurious event on
        # top of a record `cmd_status`/`cmd_clean` both treat as immutable.
        snap_workers = load_registry()["workers"]
        live_finished = [n for n in finished
                         if n in snap_workers
                         and not snap_workers[n].get("archived_at")]
        roster_entries = []
        epoch_frozen = False
        if live_finished:
            roster_ok, payload = _fetch_agents_roster()
            roster_entries = payload if roster_ok else []
            epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, snap_workers)

        changed = False
        with fleet_lock():
            data = load_registry()
            for n in finished:
                rec = data["workers"].get(n)
                if rec is None:
                    continue
                if rec.get("archived_at") is not None:
                    continue  # frozen tombstone -- never recompute/persist/event
                if epoch_frozen:
                    # G9: roster suspicious -- leave this record untouched
                    # (unwritten), same freeze as cmd_status.
                    continue
                updated = recompute_worker_native(n, rec, roster_entries)
                # T5 fix wave (I1): strip the transient waiting_for_permission
                # flag before it lands in the registry (see cmd_status for
                # the identical rationale) -- native "working" statuses
                # don't reach NATIVE_TERMINAL_STATUSES/`finished` today, but
                # guard it here too so this persist step never depends on
                # that staying true.
                persisted = dict(updated)
                persisted.pop("waiting_for_permission", None)
                data["workers"][n] = persisted
                persisted_status[n] = persisted["status"]
                changed = True
                if persisted["status"] != rec["status"]:
                    append_event("status_changed", n, old=rec["status"], new=persisted["status"])
                    if persisted["status"] == "limited":
                        append_event("limited_suspected", n,
                                    limit_reset_at=persisted.get("limit_reset_at"),
                                    limit_kind=persisted.get("limit_kind"))
                    elif persisted["status"] == "dead-suspected":
                        append_event("dead_suspected", n)
            # T9 fix wave (finding I-4a): if every finished worker this
            # invocation was either archived (skipped above) or -- in
            # principle -- otherwise unchanged, do not touch the registry
            # file at all. A wait that resolves purely against archived
            # tombstones must leave state/fleet.json byte-identical, not
            # merely value-equal after a needless rewrite.
            if changed:
                save_registry(data)

    # Summary text comes from the Stop-hook outcome store (the legacy
    # logs/<name>.jsonl pipeline is gone, pivot spec §6): the latest
    # kind=="result" outcome for the worker's current sid, else the
    # unchanged "(no result event)" placeholder.
    summary_workers = load_registry()["workers"]
    for n, status in finished.items():
        status = persisted_status.get(n, status)
        rec = summary_workers.get(n) or {}
        outcome = latest_outcome(n, rec.get("session_id")) if rec.get("session_id") else None
        summary = None
        if outcome is not None and outcome.get("kind") == "result":
            summary = outcome.get("result_text")
        if summary is None:
            summary = "(no result event)"
        print(f"{n}: {status} -- {_truncate(summary, 120)}")
    # Debt roll-up item 9 (T5-era residual): when the persist step's OWN
    # roster fetch froze (G9), the rows above fall back to the earlier poll
    # verdict -- the only one that exists -- and nothing was persisted. Say
    # so, same convention as cmd_status/cmd_clean's freeze line, instead of
    # letting the stale verdict read as current-and-committed.
    if epoch_frozen:
        print("EPOCH: roster suspicious at persist -- native rows show the "
              "pre-freeze poll verdict; nothing persisted (G9)")

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

def _cmd_send_native(name: str, before: dict, message: str,
                     run=subprocess.run, which=shutil.which, sleep=time.sleep) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_send`'s legacy body
    below -- fork-steer per RATIFIED G2(b), M-B Task 7.

    `before` is the caller's already-locked snapshot of the record (`cmd_send`
    only routes here once it has confirmed `is_native`); `refuse_if_legacy`
    below is pure defense in depth against a future misrouted call, not the
    primary gate.

    Roster fetched ONCE, outside any lock (F4 doctrine), then the verdict
    (`recompute_worker_native`) is (re)computed under a single fresh lock --
    the record is re-read here rather than trusting `before`, since an
    unbounded amount of time may have passed since the caller's snapshot.

    Verdict branches:
      - working (roster busy/waiting) -> append_mailbox + mail_sent event,
        UNCHANGED mid-turn path (hooks deliver, G1). Print states this.
      - dead-suspected -> refuse, point at peek/result then kill/respawn.
      - dead / interrupted -> refuse, point at respawn.
      - limited -> refuse, point at resume-limited (never steer a parked
        worker).
      - idle -> FORK-STEER: token-ceiling cumulative check (mirrors legacy's
        over_ceiling refusal; native has no logs/<name>.jsonl, so
        `_native_cumulative_tokens` sums the outcome store instead; USD
        check is skipped entirely -- G3), pre-claim `working`, then
        OUTSIDE the lock:
        append_mailbox(old_sid, message) FIRST so the message rides the
        drain (F6 pattern), compose_prompt(name, cwd, "", old_sid) (claims
        the mailbox, no journal_path -- this is a steer, not a context
        reset), dispatch_bg(..., resume_sid=old_sid). On success, commit via
        `_restamp_after_steer` + a fresh ceiling file for the new sid + a
        `steered` event. On NativeDispatchError/BaseException, restore the
        mailbox claim and roll the pre-claim back to idle -- but ONLY if the
        record is still in the exact claim state this call wrote (status
        working, session_id still the OLD sid) -- a concurrent actor may
        have already moved it on.
      - anything else reached here (over_ceiling/over_budget/attached --
        native sticky statuses this task's contract does not otherwise
        enumerate) refuses generically rather than silently mis-steering."""
    refuse_if_legacy(name, before, "send")

    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    roster_entries = payload if roster_ok else []

    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is None:
            raise FleetCliError(f"unknown worker: {name!r}")
        # G9 epoch rule: never trust a verdict computed against a suspicious
        # roster snapshot (fetch failure, or an empty roster while this
        # worker's own last-committed record still claims a live turn).
        if native_epoch_suspicious(roster_ok, roster_entries, {name: rec}):
            raise FleetCliError(
                f"{name}: roster fetch unavailable/suspicious (G9) -- "
                "refusing to send while native verdicts are frozen; retry shortly"
            )
        after = recompute_worker_native(name, rec, roster_entries)
        status = after["status"]

        # T7 fix wave (CRITICAL-2, race authority): recompute_worker_native's
        # "working" verdict is NOT sticky for native records (dead-suspected
        # must stay re-evaluable) -- so a concurrent send/steer's own
        # idle-fork-steer pre-claim (raw status=="working" on disk,
        # session_id still the OLD sid until ITS dispatch resolves) can get
        # RE-DERIVED by roster+outcome into something else entirely (idle,
        # pre-FIX-2a; dead-suspected/limited, post-FIX-2a's last_dispatch_at
        # restamp) once THIS call's own recompute runs, since the roster
        # hasn't caught up to the other actor's fork yet. Mirrors the FIX-1
        # revalidate pattern in `_resume_one_limited`: the untouched RAW
        # `rec` (loaded fresh under this SAME lock, never mutated by
        # `after`) is ground truth. If it still says "working" and this
        # call's own recompute disagrees, someone else already owns the
        # claim -- never pre-claim twice; queue the mailbox message against
        # the raw (current) sid instead of writing `after` back over a live
        # pre-claim.
        #
        # T7 fix wave 2 (NEW CRITICAL, re-review of eef84ae): the raw
        # mismatch above is NOT proof of a live concurrent pre-claim -- it
        # is also the routine, majority-of-the-time shape of "this turn
        # genuinely finished and nothing has persisted the demotion yet"
        # (recomputing-and-persisting exactly that staleness is this
        # function's own job). Both shapes produce an identical on-disk
        # record. Narrow the raw check to only claim in-flight authority
        # when there's no fresh completion outcome for the raw sid AND the
        # pre-claim itself hasn't expired (a crashed steer) -- i.e. the raw
        # label could still plausibly belong to a live, still-running
        # dispatch. Anchors mirror recompute_worker_native's own
        # (last_dispatch_at, falling back to created/last_activity for
        # legacy-shaped records) so this reuses the same ground truth the
        # recompute itself already applied, rather than inventing a second
        # one.
        if rec.get("status") == "working" and status != "working":
            raw_sid = rec.get("session_id")
            if raw_sid is None:
                # T7 fix wave (CRITICAL-1): a spawn/respawn launch-claim in
                # flight has no real sid yet -- appending to mailbox/None.md
                # would silently swallow the message. Refuse loudly instead.
                # (Definitionally in-flight: no sid means nothing could have
                # finished yet.)
                raise FleetCliError(
                    f"{name}: dispatch in flight -- retry in a few seconds"
                )
            outcome_anchor = rec.get("last_dispatch_at") or rec.get("created")
            claim_anchor = rec.get("last_dispatch_at") or rec.get("last_activity")
            in_flight = (
                not has_fresh_outcome(name, raw_sid, outcome_anchor)
                and not _launch_claim_expired(claim_anchor)
            )
            if in_flight:
                append_mailbox(raw_sid, message)
                append_event("mail_sent", name, sid=raw_sid, status="working")
                print(f"{name}: turn running -- message queued to mailbox")
                return 0
            # Not actually in flight: the raw "working" label is stale
            # (fresh outcome proves the turn already finished) or belongs to
            # an expired/crashed claim. Fall through to the normal verdict
            # path below, which persists the freshly recomputed `after` on
            # every branch it can reach -- self-healing the stale label
            # instead of leaving it frozen and silently misrouting mail to
            # a dead session.

        if status != rec.get("status"):
            append_event("status_changed", name, old=rec.get("status"), new=status)

        if status == "dead-suspected":
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(
                f"{name}: dead-suspected -- no outcome record for its last "
                "turn; inspect (fleet peek/result), then kill or respawn"
            )
        if status in ("dead", "interrupted"):
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(
                f"{name}: worker is {status} -- run `fleet respawn {name}` first"
            )
        if status == "limited":
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(
                f"{name}: parked (limited) -- use `fleet resume-limited {name}` "
                "instead (never steer a parked worker)"
            )

        if status == "working":
            # S5 fix (final wave): strip the transient waiting_for_permission
            # key before persisting -- T5's I1 pattern (cmd_status/cmd_wait/
            # cmd_clean), replicated here since this working-branch persist
            # was the one T7-era commit path that missed it.
            persisted = dict(after)
            persisted.pop("waiting_for_permission", None)
            data["workers"][name] = persisted
            save_registry(data)
            sid = after["session_id"]
            if sid is None:
                # T7 fix wave (CRITICAL-1), defense in depth: the raw
                # pre-check above already catches the common shape of this
                # (raw status=="working"); guard here too in case recompute
                # itself derived "working" from a sid-less launch-claim that
                # wasn't already raw "working" (a corrupted/legacy-shaped
                # record) -- never append to mailbox/None.md.
                raise FleetCliError(
                    f"{name}: dispatch in flight -- retry in a few seconds"
                )
            append_mailbox(sid, message)
            append_event("mail_sent", name, sid=sid, status=status)
            print(f"{name}: turn running -- message queued to mailbox")
            return 0

        if status != "idle":
            data["workers"][name] = after
            save_registry(data)
            raise FleetCliError(f"{name}: flagged {status} -- refusing to send")

        old_sid = after["session_id"]
        cwd = after["cwd"]
        mode = after["mode"]
        model = after.get("model")
        category = after.get("category")
        setting_sources = after.get("setting_sources")
        token_ceiling = after.get("token_ceiling")

        # Kernel 10 native lane: mirror the legacy over_ceiling refusal
        # (USD check skipped entirely for native -- G3).
        if token_ceiling is not None:
            used = _native_cumulative_tokens(name)
            if used >= token_ceiling:
                after["status"] = "over_ceiling"
                data["workers"][name] = after
                save_registry(data)
                append_event("ceiling_exceeded", name, tokens=used, token_ceiling=token_ceiling)
                raise FleetCliError(
                    f"{name}: cumulative tokens {used} reached token_ceiling "
                    f"{token_ceiling} -- refusing fork-steer (worker flagged "
                    "over_ceiling); respawn with a higher --token-ceiling or retire it"
                )

        # F1 pre-claim: atomic decide+claim, same lock, before release.
        # T7 fix wave (CRITICAL-2 fix 2a): also restamp last_dispatch_at --
        # the in-flight anchor cmd_spawn's own pre-claim stamps, mirrored
        # here so a concurrent recompute (any caller, not just a racing
        # send) never re-derives this in-flight window as stale-outcome
        # "idle" again (has_fresh_outcome is anchored on last_dispatch_at,
        # never on the outcome record's mere presence).
        # S3 fix (final wave): snapshot the PRE-pre-claim last_dispatch_at so
        # a failed dispatch's rollback can restore it verbatim. Restoring
        # only status="idle" (as before) leaves the anchor advanced to this
        # attempt's timestamp -- the next recompute anchors has_fresh_outcome
        # on THAT timestamp, and the worker's genuinely-fresh-but-now-stale
        # outcome record (predating this failed attempt) no longer vouches
        # for it -- permanently stranding an idle worker as dead-suspected.
        prior_last_dispatch_at = after.get("last_dispatch_at")
        after["status"] = "working"
        after["last_activity"] = now_iso()
        after["last_dispatch_at"] = now_iso()
        data["workers"][name] = after
        save_registry(data)

    # Outside the lock: F6 pattern -- append the message FIRST so it rides
    # the mailbox drain uniformly with any prior mail (never doubled, never
    # silently dropped).
    append_mailbox(old_sid, message)
    append_event("mail_sent", name, sid=old_sid, status="idle")
    prompt, claim = compose_prompt(name, cwd, "", old_sid)
    try:
        result = dispatch_bg(
            name, cwd, prompt, mode, model=model, category=category,
            hint=message[:NATIVE_NAME_HINT_MAX], resume_sid=old_sid,
            setting_sources=setting_sources, run=run, which=which, sleep=sleep,
        )
        finalize_mailbox_claim(claim)
    except BaseException:
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if (r is not None and r.get("status") == "working"
                    and r.get("session_id") == old_sid):
                r["status"] = "idle"
                r["last_dispatch_at"] = prior_last_dispatch_at
                save_registry(data)
        raise

    new_sid = result["session_id"]
    short_id = result["short_id"]

    # S2 fix (final wave): the success commit used to guard only `r is not
    # None`, unconditionally restamping over whatever a concurrent
    # kill/interrupt/respawn --force did during the seconds-to-minutes
    # dispatch window. Condition on `r.get("session_id") == old_sid` --
    # mirroring the rollback's own condition above -- so a record that
    # moved on (killed, tombstoned, or replaced by a fresh respawn
    # pre-claim with session_id=None) is never silently restamped back to
    # "working" under the fork's new sid.
    commit_orphaned = {"flag": False}

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") == old_sid:
                _restamp_after_steer(r, new_sid, short_id)
                r["status"] = "working"
                r["last_activity"] = now_iso()
                save_registry(data)
                # T7 fix wave (CRITICAL-2 fix 2c): a steering message that
                # raced into the OLD sid's mailbox AFTER compose_prompt
                # already claimed/drained it (e.g. a concurrent send that
                # lost the raw-status race above) must still follow the
                # worker -- migrate it onto the NEW sid rather than
                # stranding it under a sid the registry will never
                # reference again.
                _migrate_residual_mailbox(old_sid, new_sid)
                # T7 fix wave (Minor, event-append symmetry): keep
                # append_event inside the same guard as the mutation --
                # matches cmd_spawn's own commit shape. Previously fired
                # unconditionally, so a concurrent kill/clean racing this
                # window got a "steered" event in its audit trail even
                # though no registry mutation happened.
                _append_event_quiet("steered", name, old_session_id=old_sid,
                                    new_session_id=new_sid, short_id=short_id)
            elif r is not None:
                commit_orphaned["flag"] = True
                _append_event_quiet("steer_orphaned", name, old_session_id=old_sid,
                                    new_session_id=new_sid)

    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_native_turn(name, new_sid, short_id)
        return 1

    if commit_orphaned["flag"]:
        print(f"{name}: changed during dispatch (killed/interrupted?) -- "
              f"new session {short_id} left for manual adoption or archive")
        return 0

    _write_ceiling_file(new_sid, token_ceiling)
    # T7 fix wave (Minor, ceiling-file leak): the OLD sid's ceiling file is
    # now permanently unreachable (the Stop hook only ever reads the
    # CURRENT sid's) -- respawn already cleans this up on its own dispatch;
    # mirror it here for send's fork-steer, after the new one is written.
    try:
        ceiling_file_path(old_sid).unlink()
    except OSError:
        pass
    print(f"{name}: fork-steered (new session {short_id}) -- fork carries full transcript (G2b)")
    return 0


def cmd_send(args, which=shutil.which, sleep=time.sleep, run=subprocess.run) -> int:
    """`fleet send <name> <text|@file>` (SPEC §5 send row): steer a native
    worker via `_cmd_send_native` -- mailbox queue while a turn is running,
    fork-steer (RATIFIED G2b) when idle.

    SPEC §14: refuses up front (_require_instance_settings) if the
    worker-settings instance is missing -- the fork-steer branch dispatches
    a turn, and `fleet spawn` (the only way a worker could exist at all)
    already requires the instance."""
    _require_instance_settings()

    message = _read_task_arg(args.message)

    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = dict(data["workers"][args.name])

    refuse_if_archived(args.name, before, "send")
    return _cmd_send_native(args.name, before, message,
                            run=run, which=which, sleep=sleep)


def _resume_one_limited_native(name: str, old_sid: str, cwd, mode, model, category,
                               setting_sources, token_ceiling,
                               run, which, sleep) -> bool:
    """Native (`dispatch_kind:"bg"`) counterpart of the legacy resume below --
    fork-steer per RATIFIED G2(b): `claude --bg --resume <old_sid>` MINTS A
    NEW SID (the original session's own roster entry, sid, and event count
    are left untouched, Steering contract) rather than waking the same live
    session. Called with the pre-claim (status="working") already
    committed by `_resume_one_limited` under its own lock.

    Outside any lock: drain the OLD sid's mailbox into a steer body via
    compose_prompt(..., old_sid, journal_path=...) -- same "mailbox +
    journal" resume shape as the legacy path -- prefixed with the operator-
    facing continuation line, then dispatch_bg(..., resume_sid=old_sid,
    hint="resume past limit"). On any failure, restore the mailbox claim and
    roll the pre-claim back to `limited` (mirrors the legacy branch's
    rollback exactly -- session_id was never touched pre-commit, so this
    restores the OLD sid's park cleanly).

    On success: retire old_sid into retired_sids, restamp session_id/
    native_short_id to the NEW sid, re-point the ceiling file (the new sid
    didn't exist before dispatch_bg returned it), clear the limit fields,
    and commit turns/last_dispatch_at/last_activity via the same
    retry-wrapped `_commit_launched_turn` stamp step cmd_spawn's native path
    uses -- dispatch_bg is itself synchronous (it already blocks through the
    roster join), so the only remaining race is the registry commit lock,
    exactly like cmd_spawn's post-dispatch stamp."""
    journal_path = journals_dir() / f"{name}.md"
    prompt, claim = compose_prompt(name, cwd, "", old_sid, journal_path=journal_path)
    body = ("The usage-limit reset horizon has passed. Continue the task "
            "from where you left off.\n\n" + prompt)
    try:
        result = dispatch_bg(
            name, cwd, body, mode, model=model, category=category,
            hint="resume past limit", resume_sid=old_sid,
            setting_sources=setting_sources, run=run, which=which, sleep=sleep,
        )
        finalize_mailbox_claim(claim)
    except BaseException:
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("status") == "working" and r.get("session_id") == old_sid:
                r["status"] = "limited"
                save_registry(data)
        raise

    new_sid = result["session_id"]
    short_id = result["short_id"]
    _write_ceiling_file(new_sid, token_ceiling)
    # T7 fix wave (Minor, ceiling-file leak): mirror send's fork-steer
    # cleanup -- the OLD sid's ceiling file is now permanently unreachable
    # (the Stop hook only ever reads the CURRENT sid's).
    try:
        ceiling_file_path(old_sid).unlink()
    except OSError:
        pass

    # S2 fix (final wave): mirror send's own guard -- only restamp when the
    # record still matches the pre-dispatch snapshot (session_id == old_sid).
    commit_orphaned = {"flag": False}

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") == old_sid:
                r["retired_sids"] = list(r.get("retired_sids", [])) + [old_sid]
                r["session_id"] = new_sid
                r["native_short_id"] = short_id
                r["status"] = "working"
                r["last_dispatch_at"] = now_iso()
                r["last_activity"] = now_iso()
                r["turns"] = r.get("turns", 0) + 1
                r["limit_reset_at"] = None
                r["limit_kind"] = None
                save_registry(data)
                # T7 fix wave (CRITICAL-2 fix 2c): migrate any residual
                # OLD-sid mailbox onto the new fork -- see
                # _migrate_residual_mailbox's docstring.
                _migrate_residual_mailbox(old_sid, new_sid)
                _append_event_quiet("limit_resumed", name, old_session_id=old_sid,
                                    session_id=new_sid)
            elif r is not None:
                commit_orphaned["flag"] = True
                _append_event_quiet("steer_orphaned", name, old_session_id=old_sid,
                                    new_session_id=new_sid)

    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_native_turn(name, new_sid, short_id)
    elif commit_orphaned["flag"]:
        print(f"{name}: changed during dispatch (killed/interrupted?) -- "
              f"new session {short_id} left for manual adoption or archive")
    return True


def _resume_one_limited(name: str, which, sleep, run=subprocess.run) -> bool:
    """Relaunch a single `limited` worker via the native fork-steer
    (`_resume_one_limited_native`, RATIFIED G2(b)).

    Returns True iff a resume turn was actually launched, False if the worker
    was skipped because it was no longer `limited` when the claiming lock was
    taken (a concurrent resume sweep / respawn --force / send already moved it).

    Under the lock: RE-READ the record and re-validate it is STILL `limited`
    BEFORE pre-claiming (FIX-1/F-A1 -- mirrors cmd_send's idle re-check: the
    caller's eligibility decision was made against a lock-released snapshot, so
    two racing sweeps both snapshot `limited`; without this re-check the second
    clobbers the first's live pre-claim and starts a second dispatch on one
    sid). A vanished worker raises a clean FleetCliError, never a raw
    KeyError. Then pre-claim status="working" (recompute's launch-in-flight
    guard then refuses to demote this window)."""
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
        # Stamp a fresh last_activity so the stale-pre-claim guard
        # (LAUNCH_CLAIM_MAX_AGE_SECONDS) doesn't reap this in-flight
        # launch against an old timestamp.
        rec["last_activity"] = now_iso()
        data["workers"][name] = rec
        save_registry(data)
        sid = rec["session_id"]
        cwd = rec["cwd"]
        mode = rec["mode"]
        model = rec.get("model")
        setting_sources = rec.get("setting_sources")
        category = rec.get("category")
        token_ceiling = rec.get("token_ceiling")

    return _resume_one_limited_native(name, sid, cwd, mode, model, category,
                                      setting_sources, token_ceiling,
                                      run=run, which=which, sleep=sleep)


def cmd_resume_limited(args, which=shutil.which, sleep=time.sleep,
                       run=subprocess.run) -> int:
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
            refuse_if_archived(args.name, data["workers"][args.name], "resume-limited")
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
        if _resume_one_limited(name, which, sleep, run=run):
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


def _cmd_interrupt_native(name: str, rec: dict, run=subprocess.run, which=shutil.which) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_interrupt` (M-B
    T8): `claude stop` the current sid (G10: never raw-kill), write fleet's
    own tombstone (G10: stop fires no Stop hook), and mark the worker
    `interrupted` -- deliberately NOT `idle`: spec §5 forbids auto-anything,
    and an interrupted task is definitionally started, so it must read as
    "operator stopped this on purpose", never as "finished cleanly and
    ready for the next `send`". `interrupted` is in `_NATIVE_STICKY`, so no
    later recompute ever flips it back on its own -- only `fleet respawn`
    moves the worker again, a separate explicit decision (the print below
    says so).

    `_stop_native_session`'s own success/failure is not distinguished in
    the outcome here (unlike `cmd_kill`, interrupt is not terminal and
    nothing further depends on proving the stop landed) -- the tombstone
    and status flip both commit unconditionally, mirroring `cmd_respawn
    --force`'s own "write the stopped tombstone regardless of the stop's
    exit code" rule.

    T8 fix wave (adv C1, CRITICAL): the pre-fix version checked ONLY
    `session_id is None` before firing `claude stop` + the tombstone +
    the status flip -- every OTHER status (dead, dead-suspected, limited,
    over_budget/over_ceiling/attached, idle) fell straight through and got
    unconditionally overwritten to `interrupted`, which is destructive for
    anything that was never actually a live turn:
      - `dead` -> `interrupted` un-terminals a sticky status via a raw
        write that bypasses `recompute_worker_native`'s stickiness
        entirely, with rc==0 and no warning that nothing was running.
      - `limited` -> `interrupted` silently drops the worker out of
        `resume-limited`'s `status == "limited"` filter, permanently
        breaking usage-limit auto-continuity (spec §5.1.1) -- rc==0, no
        operator-visible signal.
      - a live `claude stop <sid>` subprocess call fired against a sid
        fleet's OWN registry already called dead/gone.
    Guard: only `rec["status"] == "working"` is actually interruptible.
    `recompute_worker_native`'s own definition of "working" IS "roster-
    live busy/waiting", and every write to a native record's status
    already routes through that recompute (send/status/clean/respawn) --
    trusting the last-persisted verdict here needs no extra roster fetch.
    Every other status gets either a friendly no-op (nothing was running:
    dead/interrupted/idle) or a loud refusal (limited/dead-suspected/
    anything else sticky-but-not-working -- parked or otherwise not a
    plain live turn) pointing at the right escape hatch, rather than a
    silent overwrite.

    sid is None only for a launch-in-flight pre-claim (no real session to
    stop yet) -- refuses loudly (unlike the friendly no-op statuses above)
    since a dispatch may still land any moment and silently no-op'ing
    would hide that from the operator."""
    sid = rec.get("session_id")
    if sid is None:
        print(
            f"fleet: {name}: dispatch in flight -- no live session yet to "
            "interrupt; retry in a few seconds",
            file=sys.stderr,
        )
        return 1

    status = rec.get("status")
    if status in ("dead", "interrupted", "idle"):
        print(f"{name}: no turn running -- nothing to interrupt")
        return 0
    if status == "limited":
        print(
            f"fleet: {name}: limited park -- interrupting would orphan the "
            "resume path; use resume-limited or kill",
            file=sys.stderr,
        )
        return 1
    if status == "dead-suspected":
        print(
            f"fleet: {name}: dead-suspected -- inspect first (fleet peek/"
            f"result {name}); nothing confirms a turn is actually running "
            "to stop",
            file=sys.stderr,
        )
        return 1
    if status != "working":
        print(
            f"fleet: {name}: status is {status!r}, not a live running turn "
            "-- refusing to interrupt",
            file=sys.stderr,
        )
        return 1

    stopped_ok = _stop_native_session(sid, run=run, which=which)
    write_tombstone_outcome(name, sid, "interrupted")
    with fleet_lock():
        data = load_registry()
        r = data["workers"].get(name)
        if r is not None:
            r["status"] = "interrupted"
            data["workers"][name] = r
            save_registry(data)
        append_event("interrupted", name, session_id=sid, stopped=stopped_ok)
    print(f"{name}: stopped via claude stop; marked interrupted. "
          f"Respawn is a separate decision (fleet respawn {name}).")
    return 0


def cmd_interrupt(args, run=subprocess.run, which=shutil.which) -> int:
    """`fleet interrupt <name>` (SPEC §5 interrupt row): `claude stop` +
    tombstone + a status of `interrupted` (never `idle`) via
    `_cmd_interrupt_native`, guarded to only actually fire on a `working`
    verdict (T8 fix wave, adv C1) -- every other status refuses or
    friendly-no-ops rather than un-terminaling a sticky status via a
    silent overwrite."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = dict(data["workers"][args.name])

    refuse_if_archived(args.name, rec, "interrupt")
    return _cmd_interrupt_native(args.name, rec, run=run, which=which)


def cmd_attach(args) -> int:
    """`fleet attach <name>` (SPEC §5 attach row): a native (`--bg`) session
    has no fleet-owned terminal to spawn -- point the operator at the agents
    menu / `claude attach` instead (M-B scope fence: native attach
    integration is a later milestone)."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = data["workers"][args.name]
    raise FleetCliError(
        f"{args.name}: native worker -- attach via the agents menu (Ctrl+T in claude) "
        f"or: claude attach {before.get('session_id')}"
    )


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

def _cmd_respawn_native(args, before: dict, run=subprocess.run, which=shutil.which,
                        sleep=time.sleep, clock=time.monotonic) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_respawn`'s legacy
    body below (M-B Task 7, replacing T6's interim "lands in Task 7" guard).

    Unlike the legacy respawn, this is a FRESH dispatch (no --resume) --
    the context reset is the point (SPEC §5 respawn row) -- so it goes
    through `dispatch_bg` exactly like `cmd_spawn`'s native path, just with
    carried-forward fields instead of fresh ones, and journal + old-sid
    mailbox carry via `compose_prompt(..., journal_path=...)`.

    Liveness gate: the OLD sid is "live" iff it is present in the roster
    with a `status`/`pid` (`_roster_live_sids`, contract field-presence
    table) -- NOT the registry's own stored status label (that label may
    be stale, sticky, or simply wrong for a record this task is the first
    to ever recompute via a fresh dispatch path). A roster fetch failure
    means liveness cannot be proven either way -- refuse outright (G9-style
    caution: never assume a session is dead on ambiguous data) rather than
    risking two live sessions under one name.

    --force on a live old session calls `_stop_native_session` then
    unconditionally writes a "stopped" tombstone (G10: `claude stop` fires
    no Stop hook, so fleet must record its own outcome for that turn) --
    regardless of whether the stop's own exit code was 0. The roster is
    ALWAYS re-fetched and re-checked after the stop attempt, whether or not
    `_stop_native_session` reported success (T7 fix wave, MAJOR: `claude
    stop`'s own exit code is not proof the daemon has actually torn the
    session down -- trusting a `True` return blindly skipped this
    verification entirely). If the re-check still shows the old sid live
    after a REPORTED SUCCESS, one `sleep(2)` + one more re-fetch gives a
    plausible daemon-lag stop a brief grace window before giving up; a
    REPORTED FAILURE aborts immediately on the first still-live re-check
    (no grace -- the tool itself already said it didn't work). Either way,
    still-live after the check(s) ABORTS the respawn entirely (Trap #3:
    never two live sessions under one name -- a real invariant, not a
    nicety).

    New record: `new_worker_record(None, ...)` (native pre-claim shape,
    session_id unknown until roster join, mirrors cmd_spawn) carrying
    cwd/mode/model/category/setting_sources/token_ceiling forward from
    `before` (overridable the same way legacy respawn's carry-or-override
    works), spawned_by carried immutably (§5.1 provenance), cost_usd/
    cost_baseline carried like legacy's Finding-4 fix, and retired_sids =
    the OLD record's own retired_sids + the OLD sid itself (a respawn chain
    must not lose earlier forks' history). No log rotation (native has no
    logs/<name>.jsonl to rotate). The old sid's ceiling file is removed
    (best-effort) and a fresh one written for the new sid once it is known.

    On dispatch failure, the pre-claim (session_id still None) rolls back
    to the exact pre-respawn snapshot (`before`) rather than popping the
    worker -- the operator keeps a registry entry pointing at the old
    (possibly already-stopped) session instead of losing the name outright.
    """
    name = args.name
    if getattr(args, "max_budget_usd", None) is not None:
        raise FleetCliError(
            "no USD budget under native dispatch (contract G3) -- use --token-ceiling"
        )

    old_sid = before.get("session_id")
    if old_sid is None:
        # Launch-in-flight pre-claim: no real sid exists yet to stop or
        # fork from.
        raise FleetCliError(f"launch in flight for {name}; retry in a few seconds")

    cwd = before["cwd"]
    mode = before["mode"]
    model = before.get("model")
    category = before.get("category")
    setting_sources = (args.setting_sources if getattr(args, "setting_sources", None) is not None
                       else before.get("setting_sources"))
    token_ceiling = (args.token_ceiling if getattr(args, "token_ceiling", None) is not None
                     else before.get("token_ceiling"))
    cost_usd = _registry_cost(before.get("cost_usd", 0.0))
    task_override = _read_task_arg(args.task) if getattr(args, "task", None) else None
    task_for_record = task_override if task_override is not None else before.get("task", "")
    prior_retired = list(before.get("retired_sids", []))
    spawned_by = before.get("spawned_by")

    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        raise FleetCliError(
            f"{name}: could not fetch the native roster -- refusing respawn "
            "until the old session's liveness can be verified"
        )
    old_live = old_sid in _roster_live_sids(entries)

    stopped_ok = None
    if old_live:
        if not getattr(args, "force", False):
            raise FleetCliError(
                f"{name}: turn is running -- pass --force to interrupt it first, "
                "or wait for it to finish"
            )
        stopped_ok = _stop_native_session(old_sid, run=run, which=which)
        # G10: `claude stop` fires no Stop hook -- write fleet's own
        # tombstone regardless of the stop's verified success, since an
        # operator-initiated stop was genuinely attempted either way.
        write_tombstone_outcome(name, old_sid, "stopped")
        # T7 fix wave (MAJOR): re-verify the roster after EVERY --force stop
        # attempt, not only when `_stop_native_session` reported failure --
        # its `True` return is just the stop command's own exit code, not
        # proof the daemon has actually torn the session down.
        roster_ok2, entries2 = _fetch_agents_roster(which=which, run=run)
        still_live = (not roster_ok2) or (old_sid in _roster_live_sids(entries2))
        if still_live and stopped_ok:
            # A reported success that still shows live could just be
            # daemon lag -- give it one brief grace window before aborting.
            sleep(2)
            roster_ok3, entries3 = _fetch_agents_roster(which=which, run=run)
            still_live = (not roster_ok3) or (old_sid in _roster_live_sids(entries3))
        if still_live:
            raise FleetCliError(
                f"{name}: --force could not verify the old session was "
                "stopped -- aborting respawn (never two live sessions "
                "under one name)"
            )

    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is None:
            raise FleetCliError(f"unknown worker: {name!r}")
        if not is_native(rec):
            raise FleetCliError(f"{name}: worker changed concurrently; retry")
        new_record = new_worker_record(
            None, cwd, task_for_record, mode, model=model,
            setting_sources=setting_sources, token_ceiling=token_ceiling,
            spawned_by=spawned_by, dispatch_kind="bg", category=category)
        new_record["cost_usd"] = cost_usd
        new_record["cost_baseline"] = cost_usd
        new_record["retired_sids"] = prior_retired + [old_sid]
        new_record["last_dispatch_at"] = now_iso()
        data["workers"][name] = new_record
        save_registry(data)
        append_event("respawned", name, old_session_id=old_sid, new_session_id=None,
                    stopped=stopped_ok)

    pre_claim_at = new_record["last_dispatch_at"]

    try:
        ceiling_file_path(old_sid).unlink()
    except OSError:
        pass

    journal_path = journals_dir() / f"{name}.md"
    prompt, claim = compose_prompt(name, cwd, task_for_record, old_sid, journal_path=journal_path)
    try:
        result = dispatch_bg(
            name, cwd, prompt, mode, model=model, category=category,
            hint=task_for_record, setting_sources=setting_sources,
            run=run, which=which, sleep=sleep, clock=clock,
        )
        finalize_mailbox_claim(claim)
    except NativeDispatchError as exc:
        # T7 fix wave (Important b): reuse cmd_spawn's fast-completion
        # check -- this respawn's new-record pre-claim is session_id=None
        # exactly like spawn's, so the SAME race (a fast-finishing session's
        # outcome landing under a sid-keyed fallback file before
        # dispatch_bg's join-verify loop observes it in the roster) can
        # strand a genuinely-completed turn behind a rollback. The launch
        # genuinely happened (a real --bg dispatch was issued and consumed
        # the already-composed/drained prompt) whenever join expiry raised
        # WITH a short_id, so finalize (not restore) the claim on the found
        # branch, mirroring the try block's own success path.
        fast_sid = _fast_completion_sid(name, pre_claim_at, short_id=getattr(exc, "short_id", None))
        if fast_sid is not None:
            finalize_mailbox_claim(claim)
            with fleet_lock():
                data = load_registry()
                rec = data["workers"].get(name)
                if rec is not None and rec.get("session_id") is None:
                    rec["session_id"] = fast_sid
                    rec["native_short_id"] = fast_sid.partition("-")[0] or fast_sid[:8]
                    rec["status"] = "idle"
                    rec["turns"] = 1
                    rec["last_activity"] = now_iso()
                    save_registry(data)
                    # Fix-wave N2: see cmd_spawn's fast-completion block --
                    # post-save OSError must not crash a durable commit.
                    _append_event_quiet("turn_started", name, session_id=fast_sid)
            _write_ceiling_file(fast_sid, token_ceiling)
            print(f"{name} {fast_sid} (native bg, fast completion before join)")
            return 0

        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") is None:
                data["workers"][name] = before
                save_registry(data)
                append_event("respawn_failed", name, error=str(exc), old_session_id=old_sid)
        raise FleetCliError(f"{name}: native respawn failed -- {exc}") from exc
    except BaseException as exc:
        restore_mailbox_claim(claim)
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") is None:
                data["workers"][name] = before
                save_registry(data)
                append_event("respawn_failed", name, error=str(exc), old_session_id=old_sid)
        raise

    new_sid = result["session_id"]
    short_id = result["short_id"]

    def _commit():
        with fleet_lock():
            data = load_registry()
            r = data["workers"].get(name)
            if r is not None and r.get("session_id") is None:
                r["session_id"] = new_sid
                r["native_short_id"] = short_id
                r["status"] = "working"
                r["turns"] = 1
                r["last_activity"] = now_iso()
                save_registry(data)
                _append_event_quiet("turn_started", name, session_id=new_sid)

    if not _commit_launched_turn(_commit, sleep=sleep):
        _report_stranded_native_turn(name, new_sid, short_id)
        return 1

    _write_ceiling_file(new_sid, token_ceiling)
    print(f"{name} {new_sid} (native bg)")
    return 0


def cmd_respawn(args, run=subprocess.run, which=shutil.which,
                sleep=time.sleep, clock=time.monotonic) -> int:
    """`fleet respawn <name> [--task <text>] [--force]` (SPEC §5 respawn
    row): the context-reset lever -- a fresh native session under the same
    name/cwd/mode/model, prompted with the preamble + task (original,
    truncated per the registry schema, or --task's override) + the
    worker's journal (state/journals/<name>.md, labeled, if it exists) +
    the OLD session's drained mailbox. See `_cmd_respawn_native` for the
    full dispatch/rollback contract (liveness gate, --force stop +
    tombstone, fast-completion race, carried-forward fields)."""
    _require_instance_settings()

    # §5.1: respawn retires the old session id. Ask before doing that to a
    # worker this session did not spawn. Reads the registry WITHOUT the lock
    # (a lock-free read, like `status --stale-ok`) and prompts outside it: a
    # prompt must never block the fleet.
    _ok, _reason, _snap = _read_registry_readonly()
    if _ok and args.name in _snap["workers"]:
        _confirm_destructive("respawn (retire the session of)", [args.name], _snap["workers"],
                             assume_yes=getattr(args, "yes", False))
        before = dict(_snap["workers"][args.name])
    else:
        # Unknown name or unreadable registry: resolve under the lock so a
        # corrupt registry surfaces through load_registry's quarantine and an
        # unknown worker gets the uniform error.
        with fleet_lock():
            data = load_registry()
            if args.name not in data["workers"]:
                raise FleetCliError(f"unknown worker: {args.name!r}")
            before = dict(data["workers"][args.name])
        _confirm_destructive("respawn (retire the session of)", [args.name],
                             {args.name: before}, assume_yes=getattr(args, "yes", False))

    refuse_if_archived(args.name, before, "respawn")
    return _cmd_respawn_native(args, before, run=run, which=which, sleep=sleep, clock=clock)


_RETIRED_SID_SWEEP_TIMEOUT_SECONDS = 5
_RETIRED_SID_SWEEP_CAP = 20


def _cmd_kill_native(name: str, rec: dict, run=subprocess.run, which=shutil.which) -> int:
    """Native (`dispatch_kind:"bg"`) counterpart of `cmd_kill`'s legacy body
    (M-B T8): `claude stop` the current sid (G10: never raw-kill) plus every
    retired sid best-effort (a steered-away fork per Steering contract may
    still be live even though this record's own current sid has moved on),
    write fleet's own tombstone (G10: `claude stop` fires no Stop hook, so
    nothing else records this turn ended), then unconditionally mark the
    worker dead -- kill is terminal regardless of whether the stop could be
    verified. A verified-failed stop still marks dead (mirrors the legacy
    kill_failed branch) but warns loudly and exits 1 so the operator
    investigates the session manually instead of trusting a silent success.

    `rec` is the caller's already-locked snapshot (post-launch-in-flight-
    guard, post-`_confirm_destructive`); the commit below re-reads the
    registry fresh under its own lock rather than trusting `rec`, since
    kill is meant to succeed even if the record changed shape meanwhile.

    T8 fix wave (adv I1): `retired_sids` has no cap anywhere else in the
    codebase -- it accumulates one entry per fork-steer/respawn for a
    worker's ENTIRE lifetime, so a long-lived, much-steered worker can
    carry dozens of retired sids. Sweeping all of them sequentially at the
    primary sid's 30s timeout each could block a single `fleet kill` for
    tens of minutes with zero progress feedback. Fix: each retired stop
    gets its own short `_RETIRED_SID_SWEEP_TIMEOUT_SECONDS` (5s) budget --
    best-effort only, the primary sid above still gets the full 30s -- and
    the sweep is capped to the `_RETIRED_SID_SWEEP_CAP` (20) MOST RECENT
    retired sids (older ones are long-reaped in practice; this is a
    wall-time bound, not a correctness guarantee -- a still-live retired
    sid past the cap simply isn't swept by this invocation). One stderr
    progress line per retired sid so a long sweep never looks hung.

    T8 fix wave (adv M1): before stopping a retired sid, skip it (with a
    stderr note) if it equals ANY OTHER worker's CURRENT session_id in the
    registry. A genuine sid collision through normal operation is not a
    real-world concern (~0 probability), so this only guards a corrupted/
    hand-edited registry -- but cheaply, with one extra registry read
    (under the lock, released immediately, no probe/roster fetch) before
    the sweep starts."""
    with fleet_lock():
        other_current_sids = {
            other_rec.get("session_id")
            for other_name, other_rec in load_registry()["workers"].items()
            if other_name != name and other_rec.get("session_id") is not None
        }

    sid = rec.get("session_id")
    stopped_ok = _stop_native_session(sid, run=run, which=which) if sid else True
    retired_sids = list(rec.get("retired_sids", []) or [])[-_RETIRED_SID_SWEEP_CAP:]
    for retired in retired_sids:
        if retired in other_current_sids:
            print(
                f"fleet: {name}: retired session {retired[:8]} matches another "
                "worker's current session_id -- skipping (registry looks "
                "corrupted; not stopping someone else's live session)",
                file=sys.stderr,
            )
            continue
        ok = _stop_native_session(retired, run=run, which=which,
                                  timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
        print(f"fleet: {name}: stopping retired session {retired[:8]}... "
              f"{'ok' if ok else 'timeout'}", file=sys.stderr)
    if sid:
        write_tombstone_outcome(name, sid, "killed")

    with fleet_lock():
        data = load_registry()
        r = data["workers"].get(name)
        if r is not None:
            r["status"] = "dead"
            save_registry(data)
        append_event("killed", name, interrupt_outcome=stopped_ok)

    if not stopped_ok:
        print(
            f"fleet: {name}: claude stop could not be verified -- marked dead anyway "
            "(kill is a terminal action); investigate the session manually",
            file=sys.stderr,
        )
        return 1
    print(f"{name}: killed")
    return 0


def cmd_kill(args, run=subprocess.run, which=shutil.which) -> int:
    """`fleet kill <name>` (SPEC §5): stop the native session (plus retired
    sids best-effort), write fleet's own tombstone, then unconditionally
    mark the worker "dead" and append a "killed" event -- kill is the
    terminal, "retire this worker" action, distinct from `fleet interrupt`
    (which marks `interrupted`, a respawn-eligible state). See
    `_cmd_kill_native` for the stop/tombstone contract.

    Launch-in-flight guard: a pre-claim with `session_id is None` (dispatch
    still in flight, not yet expired per `_launch_claim_expired`) refuses
    loudly -- there is no real session to stop yet, and marking it dead
    would race the in-flight dispatch's own commit."""
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = data["workers"][args.name]
        refuse_if_archived(args.name, rec, "kill")
        if rec.get("session_id") is None and not _launch_claim_expired(rec.get("last_activity")):
            raise FleetCliError(
                f"launch in flight for {args.name}; retry in a few seconds"
            )
        workers_snapshot = {args.name: dict(rec)}

    # §5.1: acknowledge before retiring a worker this session did not spawn.
    # OUTSIDE fleet_lock (an interactive prompt must never block every other
    # fleet command on a human's keystroke).
    _confirm_destructive("kill", [args.name], workers_snapshot,
                         assume_yes=getattr(args, "yes", False))

    return _cmd_kill_native(args.name, workers_snapshot[args.name], run=run, which=which)


def _remove_worker_files(name: str, sid: str, retired_sids: list = ()) -> list:
    """Delete every on-disk artifact for a removed dead worker: current +
    rotated logs, its mailbox file, any orphaned mailbox/*.claimed.* files
    for that sid (T3-F2, adversarial review deferred finding: a hook
    killed between claim and delete leaves a `.claimed.<pid>` file behind
    -- `fleet clean` sweeps these for the sid it is removing, rather than
    leaving them as permanent litter), and its journal. Best-effort
    (missing files are not an error). Returns the list of paths actually
    removed, for cmd_clean's print-what-was-removed contract.

    M-B T8: also sweeps the native outcome-store files -- the name-keyed
    `state/outcomes/<name>.jsonl` plus this sid's own sid-keyed fallback
    file (`read_outcomes`' dual-file merge shape), the worker's task file
    (`state/tasks/<name>.md`), and -- for every sid in `retired_sids` (a
    fork-steer/respawn chain's earlier sids, native-only, always empty for
    a legacy record) -- that sid's own outcome file and ceiling file, which
    would otherwise survive as permanent orphans once the registry entry
    that referenced them is gone.

    M-B T9 (spec §5.1.2): also sweeps `logs/archive/<name>/` (the whole
    tree, via shutil.rmtree) -- `fleet clean` is the only sanctioned
    deleter of an archived worker's tombstoned files, mirroring the rest
    of this function's best-effort/missing-is-fine contract. A no-op for
    a worker that was never archived (the dir simply doesn't exist)."""
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
        outcome_path(name),
        outcome_path(sid),
        task_file_path(name),
    ]
    candidates += [outcome_path(s) for s in retired_sids]
    candidates += [ceiling_file_path(s) for s in retired_sids]
    candidates += list(mailbox_dir().glob(f"{sid}.md.claimed.*")) if mailbox_dir().exists() else []
    for path in candidates:
        try:
            path.unlink()
            removed.append(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
    archive_dir = archive_root() / name
    if archive_dir.exists():
        try:
            shutil.rmtree(archive_dir)
            removed.append(archive_dir)
        except OSError:
            pass
    # T9 fix wave (finding M-3a): `_archive_dest_dir` collision-suffixes a
    # base dir that was never cleaned up (`.1`, `.2`, ...) -- a crash mid-
    # move (finding 3a) or an archive/clean/archive cycle can leave one or
    # more of these siblings behind. Sweep every `<name>.<digits>` dir too,
    # so `fleet clean` (the sole sanctioned deleter of archived history)
    # actually deletes ALL of it, not just the base dir. Regex-anchored
    # (not a loose glob) so a differently-named worker whose name happens
    # to start with this one (e.g. "w10" vs "w1") is never swept.
    if archive_root().exists():
        suffix_re = re.compile(re.escape(name) + r"\.\d+$")
        for p in sorted(archive_root().iterdir()):
            if p.is_dir() and suffix_re.match(p.name):
                try:
                    shutil.rmtree(p)
                    removed.append(p)
                except OSError:
                    pass
    return removed


def cmd_clean(args, run=subprocess.run, which=shutil.which) -> int:
    """`fleet clean` (SPEC §5): recompute every worker's status; any that
    resolve to "dead" are removed from the registry along with their
    on-disk artifacts (`_remove_worker_files`). Prints one line per removed
    worker. Never touches idle/working/attached workers. A worker whose
    recompute merely changes status (without becoming dead) is persisted
    like `fleet status` does, not removed.

    Shape (F4 doctrine, mirrors cmd_status): snapshot every record under
    one fleet_lock, release it, do ONE roster fetch + every
    `recompute_worker_native` verdict with no lock held, then re-acquire
    to merge -- but only for records that still match their pre-probe
    snapshot exactly (full-dict equality), sparing anything a concurrent
    command mutated while the lock was released. The roster verdict is
    deterministic given one fetch, so no second-pass confirm delay is
    needed (that existed for the legacy PID probe's transient flakiness).

    Deletable statuses: `dead` ONLY (T8 fix wave, review CRITICAL). NEVER
    `dead-suspected` (a surfaced, still-undecided verdict, not a finished
    state), `limited` (parked, not finished), `idle` (finished-and-still-
    steerable), `interrupted` (respawn-eligible by design), or `working`.
    `claude rm`-ing the roster entry itself is T9's territory -- this
    command never touches the roster, only fleet's own files.

    G9 epoch-freeze: a suspicious roster fetch (failure, or an empty roster
    while some worker's own last-committed record still claims a live
    turn) means clean REFUSES to touch ANY live record this invocation --
    no recompute, no delete, prints the freeze line. Archived tombstones
    are still swept (see below).

    M-B T9 (spec §5.1.2): an archived (`archived_at` set) record is ALWAYS
    doomed here, regardless of epoch-freeze or its (frozen) status --
    `fleet archive` already `claude rm`'d every sid, so there is no roster
    verdict left to compute; this is pure file deletion (registry entry +
    the `logs/archive/<name>/` dir `_remove_worker_files` also sweeps).
    It never enters `recompute_worker_native`/the roster fetch at all.

    Autoclean tiering split (docs/specs/autoclean.md D2): `--dead-only`
    spares every tombstone (sweep only confirmed-dead workers);
    `--tombstones` sweeps ONLY archived tombstones -- no recompute,
    nothing else touched. Default remains both."""
    _NATIVE_CLEAN_DELETABLE = {"dead"}
    dead_only = bool(getattr(args, "dead_only", False))
    tombstones_only = bool(getattr(args, "tombstones", False))

    removed = []  # list of (name, sid, retired_sids)
    with fleet_lock():
        data = load_registry()
        names = sorted(data["workers"])
        before = {n: data["workers"][n] for n in names}

    archived_names = [n for n in names if before[n].get("archived_at")]
    live_names = [n for n in names if n not in archived_names]
    doomed_archived_names = [] if dead_only else list(archived_names)
    if tombstones_only:
        live_names = []

    # ONE roster fetch per invocation, outside the lock (F4 doctrine), only
    # when a non-archived worker is actually in the registry.
    roster_entries = []
    epoch_frozen = False
    if live_names:
        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
        roster_entries = payload if roster_ok else []
        epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, before)

    after = {}
    if live_names and not epoch_frozen:
        for n in live_names:
            after[n] = recompute_worker_native(n, before[n], roster_entries)

    doomed_now = []  # (name, before) -- verdict already final
    doomed_now.extend((n, before[n]) for n in doomed_archived_names)
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
            if n in archived_names:
                continue  # queued into doomed_now above (unless --dead-only spared it)
            if n not in live_names:
                continue  # excluded by --tombstones: never probed, never touched
            if epoch_frozen:
                continue  # G9: no record recomputed or written this invocation
            verdict = after[n]
            if verdict["status"] in _NATIVE_CLEAN_DELETABLE:
                doomed_now.append((n, before[n]))
                continue
            persisted = dict(verdict)
            persisted.pop("waiting_for_permission", None)
            if persisted != current:
                if persisted["status"] != current["status"]:
                    append_event("status_changed", n, old=current["status"], new=persisted["status"])
                    changed = True
                data["workers"][n] = persisted
        if changed:
            save_registry(data)

    if epoch_frozen:
        print("EPOCH: roster suspicious -- verdicts frozen (G9); nothing cleaned this pass")

    # §5.1: this is the moment `clean` knows exactly which workers it will
    # DELETE (registry entry + on-disk artifacts -- irreversible; the claude
    # session survives clean ITSELF, resumable by sid from events.jsonl --
    # but F5 caveat: once the autoclean scheduler is installed, tier 2 will
    # `claude rm` that very session on its next sweep (post-clean it is
    # owned-by-events and unprotected), so sid-recovery is a promptly-or-
    # never affordance, not a durable one). Ask before sweeping any worker
    # this session did not spawn. Outside the lock: a prompt must never
    # block the fleet.
    doomed = {n: rec for n, rec in doomed_now}
    if doomed:
        # T9 fix wave (finding M-6): an archived target's confirm line names
        # what is actually being destroyed -- not just "logs + journal" but
        # the tombstoned `logs/archive/<name>/` history T9's whole design
        # exists to preserve. Only added when at least one doomed worker is
        # archived; the routine dead-worker wording is unchanged otherwise.
        any_archived = any(rec.get("archived_at") is not None for rec in doomed.values())
        action = ("clean (delete logs + journal + archived history of)" if any_archived
                  else "clean (delete logs + journal of)")
        _confirm_destructive(action, sorted(doomed), doomed,
                             assume_yes=getattr(args, "yes", False))

    changed = False
    with fleet_lock():
        data = load_registry()
        for n, before_rec in doomed_now:
            current = data["workers"].get(n)
            if current != before_rec:
                # Mutated concurrently since the first lock released --
                # spare it, don't delete on a now-stale verdict.
                continue
            removed.append((n, current.get("session_id"), current.get("retired_sids", [])))
            data["workers"].pop(n, None)
            changed = True

        if changed:
            save_registry(data)
        for n, sid, _retired in removed:
            append_event("cleaned", n, session_id=sid)

    for n, sid, retired in removed:
        _remove_worker_files(n, sid, retired_sids=retired)
        print(f"removed {n} (session {sid})")

    if not removed:
        print("nothing to clean -- no dead workers")
    return 0


# ---------------------------------------------------------------------------
# Auto-archival (M-B T9, spec §5.1.2): retire terminal-state native workers
# past a TTL. `claude rm` (G12 CONFIRMED archival primitive; UNOBSERVED
# against a live session -- hence every gate below, especially the
# roster-live check) plus a file move into logs/archive/<name>/. The
# registry entry SURVIVES as a tombstone (archived_at set) -- `fleet clean`
# remains the only deleter (CLAUDE.md irreversibility doctrine).
# ---------------------------------------------------------------------------

ARCHIVE_TTL_HOURS_DEFAULT = 24.0


def _archive_eligible(name: str, record: dict, roster_entries: list, now,
                      ttl_hours: float = ARCHIVE_TTL_HOURS_DEFAULT) -> tuple:
    """Every gate must hold; returns (True, "eligible") or (False, reason)
    naming the FIRST failed gate (binding order, task-9-brief.md):

    1. is_native(record); archived_at is None.
    2. status in {"idle", "dead", "interrupted"} (the recomputed verdict
       the caller passes in, not necessarily the raw stored one).
    3. roster entry for the current sid is absent OR dead (no `status`/
       `pid` keys) -- NEVER archive a live-process entry (G12 gap).
    4. an outcome record exists for the current sid (ANY kind -- a result
       vouches completion, a tombstone vouches an operator decision); no
       record at all is dead-suspected territory, never auto-archived.
    5. now - last_activity >= ttl_hours.

    Gate 6 (status not limited/dead-suspected/working) is implied by gate
    2's allowed set -- never reachable as its own branch, asserted by
    tests instead."""
    if not is_native(record):
        return (False, "not-native")
    if record.get("archived_at") is not None:
        return (False, "already-archived")
    status = record.get("status")
    if status not in ("idle", "dead", "interrupted"):
        return (False, f"status:{status}")
    sid = record.get("session_id")
    if not sid:
        return (False, "no-session-id")
    entry = _roster_entry_for(roster_entries, sid)
    live = entry is not None and ("status" in entry or "pid" in entry)
    if live:
        return (False, "roster-live")
    if not read_outcomes(name, sid=sid):
        return (False, "no-outcome-record")
    try:
        last_activity = _parse_iso(record.get("last_activity", ""))
    except (ValueError, TypeError):
        # Traps named in advance (task-9-brief.md): a missing/malformed
        # last_activity must fail SAFE -- never eligible, never a crash.
        return (False, "last-activity-unparseable")
    age_hours = (now - last_activity).total_seconds() / 3600.0
    if age_hours < ttl_hours:
        return (False, "ttl-not-elapsed")
    return (True, "eligible")


def _archive_dest_dir(name: str) -> Path:
    """archive_root()/<name>, suffixed .1, .2, ... on collision (contract:
    a name archived, cleaned, then archived again under the same name is
    the only way this fires -- refuse_if_archived blocks re-archiving a
    still-tombstoned record, so a collision here means an EARLIER archive
    dir was never cleaned up). NEVER called for a resume (T9 fix wave,
    finding 3b) -- a resume reuses archive_root()/<name> directly (the
    exact dir a crashed prior attempt already started populating), since
    treating that as a "collision" would split the same worker's evidence
    across two dirs (finding 3a's failure mode, re-triggered by the resume
    path itself)."""
    base = archive_root() / name
    if not base.exists():
        return base
    i = 1
    while (archive_root() / f"{name}.{i}").exists():
        i += 1
    return archive_root() / f"{name}.{i}"


def _archive_file_pairs(name: str, sid: str, retired: list) -> list:
    """(src_path, dest_filename) for every on-disk evidence file a worker's
    archive moves -- journal, name-keyed + sid-keyed outcomes, task file,
    and (T9 fix wave, finding M-4b) the mailbox file for the current sid and
    every retired sid ("stranded mail is history too" -- otherwise it
    survives forever at its original path, unreachable via `send` (refused
    on `archived_at`) and invisible to `fleet clean` (which only sweeps
    `mailbox/<sid>.md` for a worker's CURRENT sid, not its retired ones).
    Single source of truth shared by the actual move phase and
    `_archive_resume_pending`'s crash-detection check (which only needs the
    src half), so the two can never drift apart."""
    pairs = [
        (journals_dir() / f"{name}.md", "journal.md"),
        (outcome_path(name), outcome_path(name).name),
        (task_file_path(name), "task.md"),
    ]
    if sid:
        pairs.append((outcome_path(sid), outcome_path(sid).name))
        pairs.append((mailbox_dir() / f"{sid}.md", f"{sid}.md"))
    for s in retired:
        pairs.append((outcome_path(s), outcome_path(s).name))
        pairs.append((mailbox_dir() / f"{s}.md", f"{s}.md"))
    return pairs


def _archive_resume_pending(name: str, record: dict) -> bool:
    """T9 fix wave (findings C2/3b): True iff this worker's `archived_at` is
    already stamped but at least one of its evidence files still sits at
    its PRE-MOVE location -- a crash (or any other interruption) landed
    between the (now-reordered, commit-first) `archived_at` write and the
    file-move phase finishing. `cmd_archive` re-run against such a record
    RESUMES the move instead of refusing via `refuse_if_archived` -- the
    tombstone is already correct, only the file relocation is incomplete."""
    if record.get("archived_at") is None:
        return False
    sid = record.get("session_id")
    retired = list(record.get("retired_sids", []) or [])
    return any(src.exists() for src, _dest in _archive_file_pairs(name, sid, retired))


def _archive_move_and_rm(n: str, sid: str, retired: list, dest_dir: Path,
                         roster_entries: list, run, which) -> None:
    """The (potentially slow) file-move + `claude rm` phase, shared by a
    fresh archive and a resumed one: move every evidence file into
    `dest_dir`, then `claude rm` the current sid and every retired sid --
    EXCEPT any sid the roster snapshot (the SAME one `_archive_eligible`'s
    gate 3 and this invocation's own eligibility pass used) shows live
    (`status` or `pid` key present). T9 fix wave finding C1: gate 3 only
    ever checked the CURRENT sid's liveness -- a retired sid abandoned by a
    fork-steer (`_cmd_send_native`'s idle path / `_resume_one_limited_native`,
    whose own docstring says the OLD sid's roster entry is left "untouched")
    can still be genuinely live at archive-time, and the un-gated rm loop
    below (pre-fix) removed it -- and its backing `~/.claude/jobs/<short>/`
    dir -- out from under a still-running session (G12 UNOBSERVED). A live
    sid is now SKIPPED (reported, not rm'd) rather than swept; a later
    archive run catches it once it actually retires."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src, dest_name in _archive_file_pairs(n, sid, retired):
        _archive_move(src, dest_dir / dest_name, n)

    for s in ([sid] if sid else []) + retired:
        entry = _roster_entry_for(roster_entries, s)
        live = entry is not None and ("status" in entry or "pid" in entry)
        if live:
            print(f"fleet: {n}: skipping rm {s[:8]}... -- session live in roster",
                  file=sys.stderr)
            continue
        ok = _rm_native_session(s, run=run, which=which)
        print(f"fleet: {n}: rm {s[:8]}... {'ok' if ok else 'failed'}", file=sys.stderr)


def _native_job_ref(sid: str) -> str:
    """T12 fix wave (finding 2): `claude stop`/`claude rm` require the SHORT
    id, not the full `session_id` fleet stores/passes everywhere -- empirically
    confirmed 2/2 (`claude stop <full-uuid>` -> "No job matching", the same
    call with the 8-char short id -> success). Every observed short id is the
    first hyphen-delimited segment of the full sid, so derive it uniformly
    here rather than special-casing callers that do/don't have a stored
    `native_short_id` (retired sids have none)."""
    return sid.split("-", 1)[0] if sid else sid


def _rm_native_session(sid: str, run=subprocess.run, which=shutil.which,
                       timeout: int = 30) -> bool:
    """`claude rm <sid>` (G12 CONFIRMED): the archival primitive -- removes
    the roster entry and its backing `~/.claude/jobs/<short-id>/` dir.
    Never raises: an unresolvable `claude` executable or any subprocess
    error both resolve to False, exactly like `_stop_native_session` --
    the caller treats every rm as best-effort/non-fatal and reports it.

    T12 fix wave (finding 2): `claude rm` requires the SHORT id -- converts
    via `_native_job_ref` first; on a nonzero exit, retries once with the
    full sid (belt-and-braces against a future CLI accepting full ids)."""
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError:
        return False
    refs = dict.fromkeys((_native_job_ref(sid), sid))
    for ref in refs:
        try:
            proc = run([exe, "rm", ref], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode == 0:
            return True
    return False


def _archive_move(src: Path, dest: Path, name: str) -> None:
    """Best-effort shutil.move of `src` to the exact path `dest` (whose
    parent dir must already exist) -- missing source is silently skipped
    (contract: "missing files skipped silently"); any other OSError is
    reported and the sweep continues (contract: "partial failure = report
    + continue"). `dest` is always a full path, never a bare directory:
    journals_dir()/<name>.md and task_file_path(<name>) share the SAME
    basename (<name>.md) in their own source dirs -- flattening both into
    logs/archive/<name>/ by basename alone would silently clobber one with
    the other, so callers pick distinct destination filenames."""
    if not src.exists():
        return
    try:
        shutil.move(str(src), str(dest))
    except OSError as exc:
        print(f"fleet: {name}: could not archive {src.name}: {exc}", file=sys.stderr)


def cmd_archive(args, run=subprocess.run, which=shutil.which) -> int:
    """`fleet archive [name] [--ttl-hours F] [--dry-run]` (SPEC §5.1.2):
    auto-retire terminal-state (idle/dead/interrupted) native workers whose
    current sid is confirmed gone-or-dead from the roster, has an outcome
    record vouching for it, and has sat idle past `ttl_hours` (default
    `ARCHIVE_TTL_HOURS_DEFAULT`). Moves the worker's journal/outcomes/task/
    mailbox files into `logs/archive/<name>/`, `claude rm`s the current sid
    and every retired sid (best-effort, non-fatal per sid, skipping any that
    the roster shows still live -- see `_archive_move_and_rm`), then stamps
    `archived_at` under the lock -- the registry entry SURVIVES as a
    tombstone; `fleet clean` remains the only deleter.

    T9 fix wave (finding C2/3b): the per-worker commit ordering is COMMIT
    FIRST, THEN move files, THEN rm sids -- the reverse of the original cut.
    The commit itself is a conditional write (re-read under lock, proceed
    only if the record is byte-identical to the eligibility snapshot,
    mirroring `cmd_status`/`cmd_clean`'s own "spare a concurrently-mutated
    record" doctrine) -- a concurrent `fleet send` fork-steer landing in the
    (now much narrower) window between snapshot and commit is detected and
    the archive attempt is skipped entirely for that worker, rather than
    stamping `archived_at` on top of a live, newly-restamped turn. Because
    the commit happens BEFORE the (slow, crash-prone) move/rm phase, a crash
    mid-move always leaves a fully-consistent tombstone (registry says
    archived) with some evidence files merely still sitting at their
    original path -- `recompute_worker`/`cmd_status` never re-derive
    liveness for an `archived_at` record regardless of file state, so this
    can never misfire into `dead-suspected` (finding 3b). Re-running
    `fleet archive` against such a record RESUMES the move (see
    `_archive_resume_pending`) instead of refusing, and reuses the exact
    same `archive_root()/<name>` dir rather than treating it as a fresh
    collision (finding 3a would otherwise reappear on every resume).

    G9 epoch-freeze: a suspicious roster fetch (failure, or an empty
    roster while some native worker's own last-committed record still
    claims a live turn) refuses the WHOLE invocation -- zero mutations,
    exit 1 -- exactly like `cmd_status`/`cmd_clean`'s freeze line. Fetched
    when at least one named/candidate worker is native-and-not-yet-archived,
    OR at least one is a pending resume (mirrors cmd_status/cmd_clean's own
    roster-fetch conditioning, extended for the resume case since its rm
    phase needs the same live-sid gate as a fresh archive).

    `--dry-run` prints each worker's eligibility verdict and mutates
    nothing (no roster-dependent verdict is computed differently, no rm,
    no file move, no registry write) -- safe to run even while frozen is
    NOT special-cased separately: freeze still refuses first, since a
    verdict computed against a suspicious roster is not trustworthy to
    even preview. A resumable already-archived record still reports
    "already-archived" under `--dry-run` (resume is an execution-time-only
    concept)."""
    name = getattr(args, "name", None)
    ttl_hours = getattr(args, "ttl_hours", None)
    if ttl_hours is None:
        ttl_hours = ARCHIVE_TTL_HOURS_DEFAULT
    dry_run = bool(getattr(args, "dry_run", False))

    with fleet_lock():
        data = load_registry()
        if name is not None:
            if name not in data["workers"]:
                raise FleetCliError(f"unknown worker: {name!r}")
            if not dry_run:
                rec_check = data["workers"][name]
                # T9 fix wave (finding C2/3b): a resumable archived record
                # (archived_at set, evidence files still pending their move)
                # is NOT a re-archive attempt -- let it through to resume
                # rather than raising. A fully-archived record with nothing
                # left to move still refuses, exactly as before.
                resumable = (rec_check.get("archived_at") is not None
                            and _archive_resume_pending(name, rec_check))
                if not resumable:
                    refuse_if_archived(name, rec_check, "archive")
            names = [name]
        else:
            names = sorted(data["workers"])
        before = {n: data["workers"][n] for n in names}
        all_workers = data["workers"]  # snapshot for the epoch check (G9)

    # Already-archived-and-fully-moved native records never consult the
    # roster (gate 1 of _archive_eligible short-circuits before the
    # live-check) -- exclude them from the roster-fetch conditioning,
    # mirroring cmd_status/cmd_clean's own "no native work, no subprocess
    # call" convention. A pending RESUME still needs the roster (its rm
    # phase re-checks sid liveness, finding C1), so it stays included.
    resume_names = [n for n in names
                    if is_native(before[n]) and _archive_resume_pending(n, before[n])]
    native_names = [n for n in names
                    if is_native(before[n]) and before[n].get("archived_at") is None]

    roster_entries = []
    epoch_frozen = False
    if native_names or resume_names:
        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
        roster_entries = payload if roster_ok else []
        epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, all_workers)

    if epoch_frozen:
        print("EPOCH: roster suspicious -- archival refused (G9); zero mutations", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    verdicts = {n: _archive_eligible(n, before[n], roster_entries, now, ttl_hours=ttl_hours)
               for n in names}

    if dry_run:
        for n in names:
            ok, reason = verdicts[n]
            print(f"{n}: eligible" if ok else f"{n}: skipped -- {reason}")
        return 0

    # verdicts[n][0] is always False for anything in resume_names (gate 1:
    # "already-archived") -- eligible_names and resume_names are disjoint.
    eligible_names = [n for n in names if verdicts[n][0]]

    archived_count = 0
    for n in eligible_names:
        rec = before[n]
        sid = rec.get("session_id")
        retired = list(rec.get("retired_sids", []) or [])

        # T9 fix wave (finding C2): commit FIRST, under a fresh lock,
        # conditional on the record still matching the eligibility
        # snapshot exactly -- a concurrent mutation (e.g. a fork-steer
        # restamping session_id/status) since `before` was captured means
        # this worker's turn is no longer the one that was judged eligible;
        # skip it rather than stamping archived_at over a live turn.
        with fleet_lock():
            data = load_registry()
            current = data["workers"].get(n)
            if current is None:
                print(f"fleet: {n}: registry entry vanished concurrently -- skipped",
                      file=sys.stderr)
                continue
            if current != rec:
                print(f"fleet: {n}: changed during archive -- skipped", file=sys.stderr)
                continue
            current = dict(current)
            current["archived_at"] = now_iso()
            data["workers"][n] = current
            save_registry(data)
            append_event("archived", n, session_id=sid, retired_count=len(retired))
            archived_count += 1

        _archive_move_and_rm(n, sid, retired, _archive_dest_dir(n),
                             roster_entries, run, which)

    # T9 fix wave (finding C2/3b): resumed workers were ALREADY counted as
    # archived by whichever earlier run first stamped their archived_at --
    # this run is pure cleanup (finish the move, retry any un-rm'd sid), so
    # it neither adds to archived_count nor appends another "archived"
    # event; it just reports progress per worker.
    for n in resume_names:
        rec = before[n]
        sid = rec.get("session_id")
        retired = list(rec.get("retired_sids", []) or [])
        print(f"fleet: {n}: resuming archive -- completing pending file moves",
              file=sys.stderr)
        _archive_move_and_rm(n, sid, retired, archive_root() / n,
                             roster_entries, run, which)

    skipped_count = len(names) - archived_count
    print(f"archived {archived_count} worker(s), skipped {skipped_count}")
    return 0


# ---------------------------------------------------------------------------
# Autoclean (docs/specs/autoclean.md): staleness cleaned up without anyone
# remembering. One mutating command, three callers (the Scheduled Task
# `fleet init --autoclean` installs, a supervisor beat, an operator by
# hand). Tier 1 = the existing archive TTL pass; tier 2 = daemon-husk
# removal under a sid-based default-deny ownership discriminator; tier 3
# (default-OFF) = registry tombstone expiry, never file deletion --
# `fleet clean` stays the only deleter.
# ---------------------------------------------------------------------------

AUTOCLEAN_TASK_NAME = "claude-fleet-autoclean"
AUTOCLEAN_INTERVAL_HOURS_DEFAULT = 6
AUTOCLEAN_STALE_RUN_HOURS = 48.0


def autoclean_stamp_path() -> Path:
    return state_dir() / "autoclean-last-run.json"


def _registry_owned_and_protected_sids(workers: dict) -> tuple:
    """(owned, protected) sid sets from the registry snapshot. owned =
    every session_id/retired_sid of every record INCLUDING tombstones;
    protected = the same fields of NON-archived records only (a tracked,
    live worker's history belongs to `fleet archive`, never the husk
    sweep). Field-shape drift tolerated the same way the doctor's
    claude-agents check tolerates it: non-dict records, non-str sids and
    non-list retired_sids are skipped, never trusted."""
    owned, protected = set(), set()
    for rec in workers.values():
        if not isinstance(rec, dict):
            continue
        sids = []
        sid = rec.get("session_id")
        if isinstance(sid, str):
            sids.append(sid)
        retired = rec.get("retired_sids")
        if isinstance(retired, list):
            sids.extend(s for s in retired if isinstance(s, str))
        owned.update(sids)
        if rec.get("archived_at") is None:
            protected.update(sids)
    return owned, protected


def _archive_dir_sids() -> set:
    """Sid-shaped filenames under logs/archive/*/ -- owned history that
    survives even after `fleet clean` deletes the registry tombstone."""
    out = set()
    root = archive_root()
    try:
        if not root.exists():
            return out
        for path in root.glob("*/*"):
            stem = path.stem
            if _SID_SHAPE_RE.match(stem):
                out.add(stem)
    except OSError:
        pass
    return out


def _events_sids() -> set:
    """Every session_id fleet ever stamped into events.jsonl
    (turn_started/archived/cleaned/...) -- the ownership source that
    survives `fleet clean` removing the registry entry entirely.
    Unparseable lines are skipped, never fatal."""
    out = set()
    try:
        with open(events_path(), encoding="utf-8") as fh:
            for line in fh:
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                sid = ev.get("session_id") if isinstance(ev, dict) else None
                if isinstance(sid, str):
                    out.add(sid)
    except OSError:
        pass
    return out


def _sweep_husks(dry_run: bool, run=subprocess.run, which=shutil.which) -> list:
    """Tier 2 (autoclean.md D2): `claude rm` roster sessions fleet owns but
    no longer tracks live. Default-deny: a sid absent from every fleet
    record -- foremost the operator's own interactive sessions -- is never
    selected. Returns the list of removed sids; raises FleetCliError when
    the roster is unavailable/suspicious (the caller isolates tiers).

    F1 (adversarial review, HIGH): default-deny includes "no registry = no
    sweep". A corrupt fleet.json gets quarantine-RENAMED by whichever tier
    loads it first, so the next load sees a MISSING file and returns empty
    workers -- emptying the protected set while events.jsonl/logs/archive
    still vouch those sids as owned, which would rm the resumable session
    of every idle/limited/interrupted worker. The guard lives HERE (not
    only in the caller) so the NEXT scheduled run after a quarantine
    cannot fail open either: registry absent + any owned-evidence present
    => refuse, exactly like the G9 epoch refusal. A genuinely fresh home
    (no registry, no evidence) still proceeds -- nothing is owned, the
    sweep is a no-op. A present-but-corrupt registry raises
    RegistryCorruptError from load_registry; the caller treats that as
    run-abort, never tier-skip."""
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        raise FleetCliError(f"husk sweep skipped: {payload}")
    with fleet_lock():
        registry_missing = not registry_path().exists()
        data = {"workers": {}} if registry_missing else load_registry()
    # NEW-1 (re-review, MED): the F1 absence check alone has two repro'd
    # bypasses -- a routine spawn recreates fleet.json with one record, and
    # an operator "recreating" an empty registry does the same: either way
    # the file is PRESENT, the protected set is thin, and every
    # pre-quarantine worker's events-vouched session becomes rm-eligible.
    # So: any quarantine artifact on disk refuses the sweep outright,
    # registry present or not. Deliberate deviation from the reviewed
    # "artifact newer than current fleet.json" comparison: os.rename
    # preserves mtime, so the artifact's mtime is the PRE-corruption write
    # time and any recreated registry is always newer -- the comparison
    # would never fire on exactly the spawn-recreation bypass it exists to
    # stop. Presence-only is the sound superset; the operator clears the
    # artifact (after restoring what it holds) to re-arm the sweep.
    quarantine_artifacts = sorted(state_dir().glob("fleet.json.corrupt.*"))
    if quarantine_artifacts:
        raise FleetCliError(
            f"husk sweep refused: quarantine artifact present "
            f"({quarantine_artifacts[-1].name}) -- a corrupt registry was "
            f"renamed aside and its workers may be missing from the current "
            f"one; restore the quarantined file, then remove the artifact (NEW-1)")
    if registry_missing and (_events_sids() or _archive_dir_sids()):
        raise FleetCliError(
            "husk sweep refused: the registry (state/fleet.json) is missing "
            "while fleet evidence (events.jsonl / logs/archive) exists -- "
            "possible quarantine aftermath; restore the quarantined file first (F1)")
    workers = data.get("workers", {})
    if native_epoch_suspicious(roster_ok, payload, workers):
        raise FleetCliError("husk sweep refused: roster suspicious (G9)")

    owned, protected = _registry_owned_and_protected_sids(workers)
    owned |= _archive_dir_sids()
    owned |= _events_sids()

    removed = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sessionId")
        if not isinstance(sid, str):
            continue
        if sid not in owned or sid in protected:
            continue
        if "status" in entry or "pid" in entry:
            continue  # live session -- never touched (same test as archive gate 3)
        try:
            mailbox = mailbox_dir() / f"{sid}.md"
            if mailbox.exists() and mailbox.stat().st_size > 0:
                continue  # pending mail is not garbage
        except OSError:
            continue  # can't prove no mail -- fail safe, skip
        display = entry.get("name") if isinstance(entry.get("name"), str) else sid[:8]
        if dry_run:
            print(f"husk: would rm {sid} ({display})")
            continue
        if _rm_native_session(sid, run=run, which=which):
            append_event("husk_removed", display, session_id=sid)
            print(f"husk: rm {sid} ({display})")
            removed.append(sid)
        else:
            print(f"husk: rm {sid} FAILED -- left in place", file=sys.stderr)
    return removed


def _expire_tombstones(expire_hours: float, dry_run: bool) -> list:
    """Tier 3 (autoclean.md D2, opt-in only): pop registry tombstones whose
    archived_at is older than `expire_hours` AND whose evidence move is
    complete. Deletes NO files -- logs/archive/<name>/ stays on disk, so
    `fleet clean` remains the only deleter. Returns [(name, sid), ...]."""
    expired = []
    now = datetime.now(timezone.utc)
    with fleet_lock():
        data = load_registry()
        for n, rec in sorted(data.get("workers", {}).items()):
            if not isinstance(rec, dict) or rec.get("archived_at") is None:
                continue
            try:
                archived_at = _parse_iso(rec.get("archived_at"))
            except (ValueError, TypeError):
                continue  # unparseable stamp -- never expire on bad data
            if (now - archived_at).total_seconds() / 3600.0 < expire_hours:
                continue
            if _archive_resume_pending(n, rec):
                continue  # evidence files not fully moved -- keep the tombstone
            if dry_run:
                print(f"tombstone: would expire {n}")
                continue
            expired.append((n, rec.get("session_id")))
        if expired:
            for n, _sid in expired:
                data["workers"].pop(n, None)
            save_registry(data)
            for n, sid in expired:
                append_event("tombstone_expired", n, session_id=sid)
                print(f"tombstone: expired {n} (archive dir kept on disk)")
    return expired


def cmd_autoclean(args, run=subprocess.run, which=shutil.which) -> int:
    """`fleet autoclean [--ttl-hours F] [--expire-tombstones-hours F]
    [--dry-run]` (docs/specs/autoclean.md): tier 1 archive TTL pass +
    tier 2 husk sweep, tier 3 tombstone expiry only with its flag. Tiers
    are isolated -- one tier failing never blocks the next (D3); errors
    land in stderr, the run stamp, one `autoclean_run` event, and exit 1.

    F1 exception to tier isolation: RegistryCorruptError ABORTS THE WHOLE
    RUN (re-raised, no stamp, exit via main's handler). Isolation exists so
    an environmental hiccup in one tier doesn't waste the others; a corrupt
    registry is not a hiccup -- tier 1's load already quarantine-renamed
    the file, so "continue to tier 2" means sweeping against a missing
    registry, the exact fail-open the reviewer repro'd.

    `--fleet-home` (F2): overrides the module FLEET_HOME before anything
    reads a path -- the scheduled task carries it because Task Scheduler
    provides no operator environment for the env-var route."""
    fleet_home_override = getattr(args, "fleet_home", None)
    if fleet_home_override:
        # NEW-2 (re-review, LOW): resolve + validate, never use verbatim --
        # a relative path is cwd-dependent (System32 under Task Scheduler)
        # and a nonexistent home would be silently mkdir'd into a phantom
        # (fleet_lock/stamp writes create state/ even under --dry-run).
        resolved_home = Path(fleet_home_override).resolve()
        if not resolved_home.is_dir():
            raise FleetCliError(
                f"--fleet-home does not exist or is not a directory: "
                f"{resolved_home} (from {fleet_home_override!r})")
        global FLEET_HOME
        FLEET_HOME = resolved_home
    dry_run = bool(getattr(args, "dry_run", False))
    ttl_hours = getattr(args, "ttl_hours", None)
    expire_hours = getattr(args, "expire_tombstones_hours", None)
    errors = []

    archive_rc = None
    try:
        archive_args = argparse.Namespace(name=None, ttl_hours=ttl_hours, dry_run=dry_run)
        archive_rc = cmd_archive(archive_args, run=run, which=which)
        if archive_rc != 0:
            errors.append(f"archive: exit {archive_rc}")
    except RegistryCorruptError:
        raise  # F1: run-abort, never tier-skip
    except Exception as exc:  # noqa: BLE001 -- tier isolation (D3)
        errors.append(f"archive: {type(exc).__name__}: {exc}")
        print(f"autoclean: archive tier failed: {exc}", file=sys.stderr)

    husks = []
    try:
        husks = _sweep_husks(dry_run, run=run, which=which)
    except RegistryCorruptError:
        raise  # F1: run-abort, never tier-skip
    except Exception as exc:  # noqa: BLE001 -- tier isolation (D3)
        errors.append(f"husks: {type(exc).__name__}: {exc}")
        print(f"autoclean: husk tier failed: {exc}", file=sys.stderr)

    tombstones = []
    if expire_hours is not None:
        try:
            tombstones = _expire_tombstones(expire_hours, dry_run)
        except RegistryCorruptError:
            raise  # F1: run-abort, never tier-skip
        except Exception as exc:  # noqa: BLE001 -- tier isolation (D3)
            errors.append(f"tombstones: {type(exc).__name__}: {exc}")
            print(f"autoclean: tombstone tier failed: {exc}", file=sys.stderr)

    summary = {"ts": now_iso(), "dry_run": dry_run, "archive_rc": archive_rc,
               "husks_removed": len(husks), "tombstones_expired": len(tombstones),
               "errors": errors}
    if not dry_run:
        try:
            state_dir().mkdir(parents=True, exist_ok=True)
            autoclean_stamp_path().write_text(json.dumps(summary), encoding="utf-8")
        except OSError as exc:
            errors.append(f"stamp: {exc}")
        try:
            append_event("autoclean_run", "*", archive_rc=archive_rc,
                         husks_removed=len(husks),
                         tombstones_expired=len(tombstones), errors=errors)
        except OSError as exc:
            print(f"autoclean: event append failed: {exc}", file=sys.stderr)
    print(f"autoclean: husks_removed={len(husks)} tombstones_expired={len(tombstones)}"
          f" errors={len(errors)}{' (dry-run)' if dry_run else ''}")
    return 1 if errors else 0


def _autoclean_script_path() -> Path:
    """The fleet.py the scheduled task will pin. A seam (monkeypatchable)
    so tests can model canonical-vs-worktree installs without moving files."""
    return Path(__file__).resolve()


def _autoclean_task_command() -> str:
    """The Scheduled Task's command line: the exact interpreter running
    this `fleet init` plus this fleet.py -- mirroring cmd_init's own
    sys.executable-as-{{PYTHON}} doctrine (a scheduled task cannot fall
    back to a bare `py` on PATH either).

    F2 (adversarial review, HIGH): FLEET_HOME is embedded EXPLICITLY as an
    argv flag -- Task Scheduler runs with no operator environment, so
    without it fleet.py falls back to script-location resolution and the
    task sweeps whatever repo copy it happens to live in (a worktree's
    empty state/, forever, doctor green) instead of the operator's home."""
    py = Path(sys.executable).resolve()
    script = _autoclean_script_path()
    home = Path(FLEET_HOME).resolve()
    return f'"{py}" "{script}" autoclean --fleet-home "{home}"'


def _marker_guard_problems() -> list:
    """N1: the home-guard subset that protects GLOBAL machine state (the
    ~/.claude/fleet-home marker): the resolved home being a linked git
    worktree, or an existing marker that already points elsewhere. Shared
    by `cmd_init`'s marker stamp -- which must evaluate these BEFORE
    writing anything, or a worktree init repoints the marker and thereby
    defeats the very marker-mismatch guard the autoclean install relies
    on -- and by `_install_autoclean_task` (which adds its own
    script-location check on top). Deliberately EXCLUDES that script
    check: a sandboxed/relocated home with no .git file and no
    conflicting marker is a legitimate marker target."""
    home = Path(FLEET_HOME).resolve()
    problems = []
    if (home / ".git").is_file():
        problems.append(f"{home} is a linked git worktree (.git is a file) -- "
                        "a task pinned here dies with the worktree")
    marker_home = None
    try:
        marker = fleet_home_marker_path()
        if marker.exists():
            marker_home = Path(marker.read_text(encoding="utf-8").strip()).resolve()
    except (OSError, ValueError):
        marker_home = None
    if marker_home is not None and marker_home != home:
        problems.append(f"machine fleet-home marker points at {marker_home}, not {home}")
    return problems


def _autoclean_task_is_ours(command: str) -> bool:
    """F4: ownership = the existing task runs OUR fleet.py -- the exact
    resolved script path, slash- and case-normalized (Windows paths carry
    both variances through schtasks XML round-trips). Never a substring
    like 'autoclean': a foreign C:/tools/autoclean.exe task must refuse."""
    ours = str(_autoclean_script_path()).replace("\\", "/").lower()
    return ours in (command or "").replace("\\", "/").lower()


def _install_autoclean_task(interval_hours, force: bool) -> None:
    if interval_hours is None:
        interval_hours = AUTOCLEAN_INTERVAL_HOURS_DEFAULT
    interval_hours = int(interval_hours)
    if not 1 <= interval_hours <= 23:
        raise FleetCliError("--autoclean-interval-hours must be 1..23 (schtasks /SC HOURLY /MO)")

    # F2 home guards: a scheduled task outlives this shell -- refuse to pin
    # it to a fleet.py that is not the target home's own copy, to a linked
    # git worktree (dies with the worktree), or to a home that contradicts
    # the machine's fleet-home marker. --force overrides all three.
    home = Path(FLEET_HOME).resolve()
    script = _autoclean_script_path()
    problems = []
    if script.parent.parent != home:
        problems.append(f"this fleet.py ({script}) is not the target home's copy ({home})")
    problems += _marker_guard_problems()
    if problems and not force:
        raise FleetCliError(
            "autoclean install refused (F2): " + "; ".join(problems) +
            " -- run from the canonical fleet home, or rerun with --force")

    command = _autoclean_task_command()
    try:
        existing = PLATFORM.autoclean_task_query(AUTOCLEAN_TASK_NAME)
    except AutocleanTaskQueryError as exc:
        # F3: fail closed -- unknown existence must not become /Create /F.
        if not force:
            raise FleetCliError(
                f"cannot determine whether task {AUTOCLEAN_TASK_NAME!r} already "
                f"exists ({exc}) -- retry, or rerun with --force to install anyway")
        existing = None
    if existing is not None and not _autoclean_task_is_ours(existing) and not force:
        raise FleetCliError(
            f"scheduled task {AUTOCLEAN_TASK_NAME!r} exists and is not "
            f"fleet-owned (does not run this fleet.py; found {existing[:120]!r}) "
            f"-- rerun with --force to overwrite")
    ok, msg = PLATFORM.autoclean_task_install(AUTOCLEAN_TASK_NAME, command, interval_hours)
    if not ok:
        raise FleetCliError(f"schtasks create failed: {msg}")
    print(f"fleet init: scheduled task {AUTOCLEAN_TASK_NAME!r} installed "
          f"(every {interval_hours}h)")
    print(f"  command:   {command}")
    print(f"  uninstall: fleet init --autoclean-remove "
          f"(or: schtasks /Delete /TN {AUTOCLEAN_TASK_NAME} /F)")


def _remove_autoclean_task() -> None:
    ok, msg = PLATFORM.autoclean_task_remove(AUTOCLEAN_TASK_NAME)
    if not ok:
        raise FleetCliError(f"schtasks delete failed: {msg}")
    print(f"fleet init: scheduled task {AUTOCLEAN_TASK_NAME!r} removed")


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


_PIN_VERSION_ECHO_LIMIT = 40


def _clamp_version_echo(s: str, limit: int = _PIN_VERSION_ECHO_LIMIT) -> str:
    """Bounds an untrusted, stored version-ish string before it's
    interpolated into a doctor message -- a pin file can carry an
    arbitrarily long digit run (still a valid _parse_claude_version match)
    or, pre-parse, an arbitrarily long raw string; either way the message
    stays a single sane terminal line."""
    s = str(s)
    return s if len(s) <= limit else s[:limit] + "..."


def _doctor_check_pin_version(which=shutil.which, run=subprocess.run):
    """M-B T11 (docs/specs/native-substrate.md, Re-verification): the native
    contract (roster schema, transcript keys, --bg/--resume behavior) was
    observed against one specific `claude --version` and is not guaranteed
    to survive an update. FAIL is reserved for a confirmed mismatch against
    the last recorded pin-test pass -- everything else (no pin file yet,
    `claude` unresolvable, or a pin record whose claude_version doesn't
    parse -- missing, None, non-str, or otherwise not version-shaped) is a
    PASS-note, since none of those mean the contract is currently broken,
    only that it hasn't been (re)verified or the record is unreadable.

    M-B T11 fix wave: BOTH sides of the comparison are normalized through
    _parse_claude_version before comparing, not just the live side --
    otherwise a pin-pass recorded from a raw, unparsed `claude --version`
    capture (e.g. "2.1.207 (Claude Code)\\n") permanently FAILs against
    the identical, unchanged live version, purely on formatting. A pinned
    value that fails to parse at all (field-corrupt pin-pass.json: absent
    key, None, int, nested dict, ...) is treated the same as an invalid/
    unreadable pin record -- a PASS-note, never a FAIL, since a bad record
    is not evidence the contract itself is broken.

    Deliberately double-shells `claude --version` rather than sharing
    `_doctor_check_claude_version`'s subprocess result: that check returns
    an already-formatted (name, ok, message) tuple, not the parsed version,
    and threading a shared raw result through both call sites/signatures
    would contort an otherwise-simple check for the sake of one skipped
    subprocess call in a diagnostic (never-hot-path) command."""
    pin = read_pin_pass()
    if pin is None:
        return ("pin-version", True,
                "no pin-test pass recorded -- run FLEET_LIVE=1 py -3.13 -m pytest "
                "tests/integration/test_native_pin.py")
    try:
        exe = resolve_claude_executable(which=which)
        result = run([exe, "--version"], capture_output=True, text=True, timeout=10)
    except Exception:
        return ("pin-version", True, "claude not resolvable")
    live = _parse_claude_version((result.stdout or "") + (result.stderr or ""))
    if live is None:
        return ("pin-version", True, "claude not resolvable")
    live_str = ".".join(map(str, live))
    pinned_raw = pin.get("claude_version")
    pinned = _parse_claude_version(pinned_raw) if isinstance(pinned_raw, str) else None
    if pinned is None:
        return ("pin-version", True, "pin record unreadable -- re-run pin suite")
    pinned_str = ".".join(map(str, pinned))
    if live_str != pinned_str:
        return ("pin-version", False,
                f"claude {_clamp_version_echo(live_str)} != {_clamp_version_echo(pinned_str)} "
                f"at last pin pass ({pin.get('passed_at')}) -- native contract unverified "
                "(docs/specs/native-substrate.md, Re-verification)")
    return ("pin-version", True,
            f"pin-test pass current ({_clamp_version_echo(live_str)}, {pin.get('passed_at')})")


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


def _doctor_check_legacy_mix(workers: dict):
    """M-B T11 (spec §5.1 coexistence): advisory-only (always ok=True) --
    a legacy (pre-pivot, `dispatch_kind` absent) record is read-only, not
    broken; naming it just points the operator at `kill`/`clean`. Archived
    records are excluded even though they're also non-native, since they're
    already history and doctor's other archived-aware checks cover them."""
    legacy = sorted(name for name, rec in workers.items()
                    if not is_native(rec) and rec.get("archived_at") is None)
    if legacy:
        return ("legacy-mix", True,
                f"{len(legacy)} pre-pivot worker(s): {', '.join(legacy)} -- read-only; "
                "kill or clean (spec 5.1 coexistence)")
    return ("legacy-mix", True, "no pre-pivot workers")


def _doctor_check_dead_suspected(workers: dict):
    """M-B T11: advisory-only (always ok=True) -- `dead-suspected` is a
    recomputable verdict, never sticky (never auto-respawned), so doctor
    just names current holders from the snapshot it was handed; it does not
    recompute (a stale label here is fine -- doctor is point-in-time)."""
    names = sorted(name for name, rec in workers.items() if rec.get("status") == "dead-suspected")
    if names:
        return ("dead-suspected", True,
                f"{len(names)} dead-suspected worker(s): {', '.join(names)} -- no outcome record; "
                "inspect via fleet peek/result, then kill or respawn")
    return ("dead-suspected", True, "no dead-suspected workers")


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
    # M-B T11: a fork-steer/respawn retires the old sid into `retired_sids`
    # but never rm's it (spec §5.1); an archived worker's own rm is
    # best-effort and can still leave a retired sid lingering in the roster.
    # Counting only the CURRENT session_id would keep re-reporting those as
    # "fleet-unknown" forever -- every retired sid is still fleet-tracked
    # history, so it belongs in known_sids too.
    # M-B T11 fix wave: registry field-shape drift (hand-repaired records,
    # partial schema migrations) can hand this loop a non-dict record, a
    # missing session_id, or a retired_sids value that isn't a list (e.g.
    # a bare sid string, which would otherwise silently char-spread via
    # set.update() on a str). Every shape is skipped/normalized rather
    # than trusted, so a corrupt field degrades this to a no-op instead
    # of a crash or a silently-wrong known_sids set.
    known_sids = set()
    for rec in workers.values():
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id")
        if isinstance(sid, str):
            known_sids.add(sid)
        retired_sids = rec.get("retired_sids")
        if isinstance(retired_sids, list):
            known_sids.update(s for s in retired_sids if isinstance(s, str))
    unknown = sorted({
        sid for a in agents if isinstance(a, dict)
        for sid in [a.get("session_id") or a.get("id")]
        if sid and sid not in known_sids
    })
    if unknown:
        return ("claude-agents", True, f"{len(unknown)} claude agent session(s) not tracked by fleet: {', '.join(unknown)}")
    return ("claude-agents", True, "no fleet-unknown claude agent sessions")


def _doctor_check_autoclean(run=subprocess.run):
    """Note-only (docs/specs/autoclean.md D4): reports scheduler-task state
    (installed/missing) and last-run staleness from the run stamp. Never
    turns doctor red -- a missing task is a choice, not broken plumbing.

    LOW advisory (confirmation pass): a fresh timestamp alone can lie --
    the stamp's `errors` array and a lingering fleet.json.corrupt.*
    artifact (which makes tier 2 refuse itself, NEW-1) both mean the sweep
    is NOT actually doing its job. Both are appended to whichever note is
    returned, so a bricked sweep never reads green-and-fresh."""
    stamp_note, stale, run_errors = "no run recorded yet", False, []
    try:
        raw = json.loads(autoclean_stamp_path().read_text(encoding="utf-8"))
        last = _parse_iso(raw.get("ts"))
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        stamp_note = f"last run {age_h:.1f}h ago"
        stale = age_h > AUTOCLEAN_STALE_RUN_HOURS
        errs = raw.get("errors")
        if isinstance(errs, list):
            run_errors = [str(e) for e in errs if e]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    extras = []
    if run_errors:
        extras.append(f"last run reported {len(run_errors)} error(s): "
                      f"{run_errors[0][:120]}")
    try:
        artifacts = sorted(state_dir().glob("fleet.json.corrupt.*"))
    except OSError:
        artifacts = []
    if artifacts:
        extras.append(f"quarantine artifact present ({artifacts[-1].name}) -- "
                      f"husk sweep is refusing itself (NEW-1); restore the "
                      f"quarantined data, then remove the artifact")
    suffix = ("; " + "; ".join(extras)) if extras else ""

    try:
        existing = PLATFORM.autoclean_task_query(AUTOCLEAN_TASK_NAME, run=run)
    except UnsupportedPlatformError:
        return ("autoclean", True,
                f"scheduler query unsupported on this platform -- skipped{suffix}")
    except AutocleanTaskQueryError as exc:
        return ("autoclean", True,
                f"scheduler query failed ({exc}) -- state unknown; {stamp_note}{suffix}")
    if existing is None:
        return ("autoclean", True,
                f"no scheduled task installed (fleet init --autoclean) -- "
                f"staleness sweeps are manual; {stamp_note}{suffix}")
    # F2: a task pinned to a deleted worktree's fleet.py fails silently on
    # every trigger -- flag it (note-only, but actionable).
    for tok in re.findall(r'"([^"]+)"', existing):
        if tok.lower().endswith("fleet.py") and not Path(tok).exists():
            return ("autoclean", True,
                    f"task installed but pinned to a missing path ({tok}) -- "
                    f"reinstall from the canonical home: fleet init --autoclean{suffix}")
    if stale:
        return ("autoclean", True,
                f"task installed but {stamp_note} (> {AUTOCLEAN_STALE_RUN_HOURS:.0f}h) "
                f"-- scheduler may be stale{suffix}")
    return ("autoclean", True, f"task installed; {stamp_note}{suffix}")


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


def cmd_doctor(args, which=shutil.which, run=subprocess.run) -> int:
    """`fleet doctor` (SPEC §5 doctor row, §7 silent-failure alarm): runs
    every health check below and prints one [PASS]/[FAIL] line each;
    exits nonzero iff any check is not ok.

    Snapshots the registry under one fleet_lock() then runs every check
    OUTSIDE the lock: several checks shell out (claude --version, claude
    agents --json, two real hook-smoke subprocesses) and holding fleet_lock
    across them would starve every concurrent `fleet` command (F4
    doctrine)."""
    with fleet_lock():
        data = load_registry()
    workers = data.get("workers", {})

    check_calls = [
        functools.partial(_doctor_check_claude_version, which=which, run=run),
        functools.partial(_doctor_check_pin_version, which=which, run=run),
        functools.partial(_doctor_check_instance_settings),
        functools.partial(_doctor_check_instance_freshness),
        functools.partial(_doctor_check_hook_registration),
        functools.partial(_doctor_check_legacy_settings),
        functools.partial(_doctor_check_posttooluse_hook_smoke, run=run),
        functools.partial(_doctor_check_stop_hook_smoke, run=run),
        functools.partial(_doctor_check_terminal_launcher, which=which),
        functools.partial(_doctor_check_mailboxes, workers),
        functools.partial(_doctor_check_stale_attaches, workers),
        functools.partial(_doctor_check_limited_parks, workers),
        functools.partial(_doctor_check_legacy_mix, workers),
        functools.partial(_doctor_check_dead_suspected, workers),
        functools.partial(_doctor_check_orphaned_claims, workers=workers),
        functools.partial(_doctor_check_claude_agents, workers, which=which, run=run),
        functools.partial(_doctor_check_autoclean, run=run),
        functools.partial(_doctor_check_fleet_home_marker),
        functools.partial(_doctor_check_hook_errors),
        functools.partial(_doctor_check_supervisor_claim),
        functools.partial(_doctor_check_supervisor_handoff),
    ]

    # M-B T11 fix wave: each check runs in isolation -- a raising check
    # (realistically reachable via registry field-shape drift, e.g. a
    # hand-repaired or partially-migrated worker record) must not take
    # down every OTHER check's [PASS]/[FAIL] line with it. Convert a
    # crash into its own FAIL line, keyed by the check function's name
    # since a raising check never got the chance to produce its own
    # (name, ok, message) tuple.
    checks = []
    for check_fn in check_calls:
        try:
            checks.append(check_fn())
        except Exception as exc:
            fn_name = check_fn.func.__name__
            exc_msg = str(exc)[:200]
            checks.append((fn_name, False, f"check crashed: {type(exc).__name__}: {exc_msg}"))

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
        # Roll-up item 4: a partial write (ok=True, written.value < len(data))
        # produces a torn JSONL line that read_outcomes silently skips --
        # the exact silent-loss failure class T1's CRITICAL fix existed to
        # kill. Treat it the same as a WriteFile failure: raise OSError
        # (already inside this function's raise-OSError contract).
        if not ok or written.value != len(data):
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


def has_fresh_outcome(name: str, sid: str, since_iso: str,
                      kinds: tuple = ("result",)) -> bool:
    """T5 fix wave (Critical C1): `kinds` defaults to `("result",)` -- ONLY
    a Stop-hook-written completion record vouches for "idle" by default. A
    tombstone (`TOMBSTONE_KINDS`: killed/interrupted/stopped, written by
    fleet itself on an operator-initiated stop) is a DIFFERENT signal --
    the session did NOT end on its own -- and must never be read as "the
    turn finished cleanly" just because a record with a fresh ts exists.
    Before this fix, an unfiltered match let a fresh tombstone launder an
    operator kill into a false "idle" verdict during the window between
    the tombstone write and the registry status flip (two separate,
    non-transactional writes -- see task-5-adversarial.md C1). Callers
    that genuinely need to match tombstone kinds (none yet in this task)
    can pass `kinds=TOMBSTONE_KINDS` or a wider tuple explicitly."""
    try:
        since = _parse_iso(since_iso)
    except (ValueError, TypeError):
        return False
    threshold = since - timedelta(seconds=OUTCOME_FRESH_SLACK_SECONDS)
    for rec in read_outcomes(name, sid=sid):
        if rec.get("kind") not in kinds:
            continue
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


def _stop_native_session(sid: str, run=subprocess.run, which=shutil.which,
                         timeout: int = 30) -> bool:
    """`claude stop <sid>` (contract G10): the only sanctioned way to end a
    --bg-managed session -- a raw pid kill triggers a silent daemon respawn
    under the same sid (G10, never raw-kill). True iff the stop's own exit
    code was 0. Never raises: an unresolvable `claude` executable, or any
    OSError/SubprocessError (including TimeoutExpired) from the subprocess
    call, both resolve to False -- the caller (cmd_respawn --force) treats
    False as "could not verify the stop" and re-checks the roster before
    ever proceeding (never claim two live sessions under one name).

    T8 fix wave (adv I1): `timeout` defaults to 30s (the primary/current
    sid's budget) but `_cmd_kill_native`'s retired-sid sweep passes 5s --
    those stops are best-effort only and unbounded wall-time across a
    long-lived worker's whole retired_sids history is the actual defect
    being fixed, not the primary sid's own stop.

    T12 fix wave (finding 2): `claude stop` requires the SHORT id -- converts
    via `_native_job_ref` first; on a nonzero exit, retries once with the
    full sid (belt-and-braces against a future CLI accepting full ids)."""
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError:
        return False
    refs = dict.fromkeys((_native_job_ref(sid), sid))
    for ref in refs:
        try:
            proc = run([exe, "stop", ref], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode == 0:
            return True
    return False


def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
    """Mutate `record` in place after a fork-steer (`send`'s idle path,
    `resume-limited`'s native branch): retire the OLD sid into
    retired_sids, restamp session_id/native_short_id to the new fork,
    stamp last_dispatch_at (the fresh-outcome anchor for the NEXT
    recompute), and bump turns -- mirrors _resume_one_limited_native's
    inline commit shape, shared here so `send` and a future resume-limited
    refactor stay in lockstep.

    S2 fix (final wave), defense-in-depth: never append a None into
    retired_sids -- a caller reached here with `record["session_id"]` is
    None (e.g. a respawn --force's fresh pre-claim) would otherwise poison
    retired_sids, which `_cmd_kill_native`'s sweep later feeds straight into
    `_stop_native_session(None)` -> `run([exe, "stop", None])`, a TypeError
    outside the caught (OSError, SubprocessError) tuple."""
    old_sid = record["session_id"]
    if old_sid is not None:
        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
    record["session_id"] = new_sid
    record["native_short_id"] = short_id
    record["last_dispatch_at"] = now_iso()
    record["turns"] = record.get("turns", 0) + 1


def _migrate_residual_mailbox(old_sid: str, new_sid: str) -> None:
    """T7 fix wave (CRITICAL-2 fix 2c): called at every steer-restamp commit
    (`send`'s idle fork-steer, `resume-limited`'s native branch) right after
    the registry has been restamped to `new_sid`. A steering message can
    race into `mailbox/<old_sid>.md` AFTER `compose_prompt` already
    claimed/drained it for this fork's dispatch (e.g. a concurrent send
    that lost the raw-status race in `_cmd_send_native` and queued its
    message against the OLD sid, per FIX-2b) -- that message must still
    follow the worker, not be stranded under a sid the registry will never
    reference again. Best-effort: any OSError here must never fail a steer
    commit that has already succeeded, and a missing/empty old mailbox is
    the overwhelmingly common case (no-op)."""
    old_path = mailbox_dir() / f"{old_sid}.md"
    try:
        if not old_path.exists():
            return
        content = old_path.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            new_path = mailbox_dir() / f"{new_sid}.md"
            with open(new_path, "a", encoding="utf-8") as f:
                f.write(content.rstrip("\n") + "\n\n")
        old_path.unlink()
    except OSError:
        pass


def _fast_completion_sid(name: str, since_iso: str, short_id: str | None = None):
    """T4 fix wave (Critical C1): cmd_spawn's fast-completion check on a
    NativeDispatchError, keeping dispatch_bg opaque (no message parsing)
    per the brief's own suggested alternative -- but the exception now
    carries `short_id` as a real attribute (NativeDispatchError.short_id)
    instead of being buried in the message text, so this function can use
    it directly.

    Scans TWO sources for the newest record with ts >= since_iso -
    OUTCOME_FRESH_SLACK_SECONDS, returning its session_id (or None if
    nothing matches):

    1. outcomes/<name>.jsonl (name-keyed) -- reachable only when the Stop
       hook's registry scan (_resolve_name) found a record whose
       session_id already equalled the real sid, which requires the
       stamp to have landed first.
    2. When `short_id` is given: every outcomes/<stem>.jsonl in
       outcomes_dir() whose stem startswith(short_id) -- the Stop hook's
       OWN fallback key (`_resolve_name(...) or sid`) when name
       resolution fails, which is exactly what happens during the fast-
       completion race this function exists to handle: cmd_spawn's
       pre-claim record still has session_id=None when the hook fires,
       so `_resolve_name` can never match it, and the hook writes
       outcomes/<real-sid>.jsonl instead of outcomes/<name>.jsonl. A real
       sid always startswith its own short id (the short id IS a prefix
       of the sid, per _parse_bg_short_id/_join_roster_by_short_id), so
       this glob is the only way to locate that file without already
       knowing the sid -- which is the whole point of scanning for it."""
    try:
        since = _parse_iso(since_iso)
    except (ValueError, TypeError):
        return None
    threshold = since - timedelta(seconds=OUTCOME_FRESH_SLACK_SECONDS)
    best_sid, best_ts = None, None

    def _consider(rec):
        nonlocal best_sid, best_ts
        # T5 fix wave (Critical C1 audit): a tombstone (kind in
        # TOMBSTONE_KINDS) means the session was operator-stopped, not that
        # it finished on its own -- it can never mean "fast completion".
        # Only a Stop-hook-written kind=="result" record counts.
        if rec.get("kind") != "result":
            return
        try:
            ts = _parse_iso(str(rec.get("ts", "")))
        except (ValueError, TypeError):
            return
        if ts >= threshold and rec.get("session_id") and (best_ts is None or ts > best_ts):
            best_sid, best_ts = rec.get("session_id"), ts

    for rec in read_outcomes(name):
        _consider(rec)

    if short_id:
        for path in sorted(outcomes_dir().glob("*.jsonl")):
            if not path.stem.startswith(short_id):
                continue
            try:
                text = path.read_text(encoding="utf-8")
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
                    _consider(rec)

    return best_sid


# --------------------------------------------------------------------------
# Native dispatch (M-B, spec §5): single choke point for every --bg launch.
# Task-file bootstrap (G8), short-id capture + sid-prefix roster join (G6
# fallback), fresh -n render per dispatch (G13 / spec §5.1.3).
# --------------------------------------------------------------------------

NATIVE_JOIN_VERIFY_SECONDS = 60.0   # keep in sync with SUPERVISOR_ROSTER_VERIFY_SECONDS below (same window, independently defined -- Finding 3)
NATIVE_JOIN_POLL_SECONDS = 3.0
NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0
DEFAULT_CATEGORY = "fleet"
NATIVE_NAME_HINT_MAX = 40

# · = MIDDLE DOT (the daemon's literal separator glyph). Previously a
# duplicate-codepoint char class `[··]` (same character twice) -- collapsed
# to a single literal, behavior-identical.
_BG_SHORT_ID_RE = re.compile(r"backgrounded\s*·\s*(\S+)\s*·")

# T12 fix wave (finding 3, discovered during live verification): the daemon
# colorizes the short id in `--bg` stdout whenever the CHILD inherits a
# color-forcing env var (FORCE_COLOR/CLICOLOR_FORCE) from the parent shell --
# it does NOT gate on stdout being a real tty, so this fires even though
# `dispatch_bg`'s subprocess.run pipes stdout (capture_output=True). Left
# unstripped, `\S+` in _BG_SHORT_ID_RE greedily swallows the ANSI CSI codes
# wrapping the id (confirmed live: stdout repr'd to
# `'backgrounded \xb7 \x1b[36m8e4a79bb\x1b[39m \xb7 ...'`), so the captured
# "short id" never prefix-matches any real sessionId and the roster-join
# loop spins to its full NATIVE_JOIN_VERIFY_SECONDS deadline every time --
# live-confirmed root cause of every "no roster entry joined -- possible
# DOA" failure in this environment (FORCE_COLOR=3 is set); with it stripped,
# the join succeeds on the first poll (<1s).
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class NativeDispatchError(Exception):
    """T4 fix wave (Critical C1): carries the short id whenever dispatch_bg
    knows it at raise time (primarily the join-expiry raise, where a real
    --bg dispatch happened and only the roster join itself failed to
    verify) -- default None for the earlier failure causes (bad name,
    missing exe, task-file write, dispatch subprocess failure) where no
    short id was ever parsed. cmd_spawn forwards this to
    _fast_completion_sid so it can locate the Stop hook's sid-keyed
    fallback outcome file, which is the only file that exists in the
    fast-completion race (see _fast_completion_sid's docstring)."""
    def __init__(self, message, short_id=None):
        super().__init__(message)
        self.short_id = short_id


def render_native_name(category, name: str, hint: str) -> str:
    # category gets the same treatment as hint: whitespace-collapsed, then
    # `|` replaced (not stripped, to keep legibility) so a pipe in either
    # field can never corrupt the `cat|name|hint` split("|", 2) convention.
    cat = " ".join(str(category or DEFAULT_CATEGORY).split()).replace("|", "/")
    clean = " ".join((hint or "").split()).replace("|", "/")[:NATIVE_NAME_HINT_MAX]
    return f"{cat}|{name}|{clean}"


def _parse_bg_short_id(stdout_text: str):
    clean = _ANSI_ESCAPE_RE.sub("", stdout_text or "")
    m = _BG_SHORT_ID_RE.search(clean)
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
                setting_sources=None,
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
                roster_fetch=None, clock=time.monotonic):
    # Defense in depth (adversarial trap 6): every current caller
    # pre-validates `name`, but this is the single choke point for every
    # --bg launch and `task_file_path(name)` is not traversal-safe on its
    # own -- guard here too so a future direct-call path can't escape
    # tasks_dir().
    if not name or not NAME_RE.match(name) or _SID_SHAPE_RE.match(name):
        raise NativeDispatchError(
            f"invalid worker name: {name!r} (must match {NAME_RE.pattern}; "
            f"uuid-shaped names are reserved for session ids, F6)")
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
    # T12 fix wave (finding 1): the task file lives under FLEET_HOME/tasks,
    # virtually always outside the worker's own --dir cwd -- under any
    # non-bypass mode the worker's first Read on it hangs forever on an
    # unapprovable headless permission prompt. --add-dir pre-authorizes
    # tasks_dir() specifically (least privilege -- never FLEET_HOME wholesale).
    argv += ["--add-dir", tasks_dir().as_posix()]
    # T4 fix wave (Important I1): additive param -- forwards the persisted
    # --setting-sources value onto the native --bg argv, which the frozen
    # T3 dispatch_bg signature never carried. UNOBSERVED under --bg at
    # 2.1.207 (the flag's actual runtime effect on a --bg-launched worker
    # was never directly confirmed against a real daemon in this task);
    # pin-tested in T12.
    if setting_sources:
        argv += ["--setting-sources", setting_sources]
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
    # Unhashable-sessionId guard (debt roll-up, mislabeled "item 3" in an
    # earlier wave): filter the sessionId VALUE's type too -- a dict-valued
    # sessionId (CLI drift / hostile roster) would otherwise land in the set
    # and raise TypeError from the unhashable value.
    pre_sids = ({e.get("sessionId") for e in pre_entries
                 if isinstance(e, dict) and isinstance(e.get("sessionId"), str)}
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
    try:
        sid = _join_roster_by_short_id(short_id, roster_fetch, sleep,
                                       exclude_sids=pre_sids, clock=clock)
    except BaseException as exc:
        # T4 fix wave (Important, Ctrl-C mid-join): a live --bg session was
        # already dispatched (proc.returncode == 0, short_id parsed) by the
        # time this loop runs -- if Ctrl-C (or any other exception) lands
        # here, the short id is the only handle an operator has left to
        # find it again via `claude agents`. add_note survives re-raise
        # through cmd_spawn's except BaseException handler, which has no
        # other way to recover it (dispatch_bg stays opaque -- no message
        # parsing per the T4 design).
        exc.add_note(f"fleet_short_id={short_id}")
        raise
    if sid is None:
        raise NativeDispatchError(
            f"dispatched (short id {short_id}) but no roster entry joined "
            f"within {NATIVE_JOIN_VERIFY_SECONDS:.0f}s -- possible DOA; "
            f"recover manually via claude agents", short_id=short_id)
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
SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0   # dispatch -> roster-join window (contract G6 fallback); keep in sync with NATIVE_JOIN_VERIFY_SECONDS above (same window, independently defined -- Finding 3)

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


def read_handoff_abort_flag() -> dict | None:
    """Best-effort read of the abort flag (M-B T10 fix wave, Finding 2):
    used by cmd_sup_handoff_abort as fallback evidence when HANDSHAKE is
    absent. Missing/corrupt file -> None, same tolerance as read_handshake."""
    try:
        data = json.loads(handoff_abort_flag_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


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
    # Same hostile-sessionId-value guard as dispatch_bg's pre-snapshot: a
    # dict-valued sessionId (CLI drift / hostile roster) must never raise
    # TypeError from an unhashable value landing in the set.
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
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
                          sleep=time.sleep, clock=time.monotonic) -> int:
    """`fleet sup-handoff-begin [--model M] [--permission-mode P] [--sid S]`.
    Checkpoint-then-act: HANDOFF-BEGIN is journaled BEFORE dispatch so a
    crash mid-dispatch leaves evidence. Dispatch + roster polling run
    OUTSIDE fleet_lock (F4 doctrine). Both failure paths (dispatch failure,
    successor DOA) raise the doctor-visible abort flag before returning
    (M-B T10 fix 1) -- a crash here must not leave the old side believing
    a successor is in flight when none exists."""
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

    holder_inc = claim["incarnation_id"]

    def _abort_flag(reason, successor_sid=None, successor_short_id=None):
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "reason": reason,
            "successor_sid": successor_sid,
            "successor_short_id": successor_short_id,
            "holder": holder_inc,
        })

    roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    exe = resolve_claude_executable(which=which)
    pre_ok, pre_payload = roster_fetch()
    # Same unhashable-sessionId guard as dispatch_bg's pre-snapshot above.
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict) and isinstance(e.get("sessionId"), str)}
    name = f"sup|{successor_inc}|successor"
    argv = [exe, "--bg", "-n", name]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    if getattr(args, "permission_mode", None):
        argv += ["--permission-mode", args.permission_mode]
    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
    try:
        proc = run(argv, cwd=str(FLEET_HOME), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        _abort_flag("dispatch-failed")
        raise FleetCliError(f"successor dispatch failed: {exc} -- no successor to stop; "
                            f"claim unchanged, duty continues")
    if proc.returncode != 0:
        _abort_flag("dispatch-failed")
        raise FleetCliError(f"successor dispatch failed (exit {proc.returncode}): "
                            f"{(proc.stderr or '').strip()[:300]} -- no successor to stop; "
                            f"claim unchanged, duty continues")

    # Sid capture per contract G6: short id from --bg stdout, joined to the
    # full sid by prefix match (T3 helper) -- never re-derive by polling the
    # roster for a name match (ai-title collision hazard). Fall back to the
    # old name-join loop ONLY when stdout was unparseable (G6 fallback of the
    # fallback, M-B T10 fix 4).
    short_id = _parse_bg_short_id(proc.stdout or "")
    successor_sid = None
    if short_id:
        successor_sid = _join_roster_by_short_id(
            short_id, roster_fetch, sleep,
            verify_seconds=SUPERVISOR_ROSTER_VERIFY_SECONDS,
            exclude_sids=pre_sids, clock=clock)
    else:
        print("short-id parse failed -- falling back to name join (G6 fallback)")
        deadline = clock() + SUPERVISOR_ROSTER_VERIFY_SECONDS
        while clock() < deadline:
            ok, payload = roster_fetch()
            if ok:
                # Same hostile-sessionId-value guard as pre_sids above: a
                # dict-valued sessionId would raise TypeError from the
                # unhashable membership test against the set.
                fresh = [e for e in payload if isinstance(e, dict)
                         and e.get("name") == name
                         and isinstance(e.get("sessionId"), str)
                         and e.get("sessionId")
                         and e.get("sessionId") not in pre_sids]
                if fresh:
                    successor_sid = fresh[0]["sessionId"]
                    break
            sleep(3)
    if successor_sid is None:
        _abort_flag("successor-doa", successor_short_id=short_id)
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
    hook -- nothing will have journaled on the successor's behalf.

    Sid cross-check (M-B T10 fix 2): a live HANDSHAKE naming a different sid
    than --successor-sid means the caller is pointed at the wrong session --
    refuse before touching anything (nothing stopped, no flag written).

    BEHAVIOR CHANGE (M-B T10 fix wave, Finding 2 -- Important): absent
    HANDSHAKE no longer means "unchecked, proceed". Verification order is:
    (1) HANDSHAKE present -- cross-check its sid as above (mismatch refuses,
    match proceeds); (2) HANDSHAKE absent -- fall back to the abort flag
    (`handoff_abort_flag_path()`) written by sup-handoff-begin on a DOA/
    dispatch-failure; if its `successor_sid` matches --successor-sid,
    proceed (stopping the recorded limbo successor is the documented duty);
    (3) HANDSHAKE absent and no matching recorded evidence -- refuse. There
    is no longer a path where an arbitrary --successor-sid is stopped with
    zero verification."""
    with fleet_lock():
        claim, caller = _require_claim_holder(getattr(args, "sid", None))
        hs = read_handshake()
        if hs is not None:
            if hs.get("session_id") != args.successor_sid:
                raise FleetCliError(
                    f"--successor-sid does not match HANDSHAKE sid {hs.get('session_id')} -- "
                    f"refusing to stop an unrelated session")
        else:
            flag = read_handoff_abort_flag()
            recorded_sid = flag.get("successor_sid") if flag is not None else None
            # Roll-up item 8 (simplified): an abort flag recorded with
            # successor_sid=None (the dispatch-failed shape) names nothing
            # verifiable to stop -- refuse on the RECORDED side, whatever the
            # caller passed. The old args-side None check was dead via the
            # CLI (argparse required=True) and is now subsumed: a None
            # args.successor_sid can only match a None recorded_sid, which
            # this refuses first.
            if recorded_sid is None or recorded_sid != args.successor_sid:
                raise FleetCliError(
                    f"no HANDSHAKE and --successor-sid {args.successor_sid} matches no "
                    f"recorded limbo successor -- refusing to stop an unverified session "
                    f"(check claude agents; stop manually if certain)")
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
    # S1 fix (final wave): route through _stop_native_session -- the ONLY
    # sanctioned stop primitive -- instead of an inline full-sid `run(...)`.
    # T12 established `claude stop` requires the SHORT id; the raw full-sid
    # call here no-op'd 100% of the time (job-ref conversion is entirely
    # internal to _stop_native_session/_rm_native_session, and this was not
    # a call site of either).
    stopped = _stop_native_session(args.successor_sid, run=run, which=which, timeout=60)
    if not stopped:
        print(f"WARNING: `claude stop {args.successor_sid}` stop failed -- "
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
                        help="with --statusline/--autoclean: overwrite a foreign statusline / "
                             "scheduled task")
    p_init.add_argument("--autoclean", action="store_true",
                        help="install/update the Windows Scheduled Task that runs "
                             "`fleet autoclean` on an interval")
    p_init.add_argument("--autoclean-interval-hours", type=int, default=None,
                        dest="autoclean_interval_hours",
                        help=f"with --autoclean: run interval in hours, 1-23 "
                             f"(default {AUTOCLEAN_INTERVAL_HOURS_DEFAULT})")
    p_init.add_argument("--autoclean-remove", action="store_true", dest="autoclean_remove",
                        help="uninstall the autoclean scheduled task")

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
    # M-B T4 (spec §5.1.3 agents-menu categories): passed through verbatim
    # to render_native_name; defaults to DEFAULT_CATEGORY ("fleet") when
    # unset at dispatch time.
    p_spawn.add_argument("--category", default=None)

    p_status = sub.add_parser("status", help="show worker status table")
    p_status.add_argument("name", nargs="?", default=None)
    p_status.add_argument("--json", action="store_true",
                          help="print the status snapshot as JSON")
    p_status.add_argument("--stale-ok", dest="stale_ok", action="store_true",
                          help="read-only fast path: no PID probe, no lock, no write "
                               "(last-committed state; used by the statusline)")
    p_status.add_argument("--all", action="store_true",
                          help="include archived (tombstoned) workers, flagged 'archived'")

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
    clean_tier = p_clean.add_mutually_exclusive_group()
    clean_tier.add_argument("--dead-only", action="store_true", dest="dead_only",
                            help="sweep only confirmed-dead workers; spare archived tombstones")
    clean_tier.add_argument("--tombstones", action="store_true",
                            help="sweep only archived tombstones; touch nothing else")

    p_archive = sub.add_parser("archive", help="auto-archive terminal-state native workers past a TTL")
    p_archive.add_argument("name", nargs="?", default=None)
    p_archive.add_argument("--ttl-hours", type=float, default=None, dest="ttl_hours")
    p_archive.add_argument("--dry-run", action="store_true", dest="dry_run")

    p_autoclean = sub.add_parser(
        "autoclean",
        help="staleness sweep: archive TTL pass + fleet-owned daemon-husk rm "
             "(docs/specs/autoclean.md)")
    p_autoclean.add_argument("--ttl-hours", type=float, default=None, dest="ttl_hours",
                             help="tier-1 archive TTL (default 24)")
    p_autoclean.add_argument("--expire-tombstones-hours", type=float, default=None,
                             dest="expire_tombstones_hours",
                             help="tier 3 (default OFF): drop registry tombstones older than "
                                  "this; files in logs/archive/ are never deleted")
    p_autoclean.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_autoclean.add_argument("--fleet-home", dest="fleet_home", default=None,
                             help="explicit FLEET_HOME override; the scheduled task "
                                  "always passes this (Task Scheduler has no operator env)")

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
    # M-B T8: the standing cp1252-crash fix (knowledge C2) -- a Windows
    # console's default code page cannot encode most native-worker output
    # (roster/transcript text is UTF-8: emoji, CJK, box-drawing). Force
    # utf-8 with lossy replacement on both streams before anything else
    # prints, so `fleet result`/`fleet peek` et al. never raise
    # UnicodeEncodeError on a plain `cmd.exe`/legacy-codepage console.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
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
        if args.command == "archive":
            return cmd_archive(args)
        if args.command == "autoclean":
            return cmd_autoclean(args)
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
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
