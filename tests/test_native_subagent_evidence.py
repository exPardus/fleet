"""Deterministic tier for the native subagent evidence readers.

The event shapes are the ones claude 2.1.331 emitted in the pin probes,
reduced to the fields the readers use.
"""
import json
import os

import pytest

from native_subagent_evidence import (
    child_runs, read_until, session_id, sidechain_usage, stop_parent,
    stream_events, subagent_files)

SID = "11111111-2222-4333-8444-555555555555"
AGENT = "a0123456789abcdef"


def _lines(*events):
    return "\n".join(json.dumps(event) for event in events) + "\nnot json\n"


def _started(run, tool_use, background=True):
    return {"type": "system", "subtype": "task_started", "session_id": SID,
            "task_id": AGENT, "run_id": run, "tool_use_id": tool_use,
            "is_backgrounded": background}


def _notified(run, status, total=10467):
    return {"type": "system", "subtype": "task_notification", "session_id": SID,
            "task_id": AGENT, "run_id": run, "tool_use_id": "toolu_x",
            "status": status, "summary": "CHILD-OK",
            "usage": {"total_tokens": total, "tool_uses": 0, "duration_ms": 9}}


def test_a_completed_child_has_one_terminal_run_with_usage():
    events = stream_events(_lines(
        {"type": "system", "subtype": "init", "session_id": SID},
        _started("run-1", "toolu_a"),
        {"type": "system", "subtype": "task_progress", "task_id": AGENT,
         "run_id": "run-1"},
        _notified("run-1", "completed")))
    assert session_id(events) == SID
    runs = child_runs(events)
    assert list(runs) == [AGENT]
    assert runs[AGENT][0]["tool_use_id"] == "toolu_a"
    assert runs[AGENT][0]["terminal"]["status"] == "completed"
    assert runs[AGENT][0]["terminal"]["usage"]["total_tokens"] == 10467


def test_a_continued_child_keeps_its_id_and_gets_a_new_run():
    runs = child_runs(stream_events(_lines(
        _started("run-1", "toolu_a"), _notified("run-1", "completed"),
        _started("run-2", "toolu_send"), _notified("run-2", "completed"))))
    assert [run["run_id"] for run in runs[AGENT]] == ["run-1", "run-2"]
    assert runs[AGENT][1]["tool_use_id"] == "toolu_send"


def test_a_started_child_without_a_notification_has_no_terminal_evidence():
    runs = child_runs(stream_events(_lines(_started("run-1", "toolu_a"))))
    assert runs[AGENT][0]["terminal"] is None


def test_a_resumed_session_reports_a_stopped_run_it_did_not_start():
    runs = child_runs(stream_events(_lines(_notified("run-old", "stopped"))))
    assert runs[AGENT][0]["terminal"]["status"] == "stopped"


def test_progress_is_never_terminal():
    progress = dict(_notified("run-1", "running"), subtype="task_notification")
    runs = child_runs(stream_events(_lines(_started("run-1", "t"), progress)))
    assert runs[AGENT][0]["terminal"] is None


def test_sidechain_usage_counts_each_message_once(tmp_path):
    message = {"id": "msg_1", "usage": {"input_tokens": 2, "output_tokens": 13}}
    text = _lines(
        {"type": "user", "agentId": AGENT, "message": {"content": "x"}},
        {"type": "assistant", "agentId": AGENT, "message": message},
        {"type": "assistant", "agentId": AGENT, "message": message},
        {"type": "assistant", "agentId": "other",
         "message": {"id": "msg_2", "usage": {"input_tokens": 50,
                                              "output_tokens": 50}}})
    assert sidechain_usage(text, AGENT) == {
        "input_tokens": 2, "output_tokens": 13, "messages": 1}


def test_subagent_files_are_found_beside_the_parent_session(tmp_path):
    directory = tmp_path / "projects" / "-tmp-proj" / SID / "subagents"
    directory.mkdir(parents=True)
    meta = directory / f"agent-{AGENT}.meta.json"
    meta.write_text(json.dumps({"toolUseId": "toolu_a", "finished": True}))
    (directory / f"agent-{AGENT}.jsonl").write_text("")
    found_meta, transcript = subagent_files(SID, AGENT, root=tmp_path)
    assert found_meta == meta and transcript.name == f"agent-{AGENT}.jsonl"
    assert subagent_files(SID, "aother", root=tmp_path) == (None, None)


def _silent_parent(script):
    import subprocess
    import sys
    return subprocess.Popen([sys.executable, "-c", script],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, start_new_session=True)


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_a_parent_that_holds_stdout_open_silently_cannot_hang_the_pin():
    import time
    parent = _silent_parent("import time; time.sleep(60)")
    started = time.monotonic()
    try:
        assert read_until(parent, [], lambda event: True, timeout=1.5) is False
        assert time.monotonic() - started < 10
    finally:
        stop_parent(parent)
    assert parent.poll() is not None


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_read_until_stops_at_the_first_matching_event():
    script = ("import json, sys, time\n"
              "print(json.dumps({'subtype': 'task_progress', "
              "'last_tool_name': 'Bash'}), flush=True)\n"
              "time.sleep(60)\n")
    parent = _silent_parent(script)
    seen = []
    try:
        assert read_until(parent, seen, lambda event: (
            event.get("last_tool_name") == "Bash"), timeout=30) is True
    finally:
        stop_parent(parent)
    assert seen == [{"subtype": "task_progress", "last_tool_name": "Bash"}]


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_stop_parent_escalates_when_sigterm_is_ignored():
    script = ("import signal, time\n"
              "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
              "print('ready', flush=True)\n"
              "time.sleep(120)\n")
    parent = _silent_parent(script)
    parent.stdout.readline()
    real_wait = parent.wait
    calls = []

    def short_wait(timeout=None):
        calls.append(timeout)
        return real_wait(min(timeout or 1, 1))

    parent.wait = short_wait
    stop_parent(parent)
    assert parent.poll() is not None and len(calls) == 2

