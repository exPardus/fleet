"""Read native Claude subagent evidence from a `claude -p` stream and disk.

The native subagent pin suite (tests/integration/test_native_subagent_pin.py)
and its deterministic unit tier (tests/test_native_subagent_evidence.py) share
these readers, so a live run exercises exactly the parsing the unit tier
proves. They answer the open questions of
docs/specs/native-subagent-lanes-proposal.md from observable evidence only:

- child identity: `agentId` (the stream's `task_id`) plus the dispatching
  `tool_use_id`; each run of that child has its own `run_id`;
- terminal evidence: a `task_notification` whose `status` is terminal, keyed
  by `(agentId, run_id)`;
- per-child usage: the notification's `usage` block, and per-message usage in
  the child's sidechain transcript;
- the durable record: `subagents/agent-<id>.meta.json` beside the parent
  transcript, which carries `finished: true` only after the child finished.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

TERMINAL_STATUSES = frozenset({"completed", "failed", "stopped", "killed"})


def stream_events(text: str) -> list[dict]:
    """Parse stream-json lines; ignore lines that are not JSON objects."""
    events = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def session_id(events: list[dict]) -> str | None:
    for event in events:
        if isinstance(event.get("session_id"), str):
            return event["session_id"]
    return None


def child_runs(events: list[dict]) -> dict[str, list[dict]]:
    """Map each agentId to its runs in start order.

    A run is {"run_id", "tool_use_id", "background", "terminal"}; terminal is
    the run's last terminal notification or None.
    """
    runs: dict[str, list[dict]] = {}
    by_run: dict[tuple[str, str], dict] = {}
    for event in events:
        if event.get("type") != "system":
            continue
        agent, run = event.get("task_id"), event.get("run_id")
        if not isinstance(agent, str):
            continue
        if event.get("subtype") == "task_started":
            record = {"run_id": run, "tool_use_id": event.get("tool_use_id"),
                      "background": event.get("is_backgrounded"),
                      "terminal": None}
            runs.setdefault(agent, []).append(record)
            by_run[(agent, run)] = record
        elif (event.get("subtype") == "task_notification"
              and event.get("status") in TERMINAL_STATUSES):
            record = by_run.get((agent, run))
            if record is None:
                # A resumed session reports a run it did not start.
                record = {"run_id": run, "tool_use_id": event.get("tool_use_id"),
                          "background": None, "terminal": None}
                runs.setdefault(agent, []).append(record)
                by_run[(agent, run)] = record
            record["terminal"] = {
                "status": event["status"], "summary": event.get("summary"),
                "usage": event.get("usage")}
    return runs


def config_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured) if configured else Path.home() / ".claude"


def subagent_files(sid: str, agent: str, root: Path | None = None
                   ) -> tuple[Path | None, Path | None]:
    """Return the child's (meta.json, transcript) beside the parent session."""
    base = (root or config_dir()) / "projects"
    metas = sorted(base.glob(f"*/{sid}/subagents/agent-{agent}.meta.json"))
    if len(metas) != 1:
        return None, None
    transcript = metas[0].with_name(f"agent-{agent}.jsonl")
    return metas[0], transcript if transcript.exists() else None


def sidechain_usage(transcript_text: str, agent: str) -> dict[str, int]:
    """Sum per-message usage of the child's assistant messages.

    Streaming writes one record per content block with the same message id,
    so each message id counts once.
    """
    seen: dict[str, dict] = {}
    for event in stream_events(transcript_text):
        message = event.get("message")
        if (event.get("type") != "assistant" or event.get("agentId") != agent
                or not isinstance(message, dict)):
            continue
        usage = message.get("usage")
        if isinstance(usage, dict):
            seen[str(message.get("id") or len(seen))] = usage
    total = {"input_tokens": 0, "output_tokens": 0, "messages": len(seen)}
    for usage in seen.values():
        for key in ("input_tokens", "output_tokens"):
            if isinstance(usage.get(key), int):
                total[key] += usage[key]
    return total


def read_until(process, seen, predicate, timeout):
    """Collect stream events until one matches; never block past `timeout`.

    A reader thread owns the pipe, so a parent that keeps stdout open but
    writes no line cannot hold the pin beyond its deadline.
    """
    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return False
        if line is None:
            return False
        events = stream_events(line)
        seen.extend(events)
        if any(predicate(event) for event in events):
            return True


def stop_parent(process):
    """SIGTERM the parent's process group; escalate if it does not exit."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(10)
