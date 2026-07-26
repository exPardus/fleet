"""B6 re-keyed through the sid UNION (`_record_sids`), not a bare `session_id`.

Councilor 1's finding, verified by the supervisor against `main` @ `8252806`
(`docs/AUTONOMOUS-2026-07-26.md` §R3): B6 compared a bare `released_by_sid`
against the roster while `_record_sids` -- whose own docstring says *"matching
against `session_id` alone fails open on it (ND4a)"* -- keys seven other sites
(`:2020, :2064, :2116, :5503, :5790, :6057, :7117`). B6 was not one of them, and
that is why it evaporated for the fork-steered holder in §G-G: it tested the
post-fork sid while the roster held the pre-fork one.

THE ORDERING IS THE RULING, and this file is the second half of it. Re-keying
B6 converts it from fail-open to fail-closed, so it CREATES wedges where a
successor previously booted through -- and before
`tests/test_gate_arm_wedge.py`'s containment landed, every created wedge was an
indefinite fleet-wide UNGATED window. This change must never ship without that
one; the shared predicate is what makes "never Task 2 alone" mechanical rather
than a note in a commit message.
"""
import pytest

import fleet


RELEASER = "sid-releaser"
THIRD = "sid-third-body"


@pytest.fixture
def wedge_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


def _released(released_by=RELEASER, **extra):
    claim = {"incarnation_id": "inc-old", "lineage_id": "lin-L",
             "claimed_via": "fresh", "released_at": fleet.now_iso(),
             "released_by_sid": released_by, "state": "released"}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return claim


def _roster(monkeypatch, *live_sids, ok=True):
    entries = [{"sessionId": s, "status": "idle", "pid": 4242} for s in live_sids]
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (ok, entries if ok else "roster unavailable"))
    return entries


def _tombstone(name="ghost", sid="sid-ghost"):
    rec = fleet.new_worker_record(sid, "C:/proj", "task", "acceptEdits",
                                  dispatch_kind="bg")
    rec["status"] = "dead"
    rec["archived_at"] = fleet.now_iso()
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _names():
    return sorted(fleet.load_registry()["workers"])


# --- Task 2: B6 re-keyed through the sid union -----------------------------

