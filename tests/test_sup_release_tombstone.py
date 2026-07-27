"""`sup-release` tombstones its OWN registry record, so B6 is false by
construction for the body that just released.

THE PROBLEM THIS SLICE DELETES. A supervisor cannot complete its own
stand-down. `sup-release` produces a `released` claim, but the releasing body is
still in the roster, so B6 (§6.1 rule 1) refuses the next `sup-boot` and the §7
gate stays armed. The shipped succession recipe therefore had a middle step that
lives OUTSIDE the fleet -- *"the interface stops the retired body so its sid
leaves the roster"* -- and every unproven handoff this project has had died at a
step that lives outside the fleet.

WHY A TOMBSTONE AND NOT AN ATTESTATION. A retired branch
(`fix/b6-interface-release` @ `2e824ea`, RULED RETIRED 2026-07-27) solved this
with a `sup-release --interface` flag by which the releasing body SWORE it was
the interface tier. Ratified doctrine (claim-nonce §17, Altai, 2026-07-27)
forbids exactly that: *"inference may select the SUBJECT of a measurement, but
may not supply the GROUNDS of a refusal."* An attestation flag can only ever be
ADDED by an adversary and never withheld, so its presence proves nothing.

A tombstone is a different KIND of thing and that is the whole argument. It is
not something the caller SAYS about itself; it is a state change fleet PERFORMS,
under the lock, on the record fleet itself resolved from the caller's already-
proven continuity. It removes the condition B6 tests instead of authorising an
exception to it, and `_releaser_live_sids` needs to trust nothing the caller
said. `test_no_flag_by_which_the_caller_declares_anything_about_itself` is the
pin that keeps the retired road closed.

ONE SPELLING OF "THIS BODY IS GONE". §10.4's kill/respawn choreography already
had one: `_cmd_kill_native` flips the registry record's `status` to `"dead"`,
and `_record_is_live` is the predicate that reads it (`archived_at` set OR
`status == "dead"`). This slice reuses BOTH and mints neither a new field nor a
new predicate -- see `TestTheTombstoneIsTheSpellingKillAlreadyUses`.

THE CRASH WINDOW. Release and tombstone are two writes. The order is
`write_incarnation(released)` THEN the tombstone, and it is chosen so a process
death between them fails toward REFUSAL: the surviving state is `released` +
live untombstoned releaser, which is exactly today's B6 refusal and self-heals
when the body exits the roster. The reverse order would leave a HELD claim owned
by a record fleet has already retired -- the frozen-claim state that needs a
human with a text editor. `TestTheCrashWindow` pins the direction.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import fleet


RELEASER = "sid-releaser"
SUCCESSOR = "sid-successor"
THIRD = "sid-third-body"
BODY = "sup|inc-old|boot"

# A record the releasing body already HAD is necessarily older than the release
# it performed -- the same boundary `tests/test_b6_sid_union.py` states.
BEFORE_RELEASE = "2020-01-01T00:00:00Z"


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME: registry, supervisor state, rendered settings."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


@pytest.fixture(autouse=True)
def _never_dispatch(monkeypatch):
    """Nothing in this file may reach a real claude session -- the twin fixture
    of `tests/test_b6_sid_union.py`'s."""
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
        "a release/boot test reached dispatch_bg -- that dispatches a REAL session"))


def _record(current, retired=(), created=BEFORE_RELEASE, **extra):
    rec = fleet.new_worker_record(current, "C:/proj", "t", "acceptEdits",
                                  dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    rec["created"] = created
    rec.update(extra)
    return rec


def _install(rec, name=BODY):
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _registry(*records):
    """A registry dict for the PURE predicate -- `(name, record)` pairs."""
    return {"workers": dict(records)}


def _released(released_by=RELEASER, **extra):
    claim = {"incarnation_id": "inc-old", "lineage_id": "lin-L",
             "claimed_via": "fresh", "released_at": fleet.now_iso(),
             "released_by_sid": released_by, "state": "released"}
    claim.update(extra)
    return claim


def _roster(monkeypatch, *live_sids, ok=True):
    entries = [{"sessionId": s, "status": "idle", "pid": 4242} for s in live_sids]
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (ok, entries if ok else "roster unavailable"))
    return entries


