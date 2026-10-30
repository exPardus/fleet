"""bin/fleet_pi.py: the mcx-shaped pi wrapper, driven against a scripted pi."""
import json
import os
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
    work.mkdir()
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
        (job / "pid").write_text("999999999\n")
        assert wrap(["result", job_id], lane).returncode == 1
