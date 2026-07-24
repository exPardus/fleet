"""Three-tier switch-over seams (docs/AUTONOMOUS-2026-07-24.md G-B/G-C).

Two independent fixes that together let the claimless INTERFACE tier steer the
supervisor it launched (`fleet send supervisor`):

  Seam #2 -- handoff successors get a registry record `sup|<inc>|successor`, so
             the logical-name resolver (`_resolve_worker_target`) can find the
             holder body. Live-reproduced: a valid nonce cleared the §7 gate and
             `send supervisor` STILL failed `holder sid ... matches no registry
             record`. NOT operator-gated (a straight resolver-input bug).

  Seam #1 -- the §7 send-gate (`_supervisor_gate`) is disarmed for a `send`
             whose RESOLVED target record IS the current claim-holder's own
             body. Council 4-0 candidate (a). Record-IDENTITY, send-ONLY,
             resolve-then-gate (atomic). The five ratification-blocking
             fault-injections (G-C condition 6) live here.

Every arming/husk/worker/transition case is written so a WEAKENING of the
predicate (name/shape/prefix match, or dropping the send-only or atomicity
guard) turns it red.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
HOLDER_SID = "99998888-7777-6666-5555-444433332222"
OTHER_SID = "11112222-3333-4444-5555-666677778888"
IFACE_SID = "abcd0000-1111-2222-3333-444455556666"
SUCC_NAME = "sup|inc-succ|successor"
BOOT_HUSK = "sup|inc-dead|boot"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def seam_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                             encoding="utf-8")
    # A caller that is NOT a fleet-launched worker (the interface tier): a sid,
    # but no FLEET_WORKER, so the §11.3 ceiling's structural interface exemption
    # applies and the send never trips the ceiling.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", IFACE_SID)
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    return tmp_path


def _fresh_claim(sid=HOLDER_SID, inc="inc-held", beat_age_seconds=5, **extra):
    """An ARMED claim: fresh heartbeat + a generation, held by `sid`."""
    beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=beat_age_seconds))
    value = fleet.mint_nonce()
    claim = {"incarnation_id": inc, "session_id": sid,
             "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
             "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
             "lineage_id": "lin-L"}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return value


def _seed_record(name, sid, status="working", **over):
    rec = fleet.new_worker_record(sid, str(fleet.FLEET_HOME), "campaign", "bypass",
                                  dispatch_kind="bg")
    rec["status"] = status
    if isinstance(sid, str) and sid:
        rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
    rec.update(over)
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _events():
    path = fleet.FLEET_HOME / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


# ===========================================================================
# Seam #2 -- handoff successors get a registry record
# ===========================================================================
def _fake_which(_):
    return "C:/fake/claude.cmd"


def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001"):
    """Stateful run double: the successor only appears in the roster after the
    `--bg` dispatch call is observed (mirrors TestHandoff)."""
    assert successor_sid.startswith(short_id)
    state = {"dispatched": False}
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if "--bg" in argv:
            state["dispatched"] = True
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded · {short_id} · sup\n", stderr="")
        entries = [{"sessionId": "sid-old", "status": "busy"}]
        if state["dispatched"]:
            entries.append({"sessionId": successor_sid, "status": "busy"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    run.calls = calls
    return run


def _hold_predecessor(sid="sid-old", inc="inc-old"):
    fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                             "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW),
                             "claimed_via": "fresh"})


def _begin(run, sid="sid-old"):
    return fleet.cmd_sup_handoff_begin(SimpleNamespace(sid=sid, model=None,
                                                       permission_mode=None),
                                       which=_fake_which, run=run, sleep=lambda s: None)


class TestSeam2SuccessorRecord:
    def test_begin_registers_a_supervisor_shaped_successor_record(self, seam_home):
        # RED pre-fix: cmd_sup_handoff_begin never called new_worker_record, so
        # the successor had no record and the resolver dead-ended.
        _hold_predecessor()
        assert _begin(_dispatch_then_roster()) == 0
        workers = fleet.load_registry()["workers"]
        successors = [n for n in workers if n.endswith("|successor")]
        assert len(successors) == 1, workers
        name = successors[0]
        assert fleet._is_supervisor_shaped(name)
        assert workers[name]["dispatch_kind"] == "bg"
        # The daemon mints the sid; the record starts sid-less and is stamped by
        # the sid-stamping seam (handoff-complete's --expect-sid), like a gen-0
        # sup-spawn record between create and _commit_native_stamp.
        assert workers[name]["session_id"] is None

    def test_complete_stamps_the_successor_sid_and_resolver_finds_it(self, seam_home):
        # The pair that closes seam #2: begin left a sid-less record; complete
        # transfers the claim to the HANDSHAKE sid AND stamps that same sid onto
        # the successor record, so `_resolve_worker_target("supervisor")` -- the
        # claim -> holder-sid -> record walk -- now lands on the successor body.
        token = "tok-good"
        value = fleet.mint_nonce()
        beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=5))
        fleet.write_incarnation({"incarnation_id": "inc-old", "session_id": "sid-old",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_hash": fleet.nonce_digest(value),
                                 "nonce_seq": 2, "lineage_id": "lin-L",
                                 "handoff_token_hash": fleet.nonce_digest(token)})
        _seed_record(SUCC_NAME, None, status="working")   # begin's sid-less record
        succ_nonce = fleet.mint_nonce()
        fleet.write_handshake("inc-succ", HOLDER_SID,
                              handoff_token_hash=fleet.nonce_digest(token),
                              nonce_hash=fleet.nonce_digest(succ_nonce))
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ",
                               expect_sid=HOLDER_SID, nonce=value)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        rec = fleet.load_registry()["workers"][SUCC_NAME]
        assert rec["session_id"] == HOLDER_SID
        # The whole point: the logical name now resolves to the successor body.
        assert fleet._resolve_worker_target("supervisor") == SUCC_NAME

    def test_complete_without_a_successor_record_is_a_noop_not_a_crash(self, seam_home):
        # An older handoff (or a cleaned record) leaves no successor record; the
        # stamp is best-effort and complete must still transfer the claim.
        token = "tok-good"
        value = fleet.mint_nonce()
        beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=5))
        fleet.write_incarnation({"incarnation_id": "inc-old", "session_id": "sid-old",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_hash": fleet.nonce_digest(value),
                                 "nonce_seq": 2, "lineage_id": "lin-L",
                                 "handoff_token_hash": fleet.nonce_digest(token)})
        succ_nonce = fleet.mint_nonce()
        fleet.write_handshake("inc-succ", HOLDER_SID,
                              handoff_token_hash=fleet.nonce_digest(token),
                              nonce_hash=fleet.nonce_digest(succ_nonce))
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ",
                               expect_sid=HOLDER_SID, nonce=value)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        assert fleet.read_incarnation()["incarnation_id"] == "inc-succ"

    def test_stamped_successor_record_holds_the_claim_and_is_archive_exempt(self, seam_home):
        # The wanted §7.2 side effect: once stamped, the successor record IS the
        # claim holder, so `_record_is_supervisor_claim_holder` is True and the
        # archive gate exempts it -- parity with a gen-0 body.
        _fresh_claim(sid=HOLDER_SID)
        rec = _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        assert fleet._record_is_supervisor_claim_holder(rec) is True


# ===========================================================================
# Seam #1 -- the send-gate carve-out (unit level: `_supervisor_gate`)
# ===========================================================================
class TestSeam1GateCarveOut:
    def test_positive_send_to_live_holder_record_disarms(self, seam_home):
        # FI-positive (gate level): the interface holds no nonce, but a `send`
        # whose resolved target IS the holder body is ungated. Revert the
        # carve-out and this goes red (the armed gate raises).
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        fleet._supervisor_gate("send", nonce=None, send_target=SUCC_NAME)  # no raise

    def test_FI_husk_leak_supervisor_shaped_nonholder_stays_gated(self, seam_home):
        # FI-husk-leak (LOAD-BEARING): a supervisor-SHAPED record that does NOT
        # hold the claim (a dead gen-0 husk / post-transfer predecessor) stays
        # GATED. Rewriting the predicate to `_is_supervisor_shaped(send_target)`
        # or a `sup|` prefix would disarm here -> this test goes red.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(BOOT_HUSK, OTHER_SID, status="dead")   # shape, but not holder
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None, send_target=BOOT_HUSK)

    def test_FI_worker_real_name_stays_gated(self, seam_home):
        # FI-worker: a plain worker addressed by real name, from a sid-bearing
        # claimless caller under a fresh claim, stays GATED.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record("w1", OTHER_SID, status="working")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None, send_target="w1")

    def test_FI_transition_claim_moves_between_resolve_and_gate(self, seam_home):
        # FI-transition / no-TOCTOU: the caller resolved target R while R held
        # the claim, but by gate-eval time the claim moved to a different body.
        # The gate keys on ITS OWN claim read, so R no longer holds it -> the
        # full §7 gate re-arms and REFUSES.
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        _fresh_claim(sid=HOLDER_SID)                 # at resolve time R holds it
        # ... claim moves to a different live body between resolve and gate:
        _fresh_claim(sid=OTHER_SID, inc="inc-moved")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None, send_target=SUCC_NAME)

    def test_FI_record_identity_predicate_is_not_name_or_prefix(self, seam_home):
        # FI-record-identity: the disarm is keyed on record-IDENTITY
        # (`_record_is_supervisor_claim_holder`), never on the name. A record
        # with an ORDINARY (non-supervisor-shaped) name that nonetheless carries
        # the holder sid DISARMS the gate -- a predicate generalized to a
        # name/shape/prefix match would keep it armed and this goes red.
        assert not fleet._is_supervisor_shaped("ordinary-holder")
        _fresh_claim(sid=HOLDER_SID)
        _seed_record("ordinary-holder", HOLDER_SID, status="working")
        fleet._supervisor_gate("send", nonce=None, send_target="ordinary-holder")  # no raise

    def test_carve_out_is_send_only(self, seam_home):
        # send-ONLY: no other mutating verb receives a target-aware carve-out.
        # Even against the live-holder record, `kill` stays fully gated.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("kill", nonce=None, send_target=SUCC_NAME)

    def test_send_without_a_resolved_target_stays_gated(self, seam_home):
        # The carve-out requires a RESOLVED target (resolve-then-gate). A bare
        # armed `send` with no send_target keeps the unchanged §7 arming.
        _fresh_claim(sid=HOLDER_SID)
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None)

    def test_carve_out_does_not_write_the_claim(self, seam_home):
        # §5.3: the disarm validates without minting -- passing the carve-out
        # must not rotate the generation or restamp the claim.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        before = fleet.read_incarnation()
        fleet._supervisor_gate("send", nonce=None, send_target=SUCC_NAME)
        assert fleet.read_incarnation() == before


# ===========================================================================
# Seam #1 -- end-to-end through `cmd_send`
# ===========================================================================
def _roster_busy(sid):
    def fetch(**_):
        return True, [{"sessionId": sid, "name": SUCC_NAME, "status": "busy",
                       "pid": 4321, "state": "working"}]
    return fetch


class TestSeam1CmdSendEndToEnd:
    def test_FI_positive_interface_send_to_live_holder_delivers_with_caller_sid(
            self, seam_home, monkeypatch, capsys):
        # FI-positive (end-to-end): the interface (sid, no nonce) sends to the
        # logical `supervisor`; resolve-then-gate disarms, the mail lands, and
        # the emitted mail_sent event carries caller_sid so §5.3's divergence
        # detector (which DROPS events without it) can observe the steer.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_busy(HOLDER_SID))
        rc = fleet.cmd_send(SimpleNamespace(name="supervisor", message="brief you",
                                            nonce=None),
                            run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                            which=_fake_which, sleep=lambda s: None)
        assert rc == 0
        sent = [e for e in _events() if e["kind"] == "mail_sent"]
        assert sent, _events()
        assert sent[-1]["caller_sid"] == IFACE_SID
        assert sent[-1]["name"] == SUCC_NAME

    def test_FI_positive_is_observed_by_interface_divergence(self, seam_home, monkeypatch):
        # §5.3 actually consumes the provenance: two distinct interface caller
        # sids steering the holder within the window raise the divergence
        # warning -- proving the carve-out's caller_sid reaches the detector.
        _fresh_claim(sid=HOLDER_SID)
        _seed_record(SUCC_NAME, HOLDER_SID, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_busy(HOLDER_SID))
        for caller in (IFACE_SID, OTHER_SID):
            monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", caller)
            fleet.cmd_send(SimpleNamespace(name="supervisor", message="hi", nonce=None),
                           run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
                           which=_fake_which, sleep=lambda s: None)
        div = fleet._interface_divergence()
        assert div is not None and div["count"] == 2

    def test_send_to_ordinary_worker_stays_gated_end_to_end(self, seam_home, monkeypatch):
        # FI-worker end-to-end: the interface cannot steer an ordinary worker
        # while a supervisor claim is fresh -- the full gate refuses (exit 4).
        _fresh_claim(sid=HOLDER_SID)
        _seed_record("w1", OTHER_SID, status="working")
        rc = fleet.main(["send", "w1", "hi"])
        assert rc == fleet.SUPERVISOR_CONTINUITY_RC

    def test_send_supervisor_still_loud_when_no_claim(self, seam_home):
        # Condition 5: the resolver's loud failures survive resolve-then-gate.
        # No claim -> nothing answers to 'supervisor'; a named refusal, never a
        # silent pass into the gate.
        with pytest.raises(fleet.FleetCliError, match="no supervisor claim"):
            fleet.cmd_send(SimpleNamespace(name="supervisor", message="hi", nonce=None),
                           run=lambda *a, **k: None, which=_fake_which, sleep=lambda s: None)
