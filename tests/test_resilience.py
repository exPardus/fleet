"""Unit tests for resilience surfaces that survived the native-substrate
pivot: doctor checks, resume-limited sweep logic, limited-park surfacing,
cost-coercion hardening, and the destructive-clean file sweep. The legacy
Popen respawn/kill/clean state machines were deleted with the legacy
dispatch path (pivot spec §6, M-C); their native counterparts are covered
in test_native.py.

Same discipline as test_steering.py / test_cli.py: no real claude process
is invoked in the state-machine tests -- every test injects a fake run /
which / roster fetch. The doctor hook-smoke checks are the one deliberate
exception (SPEC's "end-to-end" requirement): those run the real hook
scripts as real subprocesses against a scratch temp FLEET_HOME, mirroring
tests/test_hooks.py's own technique.
"""
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    settings = tmp_path / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    return tmp_path


def _parse(ctime_iso):
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _tzdata_available() -> bool:
    """ME-UL-REVIEW-2026-07-21.md M2: `zoneinfo` is stdlib but its DATA is
    not on Windows (no system tz database -- see D1/`_doctor_check_tzdata`);
    on this host it resolves only by coincidence of an unrelated project's
    `tzdata` pip package. Tests that need a REAL named-zone resolution
    (as opposed to testing the null-park failure path, which mocks
    `zoneinfo.ZoneInfo` and needs no real data) skip rather than fail on a
    box without it -- a clean box is a valid environment, not a broken one."""
    import zoneinfo
    try:
        zoneinfo.ZoneInfo("America/New_York")
        return True
    except Exception:
        return False


_TZDATA_SKIP_REASON = "requires real tz data (tzdata pip package or a system tz database)"


ALIVE_CTIME = "2026-07-07T12:00:00Z"


def _alive_info(pid):
    return ("claude.exe", _parse(ALIVE_CTIME))


def _dead_info(pid):
    return None


class FakeStdin:
    def __init__(self, raise_on_write=None):
        self.written = b""
        self.closed = False
        self._raise_on_write = raise_on_write

    def write(self, data):
        if self._raise_on_write is not None:
            raise self._raise_on_write
        self.written += data

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, pid, stdin=None, poll_returns=None):
        self.pid = pid
        self.stdin = stdin if stdin is not None else FakeStdin()
        self._poll_returns = poll_returns

    def poll(self):
        return self._poll_returns


def _fake_popen(proc, calls=None):
    def popen(argv, **kwargs):
        if calls is not None:
            calls.append(("launch", argv, kwargs))
        return proc
    return popen


def _seed_worker(name, status=None, cwd=None, mode="dontask", model=None,
                 sid=None, token_ceiling=None, **_ignored):
    """Save a single native-shaped worker registry record."""
    if cwd is None:
        cwd = str(fleet.FLEET_HOME)
    sid = sid or str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, cwd, "some task", mode, model=model,
                                  token_ceiling=token_ceiling, dispatch_kind="bg")
    rec["last_dispatch_at"] = fleet.now_iso()
    if status is not None:
        rec["status"] = status
    data = {"workers": {}}
    try:
        data = fleet.load_registry()
    except Exception:
        pass
    data["workers"][name] = rec
    fleet.save_registry(data)
    return sid, rec


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _coerce_cost / _registry_cost hardening (fuzz-report Findings F3+F4) --
# survivors of the log-pipeline deletion: these guard the registry's own
# cost_baseline/cost_usd round-trip against poisoned values.
# ---------------------------------------------------------------------------

