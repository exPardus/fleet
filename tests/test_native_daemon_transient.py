"""claude 2.1.212 transient-daemon contract (docs/reviews/
CLAUDE-2.1.212-CONTRACT-2026-07-17.md).

Pins the failure-message taxonomy of `claude rm`/`claude stop` and the
hygiene-path behavior it forces. These are unit tests over injected `run`
stubs, so the taxonomy stays pinned without a live daemon.

PROVENANCE, precisely (M4 fix wave, review MD-CONTRACT-REVIEW-2026-07-17.md).
The earlier version of this docstring claimed every stub was "copied VERBATIM
from the live probes". That was true of `RM_OK`, `RM_GONE` and `STOP_GONE`
(re-run and confirmed byte-identical by the reviewer, receipts R1/R2/R3) and
FALSE of the one stub that matters, `RM_TRANSIENT`: the dead-daemon state is
unreachable from a --bg session (findings §Q2), so nobody in this evidence
chain has ever held those bytes. The tell was in the same commit -- three
transcriptions of that message, two different dashes. A verbatim capture
cannot disagree with itself. Each stub below now carries its own provenance
tag; do not relabel a manager report as a live probe.

Why this file exists (findings §Q2/§Q3): `rc=1` from `claude rm` is
three-way ambiguous at 2.1.212 -- already-gone (success-equivalent),
dead-daemon (retryable), or a real failure -- and the message is the only
discriminator. Fleet's hygiene tier (`fleet archive`, the autoclean
scheduled task) is BY CONSTRUCTION the code path most likely to meet a
dead daemon: it only ever runs against workers that are not live, which is
exactly the zero-live-worker state in which the transient daemon has
idle-exited.
"""
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

import fleet

SID = "aaaa1111-1111-2222-3333-444455556666"

# ---------------------------------------------------------------------------
# [OBSERVED 2.1.212 — live probe, findings §Q3] Exit codes and message text
# copied from probe output -- do not "tidy" them.
# ---------------------------------------------------------------------------
RM_OK = types.SimpleNamespace(returncode=0, stdout="removed aaaa1111", stderr="")
RM_GONE = types.SimpleNamespace(returncode=1, stdout="No job matching 'aaaa1111'", stderr="")
STOP_GONE = types.SimpleNamespace(
    returncode=1,
    stdout="No job matching 'aaaa1111'. Run 'claude agents' to list running sessions.",
    stderr="")

# [OBSERVED interactive 2026-07-17 manager session — NOT RE-OBSERVED HERE]
# The dead-daemon state is unreachable from a --bg session: the daemon cannot
# idle-exit while a bg session holds it open, and reaching it needs either
# `claude daemon stop` (banned -- machine-wide blast radius) or ending sessions
# we do not own (findings §Q2). TWO independent waves have now failed to reach
# it -- the builder and the reviewer, who is also a --bg session. The exact
# bytes, the rc, and even the stream (stdout vs stderr) of this message are a
# MANAGER REPORT, not a capture.
#
# This is why `_NATIVE_CLI_TRANSIENT_RE` deliberately matches ONLY the
# dash-free middle phrase "background service may be restarting": the wording
# and punctuation around it are exactly the parts nobody has verified. The
# em-dash below is a transcription choice, NOT evidence -- the regex spans it
# on neither side, and `test_transient_matches_regardless_of_dash_style` pins
# that. If a drift ever escapes the regex anyway, the unknown shape falls to
# `failed`, which is behaviourally identical to `daemon-transient` on every
# axis that touches state -- pinned by
# `TestUnknownMessageShapeFailsSafe`. Diagnosis degrades; correctness does not.
RM_TRANSIENT = types.SimpleNamespace(
    returncode=1,
    stdout="",
    stderr="couldn't remove aaaa1111 — the background service may be "
           "restarting. Try again in a moment.")
RM_UNKNOWN = types.SimpleNamespace(returncode=1, stdout="", stderr="kaboom")


