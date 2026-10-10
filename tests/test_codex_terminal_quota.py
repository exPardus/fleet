"""Offline terminal-quota guards; fixtures are not provider capability proof."""
import copy
import json
from types import SimpleNamespace

import pytest
import fleet
from fleet_codex import CodexApprovalStore, OperationJournal
from test_codex_native_worker import (
    native_home, _install_record, _committed_active_operation,
    _write_turn_evidence, _record_approval_wait,
    THREAD_ID, TURN_ID, NEXT_TURN_ID,
)


@pytest.fixture
def quota_case(native_home, monkeypatch, request):
    home, lane = native_home
    schema = getattr(request, "param", sorted(fleet._TERMINAL_QUOTA_SCHEMAS)[0])
    row = _install_record(lane, status="dead-suspected", adapter_state="uncertain",
                          provider_status="systemError",
                          codex_error_code="usageLimitExceeded",
                          codex_schema_digest=schema,
                          permission_effective={"approvalPolicy": "on-request",
                              "approvalsReviewer": "user",
                              "sandbox": {"type": "workspaceWrite"}})
    journal = _committed_active_operation(home, lane)
    approvals = CodexApprovalStore(home, "host-generation-1")
    _write_turn_evidence(home, turn_status="failed")
    evidence_path = home / "state/codex/public-evidence" / f"{THREAD_ID}.{TURN_ID}.json"
    evidence = json.loads(evidence_path.read_text())
    evidence["error_code"] = "usageLimitExceeded"
    evidence_path.write_text(json.dumps(evidence))
    source = {"kind": "codex", "claim_id": "fixture-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: source)
    monkeypatch.setattr(fleet, "_mail_source_is_current", lambda value: value == source)
    public = {"id": THREAD_ID, "cwd": str(lane), "model": "gpt-5.6-luna",
              "status": {"type": "systemError", "activeFlags": []},
              "turns": [{"id": TURN_ID, "status": "failed", "itemsView": "full",
                         "items": [], "error": {"codexErrorInfo": "usageLimitExceeded"}}]}
    client = SimpleNamespace(generation="host-generation-1", schema_digest=schema,
                             host_pid=1, host_process_identity="host-1",
                             app_server_pid=2, app_server_process_identity="child-2")
    calls, commits = [], []
    case = SimpleNamespace(home=home, lane=lane, row=row, journal=journal,
                           approvals=approvals, evidence=evidence_path, source=source,
                           public=public, client=client, calls=calls, commits=commits,
                           on_read=None, reads=0, allowed=True, on_rate=None,
                           on_dispatch=None, failure=None, commit_failure=None,
                           turn_id=NEXT_TURN_ID, reply_generation=client.generation)
    def read(_client, thread, generation, *args, **kwargs):
        assert thread == THREAD_ID and generation == client.generation
        case.reads += 1
        if case.on_read:
            case.on_read(case.reads)
        return SimpleNamespace(generation=client.generation,
                               result={"thread": copy.deepcopy(public)})
    def rate(_client):
        if case.on_rate:
            case.on_rate()
        return case.allowed, None
    def call(operation, timeout):
        calls.append(operation)
        case.journal.prepare(operation)
        case.journal.accept(operation["operation_id"])
        if case.on_dispatch:
            case.on_dispatch()
        if case.failure:
            raise case.failure
        result = {"turn": {"id": case.turn_id, "status": "inProgress"}}
        case.journal.observe(operation["operation_id"], result)
        return SimpleNamespace(generation=case.reply_generation, result=result)
    def commit(opid):
        commits.append(opid)
        if case.commit_failure:
            raise case.commit_failure
        case.journal.commit(opid)
    client.call, client.commit = call, commit
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_codex_paged_thread_read", read)
    monkeypatch.setattr(fleet, "_codex_rate_limit_state", rate)
    # All successor/guard tests use this fake only. Dedicated tests below restore
    # the real empty allowlist and prove it never reaches the fake host either.
    enable_fixture_dispatch(case, monkeypatch)
    return case


def enable_fixture_dispatch(case, monkeypatch):
    # Never represents real-provider proof; production allowlist stays empty.
    monkeypatch.setattr(fleet, "_TERMINAL_QUOTA_DISPATCH_PROVEN_SCHEMAS",
                        frozenset({case.client.schema_digest}))


def row_change(case, **values):
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["cx-native"].update(values)
        fleet.save_registry(data)


def test_real_source_hold_has_no_reservation_or_dispatch(quota_case, monkeypatch):
    case = quota_case
    monkeypatch.setattr(fleet, "_TERMINAL_QUOTA_DISPATCH_PROVEN_SCHEMAS", frozenset())
    before = (case.home / "state/fleet.json").read_bytes()
    with pytest.raises(fleet.FleetCliError, match="source HOLD"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not case.calls and not case.commits and case.reads == 0
    assert (case.home / "state/fleet.json").read_bytes() == before
    assert len(case.journal.records()) == 1


@pytest.mark.parametrize("values", [
    {"substrate": "claude"}, {"archived_at": "2026-10-10T00:00:00Z"},
    {"provider_status": "idle"}, {"codex_error_code": "other"},
    {"status": "working"}, {"adapter_state": "active"},
    {"pending_operation": {"operation_id": "other"}},
    {"codex_thread_id": "bad"}, {"codex_turn_id": "bad"},
    {"codex_host_generation": "other"}, {"codex_schema_digest": "other"},
    {"cwd": "/other"}, {"last_operation_id": "other"},
    {"model": "claude"}, {"permission_effective": None}, {"turns": True},
    {"permission_effective": {"approvalPolicy": "never",
                             "approvalsReviewer": "user", "sandbox": {"type": "workspaceWrite"}}},
    {"permission_effective": {"approvalPolicy": "on-request",
                             "approvalsReviewer": "guardian", "sandbox": {"type": "workspaceWrite"}}},
    {"permission_effective": {"approvalPolicy": "on-request",
                             "approvalsReviewer": "user", "sandbox": {"type": "dangerFullAccess"}}},
])
def test_wrong_row_admission_refuses(quota_case, values):
    row_change(quota_case, **values)
    with pytest.raises((fleet.FleetCliError, ValueError)):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not quota_case.calls


@pytest.mark.parametrize("change", ["cwd", "thread", "turn", "newest", "flag",
                                   "status", "error", "items", "model"])
def test_public_failed_turn_must_be_exact_and_complete(quota_case, change):
    p = quota_case.public
    if change == "cwd": p["cwd"] = "/other"
    if change == "thread": p["id"] = NEXT_TURN_ID
    if change == "turn": p["turns"][0]["id"] = NEXT_TURN_ID
    if change == "newest": p["turns"].append(dict(p["turns"][0], id=NEXT_TURN_ID))
    if change == "flag": p["status"]["activeFlags"] = ["waitingOnApproval"]
    if change == "status": p["status"]["type"] = "notLoaded"
    if change == "error": p["turns"][0]["error"]["codexErrorInfo"] = "other"
    if change == "model": p["model"] = "other"
    if change == "items": p["turns"][0]["itemsView"] = "summary"
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not quota_case.calls


@pytest.mark.parametrize("allowed", [False, None])
def test_reset_must_be_authoritative(quota_case, allowed):
    quota_case.allowed = allowed
    with pytest.raises(fleet.FleetCliError, match="ordinaryUsageAllowed"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not quota_case.calls


@pytest.mark.parametrize("drift", ["row", "host", "schema", "interface", "mail", "claimed-mail",
                                   "callback", "journal", "evidence", "public-turn"])
def test_drift_between_probes_refuses_without_dispatch(quota_case, monkeypatch, drift):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    def mutate():
        if drift == "row": row_change(c, task="other-task")
        if drift == "host": c.client.host_process_identity = "other"
        if drift == "schema": c.client.schema_digest = "other"
        if drift == "interface": monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: {})
        if drift == "mail": (c.home / "mailbox" / f"{THREAD_ID}.md").write_text("keep")
        if drift == "claimed-mail": (c.home / "mailbox" / f"{THREAD_ID}.md.claimed.test").write_text("keep")
        if drift == "callback": _record_approval_wait(c.home)
        if drift == "journal": c.journal.prepare({"operation_id": "new", "method": "rpc",
                                               "payload": {"method": "turn/start", "params": {}}})
        if drift == "evidence":
            value = json.loads(c.evidence.read_text()); value["extra"] = "changed"
            c.evidence.write_text(json.dumps(value))
        if drift == "public-turn": c.public["turns"][0]["error"]["codexErrorInfo"] = "other"
    if drift in {"host", "schema"}:
        # A new client instance must carry a different snapshot of identity.
        old = copy.copy(c.client)
        def factory(_home):
            factory.n += 1
            if factory.n == 1: return old
            mutate(); return c.client
        factory.n = 0
        monkeypatch.setattr(fleet, "_codex_existing_client", factory)
    else:
        c.on_rate = mutate
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


def test_mail_arriving_during_final_public_read_is_preserved(quota_case, monkeypatch):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    c.on_read = lambda n: ((c.home / "mailbox" / f"{THREAD_ID}.md").write_text("keep") if n == 2 else None)
    with pytest.raises(fleet.FleetCliError, match="mail"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


@pytest.mark.parametrize("quota_case", sorted(fleet._TERMINAL_QUOTA_SCHEMAS), indirect=True)
def test_fixture_success_starts_distinct_same_thread_turn_once(quota_case, monkeypatch):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    assert fleet._resume_terminal_quota_codex("cx-native") == 0
    row = fleet.load_registry()["workers"]["cx-native"]
    assert row["codex_thread_id"] == THREAD_ID and row["codex_turn_id"] == NEXT_TURN_ID
    assert row["turns"] == 2 and row["status"] == "working"
    assert row["adapter_state"] == "active" and row["provider_status"] == "active"
    assert "pending_operation" not in row and "codex_error_code" not in row
    assert len(c.calls) == 1 and len(c.commits) == 1
    assert c.calls[0]["payload"]["method"] == "turn/start"
    assert c.calls[0]["payload"]["params"]["threadId"] == THREAD_ID
    assert c.journal.load(row["last_operation_id"])["state"] == "committed"
    assert c.journal.load("committed-spawn")["result"]["turn"]["id"] == TURN_ID


@pytest.mark.parametrize("outcome", ["lost", "same-turn", "generation", "commit", "row-cas"])
def test_uncertain_accepted_outcome_keeps_reservation_and_never_retries(quota_case, monkeypatch, outcome):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    if outcome == "lost": c.failure = TimeoutError("accepted reply lost")
    if outcome == "same-turn": c.turn_id = TURN_ID
    if outcome == "generation": c.reply_generation = "other"
    if outcome == "commit": c.commit_failure = OSError("commit lost")
    if outcome == "row-cas": c.on_dispatch = lambda: row_change(c, task="newer-task")
    with pytest.raises(fleet.FleetCliError, match="uncertain|row changed"):
        fleet._resume_terminal_quota_codex("cx-native")
    row = fleet.load_registry()["workers"]["cx-native"]
    assert row["codex_turn_id"] == TURN_ID and row["pending_operation"]
    assert len(c.calls) == 1
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_terminal_quota_codex("cx-native")
    assert len(c.calls) == 1


@pytest.mark.parametrize("values", [{"name": None}, {"force_now": True}, {"_fleet_home_explicit": False}])
def test_command_never_sweeps_or_force_bypasses_quota_guard(quota_case, monkeypatch, values):
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *args, **kwargs: None)
    args = dict(name="cx-native", terminal_quota=True, force_now=False,
                _fleet_home_explicit=True, nonce=None)
    args.update(values)
    with pytest.raises(fleet.FleetCliError, match="one named worker"):
        fleet.cmd_resume_limited(SimpleNamespace(**args))
    assert not quota_case.calls


def test_command_routes_to_held_exact_worker_without_dispatch(quota_case, monkeypatch):
    monkeypatch.setattr(fleet, "_TERMINAL_QUOTA_DISPATCH_PROVEN_SCHEMAS", frozenset())
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *args, **kwargs: None)
    args = SimpleNamespace(name="cx-native", terminal_quota=True, force_now=False,
                           _fleet_home_explicit=True, nonce=None)
    with pytest.raises(fleet.FleetCliError, match="source HOLD"):
        fleet.cmd_resume_limited(args)
    assert not quota_case.calls


@pytest.mark.parametrize("state", ["prepared", "accepted", "observed", "uncertain", "unknown-state"])
def test_unresolved_or_unknown_home_operation_refuses(quota_case, state):
    c = quota_case
    path = c.journal.path("committed-spawn")
    value = json.loads(path.read_text()); value["state"] = state
    path.write_text(json.dumps(value))
    with pytest.raises(fleet.FleetCliError, match="predecessor"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


@pytest.mark.parametrize("state", ["pending", "responding", "uncertain", "unknown"])
def test_callbacks_in_every_unresolved_state_refuse(quota_case, state):
    c = quota_case
    _record_approval_wait(c.home, state=state)
    with pytest.raises(fleet.FleetCliError, match="callback"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


def test_resolved_callback_inventory_change_still_refuses(quota_case):
    c = quota_case
    def add_resolved():
        store = _record_approval_wait(c.home, state="responded")
        store.resolve({"params": {"threadId": THREAD_ID, "requestId": "request-1"}})
    c.on_rate = add_resolved
    with pytest.raises(fleet.FleetCliError, match="inventory changed"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


@pytest.mark.parametrize("field,value", [("home", "/other"), ("generation", "other"),
                                         ("schema", True), ("payload_digest", "bad"),
                                         ("method", "other"), ("public_method", "thread/resume")])
def test_prior_journal_provenance_must_bind_exact_row(quota_case, field, value):
    c = quota_case
    path = c.journal.path("committed-spawn")
    obj = json.loads(path.read_text()); obj[field] = value
    path.write_text(json.dumps(obj))
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


@pytest.mark.parametrize("field,value", [("schema", True), ("turn_status", "completed"),
                                         ("thread_id", NEXT_TURN_ID), ("turn_id", NEXT_TURN_ID),
                                         ("error_code", "other")])
def test_durable_failed_evidence_must_bind_exact_quota_turn(quota_case, field, value):
    c = quota_case
    obj = json.loads(c.evidence.read_text()); obj[field] = value
    c.evidence.write_text(json.dumps(obj))
    with pytest.raises(fleet.FleetCliError):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


def test_allowance_can_be_revoked_during_final_probe(quota_case, monkeypatch):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    c.on_read = lambda n: setattr(c, "allowed", False) if n == 2 else None
    with pytest.raises(fleet.FleetCliError, match="allowance changed"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


def test_host_can_change_during_final_probe(quota_case, monkeypatch):
    c = quota_case
    enable_fixture_dispatch(c, monkeypatch)
    c.on_read = lambda n: setattr(c.client, "app_server_process_identity", "restarted") if n == 2 else None
    with pytest.raises(fleet.FleetCliError, match="identity changed"):
        fleet._resume_terminal_quota_codex("cx-native")
    assert not c.calls


def test_parser_exposes_explicit_terminal_quota_option():
    stripped, home = fleet.strip_global_fleet_home([
        "--fleet-home", "/fixture/home", "resume-limited", "cx-native", "--terminal-quota"])
    args = fleet.build_parser().parse_args(stripped)
    assert home is not None
    assert args.terminal_quota and args.name == "cx-native" and not args.force_now
