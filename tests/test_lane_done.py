"""Completion mail is claim-bound, deduplicated, and Stop-safe."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


PARENT = "sup|inc-test|boot"
PARENT_SID = "parent-sid"
LANE_SID = "lane-sid"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "supervisor").mkdir()
    parent = fleet.new_worker_record(PARENT_SID, str(tmp_path), "supervise", "bypass")
    parent["status"] = "idle"
    lane = fleet.new_worker_record(LANE_SID, str(tmp_path), "work", "bypass",
                                   spawned_by=PARENT_SID)
    lane["status"] = "working"
    fleet.save_registry({"workers": {PARENT: parent, "lane": lane}})
    claim = {"state": "held", "session_id": PARENT_SID,
             "heartbeat_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    fleet.write_incarnation(claim)
    return tmp_path


def test_idle_completion_sends_once(home, monkeypatch):
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append((name, message)) or 0)
    git = lambda *a, **k: SimpleNamespace(returncode=0, stdout="abc1234\n")
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert sends == [(PARENT, "LANE-DONE lane idle abc1234")]


def test_busy_parent_gets_mail_without_wake(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][PARENT]["status"] = "working"
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (True, [{"sessionId": PARENT_SID,
                                              "status": "working", "state": "working",
                                              "pid": 123}]))
    fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                           run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert "LANE-DONE lane idle none" in (home / "mailbox" / f"{PARENT_SID}.md").read_text()


@pytest.mark.parametrize("change", ["absent", "dead", "released", "stale", "mismatch"])
def test_no_delivery_without_current_live_claim(home, monkeypatch, change):
    data = fleet.load_registry()
    claim = fleet.read_incarnation()
    if change == "absent":
        data["workers"]["lane"]["spawned_by"] = None
    elif change == "dead":
        data["workers"][PARENT]["status"] = "dead"
    elif change == "released":
        claim["state"] = "released"
    elif change == "stale":
        claim["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        claim["session_id"] = "other-sid"
    fleet.save_registry(data)
    fleet.write_incarnation(claim)
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda *a: sends.append(a) or 0)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID)
    assert sends == []


def test_stop_bridge_reports_failed_delivery(home, monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "bin" / "hooks" / "stop_mailbox.py"
    spec = importlib.util.spec_from_file_location("stop_lane_done_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_fleet_home", lambda: str(home))
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="failed"))
    with pytest.raises(RuntimeError):
        mod._notify_lane_done(LANE_SID)


def test_codex_observed_transition_notifies_once(home, monkeypatch, capsys):
    data = fleet.load_registry()
    data["workers"]["lane"].update({"substrate": "codex", "mcx_id": "job-1"})
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "recompute_worker",
                        lambda n, rec, roster: {**rec, "status": "idle"})
    notified = []
    monkeypatch.setattr(fleet, "notify_lane_done",
                        lambda *a, **k: notified.append((a, k)))
    args = SimpleNamespace(name="lane", all=False, stale_ok=False, json=True)
    assert fleet.cmd_status(args) == 0
    assert fleet.cmd_status(args) == 0
    assert notified == [(("lane", "idle"), {"expected_sid": LANE_SID})]
    assert "LANE-DONE" not in capsys.readouterr().out
