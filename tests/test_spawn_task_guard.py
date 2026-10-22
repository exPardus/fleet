"""`fleet spawn` never silently destroys an operator-authored task file.

Spawn writes its generated prompt to `state/tasks/<lane>.md`. A hand-written task
parked at that path was destroyed and the lane booted on a stub. The guard lives in
`refuse_foreign_spawn_inputs`, called once from `cmd_spawn` before any side effect,
so native Claude, native Codex and mcx Codex dispatch are all covered.
"""
import json
import types
from types import SimpleNamespace

import pytest

import fleet

SID = "11111111-1111-2222-3333-444455556666"
HAND = "# my hand-written task\nDo the real work.\n"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "fleet-home"
    (h / "state").mkdir(parents=True)
    (h / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (h / "logs").mkdir()
    (h / "mailbox").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    return h


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


def _args(project, **kw):
    base = dict(name="w1", dir=str(project), task="do things", mode="bypass",
                model=None, max_budget_usd=None, setting_sources=None,
                token_ceiling=None, category=None, context=None, yes=True,
                nonce=None, force_band=False, codex_adapter=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _hand_file(name="w1"):
    path = fleet.task_file_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HAND, encoding="utf-8")
    return path


def _boom(*_a, **_kw):
    raise AssertionError("a process was launched")


def _nothing_written(path):
    assert path.read_text(encoding="utf-8") == HAND
    assert fleet.load_registry()["workers"] == {}
    assert not fleet.brief_file_path("w1").exists()


@pytest.mark.parametrize("model,adapter", [
    (None, None),
    ("codex:gpt-5.6-luna", "native"),
    ("codex:gpt-5.6-luna", "mcx"),
])
def test_foreign_task_file_refused_for_every_dispatch(project, model, adapter):
    path = _hand_file()
    with pytest.raises(fleet.FleetCliError, match=r"w1-task\.md"):
        fleet.cmd_spawn(_args(project, model=model, codex_adapter=adapter),
                        run=_boom, which=lambda _n: "x")
    _nothing_written(path)


def test_own_prompt_header_is_not_foreign(project):
    path = fleet.task_file_path("w1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fleet._PREAMBLE_TEMPLATE.format(
        name="w1", cwd="x", journal_target="j") + "old", encoding="utf-8")
    fleet._spawn_task_arg("w1", "do things", project)


def test_header_of_another_lane_is_foreign(project):
    path = fleet.task_file_path("w1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("You are fleet worker `w2` in `x`.\n", encoding="utf-8")
    with pytest.raises(fleet.FleetCliError):
        fleet._spawn_task_arg("w1", "do things", project)


def test_single_token_naming_existing_file_refused(project):
    (project / "task.md").write_text("x", encoding="utf-8")
    with pytest.raises(fleet.FleetCliError, match=r"--task @task\.md"):
        fleet.cmd_spawn(_args(project, task="task.md"), run=_boom,
                        which=lambda _n: "x")
    assert fleet.load_registry()["workers"] == {}


def test_single_token_not_a_file_and_at_syntax_pass(project):
    fleet._spawn_task_arg("w1", "status", project)
    (project / "t.md").write_text("x", encoding="utf-8")
    fleet._spawn_task_arg("w1", f"@{project / 't.md'}", project)
    fleet._spawn_task_arg("w1", "t.md and more words", project)


def test_distinct_task_file_spawns_as_before(project, monkeypatch):
    hand = _hand_file("w1-task")
    entry = {"id": SID[:8], "sessionId": SID, "name": "fleet|w1|t",
             "cwd": "C:/proj", "startedAt": 1783986489446, "kind": "background",
             "state": "working", "status": "idle", "pid": 4321}
    answers = iter([(True, []), (True, [entry])])
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_k: next(answers, (True, [entry])))

    def run(argv, **kw):
        return types.SimpleNamespace(
            returncode=0, stdout=f"backgrounded \u00b7 {SID[:8]} \u00b7 x\n",
            stderr="")
    rc = fleet.cmd_spawn(_args(project, task=f"@{hand}"), run=run,
                         which=lambda _n: "claude", sleep=lambda s: None,
                         clock=lambda: 0.0)
    assert rc == 0
    assert hand.read_text(encoding="utf-8") == HAND
    assert fleet.task_file_path("w1").read_text(encoding="utf-8").startswith(
        "You are fleet worker `w1`")
    assert "w1" in fleet.load_registry()["workers"]
