"""`fleet respawn --model`: override the stored model for the new body.

Validated by spawn's rules before any process is touched, recorded in the
registry row, and never changes a row's substrate family.
"""
from types import SimpleNamespace

import pytest

import fleet

SID = "aaaabbbb-1111-2222-3333-444455556666"


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "fleet-home"
    (root / "state").mkdir(parents=True)
    (root / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(fleet, "FLEET_HOME", root)
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    return root


def _seed(tmp_path, model="claude-sonnet-5-5", **extra):
    cwd = tmp_path / "lane"
    cwd.mkdir(exist_ok=True)
    rec = fleet.new_worker_record(SID, str(cwd), "seeded task", "dontask",
                                  model=model, dispatch_kind="bg")
    rec["status"] = "idle"
    rec.update(extra)
    fleet.save_registry({"workers": {"w1": rec}})
    return rec


def _args(**kw):
    base = dict(name="w1", task=None, force=False, yes=True, nonce=None,
                force_band=False, max_budget_usd=None, setting_sources=None,
                token_ceiling=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _stub_native(monkeypatch):
    seen = []
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

    def dispatch(name, cwd, prompt, mode, **kw):
        seen.append(kw.get("model"))
        return {"session_id": "ccccdddd-1111-2222-3333-444455556666",
                "short_id": "ccccdddd"}

    monkeypatch.setattr(fleet, "dispatch_bg", dispatch)
    return seen


def test_override_is_dispatched_and_recorded(home, tmp_path, monkeypatch):
    _seed(tmp_path)
    seen = _stub_native(monkeypatch)
    assert fleet.cmd_respawn(_args(model="claude-opus-5-5")) == 0
    assert seen == ["claude-opus-5-5"]
    assert fleet.load_registry()["workers"]["w1"]["model"] == "claude-opus-5-5"


def test_omitted_model_keeps_the_stored_model(home, tmp_path, monkeypatch):
    _seed(tmp_path)
    seen = _stub_native(monkeypatch)
    assert fleet.cmd_respawn(_args(model=None)) == 0
    assert seen == ["claude-sonnet-5-5"]
    assert fleet.load_registry()["workers"]["w1"]["model"] == "claude-sonnet-5-5"


def test_blank_model_counts_as_omitted(home, tmp_path, monkeypatch):
    _seed(tmp_path)
    seen = _stub_native(monkeypatch)
    assert fleet.cmd_respawn(_args(model="  ")) == 0
    assert seen == ["claude-sonnet-5-5"]


@pytest.mark.parametrize("model", ["codex:gpt-5.6-luna", "pi:vendor/m:free"])
def test_invalid_model_refused_before_any_process(home, tmp_path, monkeypatch, model):
    before = _seed(tmp_path)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: pytest.fail("roster touched"))
    monkeypatch.setattr(fleet, "dispatch_bg",
                        lambda *a, **k: pytest.fail("dispatched"))
    with pytest.raises(fleet.FleetCliError, match="--model"):
        fleet.cmd_respawn(_args(model=model))
    assert fleet.load_registry()["workers"]["w1"]["model"] == before["model"]


def test_tier_policy_refusal_runs_before_any_process(home, tmp_path, monkeypatch):
    _seed(tmp_path)

    def refuse(role, model=None, policy=None):
        raise fleet.FleetCliError("tier policy refused")

    monkeypatch.setattr(fleet, "_enforce_tier_policy", refuse)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: pytest.fail("roster touched"))
    with pytest.raises(fleet.FleetCliError, match="tier policy refused"):
        fleet.cmd_respawn(_args(model="claude-opus-5-5"))


def test_codex_row_refuses_a_claude_model(home, tmp_path, monkeypatch):
    _seed(tmp_path, model="codex:gpt-5.6-luna", substrate="codex",
          dispatch_kind="mcx", mcx_id="00000001")
    monkeypatch.setattr(fleet, "_cmd_respawn_codex",
                        lambda *a, **k: pytest.fail("respawned"))
    with pytest.raises(fleet.FleetCliError, match="changes substrate"):
        fleet.cmd_respawn(_args(model="claude-opus-5-5"))


def test_codex_row_override_reaches_the_adapter(home, tmp_path, monkeypatch):
    _seed(tmp_path, model="codex:gpt-5.6-luna", substrate="codex",
          dispatch_kind="mcx", mcx_id="00000001")
    got = []
    monkeypatch.setattr(fleet, "_cmd_respawn_codex",
                        lambda args, before, **k: got.append(args.model) or 0)
    assert fleet.cmd_respawn(_args(model="codex:gpt-5.6-astra")) == 0
    assert got == ["codex:gpt-5.6-astra"]