class TestB6IsKeyedOnTheSidUnion:
    """c1's finding. `_record_sids` (session_id U retired_sids) is the ONE
    identity concept; B6 was the only roster comparison not using it, and G-G
    measured it failing open for a fork-steered releaser."""

    def _registry(self, current, retired=(), name="sup|inc-old|boot"):
        rec = fleet.new_worker_record(current, "C:/proj", "t", "acceptEdits",
                                      dispatch_kind="bg")
        rec["retired_sids"] = list(retired)
        return {"workers": {name: rec}}

    def test_b6_refuses_when_the_releaser_sid_is_only_in_retired_sids(self):
        # G-G, exactly: the body fork-steered after releasing, so the record
        # was eagerly restamped (session_id = post-fork) while INCARNATION
        # still carries the PRE-fork sid it was written with. The roster lists
        # the post-fork sid. A bare comparison finds nothing and boots a second
        # supervisor through.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-pre-fork", "state": "released"}
        v, reason = fleet.supervisor_claim_decision(
            released, {"sid-post-fork"}, None, caller_sid="sid-successor",
            registry=self._registry("sid-post-fork", retired=["sid-pre-fork"]))
        assert v == "refuse"
        assert "sid-pre-fork" in reason

    def test_the_gate_arms_through_the_union_too(self, wedge_home, monkeypatch):
        # One predicate, two consumers: the same fork-steered wedge that B6
        # must refuse is the one the §7 gate must arm on. Drives the last verb.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-pre-fork")
        _roster(monkeypatch, "sid-post-fork")
        rec = fleet.new_worker_record("sid-post-fork", "C:/proj", "t", "acceptEdits",
                                      dispatch_kind="bg")
        rec["retired_sids"] = ["sid-pre-fork"]
        data = fleet.load_registry()
        data["workers"]["sup|inc-old|boot"] = rec
        fleet.save_registry(data)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC
        assert "ghost" in _names()

    def test_b6_still_claims_when_no_sid_of_the_record_is_live(self):
        # The union widens WHICH sids answer for the releaser; it must not
        # make the wedge permanent. Record fully roster-gone -> claim.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-pre-fork", "state": "released"}
        v, reason = fleet.supervisor_claim_decision(
            released, {"sid-unrelated"}, None, caller_sid="sid-successor",
            registry=self._registry("sid-post-fork", retired=["sid-pre-fork"]))
        assert v == "claim"
        assert "released cleanly" in reason

    def test_the_union_never_makes_one_body_answer_for_another(self):
        # The SAFETY INVARIANT the send carve-out is also built on (:10575):
        # every writer appends only that record's OWN prior sid, so a live sid
        # in a DIFFERENT record can never make this releaser look live.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-pre-fork", "state": "released"}
        reg = self._registry("sid-post-fork", retired=["sid-pre-fork"])
        other = fleet.new_worker_record("sid-live-other", "C:/proj", "t",
                                        "acceptEdits", dispatch_kind="bg")
        reg["workers"]["unrelated"] = other
        v, _ = fleet.supervisor_claim_decision(
            released, {"sid-live-other"}, None, caller_sid="sid-successor",
            registry=reg)
        assert v == "claim"

    def test_a_bare_live_releaser_sid_still_refuses_without_any_registry(self):
        # The union is ADDITIVE. B6's shipped, ratified case -- releaser sid
        # live, no record carries it -- keeps answering `refuse` even when the
        # registry is unreadable or absent, so the re-key can never be a
        # regression on the state it already caught.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-old", "state": "released"}
        v, _ = fleet.supervisor_claim_decision(
            released, {"sid-old"}, None, caller_sid="sid-new", registry=None)
        assert v == "refuse"

    def test_a_corrupt_registry_degrades_to_the_bare_comparison(
            self, wedge_home, monkeypatch):
        # A registry fleet cannot read yields None, which is today's bare-sid
        # answer -- never worse than shipped, never a crash on a boot or on a
        # mutating verb. Real corruption on disk, not a patched reader.
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        assert fleet._registry_records_or_none() is None

        # Driven through the GATE, the consumer that actually reads it: a
        # corrupt registry must not brick every mutating verb, and must not
        # stop the bare-sid wedge from arming either.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-old")
        _roster(monkeypatch, "sid-old")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean", nonce=None)
        _roster(monkeypatch, "sid-other")
        fleet._supervisor_gate("clean", nonce=None)      # disarmed, no crash

    def test_the_gate_never_quarantines_a_corrupt_registry(
            self, wedge_home, monkeypatch):
        """The defect this re-key nearly minted, pinned.

        `load_registry` quarantines a corrupt registry -- it RENAMES the file
        aside (`bin/fleet.py:812`), which is a write. `_supervisor_gate`
        documents itself "READ-ONLY: no lock, no mint, no write" and runs at
        the top of every mutating verb, so reading the records through
        `load_registry` would let a speed-bump destroy the operator's evidence
        while claiming to touch nothing. D4 states the rule for the view path;
        this is the same rule for the gate's identity read."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-old")
        _roster(monkeypatch, "sid-old")
        fleet.registry_path().write_text("{ not json", encoding="utf-8")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean", nonce=None)
        assert fleet.registry_path().exists(), "the gate quarantined the registry"
        assert not list(fleet.registry_path().parent.glob("fleet.json.corrupt.*"))


class TestOnePredicateForBothConsumers:
    """R3's process lesson -- "this project reliably writes down the right rule
    and then ships a guard that does not follow it" -- applied here: B6 and the
    §7 gate must not be able to disagree about what a wedge IS, because the
    ruling's whole ordering argument assumes they are the same state."""

    @pytest.mark.parametrize("live,expect", [
        ({"sid-pre-fork"}, True),
        ({"sid-post-fork"}, True),
        ({"sid-unrelated"}, False),
        (set(), False),
    ])
    def test_the_shared_predicate_decides_both(self, live, expect):
        rec = fleet.new_worker_record("sid-post-fork", "C:/proj", "t", "acceptEdits",
                                      dispatch_kind="bg")
        rec["retired_sids"] = ["sid-pre-fork"]
        reg = {"workers": {"sup|inc-old|boot": rec}}
        claim = {"incarnation_id": "inc-old", "state": "released",
                 "released_by_sid": "sid-pre-fork", "released_at": fleet.now_iso()}
        assert fleet._releaser_is_roster_live(claim, live, registry=reg) is expect
        v, _ = fleet.supervisor_claim_decision(
            claim, live, None, caller_sid="sid-new", registry=reg)
        assert (v == "refuse") is expect
