"""B6 released-claim wedge: the `fleet doctor` row that makes it visible.

THE INCIDENT (2026-07-26): an interactive session took the supervisor claim with
`sup-boot`, was then redefined as the INTERFACE tier -- which "holds no claim by
construction" (three-tier-command.md `:715`) -- ran `sup-release`, and by design
never exited. §6.1 rule 1's B6 precondition refuses to consume a `released`
record whose releaser is still roster-live, and rule 1 has no caller exception,
so NO body could boot: not a successor, not even the releaser. The claim sat
released and unclaimable with an unadopted worker running, and **every other
surface reported a clean, healthy release**. It went unnoticed until a booting
body hit exit 2.

WHAT THIS FILE IS, AND WHAT IT DELIBERATELY IS NOT. It is the surviving half of
branch `fix/b6-interface-release` (`2e824ea`, never merged). That branch's other
half -- `fleet sup-release --interface`, an attestation recorded on the released
record that made rule 1 skip B6 -- was killed **4-0 by council on 2026-07-26**
and is not ported. It is also, since the tombstone slice, OBSOLETE: `cmd_sup_release`
now tombstones the releasing body's registry record, so a supervisor completes
its own stand-down generically and the wedge self-heals for EVERY releaser, not
merely for an attested one. Nothing here writes, reads or tolerates
`released_by_interface`; a record carrying it is treated as the unrecognised
field it is.

The row FAILS rather than NOTEs: the standing lesson from the daemon-wedge check
is that a note which does not move the verdict is invisible.
"""
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with an active GOALS.md (mirrors test_supervisor)."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- e\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    return tmp_path


def _released(released_by="sid-releaser", inc="inc-old", released_at=None):
    return {"incarnation_id": inc, "lineage_id": "lin-x", "claimed_via": "fresh",
            "released_at": released_at or _iso(NOW), "released_by_sid": released_by,
            "state": "released"}


def _hold(sid="sid-me", inc="inc-me", **extra):
    """Write a HELD claim and return the nonce its holder must present."""
    beat = _iso(datetime.now(timezone.utc) - timedelta(seconds=5))
    value = fleet.mint_nonce()
    claim = {"incarnation_id": inc, "session_id": sid, "claimed_at": beat,
             "heartbeat_at": beat, "claimed_via": "fresh",
             "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 4,
             "lineage_id": "lin-20260101T000000Z-aaaa"}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return value


