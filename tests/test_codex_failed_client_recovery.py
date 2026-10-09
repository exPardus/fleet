"""Bounded failed-client recovery: durable stages, exact CAS and host fence."""
import copy
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
import fleet_codex
import fleet_codex_failed_client_recovery as recovery
from fleet_errors import FleetCliError
from test_codex_host_ipc import _ensure, _shutdown


class FakeFleet:
    def __init__(self, home, row, claim):
        self.FLEET_HOME = home
        self.rows = {"sup|inc|boot": copy.deepcopy(row)}
        self.claim = copy.deepcopy(claim)
        self.saves = 0

    def read_registry_no_repair(self):
        return {"workers": copy.deepcopy(self.rows)}

    def read_incarnation(self):
        return copy.deepcopy(self.claim)

    def save_registry(self, data):
        self.rows = copy.deepcopy(data["workers"])
        self.saves += 1

    def write_incarnation(self, value):
        self.claim = copy.deepcopy(value)

    def fleet_lock(self):
        return nullcontext()

    def _codex_recovery_interface_source(self):
        return {"kind": "codex", "claim_id": "real-fixture"}

    _codex_model_slug = staticmethod(fleet._codex_model_slug)
    _codex_permission_profile = staticmethod(fleet._codex_permission_profile)
    _validate_codex_thread_effective = staticmethod(fleet._validate_codex_thread_effective)


@pytest.fixture
def staged(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "state" / "codex" / "operations").mkdir(parents=True)
    (home / "supervisor").mkdir()
    (home / "mailbox").mkdir()
    (home / "supervisor" / "JOURNAL.md").write_text("original journal\n")
    cwd = tmp_path / "owned"
    cwd.mkdir()
    thread, turn, generation = "thread-1", "turn-1", "old-generation"
    row = {"codex_host_generation": generation, "codex_thread_id": thread,
           "codex_turn_id": turn, "cwd": str(cwd), "model": "codex:gpt-6.1-sol",
           "mode": "bypass", "status": "working", "adapter_state": "working",
           "permission_effective": {"approvalPolicy": "never",
                                    "approvalsReviewer": "user",
                                    "sandbox": {"type": "dangerFullAccess"}}}
    claim = {"state": "held", "incarnation_id": "inc", "host_generation": generation,
             "holder": {"thread_id": thread}, "current_turn_id": turn,
             "pending_operation": None}
    old_host = {"generation": generation, "pid": 101, "process_identity": "host-start",
                "app_server_pid": 102, "app_server_process_identity": "child-start",
                "codex_version": "0.155.1", "schema_digest": "schema"}
    (home / "state" / "codex" / "host.json").write_text(json.dumps(old_host))
    operation = {"operation_id": "old-op", "home": str(home),
                 "generation": generation, "state": "committed"}
    (home / "state" / "codex" / "operations" / "old-op.json").write_text(
        json.dumps(operation))
    (home / "mailbox" / f"{thread}.md").write_text("retained mail\n")
    executable = tmp_path / "codex-0.155.1"
    executable.write_text("#!/bin/sh\nprintf 'codex-cli 0.155.1\\n'\n")
    executable.chmod(0o700)
    fake = FakeFleet(home, row, claim)
    monkeypatch.setattr(recovery, "_source_identity", lambda: {"head": "reviewed"})
    monkeypatch.setattr(recovery, "_git", lambda _cwd, *args: (
        "head" if args[-1] == "HEAD" else ""))
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "live")
    monkeypatch.setattr(recovery, "_descendants", lambda _pid: {})

    class OldClient:
        metadata_path = home / "state" / "codex" / "host.json"
        calls = []

        def call(self, operation, timeout):
            self.calls.append(operation)
            return SimpleNamespace(generation=self.generation,
                                   result={"stopping": True})

        def _metadata_stale(self):
            return True

    old = OldClient()
    old.generation = generation
    monkeypatch.setattr(recovery.CodexHostClient, "connect_existing",
                        lambda _home: old)
    args = SimpleNamespace(_fleet_home_explicit=True, generation=generation,
                           host_pid=101, host_start="host-start", child_pid=102,
                           child_start="child-start", incarnation="inc",
                           thread=thread, turn=turn,
                           codex_executable=str(executable), decision_file=None,
                           name="sup|inc|boot")
    return fake, args, old


def _prepared(staged):
    fake, args, old = staged
    recovery._prepare(fake, args)
    return fake, args, old, recovery._load(fake)