class TestNativeCliClassifier:
    """The discriminator itself. rc alone is NOT enough (findings §Q3)."""

    def test_zero_exit_is_ok(self):
        assert fleet._classify_native_cli_result(RM_OK) == "ok"

    def test_no_job_matching_is_gone_not_failed(self):
        # G12's "idempotent on an already-gone id" is REFUTED: rc=1 with this
        # message means the sid ALREADY reached the desired end state.
        assert fleet._classify_native_cli_result(RM_GONE) == "gone"

    def test_stop_gone_message_variant_also_classifies_gone(self):
        # `claude stop` appends a hint sentence the `rm` message lacks.
        assert fleet._classify_native_cli_result(STOP_GONE) == "gone"

    def test_may_be_restarting_is_daemon_transient(self):
        assert fleet._classify_native_cli_result(RM_TRANSIENT) == "daemon-transient"

    def test_unknown_nonzero_is_failed(self):
        assert fleet._classify_native_cli_result(RM_UNKNOWN) == "failed"

    def test_transient_wins_over_gone_if_both_appear(self):
        both = types.SimpleNamespace(
            returncode=1, stdout="No job matching 'x'",
            stderr="the background service may be restarting")
        # Retryable must never be downgraded to "already clean" -- that would
        # silently claim success for a husk that is still on the roster.
        assert fleet._classify_native_cli_result(both) == "daemon-transient"

    def test_transient_matches_regardless_of_dash_style(self):
        """M4: the transient message's exact bytes are a manager report, not a
        capture -- so the regex must not depend on the parts nobody verified.
        It matches only the dash-free middle phrase; every dash style, and the
        wording around it, is free to drift."""
        for dash in ("—", "-", "–", ":", ""):
            proc = types.SimpleNamespace(
                returncode=1, stdout="",
                stderr=f"couldn't remove aaaa1111 {dash} the background service "
                       f"may be restarting. Try again in a moment.")
            assert fleet._classify_native_cli_result(proc) == "daemon-transient", (
                f"dash style {dash!r} broke the match")

    def test_stream_and_case_do_not_matter(self):
        """Provenance again (M4): nobody has verified whether the transient
        message lands on stdout or stderr. Both must classify."""
        on_stdout = types.SimpleNamespace(
            returncode=1, stdout="The Background Service May Be Restarting", stderr="")
        assert fleet._classify_native_cli_result(on_stdout) == "daemon-transient"


class TestUnknownMessageShapeFailsSafe:
    """M4(c): the guarantee that makes the thin provenance survivable -- an
    unrecognised message degrades DIAGNOSIS, never CORRECTNESS. Pinned as
    contract rather than left as an accident of structure for the next
    reviewer to rediscover."""

    THIRD_SHAPE = types.SimpleNamespace(
        returncode=1, stdout="",
        stderr="El servicio en segundo plano se está reiniciando")  # locale drift

    def test_unknown_shape_is_not_success(self):
        ok, outcome = fleet._rm_native_session_status(
            SID, run=lambda *a, **k: self.THIRD_SHAPE, which=lambda _: "claude")
        assert (ok, outcome) == (False, "failed")

    def test_unknown_shape_never_claims_a_removal(self, home):
        """The state-touching axis: no husk_removed event, not counted in
        `removed`, husk stays -- identical to daemon-transient."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], self.THIRD_SHAPE)
        removed, deferred = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert removed == []
        assert deferred == [SID_HUSK]
        kinds = [json.loads(ln)["kind"]
                 for ln in fleet.events_path().read_text(encoding="utf-8").splitlines() if ln]
        assert "husk_removed" not in kinds

    def test_unknown_shape_is_deferred_exactly_like_transient(self, home):
        """Behavioural equivalence, stated as an assertion: the ONLY difference
        a locale drift may cause is the operator-facing note text."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        unknown = fleet._sweep_husks(
            False, run=_run_factory([_roster_dead(SID_HUSK)], self.THIRD_SHAPE),
            which=lambda _: "claude")
        transient = fleet._sweep_husks(
            False, run=_run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT),
            which=lambda _: "claude")
        assert unknown == transient == ([], [SID_HUSK])


