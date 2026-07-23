"""M-A supervisor identity tests (spec §4): state files, journal format,
claim/seizure/handshake state machine, boot ritual, handoff, nag."""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with an active GOALS.md and seeded journal."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    # Rendered worker-settings instance: the successor dispatch carries it as
    # --settings and refuses when it is absent (SPEC §6, second dispatch path).
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    return tmp_path


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class TestStateFiles:
    def test_incarnation_roundtrip_atomic(self, sup_home):
        claim = {"incarnation_id": "inc-20260714T110000Z-abcd", "session_id": "sid-1",
                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW), "claimed_via": "fresh"}
        fleet.write_incarnation(claim)
        assert fleet.read_incarnation() == claim
        # atomic: no .tmp litter left behind
        assert not list((sup_home / "supervisor").glob("*.tmp"))

    def test_read_incarnation_missing_and_corrupt(self, sup_home):
        assert fleet.read_incarnation() is None
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        assert fleet.read_incarnation() is None

    def test_handshake_roundtrip(self, sup_home):
        fleet.write_handshake("inc-x", "sid-9")
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-x" and hs["session_id"] == "sid-9"
        assert "written_at" in hs

    def test_mint_incarnation_id_format_and_uniqueness(self, sup_home):
        a, b = fleet.mint_incarnation_id(), fleet.mint_incarnation_id()
        assert a.startswith("inc-") and a != b
        import re
        assert re.fullmatch(r"inc-\d{8}T\d{6}Z-[0-9a-f]{4}", a)


class TestJournal:
    def test_append_creates_seed_and_parses_back(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "fresh claim")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "line one\nline two")
        text = fleet.supervisor_journal_path().read_text(encoding="utf-8")
        assert text.startswith("# Supervisor Journal")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["body"].strip() == "line one\nline two"
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT"

    def test_append_rejects_unknown_kind(self, sup_home):
        with pytest.raises(ValueError):
            fleet.supervisor_journal_append("SABOTAGE", "inc-a", "sid-1", "x")

    def test_parser_tolerates_prose_between_entries(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        with open(fleet.supervisor_journal_path(), "a", encoding="utf-8") as f:
            f.write("\nstray human note, not an entry header\n")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "next")
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["BOOT", "CHECKPOINT"]

    def test_empty_journal(self, sup_home):
        assert fleet.supervisor_journal_entries() == []
        assert fleet.supervisor_journal_latest() is None

    def test_header_injection_in_body_is_escaped(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        evil_line = "## 2099-01-01T00:00:00Z CHECKPOINT inc=inc-evil sid=sid-evil"
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1",
                                        f"legit body\n{evil_line}\nmore legit body")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        assert evil_line in entries[1]["body"]
        latest = fleet.supervisor_journal_latest()
        assert latest["inc"] != "inc-evil"
        assert latest["inc"] == "inc-a"


def _claim(inc="inc-old", sid="sid-old", beat=None):
    beat = beat or NOW - timedelta(seconds=60)
    return {"incarnation_id": inc, "session_id": sid,
            "claimed_at": _iso(NOW - timedelta(hours=2)),
            "heartbeat_at": _iso(beat), "claimed_via": "fresh"}


class TestNoncePrimitives:
    """claim-nonce §5.2: the three stdlib primitives the continuity proof is
    built from, and the one comparison SHAPE the spec names as the thing to
    avoid ("comparing a digest object to a hex string").

    These are deliberately tested apart from the claim machinery: every later
    rule in §5.3 is a composition of `nonce_digest` + `nonce_matches`, so a
    silent weakening here (a truncated digest, an `==` that short-circuits, a
    stored value that is bytes and compares False against everything) would
    show up as a subtle acceptance/refusal bug three layers away."""

    def test_mint_nonce_is_urlsafe_and_never_repeats(self):
        values = {fleet.mint_nonce() for _ in range(50)}
        assert len(values) == 50, "mint_nonce must not repeat"
        for v in values:
            # secrets.token_urlsafe(32) -> 43 chars of [A-Za-z0-9_-].
            assert len(v) >= 43
            assert re.fullmatch(r"[A-Za-z0-9_-]+", v), v

    def test_mint_nonce_is_not_derived_from_anything_the_claim_publishes(self):
        # A generation minted twice in the same second, for the same claim,
        # must still differ: the value is entropy, never a function of the
        # incarnation id / sid / clock (all three are published by views).
        assert fleet.mint_nonce() != fleet.mint_nonce()

    def test_nonce_digest_is_sha256_hex_of_utf8(self):
        import hashlib
        v = "a-nonce-with-é-in-it"
        assert fleet.nonce_digest(v) == hashlib.sha256(v.encode("utf-8")).hexdigest()
        assert len(fleet.nonce_digest(v)) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", fleet.nonce_digest(v))

    def test_nonce_matches_accepts_the_value_behind_the_stored_digest(self):
        v = fleet.mint_nonce()
        assert fleet.nonce_matches(v, fleet.nonce_digest(v)) is True

    def test_nonce_matches_refuses_a_different_value(self):
        v, other = fleet.mint_nonce(), fleet.mint_nonce()
        assert fleet.nonce_matches(other, fleet.nonce_digest(v)) is False

    @pytest.mark.parametrize("presented", [None, "", 0, b"bytes"])
    def test_nonce_matches_refuses_a_missing_or_non_string_presentation(self, presented):
        v = fleet.mint_nonce()
        assert fleet.nonce_matches(presented, fleet.nonce_digest(v)) is False

    @pytest.mark.parametrize("stored", [None, "", 0, b"deadbeef", {"h": "x"}])
    def test_nonce_matches_refuses_a_missing_or_non_string_store(self, stored):
        # An absent `nonce_hash` (legacy claim, released claim) must be a
        # REFUSAL from this primitive, never a crash and never a match --
        # §5.3's legacy branch is a decision made one layer up, not here.
        assert fleet.nonce_matches(fleet.mint_nonce(), stored) is False

    def test_nonce_matches_refuses_the_raw_digest_shape_the_spec_warns_about(self):
        # §5.2: "comparing a digest object to a hex string is the shape to
        # avoid". `hmac.compare_digest` raises TypeError on a str/bytes pair,
        # so a store holding raw digest BYTES must be refused, not raised.
        import hashlib
        v = fleet.mint_nonce()
        assert fleet.nonce_matches(v, hashlib.sha256(v.encode("utf-8")).digest()) is False

    def test_pending_nonce_ttl_is_the_long_value_and_the_asymmetry_is_pinned(self):
        # §5.3: proposed at 900 s, NOT 300 s. The tension between §5.4(b)
        # (short: a pending lost to a failed verb is replaced sooner) and
        # §5.4(d) (long: a delivered pending is not stolen from a body that is
        # merely thinking) resolves toward LONG, because a long TTL only
        # delays the replacement of a lost pending while a short one actively
        # invalidates a value a legitimate body is holding. Pinned so the
        # asymmetry is not re-derived backwards.
        assert fleet.PENDING_NONCE_TTL_SECONDS == 900.0
        assert fleet.PENDING_NONCE_TTL_SECONDS > fleet.SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS


class TestClaimDecision:
    def test_no_claim_file_claims(self):
        v, _ = fleet.supervisor_claim_decision(None, set(), None, now=NOW)
        assert v == "claim"

    def test_live_in_roster_refuses(self):
        v, _ = fleet.supervisor_claim_decision(_claim(), {"sid-old"}, None, now=NOW)
        assert v == "refuse"

    def test_roster_gone_stale_heartbeat_seizes(self):
        c = _claim(beat=NOW - timedelta(seconds=3601))
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "seize"

    def test_roster_gone_fresh_heartbeat_freezes(self):
        c = _claim(beat=NOW - timedelta(seconds=120))
        v, reason = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"
        assert "G9" in reason or "daemon" in reason.lower()

    def test_fresher_foreign_checkpoint_refuses(self):
        # journal's latest entry is a DIFFERENT incarnation, newer than the
        # claim's heartbeat -> mid-transition, bystander must refuse (spec §4)
        c = _claim(beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=30)), "kind": "CHECKPOINT",
                  "inc": "inc-newer", "sid": "sid-newer", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "refuse"

    def test_own_incarnation_checkpoint_does_not_block_seize(self):
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=7100)), "kind": "CHECKPOINT",
                  "inc": "inc-old", "sid": "sid-old", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"

    def test_unparseable_heartbeat_freezes_never_seizes(self):
        c = _claim()
        c["heartbeat_at"] = "garbage"
        v, _ = fleet.supervisor_claim_decision(c, set(), None, now=NOW)
        assert v == "freeze"

    def test_foreign_but_not_fresher_checkpoint_falls_through_to_seize(self):
        # journal's latest entry is a DIFFERENT incarnation but OLDER than
        # the claim's heartbeat -- the normal dead-post-handoff-successor
        # recovery path. A "refuse on any foreign inc" refactor must fail
        # this test.
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": _iso(NOW - timedelta(seconds=8000)), "kind": "CHECKPOINT",
                  "inc": "inc-other", "sid": "sid-other", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"

    def test_foreign_checkpoint_unparseable_ts_falls_through(self):
        c = _claim(inc="inc-old", beat=NOW - timedelta(seconds=7200))
        latest = {"ts": "garbage", "kind": "CHECKPOINT",
                  "inc": "inc-other", "sid": "sid-other", "body": ""}
        v, _ = fleet.supervisor_claim_decision(c, set(), latest, now=NOW)
        assert v == "seize"


class TestClaimDecisionVerdictOrder:
    """T14 (claim-nonce §6.1): the boot verdict order, table-driven over the
    spec's own four-case table, plus the released row of §6.3.

    The load-bearing row is (iii), the N1 attack: `caller_sid` is a settable
    environment variable (`current_caller_session()` is one `os.environ.get`),
    so a rule keyed on `holder_sid != caller_sid` lets a spoofer DE-AUTHORIZE
    the only body-discriminating guard in the program. The corrected rule keys
    the exception on continuity (`nonce_valid`), never on the sid alone."""

    def test_i_distinct_live_holder_refuses_even_with_a_valid_generation(self):
        # Incident 1's fork: distinct sid, holds a copied generation.
        v, reason = fleet.supervisor_claim_decision(
            _claim(), {"sid-old"}, None, now=NOW,
            caller_sid="sid-fork", nonce_valid=True)
        assert v == "refuse"
        assert "live in the roster" in reason

    def test_ii_incident_2_same_sid_resumed_with_generation_resumes(self):
        # The wart this slice exists to fix: the holder IS the caller, is
        # roster-live, its heartbeat has aged past the seizure threshold, and
        # it holds its generation. Shipped code refuses this unconditionally.
        c = _claim(beat=NOW - timedelta(seconds=7200))
        v, reason = fleet.supervisor_claim_decision(
            c, {"sid-old"}, None, now=NOW,
            caller_sid="sid-old", nonce_valid=True)
        assert v == "resume"
        assert "resumed own claim" in reason

    def test_iii_n1_attack_spoofed_sid_without_a_generation_refuses(self):
        # THE regression guard. Caller reads the holder's sid from the
        # lock-free `sup-status` view, exports it as CLAUDE_CODE_SESSION_ID,
        # and boots holding no generation against a live, healthy holder whose
        # heartbeat has merely aged (the ordinary state of a busy supervisor:
        # this slice ships no automatic beat). Must be `refuse`, NEVER `seize`.
        c = _claim(beat=NOW - timedelta(seconds=7200))
        v, reason = fleet.supervisor_claim_decision(
            c, {"sid-old"}, None, now=NOW,
            caller_sid="sid-old", nonce_valid=False)
        assert v == "refuse"
        # And it must be RULE 2 that refuses, not the fail-closed `else` on
        # rules 4-. The two are belt-and-braces: with v2's sid-keyed clause
        # (`holder_sid != caller_sid`) rule 2 does not fire, the caller falls
        # through, and the F2 backstop refuses it anyway -- so an assertion on
        # the verdict alone passes against the exact regression this row
        # exists to pin. Naming the guard is what makes the row load-bearing.
        assert "live in the roster" in reason
        assert "should have caught this" not in reason

    def test_iv_holder_roster_gone_with_generation_resumes_without_seizing(self):
        c = _claim(beat=NOW - timedelta(seconds=7200))
        v, reason = fleet.supervisor_claim_decision(
            c, set(), None, now=NOW, caller_sid="sid-new", nonce_valid=True)
        assert v == "resume"
        assert "resumed own claim" in reason

    def test_holder_roster_gone_without_generation_still_seizes(self):
        c = _claim(beat=NOW - timedelta(seconds=7200))
        v, _ = fleet.supervisor_claim_decision(
            c, set(), None, now=NOW, caller_sid="sid-new", nonce_valid=False)
        assert v == "seize"

    def test_released_claim_is_a_fresh_claim_not_a_seizure(self):
        # §6.3: a released claim has no session_id and no heartbeat_at, so it
        # must be decided by `state` alone, ahead of every other rule.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": _iso(NOW),
                    "released_by_sid": "sid-old", "state": "released"}
        v, reason = fleet.supervisor_claim_decision(
            released, set(), None, now=NOW, caller_sid="sid-new")
        assert v == "claim"
        assert "released cleanly" in reason

    def test_released_claim_is_NOT_consumed_while_its_releaser_is_roster_live(self):
        """B6 (three-tier-command.md :1184-1190), INVERTED from the test this
        class shipped in `d13af83`.

        That test asserted `claim` here and pinned the PRE-B6 semantics --
        deliberately, and flagged loudly at the time, because a future reader
        would otherwise have read a passing test as the decided answer. The
        prerequisite has since been ruled in:

          > `sup-boot` must not consume a `released` record whose
          > `released_by_sid` is still roster-live -- either rule 1 gains a
          > roster-liveness precondition, or release+stop is made atomic from
          > the claim's perspective (the record is never left
          > `released`-and-live).

        `fleet sup-release` followed by `claude stop` is two commands, and the
        window between them is real: three-tier adds AUTOMATED occupants of it
        (a scheduled beat, `sup-spawn`, a handoff successor polling
        `sup-boot`), and SPEC §16.7's one-live-session-per-name blocks a second
        `supervisor`-named spawn but not a `sup-boot` from an already-live
        differently-named session. Rule 1 gains the precondition."""
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": _iso(NOW),
                    "released_by_sid": "sid-old", "state": "released"}
        v, reason = fleet.supervisor_claim_decision(
            released, {"sid-old"}, None, now=NOW, caller_sid="sid-new")
        assert v == "refuse"
        assert "sid-old" in reason
        assert v in fleet.SUPERVISOR_BOOT_RC

    def test_the_releaser_going_roster_gone_is_what_opens_the_claim(self):
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": _iso(NOW),
                    "released_by_sid": "sid-old", "state": "released"}
        v, reason = fleet.supervisor_claim_decision(
            released, {"sid-new"}, None, now=NOW, caller_sid="sid-new")
        assert v == "claim"
        assert "released cleanly" in reason

    @pytest.mark.parametrize("released_by", [None, "", 0])
    def test_a_released_record_naming_no_releaser_is_not_gated_by_a_None_in_the_roster(
            self, released_by):
        # A released claim carries no `session_id` at all (§6.3), so nothing
        # here may be steerable by a `None` that a hostile or drifted roster
        # put in the live set. The precondition keys on `released_by_sid`
        # ONLY when it is a non-empty string -- otherwise a record that names
        # no releaser would be gated forever by a value nobody wrote.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": _iso(NOW),
                    "released_by_sid": released_by, "state": "released"}
        v, _ = fleet.supervisor_claim_decision(
            released, {"sid-old", None, ""}, None, now=NOW, caller_sid="sid-old")
        assert v == "claim"

    def test_the_releaser_may_reboot_its_own_released_claim_once_it_is_gone(self):
        # Not a special case -- just the ordinary shape after `claude stop`.
        # Recorded because "the releaser is the caller" is the row an
        # implementation keyed on `caller_sid` would get wrong.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": _iso(NOW),
                    "released_by_sid": "sid-old", "state": "released"}
        v, _ = fleet.supervisor_claim_decision(
            released, set(), None, now=NOW, caller_sid="sid-old")
        assert v == "claim"

    def test_legacy_call_signature_still_decides(self):
        # Migration: every existing caller passes neither caller_sid nor
        # nonce_valid. Without a generation nothing can resume, so the shipped
        # verdicts must be byte-identical to today's.
        assert fleet.supervisor_claim_decision(
            _claim(), {"sid-old"}, None, now=NOW)[0] == "refuse"
        assert fleet.supervisor_claim_decision(
            _claim(beat=NOW - timedelta(seconds=7200)), set(), None, now=NOW)[0] == "seize"