def test_prepare_captures_exact_evidence_without_provider_write(staged):
    fake, _, old, record = _prepared(staged)
    assert old.calls == []
    assert record["state"] == "prepared"
    assert record["original_journals"] == {"all_committed": 1,
                                            "original_generation": 1}
    assert record["evidence"]["mail"] == recovery._directory_digest(
        fake.FLEET_HOME / "mailbox", prefixes=("thread-1",))


@pytest.mark.parametrize("changed", ["claim", "row", "mail", "journal", "approval"])
def test_pre_shutdown_evidence_change_refuses_without_provider_write(staged, changed):
    fake, _, old, record = _prepared(staged)
    if changed == "claim":
        fake.claim["extra"] = 1
    elif changed == "row":
        fake.rows["sup|inc|boot"]["status"] = "idle"
    elif changed == "mail":
        (fake.FLEET_HOME / "mailbox" / "thread-1.md").write_text("changed\n")
    elif changed == "journal":
        (fake.FLEET_HOME / "supervisor" / "JOURNAL.md").write_text("changed\n")
    else:
        directory = fake.FLEET_HOME / "state" / "codex" / "approvals"
        directory.mkdir()
        (directory / "new.json").write_text("{}")
    with pytest.raises(FleetCliError, match="changed"):
        recovery._compare(fake, record)
    assert old.calls == []


def test_unresolved_journal_or_callback_refuses_before_barrier(staged):
    fake, args, _, _ = _prepared(staged)
    (fake.FLEET_HOME / "state" / "codex" / recovery.BARRIER).unlink()
    path = fake.FLEET_HOME / "state" / "codex" / "operations" / "old-op.json"
    entry = json.loads(path.read_text())
    entry["state"] = "accepted"
    path.write_text(json.dumps(entry))
    with pytest.raises(FleetCliError, match="unresolved"):
        recovery._prepare(fake, args)
    entry["state"] = "committed"
    path.write_text(json.dumps(entry))
    approvals = fake.FLEET_HOME / "state" / "codex" / "approvals"
    approvals.mkdir()
    (approvals / "callback.json").write_text(json.dumps({
        "home": str(fake.FLEET_HOME), "key": "callback",
        "generation": args.generation, "state": "pending"}))
    with pytest.raises(FleetCliError, match="callback"):
        recovery._prepare(fake, args)
    assert not (fake.FLEET_HOME / "state" / "codex" / recovery.BARRIER).exists()


def test_decision_receipt_is_required_and_bound_to_exact_intent(staged, tmp_path):
    fake, args, old, record = _prepared(staged)
    with pytest.raises(FleetCliError, match="decision"):
        recovery._decision(fake, args, record)
    path = tmp_path / "decision.json"
    args.decision_file = str(path)
    receipt = {"recovery_id": record["id"], "home": record["home"],
               "old_generation": record["old_host"]["generation"],
               "authority": "founder", "decision": "accept-controlled-interruption",
               "consequence": recovery.LOSS_TEXT}
    path.write_text(json.dumps(dict(receipt, recovery_id="wrong")))
    with pytest.raises(FleetCliError, match="mismatched"):
        recovery._decision(fake, args, record)
    path.write_text(json.dumps(receipt))
    recovery._decision(fake, args, record)
    assert recovery._load(fake)["state"] == "authorized"
    assert old.calls == []


def test_shutdown_is_one_shot_even_when_reply_is_lost(staged, tmp_path):
    fake, args, old, record = _prepared(staged)
    path = tmp_path / "decision.json"
    path.write_text(json.dumps({"recovery_id": record["id"], "home": record["home"],
        "old_generation": args.generation, "authority": "founder",
        "decision": "accept-controlled-interruption", "consequence": recovery.LOSS_TEXT}))
    args.decision_file = str(path)
    recovery._decision(fake, args, record)
    def lost(operation, timeout):
        old.calls.append(operation)
        raise TimeoutError("lost reply")
    old.call = lost
    with pytest.raises(FleetCliError, match="never resend"):
        recovery._shutdown(fake, record)
    assert len(old.calls) == 1
    assert recovery._load(fake)["state"] == "shutdown_sent"
    with pytest.raises(FleetCliError, match="decision"):
        recovery._shutdown(fake, recovery._load(fake))
    assert len(old.calls) == 1


def test_exit_requires_exact_absence_and_no_surviving_descendant(staged, monkeypatch):
    fake, _, _, record = _prepared(staged)
    record["state"] = "shutdown_sent"
    recovery._save(fake, record)
    with pytest.raises(FleetCliError, match="live"):
        recovery._exit(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "absent")
    record["descendants"] = {"103": "descendant-start"}
    recovery._save(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda pid, _identity:
                        "live" if pid == 103 else "absent")
    with pytest.raises(FleetCliError, match="descendant"):
        recovery._exit(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "reused")
    with pytest.raises(FleetCliError, match="reused"):
        recovery._exit(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "absent")
    recovery._exit(fake, record)
    assert recovery._load(fake)["state"] == "exited"


