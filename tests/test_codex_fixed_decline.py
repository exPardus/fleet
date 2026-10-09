"""Fixed, typed old-host supervisor denial; synthetic homes and provider only."""

import base64
import copy
import hashlib
import hmac
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

import fleet
import fleet_codex
from test_codex_supervisor_approval import (
    COMMAND, GEN, INC, METHOD, NAME, OTHER_THREAD, THREAD, TURN,
    approval_home, response_args)


OLD = "dd693da24733debc5573473ac429136daea53ab3"
OLD_HOST_SHA256 = fleet.FIXED_DECLINE_OLD_HOST_SHA256


def old_dispatcher(source):
    code = subprocess.check_output(
        ["git", "show", f"{OLD}:bin/fleet_codex_host.py"],
        cwd=Path(__file__).resolve().parents[1])
    assert hashlib.sha256(code).hexdigest() == OLD_HOST_SHA256
    module = ModuleType("w267_exact_old_host")
    module.__file__ = f"{OLD}:bin/fleet_codex_host.py"
    sys.modules[module.__name__] = module
    exec(compile(code, module.__file__, "exec"), module.__dict__)
    module.read_interface_claim = lambda _home: source
    module._ipc_peer_credentials = lambda _connection: (1234, os.getuid())
    module.codex_process_source = lambda _pid: {"uid": os.getuid()}
    module.interface_source_matches = lambda claim, peer: claim == source
    return module


class OldBridge:
    """Reviewed current client envelopes through the real dd693 dispatcher."""

    generation = GEN
    host_pid = 1234
    host_process_identity = "synthetic-old-host-start"

    def __init__(self, home, store, public, source, monkeypatch):
        self.home = home
        self.store = store
        self.public = public
        self.monkeypatch = monkeypatch
        self.old = old_dispatcher(source)
        self.authkey = b"w267-synthetic-key"
        self.encoded = base64.b64encode(self.authkey).decode("ascii")
        self.provider_writes = []
        self.lose_reply = False
        self.on_respond = None
        self.host = self.old.Host.__new__(self.old.Host)
        self.host.home = home
        self.host.generation = GEN
        self.host.authkey = self.authkey
        self.host.encoded_key = self.encoded
        self.host.approvals = store
        self.host.client = SimpleNamespace(
            respond=lambda request_id, payload: self.provider_writes.append(
                (request_id, payload)), notifications=lambda: [])
        metadata = {
            "generation": GEN, "schema_digest": "synthetic-schema",
            "codex_protocol_version": 2, "endpoint": "synthetic-socketpair",
            "transport": "AF_UNIX", "pid": self.host_pid,
            "process_identity": self.host_process_identity, "started_at": 1.0,
            "app_server_pid": 1235,
            "app_server_process_identity": "synthetic-child-start",
            "app_server_started_at": 1.0,
        }
        self.transport = fleet_codex.CodexHostClient(
            home, metadata, self.encoded, self.authkey)

    def _old_call(self, function):
        server, client = socket.socketpair()
        result = {}

        def serve():
            try:
                result["stop"] = self.host._serve_connection(server)
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=serve)
        thread.start()

        def connect(_endpoint, key, deadline):
            assert key == self.authkey
            challenge = fleet_codex._recv_frame(
                client, deadline, fleet_codex.IPC_AUTH_CHALLENGE_BYTES)
            fleet_codex._send_frame(
                client, hmac.digest(key, challenge, "sha256"), deadline)
            assert fleet_codex._recv_frame(client, deadline, 16) == b"OK"
            return client

        with self.monkeypatch.context() as patch:
            patch.setattr(fleet_codex, "_connect_authenticated", connect)
            if self.lose_reply:
                original_send = self.old._send_frame

                def lose_after_response(connection, payload, deadline):
                    record = self.store._load_path(self.store.path(6))
                    if record["state"] == "responded":
                        connection.close()
                        raise OSError("synthetic response ACK lost")
                    return original_send(connection, payload, deadline)

                patch.setattr(self.old, "_send_frame", lose_after_response)
            try:
                return function()
            finally:
                thread.join(timeout=3)
                assert not thread.is_alive()
                assert "error" not in result, result
                assert result["stop"] is False

    def supervisor_approval_reservation_supported(self):
        return self._old_call(
            self.transport.supervisor_approval_reservation_supported)

    def call(self, operation, timeout):
        return self.public.call(operation, timeout)

    def pending_approvals(self, thread_id, turn_id):
        return self.public.pending_approvals(thread_id, turn_id)

    def respond_approval(self, *args, **kwargs):
        if self.on_respond:
            self.on_respond()
        return self._old_call(lambda: self.transport.respond_approval(
            *args, **kwargs))