class TestRmNativeSessionStatus:
    def _run_for(self, proc, calls=None):
        def run(argv, **kwargs):
            if calls is not None:
                calls.append(argv)
            return proc
        return run

    def test_ok(self):
        ok, outcome = fleet._rm_native_session_status(
            SID, run=self._run_for(RM_OK), which=lambda _: "claude")
        assert (ok, outcome) == (True, "ok")

    def test_gone_counts_as_success(self):
        # 2.1.212 contract change [PENDING-RATIFICATION]: an already-removed
        # sid is the archive's desired end state, not a failure to report.
        # Evidence: findings §Q3 (`claude rm 0a208ce0` twice -> rc=1
        # "No job matching '0a208ce0'").
        ok, outcome = fleet._rm_native_session_status(
            SID, run=self._run_for(RM_GONE), which=lambda _: "claude")
        assert (ok, outcome) == (True, "gone")

    def test_gone_short_circuits_the_full_sid_retry(self):
        # findings §Q3: the full-uuid retry returns the SAME "No job matching"
        # -- a second doomed subprocess per already-clean sid, per archive pass.
        calls = []
        fleet._rm_native_session_status(SID, run=self._run_for(RM_GONE, calls),
                                        which=lambda _: "claude")
        assert len(calls) == 1, f"expected 1 call, got {[c[1:] for c in calls]}"
        assert calls[0][2] == "aaaa1111"

    def test_daemon_transient_is_not_success(self):
        ok, outcome = fleet._rm_native_session_status(
            SID, run=self._run_for(RM_TRANSIENT), which=lambda _: "claude")
        assert (ok, outcome) == (False, "daemon-transient")

    def test_transient_does_not_retry_with_full_sid(self):
        # A dead daemon rejects the full sid identically; retrying only doubles
        # the stall on a scheduled autoclean run.
        calls = []
        fleet._rm_native_session_status(SID, run=self._run_for(RM_TRANSIENT, calls),
                                        which=lambda _: "claude")
        assert len(calls) == 1

    def test_unknown_failure_still_retries_full_sid(self):
        # Belt-and-braces path from the T12 fix wave survives: only the two
        # message-classified outcomes short-circuit it.
        calls = []
        ok, outcome = fleet._rm_native_session_status(
            SID, run=self._run_for(RM_UNKNOWN, calls), which=lambda _: "claude")
        assert (ok, outcome) == (False, "failed")
        assert [c[2] for c in calls] == ["aaaa1111", SID]

    def test_claude_missing_is_not_a_crash(self):
        def which(_):
            return None
        ok, outcome = fleet._rm_native_session_status(SID, run=self._run_for(RM_OK),
                                                      which=which)
        assert (ok, outcome) == (False, "no-claude")

    def test_subprocess_error_is_not_a_crash(self):
        def boom(argv, **kwargs):
            raise OSError("spawn failed")
        ok, outcome = fleet._rm_native_session_status(SID, run=boom,
                                                      which=lambda _: "claude")
        assert (ok, outcome) == (False, "error")

    def test_bool_wrapper_keeps_its_contract(self):
        # Every existing caller reads the bool; "gone" must read as True there
        # too, or an already-clean sid keeps getting reported as a failure.
        assert fleet._rm_native_session(SID, run=self._run_for(RM_GONE),
                                        which=lambda _: "claude") is True
        assert fleet._rm_native_session(SID, run=self._run_for(RM_TRANSIENT),
                                        which=lambda _: "claude") is False


# ---------------------------------------------------------------------------
# Hygiene paths: never crash, never silently claim success, husk stays for the
# next pass (the brief's required adaptation, findings §Q2).
# ---------------------------------------------------------------------------
def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc)
SID_HUSK = "dddd4444-1111-2222-3333-444455556666"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    fleet.save_registry({"workers": {}})
    return tmp_path


