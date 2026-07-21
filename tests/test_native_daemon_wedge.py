"""M-E: wedged / unreachable Claude background daemon.

Covers the 2026-07-21 substrate outage (docs/specs/native-substrate.md, Known
hazards, the stale-`daemon.lock` row): a daemon died, Windows recycled its PID
onto an unrelated service, and every subsequent daemon start lost a lock race to
a process that was not a daemon. `--bg` dispatch was dead machine-wide for ~16h
and `fleet doctor` reported 21 PASS / 0 FAIL.

D1 pins `_doctor_check_daemon_wedge`; D2 pins the dispatch-failure
classification.

FIXTURE PROVENANCE -- read this before adding a fixture. The first version of
this file appended two refusal lines that never happened so that the
incident test would pass, under a comment asserting the incident had produced
them; the real log carries ONE, and in the invented window it shows a healthy
daemon (review ME-DAEMON-REVIEW-2026-07-21.md §M1.d). **When the real artifact
is in hand, the fixture IS the real artifact.** Every log line below marked
VERBATIM was read out of `C:/Users/Techn/.claude/daemon.log` at the stated line
number; `INCIDENT_LOCK` is the byte content of the manager's preserved
`daemon.lock.stale-pid15740.bak`. Anything constructed is labelled CONSTRUCTED
and says what it is probing. Nothing in this file reads or writes the real
`~/.claude/` at test time.
"""
import json
import re
import subprocess
import types
from datetime import datetime, timedelta, timezone

import pytest

import fleet


# --- the incident's own artifacts, verbatim ---------------------------------

# `~/.claude/daemon.lock`, byte content of the manager's backup at
# .../scratchpad/daemon.lock.stale-pid15740.bak.
INCIDENT_LOCK = {
    "pid": 15740,
    "version": "2.1.216",
    "jsonPath": "C:\\Users\\Techn\\.claude\\daemon.json",
    "logPath": "C:\\Users\\Techn\\.claude\\daemon.log",
    "startedAt": 1784589928352,          # 2026-07-20T23:25:28.352Z
    "origin": "transient",
    "spawnedBy": {"label": "claude", "cwd": "C:\\proga\\claude-fleet", "pid": 16144},
    "procStart": "639202047274516770",   # .NET ticks, LOCAL -- deliberately unused
    "launchTarget": "C:\\Users\\Techn\\.local\\bin\\claude.exe",
    "processWrapper": "",
}

# VERBATIM, `daemon.log` lines 682 / 693 / 694. This is the WHOLE of the
# outage's lock-race evidence: one refusal. The operator's remedy at 15:09:42
# (line 695) truncated it there permanently -- no later run of the check could
# ever have seen a second one.
INCIDENT_LOG_TAIL = (
    "[2026-07-20T23:25:27.750Z] [supervisor] ─── daemon start ─── "
    "version=2.1.216 pid=15740 origin=transient\n"
    "[2026-07-21T15:07:01.348Z] [supervisor] ─── daemon start ─── "
    "version=2.1.216 pid=34724 origin=transient\n"
    "[2026-07-21T15:07:01.868Z] [supervisor] another daemon won the lock race "
    "(pid=15740) — exiting\n"
)

# VERBATIM: every OTHER lock-race refusal in the machine's daemon.log, with the
# `daemon start` line of the pid each one names. All three are benign startup
# races -- the loser's line lands ~0.5s after the winner took the lock.
#   (log lines 149/154, 167/170, 517/520)
REAL_BENIGN_RACES = [
    ("2026-07-14T01:15:06.243Z", 28232,
     "[2026-07-14T01:15:06.243Z] [supervisor] ─── daemon start ─── "
     "version=2.1.208 pid=28232 origin=transient\n"
     "[2026-07-14T01:15:07.492Z] [supervisor] another daemon won the lock race "
     "(pid=28232) — exiting\n"),
    ("2026-07-14T06:49:11.163Z", 47240,
     "[2026-07-14T06:49:11.163Z] [supervisor] ─── daemon start ─── "
     "version=2.1.209 pid=47240 origin=transient\n"
     "[2026-07-14T06:49:12.297Z] [supervisor] another daemon won the lock race "
     "(pid=47240) — exiting\n"),
    ("2026-07-17T00:35:27.217Z", 39900,
     "[2026-07-17T00:35:27.217Z] [supervisor] ─── daemon start ─── "
     "version=2.1.212 pid=39900 origin=transient\n"
     "[2026-07-17T00:35:28.269Z] [supervisor] another daemon won the lock race "
     "(pid=39900) — exiting\n"),
]

