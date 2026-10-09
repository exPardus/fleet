"""Focused offline contract for one held supervisor turn interrupt."""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
from fleet_codex import CodexApprovalStore, _approval_key
from test_codex_supervisor import (FakeLifecycleClient, ITEM_ID, THREAD_ID,
                                   TURN_ID, _seed_native_supervisor, _send_args,
                                   supervisor_home)


class InterruptClient(FakeLifecycleClient):
    """Use the production approval store and journal with an old-host read drain."""

    def __init__(self, home, *, resolve=True, lose_reply=False):
        super().__init__(home, active_flags=["waitingOnApproval"])
        from fleet_codex import OperationJournal
        self.store = CodexApprovalStore(Path(home), self.generation)
        self.journal = OperationJournal(Path(home), self.generation)
        self.resolve_on_read = resolve
        self.lose_reply = lose_reply
        self.interrupted = False

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        if method == "turn/interrupt":
            entry = self.journal.prepare(operation)
            assert entry["state"] == "prepared"
            assert self.journal.unresolved_predecessor(operation["operation_id"]) is None
            self.journal.accept(operation["operation_id"])
            self.interrupt_calls += 1
            self.interrupted = True
            if self.lose_reply:
                self.journal.uncertain(operation["operation_id"], "lost reply")
                raise TimeoutError("lost reply after acceptance")
            self.journal.observe(operation["operation_id"], {})
            return SimpleNamespace(operation_id=operation["operation_id"],
                                   generation=self.generation, result={})
        if method == "thread/read" and self.interrupted:
            self.thread_status = "idle"
            self.turn_status = "interrupted"
            self.active_flags = []
            if self.resolve_on_read:
                self.store.resolve({"params": {
                    "requestId": 194, "threadId": THREAD_ID}})
        return super().call(operation, timeout)

    def pending_approvals(self, thread_id, turn_id):
        return self.store.unresolved(thread_id=thread_id, turn_id=turn_id)

    def commit(self, operation_id):
        if operation_id.startswith("supervisor-current-interrupt-"):
            self.journal.commit(operation_id)
        self.commits.append(operation_id)


@pytest.fixture
def case(supervisor_home, monkeypatch):
    name, inc = _seed_native_supervisor(supervisor_home)
    client = InterruptClient(supervisor_home)
    params = {"threadId": THREAD_ID, "turnId": TURN_ID,
              "itemId": ITEM_ID, "startedAtMs": 1, "command": "true"}
    original = client.store.record_request({
        "id": 194, "method": "item/commandExecution/requestApproval",
        "params": params})
    key = _approval_key(client.generation, 194)
    callback_path = client.store.path(194)
    raw_hash = hashlib.sha256(callback_path.read_bytes()).hexdigest()
    source = {"kind": "codex", "claim_id": "genuine-test-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    monkeypatch.setattr(fleet, "_mail_source_is_current", lambda value: value == source)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes", lambda *_: client)
    args = SimpleNamespace(
        _fleet_home_explicit=True, preflight=False,
        request_id="194", request_id_type="int",
        expect_old_host_sha256=fleet.SUP_INTERRUPT_OLD_HOST_SHA256,
        expect_host_pid=101, expect_app_server_pid=102,
        expect_app_server_started_at=1.0,
        expect_inc=inc, expect_thread=THREAD_ID, expect_turn=TURN_ID,
        expect_host_generation=client.generation,
        expect_host_process_identity="host-identity",
        expect_app_server_process_identity="child-identity",
        expect_item_id=ITEM_ID, expect_request_key=key,
        expect_request_sha256=raw_hash)
    return SimpleNamespace(home=supervisor_home, name=name, inc=inc,
                           client=client, args=args, original=original,
                           callback_path=callback_path)


def _reservation(case):
    claim = fleet.read_incarnation()
    row = fleet.read_registry_no_repair()["workers"][case.name]
    return claim.get("pending_operation"), claim, row


def test_exact_terminal_resolved_settles_one_interrupt_and_preserves_siblings(
        case):
    before = fleet.read_registry_no_repair()
    before["workers"]["product"] = {"status": "working", "opaque": "keep"}
    fleet.save_registry(before)
    mail = case.home / "mailbox" / f"{THREAD_ID}.md"
    mail.write_text("queued backlog\n", encoding="utf-8")
    assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
    pending, claim, row = _reservation(case)
    assert pending is None and claim["state"] == "held"
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert row["status"] == row["adapter_state"] == "idle"
    assert case.client.interrupt_calls == 1
    assert len(case.client.commits) == 1
    assert case.client.journal.records()[0]["state"] == "committed"
    assert json.loads(case.callback_path.read_text())["state"] == "resolved"
    assert "response" not in json.loads(case.callback_path.read_text())
    assert fleet.read_registry_no_repair()["workers"]["product"] == before["workers"]["product"]
    assert mail.read_text() == "queued backlog\n"


