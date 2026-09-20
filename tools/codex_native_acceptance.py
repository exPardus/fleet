#!/usr/bin/env python3
"""Bounded fake and opt-in live acceptance for Fleet's public Codex adapter."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "bin"
SCHEMA_MANIFEST = (
    REPO / "tests" / "fixtures" / "codex_app_server" / "0.155.1"
    / "manifest.json")

FAKE_CASES = {
    "supervisor_boot_claim": [
        "tests/test_codex_supervisor.py::test_explicit_native_sup_spawn_binds_genuine_holder_and_boot_turn",
    ],
    "idle_wake": [
        "tests/test_codex_supervisor.py::test_native_guard_wakes_stale_idle_thread_without_creating_second_body",
    ],
    "active_steer": [
        "tests/test_codex_supervisor.py::test_native_send_steers_only_the_claimed_active_turn",
    ],
    "result": [
        "tests/test_codex_supervisor.py::test_native_result_distinguishes_active_completed_and_failed",
    ],
    "interrupt": [
        "tests/test_codex_supervisor.py::test_native_reconcile_interrupts_and_retires_exact_handoff_predecessor",
        "tests/test_codex_supervisor.py::test_native_predecessor_interrupt_ambiguity_never_replays",
    ],
    "checkpoint_handoff": [
        "tests/test_codex_supervisor.py::test_native_checkpoint_commits_only_against_exact_observed_holder",
        "tests/test_codex_supervisor.py::test_native_handoff_transfers_before_start_and_stales_predecessor",
    ],
    "restart_adoption": [
        "tests/test_codex_supervisor.py::test_native_restart_commits_original_journal_before_new_generation_resume",
    ],
    "stale_predecessor_denial": [
        "tests/test_codex_supervisor.py::test_stale_native_predecessor_cannot_wake_or_steer",
    ],
}

BLOCKED_CASES = {
    "interface_registration": (
        "No native interface-register route can bind genuine Codex caller/source "
        "authorization; UUID membership alone is intentionally insufficient."),
    "usage": (
        "Native supervisor result observation does not yet persist public per-turn "
        "token totals."),
}


def _manifest() -> dict:
    return json.loads(SCHEMA_MANIFEST.read_text(encoding="utf-8"))


def _emit(report: dict, output: Path | None) -> int:
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.write_text(encoded, encoding="utf-8")
    sys.stdout.write(encoded)
    return 0 if report["overall"] in {"PASS", "SKIP"} else 2


def run_fake(python: str) -> dict:
    manifest = _manifest()
    with tempfile.TemporaryDirectory(prefix="fleet-codex-acceptance-") as raw:
        stub_dir = Path(raw) / "bin"
        stub_dir.mkdir()
        marker = Path(raw) / "provider-called"
        for executable in ("claude", "mcx", "codex"):
            path = stub_dir / executable
            path.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' {executable!r} >> {str(marker)!r}\n"
                "exit 97\n", encoding="utf-8")
            path.chmod(0o700)
        env = dict(os.environ)
        env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
        env.pop("FLEET_CODEX_LIVE", None)
        nodes = [node for group in FAKE_CASES.values() for node in group]
        completed = subprocess.run(
            [python, "-m", "pytest", "-q", *nodes], cwd=REPO, env=env,
            stdin=subprocess.DEVNULL, text=True, capture_output=True,
            timeout=60, check=False)
        provider_called = marker.exists()
    passed = completed.returncode == 0 and not provider_called
    rows = {
        name: {
            "status": "PASS" if passed else "FAIL",
            "probes": probes,
        }
        for name, probes in FAKE_CASES.items()
    }
    rows.update({
        name: {"status": "BLOCKED", "reason": reason}
        for name, reason in BLOCKED_CASES.items()
    })
    return {
        "mode": "fake",
        "overall": "BLOCKED" if passed else "FAIL",
        "provider_processes_started": provider_called,
        "protocol": {
            "codex_version": manifest["codex_version"],
            "schema_sha256": manifest["schema_sha256"],
        },
        "pytest": {
            "returncode": completed.returncode,
            "summary": completed.stdout.strip().splitlines()[-1]
            if completed.stdout.strip() else completed.stderr.strip()[-300:],
        },
        "rows": rows,
    }


def _rpc(client, operation_id: str, method: str, params: dict,
         *, mutation: bool = False, timeout: float = 30):
    operation = {
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": method, "params": params},
    }
    observation = client.call(operation, timeout=timeout)
    if mutation:
        client.commit(operation_id)
    return observation.result


def _quota_blocked(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            folded = key.lower().replace("_", "")
            if folded in {"limitreached", "exhausted"} and item is True:
                return True
            if folded in {"allowed", "canuse"} and item is False:
                return True
            if folded in {"usedpercent", "percentused"} \
                    and isinstance(item, (int, float)) and item >= 100:
                return True
            if _quota_blocked(item):
                return True
    elif isinstance(value, list):
        return any(_quota_blocked(item) for item in value)
    return False


def _token_usage(value) -> dict:
    found = {}

    def visit(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                folded = key.lower().replace("_", "")
                if (folded in {"inputtokens", "outputtokens", "totaltokens",
                               "cachedinputtokens", "reasoningoutputtokens"}
                        and isinstance(nested, int)):
                    found[key] = nested
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return found


def _agent_text(thread: dict, turn_id: str) -> str | None:
    turns = thread.get("turns") if isinstance(thread, dict) else None
    if not isinstance(turns, list):
        return None
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("id") != turn_id:
            continue
        items = turn.get("items")
        if not isinstance(items, list):
            return None
        messages = [item.get("text") for item in items
                    if isinstance(item, dict)
                    and item.get("type") == "agentMessage"
                    and isinstance(item.get("text"), str)]
        return messages[-1] if messages else None
    return None


def run_live() -> dict:
    if os.environ.get("FLEET_CODEX_LIVE") != "1":
        return {"mode": "live", "overall": "SKIP",
                "reason": "set FLEET_CODEX_LIVE=1 to authorize a real turn"}
    login = subprocess.run(
        ["codex", "login", "status"], cwd=REPO, stdin=subprocess.DEVNULL,
        text=True, capture_output=True, timeout=15, check=False)
    login_text = (login.stdout + login.stderr).strip()
    if login.returncode != 0 or "Logged in using ChatGPT" not in login_text:
        return {"mode": "live", "overall": "BLOCKED",
                "reason": "public login status is not ChatGPT auth"}

    sys.path.insert(0, str(BIN))
    from fleet_codex import CodexHostClient  # pylint: disable=import-outside-toplevel

    manifest = _manifest()
    thread_id = turn_id = None
    client = None
    terminal = None
    usage = {}
    result_text = None
    cleanup = {"host": "not_started", "thread": "not_created"}
    try:
        with tempfile.TemporaryDirectory(prefix="fleet-codex-live-") as raw:
            home = Path(raw).resolve()
            (home / "state").mkdir()
            client = CodexHostClient.ensure(
                home, ready_timeout=15, idle_timeout=120)
            rate_limits = _rpc(
                client, f"accept-rate-{uuid.uuid4()}",
                "account/rateLimits/read", {}, timeout=15)
            if _quota_blocked(rate_limits):
                raise RuntimeError(
                    "public rate-limit evidence reports no capacity")
            started = _rpc(
                client, f"accept-thread-{uuid.uuid4()}", "thread/start", {
                    "cwd": str(home), "model": "gpt-5.6-luna",
                    "approvalPolicy": "never", "sandbox": "read-only",
                }, mutation=True)
            thread = started.get("thread") if isinstance(started, dict) else None
            thread_id = thread.get("id") if isinstance(thread, dict) else None
            if not isinstance(thread_id, str):
                raise RuntimeError("thread/start returned no public thread ID")
            started_turn = _rpc(
                client, f"accept-turn-{uuid.uuid4()}", "turn/start", {
                    "threadId": thread_id,
                    "input": [{"type": "text",
                               "text": "Reply exactly FLEET_NATIVE_OK. Do not use tools.",
                               "text_elements": []}],
                }, mutation=True, timeout=45)
            turn = started_turn.get("turn") \
                if isinstance(started_turn, dict) else None
            turn_id = turn.get("id") if isinstance(turn, dict) else None
            if not isinstance(turn_id, str):
                raise RuntimeError("turn/start returned no public turn ID")
            deadline = time.monotonic() + 90
            last_thread = None
            while time.monotonic() < deadline:
                read = _rpc(
                    client, f"accept-read-{uuid.uuid4()}", "thread/read",
                    {"threadId": thread_id, "includeTurns": True}, timeout=15)
                last_thread = read.get("thread") if isinstance(read, dict) else None
                turns = last_thread.get("turns") \
                    if isinstance(last_thread, dict) else None
                match = next((item for item in turns or []
                              if isinstance(item, dict)
                              and item.get("id") == turn_id), None)
                terminal = match.get("status") if isinstance(match, dict) else None
                if terminal in {"completed", "failed", "interrupted"}:
                    usage = _token_usage(match)
                    result_text = _agent_text(last_thread, turn_id)
                    break
                time.sleep(0.25)
            if terminal not in {"completed", "failed", "interrupted"}:
                _rpc(client, f"accept-interrupt-{uuid.uuid4()}",
                     "turn/interrupt", {"threadId": thread_id,
                                        "turnId": turn_id},
                     mutation=True, timeout=15)
                raise RuntimeError("minimal turn did not become terminal in 90 seconds")
    except Exception as exc:
        report = {
            "mode": "live", "overall": "BLOCKED",
            "reason": f"{type(exc).__name__}: {str(exc)[:240]}",
            "thread_id": thread_id, "turn_id": turn_id,
            "terminal_status": terminal,
        }
    else:
        report = {
            "mode": "live", "overall": "PASS",
            "protocol": {
                "codex_version": manifest["codex_version"],
                "schema_sha256": manifest["schema_sha256"],
            },
            "auth": "chatgpt", "api_key_used": False,
            "thread_id": thread_id, "turn_id": turn_id,
            "terminal_status": terminal,
            "result": result_text, "usage": usage or "UNMEASURED",
        }
    finally:
        if client is not None:
            try:
                client.call({"operation_id": f"accept-shutdown-{uuid.uuid4()}",
                             "method": "host/shutdown", "payload": {}}, timeout=3)
                cleanup["host"] = "shutdown"
                client.wait_for_exit(3)
            except Exception:
                pass
        if thread_id is not None:
            deleted = subprocess.run(
                ["codex", "delete", "--force", thread_id], cwd=REPO,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=15, check=False)
            cleanup["thread"] = (
                "deleted" if deleted.returncode == 0 else "delete_failed")
    report["cleanup"] = cleanup
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fake", action="store_true")
    group.add_argument("--live", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_fake(args.python) if args.fake else run_live()
    return _emit(report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
