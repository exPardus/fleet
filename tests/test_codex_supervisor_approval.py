"""Exact, Interface-authenticated response to one native supervisor request."""
import copy
from types import SimpleNamespace

import pytest

import fleet
import fleet_codex


THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
OTHER_THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
INC = "inc-20261009T010000Z-abcd"
GEN = "host-generation-1"
METHOD = "item/commandExecution/requestApproval"
COMMAND = "gh pr view 17 -R example/tap --json number,url,isDraft"
NAME = f"sup|{INC}|boot"


class ApprovalClient:
    generation = GEN

    def __init__(self, home, store):
        self.home = home
        self.store = store
        self.provider_writes = []
        self.public_reads = []
        self.on_pending = None
        self.lose_reply = False
        self.active_flags = ["waitingOnApproval"]
        self.observed_turn = TURN

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        self.public_reads.append(method)
        if method == "thread/read":
            result = {"thread": {
                "id": THREAD, "cwd": str(self.home),
                "status": {"type": "active", "activeFlags": self.active_flags},
            }}
        elif method == "thread/turns/list":
            result = {"data": [{"id": self.observed_turn, "status": "inProgress",
                                "itemsView": "notLoaded"}], "nextCursor": None}
        elif method == "thread/items/list":
            result = {"data": [], "nextCursor": None}
        else:
            raise AssertionError(f"unexpected provider read {method}")
        return SimpleNamespace(generation=self.generation, result=result)

    def pending_approvals(self, thread_id, turn_id):
        assert (thread_id, turn_id) == (THREAD, TURN)
        if self.on_pending:
            self.on_pending()
        return self.store.unresolved(thread_id=thread_id, turn_id=turn_id)

    def respond_approval(self, request_id, thread_id, turn_id, decision, timeout):
        assert timeout == 10
        record, response = self.store.begin_response(
            request_id, thread_id, turn_id, decision)
        assert self.store._load_path(self.store.path(record["request_id"]))["state"] == "responding"
        self.provider_writes.append((request_id, thread_id, turn_id, response))
        self.store.mark_responded(record)
        if self.lose_reply:
            raise fleet_codex.HostUnavailable("response lost after provider write")
        return {"state": "responded", "request_id": record["request_id"],
                "thread_id": thread_id, "turn_id": turn_id}


