"""Offline exact-result adoption: every refused send keeps its row and mail."""
import json
from types import SimpleNamespace

import pytest

import fleet
from fleet_codex import HostRejected, OperationJournal
from test_codex_native_worker import (
    NEXT_TURN_ID, THREAD_ID, TURN_ID, _install_record, native_home,
)

OP = "worker-send-proof"
GEN = "host-generation-1"


def prepare(home, lane, *, kind="turn/start", state="committed", result=None):
    journal = OperationJournal(home.resolve(), GEN)
    journal.prepare({
        "operation_id": OP, "method": "rpc",
        "payload": {"method": kind, "params": {
            "threadId": THREAD_ID,
            "input": [{"type": "text", "text": "retained dispatch", "text_elements": []}],
            **({"expectedTurnId": TURN_ID} if kind == "turn/steer" else {}),
        }},
        "recovery": {
            "kind": f"worker/{kind}", "fleet_name": "cx-native",
            "thread_id": THREAD_ID, "previous_turn_id": TURN_ID,
            "canonical_cwd": str(lane),
        },
    })
    journal.accept(OP)
    if state == "uncertain":
        journal.uncertain(OP, "unknown acceptance")
    elif state != "accepted":
        if result is None:
            result = ({"turn": {"id": NEXT_TURN_ID, "status": "inProgress"}}
                      if kind == "turn/start" else {"turnId": TURN_ID})
        journal.observe(OP, result)
        if state == "committed":
            journal.commit(OP)
    return journal


def identity(lane):
    return dict(fleet_name="cx-native", thread_id=THREAD_ID,
                previous_turn_id=TURN_ID, canonical_cwd=str(lane))


@pytest.mark.parametrize("state", ["observed", "committed"])
@pytest.mark.parametrize("kind", ["turn/start", "turn/steer"])
def test_adoption_preserves_successful_raw_result(native_home, state, kind):
    home, lane = native_home
    journal = prepare(home, lane, kind=kind, state=state)
    original = journal.load(OP)["result"]
    target = NEXT_TURN_ID if kind == "turn/start" else TURN_ID
    journal.adopt_worker_turn(OP, turn_id=target, **identity(lane))
    assert journal.load(OP)["state"] == "committed"
    assert journal.load(OP)["result"] == original
    assert journal.worker_turn_id(OP, **identity(lane)) == target


@pytest.mark.parametrize("state", ["observed", "committed"])
@pytest.mark.parametrize("result", [
    {"turn": {"id": NEXT_TURN_ID, "status": "inProgress"}},
    {"turn": {"id": TURN_ID, "status": "inProgress"}},
    {"turn": {"id": NEXT_TURN_ID, "status": "inProgress"}, "turnId": TURN_ID},
    {"turn": {"id": NEXT_TURN_ID, "status": "inProgress"}, "threadId": TURN_ID},
    {"turn": {"id": NEXT_TURN_ID, "status": "completed"}},
    {"turn": {"id": "not-an-id", "status": "inProgress"}},
    {},
])
def test_adoption_rejects_conflicting_observed_and_committed_results(native_home, state, result):
    home, lane = native_home
    journal = prepare(home, lane, state=state, result=result)
    before = journal.path(OP).read_bytes()
    with pytest.raises(HostRejected):
        journal.adopt_worker_turn(OP, turn_id=TURN_ID, **identity(lane))
    assert journal.path(OP).read_bytes() == before


@pytest.mark.parametrize("state", ["accepted", "uncertain"])
def test_no_history_can_release_unresolved_acceptance(native_home, state):
    home, lane = native_home
    journal = prepare(home, lane, state=state)
    before = journal.path(OP).read_bytes()
    with pytest.raises(HostRejected):
        journal.adopt_worker_turn(OP, turn_id=NEXT_TURN_ID, **identity(lane))
    assert journal.path(OP).read_bytes() == before


@pytest.mark.parametrize("key,value", [
    ("fleet_name", "another"), ("thread_id", TURN_ID),
    ("previous_turn_id", NEXT_TURN_ID), ("canonical_cwd", "/another"),
])
def test_identity_mismatch_cannot_commit(native_home, key, value):
    home, lane = native_home
    journal = prepare(home, lane, state="observed")
    pins = identity(lane); pins[key] = value
    before = journal.path(OP).read_bytes()
    with pytest.raises(HostRejected):
        journal.adopt_worker_turn(OP, turn_id=NEXT_TURN_ID, **pins)
    assert journal.path(OP).read_bytes() == before


def frozen(native_home, monkeypatch, *, kind="turn/start", state="committed", result=None):
    home, lane = native_home
    row = _install_record(
        lane, status="dead-suspected", adapter_state="uncertain", last_operation_id=OP,
        pending_operation={"operation_id": OP, "kind": kind, "at": "2026-10-10T00:00:00Z"})
    journal = prepare(home, lane, kind=kind, state=state, result=result)
    claim = home / "mailbox" / f"{THREAD_ID}.md.claimed.4242"
    claim.write_text("retained dispatch", encoding="utf-8")
    client = SimpleNamespace(generation=GEN)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda home: client)
    calls = []

    def observe(binding, client=None, *, hydrate_items=True):
        calls.append(binding.turn_id)
        assert hydrate_items is False
        return dict(provider_status="active", turn_status="inProgress", active_flags=[])
    monkeypatch.setattr(fleet, "_codex_worker_observe", observe)
    return home, lane, row, journal, claim, client, calls