class TestDoctorSeesTheWedge:
    """`fleet doctor` gains the check, and it FAILS -- a note that does not
    move the verdict is invisible."""

    @staticmethod
    def _roster(*live_sids):
        return lambda **kw: (True, [{"sessionId": s, "status": "busy"} for s in live_sids])

    def test_the_check_is_registered_in_cmd_doctor(self, sup_home, monkeypatch, capsys):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-releaser"))
        fleet.write_incarnation(_released(released_by="sid-releaser"))
        rc = fleet.cmd_doctor(SimpleNamespace(),
                              which=lambda *a, **k: None,
                              run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""))
        out = capsys.readouterr().out
        assert "[FAIL] supervisor-wedge:" in out
        assert rc != 0

    def test_the_wedge_is_a_FAIL_naming_the_incarnation_sid_age_and_remedy(
            self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-releaser"))
        fleet.write_incarnation(_released(
            inc="inc-wedged", released_by="sid-releaser",
            released_at=_iso(datetime.now(timezone.utc) - timedelta(hours=3))))
        name, ok, msg = fleet._doctor_check_supervisor_wedge()
        assert name == "supervisor-wedge"
        assert ok is False
        assert "inc-wedged" in msg and "sid-releaser" in msg
        assert "3.0h" in msg                       # how long it has been live
        assert "5.7" in msg                        # escalation, not a hand-edit

    def test_the_remedy_names_no_flag_that_does_not_exist(self, sup_home, monkeypatch):
        """R2, and the reason this row was rewritten rather than cherry-picked.

        The 2026-07-26 version named `fleet sup-release --interface` as its
        remedy. Council killed that flag 4-0 the same day, so the row as written
        would have shipped a remedy that exits non-zero every time -- the exact
        defect `GATE_VERBS_ACCEPTING_NONCE` exists to prevent for `--nonce`, and
        worse here because `doctor` is the 3 a.m. surface and its credibility is
        the asset being spent. What it names now is what actually executes:
        stopping the sessions that are LIVE.
        """
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-releaser"))
        fleet.write_incarnation(_released(released_by="sid-releaser"))
        _, ok, msg = fleet._doctor_check_supervisor_wedge()
        assert ok is False
        assert "--interface" not in msg
        assert "released_by_interface" not in msg
        # The remedy that does execute, and it names the LIVE sid (MAJ-1).
        assert "stop session(s) sid-releaser" in msg
        # The row names NO command-line flag at all -- so there is no flag in it
        # that can rot. (`--` alone is this file's em-dash and is not a flag.)
        assert not re.findall(r"--[a-z][a-z0-9-]+", msg)

    def test_a_roster_gone_releaser_is_not_a_wedge(self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-someone-else"))
        fleet.write_incarnation(_released(released_by="sid-releaser"))
        _, ok, msg = fleet._doctor_check_supervisor_wedge()
        assert ok is True and "claims fresh" in msg

    def test_every_released_case_is_decided_BY_the_shared_predicate(
            self, sup_home, monkeypatch):
        """The anti-theater pin, and it exists because FI-5 caught this exact
        defect in v1 of the check.

        v1 short-circuited cases in its own early returns, which made the
        delegation unreachable for them -- so a mutation that re-implemented the
        rule inline passed the whole suite. Here the decision function is
        stubbed to a verdict it would never actually return for these records:
        if any case still answers from doctor's own logic, it will not follow
        the stub, and this fails.
        """
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-iface"))
        monkeypatch.setattr(fleet, "supervisor_claim_decision",
                            lambda *a, **kw: ("refuse", "STUBBED VERDICT"))
        for record in (_released(released_by="sid-iface"),
                       _released(released_by=None),
                       _released(released_by="sid-gone")):
            fleet.write_incarnation(record)
            _, ok, msg = fleet._doctor_check_supervisor_wedge()
            assert ok is False, f"doctor answered from its own logic for {record}"
            assert "STUBBED VERDICT" in msg

    def test_no_claim_and_a_held_claim_are_both_quiet(self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", self._roster("sid-holder"))
        _, ok, _msg = fleet._doctor_check_supervisor_wedge()
        assert ok is True
        _hold(sid="sid-holder")
        _, ok2, _msg2 = fleet._doctor_check_supervisor_wedge()
        assert ok2 is True

    def test_an_unavailable_roster_does_not_assert_a_verdict(self, sup_home, monkeypatch):
        # Never decide blind, and never double-count an environment fault that
        # already has its own doctor row.
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **kw: (False, "claude executable not found on PATH"))
        fleet.write_incarnation(_released(released_by="sid-releaser"))
        _, ok, msg = fleet._doctor_check_supervisor_wedge()
        assert ok is True
        assert "cannot evaluate B6" in msg

    def test_a_done_roster_entry_does_not_count_as_live(self, sup_home, monkeypatch):
        # Shares `_roster_live_sids` with B6, so the lingering-`state:done`
        # rule (which once blocked successors for hours) applies identically.
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **kw: (
            True, [{"sessionId": "sid-releaser", "status": "idle", "state": "done"}]))
        fleet.write_incarnation(_released(released_by="sid-releaser"))
        _, ok, _msg = fleet._doctor_check_supervisor_wedge()
        assert ok is True


class TestDoctorAndB6CannotDisagree:
    """FI-5. The check does not re-implement the predicate -- it asks
    `supervisor_claim_decision` on the same claim, the same `_roster_live_sids`
    set and the same registry, so a mutation to either arm moves BOTH."""

    CASES = [
        (_released(released_by="sid-r"), ["sid-r"], False),
        (_released(released_by="sid-r"), [], True),
        (_released(released_by=None), ["sid-r"], True),
        (_released(released_by=""), ["sid-r"], True),
    ]

    @pytest.mark.parametrize("claim,live,expect_ok", CASES)
    def test_doctor_ok_matches_the_boot_verdict_on_identical_input(
            self, sup_home, monkeypatch, claim, live, expect_ok):
        entries = [{"sessionId": s, "status": "busy"} for s in live]
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **kw: (True, entries))
        fleet.write_incarnation(claim)
        _, ok, _msg = fleet._doctor_check_supervisor_wedge()
        verdict, _reason = fleet.supervisor_claim_decision(
            claim, fleet._roster_live_sids(entries), None, now=NOW, caller_sid="sid-new",
            registry=fleet._registry_records_or_none())
        assert ok is expect_ok
        # THE invariant: doctor is quiet iff sup-boot would not refuse.
        assert ok is (verdict != "refuse")

    def test_doctor_supplies_the_REGISTRY_so_the_union_arm_cannot_diverge(
            self, sup_home, monkeypatch):
        """The porting defect, pinned.

        The 2026-07-26 version called `supervisor_claim_decision(claim, live,
        None)` with no registry -- correct then, because B6 was a bare
        `released_by_sid in live_sids` string compare. B6 has since been re-keyed
        onto the sid UNION and the tombstone arm (ND4a), both of which need the
        registry records; `cmd_sup_boot` supplies them. A doctor row that omits
        them answers the BARE comparison while `sup-boot` answers the union, so
        the two disagree on identical input -- destroying the one property this
        check exists to provide, and in the silent direction (doctor says PASS
        on a fleet that cannot boot).

        Pinned on the CALL rather than on a constructed union fixture, because
        the invariant is "doctor asks the same question boot asks", not any
        particular answer.
        """
        seen = {}

        def _spy(claim, live_sids, latest, **kw):
            seen.update(kw)
            seen["live_sids"] = live_sids
            return ("claim", "spied")

        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **kw: (True, [{"sessionId": "sid-r", "status": "busy"}]))
        monkeypatch.setattr(fleet, "supervisor_claim_decision", _spy)
        monkeypatch.setattr(fleet, "_registry_records_or_none", lambda: {"sentinel": True})
        fleet.write_incarnation(_released(released_by="sid-r"))
        fleet._doctor_check_supervisor_wedge()
        assert "registry" in seen, "doctor asked B6 without the registry -- union arm blind"
        assert seen["registry"] == {"sentinel": True}
        assert seen["live_sids"] == {"sid-r"}

    def test_the_registry_read_never_quarantines(self, sup_home, monkeypatch):
        """D4: a diagnostic row may READ the registry and must never rename it
        aside. `_registry_records_or_none` is the accessor that makes this legal
        -- it is deliberately NOT `load_registry`, which quarantines on corrupt.
        Pinned by driving a corrupt registry through the row.
        """
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **kw: (True, [{"sessionId": "sid-r", "status": "busy"}]))
        reg = fleet.registry_path()
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text("{ this is not json", encoding="utf-8")
        fleet.write_incarnation(_released(released_by="sid-r"))
        _, ok, _msg = fleet._doctor_check_supervisor_wedge()
        assert ok is False                       # still answers the wedge question
        assert reg.exists(), "doctor quarantined the registry it was invoked to diagnose"
        assert not list(reg.parent.glob("fleet.json.corrupt.*"))


