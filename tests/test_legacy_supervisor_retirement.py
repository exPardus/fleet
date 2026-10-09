"""Bounded retirement of a stale legacy supervisor from a Codex Interface."""
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


OLD_SID = "11111111-2222-4333-8444-555555555555"
OTHER_SID = "66666666-7777-4888-8999-aaaaaaaaaaaa"
INC = "inc-20260101T000000Z-abcd"
NAME = f"sup|{INC}|boot"
SOURCE = {"kind": "codex", "claim_id": "registered-interface"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# Active goals\n")
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}')
    beat = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claim = {"incarnation_id": INC, "session_id": OLD_SID,
             "lineage_id": "lin-20260101T000000Z-abcd", "claimed_via": "fresh",
             "claimed_at": beat, "heartbeat_at": beat,
             "nonce_hash": "secret-digest", "nonce_seq": 4}
    fleet.write_incarnation(claim)
    holder = fleet.new_worker_record(OLD_SID, tmp_path, "old supervisor",
                                     "bypass", dispatch_kind="bg")
    holder["status"] = "dead-suspected"  # advisory, not retirement proof
    active = fleet.new_worker_record(None, tmp_path, "live product lane",
                                     "accept", model="codex:gpt-6-sol",
                                     dispatch_kind="codex-app-server",
                                     substrate="codex")
    active.update({"status": "working", "codex_thread_id": OTHER_SID})
    fleet.save_registry({"workers": {NAME: holder, "product-lane": active}})
    (tmp_path / "mailbox").mkdir()
    (tmp_path / "mailbox" / f"{OLD_SID}.md").write_text("pending old mail\n")
    (tmp_path / "mailbox" / "claimed.md").write_text("claimed mail\n")
    (tmp_path / "supervisor" / "QUEUE.md").write_text("current queue\n")
    (tmp_path / "supervisor" / "JOURNAL.md").write_text("current journal\n")
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: SOURCE)
    return tmp_path


def args(**updates):
    values = {"expect_inc": INC, "expect_sid": OLD_SID,
              "_fleet_home_explicit": True}
    values.update(updates)
    return SimpleNamespace(**values)


def roster(old=None, extra=None):
    entries = [{"sessionId": OLD_SID, "name": NAME, "state": "done"}]
    if old is not None:
        entries[0] = old
    entries.extend(extra or [])
    return True, entries


def test_retirement_preserves_live_product_and_all_mail_and_queue(home):
    before_registry = copy.deepcopy(fleet.read_registry_no_repair())
    before_files = {str(path.relative_to(home)): path.read_bytes() for path in (
        home / "mailbox" / f"{OLD_SID}.md", home / "mailbox" / "claimed.md",
        home / "supervisor" / "QUEUE.md", home / "supervisor" / "JOURNAL.md")}
    assert fleet.cmd_sup_retire_legacy(args(), roster_fn=roster) == 0
    released = fleet.read_incarnation()
    assert released["state"] == "released"
    assert released["released_by_sid"] == OLD_SID
    assert "nonce_hash" not in released and "session_id" not in released
    after = fleet.read_registry_no_repair()
    assert after["workers"]["product-lane"] == before_registry["workers"]["product-lane"]
    assert after["workers"][NAME]["status"] == "dead"
    assert {str(path.relative_to(home)): path.read_bytes() for path in (
        home / "mailbox" / f"{OLD_SID}.md", home / "mailbox" / "claimed.md",
        home / "supervisor" / "QUEUE.md", home / "supervisor" / "JOURNAL.md")} == before_files
    evidence = json.loads((home / released["retirement_evidence"]).read_text())
    assert evidence["phase"] == "complete"
    assert evidence["claim"]["nonce_hash"] == "secret-digest"
    assert evidence["holder_row_name"] == NAME
    assert fleet.supervisor_claim_decision(released, set(), None)[0] == "claim"


def test_old_roster_absent_with_unrelated_live_worker_still_retires(home):
    product = {"sessionId": OTHER_SID, "name": "product-lane",
               "state": "working", "status": "busy", "pid": 88}
    assert fleet.cmd_sup_retire_legacy(args(),
                                       roster_fn=lambda: (True, [product])) == 0
    assert fleet.read_registry_no_repair()["workers"]["product-lane"]["status"] == "working"


