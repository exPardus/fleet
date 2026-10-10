"""Focused offline contract for one held supervisor turn interrupt."""

import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace

import fleet
import pytest
from fleet_codex import CodexApprovalStore, _approval_key
from test_codex_supervisor import (
    ITEM_ID,
    THREAD_ID,
    TURN_ID,
    FakeLifecycleClient,
    _seed_native_supervisor,
    _send_args,
)
from test_codex_supervisor import (
    supervisor_home as supervisor_home,  # noqa: PLC0414 - pytest fixture export
)

_PRODUCTION_FRESH_PROCESSES = fleet._sup_interrupt_fresh_processes


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

    def supervisor_approval_reservation_supported(self):
        from fleet_codex import HostRejected

        raise HostRejected("unknown host method")

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        if method == "turn/interrupt":
            entry = self.journal.prepare(operation)
            assert entry["state"] == "prepared"
            assert (
                self.journal.unresolved_predecessor(operation["operation_id"]) is None
            )
            self.journal.accept(operation["operation_id"])
            self.interrupt_calls += 1
            self.interrupted = True
            if self.lose_reply:
                self.journal.uncertain(operation["operation_id"], "lost reply")
                raise TimeoutError("lost reply after acceptance")
            self.journal.observe(operation["operation_id"], {})
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation,
                result={},
            )
        if method == "thread/read" and self.interrupted:
            self.thread_status = "idle"
            self.turn_status = "interrupted"
            self.active_flags = []
            if self.resolve_on_read:
                self.store.resolve(
                    {"params": {"requestId": 194, "threadId": THREAD_ID}}
                )
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
    params = {
        "threadId": THREAD_ID,
        "turnId": TURN_ID,
        "itemId": ITEM_ID,
        "startedAtMs": 1,
        "command": "true",
    }
    original = client.store.record_request(
        {"id": 194, "method": "item/commandExecution/requestApproval", "params": params}
    )
    key = _approval_key(client.generation, 194)
    callback_path = client.store.path(194)
    raw_hash = hashlib.sha256(callback_path.read_bytes()).hexdigest()
    source = {"kind": "codex", "claim_id": "genuine-test-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    monkeypatch.setattr(fleet, "_mail_source_is_current", lambda value: value == source)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes", lambda *_: client)
    args = SimpleNamespace(
        _fleet_home_explicit=True,
        preflight=False,
        request_id="194",
        request_id_type="int",
        expect_old_host_sha256=fleet.SUP_INTERRUPT_OLD_HOST_SHA256,
        expect_host_pid=101,
        expect_app_server_pid=102,
        expect_app_server_started_at=1.0,
        expect_inc=inc,
        expect_thread=THREAD_ID,
        expect_turn=TURN_ID,
        expect_host_generation=client.generation,
        expect_host_process_identity="host-identity",
        expect_app_server_process_identity="child-identity",
        expect_item_id=ITEM_ID,
        expect_request_key=key,
        expect_request_sha256=raw_hash,
    )
    return SimpleNamespace(
        home=supervisor_home,
        name=name,
        inc=inc,
        client=client,
        args=args,
        original=original,
        callback_path=callback_path,
    )


def _reservation(case):
    claim = fleet.read_incarnation()
    row = fleet.read_registry_no_repair()["workers"][case.name]
    return claim.get("pending_operation"), claim, row


def test_exact_terminal_resolved_settles_one_interrupt_and_preserves_siblings(case):
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
    assert (
        fleet.read_registry_no_repair()["workers"]["product"]
        == before["workers"]["product"]
    )
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
    operation = {
        "operation_id": "other-accepted",
        "method": "rpc",
        "payload": {
            "method": "turn/interrupt",
            "params": {"threadId": THREAD_ID, "turnId": TURN_ID},
        },
    }
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