class TestTheRejectedRepairsStayRejected:
    """The council killed four alternatives on evidence. The two reachable as
    CODE MISTAKES rather than as design choices get pins: a future edit that
    reaches for either fails here."""

    def test_no_boot_side_flag_can_accept_a_live_releaser(self):
        # (c). A booter cannot know another body's future behaviour, so no
        # boot-side argv may open B6. Asserted by PARSING, not by grepping the
        # top-level help: subparser options never appear there, so a help-text
        # assertion would pass no matter what `sup-boot` accepts.
        parser = fleet.build_parser()
        for token in ("--accept-live-releaser", "--force-claim", "--ignore-b6"):
            with pytest.raises(SystemExit):
                parser.parse_args(["sup-boot", token])
        assert not any(name.startswith("accept_live") or name in ("force_claim", "ignore_b6")
                       for name in vars(parser.parse_args(["sup-boot"])))

    def test_the_killed_attestation_flag_did_not_come_back(self):
        # (a). `--interface` died 4-0 and is obsolete besides -- the tombstone
        # slice fixes the wedge for every releaser. If it ever returns it must
        # do so through a fresh operator ruling, not by a quiet re-port.
        parser = fleet.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["sup-release", "--interface"])
        assert "interface" not in vars(parser.parse_args(["sup-release"]))

    def test_an_unrecognised_attestation_field_does_not_open_B6(self):
        # Defence in depth: a record left over from the branch (or forged) must
        # not be honoured by code that no longer knows the field.
        claim = _released(released_by="sid-releaser")
        claim["released_by_interface"] = True
        v, _ = fleet.supervisor_claim_decision(
            claim, {"sid-releaser"}, None, now=NOW, caller_sid="sid-new")
        assert v == "refuse"

    def test_the_caller_sid_matching_the_releaser_does_not_open_B6(self):
        # (a+). `--sid` is an operator override and `released_by_sid` is
        # published by a lock-free view, so a rule keyed on
        # `caller_sid == released_by_sid` would authorize on a forgeable value.
        v, _ = fleet.supervisor_claim_decision(
            _released(released_by="sid-releaser"), {"sid-releaser"}, None,
            now=NOW, caller_sid="sid-releaser")
        assert v == "refuse"

    def test_B6_is_not_time_boxed(self):
        # (b). No age of the release opens it.
        for hours in (0, 1, 2, 24, 24 * 30):
            v, _ = fleet.supervisor_claim_decision(
                _released(released_by="sid-releaser",
                          released_at=_iso(NOW - timedelta(hours=hours))),
                {"sid-releaser"}, None, now=NOW, caller_sid="sid-new")
            assert v == "refuse", f"B6 opened on age alone after {hours}h"
