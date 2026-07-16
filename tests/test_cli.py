"""Unit tests for the claude-fleet CLI layer (bin/fleet.py: main() +
argparse subcommands + native dispatch plumbing).

No real claude process is ever spawned: every test injects a fake `run` /
`which` / roster fetch. Every test monkeypatches fleet.FLEET_HOME to a
pytest tmp_path (autouse fixture below), same discipline as test_core.py.
"""
import io
import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    # SPEC §14: cmd_spawn/cmd_send now refuse to launch a turn unless the
    # worker-settings.json instance has been rendered (`fleet init`).
    # Pre-provision a stub instance here so existing spawn/send tests don't
    # need to know about that precondition; tests exercising the
    # missing-instance error path delete this file first (see
    # TestCmdSpawnRequiresInstanceSettings / TestCmdInit).
    settings = tmp_path / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    return tmp_path


def _parse(ctime_iso):
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _spawn_args(name, dir_, task, mode="dontask", model=None, max_budget_usd=None):
    argv = ["spawn", name, "--dir", str(dir_), "--task", task, "--mode", mode]
    if model:
        argv += ["--model", model]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    return fleet.build_parser().parse_args(argv)


# ---------------------------------------------------------------------------
# M-B T4: cmd_spawn fakes for the native `--bg` dispatch path (mirrors
# tests/test_native.py's own copies -- pytest path rules block importing
# fixtures across test files, per the M-B plan doc's shared-scaffolding note).
# ---------------------------------------------------------------------------

NATIVE_SID = "aaaabbbb-1111-2222-3333-444455556666"


def _make_native_roster_entry(sid, *, name="fleet|w1|task", state="working",
                              status="busy", pid=1234, kind="background"):
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        import types
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


def _native_roster_with(sid=NATIVE_SID, **kw):
    """Call-count-aware: 1st call (dispatch_bg's pre-dispatch snapshot)
    reports the session doesn't exist yet; 2nd+ call (the join poll) reports
    it present -- matches how the real daemon mints the session after --bg
    returns."""
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [_make_native_roster_entry(sid, **kw)]
    return fetch


# ---------------------------------------------------------------------------
# new_worker_record: F13 budget/setting-sources persistence (item 7, M5)
# under the M1 additive-schema rule (readers default missing -> None;
# writers preserve unknown fields).
# ---------------------------------------------------------------------------

class TestWorkerRecordBudgetPersistence:
    def test_new_record_defaults_budget_fields_to_none(self):
        rec = fleet.new_worker_record("sid-1", "C:/proj", "task", "dontask")
        assert rec["max_budget_usd"] is None
        assert rec["setting_sources"] is None

    def test_new_record_persists_given_budget_fields(self):
        rec = fleet.new_worker_record(
            "sid-1", "C:/proj", "task", "dontask",
            max_budget_usd=3.5, setting_sources="user,project")
        assert rec["max_budget_usd"] == 3.5
        assert rec["setting_sources"] == "user,project"

    def test_reader_defaults_missing_fields_to_none(self, isolated_home):
        # A record written before these fields existed must load and read
        # back as None (additive-schema: readers default missing -> None).
        rec = fleet.new_worker_record("sid-1", str(isolated_home), "task", "dontask")
        del rec["max_budget_usd"]
        del rec["setting_sources"]
        fleet.save_registry({"workers": {"probe-1": rec}})

        loaded = fleet.load_registry()["workers"]["probe-1"]
        assert loaded.get("max_budget_usd") is None
        assert loaded.get("setting_sources") is None

    def test_unknown_fields_survive_write_round_trip(self, isolated_home):
        # Additive-schema: writers preserve unknown fields (a field a newer
        # fleet.py added must not be dropped by this one's save).
        rec = fleet.new_worker_record("sid-1", str(isolated_home), "task", "dontask")
        rec["some_future_field"] = "keep-me"
        fleet.save_registry({"workers": {"probe-1": rec}})

        loaded = fleet.load_registry()["workers"]["probe-1"]
        assert loaded["some_future_field"] == "keep-me"


# ---------------------------------------------------------------------------
# Kernel 10 fleet half (F12=M24): token ceiling
# ---------------------------------------------------------------------------

class TestTokenCeilingRecordAndSum:
    def test_new_record_defaults_token_ceiling_to_none(self):
        rec = fleet.new_worker_record("sid-1", "C:/proj", "task", "dontask")
        assert rec["token_ceiling"] is None

    def test_new_record_persists_token_ceiling(self):
        rec = fleet.new_worker_record("sid-1", "C:/proj", "task", "dontask", token_ceiling=50000)
        assert rec["token_ceiling"] == 50000

    def test_reader_defaults_missing_token_ceiling_to_none(self, isolated_home):
        rec = fleet.new_worker_record("sid-1", str(isolated_home), "task", "dontask")
        del rec["token_ceiling"]
        fleet.save_registry({"workers": {"probe-1": rec}})
        loaded = fleet.load_registry()["workers"]["probe-1"]
        assert loaded.get("token_ceiling") is None


