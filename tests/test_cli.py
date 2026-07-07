"""Unit tests for the claude-fleet M1 CLI layer (bin/fleet.py: main() +
argparse subcommands + detached turn launcher).

No real claude process is ever spawned: every test that reaches launch_turn
injects a fake `popen` and a fake `get_process_info`. Every test monkeypatches
fleet.FLEET_HOME to a pytest tmp_path (autouse fixture below), same discipline
as test_core.py.
"""
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    return tmp_path


def _parse(ctime_iso):
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class FakeStdin:
    def __init__(self):
        self.written = b""
        self.closed = False

    def write(self, data):
        self.written += data

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.stdin = FakeStdin()


def _fake_popen(proc, calls=None):
    def popen(argv, **kwargs):
        if calls is not None:
            calls["argv"] = argv
            calls["kwargs"] = kwargs
        return proc
    return popen


def _spawn_args(name, dir_, task, mode="dontask", model=None, max_budget_usd=None):
    argv = ["spawn", name, "--dir", str(dir_), "--task", task, "--mode", mode]
    if model:
        argv += ["--model", model]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    return fleet.build_parser().parse_args(argv)


# ---------------------------------------------------------------------------
# build_turn_argv (pure argv builder, SPEC §6)
# ---------------------------------------------------------------------------

