"""Bounded failed-client recovery: durable stages, exact CAS and host fence."""
import copy
import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

import fleet
import fleet_codex
import fleet_codex_failed_client_recovery as recovery
from fleet_errors import FleetCliError
from test_codex_host_ipc import _ensure, _envelope, _raw_call, _shutdown


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


_FAKE_LIFECYCLE_APP = r'''#!__PYTHON__
import json
import os
from pathlib import Path
import subprocess
import sys

REAL_SCHEMA_BINARY = __REAL_SCHEMA_BINARY__
if sys.argv[1:] == ["--version"]:
    print("codex-cli 0.155.1")
    raise SystemExit(0)
if sys.argv[1:3] == ["app-server", "generate-json-schema"]:
    raise SystemExit(subprocess.call([REAL_SCHEMA_BINARY, *sys.argv[1:]]))
if sys.argv[1:] != ["app-server", "--listen", "stdio://"]:
    raise SystemExit(2)

state_path = Path(os.environ["FAKE_LIFECYCLE_STATE"])
log_path = Path(os.environ["FAKE_LIFECYCLE_LOG"])
with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"event": "started", "pid": os.getpid()}) + "\n")

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

first = json.loads(sys.stdin.readline())
send({"id": first["id"], "result": {"serverInfo": {
    "name": "fake-codex", "version": "0.155.1"}}})
if json.loads(sys.stdin.readline()) != {"method": "initialized"}:
    raise SystemExit(3)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    params = message.get("params", {})
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "request", "method": method,
                                 "params": params}) + "\n")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    thread_id = params.get("threadId")
    row = state.get(thread_id)
    if method == "thread/read":
        result = {"thread": {"id": thread_id, "cwd": row["cwd"],
                             "status": {"type": "idle" if row["resumed"]
                                        else "notLoaded", "activeFlags": []}}}
    elif method == "thread/turns/list":
        result = {"data": list(reversed(row["turns"])), "nextCursor": None}
    elif method == "thread/items/list":
        result = {"data": [], "nextCursor": None}
    elif method == "thread/resume":
        row["resumed"] = True
        state_path.write_text(json.dumps(state), encoding="utf-8")
        result = {"thread": {"id": thread_id, "cwd": row["cwd"]},
                  "cwd": row["cwd"], "model": params["model"],
                  "approvalPolicy": params["approvalPolicy"],
                  "approvalsReviewer": params["approvalsReviewer"],
                  "sandbox": {"type": "dangerFullAccess"}}
    elif method == "turn/start":
        turn = {"id": "018f22d3-9b4a-7cc3-8a0e-36d4f59106bb",
                "status": "inProgress"}
        row["turns"].append(turn)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        result = {"turn": turn}
    else:
        send({"id": message["id"], "error": {
            "code": -32601, "message": "unsupported fake method"}})
        continue
    send({"id": message["id"], "result": result})
'''


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


def test_workspace_resume_sends_all_recorded_policy_before_acceptance(staged, monkeypatch):
    fake, args, old = staged
    row = fake.rows["sup|inc|boot"]
    row["mode"] = "dontask"
    row["permission_effective"]["sandbox"] = {
        "type": "workspaceWrite", "writableRoots": [str(fake.FLEET_HOME)],
        "networkAccess": False, "excludeTmpdirEnvVar": True,
        "excludeSlashTmp": True}
    recovery._prepare(fake, args)
    record = recovery._load(fake)
    record.update({"state": "rebind", "new_generation": "new-generation"})
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
    params = old.calls[0]["payload"]["params"]
    assert params["sandbox"] == "workspace-write"
    assert params["config"] == {"sandbox_workspace_write": {
        "writable_roots": [str(fake.FLEET_HOME)],
        "network_access": False, "exclude_tmpdir_env_var": True,
        "exclude_slash_tmp": True}}