@pytest.fixture
def fixed_home(approval_home, monkeypatch):
    home, store, public, source, cwd = approval_home
    bridge = OldBridge(home, store, public, source, monkeypatch)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: bridge)
    monkeypatch.setattr(
        fleet_codex, "_process_identity",
        lambda pid: bridge.host_process_identity if pid == bridge.host_pid else None)
    return home, store, bridge, source, cwd


def decline_args(store, cwd, **updates):
    record = store._load_path(store.path(6))
    values = {
        "request_id": "6", "request_id_type": "int", "decision": "decline",
        "_fleet_home_explicit": True,
        "expect_inc": INC, "expect_thread": THREAD, "expect_turn": TURN,
        "expect_host_generation": GEN, "expect_method": METHOD,
        "expect_item_id": record["item_id"], "expect_command": COMMAND,
        "expect_request_cwd": cwd, "expect_cwd_absent": False,
        "expect_request_key": record["key"],
        "expect_request_digest": fleet_codex._fleet_state_digest(record),
        "expect_old_host_sha256": OLD_HOST_SHA256,
        "expect_host_pid": OldBridge.host_pid,
        "expect_host_process_identity": OldBridge.host_process_identity,
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_exact_old_host_declines_once_and_preserves_siblings(fixed_home):
    home, store, bridge, _source, cwd = fixed_home
    claim = copy.deepcopy(fleet.read_incarnation())
    registry = copy.deepcopy(fleet.read_registry_no_repair())
    mail = (home / "mailbox" / "pending.md").read_bytes()
    assert fleet.cmd_codex_decline_fixed(decline_args(store, cwd)) == 0
    assert bridge.provider_writes == [(6, {"decision": "decline"})]
    assert store._load_path(store.path(6))["state"] == "responded"
    assert store._load_path(store.path(7))["state"] == "pending"
    assert store._load_path(store.path(8))["state"] == "pending"
    assert fleet.read_incarnation() == claim
    assert fleet.read_registry_no_repair() == registry
    assert (home / "mailbox" / "pending.md").read_bytes() == mail
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert len(bridge.provider_writes) == 1


def test_unrelated_row_and_mail_progress_survive_exact_settlement(fixed_home):
    home, store, bridge, _source, cwd = fixed_home

    def progress_unrelated():
        registry = fleet.read_registry_no_repair()
        registry["workers"]["product-lane"]["status"] = "idle"
        fleet.save_registry(registry)
        (home / "mailbox" / "later.md").write_text("independent mail\n")

    bridge.on_respond = progress_unrelated
    assert fleet.cmd_codex_decline_fixed(decline_args(store, cwd)) == 0
    assert bridge.provider_writes == [(6, {"decision": "decline"})]
    assert fleet.read_registry_no_repair()["workers"]["product-lane"][
        "status"] == "idle"
    assert (home / "mailbox" / "pending.md").read_text() == "preserve this mail\n"
    assert (home / "mailbox" / "later.md").read_text() == "independent mail\n"


@pytest.mark.parametrize("change", [
    {"decision": "accept"}, {"decision": "cancel"},
    {"decision": "acceptForSession"},
    {"decision": {"decision": "decline"}},
    {"expect_method": "item/fileChange/requestApproval"},
    {"request_id_type": "string"}, {"request_id": "06"},
    {"expect_item_id": "different-item"},
    {"expect_command": "gh pr view 18"},
    {"expect_request_cwd": "/different"},
    {"expect_request_key": "0" * 64},
    {"expect_request_digest": "0" * 64},
    {"expect_old_host_sha256": "0" * 64},
    {"expect_host_generation": "different"},
    {"expect_host_pid": 9999},
    {"_fleet_home_explicit": False},
])
def test_exact_pins_and_every_other_decision_refuse_before_response(
        fixed_home, change):
    _home, store, bridge, _source, cwd = fixed_home
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd, **change))
    assert bridge.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"