def _roster_dead(sid):
    return {"id": sid[:8], "sessionId": sid, "name": "fleet|w|t",
            "kind": "background", "state": "done"}


def _run_factory(roster, rm_proc, calls=None):
    stdout = json.dumps(roster)

    def run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        if len(argv) >= 2 and argv[1] == "agents":
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return rm_proc
    return run


class TestHuskSweepAgainstDeadDaemon:
    def test_transient_husk_is_deferred_loudly_not_removed(self, home, capsys):
        """The brief's required shape: loud-but-nonfatal skip -- husk stays,
        next pass retries. Evidence: findings §Q2 (a scheduled autoclean run
        is exactly the zero-live-worker state where the daemon has exited)."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        removed, deferred = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert removed == [], "a transient rm failure must never count as removed"
        assert deferred == [SID_HUSK]
        err = capsys.readouterr().err
        assert "daemon" in err.lower(), err
        assert "retr" in err.lower(), f"operator must be told it is retryable: {err}"
        assert SID_HUSK[:8] in err
        # M1 / Injection F: the roll-up line itself. The reviewer deleted this
        # block and the whole suite stayed green -- nothing observed it.
        assert "left on the roster for the next pass" in err, (
            f"the deferral roll-up must survive: {err}")

    def test_transient_husk_records_no_removal_event(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        kinds = [json.loads(ln)["kind"]
                 for ln in fleet.events_path().read_text(encoding="utf-8").splitlines() if ln]
        assert "husk_removed" not in kinds, "no removal event for a husk still on the roster"

    def test_already_gone_husk_counts_as_removed(self, home):
        """rc=1 "No job matching" means the roster snapshot was merely stale --
        the husk IS gone. Reporting it as a failure would make every scheduled
        run cry wolf about sids that are already clean."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_GONE)
        removed, deferred = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert (removed, deferred) == ([SID_HUSK], [])

    def test_dead_daemon_sweep_does_not_raise(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        fleet._sweep_husks(False, run=run, which=lambda _: "claude")  # must not raise

    def test_sweep_passes_the_rosters_own_id_not_a_derived_ref(self, home):
        """m1: the `gone`->success inference is sound ONLY if the ref was
        right, and a durable husk_removed event rides on it. The roster entry
        carries the CLI's own `id`; a derived split() guess would turn a
        future ref-format drift into `No job matching` -> a false removal.
        Here the entry's id deliberately differs from the derived prefix."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        entry = _roster_dead(SID_HUSK)
        entry["id"] = "cli0wnid"           # NOT SID_HUSK.split("-")[0]
        calls = []
        run = _run_factory([entry], RM_OK, calls=calls)
        fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        rm_refs = [a[2] for a in calls if len(a) >= 3 and a[1] == "rm"]
        assert rm_refs == ["cli0wnid"], (
            f"sweep must rm by the roster's own id, got {rm_refs}")


class TestStarvationIsVisible:
    """M1: a permanently dead daemon starves the husk tier. Before this wave it
    surfaced NOWHERE -- the stamp, the autoclean_run event, the summary line and
    the exit code were byte-identical to a clean run with nothing to do
    (`husks_removed=0 errors=0`, rc=0), and doctor read "task installed; last
    run 0.3h ago" forever while the roster filled with husks. The reviewer
    proved the gap by deleting the stderr roll-up with the full suite still
    green: there was nothing outside a local variable to bind a test to.
    These tests are that binding -- Injection F must now go red."""

    def _autoclean_args(self, **kw):
        base = dict(ttl_hours=None, expire_tombstones_hours=None, dry_run=False,
                    fleet_home=None)
        base.update(kw)
        return types.SimpleNamespace(**base)

    def test_deferred_husks_reach_the_run_stamp(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        fleet.cmd_autoclean(self._autoclean_args(), run=run, which=lambda _: "claude")
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["husks_deferred"] == 1, (
            f"a starved sweep must not be byte-identical to a clean one: {stamp}")
        assert stamp["husks_removed"] == 0

    def test_deferred_husks_reach_the_autoclean_run_event(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        fleet.cmd_autoclean(self._autoclean_args(), run=run, which=lambda _: "claude")
        events = [json.loads(ln) for ln in
                  fleet.events_path().read_text(encoding="utf-8").splitlines() if ln]
        runs = [e for e in events if e.get("kind") == "autoclean_run"]
        assert runs and runs[-1]["husks_deferred"] == 1, runs

    def test_deferral_is_not_an_error_and_does_not_flip_rc(self, home):
        """Deliberate: a transient daemon is routine. Pushing deferrals into
        `errors` would turn it red on every quiet machine -- the exact
        cry-wolf this branch set out to kill."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        rc = fleet.cmd_autoclean(self._autoclean_args(), run=run, which=lambda _: "claude")
        assert rc == 0
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["errors"] == []

    def test_clean_run_reports_zero_deferred(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_OK)
        fleet.cmd_autoclean(self._autoclean_args(), run=run, which=lambda _: "claude")
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert (stamp["husks_removed"], stamp["husks_deferred"]) == (1, 0)

    def test_doctor_surfaces_a_starved_sweep(self, home):
        """The surface an operator actually reads. Doctor stays note-only
        (a transient daemon is not broken plumbing) but must stop reading
        green-and-fresh while every pass defers.

        ND-3 fix wave: this test used to seed a stamp alone and assert the note
        fired. That pinned the defect ND-3 names -- noting the FIRST deferral,
        i.e. the routine case, which habituates the operator until real
        starvation renders like Tuesday. Starvation is now a STREAK, so the
        history that proves it must exist. `TestDeferralStreakThreshold` owns
        the boundary cases; this keeps the end-to-end surface assertion."""
        for _ in range(fleet.AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD):
            fleet.append_event("autoclean_run", "*", archive_rc=0,
                               husks_removed=0, husks_deferred=3,
                               tombstones_expired=0, errors=[])
        fleet.autoclean_stamp_path().write_text(json.dumps({
            "ts": fleet.now_iso(), "dry_run": False, "archive_rc": 0,
            "husks_removed": 0, "husks_deferred": 3, "tombstones_expired": 0,
            "errors": []}), encoding="utf-8")
        name, ok, note = fleet._doctor_check_autoclean(
            run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr=""))
        assert (name, ok) == ("autoclean", True), "still note-only, never red"
        assert "3 husk" in note.lower() and "daemon" in note.lower(), note

    def test_doctor_silent_when_nothing_deferred(self, home):
        fleet.autoclean_stamp_path().write_text(json.dumps({
            "ts": fleet.now_iso(), "husks_removed": 2, "husks_deferred": 0,
            "errors": []}), encoding="utf-8")
        _n, _ok, note = fleet._doctor_check_autoclean(
            run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr=""))
        assert "defer" not in note.lower(), note