@pytest.mark.parametrize("network_access", [False, True])
def test_readonly_network_policy_accepts_shape_but_holds_unsupported_resume(
        staged, monkeypatch, network_access):
    fake, args, old = staged
    row = fake.rows["sup|inc|boot"]
    row["mode"] = "plan"
    row["permission_effective"]["sandbox"] = {
        "type": "readOnly", "networkAccess": network_access}
    model, profile = recovery._row_policy(fake, row)
    assert model == "gpt-6.1-sol" and profile["sandbox"] == "read-only"
    recovery._prepare(fake, args)
    record = recovery._load(fake)
    record.update({"state": "rebind", "new_generation": "new-generation"})
    recovery._save(fake, record)
    old.generation = "new-generation"
    monkeypatch.setattr(recovery, "_complete_history", lambda *_: {
        "thread_status": "notLoaded", "bound_turn_status": "interrupted", "turn_count": 1})
    if network_access:
        with pytest.raises(FleetCliError, match="cannot be restored"):
            recovery._rebind(fake, args, record)
        assert old.calls == []
        assert recovery._load(fake)["current_operation"] is None
    else:
        def lost(operation, timeout):
            old.calls.append(operation)
            raise TimeoutError("lost resume")
        old.call = lost
        with pytest.raises(FleetCliError, match="never replayed"):
            recovery._rebind(fake, args, record)
        assert len(old.calls) == 1
        assert old.calls[0]["payload"]["params"]["sandbox"] == "read-only"


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
        barrier.unlink(missing_ok=True)
        _shutdown(client)


@pytest.mark.parametrize("stage", ["prepared", "rebind", "complete"])
def test_real_host_fences_unclassified_public_mutations_and_shutdown(tmp_path, stage):
    _, client, log = _ensure(tmp_path)
    path = client.home / "state" / "codex" / recovery.BARRIER
    held = "thread-1"
    fleet_codex._atomic_json(path, {
        "schema": 1, "home": str(client.home), "state": stage,
        "old_host": {"generation": "old-generation"},
        "new_generation": client.generation,
        "current_operation": "reserved-resume", "current_thread": held,
        "current_payload_digest": "a" * 64, "held_threads": [held],
    })
    methods = {
        "thread/rollback": {"threadId": held, "numTurns": 1},
        "thread/fork": {"threadId": held},
        "thread/compact/start": {"threadId": held},
        "thread/archive": {"threadId": held},
        "thread/name/set": {"threadId": held, "name": "new-name"},
        "turn/steer": {"threadId": held, "expectedTurnId": "turn-1", "input": []},
    }
    try:
        for index, (method, params) in enumerate(methods.items()):
            response = _raw_call(client, _envelope(
                client, f"blocked-{index}", "rpc",
                {"method": method, "params": params}))
            assert response["ok"] is False, (stage, method, response)
            assert not (client.home / "state" / "codex" / "operations" /
                        f"blocked-{index}.json").exists()
        stopped = _raw_call(client, _envelope(
            client, "stale-stop", "host/shutdown"))
        assert stopped["ok"] is False
        assert client.call({"operation_id": "still-live", "method": "ping",
                            "payload": {}}, timeout=2).result["generation"] == client.generation
        delivered = [entry.get("method") for entry in map(
            json.loads, log.read_text().splitlines())
            if entry.get("event") == "request"]
        assert not set(methods).intersection(delivered)
    finally:
        path.unlink(missing_ok=True)
        _shutdown(client)


