"""Targeted tests for the interface's two-live-body supervisor guard."""

import json
from types import SimpleNamespace

import pytest

import fleet


SID = "sid-current"
RETIRED = "sid-retired"
BODY = "sup|inc-guard|boot"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for name in ("state", "supervisor", "mailbox", "logs"):
        (tmp_path / name).mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# active\n")
    (tmp_path / "state" / "worker-settings.json").write_text("{}")
    record = fleet.new_worker_record(SID, str(tmp_path), "standing", "bypass",
                                     dispatch_kind="bg")
    record["retired_sids"] = [RETIRED]
    fleet.save_registry({"workers": {BODY: record}})
    claim = {"incarnation_id": "inc-guard", "session_id": SID,
             "claimed_via": "handoff", "heartbeat_at": "2026-09-09T00:00:00Z"}
    fleet.write_incarnation(claim)
    return tmp_path


def snapshot(age=4000, state="held", **extra):
    sup = {"goals_active": True, "state": state,
           "heartbeat_age_seconds": age}
    sup.update(extra)
    return {"ok": True, "workers": [], "supervisor": sup}


def roster(*rows):
    return lambda: (True, list(rows))


def row(sid, *, status="idle", pid=42, name=BODY, state="working"):
    return {"sessionId": sid, "status": status, "pid": pid,
            "name": name, "state": state}


def run_guard(monkeypatch, snap, rows=(), **args):
    monkeypatch.setattr(fleet, "status_snapshot", lambda: snap)
    return fleet.cmd_sup_guard(
        SimpleNamespace(do=False, json=False, **args),
        roster_fn=roster(*rows),
    )


def test_live_idle_body_under_retired_sid_is_wake_not_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(RETIRED)])
    assert capsys.readouterr().out == f"WAKE {BODY}\n"


def test_fresh_live_idle_body_is_page_not_wake(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(age=10), [row(RETIRED)])
    assert capsys.readouterr().out == (
        "PAGE fresh heartbeat with live idle body\n")


def test_stale_claim_with_no_live_union_sid_is_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot())
    assert capsys.readouterr().out == "DISPATCH\n"


def test_unreadable_registry_is_page_not_dispatch(home, monkeypatch, capsys):
    broken = {"ok": False, "reason": "quarantined", "workers": [],
              "supervisor": {"goals_active": True, "state": "held",
                              "heartbeat_age_seconds": 4000}}
    run_guard(monkeypatch, broken)
    assert capsys.readouterr().out == (
        "PAGE registry unavailable: quarantined\n")


def test_live_busy_body_is_page_not_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(SID, status="busy")])
    assert capsys.readouterr().out == "PAGE roster says busy\n"


def test_pidless_listed_body_can_dispatch_when_stale(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(SID, pid=None)])
    assert capsys.readouterr().out == "DISPATCH\n"


def test_fresh_claim_with_missing_body_pages(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(age=10))
    assert capsys.readouterr().out == (
        "PAGE fresh heartbeat but body is not roster-live\n")


def test_handshake_always_pages(home, monkeypatch, capsys):
    (home / "supervisor" / "HANDSHAKE").write_text(
        json.dumps({"incarnation_id": "inc-guard"}))
    run_guard(monkeypatch, snapshot(), [row(RETIRED)])
    assert capsys.readouterr().out == "PAGE handoff in flight\n"


def test_no_claim_with_live_supervisor_body_pages(home, monkeypatch, capsys):
    fleet.incarnation_path().unlink()
    run_guard(monkeypatch, snapshot(state="none", age=None),
              [row(RETIRED)])
    assert capsys.readouterr().out == (
        "PAGE live supervisor body without a safe claim\n")


def test_do_reverifies_and_executes_only_the_second_verdict(
        home, monkeypatch, capsys):
    calls = []
    dispatch_observation = {
        "state": "held", "claim": {"claimed_via": "handoff"},
        "claim_sids": [SID], "roster_ok": True, "roster_reason": None,
        "live_rows": {}, "live_body_rows": [], "handshake_exists": False,
        "handshake": None, "pending": False, "body_name": BODY,
        "heartbeat_age_seconds": 4000, "goals_active": True,
    }
    observations = iter((dispatch_observation, dispatch_observation))
    monkeypatch.setattr(fleet, "_sup_guard_observe",
                        lambda **_: next(observations))
    monkeypatch.setattr(fleet, "cmd_sup_spawn",
                        lambda args: calls.append(args) or 0)
    rc = fleet.cmd_sup_guard(SimpleNamespace(do=True, json=False))
    assert rc == 0
    assert len(calls) == 1
    assert calls[0].task == "@supervisor/briefs/server-standing.md"
    assert calls[0].setting_sources == "project,local"
    assert capsys.readouterr().out == "DISPATCH\n"


def test_do_page_has_no_action(home, monkeypatch, capsys):
    calls = []
    observation = {
        "state": "held", "claim": {"claimed_via": "seize"},
        "claim_sids": [SID], "roster_ok": True, "roster_reason": None,
        "live_rows": {}, "live_body_rows": [], "handshake_exists": False,
        "handshake": None, "pending": False, "body_name": BODY,
        "heartbeat_age_seconds": 4000, "goals_active": True,
    }
    monkeypatch.setattr(fleet, "_sup_guard_observe", lambda **_: observation)
    monkeypatch.setattr(fleet, "cmd_sup_spawn",
                        lambda args: calls.append(args) or 0)
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=False)) == 0
    assert not calls
    assert capsys.readouterr().out == "PAGE claim seized\n"
