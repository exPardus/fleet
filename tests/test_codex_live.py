"""Default-safe entry points for the bounded native Codex acceptance harness."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tools" / "codex_native_acceptance.py"


def test_fake_acceptance_manifest_names_existing_exact_probes():
    scope = {"__name__": "acceptance_manifest", "__file__": str(HARNESS)}
    exec(compile(HARNESS.read_text(encoding="utf-8"), str(HARNESS), "exec"), scope)
    cases = scope["FAKE_CASES"]
    assert set(cases) == {
        "interface_registration", "supervisor_boot_claim", "idle_wake",
        "active_steer", "result", "usage",
        "interrupt", "checkpoint_handoff", "restart_adoption",
        "stale_predecessor_denial",
    }
    for nodes in cases.values():
        for node in nodes:
            relative, test_name = node.split("::", 1)
            source = (REPO / relative).read_text(encoding="utf-8")
            assert f"def {test_name}(" in source
    assert set(scope["BLOCKED_CASES"]) == {"interface_registration"}


def test_live_gate_disabled_starts_no_codex_process(tmp_path):
    stub = tmp_path / "codex"
    marker = tmp_path / "called"
    stub.write_text(
        f"#!/bin/sh\nprintf called > {str(marker)!r}\nexit 97\n",
        encoding="utf-8")
    stub.chmod(0o700)
    env = dict(os.environ)
    env.pop("FLEET_CODEX_LIVE", None)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"

    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--live"], cwd=REPO, env=env,
        stdin=subprocess.DEVNULL, text=True, capture_output=True,
        timeout=10, check=False)

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["overall"] == "SKIP"
    assert not marker.exists()


@pytest.mark.skipif(
    os.environ.get("FLEET_CODEX_LIVE") != "1",
    reason="set FLEET_CODEX_LIVE=1 for one real ChatGPT-authenticated turn")
def test_live_public_protocol_minimal_turn():
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--live"], cwd=REPO,
        stdin=subprocess.DEVNULL, text=True, capture_output=True,
        timeout=150, check=False)
    report = json.loads(completed.stdout)
    if report["overall"] == "BLOCKED":
        pytest.skip(f"BLOCKED: {report['reason']}")
    assert completed.returncode == 0
    assert report["overall"] == "PASS"
    assert report["auth"] == "chatgpt"
    assert report["api_key_used"] is False
    assert report["terminal_status"] == "completed"
    assert report["result"] == "FLEET_NATIVE_OK"
    assert report["cleanup"] == {"host": "shutdown", "thread": "deleted"}