def test_rebind_lost_reply_is_staged_once_with_same_thread_policy(staged, monkeypatch):
    fake, args, old, record = _prepared(staged)
    record["state"] = "rebind"
    record["new_generation"] = "new-generation"
    recovery._save(fake, record)
    old.generation = "new-generation"
    monkeypatch.setattr(recovery, "_complete_history", lambda *_: {
        "thread_status": "notLoaded", "bound_turn_status": "interrupted", "turn_count": 1})
    def lost(operation, timeout):
        old.calls.append(operation)
        raise TimeoutError("lost resume")
    old.call = lost
    with pytest.raises(FleetCliError, match="never replayed"):
        recovery._rebind(fake, args, record)
    assert len(old.calls) == 1
    operation = old.calls[0]
    assert operation["payload"]["method"] == "thread/resume"
    params = operation["payload"]["params"]
    assert params["threadId"] == "thread-1" and params["excludeTurns"] is True
    assert params["approvalPolicy"] == "never" and params["sandbox"] == "danger-full-access"
    with pytest.raises(FleetCliError, match="unresolved"):
        recovery._rebind(fake, args, recovery._load(fake))
    assert len(old.calls) == 1 and fake.saves == 0


def test_rebind_refuses_recorded_policy_or_claim_drift_before_resume(staged, monkeypatch):
    fake, args, old, record = _prepared(staged)
    record["state"] = "rebind"
    record["new_generation"] = "new-generation"
    old.generation = "new-generation"
    recovery._save(fake, record)
    monkeypatch.setattr(recovery, "_complete_history", lambda *_: {
        "thread_status": "notLoaded", "bound_turn_status": "interrupted", "turn_count": 1})
    fake.claim["other"] = "drift"
    with pytest.raises(FleetCliError, match="claim changed"):
        recovery._rebind(fake, args, record)
    fake.claim.pop("other")
    fake.rows["sup|inc|boot"]["permission_effective"]["approvalPolicy"] = "on-request"
    record["evidence"]["rows"]["sup|inc|boot"] = recovery._sha(
        fake.rows["sup|inc|boot"])
    with pytest.raises(FleetCliError, match="effective policy"):
        recovery._rebind(fake, args, record)
    assert old.calls == []


def test_workspace_write_recorded_policy_preserves_full_effective_shape(staged):
    fake, _, _, _ = _prepared(staged)
    row = fake.rows["sup|inc|boot"]
    row["mode"] = "dontask"
    row["permission_effective"]["sandbox"] = {
        "type": "workspaceWrite", "writableRoots": ["/tmp/owned"],
        "networkAccess": False, "excludeTmpdirEnvVar": False,
        "excludeSlashTmp": False}
    model, profile = recovery._row_policy(fake, row)
    assert model == "gpt-6.1-sol"
    assert profile == {"approvalPolicy": "never", "sandbox": "workspace-write"}
    response = copy.deepcopy(row["permission_effective"])
    recovery._require_recorded_effective(response, row)
    response["sandbox"]["writableRoots"] = ["/tmp/other"]
    with pytest.raises(FleetCliError, match="exact recorded"):
        recovery._require_recorded_effective(response, row)


@pytest.mark.parametrize("fault", [None, "cursor", "newest", "status", "items"])
def test_complete_history_pages_and_refuses_incomplete_views(staged, monkeypatch, fault):
    fake, _, _, _ = _prepared(staged)
    cwd = fake.rows["sup|inc|boot"]["cwd"]

    class Reads:
        calls = []
        generation = "new-generation"

        def call(self, operation, timeout):
            method = operation["payload"]["method"]
            params = operation["payload"]["params"]
            self.calls.append((method, params))
            if method == "thread/read":
                result = {"thread": {"id": "thread-1", "cwd": cwd,
                                     "status": {"type": "notLoaded", "activeFlags": []}}}
            elif params.get("cursor") == "next":
                result = {"data": [{"id": "turn-0", "status": "completed"}],
                          "nextCursor": "next" if fault == "cursor" else None}
            else:
                result = {"data": [{"id": "other" if fault == "newest" else "turn-1",
                                    "status": "inProgress" if fault == "status"
                                    else "interrupted"}], "nextCursor": "next"}
            return SimpleNamespace(result=result)

    class Hydrate:
        @staticmethod
        def _codex_paged_thread_read(*_args, **_kwargs):
            return SimpleNamespace(result={"thread": {"turns": [{
                "id": "turn-1", "status": "interrupted",
                "itemsView": "notLoaded" if fault == "items" else "full"}]}})

    if fault is None:
        assert recovery._complete_history(Hydrate, Reads(), "thread-1", "turn-1", cwd) == {
            "thread_status": "notLoaded", "bound_turn_status": "interrupted",
            "turn_count": 2}
    else:
        with pytest.raises(FleetCliError):
            recovery._complete_history(Hydrate, Reads(), "thread-1", "turn-1", cwd)


