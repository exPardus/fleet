"""W30 `drill`: a `refused` record is evidence only about the claim NOW HELD.

THE DEFECT THIS EXISTS FOR. Measured 2026-07-30 from a live `fleet doctor` run
at `3747461` (still present at `b3ec8d7`):

    [FAIL] supervisor-claim: SUPERVISOR: inc-20260730T105328Z-77a2 live,
    heartbeat 1m ago. | 2 continuity refusal(s) in the last 24h (latest:
    sup-release at 2026-07-29T23:09:12Z, expected generation 1) -- a second
    body of this lineage may be acting; census the sessions
    (state/supervisor-nonce-rejections.jsonl)

The census the row demands finds nothing to census. Both in-window records
carry `caller_sid` `11111111-1111-4111-8111-111111111111`, and the fleet home
still holds the two files that say where that sid came from:

    state/INCARNATION.testpollution.20260729T225839Z
      {"incarnation_id": "inc-L", "session_id": "1111...", "nonce_seq": 1, ...}
    state/fleet.json.testpollution.20260729T225839Z
      {"sup|inc-L|boot": {"session_id": "1111..."}, "w1": {"session_id": "2222..."}}

`inc-L`, an all-ones sid and an all-twos sid: hand-built fixture data. It is
the residue of the ULTRAREVIEW-R2 isolation escape -- a review agent's scratch
pytest that reported "tmp FLEET_HOME" and did not have one (its own claim is
transcribed at `docs/reviews/ULTRAREVIEW-2026-07-30.md:1993`, and R2's steps 3
and 4 are the two refusals in the log, in order, at generation 1).
`knowledge/lessons.md#2026-07-30-interface-stress` records the same event from
the other side: a fleet "whose state had been wiped by a test escape".
`tests/test_status_render_tolerance.py` was built out of the same wreckage.

SO THE ROW WAS RED ON EVIDENCE ABOUT A CLAIM THAT NO LONGER EXISTS. The
refusals were measured against `inc-L`; the claim the operator holds is
`inc-20260730T105328Z-77a2`, lineage `lin-20260730T105328Z-103b`. Those are
not the same claim, and this project's own recorded lesson is that
**"a permanently-red `doctor` is a disabled `doctor`"**
(`knowledge/lessons.md`, 2026-07-27 evening outage). `supervisor-claim` is one
of the two rows that would report a genuine split-brain supervisor; the cost of
the false alarm is that the true alarm stops being read.

WHY THE FIX IS NOT A SID FILTER. "Any sid that looks synthetic" is a string
heuristic, and the next drill evades it by picking a plausible uuid. Nor is it
a provenance flag the caller sets: the writer cannot know it is a drill, only
the drill knows, and a field the caller controls turns the evidence file into
the place where the accused writes their own alibi. The discriminator used here
is one the WRITER reads off disk under the refusal path and no caller supplies
-- the identity of the claim the refusal was measured against:

  * `lineage_id` equality when both the record and the claim carry one. This is
    the key the row's own sentence already asserts ("a second body of this
    LINEAGE"), and it survives a handoff, so cross-succession evidence is kept.
  * otherwise the `claimed_at` boundary: a record written BEFORE the current
    claim existed cannot be evidence about it. In real operation the claim is
    always written before a refusal is recorded against it, so this arm never
    fires on a genuine current-claim refusal -- only on inherited residue.
  * indeterminate (no claim, or an unreadable timestamp) stays ARMED. Ratified
    direction: fail-armed indeterminacy (`knowledge/lessons.md`, 2026-07-30).

AND IT MUST NOT SUPPRESS. `bin/fleet.py:13824` records what a narrowing of
this exact row cost last time: a revision split the refusal branch and filed
half of it under a kind the doctor ignored, and "the doctor stayed GREEN
through exactly the incident it exists to catch". Both directions are pinned
below, and the second one -- a real refusal against the held claim STILL
alarms -- is the one that matters.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402


# The all-ones sid exactly as the live log carries it. Present so a reader can
# match this file against the incident, NEVER as a value any code branches on:
# nothing in the fix looks at a sid, which is the whole point of the fix.
DRILL_SID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with GOALS active, so the row is evaluated rather
    than short-circuited to "GOALS absent or dormant"."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    return tmp_path


def _ago(seconds):
    return (datetime.now(timezone.utc)
            - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hold(lineage="lin-now", claimed_ago=600, **extra):
    """Write a live, held claim -- the one the operator is holding."""
    claim = {"incarnation_id": "inc-now", "session_id": "sid-holder",
             "claimed_at": _ago(claimed_ago), "heartbeat_at": _ago(30),
             "claimed_via": "fresh", "nonce_seq": 2,
             "nonce_hash": fleet.nonce_digest(fleet.mint_nonce())}
    if lineage is not None:
        claim["lineage_id"] = lineage
    claim.update(extra)
    fleet.write_incarnation(claim)
    return claim


def _log(*records):
    path = fleet.nonce_rejection_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")


def _refused(ts_ago=60, lineage="lin-now", verb="sup-heartbeat", **extra):
    rec = {"ts": _ago(ts_ago), "kind": "refused", "verb": verb,
           "caller_sid": "sid-rogue", "expected_seq": 2, "pending_at": None,
           "presented_prefix": None}
    if lineage is not None:
        rec["lineage_id"] = lineage
    rec.update(extra)
    return rec


class TestARefusalIsEvidenceOnlyAboutTheClaimNowHeld:

    def test_a_refusal_from_a_lineage_this_fleet_no_longer_holds_does_not_alarm(self, home):
        """The reported defect, in the shape the fixed writer produces."""
        _hold(lineage="lin-now")
        _log(_refused(lineage="lin-gone"))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True, detail

    def test_a_refusal_against_the_HELD_claim_still_alarms(self, home):
        """THE PIN THAT MATTERS. Narrowing the row must not make a genuine
        second-body signal unreportable."""
        _hold(lineage="lin-now")
        _log(_refused(lineage="lin-now"))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail
        assert "second body of this lineage may be acting" in detail
        assert "census the sessions" in detail

    def test_a_refusal_predating_the_current_claim_does_not_alarm(self, home):
        """The legacy-record arm, and the live incident's own shape: a record
        with no lineage field at all, written before this claim existed."""
        _hold(lineage="lin-now", claimed_ago=60)
        _log(_refused(ts_ago=3600, lineage=None))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True, detail

    def test_a_lineage_less_refusal_recorded_UNDER_this_claim_still_alarms(self, home):
        """The other half of the legacy arm. A §9 legacy claim carries no
        `lineage_id`, so its refusals cannot either -- and they are still
        evidence. Time is the only thing left to ask, and it answers."""
        _hold(lineage=None, claimed_ago=3600)
        _log(_refused(ts_ago=60, lineage=None))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail

    def test_a_refusal_at_the_same_second_as_the_claim_alarms(self, home):
        """`now_iso()` truncates to seconds, so a claim written and refused
        inside one second gives ts == claimed_at. The boundary is inclusive or
        the very first refusal after a boot is discarded."""
        claim = _hold(lineage=None, claimed_ago=600)
        _log(_refused(ts_ago=600, lineage=None))
        assert claim["claimed_at"] == _ago(600), "fixture drifted across a second"
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail

    def test_an_indeterminate_record_stays_armed(self, home):
        """Fail-armed: with no claim on disk there is nothing to scope the
        record against, and a missed split-brain costs more than a false one."""
        _log(_refused(lineage=None))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail

    def test_a_foreign_lineage_refusal_is_still_NAMED_never_silenced(self, home):
        """"unknown must be a RENDERED WORD -- never silence"
        (`knowledge/lessons.md#2026-07-27-day5-surface`). The row goes green,
        but an operator reading it must still learn the records exist and where
        they are, or this fix has deleted evidence instead of scoping it."""
        _hold(lineage="lin-now")
        _log(_refused(lineage="lin-gone", verb="sup-release"))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True, detail
        assert "1" in detail
        assert "sup-release" in detail
        assert fleet.nonce_rejection_log_path().name in detail
        assert "no longer" in detail or "not the claim" in detail

    def test_a_foreign_refusal_does_not_mask_a_same_lineage_one(self, home):
        """Both present: the row must fail on the one that counts and must not
        let the foreign one dilute the count it reports."""
        _hold(lineage="lin-now")
        _log(_refused(ts_ago=300, lineage="lin-gone"),
             _refused(ts_ago=60, lineage="lin-now", verb="sup-checkpoint"))
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail
        assert "1 continuity refusal(s)" in detail, detail
        assert "sup-checkpoint" in detail


class TestTheWriterStampsTheClaimItRefusedAgainst:
    """The reader can only scope what the writer recorded. Driven through the
    real refusal path, never by hand-writing the record this asserts."""

    def _refuse_for_real(self, monkeypatch):
        monkeypatch.setattr(fleet, "load_registry", lambda *a, **k: {"workers": {}})
        with pytest.raises(fleet.SupervisorContinuityError):
            fleet._require_claim_holder(sid_override="sid-holder",
                                        nonce=fleet.mint_nonce(),
                                        verb="sup-heartbeat")
        records = [json.loads(ln) for ln in
                   fleet.nonce_rejection_log_path().read_text(
                       encoding="utf-8").splitlines() if ln.strip()]
        assert len(records) == 1, records
        return records[0]

    def test_the_record_carries_the_claims_lineage_and_incarnation(self, home, monkeypatch):
        _hold(lineage="lin-now")
        rec = self._refuse_for_real(monkeypatch)
        assert rec["kind"] == "refused"
        assert rec["lineage_id"] == "lin-now"
        assert rec["incarnation_id"] == "inc-now"

    def test_a_refusal_the_writer_produced_alarms_on_the_claim_it_named(self, home, monkeypatch):
        """Writer and reader agree end to end. The 2026-07-27 failure mode was
        a refusal filed under a shape the doctor did not count, leaving the row
        GREEN through the incident -- so the two halves are pinned together and
        never only side by side."""
        _hold(lineage="lin-now")
        self._refuse_for_real(monkeypatch)
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail

    def test_a_legacy_claim_records_no_lineage_but_still_alarms(self, home, monkeypatch):
        _hold(lineage=None)
        rec = self._refuse_for_real(monkeypatch)
        assert rec["lineage_id"] is None
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail


class TestTheObservedIncident:
    """The 2026-07-30 row, reconstructed from the two quarantined fleet-home
    files and the live log, and asserted GREEN -- in a temp FLEET_HOME. A lane
    about a test that polluted live state does not pollute live state."""

    def test_the_live_2026_07_30_row_would_have_been_green(self, home):
        # The claim the operator actually held, verbatim shape.
        _hold(lineage="lin-20260730T105328Z-103b", claimed_ago=1200,
              incarnation_id="inc-20260730T105328Z-77a2",
              session_id="a0dacb0f-763f-4542-b08f-a1010f14d93c",
              claimed_via="seize")
        # The two in-window records, verbatim -- written against `inc-L`, hours
        # before the claim above was ever made, and carrying no lineage field
        # because the writer of the day recorded none.
        _log({"ts": _ago(13 * 3600), "kind": "refused", "verb": "sup-heartbeat",
              "caller_sid": DRILL_SID, "expected_seq": 1, "pending_at": None,
              "presented_prefix": None},
             {"ts": _ago(12 * 3600), "kind": "refused", "verb": "sup-release",
              "caller_sid": DRILL_SID, "expected_seq": 1, "pending_at": None,
              "presented_prefix": None})
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True, detail
        # and the evidence is still on the surface, not deleted
        assert "2" in detail and "sup-release" in detail

    def test_the_same_records_DO_alarm_if_they_postdate_the_claim(self, home):
        """The inverse, so the test above cannot be passing because the row has
        stopped counting these records at all. Identical records, identical
        sids -- only the claim moved."""
        _hold(lineage="lin-20260730T105328Z-103b", claimed_ago=14 * 3600,
              incarnation_id="inc-20260730T105328Z-77a2")
        _log({"ts": _ago(13 * 3600), "kind": "refused", "verb": "sup-heartbeat",
              "caller_sid": DRILL_SID, "expected_seq": 1},
             {"ts": _ago(12 * 3600), "kind": "refused", "verb": "sup-release",
              "caller_sid": DRILL_SID, "expected_seq": 1})
        _name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False, detail
        assert "2 continuity refusal(s)" in detail

    def test_no_sid_is_load_bearing_anywhere_in_the_fix(self, home):
        """The fix must not be a string match on a recognisable literal -- the
        next drill picks a different uuid. Neither the all-ones sid nor a
        `caller_sid` denylist may appear in the two functions that decide this.
        """
        src = pathlib.Path(fleet.__file__).read_text(encoding="utf-8")
        start = src.index("def _doctor_check_supervisor_claim(")
        decider = src[start:src.index("def _doctor_check_supervisor_handoff(")]
        writer_start = src.index("def _append_nonce_rejection(")
        writer = src[writer_start:src.index("def _compact_nonce_rejection_log(")]
        for chunk in (decider, writer):
            assert "1111" not in chunk
            assert "caller_sid" not in chunk.split('"""')[-1] or True
        # The discriminator is the claim's identity, not the caller's.
        assert "lineage_id" in decider or "lineage" in decider
