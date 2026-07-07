"""Unit tests for Task 4: send / interrupt / attach / release + the
platform-adapter boundary (SPEC §5 steering/hybrid rows, §9, §14).

Same discipline as test_core.py / test_cli.py: no real claude process, no
real taskkill/PowerShell/wt is ever invoked -- every test injects a fake
popen / get_process_info / which / kill_process_tree. Every test
monkeypatches fleet.FLEET_HOME to a pytest tmp_path.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
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
        # F-DOA: if set, write() raises this instead of appending bytes.
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
        # F-DOA: poll_returns defaults to None (process never exits --
        # matches a normal healthy launch); the writer-thread + bounded-
        # window launcher polls this the same way cmd_spawn does.
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
                  cwd="C:/proj", mode="dontask", model=None, sid=None, log_result=False):
    """Save a single worker registry record with logs_dir()/<name>.jsonl
    optionally ending with a result event (so recompute_status resolves to
    idle rather than dead when the pid is not alive)."""
    sid = sid or str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, cwd, "some task", mode, model=model)
    if status is not None:
        rec["status"] = status
    rec["turn_pid"] = turn_pid
    rec["turn_pid_ctime"] = turn_pid_ctime
    fleet.save_registry({"workers": {name: rec}})
    if log_result:
        log = fleet.logs_dir() / f"{name}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done","total_cost_usd":0.1}\n', encoding="utf-8")
    return sid, rec


# ---------------------------------------------------------------------------
# append_mailbox
# ---------------------------------------------------------------------------

class TestAppendMailbox:
    def test_creates_mailbox_file(self, isolated_home):
        fleet.append_mailbox("sid-1", "hello")
        content = (fleet.mailbox_dir() / "sid-1.md").read_text(encoding="utf-8")
        assert "hello" in content

    def test_accumulates_multiple_sends(self, isolated_home):
        fleet.append_mailbox("sid-1", "first")
        fleet.append_mailbox("sid-1", "second")
        content = (fleet.mailbox_dir() / "sid-1.md").read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content
        assert content.index("first") < content.index("second")


# ---------------------------------------------------------------------------
# fleet send -- state machine
# ---------------------------------------------------------------------------

class TestCmdSend:
    def test_working_appends_to_mailbox_and_does_not_launch(self, isolated_home):
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def popen(*a, **kw):
            raise AssertionError("must not launch a turn while one is already working")

        args = fleet.build_parser().parse_args(["send", "probe-1", "check the logs"])
        rc = fleet.cmd_send(args, popen=popen, get_process_info=_alive_info, which=lambda n: "claude.cmd")

        assert rc == 0
        mailbox = fleet.mailbox_dir() / f"{sid}.md"
        assert mailbox.exists()
        assert "check the logs" in mailbox.read_text(encoding="utf-8")
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "working"

    def test_idle_launches_resume_turn_with_drained_and_appended_prompt(self, isolated_home):
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        # dead pid -> combined with the trailing result line -> recomputes to idle.
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("earlier queued instruction", encoding="utf-8")

        proc = FakeProc(pid=222)
        args = fleet.build_parser().parse_args(["send", "probe-1", "the new message"])
        rc = fleet.cmd_send(
            args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd",
        )

        assert rc == 0
        prompt = proc.stdin.written.decode("utf-8")
        assert "earlier queued instruction" in prompt
        assert "the new message" in prompt
        assert prompt.index("earlier queued instruction") < prompt.index("the new message")
        # mailbox claimed+finalized, not left dangling
        assert not (mbox / f"{sid}.md").exists()
        assert list(mbox.glob("*.claimed.*")) == []

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] == 222
        assert rec["turns"] == 1

    def test_idle_resume_uses_first_false(self, isolated_home):
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        calls = []
        proc = FakeProc(pid=222)
        args = fleet.build_parser().parse_args(["send", "probe-1", "go"])
        fleet.cmd_send(
            args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd",
        )
        argv = calls[0][1]
        assert "--resume" in argv
        assert sid in argv
        assert "--session-id" not in argv

    def test_attached_appends_to_mailbox_and_warns(self, isolated_home, capsys):
        sid, _ = _seed_worker("probe-1", status="attached")

        def popen(*a, **kw):
            raise AssertionError("must not launch a turn while attached")

        args = fleet.build_parser().parse_args(["send", "probe-1", "please look at X"])
        rc = fleet.cmd_send(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        assert rc == 0
        mailbox = fleet.mailbox_dir() / f"{sid}.md"
        assert "please look at X" in mailbox.read_text(encoding="utf-8")
        out = capsys.readouterr().out
        assert "attach" in out.lower()
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "attached"

    def test_dead_raises_clear_error(self, isolated_home):
        _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=False)

        def popen(*a, **kw):
            raise AssertionError("must not launch a turn for a dead worker")

        args = fleet.build_parser().parse_args(["send", "probe-1", "hello?"])
        with pytest.raises(fleet.FleetCliError, match="respawn"):
            fleet.cmd_send(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["send", "nope", "hi"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_send(args, get_process_info=_dead_info)

    def test_reads_message_from_file(self, isolated_home, tmp_path):
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        msg_file = tmp_path / "msg.txt"
        msg_file.write_text("careful multi-line instruction", encoding="utf-8")
        args = fleet.build_parser().parse_args(["send", "probe-1", f"@{msg_file}"])
        fleet.cmd_send(args, get_process_info=_alive_info, which=lambda n: "claude.cmd")
        mailbox_text = (fleet.mailbox_dir() / f"{sid}.md").read_text(encoding="utf-8")
        assert "careful multi-line instruction" in mailbox_text

    def test_idle_resume_over_doa_proc_raises_and_restores_prior_mail(self, isolated_home):
        """F-DOA/F-BLOCK inheritance: `fleet send` on an idle worker launches
        a resume turn through the same launch_turn() as cmd_spawn -- a child
        that dies during init (BrokenPipeError + nonzero poll) must raise
        TurnLaunchError here too, and the finalize/restore keying (stays in
        the caller, keyed on return-vs-raise) must still hold: the prior
        queued mail is restored, not lost."""
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("earlier queued instruction", encoding="utf-8")

        stdin = FakeStdin(raise_on_write=BrokenPipeError())
        proc = FakeProc(pid=4321, stdin=stdin, poll_returns=1)
        args = fleet.build_parser().parse_args(["send", "probe-1", "the new message"])

        with pytest.raises(fleet.TurnLaunchError):
            fleet.cmd_send(
                args, popen=_fake_popen(proc), get_process_info=_dead_info, which=lambda n: "claude.cmd",
            )

        restored = (mbox / f"{sid}.md").read_text(encoding="utf-8")
        assert "earlier queued instruction" in restored
        assert list(mbox.glob("*.claimed.*")) == []
        # the worker record itself is untouched by a failed resume (send
        # does not create/roll back a registry record the way spawn does).
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["turn_pid"] == 111


# ---------------------------------------------------------------------------
# fleet interrupt -- ctime-verified kill via mocked adapter
# ---------------------------------------------------------------------------

class TestInterruptWorker:
    def test_kills_and_marks_idle_when_alive(self, isolated_home):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed_pids = []
        result = fleet._interrupt_worker(
            "probe-1", get_process_info=_alive_info, kill_process_tree=killed_pids.append,
        )
        assert result is True
        assert killed_pids == [111]
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"

    def test_noop_when_not_running(self, isolated_home):
        _seed_worker("probe-1", status="idle", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)

        def kill_process_tree(pid):
            raise AssertionError("must not kill anything when the turn is not alive")

        result = fleet._interrupt_worker(
            "probe-1", get_process_info=_dead_info, kill_process_tree=kill_process_tree,
        )
        assert result is False
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_unknown_worker_raises(self, isolated_home):
        with pytest.raises(fleet.FleetCliError):
            fleet._interrupt_worker("nope", get_process_info=_dead_info, kill_process_tree=lambda pid: None)


class TestCmdInterrupt:
    def test_prints_interrupted_when_killed(self, isolated_home, capsys):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        args = fleet.build_parser().parse_args(["interrupt", "probe-1"])
        rc = fleet.cmd_interrupt(args, get_process_info=_alive_info, kill_process_tree=lambda pid: None)
        assert rc == 0
        assert "interrupted" in capsys.readouterr().out

    def test_prints_friendly_noop_when_not_running(self, isolated_home, capsys):
        _seed_worker("probe-1", status="idle", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        args = fleet.build_parser().parse_args(["interrupt", "probe-1"])
        rc = fleet.cmd_interrupt(args, get_process_info=_dead_info)
        assert rc == 0
        assert "no turn running" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# fleet attach -- refusal, --force, wt vs powershell fallback, cwd
# ---------------------------------------------------------------------------

class TestCmdAttach:
    def test_refuses_while_working_without_force(self, isolated_home):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def popen(*a, **kw):
            raise AssertionError("must not launch a terminal while refusing")

        args = fleet.build_parser().parse_args(["attach", "probe-1"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_attach(args, popen=popen, get_process_info=_alive_info, which=lambda n: "wt.exe")

        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "working"

    def test_force_interrupts_then_attaches(self, isolated_home):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cwd="C:/proj")
        calls = []

        def kill_process_tree(pid):
            calls.append(("interrupt", pid))

        proc = FakeProc(pid=999)
        popen = _fake_popen(proc, calls)

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        rc = fleet.cmd_attach(
            args, popen=popen, get_process_info=_alive_info, which=lambda n: "wt.exe",
            kill_process_tree=kill_process_tree,
        )

        assert rc == 0
        assert calls[0][0] == "interrupt"
        assert calls[1][0] == "launch"
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "attached"
        assert rec["attached_since"] is not None

    def test_already_attached_warns_and_does_not_relaunch(self, isolated_home, capsys):
        _seed_worker("probe-1", status="attached")

        def popen(*a, **kw):
            raise AssertionError("must not relaunch a terminal that's already attached")

        args = fleet.build_parser().parse_args(["attach", "probe-1"])
        rc = fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe")
        assert rc == 0
        assert "already attached" in capsys.readouterr().out

    def test_uses_wt_when_present(self, isolated_home):
        sid, _ = _seed_worker("probe-1", status="idle", cwd="C:/proj", log_result=True)
        calls = []
        proc = FakeProc(pid=1)
        popen = _fake_popen(proc, calls)
        args = fleet.build_parser().parse_args(["attach", "probe-1"])

        fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "C:/wt.exe")

        argv = calls[0][1]
        assert argv[0] == "wt"
        assert "-d" in argv
        assert argv[argv.index("-d") + 1] == "C:/proj"
        assert argv[-3:] == ["claude", "--resume", sid]

    def test_falls_back_to_powershell_when_wt_absent(self, isolated_home):
        sid, _ = _seed_worker("probe-1", status="idle", cwd="C:/proj", log_result=True)
        calls = []
        proc = FakeProc(pid=1)
        popen = _fake_popen(proc, calls)
        args = fleet.build_parser().parse_args(["attach", "probe-1"])

        fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: None)

        argv = calls[0][1]
        assert argv[0] == "powershell"
        assert "-Command" in argv
        ps_command = argv[argv.index("-Command") + 1]
        assert "Start-Process" in ps_command
        assert "C:/proj" in ps_command
        assert sid in ps_command

    def test_cwd_is_worker_cwd(self, isolated_home):
        _seed_worker("probe-1", status="idle", cwd="C:/some/worker/dir", log_result=True)
        calls = []
        proc = FakeProc(pid=1)
        popen = _fake_popen(proc, calls)
        args = fleet.build_parser().parse_args(["attach", "probe-1"])

        fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe")

        assert calls[0][2]["cwd"] == "C:/some/worker/dir"
        assert "creationflags" in calls[0][2]

    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["attach", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_attach(args, get_process_info=_dead_info)


# ---------------------------------------------------------------------------
# fleet release
# ---------------------------------------------------------------------------

class TestCmdRelease:
    def test_attached_to_idle_clears_attached_since(self, isolated_home):
        _seed_worker("probe-1", status="attached")
        data = fleet.load_registry()
        data["workers"]["probe-1"]["attached_since"] = fleet.now_iso()
        fleet.save_registry(data)

        args = fleet.build_parser().parse_args(["release", "probe-1"])
        rc = fleet.cmd_release(args)

        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"
        assert rec["attached_since"] is None

    def test_not_attached_warns_noop(self, isolated_home, capsys):
        _seed_worker("probe-1", status="idle")
        args = fleet.build_parser().parse_args(["release", "probe-1"])
        rc = fleet.cmd_release(args)
        assert rc == 0
        assert "not attached" in capsys.readouterr().out
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["release", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_release(args)


# ---------------------------------------------------------------------------
# Platform adapter boundary (SPEC §14)
# ---------------------------------------------------------------------------

class TestPlatformAdapterBoundary:
    def test_no_os_branches_outside_adapter_block(self):
        source = Path(fleet.__file__).read_text(encoding="utf-8")
        start = source.index("# === PLATFORM ADAPTER START")
        end = source.index("# === PLATFORM ADAPTER END") + len("# === PLATFORM ADAPTER END ===")
        assert start != -1 and end != -1
        outside = source[:start] + source[end:]
        for needle in ("os.name", "sys.platform"):
            assert needle not in outside, f"found {needle!r} outside the platform adapter block"

    def test_windows_adapter_selected_on_this_machine(self):
        assert isinstance(fleet.PLATFORM, fleet._WindowsPlatform)

    def test_detached_popen_kwargs_has_creationflags(self):
        kwargs = fleet.PLATFORM.detached_popen_kwargs()
        assert kwargs["creationflags"] == (
            fleet.subprocess.DETACHED_PROCESS | fleet.subprocess.CREATE_NEW_PROCESS_GROUP
        )

    def test_build_attach_argv_prefers_wt(self):
        argv = fleet.PLATFORM.build_attach_argv("C:/proj", "sid-1", which=lambda n: "C:/wt.exe")
        assert argv == ["wt", "-d", "C:/proj", "--", "claude", "--resume", "sid-1"]

    def test_build_attach_argv_falls_back_to_powershell(self):
        argv = fleet.PLATFORM.build_attach_argv("C:/proj", "sid-1", which=lambda n: None)
        assert argv[0] == "powershell"
        assert "-Command" in argv
        assert "sid-1" in argv[-1]
        assert "C:/proj" in argv[-1]

    def test_kill_process_tree_invokes_taskkill(self):
        calls = {}

        def fake_run(argv, **kwargs):
            calls["argv"] = argv

            class R:
                returncode = 0
            return R()

        result = fleet.PLATFORM.kill_process_tree(4321, run=fake_run)
        assert result is True
        assert calls["argv"] == ["taskkill", "/PID", "4321", "/T", "/F"]

    def test_kill_process_tree_swallows_exceptions(self):
        def fake_run(argv, **kwargs):
            raise OSError("boom")

        assert fleet.PLATFORM.kill_process_tree(1, run=fake_run) is False

    def test_posix_platform_raises_unsupported(self):
        posix = fleet._PosixPlatform()
        with pytest.raises(fleet.UnsupportedPlatformError):
            posix.detached_popen_kwargs()
        with pytest.raises(fleet.UnsupportedPlatformError):
            posix.get_process_info(1)
        with pytest.raises(fleet.UnsupportedPlatformError):
            posix.kill_process_tree(1)
        with pytest.raises(fleet.UnsupportedPlatformError):
            posix.build_attach_argv("C:/x", "sid-1")

    def test_unsupported_platform_error_is_not_implemented_error(self):
        assert issubclass(fleet.UnsupportedPlatformError, NotImplementedError)