# The one directly-observed coupling between a `daemon start` line and the lock
# that start wrote: pid 15740, line at 23:25:27.750Z vs `startedAt`
# 1784589928352 = 23:25:28.352Z. DERIVED, not observed, for the other three --
# no lock file was preserved for them. Stated rather than hidden: the benign
# fixtures' `startedAt` is the real `daemon start` timestamp plus this offset.
OBSERVED_START_TO_LOCK_SECONDS = 0.602

# The real `--bg` stderr fleet echoed during the outage, verbatim including the
# `Starting background service` prefix line.
INCIDENT_BG_STDERR = (
    "Starting background service\n"
    "Couldn't reach the background service (background service did not become "
    "reachable within 45s) - run 'claude daemon status'"
)


def _ms(iso_z: str, plus_seconds: float = 0.0) -> int:
    """Epoch millis (UTC) for a `...Z` daemon.log stamp."""
    dt = datetime.strptime(iso_z, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    return int((dt + timedelta(seconds=plus_seconds)).timestamp() * 1000)


def _derived_benign_lock(start_iso: str, pid: int) -> dict:
    """The lock the named winner of a real benign race would have written."""
    return {"pid": pid, "version": "2.1.212", "origin": "transient",
            "startedAt": _ms(start_iso, OBSERVED_START_TO_LOCK_SECONDS)}


def _write_pair(tmp_path, lock, log_text):
    lock_path = tmp_path / "daemon.lock"
    log_path = tmp_path / "daemon.log"
    if lock is not None:
        lock_path.write_text(
            lock if isinstance(lock, str) else json.dumps(lock), encoding="utf-8")
    if log_text is not None:
        log_path.write_text(log_text, encoding="utf-8")
    return lock_path, log_path


def _refusal(ts, pid):
    """CONSTRUCTED refusal line, byte-identical in shape to the four real ones
    (em-dash included) but at a chosen timestamp/pid. Used only where the
    property under test is a threshold or a parse rule, never to assert what an
    incident did."""
    return (f"[{ts}] [supervisor] another daemon won the lock race "
            f"(pid={pid}) — exiting\n")


def _check(tmp_path, lock, log_text):
    lock_path, log_path = _write_pair(tmp_path, lock, log_text)
    return fleet._doctor_check_daemon_wedge(lock_path=lock_path, log_path=log_path)


# --- D1 / M1: the founding incident, on the founding incident's own bytes ----

class TestTheFoundingIncident:
    def test_the_real_incident_artifacts_fail(self, tmp_path):
        """THE M1 REGRESSION TEST. The preserved lock and the UNMODIFIED real
        log tail -- one refusal, 15.7h after the lock was taken -- must FAIL.
        The shipped-at-89d1928 rule (>=3 refusals spanning >=300s) returned
        `ok=True` here, and no threshold VALUE fixed it: the outage's whole
        evidence window was 161s and the machine only ever emitted one refusal."""
        name, ok, msg = _check(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        assert name == "daemon-wedge"
        assert ok is False, msg

    def test_the_incident_message_names_pid_age_and_remedy(self, tmp_path):
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        assert ok is False
        assert "15740" in msg and "daemon.lock" in msg
        assert "15.7h" in msg, msg          # the real age of the refusing lock
        assert "daemon stop --any" in msg
        assert re.search(r"not sufficient|does not (clear|remove)", msg, re.I), msg

    @pytest.mark.parametrize("start_iso,pid,log", REAL_BENIGN_RACES,
                             ids=[f"pid{p}" for _s, p, _l in REAL_BENIGN_RACES])
    def test_the_three_real_benign_races_pass(self, tmp_path, start_iso, pid, log):
        """The complete real-world false-positive set: every other lock-race
        refusal this machine has ever logged. Each is ~0.5s old against its own
        lock; the wedge's was 56 493s. Nothing but the AGE GATE separates them
        here -- there is one refusal, so the span gate is not consulted."""
        lock = _derived_benign_lock(start_iso, pid)
        _n, ok, msg = _check(tmp_path, lock, log)
        assert ok is True, msg

    @pytest.mark.parametrize("start_iso,pid,log", REAL_BENIGN_RACES,
                             ids=[f"pid{p}" for _s, p, _l in REAL_BENIGN_RACES])
    def test_real_benign_races_pass_with_the_span_gate_disabled(
            self, tmp_path, monkeypatch, start_iso, pid, log):
        """Explicitly isolates the age gate: with MIN_SPAN forced to 0 the
        benign races must STILL pass. Before the M1 wave three tests named for
        other properties were in fact held up by the span gate, and the age gate
        -- the only gate that discriminates -- was untested in magnitude (F7 I2).
        Since ND-1 the primary path has no span gate at all, so this now also
        asserts that the constant is irrelevant here; it survives as the receipt
        that made dropping the gate safe."""
        monkeypatch.setattr(fleet, "DAEMON_WEDGE_MIN_SPAN_SECONDS", 0.0)
        lock = _derived_benign_lock(start_iso, pid)
        _n, ok, msg = _check(tmp_path, lock, log)
        assert ok is True, msg

    def test_the_incident_fails_with_the_span_gate_disabled(self, tmp_path, monkeypatch):
        """Mirror of the above: the wedge is the age gate's doing, not the span
        gate's."""
        monkeypatch.setattr(fleet, "DAEMON_WEDGE_MIN_SPAN_SECONDS", 0.0)
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        assert ok is False, msg

    @pytest.mark.parametrize("stamps", [
        ["2026-07-21T15:07:01.868Z"],
        ["2026-07-21T15:07:01.868Z", "2026-07-21T15:07:30.868Z"],
        ["2026-07-21T15:07:01.100Z", "2026-07-21T15:07:01.480Z",
         "2026-07-21T15:07:01.868Z"],
    ], ids=["one", "two-29s", "burst-768ms"])
    def test_the_primary_path_consults_no_span_gate_at_all(
            self, tmp_path, monkeypatch, stamps):
        """ND-1, the stronger direction. MIN_SPAN forced to a WEEK: if the
        primary path still read it, every one of these would flip to PASS. It
        must not, at any count or cadence. The constant stays in the module
        because the F6 degraded path is its only remaining consumer."""
        monkeypatch.setattr(fleet, "DAEMON_WEDGE_MIN_SPAN_SECONDS", 604800.0)
        log = "".join(_refusal(ts, 15740) for ts in stamps)
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, msg


# --- D1: the age gate, in magnitude and in sign ------------------------------

class TestAgeGate:
    def test_a_refusal_just_under_the_age_threshold_passes(self, tmp_path):
        """CONSTRUCTED boundary probe. 299s < 300s."""
        log = _refusal("2026-07-20T23:30:27.352Z", 15740)   # startedAt + 299s
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_a_refusal_just_over_the_age_threshold_fails(self, tmp_path):
        """CONSTRUCTED boundary probe. 301s >= 300s."""
        log = _refusal("2026-07-20T23:30:29.352Z", 15740)   # startedAt + 301s
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, msg

    def test_a_fractionless_refusal_stamp_still_dates(self, tmp_path):
        """CONSTRUCTED. 2.1.216 emits milliseconds; a build that stops must not
        turn every line undateable. Pins the second `strptime` format -- the
        wave-1 test rewrite dropped this and left that branch uncovered."""
        log = _refusal("2026-07-21T15:07:01Z", 15740)
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, msg

    def test_refusals_dated_before_the_lock_never_count(self, tmp_path):
        """The age comparison is SIGNED, not absolute. Refusal history from
        BEFORE this lock was written belongs to a previous lock; counting it
        would break the same self-clearing property the pid match provides, and
        would do so for the one pid the pid match cannot filter -- this one."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-19T10:00:00.000Z",
            "2026-07-19T14:00:00.000Z",
            "2026-07-20T09:00:00.000Z"))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    # ND-1: the verdict must depend on the EVIDENCE, not on how fast the
    # operator happened to retry. Every row below is >= 1 late refusal against a
    # 15.7h-old lock, so every row is a wedge. Before this wave, rows 2, 3 and 5
    # returned `ok is True` -- adding evidence made the verdict WEAKER -- and the
    # cadence in those rows is not exotic: the founding incident's whole evidence
    # window was 161s, so a second dispatch attempt inside it (a retried spawn, a
    # sibling worktree, an interactive `claude`) produced exactly row 2 or 3 and
    # flipped FAIL to PASS. Seven worktrees were live at the time.
    CADENCES = [
        ("1 refusal -- the real incident", ["2026-07-21T15:07:01.868Z"]),
        ("2 refusals 29s apart -- operator retried",
         ["2026-07-21T15:07:01.868Z", "2026-07-21T15:07:30.868Z"]),
        ("2 refusals 2min apart",
         ["2026-07-21T15:07:01.868Z", "2026-07-21T15:09:01.868Z"]),
        ("2 refusals 6min apart",
         ["2026-07-21T15:07:01.868Z", "2026-07-21T15:13:01.868Z"]),
        ("3 refusals 30s apart",
         ["2026-07-21T15:07:01.868Z", "2026-07-21T15:07:31.868Z",
          "2026-07-21T15:08:01.868Z"]),
    ]

    @pytest.mark.parametrize("label,stamps", CADENCES,
                             ids=[c[0] for c in CADENCES])
    def test_the_verdict_does_not_depend_on_retry_cadence(self, tmp_path, label, stamps):
        log = "".join(_refusal(ts, 15740) for ts in stamps)
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, f"{label}: adding evidence must never weaken the verdict -- {msg}"

    def test_a_late_burst_of_refusals_fails(self, tmp_path):
        """Replaces `test_a_late_burst_of_refusals_passes`, which asserted
        `ok is True` for three LATE refusals and conceded in its own docstring
        that the shape was imaginary ("no burst of this shape has ever been
        observed"). Structurally identical to
        `test_two_late_refusals_are_under_threshold`, which this same wave
        rightly inverted: the honesty was real, the conclusion drawn from it was
        wrong. Every real burst sits inside the ~1.1s between a daemon's start
        and its socket bind, which the AGE gate already excludes -- so a burst
        that is nonetheless 15.7h older than its lock is a wedge, not a race."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01.100Z",
            "2026-07-21T15:07:01.480Z",
            "2026-07-21T15:07:01.868Z"))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, msg

    def test_two_late_refusals_spanning_hours_fail(self, tmp_path):
        """Replaces `test_two_late_refusals_are_under_threshold`, which asserted
        `ok is True` here and thereby RATIFIED the M1 blind spot as correct
        behavior (review §M1.e). Two late refusals is strictly more evidence
        than the real incident's one."""
        log = (_refusal("2026-07-21T15:07:01.868Z", 15740)
               + _refusal("2026-07-21T18:12:44.905Z", 15740))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is False, msg


# --- D1: every PASS direction (a false FAIL is worse than a missed wedge) ----

class TestDaemonWedgePasses:
    def test_absent_lock_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, None, INCIDENT_LOG_TAIL)
        assert ok is True, msg

    def test_absent_log_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, None)
        assert ok is True, msg

    def test_unparseable_lock_passes(self, tmp_path):
        _n, ok, msg = _check(tmp_path, "{not json", INCIDENT_LOG_TAIL)
        assert ok is True, msg

    @pytest.mark.parametrize("lock", [
        {"version": "2.1.216", "startedAt": 1784589928352},        # no pid
        {"pid": "15740", "startedAt": 1784589928352},              # pid not an int
        ["not", "an", "object"],
    ])
    def test_locks_with_no_usable_pid_pass(self, tmp_path, lock):
        _n, ok, msg = _check(tmp_path, lock, INCIDENT_LOG_TAIL)
        assert ok is True, msg

    def test_a_bool_pid_does_not_adopt_refusals_naming_pid_1(self, tmp_path):
        """`isinstance(True, int)` is True and `1 == True`, so without the bool
        guard a `"pid": true` lock adopts every refusal naming pid 1. A fixture
        naming any other pid can never reach this guard -- which is why the old
        `pid=True` drift case left the guard untested (F7 I13)."""
        lock = {"pid": True, "startedAt": 1784589928352}
        log = "".join(_refusal(ts, 1) for ts in (
            "2026-07-21T15:07:01.868Z",
            "2026-07-21T18:12:44.905Z",
            "2026-07-21T20:41:03.221Z"))
        _n, ok, msg = _check(tmp_path, lock, log)
        assert ok is True, msg

    def test_healthy_log_with_no_refusals_passes(self, tmp_path):
        log = ("[2026-07-20T23:25:27.750Z] [supervisor] ─── daemon start ─── "
               "version=2.1.216 pid=15740 origin=transient\n")
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_refusals_naming_a_different_pid_pass(self, tmp_path):
        """History from a PREVIOUS lock (already cleared) must not indict the
        lock currently held -- the check self-clears after the remedy."""
        log = "".join(_refusal(ts, 99999) for ts in (
            "2026-07-21T15:07:01.868Z",
            "2026-07-21T16:40:02.100Z",
            "2026-07-21T18:12:44.905Z"))
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_a_single_undated_refusal_passes(self, tmp_path):
        """A refusal fleet cannot date is INDETERMINATE, never evidence. ONE of
        them, deliberately: a multi-line version is neutralised by the span gate
        (all forced stamps would be equal ⇒ span 0), which is how the fail-open
        went untested (F7 I11b)."""
        log = "[supervisor] another daemon won the lock race (pid=15740) - exiting\n"
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_an_embedded_timestamp_is_not_a_line_stamp(self, tmp_path):
        """CONSTRUCTED. The stamp must come from the START of the line; a
        timestamp appearing anywhere else in a refusal line leaves it
        undateable, not dated by whatever it happened to quote."""
        log = ("[supervisor] another daemon won the lock race (pid=15740) — "
               "exiting; lock written [2026-07-21T18:00:00.000Z]\n")
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_a_pid_mention_outside_a_lock_race_line_is_ignored(self, tmp_path):
        """CONSTRUCTED. The matcher keys on the literal supervisor phrase, not
        on `(pid=N)` -- otherwise any late-dated line that happens to parenthesise
        the lock's pid would indict it (F7 I12)."""
        log = ("[2026-07-21T15:07:01.868Z] [supervisor] adopted worker "
               "(pid=15740) — resuming\n")
        _n, ok, msg = _check(tmp_path, INCIDENT_LOCK, log)
        assert ok is True, msg

    def test_unreadable_log_directory_passes(self, tmp_path):
        """`_read_tail_lines` swallows OSError; a log path that is a directory
        must degrade to a PASS-note, not a crash or a FAIL."""
        (tmp_path / "daemon.log").mkdir()
        (tmp_path / "daemon.lock").write_text(json.dumps(INCIDENT_LOCK), encoding="utf-8")
        _n, ok, msg = fleet._doctor_check_daemon_wedge(
            lock_path=tmp_path / "daemon.lock", log_path=tmp_path / "daemon.log")
        assert ok is True, msg


