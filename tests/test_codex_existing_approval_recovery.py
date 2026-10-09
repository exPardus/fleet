"""Existing 0.155.1 callback recovery with a pre-reservation Apps host fake."""

import copy
from types import SimpleNamespace

import pytest

import fleet
from fleet_codex import CodexApprovalStore, OperationJournal


THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
OTHER = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
INC = "inc-20261009T010000Z-abcd"
OLD = "old-apps-host-generation"
NEW = "new-apps-host-generation"
NAME = f"sup|{INC}|boot"
METHOD = "item/commandExecution/requestApproval"
COMMAND = "gh pr view 17 -R example/tap --json number,url"


class LegacyAppsHost:
    """Exposes old rpc/approval-list, never W179 reservation capability."""

    def __init__(self, home, generation, store, *, cold=False):
        self.home = home
        self.generation = generation
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

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        if method == "thread/read":
            result = {"thread": {
                "id": THREAD, "cwd": str(self.home),
                "status": {"type": self.thread_status,
                           "activeFlags": self.flags}}}
        elif method == "thread/turns/list":
            result = {"data": [{"id": TURN, "status": self.turn_status,
                                "itemsView": "notLoaded"}],
                      "nextCursor": None}
        elif method == "thread/items/list":
            result = {"data": [], "nextCursor": None}
        elif method in {"turn/interrupt", "thread/resume"}:
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
            else:
                result = {
                    "thread": {"id": THREAD, "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-6-sol",
                    "approvalPolicy": "on-request",
                    "approvalsReviewer": "user",
                    "sandbox": {"type": "workspaceWrite"},
                }
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
    worker.update({"codex_thread_id": OTHER, "status": "idle"})
    fleet.save_registry({"workers": {NAME: row, "other-worker": worker}})
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
        current[0] = LegacyAppsHost(home, NEW, store, cold=True)
        return current[0]

    monkeypatch.setattr(fleet, "_codex_native_client", create_host)
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


def test_old_host_cancel_then_exact_cold_resume(apps_home):
    home, store, old, current, cwd, mail = apps_home
    other_before = copy.deepcopy(fleet.read_registry_no_repair()["workers"]["other-worker"])
    mail_before = mail.read_bytes()
    operation_id = cancel(apps_home)
    assert [op["payload"]["method"] for op in old.mutations] == ["turn/interrupt"]
    terminal = store._load_path(store.path(6))
    assert terminal["state"] == "resolved" and "response" not in terminal
    assert store._load_path(store.path(7))["state"] == "pending"
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert fleet._prepare_codex_cancelled_approval_resume(
        args(cwd, expect_cancel_op=operation_id)) == 0
    old.host_live = old.app_live = False
    old.stale = True
    assert fleet._resume_codex_cancelled_approval(
        args(cwd, expect_cancel_op=operation_id)) == 0
    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["incarnation_id"] == INC and claim["current_turn_id"] == TURN
    assert claim["host_generation"] == NEW
    assert [op["payload"]["method"] for op in current[0].mutations] == ["thread/resume"]
    assert current[0].mutations[0]["payload"]["params"] == {
        "threadId": THREAD, "excludeTurns": True, "cwd": str(home),
        "model": "gpt-6-sol", "approvalPolicy": "on-request",
        "approvalsReviewer": "user", "sandbox": "workspace-write"}
    assert fleet.read_registry_no_repair()["workers"]["other-worker"] == other_before
    assert mail.read_bytes() == mail_before
    assert store._load_path(store.path(7))["state"] == "pending"


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
    assert fleet._prepare_codex_cancelled_approval_resume(pinned) == 0
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
    assert fleet._prepare_codex_cancelled_approval_resume(pinned) == 0
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["other-worker"]["status"] = "dead"
        fleet.save_registry(data)
    old.host_live = old.app_live = False
    old.stale = True
    assert fleet._resume_codex_cancelled_approval(pinned) == 0
    assert fleet.read_registry_no_repair()["workers"]["other-worker"]["status"] == "dead"


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
    assert fleet._prepare_codex_cancelled_approval_resume(pinned) == 0
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
