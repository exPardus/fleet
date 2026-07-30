"""three-tier-command.md §11.3 -- the 200k hard ceiling (B4).

At and above `BAND_HARD_TOKENS` the dispatch verbs (`fleet spawn`/`fleet send`)
REFUSE to start new worker turns -- but for EXACTLY ONE caller: the supervisor
claim-holder (ND1). The interface tier is exempt STRUCTURALLY (ND4c), a caller
that holds no claim is never subject, the identity gate resolves through
`retired_sids` (ND4a) so the un-restamped fork-steer window does not fail open,
and an unresolvable identity fails TOWARD the band (ND4b). Occupancy is the
caller's OWN transcript (B2/B3).

ND4c IS NARROWED, AND THIS PARAGRAPH HAS BEEN WRONG BEFORE -- read the tests,
not it. An earlier revision re-keyed (c) onto the registry (*"does any record
claim my own sid"*) and rewrote this header to match; the fix wave reverted the
code and left the header describing a shape that `TestCeiling::
test_indeterminate_identity_fails_toward_band` in this very file contradicts.
Restated 2026-07-31 against shipped code: (c) still keys on `FLEET_WORKER`'s
ABSENCE and still runs ahead of ND4b, but it is now GATED -- operator ruling A,
2026-07-31 -- on a claim-file question asked first: `caller_sid ==
INCARNATION.session_id` of a HELD claim. The holder is never exempt, whatever
its stamp and whatever the registry says. ND4b is untouched: a stamped,
unplaceable, non-holder body still fails toward the band. See
`TestTheClaimHolderIsNeverExempt` below.
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

    def test_the_interface_CAN_be_the_claim_holder_and_is_NO_LONGER_exempt(
            self, ceil_home, monkeypatch):
        """THE PIN THE 2026-07-31 RULING FLIPPED, and the flip is the ruling.

        rb's reachability correction is kept, because it is still what makes
        this shape worth a test. An intervening revision had rewritten the test
        above away from "interface carrying the HOLDER's own sid" with the
        comment that it is *"not a shape the fleet can produce -- the interface
        is a human's session and the holder is a `--bg` supervisor body"*. That
        is false: `fleet sup-boot` is runnable from an interface session and
        stamps THAT session's sid into the claim, so the shape is reachable.

        WHAT CHANGED IS THE VERDICT, not the reachability. This test asserted
        *"(c) still exempts it -- an unstamped session is outside fleet's launch
        surface whether or not it happens to hold the claim"*. Operator ruling
        A (Altai, in-session 2026-07-31) says the opposite and named this flip
        as an accepted cost before it was made: an interface session that ever
        took the claim becomes ceiling-subject, and its escape is
        `sup-handoff-begin`, which is exempt. Doctrine forbids the interface
        taking the claim at all, so the body that lands here has already
        departed from it."""
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _write_incarnation(_held("sid-interface"))
        _write_registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._caller_holds_supervisor_claim("sid-interface") is True
        assert fleet._ceiling_refuses_dispatch("send") is not None

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
        self._occ(monkeypatch, 205000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None
        assert "spawn" in reason and "200,000" in reason and "11.3" in reason

    def test_supervisor_holder_at_exact_ceiling_is_refused(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, fleet.BAND_HARD_TOKENS)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_soft_band_does_not_refuse_dispatch(self, ceil_home, monkeypatch):
        # 150k <= occ < 200k is a standing directive, NOT a fleet refusal (§11.3).
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 175000)
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
        self._occ(monkeypatch, 400000)
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
        # merely measured -- not refused, since a newborn cannot be at 200k --
        # when it has one.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []}})
        self._occ(monkeypatch, 300000)
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
        self._occ(monkeypatch, 300000)
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
        self._occ(monkeypatch, 300000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_no_session_id_is_not_refused(self, ceil_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        self._occ(monkeypatch, 400000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None


# --------------------------------------------------------------------------
# ND4(c) AS NARROWED -- operator ruling A, 2026-07-31.
# --------------------------------------------------------------------------
class TestTheClaimHolderIsNeverExempt:
    """*"Whoever holds the supervisor claim is subject to the 200k dispatch
    ceiling regardless of stamp or registry state; the predicate reads the claim
    file, not the environment, so it needs no sound env channel and never enters
    ND4(b)'s bucket. ND4(b) stands untouched."* -- Altai, in-session
    2026-07-31, `docs/OPERATOR-GATES.md`; the pricing is claim-nonce §18.4
    candidate A and the amended bullet is three-tier §11.3 ND4(c).

    WHAT THIS CLOSES, and it was measured live rather than argued: a
    claim-holding supervisor whose daemon was cold-started by an unstamped
    launcher reads no `FLEET_WORKER` and was therefore exempt from a HARD
    ceiling. Four of four live bodies in one wave (2026-07-30), two of them
    supervisors -- the common case, not an edge.

    THE SHAPE OF THE NARROWING. (c) still exempts, and it still exempts
    structurally without resolving a sid against the registry -- but it may no
    longer exempt the claim-file holder. The holdership predicate is bare
    equality against `supervisor/INCARNATION`'s own `session_id`, which is
    total (never None) and reads neither the environment nor `state/fleet.json`,
    so it cannot land in ND4(b)'s indeterminate bucket and cannot quarantine
    anything.

    WHAT IT COSTS, ratified with the ruling: (c) loses its *"runs first, with no
    sid at all"* ordering property, because the caller's own sid is now needed
    to answer the question at all."""

    def _occ(self, monkeypatch, occupancy):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, sid: "/fake" if sid else None)
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: occupancy)

    def test_the_holder_with_NO_stamp_over_the_ceiling_is_REFUSED(
            self, ceil_home, monkeypatch):
        # THE MEASURED LIVE HOLE, closed. Before the ruling this returned None.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        _write_registry({"sup|inc-x|boot": {"session_id": "sid-holder",
                                            "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None
        assert "200,000" in reason and "11.3" in reason

    @pytest.mark.parametrize("blank", ["", " ", "\t", "\n", "  \t\n "])
    def test_a_BLANK_stamp_no_longer_buys_the_holder_an_exemption(
            self, ceil_home, monkeypatch, blank):
        # The stamp's equivalence class (absent == "" == whitespace) is
        # unchanged; what changed is that the holder is outside it.
        monkeypatch.setenv("FLEET_WORKER", blank)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        _write_registry({"sup|inc-x|boot": {"session_id": "sid-holder",
                                            "retired_sids": []}})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None, (
            f"a blank stamp {blank!r} exempted the claim-file holder")

    def test_the_holder_is_refused_on_a_CORRUPT_registry_TOO(
            self, ceil_home, monkeypatch):
        # *"regardless of stamp OR REGISTRY STATE"*. The claim file alone
        # decides holdership, so an unreadable `state/fleet.json` cannot buy the
        # holder an exemption -- and the read must still not quarantine one
        # (a ceiling check is a read).
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None
        assert fleet.registry_path().read_text(encoding="utf-8") == "{ not json"
        assert not list(fleet.registry_path().parent.glob("fleet.json.corrupt*"))

    def test_a_RELEASED_claim_has_no_holder_to_catch(self, ceil_home, monkeypatch):
        # A released claim is terminal and owns nobody, so the body that
        # released it is an ordinary unstamped session again -- exempt by (c)
        # exactly as before. The narrowing is to the HELD claim's holder.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation({"incarnation_id": "inc-x", "session_id": "sid-holder",
                            "state": "released", "released_at": fleet.now_iso()})
        _write_registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_ND1_SURVIVES_a_non_holder_with_no_stamp_is_still_exempt(
            self, ceil_home, monkeypatch):
        # The half (c) exists for, and the half candidate C would have cost:
        # an unstamped session that does NOT hold the claim is exempt even when
        # nothing places either sid, so ND4(b)'s fail-toward-band still cannot
        # reach the human channel with a refusal it could never escape (§3.1).
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_ND4b_IS_UNTOUCHED_the_indeterminate_stamped_body_still_refuses(
            self, ceil_home, monkeypatch):
        # The fence on this lane, asserted rather than promised. The caller is
        # NOT the claim-file holder, so the new predicate declines and the
        # verdict is still ND4(b)'s: stamped, unplaceable, fail toward the band.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []}})
        self._occ(monkeypatch, 300000)
        assert fleet._caller_holds_supervisor_claim("sid-mystery") is None
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_the_refusal_does_not_promise_an_escape_the_holder_does_not_have(
            self, ceil_home, monkeypatch):
        # R2, the named-remedy-that-always-fails class, third instance averted.
        # The shipped wording told a refused caller that a session with no
        # `FLEET_WORKER` stamp is exempt structurally -- which, for the one
        # caller that can read this string, is now false. It must name the
        # escape the holder actually has (`sup-handoff-begin`, exempt).
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        _write_registry({})
        self._occ(monkeypatch, 500000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None
        assert "no `FLEET_WORKER` stamp is exempt structurally" not in reason
        assert "sup-handoff-begin" in reason


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
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 205000)
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
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 205000)
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