def _hold(sid=RELEASER, inc="inc-old"):
    """Write a HELD claim for `sid` and return its nonce plaintext."""
    beat = fleet.now_iso()
    value = fleet.mint_nonce()
    fleet.write_incarnation(
        {"incarnation_id": inc, "session_id": sid, "claimed_at": beat,
         "heartbeat_at": beat, "claimed_via": "fresh",
         "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 4,
         "lineage_id": "lin-20260101T000000Z-aaaa"})
    return value


def _release(sid=RELEASER, nonce=None, reason=None):
    return fleet.cmd_sup_release(
        SimpleNamespace(sid=sid, nonce=nonce, reason=reason))


def _status(name=BODY):
    return fleet.load_registry()["workers"][name].get("status")


def _untouched(name=BODY):
    """True iff this record is still whatever a fresh spawn made it -- read off
    `new_worker_record` rather than hard-coded, so the pin says "not
    tombstoned" and not "equal to the status literal of the day"."""
    fresh = fleet.new_worker_record("sid-probe", "C:/proj", "t", "acceptEdits",
                                    dispatch_kind="bg")
    rec = fleet.load_registry()["workers"][name]
    return rec.get("status") == fresh.get("status") and fleet._record_is_live(rec)


# --- 1. THE READ SIDE: the one predicate both consumers key on -------------

class TestATombstonedReleaserIsNotALiveReleaser:
    """`_releaser_live_sids` is THE comparison B6 (§6.1 rule 1) and the §7 gate
    (`_wedged_release_gate`) both decide through, held as one function so
    "wedged" cannot come to mean two things. The tombstone arm goes HERE and
    nowhere else, for that reason."""

    def test_a_tombstoned_releaser_is_not_live_though_its_session_is_in_the_roster(self):
        # The whole slice in one assertion. The roster still lists the sid --
        # `claude stop` was never run and the session has not exited -- but the
        # record fleet keeps for that body says the body is gone.
        claim = _released()
        reg = _registry((BODY, _record(RELEASER, status="dead")))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == set()
        assert fleet._releaser_is_roster_live(claim, {RELEASER}, registry=reg) is False

    def test_an_untombstoned_live_releaser_still_answers_live(self):
        # THE GUARD IS NOT REMOVED. This is the case the manual step existed
        # for and it must behave exactly as it does today.
        claim = _released()
        reg = _registry((BODY, _record(RELEASER)))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == {RELEASER}

    def test_a_releaser_with_no_registry_record_at_all_still_answers_live(self):
        # An old record, a release by a path that does not tombstone, a body
        # whose record was swept. Nothing was tombstoned, so nothing disarms.
        claim = _released()
        reg = _registry((BODY, _record("sid-someone-else")))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == {RELEASER}

    def test_an_unreadable_registry_leaves_the_guard_standing(self):
        # `registry=None` is the abstention every caller of this predicate can
        # hand it. A tombstone it cannot see must never be ASSUMED, so the
        # bare comparison stands and the answer is a refusal.
        claim = _released()
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=None) == {RELEASER}

    def test_a_registry_whose_workers_key_is_the_wrong_shape_leaves_the_guard_standing(self):
        claim = _released()
        for junk in ({"workers": []}, {"workers": "nope"}, {}):
            assert fleet._releaser_live_sids(claim, {RELEASER}, registry=junk) == {RELEASER}

    def test_a_tombstone_on_a_FOREIGN_record_does_not_disarm(self):
        # THE OWN-RECORD-ONLY PIN, read side. Some other body's record being
        # dead says nothing about this releaser, and a predicate that scanned
        # for "a dead record somewhere" would disarm B6 fleet-wide the first
        # time any worker was killed.
        claim = _released()
        reg = _registry((BODY, _record(RELEASER)),
                        ("other", _record("sid-other", status="dead")))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == {RELEASER}

    def test_a_drifted_registry_with_one_live_carrier_resolves_toward_the_gate(self):
        # Two records carrying one sid violates the uniqueness invariant. The
        # union arm's own rule for that state is "resolve TOWARD the gate", and
        # the tombstone arm inherits it: one live carrier keeps B6 armed.
        claim = _released()
        reg = _registry((BODY, _record(RELEASER, status="dead")),
                        ("twin", _record(RELEASER)))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == {RELEASER}

    def test_archived_at_is_the_other_tombstone_spelling_and_also_disarms(self):
        # `_record_is_live` reads BOTH `archived_at` and `status == "dead"`.
        # Keying the disarm on that predicate rather than on one field is what
        # keeps this from being a third spelling of "this body is gone".
        claim = _released()
        reg = _registry((BODY, _record(RELEASER, archived_at=fleet.now_iso())))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == set()

    def test_dead_suspected_is_NOT_a_tombstone(self):
        # Suspicion is not proof. `dead_suspected` is fleet guessing from a
        # missing roster entry; a tombstone is fleet recording something it did.
        claim = _released()
        reg = _registry((BODY, _record(RELEASER, status="dead_suspected")))
        assert fleet._releaser_live_sids(claim, {RELEASER}, registry=reg) == {RELEASER}

    def test_the_tombstone_arm_is_keyed_on_the_sid_UNION(self):
        # A fork-steered releaser: the record was restamped in place, so the
        # sid INCARNATION was written with now lives in `retired_sids`. The
        # tombstone must still be found, or the one case ND4a exists for is the
        # one case that keeps needing the manual step.
        claim = _released(released_by="sid-pre-fork")
        reg = _registry((BODY, _record("sid-post-fork", ["sid-pre-fork"],
                                       status="dead")))
        assert fleet._releaser_live_sids(
            claim, {"sid-post-fork"}, registry=reg) == set()

    def test_a_held_claim_is_untouched_by_the_tombstone_arm(self):
        # The predicate returns early on anything that is not `released`; a
        # tombstoned record must not make a HELD claim look releasable.
        held = {"incarnation_id": "inc-h", "session_id": RELEASER,
                "heartbeat_at": fleet.now_iso(), "state": "held"}
        reg = _registry((BODY, _record(RELEASER, status="dead")))
        assert fleet._releaser_live_sids(held, {RELEASER}, registry=reg) == set()
        v, _ = fleet.supervisor_claim_decision(
            held, {RELEASER}, None, caller_sid=SUCCESSOR, registry=reg)
        assert v == "refuse", "a tombstone let a successor boot past a HELD claim"


