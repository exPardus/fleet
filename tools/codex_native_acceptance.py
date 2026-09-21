#!/usr/bin/env python3
"""Bounded fake and opt-in live acceptance for Fleet's public Codex adapter."""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from types import SimpleNamespace


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
        "tests/test_interface_register.py::test_codex_interface_registers_same_genuine_source_in_three_explicit_homes",
        "tests/test_interface_register.py::test_codex_interface_wrong_uuid_refuses_before_membership_read",
        "tests/test_interface_register.py::test_codex_interface_reregister_rotates_claim_and_disarms_predecessor",
        "tests/test_interface_register.py::test_codex_interface_refuses_implicit_home_before_membership_read",
        "tests/test_codex_interface_auth.py::test_forked_codex_after_claim_and_reused_pid_do_not_match",
        "tests/test_codex_host_ipc.py::test_external_interface_thread_is_observe_only",
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

BLOCKED_CASES = {}


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


def run_interface_live() -> dict:
    """Register this genuine Interface in three disposable Fleet homes.

    The app-server is used only for exact ``thread/read`` membership.  No
    thread mutation is issued, and every host is stopped before its disposable
    tree is removed.
    """
    if os.environ.get("FLEET_CODEX_INTERFACE_ACCEPTANCE") != "1":
        return {"mode": "interface-live", "overall": "SKIP",
                "reason": "set FLEET_CODEX_INTERFACE_ACCEPTANCE=1 for read-only registration"}
    thread_id = os.environ.get("CODEX_THREAD_ID")
    input_bytes = json.dumps({
        "homes": ["fleet", "pm", "tap"],
        "operation": "thread/read-only Interface registration",
        "thread_id_sha256": hashlib.sha256(
            (thread_id or "").encode("utf-8")).hexdigest(),
    }, sort_keys=True).encode("utf-8")
    clients = []
    roots: list[Path] = []
    process_exit_checks = []
    rows = []
    temporary = None
    original_fleet_home = None
    try:
        parsed = uuid.UUID(thread_id) if isinstance(thread_id, str) else None
        if parsed is None or parsed.version != 7 or str(parsed) != thread_id:
            raise RuntimeError("current CODEX_THREAD_ID is not a canonical UUIDv7")
        sys.path.insert(0, str(BIN))
        import fleet  # pylint: disable=import-outside-toplevel
        from fleet_codex import (  # pylint: disable=import-outside-toplevel
            CodexHostClient, codex_process_source, read_interface_claim,
        )
        source = codex_process_source(os.getpid(), thread_id)
        original_fleet_home = fleet.FLEET_HOME
        temporary = tempfile.TemporaryDirectory(prefix="fleet-codex-interface-")
        root = Path(temporary.name).resolve()
        roots.append(root)
        for label in ("fleet", "pm", "tap"):
            home = root / label
            (home / "state").mkdir(parents=True)
            client = CodexHostClient.ensure(
                home, ready_timeout=20, idle_timeout=120)
            clients.append((label, client, _process_record(client)))
            fleet.FLEET_HOME = home
            with redirect_stdout(io.StringIO()):
                fleet.cmd_interface_register(SimpleNamespace(
                    codex_thread=thread_id, session_id=None,
                    _fleet_home_explicit=True))
            claim = read_interface_claim(home)
            if (claim is None or claim.get("thread_id") != thread_id
                    or claim.get("ancestor_pid") != source["ancestor_pid"]
                    or claim.get("ancestor_start_identity")
                    != source["ancestor_start_identity"]
                    or claim.get("home") != str(home)):
                raise AssertionError(f"{label} Interface claim mismatched process evidence")
            operations = home / "state" / "codex" / "operations"
            if operations.exists() and any(operations.glob("*.json")):
                raise AssertionError(f"{label} registration wrote a provider mutation journal")
            rows.append({
                "label": label, "home": str(home),
                "claim_id": claim["claim_id"],
                "thread_id": thread_id,
                "host_generation": client.generation,
                "host_pid": client.host_pid,
                "host_start_identity": client.host_process_identity,
                "app_server_pid": client.app_server_pid,
                "app_server_start_identity": client.app_server_process_identity,
                "provider_mutation_count": 0,
            })
            client.call({
                "operation_id": f"interface-shutdown-{uuid.uuid4()}",
                "method": "host/shutdown", "payload": {},
            }, timeout=5)
            if not client.wait_for_exit(5):
                raise RuntimeError(f"{label} Interface host did not stop")
            _stopped_label, _stopped_client, stopped_processes = clients.pop()
            process_exit_checks.append(_process_exit_check(
                f"{label}-post-exit", stopped_processes))
            if not process_exit_checks[-1]["passed"]:
                raise RuntimeError(f"{label} host or app-server remained alive")
        report = {
            "mode": "interface-live", "overall": "PASS",
            "thread_id": thread_id,
            "source": source,
            "homes": rows,
            "public_methods": ["thread/read"] * 3,
            "provider_mutation_count": 0,
        }
    except Exception as exc:
        report = {"mode": "interface-live", "overall": "BLOCKED",
                  "reason": f"{type(exc).__name__}: {str(exc)[:260]}",
                  "thread_id": thread_id, "homes": rows}
    finally:
        if original_fleet_home is not None:
            fleet.FLEET_HOME = original_fleet_home
        for label, client, processes in reversed(clients):
            try:
                client.call({
                    "operation_id": f"interface-cleanup-{uuid.uuid4()}",
                    "method": "host/shutdown", "payload": {},
                }, timeout=3)
                client.wait_for_exit(3)
            except Exception:
                pass
            process_exit_checks.append(_process_exit_check(
                f"{label}-cleanup", processes))
        if temporary is not None:
            root = roots[0]
            references = _process_references(root)
            if references:
                report["overall"] = "BLOCKED"
                report["reason"] = f"disposable Interface tree still referenced by {references}"
            else:
                temporary.cleanup()
            report["cleanup"] = {
                "reference_pids": references,
                "tree_removed": not root.exists(),
                "process_exit_checks": process_exit_checks,
            }
    return _seal_report(report, input_bytes)


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


