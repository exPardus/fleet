"""fleet.py -- claude-fleet core logic layer.

Single-file, stdlib-only CLI for one Claude Code "manager" session to spawn,
monitor, steer, and hand off multiple headless "worker" sessions.

Layering: pure-logic core (paths, registry, events, PID liveness,
stream-jsonl parsing, prompt composition, permission mode mapping) first,
then the argparse-based main() and its subcommands built on top of those
functions.

See docs/SPEC.md for the full design (this file implements SPEC sections
2, 4, 5, 6, 8, 11, 14).

Requires Python 3.10+ -- declared once, as data, in `MIN_PYTHON_VERSION`
below; every other statement of the floor (this docstring, `bin/hooks/
run_py.sh`, SPEC §14, docs/specs/portability.md D9) is checked against that
constant by `TestInterpreterFloor`. Stdlib only -- no pip deps (SPEC §14 /
docs/specs/portability.md fixed constraints). Two PLATFORM backends are
implemented -- Windows and POSIX (macOS + Linux), see the platform adapter
block below; the module is held to the 3.10 floor so the POSIX side runs
under distro pythons without a language-version bump.

`py -3.13` in `bin/fleet.cmd` and CLAUDE.md is this dev machine's PREFERRED
interpreter, not the floor -- a bare `python` there resolves to 3.10.1.
"""
from __future__ import annotations

import argparse
import ctypes
import functools
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The interpreter floor, in ONE place (posix-port campaign, follow-up 2).
# Everything else that states it -- this module's docstring, the
# `sys.version_info >= (3, 10)` gate and the candidate list in
# `bin/hooks/run_py.sh`, SPEC §14, docs/specs/portability.md D9 -- is checked
# against this constant by `TestInterpreterFloor`, so the floor cannot drift
# between the shim that SELECTS an interpreter and the docs that promise one.
#
# 3.10, not 3.13, because `run_py.sh` must keep working on distro pythons:
# Ubuntu 22.04 LTS ships 3.10 as `python3` (portability.md D9), and the Linux
# box this campaign verified against runs 3.12.3. Raising the floor to match
# `bin/fleet.cmd`'s `py -3.13` would break both.
#
# Holding a floor means RUNNING at it. D9's original justification was a grep
# for 3.11+/3.12+ APIs; that grep missed `datetime.fromisoformat("...Z")`
# (caught later by the N2 fix wave) and `BaseException.add_note` (caught by
# this campaign, by actually running the suite on 3.10.1 -- see
# `_stash_short_id_note`). A grep is a claim; a floor run is evidence.
MIN_PYTHON_VERSION = (3, 10)

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


def claude_daemon_lock_path() -> Path:
    """~/.claude/daemon.lock -- the vendor's background-daemon singleton lock.
    READ-ONLY to fleet, always: nothing in this module may create, modify or
    delete it (M-E, docs/specs/native-substrate.md, the stale-lock hazard row).
    Separate helper so tests redirect it instead of reading a real machine.

    Portable by construction: `Path.home()/".claude"` is the vendor's config
    dir on Windows, macOS and Linux alike, so this needs no platform branch
    (only the PLATFORM adapter block may carry one anyway).
    [UNVERIFIED -- no POSIX box] The POSIX filename was not observed; it is the
    same code path, and every consumer treats an absent file as "nothing to
    check", so a POSIX-side name drift degrades to a PASS-note, never a FAIL."""
    return Path.home() / ".claude" / "daemon.lock"


def claude_daemon_log_path() -> Path:
    """~/.claude/daemon.log -- the vendor's supervisor log. READ-ONLY, same
    rules and same portability argument as claude_daemon_lock_path()."""
    return Path.home() / ".claude" / "daemon.log"


def statusline_script_path() -> Path:
    return FLEET_HOME / "bin" / "fleet_statusline.py"


# The `~/.claude/fleet-home` marker lived here until 2026-07-22. It recorded
# the absolute FLEET_HOME for ONE reader: the plugin's SessionStart hook,
# which under a marketplace install runs from a cache copy of this repo whose
# own `state/` is gitignored and empty, so it could not resolve the real home
# from its own location. That hook is gone (terminal-surface D7) and the
# marker had no other reader -- `fleet.py`, `fleet_statusline.py` and both
# shell shims resolve $FLEET_HOME, else their own location, and the autoclean
# scheduled task carries an explicit `--fleet-home <path>`.
#
# It is deleted rather than kept, because it was fleet's only unconditional
# write to global machine state: plain `fleet init` stamped `~/.claude/`
# whether or not the operator had asked for anything outside the repo. That is
# the same instinct D7 removed from the plugin manifest. `fleet init
# --statusline` still writes `~/.claude/settings.json`, and that is fine --
# it is what the flag is for.
#
# Do not reintroduce it as a resolution input. A stale marker would silently
# redirect the CLI -- `fleet clean` and `fleet kill` included -- at a
# different fleet's registry.


def now_iso() -> str:
    """Current UTC time, second precision, matching the registry schema."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# === PLATFORM ADAPTER START (SPEC §14 portability mandate) ===
#
# This is the ONLY section of fleet.py permitted to branch on os.name /
# sys.platform, read subprocess creation flags, or shell out to an
# OS-specific tool (schtasks/crontab, ctypes/kernel32). Every other
# function in this module calls through the PLATFORM singleton below
# instead of doing any of that itself. Two implemented backends:
# _WindowsPlatform (schtasks scheduling, FILE_APPEND_DATA outcome append)
# and _PosixPlatform (crontab scheduling, O_APPEND outcome append --
# macOS + Linux, the posix-port branch). UnsupportedPlatformError remains
# the contract for any future genuinely-unportable operation. A
# source-scan test (test_steering.py) enforces that no other function in
# this module references os.name/sys.platform.
# ---------------------------------------------------------------------------

_FILE_APPEND_DATA = 0x0004
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80


class AutocleanTaskQueryError(Exception):
    """The scheduler could not say whether the autoclean task exists (F3:
    transient failure, access denied, timeout). Raised by BOTH backends --
    schtasks on Windows, `crontab -l` on POSIX -- since both can fail in a
    way that is not an answer. Callers fail CLOSED -- treating this as "task
    absent" would let an install clobber a foreign task of the same name on a
    hiccup (schtasks `/Create /F`, or a crontab rewrite that drops the
    foreign line)."""


class UnsupportedPlatformError(NotImplementedError):
    """A PLATFORM operation this OS has no implementation for.

    NOT raised by any adapter method today: both backends implement the whole
    surface (the posix port filled in what _PosixPlatform once stubbed). It is
    the reserved contract for a genuinely-unportable FUTURE operation -- one
    where some OS has no equivalent primitive at all, as opposed to a
    different tool for the same job (schtasks vs crontab, FILE_APPEND_DATA vs
    O_APPEND), which is what the adapter exists to absorb silently.

    Two handlers stay wired, and must: `_doctor_check_autoclean` catches it
    around `PLATFORM.autoclean_task_query` and degrades that tier to a
    "unsupported on this platform -- skipped" PASS-note rather than failing
    doctor; `main()` lists it in the top-level except so any other unportable
    call exits 1 with a `fleet: <message>` line instead of a traceback. A new
    unportable method inherits the second for free on the OS that lacks it."""


class _WindowsPlatform:
    """Windows implementation of every OS-specific fleet operation."""

    # Path-comparison semantics for scheduled-task ownership (D8, closed by
    # the posix-port campaign). NTFS/ReFS compare paths case-insensitively
    # and `\` is THE separator -- and schtasks XML round-trips genuinely
    # emit both spellings of one path -- so folding both variances is
    # required here for `_fleet_task_is_ours` to recognise fleet's own task.
    task_paths_are_case_insensitive = True
    task_paths_use_backslash_separator = True

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

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Single-syscall atomic append. Opens the file for FILE_APPEND_DATA
        access ONLY (no GENERIC_WRITE) -- the Win32 kernel documents this
        access mode as giving each WriteFile call atomic append semantics
        across concurrently-open handles/processes, so two writers appending
        "at the same instant" (Stop hook + fleet-side tombstone, see the
        outcome-store banner) never interleave or clobber each other's line.

        Deliberately NOT `os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)`
        + `os.write`: on Windows that goes through the C runtime's O_APPEND
        emulation, which lseek()s to EOF and write()s as two separate steps
        per call -- a real TOCTOU race between handles that reproducibly
        drops whole clean records under concurrent writers (confirmed
        empirically: 4 threads x 250 records via os.open+O_APPEND lost ~17%
        of records with zero JSON-decode errors, i.e. silent loss, not
        corruption). The FILE_APPEND_DATA-only handle below is the actual
        OS-level fix; verified to lose zero of 1000 records under the same
        test. (The POSIX backend CAN use O_APPEND -- there the kernel
        performs seek+write atomically; the CRT emulation race is
        Windows-only.)"""
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
            # Roll-up item 4: a partial write (ok=True, written.value <
            # len(data)) produces a torn JSONL line that read_outcomes
            # silently skips -- the exact silent-loss failure class T1's
            # CRITICAL fix existed to kill. Treat it the same as a WriteFile
            # failure: raise OSError.
            if not ok or written.value != len(data):
                raise OSError(f"WriteFile failed for {path}: {ctypes.WinError()}")
        finally:
            kernel32.CloseHandle(handle)


class _PosixPlatform:
    """POSIX backend (posix-port): macOS + Linux.

    Autoclean scheduling uses the user crontab on both OSes -- macOS still
    ships cron, and one crontab backend is strictly simpler than a
    launchd-plist/cron split (launchd can become a refinement if cron's
    macOS sandboxing ever bites; fleet's autoclean only touches user-owned
    FLEET_HOME paths, which cron may). The fleet-owned entry is found by a
    trailing `# <task_name>` tag, never by parsing schedules -- the same
    "match our own marker, refuse to guess" doctrine as the schtasks
    backend's task-name match."""

    # Path-comparison semantics for scheduled-task ownership (D8, closed by
    # the posix-port campaign). The mirror image of the Windows declaration:
    # ext4/APFS-case-sensitive compare paths byte-for-byte, and `\` is an
    # ordinary filename character, not a separator. Folding either variance
    # here would make two GENUINELY DIFFERENT paths compare equal -- a false
    # MATCH on a predicate that decides whether a scheduled job may be
    # overwritten. See `_normalize_task_token` and
    # `TestTaskPathSemanticsFollowTheFilesystem`.
    #
    # macOS note: HFS+/APFS are usually case-INSENSITIVE, so this
    # declaration is conservative there rather than exact -- it can only
    # produce the safe error (refusing a task that is provably the
    # operator's, recoverable with `--force`), never the dangerous one
    # (adopting a task that is not ours). Case-sensitivity is a per-volume
    # property on macOS, not a per-OS one, so no static declaration can be
    # exact; erring toward refusal is the whole doctrine of this predicate.
    task_paths_are_case_insensitive = False
    task_paths_use_backslash_separator = False

    def _cron_tag(self, task_name: str) -> str:
        return f"# {task_name}"

    def _read_crontab(self, run):
        """(lines, error). lines is None on failure; [] means 'user has no
        crontab', a DEFINITIVE absence (crontab -l exits nonzero for it,
        so it must be told apart from access failures by message -- cron
        implementations do not localize 'no crontab', unlike schtasks'
        locale-translated not-found error that forced the CSV dance on
        Windows)."""
        try:
            proc = run(["crontab", "-l"], capture_output=True, text=True,
                       timeout=30)
        except Exception as exc:
            return (None, f"crontab listing failed: {exc}")
        if proc.returncode == 0:
            return ((proc.stdout or "").splitlines(), "")
        if "no crontab" in (proc.stderr or "").lower():
            return ([], "")
        return (None, f"crontab listing exit {proc.returncode}: "
                      f"{(proc.stderr or '').strip()[:200]}")

    def _write_crontab(self, lines, run):
        """(ok, message). Installs the given lines as the user crontab."""
        text = "\n".join(lines) + ("\n" if lines else "")
        try:
            proc = run(["crontab", "-"], input=text, capture_output=True,
                       text=True, timeout=30)
        except Exception as exc:
            return (False, str(exc))
        if proc.returncode != 0:
            return (False, (proc.stderr or proc.stdout or "").strip()[:300])
        return (True, "")

    def autoclean_task_query(self, task_name: str, run=subprocess.run):
        """None ONLY when the entry is definitively absent; its command
        string when installed ("" if the line is unparseable); raises
        AutocleanTaskQueryError when existence cannot be determined (F3:
        callers must fail CLOSED, same contract as the schtasks backend)."""
        lines, err = self._read_crontab(run)
        if lines is None:
            raise AutocleanTaskQueryError(err)
        tag = self._cron_tag(task_name)
        for line in lines:
            if line.rstrip().endswith(tag):
                body = line.rsplit(tag, 1)[0].strip()
                # five schedule fields, then the command
                parts = body.split(None, 5)
                return parts[5] if len(parts) == 6 else ""
        return None

    def autoclean_task_install(self, task_name: str, command: str,
                               interval_hours: int, run=subprocess.run):
        """(ok, message). Idempotent re-install: any existing fleet-tagged
        line is replaced -- the caller is responsible for the
        refuse-foreign-task check BEFORE calling this (same split as the
        schtasks backend's /F)."""
        # % is a line separator inside a crontab command field; a command
        # containing one would be silently mangled, not run.
        if "%" in command or "\n" in command:
            return (False, "command contains a character cron cannot "
                           "carry literally (% or newline)")
        lines, err = self._read_crontab(run)
        if lines is None:
            return (False, err)
        tag = self._cron_tag(task_name)
        kept = [ln for ln in lines if not ln.rstrip().endswith(tag)]
        kept.append(f"0 */{int(interval_hours)} * * * {command} {tag}")
        return self._write_crontab(kept, run)

    def autoclean_task_remove(self, task_name: str, run=subprocess.run):
        """(ok, message). Missing entry counts as failure -- the caller
        reports it; nothing here raises."""
        lines, err = self._read_crontab(run)
        if lines is None:
            return (False, err)
        tag = self._cron_tag(task_name)
        kept = [ln for ln in lines if not ln.rstrip().endswith(tag)]
        if kept == lines:
            return (False, f"no crontab entry tagged {tag!r}")
        return self._write_crontab(kept, run)

    def atomic_append_bytes(self, path: Path, data: bytes) -> None:
        """Single-syscall atomic append via O_APPEND. POSIX specifies that
        for a file opened with O_APPEND the seek-to-EOF and the write are
        performed as one atomic step, so concurrent writers (Stop hook +
        fleet-side tombstone) never interleave records this small -- the
        same guarantee the Windows backend buys with a FILE_APPEND_DATA-only
        handle (the CRT-emulation TOCTOU that forced ctypes there is a
        Windows-only defect; see that docstring). A short write would tear
        a JSONL line that read_outcomes silently skips, so it raises
        exactly like the Windows partial-write check."""
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
                       spawned_by=None, dispatch_kind=None, category=None,
                       spawned_by_lineage=None) -> dict:
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
        # claim-nonce §6.2 (D2): the spawning claim's `lineage_id`, or None.
        # Additive/nullable, written where `spawned_by` is written and carried
        # across respawn exactly as it is. It lets a LATER body of the same
        # lineage -- one whose sid rotated through a fork-steer or a handoff --
        # own the workers that lineage spawned, but ONLY when that body proved
        # continuity in the same invocation (`_worker_is_foreign`'s third arg).
        # A record without it (pre-field, or a human-shell spawn) reads as
        # None and gets today's spawned_by-only ownership answer.
        "spawned_by_lineage": spawned_by_lineage,
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
        # n2 (review MD-CONTRACT-REVIEW-2026-07-17.md): TWO provenances, and
        # the difference is load-bearing. Normally the CLI's OWN short id, read
        # from `--bg` stdout (G6 fallback) -- that is the capture the
        # `gone`->success inference rests on. But on the fast-completion path
        # (grep `fast_sid.partition`, 2 of the 6 write sites) there is no
        # stdout to read and it is DERIVED from the sid by string-split, which
        # is only as good as the CLI's id format. See `_native_job_ref` and
        # docs/specs/native-substrate.md (G10 row, "the `gone`->success
        # inference has a precondition") before trusting this field as a ref.
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
    """Append one JSON line {"ts", "kind", "name", **fields} to events.jsonl.

    Written through `_atomic_append_bytes` for the same reason
    `append_outcome` is (T1's CRITICAL finding): events.jsonl has genuinely
    concurrent writers -- the manager, the scheduled autoclean task, and any
    worker invoking the CLI -- and a plain buffered `open(..., "a")` does NOT
    append atomically on Windows. The CRT's O_APPEND emulation seeks to EOF
    and writes as two separate steps, so concurrent writers drop whole clean
    records with ZERO JSON-decode errors: silent loss, not corruption, which
    is the failure mode nothing downstream can detect. Measured on this file
    before the fix: 4 threads x 250 records lost 9-12 of 1000 every run.

    `_atomic_append_bytes` raises OSError on a short write as well as on
    CreateFileW/WriteFile failure; the plain open()+write() it replaces also
    raised OSError, so `_append_event_quiet`'s deliberate swallow still
    covers every failure this can produce."""
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), "kind": kind, "name": name}
    record.update(fields)
    line = json.dumps(record)
    _atomic_append_bytes(events_path(), (line + "\n").encode("utf-8"))


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


# claim-nonce §6.5 / §13 item 1, council option (i) -- the NARROW arm.
#
# The handoff successor is dispatched as a fleet worker under this exact name
# shape (see `_successor_worker_name`, used by `cmd_sup_handoff_begin`), so it
# carries `FLEET_WORKER` like any other worker -- and its first act after
# claim transfer is `sup-checkpoint`, a `_require_claim_holder` caller. A
# BLANKET `FLEET_WORKER` refusal would therefore break the one session the
# handoff exists to serve, and would break three-tier's `sup-spawn`, which
# spawns the supervisor itself as a fleet worker.
#
# The shape is unforgeable through `fleet spawn`: `NAME_RE` is `^[a-z0-9-]+$`,
# so `|` is forbidden in every spawnable worker name and no worker can be
# named into the exemption. Held here, beside `_worker_env`, so the dispatch
# and the refusal arm read ONE shape -- two copies of a security-relevant
# literal drift silently, with the dispatch still working while the exemption
# quietly stops matching it.
_SUPERVISOR_SHAPED_WORKER_RE = re.compile(r"^sup\|[^|]+\|successor$")


def _successor_worker_name(successor_inc: str) -> str:
    """The `--bg -n` name `cmd_sup_handoff_begin` dispatches a successor under."""
    return f"sup|{successor_inc}|successor"