class TestClaimDecisionRosterPrecondition:
    """T14b (claim-nonce §6.1, break-gate residual F2): rules 4- assert
    `holder roster-gone` in strings they write into the append-only,
    git-tracked journal. That precondition must be an explicit BRANCH with a
    stated `else`, not an inherited implication.

    "Unreachable today" is exactly what `roster-gone` was before N1 -- and
    this one fails harder than N1 did: `cmd_sup_boot` maps the verdict through
    `{"claim": 0, "resume": 0, "seize": 0, "refuse": 2, "freeze": 3}[verdict]`,
    so a fall-through returning `None` is a KeyError traceback out of the boot
    ritual rather than a safe stop."""

    @pytest.mark.parametrize("nonce_valid", [True, False])
    @pytest.mark.parametrize("caller_sid", ["sid-old", "sid-other", None])
    @pytest.mark.parametrize("beat_age", [60, 3601, 86400])
    @pytest.mark.parametrize("latest_inc", [None, "inc-old", "inc-newer"])
    def test_no_seize_or_freeze_while_the_holder_is_roster_live(
            self, nonce_valid, caller_sid, beat_age, latest_inc):
        c = _claim(beat=NOW - timedelta(seconds=beat_age))
        latest = None if latest_inc is None else {
            "ts": _iso(NOW - timedelta(seconds=1)), "kind": "CHECKPOINT",
            "inc": latest_inc, "sid": "sid-x", "body": ""}
        v, reason = fleet.supervisor_claim_decision(
            c, {"sid-old"}, latest, now=NOW,
            caller_sid=caller_sid, nonce_valid=nonce_valid)
        assert v not in ("seize", "freeze"), reason
        assert "roster-gone" not in reason

    def test_the_precondition_states_its_else_and_it_is_refuse(self, monkeypatch):
        """Fault injection for the F2 guard.

        The `else` is unreachable through the shipped rules -- that is the
        whole hazard, and it is why the test has to WEAKEN rule 3's premise to
        reach it, which is precisely the future edit the guard exists to
        survive. With `_claim_resume_allowed` forced False, a roster-live
        holder falls past rules 2 and 3; absent the `else` the function drops
        off the end and returns None, and the assertion below goes red."""
        monkeypatch.setattr(fleet, "_claim_resume_allowed",
                            lambda *a, **k: False)
        c = _claim(beat=NOW - timedelta(seconds=7200))
        v, reason = fleet.supervisor_claim_decision(
            c, {"sid-old"}, None, now=NOW,
            caller_sid="sid-old", nonce_valid=True)
        assert v == "refuse"
        assert "roster-live" in reason
        # Fail-closed AND in the rc map -- the half a `None` fall-through loses.
        assert v in fleet.SUPERVISOR_BOOT_RC


class TestEpochCheck:
    def test_roster_fetch_failure_freezes(self):
        ok, reason = fleet.supervisor_epoch_check(False, "claude not on PATH")
        assert ok is False and "claude not on PATH" in reason

    def test_empty_roster_is_suspicious(self):
        # the booting session itself is a claude session -- an --all roster
        # with ZERO entries means the daemon lost its memory (G9 shape)
        ok, reason = fleet.supervisor_epoch_check(True, [])
        assert ok is False

    def test_populated_roster_passes(self):
        ok, _ = fleet.supervisor_epoch_check(True, [{"sessionId": "s1", "status": "idle"}])
        assert ok is True


class TestRosterLiveSids:
    def test_status_or_pid_means_live(self):
        entries = [
            {"sessionId": "a", "status": "busy", "pid": 1, "state": "working"},
            {"sessionId": "b", "state": "done"},              # dead: no status/pid
            {"sessionId": "c", "status": "idle"},             # interactive: live
            {"sessionId": "d", "state": "working"},           # wedged, no pid/status: NOT live
            {"no_sid": True, "status": "idle"},               # malformed: skipped
        ]
        assert fleet._roster_live_sids(entries) == {"a", "c"}

    def test_lingering_done_process_with_keys_is_not_live(self):
        # posix-port live finding 2026-07-19 (macOS, 2.1.214): a finished bg
        # session's host process lingers -- entry keeps pid AND status with
        # state:"done". Terminal state dominates key presence, or an idle
        # worker's respawn is refused ("turn is running") forever.
        entries = [
            {"sessionId": "lingerer", "pid": 42707, "status": "idle",
             "state": "done"},
            {"sessionId": "live", "pid": 1, "status": "busy",
             "state": "working"},
        ]
        assert fleet._roster_live_sids(entries) == {"live"}

    def test_hostile_sessionid_value_filtered_not_raised(self):
        # Debt roll-up item 2, third grepped site: a dict-valued sessionId
        # (CLI drift / hostile roster) must be filtered, never raise
        # TypeError from an unhashable value landing in the live-sid set.
        entries = [
            {"sessionId": {"nested": "hostile"}, "status": "busy"},
            {"sessionId": ["also", "unhashable"], "pid": 7},
            {"sessionId": "ok", "status": "idle"},
        ]
        assert fleet._roster_live_sids(entries) == {"ok"}


def _fake_run_roster(entries):
    """Injectable subprocess.run double returning a roster JSON payload."""
    def run(argv, **kw):
        assert "--json" in argv and "--all" in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


def _fake_which(name):
    return "C:/fake/claude.cmd"


class TestSupBoot:
    def _boot(self, sup_home, entries, sid="sid-me", handoff=None):
        args = SimpleNamespace(sid=sid, handoff_inc=handoff)
        return fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster(entries))

    def test_fresh_claim_writes_incarnation_and_boot_checkpoint(self, sup_home, capsys):
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "fresh"
        entries = fleet.supervisor_journal_entries()
        assert entries[-1]["kind"] == "BOOT"
        out = capsys.readouterr().out
        assert "VERDICT: claim" in out and "GOALS" in out and "entry one" in out

    def test_refuse_is_strictly_read_only(self, sup_home, capsys):
        live_holder = _claim(sid="sid-holder")
        fleet.write_incarnation(live_holder)
        before_journal = fleet.supervisor_journal_entries()
        fleet.write_handshake("inc-inflight", "sid-x")  # in-flight handoff artifact
        rc = self._boot(sup_home, [{"sessionId": "sid-holder", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}])
        assert rc == 2
        assert fleet.read_incarnation() == live_holder          # untouched
        assert fleet.read_handshake() is not None               # bystander never deletes (spec §4)
        assert fleet.supervisor_journal_entries() == before_journal
        assert "VERDICT: refuse" in capsys.readouterr().out

    def test_seize_rewrites_claim_deletes_handshake_journals_seized(self, sup_home, capsys):
        stale = _claim(inc="inc-dead", sid="sid-dead",
                       beat=datetime.now(timezone.utc) - timedelta(hours=3))
        fleet.write_incarnation(stale)
        fleet.write_handshake("inc-orphan", "sid-orphan")  # crash-mid-handoff orphan
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 0
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-me" and claim["claimed_via"] == "seize"
        assert fleet.read_handshake() is None                   # stale-HANDSHAKE hygiene
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "SEIZED" and "inc-dead" in latest["body"]

    def test_freeze_on_fresh_heartbeat_roster_gone(self, sup_home, capsys):
        fresh = _claim(sid="sid-gone", beat=datetime.now(timezone.utc) - timedelta(seconds=30))
        fleet.write_incarnation(fresh)
        rc = self._boot(sup_home, [{"sessionId": "sid-me", "status": "busy"}])
        assert rc == 3
        assert fleet.read_incarnation() == fresh
        assert "VERDICT: freeze" in capsys.readouterr().out

    def test_freeze_on_empty_roster_even_with_no_claim(self, sup_home, capsys):
        rc = self._boot(sup_home, [])
        assert rc == 3
        assert fleet.read_incarnation() is None  # epoch freeze blocks even a fresh claim

    def test_handoff_mode_writes_handshake_touches_nothing_else(self, sup_home, capsys):
        holder = _claim(sid="sid-old")
        fleet.write_incarnation(holder)
        before_journal = fleet.supervisor_journal_entries()
        rc = self._boot(sup_home, [{"sessionId": "sid-old", "status": "idle"},
                                   {"sessionId": "sid-me", "status": "busy"}],
                        handoff="inc-successor")
        assert rc == 0
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-successor" and hs["session_id"] == "sid-me"
        assert fleet.read_incarnation() == holder
        assert fleet.supervisor_journal_entries() == before_journal
        assert "handshake-written" in capsys.readouterr().out

    def test_no_sid_available_is_cli_error(self, sup_home):
        args = SimpleNamespace(sid=None, handoff_inc=None)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster([]))


