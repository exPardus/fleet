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
from datetime import datetime, timezone

import pytest

import fleet


RELEASER = "sid-releaser"
THIRD = "sid-third-body"

# The claim is released at `now`; a record the releasing body ALREADY HAD is
# necessarily older than that. Stated as a constant because it is the whole
# boundary between a fork-steer and a respawn (fix-wave item 3): a fork-steer
# mutates the record in place and leaves `created` alone, a respawn mints a
# fresh record whose `created` is stamped AFTER the release it is respawning
# past. Written explicitly rather than left at `new_worker_record`'s `now_iso()`
# so these fixtures do not depend on which side of a one-second tick they land.
BEFORE_RELEASE = "2020-01-01T00:00:00Z"
AFTER_RELEASE = "2099-01-01T00:00:00Z"


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


def _record(current, retired=(), created=BEFORE_RELEASE):
    rec = fleet.new_worker_record(current, "C:/proj", "t", "acceptEdits",
                                  dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    rec["created"] = created
    return rec


def _install(rec, name="sup|inc-old|boot"):
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _names():
    return sorted(fleet.load_registry()["workers"])


@pytest.fixture(autouse=True)
def _never_dispatch(monkeypatch):
    """MAJ-4, applied to the class -- see the twin fixture in
    `tests/test_supervisor_gate.py`. Nothing in this file may reach a real
    claude session."""
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
        "a gate test reached dispatch_bg -- that dispatches a REAL claude session"))


# --- Task 2: B6 re-keyed through the sid union -----------------------------

class TestB6IsKeyedOnTheSidUnion:
    """c1's finding. `_record_sids` (session_id U retired_sids) is the ONE
    identity concept; B6 was the only roster comparison not using it, and G-G
    measured it failing open for a fork-steered releaser."""

    def _registry(self, current, retired=(), name="sup|inc-old|boot",
                  created=BEFORE_RELEASE):
        return {"workers": {name: _record(current, retired, created)}}

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
        _install(_record("sid-post-fork", ["sid-pre-fork"]))
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

    def test_sup_boot_itself_refuses_the_fork_steered_wedge(
            self, wedge_home, monkeypatch, capsys):
        """THE LAST VERB for B6, and the only test that can catch
        `cmd_sup_boot` failing to hand the registry over.

        Every other test in this class calls `supervisor_claim_decision`
        directly and supplies `registry=` itself, so all of them stay green if
        the one production call site drops the argument -- and rule 1 would
        silently go back to the bare comparison that failed open in §G-G.
        Asserting on the predicate is precisely the smell the 2026-07-26
        ruling is about, so this drives `fleet sup-boot` and asserts on what it
        did to the claim."""
        entries = _roster(monkeypatch, "sid-post-fork", "sid-successor")
        _released(released_by="sid-pre-fork")
        _install(_record("sid-post-fork", ["sid-pre-fork"]))

        rc = fleet.main(["sup-boot", "--sid", "sid-successor"])

        assert rc == fleet.SUPERVISOR_BOOT_RC["refuse"]
        after = fleet.read_incarnation()
        assert after["state"] == "released", "sup-boot consumed a wedged claim"
        assert after["incarnation_id"] == "inc-old", "a successor minted an incarnation"
        assert "sid-pre-fork" in capsys.readouterr().out
        assert entries                          # epoch check saw a non-empty roster

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
        reg = {"workers": {"sup|inc-old|boot":
                           _record("sid-post-fork", ["sid-pre-fork"])}}
        claim = {"incarnation_id": "inc-old", "state": "released",
                 "released_by_sid": "sid-pre-fork", "released_at": fleet.now_iso()}
        assert fleet._releaser_is_roster_live(claim, live, registry=reg) is expect
        v, _ = fleet.supervisor_claim_decision(
            claim, live, None, caller_sid="sid-new", registry=reg)
        assert (v == "refuse") is expect


