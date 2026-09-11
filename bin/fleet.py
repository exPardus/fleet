"""fleet.py -- stdlib-only CLI to spawn, monitor, steer and hand off workers.
Requires Python 3.10+; MIN_PYTHON_VERSION defines the interpreter floor.
Core path, registry, event, liveness and prompt helpers support the argparse CLI.
Windows and POSIX adapters isolate platform operations. See docs/SPEC.md.
"""
from __future__ import annotations

import argparse
import ast
import ctypes
import fnmatch
import functools
import hashlib
import hmac
import io
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import fleet_index, importlib; fleet_land = importlib.import_module("fleet_land"); fleet_brief = importlib.import_module("fleet_brief")
from fleet_errors import FleetCliError
# Preserve the public facade for callers and direct probes. Internal index
# calls resolve in fleet_index; tests patch that owner through patch_fleet.
from fleet_index import (
    INDEX_DIR_NAME,
    INDEX_SYMBOLS_DIR_NAME,
    INDEX_CONFIG_FILE_NAME,
    INDEX_SHARD_SUFFIX,
    SHARD_KINDS,
    INDEX_SHA_HEX_LEN,
    INDEX_GITIGNORE_ENTRY,
    INDEX_CONFIG_KEYS,
    INDEX_CONFIG_DEFAULTS,
    INDEX_CONFIG_DEFAULT_TOML,
    INDEX_SKIP_DIR_NAMES,
    INDEX_NO_INDEX_MESSAGE,
    IndexConfigError,
    IndexPathError,
    IndexDigestTooLargeError,
    index_dir,
    index_symbols_dir,
    index_config_path,
    _index_posix_rel,
    shard_path_for_source,
    _index_require_inside,
    _index_entry_paths,
    source_rel_from_shard,
    source_lang,
    _index_tsv_field,
    _INDEX_LINE_BREAK_RE,
    _index_split_lines,
    _index_row_key,
    render_shard,
    _INDEX_HEX,
    read_shard,
    _index_unlink_quiet,
    write_shard_atomic,
    header_for_bytes,
    source_header,
    _index_decode,
    _index_py_sig,
    _index_py_symbols,
    _index_parse_python,
    _MD_HEADING_RE,
    _MD_CLOSING_HASHES_RE,
    _index_parse_markdown,
    parse_source_symbols,
    _index_config_array,
    _parse_index_config,
    load_index_config,
    _index_glob_regex,
    _index_glob_match,
    INDEX_DIGEST_WARN_CHARS,
    INDEX_DIGEST_REFUSE_CHARS,
    render_digest,
    _index_is_repo_boundary,
    _index_is_reparse_point,
    find_index_root,
    verified_shard_rows,
    _index_selects,
    index_source_files,
    index_shard_rels,
    _index_prune_shard,
    _new_index_report,
    _index_refresh_one,
    build_index,
    update_index,
    index_status,
    INDEX_TEACH_LINES,
    index_teach_verbs,
    registered_cli_verbs,
    index_teach_lines,
    parse_context_arg,
    compose_context_digests,
    INDEX_LIST_CAP,
    INDEX_FAILED_RC,
    _index_root_arg,
    _require_index,
    _index_files_arg,
    _index_git_common_dir,
    _ensure_index_excluded,
    _print_index_report,
    cmd_index_init,
    cmd_index_build,
    cmd_index_update,
    cmd_index_status,
    cmd_index,
    Q_LIMIT_DEFAULT,
    Q_OUTPUT_LINE_CAP,
    Q_TRUNCATION_TRAILER,
    Q_NOTE_CAP,
    _q_pointer,
    _q_source_lines,
    _q_print_capped,
    _q_print_notes,
    _q_collect_rows,
    _q_match,
    _q_sorted,
    _q_print_hits,
    _q_print_slice,
    _q_shard_rels,
    _q_path_dialect_hint,
    _cmd_q_query,
    _q_contained,
    _q_outline_rels,
    _q_outline_known,
    _q_print_outline_candidates,
    _cmd_q_outline,
    cmd_q,
)

# Resolve these kernel capabilities at call time so facade patches remain live.
fleet_index._replace_with_retry = lambda *args, **kwargs: _replace_with_retry(*args, **kwargs)
fleet_index.build_parser = lambda: build_parser()

# Shared interpreter floor: shims, documentation and TestInterpreterFloor agree
# on this constant. Keep compatibility with distro Python 3.10.
MIN_PYTHON_VERSION = (3, 10)

# ---------------------------------------------------------------------------
# Paths (SPEC §3)
# ---------------------------------------------------------------------------

# Home selection is captured at import; each path helper re-reads this global
# so tests and explicit home resolution can redirect all state paths together.
FLEET_HOME = (
    Path(os.environ["FLEET_HOME"]) if os.environ.get("FLEET_HOME")
    else Path(__file__).resolve().parent.parent
)

# Install code is anchored to this file independently of the selected home.
# An environment override here could redirect hooks and statusline to nonexistent
# code in a data-only home. Helpers re-read the global for test isolation.
INSTALL_ROOT = Path(__file__).resolve().parent.parent


def state_dir() -> Path:
    return FLEET_HOME / "state"


def interface_dir(home=None) -> Path:
    """The interface role's durable, per-home state directory."""
    root = FLEET_HOME if home is None else Path(home)
    return root / "state" / "interface"


def interface_board_path(home=None) -> Path:
    return interface_dir(home) / "board.md"


def interface_log_path(home=None) -> Path:
    return interface_dir(home) / "log.md"


def _interface_supervisor_state(home):
    path = Path(home) / "supervisor" / "INCARNATION"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "none"
    except (OSError, ValueError):
        return "UNMEASURED"
    if not isinstance(value, dict):
        return "UNMEASURED"
    state = value.get("state")
    if state == "released":
        return "released"
    if isinstance(value.get("incarnation_id"), str):
        return state or "held"
    return "UNMEASURED"


def _interface_lanes(home):
    path = Path(home) / "state" / "fleet.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return "UNMEASURED"
    workers = value.get("workers") if isinstance(value, dict) else None
    if not isinstance(workers, dict):
        return "UNMEASURED"
    names = sorted(name for name, row in workers.items()
                   if isinstance(row, dict) and row.get("status") == "working")
    return ", ".join(names) if names else "none"


def _interface_last_throughput(home):
    matches = []
    paths = [Path(home) / "supervisor" / "JOURNAL.md"]
    history = Path(home) / "supervisor" / "journal-history"
    try:
        paths.extend(sorted(history.glob("*.md")))
    except OSError:
        return "UNMEASURED"
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError, UnicodeError):
            continue
        for line in lines:
            if "THROUGHPUT" in line:
                match = re.search(r"THROUGHPUT\s+wave\s+(\d+)", line)
                if match:
                    matches.append((int(match.group(1)), line.strip()))
    return max(matches, key=lambda item: item[0])[1] if matches else "UNMEASURED"


def _interface_pending_rulings(home):
    root = Path(home) / "state" / "tasks"
    if not root.exists():
        return "UNMEASURED"
    found = []
    try:
        paths = sorted(path for path in root.rglob("*") if path.is_file())
    except OSError:
        return "UNMEASURED"
    for path in paths:
        relative = path.relative_to(root)
        # Lens briefs are research inputs, not operator decision slots.
        if relative.parts and relative.parts[0].lower() == "lens":
            continue
        # Supervisor-rendered task files are machine inputs, not unanswered
        # operator rulings, wherever they appear under the task root.
        if fnmatch.fnmatch(path.name, "sup~*.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return "UNMEASURED"
        if not re.search(r"(?m)^\s*RULED\s*:", text):
            found.append(path.relative_to(Path(home)).as_posix())
    return ", ".join(found) if found else "none"


def _interface_last_relayed(home):
    path = interface_log_path(home)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return "UNMEASURED"
    except (OSError, UnicodeError):
        return "UNMEASURED"
    waves = []
    for line in lines:
        match = re.search(r"RELAY.*?wave\s+(\d+)", line, re.IGNORECASE)
        if match:
            waves.append(int(match.group(1)))
    return str(max(waves)) if waves else "UNMEASURED"


def render_interface_board(home=None) -> str:
    """Render the deterministic portion of the interface's home board.

    Inputs not represented by durable fleet files remain ``UNMEASURED``;
    this function never fills an operational gap with a guess.
    """
    root = FLEET_HOME if home is None else Path(home)
    rulings = _interface_pending_rulings(root)
    return "\n".join([
        "# Fleet interface board",
        "",
        f"Supervisor: {_interface_supervisor_state(root)}",
        f"Lanes in flight: {_interface_lanes(root)}",
        f"Last THROUGHPUT: {_interface_last_throughput(root)}",
        f"Pending operator rulings (task paths): {rulings}",
        f"Last relayed wave: {_interface_last_relayed(root)}",
        "",
        "Human fields: UNMEASURED when no durable source exists.",
        "",
    ])


def ensure_interface_state(home=None) -> None:
    """Create the interface board/log without treating absence as an error."""
    directory = interface_dir(home)
    directory.mkdir(parents=True, exist_ok=True)
    board = interface_board_path(home)
    if not board.exists():
        board.write_text(render_interface_board(home), encoding="utf-8")
    log = interface_log_path(home)
    if not log.exists():
        log.write_text("", encoding="utf-8")


def refresh_interface_board(home=None) -> None:
    ensure_interface_state(home)
    interface_board_path(home).write_text(
        render_interface_board(home), encoding="utf-8")


def append_interface_log(kind, detail, home=None) -> None:
    """Append one durable, single-line interface event."""
    ensure_interface_state(home)
    clean = str(detail).replace("\r", " ").replace("\n", " ").strip()
    line = f"{now_iso()} {kind} {clean}\n"
    _atomic_append_bytes(interface_log_path(home), line.encode("utf-8", "replace"))
    refresh_interface_board(home)


def logs_dir() -> Path:
    return FLEET_HOME / "logs"


def mailbox_dir() -> Path:
    return FLEET_HOME / "mailbox"


def journals_dir() -> Path:
    return state_dir() / "journals"


def ceilings_dir() -> Path:
    """Sid-keyed token ceilings, shared with stop_mailbox.py's _ceiling_path.
    Fleet writes launch ceilings; the Stop hook reads them to allow stops with mail.
    """
    return state_dir() / "ceilings"


def ceiling_file_path(sid: str) -> Path:
    return ceilings_dir() / sid


def outcomes_dir() -> Path:
    return state_dir() / "outcomes"


def name_fs_stem(name: str) -> str:
    """Map worker names to portable filesystem stems.
    Replace the supervisor name's Windows-invalid `|` with `~`, which NAME_RE
    excludes from ordinary names, so mapped names cannot collide. Sids pass through.
    """
    return name.replace("|", "~")


def outcome_path(key: str) -> Path:
    # `key` is a worker NAME or a sid (read_outcomes' dual-file shape); the
    # stem mapping is the identity for sids.
    return outcomes_dir() / f"{name_fs_stem(key)}.jsonl"


def tasks_dir() -> Path:
    return state_dir() / "tasks"


def task_file_path(name: str) -> Path:
    return tasks_dir() / f"{name_fs_stem(name)}.md"


def briefs_dir() -> Path:
    """Store authoritative briefs outside the worker-authorized task directory.
    `dispatch_bg` grants tasks_dir() wholesale. This separation restricts access
    under permission-checking modes; bypass mode grants no such protection.
    """
    return state_dir() / "briefs"


def brief_file_path(name: str) -> Path:
    return briefs_dir() / f"{name_fs_stem(name)}.md"


def boot_bundle_path(name: str) -> Path:
    """Path shared by boot-output writers and cleanup/archive readers.
    The bundle temporarily contains the minted nonce plaintext.
    """
    return tasks_dir() / f"{name_fs_stem(name)}.boot-bundle.txt"


def journal_file_path(name: str) -> Path:
    return journals_dir() / f"{name_fs_stem(name)}.md"


def archive_root() -> Path:
    return logs_dir() / "archive"


def pin_pass_path() -> Path:
    return state_dir() / "pin-pass.json"


def record_pin_pass(claude_version: str) -> None:
    """Record the CLI version verified by the pin suite for doctor's drift check.
    Normalize parseable versions to X.Y.Z; preserve unparseable input so doctor
    can report an invalid pin record.
    """
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


def refuse_if_archived(name: str, record: dict, action: str) -> None:
    """Refuse mutation of an archived worker (SPEC §5.1.2).
    `fleet clean` deletes archived records and does not call this guard.
    """
    if isinstance(record, dict) and record.get("archived_at") is not None:
        raise FleetCliError(
            f"{name}: archived -- history only (fleet clean to delete)"
        )


def _write_ceiling_file(sid: str, ceiling) -> None:
    """Atomically persist the sid-keyed ceiling consumed by the Stop hook.
    None leaves the hook's block-on-mail default in force. Write errors propagate.
    """
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


def registry_path_at(home) -> Path:
    """Return state/fleet.json under the supplied home without filesystem effects.
    Keep registry_path() separate so its state_dir() monkeypatch seam remains valid.
    """
    return Path(home) / "state" / "fleet.json"


def events_path() -> Path:
    return state_dir() / "events.jsonl"


def hook_errors_path() -> Path:
    """Log of hook exceptions swallowed to preserve the hooks' exit-0 contract.
    Fleet reads this file for status counts and doctor diagnostics.
    """
    return state_dir() / "hook-errors.log"


def lock_path() -> Path:
    return state_dir() / "fleet.lock"


def template_settings_path() -> Path:
    """Hook-wiring template at INSTALL_ROOT, with PYTHON/FLEET_INSTALL placeholders.
    `fleet init` renders it into the home-specific instance_settings_path().
    """
    return INSTALL_ROOT / "worker-settings.template.json"


def instance_settings_path() -> Path:
    """Machine-local, gitignored settings instance (SPEC §14):
    state/worker-settings.json, rendered by `fleet init` from
    template_settings_path(). Every worker dispatch's --settings argv value
    points here (dispatch_bg's default), never at the template."""
    return state_dir() / "worker-settings.json"


def user_settings_path() -> Path:
    """Machine settings written by `fleet init --statusline`.
    A named helper lets tests redirect this global path.
    """
    return Path.home() / ".claude" / "settings.json"


def homes_list_path() -> Path:
    """Machine-wide homes list written by homes --add/--retire and init --home.
    Tests must redirect this helper explicitly; the common Path.home() fixture
    patches other helpers by name and does not sandbox this path.
    """
    return Path.home() / ".claude" / "fleet-homes.list"


def claude_daemon_lock_path() -> Path:
    """Vendor background-daemon singleton lock, read-only to fleet.
    Tests redirect this helper. An absent path yields no daemon-lock evidence.
    """
    return Path.home() / ".claude" / "daemon.lock"


def claude_daemon_log_path() -> Path:
    """~/.claude/daemon.log -- the vendor's supervisor log. READ-ONLY, same
    rules and same portability argument as claude_daemon_lock_path()."""
    return Path.home() / ".claude" / "daemon.log"


def statusline_script_path() -> Path:
    # The statusline script is installed code; a data-only home has no copy.
    return INSTALL_ROOT / "bin" / "fleet_statusline.py"


# Do not resolve a home through a stale machine marker: it could retarget destructive verbs.


def now_iso() -> str:
    """Current UTC time, second precision, matching the registry schema."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# === PLATFORM ADAPTER START (SPEC §14 portability mandate) ===
# Only this block branches on os.name/sys.platform or uses OS-specific primitives.
# All other code calls PLATFORM; source-scan tests enforce that boundary.

_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


class UnsupportedPlatformError(NotImplementedError):
    """A platform operation with no implementation on the current OS.
    main() renders this exception as a concise failure instead of a traceback.
    """


class _WindowsPlatform:
    """Windows implementation of every OS-specific fleet operation."""

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Append bytes with one FILE_APPEND_DATA-only WriteFile call.
        Windows CRT O_APPEND performs seek and write separately, risking lost records
        across concurrent handles. The kernel append handle avoids that race;
        a short write raises because a torn JSONL record would otherwise be skipped.
        """
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
            # A short write tears a JSONL record; raise instead of silently losing it.
            if not ok or written.value != len(data):
                raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")
        finally:
            kernel32.CloseHandle(handle)


class _PosixPlatform:
    """POSIX implementation of every OS-specific fleet operation."""

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Append bytes with one O_APPEND write, atomically seeking to EOF on POSIX.
        A short write raises because a torn JSONL record would otherwise be skipped.
        """
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o666)
        try:
            written = os.write(fd, data)
            if written != len(data):
                raise OSError(
                    f"short append to {path}: {written}/{len(data)} bytes")
        finally:
            os.close(fd)


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
        except PermissionError:
            # Windows delete-pending lock names can raise PermissionError instead of EEXIST.
            # A present name is contention: poll under the deadline without stale-breaking,
            # because unlink can also be denied. An absent name means directory access failed;
            # re-raise that error instead of reporting a misleading lock timeout.
            if not path.exists():
                raise
            if time.monotonic() >= deadline:
                raise FleetLockTimeout(f"timed out waiting for lock: {path}")
            time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
    try:
        os.write(fd, token.encode("utf-8"))
    except OSError:
        # O_EXCL proves this file is ours. On token-write failure, close and remove it
        # so other acquirers are not stranded; cleanup must preserve the original error.
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


# `supervisor` is a logical claim-resolved target, never an ordinary worker name.
# Reserve it at creation so a worker cannot shadow supervisor resolution.
SUPERVISOR_BODY_NAME = "supervisor"
RESERVED_NAMES = frozenset({SUPERVISOR_BODY_NAME})


# Win32 resolves these character devices in every directory, even with extensions.
# NUL can discard task text and CON can block journal reads. Refuse exact stems
# on all platforms; prefixes such as console, nulls and com10 remain legal.
_WIN32_DEVICE_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{d}" for d in range(1, 10)}
    | {f"lpt{d}" for d in range(1, 10)})


def _is_win32_device_name(name) -> bool:
    """Recognize Win32 character devices, ignoring extensions and trailing dots/spaces.
    Apply this on every OS so records created on POSIX remain usable on Windows.
    """
    stem = str(name).strip().rstrip(". ").split(".", 1)[0].strip().lower()
    return stem in _WIN32_DEVICE_STEMS


def validate_name(name: str, existing=()) -> None:
    """Require a unique [a-z0-9-]+ name excluding reserved names and devices.
    `supervisor` belongs to logical claim resolution. UUID-shaped names would
    collide with sid-keyed evidence and could authorize removal of a foreign sid.
    """
    if not name or not NAME_RE.match(name):
        raise ValueError(f"invalid worker name {name!r}: must match [a-z0-9-]+")
    if _SID_SHAPE_RE.match(name):
        raise ValueError(
            f"invalid worker name {name!r}: uuid-shaped names are reserved "
            f"for session ids (F6)")
    if _is_win32_device_name(name):
        raise ValueError(
            f"invalid worker name {name!r}: Win32 reserves this as a device "
            f"name, and every artifact this worker owns is a file named after "
            f"it -- state/tasks/{name}.md IS the {name.upper()} device, so its "
            f"task file, journal and outcome records would vanish into it "
            f"(P1-8). Reserved: con, prn, aux, nul, com1-com9, lpt1-lpt9")
    if name in RESERVED_NAMES:
        raise ValueError(
            f"invalid worker name {name!r}: reserved as the supervisor's "
            f"logical name (three-tier §10.3) -- no verb mints a record by "
            f"this name; `sup-spawn` dispatches `sup|<launch-id>|boot`")
    if name in existing:
        raise ValueError(f"worker name already exists: {name!r}")


class RegistryCorruptError(Exception):
    """An existing registry cannot be trusted; callers must not overwrite it as empty.
    `attempted=False, quarantined=None` means no rename was attempted.
    `attempted=True, quarantined=None` means the rename failed.
    `attempted=True, quarantined=Path` identifies the successful rename.
    These fields describe this incident; an older artifact cannot prove its outcome.
    """

    def __init__(self, message, quarantined=None, attempted=False):
        super().__init__(message)
        self.quarantined = quarantined
        self.attempted = attempted or quarantined is not None


def _quarantine_registry(path: Path):
    """Best-effort rename of a corrupt registry, with an event.
    Return the quarantine Path on successful rename, otherwise None.
    """
    quarantined = path.with_name(f"fleet.json.corrupt.{now_iso().replace(':', '')}")
    try:
        path.rename(quarantined)
    except OSError:
        quarantined = None
    try:
        append_event("registry_corrupt", "fleet",
                     path=str(quarantined if quarantined is not None else path))
    except OSError:
        pass
    return quarantined


def _quarantine_artifacts() -> list:
    """Return sorted quarantine artifacts; delegate the glob to _quarantine_artifacts_at.
    Artifacts distinguish an unresolved incident from a fresh install. Readers use
    three rules; absence classification must not weaken a presence-only refusal.

    RULE 1: unresolved incident, registry present or not. Refuse on presence alone:
    os.rename preserves mtime, so comparing against a recreated registry is unsafe.
      * `_sweep_husks` (:7228) -- hidden records can still own roster sessions.
      * `_doctor_check_autoclean` (:8123) -- report a sweep blocked by an artifact.
      * `_require_claim_holder`'s §9 arm (:11037) -- legacy upgrades need complete records.

    RULE 2: absent registry with an artifact means incident, not fresh install.
      * `_acting_worker_identity` (:2005) -- only a fresh absence proves no records;
        healthy reads must still identify workers for the §6.5 gate.
      * `_identity_abstention_note` (:10911) -- describe the incident-specific absence.
      * `_read_registry_readonly` (:2507) -- expose that distinction to views.
      * `_doctor_check_registry` (:8373) -- do not grade a renamed-away path readable.

    RULE 3: name the artifact after absence has already been classified.
      * `_print_snapshot_table` (:4518) -- render the stale-ok status explanation.
      * `_tombstone_releasing_body` (:11862) -- render the release explanation.
    Restore the artifact's contents before removing it to re-arm the readers.
    """
    return _quarantine_artifacts_at(state_dir())


def _quarantine_artifacts_at(state: Path) -> list:
    """Return sorted quarantine artifacts for a supplied state directory, or [].
    One glob spelling serves same-home and cross-home readers.
    """
    try:
        return sorted(Path(state).glob("fleet.json.corrupt.*"))
    except (OSError, ValueError):
        return []


# Shared repair hint: doctor --repair explicitly requests quarantine.
# Other lock-held mutations can also quarantine through load_registry.
REGISTRY_REPAIR_HINT = "repair it with `fleet doctor --repair`"


def _registry_corrupt_reason(data):
    """Return None for a registry object with dictionary worker records, else a reason.
    Shared validation keeps quarantining and read-only loaders consistent.
    """
    if not isinstance(data, dict):
        return "registry was not a JSON object"
    workers = data.get("workers", {})
    if not isinstance(workers, dict) or not all(isinstance(v, dict) for v in workers.values()):
        return "registry 'workers' was not an object of objects"
    return None


def _corrupt_error(path: Path, reason: str, quarantined) -> RegistryCorruptError:
    """Describe this incident's quarantine attempt and outcome.
    The caller performs the rename: only load_registry calls _quarantine_registry,
    so the repair capability remains identifiable by an AST call-site census.
    """
    if quarantined is None:
        # Describe only this rename; older artifacts say nothing about its success.
        return RegistryCorruptError(
            f"{reason} and could NOT be quarantined -- it is still at {path}. "
            f"The rename was attempted and LOST (win32 sharing violation, "
            f"deny-write ACL, or something holding the file open), so this "
            f"incident left no fleet.json.corrupt.<ts> artifact of its own.",
            attempted=True)
    return RegistryCorruptError(f"{reason}; quarantined to {quarantined}",
                                quarantined=quarantined, attempted=True)


def load_registry() -> dict:
    """Load the full registry; a missing file yields {"workers": {}}.
    Corrupt content triggers a quarantine attempt and RegistryCorruptError.
    Unreadable files raise without attempting a rename. Callers must abort on error.
    This loader can write: read paths use read_registry_no_repair instead.
    """
    path = registry_path()
    if not path.exists():
        return {"workers": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise _corrupt_error(path, "registry is not valid JSON",
                             _quarantine_registry(path))
    except OSError:
        # An unreadable file is not known corrupt. Preserve it so access or I/O problems
        # can be repaired without moving the operator's evidence.
        raise RegistryCorruptError(f"registry unreadable: {path}")
    reason = _registry_corrupt_reason(data)
    if reason is not None:
        raise _corrupt_error(path, reason, _quarantine_registry(path))
    data["workers"] = data.get("workers", {})
    return data


def read_registry_no_repair(hint: bool = True) -> dict:
    """Load the full registry without quarantine; missing yields {"workers": {}}.
    Use the same validation and RegistryCorruptError contract as load_registry.
    A distinct function name lets the AST census identify repair-capable callers.
    Preserve sibling keys because a later save must not erase unprojected data.
    `hint=False` lets doctor supply its own repair explanation without duplication.
    """
    path = registry_path()
    if not path.exists():
        return {"workers": {}}
    suffix = f" -- {REGISTRY_REPAIR_HINT}" if hint else ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RegistryCorruptError(f"{path} is not valid JSON{suffix}")
    except OSError:
        raise RegistryCorruptError(f"registry unreadable: {path}")
    reason = _registry_corrupt_reason(data)
    if reason is not None:
        raise RegistryCorruptError(f"{reason} ({path}){suffix}")
    data["workers"] = data.get("workers", {})
    return data


REGISTRY_REPLACE_RETRIES = 5
REGISTRY_REPLACE_BACKOFF_SECONDS = 0.1


def _replace_with_retry(tmp_name: str, dest: str, sleep=None) -> None:
    """Replace with bounded retries on PermissionError, then re-raise the error.
    A Windows directory destination does not always fail fast: it can raise
    PermissionError. Default sleeps total 1.5s; other OSErrors fail immediately.
    Resolve time.sleep at call time so callers retain the monkeypatch seam.
    """
    if sleep is None:
        sleep = time.sleep          # Resolve the injectable sleep seam at call time.
    delay = REGISTRY_REPLACE_BACKOFF_SECONDS
    for attempt in range(REGISTRY_REPLACE_RETRIES):
        try:
            os.replace(tmp_name, dest)
            return
        except PermissionError:
            if attempt == REGISTRY_REPLACE_RETRIES - 1:
                raise
            sleep(delay)
            delay *= 2


def save_registry(data: dict) -> None:
    """Atomically write state/fleet.json (temp file + os.replace, with a
    bounded win32 sharing-violation retry -- see `_replace_with_retry`)."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(d), prefix=".fleet.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        _replace_with_retry(tmp_name, str(registry_path()))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def current_caller_session() -> str | None:
    """Return the invoking Claude session sid, or None for a plain shell.
    Destructive guards use this provenance to distinguish own from foreign workers.
    """
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return sid or None


LEGACY_TASK_SNAPSHOT_CHARS = 200
"""The registry `task` snapshot cap, applied by `new_worker_record` below and
read by `read_brief`.

ONE name for ONE number, because the two readings must agree: a snapshot AT
the cap cannot be told apart from a complete task of exactly that length, so
`read_brief` treats it as a remnant and refuses to dispatch it. Written as a
literal in the record builder and re-declared in the brief store, raising the
builder's cap alone would have made `read_brief` refuse every COMPLETE task
between the old cap and the new one -- a truncated brief must fail loudly, but
a whole one must not fail at all."""


def new_worker_record(session_id, cwd, task, mode, model=None, created=None,
                       max_budget_usd=None, setting_sources=None, token_ceiling=None,
                       spawned_by=None, dispatch_kind=None, category=None,
                       spawned_by_lineage=None) -> dict:
    """Build a SPEC §4 worker record.
    Persist launch budgets and settings sources so every subsequent dispatch uses
    the same policy. Nullable additive fields preserve compatibility on reads.
    """
    created = created or now_iso()
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        # Share the cap with read_brief: equality means the snapshot may be truncated.
        "task": task[:LEGACY_TASK_SNAPSHOT_CHARS],
        "mode": mode,
        "model": model,
        "max_budget_usd": max_budget_usd,
        "setting_sources": setting_sources,
        # Immutable token ceiling, also persisted by launch paths for the Stop hook.
        "token_ceiling": token_ceiling,
        # Creator sid is immutable across respawn. Missing ownership is foreign,
        # so absent provenance cannot bypass destructive confirmation.
        "spawned_by": spawned_by,
        # A later body may own its lineage's workers only after proving continuity
        # in this invocation. Missing lineage falls back to spawned_by ownership.
        "spawned_by_lineage": spawned_by_lineage,
        # Write-once per record: fork-steer retains created; respawn mints a fresh value.
        # _releaser_live_sids compares created to released_at to bound its union arm.
        # Carrying created across respawn would falsely keep the releaser-live gate armed
        # and refuse successors even after the releaser has been replaced.
        "created": created,
        "status": "working",
        "attached_since": None,
        # Usage-limit horizon/kind are nullable. Unknown reset times remain parked;
        # only a known elapsed horizon permits normal resume eligibility.
        "limit_reset_at": None,
        "limit_kind": None,
        "turns": 0,
        "cost_usd": 0.0,
        # Prior-session spend is carried across respawn so fresh-session cost cannot
        # overwrite the lifetime total. Missing baseline reads as zero.
        "cost_baseline": 0.0,
        "last_activity": created,
        # --- M-B native-substrate fields (spec §5; None/[] on legacy records) ---
        "dispatch_kind": dispatch_kind,      # "bg" = daemon-hosted; None = pre-pivot Popen
        "category": category,                # agents-menu category (spec §5.1.3)
        # The CLI-captured short id supports the gone-to-success inference. Fast
        # completion instead derives it from the sid; that provenance depends on the
        # vendor id format. See _native_job_ref before using it as a removal reference.
        "native_short_id": None,
        "last_dispatch_at": None,            # stamped at every dispatch/steer/resume;
                                             # anchor for the fresh-outcome predicate
        "retired_sids": [],                  # prior sids retired by fork-steer/respawn
        "archived_at": None,                 # set by auto-archival; hides from status
    }


# ---------------------------------------------------------------------------
# Events (fleet.py is the only writer of state/events.jsonl)
# ---------------------------------------------------------------------------

def append_event(kind: str, name: str, **fields) -> None:
    """Atomically append one JSON event {"ts", "kind", "name", **fields}.
    Concurrent processes require the platform append primitive, especially on
    Windows where buffered append can lose whole records without a decode error.
    """
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), "kind": kind, "name": name}
    record.update(fields)
    line = json.dumps(record)
    _atomic_append_bytes(events_path(), (line + "\n").encode("utf-8"))


def _append_event_quiet(kind: str, name: str, **fields) -> None:
    """Append an event without letting logging failure retry a committed mutation.
    _commit_launched_turn retries OSError; a registry commit may be non-idempotent.
    Report logging failures without propagating them into that retry loop.
    """
    try:
        append_event(kind, name, **fields)
    except OSError as exc:
        # Even reporting failure must not raise into the commit retry loop.
        # Include event fields so the lost diagnostic can be reconstructed.
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


# Bound transcript reads to 64KB so repeated probes do not load entire large logs.
_TAIL_READ_BYTES = 64 * 1024


def _read_tail_lines(log_path) -> list:
    """Decode the trailing _TAIL_READ_BYTES, discarding a partial leading line.
    Missing or unreadable files return []; complete small files are read in full.
    """
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
                    # No newline means the tail contains only an incomplete oversized record.
                    f.seek(0)
                    chunk = f.read()
                else:
                    chunk = chunk[nl + 1:]
                    if chunk == b"":
                        # A sole terminal newline completes the discarded oversized fragment;
                        # it does not make that fragment a complete record within this window.
                        f.seek(0)
                        chunk = f.read()
            else:
                chunk = f.read()
    except OSError:
        return []
    return chunk.decode("utf-8-sig", errors="replace").splitlines()


# Maximum age of a sid-less launch claim before it can be demoted.
# Spawn cannot hold fleet_lock across Popen, so crashes can leave these claims.
# Missing age evidence remains non-expired.
LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0


def _launch_claim_expired(last_activity_iso) -> bool:
    """Whether a working, sid-less launch claim exceeds LAUNCH_CLAIM_MAX_AGE_SECONDS.
    Missing or unparseable age evidence never establishes expiry.
    """
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
    """Atomically append a message for the next mailbox claim to drain.
    Some send paths append outside fleet_lock, so the append primitive must protect
    concurrent messages. Replace unencodable characters to avoid stranding a
    pre-claimed launch on an argv surrogate; retain the rest of the message.
    """
    d = mailbox_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sid}.md"
    _atomic_append_bytes(path, (message.rstrip("\n") + "\n\n").encode("utf-8", "replace"))


_PREAMBLE_TEMPLATE = """You are fleet worker `{name}` in `{cwd}`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `{journal_target}` (create it early; update it at each milestone): goal, done, in-progress, blockers, next steps. It must be enough for a fresh session to continue.
End every turn with a compact result summary: changed, verified, blocked.
Do not leave servers or watchers running past the end of the turn without recording their PIDs in the journal.
"""


def compose_prompt(name: str, cwd, task: str, sid: str | None, journal_path=None,
                   context=None) -> tuple[str, Path | None, str]:
    """Compose preamble, optional context digests, drained mail, task and journal.
    Return (prompt, claim_path, drained_mail); sid=None skips claiming mail.
    The caller restores the claim on failure or finalizes it after process start.
    Returning the drained text lets resumed turns inline the same delivered mail.
    Empty tasks add no task section. Resolve journal paths from the live home.
    Index teaching and context use the dispatch target's cwd and are opt-in.
    """
    journal_target = journal_file_path(name).as_posix()
    parts = [_PREAMBLE_TEMPLATE.format(name=name, cwd=cwd, journal_target=journal_target)
             + fleet_index.index_teach_lines(cwd)]

    if context:
        digests, warnings = fleet_index.compose_context_digests(cwd, context)
        for warning in warnings:
            print(f"fleet: {warning}", file=sys.stderr)
        if digests:
            parts.append(digests)

    claim = None
    mail = ""
    if sid is not None:
        mail, claim = claim_mailbox(sid)
        if mail:
            parts.append(f"<MANAGER MESSAGE>\n{mail}\n")
            # Record drain at composition. The claim is recoverable on launch failure;
            # this event is an audit entry, not a retry queue.
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

    return "\n".join(parts), claim, mail


# Briefs are authoritative dispatch inputs; task payloads include transient context.
# Keep the complete text in state/briefs/<name>.md and cap only registry previews.
# Respawn rollback restores the brief alongside the registry record.

# LEGACY_TASK_SNAPSHOT_CHARS is shared with record creation and brief recovery.


def write_brief(name: str, task: str) -> None:
    """Record `task` as the worker's brief. Called only where the task text is
    AUTHORITATIVE -- a spawn, or an explicit `--task` override -- never from a
    dispatch that is merely re-composing a prompt."""
    if not task or not task.strip():
        return
    try:
        briefs_dir().mkdir(parents=True, exist_ok=True)
        brief_file_path(name).write_text(task, encoding="utf-8")
    except OSError as exc:
        raise FleetCliError(
            f"{name}: could not record the brief at {brief_file_path(name)}: {exc}"
        ) from exc


def brief_snapshot(name: str) -> bytes | None:
    """Return the brief's exact bytes, or None if absent.
    Rollback must restore bytes without newline normalization so a failed task
    override cannot change what a later bare respawn dispatches.
    """
    try:
        return brief_file_path(name).read_bytes()
    except OSError:
        return None


def restore_brief(name: str, snapshot: bytes | None) -> None:
    """Put the brief back exactly as `brief_snapshot` found it -- including
    REMOVING one this attempt created. Best-effort, like every other rollback
    step here: a failed restore must not mask the error being rolled back."""
    path = brief_file_path(name)
    try:
        if snapshot is None:
            path.unlink()
        else:
            briefs_dir().mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot)
    except OSError:
        pass


def _recovered_brief(name: str, rec: dict) -> str | None:
    """Recover a brief from a legacy payload only when its prefix matches exactly.
    The regenerated preamble and recorded snapshot must agree; uncertainty returns
    None so dispatch cannot silently inherit a guessed task.
    """
    payload = task_file_path(name)
    try:
        body = payload.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cwd = rec.get("cwd") or ""
    prefix = (_PREAMBLE_TEMPLATE.format(
        name=name, cwd=cwd, journal_target=journal_file_path(name).as_posix())
        + fleet_index.index_teach_lines(cwd) + "\n")
    if not body.startswith(prefix):
        return None
    rest = body[len(prefix):]
    marker = "\n## Journal from previous session\n"
    cut = rest.find(marker)
    if cut != -1:
        rest = rest[:cut]
    if not rest.strip():
        return None
    snapshot = rec.get("task") or ""
    if not snapshot:
        return None
    # The remainder must begin with the recorded snapshot, not just the preamble.
    # Otherwise mailbox text sharing the preamble could be recovered as task scope.
    # Normalize the short snapshot's newline spelling before checking the prefix.
    if not rest.startswith(snapshot):
        return None
    # The payload of an already-truncated respawn reproduces the remnant
    # exactly. Recovering that would launder a truncation into a "brief".
    if len(snapshot) >= LEGACY_TASK_SNAPSHOT_CHARS and rest == snapshot:
        return None
    return rest


def read_brief(name: str, rec: dict) -> str:
    """Read the authoritative brief, recover an exact payload, or use a complete snapshot.
    Persist successful recovery. A snapshot at the cap may be truncated and refuses;
    only a shorter snapshot proves completeness.
    """
    try:
        text = brief_file_path(name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if text.strip():
        return text
    recovered = _recovered_brief(name, rec)
    if recovered is not None:
        # Recovery succeeded in memory; failed persistence only forces recovery again next time.
        try:
            write_brief(name, recovered)
        except FleetCliError:
            pass
        return recovered
    snapshot = rec.get("task") or ""
    if len(snapshot) >= LEGACY_TASK_SNAPSHOT_CHARS:
        raise FleetCliError(
            f"{name}: no brief on file and the registry holds only a "
            f"{len(snapshot)}-char snapshot, which is the capped remnant -- "
            f"dispatching it would hand the session a task cut mid-sentence. "
            f"Re-supply the brief: `--task @<path-to-brief>` "
            f"(it is recorded at {brief_file_path(name)} from then on)."
        )
    return snapshot


def assert_brief_carried(name: str, brief: str, prompt_body: str) -> None:
    """Require the complete brief to appear contiguously in the composed payload.
    Length thresholds cannot detect truncation padded by a carried journal.
    """
    if not brief or not brief.strip():
        return
    if brief not in prompt_body:
        raise FleetCliError(
            f"{name}: refusing to dispatch -- the composed prompt "
            f"({len(prompt_body)} chars) does not carry the whole brief "
            f"({len(brief)} chars). A truncated brief must fail loudly, not "
            f"dispatch silently."
        )


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


def _resolved_from_current_directory(exe: str) -> bool:
    """Whether a relative executable resolution points to an existing file in cwd.
    An absolute PATH entry expresses operator intent and is trusted. Windows
    shutil.which may implicitly search cwd; relative nonexistent test doubles pass.
    """
    if not exe or os.path.isabs(exe):
        return False
    try:
        return os.path.exists(os.path.join(os.getcwd(), exe))
    except OSError:
        return False


def resolve_claude_executable(which=shutil.which) -> str:
    """Resolve claude with shutil.which and reject implicit current-directory matches.
    A planted executable would inherit the operator environment at probe and
    mutation call sites. Inspect the result to preserve the one-argument which seam.
    """
    exe = which("claude")
    if not exe:
        raise ClaudeNotFoundError(
            "claude executable not found on PATH (checked via shutil.which('claude'); "
            "expected claude.cmd or claude.exe on this machine)"
        )
    if _resolved_from_current_directory(exe):
        raise ClaudeNotFoundError(
            f"refusing to execute {exe!r}: it resolved out of the current "
            f"directory ({os.getcwd()!r}), not off PATH. On Windows "
            f"shutil.which searches the current directory FIRST, so a "
            f"claude.cmd sitting in this directory shadows the real install "
            f"-- and fleet would run it with your full environment (P1-9). "
            f"Run fleet from a directory that does not contain a claude "
            f"executable, or remove the one that does."
        )
    return exe


# Supervisor bodies are exempt from the worker-turn claim gate: handoff successors
# and gen-0 boot bodies must claim command. `fleet spawn` cannot forge this family
# because NAME_RE excludes `|`. Read the name from registry identity (SPEC.md:204),
# not the diagnostic FLEET_WORKER environment witness.
_SUPERVISOR_SHAPED_WORKER_RE = re.compile(r"^sup\|[^|]+\|[a-z][a-z0-9-]*$")


def _successor_worker_name(successor_inc: str) -> str:
    """The `--bg -n` name `cmd_sup_handoff_begin` dispatches a successor under."""
    return f"sup|{successor_inc}|successor"


def _is_supervisor_shaped(name) -> bool:
    """True iff `name` is a supervisor BODY name of the family `sup|<inc>|<role>`
    (§10.1 manager ruling) -- the handoff successor `sup|<inc>|successor` and any
    sup-spawn gen-0 role (`sup|<inc>|boot`, ...). Never raises on a non-string:
    `os.environ.get` can only return `str | None` today, but this is also called
    on registry-sourced values."""
    return isinstance(name, str) and _SUPERVISOR_SHAPED_WORKER_RE.match(name) is not None


def _worker_env(name: str) -> dict:
    """Copy the parent environment and stamp FLEET_WORKER as a diagnostic witness.
    The stamp does not establish body identity (SPEC.md:204); registry sid unions do.
    Remove CLAUDE_CODE_SESSION_ID so the child can stamp its own provenance instead
    of inheriting the manager's authority to retire sibling workers.
    """
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env["FLEET_WORKER"] = name
    return env


# ---------------------------------------------------------------------------
# Status recompute helpers (SPEC §4, §5 status row)
# ---------------------------------------------------------------------------

STALE_ATTACH_SECONDS = 3 * 3600  # doctor/status nag threshold (SPEC §9)

# Debounce unattended permission stalls for three minutes so an operator answering
# manually is not immediately nagged. Launch grace and stale-attach thresholds
# answer different questions and delay reporting too long.
PERMISSION_STALL_SECONDS = 180.0


def _coerce_cost(value):
    """Return a finite, nonnegative float or None for an untrustworthy cost.
    Numeric strings are accepted; bool, negatives, NaN and infinities are rejected
    so corrupt input cannot poison cumulative totals. Invalid values never raise.
    """
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
    """Coerce a registry cost, using 0.0 for missing or invalid summands.
    Fresh log readings retain None to distinguish no measurement from measured zero.
    """
    coerced = _coerce_cost(value)
    return coerced if coerced is not None else 0.0


# Status-table cells render unknown values explicitly; absent or malformed registry
# fields must not erase the view or fabricate a measured zero.

UNKNOWN_CELL = "?"
"""THE placeholder for any status-table cell that cannot be rendered honestly.

One token, and not a new invention: `_print_status_table` already rendered "?"
for an unparseable `last_activity`, `_print_snapshot_table` already rendered it
for an unknown age, and `status_snapshot` already used it as its `status`
fallback. Deliberately NOT the word "unknown": these are fixed-width numeric
columns 6-9 chars wide, and a token that overflows its field shifts every
column to its right."""


def _cost_cell(value, width: int = 9) -> str:
    """Render a measured cost as dollars, or ? when absent or invalid.
    The total's 0.0 fallback would falsely present a measurement in a table cell.
    """
    cost = _coerce_cost(value)
    if cost is None:
        return f"{UNKNOWN_CELL:>{width}}"
    return f"{cost:>{width}.2f}"


def _int_cell(value, width: int) -> str:
    """A right-aligned integer column (TURNS, MAIL), or `?`.

    bool is rejected even though it is an int subclass -- a JSON true in the
    turn counter is corruption, not a count of one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{UNKNOWN_CELL:>{width}}"
    return f"{value:>{width}}"


def _text_cell(value, width: int) -> str:
    """A left-aligned text column (NAME, STATUS), or `?`.

    A non-string is not coerced with str(): a status of `7` or `None` is a
    corrupt record, and printing `7` in the STATUS column would read as a
    status the fleet actually has."""
    return f"{value if isinstance(value, str) else UNKNOWN_CELL:<{width}}"


def _native_cumulative_tokens(name: str) -> int:
    """Sum valid nonnegative integer input/output tokens across native result outcomes.
    Include all sids and turns for lifetime ceiling enforcement; missing data yields 0.
    """
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


# Usage-limit parsing is conservative: uncertainty leaves an unknown reset horizon.

# An explicit ISO-8601 UTC reset instant takes precedence over local formats.
_LIMIT_RESET_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

# Local reset form: "resets 4:40am (Asia/Qyzylorda)" or "resets 12am (Asia/Qyzylorda)".
# Only fixed-UTC single-segment aliases are admitted. Other bare zone names can
# mean fixed offsets or DST rules and yield an early reset for a colloquial zone.
# Multi-segment Area/City names use ZoneInfo validation. Both the admission regex
# and fixed-offset resolver derive their closed UTC alias set from this tuple.
_LOCAL_UTC_ALIAS_NAMES = ("UTC", "UCT", "Universal", "Zulu", "Greenwich",
                          "GMT0", "GMT+0", "GMT-0")
# Longest-first is defensive, not load-bearing: no member is a prefix of
# another today, and the alternation is anchored by the `\)` that follows it,
# so ordering cannot change a verdict. It keeps that true for a future member.
_LOCAL_UTC_ALIASES = "|".join(
    re.escape(name)
    for name in sorted(_LOCAL_UTC_ALIAS_NAMES, key=len, reverse=True))
# Case-folded membership set for the resolver. The regex is IGNORECASE (a
# bare `(utc)` is admitted -- see `test_lowercase_single_segment_admitted`),
# so the resolver must fold too or it would admit a name it then cannot
# convert.
_LOCAL_UTC_ALIAS_LOOKUP = frozenset(name.lower() for name in _LOCAL_UTC_ALIAS_NAMES)

_LIMIT_RESET_LOCAL_RE = re.compile(
    r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*"
    r"\(((?:[A-Za-z_]+(?:/[A-Za-z_+\-0-9]+)+)|" + _LOCAL_UTC_ALIASES + r")\)",
    re.IGNORECASE,
)


def _next_local_reset_utc(hour: int, minute: int, tz_name: str, *, now: datetime):
    """Return the next local reset as UTC, or None if it cannot be resolved.
    Require the message-time anchor. Fixed UTC aliases bypass optional tzdata;
    other zones use zoneinfo. Missing data yields a conservative unknown horizon.
    After day rollover, compare both folds in UTC and choose the later instant:
    timedelta resets fold, and forcing fold=1 alone resolves spring gaps early.
    """
    alias = tz_name.strip().lower() if isinstance(tz_name, str) else None
    if alias in _LOCAL_UTC_ALIAS_LOOKUP:
        # Fixed UTC aliases need no tz database. Some hosts omit tzdb backward links;
        # using timezone.utc preserves the closed set's meaning on every platform.
        tz = timezone.utc
    else:
        import zoneinfo
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            return None
    try:
        moment = now.astimezone(tz)
        candidate = moment.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate < moment:
            candidate += timedelta(days=1)
        later = max(candidate.replace(fold=0), candidate.replace(fold=1),
                    key=lambda c: c.astimezone(timezone.utc))
        return later.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _parse_limit_signal(text: str, *, now: "datetime | None"):
    """Parse (reset_at, kind) from a limit message, retaining None for uncertainty.
    ISO-8601 takes precedence; local times require the message's own `now` anchor
    and a valid 1..12 hour. Missing anchors or zone data leave a null horizon.
    Recognize weekly/session keywords independently from reset-time parsing.
    """
    reset_at = None
    m = _LIMIT_RESET_RE.search(text or "")
    if m:
        reset_at = m.group(0)
    elif now is not None:
        m2 = _LIMIT_RESET_LOCAL_RE.search(text or "")
        if m2:
            hour_s, minute_s, ampm, tz_name = m2.groups()
            hour = int(hour_s)
            minute = int(minute_s) if minute_s else 0
            ampm = ampm.lower()
            if not 1 <= hour <= 12:
                # D2: a 12-hour clock has no valid hour outside 1..12 --
                # e.g. "13am" -- so this stays a null-park, not a guess.
                reset_at = None
            else:
                if ampm == "am":
                    hour24 = 0 if hour == 12 else hour
                else:
                    hour24 = 12 if hour == 12 else hour + 12
                reset_at = _next_local_reset_utc(hour24, minute, tz_name, now=now)
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
    """Find an existing transcript from name/sid outcomes, then the project's sid glob.
    Skip outcome lookup without a name. The glob selects the freshest statable mtime;
    ties and wholly unstatable candidates use sorted order. No match returns None.
    """
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


# Context occupancy bands (three-tier-command.md §11): soft means hand off at the
# next boundary; hard means finish in-flight work and start none. Supervisor
# dispatch enforces its hard threshold. Explicit tiers prevent workers silently
# receiving the supervisor's higher allowance.
SUPERVISOR_BAND_SOFT_TOKENS = 350_000
SUPERVISOR_BAND_HARD_TOKENS = 400_000
WORKER_BAND_SOFT_TOKENS = 250_000
WORKER_BAND_HARD_TOKENS = 300_000

# The tiers `supervisor_band_verdict` accepts. Ordered strictest-first: the
# worker band is at or below the supervisor band at every occupancy, which is
# why an INDETERMINATE tier resolves to "worker" (fail toward the band, §11.2).
BAND_TIERS = ("worker", "supervisor")

# The three per-turn prompt summands whose SUM is context occupancy (B2). A
# turn's usage may carry any subset; occupancy sums whatever is present.
_OCCUPANCY_USAGE_FIELDS = (
    "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _transcript_occupancy(transcript_path):
    """Return context occupancy from the newest usable transcript usage record.
    Sum input_tokens, cache_creation_input_tokens and cache_read_input_tokens;
    input_tokens alone excludes cached context. Missing/unusable evidence returns None.
    """
    if not transcript_path:
        return None
    occupancy = None
    for line in _read_tail_lines(transcript_path):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        summands = [usage.get(f) for f in _OCCUPANCY_USAGE_FIELDS
                    if isinstance(usage.get(f), int)]
        if summands:
            occupancy = sum(summands)   # newest-wins: keep scanning to the tail
    return occupancy


def band_thresholds(tier):
    """Return the requested tier's (soft, hard) thresholds; unknown tiers raise ValueError."""
    if tier == "supervisor":
        return (SUPERVISOR_BAND_SOFT_TOKENS, SUPERVISOR_BAND_HARD_TOKENS)
    if tier == "worker":
        return (WORKER_BAND_SOFT_TOKENS, WORKER_BAND_HARD_TOKENS)
    raise ValueError(f"unknown context-band tier {tier!r} -- one of {BAND_TIERS}")


def supervisor_band_verdict(occupancy, tier):
    """Return below-band, in-band, over-band or assume-near-band for the requested tier.
    Only below-band has hand_off=False. Unknown occupancy prompts handoff;
    this advisory result does not itself refuse a dispatch. Include tier thresholds.
    """
    soft, hard = band_thresholds(tier)
    common = {"tier": tier, "soft_threshold": soft, "hard_threshold": hard}
    if occupancy is None:
        return {"verdict": "assume-near-band", "hand_off": True,
                "reason": "occupancy unreadable -- assume near-band, hand off at "
                          "the next boundary (§11.2 fails toward the band)",
                **common}
    if occupancy >= hard:
        return {"verdict": "over-band", "hand_off": True,
                "reason": f"occupancy {occupancy} >= {tier} hard ceiling {hard}: "
                          "finish in-flight work only, no new dispatches (§11.3)",
                **common}
    if occupancy >= soft:
        return {"verdict": "in-band", "hand_off": True,
                "reason": f"occupancy {occupancy} >= {tier} soft trigger {soft}: "
                          "hand off at the next wave/task boundary (§11.3)",
                **common}
    return {"verdict": "below-band", "hand_off": False,
            "reason": f"occupancy {occupancy} < {tier} soft trigger {soft}",
            **common}


def _record_sids(rec) -> set:
    """Return the record's current sid and retired sid union.
    Eager record restamps precede pull-based claim restamps; the union bridges that
    window for identity checks. Only the record's own prior sids may enter it.
    """
    sids = set()
    if not isinstance(rec, dict):
        return sids
    cur = rec.get("session_id")
    if isinstance(cur, str) and cur:
        sids.add(cur)
    retired = rec.get("retired_sids")
    if isinstance(retired, list):
        sids.update(s for s in retired if isinstance(s, str) and s)
    return sids


def _caller_holds_supervisor_claim(caller_sid, claim=None, registry=None):
    """Return True for the holder, False for a definite non-holder, else None.
    Resolve claim and caller through the same live record's sid union to bridge
    fork-steer restamp lag. Unreadable state or an unmatched holder sid is unknown.
    Use read-only registry access; ceiling callers fail toward the band on None.
    """
    if not caller_sid:
        return None
    if claim is None:
        claim = read_incarnation()
    if not isinstance(claim, dict) or claim.get("state") == "released":
        return False                    # no held claim -- never subject
    holder_sid = claim.get("session_id")
    if not isinstance(holder_sid, str) or not holder_sid:
        return None                     # a claim with no readable holder sid
    if caller_sid == holder_sid:
        return True                     # direct: claim not yet staled by a fork-steer
    if registry is None:
        registry = _registry_records_or_none()
    if registry is None:
        return None                     # registry unreadable -- indeterminate
    caller_rec_sids = None              # the sid union of the record the CALLER is in
    holder_seen = False                 # the holder sid was found in SOME record
    for rec in registry.get("workers", {}).values():
        sids = _record_sids(rec)
        if caller_sid in sids:
            caller_rec_sids = sids
        if holder_sid in sids:
            holder_seen = True
    if caller_rec_sids is not None:
        # The caller is a KNOWN body: it is the holder iff its own record also
        # carries the holder sid (the fork-steer union bridges the stale claim).
        return holder_sid in caller_rec_sids
    if holder_seen:
        # The holder record exists and does not carry the caller's sid -- the
        # caller is provably a DIFFERENT body, so it is not the holder.
        return False
    return None                         # neither sid placed -- indeterminate


def supervisor_claim_sids(claim=None, registry=None):
    """Return the claim-holder record's sorted sid union, or None if indeterminate.
    A readable holder sid carried by no record yields [holder_sid]. No active claim,
    an unreadable holder sid, or unreadable registry yields None. Consumers falling
    back to a bare sid must disclose that narrower evidence. Uses read-only access.
    """
    try:
        if claim is None:
            claim = read_incarnation()
        if not isinstance(claim, dict) or claim.get("state") == "released":
            return None
        holder_sid = claim.get("session_id")
        if not isinstance(holder_sid, str) or not holder_sid:
            return None
        if registry is None:
            registry = _registry_records_or_none()
        if registry is None:
            return None
        for rec in (registry.get("workers") or {}).values():
            sids = _record_sids(rec)
            if holder_sid in sids:
                return sorted(sids)
        return [holder_sid]
    except Exception:  # noqa: BLE001 -- a view never surfaces a traceback
        return None


def band_tier_for_sid(sid):
    """Return supervisor for a resolved claim-holder; otherwise return worker.
    Unknown identity selects the lower advisory band, prompting earlier handoff.
    The dispatch ceiling independently treats unknown identity as subject to its
    gate. This read-only measurement neither quarantines nor refuses.
    """
    return "supervisor" if _caller_holds_supervisor_claim(sid) is True else "worker"


def _record_is_supervisor_claim_holder(record, claim=None):
    """Return True for the holder record, False for a definite non-holder, else None.
    Absent or released claims return False. An unreadable held sid returns None;
    archive callers then protect supervisor-shaped names. Match the sid union to
    bridge eager registry restamps and delayed claim restamps.
    """
    if claim is None:
        claim = read_incarnation()
    if not isinstance(claim, dict) or claim.get("state") == "released":
        return False
    holder_sid = claim.get("session_id")
    if not isinstance(holder_sid, str) or not holder_sid:
        return None
    return holder_sid in _record_sids(record)


# Fleet identity resolves registry sid unions; FLEET_WORKER is a diagnostic witness.
# The worker-turn claim gate uses registry identity (SPEC.md:204). The ceiling's
# stamp-absence exemption has a separate limitation documented at its predicate.
#
# RATIFIED DOCTRINE -- claim-nonce §18:
# The daemon substitutes the session environment wholesale, therefore no
# FLEET_WORKER observation, present or absent, is evidence about this body.
# The sid is trustworthy: the vendor stamps each hosted session's own sid over
# the substituted environment, closed in the safe direction by counting, and
# every other env observation on a hosted body is evidence about the daemon's
# cold-starter, not about the body; the registry sid union is the only sound
# identity channel.

IDENTITY_RESOLVED = "resolved"
IDENTITY_UNRESOLVED = "unresolved"
IDENTITY_AMBIGUOUS = "ambiguous"


def _record_is_live(rec) -> bool:
    """A record that could plausibly BE an acting body right now: not archived,
    not marked dead. Only live records contend for an identity, so the husks a
    respawn or fork-steer leaves behind never manufacture an AMBIGUOUS verdict.
    Never raises: every caller is a hot path or a doctor row."""
    return (isinstance(rec, dict) and rec.get("archived_at") is None
            and rec.get("status") != "dead")


def _acting_worker_identity(sid=None, registry=None) -> dict:
    """Resolve the caller sid through registry sid unions without mutating state.
    Return verdict, name, record, matches, candidates, registry_read and sid.
    One candidate resolves; zero is unresolved; multiple are ambiguous. Prefer live
    matches to husks, and filter non-string names before sorting. A dispatch-window
    body can legitimately be unresolved while its sid has not been persisted.
    `registry_read` distinguishes a readable miss from abstention. Fresh absence
    counts as read; absence with a quarantine artifact does not. A healthy registry
    still answers identity so the §6.5 gate can recognize workers.
    The presence-only refusal that closes it lives in `_require_claim_holder`
    (`:11037`), because legacy upgrades also require a complete registry.
    `load_registry`
    QUARANTINES a corrupt registry -- it RENAMES the file aside (`:892`) -- and
    must not be used for this read. Corrupt/unreadable state yields unresolved.
    """
    if sid is None:
        sid = current_caller_session()
    ident = {"verdict": IDENTITY_UNRESOLVED, "name": None, "record": None,
             "matches": [], "candidates": [], "registry_read": False,
             "sid": sid}
    if not isinstance(sid, str) or not sid:
        return ident                    # no read happened: `registry_read` False
    if registry is None:
        ok, reason, data = _read_registry_readonly()
        registry = data if (ok or (reason == "not_initialized"
                                   and not _quarantine_artifacts())) else None
    ident["registry_read"] = isinstance(registry, dict)
    workers = registry.get("workers") if isinstance(registry, dict) else None
    if not isinstance(workers, dict):
        ident["registry_read"] = False
        return ident
    matches = sorted(n for n, rec in workers.items()
                     if isinstance(n, str) and sid in _record_sids(rec))
    if not matches:
        return ident
    ident["matches"] = matches
    live = [n for n in matches if _record_is_live(workers.get(n))]
    candidates = live or matches
    ident["candidates"] = candidates
    if len(candidates) == 1:
        ident["verdict"] = IDENTITY_RESOLVED
        ident["name"] = candidates[0]
        ident["record"] = workers.get(candidates[0])
    else:
        ident["verdict"] = IDENTITY_AMBIGUOUS
    return ident


def _acting_worker_name(sid=None, registry=None):
    """Return the resolved worker name, or None for unresolved/ambiguous identity."""
    return _acting_worker_identity(sid=sid, registry=registry)["name"]


def _acting_worker_record(sid=None, registry=None):
    """Return the resolved worker record, or None for an identity abstention."""
    return _acting_worker_identity(sid=sid, registry=registry)["record"]


def _acting_body_is_worker_turn(sid=None, registry=None, ident=None):
    """Return True for ordinary worker candidates, False for proven non-workers, else None.
    Uniform ambiguous candidates still answer by shape; mixed shapes abstain.
    A readable miss is False, allowing interface and dispatch-window callers.
    The §6.5 gate refuses only True; the nonce-free §9 upgrade requires False.
    This preserves supervisor recovery on unreadable state without granting an
    unauthenticated upgrade on an abstention.
    """
    if ident is None:
        ident = _acting_worker_identity(sid=sid, registry=registry)
    if not ident.get("registry_read"):
        return None
    if ident["verdict"] == IDENTITY_UNRESOLVED:
        return False                    # read, and no record carries this sid
    candidates = ident.get("candidates") or []
    if not candidates:
        return None                     # defensive: a verdict with no answers
    shapes = {_is_supervisor_shaped(n) for n in candidates}
    if len(shapes) != 1:
        return None                     # ambiguous AND mixed -- genuinely mute
    return not shapes.pop()


def _resolve_worker_target(name):
    """Resolve logical `supervisor` through the claim holder's registry sid union.
    Every other target passes through. Shape alone cannot distinguish predecessor
    and successor bodies. Missing/released/corrupt claims or unmatched holder sids
    raise named refusals. Read-only lookup leaves quarantine to lock-held mutations.
    """
    if name != SUPERVISOR_BODY_NAME:
        return name
    claim = read_incarnation()
    # Absent and released claims have distinct refusals; neither permits shape guessing.
    if not isinstance(claim, dict):
        raise FleetCliError(
            "no supervisor claim exists -- nothing answers to 'supervisor'; "
            "run `fleet sup-status`")
    if claim.get("state") == "released":
        raise FleetCliError(
            f"the supervisor claim ({claim.get('incarnation_id', '?')}) is "
            f"released -- nothing answers to 'supervisor' (a released claim "
            f"is terminal, and a supervisor-shaped record is never resolved "
            f"by shape); a new body claims via `fleet sup-boot`; "
            f"run `fleet sup-status`")
    holder_sid = claim.get("session_id")
    if not isinstance(holder_sid, str) or not holder_sid:
        raise FleetCliError(
            "the supervisor claim carries no readable holder sid -- nothing "
            "answers to 'supervisor'; inspect supervisor/INCARNATION "
            "(`fleet sup-status`)")
    data = read_registry_no_repair()
    for wname, rec in data.get("workers", {}).items():
        if holder_sid in _record_sids(rec):
            return wname
    raise FleetCliError(
        f"supervisor claim holder sid {holder_sid} matches no registry record "
        f"(stranded-stamp window? see the stranded-turn report) -- refusing to "
        f"resolve 'supervisor' by guesswork; run `fleet sup-status`")




def _ceiling_refuses_dispatch(verb, now=None):
    """Return a spawn/send refusal when supervisor occupancy reaches the hard band.
    Exempt absent FLEET_WORKER, absent sid and definite non-holders, in that order.
    Unknown holder identity remains subject; unknown occupancy refuses. Read the
    caller's own transcript and compare SUPERVISOR_BAND_HARD_TOKENS.
    The stamp-absence exemption can also exempt a hosted supervisor because the
    daemon substitutes its environment; this is a current limitation (§18.4).
    SPEC.md:204's worker-turn claim prohibition concerns the separate claim gate.

    RATIFIED DOCTRINE -- claim-nonce §18:
    The daemon substitutes the session environment wholesale, therefore no
    FLEET_WORKER observation, present or absent, is evidence about this body.
    The sid is trustworthy: the vendor stamps each hosted session's own sid over
    the substituted environment, closed in the safe direction by counting, and
    every other env observation on a hosted body is evidence about the daemon's
    cold-starter, not about the body; the registry sid union is the only sound
    identity channel.
    The exemption and unknown-identity rule give opposite answers for an absent
    registry member; this function retains both behaviors pending their resolution.
    """
    # Stamp absence exempts before sid or registry reads. Hosted bodies can also lack
    # this stamp; see the predicate's documented limitation.
    if not (os.environ.get("FLEET_WORKER") or "").strip():
        return None
    caller = current_caller_session()
    if caller is None:
        return None                     # no sid -> cannot be the claim-holder body
    if _caller_holds_supervisor_claim(caller) is False:
        return None                     # a claim is held, this is not its holder
    # holder (True) or indeterminate (None, ND4b fail-toward-band): apply the
    # ceiling. Occupancy is the caller's own transcript (never the claim's sid).
    occupancy = _transcript_occupancy(find_transcript_path(None, caller))
    if occupancy is not None and occupancy < SUPERVISOR_BAND_HARD_TOKENS:
        return None                     # below the hard ceiling -- dispatch allowed
    occ_txt = f"{occupancy:,} tokens" if occupancy is not None else "unreadable"
    return (
        f"{verb}: refusing -- the supervisor claim-holder's context occupancy "
        f"({occ_txt}) is at or above the {SUPERVISOR_BAND_HARD_TOKENS:,}-token hard ceiling "
        f"(three-tier §11.3). Past the ceiling, start NO new worker turns: let "
        f"the in-flight wave finish and READ its outcomes (`fleet status`/"
        f"`result`/`peek`/`wait`), then hand off (`fleet sup-handoff-begin`). "
        f"The handoff verbs are exempt from this refusal. (Fleet-enforced, not "
        f"discretion. A session with no `FLEET_WORKER` stamp is exempt "
        f"structurally, three-tier §11.3 ND4c -- so if you believe you are the "
        f"interface tier and are reading this, the hosting daemon substituted "
        f"an environment carrying a stamp into a session it never launched: "
        f"`fleet doctor` names that leak.)")


def _record_time(rec: dict):
    """Parse a transcript timestamp as aware UTC, or None on missing/invalid input.
    Fractional seconds are allowed (spike/m0/VERDICTS.md:441). Replace trailing Z
    with +00:00 for Python 3.10 compatibility. Callers must not guess a wall-clock
    anchor when the record supplies none.
    """
    ts = rec.get("timestamp") if isinstance(rec, dict) else None
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts[:-1] + "+00:00" if ts.endswith("Z") else ts)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def transcript_limit_scan(sid: str, transcript_path=None):
    """Return (is_limit, reset_at, kind) from the authoritative transcript-tail record.
    Walk newest-first past bookkeeping; the first API error or substantive message
    wins, so older 429s cannot override newer chatter or errors. Require structured
    isApiErrorMessage plus status 429 or error=rate_limit; quoted text cannot park.
    Anchor local resets to the record timestamp. Missing time/zone evidence leaves
    a null horizon for manual recovery. Missing/unreadable transcript access returns
    (False, None, None). An explicit path avoids repeating the caller's resolution.
    """
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
            reset_at, kind = _parse_limit_signal("\n".join(parts), now=_record_time(rec))
            return True, reset_at, kind
        # First qualifying (error-shaped or substantive) record does not
        # match the limit shape -- it is the authoritative "last thing
        # that happened" and the scan stops here, never mind an older
        # stale wall further back.
        return False, None, None
    return False, None, None


def _is_substantive_transcript_record(rec: dict) -> bool:
    """Whether an assistant/user record carries text or tool/image content.
    Bookkeeping and empty messages do not stop the newest-first limit scan.
    """
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


# Native verdicts use roster and Stop-hook outcomes. _limit_scan_hook is the
# injectable transcript reader for turns whose limit wall leaves no fresh outcome.

_limit_scan_hook = transcript_limit_scan  # Injectable transcript-tail limit scanner.

NATIVE_TERMINAL_STATUSES = {"idle", "dead", "dead-suspected", "limited",
                            "over_ceiling", "interrupted"}
# Re-evaluate dead-suspected so a late outcome can return the worker to idle.
_NATIVE_STICKY = ("dead", "over_budget", "over_ceiling", "limited",
                  "interrupted", "attached")


def _dispatch_grace_active(record: dict) -> bool:
    """Whether a new dispatch remains inside the launch claim grace period.
    A state-only roster entry can be a starting session; absent fields are not enough
    to demote it during grace. Use last_dispatch_at, else created, and retain grace
    without a parseable age anchor.
    """
    anchor = record.get("last_dispatch_at") or record.get("created")
    return not _launch_claim_expired(anchor)


def _investigate_no_outcome(name: str, record: dict, updated: dict) -> dict:
    """Classify missing fresh outcomes as limited, working in grace, or dead-suspected.
    Resolve the transcript by name/sid and pass it to the injectable limit scanner.
    Both idle and absent/dead roster branches share this investigation.
    """
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
    """Derive a native worker verdict in order:
    1. Preserve sticky statuses.
    2. Keep sid-less launches working until claim expiry, then mark dead.
    3. Live roster busy/waiting means working; waiting carries a permission flag.
    4. Idle, dead or missing roster entries require a fresh outcome, else investigate.
    Freshness checks sid and last_dispatch_at (else created), so a predecessor's or
    prior turn's outcome cannot vouch for this turn. State-only startup entries use
    the shared grace window before a dead-suspected verdict.
    """
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
    """Whether roster failure or universal absence of expected sids freezes the epoch.
    The caller must preserve working records when the native evidence source fails.
    """
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
    # An absent status earns no flag; optional fields use tolerant reads.
    status = record.get("status")
    sid = record.get("session_id")
    flags = []
    if status == "idle" and sid and _pending_mail_count(sid) > 0:
        flags.append("idle+mail")
    if status == "attached":
        age = _attach_age_seconds(record)
        if age is not None and age > STALE_ATTACH_SECONDS:
            flags.append("stale-attach")
    if status == "dead":
        flags.append("dead")
    # M-B T5: dead-suspected is a native-only, non-sticky verdict -- surface
    # it as an operator prompt to look, never an auto-respawn trigger.
    if status == "dead-suspected":
        flags.append("investigate: no outcome record")
    # M-B T5: recompute_worker_native sets this transient field (never part
    # of new_worker_record's base schema) when the roster reports the native
    # session paused on a permission prompt.
    if record.get("waiting_for_permission"):
        flags.append("waiting-permission")
    # Kernel 10 (F12=M24): surface the fleet-side token-ceiling refusal in
    # `fleet status`, mirroring how over_budget shows up as its own status.
    if status == "over_ceiling":
        flags.append("over-ceiling")
    # UL1 (item 11 / F31): surface a parked worker's reset horizon and, once
    # the horizon has passed, its resume-eligibility -- a read-only FLAG only,
    # never an auto-launch (invariant 1 daemonless: status derives views, it
    # does not start turns; the operator runs `fleet resume-limited`).
    if status == "limited":
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


# Permission-stall evidence is roster-only: waiting_for_permission is transient
# and stripped before registry writes. File-only views cannot detect stalls
# without violating D1/D4; callers supply their existing roster snapshot.

def _worktree_deny_rules(cwd) -> list:
    """Read permissions.deny strings from the worker cwd's local settings.
    Malformed/missing/unreadable settings yield []; this is diagnostic evidence,
    not a permission-policy interpreter.
    """
    try:
        raw = (Path(cwd) / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    except (OSError, ValueError, TypeError):
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        return []
    deny = perms.get("deny")
    if not isinstance(deny, list):
        return []
    return [rule for rule in deny if isinstance(rule, str)]


def _permission_stalls(workers: dict, roster_entries: list, now=None) -> list:
    """Return (name, record, elapsed, waiting_for) for long native permission stalls.
    Require working records and roster waiting status; attached workers have a human
    answerer and are excluded. Elapsed is turn age, not time at the prompt, because
    no waiting_since exists. Missing age still reports the witnessed stall.
    """
    now = now or datetime.now(timezone.utc)
    stalls = []
    for name, rec in sorted(workers.items()):
        if not isinstance(rec, dict) or not is_native(rec):
            continue
        if rec.get("archived_at") is not None:
            continue
        if rec.get("status") != "working":
            continue
        sid = rec.get("session_id")
        if not isinstance(sid, str) or not sid:
            continue
        entry = _roster_entry_for(roster_entries, sid)
        if not isinstance(entry, dict) or entry.get("status") != "waiting":
            continue
        try:
            elapsed = (now - _parse_iso(rec["last_activity"])).total_seconds()
        except (KeyError, ValueError, TypeError):
            elapsed = None
        if elapsed is not None and elapsed < PERMISSION_STALL_SECONDS:
            continue
        waiting_for = entry.get("waitingFor")
        stalls.append((name, rec, elapsed,
                       waiting_for if isinstance(waiting_for, str) else None))
    return stalls


def _permission_stall_line(name: str, rec: dict, elapsed, waiting_for) -> str:
    """Render a permission stall with worker, directory, duration and remedies.
    Include worker-local deny rules as diagnostic context; the operator must resolve
    the prompt or permissions rather than treating the turn as useful progress.
    """
    age = "age unknown" if elapsed is None else f"{elapsed / 60:.0f}m"
    detail = f"waitingFor: {waiting_for}" if waiting_for else "no waitingFor reported"
    cwd = rec.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cause = "worker record carries no cwd -- inspect its settings by hand"
    else:
        # Built through Path so the separators match the platform the operator
        # is going to paste it into -- an f-string with "/" renders
        # `C:\proga\wt/.claude/settings.local.json` on Windows.
        settings = str(Path(cwd) / ".claude" / "settings.local.json")
        rules = _worktree_deny_rules(cwd)
        if rules:
            cause = (f"{settings} denies {', '.join(rules)} -- a deny beats EVERY "
                     f"permission mode, `bypass` included, so a matching call "
                     f"never returns")
        else:
            cause = (f"no deny rules readable in {settings} -- the prompt is "
                     f"coming from an inherited settings file or from the "
                     f"worker's own mode")
    return (f"{name} (working {age}, {detail}, cwd {cwd or '?'}): {cause}. "
            f"`fleet peek {name}` shows the pending call; then fix the cause and "
            f"`fleet respawn {name}`, or `fleet kill {name}`")


# File-only terminal views: no fleet_lock, liveness probe or write.
# The statusline can refresh after every assistant message.
# D4: it must NOT call load_registry() -- that quarantines a corrupt registry
# Views report corrupt evidence instead of renaming it during repeated refreshes.

def _read_registry_readonly() -> tuple:
    """Return (ok, reason, projected workers) without writes, locks or probes.
    Failure reasons are not_initialized, quarantined or unreadable. An absent file
    with an artifact is quarantined; healthy files answer for themselves.
    Handles ordinary filesystem/decode/shape errors; deep or oversized JSON and
    errors from the initial exists() call can still propagate.
    """
    path = registry_path()
    if not path.exists():
        if _quarantine_artifacts():
            return (False, "quarantined", {"workers": {}})
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


def read_registry_at(home) -> tuple:
    """Read a supplied home's registry without locking, writing or quarantining.
    Return (ok, reason, projected workers), with the same absence/incident vocabulary
    as _read_registry_readonly. Absorb parse RecursionError/MemoryError as unreadable
    so one adversarial listed home cannot break every cross-home lookup.
    """
    try:
        path = registry_path_at(home)
        exists = path.exists()
    except (OSError, ValueError):
        # A path the OS refuses to even stat (illegal characters, a reparse
        # point loop, a dead network share). Unreadable, not absent: absence is
        # an affirmative claim here and we did not get to make it.
        return (False, "unreadable", {"workers": {}})
    if not exists:
        if _quarantine_artifacts_at(path.parent):
            return (False, "quarantined", {"workers": {}})
        return (False, "not_initialized", {"workers": {}})
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError,
            RecursionError, MemoryError):
        # Deep/oversized foreign JSON must not take down every cross-home lookup.
        return (False, "unreadable", {"workers": {}})
    if _registry_corrupt_reason(data) is not None:
        # Share validation so read-only and repairing loaders agree on registry shape.
        return (False, "unreadable", {"workers": {}})
    return (True, None, {"workers": data.get("workers", {})})


def home_is_initialized(home) -> bool:
    """Whether the home's state/fleet.json is readable as a registry.
    Settings alone do not initialize it; init creates the registry and settings,
    while only explicit --home also registers the home in the machine list.
    """
    return read_registry_at(home)[0]


# Machine homes list (multi-fleet §4): append-only records and last-record-wins fold.
# Append atomically for concurrent writers; overwriting a snapshot loses other
# writers' records. A !-prefixed retirement changes membership without deletion.

HOMES_LIST_RETIRE_PREFIX = "!"

# Use the spec's absolute-path grammar on every platform and interpreter floor.
# os.path.isabs differs by OS and version; using it would change the armed home
# population solely because a different interpreter runs the same command.
_HOMES_LIST_ABSOLUTE = re.compile(
    r"^(?:"
    r"[A-Za-z]:[\\/]"                    # drive-letter root:  C:\fleet  C:/fleet
    r"|[\\/]{2}[^\\/]+[\\/]+[^\\/]+"     # UNC: \\server\share  //server/share
    r"|/"                                # POSIX root: /srv/fleet
    r")")


def homes_path_is_absolute(text) -> bool:
    """Recognize the spec's POSIX, drive-letter and UNC absolute path grammar.
    Do not delegate to os.path.isabs, whose accepted shapes differ across floors.
    """
    return bool(_HOMES_LIST_ABSOLUTE.match(str(text)))


def _has_parent_segment(text) -> bool:
    """§4: *"no `..`"*. SEGMENT-wise, not substring-wise: `C:/a..b/fleet` is a
    perfectly ordinary directory name and must not be refused."""
    return ".." in re.split(r"[\\/]", str(text))


def home_identity(text) -> str:
    """Normalize separators and trailing slashes while preserving all path casing.
    Do not resolve symlinks or case-fold: identities are the exact fold keys used
    for retirement. Overcounting aliases arms conservatively; undercounting could
    silently disable the wrong-home guard.
    """
    s = str(text).strip().replace("\\", "/")
    while len(s) > 1 and s.endswith("/"):
        s = s[:-1]
    return s


# Home tags hash the full normalized identity: basenames of fleet homes often match.
# Hex bounds the display width and cannot inject controls or statusline brackets.
# Tags can collide and therefore never choose a home.

# Four hex digits bound display width; fleet homes shows tags beside full paths.
HOME_TAG_HEX = 4


def home_tag(home) -> str:
    """Return HOME_TAG_HEX hex digits of the normalized home identity's hash.
    The tag is a stable display hint, not an identifier used to select a home.
    """
    ident = home_identity(home)
    digest = hashlib.sha256(ident.encode("utf-8", "backslashreplace")).hexdigest()
    return digest[:HOME_TAG_HEX]


def parse_homes_list_line(line) -> tuple:
    """Parse one list line as (blank|invalid|add|retire, identity).
    Require the specified absolute grammar and reject parent segments; one invalid
    record does not invalidate its neighbors.
    """
    text = str(line).strip()
    if not text:
        return ("blank", None)
    retired = text.startswith(HOMES_LIST_RETIRE_PREFIX)
    if retired:
        text = text[len(HOMES_LIST_RETIRE_PREFIX):].strip()
    if not text or not homes_path_is_absolute(text) or _has_parent_segment(text):
        return ("invalid", None)
    return ("retire" if retired else "add", home_identity(text))


def fold_homes_list(text) -> dict:
    """Fold valid list records with last-record-wins membership per identity.
    Invalid lines are counted separately; a later add restores a retired member.
    """
    order, state, invalid, records = [], {}, 0, 0
    for line in str(text).splitlines():
        kind, ident = parse_homes_list_line(line)
        if kind == "blank":
            continue
        if kind == "invalid":
            invalid += 1
            continue
        records += 1
        if ident not in state:
            order.append(ident)
        state[ident] = (kind == "add")
    return {"members": [i for i in order if state[i]],
            "retired": [i for i in order if not state[i]],
            "invalid_lines": invalid, "records": records}


def _decode_homes_list(raw: bytes, path) -> tuple:
    """Decode BOM-selected UTF-8/UTF-16, else UTF-8 with tolerant fallbacks.
    Strip BOM bytes before decoding so the first record remains parseable.
    Return (text, decode_note) without discarding readable neighboring records.
    """
    for bom, encoding in ((b"\xef\xbb\xbf", "utf-8"),
                          (b"\xff\xfe", "utf-16-le"),
                          (b"\xfe\xff", "utf-16-be")):
        if raw.startswith(bom):
            try:
                # Drop BOM bytes first so U+FEFF cannot invalidate the first absolute-path record.
                return (raw[len(bom):].decode(encoding), None)
            except UnicodeDecodeError:
                break
    try:
        return (raw.decode("utf-8"), None)
    except UnicodeDecodeError:
        pass
    for encoding in ("mbcs", "latin-1"):
        try:
            text = raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        return (text, f"{path}: not UTF-8 and carries no BOM -- decoded as "
                      f"{encoding}, so a non-ASCII home path may be misread. "
                      f"Rewrite the file as UTF-8.")
    # Unreachable while latin-1 exists; kept as a belt so the function stays
    # total by construction rather than by an argument about codecs.
    return (raw.decode("utf-8", errors="replace"),
            f"{path}: undecodable bytes were replaced")


def read_homes_list() -> dict:
    """Read and fold the machine homes list without creating or modifying it.
    Return path, readability, members, invalid-line count and decode diagnostics.
    Absence is an empty list; unreadability remains explicit for arming decisions.
    """
    path = homes_list_path()
    out = {"path": path, "ok": True, "reason": None, "members": [],
           "retired": [], "invalid_lines": 0, "decode_note": None}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        out["reason"] = "absent"
        return out
    except (OSError, ValueError):
        out["ok"] = False
        out["reason"] = "unreadable"
        return out
    text, note = _decode_homes_list(raw, path)
    out["decode_note"] = note
    folded = fold_homes_list(text)
    out["members"] = folded["members"]
    out["retired"] = folded["retired"]
    out["invalid_lines"] = folded["invalid_lines"]
    return out


def homes_population() -> dict:
    """Read the homes list and attach each member's registry state and worker snapshot.
    Use one snapshot per member for both classification and rendering. Preserve
    not_initialized, quarantined and unreadable as distinct population facts.
    """
    out = dict(read_homes_list())
    homes = []
    for ident in out["members"]:
        ok, reason, data = read_registry_at(ident)
        # Carry workers from this snapshot so the renderer does not read the home twice.
        homes.append({"path": ident, "ok": ok, "reason": reason,
                      "workers": len(data["workers"])})
    out["homes"] = homes
    return out


def append_home_record(home, retire: bool = False) -> str:
    """Append one canonical homes-list record and return the written identity.
    Validate the identity before writing. Atomic platform append protects concurrent
    writers; the fold reverses membership through a later record, not an overwrite.
    """
    ident = home_identity(home)
    if not homes_path_is_absolute(ident) or _has_parent_segment(ident):
        raise FleetCliError(
            f"not an absolute home path: {str(home)!r}. The homes list takes a "
            f"drive-letter (`C:\\fleet`), UNC (`\\\\server\\share\\fleet`) or "
            f"POSIX (`/srv/fleet`) absolute path with no `..` segment.")
    path = homes_list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (HOMES_LIST_RETIRE_PREFIX if retire else "") + ident + "\n"
    PLATFORM.atomic_append_bytes(path, line.encode("utf-8"))
    return ident


# Home resolution order (§5): explicit flag, sid lookup, validated imported default,
# then terminus. Resolution reads without writes/locks/probes; apply_resolved_home
# owns dispatch policy so every caller shares one home-selection algorithm.

#: §5 step 5's rendered terminus, verbatim from the spec: *"views render
#: `[fleet]: no home` and exit 0"*.
NO_HOME_LINE = "[fleet]: no home"

# Terminus views render no home; mutations require a named initialized home.
# Flag-qualified writers are removed from this view set at invocation time.
TERMINUS_VIEW_VERBS = ("home", "knowledge", "status", "peek", "result",
                       "doctor", "q", "sup-status", "sup-context",
                       "sup-guard")

# Machine-scope verbs bypass home resolution, including ambiguous lookup, because
# fleet homes must remain available to repair the list that caused the ambiguity.
TERMINUS_EXEMPT_VERBS = ("homes",)

# Init's creation modes bypass home resolution: --home names its own creation
# target; bare init creates cwd. Explicit --fleet-home and --statusline retain
# home resolution. No invocation may silently ignore a second home selection.
TERMINUS_EXEMPT_FLAGS = {"init": ("home",)}


def machine_exempting_flags(command, args) -> tuple:
    """The `TERMINUS_EXEMPT_FLAGS` dests that are SET on this invocation.

    Returns option spellings (`--home`), not dests, because the only consumer
    puts them in a refusal an operator reads. Empty tuple = this invocation acts
    on a home and takes §5's order."""
    return tuple(
        "--" + dest.replace("_", "-")
        for dest in TERMINUS_EXEMPT_FLAGS.get(command, ())
        if getattr(args, dest, None) not in (None, False))


def homes_are_same(a, b) -> bool:
    """Compare existing homes via samefile, falling back to normalized path identity.
    Catch filesystem failures; string normalization supplies deterministic comparison
    when samefile cannot answer.
    """
    try:
        pa, pb = Path(a), Path(b)
    except (TypeError, ValueError):
        return False
    try:
        if pa.exists() and pb.exists():
            return pa.samefile(pb)
    except (OSError, ValueError):
        pass
    try:
        return (os.path.normcase(str(pa.resolve()))
                == os.path.normcase(str(pb.resolve())))
    except (OSError, ValueError):
        return False


def validate_named_home(text, source: str = "--fleet-home") -> Path:
    """Resolve an explicit home, then require a directory and initialized registry.
    Refuse invalid paths without mkdir or falling through to a different home.
    """
    raw = "" if text is None else str(text)
    if not raw.strip():
        raise FleetCliError(
            f"{source} takes a path and was given an empty value. A home is "
            f"named explicitly or not at all -- an empty one would resolve to "
            f"the current directory, which is exactly the accident this flag "
            f"exists to prevent.")
    try:
        home = Path(raw).resolve()
    except (OSError, ValueError) as exc:
        raise FleetCliError(f"{source}: cannot resolve {raw!r} ({exc})")
    if not home.is_dir():
        raise FleetCliError(
            f"{source} does not exist or is not a directory: {home} "
            f"(from {raw!r}). Nothing was created -- `{source}` names an "
            f"existing home and never makes one.")
    if not home_is_initialized(home):
        reason = read_registry_at(home)[1]
        raise FleetCliError(
            f"{source} {home} is not initialized ({reason}) -- an initialized "
            f"home is one whose `state/fleet.json` exists and parses "
            f"(docs/specs/multi-fleet.md, Definitions). Nothing was created.")
    return home


def resolution_population(install=None) -> dict:
    """Return the folded home list plus the legacy install-root home, deduplicated.
    Keep unreadability and invalid-line metadata for the guard's arming decision.
    """
    if install is None:
        install = INSTALL_ROOT
    listed = read_homes_list()
    legacy = home_identity(install)
    homes, seen = [], set()
    for ident in list(listed["members"]) + [legacy]:
        if ident not in seen:
            seen.add(ident)
            homes.append(ident)
    return {"homes": homes, "legacy": legacy,
            "list_ok": listed["ok"], "list_reason": listed["reason"],
            # Readable bytes can still contain unparseable records, leaving home count unknown.
            "list_invalid_lines": listed["invalid_lines"],
            "listed_members": list(listed["members"])}


def lookup_home_for_sid(sid, population=None, install=None) -> dict:
    """Look up sid membership with one lock-free registry snapshot per home.
    Return no_sid, hit, miss or ambiguous plus hits, unreadable homes and census.
    Membership uses current/retired sid unions; spawned_by is the manager's identity
    and grants no membership. Misses fall through, including newborn dispatches;
    unreadable homes remain reported because their potential membership is unknown.
    Equivalent path spellings count as one hit.
    """
    pop = resolution_population(install) if population is None else population
    out = {"state": "no_sid", "home": None, "hits": [], "unreadable": [],
           "population": list(pop["homes"]), "legacy": pop["legacy"],
           "list_ok": pop["list_ok"], "list_reason": pop["list_reason"],
           "list_invalid_lines": pop.get("list_invalid_lines", 0),
           # None means no census was read; [] means a read found no homes.
           # Arming must distinguish them instead of treating a sid-less lookup as empty.
           "states": None}
    if not sid or not str(sid).strip():
        return out
    out["states"] = []
    for ident in pop["homes"]:
        ok, reason, data = read_registry_at(ident)
        # ONE SNAPSHOT PER HOME (§5.2), so the census is filled from the read
        # that was already happening rather than by a second pass. A second
        # `read_registry_at` here would double the cost of every sid-carrying
        # invocation on a surface that has been O(1) forever.
        out["states"].append({"home": ident, "ok": ok, "reason": reason})
        if not ok:
            if reason == "unreadable":
                out["unreadable"].append(ident)
            continue
        if any(sid in _record_sids(rec) for rec in data["workers"].values()):
            out["hits"].append(ident)
    hits = out["hits"]
    if not hits:
        out["state"] = "miss"
    elif len(hits) == 1 or all(homes_are_same(hits[0], h) for h in hits[1:]):
        # Two spellings of ONE directory are one hit, not an ambiguity: §5's
        # two-plus refusal is about a sid claimed by two FLEETS. `homes_are_same`
        # is affordable here and not in the population because the hit set is
        # at most one entry per listed home that actually matched.
        out["state"], out["home"] = "hit", hits[0]
    else:
        out["state"] = "ambiguous"
    return out


def resolve_home(flag=None, sid=None, env=None, default_home=None,
                 install=None, population=None) -> dict:
    """Resolve explicit flag, sid membership, imported default home, then terminus.
    Return home, step, lookup and disagreement; ambiguous unflagged lookup refuses.
    The default is the module global, preserving the path-helper isolation seam;
    env labels whether that global came from environment or legacy install root.
    An uninitialized named default terminates instead of silently retargeting the
    install. Disagreement and terminus policy remain apply_resolved_home decisions.
    """
    if env is None:
        env = os.environ.get("FLEET_HOME")
    if sid is None:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if default_home is None:
        default_home = FLEET_HOME
    if install is None:
        install = INSTALL_ROOT
    default_home = Path(default_home)

    out = {"home": None, "step": None, "sid": (sid or None), "flag": None,
           "disagreement": None, "disagreement_homes": [],
           "default_home": default_home,
           "lookup": lookup_home_for_sid(sid, population=population,
                                         install=install)}
    look = out["lookup"]

    # --- step 1: the flag. Validated BEFORE the lookup's answer is consulted,
    # so a bad --fleet-home is refused on its own terms rather than being
    # silently outranked by a membership the operator never mentioned.
    if flag is not None:
        home = validate_named_home(flag)
        out["home"], out["step"], out["flag"] = home, "flag", home
        # A flag disagrees with all claiming homes unless it names one of them.
        # Choosing an ambiguous candidate is the remedy; pointing at an unrelated third
        # home still requires the disagreement guard. Compare home identities, not strings.
        claimants = [look["home"]] if look["state"] == "hit" else list(look["hits"])
        if claimants and not any(homes_are_same(home, h) for h in claimants):
            out["disagreement"] = claimants[0]
            out["disagreement_homes"] = list(claimants)
        return out

    # --- step 2: sid -> home.
    if look["state"] == "ambiguous":
        raise FleetCliError(_refuse_ambiguous_lookup(look, sid))
    if look["state"] == "hit":
        out["home"], out["step"] = Path(look["home"]), "lookup"
        return out

    # --- steps 3 and 4, collapsed in the shipped global (see the docstring).
    if home_is_initialized(default_home):
        env_named = None
        if env and str(env).strip():
            try:
                env_named = Path(env).resolve()
            except (OSError, ValueError):
                env_named = None
        from_env = env_named is not None and homes_are_same(env_named, default_home)
        out["home"] = default_home
        out["step"] = "env" if from_env else "legacy"
        return out

    # --- step 5: terminus. `step` stays None; nothing else in this function
    # may invent a home here, which is the whole point of naming the state.
    return out


def _refuse_ambiguous_lookup(look, sid) -> str:
    """Render all claiming homes and require an explicit --fleet-home choice.
    Include the homes view directly so the refusal supplies its own remedy's facts;
    do not select or truncate the candidates for the operator.
    """
    homes = "\n".join(f"    {h}" for h in look["hits"])
    return (f"session {sid} is a member of {len(look['hits'])} fleet homes, so "
            f"no home can be resolved from membership alone:\n{homes}\n"
            f"Name the one you mean with `--fleet-home <PATH>`.\n\n"
            f"{render_homes_view()}")


def resolution_provenance(res) -> str:
    """Render the chosen home and resolution step, including unreadable lookup homes.
    A missing lookup is tolerated. Unreadable candidates must remain visible because
    they may also own the sid even when the readable lookup appears unambiguous.
    """
    step = res["step"]
    if step is None:
        return f"{NO_HOME_LINE} -- no flag, no membership, no initialized default"
    where = {"flag": "--fleet-home", "lookup": "session membership",
             "env": "$FLEET_HOME", "legacy": "the legacy install-root default"}[step]
    line = f"[fleet] home {Path(res['home']).as_posix()} (via {where})"
    unreadable = (res.get("lookup") or {}).get("unreadable") or []
    if unreadable:
        line += (f"; {len(unreadable)} listed home(s) could not be read and "
                 f"may claim this session: " + ", ".join(unreadable))
    return line


def _terminus_refusal(command: str) -> str:
    """§5 step 5: *"mutating verbs refuse with the named remedy (`--fleet-home`
    or `FLEET_HOME`)"*. The remedy is NAMED, never pre-filled -- §5's refusal
    contract bans *"a paste-ready command with a chosen home"*, because the one
    thing fleet must not do at the terminus is pick a home for the operator."""
    return (f"no fleet home resolved, so `{command}` has nowhere to act. No "
            f"`--fleet-home`, no home whose registry claims this session, and "
            f"the default home is not initialized (a directory whose "
            f"`state/fleet.json` exists and parses). Name a home with "
            f"`--fleet-home <PATH>` or `FLEET_HOME`.\n\n"
            f"{render_homes_view()}")


def _multi_fleet_population_is_live(look) -> bool:
    """Whether at least one home is listed, or the list is unreadable.
    Gate terminus enforcement only; the counted multi_fleet_arming rule is separate.
    An absent list retains single-fleet behavior.
    """
    if not look["list_ok"]:
        return True
    return [h for h in look["population"] if h != look["legacy"]] != []


# Verb-effect tuples transcribe multi-fleet §5 and are pinned against the spec.
# Destructive env/legacy resolution requires a flag; disruptive proceeds with
# provenance; ordinary proceeds. Keep runtime policy as data here so markdown
# edits do not change dispatch behavior.

VERB_EFFECT_DESTRUCTIVE = ("clean", "archive", "autoclean",
                           "doctor --repair", "sup-handoff-abort",
                           "sup-boot", "sup-handoff-begin",
                           "sup-handoff-complete", "sup-decision --clear",
                           "sup-spawn", "sup-checkpoint", "sup-release",
                           # Homes-list writes are destructive; the bare list view has an ordinary residual.
                           "homes --add", "homes --retire",
                           # init --home appends to the machine list and is destructive.
                           # Bare init creates only its target home and uses the ordinary residual.
                           "init --home", "journal-roll")
VERB_EFFECT_DISRUPTIVE = ("kill", "interrupt", "send", "respawn", "release",
                          "resume-limited", "sup-heartbeat", "interface-register")
VERB_EFFECT_ORDINARY = ("spawn", "status", "peek", "result",
                        "home", "knowledge", "attach", "wait", "sup-status",
                        "sup-context", "sup-guard", "q", "index")

#: Tier ranking. A verb matching two tokens takes the WORST of them, which is
#: the only direction §5's *"worst irreversible effect in the wrong home"*
#: admits.
VERB_EFFECT_TIERS = ("ordinary", "disruptive", "destructive")

# Residuals describe a flag-qualified verb when its destructive flag is absent.
# Keep bare verbs out of the tuples: a missing flagged token must fail toward
# unknown/destructive instead of falling back to a second ordinary row.
#   * doctor: report-only without --repair.
#   * sup-decision: show without writing flags.
#   * homes: list without --add/--retire.
#   * init: create inside its target without --home machine registration.
VERB_EFFECT_RESIDUAL = {"doctor": "ordinary", "sup-decision": "ordinary",
                        "homes": "ordinary", "init": "ordinary"}

# Decision writes without a classified tier remain destructive, never ordinary.
# Explicit dests are needed because argparse maps --raise to question;
# option-string normalization alone would miss that write.
VERB_EFFECT_RESIDUAL_FLAGS = {
    "sup-decision": (("question", "destructive"), ("answer", "destructive")),
}


def _verb_effect_index() -> dict:
    """Derive verb -> ((flag_dest_or_None, tier), ...) from the effect tuples.
    Argparse's default dash-to-underscore mapping serves these flag-qualified tokens;
    a bare verb uses None to match every invocation.
    """
    index = {}
    for tier in VERB_EFFECT_TIERS:
        tokens = {"ordinary": VERB_EFFECT_ORDINARY,
                  "disruptive": VERB_EFFECT_DISRUPTIVE,
                  "destructive": VERB_EFFECT_DESTRUCTIVE}[tier]
        for token in tokens:
            parts = token.split()
            dest = parts[1].lstrip("-").replace("-", "_") if len(parts) > 1 else None
            index.setdefault(parts[0], []).append((dest, tier))
    return {verb: tuple(rows) for verb, rows in index.items()}


def verb_effect_tier(command, args=None) -> str:
    """Return the worst matching effect tier; unknown verbs are destructive.
    Flag absence uses declared residuals only. Presence excludes None and False,
    but includes an empty string because --answer '' still writes decision state.
    """
    rows = list(_verb_effect_index().get(command, ()))
    rows += list(VERB_EFFECT_RESIDUAL_FLAGS.get(command, ()))
    if not rows:
        return "destructive"
    matched = [tier for dest, tier in rows
               if dest is None or getattr(args, dest, None) not in (None, False)]
    if not matched:
        return VERB_EFFECT_RESIDUAL.get(command, "destructive")
    return max(matched, key=VERB_EFFECT_TIERS.index)


#: A listed home counts toward §5's armed population when its registry is
#: READABLE or when we could not find out what is in it. `not_initialized` is
#: the one `read_registry_at` reason that does NOT count -- see
#: `multi_fleet_arming`'s docstring for the two grounds.
MULTI_FLEET_ARMING_UNKNOWN_REASONS = ("unreadable", "quarantined")


def multi_fleet_arming(look=None, population=None, install=None) -> dict:
    """Return armed, reason, indeterminate, counted, skipped_not_initialized and population.
    Unreadable lists or unparseable records arm because the population is unknown.
    Otherwise fewer than two candidate homes stays unarmed without disk reads.
    Count readable, unreadable and quarantined homes; exclude known uninitialized
    homes, which cannot resolve membership. Reuse a supplied lookup census so each
    home is read once per invocation; two counted homes arm the guard.
    """
    if look is None:
        look = lookup_home_for_sid(None, population=population, install=install)
    out = {"armed": False, "reason": "population_below_two",
           "indeterminate": False, "counted": [],
           "skipped_not_initialized": [],
           "population": list(look["population"])}
    if not look.get("list_ok", True):
        out.update(armed=True, indeterminate=True, reason="list_unreadable")
        return out
    if look.get("list_invalid_lines", 0):
        out.update(armed=True, indeterminate=True,
                   reason="list_has_unparseable_records")
        return out
    if len(out["population"]) < 2:
        return out
    states = look.get("states")
    if states is None:
        states = homes_population_states(out["population"])
    for state in states:
        if state["ok"] or state["reason"] in MULTI_FLEET_ARMING_UNKNOWN_REASONS:
            out["counted"].append(state["home"])
        else:
            out["skipped_not_initialized"].append(state["home"])
    if len(out["counted"]) >= 2:
        out.update(armed=True, reason="population_at_least_two")
    return out


def homes_population_states(population) -> list:
    """Return one {home, ok, reason} read_registry_at snapshot per home, in order.
    Lookup consumers share this census rather than repeat cross-home reads.
    """
    states = []
    for ident in population:
        ok, reason, _data = read_registry_at(ident)
        states.append({"home": ident, "ok": ok, "reason": reason})
    return states


def _refuse_wrong_home_destructive(command, res, arming) -> str:
    """Require --fleet-home for an armed destructive invocation resolved via env/legacy.
    Confirmation alone does not name a home. Embed the homes view and name the flag
    without manufacturing a paste-ready command that chooses a home.
    """
    counted = "\n".join(f"    {h}" for h in arming["counted"])
    why = {"list_unreadable":
           "the homes list exists and could not be read, so this machine's "
           "fleet population is unknown",
           "list_has_unparseable_records":
           "the homes list carries a record nothing can parse, so this "
           "machine's fleet population is unknown",
           "population_at_least_two":
           f"this machine runs {len(arming['counted'])} fleets"}.get(
               arming["reason"], "this machine's fleet population is unknown")
    body = (f"`{command}` destroys evidence or sessions and nothing recovers "
            f"it, {why}, and no `--fleet-home` and no session membership "
            f"chose this home:\n"
            f"{resolution_provenance(res)}\n")
    if counted:
        body += f"Homes counted:\n{counted}\n"
    return (body + f"Name the home you mean with `--fleet-home <PATH>`.\n\n"
                   f"{render_homes_view()}")


def _apply_wrong_home_guard(args, command, res) -> None:
    """Guard env/legacy resolution when multi-fleet arming applies.
    Destructive verbs require a home flag; disruptive verbs proceed with provenance;
    ordinary verbs proceed. Explicit flag and lookup-hit resolutions are exempt.
    """
    arming = multi_fleet_arming(res["lookup"])
    if not arming["armed"]:
        return
    tier = verb_effect_tier(command, args)
    if tier == "destructive":
        raise FleetCliError(
            _refuse_wrong_home_destructive(command, res, arming))
    if tier == "disruptive":
        print(resolution_provenance(res))


def _disagreement_remedy(args) -> str:
    """Render accepted remedies for an explicit-home/membership disagreement.
    Always offer dropping the home flag; mention --yes only when this verb accepts it.
    """
    head = "Refusing to act on a home the flag and the registry disagree about."
    tail = "act on the home this session belongs to."
    if hasattr(args, "yes"):
        return (f"{head} Re-run with `--yes` to act on the flag's home, or "
                f"drop `--fleet-home` to {tail}")
    return f"{head} Drop `--fleet-home` to {tail}"


def apply_resolved_home(args, flag=None) -> int:
    """Apply parsed home resolution before dispatch; return an exit code or None.
    Only explicit flag or sid lookup reassigns FLEET_HOME, preserving default-home
    monkeypatches. Machine-scope verbs bypass home lookup; mutating verbs reassert
    lookup membership under their own lock before changing state.
    """
    global FLEET_HOME
    command = getattr(args, "command", None)

    # Machine-scope remedies must precede ambiguous lookup and terminus refusals,
    # otherwise an ambiguous homes list would block its own retirement remedy.
    # Still validate and apply an explicit home flag where it has meaning.
    if command in TERMINUS_EXEMPT_VERBS:
        if flag is not None:
            FLEET_HOME = validate_named_home(flag)
        return None

    # Creation flags name their own target; a second --fleet-home would be ignored.
    # Refuse that conflicting selection rather than validate an unused home.
    exempting = machine_exempting_flags(command, args)
    if exempting:
        if flag is not None:
            raise FleetCliError(
                f"`fleet {command} {exempting[0]} <PATH>` already names the "
                f"home it acts on, so `{_GLOBAL_HOME_FLAG}` has nothing left "
                f"to name -- and it could not name this one anyway, since "
                f"`{_GLOBAL_HOME_FLAG}` validates an ALREADY-initialized home "
                f"(docs/specs/multi-fleet.md §5 step 1) and `{exempting[0]}` "
                f"creates one. Drop `{_GLOBAL_HOME_FLAG}`. Nothing was "
                f"written.")
        return None

    res = resolve_home(flag=flag)

    if res["step"] in ("flag", "lookup"):
        if res["disagreement"] is not None:
            members = res.get("disagreement_homes") or [res["disagreement"]]
            # Show every claimant: a truncated list withholds facts needed to choose a home.
            named = " and ".join(Path(h).as_posix() for h in members)
            witness = (f"[fleet] WITNESS: --fleet-home names "
                       f"{Path(res['home']).as_posix()}, but this session is a "
                       f"member of {named}.")
            if not getattr(args, "yes", False):
                raise FleetCliError(
                    f"{witness}\n{_disagreement_remedy(args)}"
                    f"\n\n{render_homes_view()}")
            print(witness)
        FLEET_HOME = Path(res["home"])
        return None

    if res["step"] is not None:
        # --- steps 3 and 4 only. §5's verb-effect guard applies to exactly the
        # homes nobody named: *"destructive via env/legacy requires the flag;
        # disruptive via env/legacy proceeds but renders its resolution
        # provenance in output; ordinary flows."* Steps 1 and 2 returned above.
        _apply_wrong_home_guard(args, command, res)
        return None

    # --- terminus (§5 step 5).
    if not _multi_fleet_population_is_live(res["lookup"]):
        return None
    if command in TERMINUS_VIEW_VERBS and not getattr(args, "repair", False):
        print(NO_HOME_LINE)
        return 0
    raise FleetCliError(_terminus_refusal(command))


_GLOBAL_HOME_FLAG = "--fleet-home"


def strip_global_fleet_home(argv: list) -> tuple:
    """Remove --fleet-home V or --fleet-home=V before argparse and return its value.
    This makes either side of the subcommand equivalent without duplicate dests
    letting subparser defaults overwrite the global flag. Stop at bare --;
    leave a trailing valueless flag for argparse. Conflicting repeated values refuse.
    Autoclean retains its direct-call option while main consumes the global spelling.
    """
    out, value, seen = [], None, False
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            out.extend(argv[i:])
            break
        found = None
        if tok == _GLOBAL_HOME_FLAG and i + 1 < len(argv):
            found, i = argv[i + 1], i + 2
        elif tok.startswith(_GLOBAL_HOME_FLAG + "="):
            found, i = tok.split("=", 1)[1], i + 1
        else:
            out.append(tok)
            i += 1
            continue
        if seen and found != value:
            raise FleetCliError(
                f"{_GLOBAL_HOME_FLAG} was given twice with different values "
                f"({value!r} and {found!r}). One invocation names one home.")
        value, seen = found, True
    return out, (value if seen else None)


def _supervisor_tier_snapshot(now=None) -> dict:
    """Project supervisor claim state using files only, without locks or probes.
    Return none for active goals without a claim, held for an active claim, released
    for clean release, and unknown for read/projection failure. These are claim
    states, not body liveness. Release removes heartbeat_at, so its missing age
    must not be interpreted as staleness.
    """
    out = {"goals_active": False, "state": "none",
           "incarnation_id": None, "heartbeat_age_seconds": None}
    try:
        out["goals_active"] = bool(supervisor_goals_active())
        claim = read_incarnation()
        if claim is None:
            return out
        out["incarnation_id"] = claim.get("incarnation_id")
        out["state"] = "released" if claim.get("state") == "released" else "held"
        if now is None:
            now = datetime.now(timezone.utc)
        try:
            out["heartbeat_age_seconds"] = (
                now - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            out["heartbeat_age_seconds"] = None
    except Exception:  # noqa: BLE001 -- a view never surfaces a traceback
        out["state"] = "unknown"
    return out


# Narrow foreign registry field types before text sanitizing. str() would turn a
# malformed object into attacker-authored status text and can cost unbounded work.
# ?type is a diagnostic word chosen by fleet.
TYPE_FAULT = "?type"
# Absent/null is a different fact from a malformed type: no value was recorded.
FIELD_UNKNOWN = "?"


def registry_status(value) -> str:
    """Return a string status, ? for absent/null, or ?type for the wrong JSON type.
    Narrow before text sanitizing: coercing foreign objects with str() would disguise
    their type as attacker-authored status text and can be expensive.
    """
    if value is None:
        return FIELD_UNKNOWN
    if isinstance(value, str):
        return value
    return TYPE_FAULT


def status_snapshot(now=None, include_archived: bool = False) -> dict:
    """Read a file-only fleet snapshot without locking, probing or mutating state.
    Project workers, numeric totals, unknown-field markers and supervisor claim state.
    Registry failures render explicit state; no session discovery occurs here.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    ok, reason, data = _read_registry_readonly()
    snap = {
        "ok": ok,
        "reason": reason,
        "generated_at": now_iso(),
        "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}},
        "workers": [],
        # The command tier lives in the claim, not in supervisor-shaped worker names.
        # Project its file-only state separately from worker rows.
        "supervisor": _supervisor_tier_snapshot(now),
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
        # Numeric totals need zero defaults; displayed cells need to disclose absent
        # measurements. Track which fields were substituted without changing totals.
        unknown_fields = []
        if _coerce_cost(rec.get("cost_usd")) is None:
            unknown_fields.append("cost_usd")
        if "turns" not in rec:
            unknown_fields.append("turns")
        try:
            stale = (now - _parse_iso(rec["last_activity"])).total_seconds()
        except (ValueError, TypeError, KeyError):
            stale = None
        # Narrow status to a hashable string before using it as a grouping key.
        status = registry_status(rec.get("status"))
        by_status[status] = by_status.get(status, 0) + 1
        total_mail += mail
        total_cost += cost
        rows.append({
            "name": name,
            "status": status,
            "turns": rec.get("turns", 0),
            "cost_usd": cost,
            "unknown_fields": unknown_fields,
            "mail": mail,
            "stale_seconds": stale,
            "limit_reset_at": rec.get("limit_reset_at"),
            "limit_kind": rec.get("limit_kind"),
            "resume_eligible": status == "limited" and _limit_reset_passed(rec),
            "attached_since": rec.get("attached_since"),
            # Expose dispatch kind from this file-only snapshot for native cost rendering.
            "dispatch_kind": rec.get("dispatch_kind"),
            "archived_at": rec.get("archived_at"),
            # Permission denials have durable outcomes: None means unmeasured, zero means
            # measured with no denial. This bounded file-only read needs no roster or lock;
            # permission stalls, in contrast, have only transient roster evidence.
            "permission_denials": _session_permission_denials(name, sid),
            # Name shape identifies a supervisor body, including released or seized bodies.
            # The separate supervisor snapshot states which body holds the claim.
            "tier": "supervisor" if _is_supervisor_shaped(name) else "worker",
        })

    snap["workers"] = rows
    snap["totals"] = {
        "workers": len(rows),
        "mail": total_mail,
        "cost_usd": round(total_cost, 6),
        "by_status": by_status,
    }
    return snap


# Shared tmux notification transport for keeper and supervisor verbs.
# The keeper imports fleet; placing the sanitizer here keeps the dependency one-way.
# Deliver only to the operator's registered fleet target (terminal-surface D7).
# Sanitize at delivery: worker-writable newlines could submit extra prompt lines,
# controls could obscure the text, and a leading dash could become a tmux option.
# Prefix first, then sanitize and bound the entire delivered line.

# Routing prefixes shared with skills/fleet/SKILL.md and both notification producers.
KEEPER_LINE_PREFIX = "KEEPER: "
SUPERVISOR_LINE_PREFIX = "SUPERVISOR: "

# Maximum delivered interface-line length, including its prefix.
INTERFACE_LINE_LIMIT = 200

# Only the CSI form is matched here; a bare ESC left by any other escape shape
# is dropped by the C0 filter in `one_line` a line later.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;:<=>?]*[ -/]*[@-~]")

#: Same wall `fleet_keeper.SUBPROCESS_TIMEOUT` uses. A wedged tmux must not
#: hang a supervisor's handoff.
TMUX_TIMEOUT_SECONDS = 30


def one_line(text, limit=INTERFACE_LINE_LIMIT):
    """Collapse `text` into one printable line of at most `limit` chars: ANSI
    stripped, `\\r\\n\\t` and the other C0 controls folded to spaces,
    whitespace collapsed, truncated with an ellipsis.

    See this section's header for why each of those is load-bearing. The body
    is `fleet_keeper._one_line`'s, moved verbatim."""
    text = _ANSI_CSI_RE.sub("", str(text))
    text = "".join(" " if ch < " " or ch == "\x7f" else ch for ch in text)
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


def interface_line(text, prefix, limit=INTERFACE_LINE_LIMIT):
    """Prefix and sanitize a complete interface line within PAGE_TEXT_LIMIT.
    The prefix prevents a leading worker-supplied dash becoming a tmux option;
    sanitizing after prefixing removes newlines and controls from the delivered line.
    """
    text = str(text)
    if not text.startswith(prefix):
        text = prefix + text
    return one_line(text, limit)


def _tmux_rc(run, argv, timeout=TMUX_TIMEOUT_SECONDS):
    """`tmux`'s exit code, or a synthetic one. `FileNotFoundError` yields the
    shell's own 127 (tmux is not installed) rather than being folded into 1
    (tmux ran and refused) -- the same split `fleet_keeper._run_text` keeps for
    `claude`, and the same reason: the two have different remedies."""
    try:
        cp = run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127
    except (OSError, subprocess.SubprocessError):
        return 1
    return cp.returncode


def tmux_command(run, out, *args, label="fleet"):
    """Run one tmux subcommand and report whether it exited zero.
    Absorb command errors and timeouts so notification failure cannot stop handoff.
    """
    argv = ["tmux", *args]
    rc = _tmux_rc(run, argv)
    if rc != 0:
        print(f"{label}: tmux failed: {argv}", file=out)
    return rc == 0


def _tmux_window_name(run, pane):
    """Return the current tmux window name for a validated pane, or None.
    Read stdout to verify registration; capture and bound the command like writes.
    """
    try:
        cp = run(["tmux", "display-message", "-p", "-t", pane,
                  "#{window_name}"], capture_output=True, text=True,
                 timeout=TMUX_TIMEOUT_SECONDS)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout.strip()


def type_interface_line(run, target, text, *, prefix, out=sys.stdout,
                        limit=INTERFACE_LINE_LIMIT, label="fleet"):
    """Submit one sanitised tmux line; return whether delivery succeeded.
    Send Enter only after the literal send succeeds, to avoid submitting an
    unrelated half-typed prompt. Callers may record delivery only on True."""
    line = interface_line(text, prefix, limit)
    if not tmux_command(run, out, "send-keys", "-t", target, "-l", line,
                        label=label):
        return False
    return tmux_command(run, out, "send-keys", "-t", target, "Enter",
                        label=label)


# Worker-settings template rendering and instance freshness (SPEC §14).

_TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")


def render_worker_settings_template(template_text: str, python_exe, fleet_home,
                                    fleet_install=None) -> str:
    """Render Python, install-root and home placeholders for `fleet init`.
    Use absolute forward-slash paths: Git Bash consumes unquoted backslashes.
    `fleet_install` defaults to `fleet_home` for a single-home installation.
    Reject unresolved placeholders before invalid settings can silently disable hooks."""
    python_path = Path(python_exe).resolve().as_posix()
    fleet_home_path = Path(fleet_home).resolve().as_posix()
    install_path = (fleet_home_path if fleet_install is None
                    else Path(fleet_install).resolve().as_posix())
    rendered = (template_text.replace("{{PYTHON}}", python_path)
                             .replace("{{FLEET_INSTALL}}", install_path)
                             .replace("{{FLEET_HOME}}", fleet_home_path))
    leftover = _TEMPLATE_PLACEHOLDER_RE.search(rendered)
    if leftover:
        raise ValueError(
            f"unrendered placeholder {leftover.group(0)!r} in worker-settings template "
            "-- only {{PYTHON}}, {{FLEET_INSTALL}} and {{FLEET_HOME}} are supported"
        )
    return rendered


def instance_freshness_info() -> dict:
    """Read template/instance existence, mtimes and instance staleness.
    An absent instance is stale. An existing instance is stale only when a
    present template is newer; a missing template cannot establish staleness."""
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


# CLI subcommands (SPEC §5).

# Continuity failures use rc 4 (claim-nonce §4.13(b)/§11).
# `sup-boot` publishes 0/2/3 (skills/fleet/SKILL.md:54); generic CLI errors use 1.
SUPERVISOR_CONTINUITY_RC = 4


class SupervisorContinuityError(FleetCliError):
    """A supervisor operation whose caller cannot prove continuity.
    Remain a FleetCliError so common handlers catch it; main() assigns the
    separate continuity exit code before its generic error handler."""


class SupervisorClaimGateError(SupervisorContinuityError):
    """A lifecycle operation refused by the supervisor claim gate.
    Inherit the continuity error's exit code and generic CLI error handling."""


class SupervisorLifecycleRefusal(FleetCliError):
    """A supervisor kill/respawn refusal with an explicit exit code.
    rc 2 means a definite refusal with an operator remedy; rc 3 freezes an
    unreadable or indeterminate claim/holder state. main() handles this before
    the generic FleetCliError arm so the distinction remains scriptable."""

    def __init__(self, message, rc=2):
        super().__init__(message)
        self.rc = rc


def _read_task_arg(task: str) -> str:
    """Resolve `@file` task syntax to file contents; otherwise return the task."""
    if task.startswith("@"):
        path = Path(task[1:])
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise FleetCliError(f"could not read task file {path}: {exc}") from exc
    return task


def _require_instance_settings() -> None:
    """Require rendered worker settings before registry mutation or dispatch.
    A missing --settings file can silently disable hooks in print mode."""
    if not instance_settings_path().exists():
        raise FleetCliError(
            f"worker settings instance missing ({instance_settings_path()}) -- run `fleet init` first"
        )


# Retry longer than an ordinary lock attempt: dispatch has already launched a
# billable session, and a failed commit must not strand its recovery identity.
# Six attempts sleep for 23s total, plus each lock-acquisition timeout.
LAUNCH_COMMIT_MAX_ATTEMPTS = 6
LAUNCH_COMMIT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0, 8.0, 7.0)


def _commit_launched_turn(commit_fn, sleep=time.sleep) -> bool:
    """Retry a post-dispatch registry commit on lock timeout or OSError.
    Return False on exhaustion; callers must report the already-launched sid
    with `_report_stranded_native_turn` so an operator does not double-dispatch.
    The callable owns its lock and must be safely retryable before atomic save.
    After save, event appends and mailbox migration must swallow I/O failures:
    retrying a durable, non-idempotent commit would apply it twice."""
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
    """Print recovery ids and append a best-effort event for a launched turn
    whose registry commit failed. Never raise: an ordinary launch-failure
    exception would invite a retry while the original session is still running."""
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
    """Read a valid `fleet_short_id=<id>` recovery note, or return None."""
    for note in getattr(exc, "__notes__", None) or ():
        if isinstance(note, str) and note.startswith("fleet_short_id="):
            return note.partition("=")[2] or None
    return None


def _stash_short_id_note(exc: BaseException, short_id: str) -> None:
    """Attach the dispatch recovery id without replacing the escaping exception.
    Populate __notes__ directly on Python 3.10, where add_note is unavailable.
    Diagnostic failures must never obscure the original exception or interrupt."""
    note = f"fleet_short_id={short_id}"
    try:
        adder = getattr(exc, "add_note", None)
        if adder is not None:
            adder(note)
            return
        notes = getattr(exc, "__notes__", None)
        if not isinstance(notes, list):
            notes = []
            exc.__notes__ = notes
        notes.append(note)
    except Exception:
        pass


def statusline_chain_path() -> Path:
    """Machine-scoped statusline delegates beside user_settings_path().
    Delegates run shell commands, so an unauthenticated resolved fleet home
    must never choose this file. Deriving it from the settings path also keeps
    the path inside the same sandbox as the settings entry being composed."""
    return user_settings_path().with_name("fleet-statusline-chain.json")


def _capture_statusline_delegate(command: str) -> None:
    """Record an incumbent statusline command for composition above fleet's row.
    Claude Code has one statusLine entry, so both displays share that command."""
    path = statusline_chain_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"delegates": [{"command": command, "captured_at": now_iso()}]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# Destructive acknowledgement (§5.1): Claude callers need --yes for foreign
# or unknown owners; proven ownership and human shells are exempt.
# Interrupt preserves the worker/transcript and does not require this guard.

class DestructiveActionRefused(FleetCliError):
    """A destructive action against a foreign worker lacks acknowledgement."""


def _worker_is_foreign(record: dict, caller: str | None, claim_lineage=None) -> bool:
    """Whether neither the caller sid nor its proven claim lineage owns this worker.
    Unknown ownership is foreign. An unproven caller cannot acquire ownership
    by reading a lineage field; absent caller/owner values never match."""
    owner = record.get("spawned_by")
    if owner and owner == caller:
        return False
    lin = record.get("spawned_by_lineage")
    if claim_lineage and lin and lin == claim_lineage:
        return False
    return True


def _describe_owner(record: dict) -> str:
    owner = record.get("spawned_by")
    lin = record.get("spawned_by_lineage")
    if not owner:
        base = "unknown owner (spawned before provenance was recorded, or by a human shell)"
        return f"{base}, lineage {lin}" if lin else base
    return f"session {owner[:8]}" + (f", lineage {lin}" if lin else "")


def _confirm_destructive(action: str, names: list, records: dict, assume_yes: bool,
                         nonce=None) -> None:
    """Require --yes for a Claude session destroying another owner's worker.
    Human shells without a caller sid are exempt. Agents have no usable prompt
    stdin, and Windows isatty cannot distinguish NUL from an interactive device.
    This is an acknowledgement guard, not authorization: sessions share an OS
    user and can alter the environment used to identify the caller."""
    caller = current_caller_session()
    if caller is None:
        return
    # Proven claim lineage preserves ownership across sid rotation. Missing or
    # invalid continuity proof leaves only the spawned_by comparison.
    claim_lineage = _caller_proven_lineage(caller, nonce)
    foreign = [n for n in names
               if _worker_is_foreign(records.get(n, {}), caller, claim_lineage)]
    if not foreign or assume_yes:
        return

    detail = ", ".join(f"{n} ({_describe_owner(records.get(n, {}))})" for n in foreign)
    raise DestructiveActionRefused(
        f"refusing to {action} {len(foreign)} worker(s) this session did not spawn: {detail}. "
        f"Re-run with --yes to confirm. (A worker you spawned needs no confirmation.)"
    )


def _install_statusline(force: bool = False, chain: bool = False) -> None:
    """Back up user settings and merge fleet's statusLine entry.
    Refuse a foreign incumbent unless force replaces it or chain captures it
    at statusline_chain_path() for composition above fleet's row."""
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
        # A shell runs this: forward slashes, and QUOTED -- a spaced path splits.
        "command": f'"{Path(sys.executable).resolve().as_posix()}" "{script}"',
        "refreshInterval": 10,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"fleet init: installed statusLine into {path}")
    print("  restart Claude Code to see it")


def cmd_home(args) -> int:
    """Print the resolved fleet home, or its statusline tag with --tag.
    Bare output is one path for shell substitution. Tags use raw FLEET_HOME,
    matching home_identity and the statusline even when resolution differs."""
    if getattr(args, "tag", False):
        print(home_tag(FLEET_HOME))
        return 0
    print(Path(FLEET_HOME).resolve().as_posix())
    return 0


def _write_text_tolerating_console_encoding(text: str) -> None:
    """Write Unicode text to stdout, preferring UTF-8.
    Fall back to backslash escapes on consoles whose encoding lacks the glyphs."""
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


def render_homes_view() -> str:
    """Render fleet homes as a string that refusals can embed.
    This view takes no lock, probes nothing and writes nothing. Render an
    unreadable list distinctly from an empty one: absence is not evidence."""
    pop = homes_population()
    out = [f"fleet homes: {pop['path']}"]
    if pop["reason"] == "unreadable":
        out.append("  list unreadable -- population unknown")
    elif not pop["homes"]:
        out.append("  (no homes listed -- this machine runs a single fleet)")
    else:
        width = max(len(h["path"]) for h in pop["homes"])
        # Pair each statusline tag with its path so the nameplate is identifiable.
        tags = [home_tag(h["path"]) for h in pop["homes"]]
        for entry, tag in zip(pop["homes"], tags):
            if entry["ok"]:
                n = entry["workers"]
                state = f"ok ({n} worker{'' if n == 1 else 's'})"
            else:
                state = {"not_initialized": "not initialized"}.get(
                    entry["reason"], entry["reason"])
            out.append(f"  {tag}  {entry['path']:<{width}}  {state}")
        # Report collisions: a shared four-digit tag cannot distinguish two homes.
        clash = sorted({t for t in tags if tags.count(t) > 1})
        if clash:
            out.append(
                f"  note: {len(clash)} tag(s) shared by two or more homes "
                f"({', '.join(clash)}) -- those homes render the same "
                f"statusline nameplate and cannot be told apart in the bar")
    if pop["retired"]:
        out.append(f"  ({len(pop['retired'])} retired)")
    if pop["invalid_lines"]:
        out.append(f"  note: {pop['invalid_lines']} unparseable line(s) skipped")
    if pop["decode_note"]:
        out.append(f"  note: {pop['decode_note']}")
    return "\n".join(out) + "\n"


def cmd_homes(args) -> int:
    """View the machine's home list, append a home, or append a retirement.
    Add requires an existing initialized directory; retire requires only valid
    path grammar, since a deleted or moved home must remain retireable.
    Validation never creates directories. Read add/retire independently so
    an empty argument refuses instead of silently selecting the view arm."""
    add, retire_arg = getattr(args, "add", None), getattr(args, "retire", None)
    if add is None and retire_arg is None:
        print(render_homes_view(), end="")
        return 0

    retire = retire_arg is not None
    target = retire_arg if retire else add
    if not str(target).strip():
        raise FleetCliError(
            f"`fleet homes --{'retire' if retire else 'add'}` takes a home "
            f"path and was given an empty value. Nothing was appended -- the "
            f"list is append-only, so a record written by accident is permanent.")
    ident = home_identity(target)
    if not homes_path_is_absolute(ident) or _has_parent_segment(ident):
        raise FleetCliError(
            f"not an absolute home path: {str(target)!r}. The homes list takes "
            f"a drive-letter (`C:\\fleet`), UNC (`\\\\server\\share\\fleet`) or "
            f"POSIX (`/srv/fleet`) absolute path with no `..` segment.")

    listed = read_homes_list()
    if listed["reason"] == "unreadable":
        raise FleetCliError(
            f"cannot read {listed['path']} -- refusing to append to a list "
            f"whose current membership is unknown. Fix the file's readability "
            f"first; the list is append-only, so nothing has been lost.")
    member = ident in listed["members"]

    if retire:
        if not member:
            print(f"fleet homes: {ident} is not listed -- nothing to retire")
            return 0
        append_home_record(ident, retire=True)
        print(f"fleet homes: retired {ident}")
        return 0

    if member:
        print(f"fleet homes: {ident} is already listed")
        return 0
    path = Path(ident)
    if not path.is_dir():
        raise FleetCliError(
            f"not a directory: {ident} -- `fleet homes --add` lists an existing "
            f"fleet home and never creates one.")
    if not home_is_initialized(path):
        ok, reason, _ = read_registry_at(path)
        raise FleetCliError(
            f"{ident} is not initialized ({reason}) -- an initialized home is "
            f"one whose `state/fleet.json` exists and parses "
            f"(docs/specs/multi-fleet.md, Definitions). A home the reader would "
            f"drop must not become a permanent record in an append-only list.")
    append_home_record(ident)
    print(f"fleet homes: added {ident}")
    return 0


def cmd_knowledge(args) -> int:
    """Print knowledge/INDEX.md without requiring shell-specific path expansion."""
    path = knowledge_dir() / "INDEX.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        print(f"(no knowledge index at {path} -- run `fleet init`)")
        return 0
    _write_text_tolerating_console_encoding(text)
    return 0


# Home creation keeps file writes separate from machine-list append operations.
# The homes-list lint bans rewrites in scopes naming list symbols, so
# _write_new_home_state writes files, _record_home_on_this_machine appends,
# and _init_named_home composes the two without writing itself.


def _home_to_create(text) -> Path:
    """Resolve and validate an existing directory for home creation.
    Do not require initialization: creating its registry is this verb's job.
    Do not create a directory during validation, which could legitimize a typo.
    Resolve relative input before appending a permanent machine-list identity."""
    raw = "" if text is None else str(text)
    if not raw.strip():
        raise FleetCliError(
            "`fleet init --home` takes a path and was given an empty value. "
            "Nothing was created and nothing was appended -- the homes list is "
            "append-only, so a record written by accident is permanent.")
    try:
        home = Path(raw).resolve()
    except (OSError, ValueError) as exc:
        raise FleetCliError(f"--home: cannot resolve {raw!r} ({exc})")
    ident = home_identity(home)
    if not homes_path_is_absolute(ident) or _has_parent_segment(ident):
        raise FleetCliError(
            f"not an absolute home path: {ident!r} (from {raw!r}). The homes "
            f"list takes a drive-letter (`C:\\fleet`), UNC "
            f"(`\\\\server\\share\\fleet`) or POSIX (`/srv/fleet`) "
            f"absolute path with no `..` segment.")
    if not home.is_dir():
        # The two shapes get different advice, because `mkdir -p` is the remedy
        # for exactly one of them: a path that already exists as a FILE is not
        # a typo the operator can fix by creating a directory over it.
        remedy = (f"It exists but is not a directory. "
                  if home.exists() else
                  f"Create it first (`mkdir -p {home}`) and re-run.")
        raise FleetCliError(
            f"--home does not exist or is not a directory: {home} (from "
            f"{raw!r}). Nothing was created -- `fleet init --home` initialises "
            f"a directory you have already made, so a typo cannot leave a "
            f"plausible-looking home behind. {remedy}")
    return home


def _write_new_home_state(target: Path, template_text: str) -> bool:
    """Create the target's registry and render its worker settings.
    Return whether this call created the registry. Preserve existing registries;
    refuse corrupt/unreadable ones so creation cannot destroy incident evidence.
    Settings are regenerated with target as HOME and INSTALL_ROOT as code root.
    Keep machine-list operations outside this file-writing scope."""
    (target / "state").mkdir(parents=True, exist_ok=True)
    registry = registry_path_at(target)
    created = False
    if registry.exists():
        ok, reason, _data = read_registry_at(target)
        if not ok:
            raise FleetCliError(
                f"{target} already has a `state/fleet.json` and it is "
                f"{reason} -- refusing to overwrite it. That file is this "
                f"home's roster and the only record of whatever happened to "
                f"it; `fleet --fleet-home {Path(target).as_posix()} doctor` "
                f"reports it, and `doctor --repair` is the verb that renames "
                f"it aside. Nothing was created and nothing was appended.")
    else:
        d = registry.parent
        fd, tmp_name = tempfile.mkstemp(dir=str(d), prefix=".fleet.",
                                        suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"workers": {}}, f, indent=2)
                f.write("\n")
            _replace_with_retry(tmp_name, str(registry))
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        created = True

    rendered = render_worker_settings_template(
        template_text, sys.executable, target, fleet_install=INSTALL_ROOT)
    (target / "state" / "worker-settings.json").write_text(
        rendered, encoding="utf-8")
    ensure_interface_state(target)
    return created


def _record_home_on_this_machine(target: Path) -> tuple:
    """Append an initialized target to the machine list unless already present.
    Return (identity, appended). Refuse unreadable membership: the list is
    append-only, so an uncertain append can leave an irreversible duplicate."""
    ident = home_identity(target)
    listed = read_homes_list()
    if listed["reason"] == "unreadable":
        raise FleetCliError(
            f"cannot read {listed['path']} -- the home at {ident} was created, "
            f"but refusing to append to a list whose current membership is "
            f"unknown. Fix the file's readability and run `fleet homes --add "
            f"{ident}`; the list is append-only, so nothing has been lost.")
    if ident in listed["members"]:
        return ident, False
    append_home_record(ident)
    return ident, True


def _init_named_home(args, *, local_home=None) -> int:
    """Create a home; register it only for explicit --home.
    Initialize and verify on disk before appending to the machine list, so a
    creation failure cannot leave a permanent record the list reader ignores.
    `local_home` is main()'s bare-init default, not a home-resolver result."""
    if getattr(args, "statusline", False):
        raise FleetCliError(
            "`--statusline` and `--home` do not compose, and nothing was "
            "written. The statusline is ONE machine-global setting "
            "(`~/.claude/settings.json`) while `--home` creates one home among "
            "many, and `--chain` captures the incumbent into `state/` of the "
            "home §5 RESOLVED -- not the one you just named -- so the pair "
            "would write two different homes from one invocation. Run "
            "`fleet init --home <PATH>` first, then `fleet init --statusline` "
            "on its own.")

    target = _home_to_create(args.home if local_home is None else local_home)

    template_path = template_settings_path()
    if not template_path.exists():
        raise FleetCliError(
            f"worker-settings template not found: {template_path} -- expected it at the "
            f"fleet INSTALL root (it is git-tracked source, not per-home state). "
            f"Nothing was created and nothing was appended."
        )
    created = _write_new_home_state(target, template_path.read_text(encoding="utf-8"))

    if not home_is_initialized(target):
        reason = read_registry_at(target)[1]
        raise FleetCliError(
            f"{target} is still not initialized ({reason}) after writing its "
            f"registry -- refusing to append it to the machine's homes list, "
            f"which §4's reader would drop. Nothing was appended.")

    if local_home is None:
        ident, appended = _record_home_on_this_machine(target)

    if local_home is not None:
        try:
            cmd_interface_register(SimpleNamespace(), home=target)
        except FleetCliError as exc:
            # A shell outside tmux and outside Claude has no caller identity.
            # Keep bare init useful there, but never hide a malformed tmux
            # registration or a failed tmux operation.
            if "CLAUDE_CODE_SESSION_ID is unset" not in str(exc):
                raise
            print("  interface:  UNMEASURED (no tmux pane or session id)")
        print("  startup ritual:")
        print(f"    board:     {interface_board_path(target).as_posix()}")
        print(f"    sup-status: {_interface_supervisor_state(target)}")
        inbox = target / "state" / "inbox"
        try:
            inbox_count = sum(1 for path in inbox.iterdir() if path.is_file())
        except FileNotFoundError:
            inbox_count = 0
        except OSError:
            inbox_count = "UNMEASURED"
        print(f"    inbox:     {inbox_count}")
        print(f"    rulings:   {_interface_pending_rulings(target)}")
        refresh_interface_board(target)

    # Keep `home` between interpolations: an adjacent interpreter/path-shaped
    # pair is parsed as a rendered command by the command-quoting census.
    state = "initialized" if created else "already initialized"
    print(f"fleet init: {state} home {Path(target).resolve().as_posix()}")
    print(f"  registry:    {registry_path_at(target).as_posix()}")
    print(f"  settings:    {(target / 'state' / 'worker-settings.json').as_posix()}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    if local_home is None:
        print(f"  homes list:  {homes_list_path()} "
              f"({'appended' if appended else 'already listed'}: {ident})")
        if appended:
            print("  note:        that append is permanent -- the list is "
                  "append-only and only `fleet homes --retire` folds it out.")
    else:
        print("  registration: unchanged -- use `fleet homes --add <PATH>` "
              "to register this home on the machine.")
    return 0


def cmd_init(args, *, create_in=None) -> int:
    """Create a cwd home by default; explicit --home also registers it.
    `main` supplies create_in before home resolution. Explicit --fleet-home and
    statusline setup render in the resolved home. Preserve existing registries,
    refuse corrupt registries, and regenerate settings using sys.executable.
    Bare init writes only in cwd; --statusline installs the machine statusline.
    The §7 continuity gate reads the home being initialized, so another home's
    claim cannot block this home's creation."""
    global FLEET_HOME
    # Gate the creation target before home resolution. Restore the module global
    # immediately so another main() call cannot inherit this command's target.
    gate_home = FLEET_HOME
    if getattr(args, "home", None) is not None or create_in is not None:
        gate_home = _home_to_create(args.home if create_in is None else create_in)
    previous_home = FLEET_HOME
    FLEET_HOME = gate_home
    try:
        _supervisor_gate("init", nonce=getattr(args, "nonce", None))
    finally:
        FLEET_HOME = previous_home
    # Handle --home before resolved-home writes: only the creation target's claim
    # may refuse it; another home's claim is irrelevant.
    if getattr(args, "home", None) is not None or create_in is not None:
        return _init_named_home(args, local_home=create_in)
    template_path = template_settings_path()
    if not template_path.exists():
        raise FleetCliError(
            f"worker-settings template not found: {template_path} -- expected it at the "
            f"fleet INSTALL root (it is git-tracked source, not per-home state)"
        )
    template_text = template_path.read_text(encoding="utf-8")
    # Hook scripts come from the install root; state paths use the target home.
    rendered = render_worker_settings_template(
        template_text, sys.executable, FLEET_HOME, fleet_install=INSTALL_ROOT)

    instance_path = instance_settings_path()
    instance_path.parent.mkdir(parents=True, exist_ok=True)
    instance_path.write_text(rendered, encoding="utf-8")
    ensure_interface_state(FLEET_HOME)

    print(f"fleet init: wrote {instance_path}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    print(f"  fleet home:  {Path(FLEET_HOME).resolve().as_posix()}")

    if getattr(args, "statusline", False):
        _install_statusline(force=getattr(args, "force", False),
                            chain=getattr(args, "chain", False))
    return 0


def cmd_spawn(args, run=subprocess.run, which=shutil.which, sleep=time.sleep,
              clock=time.monotonic) -> int:
    """Dispatch a native worker after settings validation and prompt composition.
    Pre-claim session_id=None under fleet_lock, dispatch outside it, then commit
    the joined sid with retries. A matching fast completion can establish an
    idle result even when roster join expires. Roll back only our own pre-claim.
    If an already-launched turn cannot commit, retain its recovery record, print
    its sid/short id and return nonzero rather than invite a second dispatch.
    Events accompany registry mutations under the same lock. The sid-keyed token
    ceiling can be written only after join; native dispatch rejects USD budgets.
    The injectable clock bounds roster join without real waits in tests."""
    _supervisor_gate("spawn", nonce=getattr(args, "nonce", None))
    _ceiling_refusal = _ceiling_refuses_dispatch("spawn")
    if _ceiling_refusal is not None:
        raise FleetCliError(_ceiling_refusal)
    _require_instance_settings()

    cwd = Path(args.dir)
    if not cwd.is_dir():
        raise FleetCliError(f"--dir does not exist or is not a directory: {args.dir}")

    # Warn at dispatch about hard denials, which may leave a worker waiting for
    # permission. This is advisory: a valid restricted task must remain launchable,
    # and arbitrary task prose cannot reliably determine which commands it needs.
    deny_rules = _worktree_deny_rules(cwd)
    if deny_rules:
        print(f"note: {Path(cwd) / '.claude' / 'settings.local.json'} denies "
              f"{', '.join(deny_rules)} -- a deny beats mode {args.mode!r}, so if "
              f"this task needs one of them the worker will HANG, not error "
              f"(`fleet doctor` names the stall; `fleet status` flags it)")

    if getattr(args, "max_budget_usd", None) is not None:
        raise FleetCliError(
            "no USD budget under native dispatch (contract G3) -- use --token-ceiling"
        )

    task = _read_task_arg(args.task)

    # Compose before pre-claiming so context/index I/O cannot leave a phantom
    # working record. Report ordinary compose failures, but preserve Ctrl-C:
    # there is no registry claim to roll back yet.
    try:
        prompt, _claim, _mail = compose_prompt(args.name, cwd, task, None,
                                        context=fleet_index.parse_context_arg(
                                            getattr(args, "context", None)))
    except FleetCliError:
        raise
    except Exception as exc:
        raise FleetCliError(
            f"{args.name}: could not compose the spawn prompt -- {exc} "
            f"({type(exc).__name__}); nothing was registered") from exc
    # Reject a prompt missing its brief before any registry write.
    assert_brief_carried(args.name, task, prompt)

    with fleet_lock():
        data = load_registry()
        validate_name(args.name, existing=data["workers"].keys())
        _spawner = current_caller_session()
        record = new_worker_record(
            None, cwd, task, args.mode, model=args.model,
            setting_sources=args.setting_sources, token_ceiling=args.token_ceiling,
            spawned_by=_spawner,
            # Stamp proven lineage under the lock to preserve ownership across sid rotation.
            spawned_by_lineage=_spawning_claim_lineage(_spawner),
            dispatch_kind="bg", category=args.category)
        record["last_dispatch_at"] = now_iso()
        data["workers"][args.name] = record
        save_registry(data)
        append_event("spawned", args.name, cwd=str(cwd), mode=args.mode)

    pre_claim_at = record["last_dispatch_at"]

    # No sid exists yet, so composition claims no mailbox and needs no restore.
    # Context digests are spawn-only; resumed turns do not repay the same digest.

    try:
        # Store the full brief once, inside the rollback envelope: an I/O failure
        # after pre-claim must not leave a worker that never launched.
        write_brief(args.name, task)
        result = dispatch_bg(
            args.name, cwd, prompt, args.mode, model=args.model,
            category=args.category, hint=task,
            setting_sources=record.get("setting_sources"),
            run=run, which=which, sleep=sleep, clock=clock,
        )
    except NativeDispatchError as exc:
        # The exception's short id finds sid-keyed fast-completion outcomes.
        # A newly created record has no retired sids to exclude. The helper's short-id
        # and freshness filters reject stale evidence left by best-effort cleanup.
        fast_sid = _fast_completion_sid(args.name, pre_claim_at,
                                        short_id=getattr(exc, "short_id", None))
        if fast_sid is not None:
            with fleet_lock():
                data = load_registry()
                rec = data["workers"].get(args.name)
                if rec is not None and rec.get("session_id") is None:
                    rec["session_id"] = fast_sid
                    # Derived fallback id: dispatch raised before its CLI short id was captured.
                    rec["native_short_id"] = fast_sid.partition("-")[0] or fast_sid[:8]
                    rec["status"] = "idle"
                    rec["turns"] = 1
                    rec["last_activity"] = now_iso()
                    save_registry(data)
                    # Post-save event failures must not report a durable completion as failed.
                    _append_event_quiet("turn_started", args.name, session_id=fast_sid)
            _write_ceiling_file(fast_sid, record.get("token_ceiling"))
            print(f"{args.name} {fast_sid} (native bg, fast completion before join)")
            return 0

        # Pop only our still-sid-less pre-claim; concurrent commits must survive.
        # Emit spawn_failed only when that rollback actually removed the record.
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(args.name)
            if rec is not None and rec.get("session_id") is None:
                data["workers"].pop(args.name, None)
                save_registry(data)
                append_event("spawn_failed", args.name, error=str(exc))
        raise FleetCliError(f"{args.name}: native spawn failed -- {exc}") from exc
    except BaseException as exc:
        # Roll back our sid-less pre-claim on any escaping dispatch exception, then
        # re-raise it unchanged. Preserve the exception's short-id note in the failure
        # event so an already-started session remains recoverable after Ctrl-C.
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
            # Emit the event only alongside an actual record mutation.
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

    # The sid-keyed ceiling can only be written after the roster join.
    _write_ceiling_file(sid, record.get("token_ceiling"))

    # Show effective model/config at launch so inherited dispatch settings are visible.
    model_line = f"model: {args.model or '(claude default)'}"
    subagent_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if subagent_model:
        model_line += f"; CLAUDE_CODE_SUBAGENT_MODEL={subagent_model}"
    print(model_line)

    print(f"{args.name} {sid} (native bg, short id {short_id})")
    return 0


_HOOK_ERROR_TAIL = 5  # doctor/status: how many trailing hook-error lines to show


def _hook_error_lines() -> list:
    """Read nonblank hook-error log lines, or [] when absent or unreadable."""
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
    """Recompute worker state, conditionally persist transitions and print a table.
    Read the snapshot without repair, probe outside the lock, then merge under
    fleet_lock only when the record still equals its pre-probe snapshot.
    Concurrent writes win over stale verdicts. --stale-ok reads committed state."""
    # --stale-ok reads committed state without probes, locks or writes.
    # Named queries include tombstones; default bulk listings hide them.
    if args.name is not None:
        args.name = _resolve_worker_target(args.name)
    include_archived = getattr(args, "all", False) or args.name is not None
    if getattr(args, "stale_ok", False):
        snap = status_snapshot(include_archived=include_archived)
        if getattr(args, "json", False):
            print(json.dumps(snap, indent=2))
        else:
            _print_snapshot_table(snap, args.name)
        return 0

    # D4: read the pre-probe snapshot without repair or lock; a corrupt registry
    # must refuse before any merge could quarantine it. The ordinary status verb
    # still probes and persists; --stale-ok is the file-only view.
    data = read_registry_no_repair()
    requested = [args.name] if args.name else sorted(data["workers"])
    for n in requested:
        if n not in data["workers"]:
            raise FleetCliError(f"unknown worker: {n!r}")
    before_all = {n: data["workers"][n] for n in requested}
    all_workers = data["workers"]  # snapshot for the epoch check (G9)

    names = [n for n in requested if include_archived or not before_all[n].get("archived_at")]
    before = before_all

    # Archived evidence has moved; recomputing against its absence could invent
    # dead-suspected/limited state. Preserve the committed tombstone.
    active_names = [n for n in names if not before[n].get("archived_at")]

    # Share one roster fetch outside the lock, only when a live worker needs probing.
    roster_entries = []
    epoch_frozen = False
    if active_names:
        roster_ok, payload = _fetch_agents_roster()
        roster_entries = payload if roster_ok else []
        epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, all_workers)

    # Recompute every named worker without holding the lock.
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
                # Concurrent mutations win over the stale probe snapshot. Display the current
                # record, falling back to the snapshot only if the name vanished.
                display[n] = current if current is not None else before[n]
                continue
            # waiting_for_permission is transient roster evidence, never registry state.
            # Strip it for comparison/save but retain it in display for the warning flag.
            persisted_after = dict(after[n])
            persisted_after.pop("waiting_for_permission", None)
            if persisted_after != current:
                data["workers"][n] = persisted_after
                changed = True
                # Treat missing status as None so malformed records cannot abort the whole table.
                if persisted_after.get("status") != current.get("status"):
                    append_event("status_changed", n, old=current.get("status"),
                                 new=persisted_after.get("status"))
                    # Emit limited/dead-suspected events only on transitions, never on every rerun.
                    if persisted_after.get("status") == "limited":
                        append_event("limited_suspected", n,
                                    limit_reset_at=persisted_after.get("limit_reset_at"),
                                    limit_kind=persisted_after.get("limit_kind"))
                    elif persisted_after.get("status") == "dead-suspected":
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
        # Repeat permission waits below the table so a blocked working turn is visible.
        # Reuse this probe's roster/display; file-only views cannot see the transient
        # flag. Keep the warning out of --json stdout, whose consumers parse it.
        for stall in _permission_stalls(display, roster_entries):
            print(f"permission-stall: {_permission_stall_line(*stall)}")
    # Surface nonzero swallowed hook-error totals; doctor provides the tail.
    n_hook_errors = _hook_error_count()
    if n_hook_errors:
        print(f"hook-errors: {n_hook_errors} swallowed hook error(s) logged (run `fleet doctor` for the tail)")
    return 0


def _print_snapshot_table(snap: dict, name=None) -> None:
    """Print committed worker state with its age, without asserting fresh liveness."""
    if not snap["ok"]:
        if snap["reason"] == "quarantined":
            # Named, not merely flagged: the artifact IS the roster, and the
            # operator cannot restore a file whose name they were never told.
            art = _quarantine_artifacts()
            where = f"state/{art[-1].name}" if art else "state/fleet.json.corrupt.<ts>"
            print(f"fleet: registry quarantined -- {where}. Restore what it "
                  f"holds, then remove it; until then this fleet tracks nothing")
        elif snap["reason"] == "not_initialized":
            print("fleet: not initialized")
        else:
            print("fleet: registry unreadable")
        return
    rows = [w for w in snap["workers"] if name is None or w.get("name") == name]
    if name is not None and not rows:
        raise FleetCliError(f"unknown worker: {name!r}")
    print(f"{'NAME':<20} {'STATUS':<12}{'TURNS':>6}{'COST':>9}{'AGE':>9}{'MAIL':>6}  FLAGS")
    for w in rows:
        # Tolerate malformed cells so one damaged record cannot hide every healthy row.
        stale = w.get("stale_seconds")
        age = UNKNOWN_CELL if not isinstance(stale, (int, float)) or isinstance(stale, bool) \
            else f"{stale / 60:.0f}m"
        flags = []
        if w.get("status") == "idle" and w.get("mail"):
            flags.append("idle+mail")
        if w.get("resume_eligible"):
            flags.append("resume-eligible")
        if w.get("archived_at"):
            flags.append("archived")
        # Show nonzero recorded denial counts; the count makes no claim about a rule.
        denied = w.get("permission_denials")
        if isinstance(denied, int) and not isinstance(denied, bool) and denied > 0:
            flags.append(f"permission-denied:{denied}")
        # Native USD cost is unavailable; dispatch_kind comes from this file-only row.
        # Render substitute unknown_fields as ? rather than present them as measured.
        unknown = set(w.get("unknown_fields") or ())
        if w.get("dispatch_kind") == "bg":
            cost_s = f"{'-':>9}"
        elif "cost_usd" in unknown:
            cost_s = f"{UNKNOWN_CELL:>9}"
        else:
            cost_s = _cost_cell(w.get("cost_usd"))
        turns_s = (f"{UNKNOWN_CELL:>6}" if "turns" in unknown
                   else _int_cell(w.get("turns"), 6))
        # A name at or past the column width must never swallow the separator.
        print(
            f"{_text_cell(w.get('name'), 20)} {_text_cell(w.get('status'), 12)}"
            f"{turns_s}{cost_s}"
            f"{age:>9}{_int_cell(w.get('mail'), 6)}  {','.join(flags) or '-'}"
        )
    print("(stale-ok: last-committed state, not probed)")


def _native_token_summary(name: str, rec: dict) -> str:
    """Format the current sid outcome token counts, or empty text if unavailable."""
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
        # An absent session_id means no mailbox.
        sid = rec.get("session_id")
        mail = _pending_mail_count(sid) if isinstance(sid, str) and sid else 0
        attach_age = _attach_age_seconds(rec)
        attach_s = f"{attach_age / 3600:.1f}h" if attach_age is not None else "-"
        flag_list = _worker_flags(rec)
        if is_native(rec):
            # Native dispatch has no USD cost signal; render a dash.
            cost_s = f"{'-':>9}"
            tok = _native_token_summary(n, rec)
            if tok:
                flag_list = flag_list + [tok]
            # Use the same bounded denial counter in committed and probed tables.
            denied = _session_permission_denials(n, rec.get("session_id"))
            if isinstance(denied, int) and denied > 0:
                flag_list = flag_list + [f"permission-denied:{denied}"]
        else:
            cost_s = _cost_cell(rec.get("cost_usd"))
        flags = ",".join(flag_list) or "-"
        # Render unknown cells as ? and keep rendering the remaining workers.
        print(
            f"{n:<20}{_text_cell(rec.get('status'), 10)}"
            f"{_int_cell(rec.get('turns'), 6)}{cost_s}"
            f"{mins_s:>9}{mail:>6}{attach_s:>9}  {flags}"
        )


def _render_native_peek_lines(rec: dict) -> list:
    """Render one substantive transcript record as compact text/tool/user lines.
    Bound assistant text to 200 characters and user text to 120; distinguish
    synthetic user messages with user:meta. Unknown record types render no lines."""
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
    """Render the last n substantive records from a bounded current-sid transcript tail.
    Skip malformed records. Missing sid/transcript exits 1 with a factual hint:
    a null registry sid cannot prove whether a session has launched."""
    if sid is None:
        print(f"{name}: no session id on the registry record -- there is no "
              f"transcript to address. This does NOT mean no session is "
              f"running: the dispatch may be in flight, may have failed, or "
              f"may have produced a session whose sid was never recorded. "
              f"Confirm with `fleet status {name}` and `claude agents`.",
              file=sys.stderr)
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
    """Print a digest of recent substantive records from the native transcript."""
    args.name = _resolve_worker_target(args.name)
    # D1/D4: peek reads the sid without lock or repair, then reads its transcript.
    # Atomic registry replacement makes the snapshot consistent; corruption must
    # remain available for explicit doctor --repair.
    data = read_registry_no_repair()
    if args.name not in data["workers"]:
        raise FleetCliError(f"unknown worker: {args.name!r}")
    rec = data["workers"][args.name]

    return _cmd_peek_native(args.name, rec.get("session_id"), args.lines)


def _cmd_result_native(name: str, sid) -> int:
    """Print the current sid's latest completed result, with usage on stderr.
    Result stdout contains only result_text. Missing/null results and tombstones
    exit 1 with distinct reasons rather than report an empty successful result."""
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
    """Print the last completed turn result from the current sid outcome store."""
    args.name = _resolve_worker_target(args.name)
    # D1/D4: read the sid without lock or repair, as for peek.
    data = read_registry_no_repair()
    if args.name not in data["workers"]:
        raise FleetCliError(f"unknown worker: {args.name!r}")
    rec = data["workers"][args.name]

    return _cmd_result_native(args.name, rec.get("session_id"))


def wait_for_workers(names, mode: str = "all", timeout=None, poll_interval: float = 3.0,
                      sleep=time.sleep, clock=time.monotonic):
    """Poll fresh worker snapshots until the requested completion condition or timeout.
    Return (finished statuses, pending names). Re-read each pass to see concurrent
    respawns/interrupts. Archived records resolve using frozen committed state:
    their moved evidence cannot support recomputation."""
    deadline = None if timeout is None else clock() + timeout
    finished: dict = {}
    pending = set(names)
    while True:
        data = load_registry()
        workers = data["workers"]

        # Share one roster fetch per poll. Suspicious epochs leave workers pending;
        # archived records resolve from committed state without a roster verdict.
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
    """Wait for any/all requested workers and print final statuses.
    --any succeeds when at least one finishes even if others remain pending;
    otherwise unfinished workers at the deadline produce a timeout exit."""
    with fleet_lock():
        data = load_registry()
        for n in args.names:
            if n not in data["workers"]:
                raise FleetCliError(f"unknown worker: {n!r}")

    mode = "any" if args.any else "all"
    finished, pending = wait_for_workers(
        args.names, mode=mode, timeout=args.timeout, sleep=sleep, clock=clock,
    )

    # The persist pass fetches its own roster; display its committed verdict when
    # available, since it may differ from the earlier poll. Otherwise retain the
    # poll verdict and identify any epoch freeze explicitly.
    persisted_status: dict = {}
    epoch_frozen = False
    if finished:
        # Refresh finished native verdicts outside the lock before persisting fields
        # and transition events. Archived evidence has moved, so exclude tombstones
        # from recomputation and preserve their committed state.
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
                    # Suspicious roster: preserve this record without writing.
                    continue
                updated = recompute_worker_native(n, rec, roster_entries)
                # Never persist the transient waiting_for_permission roster flag.
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
            # Save only actual changes; waiting on archived records must preserve file bytes.
            if changed:
                save_registry(data)

    # Use the current sid result outcome, or the explicit no-result placeholder.
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
    # Explain when epoch freeze prevented persistence and output uses the poll verdict.
    if epoch_frozen:
        print("EPOCH: roster suspicious at persist -- native rows show the "
              "pre-freeze poll verdict; nothing persisted (G9)")

    if pending:
        if mode == "any" and finished:
            # --any succeeds when one worker finishes even while others remain pending.
            for n in pending:
                print(f"{n}: still working")
            return 0
        for n in pending:
            print(f"{n}: timed out (still working)")
        return 1
    return 0


# CLI steering and hybrid commands (SPEC §5, §9, §14).

def _cmd_send_native(name: str, message: str,
                     run=subprocess.run, which=shutil.which, sleep=time.sleep) -> int:
    """Queue mail for a working worker or fork-steer an idle one.
    Fetch the roster outside the lock, then re-read/recompute under a fresh lock.
    Refuse dead, interrupted, suspected-dead, limited and other unsupported states.
    For idle workers, check cumulative tokens and pre-claim working. Outside the
    lock, append mail before composing/draining it and dispatch with resume_sid.
    Commit the new sid, ceiling and steered event with retries. On failure restore
    claimed mail and roll back only a record still in this call's pre-claim state."""
    # Record caller sid on mail events for interface-fork divergence detection.
    # The claimless interface tier cannot prevent forks through continuity gating;
    # provenance permits warnings. Human shells have no sid and are ignored.
    caller_sid = current_caller_session()
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

        # A raw working record may be another sender's in-flight pre-claim, even when
        # roster recomputation disagrees. Respect it only without a fresh completion
        # and before claim expiry: a stale working label also describes normal finished
        # turns. Use the same last_dispatch_at/fallback anchors as recomputation to
        # avoid double-dispatch without permanently queueing mail to a completed sid.
        if rec.get("status") == "working" and status != "working":
            raw_sid = rec.get("session_id")
            if raw_sid is None:
                # Refuse a sid-less launch claim; mailbox/None.md would silently lose this message.
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
                append_event("mail_sent", name, sid=raw_sid, status="working",
                             caller_sid=caller_sid)
                print(f"{name}: turn running -- message queued to mailbox")
                return 0
            # Fresh completion or claim expiry removes pre-claim authority; persist the verdict.

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
            # Strip transient permission-wait evidence before saving.
            persisted = dict(after)
            persisted.pop("waiting_for_permission", None)
            data["workers"][name] = persisted
            save_registry(data)
            sid = after["session_id"]
            if sid is None:
                # Even a recomputed working record must have a real sid before mailbox delivery.
                raise FleetCliError(
                    f"{name}: dispatch in flight -- retry in a few seconds"
                )
            append_mailbox(sid, message)
            append_event("mail_sent", name, sid=sid, status=status,
                         caller_sid=caller_sid)
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

        # Enforce cumulative token ceiling; native dispatch has no USD budget signal.
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

        # Decide and pre-claim atomically. Stamp last_dispatch_at so stale outcomes
        # cannot demote an in-flight fork. Save the prior anchor for rollback; leaving
        # the failed attempt's timestamp would invalidate the real completion outcome.
        prior_last_dispatch_at = after.get("last_dispatch_at")
        after["status"] = "working"
        after["last_activity"] = now_iso()
        after["last_dispatch_at"] = now_iso()
        data["workers"][name] = after
        save_registry(data)

    # Append before draining so this message joins any earlier mail exactly once.
    append_mailbox(old_sid, message)
    append_event("mail_sent", name, sid=old_sid, status="idle",
                 caller_sid=caller_sid)
    prompt, claim, mail = compose_prompt(name, cwd, "", old_sid)
    # A resumed session must receive the message inline, not only behind a pointer.
    # Use all drained mail when it fits. Over the head-first cap, use this message
    # itself: it is at the drain's tail and must not be truncated from a reported
    # success. Empty drain also falls back to the message after mailbox read failure.
    inline = mail if (mail and len(mail) <= NATIVE_INLINE_STEER_MAX) else message
    try:
        result = dispatch_bg(
            name, cwd, prompt, mode, model=model, category=category,
            hint=message[:NATIVE_NAME_HINT_MAX], resume_sid=old_sid,
            setting_sources=setting_sources,
            inline_kind="steer", inline_body=inline,
            run=run, which=which, sleep=sleep,
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

    # Restamp only a record still carrying old_sid. A concurrent sid rotation or
    # sid-less respawn claim must not be overwritten by a late fork completion.
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
                # Migrate mail queued after the old-sid drain so it follows the newly restamped fork.
                _migrate_residual_mailbox(old_sid, new_sid)
                # Append steered only when the corresponding record mutation actually occurs.
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
    # Remove the old sid ceiling after writing its replacement; hooks use the current sid.
    try:
        ceiling_file_path(old_sid).unlink()
    except OSError:
        pass
    _reap_current_supervisor_forks(name, expected_sid=new_sid, run=run,
                                   which=which, sleep=sleep, attempts=3)
    print(f"{name}: fork-steered (new session {short_id}) -- fork carries full transcript (G2b)")
    return 0


def cmd_send(args, which=shutil.which, sleep=time.sleep, run=subprocess.run) -> int:
    """Steer a native worker: queue during a turn, fork-steer when idle.
    Require worker settings before dispatch and apply the §7 continuity gate."""
    # Resolve logical supervisor before gating, so the gate sees holder identity.
    # Resolver refusals must remain visible rather than becoming a silent gate pass.
    resolved_name = _resolve_worker_target(args.name)
    _supervisor_gate("send", nonce=getattr(args, "nonce", None),
                     send_target=resolved_name)
    _ceiling_refusal = _ceiling_refuses_dispatch("send")
    if _ceiling_refusal is not None:
        raise FleetCliError(_ceiling_refusal)
    _require_instance_settings()

    message = _read_task_arg(args.message)
    args.name = resolved_name

    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        before = dict(data["workers"][args.name])

    refuse_if_archived(args.name, before, "send")
    return _cmd_send_native(args.name, message,
                            run=run, which=which, sleep=sleep)


def _resume_one_limited_native(name: str, old_sid: str, cwd, mode, model, category,
                               setting_sources, token_ceiling,
                               run, which, sleep) -> bool:
    """Fork-steer a pre-claimed limited worker into a new sid.
    The old session remains untouched by native --resume. Drain its mailbox and
    carry the journal outside the lock; restore mail and the limited pre-claim
    on failure. On success retire old_sid, restamp ids, reset limit fields and
    write the new sid ceiling through the retryable post-launch commit."""
    journal_path = journal_file_path(name)
    prompt, claim, mail = compose_prompt(name, cwd, "", old_sid, journal_path=journal_path)
    body = ("The usage-limit reset horizon has passed. Continue the task "
            "from where you left off.\n\n" + prompt)
    try:
        result = dispatch_bg(
            name, cwd, body, mode, model=model, category=category,
            hint="resume past limit", resume_sid=old_sid,
            setting_sources=setting_sources,
            # Inline drained mail: work queued before a usage-limit park must resume too.
            # Use resume wording to continue the parked task rather than replace its scope.
            inline_kind="resume", inline_body=mail,
            run=run, which=which, sleep=sleep,
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
    # Remove the unreachable old-sid ceiling after the fork.
    try:
        ceiling_file_path(old_sid).unlink()
    except OSError:
        pass

    # Restamp only while the record still matches the pre-dispatch sid.
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
                # Migrate residual old-sid mail to the new fork.
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
    """Claim and fork-steer one still-limited worker.
    Re-check limited under the lock so concurrent sweeps cannot double-dispatch.
    Return False if it has moved on, True if launched; a vanished name refuses."""
    with fleet_lock():
        data = load_registry()
        rec = data["workers"].get(name)
        if rec is None:
            raise FleetCliError(f"unknown worker: {name!r}")
        # Recheck limited under the claiming lock; another sweep may already own the launch.
        if rec.get("status") != "limited":
            return False
        rec["status"] = "working"
        # Refresh the claim timestamp so expiry cannot reap a new launch as old.
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
    """Explicitly resume limited workers past their known reset horizons.
    Unknown/future horizons remain parked unless a named --force-now overrides.
    Views only flag eligibility; this gated verb performs the actual relaunch."""
    _supervisor_gate("resume-limited", nonce=getattr(args, "nonce", None))
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
        # Report a concurrent state change as a skip, never a nonexistent resume.
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
    """Stop a working native turn, write a tombstone and mark it interrupted.
    Only working records are interruptible; terminal/idle records no-op and other
    states refuse so limit parking and sticky statuses cannot be overwritten.
    A sid-less launch claim refuses because its dispatch may still land.
    Stop fires no Stop hook; the tombstone commits even if stop is unverified.
    Interrupted stays sticky until an explicit respawn."""
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
    """Apply the continuity gate, then interrupt only a working native turn."""
    _supervisor_gate("interrupt", nonce=getattr(args, "nonce", None))
    args.name = _resolve_worker_target(args.name)
    with fleet_lock():
        data = load_registry()
        if args.name not in data["workers"]:
            raise FleetCliError(f"unknown worker: {args.name!r}")
        rec = dict(data["workers"][args.name])

    refuse_if_archived(args.name, rec, "interrupt")
    return _cmd_interrupt_native(args.name, rec, run=run, which=which)


def cmd_attach(args) -> int:
    """Point native-session users at the agents menu or `claude attach`."""
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
    """Apply the continuity gate and change attached to idle; otherwise warn/no-op."""
    _supervisor_gate("release", nonce=getattr(args, "nonce", None))
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


# CLI resilience commands (SPEC §5, §7, §11).

def _cmd_respawn_native(args, before: dict, run=subprocess.run, which=shutil.which,
                        sleep=time.sleep, clock=time.monotonic) -> int:
    """Reset context with a fresh native dispatch under the same worker name.
    Use the roster running-turn predicate; ambiguous roster data refuses to
    avoid two live sessions. --force stops a live sid and records a tombstone,
    then rechecks the roster even when stop reports success. Allow one grace
    recheck after reported success; any still-live result aborts the respawn.
    Sweep the most recent sids being retired independently of current liveness.
    Carry configuration/provenance/costs and prior retired_sids into a sid-less
    pre-claim, compose task/journal/old mailbox, then commit the new sid/ceiling.
    Dispatch failure restores the exact prior record instead of losing the name."""
    # Apply the ceiling here as well as in cmd_respawn for direct callers.
    # --task starts new work; bare respawn remains permitted as over-ceiling recovery.
    if getattr(args, "task", None):
        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
        if _ceiling_refusal is not None:
            raise FleetCliError(_ceiling_refusal)
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
    # Read the full stored brief, not the registry provenance excerpt. Do not fill
    # args.task from it: that flag arms the new-dispatch ceiling. Resolve overrides
    # here but write them only within the pre-claim rollback envelope below.
    if task_override is not None:
        task_for_record = task_override
    else:
        task_for_record = read_brief(name, before)
    prior_retired = list(before.get("retired_sids", []))
    spawned_by = before.get("spawned_by")
    # Carry ownership provenance unchanged; respawn must not transfer it to its caller.
    spawned_by_lineage = before.get("spawned_by_lineage")

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
        # Stop fires no Stop hook; record the operator stop attempt even if unverified.
        write_tombstone_outcome(name, old_sid, "stopped")
        # Always recheck roster liveness: a successful stop exit is not proof of teardown.
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

    # Sweep every sid being retired independently of the running-turn verdict:
    # an idle session may still have a resident process, and stop emits no outcome.
    # The --force/liveness refusal already ran above; write any missing tombstone.
    # Preserve oldest-first order through dedup before taking the most-recent cap;
    # exclude the old sid if --force already stopped and tombstoned it.
    _sweep = [s for s in _ordered_unique_sids(prior_retired + [old_sid])
              if s and not (old_live and s == old_sid)][-_RETIRED_SID_SWEEP_CAP:]
    if _sweep:
        with fleet_lock():
            other_current_sids = {
                other_rec.get("session_id")
                for other_name, other_rec in load_registry()["workers"].items()
                if other_name != name and other_rec.get("session_id") is not None
            }
        _sweep_retired_sessions(name, _sweep, other_current_sids,
                                run=run, which=which)
    if not old_live:
        # The stopped tombstone records deliberate retirement, not proof that stop succeeded.
        write_tombstone_outcome(name, old_sid, "stopped")

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
            spawned_by=spawned_by, spawned_by_lineage=spawned_by_lineage,
            dispatch_kind="bg", category=category)
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

    journal_path = journal_file_path(name)
    # A fresh non-resume session has no cached pointer content, so no inline
    # resumed-turn payload is needed.
    prompt, claim, _mail = compose_prompt(name, cwd, task_for_record, old_sid, journal_path=journal_path)
    prior_brief = brief_snapshot(name)
    try:
        # Write a task override inside the rollback envelope. Abort must restore it
        # along with the pre-respawn record; otherwise a later recovery would run a
        # brief no successful dispatch ever adopted.
        if task_override is not None:
            write_brief(name, task_override)
        # Verify brief delivery within rollback handling: a fresh session has no prior
        # task context, and refusal must restore both mailbox claim and worker record.
        assert_brief_carried(name, task_for_record, prompt)
        result = dispatch_bg(
            name, cwd, prompt, mode, model=model, category=category,
            hint=task_for_record, setting_sources=setting_sources,
            run=run, which=which, sleep=sleep, clock=clock,
        )
        finalize_mailbox_claim(claim)
    except NativeDispatchError as exc:
        # A short-id-matched fast completion proves dispatch consumed this prompt;
        # finalize its mailbox claim. Exclude the record's retired sid set so an old
        # session's farewell outcome cannot rebind the just-retired sid.
        fast_sid = _fast_completion_sid(name, pre_claim_at,
                                        short_id=getattr(exc, "short_id", None),
                                        exclude_sids=new_record["retired_sids"])
        if fast_sid is not None:
            finalize_mailbox_claim(claim)
            with fleet_lock():
                data = load_registry()
                rec = data["workers"].get(name)
                if rec is not None and rec.get("session_id") is None:
                    rec["session_id"] = fast_sid
                    # Derived fallback id, as in spawn fast completion; no CLI id was captured.
                    rec["native_short_id"] = fast_sid.partition("-")[0] or fast_sid[:8]
                    rec["status"] = "idle"
                    rec["turns"] = 1
                    rec["last_activity"] = now_iso()
                    save_registry(data)
                    # Post-save event errors must not invalidate a durable fast-completion commit.
                    _append_event_quiet("turn_started", name, session_id=fast_sid)
            _write_ceiling_file(fast_sid, token_ceiling)
            print(f"{name} {fast_sid} (native bg, fast completion before join)")
            return 0

        # Restore the brief only on rollback; a proven fast completion adopted this task.
        restore_brief(name, prior_brief)
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
        restore_brief(name, prior_brief)
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
    """Reset a worker's context with task, journal and old-sid mailbox carry.
    Route supervisor holders through release/stop/boot choreography. Apply the
    continuity gate before the destructive ownership acknowledgement; pass native
    liveness, dispatch and rollback handling to `_cmd_respawn_native`."""
    _supervisor_gate("respawn", nonce=getattr(args, "nonce", None))
    # §11.3: --task starts new work and arms the dispatch ceiling. Bare respawn
    # is §11.4 recovery, which must remain usable to fix over-ceiling state.
    # _cmd_respawn_native repeats this check for direct callers.
    if getattr(args, "task", None):
        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
        if _ceiling_refusal is not None:
            raise FleetCliError(_ceiling_refusal)
    _require_instance_settings()
    # Release before replacing a holder: a fresh body lacks its generation and nonce.
    _sup_target = _supervisor_lifecycle_target("respawn", args.name)
    if _sup_target is not None:
        _sup_name, _sup_rec, _sup_claim = _sup_target
        _supervisor_lifecycle_interaction_refusals("respawn", _sup_name, _sup_rec, _sup_claim)
        args.name = _sup_name
        refuse_if_archived(_sup_name, _sup_rec, "respawn")
        _confirm_destructive("respawn (retire the session of)", [_sup_name],
                             {_sup_name: dict(_sup_rec)},
                             assume_yes=getattr(args, "yes", False),
                             nonce=getattr(args, "nonce", None))
        return _cmd_respawn_supervisor(args, _sup_name, _sup_rec, _sup_claim,
                                       run=run, which=which, sleep=sleep, clock=clock)
    args.name = _resolve_worker_target(args.name)

    # Check foreign ownership outside the lock before retiring the old session.
    _ok, _reason, _snap = _read_registry_readonly()
    if _ok and args.name in _snap["workers"]:
        _confirm_destructive("respawn (retire the session of)", [args.name], _snap["workers"],
                             assume_yes=getattr(args, "yes", False), nonce=getattr(args, "nonce", None))
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
                             {args.name: before}, assume_yes=getattr(args, "yes", False), nonce=getattr(args, "nonce", None))

    refuse_if_archived(args.name, before, "respawn")
    if _is_supervisor_shaped(args.name):
        # Route non-holder supervisor-shaped husks through the boot ritual too.
        # The new body asks sup-boot to claim/refuse; a respawn flag cannot establish
        # holdership or bypass a live claim.
        return _cmd_respawn_supervisor(args, args.name, before, None,
                                       run=run, which=which, sleep=sleep, clock=clock)
    return _cmd_respawn_native(args, before, run=run, which=which, sleep=sleep, clock=clock)


_RETIRED_SID_SWEEP_TIMEOUT_SECONDS = 5
_RETIRED_SID_SWEEP_CAP = 20


def _ordered_unique_sids(values):
    """Deduplicate registry values in insertion order, preserving unhashable values.
    Malformed values reach the sweep's worker-specific diagnostics instead of
    raising here or disappearing silently. First occurrence wins so the caller's
    most-recent slice respects the oldest-first retired-sid order."""
    seen, out = set(), []
    for value in values:
        try:
            if value in seen:
                continue
            seen.add(value)
        except TypeError:
            pass          # unhashable: cannot dedup it, must not drop it
        out.append(value)
    return out


def _sweep_retired_sessions(name: str, retired_sids, other_current_sids,
                            run=subprocess.run, which=shutil.which) -> None:
    """Best-effort stop of retired sids, with classified progress per sid.
    Skip malformed ids and other workers' current sids to contain registry damage.
    Callers supply their locked ownership snapshot and retain responsibility for
    ordered deduplication and the most-recent cap. The cap bounds wall time;
    still-live retired sids beyond it remain unswept by this invocation."""
    for retired in retired_sids:
        # Validate before membership, slicing or stop: registry values are untrusted,
        # and malformed/unhashable elements must not abort either lifecycle verb.
        # Skip rather than coerce; bounded stderr diagnostics expose the damage.
        if not isinstance(retired, str) or not retired:
            print(
                f"fleet: {name}: retired session entry {retired!r:.40} is not a "
                "session id -- skipping (registry looks corrupted)",
                file=sys.stderr,
            )
            continue
        if retired in other_current_sids:
            print(
                f"fleet: {name}: retired session {retired[:8]} matches another "
                "worker's current session_id -- skipping (registry looks "
                "corrupted; not stopping someone else's live session)",
                file=sys.stderr,
            )
            continue
        # Catch unexpected failures per sid: best-effort cleanup cannot abort kill's
        # tombstone/dead mark or respawn's context reset. Report each failure and
        # continue so one corrupt fork cannot suppress the remaining sweep.
        try:
            _ok, outcome = _stop_native_session_status(
                retired, run=run, which=which,
                timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
        except Exception as exc:
            outcome = f"error ({exc.__class__.__name__}) -- not retried"
        print(f"fleet: {name}: stopping retired session {retired[:8]}... "
              f"{outcome}", file=sys.stderr)


def _cmd_kill_native(name: str, rec: dict, run=subprocess.run, which=shutil.which,
                     announce: bool = True, extra_stop_sids=None) -> int:
    """Stop current/recent retired native sids and mark the worker dead.
    Write a tombstone because stop fires no Stop hook. Kill is terminal even when
    stop cannot be verified, but warns and exits 1 so uncertainty is visible.
    Re-read for commit after unlocked stopping; cap retired work with short
    per-sid timeouts and skip any other worker's current sid."""
    with fleet_lock():
        _under_lock = load_registry()["workers"]
        other_current_sids = {
            other_rec.get("session_id")
            for other_name, other_rec in _under_lock.items()
            if other_name != name and other_rec.get("session_id") is not None
        }
        # Read stop ids under this lock to catch a fork after the caller's snapshot.
        # If the record vanished, retain snapshot ids; supervisor callers also supply
        # their last verified pre-steer union through extra_stop_sids.
        _fresh = _under_lock.get(name)
        _authoritative = _fresh if isinstance(_fresh, dict) else rec

    sid = _authoritative.get("session_id") or rec.get("session_id")
    # Use the captured native_short_id when available. A rejected guessed ref can
    # look like gone and falsely report success while the session keeps running.
    # Fast-completion ids can themselves be derived; retired ids have only the
    # _native_job_ref fallback. Classified gone remains success-equivalent.
    stop_outcome = "no-sid"
    if sid:
        captured_ref = _authoritative.get("native_short_id") or rec.get("native_short_id")
        stopped_ok, stop_outcome = _stop_native_session_status(
            sid, run=run, which=which,
            ref=captured_ref if isinstance(captured_ref, str) and captured_ref
            else None)
    else:
        stopped_ok = True
    # Union under-lock ids, caller-snapshot ids and extra_stop_sids, excluding the
    # primary already stopped above. Preserve insertion order before the cap so
    # lexical sid ordering cannot discard the most recent fork parent.
    _ordered = list(_authoritative.get("retired_sids") or [])
    _ordered += list(rec.get("retired_sids") or [])
    if rec.get("session_id"):
        _ordered.append(rec["session_id"])
    _ordered += list(extra_stop_sids or ())
    # First-occurrence dedup preserves authoritative oldest-first order and malformed values.
    retired_sids = [s for s in _ordered_unique_sids(_ordered)
                    if s and s != sid][-_RETIRED_SID_SWEEP_CAP:]
    # Callers own ordering/cap; the shared sweep handles ownership guards and progress.
    _sweep_retired_sessions(name, retired_sids, other_current_sids,
                            run=run, which=which)
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
        # Only unverified stops need investigation; classified gone is success-equivalent.
        print(
            f"fleet: {name}: claude stop could not be verified ({stop_outcome}) "
            "-- marked dead anyway (kill is a terminal action); investigate "
            "the session manually",
            file=sys.stderr,
        )
        return 1
    if announce:
        # Supervisor recovery arms have their own terminal announcements
        # (SPEC:1196-1198); generic killed output would conceal their different costs.
        print(f"{name}: killed")
    return 0


def cmd_kill(args, run=subprocess.run, which=shutil.which,
             sleep=time.sleep, clock=time.monotonic) -> int:
    """Stop a native worker, tombstone it and terminally mark it dead.
    Refuse an unexpired sid-less launch claim: dispatch may still commit.
    Apply continuity policy before destructive ownership acknowledgement."""
    _supervisor_gate("kill", nonce=getattr(args, "nonce", None))
    # Route holders into choreography; run interaction refusals before any registry write.
    _sup_target = _supervisor_lifecycle_target("kill", args.name)
    if _sup_target is not None:
        _sup_name, _sup_rec, _sup_claim = _sup_target
        _supervisor_lifecycle_interaction_refusals("kill", _sup_name, _sup_rec, _sup_claim)
        args.name = _sup_name
        refuse_if_archived(_sup_name, _sup_rec, "kill")
        _confirm_destructive("kill", [_sup_name], {_sup_name: dict(_sup_rec)},
                             assume_yes=getattr(args, "yes", False),
                             nonce=getattr(args, "nonce", None))
        return _cmd_kill_supervisor(args, _sup_name, _sup_rec, _sup_claim,
                                    run=run, which=which, sleep=sleep, clock=clock)
    args.name = _resolve_worker_target(args.name)
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

    # Acknowledge foreign ownership outside fleet_lock before retiring the worker.
    _confirm_destructive("kill", [args.name], workers_snapshot,
                         assume_yes=getattr(args, "yes", False), nonce=getattr(args, "nonce", None))

    return _cmd_kill_native(args.name, workers_snapshot[args.name], run=run, which=which)


# Supervisor tombstone choreography (three-tier §10.4).
# Both verbs resolve, refuse, steer and wait within a bound.
# Kill falls through to stop with claim frozen (SPEC:1198).
# Respawn aborts before destructive work; delivered steering may remain in
# flight, but context reset must not terminate the holder without a replacement.


def _resolve_supervisor_lifecycle_target(verb):
    """Resolve logical supervisor through claim holder sid and record sid union.
    Return (name, record, claim), or refuse with the lifecycle rc 2/3 distinction.
    Shape alone cannot identify a holder: retired supervisor-shaped husks exist.
    The identity contract is specified in SPAWN:461-471(i)."""
    state, claim = read_incarnation_status()
    if state == "corrupt":
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: refusing -- supervisor/INCARNATION is unreadable, "
            f"so the claim holder cannot be identified. A destructive verb never "
            f"decides blind (the same posture `sup-boot` takes as verdict `freeze`). "
            f"Run `fleet doctor` and inspect the claim file.", rc=3)
    if state == "absent" or not isinstance(claim, dict):
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: no supervisor claim exists -- nothing to {verb}. "
            f"`fleet sup-spawn --task <brief>` boots one.", rc=2)
    if claim.get("state") == "released":
        inc = claim.get("incarnation_id", "?")
        if verb == "kill":
            detail = (f"claim {inc} is already released -- there is no supervisor to "
                      f"kill. A released claim is terminal; any leftover body is an "
                      f"ordinary worker, so kill it by its REAL registry name "
                      f"(`fleet status` lists it).")
        else:
            detail = (f"claim {inc} is released -- there is no holder to respawn. "
                      f"Boot a fresh body with `fleet sup-spawn --task <brief>`.")
        # A release steer can land after an abort; report the resulting released state.
        raise SupervisorLifecycleRefusal(f"{verb} supervisor: refusing -- {detail}", rc=2)
    holder_sid = claim.get("session_id")
    if not isinstance(holder_sid, str) or not holder_sid:
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: refusing -- the claim "
            f"({claim.get('incarnation_id', '?')}) carries no readable holder sid, so "
            f"the body cannot be identified. Never decide blind: run `fleet doctor` "
            f"and inspect supervisor/INCARNATION.", rc=3)
    # Use a read without repair for the pre-flight
    # resolution that runs from `cmd_kill:5827` / `cmd_respawn:5643`, before
    # fleet.lock. Quarantining here would be an unlocked write destroying evidence.
    # Distinguish unreadable registry from a readable registry without a holder.
    # The refusal supplies its own --repair hint, so suppress the loader's copy.
    try:
        _records = read_registry_no_repair(hint=False)
    except RegistryCorruptError as exc:
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: refusing -- the registry is unreadable "
            f"({exc}), so the claim holder's record cannot be identified. A "
            f"destructive verb never decides blind -- the same posture this "
            f"function takes on an unreadable claim above, and the same rc. "
            f"Nothing was renamed or written: repair it with "
            f"`fleet doctor --repair`, then re-run.", rc=3)
    for wname, rec in _records.get("workers", {}).items():
        if holder_sid in _record_sids(rec):
            return (wname, rec, claim)
    raise SupervisorLifecycleRefusal(
        f"{verb} supervisor: refusing -- claim {claim.get('incarnation_id', '?')} "
        f"holder sid {holder_sid} matches no registry record. Claim/registry "
        f"divergence is never auto-repaired by a destructive verb: run "
        f"`fleet doctor` and reconcile it first.", rc=2)


def _supervisor_lifecycle_target(verb, name):
    """Route logical supervisor and real-name claim holders into §10.4.
    Return None for ordinary workers and non-holder husks. Indeterminate claims
    freeze supervisor-shaped targets only, preserving ordinary-worker recovery."""
    if name == SUPERVISOR_BODY_NAME:
        return _resolve_supervisor_lifecycle_target(verb)
    # Read without repair from
    # `cmd_kill:5827` / `cmd_respawn:5643`, ahead of either verb's `fleet_lock`,
    # so corruption remains for the ordinary path's lock-held loader.
    # `cmd_respawn:5664-5666` spells out that design -- resolve under the lock.
    # On corruption return None to route there; its loader refuses with the actual
    # registry error rather than an unknown-worker result from an empty substitute.
    try:
        rec = read_registry_no_repair().get("workers", {}).get(name)
    except RegistryCorruptError:
        return None
    if rec is None:
        return None
    # Read claim state explicitly: read_incarnation collapses corrupt to None.
    # A corrupt claim must freeze a real-name supervisor target as well as the
    # logical name, rather than routing it into an ordinary destructive action.
    state, claim = read_incarnation_status()
    if state == "corrupt" and _is_supervisor_shaped(name):
        raise SupervisorLifecycleRefusal(
            f"{verb}: refusing -- {name} is supervisor-shaped and "
            f"supervisor/INCARNATION is unreadable, so holdership cannot be "
            f"determined. Never decide blind on a destructive verb; run "
            f"`fleet doctor`.", rc=3)
    holder = _record_is_supervisor_claim_holder(rec, claim=claim if state == "ok" else None)
    if holder is True:
        if state != "ok" or not isinstance(claim, dict):
            raise SupervisorLifecycleRefusal(
                f"{verb}: refusing -- {name} looks like the supervisor claim holder "
                f"but supervisor/INCARNATION became unreadable. Never decide blind; "
                f"run `fleet doctor`.", rc=3)
        return (name, rec, claim)
    if holder is None and _is_supervisor_shaped(name):
        raise SupervisorLifecycleRefusal(
            f"{verb}: refusing -- {name} is supervisor-shaped and the claim's holder "
            f"cannot be determined (supervisor/INCARNATION unreadable). Failing "
            f"toward refusal: run `fleet doctor` and inspect the claim.", rc=3)
    return None


def _lifecycle_holder_is_limited(rec) -> bool:
    """Whether the already sid-union-resolved holder is parked as limited.
    A null reset horizon still refuses destructive lifecycle actions. Do not use
    the limit-transfer boot predicate, which requires a horizon and exact sid."""
    return isinstance(rec, dict) and rec.get("status") == "limited"


def _supervisor_lifecycle_interaction_refusals(verb, name, rec, claim):
    """Refuse handoff-in-flight and limited-parked holders before any mutation.
    A handoff token means a successor may be transferring. A parked holder cannot
    receive release steering; killing it would turn limit-transfer into a freeze.
    These refusals have no flag bypass and print the available recovery actions."""
    if claim.get("handoff_token_hash"):
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: refusing -- a handoff is in flight from claim "
            f"{claim.get('incarnation_id', '?')} (a one-shot token is minted and a "
            f"successor may already be booting). Resolve it first:\n"
            f"  fleet sup-handoff-complete   -- if the successor booted\n"
            f"  fleet sup-handoff-abort      -- if it did not\n"
            f"then re-run `fleet {verb} supervisor`.", rc=2)
    if _lifecycle_holder_is_limited(rec):
        raise SupervisorLifecycleRefusal(
            f"{verb} supervisor: refusing -- the claim holder ({name}) is parked on a "
            f"usage limit. A park is RECOVERABLE state, and every route through it is "
            f"cheaper than this verb:\n"
            f"  fleet sup-boot               -- a successor claims immediately via "
            f"limit-transfer (no wait)\n"
            f"  fleet resume-limited {name}  -- once the recorded reset horizon passes\n"
            f"  poisoned park: boot a successor via limit-transfer FIRST (`fleet "
            f"sup-boot`); the demoted body is then an ordinary worker and is killable "
            f"by its REAL registry name.\n"
            f"Killing pre-transfer costs a plain freeze of up to "
            f"{SUPERVISOR_CLAIM_STALE_SECONDS:.0f}s before any successor may seize -- "
            f"fleet cannot steer a limited body into `sup-release`, and no other actor "
            f"may release for it (B5).", rc=2)


def _refetch_holder_record(name, fallback):
    """Read the holder after release steering; return (record, verified).
    Idle steering forks/restamps the sid, so the earlier snapshot may identify a
    retired session. Read without repair: this unlocked observation must not
    quarantine evidence. If unreadable or vanished, return the fallback with
    verified=False; kill degrades loudly and respawn halts before successor
    creation rather than verify B6 against a possibly retired sid."""
    try:
        rec = read_registry_no_repair().get("workers", {}).get(name)
    except RegistryCorruptError:
        return (fallback, False)
    if not isinstance(rec, dict):
        return (fallback, False)
    return (rec, True)


def _refuse_launch_in_flight(verb, name, rec):
    """Refuse an unexpired sid-less pre-claim before supervisor stop or respawn.
    No session is yet available to stop, and a dead mark would race dispatch."""
    if rec.get("session_id") is None and not _launch_claim_expired(rec.get("last_activity")):
        raise FleetCliError(f"launch in flight for {name}; retry in a few seconds")


def _steer_supervisor_release(name, reason, *, run, which, sleep):
    """Deliver a holder-owned sup-release request (SPEC:1175-1179).
    Return None on delivery or refusal text. The holder supplies its own nonce.
    Call the native send engine directly: target resolution and continuity gating
    already happened, and callers must interpret a refused steer themselves."""
    py = Path(sys.executable).as_posix()
    # Render the installed code path; a data-only home has no bin/.
    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()
    message = (
        f"FLEET LIFECYCLE STEER ({reason}).\n"
        f"Stop what you are doing. Release the supervisor claim yourself -- fleet "
        f"cannot do it for you (three-tier §10.4 B5: `sup-release` requires YOUR "
        f"current generation, which only you hold).\n\n"
        f"Run exactly this, presenting your own nonce:\n"
        f'  "{py}" "{fleet_py}" sup-release --reason "{reason}" --nonce <your nonce>\n\n'
        f"Then take NO further fleet actions and END YOUR TURN. The body is stopped "
        f"as soon as the claim reads `released`.")
    try:
        _cmd_send_native(name, message, run=run, which=which, sleep=sleep)
    except FleetCliError as exc:
        return str(exc)
    return None


def _await_claim_released(*, timeout, poll, clock, sleep):
    """Poll for released claim state within a monotonic timeout.
    Clamp each sleep to the remaining budget. Treat unreadable claims as
    not-yet-released; timeout safely handles uncertainty without unbounded waits."""
    started = clock()
    while True:
        state, claim = read_incarnation_status()
        if state == "ok" and isinstance(claim, dict) and claim.get("state") == "released":
            return True
        elapsed = clock() - started
        if elapsed >= timeout:
            return False
        sleep(min(poll, timeout - elapsed))


def _cmd_kill_supervisor(args, name, rec, claim, *, run, which, sleep, clock) -> int:
    """Stop the supervisor and announce the recovery arm (SPEC:1196-1198).
    Steer sup-release and wait: a release permits SUP-KILL-RELEASED after stop and
    tombstone. Otherwise stop anyway and report SUP-KILL-FROZEN, leaving claim
    and heartbeat untouched so they age naturally. Fleet cannot release for it."""
    inc = claim.get("incarnation_id", "?")
    # Refuse an in-flight launch before mutation.
    _refuse_launch_in_flight("kill", name, rec)
    sid = rec.get("session_id")
    # Retain pre-steer ids as the minimum stop set if the later read cannot verify state.
    snapshot_sids = _record_sids(rec)
    verified = True
    arm2_reason = None
    if not sid:
        arm2_reason = "the holder record carries no session id -- nothing to steer"
    else:
        _require_instance_settings()
        refusal = _steer_supervisor_release(
            name, f"kill supervisor {inc}", run=run, which=which, sleep=sleep)
        if refusal is not None:
            # A refused steer cannot release the claim; fall through without waiting.
            arm2_reason = f"the release steer was refused: {refusal}"
        else:
            if not _await_claim_released(
                    timeout=SUPERVISOR_RELEASE_TIMEOUT_SECONDS,
                    poll=SUPERVISOR_RELEASE_POLL_SECONDS, clock=clock, sleep=sleep):
                arm2_reason = (f"T_release expired ({SUPERVISOR_RELEASE_TIMEOUT_SECONDS:.0f}s) "
                               f"without the claim reading `released`")
            # Delivered steering can fork on either wait outcome; refetch and stop current ids.
            rec, verified = _refetch_holder_record(name, rec)
            sid = rec.get("session_id") or sid

    rc = _cmd_kill_native(name, rec, run=run, which=which, announce=False,
                          extra_stop_sids=snapshot_sids if not verified else None)

    if not verified:
        # An unverified refetch cannot justify a clean terminal success: an unseen fork
        # may still run even after every known sid was stopped. Report degradation.
        _unverified = (
            f"SUP-KILL-UNVERIFIED {inc} -- the release steer was delivered, but "
            f"{name}'s registry record could not be re-read afterwards (registry "
            f"unreadable/quarantined, or the record was removed mid-choreography: "
            f"releasing the claim drops the §7.2 gate-0 protection, so "
            f"`autoclean`/`clean` may legitimately have taken it).\n"
            f"Stopped every session this verb knew about "
            f"({', '.join(sorted(s for s in snapshot_sids if s)) or 'none'}) -- but a "
            f"steer to an IDLE body FORK-STEERS, and a fork minted after the last "
            f"good read would not be in that set. DO NOT assume the supervisor is "
            f"gone.\n"
            f"Verify before booting a successor:\n"
            f"  fleet doctor                 -- registry health / quarantine\n"
            f"  claude agents                -- any live session for {name}?\n"
            f"  fleet sup-status             -- did the release land?")
        # Print the dangerous outcome on both streams: stdout searches for SUP-KILL-
        # must find it, while stderr retains the operator warning. Return rc 1.
        print(_unverified)
        print(_unverified, file=sys.stderr)
        return 1

    if arm2_reason is None:
        print(f"SUP-KILL-RELEASED {inc} -- the holder released the claim, the body is "
              f"stopped and the record is dead. A successor boots cleanly now "
              f"(`fleet sup-spawn`): claim-nonce §6.1 rule 1b, fresh claim, no seizure.")
        if rc != 0:
            # Failure mode (c): the claim reads `released` while the releaser
            # may still be roster-live. Boot rule 1 holds the door shut, but the
            # operator must not be left guessing why sup-boot refuses.
            print(f"fleet: WARNING (B6): {name}'s session could not be verified stopped "
                  f"-- do NOT run `fleet sup-boot` until the roster shows {sid} gone. "
                  f"Rule 1 refuses a released record whose releaser is still live.",
                  file=sys.stderr)
    else:
        print(f"SUP-KILL-FROZEN {inc} -- {arm2_reason}. The body is stopped and "
              f"tombstoned, but the claim is FROZEN: it still names the dead body, and "
              f"no killer-side release is possible (§10.4 B5). Every `fleet sup-boot` "
              f"verdicts `freeze` until the heartbeat ages past "
              f"{SUPERVISOR_CLAIM_STALE_SECONDS:.0f}s, after which a successor seizes. "
              f"`fleet sup-status` shows the remaining wait.")
    return rc


def _supervisor_abort(phase, reason, name, *, delivered):
    """Report a respawn abort with escalation commands and late-release warning.
    A delivered steer may complete asynchronously: require checking sup-status.
    Undelivered refusal has no delivery effects; a timeout may retain mailbox,
    event and fork-restamp effects, but performs no destructive tail or dispatch."""
    if delivered:
        touched = (
            f"The steer WAS DELIVERED before this abort, so the body is not untouched: "
            f"the message was queued (mid-turn) or the body FORK-STEERED (idle), which "
            f"mints a new session id and retires the old one. What did NOT happen: no "
            f"tombstone, no dead-marking, no claim-file change, no successor dispatch.\n")
    else:
        touched = (
            f"The steer was never delivered, so the supervisor body was NOT touched -- "
            f"respawn has no mandate to destroy a body that will not cooperate "
            f"(ruling 1, 4-0).\n")
    raise SupervisorLifecycleRefusal(
        f"SUP-RESPAWN-ABORTED {phase}: {reason}\n"
        f"{touched}"
        f"WARNING: the release steer may still land asynchronously -- a slow body can "
        f"complete `sup-release` after this abort. Check `fleet sup-status` BEFORE "
        f"acting on this message.\n"
        f"Escalate with:\n"
        f"  fleet peek {name}\n"
        f"  fleet kill supervisor        -- if it must go regardless (may freeze the claim)\n"
        f"  fleet sup-spawn --task <brief>   -- once the claim is released or seized",
        rc=2)


def _cmd_respawn_supervisor(args, name, rec, claim, *, run, which, sleep, clock) -> int:
    """Release, stop and replace a supervisor with a fresh gen-0 body.
    A fresh body has no generation; release enables immediate rule-1b boot rather
    than waiting for seizure. Nonce transfer is forbidden (CN:1671-1675, §6.5).
    After release steering/wait, stop and tombstone, verify caller-side B6, then
    dispatch. claim=None skips release for a husk but retains the boot ritual.
    Steer refusal/timeout aborts before destructive work; delivered steering can
    already have queued mail or forked the holder."""
    old_sid = rec.get("session_id")
    inc = claim.get("incarnation_id", "?") if claim else None

    # Resolve the full campaign before release/stop so an unreadable brief cannot strand the fleet.
    task_override = _read_task_arg(args.task) if getattr(args, "task", None) else None
    # Pass the stored campaign into the supervisor body renderer.
    campaign = (task_override if task_override is not None
                else read_brief(name, rec))

    if claim is not None:
        if not old_sid:
            _supervisor_abort("stop-precondition",
                              f"launch in flight for {name} (no session id yet) -- "
                              f"there is no body to release or stop", name,
                              delivered=False)
        _require_instance_settings()
        refusal = _steer_supervisor_release(
            name, f"respawn supervisor {inc}", run=run, which=which, sleep=sleep)
        if refusal is not None:
            # No delivered steer means no delivery mutations on this refusal path.
            _supervisor_abort("steer-refused", refusal, name, delivered=False)
        expired = not _await_claim_released(
            timeout=SUPERVISOR_RELEASE_TIMEOUT_SECONDS,
            poll=SUPERVISOR_RELEASE_POLL_SECONDS, clock=clock, sleep=sleep)
        # The steer landed; refetch before using any session id.
        rec, verified = _refetch_holder_record(name, rec)
        old_sid = rec.get("session_id") or old_sid
        if not verified:
            # Unverified state cannot pass B6; halt before deciding to dispatch a second body.
            raise SupervisorLifecycleRefusal(
                f"SUP-RESPAWN-HALTED-UNVERIFIED: the release steer for {name} was "
                f"delivered, but its registry record could not be re-read afterwards "
                f"(the registry is unreadable/was quarantined, or the record was "
                f"removed mid-choreography -- releasing the claim drops the §7.2 "
                f"gate-0 protection, so `autoclean`/`clean` may legitimately have "
                f"taken it).\n"
                f"NOT DISPATCHING a successor: the caller-side B6 gate cannot confirm "
                f"the old body is roster-gone, and a successor booted over a live one "
                f"is the two-bodies hole §10.4 exists to close.\n"
                # Report that only steering occurred; this halt precedes stop and tombstone.
                f"NOTHING was done past the steer: no stop was attempted, no tombstone "
                f"was written, and the record was NOT marked dead. The body is very "
                f"likely still alive.\n"
                f"The claim may already read `released`. Check, in this order:\n"
                f"  fleet doctor                 -- registry health / quarantine\n"
                f"  fleet sup-status             -- did the release land?\n"
                f"  claude agents                -- is any session of {name} still live?\n"
                f"Then stop any survivor by its real sid and `fleet sup-spawn`.", rc=2)
        if expired:
            _supervisor_abort(
                "T_release-expired",
                f"the claim did not read `released` within "
                f"{SUPERVISOR_RELEASE_TIMEOUT_SECONDS:.0f}s", name, delivered=True)
    else:
        _require_instance_settings()
        # A husk skips release, but keeps ordinary liveness and launch-claim guards.
        # Running turns need --force; unavailable roster data cannot establish safety.
        _refuse_launch_in_flight("respawn", name, rec)
        if old_sid:
            roster_ok, entries = _fetch_agents_roster(which=which, run=run)
            if not roster_ok:
                raise FleetCliError(
                    f"{name}: could not fetch the native roster -- refusing respawn "
                    f"until the old session's liveness can be verified")
            if old_sid in _roster_live_sids(entries) and not getattr(args, "force", False):
                raise FleetCliError(
                    f"{name}: turn is running -- pass --force to interrupt it first, "
                    f"or wait for it to finish")

    # ---- past this point the claim is released (or was never held) ----
    stopped_ok = True
    stop_outcome = "no-sid"
    if old_sid:
        # Stop the refetched current sid and best-effort sweep its retired parents.
        # Idle steering forks, leaving the old parent potentially resident too.
        stopped_ok, stop_outcome = _stop_native_session_status(
            old_sid, run=run, which=which,
            ref=rec.get("native_short_id") or None)
        for retired in list(rec.get("retired_sids", []) or [])[-_RETIRED_SID_SWEEP_CAP:]:
            if retired and retired != old_sid:
                _stop_native_session_status(
                    retired, run=run, which=which,
                    timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
        # Stop emits no Stop hook; fleet writes the stopped outcome.
        write_tombstone_outcome(name, old_sid, "stopped")

        # CALLER-SIDE B6 GATE (SPEC:1224-1229): verify the whole sid union is gone
        # before dispatching. A successor's boot refusal is insufficient protection
        # for the caller that would create that second body.
        gate_sids = _record_sids(rec)

        def _any_live():
            roster_ok, entries = _fetch_agents_roster(which=which, run=run)
            if not roster_ok:
                return True
            return bool(gate_sids & _roster_live_sids(entries))

        still_live = _any_live()
        if still_live and stopped_ok:
            sleep(2)
            still_live = _any_live()
        if still_live:
            # Use a distinct halt token: stop/tombstone already occurred, unlike an early abort.
            raise SupervisorLifecycleRefusal(
                f"SUP-RESPAWN-HALTED-B6: {name} still has a roster-live session "
                f"({', '.join(sorted(s for s in gate_sids if s))}) after the stop "
                f"attempt ({stop_outcome}) -- refusing to dispatch a successor. B6: a "
                f"successor may boot only once the old body is confirmed roster-gone, "
                f"or two bodies answer for one claim.\n"
                f"THIS IS NOT AN ABORT: the claim is already RELEASED and the body was "
                f"stopped and tombstoned. Recovery is: stop the session manually, then "
                f"`fleet sup-spawn --task <brief>`.", rc=2)

    with fleet_lock():
        data = load_registry()
        r = data["workers"].get(name)
        if r is not None:
            r["status"] = "dead"
            save_registry(data)
        append_event("respawned", name, old_session_id=old_sid,
                     new_session_id=None, stopped=stopped_ok)

    # Campaign resolution preceded every destructive step.
    mode = getattr(args, "permission_mode", None) or rec.get("mode") or SUP_SPAWN_DEFAULT_MODE
    model = getattr(args, "model", None) or rec.get("model")
    # Dispatch a fresh gen-0 body with the boot ritual and durable supervisor state.
    # Do not carry the ordinary worker journal/mailbox context into that ritual.
    # Carry setting_sources with mode/model: it controls which hooks the successor
    # runs, including project/local isolation from user-level integration hooks.
    return _dispatch_supervisor_body(campaign, mode, model,
                                     setting_sources=rec.get("setting_sources"),
                                     run=run, which=which,
                                     sleep=sleep, clock=clock)


def _remove_worker_files(name: str, sid: str, retired_sids: list = ()) -> list:
    """Best-effort delete artifacts for a removed dead worker; return removed paths.
    Include logs, journals, tasks, outcomes, current mailbox/claimed files,
    retired-sid outcomes/ceilings and the worker's archive tree. Missing files
    are harmless; only clean deletes the archived evidence tree."""
    removed = []
    stem = name_fs_stem(name)
    candidates = [
        logs_dir() / f"{stem}.jsonl", logs_dir() / f"{stem}.jsonl.1",
        logs_dir() / f"{stem}.err", logs_dir() / f"{stem}.err.1",
        mailbox_dir() / f"{sid}.md",
        journal_file_path(name),
        # Sweep sid-keyed ceiling state with the other artifacts.
        ceiling_file_path(sid),
        outcome_path(name),
        outcome_path(sid),
        task_file_path(name),
        # Remove the brief so a later worker reusing this name cannot inherit stale scope.
        brief_file_path(name),
        # Remove abandoned boot bundles, which retain the minted nonce plaintext.
        boot_bundle_path(name),
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
    archive_dir = archive_root() / stem
    if archive_dir.exists():
        try:
            shutil.rmtree(archive_dir)
            removed.append(archive_dir)
        except OSError:
            pass
    # Delete numeric collision-suffixed archive directories too. Anchor the name
    # pattern so cleaning w1 cannot sweep a differently named worker such as w10.
    if archive_root().exists():
        suffix_re = re.compile(re.escape(stem) + r"\.\d+$")
        for p in sorted(archive_root().iterdir()):
            if p.is_dir() and suffix_re.match(p.name):
                try:
                    shutil.rmtree(p)
                    removed.append(p)
                except OSError:
                    pass
    return removed


def _released_claim_body_sid(claim):
    """Return a released claim's nonempty string released_by_sid, otherwise None."""
    if not isinstance(claim, dict) or claim.get("state") != "released":
        return None
    sid = claim.get("released_by_sid")
    return sid if isinstance(sid, str) and sid else None


def _clean_spares_released_body_evidence(record, released_by, live_sids) -> bool:
    """Whether deleting a record could change the released-claim wedge evidence.
    A release tombstone lets B6 stand down; deleting its carrier while the body's
    sid union remains roster-live can re-arm the wedge. Deleting an untombstoned
    carrier can instead disarm a live wedge. Protect both until the body is gone.
    Absence cannot substitute for a tombstone: unresolved/ambiguous identities
    and unreadable registries legitimately leave no carrier, and must still fail
    closed. Consult the full sid union to cover fork-steer restamping.
    Unknown roster liveness spares evidence because deletion is irreversible.
    Absent/unreadable claims do not establish a released-body wedge to protect."""
    if not released_by:
        return False
    sids = _record_sids(record)
    if released_by not in sids:
        return False
    if live_sids is None:
        return True
    return bool(sids & live_sids)


def cmd_clean(args, run=subprocess.run, which=shutil.which) -> int:
    """Delete confirmed-dead workers and archived tombstones with their evidence.
    Probe outside the lock; condition deletion on the record still matching its
    snapshot so concurrent respawn/send wins. Suspicious rosters freeze the sweep.
    --dead-only spares tombstones; --tombstones skips recomputation and ordinary
    records. Protect current holders and released-body carrier evidence until
    its sid union leaves the roster. Apply continuity policy before deletion."""
    _supervisor_gate("clean", nonce=getattr(args, "nonce", None))
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

    # Share one claim snapshot across eligibility/protection decisions.
    claim = read_incarnation()
    released_by = _released_claim_body_sid(claim)
    carriers = [n for n in names
                if released_by and released_by in _record_sids(before[n])]

    # Fetch the roster once outside the lock for ordinary live candidates or any
    # released-body carrier, including tombstones whose safe deletion needs it.
    roster_entries = []
    roster_ok = False
    epoch_frozen = False
    if live_names or carriers:
        roster_ok, payload = _fetch_agents_roster(which=which, run=run)
        roster_entries = payload if roster_ok else []
        if live_names:
            epoch_frozen = native_epoch_suspicious(roster_ok, roster_entries, before)

    # None means "the roster is unknown", which SPARES -- see the predicate.
    live_sids = _roster_live_sids(roster_entries) if roster_ok else None
    spared = [n for n in carriers
              if _clean_spares_released_body_evidence(before[n], released_by,
                                                      live_sids)]
    doomed_archived_names = [n for n in doomed_archived_names if n not in spared]

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
            if verdict["status"] in _NATIVE_CLEAN_DELETABLE and n not in spared:
                doomed_now.append((n, before[n]))
                continue
            # A spared record falls THROUGH to the persist branch rather than
            # skipping out: sparing it from deletion is not a reason to withhold
            # a status the recompute just decided.
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

    # A record `clean` declined to delete, with nothing printed, reads as
    # "there was nothing to clean" -- and the operator never learns that fleet
    # is holding load-bearing evidence on their behalf.
    for n in spared:
        why = (f"session {released_by} is still in the roster"
               if live_sids is not None else "the roster could not be read")
        print(f"spared {n}: it vouches for released claim "
              f"{claim.get('incarnation_id', '?')} -- {why}; deleting it would "
              f"re-arm the refusal that stops a successor booting (B6)")

    # Acknowledge the exact foreign-worker deletion set outside the lock.
    # Clean removes evidence/registry state; later husk cleanup may also remove the
    # native session that events still identify, so sid recovery is not permanent.
    doomed = {n: rec for n, rec in doomed_now}
    if doomed:
        # Name archived evidence explicitly when it is part of the deletion set.
        any_archived = any(rec.get("archived_at") is not None for rec in doomed.values())
        action = ("clean (delete logs + journal + archived history of)" if any_archived
                  else "clean (delete logs + journal of)")
        _confirm_destructive(action, sorted(doomed), doomed,
                             assume_yes=getattr(args, "yes", False), nonce=getattr(args, "nonce", None))

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

    if not removed and not spared:
        print("nothing to clean -- no dead workers")
    return 0


# Archive terminal native workers into evidence directories and retain registry
# tombstones. Never remove roster-live sessions; clean owns evidence deletion.

ARCHIVE_TTL_HOURS_DEFAULT = 24.0


def _reap_mail_pending(sid: str) -> bool:
    """Fail closed on unread or claimed mail, including I/O uncertainty."""
    try:
        paths = [mailbox_dir() / f"{sid}.md"]
        paths.extend(mailbox_dir().glob(f"{sid}.md.claimed.*"))
        for path in paths:
            try:
                if path.stat().st_size:
                    return True
            except FileNotFoundError:
                pass
        return False
    except OSError:
        return True


def _reap_current_supervisor_forks(name=None, expected_sid=None, *,
                                   run=subprocess.run, which=shutil.which,
                                   sleep=time.sleep, roster_fn=None, attempts=1,
                                   caller_sid=None):
    """Stop idle pre-steer processes only after the current fork is roster-live.
    Keep the current row and sid history. Send takes three fresh observations;
    lifecycle passes retry deferred cleanup. Bound each pass to four stops with
    five-second CLI-attempt timeouts; outcomes alone cannot prove a live fork."""
    caller = caller_sid or current_caller_session()
    fetch = roster_fn or (lambda: _fetch_agents_roster(which=which, run=run))
    stopped = []

    def current():
        ok, _reason, data = _read_registry_readonly()
        claim = read_incarnation()
        if not ok or not isinstance(claim, dict) or claim.get("state") == "released":
            return None
        workers = data.get("workers", {})
        holders = [(n, r) for n, r in workers.items()
                   if _record_is_supervisor_claim_holder(r, claim=claim) is True]
        if len(holders) != 1:
            return None
        n, record = holders[0]
        sid = record.get("session_id")
        if (name is not None and n != name or not sid or
                expected_sid is not None and sid != expected_sid or
                record.get("archived_at") or not is_native(record)):
            return None
        sids = _record_sids(record)
        if any(other != n and sids & _record_sids(rec)
               for other, rec in workers.items()):
            return None
        history = record.get("retired_sids", [])
        if not isinstance(history, list):
            return None
        retired = [s for s in _ordered_unique_sids(history)
                   if isinstance(s, str) and _SID_SHAPE_RE.fullmatch(s)
                   and s != sid and s != caller]
        return n, sid, retired, claim.get("incarnation_id")

    try:
        initial = current()
        if initial is None or not initial[2]:
            return stopped
        for attempt in range(max(1, min(attempts, 3))):
            ok, entries = fetch()
            if ok and initial[1] in _fork_took_over_rows(entries):
                break
            if attempt + 1 < max(1, min(attempts, 3)):
                sleep(1)
        else:
            print(f"fleet: {initial[0]}: fork retirement deferred -- "
                  "replacement not observed live", file=sys.stderr)
            return stopped
        # Retire newest parents first. No daemon subprocess runs under the
        # fleet lock; re-read the authority and mail immediately before stop.
        live = _fork_took_over_rows(entries)
        candidates = [sid for sid in reversed(initial[2])
                      if len(live.get(sid, [])) == 1
                      and live[sid][0].get("status") == "idle"
                      and not _reap_mail_pending(sid)][:4]
        for retired in candidates:
            ok, entries = fetch()
            if not ok:
                break
            live = _sup_guard_live_rows(entries)
            old_rows = live.get(retired, [])
            if len(live.get(initial[1], [])) != 1 or not old_rows:
                continue
            if len(old_rows) != 1 or old_rows[0].get("status") != "idle":
                continue
            with fleet_lock():
                fresh = current()
                if (fresh is None or fresh[:2] != initial[:2]
                        or fresh[3] != initial[3] or retired not in fresh[2]
                        or _reap_mail_pending(retired)):
                    continue
            ok, outcome = _stop_native_session_status(
                retired, run=run, which=which,
                timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS,
                ref=old_rows[0].get("id"))
            _append_event_quiet("supervisor_fork_retired", initial[0],
                                session_id=retired, live_fork=initial[1],
                                stopped=ok, outcome=outcome)
            print(f"fleet: {initial[0]}: retiring pre-steer session "
                  f"{retired[:8]}... {outcome}", file=sys.stderr)
            if ok:
                stopped.append(retired)
    except Exception as exc:
        print(f"fleet: supervisor fork retirement deferred -- "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return stopped


def _reap_protection(name: str, record: dict, roster_entries: list, claim,
                     reap_caller_sid=None):
    """Return the shared whole-record veto for automatic reaping.
    Protect the caller, ambiguous/unreadable ownership, current claim/incarnation,
    pending mail and any current/retired sid with a PID or nonidle roster status."""
    sids = _record_sids(record)
    caller = reap_caller_sid or current_caller_session()
    if caller and caller in sids:
        return "reap-caller"
    # After release/transfer, holdership cannot protect the exiting caller.
    # Protect all ownership matches, including dead/archived rows: a resolver's
    # live-row preference cannot prove an overlapping husk sid disposable.
    ok, reason, registry = _read_registry_readonly()
    if not ok:
        return "registry-unreadable"
    if any(other != name and sids & _record_sids(rec)
           for other, rec in registry.get("workers", {}).items()):
        return "ambiguous-identity"
    holder = _record_is_supervisor_claim_holder(record, claim=claim)
    if holder is True or (holder is None and
            (name == SUPERVISOR_BODY_NAME or _is_supervisor_shaped(name))):
        return "current-claim"
    if (isinstance(claim, dict) and claim.get("state") != "released"
            and _is_supervisor_shaped(name)
            and name.split("|")[1] == claim.get("incarnation_id")):
        return "current-incarnation"
    for member in _record_sids(record):
        if _reap_mail_pending(member):
            return "unread-mail"
        entry = _roster_entry_for(roster_entries, member)
        if entry is not None and ("pid" in entry or
                ("status" in entry and entry.get("status") != "idle")):
            return "roster-live"
    return None


def _reap_eligible(name: str, record: dict, roster_entries: list, claim,
                   reap_caller_sid=None) -> tuple:
    """Apply age-independent landing/dead eligibility and the shared protection veto.
    A result alone is not a landing; require lane_state/outcome evidence unless
    the daemon confirms death. A verified non-holder supervisor predecessor can
    qualify without a lane landing; pending successors cannot. Roster absence
    alone is insufficient, and PID presence protects current and retired sids
    without host-specific probes."""
    sid = record.get("session_id")
    if not sid:
        return False, "no-session-id"
    protection = _reap_protection(name, record, roster_entries, claim, reap_caller_sid)
    if protection:
        return False, protection
    # A missing/corrupt claim cannot establish a predecessor. Pending handoff
    # successors also do not become predecessors just by having another inc.
    if isinstance(claim, dict) and (name == SUPERVISOR_BODY_NAME or
                                    _is_supervisor_shaped(name)):
        pending = handoff_pending_members(claim)
        if any(not isinstance(m, dict) or
               name == _successor_worker_name(m.get("successor_inc", ""))
               for m in pending):
            return False, "pending-successor"
        if _record_is_supervisor_claim_holder(record, claim=claim) is False:
            return True, "predecessor-supervisor"
    entry = _roster_entry_for(roster_entries, sid)
    if entry is not None and "status" not in entry and "pid" not in entry:
        return True, "daemon-dead"
    outcome = latest_outcome(name, sid)
    lane_state = record.get("lane_state")
    if lane_state not in ("landed", "abandoned") and isinstance(outcome, dict):
        lane_state = outcome.get("kind")
    if lane_state not in ("landed", "abandoned"):
        return False, "lane-not-terminal"
    if entry is not None and entry.get("status") == "idle":
        return True, f"lane-{lane_state}"
    if entry is None and record.get("status") == "idle":
        return True, f"lane-{lane_state}"
    return False, "session-not-idle"


def _archive_eligible(name: str, record: dict, roster_entries: list, now,
                      ttl_hours: float = ARCHIVE_TTL_HOURS_DEFAULT,
                      reap: bool = False, reap_caller_sid=None) -> tuple:
    """Return eligibility or the first failed gate, protecting the claim holder first.
    Indeterminate claims protect supervisor-shaped names only. Internal reap=True
    first applies age-independent eligibility and shared PID/mail/claim vetoes.
    TTL eligibility requires native/unarchived, idle/dead/interrupted, current sid
    absent or dead in the roster, an outcome, and last_activity older than TTL.
    Also protect a released-body record currently wedging the fleet: archiving it
    must not remove the evidence the guard reads. Ordinary live retired sids are
    skipped by the removal loop rather than vetoing the whole TTL archive."""
    # Share one claim read across both claim-keyed archive gates.
    claim = read_incarnation()
    holder = _record_is_supervisor_claim_holder(record, claim=claim)
    if holder is True or (holder is None and
                          (name == SUPERVISOR_BODY_NAME or _is_supervisor_shaped(name))):
        return (False, "supervisor claim-holder -- protected while live (§7.2)")
    if not is_native(record):
        return (False, "not-native")
    if record.get("archived_at") is not None:
        return (False, "already-archived")
    if reap:
        eligible, reason = _reap_eligible(name, record, roster_entries, claim,
                                         reap_caller_sid)
        if eligible or reason not in ("lane-not-terminal", "session-not-idle"):
            return eligible, reason
        # TTL fallback retains the shared PID/mail/claim vetoes; daemon-confirmed dead
        # rows can qualify through the age-independent path without a result or TTL.
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
    # Gate 3b protects the sid-union carrier currently wedging the fleet.
    # Gate 3 intentionally checks only current sid; ordinary live retired forks are
    # skipped by removal. Apply the gate's own predicate so archive cannot erase
    # its evidence while it still refuses mutating verbs.
    if (isinstance(claim, dict)
            and claim.get("released_by_sid") in _record_sids(record)
            and _releaser_live_sids(claim, _roster_live_sids(roster_entries),
                                    registry={"workers": {name: record}})):
        return (False, "wedging-released-claim")
    if not read_outcomes(name, sid=sid):
        return (False, "no-outcome-record")
    try:
        last_activity = _parse_iso(record.get("last_activity", ""))
    except (ValueError, TypeError):
        # Missing/malformed last_activity must refuse eligibility without raising.
        return (False, "last-activity-unparseable")
    age_hours = (now - last_activity).total_seconds() / 3600.0
    if age_hours < ttl_hours:
        return (False, "ttl-not-elapsed")
    return (True, "eligible")


def _archive_dest_dir(name: str) -> Path:
    """Choose an unused archive directory, suffixing name on collision.
    Only fresh archives allocate; resume uses the prior directory so a crash
    cannot split one worker's evidence across destinations."""
    stem = name_fs_stem(name)
    base = archive_root() / stem
    if not base.exists():
        return base
    i = 1
    while (archive_root() / f"{stem}.{i}").exists():
        i += 1
    return archive_root() / f"{stem}.{i}"


def _archive_file_pairs(name: str, sid: str, retired: list) -> list:
    """Map worker evidence sources to distinct archive filenames.
    Include journal, outcomes, task and current/retired mailboxes. Share this
    mapping with resume detection so pending evidence cannot be overlooked."""
    pairs = [
        (journal_file_path(name), "journal.md"),
        (outcome_path(name), outcome_path(name).name),
        (task_file_path(name), "task.md"),
        # Archive the original brief too: task.md may contain only the latest steer payload.
        (brief_file_path(name), "brief.md"),
        # Move abandoned boot bundles so nonce plaintext is not stranded at its old path.
        (boot_bundle_path(name), "boot-bundle.txt"),
    ]
    if sid:
        pairs.append((outcome_path(sid), outcome_path(sid).name))
        pairs.append((mailbox_dir() / f"{sid}.md", f"{sid}.md"))
    for s in retired:
        pairs.append((outcome_path(s), outcome_path(s).name))
        pairs.append((mailbox_dir() / f"{s}.md", f"{s}.md"))
    return pairs


def _archive_resume_pending(name: str, record: dict) -> bool:
    """Whether a tombstoned archive still has evidence at pre-move locations.
    A rerun resumes relocation into the same directory after interrupted moves."""
    if record.get("archived_at") is None:
        return False
    sid = record.get("session_id")
    retired = list(record.get("retired_sids", []) or [])
    return any(src.exists() for src, _dest in _archive_file_pairs(name, sid, retired))


def _archive_move_and_rm(n: str, sid: str, retired: list, dest_dir: Path,
                         roster_entries: list, run, which, reap: bool = False,
                         reap_caller_sid=None) -> None:
    """Move evidence, then best-effort remove current and retired native sessions.
    Use the eligibility roster snapshot to skip every live sid, including retired
    forks; current-sid eligibility alone cannot establish their safety."""
    if reap:
        # The same protection applies to crash-resumes, and BEFORE moving mail
        # out of its inbox. A post-commit arrival leaves the archive resumable.
        record = {"session_id": sid, "retired_sids": retired}
        if _reap_protection(n, record, roster_entries, read_incarnation(), reap_caller_sid):
            return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src, dest_name in _archive_file_pairs(n, sid, retired):
        if reap and src.parent == mailbox_dir():
            # Mail can arrive while slow evidence moves run. Never move the
            # inbox out from under the final pre-rm check in automatic cleanup.
            continue
        _archive_move(src, dest_dir / dest_name, n)

    if reap and _reap_protection(n, record, roster_entries, read_incarnation(), reap_caller_sid):
        return  # a delivery during file moves protects the entire sid union
    for s in ([sid] if sid else []) + retired:
        entry = _roster_entry_for(roster_entries, s)
        live = entry is not None and ("pid" in entry or
                ("status" in entry and (not reap or entry.get("status") != "idle")))
        if reap and _reap_mail_pending(s):
            continue
        if live:
            print(f"fleet: {n}: skipping rm {s[:8]}... -- session live in roster",
                  file=sys.stderr)
            continue
        # Use the CLI roster id: a rejected guessed ref can masquerade as already gone.
        entry_ref = entry.get("id") if isinstance(entry, dict) else None
        ok, outcome = _rm_native_session_status(
            s, run=run, which=which,
            ref=entry_ref if isinstance(entry_ref, str) and entry_ref else None)
        if ok:
            # Gone is success-equivalent: the desired roster absence already holds.
            print(f"fleet: {n}: rm {s[:8]}... {outcome}", file=sys.stderr)
            continue
        # Report nonfatal removal reasons; a committed tombstone remains resumable.
        print(f"fleet: {n}: rm {s[:8]}... {_rm_deferred_line(outcome)} -- "
              f"{_rm_outcome_note(outcome)}", file=sys.stderr)


def _native_job_ref(sid: str) -> str:
    """Derive a fallback native short id from the full sid's first segment.
    Prefer a captured CLI/roster id when available: a rejected guessed reference
    can look identical to an already-gone session."""
    return sid.split("-", 1)[0] if sid else sid


# Native CLI rc=1 is ambiguous: classify message as gone, daemon-transient,
# or failed. Match the stable dash-free transient phrase rather than punctuation.
# Stop's gone response can include an extra agents-menu hint.
_NATIVE_CLI_GONE_RE = re.compile(r"no job matching", re.I)
_NATIVE_CLI_TRANSIENT_RE = re.compile(r"background service may be restarting", re.I)

# Unreachable background service is machine-wide dispatch failure.
# Match either timeout phrase, allowing wrapper/timeout wording to vary.
# Starting background service alone is normal startup, not failure evidence.
_NATIVE_BG_UNREACHABLE_RE = re.compile(
    r"couldn't reach the background service"
    r"|background service did not become reachable", re.I)

# Dispatch and doctor share the daemon recovery guidance. Timeout does not
# prove a stale lock: a slow healthy daemon can produce it too. Require proof
# the holder is dead before removing its singleton lock, or a second daemon
# could start. Label PowerShell and cmd.exe forms separately for shell syntax.
NATIVE_DAEMON_WEDGE_REMEDY = (
    "REMEDY -- PRECONDITION FIRST: only if NO `claude` session is running and "
    "`claude daemon status` reports `not running`. If a daemon IS live the lock "
    "is not stale and removing it is HARMFUL (it destroys the singleton "
    "guarantee: the next start sees no lock and takes a fresh one). "
    "Then back up and REMOVE the stale lock; PowerShell: "
    "Copy-Item $env:USERPROFILE\\.claude\\daemon.lock $env:TEMP\\daemon.lock.bak; "
    "Remove-Item $env:USERPROFILE\\.claude\\daemon.lock ; cmd.exe: "
    'copy "%USERPROFILE%\\.claude\\daemon.lock" "%TEMP%\\daemon.lock.bak" && '
    'del "%USERPROFILE%\\.claude\\daemon.lock" ; POSIX: '
    "cp ~/.claude/daemon.lock /tmp/daemon.lock.bak && rm ~/.claude/daemon.lock ; "
    "then re-run any dispatch -- the next `claude` start takes a fresh lock. "
    "`claude daemon stop --any` is NOT sufficient: it prints `no daemon running` "
    "and does not clear the lock (receipt: the 2026-07-21 outage). Fleet will "
    "never do this for you -- nothing under ~/.claude is fleet-writable."
)


def _classify_native_cli_result(proc) -> str:
    """Classify a native CLI result as ok, gone, daemon-transient or failed.
    Gone is success-equivalent. Check daemon-transient first: an unavailable
    daemon cannot establish that the requested session has already disappeared."""
    if proc.returncode == 0:
        return "ok"
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if _NATIVE_CLI_TRANSIENT_RE.search(text):
        return "daemon-transient"
    if _NATIVE_CLI_GONE_RE.search(text):
        return "gone"
    return "failed"


def _rm_native_session_status(sid: str, run=subprocess.run, which=shutil.which,
                              timeout: int = 30, ref: str = None) -> tuple:
    """Best-effort remove a native roster entry and its backing job directory.
    Return (ok, outcome); ok/gone succeed, no-claude/error cover unrun attempts.
    Prefer caller-supplied ref from the CLI; otherwise derive a short id. Retry
    with full sid only for an unclassified failure, not gone/daemon-transient.
    Never raise: archival callers report removal failures and continue."""
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError:
        return (False, "no-claude")
    refs = dict.fromkeys((ref or _native_job_ref(sid), sid))
    outcome = "failed"
    for r in refs:
        try:
            proc = run([exe, "rm", r], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return (False, "error")
        outcome = _classify_native_cli_result(proc)
        if outcome in ("ok", "gone"):
            return (True, outcome)
        if outcome == "daemon-transient":
            return (False, outcome)
    return (False, outcome)


def _rm_native_session(sid: str, run=subprocess.run, which=shutil.which,
                       timeout: int = 30) -> bool:
    """Return whether native removal succeeded or the session was already gone."""
    ok, _outcome = _rm_native_session_status(sid, run=run, which=which,
                                             timeout=timeout)
    return ok


# Share the deferral fragment with integration pins that classify transient skips.
NATIVE_RM_DEFERRED_PREFIX = "deferred"


def _rm_deferred_line(outcome: str) -> str:
    """Return the operator-facing removal deferral fragment."""
    return f"{NATIVE_RM_DEFERRED_PREFIX} ({outcome})"


def _rm_outcome_note(outcome: str) -> str:
    """Explain whether a failed native removal should be retried or investigated.
    Hygiene cannot revive a daemon by dispatching a billable worker as a side effect."""
    if outcome == "daemon-transient":
        return ("the background daemon is down/restarting -- it is transient "
                "at 2.1.212 and only a dispatch revives it; RETRYABLE, the "
                "next pass sweeps this sid")
    if outcome == "no-claude":
        return "claude not on PATH"
    if outcome == "error":
        return "the rm subprocess could not be run"
    return "unknown rm failure"


def _archive_move(src: Path, dest: Path, name: str) -> None:
    """Move one source to an exact destination, reporting non-missing I/O errors.
    Skip missing files and continue on other failures. Explicit filenames prevent
    same-basename task and journal files from overwriting each other."""
    if not src.exists():
        return
    try:
        shutil.move(str(src), str(dest))
    except OSError as exc:
        print(f"fleet: {name}: could not archive {src.name}: {exc}", file=sys.stderr)


def cmd_archive(args, run=subprocess.run, which=shutil.which,
                as_autoclean_tier: bool = False) -> int:
    """Archive eligible native workers while retaining registry tombstones.
    Commit archived_at under the lock only if the eligibility snapshot still
    matches; then move evidence and best-effort remove nonlive sids. Commit first
    so interrupted moves leave frozen state and can resume into the same directory.
    Suspicious rosters refuse the entire invocation, including dry-run. Dry-run
    prints eligibility without mutations; pending moves remain already-archived.
    The §7 caller gate applies to the archive verb, including previews. The
    internal as_autoclean_tier argument preserves autoclean's structural exemption;
    it is set only by cmd_autoclean and has no CLI flag. Sid-bearing autoclean
    callers therefore remain exempt even while the supervisor claim is fresh."""
    if not as_autoclean_tier:
        _supervisor_gate("archive", nonce=getattr(args, "nonce", None))
    name = getattr(args, "name", None)
    ttl_hours = getattr(args, "ttl_hours", None)
    if ttl_hours is None:
        ttl_hours = ARCHIVE_TTL_HOURS_DEFAULT
    dry_run = bool(getattr(args, "dry_run", False))
    reap = bool(getattr(args, "reap", False))
    reap_caller_sid = getattr(args, "reap_caller_sid", None)

    with fleet_lock():
        data = load_registry()
        if name is not None:
            if name not in data["workers"]:
                raise FleetCliError(f"unknown worker: {name!r}")
            if not dry_run:
                rec_check = data["workers"][name]
                # Pending moves resume an existing archive; only fully archived targets refuse.
                resumable = (rec_check.get("archived_at") is not None
                            and _archive_resume_pending(name, rec_check))
                if not resumable:
                    refuse_if_archived(name, rec_check, "archive")
            names = [name]
        else:
            names = sorted(data["workers"])
        before = {n: data["workers"][n] for n in names}
        all_workers = data["workers"]  # snapshot for the epoch check (G9)

    # Fully moved tombstones need no roster probe. Pending resumes do: their
    # removal phase must still establish which sids are safe to remove.
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
    verdicts = {n: _archive_eligible(n, before[n], roster_entries, now,
                                    ttl_hours=ttl_hours, reap=reap,
                                    reap_caller_sid=reap_caller_sid)
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

        # Commit only an unchanged eligibility snapshot so a concurrent new turn cannot be archived.
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
            if reap and not _archive_eligible(n, current, roster_entries, now,
                                              reap=True, reap_caller_sid=reap_caller_sid)[0]:
                continue  # claim/mail may have changed without a registry write
            current = dict(current)
            current["archived_at"] = now_iso()
            data["workers"][n] = current
            save_registry(data)
            append_event("archived", n, session_id=sid, retired_count=len(retired))
            archived_count += 1

        _archive_move_and_rm(n, sid, retired, _archive_dest_dir(n),
                             roster_entries, run, which, reap=reap,
                             reap_caller_sid=reap_caller_sid)

    # Resumes finish prior work; do not count or emit a second archived transition.
    for n in resume_names:
        rec = before[n]
        sid = rec.get("session_id")
        retired = list(rec.get("retired_sids", []) or [])
        print(f"fleet: {n}: resuming archive -- completing pending file moves",
              file=sys.stderr)
        _archive_move_and_rm(n, sid, retired, archive_root() / name_fs_stem(n),
                             roster_entries, run, which, reap=reap,
                             reap_caller_sid=reap_caller_sid)

    skipped_count = len(names) - archived_count
    stats = getattr(args, "reap_stats", None)
    if stats is not None:
        stats["archived"] = archived_count
        stats["protected_unread_mail"] = _wave_protected_unread_mail(verdicts)
    print(f"archived {archived_count} worker(s), skipped {skipped_count}")
    return 0


# Autoclean runs on supervisor beats, interface startup and explicit invocation.
# Tier 1 archives; tier 2 removes owned unprotected husks; opt-in tier 3 expires
# registry tombstones. Clean remains the evidence-file deleter.

# Doctor expects autoclean on hourly supervisor beats. Three hours without a
# sweep indicates missed beats while tolerating one slow cycle.
AUTOCLEAN_STALE_RUN_HOURS = 3.0
# Repeated consecutive husk deferrals indicate starvation; a single unavailable
# daemon can be routine. The threshold surfaces sustained cleanup failure.
AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD = 3


def autoclean_stamp_path() -> Path:
    return state_dir() / "autoclean-last-run.json"


def _registry_owned_and_protected_sids(workers: dict) -> tuple:
    """Return all owned sids and the subset in nonarchived registry records.
    Include current/retired ids and tolerate malformed field shapes. Tombstones
    vouch ownership, while nonarchived workers' evidence belongs to archive."""
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
    """Read sid-shaped archive filenames that vouch ownership after registry deletion."""
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
    """Read owned session ids from parseable event lines, surviving registry deletion."""
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


def _sweep_husks(dry_run: bool, run=subprocess.run, which=shutil.which,
                 reap_caller_sid=None) -> tuple:
    """Remove owned roster sessions no longer protected by active fleet records.
    Default-deny unowned sessions. Return (removed, deferred) for durable sweep
    reporting; unavailable/suspicious roster data raises FleetCliError.
    Missing registry with owned evidence refuses: quarantine can erase protection
    without erasing ownership evidence. A fresh home with neither is a no-op.
    A present corrupt registry aborts the run; never continue with empty workers."""
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        raise FleetCliError(f"husk sweep skipped: {payload}")
    with fleet_lock():
        registry_missing = not registry_path().exists()
        data = {"workers": {}} if registry_missing else load_registry()
    # Refuse for any quarantine artifact,
    # registry present or not. A recreated registry can omit protected workers.
    # Rename preserves the old file's mtime, so comparing artifact age against a
    # new registry cannot prove restoration. Clear only after restoring evidence.
    quarantine_artifacts = _quarantine_artifacts()
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

    # Protect the holder's entire sid union under any name, even if its record
    # carries an archived_at field. Holdership alone establishes this protection.
    claim = read_incarnation()
    for name, rec in workers.items():
        if isinstance(rec, dict) and _reap_protection(name, rec, payload, claim,
                                                     reap_caller_sid):
            protected |= _record_sids(rec)
    caller = reap_caller_sid or current_caller_session()
    if caller:
        protected.add(caller)  # even an unregistered caller is not a husk

    removed = []
    deferred = []
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
        if _reap_mail_pending(sid):
            continue
        display = entry.get("name") if isinstance(entry.get("name"), str) else sid[:8]
        if dry_run:
            print(f"husk: would rm {sid} ({display})")
            continue
        # Use the roster id so a durable gone-success event cannot rest on a guessed ref.
        entry_ref = entry.get("id")
        ok, outcome = _rm_native_session_status(
            sid, run=run, which=which,
            ref=entry_ref if isinstance(entry_ref, str) and entry_ref else None)
        if ok:
            # Already gone satisfies removal even if the fetched roster snapshot was stale.
            append_event("husk_removed", display, session_id=sid)
            print(f"husk: rm {sid} ({display}) [{outcome}]")
            removed.append(sid)
        else:
            deferred.append(sid)
            print(f"husk: rm {sid} ({display}) {_rm_deferred_line(outcome)} -- "
                  f"{_rm_outcome_note(outcome)}", file=sys.stderr)
    if deferred:
        # Return deferrals for the durable stamp/event doctor reads, as well as stderr.
        print(f"husk: {len(deferred)} husk(s) left on the roster for the next "
              f"pass: {', '.join(s[:8] for s in deferred)}", file=sys.stderr)
    return removed, deferred


def _expire_tombstones(expire_hours: float, dry_run: bool) -> list:
    """Expire opted-in tombstones older than the horizon only after evidence moves finish.
    Return removed (name, sid) pairs. Delete no files; archive evidence remains."""
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
    """Run isolated archive/reap, husk-sweep and optional tombstone-expiry tiers.
    Ordinary tier errors are reported and return exit 1. RegistryCorruptError
    aborts the whole run: a quarantine rename makes later sweeps unsafe.
    Direct callers may override fleet_home with an existing directory; main()
    resolves the global flag first and requires an initialized home.
    """
    fleet_home_override = getattr(args, "fleet_home", None)
    if fleet_home_override:
        # Resolve and validate before writes: relative or missing homes can create phantom state.
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
        archive_args.reap = bool(getattr(args, "reap", True))
        archive_args.reap_stats = getattr(args, "reap_stats", None)
        archive_args.reap_caller_sid = getattr(args, "reap_caller_sid", None)
        # Carry the sweep exemption across cmd_archive: beat callers have sids,
        # and the interface caller has no nonce.
        archive_rc = cmd_archive(archive_args, run=run, which=which,
                                 as_autoclean_tier=True)
        if archive_rc != 0:
            errors.append(f"archive: exit {archive_rc}")
    except RegistryCorruptError:
        raise  # F1: run-abort, never tier-skip
    except Exception as exc:  # noqa: BLE001 -- tier isolation (D3)
        errors.append(f"archive: {type(exc).__name__}: {exc}")
        print(f"autoclean: archive tier failed: {exc}", file=sys.stderr)

    husks, husks_deferred = [], []
    try:
        husks, husks_deferred = _sweep_husks(
            dry_run, run=run, which=which,
            reap_caller_sid=getattr(args, "reap_caller_sid", None))
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

    # Report deferred work in stamp/event/summary without making a transient daemon failure fatal.
    summary = {"ts": now_iso(), "dry_run": dry_run, "archive_rc": archive_rc,
               "husks_removed": len(husks), "husks_deferred": len(husks_deferred),
               "tombstones_expired": len(tombstones),
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
                         husks_deferred=len(husks_deferred),
                         tombstones_expired=len(tombstones), errors=errors)
        except OSError as exc:
            print(f"autoclean: event append failed: {exc}", file=sys.stderr)
    print(f"autoclean: husks_removed={len(husks)} "
          f"husks_deferred={len(husks_deferred)} "
          f"tombstones_expired={len(tombstones)}"
          f" errors={len(errors)}{' (dry-run)' if dry_run else ''}")
    return 1 if errors else 0


SUPERVISOR_REAP_RULE = (
    "Fleet automatically reaps at supervisor boot, handoff completion and release: "
    "landed or abandoned lanes with an idle session and no unread mail, "
    "daemon-confirmed dead rows, and predecessor supervisor bodies outside the "
    "current claim, regardless of age; unread mail and any live PID always protect "
    "a row. The calling body's SID union and rows with overlapping SID ownership "
    "are also protected. Record landing as lane_state=landed or abandoned in the registry "
    "(or a matching outcome kind); a result alone is not a landing. "
    "Before any dispatch, allow at most 3 live worker sessions total across Claude "
    "and Codex (a Codex lane counts as one), and require at least 1.5 GB available "
    "memory. Reaping is automatic; supervisors do not run fleet autoclean or fleet "
    "archive by hand. "
    "Output is compressed: facts, numbers, paths, commands. No preamble, recap, "
    "tool narration or essays; one line per finding. A checkpoint is at most three "
    "model-written lines plus computed state; a lane report is the structured "
    "result plus at most 40 lines; errors are quoted exact, shortest line only."
)


def _supervisor_reap(run=subprocess.run, which=shutil.which, caller_sid=None,
                     reap_stats=None) -> tuple:
    """Run best-effort maintenance after releasing the claim lock.
    Unreadable registries are not quarantined; maintenance failures must not
    strand a minted nonce. Return the reap count and any diagnostic.
    """
    ok, reason, data = _read_registry_readonly()
    if not ok:
        return 0, f"registry {reason}"
    _reap_current_supervisor_forks(run=run, which=which, caller_sid=caller_sid)
    stats = {} if reap_stats is None else reap_stats
    args = argparse.Namespace(reap=True, reap_stats=stats, dry_run=False,
                              reap_caller_sid=caller_sid)
    try:
        with redirect_stdout(io.StringIO()):
            rc = cmd_autoclean(args, run=run, which=which)
        return stats.get("archived", 0), "autoclean incomplete; see run stamp" if rc else None
    except Exception as exc:
        return stats.get("archived", 0), f"{type(exc).__name__}: {exc}"


def _supervisor_reap_line(run=subprocess.run, which=shutil.which, caller_sid=None) -> str:
    count, error = _supervisor_reap(run=run, which=which, caller_sid=caller_sid)
    return f"reaped: {count} rows" + (f" (deferred: {error})" if error else "")


# CLI: doctor returns (name, ok, message) per check. ASCII PASS/FAIL avoids
# UnicodeEncodeError on Windows consoles; note-only checks keep ok=True.

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
    """Bound an untrusted version string before embedding it in a diagnostic."""
    s = str(s)
    return s if len(s) <= limit else s[:limit] + "..."


def _doctor_check_pin_version(which=shutil.which, run=subprocess.run):
    """Compare parsed live and pinned Claude versions; fail only on a mismatch.
    Missing, unreadable or unparseable versions produce notes, since an invalid
    record is not evidence of a broken native contract. Normalize both versions
    so raw CLI formatting cannot create a false mismatch.
    """
    pin = read_pin_pass()
    if pin is None:
        return ("pin-version", True,
                "no pin-test pass recorded -- run FLEET_LIVE=1 python -m pytest "
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
    """Collect command strings from recognized hook groups, skipping malformed groups."""
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
    """Extract whitespace-delimited *.py tokens, stripping surrounding quotes.
    Rendered commands quote paths; retaining a quote would make exists() test
    a different filename. This parser does not join tokens across spaces.
    """
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
    if not info["template_exists"]:
        # A missing tracked template is a broken checkout, distinct from a stale instance.
        return ("instance-freshness", False,
                f"{template_settings_path()} missing -- can't verify the "
                f"instance against it; restore the template")
    if info["stale"]:
        if not info["instance_exists"]:
            return ("instance-freshness", False, "worker-settings.json instance missing -- run `fleet init`")
        return ("instance-freshness", False,
                "worker-settings.json instance is older than the template -- run `fleet init`")
    return ("instance-freshness", True, "instance is up to date with the template")


def _fleet_grants(settings_data) -> list:
    """Return permissions entries mentioning fleet from every bucket.
    A deny entry can fence off an allow grant, so checking allow alone is unsafe.
    """
    out = []
    permissions = settings_data.get("permissions") if isinstance(settings_data, dict) else None
    if not isinstance(permissions, dict):
        return out
    for bucket in sorted(permissions):
        entries = permissions.get(bucket)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str) and "fleet" in entry:
                out.append(f"{bucket}:{entry}")
    return out


def _doctor_check_instance_grants():
    """Compare rendered fleet grants with the template, in both directions.
    Fail on widened or missing grants. Content checks detect hand edits even
    when the instance's mtime is newer; unrelated operator grants are ignored.
    """
    template_path = template_settings_path()
    instance_path = instance_settings_path()
    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Distinguish a missing tracked template from a transient read failure.
        return ("instance-grants", False,
                f"{template_path} missing -- can't verify the instance's "
                f"fleet grants against it; restore the template")
    except (OSError, json.JSONDecodeError) as exc:
        return ("instance-grants", True,
                f"template unreadable ({exc}) -- grant comparison skipped")
    try:
        instance = json.loads(instance_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ("instance-grants", False,
                f"{instance_path} missing -- run `fleet init`")
    except (OSError, json.JSONDecodeError) as exc:
        return ("instance-grants", False,
                f"{instance_path} does not parse as JSON: {exc}")
    want, have = _fleet_grants(template), _fleet_grants(instance)
    if want == have:
        return ("instance-grants", True,
                f"instance fleet grants match the template: {have or 'none'}")
    extra = [e for e in have if e not in want]
    lost = [e for e in want if e not in have]
    detail = []
    if extra:
        detail.append(f"instance carries fleet grant(s) the template does not: "
                      f"{extra} -- a grant nobody issued is reaching every worker")
    if lost:
        detail.append(f"instance is missing the template's fleet grant(s): {lost} "
                      f"-- workers cannot run the tool they are taught")
    return ("instance-grants", False,
            "; ".join(detail) + " -- re-run `fleet init` to restore the "
            "template's grants")


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
    # Smoke-test the installed hook script.
    script = INSTALL_ROOT / "bin" / "hooks" / "posttooluse_mailbox.py"
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
    # Smoke-test the installed hook script.
    script = INSTALL_ROOT / "bin" / "hooks" / "stop_mailbox.py"
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
    # Orphaned files belong to _doctor_check_orphaned_claims; this checks idle-worker mail.
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
    """Note parks past their reset horizon, weekly parks and unknown horizons.
    These remain PASS because waiting on a usage limit is expected state.
    """
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
    """Note unarchived records without native dispatch support.
    Such records support retirement operations only; archived rows need no notice.
    """
    legacy = sorted(name for name, rec in workers.items()
                    if not is_native(rec) and rec.get("archived_at") is None)
    if legacy:
        return ("legacy-mix", True,
                f"{len(legacy)} pre-pivot worker(s): {', '.join(legacy)} -- "
                "unmanageable by this build; kill/clean/archive only")
    return ("legacy-mix", True, "no pre-pivot workers")


def _doctor_check_dead_suspected(workers: dict):
    """Note dead-suspected rows in the supplied snapshot without recomputing.
    The verdict is advisory and recomputable, never a sticky respawn trigger.
    """
    names = sorted(name for name, rec in workers.items() if rec.get("status") == "dead-suspected")
    if names:
        return ("dead-suspected", True,
                f"{len(names)} dead-suspected worker(s): {', '.join(names)} -- no outcome record; "
                "inspect via fleet peek/result, then kill or respawn")
    return ("dead-suspected", True, "no dead-suspected workers")


def _doctor_check_permission_stalls(workers: dict, which=shutil.which, run=subprocess.run):
    """Fail for fresh roster evidence of an unattended permission stall.
    The threshold and attached-session exclusion filter routine prompts; the
    failure clears when the live condition ends. An unavailable roster returns
    a PASS note saying NOT CHECKED, since absence of evidence is not health.
    """
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        return ("permission-stalls", True, f"NOT CHECKED -- roster unavailable ({payload})")
    stalls = _permission_stalls(workers, payload)
    if not stalls:
        return ("permission-stalls", True,
                f"no worker parked on a permission prompt >"
                f"{PERMISSION_STALL_SECONDS / 60:.0f}m")
    detail = " | ".join(_permission_stall_line(*stall) for stall in stalls)
    return ("permission-stalls", False,
            f"{len(stalls)} worker(s) parked on a permission prompt with nobody "
            f"to answer it -- these render as `working` and will never finish: "
            f"{detail}")


def _doctor_check_permission_denials(workers: dict):
    """Note durable session denial counts and each worker's permission mode.
    Keep PASS: durable evidence can outlive its incident. Skip archived rows,
    zero counts and unknown counts; unknown does not mean measured zero.
    """
    denied = []
    for name, rec in sorted(workers.items()):
        if not isinstance(rec, dict) or rec.get("archived_at") is not None:
            continue
        count = _session_permission_denials(name, rec.get("session_id"))
        if isinstance(count, int) and count > 0:
            denied.append((name, rec.get("mode"), count))
    if not denied:
        # No measured counts must not read as measured absence of denials.
        return ("permission-denials", True,
                "no live worker has a measured tool-permission denial")
    detail = " | ".join(
        f"{n} (mode={m if isinstance(m, str) else '?'}): {c} denied"
        for n, m, c in denied)
    return ("permission-denials", True,
            f"{len(denied)} worker(s) had tool calls refused by the permission "
            f"layer -- a worker denied its first Bash call goes idle on turn 1 "
            f"and is otherwise indistinguishable from one that finished fast: "
            f"{detail}. Read the report (`fleet result <name>`), then respawn "
            f"under a mode that can run the brief or fix the allow-list")


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
    """Note orphaned claim files, mailboxes and token-ceiling files.
    With workers=None, skip scans requiring registered sid membership. Mailbox
    notes include their first line to identify stranded mail without dumping it.
    """
    parts = []
    mbox_dir = mailbox_dir()
    if mbox_dir.exists():
        # A hook can die between claim and deletion regardless of worker status.
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


DAEMON_ENV_LEAK_REMEDY = (
    "The stamp comes from the machine-wide `claude` daemon, which SUBSTITUTES "
    "the environment of whichever `--bg` dispatch started it into every session "
    "it hosts afterwards -- it does not add to this dispatch's environment, it "
    "replaces it wholesale, which is why the value you see may name a long-dead "
    "body and why it can be missing entirely on a body fleet certainly "
    "launched. Fleet cannot fix it from inside a hosted session: let the daemon "
    "idle-exit (no `--bg` sessions alive) so the next dispatch starts a fresh "
    "one, or ensure the supervisor's own dispatch is the one that starts it. "
    "NO OBSERVATION OF THIS VARIABLE IS EVIDENCE ABOUT THIS BODY, IN EITHER "
    "DIRECTION (claim-nonce §18, ratified 2026-07-30) -- it is a WITNESS: "
    "worth reporting when it disagrees with the registry, never worth "
    "believing over it. EXACTLY ONE GUARD STILL KEYS ON IT AND THAT IS A KNOWN "
    "LIVE HOLE, not a sound read: three-tier §11.3 ND4c exempts a session with "
    f"no stamp from the {SUPERVISOR_BAND_HARD_TOKENS:,}-token dispatch ceiling, "
    "so a body whose daemon was "
    "cold-started unstamped is exempt from a ceiling that applies to it. The "
    "re-grounding is ordered and BLOCKED on an operator ruling (it collides "
    "with ND4b on the same input); the accounting and the three candidates are "
    "in claim-nonce §18.4. The sid itself is NOT affected -- the vendor stamps "
    "each hosted session's own sid over the substituted environment (§18.2, "
    "closed by counting), which is what makes the registry union readable at "
    "all")


def _doctor_check_identity_witness(workers: dict):
    """Compare the FLEET_WORKER witness with registry-resolved identity.
    Fail on disagreement or ambiguity. An unresolved sid is note-only because
    dispatch creates a window before the registry records it. Never raise on
    field-shape drift; the environment witness does not decide identity.
    """
    witness = (os.environ.get("FLEET_WORKER") or "").strip()
    sid = current_caller_session()
    ident = _acting_worker_identity(sid=sid, registry={"workers": workers})
    verdict = ident["verdict"]

    if verdict == IDENTITY_AMBIGUOUS:
        return ("identity-witness", False,
                f"AMBIGUOUS identity: session id {sid!r} is carried by "
                f"{len(ident['matches'])} registry records "
                f"({', '.join(repr(n) for n in ident['matches'])}). One session "
                f"cannot be two workers, so at least one record's sid union is "
                f"wrong -- fleet abstains from judging this body's identity "
                f"until it is resolved (no verb is refused because of it). "
                f"Inspect those records in state/fleet.json and retire the "
                f"stale one (`fleet clean`, or edit the registry out of band)"
                + (f". FLEET_WORKER witness: {witness!r}" if witness else ""))

    if not witness:
        # Registry identity and the environment witness disagree. Daemon substitution
        # can omit a dispatch stamp; absence does not imply a stripper or tampering.
        # Resolved identity earns a failure; unresolved unstamped interface shells do not.
        if verdict == IDENTITY_RESOLVED:
            return ("identity-witness", False,
                    f"no FLEET_WORKER stamp in this environment, but the "
                    f"registry resolves this session's own id ({sid!r}) to "
                    f"{ident['name']!r} -- so a fleet dispatch DID launch this "
                    f"body and the stamp it wrote is not here. BELIEVE THE "
                    f"REGISTRY: you are {ident['name']!r}. Nothing is stripping "
                    f"the variable -- the hosting daemon SUBSTITUTES its own "
                    f"frozen first-dispatch environment into every session it "
                    f"hosts, so a daemon cold-started by an unstamped launcher "
                    f"produces exactly this, and no observation of "
                    f"FLEET_WORKER (present, absent or blank) is evidence about "
                    f"this body (claim-nonce §18). WHAT IT STILL COSTS, and it "
                    f"is why this row is red rather than a note: three-tier "
                    f"§11.3 ND4c exempts a stamp-less session from the "
                    f"{SUPERVISOR_BAND_HARD_TOKENS:,}-token "
                    f"dispatch ceiling, so until that exemption is re-grounded "
                    f"this body is exempt from a ceiling the registry says "
                    f"applies to it. The re-grounding is ordered and BLOCKED on "
                    f"an operator ruling (claim-nonce §18.4). Remedy for the "
                    f"witness itself: let the daemon idle-exit so the next "
                    f"dispatch starts a fresh one.")
        return ("identity-witness", True,
                f"no FLEET_WORKER stamp in this environment; registry verdict "
                f"for sid {sid!r}: {verdict}"
                + (f" ({ident['name']!r})" if ident["name"] else ""))

    if verdict == IDENTITY_UNRESOLVED:
        return ("identity-witness", True,
                f"NOTE: FLEET_WORKER={witness!r} but no registry record claims "
                f"this session's own id ({sid!r}), so the witness cannot be "
                f"checked against anything. Expected during a body's own "
                f"dispatch window (the record is written before the session "
                f"exists and the sid is filled in when the dispatch returns), "
                f"and expected for any session fleet did not launch. If it "
                f"persists for a body that IS fleet-launched, the record's sid "
                f"was never filled in -- inspect state/fleet.json. "
                + DAEMON_ENV_LEAK_REMEDY)

    if witness == ident["name"]:
        return ("identity-witness", True,
                f"the FLEET_WORKER witness agrees with the registry (both name "
                f"{witness!r} for sid {sid!r})")

    named = witness in workers
    return ("identity-witness", False,
            f"LEAK: the FLEET_WORKER witness names a DIFFERENT record than this "
            f"session's own id resolves to. Witness: {witness!r} "
            f"({'a registry record, status ' + str(workers.get(witness, {}).get('status')) if named else 'no registry record of that name'}). "
            f"Registry verdict for my sid {sid!r}: {ident['name']!r}. "
            f"The registry is the judge and {ident['name']!r} is who this "
            f"session is. " + DAEMON_ENV_LEAK_REMEDY)


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
    # Retired sids remain fleet-tracked even when best-effort removal leaves them
    # in the roster. Normalize malformed fields rather than spreading a string into characters.
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


def _autoclean_deferral_streak() -> tuple:
    """Return (consecutive deferring runs, latest husk count, first timestamp).
    Read newest autoclean_run events backward until a run deferred nothing.
    Skip dry runs: they reclaim nothing. The streak measures outstanding work,
    not daemon reachability; unreadable history degrades to (0, 0, None).
    """
    try:
        raw = events_path().read_text(encoding="utf-8")
    except OSError:
        return (0, 0, None)
    runs = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or '"autoclean_run"' not in line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if rec.get("kind") != "autoclean_run" or rec.get("dry_run"):
            continue
        deferred = rec.get("husks_deferred")
        if not isinstance(deferred, int) or isinstance(deferred, bool):
            continue  # pre-M1 event: no data, cannot vouch either way
        runs.append((deferred, rec.get("ts")))
    streak, husks, since = 0, 0, None
    for deferred, ts in reversed(runs):
        if deferred <= 0:
            break
        if streak == 0:
            husks = deferred
        streak += 1
        since = ts or since
    return (streak, husks, since)


def _doctor_check_autoclean():
    """Note the autoclean run stamp's age, errors and quarantine artifacts.
    Persistent husk deferrals are advisory; a single deferral is routine.
    Never fail doctor for inactivity or a transient daemon. Name the supervisor
    beat and interface startup ritual so a stale note identifies its drivers.
    """
    age_h, run_errors = None, []
    husks_deferred = 0
    try:
        raw = json.loads(autoclean_stamp_path().read_text(encoding="utf-8"))
        last = _parse_iso(raw.get("ts"))
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        errs = raw.get("errors")
        if isinstance(errs, list):
            run_errors = [str(e) for e in errs if e]
        deferred_raw = raw.get("husks_deferred")
        if isinstance(deferred_raw, int) and not isinstance(deferred_raw, bool):
            husks_deferred = deferred_raw
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    extras = []
    if run_errors:
        extras.append(f"last run reported {len(run_errors)} error(s): "
                      f"{run_errors[0][:120]}")
    streak, streak_husks, streak_since = _autoclean_deferral_streak()
    if husks_deferred > 0 and streak >= AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD:
        since = f" since {streak_since}" if streak_since else ""
        extras.append(
            f"husk sweep DEFERRED on the last {streak} consecutive runs "
            f"({streak_husks} husk(s) on the most recent) -- the background "
            f"daemon has not been reachable{since}. A single deferral is "
            f"routine (the daemon is transient at 2.1.212 and idle-exits once "
            f"no session holds it open), but {streak} in a row means this tier "
            f"is starving: the husks stay on the roster and nothing is "
            f"reclaiming them. Check `claude daemon status`")
    artifacts = _quarantine_artifacts()
    if artifacts:
        extras.append(f"quarantine artifact present ({artifacts[-1].name}) -- "
                      f"husk sweep is refusing itself (NEW-1); restore the "
                      f"quarantined data, then remove the artifact")
    suffix = ("; " + "; ".join(extras)) if extras else ""

    # Name the sweep drivers so a stale stamp has an actionable owner.
    drivers = ("the supervisor runs it on its watchtower beat, the interface "
               "in its startup ritual")
    if age_h is None:
        return ("autoclean", True,
                f"no run recorded yet ({autoclean_stamp_path().name} absent or "
                f"unreadable) -- {drivers}{suffix}")
    if age_h > AUTOCLEAN_STALE_RUN_HOURS:
        return ("autoclean", True,
                f"last run {age_h:.1f}h ago, past the "
                f"{AUTOCLEAN_STALE_RUN_HOURS:.0f}h beat window -- THE BEAT IS "
                f"NOT BEATING: {drivers}, so neither tier has run in that "
                f"window. Check `fleet sup-status`{suffix}")
    return ("autoclean", True, f"last run {age_h:.1f}h ago{suffix}")


def _doctor_check_tzdata():
    """Note whether local-time usage-limit horizons can resolve via zoneinfo.
    Missing timezone data narrows parsing to explicit UTC/ISO horizons; it does
    not break dispatch and therefore produces a PASS note.
    """
    import zoneinfo
    try:
        zoneinfo.ZoneInfo("Asia/Qyzylorda")
    except Exception as exc:
        return ("tzdata", True,
                f"zoneinfo cannot resolve a named zone ({type(exc).__name__}: {exc}) -- "
                f"local-format limit-signal parsing (\"resets 4:40am (Zone/City)\") will "
                f"null-park until tz data is installed: py -3.13 -m pip install tzdata")
    return ("tzdata", True, "zoneinfo resolves named zones (tz data present)")

# Daemon-wedge evidence: daemon.lock has integer pid and UTC epoch-millisecond
# startedAt; daemon.log has UTC-stamped lock-race refusal lines. Read only these
# two files, with no subprocess. Ignore procStart, which uses a different time base.
_DAEMON_LOG_TS_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)Z\]")
_DAEMON_LOCK_RACE_RE = re.compile(
    r"another daemon won the lock race \(pid=(\d+)\)", re.I)

# One sufficiently late refusal proves persistent lock failure. Refusals are
# demand-driven; requiring repeated dispatch failures would delay diagnosis.
DAEMON_WEDGE_MIN_REFUSALS = 1
DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS = 300.0
# The span threshold is only for degraded evidence without a usable startedAt.
# The primary age gate must not vary with the operator's retry cadence.
DAEMON_WEDGE_MIN_SPAN_SECONDS = 300.0


def _parse_daemon_log_ts(line: str):
    """Parse a UTC daemon-log timestamp with optional fractional seconds.
    Use strptime so trailing Z works on the Python 3.10 floor as well.
    """
    m = _DAEMON_LOG_TS_RE.match(line)
    if not m:
        return None
    stamp = m.group(1)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _doctor_check_daemon_wedge(lock_path=None, log_path=None):
    """Fail when log refusals establish that the current daemon lock is stale.
    Only read daemon.lock and daemon.log: subprocess probes may start a daemon.
    Match the lock pid and require refusals sufficiently after its startedAt;
    signed age excludes older locks' evidence. One late refusal suffices because
    refusals are demand-driven. No attempted dispatch means no detection.
    If startedAt is unusable, require repeated refusals spanning the degraded
    window instead. Other unknown evidence produces a PASS note. Never mutate
    vendor state. Roster mtime is event-driven and cannot serve as a heartbeat.
    """
    lock_path = Path(lock_path) if lock_path is not None else claude_daemon_lock_path()
    log_path = Path(log_path) if log_path is not None else claude_daemon_log_path()
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ("daemon-wedge", True,
                "no ~/.claude/daemon.lock -- no daemon singleton to be stale")
    except (json.JSONDecodeError, ValueError):
        return ("daemon-wedge", True,
                "~/.claude/daemon.lock is not readable JSON -- skipped")
    if not isinstance(lock, dict):
        return ("daemon-wedge", True,
                "~/.claude/daemon.lock has an unexpected shape -- skipped")
    pid, started_ms = lock.get("pid"), lock.get("startedAt")
    # Reject bool: True is an int and would incorrectly match refusals naming pid 1.
    if not isinstance(pid, int) or isinstance(pid, bool):
        return ("daemon-wedge", True,
                "~/.claude/daemon.lock carries no usable pid -- skipped")
    started = None
    if isinstance(started_ms, (int, float)) and not isinstance(started_ms, bool):
        try:
            started = datetime.fromtimestamp(started_ms / 1000.0, timezone.utc)
        except (OSError, OverflowError, ValueError):
            started = None  # NaN, +-inf, out-of-range epoch -> F6 degraded path

    refusals = []
    for line in _read_tail_lines(log_path):
        m = _DAEMON_LOCK_RACE_RE.search(line)
        if m is None or int(m.group(1)) != pid:
            continue
        ts = _parse_daemon_log_ts(line)
        if ts is None:
            continue  # undateable -> INDETERMINATE, never evidence
        refusals.append(ts)

    if started is None:
        # Without lock age, repeated same-pid refusals separated in time rule out a startup race.
        return _daemon_wedge_degraded_verdict(pid, refusals)

    held_since = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    # SIGNED, not absolute: a refusal older than this lock belongs to a previous
    # one and must never indict it.
    late = [ts for ts in refusals
            if (ts - started).total_seconds() >= DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS]

    if len(late) < DAEMON_WEDGE_MIN_REFUSALS:
        return ("daemon-wedge", True,
                f"daemon.lock held by pid {pid} since {held_since}; "
                f"{len(late)} late lock-race refusal(s) in the daemon.log "
                f"tail (< {DAEMON_WEDGE_MIN_REFUSALS}) -- no wedge signature")
    # No span gate here: more late refusals must never weaken the age-based verdict.
    # The degraded path alone needs a span because it cannot compute lock age.
    newest = max(late)
    age_h = (newest - started).total_seconds() / 3600.0
    return ("daemon-wedge", False,
            f"the Claude background daemon looks WEDGED: {len(late)} daemon "
            f"start(s) were refused by ~/.claude/daemon.lock (pid {pid}, held "
            f"since {held_since}); the most recent, at "
            f"{newest.strftime('%Y-%m-%dT%H:%M:%SZ')}, was refused by a lock "
            f"already {age_h:.1f}h old -- i.e. that pid is no longer a daemon "
            f"(a recycled pid still looks alive), so EVERY `claude --bg` "
            f"dispatch is failing machine-wide: no spawn, no respawn, no steer, "
            f"no resume. {NATIVE_DAEMON_WEDGE_REMEDY}")


def _daemon_wedge_degraded_verdict(pid, refusals):
    """Evaluate refusals when the lock's startedAt cannot supply an age gate.
    Require two matching-pid refusals spanning DAEMON_WEDGE_MIN_SPAN_SECONDS;
    this separates persistent failure from startup races at reduced confidence.
    """
    if len(refusals) < 2:
        return ("daemon-wedge", True,
                f"~/.claude/daemon.lock (pid {pid}) carries no usable startedAt, "
                f"so the lock-age gate cannot run; {len(refusals)} lock-race "
                f"refusal(s) naming it (< 2) -- not enough for a degraded "
                f"verdict")
    span = (max(refusals) - min(refusals)).total_seconds()
    if span < DAEMON_WEDGE_MIN_SPAN_SECONDS:
        return ("daemon-wedge", True,
                f"~/.claude/daemon.lock (pid {pid}) carries no usable startedAt, "
                f"so the lock-age gate cannot run; {len(refusals)} refusals "
                f"naming it span only {span:.0f}s -- one burst, not a wedge")
    return ("daemon-wedge", False,
            f"the Claude background daemon looks WEDGED (DEGRADED confidence): "
            f"~/.claude/daemon.lock (pid {pid}) carries no usable startedAt, so "
            f"the lock-age gate could not run -- but {len(refusals)} daemon "
            f"starts were refused by it across {span / 3600.0:.1f}h, most "
            f"recently at {max(refusals).strftime('%Y-%m-%dT%H:%M:%SZ')}, and a "
            f"genuine startup race resolves in under a second. Confirm with "
            f"`claude daemon status` before acting. {NATIVE_DAEMON_WEDGE_REMEDY}")


def _doctor_check_hook_errors():
    """Fail on a nonempty hook-errors log and show its tail.
    Hooks must exit safely even when their durable write fails; doctor must
    surface that loss. The log is not rotated, so the failure persists until
    the operator acts and clears the named file.
    """
    lines = _hook_error_lines()
    if not lines:
        return ("hook-errors", True, "no swallowed hook errors logged")
    tail = lines[-_HOOK_ERROR_TAIL:]
    return ("hook-errors", False,
            f"{len(lines)} swallowed hook error(s) logged -- a hook abandoned a "
            f"durable write (mailbox delivery, journal landmark or worker RESULT) "
            f"and exited 0 anyway; last {len(tail)}: " + " | ".join(tail)
            + " -- act on these, then clear state/hook-errors.log to return "
              "this row to PASS")


_KNOWN_HOOK_EVENTS = frozenset({"PostToolUse", "Stop", "PostCompact"})


def _doctor_check_hook_registration():
    """Validate registered hook event names, command paths and JSON shape.
    A hooks-less instance passes: the instance check owns missing wiring, while
    this check catches invalid registrations that synthetic smoke tests miss.
    """
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


def _doctor_check_registry(error, repaired: bool, quarantined=None,
                           attempted: bool = False):
    """Report registry readability and the actual quarantine outcome.
    Run first so later empty worker checks cannot imply health after a read
    failure. Bare absence is normal before the first save; quarantine artifacts
    make absence suspect. Distinguish successful rename, failed rename and
    failed read, since each needs a different repair.
    """
    if error is None:
        path = registry_path()
        if path.exists():
            return ("registry", True, f"{path} is readable")
        artifacts = _quarantine_artifacts()
        if artifacts:
            return ("registry", False,
                    f"{path} does NOT exist -- it was quarantined aside to "
                    f"state/{artifacts[-1].name}, so every worker-keyed check "
                    f"below ran against an EMPTY registry and passed VACUOUSLY. "
                    f"Any session that registry tracked is now untracked. "
                    f"Restore what the artifact holds, then remove it (the same "
                    f"remedy the husk sweep asks for)")
        return ("registry", True,
                f"{path} does not exist yet -- no worker has been spawned on "
                f"this home. Every worker-keyed check below has nothing to check")
    if quarantined is not None:
        return ("registry", False,
                f"registry was corrupt and has been quarantined -- {error}")
    if attempted:
        # The corrupt content was read but its rename failed; remedy file access, not reading.
        return ("registry", False,
                f"--repair TRIED to quarantine the registry and the RENAME "
                f"FAILED -- {error}. The file is still at {registry_path()} "
                f"under its own name and still unparseable, so every verb that "
                f"loads it keeps refusing. Free the file -- a process holding "
                f"it open, an AV or backup handle, a deny-write ACL -- and "
                f"rerun; nothing improves until the rename lands")
    if repaired:
        return ("registry", False,
                f"--repair attempted NO rename -- {error}. The file could not "
                f"be READ at all, so nothing classified it as corrupt and there "
                f"was nothing to rename aside; {registry_path()} is untouched "
                f"and this is NOT a claim that its contents are sound. Fix what "
                f"is denying the read (an ACL, a process holding the file open, "
                f"an I/O error) and rerun")
    return ("registry", False,
            f"{error}; every worker-keyed check below ran against an EMPTY "
            f"registry. Rerun as `fleet doctor --repair` to quarantine it "
            f"(renames it aside to state/fleet.json.corrupt.<ts>)")


def cmd_doctor(args, which=shutil.which, run=subprocess.run) -> int:
    """Run health checks and return nonzero if any check fails.
    Report only by default; --repair permits quarantine under fleet_lock.
    Capture a corrupt registry as a diagnostic and continue other checks.
    Snapshot under the lock, then run checks outside it so subprocesses cannot
    starve concurrent fleet commands.
    """
    # In-process callers may omit repair; absence must retain report-only behavior.
    repair = bool(getattr(args, "repair", False))
    registry_error = None
    # Track the observed quarantine outcome separately from the repair request.
    registry_quarantined = None
    registry_rename_attempted = False
    try:
        if repair:
            with fleet_lock():
                data = load_registry()          # the ONE quarantine site left
        else:
            # The diagnostic row supplies its own more precise repair hint.
            data = read_registry_no_repair(hint=False)
    except RegistryCorruptError as exc:
        # Registry corruption is a finding here, so continue other diagnostic rows.
        # Mutating callers must instead abort before writing against untrusted state.
        registry_error = str(exc)
        registry_quarantined = getattr(exc, "quarantined", None)
        registry_rename_attempted = bool(getattr(exc, "attempted", False))
        data = {"workers": {}}
    workers = data.get("workers", {})

    check_calls = [
        functools.partial(_doctor_check_registry, registry_error, repair,
                          registry_quarantined, registry_rename_attempted),
        functools.partial(_doctor_check_claude_version, which=which, run=run),
        functools.partial(_doctor_check_pin_version, which=which, run=run),
        functools.partial(_doctor_check_instance_settings),
        functools.partial(_doctor_check_instance_freshness),
        # Pair content-grant validation with freshness: mtime alone misses hand edits.
        functools.partial(_doctor_check_instance_grants),
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
        # Keep worker-action rows together; tzdata owns the final check slot.
        functools.partial(_doctor_check_permission_stalls, workers, which=which, run=run),
        # Pair durable denials with live permission stalls; tzdata remains last.
        functools.partial(_doctor_check_permission_denials, workers),
        functools.partial(_doctor_check_orphaned_claims, workers=workers),
        functools.partial(_doctor_check_identity_witness, workers),
        functools.partial(_doctor_check_claude_agents, workers, which=which, run=run),
        functools.partial(_doctor_check_daemon_wedge),
        functools.partial(_doctor_check_autoclean),
        functools.partial(_doctor_check_hook_errors),
        functools.partial(_doctor_check_supervisor_claim),
        functools.partial(_doctor_check_supervisor_wedge, which=which, run=run),
        functools.partial(_doctor_check_supervisor_handoff),
        functools.partial(_doctor_check_pending_decision),
        functools.partial(_doctor_check_tzdata),
    ]

    # Isolate each check: unexpected field shapes must produce one FAIL row,
    # not suppress every remaining diagnosis.
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


# Outcome store: name-keyed JSONL with sid-keyed fallback for unresolved hooks.
# Stop writes result; fleet writes stop tombstones because operator stop fires no hook.

OUTCOME_FRESH_SLACK_SECONDS = 5.0
OUTCOME_RESULT_TEXT_MAX = 20000
TOMBSTONE_KINDS = ("killed", "interrupted", "stopped")


def _atomic_append_bytes(path: Path, data: bytes) -> None:
    """Append bytes in one syscall through PLATFORM; partial writes raise OSError.
    The backend uses FILE_APPEND_DATA on Windows and O_APPEND on POSIX.
    """
    PLATFORM.atomic_append_bytes(path, data)


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


# Permission denials are durable harness toolDenialKind counts written by the
# Stop hook, so file-only views can read them. Permission stalls require a live
# roster. Do not infer denials from model-written report text: it may quote an
# error without having encountered one, or omit a refusal entirely.

# Statusline reads must stay bounded as outcome files grow. Newest records are
# at the tail; full-file parsing belongs to explicit outcome views.
OUTCOME_TAIL_BYTES = 65536


def _tail_outcome_records(key: str, max_bytes: int = OUTCOME_TAIL_BYTES) -> list:
    """Read parseable JSONL records from a bounded outcome-file tail; never write.
    Discard the first partial line unless reading from byte zero. Replacement
    decoding preserves records containing bad characters; unreadable files yield [].
    """
    path = outcome_path(key)
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - max_bytes)
            fh.seek(start)
            raw = fh.read()
    except OSError:
        return []
    lines = raw.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def _outcome_denial_count(rec: dict):
    """Return a nonnegative integer denial count, or None for unknown.
    Reject booleans as counts and preserve the distinction between unknown and zero.
    """
    if not isinstance(rec, dict):
        return None
    value = rec.get("permission_denials")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _session_permission_denials(name: str, sid: str, records=None):
    """Return the newest measured cumulative denial count for this sid, or None.
    Skip newer records without the field, such as kill tombstones. Counts span
    the session, so a respawn does not inherit its predecessor's denials.
    Use supplied records or bounded tails of both name- and sid-keyed files.
    """
    if not isinstance(sid, str) or not sid:
        return None
    if records is None:
        records = _tail_outcome_records(name)
        if sid != name:
            records = records + _tail_outcome_records(sid)
    scoped = [r for r in records if isinstance(r, dict) and r.get("session_id") == sid]
    scoped.sort(key=lambda r: str(r.get("ts", "")))
    for rec in reversed(scoped):
        count = _outcome_denial_count(rec)
        if count is not None:
            return count
    return None


def has_fresh_outcome(name: str, sid: str, since_iso: str,
                      kinds: tuple = ("result",)) -> bool:
    """Whether a matching session outcome falls inside the dispatch freshness window.
    By default only Stop-hook result records count: operator-stop tombstones
    cannot certify clean completion. Callers may explicitly request other kinds.
    """
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


def _stop_native_session_status(sid: str, run=subprocess.run, which=shutil.which,
                                timeout: int = 30, ref: str = None) -> tuple:
    """Return (ok, outcome) for sanctioned claude stop; never raw-kill a daemon child.
    Both successful stop and already-gone mean ok; other outcomes are unverified.
    Use the short job reference, retrying an unclassified failure with the full sid.
    Callers can lower the default timeout for best-effort retired-session sweeps.
    """
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError:
        return (False, "no-claude")
    refs = dict.fromkeys((ref or _native_job_ref(sid), sid))
    outcome = "failed"
    for r in refs:
        try:
            proc = run([exe, "stop", r], capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return (False, "error")
        outcome = _classify_native_cli_result(proc)
        if outcome in ("ok", "gone"):
            return (True, outcome)
        if outcome == "daemon-transient":
            return (False, outcome)
    return (False, outcome)


def _stop_native_session(sid: str, run=subprocess.run, which=shutil.which,
                         timeout: int = 30) -> bool:
    """Bool face of `_stop_native_session_status` -- "is this session not
    running any more?". True for a fresh stop AND for an already-gone id;
    False means COULD NOT VERIFY, which callers treat fail-safe."""
    ok, _outcome = _stop_native_session_status(sid, run=run, which=which,
                                               timeout=timeout)
    return ok


def _restamp_after_steer(record: dict, new_sid: str, short_id: str) -> None:
    """Retire the prior sid, restamp the fork identity and dispatch time, and bump turns.
    Do not add None to retired_sids: cleanup later passes those values to the CLI.
    """
    old_sid = record["session_id"]
    if old_sid is not None:
        record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
    record["session_id"] = new_sid
    record["native_short_id"] = short_id
    record["last_dispatch_at"] = now_iso()
    record["turns"] = record.get("turns", 0) + 1


def _migrate_residual_mailbox(old_sid: str, new_sid: str) -> None:
    """Carry mail arriving after prompt composition from old_sid to new_sid.
    Run after the steer commit. Use append_mailbox's atomic append because
    senders can race this migration; errors must not undo a successful steer.
    """
    old_path = mailbox_dir() / f"{old_sid}.md"
    try:
        if not old_path.exists():
            return
        content = old_path.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            append_mailbox(new_sid, content)
        old_path.unlink()
    except OSError:
        pass


def _fast_completion_sid(name: str, since_iso: str, short_id: str | None = None,
                         exclude_sids=()):
    """Recover a fresh result sid after dispatch succeeded but roster join failed.
    Scan name-keyed outcomes and sid-keyed filenames matching short_id: hooks
    cannot resolve the name before the pre-claim receives its session_id.
    Require the record's sid prefix too, exclude known retired sids, and reject
    missing short_id. Freshness alone could bind a predecessor's farewell result
    to a new dispatch because name-keyed files survive respawn.
    """
    if not short_id:
        return None
    try:
        since = _parse_iso(since_iso)
    except (ValueError, TypeError):
        return None
    threshold = since - timedelta(seconds=OUTCOME_FRESH_SLACK_SECONDS)
    excluded = {str(s) for s in (exclude_sids or ())}
    best_sid, best_ts = None, None

    def _consider(rec):
        nonlocal best_sid, best_ts
        # Only Stop-hook results prove completion; operator-stop tombstones do not.
        if rec.get("kind") != "result":
            return
        sid = rec.get("session_id")
        if not sid:
            return
        # Apply identity and retirement filters to both sources: filenames alone
        # cannot prove that an outcome belongs to this dispatch.
        if str(sid) in excluded or not str(sid).startswith(short_id):
            return
        try:
            ts = _parse_iso(str(rec.get("ts", "")))
        except (ValueError, TypeError):
            return
        if ts >= threshold and (best_ts is None or ts > best_ts):
            best_sid, best_ts = sid, ts

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


# Native worker dispatch: task-file bootstrap, short-id capture, roster join
# and fresh display name. Handoff successors use their dedicated dispatch path.

NATIVE_JOIN_VERIFY_SECONDS = 60.0   # keep in sync with SUPERVISOR_ROSTER_VERIFY_SECONDS below (same window, independently defined -- Finding 3)
NATIVE_JOIN_POLL_SECONDS = 3.0
NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0
# Attachment deadlines are detection thresholds, not proof of death. Verify
# cleanup before retry and abort on a full-window roster blackout.
NATIVE_ATTACH_VERIFY_SECONDS = 30.0
NATIVE_ATTACH_POLL_SECONDS = 2.0
# Bound wedge cleanup inside spawn latency budgets; stacked default stop/rm
# timeouts would otherwise exhaust the caller's outer timeout.
NATIVE_WEDGE_CLEANUP_TIMEOUT_SECONDS = 10
DEFAULT_CATEGORY = "fleet"
NATIVE_NAME_HINT_MAX = 40

# Inline the message so resumed turns carry changed instructions directly.
# Cap its size for Win32 command-line limits; over-length messages still require
# the worker to reread the payload file for the remainder.
NATIVE_INLINE_STEER_MAX = 4000

# Steer means replace instructions; resume-limited means continue parked work.
# Keep distinct framing so a resumed worker does not abandon its task.
NATIVE_INLINE_LEAD = {
    "steer": ("That message is a NEW instruction and it supersedes anything "
              "earlier in this session."),
    "resume": ("Your previous turn was cut short by a usage limit, whose reset "
               "horizon has now passed. CONTINUE the task you were already "
               "working on -- nothing here replaces it, and anything above is "
               "further instruction for that same task."),
}

# Middle dot is the daemon's literal separator glyph.
_BG_SHORT_ID_RE = re.compile(r"backgrounded\s*·\s*(\S+)\s*·")

# Color-forcing environment variables can colorize piped background stdout.
# Strip ANSI CSI codes before parsing or the short id will never join a real sid.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class NativeDispatchError(Exception):
    """Dispatch failure carrying short_id when dispatch parsed one.
    The handle allows fast-completion recovery from sid-keyed outcomes; it is
    None for failures before an id is known.
    """
    def __init__(self, message, short_id=None):
        super().__init__(message)
        self.short_id = short_id


def render_native_name(category, name: str, hint: str) -> str:
    # Collapse whitespace and replace pipes to preserve the cat|name|hint split.
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


def _roster_entry_has_life_signal(entry) -> bool:
    """Whether status, pid or a reached terminal/blocked state proves attachment.
    A handoff name join needs this additional evidence because a matching name
    alone can identify a never-attached husk.
    """
    if not isinstance(entry, dict):
        return False
    if "status" in entry or "pid" in entry:
        return True
    return entry.get("state") in ("done", "failed", "stopped", "blocked")


def _join_roster_by_short_id(short_id, roster_fetch, sleep,
                             verify_seconds=NATIVE_JOIN_VERIFY_SECONDS,
                             exclude_sids=frozenset(), clock=time.monotonic):
    """Join the dispatch short-id prefix to a full sid, including completed entries.
    Exclude pre-existing sids so prefix collisions cannot bind a foreign session.
    A window with no successful roster fetch raises NativeDispatchError: unseen is not dead.
    An observed roster without a match returns None. The clock is injectable.
    """
    deadline = clock() + verify_seconds
    verified_once = False
    while True:
        ok, payload = roster_fetch()
        if ok:
            verified_once = True
            for e in payload:
                sid = e.get("sessionId") if isinstance(e, dict) else None
                if (isinstance(sid, str) and sid.startswith(short_id)
                        and sid not in exclude_sids):
                    return sid
        if clock() >= deadline:
            if not verified_once:
                raise NativeDispatchError(
                    f"cannot verify roster join for short id {short_id}: every "
                    f"roster fetch failed for {verify_seconds:.0f}s -- the roster "
                    f"is unavailable, so the join is INDETERMINATE, not failed "
                    f"(an unobserved session is never declared dead)",
                    short_id=short_id)
            return None
        sleep(NATIVE_JOIN_POLL_SECONDS)


def _await_attach(name, sid, roster_fetch, sleep, clock,
                  verify_seconds=NATIVE_ATTACH_VERIFY_SECONDS):
    """Wait for evidence that a joined background session attached.
    Accept status/pid, a terminal/blocked state, disappearance after joining,
    or an outcome for this sid. Retry transient roster errors.
    False means a never-attach wedge. A full-window roster blackout raises
    NativeDispatchError instead, since stop/rm must not target an unseen live turn.
    """
    deadline = clock() + verify_seconds
    verified_once = False
    while True:
        ok, entries = roster_fetch()
        if ok:
            verified_once = True
            entry = _roster_entry_for(entries, sid)
            if entry is None:
                return True
            if "status" in entry or "pid" in entry:
                return True
            if entry.get("state") in ("done", "failed", "stopped", "blocked"):
                return True
        if read_outcomes(name, sid=sid):
            return True
        if clock() >= deadline:
            if not verified_once:
                raise NativeDispatchError(
                    f"cannot verify attachment of {name!r} session {sid}: "
                    f"every roster fetch failed for {verify_seconds:.0f}s -- "
                    f"aborting dispatch WITHOUT touching the session (H1: "
                    f"an unobserved session is never treated as a wedge)",
                    short_id=sid.split("-", 1)[0])
            return False
        sleep(NATIVE_ATTACH_POLL_SECONDS)


def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
                hint="", resume_sid=None, settings_path=None,
                setting_sources=None, inline_kind=None, inline_body="",
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
                roster_fetch=None, clock=time.monotonic):
    # Validate names at this dispatch boundary too: direct callers must not escape
    # tasks_dir(). Supervisor names are admitted here, while fleet spawn's NAME_RE
    # rejects their pipe-delimited shape.
    if (not name or not (NAME_RE.match(name) or _is_supervisor_shaped(name))
            or _SID_SHAPE_RE.match(name)):
        raise NativeDispatchError(
            f"invalid worker name: {name!r} (must match {NAME_RE.pattern} or "
            f"the supervisor family {_SUPERVISOR_SHAPED_WORKER_RE.pattern}; "
            f"uuid-shaped names are reserved for session ids, F6)")
    # Reject Win32 device names before writes: nul passes NAME_RE yet writes to
    # a device, which a later path-containment check cannot detect.
    if _is_win32_device_name(name):
        raise NativeDispatchError(
            f"invalid worker name: {name!r} (Win32 reserved device name -- the "
            f"task file write would report success and vanish, P1-8)")
    if roster_fetch is None:
        roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    try:
        exe = resolve_claude_executable(which)
    except ClaudeNotFoundError as exc:
        raise NativeDispatchError(str(exc)) from exc
    settings = Path(settings_path) if settings_path else instance_settings_path()
    try:
        tasks_dir().mkdir(parents=True, exist_ok=True)
        # Create journals_dir before --add-dir: nonexistent directories grant nothing
        # and a headless worker cannot answer the resulting write-permission prompt.
        journals_dir().mkdir(parents=True, exist_ok=True)
        task_path = task_file_path(name)
        task_path.write_text(prompt_body, encoding="utf-8")
    except OSError as exc:
        raise NativeDispatchError(f"task-file write failed: {exc}") from exc
    # Supervisor names already contain pipes; use them bare to preserve name parsing.
    rendered = (name if _is_supervisor_shaped(name)
                else render_native_name(category, name, hint))
    tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
    # Inline resumed instructions so a previously read task-file pointer cannot
    # look like an unchanged turn. inline_kind selects distinct steer/resume framing.
    if inline_kind is not None:
        lead = NATIVE_INLINE_LEAD.get(inline_kind)
        if lead is None:
            raise NativeDispatchError(
                f"unknown inline_kind: {inline_kind!r} (expected one of "
                f"{sorted(NATIVE_INLINE_LEAD)}) -- a dispatch that inlines "
                f"must say which framing it means, since they contradict")
        body = (inline_body or "").strip()
        if len(body) > NATIVE_INLINE_STEER_MAX:
            body = (body[:NATIVE_INLINE_STEER_MAX].rstrip()
                    + "\n[truncated here -- the full text is in the file "
                      "named below]")
        block = f"<MANAGER MESSAGE>\n{body}\n</MANAGER MESSAGE>\n\n" if body else ""
        tiny_prompt = (
            f"{block}{lead} {tiny_prompt} That file has been REWRITTEN since "
            f"you last read it -- read it again rather than reusing an "
            f"earlier copy.")
    argv = [exe, "--bg"]
    if resume_sid:
        argv += ["--resume", resume_sid]
    argv += ["-n", rendered, "--settings", settings.as_posix()]
    # Preauthorize task and journal directories: headless workers cannot answer
    # prompts for protocol-required files outside their cwd. Do not grant the whole home.
    argv += ["--add-dir", tasks_dir().as_posix(),
             "--add-dir", journals_dir().as_posix()]
    # Forward persisted setting sources to the native dispatch.
    if setting_sources:
        argv += ["--setting-sources", setting_sources]
    argv += mode_flags(mode)
    if model:
        argv += ["--model", model]
    argv.append(tiny_prompt)
    def _dispatch_once():
        """Dispatch and join using a fresh per-attempt roster snapshot.
        Exclude foreign sessions minted during an earlier attempt's attach window;
        reusing the earlier snapshot would permit a retry-prefix collision.
        """
        # Snapshot once per attempt and exclude existing sids from the prefix join.
        # Failed fetch falls back to no exclusions; filter non-string sids before set insertion.
        pre_ok, pre_entries = roster_fetch()
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
            # Classify both output streams: vendor prefixes and symptoms may be split between them.
            detail = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()
            # Name the machine-wide cause and remedy, retaining raw vendor text for diagnosis.
            if _NATIVE_BG_UNREACHABLE_RE.search(detail):
                raise NativeDispatchError(
                    f"--bg dispatch exited {proc.returncode}: the Claude "
                    f"background service never became reachable, so NO fleet "
                    f"dispatch can succeed on this machine (spawn, respawn, "
                    f"steer, resume). Most likely cause: a STALE "
                    f"~/.claude/daemon.lock whose pid was recycled onto an "
                    f"unrelated process, making every daemon start lose a lock "
                    f"race to a daemon that is already dead. Confirm with "
                    f"`fleet doctor` (the daemon-wedge check) -- and if it "
                    f"does NOT report a wedge, do not remove the lock: the "
                    f"unreachable-service message is a 45s TIMEOUT, which a "
                    f"loaded machine or a slow upgrade self-restart can also "
                    f"produce while a healthy daemon owns it. "
                    f"{NATIVE_DAEMON_WEDGE_REMEDY} -- vendor said: "
                    f"{detail[:400]}")
            raise NativeDispatchError(
                f"--bg dispatch exited {proc.returncode}: {detail[:400]}")
        short_id = _parse_bg_short_id(proc.stdout or "")
        if not short_id:
            raise NativeDispatchError(
                f"could not parse short id from --bg stdout: {(proc.stdout or '').strip()[:400]}")
        try:
            sid = _join_roster_by_short_id(short_id, roster_fetch, sleep,
                                           exclude_sids=pre_sids, clock=clock)
        except BaseException as exc:
            # A session already launched; preserve its short id on escaping exceptions so
            # the operator can recover it. The helper supports Python 3.10 without add_note.
            _stash_short_id_note(exc, short_id)
            raise
        if sid is None:
            raise NativeDispatchError(
                f"dispatched (short id {short_id}) but no roster entry joined "
                f"within {NATIVE_JOIN_VERIFY_SECONDS:.0f}s -- possible DOA; "
                f"recover manually via claude agents", short_id=short_id)
        return sid, short_id

    def _cleanup_wedged(sid, short_id):
        """Stop and remove a wedge candidate; return verification and retry safety.
        On uncertain cleanup, re-read the roster and retry only if the entry is gone
        or still status/pid-free. Otherwise a slow first attach could race the retry
        and create two live sessions. Short timeouts preserve the spawn budget.
        """
        stopped = _stop_native_session(sid, run=run, which=which,
                                       timeout=NATIVE_WEDGE_CLEANUP_TIMEOUT_SECONDS)
        removed = _rm_native_session(sid, run=run, which=which,
                                     timeout=NATIVE_WEDGE_CLEANUP_TIMEOUT_SECONDS)
        retry_safe = True
        detail = f"stop={'ok' if stopped else 'FAILED'}/rm={'ok' if removed else 'FAILED'}"
        if not (stopped and removed):
            ok, entries = roster_fetch()
            if not ok:
                retry_safe = False
                detail += ", recheck=unavailable"
            else:
                entry = _roster_entry_for(entries, sid)
                if entry is None:
                    detail += ", recheck=gone"
                elif "status" in entry or "pid" in entry:
                    retry_safe = False
                    detail += ", recheck=LIVE"
                else:
                    detail += ", recheck=still-unattached"
        return stopped, removed, retry_safe, detail

    # A roster join does not prove attachment. Verify life, then verify wedge
    # cleanup before retrying exactly once; a second wedge raises loudly.
    sid, short_id = _dispatch_once()
    if _await_attach(name, sid, roster_fetch, sleep, clock):
        return {"session_id": sid, "short_id": short_id, "rendered_name": rendered}
    _append_event_quiet("dispatch_wedged", name, session_id=sid, short_id=short_id)
    print(f"fleet: {name}: session {short_id} joined the roster but never "
          f"attached within {NATIVE_ATTACH_VERIFY_SECONDS:.0f}s -- stopping "
          f"the wedged session and retrying once", file=sys.stderr)
    stopped1, removed1, retry_safe, detail1 = _cleanup_wedged(sid, short_id)
    if not retry_safe:
        raise NativeDispatchError(
            f"wedged session {short_id} for {name!r} could not be verified "
            f"stopped ({detail1}) -- refusing the retry: redispatching over a "
            f"possibly-live session risks two sessions on one task (C1)",
            short_id=short_id)
    _append_event_quiet("dispatch_retried", name, wedged_session_id=sid,
                        cleanup=detail1)

    sid2, short_id2 = _dispatch_once()
    if _await_attach(name, sid2, roster_fetch, sleep, clock):
        return {"session_id": sid2, "short_id": short_id2, "rendered_name": rendered}
    _append_event_quiet("dispatch_wedged", name, session_id=sid2, short_id=short_id2)
    _stopped2, _removed2, _retry_safe2, detail2 = _cleanup_wedged(sid2, short_id2)
    raise NativeDispatchError(
        f"two consecutive --bg dispatches for {name!r} joined the roster but "
        f"never attached (no pid/status, no outcome) within "
        f"{NATIVE_ATTACH_VERIFY_SECONDS:.0f}s each -- daemon dispatch wedge; "
        f"cleanup: {short_id} {detail1}; {short_id2} {detail2}",
        short_id=short_id2)


# Supervisor state: committed GOALS/JOURNAL, machine-local INCARNATION and
# HANDSHAKE. Claim writes hold fleet_lock and replace atomically; successors
# write HANDSHAKE separately because only the claim holder may write the journal.

SUPERVISOR_CLAIM_STALE_SECONDS = 3600.0   # S: seizure/nag threshold, > beat period + margin (spec §4)
SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0   # T: handoff wait before abort (spec §4)

# three-tier §10.4 T_release bounds the wait for a steered supervisor to release.
# SPEC:1191 gives the handshake timeout as a shape precedent, not a shared
# tunable: kill/respawn patience and handoff patience must remain independent.
SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0
# Divide the release window exactly so timeout fires at the bound.
SUPERVISOR_RELEASE_POLL_SECONDS = 5.0
SUPERVISOR_ROSTER_VERIFY_SECONDS = 60.0   # dispatch -> roster-join window (contract G6 fallback); keep in sync with NATIVE_JOIN_VERIFY_SECONDS above (same window, independently defined -- Finding 3)

# Pending TTL balances lost-delivery recovery against a thinking body's time
# to acknowledge. A longer TTL delays replacement while live remains usable;
# a shorter TTL ages valid pending values through their final grace generation.
PENDING_NONCE_TTL_SECONDS = 900.0

# Nonce presentation is argv-only: an environment channel would propagate to
# every worker and subagent through inherited environment. Same-user readability
# is shared by both channels; inheritance is the distinction.
NONCE_ARG_HELP = ("the generation this body was last given (claim-nonce §5.3); "
                  "the ONLY presentation channel -- there is no env-var fallback")

# Mutating verbs use the generation for the continuity gate and lineage ownership.
# These are bypassable speed-bumps, not authorization boundaries.
GATE_NONCE_ARG_HELP = ("the current supervisor generation (claim-nonce §5.3): clears §7's "
                       "claim gate for a mutating verb while a fresh claim is held, and "
                       "proves the lineage that owns a rotated body's workers (§6.2)")

# Keep refusal evidence visible across an overnight gap, while bounding stale alarms.
NONCE_REJECTION_WINDOW_SECONDS = 24 * 3600

# Two pending TTLs exhaust the prior slot's grace. Longer outstanding pending
# signals missing acknowledgments even if no caller has yet been refused.
NONCE_PENDING_STALE_MULTIPLE = 2

# Compact the rejection log out of band under fleet_lock: read-modify-write
# would forfeit concurrent atomic append. Readers bound their own tail reads.
NONCE_REJECTION_LOG_MAX_RECORDS = 200


# Supervisor nonce primitives prove generation continuity on this substrate.

def mint_nonce() -> str:
    """A fresh generation. Entropy only -- never derived from the incarnation
    id, the sid or the clock, all three of which a lock-free view publishes."""
    return secrets.token_urlsafe(32)


def nonce_digest(value: str) -> str:
    """Hash a nonce for storage; INCARNATION never stores its plaintext.
    This protects that file, not a session transcript copied by fork-session.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def nonce_matches(presented, stored) -> bool:
    """Compare a presented nonce with a stored hex digest in constant time.
    Non-string values refuse rather than raise; absent digests routinely occur
    on legacy or released claims.
    """
    if not isinstance(presented, str) or not presented:
        return False
    if not isinstance(stored, str) or not stored:
        return False
    return hmac.compare_digest(nonce_digest(presented), stored)

# Handoff successors need bypass to run their fleet sup-boot bootstrap.
# dontAsk avoids prompts by denying unlisted calls; it cannot bootstrap the
# supervisor. Keep a separate named default for the handoff dispatch.
SUCCESSOR_DEFAULT_MODE = "bypass"

# Gen-0 supervisors likewise need bypass for fleet sup-boot. Keep the constant
# separate because sup-spawn is operator-attended and handoff is not; the
# permission-mode flag overrides through MODE_FLAGS.
SUP_SPAWN_DEFAULT_MODE = "bypass"

SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED", "RELEASED", "LIMIT-TRANSFER",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)

# Published sup-boot exit contract (skills/fleet/SKILL.md:54). Resume shares
# success with fresh claim: the holder keeps its existing claim.
SUPERVISOR_BOOT_RC = {"claim": 0, "resume": 0, "seize": 0, "limit-transfer": 0,
                      "refuse": 2, "freeze": 3}
SUPERVISOR_BOOT_VERDICTS = tuple(SUPERVISOR_BOOT_RC) + ("handshake-written",
                                                        "handoff-refused")
# A noncurrent successor gets a distinct rc so it can terminate without
# confusing that terminal disposition with an ordinary occupied-claim refusal.
SUPERVISOR_BOOT_HANDOFF_REFUSED_RC = 5

_SUPERVISOR_JOURNAL_SEED = """# Supervisor Journal

Append-only checkpoint log (spec §4). Single writer: the current claim
holder, via `fleet sup-*` commands only. Never edit or delete entries.
Entry header format: `## <utc-iso> <KIND> inc=<incarnation-id> sid=<session-id>`
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, RELEASED, LIMIT-TRANSFER, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.

<!-- entries below -->
"""


def supervisor_dir() -> Path:
    return FLEET_HOME / "supervisor"


def goals_path() -> Path:
    return supervisor_dir() / "GOALS.md"


# Read operator-owned role/tier/model policy from GOALS.md over defaults.
# Emit configured tier aliases; concrete provider models belong below fleet.
_TIER_POLICY_DEFAULTS = {
    "supervisor_chain": ["top", "second"],   # §3.5 preference chain
    "worker_tiers": ["second", "third"],     # §3.4 (Opus/Sonnet, never Haiku)
    "tier_model": {},                        # §3.3(d): unset -> omit --model
}
_TIER_POLICY_BLOCK_OPEN = "<!-- fleet-tier-policy"
_TIER_POLICY_BLOCK_CLOSE = "-->"


def _parse_tier_policy_block(text: str) -> dict:
    """Parse the `fleet-tier-policy` HTML-comment block out of GOALS.md prose
    (invisible in rendered markdown, greppable in source). Recognised keys:
    `supervisor-tier-chain`, `worker-tiers` (comma lists), `tier-model`
    (`tier=alias` pairs). Unknown keys and empty values are ignored -- an empty
    value keeps the default rather than an empty list. Returns only the keys it
    actually found; the caller merges over defaults."""
    lines = text.splitlines()
    inside = False
    found = {}
    for raw in lines:
        line = raw.strip()
        if not inside:
            if line.startswith(_TIER_POLICY_BLOCK_OPEN):
                inside = True
            continue
        if line.startswith(_TIER_POLICY_BLOCK_CLOSE):
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            continue
        if key in ("supervisor-tier-chain", "worker-tiers"):
            tiers = [t.strip() for t in value.split(",") if t.strip()]
            if tiers:
                found["supervisor_chain" if key == "supervisor-tier-chain"
                      else "worker_tiers"] = tiers
        elif key == "tier-model":
            mapping = {}
            for pair in value.split(","):
                tier, _, alias = pair.partition("=")
                tier, alias = tier.strip(), alias.strip()
                if tier and alias:
                    mapping[tier] = alias
            if mapping:
                found["tier_model"] = mapping
    return found


def read_tier_policy() -> dict:
    """Read role/tier policy from operator-owned GOALS.md over defaults.
    _source is goals when the block supplies a key. Missing or undecodable
    GOALS.md yields defaults.
    """
    policy = {"supervisor_chain": list(_TIER_POLICY_DEFAULTS["supervisor_chain"]),
              "worker_tiers": list(_TIER_POLICY_DEFAULTS["worker_tiers"]),
              "tier_model": dict(_TIER_POLICY_DEFAULTS["tier_model"]),
              "_source": "default"}
    try:
        text = goals_path().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return policy
    found = _parse_tier_policy_block(text)
    if found:
        policy.update(found)
        policy["_source"] = "goals"
    return policy


def resolve_model_for_role(role: str, policy: dict = None):
    """The `--model` tier alias for `role`, or None to OMIT --model (§3.3(d),
    the honest provider-agnostic default). Resolves role -> the first tier it
    binds to -> the operator's tier->alias mapping:

      supervisor -> supervisor_chain[0]   (the preferred tier, §3.5)
      worker     -> worker_tiers[0]        (the supervisor overrides per-spawn)
      interface  -> "top"                  (advisory: fleet never launches it, §3.1)

    None when the tier has no operator-set alias -- fleet does not invent one."""
    if policy is None:
        policy = read_tier_policy()
    if role == "supervisor":
        tiers = policy.get("supervisor_chain") or []
    elif role == "worker":
        tiers = policy.get("worker_tiers") or []
    elif role == "interface":
        tiers = ["top"]
    else:
        tiers = []
    if not tiers:
        return None
    return policy.get("tier_model", {}).get(tiers[0])


def proposed_goals_tier_block() -> str:
    """The tier-policy block this build proposes the operator add to
    supervisor/GOALS.md (§3.3: the resolver READS this; the operator APPLIES
    it). Kept in code so the proposal doc and the parser never drift."""
    return (f"{_TIER_POLICY_BLOCK_OPEN}\n"
            "supervisor-tier-chain: top, second\n"
            "worker-tiers: second, third\n"
            "tier-model: top=opus, second=opus, third=sonnet\n"
            f"{_TIER_POLICY_BLOCK_CLOSE}\n")


def incarnation_path() -> Path:
    return supervisor_dir() / "INCARNATION"


def handshake_path() -> Path:
    return supervisor_dir() / "HANDSHAKE"


def supervisor_journal_path() -> Path:
    return supervisor_dir() / "JOURNAL.md"


def supervisor_journal_history_path() -> Path:
    """Return the stable append-only destination for rolled journal entries."""
    return supervisor_dir() / "journal-history" / "journal-roll.md"


def handoff_abort_flag_path() -> Path:
    """Doctor-visible flag written by sup-handoff-abort (spec §4 timeout
    branch). Lives in state/ (gitignored runtime), cleared by the next
    sup-handoff-begin or manually by the operator."""
    return state_dir() / "supervisor-handoff-aborted.json"


# The abort flag is a doctor-visible record, not successor identity evidence.


def pending_decision_path() -> Path:
    """Return the routing-state path for the single open operator decision.
    Presence means open; removing the file clears it.
    """
    return state_dir() / "supervisor-pending-decision.json"


def read_pending_decision() -> dict | None:
    """The open operator decision, or None when absent. A corrupt file reads as
    `{"_unreadable": True, ...}` -- NEVER None -- so a garbled gate stays
    nag-visible rather than silently dropping an operator decision (§8: the file
    is the routing surface for "operator gates stay human" under an unattended
    supervisor)."""
    path = pending_decision_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"_unreadable": True,
                "question": "(pending-decision file present but unreadable)"}
    if not isinstance(data, dict):
        return {"_unreadable": True,
                "question": "(pending-decision file is not a JSON object)"}
    return data


def write_pending_decision(obj: dict) -> None:
    _write_json_atomic(pending_decision_path(), obj)


def clear_pending_decision() -> None:
    """Remove the open decision (§8: answering may write the answer OR remove
    the file; consuming the answer removes it). Idempotent -- a missing file is
    not an error."""
    try:
        pending_decision_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _write_json_atomic(path: Path, obj: dict) -> None:
    """Write JSON atomically so lock-free readers cannot see a partial file.
    Retry bounded Windows sharing violations: polling readers can temporarily
    hold INCARNATION open, and that collision must not prevent release.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    _replace_with_retry(str(tmp), str(path))


def read_incarnation() -> dict | None:
    """The current claim, or None when absent/unreadable. Lock-free-safe
    (writes are atomic); mutating callers still re-read under fleet_lock."""
    try:
        data = json.loads(incarnation_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_incarnation_status() -> tuple:
    """Return (absent|corrupt|ok, claim_or_None) without raising.
    Destructive callers must distinguish no claim from an unreadable claim;
    permission errors, directories and non-object JSON are corrupt.
    """
    try:
        raw = incarnation_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return ("absent", None)
    except OSError:
        return ("corrupt", None)
    try:
        data = json.loads(raw)
    except ValueError:
        return ("corrupt", None)
    if not isinstance(data, dict):
        return ("corrupt", None)
    return ("ok", data)


def write_incarnation(claim: dict) -> None:
    """Caller MUST hold fleet_lock (single-supervisor invariant, spec §4)."""
    _write_json_atomic(incarnation_path(), claim)


def read_handshake() -> dict | None:
    try:
        data = json.loads(handshake_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_handshake(incarnation_id: str, session_id: str,
                    handoff_token_hash=None, nonce_hash=None) -> None:
    """Write successor identity, token digest, nonce digest and timestamp.
    The one-shot token verifies handoff across fork-steer; the successor's own
    nonce supplies continuity after transfer. Optional hashes support mixed
    callers. session_id is diagnostic; doctor uses file mtime for age.
    """
    data = {
        "incarnation_id": incarnation_id,
        "session_id": session_id,
        "written_at": now_iso(),
    }
    if handoff_token_hash is not None:
        data["handoff_token_hash"] = handoff_token_hash
    if nonce_hash is not None:
        data["nonce_hash"] = nonce_hash
    _write_json_atomic(handshake_path(), data)


INCARNATION_ID_RE = re.compile(r"^inc-\d{8}T\d{6}Z-[0-9a-f]{4}$")

_HANDOFF_TASK_FILE_RE = re.compile(
    r"^supervisor-handoff-(?P<inc>inc-\d{8}T\d{6}Z-[0-9a-f]{4})\.md$")


def valid_incarnation_id(value) -> str:
    """Validate a minted incarnation-id shape or raise ValueError.
    IDs become path components and can come from argv or a successor-written
    HANDSHAKE; validation and path containment independently prevent traversal.
    """
    if not isinstance(value, str) or not INCARNATION_ID_RE.match(value):
        raise ValueError(
            f"not an incarnation id: {value!r} -- expected inc-<YYYYMMDD>T<HHMMSS>Z-<4 hex>")
    return value


def _argparse_incarnation_id(value: str) -> str:
    """`type=` adapter: argparse renders ValueError as a usage error."""
    try:
        return valid_incarnation_id(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def handoff_task_file_path(successor_inc: str) -> Path:
    """Return the confined bootstrap-file path carrying the plaintext handoff token.
    Validate the id and require the resolved parent to be state_dir(). Callers
    must treat invalid paths as unavailable, never unlink outside the home.
    """
    valid_incarnation_id(successor_inc)
    root = state_dir()
    path = (root / f"supervisor-handoff-{successor_inc}.md").resolve()
    if path.parent != root.resolve():
        raise FleetCliError(
            f"refusing a handoff task path outside {root.as_posix()}: {path.as_posix()}")
    return path


def unlink_handoff_task_file(successor_inc, context="") -> bool:
    """Remove one confined successor task file and return whether it was removed.
    Invalid or escaping ids remove nothing and are reported. Missing files are
    silent; other unlink failures are reported so retained tokens stay visible.
    """
    try:
        handoff_task_file_path(successor_inc).unlink()
    except FileNotFoundError:
        return False
    except (ValueError, FleetCliError) as exc:
        print(f"WARNING: not unlinking a handoff task file for {successor_inc!r}"
              f"{context}: {exc}")
        return False
    except OSError as exc:
        print(f"WARNING: could not unlink the handoff task file for {successor_inc}"
              f"{context} -- it carries a handoff token: {exc}")
        return False
    return True


HANDOFF_PENDING_KEY = "handoff_pending"
HANDOFF_SUPERSEDED_KEY = "superseded_at"
# Release ends succession without naming a replacement incarnation. Record
# that cause separately so the refusal cannot claim a later begin occurred.
HANDOFF_SUPERSEDED_REASON_KEY = "superseded_reason"
HANDOFF_SUPERSEDED_BY_RELEASE = "predecessor-released"

# Four entry states shared by views and abort resolution.
HANDOFF_JOINING = "joining"                    # no sid yet, inside the join window
HANDOFF_AWAITING_HANDSHAKE = "awaiting-handshake"   # joined, HANDSHAKE not yet written
HANDOFF_RESOLVABLE_STALE = "resolvable-stale"  # no sid, past T -- retirable by inc
HANDOFF_SUPERSEDED = "superseded"              # R9: a later begin took the succession


def handoff_pending_members(claim) -> list:
    """Return raw pending members, including torn entries.
    Writers must preserve unreadable members because dropping one also drops
    protection for a task file whose identity cannot be determined.
    """
    if not isinstance(claim, dict):
        return []
    pending = claim.get(HANDOFF_PENDING_KEY)
    if isinstance(pending, dict):
        return [pending]
    if not isinstance(pending, list):
        return []
    return list(pending)


def handoff_pending_entries(claim) -> list:
    """Return readable pending entries naming a successor, accepting a bare dict.
    Unaddressable members are excluded from views but remain in raw members:
    the torn-entry predicate reports them and writers preserve their protection.
    """
    return [e for e in handoff_pending_members(claim)
            if isinstance(e, dict) and isinstance(e.get("successor_inc"), str)
            and e.get("successor_inc")]


def handoff_pending_torn(claim) -> list:
    """Return members without a usable successor_inc or dictionary shape.
    While these unidentified attempts stand, the sweep protects every file and
    doctor fails; retire-all explicitly clears them.
    """
    torn = []
    for member in handoff_pending_members(claim):
        if not isinstance(member, dict):
            torn.append(member)
        elif not (isinstance(member.get("successor_inc"), str)
                  and member.get("successor_inc")):
            torn.append(member)
    return torn


def _entry_age_seconds(entry, key, now=None):
    """Return seconds since entry[key], or None for absent or unparseable values."""
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        return (now - _parse_iso(entry[key])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return None


def handoff_entry_state(entry, now=None, timeout_seconds=None) -> str:
    """Classify an attempt as joining, awaiting-handshake, stale or replaced.
    A replaced attempt is immediately resolvable. A sid-less attempt normally
    ages out at the timeout; a timestamp beyond one timeout in the future is
    also stale. Unreadable time on a sid-less attempt keeps it joining.
    """
    if entry.get(HANDOFF_SUPERSEDED_KEY):
        return HANDOFF_SUPERSEDED
    if entry.get("successor_sid"):
        return HANDOFF_AWAITING_HANDSHAKE
    if timeout_seconds is None:
        timeout_seconds = SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS
    age = _entry_age_seconds(entry, "minted_at", now=now)
    if age is None:
        # Unreadable minted_at cannot authorize age-based deletion. Keep joining;
        # explicit --successor-inc with --force permits retirement.
        return HANDOFF_JOINING
    if age < -timeout_seconds:
        return HANDOFF_RESOLVABLE_STALE
    return HANDOFF_RESOLVABLE_STALE if age > timeout_seconds else HANDOFF_JOINING


def handoff_entry_protects_file(entry, now=None, timeout_seconds=None) -> bool:
    """Whether an attempt still protects its bootstrap file from sweeping.
    Only a replaced attempt whose replacement is past the timeout loses
    protection; an unreadable replacement timestamp keeps it protected.
    """
    if handoff_entry_state(entry, now=now, timeout_seconds=timeout_seconds) \
            != HANDOFF_SUPERSEDED:
        return True
    if timeout_seconds is None:
        timeout_seconds = SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS
    age = _entry_age_seconds(entry, HANDOFF_SUPERSEDED_KEY, now=now)
    if age is None:
        return True
    return age <= timeout_seconds


def handoff_task_files_to_sweep(candidates, claim, timeout_seconds=None, now=None) -> list:
    """Return a sorted subset of dead bootstrap filenames; pure and fail-closed.
    Unknown claims or torn pending members protect all files. Otherwise protect
    the holder's file, still-protected pending files, and files younger than the
    timeout or with unreadable ages. Unrecognized filenames are never returned.
    A bootstrap file is the successor's only instruction source, so uncertain
    identity or age must never authorize deleting it.
    """
    if not isinstance(claim, dict) or not claim.get("incarnation_id"):
        return []
    if handoff_pending_torn(claim):
        return []
    if timeout_seconds is None:
        timeout_seconds = SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS
    live = {claim["incarnation_id"]}
    for entry in handoff_pending_entries(claim):
        inc = entry.get("successor_inc")
        if inc and handoff_entry_protects_file(entry, now=now,
                                               timeout_seconds=timeout_seconds):
            live.add(inc)
    dead = []
    for name, age in candidates:
        match = _HANDOFF_TASK_FILE_RE.match(name)
        if match is None or match.group("inc") in live:
            continue
        if not isinstance(age, (int, float)) or age <= timeout_seconds:
            continue
        dead.append(name)
    return sorted(dead)


def sweep_handoff_task_files(claim) -> list:
    """Unlink files approved by handoff_task_files_to_sweep and return removed names.
    Caller must hold fleet_lock because begin appends pending entries under it.
    Missing files are silent; other OSErrors report token-retention failures.
    """
    root = state_dir()
    try:
        candidates = []
        for path in root.glob("supervisor-handoff-*.md"):
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = None
            candidates.append((path.name, age))
    except OSError as exc:
        print(f"WARNING: could not list {root.as_posix()} for handoff-file sweep: {exc}")
        return []
    swept = []
    for name in handoff_task_files_to_sweep(candidates, claim):
        try:
            (root / name).unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(f"WARNING: could not unlink stale handoff task file {name} "
                  f"(it carries a handoff token): {exc}")
            continue
        swept.append(name)
    return swept


def _handoff_entry_named(entry, successor_sid=None, successor_inc=None) -> bool:
    """Match supplied handles by identity, never list position.
    A sid alone must match the recorded sid; an inc alone must match the inc.
    With both, the inc must match and the entry's sid must match or be absent.
    """
    if successor_inc and entry.get("successor_inc") != successor_inc:
        return False
    if successor_sid:
        recorded = entry.get("successor_sid")
        if recorded:
            if recorded != successor_sid:
                return False
        elif not successor_inc:
            return False
    return bool(successor_sid or successor_inc)


def handoff_entries_matching(claim, successor_sid=None, successor_inc=None) -> list:
    """EVERY pending entry the handle(s) name -- more than one means the handle
    is AMBIGUOUS, which callers must refuse on rather than guess at."""
    return [e for e in handoff_pending_entries(claim)
            if _handoff_entry_named(e, successor_sid=successor_sid,
                                    successor_inc=successor_inc)]


def handoff_entry_matching(claim, successor_sid=None, successor_inc=None):
    """Return the uniquely matching pending entry, or None for absence or ambiguity.
    List order must never decide which live successor an abort stops.
    """
    matches = handoff_entries_matching(claim, successor_sid=successor_sid,
                                       successor_inc=successor_inc)
    return matches[0] if len(matches) == 1 else None


def _carry_handoff_pending(old_claim, new_claim) -> None:
    """Copy raw pending members into a new claim, in place.
    Transitions must retain unresolved successors' abort handles and file
    protection, including unreadable entries. Empty input leaves the claim alone.
    """
    carried = handoff_pending_members(old_claim)
    if carried:
        new_claim[HANDOFF_PENDING_KEY] = carried


def _carry_handoff_pending_on_release(old_claim, new_claim) -> None:
    """Carry raw pending members onto release and mark readable attempts replaced.
    Release removes the handoff token hash, so no carried attempt can complete;
    they must become immediately abortable and refuse bootstrap. Preserve each
    existing replacement's provenance and all torn members' file protection.
    """
    members = handoff_pending_members(old_claim)
    if not members:
        return
    stamp = now_iso()
    for member in members:
        if isinstance(member, dict) and not member.get(HANDOFF_SUPERSEDED_KEY):
            member[HANDOFF_SUPERSEDED_KEY] = stamp
            member[HANDOFF_SUPERSEDED_REASON_KEY] = HANDOFF_SUPERSEDED_BY_RELEASE
    new_claim[HANDOFF_PENDING_KEY] = members


def resolve_handoff_abort(claim, handshake, successor_sid=None, successor_inc=None,
                          now=None, timeout_seconds=None, force=False) -> dict:
    """Decide stop, retire or refuse without IO.
    A HANDSHAKE must match the supplied handles. Otherwise require a unique
    pending match: stop a known sid; retire a replaced or stale sid-less entry;
    refuse a joining entry. Force permits retirement only when a sid-less entry's
    minted_at is unreadable, never a readable join still inside its window.
    Ambiguous handles refuse and name rival incarnations; this is not a general
    stop-any-sid operation. The abort flag is diagnostic, not identity evidence.
    """
    if handshake is not None:
        hs_sid, hs_inc = handshake.get("session_id"), handshake.get("incarnation_id")
        if successor_sid and hs_sid != successor_sid:
            return {"action": "refuse", "reason": (
                f"--successor-sid does not match HANDSHAKE sid {hs_sid} -- "
                f"refusing to stop an unrelated session")}
        if successor_inc and hs_inc != successor_inc:
            return {"action": "refuse", "reason": (
                f"--successor-inc does not match HANDSHAKE inc {hs_inc} -- "
                f"refusing to stop an unrelated session")}
        return {"action": "stop", "sid": hs_sid, "inc": hs_inc, "via": "handshake",
                "entry": handoff_entry_matching(claim, successor_sid=hs_sid,
                                                successor_inc=hs_inc)}
    rivals = handoff_entries_matching(claim, successor_sid=successor_sid,
                                      successor_inc=successor_inc)
    if len(rivals) > 1:
        return {"action": "refuse", "reason": (
            f"{successor_sid or successor_inc} is AMBIGUOUS -- {len(rivals)} recorded "
            f"successors answer to it ("
            + ", ".join(f"{e.get('successor_inc')}" for e in rivals)
            + "). Refusing to guess which session to stop; name one with "
              "`--successor-inc <inc>`")}
    entry = rivals[0] if rivals else None
    if entry is None:
        named = successor_sid or successor_inc
        known = ", ".join(
            f"{e.get('successor_inc')}"
            f"[{handoff_entry_state(e, now=now, timeout_seconds=timeout_seconds)}"
            f"{'' if not e.get('successor_sid') else ' sid=' + e['successor_sid']}]"
            for e in handoff_pending_entries(claim)) or "none recorded"
        return {"action": "refuse", "reason": (
            f"no HANDSHAKE and {named} matches no recorded limbo successor -- "
            f"refusing to stop an unverified session (pending successors: {known}; "
            f"check claude agents; stop manually if certain)")}
    state = handoff_entry_state(entry, now=now, timeout_seconds=timeout_seconds)
    if state == HANDOFF_SUPERSEDED:
        if entry.get("successor_sid"):
            return {"action": "stop", "sid": entry["successor_sid"],
                    "inc": entry.get("successor_inc"), "entry": entry,
                    "via": "superseded-entry"}
        return {"action": "retire", "sid": None, "inc": entry.get("successor_inc"),
                "entry": entry, "via": "superseded-entry"}
    if state == HANDOFF_AWAITING_HANDSHAKE:
        return {"action": "stop", "sid": entry["successor_sid"],
                "inc": entry.get("successor_inc"), "entry": entry, "via": "pending-entry"}
    if state == HANDOFF_RESOLVABLE_STALE:
        return {"action": "retire", "sid": None, "inc": entry.get("successor_inc"),
                "entry": entry, "via": "stale-entry"}
    unageable = _entry_age_seconds(entry, "minted_at", now=now) is None
    if force and unageable:
        return {"action": "retire", "sid": None, "inc": entry.get("successor_inc"),
                "entry": entry, "via": "forced"}
    if timeout_seconds is None:
        timeout_seconds = SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS
    return {"action": "refuse", "reason": (
        f"successor {entry.get('successor_inc')} was dispatched at "
        f"{entry.get('minted_at')} and has no recorded sid yet -- it is still inside "
        f"the {timeout_seconds:.0f}s join window, so there is nothing to stop and "
        f"nothing to retire. Wait it out, then retire it with "
        f"`--successor-inc {entry.get('successor_inc')}`"
        + (f" -- or, since its minted_at ({entry.get('minted_at')!r}) cannot be read "
           f"and it will therefore NEVER age out, retire it now with "
           f"`--successor-inc {entry.get('successor_inc')} --force`" if unageable else
           " -- --force does not apply here: its minted_at reads fine, so it ages "
           "out on its own and forcing it would unlink a still-joining successor's "
           "only input file" if force else ""))}


def drop_handoff_entry(claim, entry) -> None:
    """Retire an entry and remove the token hash when the last raw member leaves.
    Match incarnation id across rereads; use object identity only for torn
    entries without an id. Preserve other raw members and their protection;
    no outstanding attempt means no plaintext handoff token may remain valid.
    """
    inc = entry.get("successor_inc") if isinstance(entry, dict) else None
    remaining = [m for m in handoff_pending_members(claim)
                 if not (m is entry or (inc and isinstance(m, dict)
                                        and m.get("successor_inc") == inc))]
    if remaining:
        claim[HANDOFF_PENDING_KEY] = remaining
    else:
        claim.pop(HANDOFF_PENDING_KEY, None)
        claim.pop("handoff_token_hash", None)


def handoff_pending_append(claim, entry) -> None:
    """Append an attempt and mark earlier unresolved attempts replaced.
    Only one successor may bootstrap into the single HANDSHAKE path; older
    attempts remain recorded and abortable. Reject duplicate incarnation ids,
    which would otherwise share one task file and token between two bodies.
    """
    inc = entry.get("successor_inc")
    members = handoff_pending_members(claim)
    if inc and any(isinstance(m, dict) and m.get("successor_inc") == inc
                   for m in members):
        raise FleetCliError(
            f"refusing to record a second pending successor under {inc} -- one "
            f"incarnation id is one task file, one handoff token and one abort")
    stamp = now_iso()
    for member in members:
        if isinstance(member, dict) and not member.get(HANDOFF_SUPERSEDED_KEY):
            member[HANDOFF_SUPERSEDED_KEY] = stamp
            member["superseded_by"] = inc
    claim[HANDOFF_PENDING_KEY] = members + [entry]


def _mint_successor_inc(claim, attempts=8) -> str:
    """Mint an id absent from pending entries, the holder and existing task files.
    Retry collisions: sharing one bootstrap file or token between bodies would
    break handoff identity, while preserving the established id path shape.
    """
    used = {claim.get("incarnation_id") if isinstance(claim, dict) else None}
    used |= {e.get("successor_inc") for e in handoff_pending_entries(claim)}
    for _ in range(attempts):
        inc = mint_incarnation_id()
        if inc in used:
            continue
        try:
            if handoff_task_file_path(inc).exists():
                continue
        except (ValueError, FleetCliError):
            continue
        return inc
    raise FleetCliError(
        f"could not mint an unused successor incarnation id in {attempts} attempts -- "
        f"nothing dispatched; claim unchanged, duty continues")


def handoff_boot_refusal(claim, successor_inc, now=None, timeout_seconds=None):
    """Return why a successor must terminate, or None when bootstrap is allowed.
    Permit only the current attempt to write the single HANDSHAKE file, so a
    late rival cannot overwrite it. A claim with no pending record allows mixed
    predecessors; once a pending record exists, fail closed on mismatches.
    """
    if isinstance(claim, dict) and claim.get("incarnation_id") == successor_inc:
        return None            # already the holder: nothing to supersede it
    entries = handoff_pending_entries(claim)
    if not entries:
        return None
    known = ", ".join(f"{e.get('successor_inc')}"
                      f"[{handoff_entry_state(e, now=now, timeout_seconds=timeout_seconds)}]"
                      for e in entries)
    mine = [e for e in entries if e.get("successor_inc") == successor_inc]
    if not mine:
        return (f"{successor_inc} is not a pending successor of this claim "
                f"(recorded: {known}). Its attempt was retired or completed, so it "
                f"must not write HANDSHAKE -- a stale successor that writes one "
                f"clobbers the live attempt. TERMINATE: take no fleet actions and "
                f"end your turn with the final message HANDOFF-ORPHAN "
                f"{successor_inc}")
    superseded = [e for e in mine
                  if handoff_entry_state(e, now=now, timeout_seconds=timeout_seconds)
                  == HANDOFF_SUPERSEDED]
    if any(e.get(HANDOFF_SUPERSEDED_REASON_KEY) == HANDOFF_SUPERSEDED_BY_RELEASE
           for e in superseded):
        # Release removed the token hash, so this attempt can no longer transfer the claim.
        return (f"{successor_inc} cannot boot: the predecessor RELEASED the supervisor "
                f"claim after dispatching you, and the release took the handoff token "
                f"with it -- no body can complete your transfer, and a HANDSHAKE "
                f"written now is one no verb can act on. TERMINATE: take no fleet "
                f"actions and end your turn with the final message HANDOFF-ORPHAN "
                f"{successor_inc}")
    if superseded:
        newer = next((e.get("superseded_by") for e in mine if e.get("superseded_by")),
                     "a later attempt")
        return (f"{successor_inc} was SUPERSEDED by {newer}: the predecessor began "
                f"another handoff after dispatching you, and at most one successor "
                f"may boot (there is no promote verb -- the operator aborts and "
                f"begins again). Writing HANDSHAKE now would clobber the live "
                f"attempt's and strand the claim with NO holder. TERMINATE: take no "
                f"fleet actions and end your turn with the final message "
                f"HANDOFF-ORPHAN {successor_inc}")
    return None


def mint_incarnation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"inc-{stamp}-{uuid.uuid4().hex[:4]}"


def mint_lineage_id() -> str:
    """Mint lin-<utc>-<4 hex> for a fresh claim or recovery; carry it across handoff.
    Planned succession preserves vouched provenance. Seize must mint anew so
    a recovering body does not silently inherit ownership of prior workers.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"lin-{stamp}-{uuid.uuid4().hex[:4]}"


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


def _journal_roll_header_hint(line: str) -> bool:
    """Whether a non-matching markdown heading looks like an entry header."""
    body = line.rstrip("\r\n")
    if not body.startswith("## "):
        return False
    return bool(re.match(
        r"^## (?:\d{4}-\d{2}-\d{2}(?:T|\s)|\S+ "
        r"(?:BOOT|CHECKPOINT|PROPOSAL|SEIZED|RELEASED|LIMIT-TRANSFER|"
        r"HANDOFF-BEGIN|HANDOFF-COMPLETE|HANDOFF-ABORT)\b)", body))


def roll_supervisor_journal(home=None) -> dict:
    """Losslessly roll old supervisor entries off the committed journal board.

    The board is parsed as UTF-8 lines, but the moved and retained regions are
    byte slices of the original file.  That makes the content-preservation
    check independent of line counts and preserves line endings and non-ASCII
    bytes exactly.  A malformed entry-looking heading raises before either
    file is touched.

    Returns counts and ``rolled`` status for the CLI.  The caller must hold
    ``fleet_lock`` when this is used alongside another journal write.
    """
    # wave-close can target a checkout other than runtime FLEET_HOME.
    board = (Path(home) / "supervisor" / "JOURNAL.md"
             if home is not None else supervisor_journal_path())
    try:
        raw = board.read_bytes()
    except FileNotFoundError:
        return {"rolled": False, "checkpoints": 0, "entries": 0,
                "moved_bytes": 0}

    entries = []
    offset = 0
    for raw_line in raw.splitlines(keepends=True):
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"journal-roll: refusing malformed UTF-8 in {board}") from exc
        header = line.rstrip("\r\n")
        match = _SUPERVISOR_ENTRY_RE.match(header)
        if match:
            kind = match.group("kind")
            if kind not in SUPERVISOR_JOURNAL_KINDS:
                raise ValueError(
                    f"journal-roll: refusing unknown entry kind {kind!r}")
            entries.append({"start": offset, "kind": kind})
        elif _journal_roll_header_hint(line):
            raise ValueError(
                f"journal-roll: refusing malformed entry header in {board}")
        offset += len(raw_line)

    checkpoints = [entry for entry in entries if entry["kind"] == "CHECKPOINT"]
    if len(checkpoints) <= 3:
        return {"rolled": False, "checkpoints": len(checkpoints),
                "entries": len(entries), "moved_bytes": 0}

    cutoff = checkpoints[-3]["start"]
    first_entry = entries[0]["start"]
    moved = raw[first_entry:cutoff]
    retained = raw[:first_entry] + raw[cutoff:]
    if raw[:first_entry] + moved + raw[cutoff:] != raw:
        raise ValueError("journal-roll: refusing a non-lossless board partition")

    history = (Path(home) / "supervisor" / "journal-history" / "journal-roll.md"
               if home is not None else supervisor_journal_history_path())
    history.parent.mkdir(parents=True, exist_ok=True)
    try:
        history_before = history.read_bytes()
    except FileNotFoundError:
        history_before = b""
    if not history_before.endswith(moved):
        with open(history, "ab") as stream:
            stream.write(moved)
    board.write_bytes(retained)
    return {"rolled": True, "checkpoints": len(checkpoints),
            "entries": len(entries), "moved_bytes": len(moved),
            "history": history}


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
    # Prefix header-shaped body lines so pasted excerpts cannot inject journal entries.
    safe_body = "\n".join(
        f" {line}" if _SUPERVISOR_ENTRY_RE.match(line) else line
        for line in body.rstrip().splitlines()
    )
    entry = f"\n## {now_iso()} {kind} inc={inc} sid={sid}\n\n{safe_body}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)


def _roster_live_sids(entries: list) -> set:
    """Return sids with process evidence, excluding terminal-state entries.
    A done entry can retain status and pid while its host lingers; terminal
    state must dominate key presence so it cannot block successor claims.
    """
    # Filter non-string session ids before set insertion to avoid unhashable-value errors.
    return {
        e.get("sessionId") for e in entries
        if isinstance(e, dict) and isinstance(e.get("sessionId"), str)
        and e.get("sessionId") and ("status" in e or "pid" in e)
        and e.get("state") != "done"
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


def _claim_resume_allowed(nonce_valid: bool, holder_sid, caller_sid, live_sids: set) -> bool:
    """Allow proven continuity to resume when the holder is gone or is the caller.
    A separate predicate lets tests verify later rules' explicit liveness guard.
    """
    return bool(nonce_valid) and (holder_sid not in live_sids or holder_sid == caller_sid)


def _holder_is_limited(holder_sid) -> bool:
    """Whether the registry records holder_sid as limited with a reset horizon.
    three-tier-command.md `:432-437` requires this evidence for immediate transfer.
    A null horizon cannot certify when the body returns. Read under the caller's
    fleet_lock; errors decline transfer without aborting the claim ritual.
    """
    if not isinstance(holder_sid, str) or not holder_sid:
        return False
    try:
        data = load_registry()
    except Exception:  # noqa: BLE001 -- see the docstring: never abort a boot on this
        return False
    for rec in data.get("workers", {}).values():
        if not isinstance(rec, dict) or rec.get("session_id") != holder_sid:
            continue
        if rec.get("status") == "limited" and rec.get("limit_reset_at"):
            return True
    return False


def _registry_records_or_none():
    """Read registry records for identity, or None when unreadable.
    `load_registry`
    QUARANTINES a corrupt registry -- it renames the file aside (`:892`) --
    so using it here would write from the read-only supervisor gate.
    Quarantine belongs to explicit lock-held mutation. D4's
    rule for the view path (`:2495`) applies here too. An unreadable registry
    leaves callers with their bare-sid comparison, never a quarantine side effect.
    """
    ok, _reason, data = _read_registry_readonly()
    return data if ok else None


def _releaser_body_is_tombstoned(released_by, registry) -> bool:
    """Whether every registry carrier of released_by is fleet-tombstoned.
    Use _record_is_live and the sid union: fork-steer can move the current sid.
    A carrier must exist and all carriers must be retired; unreadable registry
    or any live carrier keeps the gate armed. These are fleet-written tombstones,
    not caller attestations, so a released body's lingering process may be ignored.
    """
    if not isinstance(registry, dict):
        return False
    workers = registry.get("workers")
    if not isinstance(workers, dict):
        return False
    carriers = [rec for rec in workers.values()
                if released_by in _record_sids(rec)]
    return bool(carriers) and not any(_record_is_live(rec) for rec in carriers)


def _releaser_live_sids(claim, live_sids: set, registry=None) -> set:
    """Return roster-live sids belonging to the released body; empty means no wedge.
    Fleet-tombstoned carriers disarm first. Otherwise include the releaser itself
    and live sids from carriers created no later than released_at. Fork-steer
    mutates a record in place; respawn creates a new body and must not keep the
    old release wedged forever. Second-precision ties arm the gate.
    Unreadable registry or timestamps disable union matching for that record,
    leaving the bare released_by_sid comparison. Return actual live sids so
    refusals name sessions an operator can act on.
    """
    if not isinstance(claim, dict) or claim.get("state") != "released":
        return set()
    released_by = claim.get("released_by_sid")
    if not isinstance(released_by, str) or not released_by:
        return set()
    if _releaser_body_is_tombstoned(released_by, registry):
        return set()            # fleet retired that body: not a live releaser
    if released_by in live_sids:
        return {released_by}
    if not isinstance(registry, dict):
        return set()
    try:
        released_at = _parse_iso(claim.get("released_at"))
    except (TypeError, ValueError):
        return set()            # no boundary to draw -- bare comparison only
    live = set()
    # OR across all sid carriers: registry ambiguity must resolve toward the gate.
    for rec in registry.get("workers", {}).values():
        sids = _record_sids(rec)
        if released_by not in sids:
            continue
        # `rec` is a dict here or `_record_sids` would have yielded nothing.
        try:
            created = _parse_iso(rec.get("created"))
        except (TypeError, ValueError):
            continue            # unreadable birth: not attributable, skip it
        if created > released_at:
            continue            # minted AFTER the release -- a respawn, not a fork
        live |= sids & live_sids
    return live


def _releaser_is_roster_live(claim, live_sids: set, registry=None) -> bool:
    """Whether a released claim still has a roster-live releasing body.
    Both boot and lifecycle gates use this pure predicate, with IO supplied by
    callers. _releaser_live_sids owns the tombstone and fork-steer age boundaries.
    The sid union handles forks whose claim still names their earlier session;
    sites that already key on the union (`:1885, :1920,
    :1950, :2012, :2090, :2886, :5916, :6078, :6275, :6395, :6431, :6593, :6594, :6664,
    :6674, :6685, :6779, :7254, :10193, :12154, :12155, :12216, :12993`).
    No foreign sid enters a record's retired_sids: every writer appends the record's
    OWN prior sid alone: :5185, :5519, :8699,
    :13318. This makes union identity safe; the age boundary distinguishes respawn.
    Missing registry data falls back to the bare sid comparison.
    """
    return bool(_releaser_live_sids(claim, live_sids, registry=registry))


def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS,
                              caller_sid=None, nonce_valid: bool = False,
                              holder_limited: bool = False, registry=None):
    """Apply boot claim rules in order; return (verdict, reason), without IO.
    0. No claim: claim fresh.
    1. Released: claim fresh unless its releaser remains live (B6).
    1b. A limited holder with a horizon and no proven resume: limit-transfer
        (three-tier `:432-437`), before the roster-live refusal.
    2. Live holder: refuse unless this caller proves that holder's continuity.
    3. Proven continuity with gone or same holder: resume.
    4. Gone holder: freeze, refuse or seize by heartbeat and epoch evidence;
       otherwise refuse explicitly.
    A caller-supplied sid alone cannot disarm the live-holder check. Registry
    input enables the releaser union; absent input retains the bare comparison.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    if claim.get("state") == "released":
        # B6 (three-tier-command.md :1184-1190): a released claim remains blocked while
        # its releasing body is live. Share the comparison with the lifecycle gate so
        # boot and mutation agree on the release/stop window.
        released_by = claim.get("released_by_sid")
        if _releaser_is_roster_live(claim, live_sids, registry=registry):
            # Name actual live union sids: released_by_sid itself may already be gone.
            still = ", ".join(sorted(_releaser_live_sids(
                claim, live_sids, registry=registry))) or "?"
            return ("refuse", f"claim {claim.get('incarnation_id', '?')} is released by sid "
                              f"{released_by} but that body is still live in the roster as "
                              f"session(s) {still} -- release+stop is not complete; wait for "
                              f"that body to exit")
        return ("claim", f"predecessor {claim.get('incarnation_id', '?')} released cleanly "
                         f"-- fresh claim, no seizure")
    holder_sid = claim.get("session_id")
    holder_live = holder_sid in live_sids
    resume_ok = _claim_resume_allowed(nonce_valid, holder_sid, caller_sid, live_sids)
    if holder_limited and not resume_ok:
        # three-tier-command.md `:432-437`: a horizon-bearing limited holder permits
        # immediate transfer before roster liveness refuses it. Proven resume still
        # wins: a parked holder returning with continuity must retain its claim.
        return ("limit-transfer", f"claim holder {claim.get('incarnation_id', '?')} "
                                  f"(sid {holder_sid}) is parked limited with a recorded "
                                  f"horizon -- immediate transfer, not a seizure")
    if holder_live and not (holder_sid == caller_sid and nonce_valid):
        return ("refuse", f"claim holder {claim.get('incarnation_id', '?')} "
                          f"(sid {holder_sid}) is live in the roster")
    if resume_ok:
        age_txt = "unknown age"
        try:
            age_txt = f"{(now - _parse_iso(claim['heartbeat_at'])).total_seconds():.0f}s"
        except (KeyError, TypeError, ValueError):
            pass
        return ("resume", f"resumed own claim after {age_txt} -- continuity proved, "
                          f"no seizure")
    # Require roster absence explicitly before journaling verdicts that assert it.
    # The audit record must not state a premise the decision never checked.
    if holder_live:
        return ("refuse", "holder is roster-live -- the guard should have caught this; "
                          "refusing rather than deciding")
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
    # Name the ambiguity and escalation, never a unilateral seizure lever.
    return ("freeze", f"holder roster-gone but heartbeat fresh ({age:.0f}s <= "
                      f"{stale_seconds:.0f}s) -- daemon restart? (G9). The holder may "
                      f"still be LIVE and closing out: roster-gone does not imply dead. "
                      f"This verdict is a snapshot -- re-verify at act time; if still "
                      f"ambiguous, stop and escalate to the operator. "
                      f"Never seize on ambiguity.")


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
    """Render GOALS, journal tail, knowledge index, roster and fleet status.
    Registry verdicts come from status_snapshot.
    """
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
    # Apply the same worker-turn gate as other sup verbs before the roster read.
    # Admitting a worker here would mint a claim that even release refuses.
    # Supervisor-shaped and unresolved dispatch-window identities remain eligible.
    _boot_ident = _acting_worker_identity(sid=caller_sid)
    if _acting_body_is_worker_turn(ident=_boot_ident) is True:
        raise FleetCliError(
            f"sup-boot: refusing --{_worker_turn_note(_boot_ident)} "
            f"Escalate to the supervisor session.")
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    epoch_ok, epoch_reason = supervisor_epoch_check(roster_ok, payload)
    entries = payload if roster_ok else []
    live_sids = _roster_live_sids(entries)

    inc_line = None
    notices = []
    if getattr(args, "handoff_inc", None):
        # Claim-pending successors write HANDSHAKE only. Mint their nonce here so
        # plaintext reaches only the successor's stdout; the predecessor verifies its
        # dispatch token hash. Hold the lock across current-attempt check and write
        # so a later begin cannot let this body clobber another attempt's HANDSHAKE.
        token = getattr(args, "handoff_token", None)
        succ_value = mint_nonce()
        with fleet_lock():
            refusal = handoff_boot_refusal(read_incarnation(), args.handoff_inc)
            if refusal is None:
                write_handshake(args.handoff_inc, caller_sid,
                                handoff_token_hash=nonce_digest(token) if token else None,
                                nonce_hash=nonce_digest(succ_value))
        if refusal is not None:
            # A refused successor receives neither HANDSHAKE nor generation.
            verdict = "handoff-refused"
            reason = refusal
            rc = SUPERVISOR_BOOT_HANDOFF_REFUSED_RC
        else:
            notices.append(f"NONCE: {succ_value}")
            verdict = "handshake-written"
            reason = (f"successor {args.handoff_inc} awaiting claim transfer; "
                      f"take NO fleet actions until sup-status shows your incarnation")
            rc = 0
    else:
        with fleet_lock():
            # Compact refusal evidence under the boot lock, before the decision, so
            # even a refused boot bounds the log without involving concurrent refused writers.
            _compact_nonce_rejection_log()
            claim = read_incarnation()
            # Sweep fixed supervisor task paths under the boot lock: worker cleanup cannot
            # reach them. The successor branch skips this sweep of its own input file.
            sweep_handoff_task_files(claim)
            latest = supervisor_journal_latest()
            # The boot decision needs both caller identity and proven generation continuity.
            presented = None if claim is None else _nonce_presentation(
                claim, getattr(args, "nonce", None))
            if not epoch_ok:
                verdict, reason = "freeze", f"epoch check failed: {epoch_reason}"
            else:
                verdict, reason = supervisor_claim_decision(
                    claim, live_sids, latest, caller_sid=caller_sid,
                    nonce_valid=presented is not None,
                    # Resolve registry evidence under this lock for the pure decision function.
                    # Unreadable registry leaves B6's bare comparison without aborting boot.
                    holder_limited=claim is not None and _holder_is_limited(
                        claim.get("session_id")),
                    registry=_registry_records_or_none())
            if verdict == "claim":
                inc = mint_incarnation_id()
                value = mint_nonce()
                # Fresh literal claim writer: explicitly carry every required continuity field.
                fresh = {"incarnation_id": inc, "session_id": caller_sid,
                         "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                         "claimed_via": "fresh",
                         "nonce_hash": nonce_digest(value), "nonce_seq": 1,
                         "lineage_id": mint_lineage_id()}
                _carry_handoff_pending(claim, fresh)
                write_incarnation(fresh)
                supervisor_journal_append("BOOT", inc, caller_sid, f"fresh claim: {reason}")
                inc_line = inc
                notices.append(f"NONCE: {value}")
            elif verdict == "resume":
                # Proven resume restamps and refreshes the same claim, without seizure or new incarnation.
                if presented == "pending":
                    _acknowledge_pending(claim)
                claim["session_id"] = caller_sid
                claim["heartbeat_at"] = now_iso()
                notices.append(_mint_pending_nonce(claim))
                write_incarnation(claim)
                supervisor_journal_append("BOOT", claim["incarnation_id"], caller_sid,
                                          f"resumed own claim: {reason}")
                inc_line = claim["incarnation_id"]
            elif verdict in ("seize", "limit-transfer"):
                inc = mint_incarnation_id()
                value = mint_nonce()
                dead = claim.get("incarnation_id", "?")
                # three-tier `:429` requires a distinct limit-transfer journal kind: the
                # audit record must not describe a seizure that did not occur.
                kind = "SEIZED" if verdict == "seize" else "LIMIT-TRANSFER"
                took = "seized from" if verdict == "seize" else "limit-transfer from"
                try:
                    # Discard an orphan HANDSHAKE so a crash residue cannot receive a transfer.
                    handshake_path().unlink()
                except FileNotFoundError:
                    pass
                # Recovery literal writer: mint a new lineage for seize and limit-transfer.
                # A parked predecessor can return; it has not vouched for transfer of worker ownership.
                taken = {"incarnation_id": inc, "session_id": caller_sid,
                         "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                         "claimed_via": verdict if verdict != "seize" else "seize",
                         "nonce_hash": nonce_digest(value), "nonce_seq": 1,
                         "lineage_id": mint_lineage_id()}
                _carry_handoff_pending(claim, taken)
                write_incarnation(taken)
                supervisor_journal_append(kind, inc, caller_sid,
                                          f"{took} {dead}: {reason}")
                inc_line = inc
                notices.append(f"NONCE: {value}")
            # refuse / freeze: strictly read-only.
        rc = SUPERVISOR_BOOT_RC[verdict]

    bundle = _render_boot_bundle(entries, status_snapshot(), supervisor_journal_entries())
    # Run lifecycle reaping only after successful boot; successors skip it.
    reap_line = (_supervisor_reap_line(run=run, which=which, caller_sid=caller_sid)
                 if rc == 0 and not getattr(args, "handoff_inc", None) else
                 "reaped: 0 rows (deferred: boot has not acquired the claim)")
    lines = [bundle, "", reap_line, SUPERVISOR_REAP_RULE, "",
             f"EPOCH: {'ok' if epoch_ok else 'FAIL'} -- {epoch_reason}"]
    if inc_line:
        lines.append(f"INCARNATION: {inc_line}")
    lines.append(f"VERDICT: {verdict} -- {reason}")
    _write_text_tolerating_console_encoding("\n".join(lines) + "\n")
    # Deliver only the newly minted plaintext once, on this verb's stdout.
    _deliver_notices(notices)
    return rc


def _claim_is_legacy(claim: dict) -> bool:
    """A legacy claim has neither nonce_hash nor state.
    Released claims lack a nonce too; requiring absent state prevents a released
    claim from being resurrected through legacy sid equality.
    """
    return "nonce_hash" not in claim and "state" not in claim


def _wedged_release_gate(verb, claim):
    """Refuse when a released claim still has a live releasing body.
    This gate arm fetches the roster only for released claims naming a releaser.
    No nonce can prove continuity after release because all generations are gone.
    Report the actual live union sids, not just a possibly vanished released_by_sid;
    fleet tombstones or those sessions leaving the roster end the wedge.
    """
    released_by = claim.get("released_by_sid")
    if not isinstance(released_by, str) or not released_by:
        return                          # names no releaser -- nothing to gate
    roster_ok, payload = _fetch_agents_roster()
    if not roster_ok:
        return                          # roster unreadable: fail OPEN
    live_now = _releaser_live_sids(claim, _roster_live_sids(payload),
                                   registry=_registry_records_or_none())
    if not live_now:
        return                          # release+stop completed -- claim open
    still = ", ".join(sorted(live_now))
    raise SupervisorClaimGateError(
        f"{verb}: refusing -- the supervisor claim "
        f"({claim.get('incarnation_id', '?')}) is RELEASED but the body that "
        f"released it (sid {released_by}) is still live in the roster as "
        f"session(s) {still}, so no body holds the claim and the fleet has no "
        f"supervisor. That body was told to exit and has not; until it does, "
        f"no successor can boot (claim-nonce §6.1 rule 1) and this gate stays "
        f"armed. There is no generation to present -- a released claim carries "
        f"none. If you ARE that body: stop taking fleet actions and exit. "
        f"Otherwise escalate to the operator, who can stop session(s) {still} "
        f"directly -- those are the live ones; sid {released_by} may already "
        f"be gone. This is a SPEED-BUMP, not a security boundary: it is "
        f"bypassable by anyone who can run this command without a session id.")


GATE_VERBS_ACCEPTING_NONCE = frozenset({
    "init", "spawn", "send", "resume-limited", "interrupt", "release",
    "respawn", "kill", "clean", "archive", "sup-spawn",
})
"""The gated verbs whose parser actually declares `--nonce`, i.e. the ones the
refusal below may honestly name that flag to (R2, ruling 2026-07-26: **a named
remedy that always fails is a defect**).

This exists because §7 shipped one. `_supervisor_gate` is armed with the verb
string of the FRAME, which is not necessarily the command the caller ran: the
autoclean sweep's tier 1 is `cmd_archive`, so between 2026-07-27 and 2026-07-28
a beat-driven `fleet autoclean` was refused with *"archive: refusing ... present
`--nonce`"* while **`fleet autoclean` has no `--nonce` flag at all**
(`autoclean --help | grep -c nonce` -> 0; `archive --help` -> 2). Both real
drivers were told to do something neither could do -- the interface tier holds
no generation by design (§7.1) and the supervisor's beat had no flag to present
one through. Found by the four-councilor §7 council, 2026-07-28, which
classified it a live R2 violation rather than a convenience defect.

The exemption fixed that instance. **This set fixes the shape**, which rider 1
says will recur: an exemption is carried per-frame, so any future frame that
arms the gate under a nonce-less entry point re-creates exactly this refusal.
When the verb is not in here the refusal says so and names a remedy its audience
can perform (report the bug) instead of a flag that does not exist.

NOT hand-maintained truth: `tests/test_supervisor_gate.py::
TestTheRefusalNeverNamesAnUnreachableRemedy` derives the real set from
`build_parser()` and from the `_supervisor_gate` call sites and asserts equality
both ways, so a verb added to the gate without a flag, or a flag removed from a
gated verb, is a test failure and not a silently unreachable remedy."""


def _supervisor_gate(verb, nonce=None, now=None, send_target=None):
    """Gate mutating lifecycle verbs for sid-bearing callers under a fresh held claim.
    Raise SupervisorClaimGateError unless the caller proves continuity. READ-ONLY:
    no lock, no mint, no write. Views and authoritative reads never call this gate.
    This is a continuity speed-bump, not a security boundary: a shell without a
    caller sid bypasses it. Absent, legacy or stale claims disarm; unreadable
    heartbeat or roster data fails open so the gate cannot brick maintenance.
    A released claim with a live releaser arms independently of heartbeat and
    has no nonce remedy; _wedged_release_gate owns that arm.
    Autoclean's effect-based exemption crosses delegation via as_autoclean_tier:
    the sweep performs no dispatch, steer or claim operation. Each reachable
    frame must carry the exemption. Send to the current claim holder has its
    own identity-checked mailbox carve-out below. Validation never rotates a nonce.
    """
    caller = current_caller_session()
    if caller is None:
        return
    try:
        claim = read_incarnation()
    except Exception:  # noqa: BLE001 -- speed-bump: never crash a verb on this
        return
    if not isinstance(claim, dict):
        return
    if claim.get("state") == "released":
        # Unexpected roster or registry failures must not crash a mutating verb.
        # Preserve SupervisorClaimGateError itself: swallowing refusal would disarm the gate.
        try:
            return _wedged_release_gate(verb, claim)
        except SupervisorClaimGateError:
            raise
        except Exception:  # noqa: BLE001 -- speed-bump: never crash a verb on this
            return
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        age = (now - _parse_iso(claim["heartbeat_at"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return                      # unreadable beat: fail open
    if age > SUPERVISOR_CLAIM_STALE_SECONDS:
        return                      # stale: disarmed (§4.13(e))
    if _claim_is_legacy(claim):
        return                      # no generation to demand (§9)
    if _nonce_presentation(claim, nonce) is not None:
        return                      # continuity proved -- validate without minting
    # Send to the current claim holder is an upward mailbox append and needs no nonce.
    # Resolve the physical record first, then compare identity against this claim;
    # a moved claim or supervisor-shaped husk does not qualify. Other verbs stay gated.
    # SAFETY INVARIANT: no foreign sid enters retired_sids; each
    # writer appends that record's OWN prior sid alone (:5185, :5519, :8699,
    # :13318) -- so union identity cannot make one body answer for another.
    # Read registry identity without quarantine; unreadable data declines the carve-out.
    if verb == "send" and send_target is not None:
        # `_registry_records_or_none`, NEVER `load_registry`: this gate is read-only.
        # load_registry QUARANTINES a corrupt registry -- it RENAMES the
        # file aside (`:892`), which is a write. Routing the identity read
        # through the read-only helper preserves evidence.
        # The helper declines unreadable data and
        # names this gate as its reason (`:10167`).
        # Unreadable or malformed records provide no holder proof and leave the gate armed.
        _records = _registry_records_or_none()
        _workers = _records.get("workers") if isinstance(_records, dict) else None
        resolved_rec = (_workers.get(send_target)
                        if isinstance(_workers, dict) else None)
        if (resolved_rec is not None
                and _record_is_supervisor_claim_holder(resolved_rec, claim=claim) is True):
            return
    # Only offer --nonce when the actual entry point accepts it; the gate frame
    # label can differ from the command the caller ran.
    if verb in GATE_VERBS_ACCEPTING_NONCE:
        remedy = ("Present the current generation with `--nonce <value>` "
                  "(the value the last `sup-*` verb printed), or escalate to "
                  "the supervisor session.")
    else:
        remedy = (f"THERE IS NOTHING YOU CAN PRESENT: `fleet {verb}` declares no "
                  f"`--nonce` flag, so this refusal cannot be satisfied by any "
                  f"caller and must not be routed around. It is a BUG IN FLEET "
                  f"-- §7's gate armed at a frame reached from a verb with no way "
                  f"to prove continuity, which is what claim-nonce §7 rider 1 "
                  f"(the exemption is carried explicitly at every frame, never "
                  f"inherited from the call graph) exists to prevent. REPORT IT.")
    raise SupervisorClaimGateError(
        f"{verb}: refusing -- a supervisor claim ({claim.get('incarnation_id', '?')}) "
        f"is held and fresh, and this call did not prove continuity on it "
        f"(claim-nonce §7). {remedy} This is a SPEED-BUMP, "
        f"not a security boundary: it is bypassable "
        f"by anyone who can run this command without a session id, and it is armed "
        f"only while the claim's heartbeat is fresh.")


def _caller_proven_lineage(caller, nonce):
    """Return lineage proven by a presented claim generation, or None.
    Read without minting or writing: destructive verbs use the result for worker
    ownership. Legacy, released or unreadable claims give no lineage proof.
    """
    try:
        claim = read_incarnation()
    except Exception:  # noqa: BLE001 -- guard path: never crash a kill on this
        return None
    if not isinstance(claim, dict) or claim.get("state") == "released":
        return None
    if _claim_is_legacy(claim):
        return None
    if _nonce_presentation(claim, nonce) is None:
        return None
    return claim.get("lineage_id")


def _spawning_claim_lineage(caller):
    """Return the current holder's lineage to stamp dispatch provenance, or None.
    Match the holder sid; this records ownership without rotating or proving a
    nonce. An un-restamped fork falls back to spawned_by sid ownership. Never raise.
    """
    try:
        claim = read_incarnation()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(claim, dict) or claim.get("state") == "released":
        return None
    if claim.get("session_id") == caller:
        return claim.get("lineage_id")
    return None


def nonce_rejection_log_path() -> Path:
    """§5.6's evidence file. Under `state/` (gitignored runtime)."""
    return state_dir() / "supervisor-nonce-rejections.jsonl"


def _append_nonce_rejection(kind, verb, caller_sid, claim: dict, presented) -> None:
    """Atomically append one refusal record; failures must not prevent refusal.
    Use the single-syscall appender so concurrent refusals cannot overwrite each
    other; compaction runs out of band under fleet_lock. Store only a digest
    prefix of the presented value. Claim and lineage identity come from the
    loaded claim, never caller-supplied provenance, so doctor can scope evidence.
    """
    record = {
        "ts": now_iso(),
        "kind": kind,
        "verb": verb,
        "caller_sid": caller_sid,
        "incarnation_id": claim.get("incarnation_id"),
        "lineage_id": claim.get("lineage_id"),
        "expected_seq": claim.get("nonce_seq"),
        "pending_at": claim.get("pending_at"),
        "presented_prefix": nonce_digest(presented)[:8] if isinstance(presented, str)
                            and presented else None,
    }
    try:
        nonce_rejection_log_path().parent.mkdir(parents=True, exist_ok=True)
        _atomic_append_bytes(nonce_rejection_log_path(),
                             (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    except (OSError, ValueError):
        pass


def _compact_nonce_rejection_log(limit=NONCE_REJECTION_LOG_MAX_RECORDS) -> None:
    """Keep the newest refusal records under the caller-held fleet_lock.
    Run at sup-boot, outside the concurrent refusal writer. This fixed supervisor
    path belongs to no worker cleanup. Best-effort hygiene must never fail boot.
    """
    path = nonce_rejection_log_path()
    try:
        if not path.exists():
            # Skip a doomed read when the file is absent.
            return
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) <= limit:
            return
        # Atomic replacement keeps concurrent observers from seeing a partial log rewrite.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def _recent_nonce_rejections(now=None, window=NONCE_REJECTION_WINDOW_SECONDS) -> list:
    """Read recent refusal records from a bounded, newest-biased tail.
    Unreadable logs yield no records; compaction is hygiene, not a reader prerequisite.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    out = []
    for line in _read_tail_lines(nonce_rejection_log_path()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            if (now - _parse_iso(rec["ts"])).total_seconds() <= window:
                out.append(rec)
        except (ValueError, TypeError, KeyError):
            continue
    return out


def _rejection_is_about_current_claim(rec: dict, claim) -> bool:
    """Whether a refusal record is evidence about the current claim; pure and total.
    Compare lineage when both carry one, preserving evidence across handoff.
    Otherwise require a timestamp at or after claimed_at; ties count because
    stamps have second precision. Unknown claim identity or time stays armed:
    a missed second body costs more than a census caused by a false alarm.
    """
    if not isinstance(claim, dict):
        return True
    rec_lineage = rec.get("lineage_id")
    claim_lineage = claim.get("lineage_id")
    if rec_lineage and claim_lineage:
        return rec_lineage == claim_lineage
    try:
        return _parse_iso(rec["ts"]) >= _parse_iso(claim["claimed_at"])
    except (KeyError, TypeError, ValueError):
        return True


def _nonce_presentation(claim: dict, nonce):
    """Classify a presented generation as live, pending, prior, or None; pure.
    Retain one replaced pending generation so TTL replacement does not immediately
    lock out a slower body. Boot and holder validation share this slot ordering.
    """
    if nonce_matches(nonce, claim.get("nonce_hash")):
        return "live"
    if nonce_matches(nonce, claim.get("pending_nonce_hash")):
        return "pending"
    if nonce_matches(nonce, claim.get("prior_pending_hash")):
        return "prior"
    return None


def _acknowledge_pending(claim: dict) -> None:
    """Promote the acknowledged pending generation in memory.
    Clear all pending slots, including prior, so acknowledgment retires every
    earlier generation rather than leaving an old value presentable.
    """
    claim["nonce_hash"] = claim["pending_nonce_hash"]
    claim["nonce_seq"] = claim.get("nonce_seq", 1) + 1
    for key in ("pending_nonce_hash", "pending_at", "prior_pending_hash"):
        claim.pop(key, None)


def _continuity_refusal(verb, claim: dict) -> FleetCliError:
    """Build an agent-facing refusal naming ambiguity and human escalation.
    Do not name a unilateral recovery lever: either indistinguishable body may
    be legitimate. Human recovery instructions live in the supervisor runbook.
    """
    return SupervisorContinuityError(
        f"{verb}: continuity proof failed (expected generation "
        f"{claim.get('nonce_seq', '?')}) -- a second body of your lineage may be "
        f"acting. STOP: take no further supervisor actions and escalate to the "
        f"operator.")


SPEED_BUMP_NOTE = (
    "(A speed-bump, not a security boundary: the identity behind it is the "
    "registry's verdict on an environment-supplied session id -- settable by "
    "anyone who can run this command, and donatable by the daemon that hosts "
    "the session.)")


def _worker_turn_note(ident) -> str:
    """Explain a resolved or all-worker ambiguous worker-turn refusal.
    Return empty when the gate does not fire. Name all ambiguous records so the
    operator can resolve stale ownership without guessing which body is acting.
    Registry sid identity remains a speed-bump, not a security boundary.
    """
    if _acting_body_is_worker_turn(ident=ident) is not True:
        return ""
    if ident["verdict"] == IDENTITY_AMBIGUOUS:
        names = ", ".join(repr(n) for n in ident["candidates"])
        return (f" This is a worker turn: {len(ident['candidates'])} registry "
                f"records carry this session's id ({names}) and every one of "
                f"them is an ordinary worker, so whichever this body is, it is "
                f"a worker -- and the supervisor claim is not a worker's to "
                f"hold (claim-nonce §6.5 D5, keyed on the registry per "
                f"SPEC.md:204). One session cannot be two workers: inspect "
                f"those records in state/fleet.json and retire the stale one. "
                + SPEED_BUMP_NOTE)
    return (f" This is a worker turn: the registry resolves this session to "
            f"worker {ident['name']!r}, and the supervisor claim is not a "
            f"worker's to hold (claim-nonce §6.5 D5, keyed on the registry per "
            f"SPEC.md:204). " + SPEED_BUMP_NOTE)


def _identity_abstention_note(ident) -> str:
    """Name the unreadable, ambiguous or quarantined identity condition.
    Quarantined data needs restoration; sending that case back to doctor alone
    cannot repair a registry already renamed aside.
    """
    if not ident.get("registry_read"):
        artifacts = _quarantine_artifacts()
        if artifacts and not registry_path().exists():
            return (f"state/fleet.json is GONE and {artifacts[-1].name} sits "
                    f"beside it -- a corrupt registry was quarantined, so this "
                    f"absence is a repaired incident and not a fresh install; "
                    f"restore the quarantined file, then remove the artifact")
        return "state/fleet.json could not be read"
    if ident["verdict"] == IDENTITY_AMBIGUOUS:
        names = ", ".join(repr(n) for n in ident["candidates"])
        return (f"{len(ident['candidates'])} records carry this session's id "
                f"({names}) and they do not agree on whether it is a worker")
    return f"registry verdict for this session: {ident['verdict']}"


def _mint_pending_nonce(claim: dict, now=None) -> str:
    """Mint in memory when no pending exists or its TTL expires; return a notice.
    The caller commits once and emits the notice afterward. Preserve the replaced
    hash in one prior slot so a slower body retains a presentable generation;
    a second replacement drops the oldest. Unreadable pending_at counts as expired.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    seq = claim.get("nonce_seq", 1)
    outstanding = claim.get("pending_nonce_hash")
    if outstanding:
        try:
            age = (now - _parse_iso(claim["pending_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            age = None
        if age is not None and age <= PENDING_NONCE_TTL_SECONDS:
            return f"NONCE: unchanged (generation {seq + 1} already outstanding)"
        claim["prior_pending_hash"] = outstanding
    value = mint_nonce()
    claim["pending_nonce_hash"] = nonce_digest(value)
    claim["pending_at"] = now_iso()
    return f"NONCE: {value}"


def _deliver_notices(notices) -> None:
    """§5.3's delivery step: the plaintext of a newly minted generation is
    printed ONCE, on the minting verb's own stdout, AFTER the commit, and
    nowhere else. Routed through the console-encoding-tolerant writer every
    other supervisor output uses, so no supervisor path prints through a raw
    `print` a legacy code page could crash on."""
    for line in notices:
        _write_text_tolerating_console_encoding(line + "\n")


def _require_claim_holder(sid_override=None, nonce=None, verb="sup", mint=True, now=None):
    """Return (claim, caller_sid, notices) on continuity proof, else raise FleetCliError.
    Caller must hold fleet_lock and commit exactly one write_incarnation afterward
    so acknowledgment, mint and verb mutation are atomic. Emit notices only after
    commit; failed verbs must neither rotate nor deliver a generation.
    Validation: live accepts; pending accepts and promotes; prior accepts quietly;
    legacy sid equality upgrades once subject to affirmative non-worker identity
    and quarantine completeness; all other values refuse. Worker turns are gated
    before claim reads. This enforces the journal's single-writer contract.
    """
    # Resolve caller identity once, including --sid, for role and continuity checks.
    # SPEC.md:281 makes refused the doctor alarm kind, so role classification must
    # use the same caller whose continuity is being tested.
    caller = sid_override or current_caller_session()
    if not caller:
        raise FleetCliError("caller session unknown -- pass --sid or run from a Claude session")
    # Gate worker turns by registry sid union before reading the claim.
    # SPEC.md:204 forbids FLEET_WORKER as the identity key; the environment witness
    # is not body identity. A worker must not upgrade a legacy claim via sid equality.
    # Unresolved dispatch windows and supervisor-shaped bodies abstain; all-worker
    # ambiguity refuses, while mixed ambiguity abstains. An unreadable registry
    # also abstains here so release can recover; legacy upgrade below requires
    # affirmative non-worker identity and a complete registry.
    # RATIFIED DOCTRINE -- claim-nonce §18:
    # The daemon substitutes the session environment wholesale, therefore no
    # FLEET_WORKER observation, present or absent, is evidence about this body.
    # The sid is trustworthy: the vendor stamps each hosted session's own sid over
    #  the substituted environment, closed in the safe direction by counting, and
    #  every other env observation on a hosted body is evidence about the daemon's
    #  cold-starter, not about the body; the registry sid union is the only sound
    #  identity channel. This is the registry-keyed gate SPEC.md:204 requires.
    ident = _acting_worker_identity(sid=caller)
    worker_turn = _acting_body_is_worker_turn(ident=ident)
    if worker_turn is True:
        raise FleetCliError(
            f"{verb}: refusing --{_worker_turn_note(ident)} "
            f"Escalate to the supervisor session.")
    claim = read_incarnation()
    if claim is None:
        raise FleetCliError("no supervisor claim exists -- run `fleet sup-boot` first.")

    notices = []
    if claim.get("state") == "released":
        # Released is terminal outside sup-boot; do not mislabel a clean release
        # as second-body continuity ambiguity.
        raise FleetCliError(
            f"{verb}: claim {claim.get('incarnation_id', '?')} was released "
            f"{claim.get('released_at', '?')} -- there is no holder to be. "
            f"Run `fleet sup-boot` to claim afresh.")
    if _claim_is_legacy(claim):
        # Legacy claims honor sid equality once, then upgrade.
        if caller != claim.get("session_id"):
            raise FleetCliError(
                f"caller sid {caller} does not hold the claim (holder: "
                f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
                f"the journal is single-writer, claim-holder-only (spec §4)")
        # Legacy upgrade requires affirmative non-worker identity, never abstention: it
        # mints generation one without any presented nonce. Refuse unreadable identity
        # loudly but do not log second-body evidence (SPEC.md:281) for a matching holder
        # with a broken registry. Repair may rename corrupt data; the completeness
        # guard below also checks remaining quarantine artifacts.
        if _acting_body_is_worker_turn(ident=ident) is not False:
            raise FleetCliError(
                f"{verb}: refusing -- this is a §9 legacy claim, whose upgrade "
                f"is granted on sid equality alone with no generation "
                f"presented, and the registry cannot confirm that this session "
                f"is not a worker turn ({_identity_abstention_note(ident)}). "
                f"An upgrade that mints generation 1 needs an affirmative "
                f"answer, not an abstention. Repair `state/fleet.json` "
                f"(`fleet doctor --repair`), or run this from a session the "
                f"registry can place.")
        # Require completeness as well as readable identity: a recreated registry may
        # omit live records now held in quarantine. Presence alone blocks upgrade.
        # PRESENCE-ONLY, REGISTRY PRESENT OR NOT, verbatim as _sweep_husks
        # spells it at `:7225`. Rename preserves mtime, so age ordering cannot prove
        # that a newer registry restored all quarantined records. Scope this check to
        # legacy upgrade: making the shared identity reader abstain would let a known
        # worker through the earlier worker-turn gate.
        legacy_artifacts = _quarantine_artifacts()
        if legacy_artifacts:
            raise FleetCliError(
                f"{verb}: refusing -- this is a §9 legacy claim, whose upgrade "
                f"is granted on sid equality alone with no generation "
                f"presented, and {legacy_artifacts[-1].name} sits in state/. A "
                f"corrupt registry was renamed aside, so the registry that just "
                f"placed this session is missing whatever that file held -- "
                f"including, possibly, the record that would call this session a "
                f"worker. An upgrade that mints generation 1 needs a COMPLETE "
                f"registry, not merely a readable one. Restore the quarantined "
                f"file, then remove the artifact -- the same remedy the husk "
                f"sweep asks for.")
        value = mint_nonce()
        claim["nonce_hash"] = nonce_digest(value)
        claim["nonce_seq"] = 1
        notices.append(f"NONCE: {value}")
        # Deliver only the new live generation on upgrade; a second pending value
        # would make the most recently delivered generation ambiguous.
        mint = False
    elif _nonce_presentation(claim, nonce) == "pending":
        _acknowledge_pending(claim)                       # rule 2
    elif _nonce_presentation(claim, nonce) == "prior":
        # Prior pending is valid after TTL replacement. Log it quietly and distinctly
        # from refusal so a slow legitimate body does not look like a second-body attack.
        _append_nonce_rejection("superseded-pending", verb, caller, claim, nonce)
    elif _nonce_presentation(claim, nonce) is not None:
        pass                                              # rule 1 (live)
    else:
        # Every remaining failed proof is refused (SPEC.md:281), the doctor's evidence
        # kind. Worker turns have already been handled using the same caller identity.
        _append_nonce_rejection("refused", verb, caller, claim, nonce)
        raise _continuity_refusal(verb, claim)

    # Restamp validated writes so registry identity follows the acting fork.
    claim["session_id"] = caller
    if mint:
        notices.append(_mint_pending_nonce(claim, now=now))
    return claim, caller, notices


def cmd_sup_checkpoint(args) -> int:
    """`fleet sup-checkpoint <body|@file> [--kind CHECKPOINT|PROPOSAL] [--sid S]`.
    Every checkpoint refreshes the heartbeat (spec §4: 'the holder refreshes
    at every checkpoint/beat')."""
    body = _read_task_arg(args.body)
    with fleet_lock():
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-checkpoint")
        supervisor_journal_append(args.kind, claim["incarnation_id"], caller, body)
        roll = roll_supervisor_journal()
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"checkpointed ({args.kind}) as {claim['incarnation_id']}; heartbeat refreshed")
    if roll["rolled"]:
        print(f"journal board rolled: {roll['moved_bytes']} bytes to "
              f"{supervisor_journal_history_path()}")
    _deliver_notices(notices)
    return 0


def cmd_journal_roll(args) -> int:
    """`fleet journal-roll` -- keep only the newest three checkpoints.

    A malformed board is reported and left untouched.  The command takes the
    same single-writer lock as supervisor journal append so an explicit roll
    cannot race a checkpoint.
    """
    with fleet_lock():
        result = roll_supervisor_journal()
    if result["rolled"]:
        print(f"journal board rolled: {result['moved_bytes']} bytes to "
              f"{supervisor_journal_history_path()}")
    else:
        print(f"journal board unchanged: {result['checkpoints']} checkpoints")
    return 0


# CLI: wave-close -- one mechanically bounded wave boundary.

WAVE_CLOSE_EXPECTED_FAILURES = frozenset({
    "tests/test_fleet_index.py::TestPathContainment::test_the_choke_point_refuses_a_drive_qualified_rel_and_writes_nothing",
    "tests/test_fleet_index.py::TestPathContainment::test_a_drive_qualified_rel_cannot_overwrite_a_file_outside_the_root",
    "tests/test_fleet_index.py::TestPathContainment::test_the_update_library_surface_refuses_a_drive_qualified_rel",
    "tests/test_fleet_q.py::TestOutlinePathContainment::test_an_absolute_path_outside_the_root_is_refused_too",
    "tests/test_terminal_surface.py::TestCollaboratorInstall::test_fleet_python_may_be_a_path_containing_spaces",
    "tests/test_terminal_surface.py::TestCollaboratorInstall::test_fleet_python_still_accepts_a_multi_word_command",
})
WAVE_CLOSE_PUSH_ATTEMPTS = 4  # initial push plus three retries
WAVE_CLOSE_PUSH_WINDOW_SECONDS = 300.0


def _wave_git(repo, *argv, run=subprocess.run, check=True):
    """Run one injectable non-shell git command for wave-close."""
    try:
        result = run(["git", *argv], cwd=str(repo), capture_output=True,
                     text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        raise FleetCliError(f"wave-close: git {argv[0]} failed: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise FleetCliError(f"wave-close: git {' '.join(argv)} failed"
                            + (f": {detail[:300]}" if detail else ""))
    return result


def _wave_repo_root(run=subprocess.run):
    """Resolve the checkout containing the caller's current directory."""
    result = _wave_git(Path.cwd(), "rev-parse", "--show-toplevel", run=run)
    root = Path(result.stdout.strip()).resolve()
    if not root.is_dir():
        raise FleetCliError(f"wave-close: git root is not a directory: {root}")
    return root


def _wave_previous_close(repo, run=subprocess.run):
    """Find the newest prior close commit for the default accounting base."""
    result = _wave_git(repo, "log", "--format=%H%x09%s", "HEAD", run=run)
    for line in result.stdout.splitlines():
        commit, _, subject = line.partition("\t")
        if re.fullmatch(r"fleet wave-close: wave \d+", subject.strip()):
            return commit
    raise FleetCliError(
        "wave-close: no previous `fleet wave-close: wave N` commit found; "
        "supply --base explicitly")


def _wave_merge_commits(repo, base, run=subprocess.run):
    result = _wave_git(repo, "log", "--merges", "--format=%H",
                       f"{base}..HEAD", run=run)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _wave_changelog_gaps(repo, base, extra="", run=subprocess.run):
    """Return merge SHAs since base that have no CHANGELOG line."""
    path = Path(repo) / "docs" / "CHANGELOG.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    text += "\n" + (extra or "")
    gaps = []
    for commit in _wave_merge_commits(repo, base, run=run):
        short = commit[:7]
        if not any(re.search(rf"(?<![0-9a-f]){re.escape(token)}"
                            rf"(?![0-9a-f])", text, re.IGNORECASE)
                   for token in (commit, short)):
            gaps.append(short)
    return gaps


def _wave_protected_unread_mail(verdicts):
    """Count rows whose reap veto specifically says unread mail."""
    if not isinstance(verdicts, dict):
        return 0
    return sum(1 for verdict in verdicts.values()
               if isinstance(verdict, tuple) and len(verdict) >= 2
               and not verdict[0] and verdict[1] == "unread-mail")


def _wave_numstat(repo, base, run=subprocess.run):
    """Return additions/deletions in the five non-overlapping accounting buckets."""
    result = _wave_git(repo, "diff", "--numstat", f"{base}..HEAD", run=run)
    buckets = {name: [0, 0] for name in
               ("bin", "tests", "docs", "journal", "other")}
    paths = []
    for raw in result.stdout.splitlines():
        fields = raw.split("\t", 2)
        if len(fields) != 3:
            continue
        added, removed, path = fields
        if added.isdigit() and removed.isdigit():
            counts = (int(added), int(removed))
        else:
            # Git reports binary files as ``-``.  The path is still recorded,
            # but a line count cannot honestly be invented for it.
            counts = (0, 0)
        posix = path.replace("\\", "/")
        if posix == "supervisor/JOURNAL.md" or posix.startswith(
                "supervisor/journal-history/"):
            bucket = "journal"
        elif posix.startswith("bin/"):
            bucket = "bin"
        elif posix.startswith("tests/"):
            bucket = "tests"
        elif posix.startswith("docs/"):
            bucket = "docs"
        else:
            bucket = "other"
        buckets[bucket][0] += counts[0]
        buckets[bucket][1] += counts[1]
        paths.append(path)
    return buckets, paths


def _wave_id(repo, run=subprocess.run):
    """Read the branch wave, otherwise increment the maximum wave across journal sources."""
    branch = _wave_git(repo, "branch", "--show-current", run=run).stdout.strip()
    match = re.search(r"(?:^|/)w(\d+)(?:[-/]|$)", branch)
    if match:
        return match.group(1)
    # Take the maximum wave across every journal source: board rolls move the
    # highest number into history, and first-match selection could reuse an old id.
    sources = [Path(repo) / "supervisor" / "JOURNAL.md",
               Path(repo) / "docs" / "CHANGELOG.md"]
    sources.extend(sorted((Path(repo) / "supervisor" / "journal-history").glob("*.md")))
    found = []
    for path in sources:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found.extend(int(value) for value in re.findall(r"THROUGHPUT wave (\d+)", text))
    if found:
        return str(max(found) + 1)
    return "UNMEASURED"


def _wave_token_pair(value):
    """Read one ``(input, output)`` pair from a durable usage shape."""
    if isinstance(value, dict):
        candidates = (
            ("input_tokens", "output_tokens"),
            ("input", "output"),
            ("in", "out"),
        )
        for incoming, outgoing in candidates:
            pair = (value.get(incoming), value.get(outgoing))
            if all(isinstance(item, int) and not isinstance(item, bool)
                   and item >= 0 for item in pair):
                return pair
    if isinstance(value, str):
        match = re.search(
            r"tokens\s*:\s*in\s*=\s*(\d+)\s+out\s*=\s*(\d+)",
            value, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def _wave_roster_claude_tokens(entries):
    """Sum Claude usage from expanded or compact roster token fields.
    Missing usage remains a source-specific measurement gap, not zero.
    """
    if not isinstance(entries, list):
        return "UNMEASURED (roster has no token field)"
    total = 0
    for entry in entries:
        if not isinstance(entry, dict):
            return "UNMEASURED (roster has no token field)"
        pair = None
        for candidate in (entry.get("usage"), entry.get("tokens"), entry):
            pair = _wave_token_pair(candidate)
            if pair is not None:
                break
        if pair is None:
            return "UNMEASURED (roster has no token field)"
        total += sum(pair)
    return str(total)


def _wave_registry_worker_count():
    """Count workers from the registry for callers requiring that source."""
    try:
        data = read_registry_no_repair(hint=False)
    except Exception:  # noqa: BLE001 - accounting must never invent a count
        return "UNMEASURED"
    workers = data.get("workers") if isinstance(data, dict) else None
    return str(len(workers)) if isinstance(workers, dict) else "UNMEASURED"


def _wave_lane_worktree(repo, lane, run=subprocess.run):
    """Return the worktree registered for a landed lane branch.

    The merge subject identifies the branch, but it does not identify the
    worker substrate. Git's worktree table is the durable join between that
    branch and the lane's own worker records.
    """
    result = _wave_git(repo, "worktree", "list", "--porcelain", run=run,
                       check=False)
    if result.returncode != 0:
        return None
    current = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current = Path(line[len("worktree "):].strip())
        elif current is not None and line == f"branch refs/heads/{lane}":
            return current
    return None


def _wave_worktree_entries(repo, run=subprocess.run):
    """Read linked worktrees as ``(path, branch)`` pairs."""
    result = _wave_git(repo, "worktree", "list", "--porcelain", run=run)
    entries = []
    path = branch = None
    for line in result.stdout.splitlines() + [""]:
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):].strip())
            branch = None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):].strip()
        elif not line and path is not None:
            entries.append((path, branch))
            path = branch = None
    return entries


def _wave_prune_landed_worktrees(repo, tip, run=subprocess.run):
    """Remove clean lane worktrees whose branches are ancestors of ``tip``.

    This is intentionally conservative: a dirty, unmerged, protected, or
    otherwise failed entry is reported and left in place. In particular,
    ``git worktree remove`` is never given ``--force`` and a branch is deleted
    only after its worktree removal succeeds.
    """
    stats = {"removed": 0, "skipped": 0,
             "unmerged": 0, "dirty": 0, "protected": 0, "failed": 0}
    current = Path.cwd().resolve()
    live_home = Path(FLEET_HOME).resolve()
    for raw_path, branch in _wave_worktree_entries(repo, run=run):
        if not branch or not re.fullmatch(r"w\d+/.+", branch):
            continue
        path = raw_path.resolve()
        if _wave_same_path(path, repo) or _wave_same_path(path, current) \
                or _wave_same_path(path, live_home):
            stats["skipped"] += 1
            stats["protected"] += 1
            continue
        merged = _wave_git(repo, "merge-base", "--is-ancestor", branch, tip,
                           run=run, check=False)
        if merged.returncode != 0:
            stats["skipped"] += 1
            stats["unmerged"] += 1
            print(f"wave-close: kept {path}: branch {branch} is unmerged",
                  file=sys.stderr)
            continue
        status = _wave_git(repo, "-C", str(path), "status", "--porcelain",
                           "--untracked-files=all", run=run, check=False)
        if status.returncode != 0:
            stats["skipped"] += 1
            stats["failed"] += 1
            print(f"wave-close: kept {path}: could not inspect worktree",
                  file=sys.stderr)
            continue
        if status.stdout.strip():
            stats["skipped"] += 1
            stats["dirty"] += 1
            print(f"wave-close: kept {path}: dirty worktree", file=sys.stderr)
            continue
        removed = _wave_git(repo, "worktree", "remove", str(path),
                            run=run, check=False)
        if removed.returncode != 0:
            stats["skipped"] += 1
            stats["failed"] += 1
            detail = (removed.stderr or removed.stdout or "").strip()
            print(f"wave-close: kept {path}: worktree remove failed"
                  + (f": {detail[:200]}" if detail else ""), file=sys.stderr)
            continue
        branch_deleted = _wave_git(repo, "branch", "-d", branch,
                                   run=run, check=False)
        stats["removed"] += 1
        if branch_deleted.returncode != 0:
            stats["failed"] += 1
            detail = (branch_deleted.stderr or branch_deleted.stdout or "").strip()
            print(f"wave-close: removed {path} but branch {branch} remains"
                  + (f": {detail[:200]}" if detail else ""), file=sys.stderr)
    return stats


def _wave_same_path(left, right):
    """Compare two record paths without requiring either path to exist."""
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right)))
    except (OSError, TypeError, ValueError):
        return False


def _wave_record_substrate(repo, worktree):
    """Read a substrate only from a record tied to ``worktree``.

    The fleet registry is the source for native worker records when it carries
    the explicit field. mcx records live in the lane worktree; their saved
    ``cwd`` plus the ``codex`` executable marker is the mcx record. Neither a
    branch name nor commit-message trailers are evidence of the substrate.
    """
    if worktree is None:
        return "unknown"
    registry = Path(repo) / "state" / "fleet.json"
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError):
        payload = None
    workers = payload.get("workers") if isinstance(payload, dict) else None
    if isinstance(workers, dict):
        for record in workers.values():
            if not isinstance(record, dict) or not _wave_same_path(
                    record.get("cwd"), worktree):
                continue
            substrate = record.get("substrate")
            if substrate in {"claude", "codex"}:
                return substrate

    jobs = Path(worktree) / ".mcx"
    try:
        candidates = sorted(path for path in jobs.iterdir() if path.is_dir())
    except (FileNotFoundError, OSError):
        candidates = []
    for job in candidates:
        try:
            saved_cwd = (job / "cwd").read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError, UnicodeError):
            continue
        if _wave_same_path(saved_cwd, worktree) and (job / "codex").is_file():
            return "codex"
    return "unknown"


def _wave_landed_lanes(repo, base, run=subprocess.run):
    """Return merge-commit lanes in ``base..HEAD`` with recorded substrate."""
    result = _wave_git(repo, "log", "--merges", "--format=%H%x09%s",
                       f"{base}..HEAD", run=run)
    lanes = []
    for line in result.stdout.splitlines():
        commit, _, subject = line.partition("\t")
        match = re.search(r"^merge\(([^)]+)\):", subject, re.IGNORECASE)
        if not match:
            continue
        lane = match.group(1)
        substrate = _wave_record_substrate(
            repo, _wave_lane_worktree(repo, lane, run=run))
        lanes.append((lane, substrate, commit[:7]))
    return lanes


def _wave_codex_tokens(repo):
    """Sum Codex usage from local mcx result records.

    Completed mcx jobs conventionally leave a text ``result`` plus an
    ``events.jsonl`` containing the final usage object.  Prefer the result and
    consult its event log only when the result has no machine-readable usage,
    so one job cannot be counted twice.
    """
    root = Path(repo) / ".mcx"
    try:
        result_paths = sorted(root.glob("*/result"))
    except OSError:
        result_paths = []
    if not result_paths:
        return "UNMEASURED (mcx result files missing)"
    total = 0
    measured = 0
    missing = []
    for result_path in result_paths:
        try:
            text = result_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing.append(result_path.as_posix())
            continue
        pairs = []
        pair = _wave_token_pair(text)
        if pair is not None:
            pairs.append(pair)
        else:
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                payload = None
            if payload is not None:
                pending = [payload]
                while pending:
                    item = pending.pop()
                    if isinstance(item, dict):
                        pair = _wave_token_pair(item)
                        if pair is not None:
                            pairs.append(pair)
                        else:
                            pending.extend(item.values())
                    elif isinstance(item, list):
                        pending.extend(item)
            if pairs:
                total += sum(sum(pair) for pair in pairs)
                measured += 1
                continue
            try:
                events = result_path.with_name("events.jsonl").read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                events = ""
            for line in events.splitlines():
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                usage = event.get("usage") if isinstance(event, dict) else None
                if usage is None and isinstance(event, dict):
                    item = event.get("item")
                    usage = item.get("usage") if isinstance(item, dict) else None
                pair = _wave_token_pair(usage)
                if pair is not None:
                    pairs.append(pair)
        if pairs:
            total += sum(sum(pair) for pair in pairs)
            measured += 1
        else:
            missing.append(result_path.as_posix())
    if missing:
        return "UNMEASURED (mcx usage missing: " + ", ".join(missing) + ")"
    return str(total) if measured else "UNMEASURED (mcx usage missing)"


_WAVE_PYTEST_COUNT_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>failed|passed|skipped|xfailed|xpassed|error|errors)")


def _wave_parse_pytest_result(stdout, stderr, returncode):
    """Parse one half's final pytest summary, including failure nodeids."""
    counts = {key: 0 for key in
              ("failed", "passed", "skipped", "xfailed", "xpassed", "errors")}
    summary = "\n".join((stdout or "").splitlines()[-8:])
    for match in _WAVE_PYTEST_COUNT_RE.finditer(summary):
        kind = match.group("kind")
        if kind == "error":
            kind = "errors"
        counts[kind] += int(match.group("count"))
    failures = set()
    for line in (stdout or "").splitlines():
        if line.startswith("FAILED "):
            failures.add(line[7:].split(" - ", 1)[0].strip())
    counts["collected"] = sum(counts.values())
    counts["returncode"] = returncode
    return counts, failures


def _wave_floor(repo, wave_id, run=subprocess.run, which=shutil.which,
                log_root=None):
    """Run both foreground halves for each required interpreter in a fresh clone."""
    # Check prerequisites before paying for a clone.
    uv = which("uv")
    if uv is None:
        raise FleetCliError(
            "wave-close: `uv` is required to run the floor -- no interpreter on "
            "PATH has pytest importable (CLAUDE.md)")
    clone_parent = Path(tempfile.mkdtemp(prefix="fleet-wave-close-"))
    clone = clone_parent / "repo"
    try:
        _wave_git(repo, "clone", "--no-local", "--quiet", str(repo), str(clone),
                  run=run)
        # Walk the fresh clone itself so nested suites such as integration are
        # included and the one derived list drives both halves.
        files = sorted(path.relative_to(clone).as_posix()
                       for path in clone.joinpath("tests").rglob("test_*.py"))
        if not files:
            raise FleetCliError("wave-close: fresh clone contains no test files")
        midpoint = (len(files) + 1) // 2
        halves = (files[:midpoint], files[midpoint:])
        interpreters = ("python3.10", "python3.12")
        results = {}
        if log_root is None:
            log_root = state_dir() / "wave-close" / str(wave_id)
        Path(log_root).mkdir(parents=True, exist_ok=True)
        for interpreter in interpreters:
            executable = which(interpreter)
            if executable is None:
                raise FleetCliError(f"wave-close: required interpreter {interpreter} is unavailable")
            version = interpreter.replace("python", "", 1)
            aggregate = {key: 0 for key in
                         ("failed", "passed", "skipped", "xfailed", "xpassed",
                          "errors", "collected")}
            failures = set()
            for number, half in enumerate(halves, 1):
                if not half:
                    continue
                env = os.environ.copy()
                for key in ("CLAUDE_CODE_SESSION_ID", "FLEET_HOME", "FLEET_LIVE",
                            "FLEET_WORKER"):
                    env.pop(key, None)
                env["UV_OFFLINE"] = "1"
                env["UV_CACHE_DIR"] = "/tmp/w64-initrepo-uv-cache"
                # uv supplies pytest and the selected interpreter. Resolve the interpreter
                # first so a missing local installation fails instead of downloading one.
                proc = run([uv, "run", "--no-project", "--python", version,
                            "--with", "pytest", "python", "-m", "pytest",
                            "-q", "--color=no", *half],
                           cwd=str(clone), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
                log = Path(log_root) / f"{interpreter}-half-{number}.log"
                log.write_text((proc.stdout or "") + "\n--- stderr ---\n" +
                               (proc.stderr or ""), encoding="utf-8")
                parsed, half_failures = _wave_parse_pytest_result(
                    proc.stdout, proc.stderr, proc.returncode)
                if parsed["collected"] == 0:
                    # An absent pytest summary cannot count as a clean floor with zero tests.
                    raise FleetCliError(
                        f"wave-close: {interpreter} half {number} produced no "
                        f"pytest summary -- the floor did not run; see {log}")
                for key in aggregate:
                    aggregate[key] += parsed[key]
                failures |= half_failures
            aggregate["failures"] = sorted(failures)
            results[interpreter] = aggregate
        comparable = [{key: value for key, value in result.items()
                       if key != "failures"} for result in results.values()]
        if comparable[0] != comparable[1]:
            raise FleetCliError(
                f"wave-close: floor totals differ between interpreters: {results}")
        if results["python3.12"]["failures"] != results["python3.10"]["failures"]:
            raise FleetCliError(
                f"wave-close: floor failure sets differ between interpreters: {results}")
        if set(results["python3.10"]["failures"]) != WAVE_CLOSE_EXPECTED_FAILURES:
            raise FleetCliError(
                "wave-close: floor failure set differs from the expected host "
                f"assumptions: {results['python3.10']['failures']}")
        return results, _wave_git(clone, "rev-parse", "HEAD", run=run).stdout.strip()
    finally:
        shutil.rmtree(clone_parent, ignore_errors=True)


def _wave_prepend_after_title(path, text):
    """Prepend entries while preserving a markdown title and its encoding."""
    raw = path.read_bytes() if path.exists() else b""
    if not raw:
        raw = b"# Operator changelog\n\n"
    line_end = raw.find(b"\n")
    if line_end < 0:
        line_end = len(raw)
    head = raw[:line_end + (1 if line_end < len(raw) else 0)]
    tail = raw[len(head):]
    block = text.rstrip("\n").encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + block + tail)


def _wave_prepend_journal(path, line):
    """Place the accounting line before the first parsed journal entry."""
    raw = path.read_bytes() if path.exists() else b"# Supervisor Journal\n\n"
    marker = b"\n## "
    index = raw.find(marker)
    if index < 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw.rstrip(b"\n") + b"\n" + line.encode() + b"\n")
        return
    insertion = line.encode("utf-8") + b"\n\n"
    path.write_bytes(raw[:index + 1] + insertion + raw[index + 1:])


def _wave_refresh_progress(repo, wave_id):
    """Refresh only a mechanically recognizable current-wave marker.

    Lane acceptance, priority advancement, and prose are model judgements;
    this arm intentionally reports no refresh when there is no exact row to
    update rather than manufacturing status from filenames.
    """
    path = Path(repo) / "docs" / "PLAN-PROGRESS.md"
    if not path.exists() or wave_id == "UNMEASURED":
        return 0
    text = path.read_text(encoding="utf-8")
    marker = f"w{wave_id}"
    return sum(1 for line in text.splitlines() if marker in line and line.startswith("|"))


def _wave_push(repo, run=subprocess.run, sleep=time.sleep):
    """Push, retrying three times over five minutes, and return success/detail."""
    delay = WAVE_CLOSE_PUSH_WINDOW_SECONDS / (WAVE_CLOSE_PUSH_ATTEMPTS - 1)
    failures = []
    for attempt in range(WAVE_CLOSE_PUSH_ATTEMPTS):
        if attempt:
            sleep(delay)
        result = _wave_git(repo, "push", run=run, check=False)
        if result.returncode == 0:
            return True, attempt + 1, failures
        failures.append((attempt + 1, (result.stderr or result.stdout or "").strip()))
    return False, WAVE_CLOSE_PUSH_ATTEMPTS, failures


def cmd_wave_close(args, run=subprocess.run, which=shutil.which,
                   sleep=time.sleep) -> int:
    """Close one wave from a clean checkout after a strict two-interpreter floor."""
    repo = _wave_repo_root(run=run)
    raw_base = getattr(args, "base", None)
    base = (_wave_previous_close(repo, run=run) if raw_base is None
            else str(raw_base).strip())
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", base):
        raise FleetCliError("wave-close: --base must be a commit SHA")
    _wave_git(repo, "rev-parse", "--verify", f"{base}^{{commit}}", run=run)
    status = _wave_git(repo, "status", "--porcelain", run=run).stdout
    if status.strip():
        raise FleetCliError("wave-close: working tree must be clean before close")
    changelog = _read_task_arg(args.changelog)
    if not changelog.strip():
        raise FleetCliError("wave-close: --changelog must contain at least one sentence")
    gaps = _wave_changelog_gaps(repo, base, extra=changelog, run=run)
    if gaps:
        raise FleetCliError(
            "wave-close: CHANGELOG coverage missing for merge commit(s) since "
            f"{base}: {', '.join(gaps)}")
    # Check committer identity before the expensive reap and interpreter floor.
    identity = run(["git", "-C", str(repo), "var", "GIT_COMMITTER_IDENT"],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace")
    if identity.returncode != 0:
        raise FleetCliError(
            "wave-close: git has no committer identity in this repo -- set "
            "`git config user.name` and `user.email` before closing a wave")

    # Claim first: the reap, floor, and git operations below can take time,
    # but an unclaimed body must not perform even the janitorial mutation.
    with fleet_lock():
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="wave-close", mint=False)
        # Refresh liveness before the long close so active work does not look stale.
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    _deliver_notices(notices)

    wave_id = _wave_id(repo, run=run)
    reap_stats = {}
    reap_count, reap_error = _supervisor_reap(caller_sid=caller,
                                              reap_stats=reap_stats)
    if reap_error:
        print(f"wave-close: reap note: {reap_error}", file=sys.stderr)
    floor, tree = _wave_floor(repo, wave_id, run=run, which=which)
    buckets, changed_paths = _wave_numstat(repo, base, run=run)
    roster_ok, roster = _fetch_agents_roster(which=which, run=run)
    claude_tokens = (_wave_roster_claude_tokens(roster) if roster_ok else
                     f"UNMEASURED (roster unavailable: {roster})")
    lanes = _wave_landed_lanes(repo, base, run=run)
    lane_text = ", ".join(f"{name}: {substrate}" for name, substrate, _sha in lanes)
    if not lane_text:
        lane_text = "none"
    codex_tokens = (_wave_codex_tokens(repo)
                    if any(substrate == "codex" for _name, substrate, _sha in lanes)
                    else "0")
    token_values = [claude_tokens, codex_tokens]
    unknown = [value for value in token_values
               if value.startswith("UNMEASURED")]
    token_text = ("UNMEASURED (" + "; ".join(value[len("UNMEASURED ("):-1]
                                                for value in unknown) + ")"
                  if unknown else str(sum(int(value) for value in token_values)))
    protected = reap_stats.get("protected_unread_mail", 0)
    throughput = (
        f"THROUGHPUT wave {wave_id} ({base}..{tree}): "
        + ", ".join(f"{name} +{values[0]}/-{values[1]}"
                     for name, values in buckets.items())
        + f"; workers: {len(lanes)} ({lane_text}); tokens: {token_text}; "
        f"reaped: {reap_count}; protected: {protected} (unread mail)")

    # Re-check immediately before landing the append-only boundary.  The
    # floor is intentionally outside the lock, so the original claim cannot
    # be trusted blindly after a long run.
    with fleet_lock():
        claim, _, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="wave-close", mint=False)
        _wave_prepend_after_title(repo / "docs" / "CHANGELOG.md", changelog)
        _wave_prepend_journal(repo / "supervisor" / "JOURNAL.md", throughput)
        progress_rows = _wave_refresh_progress(repo, wave_id)
        roll = roll_supervisor_journal(home=repo)
        write_incarnation(claim)
    _deliver_notices(notices)
    receipt = state_dir() / "wave-close" / f"{wave_id}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt_roll = dict(roll)
    if "history" in receipt_roll:
        receipt_roll["history"] = str(receipt_roll["history"])
    receipt.write_text(json.dumps({"wave": wave_id, "base": base, "tree": tree,
                                   "throughput": throughput, "changed_paths": changed_paths,
                                   "floor": floor, "progress_rows": progress_rows,
                                   "journal_roll": receipt_roll}, indent=2), encoding="utf-8")
    _wave_git(repo, "add", "-A", run=run)
    _wave_git(repo, "commit", "-m", f"fleet wave-close: wave {wave_id}", run=run)
    pushed, attempts, push_failures = _wave_push(repo, run=run, sleep=sleep)
    if not pushed:
        with open(repo / "supervisor" / "JOURNAL.md", "a", encoding="utf-8") as stream:
            stream.write(f"\nPUSH FAILURE wave {wave_id}: {attempts} attempts; "
                         f"retry window {WAVE_CLOSE_PUSH_WINDOW_SECONDS:.0f}s\n")
        _wave_git(repo, "add", "supervisor/JOURNAL.md", run=run)
        _wave_git(repo, "commit", "-m", f"fleet wave-close: checkpoint push failure wave {wave_id}", run=run)
        raise FleetCliError(f"wave-close: push failed after {attempts} attempts: {push_failures}")

    pruned = _wave_prune_landed_worktrees(repo, "HEAD", run=run)
    notify_args = argparse.Namespace(text=throughput, tmux_session="work", window="fleet",
                                     dry_run=False, sid=getattr(args, "sid", None),
                                     nonce=getattr(args, "nonce", None))
    cmd_sup_notify(notify_args, run=run)
    print(throughput)
    print(f"wave-close: floor tree={tree}; journal rolled={roll['rolled']}; "
          f"progress rows refreshed={progress_rows}; push attempts={attempts}")
    print(f"wave-close: worktrees removed: {pruned['removed']}; "
          f"worktrees skipped: {pruned['skipped']} "
          f"(unmerged: {pruned['unmerged']}, dirty: {pruned['dirty']}, "
          f"protected: {pruned['protected']}, failed: {pruned['failed']})")
    return 0


def cmd_sup_heartbeat(args) -> int:
    """`fleet sup-heartbeat [--sid S]` -- beat without journal spam (GOALS
    frugality: a beat is not an event worth a checkpoint)."""
    with fleet_lock():
        claim, _, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-heartbeat")
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"heartbeat refreshed for {claim['incarnation_id']}")
    _deliver_notices(notices)
    return 0


def _tombstone_releasing_body(caller: str, inc: str):
    """Retire the releasing caller's own registry record; return its name or None.
    Caller must hold fleet_lock and have committed the released claim first.
    Resolve only the caller's sid union; abstain on unresolved or ambiguous
    identity so release cannot target another body. Read without quarantine and
    save only a readable registry, preserving live records on read failure.
    Write status="dead" and the ordinary status_changed event. Do not write a
    stop outcome: release asks the body to exit but does not stop its session."""
    ok, reason, data = _read_registry_readonly()
    if not ok:
        if reason == "quarantined":
            # A quarantined registry is not absent or merely unreadable; name the
            # quarantine explicitly so the operator can recover the releasing record.
            art = _quarantine_artifacts()
            where = f"state/{art[-1].name}" if art else "state/fleet.json.corrupt.<ts>"
            print(f"fleet: sup-release: the registry was quarantined aside to "
                  f"{where} -- the releasing body's own record could NOT be "
                  f"tombstoned and now exists only inside that artifact. Claim "
                  f"{inc} IS released; until this session leaves the roster a "
                  f"successor `sup-boot` still refuses (B6). Restore the "
                  f"artifact, then stop this session.", file=sys.stderr)
        elif reason != "not_initialized":
            print(f"fleet: sup-release: registry {reason} -- the releasing body's own "
                  f"record could NOT be tombstoned (and was NOT quarantined). Claim "
                  f"{inc} IS released; until this session leaves the roster a "
                  f"successor `sup-boot` still refuses (B6). Run `fleet doctor`, "
                  f"then stop this session.", file=sys.stderr)
        return None
    ident = _acting_worker_identity(sid=caller, registry=data)
    if ident["verdict"] == IDENTITY_AMBIGUOUS:
        print(f"fleet: sup-release: registry identity is AMBIGUOUS for sid {caller} "
              f"({', '.join(ident['candidates'])}) -- NOT tombstoning any of them, "
              f"because guessing would retire another body's record. Claim {inc} IS "
              f"released; a successor `sup-boot` refuses until this session leaves "
              f"the roster. Run `fleet doctor`.", file=sys.stderr)
        return None
    if ident["verdict"] != IDENTITY_RESOLVED:
        return None                     # not a fleet-launched body: nothing to retire
    name = ident["name"]
    rec = data["workers"].get(name)
    if not isinstance(rec, dict):
        return None
    if not _record_is_live(rec):
        return name                     # already a tombstone -- never re-stamp one
    old = rec.get("status")
    rec["status"] = "dead"
    save_registry(data)
    append_event("status_changed", name, old=old, new="dead")
    return name


def cmd_sup_release(args, run=subprocess.run, which=shutil.which) -> int:
    """Release the claim, carry pending handoffs, then tombstone the caller.
    Write the released claim from an explicit key set: carrying session_id or
    nonce fields could let the legacy branch resurrect it. Pending handoffs
    are carried explicitly because release must retain in-flight attempts.
    Validate without minting: a nonce for the departing claim would be unusable.
    Both writes hold fleet_lock. Release must commit before the tombstone: a
    crash between writes leaves a released claim with a live releaser, which B6
    refuses until that body exits. Reversing them could freeze a held claim
    whose owner fleet has already retired. Release retains INCARNATION so boot
    can distinguish an orderly stand-down from an absent claim."""
    with fleet_lock():
        claim, caller, _ = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-release", mint=False)
        inc = claim["incarnation_id"]
        reason = (getattr(args, "reason", None) or "").strip()
        # Journal while this body still holds the claim. A crash before release
        # then leaves evidence of the attempt instead of an unrecorded release.
        supervisor_journal_append("RELEASED", inc, caller,
                                  f"released cleanly: {reason or '(no reason given)'}")
        released = {"incarnation_id": inc,
                    "lineage_id": claim.get("lineage_id"),
                    "claimed_via": claim.get("claimed_via"),
                    "released_at": now_iso(),
                    "released_by_sid": caller,
                    "state": "released"}
        if reason:
            released["reason"] = reason
        # Carry handoff_pending explicitly: it decides no holdership and keeps
        # unresolved successors abortable, visible and protected from file sweeps.
        _carry_handoff_pending_on_release(claim, released)
        write_incarnation(released)
        # AFTER the claim write, never before -- see the ORDER note above.
        retired = _tombstone_releasing_body(caller, inc)
    print(_supervisor_reap_line(run=run, which=which, caller_sid=caller))
    tail = (f"This body's registry record ({retired}) is tombstoned, so the next "
            f"`fleet sup-boot` claims immediately -- nobody has to stop this "
            f"session first." if retired else
            f"The next body claims fresh via `fleet sup-boot` (no seizure, no page).")
    print(f"claim {inc} released. Nothing holds the supervisor claim now -- this "
          f"incarnation must EXIT: take no further fleet actions. {tail}")
    return 0


def _project_claim(claim, now=None):
    """Publish an allowlisted, secret-free claim projection for read-only views.
    Expose presence, sequence and age observables instead of nonce hashes.
    An allowlist prevents newly added private fields from leaking by default.
    Pure and tolerant of unreadable claim shapes."""
    if claim is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    pending_age = None
    if claim.get("pending_at"):
        try:
            pending_age = int((now - _parse_iso(claim["pending_at"])).total_seconds())
        except (TypeError, ValueError):
            pending_age = None
    out = {key: claim.get(key) for key in (
        "incarnation_id", "session_id", "claimed_at", "heartbeat_at", "claimed_via",
        "lineage_id", "nonce_seq", "state", "released_at", "released_by_sid", "reason")}
    out["nonce_present"] = bool(claim.get("nonce_hash"))
    out["pending_present"] = bool(claim.get("pending_nonce_hash"))
    out["pending_age_seconds"] = pending_age
    # Expose all pending successors separately from the pending nonce. Each
    # entry carries its state; omit task_file because it locates a live token.
    entries = handoff_pending_entries(claim)
    out[HANDOFF_PENDING_KEY] = [
        {"successor_inc": e.get("successor_inc"),
         "successor_sid": e.get("successor_sid"),
         "minted_at": e.get("minted_at"),
         "state": handoff_entry_state(e, now=now)}
        for e in entries]
    out["handoff_pending_count"] = len(entries)
    return out


def _project_handshake(hs):
    """§5.8, same rule, the other dict this view dumps: `handoff_token_hash`
    (§6.4) is reported as a presence bit and never published."""
    if hs is None:
        return None
    out = {key: hs.get(key) for key in ("incarnation_id", "session_id", "written_at")}
    out["handoff_token_present"] = bool(hs.get("handoff_token_hash"))
    return out


INTERFACE_DIVERGENCE_WINDOW_SECONDS = SUPERVISOR_CLAIM_STALE_SECONDS


def _interface_divergence(now=None, window_seconds=None):
    """Warn when recent supervisor mail names multiple interface caller sids.
    Read a bounded transcript tail and return a warning dict or None.
    The interface has no claim, so this detects divergence without refusing
    sends. Read-only and tolerant of malformed evidence."""
    if now is None:
        now = datetime.now(timezone.utc)
    if window_seconds is None:
        window_seconds = INTERFACE_DIVERGENCE_WINDOW_SECONDS
    callers = {}     # caller_sid -> latest ts string seen (for reporting)
    for line in _read_tail_lines(events_path()):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("kind") != "mail_sent":
            continue
        target = ev.get("name")
        if not (target == SUPERVISOR_BODY_NAME or _is_supervisor_shaped(target)):
            continue
        cs = ev.get("caller_sid")
        if not isinstance(cs, str) or not cs:
            continue      # no provenance (human shell / pre-§5.3 event): ignore
        try:
            ts = _parse_iso(ev["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        if (now - ts).total_seconds() > window_seconds:
            continue      # outside the window
        callers[cs] = ev["ts"]
    if len(callers) < 2:
        return None
    return {"caller_sids": sorted(callers), "count": len(callers),
            "window_seconds": window_seconds}


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
        # Project allowlisted JSON fields; the human form names its fields explicitly.
        "incarnation": _project_claim(claim),
        "heartbeat_age_seconds": beat_age,
        "handshake": _project_handshake(hs),
        "abort_flag": handoff_abort_flag_path().exists(),
        "pending_decision": read_pending_decision(),   # §8: routing surface
        "interface_divergence": _interface_divergence(),  # §5.3: B7 detection
        "nag": supervisor_status_line(),
        # Publish the holder body's sid union separately from the claim: it is a
        # registry fact, resolved without quarantine. Pass the claim already read
        # so the union and incarnation describe the same snapshot; no claim means
        # no extra registry read. None preserves an indeterminate resolution.
        "claim_sids": supervisor_claim_sids(claim) if claim is not None else None,
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
    if claim is None:
        print("supervisor: no claim" + (" (GOALS active -- start one: `fleet sup-boot`)"
                                        if info["goals_active"] else ""))
    elif claim.get("state") == "released":
        # Released claims intentionally lack heartbeat_at; render release directly
        # instead of reporting a clean stand-down as unreadable heartbeat.
        print(f"supervisor: {claim.get('incarnation_id', '?')} RELEASED at "
              f"{claim.get('released_at', '?')} by sid={claim.get('released_by_sid')}"
              + (f" ({claim['reason']})" if claim.get("reason") else "")
              + " -- no holder; `fleet sup-boot` claims fresh")
    else:
        age = f"{beat_age:.0f}s ago" if beat_age is not None else "unreadable"
        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
              f"via {claim.get('claimed_via', '?')}, heartbeat {age}")
        # Show other sids of the same body in the human form for liveness diagnosis.
        _others = [s for s in (info["claim_sids"] or [])
                   if s != claim.get("session_id")]
        if _others:
            print("  same body, retired sids: " + ", ".join(_others)
                  + " -- a roster row under ANY of these is this body alive")
        # Render the freeze-window note only for a held claim; the no-claim and
        # released branches already describe their own state.
        if beat_age is not None:
            frozen = _claim_holder_dead_note(
                claim, claim.get("incarnation_id", "?"), beat_age)
            if frozen is not None:
                print(frozen)
    if hs is not None:
        print(f"handshake: {hs.get('incarnation_id')} sid={hs.get('session_id')} (handoff in flight)")
    # Show pending successors and actionable recipes in the human form.
    # Joining entries name their wait; unreadable mint times require --force.
    for entry in info["incarnation"].get(HANDOFF_PENDING_KEY, []) if info["incarnation"] else []:
        handle = (f"--successor-sid {entry['successor_sid']}" if entry.get("successor_sid")
                  else f"--successor-inc {entry['successor_inc']}")
        recipe = (f"abort with `fleet sup-handoff-abort {handle} --nonce <value>`")
        if entry.get("state") == HANDOFF_JOINING and not entry.get("successor_sid"):
            try:
                minted = _parse_iso(entry.get("minted_at"))
            except (TypeError, ValueError):
                minted = None
            if minted is None:
                recipe = (f"NOT retirable by age -- its minted_at "
                          f"({entry.get('minted_at')!r}) cannot be read, so it will "
                          f"never age out: `fleet sup-handoff-abort {handle} --force "
                          f"--nonce <value>`")
            else:
                when = (minted + timedelta(
                    seconds=SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
                recipe = (f"still joining -- retirable at {when}, then `fleet "
                          f"sup-handoff-abort {handle} --nonce <value>` "
                          f"(before that the abort is refused: a join in progress is "
                          f"not a dead successor)")
        print(f"pending successor: {entry.get('successor_inc')} [{entry.get('state')}]"
              f" minted {entry.get('minted_at')} -- {recipe}")
    if info["abort_flag"]:
        print(f"WARNING: aborted-handoff flag present ({handoff_abort_flag_path()})")
    pd = info["pending_decision"]
    if pd is not None:
        if pd.get("answer"):
            print(f"pending-decision: ANSWERED ({pd.get('answer')!r}) -- supervisor "
                  f"should consume and `fleet sup-decision --clear`")
        else:
            print(f"pending-decision OPEN (needs operator): {pd.get('question')!r}"
                  + (f" [ctx {pd['context_ref']}]" if pd.get("context_ref") else "")
                  + " -- answer with `fleet sup-decision --answer <text>`")
    div = info["interface_divergence"]
    if div is not None:
        print(f"WARNING: interface divergence -- {div['count']} distinct caller sids "
              f"steered the supervisor within {div['window_seconds']:.0f}s "
              f"({', '.join(div['caller_sids'])}). A forked interface body may be "
              f"re-deriving steers (§5.3). Detection only; confirm the human owns "
              f"every session before trusting recent briefs.")
    return 0


def _sup_guard_body_sids(claim):
    """Return the released body's sid union, or ``None`` if it is unknown.

    ``supervisor_claim_sids`` intentionally treats a released claim as having
    no holder.  The guard still needs the releaser's union so a release that
    has not yet stopped its body cannot authorize a second body.
    """
    if not isinstance(claim, dict):
        return None
    sid = claim.get("released_by_sid") or claim.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    registry = _registry_records_or_none()
    if registry is None:
        return None
    for record in (registry.get("workers") or {}).values():
        if sid in _record_sids(record):
            return sorted(_record_sids(record))
    return [sid]


def _seize_settled_by_a_heartbeat(claim):
    """True once the seizing body has beaten at least once after claiming.

    `sup-boot` writes `claimed_at` and `heartbeat_at` together, so they are
    equal for exactly one moment: the seizure. Any later beat moves
    `heartbeat_at` past it and settles the takeover -- the body proved it is
    the holder. After that the claim is ordinary and the stale/idle rules
    decide; a seize hours old is not evidence about now.
    """
    claimed, beat = claim.get("claimed_at"), claim.get("heartbeat_at")
    if not claimed or not beat:
        return False
    try:
        return _parse_iso(beat) > _parse_iso(claimed)
    except (ValueError, TypeError):
        return False


def _sup_guard_live_rows(entries):
    """Map live roster sids to rows with a non-empty pid.
    Status alone can survive process exit. Do not consult state: a bg-spare
    host can report state="done" while its adopted session holds a live pid;
    the host lifecycle does not establish the session's death."""
    rows = {}
    for entry in entries if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sessionId")
        pid = entry.get("pid")
        if not isinstance(sid, str) or not sid or pid in (None, "", 0):
            continue
        rows.setdefault(sid, []).append(entry)
    return rows


def _fork_took_over_rows(entries):
    """Live rows that also prove a fork TOOK OVER, not merely that it exists.

    Stricter than `_sup_guard_live_rows` on purpose. The guard asks "can this
    body be reached", where a `state: done` bg-spare host with a live pid is a
    yes. Retirement asks "has the replacement actually assumed the work", and a
    `done` fork answers no -- retiring the parent on that evidence is how the
    addendum's "never retire on the strength of the send alone" gets violated.
    """
    return {sid: rows for sid, rows in _sup_guard_live_rows(entries).items()
            if any(r.get("state") != "done" for r in rows)}


def _sup_guard_body_name(sids):
    """Resolve a body name from the same registry record as its sid union."""
    if not sids:
        return None
    registry = _registry_records_or_none()
    if registry is None:
        return None
    wanted = set(sids)
    for name, record in (registry.get("workers") or {}).items():
        if wanted.intersection(_record_sids(record)):
            return name
    return None


def _sup_guard_observe(snapshot_fn=None, roster_fn=None):
    """Collect the read-only inputs for one two-live-body decision."""
    snapshot_fn = snapshot_fn or status_snapshot
    roster_fn = roster_fn or _fetch_agents_roster
    snapshot = snapshot_fn()
    sup = snapshot.get("supervisor") if isinstance(snapshot, dict) else None
    sup = sup if isinstance(sup, dict) else {}
    claim = read_incarnation()
    state = sup.get("state")
    if state not in ("none", "held", "released", "unknown"):
        state = "unknown"
    raw_state = ("none" if claim is None else
                 "released" if claim.get("state") == "released" else "held"
                 if isinstance(claim, dict) else "unknown")
    if state != "unknown" and state != raw_state:
        state = "unknown"

    roster_ok, roster_or_reason = roster_fn()
    entries = roster_or_reason if roster_ok and isinstance(roster_or_reason, list) else []
    roster_ok = bool(roster_ok and isinstance(roster_or_reason, list))
    live_rows = _sup_guard_live_rows(entries)
    handshake_exists = handshake_path().exists()
    handshake = read_handshake() if handshake_exists else None
    pending = bool(handoff_pending_members(claim))

    if state == "held":
        sids = supervisor_claim_sids(claim)
    elif state == "released":
        sids = _sup_guard_body_sids(claim)
    else:
        sids = None
    body_name = _sup_guard_body_name(sids)
    # The fleet projection supplies transcript-detected parks; newer native
    # rosters may supply the same status/horizon directly, even without a PID.
    body_rows = [row for row in entries if isinstance(row, dict)
                 and row.get("sessionId") in (sids or [])]
    projected = snapshot.get("workers") if isinstance(snapshot, dict) else None
    projected_rows = [row for row in projected if isinstance(row, dict)
                      and row.get("name") == body_name] if isinstance(projected, list) else []
    limited_rows = [row for row in body_rows + projected_rows
                    if row.get("status") == "limited"]
    horizons = [row.get("limit_reset_at") for row in limited_rows
                if isinstance(row.get("limit_reset_at"), str)]
    live_body_rows = [row for sid, rows in live_rows.items()
                      for row in rows
                      if isinstance(row.get("name"), str)
                      and (row.get("name") == SUPERVISOR_BODY_NAME
                           or _is_supervisor_shaped(row.get("name")))]
    return {
        "snapshot": snapshot,
        "registry_ok": bool(snapshot.get("ok", True))
        if isinstance(snapshot, dict) else False,
        "registry_reason": snapshot.get("reason")
        if isinstance(snapshot, dict) else "snapshot unreadable",
        "state": state,
        "claim": claim,
        "claim_sids": sids,
        "roster_ok": bool(roster_ok),
        "roster_reason": None if roster_ok else str(roster_or_reason),
        "live_rows": live_rows,
        "live_body_rows": live_body_rows,
        "handshake_exists": handshake_exists,
        "handshake": handshake,
        "pending": pending,
        "body_name": body_name,
        "limited": bool(limited_rows),
        "limit_reset_at": max(horizons, default=None),
        "heartbeat_age_seconds": sup.get("heartbeat_age_seconds"),
        "goals_active": bool(sup.get("goals_active")),
    }


def _sup_guard_decide(observation):
    """Return ``(verdict, reason, detail)`` for one guard observation."""
    obs = observation
    detail = {
        key: obs.get(key) for key in
        ("state", "claim_sids", "registry_ok", "registry_reason",
         "roster_ok", "roster_reason",
         "heartbeat_age_seconds", "body_name", "pending",
         "handshake_exists", "limit_reset_at")
    }
    if not obs.get("goals_active"):
        detail["quiet"] = True
        return "PAGE", "supervisor goals inactive", detail
    if obs.get("registry_ok", True) is False:
        return "PAGE", f"registry unavailable: {obs.get('registry_reason')}", detail
    if not obs.get("roster_ok"):
        return "PAGE", f"roster unavailable: {obs.get('roster_reason')}", detail
    if obs.get("state") == "unknown":
        return "PAGE", "claim state unknown", detail
    if obs.get("handshake_exists"):
        reason = ("handoff in flight"
                  if obs.get("handshake") is not None
                  else "supervisor/HANDSHAKE unreadable")
        return "PAGE", reason, detail
    if obs.get("pending"):
        return "PAGE", "handoff in flight", detail

    if obs.get("limited"):
        reason = "supervisor limited"
        if _limit_reset_passed({"limit_reset_at": obs.get("limit_reset_at")}):
            reason += "; reset horizon passed, interface must resume"
        return "PAGE", reason, detail

    state = obs.get("state")
    claim = obs.get("claim") or {}
    if (state == "held" and
            (claim.get("claimed_via") == "seize" or
             claim.get("state") == "seized")
            and not _seize_settled_by_a_heartbeat(claim)):
        age = obs.get("heartbeat_age_seconds")
        if (not isinstance(age, (int, float))
                or age > SUPERVISOR_CLAIM_STALE_SECONDS):
            return "PAGE", "claim seized", detail

    if state in ("none", "released"):
        if obs.get("claim_sids") is None and state == "released":
            return "PAGE", "releasing body identity unavailable", detail
        if (obs.get("live_body_rows") or any(
                obs["live_rows"].get(sid) for sid in (obs.get("claim_sids") or []))):
            return "PAGE", "live supervisor body without a safe claim", detail
        if state == "released":
            return "DISPATCH", "claim released", detail
        return "DISPATCH", "claim none", detail

    sids = obs.get("claim_sids")
    if not isinstance(sids, list) or not sids:
        return "PAGE", "claim session not in the roster, sid union unavailable", detail
    matching = [row for sid in sids for row in obs["live_rows"].get(sid, [])]
    if matching:
        statuses = {row.get("status") if isinstance(row.get("status"), str) else None
                    for row in matching}
        age = obs.get("heartbeat_age_seconds")
        if not isinstance(age, (int, float)):
            return "PAGE", "claim heartbeat unreadable", detail
        if (age <= SUPERVISOR_CLAIM_STALE_SECONDS
                and ("busy" in statuses or statuses == {"idle"})):
            detail["quiet"] = True
            return "OK", "fresh heartbeat with live body", detail
        if "busy" in statuses:
            return "PAGE", "roster says busy", detail
        if statuses == {"idle"}:
            return "WAKE", obs.get("body_name") or SUPERVISOR_BODY_NAME, detail
        return "PAGE", "live supervisor status unknown", detail

    age = obs.get("heartbeat_age_seconds")
    if not isinstance(age, (int, float)):
        return "PAGE", "claim heartbeat unreadable", detail
    if age <= SUPERVISOR_CLAIM_STALE_SECONDS:
        return "PAGE", "fresh heartbeat but body is not roster-live", detail
    if any(row not in matching for row in obs.get("live_body_rows", [])):
        return "PAGE", "another live supervisor body is present", detail
    return "DISPATCH", "stale claim with no live body", detail


def _sup_guard_line(verdict, reason, target=None):
    if verdict == "WAKE":
        target = " ".join(str(target or SUPERVISOR_BODY_NAME).split())
        return f"WAKE {target}"
    if verdict in {"OK", "DISPATCH"}:
        return verdict
    reason = " ".join(str(reason).split())
    return f"PAGE {reason}"


def cmd_sup_guard(args, *, snapshot_fn=None, roster_fn=None) -> int:
    """Observe twice before action; only WAKE acts, and never spawns.

    JSON includes explicit sent/quiet flags so the keeper does not derive
    liveness again. Plain output uses the four-verdict interface, including OK.
    """
    do = getattr(args, "do", False)
    observation = _sup_guard_observe(snapshot_fn=snapshot_fn, roster_fn=roster_fn)
    if do:
        # Only the WAKE path retries deferred fork retirement. OK and PAGE
        # must stay action-free. Re-observe after any retirement before send.
        if _sup_guard_decide(observation)[0] == "WAKE":
            _reap_current_supervisor_forks(roster_fn=roster_fn)
        observation = _sup_guard_observe(snapshot_fn=snapshot_fn, roster_fn=roster_fn)
    verdict, reason, detail = _sup_guard_decide(observation)
    sent, rc = False, 0
    if do and verdict == "WAKE":
        try:
            with redirect_stdout(io.StringIO()):
                rc = cmd_send(SimpleNamespace(
                    name=SUPERVISOR_BODY_NAME,
                    message="@supervisor/briefs/wake.md", nonce=None))
            sent = rc == 0
            if not sent:
                verdict, reason = "PAGE", "supervisor wake send failed"
        except (FleetCliError, ClaudeNotFoundError, ValueError, OSError,
                FleetLockTimeout) as exc:
            verdict, reason, rc = "PAGE", f"supervisor wake send failed: {exc}", 1
            print(f"fleet: sup-guard action failed: {exc}", file=sys.stderr)
    if do and rc:
        # Send can discover and persist a limit while recomputing its target.
        # Publish that park/horizon immediately; never turn it into timer retries
        # of a generic send failure. This is observation only, not a second send.
        after = _sup_guard_observe(snapshot_fn=snapshot_fn, roster_fn=roster_fn)
        next_verdict, next_reason, next_detail = _sup_guard_decide(after)
        if next_reason.startswith("supervisor limited"):
            verdict, reason, detail, rc = next_verdict, next_reason, next_detail, 0
    line = _sup_guard_line(verdict, reason, detail.get("body_name"))
    if getattr(args, "json", False):
        output = {"verdict": line, "reason": reason, **detail, "sent": sent}
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    else:
        print(line)
    return rc


def cmd_sup_context(args) -> int:
    """Measure the observed body's context band without locks or writes.
    Use the running process's own sid, or --sid for explicit inspection, so a
    fork does not leave the lookup tied to a stale claim or outcome.
    Missing sid/transcript yields assume-near-band and hand_off=True.
    Resolve the observed sid's tier and report its configured band; an unknown
    tier uses the stricter worker band. Both renderings include the tier."""
    sid = getattr(args, "sid", None) or current_caller_session()
    transcript = find_transcript_path(None, sid) if sid else None
    occupancy = _transcript_occupancy(transcript)
    tier = band_tier_for_sid(sid)
    verdict = supervisor_band_verdict(occupancy, tier)
    info = {
        "sid": sid,
        "occupancy": occupancy,
        "transcript": transcript.as_posix() if transcript else None,
        **verdict,
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
    occ = f"{occupancy:,} tokens" if occupancy is not None else "unreadable"
    print(f"context occupancy: {occ}  ->  {verdict['verdict'].upper()}"
          f"  ({tier} band {verdict['soft_threshold']:,}-"
          f"{verdict['hard_threshold']:,})")
    print(verdict["reason"])
    if sid is None:
        print("NOTE: no CLAUDE_CODE_SESSION_ID -- run this from the session you "
              "are measuring (it reads its OWN transcript, §11.2)")
    return 0


def cmd_sup_notify(args, run=subprocess.run) -> int:
    """Send a sanitized SUPERVISOR line to the registered tmux interface.
    Require claim continuity, but treat this as an accidental-second-body
    speed bump: the same OS user can invoke tmux directly. The shared
    sanitizer remains necessary regardless of the caller's identity.
    Do not apply the dispatch ceiling: notifying a handoff must remain possible
    at the band. Validate with mint=False to avoid rotating the generation
    between notification and handoff. Commit acknowledgments and sid restamps,
    then emit notices before tmux, whose failure must not hide that commit.
    Do not refresh heartbeat: a notification is not a checkpoint.
    --dry-run only prints the sanitized bytes, before any claim work or lock."""
    target = f"{args.tmux_session}:{args.window}"
    if args.dry_run:
        print(f"[dry-run] would type into {target}: "
              f"{interface_line(args.text, SUPERVISOR_LINE_PREFIX)}")
        return 0
    with fleet_lock():
        claim, _, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-notify", mint=False)
        write_incarnation(claim)
    inc = claim.get("incarnation_id", "?")
    _deliver_notices(notices)
    if not type_interface_line(run, target, args.text,
                               prefix=SUPERVISOR_LINE_PREFIX, label="fleet"):
        raise FleetCliError(
            f"sup-notify: tmux would not deliver the line to {target} -- the "
            f"interface has NOT been told. Check that the tmux server and the "
            f"window exist (`tmux list-windows -t {args.tmux_session}`); the "
            f"claim is untouched apart from this call's own restamp, so "
            f"re-running this verb is safe.")
    append_interface_log("RELAY", args.text)
    print(f"notified {target} as {inc}: "
          f"{interface_line(args.text, SUPERVISOR_LINE_PREFIX)}")
    return 0


def cmd_interface_register(args, run=subprocess.run, home=None) -> int:
    """Register the current interface pane or session.

    The pane id comes only from ``TMUX_PANE`` and is checked in the same shape
    the keeper accepts: a percent sign followed by ASCII decimal digits.  A
    missing or malformed environment value is a refusal, never a guessed pane
    target or a state-file write. Outside tmux, the caller's Claude session id
    is the interface identity; this path does not weaken the pane refusal.
    """
    root = FLEET_HOME if home is None else Path(home)
    ensure_interface_state(root)
    pane = os.environ.get("TMUX_PANE")
    if pane is not None:
        if not (pane.startswith("%") and pane[1:].isascii()
                and pane[1:].isdecimal()):
            raise FleetCliError(
                "interface-register: TMUX_PANE must contain a tmux pane ID")
        current_window = _tmux_window_name(run, pane)
        if current_window is None:
            raise FleetCliError(
                "interface-register: tmux pane lookup failed; registration was not written")
        if current_window != "fleet":
            if not tmux_command(run, sys.stderr, "rename-window", "-t", pane,
                                "fleet", label="interface-register"):
                raise FleetCliError(
                    "interface-register: tmux window rename failed; registration was not written")
        path = root / "state" / "interface-pane"
        existing = None
        try:
            existing = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        if existing != pane:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pane + "\n", encoding="utf-8")
            print(f"interface pane registered: {pane}")
            append_interface_log("REGISTER", f"pane={pane}", home=root)
        else:
            print(f"interface pane already registered: {pane}")
        return 0

    sid = (getattr(args, "session_id", None)
           or os.environ.get("CLAUDE_CODE_SESSION_ID"))
    if sid is None or not sid.strip() or "\n" in sid or "\r" in sid:
        raise FleetCliError(
            "interface-register: TMUX_PANE is unset and "
            "CLAUDE_CODE_SESSION_ID is unset; run from the interface session")
    path = root / "state" / "interface-session"
    existing = None
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    if existing != sid:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sid + "\n", encoding="utf-8")
        print(f"interface session registered: {sid}")
        append_interface_log("REGISTER", f"session={sid}", home=root)
    else:
        print(f"interface session already registered: {sid}")
    return 0


def cmd_sup_decision(args) -> int:
    """`fleet sup-decision` -- three-tier §8 operator-gate routing.

      --raise QUESTION [--context-ref REF]   supervisor routes a decision (the
          claim-holder only) and PARKS. Refuses if one is already open: one
          decision at a time.
      --answer TEXT                          the interface tier writes the
          operator's decision. NOT claim-gated -- the interface holds no claim
          by design (§3.1), so requiring continuity here would be wrong.
      --clear                                remove the open decision (consumed).
      (no flag)                              show the current decision.

    The supervisor never writes its own answer (§8): `--raise` sets `answer` to
    None and `--answer` is the interface's verb. This file is ROUTING, not
    authorization -- it never lets the supervisor act on the operator's behalf;
    it is how "operator gates stay human" survives an unattended supervisor."""
    raising = getattr(args, "question", None) is not None
    answering = getattr(args, "answer", None) is not None
    clearing = bool(getattr(args, "clear", False))
    if sum((raising, answering, clearing)) > 1:
        raise FleetCliError("sup-decision: pass at most one of --raise / --answer / --clear")

    if raising:
        with fleet_lock():
            claim, caller, notices = _require_claim_holder(
                getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
                verb="sup-decision")
            existing = read_pending_decision()
            if existing is not None and not existing.get("answer"):
                raise FleetCliError(
                    "sup-decision: a decision is already open -- one at a time. "
                    "Answer or clear it first "
                    f"(question: {existing.get('question')!r})")
            write_pending_decision({
                "question": args.question,
                "raised_by_inc": claim.get("incarnation_id"),
                "raised_at": now_iso(),
                "context_ref": getattr(args, "context_ref", None),
                "answer": None,
            })
            write_incarnation(claim)   # §5.3: acknowledge + commit together
        print(f"pending-decision raised: {args.question!r} -- routed to the "
              f"interface tier; supervisor parks until answered")
        append_interface_log("RULING", f"raised={args.question}")
        _deliver_notices(notices)
        return 0

    if answering:
        # Share --raise's lock so answering cannot lose a concurrent decision write.
        with fleet_lock():
            rec = read_pending_decision()
            if rec is None:
                raise FleetCliError("sup-decision: no open decision to answer")
            # Refuse unreadable state instead of fabricating an answered record over it.
            if rec.get("_unreadable"):
                raise FleetCliError(
                    "sup-decision: the pending-decision file is present but "
                    f"corrupt ({pending_decision_path().name}) -- refusing to "
                    "answer over it (an answer written now would fabricate a "
                    "record over unreadable state). Inspect and remove the file, "
                    "then re-raise the decision.")
            rec["answer"] = args.answer
            rec["answered_at"] = now_iso()
            rec["answered_by_sid"] = current_caller_session()
            write_pending_decision(rec)
        print(f"pending-decision answered: {args.answer!r}")
        append_interface_log("RULING", f"answered={args.answer}")
        return 0

    if clearing:
        # Share --raise/--answer's lock. Clearing corrupt state is valid recovery.
        with fleet_lock():
            clear_pending_decision()
        print("pending-decision cleared")
        append_interface_log("RULING", "cleared")
        return 0

    rec = read_pending_decision()
    if getattr(args, "json", False):
        print(json.dumps(rec, indent=2))
        return 0
    if rec is None:
        print("pending-decision: none open")
    elif rec.get("answer"):
        print(f"pending-decision ANSWERED: {rec.get('question')!r} -> {rec.get('answer')!r}")
    else:
        print(f"pending-decision OPEN: {rec.get('question')!r}"
              + (f" [ctx {rec['context_ref']}]" if rec.get("context_ref") else ""))
    return 0


def _doctor_check_pending_decision():
    """three-tier §8 nag surface: FAIL while an operator decision is OPEN and
    unanswered (it needs a human), and on a corrupt file. An answered-but-not-
    yet-consumed decision is a NOTE (ok=True) -- the supervisor owes the clear,
    not the operator. Never raises: a doctor row must not crash on evidence."""
    try:
        rec = read_pending_decision()
    except Exception:  # noqa: BLE001 -- doctor row: evidence must not break health
        return ("supervisor-pending-decision", False, "pending-decision unreadable")
    if rec is None:
        return ("supervisor-pending-decision", True, "no operator decision pending")
    if rec.get("_unreadable"):
        return ("supervisor-pending-decision", False,
                "pending-decision file present but unreadable -- inspect "
                f"{pending_decision_path().name}")
    if rec.get("answer"):
        return ("supervisor-pending-decision", True,
                f"ANSWERED ({rec.get('answer')!r}) -- supervisor should consume and "
                f"`fleet sup-decision --clear`")
    return ("supervisor-pending-decision", False,
            f"OPEN, needs operator: {rec.get('question')!r} (raised by "
            f"{rec.get('raised_by_inc')} at {rec.get('raised_at')}) -- answer with "
            f"`fleet sup-decision --answer <text>`")


def _warn_missing_bypass_ack(mode: str) -> None:
    """Warn if bypass mode lacks the GOALS acknowledgment (§10.2).
    A missing or unreadable GOALS file warns too. The check is advisory:
    operator-owned prose is too brittle for a dispatch refusal.
    Non-bypass modes do not require this acknowledgment."""
    if mode != "bypass":
        return
    try:
        text = goals_path().read_text(encoding="utf-8").lower()
    except OSError:
        text = ""
    if "bypass" in text and "acknowledg" in text:
        return
    print("fleet: WARNING: supervisor/GOALS.md does not state the "
          "bypass-permission acknowledgement (three-tier §10.2/§13) -- "
          "proceeding per operator ruling 2 (2026-07-24). Add the "
          "acknowledgement to GOALS before the supervisor runs unattended.",
          file=sys.stderr)


# Read boot bundles in bounded slices: a harness may persist a large tool
# result, creating another plaintext nonce copy outside fleet cleanup.
# Redirecting stdout and deleting the bundle do not remove that copy.
# Both bootstrap renders use this ritual; no transport-size boundary is assumed.
def _render_sup_spawn_task(name: str, launch_id: str, campaign: str) -> str:
    """Render the gen-0 supervisor's task-file bootstrap ritual.
    GOALS arrives fresh in sup-boot's bundle instead of being embedded here.
    Redirect boot output to a file; extract verdict and nonce before reading
    bounded slices so stream truncation cannot hide the generation. Delete
    the bundle after reading because it contains a plaintext nonce; worker
    cleanup also sweeps it if the body dies first. Quote paths and use a
    pipe-free task stem so shell syntax cannot alter the commands."""
    # Invoke the running install; a data-only home has no bin directory.
    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()
    # The interpreter running fleet right now, not a hardcoded launcher --
    # same doctrine as `_render_successor_task`.
    py = Path(sys.executable).as_posix()
    bundle = boot_bundle_path(name).as_posix()
    # Pass the home explicitly while the dispatched body has no registered sid
    # and sid-to-home lookup cannot identify its destination.
    home = FLEET_HOME.as_posix()
    return f"""You are the claude-fleet supervisor's GEN-0 body, fleet worker `{name}`, running in {FLEET_HOME.as_posix()} (three-tier §10.1).
The `{launch_id}` segment of your worker name is a launch id, NOT your incarnation id -- your incarnation is minted at boot in step 1, and `fleet sup-status` reads supervisor/INCARNATION, never your worker name.

Do exactly this, in order:
1. FIRST ACT, before anything else -- run sup-boot with its output redirected to a file (class-4
   nonce doctrine: never read a secret off the stream tail):
   "{py}" "{fleet_py}" --fleet-home "{home}" sup-boot > "{bundle}" 2>&1
   Pass NO handoff flags -- this is the fresh-claim path. Note the command's exit code.
2. Read the verdict, and on success your incarnation and nonce, FROM THE FILE:
   grep -E "^(VERDICT|INCARNATION|NONCE):" "{bundle}"
   RECORD THE NONCE VALUE NOW -- it is printed exactly once. Every later `sup-*` verb requires it
   (present it with the --nonce flag); losing it costs up to 3600s of lockout.
3. Read the REST of the bundle file now (GOALS, journal tail, knowledge index, fleet status) so
   its content is in your working context -- IN SLICES, never in one read:
   sed -n '1,120p' "{bundle}"
   then '121,240p', then '241,360p', and so on until a slice comes back empty. WHY IN SLICES: a
   redirect protects the STREAM, not the READER -- a tool that persists a large result writes a
   SECOND durable plaintext copy of it, in storage this ritual's `rm` cannot reach, and that copy
   would carry the nonce. The hazard is the SIZE of one read's output, not the spelling of the
   command, so do not substitute `cat`, a large `head -n`, a file-reading tool, or a one-line
   script. Then delete the file:
   rm "{bundle}"
   Carry the NONCE value in your working context ONLY -- never into the journal, never into any
   file. Why: claim-nonce §5.8 -- the nonce is printed exactly once and retained nowhere else; a
   bundle left on disk is a durable plaintext copy (gitignored is not a retention policy, §5.9).
4. React to the VERDICT line:
   - `claim` (exit 0): fresh claim -- the expected gen-0 outcome. Proceed (step 5).
   - `seize` (exit 0): a dead predecessor's stale claim was seized. Proceed, and record the
     seizure in your first checkpoint note.
   - `limit-transfer` (exit 0): a limit-parked predecessor's claim transferred to you. Proceed,
     and record the transfer in your first checkpoint note.
   (`resume` (exit 0) cannot occur on a fresh body -- it means a claim your own session already
   holds; treat it as an anomaly worth a checkpoint note, then proceed.)
   - `refuse` (exit 2): a live supervisor claim exists -- a supervisor is already running. Do NOT
     retry, do NOT spawn/send/kill anything. End your turn with the final message:
     SUP-BOOT-REFUSED <reason>
   - `freeze` (exit 3): the claim state is ambiguous (unreadable heartbeat or a failed epoch
     check). Same stop discipline. End your turn with the final message:
     SUP-BOOT-FROZEN <reason>
5. After a successful claim: proceed per skills/fleet/supervisor.md -- with the boot bundle
   content you read in step 3 (GOALS, journal tail, knowledge index, fleet status), run an early
   "{py}" "{fleet_py}" --fleet-home "{home}" sup-checkpoint "<note>" --nonce <YOUR-NONCE>, substituting the NONCE
   value from step 2, then begin the campaign brief below. The flag is not optional: every
   `sup-*` holder verb is refused without it.

--- CAMPAIGN BRIEF ---
{campaign}
"""


def cmd_sup_spawn(args, run=subprocess.run, which=shutil.which, sleep=time.sleep,
                  clock=time.monotonic) -> int:
    """Dispatch a gen-0 supervisor with the supervisor gate and context ceiling.
    Use a launch-scoped pipe name, FLEET_HOME cwd, the supervisor model and
    bypass default, and a generated boot ritual. The nonce is presented without
    rotation because this is a mutating lifecycle verb (claim-nonce §7)."""
    _supervisor_gate("sup-spawn", nonce=getattr(args, "nonce", None))
    _ceiling_refusal = _ceiling_refuses_dispatch("sup-spawn")
    if _ceiling_refusal is not None:
        raise FleetCliError(_ceiling_refusal)
    _require_instance_settings()

    campaign = _read_task_arg(args.task)
    mode = getattr(args, "permission_mode", None) or SUP_SPAWN_DEFAULT_MODE
    return _dispatch_supervisor_body(campaign, mode, getattr(args, "model", None),
                                     setting_sources=getattr(args, "setting_sources", None),
                                     run=run, which=which, sleep=sleep, clock=clock)


def _dispatch_supervisor_body(campaign, mode, model, *, setting_sources=None,
                              run=subprocess.run, which=shutil.which,
                              sleep=time.sleep, clock=time.monotonic) -> int:
    """Pre-claim, dispatch, stamp or roll back one gen-0 supervisor body.
    Shared by sup-spawn and supervisor respawn. Gate, ceiling and instance
    settings preflight belong to the calling verb and are not repeated here."""
    _warn_missing_bypass_ack(mode)
    policy = read_tier_policy()
    model = model or resolve_model_for_role("supervisor", policy)

    launch_id = mint_incarnation_id()
    name = f"sup|{launch_id}|boot"
    if not _is_supervisor_shaped(name):
        raise FleetCliError(
            f"internal: minted gen-0 name {name!r} is not supervisor-shaped "
            f"-- refusing to dispatch a body that would be denied its own claim")

    cwd = FLEET_HOME
    with fleet_lock():
        data = load_registry()
        if name in data["workers"]:
            raise FleetCliError(f"minted gen-0 name already exists: {name!r} "
                                f"-- re-run sup-spawn (per-launch ids collide "
                                f"only on a same-second duplicate)")
        _spawner = current_caller_session()
        record = new_worker_record(
            None, cwd, campaign, mode, model=model,
            setting_sources=setting_sources,
            spawned_by=_spawner,
            # §10.2: null at gen-0 falls out naturally -- the caller holds no
            # claim, so `_spawning_claim_lineage` returns None (design §3).
            spawned_by_lineage=_spawning_claim_lineage(_spawner),
            dispatch_kind="bg", category=None)
        record["last_dispatch_at"] = now_iso()
        data["workers"][name] = record
        save_registry(data)
        append_event("spawned", name, cwd=str(cwd), mode=mode)

    pre_claim_at = record["last_dispatch_at"]
    prompt = _render_sup_spawn_task(name, launch_id, campaign)

    try:
        # Keep post-preclaim work inside rollback coverage. Save the full campaign
        # under the minted name so respawn need not use the capped record snapshot.
        write_brief(name, campaign)
        assert_brief_carried(name, campaign, prompt)
        result = dispatch_bg(
            name, cwd, prompt, mode, model=model,
            category=None, hint="", setting_sources=setting_sources,
            run=run, which=which, sleep=sleep, clock=clock,
        )
    except NativeDispatchError as exc:
        # No prior-session exclusion: the launch-scoped name passed a collision
        # check, so no earlier session or outcome can belong to this name.
        fast_sid = _fast_completion_sid(name, pre_claim_at,
                                        short_id=getattr(exc, "short_id", None))
        if fast_sid is not None:
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
                    _append_event_quiet("turn_started", name, session_id=fast_sid)
            print(f"{name} {fast_sid} (native bg, fast completion before join)")
            append_interface_log("SPAWN", f"supervisor={name} sid={fast_sid}")
            return 0

        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(name)
            if rec is not None and rec.get("session_id") is None:
                data["workers"].pop(name, None)
                save_registry(data)
                append_event("spawn_failed", name, error=str(exc))
        raise FleetCliError(f"{name}: native spawn failed -- {exc}") from exc
    except BaseException as exc:
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(name)
            if rec is not None and rec.get("session_id") is None:
                data["workers"].pop(name, None)
                save_registry(data)
                append_event("spawn_failed", name, error=str(exc),
                             short_id=_short_id_from_notes(exc))
        raise

    sid = result["session_id"]
    short_id = result["short_id"]

    def _commit_native_stamp():
        with fleet_lock():
            data = load_registry()
            rec = data["workers"].get(name)
            if rec is not None:
                rec["session_id"] = sid
                rec["native_short_id"] = short_id
                rec["status"] = "working"
                rec["turns"] = 1
                rec["last_activity"] = now_iso()
                save_registry(data)
                _append_event_quiet("turn_started", name, session_id=sid)

    if not _commit_launched_turn(_commit_native_stamp, sleep=sleep):
        _report_stranded_native_turn(name, sid, short_id)
        return 1

    # Show effective model and policy provenance, including inherited subagent
    # model, so launch cost is visible before the body runs.
    model_line = (f"model: {model or '(claude default)'} "
                  f"(tier policy: {policy.get('_source', 'default')})")
    subagent_model = os.environ.get("CLAUDE_CODE_SUBAGENT_MODEL")
    if subagent_model:
        model_line += f"; CLAUDE_CODE_SUBAGENT_MODEL={subagent_model}"
    print(model_line)
    print(f"{name} {sid} (native bg, short id {short_id})")
    append_interface_log("SPAWN", f"supervisor={name} sid={sid}")
    return 0


def _render_successor_task(successor_inc: str, old_inc: str, handoff_token: str) -> str:
    """Render the successor's task-file bootstrap, with POSIX-style paths.
    The task file carries the plaintext handoff token; the claim stores its
    hash, and complete/abort unlinks the file. Token verification tolerates a
    fork-steer that changes the successor's sid.
    Redirect boot output, extract verdict/incarnation/nonce, read bounded
    slices, then remove the nonce-bearing bundle. The bundle uses the registered
    successor worker name so worker cleanup can sweep it after a crash."""
    # Invoke the running install; a data-only home has no bin directory.
    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()
    # Use this process's interpreter so the bootstrap works on every platform.
    py = Path(sys.executable).as_posix()
    # Pass the home explicitly on each bootstrap verb. Until the successor sid
    # is stamped, sid-to-home lookup cannot answer and may select the donor home.
    home = FLEET_HOME.as_posix()
    # Key the bundle on the registered successor name shared by writer and cleanup.
    bundle = boot_bundle_path(_successor_worker_name(successor_inc)).as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
Your predecessor ({old_inc}) dispatched you mid-handoff (spec docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §4).

Do exactly this, in order:
1. FIRST ACT, before anything else -- run sup-boot with its output redirected to a file (class-4
   nonce doctrine: never read a secret off the stream tail -- the same ritual the gen-0 body runs):
   "{py}" "{fleet_py}" --fleet-home "{home}" sup-boot --handoff-inc {successor_inc} --handoff-token {handoff_token} > "{bundle}" 2>&1
   Note the command's exit code. On success this writes your boot bundle to that file and writes
   supervisor/HANDSHAKE (carrying the token hash and your own freshly minted generation).
2. Read the verdict, and on success your generation, FROM THE FILE:
   grep -E "^(VERDICT|INCARNATION|NONCE):" "{bundle}"
   RECORD THE NONCE VALUE NOW -- it is printed exactly once. That is YOUR generation; you present
   it on your first supervisor verb after the claim transfers. You hold NO claim yet.
   IF THE VERDICT IS `handoff-refused` (exit 5): your predecessor began another handoff after
   dispatching you, so you were superseded and at most one successor may boot. Delete the bundle
   with the step-3 `rm` and stop -- you hold nothing and there is nothing to retry. Take no
   actions, end your turn with the final message: HANDOFF-ORPHAN {successor_inc}
3. Read the REST of the bundle file now (GOALS, journal tail, knowledge index, fleet status) so
   its content is in your working context -- IN SLICES, never in one read:
   sed -n '1,120p' "{bundle}"
   then '121,240p', then '241,360p', and so on until a slice comes back empty. WHY IN SLICES: a
   redirect protects the STREAM, not the READER -- a tool that persists a large result writes a
   SECOND durable plaintext copy of it, in storage this ritual's `rm` cannot reach, and that copy
   would carry the nonce. The hazard is the SIZE of one read's output, not the spelling of the
   command, so do not substitute `cat`, a large `head -n`, a file-reading tool, or a one-line
   script. Then delete the file:
   rm "{bundle}"
   Carry the NONCE value in your working context ONLY -- never into the journal, never into any
   file. Why: claim-nonce §5.8 -- the nonce is printed exactly once and retained nowhere else; a
   bundle left on disk is a durable plaintext copy (gitignored is not a retention policy, §5.9).
4. Take NO spawn/respawn/send/kill/clean actions before claim transfer -- spec §4's double-spawn guard.
5. Poll every ~30s (up to 10 minutes): "{py}" "{fleet_py}" --fleet-home "{home}" sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     "{py}" "{fleet_py}" --fleet-home "{home}" sup-checkpoint "claim received via handoff from {old_inc}" --nonce <YOUR-NONCE>
     substituting the NONCE value step 2 printed. THE FLAG IS NOT OPTIONAL: `sup-checkpoint`
     is a `_require_claim_holder` verb, so without it this call is REFUSED and the refusal
     files a false second-body row in `fleet doctor` -- a permanently-red row trains the
     operator to ignore the row that will one day be real.
     then continue the supervisor duty per skills/fleet/supervisor.md on the boot bundle content
     you read in step 3.
   - If 10 minutes pass without transfer: the handoff was aborted. STOP -- take no actions,
     end your turn with the final message: HANDOFF-ORPHAN {successor_inc}
"""


def _claim_holder_setting_sources(claim):
    """Read the claim holder's persisted setting_sources, or None.
    This best-effort read decides a dispatch flag, not handoff eligibility.
    Unreadable identity or registry uses Claude's default settings merge.
    Use read_registry_no_repair outside fleet_lock: load_registry could perform
    an unlocked quarantine write."""
    holder_sid = claim.get("session_id")
    if not isinstance(holder_sid, str) or not holder_sid:
        return None
    try:
        data = read_registry_no_repair(hint=False)
    except RegistryCorruptError:
        return None
    for rec in data.get("workers", {}).values():
        if not isinstance(rec, dict):
            continue
        if holder_sid in _record_sids(rec):
            value = rec.get("setting_sources")
            return value if isinstance(value, str) and value else None
    return None


def cmd_sup_handoff_begin(args, which=shutil.which, run=subprocess.run,
                          sleep=time.sleep, clock=time.monotonic) -> int:
    """Checkpoint and dispatch a successor, then join its roster identity.
    Journal HANDOFF-BEGIN before dispatch so a crash leaves evidence. Dispatch
    and polling run outside fleet_lock; dispatch failure and DOA set the
    operator-visible abort flag. Validate executable and instance settings
    before the lock so missing prerequisites leave no partial handoff state.
    This launch builds its own --bg argv: incarnation ids fail dispatch_bg's
    name guard, its task file is already journaled at a handoff-specific path,
    and dispatch_bg's wedge retry could spawn two successors for one attempt.
    Carry --settings for hooks and _worker_env to strip the predecessor's sid;
    a successor inheriting that sid could produce a false HANDSHAKE identity.
    Carry the holder's setting_sources and persist it for subsequent handoffs,
    so the selected hook configuration survives the succession chain.
    No --add-dir is needed because the task file is inside cwd=FLEET_HOME.
    Render explicit and default permissions through mode_flags. The default
    is SUCCESSOR_DEFAULT_MODE: a headless supervisor must be able to run its
    bootstrap Bash command without an interactive permission prompt."""
    _require_instance_settings()
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError as exc:
        raise FleetCliError(f"{exc} -- nothing dispatched; claim unchanged, duty continues")
    with fleet_lock():
        # Do not mint a pending generation before lock-free dispatch and handoff.
        # Deliver notices after commit: legacy upgrade may still create a generation
        # the predecessor must know to complete or abort.
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-begin", mint=False)
        # Avoid collisions with holder id, pending attempts and existing task files.
        successor_inc = _mint_successor_inc(claim)
        # Keep only the token hash in the claim; send plaintext through the task
        # file that complete/abort unlinks. Commit the hash under the lock.
        handoff_token = mint_nonce()
        task_path = handoff_task_file_path(successor_inc)
        claim["handoff_token_hash"] = nonce_digest(handoff_token)
        # Append the sid-less attempt with its token hash before dispatch. Preserve
        # earlier attempts for abort, but invalidate their boot eligibility. Stamp
        # this attempt's sid only after the roster join.
        handoff_pending_append(claim, {
            "successor_inc": successor_inc,
            "successor_sid": None,
            "task_file": task_path.as_posix(),
            "minted_at": now_iso(),
        })
        write_incarnation(claim)
        task_path.parent.mkdir(parents=True, exist_ok=True)
        # Create the boot-bundle directory here: this path bypasses dispatch_bg,
        # and a redirect into a missing directory would strand the successor.
        boot_bundle_path(_successor_worker_name(successor_inc)).parent.mkdir(
            parents=True, exist_ok=True)
        task_path.write_text(
            _render_successor_task(successor_inc, claim["incarnation_id"], handoff_token),
            encoding="utf-8")
        # Sweep only aged ownerless files. An earlier live attempt may still be
        # reading its task file and remains protected by its pending entry.
        sweep_handoff_task_files(claim)
        supervisor_journal_append("HANDOFF-BEGIN", claim["incarnation_id"], caller,
                                  f"successor={successor_inc} task={task_path.as_posix()}")
        try:
            # Clear the diagnostic abort flag; abort eligibility comes from attempt
            # evidence, so this does not make an earlier successor unabortable.
            handoff_abort_flag_path().unlink()
        except FileNotFoundError:
            pass

    # After the commit and on every subsequent path (success, DOA, dispatch
    # failure): the generation the validator settled on is committed, so the
    # predecessor must learn it. Empty for the common live-claim case.
    _deliver_notices(notices)
    holder_inc = claim["incarnation_id"]

    def _abort_flag(reason, successor_sid=None, successor_short_id=None):
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "reason": reason,
            "successor_sid": successor_sid,
            "successor_short_id": successor_short_id,
            "holder": holder_inc,
        })

    def _drop_pending_marker():
        """Best-effort cleanup of this attempt after dispatch failed to launch.
        Require an exact successor_inc match so a rival begin cannot lose its entry.
        Do not use for DOA or unreadable roster: those observations do not prove no
        body exists, and a live successor may still need its bootstrap file.
        Keep earlier entries invalidated: begin replaced their token hash, so
        reactivating them would admit bodies that complete can never verify.
        Cleanup failure must not replace the caller's dispatch diagnosis."""
        try:
            with fleet_lock():
                live = read_incarnation()
                entry = handoff_entry_matching(live, successor_inc=successor_inc)
                if entry is not None:
                    drop_handoff_entry(live, entry)
                    write_incarnation(live)
        except (FleetCliError, OSError) as exc:
            print(f"WARNING: could not clear the pending entry for {successor_inc}: {exc}")
            return
        unlink_handoff_task_file(successor_inc, context=" (dispatch failed)")

    roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    pre_ok, pre_payload = roster_fetch()
    # Same unhashable-sessionId guard as dispatch_bg's pre-snapshot above.
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict) and isinstance(e.get("sessionId"), str)}
    name = _successor_worker_name(successor_inc)
    # Use the rendered instance settings so the successor receives fleet hooks.
    argv = [exe, "--bg", "-n", name,
            "--settings", instance_settings_path().as_posix()]
    # Carry the claim holder's optional settings-source selection.
    succ_setting_sources = _claim_holder_setting_sources(claim)
    if succ_setting_sources:
        argv += ["--setting-sources", succ_setting_sources]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    # Map both explicit and default fleet permission modes through mode_flags;
    # the parser rejects raw Claude mode spellings before dispatch.
    argv += mode_flags(getattr(args, "permission_mode", None) or SUCCESSOR_DEFAULT_MODE)
    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
    try:
        proc = run(argv, cwd=str(FLEET_HOME), env=_worker_env(name),
                   capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        _abort_flag("dispatch-failed")
        _drop_pending_marker()
        raise FleetCliError(f"successor dispatch failed: {exc} -- no successor to stop; "
                            f"claim unchanged, duty continues")
    if proc.returncode != 0:
        _abort_flag("dispatch-failed")
        _drop_pending_marker()
        raise FleetCliError(f"successor dispatch failed (exit {proc.returncode}): "
                            f"{(proc.stderr or '').strip()[:300]} -- no successor to stop; "
                            f"claim unchanged, duty continues")

    # Join the stdout short id to a full sid. Name matching risks title
    # collisions and is only a fallback for unparseable stdout.
    short_id = _parse_bg_short_id(proc.stdout or "")
    successor_sid = None
    # A full-window roster blackout is indeterminate, not proof of death.
    # Both join paths track whether any roster was actually observed.
    join_indeterminate = False
    if short_id:
        try:
            successor_sid = _join_roster_by_short_id(
                short_id, roster_fetch, sleep,
                verify_seconds=SUPERVISOR_ROSTER_VERIFY_SECONDS,
                exclude_sids=pre_sids, clock=clock)
        except NativeDispatchError:
            join_indeterminate = True
    else:
        print("short-id parse failed -- falling back to name join (G6 fallback)")
        deadline = clock() + SUPERVISOR_ROSTER_VERIFY_SECONDS
        verified_once = False
        while clock() < deadline:
            ok, payload = roster_fetch()
            if ok:
                verified_once = True
                # Reject unhashable session ids. A name match also needs a life signal: a
                # reused title or never-attached husk cannot establish successor identity.
                fresh = [e for e in payload if isinstance(e, dict)
                         and e.get("name") == name
                         and isinstance(e.get("sessionId"), str)
                         and e.get("sessionId")
                         and e.get("sessionId") not in pre_sids
                         and _roster_entry_has_life_signal(e)]
                if fresh:
                    successor_sid = fresh[0]["sessionId"]
                    break
            sleep(3)
        else:
            # Loop ran to the deadline without binding. If NOT ONE fetch
            # succeeded, that is a blackout (indeterminate), not a DOA.
            if not verified_once:
                join_indeterminate = True
    if join_indeterminate:
        _abort_flag("successor-indeterminate", successor_short_id=short_id)
        print(f"successor INDETERMINATE: the roster was unavailable for the "
              f"whole {SUPERVISOR_ROSTER_VERIFY_SECONDS:.0f}s join window, so "
              f"whether the dispatched successor joined CANNOT be verified -- "
              f"NOT declaring it DOA (a live successor must not be stranded). "
              f"Claim unchanged -- duty continues; recover via `claude agents`, "
              f"then re-run sup-handoff-begin only once the roster is back.")
        return 1
    if successor_sid is None:
        _abort_flag("successor-doa", successor_short_id=short_id)
        print(f"successor DOA: no roster entry named {name!r} appeared within "
              f"{SUPERVISOR_ROSTER_VERIFY_SECONDS:.0f}s (contract G6 fallback). "
              f"Claim unchanged -- duty continues; re-run sup-handoff-begin to retry.")
        return 1

    # Register the verified successor body with its provisional sid and turns=1.
    # The sid lets hooks resolve its name and readers find sid-keyed outcomes
    # before completion. Complete may replace it and retire the prior sid.
    # This record also provides supervisor archive exemption and view parity.
    # The other initial-turn dispatch writers are cmd_spawn, _cmd_respawn_native
    # and _dispatch_supervisor_body, each in fast-completion and joined arms.
    # Steer/resume paths increment turns; completion is a separate event.
    succ_mode = getattr(args, "permission_mode", None) or SUCCESSOR_DEFAULT_MODE
    with fleet_lock():
        # Re-read under the lock and stamp only our successor_inc. Reusing the
        # pre-dispatch claim could erase a concurrent begin; positional stamping
        # could put our sid on a rival attempt and aim abort at the wrong body.
        live = read_incarnation()
        entry = handoff_entry_matching(live, successor_inc=successor_inc)
        if entry is not None:
            entry["successor_sid"] = successor_sid
            write_incarnation(live)
        data = load_registry()
        if name not in data["workers"]:
            succ_rec = new_worker_record(
                successor_sid, FLEET_HOME,
                f"supervisor successor {successor_inc} (handoff from {holder_inc})",
                succ_mode, model=getattr(args, "model", None),
                setting_sources=succ_setting_sources,
                spawned_by=caller, spawned_by_lineage=claim.get("lineage_id"),
                dispatch_kind="bg", category=None)
            succ_rec["turns"] = 1
            succ_rec["last_dispatch_at"] = now_iso()
            data["workers"][name] = succ_rec
            save_registry(data)
            append_event("spawned", name, cwd=str(FLEET_HOME), mode=succ_mode)
            # Record turn_started beside the turns=1 registry stamp. The other initial
            # dispatch sites are cmd_spawn, _cmd_respawn_native and
            # _dispatch_supervisor_body, each in fast-completion and joined arms.
            # spawned has no session_id, so this event keeps ownership discoverable
            # even if completion never runs and clean later removes the registry row.
            # It proves dispatch, not successful boot; completion emits its own event.
            # Best effort: an event-log error must not hide SUCCESSOR-SID after dispatch
            # and registry commit, because abort needs that handle.
            _append_event_quiet("turn_started", name, session_id=successor_sid)

    print(f"SUCCESSOR-INC: {successor_inc}")
    print(f"SUCCESSOR-SID: {successor_sid}")
    # Both recipes present --nonce because both verbs require continuity.
    print(f"Next: wait for supervisor/HANDSHAKE (timeout "
          f"{SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:.0f}s), then run:\n"
          f"  fleet sup-handoff-complete --expect-inc {successor_inc} "
          f"--expect-sid {successor_sid} --nonce <value>\n"
          f"On timeout/failure instead run:\n"
          f"  fleet sup-handoff-abort --successor-sid {successor_sid} --nonce <value>")
    return 0


def cmd_sup_handoff_complete(args, run=subprocess.run, which=shutil.which) -> int:
    """Verify the successor token and incarnation, then transfer the claim.
    HANDSHAKE must match the incarnation and token hash recorded by begin.
    An optional --expect-sid mismatch warns about a fork but does not refuse:
    a legitimate fork retains the token. Journal HANDOFF-COMPLETE while the
    predecessor still holds the claim, then transfer."""
    with fleet_lock():
        # Do not mint for the departing claim. The successor's own generation
        # arrives in HANDSHAKE and is committed by the transfer.
        claim, caller, _ = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-complete", mint=False)
        hs = read_handshake()
        if hs is None:
            raise FleetCliError("no supervisor/HANDSHAKE -- successor not ready; wait, "
                                "or sup-handoff-abort past the timeout")
        if hs.get("incarnation_id") != args.expect_inc:
            raise FleetCliError(
                f"HANDSHAKE mismatch: found inc={hs.get('incarnation_id')}, "
                f"expected inc={args.expect_inc} -- NOT transferring (spec §4 id "
                f"verification)")
        expected_hash = claim.get("handoff_token_hash")
        if not expected_hash or hs.get("handoff_token_hash") != expected_hash:
            # Require the minted token hash, including a nonempty expected hash.
            # Missing proof must refuse rather than transfer on two absent values.
            raise FleetCliError(
                f"HANDSHAKE token mismatch for inc={args.expect_inc} -- the body that "
                f"wrote HANDSHAKE is not the successor this claim dispatched, or the "
                f"predecessor claim carries no handoff token. NOT transferring (§6.4).")
        successor_sid = hs.get("session_id")
        sid_warning = None
        if getattr(args, "expect_sid", None) and successor_sid != args.expect_sid:
            sid_warning = (
                f"WARNING: --expect-sid {args.expect_sid} does not match the HANDSHAKE "
                f"sid {successor_sid} -- the successor forked after it was dispatched. "
                f"The token verified, so transferring anyway to the body that holds it "
                f"(§6.4); recorded for observability.")
        supervisor_journal_append("HANDOFF-COMPLETE", claim["incarnation_id"], caller,
                                  f"claim -> {args.expect_inc} sid={successor_sid}")
        # Carry lineage across planned succession so existing workers stay local.
        # The successor's nonce comes from HANDSHAKE; drop the predecessor token.
        # Remove the winner's pending entry and carry all rivals, including torn
        # members, so the new holder can abort them and their files stay protected.
        # Invalidate rival boot eligibility: a rival must not overwrite the winner's
        # HANDSHAKE after transfer.
        carried = [m for m in handoff_pending_members(claim)
                   if not (isinstance(m, dict)
                           and m.get("successor_inc") == args.expect_inc)]
        for member in carried:
            if isinstance(member, dict) and not member.get(HANDOFF_SUPERSEDED_KEY):
                member[HANDOFF_SUPERSEDED_KEY] = now_iso()
                member["superseded_by"] = args.expect_inc
        new_claim = {"incarnation_id": args.expect_inc,
                     "session_id": successor_sid,
                     "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                     "claimed_via": "handoff",
                     "lineage_id": claim.get("lineage_id")}
        if carried:
            new_claim[HANDOFF_PENDING_KEY] = carried
        succ_nonce_hash = hs.get("nonce_hash")
        if succ_nonce_hash:
            new_claim["nonce_hash"] = succ_nonce_hash
            new_claim["nonce_seq"] = 1
        write_incarnation(new_claim)
        # Stamp the authoritative HANDSHAKE sid so logical supervisor resolution
        # reaches the successor despite fork-steer. Missing/cleaned records leave
        # the committed claim transfer intact.
        succ_name = _successor_worker_name(args.expect_inc)
        reg = load_registry()
        succ_rec = reg["workers"].get(succ_name)
        if succ_rec is not None and isinstance(successor_sid, str) and successor_sid:
            prior = succ_rec.get("session_id")
            if isinstance(prior, str) and prior and prior != successor_sid:
                succ_rec["retired_sids"] = list(succ_rec.get("retired_sids", [])) + [prior]
            succ_rec["session_id"] = successor_sid
            succ_rec["native_short_id"] = successor_sid.partition("-")[0] or successor_sid[:8]
            succ_rec["status"] = "working"
            succ_rec["last_activity"] = now_iso()
            save_registry(reg)
            _append_event_quiet("turn_started", succ_name, session_id=successor_sid)
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
        # §5.9: the task file carries the plaintext token; unlink it here.
        unlink_handoff_task_file(args.expect_inc, context=" (handoff complete)")
        # Sweep aged ownerless token files against the transferred claim; retained
        # pending entries still protect their own files.
        sweep_handoff_task_files(new_claim)
    print(_supervisor_reap_line(run=run, which=which, caller_sid=caller))
    if sid_warning:
        print(sid_warning)
    print(f"claim transferred to {args.expect_inc}. This (old) incarnation must now "
          f"EXIT: end the session, take no further fleet actions.")
    return 0


def _cmd_sup_handoff_retire_all(args, force=False) -> int:
    """Retire every pending entry that needs no session stopped, in one write.
    Eligible entries have no sid and are aged-out, replaced by a later begin,
    or unreadable. --force also permits joining entries with unreadable
    minted_at; it never retires a still-timed joining attempt.
    Leave sid-bearing entries for per-body abort and report their recipes.
    Refuse the whole call on a live HANDSHAKE because that attempt can complete.
    Remove retired task files so plaintext handoff tokens do not linger."""
    with fleet_lock():
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-abort --retire-all")
        hs = read_handshake()
        if hs is not None:
            raise FleetCliError(
                f"supervisor/HANDSHAKE is present (inc={hs.get('incarnation_id')} "
                f"sid={hs.get('session_id')}) -- a successor got far enough to write "
                f"one, so this succession is still live. Complete it "
                f"(`sup-handoff-complete --expect-inc {hs.get('incarnation_id')} "
                f"--nonce <value>`) or abort it by handle first; --retire-all is for "
                f"attempts no session answers for")
        now = datetime.now(timezone.utc)
        torn = handoff_pending_torn(claim)
        retirable, standing = [], []
        for entry in handoff_pending_entries(claim):
            state = handoff_entry_state(entry, now=now)
            if entry.get("successor_sid"):
                standing.append((entry, state))
            elif (state in (HANDOFF_RESOLVABLE_STALE, HANDOFF_SUPERSEDED)
                    or (force and _entry_age_seconds(entry, "minted_at",
                                                     now=now) is None)):
                retirable.append((entry, state))
            else:
                standing.append((entry, state))
        if not retirable and not torn:
            detail = "; ".join(
                f"{e.get('successor_inc')} [{s}]"
                f"{' sid=' + e['successor_sid'] if e.get('successor_sid') else ''}"
                for e, s in standing) or "none recorded"
            raise FleetCliError(
                f"nothing to retire: {detail}. An entry bearing a sid is stopped by "
                f"handle (`--successor-sid <sid>`); one still inside the join window "
                f"becomes retirable when it ages out. --force adds only entries whose "
                f"minted_at cannot be read at all -- it is not a way out of the join "
                f"window, and forcing one would unlink a still-joining successor's "
                f"only input file")
        retired_incs = []
        for entry, _state in retirable:
            retired_incs.append(entry.get("successor_inc"))
            drop_handoff_entry(claim, entry)
        for member in torn:
            drop_handoff_entry(claim, member)
        for inc in retired_incs:
            unlink_handoff_task_file(inc, context=" (handoff retire-all)")
        supervisor_journal_append(
            "HANDOFF-ABORT", claim["incarnation_id"], caller,
            f"retire-all: retired {len(retired_incs)} pending successor(s) "
            f"[{', '.join(str(i) for i in retired_incs) or 'none'}] and "
            f"{len(torn)} unreadable member(s); NO session was stopped")
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "reason": "bulk-retired",
            "successor_sid": None,
            "successor_inc": retired_incs,
            "holder": claim["incarnation_id"],
        })
        claim["heartbeat_at"] = now_iso()      # the holder resumes duty
        write_incarnation(claim)
        sweep_handoff_task_files(claim)
    print(f"retired {len(retired_incs)} pending successor(s)"
          + (f": {', '.join(str(i) for i in retired_incs)}" if retired_incs else "")
          + (f", plus {len(torn)} unreadable pending member(s) that named nothing "
             f"this code could read" if torn else "")
          + ". NO session was stopped -- none of them ever recorded one. Their task "
            "files and handoff tokens are gone; if a body did start, stop it via "
            "`claude agents`.")
    for entry, state in standing:
        handle = (f"--successor-sid {entry['successor_sid']}" if entry.get("successor_sid")
                  else f"--successor-inc {entry.get('successor_inc')}")
        print(f"STILL STANDING: {entry.get('successor_inc')} [{state}] -- "
              f"`fleet sup-handoff-abort {handle} --nonce <value>`")
    _deliver_notices(notices)
    return 0


def cmd_sup_handoff_abort(args, which=shutil.which, run=subprocess.run) -> int:
    """Resolve and abort one recorded successor, or bulk-retire eligible entries.
    Cross-check HANDSHAKE and pending records through resolve_handoff_abort;
    never stop an arbitrary unverified sid. Use claude stop, not a raw kill,
    then remove HANDSHAKE and raise the doctor-visible abort flag. Claude stop
    fires no Stop hook, so it supplies no successor journal entry.
    An incarnation handle can also retire an aged-out sid-less entry; that
    path stops nothing and reports retirement without claiming a stop."""
    successor_sid = getattr(args, "successor_sid", None)
    successor_inc = getattr(args, "successor_inc", None)
    force = bool(getattr(args, "force", False))
    if getattr(args, "retire_all", False):
        if successor_sid or successor_inc:
            raise FleetCliError(
                "--retire-all takes no handle: it retires EVERY retirable entry. "
                "Drop --successor-sid/--successor-inc, or drop --retire-all to "
                "retire exactly one")
        return _cmd_sup_handoff_retire_all(args, force=force)
    if not successor_sid and not successor_inc:
        raise FleetCliError("sup-handoff-abort needs --successor-sid, --successor-inc "
                            "or --retire-all "
                            "(see `fleet sup-status --json` for the pending successors)")
    with fleet_lock():
        # The old side RESUMES duty here (it rewrites its own heartbeat
        # below), so it mints and is delivered a fresh generation like any
        # other continuing verb.
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-abort")
        verdict = resolve_handoff_abort(claim, read_handshake(),
                                        successor_sid=successor_sid,
                                        successor_inc=successor_inc,
                                        force=force)
        if verdict["action"] == "refuse":
            raise FleetCliError(verdict["reason"])
        retiring = verdict["action"] == "retire"
        target_sid, aborted_inc = verdict["sid"], verdict["inc"]
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
        # Unlink the aborted token file. Only absence is silent: failure to remove
        # a plaintext token must remain visible.
        if aborted_inc:
            unlink_handoff_task_file(aborted_inc, context=" (handoff abort)")
        supervisor_journal_append(
            "HANDOFF-ABORT", claim["incarnation_id"], caller,
            f"retiring stale successor {aborted_inc} (no sid was ever recorded; "
            f"via {verdict.get('via')})"
            if retiring else
            f"stopping limbo successor sid={target_sid} inc={aborted_inc} "
            f"(via {verdict.get('via')})")
        _write_json_atomic(handoff_abort_flag_path(), {
            "aborted_at": now_iso(),
            "reason": "stale-entry-retired" if retiring else "aborted",
            "successor_sid": target_sid,
            "successor_inc": aborted_inc,
            "holder": claim["incarnation_id"],
        })
        claim["heartbeat_at"] = now_iso()   # old resumes duty
        # Retire only this attempt. Drop the claim token hash with the last entry
        # so stranded plaintext no longer validates.
        if verdict.get("entry") is not None:
            drop_handoff_entry(claim, verdict["entry"])
        write_incarnation(claim)
        # D2/R2: age-gated, fail-closed sweep of ownerless residue, under the
        # lock we already hold. It cannot reach a surviving entry's file.
        sweep_handoff_task_files(claim)
    if retiring:
        why = {
            "stale-entry": "no sid was ever recorded for it (dispatch never joined "
                           "the roster, or the roster could not be read)",
            "superseded-entry": "it was superseded by a later handoff and never "
                                "recorded a sid, so it could no longer boot",
            "forced": "--force: it recorded no sid and could not be aged, so no "
                      "verb would ever have retired it (rs-MIN-B)",
        }.get(verdict.get("via"), "no sid was ever recorded for it")
        print(f"stale successor {aborted_inc} retired: NO session was stopped -- {why}. "
              f"Its task file and handoff token are gone. "
              f"If a body did start, stop it via `claude agents`. Duty resumed by "
              f"{claim['incarnation_id']}.")
        _deliver_notices(notices)
        return 0
    # Use the shared stop primitive for the required short-id conversion.
    stopped = _stop_native_session(target_sid, run=run, which=which, timeout=60)
    if not stopped:
        print(f"WARNING: `claude stop {target_sid}` stop failed -- "
              f"successor may still be live; stop it manually via the agents menu. "
              f"Abort flag is set either way.")
    else:
        print(f"limbo successor {target_sid} stopped; duty resumed by "
              f"{claim['incarnation_id']}. Doctor will flag until the abort flag is cleared.")
    _deliver_notices(notices)
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


def _claim_holder_dead_note(claim, inc, age):
    """Describe a tombstoned claim holder and the remaining seizure delay.
    Use registry dead status as a file-only proxy for roster absence; kill
    writes this status before reporting its frozen-claim window. Unnoticed
    deaths remain covered by the stale-heartbeat advisory.
    Read without quarantine, lock or probe. Return None when evidence cannot
    answer, rather than calling an unknown holder dead."""
    ok, _reason, data = _read_registry_readonly()
    if not ok:
        return None
    holder = None
    for rec in data.get("workers", {}).values():
        if _record_is_supervisor_claim_holder(rec, claim=claim) is True:
            holder = rec
            break
    if holder is None or holder.get("status") != "dead":
        return None
    remaining = max(0, int(SUPERVISOR_CLAIM_STALE_SECONDS - age))
    return (f"SUPERVISOR: claim {inc} held by a DEAD sid "
            f"({(holder.get('session_id') or '?')[:8]}) -- claim FROZEN, seizable in "
            f"{remaining}s. `fleet sup-boot` verdicts `freeze` until then "
            f"(three-tier §10.4 arm 2).")


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
        if claim.get("state") == "released":
            # Released claims lack heartbeat_at by design; render release explicitly
            # so read-only surfaces do not report planned stand-down as corruption.
            # Unreadable release age must remain inside this branch.
            try:
                age_txt = f"{(now - _parse_iso(claim['released_at'])).total_seconds() / 60:.0f}m ago"
            except (KeyError, TypeError, ValueError):
                age_txt = "at an unrecorded time"
            return (f"SUPERVISOR: claim {inc} released {age_txt} -- no body holds "
                    f"the claim; boot one (`fleet sup-boot`).")
        try:
            age = (now - _parse_iso(claim["heartbeat_at"])).total_seconds()
        except (KeyError, TypeError, ValueError):
            return f"SUPERVISOR: claim {inc} heartbeat unreadable -- inspect supervisor/INCARNATION."
        if age > SUPERVISOR_CLAIM_STALE_SECONDS:
            return (f"SUPERVISOR: claim {inc} heartbeat stale (~{age / 60:.0f}m > "
                    f"{SUPERVISOR_CLAIM_STALE_SECONDS / 60:.0f}m) -- boot a new incarnation.")
        frozen = _claim_holder_dead_note(claim, inc, age)
        if frozen is not None:
            return frozen
        return f"SUPERVISOR: {inc} live, heartbeat {age / 60:.0f}m ago."
    except Exception:  # noqa: BLE001 -- view: never raises
        return None


def _nonce_pending_age_note(claim, now=None):
    """Report a pending nonce outstanding past NONCE_PENDING_STALE_MULTIPLE TTLs.
    A body can keep presenting the accepted live generation indefinitely
    without acknowledging pending, weakening duplicate-body detection without
    a refusal. This age signal is advisory, not a health failure."""
    if not isinstance(claim, dict) or not claim.get("pending_at"):
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        age = (now - _parse_iso(claim["pending_at"])).total_seconds()
    except (TypeError, ValueError):
        return None
    limit = PENDING_NONCE_TTL_SECONDS * NONCE_PENDING_STALE_MULTIPLE
    if age <= limit:
        return None
    return (f"NOTE: unacknowledged pending generation for {age / 60:.0f}m "
            f"(> {limit / 60:.0f}m) -- the presenter obligation is being violated "
            f"and divergence detection is degraded (claim-nonce §5.4(e))")


def _doctor_check_supervisor_claim():
    """Fail on a nonce refusal recorded in the last 24 hours.
    Other claim nags remain advisory: an expired pending generation can belong
    to a legitimate body that spent longer than its TTL thinking.
    Tolerate corrupt evidence without crashing the doctor row."""
    line = supervisor_status_line()
    if line is None:
        return ("supervisor-claim", True, "GOALS absent or dormant -- no supervisor expected")
    parts = [line]
    ok = True
    try:
        recent = _recent_nonce_rejections()
        superseded = [r for r in recent if r.get("kind") == "superseded-pending"]
        # Count only refusals against the currently held claim. Keep unknown-scope
        # records visible as notes instead of treating them as duplicate-body proof.
        held = read_incarnation()
        refused, foreign = [], []
        for rec in recent:
            if rec.get("kind") != "refused":
                continue
            (refused if _rejection_is_about_current_claim(rec, held)
             else foreign).append(rec)
        if refused:
            ok = False
            last = refused[-1]
            parts.append(
                f"{len(refused)} continuity refusal(s) in the last "
                f"{NONCE_REJECTION_WINDOW_SECONDS // 3600}h (latest: {last.get('verb')} "
                f"at {last.get('ts')}, expected generation {last.get('expected_seq')}) -- "
                f"a second body of this lineage may be acting; census the sessions "
                f"(state/{nonce_rejection_log_path().name})")
        if foreign:
            # Render the unknown count and evidence location so scoping cannot hide
            # records concerning claims this fleet no longer holds.
            last = foreign[-1]
            parts.append(
                f"NOTE: {len(foreign)} further continuity refusal(s) in the window "
                f"belong to a claim this fleet no longer holds (latest: "
                f"{last.get('verb')} at {last.get('ts')}, incarnation "
                f"{last.get('incarnation_id') or 'unrecorded'}) -- not evidence about "
                f"the current lineage, so not counted above; kept in "
                f"state/{nonce_rejection_log_path().name}")
        if superseded:
            # A replaced pending nonce means either a second presenter or failure to
            # present the newest generation. Report both possibilities as advisory: a
            # slow legitimate body does not prove a duplicate.
            parts.append(
                f"NOTE: {len(superseded)} superseded-pending acceptance(s) -- a body "
                f"presented a generation that a later mint had already replaced. A "
                f"protocol-conforming single body cannot do that (claim-nonce §5.3), "
                f"so this implies EITHER a second presenter OR a violated presenter "
                f"obligation. Not proof of either, and not a refusal -- but not benign")
        note = _nonce_pending_age_note(read_incarnation())
        if note:
            parts.append(note)
    except Exception:  # noqa: BLE001 -- doctor row: evidence must not break health
        pass
    return ("supervisor-claim", ok, " | ".join(parts))


def _doctor_check_supervisor_wedge(which=shutil.which, run=subprocess.run):
    """Fail when a released claim still has a live, untombstoned releaser.
    Delegate to supervisor_claim_decision with _roster_live_sids and registry
    inputs as boot, including sid unions and tombstones, so doctor agrees with
    B6 on identical evidence. Read registry without quarantine.
    A boot-blocking wedge is a health failure. Doctor may probe the roster;
    file-only views such as sup-status may only describe stored evidence."""
    claim = read_incarnation()
    if claim is None or claim.get("state") != "released":
        return ("supervisor-wedge", True, "no released claim -- B6 cannot be wedged")
    inc = claim.get("incarnation_id", "?")
    released_by = claim.get("released_by_sid")
    # Delegate every released-claim decision, even with no named releaser, so
    # doctor and boot cannot drift into separate liveness rules.
    roster_ok, payload = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        # Same direction as every other roster-dependent decision in this file:
        # never assert a verdict blind. Not a FAIL -- an unavailable roster is
        # an environment fault with its own doctor row, and failing here would
        # double-count it.
        return ("supervisor-wedge", True,
                f"{inc} released by sid {released_by}; roster unavailable ({payload}) -- "
                f"cannot evaluate B6, `fleet sup-boot` reports the authoritative verdict")
    live_sids = _roster_live_sids(payload)
    registry = _registry_records_or_none()
    verdict, reason = supervisor_claim_decision(claim, live_sids, None, registry=registry)
    if verdict != "refuse":
        return ("supervisor-wedge", True,
                f"{inc} released and `fleet sup-boot` claims fresh -- {reason}")
    age_txt = "unknown"
    try:
        age = (datetime.now(timezone.utc) - _parse_iso(claim["released_at"])).total_seconds()
        age_txt = f"{age / 3600:.1f}h" if age >= 3600 else f"{age:.0f}s"
    except (KeyError, TypeError, ValueError):
        pass
    # Name actionable live sids from the union. The original releasing sid
    # may already be gone, so printing it alone could prescribe a no-op stop.
    still = ", ".join(sorted(_releaser_live_sids(claim, live_sids, registry=registry))) or "?"
    return ("supervisor-wedge", False,
            f"SUPERVISOR CLAIM WEDGED: {reason}. Released {age_txt} ago and the releaser has "
            f"been live throughout, so `fleet sup-boot` exits 2 and no supervisor can be "
            f"booted. Remedy: stop session(s) {still} -- those are the live ones, and sid "
            f"{released_by} may already be gone; any `sup-boot` then claims fresh. A release "
            f"performed by current code tombstones the releasing body and self-heals, so a "
            f"wedge here means the release predates that or the record was re-armed by a "
            f"deletion. A record whose releaser can no longer re-release it (the released "
            f"record carries no session_id, so `sup-release` refuses) is an OPERATOR "
            f"escalation -- claim-nonce §5.7, never a hand-edit by an agent")


def _doctor_check_supervisor_handoff():
    """Fail on handoff residue requiring operator action.
    Check the abort flag, a HANDSHAKE older than the timeout, and pending
    entries requiring retirement. Pending residue affects the verdict even
    when a subsequent begin has cleared the abort flag."""
    parts = []
    ok = True
    try:
        claim = read_incarnation()
        stranded = [(e, handoff_entry_state(e)) for e in handoff_pending_entries(claim)]
        stranded = [(e, s) for e, s in stranded
                    if s in (HANDOFF_RESOLVABLE_STALE, HANDOFF_SUPERSEDED)]
        torn = handoff_pending_torn(claim)
        # Retirement needs a holder; after release, tell the operator to boot
        # before presenting a generation to --retire-all.
        recipe = ("`fleet sup-handoff-abort --retire-all --nonce <value>`"
                  if not (isinstance(claim, dict) and claim.get("state") == "released")
                  else "`fleet sup-boot` (the claim is RELEASED -- there is no holder to "
                       "present a nonce to), then `fleet sup-handoff-abort --retire-all "
                       "--nonce <value>`")
        if stranded:
            ok = False
            parts.append(
                f"{len(stranded)} pending successor(s) awaiting retirement ("
                + ", ".join(f"{e.get('successor_inc')}[{s}]" for e, s in stranded)
                + ") -- each pins a task file whose plaintext handoff token is LIVE "
                  "while the claim holds its hash. Retire them: " + recipe)
        if torn:
            ok = False
            parts.append(
                f"{len(torn)} unreadable pending member(s) in the claim -- they name "
                f"no successor this code can identify, so the handoff-file sweep "
                f"protects EVERY task file while they stand (fail-closed). Clear "
                f"them: " + recipe)
    except Exception:  # noqa: BLE001 -- doctor row: evidence must not break health
        pass
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
    # Advisory backstop for crash-before-unlink token residue. Stat failures
    # must not crash doctor; complete/abort provide the actual deletion path.
    try:
        orphans = []
        for f in state_dir().glob("supervisor-handoff-*.md"):
            try:
                fage = time.time() - f.stat().st_mtime
            except OSError:
                # An unreadable age prevents sweeping, so report that file explicitly.
                orphans.append(f"{f.name} (age unreadable)")
                continue
            if fage > SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:
                orphans.append(f.name)
        if orphans:
            # A token can still validate while its hash remains in the claim. Removing
            # plaintext files is the retention policy, even for apparent residue.
            parts.append(
                f"NOTE: {len(orphans)} orphaned successor task file(s) past the handoff "
                f"timeout, or of unreadable age "
                f"({', '.join(sorted(orphans))}) -- residue from a handoff that "
                f"crashed before unlinking. Each carries a handoff token that is still "
                f"LIVE if the claim still holds its hash; delete them (claim-nonce §5.9), "
                f"and prefer `fleet sup-handoff-abort --successor-inc <inc>`, which "
                f"retires the pending entry and the token hash with the file")
    except OSError:
        pass
    if not parts:
        parts.append("no handoff in flight, no aborted-handoff flag")
    return ("supervisor-handoff", ok, " | ".join(parts))


# ---------------------------------------------------------------------------
# CLI: argparse wiring + main()
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # main consumes --fleet-home before argparse so it works on either side of
    # the verb and cannot collide with a subcommand destination.
    parser = argparse.ArgumentParser(
        prog="fleet", description="claude-fleet manager CLI",
        epilog="global: --fleet-home <PATH> selects which fleet home to act on "
               "(accepted in any position; see docs/specs/multi-fleet.md §5)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_home = sub.add_parser("home", help="print the resolved FLEET_HOME path")
    p_home.add_argument("--tag", action="store_true",
                        help="print the home's statusline tag instead of its "
                             "path -- the tag the bar shows in `[fleet:<tag>]`)")

    sub.add_parser("knowledge", help="print knowledge/INDEX.md")

    # Add and retire are exclusive: applying both has no defined order.
    p_homes = sub.add_parser("homes", help="list, add or retire fleet homes")
    homes_write = p_homes.add_mutually_exclusive_group()
    homes_write.add_argument("--add", default=None, metavar="PATH",
                             help="append <PATH> to ~/.claude/fleet-homes.list "
                                  "(must be an initialized fleet home)")
    homes_write.add_argument("--retire", default=None, metavar="PATH",
                             help="append a retirement record for <PATH> "
                                  "(the home need not still exist)")

    p_init = sub.add_parser("init", help="create a fleet home in cwd without "
                            "registering it; --home also registers a named home")
    p_init.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    # Keep argparse's default home destination: the verb-effect table derives
    # init --home mechanically and needs no residual flag mapping.
    p_init.add_argument("--home", metavar="PATH",
                        help="initialise a fleet home at PATH (creates its "
                             "state/fleet.json) and record it in "
                             "~/.claude/fleet-homes.list -- DESTRUCTIVE: the "
                             "append is irreversible, only the fold reverses it")
    p_init.add_argument("--statusline", action="store_true",
                        help="also install fleet's statusline into ~/.claude/settings.json")
    p_init.add_argument("--chain", action="store_true",
                        help="with --statusline: keep an existing foreign statusline and print "
                             "fleet's row beneath it")
    p_init.add_argument("--force", action="store_true",
                        help="with --statusline: overwrite a foreign statusline")

    p_spawn = sub.add_parser("spawn", help="spawn a new worker session")
    p_spawn.add_argument("name")
    p_spawn.add_argument("--dir", required=True)
    p_spawn.add_argument("--task", required=True)
    # Default to allowlist-based auto-denial so headless workers cannot stall
    # on permission prompts.
    p_spawn.add_argument("--mode", choices=list(MODE_FLAGS), default="dontask")
    p_spawn.add_argument("--model", default=None)
    p_spawn.add_argument("--max-budget-usd", type=float, default=None, dest="max_budget_usd")
    # Pass settings-source selection through to Claude so foreign hooks can be excluded.
    p_spawn.add_argument("--setting-sources", dest="setting_sources", default=None)
    p_spawn.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    # Enforce the cumulative token ceiling before resume and expose it to the
    # Stop hook so pending mail cannot block a ceiling stop.
    p_spawn.add_argument("--token-ceiling", type=int, default=None, dest="token_ceiling")
    # Use the default fleet category when dispatch receives no explicit category.
    p_spawn.add_argument("--category", default=None)
    # Resolve context sources against worker --dir and prepend complete digests.
    p_spawn.add_argument("--context", default=None,
                         help="comma-separated source paths under --dir whose "
                              "fleet-index digests are injected into the prompt "
                              "(§7); ignored when the project has no index")

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
    p_send.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

    p_interrupt = sub.add_parser("interrupt", help="kill a worker's running turn")
    p_interrupt.add_argument("name")
    p_interrupt.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

    p_attach = sub.add_parser("attach", help="attach an interactive terminal to a worker")
    p_attach.add_argument("name")
    p_attach.add_argument("--force", action="store_true")

    p_release = sub.add_parser("release", help="release an attached worker back to idle")
    p_release.add_argument("name")
    p_release.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

    p_respawn = sub.add_parser("respawn", help="fresh session for a worker (context-reset lever)")
    p_respawn.add_argument("name")
    p_respawn.add_argument("--task", default=None)
    p_respawn.add_argument("--force", action="store_true")
    p_respawn.add_argument("--yes", action="store_true",
                           help="confirm respawning a worker this session did not spawn")
    p_respawn.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    # None carries persisted budget/settings forward; explicit values override.
    p_respawn.add_argument("--max-budget-usd", type=float, default=None, dest="max_budget_usd")
    p_respawn.add_argument("--setting-sources", dest="setting_sources", default=None)
    # Carry the token ceiling forward unless overridden.
    p_respawn.add_argument("--token-ceiling", type=int, default=None, dest="token_ceiling")

    # Explicit usage-limit resume sweep.
    p_resume = sub.add_parser("resume-limited",
                              help="relaunch limited workers whose reset horizon has passed")
    p_resume.add_argument("name", nargs="?", default=None)
    p_resume.add_argument("--force-now", action="store_true", dest="force_now",
                          help="resume a named worker even before its horizon / with an unknown horizon")
    p_resume.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

    p_kill = sub.add_parser("kill", help="interrupt (if running) and mark a worker dead")
    p_kill.add_argument("--yes", action="store_true",
                        help="confirm killing a worker this session did not spawn")
    p_kill.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    p_kill.add_argument("name")

    p_clean = sub.add_parser("clean", help="remove dead workers and their logs/mailboxes/journals")
    p_clean.add_argument("--yes", action="store_true",
                         help="confirm deleting workers this session did not spawn")
    p_clean.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    clean_tier = p_clean.add_mutually_exclusive_group()
    clean_tier.add_argument("--dead-only", action="store_true", dest="dead_only",
                            help="sweep only confirmed-dead workers; spare archived tombstones")
    clean_tier.add_argument("--tombstones", action="store_true",
                            help="sweep only archived tombstones; touch nothing else")

    p_archive = sub.add_parser("archive", help="auto-archive terminal-state native workers past a TTL")
    p_archive.add_argument("name", nargs="?", default=None)
    p_archive.add_argument("--ttl-hours", type=float, default=None, dest="ttl_hours")
    p_archive.add_argument("--dry-run", action="store_true", dest="dry_run")
    p_archive.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

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
                             help="explicit FLEET_HOME override for a caller whose "
                                  "environment does not carry one")

    # Index operations use only the target project, never fleet state.
    p_index = sub.add_parser("index", help="per-project symbol index (opt-in)")
    index_sub = p_index.add_subparsers(dest="index_command", required=True)

    p_ix_init = index_sub.add_parser(
        "init", help="opt in: create .fleet-index/ and run the first build")
    p_ix_build = index_sub.add_parser("build", help="rebuild an existing index")
    p_ix_build.add_argument("--force", action="store_true",
                            help="re-parse every file, not just the changed ones")
    p_ix_update = index_sub.add_parser("update", help="refresh named files only")
    # --files selects source files; --path selects the index root.
    p_ix_update.add_argument("--files", required=True,
                             help="comma-separated source paths, relative to the index root")
    p_ix_status = index_sub.add_parser("status", help="counts and stale shards")
    for p_ix in (p_ix_init, p_ix_build, p_ix_update, p_ix_status):
        p_ix.add_argument("--path", default=None,
                          help="index root (default: the current directory)")

    p_land = sub.add_parser(
        "land",
        help="stage a lane result, rebase its branch, and run its checks")
    p_land.add_argument("lane", help="lane name, such as w78"); p_brief = sub.add_parser("brief", help="render a validated brief from a task file"); p_brief.add_argument("item", help="task file path or task item name")

    # Query operations use only the target project, never fleet state.
    p_q = sub.add_parser("q", help="query this project's symbol index (M2)")
    # Stashed so `cmd_q` can raise argparse's own exit-2 usage error for the
    # cross-flag rules argparse cannot express (§11.5 row 2).
    p_q.set_defaults(q_parser=p_q)
    p_q.add_argument("query", nargs="?", default=None,
                     help="exact name, dotted name, or a `*`/`?` glob over names")
    p_q.add_argument("--outline", default=None, metavar="PATH",
                     help="print one file's digest instead of running a query; "
                          "takes only --no-refresh")
    p_q.add_argument("--src", action="store_true",
                     help="the query must resolve to exactly one symbol; print "
                          "its source, sliced from the file")
    # `--path` is a FILTER here, not a root: `q` takes no root argument (the
    # §11.1 walk-up supplies it), which is what frees the flag name.
    p_q.add_argument("--path", default=None, metavar="GLOB",
                     help="restrict hits to source paths matching this glob "
                          "(the config.toml dialect: `**`-aware, case-sensitive)")
    p_q.add_argument("--kind", default=None, choices=list(SHARD_KINDS),
                     help="restrict hits to one symbol kind")
    p_q.add_argument("--limit", type=int, default=None, metavar="N",
                     help=f"cap printed hits (default {Q_LIMIT_DEFAULT}); a "
                          f"truncated list is still exit 0")
    p_q.add_argument("--no-refresh", action="store_true", dest="no_refresh",
                     help="never write anything: stale and orphan hits are "
                          "withheld rather than repaired")

    p_doctor = sub.add_parser("doctor", help="run fleet health checks")
    p_doctor.add_argument(
        "--repair", action="store_true",
        help="quarantine a corrupt state/fleet.json by renaming it aside to "
             "state/fleet.json.corrupt.<ts>. Without this flag `doctor` only "
             "reports (operator gate 2026-07-27): a diagnostic verb does not "
             "mutate the state it was invoked to diagnose")

    p_supboot = sub.add_parser("sup-boot", help="supervisor boot ritual: epoch check, claim decision, boot bundle (spec §4)")
    p_supboot.add_argument("--sid", help="override caller session id (default: CLAUDE_CODE_SESSION_ID)")
    p_supboot.add_argument("--nonce", help=NONCE_ARG_HELP)
    p_supboot.add_argument("--handoff-inc", dest="handoff_inc",
                           type=_argparse_incarnation_id,
                           help="handoff-successor mode: write HANDSHAKE with this incarnation id; no claim action")
    p_supboot.add_argument("--handoff-token", dest="handoff_token",
                           help="handoff-successor mode: the one-shot token from the "
                                "predecessor's task file; its hash is written into HANDSHAKE "
                                "so complete can verify this body without a sid comparison (§6.4)")

    # three-tier §10.1: gen-0 supervisor dispatch. The body name is minted
    # (`sup|<launch-id>|boot`), so unlike `spawn` there is no name argument.
    p_supspawn = sub.add_parser(
        "sup-spawn",
        help="dispatch the gen-0 supervisor body under sup|<launch-id>|boot "
             "(three-tier §10.1); its first act is `fleet sup-boot`")
    p_supspawn.add_argument("--task", required=True,
                            help="campaign brief, text or @file -- delivered "
                                 "below the boot ritual in the task file")
    p_supspawn.add_argument("--model", default=None,
                            help="tier alias for the supervisor session "
                                 "(default: resolve_model_for_role('supervisor') "
                                 "from the GOALS tier policy; unset policy omits "
                                 "--model, §3.3(d))")
    p_supspawn.add_argument("--permission-mode", dest="permission_mode",
                            choices=list(MODE_FLAGS),
                            help=f"fleet mode name (default: "
                                 f"{SUP_SPAWN_DEFAULT_MODE}, §10.2 "
                                 f"earned-privilege)")
    p_supspawn.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
    # Carry settings-source selection so foreign Stop hooks can be excluded.
    p_supspawn.add_argument("--setting-sources", dest="setting_sources", default=None)

    p_supckpt = sub.add_parser("sup-checkpoint", help="append a supervisor journal checkpoint (claim holder only) + refresh heartbeat")
    p_supckpt.add_argument("body", help="checkpoint text, or @file")
    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
    p_supckpt.add_argument("--sid", help="override caller session id")
    p_supckpt.add_argument("--nonce", help=NONCE_ARG_HELP)

    sub.add_parser("journal-roll",
                   help="roll older supervisor journal entries into history")

    p_interface = sub.add_parser(
        "interface-register",
        help="register this tmux pane or Claude session as the interface")
    p_interface.add_argument(
        "--session-id", dest="session_id", default=None,
        help="session id for registration when outside tmux (default: environment)")

    p_wave = sub.add_parser(
        "wave-close",
        help="reap, floor, account, land, push, and notify one wave boundary")
    p_wave.add_argument("--base", required=False, default=None,
                        help="base commit SHA for the throughput diff (default: previous wave-close commit)")
    p_wave.add_argument("--changelog", required=True,
                        help="CHANGELOG sentences, or @file containing them")
    p_wave.add_argument("--sid", help="override caller session id")
    p_wave.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)

    p_supbeat = sub.add_parser("sup-heartbeat", help="refresh the supervisor claim heartbeat (no journal write)")
    p_supbeat.add_argument("--sid", help="override caller session id")
    p_supbeat.add_argument("--nonce", help=NONCE_ARG_HELP)

    # Release requires continuity proof. Roster absence plus stale heartbeat
    # allows seizure; view-derived ids cannot authorize forced release.
    p_suprel = sub.add_parser("sup-release",
                              help="release the supervisor claim cleanly (claim holder only); "
                                   "the next sup-boot claims fresh with no seizure")
    p_suprel.add_argument("--reason", help="short note recorded in the journal and the claim")
    p_suprel.add_argument("--sid", help="override caller session id")
    p_suprel.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_supstat = sub.add_parser("sup-status", help="read-only supervisor claim/handshake status")
    p_supstat.add_argument("--json", action="store_true")

    p_supguard = sub.add_parser(
        "sup-guard",
        help="one-line two-live-body verdict before supervisor revival")
    p_supguard.add_argument(
        "--do", action="store_true",
        help="re-verify immediately, then send WAKE; OK does nothing; DISPATCH/PAGE remain interface verdicts")
    p_supguard.add_argument(
        "--json", action="store_true",
        help="include read-only guard detail as one JSON line")

    # three-tier §11.2: self-monitored context band measurement (read-only).
    p_supctx = sub.add_parser(
        "sup-context",
        help="read this session's own context occupancy vs its tier's context "
             "band -- supervisor 350-400k, worker 250-300k (§11.2)")
    p_supctx.add_argument("--sid", help="override caller session id (out-of-band inspection)")
    p_supctx.add_argument("--json", action="store_true")

    # three-tier §8: operator-gate routing state file.
    p_supdec = sub.add_parser(
        "sup-decision",
        help="operator-gate routing (§8): --raise (supervisor parks a decision), "
             "--answer (interface answers), --clear, or show")
    p_supdec.add_argument("--raise", dest="question", metavar="QUESTION",
                          help="supervisor routes an operator-only decision and parks "
                               "(claim holder only; one open at a time)")
    p_supdec.add_argument("--context-ref", dest="context_ref",
                          help="a pointer (file#L, journal ref) the interface reads for context")
    p_supdec.add_argument("--answer", metavar="TEXT",
                          help="the interface tier writes the operator's decision")
    p_supdec.add_argument("--clear", action="store_true",
                          help="remove the open decision (consumed)")
    p_supdec.add_argument("--json", action="store_true")
    p_supdec.add_argument("--sid", help="override caller session id (for --raise)")
    p_supdec.add_argument("--nonce", help=NONCE_ARG_HELP)

    # Match the keeper's tmux defaults and dry-run interface for this shared channel.
    p_supnotify = sub.add_parser(
        "sup-notify",
        help="type one `SUPERVISOR: <text>` line into the interface tmux "
             "window (claim holder only): the graceful-end announcement the "
             "interface acts on")
    p_supnotify.add_argument("text",
                             help="the line's text -- prefixed with `SUPERVISOR: ` "
                                  "and sanitised to one printable line before it is typed")
    p_supnotify.add_argument("--tmux-session", dest="tmux_session", default="work",
                             help="tmux session holding the interface window (default: work)")
    p_supnotify.add_argument("--window", default="fleet",
                             help="tmux window name (default: fleet)")
    p_supnotify.add_argument("--dry-run", dest="dry_run", action="store_true",
                             help="print the exact bytes and stop: no lock, no claim "
                                  "read, no write, no tmux")
    p_supnotify.add_argument("--sid", help="override caller session id")
    p_supnotify.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_suphb = sub.add_parser("sup-handoff-begin", help="dispatch a handoff successor (claim holder only)")
    p_suphb.add_argument("--model", help="model for the successor session")
    p_suphb.add_argument("--permission-mode", dest="permission_mode",
                         choices=list(MODE_FLAGS),
                         help="fleet mode name for the successor session "
                              f"(default: {SUCCESSOR_DEFAULT_MODE})")
    p_suphb.add_argument("--sid", help="override caller session id")
    p_suphb.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_suphc = sub.add_parser("sup-handoff-complete", help="verify HANDSHAKE and transfer the claim")
    # R6: an incarnation id is a PATH COMPONENT (`handoff_task_file_path`).
    # Shape-check it at the parser so a traversal never reaches the filesystem.
    p_suphc.add_argument("--expect-inc", dest="expect_inc", required=True,
                         type=_argparse_incarnation_id)
    # §6.4: optional. The token verifies the successor; --expect-sid is
    # observability, and a mismatch is a warning naming the fork, not a refusal.
    p_suphc.add_argument("--expect-sid", dest="expect_sid",
                         help="optional: warn (do not refuse) if the HANDSHAKE sid differs")
    p_suphc.add_argument("--sid", help="override caller session id")
    p_suphc.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_supha = sub.add_parser("sup-handoff-abort", help="abort a handoff: stop the limbo successor, resume duty")
    # R3: EITHER handle. `--successor-sid` stops a recorded session;
    # `--successor-inc` also retires an entry that aged out of the join window
    # without ever recording one (nothing is stopped on that path, and the verb
    # says so). Not `required=True` on either, not a mutually-exclusive group:
    # passing both is legitimate and means "this sid AND this inc", which
    # `handoff_entry_matching` requires to agree.
    p_supha.add_argument("--successor-sid", dest="successor_sid",
                         help="sid of the limbo successor to stop")
    p_supha.add_argument("--successor-inc", dest="successor_inc",
                         type=_argparse_incarnation_id,
                         help="incarnation id of the pending successor; retires a "
                              "stale entry that never recorded a sid")
    # Bulk retirement stops no sessions; sid-bearing entries need individual abort.
    p_supha.add_argument("--retire-all", dest="retire_all", action="store_true",
                         help="retire EVERY pending entry that names no session "
                              "(resolvable-stale, superseded, unreadable); stops "
                              "nothing, reports what still stands")
    # rs-MIN-B: an entry whose `minted_at` cannot be read resolves by neither
    # evidence nor time -- the one shape that defeats R3. This is its way out.
    p_supha.add_argument("--force", action="store_true",
                         help="also retire an entry that records no sid and cannot "
                              "be aged (unreadable minted_at), which no other verb "
                              "would ever retire; never stops a session, and is "
                              "DECLINED on an entry whose minted_at reads fine")
    p_supha.add_argument("--sid", help="override caller session id")
    p_supha.add_argument("--nonce", help=NONCE_ARG_HELP)

    return parser


# Minted base64url values can begin with a dash. Normalize their flag pairs
# to argparse's equals form so fleet accepts every nonce or token it mints.
_MINTED_VALUE_FLAGS = ("--nonce", "--handoff-token")


def _absorb_minted_flag_values(argv: list) -> list:
    """Rewrite ["--nonce", V] -> ["--nonce=V"] for the minted-value flags:
    argparse's equals form accepts any value, leading dash included. Every
    other token passes through byte-for-byte; a trailing valueless flag is
    left for argparse to refuse with its ordinary usage error."""
    out = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _MINTED_VALUE_FLAGS and i + 1 < len(argv):
            out.append(f"{tok}={argv[i + 1]}")
            i += 2
        else:
            out.append(tok)
            i += 1
    return out


def main(argv=None) -> int:
    # Use UTF-8 with replacement before output: legacy Windows code pages
    # cannot encode arbitrary Unicode roster and transcript text.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    parser = build_parser()
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    try:
        # Strip the global home selector before parsing so position and subparser
        # destinations cannot change its meaning. Fleet refusals stay inside try;
        # argparse usage errors retain their own exit code.
        stripped, home_flag = strip_global_fleet_home(raw_argv)
    except FleetCliError as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1
    args = parser.parse_args(_absorb_minted_flag_values(stripped))
    try:
        # Land is a repository operation owned by its leaf module. It must not
        # resolve or read fleet-home state before it can prepare a lane.
        if args.command == "land" or args.command == "brief":
            return (fleet_land.cmd_land(args) if args.command == "land"
                    else fleet_brief.cmd_brief(args))
        # Bare init creates in cwd; explicit selectors and statusline setup use the
        # normal resolver. Do not synthesize args.home, which also appends the
        # machine-list entry and invokes the destructive tier.
        if (args.command == "init" and args.home is None
                and home_flag is None and not args.statusline):
            return cmd_init(args, create_in=Path.cwd())
        # §5's resolution order, applied before dispatch. Returns an exit code
        # only at the terminus (§5 step 5: views render and exit 0); every other
        # outcome either sets FLEET_HOME or refuses.
        terminus_rc = apply_resolved_home(args, flag=home_flag)
        if terminus_rc is not None:
            return terminus_rc
        if args.command == "home":
            return cmd_home(args)
        if args.command == "knowledge":
            return cmd_knowledge(args)
        if args.command == "homes":
            return cmd_homes(args)
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
        if args.command == "index":
            return fleet_index.cmd_index(args)
        if args.command == "q":
            return fleet_index.cmd_q(args)
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "sup-boot":
            return cmd_sup_boot(args)
        if args.command == "sup-spawn":
            return cmd_sup_spawn(args)
        if args.command == "sup-checkpoint":
            return cmd_sup_checkpoint(args)
        if args.command == "journal-roll":
            return cmd_journal_roll(args)
        if args.command == "interface-register":
            return cmd_interface_register(args)
        if args.command == "wave-close":
            return cmd_wave_close(args)
        if args.command == "sup-heartbeat":
            return cmd_sup_heartbeat(args)
        if args.command == "sup-release":
            return cmd_sup_release(args)
        if args.command == "sup-status":
            return cmd_sup_status(args)
        if args.command == "sup-guard":
            return cmd_sup_guard(args)
        if args.command == "sup-context":
            return cmd_sup_context(args)
        if args.command == "sup-notify":
            return cmd_sup_notify(args)
        if args.command == "sup-decision":
            return cmd_sup_decision(args)
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
    except SupervisorLifecycleRefusal as exc:
        # Catch the subclass first so its graded exit codes remain reachable.
        print(f"fleet: {exc}", file=sys.stderr)
        return exc.rc
    except SupervisorContinuityError as exc:
        # Catch nonce refusals before FleetCliError collapses them to exit 1.
        print(f"fleet: {exc}", file=sys.stderr)
        return SUPERVISOR_CONTINUITY_RC
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