def _is_supervisor_shaped(name) -> bool:
    """True iff `name` is a handoff-successor worker name. Never raises on a
    non-string: `os.environ.get` can only return `str | None` today, but this
    is also called on registry-sourced values."""
    return isinstance(name, str) and _SUPERVISOR_SHAPED_WORKER_RE.match(name) is not None


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
    could quietly retire its siblings with no confirmation.

    The re-stamp is MEASURED, not assumed -- twice, independently, in two
    different live `--bg` workers:

        py -3.13 -c "import os; print(repr(os.environ.get('CLAUDE_CODE_SESSION_ID')))"
          -> '820762d0-5298-4b1b-9471-4048ea27e278'    (worker mf-fix)
          -> '1a9374bd-df92-42ad-972a-06693aeef272'    (a later worker)

    Each read back as exactly that worker's own `session_id` in the registry,
    not the manager's (the manager's is what `spawned_by` holds). So the strip
    below does not leave a worker session-id-less: it leaves it carrying its
    OWN id, and the `caller is None` early-out in `_confirm_destructive` is
    unreachable from a worker. Pinned at both levels --
    tests/test_destructive_guard.py::TestAWorkerIsNotExempt (unit) and
    ::TestAWorkerCallerIsNotExempt (end-to-end, real CLI, real worker env)."""
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

# The observed production shape instead (M-C park journal 2026-07-16,
# knowledge/lessons.md:607): a LOCAL wall-clock time + IANA tz name, e.g.
# "resets 4:40am (Asia/Qyzylorda)" or "resets 12am (Asia/Qyzylorda)" (the
# hour-only form is the production gap this fallback closes). Only
# consulted when the ISO regex above finds nothing (ISO keeps precedence).
#
# D4 + m1 + DQ1 + ND-2 + ND-5 (MD-ULPARSER-REVIEW-2026-07-17.md D4;
# ME-UL-REVIEW-2026-07-21.md m1/DQ1/ND-2/ND-5): three straight attempts to
# characterise an OPEN single-segment tz group as safe were each wrong in
# turn -- D4's original gap comment claimed these names need a curated
# alias table (false: they're canonical IANA keys); the DQ1 ruling that
# widening "can never convert a null-park into a wrong horizon" (false:
# `EST` in July resolves 1h off from `America/New_York`); and the ND-2
# fix's own replacement claim that the mismatch "always resolves LATE,
# never early" (also false -- see below). Every round narrowed the claim
# and every round still overreached, because "single-segment tzdb key" is
# not a category with one safety direction: it is a mix of geographic
# aliases (exact), legacy fixed-offset keys (late-drifting relative to a
# DST-observing zone at the same standard offset, e.g. `EST` vs
# `America/New_York`), and rule-only zones that themselves observe DST
# (early-drifting relative to a zone permanently at that standard offset,
# e.g. `CET` resolves 1h EARLY vs `Africa/Algiers`, which is CET-standard
# year-round with no DST -- and `EST` itself flips to early against
# `Pacific/Easter`, the same key ND-2's fix called "known late"). No
# wording over that mixed set can be made true.
#
# ND-5 restructures instead of re-arguing: the single-segment branch is
# now a CLOSED allowlist of fixed-UTC aliases only --
# `{UTC, UCT, Universal, Zulu, Greenwich, GMT0, GMT+0, GMT-0}`. Every
# member means UTC and only UTC, in every season -- no DST, no standard-
# offset ambiguity, so no colloquial-vs-tzdb divergence is possible in
# EITHER direction. This is a structural guarantee (closed enumeration),
# not an argued one (open set + validator), which is what the prior three
# rounds each mistook for equivalent and weren't. It keeps the whole of
# what D4 asked for -- `"a bare (UTC) is plausible enough in a message to
# be worth a follow-up"` -- and admits nothing else: `(EST)`, `(CET)`,
# `(Singapore)` and any other bare word null-park via this regex, same as
# before D4, never reaching `ZoneInfo` at all. Multi-segment names
# (`Area/City`) are untouched by this change and remain fully open, with
# `zoneinfo.ZoneInfo` -- not this regex -- as their validator: a name it
# resolves yields a horizon, a name it rejects null-parks via the existing
# blanket `except Exception: return None`.
#
# posix-port campaign (Class 1): the closed set is DATA here, and the two
# places that consume it -- the regex that ADMITS a name and
# `_next_local_reset_utc`'s fixed-offset resolver that CONVERTS one -- are
# both derived from this one tuple, so they cannot drift apart. A member the
# regex admitted but the resolver did not recognise would silently fall
# through to `zoneinfo` and reintroduce, for that member alone, exactly the
# tz-database dependency the fixed-offset resolution exists to remove.
# Pinned by `test_regex_alternation_and_resolver_share_one_source_of_truth`.
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
    """UTC ISO-8601 instant of the next occurrence of `hour:minute` local wall-
    clock time in the named IANA tz, or None if the tz can't be resolved.

    A member of `_LOCAL_UTC_ALIAS_NAMES` (ND-5's closed fixed-UTC set) is
    resolved to `timezone.utc` DIRECTLY and never reaches `zoneinfo` at all
    -- see the inline comment below for why routing a closed set through a
    tz database made it not closed. Every other name (only multi-segment
    `Area/City` shapes can reach here, per `_LIMIT_RESET_LOCAL_RE`) still
    goes to `zoneinfo`, which remains their sole validator.

    `zoneinfo` is stdlib but its DATA is not guaranteed on Windows (no
    `tzdata` pip package -- this repo stays stdlib-only; `fleet doctor`'s
    `tzdata` check reports its absence). The module is imported here
    (inside the helper, not at module scope) so a plain `import fleet`
    never gains a hard dependency on tz-data being present; any lookup
    failure (unknown zone, missing data, whatever shape the stdlib raises)
    falls back to None -- a conservative null-horizon park, never a
    guessed UTC time or approximated offset.

    `now` is required, keyword-only, with no default (MD-ULPARSER-REVIEW-
    2026-07-17.md §5.1): this helper's sole caller (`_parse_limit_signal`)
    only ever reaches it from inside an `elif now is not None:` guard, so a
    wall-clock fallback here was unreachable in production -- but it was a
    *latent* footgun, reachable the moment any future caller invoked this
    directly without `now=`, silently reproducing the exact wrong-instant
    bug (C1) the N3 fix wave closed elsewhere. Removing the default makes
    that invariant structural (a `TypeError` at the call site) rather than
    a convention a future caller could forget.

    D3 fix (ME-UL-REVIEW-2026-07-21.md M1): a prior version of this
    docstring claimed both DST edge cases -- the nonexistent spring-forward
    "gap" and the repeated fall-back "fold" -- resolved late, never early.
    That was FALSE for the fold case: `moment.replace(...)` without an
    explicit `fold=` inherits `moment`'s own fold, which is 0 unless the
    anchor itself falls inside the one repeated hour of the year -- so in
    practice the ambiguous candidate resolved to its FIRST (earlier, DST)
    occurrence, up to one DST delta EARLY.

    The obvious one-line fix -- add `fold=1` to the SAME `.replace(...)`
    call that sets hour/minute -- does NOT work and would have shipped a
    silent no-op: per PEP 495, `aware_datetime + timedelta` resets `fold`
    to 0 on the result. The very next line, `candidate += timedelta(days=1)`
    (taken whenever the target time has already passed today, which is
    exactly the case a next-day fall-back horizon needs), erases any
    `fold=1` set before it. Verified empirically: setting `fold=1` inside
    the same `.replace()` and then rolling to the next day round-trips
    back to `fold=0` and the identical (wrong, early) instant.

    Fix actually applied: after any day-rollover, evaluate the final
    candidate at BOTH `fold=0` and `fold=1` and keep whichever converts to
    the LATER UTC instant. This is deliberately fold-agnostic rather than
    "always force fold=1", because forcing fold=1 unconditionally would
    also flip the GAP case: today's default (fold inherited, effectively
    0) already gives the gap case's later, pre-transition reading, so
    forcing fold=1 there would make the gap case resolve EARLY where it
    currently resolves late -- trading a real bug in the fold case for a
    new one in the gap case. Taking `max()` of the two candidates gets
    both directions right without needing to classify which case (gap vs.
    fold) applies:
      - gap (spring-forward): fold=0 and fold=1 give the pre- and
        post-transition offsets respectively; the pre-transition (fold=0)
        reading is later, so `max()` keeps today's already-correct value.
      - fold (fall-back): fold=0 and fold=1 give the first (DST) and
        second (standard-time) occurrences respectively; the second
        (fold=1) reading is later, so `max()` now takes it unconditionally
        instead of depending on the anchor's fold.
    Both directions are now genuinely late-erring, never early, consistent
    with this module's standing bias (a late resume beats an early one,
    and either beats a fabricated horizon). The host zone observed in
    production (Asia/Qyzylorda) has no DST, so this path is dormant today;
    documented here because the helper is generic and the tz name comes
    from untrusted message text, so a DST zone can reach it. Pinned by
    `TestNextLocalResetUtcDst` (America/New_York fold + gap cases)."""
    alias = tz_name.strip().lower() if isinstance(tz_name, str) else None
    if alias in _LOCAL_UTC_ALIAS_LOOKUP:
        # posix-port campaign, Class 1 [PRODUCT DEFECT]. ND-5's whole point
        # was a CLOSED set: every member means UTC and only UTC, in every
        # season, BY DEFINITION. Resolving them through `zoneinfo` made that
        # supposedly-closed set depend on the host's tz database, which is
        # the opposite of closed -- and seven of the eight members are tzdb
        # "backward" LINK names (`UCT`, `Universal`, `Zulu`, `Greenwich`,
        # `GMT0`, `GMT+0`, `GMT-0`) that a stock Debian/Ubuntu `tzdata`
        # package does not ship. Windows resolved them only via the `tzdata`
        # PyPI package, macOS via its full system tzdb; on Linux all seven
        # raised `ZoneInfoNotFoundError` and null-parked. The failure was in
        # the safe direction (D2: unresolvable -> conservative null horizon,
        # never a guessed instant), so nothing was ever resumed at a wrong
        # time -- but the guarantee ND-5 claimed to make structurally was in
        # fact platform-dependent, which is a correctness-of-guarantee bug.
        # Resolving to a fixed zero offset makes the enumeration actually
        # closed, on every host, with or without a tz database installed.
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
    """Best-effort (reset_at, kind) from a limit-shaped stderr tail. reset_at is
    an ISO-8601 UTC string if one is present, else None (park with an unknown
    horizon -- never auto-resumed blind); kind is 'weekly' | 'session_5h' | None
    by keyword. Parser is pinned to the observed signal by the kernel probe
    later; today it stays conservative and returns None where uncertain.

    ISO-8601 (`_LIMIT_RESET_RE`) keeps absolute precedence over existing
    consumers. When absent, falls back to the LOCAL wall-clock + IANA tz
    shape (`_LIMIT_RESET_LOCAL_RE`) actually observed in production
    (M-D item 3) -- 12am/12pm are normalized to 00:00/12:00 (the classic
    12-o'clock bug), and the next occurrence at-or-after `now` of that
    wall-clock time is converted to UTC via `_next_local_reset_utc`. `now`
    is keyword-only and REQUIRED (no default -- MD-ULPARSER-REVIEW-2026-
    07-17.md §5.1): its sole production caller (`transcript_limit_scan`)
    already passes the transcript record's own timestamp on every call
    (C1 fix wave), possibly `None` when that timestamp is absent or
    unparseable, so requiring the keyword costs production nothing and
    removes a wall-clock default that was reachable only by a future
    caller forgetting `now=` -- the exact shape C1 itself took. Passing
    `now=None` explicitly is still how a caller opts into "no anchor
    available"; it is the *default* that is gone, not the `None` value.

    D2 fix (MD-ULPARSER-REVIEW-2026-07-17.md): the local-format hour is
    validated to the 1..12 range a 12-hour clock actually has before any
    am/pm arithmetic runs. Without this, `"resets 13am"` silently computed
    `hour24 = 13` (the am-branch only special-cases `hour == 12`) and
    produced a well-formed but WRONG horizon (1pm) -- worse than no
    horizon, since a park then resumes at the wrong instant and can burn a
    second limit hit. An out-of-range hour takes the same null-park branch
    as an unresolvable tz or missing tz-data (`reset_at` stays `None`);
    `kind` keyword-detection is unaffected, since it reads the raw text
    independently of the hour parse.

    N3 fix wave (MD-ULPARSER-REVIEW-2026-07-17.md re-review): `now=None`
    (record timestamp absent or unparseable -- see `_record_time`) no
    longer resolves the local-format branch against the real wall clock.
    That fallback reproduced C1's exact defect -- a confidently wrong
    horizon -- on every path where the anchor is unavailable, including
    every Python-3.10 run pre-N2. Without a message-instant anchor the
    local-format branch is left unresolved (`reset_at` stays `None`): a
    conservative null-horizon park, same standard as an unknown tz or
    missing tz-data. `--force-now` remains the recovery, as documented at
    the `transcript_limit_scan` call site."""
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


def _record_time(rec: dict):
    """Aware UTC datetime from a transcript record's own `timestamp` field,
    or None on absence/garbage. Records carry fractional-second ISO-8601
    (e.g. "2026-07-13T23:48:10.741Z", spike/m0/VERDICTS.md:441) -- NOT
    `_parse_iso`'s strict `%Y-%m-%dT%H:%M:%SZ`, which rejects that
    fractional form.

    N2 fix wave (MD-ULPARSER-REVIEW-2026-07-17.md re-review): plain
    `datetime.fromisoformat(ts)` only accepts a trailing `Z` from Python
    **3.11** -- this repo's documented floor is 3.10 (docs/specs/
    portability.md D9, SPEC.md's multi-platform directive). On 3.10 every
    real (`Z`-suffixed) record raised ValueError here, silently falling
    back to the wall clock and reverting C1 in full. Swap the trailing `Z`
    for an explicit `+00:00` offset before parsing -- `fromisoformat` has
    accepted numeric UTC offsets since 3.7, so this is floor-safe. A
    missing/non-string/unparseable timestamp returns None; per N3 the
    caller treats that as "cannot anchor" and parks a null horizon rather
    than guessing via the wall clock."""
    ts = rec.get("timestamp") if isinstance(rec, dict) else None
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts[:-1] + "+00:00" if ts.endswith("Z") else ts)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


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
    `_parse_limit_signal` against the record's `message.content[].text`,
    anchored via `now=_record_time(rec)` to the TRANSCRIPT RECORD'S OWN
    timestamp -- not the wall clock at parse time (C1 fix wave,
    MD-ULPARSER-REVIEW-2026-07-17.md: `limited` is sticky, so a park's
    horizon is parsed exactly once; anchoring to "now" meant any scan that
    first observed the park after the quoted local reset time had already
    passed rolled the horizon a full day late -- 24h wrong, and never
    self-corrected). Anchoring to the message instant instead yields the
    first occurrence at-or-after when the signal actually fired, which is
    the correct reset regardless of how late the scan runs. A missing or
    unparseable `timestamp` (N3 fix wave, same review doc) is never
    guessed against the wall clock -- without a message-instant anchor,
    the local-format branch stays unresolved and reset_at is None: a
    conservative null-horizon park, same as an unknown tz or missing
    tz-data (`resume-limited --force-now` is the recovery). Never raises:
    a missing/unreadable transcript or an unparseable line both fall
    through to (False, None, None).

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
            reset_at, kind = _parse_limit_signal("\n".join(parts), now=_record_time(rec))
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


# claim-nonce §4.13(b)/§11: the distinct exit code for a failed continuity
# proof. `sup-boot` already publishes 0/2/3 (skills/fleet/SKILL.md:37) and
# main()'s generic arm returns 1, so 4 is the first free value.
SUPERVISOR_CONTINUITY_RC = 4


class SupervisorContinuityError(FleetCliError):
    """A `sup-*` verb refused because the caller could not prove continuity
    (claim-nonce §5.3 rule 5).

    A SUBCLASS, deliberately: every `except FleetCliError` already in the tree
    keeps catching it, so the new code narrows nothing. A sibling class would
    silently escape those handlers and surface as a traceback -- the opposite
    of what a distinct exit code is for.

    The code exists because main()'s generic arm collapses every
    `FleetCliError` to exit 1, which is indistinguishable from a corrupt
    registry, a lock timeout, an unknown worker or a bad flag. "A second body
    of your lineage may be acting" and "you typed the wrong worker name" are
    not the same event, and the refusal message is prose -- the exit code is
    the only thing a caller can script against."""


class SupervisorClaimGateError(SupervisorContinuityError):
    """claim-nonce §7 -- a mutating lifecycle verb refused by THE GATE because
    a supervisor claim is held with a fresh heartbeat and the caller could not
    prove continuity on it.

    A subclass of `SupervisorContinuityError` (hence of `FleetCliError`): a
    gate refusal IS a failed continuity proof, so it inherits the distinct exit
    code (§4.13(b)) and every `except FleetCliError` keeps catching it. Distinct
    only so a reader can tell a gated-verb refusal from a `sup-*` refusal."""


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
    when a short id is known at that point. Pulls it back out, or returns
    None if absent/malformed. See `_stash_short_id_note` for the writer."""
    for note in getattr(exc, "__notes__", None) or ():
        if isinstance(note, str) and note.startswith("fleet_short_id="):
            return note.partition("=")[2] or None
    return None


def _stash_short_id_note(exc: BaseException, short_id: str) -> None:
    """Attach `fleet_short_id=<id>` to an escaping exception, floor-safely.

    posix-port campaign, follow-up 2: this used to be a bare
    `exc.add_note(...)`, and `BaseException.add_note` is **3.11+** while this
    repo's documented floor is `MIN_PYTHON_VERSION` = 3.10 (chosen so Ubuntu
    22.04's system `python3` works -- docs/specs/portability.md D9). The call
    sits inside `except BaseException: ... raise`, so on a 3.10 interpreter it
    did not merely fail to attach the note: the AttributeError REPLACED the
    exception being handled. Measured on 3.10.1, running that exact shape:

        escaping exception type: AttributeError ->
            'KeyboardInterrupt' object has no attribute 'add_note'
        short id recoverable: None

    So on the floor interpreter an operator's Ctrl-C surfaced as a confusing
    AttributeError AND lost the short id -- which is the only handle left to
    a live `--bg` session, i.e. exactly the loss T4 exists to prevent, made
    worse rather than merely absent. `bin/hooks/run_py.sh` will happily
    select python3.10, so this was reachable, not hypothetical.

    `__notes__` is a plain list attribute that 3.11's `add_note` appends to,
    and `_short_id_from_notes` reads it via `getattr` -- so populating it
    directly is behaviourally identical for fleet's own recovery path on the
    floor. The only thing 3.10 loses is the interpreter printing the note in
    the traceback, which fleet never depended on.

    Never raises. A failure to attach a diagnostic note must not replace the
    exception it is annotating -- that is the whole defect being fixed here,
    and a broad guard is the point rather than an oversight."""
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


def _worker_is_foreign(record: dict, caller: str | None, claim_lineage=None) -> bool:
    """True when this session did not spawn the worker.

    Two ways to own it (claim-nonce §6.2):
      * `record["spawned_by"] == caller` -- today's rule, byte-for-byte
        unchanged; or
      * `record["spawned_by_lineage"] == claim_lineage`, where `claim_lineage`
        is the lineage the caller PROVED continuity on in this same invocation
        (`_caller_proven_lineage`). This is what lets a later body of the same
        lineage -- sid rotated by a fork-steer or a handoff -- keep ownership,
        and what a seize deliberately breaks by re-minting the lineage.

    An UNKNOWN owner (`spawned_by` absent -- every record written before that
    field existed) still counts as foreign: the guard fails toward asking. And
    `claim_lineage` defaults to None (an UNPROVEN caller), so the lineage arm
    is inert unless the caller actually proved a claim -- a body must not
    inherit ownership from a field it can simply read out of the registry.
    Both-None never matches, so a legacy worker and an unproven caller do not
    collide on the null."""
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
    prompt.

    The `caller is None` early-out does NOT exempt fleet workers. That was
    filed once as a defect -- "`_worker_env` strips the sid, so every worker
    presents as the exempted human" -- and disproved by measuring inside a live
    worker, whose CLAUDE_CODE_SESSION_ID read back as its OWN registry
    session_id (receipt in `_worker_env`). `caller` is a real value inside a
    worker, so a worker killing a sibling compares against the MANAGER's sid in
    `spawned_by`, comes out foreign, and is refused.

    What this raises is the COST of an unacknowledged kill, not its
    possibility: a worker runs as the same OS user with shell access, so it can
    set CLAUDE_CODE_SESSION_ID to whatever it likes and no env-or-registry
    signal here is a security boundary. The guard is aimed at the over-helpful
    agent that would never think to forge one -- the actual 2026-07-09
    incident -- and it makes the destructive path explicit rather than
    incidental. Do not read it as authorization. (Same conclusion the
    claim-nonce design reached independently: a bearer signal cannot authorize
    on a substrate with no privilege separation.)

    Pinned at both levels, in both directions:
    tests/test_destructive_guard.py::TestAWorkerIsNotExempt (unit) and
    ::TestAWorkerCallerIsNotExempt (end-to-end, real CLI, real worker env) --
    re-introduce a worker exemption and they go red; delete the human-shell
    exemption and they also go red."""
    caller = current_caller_session()
    if caller is None:
        return
    # §6.2: a caller that proves continuity on the supervisor claim owns the
    # workers its lineage spawned, even after its sid rotated. Unproven (no
    # `--nonce`, or a wrong one) yields None and the guard keeps today's
    # spawned_by-only answer.
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

    N1 (re-review, MED): the home guard is evaluated BEFORE anything is
    written. With --autoclean, a guard problem refuses the WHOLE init before
    any write, so a worktree never gets a scheduled task pinned to it;
    --force overrides. Plain `fleet init` writes only inside the fleet home
    and needs no guard.

    Since 2026-07-22 plain `fleet init` writes NOTHING outside the repo. It
    used to also stamp the global `~/.claude/fleet-home` marker, which is why
    this guard once had a second condition and this docstring once described
    a marker-repointing hazard; both went with the marker's only reader (see
    the note above `_home_guard_problems`). `--statusline` remains the one
    flag that touches `~/.claude/`, which is what it is for.

    §7 THE GATE: `init` is a mutating lifecycle verb, so a supervisor-shaped
    caller must prove continuity while a fresh claim is held (bypassable, see
    `_supervisor_gate`). This narrows the old "never refuses" only for a caller
    with a session id acting against a live supervisor -- a human at a plain
    shell (no sid) is unaffected, which is how init is run at setup."""
    _supervisor_gate("init", nonce=getattr(args, "nonce", None))
    force = getattr(args, "force", False)
    guard_problems = _home_guard_problems()
    if getattr(args, "autoclean", False) and guard_problems and not force:
        raise FleetCliError(
            "fleet init --autoclean refused before writing anything (N1): "
            + "; ".join(guard_problems)
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

    print(f"fleet init: wrote {instance_path}")
    print(f"  python:      {Path(sys.executable).resolve().as_posix()}")
    print(f"  fleet home:  {Path(FLEET_HOME).resolve().as_posix()}")

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
    _supervisor_gate("spawn", nonce=getattr(args, "nonce", None))
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
        _spawner = current_caller_session()
        record = new_worker_record(
            None, cwd, task, args.mode, model=args.model,
            setting_sources=args.setting_sources, token_ceiling=args.token_ceiling,
            spawned_by=_spawner,
            # §6.2: stamp the spawning claim's lineage so a later body of it
            # keeps ownership across a sid rotation. Under the lock we already
            # hold; read-only, never raises.
            spawned_by_lineage=_spawning_claim_lineage(_spawner),
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
                    # n2: DERIVED, not captured -- the dispatch raised before
                    # any `--bg` stdout could be read, so this is a string
                    # split of the sid, not the CLI's own id. See the
                    # `native_short_id` schema comment.
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

def _cmd_send_native(name: str, message: str,
                     run=subprocess.run, which=shutil.which, sleep=time.sleep) -> int:
    """`cmd_send`'s engine -- fork-steer per RATIFIED G2(b), M-B Task 7.

    Roster fetched ONCE, outside any lock (F4 doctrine), then the verdict
    (`recompute_worker_native`) is (re)computed under a single fresh lock --
    the record is re-read here rather than trusting the caller's snapshot,
    since an unbounded amount of time may have passed since it was taken.

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
    already requires the instance.

    §7 THE GATE: `send` is the incident-1 verb -- a divergent supervisor body
    dispatching workers -- so it is the gate's headline case (bypassable, see
    `_supervisor_gate`)."""
    _supervisor_gate("send", nonce=getattr(args, "nonce", None))
    _require_instance_settings()

    message = _read_task_arg(args.message)

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
    this command is the one lever that actually relaunches.

    §7 THE GATE: a mutating lifecycle verb (it relaunches turns), gated for a
    supervisor-shaped caller while a fresh claim is held."""
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
    silent overwrite.

    §7 THE GATE: a mutating lifecycle verb, gated for a supervisor-shaped
    caller while a fresh claim is held (bypassable, see `_supervisor_gate`)."""
    _supervisor_gate("interrupt", nonce=getattr(args, "nonce", None))
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
    clearing attached_since; a friendly no-op warning if not attached.

    §7 THE GATE: `release` is one of the two registry-mutating verbs v1's
    partition missed; it is a mutating lifecycle verb and is gated for a
    supervisor-shaped caller while a fresh claim is held."""
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
    # §6.2: provenance is carried across respawn exactly as `spawned_by` is --
    # a respawn is not a new spawn and must not launder ownership onto the
    # respawning body (TestRespawnDoesNotLaunderOwnership).
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
                    # n2: DERIVED, not captured -- same as cmd_spawn's
                    # fast-completion block. See the `native_short_id` schema
                    # comment.
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
    tombstone, fast-completion race, carried-forward fields).

    §7 THE GATE: a mutating lifecycle verb (it retires a session and launches a
    fresh one), gated for a supervisor-shaped caller while a fresh claim is
    held. Ahead of the destructive-guard prompt: the gate is the outer policy,
    the ownership prompt the inner one."""
    _supervisor_gate("respawn", nonce=getattr(args, "nonce", None))
    _require_instance_settings()

    # §5.1: respawn retires the old session id. Ask before doing that to a
    # worker this session did not spawn. Reads the registry WITHOUT the lock
    # (a lock-free read, like `status --stale-ok`) and prompts outside it: a
    # prompt must never block the fleet.
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
    # M5 fix wave: classify, so an already-gone sid reads as success rather
    # than "could not verify". `stop_outcome` is reported verbatim below.
    #
    # ND-1 fix wave (re-review MD-CONTRACT-REVIEW-2026-07-17.md): pass the id
    # fleet CAPTURED from `--bg` stdout, never a derived one. The M5 commit gave
    # `stop` the inference "gone == success" and the m1 commit taught `rm` never
    # to trust a derived ref for exactly that inference -- but it hardened both
    # rm call sites and NEITHER stop site, in the same commit. Repro'd: with a
    # CLI that answers only to its own short id, `fleet kill` derived
    # sid.split("-")[0], got `No job matching` -> `gone` -> success, printed
    # "w1: killed", exited 0, stamped interrupt_outcome=True and marked the
    # worker dead -- WHILE THE SESSION KEPT RUNNING. Fleet then forgets a live
    # bg session that every husk sweep skips forever (status/pid-live): the
    # rogue-session class `_cleanup_wedged` calls a C1 CRITICAL, reached through
    # the front door. Worse, the pre-M5 code was fail-SAFE on this input (rc=1,
    # "investigate manually"), so that wave removed the only signal that would
    # have caught the true case.
    #
    # Caveat, recorded honestly: `native_short_id` is itself derived on 2 of its
    # 6 write paths (the fast-sid paths), so this is a strict improvement on the
    # 4 paths that capture it from `--bg` stdout and a no-op on the other 2 --
    # not a cure. Retired sids have no `native_short_id` at all and keep the
    # derived fallback by design; that is what `_native_job_ref` is for.
    stop_outcome = "no-sid"
    if sid:
        captured_ref = rec.get("native_short_id")
        stopped_ok, stop_outcome = _stop_native_session_status(
            sid, run=run, which=which,
            ref=captured_ref if isinstance(captured_ref, str) and captured_ref
            else None)
    else:
        stopped_ok = True
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
        _ok, outcome = _stop_native_session_status(
            retired, run=run, which=which,
            timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
        # M5: was `'ok' if ok else 'timeout'` -- which named a mechanism that
        # usually did not occur. A retired sid is an abandoned fork, so
        # "already gone" is the COMMON case, and it printed "timeout": a
        # specific, wrong diagnosis inviting a hunt for a hung daemon. Print
        # what actually happened.
        print(f"fleet: {name}: stopping retired session {retired[:8]}... "
              f"{outcome}", file=sys.stderr)
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
        # M5: reached only when the stop genuinely could not be verified --
        # an already-gone sid ("gone") is now success, so `fleet kill` no
        # longer exits 1 telling the operator to investigate a session that
        # is verifiably, correctly gone.
        print(
            f"fleet: {name}: claude stop could not be verified ({stop_outcome}) "
            "-- marked dead anyway (kill is a terminal action); investigate "
            "the session manually",
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
    would race the in-flight dispatch's own commit.

    §7 THE GATE: a mutating lifecycle verb, gated for a supervisor-shaped
    caller while a fresh claim is held -- ahead of the destructive-ownership
    prompt (the gate is the outer policy)."""
    _supervisor_gate("kill", nonce=getattr(args, "nonce", None))
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
                         assume_yes=getattr(args, "yes", False), nonce=getattr(args, "nonce", None))

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
    nothing else touched. Default remains both.

    §7 THE GATE: a mutating lifecycle verb (irreversible deletion), gated for a
    supervisor-shaped caller while a fresh claim is held."""
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
        # m1: hand rm the CLI's OWN id from the roster entry rather than a
        # string-split guess -- a rejected ref would report "No job matching",
        # which this wave now reads as success.
        entry_ref = entry.get("id") if isinstance(entry, dict) else None
        ok, outcome = _rm_native_session_status(
            s, run=run, which=which,
            ref=entry_ref if isinstance(entry_ref, str) and entry_ref else None)
        if ok:
            # 2.1.212 contract change [PENDING-RATIFICATION]: "gone" (rc=1
            # "No job matching") is success -- the sid is off the roster,
            # which is all this phase wanted. Evidence: findings §Q3.
            print(f"fleet: {n}: rm {s[:8]}... {outcome}", file=sys.stderr)
            continue
        # Non-fatal by design (the tombstone is already committed): name WHY,
        # so a retryable dead-daemon skip is not read as a broken archive. The
        # husk stays on the roster and the autoclean husk tier retries it.
        print(f"fleet: {n}: rm {s[:8]}... {_rm_deferred_line(outcome)} -- "
              f"{_rm_outcome_note(outcome)}", file=sys.stderr)


def _native_job_ref(sid: str) -> str:
    """T12 fix wave (finding 2): `claude stop`/`claude rm` require the SHORT
    id, not the full `session_id` fleet stores/passes everywhere -- empirically
    confirmed 2/2 (`claude stop <full-uuid>` -> "No job matching", the same
    call with the 8-char short id -> success). Every observed short id is the
    first hyphen-delimited segment of the full sid, so derive it uniformly
    here rather than special-casing callers that do/don't have a stored
    `native_short_id` (retired sids have none).

    STALE as stated (ND-1 fix wave, re-review MD-CONTRACT-REVIEW-2026-07-17.md):
    "derive it uniformly rather than special-casing callers" was a sound
    T12-era call, but 2.1.212 made `gone` (rc=1 `No job matching`) mean SUCCESS
    -- so a ref the CLI merely rejects is now indistinguishable from a session
    that is really gone, and deriving it became fail-unsafe. Callers that hold
    the CLI's own id (roster entry `id`, or the captured `native_short_id`)
    now pass it via `ref=` and this function is their FALLBACK, not their
    source of truth. Retired sids still have none, so they still land here --
    which remains correct, since nothing better exists for them."""
    return sid.split("-", 1)[0] if sid else sid


# 2.1.212 contract change [PENDING-RATIFICATION]. Evidence:
# docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md §Q3. `claude rm`'s exit
# code is THREE-WAY AMBIGUOUS -- rc=1 means already-gone, dead-daemon, or a
# real failure, and only the message tells them apart:
#   rc=0  "removed <id>"                                            -> ok
#   rc=1  "No job matching '<id>'"                                  -> gone
#   rc=1  "couldn't remove <id> — the background service may be
#          restarting. Try again in a moment."                      -> transient
# `claude stop`'s gone-message carries an extra hint sentence ("Run 'claude
# agents' to list running sessions.") but the same leading phrase.
#
# PROVENANCE (M4/N2 fix wave, review MD-CONTRACT-REVIEW-2026-07-17.md): rows 1-2
# are live receipts (§Q3). Row 3 is a MANAGER REPORT, never re-observed -- the
# dead-daemon state is unreachable from a --bg session (§Q2) and two waves have
# now failed to reach it. Its exact bytes, rc and stream are unverified, which
# is exactly why `_NATIVE_CLI_TRANSIENT_RE` matches ONLY the dash-free middle
# phrase and never the punctuation around it. (This comment previously spelled
# that dash as an ASCII hyphen while every other copy used an em-dash -- three
# transcriptions, two dashes, which is what exposed the false "verbatim" claim.
# Em-dash everywhere now, on the understanding that it is a transcription
# choice, not evidence.)
_NATIVE_CLI_GONE_RE = re.compile(r"no job matching", re.I)
_NATIVE_CLI_TRANSIENT_RE = re.compile(r"background service may be restarting", re.I)

# M-E (2026-07-21 substrate outage, docs/specs/native-substrate.md "the
# daemon.lock PID-reuse wedge"). A `--bg` dispatch that dies with the
# unreachable-service shape is NOT a per-worker hiccup: it means the daemon
# could not be started at all, so every dispatch on the machine is down. The
# live stderr, captured verbatim by the manager at 2.1.216:
#
#   Starting background service
#   Couldn't reach the background service (background service did not become
#   reachable within 45s) - run 'claude daemon status'
#
# Two independent halves are matched, either alone sufficient: the vendor may
# reword the wrapper sentence or change the 45s timeout, and a diagnosis that
# survives only the exact bytes is a diagnosis that expires. `Starting
# background service` is deliberately NOT matched -- it is printed on healthy
# dispatches too, so it is a prefix, not a symptom.
_NATIVE_BG_UNREACHABLE_RE = re.compile(
    r"couldn't reach the background service"
    r"|background service did not become reachable", re.I)

# Shared by the dispatch classifier above and _doctor_check_daemon_wedge --
# one remedy text, so the two surfaces can never drift apart. The `stop --any`
# sentence is a receipt, not a guess (manager, 2026-07-21: it printed `no daemon
# running` and left the lock in place).
#
# F4 fix wave (review ME-DAEMON-REVIEW-2026-07-21.md): this text now opens with
# a PRECONDITION, and that is the most important edit in it. It is the only
# output in this feature that instructs a destructive, manual, irreversible-
# without-backup action, and the signal that reaches it is not proof: the
# dispatch classifier fires on `background service did not become reachable`,
# which is a TIMEOUT -- a loaded machine, an AV scan of claude.exe, or a slow
# binary-upgrade self-restart produce the same bytes while a HEALTHY daemon owns
# the lock (reasoned, not observed: both logged self-restarts completed in ~1.2s,
# 37x under the 45s timeout). Removing a live daemon's singleton lock destroys
# the singleton guarantee -- the next start sees no lock and takes a fresh one.
# So: confirm the holder is dead FIRST, and say plainly that a live daemon means
# the lock is not stale.
#
# F3 fix wave (same review): the Windows line was cmd.exe syntax (`&&`, `%VAR%`)
# while this project's documented primary Windows shell is PowerShell 5.1, in
# which it is a hard parse error ("The token '&&' is not a valid statement
# separator in this version") plus a literal, unexpanded `%USERPROFILE%`. An
# operator following the old remedy got a parse error while dispatch was down
# machine-wide. PowerShell is now the labelled Windows form; the cmd.exe form is
# kept and labelled as such rather than dropped.
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
    """"ok" | "gone" | "daemon-transient" | "failed" for a finished `claude
    rm`/`claude stop` subprocess.

    "gone" is a SUCCESS-EQUIVALENT: the sid already reached the end state the
    caller wanted. G12 recorded rm as idempotent on an already-gone id; at
    2.1.212 that is refuted in FORM (rc=1, not rc=0) though not in EFFECT --
    hence classify-by-message rather than by exit code.

    "daemon-transient" is checked FIRST and deliberately wins a tie: the
    daemon is transient (it idle-exits once no worker or client holds it
    open, findings §Q4), so a retryable failure must never be downgraded to
    "already clean" -- that would silently claim success for a husk that is
    still on the roster."""
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
    """(ok, outcome) for `claude rm <sid>` -- the archival primitive (G12):
    removes the roster entry and its backing `~/.claude/jobs/<short-id>/` dir.
    `outcome` is a `_classify_native_cli_result` verdict, plus "no-claude" /
    "error" for the two never-ran cases; `ok` is True for "ok" and "gone".

    Never raises: an unresolvable `claude` executable or any subprocess error
    both resolve to (False, ...), exactly like `_stop_native_session` -- every
    caller treats rm as best-effort/non-fatal and reports the outcome.

    T12 fix wave (finding 2): `claude rm` requires the SHORT id -- converts via
    `_native_job_ref` first; on an UNCLASSIFIED nonzero exit, retries once with
    the full sid (belt-and-braces against a future CLI accepting full ids).
    2.1.212 [PENDING-RATIFICATION]: the two message-classified outcomes
    short-circuit that retry. §Q3 confirms the full-uuid call returns the same
    `No job matching` -- that half is a receipt. The transient short-circuit is
    REASONING, NOT A RECEIPT (m5 fix wave): a daemon that cannot answer cannot
    discriminate refs, but the dead-daemon state is unreachable from a --bg
    session (§Q2), so it is untested.

    `ref` (m1 fix wave, review MD-CONTRACT-REVIEW-2026-07-17.md) overrides the
    DERIVED short id with one the caller read from the roster entry itself
    (the CLI's own `id` field). This is the one direction in which classifying
    `gone` as success could fail UNSAFE: the `gone` inference ("the sid already
    reached the desired end state") is sound only if the ref was right, and
    `_native_job_ref` derives it by string-splitting rather than reading it. If
    a future CLI stopped accepting the bare 8-char prefix, a rejected ref would
    report `No job matching` -> `gone` -> a `husk_removed` event for a husk
    that is still there. Callers holding the entry pass its `id`, so the
    verdict rests on the CLI's own identifier and the short-circuit stays
    honest; the derived ref remains the fallback for callers that have only a
    sid (a retired fork, a tombstone)."""
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
    """Bool face of `_rm_native_session_status` for callers that only need
    "is the sid off the roster now?" -- True for both a fresh removal and an
    already-gone id."""
    ok, _outcome = _rm_native_session_status(sid, run=run, which=which,
                                             timeout=timeout)
    return ok


# ND-2 (re-review MD-CONTRACT-REVIEW-2026-07-17.md): the deferral line's shape
# is a CONTRACT, not an implementation detail -- tests/integration/
# test_native_pin.py branches on it to tell a dead-daemon skip from a real
# contract regression. Renaming it silently would leave the pin passing until
# the next live run against a dead daemon. Both sides import this.
NATIVE_RM_DEFERRED_PREFIX = "deferred"


def _rm_deferred_line(outcome: str) -> str:
    """The operator-facing deferral fragment, in one place (ND-2)."""
    return f"{NATIVE_RM_DEFERRED_PREFIX} ({outcome})"


def _rm_outcome_note(outcome: str) -> str:
    """Operator-facing gloss for a non-success `_rm_native_session_status`
    outcome -- the difference between "retry will fix this" and "look at
    this" (findings §Q2: fleet's hygiene tier is the code path most likely
    to meet a dead daemon and the least able to revive it -- only a dispatch
    revives it, and no hygiene pass may mint a billable session as a side
    effect)."""
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
    concept).

    §7 THE GATE: a mutating lifecycle verb, gated for a supervisor-shaped
    caller while a fresh claim is held. `--dry-run` mutates nothing, but the
    gate is a policy on the CALLER, not on the effect, so it applies uniformly
    (a divergent body previewing is still a divergent body); the bypass is the
    same `--nonce` / no-session route."""
    _supervisor_gate("archive", nonce=getattr(args, "nonce", None))
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
# ND-3 (re-review MD-CONTRACT-REVIEW-2026-07-17.md): how many CONSECUTIVE
# husk-deferring autoclean runs before doctor calls it starvation rather than
# routine. A single deferral is the normal case at 2.1.212 -- the daemon is
# transient and this tier is the one most likely to meet it dead (§Q2) -- so
# noting the first one is cry-wolf. The scheduled task's floor is hourly
# (`--autoclean-interval-hours` is 1..23), so 3 in a row is >=3h of an
# unreachable daemon: long past any idle-exit, and short enough that a genuinely
# broken daemon surfaces the same day.
AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD = 3


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


def _sweep_husks(dry_run: bool, run=subprocess.run, which=shutil.which) -> tuple:
    """Tier 2 (autoclean.md D2): `claude rm` roster sessions fleet owns but
    no longer tracks live. Default-deny: a sid absent from every fleet
    record -- foremost the operator's own interactive sessions -- is never
    selected. Returns `(removed, deferred)`; raises FleetCliError when
    the roster is unavailable/suspicious (the caller isolates tiers).

    M1 fix wave (review MD-CONTRACT-REVIEW-2026-07-17.md): `deferred` used
    to be a local that died at the return, so a dead-daemon-starved sweep
    was byte-identical to a clean one at every durable surface (stamp,
    `autoclean_run` event, exit code) -- and the scheduled task is headless,
    so the stderr roll-up went to a console nobody owns. A permanently dead
    daemon could starve this tier for weeks while `fleet doctor` read
    green-and-fresh. The reviewer proved the gap by deleting the roll-up
    with the full suite still green. Deferred sids now reach the caller.

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
        # m1: the sweep read this entry from the roster -- use the CLI's own
        # `id` rather than a derived one, so a "gone" verdict (which becomes a
        # durable husk_removed event) can never rest on a ref the CLI rejected.
        entry_ref = entry.get("id")
        ok, outcome = _rm_native_session_status(
            sid, run=run, which=which,
            ref=entry_ref if isinstance(entry_ref, str) and entry_ref else None)
        if ok:
            # 2.1.212 [PENDING-RATIFICATION]: "gone" means the roster snapshot
            # this sweep read was merely stale -- the husk IS off the roster,
            # so it counts as removed rather than crying wolf every run
            # (findings §Q3: rm is not idempotent in FORM, only in EFFECT).
            append_event("husk_removed", display, session_id=sid)
            print(f"husk: rm {sid} ({display}) [{outcome}]")
            removed.append(sid)
        else:
            deferred.append(sid)
            print(f"husk: rm {sid} ({display}) {_rm_deferred_line(outcome)} -- "
                  f"{_rm_outcome_note(outcome)}", file=sys.stderr)
    if deferred:
        # Loud, non-fatal, and honest about the retry. The stderr line alone is
        # NOT enough (M1): it is invisible to the headless scheduled task, so
        # `deferred` is returned to the caller, which carries it into the run
        # stamp and the autoclean_run event -- the surfaces doctor reads.
        print(f"husk: {len(deferred)} husk(s) left on the roster for the next "
              f"pass: {', '.join(s[:8] for s in deferred)}", file=sys.stderr)
    return removed, deferred


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

    husks, husks_deferred = [], []
    try:
        husks, husks_deferred = _sweep_husks(dry_run, run=run, which=which)
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

    # M1: `husks_deferred` rides the stamp, the event and the summary line so a
    # starved sweep is distinguishable from a clean one. It deliberately does
    # NOT join `errors` -- that would flip rc to 1 and turn a routine transient
    # daemon state red, which is exactly the cry-wolf this branch set out to
    # kill. Deferral is a note, not a failure; doctor is where it surfaces.
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


def _home_guard_problems() -> list:
    """N1: the home-guard subset that protects state OUTLIVING this shell --
    now exactly one condition, the resolved home being a linked git worktree.
    A scheduled task pinned at a worktree keeps running after `git worktree
    remove` deletes the tree out from under it.

    Used by `_install_autoclean_task` (which adds its own script-location
    check on top) and by `cmd_init --autoclean`, which must evaluate it
    BEFORE writing anything. Deliberately EXCLUDES the script check: a
    sandboxed or relocated home with no `.git` file is a legitimate target.

    Was `_marker_guard_problems` and carried a second condition -- an existing
    `~/.claude/fleet-home` marker pointing elsewhere. Both the marker and that
    check were removed on 2026-07-22 with their only reader (see the note
    where the marker helpers used to live, above)."""
    home = Path(FLEET_HOME).resolve()
    problems = []
    if (home / ".git").is_file():
        problems.append(f"{home} is a linked git worktree (.git is a file) -- "
                        "a task pinned here dies with the worktree")
    return problems


# A scheduled task's command line, as it comes back from the platform
# adapter: `"<py>" "<script>" <verb> --fleet-home "<home>"`. Quoted runs are
# single tokens (paths contain spaces); everything else splits on whitespace.
# `--flag="quoted value"` is one token too, split on the `=` afterwards.
# Platform-neutral by construction -- it only ever sees a string.
_TASK_ARG_RE = re.compile(r'[^\s"]*"[^"]*"|\S+')


def _normalize_task_token(value) -> str:
    """Normalize one scheduled-task command-line token for comparison, under
    the running filesystem's own path-equality rules.

    Two of the three normalizations are PLATFORM-DECLARED, not universal
    (D8, closed by the posix-port campaign -- previously applied
    unconditionally and filed as a Phase-1.5 note while the POSIX scheduler
    backend was still hypothetical):

      - case folding: correct on Windows (schtasks XML round-trips emit
        case-varied spellings of one path, and NTFS considers them the same
        file); a false MATCH on a case-sensitive filesystem, where
        `/opt/Fleet` and `/opt/fleet` are two different directories.
      - backslash-to-slash: correct on Windows (`\\` is the separator, and
        schtasks round-trips vary it against `/`); a false MATCH on POSIX,
        where `\\` is an ordinary filename character, so `/opt/my\\fleet`
        and `/opt/my/fleet` are two different directories.

    Both wrong directions are the DANGEROUS one. `_fleet_task_is_ours` is
    what decides whether a scheduled job belongs to this fleet and may
    therefore be replaced; a false MATCH means overwriting somebody else's
    job, where a false MISS costs one `--force`.

    The third normalization is universal and stays unconditional: strip a
    trailing separator (B2 -- a directory argument that round-trips through
    schtasks XML can pick one up). `/` is a separator on every platform;
    a trailing `\\` is stripped only where `\\` is a separator, which the
    branch above has already converted."""
    text = str(value).strip()
    if PLATFORM.task_paths_use_backslash_separator:
        text = text.replace("\\", "/")
    if PLATFORM.task_paths_are_case_insensitive:
        text = text.lower()
    return text.rstrip("/") or text


def _strip_task_quotes(raw: str) -> str:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _task_command_tokens(command: str) -> list:
    """Normalized tokens of a scheduled task's command line, quotes stripped.

    One token in, one token out -- this never SYNTHESIZES a token (G2). An
    earlier revision split `--flag=value` into two tokens here so that
    index-based lookup saw one shape either way; the cost was that
    `--exclude=--fleet-home <home>` manufactured a `--fleet-home` token the
    command never carried, and the ownership predicate read it as ours. A
    predicate that can be *fed* an argument it was never given is the same
    shape as the untested-parser defect that preceded it. The `=` spelling is
    resolved where it is consumed instead -- see `_task_flag_value`."""
    return [_normalize_task_token(_strip_task_quotes(raw))
            for raw in _TASK_ARG_RE.findall(command or "")]


def _task_flag_value(tokens: list, flag: str):
    """Value of `flag` in a tokenized task command, or None if absent.

    Accepts both spellings fleet's own argparse accepts: `--flag value` (two
    tokens) and `--flag=value` (one). Only a token that IS the flag, or that
    starts with `flag=`, can supply a value -- so no other argument's value can
    stand in for it. The `=` value is re-normalized after its quotes come off,
    because the enclosing token ended in a quote and so escaped the trailing-
    separator rule the first time through."""
    want = _normalize_task_token(flag)
    prefix = want + "="
    for i, tok in enumerate(tokens):
        if tok == want:
            return tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.startswith(prefix):
            return _normalize_task_token(_strip_task_quotes(tok[len(prefix):]))
    return None


def _fleet_task_is_ours(command: str, subcommand: str) -> bool:
    """F4 ownership, by FULL identity: the task runs OUR resolved fleet.py,
    with THIS subcommand, against THIS fleet home.

    The predicate used to match the script path alone, which made it say
    "ours" for every fleet-owned scheduled task regardless of verb or home --
    so the moment a second one exists (the three-tier adjudication's
    `fleet init --supervisor-beat` is the concrete near-term case),
    `fleet init --autoclean` would silently /Create /F over it. Latent while
    only one task exists; data loss the day a second lands.

    F4 doctrine is intact and tightened: matching is on whole, quote-stripped
    tokens, never a bare substring -- a foreign `C:/tools/autoclean.exe`
    task still refuses, and now so does a task that merely mentions the word
    somewhere. Slash/case normalization is kept (schtasks XML round-trips
    carry both variances). An absent `--fleet-home` is NOT ours: `fleet`
    embeds it in every task it installs (F2), so a command without one was
    installed by something else. (B11: that includes a task installed by a
    fleet build older than F2 -- it has no `--fleet-home` and is refused
    rather than overwritten. Safe direction, `--force` recovers, and the
    refusal message names all three identity components.)

    QUOTING (B1 fix wave). Accepted: every form fleet itself renders, either
    path quoted or bare, slash- or case-varied, and `--fleet-home=VALUE` (which
    fleet's own argparse accepts, so a hand-edited task may carry it).
    Refused, deliberately: a command whose paths contain spaces and carry NO
    quotes at all -- that is genuinely undecidable, not merely unhandled -- and
    sh-style single quotes. The POSIX scheduler backend now exists, so that
    refusal no longer rests on "no dialect to validate against"; it rests on
    what it always really meant. `_autoclean_task_command` renders DOUBLE
    quotes on both backends and cron stores that command field verbatim, so a
    single-quoted command is never one fleet wrote -- while `'` is a legal
    Windows filename character (`C:\\Users\\O'Brien\\...`) that a single-quote
    alternation would mis-tokenize. Both refusals are the SAFE direction: the cost is one
    `--force` on a task that is provably the operator's, where the opposite
    error is `/Create /F` over somebody else's scheduled task. Pinned by
    `TestOwnershipQuotingVariants`, which fixes each verdict as a decision.

    NOT constrained: the interpreter (argv[0]). A contrived command that runs
    a foreign wrapper but still names our fleet.py, the `autoclean` verb and
    our `--fleet-home` reads as ours (B7). Recorded so it is not re-filed as
    new; it is strictly narrower than the pre-fix substring predicate, and
    every realistic shape answers correctly.

    Portability (invariant 8): pure string work over a command string plus
    `Path(...).resolve()`, with the two filesystem-dependent path-equality
    rules DECLARED BY THE ADAPTER rather than assumed -- see
    `_normalize_task_token`. D8 (CLOSED, posix-port campaign): both
    normalizations used to be applied unconditionally, which on a
    case-sensitive filesystem made two genuinely different paths compare
    EQUAL. The old note here called `.lower()` a "false MISS" risk; it is
    the opposite, and a false MATCH is the dangerous direction for a
    predicate that licenses replacing a scheduled job.

    Reachable, not theoretical: the crontab backend finds fleet's line by a
    CONSTANT `# claude-fleet-autoclean` tag, so two fleet homes under one
    user account -- differing only in path case, or one carrying a literal
    backslash -- write same-tagged lines, and this predicate is the only
    thing stopping the second install from overwriting the first's job.
    Pinned end-to-end through the real crontab backend by
    `TestTaskPathSemanticsFollowTheFilesystem`, which drives both adapters
    on both operating systems."""
    tokens = _task_command_tokens(command)
    try:
        script_at = tokens.index(_normalize_task_token(_autoclean_script_path()))
    except ValueError:
        return False
    # The verb is the argument immediately after the script path -- fleet.py's
    # own parser takes the subcommand first, so anything else is a different
    # task even if the word appears later in the line.
    if tokens[script_at + 1:script_at + 2] != [_normalize_task_token(subcommand)]:
        return False
    home = _task_flag_value(tokens, "--fleet-home")
    return home is not None and home == _normalize_task_token(Path(FLEET_HOME).resolve())


def _autoclean_task_is_ours(command: str) -> bool:
    """F4 for the autoclean task specifically -- see `_fleet_task_is_ours`.
    Kept as a named seam so the sole consumer (`_install_autoclean_task`)
    reads the same as before and a second fleet task gets its own one-liner."""
    return _fleet_task_is_ours(command, "autoclean")


def _install_autoclean_task(interval_hours, force: bool) -> None:
    if interval_hours is None:
        interval_hours = AUTOCLEAN_INTERVAL_HOURS_DEFAULT
    interval_hours = int(interval_hours)
    if not 1 <= interval_hours <= 23:
        raise FleetCliError("--autoclean-interval-hours must be 1..23 (schtasks /SC HOURLY /MO)")

    # F2 home guards: a scheduled task outlives this shell -- refuse to pin
    # it to a fleet.py that is not the target home's own copy, or to a linked
    # git worktree (dies with the worktree). --force overrides both. A third
    # guard (a home contradicting the machine's fleet-home marker) went with
    # the marker on 2026-07-22.
    home = Path(FLEET_HOME).resolve()
    script = _autoclean_script_path()
    problems = []
    if script.parent.parent != home:
        problems.append(f"this fleet.py ({script}) is not the target home's copy ({home})")
    problems += _home_guard_problems()
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
            f"fleet-owned by THIS identity -- ownership is all three of: this "
            f"fleet.py ({_autoclean_script_path()}), the `autoclean` "
            f"subcommand, and --fleet-home {Path(FLEET_HOME).resolve()}. "
            f"Found {existing[:120]!r} -- rerun with --force to overwrite. "
            f"(A task installed by a fleet build older than F2 carries no "
            f"--fleet-home and lands here; --force is safe if the fleet.py "
            f"path above is yours.)")
    ok, msg = PLATFORM.autoclean_task_install(AUTOCLEAN_TASK_NAME, command, interval_hours)
    if not ok:
        raise FleetCliError(f"scheduler create failed: {msg}")
    print(f"fleet init: scheduled task {AUTOCLEAN_TASK_NAME!r} installed "
          f"(every {interval_hours}h)")
    print(f"  command:   {command}")
    print(f"  uninstall: fleet init --autoclean-remove")


def _remove_autoclean_task() -> None:
    ok, msg = PLATFORM.autoclean_task_remove(AUTOCLEAN_TASK_NAME)
    if not ok:
        raise FleetCliError(f"scheduler delete failed: {msg}")
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
# Every check that is explicitly "note-only"/"warn" (legacy settings
# file, orphaned/pending mailboxes, stale attaches, orphaned *.claimed.*
# files, fleet-unknown claude-agents sessions, limited parks, legacy-mix,
# dead-suspected, autoclean scheduler state) always returns ok=True -- it
# can inform, never turn
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
    """Advisory-only (always ok=True): a legacy (pre-pivot, `dispatch_kind`
    absent) record is unmanageable by this build -- the legacy dispatch/
    probe path it needs was deleted (pivot spec §6, M-C). Nothing enforces
    read-only; the truthful advice is retire-only (kill/clean/archive).
    Archived records are excluded even though they're also non-native,
    since they're already history and doctor's other archived-aware checks
    cover them."""
    legacy = sorted(name for name, rec in workers.items()
                    if not is_native(rec) and rec.get("archived_at") is None)
    if legacy:
        return ("legacy-mix", True,
                f"{len(legacy)} pre-pivot worker(s): {', '.join(legacy)} -- "
                "unmanageable by this build; kill/clean/archive only")
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


def _autoclean_deferral_streak() -> tuple:
    """(streak, husks_on_latest, since_ts): how many of the MOST RECENT
    consecutive `autoclean_run` events deferred at least one husk (ND-3).

    The run stamp holds exactly one pass, so it can never answer "is this
    persistent?" -- the question that separates a routine dead-daemon skip from
    a starved tier. `events.jsonl` is append-only history and carries
    `husks_deferred` since the M1 fix, so the streak is derived from there.

    Counts backwards from the newest event and stops at the first pass that
    deferred NOTHING, regardless of what came before. n3 (review
    MD-CONTRACT-REVIEW-2026-07-17.md) corrects the justification this line used
    to carry ("a single successful sweep means the daemon was reachable"): the
    reset rule is "deferred nothing", which ALSO fires on a nothing-to-do pass
    -- a pass that found no husks proves nothing about reachability. The rule is
    still the right one, for a weaker reason: what this streak measures is
    UNRECLAIMED WORK PILING UP, and a pass with nothing left to defer is not
    piling any up. Dry-run passes
    are skipped entirely: they never rm anything, so they neither prove nor
    disprove reachability. Any read/parse failure degrades to (0, 0, None) --
    doctor is note-only and must never fail on unreadable history."""
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


def _doctor_check_autoclean(run=subprocess.run):
    """Note-only (docs/specs/autoclean.md D4): reports scheduler-task state
    (installed/missing) and last-run staleness from the run stamp. Never
    turns doctor red -- a missing task is a choice, not broken plumbing.

    LOW advisory (confirmation pass): a fresh timestamp alone can lie --
    the stamp's `errors` array and a lingering fleet.json.corrupt.*
    artifact (which makes tier 2 refuse itself, NEW-1) both mean the sweep
    is NOT actually doing its job. Both are appended to whichever note is
    returned, so a bricked sweep never reads green-and-fresh.

    M1 fix wave (review MD-CONTRACT-REVIEW-2026-07-17.md): `husks_deferred`
    is the third such lie and the reason this check existed at all was
    defeated without it. A dead daemon defers every husk on every pass
    while raising nothing into `errors` -- so the stamp read
    `husks_removed=0, errors=[]`, identical to "nothing to do", and this
    check said "task installed; last run 0.3h ago" forever while the roster
    filled with husks. A deferring sweep is a bricked sweep and now says so.
    Still note-only: a transient daemon is normal, not broken plumbing.

    ND-3 fix wave (re-review MD-CONTRACT-REVIEW-2026-07-17.md): the M1 note
    fired on the FIRST deferral -- i.e. on the normal case. §Q2's own finding is
    that this tier is "the one code path most likely to meet a dead daemon", so
    on a quiet machine with hourly autoclean nearly every run defers, doctor
    carried the note nearly every invocation, an operator habituates in a week,
    and then the permanently-starved case M1 exists to surface renders
    IDENTICALLY -- the cry-wolf pattern this whole branch exists to kill. The
    old note even conceded it ("if this count persists across runs") while
    reading from a stamp that holds exactly one run and cannot show persistence.
    So: read the STREAK from `events.jsonl` (append-only history, which
    `husks_deferred` now rides) and note only AT or past
    `AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD` consecutive starved sweeps (n4: the
    code is `streak >= THRESHOLD`, so the note fires ON the 3rd, not after it).
    That is the sentence that distinguishes starvation from Tuesday.

    n3: the streak RESETS on any pass that deferred nothing -- which includes a
    nothing-to-do pass, and therefore is not by itself proof that the daemon was
    reachable. See `_autoclean_deferral_streak` for why that is still the right
    rule."""
    stamp_note, stale, run_errors = "no run recorded yet", False, []
    husks_deferred = 0
    try:
        raw = json.loads(autoclean_stamp_path().read_text(encoding="utf-8"))
        last = _parse_iso(raw.get("ts"))
        age_h = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        stamp_note = f"last run {age_h:.1f}h ago"
        stale = age_h > AUTOCLEAN_STALE_RUN_HOURS
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
    #
    # B6/D9: tokenize through `_task_command_tokens`, the same splitter the
    # ownership predicate uses. This scan previously required QUOTED tokens
    # (`re.findall(r'"([^"]+)"', existing)`), so an unquoted script path --
    # a shape a schtasks XML round-trip can produce, and one the predicate
    # accepts -- made the check silently no-op and doctor read green on a
    # task pinned to a deleted worktree. Two tokenizers over the same string
    # is exactly the drift this branch exists to remove. Note the tokens come
    # back slash/case-normalized; `Path.exists()` is fine with forward slashes
    # on Windows, and this check is note-only either way.
    # Only an ABSOLUTE token can be proven dead: a relative `fleet.py` resolves
    # against the scheduler's working directory, which is not ours to know, so
    # `Path(tok).exists()` would answer against the WRONG cwd. The old
    # quoted-only scan excluded those by accident (fleet always quotes an
    # absolute path); this makes the exclusion the stated rule, and keeps the
    # check to claims it can actually support.
    for tok in _task_command_tokens(existing):
        if (tok.endswith("fleet.py") and Path(tok).is_absolute()
                and not Path(tok).exists()):
            return ("autoclean", True,
                    f"task installed but pinned to a missing path ({tok}) -- "
                    f"reinstall from the canonical home: fleet init --autoclean{suffix}")
    if stale:
        return ("autoclean", True,
                f"task installed but {stamp_note} (> {AUTOCLEAN_STALE_RUN_HOURS:.0f}h) "
                f"-- scheduler may be stale{suffix}")
    return ("autoclean", True, f"task installed; {stamp_note}{suffix}")


def _doctor_check_tzdata():
    """D1 (MD-ULPARSER-REVIEW-2026-07-17.md §3): `zoneinfo` is stdlib but its
    DATA is not guaranteed on Windows -- there is no system tz database, so
    every named-zone lookup depends entirely on the `tzdata` pip package
    being importable. On the review's own host that only held **by
    coincidence** of an unrelated project's transitive dependency
    (`pandas`); a clean box, a venv, or that dependency going away all
    silently break it. Absent tz data, `_next_local_reset_utc` returns
    `None` for every lookup, so every LOCAL-format limit signal
    ("resets 4:40am (Asia/Qyzylorda)") null-parks instead of resolving --
    correctly conservative (never a guessed horizon), but previously
    invisible: nothing told an operator *why* parsing had gone quiet.

    PASS-note, never FAIL -- same doctrine as `_doctor_check_autoclean`
    (this check is placed right after it in the file: m7 nit,
    ME-UL-REVIEW-2026-07-21.md -- moved out of the supervisor-handoff
    worker's textual neighborhood to reduce merge friction; registration
    order in `cmd_doctor`'s `check_calls`, which controls print order and
    is what C1 pins, is unaffected by where the function is defined).
    Missing tz data does not break dispatch, spawn, or any daemon
    contract; it narrows limit-signal parsing back to horizons already in
    ISO-8601/UTC form (`_LIMIT_RESET_RE`), which need no tz lookup at all.
    Failing doctor over a parsing-precision gap would teach an operator to
    treat a cosmetic degradation as fleet-breaking, which it is not."""
    import zoneinfo
    try:
        zoneinfo.ZoneInfo("Asia/Qyzylorda")
    except Exception as exc:
        return ("tzdata", True,
                f"zoneinfo cannot resolve a named zone ({type(exc).__name__}: {exc}) -- "
                f"local-format limit-signal parsing (\"resets 4:40am (Zone/City)\") will "
                f"null-park until tz data is installed: py -3.13 -m pip install tzdata")
    return ("tzdata", True, "zoneinfo resolves named zones (tz data present)")

# --- M-E: wedged / unreachable background daemon ---------------------------
#
# The 2026-07-21 outage this exists for: `--bg` dispatch was dead machine-wide
# for ~16h and `fleet doctor` reported 21 PASS / 0 FAIL. Full receipts in
# docs/specs/native-substrate.md (Known hazards, "the daemon.lock PID-reuse
# wedge").
#
# VENDOR SURFACE THIS DEPENDS ON (both will drift; both fail SAFE when they do):
#   1. `~/.claude/daemon.lock` -- a JSON object with an integer `pid` and a
#      numeric `startedAt` in epoch MILLISECONDS, UTC.
#   2. `~/.claude/daemon.log` -- one record per line, prefixed
#      `[<ISO-8601>Z] `, carrying the literal supervisor line
#      `another daemon won the lock race (pid=<N>) — exiting`.
# Nothing else is read, and no subprocess is run at all.
#
# TIME BASE (named deliberately -- fleet has been burned by mixed bases before):
# BOTH quantities compared here are WALL-CLOCK UTC. `startedAt` is epoch-millis
# UTC (verified arithmetically against the incident capture: 1784589928352 ->
# 2026-07-20T23:25:28.352Z, 0.6s after that lock's own `daemon start` log line
# at 23:25:27.750Z), and the log stamps are ISO-8601 with an explicit `Z`. No
# monotonic, boot-relative or process-relative quantity enters the comparison.
# The lock's `procStart` field is a THIRD base -- .NET ticks in LOCAL time
# (639202047274516770 -> 2026-07-21T04:25:27 local = 23:25:27Z at UTC+5) -- and
# is deliberately never read.
_DAEMON_LOG_TS_RE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)Z\]")
_DAEMON_LOCK_RACE_RE = re.compile(
    r"another daemon won the lock race \(pid=(\d+)\)", re.I)

# M1 fix wave (review ME-DAEMON-REVIEW-2026-07-21.md §M1). THE AGE GATE IS THE
# DISCRIMINATOR; the other two are secondary. The original rule (>=3 refusals
# spanning >=300s) could not fire on the incident it was built from, and no
# threshold VALUE fixes that, because the instrument was wrong: refusal lines are
# DEMAND-DRIVEN, minted one per attempted dispatch, never by the passage of time.
# The 16h outage produced exactly ONE refusal, and the whole interval in which
# more could accumulate -- first failed dispatch 15:07:01.868Z to the operator's
# remedy at 15:09:42.909Z -- was 161 seconds. A wedge on a quiet machine emits
# zero. Requiring three over five minutes required the operator to diagnose the
# outage before the check would speak.
#
# Calibration, on all four lock-race refusals in the machine's real daemon.log
# (2026-07-14 -> 2026-07-21); "age" is the refusal's distance from the lock its
# named winner wrote, derived via the one directly-observed coupling (pid 15740:
# `daemon start` 23:25:27.750Z vs `startedAt` 23:25:28.352Z = +0.602s):
#
#   refusal ts                  names pid   winner daemon start        age
#   2026-07-14T01:15:07.492Z        28232   2026-07-14T01:15:06.243Z   0.647s  benign
#   2026-07-14T06:49:12.297Z        47240   2026-07-14T06:49:11.163Z   0.532s  benign
#   2026-07-17T00:35:28.269Z        39900   2026-07-17T00:35:27.217Z   0.450s  benign
#   2026-07-21T15:07:01.868Z        15740   2026-07-20T23:25:27.750Z  56493.5s THE WEDGE
#
# 0.647s vs 56 493.5s -- 4.9 orders of magnitude. 300.0 sits 464x above the
# largest benign sample and 0.5% of the way to the wedge. There is no
# false-positive pressure for the count/span gates to defend against: the benign
# races were never at risk of counting, because each names a winner that wrote
# the lock milliseconds earlier. So one late refusal is enough.
DAEMON_WEDGE_MIN_REFUSALS = 1
DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS = 300.0
# ND-1: consumed by the F6 DEGRADED path ONLY (_daemon_wedge_degraded_verdict),
# where `startedAt` is unusable so no age gate can run and this is the only
# discriminator left. It is deliberately NOT consulted on the primary path: there
# it made adding evidence weaken the verdict (1 refusal FAIL, 2 refusals 29s
# apart PASS), i.e. the verdict tracked the operator's retry cadence instead of
# the evidence. Full table and reasoning at the primary path's own comment.
DAEMON_WEDGE_MIN_SPAN_SECONDS = 300.0


def _parse_daemon_log_ts(line: str):
    """UTC datetime for a `[2026-07-21T15:07:01.868Z] ...` daemon.log line, or
    None if the line carries no parseable stamp.

    `strptime`, NOT `fromisoformat`: under the 3.10 floor `fromisoformat`
    rejects the trailing `Z` outright while 3.11+ accepts it (M-D shipped a bug
    of exactly this shape), and a parser whose verdict depends on which
    interpreter ran it is not a parser. The fractional part is optional --
    2.1.216 emits milliseconds, and a build that stops doing so must not turn
    every line into an unparseable one."""
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
    """FAIL iff `~/.claude/daemon.lock` is demonstrably STALE: repeated daemon
    starts, spread over time and long after the lock was written, were each
    refused by that same lock. That is a machine-wide dispatch outage -- fleet
    can spawn, respawn, steer and resume exactly nothing until it is cleared.

    SIGNAL CHOICE, and why the other candidates were rejected.
    Signals used: the lock's own (pid, startedAt), plus the supervisor's
    `another daemon won the lock race (pid=N) — exiting` lines. Two files, no
    subprocess. The discriminator is that a lock-race refusal only happens
    after a client concluded no daemon was REACHABLE and launched a supervisor
    -- when a healthy daemon is reachable, clients connect and no start is
    attempted at all. So a refusal is already evidence of unreachability; the
    ONE gate that turns it into a verdict is its AGE relative to the lock it was
    refused by:
      * >= DAEMON_WEDGE_MIN_LOCK_AGE_SECONDS after `startedAt`. A genuine
        startup race resolves in under a second (the loser's line lands
        milliseconds after the winner wrote the lock); a wedge's refusal is
        hours old. Measured on all four real refusals in this machine's log:
        0.647 / 0.532 / 0.450 s benign vs 56 493.5 s for the wedge. The
        comparison is SIGNED, deliberately: a refusal dated BEFORE the current
        lock was written is history from a previous lock and must never indict
        this one (an absolute comparison would break the same self-clearing
        property the pid match provides).
      * >= DAEMON_WEDGE_MIN_REFUSALS (= 1) of them. See the constant: refusals
        are demand-driven, so requiring several requires the operator to fail
        several dispatches first, and the real incident only ever produced one.
      * and NOTHING ELSE. There is no span/burst gate on this path (ND-1): one
        used to sit here and it made adding evidence weaken the verdict -- one
        refusal FAILed, two 29s apart PASSed. A rule whose answer depends on how
        fast the operator retried is not reading the evidence. The age gate
        needs no help; DAEMON_WEDGE_MIN_SPAN_SECONDS survives for the F6
        degraded path alone.
    Refusals naming a pid other than the lock's current holder are ignored, so
    the check self-clears the moment an operator replaces the lock.

    THE PROACTIVE GAP, stated rather than papered over (review
    ME-DAEMON-REVIEW-2026-07-21.md §M1.c). Refusal lines are minted per
    ATTEMPTED DISPATCH. A wedge on a machine where nobody has dispatched yet
    emits zero of them, and this check is silent -- which is exactly the row a
    `fleet doctor` run BEFORE dispatching would want. One dispatch attempt is
    enough to make it speak (that is what MIN_REFUSALS=1 buys), and the
    dispatch classifier itself covers the operator who did attempt one; but a
    genuinely proactive detector needs a signal the vendor writes without being
    asked. `~/.claude/daemon.status.json` is the promising candidate -- on the
    live healthy machine it carries `supervisorPid` matching `daemon.lock.pid`
    and a `writtenAt` 413 ms after the lock's `startedAt` -- but whether the
    supervisor REWRITES it while running, and what it held during the wedge,
    are both unobserved. [MANAGER-VERIFICATION REQUIRED] capture
    `daemon.status.json` and `daemon/roster.json` alongside `daemon.lock` at
    the next wedge. Nothing here is built on those files until then: building
    on unverified vendor-file semantics is the failure this check was already
    caught committing once.
    `~/.claude/daemon/roster.json` mtime is NOT a candidate and was refuted on
    this machine's own data: it is event-driven, not a heartbeat, and during
    this very incident it was already 1.59 h stale while the daemon was
    provably healthy (roster written ~02:20:59Z; daemon proven alive by an auth
    refresh at 03:56:41Z). Any threshold tight enough to catch a wedge fires on
    a healthy quiet machine.

    (a) `claude daemon status` REJECTED. It is the most direct signal and it is
    what the vendor tells you to run, but the hard constraint here is that a
    probe must never START a daemon -- the vendor's own warning says `claude
    agents` does -- and `daemon status`'s side-effect freedom IN THE
    DEAD-DAEMON STATE cannot be verified from a `--bg` session, which is by
    construction always holding a live daemon open (native-substrate.md, Known
    hazards). Unverifiable means not called. A check that shells out to nothing
    cannot start anything; that is the entire argument.
    [MANAGER-VERIFICATION REQUIRED] if `daemon status` is ever confirmed
    side-effect free on a dead daemon from an interactive session, it becomes
    the better primary signal and this check should be revisited.

    (d) PID-liveness / `procStart` comparison REJECTED, and the incident is the
    reason: Windows recycled the dead daemon's pid onto `WacomHost`, a service
    whose StartTime is unreadable to a normal-token probe. An unreadable start
    time is INDETERMINATE and must never be read as "matches / still ours" --
    so on the one case this check exists for, (d) returns "don't know" and
    decides nothing. It also has no implementation to lean on: `probe_liveness`
    / `get_process_info` / `boot_identity` were all deleted in the section-6
    pivot (grep receipt, `bin/fleet.py` @ac3e34d: zero matches), so it would
    mean a new PLATFORM adapter method with no POSIX backend.

    FAIL DIRECTION -- chosen deliberately, and it is CONSERVATIVE. Doctor is
    read every session, so a false FAIL is worse than a missed wedge. Every
    unknown is a PASS-note: absent lock, unreadable/non-JSON lock, a lock with
    no usable `pid`, absent or unreadable log, refusal lines fleet cannot date,
    and refusals that are not late. The residual cost is the proactive gap
    above, not lateness: once a single dispatch has been attempted the check
    speaks.

    F6 fix wave (same review): an unusable/out-of-range `startedAt` no longer
    discards the evidence. The refusals naming this lock's pid are still fully
    readable and still probative -- only the age gate cannot run -- so a
    one-key field drift used to retire the check permanently. Without a usable
    `startedAt` the check falls back to LOG-ONLY evidence: >= 2 refusals naming
    the lock's pid, spanning >= DAEMON_WEDGE_MIN_SPAN_SECONDS. Two refusals
    against the same lock five minutes apart cannot be a startup race, which is
    sub-second. The message says the confidence is degraded and why.
    Deliberately NOT implemented, and this is a scope call: the review also
    suggested requiring "no intervening supervisor line indicating that pid was
    serving". That needs semantics for vendor log lines nobody has catalogued,
    which is the same unverified-vendor-surface move M1 charged. Recorded here
    instead of guessed at.

    NEVER MUTATES anything under `~/.claude` -- two reads, and it prints the
    remedy. Pinned by test_check_mutates_nothing.

    PORTABILITY (SPEC.md v3 invariant 8): pure `Path.home()` + `Path.read_text`
    + `re`, so it resolves identically on Windows, macOS and Linux and carries
    no platform branch. [UNVERIFIED -- no POSIX box] the POSIX daemon.log line
    format and lock filename were not observed; if either differs, this check
    finds no refusals and returns a PASS-note, which is the intended failure
    direction."""
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
    # `isinstance(True, int)` is True in Python and `1 == True`, so without the
    # bool guard a lock carrying `"pid": true` would attribute every refusal
    # naming pid 1 to it. Pinned by a `pid=1` refusal fixture -- a fixture
    # naming any other pid can never reach this guard.
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
        # F6: degraded, log-only. The age gate is unavailable, so the only
        # remaining discriminator is that two refusals against the SAME lock,
        # minutes apart, cannot be a startup race (which is sub-second).
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
    # ND-1 (final gate, review ME-DAEMON-REVIEW-2026-07-21.md): there is NO span
    # gate on this path, deliberately. It used to sit here, guarded at >= 2, and
    # it made ADDING EVIDENCE WEAKEN THE VERDICT:
    #
    #   1 late refusal (the REAL incident)            -> FAIL (detected)
    #   2 late refusals 29s apart (operator retried)  -> PASS (MISSED)
    #   2 late refusals 2min apart                    -> PASS (MISSED)
    #   2 late refusals 6min apart                    -> FAIL (detected)
    #   3 late refusals 30s apart                     -> PASS (MISSED)
    #
    # i.e. the verdict tracked the OPERATOR'S RETRY CADENCE, not the evidence --
    # and on the founding incident that is reachable, not exotic: the outage's
    # evidence window was 161s, so any second dispatch attempt inside it (a
    # retried `fleet spawn`, a sibling worktree, a plain interactive `claude`)
    # minted a second refusal and flipped FAIL to PASS. Seven worktrees were
    # live. The only reason the real log holds one refusal is that the operator
    # diagnosed it in under three minutes.
    #
    # The age gate does not need the help: it separates the wedge from every
    # real benign race by 4.9 orders of magnitude, and by this check's own model
    # a refusal only happens after a client found no daemon reachable -- so two
    # such events >= 300s after the lock was written mean the holder is not
    # serving, burst or not. Pinned both ways by
    # test_real_benign_races_pass_with_the_span_gate_disabled (all three real
    # races still PASS at MIN_SPAN=0) and by the cadence table above, now a test.
    # The span gate REMAINS in _daemon_wedge_degraded_verdict, where no age gate
    # exists and it is the only discriminator there is.
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
    """F6 fallback for a lock whose `startedAt` is missing, wrong-typed, NaN,
    infinite or out of epoch range: the age gate cannot run, but the refusals
    naming this lock's pid are still readable and still probative. Requires
    >= 2 of them spanning >= DAEMON_WEDGE_MIN_SPAN_SECONDS -- a startup race
    resolves sub-second, so two refusals against one lock minutes apart is not
    one. Confidence is lower than the primary path and the message says so."""
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
        functools.partial(_doctor_check_daemon_wedge),
        functools.partial(_doctor_check_autoclean, run=run),
        functools.partial(_doctor_check_hook_errors),
        functools.partial(_doctor_check_supervisor_claim),
        functools.partial(_doctor_check_supervisor_handoff),
        functools.partial(_doctor_check_tzdata),
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


def _atomic_append_bytes(path: Path, data: bytes) -> None:
    """Single-syscall atomic append; the guarantee is per-backend
    (FILE_APPEND_DATA-only handle on Windows, O_APPEND on POSIX -- see the
    PLATFORM adapter block, SPEC §14). Module-level name kept: callers and
    tests pin it, and the raise-OSError-on-partial-write contract is the
    adapter's, unchanged."""
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


def _stop_native_session_status(sid: str, run=subprocess.run, which=shutil.which,
                                timeout: int = 30, ref: str = None) -> tuple:
    """(ok, outcome) for `claude stop <sid>` (contract G10): the only
    sanctioned way to end a --bg-managed session -- a raw pid kill triggers a
    silent daemon respawn under the same sid (G10, never raw-kill).

    M5 fix wave (review MD-CONTRACT-REVIEW-2026-07-17.md): `stop` now shares
    `rm`'s 3-way message discriminator instead of classifying on exit code
    alone. `claude stop` against an already-gone id exits 1 with `No job
    matching '<id>'. Run 'claude agents' to list running sessions.` (live
    receipt, findings §Q3) -- the session is not running, which is precisely
    what the caller wanted, exactly as for `rm`. Reading that as failure made
    `fleet kill` on an already-gone sid exit 1 while telling the operator to
    "investigate the session manually" about a session that is verifiably
    gone, print a specific and WRONG "timeout" diagnosis for retired sids (the
    common case -- retired sids are abandoned forks), and stamp
    `interrupt_outcome=False` into the durable event log. Same cry-wolf this
    wave cured on `rm`, left standing on `stop`.

    `ok` is True for "ok" and "gone". Everything else stays False = COULD NOT
    VERIFY, which every caller already handles fail-safe (`cmd_respawn
    --force`/`_cleanup_wedged` re-check the roster before proceeding;
    `_cmd_kill_native` marks dead anyway -- kill is terminal -- and warns).

    T8 fix wave (adv I1): `timeout` defaults to 30s (the primary/current
    sid's budget) but `_cmd_kill_native`'s retired-sid sweep passes 5s --
    those stops are best-effort only and unbounded wall-time across a
    long-lived worker's whole retired_sids history is the actual defect
    being fixed, not the primary sid's own stop.

    T12 fix wave (finding 2): `claude stop` requires the SHORT id -- converts
    via `_native_job_ref` first; on an UNCLASSIFIED nonzero exit, retries once
    with the full sid (belt-and-braces against a future CLI accepting full
    ids). `ref` overrides the derived short id -- see
    `_rm_native_session_status` for why a caller holding the roster entry
    should pass the CLI's own `id` (m1)."""
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
# Native dispatch (M-B, spec §6): the choke point for every --bg WORKER
# launch (spawn / fork-steer / resume-limited / respawn). The supervisor
# successor is dispatched by cmd_sup_handoff_begin's own argv -- spec §6.1
# enumerates that second path and why it cannot route through here.
# Task-file bootstrap (G8), short-id capture + sid-prefix roster join (G6
# fallback), fresh -n render per dispatch (G13 / spec §5.1.3).
# --------------------------------------------------------------------------

NATIVE_JOIN_VERIFY_SECONDS = 60.0   # keep in sync with SUPERVISOR_ROSTER_VERIFY_SECONDS below (same window, independently defined -- Finding 3)
NATIVE_JOIN_POLL_SECONDS = 3.0
NATIVE_DISPATCH_TIMEOUT_SECONDS = 120.0
# Never-attach wedge (live finding #2, 2026-07-16): across 12 healthy probe
# spawns, status+pid appeared on the joined roster entry 4-6s post-dispatch
# (outcome ~10-15s); 30s is 5x that observed ceiling as loaded-daemon
# headroom. CALIBRATION, not proof (n=12, one machine, one day) -- which is
# why a wedge verdict is not trusted blindly: the cleanup path verifies the
# stop/rm outcome and re-checks the roster before any retry (C1), and a
# full-window fetch blackout aborts rather than verdicts (H1). An
# over-tight window costs one stopped-and-verified session + one
# redispatch; an over-generous one just delays wedge detection.
NATIVE_ATTACH_VERIFY_SECONDS = 30.0
NATIVE_ATTACH_POLL_SECONDS = 2.0
# M2: wedge-path stop/rm run with this short timeout instead of the default
# 30s -- the wedge path sits inside spawn latency budgets (callers' outer
# timeouts, the pin suite's SPAWN_TIMEOUT); three stacked 30s subprocess
# stalls would turn a slow-daemon day into a blown harness rather than a
# slow spawn.
NATIVE_WEDGE_CLEANUP_TIMEOUT_SECONDS = 10
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


def _await_attach(name, sid, roster_fetch, sleep, clock,
                  verify_seconds=NATIVE_ATTACH_VERIFY_SECONDS):
    """True iff a freshly joined --bg session shows LIFE within the window;
    False = the never-attach wedge (live finding #2, 2026-07-16: the daemon
    occasionally mints the roster entry but never starts the runner --
    state:'working', no status/pid, no transcript, no outcome, forever).

    Life signals, cheapest-reliable-first per the probe forensics (12
    healthy spawns: status+pid at 4-6s post-dispatch, outcome ~10-15s):
      * roster entry carries `status` or `pid` -- the process attached;
      * roster entry reached a terminal/blocked state literal (done/failed/
        stopped/blocked) -- it RAN; the discriminator owns the verdict;
      * roster entry VANISHED post-join -- reaped, not the wedge shape;
        the discriminator + dispatch grace window own it;
      * an outcome record for this sid exists -- completed before any poll
        ever saw it live (fast-completion race).
    A transient roster-fetch failure is simply retried until the deadline
    (never treated as a wedge on its own).

    H1 (adversarial review): a FULL-WINDOW blackout -- zero successful
    fetches before the deadline -- is CANNOT-VERIFY, never a wedge
    verdict. A wedge verdict licenses stop/rm of the session; issuing it
    against a session we never once observed could kill a live turn
    mid-tool-run. Raises NativeDispatchError instead (loud abort; the
    caller's DOA handling surfaces it and the session, whatever its
    actual state, is left untouched)."""
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
                setting_sources=None,
                run=subprocess.run, which=shutil.which, sleep=time.sleep,
                roster_fetch=None, clock=time.monotonic):
    # Defense in depth (adversarial trap 6): every current caller
    # pre-validates `name`, but this is the choke point for every --bg
    # WORKER launch and `task_file_path(name)` is not traversal-safe on its
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
        # journals_dir() must exist BEFORE dispatch: it goes onto --add-dir
        # below, and claude silently grants nothing for a nonexistent dir --
        # the worker's protocol-mandated journal Write then hangs on a
        # permission prompt on any fresh fleet home (posix-port live
        # finding 2026-07-18, part 2).
        journals_dir().mkdir(parents=True, exist_ok=True)
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
    # posix-port live finding 2026-07-18: journals_dir() needs the same
    # pre-authorization -- compose_prompt's preamble ORDERS the worker to
    # "create it early; update it at each milestone", so under acceptEdits
    # every worker's first journal Write hung on the same unapprovable
    # prompt (latent upstream: campaigns run bypass, and the pin tasks are
    # reply-only). Same least-privilege doctrine: the two specific dirs
    # the worker protocol requires, never state/ or FLEET_HOME wholesale.
    argv += ["--add-dir", tasks_dir().as_posix(),
             "--add-dir", journals_dir().as_posix()]
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
    def _dispatch_once():
        """One dispatch + roster join. Per-attempt so the never-attach
        retry below re-runs the WHOLE sequence with a FRESH pre-snapshot.
        M1 (review): the wedged sid itself can never collide with the
        retry's join -- the join is short-id-prefix based and attempt 2
        gets a different prefix -- so the snapshot's real job is FOREIGN
        sessions: anything minted during attempt 1's attach window whose
        sid happens to share attempt 2's short-id prefix is present in the
        fresh snapshot and excluded; a stale (attempt-1) snapshot would
        predate it and let the join bind a foreign session. Pinned by
        test_fresh_presnapshot_excludes_foreign_prefix_collision."""
        # Snapshot the roster ONCE before dispatching -- any sid already
        # present (sharing the short-id prefix fleet is about to receive)
        # is excluded from the join below, so a foreign concurrent session
        # can never be mistaken for the one just launched. A snapshot fetch
        # failure never blocks dispatch -- fall back to an empty exclusion
        # set. Unhashable-sessionId guard (debt roll-up): filter the
        # sessionId VALUE's type too -- a dict-valued sessionId (CLI drift/
        # hostile roster) would otherwise raise TypeError from the set.
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
            # F5 fix wave (review ME-DAEMON-REVIEW-2026-07-21.md): read BOTH
            # streams, matching the twin classifier `_classify_native_cli_result`
            # (`text = f"{proc.stdout}\n{proc.stderr}"`). The old
            # `stderr or stdout` picked ONE: at 2.1.216 both the prefix and the
            # symptom land on the same stream so it was latent, but a vendor
            # that split them (prefix -> stderr, symptom -> stdout) silently
            # disabled the whole diagnosis, since non-empty stderr short-circuits
            # the `or`. stderr leads because that is where the real error was
            # observed and the raw echo below stays readable.
            detail = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()
            # M-E: name the cause instead of echoing the vendor string. The
            # unreachable-service shape is not this worker's problem -- it is
            # the whole machine's, and the operator needs the remedy, not the
            # bytes. The bytes are kept anyway (`vendor said`): the NEXT
            # wording drift is only findable if they survive into the log.
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
            # T4 fix wave (Important, Ctrl-C mid-join): a live --bg session
            # was already dispatched (proc.returncode == 0, short_id parsed)
            # by the time this loop runs -- if Ctrl-C (or any other
            # exception) lands here, the short id is the only handle an
            # operator has left to find it again via `claude agents`.
            # The note survives re-raise through cmd_spawn's except
            # BaseException handler, which has no other way to recover it
            # (dispatch_bg stays opaque -- no message parsing per T4).
            # `_stash_short_id_note`, not a bare `exc.add_note(...)`:
            # add_note is 3.11+ and this repo's floor is 3.10, where the
            # bare call replaced the escaping exception with an
            # AttributeError. See that helper.
            _stash_short_id_note(exc, short_id)
            raise
        if sid is None:
            raise NativeDispatchError(
                f"dispatched (short id {short_id}) but no roster entry joined "
                f"within {NATIVE_JOIN_VERIFY_SECONDS:.0f}s -- possible DOA; "
                f"recover manually via claude agents", short_id=short_id)
        return sid, short_id

    def _cleanup_wedged(sid, short_id):
        """Stop + rm a wedge-verdicted session and VERIFY the outcome
        (C1 CRITICAL, adversarial review): the stop/rm booleans were
        previously discarded and the retry dispatched unconditionally --
        but a false wedge (attach slower than the window under daemon
        overload) plus a failed stop (same overload, correlated) meant
        attempt 1 could attach AFTER attempt 2 launched: two live sessions
        on one task file, only sid2 tracked, and the rogue -- being
        status/pid-live -- is skipped by every husk sweep forever. Per
        _stop_native_session's own contract, False means COULD NOT VERIFY:
        re-fetch the roster and declare the retry safe only if the entry
        is verifiably gone or still status/pid-free. Returns
        (stopped, removed, retry_safe, detail).

        M2: both subprocesses run with the short wedge-path timeout --
        this path sits inside spawn latency budgets (pin SPAWN_TIMEOUT);
        a hung schtasks-style 30s x 3 stall here is the difference between
        a slow spawn and a blown harness."""
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

    # Never-attach wedge guard (live finding #2, 2026-07-16): a joined
    # roster entry is NOT a started session -- rarely (~1/13 hand-probed
    # spawns that day) the daemon mints the entry and never attaches the
    # runner. Verify attachment; on a wedge, stop/rm the session -- unstarted
    # as far as every observation shows (no process, no tool ran, task file
    # untouched; the 30s window is calibration against n=12 healthy probes,
    # not proof, which is exactly why _cleanup_wedged verifies before any
    # retry) -- and redispatch EXACTLY ONCE. A second consecutive wedge
    # gives up loudly -- callers (cmd_spawn DOA rollback et al.) surface
    # it; never a silent working-forever record.
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

