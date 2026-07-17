"""claude 2.1.212 transient-daemon contract (docs/reviews/
CLAUDE-2.1.212-CONTRACT-2026-07-17.md).

Pins the failure-message taxonomy of `claude rm`/`claude stop` and the
hygiene-path behavior it forces. Every expectation here is anchored to a
receipt in that findings doc -- these are unit tests over injected `run`
stubs whose stdout/stderr/returncode are copied VERBATIM from the live
probes, so the taxonomy stays pinned without a live daemon.

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
# Verbatim live receipts (findings doc Q3). Exit codes and message text are
# copied from the probe output -- do not "tidy" them.
# ---------------------------------------------------------------------------
RM_OK = types.SimpleNamespace(returncode=0, stdout="removed aaaa1111", stderr="")
RM_GONE = types.SimpleNamespace(returncode=1, stdout="No job matching 'aaaa1111'", stderr="")
RM_TRANSIENT = types.SimpleNamespace(
    returncode=1,
    stdout="",
    stderr="couldn't remove aaaa1111 — the background service may be "
           "restarting. Try again in a moment.")
RM_UNKNOWN = types.SimpleNamespace(returncode=1, stdout="", stderr="kaboom")
STOP_GONE = types.SimpleNamespace(
    returncode=1,
    stdout="No job matching 'aaaa1111'. Run 'claude agents' to list running sessions.",
    stderr="")


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
        removed = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert removed == [], "a transient rm failure must never count as removed"
        err = capsys.readouterr().err
        assert "daemon" in err.lower(), err
        assert "retr" in err.lower(), f"operator must be told it is retryable: {err}"
        assert SID_HUSK[:8] in err

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
        removed = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert removed == [SID_HUSK]

    def test_dead_daemon_sweep_does_not_raise(self, home):
        fleet.append_event("turn_started", "gone-worker", session_id=SID_HUSK)
        run = _run_factory([_roster_dead(SID_HUSK)], RM_TRANSIENT)
        fleet._sweep_husks(False, run=run, which=lambda _: "claude")  # must not raise


class TestArchiveRmAgainstDeadDaemon:
    def test_transient_rm_reports_retryable_and_still_archives(self, home, capsys):
        """Archive commits the tombstone BEFORE the rm phase by design, so a
        dead daemon must not undo the archive -- but it must not be reported
        as a plain failure either: the sid stays on the roster and the husk
        tier retries it."""
        dest = home / "logs" / "archive" / "w1"
        fleet._archive_move_and_rm("w1", SID, [], dest,
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_TRANSIENT),
                                   which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "daemon" in err.lower() and "retr" in err.lower(), err

    def test_already_gone_rm_is_reported_as_ok_not_failed(self, home, capsys):
        fleet._archive_move_and_rm("w1", SID, [], home / "logs" / "archive" / "w1",
                                   roster_entries=[_roster_dead(SID)],
                                   run=_run_factory([], RM_GONE),
                                   which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "failed" not in err.lower(), (
            f"an already-gone sid must not be reported as a failure: {err}")
