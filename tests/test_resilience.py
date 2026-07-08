"""Unit tests for Task 5 (M4 resilience): respawn / kill / clean / doctor,
plus the spec-audit-gap items (spawn --setting-sources passthrough, peek
tokens, and the tail-read perf optimization for status/wait polling).

Same discipline as test_steering.py / test_cli.py: no real claude process,
no real taskkill/PowerShell/wt/claude-agents subprocess is ever invoked in
the state-machine tests -- every test injects a fake popen /
get_process_info / which / kill_process_tree / run. The doctor hook-smoke
checks are the one deliberate exception (SPEC's "end-to-end" requirement):
those run the real hook scripts as real subprocesses against a scratch
temp FLEET_HOME, mirroring tests/test_hooks.py's own technique.
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


def _seed_worker(name, status=None, turn_pid=None, turn_pid_ctime=None,
                  cwd=None, mode="dontask", model=None, sid=None,
                  task="original task text", log_result=False, cost_usd=0.0):
    # Kernel 4 cwd preflight: launch_turn now refuses to launch into a
    # vanished cwd, so the default seeded cwd must be a real directory
    # (FLEET_HOME, created by the isolated_home fixture). Tests that need a
    # specific cwd pass it explicitly and create it themselves.
    if cwd is None:
        cwd = str(fleet.FLEET_HOME)
    sid = sid or str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, cwd, task, mode, model=model)
    if status is not None:
        rec["status"] = status
    rec["turn_pid"] = turn_pid
    rec["turn_pid_ctime"] = turn_pid_ctime
    rec["cost_usd"] = cost_usd
    data = fleet.load_registry()  # merge, not overwrite -- tests may seed several workers
    data["workers"][name] = rec
    fleet.save_registry(data)
    if log_result:
        log = fleet.logs_dir() / f"{name}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f'{{"type":"result","result":"done","total_cost_usd":{cost_usd}}}\n', encoding="utf-8",
        )
    return sid, rec


# ---------------------------------------------------------------------------
# _rotate_worker_log
# ---------------------------------------------------------------------------

class TestRotateWorkerLog:
    def test_rotates_jsonl_and_err(self, isolated_home):
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "probe-1.jsonl").write_text("old jsonl", encoding="utf-8")
        (logs / "probe-1.err").write_text("old err", encoding="utf-8")

        fleet._rotate_worker_log("probe-1")

        assert not (logs / "probe-1.jsonl").exists()
        assert not (logs / "probe-1.err").exists()
        assert (logs / "probe-1.jsonl.1").read_text(encoding="utf-8") == "old jsonl"
        assert (logs / "probe-1.err.1").read_text(encoding="utf-8") == "old err"

    def test_overwrites_existing_dot_one(self, isolated_home):
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "probe-1.jsonl").write_text("newer", encoding="utf-8")
        (logs / "probe-1.jsonl.1").write_text("stale-from-a-prior-respawn", encoding="utf-8")

        fleet._rotate_worker_log("probe-1")

        assert (logs / "probe-1.jsonl.1").read_text(encoding="utf-8") == "newer"

    def test_missing_logs_is_a_noop(self, isolated_home):
        fleet._rotate_worker_log("nope")  # must not raise


# ---------------------------------------------------------------------------
# fleet respawn
# ---------------------------------------------------------------------------

class TestCmdRespawn:
    def test_missing_instance_settings_raises(self, isolated_home):
        fleet.instance_settings_path().unlink()
        _seed_worker("probe-1", status="idle", log_result=True)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.FleetCliError, match="fleet init"):
            fleet.cmd_respawn(args, get_process_info=_dead_info, which=lambda n: "claude.cmd")

    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["respawn", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_respawn(args, get_process_info=_dead_info)

    def test_refuses_while_working_without_force(self, isolated_home):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def popen(*a, **kw):
            raise AssertionError("must not launch while refusing")

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_alive_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"

    def test_force_refuses_during_launch_in_flight(self, isolated_home):
        _seed_worker("probe-1", status="working", turn_pid=None)

        def kill_process_tree(pid):
            raise AssertionError("must not attempt a kill with no real pid yet")

        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_respawn(
                args, get_process_info=_dead_info, which=lambda n: "claude.cmd",
                kill_process_tree=kill_process_tree,
            )
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None

    def test_force_raises_when_kill_verification_fails(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def popen(*a, **kw):
            raise AssertionError("must not launch when --force kill verification fails")

        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_respawn(
                args, popen=popen, get_process_info=_alive_info, which=lambda n: "claude.cmd",
                kill_process_tree=lambda pid: None,
            )
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["session_id"] == old_sid  # never replaced

    def test_force_interrupts_then_respawns(self, isolated_home):
        old_sid, _ = _seed_worker(
            "probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cost_usd=2.5,
        )
        killed = {"done": False}

        def kill_process_tree(pid):
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        proc = FakeProc(pid=999)
        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        rc = fleet.cmd_respawn(
            args, popen=_fake_popen(proc), get_process_info=get_process_info, which=lambda n: "claude.cmd",
            kill_process_tree=kill_process_tree,
        )

        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] != old_sid
        assert rec["status"] == "working"
        assert rec["turn_pid"] == 999
        assert rec["turns"] == 1
        assert rec["cost_usd"] == 2.5  # cumulative, carried over

    def test_force_refuses_when_reclaimed_between_interrupt_and_relock(self, isolated_home, monkeypatch):
        """F1 (final-review.md): mirrors cmd_attach's own regression test --
        the window between _interrupt_worker's idle-commit (releasing its
        own lock) and respawn's re-lock is exactly where a concurrent
        `fleet send` can pre-claim status="working"/turn_pid=None for a
        brand-new launch. Simulate it by having the (faked) interrupt path
        leave that concurrent pre-claim instead of idle before reporting
        "killed": respawn's re-lock must refuse instead of overwriting the
        record with a new-sid record (which would orphan the send-launched
        turn against the old sid while the registry tracks the new one)."""
        old_sid, _ = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def fake_interrupt_worker(name, get_process_info=None, kill_process_tree=None):
            data = fleet.load_registry()
            rec = data["workers"][name]
            rec["status"] = "working"
            rec["turn_pid"] = None  # the concurrent send's own launch-in-flight claim
            fleet.save_registry(data)
            return "killed"

        monkeypatch.setattr(fleet, "_interrupt_worker", fake_interrupt_worker)

        def popen(*a, **kw):
            raise AssertionError("must not launch over a concurrently reclaimed worker")

        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError, match="claimed concurrently"):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_alive_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None
        assert rec["session_id"] == old_sid  # never replaced

    def test_attached_worker_refuses_respawn_without_force(self, isolated_home):
        """Finding 5 (task-5 adversarial review / task-5-review.md
        Important #2): a live human TUI owns an attached worker's name --
        respawn must mirror cmd_attach's own working-state guard and
        refuse instead of silently stealing it and rerouting the drained
        mailbox into a session the operator never sees."""
        _seed_worker("probe-1", status="attached")

        def popen(*a, **kw):
            raise AssertionError("must not launch while refusing")

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.FleetCliError, match="attached"):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "attached"

    def test_attached_worker_respawns_with_force_and_releases_attach(self, isolated_home):
        """--force proceeds directly (no turn_pid to interrupt) and the
        takeover releases the attach as a side effect (new_worker_record
        always starts attached_since=None)."""
        old_sid, _ = _seed_worker("probe-1", status="attached")
        data = fleet.load_registry()
        data["workers"]["probe-1"]["attached_since"] = "2026-07-07T10:00:00Z"
        fleet.save_registry(data)

        proc = FakeProc(pid=42)
        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        rc = fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["attached_since"] is None
        assert rec["session_id"] != old_sid

    def test_new_uuid_same_name_cwd_mode_model(self, isolated_home, tmp_path):
        proj = tmp_path / "some" / "proj"
        proj.mkdir(parents=True)  # kernel 4 preflight: cwd must really exist
        old_sid, _ = _seed_worker("probe-1", status="idle", cwd=proj.as_posix(), mode="bypass",
                                   model="opus", log_result=True)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert uuid.UUID(rec["session_id"])
        assert rec["session_id"] != old_sid
        assert rec["cwd"] == proj.as_posix()
        assert rec["mode"] == "bypass"
        assert rec["model"] == "opus"

    def test_turns_reset_then_one_after_launch(self, isolated_home):
        _seed_worker("probe-1", status="idle", log_result=True)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert fleet.load_registry()["workers"]["probe-1"]["turns"] == 1

    def test_commit_lock_exhaustion_does_not_abandon_the_launched_turn(
        self, isolated_home, monkeypatch, capsys,
    ):
        """Post-testing wave, item 1b (stress-report Finding 1, CRITICAL --
        "Same defect shape elsewhere"): cmd_respawn's final post-launch
        commit lock is the same unwrapped shape as cmd_spawn's. If every
        retry times out, cmd_respawn must not raise (a real turn is
        already running under new_sid) -- it reports success loudly-with-
        a-warning, same contract as cmd_spawn/cmd_send."""
        _seed_worker("probe-1", status="idle", log_result=True)
        proc = FakeProc(pid=42)

        real_fleet_lock = fleet.fleet_lock
        calls = {"n": 0}

        @contextmanager
        def flaky(timeout=fleet.LOCK_TIMEOUT_SECONDS):
            calls["n"] += 1
            if calls["n"] == 1:
                # cmd_respawn's own pre-claim lock -- must succeed.
                with real_fleet_lock(timeout=timeout):
                    yield
            else:
                # Every post-launch commit attempt fails.
                raise fleet.FleetLockTimeout("simulated")

        monkeypatch.setattr(fleet, "fleet_lock", flaky)

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        rc = fleet.cmd_respawn(
            args, popen=_fake_popen(proc), get_process_info=_dead_info,
            which=lambda n: "claude.cmd", sleep=lambda s: None,
        )

        assert rc == 0
        err = capsys.readouterr().err
        assert "CRITICAL" in err
        assert "probe-1" in err
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None  # never got stamped
        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "turn_commit_failed" for e in events)

    def test_old_sid_recorded_to_events(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="idle", log_result=True)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        respawned = [e for e in events if e["kind"] == "respawned"]
        assert len(respawned) == 1
        assert respawned[0]["old_session_id"] == old_sid

    def test_prompt_includes_journal_and_drains_old_mailbox(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="idle", log_result=True, task="do the original thing")
        journal = fleet.journals_dir() / "probe-1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("goal: ship X\ndone: half of it", encoding="utf-8")
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{old_sid}.md").write_text("manager note before respawn", encoding="utf-8")

        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        prompt = proc.stdin.written.decode("utf-8")
        assert "do the original thing" in prompt
        assert "goal: ship X" in prompt
        assert "manager note before respawn" in prompt
        # consumed, not orphaned
        assert not (mbox / f"{old_sid}.md").exists()
        assert list(mbox.glob("*.claimed.*")) == []

    def test_task_override_replaces_original_task_in_prompt(self, isolated_home):
        _seed_worker("probe-1", status="idle", log_result=True, task="do the original thing")
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--task", "do something else entirely"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        prompt = proc.stdin.written.decode("utf-8")
        assert "do something else entirely" in prompt
        assert "do the original thing" not in prompt
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["task"] == "do something else entirely"

    def test_launches_with_first_true_new_session_id(self, isolated_home):
        _seed_worker("probe-1", status="idle", log_result=True)
        calls = []
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        argv = calls[0][1]
        assert "--session-id" in argv
        assert "--resume" not in argv
        new_sid = fleet.load_registry()["workers"]["probe-1"]["session_id"]
        assert argv[argv.index("--session-id") + 1] == new_sid

    def test_respawn_carries_forward_budget_and_setting_sources(self, isolated_home):
        # F13 (item 7, M5): respawn is a context reset, not a config reset --
        # the persisted max_budget_usd/setting_sources carry forward onto the
        # new record AND onto the fresh-session launch argv (respawn is a
        # launch path too).
        _seed_worker("probe-1", status="idle", log_result=True)
        data = fleet.load_registry()
        data["workers"]["probe-1"]["max_budget_usd"] = 4.0
        data["workers"]["probe-1"]["setting_sources"] = "user,project"
        fleet.save_registry(data)

        calls = []
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["max_budget_usd"] == 4.0
        assert rec["setting_sources"] == "user,project"

        argv = calls[0][1]
        assert argv[argv.index("--max-budget-usd") + 1] == "4.0"
        assert argv[argv.index("--setting-sources") + 1] == "user,project"

    def test_respawn_override_replaces_persisted_budget_and_setting_sources(self, isolated_home):
        # "carries them forward unless explicitly overridden" -- an explicit
        # --max-budget-usd/--setting-sources on respawn replaces the carried
        # value.
        _seed_worker("probe-1", status="idle", log_result=True)
        data = fleet.load_registry()
        data["workers"]["probe-1"]["max_budget_usd"] = 4.0
        data["workers"]["probe-1"]["setting_sources"] = "user,project"
        fleet.save_registry(data)

        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args([
            "respawn", "probe-1", "--max-budget-usd", "9.0", "--setting-sources", "user",
        ])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["max_budget_usd"] == 9.0
        assert rec["setting_sources"] == "user"

    def test_log_rotation_happens_before_launch(self, isolated_home):
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "probe-1.jsonl").write_text("old transcript", encoding="utf-8")
        _seed_worker("probe-1", status="idle", log_result=False)
        # overwrite with old transcript content post-seed (log_result=False
        # above so _seed_worker doesn't clobber our fixture content) --
        # but idle requires a trailing result line for recompute_status,
        # so seed one that still counts as "old transcript" for rotation.
        (logs / "probe-1.jsonl").write_text(
            'old transcript\n{"type":"result","result":"done","total_cost_usd":0.1}\n', encoding="utf-8",
        )
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        assert "old transcript" in (logs / "probe-1.jsonl.1").read_text(encoding="utf-8")
        assert (logs / "probe-1.jsonl").exists()  # launch_turn recreated it (append-mode open)

    def test_pre_claim_working_visible_before_launch(self, isolated_home):
        """Uniform status-claim protocol: by the time popen is reached, a
        fresh registry read must already observe the NEW pre-claimed
        record (status=="working", turn_pid is None)."""
        _seed_worker("probe-1", status="idle", log_result=True)

        def popen(argv, **kwargs):
            rec = fleet.load_registry()["workers"]["probe-1"]
            assert rec["status"] == "working"
            assert rec["turn_pid"] is None
            return FakeProc(pid=555)

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        rc = fleet.cmd_respawn(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert rc == 0

    def test_launch_failure_rolls_back_to_prior_snapshot_and_restores_mailbox(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="idle", log_result=True, cost_usd=1.0)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{old_sid}.md").write_text("pending note", encoding="utf-8")

        def popen(*a, **kw):
            raise OSError("boom")

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == old_sid
        assert rec["cost_usd"] == 1.0
        restored = (mbox / f"{old_sid}.md").read_text(encoding="utf-8")
        assert "pending note" in restored
        assert list(mbox.glob("*.claimed.*")) == []

        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "respawn_failed" for e in events)

    def test_launch_failure_rolls_back_on_keyboard_interrupt(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="idle", log_result=True)

        def popen(*a, **kw):
            raise KeyboardInterrupt()

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == old_sid

    def test_force_path_rollback_restores_idle_old_sid(self, isolated_home):
        """Rollback after a --force respawn must restore the POST-INTERRUPT
        state (old_sid, idle) -- not the stale pre-interrupt "working"
        snapshot, which would falsely resurrect a pid that was just
        killed. turn_pid itself is left as _interrupt_worker's own
        "killed" transition leaves it (it only flips status, exactly like
        cmd_interrupt's own contract) -- not additionally cleared here."""
        old_sid, _ = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed = {"done": False}

        def kill_process_tree(pid):
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        def popen(*a, **kw):
            raise OSError("boom")

        args = fleet.build_parser().parse_args(["respawn", "probe-1", "--force"])
        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_respawn(
                args, popen=popen, get_process_info=get_process_info, which=lambda n: "claude.cmd",
                kill_process_tree=kill_process_tree,
            )

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == old_sid
        assert rec["status"] == "idle"

    def test_launch_failure_rollback_unrotates_log_and_preserves_transcript(self, isolated_home):
        """Finding 1 (task-5 adversarial review): _rotate_worker_log runs
        unconditionally before the launch attempt; if the launch then
        fails, the rollback must un-rotate the log BEFORE restoring the
        registry snapshot, or the restored (old_sid) worker's transcript
        is stranded in .jsonl.1 while the live path sees the empty file
        launch_turn's failed append-open (re-)created -- recomputing to
        "dead" despite the registry correctly saying "idle"."""
        old_sid, _ = _seed_worker("probe-1", status="idle", cost_usd=1.0, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        original_transcript = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":'
            '"original session content XYZ"}]}}\n'
            '{"type":"result","result":"done","total_cost_usd":1.0}\n'
        )
        (logs / "probe-1.jsonl").write_text(original_transcript, encoding="utf-8")

        def popen(*a, **kw):
            raise OSError("boom")

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_respawn(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["session_id"] == old_sid
        assert rec["status"] == "idle"

        # the .1 file must be gone (restored back onto the live path) --
        # not left stranding the real transcript
        assert not (logs / "probe-1.jsonl.1").exists()
        restored = (logs / "probe-1.jsonl").read_text(encoding="utf-8")
        assert "original session content XYZ" in restored
        assert fleet.tail_events(logs / "probe-1.jsonl", n=20)
        assert fleet._last_line_type(logs / "probe-1.jsonl") == "result"
        # the "recompute_status now returns dead from an empty log" defect
        # this fix closes:
        status = fleet.recompute_status(
            None, None, logs / "probe-1.jsonl", current_status="idle", get_process_info=_dead_info,
        )
        assert status == "idle"

    def test_second_respawn_after_failed_respawn_does_not_destroy_history(self, isolated_home):
        """A failed respawn's rollback must leave the worker in a state
        where a SUBSEQUENT (successful) respawn rotates the real restored
        transcript into .1 -- not an empty stub that would permanently
        overwrite it (Finding 1's "destroys history" escalation)."""
        _seed_worker("probe-1", status="idle", log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        original_transcript = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":'
            '"irreplaceable history"}]}}\n'
            '{"type":"result","result":"done","total_cost_usd":0.0}\n'
        )
        (logs / "probe-1.jsonl").write_text(original_transcript, encoding="utf-8")

        def failing_popen(*a, **kw):
            raise OSError("boom")

        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_respawn(args, popen=failing_popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        # second respawn, this time succeeding
        proc = FakeProc(pid=7)
        rc = fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert rc == 0

        assert "irreplaceable history" in (logs / "probe-1.jsonl.1").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# cost_usd cumulative-across-respawns (Finding 4, task-5 adversarial review)
# ---------------------------------------------------------------------------

class TestCostBaseline:
    def test_respawn_stamps_carried_cost_as_new_baseline(self, isolated_home):
        _seed_worker("probe-1", status="idle", log_result=True, cost_usd=2.5)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["cost_usd"] == 2.5
        assert rec["cost_baseline"] == 2.5

    def test_cost_accumulates_after_respawn_and_new_session_result(self, isolated_home):
        """Finding 4: carried 2.50 + a fresh post-respawn session result of
        0.30 must recompute to 2.80, not clobber down to 0.30."""
        _seed_worker("probe-1", status="idle", log_result=True, cost_usd=2.5)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        # simulate the new session's own log gaining its first result event
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.write_text('{"type":"result","result":"done","total_cost_usd":0.3}\n', encoding="utf-8")

        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["cost_usd"] == pytest.approx(2.8)

    def test_recompute_worker_tolerates_missing_cost_baseline_key(self, isolated_home):
        """Old registry records that predate cost_baseline must default it
        to 0.0 rather than raise or misbehave."""
        _seed_worker("probe-1", status="idle", log_result=False, cost_usd=0.0)
        data = fleet.load_registry()
        del data["workers"]["probe-1"]["cost_baseline"]
        fleet.save_registry(data)

        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done","total_cost_usd":0.7}\n', encoding="utf-8")

        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["cost_usd"] == pytest.approx(0.7)

    def test_sums_multiple_result_events_in_one_session(self, isolated_home):
        """SMOKE-B (integration-smoke.md Finding B, live-proven): `claude`
        reports cost PER-INVOCATION on `--resume` turns, not cumulatively --
        observed live where a second send-resumed turn's own result event
        reported a SMALLER total_cost_usd than the first. recompute_worker
        used to take only the LAST result event's cost, so a multi-turn
        `send` sequence within one session (cost_baseline stays 0.0 there,
        it's only set on respawn) would drop the displayed total down to
        just the latest turn instead of the session's real running total.
        Two result events (0.03 + 0.01) in the current log must sum to
        0.04."""
        _seed_worker("probe-1", status="idle", log_result=False, cost_usd=0.0)
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","result":"turn one","total_cost_usd":0.03}\n'
            '{"type":"system","subtype":"hook_response","hook_name":"SessionStart:resume"}\n'
            '{"type":"result","result":"turn two","total_cost_usd":0.01}\n',
            encoding="utf-8",
        )
        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["cost_usd"] == pytest.approx(0.04)

    def test_sums_multiple_result_events_plus_baseline(self, isolated_home):
        """Same as above, but with a nonzero cost_baseline carried from a
        prior respawn -- the sum must still add on top of the baseline,
        not replace it."""
        _seed_worker("probe-1", status="idle", log_result=False, cost_usd=2.5)
        data = fleet.load_registry()
        data["workers"]["probe-1"]["cost_baseline"] = 2.5
        fleet.save_registry(data)
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","result":"turn one","total_cost_usd":0.03}\n'
            '{"type":"result","result":"turn two","total_cost_usd":0.01}\n',
            encoding="utf-8",
        )
        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["cost_usd"] == pytest.approx(2.54)


# ---------------------------------------------------------------------------
# _sum_result_costs / _coerce_cost hardening (fuzz-report Findings F3+F4)
# ---------------------------------------------------------------------------

class TestCostHardening:
    def test_string_cost_is_coerced_when_cleanly_numeric(self, isolated_home):
        """Finding F3 (HIGH): a `total_cost_usd` that arrives as a JSON
        string (e.g. "5.00") used to raise TypeError ('float' + 'str') --
        never raises now, and a cleanly-numeric string is still summed."""
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","total_cost_usd":"5.00","result":"x"}\n', encoding="utf-8")
        assert fleet._sum_result_costs(log) == pytest.approx(5.0)

    def test_non_numeric_string_cost_is_skipped_not_raised(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","total_cost_usd":"garbage","result":"x"}\n', encoding="utf-8")
        # No other result event with a valid cost -> None (nothing to sum).
        assert fleet._sum_result_costs(log) is None

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_cost_is_skipped(self, isolated_home, literal):
        """Finding F4 (MEDIUM): json.loads accepts NaN/Infinity/-Infinity
        by default -- summing one straight in permanently poisons cost_usd
        with no crash and no visible warning. Must be skipped instead."""
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f'{{"type":"result","total_cost_usd":{literal},"result":"x"}}\n', encoding="utf-8")
        assert fleet._sum_result_costs(log) is None

    def test_negative_cost_is_skipped(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","total_cost_usd":-1.5,"result":"x"}\n', encoding="utf-8")
        assert fleet._sum_result_costs(log) is None

    def test_bad_cost_line_among_good_ones_only_drops_the_bad_one(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","total_cost_usd":0.03,"result":"one"}\n'
            '{"type":"result","total_cost_usd":NaN,"result":"two"}\n'
            '{"type":"result","total_cost_usd":0.01,"result":"three"}\n',
            encoding="utf-8",
        )
        assert fleet._sum_result_costs(log) == pytest.approx(0.04)

    def test_recompute_worker_tolerates_poisoned_cost_baseline(self, isolated_home):
        """A registry record whose cost_baseline was already poisoned
        (NaN/Infinity/negative -- e.g. persisted before this hardening
        existed, or hand-edited) must not propagate forward forever:
        _registry_cost falls back to 0.0 instead of contaminating the
        freshly-summed total."""
        _seed_worker("probe-1", status="idle", log_result=False, cost_usd=0.0)
        data = fleet.load_registry()
        data["workers"]["probe-1"]["cost_baseline"] = float("nan")
        fleet.save_registry(data)

        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done","total_cost_usd":0.5}\n', encoding="utf-8")

        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["cost_usd"] == pytest.approx(0.5)

    def test_coerce_cost_rejects_bool(self):
        """A JSON true/false is never a sane cost, even though bool is an
        int subclass in Python."""
        assert fleet._coerce_cost(True) is None
        assert fleet._coerce_cost(False) is None


# ---------------------------------------------------------------------------
# fleet kill
# ---------------------------------------------------------------------------

class TestCmdKill:
    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["kill", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_kill(args, get_process_info=_dead_info)

    def test_refuses_during_launch_in_flight(self, isolated_home):
        """F2 (final-review.md): attach --force and respawn --force both
        refuse on a launch-in-flight claim (status=="working", turn_pid is
        None -- a spawn/send/attach/respawn pre-claim mid-launch, no real
        pid yet to verify-kill); kill lacked this guard. Before the fix,
        kill would snapshot pid=None, pid_alive(None)=False -> "not_running"
        on both probes, and unconditionally mark the worker dead -- opening
        a window for a concurrent `fleet clean` to delete the logs/mailbox
        of a live, just-launched worker (the recompute launch-in-flight
        guard no longer protects a dead+turn_pid=None record)."""
        _seed_worker("probe-1", status="working", turn_pid=None)

        def kill_process_tree(pid):
            raise AssertionError("must not attempt a kill with no real pid yet")

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_kill(args, get_process_info=_dead_info, kill_process_tree=kill_process_tree)

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None

    def test_expired_launch_claim_is_not_refused(self, isolated_home):
        """Post-testing wave, item 1c (zombie escape hatch): a
        "working"/turn_pid=None claim whose last_activity is older than
        LAUNCH_CLAIM_MAX_AGE_SECONDS is no longer a real in-flight launch
        (the launcher stamps a pid within seconds; this old means the
        `fleet` CLI process that owned the launch died mid-claim) -- kill
        must proceed instead of refusing forever."""
        sid, _ = _seed_worker("probe-1", status="working", turn_pid=None)
        data = fleet.load_registry()
        stale = fleet.ctime_to_iso(datetime.now(timezone.utc) - timedelta(seconds=fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS + 1))
        data["workers"]["probe-1"]["last_activity"] = stale
        fleet.save_registry(data)

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(
            args, get_process_info=_dead_info, kill_process_tree=lambda pid: None, sleep=lambda s: None,
        )

        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "dead"

    def test_kills_running_turn_and_marks_dead(self, isolated_home, capsys):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed = {"done": False}

        def kill_process_tree(pid):
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(args, get_process_info=get_process_info, kill_process_tree=kill_process_tree)

        assert rc == 0
        assert "killed" in capsys.readouterr().out
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "dead"
        assert rec["turn_pid"] is None
        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "killed" for e in events)

    def test_idle_worker_is_marked_dead_without_kill_attempt(self, isolated_home):
        _seed_worker("probe-1", status="idle", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)

        def kill_process_tree(pid):
            raise AssertionError("must not attempt a kill when nothing is running")

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(
            args, get_process_info=_dead_info, kill_process_tree=kill_process_tree, sleep=lambda s: None,
        )

        assert rc == 0
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "dead"

    def test_kill_failed_still_marks_dead_but_warns_and_nonzero(self, isolated_home, capsys):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(args, get_process_info=_alive_info, kill_process_tree=lambda pid: None)

        assert rc != 0
        combined = "".join(capsys.readouterr())
        assert "probe-1" in combined
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "dead"

    def test_flaky_once_not_running_probe_still_kills_a_live_worker(self, isolated_home):
        """Finding 3 (task-5 adversarial review): a single get_process_info
        probe returning None can be a transient failure (any exception ->
        None), not a genuinely dead process. Before finalizing "not
        running" -> dead, kill must re-verify after a delay -- and if
        that second probe finds the turn actually alive, kill it for
        real rather than orphaning it as "dead"."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        calls = {"n": 0}
        killed = {"done": False}
        slept = []

        def get_process_info(pid):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # transient false-negative on the first probe
            return None if killed["done"] else _alive_info(pid)

        def kill_process_tree(pid):
            killed["done"] = True

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(
            args, get_process_info=get_process_info, kill_process_tree=kill_process_tree,
            sleep=slept.append,
        )

        assert rc == 0
        assert killed["done"] is True  # the real kill was actually attempted
        assert slept  # the confirm delay was actually taken
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "dead"

    def test_consistently_not_running_worker_is_still_marked_dead(self, isolated_home):
        """Corroborating with a second probe must not block a genuinely
        dead worker from being marked dead."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        calls = {"n": 0}

        def get_process_info(pid):
            calls["n"] += 1
            return None

        def kill_process_tree(pid):
            raise AssertionError("nothing alive to kill")

        args = fleet.build_parser().parse_args(["kill", "probe-1"])
        rc = fleet.cmd_kill(
            args, get_process_info=get_process_info, kill_process_tree=kill_process_tree,
            sleep=lambda s: None,
        )

        assert rc == 0
        assert calls["n"] >= 2  # confirmed via a second probe
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "dead"


# ---------------------------------------------------------------------------
# fleet clean
# ---------------------------------------------------------------------------

class TestCmdClean:
    def test_removes_dead_worker_and_files(self, isolated_home, capsys):
        sid, _ = _seed_worker("dead-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        # no result line + dead pid -> recomputes to "dead"
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "dead-1.jsonl").write_text("junk\n", encoding="utf-8")
        (logs / "dead-1.jsonl.1").write_text("older junk\n", encoding="utf-8")
        (logs / "dead-1.err").write_text("", encoding="utf-8")
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("stray mail", encoding="utf-8")
        journal = fleet.journals_dir() / "dead-1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("journal content", encoding="utf-8")

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=_dead_info, sleep=lambda s: None)

        assert rc == 0
        assert "dead-1" not in fleet.load_registry()["workers"]
        assert not (logs / "dead-1.jsonl").exists()
        assert not (logs / "dead-1.jsonl.1").exists()
        assert not (logs / "dead-1.err").exists()
        assert not (mbox / f"{sid}.md").exists()
        assert not journal.exists()
        out = capsys.readouterr().out
        assert "dead-1" in out
        assert sid in out

    def test_sweeps_orphaned_claimed_files_for_removed_sid(self, isolated_home):
        sid, _ = _seed_worker("dead-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        claimed = mbox / f"{sid}.md.claimed.4321"
        claimed.write_text("orphaned claim litter", encoding="utf-8")

        args = fleet.build_parser().parse_args(["clean"])
        fleet.cmd_clean(args, get_process_info=_dead_info, sleep=lambda s: None)

        assert not claimed.exists()

    def test_flaky_once_probe_does_not_delete_a_live_worker(self, isolated_home):
        """Finding 3 (task-5 adversarial review): clean's deletion is
        irreversible, but "dead" rests on a single pid_alive() probe that
        can misfire on a transient get_process_info failure. A worker
        that looks dead on the first pass but alive on a second, delayed
        probe must NOT be removed."""
        sid, _ = _seed_worker("flaky-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "flaky-1.jsonl").write_text("junk, no trailing result\n", encoding="utf-8")
        calls = {"n": 0}
        slept = []

        def get_process_info(pid):
            calls["n"] += 1
            return None if calls["n"] == 1 else _alive_info(pid)

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=get_process_info, sleep=slept.append)

        assert rc == 0
        assert slept  # the confirm delay was actually taken
        assert "flaky-1" in fleet.load_registry()["workers"]
        assert (logs / "flaky-1.jsonl").exists()
        assert fleet.load_registry()["workers"]["flaky-1"]["status"] == "working"

    def test_consistently_dead_worker_is_still_removed(self, isolated_home):
        """Corroborating with a second probe must not block a genuinely
        dead worker from being cleaned."""
        sid, _ = _seed_worker("dead-2", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "dead-2.jsonl").write_text("junk, no trailing result\n", encoding="utf-8")
        calls = {"n": 0}

        def get_process_info(pid):
            calls["n"] += 1
            return None

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=get_process_info, sleep=lambda s: None)

        assert rc == 0
        assert calls["n"] >= 2  # confirmed via a second probe
        assert "dead-2" not in fleet.load_registry()["workers"]
        assert not (logs / "dead-2.jsonl").exists()

    def test_leaves_idle_working_attached_workers_untouched(self, isolated_home):
        _seed_worker("idle-1", status="idle", log_result=True)
        _seed_worker("working-1", status="working", turn_pid=222, turn_pid_ctime=ALIVE_CTIME)
        _seed_worker("attached-1", status="attached")

        args = fleet.build_parser().parse_args(["clean"])
        fleet.cmd_clean(args, get_process_info=_alive_info)

        workers = fleet.load_registry()["workers"]
        assert set(workers) == {"idle-1", "working-1", "attached-1"}

    def test_nothing_to_clean_prints_friendly_message(self, isolated_home, capsys):
        _seed_worker("idle-1", status="idle", log_result=True)
        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=_dead_info)
        assert rc == 0
        assert "nothing to clean" in capsys.readouterr().out

    def test_confirm_delay_does_not_hold_fleet_lock(self, isolated_home):
        """Review wave 5b: the dead-confirm sleep must not run inside
        `with fleet_lock()` -- it used to, blocking every concurrent fleet
        command for _DEAD_CONFIRM_DELAY_SECONDS. Reuses the reentrancy/
        lock-probe technique from
        test_snapshots_registry_without_holding_lock_across_checks: a fake
        `sleep` that tries to acquire fleet_lock itself. If cmd_clean
        still held the lock across the sleep, this nested acquisition
        would raise FleetLockTimeout."""
        _seed_worker("dead-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "dead-1.jsonl").write_text("junk, no trailing result\n", encoding="utf-8")

        def probing_sleep(seconds):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=_dead_info, sleep=probing_sleep)

        assert rc == 0
        assert "dead-1" not in fleet.load_registry()["workers"]

    def test_first_pass_probe_does_not_hold_fleet_lock(self, isolated_home):
        """Stress residual, Finding N1 (re-review of 550df0a): clean's FIRST
        pass used to call recompute_worker's real probe for every worker
        inside the single `with fleet_lock():` block -- the same
        recompute-all-under-lock shape that made `fleet status` a
        stress-critical (see test_cli.py's
        TestCmdStatus.test_probe_does_not_hold_fleet_lock). Reuses the same
        nested-lock probe technique as
        test_confirm_delay_does_not_hold_fleet_lock: a fake
        get_process_info that itself tries to acquire fleet_lock. If
        cmd_clean's first pass still held the lock across this probe, the
        nested acquisition would raise FleetLockTimeout."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "probe-1.jsonl").write_text("junk, no trailing result\n", encoding="utf-8")

        def probing_get_process_info(pid):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout
            return _alive_info(pid)  # keep it alive/non-dead -- not the point of this test

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=probing_get_process_info, sleep=lambda s: None)
        assert rc == 0

    def test_respawned_meanwhile_is_spared_not_deleted(self, isolated_home):
        """A worker that looks dead on pass 1 but gets respawned (registry
        entry mutated) by a concurrent command while clean's lock is
        released for the confirm sleep must be spared -- clean must not
        delete or overwrite it on the strength of a verdict computed
        against now-stale pre-sleep data."""
        sid, _ = _seed_worker("respawn-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "respawn-1.jsonl").write_text("junk, no trailing result\n", encoding="utf-8")

        def respawn_meanwhile(seconds):
            data = fleet.load_registry()
            data["workers"]["respawn-1"]["turn_pid"] = 999
            data["workers"]["respawn-1"]["turn_pid_ctime"] = ALIVE_CTIME
            data["workers"]["respawn-1"]["status"] = "working"
            fleet.save_registry(data)

        args = fleet.build_parser().parse_args(["clean"])
        rc = fleet.cmd_clean(args, get_process_info=_dead_info, sleep=respawn_meanwhile)

        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert "respawn-1" in workers
        assert workers["respawn-1"]["turn_pid"] == 999


# ---------------------------------------------------------------------------
# fleet doctor -- individual checks
# ---------------------------------------------------------------------------

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
    def test_stale_pid_reported_but_ok(self, isolated_home):
        _, rec = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        workers = {"probe-1": rec}
        name, ok, msg = fleet._doctor_check_stale_pids(workers, get_process_info=_dead_info)
        assert ok is True
        assert "probe-1" in msg

    def test_no_stale_pid_when_alive(self, isolated_home):
        _, rec = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        workers = {"probe-1": rec}
        name, ok, msg = fleet._doctor_check_stale_pids(workers, get_process_info=_alive_info)
        assert ok is True
        assert "no stale" in msg

    def test_orphaned_mailbox_reported(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / "unknown-sid.md").write_text("x", encoding="utf-8")
        name, ok, msg = fleet._doctor_check_mailboxes({})
        assert ok is True
        assert "orphaned" in msg

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

    def test_no_mailbox_dir_yet(self, isolated_home):
        name, ok, msg = fleet._doctor_check_orphaned_claims()
        assert ok is True
        assert "no mailbox dir" in msg

    def test_log_sizes_over_threshold_reported(self, isolated_home, monkeypatch):
        logs = fleet.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        big = logs / "probe-1.jsonl"
        big.write_text("x", encoding="utf-8")
        monkeypatch.setattr(fleet, "_LOG_SIZE_WARN_BYTES", 0)  # force over-threshold without a real 50MB file
        name, ok, msg = fleet._doctor_check_log_sizes()
        assert ok is True
        assert "probe-1.jsonl" in msg

    def test_no_big_logs(self, isolated_home):
        name, ok, msg = fleet._doctor_check_log_sizes()
        assert ok is True
        assert "no log files" in msg


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
    def test_build_turn_argv_includes_flag_when_given(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit",
                                      setting_sources="user,project")
        assert "--setting-sources" in argv
        assert argv[argv.index("--setting-sources") + 1] == "user,project"

    def test_build_turn_argv_omits_flag_when_absent(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit")
        assert "--setting-sources" not in argv

    def test_spawn_plumbs_setting_sources_through(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        calls = []
        proc = FakeProc(pid=1)
        args = fleet.build_parser().parse_args(
            ["spawn", "probe-1", "--dir", str(worker_dir), "--task", "do it", "--setting-sources", "project"]
        )
        fleet.cmd_spawn(args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        argv = calls[0][1]
        assert "--setting-sources" in argv
        assert argv[argv.index("--setting-sources") + 1] == "project"

    def test_spawn_without_setting_sources_omits_flag(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        calls = []
        proc = FakeProc(pid=1)
        args = fleet.build_parser().parse_args(
            ["spawn", "probe-1", "--dir", str(worker_dir), "--task", "do it"]
        )
        fleet.cmd_spawn(args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        assert "--setting-sources" not in calls[0][1]


# ---------------------------------------------------------------------------
# peek tokens (spec-audit gap 5)
# ---------------------------------------------------------------------------

class TestPeekTokens:
    def test_format_tokens_known_keys(self):
        s = fleet._format_tokens({"input_tokens": 10, "output_tokens": 20})
        assert "in=10" in s
        assert "out=20" in s

    def test_format_tokens_empty(self):
        assert fleet._format_tokens({}) == "-"

    def test_format_tokens_unknown_shape_falls_back_to_dump(self):
        s = fleet._format_tokens({"weird_key": 1})
        assert "weird_key" in s

    def test_peek_prints_tokens_alongside_cost(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        fleet.save_registry({"workers": {"probe-1": rec}})
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","result":"all done","total_cost_usd":0.1,'
            '"usage":{"input_tokens":123,"output_tokens":45}}\n',
            encoding="utf-8",
        )
        args = fleet.build_parser().parse_args(["peek", "probe-1"])
        rc = fleet.cmd_peek(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "in=123" in out
        assert "out=45" in out
        assert "$0.10" in out


# ---------------------------------------------------------------------------
# tail-read perf optimization (spec-audit gap: status/wait poll tail reads)
# ---------------------------------------------------------------------------

class TestTailReadPerf:
    def _fabricate_large_log(self, log_path, total_bytes=70_000):
        """Build a >64KB log: a long run of junk padding lines, followed by
        a single well-formed trailing result event."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        padding_line = ("x" * 200) + "\n"
        with open(log_path, "w", encoding="utf-8") as f:
            written = 0
            while written < total_bytes:
                f.write(padding_line)
                written += len(padding_line)
            f.write('{"type":"assistant","message":{"content":"hello from the tail"}}\n')
            f.write('{"type":"result","result":"done at the tail","total_cost_usd":0.42}\n')

    def test_last_line_type_finds_trailing_result_past_64kb(self, isolated_home):
        log = fleet.logs_dir() / "big.jsonl"
        self._fabricate_large_log(log)
        assert log.stat().st_size > fleet._TAIL_READ_BYTES
        assert fleet._last_line_type(log) == "result"

    def test_tail_events_finds_trailing_entries_past_64kb(self, isolated_home):
        log = fleet.logs_dir() / "big.jsonl"
        self._fabricate_large_log(log)
        entries = fleet.tail_events(log, n=20)
        kinds_texts = [(e["kind"], e.get("text")) for e in entries]
        assert ("result", "done at the tail") in kinds_texts

    def test_recompute_status_resolves_idle_on_large_log_with_trailing_result(self, isolated_home):
        log = fleet.logs_dir() / "big.jsonl"
        self._fabricate_large_log(log)
        status = fleet.recompute_status(111, ALIVE_CTIME, log, current_status="working", get_process_info=_dead_info)
        assert status == "idle"

    def test_small_log_unaffected_reads_whole_file(self, isolated_home):
        log = fleet.logs_dir() / "small.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"tiny","total_cost_usd":0.01}\n', encoding="utf-8")
        assert log.stat().st_size < fleet._TAIL_READ_BYTES
        assert fleet._last_line_type(log) == "result"

    def test_partial_leading_line_in_tail_window_is_discarded_not_misparsed(self, isolated_home):
        """When the 64KB window's start lands mid-line, the partial
        fragment must be dropped rather than fed to json.loads as if it
        were a whole line (it would just fail to parse and be skipped
        anyway, but this pins that no spurious data leaks through)."""
        log = fleet.logs_dir() / "big2.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        # Build a log where a padding line straddles the tail-window
        # boundary, then a clean trailing result line.
        with open(log, "wb") as f:
            f.write(b"y" * (fleet._TAIL_READ_BYTES + 50))
            f.write(b"\n")
            f.write(b'{"type":"result","result":"clean tail","total_cost_usd":0.2}\n')
        assert fleet._last_line_type(log) == "result"

    def test_oversized_trailing_line_falls_back_to_whole_file(self, isolated_home):
        """Finding 2 (task-5 adversarial review): if the trailing window's
        ONLY newline is the oversized final line's own terminator,
        "discard up to and including the first newline" drops that whole
        line instead of trimming a partial leading fragment. A single
        stream-json event (e.g. a big result payload) exceeding 64KB must
        not be silently lost -- fall back to a whole-file read."""
        log = fleet.logs_dir() / "bigline.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        result_obj = {"type": "result", "result": "x" * 70_000, "total_cost_usd": 0.55}
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps(result_obj) + "\n")
        assert log.stat().st_size > fleet._TAIL_READ_BYTES

        assert fleet._last_line_type(log) == "result"
        entries = fleet.tail_events(log, n=20)
        assert any(e["kind"] == "result" for e in entries)

    def test_no_newline_anywhere_in_tail_window_falls_back_to_whole_file(self, isolated_home):
        """The window can also contain NO newline at all (an oversized
        final line still being written, with no terminator yet) --
        that must fall back to a whole-file read too, rather than
        parsing an empty/truncated chunk."""
        log = fleet.logs_dir() / "nonl.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "wb") as f:
            f.write(b'{"type":"result","result":"leading","total_cost_usd":0.1}\n')
            f.write(b"z" * (fleet._TAIL_READ_BYTES + 5000))  # no trailing newline yet
        assert log.stat().st_size > fleet._TAIL_READ_BYTES

        lines = fleet._read_tail_lines(log)
        assert any(line.startswith('{"type":"result"') for line in lines)