class TestCoerceCostHardening:
    def test_cleanly_numeric_string_is_coerced(self):
        assert fleet._coerce_cost("5.00") == 5.0

    def test_non_numeric_string_is_none(self):
        assert fleet._coerce_cost("lots") is None

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_is_none(self, value):
        assert fleet._coerce_cost(value) is None

    def test_negative_is_none(self):
        assert fleet._coerce_cost(-0.5) is None

    def test_bool_is_rejected_even_though_int_subclass(self):
        assert fleet._coerce_cost(True) is None

    def test_registry_cost_falls_back_to_zero(self):
        assert fleet._registry_cost(float("nan")) == 0.0
        assert fleet._registry_cost(None) == 0.0
        assert fleet._registry_cost(1.25) == 1.25


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestDoctorClaudeVersion:
    def test_missing_claude_fails(self, isolated_home):
        name, ok, msg = fleet._doctor_check_claude_version(which=lambda n: None)
        assert ok is False
        assert "PATH" in msg or "claude" in msg

    def test_recent_enough_version_passes(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(stdout="2.1.202 (Claude Code)")
        name, ok, msg = fleet._doctor_check_claude_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True

    def test_older_version_fails(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(stdout="2.0.1")
        name, ok, msg = fleet._doctor_check_claude_version(which=lambda n: "claude.cmd", run=run)
        assert ok is False

    def test_unparseable_version_passes_with_note(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(stdout="garbage output")
        name, ok, msg = fleet._doctor_check_claude_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "could not parse" in msg

    def test_run_raising_fails(self, isolated_home):
        def run(argv, **kw):
            raise OSError("boom")
        name, ok, msg = fleet._doctor_check_claude_version(which=lambda n: "claude.cmd", run=run)
        assert ok is False


class TestDoctorTzdata:
    """D1 / §5.1 follow-up (MD-ULPARSER-REVIEW-2026-07-17.md): tz-data
    availability was invisible -- a `fleet doctor` check now surfaces it."""

    def test_zoneinfo_resolves_passes_plain(self, isolated_home, monkeypatch):
        # ME-UL-REVIEW-2026-07-21.md M2: this must NOT depend on the real
        # host actually having tz data -- that's a coincidence (D1), and a
        # test asserting "tz data is present" inverts on exactly the clean
        # box this check exists to detect (was RED under a tzdata import
        # block; see the review's §4 repro). Stub the seam deterministically
        # instead, mirroring the existing failure-branch test below.
        import zoneinfo

        monkeypatch.setattr(zoneinfo, "ZoneInfo", lambda name: object())
        name, ok, msg = fleet._doctor_check_tzdata()
        assert name == "tzdata"
        assert ok is True
        assert "resolves named zones" in msg

    def test_zoneinfo_lookup_failure_is_pass_note_not_fail(self, isolated_home, monkeypatch):
        import zoneinfo

        def boom(name):
            raise zoneinfo.ZoneInfoNotFoundError(name)

        monkeypatch.setattr(zoneinfo, "ZoneInfo", boom)
        name, ok, msg = fleet._doctor_check_tzdata()
        assert name == "tzdata"
        assert ok is True  # PASS-note, never FAIL -- absent tz data narrows, doesn't break
        assert "pip install tzdata" in msg


class TestDoctorInstanceSettings:
    def test_missing_instance_fails(self, isolated_home):
        fleet.instance_settings_path().unlink()
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is False
        assert "fleet init" in msg

    def test_invalid_json_fails(self, isolated_home):
        fleet.instance_settings_path().write_text("{not json", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is False

    def test_backslash_hook_command_fails(self, isolated_home):
        data = {"hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": r"py C:\proga\claude-fleet\bin\hooks\posttooluse_mailbox.py"}
        ]}]}}
        fleet.instance_settings_path().write_text(json.dumps(data), encoding="utf-8")
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is False
        assert "backslash" in msg

    def test_missing_hook_script_fails(self, isolated_home):
        data = {"hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": "py /nonexistent/nope.py"}
        ]}]}}
        fleet.instance_settings_path().write_text(json.dumps(data), encoding="utf-8")
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is False
        assert "not found" in msg

    def test_quoted_script_path_still_resolves(self, isolated_home):
        """Regression (caught by live smoke-testing this doctor check
        against the real repo): rendered commands wrap each path segment
        in double quotes (spaced-install-path fix) -- the script-exists
        check must strip that quoting before checking Path.exists(),
        not treat the leading quote as part of the path."""
        real_repo_root = Path(fleet.__file__).resolve().parent.parent
        script = (real_repo_root / "bin" / "hooks" / "posttooluse_mailbox.py").as_posix()
        data = {"hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": f'"C:/some/python.exe" "{script}"'}
        ]}]}}
        fleet.instance_settings_path().write_text(json.dumps(data), encoding="utf-8")
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is True, msg

    def test_valid_forward_slash_settings_pass(self, isolated_home):
        real_hook = fleet.FLEET_HOME.parent / "bin" / "hooks" / "posttooluse_mailbox.py"
        # Use the REAL repo's hook script path (read-only referenced, not
        # written) so the "script exists" half of the check has a genuine
        # target -- isolated_home's FLEET_HOME is a tmp_path sandbox, but
        # the hook scripts themselves are real repo files, addressed here
        # via the actual fleet.py location rather than the sandbox.
        import fleet as fleet_module
        real_repo_root = Path(fleet_module.__file__).resolve().parent.parent
        script = (real_repo_root / "bin" / "hooks" / "posttooluse_mailbox.py").as_posix()
        data = {"hooks": {"PostToolUse": [{"hooks": [
            {"type": "command", "command": f"py {script}"}
        ]}]}}
        fleet.instance_settings_path().write_text(json.dumps(data), encoding="utf-8")
        name, ok, msg = fleet._doctor_check_instance_settings()
        assert ok is True


class TestDoctorFreshness:
    def test_missing_instance_is_stale_and_fails(self, isolated_home):
        fleet.instance_settings_path().unlink()
        name, ok, msg = fleet._doctor_check_instance_freshness()
        assert ok is False

    def test_fresh_instance_passes(self, isolated_home):
        template = fleet.template_settings_path()
        template.write_text("{}", encoding="utf-8")
        instance = fleet.instance_settings_path()
        # Simulate the instance having been rendered AFTER this template
        # edit (the real `fleet init` ordering) -- explicit mtimes rather
        # than a real-clock sleep (matches Task 8's own test technique).
        template_mtime = template.stat().st_mtime
        os.utime(instance, (template_mtime + 10, template_mtime + 10))
        name, ok, msg = fleet._doctor_check_instance_freshness()
        assert ok is True


