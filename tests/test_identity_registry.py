"""The registry judges fleet identity; the environment only witnesses.

SPEC.md:196 -- *"A future guard enforcing 'a worker turn must never hold the
supervisor claim' must key on the registry or the claim itself, NEVER on
`FLEET_WORKER`, or it will refuse the one session whose whole purpose is to
receive the claim."*

THE DEFECT THIS FILE EXISTS FOR. `_worker_env` stamps `FLEET_WORKER=<name>`
into a dispatch's child environment, but that env reaches only a thin launcher:
the machine-wide `claude` daemon hosts the real session and donates its OWN
environment to it, frozen from whichever `--bg` dispatch started it. So every
daemon-hosted session inherits the `FLEET_WORKER` of a long-dead dispatch.

Measured on a live supervisor body, 2026-07-26 (the receipt encoded by
`TestTheReceipt`)::

    my env CLAUDE_CODE_SESSION_ID : 108300de-8d43-411e-8177-94843bee05ab
    my env FLEET_WORKER           : sup|inc-20260726T140146Z-5a0e|boot
    records whose sid union contains MY env sid: ['sup|inc-20260726T164152Z-8180|boot']
    my actual dispatched worker name          : sup|inc-20260726T164152Z-8180|boot
    env FLEET_WORKER names a DIFFERENT record :  True (status: idle)

At one instant, on one body: resolving identity from the REGISTRY by the acting
sid returned exactly one record and it was the right one; resolving it from
`FLEET_WORKER` returned a different, idle worker. The registry was right and the
environment was wrong, simultaneously.

THE HARD INVARIANT (§5 of the build brief), pinned by `TestInferenceNeverRefuses`:

    An identity inference derived from the environment may never be the sole
    basis of a refusal. The nonce and the claim refuse; inference may only
    inform and announce.

Both `FLEET_WORKER` and `CLAUDE_CODE_SESSION_ID` are read from the same medium
-- the donated daemon environment. Re-keying onto "registry lookup by the acting
sid" improves blame-assignment but does not escape that medium: whether the sid
itself can be donated is an OPEN question (`_worker_env` pops it before
`Popen(env=...)`, so the live measurement is equally consistent with "the vendor
stamps a fresh sid" and "the vendor passes the env through and there was nothing
to pass"). The invariant is what makes the design sound under both: a
misidentification can cost a wrong measurement or a spurious announcement, never
a wrongly-refused claim verb.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


# --------------------------------------------------------------------------
# fixtures / builders
# --------------------------------------------------------------------------

@pytest.fixture
def id_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with a supervisor dir, and a guaranteed-clean env.

    The autouse `_no_inherited_claude_session` fixture already strips both
    variables; this restates the guarantee locally because every test here is
    ABOUT those two variables and a reader must not have to go looking."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "supervisor"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _registry(workers):
    fleet.save_registry({"workers": workers})


def _rec(session_id=None, retired=(), status="idle", archived_at=None):
    return {"session_id": session_id, "retired_sids": list(retired),
            "status": status, "archived_at": archived_at}


def _held(session_id, nonce_hash="deadbeef", **extra):
    c = {"incarnation_id": "inc-x", "session_id": session_id, "state": "active",
         "nonce_hash": nonce_hash, "nonce_seq": 3, "lineage_id": "lin-x",
         "heartbeat_at": fleet.now_iso()}
    c.update(extra)
    return c


def _hold_with_live_nonce(sid):
    """Write a held claim and return the plaintext of its LIVE generation."""
    value = fleet.mint_nonce()
    fleet.write_incarnation(_held(sid, nonce_hash=fleet.nonce_digest(value)))
    return value


def _ckpt(sid="sid-me", nonce=None, body="did a thing", kind="CHECKPOINT"):
    return SimpleNamespace(body=body, kind=kind, sid=sid, nonce=nonce)


# --------------------------------------------------------------------------
# 1. The helper -- the single place that answers "which fleet worker am I?"
# --------------------------------------------------------------------------

class TestActingWorkerIdentity:
    """`_acting_worker_identity` resolves the ACTING session's own
    `CLAUDE_CODE_SESSION_ID` against every record's sid UNION (`_record_sids`,
    so fork-steered and respawned bodies still resolve). Three verdicts:
    resolved / unresolved / ambiguous."""

    def test_a_human_shell_with_no_sid_is_unresolved(self, id_home):
        _registry({"w1": _rec("sid-w1")})
        ident = fleet._acting_worker_identity()
        assert ident["verdict"] == fleet.IDENTITY_UNRESOLVED
        assert ident["name"] is None
        assert fleet._acting_worker_name() is None
        assert fleet._acting_worker_record() is None

    def test_no_record_claiming_my_sid_is_unresolved(self, id_home, monkeypatch):
        # The interface session: a real Claude session, but not a fleet-launched
        # body. UNRESOLVED is not an error -- it is the honest answer.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        _registry({"w1": _rec("sid-w1")})
        assert fleet._acting_worker_identity()["verdict"] == fleet.IDENTITY_UNRESOLVED
        assert fleet._acting_worker_name() is None

    def test_resolves_by_the_records_current_session_id(self, id_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1"), "w2": _rec("sid-w2")})
        ident = fleet._acting_worker_identity()
        assert ident["verdict"] == fleet.IDENTITY_RESOLVED
        assert ident["name"] == "w1"
        assert fleet._acting_worker_name() == "w1"
        assert fleet._acting_worker_record()["session_id"] == "sid-w1"

    def test_resolves_through_retired_sids_after_a_fork_steer(self, id_home, monkeypatch):
        # A sid ROTATES on fork-steer and respawn. `_record_sids` is the union
        # of `session_id` and `retired_sids`; keying on the bare `session_id`
        # would fail to resolve every body that has ever been steered.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-old")
        _registry({"w1": _rec("sid-new", retired=["sid-old"])})
        assert fleet._acting_worker_name() == "w1"

    def test_the_union_is_the_key_not_the_bare_session_id(self, id_home, monkeypatch):
        # The guard that dies if someone re-keys the helper onto `session_id`.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-retired-only")
        _registry({"w1": _rec("sid-current", retired=["sid-retired-only"])})
        assert fleet._acting_worker_name() == "w1"

    def test_the_dispatch_window_newborn_is_unresolved(self, id_home, monkeypatch):
        # THE NAMED TRAP. `cmd_sup_spawn` (and the worker spawn path) create the
        # record BEFORE the session exists -- `new_worker_record(session_id=None,
        # ...)` -- and fill the sid in only once the dispatch returns it. So a
        # legitimately-new body has NO sid-matching record during its own
        # dispatch window. Every worker's first moments, and the supervisor's.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-newborn")
        _registry({"w1": _rec(None), "w2": _rec("sid-w2")})
        assert fleet._acting_worker_identity()["verdict"] == fleet.IDENTITY_UNRESOLVED

    def test_a_null_session_id_never_matches_a_null_sid(self, id_home, monkeypatch):
        # The inverse of the trap: a pre-claim record carries session_id=None,
        # and `None in {None}` must never be how a body resolves. `_record_sids`
        # already drops non-str members; this pins that it stays that way.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _registry({"w1": _rec(None)})
        assert fleet._acting_worker_name() is None

    def test_a_corrupt_registry_is_unresolved_not_a_crash(self, id_home, monkeypatch):
        # The helper runs on the dispatch hot path and inside a doctor row.
        # A corrupt registry must degrade to "I do not know", never take a
        # verb or a health check down with it.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        fleet.registry_path().write_text("{not json", encoding="utf-8")
        assert fleet._acting_worker_identity()["verdict"] == fleet.IDENTITY_UNRESOLVED


class TestAmbiguityIsItsOwnVerdict:
    """Two or more LIVE records carrying one sid is itself a leak signature.
    Treated as UNRESOLVED for control flow, announced DISTINCTLY by doctor,
    and never resolved by silently taking the first match."""

    def test_two_live_records_claiming_my_sid_is_ambiguous(self, id_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"w1": _rec("sid-dup"), "w2": _rec("sid-dup")})
        ident = fleet._acting_worker_identity()
        assert ident["verdict"] == fleet.IDENTITY_AMBIGUOUS
        assert ident["name"] is None
        assert sorted(ident["matches"]) == ["w1", "w2"]

    def test_ambiguity_never_silently_takes_the_first_match(self, id_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"aaa": _rec("sid-dup"), "zzz": _rec("sid-dup")})
        assert fleet._acting_worker_name() is None
        assert fleet._acting_worker_record() is None

    def test_a_dead_husk_sharing_the_sid_does_not_make_it_ambiguous(
            self, id_home, monkeypatch):
        # A respawn/fork leaves husks behind. Only LIVE records contend for an
        # identity; one live match beside any number of dead ones resolves.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"live": _rec("sid-dup", status="working"),
                   "husk": _rec("sid-dup", status="dead")})
        assert fleet._acting_worker_name() == "live"

    def test_an_archived_record_sharing_the_sid_does_not_make_it_ambiguous(
            self, id_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"live": _rec("sid-dup", status="idle"),
                   "old": _rec("sid-dup", status="idle",
                               archived_at="2026-07-01T00:00:00Z")})
        assert fleet._acting_worker_name() == "live"

    def test_two_dead_records_are_still_ambiguous_not_arbitrary(
            self, id_home, monkeypatch):
        # No live candidate to prefer: refusing to guess is the whole rule.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"h1": _rec("sid-dup", status="dead"),
                   "h2": _rec("sid-dup", status="dead")})
        assert fleet._acting_worker_identity()["verdict"] == fleet.IDENTITY_AMBIGUOUS
        assert fleet._acting_worker_name() is None


# --------------------------------------------------------------------------
# 2. THE RECEIPT, encoded. The regression test that fails if either read site
#    is ever re-keyed back onto `FLEET_WORKER`.
# --------------------------------------------------------------------------

class TestTheReceipt:
    """Construct the measured 2026-07-26 disagreement -- env `FLEET_WORKER`
    names record X while the acting sid belongs to record Y -- and assert
    every read site answers **Y**."""

    ENV_NAME = "sup|inc-20260726T140146Z-5a0e|boot"     # X: the donated witness
    MY_NAME = "sup|inc-20260726T164152Z-8180|boot"      # Y: my real record
    MY_SID = "108300de-8d43-411e-8177-94843bee05ab"

    def _leak(self, monkeypatch, x_status="idle"):
        monkeypatch.setenv("FLEET_WORKER", self.ENV_NAME)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.MY_SID)
        _registry({self.ENV_NAME: _rec("sid-long-dead", status=x_status),
                   self.MY_NAME: _rec(self.MY_SID, status="working")})

    def test_the_helper_answers_Y_not_the_env_X(self, id_home, monkeypatch):
        self._leak(monkeypatch)
        assert fleet._acting_worker_name() == self.MY_NAME
        assert fleet._acting_worker_name() != self.ENV_NAME

    def test_site_A_the_ceiling_judges_by_the_registry_not_the_env(
            self, id_home, monkeypatch):
        # My sid IS the claim holder's, so the ceiling applies to me -- and it
        # must reach that verdict from the registry, not from a witness that
        # names an idle stranger.
        self._leak(monkeypatch)
        fleet.write_incarnation(_held(self.MY_SID))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 300000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None and "200,000" in reason

    def test_site_B_does_not_refuse_the_body_the_env_slanders(
            self, id_home, monkeypatch):
        # The witness names a worker-shaped stranger. Under the shipped code
        # that env value alone decided the refusal. It must decide nothing.
        monkeypatch.setenv("FLEET_WORKER", "some-ordinary-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.MY_SID)
        _registry({"some-ordinary-worker": _rec("sid-long-dead"),
                   self.MY_NAME: _rec(self.MY_SID, status="working")})
        live = _hold_with_live_nonce(self.MY_SID)
        assert fleet.cmd_sup_checkpoint(_ckpt(sid=self.MY_SID, nonce=live)) == 0


# --------------------------------------------------------------------------
# 3. Site A -- the 200k ceiling's structural exemption, re-keyed.
# --------------------------------------------------------------------------

class TestSiteACeiling:
    """`_ceiling_refuses_dispatch`'s exemption (c), RESTORED BY THE FIX WAVE.

    This branch re-keyed (c) from *"`FLEET_WORKER` is absent, therefore I am
    the interface"* onto *"no registry record claims my sid AND I am not the
    claim-holder"*. That broke ratified `three-tier-command.md` §11.3 ND4 in
    three places at once and the tests below were written to the broken rule:

      (c) *"Exempt the interface structurally, with no sid at all ...
          independent of any sid resolution"* -- the re-keyed exemption was
          three sid resolutions deep.
      (b) *"An unresolvable identity must never be the reason a ceiling stays
          dormant"* -- it became exactly that reason: a caller at 500,000
          tokens whose sid no record carries was exempt, and so was one whose
          `state/fleet.json` was corrupt.

    THE ASYMMETRY THAT MAKES ND4(c) SOUND, which the re-key missed. The daemon
    leak DONATES a `FLEET_WORKER` stamp to sessions it never launched. Donation
    can only ADD a stamp; nothing removes one. So PRESENCE is unsound evidence
    and ABSENCE is sound -- and ND4(c) reads absence. The claim guard (Site B)
    read presence, which is why SPEC.md:196 names that guard and not this one.

    Direction of travel still matters here: at this site the inference only
    ever EXEMPTS, and the refusal's sole basis stays the measured occupancy of
    the acting transcript."""

    def _occ(self, monkeypatch, occupancy):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, sid: "/fake" if sid else None)
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: occupancy)

    def test_the_interface_session_is_still_exempt(self, id_home, monkeypatch):
        # The realistic interface: no `FLEET_WORKER` stamp (nothing fleet
        # launched it and no daemon donated to it), its own sid, no registry
        # record. Exempt no matter the occupancy (ND1/ND4c), and exempt
        # STRUCTURALLY -- before any sid is resolved.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        fleet.write_incarnation(_held("sid-holder"))
        _registry({"supervisor": _rec("sid-holder")})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_the_interface_is_exempt_even_with_an_empty_registry(
            self, id_home, monkeypatch):
        # Nothing places either sid -> `_caller_holds_supervisor_claim` would be
        # INDETERMINATE (None) and (b)'s fail-toward-band would catch the human
        # channel -- a refusal it could never escape, being outside fleet's
        # launch surface (§3.1). (c) runs ahead of (b) precisely so it cannot.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        fleet.write_incarnation(_held("sid-ghost"))
        _registry({})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_the_interface_is_exempt_even_with_a_CORRUPT_registry(
            self, id_home, monkeypatch):
        # ND4(c) is "independent of ANY sid resolution", and that has to include
        # the resolution that cannot happen. Also the Task 1 direction: the
        # exempt path must not read the registry at all, so it cannot quarantine
        # one either.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        fleet.write_incarnation(_held("sid-holder"))
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None
        assert fleet.registry_path().exists()

    def test_a_human_shell_with_no_sid_is_exempt(self, id_home, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        fleet.write_incarnation(_held("sid-holder"))
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_a_resolved_holder_over_the_ceiling_is_refused(self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|boot")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        fleet.write_incarnation(_held("sid-holder"))
        _registry({"sup|inc-x|boot": _rec("sid-holder", status="working")})
        self._occ(monkeypatch, 205000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_an_absent_FLEET_WORKER_EXEMPTS_because_ND4c_says_so(
            self, id_home, monkeypatch):
        """THE PIN THIS FIX WAVE INVERTED, and why.

        Its predecessor -- `test_an_absent_FLEET_WORKER_no_longer_exempts_the_
        holder` -- asserted the opposite, on the reasoning that the environment
        has no standing to excuse a registered, resolved, over-ceiling
        claim-holder. That reasoning is sound in the abstract and it is not the
        ratified rule: `three-tier-command.md` §11.3 ND4(c) exempts on
        `FLEET_WORKER`-absence *unconditionally* and *independent of any sid
        resolution*, and SPEC.md:196 -- the citation the re-key was built on --
        constrains only the guard enforcing *"a worker turn must never hold the
        supervisor claim"*, which this site is not.

        THE RESIDUAL HOLE THIS RATIFIES, stated so it is a known cost and not a
        surprise: a claim-holder that unsets `FLEET_WORKER` escapes the 200k
        ceiling. That is a self-inflicted escape by the one body the ceiling
        exists to slow down, not an attack surface -- and the ceiling is
        explicitly *"a speed-bump, not a security boundary"*. Buying protection
        against it costs the human control channel, which ND1 forbids."""
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        fleet.write_incarnation(_held("sid-holder"))
        _registry({"sup|inc-x|boot": _rec("sid-holder", status="working")})
        self._occ(monkeypatch, 400000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_a_donated_FLEET_WORKER_costs_a_session_the_structural_exemption(
            self, id_home, monkeypatch):
        """The accepted cost of ND4(c), inverted from its predecessor
        (`test_a_present_FLEET_WORKER_no_longer_costs_the_interface_its_
        exemption`) for the same reason as the test above.

        A daemon-donated stamp does make an interface session look
        fleet-launched, and it therefore loses the structural exemption and
        falls through to (b). This is the price of reading the ONE signal that
        answers "am I fleet-launched" without resolving a sid, and it fails in
        the SAFE direction: the body is measured rather than excused. The
        refusal wording must not tell such a caller that "the interface tier is
        never subject to it", because here it plainly is -- pinned separately by
        `test_the_refusal_does_not_claim_the_interface_can_never_see_it`."""
        monkeypatch.setenv("FLEET_WORKER", "a-worker-that-is-not-me")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        fleet.write_incarnation(_held("sid-holder"))
        _registry({"supervisor": _rec("sid-holder"),
                   "a-worker-that-is-not-me": _rec("sid-long-dead")})
        self._occ(monkeypatch, 500000)
        # `_caller_holds_supervisor_claim` places the holder and not the caller
        # -> provably NOT the holder -> False -> exempt by the middle arm. The
        # donation costs the STRUCTURAL exemption, not the verdict.
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_the_refusal_does_not_claim_the_interface_can_never_see_it(
            self, id_home, monkeypatch):
        """rb MINOR 6, re-graded into Task 2(c). An interface session CAN hold
        the claim -- `fleet sup-boot` is runnable from it and stamps its own
        sid -- and with a donated `FLEET_WORKER` it reaches this refusal. The
        shipped sentence *"the interface tier is never subject to it"* told
        that caller something false about its own situation."""
        monkeypatch.setenv("FLEET_WORKER", "a-donated-stamp")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        fleet.write_incarnation(_held("sid-interface"))
        _registry({"a-donated-stamp": _rec("sid-long-dead")})
        self._occ(monkeypatch, 500000)
        reason = fleet._ceiling_refuses_dispatch("send")
        assert reason is not None                    # it IS subject
        assert "never subject" not in reason
        assert "FLEET_WORKER" in reason              # names the escape it has


class TestSiteAFailsTowardTheBand:
    """TASK 5 PIN 2 -- ratified `three-tier-command.md` §11.3 ND4(b):
    *"An unresolvable identity must never be the reason a ceiling stays
    dormant."*

    This branch inverted it. Both shapes below were EXEMPT on the branch and
    both were measured by the break lens at 500,000 tokens; the second was
    driven end-to-end as `fleet spawn` at **999,999 tokens on a corrupt
    registry returning rc=0 and replacing the roster with a single record**.
    Two failures in one receipt -- a 200k hard ceiling bypassable by any
    condition that makes the registry unreadable, and a roster REPLACED rather
    than merely quarantined.

    A `FLEET_WORKER` stamp is present in every test here on purpose: without
    one, ND4(c) exempts structurally and (b) is never reached. (b) is the
    default AFTER (c) declines, not instead of it."""

    def _occ(self, monkeypatch, occupancy):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, sid: "/fake" if sid else None)
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: occupancy)

    def test_an_unplaceable_sid_REFUSES_at_the_ceiling(self, id_home, monkeypatch):
        # Neither the caller's sid nor the holder's is in any record ->
        # `_caller_holds_supervisor_claim` is INDETERMINATE. Fail toward the
        # band: measure this body rather than excuse it.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        fleet.write_incarnation(_held("sid-ghost"))
        _registry({"other": _rec("sid-else")})
        self._occ(monkeypatch, 500000)
        assert fleet._caller_holds_supervisor_claim("sid-mystery") is None
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_a_CORRUPT_registry_REFUSES_at_the_ceiling(self, id_home, monkeypatch):
        # The branch exempted here, which made the hard ceiling bypassable by
        # any condition that makes `state/fleet.json` unreadable.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        fleet.write_incarnation(_held("sid-ghost"))
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        self._occ(monkeypatch, 999999)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_the_ceiling_read_does_not_QUARANTINE_a_corrupt_registry(
            self, id_home, monkeypatch):
        # TASK 1's direction, at Site A. The refusal above is only half the
        # receipt: `load_registry` RENAMES a corrupt registry aside, so the
        # refusal could arrive having already destroyed the operator's
        # evidence. A ceiling check is a read.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        fleet.write_incarnation(_held("sid-ghost"))
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        self._occ(monkeypatch, 999999)
        fleet._ceiling_refuses_dispatch("spawn")
        assert fleet.registry_path().read_text(encoding="utf-8") == "{ not json"
        assert not list(fleet.registry_path().parent.glob("fleet.json.corrupt*"))

    def test_an_AMBIGUOUS_identity_REFUSES_at_the_ceiling(self, id_home, monkeypatch):
        # Two live records carry my sid -- itself a leak signature. The branch
        # exempted; ND4(b) says an identity fleet cannot settle is never the
        # reason the ceiling stays dormant.
        monkeypatch.setenv("FLEET_WORKER", "w-dup")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        claim = _held("sid-holder")
        del claim["session_id"]              # unreadable holder sid -> None
        fleet.write_incarnation(claim)
        _registry({"a": _rec("sid-dup"), "b": _rec("sid-dup")})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_a_body_provably_not_the_holder_is_still_exempt(
            self, id_home, monkeypatch):
        # The line (b) must not cross: an ordinary worker whose sid the registry
        # PLACES, against a holder the registry also places, is definitely not
        # the holder. Not indeterminate -- exempt, ceiling or no ceiling.
        monkeypatch.setenv("FLEET_WORKER", "w1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-worker")
        fleet.write_incarnation(_held("sid-holder"))
        _registry({"w1": _rec("sid-worker"), "sup|inc-x|boot": _rec("sid-holder")})
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None


# --------------------------------------------------------------------------
# 4. Site B -- `_require_claim_holder`, under the §5 invariant.
# --------------------------------------------------------------------------

class TestInferenceNeverRefuses:
    """WHAT THE RE-KEY BUYS, AND WHAT IT DOES NOT -- corrected by the fix wave.

    This class was written under the reading that the worker-turn arm must stop
    being a gate and become a CLASSIFIER, because an identity inference derived
    from the environment may never be the SOLE basis of a refusal (the PROPOSED
    invariant, claim-nonce §16.4 item 3, which originates in a supervisor
    instruction and is in NO ratified document).

    THE GATE IS RESTORED and the cure survives it, which is the point this
    class now pins. The §1 wedge -- a legitimate claim-holder refused its own
    `sup-release` -- is cured by the RE-KEY alone: the wedged supervisor's own
    registry record is supervisor-shaped, `_is_supervisor_shaped` exempts it,
    and the donated worker-shaped `FLEET_WORKER` that used to decide the
    refusal now decides nothing. The demotion bought a second thing on top --
    that a worker-shaped body presenting a valid nonce also passes -- and that
    is only valuable under the OPEN hypothesis that the daemon donates the SID
    as well as the stamp (claim-nonce:2573). Ratified §6.5 D5 requires the
    refusal to exist; SPEC.md:196 constrains only its KEY; a registry-keyed
    gate satisfies both, so nothing had to be traded away."""

    def test_a_worker_shaped_identity_holding_the_live_nonce_IS_refused(
            self, id_home, monkeypatch, capsys):
        """The demotion, reversed -- and the cost of the reversal, stated.

        The registry judges this body to be the ordinary worker `some-worker`,
        and claim-nonce §6.5 D5 says the supervisor claim is not a worker's to
        hold. It is refused even though it presents the LIVE generation.

        Under hypothesis (ii) -- the daemon donates the sid too -- this body
        could be a legitimate supervisor wearing a worker's registry identity,
        and refusing it would be the §1 wedge all over again one layer down.
        That hypothesis is OPEN, deciding it needs the machine-wide daemon
        restarted from a process that HOLDS a sid, and trading a ratified
        control away to insure against it is the operator's call. Filed, not
        taken."""
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _registry({"some-worker": _rec("sid-me", status="working")})
        live = _hold_with_live_nonce("sid-me")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=live))
        assert "worker turn" in str(exc.value)
        capsys.readouterr()

    def test_the_gate_is_AHEAD_of_the_claim_read(self, id_home, monkeypatch):
        """The ordering `main` had, restored -- and it is not cosmetic.

        With the classifier sitting AFTER the four nonce arms instead, a worker
        turn walked through rule 4 (the §9 legacy path) on sid equality ALONE,
        upgraded the legacy claim and minted itself generation 1 with no
        `--nonce` ever passed. Reachability was bounded -- nothing mints a
        five-key legacy INCARNATION today -- but the ordering is what closed
        it, so the ordering is what gets pinned."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        fleet.write_incarnation({                        # a five-key legacy claim
            "incarnation_id": "inc-legacy", "session_id": "sid-w1",
            "lineage_id": "lin-x", "state": "active",
            "heartbeat_at": fleet.now_iso()})
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1"))
        assert "worker turn" in str(exc.value)
        # The claim was never upgraded: no generation was minted for a worker.
        assert "nonce_hash" not in fleet.read_incarnation()

    def test_the_wedged_supervisor_can_still_RELEASE(self, id_home, monkeypatch, capsys):
        """The §1 incident, end to end, asserted at the verb that was
        unreachable.

        A supervisor body hosted by a daemon that an ordinary WORKER dispatch
        started: the donated `FLEET_WORKER` is worker-shaped, so the shipped
        arm refused `_require_claim_holder` -- and the body could `sup-boot`
        (which does not call it) and take the claim, then never heartbeat,
        checkpoint, or RELEASE it. A wedged claim needing a manual operator
        lever.

        This asserts the END STATE of the protocol, not that the next step is
        reachable: the claim must actually come out `released`."""
        monkeypatch.setenv("FLEET_WORKER", "hs-fix2")          # the donated witness
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"hs-fix2": _rec("sid-long-dead", status="idle"),
                   "sup|inc-x|boot": _rec("sid-sup", status="working")})
        live = _hold_with_live_nonce("sid-sup")
        assert fleet.cmd_sup_release(
            SimpleNamespace(reason="done", sid="sid-sup", nonce=live)) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["state"] == "released"

    def test_the_wedged_supervisor_can_still_HEARTBEAT_and_CHECKPOINT(
            self, id_home, monkeypatch, capsys):
        monkeypatch.setenv("FLEET_WORKER", "hs-fix2")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"hs-fix2": _rec("sid-long-dead"),
                   "sup|inc-x|boot": _rec("sid-sup", status="working")})
        live = _hold_with_live_nonce("sid-sup")
        assert fleet.cmd_sup_heartbeat(
            SimpleNamespace(sid="sid-sup", nonce=live)) == 0
        nxt = _nonce_from(capsys.readouterr().out) or live
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-sup", nonce=nxt)) == 0
        capsys.readouterr()
        assert fleet.supervisor_journal_entries()

    def test_an_unresolved_body_passes_through_to_the_nonce(
            self, id_home, monkeypatch, capsys):
        # §4, the dispatch window: no record claims my sid yet. Pass through --
        # the nonce is the real gate and loses nothing the env arm provided.
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-newborn")
        _registry({"some-worker": _rec("sid-long-dead"), "pre": _rec(None)})
        live = _hold_with_live_nonce("sid-newborn")
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-newborn", nonce=live)) == 0
        capsys.readouterr()

    def test_an_unresolved_body_WITHOUT_the_nonce_still_faces_continuity(
            self, id_home, monkeypatch):
        # "Pass through" means to the nonce, not around it.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-newborn")
        _registry({})
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-newborn", nonce=fleet.mint_nonce()))
        assert "continuity proof failed" in str(exc.value)

    def test_an_ambiguous_body_of_MIXED_SHAPE_passes_through_to_the_nonce(
            self, id_home, monkeypatch, capsys):
        """AMBIGUOUS is no longer a blanket abstention -- FIX WAVE 2, MAJOR 2.

        This test used to plant TWO ORDINARY WORKERS and assert they passed.
        That is now a refusal and `tests/test_identity_fixwave2.py` pins it:
        when every candidate is a worker, which one this body is does not
        matter, because every answer is a worker turn.

        What survives here is the ambiguity that is genuinely mute. One
        candidate is a worker and the other is supervisor-shaped, so the two
        answers disagree, the registry has no verdict to give, and the nonce
        stays the real gate."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"a": _rec("sid-dup"), "sup|inc-x|boot": _rec("sid-dup")})
        live = _hold_with_live_nonce("sid-dup")
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-dup", nonce=live)) == 0
        capsys.readouterr()

    def test_a_supervisor_shaped_identity_still_faces_the_continuity_check(
            self, id_home, monkeypatch):
        # Exempt from the ROLE classifier is not exempt from §5.3.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|inc-x|boot": _rec("sid-sup")})
        _hold_with_live_nonce("sid-sup")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-sup", nonce=fleet.mint_nonce()))
        assert "continuity proof failed" in str(exc.value)


class TestTheRoleClassifier:
    """What survives of claim-nonce §6.5: a body the REGISTRY judges to be an
    ordinary worker, which ALSO fails the nonce, is told it is a worker rather
    than told a second body may be acting. The refusal is the nonce's; the
    wording, the exit code and the log kind are the classifier's."""

    def _worker_turn(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})

    def test_a_worker_turn_without_the_nonce_is_named_as_a_worker(
            self, id_home, monkeypatch):
        self._worker_turn(monkeypatch)
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1", nonce=fleet.mint_nonce()))
        msg = str(exc.value)
        assert "worker turn" in msg
        assert "w1" in msg
        assert "sup-checkpoint" in msg
        assert fleet.supervisor_journal_entries() == []

    def test_the_name_comes_from_the_registry_not_the_environment(
            self, id_home, monkeypatch):
        # The receipt again, at the classifier: the message must name the
        # record my sid resolves to, never the donated witness.
        monkeypatch.setenv("FLEET_WORKER", "the-donated-stranger")
        self._worker_turn(monkeypatch)
        _registry({"w1": _rec("sid-w1", status="working"),
                   "the-donated-stranger": _rec("sid-long-dead")})
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1", nonce=fleet.mint_nonce()))
        assert "w1" in str(exc.value)
        assert "the-donated-stranger" not in str(exc.value)

    def test_it_is_an_ordinary_error_not_a_continuity_failure(
            self, id_home, monkeypatch):
        # Exit 4 means "a second body of your lineage may be acting" (§5.6).
        # A worker reaching a supervisor verb is a ROLE error and is not
        # evidence of a second body; conflating them would make the one code an
        # operator scripts against mean two different incidents.
        self._worker_turn(monkeypatch)
        _hold_with_live_nonce("sid-holder")
        assert fleet.main(["sup-checkpoint", "body", "--sid", "sid-w1"]) == 1

    def test_the_role_refusal_is_not_logged_as_a_continuity_refusal(
            self, id_home, monkeypatch):
        # A `refused` record makes `fleet doctor` say "a second body of this
        # lineage may be acting" (SPEC.md:273). A worker turn is not that, and
        # must not train the operator to ignore the one signal that does mean
        # two bodies.
        #
        # With the GATE restored the worker turn is refused BEFORE the claim is
        # read, so no rejection is journalled at all -- `_append_nonce_rejection`
        # takes the claim this call never gets to. That is `main`'s behaviour
        # and it satisfies the requirement the same way, by never filing the
        # wrong kind rather than by filing a second one. The evidence trade is
        # recorded in FIX-WAVE-IDENTITY.md: a worker turn now leaves no
        # rejection trace, exactly as it did before this branch existed.
        self._worker_turn(monkeypatch)
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1", nonce=fleet.mint_nonce()))
        kinds = [r.get("kind") for r in fleet._recent_nonce_rejections()]
        assert "refused" not in kinds
        name, ok, _msg = fleet._doctor_check_supervisor_claim()
        assert ok is True

    def test_a_sid_override_continuity_refusal_IS_filed_as_refused(
            self, id_home, monkeypatch):
        """TASK 4's consequence, pinned.

        The role was read from `current_caller_session()` while the continuity
        check ran against `sid_override or current_caller_session()` -- one
        function, two caller identities. A genuine second-body continuity
        failure raised by a caller using `--sid` was therefore classified off
        the AMBIENT sid, filed under kind `worker-turn`, and
        `_doctor_check_supervisor_claim` stayed GREEN through exactly the
        incident it exists to catch.

        Here the ambient environment says `sid-w1` (a worker) and the caller
        typed `--sid sid-other` (not a worker, and not the holder). Ratified
        claim-nonce §4.3 makes what the caller typed the sole source of caller
        identity, so this is a continuity failure and must be filed as one."""
        self._worker_turn(monkeypatch)               # ambient env: worker `w1`
        _registry({"w1": _rec("sid-w1", status="working")})
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.SupervisorContinuityError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-other", nonce=fleet.mint_nonce()))
        kinds = [r.get("kind") for r in fleet._recent_nonce_rejections()]
        assert kinds == ["refused"], kinds
        _name, ok, msg = fleet._doctor_check_supervisor_claim()
        assert ok is False, msg

    def test_it_is_still_described_as_a_speed_bump_not_a_boundary(
            self, id_home, monkeypatch):
        self._worker_turn(monkeypatch)
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1", nonce=fleet.mint_nonce()))
        assert "not a security boundary" in str(exc.value)

    def test_a_worker_turn_facing_no_claim_at_all_is_told_it_is_a_worker(
            self, id_home, monkeypatch):
        # The role answer does not depend on whether a claim exists, and the
        # refusal here is the absent claim's -- inference only adds the
        # sentence that tells the body why it should not be here.
        self._worker_turn(monkeypatch)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1"))
        assert "w1" in str(exc.value)
        assert "worker turn" in str(exc.value)

    def test_a_supervisor_shaped_record_is_never_classified_as_a_worker(
            self, id_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|inc-x|boot": _rec("sid-sup", status="working")})
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-sup", nonce=fleet.mint_nonce()))
        assert "worker turn" not in str(exc.value)
        assert "continuity proof failed" in str(exc.value)

    def test_an_unresolved_body_is_never_classified_as_a_worker(
            self, id_home, monkeypatch):
        # The dispatch window must not turn a newborn supervisor's continuity
        # failure into "you are a worker".
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-newborn")
        _registry({"some-worker": _rec("sid-long-dead")})
        _hold_with_live_nonce("sid-holder")
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-newborn", nonce=fleet.mint_nonce()))
        assert "worker turn" not in str(exc.value)

    @pytest.mark.parametrize("verb", ["checkpoint", "heartbeat", "handoff-abort"])
    def test_every_require_claim_holder_caller_classifies(
            self, id_home, monkeypatch, verb):
        self._worker_turn(monkeypatch)
        _hold_with_live_nonce("sid-holder")
        bad = fleet.mint_nonce()
        calls = {
            "checkpoint": lambda: fleet.cmd_sup_checkpoint(_ckpt(sid="sid-w1", nonce=bad)),
            "heartbeat": lambda: fleet.cmd_sup_heartbeat(
                SimpleNamespace(sid="sid-w1", nonce=bad)),
            "handoff-abort": lambda: fleet.cmd_sup_handoff_abort(
                SimpleNamespace(sid="sid-w1", nonce=bad, successor_sid="sid-x")),
        }
        with pytest.raises(fleet.FleetCliError) as exc:
            calls[verb]()
        assert "w1" in str(exc.value)


# --------------------------------------------------------------------------
# 5. The doctor row -- the leak, announced by name.
# --------------------------------------------------------------------------

class TestDoctorAnnouncesTheLeak:
    """`FLEET_WORKER` keeps being written by `_worker_env`. It stops being a
    predicate anywhere and becomes a WITNESS -- and a witness that disagrees
    with the registry is a detected leak `fleet doctor` reports by name."""

    def _check(self, workers=None):
        return fleet._doctor_check_identity_witness(
            workers if workers is not None else fleet.load_registry()["workers"])

    def test_a_RESOLVED_body_with_NO_witness_is_REDDENED(self, id_home, monkeypatch):
        """FIX WAVE 2, Task 5 item 4 -- the one state that FALSIFIES the
        ceiling's soundness argument, and it used to be the greenest row here.

        ND4(c)'s structural exemption rests on *"donation can only ever ADD a
        stamp; nothing removes one"*, so an ABSENT `FLEET_WORKER` is sound
        evidence that no fleet dispatch is in this session's donation chain.
        Registry-RESOLVED + witness-GONE is exactly the state that makes that
        false: the registry says a fleet dispatch created this body, and the
        stamp that dispatch wrote is not here.

        The confirmation review found no reachable blanker anywhere in fleet,
        the hooks, the settings template or the launcher -- so the escape stays
        a note rather than a finding, and ND1 forbids PREVENTING it in any
        case. ND1 says nothing about DETECTING it, and the information to
        redden this row was already in the message it printed."""
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1")})
        name, ok, msg = self._check()
        assert name == "identity-witness"
        assert ok is False
        assert "no FLEET_WORKER" in msg and "w1" in msg
        # The row must name what it costs, or an operator cannot act on it.
        assert "200k" in msg or "ceiling" in msg

    def test_a_blanked_witness_reddens_it_too(self, id_home, monkeypatch):
        """`FLEET_WORKER=""`, `"   "`, `"\\t"`, `"\\n"` are not merely
        falsy-absent, they are `.strip()`-absent -- all four grant the
        structural exemption. The doctor row reads the stamp through the same
        `.strip()`, so it must redden on all four rather than on unset alone."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1")})
        for blank in ("", "   ", "\t", "\n"):
            monkeypatch.setenv("FLEET_WORKER", blank)
            _name, ok, _msg = self._check()
            assert ok is False, f"a blanked witness {blank!r} stayed green"

    def test_an_UNRESOLVED_body_with_no_witness_stays_GREEN(self, id_home, monkeypatch):
        """The interface session and every non-fleet shell live here, and they
        are the common case. No record claims this sid, so nothing says a fleet
        dispatch is in the donation chain, and the absent stamp agrees."""
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-nobody")
        _registry({"w1": _rec("sid-w1")})
        _name, ok, msg = self._check()
        assert ok is True
        assert "no FLEET_WORKER" in msg

    def test_a_human_shell_with_neither_a_sid_nor_a_witness_stays_GREEN(
            self, id_home, monkeypatch):
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _registry({"w1": _rec("sid-w1")})
        _name, ok, _msg = self._check()
        assert ok is True

    def test_the_remedy_text_stops_being_silent_about_REMOVAL(self):
        """`DAEMON_ENV_LEAK_REMEDY` said the one decision keyed on this variable
        keys on the stamp's ABSENCE, *"which donation cannot manufacture"*. True
        of donation and silent about removal -- and removal is the half that
        matters, because absence is what grants the exemption."""
        assert "donation cannot manufacture" in fleet.DAEMON_ENV_LEAK_REMEDY
        assert "remove" in fleet.DAEMON_ENV_LEAK_REMEDY.lower()

    def test_an_agreeing_witness_passes(self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "w1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1")})
        _name, ok, msg = self._check()
        assert ok is True
        assert "agrees" in msg and "w1" in msg

    def test_a_disagreeing_witness_FAILS_and_names_both_records(
            self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "stale-donor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _registry({"stale-donor": _rec("sid-long-dead", status="idle"),
                   "real-me": _rec("sid-me", status="working")})
        _name, ok, msg = self._check()
        assert ok is False
        assert "stale-donor" in msg and "real-me" in msg

    def test_the_disagreement_row_tells_the_operator_what_to_do(
            self, id_home, monkeypatch):
        # The fix is out of fleet's hands -- it is the machine-wide daemon that
        # donates the env, so the row must name BOTH levers: let the daemon
        # idle-exit, or ensure the supervisor's own dispatch starts it.
        monkeypatch.setenv("FLEET_WORKER", "stale-donor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _registry({"stale-donor": _rec("sid-long-dead"), "real-me": _rec("sid-me")})
        _name, _ok, msg = self._check()
        assert "daemon" in msg
        assert "idle-exit" in msg
        assert "supervisor's own dispatch" in msg

    def test_a_witness_naming_no_record_at_all_still_FAILS(self, id_home, monkeypatch):
        # A cleaned-away donor. The witness still disagrees with the registry.
        monkeypatch.setenv("FLEET_WORKER", "long-since-cleaned")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _registry({"real-me": _rec("sid-me")})
        _name, ok, msg = self._check()
        assert ok is False
        assert "long-since-cleaned" in msg
        assert "no registry record" in msg

    def test_ambiguity_is_announced_DISTINCTLY_from_a_plain_disagreement(
            self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "dup-one")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"dup-one": _rec("sid-dup"), "dup-two": _rec("sid-dup")})
        _name, ok, msg = self._check()
        assert ok is False
        assert "AMBIGUOUS" in msg
        assert "dup-one" in msg and "dup-two" in msg
        # distinct in KIND, not merely in wording: the disagreement row's
        # signature phrase must not be what an operator reads here.
        assert "witness names a DIFFERENT record" not in msg

    def test_ambiguity_is_announced_even_without_a_witness(self, id_home, monkeypatch):
        # Two live records sharing one sid is a leak signature in its own
        # right; it does not need `FLEET_WORKER` to be present to be worth a row.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"a": _rec("sid-dup"), "b": _rec("sid-dup")})
        _name, ok, msg = self._check()
        assert ok is False
        assert "AMBIGUOUS" in msg

    def test_an_unresolved_body_is_NOTED_not_failed(self, id_home, monkeypatch):
        # The dispatch window: a legitimately-new body has no sid-matching
        # record for its own first moments. Announce, never fail -- §5 lets
        # inference inform, and a transient window must not turn doctor red.
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-newborn")
        _registry({"some-worker": _rec("sid-w1"), "pre": _rec(None)})
        _name, ok, msg = self._check()
        assert ok is True
        assert "NOTE" in msg
        assert "dispatch window" in msg

    def test_a_human_shell_with_a_witness_but_no_sid_is_noted_not_failed(
            self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _registry({"some-worker": _rec("sid-w1")})
        _name, ok, _msg = self._check()
        assert ok is True

    def test_the_check_is_wired_into_fleet_doctor(self, id_home, monkeypatch, capsys):
        monkeypatch.setenv("FLEET_WORKER", "stale-donor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _registry({"stale-donor": _rec("sid-long-dead"), "real-me": _rec("sid-me")})
        rc = fleet.cmd_doctor(SimpleNamespace(), which=lambda n: None,
                              run=lambda *a, **k: SimpleNamespace(
                                  returncode=1, stdout="", stderr=""))
        out = capsys.readouterr().out
        assert "[FAIL] identity-witness:" in out
        assert rc != 0

    def test_the_row_never_raises_on_a_corrupt_registry(self, id_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "w1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-me")
        _name, ok, _msg = fleet._doctor_check_identity_witness({"w1": "not-a-dict"})
        assert isinstance(ok, bool)


# --------------------------------------------------------------------------
# 6. The write survives. FLEET_WORKER is still stamped -- the doctor row above
#    has nothing to check if the witness stops being written.
# --------------------------------------------------------------------------

class TestTheWitnessIsStillWritten:
    def test_worker_env_still_stamps_FLEET_WORKER(self, monkeypatch):
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        assert fleet._worker_env("pmbot")["FLEET_WORKER"] == "pmbot"

    def test_worker_env_still_strips_the_inherited_session_id(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-parent")
        assert "CLAUDE_CODE_SESSION_ID" not in fleet._worker_env("pmbot")

    def test_FLEET_WORKER_is_not_a_predicate_at_the_CLAIM_GUARD(self):
        """The structural pin, RE-SCOPED BY THE FIX WAVE (Task 2).

        The rule this pin enforced -- *"`FLEET_WORKER` appears exactly once,
        in the doctor row"* -- was wrong, and it was wrong in the direction
        that fights ratified text. `three-tier-command.md` §11.3 ND4(c)
        (spec-of-record, ratified 2026-07-23) REQUIRES the 200k ceiling to
        *"exempt the interface structurally, with no sid at all ... independent
        of any sid resolution"*, and the only thing on this machine that
        answers "am I a fleet-launched body at all" without resolving a sid is
        `FLEET_WORKER`'s ABSENCE.

        SPEC.md:196's prohibition is NARROWER than this pin read it. Quoted:
        *"A future guard enforcing `a worker turn must never hold the
        supervisor claim` must key on the registry or the claim itself, never
        on `FLEET_WORKER`."* That is one guard -- the claim guard, Site B --
        and `_ceiling_refuses_dispatch` is not it: it is an occupancy ceiling
        whose `FLEET_WORKER` read was an EXEMPTION for the human channel, never
        a refusal of a worker turn.

        AND THE TWO DIRECTIONS ARE NOT SYMMETRIC, which is what the original
        pin missed. The daemon leak DONATES a stamp: a session the daemon hosts
        inherits the `FLEET_WORKER` of whichever `--bg` dispatch started the
        daemon. Donation can only ever ADD a stamp -- there is no mechanism
        that REMOVES one. So `FLEET_WORKER` PRESENT is unsound evidence ("I am
        that worker" may be a lie), while `FLEET_WORKER` ABSENT is sound ("no
        fleet dispatch is anywhere in my donation chain"). ND4(c) keys on the
        sound direction. The claim guard keyed on the unsound one, and that is
        the defect SPEC.md:196 records.

        So the pin now asserts what actually holds: the reads are exactly the
        two ALLOWLISTED non-predicate/structural sites, and the claim guard is
        not one of them."""
        from pathlib import Path
        import re
        lines = Path(fleet.__file__).read_text(encoding="utf-8").splitlines()
        owner, cur = {}, None
        for i, ln in enumerate(lines, start=1):
            m = re.match(r"^(?:def|class)\s+(\w+)", ln)
            if m:
                cur = m.group(1)
            owner[i] = cur
        reads = {owner[i] for i, ln in enumerate(lines, start=1)
                 if 'os.environ.get("FLEET_WORKER")' in ln
                 or "os.environ.get('FLEET_WORKER')" in ln}
        # The seed check: a reworded read that this matcher misses would make
        # every assertion below pass vacuously, which is the failure mode
        # `tools/verify_receipts.py --self-test` exists for.
        assert reads, "no `FLEET_WORKER` read found at all -- the matcher rotted"
        assert reads == {"_ceiling_refuses_dispatch", "_doctor_check_identity_witness"}, (
            f"unexpected `FLEET_WORKER` reader(s): {sorted(reads)}. Only two are "
            f"allowed: three-tier §11.3 ND4(c)'s structural ceiling exemption "
            f"(absence, the sound direction) and the doctor row that reports the "
            f"witness/registry disagreement. Anything else is a predicate.")
        assert "_require_claim_holder" not in reads, (
            "SPEC.md:196: the guard enforcing `a worker turn must never hold the "
            "supervisor claim` must key on the registry or the claim itself")


def _nonce_from(out: str):
    """The one plaintext generation a verb delivers, off its stdout."""
    for line in out.splitlines():
        if line.startswith("NONCE: ") and "unchanged" not in line:
            return line.split("NONCE: ", 1)[1].strip()
    return None
