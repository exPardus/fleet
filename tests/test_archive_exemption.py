"""three-tier-command.md §7.2 -- the archive/husk exemption (B1 + B9).

The current live supervisor CLAIM-HOLDER record is protected from BOTH the
archive TTL pass and the daemon-husk sweep, under ANY name (gen-0 "supervisor"
or a successor `sup|<inc>|successor`) -- keyed on the claim, never a static
name. B1: protect the running manager under any name. B9: a husk (roster-gone
AND no longer the claim-holder) is NOT protected -- the sweep still removes it.

Predicate ruling (oracle-confirmed spec-internal-tension resolution): protection
is keyed on HOLDER ALONE, not "holder AND roster-live". The verbatim
"AND roster-live" is descriptive of B1's typical case; requiring it would make
the archive gate a no-op (gate 3 already refuses every roster-live record) and
would fail to close §7.2's stated disaster -- an idle/roster-gone supervisor
that still holds the claim crossing the 24h TTL and being archived. On an
indeterminate identity (claim present, holder sid unreadable) the archive gate
fails TOWARD protection but ONLY for supervisor-shaped names, so a briefly
unreadable INCARNATION cannot freeze all autoclean archiving.
"""
from datetime import datetime, timedelta, timezone

import pytest

import fleet


NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    fleet.save_registry({"workers": {}})
    return tmp_path


def _held(session_id, **extra):
    c = {"incarnation_id": "inc-x", "session_id": session_id, "state": "active",
         "nonce_hash": "deadbeef", "nonce_seq": 3, "heartbeat_at": fleet.now_iso()}
    c.update(extra)
    return c


def _eligible_record(name, sid, *, retired=(), age_hours=25.0):
    """A record that passes EVERY existing `_archive_eligible` gate against an
    empty roster: native, terminal status, roster-gone, has an outcome, TTL
    elapsed. Only the new §7.2 exemption can flip it to ineligible."""
    rec = fleet.new_worker_record(sid, "C:/proj", "task", "accept", dispatch_kind="bg")
    rec["status"] = "idle"
    rec["archived_at"] = None
    rec["retired_sids"] = list(retired)
    rec["last_activity"] = _iso(datetime.now(timezone.utc) - timedelta(hours=age_hours))
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    # Key the outcome by SID (read_outcomes merges name- and sid-keyed files),
    # so a pipe-delimited successor name never becomes an illegal filename.
    fleet.append_outcome(sid, {"ts": _iso(NOW), "session_id": sid, "kind": "result",
                               "result_text": "done"})
    return rec


# --------------------------------------------------------------------------
# _record_is_supervisor_claim_holder -- the record-oriented identity sibling.
# --------------------------------------------------------------------------
class TestRecordIsClaimHolder:
    def test_no_claim(self, home):
        assert fleet._record_is_supervisor_claim_holder({"session_id": "s"}) is False

    def test_released_claim(self, home):
        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released"})
        assert fleet._record_is_supervisor_claim_holder({"session_id": "s"}) is False

    def test_unreadable_holder_sid_is_indeterminate(self, home):
        c = _held("s")
        del c["session_id"]
        fleet.write_incarnation(c)
        assert fleet._record_is_supervisor_claim_holder({"session_id": "s"}) is None

    def test_direct_holder_by_session_id(self, home):
        fleet.write_incarnation(_held("sid-holder"))
        assert fleet._record_is_supervisor_claim_holder(
            {"session_id": "sid-holder", "retired_sids": []}) is True

    def test_holder_via_retired_sid_bridges_fork_steer(self, home):
        # Claim still carries the OLD sid (pull-restamp lag); the record was
        # eagerly restamped and carries the old sid in retired_sids (ND4a).
        fleet.write_incarnation(_held("sid-old"))
        assert fleet._record_is_supervisor_claim_holder(
            {"session_id": "sid-new", "retired_sids": ["sid-old"]}) is True

    def test_unrelated_record_is_not_holder(self, home):
        fleet.write_incarnation(_held("sid-holder"))
        assert fleet._record_is_supervisor_claim_holder(
            {"session_id": "sid-other", "retired_sids": []}) is False