class TestDoctorLegacySettings:
    def test_no_legacy_file_passes(self, isolated_home):
        name, ok, msg = fleet._doctor_check_legacy_settings()
        assert ok is True
        assert "no legacy" in msg

    def test_legacy_file_present_warns_but_passes(self, isolated_home):
        (fleet.FLEET_HOME / "worker-settings.json").write_text("{}", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_legacy_settings()
        assert ok is True
        assert "legacy" in msg


_REAL_REPO_ROOT = Path(fleet.__file__).resolve().parent.parent


class TestDoctorHookSmoke:
    def test_posttooluse_smoke_real_subprocess_passes(self, isolated_home, monkeypatch):
        """Real end-to-end run (no injected `run`) against the actual repo
        hook script -- mirrors tests/test_hooks.py's own subprocess
        technique. FLEET_HOME must point at the real repo root here (where
        bin/hooks/*.py actually live) rather than isolated_home's bare
        tmp_path sandbox; the smoke test's own scratch temp FLEET_HOME
        (passed to the hook subprocess's env) is unrelated and still
        isolated."""
        monkeypatch.setattr(fleet, "FLEET_HOME", _REAL_REPO_ROOT)
        name, ok, msg = fleet._doctor_check_posttooluse_hook_smoke()
        assert ok is True, msg

    def test_stop_smoke_real_subprocess_passes(self, isolated_home, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", _REAL_REPO_ROOT)
        name, ok, msg = fleet._doctor_check_stop_hook_smoke()
        assert ok is True, msg

    def test_posttooluse_smoke_missing_script_fails(self, isolated_home, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", isolated_home / "nonexistent-fleet-home")
        name, ok, msg = fleet._doctor_check_posttooluse_hook_smoke()
        assert ok is False

    def test_posttooluse_smoke_nonzero_exit_fails(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(returncode=1, stderr="boom")
        name, ok, msg = fleet._doctor_check_posttooluse_hook_smoke(run=run)
        assert ok is False

    def test_posttooluse_smoke_non_json_stdout_fails(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(returncode=0, stdout="not json")
        name, ok, msg = fleet._doctor_check_posttooluse_hook_smoke(run=run)
        assert ok is False

    def test_stop_smoke_wrong_shape_fails(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(returncode=0, stdout=json.dumps({"unexpected": True}))
        name, ok, msg = fleet._doctor_check_stop_hook_smoke(run=run)
        assert ok is False


class TestDoctorTerminalLauncher:
    def test_wt_present(self, isolated_home):
        name, ok, msg = fleet._doctor_check_terminal_launcher(which=lambda n: "wt.exe")
        assert ok is True
        assert "wt" in msg.lower()

    def test_wt_absent_notes_fallback(self, isolated_home):
        name, ok, msg = fleet._doctor_check_terminal_launcher(which=lambda n: None)
        assert ok is True
        assert "falls back" in msg.lower()


class TestDoctorRegistryChecks:
    def test_orphaned_mailbox_reported(self, isolated_home):
        # F9: orphaned-mailbox detection now lives in the orphaned-claims check
        # (with sid + first-line disposition), not _doctor_check_mailboxes --
        # extended, not duplicated.
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / "unknown-sid.md").write_text("x", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims(workers={})
        assert ok is True
        assert "orphaned" in msg
        assert "unknown-sid" in msg

    def test_pending_mail_on_idle_worker_reported(self, isolated_home):
        sid, rec = _seed_worker("probe-1", status="idle", log_result=True)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("undelivered", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_mailboxes({"probe-1": rec})
        assert ok is True
        assert "undelivered" in msg

    def test_stale_attach_reported(self, isolated_home):
        _, rec = _seed_worker("probe-1", status="attached")
        rec["attached_since"] = "2020-01-01T00:00:00Z"
        name, ok, msg = fleet._doctor_check_stale_attaches({"probe-1": rec})
        assert ok is True
        assert "probe-1" in msg

    def test_no_stale_attach(self, isolated_home):
        _, rec = _seed_worker("probe-1", status="idle", log_result=True)
        name, ok, msg = fleet._doctor_check_stale_attaches({"probe-1": rec})
        assert ok is True
        assert "no attaches" in msg

    def test_orphaned_claims_reported(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / "sid-1.md.claimed.123").write_text("x", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims()
        assert ok is True
        assert "claimed" in msg

    def test_no_orphaned_claims(self, isolated_home):
        fleet.mailbox_dir().mkdir(parents=True, exist_ok=True)
        name, ok, msg = fleet._doctor_check_orphaned_claims()
        assert ok is True
        assert "no orphaned" in msg

    def test_no_dirs_yet_reports_no_orphans(self, isolated_home):
        # FIX-5: the check no longer early-returns on a missing mailbox dir
        # (it also scans state/ceilings); with nothing on disk it reports the
        # clean "no orphaned ..." message, still ok=True.
        name, ok, msg = fleet._doctor_check_orphaned_claims()
        assert ok is True
        assert "no orphaned" in msg

class TestDoctorClaudeAgents:
    def test_command_absent_is_note_only(self, isolated_home):
        name, ok, msg = fleet._doctor_check_claude_agents({}, which=lambda n: None)
        assert ok is True
        assert "skipped" in msg

    def test_command_failure_is_note_only(self, isolated_home):
        def run(argv, **kw):
            raise OSError("boom")
        name, ok, msg = fleet._doctor_check_claude_agents({}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "skipped" in msg

    def test_nonzero_exit_is_note_only(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(returncode=1)
        name, ok, msg = fleet._doctor_check_claude_agents({}, which=lambda n: "claude.cmd", run=run)
        assert ok is True

    def test_unknown_session_reported(self, isolated_home):
        def run(argv, **kw):
            return _FakeResult(returncode=0, stdout=json.dumps([{"session_id": "totally-unknown"}]))
        name, ok, msg = fleet._doctor_check_claude_agents({}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "totally-unknown" in msg

    def test_known_session_not_flagged(self, isolated_home):
        sid, rec = _seed_worker("probe-1", status="idle", log_result=True)

        def run(argv, **kw):
            return _FakeResult(returncode=0, stdout=json.dumps([{"session_id": sid}]))
        name, ok, msg = fleet._doctor_check_claude_agents({"probe-1": rec}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "no fleet-unknown" in msg


class TestCmdDoctorOrchestration:
    def test_all_pass_exits_zero(self, isolated_home, capsys, monkeypatch):
        monkeypatch.setattr(fleet, "_doctor_check_claude_version", lambda **kw: ("a", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_instance_settings", lambda: ("b", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_instance_freshness", lambda: ("c", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_legacy_settings", lambda: ("d", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_posttooluse_hook_smoke", lambda **kw: ("e", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_stop_hook_smoke", lambda **kw: ("f", True, "ok"))
        # The isolated home has no ~/.claude/fleet-home marker (conftest sandboxes it
        # away from the developer's real one), so the real check correctly fails
        # there. These tests are about orchestration, not that check.
        monkeypatch.setattr(fleet, "_doctor_check_fleet_home_marker", lambda: ("g", True, "ok"))

        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(args, which=lambda n: "wt.exe", run=lambda *a, **k: _FakeResult())
        assert rc == 0
        out = capsys.readouterr().out
        assert "[PASS]" in out
        assert "[FAIL]" not in out

    def test_one_failure_exits_nonzero(self, isolated_home, capsys, monkeypatch):
        monkeypatch.setattr(fleet, "_doctor_check_claude_version", lambda **kw: ("a", False, "not found"))
        monkeypatch.setattr(fleet, "_doctor_check_instance_settings", lambda: ("b", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_instance_freshness", lambda: ("c", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_legacy_settings", lambda: ("d", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_posttooluse_hook_smoke", lambda **kw: ("e", True, "ok"))
        monkeypatch.setattr(fleet, "_doctor_check_stop_hook_smoke", lambda **kw: ("f", True, "ok"))
        # The isolated home has no ~/.claude/fleet-home marker (conftest sandboxes it
        # away from the developer's real one), so the real check correctly fails
        # there. These tests are about orchestration, not that check.
        monkeypatch.setattr(fleet, "_doctor_check_fleet_home_marker", lambda: ("g", True, "ok"))

        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(args, which=lambda n: "wt.exe", run=lambda *a, **k: _FakeResult())
        assert rc == 1
        out = capsys.readouterr().out
        assert "[FAIL]" in out
        assert "not found" in out

    def test_snapshots_registry_without_holding_lock_across_checks(self, isolated_home, monkeypatch):
        """Doctor must release fleet_lock before running its (subprocess-
        shaped) checks -- assert a second lock acquisition succeeds while
        one of the check functions is running."""
        _seed_worker("probe-1", status="idle", log_result=True)

        def fake_run(argv, **kw):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout
            return _FakeResult(stdout="2.1.202")

        args = fleet.build_parser().parse_args(["doctor"])
        fleet.cmd_doctor(args, which=lambda n: "wt.exe", run=fake_run)


# ---------------------------------------------------------------------------
# spawn --setting-sources passthrough (spec-audit gap 5)
# ---------------------------------------------------------------------------

class TestSettingSourcesPassthrough:
    def test_spawn_persists_and_forwards_setting_sources(self, isolated_home, tmp_path, monkeypatch):
        # T4 fix wave (Important I1): --setting-sources is persisted in the
        # registry at spawn AND forwarded onto the native --bg argv via
        # dispatch_bg's setting_sources param (previously persistence-only
        # -- dispatch_bg's frozen T3 signature had no such param; see
        # tests/test_cli.py::TestCmdSpawn's matching note).
        import types
        state = {"n": 0}
        calls = []

        def roster_fetch(**_):
            # Call-count-aware: the 1st call is dispatch_bg's pre-dispatch
            # snapshot (session doesn't exist yet); the 2nd+ call is the
            # join poll (session now present) -- a statically-present entry
            # would be excluded from the join by dispatch_bg's own foreign-
            # session guard and spin the real NATIVE_JOIN_VERIFY_SECONDS.
            state["n"] += 1
            if state["n"] == 1:
                return True, []
            return True, [{"id": "aaaabbbb", "sessionId":
                "aaaabbbb-1111-2222-3333-444455556666", "name": "fleet|probe-1|t",
                "cwd": str(tmp_path), "startedAt": 1, "kind": "background",
                "state": "working", "status": "busy", "pid": 1}]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster_fetch)
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = fleet.build_parser().parse_args(
            ["spawn", "probe-1", "--dir", str(worker_dir), "--task", "do it", "--setting-sources", "project"]
        )

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0,
                stdout="backgrounded · aaaabbbb · fleet|probe-1|t\n", stderr="")

        fleet.cmd_spawn(args, run=fake_run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["setting_sources"] == "project"

        argv = calls[0]
        assert argv[argv.index("--setting-sources") + 1] == "project"
        # Positioned after --settings, per the T4 fix wave contract.
        assert argv.index("--setting-sources") > argv.index("--settings")

    def test_spawn_omits_setting_sources_flag_when_not_given(self, isolated_home, tmp_path, monkeypatch):
        import types
        state = {"n": 0}
        calls = []

        def roster_fetch(**_):
            state["n"] += 1
            if state["n"] == 1:
                return True, []
            return True, [{"id": "aaaabbbb", "sessionId":
                "aaaabbbb-1111-2222-3333-444455556666", "name": "fleet|probe-1|t",
                "cwd": str(tmp_path), "startedAt": 1, "kind": "background",
                "state": "working", "status": "busy", "pid": 1}]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster_fetch)
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = fleet.build_parser().parse_args(
            ["spawn", "probe-1", "--dir", str(worker_dir), "--task", "do it"]
        )

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0,
                stdout="backgrounded · aaaabbbb · fleet|probe-1|t\n", stderr="")

        fleet.cmd_spawn(args, run=fake_run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        assert "--setting-sources" not in calls[0]


# ---------------------------------------------------------------------------
# peek tokens (spec-audit gap 5)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# M-D item 3: local-format ("resets 4:40am (Asia/Qyzylorda)") reset-time
# fallback in _parse_limit_signal -- production gap, journal 2026-07-16 /
# knowledge/lessons.md:607.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _tzdata_available(), reason=_TZDATA_SKIP_REASON)
class TestParseLimitSignalLocalFormat:
    def test_iso_wins_verbatim_over_local_text(self):
        text = "resets 2026-07-18T04:40:00Z, but also resets 4:40am (Asia/Qyzylorda)"
        reset_at, kind = fleet._parse_limit_signal(text, now=None)
        assert reset_at == "2026-07-18T04:40:00Z"

    def test_no_signal_returns_none_none(self):
        assert fleet._parse_limit_signal("nothing to see here", now=None) == (None, None)

    def test_unknown_timezone_returns_none_horizon(self):
        now = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)
        reset_at, kind = fleet._parse_limit_signal(
            "resets 4:40am (Not/AZone)", now=now)
        assert reset_at is None

    def test_zoneinfo_lookup_failure_falls_back_to_none(self, monkeypatch):
        import zoneinfo

        def boom(name):
            raise zoneinfo.ZoneInfoNotFoundError(name)

        monkeypatch.setattr(zoneinfo, "ZoneInfo", boom)
        now = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)
        reset_at, kind = fleet._parse_limit_signal(
            "resets 4:40am (Asia/Qyzylorda)", now=now)
        assert reset_at is None

    @pytest.mark.parametrize(
        "text,now,expected",
        [
            # Asia/Qyzylorda is UTC+5, no DST. now=10:00 UTC == 15:00 local,
            # so today's 04:40 local is already past -> rolls to tomorrow's
            # 04:40 local, which lands on 2026-07-16T23:40:00Z in UTC (the
            # local date rolls to the 17th but UTC is still 5h behind it).
            (
                "You've hit your session limit -- resets 4:40am (Asia/Qyzylorda)",
                datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
                "2026-07-16T23:40:00Z",
            ),
            # 12am -> 00:00 local, hour-only form (the production gap).
            # now=01:00 UTC == 06:00 local (past midnight) -> tomorrow.
            (
                "session limit -- resets 12am (Asia/Qyzylorda)",
                datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc),
                "2026-07-16T19:00:00Z",
            ),
            # 12pm -> 12:00 local. now=01:00 UTC == 06:00 local -> today's
            # noon local (still ahead) == 07:00 UTC same day.
            (
                "session limit -- resets 12pm (Asia/Qyzylorda)",
                datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc),
                "2026-07-16T07:00:00Z",
            ),
            # 11:59pm -> 23:59 local, still ahead of 06:00 local -> today.
            (
                "session limit -- resets 11:59pm (Asia/Qyzylorda)",
                datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc),
                "2026-07-16T18:59:00Z",
            ),
        ],
    )
    def test_local_format_parsed_to_correct_utc_instant(self, text, now, expected):
        reset_at, kind = fleet._parse_limit_signal(text, now=now)
        assert reset_at == expected
        assert kind == "session_5h"

    def test_already_past_today_rolls_to_tomorrow(self):
        # now is exactly at local midnight + 1 minute -- today's "12am"
        # occurrence is already behind now, must roll to tomorrow.
        now = datetime(2026, 7, 16, 19, 1, 0, tzinfo=timezone.utc)  # 00:01 local
        reset_at, _ = fleet._parse_limit_signal("resets 12am (Asia/Qyzylorda)", now=now)
        assert reset_at == "2026-07-17T19:00:00Z"

    def test_no_anchor_never_guesses_via_wall_clock(self):
        # N3 fix wave: `now=None` (the record-timestamp anchor was
        # unavailable) must not fall back to the wall clock for the
        # local-format branch -- it stays unresolved (None), a
        # conservative null-horizon park, never a possibly-wrong guess.
        reset_at, kind = fleet._parse_limit_signal(
            "session limit -- resets 4:40am (Asia/Qyzylorda)", now=None)
        assert reset_at is None
        assert kind == "session_5h"  # kind detection is independent of the anchor


# ---------------------------------------------------------------------------
# D2 (MD-ULPARSER-REVIEW-2026-07-17.md): 1..12 hour validation on the
# 12-hour-clock local-format branch. Boundary on both sides of the valid
# range -- 12am/12pm/1am are legitimate 12-hour-clock hours and must still
# resolve; 13am/0pm are outside 1..12 and must null-park rather than
# silently wrapping (the pre-fix bug: "13am" parsed as 1pm).
# ---------------------------------------------------------------------------

class TestParseLimitSignalHourValidation:
    _NOW = datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc)  # 06:00 Qyzylorda

    @pytest.mark.parametrize(
        "hour_text,expected",
        [
            ("12am", "2026-07-16T19:00:00Z"),  # 00:00 local -> tomorrow (past)
            ("12pm", "2026-07-16T07:00:00Z"),   # 12:00 local -> today (ahead)
            ("1am", "2026-07-16T20:00:00Z"),    # 01:00 local -> tomorrow (past)
        ],
    )
    @pytest.mark.skipif(not _tzdata_available(), reason=_TZDATA_SKIP_REASON)
    def test_valid_boundary_hours_still_resolve(self, hour_text, expected):
        reset_at, _ = fleet._parse_limit_signal(
            f"session limit -- resets {hour_text} (Asia/Qyzylorda)", now=self._NOW)
        assert reset_at == expected

    @pytest.mark.parametrize("hour_text", ["13am", "0pm"])
    def test_out_of_range_hours_null_park_not_wrong_horizon(self, hour_text):
        # Pre-fix: "13am" silently computed hour24=13 (only hour==12 is
        # special-cased in the am branch) -> a well-formed but WRONG
        # horizon (1pm). Post-fix: out-of-range hours take the null-park
        # branch, same as an unresolvable tz.
        reset_at, kind = fleet._parse_limit_signal(
            f"session limit -- resets {hour_text} (Asia/Qyzylorda)", now=self._NOW)
        assert reset_at is None
        assert kind == "session_5h"  # kind detection is independent of the hour parse


# ---------------------------------------------------------------------------
# DQ1 (ME-UL-REVIEW-2026-07-21.md, m1): the tz-name regex now admits
# single-segment IANA keys ("UTC", "Singapore", "EST5EDT", ...), not just
# multi-segment ("Area/City") names. `zoneinfo.ZoneInfo` is the validator
# in both directions -- a real key resolves, a garbage single-segment word
# null-parks exactly like an unresolvable multi-segment name always did.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _tzdata_available(), reason=_TZDATA_SKIP_REASON)
class TestParseLimitSignalSingleSegmentZone:
    _NOW = datetime(2026, 7, 16, 1, 0, 0, tzinfo=timezone.utc)

    def test_utc_single_segment_zone_resolves(self):
        reset_at, _ = fleet._parse_limit_signal(
            "session limit -- resets 4:40am (UTC)", now=self._NOW)
        assert reset_at == "2026-07-16T04:40:00Z"

    def test_garbage_single_segment_zone_null_parks(self):
        reset_at, kind = fleet._parse_limit_signal(
            "session limit -- resets 4:40am (NotAZone)", now=self._NOW)
        assert reset_at is None
        assert kind == "session_5h"


# ---------------------------------------------------------------------------
# §5.1 (MD-ULPARSER-REVIEW-2026-07-17.md): the wall-clock default on `now`
# is vestigial -- every real caller already passes it explicitly. Made
# required (keyword-only, no default) so a future direct caller that
# forgets `now=` gets a structural TypeError instead of silently
# resolving against the wall clock (the exact shape C1 took).
# ---------------------------------------------------------------------------

class TestNowParameterRequired:
    def test_parse_limit_signal_requires_now_kwarg(self):
        # m5 (ME-UL-REVIEW-2026-07-21.md): match= so this stays pinned to
        # the missing-keyword shape specifically, not any TypeError.
        with pytest.raises(TypeError, match=r"missing 1 required keyword-only argument: 'now'"):
            fleet._parse_limit_signal("resets 4:40am (Asia/Qyzylorda)")

    def test_next_local_reset_utc_requires_now_kwarg(self):
        with pytest.raises(TypeError, match=r"missing 1 required keyword-only argument: 'now'"):
            fleet._next_local_reset_utc(4, 40, "Asia/Qyzylorda")


# ---------------------------------------------------------------------------
# M1 (ME-UL-REVIEW-2026-07-21.md): DST fold/gap semantics for
# _next_local_reset_utc. Prior docstring claimed both directions resolved
# late, never early -- false for the ambiguous fall-back case (resolved up
# to 1h EARLY). No DST test existed anywhere in the suite before this. Both
# cases need real America/New_York tz data -- skip (not fail) on a box
# without it, same doctrine as the local-format tests above (M2).
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _tzdata_available(), reason=_TZDATA_SKIP_REASON)
class TestNextLocalResetUtcDst:
    def test_ambiguous_fallback_resolves_late_not_early(self):
        # 2025-11-02 01:30 America/New_York occurs twice (EDT then EST) as
        # the clocks fall back. Anchor a day earlier -- far from the fold,
        # so its own fold=0 carries no information -- and require rolling
        # into the ambiguous day. Pre-fix this returned the FIRST (EDT,
        # earlier) occurrence, 2025-11-02T05:30:00Z -- 1h early.
        now = datetime(2025, 11, 1, 6, 0, 0, tzinfo=timezone.utc)
        reset_at, _ = fleet._parse_limit_signal(
            "session limit -- resets 1:30am (America/New_York)", now=now)
        assert reset_at == "2025-11-02T06:30:00Z"  # second (EST) occurrence -- late

    def test_gap_still_resolves_late_unaffected_by_fold_fix(self):
        # 2025-03-09 02:30 America/New_York does not exist (spring-forward
        # skips 2am-3am). This direction was already correct (pre-transition
        # offset, the later reading) and must stay that way -- the fold fix
        # must not trade a fold-case bug for a new gap-case one.
        now = datetime(2025, 3, 9, 1, 0, 0, tzinfo=timezone.utc)
        reset_at, _ = fleet._parse_limit_signal(
            "session limit -- resets 2:30am (America/New_York)", now=now)
        assert reset_at == "2025-03-09T07:30:00Z"


# ---------------------------------------------------------------------------
# N2 fix wave (MD-ULPARSER-REVIEW-2026-07-17.md re-review): `_record_time`
# must parse a trailing-Z timestamp WITHOUT relying on
# `datetime.fromisoformat`'s native `Z` support, which is Python 3.11+
# only. This repo's documented floor is 3.10 (docs/specs/portability.md
# D9, SPEC.md's multi-platform directive) -- on 3.10, `fromisoformat("...Z")`
# raises ValueError, which is exactly how C1 silently reverted in full
# pre-N2 (bad timestamp -> None -> old wall-clock-guess behavior). These
# tests run on this repo's dev interpreter (3.13, where the naive
# `fromisoformat("...Z")` form would ALSO happen to work) so they cannot
# themselves fail on a 3.10 floor violation -- they pin the trailing-Z
# input/output contract so any future edit that reintroduces a
# 3.11-only parse gets caught the moment a 3.10 CI job exists
# (portability.md D9 recommends one), and so the intent is explicit in
# the meantime, per the review's own closing suggestion.
# ---------------------------------------------------------------------------

class TestRecordTimeParsing:
    def test_trailing_z_fractional_seconds(self):
        # The exact real G7 evidence form (spike/m0/VERDICTS.md:441).
        dt = fleet._record_time({"timestamp": "2026-07-13T23:48:10.741Z"})
        assert dt == datetime(2026, 7, 13, 23, 48, 10, 741000, tzinfo=timezone.utc)

    def test_trailing_z_whole_seconds(self):
        dt = fleet._record_time({"timestamp": "2026-07-13T23:48:10Z"})
        assert dt == datetime(2026, 7, 13, 23, 48, 10, tzinfo=timezone.utc)

    def test_explicit_offset_still_parses(self):
        dt = fleet._record_time({"timestamp": "2026-07-13T23:48:10+05:00"})
        assert dt.utcoffset().total_seconds() == 5 * 3600

    def test_naive_timestamp_assumed_utc(self):
        dt = fleet._record_time({"timestamp": "2026-07-13T23:48:10"})
        assert dt == datetime(2026, 7, 13, 23, 48, 10, tzinfo=timezone.utc)

    @pytest.mark.parametrize("rec", [
        {}, {"timestamp": None}, {"timestamp": 123}, {"timestamp": "garbage"},
        {"timestamp": ""}, "not-a-dict", None,
    ])
    def test_garbage_returns_none(self, rec):
        assert fleet._record_time(rec) is None


class TestDoctorHookErrors:
    def test_no_log_passes(self, isolated_home):
        name, ok, msg = fleet._doctor_check_hook_errors()
        assert name == "hook-errors"
        assert ok is True
        assert "no swallowed hook errors" in msg

    def test_empty_log_passes(self, isolated_home):
        fleet.hook_errors_path().write_text("\n  \n", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_hook_errors()
        assert ok is True
        assert "no swallowed hook errors" in msg

    def test_nonempty_log_surfaces_tail(self, isolated_home):
        lines = [f"2026-07-08T00:0{i}:00Z sid-{i} KeyError('boom{i}')" for i in range(6)]
        fleet.hook_errors_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_hook_errors()
        # A logged hook error is surfaced, not a hard doctor failure
        # (hooks keep the exit-0 invariant; this only makes them visible).
        assert ok is True
        assert "6" in msg
        # the newest line must appear; the oldest (line 0) is off the tail
        assert "boom5" in msg
        assert "boom0" not in msg


# ---------------------------------------------------------------------------
# Kernel 2 -- static hook-registration lint (learns PostCompact, F11)
# ---------------------------------------------------------------------------

class TestDoctorHookRegistration:
    def _write_settings(self, hooks):
        fleet.instance_settings_path().write_text(
            json.dumps({"hooks": hooks}), encoding="utf-8"
        )

    def _existing_script(self, isolated_home):
        script = isolated_home / "state" / "hook.py"
        script.write_text("# stub", encoding="utf-8")
        return script.as_posix()

    def test_missing_instance_fails(self, isolated_home):
        fleet.instance_settings_path().unlink()
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert name == "hook-registration"
        assert ok is False

    def test_invalid_json_fails(self, isolated_home):
        fleet.instance_settings_path().write_text("{not json", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert ok is False

    def test_no_hooks_object_is_tolerated(self, isolated_home):
        # The stub `{}` instance (what the fixture writes) must not turn
        # doctor red -- the instance-settings check owns "is there anything
        # here"; this lint only validates whatever IS registered.
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert ok is True

    def test_known_events_with_existing_paths_pass(self, isolated_home):
        script = self._existing_script(isolated_home)
        self._write_settings({
            "PostToolUse": [{"hooks": [{"type": "command", "command": f'py "{script}"'}]}],
            "Stop": [{"hooks": [{"type": "command", "command": f'py "{script}"'}]}],
            "PostCompact": [{"hooks": [{"type": "command", "command": f'py "{script}"'}]}],
        })
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert ok is True, msg
        # F11: PostCompact is a KNOWN event now -- a lint that hadn't
        # learned it would flag it as unknown and fail here.
        assert "PostCompact" in msg

    def test_unknown_event_name_fails(self, isolated_home):
        script = self._existing_script(isolated_home)
        self._write_settings({
            "PostToolUsee": [{"hooks": [{"type": "command", "command": f'py "{script}"'}]}],
        })
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert ok is False
        assert "PostToolUsee" in msg

    def test_missing_command_path_fails(self, isolated_home):
        self._write_settings({
            "Stop": [{"hooks": [{"type": "command", "command": 'py "/nope/gone.py"'}]}],
        })
        name, ok, msg = fleet._doctor_check_hook_registration()
        assert ok is False
        assert "gone.py" in msg


# ---------------------------------------------------------------------------
# Kernel 4 -- abnormal-turn-end journal note + cwd preflight
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Item 8 (F9): send-lock serialization + mail events + orphaned-mailbox doctor
# ---------------------------------------------------------------------------

def _read_events():
    p = fleet.events_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestMailEvents:
    """F9: fleet.py (sole writer) emits mail_sent (cmd_send) and mail_drained
    (compose-time drain) audit events -- not a DLQ, no redelivery machinery."""

    def test_send_to_working_emits_mail_sent(self, isolated_home, monkeypatch):
        sid, _ = _seed_worker("w", status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            {"sessionId": sid, "state": "working", "status": "busy", "pid": 1}]))
        args = fleet.build_parser().parse_args(["send", "w", "ping"])
        fleet.cmd_send(args, which=lambda n: "claude.cmd")
        sent = [e for e in _read_events() if e["kind"] == "mail_sent"]
        assert sent, "no mail_sent event emitted"
        assert sent[-1]["name"] == "w"
        assert sent[-1]["sid"] == sid

    def test_compose_prompt_drain_emits_mail_drained(self, isolated_home):
        sid = "sid-drain"
        fleet.append_mailbox(sid, "queued work")
        # append_mailbox itself is a low-level helper -- it must NOT emit an event.
        assert not any(e["kind"] == "mail_drained" for e in _read_events())
        prompt, claim = fleet.compose_prompt("w", str(fleet.FLEET_HOME), "", sid)
        assert "queued work" in prompt
        drained = [e for e in _read_events() if e["kind"] == "mail_drained"]
        assert drained, "no mail_drained event emitted at compose-time drain"
        assert drained[-1]["name"] == "w"
        assert drained[-1]["sid"] == sid

    def test_compose_prompt_no_mail_emits_no_drain(self, isolated_home):
        prompt, claim = fleet.compose_prompt("w", str(fleet.FLEET_HOME), "do the thing", "empty-sid")
        assert not any(e["kind"] == "mail_drained" for e in _read_events())


class TestOrphanedMailboxDoctor:
    """F9: doctor's orphaned-mailbox check EXTENDS _doctor_check_orphaned_claims
    -- a mailbox/<sid>.md whose sid matches no registered worker, disposed with
    sid + first line."""

    def test_orphaned_mailbox_reports_sid_and_first_line(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / "ghost-sid.md").write_text("resume the migration\nsecond line", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims(workers={})
        assert name == "orphaned-claims"
        assert ok is True
        assert "ghost-sid" in msg
        assert "resume the migration" in msg

    def test_registered_mailbox_not_flagged_orphaned(self, isolated_home):
        sid, rec = _seed_worker("w", status="idle", log_result=True)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("pending", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims(workers={"w": rec})
        assert ok is True
        assert sid not in msg

    def test_orphaned_claims_still_reported_alongside(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / "sid-1.md.claimed.123").write_text("x", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims(workers={})
        assert ok is True
        assert "claimed" in msg


# ---------------------------------------------------------------------------
# Item 9 (F15): PID-probe three-way + retry-once-before-dead + doctor check
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Kernel 10 fleet half (F12=M24): token-ceiling ENFORCEMENT (fleet-side)
# ---------------------------------------------------------------------------

def _set_field(name, **fields):
    data = fleet.load_registry()
    data["workers"][name].update(fields)
    fleet.save_registry(data)


class TestTokenCeilingNative:
    def test_status_flags_over_ceiling(self, isolated_home, monkeypatch, capsys):
        sid, _ = _seed_worker("probe-1", status="over_ceiling")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            {"sessionId": sid, "state": "idle", "status": "idle", "pid": 1}]))
        args = fleet.build_parser().parse_args(["status"])
        fleet.cmd_status(args)
        assert "over-ceiling" in capsys.readouterr().out

    def test_fork_steer_refuses_at_exactly_ceiling(self, isolated_home, monkeypatch):
        """FIX-3 (F-2) boundary, native lane: the Stop hook allows stop at
        tokens >= ceiling; the fleet-side fork-steer refusal must also use
        >= so tokens == ceiling is treated as over by BOTH halves."""
        sid, _ = _seed_worker("probe-1", status="idle", token_ceiling=1000)
        fleet.append_outcome("probe-1", {"ts": fleet.now_iso(), "session_id": sid,
                                         "kind": "result", "result_text": "done",
                                         "input_tokens": 600, "output_tokens": 400})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            {"sessionId": sid, "state": "idle", "status": "idle", "pid": 1}]))

        def boom_run(*a, **kw):
            raise AssertionError("must not dispatch at tokens == ceiling")

        args = fleet.build_parser().parse_args(["send", "probe-1", "keep going"])
        with pytest.raises(fleet.FleetCliError, match="ceiling"):
            fleet.cmd_send(args, run=boom_run, which=lambda n: "claude.cmd")
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "over_ceiling"


_NO_SLEEP = lambda *a, **k: None


def _iso_at(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _past():
    return _iso_at(datetime.now(timezone.utc) - timedelta(hours=1))


def _future():
    return _iso_at(datetime.now(timezone.utc) + timedelta(hours=1))


class TestCmdResumeLimited:
    def _stub_native_resume(self, monkeypatch, calls):
        def fake(name, old_sid, cwd, mode, model, category,
                 setting_sources, token_ceiling, run, which, sleep):
            calls.append(name)
            return True
        monkeypatch.setattr(fleet, "_resume_one_limited_native", fake)

    def test_past_horizon_worker_relaunched_and_flipped_working(self, isolated_home, monkeypatch):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_past(), limit_kind="session_5h")
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == ["probe-1"]
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"

    def test_before_horizon_worker_skipped(self, isolated_home, monkeypatch, capsys):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_future(), limit_kind="session_5h")
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == []
        assert "still before reset horizon" in capsys.readouterr().out
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "limited"

    def test_null_horizon_worker_skipped_without_force(self, isolated_home, monkeypatch, capsys):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=None, limit_kind=None)
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == []
        assert "--force-now" in capsys.readouterr().out

    def test_null_horizon_worker_relaunched_with_force_now(self, isolated_home, monkeypatch):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=None, limit_kind=None)
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited", "probe-1", "--force-now"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == ["probe-1"]

    def test_before_horizon_relaunched_with_force_now(self, isolated_home, monkeypatch):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_future(), limit_kind="session_5h")
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited", "probe-1", "--force-now"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == ["probe-1"]

    def test_non_limited_worker_left_untouched(self, isolated_home, monkeypatch, capsys):
        _seed_worker("probe-1", status="idle")
        calls = []
        self._stub_native_resume(monkeypatch, calls)
        args = fleet.build_parser().parse_args(["resume-limited"])
        rc = fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)
        assert rc == 0
        assert calls == []
        assert "not limited" in capsys.readouterr().out

    def test_named_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["resume-limited", "ghost"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_resume_limited(args, which=lambda n: "claude.cmd", sleep=_NO_SLEEP)


class TestLimitedSurfacing:
    def test_status_flags_resets_and_resume_eligible_when_past(self, isolated_home):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_past(), limit_kind="session_5h")
        rec = fleet.load_registry()["workers"]["probe-1"]
        flags = fleet._worker_flags(rec)
        assert any("resets" in f for f in flags)
        assert "resume-eligible" in flags

    def test_status_flags_reset_unknown_when_null(self, isolated_home):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=None, limit_kind=None)
        rec = fleet.load_registry()["workers"]["probe-1"]
        flags = fleet._worker_flags(rec)
        assert any("reset unknown" in f for f in flags)
        assert "resume-eligible" not in flags

    def test_status_flags_no_resume_eligible_before_horizon(self, isolated_home):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_future(), limit_kind="session_5h")
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert "resume-eligible" not in fleet._worker_flags(rec)

    def test_doctor_notes_past_reset_park(self, isolated_home):
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_past(), limit_kind="session_5h")
        workers = fleet.load_registry()["workers"]
        name, ok, msg = fleet._doctor_check_limited_parks(workers)
        assert ok
        assert "resume-limited" in msg

    def test_doctor_notes_weekly_and_null_horizon(self, isolated_home):
        _seed_worker("weekly-one", status="limited")
        _set_field("weekly-one", limit_reset_at=_future(), limit_kind="weekly")
        _seed_worker("null-one", status="limited")
        _set_field("null-one", limit_reset_at=None, limit_kind=None)
        workers = fleet.load_registry()["workers"]
        name, ok, msg = fleet._doctor_check_limited_parks(workers)
        assert "weekly-one" in msg
        assert "null-one" in msg


