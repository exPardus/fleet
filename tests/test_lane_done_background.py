"""LANE-DONE waits for a lane's background tasks and queued wakes.

Reproduces the w402 sequence: a lane commits, leaves its suites running under
background Bash and Monitor tasks, and ends several turns as each notification
re-wakes it. Only the final Stop, with nothing left running, reports.
"""
import json
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
    fleet.write_incarnation({
        "state": "held", "session_id": PARENT_SID,
        "heartbeat_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return tmp_path


class Transcript:
    def __init__(self, path):
        self.path = path
        self.n = 0
        self.at = datetime.now(timezone.utc) - timedelta(minutes=30)
        path.write_text("", encoding="utf-8")

    def _add(self, entry):
        self.n += 1
        self.at += timedelta(seconds=10)
        entry.setdefault("timestamp", self.at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def assistant(self):
        self._add({"type": "assistant", "uuid": f"a-{self.n}",
                   "message": {"role": "assistant",
                               "content": [{"type": "text", "text": "ok"}]}})

    def result(self, tool_result, text=""):
        self._add({"type": "user", "toolUseResult": tool_result,
                   "message": {"role": "user", "content": [
                       {"type": "tool_result", "tool_use_id": f"t-{self.n}",
                        "content": text}]}})

    def bash_background(self, task):
        self.result({"stdout": "", "backgroundTaskId": task},
                    f"Command running in background with ID: {task}.")

    def monitor(self, task):
        self.result({"taskId": task, "timeoutMs": 900000, "persistent": False},
                    f"Monitor started (task {task}, expires in 15m).")

    def notification(self, task, body, *, queued=True):
        text = (f"<task-notification>\n<task-id>{task}</task-id>\n{body}\n"
                f"</task-notification>")
        if queued:
            self._add({"type": "queue-operation", "operation": "enqueue",
                       "content": text})
            self._add({"type": "queue-operation", "operation": "dequeue"})
        self._add({"type": "user", "origin": {"kind": "task-notification"},
                   "message": {"role": "user", "content": text}})


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    t = Transcript(tmp_path / f"{LANE_SID}.jsonl")
    monkeypatch.setattr(fleet, "find_transcript_path",
                        lambda name, sid: t.path if sid == LANE_SID else None)
    return t


@pytest.fixture
def sends(monkeypatch):
    out = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: out.append((name, message)) or 0)
    return out


def _git(sha="05d08e3a"):
    def run(argv, **kw):
        if "status" in argv:
            return SimpleNamespace(returncode=0, stdout="")
        return SimpleNamespace(returncode=0, stdout=f"{sha}\n")
    return run


def _stop():
    return fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_git())


def test_w402_sequence_reports_only_the_final_stop(home, transcript, sends):
    transcript.bash_background("bsuite")
    transcript.monitor("bwatch1")
    transcript.assistant()
    assert not _stop()
    transcript.notification("bwatch1", "<event>[Monitor expired after 15m]</event>")
    transcript.monitor("bwatch2")
    transcript.assistant()
    assert not _stop()
    transcript.notification("bsuite", "<status>completed</status>")
    transcript.assistant()
    assert not _stop()
    transcript.notification("bwatch2", "<event>[Monitor expired after 15m]</event>")
    transcript.assistant()
    assert _stop()
    transcript.assistant()
    assert not _stop()
    assert sends == [(PARENT, "LANE-DONE lane idle 05d08e3a")]
    assert "lane_done_pending" not in fleet.load_registry()["workers"]["lane"]


def test_monitor_event_without_end_keeps_the_lane_working(home, transcript, sends):
    transcript.monitor("bwatch")
    transcript.notification("bwatch", "<event>12 passed</event>")
    transcript.assistant()
    assert not _stop()
    transcript.notification("bwatch", "<status>completed</status>\n"
                                      "<summary>Monitor stream ended</summary>")
    transcript.assistant()
    assert _stop()


def test_task_stop_and_async_agent(home, transcript, sends):
    transcript.bash_background("bslow")
    transcript.result({"agentId": "agent1", "isAsync": True,
                       "status": "async_launched"})
    transcript.result({"message": "Successfully stopped task: bslow",
                       "task_id": "bslow", "task_type": "local_bash"})
    transcript.assistant()
    assert fleet._lane_background_live("lane", LANE_SID) == ["agent1"]
    assert not _stop()
    transcript.notification("agent1", "<status>completed</status>")
    transcript.assistant()
    assert _stop()


def test_queued_wake_suppresses(home, transcript, sends):
    transcript.assistant()
    transcript._add({"type": "queue-operation", "operation": "enqueue",
                     "content": "<task-notification><task-id>bx</task-id>"
                                "<status>completed</status></task-notification>"})
    assert fleet._lane_background_live("lane", LANE_SID) == ["queued-wake"]
    assert not _stop()
    assert sends == []


def _attached_notice(transcript, task, body):
    transcript._add({"type": "attachment", "attachment": {
        "type": "queued_command",
        "prompt": f"<task-notification>\n<task-id>{task}</task-id>\n{body}\n"
                  f"</task-notification>"}})


def test_queued_command_attachment_completes_task(home, transcript, sends):
    transcript.monitor("bwatch")
    transcript.assistant()
    assert fleet._lane_background_live("lane", LANE_SID) == ["bwatch"]
    _attached_notice(transcript, "bwatch", "<status>completed</status>")
    transcript.assistant()
    assert fleet._lane_background_live("lane", LANE_SID) == []
    assert _stop()


def test_queued_command_attachment_content_list(home, transcript, sends):
    transcript.bash_background("bsuite")
    transcript._add({"type": "attachment", "attachment": {
        "type": "queued_command", "content": [
            {"type": "text", "text": "<task-notification><task-id>bsuite</task-id>"
                                     "<status>completed</status></task-notification>"}]}})
    assert fleet._lane_background_live("lane", LANE_SID) == []


def test_quoted_marker_text_is_not_a_task(home, transcript, sends):
    transcript.result({"stdout": "Monitor started (task bfake, expires in 15m)"},
                      "Command running in background with ID: bfake2.")
    transcript.assistant()
    assert _stop()


def test_task_older_than_cap_no_longer_blocks(home, transcript, sends, monkeypatch):
    transcript.bash_background("bhung")
    transcript.assistant()
    assert not _stop()
    monkeypatch.setattr(fleet, "LANE_DONE_BACKGROUND_MAX_SECONDS", 1)
    assert _stop()


def test_new_turn_between_emit_and_send_is_not_reported(home, transcript, sends):
    transcript.assistant()

    def git(argv, **kw):
        if "rev-parse" in argv:
            transcript.monitor("blate")
            transcript.assistant()
        return _git()(argv, **kw)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=git)
    assert sends == []
    assert "lane_done_pending" not in fleet.load_registry()["workers"]["lane"]


def test_stop_bridge_honours_background(home, transcript, sends):
    transcript.bash_background("bsuite")
    transcript.assistant()
    fleet.cmd_lane_done(SimpleNamespace(sid=LANE_SID))
    assert sends == []
    transcript.notification("bsuite", "<status>completed</status>")
    transcript.assistant()
    fleet.cmd_lane_done(SimpleNamespace(sid=LANE_SID))
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def _roster(pid=True):
    entry = {"sessionId": LANE_SID, "status": "idle", "state": "done"}
    if pid:
        entry["pid"] = 4242
    return lambda: (True, [entry])


def test_sweep_waits_for_live_body_background(home, transcript, sends, monkeypatch):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    transcript.bash_background("bsuite")
    transcript.assistant()
    assert fleet.sweep_lane_done(_roster(), run=_git()) == []
    assert fleet.sweep_lane_done(_roster(pid=False), run=_git()) == ["lane"]
    assert sends == [(PARENT, "LANE-DONE lane idle 05d08e3a")]
