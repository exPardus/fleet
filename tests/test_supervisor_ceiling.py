"""three-tier-command.md §11.3 -- the supervisor's hard dispatch ceiling (B4),
**400k since the 2026-08-05 operator ruling** (200k before it).

At and above `SUPERVISOR_BAND_HARD_TOKENS` the dispatch verbs (`fleet spawn`/`fleet send`)
REFUSE to start new worker turns -- but for EXACTLY ONE caller: the supervisor
claim-holder (ND1). The interface tier is exempt STRUCTURALLY (ND4c), a caller
that holds no claim is never subject, the identity gate resolves through
`retired_sids` (ND4a) so the un-restamped fork-steer window does not fail open,
and an unresolvable identity fails TOWARD the band (ND4b). Occupancy is the
caller's OWN transcript (B2/B3).

ND4c's KEY CHANGED (SPEC.md:204, `tests/test_identity_registry.py`). It read
*"no `FLEET_WORKER` in its env"*; the machine-wide daemon donates that stamp to
sessions it never launched, so its presence and its absence say equally little
about the acting body. The structural question is now asked of the registry --
*"does any record claim my own sid, and am I the claim-holder"* -- and ND4b
narrows to match: an identity fleet cannot place at all abstains and exempts
(it is the interface, a human shell, or a body inside its own dispatch window,
and a newborn body cannot be at 200k tokens), while a REGISTERED body whose
holder-ness is merely indeterminate still fails toward the band.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def ceil_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs"):
        (tmp_path / sub).mkdir()
    # A clean env each test: no interface/worker stamp, no session leaking in.
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _write_incarnation(claim):
    fleet.write_incarnation(claim)


def _write_registry(workers):
    fleet.save_registry({"workers": workers})


def _held(session_id, **extra):
    """A held (non-released, non-legacy) claim owned by `session_id`."""
    c = {"incarnation_id": "inc-x", "session_id": session_id, "state": "active",
         "nonce_hash": "deadbeef", "nonce_seq": 3, "heartbeat_at": fleet.now_iso()}
    c.update(extra)
    return c


# --------------------------------------------------------------------------
# _caller_holds_supervisor_claim -- the shared identity concept (ND4a).
# --------------------------------------------------------------------------
class TestIdentity:
    def test_no_claim_is_not_holder(self, ceil_home):
        assert fleet._caller_holds_supervisor_claim("sid-a") is False

    def test_released_claim_is_not_holder(self, ceil_home):
        _write_incarnation({"incarnation_id": "inc-x", "state": "released",
                            "released_at": fleet.now_iso()})
        assert fleet._caller_holds_supervisor_claim("sid-a") is False

    def test_direct_holder_by_session_id(self, ceil_home):
        _write_incarnation(_held("sid-holder"))
        assert fleet._caller_holds_supervisor_claim("sid-holder") is True

    def test_claim_without_holder_sid_is_indeterminate(self, ceil_home):
        c = _held("sid-holder")
        del c["session_id"]
        _write_incarnation(c)
        assert fleet._caller_holds_supervisor_claim("sid-a") is None

    def test_unrestamped_fork_steer_window_resolves_through_retired_sids(self, ceil_home):
        # After a fork-steer: the body runs under NEW sid, the registry record was
        # eagerly restamped (session_id=new, retired_sids=[old]), but INCARNATION
        # still holds the OLD sid (pull-restamp lags, claim-nonce §5.10a). The
        # new caller must still resolve to the holder (ND4a) -- else the ceiling
        # fails open on the path every supervisor turn starts with.
        _write_incarnation(_held("sid-old"))
        _write_registry({"supervisor": {"session_id": "sid-new",
                                        "retired_sids": ["sid-old"]}})
        assert fleet._caller_holds_supervisor_claim("sid-new") is True

    def test_other_worker_is_not_the_holder(self, ceil_home):
        _write_incarnation(_held("sid-old"))
        _write_registry({"supervisor": {"session_id": "sid-new",
                                        "retired_sids": ["sid-old"]},
                         "w1": {"session_id": "sid-worker", "retired_sids": []}})
        assert fleet._caller_holds_supervisor_claim("sid-worker") is False

    def test_holder_sid_matching_no_record_is_indeterminate(self, ceil_home):
        # Claim points at a sid no live record carries (record archived/removed).
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"w1": {"session_id": "sid-worker", "retired_sids": []}})
        assert fleet._caller_holds_supervisor_claim("sid-someone") is None

    def test_empty_caller_is_indeterminate(self, ceil_home):
        _write_incarnation(_held("sid-holder"))
        assert fleet._caller_holds_supervisor_claim(None) is None


# --------------------------------------------------------------------------
# _ceiling_refuses_dispatch -- the refusal predicate itself.
# --------------------------------------------------------------------------
class TestCeiling:
    def _occ(self, monkeypatch, occupancy):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, sid: "/fake" if sid else None)
        monkeypatch.setattr(fleet, "_transcript_occupancy",
                            lambda p: occupancy)

    def _as_supervisor(self, monkeypatch, sid="sid-holder"):
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _write_incarnation(_held(sid))

    def test_interface_is_exempt_even_over_ceiling(self, ceil_home, monkeypatch):
        # No FLEET_WORKER => interface: NEVER refused, no matter the occupancy
        # (ND1/ND4c). Structural, ahead of any sid resolution.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _write_incarnation(_held("sid-holder"))
        _write_registry({"supervisor": {"session_id": "sid-holder", "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_the_interface_CAN_be_the_claim_holder_and_is_still_exempt(
            self, ceil_home, monkeypatch):
        """rb's reachability correction, pinned so the false impossibility
        cannot be re-recorded.

        An intervening revision rewrote the test above away from the shape
        "interface carrying the HOLDER's own sid", with the comment that it is
        *"not a shape the fleet can produce -- the interface is a human's
        session and the holder is a `--bg` supervisor body"*. That is false:
        `fleet sup-boot` is runnable from an interface session and stamps THAT
        session's sid into the claim. So the shape is reachable, it is exactly
        the case ND4(c) has to survive, and (c) still exempts it -- an
        unstamped session is outside fleet's launch surface whether or not it
        happens to hold the claim."""
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _write_incarnation(_held("sid-interface"))
        _write_registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._caller_holds_supervisor_claim("sid-interface") is True
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_interface_is_exempt_even_when_nothing_places_either_sid(
            self, ceil_home, monkeypatch):
        # The half the structural arm exists for: an EMPTY registry makes
        # `_caller_holds_supervisor_claim` INDETERMINATE, and (b)'s
        # fail-toward-band would otherwise catch the human channel -- a refusal
        # it could never escape, being outside fleet's launch surface (§3.1).
        # (c) still runs ahead of (b).
        #
        # FIX WAVE: this test carried a DONATED `FLEET_WORKER` stamp while
        # asserting the exemption, which is a shape ND4(c) does not promise.
        # Absence is what exempts, and donation can only ever ADD a stamp --
        # so a session carrying one is measured by (b) rather than excused, and
        # that is the safe direction. The genuine interface has no stamp.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_supervisor_holder_over_ceiling_is_refused(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 405000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None
        assert "spawn" in reason and "400,000" in reason and "11.3" in reason

    def test_supervisor_holder_at_exact_ceiling_is_refused(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, fleet.SUPERVISOR_BAND_HARD_TOKENS)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_soft_band_does_not_refuse_dispatch(self, ceil_home, monkeypatch):
        # soft <= occ < hard is a standing directive, NOT a fleet refusal
        # (§11.3). 375k sits inside the supervisor's 350-400k band, which is
        # where the old 175k sat inside 150-200k.
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 375000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_below_band_does_not_refuse(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 40000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_unreadable_occupancy_refuses_holder(self, ceil_home, monkeypatch):
        # §11.2: None fails TOWARD the band -- an unreadable transcript for the
        # claim-holder refuses, never "plenty of room".
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, None)
        assert fleet._ceiling_refuses_dispatch("send") is not None

    def test_non_holder_worker_is_not_refused(self, ceil_home, monkeypatch):
        # A worker turn (FLEET_WORKER set) that is not the claim-holder holds no
        # claim -> never subject, even if its own transcript is huge.
        monkeypatch.setenv("FLEET_WORKER", "w1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-worker")
        _write_incarnation(_held("sid-holder"))
        _write_registry({"w1": {"session_id": "sid-worker", "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_indeterminate_identity_fails_toward_band(self, ceil_home, monkeypatch):
        # ND4b, RESTORED VERBATIM by the fix wave. FLEET_WORKER present (not the
        # interface), a claim is held, identity unresolvable (holder sid in no
        # record). Treat the caller as the supervisor and apply the ceiling.
        #
        # An intervening revision NARROWED this to bodies the registry can
        # place, on the reasoning that a sid fleet cannot place is more likely a
        # newborn than an over-ceiling supervisor -- and inverted this very
        # assertion under the name `test_an_unplaceable_sid_is_exempt_rather_
        # than_failing_toward_band`. The narrowing contradicts ND4(b)'s text
        # (*"an unresolvable identity must never be the reason a ceiling stays
        # dormant"*) and made a 200k HARD ceiling bypassable by any condition
        # that makes `state/fleet.json` unreadable, measured end-to-end as
        # `fleet spawn` at 999,999 tokens returning rc=0. The newborn it was
        # protecting is protected by (c) instead when it has no stamp, and is
        # merely measured -- not refused, since a newborn cannot be at 400k --
        # when it has one.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._caller_holds_supervisor_claim("sid-mystery") is None
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_a_placed_caller_against_an_unreadable_holder_sid_also_refuses(
            self, ceil_home, monkeypatch):
        # The second reachable shape of an indeterminate verdict, kept from the
        # revision that narrowed the test above because it is real coverage the
        # original did not have: the registry PLACES the caller, and the claim
        # carries no readable holder sid at all.
        claim = _held("sid-holder")
        del claim["session_id"]
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(claim)
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []},
                         "sup|inc-x|successor": {"session_id": "sid-mystery",
                                                 "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._caller_holds_supervisor_claim("sid-mystery") is None
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_an_unplaceable_sid_with_no_stamp_is_exempt_STRUCTURALLY(
            self, ceil_home, monkeypatch):
        # What actually exempts the unplaceable body, named for the arm that
        # does it. Same shape as the ND4(b) test above with the one difference
        # that decides it: no `FLEET_WORKER`. (c) answers before (b) is reached.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_no_session_id_is_not_refused(self, ceil_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None


# --------------------------------------------------------------------------
# Wiring: the dispatch verbs actually consult the ceiling (B4 "fleet-enforced").
# --------------------------------------------------------------------------
class TestWiring:
    def test_cmd_spawn_refuses_over_ceiling(self, ceil_home, monkeypatch):
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 405000)
        args = SimpleNamespace(name="w1", dir=str(ceil_home), task="do it",
                               nonce=None, max_budget_usd=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_spawn(args)
        assert "11.3" in str(ei.value)

    def test_cmd_send_refuses_over_ceiling(self, ceil_home, monkeypatch):
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 405000)
        args = SimpleNamespace(name="w1", message="hi", nonce=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_send(args)
        assert "11.3" in str(ei.value)

    def test_cmd_spawn_below_ceiling_passes_the_gate(self, ceil_home, monkeypatch):
        # Below the ceiling the ceiling raises nothing; the verb proceeds to its
        # NEXT guard (_require_instance_settings), proving the ceiling did not
        # itself block. We assert the failure is NOT the ceiling.
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 40000)
        args = SimpleNamespace(name="w1", dir=str(ceil_home), task="do it",
                               nonce=None, max_budget_usd=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_spawn(args)
        assert "11.3" not in str(ei.value)