# claim-nonce §5.3: how long a minted-but-unacknowledged generation blocks a
# replacement mint. Proposed at 900 s and NOT 300 s, and the asymmetry is the
# part that must not be re-derived backwards: §5.4(b) wants it short (a pending
# lost to a verb that died after committing is replaced sooner) and §5.4(d)
# wants it long (a delivered pending is not stolen from a body that is merely
# thinking). The two costs are NOT symmetric -- a long TTL only delays the
# REPLACEMENT of a lost pending, during which the body keeps working on `live`
# and nothing is refused, whereas a short TTL actively invalidates a value a
# legitimate body is holding. 900 s is above a routine supervisor turn here;
# the exact number is the operator's to tune.
PENDING_NONCE_TTL_SECONDS = 900.0

# §6.5 D5: `--nonce <value>` is the ONLY presentation channel. There is no
# `FLEET_SUP_NONCE`, and adding one would be a design error rather than a
# convenience: `_worker_env` copies the entire parent environment and strips
# exactly one key, so any env-var channel is inherited by every worker fleet
# spawns and by every subagent those workers spawn. A command-line argument
# does not propagate to children; on this substrate both are readable by a
# same-user process, so propagation is the whole difference -- and it is
# decisive. (Belt-and-braces if a future env channel is ever added anyway:
# strip it in `_worker_env` alongside CLAUDE_CODE_SESSION_ID.)
NONCE_ARG_HELP = ("the generation this body was last given (claim-nonce §5.3); "
                  "the ONLY presentation channel -- there is no env-var fallback")

