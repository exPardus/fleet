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

WAVE 3 (R9/R10) answers what R1 and R2 together created. Keeping every attempt
recorded AND keeping its task file left a superseded successor fully BOOTABLE,
on top of a protocol whose HANDSHAKE and token hash are single-valued:

  R9  AT MOST ONE BOOTABLE SUCCESSOR, and supersession is EXPLICIT. Keep the
      collection -- that is what makes every attempt abortable and auditable --
      but a begin marks every earlier unresolved entry superseded: still
      abortable by either handle, sweepable once past T, and NOT bootable.
      `sup-boot --handoff-inc` refuses a superseded inc and tells that body to
      terminate, which is what stops a rival from clobbering the winner's
      HANDSHAKE and stranding the claim with no holder (rb-CRIT-2). There is
      deliberately no promote verb: abort, then begin again.
  R10 eight more mutations survived the wave-2 suite. Each has a test here that
      goes RED under exactly that mutation, proven mutate-red-restore.
"""
import json
import os
import re
import subprocess
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


def _roster_run(*sids):
    """`subprocess.run` double that only ever answers the roster query."""
    def run(argv, **kw):
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
            [{"sessionId": s, "status": "busy"} for s in sids]))
    return run


def _token_of(sup_home, inc):
    """The PLAINTEXT one-shot token, read where the successor body reads it:
    out of the `sup-boot --handoff-inc ... --handoff-token ...` line of its own
    task file (§6.4). No test-only channel."""
    text = (sup_home / "state" / f"supervisor-handoff-{inc}.md").read_text(
        encoding="utf-8")
    return re.search(r"--handoff-token (\S+)", text).group(1)


def _boot_successor(sid, inc, token=None, roster=()):
    """A REAL successor boot: the same `cmd_sup_boot` entry point, the same
    argv shape the task file prescribes."""
    return fleet.cmd_sup_boot(
        SimpleNamespace(sid=sid, handoff_inc=inc, handoff_token=token, nonce=None),
        which=_fake_which, run=_roster_run(*(roster or (sid,))))


def _backdate(entry_inc, key, seconds):
    """Back-date one timestamp field of a REAL begin-produced entry."""
    claim = fleet.read_incarnation()
    for entry in fleet.handoff_pending_entries(claim):
        if entry.get("successor_inc") == entry_inc:
            entry[key] = (fleet.datetime.now(fleet.timezone.utc)
                          - fleet.timedelta(seconds=seconds)).strftime(
                              "%Y-%m-%dT%H:%M:%SZ")
    fleet.write_incarnation(claim)
    return claim


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
               successor_inc=None, force=False, retire_all=False):
        args = SimpleNamespace(sid=sid, nonce=nonce, successor_sid=successor_sid,
                               successor_inc=successor_inc, force=force,
                               retire_all=retire_all)
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

    def test_M07_the_join_stamps_our_entry_and_no_other(self, sup_home, capsys):
        """Our attempt is the SECOND of three entries: an earlier attempt that
        already joined sits before it, and a rival begin appends a third while
        we are still inside the roster-join window.

        The arrangement is the point. Stamping "the pending entry"
        positionally puts OUR sid on the FIRST entry (`[0]`, overwriting a
        different live successor's sid) or on the RIVAL's (`[-1]`), either way
        aiming a later abort at the wrong live session; writing back the claim
        dict captured before the dispatch drops the rival's entry entirely.
        Only an exact `successor_inc` match survives all three."""
        self._hold()
        _rc, gen = self._begin(capsys)                     # attempt 1: joined
        first = self._incs()[0]
        rival = {"successor_inc": DEAD_INC_B, "successor_sid": None,
                 "task_file": "rival.md", "minted_at": fleet.now_iso()}
        inner = _dispatch_then_roster("succ0002-full", "succ0002")
        def run(argv, **kw):
            out = inner(argv, **kw)
            if "--bg" in argv:
                # Between our claim write and our join: a third body appends.
                claim = fleet.read_incarnation()
                claim["handoff_pending"] = fleet.handoff_pending_entries(claim) + [rival]
                fleet.write_incarnation(claim)
            return out
        rc, _gen = self._begin(capsys, run=run, nonce=gen)  # attempt 2: ours
        assert rc == 0
        entries = {e["successor_inc"]: e for e in
                   fleet.handoff_pending_entries(fleet.read_incarnation())}
        assert set(entries) >= {first, DEAD_INC_B}, \
            "an entry was dropped by our claim write"
        assert entries[first]["successor_sid"] == "succ0001-full", \
            "our joined sid was stamped onto an earlier attempt's entry"
        assert entries[DEAD_INC_B]["successor_sid"] is None, \
            "our joined sid was stamped onto the rival's entry"
        ours = [i for i in entries if i not in (first, DEAD_INC_B)]
        assert len(ours) == 1 and entries[ours[0]]["successor_sid"] == "succ0002-full"


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
        with pytest.raises(fleet.FleetCliError,
                           match="needs --successor-sid, --successor-inc or --retire-all"):
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
        # R9: the second begin SUPERSEDED the first attempt, and the view says
        # so. Both are still published and both are still abortable -- what the
        # older one is not, any more, is bootable.
        assert [e["state"] for e in inc["handoff_pending"]] == [
            fleet.HANDOFF_SUPERSEDED, fleet.HANDOFF_AWAITING_HANDSHAKE]
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


class TestAtMostOneBootableSuccessor(_HandoffBase):
    """R9 / rb-CRIT-2 -- the defect wave 2 CREATED. Wave 1 made a rival
    unbootable by deleting its task file; wave 2 kept the file (R2) and kept the
    entry (R1), so the rival became fully bootable on top of a protocol whose
    HANDSHAKE is a single path and whose `handoff_token_hash` is a single
    value."""

    def _two_live_attempts(self, sup_home, capsys):
        """Two REAL begins: the slow rival first, then the winner. Returns
        `(gen, rival_inc, rival_token, winner_inc, winner_token)` with both
        task files on disk and both plaintext tokens live."""
        self._hold()
        _rc, gen = self._begin(capsys)
        rival_inc = self._incs()[0]
        rival_token = _token_of(sup_home, rival_inc)
        rc, _g = self._begin(capsys, nonce=gen,
                             run=_dispatch_then_roster("succ0002-full", "succ0002"))
        assert rc == 0
        winner_inc = self._incs()[1]
        return gen, rival_inc, rival_token, winner_inc, _token_of(sup_home, winner_inc)

    def test_rb_CRIT_2_a_superseded_rival_cannot_clobber_the_winners_handshake(
            self, sup_home, capsys):
        """THE probe, with two REAL successor boots and no hand-built state.

        Before R9 the second boot overwrote `supervisor/HANDSHAKE` with the
        rival's incarnation id and its own token hash. `complete` on the winner
        then refused (the HANDSHAKE names the rival), `abort` on the winner
        refused (sid mismatch), and aborting the rival deleted the HANDSHAKE the
        winner would never rewrite -- `_render_successor_task` runs `sup-boot
        --handoff-inc` once at step 1 and only polls afterwards. The claim
        transferred to NOBODY."""
        gen, rival_inc, rival_token, winner_inc, winner_token = \
            self._two_live_attempts(sup_home, capsys)

        assert _boot_successor("succ0002-full", winner_inc, winner_token) == 0
        capsys.readouterr()
        winners_handshake = fleet.read_handshake()
        assert winners_handshake["incarnation_id"] == winner_inc

        # the slow rival boots LATE, for real, holding its own live token
        rc = _boot_successor("succ0001-full", rival_inc, rival_token)
        out = capsys.readouterr().out
        assert rc == fleet.SUPERVISOR_BOOT_HANDOFF_REFUSED_RC
        assert "SUPERSEDED" in out and winner_inc in out
        assert "TERMINATE" in out and f"HANDOFF-ORPHAN {rival_inc}" in out
        assert fleet.read_handshake() == winners_handshake, \
            "the superseded rival clobbered the live attempt's HANDSHAKE"
        assert "NONCE:" not in out, "a refused body must hold no generation"

        # and because it could not, the succession still completes
        assert fleet.cmd_sup_handoff_complete(SimpleNamespace(
            sid="sid-old", expect_inc=winner_inc, expect_sid="succ0002-full",
            nonce=gen)) == 0
        assert fleet.read_incarnation()["incarnation_id"] == winner_inc

    def test_the_current_attempt_still_boots_normally(self, sup_home, capsys):
        """The refusal must not cost the succession its one working path."""
        self._hold()
        _rc, _gen = self._begin(capsys)
        inc = self._incs()[0]
        assert _boot_successor("succ0001-full", inc, _token_of(sup_home, inc)) == 0
        capsys.readouterr()
        assert fleet.read_handshake()["incarnation_id"] == inc

    def test_a_claim_recording_no_attempt_at_all_still_boots(self, sup_home, capsys):
        """Fails OPEN with nothing to read: an old-code predecessor records no
        pending set, and refusing every handoff on that evidence would wedge the
        one path that still works."""
        self._hold()
        assert _boot_successor("succ0001-full", DEAD_INC_A, "tok") == 0
        capsys.readouterr()
        assert fleet.read_handshake()["incarnation_id"] == DEAD_INC_A

    def test_an_inc_no_entry_records_is_refused_when_others_are_recorded(
            self, sup_home, capsys):
        """The retired-rival shape: its entry is gone (aborted), so it is not
        the current attempt either, and it must not write a HANDSHAKE."""
        self._hold()
        self._begin(capsys)
        rc = _boot_successor("succ0009-full", DEAD_INC_B, "tok")
        out = capsys.readouterr().out
        assert rc == fleet.SUPERVISOR_BOOT_HANDOFF_REFUSED_RC
        assert "not a pending successor" in out and "TERMINATE" in out
        assert fleet.read_handshake() is None

    def test_begin_supersedes_every_earlier_unresolved_entry(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        for n in (2, 3):
            self._begin(capsys, nonce=gen,
                        run=_dispatch_then_roster(f"succ000{n}-full", f"succ000{n}"))
        entries = fleet.handoff_pending_entries(fleet.read_incarnation())
        states = [fleet.handoff_entry_state(e) for e in entries]
        assert states == [fleet.HANDOFF_SUPERSEDED, fleet.HANDOFF_SUPERSEDED,
                          fleet.HANDOFF_AWAITING_HANDSHAKE]
        assert entries[0]["superseded_by"] == entries[1]["successor_inc"], \
            "supersession must name the attempt that took over"
        assert entries[1]["superseded_by"] == entries[2]["successor_inc"]

    def test_a_superseded_entry_is_still_abortable_by_either_handle(
            self, sup_home, capsys):
        """R9 clause (a). Supersession removes bootability, not abortability --
        a superseded body may be LIVE, and only an abort stops it."""
        self._hold()
        _rc, gen = self._begin(capsys)
        superseded = self._incs()[0]
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen,
                           successor_inc=superseded) == 0
        assert calls[0][-1] == fleet._native_job_ref("succ0001-full"), \
            "a superseded entry that recorded a sid is STOPPED, not just retired"
        assert superseded not in self._incs()

    def test_a_superseded_sidless_entry_retires_at_once_no_waiting(
            self, sup_home, capsys):
        """It is not `resolvable-stale` and never will be -- there is no join
        left to wait out, so waiting T for it would be a fiction."""
        self._hold()
        gen = self._begin_doa(capsys)             # attempt 1: never joined
        superseded = self._incs()[0]
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen,
                           successor_inc=superseded) == 0
        out = capsys.readouterr().out
        assert not calls and "NO session was stopped" in out
        assert "superseded" in out
        assert superseded not in self._incs()

    def test_complete_supersedes_the_rivals_it_carries(self, sup_home, capsys):
        """The succession is over: a rival that booted after the transfer would
        clobber the NEW holder's HANDSHAKE, so none of them may boot again."""
        self._hold()
        _rc, gen = self._begin(capsys)
        loser = self._incs()[0]
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        winner = self._incs()[1]
        assert _boot_successor("succ0002-full", winner,
                               _token_of(sup_home, winner)) == 0
        capsys.readouterr()
        assert fleet.cmd_sup_handoff_complete(SimpleNamespace(
            sid="sid-old", expect_inc=winner, expect_sid="succ0002-full",
            nonce=gen)) == 0
        capsys.readouterr()
        carried = fleet.handoff_pending_entries(fleet.read_incarnation())
        assert [e["successor_inc"] for e in carried] == [loser]
        assert fleet.handoff_entry_state(carried[0]) == fleet.HANDOFF_SUPERSEDED
        assert carried[0]["superseded_by"] == winner
        rc = _boot_successor("succ0001-full", loser, "tok")
        assert rc == fleet.SUPERVISOR_BOOT_HANDOFF_REFUSED_RC
        capsys.readouterr()

    def test_a_superseded_entry_stops_protecting_its_file_only_past_T(
            self, sup_home, capsys):
        """R9 clause (b), and the bound on rb-MAJ-6: superseded entries are
        never `resolvable-stale`, so without this the list and its token files
        could only ever grow. Inside T the file is still protected -- the body
        may be reading it right now."""
        self._hold()
        _rc, gen = self._begin(capsys)
        superseded = self._incs()[0]
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        name = f"supervisor-handoff-{superseded}.md"
        _age_file(sup_home / "state" / name, 10 * T)
        claim = fleet.read_incarnation()
        assert fleet.handoff_task_files_to_sweep([(name, 10 * T)], claim) == []
        _backdate(superseded, "superseded_at", 2 * T)
        aged = fleet.read_incarnation()
        assert fleet.handoff_task_files_to_sweep([(name, 10 * T)], aged) == [name]
        assert fleet.sweep_handoff_task_files(aged) == [name]

    def test_an_unreadable_superseded_at_keeps_protecting_its_file(
            self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        superseded = self._incs()[0]
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        claim = fleet.read_incarnation()
        fleet.handoff_pending_entries(claim)[0]["superseded_at"] = "not-a-date"
        name = f"supervisor-handoff-{superseded}.md"
        assert fleet.handoff_task_files_to_sweep([(name, 10 * T)], claim) == []


class TestCollideProofSuccessorIds(_HandoffBase):
    """rb-MIN-5: two entries sharing an inc means ONE task file for TWO
    successors, one token overwriting the other, and a single abort retiring
    both -- the double-spawn-on-one-inc shape §4 exists to prevent."""

    def test_a_colliding_mint_is_re_minted(self, sup_home, capsys, monkeypatch):
        self._hold()
        _rc, gen = self._begin(capsys)
        taken = self._incs()[0]
        fresh = "inc-20260724T111111Z-beef"
        minted = iter([taken, taken, fresh])
        monkeypatch.setattr(fleet, "mint_incarnation_id", lambda: next(minted))
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        assert self._incs() == [taken, fresh]

    def test_a_mint_that_only_ever_collides_dispatches_nothing(
            self, sup_home, capsys, monkeypatch):
        self._hold()
        _rc, gen = self._begin(capsys)
        taken = self._incs()[0]
        monkeypatch.setattr(fleet, "mint_incarnation_id", lambda: taken)
        dispatched = []
        def run(argv, **kw):
            dispatched.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        with pytest.raises(fleet.FleetCliError, match="could not mint an unused"):
            self._begin(capsys, nonce=gen, run=run)
        assert not any("--bg" in a for a in dispatched)
        assert self._incs() == [taken]

    def test_an_existing_task_file_also_counts_as_taken(self, sup_home, capsys,
                                                        monkeypatch):
        """The file is the collision that matters: it is the successor's only
        input and it carries the plaintext token."""
        self._hold()
        _orphan(sup_home, DEAD_INC_A)
        fresh = "inc-20260724T222222Z-cafe"
        minted = iter([DEAD_INC_A, fresh])
        monkeypatch.setattr(fleet, "mint_incarnation_id", lambda: next(minted))
        self._begin(capsys)
        assert self._incs() == [fresh]

    def test_appending_a_duplicate_id_is_refused(self):
        claim = {"incarnation_id": "inc-20260724T000000Z-0old"}
        fleet.handoff_pending_append(claim, {"successor_inc": DEAD_INC_A,
                                             "minted_at": fleet.now_iso()})
        with pytest.raises(fleet.FleetCliError, match="second pending successor"):
            fleet.handoff_pending_append(claim, {"successor_inc": DEAD_INC_A,
                                                 "minted_at": fleet.now_iso()})
        assert len(fleet.handoff_pending_entries(claim)) == 1


class TestEntriesMatchOnIdentityNotPosition(_HandoffBase):
    """rb-MIN-6 / N13 / N21."""

    def _claim_with(self, *entries):
        return {"incarnation_id": "inc-20260724T000000Z-0old",
                "handoff_pending": list(entries)}

    def test_N13_naming_a_sid_that_belongs_to_another_attempt_matches_nothing(self):
        """The sid cross-check on an inc match. Dropping it points an abort at
        the entry the INC named while reporting the SID the caller passed."""
        claim = self._claim_with(
            {"successor_inc": DEAD_INC_A, "successor_sid": "sid-A"},
            {"successor_inc": DEAD_INC_B, "successor_sid": "sid-B"})
        assert fleet.handoff_entry_matching(
            claim, successor_sid="sid-B", successor_inc=DEAD_INC_A) is None
        verdict = fleet.resolve_handoff_abort(
            claim, None, successor_sid="sid-B", successor_inc=DEAD_INC_A)
        assert verdict["action"] == "refuse"

    def test_two_entries_sharing_a_sid_are_AMBIGUOUS_not_first_wins(self):
        """LIST ORDER used to decide which live session an abort stopped."""
        claim = self._claim_with(
            {"successor_inc": DEAD_INC_A, "successor_sid": "sid-shared"},
            {"successor_inc": DEAD_INC_B, "successor_sid": "sid-shared"})
        assert fleet.handoff_entry_matching(claim, successor_sid="sid-shared") is None
        assert len(fleet.handoff_entries_matching(claim, successor_sid="sid-shared")) == 2
        verdict = fleet.resolve_handoff_abort(claim, None, successor_sid="sid-shared")
        assert verdict["action"] == "refuse"
        assert "AMBIGUOUS" in verdict["reason"]
        assert DEAD_INC_A in verdict["reason"] and DEAD_INC_B in verdict["reason"]

    def test_the_ambiguous_refusal_stops_no_session(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        claim = fleet.read_incarnation()
        twin = dict(fleet.handoff_pending_entries(claim)[0])
        twin["successor_inc"] = DEAD_INC_B
        claim["handoff_pending"] = fleet.handoff_pending_members(claim) + [twin]
        fleet.write_incarnation(claim)
        calls = []
        with pytest.raises(fleet.FleetCliError, match="AMBIGUOUS"):
            self._abort(run=_stop_ok(calls), nonce=gen, successor_sid="succ0001-full")
        assert not calls
        assert len(self._incs()) == 2

    def test_N21_an_entry_is_dropped_by_its_id_not_by_object_identity(self):
        """Every real caller re-reads the claim under the lock and drops an
        entry it matched in THAT dict -- but `resolve_handoff_abort` hands back
        an entry from the dict the caller read BEFORE the lock. Identity-only
        dropping silently retires nothing and leaves the live token hash
        standing (R4)."""
        claim = self._claim_with({"successor_inc": DEAD_INC_A,
                                  "successor_sid": "sid-A", "minted_at": "x"},
                                 {"successor_inc": DEAD_INC_B,
                                  "successor_sid": "sid-B", "minted_at": "x"})
        claim["handoff_token_hash"] = "sha256-of-something"
        detached = dict(claim["handoff_pending"][0])      # same id, other object
        assert detached is not claim["handoff_pending"][0]
        fleet.drop_handoff_entry(claim, detached)
        assert [e["successor_inc"]
                for e in fleet.handoff_pending_entries(claim)] == [DEAD_INC_B]
        other = dict(claim["handoff_pending"][0])
        fleet.drop_handoff_entry(claim, other)
        assert fleet.handoff_pending_entries(claim) == []
        assert "handoff_token_hash" not in claim, \
            "R4: the last entry retiring takes the live token hash with it"

    def test_a_sidless_entry_answers_to_no_sid(self):
        claim = self._claim_with({"successor_inc": DEAD_INC_A, "successor_sid": None})
        assert fleet.handoff_entry_matching(claim, successor_sid="sid-A") is None
        assert fleet.handoff_entry_matching(claim, successor_inc=DEAD_INC_A) is not None


class TestTornPendingMembersFailClosed:
    """rb-MIN-7: a torn entry failed OPEN while a torn claim failed CLOSED --
    inside a predicate whose whole doctrine is fail-closed."""

    CLAIM = "inc-20260724T045450Z-0dea"

    def _claim(self, *members):
        return {"incarnation_id": self.CLAIM, "handoff_pending": list(members)}

    def test_an_unreadable_member_protects_every_task_file(self):
        candidates = [(f"supervisor-handoff-{DEAD_INC_B}.md", 10 * T),
                      ("supervisor-handoff-inc-20260724T082006Z-696e.md", 10 * T)]
        readable = self._claim({"successor_inc": DEAD_INC_B, "minted_at": "x"})
        assert fleet.handoff_task_files_to_sweep(candidates, readable) == \
            ["supervisor-handoff-inc-20260724T082006Z-696e.md"]
        for torn in ("not-a-dict", None, 7, {"successor_sid": "sid-x"},
                     {"successor_inc": ""}):
            claim = self._claim({"successor_inc": DEAD_INC_B, "minted_at": "x"}, torn)
            assert fleet.handoff_task_files_to_sweep(candidates, claim) == [], torn

    def test_torn_members_are_reported_not_silently_dropped(self):
        claim = self._claim({"successor_inc": DEAD_INC_B}, "torn", {"x": 1})
        assert len(fleet.handoff_pending_entries(claim)) == 1
        assert fleet.handoff_pending_torn(claim) == ["torn", {"x": 1}]
        assert len(fleet.handoff_pending_members(claim)) == 3

    def test_a_torn_member_survives_a_claim_transition(self):
        old = self._claim({"successor_inc": DEAD_INC_B}, "torn")
        fresh = {"incarnation_id": "inc-20260724T090000Z-new0"}
        fleet._carry_handoff_pending(old, fresh)
        assert fleet.handoff_pending_torn(fresh) == ["torn"]

    def test_a_torn_member_survives_a_per_entry_retirement(self):
        claim = self._claim({"successor_inc": DEAD_INC_B}, "torn")
        claim["handoff_token_hash"] = "live"
        fleet.drop_handoff_entry(claim, {"successor_inc": DEAD_INC_B})
        assert fleet.handoff_pending_torn(claim) == ["torn"]
        assert claim["handoff_token_hash"] == "live", \
            "an unreadable member may still name an attempt: fail closed"

    def test_the_doctor_moves_its_verdict_on_a_torn_member(self, sup_home):
        fleet.write_incarnation(self._claim({"successor_inc": DEAD_INC_B,
                                             "successor_sid": "sid-A"}, "torn"))
        _name, ok, detail = fleet._doctor_check_supervisor_handoff()
        assert ok is False
        assert "unreadable pending member" in detail


class TestClockStepBack:
    """rb-MIN-8: a `minted_at` in the FUTURE pinned an entry at `joining`
    forever -- no verb retired it and its token file was immortal."""

    def _entry(self, offset_seconds):
        return {"successor_inc": DEAD_INC_A, "minted_at":
                (fleet.datetime.now(fleet.timezone.utc)
                 + fleet.timedelta(seconds=offset_seconds)).strftime(
                     "%Y-%m-%dT%H:%M:%SZ")}

    def test_a_far_future_stamp_ages_out_at_once(self):
        assert fleet.handoff_entry_state(self._entry(4 * T)) == \
            fleet.HANDOFF_RESOLVABLE_STALE

    def test_ordinary_skew_is_left_to_the_clock(self):
        """A stamp a few seconds ahead is skew between two writers, not a step
        back, and it resolves itself in seconds."""
        assert fleet.handoff_entry_state(self._entry(5)) == fleet.HANDOFF_JOINING
        assert fleet.handoff_entry_state(self._entry(T - 5)) == fleet.HANDOFF_JOINING

    def test_the_operator_can_then_retire_it(self, sup_home, capsys):
        beat = fleet.now_iso()
        claim = {"incarnation_id": "inc-20260724T000000Z-0old", "session_id": "sid-old",
                 "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
                 "handoff_pending": [self._entry(4 * T)],
                 "handoff_token_hash": "live"}
        fleet.write_incarnation(claim)
        args = SimpleNamespace(sid="sid-old", nonce=None, successor_sid=None,
                               successor_inc=DEAD_INC_A, force=False, retire_all=False)
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok()) == 0
        assert fleet.handoff_pending_entries(fleet.read_incarnation()) == []
        assert "handoff_token_hash" not in fleet.read_incarnation()


class TestForcedRetire(_HandoffBase):
    """rs-MIN-B: an entry with an unreadable `minted_at` resolves by neither
    evidence nor time -- the one shape that defeats the thesis of R3."""

    def _wreck_minted_at(self, inc):
        claim = fleet.read_incarnation()
        for entry in fleet.handoff_pending_entries(claim):
            if entry["successor_inc"] == inc:
                entry["minted_at"] = "whenever"
        fleet.write_incarnation(claim)

    def test_without_force_it_is_refused_and_the_refusal_names_force(
            self, sup_home, capsys):
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        self._wreck_minted_at(inc)
        with pytest.raises(fleet.FleetCliError, match="--force"):
            self._abort(nonce=gen, successor_inc=inc)
        assert self._incs() == [inc]

    def test_force_retires_it_and_stops_nothing(self, sup_home, capsys):
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        self._wreck_minted_at(inc)
        task_file = sup_home / "state" / f"supervisor-handoff-{inc}.md"
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen, successor_inc=inc,
                           force=True) == 0
        out = capsys.readouterr().out
        assert not calls and "NO session was stopped" in out and "--force" in out
        assert self._incs() == []
        assert not task_file.exists()
        assert "handoff_token_hash" not in fleet.read_incarnation()

    def test_force_never_overrides_the_handshake_cross_check(self, sup_home, capsys):
        """`--force` is a retirement lever, not a stop-anything lever."""
        self._hold()
        _rc, gen = self._begin(capsys)
        fleet.write_handshake("inc-20260724T090000Z-abcd", "sid-from-handshake")
        calls = []
        with pytest.raises(fleet.FleetCliError, match="does not match HANDSHAKE sid"):
            self._abort(run=_stop_ok(calls), nonce=gen, successor_sid="succ0001-full",
                        force=True)
        assert not calls


class TestRetireAll(_HandoffBase):
    """rb-MAJ-6: retirement was O(N) manual aborts, and N was three inside
    sixteen minutes on the real sequence -- each one pinning a live token."""

    def test_it_retires_every_sidless_entry_in_one_write(self, sup_home, capsys):
        self._hold()
        gen = self._begin_doa(capsys, short_id="nope0001")
        first = self._incs()[0]
        gen2 = self._begin_doa(capsys, nonce=gen, short_id="nope0002")
        second = self._incs()[1]
        # first: superseded by the second. second: aged out of its join window.
        _age_entry(second, 2 * T)
        assert self._abort(nonce=gen2, retire_all=True) == 0
        out = capsys.readouterr().out
        assert "retired 2 pending successor(s)" in out
        assert first in out and second in out
        assert "NO session was stopped" in out
        assert self._incs() == []
        assert "handoff_token_hash" not in fleet.read_incarnation()
        assert not list((sup_home / "state").glob("supervisor-handoff-*.md"))
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"

    def test_an_entry_bearing_a_sid_is_left_standing_with_its_own_recipe(
            self, sup_home, capsys):
        """Stopping a session is a per-body decision with a `claude stop`
        behind it. This verb never stops anything."""
        self._hold()
        _rc, gen = self._begin(capsys)                       # joins: has a sid
        live = self._incs()[0]
        gen2 = self._begin_doa(capsys, nonce=gen, short_id="nope0002")
        _age_entry(self._incs()[1], 2 * T)      # the sid-less one is retirable
        calls = []
        assert self._abort(run=_stop_ok(calls), nonce=gen2, retire_all=True) == 0
        out = capsys.readouterr().out
        assert not calls
        assert f"STILL STANDING: {live}" in out
        assert "--successor-sid succ0001-full" in out and "--nonce" in out
        assert self._incs() == [live]

    def test_it_clears_torn_members_that_block_the_sweep(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        claim = fleet.read_incarnation()
        claim["handoff_pending"] = fleet.handoff_pending_members(claim) + ["torn"]
        fleet.write_incarnation(claim)
        assert self._abort(nonce=gen, retire_all=True, force=True) == 0
        out = capsys.readouterr().out
        assert "unreadable pending member" in out
        assert fleet.handoff_pending_torn(fleet.read_incarnation()) == []

    def test_a_live_handshake_refuses_the_whole_call(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        inc = self._incs()[0]
        fleet.write_handshake(inc, "succ0001-full")
        with pytest.raises(fleet.FleetCliError, match="HANDSHAKE is present"):
            self._abort(nonce=gen, retire_all=True)
        assert self._incs() == [inc]

    def test_nothing_retirable_refuses_and_says_what_stands(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        with pytest.raises(fleet.FleetCliError, match="nothing to retire"):
            self._abort(nonce=gen, retire_all=True)
        assert len(self._incs()) == 1

    def test_it_takes_no_handle(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        with pytest.raises(fleet.FleetCliError, match="takes no handle"):
            self._abort(nonce=gen, retire_all=True, successor_inc=self._incs()[0])

    def test_the_parser_exposes_both_levers(self):
        args = fleet.build_parser().parse_args(
            ["sup-handoff-abort", "--retire-all", "--force"])
        assert args.retire_all is True and args.force is True


class TestDoctorMovesItsVerdict(_HandoffBase):
    """rb-MAJ-6 second half / rs-MIN-A: `begin` clears the abort flag that used
    to make doctor FAIL, so N stranded plaintext tokens read as PASS."""

    def test_a_resolvable_stale_entry_fails_the_row(self, sup_home, capsys):
        self._hold()
        self._begin_doa(capsys)
        inc = self._incs()[0]
        _age_entry(inc, 2 * T)
        _name, ok, detail = fleet._doctor_check_supervisor_handoff()
        assert ok is False
        assert inc in detail and "--retire-all" in detail

    def test_a_superseded_entry_fails_the_row(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        self._begin(capsys, nonce=gen,
                    run=_dispatch_then_roster("succ0002-full", "succ0002"))
        _name, ok, detail = fleet._doctor_check_supervisor_handoff()
        assert ok is False and fleet.HANDOFF_SUPERSEDED in detail

    def test_a_healthy_in_flight_attempt_still_passes(self, sup_home, capsys):
        """The row must not cry wolf at every handoff: one live attempt, no
        flag, no stale HANDSHAKE, is a PASS."""
        self._hold()
        self._begin(capsys)
        if fleet.handoff_abort_flag_path().exists():
            fleet.handoff_abort_flag_path().unlink()
        _name, ok, _detail = fleet._doctor_check_supervisor_handoff()
        assert ok is True

    def test_the_verdict_survives_an_unreadable_claim(self, sup_home):
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        _name, ok, _detail = fleet._doctor_check_supervisor_handoff()
        assert ok is True


class TestStatusPrintsTheRecipeThatWorks(_HandoffBase):
    """rs-MIN-C: the plain form printed an abort recipe that is REFUSED inside
    the join window -- the operator's first move mid-incident was a refusal."""

    def test_a_joining_entry_says_when_it_becomes_retirable(self, sup_home, capsys):
        self._hold()
        self._begin_doa(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "still joining" in out and "retirable at" in out
        assert re.search(r"retirable at 20\d\d-\d\d-\d\dT", out)

    def test_an_unageable_entry_is_told_to_use_force(self, sup_home, capsys):
        self._hold()
        self._begin_doa(capsys)
        claim = fleet.read_incarnation()
        fleet.handoff_pending_entries(claim)[0]["minted_at"] = "whenever"
        fleet.write_incarnation(claim)
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "--force" in out and "never age out" in out

    def test_a_sid_bearing_entry_keeps_the_recipe_that_works_now(
            self, sup_home, capsys):
        self._hold()
        self._begin(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=False)) == 0
        out = capsys.readouterr().out
        assert "abort with `fleet sup-handoff-abort --successor-sid succ0001-full" in out


class TestDeadCodeIsGone:
    def test_rs_MIN_D_read_handoff_abort_flag_is_deleted(self):
        """R7 deleted its only caller. A reader with no callers is a standing
        invitation to route a decision back through a record no begin path ever
        writes a sid into."""
        assert not hasattr(fleet, "read_handoff_abort_flag")


def _make_escaping_path(link: Path, target_dir: Path):
    """Plant a real filesystem escape at `link` -- a path INSIDE `state/` whose
    `resolve()` lands somewhere else. A symlink where the platform allows one
    (POSIX always; Windows only with the privilege), otherwise a Windows
    directory junction, which needs no privilege and is resolved by
    `Path.resolve()` exactly like a symlink.

    Both are the R6 threat model, not a contrivance: anything that can write
    into `state/` can plant one, and the incarnation id in a HANDSHAKE is
    written by the SUCCESSOR."""
    try:
        os.symlink(str(target_dir), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name == "nt":
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link),
                               str(target_dir)], capture_output=True, text=True)
        if proc.returncode == 0 and link.exists():
            return
    pytest.skip("no way to create a resolving escape (symlink/junction) here")


class TestR10MutationSurvivors(_HandoffBase):
    """R10 -- the eight mutations that survived the full wave-2 suite. Each
    test below goes RED under exactly one of them, mutate-red-restore.

    N13 (sid cross-check dropped on an inc match) and N21 (drop by object
    identity instead of by inc) are killed by
    `TestEntriesMatchOnIdentityNotPosition`, where the fix that made them
    reachable lives (rb-MIN-6). The other six are here.

    N23 + N38 + N24 + N32 are the sharp ones: three round-1 fixes shipped with
    NO test that dies when the fix is removed. R6's containment was exercised
    only through `valid_incarnation_id`, which cannot reach the containment
    branch at all, and rb-MIN-2's best-effort marker drop had no failing-lock
    test."""

    def test_N09_the_stale_boundary_is_strictly_PAST_the_timeout(self):
        """N09: `age > timeout` flipped to `>=`. An entry at exactly T is a
        join that has just run out of window, not one that ran out -- and the
        boundary is the moment an operator's `--successor-inc` starts deleting
        a task file, so which side owns the instant is not decoration."""
        # second precision on BOTH sides: `minted_at` is written by strftime,
        # so a `now` carrying microseconds would put the boundary case a
        # fraction past T and test nothing.
        now = fleet.datetime.now(fleet.timezone.utc).replace(microsecond=0)
        def at(age):
            return {"successor_inc": DEAD_INC_A,
                    "minted_at": (now - fleet.timedelta(seconds=age)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ")}
        assert fleet.handoff_entry_state(at(T), now=now) == fleet.HANDOFF_JOINING
        assert fleet.handoff_entry_state(at(T - 1), now=now) == fleet.HANDOFF_JOINING
        assert fleet.handoff_entry_state(at(T + 1), now=now) == \
            fleet.HANDOFF_RESOLVABLE_STALE

    def test_N23_a_path_that_RESOLVES_outside_the_state_dir_is_refused(
            self, sup_home, capsys):
        """N23: the containment check deleted. The id shape-check cannot cover
        this -- the id here is perfectly well-formed; it is the FILESYSTEM that
        redirects, which is precisely why `handoff_task_file_path` has a second
        half that does not depend on the regex being exhaustive."""
        outside = sup_home / "outside"
        outside.mkdir()
        (outside / "victim.md").write_text("do not delete me", encoding="utf-8")
        inc = DEAD_INC_A
        link = sup_home / "state" / f"supervisor-handoff-{inc}.md"
        _make_escaping_path(link, outside)
        assert link.resolve() != link, "the escape did not take"
        with pytest.raises(fleet.FleetCliError,
                           match="refusing a handoff task path outside"):
            fleet.handoff_task_file_path(inc)
        assert fleet.unlink_handoff_task_file(inc, context=" (abort)") is False
        assert (outside / "victim.md").exists()
        assert "WARNING" in capsys.readouterr().out

    def test_N38_containment_compares_RESOLVED_roots(self, tmp_path, monkeypatch):
        """N38: `path.parent != root.resolve()` mutated to `path.parent != root`.
        The left side is always resolved, so dropping the right side's resolve
        makes every legitimate path look like an escape the moment the fleet
        home reaches `state/` through anything the filesystem normalizes -- and
        then complete, abort and begin all refuse to unlink the file that
        carries the plaintext token. A fail-closed check that fails closed on
        the happy path is a retention failure, not a defense."""
        home = tmp_path / "home"
        (home / "state").mkdir(parents=True)
        (home / "sub").mkdir()
        monkeypatch.setattr(fleet, "FLEET_HOME", home / "sub" / "..")
        inc = fleet.mint_incarnation_id()
        path = fleet.handoff_task_file_path(inc)
        assert path.parent == (home / "state").resolve()
        assert path.name == f"supervisor-handoff-{inc}.md"

    def test_N24_an_unremovable_token_file_is_REPORTED_not_swallowed(
            self, sup_home, capsys, monkeypatch):
        """N24: the `OSError` arm of `unlink_handoff_task_file` mutated back to
        a silent `return False`. Only a MISSING file may be silent -- a file we
        could not remove is the §5.9 retention failure itself, and it is
        exactly the case nobody would ever see."""
        _orphan(sup_home, DEAD_INC_A)
        real_unlink = Path.unlink
        def boom(self, *a, **kw):
            if self.name.endswith(f"{DEAD_INC_A}.md"):
                raise PermissionError(13, "file is locked")
            return real_unlink(self, *a, **kw)
        monkeypatch.setattr(Path, "unlink", boom)
        assert fleet.unlink_handoff_task_file(
            DEAD_INC_A, context=" (handoff abort)") is False
        out = capsys.readouterr().out
        assert "WARNING" in out and DEAD_INC_A in out
        assert "handoff token" in out and "(handoff abort)" in out

    def test_N29_the_HANDSHAKE_inc_cross_check_refuses_a_mismatch(self):
        """N29: the inc arm of the HANDSHAKE cross-check dropped, leaving only
        the sid arm. `--successor-inc` is the handle the doctor NOTE and the
        stale-entry recipe both print, so it is the one an operator reaches for
        mid-incident -- and with the check gone it stops whatever session the
        HANDSHAKE happens to name, which is the wrong body by construction."""
        claim = {"incarnation_id": "inc-20260724T000000Z-0old"}
        hs = {"incarnation_id": DEAD_INC_A, "session_id": "sid-from-handshake"}
        verdict = fleet.resolve_handoff_abort(claim, hs, successor_inc=DEAD_INC_B)
        assert verdict["action"] == "refuse"
        assert "does not match HANDSHAKE inc" in verdict["reason"]
        assert fleet.resolve_handoff_abort(
            claim, hs, successor_inc=DEAD_INC_A)["action"] == "stop"

    def test_N32_a_failed_marker_drop_never_replaces_the_real_diagnosis(
            self, sup_home, capsys, monkeypatch):
        """N32: `_drop_pending_marker`'s `except (FleetCliError, OSError)`
        removed. Every caller is already raising a `FleetCliError` that names
        the real failure -- the dispatch that did not happen -- so a lock
        timeout or an unwritable claim in the CLEANUP must not surface instead
        of it. The operator would then be told the claim is unwritable and
        never told the successor was never launched."""
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        real_write = fleet.write_incarnation
        writes = {"n": 0}
        def wedged(claim):
            writes["n"] += 1
            if writes["n"] > 1:          # the begin write lands; the cleanup does not
                raise OSError(5, "INCARNATION is unwritable")
            return real_write(claim)
        monkeypatch.setattr(fleet, "write_incarnation", wedged)
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None,
                               nonce=None)
        with pytest.raises(fleet.FleetCliError, match="successor dispatch failed"):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                        sleep=lambda s: None)
        out = capsys.readouterr().out
        assert "WARNING: could not clear the pending entry" in out
        assert writes["n"] > 1, "the cleanup never attempted the write it must survive"


class TestEveryAdmittedBodyReachesATerminalState(_HandoffBase):
    """R1 of the 2026-07-26 council ruling, and the rule the council produced:

        Assert on the LAST verb of the sequence the change exists to enable --
        not on the precondition the change manipulates.

    `cb9f078` un-superseded the entries a dispatch-failed begin had marked, and
    its gate asserted the earlier attempt was *bootable*. Bootability is a
    precondition nobody wants for its own sake. The sequence a body actually
    runs to collect the claimed benefit is `begin` -> *fail at dispatch* ->
    `sup-boot` -> **`sup-handoff-complete`**, and on the resurrected attempt
    that LAST verb refused under every input: part 3 of the failed `begin`'s
    write had already overwritten `handoff_token_hash` with the dead attempt's,
    `sha(tokA)` is absent from the entire claim, and the only surviving copy of
    token A is the plaintext in the successor's own task file -- so there is
    nothing to restore it from. The un-supersede therefore admitted a body it
    could not carry to any terminal state; it wrote a HANDSHAKE nobody could
    act on and failed two verbs later with a message that was factually false
    about that body.

    The counterfactual, which is what this asserts: the body is refused at its
    own `sup-boot` with `rc=5` and operator-actionable TERMINATE text.

    Corollary, and it is the general rule: a state-machine change must drive
    every newly admitted body to a terminal state.
    """

    def _dispatch_fails(self, argv, **kw):
        if "--bg" in argv:
            return SimpleNamespace(returncode=1, stdout="", stderr="boom")
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    def test_a_dispatch_failure_admits_no_body_it_cannot_terminate(
            self, sup_home, capsys):
        """Drive EVERY attempt the claim still records through both remaining
        verbs of the sequence, and assert each one's terminal outcome."""
        self._hold()
        _rc, gen = self._begin(capsys)                # attempt 1: live, joined
        first = self._incs()[0]
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None,
                               nonce=gen)
        with pytest.raises(fleet.FleetCliError, match="successor dispatch failed"):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which,   # attempt 2 dies
                                        run=self._dispatch_fails,
                                        sleep=lambda s: None)
        capsys.readouterr()
        recorded = self._incs()
        assert recorded == [first], \
            "R1 keeps the collection: attempt 1 stays recorded and abortable"
        for inc in recorded:
            rc = _boot_successor("succ0001-full", inc, _token_of(sup_home, inc))
            out = capsys.readouterr().out
            assert rc == fleet.SUPERVISOR_BOOT_HANDOFF_REFUSED_RC, \
                f"{inc} booted -- a body was admitted that no verb can complete"
            assert "VERDICT: handoff-refused" in out
            assert f"HANDOFF-ORPHAN {inc}" in out, \
                "the refusal must be legible to a BODY: it says terminate"
            assert fleet.read_handshake() is None
            with pytest.raises(fleet.FleetCliError, match="no supervisor/HANDSHAKE"):
                fleet.cmd_sup_handoff_complete(SimpleNamespace(
                    sid="sid-old", nonce=gen, expect_inc=inc, expect_sid=None))

    def test_the_dead_attempts_own_entry_and_token_file_are_gone(
            self, sup_home, capsys):
        """The half of `_drop_pending_marker` that survives the revert: this
        attempt launched no process, so its own entry and the plaintext token
        with it are retired. Only the un-supersede goes."""
        self._hold()
        _rc, gen = self._begin(capsys)
        first = self._incs()[0]
        before = set((sup_home / "state").glob("supervisor-handoff-*.md"))
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None,
                               nonce=gen)
        with pytest.raises(fleet.FleetCliError, match="successor dispatch failed"):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which,
                                        run=self._dispatch_fails,
                                        sleep=lambda s: None)
        capsys.readouterr()
        assert set((sup_home / "state").glob("supervisor-handoff-*.md")) == before
        assert (sup_home / "state" / f"supervisor-handoff-{first}.md").exists(), \
            "attempt 1's only input file is not attempt 2's to delete"