class TestTheUnionArmIsBoundedToTheForkSteerWindow:
    """Fix-wave item 3 / break-lens MAJ-2 -- the supervisor's design decision,
    executed and pinned by BOTH fixtures it named.

    `retired_sids` is not a fork-steer artefact only. `cmd_respawn` carries
    `prior_retired + [old_sid]` into a record it MINTS FRESH, and a respawn is a
    genuinely different body. The union arm as first shipped could not tell the
    two apart, so a record whose releaser died and was respawned answered "the
    releaser is roster-live" FOREVER -- B6 refusing every successor on the same
    state, with (measured by the break lens) no in-fleet exit at all: `send`,
    `kill`, `respawn` and `send supervisor` all refused. A self-healing wedge
    became a lockout clearable only by a human editing `supervisor/INCARNATION`.

    The boundary is the record's own `created` against the claim's
    `released_at`: a record minted AFTER the release cannot be the body that
    performed it. A fork-steer mutates the record in place and leaves `created`
    alone; a respawn stamps a new one.

    "Assert on the last verb" throughout: `clean --yes` deleting or not, and
    `sup-boot` consuming the claim or not."""

    def _wedge(self, monkeypatch, created, live="sid-live-now",
               releaser="sid-dead-releaser"):
        _released(released_by=releaser)
        _roster(monkeypatch, live)
        _install(_record(live, [releaser], created=created))

    # --- the fork-steer window still ARMS (ND4a -- the point of Task 2) ------

    def test_a_fork_steered_releaser_still_arms_the_gate(self, wedge_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        self._wedge(monkeypatch, BEFORE_RELEASE)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC
        assert "ghost" in _names(), "clean deleted through a fork-steer wedge"

    def test_a_fork_steered_releaser_still_refuses_a_successor_boot(
            self, wedge_home, monkeypatch):
        _roster(monkeypatch, "sid-live-now", "sid-successor")
        _released(released_by="sid-dead-releaser")
        _install(_record("sid-live-now", ["sid-dead-releaser"], created=BEFORE_RELEASE))
        assert (fleet.main(["sup-boot", "--sid", "sid-successor"])
                == fleet.SUPERVISOR_BOOT_RC["refuse"])
        assert fleet.read_incarnation()["state"] == "released"

    def test_the_tie_arms(self, wedge_home, monkeypatch):
        # `created == released_at` is the same second, and both stamps are
        # second-precision (`now_iso`). It resolves TOWARD the gate: a respawn
        # landing inside the release's own second reads as the fork-steer case
        # rather than silently disarming a live wedge.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        released_at = fleet.now_iso()
        _released(released_by="sid-dead-releaser", released_at=released_at)
        _roster(monkeypatch, "sid-live-now")
        _install(_record("sid-live-now", ["sid-dead-releaser"], created=released_at))
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC

    # --- a respawn chain does NOT ------------------------------------------

    def test_a_respawned_body_does_not_arm_the_gate(self, wedge_home, monkeypatch):
        # The record carries the releaser's sid in `retired_sids` exactly as a
        # fork-steered one does -- `cmd_respawn` puts it there. What differs is
        # that the record itself was MINTED after the release, so the live
        # session is a body that never held or released the claim.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        self._wedge(monkeypatch, AFTER_RELEASE)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert "ghost" not in _names(), "a respawn chain kept the fleet wedged"

    def test_a_respawned_body_leaves_an_in_fleet_exit(self, wedge_home, monkeypatch):
        # THE harm, reversed. With the union arm unbounded, B6 refused every
        # successor forever on this state and nothing inside fleet could clear
        # it. A successor must be able to boot and take the claim.
        _roster(monkeypatch, "sid-live-now", "sid-successor")
        _released(released_by="sid-dead-releaser")
        _install(_record("sid-live-now", ["sid-dead-releaser"], created=AFTER_RELEASE))
        rc = fleet.main(["sup-boot", "--sid", "sid-successor"])
        assert rc == fleet.SUPERVISOR_BOOT_RC["claim"]
        after = fleet.read_incarnation()
        assert after.get("state") != "released", "no successor could ever boot"
        assert after["incarnation_id"] != "inc-old"
        assert after["session_id"] == "sid-successor"

    def test_a_respawn_chain_is_not_protected_from_archive_either(self, wedge_home):
        # The corollary of item 4: gate 3 is re-keyed through the sid union, and
        # that must not quietly grant a respawned body's dead ancestors an
        # archive exemption they never had. Only a LIVE sid protects.
        rec = _record("sid-gone", ["sid-also-gone"], created=AFTER_RELEASE)
        rec["status"] = "dead"
        rec["last_activity"] = "2020-01-01T00:00:00Z"
        fleet.write_tombstone_outcome("w", "sid-gone", "stopped")
        eligible, reason = fleet._archive_eligible(
            "w", rec, [{"sessionId": "sid-unrelated", "status": "idle", "pid": 1}],
            datetime.now(timezone.utc))
        assert (eligible, reason) == (True, "eligible")

    # --- degradation, one direction ----------------------------------------

    @pytest.mark.parametrize("mutate,why", [
        (lambda c, r: c.pop("released_at"), "claim carries no released_at"),
        (lambda c, r: c.update(released_at="not-a-timestamp"), "unparseable released_at"),
        (lambda c, r: r.pop("created"), "record carries no created"),
        (lambda c, r: r.update(created="not-a-timestamp"), "unparseable created"),
    ])
    def test_an_undrawable_boundary_degrades_to_the_bare_comparison(
            self, wedge_home, monkeypatch, mutate, why):
        # Stated once in `_releaser_live_sids` and pinned here: with no boundary
        # to draw, that record drops out of the union and the bare
        # `released_by_sid in live_sids` comparison is all that is left -- which
        # is `main`'s shipped answer, so the union arm can never be worse than
        # the state the fleet already lives with. It resolves the ambiguity
        # toward a failure an operator can still act on (a fail-open B6,
        # refusable at the next boot) rather than one needing a text editor.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        claim = {"incarnation_id": "inc-old", "lineage_id": "lin-L",
                 "claimed_via": "fresh", "released_at": fleet.now_iso(),
                 "released_by_sid": "sid-dead-releaser", "state": "released"}
        rec = _record("sid-live-now", ["sid-dead-releaser"], created=BEFORE_RELEASE)
        mutate(claim, rec)
        fleet.write_incarnation(claim)
        _install(rec)
        _roster(monkeypatch, "sid-live-now")
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0, why
        assert "ghost" not in _names(), why

        # ... and the BARE arm is untouched by any of it: with the releaser's
        # own sid live, the wedge still arms and never reads the registry.
        _roster(monkeypatch, "sid-dead-releaser")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean", nonce=None)