def _live_turn_request(thread_id: str, label: str) -> dict:
    """One fixed, schema-bounded inference request with no tool work."""
    return {
        "threadId": thread_id,
        "input": [{"type": "text",
                   "text": f'Return only JSON {{"ok":"{label}"}}. Do not use tools.',
                   "text_elements": []}],
        "effort": "low",
        "approvalPolicy": "never",
        "outputSchema": {
            "type": "object", "additionalProperties": False,
            "properties": {"ok": {"type": "string", "const": label}},
            "required": ["ok"], "maxProperties": 1,
        },
    }


def _live_turn(client, thread_id: str, label: str, *, timeout: float = 45.0) -> dict:
    """Start exactly one turn, observe it once, and never retry its body."""
    operation_id = f"accept-{label.lower()}-{uuid.uuid4()}"
    started = _rpc(client, operation_id, "turn/start",
                   _live_turn_request(thread_id, label),
                   mutation=True, timeout=min(timeout, 45.0))
    turn = started.get("turn") if isinstance(started, dict) else None
    turn_id = turn.get("id") if isinstance(turn, dict) else None
    if not isinstance(turn_id, str) or not turn_id:
        raise RuntimeError(f"{label} turn/start returned no public turn ID")
    deadline = time.monotonic() + min(timeout, 45.0)
    terminal = None
    observed_thread = None
    while time.monotonic() < deadline:
        read = _rpc(client, f"accept-{label.lower()}-read-{uuid.uuid4()}",
                    "thread/read", {"threadId": thread_id,
                                    "includeTurns": True}, timeout=10)
        observed_thread = read.get("thread") if isinstance(read, dict) else None
        turns = observed_thread.get("turns") \
            if isinstance(observed_thread, dict) else None
        matches = [item for item in turns or [] if isinstance(item, dict)
                   and item.get("id") == turn_id]
        if len(matches) != 1 or matches[0] is not (turns or [])[-1]:
            raise RuntimeError(f"{label} turn identity is absent, duplicated, or not newest")
        terminal = matches[0].get("status")
        if terminal in {"completed", "failed", "interrupted"}:
            break
        time.sleep(0.25)
    if terminal not in {"completed", "failed", "interrupted"}:
        _rpc(client, f"accept-{label.lower()}-interrupt-{uuid.uuid4()}",
             "turn/interrupt", {"threadId": thread_id, "turnId": turn_id},
             mutation=True, timeout=10)
        raise RuntimeError(f"{label} turn exceeded the 45-second hard deadline")
    evidence = None
    evidence_deadline = time.monotonic() + 3
    while time.monotonic() < evidence_deadline:
        evidence = client.call({
            "operation_id": f"accept-{label.lower()}-evidence-{uuid.uuid4()}",
            "method": "public-evidence/read",
            "payload": {"thread_id": thread_id, "turn_id": turn_id},
        }, timeout=5).result
        if (isinstance(evidence, dict) and evidence.get("turn_status") == terminal
                and isinstance(evidence.get("usage"), dict)
                and isinstance(evidence.get("result_text"), str)):
            break
        time.sleep(0.1)
    if terminal != "completed":
        raise RuntimeError(f"{label} turn ended as {terminal}")
    if not isinstance(evidence, dict):
        raise RuntimeError(f"{label} durable public evidence is absent")
    result_text = evidence.get("result_text")
    usage = evidence.get("usage")
    if (not isinstance(result_text, str)
            or len(result_text.encode("utf-8")) > 64):
        raise RuntimeError(f"{label} result exceeds the 64-byte hard output bound")
    try:
        parsed = json.loads(result_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} result is not bounded JSON") from exc
    if parsed != {"ok": label}:
        raise RuntimeError(f"{label} result did not match the fixed output schema")
    if (not isinstance(usage, dict) or not usage
            or any(not isinstance(value, int) or value < 0
                   for value in usage.values())):
        raise RuntimeError(f"{label} durable token usage is absent or malformed")
    turns = observed_thread.get("turns")
    return {
        "operation_id": operation_id, "turn_id": turn_id,
        "terminal_status": terminal, "result": parsed,
        "result_bytes": len(result_text.encode("utf-8")),
        "result_sha256": hashlib.sha256(result_text.encode("utf-8")).hexdigest(),
        "usage": usage, "observed_turn_count": len(turns),
    }