class TestSupBootContinuity:
    """The boot half of the continuity proof.

    `d13af83` gave `supervisor_claim_decision` its `caller_sid`/`nonce_valid`
    parameters and its `resume` rule; `cmd_sup_boot` passed NEITHER and had no
    `resume` branch, so the rule was unreachable from the command that owns
    it. Everything here is about closing that gap, end to end, through the
    real verb rather than the pure function -- which is the only level at
    which "incident 2 is fixed" is a true statement."""

    def _boot(self, entries, sid="sid-me", handoff=None, nonce=None):
        args = SimpleNamespace(sid=sid, handoff_inc=handoff, nonce=nonce)
        return fleet.cmd_sup_boot(args, which=_fake_which, run=_fake_run_roster(entries))

    def _held(self, sid="sid-old", inc="inc-old", age_seconds=7200, **extra):
        value = fleet.mint_nonce()
        beat = (datetime.now(timezone.utc)
                - timedelta(seconds=age_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
        claim = {"incarnation_id": inc, "session_id": sid, "claimed_at": beat,
                 "heartbeat_at": beat, "claimed_via": "fresh",
                 "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
                 "lineage_id": "lin-20260101T000000Z-aaaa"}
        claim.update(extra)
        fleet.write_incarnation(claim)
        return value

    # --- incident 2, end to end ------------------------------------------

    def test_incident_2_the_holder_resumes_its_own_aged_claim(self, sup_home, capsys):
        # The wart this slice exists to fix: same body, roster-live, heartbeat
        # aged past the seizure threshold, holding its generation. Shipped code
        # refuses this unconditionally, and the refusal is what drove operators
        # to seize their own live claim.
        live = self._held(sid="sid-me", age_seconds=7200)
        rc = self._boot([{"sessionId": "sid-me", "status": "busy"}],
                        sid="sid-me", nonce=live)
        out = capsys.readouterr().out
        assert rc == 0
        assert "VERDICT: resume" in out
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == "inc-old", "a resume mints no incarnation"
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["BOOT"]
        assert "resumed own claim" in fleet.supervisor_journal_latest()["body"]
        assert fleet.supervisor_journal_latest()["kind"] != "SEIZED"

    def test_a_resume_refreshes_the_heartbeat_and_restamps_the_sid(self, sup_home, capsys):
        # Fork-steer as it actually presents at boot: the recorded sid was
        # RETIRED by the steer, so it is roster-gone, and the body that still
        # holds the generation carries a new one. §6.1 rule 2 does not fire (no
        # distinct LIVE holder to protect), rule 3 does. Had the retired sid
        # still been roster-live, rule 2 would refuse -- correctly: a
        # continuity proof is not a body-discriminator, and two live sids on
        # one claim is the exact shape the guard exists for.
        live = self._held(sid="sid-before", age_seconds=7200)
        before = fleet.read_incarnation()["heartbeat_at"]
        assert self._boot([{"sessionId": "sid-after", "status": "busy"}],
                          sid="sid-after", nonce=live) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["heartbeat_at"] > before
        assert claim["session_id"] == "sid-after"

    def test_the_N1_attack_end_to_end_a_spoofed_sid_without_a_generation_refuses(
            self, sup_home, capsys):
        # T14(iii) at the command level. The pure-function test pins the rule;
        # this pins that `cmd_sup_boot` actually HANDS the rule its inputs --
        # the exact wiring whose absence made the rule unreachable.
        self._held(sid="sid-holder", age_seconds=7200)
        before = fleet.read_incarnation()
        rc = self._boot([{"sessionId": "sid-holder", "status": "idle"}],
                        sid="sid-holder", nonce=None)
        assert rc == 2
        assert "VERDICT: refuse" in capsys.readouterr().out
        assert fleet.read_incarnation() == before
        assert fleet.supervisor_journal_entries() == []

    def test_a_forked_body_presenting_a_copied_generation_still_refuses(self, sup_home, capsys):
        # T14(i) / incident 1's fork: DISTINCT sid, valid generation, holder
        # roster-live. Rule 2 runs ahead of the continuity check for exactly
        # this case -- a continuity proof is not a body-discriminator.
        live = self._held(sid="sid-holder", age_seconds=60)
        rc = self._boot([{"sessionId": "sid-holder", "status": "idle"},
                         {"sessionId": "sid-fork", "status": "busy"}],
                        sid="sid-fork", nonce=live)
        assert rc == 2
        assert "VERDICT: refuse" in capsys.readouterr().out

    def test_a_resume_that_presents_the_PENDING_generation_acknowledges_it(
            self, sup_home, capsys):
        # Boot is a `sup-*` verb like any other: it must run the same
        # three-slot rules, or a body whose last delivery was a pending is
        # refused by the one command whose job is to re-establish continuity.
        live = self._held(sid="sid-me", age_seconds=7200)
        pending = fleet.mint_nonce()
        claim = fleet.read_incarnation()
        claim["pending_nonce_hash"] = fleet.nonce_digest(pending)
        claim["pending_at"] = fleet.now_iso()
        fleet.write_incarnation(claim)
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}],
                          sid="sid-me", nonce=pending) == 0
        capsys.readouterr()
        after = fleet.read_incarnation()
        assert after["nonce_seq"] == 4, "the acknowledgment advanced the generation"
        assert after["nonce_hash"] == fleet.nonce_digest(pending)
        assert fleet.nonce_matches(live, after["nonce_hash"]) is False

    # --- §9's binding dict-literal rule -----------------------------------

    def test_a_fresh_claim_carries_the_v2_fields_and_delivers_its_generation(
            self, sup_home, capsys):
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}]) == 0
        value = _nonce_of(capsys.readouterr().out)
        claim = fleet.read_incarnation()
        assert claim["nonce_hash"] == fleet.nonce_digest(value)
        assert claim["nonce_seq"] == 1
        assert re.fullmatch(r"lin-\d{8}T\d{6}Z-[0-9a-f]{4}", claim["lineage_id"])

    def test_a_seize_carries_the_v2_fields_and_RE_MINTS_the_lineage(self, sup_home, capsys):
        # §6.2: lineage is minted at the first fresh claim, CARRIED across
        # handoff, RE-MINTED on seize -- a seize is a recovery, and being asked
        # once at a recovery is correct. Carrying it would launder the dead
        # body's provenance onto the seizing one.
        self._held(sid="sid-dead", age_seconds=3 * 3600)
        old_lineage = fleet.read_incarnation()["lineage_id"]
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}]) == 0
        value = _nonce_of(capsys.readouterr().out)
        claim = fleet.read_incarnation()
        assert claim["claimed_via"] == "seize"
        assert claim["nonce_hash"] == fleet.nonce_digest(value)
        assert claim["nonce_seq"] == 1
        assert claim["lineage_id"] != old_lineage

    def test_a_resume_neither_re_mints_nor_drops_the_lineage(self, sup_home, capsys):
        live = self._held(sid="sid-me", age_seconds=7200)
        before = fleet.read_incarnation()["lineage_id"]
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}],
                          sid="sid-me", nonce=live) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["lineage_id"] == before

    @pytest.mark.parametrize("writer", ["fresh", "seize"])
    def test_T10_every_dict_literal_writer_produces_a_claim_that_still_validates(
            self, sup_home, capsys, writer):
        """The test §9 says exists solely to fail if a literal is missed.

        Three writers build an INCARNATION from a dict LITERAL and three
        round-trip the dict they read. Fields added only to the round-trip
        writers survive checkpoints and heartbeats and are then silently
        destroyed by the next seize or handoff -- a claim that works for days
        and fails at the worst moment. So the assertion is not "the key is
        present": it is that the very next continuity-proving call SUCCEEDS."""
        if writer == "seize":
            self._held(sid="sid-dead", age_seconds=3 * 3600)
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}]) == 0
        value = _nonce_of(capsys.readouterr().out)
        # FIRST, and load-bearing: a claim whose literal dropped the nonce
        # fields is a five-key claim, i.e. a LEGACY claim -- and §5.3 rule 4
        # then honors it by sid equality, so the "next call succeeds"
        # assertion below passes on exactly the bug this test exists to catch.
        # A wrong value under a MATCHING sid is what separates the two: the
        # legacy path ignores the value, the continuity path refuses it.
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=fleet.mint_nonce()))
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=value)) == 0
        capsys.readouterr()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=None))

    def test_the_handoff_complete_literal_carries_the_predecessors_lineage(
            self, sup_home, capsys):
        # §6.2: carried across handoff. The successor's own generation is
        # §6.4's work (it reaches the claim through HANDSHAKE, which does not
        # carry it yet), so the transferred claim is deliberately a LEGACY
        # claim in this slice -- §9's documented mixed-code shape, which the
        # successor's first call upgrades in place.
        live = self._held(sid="sid-old", inc="inc-old", age_seconds=10)
        fleet.write_handshake("inc-new", "sid-new")
        args = SimpleNamespace(expect_inc="inc-new", expect_sid="sid-new",
                               sid="sid-old", nonce=live)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == "inc-new"
        assert claim["lineage_id"] == "lin-20260101T000000Z-aaaa"

    # --- §5.8's second publisher ------------------------------------------

    def test_B6_boot_refuses_a_released_record_whose_releaser_is_still_live(
            self, sup_home, capsys):
        # The guard where an operator meets it. `fleet sup-release` then
        # `claude stop` is TWO commands; between them the record is
        # `released`-and-live and a second body booting into it produces
        # exactly the two-live-supervisors shape §6.6 exists to prevent.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-releaser", "state": "released"}
        fleet.write_incarnation(released)
        rc = self._boot([{"sessionId": "sid-releaser", "status": "idle"},
                         {"sessionId": "sid-me", "status": "busy"}])
        assert rc == 2
        assert "VERDICT: refuse" in capsys.readouterr().out
        assert fleet.read_incarnation() == released, "refuse is strictly read-only"
        assert fleet.supervisor_journal_entries() == []

    def test_B6_once_the_releaser_is_gone_the_boot_proceeds(self, sup_home, capsys):
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-releaser", "state": "released"}
        fleet.write_incarnation(released)
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}]) == 0
        out = capsys.readouterr().out
        assert "VERDICT: claim" in out
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] != "inc-old"
        assert claim["nonce_hash"] == fleet.nonce_digest(_nonce_of(out))
        assert fleet.supervisor_journal_latest()["kind"] == "BOOT"

    def test_no_stored_hash_reaches_sup_boots_stdout(self, sup_home, capsys):
        # §5.8 enumerates TWO publishers and v2 wrote the rule against one.
        # `cmd_sup_boot` prints claim identity on the same run and §11 adds the
        # `NONCE:` line to that same stream, so the rule extends here: the one
        # plaintext this design prints is the newly minted generation, printed
        # exactly once, and no HASH may appear at all.
        self._held(sid="sid-dead", age_seconds=3 * 3600)
        hashes = [v for k, v in fleet.read_incarnation().items() if k.endswith("_hash")]
        assert hashes, "guard the guard: the seeded claim must actually hold a hash"
        assert self._boot([{"sessionId": "sid-me", "status": "busy"}]) == 0
        out = capsys.readouterr().out
        for h in hashes + [v for k, v in fleet.read_incarnation().items()
                           if k.endswith("_hash")]:
            assert h not in out


