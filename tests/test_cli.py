"""Unit tests for the claude-fleet M1 CLI layer (bin/fleet.py: main() +
argparse subcommands + detached turn launcher).

No real claude process is ever spawned: every test that reaches launch_turn
injects a fake `popen` and a fake `get_process_info`. Every test monkeypatches
fleet.FLEET_HOME to a pytest tmp_path (autouse fixture below), same discipline
as test_core.py.
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


class FakeStdin:
    def __init__(self, raise_on_write=None, block_event=None):
        self.written = b""
        self.closed = False
        # F-DOA: if set, write() raises this instead of appending bytes
        # (simulates the child's read end having closed -- BrokenPipeError).
        self._raise_on_write = raise_on_write
        # F-BLOCK: if set, write() blocks on this threading.Event before
        # doing anything else (simulates a slow/wedged reader).
        self._block_event = block_event

    def write(self, data):
        if self._block_event is not None:
            self._block_event.wait()
        if self._raise_on_write is not None:
            raise self._raise_on_write
        self.written += data

    def close(self):
        self.closed = True


class FakeProc:
    def __init__(self, pid, stdin=None, poll_returns=None):
        self.pid = pid
        self.stdin = stdin if stdin is not None else FakeStdin()
        # F-DOA/F-BLOCK: poll_returns is either None (process never exits --
        # the default, matching a normal healthy launch) or a fixed int
        # returncode that poll() reports from the very first call onward.
        self._poll_returns = poll_returns

    def poll(self):
        return self._poll_returns


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
        # SPEC §14: WORKER_SETTINGS_PATH (a fixed module constant) was
        # replaced by instance_settings_path(), resolved fresh per call so
        # it follows FLEET_HOME (env-var override / test sandboxes) like
        # every other path helper in this module.
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit")
        assert "--settings" in argv
        assert argv[argv.index("--settings") + 1] == str(fleet.instance_settings_path())

    def test_settings_path_explicit_override_wins(self):
        argv = fleet.build_turn_argv(
            "claude.cmd", "sid-1", first=True, mode="omit", settings_path="C:/custom/settings.json",
        )
        assert argv[argv.index("--settings") + 1] == "C:/custom/settings.json"

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

    def test_setting_sources_flag_included_when_given(self):
        argv = fleet.build_turn_argv(
            "claude.cmd", "sid-1", first=True, mode="omit", setting_sources="user,project")
        assert argv[argv.index("--setting-sources") + 1] == "user,project"

    def test_setting_sources_flag_omitted_when_none(self):
        argv = fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="omit", setting_sources=None)
        assert "--setting-sources" not in argv

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            fleet.build_turn_argv("claude.cmd", "sid-1", first=True, mode="yolo")


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

    def test_sum_result_tokens_sums_input_plus_output_across_results(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"assistant","message":{"usage":{"input_tokens":9999}}}\n'
            '{"type":"result","usage":{"input_tokens":100,"output_tokens":20}}\n'
            '{"type":"result","usage":{"input_tokens":30,"output_tokens":5}}\n',
            encoding="utf-8",
        )
        # only "result" events counted (assistant usage ignored): 100+20+30+5
        assert fleet._sum_result_tokens(log) == 155

    def test_sum_result_tokens_none_when_no_result(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"assistant","message":{"usage":{"input_tokens":10}}}\n', encoding="utf-8")
        assert fleet._sum_result_tokens(log) is None

    def test_sum_result_tokens_none_when_missing(self, isolated_home):
        assert fleet._sum_result_tokens(fleet.logs_dir() / "nope.jsonl") is None

    def test_sum_result_tokens_ignores_bogus_usage_values(self, isolated_home):
        log = fleet.logs_dir() / "probe-1.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            '{"type":"result","usage":{"input_tokens":true,"output_tokens":-5}}\n'
            '{"type":"result","usage":{"input_tokens":40,"output_tokens":2}}\n',
            encoding="utf-8",
        )
        assert fleet._sum_result_tokens(log) == 42


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

    # -----------------------------------------------------------------
    # F-DOA: a child that dies during init before consuming its prompt
    # must be reported as a launch failure, not a running turn.
    # -----------------------------------------------------------------

    def test_broken_pipe_write_with_nonzero_poll_raises_turn_launch_error(self, isolated_home):
        """The exact testDOA.py scenario: the child closed its read end
        before the prompt was consumed (BrokenPipeError) and poll() confirms
        it already exited nonzero -- this must raise, not report success."""
        stdin = FakeStdin(raise_on_write=BrokenPipeError())
        proc = FakeProc(pid=4321, stdin=stdin, poll_returns=1)
        popen = _fake_popen(proc)
        with pytest.raises(fleet.TurnLaunchError):
            fleet.launch_turn(
                "probe-1", isolated_home, "sid-1", "hello prompt", "omit", first=True,
                popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
            )

    def test_buffered_write_succeeds_but_nonzero_poll_raises(self, isolated_home):
        """Small-prompt case: the write is buffered and returns cleanly, but
        the child has already exited nonzero within the window -- BrokenPipe
        alone would miss this, so poll() must be checked too."""
        proc = FakeProc(pid=4321, poll_returns=7)
        popen = _fake_popen(proc)
        with pytest.raises(fleet.TurnLaunchError):
            fleet.launch_turn(
                "probe-1", isolated_home, "sid-1", "hello prompt", "omit", first=True,
                popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
            )

    def test_zero_poll_within_window_is_success_not_failure(self, isolated_home):
        """An ultra-fast legitimately-completed turn (rc == 0) must not be
        misreported as a launch failure."""
        proc = FakeProc(pid=4321, poll_returns=0)
        popen = _fake_popen(proc)
        info = fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "hello prompt", "omit", first=True,
            popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
        )
        assert info["turn_pid"] == 4321

    # -----------------------------------------------------------------
    # F-BLOCK: the prompt write must not block the manager thread.
    # -----------------------------------------------------------------

    def test_blocked_writer_with_process_alive_returns_within_bounded_window(self, isolated_home, monkeypatch):
        """A wedged/slow-booting child that never reads stdin (poll() stays
        None) must not hang launch_turn forever -- it returns within the
        bounded DOA window and is treated as success (F-DOA residual)."""
        monkeypatch.setattr(fleet, "LAUNCH_DOA_WINDOW_SECONDS", 0.2)
        block_event = threading.Event()
        stdin = FakeStdin(block_event=block_event)
        proc = FakeProc(pid=4321, stdin=stdin, poll_returns=None)
        popen = _fake_popen(proc)

        start = fleet.time.monotonic()
        info = fleet.launch_turn(
            "probe-1", isolated_home, "sid-1", "hello prompt", "omit", first=True,
            popen=popen, get_process_info=lambda pid: None, which=lambda n: "claude.cmd",
        )
        elapsed = fleet.time.monotonic() - start

        assert elapsed < 2.0  # bounded, not hung
        assert info["turn_pid"] == 4321

        # release the wedged write so the daemon thread can finish cleanly;
        # no exception should escape (it has nowhere to go but the holder).
        block_event.set()

    # M-B T4: test_blocked_writer_turn_pid_recorded_by_cmd_spawn (the
    # orphan-pid regression via cmd_spawn's post-launch lock) is DELETED --
    # cmd_spawn no longer calls launch_turn/Popen at all (native `--bg`
    # dispatch via dispatch_bg, see TestCmdSpawn below); the blocked-writer
    # DOA-window mechanism it exercised only exists for launch_turn callers
    # that still use it (cmd_send/cmd_respawn), already covered by
    # test_blocked_writer_with_process_alive_returns_within_bounded_window
    # above.


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
        assert rec["turn_pid"] is None  # native flow never populates the legacy Popen field
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
        forever by recompute_status's launch-in-flight guard."""
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
        `fleet status` can recompute_status(...) -> "dead" and persist it.
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
# _commit_launched_turn / _report_stranded_turn (post-testing wave, item 1b:
# stress-report Finding 1, CRITICAL -- the post-launch commit lock in
# cmd_spawn/cmd_send/cmd_respawn must not strand an already-launched, live
# turn just because that ONE lock acquisition timed out.)
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