# --- D1 / F6: the degraded, startedAt-less path ------------------------------

class TestStartedAtDrift:
    """F6: an unusable `startedAt` used to discard refusals the check could
    still read, retiring it permanently on a one-key field drift. It now falls
    back to log-only evidence at reduced confidence."""

    UNUSABLE = [
        {"pid": 15740},                                  # key absent
        {"pid": 15740, "startedAt": "yesterday"},         # wrong type
        {"pid": 15740, "startedAt": None},
        {"pid": 15740, "startedAt": True},                # bool is not a number
        {"pid": 15740, "startedAt": float("nan")},
        {"pid": 15740, "startedAt": float("inf")},
        {"pid": 15740, "startedAt": 1e300},               # out of epoch range
    ]
    SPREAD = "".join(_refusal(ts, 15740) for ts in (
        "2026-07-21T15:07:01.868Z", "2026-07-21T18:12:44.905Z"))

    @pytest.mark.parametrize("lock", UNUSABLE)
    def test_spread_refusals_still_reach_a_degraded_fail(self, tmp_path, lock):
        _n, ok, msg = _check(tmp_path, lock, self.SPREAD)
        assert ok is False, msg
        assert "DEGRADED" in msg and "startedAt" in msg

    @pytest.mark.parametrize("lock", UNUSABLE)
    def test_a_single_refusal_is_not_enough_without_the_age_gate(self, tmp_path, lock):
        """Without `startedAt` there is no age to measure, so one refusal could
        be an ordinary startup race. The degraded path needs two."""
        _n, ok, msg = _check(tmp_path, lock, INCIDENT_LOG_TAIL)
        assert ok is True, msg

    def test_a_burst_is_not_enough_without_the_age_gate(self, tmp_path):
        """ND-1 removed the span gate from the PRIMARY path; this pins that it
        is still wired HERE, where no age gate exists and it is the only
        discriminator between a wedge and an ordinary startup race."""
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01.100Z", "2026-07-21T15:07:01.868Z"))
        _n, ok, msg = _check(tmp_path, {"pid": 15740}, log)
        assert ok is True, msg

    def test_the_degraded_span_gate_reads_the_live_constant(self, tmp_path, monkeypatch):
        """The other half: forcing MIN_SPAN to 0 turns that same burst into a
        degraded FAIL, so the gate is genuinely consulted here rather than
        vestigial."""
        monkeypatch.setattr(fleet, "DAEMON_WEDGE_MIN_SPAN_SECONDS", 0.0)
        log = "".join(_refusal(ts, 15740) for ts in (
            "2026-07-21T15:07:01.100Z", "2026-07-21T15:07:01.868Z"))
        _n, ok, msg = _check(tmp_path, {"pid": 15740}, log)
        assert ok is False, msg

    @pytest.mark.parametrize("log", [
        "[supervisor] another daemon won the lock race (pid=15740) - exiting\n"
        "[supervisor] another daemon won the lock race (pid=15740) - exiting\n",
        "[supervisor] another daemon won the lock race (pid=15740) - exiting\n"
        + _refusal("2026-07-21T15:07:01.868Z", 15740),
    ], ids=["all-undated", "mixed"])
    def test_undated_refusals_on_the_degraded_path_pass(self, tmp_path, log):
        """The input the closeout gate named, and which this suite did not have.
        My I11 dispute claimed `ts = started` was an equivalent mutant; the gate
        rejected it because on THIS path `started` is None, so the mutant appends
        None to `refusals` and `max()` raises TypeError. It was right, and the
        reason the injection stayed green is that no fixture combined an unusable
        `startedAt` with an undateable line. It does now: undateable is
        INDETERMINATE on the degraded path too, never evidence and never a
        crash."""
        _n, ok, msg = _check(tmp_path, {"pid": 15740}, log)
        assert ok is True, msg

    def test_the_degraded_path_still_honours_the_pid_match(self, tmp_path):
        log = "".join(_refusal(ts, 99999) for ts in (
            "2026-07-21T15:07:01.868Z", "2026-07-21T18:12:44.905Z"))
        _n, ok, msg = _check(tmp_path, {"pid": 15740}, log)
        assert ok is True, msg