@pytest.mark.parametrize(
    "change",
    ["claim", "row", "callback", "inventory", "source", "child", "request_type"],
)
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
        case.client.store.record_request(
            {
                "id": 195,
                "method": "item/commandExecution/requestApproval",
                "params": {
                    "threadId": THREAD_ID,
                    "turnId": TURN_ID,
                    "itemId": "second",
                    "startedAtMs": 2,
                },
            }
        )
    elif change == "source":
        monkeypatch.setattr(fleet, "_mail_source_is_current", lambda _: False)
    elif change == "child":
        monkeypatch.setattr(
            fleet,
            "_sup_interrupt_fresh_processes",
            lambda *_: (_ for _ in ()).throw(fleet.FleetCliError("child drift")),
        )
    elif change == "request_type":
        case.args.request_id_type = "string"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 0


def test_old_host_source_fixture_and_supported_approval_store(case):
    host = Path(__file__).parent / "fixtures" / "w273_a1ee_fleet_codex_host.py"
    assert (
        hashlib.sha256(host.read_bytes()).hexdigest()
        == fleet.SUP_INTERRUPT_OLD_HOST_SHA256
    )
    assert case.original["offered_decisions"] == [
        "accept",
        "acceptForSession",
        "decline",
        "cancel",
    ]
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
    case, monkeypatch, capsys
):
    queued = case.home / "mailbox" / f"{THREAD_ID}.md"
    queued.write_text("previous queued direction\n", encoding="utf-8")
    assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
    assert queued.read_text() == "previous queued direction\n"
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: case.client)
    case.client.interrupted = False
    assert (
        fleet.cmd_send(
            _send_args(
                message=(
                    "Process the already queued current backlog once; "
                    "do not repeat the old report command."
                )
            )
        )
        == 0
    )
    starts = [
        op for op in case.client.operations if op["payload"]["method"] == "turn/start"
    ]
    assert len(starts) == 1
    sent = starts[0]["payload"]["params"]["input"][0]["text"]
    assert "previous queued direction" in sent
    receipt = re.search(r"FLEET VERIFIED MAIL NOTICE ([^\s]+)", sent)
    assert receipt is not None
    capsys.readouterr()
    assert fleet.cmd_mail_verify(SimpleNamespace(mail_id=receipt.group(1))) == 0
    assert "Process the already queued current backlog once" in capsys.readouterr().out
    assert not queued.exists()


@pytest.mark.parametrize("capability", [True, False, "wrong-error", "lost-reply"])
def test_capable_or_ambiguous_host_refuses_without_reservation(
    case, monkeypatch, capability
):
    from fleet_codex import HostRejected, HostUnavailable

    def check():
        if capability == "wrong-error":
            raise HostRejected("unknown blocking server request")
        if capability == "lost-reply":
            raise HostUnavailable("lost capability reply")
        return capability

    monkeypatch.setattr(case.client, "supervisor_approval_reservation_supported", check)
    with pytest.raises((fleet.FleetCliError, HostUnavailable)):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert _reservation(case)[0] is None
    assert case.client.interrupt_calls == 0
    assert case.client.journal.records() == []


def test_old_host_source_pin_is_not_repointed_to_current_source(case):
    current = Path(fleet.__file__).with_name("fleet_codex_host.py").read_bytes()
    assert fleet.SUP_INTERRUPT_OLD_HOST_SHA256 == fleet.FIXED_DECLINE_OLD_HOST_SHA256
    assert hashlib.sha256(current).hexdigest() != fleet.SUP_INTERRUPT_OLD_HOST_SHA256
    case.args.preflight = True
    assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
    assert case.client.interrupt_calls == 0


