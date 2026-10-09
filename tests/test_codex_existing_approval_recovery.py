"""Existing 0.155.1 callback recovery with a pre-reservation Apps host fake."""

import copy
import json
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import pytest

import fleet
import fleet_codex_host
from fleet_codex import (CodexApprovalStore, CodexHostClient,
                         OperationJournal, _create_key)


THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
OTHER = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
INC = "inc-20261009T010000Z-abcd"
OLD = "old-apps-host-generation"
NEW = "new-apps-host-generation"
NAME = f"sup|{INC}|boot"
METHOD = "item/commandExecution/requestApproval"
COMMAND = "gh pr view 17 -R example/tap --json number,url"
FRESH_TURN = "018f22d3-9b4a-7cc3-8a0e-36d4f59106ba"
FRESH_COMMAND = "gh pr view 18 -R example/tap --json number,url"
PINNED_SCHEMA = (
    "f0402dc8ce8d278108f1e68e9d46ec7e59ddd9d153f5e70668d84d56f258dda3")


class LegacyAppsHost:
    """Exposes old rpc/approval-list, never W179 reservation capability."""

    def __init__(self, home, generation, store, *, cold=False):
        self.home = home
        self.generation = generation
        self.codex_version = "0.155.1"
        self.schema_digest = PINNED_SCHEMA
        self.store = store
        self.host_pid = 55037 if not cold else 55100
        self.host_process_identity = "old-host-start" if not cold else "new-host-start"
        self.app_server_pid = 55038 if not cold else 55101
        self.app_server_process_identity = "old-child-start" if not cold else "new-child-start"
        self.host_live = True
        self.app_live = True
        self.stale = False
        self._launched_process = object() if cold else None
        self.thread_status = "idle" if cold else "active"
        self.turn_status = "interrupted" if cold else "inProgress"
        self.flags = [] if cold else ["waitingOnApproval"]
        self.mutations = []
        self.fail_after_accept = False
        self.on_mutation = None
        self.on_pending = None
        self.other_active = False
        self.cold = cold
        self.turn_id = TURN
        self.responses = []
        if cold:
            self.host = fleet_codex_host.Host.__new__(fleet_codex_host.Host)
            self.host.home = home
            self.host.generation = generation
            self.host.approvals = store

    def _owner_live(self):
        return self.host_live

    def _app_server_live(self):
        return self.app_live

    def _metadata_stale(self):
        return self.stale

    def config_requirements(self):
        return {"requirements": None}

    def pending_approvals(self, thread_id, turn_id=None):
        if self.on_pending is not None:
            self.on_pending()
        return self.store.unresolved(thread_id=thread_id, turn_id=turn_id)

    def supervisor_approval_reservation_supported(self):
        return self.cold

    def respond_approval(self, request_id, thread_id, turn_id, decision, timeout,
                         supervisor_reservation=None):
        assert self.cold and timeout == 10
        payload = {"request_id": request_id, "thread_id": thread_id,
                   "turn_id": turn_id, "decision": decision}
        with fleet.fleet_lock():
            self.host._validate_supervisor_approval_reservation(
                None, payload, supervisor_reservation)
            record, response = self.store.begin_response(
                request_id, thread_id, turn_id, decision)
        self.responses.append(response)
        current = self.store.mark_responded(record)
        return {"state": current["state"], "request_id": current["request_id"],
                "thread_id": thread_id, "turn_id": turn_id}

    def commit(self, operation_id):
        OperationJournal(self.home, self.generation).commit(operation_id)

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        target = operation["payload"].get("params", {}).get("threadId")
        other = target == OTHER
        if method == "thread/read":
            result = {"thread": {
                "id": OTHER if other else THREAD, "cwd": str(self.home),
                "status": {"type": ("active" if self.other_active else "idle")
                           if other else self.thread_status,
                           "activeFlags": [] if other else self.flags}}}
        elif method == "thread/turns/list":
            turns = [{"id": self.turn_id, "status": (
                                "inProgress" if self.other_active else "completed")
                                if other else self.turn_status,
                                "itemsView": "notLoaded"}]
            if self.turn_id == FRESH_TURN and not other:
                turns.append({"id": TURN, "status": "interrupted",
                              "itemsView": "notLoaded"})
            result = {"data": turns, "nextCursor": None}
        elif method == "thread/items/list":
            result = {"data": [], "nextCursor": None}
        elif method in {"turn/interrupt", "thread/resume", "turn/start"}:
            journal = OperationJournal(self.home, self.generation)
            journal.prepare(operation)
            journal.accept(operation["operation_id"])
            self.mutations.append(copy.deepcopy(operation))
            if self.on_mutation is not None:
                self.on_mutation(method)
            if self.fail_after_accept:
                raise TimeoutError("old host accepted request, reply lost")
            if method == "turn/interrupt":
                self.thread_status = "idle"
                self.turn_status = "interrupted"
                self.flags = []
                self.store.resolve({"params": {
                    "threadId": THREAD, "requestId": 6}})
                result = {}
            elif method == "thread/resume":
                result = {
                    "thread": {"id": THREAD, "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-6-sol",
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "sandbox": {"type": "workspaceWrite"},
                }
            else:
                self.turn_id = FRESH_TURN
                self.thread_status = "active"
                self.turn_status = "inProgress"
                self.flags = ["waitingOnApproval"]
                self.store.record_request({"id": 9, "method": METHOD, "params": {
                    "threadId": THREAD, "turnId": FRESH_TURN,
                    "itemId": "item-9", "startedAtMs": 9,
                    "command": FRESH_COMMAND,
                    "cwd": str(self.home / "tap-wt-ci-edge-fix")}})
                result = {"turn": {"id": FRESH_TURN,
                                   "status": "inProgress"}}
            journal.observe(operation["operation_id"], result)
        else:
            raise AssertionError(f"legacy host received unexpected method {method}")
        return SimpleNamespace(generation=self.generation, result=result)


@pytest.fixture
def apps_home(tmp_path, monkeypatch):
    home = (tmp_path / "apps").resolve()
    for directory in ("state", "mailbox", "supervisor"):
        (home / directory).mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    source = {"kind": "codex", "claim_id": "current-genuine-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: source)
    row = fleet.new_worker_record(
        None, home, "supervise", "accept", model="codex:gpt-6-sol",
        dispatch_kind="codex-app-server", substrate="codex")
    row.update({
        "codex_thread_id": THREAD, "codex_turn_id": TURN,
        "codex_host_generation": OLD, "supervisor_incarnation_id": INC,
        "adapter_state": "waiting", "status": "working",
        "permission_effective": {
            "approvalPolicy": "on-request", "approvalsReviewer": "user",
            "sandbox": {"type": "workspaceWrite"}},
    })
    worker = fleet.new_worker_record(
        None, home, "other product", "accept", model="codex:gpt-6-sol",
        dispatch_kind="codex-app-server", substrate="codex")
    worker.update({"codex_thread_id": OTHER, "codex_turn_id": TURN,
                   "codex_host_generation": OLD,
                   "adapter_state": "active", "provider_status": "idle",
                   "status": "idle"})
    legacy = fleet.new_worker_record(
        None, home, "legacy product", "accept", model="claude:sonnet",
        dispatch_kind="bg", substrate="claude")
    legacy["status"] = "idle"
    fleet.save_registry({"workers": {
        NAME: row, "other-worker": worker, "legacy-worker": legacy}})
    fleet.write_incarnation({
        "incarnation_id": INC, "state": "held", "provider": "codex",
        "holder": {"provider": "codex", "thread_id": THREAD},
        "current_turn_id": TURN, "host_generation": OLD,
        "heartbeat_at": fleet.now_iso(),
    })
    mail = home / "mailbox" / f"{THREAD}.md"
    mail.write_text("preserve queued Apps work\n")
    store = CodexApprovalStore(home, OLD)
    cwd = str(home / "tap-wt-ci-edge-fix")
    store.record_request({"id": 6, "method": METHOD, "params": {
        "threadId": THREAD, "turnId": TURN, "itemId": "item-6",
        "startedAtMs": 1, "command": COMMAND, "cwd": cwd}})
    store.record_request({"id": 7, "method": METHOD, "params": {
        "threadId": OTHER, "turnId": TURN, "itemId": "item-7",
        "startedAtMs": 2, "command": "git status", "cwd": cwd}})
    old = LegacyAppsHost(home, OLD, store)
    current = [old]
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: current[0])

    def create_host(_home):
        assert current[0] is old
        current[0] = LegacyAppsHost(
            home, NEW, CodexApprovalStore(home, NEW), cold=True)
        return current[0]

    monkeypatch.setattr(fleet, "_codex_native_client", create_host)
    monkeypatch.setattr(fleet_codex_host, "read_interface_claim",
                        lambda _home: source)
    monkeypatch.setattr(fleet_codex_host, "_ipc_peer_credentials",
                        lambda _connection: (1234, 1000))
    monkeypatch.setattr(fleet_codex_host.os, "getuid", lambda: 1000)
    monkeypatch.setattr(fleet_codex_host, "codex_process_source",
                        lambda _pid: {"uid": 1000})
    monkeypatch.setattr(fleet_codex_host, "interface_source_matches",
                        lambda claim, peer: claim == source)
    monkeypatch.setattr(fleet, "_mail_source_is_current",
                        lambda value: value == source)
    return home, store, old, current, cwd, mail


def args(cwd, **changes):
    data = {
        "_fleet_home_explicit": True,
        "expect_inc": INC, "expect_thread": THREAD, "expect_turn": TURN,
        "expect_host_generation": OLD, "expect_cancel_op": None,
        "expect_request_id": "6", "expect_item_id": "item-6",
        "expect_method": METHOD, "expect_command": COMMAND,
        "expect_request_cwd": cwd,
    }
    data.update(changes)
    return SimpleNamespace(**data)


def cancel(apps_home):
    home, store, old, current, cwd, mail = apps_home
    assert fleet._cancel_codex_supervisor_approval(args(cwd)) == 0
    operation_id = fleet.read_incarnation()["pending_operation"]["operation_id"]
    return operation_id


def prepare(apps_home, operation_id):
    _home, store, _old, _current, cwd, _mail = apps_home
    # A different worker's callback completes through its own provider path
    # before any shared-host shutdown can be prepared.
    store.resolve({"params": {"threadId": OTHER, "requestId": 7}})
    return fleet._prepare_codex_cancelled_approval_resume(
        args(cwd, expect_cancel_op=operation_id))


def test_old_host_cancel_then_exact_cold_resume(apps_home):
    home, store, old, current, cwd, mail = apps_home
    other_before = copy.deepcopy(fleet.read_registry_no_repair()["workers"]["other-worker"])
    mail_before = mail.read_bytes()
    operation_id = cancel(apps_home)
    assert [op["payload"]["method"] for op in old.mutations] == ["turn/interrupt"]
    cancelled = fleet.read_incarnation()["pending_operation"]
    original = OperationJournal(home, OLD).load(operation_id)
    assert cancelled["old_host"]["codex_version"] == "0.155.1"
    assert cancelled["old_host"]["schema_digest"] == PINNED_SCHEMA
    assert original["recovery"]["old_host"] == cancelled["old_host"]
    terminal = store._load_path(store.path(6))
    assert terminal["state"] == "resolved" and "response" not in terminal
    assert store._load_path(store.path(7))["state"] == "pending"
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert prepare(apps_home, operation_id) == 0
    assert fleet.read_incarnation()["pending_operation"][
        "approval_resume_preflight"]["host"] == cancelled["old_host"]
    old.host_live = old.app_live = False
    old.stale = True
    assert fleet._resume_codex_cancelled_approval(
        args(cwd, expect_cancel_op=operation_id)) == 0
    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["incarnation_id"] == INC and claim["current_turn_id"] == TURN
    assert claim["host_generation"] == NEW
    assert [op["payload"]["method"] for op in current[0].mutations] == ["thread/resume"]
    assert current[0].mutations[0]["recovery"]["previous_host"] == \
        cancelled["old_host"]
    assert current[0].mutations[0]["payload"]["params"] == {
        "threadId": THREAD, "excludeTurns": True, "cwd": str(home),
        "model": "gpt-6-sol", "approvalPolicy": "on-request",
        "approvalsReviewer": "user", "sandbox": "workspace-write"}
    assert fleet.read_registry_no_repair()["workers"]["other-worker"] == other_before
    assert mail.read_bytes() == mail_before
    assert store._load_path(store.path(7))["state"] == "resolved"


def test_cold_recovery_new_host_handles_fresh_approval_once(apps_home):
    _home, old_store, old, current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    assert prepare(apps_home, operation_id) == 0
    old.host_live = old.app_live = False
    old.stale = True
    assert fleet._resume_codex_cancelled_approval(
        args(cwd, expect_cancel_op=operation_id)) == 0
    new = current[0]
    assert new.supervisor_approval_reservation_supported()
    assert fleet._cmd_send_codex_supervisor(NAME, "continue queued Apps work") == 0
    fresh = new.store._load_path(new.store.path(9))
    assert fresh["state"] == "pending"
    respond = SimpleNamespace(
        name="supervisor", request_id="9", decision="accept", nonce=None,
        _fleet_home_explicit=True, expect_inc=INC, expect_thread=THREAD,
        expect_turn=FRESH_TURN, expect_host_generation=NEW,
        expect_method=METHOD, expect_command=FRESH_COMMAND,
        expect_request_cwd=cwd)
    assert fleet.cmd_codex_respond(respond) == 0
    assert new.responses == [{"decision": "accept"}]
    assert new.store._load_path(new.store.path(9))["state"] == "responded"
    assert old_store._load_path(old_store.path(6))["state"] == "resolved"
    assert fleet.read_incarnation()["state"] == "held"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(respond)
    assert len(new.responses) == 1


@pytest.mark.parametrize("change", [
    {"expect_inc": "inc-other"}, {"expect_host_generation": "wrong"},
    {"expect_command": "gh pr view 18"}, {"expect_item_id": "other"},
])
def test_cancel_wrong_pin_refuses_before_old_host_mutation(apps_home, change):
    _home, store, old, _current, cwd, _mail = apps_home
    with pytest.raises(fleet.FleetCliError):
        fleet._cancel_codex_supervisor_approval(args(cwd, **change))
    assert old.mutations == []
    assert store._load_path(store.path(6))["state"] == "pending"


def test_accepted_interrupt_lost_reply_stays_fenced_and_never_replays(apps_home):
    _home, store, old, _current, cwd, _mail = apps_home
    old.fail_after_accept = True
    with pytest.raises(TimeoutError):
        fleet._cancel_codex_supervisor_approval(args(cwd))
    assert len(old.mutations) == 1
    assert fleet.read_incarnation()["pending_operation"]["kind"] == \
        "approval-turn-cancel"
    with pytest.raises(fleet.FleetCliError):
        fleet._cancel_codex_supervisor_approval(args(cwd))
    assert len(old.mutations) == 1


def test_preflight_drift_and_live_old_child_refuse_cold_resume(apps_home):
    home, _store, old, _current, cwd, mail = apps_home
    operation_id = cancel(apps_home)
    pinned = args(cwd, expect_cancel_op=operation_id)
    assert prepare(apps_home, operation_id) == 0
    with pytest.raises(fleet.FleetCliError, match="must fully exit"):
        fleet._resume_codex_cancelled_approval(pinned)
    old.host_live = old.app_live = False
    old.stale = True
    mail.write_text("changed target mail\n")
    with pytest.raises(fleet.FleetCliError, match="prepared claim, row, mail"):
        fleet._resume_codex_cancelled_approval(pinned)
    assert fleet.read_incarnation()["state"] == "uncertain"


def test_unrelated_product_row_can_progress_before_cold_resume(apps_home):
    _home, _store, old, _current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    pinned = args(cwd, expect_cancel_op=operation_id)
    assert prepare(apps_home, operation_id) == 0
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["legacy-worker"]["status"] = "dead"
        fleet.save_registry(data)
    old.host_live = old.app_live = False
    old.stale = True
    assert fleet._resume_codex_cancelled_approval(pinned) == 0
    assert fleet.read_registry_no_repair()["workers"]["legacy-worker"]["status"] == "dead"


@pytest.mark.parametrize("version", ["0.160.0", "0.161.0"])
def test_real_client_newer_reviewed_version_refuses_cancel_before_reservation(
        apps_home, version):
    home, store, old, current, cwd, _mail = apps_home
    manifest = json.loads((Path(__file__).resolve().parent / "fixtures"
        / "codex_app_server" / version / "manifest.json").read_text())
    state_dir = home / "state" / "codex"
    metadata = {
        "schema": 1, "home": str(home),
        "generation": str(uuid.uuid4()), "codex_version": version,
        "schema_digest": manifest["schema_sha256"],
        "ipc_protocol_version": 1,
        "codex_protocol_version": manifest["protocol_version"],
        "endpoint": str(state_dir / "ipc.sock"), "transport": "AF_UNIX",
        "ready": True, "heartbeat": time.time(),
        "pid": old.host_pid, "process_identity": old.host_process_identity,
        "started_at": 1.0, "app_server_pid": old.app_server_pid,
        "app_server_process_identity": old.app_server_process_identity,
        "app_server_started_at": 1.0,
    }
    _create_key(state_dir / "host.key")
    metadata_path = state_dir / "host.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    metadata_path.chmod(0o600)
    real = CodexHostClient.connect_existing(home)
    assert real.codex_version == version
    assert real.schema_digest == manifest["schema_sha256"]
    current[0] = real
    with pytest.raises(fleet.FleetCliError, match="running Codex 0.155.1"):
        fleet._cancel_codex_supervisor_approval(args(cwd))
    assert fleet.read_incarnation().get("pending_operation") is None
    assert store._load_path(store.path(6))["state"] == "pending"
    assert old.mutations == []


@pytest.mark.parametrize("generation,status", [
    (None, "active"), (None, "idle"),
    ("other-host-generation", "active"),
    ("other-host-generation", "idle"),
])
def test_ambiguous_native_inventory_blocks_preparation(
        apps_home, generation, status):
    _home, _store, _old, _current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    with fleet.fleet_lock():
        data = fleet.load_registry()
        row = data["workers"]["other-worker"]
        row["status"] = "working" if status == "active" else "idle"
        row["adapter_state"] = status
        row["provider_status"] = status
        if generation is None:
            row.pop("codex_host_generation")
        else:
            row["codex_host_generation"] = generation
        fleet.save_registry(data)
    with pytest.raises(fleet.FleetCliError, match="generation is missing or ambiguous"):
        prepare(apps_home, operation_id)
    assert fleet.read_incarnation()["pending_operation"].get(
        "approval_resume_preflight") is None


def _add_ambiguous_native_row():
    with fleet.fleet_lock():
        data = fleet.load_registry()
        row = copy.deepcopy(data["workers"]["other-worker"])
        row.pop("codex_host_generation")
        data["workers"]["new-ambiguous-native"] = row
        fleet.save_registry(data)


@pytest.mark.parametrize("stage", ["before-creation", "at-creation",
                                    "before-dispatch", "at-settlement"])
def test_new_native_row_after_preflight_never_allows_unproved_resume(
        apps_home, monkeypatch, stage):
    _home, _store, old, current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    assert prepare(apps_home, operation_id) == 0
    old.host_live = old.app_live = False
    old.stale = True
    if stage == "before-creation":
        _add_ambiguous_native_row()
    elif stage == "at-creation":
        create = fleet._codex_native_client

        def drift_at_creation(home):
            client = create(home)
            _add_ambiguous_native_row()
            return client

        monkeypatch.setattr(fleet, "_codex_native_client", drift_at_creation)
    elif stage == "before-dispatch":
        call = fleet._call_codex_supervisor_claimed

        def drift_before_dispatch(*args, **kwargs):
            _add_ambiguous_native_row()
            return call(*args, **kwargs)

        monkeypatch.setattr(fleet, "_call_codex_supervisor_claimed",
                            drift_before_dispatch)
    else:
        create = fleet._codex_native_client

        def drift_at_settlement(home):
            client = create(home)
            client.on_mutation = lambda method: _add_ambiguous_native_row() \
                if method == "thread/resume" else None
            return client

        monkeypatch.setattr(fleet, "_codex_native_client", drift_at_settlement)
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_codex_cancelled_approval(
            args(cwd, expect_cancel_op=operation_id))
    assert fleet.read_incarnation()["state"] == "uncertain"
    resume_calls = [op for op in current[0].mutations
                    if op["payload"]["method"] == "thread/resume"]
    assert len(resume_calls) == (1 if stage == "at-settlement" else 0)


def test_running_old_host_schema_drift_after_reservation_blocks_interrupt(
        apps_home):
    _home, store, old, _current, cwd, _mail = apps_home
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        if calls == 3:
            old.schema_digest = "0" * 64

    old.on_pending = drift
    with pytest.raises(fleet.FleetCliError, match="before provider dispatch"):
        fleet._cancel_codex_supervisor_approval(args(cwd))
    assert old.mutations == []
    assert store._load_path(store.path(6))["state"] == "pending"
    assert fleet.read_incarnation()["pending_operation"]["kind"] == \
        "approval-turn-cancel"


def test_active_same_host_worker_blocks_shutdown_preparation(apps_home):
    _home, _store, old, _current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    with fleet.fleet_lock():
        data = fleet.load_registry()
        other = data["workers"]["other-worker"]
        other.update({"codex_host_generation": OLD, "codex_turn_id": TURN,
                      "adapter_state": "active", "status": "working"})
        fleet.save_registry(data)
    old.other_active = True
    with pytest.raises(fleet.FleetCliError, match="another Apps worker is active"):
        prepare(apps_home, operation_id)
    assert fleet.read_incarnation()["pending_operation"].get(
        "approval_resume_preflight") is None


def test_unrelated_pending_callback_blocks_shared_host_shutdown(apps_home):
    _home, store, _old, _current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    with pytest.raises(fleet.FleetCliError, match="unrelated unresolved callback"):
        fleet._prepare_codex_cancelled_approval_resume(
            args(cwd, expect_cancel_op=operation_id))
    assert store._load_path(store.path(7))["state"] == "pending"


def test_invalid_same_host_worker_route_blocks_shutdown_preparation(apps_home):
    _home, store, _old, _current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    store.resolve({"params": {"threadId": OTHER, "requestId": 7}})
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["other-worker"].update({
            "codex_host_generation": OLD, "mcx_id": "mixed-route"})
        fleet.save_registry(data)
    with pytest.raises(fleet.FleetCliError, match="invalid route"):
        fleet._prepare_codex_cancelled_approval_resume(
            args(cwd, expect_cancel_op=operation_id))


def test_same_host_worker_change_after_preflight_blocks_cold_resume(apps_home):
    _home, _store, old, _current, cwd, _mail = apps_home
    with fleet.fleet_lock():
        data = fleet.load_registry()
        other = data["workers"]["other-worker"]
        other.update({"codex_host_generation": OLD, "codex_turn_id": TURN,
                      "adapter_state": "active", "status": "idle"})
        fleet.save_registry(data)
    operation_id = cancel(apps_home)
    pinned = args(cwd, expect_cancel_op=operation_id)
    assert prepare(apps_home, operation_id) == 0
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["other-worker"]["last_activity"] = \
            "2030-01-01T00:00:00Z"
        fleet.save_registry(data)
    old.host_live = old.app_live = False
    old.stale = True
    with pytest.raises(fleet.FleetCliError, match="prepared claim, row, mail"):
        fleet._resume_codex_cancelled_approval(pinned)


def test_other_worker_progress_during_old_host_interrupt_is_preserved(apps_home):
    home, store, old, _current, cwd, mail = apps_home

    def advance(method):
        assert method == "turn/interrupt"
        with fleet.fleet_lock():
            data = fleet.load_registry()
            data["workers"]["other-worker"]["status"] = "dead"
            fleet.save_registry(data)
        (home / "mailbox" / "other-worker.md").write_text("new worker mail\n")

    old.on_mutation = advance
    cancel(apps_home)
    assert fleet.read_registry_no_repair()["workers"]["other-worker"]["status"] == "dead"
    assert (home / "mailbox" / "other-worker.md").read_text() == "new worker mail\n"
    assert mail.read_text() == "preserve queued Apps work\n"
    assert store._load_path(store.path(7))["state"] == "pending"


def test_supervisor_claim_drift_before_old_host_dispatch_refuses(apps_home):
    _home, store, old, _current, cwd, _mail = apps_home
    calls = 0

    def drift():
        nonlocal calls
        calls += 1
        if calls == 3:
            with fleet.fleet_lock():
                claim = fleet.read_incarnation()
                claim["heartbeat_at"] = "2026-10-09T12:00:00Z"
                fleet.write_incarnation(claim)

    old.on_pending = drift
    with pytest.raises(fleet.FleetCliError, match="claim or row changed"):
        fleet._cancel_codex_supervisor_approval(args(cwd))
    assert old.mutations == []
    assert store._load_path(store.path(6))["state"] == "pending"
    assert fleet.read_incarnation()["heartbeat_at"] == "2026-10-09T12:00:00Z"


def test_cold_resume_policy_mismatch_leaves_exact_intent_fenced(apps_home):
    _home, _store, old, current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    pinned = args(cwd, expect_cancel_op=operation_id)
    assert prepare(apps_home, operation_id) == 0
    old.host_live = old.app_live = False
    old.stale = True
    original_create = fleet._codex_native_client

    def wrong_policy(home):
        fresh = original_create(home)
        real_call = fresh.call

        def changed(operation, timeout):
            reply = real_call(operation, timeout)
            if operation["payload"]["method"] == "thread/resume":
                reply.result["sandbox"] = {"type": "dangerFullAccess"}
            return reply

        fresh.call = changed
        return fresh

    # The local fake simulates an accepted response with a broadened policy.
    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(fleet, "_codex_native_client", wrong_policy)
        with pytest.raises(fleet.FleetCliError, match="sandbox mismatch"):
            fleet._resume_codex_cancelled_approval(pinned)
    assert len(current[0].mutations) == 1
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert fleet.read_incarnation()["pending_operation"]["kind"] == \
        "approval-cancelled/resume"


def test_new_host_without_reviewed_response_fence_refuses_before_resume(
        apps_home, monkeypatch):
    _home, _store, old, current, cwd, _mail = apps_home
    operation_id = cancel(apps_home)
    assert prepare(apps_home, operation_id) == 0
    old.host_live = old.app_live = False
    old.stale = True
    create = fleet._codex_native_client

    def incapable(home):
        fresh = create(home)
        fresh.supervisor_approval_reservation_supported = lambda: False
        return fresh

    monkeypatch.setattr(fleet, "_codex_native_client", incapable)
    with pytest.raises(fleet.FleetCliError, match="reviewed supervisor approval fence"):
        fleet._resume_codex_cancelled_approval(
            args(cwd, expect_cancel_op=operation_id))
    assert current[0].mutations == []
    assert fleet.read_incarnation()["pending_operation"]["kind"] == \
        "approval-cancelled/cold-resume"
