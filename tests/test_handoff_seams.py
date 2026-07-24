"""Handoff-path seams found LIVE during the 2026-07-24 supervisor succession
(inc-651f -> inc-7d7d, two stillborn attempts before the third took), plus the
fix wave the dual-lens gate ordered on the first cut of that fix.

WAVE 1 recorded the successor a handoff dispatched, which made a stillborn
handoff abortable for the first time. WAVE 2 (this file's contract) fixes what
a slot-shaped record could not express:

  R1 pending successors are a COLLECTION. Three begins in sixteen minutes is
     the real sequence; a single marker meant the second begin destroyed the
     first one's record, so the older successors matched nothing and produced
     the EXACT pre-fix refusal. The fix for the incident resurrected it.
  R2 the sweep FAILS CLOSED. A successor's whole prompt is `Read <task_path>
     and follow it exactly`, so deleting that file under a booting body does
     not crash anything -- it silently strips the body of its only input.
     Nothing is swept without a readable claim, nothing named by any pending
     entry, nothing younger than the handoff timeout, nothing of unknown age.
  R3 entries resolve by EVIDENCE or by TIME. An entry that never recorded a
     sid used to be immortal: no HANDSHAKE, no sid, no flag -- every abort arm
     dead at once. Past the timeout it is `resolvable-stale` and
     `--successor-inc` retires it, reporting honestly that nothing was stopped.
  R4 the last entry retiring takes `handoff_token_hash` with it: a stranded
     plaintext token still VALIDATES while that hash stands.
  R5 claim transitions carry the pending set forward -- a predecessor dying
     mid-handoff is the exact failure the succession path exists for.
  R6 the incarnation id is a path component reached from successor-controlled
     input; confine the path, validate the shape, and do not swallow OSError.
  R7 the abort flag arm is gone: no begin path ever wrote a sid into it.
  R8 six mutations survived the wave-1 suite. Each has a test here.
"""
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parents[1]
T = fleet.SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME, same shape as tests/test_supervisor.py's."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n",
                                                     encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                             encoding="utf-8")
    return tmp_path


def _fake_which(name):
    return "C:/fake/claude.cmd"