class PinnedOldInterruptBridge:
    """Current envelopes through pinned old dispatcher, with no real provider."""

    def __init__(self, case, monkeypatch):
        from test_codex_fixed_decline import OldBridge

        source = fleet._registered_interface_mail_source()
        self.case = case
        self.inner = OldBridge(
            case.home, case.client.store, case.client, source, monkeypatch
        )
        self.generation = case.client.generation
        self.inner.host.generation = self.inner.transport.generation = self.generation
        self.inner.host.journal = case.client.journal
        self.inner.host.evidence = SimpleNamespace(record=lambda _: None)
        self.notifications_ready = False
        self.lose_interrupt_reply = False
        self.inner.host.client = SimpleNamespace(
            request=self.request,
            notifications=self.notifications,
            respond=lambda *_: pytest.fail("interrupt must never answer a callback"),
        )

    def request(self, method, params, timeout):
        public = self.case.client
        if method == "turn/interrupt":
            public.interrupt_calls += 1
            public.interrupted = True
            return {}
        if method == "thread/read" and public.interrupted:
            public.thread_status = "idle"
            public.turn_status = "interrupted"
            public.active_flags = []
            self.notifications_ready = public.resolve_on_read
        # Bypass the direct fixture's journal and store mutations: only the
        # exact old host controls acceptance and notification draining here.
        return FakeLifecycleClient.call(
            public,
            {
                "operation_id": "provider-fixture-read",
                "payload": {"method": method, "params": params},
            },
            timeout,
        ).result

    def notifications(self):
        if not self.notifications_ready:
            return []
        self.notifications_ready = False
        return [
            {
                "method": "serverRequest/resolved",
                "params": {"requestId": 194, "threadId": THREAD_ID},
            }
        ]

    def supervisor_approval_reservation_supported(self):
        return self.inner.supervisor_approval_reservation_supported()

    def call(self, operation, timeout):
        with self.inner.monkeypatch.context() as patch:
            if (
                self.lose_interrupt_reply
                and operation["payload"]["method"] == "turn/interrupt"
            ):
                original = self.inner.old._send_frame

                def lose(connection, payload, deadline):
                    if self.case.client.interrupt_calls:
                        connection.close()
                        raise OSError("synthetic interrupt ACK lost")
                    return original(connection, payload, deadline)

                patch.setattr(self.inner.old, "_send_frame", lose)
            return self.inner._old_call(
                lambda: self.inner.transport.call(operation, timeout)
            )

    def pending_approvals(self, thread_id, turn_id):
        return self.inner._old_call(
            lambda: self.inner.transport.pending_approvals(thread_id, turn_id)
        )

    def commit(self, operation_id):
        self.inner.transport.commit(operation_id)
        self.case.client.commits.append(operation_id)


@pytest.mark.parametrize(
    "outcome", ["resolved", "pending", "lost-reply", "foreign-peer"]
)
def test_pinned_old_dispatcher_interrupt_and_paged_drain(case, monkeypatch, outcome):
    bridge = PinnedOldInterruptBridge(case, monkeypatch)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _: bridge)
    monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes", lambda *_: bridge)
    if outcome == "pending":
        case.client.resolve_on_read = False
    elif outcome == "lost-reply":
        bridge.lose_interrupt_reply = True
    elif outcome == "foreign-peer":
        bridge.inner.old.interface_source_matches = lambda *_: False
        bridge.inner.old.Host._exact_home_supervisor_source = lambda *_: False
    if outcome == "resolved":
        assert fleet.cmd_codex_sup_interrupt_current(case.args) == 0
        assert _reservation(case)[0] is None
        assert case.client.interrupt_calls == 1
        assert case.client.journal.records()[0]["state"] == "committed"
        assert json.loads(case.callback_path.read_text())["state"] == "resolved"
        assert case.client.paging_operations
    else:
        with pytest.raises(fleet.FleetCliError, match="outcome uncertain"):
            fleet.cmd_codex_sup_interrupt_current(case.args)
        assert _reservation(case)[0] is not None
        assert case.client.interrupt_calls == (0 if outcome == "foreign-peer" else 1)
        assert not case.client.commits
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_codex_sup_interrupt_current(case.args)
        assert case.client.interrupt_calls == (0 if outcome == "foreign-peer" else 1)


