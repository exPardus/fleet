"""bin/fleet_pi.py: the mcx-shaped pi wrapper, driven against a scripted pi."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pi_test_support import (KEY, SLUG, assistant, calls, error_run,
                             install_fake_pi, job_state, ok_run, wait_for,
                             wait_terminal)

WRAPPER = Path(__file__).resolve().parents[1] / "bin" / "fleet_pi.py"


def wrap(args, cwd, input_text=None):
    env = dict(os.environ, MCX_DIR=str(Path(cwd) / ".mcx"))
    return subprocess.run([sys.executable, str(WRAPPER), *args], cwd=cwd,
                          env=env, input=input_text, capture_output=True,
                          text=True, timeout=60)


def spawn(cwd, slug=SLUG, prompt="do the thing", effort="medium"):
    proc = wrap(["spawn", "-m", slug, "-r", effort, prompt], cwd)
    assert proc.returncode == 0, proc.stderr
    job_id = proc.stdout.strip()
    return job_id, Path(cwd) / ".mcx" / job_id


@pytest.fixture
def lane(tmp_path):
    work = tmp_path / "lane"
    (work / ".git").mkdir(parents=True)
    return work


class TestSlugGuard:
    @pytest.mark.parametrize("slug", [
        "acme/tiny-1", "acme/tiny-1:free2", "tiny-1:free", "acme/tiny:paid",
        "pi:acme/tiny-1", "", "acme/ti ny:free", "../x/y:free",
    ])
    def test_non_free_slugs_never_start_pi(self, tmp_path, monkeypatch, lane,
                                           slug):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        proc = wrap(["spawn", "-m", slug, "x"], lane)
        assert proc.returncode == 1
        assert "free" in proc.stderr
        assert calls(log) == []
        assert not (lane / ".mcx").exists()

    def test_pi_prefix_is_stripped_for_a_free_slug(self, tmp_path, monkeypatch,
                                                   lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane, slug="pi:" + SLUG)
        assert wait_terminal(job) == "done"
        assert (job / "model").read_text().strip() == SLUG


class TestRun:
    def test_success_derives_done_from_events(self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run("the answer")])
        job_id, job = spawn(lane)
        assert wrap(["result", job_id], lane).returncode in (0, 2)
        assert wait_terminal(job) == "done"
        proc = wrap(["result", job_id], lane)
        assert (proc.returncode, proc.stdout.strip()) == (0, "the answer")
        [call] = calls(log)
        argv = call["argv"]
        # exact slug, pinned provider, JSON events, thinking from effort
        assert argv[argv.index("--provider") + 1] == "openrouter"
        assert argv[argv.index("--model") + 1] == SLUG
        assert argv[argv.index("--mode") + 1] == "json"
        assert argv[argv.index("--thinking") + 1] == "medium"
        assert argv[-2:] == ["--", "do the thing"]
        assert call["cwd"] == str(lane) or Path(call["cwd"]).samefile(lane)
        assert call["has_key"] is True
        log_text = (job / "log").read_text()
        assert "tool bash" in log_text and "assistant: the answer" in log_text
        assert (job / "events.jsonl").read_text().count("\n") >= 6

    def test_key_never_lands_in_the_job_directory(self, tmp_path, monkeypatch,
                                                  lane):
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        for path in job.rglob("*"):
            if path.is_file():
                assert KEY not in path.read_text(errors="replace"), path

    def test_provider_error_with_exit_zero_is_failed(self, tmp_path,
                                                     monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        install_fake_pi(tmp_path, monkeypatch, [error_run("400 bad request")])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"
        proc = wrap(["result", job_id], lane)
        assert proc.returncode == 1 and "400 bad request" in proc.stderr

    def test_exhausted_auto_retry_is_failed(self, tmp_path, monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        run = {"events": [
            {"type": "agent_start"},
            {"type": "auto_retry_start", "attempt": 1, "maxAttempts": 5,
             "delayMs": 1, "errorMessage": "503 no upstreams available"},
            {"type": "auto_retry_end", "success": False,
             "finalError": "503 no upstreams available"},
            {"type": "agent_end", "messages": [], "willRetry": False},
        ]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"
        assert "503" in (job / "error").read_text()
        assert "retry 1/5" in (job / "log").read_text()

    def test_error_event_is_failed(self, tmp_path, monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        run = {"events": [{"type": "agent_start"},
                          {"type": "error", "message": "boom"},
                          {"type": "agent_end", "messages": [],
                           "willRetry": False}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"

    def test_exit_without_agent_end_is_failed(self, tmp_path, monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        install_fake_pi(tmp_path, monkeypatch,
                        [{"events": [{"type": "agent_start"}], "exit": 0}])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"
        assert "agent_end" in (job / "error").read_text()

    def test_nonzero_exit_after_clean_events_is_still_done(
            self, tmp_path, monkeypatch, lane):
        run = ok_run("fine")
        run["exit"] = 3
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"

    def test_model_mismatch_is_failed(self, tmp_path, monkeypatch, lane):
        run = {"events": [{"type": "agent_start"},
                          assistant("hi", model="other/model:free"),
                          {"type": "agent_end", "messages": [],
                           "willRetry": False}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"
        assert "model mismatch" in (job / "error").read_text()

    def test_answer_only_in_thinking_is_kept(self, tmp_path, monkeypatch, lane):
        run = {"events": [{"type": "agent_start"},
                          assistant("", thinking="42 is the answer"),
                          {"type": "agent_end", "messages": [],
                           "willRetry": False}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        assert "42 is the answer" in wrap(["result", job_id], lane).stdout

    def test_transient_provider_failure_restarts_once(self, tmp_path,
                                                      monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch,
                              [error_run("429 upstream rate-limited"),
                               ok_run("recovered")])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        first, second = calls(log)
        assert "--continue" not in first["argv"]
        assert "--continue" in second["argv"]
        assert second["argv"][-1].startswith("Continue the task")
        assert wrap(["result", job_id], lane).stdout.strip() == "recovered"

    def test_non_transient_failure_does_not_restart(self, tmp_path,
                                                    monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch,
                              [error_run("400 bad request"), ok_run()])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "failed"
        assert len(calls(log)) == 1


class TestConfig:
    def test_patient_retry_and_default_telemetry(self, tmp_path, monkeypatch,
                                                 lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        settings = json.loads((job / "pi-agent" / "settings.json").read_text())
        assert settings["retry"]["maxRetries"] == 5
        assert settings["retry"]["baseDelayMs"] == 4000
        assert settings["retry"]["maxAgentDelayMs"] >= 60000
        # install telemetry stays at pi's default (inkling 403s without the
        # attribution headers it controls): never written, never overridden.
        assert "enableInstallTelemetry" not in settings
        assert "PI_TELEMETRY" not in os.environ
        assert calls(log)[0]["agent_dir"] == str(job / "pi-agent")
        assert not (job / "pi-agent" / "models.json").exists()

    def test_dots_gets_the_max_tokens_override(self, tmp_path, monkeypatch,
                                               lane):
        slug = "dots-studio/dots-3-note-preview:free"
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        run = ok_run()
        run["events"][4] = assistant("x", model=slug)
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane, slug=slug)
        assert wait_terminal(job) == "done"
        models = json.loads((job / "pi-agent" / "models.json").read_text())
        assert models["providers"]["openrouter"]["modelOverrides"][slug] == {
            "maxTokens": 32768}

    def test_retry_knobs_are_configurable(self, tmp_path, monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_MAX_RETRIES", "7")
        monkeypatch.setenv("FLEET_PI_RETRY_BASE_MS", "9000")
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        settings = json.loads((job / "pi-agent" / "settings.json").read_text())
        assert (settings["retry"]["maxRetries"],
                settings["retry"]["baseDelayMs"]) == (7, 9000)

    def test_missing_key_refuses_before_pi(self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.delenv("OPENROUTER_API_KEY")
        monkeypatch.setenv("FLEET_PI_KEY_FILE", str(tmp_path / "no-such-file"))
        proc = wrap(["spawn", "-m", SLUG, "x"], lane)
        assert proc.returncode == 1 and "OPENROUTER_API_KEY" in proc.stderr
        assert calls(log) == []


class TestWatchdogAndControl:
    def test_stall_kills_and_marks_stopped(self, tmp_path, monkeypatch, lane):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        monkeypatch.setenv("FLEET_PI_STALL_MINUTES", "0.03")  # ~1.8 s
        job_id, job = spawn(lane)
        started = wait_for(lambda: job_state(job) == "running", 10)
        assert started
        assert wait_terminal(job, timeout=15) == "stopped"
        assert "stalled" in (job / "error").read_text()
        proc = wrap(["result", job_id], lane)
        assert proc.returncode == 1

    def test_stop_marks_stopped_and_kills_pi(self, tmp_path, monkeypatch, lane):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        wait_for(lambda: job_state(job) == "running", 10)
        assert wrap(["result", job_id], lane).returncode == 2
        assert wrap(["stop", job_id], lane).returncode == 0
        assert job_state(job) == "stopped"
        assert wrap(["result", job_id], lane).returncode == 1

    def test_steer_resumes_the_session(self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch,
                              [ok_run("first"), ok_run("second")])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        proc = wrap(["steer", job_id, "-"], lane, input_text="now do more")
        assert proc.returncode == 0, proc.stderr
        wait_for(lambda: len(calls(log)) == 2, 10)
        assert wait_terminal(job) == "done"
        wait_for(lambda: wrap(["result", job_id], lane).stdout.strip()
                 == "second", 10)
        first, second = calls(log)
        assert "--continue" not in first["argv"]
        assert "--continue" in second["argv"]
        assert second["argv"][-1] == "now do more"
        # the follow-up keeps the same session directory
        sd = second["argv"][second["argv"].index("--session-dir") + 1]
        assert sd == first["argv"][first["argv"].index("--session-dir") + 1]

    def test_steer_refuses_a_live_job(self, tmp_path, monkeypatch, lane):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        install_fake_pi(tmp_path, monkeypatch, [run])
        job_id, job = spawn(lane)
        wait_for(lambda: job_state(job) == "running", 10)
        proc = wrap(["steer", job_id, "-"], lane, input_text="hey")
        assert proc.returncode == 1 and "running" in proc.stderr
        wrap(["stop", job_id], lane)

    def test_unknown_job(self, tmp_path, lane):
        assert wrap(["result", "deadbeef"], lane).returncode == 1
        assert wrap(["stop", "deadbeef"], lane).returncode == 1
        assert wrap(["result", "../etc"], lane).returncode == 1

    def test_dead_runner_reads_failed_not_live(self, tmp_path, monkeypatch,
                                               lane):
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        (job / "state").write_text("running\n")
        (job / "pid").write_text("999999999 1\n")
        assert wrap(["result", job_id], lane).returncode == 1


class TestChildEnv:
    def test_pi_gets_an_allowlisted_environment(self, tmp_path, monkeypatch,
                                                lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "x")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        keys = set(calls(log)[0]["env_keys"])
        assert "UNRELATED_SECRET_TOKEN" not in keys
        assert "AWS_SECRET_ACCESS_KEY" not in keys
        assert {"PATH", "OPENROUTER_API_KEY", "PI_CODING_AGENT_DIR",
                "FLEET_PI_FAKE_LOG"} <= keys
        allowed = {"PATH", "HOME", "LANG", "TERM", "TMPDIR",
                   "OPENROUTER_API_KEY", "PI_CODING_AGENT_DIR",
                   "PI_SKIP_VERSION_CHECK", "UV_CACHE_DIR", "UV_PYTHON_INSTALL_DIR", "PWD", "SHLVL", "_", "LC_CTYPE"}
        assert all(k in allowed or k.startswith("FLEET_PI_FAKE_")
                   for k in keys), keys

    def test_escape_variables_are_not_honoured(self, tmp_path, monkeypatch,
                                               lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.setenv("UNRELATED_SECRET_TOKEN", "x")
        monkeypatch.setenv("FLEET_PI_FULL_ENV", "1")
        monkeypatch.setenv("FLEET_PI_EVIL", "1")
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        keys = set(calls(log)[0]["env_keys"])
        assert not keys & {"UNRELATED_SECRET_TOKEN", "FLEET_PI_FULL_ENV",
                           "FLEET_PI_EVIL"}


class TestWindowsRefusal:
    def test_wrapper_refuses_on_windows(self, monkeypatch, capsys):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        import fleet_platform

        monkeypatch.setattr(fleet_pi, "PLATFORM", fleet_platform._WindowsPlatform())
        assert fleet_pi.main(["list"]) == 1
        assert "unsupported on Windows" in capsys.readouterr().err


def _bwrap_runs(tmp_path):
    path = tmp_path / "bwrap-calls.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    return [r for r in rows if r["cmd"] != ["/usr/bin/true"]]


def _pairs(opts, flag, width):
    return [tuple(opts[i + 1:i + 1 + width]) for i, o in enumerate(opts) if o == flag]


class TestSandbox:
    def test_pi_runs_inside_bwrap_with_expected_argv(self, tmp_path,
                                                     monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        (run,) = _bwrap_runs(tmp_path)
        opts, cmd = run["opts"], run["cmd"]
        assert cmd[0] == os.environ["FLEET_PI_BIN"] and "--provider" in cmd
        for flag in ("--die-with-parent", "--unshare-pid", "--new-session",
                     "--unshare-ipc", "--unshare-uts", "--unshare-cgroup-try"):
            assert flag in opts
        assert "--unshare-net" not in opts
        assert "--clearenv" not in opts and "--setenv" not in opts
        binds = [b[0] for b in _pairs(opts, "--bind", 2)]
        assert str(lane) in binds
        assert str(job) not in binds            # the job dir is not rw
        assert sorted(binds) == sorted(
            [str(lane), str(job / "home"), str(job / "sessions"),
             str(job / "pi-agent")])
        ro = [b[0] for b in _pairs(opts, "--ro-bind", 2)]
        assert str(job) in ro and str(lane / ".git") in ro
        assert str(job / "pi-agent" / "settings.json") in ro
        assert ("/usr", "/usr") in _pairs(opts, "--ro-bind", 2)
        assert ("/tmp",) in _pairs(opts, "--tmpfs", 1)
        assert KEY not in json.dumps(run)       # no secret in argv
        # the fake pi saw the scrubbed env, key included
        seen = calls(log)[0]["env_keys"]
        assert "OPENROUTER_API_KEY" in seen and "PI_CODING_AGENT_DIR" in seen

    def test_home_secrets_are_never_bound(self, tmp_path, monkeypatch, lane):
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        home = Path.home()
        job_id, job = spawn(lane)
        assert wait_terminal(job) == "done"
        (run,) = _bwrap_runs(tmp_path)
        opts = run["opts"]
        mounted = [o for i, o in enumerate(opts)
                   if opts[i - 1] in ("--bind", "--ro-bind") or
                   (i > 1 and opts[i - 2] in ("--bind", "--ro-bind"))]
        for path in mounted:
            assert path != str(home), "whole HOME must not be mounted"
            for secret in (".ssh", ".config", "proga", ".gnupg", ".aws"):
                assert not path.startswith(str(home / secret)), path

    def test_missing_bwrap_refuses_spawn_without_running_pi(
            self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.setenv("FLEET_PI_TEST_BWRAP", str(tmp_path / "no-such-bwrap"))
        proc = wrap(["spawn", "-m", SLUG, "x"], lane)
        assert proc.returncode == 1
        assert "bwrap" in proc.stderr and "unsandboxed" in proc.stderr
        assert calls(log) == [] and not (lane / ".mcx").exists()

    def test_no_bwrap_on_path_refuses(self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.delenv("FLEET_PI_TEST_BWRAP")
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        proc = wrap(["spawn", "-m", SLUG, "x"], lane)
        assert proc.returncode == 1 and "bwrap not found" in proc.stderr
        assert calls(log) == []

    def test_failing_probe_refuses_and_never_runs_pi(self, tmp_path,
                                                     monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        monkeypatch.setenv("FLEET_PI_FAKE_BWRAP_FAIL", "1")
        proc = wrap(["spawn", "-m", SLUG, "x"], lane)
        assert proc.returncode == 1
        assert "probe failed" in proc.stderr and "unsandboxed" in proc.stderr
        assert calls(log) == []

    def test_bwrap_vanishing_after_spawn_fails_the_job(self, tmp_path,
                                                       monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        monkeypatch.setenv("FLEET_PI_TEST_BWRAP", str(tmp_path / "gone"))
        (job / "state").write_text("starting\n")
        (job / "turn").write_text("2\n")
        n = len(calls(log))
        proc = wrap(["_run", job_id], lane)
        assert job_state(job) == "failed"
        assert "bwrap" in (job / "error").read_text()
        assert len(calls(log)) == n

    def test_linked_worktree_git_pointers_are_readonly(self, tmp_path):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        common = tmp_path / "main" / ".git"
        gitdir = common / "worktrees" / "w"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n")
        work = tmp_path / "w"
        work.mkdir()
        (work / ".git").write_text(f"gitdir: {gitdir}\n")
        (gitdir / "gitdir").write_text(f"{work / '.git'}\n")
        job = work / ".mcx" / "abcd1234"
        job.mkdir(parents=True)
        argv, env = fleet_pi.sandbox_command(
            ["/bin/pi", "x"], str(work), job, {"PATH": "/usr/bin",
                                               "OPENROUTER_API_KEY": KEY},
            bwrap="/x/bwrap")
        triples = [tuple(argv[i:i + 3]) for i in range(len(argv))]
        assert ("--bind", str(gitdir), str(gitdir)) not in triples
        for path in (gitdir, common, work / ".git", job):
            assert ("--ro-bind", str(path), str(path)) in triples, path
        assert argv[-3:] == ["--", "/bin/pi", "x"]
        assert KEY not in argv and env["OPENROUTER_API_KEY"] == KEY
        assert fleet_pi.check_lane_cwd(str(work)) == str(work.resolve())
        (gitdir / "gitdir").write_text(f"{tmp_path / 'elsewhere' / '.git'}\n")
        with pytest.raises(fleet_pi.WrapperError, match="does not belong"):
            fleet_pi.check_lane_cwd(str(work))

    def test_job_dir_is_readonly_inside_the_real_sandbox(self, tmp_path,
                                                         monkeypatch, lane):
        bwrap = shutil.which("bwrap")
        if not bwrap or not os.path.isfile("/usr/bin/sh"):
            pytest.skip("no bwrap")
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        monkeypatch.delenv("FLEET_PI_TEST_BWRAP", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "h"))
        job = lane / ".mcx" / "abcd1234"
        other = lane / ".mcx" / "ffff0000"
        for d in (job / "home", job / "sessions", other):
            d.mkdir(parents=True)
        for name in ("cwd", "pid", "state", "result"):
            (job / name).write_text("orig\n")
        (other / "state").write_text("orig\n")
        script = ("for f in cwd pid state result newfile; do "
                  "echo hacked > $J/$f 2>/dev/null && echo WROTE:$f; done; "
                  "echo ok > $J/home/a && echo HOMEOK; "
                  "echo ok > $J/sessions/a && echo SESSOK; "
                  "test -e $J/../ffff0000 && echo SIBLING; "
                  "echo x > .git/config 2>/dev/null && echo GITWROTE; "
                  "echo OPENROUTER_API_KEY=$OPENROUTER_API_KEY")
        env = {"PATH": "/usr/bin:/bin", "OPENROUTER_API_KEY": KEY, "J": str(job)}
        argv, cenv = fleet_pi.sandbox_command(
            ["/usr/bin/sh", "-c", script], str(lane), job, env, bwrap=bwrap)
        try:
            fleet_pi.probe_bwrap(bwrap)
        except fleet_pi.WrapperError:
            pytest.skip("bwrap cannot create a sandbox here")
        cenv["J"] = str(job)
        out = subprocess.run(argv, env=cenv, cwd=lane, capture_output=True,
                             text=True, timeout=60)
        assert "WROTE" not in out.stdout, out.stdout
        assert "HOMEOK" in out.stdout and "SESSOK" in out.stdout, out
        assert "SIBLING" not in out.stdout and "GITWROTE" not in out.stdout
        assert f"OPENROUTER_API_KEY={KEY}" in out.stdout
        for name in ("cwd", "pid", "state", "result"):
            assert (job / name).read_text() == "orig\n"
        assert not (job / "newfile").exists()


class TestEscapes:
    def test_bwrap_override_ignored_outside_tests(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        fake = tmp_path / "bwrap"
        fake.write_text("#!/bin/sh\nexec \"$@\"\n")
        fake.chmod(0o755)
        monkeypatch.setenv("FLEET_PI_BWRAP", str(fake))
        monkeypatch.setenv("FLEET_PI_TEST_BWRAP", str(fake))
        monkeypatch.delenv("PYTEST_CURRENT_TEST")
        monkeypatch.setenv("PATH", str(tmp_path))
        with pytest.raises(fleet_pi.WrapperError, match="not a root-owned"):
            fleet_pi.find_bwrap()           # on PATH but user-owned: refused
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        with pytest.raises(fleet_pi.WrapperError, match="bwrap not found"):
            fleet_pi.find_bwrap()

    def test_system_bwrap_must_be_root_owned(self):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        assert fleet_pi._trusted_bwrap("/usr/bin/bwrap") or not os.path.exists(
            "/usr/bin/bwrap")
        assert not fleet_pi._trusted_bwrap(str(WRAPPER))

    def test_lane_directory_must_be_a_worktree_not_home(self, tmp_path,
                                                         monkeypatch, lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        home = tmp_path / "home"
        (home / "proj" / ".git").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(home))
        for bad in (str(home), str(tmp_path), "relative", str(tmp_path / "no")):
            with pytest.raises(fleet_pi.WrapperError):
                fleet_pi.check_lane_cwd(bad)
        (tmp_path / "plain").mkdir()
        with pytest.raises(fleet_pi.WrapperError, match="not a git worktree"):
            fleet_pi.check_lane_cwd(str(tmp_path / "plain"))
        assert fleet_pi.check_lane_cwd(str(home / "proj"))
        assert fleet_pi.check_lane_cwd(str(lane))

    def test_rewritten_cwd_never_gets_bound(self, tmp_path, monkeypatch, lane):
        log = install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        job_id, job = spawn(lane)
        wait_terminal(job)
        n = len(calls(log))
        (job / "cwd").write_text(str(Path.home()) + "\n")
        (job / "state").write_text("starting\n")
        (job / "turn").write_text("2\n")
        wrap(["_run", job_id], lane)
        assert job_state(job) == "failed"
        assert "refusing lane directory" in (job / "error").read_text()
        assert len(calls(log)) == n

    def test_node_prefix_covering_home_is_refused(self, tmp_path, monkeypatch,
                                                  lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        home = tmp_path / "home"
        (home / "bin").mkdir(parents=True)
        (home / "lib" / "node_modules").mkdir(parents=True)
        node = home / "bin" / "node"
        node.write_text("#!/bin/sh\n")
        node.chmod(0o755)
        monkeypatch.setenv("HOME", str(home))
        job = lane / ".mcx" / "abcd1234"
        job.mkdir(parents=True)
        with pytest.raises(fleet_pi.WrapperError, match=r"\$HOME"):
            fleet_pi.sandbox_command(
                ["/bin/pi"], str(lane), job,
                {"PATH": str(home / "bin")}, bwrap="/x/bwrap")

    def test_node_is_bound_by_prefix(self, tmp_path, monkeypatch, lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        prefix = tmp_path / "node-v1"
        (prefix / "bin").mkdir(parents=True)
        (prefix / "lib" / "node_modules").mkdir(parents=True)
        node = prefix / "bin" / "node"
        node.write_text("#!/bin/sh\n")
        node.chmod(0o755)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        job = lane / ".mcx" / "abcd1234"
        job.mkdir(parents=True)
        argv, _ = fleet_pi.sandbox_command(
            ["/bin/pi"], str(lane), job, {"PATH": str(prefix / "bin")},
            bwrap="/x/bwrap")
        assert ("--ro-bind", str(prefix), str(prefix)) in [
            tuple(argv[i:i + 3]) for i in range(len(argv))]

    def test_lone_node_binary_never_mounts_its_directory_tree(
            self, tmp_path, monkeypatch, lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".local" / "share" / "secret").mkdir(parents=True)
        node = home / ".local" / "bin" / "node"
        node.write_text("#!/bin/sh\n")
        node.chmod(0o755)
        monkeypatch.setenv("HOME", str(home))
        job = lane / ".mcx" / "abcd1234"
        job.mkdir(parents=True)
        argv, _ = fleet_pi.sandbox_command(
            ["/bin/pi"], str(lane), job, {"PATH": str(home / ".local" / "bin")},
            bwrap="/x/bwrap")
        triples = [tuple(argv[i:i + 3]) for i in range(len(argv))]
        assert ("--ro-bind", str(node), str(node)) in triples
        assert ("--ro-bind", str(home / ".local"),
                str(home / ".local")) not in triples

    def test_planted_temp_symlink_is_not_followed(self, tmp_path, lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        job = lane / ".mcx" / "abcd1234"
        agent = job / "pi-agent"
        agent.mkdir(parents=True)
        victim = tmp_path / "victim"
        victim.write_text("precious\n")
        for name in ("settings.json.tmp", "models.json.tmp", "settings.json"):
            (agent / name).symlink_to(victim)
        fleet_pi.write_agent_config(job, "dots-studio/dots-3-note-preview:free")
        assert victim.read_text() == "precious\n"
        assert (agent / "settings.json").is_file()
        assert not (agent / "settings.json").is_symlink()

    def test_symlinked_config_or_dirs_refuse_the_bind(self, tmp_path, lane):
        sys.path.insert(0, str(WRAPPER.parent))
        import fleet_pi
        job = lane / ".mcx" / "abcd1234"
        for sub in ("home", "sessions", "pi-agent"):
            (job / sub).mkdir(parents=True)
        fleet_pi.write_agent_config(job, SLUG)
        run = lambda: fleet_pi.sandbox_command(
            ["/bin/pi"], str(lane), job, {"PATH": "/usr/bin"}, bwrap="/x/bwrap")
        run()
        victim = tmp_path / "victim"
        victim.write_text("x")
        (job / "pi-agent" / "models.json").symlink_to(victim)
        with pytest.raises(fleet_pi.WrapperError, match="not a regular file"):
            run()
        (job / "pi-agent" / "models.json").unlink()
        (job / "sessions").rmdir()
        (job / "sessions").symlink_to(tmp_path)
        with pytest.raises(fleet_pi.WrapperError, match="not a plain directory"):
            run()

    def test_stop_ignores_a_rewritten_pid(self, tmp_path, monkeypatch, lane):
        install_fake_pi(tmp_path, monkeypatch, [ok_run()])
        victim = subprocess.Popen(["sleep", "30"])
        try:
            job_id, job = spawn(lane)
            wait_terminal(job)
            for text in (f"{victim.pid}\n", f"{victim.pid} 1\n",
                         f"{victim.pid} {_start(victim.pid)}\n"):
                (job / "pid").write_text(text)
                (job / "state").write_text("running\n")
                assert wrap(["stop", job_id], lane).returncode == 0
                assert victim.poll() is None, text
                assert job_state(job) == "stopped"
        finally:
            victim.kill()
            victim.wait()


def _start(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])