def _wait_stale_host(home: Path, timeout: float = 5.0) -> None:
    metadata_path = home / "state" / "codex" / "host.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        if time.time() - metadata.get("heartbeat", time.time()) > 3.0:
            return
        time.sleep(0.05)
    raise RuntimeError("stopped host metadata did not become stale")


def run_live() -> dict:
    """One two-turn boot/wake lifecycle; no accepted body is ever retried."""
    if os.environ.get("FLEET_CODEX_LIVE") != "1":
        return {"mode": "live", "overall": "SKIP",
                "reason": "set FLEET_CODEX_LIVE=1 to authorize one bounded lifecycle"}
    login = subprocess.run(
        ["codex", "login", "status"], cwd=REPO, stdin=subprocess.DEVNULL,
        text=True, capture_output=True, timeout=15, check=False)
    login_text = (login.stdout + login.stderr).strip()
    if login.returncode != 0 or "Logged in using ChatGPT" not in login_text:
        return {"mode": "live", "overall": "BLOCKED",
                "reason": "public login status is not ChatGPT auth"}

    sys.path.insert(0, str(BIN))
    import fleet  # pylint: disable=import-outside-toplevel
    from fleet_codex import (  # pylint: disable=import-outside-toplevel
        CodexHostClient, codex_process_source, read_interface_claim,
    )

    manifest = _manifest()
    thread_id = os.environ.get("CODEX_THREAD_ID")
    provider_thread_id = None
    client = None
    launched_processes = []
    process_exit_checks = []
    turns = []
    cleanup = {"registration_host": "not_started",
               "first_lifecycle_host": "not_started",
               "second_lifecycle_host": "not_started",
               "disposable_tree": "pending"}
    original_fleet_home = fleet.FLEET_HOME
    temporary = tempfile.TemporaryDirectory(prefix="fleet-codex-live-")
    root = Path(temporary.name).resolve()
    home = root / "fleet-home"
    codex_home = root / "codex-home"
    user_home = root / "user-home"
    for path in (home / "state", codex_home, user_home):
        path.mkdir(parents=True)
    codex_home.chmod(0o700)
    user_home.chmod(0o700)
    live_env = dict(os.environ)
    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY",
                 "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
        live_env.pop(name, None)
    live_env.update({
        "CODEX_HOME": str(codex_home), "HOME": str(user_home),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
    })
    report: dict
    try:
        current = uuid.UUID(thread_id) if isinstance(thread_id, str) else None
        if current is None or current.version != 7 or str(current) != thread_id:
            raise RuntimeError("current CODEX_THREAD_ID is not a canonical UUIDv7")
        source = codex_process_source(os.getpid(), thread_id)

        # Read-only registration uses the current public Codex home so the
        # external Interface thread can be observed. It is stopped before the
        # same Fleet home starts the isolated lifecycle app-server.
        client = CodexHostClient.ensure(home, ready_timeout=20, idle_timeout=120)
        cleanup["registration_host"] = "running"
        registration_processes = _process_record(client)
        launched_processes.append(("registration", registration_processes))
        fleet.FLEET_HOME = home
        with redirect_stdout(io.StringIO()):
            fleet.cmd_interface_register(SimpleNamespace(
                codex_thread=thread_id, session_id=None,
                _fleet_home_explicit=True))
        interface_claim = read_interface_claim(home)
        if (interface_claim is None
                or interface_claim.get("thread_id") != thread_id
                or interface_claim.get("ancestor_pid") != source["ancestor_pid"]):
            raise RuntimeError("live home Interface claim did not bind current process")
        client.call({"operation_id": f"live-registration-stop-{uuid.uuid4()}",
                     "method": "host/shutdown", "payload": {}}, timeout=5)
        if not client.wait_for_exit(5):
            raise RuntimeError("registration host did not stop")
        cleanup["registration_host"] = "shutdown"
        process_exit_checks.append(_process_exit_check(
            "registration-post-exit", registration_processes))
        client = None
        _wait_stale_host(home)

        client = CodexHostClient.ensure(
            home, env=live_env, ready_timeout=20, idle_timeout=120)
        cleanup["first_lifecycle_host"] = "running"
        first_processes = _process_record(client)
        launched_processes.append(("first-lifecycle", first_processes))
        first_generation = client.generation
        rate_limits = _rpc(client, f"live-rate-{uuid.uuid4()}",
                           "account/rateLimits/read", {}, timeout=15)
        if _quota_blocked(rate_limits):
            raise RuntimeError("public rate-limit evidence reports no capacity")
        started = _rpc(client, f"live-thread-{uuid.uuid4()}", "thread/start", {
            "cwd": str(home), "model": "gpt-5.6-luna",
            "approvalPolicy": "never", "sandbox": "read-only",
            "ephemeral": False,
            "baseInstructions": (
                "Return only JSON matching the supplied output schema. "
                "Never call tools."),
        }, mutation=True, timeout=20)
        provider_thread = started.get("thread") if isinstance(started, dict) else None
        provider_thread_id = provider_thread.get("id") \
            if isinstance(provider_thread, dict) else None
        if not isinstance(provider_thread_id, str) or provider_thread_id == thread_id:
            raise RuntimeError("thread/start did not return a distinct provider thread")
        turns.append(_live_turn(client, provider_thread_id, "BOOT"))
        if turns[-1]["observed_turn_count"] != 1:
            raise RuntimeError("boot created a duplicate turn")

        client.call({"operation_id": f"live-first-stop-{uuid.uuid4()}",
                     "method": "host/shutdown", "payload": {}}, timeout=5)
        if not client.wait_for_exit(5):
            raise RuntimeError("first lifecycle host did not stop")
        cleanup["first_lifecycle_host"] = "shutdown"
        process_exit_checks.append(_process_exit_check(
            "first-lifecycle-post-exit", first_processes))
        client = None
        _wait_stale_host(home)

        client = CodexHostClient.ensure(
            home, env=live_env, ready_timeout=20, idle_timeout=120)
        cleanup["second_lifecycle_host"] = "running"
        second_processes = _process_record(client)
        launched_processes.append(("second-lifecycle", second_processes))
        second_generation = client.generation
        if second_generation == first_generation:
            raise RuntimeError("lifecycle host restart retained its generation")
        recovered = _result_thread(_rpc(
            client, f"live-restart-read-{uuid.uuid4()}", "thread/read",
            {"threadId": provider_thread_id, "includeTurns": True}, timeout=15),
            "restart thread/read")
        recovered_turns = recovered.get("turns")
        if (recovered.get("id") != provider_thread_id
                or not isinstance(recovered_turns, list)
                or [item.get("id") for item in recovered_turns]
                != [turns[0]["turn_id"]]):
            raise RuntimeError("restart did not recover exactly the boot turn")
        turns.append(_live_turn(client, provider_thread_id, "WAKE"))
        if turns[-1]["observed_turn_count"] != 2:
            raise RuntimeError("idle wake did not produce exactly one successor turn")

        report = {
            "mode": "live", "overall": "PASS",
            "protocol": {"codex_version": manifest["codex_version"],
                         "schema_sha256": manifest["schema_sha256"]},
            "auth": "chatgpt", "api_key_used": False,
            "interface": {"thread_id": thread_id,
                          "claim_id": interface_claim["claim_id"],
                          "ancestor_pid": source["ancestor_pid"],
                          "external_thread_written": False},
            "lifecycle": {
                "thread_id": provider_thread_id,
                "model": "gpt-5.6-luna", "approval_policy": "never",
                "sandbox": "read-only", "turn_limit": 2,
                "per_turn_deadline_seconds": 45, "output_limit_bytes": 64,
                "first_generation": first_generation,
                "second_generation": second_generation,
                "restart_recovered_exact_boot_turn": True,
                "turns": turns,
            },
            "rate_limits_sha256": _canonical_sha256(rate_limits),
            "duplicate_body_count": 0, "retry_count": 0,
        }
    except Exception as exc:
        report = {"mode": "live", "overall": "BLOCKED",
                  "reason": f"{type(exc).__name__}: {str(exc)[:300]}",
                  "interface_thread_id": thread_id,
                  "provider_thread_id": provider_thread_id,
                  "accepted_turns": turns, "retry_count": 0}
    finally:
        fleet.FLEET_HOME = original_fleet_home
        if client is not None:
            try:
                client.call({"operation_id": f"live-cleanup-{uuid.uuid4()}",
                             "method": "host/shutdown", "payload": {}}, timeout=3)
                client.wait_for_exit(3)
                for key in ("second_lifecycle_host", "first_lifecycle_host",
                            "registration_host"):
                    if cleanup[key] == "running":
                        cleanup[key] = "shutdown"
                        break
            except Exception:
                pass
        reference_samples = []
        deadline = time.monotonic() + 3
        while root.exists():
            references = _process_references(root)
            reference_samples.append(references)
            if not references or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        references = reference_samples[-1] if reference_samples else []
        if references:
            cleanup["disposable_tree"] = "referenced_cleanup_refused"
            report["overall"] = "BLOCKED"
            report["reason"] = f"disposable live tree still referenced by {references}"
        else:
            temporary.cleanup()
            cleanup["disposable_tree"] = "removed" if not root.exists() else "cleanup_failed"
        for label, processes in launched_processes:
            process_exit_checks.append(_process_exit_check(
                f"{label}-post-cleanup", processes))
        cleanup["reference_pid_samples"] = reference_samples
        cleanup["process_exit_checks"] = process_exit_checks
        cleanup["tree_removed"] = not root.exists()
        report["cleanup"] = cleanup
    input_bytes = json.dumps({
        "model": "gpt-5.6-luna", "turns": ["BOOT", "WAKE"],
        "turn_limit": 2, "deadline_seconds": 45, "output_limit_bytes": 64,
    }, sort_keys=True).encode("utf-8")
    return _seal_report(report, input_bytes)

def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fake", action="store_true")
    group.add_argument("--live", action="store_true")
    group.add_argument("--interface-live", action="store_true")
    group.add_argument("--public-no-inference", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cleanup-ledger", type=Path)
    args = parser.parse_args()
    if args.fake:
        report = run_fake(args.python)
    elif args.interface_live:
        report = run_interface_live()
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