class TestCheckpointHeartbeat:
    def _hold(self, sid="sid-me", inc="inc-me"):
        # Seed the heartbeat strictly in the past: now_iso() truncates to
        # whole seconds, so a same-second seed would let `>=` pass on
        # equality even if the refresh silently stopped happening.
        beat = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})

    def test_checkpoint_appends_and_refreshes_heartbeat(self, sup_home):
        self._hold()
        old_beat = fleet.read_incarnation()["heartbeat_at"]
        args = SimpleNamespace(body="did a thing", kind="CHECKPOINT", sid="sid-me")
        assert fleet.cmd_sup_checkpoint(args) == 0
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT" and latest["body"] == "did a thing"
        assert latest["inc"] == "inc-me"
        assert fleet.read_incarnation()["heartbeat_at"] > old_beat

    def test_non_holder_refused_journal_untouched(self, sup_home):
        self._hold(sid="sid-holder")
        args = SimpleNamespace(body="intruder", kind="CHECKPOINT", sid="sid-intruder")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)
        assert fleet.supervisor_journal_entries() == []

    def test_checkpoint_without_any_claim_refused(self, sup_home):
        args = SimpleNamespace(body="x", kind="CHECKPOINT", sid="sid-me")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(args)

    def test_heartbeat_refreshes_without_journal_growth(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-me")
        assert fleet.cmd_sup_heartbeat(args) == 0
        assert fleet.supervisor_journal_entries() == []
        assert fleet.read_incarnation()["heartbeat_at"] is not None


def _ckpt(sid="sid-me", nonce=None, body="did a thing", kind="CHECKPOINT"):
    return SimpleNamespace(body=body, kind=kind, sid=sid, nonce=nonce)


def _nonce_of(out: str) -> str:
    """The one plaintext generation a verb delivers, parsed off its stdout.

    §5.3: the plaintext of a newly minted pending is printed once, on the
    verb's own stdout, after the commit -- there is no other copy anywhere, so
    a test that wants the next generation has to read it exactly where a real
    supervisor body reads it."""
    values = re.findall(r"^NONCE: (?!unchanged)(\S+)$", out, re.M)
    assert len(values) == 1, f"expected exactly one delivered generation, got {values!r}"
    return values[0]


class TestLegacyClaimUpgrade:
    """T11 / §9: the path EVERY existing installation takes on first contact.

    A shipped five-key INCARNATION has no `nonce_hash`. §5.3 rule 4 honors
    today's sid equality ONCE and upgrades the claim in place. §9's predicate
    is `nonce_hash` absent AND `state` absent, precisely so a released claim
    (§6.3, which also has no `nonce_hash`) cannot be misread as legacy and
    resurrected by whoever matches a sid the release already deleted."""

    def _legacy(self, sid="sid-me", inc="inc-me"):
        beat = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})

    def test_legacy_claim_is_honored_once_by_sid_and_upgraded_in_place(self, sup_home, capsys):
        self._legacy()
        assert fleet.cmd_sup_checkpoint(_ckpt()) == 0
        value = _nonce_of(capsys.readouterr().out)
        claim = fleet.read_incarnation()
        assert claim["nonce_seq"] == 1
        assert claim["nonce_hash"] == fleet.nonce_digest(value)
        assert claim["incarnation_id"] == "inc-me", "an upgrade is not a new incarnation"

    def test_the_upgrade_delivers_a_LIVE_generation_not_a_pending_one(self, sup_home, capsys):
        # §5.3 rule 4 mints a LIVE generation and sets nonce_seq = 1. Minting a
        # pending in the same breath would deliver two values on one output and
        # make "the most recent generation it was given" ambiguous on the very
        # first contact -- the presenter-obligation hazard of §5.4(e), at the
        # one moment every installation passes through.
        self._legacy()
        fleet.cmd_sup_checkpoint(_ckpt())
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert "pending_nonce_hash" not in claim
        assert "pending_at" not in claim

    def test_after_the_upgrade_the_sid_alone_no_longer_suffices(self, sup_home, capsys):
        self._legacy()
        fleet.cmd_sup_checkpoint(_ckpt())
        capsys.readouterr()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt())

    def test_after_the_upgrade_the_delivered_generation_does_suffice(self, sup_home, capsys):
        self._legacy()
        fleet.cmd_sup_checkpoint(_ckpt())
        value = _nonce_of(capsys.readouterr().out)
        assert fleet.cmd_sup_checkpoint(_ckpt(nonce=value)) == 0

    def test_legacy_sid_mismatch_still_refuses_exactly_as_shipped_code_does(self, sup_home):
        self._legacy(sid="sid-holder")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-intruder"))
        assert "nonce_hash" not in fleet.read_incarnation(), "a refusal upgrades nothing"

    def test_a_released_claim_is_NOT_legacy_and_is_not_resurrected_by_a_sid(self, sup_home):
        # T12. The released claim keeps `released_by_sid` (§6.3), so the
        # tempting-but-wrong implementation -- "no nonce_hash means legacy,
        # compare the sid" -- has a sid sitting right there to match.
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-me", "state": "released"}
        fleet.write_incarnation(released)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me"))
        assert fleet.read_incarnation() == released, "a released claim is terminal"
        # The released state is decided by its own branch, not reached by
        # falling through the continuity rules to the generic refusal: a body
        # facing a cleanly released claim is not facing a possible second body,
        # and telling it so would send it to the operator for nothing. §6.1
        # rule 1 is the route forward and the message says exactly that.
        assert "released" in str(exc.value)
        assert "sup-boot" in str(exc.value)
        assert "second body" not in str(exc.value)

    def test_a_released_claim_carrying_a_STRAY_session_id_is_still_not_legacy(self, sup_home):
        """Fault injection for §9's second conjunct.

        §6.3 removes `session_id` on release, so with a correctly-written
        released claim the weakened predicate (`nonce_hash` absent alone)
        still refuses -- by accident, on the sid comparison, because there is
        no sid to match. That accident is exactly what makes the conjunct look
        droppable. §9 names the hazard directly: "with no recorded sid there is
        nothing for a sid comparison to match EVEN IF a future reader
        re-introduces one". This is that reader. Written by an older release
        path, a hand-edited file, or a merge of the two shapes, the sid is
        present -- and under the weakened predicate the claim is upgraded in
        place, `state: released` survives beside a live generation, and
        "released" has stopped being terminal."""
        released = {"incarnation_id": "inc-old", "lineage_id": "lin-x",
                    "claimed_via": "fresh", "released_at": fleet.now_iso(),
                    "released_by_sid": "sid-me", "session_id": "sid-me",
                    "state": "released"}
        fleet.write_incarnation(released)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me"))
        assert fleet.read_incarnation() == released
        assert "nonce_hash" not in fleet.read_incarnation()


class TestLegacyPredicateDirectly:
    """§9's predicate, pinned as a UNIT.

    `_claim_is_legacy` is SHADOWED at its only call site: `_require_claim_holder`
    raises on `state == "released"` before ever consulting it, so dropping the
    `state` conjunct leaves every verb-level test green. A guard that cannot be
    made to go red through the surface has to be pinned at its own level or it
    is decorative -- and this one is not decorative, because §9 wrote it down
    precisely as belt-and-braces for the day a future reader re-introduces a
    `session_id` onto a released claim."""

    def test_a_five_key_claim_is_legacy(self):
        assert fleet._claim_is_legacy(
            {"incarnation_id": "i", "session_id": "s", "claimed_at": "t",
             "heartbeat_at": "t", "claimed_via": "fresh"}) is True

    def test_a_claim_with_a_generation_is_not_legacy(self):
        assert fleet._claim_is_legacy({"nonce_hash": "ab" * 32}) is False

    def test_a_released_claim_is_not_legacy_even_though_it_has_no_generation(self):
        assert fleet._claim_is_legacy(
            {"incarnation_id": "i", "released_by_sid": "s", "state": "released"}) is False

    def test_a_released_claim_with_a_stray_session_id_is_still_not_legacy(self):
        assert fleet._claim_is_legacy(
            {"incarnation_id": "i", "session_id": "s", "released_by_sid": "s",
             "state": "released"}) is False


class TestClaimContinuity:
    """§5.3's validation rules, driven through a real verb rather than the
    helper, because the rules only mean anything in company with the single
    `write_incarnation` inside the single `fleet_lock` that §5.3 mandates."""

    def _hold(self, sid="sid-me", inc="inc-me", **extra):
        beat = (datetime.now(timezone.utc) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        value = fleet.mint_nonce()
        claim = {"incarnation_id": inc, "session_id": sid, "claimed_at": beat,
                 "heartbeat_at": beat, "claimed_via": "fresh",
                 "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 1,
                 "lineage_id": "lin-20260723-abcd"}
        claim.update(extra)
        fleet.write_incarnation(claim)
        return value

    def test_rule_1_the_live_generation_is_accepted_and_promotes_nothing(self, sup_home, capsys):
        live = self._hold()
        assert fleet.cmd_sup_checkpoint(_ckpt(nonce=live)) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["nonce_hash"] == fleet.nonce_digest(live)
        assert claim["nonce_seq"] == 1, "rule 1 promotes nothing"

    def test_T5_a_batch_of_calls_from_one_body_all_validate_and_mint_ONE_pending(
            self, sup_home, capsys):
        # The false-positive regression test. A Claude Code session batches
        # independent tool calls by instruction; fleet_lock serialises them.
        # All present `live`, all validate, exactly one pending is minted and
        # calls 2..N are told so. v1's rotate-on-every-call design turned a
        # healthy body following its own skill into a two-body alarm.
        live = self._hold()
        outs = []
        for i in range(4):
            assert fleet.cmd_sup_checkpoint(_ckpt(nonce=live, body=f"call {i}")) == 0
            outs.append(capsys.readouterr().out)
        assert len(re.findall(r"^NONCE: (?!unchanged)", "".join(outs), re.M)) == 1
        assert "NONCE: unchanged" in outs[1]
        assert outs.count(outs[1]) == 3 or all("unchanged" in o for o in outs[1:])
        claim = fleet.read_incarnation()
        assert claim["nonce_seq"] == 1, "nothing was acknowledged, so nothing advanced"

    def test_the_unchanged_notice_names_the_outstanding_generation(self, sup_home, capsys):
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        assert "NONCE: unchanged (generation 2 already outstanding)" in capsys.readouterr().out

    def test_T4_presenting_the_pending_generation_acknowledges_and_promotes(
            self, sup_home, capsys):
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        pending = _nonce_of(capsys.readouterr().out)
        assert fleet.cmd_sup_checkpoint(_ckpt(nonce=pending)) == 0
        acked_out = capsys.readouterr().out
        claim = fleet.read_incarnation()
        assert claim["nonce_hash"] == fleet.nonce_digest(pending)
        assert claim["nonce_seq"] == 2
        # Rule 2 clears all three pending slots; the SAME call then mints
        # generation 3, so `pending_nonce_hash` is repopulated -- with a
        # different value, and `prior_pending_hash` stays cleared because that
        # mint replaced nothing.
        assert claim["pending_nonce_hash"] != claim["nonce_hash"]
        assert claim["pending_nonce_hash"] == fleet.nonce_digest(_nonce_of(acked_out))
        assert "prior_pending_hash" not in claim

    def test_T4_the_old_live_generation_dies_only_once_its_successor_is_proven_received(
            self, sup_home, capsys):
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        pending = _nonce_of(capsys.readouterr().out)
        fleet.cmd_sup_checkpoint(_ckpt(nonce=pending))       # the acknowledgment
        capsys.readouterr()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=live))

    def test_T7_a_FRESH_pending_is_not_replaced(self, sup_home, capsys):
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        before = fleet.read_incarnation()["pending_nonce_hash"]
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        assert fleet.read_incarnation()["pending_nonce_hash"] == before

    def _expire_pending(self):
        claim = fleet.read_incarnation()
        old = datetime.now(timezone.utc) - timedelta(
            seconds=fleet.PENDING_NONCE_TTL_SECONDS + 60)
        claim["pending_at"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation(claim)
        return claim["pending_nonce_hash"]

    def test_T7_an_EXPIRED_pending_is_replaced_and_the_old_hash_moves_to_prior(
            self, sup_home, capsys):
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        p1_hash = self._expire_pending()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        p2 = _nonce_of(capsys.readouterr().out)
        claim = fleet.read_incarnation()
        assert claim["pending_nonce_hash"] == fleet.nonce_digest(p2) != p1_hash
        assert claim["prior_pending_hash"] == p1_hash

    def test_T7_the_body_holding_the_REPLACED_pending_is_accepted_not_refused(
            self, sup_home, capsys):
        # §5.4(d): without the third slot the alarm fires on the LEGITIMATE
        # body -- the one that spent longer than the TTL thinking -- while the
        # body that acts most often inside the window owns the chain. That is
        # the wrong bias for this system. Rule 3 bounds it to two TTL periods.
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        p1 = _nonce_of(capsys.readouterr().out)
        self._expire_pending()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))          # mints P2, P1 -> prior
        capsys.readouterr()
        assert fleet.cmd_sup_checkpoint(_ckpt(nonce=p1)) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["nonce_seq"] == 1, "rule 3 promotes nothing"

    def test_the_prior_slot_is_ONE_slot_not_a_chain(self, sup_home, capsys):
        # §5.3: "One slot, not a chain: a second replacement drops the oldest."
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        p1 = _nonce_of(capsys.readouterr().out)
        self._expire_pending()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        self._expire_pending()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        capsys.readouterr()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=p1))

    def test_an_acknowledgment_clears_the_prior_slot_too(self, sup_home, capsys):
        # §5.3 rule 2 clears `pending_nonce_hash`, `pending_at` AND
        # `prior_pending_hash`. Dropping the third from the clear list leaves a
        # superseded generation presentable across an acknowledgment that was
        # supposed to retire everything before it -- a third live value, which
        # is precisely the budget §5.4(d) bounded to one.
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))
        p1 = _nonce_of(capsys.readouterr().out)
        self._expire_pending()
        fleet.cmd_sup_checkpoint(_ckpt(nonce=live))          # P1 -> prior, mints P2
        p2 = _nonce_of(capsys.readouterr().out)
        assert fleet.read_incarnation()["prior_pending_hash"] == fleet.nonce_digest(p1)
        fleet.cmd_sup_checkpoint(_ckpt(nonce=p2))            # the acknowledgment
        capsys.readouterr()
        assert "prior_pending_hash" not in fleet.read_incarnation()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=p1))

    def test_rule_5_an_unknown_value_is_refused(self, sup_home):
        self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=fleet.mint_nonce()))

    def test_rule_5_a_missing_value_against_a_v2_claim_is_refused(self, sup_home):
        self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=None))

    def test_a_refusal_writes_neither_the_journal_nor_the_claim(self, sup_home):
        self._hold()
        before = fleet.read_incarnation()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(nonce=fleet.mint_nonce()))
        assert fleet.supervisor_journal_entries() == []
        assert fleet.read_incarnation() == before

    def test_T1_fork_steer_the_sid_may_rotate_under_a_held_generation(self, sup_home, capsys):
        # §5.1: the nonce REPLACES the sid as the continuity key. §5.10(a): at
        # rotation time there is nothing to do -- the body keeps presenting its
        # generation and `session_id` is restamped by the next validated write.
        live = self._hold(sid="sid-before")
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-after", nonce=live)) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["session_id"] == "sid-after", "§6.6: the roster join tracks the acting body"
        assert claim["incarnation_id"] == "inc-me", "no new incarnation"
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["CHECKPOINT"], \
            "no SEIZED"

    def test_a_valid_generation_from_an_unknown_sid_beats_a_matching_sid_without_one(
            self, sup_home, capsys):
        # The two halves of the same sentence, asserted together so neither can
        # be quietly dropped: continuity is sufficient, and the sid is not.
        live = self._hold(sid="sid-holder")
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-stranger", nonce=live)) == 0
        capsys.readouterr()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-holder", nonce=None))

    def test_heartbeat_carries_the_same_continuity_rules_as_checkpoint(self, sup_home, capsys):
        live = self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_heartbeat(SimpleNamespace(sid="sid-me", nonce=None))
        assert fleet.cmd_sup_heartbeat(SimpleNamespace(sid="sid-me", nonce=live)) == 0
        assert "NONCE: " in capsys.readouterr().out