class TestDeferralLineFormat:
    """ND-2: the deferral line's shape is a CONTRACT -- the live pin
    (tests/integration/test_native_pin.py) branches on it to tell a dead-daemon
    skip from a real contract regression. Nothing bound the two sides, so a
    rename would leave the pin passing until the next live run against a dead
    daemon. Both sides now import `NATIVE_RM_DEFERRED_PREFIX`; this pins the
    rendered shape the pin actually greps for."""

    def test_transient_line_shape_is_what_the_pin_greps_for(self):
        assert fleet._rm_deferred_line("daemon-transient") == "deferred (daemon-transient)"

    def test_prefix_constant_matches_the_rendered_line(self):
        assert fleet._rm_deferred_line("failed").startswith(
            fleet.NATIVE_RM_DEFERRED_PREFIX)

    def test_archive_stderr_carries_the_exact_pin_token(self, home, capsys):
        """End-to-end: the token the pin greps for really reaches stderr."""
        fleet._archive_move_and_rm("w1", SID, [], home / "logs" / "archive" / "w1",
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_TRANSIENT),
                                   which=lambda _: "claude")
        assert "deferred (daemon-transient)" in capsys.readouterr().err

    def test_unclassified_deferral_is_distinguishable_from_transient(self, home, capsys):
        """The pin's ND-2 fallback keys on exactly this: a deferral that is NOT
        daemon-transient (an unpredicted message shape) renders with the same
        prefix but a different outcome."""
        fleet._archive_move_and_rm("w1", SID, [], home / "logs" / "archive" / "w1",
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_UNKNOWN),
                                   which=lambda _: "claude")
        err = capsys.readouterr().err
        assert f"{fleet.NATIVE_RM_DEFERRED_PREFIX} (" in err
        assert "deferred (daemon-transient)" not in err


