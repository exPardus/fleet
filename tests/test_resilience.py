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
from datetime import datetime, timezone
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
                  cwd="C:/proj", mode="dontask", model=None, sid=None,
                  task="original task text", log_result=False, cost_usd=0.0):
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

    def test_attached_worker_respawns_directly_without_force(self, isolated_home):
        """Attach never sets turn_pid -- respawn must not treat "attached"
        as "turn running" and must not require --force for it."""
        _seed_worker("probe-1", status="attached")
        proc = FakeProc(pid=42)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        rc = fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"

    def test_new_uuid_same_name_cwd_mode_model(self, isolated_home):
        old_sid, _ = _seed_worker("probe-1", status="idle", cwd="C:/some/proj", mode="bypass",
                                   model="opus", log_result=True)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert uuid.UUID(rec["session_id"])
        assert rec["session_id"] != old_sid
        assert rec["cwd"] == "C:/some/proj"
        assert rec["mode"] == "bypass"
        assert rec["model"] == "opus"

    def test_turns_reset_then_one_after_launch(self, isolated_home):
        _seed_worker("probe-1", status="idle", log_result=True)
        proc = FakeProc(pid=7)
        args = fleet.build_parser().parse_args(["respawn", "probe-1"])
        fleet.cmd_respawn(args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert fleet.load_registry()["workers"]["probe-1"]["turns"] == 1

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


# ---------------------------------------------------------------------------
# fleet kill
# ---------------------------------------------------------------------------

class TestCmdKill:
    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["kill", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_kill(args, get_process_info=_dead_info)

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
        rc = fleet.cmd_kill(args, get_process_info=_dead_info, kill_process_tree=kill_process_tree)

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
        rc = fleet.cmd_clean(args, get_process_info=_dead_info)

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
        fleet.cmd_clean(args, get_process_info=_dead_info)

        assert not claimed.exists()

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