@pytest.mark.parametrize("state", ["observed", "committed"])
@pytest.mark.parametrize("kind", ["turn/start", "turn/steer"])
def test_repair_adopts_proven_success_once(native_home, monkeypatch, state, kind):
    home, lane, row, journal, claim, client, calls = frozen(
        native_home, monkeypatch, state=state, kind=kind)
    raw = journal.load(OP)["result"]
    assert fleet._reconcile_frozen_codex_worker_operations() == ["cx-native"]
    target = NEXT_TURN_ID if kind == "turn/start" else TURN_ID
    assert calls == [target]
    after = fleet.load_registry()["workers"]["cx-native"]
    assert "pending_operation" not in after
    assert after["codex_turn_id"] == target
    assert after["status"] == "working"
    assert journal.load(OP)["result"] == raw
    assert not claim.exists()
    assert fleet._reconcile_frozen_codex_worker_operations() == []


@pytest.mark.parametrize("state", ["accepted", "uncertain"])
def test_repair_does_not_read_provider_for_unknown_acceptance(native_home, monkeypatch, state):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch, state=state)
    original = journal.path(OP).read_bytes()
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.read_text() == "retained dispatch"
    assert journal.path(OP).read_bytes() == original
    assert calls == []


@pytest.mark.parametrize("drift", ["journal", "row", "claim_inode", "claim_bytes", "callback", "generation"])
@pytest.mark.parametrize("state", ["observed", "committed"])
def test_conflict_during_observation_preserves_reservation_and_claim(native_home, monkeypatch, drift, state):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch, state=state)
    original_observe = fleet._codex_worker_observe
    callback_checks = []

    def callback_check(name, record):
        callback_checks.append(record)
        if drift == "callback" and calls:
            raise fleet.FleetCliError("callback changed")
    monkeypatch.setattr(fleet, "_require_no_codex_current_waits", callback_check)

    def observe(*args, **kwargs):
        result = original_observe(*args, **kwargs)
        if drift == "journal":
            record = journal.load(OP)
            record["result"] = {"turn": {"id": TURN_ID, "status": "inProgress"}}
            journal.path(OP).write_text(json.dumps(record))
        elif drift == "row":
            data = fleet.load_registry();data["workers"]["cx-native"]["note"] = "changed"
            fleet.save_registry(data)
        elif drift == "claim_inode":
            replacement = claim.with_suffix(".new");replacement.write_bytes(claim.read_bytes())
            replacement.replace(claim)
        elif drift == "claim_bytes":
            claim.write_text("changed mail")
        elif drift == "generation":
            client.generation = "host-generation-2"
        return result
    monkeypatch.setattr(fleet, "_codex_worker_observe", observe)
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    after = fleet.load_registry()["workers"]["cx-native"]
    assert after["pending_operation"] == row["pending_operation"]
    assert after["codex_turn_id"] == TURN_ID
    assert claim.exists()
    assert journal.load(OP)["state"] == state


@pytest.mark.parametrize("change", ["multiple_claims", "kind", "last_operation", "host", "generation"])
def test_ambiguous_inputs_stay_fenced(native_home, monkeypatch, change):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    if change == "multiple_claims":
        (claim.parent / f"{THREAD_ID}.md.claimed.4243").write_text("older mail")
    elif change == "host":
        client.generation = "another-host"
    elif change == "generation":
        record=journal.load(OP);record["generation"]="another-host"
        journal.path(OP).write_text(json.dumps(record))
    else:
        data=fleet.load_registry()
        if change == "kind": data["workers"]["cx-native"]["pending_operation"]["kind"]="turn/steer"
        else: data["workers"]["cx-native"]["last_operation_id"]="another-op"
        fleet.save_registry(data)
    before=fleet.load_registry()
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()==before
    assert claim.exists()


@pytest.mark.parametrize("state", ["observed", "committed"])
def test_steer_result_must_keep_previous_turn(native_home, state):
    home, lane = native_home
    journal = prepare(home, lane, kind="turn/steer", state=state,
                      result={"turnId": NEXT_TURN_ID})
    before = journal.path(OP).read_bytes()
    with pytest.raises(HostRejected):
        journal.adopt_worker_turn(OP, turn_id=NEXT_TURN_ID, **identity(lane))
    assert journal.path(OP).read_bytes() == before


@pytest.mark.parametrize("provider", ["notLoaded", "systemError"])
def test_unobservable_provider_does_not_release(native_home, monkeypatch, provider):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    monkeypatch.setattr(fleet, "_codex_worker_observe", lambda *args, **kwargs: dict(
        provider_status=provider, turn_status="completed", active_flags=[]))
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.exists()


def test_other_unresolved_journal_predecessor_keeps_send_fenced(native_home, monkeypatch):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    journal.prepare({"operation_id": "another-uncertain-operation", "method": "rpc",
                     "payload": {"method": "turn/start", "params": {}}})
    journal.accept("another-uncertain-operation")
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.exists()
    assert calls == []