class TestDeferralStreakThreshold:
    """ND-3: a single deferral is Tuesday; N in a row is starvation. Doctor must
    tell them apart, and the streak can only come from append-only history --
    the run stamp holds one pass."""

    def _run_event(self, deferred, removed=0):
        fleet.append_event("autoclean_run", "*", archive_rc=0,
                           husks_removed=removed, husks_deferred=deferred,
                           tombstones_expired=0, errors=[])

    def _stamp(self, deferred):
        fleet.autoclean_stamp_path().write_text(json.dumps({
            "ts": fleet.now_iso(), "dry_run": False, "archive_rc": 0,
            "husks_removed": 0, "husks_deferred": deferred,
            "tombstones_expired": 0, "errors": []}), encoding="utf-8")

    def _doctor(self):
        return fleet._doctor_check_autoclean(
            run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr=""))

    def test_streak_counts_consecutive_deferring_runs(self, home):
        for _ in range(3):
            self._run_event(2)
        streak, husks, since = fleet._autoclean_deferral_streak()
        assert (streak, husks) == (3, 2) and since

    def test_a_pass_that_deferred_nothing_resets_the_streak(self, home):
        # n3: the rule is "deferred nothing", NOT "removed a husk" -- see
        # _autoclean_deferral_streak's docstring. `removed=1` here is
        # incidental; test_a_nothing_to_do_pass_also_resets pins the other half.
        self._run_event(5)
        self._run_event(5)
        self._run_event(0, removed=1)
        assert fleet._autoclean_deferral_streak()[0] == 0

    def test_a_nothing_to_do_pass_also_resets_the_streak(self, home):
        # n3: a pass that removed nothing AND deferred nothing proves nothing
        # about daemon reachability, and still resets. Documented behavior,
        # previously described wrongly in three of four places.
        self._run_event(5)
        self._run_event(5)
        self._run_event(0, removed=0)
        assert fleet._autoclean_deferral_streak()[0] == 0

    def test_streak_only_counts_the_most_recent_consecutive_run(self, home):
        self._run_event(9)
        self._run_event(0, removed=1)
        self._run_event(4)
        assert fleet._autoclean_deferral_streak()[0] == 1

    def test_missing_history_is_not_a_crash(self, home):
        assert fleet._autoclean_deferral_streak() == (0, 0, None)

    def test_pre_m1_events_without_the_field_are_ignored(self, home):
        fleet.append_event("autoclean_run", "*", archive_rc=0, husks_removed=0)
        assert fleet._autoclean_deferral_streak()[0] == 0

    def test_doctor_is_silent_on_a_routine_single_deferral(self, home):
        """THE ND-3 test: the normal case per this branch's own §Q2 must NOT
        render like starvation, or the operator habituates and the real thing
        is invisible."""
        self._run_event(2)
        self._stamp(2)
        _n, ok, note = self._doctor()
        assert ok is True
        assert "defer" not in note.lower(), (
            f"a single deferral is routine -- doctor must not cry wolf: {note}")

    def test_doctor_is_silent_below_the_threshold(self, home):
        for _ in range(fleet.AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD - 1):
            self._run_event(2)
        self._stamp(2)
        assert "defer" not in self._doctor()[2].lower()

    def test_doctor_reports_at_the_threshold_with_the_streak(self, home):
        for _ in range(fleet.AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD):
            self._run_event(7)
        self._stamp(7)
        _n, ok, note = self._doctor()
        assert ok is True, "still note-only -- a transient daemon is not broken plumbing"
        low = note.lower()
        assert "defer" in low and "consecutive" in low, note
        assert str(fleet.AUTOCLEAN_DEFERRAL_STREAK_THRESHOLD) in note, note
        assert "daemon" in low, note