# The same generation, presented on a MUTATING LIFECYCLE verb. It does two
# jobs: it clears §7's gate (a fresh held claim demands continuity from a
# supervisor-shaped caller), and it lets §6.2's lineage rule own the workers a
# rotated body's lineage spawned. Both are bypassable speed-bumps, not
# authorization; both are inert when no fresh claim is held.
GATE_NONCE_ARG_HELP = ("the current supervisor generation (claim-nonce §5.3): clears §7's "
                       "claim gate for a mutating verb while a fresh claim is held, and "
                       "proves the lineage that owns a rotated body's workers (§6.2)")

# §5.6: a `refused` record inside this window is the ONE condition that flips
# `_doctor_check_supervisor_claim` off `ok=True`. 24 h is long enough that a
# refusal survives an overnight gap between an incident and the operator
# looking, and short enough that a resolved one stops shouting.
NONCE_REJECTION_WINDOW_SECONDS = 24 * 3600

# §5.6's "a stated multiple of the TTL". Stated as 2, and the choice is
# §5.4(d)'s: `prior_pending_hash` keeps a delivered pending presentable for
# exactly one more generation, so two TTL periods is precisely the point past
# which the third slot has stopped protecting the quiet body. A pending
# outstanding longer than that means the presenter obligation (§5.3) is being
# violated and the detection property is degraded -- the §5.4(e) silent miss,
# which produces no refusal at all and would otherwise leave doctor green.
NONCE_PENDING_STALE_MULTIPLE = 2