def test_public_turn_disagreement_keeps_exact_reservation(native_home, monkeypatch):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    def wrong_public(*args, **kwargs):
        raise fleet.FleetCliError("bound turn is absent, ambiguous, or not newest")
    monkeypatch.setattr(fleet, "_codex_worker_observe", wrong_public)
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.exists()


def test_symlink_claim_is_never_finalized(native_home, monkeypatch):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    target = home / "other-mail";target.write_text("untouched")
    claim.unlink();claim.symlink_to(target)
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.is_symlink() and target.read_text() == "untouched"


def test_retained_mail_must_match_original_payload_digest(native_home, monkeypatch):
    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    claim.write_text("different dispatch")
    original = journal.path(OP).read_bytes()
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.read_text() == "different dispatch"
    assert journal.path(OP).read_bytes() == original
    assert calls == []


def test_exact_observed_api_rejects_payload_drift(native_home):
    home, lane = native_home
    journal = prepare(home, lane)
    operation = {
        "operation_id": OP, "method": "rpc",
        "payload": {"method": "turn/start", "params": {"threadId": THREAD_ID}},
        "recovery": {"kind": "worker/turn/start", **identity(lane)},
    }
    before = journal.path(OP).read_bytes()
    with pytest.raises(HostRejected, match="durable intent"):
        journal.observed_operation(operation)
    assert journal.path(OP).read_bytes() == before


@pytest.mark.parametrize('shape',['valid','thread','cwd','turn','duplicate','changed','payload-drift'])
def test_repair_uses_real_paged_observer_and_refuses_public_drift(native_home,monkeypatch,shape):
    real_observe=fleet._codex_worker_observe
    home,lane,row,journal,claim,_client,_calls=frozen(native_home,monkeypatch,state='observed')
    before=journal.path('worker-send-proof').read_bytes()
    class Public:
        generation=GEN
        def __init__(self):self.calls=[];self.pages=0
        def call(self,op,timeout):
            method=op['payload']['method'];self.calls.append(method)
            if method=='thread/read':
                result={'thread':{'id':TURN_ID if shape=='thread' else THREAD_ID,
                    'cwd':str(home if shape=='cwd' else lane),
                    'status':{'type':'active','activeFlags':[]}}}
            elif method=='thread/turns/list':
                self.pages+=1
                turn=TURN_ID if shape=='turn' or (shape=='changed' and self.pages==2) else NEXT_TURN_ID
                turns=[{'id':turn,'status':'inProgress','itemsView':'notLoaded'}]
                if shape=='duplicate':turns.append(dict(turns[0]))
                result={'data':turns,'nextCursor':None}
                if shape=='payload-drift' and self.pages==2:
                    record=journal.load('worker-send-proof');record['payload_digest']='changed'
                    from fleet_codex import _atomic_json
                    _atomic_json(journal.path('worker-send-proof'),record)
            else:pytest.fail('unexpected provider call '+method)
            return SimpleNamespace(generation=GEN,result=result)
    client=Public()
    monkeypatch.setattr(fleet,'_codex_existing_client',lambda _home:client)
    monkeypatch.setattr(fleet,'_codex_worker_observe',real_observe)
    result=fleet._reconcile_frozen_codex_worker_operations()
    if shape=='valid':
        assert result==['cx-native']
        assert not claim.exists()
        after=fleet.load_registry()['workers']['cx-native']
        assert after['codex_turn_id']==NEXT_TURN_ID and 'pending_operation' not in after
        assert journal.load('worker-send-proof')['state']=='committed'
    else:
        assert result==[]
        assert fleet.load_registry()['workers']['cx-native']==row
        assert claim.read_text()=='retained dispatch'
        if shape!='payload-drift':assert journal.path('worker-send-proof').read_bytes()==before
    assert all(method in ['thread/read','thread/turns/list'] for method in client.calls)


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="FIFO requires POSIX")
def test_fifo_claim_refuses_promptly_without_a_writer(native_home, monkeypatch):
    """Open the real no-writer FIFO; a subprocess timeout catches blocking open."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    home, lane, row, journal, claim, client, calls = frozen(native_home, monkeypatch)
    claim.unlink()
    os.mkfifo(claim)
    inode = claim.lstat().st_ino
    # Isolate a potential blocking regression so the suite fails instead of hanging.
    # The child imports source only and never invokes any provider or live Fleet verb.
    probe = """
import sys
from pathlib import Path
import fleet
try:
    fleet._codex_claim_fingerprint(Path(sys.argv[1]))
except fleet.FleetCliError:
    pass
else:
    raise AssertionError('FIFO accepted as regular claimed mail')
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(claim)],
        env={**os.environ, "PYTHONPATH": str(Path(fleet.__file__).parent)},
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr
    # The complete repair path must also refuse this unchanged FIFO before RPC.
    assert fleet._reconcile_frozen_codex_worker_operations() == []
    assert fleet.load_registry()["workers"]["cx-native"] == row
    assert claim.lstat().st_ino == inode
    assert calls == []
