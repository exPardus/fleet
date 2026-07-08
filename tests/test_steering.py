"""Unit tests for Task 4: send / interrupt / attach / release + the
platform-adapter boundary (SPEC §5 steering/hybrid rows, §9, §14).

Same discipline as test_core.py / test_cli.py: no real claude process, no
real taskkill/PowerShell/wt is ever invoked -- every test injects a fake
popen / get_process_info / which / kill_process_tree. Every test
monkeypatches fleet.FLEET_HOME to a pytest tmp_path.
"""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    # SPEC §14: cmd_send's idle-resume path now refuses to launch a turn
    # unless the worker-settings.json instance has been rendered (`fleet
    # init`). Pre-provision a stub instance here so existing send tests
    # don't need to know about that precondition; the dedicated
    # missing-instance test deletes this file first.
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
                  cwd=None, mode="dontask", model=None, sid=None, log_result=False):
    """Save a single worker registry record with logs_dir()/<name>.jsonl
    optionally ending with a result event (so recompute_status resolves to
    idle rather than dead when the pid is not alive).

    Kernel 4 cwd preflight: launch_turn refuses to launch/resume into a
    vanished cwd, so the default seeded cwd is a real directory (FLEET_HOME,
    created by isolated_home). Tests asserting on a specific cwd string still
    pass one explicitly (those paths do not reach an actual launch)."""
    if cwd is None:
        cwd = str(fleet.FLEET_HOME)
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
    def test_send_raises_clear_error_when_instance_settings_missing(self, isolated_home):
        """SPEC §14: cmd_send refuses up front when `fleet init` has never
        been run on this machine (mirrors cmd_spawn's precondition)."""
        fleet.instance_settings_path().unlink()  # the isolated_home fixture stubs one in
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def popen(*a, **kw):
            raise AssertionError("must not launch when the settings instance is missing")

        args = fleet.build_parser().parse_args(["send", "probe-1", "check the logs"])
        with pytest.raises(fleet.FleetCliError, match="fleet init"):
            fleet.cmd_send(args, popen=popen, get_process_info=_alive_info, which=lambda n: "claude.cmd")

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

    def test_idle_resume_repasses_persisted_budget_and_setting_sources(self, isolated_home):
        # F13 (item 7, M5): the RESUME launch (turn 2..N) must re-emit
        # --max-budget-usd/--setting-sources from the PERSISTED registry
        # record, not just turn 1 -- a missing re-pass is the exact bug this
        # closes (turns 2..N ran uncapped, foreign-hook remedy evaporated).
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        data = fleet.load_registry()
        data["workers"]["probe-1"]["max_budget_usd"] = 4.0
        data["workers"]["probe-1"]["setting_sources"] = "user,project"
        fleet.save_registry(data)

        calls = []
        proc = FakeProc(pid=222)
        args = fleet.build_parser().parse_args(["send", "probe-1", "go"])
        fleet.cmd_send(
            args, popen=_fake_popen(proc, calls), get_process_info=_dead_info, which=lambda n: "claude.cmd",
        )
        argv = calls[0][1]
        assert "--resume" in argv
        assert argv[argv.index("--max-budget-usd") + 1] == "4.0"
        assert argv[argv.index("--setting-sources") + 1] == "user,project"

    def test_idle_resume_refuses_and_flags_when_cumulative_over_budget(self, isolated_home):
        # F13 cumulative check: before a RESUME turn, compare registry
        # cost_usd against max_budget_usd; if already exceeded, REFUSE the
        # launch (clear error) and FLAG it in status. The CLI --max-budget-usd
        # is per-turn; this is the worker-lifetime enforcement (SPEC §11).
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        # cost_usd is recomputed from the log each call, so encode the
        # over-cap lifetime spend in a trailing result event (also lands the
        # dead-pid worker on "idle" for the resume path).
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done","total_cost_usd":2.5}\n', encoding="utf-8")
        data = fleet.load_registry()
        data["workers"]["probe-1"]["max_budget_usd"] = 1.0
        fleet.save_registry(data)

        def popen(*a, **kw):
            raise AssertionError("must not launch a resume turn once over the cumulative cap")

        args = fleet.build_parser().parse_args(["send", "probe-1", "keep going"])
        with pytest.raises(fleet.FleetCliError, match="budget"):
            fleet.cmd_send(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "over_budget"

    def test_over_budget_status_is_sticky_across_recompute(self, isolated_home):
        # The over_budget flag must survive a later status recompute (like
        # attached/dead), else the flag silently reverts to idle.
        sid, _ = _seed_worker("probe-1", status="over_budget", log_result=True)
        rec = fleet.load_registry()["workers"]["probe-1"]
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=_dead_info)
        assert updated["status"] == "over_budget"

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
        queued mail is restored, not lost.

        Fix wave 1 (F1+F6): the idle path now pre-claims
        status="working"/turn_pid=None atomically before launching (F1); on
        a failed launch, only the status is conditionally rolled back to
        "idle" -- turn_pid is intentionally left at the pre-claim's None
        rather than restored to the prior (already-dead) pid, per the
        verdict's rollback contract ("send: status=='working' with
        turn_pid is None -> set status='idle'"). F6 also requires the NEW
        message (not just the prior mail) to survive the failed launch."""
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
        assert "the new message" in restored  # F6: the new message is not lost either
        assert list(mbox.glob("*.claimed.*")) == []
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"  # F1: conditional rollback of the pre-claim
        assert rec["turn_pid"] is None  # F1: rollback reverts status only, not turn_pid

    def test_idle_resume_rolls_back_on_keyboard_interrupt(self, isolated_home):
        """Task-4-verdict re-review Fix 2: the idle-resume rollback must
        catch BaseException, not just Exception -- a Ctrl-C landing during
        launch_turn must still restore the drained mailbox claim (so the
        new message is not lost) and revert the pre-claim to idle, not pin
        a permanently-guarded ghost claim (recompute_status's launch-in-
        flight guard never demotes "working"+turn_pid is None on its own)."""
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True, exist_ok=True)
        (mbox / f"{sid}.md").write_text("earlier queued instruction", encoding="utf-8")

        def popen(*a, **kw):
            raise KeyboardInterrupt()

        args = fleet.build_parser().parse_args(["send", "probe-1", "the new message"])
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_send(
                args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd",
            )

        restored = (mbox / f"{sid}.md").read_text(encoding="utf-8")
        assert "earlier queued instruction" in restored
        assert "the new message" in restored
        assert list(mbox.glob("*.claimed.*")) == []
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"
        assert rec["turn_pid"] is None

    def test_idle_send_preclaims_working_before_launch(self, isolated_home):
        """F1 required test (a): the decide-and-claim must be atomic under
        one lock -- by the time launch_turn (and, transitively, popen) is
        reached, a fresh registry read must already observe
        status=="working"/turn_pid is None (the pre-claim), never the
        pre-decision "idle"."""
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)

        def popen(argv, **kwargs):
            rec = fleet.load_registry()["workers"]["probe-1"]
            assert rec["status"] == "working"
            assert rec["turn_pid"] is None
            return FakeProc(pid=555)

        args = fleet.build_parser().parse_args(["send", "probe-1", "go"])
        rc = fleet.cmd_send(args, popen=popen, get_process_info=_dead_info, which=lambda n: "claude.cmd")
        assert rc == 0

    def test_commit_lock_exhaustion_does_not_abandon_the_launched_turn(
        self, isolated_home, monkeypatch, capsys,
    ):
        """Post-testing wave, item 1b (stress-report Finding 1, CRITICAL --
        "Same defect shape elsewhere": cmd_send's idle-resume path ends
        with an unwrapped `with fleet_lock(): ... rec["turn_pid"] = ...`
        commit, identical in shape to cmd_spawn's. If every retry of that
        commit lock times out, cmd_send must not raise (a real turn is
        already running) -- it must report success loudly-with-a-warning,
        same contract as cmd_spawn's own exhaustion path."""
        sid, _ = _seed_worker("probe-1", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        proc = FakeProc(pid=42)

        real_fleet_lock = fleet.fleet_lock
        calls = {"n": 0}

        @contextmanager
        def flaky(timeout=fleet.LOCK_TIMEOUT_SECONDS):
            calls["n"] += 1
            if calls["n"] == 1:
                # cmd_send's own pre-claim lock -- must succeed.
                with real_fleet_lock(timeout=timeout):
                    yield
            else:
                # Every post-launch commit attempt fails.
                raise fleet.FleetLockTimeout("simulated")

        monkeypatch.setattr(fleet, "fleet_lock", flaky)

        args = fleet.build_parser().parse_args(["send", "probe-1", "go"])
        rc = fleet.cmd_send(
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


# ---------------------------------------------------------------------------
# fleet interrupt -- ctime-verified kill via mocked adapter
# ---------------------------------------------------------------------------

class TestInterruptWorker:
    def test_kills_and_marks_idle_when_alive(self, isolated_home):
        """F3: get_process_info must go dead once kill_process_tree actually
        runs, so the post-kill re-verification confirms "killed" -- a
        static "always alive" fake would (correctly, per F3) report
        kill_failed instead."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed_pids = []
        killed = {"done": False}

        def kill_process_tree(pid):
            killed_pids.append(pid)
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        result = fleet._interrupt_worker(
            "probe-1", get_process_info=get_process_info, kill_process_tree=kill_process_tree,
        )
        assert result == "killed"
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
        assert result == "not_running"
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_unknown_worker_raises(self, isolated_home):
        with pytest.raises(fleet.FleetCliError):
            fleet._interrupt_worker("nope", get_process_info=_dead_info, kill_process_tree=lambda pid: None)

    def test_kill_failed_when_still_alive_after_kill_does_not_mark_idle(self, isolated_home):
        """F3: a kill attempt whose post-kill re-verification still sees the
        pid alive must be reported as "kill_failed" and must NOT mark the
        worker idle -- the pre-fix defect was discarding kill_process_tree's
        (and reality's) outcome and always claiming success."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed_pids = []
        result = fleet._interrupt_worker(
            "probe-1", get_process_info=_alive_info, kill_process_tree=killed_pids.append,
        )
        assert result == "kill_failed"
        assert killed_pids == [111]  # a kill was attempted
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"  # never marked idle while possibly still alive

    def test_probe_and_kill_run_outside_the_lock(self, isolated_home):
        """F4: pid_alive/kill_process_tree must not run while fleet_lock is
        held -- otherwise every concurrent `fleet` command would fail with
        FleetLockTimeout for the ~15s worst case (5s Get-Process + 10s
        taskkill) this fix exists to prevent. Assert a second fleet_lock()
        acquisition succeeds *during* the kill call."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)

        def kill_process_tree(pid):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout -- the outer lock is released

        result = fleet._interrupt_worker(
            "probe-1", get_process_info=_alive_info, kill_process_tree=kill_process_tree,
        )
        assert result == "kill_failed"  # _alive_info never reports it dead in this test


class TestCmdInterrupt:
    def test_prints_interrupted_when_killed(self, isolated_home, capsys):
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        killed = {"done": False}

        def kill_process_tree(pid):
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        args = fleet.build_parser().parse_args(["interrupt", "probe-1"])
        rc = fleet.cmd_interrupt(args, get_process_info=get_process_info, kill_process_tree=kill_process_tree)
        assert rc == 0
        assert "interrupted" in capsys.readouterr().out

    def test_prints_friendly_noop_when_not_running(self, isolated_home, capsys):
        _seed_worker("probe-1", status="idle", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, log_result=True)
        args = fleet.build_parser().parse_args(["interrupt", "probe-1"])
        rc = fleet.cmd_interrupt(args, get_process_info=_dead_info)
        assert rc == 0
        assert "no turn running" in capsys.readouterr().out

    def test_prints_loud_warning_and_nonzero_when_kill_failed(self, isolated_home, capsys):
        """F3: cmd_interrupt must not lie with "interrupted"/idle when the
        post-kill re-verification still sees the pid alive."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME)
        args = fleet.build_parser().parse_args(["interrupt", "probe-1"])
        rc = fleet.cmd_interrupt(args, get_process_info=_alive_info, kill_process_tree=lambda pid: None)
        assert rc != 0
        combined = "".join(capsys.readouterr())
        assert "probe-1" in combined
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"


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
        """F3: _interrupt_worker now re-verifies liveness after the kill, so
        get_process_info must go dead once the kill actually happens (a
        static "always alive" fake would make the re-verification report
        kill_failed and abort the attach)."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cwd="C:/proj")
        calls = []
        killed = {"done": False}

        def kill_process_tree(pid):
            calls.append(("interrupt", pid))
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        proc = FakeProc(pid=999)
        popen = _fake_popen(proc, calls)

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        rc = fleet.cmd_attach(
            args, popen=popen, get_process_info=get_process_info, which=lambda n: "wt.exe",
            kill_process_tree=kill_process_tree,
        )

        assert rc == 0
        assert calls[0][0] == "interrupt"
        assert calls[1][0] == "launch"
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "attached"
        assert rec["attached_since"] is not None

    def test_force_raises_when_kill_verification_fails(self, isolated_home):
        """F3 required test: if _interrupt_worker cannot verify the kill
        (the pid still reports alive afterward), --force must abort loudly
        -- no popen, no attached claim, status left as-is."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cwd="C:/proj")

        def popen(*a, **kw):
            raise AssertionError("must not launch a terminal when --force kill verification fails")

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_attach(
                args, popen=popen, get_process_info=_alive_info, which=lambda n: "wt.exe",
                kill_process_tree=lambda pid: None,
            )

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"

    def test_force_refuses_during_launch_in_flight_claim(self, isolated_home):
        """Task-4-verdict re-review Fix 1: during a turn-starter's pre-claim
        window (status=="working", turn_pid is None -- lasting the whole
        launch_turn duration, per recompute_status's launch-in-flight
        guard), --force must refuse loudly instead of proceeding. Before
        the fix: _interrupt_worker would snapshot pid=None, pid_alive(None)
        is False, return "not_running", and cmd_attach treated that as
        clear-to-proceed -- popen-ing a second live claude while the
        concurrent starter brings its own claude up."""
        _seed_worker("probe-1", status="working", turn_pid=None, cwd="C:/proj")

        def popen(*a, **kw):
            raise AssertionError("must not launch a terminal during a launch-in-flight claim")

        def kill_process_tree(pid):
            raise AssertionError("must not attempt a kill when there is no real pid yet")

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_attach(
                args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe",
                kill_process_tree=kill_process_tree,
            )

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None

    def test_force_still_proceeds_on_real_dead_pid_working_record(self, isolated_home):
        """Regression guard for Fix 1: the new turn_pid-is-None refusal must
        be scoped tightly to the launch-in-flight window -- a "working"
        record with a real (already-dead) turn_pid must still proceed
        through the normal --force interrupt-then-attach path (this is
        exactly test_force_interrupts_then_attaches's scenario, re-asserted
        here to pin that Fix 1 didn't broaden the refusal)."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cwd="C:/proj")
        calls = []
        killed = {"done": False}

        def kill_process_tree(pid):
            calls.append(("interrupt", pid))
            killed["done"] = True

        def get_process_info(pid):
            return None if killed["done"] else _alive_info(pid)

        proc = FakeProc(pid=999)
        popen = _fake_popen(proc, calls)

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        rc = fleet.cmd_attach(
            args, popen=popen, get_process_info=get_process_info, which=lambda n: "wt.exe",
            kill_process_tree=kill_process_tree,
        )

        assert rc == 0
        assert calls[0][0] == "interrupt"
        assert calls[1][0] == "launch"
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "attached"

    def test_force_refuses_when_reclaimed_between_interrupt_and_relock(self, isolated_home, monkeypatch):
        """F1 (final-review.md): _interrupt_worker's "killed" branch commits
        idle and releases ITS OWN lock before cmd_attach re-locks to claim
        "attached" -- in real production that gap is wide enough (Get-
        Process/taskkill take hundreds of ms) for a concurrent `fleet send`
        to observe idle and pre-claim status="working"/turn_pid=None for a
        brand-new launch first. Simulate the race by having the (faked)
        interrupt path leave that concurrent pre-claim in the registry
        instead of idle before reporting "killed" back to cmd_attach: the
        re-lock must refuse loudly instead of stamping "attached" over it
        (which would leave two live claudes on one session)."""
        _seed_worker("probe-1", status="working", turn_pid=111, turn_pid_ctime=ALIVE_CTIME, cwd="C:/proj")

        def fake_interrupt_worker(name, get_process_info=None, kill_process_tree=None):
            data = fleet.load_registry()
            rec = data["workers"][name]
            rec["status"] = "working"
            rec["turn_pid"] = None  # the concurrent send's own launch-in-flight claim
            fleet.save_registry(data)
            return "killed"

        monkeypatch.setattr(fleet, "_interrupt_worker", fake_interrupt_worker)

        def popen(*a, **kw):
            raise AssertionError("must not launch a terminal over a concurrently reclaimed worker")

        args = fleet.build_parser().parse_args(["attach", "probe-1", "--force"])
        with pytest.raises(fleet.FleetCliError, match="claimed concurrently"):
            fleet.cmd_attach(args, popen=popen, get_process_info=_alive_info, which=lambda n: "wt.exe")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None

    def test_attach_claims_attached_before_popen_called(self, isolated_home):
        """F1 required test (d): the "attached" claim must be committed
        under the decision lock BEFORE popen launches the terminal."""
        _seed_worker("probe-1", status="idle", cwd="C:/proj", log_result=True)

        def popen(argv, **kwargs):
            rec = fleet.load_registry()["workers"]["probe-1"]
            assert rec["status"] == "attached"
            assert rec["attached_since"] is not None
            return FakeProc(pid=1)

        args = fleet.build_parser().parse_args(["attach", "probe-1"])
        rc = fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe")
        assert rc == 0

    def test_attach_rolls_back_on_popen_failure(self, isolated_home):
        """F1 required test (e): if the (detached) terminal fails to even
        launch, the pre-committed "attached" claim must be rolled back to
        idle -- conditionally, only because the record is still exactly in
        the state this call wrote."""
        _seed_worker("probe-1", status="idle", cwd="C:/proj", log_result=True)

        def popen(*a, **kw):
            raise OSError("boom")

        args = fleet.build_parser().parse_args(["attach", "probe-1"])
        with pytest.raises(OSError):
            fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"
        assert rec["attached_since"] is None

    def test_attach_rolls_back_on_keyboard_interrupt_during_popen(self, isolated_home):
        """Task-4-verdict re-review Fix 2: the popen rollback must catch
        BaseException, not just Exception -- a Ctrl-C landing exactly
        during the (detached) terminal launch must still revert the
        pre-committed "attached" claim to idle, not pin it forever."""
        _seed_worker("probe-1", status="idle", cwd="C:/proj", log_result=True)

        def popen(*a, **kw):
            raise KeyboardInterrupt()

        args = fleet.build_parser().parse_args(["attach", "probe-1"])
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_attach(args, popen=popen, get_process_info=_dead_info, which=lambda n: "wt.exe")

        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"
        assert rec["attached_since"] is None

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
        # F7: broadened beyond os.name/sys.platform to also reject every
        # other OS-branching surface an adapter method could smuggle in.
        for needle in (
            "os.name", "sys.platform", "platform.system",
            "sys.getwindowsversion", "os.uname", "os.sep",
        ):
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

    def test_build_attach_argv_powershell_handles_space_in_cwd(self):
        """F2 (Minor 3): a space in cwd is fine inside the PS single-quoted
        literal -- must not be mangled or split."""
        cwd = r"C:\some dir\proj"
        argv = fleet.PLATFORM.build_attach_argv(cwd, "sid-1", which=lambda n: None)
        ps_command = argv[argv.index("-Command") + 1]
        assert f"'{cwd}'" in ps_command

    def test_build_attach_argv_powershell_escapes_single_quote_in_cwd(self):
        """F2: an unescaped `'` in cwd would terminate the PS single-quoted
        string literal early (ParserError) while `fleet attach` still
        reports success. The doubled `''` form must appear literally."""
        cwd = r"C:\Users\O'Brien\proj"
        argv = fleet.PLATFORM.build_attach_argv(cwd, "sid-1", which=lambda n: None)
        ps_command = argv[argv.index("-Command") + 1]
        assert "O''Brien" in ps_command
        assert "O'Brien" not in ps_command  # the raw, unescaped form must not survive

    def test_build_attach_argv_wt_keeps_quote_and_space_cwd_as_one_element(self):
        """F2: the `wt` branch is unaffected -- list2cmdline double-quotes
        each argv element, so a `'` or a space in cwd stays a literal part
        of one intact list element, not something requiring escaping here."""
        for cwd in (r"C:\some dir\proj", r"C:\Users\O'Brien\proj"):
            argv = fleet.PLATFORM.build_attach_argv(cwd, "sid-1", which=lambda n: "C:/wt.exe")
            assert argv[argv.index("-d") + 1] == cwd

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