def test_typed_id_collision_and_changed_body_refuse(fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    store.record_request({"id": "6", "method": METHOD, "params": {
        "threadId": THREAD, "turnId": TURN, "itemId": "item-string-6",
        "startedAtMs": 4, "command": "different", "cwd": cwd}})
    with pytest.raises(fleet.FleetCliError, match="ambiguous|disagrees"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    store.path("6").unlink()
    with pytest.raises(fleet_codex.UnsafeHostState):
        store.record_request({"id": 6, "method": METHOD, "params": {
            "threadId": OTHER_THREAD, "turnId": TURN,
            "itemId": "different-body", "startedAtMs": 5,
            "command": "different", "cwd": cwd}})


def test_request_drift_after_public_list_refuses_before_reservation(fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    original = decline_args(store, cwd)

    def drift():
        record = store._load_path(store.path(6))
        record["params"]["command"] = "different command"
        fleet_codex._atomic_json(store.path(6), record)

    bridge.public.on_pending = drift
    with pytest.raises(fleet.FleetCliError, match="pending request disagrees"):
        fleet.cmd_codex_decline_fixed(original)
    assert bridge.provider_writes == []
    assert fleet.read_incarnation().get("pending_operation") is None


@pytest.mark.parametrize("change", [
    ("method", "item/fileChange/requestApproval"),
    ("state", "responding"),
    ("thread_id", OTHER_THREAD),
    ("turn_id", OTHER_THREAD),
    ("item_id", "other-item"),
    ("command", "gh pr view 18"),
    ("cwd", "/other"),
    ("offered_decisions", ["accept"]),
])
def test_changed_durable_request_refuses_without_provider_write(
        fixed_home, change):
    _home, store, bridge, _source, cwd = fixed_home
    args = decline_args(store, cwd)
    field, value = change
    record = store._load_path(store.path(6))
    if field in {"command", "cwd"}:
        record["params"][field] = value
    else:
        record[field] = value
    fleet_codex._atomic_json(store.path(6), record)
    with pytest.raises((fleet.FleetCliError, fleet_codex.HostRejected)):
        fleet.cmd_codex_decline_fixed(args)
    assert bridge.provider_writes == []
    assert fleet.read_incarnation().get("pending_operation") is None


def test_real_old_host_rejection_clears_only_exact_pending_reservation(fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    claim = copy.deepcopy(fleet.read_incarnation())
    registry = copy.deepcopy(fleet.read_registry_no_repair())

    def add_unknown():
        store.record_request({"id": 99, "method": "unknown/blocking",
                              "params": {"threadId": OTHER_THREAD,
                                         "turnId": TURN, "itemId": "unknown"}})

    bridge.on_respond = add_unknown
    with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"
    assert fleet.read_incarnation() == claim
    assert fleet.read_registry_no_repair() == registry


def test_returned_rejection_with_changed_pending_record_keeps_reservation(
        fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    original = decline_args(store, cwd)

    def changed_rejection(*_args, **_kwargs):
        record = store._load_path(store.path(6))
        record["params"]["command"] = "changed after reservation"
        fleet_codex._atomic_json(store.path(6), record)
        raise fleet_codex.HostRejected("pre-consumption rejection")

    bridge.respond_approval = changed_rejection
    with pytest.raises(fleet.FleetCliError, match="never replay"):
        fleet.cmd_codex_decline_fixed(original)
    assert bridge.provider_writes == []
    assert fleet.read_incarnation()["pending_operation"]["kind"] == (
        "approval-response")


def test_genuine_interface_and_no_pending_operation_required(fixed_home, monkeypatch):
    _home, store, bridge, source, cwd = fixed_home
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    with pytest.raises(fleet.FleetCliError, match="registered Codex Interface"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    claim = fleet.read_incarnation()
    claim["pending_operation"] = {"operation_id": "other"}
    fleet.write_incarnation(claim)
    with pytest.raises(fleet.FleetCliError, match="held binding disagrees"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []


def test_old_host_os_start_identity_must_match(fixed_home, monkeypatch):
    _home, store, bridge, _source, cwd = fixed_home
    monkeypatch.setattr(fleet_codex, "_process_identity", lambda _pid: None)
    with pytest.raises(fleet.FleetCliError, match="old host identity changed"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    assert fleet.read_incarnation().get("pending_operation") is None


def test_competing_normal_supervisor_reserve_is_blocked(fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    binding = fleet._codex_supervisor_binding(allowed_states={"held"})

    def compete():
        fleet._reserve_codex_supervisor_operation(
            binding, "competing-operation", "observe-send",
            allowed_states={"held"})

    bridge.on_respond = compete
    with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    assert store._load_path(store.path(6))["state"] == "pending"
    assert fleet.read_incarnation()["pending_operation"]["kind"] == "approval-response"


def test_lost_ack_keeps_reservation_and_never_replays(fixed_home):
    _home, store, bridge, _source, cwd = fixed_home
    bridge.lose_reply = True
    with pytest.raises(fleet.FleetCliError, match="never replay"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == [(6, {"decision": "decline"})]
    assert store._load_path(store.path(6))["state"] == "responded"
    assert fleet.read_incarnation()["pending_operation"]["kind"] == "approval-response"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert len(bridge.provider_writes) == 1


def test_capable_host_decline_refuses_and_existing_accept_still_works(
        fixed_home, monkeypatch):
    _home, store, bridge, _source, cwd = fixed_home
    monkeypatch.setattr(bridge, "supervisor_approval_reservation_supported",
                        lambda: True)
    with pytest.raises(fleet.FleetCliError, match="capable-host"):
        fleet.cmd_codex_decline_fixed(decline_args(store, cwd))
    assert bridge.provider_writes == []
    # The reviewed W179 route remains a separate command and takes its normal
    # capable-host response path with the fixture's original fake client.
    public = bridge.public
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: public)
    assert fleet.cmd_codex_respond(response_args(cwd)) == 0
    assert public.provider_writes == [("6", THREAD, TURN, {"decision": "accept"})]


def test_parser_exposes_separate_typed_verb_and_rejects_missing_cwd_mode():
    parser = fleet.build_parser()
    base = ["codex-decline-fixed", "6", "decline", "--request-id-type", "int"]
    with pytest.raises(SystemExit):
        parser.parse_args(base)
    with pytest.raises(SystemExit):
        parser.parse_args(["codex-decline-fixed", "6", "accept"])
    flags = {
        "inc": INC, "thread": THREAD, "turn": TURN,
        "host-generation": GEN, "method": METHOD,
        "item-id": "item-6", "command": COMMAND,
        "request-key": "1" * 64, "request-digest": "2" * 64,
        "old-host-sha256": OLD_HOST_SHA256,
        "host-process-identity": OldBridge.host_process_identity,
        "host-pid": str(OldBridge.host_pid),
        "request-cwd": "/synthetic/cwd",
    }
    argv = base + [piece for key, value in flags.items()
                   for piece in (f"--expect-{key}", value)]
    parsed = parser.parse_args(argv)
    assert (parsed.command, parsed.request_id_type, parsed.decision,
            parsed.expect_request_cwd) == (
                "codex-decline-fixed", "int", "decline", "/synthetic/cwd")