def test_stopped_holder_and_done_predecessors_retire_with_exact_home(home):
    before_product = copy.deepcopy(
        fleet.read_registry_no_repair()["workers"]["product-lane"])
    old = {"sessionId": OLD_SID, "name": NAME, "state": "stopped",
           "cwd": str(home)}
    predecessors = [
        {"sessionId": OTHER_SID, "name": f"sup|{INC}|successor",
         "state": "done", "cwd": str(home)},
        {"sessionId": "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff",
         "name": "sup|inc-20260101T010000Z-bbbb|successor",
         "state": "done", "cwd": str(home)},
    ]
    assert fleet.cmd_sup_retire_legacy(
        args(), roster_fn=lambda: roster(old, predecessors)) == 0
    released = fleet.read_incarnation()
    assert released["state"] == "released"
    assert fleet.read_registry_no_repair()["workers"]["product-lane"] == before_product
    evidence = json.loads((home / released["retirement_evidence"]).read_text())
    assert evidence["phase"] == "complete"
    assert [entry["state"] for entry in evidence["roster_supervisor_rows"]] == [
        "stopped", "done", "done"]


@pytest.mark.parametrize("mutate", [
    lambda claim: claim.update(provider="codex"),
    lambda claim: claim.update(holder={"provider": "codex", "thread_id": OTHER_SID}),
    lambda claim: claim.update(state="released"),
    lambda claim: claim.update(session_id=OTHER_SID),
    lambda claim: claim.update(heartbeat_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    lambda claim: claim.update(handoff_pending=[{"successor_inc": "inc-other"}]),
])
def test_wrong_kind_identity_freshness_or_handoff_refuses(home, mutate):
    claim = fleet.read_incarnation()
    mutate(claim)
    fleet.write_incarnation(claim)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    assert fleet.read_incarnation() == claim
    assert not (home / "state" / "supervisor-retirements").exists()


@pytest.mark.parametrize("pending", [
    "MALFORMED-UNRESOLVED-SUCCESSOR", None, False, 0, {}, [],
    [None], [{"missing_successor_inc": "unknown"}],
    {"successor_inc": None}, {"successor_inc": "inc-other"},
])
def test_present_handoff_pending_refuses_without_losing_claim_or_mail(home, pending):
    claim = fleet.read_incarnation()
    claim["handoff_pending"] = pending
    fleet.write_incarnation(claim)
    registry = fleet.read_registry_no_repair()
    mail = {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()}
    with pytest.raises(fleet.FleetCliError, match="successor|handoff"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    assert fleet.read_incarnation() == claim
    assert fleet.read_registry_no_repair() == registry
    assert {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()} == mail
    assert not (home / "state" / "supervisor-retirements").exists()


@pytest.mark.parametrize("old", [
    {"sessionId": OLD_SID, "name": NAME, "state": "working", "pid": 42},
    {"sessionId": OLD_SID, "name": NAME, "state": "working"},
    {"sessionId": OLD_SID, "name": NAME, "state": "done", "pid": 42},
    {"sessionId": OLD_SID, "name": NAME, "state": "done", "pid": False},
    {"sessionId": OLD_SID, "name": NAME, "state": "done", "status": "idle"},
    {"sessionId": OLD_SID, "name": NAME, "state": "done", "status": "working"},
    {"sessionId": OLD_SID, "name": NAME, "state": "stopped", "pid": False},
    {"sessionId": OLD_SID, "name": NAME, "state": "stopped", "status": "idle"},
    {"sessionId": OLD_SID, "name": NAME, "state": "stopped", "status": "working"},
    {"sessionId": OLD_SID, "name": NAME, "state": "unknown"},
])
def test_live_or_ambiguous_old_body_refuses(home, old):
    claim = fleet.read_incarnation()
    registry = fleet.read_registry_no_repair()
    mail = {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()}
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=lambda: roster(old))
    assert fleet.read_incarnation() == claim
    assert fleet.read_registry_no_repair() == registry
    assert {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()} == mail
    assert not (home / "state" / "supervisor-retirements").exists()


@pytest.mark.parametrize("state", ["done", "stopped"])
def test_status_bearing_predecessor_refuses(home, state):
    predecessor = {"sessionId": OTHER_SID, "name": f"sup|{INC}|successor",
                   "state": state, "status": "working", "cwd": str(home)}
    claim = fleet.read_incarnation()
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(
            args(), roster_fn=lambda: roster(extra=[predecessor]))
    assert fleet.read_incarnation() == claim
    assert not (home / "state" / "supervisor-retirements").exists()


def test_live_predecessor_refuses_and_unrelated_product_does_not(home):
    predecessor = {"sessionId": OTHER_SID,
                   "name": f"sup|{INC}|successor", "state": "working",
                   "status": "busy", "pid": 52, "cwd": str(home)}
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=lambda: roster(extra=[predecessor]))
    product = {**predecessor, "name": "product-lane"}
    assert fleet.cmd_sup_retire_legacy(args(),
                                       roster_fn=lambda: roster(extra=[product])) == 0