@pytest.mark.parametrize(
    "field",
    [
        "generation",
        "host_pid",
        "host_process_identity",
        "app_server_pid",
        "app_server_process_identity",
        "app_server_started_at",
        "os_host",
        "os_child",
    ],
)
def test_fresh_process_pin_drift_refuses(case, monkeypatch, field):
    import fleet_codex

    helper = _PRODUCTION_FRESH_PROCESSES
    expected = SimpleNamespace(
        generation=case.args.expect_host_generation,
        host_pid=case.args.expect_host_pid,
        host_process_identity=case.args.expect_host_process_identity,
        app_server_pid=case.args.expect_app_server_pid,
        app_server_process_identity=case.args.expect_app_server_process_identity,
        app_server_started_at=case.args.expect_app_server_started_at,
    )
    identities = {
        expected.host_pid: expected.host_process_identity,
        expected.app_server_pid: expected.app_server_process_identity,
    }
    if field in {"os_host", "os_child"}:
        pid = expected.host_pid if field == "os_host" else expected.app_server_pid
        identities[pid] = None
    else:
        setattr(expected, field, 999 if field.endswith("pid") else "changed")
    monkeypatch.setattr(
        fleet_codex.CodexHostClient, "connect_existing", lambda _: expected
    )
    monkeypatch.setattr(
        fleet_codex, "_process_identity", lambda pid: identities.get(pid)
    )
    monkeypatch.setattr(fleet_codex, "_process_identities_match", lambda a, b: a == b)
    with pytest.raises(fleet.FleetCliError, match="changed"):
        helper(case.args, case.args.expect_host_generation)