class TestStopClassification:
    """M5: `stop` shares rm's discriminator. `fleet kill` on an already-gone
    sid must succeed-as-already-gone -- and still tombstone."""

    def test_stop_gone_is_success(self):
        ok, outcome = fleet._stop_native_session_status(
            SID, run=lambda *a, **k: STOP_GONE, which=lambda _: "claude")
        assert (ok, outcome) == (True, "gone")

    def test_stop_transient_is_not_success(self):
        ok, outcome = fleet._stop_native_session_status(
            SID, run=lambda *a, **k: RM_TRANSIENT, which=lambda _: "claude")
        assert (ok, outcome) == (False, "daemon-transient")

    def test_stop_bool_face_keeps_its_contract(self):
        assert fleet._stop_native_session(
            SID, run=lambda *a, **k: STOP_GONE, which=lambda _: "claude") is True
        assert fleet._stop_native_session(
            SID, run=lambda *a, **k: RM_UNKNOWN, which=lambda _: "claude") is False

    def test_stop_unknown_failure_still_could_not_verify(self):
        ok, outcome = fleet._stop_native_session_status(
            SID, run=lambda *a, **k: RM_UNKNOWN, which=lambda _: "claude")
        assert (ok, outcome) == (False, "failed")


class TestArchiveRmAgainstDeadDaemon:
    def test_transient_rm_reports_retryable_and_still_archives(self, home, capsys):
        """Archive commits the tombstone BEFORE the rm phase by design, so a
        dead daemon must not undo the archive -- but it must not be reported
        as a plain failure either: the sid stays on the roster and the husk
        tier retries it.

        m4 fix wave: this test bound `dest` and never asserted on it -- it was
        named for a property it did not check, which reads as coverage while
        pinning nothing. A refactor moving the rm phase ahead of the
        `archived_at` commit would have stayed green. Now the archive itself
        is asserted."""
        dest = home / "logs" / "archive" / "w1"
        journal = fleet.journals_dir() / "w1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("evidence\n", encoding="utf-8")
        fleet._archive_move_and_rm("w1", SID, [], dest,
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_TRANSIENT),
                                   which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "daemon" in err.lower() and "retr" in err.lower(), err
        assert dest.exists() and any(dest.iterdir()), (
            f"a deferred rm must not undo the archive: nothing moved into {dest}")

    def test_already_gone_rm_is_reported_as_ok_not_failed(self, home, capsys):
        fleet._archive_move_and_rm("w1", SID, [], home / "logs" / "archive" / "w1",
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_GONE),
                                   which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "failed" not in err.lower(), (
            f"an already-gone sid must not be reported as a failure: {err}")


class TestRmOutcomeNotes:
    """N3: only the `daemon-transient` gloss was pinned -- the reviewer swapped
    the other two for "XXX" and the whole suite stayed green. If the retryable
    gloss is worth pinning, so is "claude not on PATH"."""

    def test_transient_note_names_the_daemon_and_the_retry(self):
        note = fleet._rm_outcome_note("daemon-transient")
        assert "daemon" in note.lower() and "retr" in note.lower(), note

    def test_no_claude_note_names_the_path_problem(self):
        assert "path" in fleet._rm_outcome_note("no-claude").lower()

    def test_error_note_names_the_subprocess(self):
        assert "subprocess" in fleet._rm_outcome_note("error").lower()

    def test_unknown_outcome_has_a_gloss(self):
        assert fleet._rm_outcome_note("failed").strip()