# §5.9's cap on `state/supervisor-nonce-rejections.jsonl`. Enforced OUT OF
# BAND (see `_compact_nonce_rejection_log`), never by the writer: truncation
# is a read-modify-write needing GENERIC_WRITE, which is exactly the access
# mode `_atomic_append_bytes`'s docstring says forfeits the atomic-append
# guarantee -- and the concurrent-writer case is the one this file exists to
# record. `_doctor_check_supervisor_claim` reads only the tail regardless, so
# the cap is hygiene, not correctness.
NONCE_REJECTION_LOG_MAX_RECORDS = 200


# ---------------------------------------------------------------------------
# Supervisor claim nonce -- the continuity primitives (claim-nonce §5.1, §5.2)
#
# The nonce is a CONTINUITY token, not an authorization one. Presenting the
# current generation proves exactly one thing: the actor presenting this value
# is the same actor to which the last generation was delivered. §2.1 of that
# spec explains why nothing on this box can prove more than that.
#
# Stdlib-only and inside the 3.10 floor: `secrets.token_urlsafe` (3.6+),
# `hashlib.sha256`, `hmac.compare_digest` (3.3+).
# ---------------------------------------------------------------------------

def mint_nonce() -> str:
    """A fresh generation. Entropy only -- never derived from the incarnation
    id, the sid or the clock, all three of which a lock-free view publishes."""
    return secrets.token_urlsafe(32)


