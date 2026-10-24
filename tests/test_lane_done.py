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


def _git_runner(head, dirty=False):
    def run(argv, **kw):
        if "status" in argv:
            return SimpleNamespace(returncode=0, stdout=" M f.py\n" if dirty else "")
        return SimpleNamespace(returncode=0, stdout=f"{head['sha']}\n")
    return run


def test_idle_completion_sends_once(home, monkeypatch):
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append((name, message)) or 0)
    git = _git_runner({"sha": "abc1234"})
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


def test_status_change_during_send_clears_pending_marker(home, monkeypatch):
    """A concurrent turn change must not strand the old pending marker."""
    before = fleet.load_registry()["workers"]["lane"]
    expected_dispatch = before.get("last_dispatch_at")

    def send(name, message):
        data = fleet.load_registry()
        data["workers"]["lane"]["status"] = "idle"
        fleet.save_registry(data)
        return 0

    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    assert fleet.notify_lane_done(
        "lane", "idle", expected_sid=LANE_SID,
        expected_status="working", expected_last_dispatch_at=expected_dispatch,
        run=lambda *a, **k: SimpleNamespace(returncode=1, stdout=""),
    )
    rec = fleet.load_registry()["workers"]["lane"]
    assert "lane_done_pending" not in rec
    assert "lane_done_notified" not in rec


@pytest.mark.parametrize("change", ["absent", "dead", "released", "mismatch"])
def test_no_delivery_without_current_live_claim(home, monkeypatch, change):
    data = fleet.load_registry()
    claim = fleet.read_incarnation()
    if change == "absent":
        data["workers"]["lane"]["spawned_by"] = None
    elif change == "dead":
        data["workers"][PARENT]["status"] = "dead"
    elif change == "released":
        claim["state"] = "released"
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


def test_busy_parent_queue_collapses_repeat_stops(home, monkeypatch):
    """A lane re-woken by background tasks ends many turns; each Stop mints a
    new assistant uuid. The busy parent's unread mailbox must hold one copy."""
    data = fleet.load_registry()
    data["workers"][PARENT]["status"] = "working"
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (True, [{"sessionId": PARENT_SID,
                                              "status": "working", "state": "working",
                                              "pid": 123}]))
    monkeypatch.setattr(fleet, "_wake_supervisor_native", lambda *a, **k: None)
    tail = []
    monkeypatch.setattr(fleet, "_last_assistant_uuid", lambda n, s: tail[-1])
    git = _git_runner({"sha": "abc1234"})
    for i in range(1, 4):
        tail.append(f"uuid-{i}")
        fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    mail = (home / "mailbox" / f"{PARENT_SID}.md").read_text()
    assert mail.count("LANE-DONE lane idle abc1234") == 1
    lane = fleet.load_registry()["workers"]["lane"]
    assert lane["lane_done_shas"] == [f"{lane.get('last_dispatch_at') or ''}@abc1234"]


def test_same_sha_delivers_once_across_new_turns(home, monkeypatch):
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append(message) or 0)
    tail = []
    monkeypatch.setattr(fleet, "_last_assistant_uuid", lambda n, s: tail[-1])
    git = _git_runner({"sha": "abc1234"})
    for i in range(4):
        tail.append(f"uuid-{i}")
        fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert sends == ["LANE-DONE lane idle abc1234"]


def test_dirty_lane_sends_nothing_then_clean_fires(home, monkeypatch):
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append(message) or 0)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                                      run=_git_runner({"sha": "abc1234"}, dirty=True))
    assert sends == []
    assert "lane_done_pending" not in fleet.load_registry()["workers"]["lane"]
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                                  run=_git_runner({"sha": "abc1234"}))
    assert sends == ["LANE-DONE lane idle abc1234"]


def test_new_sha_fires_once_more(home, monkeypatch):
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append(message) or 0)
    tail = []
    monkeypatch.setattr(fleet, "_last_assistant_uuid", lambda n, s: tail[-1])
    head = {"sha": "aaaa111"}
    for sha in ("aaaa111", "aaaa111", "bbbb222", "bbbb222", "aaaa111"):
        head["sha"] = sha
        tail.append(f"uuid-{len(tail)}")
        fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                               run=_git_runner(head))
    assert sends == ["LANE-DONE lane idle aaaa111", "LANE-DONE lane idle bbbb222"]


def test_redispatch_on_same_sha_fires_again(home, monkeypatch):
    """A review lane commits nothing: its next dispatch ends on the same sha
    and must still report."""
    sends = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: sends.append(message) or 0)
    tail = []
    monkeypatch.setattr(fleet, "_last_assistant_uuid", lambda n, s: tail[-1])
    git = _git_runner({"sha": "abc1234"})
    for dispatch in ("2026-10-24T00:00:00Z", "2026-10-24T01:00:00Z"):
        data = fleet.load_registry()
        data["workers"]["lane"]["last_dispatch_at"] = dispatch
        fleet.save_registry(data)
        for _ in range(2):
            tail.append(f"uuid-{len(tail)}")
            fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert sends == ["LANE-DONE lane idle abc1234"] * 2
