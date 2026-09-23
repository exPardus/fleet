"""Completion mail is claim-bound, deduplicated, and Stop-safe."""
import io
import json
import runpy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


PARENT = "sup|inc-test|boot"
PARENT_SID = "parent-sid"
LANE_SID = "lane-sid"
STOP_HOOK = Path(__file__).resolve().parents[1] / "bin" / "hooks" / "stop_mailbox.py"


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
    wakes = []
    monkeypatch.setattr(fleet, "_wake_supervisor_native",
                        lambda *a, **k: wakes.append((a, k)))
    fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                           run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""))
    assert "LANE-DONE lane idle none" in (home / "mailbox" / f"{PARENT_SID}.md").read_text()
    assert wakes == []
    assert fleet.load_registry()["workers"][PARENT]["status"] == "working"


@pytest.mark.parametrize("source", ["successor", "own-stop"])
def test_supervisor_stop_never_sends_to_claim_holder(home, monkeypatch, source):
    data = fleet.load_registry()
    if source == "successor":
        name, sid = "sup|inc-next|successor", "successor-sid"
        rec = fleet.new_worker_record(sid, str(home), "succeed", "bypass",
                                      spawned_by=PARENT_SID)
        data["workers"][name] = rec
    else:
        name, sid = PARENT, PARENT_SID
        data["workers"][name]["spawned_by"] = PARENT_SID
    fleet.save_registry(data)
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda *a: sends.append(a) or 0)
    assert not fleet.notify_lane_done(name, "idle", expected_sid=sid)
    assert fleet.cmd_lane_done(SimpleNamespace(sid=sid)) == 0
    assert sends == []
    assert not (home / "mailbox" / f"{PARENT_SID}.md").exists()


def test_failed_send_clears_marker_and_next_observation_retries(home, monkeypatch):
    calls = []

    def send(name, message):
        calls.append((name, message))
        if len(calls) == 1:
            raise fleet.FleetCliError("injected send failure")
        return 0

    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    git = lambda *a, **k: SimpleNamespace(returncode=1, stdout="")
    with pytest.raises(fleet.FleetCliError, match="injected"):
        fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert "lane_done_notified" not in fleet.load_registry()["workers"]["lane"]
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert calls == [(PARENT, "LANE-DONE lane idle none")] * 2


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


def test_stop_bridge_failure_exits_zero_and_logs_one_line(home, monkeypatch):
    calls = []

    def failed_bridge(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1, stderr="failed")

    monkeypatch.setattr(subprocess, "run", failed_bridge)
    monkeypatch.setenv("FLEET_HOME", str(home))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": LANE_SID})))
    monkeypatch.setattr(sys, "argv", [str(STOP_HOOK)])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(STOP_HOOK), run_name="__main__")
    assert stopped.value.code == 0
    assert len(calls) == 1 and calls[0][1]["timeout"] == 90
    lines = (home / "state" / "hook-errors.log").read_text().splitlines()
    assert len(lines) == 1
    assert "lane-done exited 1" in lines[0]


@pytest.mark.parametrize("change", ["no-spawner", "wrong-holder"])
def test_stop_precheck_skips_subprocess(home, monkeypatch, change):
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_lane_done_test", STOP_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    data = fleet.load_registry()
    if change == "no-spawner":
        data["workers"]["lane"]["spawned_by"] = None
        fleet.save_registry(data)
    else:
        claim = fleet.read_incarnation()
        claim["session_id"] = "other-sid"
        fleet.write_incarnation(claim)
    monkeypatch.setattr(mod, "_fleet_home", lambda: str(home))
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda *a, **k: pytest.fail("bridge subprocess started"))
    mod._notify_lane_done(LANE_SID)


def test_codex_observed_transition_notifies_once(home, monkeypatch, capsys):
    data = fleet.load_registry()
    data["workers"]["lane"].update({"substrate": "codex", "dispatch_kind": "mcx",
                                      "session_id": None, "mcx_id": "job-1"})
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_mcx_probe", lambda *a, **k: "idle")
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append((name, message)) or 0)
    args = SimpleNamespace(name="lane", all=False, stale_ok=False, json=True)
    assert fleet.cmd_status(args) == 0
    assert fleet.cmd_status(args) == 0
    assert sends == [(PARENT, "LANE-DONE lane idle none")]
    assert fleet.load_registry()["workers"]["lane"]["lane_done_notified"]
    assert "LANE-DONE" not in capsys.readouterr().out


def test_codex_idle_observation_retries_failed_send(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"]["lane"].update({"substrate": "codex", "dispatch_kind": "mcx",
                                      "session_id": None, "mcx_id": "job-1"})
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_mcx_probe", lambda *a, **k: "idle")
    calls = []

    def send(name, message):
        calls.append((name, message))
        if len(calls) == 1:
            raise fleet.FleetCliError("injected")
        return 0

    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    args = SimpleNamespace(name="lane", all=False, stale_ok=False, json=True)
    assert fleet.cmd_status(args) == 0  # delivery failed, observation still succeeds
    assert "lane_done_notified" not in fleet.load_registry()["workers"]["lane"]
    assert fleet.cmd_status(args) == 0  # same idle state retries
    assert fleet.cmd_status(args) == 0  # delivered marker suppresses a duplicate
    assert calls == [(PARENT, "LANE-DONE lane idle none")] * 2