# ---------------------------------------------------------------------------
# Kernel 1 (fleet-side) -- doctor hook-error tail surfacing
# ---------------------------------------------------------------------------

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

class TestAbnormalTurnEndNote:
    def _crash_log(self, name):
        log = fleet.logs_dir() / f"{name}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"assistant","message":{"content":[]}}\n', encoding="utf-8")

    def test_crash_classification_appends_note(self, isolated_home):
        sid, rec = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        self._crash_log("probe-1")
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["status"] == "dead"
        journal = fleet.journals_dir() / "probe-1.md"
        assert journal.exists()
        assert "turn ended abnormally" in journal.read_text(encoding="utf-8")

    def test_note_written_once_per_crash(self, isolated_home):
        sid, rec = _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        self._crash_log("probe-1")
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        # feeding the now-"dead" record back must not append a second note
        fleet.recompute_worker("probe-1", updated, get_process_info=_dead_info)
        journal = fleet.journals_dir() / "probe-1.md"
        assert journal.read_text(encoding="utf-8").count("turn ended abnormally") == 1

    def test_clean_finish_writes_no_note(self, isolated_home):
        # working -> idle (trailing result) is a NORMAL finish, not a crash
        sid, rec = _seed_worker(
            "probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True,
        )
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["status"] == "idle"
        journal = fleet.journals_dir() / "probe-1.md"
        assert not journal.exists() or "turn ended abnormally" not in journal.read_text(encoding="utf-8")


class TestCwdPreflight:
    def test_launch_turn_refuses_vanished_cwd(self, isolated_home, tmp_path):
        gone = tmp_path / "vanished"  # never created

        def popen(*a, **kw):
            raise AssertionError("must not launch a turn into a vanished cwd")

        with pytest.raises(fleet.TurnLaunchError, match="cwd"):
            fleet.launch_turn(
                "probe-1", gone, "sid-1", "prompt", "dontask",
                popen=popen, which=lambda n: "claude.cmd",
            )
