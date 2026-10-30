"""`fleet spawn --model pi:<slug>:free` end to end: the real fleet verbs, the
real bin/fleet_pi.py wrapper, a scripted pi. No network, no key, no model."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
from pi_test_support import (SLUG, calls, error_run, install_fake_pi, ok_run,
                             wait_for, wait_terminal)

MODEL = "pi:" + SLUG


@pytest.fixture
def pi_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        json.dumps({"permissions": {"allow": []},
                    "hooks": {"Stop": [{"hooks": [{"type": "command",
                                                   "command": "true"}]}]}}),
        encoding="utf-8")
    key = tmp_path / "home" / "openrouter-env"
    key.parent.mkdir()
    key.write_text("OPENROUTER_API_KEY=test-key-not-real-0000\n")
    monkeypatch.setattr(fleet, "openrouter_key_path", lambda: key)
    monkeypatch.setenv("MCX_DIR", str(tmp_path / "must-not-be-used"))
    return tmp_path


def _args(worktree, **kw):
    base = dict(name="pi1", dir=str(worktree), task="do pi things",
                mode="accept", model=MODEL, codex_adapter=None,
                max_budget_usd=None, setting_sources=None,
                token_ceiling=None, category=None, nonce=None,
                force_band=False, context=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _spawn(pi_home, monkeypatch, runs, **kw):
    log = install_fake_pi(pi_home, monkeypatch, runs)
    worktree = pi_home / "lane"
    worktree.mkdir(exist_ok=True)
    assert fleet.cmd_spawn(_args(worktree, **kw)) == 0
    rec = fleet.load_registry()["workers"][kw.get("name", "pi1")]
    return log, worktree, rec


def _job(worktree, rec):
    return Path(worktree) / ".mcx" / rec["mcx_id"]


class TestHelpers:
    def test_slug_and_substrate(self):
        assert fleet._pi_model_slug(MODEL) == SLUG
        assert fleet._pi_model_slug("codex:x") is None
        assert fleet._pi_model_slug(None) is None
        assert fleet._substrate_for_model(MODEL) == "pi/" + SLUG
        assert fleet._substrate_for_model("codex:gpt-5.6-luna") == "codex"
        assert fleet._is_codex_record({"substrate": "pi/" + SLUG})
        assert fleet._is_pi_record({"substrate": "pi/" + SLUG})
        assert not fleet._is_pi_record({"substrate": "codex"})

    @pytest.mark.parametrize("model", [
        "pi:acme/tiny-1", "pi:acme/tiny-1:paid", "pi:tiny:free", "pi:",
        "pi:acme/tiny 1:free", "pi:acme/tiny-1:free:free2",
    ])
    def test_non_free_models_are_refused(self, model):
        with pytest.raises(fleet.FleetCliError, match="pi model refused"):
            fleet._require_pi_free_model(model)

    def test_wave_substrate_accepts_pi(self):
        assert fleet._wave_substrate_of_record(
            {"substrate": "pi/" + SLUG}) == "pi/" + SLUG


class TestSpawn:
    def test_spawn_records_a_pi_row(self, pi_home, monkeypatch):
        log, worktree, rec = _spawn(pi_home, monkeypatch, [ok_run("hello")])
        assert rec["substrate"] == "pi/" + SLUG
        assert rec["dispatch_kind"] == "mcx"
        assert rec["model"] == MODEL
        assert rec["session_id"] is None
        assert rec["status"] == "working"
        assert rec["mcx_approval"] == "auto"
        job = _job(worktree, rec)
        assert (job / "model").read_text().strip() == SLUG
        assert "state/tasks/pi1.md" in (job / "prompt").read_text()
        assert not Path(os.environ["MCX_DIR"]).exists()
        wait_terminal(job)
        [call] = calls(log)
        assert call["argv"][call["argv"].index("--model") + 1] == SLUG
        assert call["argv"][call["argv"].index("--provider") + 1] == "openrouter"

    @pytest.mark.parametrize("model", ["pi:acme/tiny-1", "pi:acme/tiny:paid"])
    def test_non_free_spawn_is_refused_before_any_write(self, pi_home,
                                                        monkeypatch, model):
        log = install_fake_pi(pi_home, monkeypatch, [ok_run()])
        worktree = pi_home / "lane"
        worktree.mkdir()
        with pytest.raises(fleet.FleetCliError, match="pi model refused"):
            fleet.cmd_spawn(_args(worktree, model=model))
        assert "pi1" not in fleet.load_registry()["workers"]
        assert calls(log) == []
        assert not (worktree / ".mcx").exists()

    def test_missing_key_is_refused(self, pi_home, monkeypatch):
        install_fake_pi(pi_home, monkeypatch, [ok_run()])
        monkeypatch.delenv("OPENROUTER_API_KEY")
        (pi_home / "home" / "openrouter-env").unlink()
        worktree = pi_home / "lane"
        worktree.mkdir()
        with pytest.raises(fleet.FleetCliError, match="no OpenRouter key"):
            fleet.cmd_spawn(_args(worktree))
        assert "pi1" not in fleet.load_registry()["workers"]

    def test_pi_cannot_be_a_supervisor_model(self):
        with pytest.raises(fleet.FleetCliError, match="worker lanes only"):
            fleet._enforce_tier_policy("supervisor", MODEL)

    def test_codex_adapter_flag_does_not_misroute_pi(self, pi_home, monkeypatch):
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [ok_run()],
                                     codex_adapter="native")
        assert rec["dispatch_kind"] == "mcx"
        assert rec.get("adapter_state") is None

    def test_wrapper_refusal_rolls_the_row_back(self, pi_home, monkeypatch):
        install_fake_pi(pi_home, monkeypatch, [ok_run()])
        monkeypatch.setenv("FLEET_PI_BIN", str(pi_home / "no-such-pi"))
        worktree = pi_home / "lane"
        worktree.mkdir()
        # find_pi() accepts an explicit path without checking it, so break the
        # wrapper itself: a key-less environment makes spawn exit 1.
        monkeypatch.delenv("OPENROUTER_API_KEY")
        monkeypatch.setenv("FLEET_PI_KEY_FILE", str(pi_home / "nokey"))
        with pytest.raises(fleet.FleetCliError, match="pi spawn|codex spawn"):
            fleet.cmd_spawn(_args(worktree))
        assert "pi1" not in fleet.load_registry()["workers"]


class TestVerbs:
    def test_status_goes_idle_and_result_prints_the_answer(
            self, pi_home, monkeypatch, capsys):
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [ok_run("42")])
        wait_terminal(_job(worktree, rec))
        out = fleet.recompute_worker_codex("pi1", rec)
        assert out["status"] == "idle"
        assert out["mcx_result_text"].strip() == "42"
        capsys.readouterr()
        assert fleet.cmd_result(SimpleNamespace(name="pi1")) == 0
        assert capsys.readouterr().out.strip() == "42"

    def test_provider_failure_is_dead_not_idle(self, pi_home, monkeypatch):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        _log, worktree, rec = _spawn(pi_home, monkeypatch,
                                     [error_run("400 bad request")])
        wait_terminal(_job(worktree, rec))
        assert fleet.recompute_worker_codex("pi1", rec)["status"] == "dead"

    def test_stalled_lane_is_dead(self, pi_home, monkeypatch):
        monkeypatch.setenv("FLEET_PI_PROVIDER_RESTARTS", "0")
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        install_fake_pi(pi_home, monkeypatch, [run])
        monkeypatch.setenv("FLEET_PI_STALL_MINUTES", "0.03")
        worktree = pi_home / "lane"
        worktree.mkdir()
        assert fleet.cmd_spawn(_args(worktree)) == 0
        rec = fleet.load_registry()["workers"]["pi1"]
        assert wait_terminal(_job(worktree, rec), timeout=15) == "stopped"
        assert fleet.recompute_worker_codex("pi1", rec)["status"] == "dead"

    def test_runner_crash_is_not_working_forever(self, pi_home, monkeypatch):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [run])
        job = _job(worktree, rec)
        wait_for(lambda: (job / "state").read_text().strip() == "running", 10)
        assert fleet.recompute_worker_codex("pi1", rec)["status"] == "working"
        pid = int((job / "pid").read_text())
        os.kill(pid, 9)  # runner dies without writing a terminal state
        wait_for(lambda: not _alive(pid), 10)
        assert fleet.recompute_worker_codex("pi1", rec)["status"] == "dead"

    def test_peek_shows_the_wrapper_log(self, pi_home, monkeypatch, capsys):
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [ok_run("peekable")])
        wait_terminal(_job(worktree, rec))
        capsys.readouterr()
        assert fleet.cmd_peek(SimpleNamespace(name="pi1", lines=20)) == 0
        out = capsys.readouterr().out
        assert "tool bash" in out and "peekable" in out

    def test_send_resumes_the_pi_session(self, pi_home, monkeypatch):
        log, worktree, rec = _spawn(pi_home, monkeypatch,
                                    [ok_run("one"), ok_run("two")])
        job = _job(worktree, rec)
        wait_terminal(job)
        fresh = fleet.recompute_worker_codex("pi1", rec)
        _write_rec("pi1", fresh)
        assert fleet.cmd_send(SimpleNamespace(
            name="pi1", message="and now this", nonce=None,
            force_band=False)) == 0
        wait_for(lambda: len(calls(log)) == 2, 10)
        wait_for(lambda: fleet.cmd_result.__name__ and
                 (job / "result").exists() and
                 (job / "result").read_text().strip() == "two", 10)
        second = calls(log)[1]["argv"]
        assert "--continue" in second and second[-1] == "and now this"
        row = fleet.load_registry()["workers"]["pi1"]
        assert row["turns"] == 2

    def test_send_refuses_a_running_turn(self, pi_home, monkeypatch):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [run])
        job = _job(worktree, rec)
        wait_for(lambda: (job / "state").read_text().strip() == "running", 10)
        with pytest.raises(fleet.FleetCliError, match="turn running"):
            fleet.cmd_send(SimpleNamespace(name="pi1", message="x", nonce=None,
                                           force_band=False))
        fleet.cmd_kill(SimpleNamespace(name="pi1", nonce=None, yes=True))

    def test_interrupt_and_kill_stop_the_job(self, pi_home, monkeypatch):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [run])
        job = _job(worktree, rec)
        wait_for(lambda: (job / "state").read_text().strip() == "running", 10)
        assert fleet.cmd_interrupt(SimpleNamespace(name="pi1", nonce=None)) == 0
        assert (job / "state").read_text().strip() == "stopped"
        assert fleet.load_registry()["workers"]["pi1"]["status"] == "interrupted"
        assert fleet.cmd_kill(SimpleNamespace(name="pi1", nonce=None,
                                              yes=True)) == 0
        assert fleet.load_registry()["workers"]["pi1"]["status"] == "dead"

    def test_respawn_dispatches_a_fresh_job(self, pi_home, monkeypatch):
        log, worktree, rec = _spawn(pi_home, monkeypatch,
                                    [ok_run("one"), ok_run("fresh")])
        wait_terminal(_job(worktree, rec))
        assert fleet.cmd_respawn(SimpleNamespace(
            name="pi1", task=None, force=False, yes=True, nonce=None,
            force_band=False, max_budget_usd=None, setting_sources=None,
            token_ceiling=None)) == 0
        new = fleet.load_registry()["workers"]["pi1"]
        assert new["mcx_id"] != rec["mcx_id"]
        assert new["substrate"] == "pi/" + SLUG
        wait_terminal(_job(worktree, new))
        second = calls(log)[1]["argv"]
        assert "--continue" not in second  # fresh context, not a resume

    def test_wave_close_style_stop_uses_the_wrapper(self, pi_home, monkeypatch):
        run = {"events": [{"type": "agent_start"}, {"sleep": 30}]}
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [run])
        job = _job(worktree, rec)
        wait_for(lambda: (job / "state").read_text().strip() == "running", 10)
        proc = fleet._mcx_run(rec, ["stop", rec["mcx_id"]])
        assert proc.returncode == 0
        assert (job / "state").read_text().strip() == "stopped"


class TestLaneDone:
    def test_finished_pi_lane_mails_lane_done(self, pi_home, monkeypatch):
        _log, worktree, rec = _spawn(pi_home, monkeypatch, [ok_run("done")])
        wait_terminal(_job(worktree, rec))
        parent_sid = "supervisor-sid"
        parent_name = "sup|inc-test|boot"
        (pi_home / "supervisor").mkdir()
        parent = fleet.new_worker_record(parent_sid, str(pi_home), "supervise",
                                         "bypass")
        parent["status"] = "idle"
        data = fleet.load_registry()
        data["workers"][parent_name] = parent
        data["workers"]["pi1"]["spawned_by"] = parent_sid
        data["workers"]["pi1"]["status"] = "working"
        fleet.save_registry(data)
        fleet.write_incarnation({
            "state": "held", "session_id": parent_sid,
            "heartbeat_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")})
        sends = []
        monkeypatch.setattr(fleet, "_cmd_send_native",
                            lambda name, message: sends.append((name, message)) or 0)
        assert fleet.sweep_lane_done(run=subprocess.run) == ["pi1"]
        assert sends and sends[0][0] == parent_name
        assert sends[0][1].startswith("LANE-DONE pi1 idle")


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    return True


def _write_rec(name, rec):
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"][name] = rec
        fleet.save_registry(data)
