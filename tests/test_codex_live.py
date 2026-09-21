"""Default-safe entry points for the bounded native Codex acceptance harness."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "tools" / "codex_native_acceptance.py"
NO_INFERENCE_FIXTURE = (
    REPO / "tests" / "fixtures" / "codex_app_server" / "0.155.1"
    / "no-inference-acceptance.json")
NO_INFERENCE_RECEIPT = (
    REPO / "docs" / "lanes" / "codex-native-public-no-inference.json")


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


def test_public_no_inference_fixture_has_no_turn_or_duplicate_start():
    fixture = json.loads(NO_INFERENCE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["codex_version"] == "0.155.1"
    assert fixture["rpc_sequence"].count("thread/start") == 1
    assert fixture["rpc_sequence"].count("thread/resume") == 1
    assert fixture["rpc_sequence"].count("thread/inject_items") == 1
    assert set(fixture["rpc_sequence"]).isdisjoint(fixture["forbidden_methods"])
    assert fixture["expected_thread_count"] == 1
    assert fixture["maximum_pre_restart_thread_count"] == 1
    assert fixture["expected_turn_count"] == 0
    assert fixture["thread_read_include_turns"] is False
    assert fixture["thread_list_cwd_filter"] is False
    assert fixture["thread_list_state_db_only"] is False


def test_public_no_inference_gate_disabled_starts_no_codex_process(tmp_path):
    stub = tmp_path / "codex"
    marker = tmp_path / "called"
    stub.write_text(
        f"#!/bin/sh\nprintf called > {str(marker)!r}\nexit 97\n",
        encoding="utf-8")
    stub.chmod(0o700)
    env = dict(os.environ)
    env.pop("FLEET_CODEX_PUBLIC_ACCEPTANCE", None)
    env["PATH"] = f"{tmp_path}{os.pathsep}{env.get('PATH', '')}"

    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--public-no-inference"],
        cwd=REPO, env=env, stdin=subprocess.DEVNULL, text=True,
        capture_output=True, timeout=10, check=False)

    assert completed.returncode == 0
    report = json.loads(completed.stdout)
    assert report["mode"] == "public-no-inference"
    assert report["overall"] == "SKIP"
    assert not marker.exists()


def test_public_no_inference_report_hash_has_explicit_scope():
    scope = {"__name__": "acceptance_hash", "__file__": str(HARNESS)}
    exec(compile(HARNESS.read_text(encoding="utf-8"), str(HARNESS), "exec"), scope)
    report = scope["_seal_report"]({"overall": "BLOCKED"}, b"fixture")
    output_hash = report["evidence_hashes"].pop("output_payload_sha256")

    assert output_hash == scope["_canonical_sha256"](report)
    assert report["evidence_hashes"]["input_fixture_sha256"] == (
        "f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d")


def test_checked_public_no_inference_receipt_is_sealed_and_clean():
    scope = {"__name__": "acceptance_receipt", "__file__": str(HARNESS)}
    exec(compile(HARNESS.read_text(encoding="utf-8"), str(HARNESS), "exec"), scope)
    report = json.loads(NO_INFERENCE_RECEIPT.read_text(encoding="utf-8"))
    claimed = report["evidence_hashes"].pop("output_payload_sha256")

    assert claimed == scope["_canonical_sha256"](report)
    assert report["schema"]["initialize_codex_home_canonical_match"] is True
    assert report["cleanup"]["active_tree"]["reference_pids_before_cleanup"] == []
    assert report["cleanup"]["active_tree"]["lock_checks_after"] == [False, False]
    assert all(row["passed"] for row in report["process_exit_checks"])
    assert all(row["removed"] for row in report["stale_tree_cleanup"])


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


@pytest.mark.skipif(
    os.environ.get("FLEET_CODEX_PUBLIC_ACCEPTANCE") != "1",
    reason="set FLEET_CODEX_PUBLIC_ACCEPTANCE=1 for zero-inference app-server acceptance")
def test_real_public_protocol_without_inference():
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--public-no-inference"], cwd=REPO,
        stdin=subprocess.DEVNULL, text=True, capture_output=True,
        timeout=60, check=False)
    report = json.loads(completed.stdout)
    if report["overall"] == "BLOCKED":
        pytest.skip(f"BLOCKED: {report['reason']}")
    assert completed.returncode == 0
    assert report["overall"] == "PASS"
    assert report["codex_version"] == "0.155.1"
    assert report["thread"]["count"] == 1
    assert report["thread"]["turn_count"] == 0
    assert report["host"]["generation_changed"] is True
    assert report["journal"]["states"] == ["committed", "committed"]
    assert report["inference"]["turn_methods"] == []