def test_partial_claim_write_keeps_barrier_then_settles_without_resume(staged, monkeypatch):
    fake, _, old, record = _prepared(staged)
    record.update({"state": "rebind", "new_generation": "new-generation",
                   "current_operation": "resume-1", "current_name": "sup|inc|boot",
                   "current_thread": "thread-1", "current_payload_digest": "a" * 64,
                   "current_row": copy.deepcopy(fake.rows["sup|inc|boot"]),
                   "current_claim": copy.deepcopy(fake.claim),
                   "resume_operations": {"sup|inc|boot": "resume-1"}})
    recovery._save(fake, record)
    old.generation = "new-generation"
    result = {"thread": {"id": "thread-1", "cwd": fake.rows["sup|inc|boot"]["cwd"]},
              "cwd": fake.rows["sup|inc|boot"]["cwd"], "model": "gpt-6.1-sol",
              "approvalPolicy": "never", "approvalsReviewer": "user",
              "sandbox": {"type": "dangerFullAccess"}}

    class Journal:
        digest = "a" * 64

        def __init__(self, *_args):
            pass

        def load(self, _operation_id):
            return {"state": "observed", "result": result,
                    "home": str(fake.FLEET_HOME), "generation": "new-generation",
                    "operation_id": "resume-1", "method": "rpc",
                    "public_method": "thread/resume", "payload_digest": self.digest,
                    "recovery": {"kind": "failed-client/thread-resume",
                                 "recovery_id": record["id"],
                                 "fleet_name": "sup|inc|boot",
                                 "thread_id": "thread-1", "bound_turn_id": "turn-1",
                                 "previous_host_generation": "old-generation",
                                 "canonical_cwd": fake.rows["sup|inc|boot"]["cwd"]}}

        def commit(self, _operation_id):
            pass

    monkeypatch.setattr(recovery, "OperationJournal", Journal)
    monkeypatch.setattr(recovery, "_complete_history", lambda *_: {
        "thread_status": "idle", "bound_turn_status": "interrupted", "turn_count": 1})
    Journal.digest = "b" * 64
    with pytest.raises(FleetCliError, match="staged exact intent"):
        recovery._settle_rebind(fake, record)
    assert fake.claim["host_generation"] == "old-generation"
    Journal.digest = "a" * 64
    original_save = fake.save_registry
    def fail_once(_data):
        raise OSError("simulated registry save failure")
    fake.save_registry = fail_once
    with pytest.raises(OSError, match="simulated"):
        recovery._settle_rebind(fake, record)
    assert fake.claim["host_generation"] == "new-generation"
    assert fake.rows["sup|inc|boot"]["codex_host_generation"] == "old-generation"
    assert recovery._load(fake)["current_operation"] == "resume-1"
    fake.save_registry = original_save
    recovery._settle_rebind(fake, recovery._load(fake))
    assert fake.rows["sup|inc|boot"]["codex_host_generation"] == "new-generation"
    assert recovery._load(fake)["current_operation"] is None
    assert old.calls == []


def test_boot_refuses_live_old_child_and_journal_drift(staged, monkeypatch):
    fake, _, _, record = _prepared(staged)
    record["state"] = "exited"
    recovery._save(fake, record)
    launches = []
    monkeypatch.setattr(recovery.CodexHostClient, "ensure",
                        lambda _home: launches.append("launched"))
    with pytest.raises(FleetCliError, match="live"):
        recovery._boot(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "absent")
    path = fake.FLEET_HOME / "state" / "codex" / "operations" / "old-op.json"
    entry = json.loads(path.read_text())
    entry["state"] = "accepted"
    path.write_text(json.dumps(entry))
    with pytest.raises(FleetCliError, match="changed"):
        recovery._boot(fake, record)
    assert launches == []