def nonce_digest(value: str) -> str:
    """The stored form. INCARNATION holds this, never the value (§5.2).

    Hash-only storage protects the copy in `supervisor/`; §5.5 is explicit
    that this is NOT what makes the nonce unforgeable -- the real store is the
    session transcript, which `--fork-session` duplicates by design."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def nonce_matches(presented, stored) -> bool:
    """Constant-time comparison of a presented value against a stored digest.

    Both operands of `hmac.compare_digest` are HEX STRINGS -- §5.2 names
    "comparing a digest object to a hex string" as the shape to avoid, and
    `compare_digest` raises TypeError on a str/bytes pair rather than
    returning False. Every non-string input is therefore a REFUSAL here, never
    an exception: an absent `nonce_hash` (a legacy claim §9, a released claim
    §6.3) reaches this function routinely, and deciding what that absence
    means is §5.3's job one layer up, not this primitive's."""
    if not isinstance(presented, str) or not presented:
        return False
    if not isinstance(stored, str) or not stored:
        return False
    return hmac.compare_digest(nonce_digest(presented), stored)

# B4/D6: the fleet mode name the handoff successor is dispatched under when the
# operator passes no --permission-mode. Deliberately the SAME default
# `fleet spawn` uses (`p_spawn --mode`, MODE_FLAGS @949) rather than a bespoke
# one: the successor's first act is a Bash call, and a headless --bg session
# under claude's own default mode wedges on an unanswerable permission prompt
# (the T12 hang class). Held as a named constant so the dispatch and its pin
# read the same value.
SUCCESSOR_DEFAULT_MODE = "dontask"

SUPERVISOR_JOURNAL_KINDS = (
    "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED", "RELEASED", "LIMIT-TRANSFER",
    "HANDOFF-BEGIN", "HANDOFF-COMPLETE", "HANDOFF-ABORT",
)

# The published `sup-boot` exit-code contract (skills/fleet/SKILL.md:37).
# Held as a named constant rather than a dict literal inside cmd_sup_boot so
# that a verdict outside the set is a KeyError at ONE site a test can name --
# break-gate residual F2's failure mode is a verdict the map does not carry.
# `resume` (claim-nonce §6.1 rule 3) joins the 0-row: it is the holder keeping
# a claim it already had, which is not an event an exit code should distinguish
# from claiming one.
SUPERVISOR_BOOT_RC = {"claim": 0, "resume": 0, "seize": 0, "limit-transfer": 0,
                      "refuse": 2, "freeze": 3}
SUPERVISOR_BOOT_VERDICTS = tuple(SUPERVISOR_BOOT_RC) + ("handshake-written",)

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


def write_handshake(incarnation_id: str, session_id: str,
                    handoff_token_hash=None, nonce_hash=None) -> None:
    """claim-nonce §6.4: HANDSHAKE is
    `{incarnation_id, session_id, handoff_token_hash, nonce_hash, written_at}`.

    `handoff_token_hash` is sha256 of the one-shot token begin minted and the
    successor was handed through its task file -- it is what complete verifies,
    replacing the old `session_id` equality that a fork-steer between HANDSHAKE
    and complete would break (the fork-steer root cause, third instance).
    `nonce_hash` is the successor's OWN freshly minted generation, so the
    transferred claim carries a live generation and needs no legacy upgrade.
    Both are optional so the older 2-arg call sites (bystander/refuse-path
    tests, and a mixed-code successor) still produce a valid HANDSHAKE;
    `session_id` stays for observability, `written_at` is write-only (the
    doctor check uses file mtime)."""
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


def handoff_task_file_path(successor_inc: str) -> Path:
    """§5.9: the successor's bootstrap task file, which carries the plaintext
    handoff token. Written by `sup-handoff-begin`, unlinked by complete/abort,
    and NOTE-backstopped by the doctor for the crash-before-unlink paths."""
    return state_dir() / f"supervisor-handoff-{successor_inc}.md"


def mint_incarnation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"inc-{stamp}-{uuid.uuid4().hex[:4]}"


def mint_lineage_id() -> str:
    """claim-nonce §5.2: `lin-<utc>-<4 hex>`. Minted at the first fresh claim,
    CARRIED across handoff, RE-MINTED on seize.

    The re-mint is the load-bearing asymmetry (§6.2): a handoff is a planned
    succession with the predecessor alive to vouch, so provenance continues; a
    seize is a recovery from a body that could not vouch for anything, so
    carrying the lineage would launder the dead body's provenance onto the
    seizing one and make every worker it spawned look like the new body's own.
    Being asked once, at a recovery, is correct."""
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
    predecessor would block every successor claim for hours.

    posix-port live finding 2026-07-19 (macOS, claude 2.1.214): a finished
    bg session's host process can LINGER after its turn ends -- the entry
    keeps `pid` AND `status` ("idle") with `state:"done"`. The key-presence
    heuristic alone therefore misreads it as live (observed blocking
    `fleet respawn` on an idle worker). The documented terminal-state rule
    must dominate key presence: `state:"done"` is never live, keys or not.
    (On Windows the two conditions agree -- done entries lose pid/status.)"""
    # Same hostile-sessionId-value guard as dispatch_bg's pre-snapshot: a
    # dict-valued sessionId (CLI drift / hostile roster) must never raise
    # TypeError from an unhashable value landing in the set.
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
    """§6.1 rule 3's premise, named so rules 4-'s precondition can be tested
    against a WEAKENED version of it (T14b). A caller that proved continuity
    resumes iff the recorded holder is roster-gone, or is the caller itself.

    Held as a function rather than inlined because the whole lesson of N1 is
    that an implication nobody can reach is an implication nobody can test:
    the roster precondition below is unreachable while this returns True for
    the live-holder case, so the test that proves the precondition has a
    stated `else` has to be able to make this False."""
    return bool(nonce_valid) and (holder_sid not in live_sids or holder_sid == caller_sid)


def _holder_is_limited(holder_sid) -> bool:
    """True iff the registry records `holder_sid` as `limited` WITH a horizon.

    three-tier-command.md `:432-437`, filed against this slice: the parked
    holder's status is what authorizes an immediate claim transfer. Resolved
    HERE, by a caller that already holds `fleet_lock`, and passed into
    `supervisor_claim_decision` -- that function is pure and has no registry
    access, which is precisely the hole the prerequisite targets.

    "With a horizon" is load-bearing. `_limit_reset_passed`'s own docstring
    says a null `limit_reset_at` is "never auto-eligible": fleet does not know
    when that body comes back, so it is NOT the unambiguous fleet-observed
    state the prerequisite rests on -- and ambiguity is exactly what the
    freeze exists for.

    Never raises. `load_registry` quarantines a corrupt file and raises
    `RegistryCorruptError`, and the callers it documents "must abort" -- the
    boot ritual must not. A corrupt registry is already reported by its own
    doctor row and by `_render_boot_bundle`'s "(registry unreadable)" line,
    and turning it into an aborted claim decision would take the supervisor
    down for a fault in a different subsystem. False is also the fail-closed
    answer: it declines the transfer."""
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


def supervisor_claim_decision(claim, live_sids: set, latest_entry, now=None,
                              stale_seconds: float = SUPERVISOR_CLAIM_STALE_SECONDS,
                              caller_sid=None, nonce_valid: bool = False,
                              holder_limited: bool = False):
    """Claim rules at boot (claim-nonce §6.1, verbatim order). Returns
    (verdict, reason); verdict in SUPERVISOR_BOOT_VERDICTS. Pure -- no IO.

    Rule order, and why it is this order:

      0. no claim                       -> claim   (fresh)
      1. state == "released"            -> claim   (fresh, §6.3) -- ahead of
         everything, because a released claim has neither session_id nor
         heartbeat_at and every later rule would misread its absence;
         `refuse` while its releaser is still roster-live (B6)
      1b. holder parked `limited` with a horizon, and not resumable
                                        -> limit-transfer (three-tier
         `:432-437`) -- ahead of rule 2, because a parked body is still
         roster-live and rule 2 would refuse before anything looked at it
      2. holder roster-live, UNLESS the caller is that holder AND proved
         continuity                     -> refuse  (the two-supervisor guard)
      3. continuity proved, holder roster-gone or holder is the caller
                                        -> resume  (incident 2's fix: no
         seize, no new incarnation, no SEIZED entry, no page)
      4- holder roster-gone             -> freeze / refuse / seize / freeze
         else                           -> refuse  (fail-closed)

    Rule 2's exception is keyed on CONTINUITY, never on the sid alone.
    `caller_sid` reaches this function from `current_caller_session()`, which
    is one `os.environ.get` -- so a rule written as `holder_sid != caller_sid`
    would let a settable environment variable DE-AUTHORIZE the only
    body-discriminating check in the program. Concretely: read the holder's
    sid from the lock-free `sup-status` view, export it, boot holding no
    generation, and rules 4- reach `seize` against a live healthy supervisor
    as soon as its heartbeat ages past the threshold -- which, with no
    automatic beat in this slice, is the ordinary state of a busy supervisor.
    That would be strictly less safe than shipped code, which refuses a
    roster-live holder unconditionally. T14(iii) pins the attack."""
    if now is None:
        now = datetime.now(timezone.utc)
    if claim is None:
        return ("claim", "no existing claim -- fresh claim")
    if claim.get("state") == "released":
        # B6 (three-tier-command.md :1184-1190), the prerequisite that spec
        # filed against this one: "sup-boot must not consume a `released`
        # record whose `released_by_sid` is still roster-live -- either rule 1
        # gains a roster-liveness precondition, or release+stop is made atomic
        # from the claim's perspective". Rule 1 gains the precondition.
        #
        # `fleet sup-release` then `claude stop` is TWO commands and the window
        # between them is real. three-tier adds AUTOMATED occupants of it (a
        # scheduled beat, `sup-spawn`, a handoff successor polling `sup-boot`),
        # and SPEC §16.7's one-live-session-per-name blocks a second
        # `supervisor`-named spawn but not a `sup-boot` from an already-live
        # differently-named session. Consuming the record inside that window
        # produces exactly the two-live-supervisors shape §6.6 exists for.
        #
        # Keyed on a non-empty STRING only: a released claim carries no
        # `session_id` at all (§6.3), so a `None` that a drifted or hostile
        # roster put in the live set must not be able to gate a record that
        # names no releaser -- that would strand the claim forever on a value
        # nobody wrote.
        released_by = claim.get("released_by_sid")
        if isinstance(released_by, str) and released_by and released_by in live_sids:
            return ("refuse", f"claim {claim.get('incarnation_id', '?')} is released but its "
                              f"releaser (sid {released_by}) is still live in the roster -- "
                              f"release+stop is not complete; wait for that body to exit")
        return ("claim", f"predecessor {claim.get('incarnation_id', '?')} released cleanly "
                         f"-- fresh claim, no seizure")
    holder_sid = claim.get("session_id")
    holder_live = holder_sid in live_sids
    resume_ok = _claim_resume_allowed(nonce_valid, holder_sid, caller_sid, live_sids)
    if holder_limited and not resume_ok:
        # three-tier-command.md `:432-437`, filed against this slice: a holder
        # parked `limited` with a recorded horizon authorizes IMMEDIATE
        # transfer. Unlike roster-gone -- which is G9-ambiguous, and is exactly
        # why the freeze exists -- `limited` is a fleet-observed, unambiguous
        # state that fleet itself wrote. Today a successor meets only `refuse`
        # or an hour-long `freeze` against a parked predecessor.
        #
        # It runs AHEAD of the roster-liveness guard, and that ordering is the
        # branch: a parked body is still roster-live, so rule 2 would refuse
        # before anything could look at it. This is a narrow, deliberate
        # carve-out of §6.6 -- that guard exists to stop two ACTING bodies,
        # and a body parked on a plan limit is not an acting body; the
        # prerequisite's own "including a holder parked mid-handoff" clause is
        # the extreme case, since such a body can neither complete nor abort
        # the ritual it started.
        #
        # `not resume_ok` is the exception to the exception: a parked body
        # that came back and can PROVE continuity is not a transfer candidate,
        # it is the holder. Without this, fleet would take the claim away from
        # the one body that just demonstrated it still has it.
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
    # Rules 4- assert "holder roster-gone" in strings they write into the
    # append-only, git-tracked journal. Break-gate residual F2: that
    # precondition must be an explicit branch with a stated `else`, because an
    # audit record asserting a premise nobody tested is a durable corruption
    # of the only artifact a future incident review will have.
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
    notices = []
    if getattr(args, "handoff_inc", None):
        # Successor mode: claim-pending, holds NO claim, takes no actions
        # (spec §4). Writes HANDSHAKE only -- never the journal.
        #
        # §6.4: the successor mints its OWN generation here and stores its hash
        # in HANDSHAKE, so the claim complete transfers carries a live
        # generation and needs no legacy upgrade. The plaintext is delivered on
        # THIS body's own stdout -- the successor is the one body allowed to
        # hold it, which is exactly why it is minted here and not at complete
        # (that would print it on the predecessor's stream). The token hash
        # travels alongside so the predecessor can verify the body it
        # dispatched without a sid comparison a fork-steer would break.
        token = getattr(args, "handoff_token", None)
        succ_value = mint_nonce()
        with fleet_lock():
            write_handshake(args.handoff_inc, caller_sid,
                            handoff_token_hash=nonce_digest(token) if token else None,
                            nonce_hash=nonce_digest(succ_value))
        notices.append(f"NONCE: {succ_value}")
        verdict = "handshake-written"
        reason = (f"successor {args.handoff_inc} awaiting claim transfer; "
                  f"take NO fleet actions until sup-status shows your incarnation")
        rc = 0
    else:
        with fleet_lock():
            # §5.9 / break-gate residual F1: the ONE authorized site for the
            # rejection log's out-of-band cap. Under the lock this block
            # already holds, on a path that runs once per body -- never on the
            # refused caller, which holds no lock and may be the untrusted
            # body. Ahead of the decision so an oversized log is bounded even
            # on a boot that goes on to refuse.
            _compact_nonce_rejection_log()
            claim = read_incarnation()
            latest = supervisor_journal_latest()
            # §6.1 rules 2 and 3 both key on CONTINUITY, so the decision needs
            # both of these -- and until this wiring existed the rule the
            # verdict order was rewritten around was unreachable from the one
            # command that owns it.
            presented = None if claim is None else _nonce_presentation(
                claim, getattr(args, "nonce", None))
            if not epoch_ok:
                verdict, reason = "freeze", f"epoch check failed: {epoch_reason}"
            else:
                verdict, reason = supervisor_claim_decision(
                    claim, live_sids, latest, caller_sid=caller_sid,
                    nonce_valid=presented is not None,
                    # Resolved here rather than inside the pure function --
                    # this block already holds `fleet_lock`, and the decision
                    # function has no registry access by design.
                    holder_limited=claim is not None and _holder_is_limited(
                        claim.get("session_id")))
            if verdict == "claim":
                inc = mint_incarnation_id()
                value = mint_nonce()
                # §9's binding rule: this is one of the three DICT-LITERAL
                # writers, and a field added only to the round-trip writers
                # survives checkpoints and heartbeats and is then silently
                # destroyed here -- a claim that works for days and fails at
                # the worst moment. T10 exists solely to catch a missed one.
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": "fresh",
                                   "nonce_hash": nonce_digest(value), "nonce_seq": 1,
                                   "lineage_id": mint_lineage_id()})
                supervisor_journal_append("BOOT", inc, caller_sid, f"fresh claim: {reason}")
                inc_line = inc
                notices.append(f"NONCE: {value}")
            elif verdict == "resume":
                # §6.1 rule 3: NO seize, NO new incarnation, NO `SEIZED`, no
                # page. The body already holds the claim; this is it proving
                # so. Restamp, beat, and journal a BOOT that says which.
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
                # A limit transfer is NOT a seizure and the append-only,
                # git-tracked audit record must not say it was: three-tier
                # `:429` asks for "a distinct journal kind recording that it
                # was a limit transfer rather than a seizure", and an entry
                # asserting a seizure that did not happen is a durable
                # corruption of the only artifact a future incident review
                # will have (the F2 lesson, one layer out).
                kind = "SEIZED" if verdict == "seize" else "LIMIT-TRANSFER"
                took = "seized from" if verdict == "seize" else "limit-transfer from"
                try:
                    # Stale-HANDSHAKE hygiene (spec §4): an orphan from a crash
                    # mid-handoff must never receive a claim transfer.
                    handshake_path().unlink()
                except FileNotFoundError:
                    pass
                # Second dict-literal writer (§9). `lineage_id` is RE-MINTED
                # here, never carried: see mint_lineage_id's docstring.
                # `lineage_id` is re-minted on BOTH arms. A limit transfer is
                # like a seize and unlike a handoff: the parked predecessor is
                # not alive to vouch for anything, and it may yet come back
                # when its horizon passes -- carrying its lineage would hand
                # every worker it spawned to the taking body (§6.2).
                write_incarnation({"incarnation_id": inc, "session_id": caller_sid,
                                   "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                                   "claimed_via": verdict if verdict != "seize" else "seize",
                                   "nonce_hash": nonce_digest(value), "nonce_seq": 1,
                                   "lineage_id": mint_lineage_id()})
                supervisor_journal_append(kind, inc, caller_sid,
                                          f"{took} {dead}: {reason}")
                inc_line = inc
                notices.append(f"NONCE: {value}")
            # refuse / freeze: strictly read-only.
        rc = SUPERVISOR_BOOT_RC[verdict]

    bundle = _render_boot_bundle(entries, status_snapshot(), supervisor_journal_entries())
    lines = [bundle, "", f"EPOCH: {'ok' if epoch_ok else 'FAIL'} -- {epoch_reason}"]
    if inc_line:
        lines.append(f"INCARNATION: {inc_line}")
    lines.append(f"VERDICT: {verdict} -- {reason}")
    _write_text_tolerating_console_encoding("\n".join(lines) + "\n")
    # §5.8's second publisher: the ONE plaintext this design prints is the
    # newly minted generation, printed exactly once, on the minting verb's own
    # stdout. No hash reaches this stream at all.
    _deliver_notices(notices)
    return rc


def _claim_is_legacy(claim: dict) -> bool:
    """claim-nonce §9's predicate, verbatim: legacy <=> `nonce_hash` absent
    AND `state` absent.

    The second conjunct is the whole point. A RELEASED claim (§6.3) also has
    no `nonce_hash`, and it keeps `released_by_sid` -- so a predicate written
    as "no nonce_hash means legacy, compare the sid" has a sid sitting right
    there to match, and "released" would stop being terminal: whoever matched
    the recorded sid would resurrect the claim in place.

    §6.3's enumerated post-release key set (which drops `session_id`) is the
    other half of that fix, and the two are deliberately belt-and-braces: this
    predicate is shadowed at its only call site by the released branch in
    `_require_claim_holder`, so it is pinned by direct unit tests rather than
    through a verb, which is the only way a shadowed guard can be proven to
    carry its own weight."""
    return "nonce_hash" not in claim and "state" not in claim


def _supervisor_gate(verb, nonce=None, now=None):
    """claim-nonce §7 -- THE GATE (option (b), ratified 2026-07-23). Raises
    `SupervisorClaimGateError` when a mutating lifecycle verb is run by a
    supervisor-shaped caller while a supervisor claim is HELD with a FRESH
    heartbeat and the caller cannot prove continuity on it. Returns silently
    otherwise. READ-ONLY: no lock, no mint, no write.

    Called at the top of every mutating lifecycle verb (§7's taxonomy: spawn,
    send, respawn, kill, clean, interrupt, archive, resume-limited, release,
    init). It is NEVER called from a view or an authoritative-read path -- a
    gate on `sup-status` or `status --stale-ok` would make the SessionStart
    hook of every session on this box refuse while a supervisor is live.

    WHAT IT IS, stated exactly because §7 was corrected for pretending
    otherwise: a speed-bump against an over-helpful SECOND body, not an
    authorization boundary. Everything it refuses, the refused caller reaches
    by another documented route -- present the generation with `--nonce`, or
    run the verb from a shell with no `CLAUDE_CODE_SESSION_ID`. A substrate
    with no privilege separation (§2.1) cannot host authorization, and calling
    this one would mislead a future reader.

    THE ARMING CONDITIONS, and why each disarms:
      * no `CLAUDE_CODE_SESSION_ID` -> not armed. A caller with no sid cannot
        be the divergent supervisor body a fork produced. This is also the
        STRUCTURAL exemption for `autoclean`'s scheduled task (no operator env)
        and for a human shell; `autoclean` additionally is not wired to call
        this at all (§7).
      * no held claim / a released claim -> nothing to gate against.
      * heartbeat older than `SUPERVISOR_CLAIM_STALE_SECONDS` -> DISARMED. This
        slice ships no automatic beat (§4.13(e)), so protection is present only
        in the hour after a human last acted and absent in the quiet stretches
        an unattended second body would exploit. A DISCLOSED weakness of option
        (b), not a bug: arming it against a stale claim would fire on a body
        that has already aged into being seizable, which is the wrong target.
      * an unreadable heartbeat -> fail OPEN (a speed-bump must not brick every
        mutating verb; the corrupt claim is reported by its own doctor row).
      * a legacy claim (§9) -> no generation exists to demand; the mixed-code
        shape must not brick a body.

    When armed, the caller must present a generation that VALIDATES against the
    claim (§5.3, via `_nonce_presentation`) -- and validation here mints
    NOTHING (§5.3: rotation is a supervisor ritual, not a side effect of
    dispatching a worker). A divergent fork holding a retired generation
    presents a value that is neither live nor pending nor prior-pending and is
    refused; this is what makes the 2026-07-16 dual-supervisor class a refusal
    instead of ~100 silent minutes."""
    caller = current_caller_session()
    if caller is None:
        return
    try:
        claim = read_incarnation()
    except Exception:  # noqa: BLE001 -- speed-bump: never crash a verb on this
        return
    if not isinstance(claim, dict) or claim.get("state") == "released":
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
    raise SupervisorClaimGateError(
        f"{verb}: refusing -- a supervisor claim ({claim.get('incarnation_id', '?')}) "
        f"is held and fresh, and this call did not prove continuity on it "
        f"(claim-nonce §7). Present the current generation with `--nonce <value>` "
        f"(the value the last `sup-*` verb printed), or escalate to the supervisor "
        f"session. This is a SPEED-BUMP, not a security boundary: it is bypassable "
        f"by anyone who can run this command without a session id, and it is armed "
        f"only while the claim's heartbeat is fresh.")