@pytest.fixture
def approval_home(tmp_path, monkeypatch):
    home = (tmp_path / "home").resolve()
    for directory in ("state", "supervisor", "mailbox"):
        (home / directory).mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    record = fleet.new_worker_record(
        None, home, "supervise", "accept", model="codex:gpt-6-sol",
        dispatch_kind="codex-app-server", substrate="codex")
    record.update({
        "codex_thread_id": THREAD, "codex_turn_id": TURN,
        "codex_host_generation": GEN, "supervisor_incarnation_id": INC,
        "adapter_state": "waiting", "status": "working",
    })
    worker = fleet.new_worker_record(
        None, home, "unrelated product", "accept", model="codex:gpt-6-sol",
        dispatch_kind="codex-app-server", substrate="codex")
    worker.update({"codex_thread_id": OTHER_THREAD, "status": "working"})
    fleet.save_registry({"workers": {NAME: record, "product-lane": worker}})
    fleet.write_incarnation({
        "incarnation_id": INC, "state": "held", "provider": "codex",
        "holder": {"provider": "codex", "thread_id": THREAD},
        "current_turn_id": TURN, "host_generation": GEN,
        "heartbeat_at": fleet.now_iso(),
    })
    (home / "mailbox" / "pending.md").write_text("preserve this mail\n")
    source = {"kind": "codex", "claim_id": "registered-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    monkeypatch.setattr(fleet, "_mail_source_is_current", lambda value: value == source)
    store = fleet_codex.CodexApprovalStore(home, GEN)
    cwd = str(home / "tap-wt-ci-edge-fix")
    store.record_request({"id": 6, "method": METHOD, "params": {
        "threadId": THREAD, "turnId": TURN, "itemId": "item-6",
        "startedAtMs": 1, "command": COMMAND, "cwd": cwd,
    }})
    store.record_request({"id": 7, "method": METHOD, "params": {
        "threadId": THREAD, "turnId": TURN, "itemId": "item-7",
        "startedAtMs": 2, "command": "git status", "cwd": cwd,
    }})
    store.record_request({"id": 8, "method": METHOD, "params": {
        "threadId": OTHER_THREAD, "turnId": TURN, "itemId": "item-8",
        "startedAtMs": 3, "command": "git diff", "cwd": cwd,
    }})
    client = ApprovalClient(home, store)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    return home, store, client, source, cwd


def response_args(cwd, **updates):
    values = {
        "name": "supervisor", "request_id": "6", "decision": "accept",
        "nonce": None, "_fleet_home_explicit": True,
        "expect_inc": INC, "expect_thread": THREAD, "expect_turn": TURN,
        "expect_host_generation": GEN, "expect_method": METHOD,
        "expect_command": COMMAND, "expect_request_cwd": cwd,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_exact_supervisor_response_audits_once_and_preserves_unrelated_state(
        approval_home, capsys):
    home, store, client, _source, cwd = approval_home
    claim = copy.deepcopy(fleet.read_incarnation())
    registry = copy.deepcopy(fleet.read_registry_no_repair())
    mail = (home / "mailbox" / "pending.md").read_bytes()

    assert fleet.cmd_codex_respond(response_args(cwd)) == 0
    assert client.provider_writes == [
        ("6", THREAD, TURN, {"decision": "accept"})]
    assert store._load_path(store.path(6))["state"] == "responded"
    assert store._load_path(store.path(7))["state"] == "pending"
    assert store._load_path(store.path(8))["state"] == "pending"
    assert fleet.read_incarnation() == claim
    assert fleet.read_registry_no_repair() == registry
    assert (home / "mailbox" / "pending.md").read_bytes() == mail
    assert "consumed once" in capsys.readouterr().out
    with pytest.raises(fleet.FleetCliError, match="pending request disagrees"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert len(client.provider_writes) == 1


@pytest.mark.parametrize("change", [
    {"expect_inc": "inc-wrong"}, {"expect_thread": OTHER_THREAD},
    {"expect_turn": OTHER_THREAD}, {"expect_host_generation": "other-host"},
    {"expect_method": "item/fileChange/requestApproval"},
    {"expect_command": "gh pr view 18"},
    {"expect_request_cwd": "/other/worktree"},
    {"request_id": "7"}, {"_fleet_home_explicit": False},
    {"nonce": "fabricated"},
])
def test_supervisor_response_requires_exact_operator_binding(approval_home, change):
    _home, store, client, _source, cwd = approval_home
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(response_args(cwd, **change))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


@pytest.mark.parametrize("claim_change", [
    {"state": "released"}, {"current_turn_id": OTHER_THREAD},
    {"host_generation": "other-host"},
    {"holder": {"provider": "codex", "thread_id": OTHER_THREAD}},
])
def test_supervisor_response_refuses_changed_or_nonheld_claim(
        approval_home, claim_change):
    _home, store, client, _source, cwd = approval_home
    claim = fleet.read_incarnation()
    claim.update(claim_change)
    fleet.write_incarnation(claim)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


@pytest.mark.parametrize("request_change", [
    {"method": "item/fileChange/requestApproval"},
    {"params": {"command": "gh pr view 18"}},
    {"state": "uncertain"}, {"generation": "other-host"},
    {"thread_id": OTHER_THREAD}, {"turn_id": OTHER_THREAD},
    {"item_id": "different-item"},
    {"params": {"cwd": "/different/worktree"}},
])
def test_supervisor_response_refuses_changed_request(
        approval_home, request_change):
    _home, store, client, _source, cwd = approval_home
    record = store._load_path(store.path(6))
    for key, value in request_change.items():
        if key == "params":
            record[key].update(value)
        else:
            record[key] = value
    fleet_codex._atomic_json(store.path(6), record)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.provider_writes == []


@pytest.mark.parametrize("decision", [
    "acceptForSession", "decline", '{"decision":"accept"}', "[]", "null",
])
def test_supervisor_response_refuses_other_or_malformed_decision(
        approval_home, decision):
    _home, store, client, _source, cwd = approval_home
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(response_args(cwd, decision=decision))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


def test_supervisor_response_refuses_foreign_source_and_mid_read_claim_change(
        approval_home, monkeypatch):
    _home, store, client, source, cwd = approval_home
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    with pytest.raises(fleet.FleetCliError, match="Interface"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.public_reads == []
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)

    def drift():
        claim = fleet.read_incarnation()
        claim["current_turn_id"] = OTHER_THREAD
        fleet.write_incarnation(claim)
    client.on_pending = drift
    with pytest.raises(fleet.FleetCliError, match="binding|disagree"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


def test_supervisor_response_refuses_source_drift_before_dispatch(
        approval_home, monkeypatch):
    _home, store, client, source, cwd = approval_home
    current_source = [source]
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: current_source[0])
    client.on_pending = lambda: current_source.__setitem__(0, None)
    with pytest.raises(fleet.FleetCliError, match="binding or Interface changed"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


@pytest.mark.parametrize("failure", ["host", "newer-turn", "not-waiting"])
def test_supervisor_response_requires_current_host_turn_and_wait(
        approval_home, failure):
    _home, store, client, _source, cwd = approval_home
    if failure == "host":
        client.generation = "other-host"
    elif failure == "newer-turn":
        client.observed_turn = OTHER_THREAD
    else:
        client.active_flags = []
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_respond(response_args(cwd))
    assert client.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


def test_supervisor_response_parser_requires_explicit_expectations_at_execution():
    args = fleet.build_parser().parse_args([
        "codex-respond", "supervisor", "6", "accept",
        "--expect-inc", INC, "--expect-thread", THREAD,
        "--expect-turn", TURN, "--expect-host-generation", GEN,
        "--expect-method", METHOD, "--expect-command", COMMAND])
    assert (args.name, args.request_id, args.decision,
            args.expect_inc, args.expect_thread, args.expect_turn,
            args.expect_host_generation, args.expect_method,
            args.expect_command) == (
                "supervisor", "6", "accept", INC, THREAD, TURN,
                GEN, METHOD, COMMAND)


def test_consumed_response_with_lost_reply_is_uncertain_and_never_replayed(
        approval_home):
    _home, store, client, _source, cwd = approval_home
    client.lose_reply = True
    with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert store._load_path(store.path(6))["state"] == "responded"
    assert len(client.provider_writes) == 1
    with pytest.raises(fleet.FleetCliError, match="pending request disagrees"):
        fleet.cmd_codex_respond(response_args(cwd))
    assert len(client.provider_writes) == 1


def test_physical_supervisor_name_still_refuses_ordinary_worker_route(
        approval_home):
    _home, _store, client, _source, cwd = approval_home
    args = response_args(cwd, name=NAME)
    with pytest.raises(fleet.FleetCliError, match="target 'supervisor'"):
        fleet.cmd_codex_respond(args)
    args = response_args(cwd, name=NAME)
    for key in ("expect_inc", "expect_thread", "expect_turn",
                "expect_host_generation", "expect_method", "expect_command",
                "expect_request_cwd"):
        setattr(args, key, None)
    with pytest.raises(fleet.FleetCliError, match="not an ordinary worker"):
        fleet.cmd_codex_respond(args)
    assert client.provider_writes == []