def test_boot_refuses_changed_pinned_executable_before_launch(staged, monkeypatch):
    fake, _, _, record = _prepared(staged)
    record["state"] = "exited"
    recovery._save(fake, record)
    monkeypatch.setattr(recovery, "_process_state", lambda *_: "absent")
    launches = []
    monkeypatch.setattr(recovery.CodexHostClient, "ensure",
                        lambda *_args, **_kwargs: launches.append("launched"))
    Path(record["codex_executable"]["path"]).write_text(
        "#!/bin/sh\nprintf 'codex-cli 0.161.0\\n'\n")
    with pytest.raises(FleetCliError, match="version differs"):
        recovery._boot(fake, record)
    assert launches == []


def test_real_host_barrier_rejects_before_provider_write(tmp_path):
    _, client, log = _ensure(tmp_path)
    barrier = client.home / "state" / "codex" / recovery.BARRIER
    try:
        fleet_codex._atomic_json(barrier, {"schema": 1, "home": str(client.home),
            "state": "prepared", "old_host": {"generation": client.generation}})
        with pytest.raises(fleet_codex.HostRejected, match="barrier"):
            client.call({"operation_id": "blocked-start", "method": "rpc",
                "payload": {"method": "thread/start", "params": {
                    "cwd": str(client.home)}}}, timeout=2)
        assert not (client.home / "state" / "codex" / "operations" /
                    "blocked-start.json").exists()
        assert all(json.loads(line).get("method") != "thread/start"
                   for line in log.read_text().splitlines())
    finally:
        _shutdown(client)


def test_staged_host_gate_binds_full_resume_payload_and_exact_interface(staged, monkeypatch):
    import fleet_codex_host as host_module

    fake, _, _, record = _prepared(staged)
    record.update({"state": "rebind", "new_generation": "new-generation",
                   "current_operation": "resume-1", "current_thread": "thread-1",
                   "current_payload_digest": "a" * 64})
    recovery._save(fake, record)
    gate = fleet_codex.authorize_failed_client_recovery_operation
    gate(fake.FLEET_HOME, "new-generation", "resume-1", "thread/resume",
         "thread-1", "a" * 64)
    for generation, operation, thread, digest in (
            ("wrong", "resume-1", "thread-1", "a" * 64),
            ("new-generation", "wrong", "thread-1", "a" * 64),
            ("new-generation", "resume-1", "wrong", "a" * 64),
            ("new-generation", "resume-1", "thread-1", "b" * 64)):
        with pytest.raises(fleet_codex.HostRejected, match="barrier"):
            gate(fake.FLEET_HOME, generation, operation, "thread/resume", thread, digest)

    host = host_module.Host.__new__(host_module.Host)
    host.home = fake.FLEET_HOME
    claim = {"thread_id": "interface-thread", "uid": 1000,
             "ancestor_pid": 41, "ancestor_start_identity": "100"}
    monkeypatch.setattr(host_module, "read_interface_claim", lambda _home: claim)
    monkeypatch.setattr(host_module, "_ipc_peer_credentials", lambda _connection: (99, 1000))
    monkeypatch.setattr(host_module.os, "getuid", lambda: 1000)
    source = dict(claim)
    monkeypatch.setattr(host_module, "codex_process_source", lambda _pid: source)
    host._authorize_failed_client_interface(object())
    source = dict(source, ancestor_start_identity="101")
    with pytest.raises(fleet_codex.HostRejected, match="exact Interface peer"):
        host._authorize_failed_client_interface(object())


def test_source_contract_rejects_missing_genuine_interface(tmp_path, monkeypatch):
    fake = SimpleNamespace(_codex_recovery_interface_source=lambda:
                           fleet._codex_recovery_interface_source())
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    with pytest.raises(FleetCliError, match="authenticated Codex Interface"):
        recovery._source_and_caller(fake, SimpleNamespace(_fleet_home_explicit=True))
    with pytest.raises(FleetCliError, match="explicit --fleet-home"):
        recovery._source_and_caller(fake, SimpleNamespace(_fleet_home_explicit=False))


def test_cli_prepare_refuses_unregistered_source_before_barrier(staged, monkeypatch):
    fake, args, old = staged
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    code = fleet.main([
        "codex-recover-failed-client", "prepare", "--fleet-home", str(fake.FLEET_HOME),
        "--generation", args.generation, "--host-pid", str(args.host_pid),
        "--host-start", args.host_start, "--child-pid", str(args.child_pid),
        "--child-start", args.child_start, "--incarnation", args.incarnation,
        "--thread", args.thread, "--turn", args.turn,
        "--codex-executable", args.codex_executable])
    assert code != 0
    assert not (fake.FLEET_HOME / "state" / "codex" / recovery.BARRIER).exists()
    assert old.calls == []