# --- D1: the hard constraints ------------------------------------------------

class TestDaemonWedgeConstraints:
    def test_check_spawns_no_subprocess(self, tmp_path, monkeypatch):
        """HARD CONSTRAINT: the probe must not be able to start a daemon. The
        cheapest possible proof is that it shells out to nothing at all."""
        def _boom(*a, **kw):
            raise AssertionError("_doctor_check_daemon_wedge shelled out")
        monkeypatch.setattr(subprocess, "run", _boom)
        monkeypatch.setattr(subprocess, "Popen", _boom)
        _n, ok, _msg = _check(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        assert ok is False

    def test_check_mutates_nothing(self, tmp_path):
        """NEVER writes under ~/.claude: byte-for-byte and mtime-for-mtime."""
        lock_path, log_path = _write_pair(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in (lock_path, log_path)}
        listing_before = sorted(p.name for p in tmp_path.iterdir())
        fleet._doctor_check_daemon_wedge(lock_path=lock_path, log_path=log_path)
        assert {p: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in (lock_path, log_path)} == before
        assert sorted(p.name for p in tmp_path.iterdir()) == listing_before

    def test_default_paths_resolve_under_the_claude_home(self):
        """Portability: `Path.home()/.claude` is the vendor's config dir on
        Windows, macOS and Linux alike -- no platform branch anywhere."""
        assert fleet.claude_daemon_lock_path().name == "daemon.lock"
        assert fleet.claude_daemon_lock_path().parent.name == ".claude"
        assert fleet.claude_daemon_log_path().name == "daemon.log"
        assert fleet.claude_daemon_log_path().parent.name == ".claude"

    def test_registered_with_the_other_doctor_checks(self, tmp_path, monkeypatch, capsys):
        """A check nobody runs is not a check -- that IS the outage's lesson
        (21 PASS / 0 FAIL while dispatch was dead machine-wide)."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        (tmp_path / "state").mkdir()
        lock_path, log_path = _write_pair(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
        monkeypatch.setattr(fleet, "claude_daemon_lock_path", lambda: lock_path)
        monkeypatch.setattr(fleet, "claude_daemon_log_path", lambda: log_path)
        rc = fleet.cmd_doctor(types.SimpleNamespace(), which=lambda _: None,
                              run=lambda *a, **kw: None)
        out = capsys.readouterr().out
        assert "[FAIL] daemon-wedge:" in out, out
        assert rc != 0


# --- The remedy text ---------------------------------------------------------

class TestRemedyText:
    def test_the_windows_form_is_powershell_not_cmd(self):
        """F3: the project's documented primary Windows shell is PowerShell 5.1,
        in which `&&` is a hard parse error ("The token '&&' is not a valid
        statement separator in this version") and `%VAR%` does not expand. The
        old remedy handed the operator a parse error while dispatch was down."""
        remedy = fleet.NATIVE_DAEMON_WEDGE_REMEDY
        ps = remedy.split("PowerShell:", 1)[1].split("cmd.exe:", 1)[0]
        assert "&&" not in ps, ps
        assert "%" not in ps, ps
        assert "$env:USERPROFILE" in ps and "Copy-Item" in ps and "Remove-Item" in ps
        # the cmd.exe form is kept, but labelled -- not passed off as "Windows"
        assert "cmd.exe:" in remedy

    def test_the_remedy_carries_a_live_daemon_precondition(self):
        """F4: this is the one output in the feature that instructs a
        destructive, manual, irreversible-without-backup action, and the signal
        that reaches it is a TIMEOUT, not proof of a stale lock. Removing a live
        daemon's lock destroys the singleton guarantee."""
        remedy = fleet.NATIVE_DAEMON_WEDGE_REMEDY
        assert "PRECONDITION" in remedy
        assert re.search(r"\bonly if\b", remedy, re.I), remedy
        assert re.search(r"HARMFUL|harmful", remedy), remedy
        assert "daemon stop --any" in remedy

    def test_the_remedy_still_backs_up_before_removing(self):
        for fragment in ("daemon.lock.bak", "Copy-Item", "cp ~/.claude/daemon.lock"):
            assert fragment in fleet.NATIVE_DAEMON_WEDGE_REMEDY

    def test_the_stop_any_caveat_is_pinned_verbatim(self):
        """Both halves of the caveat, as literals. Found by this wave's own
        injection run: the earlier assertion was the alternation
        `not sufficient|does not (clear|remove)`, which a mutation that deleted
        `is NOT sufficient` still satisfied via the surviving `does not clear
        the lock` -- so the caveat looked pinned and was not (I15 GREEN). The
        caveat is a RECEIPT (manager, 2026-07-21: `stop --any` printed `no
        daemon running` and left the lock in place), so it is pinned as bytes."""
        remedy = fleet.NATIVE_DAEMON_WEDGE_REMEDY
        assert "`claude daemon stop --any` is NOT sufficient" in remedy
        assert "does not clear the lock" in remedy


# --- D2: dispatch-failure classification -------------------------------------

@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _run_failing(stderr, stdout="", rc=1):
    def fake_run(argv, **kwargs):
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)
    return fake_run


def _dispatch(run):
    return fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=run,
                             which=lambda _: "claude", sleep=lambda s: None,
                             roster_fetch=lambda: (True, []))


