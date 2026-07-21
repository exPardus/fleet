"""M-E: wedged / unreachable Claude background daemon.

Covers the 2026-07-21 substrate outage (docs/specs/native-substrate.md, Known
hazards, the stale-`daemon.lock` row): a daemon died, Windows recycled its PID
onto an unrelated service, and every subsequent daemon start lost a lock race to
a process that was not a daemon. `--bg` dispatch was dead machine-wide for ~16h
and `fleet doctor` reported 21 PASS / 0 FAIL.

D1 pins `_doctor_check_daemon_wedge`; D2 pins the dispatch-failure
classification. Every fixture is fabricated or a verbatim transcription of the
manager's receipts -- nothing in this file reads or writes the real
`~/.claude/`.
"""
import json
import re
import subprocess
import types
from pathlib import Path

import pytest

import fleet


# --- fixtures reproducing the incident's own artifacts -----------------------

# `~/.claude/daemon.lock` as captured 2026-07-21 (backed up by the manager at
# .../scratchpad/daemon.lock.stale-pid15740.bak). Verbatim except for the
# elided path strings.
INCIDENT_LOCK = {
    "pid": 15740,
    "version": "2.1.216",
    "jsonPath": "...",
    "logPath": "...",
    "startedAt": 1784589928352,          # 2026-07-20T23:25:28.352Z
    "origin": "transient",
    "spawnedBy": {"label": "claude", "cwd": "C:\\proga\\claude-fleet", "pid": 16144},
    "procStart": "639202047274516770",   # .NET ticks, LOCAL -- deliberately unused
    "launchTarget": "C:\\Users\\Techn\\.local\\bin\\claude.exe",
    "processWrapper": "",
}

# `~/.claude/daemon.log` tail, verbatim from the incident (the em-dash is the
# vendor's).
INCIDENT_LOG_TAIL = (
    "[2026-07-20T23:25:27.750Z] [supervisor] ─── daemon start ─── "
    "version=2.1.216 pid=15740 origin=transient\n"
    "[2026-07-21T15:07:01.348Z] [supervisor] ─── daemon start ─── "
    "version=2.1.216 pid=34724 origin=transient\n"
    "[2026-07-21T15:07:01.868Z] [supervisor] another daemon won the lock race "
    "(pid=15740) — exiting\n"
)

# The real `--bg` stderr fleet echoed during the outage, verbatim including the
# `Starting background service` prefix line.
INCIDENT_BG_STDERR = (
    "Starting background service\n"
    "Couldn't reach the background service (background service did not become "
    "reachable within 45s) - run 'claude daemon status'"
)


def _write_pair(tmp_path, lock, log_text):
    lock_path = tmp_path / "daemon.lock"
    log_path = tmp_path / "daemon.log"
    if lock is not None:
        lock_path.write_text(
            lock if isinstance(lock, str) else json.dumps(lock), encoding="utf-8")
    if log_text is not None:
        log_path.write_text(log_text, encoding="utf-8")
    return lock_path, log_path


def _refusal(ts, pid):
    return (f"[{ts}] [supervisor] another daemon won the lock race "
            f"(pid={pid}) — exiting\n")


def _check(tmp_path, lock, log_text):
    lock_path, log_path = _write_pair(tmp_path, lock, log_text)
    return fleet._doctor_check_daemon_wedge(lock_path=lock_path, log_path=log_path)


# --- D1: the FAIL direction --------------------------------------------------

class TestDaemonWedgeFails:
    def test_the_2026_07_21_incident_fails(self, tmp_path):
        """The one case this check exists for. Three refusals naming the
        lock's own pid, spanning ~16h, all long after the lock was written."""
        log = INCIDENT_LOG_TAIL
        # The incident ran for ~16h; the log carried the refusal on every
        # start attempt. Three is the threshold.
        log += _refusal("2026-07-21T16:40:02.100Z", 15740)
        log += _refusal("2026-07-21T18:12:44.905Z", 15740)
        name, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert name == "daemon-wedge"
        assert ok is False, msg

    def test_fail_message_names_the_lock_pid_and_the_remedy(self, tmp_path):
        log = (INCIDENT_LOG_TAIL
               + _refusal("2026-07-21T16:40:02.100Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False
        assert "15740" in msg
        assert "daemon.lock" in msg
        # The remedy must be copy-pasteable and must say stop --any is NOT enough.
        assert "daemon stop --any" in msg
        assert re.search(r"not sufficient|does not (clear|remove)", msg, re.I), msg

    def test_fails_when_the_refusals_are_the_only_log_content(self, tmp_path):
        """Log rotation can drop the `daemon start` line; the refusals alone
        still carry the verdict."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01.868Z",
            "2026-07-21T16:40:02.100Z",
            "2026-07-21T18:12:44.905Z"))
        _n, ok, _msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False

    def test_fractionless_timestamps_still_fail(self, tmp_path):
        """3.10 floor: the parser must not lean on `fromisoformat`, and must
        take a `Z` stamp with or without a fractional part."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01Z",
            "2026-07-21T16:40:02Z",
            "2026-07-21T18:12:44Z"))
        _n, ok, _msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False