def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001"):
    """Stateful `subprocess.run` double: the successor appears in the roster
    only after the `--bg` dispatch has been observed (contract G6 join)."""
    assert successor_sid.startswith(short_id)
    state = {"dispatched": False}
    def run(argv, **kw):
        if "--bg" in argv:
            state["dispatched"] = True
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded \u00b7 {short_id} \u00b7 sup\n",
                                   stderr="")
        entries = [{"sessionId": "sid-old", "status": "busy"}]
        if state["dispatched"]:
            entries.append({"sessionId": successor_sid, "status": "busy"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


def _never_joins(short_id="nope0001"):
    """Dispatch succeeds, the successor never appears in the roster: the DOA
    branch, which records an entry with NO sid."""
    def run(argv, **kw):
        if "--bg" in argv:
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded \u00b7 {short_id} \u00b7 sup\n",
                                   stderr="")
        return SimpleNamespace(returncode=0,
                               stdout=json.dumps([{"sessionId": "sid-old"}]), stderr="")
    return run


class _Clock:
    """Injectable monotonic clock; pairing `sleep=advance` runs the real join
    window in zero wall-clock time."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _stop_ok(calls=None):
    def run(argv, **kw):
        if calls is not None:
            calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def _age_entry(inc, seconds):
    """Back-date a REAL begin-produced entry's `minted_at`. The entry still
    comes from `begin` (R8: no hand-built markers); only the clock moves."""
    claim = fleet.read_incarnation()
    for entry in fleet.handoff_pending_entries(claim):
        if entry["successor_inc"] == inc:
            entry["minted_at"] = fleet._iso(
                fleet.datetime.now(fleet.timezone.utc) - fleet.timedelta(seconds=seconds)
            ) if hasattr(fleet, "_iso") else (
                fleet.datetime.now(fleet.timezone.utc)
                - fleet.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fleet.write_incarnation(claim)
    return claim


def _age_file(path, seconds):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))
    return path


def _orphan(sup_home, inc, age_seconds=2 * T):
    """A `supervisor-handoff-<inc>.md` belonging to no claim and no entry."""
    path = sup_home / "state" / f"supervisor-handoff-{inc}.md"
    path.write_text("TOKEN: plaintext-bearer-secret\n", encoding="utf-8")
    return _age_file(path, age_seconds)


DEAD_INC_A = "inc-20260724T045450Z-0dea"
DEAD_INC_B = "inc-20260724T081049Z-754f"


class _HandoffBase:
    """A live claim-holding predecessor, plus `begin` driven to a chosen
    outcome. Generations are captured off begin's own stdout, exactly where a
    real body reads them."""

    def _hold(self, sid="sid-old", inc="inc-20260724T000000Z-0old"):
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})

    def _begin(self, capsys, run=None, sid="sid-old", nonce=None, clock=None):
        """Returns `(rc, generation)`. A legacy first-contact claim is upgraded
        by begin and its generation delivered on stdout (§9); a claim that is
        already live gets `notices == []` and prints nothing, so the caller
        keeps presenting the value it already holds."""
        args = SimpleNamespace(sid=sid, model=None, permission_mode=None, nonce=nonce)
        kw = {"sleep": (clock.advance if clock else (lambda s: None))}
        if clock is not None:
            kw["clock"] = clock
        rc = fleet.cmd_sup_handoff_begin(args, which=_fake_which,
                                         run=run or _dispatch_then_roster(), **kw)
        out = capsys.readouterr().out
        delivered = re.findall(r"^NONCE: (?!unchanged)(\S+)$", out, re.M)
        return rc, (delivered[0] if delivered else nonce)

    def _begin_doa(self, capsys, sid="sid-old", nonce=None, short_id="nope0001"):
        clock = _Clock()
        rc, gen = self._begin(capsys, run=_never_joins(short_id), sid=sid,
                              nonce=nonce, clock=clock)
        assert rc == 1
        return gen

    def _incs(self):
        return [e["successor_inc"]
                for e in fleet.handoff_pending_entries(fleet.read_incarnation())]

    def _abort(self, run=None, sid="sid-old", nonce=None, successor_sid=None,
               successor_inc=None):
        args = SimpleNamespace(sid=sid, nonce=nonce, successor_sid=successor_sid,
                               successor_inc=successor_inc)
        return fleet.cmd_sup_handoff_abort(args, which=_fake_which,
                                           run=run or _stop_ok())


class TestPendingSuccessorsAreACollection(_HandoffBase):
    """R1 -- the wave-1 slot destroyed the record of every earlier attempt."""

    def test_begin_appends_an_entry_with_the_joined_sid(self, sup_home, capsys):
        self._hold()
        rc, _gen = self._begin(capsys)
        assert rc == 0
        entries = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert len(entries) == 1
        entry = entries[0]
        assert entry["successor_inc"].startswith("inc-")
        assert entry["successor_sid"] == "succ0001-full"
        assert entry["task_file"].endswith(
            f"supervisor-handoff-{entry['successor_inc']}.md")
        assert entry["minted_at"] and Path(entry["task_file"]).exists()

    def test_three_begins_leave_three_abortable_successors(self, sup_home, capsys):
        """THE incident, and then the incident the wave-1 fix resurrected:
        three attempts in sixteen minutes. Under a slot, #1 and #2 matched
        nothing and produced the pre-fix refusal verbatim."""
        self._hold()
        _rc, gen = self._begin(capsys)
        for n in (2, 3):
            self._begin(capsys, run=_dispatch_then_roster(f"succ000{n}-full",
                                                          f"succ000{n}"), nonce=gen)
        entries = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert len(entries) == 3
        assert [e["successor_sid"] for e in entries] == [
            "succ0001-full", "succ0002-full", "succ0003-full"]
        # every one of them resolves to a stop, oldest included
        for sid in ("succ0001-full", "succ0002-full", "succ0003-full"):
            verdict = fleet.resolve_handoff_abort(fleet.read_incarnation(), None,
                                                  successor_sid=sid)
            assert verdict["action"] == "stop" and verdict["sid"] == sid

    def test_begin_never_unlinks_an_earlier_attempts_task_file(self, sup_home, capsys):
        """R1/R2: the earlier successor may be alive and mid-boot, and that
        file is its ONLY input. Wave 1 deleted it as 'superseded'."""
        self._hold()
        _rc, gen = self._begin(capsys)
        first = self._incs()[0]
        first_file = sup_home / "state" / f"supervisor-handoff-{first}.md"
        _age_file(first_file, 10 * T)      # even ancient, it is still claimed
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        assert first_file.exists(), "begin deleted a live successor's only input"
        assert len(self._incs()) == 2

    def test_aborting_one_successor_leaves_the_others_recorded(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        assert self._abort(nonce=gen, successor_sid="succ0001-full") == 0
        remaining = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert [e["successor_sid"] for e in remaining] == ["succ0002-full"]

    def test_M09_a_claim_that_is_not_a_dict_reads_as_no_entries(self):
        """M09: the guard the wave-1 suite never exercised. Every caller of
        `handoff_pending_entries` may hand it a `read_incarnation()` result,
        which is None for a missing or corrupt INCARNATION."""
        for claim in (None, "corrupt", 7, ["not", "a", "claim"]):
            assert fleet.handoff_pending_entries(claim) == []

    def test_a_corrupt_pending_value_reads_as_empty_not_as_a_crash(self):
        assert fleet.handoff_pending_entries({"handoff_pending": "nonsense"}) == []
        assert fleet.handoff_pending_entries({"handoff_pending": ["str", 1]}) == []

    def test_a_wave_1_single_marker_still_reads(self):
        """A claim written by the first cut of this branch holds a bare dict."""
        legacy = {"handoff_pending": {"successor_inc": DEAD_INC_A,
                                      "successor_sid": "sid-x", "minted_at": "x"}}
        assert [e["successor_inc"] for e in fleet.handoff_pending_entries(legacy)] == \
            [DEAD_INC_A]


class TestPostJoinStampTargetsItsOwnEntry(_HandoffBase):
    """R8 / M07 -- the concurrency guard nearest the CRIT, untested in wave 1."""

    def test_M07_the_join_stamps_our_entry_and_leaves_a_rivals_alone(
            self, sup_home, capsys):
        """A rival `sup-handoff-begin` appends its own entry while we are in
        the roster-join window. Stamping "the pending entry" positionally, or
        writing back the claim dict captured before the dispatch, puts OUR
        sid on the RIVAL's entry (aiming abort at the wrong live session) or
        drops the rival's entry entirely."""
        self._hold()
        rival = {"successor_inc": DEAD_INC_B, "successor_sid": None,
                 "task_file": "rival.md", "minted_at": fleet.now_iso()}
        inner = _dispatch_then_roster()
        def run(argv, **kw):
            out = inner(argv, **kw)
            if "--bg" in argv:
                # Between the claim write and the join: a second body appends.
                claim = fleet.read_incarnation()
                claim["handoff_pending"] = fleet.handoff_pending_entries(claim) + [rival]
                fleet.write_incarnation(claim)
            return out
        rc, _gen = self._begin(capsys, run=run)
        assert rc == 0
        entries = {e["successor_inc"]: e for e in
                   fleet.handoff_pending_entries(fleet.read_incarnation())}
        assert DEAD_INC_B in entries, "the rival's entry was dropped by our claim write"
        assert entries[DEAD_INC_B]["successor_sid"] is None, \
            "our joined sid was stamped onto the rival's entry"
        ours = [i for i in entries if i != DEAD_INC_B]
        assert len(ours) == 1 and entries[ours[0]]["successor_sid"] == "succ0001-full"


class TestAbortResolution(_HandoffBase):
    """R3/R7 -- `resolve_handoff_abort` is pure, so every arm is testable."""

    def test_a_stillborn_successor_aborts_with_no_handshake(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        inc = self._incs()[0]
        task_file = sup_home / "state" / f"supervisor-handoff-{inc}.md"
        assert fleet.read_handshake() is None
        assert not fleet.handoff_abort_flag_path().exists()
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen,
                           successor_sid="succ0001-full") == 0
        assert calls and calls[0][-2:] == ["stop", fleet._native_job_ref("succ0001-full")]
        assert fleet.handoff_pending_entries(fleet.read_incarnation()) == []
        assert not task_file.exists()
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"

    def test_an_unrelated_sid_is_still_refused(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        before = fleet.handoff_pending_entries(fleet.read_incarnation())
        calls = []
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            self._abort(run=_stop_ok(calls), nonce=gen, successor_sid="sid-SOMEONE-ELSE")
        assert not calls
        assert not fleet.handoff_abort_flag_path().exists()
        assert fleet.handoff_pending_entries(fleet.read_incarnation()) == before

    def test_the_refusal_names_the_pending_successors_it_did_not_match(
            self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        with pytest.raises(fleet.FleetCliError, match="succ0001-full"):
            self._abort(nonce=gen, successor_sid="sid-typo")

    def test_a_live_handshake_still_wins_and_cross_checks(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        fleet.write_handshake("inc-20260724T090000Z-abcd", "sid-from-handshake")
        calls = []
        with pytest.raises(fleet.FleetCliError, match="does not match HANDSHAKE sid"):
            self._abort(run=_stop_ok(calls), nonce=gen, successor_sid="succ0001-full")
        assert not calls

    def test_neither_handle_is_a_refusal_not_a_crash(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        with pytest.raises(fleet.FleetCliError, match="successor-sid or --successor-inc"):
            self._abort(nonce=gen)

    def test_R7_a_sid_bearing_abort_flag_is_no_longer_evidence(self, sup_home):
        """The wave-1 third arm. NO begin path writes a sid into that flag --
        every `_abort_flag` call site omits `successor_sid` -- so it could only
        fire on a repeat abort of a sid the first abort already stopped, while
        its docstring claimed it covered the DOA path. Deleted; with no
        pending entry the answer is the refusal, not a stop."""
        self._hold()
        fleet._write_json_atomic(fleet.handoff_abort_flag_path(), {
            "aborted_at": fleet.now_iso(), "reason": "aborted",
            "successor_sid": "sid-recorded", "holder": "inc-20260724T000000Z-0old"})
        calls = []
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            self._abort(run=_stop_ok(calls), successor_sid="sid-recorded")
        assert not calls

    def test_an_entry_inside_the_join_window_refuses_and_says_when(self, sup_home, capsys):
        """R3 arm 4: a join in progress is not a dead successor."""
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        with pytest.raises(fleet.FleetCliError, match="join window"):
            self._abort(nonce=gen, successor_inc=inc)
        assert self._incs() == [inc], "a refusal must not retire the entry"

    def test_a_stale_sidless_entry_retires_and_claims_no_stop(self, sup_home, capsys):
        """R3, the state wave 1 could not leave: DOA recorded an entry with no
        sid, so all three abort arms were dead at once and NOTHING the body
        could do retired it. Past T it is retirable by inc -- and the verb must
        never report stopping a session it never had."""
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        task_file = sup_home / "state" / f"supervisor-handoff-{inc}.md"
        assert task_file.exists()
        _age_entry(inc, 2 * T)
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen, successor_inc=inc) == 0
        out = capsys.readouterr().out
        assert not calls, "nothing may be stopped: no sid was ever recorded"
        assert "NO session was stopped" in out
        assert fleet.handoff_pending_entries(fleet.read_incarnation()) == []
        assert not task_file.exists()
        assert "no sid was ever recorded" in fleet.supervisor_journal_latest()["body"]

    def test_abort_by_inc_stops_a_sid_bearing_entry(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        inc = self._incs()[0]
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen, successor_inc=inc) == 0
        assert calls and calls[0][-1] == fleet._native_job_ref("succ0001-full")

    def test_two_handles_naming_different_successors_match_neither(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        first, second = self._incs()
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            self._abort(nonce=gen, successor_sid="succ0001-full", successor_inc=second)
        assert len(self._incs()) == 2

    def test_R4_the_token_hash_dies_with_the_LAST_entry_only(self, sup_home, capsys):
        """A stranded plaintext token is LIVE, not spent: `sup-boot
        --handoff-inc <inc> --handoff-token <tok>` still validates it while the
        claim holds its hash."""
        self._hold()
        _rc, gen = self._begin(capsys)
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        assert self._abort(nonce=gen, successor_sid="succ0001-full") == 0
        assert fleet.read_incarnation().get("handoff_token_hash"), \
            "one attempt is still outstanding -- its token must still verify"
        assert self._abort(nonce=gen, successor_sid="succ0002-full") == 0
        assert "handoff_token_hash" not in fleet.read_incarnation()


class TestSweepPredicateFailsClosed:
    """R2 -- the pure predicate, over `(name, age_seconds)` pairs."""

    HOLDER = "inc-20260724T045450Z-0dea"
    PENDING = "inc-20260724T082006Z-696e"
    DEAD = "inc-20260724T081049Z-754f"

    def _claim(self, pending=(), holder=HOLDER):
        claim = {"incarnation_id": holder}
        if pending:
            claim["handoff_pending"] = [
                {"successor_inc": inc, "successor_sid": None,
                 "task_file": f"state/supervisor-handoff-{inc}.md",
                 "minted_at": fleet.now_iso()} for inc in pending]
        return claim

    def _named(self, *incs, age=2 * T):
        return [(f"supervisor-handoff-{i}.md", age) for i in incs]

    def test_a_pending_entrys_file_is_never_swept_however_old(self):
        got = fleet.handoff_task_files_to_sweep(
            self._named(self.PENDING, self.HOLDER, self.DEAD, age=100 * T),
            self._claim(pending=[self.PENDING]))
        assert got == [f"supervisor-handoff-{self.DEAD}.md"]

    def test_the_holders_own_file_is_never_swept(self):
        got = fleet.handoff_task_files_to_sweep(
            self._named(self.HOLDER, self.DEAD), self._claim())
        assert got == [f"supervisor-handoff-{self.DEAD}.md"]

    def test_a_missing_or_corrupt_claim_sweeps_NOTHING(self):
        """The assertion this test's NAME always described. Wave 1 asserted the
        opposite -- `== sorted(names)`, i.e. take everything -- which is
        reachable by doing exactly what the runbook says: remove
        `supervisor/INCARNATION` by hand. `read_incarnation` then returns None,
        nothing is protected, and a booting successor loses its only input."""
        names = self._named(self.PENDING, self.DEAD)
        for claim in (None, {}, "corrupt", {"session_id": "sid-x"}):
            assert fleet.handoff_task_files_to_sweep(names, claim) == [], claim

    def test_a_file_younger_than_the_handoff_timeout_is_never_swept(self):
        assert fleet.handoff_task_files_to_sweep(
            self._named(self.DEAD, age=T - 1), self._claim()) == []
        assert fleet.handoff_task_files_to_sweep(
            self._named(self.DEAD, age=T + 1), self._claim()) == \
            [f"supervisor-handoff-{self.DEAD}.md"]

    def test_a_file_whose_age_could_not_be_read_is_never_swept(self):
        assert fleet.handoff_task_files_to_sweep(
            [(f"supervisor-handoff-{self.DEAD}.md", None)], self._claim()) == []

    def test_an_unparseable_name_is_left_for_a_human(self):
        names = [("supervisor-handoff-notes.md", 10 * T),
                 ("supervisor-handoff-.md", 10 * T),
                 (f"supervisor-handoff-{self.DEAD.upper()}.md", 10 * T),
                 ("README.md", 10 * T)]
        assert fleet.handoff_task_files_to_sweep(names, self._claim()) == []

    def test_every_pending_entry_protects_its_file_not_just_the_newest(self):
        got = fleet.handoff_task_files_to_sweep(
            self._named(self.PENDING, self.DEAD, age=10 * T),
            self._claim(pending=[self.PENDING, self.DEAD]))
        assert got == []


class TestSweepSites(_HandoffBase):
    """R8 / M18 + M19 -- wave 1's two sweep-site tests were VACUOUS: begin's
    own sweep removed the seeded file before the site under test ran, so the
    assertion held with the site deleted. Here the orphan is seeded AFTER
    begin, so the site under test is the only thing that can remove it."""

    def _remaining(self, sup_home):
        return sorted(p.name for p in (sup_home / "state").glob("supervisor-handoff-*.md"))

    def test_begin_sweeps_an_aged_ownerless_file(self, sup_home, capsys):
        self._hold()
        _orphan(sup_home, DEAD_INC_A)
        self._begin(capsys)
        assert f"supervisor-handoff-{DEAD_INC_A}.md" not in self._remaining(sup_home)

    def test_M18_complete_sweeps_a_file_only_it_can_reach(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        inc = self._incs()[0]
        _orphan(sup_home, DEAD_INC_A)          # AFTER begin: only complete can take it
        assert f"supervisor-handoff-{DEAD_INC_A}.md" in self._remaining(sup_home)
        fleet.write_handshake(inc, "succ0001-full",
                              handoff_token_hash=fleet.read_incarnation()["handoff_token_hash"],
                              nonce_hash=fleet.nonce_digest(fleet.mint_nonce()))
        args = SimpleNamespace(sid="sid-old", expect_inc=inc,
                               expect_sid="succ0001-full", nonce=gen)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        assert self._remaining(sup_home) == []

    def test_M19_abort_sweeps_a_file_only_it_can_reach(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        _orphan(sup_home, DEAD_INC_A)          # AFTER begin: only abort can take it
        assert f"supervisor-handoff-{DEAD_INC_A}.md" in self._remaining(sup_home)
        assert self._abort(nonce=gen, successor_sid="succ0001-full") == 0
        assert self._remaining(sup_home) == []

    def test_sup_boot_sweeps_orphans_but_spares_every_pending_entry(
            self, sup_home, capsys):
        """§5.9 put the rejection log's out-of-band compaction in `sup-boot`
        because a `supervisor-handoff-<inc>.md` belongs to no worker record and
        `fleet clean` cannot reach it. Same site, same reasoning -- and the
        seize path is exactly where wave 1 could delete a live successor's
        file, because the new claim had no pending set to protect it (R5)."""
        self._hold()
        _rc, gen = self._begin(capsys)
        pending_inc = self._incs()[0]
        _age_file(sup_home / "state" / f"supervisor-handoff-{pending_inc}.md", 10 * T)
        _orphan(sup_home, DEAD_INC_A)
        _orphan(sup_home, DEAD_INC_B)
        args = SimpleNamespace(sid="sid-old", handoff_inc=None, nonce=gen)
        def roster(argv, **kw):
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                [{"sessionId": "sid-old", "status": "busy"}]), stderr="")
        fleet.cmd_sup_boot(args, which=_fake_which, run=roster)
        capsys.readouterr()
        assert self._remaining(sup_home) == [f"supervisor-handoff-{pending_inc}.md"]

    def test_M29_an_unremovable_token_file_is_reported_not_swallowed(
            self, sup_home, capsys, monkeypatch):
        """R6: wave 1 caught `OSError` wholesale, so a PermissionError on a
        live token file became a silent no-op -- a retention failure nobody
        would ever see."""
        self._hold()
        _orphan(sup_home, DEAD_INC_A)
        real_unlink = Path.unlink
        def boom(self, *a, **kw):
            if self.name.endswith(f"{DEAD_INC_A}.md"):
                raise PermissionError(13, "file is locked")
            return real_unlink(self, *a, **kw)
        monkeypatch.setattr(Path, "unlink", boom)
        swept = fleet.sweep_handoff_task_files(fleet.read_incarnation())
        out = capsys.readouterr().out
        assert swept == []
        assert "WARNING" in out and DEAD_INC_A in out and "handoff token" in out


class TestPathConfinement:
    """R6 -- the incarnation id is a PATH COMPONENT reached from successor-
    controlled input (`HANDSHAKE.incarnation_id`). The break lens deleted a
    file outside FLEET_HOME with rc 0."""

    def test_the_minted_shape_is_the_only_accepted_shape(self):
        assert fleet.valid_incarnation_id(fleet.mint_incarnation_id())
        for bad in ("../../evil", "inc-succ", "inc-20260724T045450Z-0DEA",
                    "", None, 7, "inc-2026724T045450Z-0dea",
                    "inc-20260724T045450Z-0dea/../x"):
            with pytest.raises(ValueError):
                fleet.valid_incarnation_id(bad)

    def test_a_traversal_never_produces_a_path(self, sup_home):
        with pytest.raises(ValueError):
            fleet.handoff_task_file_path("../../../etc/passwd")

    def test_a_traversal_unlinks_nothing_and_says_so(self, sup_home, capsys):
        outside = sup_home.parent / "victim.md"
        outside.write_text("do not delete me", encoding="utf-8")
        rel = os.path.relpath(outside, sup_home / "state").replace(os.sep, "/")
        assert fleet.unlink_handoff_task_file(rel[:-3]) is False
        assert outside.exists()
        assert "WARNING" in capsys.readouterr().out

    def test_the_parser_refuses_a_malformed_incarnation_id(self, sup_home):
        for argv in (["sup-handoff-abort", "--successor-inc", "../../x"],
                     ["sup-handoff-complete", "--expect-inc", "../../x"],
                     ["sup-boot", "--handoff-inc", "../../x"]):
            with pytest.raises(SystemExit):
                fleet.main(argv)

    def test_a_real_id_round_trips_inside_the_state_dir(self, sup_home):
        inc = fleet.mint_incarnation_id()
        path = fleet.handoff_task_file_path(inc)
        assert path.parent == (sup_home / "state").resolve()


class TestClaimTransitionsCarryThePendingSet(_HandoffBase):
    """R5 -- a predecessor dying mid-handoff is the exact failure the
    succession path exists for, and wave 1 erased its successor at that
    moment: invisible in `--json`, unabortable, and its file unprotected."""

    def _boot(self, sup_home, sid="sid-new", entries=None):
        args = SimpleNamespace(sid=sid, handoff_inc=None, nonce=None)
        payload = entries if entries is not None else [{"sessionId": sid, "status": "busy"}]
        def roster(argv, **kw):
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        return fleet.cmd_sup_boot(args, which=_fake_which, run=roster)

    def test_a_seize_carries_the_pending_successors_forward(self, sup_home, capsys):
        self._hold()
        self._begin(capsys)
        inc = self._incs()[0]
        stale = fleet.read_incarnation()      # predecessor dies mid-handoff
        stale["heartbeat_at"] = (
            fleet.datetime.now(fleet.timezone.utc)
            - fleet.timedelta(seconds=4 * 3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation(stale)
        assert self._boot(sup_home) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["claimed_via"] == "seize"
        assert [e["successor_inc"] for e in fleet.handoff_pending_entries(claim)] == [inc]

    def test_a_fresh_claim_after_a_release_carries_them_forward(self, sup_home, capsys):
        self._hold()
        self._begin(capsys)
        inc = self._incs()[0]
        released = fleet.read_incarnation()
        released["state"] = "released"
        released["released_at"] = fleet.now_iso()
        released["released_by_sid"] = "sid-old"
        released.pop("session_id", None)
        released.pop("nonce_hash", None)
        fleet.write_incarnation(released)
        assert self._boot(sup_home) == 0
        capsys.readouterr()
        claim = fleet.read_incarnation()
        assert claim["claimed_via"] == "fresh"
        assert [e["successor_inc"] for e in fleet.handoff_pending_entries(claim)] == [inc]

    def test_the_boot_that_carries_them_does_not_sweep_their_files(
            self, sup_home, capsys):
        self._hold()
        self._begin(capsys)
        inc = self._incs()[0]
        _age_file(sup_home / "state" / f"supervisor-handoff-{inc}.md", 10 * T)
        stale = fleet.read_incarnation()
        stale["heartbeat_at"] = (
            fleet.datetime.now(fleet.timezone.utc)
            - fleet.timedelta(seconds=4 * 3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fleet.write_incarnation(stale)
        assert self._boot(sup_home) == 0
        capsys.readouterr()
        assert (sup_home / "state" / f"supervisor-handoff-{inc}.md").exists()

    def test_complete_carries_the_rivals_and_drops_the_completed_one(
            self, sup_home, capsys):
        """The new holder is the only body with a claim, so it inherits the
        duty to stop the attempts that did not win."""
        self._hold()
        _rc, gen = self._begin(capsys)
        loser = self._incs()[0]
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        winner = self._incs()[1]
        fleet.write_handshake(winner, "succ0002-full",
                              handoff_token_hash=fleet.read_incarnation()["handoff_token_hash"],
                              nonce_hash=fleet.nonce_digest(fleet.mint_nonce()))
        args = SimpleNamespace(sid="sid-old", expect_inc=winner,
                               expect_sid="succ0002-full", nonce=gen)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == winner
        assert [e["successor_inc"] for e in fleet.handoff_pending_entries(claim)] == [loser]
        assert "handoff_token_hash" not in claim   # the predecessor's, never carried


class TestMarkerLifecycle(_HandoffBase):
    def test_dispatch_failure_retires_the_entry_and_the_token_file(self, sup_home):
        """Nothing was launched, so no body can be reading the task file and
        there is nothing for a later abort to stop."""
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                        sleep=lambda s: None)
        claim = fleet.read_incarnation()
        assert fleet.handoff_pending_entries(claim) == []
        assert "handoff_token_hash" not in claim      # R4: last entry took it
        assert not list((sup_home / "state").glob("supervisor-handoff-*.md"))

    def test_M25_a_dispatch_failure_never_retires_a_RIVALS_entry(self, sup_home, capsys):
        """M25: `_drop_pending_marker`'s identity guard. Entries belong to
        attempts; popping without an exact `successor_inc` match retires a
        concurrent begin's LIVE successor from this attempt's failure path."""
        self._hold()
        _rc, gen = self._begin(capsys)          # attempt 1 joins and stays live
        survivor = self._incs()[0]
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=gen)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                        sleep=lambda s: None)
        assert self._incs() == [survivor], "the rival attempt's entry was retired"
        assert fleet.read_incarnation().get("handoff_token_hash"), \
            "an outstanding attempt's token must still verify (R4)"
        assert (sup_home / "state" / f"supervisor-handoff-{survivor}.md").exists()

    def test_a_DOA_successor_keeps_its_entry_and_then_ages_out(self, sup_home, capsys):
        """The deliberate asymmetry: DOA means the roster never showed the
        successor, which is NOT the same as knowing no body exists. The entry
        stands, and R3 ages it into `resolvable-stale` rather than leaving it
        immortal."""
        self._hold()
        self._begin_doa(capsys)
        entries = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert len(entries) == 1 and entries[0]["successor_sid"] is None
        assert fleet.handoff_entry_state(entries[0]) == fleet.HANDOFF_JOINING
        assert Path(entries[0]["task_file"]).exists()
        _age_entry(entries[0]["successor_inc"], 2 * T)
        aged = fleet.handoff_pending_entries(fleet.read_incarnation())[0]
        assert fleet.handoff_entry_state(aged) == fleet.HANDOFF_RESOLVABLE_STALE

    def test_an_unreadable_minted_at_never_becomes_retirable(self):
        """Fail closed: an entry that cannot be aged cannot be aged OUT."""
        assert fleet.handoff_entry_state({"minted_at": "not-a-date"}) == \
            fleet.HANDOFF_JOINING
        assert fleet.handoff_entry_state({}) == fleet.HANDOFF_JOINING


class TestViewsPublishThePendingSuccessors(_HandoffBase):
    def test_json_publishes_one_entry_per_attempt_with_its_state(
            self, sup_home, capsys):
        """The live confusion: `pending_present: false` is about the pending
        GENERATION and says nothing about a pending SUCCESSOR."""
        self._hold()
        _rc, gen = self._begin(capsys)
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        inc = json.loads(capsys.readouterr().out)["incarnation"]
        assert inc["handoff_pending_count"] == 2
        assert [e["successor_sid"] for e in inc["handoff_pending"]] == [
            "succ0001-full", "succ0002-full"]
        assert {e["state"] for e in inc["handoff_pending"]} == \
            {fleet.HANDOFF_AWAITING_HANDSHAKE}
        assert inc["pending_present"] is False     # the nonce pending: unrelated

    def test_a_DOA_attempt_reads_as_stale_not_as_a_live_successor(
            self, sup_home, capsys):
        """rs-MIN-1: wave 1 published a DOA attempt's fields as if a successor
        were still coming."""
        self._hold()
        self._begin_doa(capsys)
        _age_entry(self._incs()[0], 2 * T)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        entry = json.loads(capsys.readouterr().out)["incarnation"]["handoff_pending"][0]
        assert entry["successor_sid"] is None
        assert entry["state"] == fleet.HANDOFF_RESOLVABLE_STALE

    def test_the_plain_human_form_reports_pending_successors(self, sup_home, capsys):
        """rb-MIN-4: the surface an operator reads by reflex was silent about
        the thing they were looking for."""
        self._hold()
        self._begin(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "pending successor" in out
        assert "succ0001-full" in out and fleet.HANDOFF_AWAITING_HANDSHAKE in out
        assert "--nonce" in out

    def test_the_view_never_publishes_the_task_file_path(self, sup_home, capsys):
        """§5.8: the entry's `task_file` names a LIVE plaintext token."""
        self._hold()
        self._begin(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        raw = capsys.readouterr().out
        assert "task_file" not in raw and "supervisor-handoff-" not in raw

    def test_the_doctor_note_does_not_call_a_live_token_spent(self, sup_home):
        """rs-MIN-2: right advice, false rationale. Nothing invalidates a
        handoff token but the claim dropping `handoff_token_hash`."""
        _orphan(sup_home, DEAD_INC_A)
        _name, _ok, detail = fleet._doctor_check_supervisor_handoff()
        assert "spent handoff token" not in detail
        assert "still" in detail and "LIVE" in detail


class TestAbortRecipeCarriesTheNonce:
    """D3: `sup-handoff-abort` is NOT exempt from the §7 continuity gate. The
    runbook showed it without `--nonce`, and following it verbatim earned an
    rc 4 mid-succession on 2026-07-24 -- the moment a wrong recipe costs most.

    Linted rather than fixed-once because the same recipe is copied across the
    operator surface, and an under-swept doc fix is how the last three doc
    defects survived. Scope is the surfaces an operator READS AS INSTRUCTIONS
    (skills/, commands/) plus the hint fleet itself prints; pinned receipts in
    docs/specs quote OLD file contents on purpose and are not swept."""

    # An INVOCATION, not a mention: the verb plus at least one argument-shaped
    # token. Bare prose (`sup-handoff-abort` is also a _require_claim_holder
    # caller) is not a recipe and is not swept.
    RECIPE = re.compile(
        r"sup-handoff-(?:abort|complete)"
        r"(?:\s+(?:--[a-z-]+|<[^>\n]*>|\[[^\]\n]*\]|[A-Za-z0-9|._-]+))+")

    def _surfaces(self):
        return sorted(REPO_ROOT.joinpath("skills").rglob("*.md")) + \
            sorted(REPO_ROOT.joinpath("commands").glob("*.md"))

    def test_every_operator_facing_handoff_recipe_presents_a_nonce(self):
        offenders = []
        for path in self._surfaces():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in self.RECIPE.finditer(line):
                    if "--nonce" not in match.group(0):
                        offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: "
                                         f"{match.group(0)}")
        assert not offenders, (
            "handoff recipe without --nonce (rc 4 for anyone who follows it):\n"
            + "\n".join(offenders))

    def test_the_hint_fleet_prints_after_begin_presents_a_nonce(self, sup_home, capsys):
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-20260724T000000Z-0old",
                                 "session_id": "sid-old", "claimed_at": beat,
                                 "heartbeat_at": beat, "claimed_via": "fresh"})
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None)
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which,
                                           run=_dispatch_then_roster(),
                                           sleep=lambda s: None) == 0
        out = capsys.readouterr().out
        for match in self.RECIPE.finditer(out):
            assert "--nonce" in match.group(0), match.group(0)
        assert "sup-handoff-abort" in out and "sup-handoff-complete" in out