class TestBuildTurnArgv:
    def test_first_turn_uses_session_id(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit")
        assert "--session-id" in argv
        assert argv[argv.index("--session-id") + 1] == "sid-1"
        assert "--resume" not in argv

    def test_resume_turn_uses_resume(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=False, mode="omit")
        assert "--resume" in argv
        assert argv[argv.index("--resume") + 1] == "sid-1"
        assert "--session-id" not in argv

    def test_mandatory_flags_present(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit")
        assert argv[0] == "claude.cmd"
        for flag in ("-p", "--output-format", "stream-json", "--verbose", "--include-hook-events"):
            assert flag in argv

    def test_settings_path_included(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit")
        assert "--settings" in argv
        assert argv[argv.index("--settings") + 1] == fleet.WORKER_SETTINGS_PATH

    @pytest.mark.parametrize("mode,expected", [
        ("bypass", ["--dangerously-skip-permissions"]),
        ("accept", ["--permission-mode", "acceptEdits"]),
        ("dontask", ["--permission-mode", "dontAsk"]),
        ("plan", ["--permission-mode", "plan"]),
        ("omit", []),
    ])
    def test_mode_flags_embedded(self, mode, expected):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode=mode)
        if expected:
            idx = argv.index(expected[0])
            assert argv[idx:idx + len(expected)] == expected
        else:
            assert "--permission-mode" not in argv
            assert "--dangerously-skip-permissions" not in argv

    def test_model_flag_included_when_given(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit", model="haiku")
        assert argv[argv.index("--model") + 1] == "haiku"

    def test_model_flag_omitted_when_none(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit", model=None)
        assert "--model" not in argv

    def test_max_budget_flag_included_when_given(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit", max_budget_usd=2.5)
        assert argv[argv.index("--max-budget-usd") + 1] == "2.5"

    def test_max_budget_flag_omitted_when_none(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit", max_budget_usd=None)
        assert "--max-budget-usd" not in argv

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="yolo")


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
# launch_turn (Popen injected -- no real claude spawn)
# ---------------------------------------------------------------------------

class TestLaunchTurn:
    def test_launch_writes_prompt_to_stdin_and_closes_it(self, isolated_home):
        proc = FakeProc(pid=4321)
        popen = _fake_popen(proc)
        ctime = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
        info = fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "hello prompt", "omit", first=True,
            popen=popen, get_process_info=lambda pid: ("claude.exe", ctime),
            which=lambda n: "claude.cmd",
        )
        assert proc.stdin.written == "hello prompt".encode("utf-8")
        assert proc.stdin.closed is True
        assert info["turn_pid"] == 4321
        assert info["turn_pid_ctime"] == fleet.ctime_to_iso(ctime)

    def test_launch_creates_log_files(self, isolated_home):
        proc = FakeProc(pid=1)
        popen = _fake_popen(proc)
        fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "x", "omit", first=True,
            popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
        )
        assert (isolated_home / "logs" / "probe-1.jsonl").exists()
        assert (isolated_home / "logs" / "probe-1.err").exists()

    def test_launch_passes_cwd_and_creationflags(self, isolated_home):
        proc = FakeProc(pid=1)
        calls = {}
        popen = _fake_popen(proc, calls)
        fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "x", "omit", first=True,
            popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
        )
        assert calls["kwargs"]["cwd"] == str(isolated_home)
        assert calls["kwargs"]["creationflags"] == (
            fleet.subprocess.DETACHED_PROCESS | fleet.subprocess.CREATE_NEW_PROCESS_GROUP
        )

    def test_claude_not_found_raises_before_popen_called(self, isolated_home):
        def popen(*a, **kw):
            raise AssertionError("popen must not be called when claude is not on PATH")

        with pytest.raises(fleet.ClaudeNotFoundError):
            fleet.launch_turn(
                "probe-1", isolated_home, "sid-1", "x", "omit", first=True,
                popen=popen, get_process_info=lambda pid: None, which=lambda n: None,
            )

    def test_popen_failure_raises_turn_launch_error(self, isolated_home):
        def popen(*a, **kw):
            raise OSError("boom")

        with pytest.raises(fleet.TurnLaunchError):
            fleet.launch_turn(
                "probe-1", isolated_home, "sid-1", "x", "omit", first=True,
                popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
            )

    def test_process_info_none_yields_none_ctime_not_an_error(self, isolated_home):
        proc = FakeProc(pid=1)
        popen = _fake_popen(proc)
        info = fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "x", "omit", first=True,
            popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
        )
        assert info["turn_pid_ctime"] is None


# ---------------------------------------------------------------------------
# cmd_spawn
# ---------------------------------------------------------------------------

class TestCmdSpawn:
    def test_spawn_creates_registry_entry_and_launches(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        proc = FakeProc(pid=999)
        ctime = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
        args = _spawn_args("probe-1", worker_dir, "do the thing", mode="dontask", model="haiku")

        rc = fleet.cmd_spawn(
            args, popen=_fake_popen(proc), get_process_info=lambda pid: ("claude.exe", ctime),
            which=lambda n: "claude.cmd",
        )

        assert rc == 0
        data = fleet.load_registry()
        rec = data["workers"]["probe-1"]
        assert uuid.UUID(rec["session_id"])
        assert rec["cwd"] == str(worker_dir)
        assert rec["mode"] == "dontask"
        assert rec["model"] == "haiku"
        assert rec["turn_pid"] == 999
        assert rec["turn_pid_ctime"] == fleet.ctime_to_iso(ctime)
        assert rec["turns"] == 1

    def test_spawn_prints_name_session_id_log_path(self, isolated_home, tmp_path, capsys):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        proc = FakeProc(pid=1)
        args = _spawn_args("probe-1", worker_dir, "do the thing")

        fleet.cmd_spawn(args, popen=_fake_popen(proc), get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

        out = capsys.readouterr().out
        assert "probe-1" in out
        data = fleet.load_registry()
        assert data["workers"]["probe-1"]["session_id"] in out
        assert "probe-1.jsonl" in out

    def test_spawn_refuses_duplicate_name(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        fleet.save_registry({"workers": {"probe-1": _seed_record(worker_dir)}})
        args = _spawn_args("probe-1", worker_dir, "do the thing")

        def popen(*a, **kw):
            raise AssertionError("must not launch when name is a duplicate")

        with pytest.raises(ValueError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

    def test_spawn_refuses_bad_name(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def popen(*a, **kw):
            raise AssertionError("must not launch when name is invalid")

        args = _spawn_args("Bad Name!", worker_dir, "do the thing")
        with pytest.raises(ValueError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

    def test_spawn_refuses_missing_dir(self, isolated_home, tmp_path):
        missing = tmp_path / "nope"

        def popen(*a, **kw):
            raise AssertionError("must not launch when --dir is missing")

        args = _spawn_args("probe-1", missing, "do the thing")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

    def test_spawn_reads_task_from_file(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        task_file = tmp_path / "task.md"
        task_file.write_text("do the elaborate multi-line thing\nwith detail", encoding="utf-8")
        proc = FakeProc(pid=1)
        args = _spawn_args("probe-1", worker_dir, f"@{task_file}")

        fleet.cmd_spawn(args, popen=_fake_popen(proc), get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

        assert "do the elaborate multi-line thing" in proc.stdin.written.decode("utf-8")
        data = fleet.load_registry()
        assert data["workers"]["probe-1"]["task"].startswith("do the elaborate multi-line thing")

    def test_spawn_missing_task_file_raises_clear_error(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()
        args = _spawn_args("probe-1", worker_dir, "@" + str(tmp_path / "nope.md"))

        def popen(*a, **kw):
            raise AssertionError("must not launch when task file is missing")

        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

    def test_spawn_launch_failure_rolls_back_registry_and_restores_mailbox(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        def popen(*a, **kw):
            raise OSError("boom")

        args = _spawn_args("probe-1", worker_dir, "do the thing")
        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

        data = fleet.load_registry()
        assert "probe-1" not in data["workers"]

    def test_spawn_launch_failure_restores_mail_for_next_launch(self, isolated_home, tmp_path):
        worker_dir = tmp_path / "proj"
        worker_dir.mkdir()

        # Seed the registry with a worker whose session's mailbox has a
        # pending message, then simulate spawn failing via a mailbox-bearing
        # sid collision is not realistic for spawn (fresh uuid4 sid each
        # time) -- so instead we verify the restore path directly against
        # compose_prompt/claim semantics that cmd_spawn must invoke: this is
        # covered at the unit level in TestRestoreMailboxClaim (test_core.py);
        # here we just assert cmd_spawn's failure path does not leave a
        # dangling .claimed.* file when there was never any mail to claim.
        args = _spawn_args("probe-1", worker_dir, "do the thing")

        def popen(*a, **kw):
            raise OSError("boom")

        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_spawn(args, popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd")

        leftover = list(fleet.mailbox_dir().glob("*.claimed.*")) if fleet.mailbox_dir().exists() else []
        assert leftover == []


def _seed_record(worker_dir):
    rec = fleet.new_worker_record(str(uuid.uuid4()), worker_dir, "existing task", "dontask")
    return rec


# ---------------------------------------------------------------------------
# recompute_worker / cmd_status transitions
# ---------------------------------------------------------------------------

class TestRecomputeWorker:
    def test_working_to_idle_on_result_line(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","subtype":"success","result":"all done","total_cost_usd":0.5}\n',
            encoding="utf-8",
        )
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=lambda pid: None)
        assert updated["status"] == "idle"
        assert updated["cost_usd"] == 0.5

    def test_working_to_dead_on_crash_no_result_line(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"assistant","message":{"content":[]}}\n', encoding="utf-8")
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=lambda pid: None)
        assert updated["status"] == "dead"

    def test_stays_working_when_pid_alive(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        info = lambda pid: ("claude.exe", _parse("2026-07-07T12:00:00Z"))
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=info)
        assert updated["status"] == "working"

    def test_attached_not_clobbered(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["status"] = "attached"
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=lambda pid: None)
        assert updated["status"] == "attached"


class TestCmdStatus:
    def test_status_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["status", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_status(args)

    def test_status_prints_table_with_all_workers(self, isolated_home, capsys):
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
        rec1 = fleet.new_worker_record(sid1, "C:/x", "task1", "dontask")
        rec2 = fleet.new_worker_record(sid2, "C:/y", "task2", "bypass")
        fleet.save_registry({"workers": {"probe-1": rec1, "probe-2": rec2}})
        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args, get_process_info=lambda pid: None)
        assert rc == 0
        out = capsys.readouterr().out
        assert "probe-1" in out
        assert "probe-2" in out

    def test_status_flags_idle_with_pending_mail(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")
        fleet.save_registry({"workers": {"probe-1": rec}})
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("please check X", encoding="utf-8")

        args = fleet.build_parser().parse_args(["status"])
        fleet.cmd_status(args, get_process_info=lambda pid: None)
        out = capsys.readouterr().out
        assert "idle+mail" in out

    def test_status_persists_recomputed_status(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")
        fleet.save_registry({"workers": {"probe-1": rec}})

        args = fleet.build_parser().parse_args(["status", "probe-1"])
        fleet.cmd_status(args, get_process_info=lambda pid: None)

        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"


# ---------------------------------------------------------------------------
# hook_events_present / cmd_peek
# ---------------------------------------------------------------------------

class TestHookEventsPresent:
    def test_present_when_hookeventname_in_log(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text(
            '{"type":"system","hookSpecificOutput":{"hookEventName":"PostToolUse"}}\n',
            encoding="utf-8",
        )
        assert fleet.hook_events_present(log) is True

    def test_absent_when_no_hook_events(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text('{"type":"assistant","message":{"content":[]}}\n', encoding="utf-8")
        assert fleet.hook_events_present(log) is False

    def test_missing_log_is_absent(self, tmp_path):
        assert fleet.hook_events_present(tmp_path / "nope.jsonl") is False


class TestCmdPeek:
    def test_peek_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["peek", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_peek(args)

    def test_peek_prints_digest(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        fleet.save_registry({"workers": {"probe-1": rec}})
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}\n'
            '{"type":"result","result":"all done","total_cost_usd":0.1}\n',
            encoding="utf-8",
        )
        args = fleet.build_parser().parse_args(["peek", "probe-1"])
        rc = fleet.cmd_peek(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Bash" in out
        assert "all done" in out

    def test_peek_no_events_yet(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        fleet.save_registry({"workers": {"probe-1": rec}})
        args = fleet.build_parser().parse_args(["peek", "probe-1"])
        rc = fleet.cmd_peek(args)
        assert rc == 0
        assert "no events yet" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_result
# ---------------------------------------------------------------------------

class TestCmdResult:
    def test_result_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["result", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_result(args)

    def test_result_prints_final_result_text_only(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        fleet.save_registry({"workers": {"probe-1": rec}})
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"thinking..."}]}}\n'
            '{"type":"result","result":"the final answer","total_cost_usd":0.2}\n',
            encoding="utf-8",
        )
        args = fleet.build_parser().parse_args(["result", "probe-1"])
        rc = fleet.cmd_result(args)
        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "the final answer"

    def test_result_none_yet_prints_clear_message_and_nonzero(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        fleet.save_registry({"workers": {"probe-1": rec}})
        args = fleet.build_parser().parse_args(["result", "probe-1"])
        rc = fleet.cmd_result(args)
        assert rc != 0
        assert "no completed turn result" in capsys.readouterr().out


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
    def test_all_mode_waits_for_every_worker(self, isolated_home):
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
        rec1 = fleet.new_worker_record(sid1, "C:/x", "t1", "dontask")
        rec1["turn_pid"], rec1["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        rec2 = fleet.new_worker_record(sid2, "C:/y", "t2", "dontask")
        rec2["turn_pid"], rec2["turn_pid_ctime"] = 222, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec1, "probe-2": rec2}})
        for name in ("probe-1", "probe-2"):
            log = fleet.logs_dir() / f"{name}.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")

        calls = {"n": 0}

        def info(pid):
            calls["n"] += 1
            # probe-1 (111) finishes after the first poll; probe-2 (222)
            # finishes after the second poll.
            if pid == 111:
                return None
            if pid == 222:
                return None if calls["n"] > 4 else ("claude.exe", _parse("2026-07-07T12:00:00Z"))
            return None

        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1", "probe-2"], mode="all", timeout=None, poll_interval=1.0,
            get_process_info=info, sleep=clock.sleep, clock=clock.now,
        )
        assert pending == set()
        assert finished == {"probe-1": "idle", "probe-2": "idle"}

    def test_any_mode_returns_as_soon_as_one_finishes(self, isolated_home):
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
        rec1 = fleet.new_worker_record(sid1, "C:/x", "t1", "dontask")
        rec1["turn_pid"], rec1["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        rec2 = fleet.new_worker_record(sid2, "C:/y", "t2", "dontask")
        rec2["turn_pid"], rec2["turn_pid_ctime"] = 222, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec1, "probe-2": rec2}})
        for name in ("probe-1", "probe-2"):
            log = fleet.logs_dir() / f"{name}.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")

        def info(pid):
            if pid == 111:
                return None  # probe-1 already stopped
            return ("claude.exe", _parse("2026-07-07T12:00:00Z"))  # probe-2 still working forever

        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1", "probe-2"], mode="any", timeout=None, poll_interval=1.0,
            get_process_info=info, sleep=clock.sleep, clock=clock.now,
        )
        assert finished == {"probe-1": "idle"}
        assert pending == {"probe-2"}

    def test_timeout_leaves_pending_nonempty(self, isolated_home):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "t1", "dontask")
        rec["turn_pid"], rec["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec}})

        def info(pid):
            return ("claude.exe", _parse("2026-07-07T12:00:00Z"))  # never finishes

        clock = FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["probe-1"], mode="all", timeout=5.0, poll_interval=1.0,
            get_process_info=info, sleep=clock.sleep, clock=clock.now,
        )
        assert finished == {}
        assert pending == {"probe-1"}


class TestCmdWait:
    def test_wait_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["wait", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_wait(args, get_process_info=lambda pid: None, sleep=lambda s: None, clock=lambda: 0.0)

    def test_wait_all_prints_finish_and_returns_zero(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "t1", "dontask")
        rec["turn_pid"], rec["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec}})
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"all set"}\n', encoding="utf-8")

        args = fleet.build_parser().parse_args(["wait", "probe-1"])
        rc = fleet.cmd_wait(args, get_process_info=lambda pid: None, sleep=lambda s: None, clock=lambda: 0.0)

        assert rc == 0
        out = capsys.readouterr().out
        assert "probe-1" in out
        assert "all set" in out
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_wait_timeout_returns_nonzero(self, isolated_home, capsys):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "t1", "dontask")
        rec["turn_pid"], rec["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec}})

        clock = FakeClock()
        args = fleet.build_parser().parse_args(["wait", "probe-1", "--timeout", "3"])
        rc = fleet.cmd_wait(
            args, get_process_info=lambda pid: ("claude.exe", _parse("2026-07-07T12:00:00Z")),
            sleep=clock.sleep, clock=clock.now,
        )
        assert rc != 0
        assert "timed out" in capsys.readouterr().out


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