def test_registry_bound_predecessor_without_roster_name_refuses(home):
    registry = fleet.read_registry_no_repair()
    predecessor = fleet.new_worker_record(
        OTHER_SID, home, "old successor", "bypass", dispatch_kind="bg")
    registry["workers"][f"sup|{INC}|successor"] = predecessor
    fleet.save_registry(registry)
    unnamed = {"sessionId": OTHER_SID, "state": "working", "pid": 77}
    with pytest.raises(fleet.FleetCliError, match="predecessor|supervisor"):
        fleet.cmd_sup_retire_legacy(args(),
                                    roster_fn=lambda: roster(extra=[unnamed]))


def test_roster_change_before_commit_refuses(home):
    calls = 0
    def changing():
        nonlocal calls
        calls += 1
        if calls == 2:
            return roster({"sessionId": OLD_SID, "name": NAME,
                           "state": "working", "pid": 43})
        return roster()
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=changing)
    assert calls == 2
    assert fleet.read_incarnation().get("state") != "released"


@pytest.mark.parametrize("target", ["claim", "row", "journal"])
def test_claim_or_holder_change_before_commit_refuses(home, target):
    calls = 0
    def drifting_roster():
        nonlocal calls
        calls += 1
        if calls == 2:
            if target == "claim":
                claim = fleet.read_incarnation()
                claim["heartbeat_at"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
                fleet.write_incarnation(claim)
            elif target == "row":
                registry = fleet.read_registry_no_repair()
                registry["workers"][NAME]["last_activity"] = "changed"
                fleet.save_registry(registry)
            else:
                with open(fleet.supervisor_journal_path(), "a") as stream:
                    stream.write("concurrent checkpoint\n")
        return roster()
    with pytest.raises(fleet.FleetCliError, match="changed"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=drifting_roster)
    assert calls == 2
    assert fleet.read_incarnation().get("state") != "released"


def test_new_supervisor_predecessor_row_before_commit_refuses(home):
    calls = 0
    def drifting_roster():
        nonlocal calls
        calls += 1
        if calls == 2:
            registry = fleet.read_registry_no_repair()
            predecessor = fleet.new_worker_record(
                OTHER_SID, home, "new predecessor", "bypass", dispatch_kind="bg")
            predecessor["status"] = "working"
            registry["workers"][f"sup|{INC}|successor"] = predecessor
            fleet.save_registry(registry)
        return roster()
    with pytest.raises(fleet.FleetCliError, match="changed"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=drifting_roster)
    assert calls == 2
    assert fleet.read_incarnation().get("state") != "released"
    assert fleet.read_registry_no_repair()["workers"][f"sup|{INC}|successor"]["status"] == "working"
    assert not (home / "state" / "supervisor-retirements").exists()


def test_unrelated_product_row_change_during_proof_is_preserved(home):
    calls = 0
    def changing_product():
        nonlocal calls
        calls += 1
        if calls == 2:
            registry = fleet.read_registry_no_repair()
            registry["workers"]["product-lane"]["last_activity"] = "product-progress"
            fleet.save_registry(registry)
        return roster()
    assert fleet.cmd_sup_retire_legacy(args(), roster_fn=changing_product) == 0
    assert calls == 2
    assert fleet.read_registry_no_repair()["workers"]["product-lane"]["last_activity"] == "product-progress"


def test_registry_write_failure_keeps_prepared_audit_and_blocks_native_spawn(
        home, monkeypatch):
    before = fleet.read_registry_no_repair()
    mail = {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()}
    original_save = fleet.save_registry
    def fail_save(_data):
        raise OSError("injected registry write failure")
    monkeypatch.setattr(fleet, "save_registry", fail_save)
    with pytest.raises(OSError, match="injected"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    monkeypatch.setattr(fleet, "save_registry", original_save)
    released = fleet.read_incarnation()
    assert released["state"] == "released"
    evidence_path = home / released["retirement_evidence"]
    evidence = json.loads(evidence_path.read_text())
    assert evidence["phase"] == "prepared"
    assert evidence["claim"]["session_id"] == OLD_SID
    assert fleet.read_registry_no_repair() == before
    assert {p.name: p.read_bytes() for p in (home / "mailbox").iterdir()} == mail
    monkeypatch.setattr(fleet, "_fetch_agents_roster", roster)
    monkeypatch.setattr(fleet, "_codex_native_client",
                        lambda _home: pytest.fail("provider thread must not start"))
    with pytest.raises(fleet.FleetCliError, match="incomplete"):
        fleet._dispatch_codex_supervisor_body("campaign", "bypass", "codex:gpt-6-sol")
    assert fleet.read_incarnation() == released
    assert json.loads(evidence_path.read_text()) == evidence


@pytest.mark.parametrize("damage", ["prepared", "missing", "row"])
def test_native_spawn_requires_complete_matching_retirement(home, monkeypatch, damage):
    assert fleet.cmd_sup_retire_legacy(args(), roster_fn=roster) == 0
    released = fleet.read_incarnation()
    evidence_path = home / released["retirement_evidence"]
    if damage == "prepared":
        evidence = json.loads(evidence_path.read_text())
        evidence["phase"] = "prepared"
        evidence_path.write_text(json.dumps(evidence))
    elif damage == "missing":
        evidence_path.unlink()
    else:
        registry = fleet.read_registry_no_repair()
        registry["workers"][NAME]["status"] = "dead-suspected"
        fleet.save_registry(registry)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", roster)
    monkeypatch.setattr(fleet, "_codex_native_client",
                        lambda _home: pytest.fail("provider thread must not start"))
    with pytest.raises(fleet.FleetCliError, match="incomplete"):
        fleet._dispatch_codex_supervisor_body("campaign", "bypass", "codex:gpt-6-sol")
    assert fleet.read_incarnation() == released


def test_wrong_interface_home_or_bad_roster_refuses(home, monkeypatch):
    with pytest.raises(fleet.FleetCliError, match="explicit"):
        fleet.cmd_sup_retire_legacy(args(_fleet_home_explicit=False), roster_fn=roster)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: None)
    with pytest.raises(fleet.FleetCliError, match="authenticated"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", lambda: SOURCE)
    for fetch in (lambda: (False, "unavailable"), lambda: (True, [])):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_retire_legacy(args(), roster_fn=fetch)
    assert fleet.read_incarnation().get("state") != "released"


def test_interface_source_change_during_proof_refuses(home, monkeypatch):
    calls = 0
    def source():
        nonlocal calls
        calls += 1
        return SOURCE if calls == 1 else {"kind": "codex", "claim_id": "other"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source", source)
    with pytest.raises(fleet.FleetCliError, match="changed"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    assert fleet.read_incarnation().get("state") != "released"


def test_malformed_provider_row_refuses(home):
    with pytest.raises(fleet.FleetCliError, match="malformed"):
        fleet.cmd_sup_retire_legacy(args(),
                                    roster_fn=lambda: (True, ["not a row"]))


def test_corrupt_claim_and_registry_refuse_without_quarantine(home):
    fleet.incarnation_path().write_text("{bad")
    with pytest.raises(fleet.FleetCliError, match="corrupt"):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    assert fleet.incarnation_path().read_text() == "{bad"
    fleet.incarnation_path().write_text(json.dumps({"incarnation_id": INC,
                                                      "session_id": OLD_SID}))
    fleet.registry_path().write_text("{bad")
    with pytest.raises(fleet.RegistryCorruptError):
        fleet.cmd_sup_retire_legacy(args(), roster_fn=roster)
    assert fleet.registry_path().read_text() == "{bad"


def test_parser_requires_exact_identity_and_has_no_force_flag(home):
    parser = fleet.build_parser()
    parsed = parser.parse_args(["sup-retire-legacy",
                                "--expect-inc", INC, "--expect-sid", OLD_SID])
    assert parsed.expect_inc == INC and parsed.expect_sid == OLD_SID
    with pytest.raises(SystemExit):
        parser.parse_args(["sup-retire-legacy", "--expect-inc", INC,
                           "--expect-sid", OLD_SID, "--force"])