class TestSpawnWritesCeilingFile:
    def test_spawn_writes_sid_keyed_ceiling_file_when_configured(self, isolated_home, tmp_path, monkeypatch):
        # Kernel 10 fleet half: cmd_spawn persists the token ceiling at
        # state/ceilings/<sid> -- the exact path stop_mailbox.py reads to
        # decide whether to ALLOW a stop despite pending mail. M-B T4: sid
        # is only known post-join, so the ceiling file is written AFTER the
        # native dispatch stamps the record (G6 -- see cmd_spawn docstring).
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = fleet.build_parser().parse_args([
            "spawn", "probe-1", "--dir", str(worker_dir), "--task", "go", "--token-ceiling", "12345",
        ])
        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["token_ceiling"] == 12345
        ceiling_file = fleet.state_dir() / "ceilings" / rec["session_id"]
        assert ceiling_file.read_text(encoding="utf-8").strip() == "12345"

    def test_spawn_writes_no_ceiling_file_when_not_configured(self, isolated_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "go")
        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["token_ceiling"] is None
        assert not (fleet.state_dir() / "ceilings" / rec["session_id"]).exists()


# ---------------------------------------------------------------------------
# fleet init (SPEC §14): template -> machine-local instance
# ---------------------------------------------------------------------------

_TEMPLATE_JSON = """{
  "hooks": {
    "PostToolUse": [{ "hooks": [{ "type": "command",
      "command": "{{PYTHON}} {{FLEET_HOME}}/bin/hooks/posttooluse_mailbox.py" }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "{{PYTHON}} {{FLEET_HOME}}/bin/hooks/stop_mailbox.py" }] }]
  }
}
"""


class TestCmdInit:
    def test_renders_instance_from_template(self, isolated_home, capsys):
        fleet.template_settings_path().write_text(_TEMPLATE_JSON, encoding="utf-8")

        rc = fleet.cmd_init(fleet.build_parser().parse_args(["init"]))

        assert rc == 0
        instance_path = fleet.instance_settings_path()
        assert instance_path.exists()
        rendered = instance_path.read_text(encoding="utf-8")
        assert "{{" not in rendered
        assert fleet.Path(fleet.sys.executable).resolve().as_posix() in rendered
        assert fleet.Path(isolated_home).resolve().as_posix() in rendered
        json.loads(rendered)
        out = capsys.readouterr().out
        assert str(instance_path) in out

    def test_missing_template_raises_clear_error(self, isolated_home):
        # isolated_home starts empty -- no worker-settings.template.json.
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_init(fleet.build_parser().parse_args(["init"]))

    def test_idempotent_rerender_never_refuses(self, isolated_home):
        fleet.template_settings_path().write_text(_TEMPLATE_JSON, encoding="utf-8")
        args = fleet.build_parser().parse_args(["init"])

        fleet.cmd_init(args)
        rc = fleet.cmd_init(args)  # re-render must succeed again, not refuse

        assert rc == 0
        assert fleet.instance_settings_path().exists()

    def test_main_dispatches_init_command(self, isolated_home):
        fleet.template_settings_path().write_text(_TEMPLATE_JSON, encoding="utf-8")
        rc = fleet.main(["init"])
        assert rc == 0
        assert fleet.instance_settings_path().exists()

    def test_main_dispatches_resume_limited_command(self, isolated_home, monkeypatch):
        # UL1 (item 11 / F31): main() routes `resume-limited` to
        # cmd_resume_limited with the parsed name/--force-now.
        seen = {}

        def fake(args, **kwargs):
            seen["name"] = args.name
            seen["force_now"] = args.force_now
            return 0

        monkeypatch.setattr(fleet, "cmd_resume_limited", fake)
        rc = fleet.main(["resume-limited", "w1", "--force-now"])
        assert rc == 0
        assert seen == {"name": "w1", "force_now": True}


# ---------------------------------------------------------------------------
# resolve_claude_executable
# ---------------------------------------------------------------------------

class TestResolveClaudeExecutable:
    def test_found_returns_path(self):
        assert fleet.resolve_claude_executable(which=lambda n: "C:/fake/claude.cmd") == "C:/fake/claude.cmd"

    def test_missing_raises_clear_error(self):
        with pytest.raises(fleet.ClaudeNotFoundError):
            fleet.resolve_claude_executable(which=lambda n: None)


# ---------------------------------------------------------------------------
# cmd_spawn (M-B T4: native `--bg` dispatch via dispatch_bg -- see
# tests/test_native.py::TestCmdSpawnNative for the launch-contract-specific
# cases: USD-budget refusal, dispatch-failure rollback, join-expiry
# fast-completion idle commit, join-expiry DOA rollback. This class covers
# the surrounding CLI-layer concerns: registry shape, name/dir/task-file
# validation, model echo, F-RACE re-assertion.)
# ---------------------------------------------------------------------------

