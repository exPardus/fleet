#!/usr/bin/env python3
"""Bounded fake and opt-in live acceptance for Fleet's public Codex adapter."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import shutil
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
NO_INFERENCE_FIXTURE = (
    REPO / "tests" / "fixtures" / "codex_app_server" / "0.155.1"
    / "no-inference-acceptance.json")

FAKE_CASES = {
    "interface_registration": [
        "tests/test_interface_register.py::test_codex_interface_refuses_all_three_explicit_homes_without_authenticator",
        "tests/test_interface_register.py::test_codex_interface_refuses_implicit_home_before_membership_read",
    ],
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
        "tests/test_codex_supervisor.py::test_native_completed_result_requires_complete_durable_item_evidence",
    ],
    "usage": [
        "tests/test_codex_supervisor.py::test_native_completed_result_persists_public_usage_and_result",
        "tests/test_codex_host_ipc.py::test_public_turn_evidence_store_survives_process_restart_without_provider",
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
        "The reviewed public protocol exposes thread membership, sessionId, and "
        "source, but no credential authenticating the invoking Codex caller."),
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
        "overall": ("FAIL" if not passed else
                    "BLOCKED" if BLOCKED_CASES else "PASS"),
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
         *, mutation: bool = False, timeout: float = 30,
         methods: list[str] | None = None):
    if methods is not None:
        methods.append(method)
    operation = {
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": method, "params": params},
    }
    observation = client.call(operation, timeout=timeout)
    if mutation:
        client.commit(operation_id)
    return observation.result


def _result_thread(result: object, source: str) -> dict:
    thread = result.get("thread") if isinstance(result, dict) else None
    if not isinstance(thread, dict):
        raise AssertionError(f"{source} returned no thread object")
    return thread


def _same_thread(thread: dict, thread_id: str, session_id: str,
                 home: Path, source: str, *, require_turns: bool = False) -> None:
    if thread.get("id") != thread_id:
        raise AssertionError(f"{source} changed the genuine thread ID")
    if thread.get("sessionId") != session_id:
        raise AssertionError(f"{source} changed the genuine session ID")
    if thread.get("cwd") != str(home):
        raise AssertionError(f"{source} escaped the disposable Fleet home")
    if require_turns and thread.get("turns") != []:
        raise AssertionError(f"{source} observed a turn in zero-inference acceptance")


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, separators=(",", ":"), sort_keys=True,
        ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _linux_process_identity(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()[21]
    except (OSError, IndexError, UnicodeError):
        return None


def _process_record(client) -> dict:
    return {
        "host": {
            "pid": client.host_pid,
            "start_identity": client.host_process_identity,
            "started_at": client.started_at,
        },
        "app_server": {
            "pid": client.app_server_pid,
            "start_identity": client.app_server_process_identity,
            "started_at": client.app_server_started_at,
        },
    }


def _process_exit_check(label: str, processes: dict) -> dict:
    alive = []
    for role in ("host", "app_server"):
        record = processes[role]
        if _linux_process_identity(record["pid"]) == record["start_identity"]:
            alive.append(role)
    return {"label": label, "alive": alive, "passed": not alive}


def _under(path: str, root: Path) -> bool:
    clean = path.removesuffix(" (deleted)")
    try:
        Path(clean).relative_to(root)
    except ValueError:
        return False
    return True


def _process_references(root: Path) -> list[int]:
    references = set()
    encoded_root = os.fsencode(str(root))
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if encoded_root in (process / "cmdline").read_bytes():
                references.add(int(process.name))
                continue
        except OSError:
            continue
        for name in ("cwd", "root"):
            try:
                if _under(os.readlink(process / name), root):
                    references.add(int(process.name))
                    break
            except OSError:
                pass
        if int(process.name) in references:
            continue
        try:
            descriptors = list((process / "fd").iterdir())
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if _under(os.readlink(descriptor), root):
                    references.add(int(process.name))
                    break
            except OSError:
                pass
    return sorted(references)


def _cleanup_stale_public_trees() -> list[dict]:
    records = []
    temp_root = Path(tempfile.gettempdir()).resolve()
    for candidate in sorted(temp_root.glob("fleet-codex-public-*")):
        if (candidate.is_symlink() or not candidate.is_dir()
                or candidate.stat().st_uid != os.getuid()):
            raise RuntimeError(f"unsafe stale acceptance tree: {candidate}")
        references = _process_references(candidate)
        locks = sum(1 for path in candidate.rglob("*.lock") if path.is_file())
        if references:
            raise RuntimeError(
                f"stale acceptance tree still referenced by PIDs {references}")
        record = {
            "path": str(candidate), "reference_pids": references,
            "lock_files_before": locks,
        }
        shutil.rmtree(candidate)
        record["exists_checks_after"] = [candidate.exists(), candidate.exists()]
        record["lock_checks_after"] = [
            any(candidate.rglob("*.lock")) if candidate.exists() else False,
            any(candidate.rglob("*.lock")) if candidate.exists() else False,
        ]
        record["removed"] = not any(record["exists_checks_after"])
        if not record["removed"]:
            raise RuntimeError(f"stale acceptance tree was not removed: {candidate}")
        records.append(record)
    return records


def _seal_report(report: dict, fixture_bytes: bytes) -> dict:
    report["evidence_hashes"] = {
        "input_fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "output_hash_scope": (
            "canonical JSON excluding evidence_hashes.output_payload_sha256"),
    }
    report["evidence_hashes"]["output_payload_sha256"] = \
        _canonical_sha256(report)
    return report


def run_public_no_inference(*, cleanup_ledger: dict | None = None,
                            cleanup_ledger_sha256: str | None = None) -> dict:
    """Exercise genuine stable thread identity without ever starting a turn."""
    if os.environ.get("FLEET_CODEX_PUBLIC_ACCEPTANCE") != "1":
        return {
            "mode": "public-no-inference", "overall": "SKIP",
            "reason": "set FLEET_CODEX_PUBLIC_ACCEPTANCE=1 to run the installed app-server",
        }

    manifest = _manifest()
    fixture_bytes = NO_INFERENCE_FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    methods: list[str] = []
    cleanup = {"first_host": "not_started", "second_host": "not_started",
               "disposable_home": "pending"}
    process_exit_checks: list[dict] = []
    owned_processes: list[tuple[str, dict]] = []
    stale_tree_cleanup: list[dict] = list(
        (cleanup_ledger or {}).get("stale_tree_cleanup", []))
    client = None
    root = None
    temporary = None
    report: dict
    try:
        stale_tree_cleanup.extend(_cleanup_stale_public_trees())
        temporary = tempfile.TemporaryDirectory(prefix="fleet-codex-public-")
        with nullcontext(temporary.name) as raw:
            root = Path(raw).resolve()
            home = root / "fleet-home"
            foreign_home = root / "foreign-home"
            codex_home = root / "codex-home"
            disposable_user_home = root / "user-home"
            for path in (home / "state", foreign_home / "state", codex_home,
                         disposable_user_home):
                path.mkdir(parents=True)
            codex_home.chmod(0o700)
            disposable_user_home.chmod(0o700)
            env = dict(os.environ)
            for name in (
                    "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY",
                    "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
                env.pop(name, None)
            env.update({
                "CODEX_HOME": str(codex_home),
                "HOME": str(disposable_user_home),
                "XDG_CACHE_HOME": str(root / "cache"),
                "XDG_CONFIG_HOME": str(root / "config"),
                "XDG_DATA_HOME": str(root / "data"),
            })
            version = subprocess.run(
                ["codex", "--version"], cwd=home, env=env,
                stdin=subprocess.DEVNULL, text=True, capture_output=True,
                timeout=10, check=False)
            expected_version = f"codex-cli {fixture['codex_version']}"
            if version.returncode != 0 or version.stdout.strip() != expected_version:
                raise RuntimeError(
                    f"installed Codex version is not {expected_version!r}")

            sys.path.insert(0, str(BIN))
            from fleet_codex import (  # pylint: disable=import-outside-toplevel
                CodexHostClient, HostUnavailable, OperationJournal,
                connect_existing,
            )

            client = CodexHostClient.ensure(
                home, env=env, ready_timeout=20, idle_timeout=120)
            cleanup["first_host"] = "running"
            first_processes = _process_record(client)
            owned_processes.append(("first", first_processes))
            first_generation = client.generation
            ping = client.call({
                "operation_id": f"accept-ping-{uuid.uuid4()}",
                "method": "ping", "payload": {},
            }, timeout=5).result
            if (ping.get("home") != str(home)
                    or ping.get("schema_digest") != manifest["schema_sha256"]
                    or ping.get("codex_protocol_version")
                    != manifest["protocol_version"]):
                raise AssertionError("ready host metadata did not prove exact schema and home")

            foreign_refused = False
            try:
                connect_existing(foreign_home)
            except HostUnavailable:
                foreign_refused = True
            if not foreign_refused:
                raise AssertionError("foreign Fleet home attached to the exact-home host")

            start_id = f"accept-thread-start-{uuid.uuid4()}"
            started = _rpc(
                client, start_id, "thread/start", {
                    "cwd": str(home), "approvalPolicy": "never",
                    "sandbox": "read-only", "ephemeral": False,
                }, mutation=True, timeout=15, methods=methods)
            started_thread = _result_thread(started, "thread/start")
            thread_id = started_thread.get("id")
            session_id = started_thread.get("sessionId")
            if not isinstance(thread_id, str) or not thread_id:
                raise AssertionError("thread/start returned no genuine thread ID")
            if not isinstance(session_id, str) or not session_id:
                raise AssertionError("thread/start returned no genuine session ID")
            _same_thread(started_thread, thread_id, session_id, home,
                         "thread/start")
            _rpc(
                client, f"accept-inject-{uuid.uuid4()}",
                "thread/inject_items", {
                    "threadId": thread_id,
                    "items": [{
                        "type": "message", "role": "user",
                        "content": [{
                            "type": "input_text",
                            "text": "Fleet zero-inference acceptance marker",
                        }],
                    }],
                }, timeout=10, methods=methods)

            read_one = _result_thread(_rpc(
                client, f"accept-read-one-{uuid.uuid4()}", "thread/read",
                {"threadId": thread_id,
                 "includeTurns": fixture["thread_read_include_turns"]},
                timeout=10, methods=methods), "first thread/read")
            _same_thread(read_one, thread_id, session_id, home,
                         "first thread/read")
            listed_one = _rpc(
                client, f"accept-list-one-{uuid.uuid4()}", "thread/list",
                {"limit": 100,
                 "useStateDbOnly": fixture["thread_list_state_db_only"]},
                timeout=10,
                methods=methods)
            first_rows = listed_one.get("data") \
                if isinstance(listed_one, dict) else None
            if (not isinstance(first_rows, list)
                    or len(first_rows) > fixture["maximum_pre_restart_thread_count"]):
                count = len(first_rows) if isinstance(first_rows, list) else None
                raise AssertionError(
                    "thread/list returned duplicate disposable-home threads "
                    f"(count={count}, source={read_one.get('source')!r})")
            if first_rows:
                _same_thread(first_rows[0], thread_id, session_id, home,
                             "first thread/list")

            client.call({
                "operation_id": f"accept-shutdown-one-{uuid.uuid4()}",
                "method": "host/shutdown", "payload": {},
            }, timeout=5)
            if not client.wait_for_exit(5):
                raise RuntimeError("first Fleet host did not stop")
            cleanup["first_host"] = "shutdown"
            for sequence in (1, 2):
                check = _process_exit_check(
                    f"first-host-post-exit-{sequence}", first_processes)
                process_exit_checks.append(check)
                if not check["passed"]:
                    raise RuntimeError("first host or app-server remained alive")
                time.sleep(0.05)
            client = None
            deadline = time.monotonic() + 5
            metadata_path = home / "state" / "codex" / "host.json"
            while time.monotonic() < deadline:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if time.time() - metadata["heartbeat"] > 3.0:
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("first Fleet host metadata did not become stale")

            client = CodexHostClient.ensure(
                home, env=env, ready_timeout=20, idle_timeout=120)
            cleanup["second_host"] = "running"
            second_processes = _process_record(client)
            owned_processes.append(("second", second_processes))
            second_generation = client.generation
            if second_generation == first_generation:
                raise AssertionError("Fleet host restart retained its old generation")

            read_two = _result_thread(_rpc(
                client, f"accept-read-two-{uuid.uuid4()}", "thread/read",
                {"threadId": thread_id,
                 "includeTurns": fixture["thread_read_include_turns"]},
                timeout=10, methods=methods), "restart thread/read")
            _same_thread(read_two, thread_id, session_id, home,
                         "restart thread/read")

            resume_id = f"accept-thread-resume-{uuid.uuid4()}"
            resumed = _rpc(
                client, resume_id, "thread/resume", {"threadId": thread_id},
                mutation=True, timeout=15, methods=methods)
            resumed_thread = _result_thread(resumed, "thread/resume")
            _same_thread(resumed_thread, thread_id, session_id, home,
                         "thread/resume")
            read_three = _result_thread(_rpc(
                client, f"accept-read-three-{uuid.uuid4()}", "thread/read",
                {"threadId": thread_id,
                 "includeTurns": fixture["thread_read_include_turns"]},
                timeout=10, methods=methods), "resumed thread/read")
            _same_thread(read_three, thread_id, session_id, home,
                         "resumed thread/read")
            listed_two = _rpc(
                client, f"accept-list-two-{uuid.uuid4()}", "thread/list",
                {"limit": 100,
                 "useStateDbOnly": fixture["thread_list_state_db_only"]},
                timeout=10,
                methods=methods)
            second_rows = listed_two.get("data") \
                if isinstance(listed_two, dict) else None
            if not isinstance(second_rows, list) or len(second_rows) > 1:
                raise AssertionError("restart created duplicate provider threads")
            if second_rows:
                _same_thread(second_rows[0], thread_id, session_id, home,
                             "restart thread/list")

            if methods != fixture["rpc_sequence"]:
                raise AssertionError("public RPC sequence escaped the reviewed fixture")
            forbidden = sorted(set(methods) & set(fixture["forbidden_methods"]))
            if forbidden:
                raise AssertionError(f"inference methods were called: {forbidden}")
            records = {row["operation_id"]: row for row in
                       OperationJournal(home, "acceptance").records()}
            journal_rows = [records[start_id], records[resume_id]]
            if ([row.get("state") for row in journal_rows]
                    != ["committed", "committed"]):
                raise AssertionError("thread identity mutations are not durably committed")
            for row, expected_method in zip(
                    journal_rows, ("thread/start", "thread/resume"), strict=True):
                result_thread = _result_thread(row.get("result"), expected_method)
                if (row.get("public_method") != expected_method
                        or result_thread.get("id") != thread_id):
                    raise AssertionError("journal result lost genuine thread identity")

            list_blocked = len(second_rows) == 0
            report = {
                "mode": "public-no-inference",
                "overall": "BLOCKED" if list_blocked else "PASS",
                "codex_version": fixture["codex_version"],
                "schema": {
                    "protocol_version": manifest["protocol_version"],
                    "sha256": manifest["schema_sha256"],
                    "initialized_server_version": fixture["codex_version"],
                    "configured_codex_home": str(codex_home),
                    "initialize_codex_home_canonical_match": True,
                },
                "host": {
                    "first_generation": first_generation,
                    "second_generation": second_generation,
                    "generation_changed": True,
                    "exact_home": True, "foreign_home_refused": True,
                    "processes": {
                        "first": first_processes,
                        "second": second_processes,
                    },
                },
                "thread": {
                    "id": thread_id, "session_id": session_id,
                    "identity_matches": True, "cwd_matches": True,
                    "count": len(second_rows), "turn_count": 0,
                    "read_after_restart": True, "resume_same_id": True,
                    "list_status": "BLOCKED_ZERO_TURN" if list_blocked else "PASS",
                },
                "journal": {
                    "operation_ids": [start_id, resume_id],
                    "methods": [row["public_method"] for row in journal_rows],
                    "states": [row["state"] for row in journal_rows],
                    "generations": [row["generation"] for row in journal_rows],
                    "input_sha256": [
                        row["payload_digest"] for row in journal_rows],
                    "output_sha256": [
                        _canonical_sha256(row["result"])
                        for row in journal_rows],
                },
                "inference": {"turn_methods": forbidden, "model_calls": 0},
                "api_key_used": False,
            }
            if list_blocked:
                report["reason"] = (
                    "Codex 0.155.1 thread/list omits the genuine zero-turn thread; "
                    "read and resume recover the same ID after Fleet-host restart")
            client.call({
                "operation_id": f"accept-shutdown-two-{uuid.uuid4()}",
                "method": "host/shutdown", "payload": {},
            }, timeout=5)
            if not client.wait_for_exit(5):
                raise RuntimeError("second Fleet host did not stop")
            cleanup["second_host"] = "shutdown"
            for sequence in (1, 2):
                check = _process_exit_check(
                    f"second-host-post-exit-{sequence}", second_processes)
                process_exit_checks.append(check)
                if not check["passed"]:
                    raise RuntimeError("second host or app-server remained alive")
                time.sleep(0.05)
            client = None
    except AssertionError as exc:
        report = {"mode": "public-no-inference", "overall": "FAIL",
                  "reason": str(exc)[:300]}
    except Exception as exc:
        report = {"mode": "public-no-inference", "overall": "BLOCKED",
                  "reason": f"{type(exc).__name__}: {str(exc)[:260]}"}
    finally:
        if client is not None:
            try:
                client.call({"operation_id": f"accept-cleanup-{uuid.uuid4()}",
                             "method": "host/shutdown", "payload": {}}, timeout=3)
                client.wait_for_exit(3)
                for key in ("second_host", "first_host"):
                    if cleanup[key] == "running":
                        cleanup[key] = "shutdown"
                        break
            except Exception:
                pass
        if temporary is not None:
            reference_samples = []
            reference_deadline = time.monotonic() + 3
            while root is not None and root.exists():
                references = _process_references(root)
                reference_samples.append(references)
                if not references:
                    break
                if time.monotonic() >= reference_deadline:
                    break
                time.sleep(0.05)
            active_tree = {
                "path": str(root),
                "reference_pid_samples": reference_samples,
                "reference_pids_before_cleanup": (
                    reference_samples[-1] if reference_samples else []),
                "lock_files_before": (
                    sum(1 for path in root.rglob("*.lock") if path.is_file())
                    if root is not None and root.exists() else 0),
            }
            if active_tree["reference_pids_before_cleanup"]:
                cleanup["disposable_home"] = "referenced_cleanup_refused"
                report["overall"] = "BLOCKED"
                report["reason"] = (
                    "task-owned disposable tree retained live process references")
            else:
                temporary.cleanup()
                cleanup["disposable_home"] = (
                    "removed" if root is not None and not root.exists()
                    else "cleanup_failed")
            active_tree["exists_checks_after"] = (
                [root.exists(), root.exists()] if root is not None else [True, True])
            active_tree["lock_checks_after"] = (
                [any(root.rglob("*.lock")), any(root.rglob("*.lock"))]
                if root is not None and root.exists() else [False, False])
            active_tree["reference_pids_after"] = (
                _process_references(root) if root is not None and root.exists()
                else [])
            active_tree["removed"] = (
                not any(active_tree["exists_checks_after"])
                and not active_tree["reference_pids_after"])
            cleanup["active_tree"] = active_tree
            for owner, processes in owned_processes:
                for sequence in (1, 2):
                    process_exit_checks.append(_process_exit_check(
                        f"{owner}-post-tree-cleanup-{sequence}", processes))
    report["cleanup"] = cleanup
    report["process_exit_checks"] = process_exit_checks
    report["stale_tree_cleanup"] = stale_tree_cleanup
    if cleanup_ledger_sha256 is not None:
        report["cleanup_ledger_sha256"] = cleanup_ledger_sha256
    return _seal_report(report, fixture_bytes)


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
    group.add_argument("--public-no-inference", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cleanup-ledger", type=Path)
    args = parser.parse_args()
    if args.fake:
        report = run_fake(args.python)
    elif args.live:
        report = run_live()
    else:
        ledger = None
        ledger_sha256 = None
        if args.cleanup_ledger is not None:
            ledger_bytes = args.cleanup_ledger.read_bytes()
            if len(ledger_bytes) > 64 * 1024:
                raise SystemExit("cleanup ledger exceeds 65536 bytes")
            ledger = json.loads(ledger_bytes)
            claimed = ledger.get("evidence_hashes", {}).get(
                "output_payload_sha256") if isinstance(ledger, dict) else None
            if not isinstance(ledger, dict) or not isinstance(claimed, str):
                raise SystemExit("cleanup ledger is not a sealed report")
            unsealed = json.loads(json.dumps(ledger))
            unsealed["evidence_hashes"].pop("output_payload_sha256")
            if _canonical_sha256(unsealed) != claimed:
                raise SystemExit("cleanup ledger hash does not match")
            ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
        report = run_public_no_inference(
            cleanup_ledger=ledger,
            cleanup_ledger_sha256=ledger_sha256)
    return _emit(report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