def test_preflight_checks_original_child_after_public_reads(case, monkeypatch):
    case.args.preflight = True
    monkeypatch.setattr(
        fleet,
        "_sup_interrupt_fresh_processes",
        lambda *_: (_ for _ in ()).throw(
            fleet.FleetCliError("original child replaced")
        ),
    )
    with pytest.raises(fleet.FleetCliError, match="child replaced"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert _reservation(case)[0] is None
    assert case.client.interrupt_calls == 0


@pytest.mark.parametrize(
    "defect",
    [
        "missing-ok",
        "missing-result",
        "missing-error",
        "missing-operation_id",
        "missing-host_generation",
        "missing-fleet_home",
        "missing-payload_digest",
        "ok-null",
        "ok-zero",
        "ok-string",
        "contradictory-result",
        "error-object",
        "error-empty",
        "error-oversized",
        "success-with-error",
        "extra-key",
        "duplicate-ok",
        "non-finite-result",
    ],
)
def test_real_client_malformed_capability_envelope_never_proves_old_host(
    tmp_path, monkeypatch, defect
):
    import fleet_codex

    client = object.__new__(fleet_codex.CodexHostClient)
    client.home = tmp_path
    client.generation = "synthetic-generation"
    client._endpoint = "synthetic-endpoint"
    client._authkey = b"synthetic-key"
    client._encoded_key = "synthetic-encoded-key"
    captured = {}
    monkeypatch.setattr(
        fleet_codex,
        "_connect_authenticated",
        lambda *_: SimpleNamespace(close=lambda: None),
    )
    monkeypatch.setattr(
        fleet_codex,
        "_send_frame",
        lambda _c, encoded, _d: captured.update(json.loads(encoded)),
    )

    def receive(*_):
        envelope = {
            key: captured[key]
            for key in (
                "operation_id",
                "host_generation",
                "fleet_home",
                "payload_digest",
            )
        }
        envelope.update(ok=False, result=None, error="unknown host method")
        if defect.startswith("missing-"):
            envelope.pop(defect.removeprefix("missing-"))
        elif defect in {"ok-null", "ok-zero", "ok-string"}:
            envelope["ok"] = {"ok-null": None, "ok-zero": 0, "ok-string": "false"}[
                defect
            ]
        elif defect == "contradictory-result":
            envelope["result"] = {"version": 1}
        elif defect == "error-object":
            envelope["error"] = {"message": "unknown host method"}
        elif defect == "error-empty":
            envelope["error"] = ""
        elif defect == "error-oversized":
            envelope["error"] = "x" * 301
        elif defect == "success-with-error":
            envelope["ok"] = True
        elif defect == "extra-key":
            envelope["unreviewed"] = True
        elif defect == "non-finite-result":
            envelope["result"] = float("nan")
        raw = json.dumps(envelope)
        if defect == "duplicate-ok":
            raw = raw.replace('"ok": false', '"ok": true, "ok": false')
        return raw.encode()

    monkeypatch.setattr(fleet_codex, "_recv_frame", receive)
    with pytest.raises((fleet.FleetCliError, fleet_codex.HostUnavailable)):
        fleet._sup_interrupt_old_host(client)


@pytest.mark.parametrize(
    "evidence",
    ["response", "responding_at", "responded_at", "uncertain_at", "resolved_at"],
)
def test_pending_callback_with_consumption_evidence_refuses_before_reservation(
    case, evidence
):
    record = json.loads(case.callback_path.read_text())
    record[evidence] = {"decision": "decline"} if evidence == "response" else 1.0
    case.callback_path.write_text(json.dumps(record))
    case.callback_path.chmod(0o600)
    # Match the supplied byte pin so the test measures contradictory state,
    # rather than being satisfied by a hash mismatch.
    case.args.expect_request_sha256 = hashlib.sha256(
        case.callback_path.read_bytes()
    ).hexdigest()
    with pytest.raises(fleet.FleetCliError, match="consumption evidence"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert _reservation(case)[0] is None
    assert case.client.interrupt_calls == 0


@pytest.mark.parametrize(
    "drift", ["public-callback", "durable-only", "active-turn", "new-turn"]
)
def test_callback_or_turn_drift_after_commit_retains_reservation(
    case, monkeypatch, drift
):
    original = case.client.commit

    def commit(operation_id):
        original(operation_id)
        if drift in {"public-callback", "durable-only"}:
            case.client.store.record_request(
                {
                    "id": 195,
                    "method": "item/commandExecution/requestApproval",
                    "params": {
                        "threadId": THREAD_ID,
                        "turnId": TURN_ID,
                        "itemId": "late-item",
                        "startedAtMs": 2,
                    },
                }
            )
            if drift == "durable-only":
                monkeypatch.setattr(case.client, "pending_approvals", lambda *_: [])
        elif drift == "active-turn":
            case.client.interrupted = False
            case.client.thread_status = "active"
            case.client.turn_status = "inProgress"
            case.client.active_flags = ["waitingOnApproval"]
        else:
            from test_codex_supervisor import SUCCESSOR_TURN_ID

            case.client.newer_turn = SUCCESSOR_TURN_ID

    monkeypatch.setattr(case.client, "commit", commit)
    with pytest.raises(fleet.FleetCliError, match="reservation retained; never replay"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    pending, claim, row = _reservation(case)
    assert pending is not None
    assert row["adapter_state"] == "mutating"
    assert claim["pending_operation"] == pending
    assert case.client.interrupt_calls == 1
    assert case.client.journal.records()[0]["state"] == "committed"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 1


@pytest.mark.parametrize("replacement_read", ["thread", "approval-list"])
def test_final_public_read_process_replacement_retains_reservation(
    case, monkeypatch, replacement_read
):
    observed = fleet._codex_supervisor_observe
    pending = case.client.pending_approvals
    committed = {"done": False, "replaced": False}
    commit = case.client.commit

    def mark_commit(operation_id):
        commit(operation_id)
        committed["done"] = True

    def observe(*args, **kwargs):
        result = observed(*args, **kwargs)
        if committed["done"] and replacement_read == "thread":
            committed["replaced"] = True
        return result

    def list_pending(*args):
        result = pending(*args)
        if committed["done"] and replacement_read == "approval-list":
            committed["replaced"] = True
        return result

    def fresh(*_):
        if committed["replaced"]:
            raise fleet.FleetCliError("original process replaced by final public read")
        return case.client

    monkeypatch.setattr(case.client, "commit", mark_commit)
    monkeypatch.setattr(case.client, "pending_approvals", list_pending)
    monkeypatch.setattr(fleet, "_codex_supervisor_observe", observe)
    monkeypatch.setattr(fleet, "_sup_interrupt_fresh_processes", fresh)
    with pytest.raises(fleet.FleetCliError, match="reservation retained; never replay"):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    reservation, claim, row = _reservation(case)
    assert committed["replaced"]
    assert reservation is not None and claim["pending_operation"] == reservation
    assert row["adapter_state"] == "mutating"
    assert case.client.interrupt_calls == 1
    assert case.client.journal.records()[0]["state"] == "committed"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_codex_sup_interrupt_current(case.args)
    assert case.client.interrupt_calls == 1
