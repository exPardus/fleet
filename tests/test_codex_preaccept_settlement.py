"""Exact worker preaccept authentication rejection, with no provider calls."""

import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from types import SimpleNamespace
import time

import pytest

import fleet
import fleet_codex


@pytest.fixture
def preaccept_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    lane = tmp_path / "lane"
    lane.mkdir()
    name = "root-worker"
    operation_id = "worker-root-worker-thread-3b51220e-cd83-4740-8efc-e25a30e86d0a"
    generation = "f4391e03-8513-4e06-a129-05bf4976f3db"
    row = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "adapter_state": "uncertain",
        "status": "dead-suspected", "last_operation_id": operation_id,
        "pending_operation": None, "codex_thread_id": None,
        "codex_turn_id": None, "codex_host_generation": None,
        "permission_effective": None, "provider_status": None,
        "cwd": str(lane), "model": "codex:gpt-5.6-luna", "mode": "accept",
        "task": "original task", "created": "2026-10-09T00:00:00Z",
    }
    sibling = {"status": "working", "task": "unrelated"}
    site_owner = {"status": "dead", "task": "separate failed predecessor"}
    fleet.save_registry({"workers": {name: row, "sibling": sibling,
                                     "site-agent-readiness-native": site_owner},
                         "unrelated_top_level": {"keep": True}})
    journal = fleet_codex.OperationJournal(tmp_path, generation)
    digest, recovery = fleet._codex_preaccept_expected_intent(
        name, row, operation_id)
    thread_source = recovery["thread_source"]
    payload = {"method": "thread/start", "params": {
        "cwd": str(lane), "model": "gpt-5.6-luna",
        "threadSource": thread_source, "approvalPolicy": "on-request",
        "sandbox": "workspace-write",
    }}
    record = journal.prepare({"operation_id": operation_id,
                              "method": "rpc", "payload": payload,
                              "recovery": recovery})
    assert record["payload_digest"] == digest
    site_operation = "worker-site-agent-readiness-native-thread-other"
    journal.prepare({"operation_id": site_operation, "method": "rpc",
                     "payload": {"method": "thread/start", "params": {}},
                     "recovery": {"kind": "thread/start",
                                  "fleet_name": "site-agent-readiness-native"}})
    journal.fail(site_operation, "blocked by unresolved predecessor operation")
    site_bytes = journal.path(site_operation).read_bytes()
    approvals = tmp_path / "state" / "codex" / "approvals"
    approvals.mkdir(mode=0o700)
    fleet_codex._atomic_json(approvals / "resolved.json", {"state": "resolved"})
    approval_bytes = (approvals / "resolved.json").read_bytes()
    host = {
        "home": str(tmp_path), "generation": generation,
        "pid": os.getpid(), "process_identity": "fake-host-start",
        "started_at": 1.0, "ready": True, "heartbeat": time.time(),
        "app_server_pid": os.getpid() + 1,
        "app_server_process_identity": "fake-child-start",
        "app_server_started_at": 2.0,
        "codex_version": "0.155.1", "schema_digest": "f" * 64,
    }
    fleet_codex._atomic_json(tmp_path / "state" / "codex" / "host.json", host)
    source = {"kind": "codex", "claim_id": "claim-1"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    monkeypatch.setattr(fleet, "_mail_source_is_current", lambda _source: True)
    monkeypatch.setattr(fleet_codex, "_process_identity", lambda pid: (
        "fake-host-start" if pid == os.getpid() else
        "fake-child-start" if pid == os.getpid() + 1 else None))
    root = Path(fleet.__file__).parent
    provenance_path = tmp_path / "state" / "interface" / "root-predecessor-source-provenance.json"
    provenance_path.parent.mkdir()
    provenance_path.write_text('{"original_source":"reviewed"}\n', encoding="utf-8")
    provenance_path.chmod(0o644)
    report_path = tmp_path / "mailbox" / "done" / "original-rejection.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("Original one-invocation peer authentication rejection\n",
                           encoding="utf-8")
    report_path.chmod(0o644)
    evidence = {
        "schema": 1, "kind": "worker/thread-start-auth-rejection",
        "home": str(tmp_path), "worker": name,
        "operation_id": operation_id, "generation": generation,
        "payload_digest": digest,
        "row_digest": fleet._codex_preaccept_digest(row, "row"),
        "journal_digest": fleet._codex_preaccept_digest(record, "journal"),
        "journal_sha256": hashlib.sha256(journal.path(operation_id).read_bytes()).hexdigest(),
        "classification_sha256": "c" * 64,
        "source": {
            "commit": "a" * 40, "fleet_sha256": "d" * 64,
            "client_sha256": hashlib.sha256(
                (root / "fleet_codex.py").read_bytes()).hexdigest(),
            "host_sha256": hashlib.sha256(
                (root / "fleet_codex_host.py").read_bytes()).hexdigest(),
            "host_pid": os.getpid(), "host_identity": "fake-host-start",
            "host_started_at": 1.0,
            "provenance_path": "state/interface/root-predecessor-source-provenance.json",
            "provenance_sha256": hashlib.sha256(provenance_path.read_bytes()).hexdigest(),
            "app_server_pid": os.getpid() + 1,
            "app_server_identity": "fake-child-start",
            "app_server_started_at": 2.0,
            "codex_version": "0.155.1", "schema_digest": "f" * 64,
        },
        "rejection": {
            "error": fleet._CODEX_PREACCEPT_AUTH_ERROR,
            "operation_id": operation_id, "generation": generation,
            "home": str(tmp_path), "payload_digest": digest,
            "report_path": "mailbox/done/original-rejection.md",
            "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    }
    path = tmp_path / "preaccept-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    path.chmod(0o600)
    args = SimpleNamespace(name=name, operation_id=operation_id,
                           generation=generation, evidence=str(path),
                           expect_evidence_sha256=hashlib.sha256(
                               path.read_bytes()).hexdigest(),
                           _fleet_home_explicit=True)
    preserved = {}
    for filename in ("state/tasks/root-worker.md", "state/briefs/root-worker.md",
                     "mailbox/sibling.md"):
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(filename, encoding="utf-8")
        preserved[filename] = target.read_bytes()
    return SimpleNamespace(home=tmp_path, name=name, row=row, sibling=sibling,
                           site_owner=site_owner,
                           journal=journal, record=record, evidence=evidence,
                           evidence_path=path, args=args, source=source,
                           preserved=preserved, site_operation=site_operation,
                           site_bytes=site_bytes, approval_bytes=approval_bytes,
                           provenance_path=provenance_path, report_path=report_path)


def _assert_preserved(case):
    data = fleet.read_registry_no_repair()
    assert data["workers"]["sibling"] == case.sibling
    assert data["workers"]["site-agent-readiness-native"] == case.site_owner
    assert data["unrelated_top_level"] == {"keep": True}
    for filename, content in case.preserved.items():
        assert (case.home / filename).read_bytes() == content
    assert case.journal.path(case.site_operation).read_bytes() == case.site_bytes
    assert (case.home / "state" / "codex" / "approvals" /
            "resolved.json").read_bytes() == case.approval_bytes


def test_exact_preaccept_settlement_is_terminal_and_idempotent(preaccept_home):
    case = preaccept_home
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    row = fleet.read_registry_no_repair()["workers"][case.name]
    record = case.journal.load(case.args.operation_id)
    assert row["status"] == "dead"
    assert row["adapter_state"] == "preaccept-failed"
    assert row["last_operation_id"] == case.args.operation_id
    assert row["codex_thread_id"] is None and row["codex_turn_id"] is None
    assert record["state"] == "failed"
    assert record["preaccept_settlement"] == row["preaccept_settlement"]
    assert not case.journal.has_unresolved()
    before = case.journal.path(case.args.operation_id).read_bytes()
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    assert case.journal.path(case.args.operation_id).read_bytes() == before
    _assert_preserved(case)


def test_partial_journal_write_recovers_under_new_interface_claim(
        preaccept_home, monkeypatch):
    case = preaccept_home
    original_save = fleet.save_registry
    def fail_once(_data):
        raise OSError("registry write failed after journal transition")
    monkeypatch.setattr(fleet, "save_registry", fail_once)
    with pytest.raises(OSError, match="registry write failed"):
        fleet.cmd_codex_settle_preaccept(case.args)
    assert case.journal.load(case.args.operation_id)["state"] == "failed"
    assert fleet.read_registry_no_repair()["workers"][case.name] == case.row
    monkeypatch.setattr(fleet, "save_registry", original_save)
    case.source["claim_id"] = "claim-2"
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    assert fleet.read_registry_no_repair()["workers"][case.name]["status"] == "dead"
    _assert_preserved(case)


@pytest.mark.parametrize("window", ["before-replace", "after-replace"])
def test_journal_write_failure_window_is_recoverable(
        preaccept_home, monkeypatch, window):
    case = preaccept_home
    original_replace = os.replace
    original_fsync = os.fsync
    target = case.journal.path(case.args.operation_id)
    if window == "before-replace":
        def fail_replace(src, dst):
            if Path(dst) == target:
                raise OSError("journal replace failed")
            return original_replace(src, dst)
        monkeypatch.setattr(os, "replace", fail_replace)
    else:
        def fail_directory_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("journal directory sync failed")
            return original_fsync(fd)
        monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError):
        fleet.cmd_codex_settle_preaccept(case.args)
    assert fleet.read_registry_no_repair()["workers"][case.name] == case.row
    assert case.journal.load(case.args.operation_id)["state"] == (
        "prepared" if window == "before-replace" else "failed")
    assert not list(target.parent.glob(f".{target.stem}.preaccept.*.tmp"))
    monkeypatch.setattr(os, "replace", original_replace)
    monkeypatch.setattr(os, "fsync", original_fsync)
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    _assert_preserved(case)


def test_fresh_unrelated_registry_progress_is_retained(preaccept_home, monkeypatch):
    case = preaccept_home
    data = fleet.read_registry_no_repair()
    data["workers"]["sibling"]["status"] = "idle"
    data["workers"]["sibling"]["last_activity"] = "new activity"
    fleet.save_registry(data)
    case.sibling = dict(data["workers"]["sibling"])
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    _assert_preserved(case)
    monkeypatch.setattr(fleet, "_codex_worker_binding",
                        lambda *_a, **_kw: pytest.fail("terminal row was probed"))
    terminal = fleet.read_registry_no_repair()["workers"][case.name]
    assert fleet.recompute_worker_codex(case.name, terminal) == terminal


def test_cli_exposes_exact_supported_method():
    args = fleet.build_parser().parse_args([
        "codex-settle-preaccept", "root-worker", "operation-id",
        "generation", "--evidence", "/audit/evidence.json",
        "--expect-evidence-sha256", "a" * 64])
    assert args.command == "codex-settle-preaccept"
    assert args.name == "root-worker"


@pytest.mark.parametrize("kind", [
    "no-auth", "row-drift", "accepted-journal", "uncertain-journal",
    "another-prepared", "callback-unknown", "host-drift", "wrong-source",
    "wrong-digest", "wrong-evidence-mode", "non-explicit-home",
    "supervisor-claim", "same-worker-intent", "accepted-marker-failed",
    "provenance-drift", "report-drift", "provenance-symlink",
    "host-process-drift", "child-process-drift", "unknown-operation-entry",
    "target-mail", "target-claimed-mail", "ownerless-terminal",
])
def test_ambiguity_refuses_without_target_write(preaccept_home, monkeypatch, kind):
    case = preaccept_home
    if kind == "no-auth":
        monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    elif kind == "row-drift":
        data = fleet.read_registry_no_repair()
        data["workers"][case.name]["task"] = "changed"
        fleet.save_registry(data)
    elif kind in {"accepted-journal", "uncertain-journal"}:
        record = case.journal.load(case.args.operation_id)
        record["state"] = kind.split("-")[0]
        record["accepted_at"] = 1.0
        fleet_codex._atomic_json(case.journal.path(case.args.operation_id), record)
    elif kind == "another-prepared":
        case.journal.prepare({"operation_id": "unrelated-prepared", "method": "rpc",
                              "payload": {"method": "thread/start", "params": {}},
                              "recovery": {"kind": "thread/start", "fleet_name": "other"}})
    elif kind == "callback-unknown":
        callbacks = case.home / "state" / "codex" / "approvals"
        fleet_codex._atomic_json(callbacks / "unknown.json", {"state": "unknown"})
    elif kind == "host-drift":
        host_path = case.home / "state" / "codex" / "host.json"
        host = fleet_codex._read_json(host_path)
        host["generation"] = "different-generation"
        fleet_codex._atomic_json(host_path, host)
    elif kind == "wrong-source":
        case.evidence["source"]["host_sha256"] = "f" * 64
        case.evidence_path.write_text(json.dumps(case.evidence), encoding="utf-8")
        case.args.expect_evidence_sha256 = hashlib.sha256(
            case.evidence_path.read_bytes()).hexdigest()
    elif kind == "wrong-digest":
        case.evidence["payload_digest"] = "f" * 64
        case.evidence["rejection"]["payload_digest"] = "f" * 64
        case.evidence_path.write_text(json.dumps(case.evidence), encoding="utf-8")
        case.args.expect_evidence_sha256 = hashlib.sha256(
            case.evidence_path.read_bytes()).hexdigest()
    elif kind == "wrong-evidence-mode":
        case.evidence_path.chmod(0o644)
    elif kind == "non-explicit-home":
        case.args._fleet_home_explicit = False
    elif kind == "supervisor-claim":
        fleet._write_json_atomic(fleet.incarnation_path(), {"state": "held"})
    elif kind == "same-worker-intent":
        case.journal.prepare({
            "operation_id": "another-target-intent", "method": "rpc",
            "payload": {"method": "thread/start", "params": {}},
            "recovery": {"kind": "thread/start", "fleet_name": case.name}})
        case.journal.fail("another-target-intent", "before acceptance")
    elif kind == "accepted-marker-failed":
        site = case.journal.load(case.site_operation)
        site["accepted_at"] = 1.0
        fleet_codex._atomic_json(case.journal.path(case.site_operation), site)
        case.site_bytes = case.journal.path(case.site_operation).read_bytes()
    elif kind == "provenance-drift":
        case.provenance_path.write_text("changed\n", encoding="utf-8")
    elif kind == "report-drift":
        case.report_path.write_text("changed\n", encoding="utf-8")
    elif kind == "provenance-symlink":
        case.provenance_path.unlink()
        case.provenance_path.symlink_to(case.report_path)
    elif kind == "host-process-drift":
        monkeypatch.setattr(fleet_codex, "_process_identity", lambda _pid: None)
    elif kind == "child-process-drift":
        monkeypatch.setattr(fleet_codex, "_process_identity", lambda pid: (
            "fake-host-start" if pid == os.getpid() else "different-child"))
    elif kind == "unknown-operation-entry":
        (case.journal.directory / "unindexed-entry").write_text("unknown\n")
    elif kind == "target-mail":
        (case.home / "mailbox" / f"{case.name}.md").write_text("new target mail\n")
    elif kind == "target-claimed-mail":
        (case.home / "mailbox" / f"{case.name}.md.claimed.123").write_text(
            "unconsumed claimed mail\n")
    elif kind == "ownerless-terminal":
        other = "other-failed-unknown-owner"
        case.journal.prepare({"operation_id": other, "method": "rpc",
                              "payload": {"method": "thread/start", "params": {}},
                              "recovery": {"kind": "thread/start",
                                           "fleet_name": "sibling"}})
        case.journal.fail(other, "before acceptance")
        record = case.journal.load(other)
        record["recovery"] = None
        fleet_codex._atomic_json(case.journal.path(other), record)
    target_before = case.journal.path(case.args.operation_id).read_bytes()
    row_before = fleet.read_registry_no_repair()["workers"][case.name]
    with pytest.raises((fleet.FleetCliError, fleet_codex.UnsafeHostState)):
        fleet.cmd_codex_settle_preaccept(case.args)
    assert case.journal.path(case.args.operation_id).read_bytes() == target_before
    assert fleet.read_registry_no_repair()["workers"][case.name] == row_before
    _assert_preserved(case)


def test_journal_drift_after_inventory_refuses_before_transition(
        preaccept_home, monkeypatch):
    case = preaccept_home
    original_records = fleet_codex.OperationJournal.records
    def drift_after_inventory(self):
        records = original_records(self)
        if self.home == case.home:
            current = self.load(case.args.operation_id)
            current["state"] = "accepted"
            current["accepted_at"] = time.time()
            fleet_codex._atomic_json(self.path(case.args.operation_id), current)
        return records
    monkeypatch.setattr(fleet_codex.OperationJournal, "records", drift_after_inventory)
    with pytest.raises(fleet.FleetCliError, match="changed before settlement"):
        fleet.cmd_codex_settle_preaccept(case.args)
    assert case.journal.load(case.args.operation_id)["state"] == "accepted"
    assert fleet.read_registry_no_repair()["workers"][case.name] == case.row
    _assert_preserved(case)


@pytest.mark.parametrize("window", ["before-journal", "after-journal"])
def test_delayed_live_lock_owner_cannot_be_stale_broken_through_both_writes(
        preaccept_home, monkeypatch, window):
    case = preaccept_home
    monkeypatch.setattr(fleet, "LOCK_STALE_SECONDS", 0.03)
    entered = threading.Event()
    release = threading.Event()
    errors = []
    if window == "before-journal":
        original = fleet_codex.OperationJournal.records

        def paused(self):
            records = original(self)
            if self.home == case.home:
                entered.set()
                assert release.wait(3), "review pause expired"
            return records

        monkeypatch.setattr(fleet_codex.OperationJournal, "records", paused)
    else:
        original = fleet._codex_preaccept_write_failed

        def paused(path, value):
            original(path, value)
            entered.set()
            assert release.wait(3), "review pause expired"

        monkeypatch.setattr(fleet, "_codex_preaccept_write_failed", paused)

    def first():
        try:
            fleet.cmd_codex_settle_preaccept(case.args)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert entered.wait(3), "settlement did not reach delayed window"
        time.sleep(0.07)
        with pytest.raises(fleet.FleetLockTimeout):
            with fleet.fleet_lock(timeout=0.15):
                pytest.fail("second owner entered through a stale live lock")
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert not errors
    assert fleet.read_registry_no_repair()["workers"][case.name]["status"] == "dead"
    _assert_preserved(case)


def test_aged_legacy_live_owner_token_is_not_broken(preaccept_home):
    path = fleet.lock_path()
    path.write_text(f"{os.getpid()}:legacy-nonce", encoding="ascii")
    old = time.time() - 60
    os.utime(path, (old, old))
    try:
        with pytest.raises(fleet.FleetLockTimeout):
            with fleet.fleet_lock(timeout=0.12):
                pytest.fail("legacy live owner was stale-broken")
    finally:
        path.unlink()


def test_aged_modern_dead_owner_token_is_recoverable(preaccept_home):
    path = fleet.lock_path()
    path.write_text("999999999|dead-start|nonce", encoding="ascii")
    old = time.time() - 60
    os.utime(path, (old, old))
    with fleet.fleet_lock(timeout=0.5):
        assert path.exists()
    assert not path.exists()


def test_target_mail_arriving_after_journal_write_preserves_partial_recovery(
        preaccept_home, monkeypatch):
    case = preaccept_home
    mail = case.home / "mailbox" / f"{case.name}.md"
    original = fleet._codex_preaccept_write_failed

    def write_then_deliver(path, value):
        original(path, value)
        mail.write_text("new target instruction\n", encoding="utf-8")

    monkeypatch.setattr(fleet, "_codex_preaccept_write_failed", write_then_deliver)
    with pytest.raises(fleet.FleetCliError, match="target mail appeared after journal"):
        fleet.cmd_codex_settle_preaccept(case.args)
    assert case.journal.load(case.args.operation_id)["state"] == "failed"
    assert fleet.read_registry_no_repair()["workers"][case.name] == case.row
    assert mail.read_text(encoding="utf-8") == "new target instruction\n"
    _assert_preserved(case)

    monkeypatch.setattr(fleet, "_codex_preaccept_write_failed", original)
    mail.unlink()
    assert fleet.cmd_codex_settle_preaccept(case.args) == 0
    _assert_preserved(case)