def test_rebind_read_overflow_holds_one_replacement_child(tmp_path, monkeypatch):
    import test_codex_host_ipc as host_tests

    needle = '    if message.get("method") == "test/echo":'
    overflow = (
        '    if message.get("method") == "thread/read":\n'
        '        import time\n'
        '        send({{"method": "thread/status/changed", "params": {{"seq": 1}}}})\n'
        '        send({{"method": "turn/started", "params": {{"seq": 2}}}})\n'
        '        time.sleep(0.05)\n'
        '        send({{"id": message["id"], "result": {{"thread": {{}}}}}})\n'
        '    elif message.get("method") == "test/echo":')
    monkeypatch.setattr(host_tests, "FAKE_APP_SERVER",
                        host_tests.FAKE_APP_SERVER.replace(needle, overflow))
    _, client, log = _ensure(
        tmp_path, env_overrides={"FLEET_CODEX_EVENT_QUEUE_MAX": "1"})
    path = client.home / "state" / "codex" / recovery.BARRIER
    barrier = {"schema": 1, "home": str(client.home), "state": "rebind",
               "old_host": {"generation": "old-generation"},
               "new_generation": client.generation,
               "rebound": ["already-rebound"], "current_operation": None,
               "held_threads": []}
    fleet_codex._atomic_json(path, barrier)
    metadata_before = client.metadata_path.read_bytes()
    try:
        with pytest.raises(fleet_codex.HostRejected, match="replacement child changed"):
            client.call({"operation_id": "later-history-read", "method": "rpc",
                         "payload": {"method": "thread/read", "params": {
                             "threadId": "later-thread", "includeTurns": False}}}, timeout=2)
        events = list(map(json.loads, log.read_text().splitlines()))
        assert [item["event"] for item in events].count("started") == 1
        assert [item.get("method") for item in events].count("thread/read") == 1
        assert client.metadata_path.read_bytes() == metadata_before
        assert recovery._load(SimpleNamespace(FLEET_HOME=client.home)) == barrier
    finally:
        path.unlink(missing_ok=True)
        _shutdown(client)