class TestRefusalMessageIsAgentSafe:
    """§5.7's binding constraint on agent-facing output: it must name the
    ambiguity and the escalation, and must NOT name a lever that resolves it
    unilaterally. v1's refusal instructed the refused caller to run a
    read-only view and then act on what it printed -- the refused body may be
    the DIVERGENT one (§5.4(c) cannot prefer either), so naming a lever hands
    it to whichever body reads the message first.

    The human-facing runbook (`skills/fleet/supervisor.md`) is the far side of
    that audience boundary, and it is a convention, not a mechanism."""

    def _refusal(self, sup_home):
        value = fleet.mint_nonce()
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_seq": 4,
                                 "nonce_hash": fleet.nonce_digest(value)})
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(nonce=fleet.mint_nonce()))
        return str(exc.value)

    def test_it_names_the_ambiguity_and_the_escalation(self, sup_home):
        msg = self._refusal(sup_home)
        assert "second body" in msg
        assert "escalate" in msg

    def test_it_names_the_expected_generation_and_the_verb(self, sup_home):
        msg = self._refusal(sup_home)
        assert "4" in msg            # §5.6: the refusal names the expected nonce_seq
        assert "sup-checkpoint" in msg

    @pytest.mark.parametrize("lever", ["sup-status", "INCARNATION", "--force", "rm ", "delete"])
    def test_it_names_no_unilateral_lever(self, sup_home, lever):
        assert lever not in self._refusal(sup_home)

    def test_no_generation_plaintext_reaches_the_error_or_the_stored_state(self, sup_home):
        # T16: the plaintext appears in no error message and in no file.
        value = fleet.mint_nonce()
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_seq": 1,
                                 "nonce_hash": fleet.nonce_digest(value)})
        presented = fleet.mint_nonce()
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(nonce=presented))
        assert presented not in str(exc.value) and value not in str(exc.value)
        assert value not in fleet.incarnation_path().read_text(encoding="utf-8")

    def test_a_delivered_generation_never_reaches_the_git_tracked_journal(self, sup_home, capsys):
        value = fleet.mint_nonce()
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_seq": 1,
                                 "nonce_hash": fleet.nonce_digest(value)})
        fleet.cmd_sup_checkpoint(_ckpt(nonce=value))
        pending = _nonce_of(capsys.readouterr().out)
        journal = fleet.supervisor_journal_path().read_text(encoding="utf-8")
        assert pending not in journal and value not in journal
        assert fleet.incarnation_path().read_text(encoding="utf-8").count(pending) == 0
        # And the anchored entry regex still matches every header written.
        assert len(fleet.supervisor_journal_entries()) == 1


class TestSupStatus:
    def test_json_shape(self, sup_home, capsys):
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-me",
                                 "claimed_at": _iso(NOW), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        args = SimpleNamespace(json=True)
        assert fleet.cmd_sup_status(args) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["goals_active"] is True
        assert data["incarnation"]["incarnation_id"] == "inc-me"
        assert data["heartbeat_age_seconds"] < 60
        assert data["handshake"] is None and data["abort_flag"] is False

    def test_no_claim_human_output(self, sup_home, capsys):
        args = SimpleNamespace(json=False)
        assert fleet.cmd_sup_status(args) == 0
        assert "no claim" in capsys.readouterr().out.lower()


def _rejection_records():
    try:
        text = fleet.nonce_rejection_log_path().read_text(encoding="utf-8")
    except OSError:
        return []
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


class TestRejectionLog:
    """§5.6: "the refusal is the whole product, so it is loud."

    Three things happen on a refused presentation -- a distinct exit code
    (item D), an atomic append to `state/supervisor-nonce-rejections.jsonl`,
    and a doctor flip. This class is the second and third.

    The file's whole purpose is to record the case where TWO BODIES ARE BEING
    REFUSED CONCURRENTLY (§5.9), which is why the append must stay a
    single-syscall `_atomic_append_bytes` and must never degrade to a
    read-modify-write -- the shape that loses exactly the records proving a
    two-body incident."""

    def _hold(self, sid="sid-me", seq=3):
        value = fleet.mint_nonce()
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_seq": seq,
                                 "lineage_id": "lin-x",
                                 "nonce_hash": fleet.nonce_digest(value)})
        return value

    def test_a_refusal_appends_one_record_naming_the_case(self, sup_home):
        self._hold(seq=3)
        presented = fleet.mint_nonce()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=presented))
        recs = _rejection_records()
        assert len(recs) == 1
        r = recs[0]
        assert r["kind"] == "refused"
        assert r["verb"] == "sup-checkpoint"
        assert r["caller_sid"] == "sid-me"
        assert r["expected_seq"] == 3
        assert "ts" in r and "pending_at" in r

    def test_the_record_carries_a_PREFIX_of_the_presented_value_never_the_value(
            self, sup_home):
        # §5.6: `presented_prefix` = first 8 hex of the presented value's
        # sha256. A log that is readable by anything on this box must not be
        # the place a presented generation goes to be recovered -- and the
        # prefix is enough to tell "the same wrong value twice" from "two
        # different wrong values", which is what an operator actually asks.
        live = self._hold()
        presented = fleet.mint_nonce()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=presented))
        r = _rejection_records()[0]
        assert r["presented_prefix"] == fleet.nonce_digest(presented)[:8]
        raw = fleet.nonce_rejection_log_path().read_text(encoding="utf-8")
        assert presented not in raw and live not in raw
        assert fleet.nonce_digest(presented) not in raw, "the full digest is not the prefix"

    def test_a_missing_presentation_records_a_null_prefix_rather_than_crashing(
            self, sup_home):
        self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=None))
        assert _rejection_records()[0]["presented_prefix"] is None

    def test_T7_the_superseded_pending_record_is_a_DIFFERENT_KIND_not_a_refusal(
            self, sup_home, capsys):
        # §5.4(d)/§5.6: `kind` and `pending_at` are what let an operator
        # separate "a TTL fired under a slow body" from "a stale or forged
        # value". Without them the log's two most important cases are
        # indistinguishable -- and the slow body would be read as an attack.
        live = self._hold()
        fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=live))
        p1 = _nonce_of(capsys.readouterr().out)
        claim = fleet.read_incarnation()
        claim["pending_at"] = (datetime.now(timezone.utc) - timedelta(
            seconds=fleet.PENDING_NONCE_TTL_SECONDS + 60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation(claim)
        fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=live))     # P1 -> prior
        capsys.readouterr()
        assert fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=p1)) == 0
        capsys.readouterr()
        recs = _rejection_records()
        assert [r["kind"] for r in recs] == ["superseded-pending"]
        assert recs[0]["verb"] == "sup-checkpoint"

    def test_T17_the_append_is_atomic_and_never_a_read_modify_write(self, sup_home, monkeypatch):
        seen = []
        real = fleet._atomic_append_bytes
        monkeypatch.setattr(fleet, "_atomic_append_bytes",
                            lambda path, data: (seen.append(path), real(path, data))[1])
        # A record already on disk, as a concurrent writer would have left it.
        fleet.nonce_rejection_log_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.nonce_rejection_log_path().write_text(
            json.dumps({"kind": "refused", "ts": fleet.now_iso(), "verb": "other"}) + "\n",
            encoding="utf-8")
        self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=fleet.mint_nonce()))
        assert fleet.nonce_rejection_log_path() in seen
        recs = _rejection_records()
        assert len(recs) == 2, "the pre-existing record was not clobbered"
        assert recs[0]["verb"] == "other"

    def test_T17_the_writer_does_NOT_bound_the_file(self, sup_home):
        # §5.9: v2 said "the writer truncates to the most recent 200 records".
        # Truncation is a read-modify-write needing GENERIC_WRITE, which is the
        # access mode `_atomic_append_bytes`'s own docstring says forfeits the
        # atomic-append guarantee -- and the concurrent-writer case is the one
        # this file exists to record. The cap is enforced out of band, under
        # `fleet_lock`, never by the refused caller (which may be the
        # untrusted body and holds no lock of its own).
        fleet.nonce_rejection_log_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.nonce_rejection_log_path().write_text(
            "".join(json.dumps({"kind": "refused", "ts": fleet.now_iso(),
                                "verb": f"v{i}"}) + "\n" for i in range(250)),
            encoding="utf-8")
        self._hold()
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=fleet.mint_nonce()))
        assert len(_rejection_records()) == 251

    def test_an_unreadable_log_directory_never_turns_a_refusal_into_a_crash(
            self, sup_home, monkeypatch):
        # The record is evidence, not the refusal. If recording fails the
        # caller must still be refused: a body that learns "I could not be
        # logged" instead of "stop and escalate" is the worst of both.
        def boom(path, data):
            raise OSError("disk full")
        monkeypatch.setattr(fleet, "_atomic_append_bytes", boom)
        self._hold()
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_sup_checkpoint(_ckpt(sid="sid-me", nonce=fleet.mint_nonce()))
        assert "escalate" in str(exc.value)