# --- D1: every PASS direction (a false FAIL is worse than a missed wedge) ----

class TestDaemonWedgePasses:
    def test_absent_lock_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, None, INCIDENT_LOG_TAIL)
        assert ok is True, msg

    def test_absent_log_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, None)
        assert ok is True, msg

    def test_unparseable_lock_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, "{not json", INCIDENT_LOG_TAIL)
        assert ok is True, msg

    @pytest.mark.parametrize("lock", [
        {"version": "2.1.216", "startedAt": 1784589928352},        # no pid
        {"pid": 15740},                                            # no startedAt
        {"pid": "15740", "startedAt": 1784589928352},              # pid not an int
        {"pid": True, "startedAt": 1784589928352},                 # bool is not a pid
        {"pid": 15740, "startedAt": "yesterday"},                  # startedAt not numeric
        {"pid": 15740, "startedAt": None},
        ["not", "an", "object"],
    ])
    def test_field_shape_drift_passes(self, tmp_path, lock):
        log = (INCIDENT_LOG_TAIL
               + _refusal("2026-07-21T16:40:02.100Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        _n, ok, msg = _check(tmp_path, lock, log)
        assert ok is True, msg

    def test_healthy_log_with_no_refusals_passes(self, tmp_path):
        log = ("[2026-07-20T23:25:27.750Z] [supervisor] daemon start "
               "version=2.1.216 pid=15740 origin=transient\n")
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_genuine_startup_race_passes(self, tmp_path):
        """Two clients start a supervisor at the same instant; the loser logs
        the refusal within a second of the winner taking the lock. Normal."""
        log = (INCIDENT_LOG_TAIL.splitlines(keepends=True)[0]
               + _refusal("2026-07-20T23:25:28.900Z", 15740)
               + _refusal("2026-07-20T23:25:29.010Z", 15740)
               + _refusal("2026-07-20T23:25:29.400Z", 15740))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_late_but_bursted_refusals_pass(self, tmp_path):
        """Three clients race a HEALTHY long-lived daemon hours into its life.
        Late, but they span under a second -- not a wedge."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01.100Z",
            "2026-07-21T15:07:01.480Z",
            "2026-07-21T15:07:01.868Z"))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_refusals_naming_a_different_pid_pass(self, tmp_path):
        """History from a PREVIOUS lock (already cleared) must not indict the
        lock currently held -- the check self-clears after the remedy."""
        log = "".join(_refusal(ts, 99999) for ts in (
            "2026-07-21T15:07:01.868Z",
            "2026-07-21T16:40:02.100Z",
            "2026-07-21T18:12:44.905Z"))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_two_late_refusals_are_under_threshold(self, tmp_path):
        log = (_refusal("2026-07-21T15:07:01.868Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_undated_refusal_lines_pass(self, tmp_path):
        """A refusal fleet cannot date is INDETERMINATE, never evidence."""
        log = ("[supervisor] another daemon won the lock race (pid=15740) - exiting\n" * 5)
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_unreadable_log_directory_passes(self, tmp_path):
        """`_read_tail_lines` swallows OSError; a log path that is a directory
        must degrade to a PASS-note, not a crash or a FAIL."""
        (tmp_path / "daemon.log").mkdir()
        (tmp_path / "daemon.lock").write_text(json.dumps(INCIDENT_LOCK), encoding="utf-8")
        _n, ok, msg = fleet._doctor_check_daemon_wedge(
            lock_path=tmp_path / "daemon.lock", log_path=tmp_path / "daemon.log")
        assert ok is True, msg


# --- D1: the hard constraints ------------------------------------------------

class TestDaemonWedgeConstraints:
    def test_check_spawns_no_subprocess(self, tmp_path, monkeypatch):
        """HARD CONSTRAINT: the probe must not be able to start a daemon. The
        cheapest possible proof is that it shells out to nothing at all."""
        def _boom(*a, **kw):
            raise AssertionError("_doctor_check_daemon_wedge shelled out")
        monkeypatch.setattr(subprocess, "run", _boom)
        monkeypatch.setattr(subprocess, "Popen", _boom)
        log = (INCIDENT_LOG_TAIL
               + _refusal("2026-07-21T16:40:02.100Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        _n, ok, _msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False

    def test_check_mutates_nothing(self, tmp_path):
        """NEVER writes under ~/.claude: byte-for-byte and mtime-for-mtime."""
        log = (INCIDENT_LOG_TAIL
               + _refusal("2026-07-21T16:40:02.100Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        lock_path, log_path = _write_pair(tmp_path, INCIDENT_LOCK, log)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (lock_path, log_path)}
        listing_before = sorted(p.name for p in tmp_path.iterdir())
        fleet._doctor_check_daemon_wedge(lock_path=lock_path, log_path=log_path)
        assert {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in (lock_path, log_path)} == before
        assert sorted(p.name for p in tmp_path.iterdir()) == listing_before

    def test_default_paths_resolve_under_the_claude_home(self):
        """Portability: `Path.home()/.claude` is the vendor's config dir on
        Windows, macOS and Linux alike -- no os.name branch anywhere."""
        assert fleet.claude_daemon_lock_path().name == "daemon.lock"
        assert fleet.claude_daemon_lock_path().parent.name == ".claude"
        assert fleet.claude_daemon_log_path().name == "daemon.log"
        assert fleet.claude_daemon_log_path().parent.name == ".claude"

    def test_registered_with_the_other_doctor_checks(self, tmp_path, monkeypatch, capsys):
        """A check nobody runs is not a check -- that IS the outage's lesson
        (21 PASS / 0 FAIL while dispatch was dead machine-wide)."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        (tmp_path / "state").mkdir()
        log = (INCIDENT_LOG_TAIL
               + _refusal("2026-07-21T16:40:02.100Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        lock_path, log_path = _write_pair(tmp_path, INCIDENT_LOCK, log)
        monkeypatch.setattr(fleet, "claude_daemon_lock_path", lambda: lock_path)
        monkeypatch.setattr(fleet, "claude_daemon_log_path", lambda: log_path)
        rc = fleet.cmd_doctor(types.SimpleNamespace(), which=lambda _: None,
                              run=lambda *a, **kw: None)
        out = capsys.readouterr().out
        assert "[FAIL] daemon-wedge:" in out, out
        assert rc != 0


# --- D2: dispatch-failure classification -------------------------------------

@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _run_failing(stderr, rc=1):
    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(returncode=rc, stdout="", stderr=stderr)
    return fake_run


class TestDispatchUnreachableService:
    def test_unreachable_service_is_named_not_echoed(self, native_home):
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_run_failing(INCIDENT_BG_STDERR),
                              which=lambda _: "claude", sleep=lambda s: None,
                              roster_fetch=lambda: (True, []))
        msg = str(exc.value)
        assert "daemon.lock" in msg
        assert "fleet doctor" in msg
        assert "daemon stop --any" in msg
        assert re.search(r"not sufficient|does not (clear|remove)", msg, re.I), msg

    def test_the_vendor_string_is_still_carried(self, native_home):
        """Diagnosis must ADD to the raw string, never replace it -- the next
        wording drift is only findable if the bytes survive."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_run_failing(INCIDENT_BG_STDERR),
                              which=lambda _: "claude", sleep=lambda s: None,
                              roster_fetch=lambda: (True, []))
        assert "Couldn't reach the background service" in str(exc.value)

    def test_the_prefix_line_alone_does_not_trigger(self, native_home):
        """`Starting background service` is printed on every healthy dispatch
        too -- it must never be the matcher."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_run_failing("Starting background service\nboom"),
                              which=lambda _: "claude", sleep=lambda s: None,
                              roster_fetch=lambda: (True, []))
        assert "daemon.lock" not in str(exc.value)

    def test_unrelated_failure_keeps_the_plain_shape(self, native_home):
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_run_failing("permission denied"),
                              which=lambda _: "claude", sleep=lambda s: None,
                              roster_fetch=lambda: (True, []))
        msg = str(exc.value)
        assert "permission denied" in msg and "daemon.lock" not in msg

    @pytest.mark.parametrize("stderr", [
        "Couldn't reach the background service",
        "background service did not become reachable within 45s",
        "COULDN'T REACH THE BACKGROUND SERVICE (whatever)",
    ])
    def test_both_halves_of_the_shape_match_independently(self, native_home, stderr):
        """Vendor surface: either half alone is enough, so a reworded wrapper
        or a changed timeout still classifies."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_run_failing(stderr), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=lambda: (True, []))
        assert "daemon.lock" in str(exc.value)

    def test_stdout_only_failure_also_classifies(self, native_home):
        def fake_run(argv, **kwargs):
            return types.SimpleNamespace(
                returncode=1, stdout=INCIDENT_BG_STDERR, stderr="")
        with pytest.raises(fleet.NativeDispatchError) as exc:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                              which=lambda _: "claude", sleep=lambda s: None,
                              roster_fetch=lambda: (True, []))
        assert "daemon.lock" in str(exc.value)
