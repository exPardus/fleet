"""Shared scaffolding for the pi lane tests: scripted events and a fake pi."""
import json
import os
import stat
import sys
import time
from pathlib import Path

FLEET_PI_FAKE_SOURCE = Path(__file__).parent / "fixtures" / "fake_pi.py"
SLUG = "acme/tiny-1:free"
KEY = "test-key-not-real-0000"


def assistant(text="", *, stop="stop", error=None, model=SLUG, thinking=""):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    if text:
        content.append({"type": "text", "text": text})
    message = {"role": "assistant", "content": content, "stopReason": stop,
               "model": model, "usage": {"input": 10, "output": 2}}
    if error:
        message["errorMessage"] = error
    return {"type": "message_end", "message": message}


def ok_run(text="all done"):
    return {"events": [
        {"type": "session", "version": 3, "id": "s", "cwd": "."},
        {"type": "agent_start"},
        {"type": "tool_execution_start", "toolCallId": "c1", "toolName": "bash",
         "args": {"command": "ls"}},
        {"type": "tool_execution_end", "toolCallId": "c1", "toolName": "bash",
         "isError": False},
        assistant(text),
        {"type": "agent_end", "messages": [], "willRetry": False},
        {"type": "agent_settled", "aborted": False},
    ]}


def error_run(message="429 upstream rate-limited"):
    return {"events": [
        {"type": "agent_start"},
        assistant(stop="error", error=message),
        {"type": "agent_end", "messages": [], "willRetry": False},
    ], "exit": 0}  # --mode json exits 0 on provider failure


def install_fake_pi(tmp_path, monkeypatch, runs):
    """Write the scenario and a runnable fake pi; export FLEET_PI_* env."""
    scenario = tmp_path / "pi-scenario.json"
    scenario.write_text(json.dumps({"runs": runs}), encoding="utf-8")
    fake = tmp_path / "fake-pi"
    fake.write_text(f"#!{sys.executable}\n" + FLEET_PI_FAKE_SOURCE.read_text(
        encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "pi-calls.jsonl"
    monkeypatch.setenv("FLEET_PI_BIN", str(fake))
    monkeypatch.setenv("FLEET_PI_FAKE_SCENARIO", str(scenario))
    monkeypatch.setenv("FLEET_PI_FAKE_STATE", str(tmp_path / "pi-count"))
    monkeypatch.setenv("FLEET_PI_FAKE_LOG", str(log))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("FLEET_PI_RESTART_PAUSE_SECONDS", "0")
    monkeypatch.setenv("FLEET_PI_STALL_MINUTES", "2")
    monkeypatch.delenv("MCX_WORKER", raising=False)
    return log


def calls(log):
    if not Path(log).exists():
        return []
    return [json.loads(line) for line in
            Path(log).read_text(encoding="utf-8").splitlines() if line]


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the pi runner")


def job_state(job):
    try:
        return (Path(job) / "state").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def wait_terminal(job, timeout=20.0):
    return wait_for(lambda: job_state(job) in {"done", "failed", "stopped"}
                    and job_state(job), timeout)