def test_terminal_with_pending_callback_holds_without_replay(case):
    case.client.resolve_on_read = False
    with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    pending, _, row = _reservation(case)
    assert pending["kind"] == "supervisor/current-turn-interrupt"
    assert row["adapter_state"] == "mutating"
    assert case.client.interrupt_calls == 1
    assert not case.client.commits
    assert json.loads(case.callback_path.read_text())["state"] == "pending"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 1


def test_preflight_reads_only_and_unresolved_predecessor_refuses(case):
    case.args.preflight = True
    assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
    assert _reservation(case)[0] is None
    assert case.client.journal.records() == []
    assert case.client.interrupt_calls == 0
    case.args.preflight = False
    operation = {"operation_id": "other-accepted", "method": "rpc",
                 "payload": {"method": "turn/interrupt", "params": {
                     "threadId": THREAD_ID, "turnId": TURN_ID}}}
    case.client.journal.prepare(operation)
    case.client.journal.accept("other-accepted")
    with pytest.raises(fleet.FleetCliError, match="unresolved predecessor"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert _reservation(case)[0] is None
    assert case.client.interrupt_calls == 0


def test_accepted_lost_reply_preserves_reservation_and_journal(case):
    case.client.lose_reply = True
    with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    pending, _, _ = _reservation(case)
    assert pending is not None
    assert case.client.journal.records()[0]["state"] == "uncertain"
    assert case.client.interrupt_calls == 1 and not case.client.commits
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 1


@pytest.mark.parametrize("change", ["claim", "row", "callback", "inventory",
                                    "source", "child", "request_type"])
def test_drift_refuses_before_mutation(case, monkeypatch, change):
    if change == "claim":
        claim = fleet.read_incarnation()
        claim["current_turn_id"] = "different-turn"
        fleet.write_incarnation(claim)
    elif change == "row":
        reg = fleet.read_registry_no_repair()
        reg["workers"][case.name]["adapter_state"] = "idle"
        fleet.save_registry(reg)
    elif change == "callback":
        record = json.loads(case.callback_path.read_text())
        record["params"]["command"] = "different"
        case.callback_path.write_text(json.dumps(record), encoding="utf-8")
        case.callback_path.chmod(0o600)
    elif change == "inventory":
        case.client.store.record_request({
            "id": 195, "method": "item/commandExecution/requestApproval",
            "params": {"threadId": THREAD_ID, "turnId": TURN_ID,
                       "itemId": "second", "startedAtMs": 2}})
    elif change == "source":
        monkeypatch.setattr(fleet, "_mail_source_is_current", lambda _: False)
    elif change == "child":
        monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes",
                            lambda *_: (_ for _ in ()).throw(
                                fleet.FleetCliError("child drift")))
    elif change == "request_type":
        case.args.request_id_type = "string"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 0


def test_old_host_source_fixture_and_supported_approval_store(case):
    host = Path(fleet.__file__).with_name("fleet_codex_host.py")
    assert hashlib.sha256(host.read_bytes()).hexdigest() == \
        fleet.SUP_INTERRUPT_OLD_HOST_SHA256
    assert case.original["offered_decisions"] == [
        "accept", "acceptForSession", "decline", "cancel"]
    assert case.client.pending_approvals(THREAD_ID, TURN_ID) == [case.original]


def test_read_induced_child_replacement_refuses_before_reservation(case, monkeypatch):
    original_observe = fleet._codex_supervisor_observe
    observed = {"done": False}

    def read_and_replace(*args, **kwargs):
        result = original_observe(*args, **kwargs)
        observed["done"] = True
        return result

    def fresh(*_):
        assert observed["done"]
        raise fleet.FleetCliError("original child replaced after public read")

    monkeypatch.setattr(fleet, "_codex_supervisor_observe", read_and_replace)
    monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes", fresh)
    with pytest.raises(fleet.FleetCliError, match="child replaced"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert _reservation(case)[0] is None
    assert case.client.interrupt_calls == 0


def test_queued_backlog_and_distinct_wake_use_existing_send_once(
        case, monkeypatch, capsys):
    queued = case.home / "mailbox" / f"{THREAD_ID}.md"
    queued.write_text("previous queued direction\n", encoding="utf-8")
    assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
    assert queued.read_text() == "previous queued direction\n"
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: case.client)
    case.client.interrupted = False
    assert fleet.cmd_send(_send_args(message=(
        "Process the already queued current backlog once; "
        "do not repeat the old report command."))) == 0
    starts = [op for op in case.client.operations
              if op["payload"]["method"] == "turn/start"]
    assert len(starts) == 1
    sent = starts[0]["payload"]["params"]["input"][0]["text"]
    assert "previous queued direction" in sent
    receipt = re.search(r"FLEET VERIFIED MAIL NOTICE ([^\s]+)", sent)
    assert receipt is not None
    capsys.readouterr()
    assert fleet.cmd_mail_verify(SimpleNamespace(mail_id=receipt.group(1))) == 0
    assert "Process the already queued current backlog once" in capsys.readouterr().out
    assert not queued.exists()