class TestCmdSpawn:
    def test_spawn_creates_registry_entry_and_launches(self, isolated_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "do the thing", mode="dontask", model="haiku")

        rc = fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd",
                             sleep=lambda s: None)

        assert rc == 0
        data = fleet.load_registry()
        rec = data["workers"]["probe-1"]
        assert rec["dispatch_kind"] == "bg"
        assert rec["session_id"] == NATIVE_SID
        assert rec["native_short_id"] == "aaaabbbb"
        assert rec["cwd"] == str(worker_dir)
        assert rec["mode"] == "dontask"
        assert rec["model"] == "haiku"
        assert "turn_pid" not in rec  # legacy Popen field retired (pivot spec §6)
        assert rec["turns"] == 1

    def test_spawn_persists_setting_sources(self, isolated_home, tmp_path, monkeypatch):
        # F13 (item 7, M5): --setting-sources is recorded in the registry
        # at spawn. T4 fix wave (Important I1): it is now also forwarded
        # onto the native --bg argv via dispatch_bg's setting_sources
        # param -- see the argv assertion below (previously persistence
        # only, see task-4-report.md/task-4-adversarial.md I1).
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = fleet.build_parser().parse_args([
            "spawn", "probe-1", "--dir", str(worker_dir), "--task", "do the thing",
            "--setting-sources", "user,project",
        ])

        fleet.cmd_spawn(args, run=_fake_run_factory(calls=calls), which=lambda n: "claude.cmd",
                        sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["setting_sources"] == "user,project"
        argv = calls[0][0]
        assert argv[argv.index("--setting-sources") + 1] == "user,project"

    def test_spawn_prints_name_and_session_id(self, isolated_home, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "do the thing")

        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)

        out = capsys.readouterr().out
        assert "probe-1" in out
        data = fleet.load_registry()
        assert data["workers"]["probe-1"]["session_id"] in out
        assert "short id aaaabbbb" in out

    def test_spawn_refuses_duplicate_name(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        fleet.save_registry({"workers": {"probe-1": _seed_record(worker_dir)}})
        args = _spawn_args("probe-1", worker_dir, "do the thing")

        def run(*a, **kw):
            raise AssertionError("must not dispatch when name is a duplicate")

        with pytest.raises(ValueError):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

    def test_spawn_refuses_bad_name(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def run(*a, **kw):
            raise AssertionError("must not dispatch when name is invalid")

        args = _spawn_args("Bad Name!", worker_dir, "do the thing")
        with pytest.raises(ValueError):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

    def test_spawn_refuses_missing_dir(self, isolated_home, tmp_path):
        missing = tmp_path / "nope"

        def run(*a, **kw):
            raise AssertionError("must not dispatch when --dir is missing")

        args = _spawn_args("probe-1", missing, "do the thing")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

    def test_spawn_raises_clear_error_when_instance_settings_missing(self, isolated_home, tmp_path):
        """SPEC §14: cmd_spawn refuses before any registry mutation or
        dispatch when `fleet init` has never been run on this machine."""
        fleet.instance_settings_path().unlink()  # the isolated_home fixture stubs one in
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def run(*a, **kw):
            raise AssertionError("must not dispatch when the settings instance is missing")

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(fleet.FleetCliError, match="fleet init"):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        assert fleet.load_registry()["workers"] == {}  # no partial record left behind

    def test_spawn_reads_task_from_file(self, isolated_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        task_file = tmp_path / "task.md"
        task_file.write_text("do the elaborate multi-line thing\nwith detail", encoding="utf-8")
        args = _spawn_args("probe-1", worker_dir, f"@{task_file}")

        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)

        written = fleet.task_file_path("probe-1").read_text(encoding="utf-8")
        assert "do the elaborate multi-line thing" in written
        data = fleet.load_registry()
        assert data["workers"]["probe-1"]["task"].startswith("do the elaborate multi-line thing")

    def test_spawn_missing_task_file_raises_clear_error(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "@" + str(tmp_path / "nope.md"))

        def run(*a, **kw):
            raise AssertionError("must not dispatch when task file is missing")

        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

    def test_spawn_dispatch_failure_rolls_back_registry(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=_fake_run_factory(rc=1), which=lambda n: "claude.cmd",
                            sleep=lambda s: None)

        data = fleet.load_registry()
        assert "probe-1" not in data["workers"]

    def test_spawn_rolls_back_on_keyboard_interrupt(self, isolated_home, tmp_path):
        """Task-4-verdict re-review Fix 2 precedent, carried into the native
        flow: cmd_spawn's rollback must also catch BaseException -- a Ctrl-C
        landing during dispatch must still pop the just-created registry
        record, not leave a ghost "working"+session_id=None record pinned
        forever by the recompute launch-in-flight guard."""
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def run(*a, **kw):
            raise KeyboardInterrupt()

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        data = fleet.load_registry()
        assert "probe-1" not in data["workers"]

    def test_spawn_reasserts_working_after_concurrent_recompute_race(self, isolated_home, tmp_path, monkeypatch):
        """F-RACE: between cmd_spawn's create-lock (record written with
        session_id=None) and its post-dispatch stamp lock, a concurrent
        `fleet status` can recompute a "dead" verdict and persist it.
        The stamp lock must re-assert status="working" so the live worker
        is not left permanently `dead` (testRace.py in the adversarial
        review; same contract under native dispatch)."""
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())

        def run(argv, **kwargs):
            # Simulate the racing `fleet status` landing in the inter-lock
            # gap: sees the pre-claim record (working, session_id=None) and
            # persists a spurious "dead".
            data = fleet.load_registry()
            rec = data["workers"]["probe-1"]
            assert rec["status"] == "working"
            assert rec["session_id"] is None
            rec["status"] = "dead"
            fleet.save_registry(data)
            import types
            return types.SimpleNamespace(returncode=0, stdout="backgrounded · aaaabbbb · fleet|w1|t\n", stderr="")

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        rc = fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"


# ---------------------------------------------------------------------------
# _commit_launched_turn (post-testing wave, item 1b: stress-report Finding 1,
# CRITICAL -- the post-dispatch commit lock in cmd_spawn/cmd_send/cmd_respawn
# must not strand an already-dispatched, live session just because that ONE
# lock acquisition timed out.)
# ---------------------------------------------------------------------------

class TestCommitLaunchedTurn:
    def test_succeeds_immediately_no_retry(self):
        calls = {"n": 0}

        def commit():
            calls["n"] += 1

        slept = []
        assert fleet._commit_launched_turn(commit, sleep=slept.append) is True
        assert calls["n"] == 1
        assert slept == []

    def test_retries_with_backoff_then_succeeds(self):
        calls = {"n": 0}

        def commit():
            calls["n"] += 1
            if calls["n"] < 3:
                raise fleet.FleetLockTimeout("simulated")

        slept = []
        assert fleet._commit_launched_turn(commit, sleep=slept.append) is True
        assert calls["n"] == 3
        assert slept == list(fleet.LAUNCH_COMMIT_BACKOFF_SECONDS[:2])

    def test_exhausts_every_attempt_and_returns_false(self):
        calls = {"n": 0}

        def commit():
            calls["n"] += 1
            raise fleet.FleetLockTimeout("simulated")

        slept = []
        assert fleet._commit_launched_turn(commit, sleep=slept.append) is False
        assert calls["n"] == fleet.LAUNCH_COMMIT_MAX_ATTEMPTS
        assert len(slept) == fleet.LAUNCH_COMMIT_MAX_ATTEMPTS - 1

    def test_non_timeout_exception_propagates_without_retry(self):
        def commit():
            raise ValueError("some other bug")

        with pytest.raises(ValueError):
            fleet._commit_launched_turn(commit, sleep=lambda s: None)

    def test_oserror_retried_like_lock_timeout_then_succeeds(self):
        # Debt roll-up item 3: a transient non-lock OSError (Windows sharing
        # violation on save_registry) gets the same backoff as
        # FleetLockTimeout instead of escaping raw to the caller.
        calls = {"n": 0}

        def commit():
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("sharing violation")

        slept = []
        assert fleet._commit_launched_turn(commit, sleep=slept.append) is True
        assert calls["n"] == 3
        assert slept == list(fleet.LAUNCH_COMMIT_BACKOFF_SECONDS[:2])

    def test_oserror_exhaustion_returns_false_and_reports(self, capsys):
        # Debt roll-up item 3: on exhaustion the OSError folds into the same
        # False return (turn IS launched -- caller must go down the
        # _report_stranded_* path, never see the raw exception, which would
        # read as a failed launch and tempt a double-launch retry) and is
        # named on stderr so it is not silently indistinguishable from a
        # plain lock timeout.
        def commit():
            raise OSError(28, "No space left on device")

        assert fleet._commit_launched_turn(commit, sleep=lambda s: None) is False
        err = capsys.readouterr().err
        assert "No space left on device" in err


class TestCmdSpawnNativeCommitLockRetry:
    """T4 fix wave (Critical C2): port of the legacy TestCmdSpawnCommitLockRetry
    onto the native flow -- cmd_spawn's post-dispatch stamp lock (after
    dispatch_bg already returned a real, joined sid) is now wrapped in
    _commit_launched_turn's retry+backoff, same machinery as the legacy
    launch path, via a monkeypatched `fleet.fleet_lock` that fails the
    stamp-lock acquisitions specifically (the pre-claim lock, called
    first, is left alone) -- exercises the real call sites, not a
    fabricated stand-in."""

    def _flaky_fleet_lock(self, fail_calls):
        real_fleet_lock = fleet.fleet_lock
        calls = {"n": 0}

        @contextmanager
        def flaky(timeout=fleet.LOCK_TIMEOUT_SECONDS):
            calls["n"] += 1
            if calls["n"] in fail_calls:
                raise fleet.FleetLockTimeout("simulated")
            with real_fleet_lock(timeout=timeout):
                yield

        return flaky

    def test_retries_past_a_flaky_stamp_lock_then_succeeds(self, isolated_home, tmp_path, monkeypatch):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())

        # Call 1 = the pre-claim lock (must succeed). Calls 2 and 3 = the
        # post-dispatch stamp lock's first two attempts (fail); call 4 =
        # the third attempt (succeeds).
        monkeypatch.setattr(fleet, "fleet_lock", self._flaky_fleet_lock({2, 3}))

        slept = []
        args = _spawn_args("probe-1", worker_dir, "do it")
        rc = fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd",
                             sleep=slept.append)

        assert rc == 0
        assert slept == list(fleet.LAUNCH_COMMIT_BACKOFF_SECONDS[:2])
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["session_id"] == NATIVE_SID

    def test_gives_up_loudly_without_stamping_and_returns_nonzero(
        self, isolated_home, tmp_path, monkeypatch, capsys,
    ):
        """If every stamp-lock attempt times out, cmd_spawn must NOT pop
        the pre-claim record (a live session genuinely exists -- popping
        would orphan it beyond even the stranded-turn recovery
        instructions) and must NOT raise raw: a loud stderr warning
        carrying the sid/short_id an operator needs to stamp by hand, plus
        a NONZERO return (unlike legacy's rc==0 -- native has no OS pid
        fallback, so the failure signal here has to be louder, per the T4
        fix-wave brief)."""
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())

        # Call 1 = the pre-claim lock (succeeds); every call from #2 onward
        # (every stamp attempt) fails.
        monkeypatch.setattr(fleet, "fleet_lock", self._flaky_fleet_lock(set(range(2, 30))))

        slept = []
        args = _spawn_args("probe-1", worker_dir, "do it")
        rc = fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd",
                             sleep=slept.append)

        assert rc != 0
        assert len(slept) == fleet.LAUNCH_COMMIT_MAX_ATTEMPTS - 1
        err = capsys.readouterr().err
        assert "CRITICAL" in err
        assert "probe-1" in err
        assert NATIVE_SID in err
        assert "aaaabbbb" in err

        # The pre-claim record is left exactly where it was -- NOT popped
        # (the session is genuinely live) and NOT stamped (the stamp lock
        # never landed): session_id is still None, the pre-claim state --
        # the recovery message above is the ONLY place the real sid/short
        # id survive; the operator must hand-stamp the record using it.
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["session_id"] is None

        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "turn_commit_failed" and e["session_id"] == NATIVE_SID for e in events)