def _caller_proven_lineage(caller, nonce):
    """claim-nonce §6.2: the `lineage_id` of a claim the caller proved
    continuity on in THIS invocation, or None. Consumed by the destructive
    guard (`_confirm_destructive`) so a later body of a lineage owns the
    workers that lineage spawned.

    VALIDATES WITHOUT MINTING (§7's rule for gated verbs): the destructive
    verbs are not sup verbs and must not rotate the generation or write the
    claim. So this reads only -- no `write_incarnation`, no `_mint_pending`.
    Never raises: it runs on the kill/clean/respawn path and a corrupt or
    absent claim must degrade to "unproven" (today's spawned_by-only answer),
    not crash a kill.

    Proof is a presented GENERATION (§5.3). A legacy claim has none, so it
    yields None -- a legacy-era supervisor gets today's answer, which is the
    conservative direction. A released claim yields None too: it has no holder
    and no live lineage to speak for."""
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
    """claim-nonce §6.2: the `lineage_id` to stamp into a worker spawned by
    this caller, or None. The spawning body is the supervisor holding the
    claim, so this is the current claim's lineage when the caller is its
    recorded holder.

    Keyed on the holder sid rather than on a presented generation because
    `fleet spawn` is not a continuity-gated verb -- stamping provenance is a
    record, not a guarded action, and requiring a nonce on every spawn would
    be a large surface for a field that only ever HELPS ownership. A
    fork-steered supervisor that spawns before its next sup verb simply stamps
    None and the worker falls back to `spawned_by == caller` (its current sid),
    which still owns it. Never raises."""
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
    """One JSON record, appended ATOMICALLY (§5.6).

    `_atomic_append_bytes` is the single-syscall FILE_APPEND_DATA/O_APPEND
    primitive this codebase already carries precisely so that two writers
    appending in the same instant never clobber each other -- and THIS FILE'S
    WHOLE PURPOSE is to record the case where two bodies are being refused
    concurrently. So the append must never degrade to a read-modify-write, and
    the file is left unbounded by the writer; §5.9 puts the cap out of band,
    under `fleet_lock`, never on the refused caller.

    `presented_prefix` is the first 8 hex of the presented value's sha256 and
    never the value: enough to tell "the same wrong value twice" from "two
    different wrong values", which is the question an operator actually asks,
    without making the log a place a generation can be recovered from.

    Best-effort. The record is EVIDENCE, not the refusal -- if it cannot be
    written the caller must still be refused, because a body that learns "I
    could not be logged" instead of "stop and escalate" is the worst of
    both."""
    record = {
        "ts": now_iso(),
        "kind": kind,
        "verb": verb,
        "caller_sid": caller_sid,
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
    """§5.9's out-of-band cap, and break-gate residual F1's resolution.

    CALLER MUST HOLD `fleet_lock`. The one authorized site is `cmd_sup_boot`
    (§8): it already takes the lock, it already writes supervisor state, and
    it runs once per body rather than on any hot path. `fleet clean` is NOT a
    site -- F1's finding was that §5.9 applied two different standards to it
    in adjacent bullets, withdrawing the handoff-file sweep on the receipt
    that every candidate `_remove_worker_files` builds is keyed on a worker
    name or sid, and then proposing `fleet clean` for this file two paragraphs
    later. Same class, same receipt: a fixed supervisor-scoped path belonging
    to no worker record, which §4.13(g) shows `cmd_clean` cannot reach.

    The rewrite keeps the NEWEST records -- dropping those would throw away
    the evidence of the incident an operator is most likely in the middle of.
    Best-effort and silent: a hygiene sweep must never be able to fail a boot,
    and a log at 260 records is not a problem worth refusing a claim over."""
    path = nonce_rejection_log_path()
    try:
        if not path.exists():
            # early-out, not a guard -- absence is behavior-identical: the
            # `except OSError` arm below already swallows the FileNotFoundError
            # a missing file raises from read_text. Removing this line stays
            # green by design; it exists only to skip a doomed read.
            return
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if len(lines) <= limit:
            return
        # temp + os.replace, the same shape `_write_json_atomic` uses: a
        # concurrent refused caller appending through _atomic_append_bytes must
        # never observe a half-rewritten file, and `state/` is gitignored so
        # the sibling leaves no repo residue.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(lines[-limit:]) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
    except OSError:
        pass


def _recent_nonce_rejections(now=None, window=NONCE_REJECTION_WINDOW_SECONDS) -> list:
    """Records inside the window, newest-biased. Reads only the TAIL (§5.9:
    the cap is hygiene, not correctness, precisely because this reader never
    needs the whole file). Never raises -- every caller is a view or the
    doctor."""
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


def _nonce_presentation(claim: dict, nonce):
    """Which generation the caller presented: "live", "pending", "prior", or
    None. PURE -- it decides nothing and mutates nothing.

    Up to three generations are presentable at once (§5.3): the live one, an
    optional pending that has been minted and committed but not yet proven
    received, and an optional superseded pending -- a pending that was replaced
    before anyone acknowledged it (§5.4(d) is why the third slot exists).

    Held as one function because it has TWO callers that must agree:
    `_require_claim_holder` (which acts on the answer) and `cmd_sup_boot`
    (which feeds `nonce_valid` to §6.1's verdict order). Duplicating the slot
    list across the two is the shape that lets `sup-boot` refuse a body whose
    last delivery was a pending -- the one command whose job is to
    re-establish continuity, failing the bodies with the least of it."""
    if nonce_matches(nonce, claim.get("nonce_hash")):
        return "live"
    if nonce_matches(nonce, claim.get("pending_nonce_hash")):
        return "pending"
    if nonce_matches(nonce, claim.get("prior_pending_hash")):
        return "prior"
    return None


def _acknowledge_pending(claim: dict) -> None:
    """§5.3 rule 2's promotion, in-memory. The caller has proven it received
    the pending value; ONLY THEN does the old generation die.

    All three pending slots are cleared, `prior_pending_hash` included --
    leaving it behind would keep a superseded generation presentable across an
    acknowledgment that was supposed to retire everything before it."""
    claim["nonce_hash"] = claim["pending_nonce_hash"]
    claim["nonce_seq"] = claim.get("nonce_seq", 1) + 1
    for key in ("pending_nonce_hash", "pending_at", "prior_pending_hash"):
        claim.pop(key, None)


def _continuity_refusal(verb, claim: dict) -> FleetCliError:
    """§5.6's loud refusal, worded under §5.7's binding constraint.

    Agent-facing output must name the ambiguity and the escalation, and must
    NOT name a lever that resolves it unilaterally. §5.4(c) is explicit that
    the mechanism cannot prefer either body -- both present byte-identical
    values from byte-identical contexts -- so the refused body may be the
    legitimate one, and a message naming a lever hands that lever to whichever
    body reads it first. v1's refusal instructed the refused caller to run a
    read-only view and act on what it printed; that is the reversal.

    The human-facing runbook (`skills/fleet/supervisor.md`) is the far side of
    this audience boundary. It is a convention, not a mechanism."""
    return SupervisorContinuityError(
        f"{verb}: continuity proof failed (expected generation "
        f"{claim.get('nonce_seq', '?')}) -- a second body of your lineage may be "
        f"acting. STOP: take no further supervisor actions and escalate to the "
        f"operator.")


def _mint_pending_nonce(claim: dict, now=None) -> str:
    """§5.3's mint step, in-memory. Returns the stdout notice the verb emits
    AFTER its commit; the caller performs the single `write_incarnation`.

    Mint iff no pending is outstanding, or the outstanding one has aged past
    `PENDING_NONCE_TTL_SECONDS`. A mint that REPLACES an outstanding pending
    moves the old hash to `prior_pending_hash` rather than discarding it
    (§5.4(d): otherwise the TTL makes the winner the body that acts most often
    inside the window, which systematically favours a looping body over a
    human-attached one that thinks). One slot, not a chain -- a second
    replacement drops the oldest.

    An unreadable `pending_at` counts as expired: the replacement is the safe
    direction, because the value being replaced stays presentable for one more
    generation via `prior_pending_hash` and nobody is locked out."""
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
    """(claim, caller_sid, notices) iff the caller proves CONTINUITY on the
    claim; FleetCliError otherwise. Caller MUST already hold fleet_lock, and
    MUST perform exactly one `write_incarnation(claim)` afterwards -- §5.3
    requires the acknowledgment, the mint and the verb's own state change to
    commit together, so a verb that fails before that write rotates nothing.

    `notices` is the list of stdout lines the verb emits AFTER its commit:
    delivery is "printed once, on the verb's own stdout" (§5.3) and there is
    no other copy anywhere. Returning them rather than printing here is what
    keeps the print outside the committed state change.

    §5.1: the nonce REPLACES the sid as the continuity key here -- a strictly
    better key, because it survives fork-steer and respawn and because a stale
    one is evidence rather than noise. Validation rules, in §5.3's order:

      1. presented == live          -> valid; nothing is promoted
      2. presented == pending       -> valid, AND this is the acknowledgment:
         the old generation dies only once its successor is proven received
      3. presented == prior_pending -> valid, NOT an alarm (§5.4(d)); promote
         nothing and record it quietly
      4. legacy claim (§9)          -> today's exact sid equality, honored
         ONCE, then upgraded in place
      5. otherwise                  -> refuse (§5.6)

    Still the enforcement point for spec §4's journal single-writer rule; the
    question it asks has changed from "are you the recorded sid" to "are you
    the actor the last generation was delivered to"."""
    # §6.5 / §13 item 1: "a worker turn can hold the supervisor claim, and is
    # prevented only by accident." Adjudicated to the NARROW arm -- refuse when
    # FLEET_WORKER is set and its value is not supervisor-shaped. See
    # `_SUPERVISOR_SHAPED_WORKER_RE` for why a blanket refusal is wrong and why
    # the exempt shape cannot be forged through `fleet spawn`.
    #
    # Ahead of the claim read on purpose: the ROLE answer does not depend on
    # whether a claim exists, and a worker turn should be told it is a worker
    # rather than that a claim is missing.
    #
    # This keys on the worker NAME because that is what `_worker_env` stamps
    # (`env["FLEET_WORKER"] = name`). three-tier-command.md ~L1078 describes it
    # as `FLEET_WORKER=1`; that text is wrong and its own receipt at :1402-1408
    # pastes the correct line. An arm keyed on the value "1" would be a no-op.
    worker = os.environ.get("FLEET_WORKER")
    if worker and worker.strip() and not _is_supervisor_shaped(worker):
        raise FleetCliError(
            f"{verb}: refusing -- this is a worker turn (FLEET_WORKER={worker!r}) and "
            f"the supervisor claim is not a worker's to hold (claim-nonce §6.5). "
            f"Escalate to the supervisor session. (A speed-bump, not a security "
            f"boundary: an environment variable is settable by anyone who can run "
            f"this command.)")
    claim = read_incarnation()
    if claim is None:
        raise FleetCliError("no supervisor claim exists -- run `fleet sup-boot` first")
    caller = sid_override or current_caller_session()
    if not caller:
        raise FleetCliError("caller session unknown -- pass --sid or run from a Claude session")

    notices = []
    if claim.get("state") == "released":
        # A released claim is terminal for every verb but `sup-boot` (§6.1
        # rule 1). Decided by its own branch rather than left to fall through
        # to the continuity refusal: a body facing a cleanly released claim is
        # not facing a possible second body, and §5.7's escalation wording
        # would send it to the operator for nothing.
        raise FleetCliError(
            f"{verb}: claim {claim.get('incarnation_id', '?')} was released "
            f"{claim.get('released_at', '?')} -- there is no holder to be. "
            f"Run `fleet sup-boot` to claim afresh.")
    if _claim_is_legacy(claim):
        # §5.3 rule 4 / §9: the path every shipped five-key INCARNATION takes
        # on first contact. Honor today's comparison once, then upgrade.
        if caller != claim.get("session_id"):
            raise FleetCliError(
                f"caller sid {caller} does not hold the claim (holder: "
                f"{claim.get('incarnation_id', '?')} sid {claim.get('session_id')}) -- "
                f"the journal is single-writer, claim-holder-only (spec §4)")
        value = mint_nonce()
        claim["nonce_hash"] = nonce_digest(value)
        claim["nonce_seq"] = 1
        notices.append(f"NONCE: {value}")
        # No pending is minted on the upgrade call: the LIVE generation just
        # delivered is this call's delivery, and minting a pending in the same
        # breath would put two values on one output and make "the most recent
        # generation it was given" ambiguous at the one moment every
        # installation passes through (§5.4(e)'s hazard, at first contact).
        mint = False
    elif _nonce_presentation(claim, nonce) == "pending":
        _acknowledge_pending(claim)                       # rule 2
    elif _nonce_presentation(claim, nonce) == "prior":
        # Rule 3. Valid, and NOT an alarm: the caller holds a pending that a
        # later mint replaced (§5.4(d)). The record is QUIET and distinct in
        # kind from a refusal, so an operator reading the log can tell "the TTL
        # fired under a slow body" from "a second body presented a stale
        # value" -- without `kind` those two are indistinguishable, and the
        # slow body reads as an attack.
        _append_nonce_rejection("superseded-pending", verb, caller, claim, nonce)
    elif _nonce_presentation(claim, nonce) is not None:
        pass                                              # rule 1 (live)
    else:
        _append_nonce_rejection("refused", verb, caller, claim, nonce)
        raise _continuity_refusal(verb, claim)            # rule 5

    # §6.6: restamp on every validated write, so the roster join tracks the
    # body that is actually acting rather than a sid retired by a fork-steer.
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
        claim["heartbeat_at"] = now_iso()
        write_incarnation(claim)
    print(f"checkpointed ({args.kind}) as {claim['incarnation_id']}; heartbeat refreshed")
    _deliver_notices(notices)
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


def cmd_sup_release(args) -> int:
    """`fleet sup-release [--reason TEXT] [--nonce N] [--sid S]` -- claim-nonce
    §6.3 / D3. The verb that produces a RELEASED claim.

    It does NOT delete `supervisor/INCARNATION`; it rewrites it. Deleting
    would leave the absent-claim shape, which says "nobody ever claimed" --
    the released record says "a body held this and gave it up cleanly", and
    that distinction is the whole of incident 3: an operator-authorized stop
    must be distinguishable from a daemon restart. §6.1 rule 1 then reads the
    record and returns `claim` with no seizure and no `SEIZED` entry.

    THE KEY SET IS ENUMERATED BY §6.3 AND WRITTEN AS A LITERAL, never as a
    filtered copy of the live claim. v1 left it open and the gap made a
    released claim indistinguishable from a legacy one (§9): both lack
    `nonce_hash`, so a leftover `session_id` would let the legacy branch honor
    it by sid equality and upgrade it in place -- "released" would stop being
    terminal and whoever matched the recorded sid would resurrect the claim.
    A literal cannot carry a field a future spec adds to the live claim by
    accident; a filtered copy can.

    No mint, and notices discarded, for the reason `sup-handoff-complete`
    already carries one layer over: the claim this call validates ceases to
    exist inside this same lock section, so a generation minted for it would
    be dead on delivery -- and it would be the only `NONCE:` line a supervisor
    ever reads that it must not present.

    Doctrine (`skills/fleet/supervisor.md`): release, THEN stop. The window
    between the two commands is real, which is why §6.1 rule 1 refuses to
    consume a released record whose releaser is still roster-live (B6)."""
    with fleet_lock():
        claim, caller, _ = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-release", mint=False)
        inc = claim["incarnation_id"]
        reason = (getattr(args, "reason", None) or "").strip()
        # Journal FIRST, checkpoint-then-act: the releasing body is still the
        # holder here, and the entry is written under ITS incarnation id --
        # there is no successor to attribute it to. A crash between the two
        # writes leaves the entry without the release, which reads as "a
        # release was attempted"; the reverse would lose the record entirely.
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
        write_incarnation(released)
    print(f"claim {inc} released. Nothing holds the supervisor claim now -- this "
          f"incarnation must EXIT: take no further fleet actions. The next body "
          f"claims fresh via `fleet sup-boot` (no seizure, no page).")
    return 0


def _project_claim(claim, now=None):
    """claim-nonce §5.8's binding build rule: what a VIEW may publish.

    §4.8's receipt showed `sup-status --json` emitting the raw claim dict, so
    every field this spec adds is published by a lock-free view unless a
    redaction step is specified. `nonce_hash`, `pending_nonce_hash` and
    `prior_pending_hash` are omitted; the observables that replace them --
    `nonce_present`, `pending_present`, `pending_age_seconds` (§5.6's
    unacknowledged-pending signal), `nonce_seq`, `lineage_id`, `state` -- are
    published instead.

    An ALLOWLIST, not a denylist. A denylist republishes every field a future
    spec adds, which is precisely how §5.8 came to be needed. The cost is real
    and accepted: a key hand-added to INCARNATION stops appearing in
    `sup-status --json`.

    Pure and never raises: this runs on the view path (`sup-status`, and via
    `supervisor_status_line` the SessionStart hook of every Claude Code
    session on this box)."""
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
    return out


def _project_handshake(hs):
    """§5.8, same rule, the other dict this view dumps: `handoff_token_hash`
    (§6.4) is reported as a presence bit and never published."""
    if hs is None:
        return None
    out = {key: hs.get(key) for key in ("incarnation_id", "session_id", "written_at")}
    out["handoff_token_present"] = bool(hs.get("handoff_token_hash"))
    return out


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
        # §5.8: a PROJECTION, never the raw dicts. The human branch below
        # keeps reading `claim` directly -- it is a hand-written f-string over
        # four named fields that has never held a hash, and §5.8's scope was
        # corrected to exclude it.
        "incarnation": _project_claim(claim),
        "heartbeat_age_seconds": beat_age,
        "handshake": _project_handshake(hs),
        "abort_flag": handoff_abort_flag_path().exists(),
        "nag": supervisor_status_line(),
    }
    if getattr(args, "json", False):
        print(json.dumps(info, indent=2))
        return 0
    if claim is None:
        print("supervisor: no claim" + (" (GOALS active -- start one: `fleet sup-boot`)"
                                        if info["goals_active"] else ""))
    elif claim.get("state") == "released":
        # The same §6.3 defect as `supervisor_status_line`'s, one surface over
        # and operator-facing: a released claim has no `heartbeat_at`, so the
        # human line below would print "heartbeat unreadable" for a clean,
        # planned release. §5.8 scoped its redaction rule away from this
        # f-string; that is a different question and does not exempt it from
        # this one.
        print(f"supervisor: {claim.get('incarnation_id', '?')} RELEASED at "
              f"{claim.get('released_at', '?')} by sid={claim.get('released_by_sid')}"
              + (f" ({claim['reason']})" if claim.get("reason") else "")
              + " -- no holder; `fleet sup-boot` claims fresh")
    else:
        age = f"{beat_age:.0f}s ago" if beat_age is not None else "unreadable"
        print(f"supervisor: {claim.get('incarnation_id', '?')} sid={claim.get('session_id')} "
              f"via {claim.get('claimed_via', '?')}, heartbeat {age}")
    if hs is not None:
        print(f"handshake: {hs.get('incarnation_id')} sid={hs.get('session_id')} (handoff in flight)")
    if info["abort_flag"]:
        print(f"WARNING: aborted-handoff flag present ({handoff_abort_flag_path()})")
    return 0