def test_complete_fake_host_recovery_lifecycle(tmp_path, monkeypatch):
    """Exercise every staged verb and one later turn without a model request."""
    pinned = Path("/usr/local/bin/codex")
    if not pinned.is_file() or pinned.stat().st_size == 0:
        pytest.skip("pinned local 0.155.1 schema generator is unavailable")
    home = (tmp_path / "home").resolve()
    state_dir = home / "state" / "codex"
    (state_dir / "operations").mkdir(parents=True)
    state_dir.chmod(0o700)
    (state_dir / "operations").chmod(0o700)
    (home / "supervisor").mkdir()
    (home / "mailbox").mkdir()
    (home / "supervisor" / "JOURNAL.md").write_text("original journal\n")
    supervisor_cwd = tmp_path / "supervisor-worktree"
    held_cwd = tmp_path / "held-worktree"
    supervisor_cwd.mkdir()
    held_cwd.mkdir()
    supervisor_thread = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
    supervisor_turn = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
    held_thread = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
    held_turn = "018f22d3-9b4a-7cc3-8a0e-36d4f59106ba"
    provider_state = tmp_path / "fake-provider-state.json"
    provider_log = tmp_path / "fake-provider-log.jsonl"
    provider_state.write_text(json.dumps({
        supervisor_thread: {"cwd": str(supervisor_cwd), "resumed": False,
                            "turns": [{"id": supervisor_turn, "status": "interrupted"}]},
        held_thread: {"cwd": str(held_cwd), "resumed": False,
                      "turns": [{"id": held_turn, "status": "completed"}]},
    }))
    executable = tmp_path / "fake-codex-0.155.1"
    executable.write_text(
        _FAKE_LIFECYCLE_APP.replace("__PYTHON__", str(Path(sys.executable).resolve()))
        .replace("__REAL_SCHEMA_BINARY__", repr(str(pinned))), encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setenv("FAKE_LIFECYCLE_STATE", str(provider_state))
    monkeypatch.setenv("FAKE_LIFECYCLE_LOG", str(provider_log))
    try:
        source = fleet_codex.codex_process_source(os.getpid())
    except fleet_codex.HostRejected:
        pytest.skip("whole-host authentication requires a genuine Codex ancestor")
    fleet_codex._atomic_json(home / "state" / "interface-codex.json", {
        "schema": 1, "home": str(home), "claim_id": str(uuid4()), **source})
    old_client = fleet_codex.CodexHostClient.ensure(
        home, app_server_command=[str(executable), "app-server", "--listen", "stdio://"],
        schema_command=[str(executable)], env=dict(os.environ), ready_timeout=20)
    new_client = None
    try:
        old_meta = json.loads(old_client.metadata_path.read_text())
        old_generation = old_client.generation
        row = {"codex_host_generation": old_generation,
               "codex_thread_id": supervisor_thread, "codex_turn_id": supervisor_turn,
               "cwd": str(supervisor_cwd), "model": "codex:gpt-6.1-sol",
               "mode": "bypass", "status": "working", "adapter_state": "working",
               "permission_effective": {"approvalPolicy": "never",
                   "approvalsReviewer": "user", "sandbox": {"type": "dangerFullAccess"}}}
        claim = {"state": "held", "incarnation_id": "inc",
                 "host_generation": old_generation,
                 "holder": {"thread_id": supervisor_thread},
                 "current_turn_id": supervisor_turn, "pending_operation": None}
        fake = FakeFleet(home, row, claim)
        fake.rows["held-worker"] = dict(row, codex_thread_id=held_thread,
                                         codex_turn_id=held_turn, cwd=str(held_cwd),
                                         status="dead", adapter_state="idle")
        mail = home / "mailbox" / (supervisor_thread + ".md")
        mail.write_bytes(b"retained original supervisor mail\n")
        fleet_codex._atomic_json(state_dir / "operations" / "old-op.json", {
            "operation_id": "old-op", "home": str(home),
            "generation": old_generation, "state": "committed"})
        monkeypatch.setattr(recovery, "_source_identity", lambda: {"head": "reviewed"})
        monkeypatch.setattr(recovery, "_git", lambda _cwd, *args:
                            "head" if args[-1] == "HEAD" else "")
        args = SimpleNamespace(_fleet_home_explicit=True, generation=old_generation,
            host_pid=old_meta["pid"], host_start=old_meta["process_identity"],
            child_pid=old_meta["app_server_pid"],
            child_start=old_meta["app_server_process_identity"],
            incarnation="inc", thread=supervisor_thread, turn=supervisor_turn,
            codex_executable=str(executable), decision_file=None,
            name="sup|inc|boot")
        recovery._prepare(fake, args)
        record = recovery._load(fake)
        assert record["state"] == "prepared" and old_client.generation == old_generation
        decision = tmp_path / "decision.json"
        decision.write_text(json.dumps({"recovery_id": record["id"],
            "home": str(home), "old_generation": old_generation,
            "authority": "founder", "decision": "accept-controlled-interruption",
            "consequence": recovery.LOSS_TEXT}))
        args.decision_file = str(decision)
        recovery._decision(fake, args, record)
        recovery._shutdown(fake, recovery._load(fake))
        assert recovery._load(fake)["state"] == "shutdown_ack"
        old_client._launched_process.wait(timeout=5)
        deadline = time.monotonic() + 6
        while True:
            try:
                recovery._exit(fake, recovery._load(fake))
                break
            except FleetCliError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        assert recovery._load(fake)["state"] == "exited"
        original_samefile = os.path.samefile
        monkeypatch.setattr(recovery.os.path, "samefile", lambda a, b: (
            True if str(a).endswith("/exe") and str(b) == str(executable)
            else original_samefile(a, b)))
        recovery._boot(fake, recovery._load(fake))
        record = recovery._load(fake)
        assert record["state"] == "rebind" and record["new_generation"] != old_generation
        new_client = fleet_codex.CodexHostClient.connect_existing(home)
        recovery._rebind(fake, args, record)
        args.name = "held-worker"
        recovery._rebind(fake, args, recovery._load(fake))
        assert recovery._load(fake)["held"] == ["held-worker"]
        recovery._finish(fake, recovery._load(fake))
        assert recovery._load(fake)["state"] == "complete"
        assert fake.rows["sup|inc|boot"]["codex_thread_id"] == supervisor_thread
        assert fake.rows["sup|inc|boot"]["codex_host_generation"] == new_client.generation
        assert fake.rows["held-worker"]["codex_host_generation"] == old_generation
        with pytest.raises(fleet_codex.HostRejected, match="held"):
            new_client.call({"operation_id": "held-turn", "method": "rpc",
                "payload": {"method": "turn/start", "params": {
                    "threadId": held_thread, "input": []}}}, timeout=2)
        new_client.call({"operation_id": "normal-next-turn", "method": "rpc",
            "payload": {"method": "turn/start", "params": {
                "threadId": supervisor_thread, "input": []}}}, timeout=2)
        new_client.commit("normal-next-turn")
        methods = [entry["method"] for entry in map(
            json.loads, provider_log.read_text().splitlines())
            if entry.get("event") == "request"]
        assert methods.count("thread/resume") == 1
        assert methods.count("turn/start") == 1
        assert "thread/start" not in methods
        assert mail.read_bytes() == b"retained original supervisor mail\n"
    finally:
        (state_dir / recovery.BARRIER).unlink(missing_ok=True)
        if new_client is not None:
            _shutdown(new_client)
        else:
            _shutdown(old_client)


def test_live_host_failed_reader_still_allows_metadata_prepare(staged, tmp_path,
                                                               monkeypatch):
    import test_codex_host_ipc as host_tests

    fake, args, _ = staged
    metadata_path = fake.FLEET_HOME / "state" / "codex" / "host.json"
    metadata_path.unlink()
    (fake.FLEET_HOME / "state" / "codex").chmod(0o700)
    (fake.FLEET_HOME / "state" / "codex" / "operations").chmod(0o700)
    (fake.FLEET_HOME / "state" / "codex" / "operations" / "old-op.json").chmod(0o600)
    needle = '    if message.get("method") == "test/echo":'
    replacement = (
        '    if message.get("method") == "test/fail":\n'
        '        sys.stdout.write("not-json\\n")\n'
        '        sys.stdout.flush()\n'
        '    elif message.get("method") == "test/echo":')
    monkeypatch.setattr(host_tests, "FAKE_APP_SERVER",
                        host_tests.FAKE_APP_SERVER.replace(needle, replacement))
    _, client, log = _ensure(tmp_path, home=fake.FLEET_HOME)
    try:
        with pytest.raises(Exception):
            client.call({"operation_id": "poison-read", "method": "rpc",
                "payload": {"method": "test/fail", "params": {}}}, timeout=2)
        assert client.call({"operation_id": "still-live", "method": "ping",
                            "payload": {}}, timeout=2).result["generation"] == client.generation
        with pytest.raises(Exception):
            client.call({"operation_id": "pre-send-refusal", "method": "rpc",
                "payload": {"method": "test/echo", "params": {"value": 1}}}, timeout=2)
        methods = [entry.get("method") for entry in map(json.loads,
                   log.read_text().splitlines()) if entry.get("event") == "request"]
        assert methods == ["test/fail"]

        metadata = json.loads(metadata_path.read_text())
        args.generation = client.generation
        args.host_pid = metadata["pid"]
        args.host_start = metadata["process_identity"]
        args.child_pid = metadata["app_server_pid"]
        args.child_start = metadata["app_server_process_identity"]
        fake.claim["host_generation"] = client.generation
        fake.rows["sup|inc|boot"]["codex_host_generation"] = client.generation
        old_op = fake.FLEET_HOME / "state" / "codex" / "operations" / "old-op.json"
        entry = json.loads(old_op.read_text())
        entry["generation"] = client.generation
        old_op.write_text(json.dumps(entry))
        monkeypatch.setattr(recovery.CodexHostClient, "connect_existing",
                            lambda home: fleet_codex.CodexHostClient._existing(home))
        recovery._prepare(fake, args)
        assert recovery._load(fake)["state"] == "prepared"
        assert [entry.get("method") for entry in map(json.loads,
                log.read_text().splitlines()) if entry.get("event") == "request"] == ["test/fail"]
    finally:
        (fake.FLEET_HOME / "state" / "codex" / recovery.BARRIER).unlink(missing_ok=True)
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