# --- 2. B6 AND THE GATE, THE TWO CONSUMERS ---------------------------------

class TestB6ClaimsAfterATombstoningRelease:

    def test_b6_claims_when_the_releaser_is_tombstoned(self):
        claim = _released()
        reg = _registry((BODY, _record(RELEASER, status="dead")))
        v, reason = fleet.supervisor_claim_decision(
            claim, {RELEASER}, None, caller_sid=SUCCESSOR, registry=reg)
        assert v == "claim"
        assert "released cleanly" in reason

    def test_b6_still_refuses_an_untombstoned_live_releaser(self):
        claim = _released()
        reg = _registry((BODY, _record(RELEASER)))
        v, reason = fleet.supervisor_claim_decision(
            claim, {RELEASER}, None, caller_sid=SUCCESSOR, registry=reg)
        assert v == "refuse"
        assert RELEASER in reason


class TestTheGateDisarmsOnTheSamePredicate:
    """§7's released-claim arm and B6 must agree, because they are the same
    predicate. OPERATOR-GATES 2026-07-27 recorded the missing in-fleet disarm
    for this arm as OWED work: *"an in-fleet disarm path is owed"*. This is it."""

    def _wedge(self, monkeypatch, tombstoned):
        _roster(monkeypatch, RELEASER)
        fleet.write_incarnation(_released())
        _install(_record(RELEASER, status="dead" if tombstoned else "idle"))
        # A second, plainly-live record so `clean` has something to delete when
        # the gate is disarmed -- the probe that tells the two cases apart.
        _install(_record("sid-ghost", created=BEFORE_RELEASE), name="ghost")

    def test_the_gate_stays_armed_for_an_untombstoned_live_releaser(
            self, sup_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        self._wedge(monkeypatch, tombstoned=False)
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC
        assert "ghost" in fleet.load_registry()["workers"]

    def test_the_gate_disarms_once_the_releaser_is_tombstoned(
            self, sup_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        self._wedge(monkeypatch, tombstoned=True)
        assert fleet.main(["clean", "--yes"]) == 0


# --- 3. THE WRITE SIDE: only its own record, and only its own --------------

class TestReleaseTombstonesItsOwnRecord:

    def test_release_tombstones_the_releasing_bodys_own_record(self, sup_home, capsys):
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        assert _status() == "dead"
        assert fleet._record_is_live(fleet.load_registry()["workers"][BODY]) is False

    def test_release_tombstones_ONLY_its_own_record(self, sup_home, capsys):
        # THE SAFETY PROPERTY, and it is the one the `retired_sids` invariant
        # rests on elsewhere: no foreign sid ever enters another record's
        # state. Every other record must survive the release BYTE-IDENTICAL.
        _install(_record(RELEASER))
        _install(_record("sid-worker-a"), name="alpha")
        _install(_record("sid-worker-b"), name="beta")
        before = {n: dict(r) for n, r in fleet.load_registry()["workers"].items()
                  if n != BODY}
        value = _hold()
        assert _release(nonce=value) == 0
        after = {n: r for n, r in fleet.load_registry()["workers"].items()
                 if n != BODY}
        assert after == before, "a release reached a record that was not its own"

    def test_the_record_is_resolved_through_the_sid_UNION(self, sup_home, capsys):
        # A fork-steered releaser proves continuity under its POST-fork sid
        # while its record carries the pre-fork one in `retired_sids`. Resolving
        # by the bare `session_id` would tombstone nothing here.
        _install(_record("sid-pre-fork", ["sid-post-fork"]))
        value = _hold(sid="sid-post-fork")
        assert _release(sid="sid-post-fork", nonce=value) == 0
        assert _status() == "dead"

    def test_a_release_with_no_registry_record_still_succeeds(self, sup_home, capsys):
        # The interface tier and a human shell are UNRESOLVED here, and that is
        # not an error -- it is what "I am not a fleet-launched body" looks
        # like. Such a body is not in the roster either, so nothing is wedged.
        value = _hold()
        assert _release(nonce=value) == 0
        assert fleet.read_incarnation()["state"] == "released"
        assert fleet.load_registry()["workers"] == {}, "a release invented a record"

    def test_an_AMBIGUOUS_identity_tombstones_nothing(self, sup_home, capsys):
        # Two records carrying the caller's sid is itself a leak signature. The
        # first match is NOT silently taken -- guessing here would tombstone
        # some other body's record, which is the one thing this must never do.
        _install(_record(RELEASER))
        _install(_record(RELEASER), name="twin")
        value = _hold()
        assert _release(nonce=value) == 0
        assert _untouched()
        assert _untouched("twin")
        assert "ambiguous" in capsys.readouterr().err.lower()

    def test_a_corrupt_registry_does_not_fail_the_release_and_says_so(
            self, sup_home, capsys):
        # The release is already committed by the time the tombstone runs, so a
        # registry that cannot be loaded must not make `sup-release` report
        # failure. It must say what did NOT happen -- the consequence is that
        # the manual step is back for this one release.
        value = _hold()
        fleet.registry_path().write_text("{{{not json", encoding="utf-8")
        assert _release(nonce=value) == 0
        assert fleet.read_incarnation()["state"] == "released"
        assert "tombston" in capsys.readouterr().err.lower()

    def test_an_already_tombstoned_record_is_left_alone(self, sup_home, capsys):
        """A frozen tombstone is never re-stamped: NO registry write and NO
        event, not merely "the fields end up the same".

        This assertion is the second version. The first compared `archived_at`
        before and after, and injecting the defect (delete the
        `if not _record_is_live(rec): return name` guard) left the suite GREEN --
        of course it did: re-stamping `status = "dead"` onto a record that is
        already dead changes no field. The harm is the SPURIOUS WRITE and the
        spurious `status_changed: dead -> dead` event appended to an append-only
        log about an archived record, which is the same "never recompute/persist/
        event a frozen tombstone" rule the sweep paths already carry. So the
        assertion is about what was DONE, not about what the fields say."""
        stamp = fleet.now_iso()
        _install(_record(RELEASER, status="dead", archived_at=stamp))
        value = _hold()
        before_bytes = fleet.registry_path().read_bytes()
        before_events = len(_events())
        assert _release(nonce=value) == 0
        assert fleet.registry_path().read_bytes() == before_bytes, \
            "the release rewrote a registry it had nothing to change"
        assert [e for e in _events()[before_events:]
                if e.get("kind") == "status_changed"] == [], \
            "the release appended a dead -> dead event to a frozen tombstone"
        assert fleet.load_registry()["workers"][BODY]["archived_at"] == stamp

    def test_a_refused_release_tombstones_nothing(self, sup_home, capsys):
        # No continuity proof -> no release -> no tombstone. A verb that failed
        # before its state change must rotate nothing and retire nothing.
        _install(_record(RELEASER))
        _hold()
        with pytest.raises(fleet.FleetCliError):
            _release(nonce="not-the-nonce")
        assert _untouched()
        assert fleet.read_incarnation().get("state") is None

    def test_the_enumerated_post_release_key_set_is_unchanged(self, sup_home, capsys):
        # §6.3 enumerates the released claim's keys as a LITERAL. The tombstone
        # is a REGISTRY fact; it must not leak a field into the claim, or a
        # released record stops being distinguishable from a legacy one (§9).
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value, reason="standing down") == 0
        assert set(fleet.read_incarnation()) == {
            "incarnation_id", "lineage_id", "claimed_via", "released_at",
            "released_by_sid", "reason", "state"}

    def test_the_status_change_is_recorded_as_an_event(self, sup_home, capsys):
        # A registry status flip with no event is an audit hole. `status_changed`
        # is the EXISTING spelling every other status writer uses -- no new
        # event kind is minted for this.
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        kinds = [e for e in _events() if e.get("name") == BODY]
        assert any(e["kind"] == "status_changed" and e.get("new") == "dead"
                   for e in kinds), kinds


def _events():
    path = fleet.FLEET_HOME / "state" / "events.jsonl"
    if not path.exists():
        return []
    import json
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


# --- 4. THE END-TO-END SEQUENCE the manual step used to be inside ----------

class TestSuccessionNeedsNoManualStep:
    """A holds a claim -> A releases -> a fresh body B boots -> B CLAIMS. Driven
    through `fleet.main` with A's session STILL IN THE ROSTER for the whole
    sequence, because the manual step this slice deletes was exactly "make A
    leave the roster first"."""

    def test_a_releases_and_b_boots_cleanly_with_a_still_in_the_roster(
            self, sup_home, monkeypatch, capsys):
        _install(_record(RELEASER))
        value = _hold()
        # A releases. Note what is NOT here: no `claude stop`, no operator, no
        # attestation flag.
        assert fleet.main(["sup-release", "--sid", RELEASER,
                           "--nonce", value, "--reason", "standing down"]) == 0
        # A is still live in the roster -- it has been told to exit and has not
        # yet. This is the state that used to refuse.
        _roster(monkeypatch, RELEASER, SUCCESSOR)
        assert fleet.main(["sup-boot", "--sid", SUCCESSOR]) == \
            fleet.SUPERVISOR_BOOT_RC["claim"]
        claim = fleet.read_incarnation()
        assert claim.get("state") != "released"
        assert claim["session_id"] == SUCCESSOR
        assert claim["incarnation_id"] != "inc-old"

    def test_the_same_sequence_REFUSES_when_the_release_did_not_tombstone(
            self, sup_home, monkeypatch, capsys):
        # The control. Identical state except the record was never tombstoned,
        # which is what a release by a path that does not tombstone leaves --
        # and it must still refuse exactly as it does today.
        _install(_record(RELEASER))
        fleet.write_incarnation(_released())
        _roster(monkeypatch, RELEASER, SUCCESSOR)
        assert fleet.main(["sup-boot", "--sid", SUCCESSOR]) == \
            fleet.SUPERVISOR_BOOT_RC["refuse"]
        assert fleet.read_incarnation()["state"] == "released"


# --- 5. THE CRASH WINDOW ---------------------------------------------------

class TestTheCrashWindow:
    """Release and tombstone are two state changes. A half-released claim must
    fail toward REFUSAL -- the abstaining state -- never toward a free claim."""

    def test_the_release_commits_BEFORE_the_tombstone(self, sup_home, monkeypatch,
                                                      capsys):
        # The ordering pin. A death inside the tombstone must leave the release
        # already durable, because the reverse order leaves a HELD claim owned
        # by a record fleet has retired -- recoverable only by hand.
        _install(_record(RELEASER))
        value = _hold()

        def _die(*a, **k):
            raise KeyboardInterrupt("process died between the two writes")

        monkeypatch.setattr(fleet, "_tombstone_releasing_body", _die)
        with pytest.raises(KeyboardInterrupt):
            _release(nonce=value)
        assert fleet.read_incarnation()["state"] == "released"
        assert _untouched(), "the tombstone landed before the release"

    def test_the_surviving_half_released_state_refuses_a_successor(
            self, sup_home, monkeypatch, capsys):
        # What the crash actually leaves, driven end to end: released claim,
        # live untombstoned releaser. B6 refuses, which is the safe direction,
        # and the wedge self-heals when A finally exits the roster.
        _install(_record(RELEASER))
        value = _hold()

        def _die(*a, **k):
            raise KeyboardInterrupt("crash")

        monkeypatch.setattr(fleet, "_tombstone_releasing_body", _die)
        with pytest.raises(KeyboardInterrupt):
            _release(nonce=value)
        _roster(monkeypatch, RELEASER, SUCCESSOR)
        assert fleet.main(["sup-boot", "--sid", SUCCESSOR]) == \
            fleet.SUPERVISOR_BOOT_RC["refuse"]
        # ...and the self-heal is still there: A leaves the roster, B claims.
        _roster(monkeypatch, SUCCESSOR)
        assert fleet.main(["sup-boot", "--sid", SUCCESSOR]) == \
            fleet.SUPERVISOR_BOOT_RC["claim"]

    def test_the_crashed_release_never_reads_as_a_free_claim(self, sup_home,
                                                             monkeypatch, capsys):
        # Stated as the property rather than as a verdict: whatever the crash
        # leaves, it is never the shape that hands a second body the claim
        # while the first is still live.
        _install(_record(RELEASER))
        claim = _released()
        fleet.write_incarnation(claim)
        reg = fleet.load_registry()
        assert fleet._releaser_is_roster_live(claim, {RELEASER}, registry=reg) is True


# --- 6. ONE SPELLING, AND NO ATTESTATION ----------------------------------

class TestTheTombstoneIsTheSpellingKillAlreadyUses:
    """§10.4 landed the mechanism; this slice reuses it. Two spellings of one
    state is how this repo grows the defects it later names."""

    def test_the_release_tombstone_and_the_kill_tombstone_are_one_predicate(
            self, sup_home, capsys):
        # Same field, same value, same reader. Asserted through
        # `_record_is_live` -- the predicate -- rather than by comparing source
        # text, so a future rename of the field cannot pass this vacuously
        # while the two sites drift.
        killed = _record("sid-killed")
        killed["status"] = "dead"              # exactly `_cmd_kill_native`'s write
        _install(killed, name="killed-one")
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        workers = fleet.load_registry()["workers"]
        assert workers[BODY]["status"] == workers["killed-one"]["status"] == "dead"
        assert fleet._record_is_live(workers[BODY]) is False
        assert fleet._record_is_live(workers["killed-one"]) is False

    def test_the_release_writes_no_stop_outcome_it_did_not_perform(
            self, sup_home, capsys):
        # `write_tombstone_outcome` means "fleet ENDED this session"
        # (killed/interrupted/stopped). `sup-release` runs no `claude stop`, so
        # writing one would be a fabricated receipt for a stop that never
        # happened -- the defect class this repo has shipped four times.
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        path = fleet.outcome_path(BODY)
        assert not path.exists() or "stopped" not in path.read_text(encoding="utf-8")


class TestTheRetiredAttestationRoadStaysClosed:

    def test_no_flag_by_which_the_caller_declares_anything_about_itself(self):
        # `fix/b6-interface-release`'s `--interface` was ruled dead 4-0: an
        # attestation is a caller supplying the GROUNDS of its own non-refusal,
        # and it can only ever be ADDED by an adversary. If this ever needs a
        # flag again, the design has drifted back onto the retired road.
        parser = fleet.build_parser()
        sub = [a for a in parser._subparsers._group_actions
               if hasattr(a, "choices")][0].choices["sup-release"]
        flags = {opt for action in sub._actions for opt in action.option_strings}
        assert flags == {"-h", "--help", "--reason", "--nonce", "--sid"}, flags

    def test_the_disarm_reads_no_field_the_caller_could_have_supplied(self):
        # The doctrinal shape, as a test. A released claim carrying a hostile
        # `interface`/`tombstoned` key of its own must not disarm B6: the ONLY
        # thing that disarms is a registry record fleet itself retired.
        for forged in ("interface", "tombstoned", "tombstone", "released_cleanly"):
            claim = _released(**{forged: True})
            reg = _registry((BODY, _record(RELEASER)))
            assert fleet._releaser_live_sids(
                claim, {RELEASER}, registry=reg) == {RELEASER}, forged


# --- 7. THE CONSEQUENCE OF REUSING A STICKY STATUS -------------------------

class TestWhatElseTheTombstoneChanges:
    """Found while auditing the reuse rather than by driving the feature, and
    pinned so it is a decision instead of a surprise. `"dead"` is in
    `_NATIVE_STICKY`, so `recompute_worker_native` passes it through unchanged
    and `fleet clean` -- which deletes on the RECOMPUTED verdict -- becomes
    willing to sweep the retired body's record even while its session lingers.

    That is the right answer and it is not new: it is exactly the state a
    `fleet kill` leaves, and it is what the manual step produced anyway once the
    operator stopped the body. Recorded because the alternative reading -- "the
    release quietly made a live session's evidence deletable" -- is a fair thing
    for the next reader to worry about, and the two things it must NOT cost are
    checked below."""

    def test_the_retired_body_becomes_sweepable_by_clean(self, sup_home,
                                                         monkeypatch, capsys):
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        # The session is STILL live in the roster -- this is the whole point.
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        assert BODY not in fleet.load_registry()["workers"]

    def test_it_does_not_cost_the_supervisor_journal(self, sup_home, monkeypatch,
                                                     capsys):
        # The ratified journal lives on a fixed supervisor-scoped path belonging
        # to no worker record, so `fleet clean` cannot reach it (§4.13(g)). That
        # is what makes the sweep above cheap; if it ever stopped being true,
        # tombstoning on release would be destroying the campaign's record.
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value, reason="standing down") == 0
        journal = fleet.supervisor_journal_path()
        assert "RELEASED" in journal.read_text(encoding="utf-8")
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        assert "RELEASED" in journal.read_text(encoding="utf-8")

    def test_it_does_not_cost_the_operator_the_stop_lever(self, sup_home, capsys):
        # `fleet kill <body>` must still reach a tombstoned record, or the
        # operator loses the ability to stop a lingering released session
        # through fleet. `kill` refuses ARCHIVED records, not dead ones -- which
        # is one more reason the tombstone is `status`, never `archived_at`.
        _install(_record(RELEASER))
        value = _hold()
        assert _release(nonce=value) == 0
        rec = fleet.load_registry()["workers"][BODY]
        assert rec.get("archived_at") is None
        stopped = []
        fleet.cmd_kill(SimpleNamespace(name=BODY, yes=True, nonce=None),
                       run=lambda *a, **k: stopped.append(a) or SimpleNamespace(
                           returncode=0, stdout="", stderr=""),
                       which=lambda _x: "claude")
        assert stopped, "kill could not reach the tombstoned body"