class TestCmdSpawnCtrlCMidJoin:
    def test_ctrlc_mid_join_preserves_short_id_in_spawn_failed_event(self, isolated_home, tmp_path, monkeypatch):
        """T4 fix wave (Ctrl-C short-id loss): a KeyboardInterrupt landing
        during dispatch_bg's join-verify wait -- AFTER the --bg dispatch
        itself already succeeded, so a live session genuinely exists --
        must not lose the short id. Previously str(KeyboardInterrupt()) is
        empty, so the spawn_failed event carried zero trace of the
        orphaned session's identity, worse than the sibling DOA-timeout
        branch (whose message embeds the short id in plain text)."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def sleep(s):
            raise KeyboardInterrupt()

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=sleep)

        assert "probe-1" not in fleet.load_registry()["workers"]
        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        spawn_failed = [e for e in events if e["kind"] == "spawn_failed"]
        assert len(spawn_failed) == 1
        assert spawn_failed[0]["short_id"] == "aaaabbbb"


class TestCmdSpawnGuardedPopEventSymmetry:
    """T4 fix wave (Minor): the spawn_failed event must fire ONLY when the
    guarded pop actually pops the record -- adversarial fault injection
    proved zero coverage for this in either exception branch (weakening
    `rec.get("session_id") is None` down to just `rec is not None` stayed
    green in the full suite for both). These pin both conditions in both
    branches, so that regression would go red."""

    def test_native_dispatch_error_concurrent_stamp_no_pop_no_event(self, isolated_home, tmp_path):
        import types
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        real_sid = "cccccccc-1111-2222-3333-444455556666"

        def run(argv, **kwargs):
            # Simulate a concurrent process (e.g. a fast-completion commit
            # racing in from elsewhere) stamping the record with a real sid
            # before this dispatch's own failure handler re-locks.
            data = fleet.load_registry()
            data["workers"]["probe-1"]["session_id"] = real_sid
            data["workers"]["probe-1"]["status"] = "working"
            fleet.save_registry(data)
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == real_sid  # not clobbered by the DOA rollback
        kinds = [json.loads(line)["kind"] for line in
                fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert kinds == ["spawned"]  # no spawn_failed -- nothing actually failed

    def test_native_dispatch_error_unstamped_pops_and_events(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=_fake_run_factory(rc=1), which=lambda n: "claude.cmd",
                            sleep=lambda s: None)

        assert "probe-1" not in fleet.load_registry()["workers"]
        kinds = [json.loads(line)["kind"] for line in
                fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert kinds == ["spawned", "spawn_failed"]

    def test_base_exception_concurrent_stamp_no_pop_no_event(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        real_sid = "cccccccc-1111-2222-3333-444455556666"

        def run(argv, **kwargs):
            data = fleet.load_registry()
            data["workers"]["probe-1"]["session_id"] = real_sid
            data["workers"]["probe-1"]["status"] = "working"
            fleet.save_registry(data)
            raise KeyboardInterrupt()

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == real_sid
        kinds = [json.loads(line)["kind"] for line in
                fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert kinds == ["spawned"]

    def test_base_exception_unstamped_pops_and_events(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def run(argv, **kwargs):
            raise KeyboardInterrupt()

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_spawn(args, run=run, which=lambda n: "claude.cmd", sleep=lambda s: None)

        assert "probe-1" not in fleet.load_registry()["workers"]
        kinds = [json.loads(line)["kind"] for line in
                fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert kinds == ["spawned", "spawn_failed"]


class TestCmdSpawnStampEventSymmetry:
    def test_success_stamp_skips_turn_started_event_when_record_concurrently_removed(
        self, isolated_home, tmp_path, monkeypatch,
    ):
        """T4 fix wave (Minor M1, event-symmetry nit from task-4-review.md):
        the success-stamp block's append_event("turn_started", ...) now
        lives inside the same `if rec is not None:` guard as the mutation
        it describes, matching the fast-completion commit block's shape --
        previously it fired unconditionally, so a concurrent kill/clean
        landing in the inter-lock gap produced a turn_started event for a
        registry mutation that never happened."""
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        state = {"n": 0}

        def roster_fetch(**_):
            # Call-count-aware like _native_roster_with: 1st call is
            # dispatch_bg's pre-dispatch snapshot (must stay empty, or the
            # real sid would be excluded from its own join as a "foreign
            # pre-existing session"). From the 2nd call (the join poll)
            # onward, report the session AND simulate a concurrent `fleet
            # clean`/`kill` removing the record entirely right as the join
            # completes (the inter-lock gap this fix targets).
            state["n"] += 1
            if state["n"] == 1:
                return True, []
            data = fleet.load_registry()
            data["workers"].pop("probe-1", None)
            fleet.save_registry(data)
            return True, [{"id": "aaaabbbb", "sessionId": NATIVE_SID,
                          "name": "fleet|probe-1|t", "cwd": str(worker_dir),
                          "startedAt": 1, "kind": "background", "state": "working",
                          "status": "busy", "pid": 1}]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster_fetch)
        args = _spawn_args("probe-1", worker_dir, "do the thing")
        rc = fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd",
                             sleep=lambda s: None)

        assert rc == 0  # the launch itself still succeeds/reports normally
        assert "probe-1" not in fleet.load_registry()["workers"]  # stays removed
        kinds = [json.loads(line)["kind"] for line in
                fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert kinds == ["spawned"]  # no turn_started -- nothing was mutated


def _seed_record(worker_dir):
    rec = fleet.new_worker_record(str(uuid.uuid4()), worker_dir, "existing task", "dontask")
    return rec


# ---------------------------------------------------------------------------
# cmd_status transitions (native verdict engine wired through the CLI)
# ---------------------------------------------------------------------------


def _seed_native(name, sid=None, status=None, fresh_outcome=False):
    """Save one native worker record; optionally a fresh result outcome so a
    roster-idle verdict resolves to idle instead of dead-suspected."""
    sid = sid or str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask", dispatch_kind="bg")
    rec["last_dispatch_at"] = fleet.now_iso()
    if status is not None:
        rec["status"] = status
    fleet.save_registry({"workers": {name: rec}})
    if fresh_outcome:
        fleet.append_outcome(name, {"ts": fleet.now_iso(), "session_id": sid,
                                    "kind": "result", "result_text": "all set"})
    return sid, rec


class TestCmdStatus:
    def test_status_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["status", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_status(args)

    def test_status_prints_table_with_all_workers(self, isolated_home, capsys, monkeypatch):
        sid1, _ = _seed_native("probe-1")
        sid2 = str(uuid.uuid4())
        data = fleet.load_registry()
        rec2 = fleet.new_worker_record(sid2, "C:/y", "task2", "bypass", dispatch_kind="bg")
        data["workers"]["probe-2"] = rec2
        fleet.save_registry(data)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid1), _make_native_roster_entry(sid2)]))
        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "probe-1" in out
        assert "probe-2" in out

    def test_status_flags_idle_with_pending_mail(self, isolated_home, capsys, monkeypatch):
        sid, _ = _seed_native("probe-1", fresh_outcome=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="idle")]))
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("please check X", encoding="utf-8")

        args = fleet.build_parser().parse_args(["status"])
        fleet.cmd_status(args)
        out = capsys.readouterr().out
        assert "idle+mail" in out

    def test_status_persists_recomputed_status(self, isolated_home, monkeypatch):
        sid, _ = _seed_native("probe-1", fresh_outcome=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="idle")]))

        args = fleet.build_parser().parse_args(["status", "probe-1"])
        fleet.cmd_status(args)

        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_roster_fetch_does_not_hold_fleet_lock(self, isolated_home, monkeypatch):
        """Stress-report Finding 1 heritage: cmd_status must run its roster
        fetch/recompute with NO fleet_lock held. A roster fetch that itself
        tries to acquire fleet_lock would raise FleetLockTimeout if
        cmd_status still held the lock across it."""
        sid, _ = _seed_native("probe-1")

        def probing_fetch(**_):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout
            return True, [_make_native_roster_entry(sid)]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", probing_fetch)
        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args)
        assert rc == 0

    def test_concurrent_mutation_during_probe_is_not_clobbered(self, isolated_home, monkeypatch):
        """A worker mutated by a concurrent command while cmd_status's lock
        is released for the roster fetch must be spared -- cmd_status must
        not overwrite that concurrent write with a verdict computed against
        now-stale pre-probe data."""
        sid, _ = _seed_native("probe-1", fresh_outcome=True)

        def mutating_fetch(**_):
            data = fleet.load_registry()
            data["workers"]["probe-1"]["turns"] = 999
            fleet.save_registry(data)
            return True, [_make_native_roster_entry(sid, status="idle")]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", mutating_fetch)
        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args)
        assert rc == 0
        assert fleet.load_registry()["workers"]["probe-1"]["turns"] == 999


# ---------------------------------------------------------------------------
# cmd_peek (native transcript digest)
# ---------------------------------------------------------------------------

class TestCmdPeek:
    def test_peek_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["peek", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_peek(args)

    def test_peek_prints_transcript_digest(self, isolated_home, capsys, monkeypatch):
        sid, _ = _seed_native("probe-1")
        transcript = isolated_home / "transcript.jsonl"
        transcript.write_text(
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}\n'
            '{"type":"assistant","message":{"content":[{"type":"text","text":"all done"}]}}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, s: transcript)
        args = fleet.build_parser().parse_args(["peek", "probe-1"])
        rc = fleet.cmd_peek(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Bash" in out
        assert "all done" in out

    def test_peek_no_transcript_yet_exits_nonzero_with_hint(self, isolated_home, capsys, monkeypatch):
        _seed_native("probe-1")
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, s: None)
        args = fleet.build_parser().parse_args(["peek", "probe-1"])
        rc = fleet.cmd_peek(args)
        assert rc == 1
        assert "no transcript" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_result
# ---------------------------------------------------------------------------

class TestCmdResult:
    def test_result_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["result", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_result(args)

    def test_result_prints_final_result_text_only(self, isolated_home, capsys):
        sid, _ = _seed_native("probe-1")
        fleet.append_outcome("probe-1", {"ts": fleet.now_iso(), "session_id": sid,
                                         "kind": "result",
                                         "result_text": "the final answer"})
        args = fleet.build_parser().parse_args(["result", "probe-1"])
        rc = fleet.cmd_result(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "the final answer"

    def test_result_none_yet_prints_clear_message_and_nonzero(self, isolated_home, capsys):
        _seed_native("probe-1")
        args = fleet.build_parser().parse_args(["result", "probe-1"])
        rc = fleet.cmd_result(args)
        assert rc != 0
        assert "no outcome record" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# wait_for_workers / cmd_wait
# ---------------------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class TestWaitForWorkers:
    def test_all_mode_waits_for_every_worker(self, isolated_home, monkeypatch):
        sid1, _ = _seed_native("probe-1", fresh_outcome=True)
        sid2 = str(uuid.uuid4())
        data = fleet.load_registry()
        rec2 = fleet.new_worker_record(sid2, "C:/y", "t2", "dontask", dispatch_kind="bg")
        rec2["last_dispatch_at"] = fleet.now_iso()
        data["workers"]["probe-2"] = rec2
        fleet.save_registry(data)
        fleet.append_outcome("probe-2", {"ts": fleet.now_iso(), "session_id": sid2,
                                         "kind": "result"})

        calls = {"n": 0}

        def fetch(**_):
            calls["n"] += 1
            # probe-1 idles immediately; probe-2 stays busy for two polls.
            e2_status = "idle" if calls["n"] > 2 else "busy"
            return True, [_make_native_roster_entry(sid1, status="idle"),
                          _make_native_roster_entry(sid2, status=e2_status)]

        monkeypatch.setattr(fleet, "_fetch_agents_roster", fetch)
        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1", "probe-2"], mode="all", timeout=None, poll_interval=1.0,
            sleep=clock.sleep, clock=clock.now,
        )
        assert pending == set()
        assert finished == {"probe-1": "idle", "probe-2": "idle"}


# ---------------------------------------------------------------------------
# F-TEST-CORRUPT: RegistryCorruptError must propagate through the CLI layer
# to main()'s dedicated handler -- never swallowed, never degraded to an
# empty registry (spec review Minor 2).
# ---------------------------------------------------------------------------

class TestRegistryCorruptPropagatesThroughMain:
    def test_corrupt_registry_reaches_mains_dedicated_handler(self, isolated_home, capsys):
        state = isolated_home / "state"
        # exist_ok=True: the isolated_home fixture (SPEC §14) already creates
        # state/ to stub a worker-settings.json instance.
        state.mkdir(parents=True, exist_ok=True)
        (state / "fleet.json").write_text("{not json", encoding="utf-8")

        rc = fleet.main(["status"])

        assert rc == 1
        err = capsys.readouterr().err
        assert "registry error" in err.lower()

    def test_corrupt_registry_raised_not_caught_at_cmd_level(self, isolated_home):
        state = isolated_home / "state"
        # exist_ok=True: the isolated_home fixture (SPEC §14) already creates
        # state/ to stub a worker-settings.json instance.
        state.mkdir(parents=True, exist_ok=True)
        (state / "fleet.json").write_text("{not json", encoding="utf-8")

        args = fleet.build_parser().parse_args(["status"])
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_status(args)

    def test_any_mode_returns_as_soon_as_one_finishes(self, isolated_home, monkeypatch):
        sid1, _ = _seed_native("probe-1", fresh_outcome=True)
        sid2 = str(uuid.uuid4())
        data = fleet.load_registry()
        rec2 = fleet.new_worker_record(sid2, "C:/y", "t2", "dontask", dispatch_kind="bg")
        rec2["last_dispatch_at"] = fleet.now_iso()
        data["workers"]["probe-2"] = rec2
        fleet.save_registry(data)

        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid1, status="idle"),
            _make_native_roster_entry(sid2, status="busy")]))
        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1", "probe-2"], mode="any", timeout=None, poll_interval=1.0,
            sleep=clock.sleep, clock=clock.now,
        )
        assert finished == {"probe-1": "idle"}
        assert pending == {"probe-2"}

    def test_timeout_leaves_pending_nonempty(self, isolated_home, monkeypatch):
        sid, _ = _seed_native("probe-1")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="busy")]))

        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1"], mode="all", timeout=5.0, poll_interval=1.0,
            sleep=clock.sleep, clock=clock.now,
        )
        assert finished == {}
        assert pending == {"probe-1"}


class TestCmdWait:
    def test_wait_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["wait", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_wait(args, sleep=lambda s: None, clock=lambda: 0.0)

    def test_wait_all_prints_finish_and_returns_zero(self, isolated_home, capsys, monkeypatch):
        sid, _ = _seed_native("probe-1", fresh_outcome=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="idle")]))

        args = fleet.build_parser().parse_args(["wait", "probe-1"])
        rc = fleet.cmd_wait(args, sleep=lambda s: None, clock=lambda: 0.0)

        assert rc == 0
        out = capsys.readouterr().out
        assert "probe-1" in out
        assert "all set" in out
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_wait_timeout_returns_nonzero(self, isolated_home, capsys, monkeypatch):
        sid, _ = _seed_native("probe-1")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="busy")]))

        clock = FakeClock()
        args = fleet.build_parser().parse_args(["wait", "probe-1", "--timeout", "3"])
        rc = fleet.cmd_wait(args, sleep=clock.sleep, clock=clock.now)
        assert rc != 0
        assert "timed out" in capsys.readouterr().out

    def test_wait_any_success_with_pending_returns_zero_and_says_still_working(
            self, isolated_home, capsys, monkeypatch):
        """Post-testing wave, item 4 (live-report scenario 2): `wait --any`
        returning as soon as ONE worker finishes, with others still
        pending, is success -- not a timeout. Must exit 0 and must not
        call the still-running worker "timed out"."""
        sid_fast, _ = _seed_native("probe-fast", fresh_outcome=True)
        sid_slow = str(uuid.uuid4())
        data = fleet.load_registry()
        rec_slow = fleet.new_worker_record(sid_slow, "C:/y", "t2", "dontask", dispatch_kind="bg")
        rec_slow["last_dispatch_at"] = fleet.now_iso()
        data["workers"]["probe-slow"] = rec_slow
        fleet.save_registry(data)

        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid_fast, status="idle"),
            _make_native_roster_entry(sid_slow, status="busy")]))

        args = fleet.build_parser().parse_args(["wait", "probe-fast", "probe-slow", "--any"])
        rc = fleet.cmd_wait(args, sleep=lambda s: None, clock=lambda: 0.0)

        assert rc == 0
        out = capsys.readouterr().out
        assert "probe-slow: still working" in out
        assert "timed out" not in out


# ---------------------------------------------------------------------------
# argparse wiring smoke tests
# ---------------------------------------------------------------------------

class TestArgparseWiring:
    def test_spawn_requires_dir_and_task(self):
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["spawn", "probe-1"])

    def test_spawn_default_mode_is_dontask(self):
        args = fleet.build_parser().parse_args(["spawn", "probe-1", "--dir", "C:/x", "--task", "t"])
        assert args.mode == "dontask"

    def test_spawn_rejects_unknown_mode(self):
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["spawn", "probe-1", "--dir", "C:/x", "--task", "t", "--mode", "yolo"])

    def test_wait_all_and_any_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["wait", "probe-1", "--any", "--all"])

    def test_status_name_optional(self):
        args = fleet.build_parser().parse_args(["status"])
        assert args.name is None


# ---------------------------------------------------------------------------
# Kernel 1 (fleet-side) -- hook-error count surfaced in `fleet status`
# ---------------------------------------------------------------------------

class TestStatusHookErrorCount:
    def _seed_idle(self, monkeypatch, name="probe-1"):
        sid, _ = _seed_native(name, fresh_outcome=True)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
            _make_native_roster_entry(sid, status="idle")]))

    def test_no_hook_errors_no_footer(self, isolated_home, capsys, monkeypatch):
        self._seed_idle(monkeypatch)
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]))
        out = capsys.readouterr().out
        assert "hook-error" not in out

    def test_hook_error_count_shown_when_nonzero(self, isolated_home, capsys, monkeypatch):
        self._seed_idle(monkeypatch)
        fleet.hook_errors_path().write_text(
            "2026-07-08T00:00:00Z s1 err\n2026-07-08T00:01:00Z s2 err\n2026-07-08T00:02:00Z s3 err\n",
            encoding="utf-8",
        )
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]))
        out = capsys.readouterr().out
        assert "hook-error" in out
        assert "3" in out


# ---------------------------------------------------------------------------
# Kernel 5 -- spawn-time model echo
# ---------------------------------------------------------------------------

class TestSpawnModelEcho:
    def test_echoes_resolved_model(self, isolated_home, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "do the thing", model="opus")
        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "model" in out
        assert "opus" in out

    def test_echoes_subagent_model_env_when_set(self, isolated_home, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "haiku")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _native_roster_with())
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "do the thing", model="opus")
        fleet.cmd_spawn(args, run=_fake_run_factory(), which=lambda n: "claude.cmd", sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "CLAUDE_CODE_SUBAGENT_MODEL" in out
        assert "haiku" in out
