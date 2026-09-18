"""Item 29: `--model codex:<model>` lanes dispatched through mcx.

Every test runs OFFLINE against a stub `mcx` on a redirected PATH -- no Codex
API call is possible (the weekly limit is exhausted until 2026-09-20T18:16Z)
and none is needed: the fleet/mcx contract is argv + exit codes + the job
directory, which the stub reproduces faithfully:

- `mcx spawn -m MODEL "prompt"` prints an 8-char worker id and creates
  $MCX_DIR/<id>/{state,model,prompt,log,result};
- `mcx result <id>` exits 2 while the state file says starting/running, 0 with
  the result on stdout when done, 1 when stopped/unknown;
- `mcx steer <id> -` reads the new prompt on stdin and restarts the run;
- `mcx stop <id>` marks the job stopped.

Each test fails against the current tree, where `codex:` is not a model prefix
fleet understands.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


def _write_rec(name, rec):
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"][name] = rec
        fleet.save_registry(data)

STUB_MCX = r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path

root = Path(os.environ["MCX_DIR"])
cmd = sys.argv[1] if len(sys.argv) > 1 else ""


def fail(msg):
    print(f"mcx: {msg}", file=sys.stderr)
    sys.exit(1)


if cmd == "spawn":
    model = sys.argv[sys.argv.index("-m") + 1] if "-m" in sys.argv else "default"
    prompt = sys.argv[-1]
    root.mkdir(parents=True, exist_ok=True)
    existing = [p for p in root.iterdir() if p.is_dir()]
    wid = f"{len(existing) + 1:08d}"
    job = root / wid
    job.mkdir()
    (job / "state").write_text("running", encoding="utf-8")
    (job / "model").write_text(model, encoding="utf-8")
    (job / "prompt").write_text(prompt, encoding="utf-8")
    (job / "log").write_text(f"log line one for {wid}\nlog line two\n",
                             encoding="utf-8")
    (job / "result").write_text(f"RESULT-{wid}\n", encoding="utf-8")
    print(wid)
elif cmd == "result":
    job = root / sys.argv[2]
    if not job.is_dir():
        fail(f"unknown worker: {sys.argv[2]}")
    state = (job / "state").read_text(encoding="utf-8").strip()
    if state in ("starting", "running"):
        print(f"mcx: {sys.argv[2]} is {state}", file=sys.stderr)
        sys.exit(2)
    if state == "done":
        print((job / "result").read_text(encoding="utf-8"), end="")
        sys.exit(0)
    fail(f"{sys.argv[2]} is {state}; see the job log")
elif cmd == "stop":
    job = root / sys.argv[2]
    if not job.is_dir():
        fail(f"unknown worker: {sys.argv[2]}")
    (job / "state").write_text("stopped", encoding="utf-8")
    print("stopped")
elif cmd == "steer":
    job = root / sys.argv[2]
    if not job.is_dir():
        fail(f"unknown worker: {sys.argv[2]}")
    prompt = sys.stdin.read() if sys.argv[3] == "-" else sys.argv[3]
    if not prompt.strip():
        fail("instructions must not be empty")
    (job / "prompt").write_text(prompt, encoding="utf-8")
    (job / "state").write_text("running", encoding="utf-8")
    print(sys.argv[2])
else:
    fail(f"unknown command: {cmd}")
"""


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME plus the stub mcx on PATH."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        json.dumps({"permissions": {"allow": []},
                    "hooks": {"Stop": [{"hooks": [{"type": "command",
                                                   "command": "true"}]}]}}),
        encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    stub = bin_dir / "mcx"
    stub.write_text(STUB_MCX, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("MCX_DIR", str(tmp_path / "must-not-be-used"))
    return tmp_path


def _job(worktree, mcx_id):
    return Path(worktree) / ".mcx" / mcx_id


def _set_state(worktree, mcx_id, state):
    (_job(worktree, mcx_id) / "state").write_text(state, encoding="utf-8")


def _spawn_args(worktree, **kw):
    base = dict(name="cx1", dir=str(worktree), task="do codex things",
                mode="accept", model="codex:gpt-5.6-luna",
                max_budget_usd=None, setting_sources=None,
                token_ceiling=None, category=None, nonce=None,
                force_band=False, context=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _spawn(codex_home, worktree=None, **kw):
    worktree = worktree or (codex_home / "lane")
    worktree.mkdir(exist_ok=True)
    rc = fleet.cmd_spawn(_spawn_args(worktree, **kw))
    assert rc == 0
    return worktree, fleet.load_registry()["workers"]["cx1"]


class TestCodexModelSlug:
    def test_parses_the_bare_model(self):
        assert fleet._codex_model_slug("codex:gpt-5.6-luna") == "gpt-5.6-luna"

    def test_non_codex_models_return_none(self):
        assert fleet._codex_model_slug("haiku") is None
        assert fleet._codex_model_slug("openrouter:z/y") is None
        assert fleet._codex_model_slug(None) is None
        assert fleet._codex_model_slug("") is None

    def test_substrate_routing_helpers(self):
        assert fleet._codex_substrate("codex:gpt-5.6-luna") == "codex"
        assert fleet._codex_substrate("haiku") is None
        # openrouter rows keep their slug substrate; plain models stay None.
        assert fleet._substrate_for_model("openrouter:z/y") == "openrouter/z/y"
        assert fleet._substrate_for_model("codex:gpt-5.6-luna") == "codex"
        assert fleet._substrate_for_model("haiku") is None
        assert fleet._is_codex_record({"substrate": "codex"})
        assert not fleet._is_codex_record({"substrate": "openrouter/z/y"})
        assert not fleet._is_codex_record({"substrate": None})


class TestSpawn:
    def test_spawn_records_a_codex_row(self, codex_home):
        worktree, rec = _spawn(codex_home)
        assert rec["substrate"] == "codex"
        assert rec["dispatch_kind"] == "mcx"
        assert rec["mcx_id"] == "00000001"
        assert rec["session_id"] is None
        assert rec["status"] == "working"
        assert rec["turns"] == 1
        # The bare model, not the codex: prefix, reaches mcx -m.
        job = _job(worktree, "00000001")
        assert (job / "model").read_text(encoding="utf-8") == "gpt-5.6-luna"
        # Task-file bootstrap: the tiny prompt points at the fleet task file.
        prompt = (job / "prompt").read_text(encoding="utf-8")
        assert "state/tasks/cx1.md" in prompt
        assert "do codex things" in fleet.task_file_path("cx1").read_text(
            encoding="utf-8")

    def test_spawn_runs_mcx_inside_the_lane_worktree(self, codex_home):
        worktree, rec = _spawn(codex_home)
        # mcx state lives in the worktree's .mcx (gitignored), never in the
        # caller's MCX_DIR (the fixture poisons it to prove the seam).
        assert _job(worktree, rec["mcx_id"]).is_dir()
        assert not Path(os.environ["MCX_DIR"]).exists()

    def test_spawn_without_mcx_refuses_and_rolls_back(self, codex_home,
                                                       monkeypatch):
        monkeypatch.setenv("PATH", "/nonexistent-bin")
        worktree = codex_home / "lane"
        worktree.mkdir()
        with pytest.raises(fleet.FleetCliError, match="mcx"):
            fleet.cmd_spawn(_spawn_args(worktree))
        assert "cx1" not in fleet.load_registry()["workers"]

    def test_mcx_failure_rolls_the_row_back(self, codex_home):
        def boom(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "mcx: codex down")
        worktree = codex_home / "lane"
        worktree.mkdir()
        with pytest.raises(fleet.FleetCliError, match="codex down"):
            fleet.cmd_spawn(_spawn_args(worktree), run=boom)
        assert "cx1" not in fleet.load_registry()["workers"]


class TestRecompute:
    def _rec(self, worktree, mcx_id="00000001", status="working"):
        return {"substrate": "codex", "mcx_id": mcx_id, "status": status,
                "cwd": str(worktree), "last_activity": fleet.now_iso(),
                "last_dispatch_at": fleet.now_iso()}

    def test_mcx_exit_codes_map_to_fleet_states(self, codex_home):
        worktree, rec = _spawn(codex_home)
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "working"
        _set_state(worktree, "00000001", "done")
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "idle"
        _set_state(worktree, "00000001", "stopped")
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "dead"

    def test_sticky_statuses_are_preserved(self, codex_home):
        worktree, rec = _spawn(codex_home)
        rec["status"] = "interrupted"
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == \
            "interrupted"

    def test_a_failed_probe_keeps_the_committed_status(self, codex_home):
        worktree, rec = _spawn(codex_home)
        # which() finds no mcx: the probe cannot run, so the committed status
        # stands (never assume dead on ambiguity).
        out = fleet.recompute_worker_codex("cx1", rec, which=lambda _: None)
        assert out["status"] == "working"

    def test_router_dispatches_by_substrate(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, "00000001", "done")
        out = fleet.recompute_worker("cx1", rec, [])
        assert out["status"] == "idle"


class TestStatus:
    def test_status_recomputes_codex_rows_without_the_roster(
            self, codex_home, monkeypatch, capsys):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "done")

        def forbidden_roster(**kwargs):
            raise AssertionError("a codex-only fleet must not fetch the roster")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", forbidden_roster)
        capsys.readouterr()  # drain the spawn banner

        rc = fleet.cmd_status(SimpleNamespace(name="cx1", json=True,
                                              stale_ok=False, all=False))
        assert rc == 0
        snap = json.loads(capsys.readouterr().out)
        row = next(w for w in snap["workers"] if w["name"] == "cx1")
        assert row["status"] == "idle"
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "idle"


class TestPeekAndResult:
    def test_peek_prints_the_mcx_log_tail(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        rc = fleet.cmd_peek(SimpleNamespace(name="cx1", lines=1))
        assert rc == 0
        out = capsys.readouterr().out
        assert f"-- cx1 ({rec['mcx_id']}) --" in out
        assert "log line two" in out
        assert "log line one" not in out

    def test_result_prints_the_mcx_result(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "done")
        rc = fleet.cmd_result(SimpleNamespace(name="cx1"))
        assert rc == 0
        assert f"RESULT-{rec['mcx_id']}" in capsys.readouterr().out

    def test_result_on_a_live_run_exits_1(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        rc = fleet.cmd_result(SimpleNamespace(name="cx1"))
        assert rc == 1
        assert "still running" in capsys.readouterr().err


class TestSend:
    def test_send_to_an_idle_lane_steers_and_says_it_restarts(
            self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "done")
        rec["status"] = "idle"
        _write_rec("cx1", rec)
        rc = fleet.cmd_send(SimpleNamespace(name="cx1", message="second turn",
                                            nonce=None, force_band=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "RESTART" in out.upper()
        job = _job(worktree, rec["mcx_id"])
        assert (job / "prompt").read_text(encoding="utf-8") == "second turn"
        after = fleet.load_registry()["workers"]["cx1"]
        assert after["status"] == "working"
        assert after["turns"] == rec["turns"] + 1

    def test_send_to_a_running_lane_refuses_without_queueing(self, codex_home):
        worktree, rec = _spawn(codex_home)  # stub state: running
        with pytest.raises(fleet.FleetCliError, match="RESTARTS"):
            fleet.cmd_send(SimpleNamespace(name="cx1", message="queue me",
                                           nonce=None, force_band=False))
        job = _job(worktree, rec["mcx_id"])
        assert (job / "prompt").read_text(encoding="utf-8") != "queue me"

    def test_send_to_a_dead_lane_marks_and_refuses(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "stopped")
        with pytest.raises(fleet.FleetCliError, match="dead"):
            fleet.cmd_send(SimpleNamespace(name="cx1", message="wake",
                                           nonce=None, force_band=False))
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "dead"


class TestInterruptAndKill:
    def test_interrupt_stops_the_run_and_marks_interrupted(self, codex_home,
                                                           capsys):
        worktree, rec = _spawn(codex_home)
        rc = fleet.cmd_interrupt(SimpleNamespace(name="cx1", nonce=None))
        assert rc == 0
        assert (_job(worktree, rec["mcx_id"]) / "state").read_text(
            encoding="utf-8") == "stopped"
        assert fleet.load_registry()["workers"]["cx1"]["status"] == \
            "interrupted"
        assert "mcx stop" in capsys.readouterr().out

    def test_interrupt_on_an_idle_lane_is_a_noop(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "done")
        rec["status"] = "idle"
        _write_rec("cx1", rec)
        rc = fleet.cmd_interrupt(SimpleNamespace(name="cx1", nonce=None))
        assert rc == 0
        assert "nothing to interrupt" in capsys.readouterr().out

    def test_kill_stops_and_marks_dead(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        rc = fleet.cmd_kill(SimpleNamespace(name="cx1", nonce=None, yes=True))
        assert rc == 0
        assert (_job(worktree, rec["mcx_id"]) / "state").read_text(
            encoding="utf-8") == "stopped"
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "dead"

    def test_kill_treats_an_unknown_mcx_job_as_gone(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        shutil.rmtree(_job(worktree, rec["mcx_id"]))
        rc = fleet.cmd_kill(SimpleNamespace(name="cx1", nonce=None, yes=True))
        assert rc == 0
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "dead"


class TestRespawn:
    def test_respawn_replaces_the_mcx_worker(self, codex_home, capsys):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "done")
        rc = fleet.cmd_respawn(SimpleNamespace(
            name="cx1", task=None, force=False, yes=True, nonce=None,
            force_band=False, max_budget_usd=None, setting_sources=None,
            token_ceiling=None))
        assert rc == 0
        after = fleet.load_registry()["workers"]["cx1"]
        assert after["mcx_id"] == "00000002"
        assert after["status"] == "working"
        assert after["model"] == "codex:gpt-5.6-luna"
        # The old job survives for wave accounting.
        assert _job(worktree, "00000001").is_dir()

    def test_respawn_refuses_a_live_run_without_force(self, codex_home):
        worktree, rec = _spawn(codex_home)  # stub state: running
        with pytest.raises(fleet.FleetCliError, match="--force"):
            fleet.cmd_respawn(SimpleNamespace(
                name="cx1", task=None, force=False, yes=True, nonce=None,
                force_band=False, max_budget_usd=None, setting_sources=None,
                token_ceiling=None))
        assert fleet.load_registry()["workers"]["cx1"]["mcx_id"] == \
            rec["mcx_id"]


class TestWaveAccounting:
    def _repo(self, tmp_path, worktree, mcx_id):
        repo = tmp_path / "repo"
        (repo / "state").mkdir(parents=True)
        registry = {"workers": {"cx1": {
            "cwd": str(worktree), "substrate": "codex", "mcx_id": mcx_id}}}
        (repo / "state" / "fleet.json").write_text(json.dumps(registry),
                                                   encoding="utf-8")
        return repo

    def test_record_substrate_reads_the_registry_row(self, tmp_path):
        worktree = tmp_path / "lane"
        worktree.mkdir()
        repo = self._repo(tmp_path, worktree, "00000001")
        # No .mcx marker needed once the row carries substrate + mcx_id.
        assert fleet._wave_record_substrate(repo, str(worktree)) == "codex"

    def test_codex_tokens_prefer_the_registry_row(self, tmp_path):
        # lanes=None reads the repo root itself as the worktree; the row's own
        # job carries usage and a foreign job in the same .mcx must NOT be
        # summed now that the registry names the lane's id.
        repo = tmp_path / "repo"
        mine = repo / ".mcx" / "00000001"
        foreign = repo / ".mcx" / "99999999"
        mine.mkdir(parents=True)
        foreign.mkdir(parents=True)
        (mine / "result").write_text(
            json.dumps({"usage": {"input_tokens": 5, "output_tokens": 7}}),
            encoding="utf-8")
        (foreign / "result").write_text(
            json.dumps({"usage": {"input_tokens": 1000,
                                  "output_tokens": 1000}}),
            encoding="utf-8")
        self._repo(tmp_path, repo, "00000001")
        assert fleet._wave_codex_tokens(repo) == "12"

    def test_codex_tokens_fall_back_to_the_glob_for_old_rows(self, tmp_path):
        repo = tmp_path / "repo"
        job = repo / ".mcx" / "00000001"
        job.mkdir(parents=True)
        (job / "result").write_text(
            json.dumps({"usage": {"input_tokens": 3, "output_tokens": 4}}),
            encoding="utf-8")
        (repo / "state").mkdir(parents=True)
        (repo / "state" / "fleet.json").write_text(
            json.dumps({"workers": {}}), encoding="utf-8")
        assert fleet._wave_codex_tokens(repo) == "7"

    def test_wave_close_stops_a_landed_codex_lane(self, codex_home):
        worktree, rec = _spawn(codex_home)
        stopped, errors = fleet._wave_stop_landed_sessions(["cx1"])
        assert stopped == ["cx1"]
        assert errors == []
        assert (_job(worktree, rec["mcx_id"]) / "state").read_text(
            encoding="utf-8") == "stopped"