# ---------------------------------------------------------------------------
# C2 Wave-2D adjudicated fixes (docs/reviews/C2-FIX-LIST-2026-07-08.md)
# ---------------------------------------------------------------------------

class TestFix1ResumeUnderLockRevalidation:
    def test_second_resume_skips_when_no_longer_limited(self, isolated_home, monkeypatch):
        # F-A1/F-1 (HIGH): a resume that snapshotted `limited` must re-check
        # the record IS STILL `limited` under its own claiming lock before
        # pre-claiming -- else two racing sweeps both fork-steer a second
        # dispatch onto one sid. After the first resume flips it to working,
        # the second must skip, not double-launch.
        _seed_worker("probe-1", status="limited")
        _set_field("probe-1", limit_reset_at=_past(), limit_kind="session_5h")
        calls = []

        def fake(name, old_sid, cwd, mode, model, category,
                 setting_sources, token_ceiling, run, which, sleep):
            calls.append(name)
            return True
        monkeypatch.setattr(fleet, "_resume_one_limited_native", fake)
        launched1 = fleet._resume_one_limited("probe-1", lambda n: "claude.cmd", _NO_SLEEP)
        launched2 = fleet._resume_one_limited("probe-1", lambda n: "claude.cmd", _NO_SLEEP)
        assert launched1 is True
        assert launched2 is False
        assert len(calls) == 1  # exactly one dispatch, no double-launch

    def test_vanished_worker_raises_clean_error_not_keyerror(self, isolated_home):
        with pytest.raises(fleet.FleetCliError):
            fleet._resume_one_limited("ghost", lambda n: "claude.cmd", _NO_SLEEP)


class TestFix5OrphanedCeilingFiles:
    def test_clean_removes_dead_worker_ceiling_file(self, isolated_home, monkeypatch):
        # F-4 (LOW): state/ceilings/<sid> is never cleaned -> resource leak.
        # cmd_clean must sweep it alongside the other per-worker artifacts.
        sid, _ = _seed_worker("probe-1", status="dead")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            {"sessionId": sid, "state": "idle", "status": "idle", "pid": 1}]))
        ceiling = fleet.ceiling_file_path(sid)
        ceiling.parent.mkdir(parents=True, exist_ok=True)
        ceiling.write_text("500", encoding="utf-8")
        args = fleet.build_parser().parse_args(["clean"])
        fleet.cmd_clean(args)
        assert not ceiling.exists()

    def test_doctor_notes_orphaned_ceiling_file(self, isolated_home):
        ceilings = fleet.ceilings_dir()
        ceilings.mkdir(parents=True, exist_ok=True)
        (ceilings / "orphan-sid-xyz").write_text("500", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_orphaned_claims(workers={})
        assert ok
        assert "ceiling" in msg.lower()
        assert "orphan-sid-xyz" in msg