def _render_successor_task(successor_inc: str, old_inc: str, handoff_token: str) -> str:
    """Successor bootstrap body (task-file bootstrap, contract G8 -- never
    argv for size-unbounded content). Paths rendered .as_posix().

    §6.4: the plaintext `handoff_token` is rendered into step 1's `sup-boot`
    invocation. This file is the ONLY channel that carries it -- the
    predecessor stores only its hash (§5.8), and the file is unlinked on
    complete/abort (§5.9). The successor hashes the token into HANDSHAKE so the
    predecessor can verify the body it dispatched without a sid comparison a
    fork-steer would break."""
    fleet_py = (FLEET_HOME / "bin" / "fleet.py").as_posix()
    # The interpreter that is running fleet right now, not a hardcoded
    # `py -3.13` (a Windows-only launcher): the successor must invoke the
    # same Python this incarnation was launched with, on any platform.
    py = Path(sys.executable).as_posix()
    return f"""You are the claude-fleet supervisor SUCCESSOR, incarnation {successor_inc}.
Your predecessor ({old_inc}) dispatched you mid-handoff (spec docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §4).

Do exactly this, in order:
1. Run: "{py}" {fleet_py} sup-boot --handoff-inc {successor_inc} --handoff-token {handoff_token}
   This prints your boot bundle and writes supervisor/HANDSHAKE (carrying the
   token hash and your own freshly minted generation). It also prints a
   `NONCE:` line -- that is YOUR generation; keep it, you present it on your
   first supervisor verb after the claim transfers. You hold NO claim yet.
2. Take NO spawn/respawn/send/kill/clean actions before claim transfer -- spec §4's double-spawn guard.
3. Poll every ~30s (up to 10 minutes): "{py}" {fleet_py} sup-status --json
   - When incarnation.incarnation_id == "{successor_inc}": the claim is yours. Run:
     "{py}" {fleet_py} sup-checkpoint "claim received via handoff from {old_inc}"
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
    a successor is in flight when none exists.

    SECOND DISPATCH PATH (SPEC §6, defect-A fix wave). This is the ONLY
    `--bg` launch that does not go through `dispatch_bg`, and it cannot:

      * `NAME_RE` is `^[a-z0-9-]+$`, but an incarnation id is
        `inc-<YYYYMMDD>T<HHMMSS>Z-<hex4>` -- the T and Z are uppercase, so
        the choke point's own name guard (the `NAME_RE`/`_SID_SHAPE_RE` check
        opening `dispatch_bg`) refuses it outright;
      * `dispatch_bg` writes the prompt body to `task_file_path(name)`,
        while the successor's body is already written to
        `state/supervisor-handoff-<inc>.md` and journaled BY PATH in the
        HANDOFF-BEGIN entry below -- re-routing would leave two task files
        and a journal entry naming the wrong one;
      * `dispatch_bg`'s single safe wedge-retry re-dispatches the whole
        launch once. For a worker that is correct; for a handoff it means a
        second live successor on one incarnation id -- exactly the
        double-spawn hazard spec §4 exists to prevent.

    So the path stays, but it is SANCTIONED, not a bypass: it carries the
    same `--settings` instance and the same `_worker_env` process identity
    the choke point carries. Both are load-bearing:

      * without `--settings`, the successor runs with NONE of fleet's hooks.
        All four (Stop outcome, Stop mailbox, PostToolUse mailbox,
        PostCompact journal) degrade cleanly to SID-keyed writes for a
        session with no registry record -- and the successor's sid is
        exactly the handle `sup-handoff-complete --expect-sid` /
        `sup-handoff-abort --successor-sid` already print and consume. The
        `_require_instance_settings()` pre-flight is the same doctrine
        cmd_spawn applies: `claude` silently IGNORES a --settings path that
        does not exist, so an unrendered instance would put the hookless
        successor back with no error anywhere. It runs before the lock so a
        refusal writes neither the journal entry nor the task file;
      * without `env=_worker_env(name)`, the successor inherits the OLD
        holder's `CLAUDE_CODE_SESSION_ID`, which `cmd_sup_boot` reads
        directly (`caller_sid`) and writes into the HANDSHAKE -- so the
        successor would hand back the predecessor's sid and
        `sup-handoff-complete` would refuse on the §4 id mismatch, wedging
        the handoff. (Whether the daemon actually propagates the launcher's
        environment into the hosted session is UNOBSERVED here; the strip
        is the same defense `dispatch_bg` applies at every worker launch,
        and costs nothing if the daemon already isolates.)

    NOT carried, deliberately: `--add-dir`. `dispatch_bg` needs it because
    `tasks_dir()` sits outside the worker's cwd; this dispatch runs with
    `cwd=FLEET_HOME` and its task file is `FLEET_HOME/state/...`, already
    inside the authorized root. `--setting-sources` likewise: it is a
    per-worker persisted value and a successor has no registry record.

    Mode flags ARE carried (B4/D6 fix wave). `dispatch_bg` ends every worker
    argv with `mode_flags(mode)` and `fleet spawn` defaults that to `dontask`;
    this path emitted a permission flag only when the operator typed
    `--permission-mode`, so the default was claude's own. The successor's
    bootstrap opens with a Bash call (`sup-boot --handoff-inc`), and a headless
    `--bg` session cannot answer a permission prompt -- it wedges until the
    300s handshake timeout. That is the T12 hang class. The default is
    `SUCCESSOR_DEFAULT_MODE`, deliberately the SAME fleet mode name a worker
    gets, not a bespoke one; an explicit `--permission-mode` still wins.

    ONE mode vocabulary (G3 fix wave). `--permission-mode` takes a FLEET mode
    name -- argparse-constrained to `MODE_FLAGS`, the same keyspace `fleet
    spawn --mode` uses -- and BOTH the explicit and default branches render it
    through `mode_flags()`. Previously the explicit branch forwarded a raw
    claude mode string while the default branch mapped a fleet name, so one
    argument meant two different things depending on which branch produced it,
    and a raw spelling like `acceptEdits` parsed cleanly and then died inside
    `mode_flags` at dispatch time. It is now refused at the parser.

    BOTH external pre-flights run before the lock (B5 fix wave).
    `resolve_claude_executable` is the same class of check as
    `_require_instance_settings` -- a missing external prerequisite -- but ran
    after the journal write, the task-file write, and the prior abort flag's
    deletion, with no `_abort_flag` guard on its raise. A `claude` that dropped
    off PATH therefore left HANDOFF-BEGIN journaled forever, a stale task file
    in `state/`, the previous handoff's abort flag deleted, no successor, and
    nothing for doctor to see -- falsifying this docstring's own promise that
    both failure paths raise the flag. Moving one pre-flight above the lock and
    leaving its twin behind is this repo's named recurring class; the twin is
    now beside it. (`_fetch_agents_roster`, the only other post-lock caller,
    catches `ClaudeNotFoundError` and returns `(False, reason)` -- it cannot
    raise through here.)"""
    _require_instance_settings()
    try:
        exe = resolve_claude_executable(which=which)
    except ClaudeNotFoundError as exc:
        raise FleetCliError(f"{exc} -- nothing dispatched; claim unchanged, duty continues")
    with fleet_lock():
        # §5.3: `sup-handoff-begin` does NOT mint a continuity PENDING. Its
        # dispatch runs outside the lock by F4 doctrine, so a pending minted in
        # this critical section would be exposed to exactly the failure §5.4(b)
        # exists to prevent -- and it is handing the claim over regardless. So
        # `mint=False`.
        #
        # The validator's `notices` are NOT discarded here, unlike the old
        # begin. §6.4 makes this a claim WRITE (the token hash below), so
        # whatever generation the validator settled on is now committed -- and
        # for a legacy predecessor whose first new-code contact is this verb,
        # that generation is its first-contact upgrade (§9), which belongs to
        # the predecessor and it must hold until complete/abort. Discarding it
        # once it is persisted would lock the resuming predecessor out. In the
        # common case -- a healthy predecessor presenting its live generation
        # -- rule 1 leaves `notices` empty and nothing is printed.
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-begin", mint=False)
        successor_inc = mint_incarnation_id()
        # §6.4: mint the one-shot handoff token, stamp only its HASH into this
        # body's own claim (so a predecessor fork-steer mid-handoff does not
        # lose it, and so INCARNATION never becomes a place the token can be
        # read from -- §5.8), and render the PLAINTEXT into the successor's
        # task file, which is the only channel that carries it and is unlinked
        # on complete/abort (§5.9). This is a claim write, unlike the old
        # begin: it adds exactly one field and commits it here under the lock.
        handoff_token = mint_nonce()
        claim["handoff_token_hash"] = nonce_digest(handoff_token)
        write_incarnation(claim)
        task_path = handoff_task_file_path(successor_inc)
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text(
            _render_successor_task(successor_inc, claim["incarnation_id"], handoff_token),
            encoding="utf-8")
        supervisor_journal_append("HANDOFF-BEGIN", claim["incarnation_id"], caller,
                                  f"successor={successor_inc} task={task_path.as_posix()}")
        try:
            # A new attempt supersedes any previous aborted handoff.
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

    roster_fetch = lambda: _fetch_agents_roster(which=which, run=run)  # noqa: E731
    pre_ok, pre_payload = roster_fetch()
    # Same unhashable-sessionId guard as dispatch_bg's pre-snapshot above.
    pre_sids = {e.get("sessionId") for e in (pre_payload if pre_ok else [])
                if isinstance(e, dict) and isinstance(e.get("sessionId"), str)}
    name = _successor_worker_name(successor_inc)
    # Same value dispatch_bg's --settings default resolves to (the RENDERED
    # instance, never the template): the successor gets fleet's hooks. See
    # this function's docstring for why this path is not dispatch_bg.
    argv = [exe, "--bg", "-n", name,
            "--settings", instance_settings_path().as_posix()]
    if getattr(args, "model", None):
        argv += ["--model", args.model]
    # B4/D6: never leave the mode to claude's default -- see the docstring.
    # G3: ONE vocabulary. `--permission-mode` takes a FLEET mode name
    # (argparse-constrained to MODE_FLAGS, same keyspace `fleet spawn --mode`
    # uses) and both the explicit and default branches render it through
    # `mode_flags`, so exactly one mode opinion reaches the argv and a raw
    # claude spelling is refused at the parser instead of raising ValueError
    # from inside the dispatch.
    argv += mode_flags(getattr(args, "permission_mode", None) or SUCCESSOR_DEFAULT_MODE)
    argv.append(f"Read {task_path.as_posix()} and follow it exactly.")
    try:
        proc = run(argv, cwd=str(FLEET_HOME), env=_worker_env(name),
                   capture_output=True, text=True,
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
    """`fleet sup-handoff-complete --expect-inc I [--expect-sid S] [--sid ...]`.

    §6.4 / D4: verification turns on the TOKEN, not the sid. The HANDSHAKE must
    carry the incarnation id the old side minted AND a `handoff_token_hash`
    equal to the one begin stamped into this claim. `--expect-sid` becomes
    OPTIONAL: when passed it is checked, and a mismatch is a loud warning
    naming the fork, not a refusal -- a successor that fork-steered between the
    SUCCESSOR-SID print and this call still holds the token, so refusing on the
    sid would wedge a legitimate handoff on the exact failure this redesign
    removes (the fork-steer root cause, third instance). Journal
    HANDOFF-COMPLETE first (old is still holder), then transfer."""
    with fleet_lock():
        # No mint, and continuity notices discarded: the claim this call
        # validates ceases to exist inside this same lock section (the literal
        # below replaces it), so a generation minted for it would be dead on
        # delivery. The successor already minted ITS generation at its own
        # sup-boot (§6.4) and it rides in on the HANDSHAKE.
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
            # The fork case, and the whole point of the token: a successor that
            # is not the body begin dispatched cannot produce the token, so it
            # cannot forge a matching HANDSHAKE hash. `not expected_hash` is
            # fail-closed for a claim that never went through a token-minting
            # begin (an old-code predecessor): with nothing to verify against,
            # refuse rather than transfer on an absent equality.
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
        # Third dict-literal writer (§9). `lineage_id` is CARRIED, never
        # re-minted: a handoff is a planned succession with the predecessor
        # alive to vouch, so provenance continues across it (§6.2), and every
        # worker the predecessor spawned stays not-foreign to the successor.
        #
        # §6.4: the successor's OWN generation reaches the claim through
        # HANDSHAKE (`nonce_hash`, minted at the successor's sup-boot). Carrying
        # it here is what makes the transferred claim a live claim rather than a
        # legacy one -- the successor's first supervisor verb proves continuity
        # on the value its own boot delivered, with no in-place upgrade. The
        # token hash is the PREDECESSOR's and is deliberately not carried.
        new_claim = {"incarnation_id": args.expect_inc,
                     "session_id": successor_sid,
                     "claimed_at": now_iso(), "heartbeat_at": now_iso(),
                     "claimed_via": "handoff",
                     "lineage_id": claim.get("lineage_id")}
        succ_nonce_hash = hs.get("nonce_hash")
        if succ_nonce_hash:
            new_claim["nonce_hash"] = succ_nonce_hash
            new_claim["nonce_seq"] = 1
        write_incarnation(new_claim)
        try:
            handshake_path().unlink()
        except FileNotFoundError:
            pass
        # §5.9: the task file carries the plaintext token; unlink it here.
        try:
            handoff_task_file_path(args.expect_inc).unlink()
        except FileNotFoundError:
            pass
    if sid_warning:
        print(sid_warning)
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
        # The old side RESUMES duty here (it rewrites its own heartbeat
        # below), so it mints and is delivered a fresh generation like any
        # other continuing verb.
        claim, caller, notices = _require_claim_holder(
            getattr(args, "sid", None), nonce=getattr(args, "nonce", None),
            verb="sup-handoff-abort")
        hs = read_handshake()
        aborted_inc = None
        if hs is not None:
            if hs.get("session_id") != args.successor_sid:
                raise FleetCliError(
                    f"--successor-sid does not match HANDSHAKE sid {hs.get('session_id')} -- "
                    f"refusing to stop an unrelated session")
            aborted_inc = hs.get("incarnation_id")
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
        # §5.9: the aborted successor's task file carries the plaintext token;
        # unlink it here too (best-effort, keyed on the HANDSHAKE's inc when we
        # have one -- an abort taken off the flag alone does not know the
        # successor inc, and the doctor NOTE is the backstop for that path).
        if aborted_inc:
            try:
                handoff_task_file_path(aborted_inc).unlink()
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
        # The handoff this body started is over; its token hash is spent. Drop
        # it so a later verb never re-reads a stale token (§6.4). A fresh begin
        # overwrites it regardless; clearing it keeps the resumed claim clean.
        claim.pop("handoff_token_hash", None)
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
            # claim-nonce §6.3's BINDING BUILD RULE, and it is binding because
            # of who reads this line. §6.3 removes `heartbeat_at` from a
            # released claim -- correct for the claim -- and a released claim
            # is not None, so without this branch the no-claim branch above is
            # skipped and the KeyError arm below fires. Per §4.8 that arm's
            # text reaches `fleet doctor`, `sup-status`, and
            # `bin/hooks/sessionstart_fleet.py`, which runs in EVERY Claude
            # Code session on this machine: the NORMAL outcome of a correct,
            # planned `fleet sup-release` would be a persistent machine-wide
            # "inspect supervisor/INCARNATION" corruption warning.
            #
            # The age is best-effort and its failure must not fall through to
            # that same arm -- a branch that re-introduces the defect it fixes
            # is worse than no branch, because it fixes the tested case only.
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
        return f"SUPERVISOR: {inc} live, heartbeat {age / 60:.0f}m ago."
    except Exception:  # noqa: BLE001 -- view: never raises
        return None


def _nonce_pending_age_note(claim, now=None):
    """§5.6's other observable: `unacknowledged pending age`.

    §5.4(e)'s silent miss produces NO refusal at all. Rule 1 accepts the live
    generation forever, so a body that only ever presents `live` -- because it
    read `NONCE: unchanged` in a batch, because a verb's output was truncated,
    or because a compaction dropped the newest line and kept an older one --
    never acknowledges, `nonce_seq` never advances, and two bodies of one
    lineage both validate indefinitely with no refusal, no record, and doctor
    green. That is strictly worse than a false alarm.

    A pending outstanding past NONCE_PENDING_STALE_MULTIPLE TTLs is the signal
    that the presenter obligation is being violated and the detection property
    has degraded. It is a NOTE, not a health failure: nothing is broken, the
    mechanism has merely stopped detecting."""
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
    """Spec §4 nag, doctor surface.

    Was ALWAYS ok=True ("the nag is advisory"). claim-nonce §5.6 changes
    exactly ONE condition: a `refused` record in the last 24 h. A rejection is
    not a nag -- it is evidence of a second body. Everything else here stays
    advisory, `superseded-pending` included: §5.4(d) says the body holding a
    superseded pending is most likely the LEGITIMATE one that spent longer
    than a TTL thinking, and flipping the health check on it would train an
    operator to ignore the one signal that does mean two bodies.

    Never raises: this is a doctor row, and a corrupt evidence file must not
    take the health check out with it."""
    line = supervisor_status_line()
    if line is None:
        return ("supervisor-claim", True, "GOALS absent or dormant -- no supervisor expected")
    parts = [line]
    ok = True
    try:
        recent = _recent_nonce_rejections()
        refused = [r for r in recent if r.get("kind") == "refused"]
        superseded = [r for r in recent if r.get("kind") == "superseded-pending"]
        if refused:
            ok = False
            last = refused[-1]
            parts.append(
                f"{len(refused)} continuity refusal(s) in the last "
                f"{NONCE_REJECTION_WINDOW_SECONDS // 3600}h (latest: {last.get('verb')} "
                f"at {last.get('ts')}, expected generation {last.get('expected_seq')}) -- "
                f"a second body of this lineage may be acting; census the sessions "
                f"(state/{nonce_rejection_log_path().name})")
        if superseded:
            # Break-gate residual F3: a `superseded-pending` record CANNOT be
            # produced by a protocol-conforming single body -- that body would
            # have to present an older value after a newer one, which §5.3's
            # presenter obligation forbids. So the record implies EITHER a
            # second presenter OR a violated obligation, and both are
            # conditions this design wants seen. NOTE rather than `ok=False`
            # is right (it is not proof of a second body, and §5.4(d) says the
            # body holding a superseded pending is most likely the legitimate
            # slow one) -- but "quiet" must not read as "benign", so the
            # wording names both possibilities rather than only the benign one.
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
    # §5.9 backstop: a `supervisor-handoff-*.md` carries the plaintext handoff
    # token and is unlinked by complete/abort. Unlink is the mechanism; this
    # NOTE catches the crash-before-unlink paths. A NOTE, not a health
    # failure -- an orphan token file is a hygiene residue, not a broken
    # supervisor; and it is best-effort, since a view/doctor row must never
    # raise on a stat.
    try:
        orphans = []
        for f in state_dir().glob("supervisor-handoff-*.md"):
            try:
                fage = time.time() - f.stat().st_mtime
            except OSError:
                continue
            if fage > SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS:
                orphans.append(f.name)
        if orphans:
            parts.append(
                f"NOTE: {len(orphans)} orphaned successor task file(s) past the handoff "
                f"timeout ({', '.join(sorted(orphans))}) -- residue from a handoff that "
                f"crashed before unlinking; each carries a spent handoff token, safe to "
                f"delete manually (claim-nonce §5.9)")
    except OSError:
        pass
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
    p_init.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
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
    p_spawn.add_argument("--nonce", help=GATE_NONCE_ARG_HELP)
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
                             help="explicit FLEET_HOME override; the scheduled task "
                                  "always passes this (Task Scheduler has no operator env)")

    sub.add_parser("doctor", help="run fleet health checks")

    p_supboot = sub.add_parser("sup-boot", help="supervisor boot ritual: epoch check, claim decision, boot bundle (spec §4)")
    p_supboot.add_argument("--sid", help="override caller session id (default: CLAUDE_CODE_SESSION_ID)")
    p_supboot.add_argument("--nonce", help=NONCE_ARG_HELP)
    p_supboot.add_argument("--handoff-inc", dest="handoff_inc",
                           help="handoff-successor mode: write HANDSHAKE with this incarnation id; no claim action")
    p_supboot.add_argument("--handoff-token", dest="handoff_token",
                           help="handoff-successor mode: the one-shot token from the "
                                "predecessor's task file; its hash is written into HANDSHAKE "
                                "so complete can verify this body without a sid comparison (§6.4)")

    p_supckpt = sub.add_parser("sup-checkpoint", help="append a supervisor journal checkpoint (claim holder only) + refresh heartbeat")
    p_supckpt.add_argument("body", help="checkpoint text, or @file")
    p_supckpt.add_argument("--kind", choices=["CHECKPOINT", "PROPOSAL"], default="CHECKPOINT")
    p_supckpt.add_argument("--sid", help="override caller session id")
    p_supckpt.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_supbeat = sub.add_parser("sup-heartbeat", help="refresh the supervisor claim heartbeat (no journal write)")
    p_supbeat.add_argument("--sid", help="override caller session id")
    p_supbeat.add_argument("--nonce", help=NONCE_ARG_HELP)

    # claim-nonce §6.3. PLAIN FORM ONLY -- there is deliberately no `--force`
    # / `--confirm-inc` pair here. v1 added one for the case incident 3
    # presented (a body already `claude stop`ped, unable to release itself) and
    # thereby created a fully-sanctioned seizure of a LIVE claim whose only
    # input is printed by a read-only view. The unplanned case resolves itself
    # instead: roster-gone plus a heartbeat aged past
    # SUPERVISOR_CLAIM_STALE_SECONDS becomes `seize` with a `SEIZED` entry.
    # §12 O2 keeps that removal in front of the operator.
    p_suprel = sub.add_parser("sup-release",
                              help="release the supervisor claim cleanly (claim holder only); "
                                   "the next sup-boot claims fresh with no seizure")
    p_suprel.add_argument("--reason", help="short note recorded in the journal and the claim")
    p_suprel.add_argument("--sid", help="override caller session id")
    p_suprel.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_supstat = sub.add_parser("sup-status", help="read-only supervisor claim/handshake status")
    p_supstat.add_argument("--json", action="store_true")

    p_suphb = sub.add_parser("sup-handoff-begin", help="dispatch a handoff successor (claim holder only)")
    p_suphb.add_argument("--model", help="model for the successor session")
    p_suphb.add_argument("--permission-mode", dest="permission_mode",
                         choices=list(MODE_FLAGS),
                         help="fleet mode name for the successor session "
                              f"(default: {SUCCESSOR_DEFAULT_MODE})")
    p_suphb.add_argument("--sid", help="override caller session id")
    p_suphb.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_suphc = sub.add_parser("sup-handoff-complete", help="verify HANDSHAKE and transfer the claim")
    p_suphc.add_argument("--expect-inc", dest="expect_inc", required=True)
    # §6.4: optional. The token verifies the successor; --expect-sid is
    # observability, and a mismatch is a warning naming the fork, not a refusal.
    p_suphc.add_argument("--expect-sid", dest="expect_sid",
                         help="optional: warn (do not refuse) if the HANDSHAKE sid differs")
    p_suphc.add_argument("--sid", help="override caller session id")
    p_suphc.add_argument("--nonce", help=NONCE_ARG_HELP)

    p_supha = sub.add_parser("sup-handoff-abort", help="abort a handoff: stop the limbo successor, resume duty")
    p_supha.add_argument("--successor-sid", dest="successor_sid", required=True)
    p_supha.add_argument("--sid", help="override caller session id")
    p_supha.add_argument("--nonce", help=NONCE_ARG_HELP)

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
        if args.command == "sup-release":
            return cmd_sup_release(args)
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
    except SupervisorContinuityError as exc:
        # claim-nonce §4.13(b): AHEAD of the generic arm below, which collapses
        # every FleetCliError to exit 1. Ordering is the whole seam -- behind
        # it, the subclass is caught by its parent and the distinct code is
        # unreachable.
        print(f"fleet: {exc}", file=sys.stderr)
        return SUPERVISOR_CONTINUITY_RC
    except (FleetCliError, ClaudeNotFoundError, ValueError, FleetLockTimeout,
            UnsupportedPlatformError) as exc:
        print(f"fleet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