# --------------------------------------------------------------------------
# _archive_eligible -- the first gate (holder-alone, no roster-live conjunct).
# --------------------------------------------------------------------------
class TestArchiveExemption:
    def test_claim_holder_roster_gone_is_protected(self, home):
        # THE stated disaster: an idle/roster-gone supervisor still holding the
        # claim would otherwise cross the 24h TTL and be archived (all base
        # gates pass). The exemption protects it. Empty roster => roster-gone.
        rec = _eligible_record("supervisor", "sid-sup")
        fleet.write_incarnation(_held("sid-sup"))
        ok, reason = fleet._archive_eligible("supervisor", rec, [], NOW)
        assert ok is False
        assert "claim-holder" in reason

    def test_successor_named_claim_holder_protected_under_any_name(self, home):
        # B1: the live manager runs as sup|<inc>|successor after a handoff; the
        # exemption must catch it, not just the static "supervisor" name.
        rec = _eligible_record("sup|inc-9|successor", "sid-succ")
        fleet.write_incarnation(_held("sid-succ"))
        ok, reason = fleet._archive_eligible("sup|inc-9|successor", rec, [], NOW)
        assert ok is False and "claim-holder" in reason

    def test_claim_holder_via_retired_sid_protected(self, home):
        rec = _eligible_record("supervisor", "sid-new", retired=["sid-old"])
        fleet.write_incarnation(_held("sid-old"))
        ok, reason = fleet._archive_eligible("supervisor", rec, [], NOW)
        assert ok is False and "claim-holder" in reason

    def test_non_holder_worker_still_eligible(self, home):
        # An ordinary worker that is not the claim-holder is unaffected -- the
        # gate must not over-protect (regression guard on the base behaviour).
        rec = _eligible_record("w1", "sid-worker")
        fleet.write_incarnation(_held("sid-someone-else"))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (True, "eligible")

    def test_released_away_husk_still_eligible(self, home):
        # B9: a supervisor record whose body no longer holds the claim (released
        # away) is an ordinary husk -- NOT protected.
        rec = _eligible_record("supervisor", "sid-dead-sup")
        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released"})
        assert fleet._archive_eligible("supervisor", rec, [], NOW) == (True, "eligible")

    def test_no_claim_at_all_leaves_workers_eligible(self, home):
        rec = _eligible_record("supervisor", "sid-sup")
        # No INCARNATION written.
        assert fleet._archive_eligible("supervisor", rec, [], NOW) == (True, "eligible")

    def test_indeterminate_identity_protects_only_supervisor_shaped_names(self, home):
        # Claim present but holder sid unreadable => indeterminate. Fail TOWARD
        # protection, but ONLY for supervisor-shaped names, so a briefly
        # unreadable INCARNATION cannot freeze archiving of ordinary workers.
        c = _held("x")
        del c["session_id"]
        fleet.write_incarnation(c)
        sup = _eligible_record("supervisor", "sid-sup")
        wrk = _eligible_record("w1", "sid-worker")
        ok_sup, reason_sup = fleet._archive_eligible("supervisor", sup, [], NOW)
        assert ok_sup is False and "claim-holder" in reason_sup
        assert fleet._archive_eligible("w1", wrk, [], NOW) == (True, "eligible")

    def test_exemption_is_the_first_gate(self, home):
        # A claim-holder that ALSO fails a later gate (e.g. still roster-live)
        # reports the exemption reason, proving it runs first.
        rec = _eligible_record("supervisor", "sid-sup")
        fleet.write_incarnation(_held("sid-sup"))
        entries = [{"sessionId": "sid-sup", "status": "busy", "pid": 1}]
        ok, reason = fleet._archive_eligible("supervisor", rec, entries, NOW)
        assert ok is False and "claim-holder" in reason


# --------------------------------------------------------------------------
# _sweep_husks -- belt-and-braces protection of the claim-holder's sids.
# --------------------------------------------------------------------------
def _sweep_fake_run(roster, calls=None, rm_rc=0):
    import json
    import types
    stdout = json.dumps(roster)

    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        if len(argv) >= 2 and argv[1] == "agents":
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return types.SimpleNamespace(returncode=rm_rc, stdout="", stderr="")
    return fake_run


def _rm_targets(calls):
    return [argv[2] for argv in calls if len(argv) >= 3 and argv[1] == "rm"]


class TestHuskSweepExemption:
    def test_claim_holder_retired_sid_never_swept(self, home):
        # A retired sid of the live claim-holder record is roster-gone and would
        # otherwise be an owned husk. The §7.2 exemption keeps it protected even
        # if the record's own protection machinery ever regressed.
        rec = fleet.new_worker_record("sid-new", "C:/proj", "t", "accept", dispatch_kind="bg")
        rec["retired_sids"] = ["sid-retired"]
        fleet.save_registry({"workers": {"supervisor": rec}})
        fleet.write_incarnation(_held("sid-new"))
        # Make the retired sid look owned via an events line, so the sweep would
        # consider it if not protected.
        fleet.append_event("turn_started", "supervisor", session_id="sid-retired")
        calls = []
        run = _sweep_fake_run([{"sessionId": "sid-retired", "state": "done"}], calls=calls)
        fleet._sweep_husks(dry_run=False, run=run, which=lambda _n: "claude")
        assert "sid-retired" not in _rm_targets(calls)