class TestForceConsultsTheAgeItClaimsToHaveConsulted(_HandoffBase):
    """MAJOR-2. `--force` exists for exactly one shape: an entry that records
    no sid AND whose `minted_at` cannot be read, which resolves by neither
    evidence nor time and would otherwise be immortal (rs-MIN-B). Three
    surfaces say so -- the flag's own help, `resolve_handoff_abort`'s arm 4,
    and `--retire-all`'s docstring -- and the retire message says so *while it
    prints*: "it recorded no sid and could not be aged".

    The code never evaluated that predicate. On a readable, fresh, sid-less
    entry `--force` retired a still-joining successor and unlinked its ONLY
    input file, then printed a reason it had not checked. This is the
    fail-closed narrowing that makes the code match the three surfaces."""

    def test_force_is_refused_on_an_entry_that_can_be_aged(self, sup_home, capsys):
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        task_file = sup_home / "state" / f"supervisor-handoff-{inc}.md"
        with pytest.raises(fleet.FleetCliError, match="still inside the") as exc:
            self._abort(nonce=gen, successor_inc=inc, force=True)
        assert "--force does not apply" in str(exc.value), \
            "a declined --force must say it was declined and why"
        assert self._incs() == [inc]
        assert task_file.exists(), "a still-joining successor keeps its only input"

    def test_retire_all_force_leaves_an_ageable_joining_entry_standing(
            self, sup_home, capsys):
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        with pytest.raises(fleet.FleetCliError, match="nothing to retire") as exc:
            self._abort(nonce=gen, retire_all=True, force=True)
        assert "not a way out of the join window" in str(exc.value), \
            "the recipe must not advertise --force as a way out of the window"
        assert self._incs() == [inc]
        assert (sup_home / "state" / f"supervisor-handoff-{inc}.md").exists()

    def test_retire_all_force_still_takes_the_unageable_entry(
            self, sup_home, capsys):
        """Positive control: the narrowing must not reach the one shape
        `--force` was built for."""
        self._hold()
        gen = self._begin_doa(capsys)
        inc = self._incs()[0]
        claim = fleet.read_incarnation()
        fleet.handoff_pending_entries(claim)[0]["minted_at"] = "whenever"
        fleet.write_incarnation(claim)
        assert self._abort(nonce=gen, retire_all=True, force=True) == 0
        assert self._incs() == []
        assert not (sup_home / "state" / f"supervisor-handoff-{inc}.md").exists()