class TestReportStrandedTurn:
    def test_prints_loud_message_and_appends_event(self, isolated_home, capsys):
        info = {"turn_pid": 4242, "turn_pid_ctime": "2026-07-07T12:00:00Z", "log_path": "x.jsonl"}
        fleet._report_stranded_turn("probe-1", "sid-123", info)

        err = capsys.readouterr().err
        assert "CRITICAL" in err
        assert "probe-1" in err
        assert "4242" in err

        events = [json.loads(line) for line in fleet.events_path().read_text(encoding="utf-8").splitlines()]
        assert any(e["kind"] == "turn_commit_failed" and e["name"] == "probe-1" for e in events)

    def test_never_raises_even_if_append_event_fails(self, isolated_home, monkeypatch, capsys):
        def broken_append_event(*a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr(fleet, "append_event", broken_append_event)
        info = {"turn_pid": 1, "turn_pid_ctime": None, "log_path": "x.jsonl"}
        fleet._report_stranded_turn("probe-1", "sid-123", info)  # must not raise
        assert "CRITICAL" in capsys.readouterr().err


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

    def test_expired_launch_claim_demotes_to_dead(self, isolated_home):
        """Post-testing wave, item 1c: recompute_worker must plumb the
        record's own last_activity through to recompute_status so an
        expired "working"/turn_pid=None claim (the fleet CLI died mid-
        launch, per the zombie-escape-hatch fix) actually demotes here,
        not just when recompute_status is called directly."""
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = None
        rec["last_activity"] = fleet.ctime_to_iso(
            datetime.now(timezone.utc) - timedelta(seconds=fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS + 1)
        )
        updated = fleet.recompute_worker("probe-1", rec, get_process_info=lambda pid: None)
        assert updated["status"] == "dead"


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
        """Fix wave 1 (F1): a "working" record with turn_pid=None is now the
        pre-claim launch-in-flight window and recompute_status refuses to
        demote it (a raw new_worker_record() with turn_pid never stamped
        would otherwise be indistinguishable from a real in-flight launch).
        Use a real, dead turn_pid here so the ordinary (non-guarded)
        liveness path demotes it to idle."""
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
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

    def test_probe_does_not_hold_fleet_lock(self, isolated_home):
        """Post-testing wave, item 1a (stress-report Finding 1, CRITICAL):
        cmd_status used to recompute (and probe) every worker inside one
        `with fleet_lock():` block -- get_process_info can cost hundreds of
        ms per real subprocess call, and several workers'-worth of that
        while holding the lock starved concurrent commands (including a
        spawn/send/respawn's own post-launch commit lock, after a real
        turn had already been launched). Reuses the lock-probe technique
        from test_resilience.py's test_confirm_delay_does_not_hold_fleet_lock
        / test_snapshots_registry_without_holding_lock_across_checks: a
        fake get_process_info that itself tries to acquire fleet_lock. If
        cmd_status still held the lock across the probe, this nested
        acquisition would raise FleetLockTimeout."""
        sid1, sid2 = str(uuid.uuid4()), str(uuid.uuid4())
        rec1 = fleet.new_worker_record(sid1, "C:/x", "t1", "dontask")
        rec1["turn_pid"], rec1["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        rec2 = fleet.new_worker_record(sid2, "C:/y", "t2", "dontask")
        rec2["turn_pid"], rec2["turn_pid_ctime"] = 222, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec1, "probe-2": rec2}})

        def probing_get_process_info(pid):
            with fleet.fleet_lock(timeout=0.5):
                pass  # must not raise FleetLockTimeout
            return None  # both workers recompute to dead/idle-ish; not the point of this test

        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args, get_process_info=probing_get_process_info)
        assert rc == 0

    def test_concurrent_mutation_during_probe_is_not_clobbered(self, isolated_home):
        """A worker mutated by a concurrent command while cmd_status's lock
        is released for probing must be spared -- cmd_status must not
        overwrite that concurrent write with a verdict computed against
        now-stale pre-probe data (mirrors cmd_clean's respawned-meanwhile
        guard)."""
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "t1", "dontask")
        rec["turn_pid"], rec["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-1": rec}})

        def mutating_get_process_info(pid):
            data = fleet.load_registry()
            data["workers"]["probe-1"]["turns"] = 999
            fleet.save_registry(data)
            return None

        args = fleet.build_parser().parse_args(["status"])
        rc = fleet.cmd_status(args, get_process_info=mutating_get_process_info)
        assert rc == 0
        assert fleet.load_registry()["workers"]["probe-1"]["turns"] == 999


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

    def test_wait_any_success_with_pending_returns_zero_and_says_still_working(self, isolated_home, capsys):
        """Post-testing wave, item 4 (live-report scenario 2): `wait --any`
        returning as soon as ONE worker finishes, with others still
        pending, is success -- not a timeout. Must exit 0 and must not
        call the still-running worker "timed out"."""
        sid_fast = str(uuid.uuid4())
        rec_fast = fleet.new_worker_record(sid_fast, "C:/x", "t1", "dontask")
        rec_fast["turn_pid"], rec_fast["turn_pid_ctime"] = 111, "2026-07-07T12:00:00Z"
        sid_slow = str(uuid.uuid4())
        rec_slow = fleet.new_worker_record(sid_slow, "C:/y", "t2", "dontask")
        rec_slow["turn_pid"], rec_slow["turn_pid_ctime"] = 222, "2026-07-07T12:00:00Z"
        fleet.save_registry({"workers": {"probe-fast": rec_fast, "probe-slow": rec_slow}})
        log = fleet.logs_dir() / "probe-fast.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done fast"}\n', encoding="utf-8")

        def info(pid):
            return None if pid == 111 else ("claude.exe", _parse("2026-07-07T12:00:00Z"))

        args = fleet.build_parser().parse_args(["wait", "probe-fast", "probe-slow", "--any"])
        rc = fleet.cmd_wait(args, get_process_info=info, sleep=lambda s: None, clock=lambda: 0.0)

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
    def _seed_idle(self, name="probe-1"):
        sid = str(uuid.uuid4())
        rec = fleet.new_worker_record(sid, "C:/x", "task", "dontask")
        rec["turn_pid"] = 111
        rec["turn_pid_ctime"] = "2026-07-07T12:00:00Z"
        log = fleet.logs_dir() / f"{name}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type":"result","result":"done"}\n', encoding="utf-8")
        fleet.save_registry({"workers": {name: rec}})

    def test_no_hook_errors_no_footer(self, isolated_home, capsys):
        self._seed_idle()
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]), get_process_info=lambda pid: None)
        out = capsys.readouterr().out
        assert "hook-error" not in out

    def test_hook_error_count_shown_when_nonzero(self, isolated_home, capsys):
        self._seed_idle()
        fleet.hook_errors_path().write_text(
            "2026-07-08T00:00:00Z s1 err\n2026-07-08T00:01:00Z s2 err\n2026-07-08T00:02:00Z s3 err\n",
            encoding="utf-8",
        )
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]), get_process_info=lambda pid: None)
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