class TestDoctorSeesTheRejections:
    """§5.6 item 3. `_doctor_check_supervisor_claim` hard-codes `ok=True` on
    both returns today, with the docstring *"ALWAYS ok=True -- the nag is
    advisory"*. A rejection is not a nag: it is evidence of a second body, and
    it is the ONE condition that changes. `superseded-pending` is not one --
    it is surfaced as a NOTE."""

    def _log(self, *records):
        fleet.nonce_rejection_log_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.nonce_rejection_log_path().write_text(
            "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    def _claim(self, **extra):
        claim = {"incarnation_id": "inc-me", "session_id": "sid-me",
                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                 "claimed_via": "fresh", "nonce_seq": 1, "lineage_id": "lin-x",
                 "nonce_hash": fleet.nonce_digest(fleet.mint_nonce())}
        claim.update(extra)
        fleet.write_incarnation(claim)

    def _ago(self, seconds):
        return (datetime.now(timezone.utc)
                - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_a_refused_record_in_the_window_flips_ok_to_False(self, sup_home):
        self._claim()
        self._log({"kind": "refused", "ts": self._ago(60), "verb": "sup-checkpoint",
                   "expected_seq": 1})
        name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert name == "supervisor-claim"
        assert ok is False
        assert "refus" in detail.lower()

    def test_a_refused_record_OUTSIDE_the_window_does_not(self, sup_home):
        self._claim()
        self._log({"kind": "refused", "ts": self._ago(25 * 3600), "verb": "sup-checkpoint"})
        _, ok, _ = fleet._doctor_check_supervisor_claim()
        assert ok is True

    def test_a_superseded_pending_record_is_a_NOTE_never_a_failure(self, sup_home):
        # §5.4(d): the slow body is the legitimate one. Flipping the health
        # check on it would train an operator to ignore the one signal that
        # actually means "two bodies".
        self._claim()
        self._log({"kind": "superseded-pending", "ts": self._ago(60), "verb": "sup-heartbeat"})
        _, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True
        assert "superseded-pending" in detail

    def test_a_superseded_note_does_not_mask_a_real_refusal(self, sup_home):
        self._claim()
        self._log({"kind": "superseded-pending", "ts": self._ago(90), "verb": "sup-heartbeat"},
                  {"kind": "refused", "ts": self._ago(60), "verb": "sup-checkpoint"})
        _, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is False
        assert "superseded-pending" in detail

    def test_the_unacknowledged_pending_age_is_surfaced(self, sup_home):
        # §5.4(e)'s silent miss produces NO refusal: a body that only ever
        # presents `live` validates forever, `nonce_seq` never advances, and
        # two bodies of one lineage both validate indefinitely with doctor
        # green. That is strictly worse than a false alarm. This observable is
        # the only thing that distinguishes "nothing is wrong" from "the
        # mechanism has quietly stopped working".
        stale = fleet.PENDING_NONCE_TTL_SECONDS * fleet.NONCE_PENDING_STALE_MULTIPLE + 60
        self._claim(pending_nonce_hash=fleet.nonce_digest(fleet.mint_nonce()),
                    pending_at=self._ago(stale))
        _, ok, detail = fleet._doctor_check_supervisor_claim()
        assert "unacknowledged" in detail.lower()
        assert ok is True, "a degraded detection property is a NOTE, not a health failure"

    def test_a_fresh_pending_is_not_surfaced(self, sup_home):
        self._claim(pending_nonce_hash=fleet.nonce_digest(fleet.mint_nonce()),
                    pending_at=self._ago(30))
        _, _, detail = fleet._doctor_check_supervisor_claim()
        assert "unacknowledged" not in detail.lower()

    def test_the_check_never_raises_on_a_corrupt_log(self, sup_home):
        self._claim()
        fleet.nonce_rejection_log_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.nonce_rejection_log_path().write_text(
            "{not json\n[]\n" + json.dumps({"kind": "refused", "ts": "nonsense"}) + "\n",
            encoding="utf-8")
        name, ok, detail = fleet._doctor_check_supervisor_claim()
        assert name == "supervisor-claim" and isinstance(detail, str)

    def test_goals_dormant_still_short_circuits_to_ok(self, sup_home):
        (sup_home / "supervisor" / "GOALS.md").write_text("SUPERVISOR-DORMANT", encoding="utf-8")
        self._claim()
        self._log({"kind": "refused", "ts": self._ago(60), "verb": "sup-checkpoint"})
        _, ok, detail = fleet._doctor_check_supervisor_claim()
        assert ok is True and "dormant" in detail.lower()

    def test_the_doctor_row_publishes_no_hash(self, sup_home):
        # §5.8's family rule: the check's detail string is operator-facing
        # output on the same surface as the view.
        claim_hash = fleet.nonce_digest(fleet.mint_nonce())
        self._claim(nonce_hash=claim_hash)
        self._log({"kind": "refused", "ts": self._ago(60), "verb": "sup-checkpoint"})
        _, _, detail = fleet._doctor_check_supervisor_claim()
        assert claim_hash not in detail


class TestViewRedaction:
    """T15 (§5.8), the binding build rule.

    §4.8's receipt showed `sup-status --json` emitting `"incarnation": claim`
    and `"handshake": hs` VERBATIM, so every field this spec adds is published
    by a lock-free view unless a redaction step is specified. v1 asserted the
    opposite and its own test would have passed on an implementation that
    published both hashes -- because it asserted only that the NONCE STRING
    was absent, and the nonce string was never in the file.

    So these assert the HASH STRINGS. And they are scoped to the dict-dumping
    paths: `sup-status --json` and `sup-boot`'s stdout. The human line is a
    hand-written f-string over four named fields and has never held a hash;
    asserting there is a test that cannot fail dressed as a regression guard,
    which is the same defect one layer out."""

    def _v2_claim(self):
        live, pending, prior = fleet.mint_nonce(), fleet.mint_nonce(), fleet.mint_nonce()
        claim = {"incarnation_id": "inc-me", "session_id": "sid-me",
                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                 "claimed_via": "fresh", "nonce_seq": 7,
                 "lineage_id": "lin-20260101T000000Z-aaaa",
                 "nonce_hash": fleet.nonce_digest(live),
                 "pending_nonce_hash": fleet.nonce_digest(pending),
                 "pending_at": fleet.now_iso(),
                 "prior_pending_hash": fleet.nonce_digest(prior)}
        fleet.write_incarnation(claim)
        return claim

    def test_no_stored_hash_survives_into_the_json_view(self, sup_home, capsys):
        claim = self._v2_claim()
        fleet.write_handshake("inc-next", "sid-next")
        hs = fleet.read_handshake()
        hs["handoff_token_hash"] = fleet.nonce_digest(fleet.mint_nonce())
        fleet._write_json_atomic(fleet.handshake_path(), hs)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        raw = capsys.readouterr().out
        hashes = [claim["nonce_hash"], claim["pending_nonce_hash"],
                  claim["prior_pending_hash"], hs["handoff_token_hash"]]
        assert len(set(hashes)) == 4, "guard the guard: four distinct hashes were seeded"
        for h in hashes:
            assert h not in raw
        for key in ("nonce_hash", "pending_nonce_hash", "prior_pending_hash",
                    "handoff_token_hash"):
            assert key not in raw

    def test_the_projection_publishes_the_observables_that_replace_them(
            self, sup_home, capsys):
        self._v2_claim()
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        inc = json.loads(capsys.readouterr().out)["incarnation"]
        assert inc["nonce_present"] is True
        assert inc["pending_present"] is True
        assert isinstance(inc["pending_age_seconds"], int)
        assert inc["nonce_seq"] == 7
        assert inc["lineage_id"] == "lin-20260101T000000Z-aaaa"
        assert inc["state"] is None
        assert inc["incarnation_id"] == "inc-me" and inc["session_id"] == "sid-me"

    def test_pending_age_is_null_when_nothing_is_outstanding(self, sup_home, capsys):
        claim = self._v2_claim()
        for k in ("pending_nonce_hash", "pending_at", "prior_pending_hash"):
            claim.pop(k)
        fleet.write_incarnation(claim)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        inc = json.loads(capsys.readouterr().out)["incarnation"]
        assert inc["pending_present"] is False and inc["pending_age_seconds"] is None

    def test_a_released_claim_projects_its_state(self, sup_home, capsys):
        fleet.write_incarnation({"incarnation_id": "inc-old", "lineage_id": "lin-x",
                                 "claimed_via": "fresh", "released_at": fleet.now_iso(),
                                 "released_by_sid": "sid-old", "state": "released"})
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        inc = json.loads(capsys.readouterr().out)["incarnation"]
        assert inc["state"] == "released" and inc["nonce_present"] is False

    def test_the_projection_is_an_ALLOWLIST_so_a_future_field_is_not_auto_published(
            self, sup_home, capsys):
        # A denylist republishes every field a future spec adds, which is
        # exactly how §5.8 came to be written: the view emitted the raw dict
        # and every new field rode along for free. The cost is real and
        # accepted -- a hand-added debugging key stops showing up in
        # `sup-status --json` -- and it is the right side to fail on for a
        # surface whose whole job is to publish supervisor identity.
        claim = self._v2_claim()
        claim["some_future_secret"] = "SHOULD-NOT-BE-PUBLISHED"
        fleet.write_incarnation(claim)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        assert "SHOULD-NOT-BE-PUBLISHED" not in capsys.readouterr().out

    def test_the_handshake_projection_reports_the_token_without_publishing_it(
            self, sup_home, capsys):
        self._v2_claim()
        fleet.write_handshake("inc-next", "sid-next")
        hs = fleet.read_handshake()
        hs["handoff_token_hash"] = fleet.nonce_digest(fleet.mint_nonce())
        fleet._write_json_atomic(fleet.handshake_path(), hs)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        got = json.loads(capsys.readouterr().out)["handshake"]
        assert got["incarnation_id"] == "inc-next" and got["session_id"] == "sid-next"
        assert got["handoff_token_present"] is True

    def test_the_view_stays_a_view(self, sup_home, capsys):
        # terminal-surface doctrine, unchanged by §5.8: no lock, no probe, no
        # write. A projection is a filter on the way out, not a migration.
        claim = self._v2_claim()
        before = fleet.incarnation_path().read_text(encoding="utf-8")
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        capsys.readouterr()
        assert fleet.incarnation_path().read_text(encoding="utf-8") == before
        assert fleet.read_incarnation() == claim

    def test_the_human_form_still_reports_the_claim(self, sup_home, capsys):
        self._v2_claim()
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "inc-me" in out and "sid-me" in out


class TestHandoff:
    def _hold(self, sid="sid-old", inc="inc-old"):
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW),
                                 "claimed_via": "fresh"})

    class _Clock:
        """Injectable monotonic clock; pairing sleep=advance exercises
        dispatch_bg's real 60s join window in zero wall-clock time (same
        pattern as test_native's _FakeClock)."""
        def __init__(self):
            self.t = 0.0

        def __call__(self):
            return self.t

        def advance(self, dt):
            self.t += dt

    def _begin(self, run, sid="sid-old", clock=None, model=None,
               permission_mode=None):
        args = SimpleNamespace(sid=sid, model=model,
                               permission_mode=permission_mode)
        if clock is None:
            return fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                               sleep=lambda s: None)
        return fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=clock.advance, clock=clock)

    @staticmethod
    def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001"):
        """run double. Call order in cmd_sup_handoff_begin is: pre-dispatch
        roster fetch, --bg dispatch, then roster polls by short-id prefix
        (contract G6) -- so the fake is STATEFUL: the successor appears in
        the roster only after the dispatch call has been observed.
        `successor_sid` must start with `short_id` for the join to succeed."""
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

    def test_begin_journals_writes_taskfile_joins_sid(self, sup_home, capsys):
        self._hold()
        run = self._dispatch_then_roster()
        rc = self._begin(run)
        assert rc == 0
        latest_kinds = [e["kind"] for e in fleet.supervisor_journal_entries()]
        assert "HANDOFF-BEGIN" in latest_kinds
        out = capsys.readouterr().out
        assert "SUCCESSOR-SID: succ0001-full" in out and "SUCCESSOR-INC: inc-" in out
        taskfiles = list((sup_home / "state").glob("supervisor-handoff-*.md"))
        assert len(taskfiles) == 1
        body = taskfiles[0].read_text(encoding="utf-8")
        assert "sup-boot --handoff-inc" in body and "NO spawn" in body
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert any(a.startswith("sup|inc-") for a in dispatch)

    def test_begin_pre_snapshot_filters_hostile_sessionid_value(self, sup_home):
        # Roll-up item 3: a dict-valued sessionId in the roster payload (CLI
        # drift / hostile roster) must not raise TypeError from an
        # unhashable value landing in cmd_sup_handoff_begin's own pre_sids
        # exclusion set.
        self._hold()
        state = {"dispatched": False}
        def run(argv, **kw):
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0,
                                       stdout="backgrounded · succ0001 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"},
                       {"sessionId": {"nested": "hostile"}, "status": "busy"}]
            if state["dispatched"]:
                entries.append({"sessionId": "succ0001-full", "status": "busy"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0

    def test_successor_dispatch_passes_fleet_home_cwd(self, sup_home):
        self._hold()
        kwargs_seen = []
        run = self._dispatch_then_roster()
        def wrapped(argv, **kw):
            kwargs_seen.append(kw)
            return run(argv, **kw)
        rc = self._begin(wrapped)
        assert rc == 0
        dispatch_kwargs = next(kw for kw, argv in zip(kwargs_seen, run.calls) if "--bg" in argv)
        assert dispatch_kwargs["cwd"] == str(sup_home)

    # --- Defect A: the sanctioned second dispatch path (SPEC §6) -----------
    #
    # `cmd_sup_handoff_begin` does NOT go through `dispatch_bg` -- it cannot:
    # an incarnation id (`inc-<8>T<6>Z-<4>`) carries uppercase T/Z and so fails
    # `NAME_RE` at the choke point's own guard, and the successor's task file is
    # already written to `state/supervisor-handoff-<inc>.md` and journaled by
    # path, which `task_file_path(name)` would duplicate. The tests below pin
    # the contract that makes the second path SANCTIONED rather than a bypass:
    # it must carry the same hook wiring and the same process-identity hygiene
    # the choke point carries.

    def test_successor_dispatch_carries_instance_settings(self, sup_home):
        """Defect A: a successor launched WITHOUT --settings gets none of
        fleet's hooks (Stop outcome, Stop mailbox, PostToolUse mailbox,
        PostCompact journal). All four degrade to sid-keyed writes when the
        session has no registry record, so a successor genuinely benefits --
        and its sid is exactly the handle sup-handoff-complete/-abort use."""
        self._hold()
        run = self._dispatch_then_roster()
        assert self._begin(run) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert "--settings" in dispatch
        assert (dispatch[dispatch.index("--settings") + 1]
                == fleet.instance_settings_path().as_posix())

    def test_successor_dispatch_refused_without_rendered_settings(self, sup_home):
        """Same doctrine as cmd_spawn's `_require_instance_settings`: claude
        silently ignores a --settings path that does not exist, so a missing
        instance would put the hookless successor back with no error anywhere.
        Fail closed BEFORE the journal entry and the task file are written."""
        self._hold()
        fleet.instance_settings_path().unlink()
        run = self._dispatch_then_roster()
        with pytest.raises(fleet.FleetCliError, match="worker settings instance missing"):
            self._begin(run)
        assert not any("--bg" in c for c in run.calls)
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == []
        assert list((sup_home / "state").glob("supervisor-handoff-*.md")) == []

    def test_successor_dispatch_always_carries_a_permission_mode(self, sup_home):
        """B4/D6: `dispatch_bg` ends every worker argv with `mode_flags(mode)`
        and every worker defaults to `dontask`. The successor emitted a
        permission flag ONLY when the operator typed `--permission-mode`
        (argparse default None), so the default path ran under claude's own
        default mode -- and the successor's bootstrap opens with a Bash call,
        which in a headless `--bg` session hangs forever on an unanswerable
        permission prompt. That is the T12 wedge class this repo already paid
        for once."""
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None)
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        expected = fleet.mode_flags(fleet.SUCCESSOR_DEFAULT_MODE)
        assert expected, "the successor default mode must emit at least one flag"
        for flag in expected:
            assert flag in dispatch
        # same default the worker choke point uses -- not a bespoke one
        assert fleet.SUCCESSOR_DEFAULT_MODE in fleet.MODE_FLAGS

    def test_explicit_permission_mode_overrides_the_successor_default(self, sup_home):
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode="plan")
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert dispatch[dispatch.index("--permission-mode") + 1] == "plan"
        # exactly one mode opinion on the argv, never the default alongside it
        assert dispatch.count("--permission-mode") == 1
        assert "--dangerously-skip-permissions" not in dispatch

    def test_successor_mode_uses_one_vocabulary_everywhere(self, sup_home):
        """G3: the explicit branch took a RAW CLAUDE mode string while the
        default branch took a FLEET mode name through `mode_flags()` -- two
        vocabularies for one argument. Both branches now speak fleet mode
        names, so `--permission-mode bypass` reaches the argv as
        `--dangerously-skip-permissions`, exactly as `fleet spawn --mode
        bypass` does. A raw claude spelling is refused by argparse rather than
        silently forwarded."""
        self._hold()
        run = self._dispatch_then_roster()
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode="bypass")
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=lambda s: None) == 0
        dispatch = next(c for c in run.calls if "--bg" in c)
        assert dispatch[-2:] != ["--permission-mode", "bypass"]
        assert "--dangerously-skip-permissions" in dispatch
        assert "--permission-mode" not in dispatch

    def test_successor_permission_mode_is_constrained_to_fleet_mode_names(self):
        """G3, the enforcement half: the parser must reject a vocabulary the
        dispatch cannot speak. Without `choices`, `--permission-mode acceptEdits`
        parsed fine and then raised ValueError deep inside `mode_flags`."""
        parser = fleet.build_parser()
        args = parser.parse_args(["sup-handoff-begin", "--permission-mode", "accept"])
        assert args.permission_mode == "accept"
        with pytest.raises(SystemExit):
            parser.parse_args(["sup-handoff-begin", "--permission-mode", "acceptEdits"])

    def test_missing_claude_refuses_before_journal_and_taskfile(self, sup_home):
        """B5: `resolve_claude_executable` is the same class of pre-flight as
        `_require_instance_settings` -- a missing external prerequisite. It ran
        AFTER the journal write, the task-file write and the prior abort flag's
        deletion, and raises `ClaudeNotFoundError` with no `_abort_flag` guard,
        so a `claude` that dropped off PATH left HANDOFF-BEGIN journaled with no
        successor and nothing for doctor to see -- contradicting the docstring's
        promise that both failure paths raise the flag."""
        self._hold()
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError, match="claude executable not found"):
            fleet.cmd_sup_handoff_begin(SimpleNamespace(sid="sid-old", model=None,
                                                        permission_mode=None),
                                        which=lambda _n: None, run=run,
                                        sleep=lambda s: None)
        assert fleet.supervisor_journal_entries() == []
        assert list((sup_home / "state").glob("supervisor-handoff-*.md")) == []
        assert calls == []

    def test_missing_claude_leaves_a_prior_abort_flag_intact(self, sup_home):
        """The refusal must not consume the previous handoff's evidence: the
        `unlink()` of the abort flag sits inside the lock, after the pre-flights."""
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(),
                                 {"reason": "successor-doa", "holder": "inc-older"})
        with pytest.raises(fleet.FleetCliError, match="claude executable not found"):
            fleet.cmd_sup_handoff_begin(SimpleNamespace(sid="sid-old", model=None,
                                                        permission_mode=None),
                                        which=lambda _n: None,
                                        run=lambda *a, **k: SimpleNamespace(
                                            returncode=0, stdout="[]", stderr=""),
                                        sleep=lambda s: None)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"

    def test_successor_dispatch_uses_worker_env(self, sup_home, monkeypatch):
        """§5.1 provenance: without `env=_worker_env(name)` the successor
        inherits the OLD supervisor's CLAUDE_CODE_SESSION_ID. `cmd_sup_boot`
        reads exactly that variable (@caller_sid) and writes it into the
        HANDSHAKE, so an inherited value makes the successor hand back the old
        holder's sid -- and `sup-handoff-complete --expect-sid <successor_sid>`
        then refuses on a mismatch, wedging the handoff. Same reason
        `dispatch_bg` strips it at every worker launch."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-old")
        self._hold()
        kwargs_seen = []
        run = self._dispatch_then_roster()
        def wrapped(argv, **kw):
            kwargs_seen.append(kw)
            return run(argv, **kw)
        assert self._begin(wrapped) == 0
        env = next(kw for kw, argv in zip(kwargs_seen, run.calls) if "--bg" in argv)["env"]
        assert "CLAUDE_CODE_SESSION_ID" not in env
        assert env["FLEET_WORKER"].startswith("sup|inc-")
        assert env["PATH"] == os.environ["PATH"]  # inherited env, not a bare one

    def test_successor_join_uses_short_id_prefix(self, sup_home, capsys):
        """ai-title collision hazard: TWO fresh roster entries share the
        successor's display name; only the sid whose prefix matches the
        dispatch-printed short id may be joined."""
        self._hold()
        state = {"dispatched": False}
        def run(argv, **kw):
            if "--bg" in argv:
                state["dispatched"] = True
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc999 · sup\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["dispatched"]:
                entries += [
                    {"sessionId": "abc999-genuine", "status": "busy", "name": "sup|collided|successor"},
                    {"sessionId": "def000-imposter", "status": "busy", "name": "sup|collided|successor"},
                ]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        assert "SUCCESSOR-SID: abc999-genuine" in capsys.readouterr().out

    def test_join_falls_back_to_name_join_when_short_id_unparseable(self, sup_home, capsys):
        self._hold()
        state = {"name": None}
        def run(argv, **kw):
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries.append({"sessionId": "sid-fallback-joined", "status": "busy",
                                "name": state["name"]})
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        out = capsys.readouterr().out
        assert "falling back to name join (G6 fallback)" in out
        assert "SUCCESSOR-SID: sid-fallback-joined" in out

    def test_name_join_fallback_filters_hostile_sessionid_value(self, sup_home, capsys):
        # Debt roll-up item 2, fourth grepped site: the G6 name-join
        # fallback's `not in pre_sids` membership test hashes the sessionId
        # value -- a dict-valued one (CLI drift / hostile roster) raised
        # TypeError instead of being filtered.
        self._hold()
        state = {"name": None}
        def run(argv, **kw):
            if "--bg" in argv:
                state["name"] = next(a for a in argv if a.startswith("sup|"))
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            entries = [{"sessionId": "sid-old", "status": "busy"}]
            if state["name"]:
                entries += [
                    {"sessionId": {"nested": "hostile"}, "status": "busy",
                     "name": state["name"]},
                    {"sessionId": "sid-fallback-joined", "status": "busy",
                     "name": state["name"]},
                ]
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        rc = self._begin(run)
        assert rc == 0
        assert "SUCCESSOR-SID: sid-fallback-joined" in capsys.readouterr().out

    # REMOVED in the posix/provider reconcile merge: the three
    # `dispatch_bg` wedge-retry tests from 351d180/51aaefe
    # (test_wedge_retry_husk_never_bound_by_name_join,
    # test_all_husk_name_join_reports_doa_never_binds_dead,
    # test_wedge_cleaned_then_failed_redispatch_flags_dispatch_failed).
    # They pin behaviour of a handoff path that lost this merge: their
    # premise is dispatch_bg's INTERNAL single wedge-retry emitting a
    # second `--bg` under the same rendered name. cmd_sup_handoff_begin is
    # the sanctioned second dispatch path (SPEC 6) and issues exactly ONE
    # `--bg` per call with a per-incarnation-unique name, so no retry husk
    # can share a name with a live successor and the scenarios are
    # unreachable, not merely unasserted. Nothing they covered is left
    # untested on this path: the single dispatch's failure and DOA
    # branches are pinned by test_begin_doa_when_successor_never_appears
    # and the dispatch-failure tests below.

    def test_begin_doa_when_successor_never_appears(self, sup_home, capsys):
        # fake clock (sleep advances it): dispatch_bg's real 60s join window
        # runs in zero wall-clock time
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc · sup\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run, clock=self._Clock())
        assert rc == 1
        assert "DOA" in capsys.readouterr().out

    def test_handoff_begin_doa_writes_abort_flag(self, sup_home):
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="backgrounded · abc · sup\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run, clock=self._Clock())
        assert rc == 1
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"
        assert flag["successor_sid"] is None
        assert flag["successor_short_id"] == "abc"
        assert flag["holder"] == "inc-old"

    def test_handoff_begin_doa_via_name_fallback_writes_abort_flag(self, sup_home, monkeypatch):
        monkeypatch.setattr(fleet, "SUPERVISOR_ROSTER_VERIFY_SECONDS", 0.05)
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0, stdout="launched (no short id token)\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        rc = self._begin(run)
        assert rc == 1
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "successor-doa"
        assert flag["successor_short_id"] is None

    def test_handoff_begin_dispatch_failure_writes_abort_flag(self, sup_home):
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                raise OSError("spawn failed")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError):
            self._begin(run)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "dispatch-failed"
        assert flag["successor_sid"] is None
        assert flag["successor_short_id"] is None
        assert flag["holder"] == "inc-old"

    def test_handoff_begin_dispatch_nonzero_exit_writes_abort_flag(self, sup_home):
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        with pytest.raises(fleet.FleetCliError):
            self._begin(run)
        flag = json.loads(fleet.handoff_abort_flag_path().read_text(encoding="utf-8"))
        assert flag["reason"] == "dispatch-failed"

    def test_handoff_begin_success_leaves_no_abort_flag(self, sup_home):
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        assert not fleet.handoff_abort_flag_path().exists()

    def test_begin_refused_for_non_holder(self, sup_home):
        self._hold(sid="sid-holder")
        with pytest.raises(fleet.FleetCliError):
            self._begin(self._dispatch_then_roster(), sid="sid-imposter")

    def test_complete_transfers_on_dual_match(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        assert fleet.cmd_sup_handoff_complete(args) == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == "inc-succ" and claim["session_id"] == "sid-new"
        assert claim["claimed_via"] == "handoff"
        assert fleet.read_handshake() is None
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "HANDOFF-COMPLETE" and latest["inc"] == "inc-old"

    def test_complete_refuses_on_inc_mismatch(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-WRONG", "sid-new")
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"
        assert fleet.read_handshake() is not None

    def test_complete_refuses_when_no_handshake(self, sup_home):
        self._hold()
        args = SimpleNamespace(sid="sid-old", expect_inc="inc-succ", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_complete(args)

    def test_abort_stops_successor_flags_and_resumes(self, sup_home, capsys):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        stopped = []
        def run(argv, **kw):
            stopped.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        # S1 fix (final wave): routes through _stop_native_session -- tries
        # the SHORT job-ref ("sid", the first hyphen segment) first, not the
        # raw full sid.
        assert stopped and stopped[0][-2:] == ["stop", fleet._native_job_ref("sid-new")]
        assert fleet.read_handshake() is None
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"
        assert fleet.read_incarnation()["incarnation_id"] == "inc-old"  # old resumes duty

    def test_abort_reports_failed_stop_but_still_flags(self, sup_home, capsys):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-gone")
        def run(argv, **kw):
            return SimpleNamespace(returncode=1, stdout="", stderr="no such session")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-gone")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert "stop failed" in capsys.readouterr().out.lower()

    def test_handoff_abort_refuses_on_handshake_sid_mismatch(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-real-successor")
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-WRONG-target")
        with pytest.raises(fleet.FleetCliError, match="does not match HANDSHAKE sid"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped
        assert not fleet.handoff_abort_flag_path().exists()   # no flag written
        assert fleet.read_handshake() is not None   # handshake untouched
        kinds = [e["kind"] for e in fleet.supervisor_journal_entries()]
        assert "HANDOFF-ABORT" not in kinds

    def test_handoff_abort_proceeds_on_matching_handshake(self, sup_home):
        self._hold()
        fleet.write_handshake("inc-succ", "sid-new")
        run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()
        assert fleet.read_handshake() is None

    def test_handoff_abort_proceeds_on_absent_handshake_with_matching_flag(self, sup_home):
        # Finding 2 fix: with no HANDSHAKE, the recorded limbo successor in
        # the abort flag (written by sup-handoff-begin on DOA/dispatch-fail)
        # is the only evidence that makes an absent-HANDSHAKE abort legit.
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": "sid-whatever", "successor_short_id": None,
            "holder": "inc-old"})
        run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-whatever")
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run) == 0
        assert fleet.handoff_abort_flag_path().exists()

    def test_handoff_abort_refuses_on_absent_handshake_with_mismatched_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": "sid-recorded", "successor_short_id": None,
            "holder": "inc-old"})
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-typo")
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_handoff_abort_refuses_on_absent_handshake_and_no_flag(self, sup_home):
        self._hold()
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-whatever")
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_handoff_abort_refuses_on_none_successor_sid_matching_none_flag(self, sup_home):
        # Roll-up item 8: an abort flag recorded with successor_sid=None
        # (the dispatch-failed shape) must not be treated as matching an
        # args.successor_sid that is itself None -- unreachable via the CLI
        # (argparse required=True) but must refuse, not proceed into
        # `claude stop None`.
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "successor-doa",
            "successor_sid": None, "successor_short_id": None,
            "holder": "inc-old"})
        calls = []
        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        args = SimpleNamespace(sid="sid-old", successor_sid=None)
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=run)
        assert not calls   # nothing stopped

    def test_begin_clears_previous_abort_flag(self, sup_home):
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"stale": True})
        self._begin(self._dispatch_then_roster())
        assert not fleet.handoff_abort_flag_path().exists()

    def test_handoff_timeout_drill_end_to_end(self, sup_home):
        """Spec §4 failure branch: begin -> successor never handshakes ->
        complete refuses -> abort stops the limbo successor and old resumes.

        Post-Finding-2-fix: the roster join succeeded here, so begin's DOA/
        dispatch-failure abort-flag paths never fire and HANDSHAKE is never
        written (that's the whole point of the drill). Under the new
        absent-HANDSHAKE rule, abort itself now needs recorded evidence
        before it will act -- simulate the operator recording the sid
        printed as SUCCESSOR-SID by begin (external verification is the
        documented alternative when no flag exists, per the abort
        docstring)."""
        self._hold()
        rc = self._begin(self._dispatch_then_roster())
        assert rc == 0
        args = SimpleNamespace(sid="sid-old",
                               expect_inc="inc-whatever", expect_sid="sid-new")
        with pytest.raises(fleet.FleetCliError):   # no HANDSHAKE was written
            fleet.cmd_sup_handoff_complete(args)
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "operator-recorded",
            "successor_sid": "sid-new", "successor_short_id": None,
            "holder": "inc-old"})
        def stop_run(argv, **kw):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        abort = SimpleNamespace(sid="sid-old", successor_sid="sid-new")
        assert fleet.cmd_sup_handoff_abort(abort, which=_fake_which, run=stop_run) == 0
        assert fleet.read_incarnation()["session_id"] == "sid-old"


class TestSuccessorInterpreterIsPortable:
    """The successor bootstrap must invoke the interpreter THIS incarnation
    is running, never the `py -3.13` launcher -- `py` is Windows-only, so a
    hardcoded one makes supervisor handoff unrunnable on macOS/Linux.

    Unpinned until now: a reconcile fault-injection sweep reverted this to
    `py -3.13` and the whole suite stayed green on both platforms, which is
    exactly how a portability fix silently regresses."""

    def test_body_uses_this_interpreter_not_the_windows_launcher(self, sup_home):
        import sys
        body = fleet._render_successor_task("inc-new", "inc-old")
        assert Path(sys.executable).as_posix() in body
        assert "py -3.13" not in body

    def test_every_rendered_command_is_the_same_interpreter(self, sup_home):
        # The body issues several commands (sup-boot, sup-status, ...); a
        # partial fix that portably renders only the first one still leaves
        # the successor wedged at step 3 on a non-Windows host.
        import sys
        body = fleet._render_successor_task("inc-new", "inc-old")
        py = Path(sys.executable).as_posix()
        invocations = re.findall(r'"([^"]*)"\s+\S*fleet\.py', body)
        assert invocations, "no rendered fleet.py invocation found"
        assert all(i == py for i in invocations), invocations


class TestNag:
    def test_none_when_goals_absent(self, sup_home):
        fleet.goals_path().unlink()
        assert fleet.supervisor_status_line() is None

    def test_none_when_dormant_token(self, sup_home):
        fleet.goals_path().write_text("# Goals\nSUPERVISOR-DORMANT\n", encoding="utf-8")
        assert fleet.supervisor_status_line() is None

    def test_nags_when_no_claim(self, sup_home):
        line = fleet.supervisor_status_line()
        assert line is not None and "no claim" in line

    def test_nags_when_heartbeat_stale(self, sup_home):
        stale = datetime.now(timezone.utc) - timedelta(hours=2)
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": _iso(stale), "heartbeat_at": _iso(stale),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "stale" in line

    def test_informational_when_fresh(self, sup_home):
        fleet.write_incarnation({"incarnation_id": "inc-x", "session_id": "s",
                                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        line = fleet.supervisor_status_line()
        assert "inc-x" in line and "stale" not in line and "no claim" not in line


class TestSupervisorDoctorChecks:
    def test_claim_check_is_always_advisory_pass(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_claim()
        assert name == "supervisor-claim" and ok is True
        assert "no claim" in msg

    def test_handoff_check_fails_on_abort_flag(self, sup_home):
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {"aborted_at": "x"})
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "abort" in msg.lower()

    def test_handoff_check_fails_on_stale_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        import os as _os, time as _time
        old = _time.time() - fleet.SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS - 60
        _os.utime(fleet.handshake_path(), (old, old))
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is False and "stale" in msg.lower()

    def test_handoff_check_passes_on_fresh_handshake(self, sup_home):
        fleet.write_handshake("inc-x", "sid-x")
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True and "in flight" in msg

    def test_handoff_check_passes_clean(self, sup_home):
        name, ok, msg = fleet._doctor_check_supervisor_handoff()
        assert ok is True


class TestSupervisorStatusLine:
    """`supervisor_status_line()` was only ever asserted through the
    SessionStart hook's `_build_context()`. The hook is gone (D7,
    docs/specs/terminal-surface.md) and the function is not: the statusline
    and `sup-status` still render it. Tested directly, so its one remaining
    consumer-independent behaviour keeps a pin."""

    def test_returns_a_supervisor_line_when_a_claim_is_stale(self, sup_home):
        line = fleet.supervisor_status_line()
        assert line and line.startswith("SUPERVISOR:")


class TestDispatchPathsAreDocumented:
    """Defect A regression: SPEC §6 claimed "one choke point for every --bg
    launch" while `bin/fleet.py` has always had TWO argv builders. The claim is
    now scoped to worker launches and the second path is named; these tests go
    RED if either the code grows a third path or the SPEC text drops the
    correction."""

    REPO = Path(__file__).resolve().parents[1]
    # B3 + G1: the guard SPEC §6.1 leans on has been evaded twice. It began as
    # `r'^\s*argv = \[exe, "--bg"'` -- one spelling -- and injection I16 walked
    # past it with `cmd = [claude_exe, "--bg", ...]`. The B3 widening to
    # `r'\[[^\]\n]*"--bg"'` still could not cross a newline, so a builder whose
    # list literal wraps (`argv = [\n    exe, "--bg", ...`) walked past that.
    # Dropping the newline exclusion catches every spelling; verified still
    # exactly 2 on the real source, and 3 under each evasion in
    # `test_shape_guard_catches_every_third_builder_spelling`.
    ARGV_BUILDER_RE = re.compile(r'\[[^\]]*"--bg"')
    # Every builder that legitimately exists, by the function that owns it.
    KNOWN_BUILDERS = ("dispatch_bg", "cmd_sup_handoff_begin")

    def _source(self):
        return (self.REPO / "bin" / "fleet.py").read_text(encoding="utf-8")

    def _spec(self):
        return (self.REPO / "docs" / "SPEC.md").read_text(encoding="utf-8")

    def _section(self):
        spec = self._spec()
        return spec.split("## 6. Dispatch contract", 1)[1].split("\n## 7.", 1)[0]

    def _subsection_61(self):
        """D3: §6.1 ONLY. `_section()` spans §6 through §7, and §6's own lead
        sentence and argv block already contain `cmd_sup_handoff_begin` and
        `--settings` -- so a test asserting those against `_section()` stayed
        green when the reviewer deleted §6.1 wholesale, while SPEC §6.1 claimed
        the test 'fails if this subsection stops naming the path'. A spec
        sentence asserting protection that does not exist is worse than none."""
        return self._section().split("### 6.1", 1)[1]

    def test_exactly_two_bg_argv_builders(self):
        """Not a fix pin -- a shape guard. A THIRD argv builder means the
        SPEC's enumeration is stale again and must be extended."""
        assert len(self.ARGV_BUILDER_RE.findall(self._source())) == 2

    @pytest.mark.parametrize("label,builder", [
        ("plain", '\ndef _third(exe):\n    argv = [exe, "--bg", "-n", "p"]\n    return argv\n'),
        ("renamed", '\ndef _third(x):\n    cmd = [x, "--bg", "-n", "p"]\n    return cmd\n'),
        ("augmented", '\ndef _third(exe):\n    argv = [exe]\n    argv += ["--bg", "-n", "p"]\n    return argv\n'),
        ("multiline", '\ndef _third(exe):\n    argv = [\n        exe, "--bg",\n        "-n", "p",\n    ]\n    return argv\n'),
    ])
    def test_shape_guard_catches_every_third_builder_spelling(self, label, builder):
        """G1: this guard has now been evaded twice -- B3 (`cmd = [claude_exe,`
        walked past the `argv = [exe,` spelling) and G1 (a builder whose list
        literal wraps across a newline walked past `[^\\]\\n]*`). It is the guard
        SPEC §6.1 leans on to keep the dispatch enumeration from going stale a
        second time, so every spelling a real third builder could take is
        pinned here rather than discovered by the next reviewer."""
        source = self._source()
        assert len(self.ARGV_BUILDER_RE.findall(source)) == 2, "baseline"
        assert len(self.ARGV_BUILDER_RE.findall(source + builder)) == 3, label

    def test_both_bg_argv_builders_live_in_the_documented_functions(self):
        """B3, the other half: two builders is only reassuring if they are the
        two §6.1 names. A third builder that REPLACED one of these would keep
        the count at 2."""
        source = self._source()
        owners = []
        for m in self.ARGV_BUILDER_RE.finditer(source):
            head = source[:m.start()]
            defs = re.findall(r"^def (\w+)", head, re.M)
            owners.append(defs[-1] if defs else None)
        assert sorted(owners) == sorted(self.KNOWN_BUILDERS)

    def test_spec_lead_sentence_scopes_the_choke_point(self):
        """The pre-fix lead read 'Every native launch ... funnels through one
        choke point', which is false: the successor never did. It must now
        scope to WORKER launches and say how many builders exist."""
        # drop the remainder of the "## 6. Dispatch contract ..." heading line
        body = self._section().split("\n", 1)[1]
        lead = next(l for l in body.splitlines() if l.strip()).lower()
        assert "worker" in lead
        assert "two" in lead and "argv builder" in lead

    def test_spec_names_the_successor_dispatch_path(self):
        """D3: asserted against §6.1 alone, and against the tokens that carry
        the subsection's load -- so deleting or hollowing it goes RED."""
        sub = self._subsection_61()
        assert "cmd_sup_handoff_begin" in sub
        for token in ("--settings", "_worker_env", "_require_instance_settings",
                      "supervisor-handoff-", "NAME_RE"):
            assert token in sub, token

    def test_spec_61_records_the_mode_flag_decision(self):
        """B4/D6: §6.1's parity enumeration claimed the path carries what the
        choke point carries and listed two deliberate omissions, silently
        omitting the third and only hazardous asymmetry."""
        sub = self._subsection_61()
        assert "mode" in sub.lower()
        assert "SUCCESSOR_DEFAULT_MODE" in sub

    def test_spec_61_keeps_the_unobserved_hedge(self):
        """D7: the branch's own docstring and commit message hedge the daemon
        env-propagation claim; the SPEC stated it flatly. The spec is the
        artifact a future builder trusts -- it must be the more careful one."""
        sub = self._subsection_61()
        assert "UNVERIFIED" in sub or "UNOBSERVED" in sub

    def test_spec_12_does_not_claim_the_successor_uses_dispatch_bg(self):
        """D2: §12 still read 'old dispatches a claim-pending successor via
        `dispatch_bg`' -- false, and false in the same document whose §6.1
        exists to explain why it cannot be `dispatch_bg`. The branch corrected
        §6 and left the other half of the same inaccuracy standing."""
        spec = self._spec()
        section12 = spec.split("## 12. Supervisor protocol", 1)[1].split("\n## 13.", 1)[0]
        assert "via `dispatch_bg`" not in section12
        assert "§6.1" in section12