class TestDispatchUnreachableService:
    def test_unreachable_service_is_named_not_echoed(self, native_home):
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing(INCIDENT_BG_STDERR))
        msg = str(exc.value)
        assert "daemon.lock" in msg
        assert "fleet doctor" in msg
        assert "daemon stop --any" in msg
        assert re.search(r"not sufficient|does not (clear|remove)", msg, re.I), msg

    def test_the_vendor_string_is_still_carried(self, native_home):
        """Diagnosis must ADD to the raw string, never replace it -- the next
        wording drift is only findable if the bytes survive."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing(INCIDENT_BG_STDERR))
        assert "Couldn't reach the background service" in str(exc.value)

    def test_the_prefix_line_alone_does_not_trigger(self, native_home):
        """`Starting background service` is printed on every healthy dispatch
        too -- it must never be the matcher."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing("Starting background service\nboom"))
        assert "daemon.lock" not in str(exc.value)

    def test_unrelated_failure_keeps_the_plain_shape(self, native_home):
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing("permission denied"))
        msg = str(exc.value)
        assert "permission denied" in msg and "daemon.lock" not in msg

    @pytest.mark.parametrize("stderr", [
        "Couldn't reach the background service",
        "background service did not become reachable within 45s",
        "COULDN'T REACH THE BACKGROUND SERVICE (whatever)",
    ])
    def test_both_halves_of_the_shape_match_independently(self, native_home, stderr):
        """Vendor surface: either half alone is enough, so a reworded wrapper
        or a changed timeout still classifies."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing(stderr))
        assert "daemon.lock" in str(exc.value)

    def test_stdout_only_failure_also_classifies(self, native_home):
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing("", stdout=INCIDENT_BG_STDERR))
        assert "daemon.lock" in str(exc.value)

    def test_a_stream_split_still_classifies(self, native_home):
        """F5: the prefix on stderr and the symptom on stdout. The old
        `stderr or stdout` short-circuited on the non-empty stderr and silently
        dropped the symptom, disabling the whole diagnosis; the twin
        `_classify_native_cli_result` has always read both streams."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing(
                "Starting background service",
                stdout="Couldn't reach the background service (background "
                       "service did not become reachable within 45s)"))
        assert "daemon.lock" in str(exc.value)

    def test_the_reverse_stream_split_still_classifies(self, native_home):
        """The twin of the above -- symptom on stderr, noise on stdout. Pins
        that the fix did not merely swap which single stream is read."""
        with pytest.raises(fleet.NativeDispatchError) as exc:
            _dispatch(_run_failing(
                "Couldn't reach the background service",
                stdout="Starting background service"))
        assert "daemon.lock" in str(exc.value)


# --- F2: the two halves of the feature must agree ----------------------------

def test_dispatch_and_doctor_agree_on_the_real_incident(native_home, tmp_path):
    """F2. `dispatch_bg` tells the operator to "Confirm with `fleet doctor`".
    At 89d1928 `fleet doctor` answered `no wedge signature` on the very incident
    the message was written from -- routing an operator with a correct diagnosis
    to a surface that refuted it. Both halves, one artifact, one verdict."""
    with pytest.raises(fleet.NativeDispatchError) as exc:
        _dispatch(_run_failing(INCIDENT_BG_STDERR))
    assert "fleet doctor" in str(exc.value)

    lock_path, log_path = _write_pair(tmp_path, INCIDENT_LOCK, INCIDENT_LOG_TAIL)
    _n, ok, msg = fleet._doctor_check_daemon_wedge(
        lock_path=lock_path, log_path=log_path)
    assert ok is False, (
        "dispatch_bg routes the operator to `fleet doctor`; doctor must not "
        f"contradict it on the incident both were built from: {msg}")