class TestOperatorGatesFile:
    """The operator asked (2026-07-21) that ratification decisions be put to
    them BEFORE a session starts any work. That used to be enforced by the
    SessionStart hook, which injected the open gates into every session --
    including every session in every unrelated project on the machine, which
    is why the hook is gone (D7, docs/specs/terminal-surface.md, 2026-07-22).

    The ask now lands one step later: step 1 of the `fleet` skill's startup
    ritual reads this file, so a session that has chosen to manage the fleet
    still meets the gates before doing anything. Nothing machine-parses the
    file any more, so what survives here is the FORMAT pin -- a reader (human
    or model) following the ritual needs the open/settled distinction to be
    unambiguous, and a drift that blurs it is invisible from any one gate."""

    def test_the_shipped_gates_file_parses_and_has_open_items(self):
        repo = Path(__file__).resolve().parents[1]
        text = (repo / "docs" / "OPERATOR-GATES.md").read_text(encoding="utf-8")
        open_gates = [ln for ln in text.splitlines() if ln.strip().startswith("- [ ]")]
        assert open_gates, "no open gates parse out of the shipped file"
        for ln in open_gates:
            assert ln.strip().endswith("?"), f"a gate must be a question: {ln[:80]}"

    def test_the_skill_startup_ritual_still_routes_the_operator_to_the_gates(self):
        """The hook was the enforcement; the skill is now the only one. If the
        ritual stops naming the gates file, the 2026-07-21 ask is silently
        unmet and no other test notices."""
        repo = Path(__file__).resolve().parents[1]
        skill = (repo / "skills" / "fleet" / "SKILL.md").read_text(encoding="utf-8")
        ritual = skill.split("## Startup ritual", 1)[1].split("\n## ", 1)[0]
        assert "OPERATOR-GATES.md" in ritual
