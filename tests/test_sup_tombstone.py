"""three-tier §10.4 -- `kill supervisor` / `respawn supervisor` tombstone
choreography.

Built from the council-ruled decision record
`docs/proposals/sup-tombstone-choreography.md` (both dockets 4-0, 2026-07-24;
binding conditions folded into §2 step 4, §3 phase-2 item 5, §4, §5, §7).

Test list = proposal §7, verbatim numbering:

  1  resolver table (§4)                     TestLifecycleResolver
  2  T_release constant exists and is used   TestReleaseTimeoutConstant
  3  kill arm-1 happy path                   TestKillArmOne
  4  arm announcement (normative)            TestKillArmTwo
  5  respawn success shape                   TestRespawnSuccess
  6  respawn journaling (five-list)          TestRespawnJournaling
  7  matrix refusals (ruling-2 conditions)   TestMatrixRefusals
  8  protection ordering (B1/B9)             TestProtectionOrdering
  9  tombstone kinds                         TestTombstoneKinds
  10 parser lint: no --force escape          TestNoForceEscape
  11 abort landing spot (ruling-1 cond. 1)   TestAbortLandingSpot
  12 freeze-window status surface (cond. 5)  TestFreezeWindowStatusSurface

Fault-injection targets (mutate -> confirm red -> restore, tt-build
convention). F1/F2 are RATIFICATION-BLOCKING (ruling 1, condition 2):

  F1  send raises -> kill falls through with ZERO wait; respawn aborts with
      registry/claim/record BYTE-IDENTICAL and shares no branch with kill's
      arm 2                                   TestF1SteerRefused
  F2  clock-stepped wait -> both fire at exactly T_release, never a hang
                                              TestF2BoundedWait
  F3  stop reports success, roster still live -> successor dispatch NOT
      reached (caller-side B6 gate)            TestF3B6CallerGate
  F4  dispatch_bg raises after release+stop -> rollback, claim still
      `released`, rc 1                         TestF4DispatchFailureRollback
  F5  RELEASED journalled then death before write_incarnation -> next boot
      verdicts freeze                          TestF5CrashBetweenWrites
"""
import inspect
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
SID = "aaaabbbb-1111-2222-3333-444455556666"
HOLDER_SID = "99998888-7777-6666-5555-444433332222"
NEW_SID = "eeeeffff-1111-2222-3333-444455556666"
# The sid a fork-steer mints when the release steer lands on an IDLE holder.
FORK_SID = "12345678-aaaa-bbbb-cccc-ddddeeeeffff"
SUP_PIPE = "sup|inc-1|boot"
SUP_NAME_RE = re.compile(r"^sup\|inc-\d{8}T\d{6}Z-[0-9a-f]{4}\|boot$")


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    (tmp_path / "supervisor").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name=SUP_PIPE, state="working",
                      status="busy", pid=1234, kind="background"):
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_run_factory(stdout="backgrounded · eeeeffff · sup\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


def _roster_sequence(*results):
    state = {"n": 0}

    def fetch(**_):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        return results[i]
    return fetch


class _Clock:
    """Monotonic stand-in advanced by the paired fake `sleep`."""

    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t


def _stepping_sleep(clock, log=None):
    def _sleep(seconds):
        if log is not None:
            log.append(seconds)
        clock.t += seconds
    return _sleep


def _timed(**over):
    """The standard injected I/O for a §10.4 verb call.

    FIX WAVE 1, rb MIN-4: ALWAYS pairs `sleep` with the `clock` that same
    sleep advances. Injecting `sleep` alone leaves `_await_claim_released`
    measuring against the real `time.monotonic`, so a regression that never
    releases busy-spins for the full 300s T_release -- the suite HANGS instead
    of failing, which is how two of these were first mistaken for timeouts.
    Values of None are dropped so `_timed(run=None)` keeps the default."""
    clock = _Clock()
    base = dict(run=_fake_run_factory(), which=lambda _: "claude",
                sleep=_stepping_sleep(clock), clock=clock)
    base.update({k: v for k, v in over.items() if v is not None})
    return base


def _held_claim(sid=HOLDER_SID, **extra):
    claim = {"incarnation_id": "inc-held", "session_id": sid,
             "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
             "claimed_via": "fresh", "nonce_hash": "deadbeef", "nonce_seq": 1,
             "lineage_id": "lin-x"}
    claim.update(extra)
    (fleet.FLEET_HOME / "supervisor").mkdir(exist_ok=True)
    fleet.write_incarnation(claim)
    return claim


def _released_claim(**extra):
    claim = {"incarnation_id": "inc-held", "lineage_id": "lin-x",
             "claimed_via": "fresh", "released_at": fleet.now_iso(),
             "released_by_sid": HOLDER_SID, "state": "released"}
    claim.update(extra)
    (fleet.FLEET_HOME / "supervisor").mkdir(exist_ok=True)
    fleet.write_incarnation(claim)
    return claim


def _seed_pipe_worker(sid=HOLDER_SID, name=SUP_PIPE, status="working", **over):
    rec = fleet.new_worker_record(sid, "C:/x", "campaign text", "bypass",
                                  dispatch_kind="bg")
    rec["status"] = status
    # A pre-claim (sid=None, dispatch still in flight) carries no short id --
    # the launch-in-flight fixtures depend on being able to seed that shape.
    rec["native_short_id"] = sid[:8] if sid else None
    rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
    rec.update(over)
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _events_kinds():
    path = fleet.FLEET_HOME / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["kind"]
            for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _kill_args(name="supervisor", **kw):
    base = dict(name=name, yes=True, nonce=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _respawn_args(name="supervisor", **kw):
    base = dict(name=name, task=None, force=False, yes=True, nonce=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None,
                model=None, permission_mode=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _fork_steer(name):
    """Apply the REAL idle-path steer semantics to `name`'s record.

    FIX WAVE 1, CRIT-1. `_cmd_send_native`'s idle branch is a FORK-STEER
    (RATIFIED G2b): it dispatches a NEW session and `_restamp_after_steer`
    moves `session_id` to the fork, pushing the old sid into `retired_sids`.
    Every §10.4 test in the build slice stubbed the steer into a no-op and
    seeded `status="working"` (the mailbox path), so the whole fork-steer
    branch -- the PRIMARY intended case, a planned reset of an idle supervisor
    -- was untested, and both verbs shipped acting on the retired sid.

    Calls the production restamp rather than reimplementing it: a fake that
    drifts from `_restamp_after_steer` would re-open exactly this hole."""
    with fleet.fleet_lock():
        data = fleet.load_registry()
        r = data["workers"][name]
        fleet._restamp_after_steer(r, FORK_SID, FORK_SID[:8])
        r["status"] = "working"
        fleet.save_registry(data)


def _releasing_send(monkeypatch, calls=None, fork=True):
    """A cooperative holder: it runs `sup-release`, so the claim flips to
    `released` before the poll. `fork=True` (the default) is the IDLE path;
    `fork=False` is the mid-turn mailbox path, which restamps nothing."""
    def fake_send(name, message, **kw):
        if calls is not None:
            calls.append((name, message))
        if fork:
            _fork_steer(name)
        _released_claim()
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)


def _silent_send(monkeypatch, calls=None, fork=True):
    """A steer that is accepted but never produces a release (wedged body).
    Still fork-steers on the idle path -- the delivery happened."""
    def fake_send(name, message, **kw):
        if calls is not None:
            calls.append((name, message))
        if fork:
            _fork_steer(name)
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)


def _refusing_send(monkeypatch, reason="suspicious roster (G9)"):
    def fake_send(name, message, **kw):
        raise fleet.FleetCliError(reason)
    monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)


def _registry_bytes():
    return fleet.registry_path().read_bytes()


def _claim_bytes():
    return fleet.incarnation_path().read_bytes()


# ---------------------------------------------------------------------------
# §7 test 1 -- the resolver table (§4).
# ---------------------------------------------------------------------------
class TestLifecycleResolver:
    def test_no_claim_refuses_rc2(self, native_home):
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 2
        assert "sup-spawn" in str(exc.value)

    def test_corrupt_claim_refuses_rc3(self, native_home):
        fleet.incarnation_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 3
        assert "doctor" in str(exc.value)

    def test_released_claim_kill_and_respawn_messages_differ(self, native_home):
        _released_claim()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as kill_exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as resp_exc:
            fleet._resolve_supervisor_lifecycle_target("respawn")
        assert kill_exc.value.rc == 2 and resp_exc.value.rc == 2
        assert str(kill_exc.value) != str(resp_exc.value)
        # kill's arm names the real-name escape; respawn's names sup-spawn.
        assert "REAL registry name" in str(kill_exc.value)
        assert "sup-spawn" in str(resp_exc.value)

    def test_live_claim_resolves_successor_named_record_via_retired_union(self, native_home):
        """Shape is never the key: a `sup|...|successor` record whose CURRENT
        sid has moved on still resolves through the retired-sid union."""
        _held_claim(sid=HOLDER_SID)
        _seed_pipe_worker(sid=NEW_SID, name="sup|inc-held|successor",
                          retired_sids=[HOLDER_SID])
        name, rec, claim = fleet._resolve_supervisor_lifecycle_target("kill")
        assert name == "sup|inc-held|successor"
        assert rec["session_id"] == NEW_SID
        assert claim["incarnation_id"] == "inc-held"

    def test_live_claim_no_record_refuses_naming_both_sides(self, native_home):
        _held_claim(sid=HOLDER_SID)
        _seed_pipe_worker(sid=NEW_SID, name="w1")
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 2
        assert HOLDER_SID in str(exc.value)
        assert "inc-held" in str(exc.value)
        assert "doctor" in str(exc.value)

    def test_unreadable_holder_sid_freezes(self, native_home):
        _held_claim(sid="")
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet._resolve_supervisor_lifecycle_target("kill")
        assert exc.value.rc == 3


# ---------------------------------------------------------------------------
# §7 test 2 -- the constant exists, has the ruled value, and is what the wait
# actually reads (guards against silently reusing the handshake knob: option
# (B) was REJECTED, "same 300.0 value, own name").
# ---------------------------------------------------------------------------
class TestReleaseTimeoutConstant:
    def test_value(self):
        assert fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS == 300.0

    def test_distinct_from_the_handshake_knob(self):
        src = inspect.getsource(fleet)
        assert "SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0" in src

    def test_the_wait_reads_it_and_not_the_handshake_constant(self):
        for fn in (fleet._cmd_kill_supervisor, fleet._cmd_respawn_supervisor):
            src = inspect.getsource(fn)
            assert "SUPERVISOR_RELEASE_TIMEOUT_SECONDS" in src, fn
            assert "SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS" not in src, fn


# ---------------------------------------------------------------------------
# §7 test 3 -- arm-1 happy path.
# ---------------------------------------------------------------------------
def _record_stops(monkeypatch, result=(True, "gone")):
    stops = []

    def fake_stop(sid, run=None, which=None, ref=None, timeout=None):
        stops.append((sid, ref))
        return result
    monkeypatch.setattr(fleet, "_stop_native_session_status", fake_stop)
    return stops


class TestKillArmOne:
    def test_released_then_stopped_tombstoned_dead(self, native_home, monkeypatch, capsys):
        """Mid-turn (mailbox) delivery: no restamp, so the pre-steer sid IS
        the current one."""
        _held_claim()
        _seed_pipe_worker()
        sends = []
        _releasing_send(monkeypatch, sends, fork=False)
        stops = _record_stops(monkeypatch)

        clock = _Clock()
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                            which=lambda _: "claude",
                            sleep=_stepping_sleep(clock), clock=clock)
        assert rc == 0
        out = capsys.readouterr().out
        assert "SUP-KILL-RELEASED" in out
        assert "inc-held" in out
        # stop used the CAPTURED short id (ND-1), not a derived one.
        assert stops and stops[0] == (HOLDER_SID, HOLDER_SID[:8])
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "dead"
        assert any(r["kind"] == "killed"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=HOLDER_SID))
        # The steer told the body to run sup-release and exit.
        assert sends and "sup-release" in sends[0][1]

    def test_arm_one_warns_b6_when_the_stop_cannot_be_verified(self, native_home,
                                                               monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker()
        _releasing_send(monkeypatch, fork=False)
        _record_stops(monkeypatch, (False, "timeout"))
        clock = _Clock()
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                            which=lambda _: "claude",
                            sleep=_stepping_sleep(clock), clock=clock)
        assert rc == 1
        err = capsys.readouterr().err
        assert "B6" in err
        assert "sup-boot" in err


# ---------------------------------------------------------------------------
# FIX WAVE 1, CRIT-1 -- the steer LANDS on an idle holder and fork-steers it.
# Both verbs must act on the CURRENT sid set, never the pre-steer snapshot.
#
# FI (mutate -> red -> restore): make `_refetch_holder_record` return its
# `fallback` argument (the pre-steer snapshot). Confirmed RED on both verbs
# 2026-07-24; restored.
# ---------------------------------------------------------------------------
class TestCrit1StaleSidStop:
    def test_kill_stops_the_fork_not_the_retired_sid(self, native_home, monkeypatch,
                                                     capsys):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _releasing_send(monkeypatch)                 # idle path -> fork-steer
        stops = _record_stops(monkeypatch)
        clock = _Clock()
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                            which=lambda _: "claude",
                            sleep=_stepping_sleep(clock), clock=clock)
        assert rc == 0
        stopped = [s for s, _ref in stops]
        # The LIVE fork is stopped with the full timeout (primary), and the
        # retired parent is swept too -- the Steering contract leaves its
        # roster entry alive.
        assert stopped[0] == FORK_SID, stops
        assert HOLDER_SID in stopped, stops
        # The tombstone names the sid that was actually killed.
        assert any(r["kind"] == "killed"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=FORK_SID))
        assert "SUP-KILL-RELEASED" in capsys.readouterr().out

    def test_kill_arm2_also_refetches(self, native_home, monkeypatch):
        """The steer landed but the body never released: still a fork."""
        _held_claim()
        _seed_pipe_worker(status="idle")
        _silent_send(monkeypatch)
        stops = _record_stops(monkeypatch)
        clock = _Clock()
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                       which=lambda _: "claude",
                       sleep=_stepping_sleep(clock), clock=clock)
        assert [s for s, _ in stops][0] == FORK_SID, stops

    def test_respawn_b6_gate_sees_the_live_fork(self, native_home, monkeypatch):
        """The gate used to poll the RETIRED sid and pass vacuously, leaving a
        dead-marked record with a live session PLUS a fresh gen-0 body."""
        _held_claim()
        _seed_pipe_worker(status="idle")
        _releasing_send(monkeypatch)
        _record_stops(monkeypatch)
        # The fork is still on the roster -> the gate must halt.
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, [make_roster_entry(FORK_SID)]),
            (True, [make_roster_entry(FORK_SID)]),
        ))

        def _boom(*a, **k):
            raise AssertionError("successor dispatched while the fork was live")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)
        clock = _Clock()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), run=_fake_run_factory(),
                              which=lambda _: "claude",
                              sleep=_stepping_sleep(clock), clock=clock)
        assert "SUP-RESPAWN-HALTED-B6" in str(exc.value)
        assert FORK_SID in str(exc.value)

    def test_respawn_stops_the_fork_before_dispatching(self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _releasing_send(monkeypatch)
        stops = _record_stops(monkeypatch)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),
            (True, []),
            (True, [make_roster_entry(NEW_SID, status="idle")]),
        ))
        clock = _Clock()
        rc = fleet.cmd_respawn(_respawn_args(), run=_fake_run_factory(),
                               which=lambda _: "claude",
                               sleep=_stepping_sleep(clock), clock=clock)
        assert rc == 0
        stopped = [s for s, _ in stops]
        assert stopped[0] == FORK_SID, stops
        assert HOLDER_SID in stopped, stops
        assert any(r["kind"] == "stopped"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=FORK_SID))


# ---------------------------------------------------------------------------
# §7 test 4 -- the arm announcement is normative (SPEC:1196-1198), asserted,
# never incidental.
# ---------------------------------------------------------------------------
class TestKillArmTwo:
    def test_timeout_falls_through_and_announces_the_arm(self, native_home,
                                                         monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker()
        _silent_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        clock = _Clock()
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                            which=lambda _: "claude",
                            sleep=_stepping_sleep(clock), clock=clock)
        assert rc == 0
        out = capsys.readouterr().out
        assert "SUP-KILL-FROZEN" in out
        assert "T_release expired" in out
        assert str(int(fleet.SUPERVISOR_CLAIM_STALE_SECONDS)) in out
        # The claim was NOT touched: no killer-side release (B5).
        assert fleet.read_incarnation().get("state") != "released"
        assert "heartbeat_at" in fleet.read_incarnation()
        assert fleet.read_incarnation()["nonce_hash"] == "deadbeef"

    def test_refused_steer_names_the_refusal_in_the_arm_line(self, native_home,
                                                             monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker()
        _refusing_send(monkeypatch, "suspicious roster (G9)")
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        fleet.cmd_kill(_kill_args(), **_timed())
        out = capsys.readouterr().out
        assert "SUP-KILL-FROZEN" in out
        assert "suspicious roster (G9)" in out


# ---------------------------------------------------------------------------
# §7 test 5 -- respawn success shape.
# ---------------------------------------------------------------------------
def _respawn_happy(native_home, monkeypatch, args=None, run=None):
    _held_claim()
    _seed_pipe_worker()
    _releasing_send(monkeypatch)
    monkeypatch.setattr(fleet, "_stop_native_session_status",
                        lambda *a, **k: (True, "gone"))
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
        (True, []),                                        # caller-side B6 gate
        (True, []),                                        # dispatch pre-snapshot
        (True, [make_roster_entry(NEW_SID, status="idle")]),
    ))
    return fleet.cmd_respawn(args or _respawn_args(),
                             **_timed(run=run))


class TestRespawnSuccess:
    def test_fresh_gen0_body_with_the_boot_ritual(self, native_home, monkeypatch):
        journal = fleet.journals_dir() / "sup~inc-1~boot.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("JOURNAL-SENTINEL-77", encoding="utf-8")
        rc = _respawn_happy(native_home, monkeypatch)
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        new_names = [n for n in workers if n != SUP_PIPE]
        assert len(new_names) == 1, workers
        new_name = new_names[0]
        # A FRESH gen-0 body: supervisor-shaped, new launch id, not the old name.
        assert fleet._is_supervisor_shaped(new_name)
        assert SUP_NAME_RE.match(new_name), new_name
        assert new_name != SUP_PIPE
        # The old body is retired, not resurrected.
        assert workers[SUP_PIPE]["status"] == "dead"

        body = fleet.task_file_path(new_name).read_text(encoding="utf-8")
        # It gets the sup-spawn boot ritual (SPAWN §4), NOT compose_prompt's
        # worker carry-over.
        assert "sup-boot" in body
        assert "SUP-BOOT-REFUSED" in body
        assert "JOURNAL-SENTINEL-77" not in body
        # CN §6.5: no nonce material anywhere in the dispatched body.
        assert "nonce_hash" not in body
        assert "deadbeef" not in body
        # The campaign is carried forward from the old record.
        assert "campaign text" in body

    def test_no_nonce_in_the_new_bodys_environment(self, native_home, monkeypatch):
        """CN §6.5 bans an env channel for the generation. Asserted against
        the CLAIM'S OWN nonce material, not against the substring "NONCE" --
        the ambient environment carries unrelated vars (VSCODE_NONCE, ...) and
        a test that keys on the word passes or fails by whose shell ran it."""
        calls = []
        rc = _respawn_happy(native_home, monkeypatch,
                            run=_fake_run_factory(calls=calls))
        assert rc == 0
        assert calls
        for argv, kwargs in calls:
            env = kwargs.get("env") or {}
            assert "deadbeef" not in " ".join(env.values())
            assert not any(k.startswith("FLEET_") and "NONCE" in k.upper() for k in env), env
            assert "deadbeef" not in " ".join(str(a) for a in argv)


# ---------------------------------------------------------------------------
# §7 test 6 -- zero new journal kinds (CN §4.7 five-list check).
# ---------------------------------------------------------------------------
class TestRespawnJournaling:
    def test_kind_list_unchanged(self):
        assert fleet.SUPERVISOR_JOURNAL_KINDS == (
            "BOOT", "CHECKPOINT", "PROPOSAL", "SEIZED", "RELEASED",
            "LIMIT-TRANSFER", "HANDOFF-BEGIN", "HANDOFF-COMPLETE",
            "HANDOFF-ABORT",
        )

    def test_choreography_introduces_no_journal_kind(self):
        for fn in (fleet._cmd_kill_supervisor, fleet._cmd_respawn_supervisor):
            src = inspect.getsource(fn)
            assert "supervisor_journal_append" not in src, fn


# ---------------------------------------------------------------------------
# §7 test 7 -- the interaction-matrix refusals, with ruling-2's binding
# message + zero-mutation conditions.
# ---------------------------------------------------------------------------
class TestMatrixRefusals:
    def test_handoff_in_flight_refuses_both_verbs(self, native_home):
        _held_claim(handoff_token_hash="cafebabe")
        _seed_pipe_worker()
        for verb, call in (("kill", lambda: fleet.cmd_kill(_kill_args())),
                           ("respawn", lambda: fleet.cmd_respawn(_respawn_args()))):
            with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
                call()
            assert "handoff" in str(exc.value).lower(), verb
            assert "sup-handoff-complete" in str(exc.value), verb
            assert "sup-handoff-abort" in str(exc.value), verb

    def test_limited_parked_holder_refuses_both_verbs(self, native_home):
        _held_claim()
        _seed_pipe_worker(status="limited",
                          limit_reset_at=_iso(NOW + timedelta(hours=2)))
        for call in (lambda: fleet.cmd_kill(_kill_args()),
                     lambda: fleet.cmd_respawn(_respawn_args())):
            with pytest.raises(fleet.SupervisorLifecycleRefusal):
                call()

    def test_limited_kill_refusal_prints_every_escape_verbatim(self, native_home):
        """Ruling 2, condition 3 (binding): never a dead end."""
        _held_claim()
        _seed_pipe_worker(status="limited",
                          limit_reset_at=_iso(NOW + timedelta(hours=2)))
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_kill(_kill_args())
        msg = str(exc.value)
        assert "fleet sup-boot" in msg
        assert "fleet resume-limited" in msg
        assert "limit-transfer" in msg
        # The poisoned-park sequence and its stated pre-transfer cost.
        assert "REAL registry name" in msg
        assert str(int(fleet.SUPERVISOR_CLAIM_STALE_SECONDS)) in msg

    def test_limited_kill_refusal_mutates_nothing(self, native_home):
        """Ruling 2, condition 3: ZERO mutations -- registry byte-identical,
        no tombstone, no dead-marking, no heartbeat touch."""
        _held_claim()
        _seed_pipe_worker(status="limited",
                          limit_reset_at=_iso(NOW + timedelta(hours=2)))
        before_registry = _registry_bytes()
        before_claim = _claim_bytes()
        before_events = _events_kinds()
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_kill(_kill_args())
        assert _registry_bytes() == before_registry
        assert _claim_bytes() == before_claim
        assert _events_kinds() == before_events
        assert fleet.read_outcomes(SUP_PIPE, sid=HOLDER_SID) == []


# ---------------------------------------------------------------------------
# §7 test 8 -- protection ordering (B1/B9 pair). Arm-2's corpse still holds
# the claim, so sweep + archive both skip it; once the claim moves, both
# remove it.
# ---------------------------------------------------------------------------
class TestProtectionOrdering:
    """FIX WAVE 1, rs MIN-2: the proposal's wording is that arm-2's corpse
    SURVIVES `_sweep_husks` and `_archive_eligible` while the claim names it,
    and that after a seizure BOTH mechanisms actually remove/archive it. The
    build only asserted the predicates, which is a weaker claim than the one
    §7 test 8 makes -- so this now drives the real sweep."""

    def _roster_with_corpse(self, monkeypatch):
        # The corpse's sid is still on the roster as a dead entry (no
        # status/pid): what a stopped session looks like before reaping.
        monkeypatch.setattr(
            fleet, "_fetch_agents_roster",
            lambda **_: (True, [make_roster_entry(HOLDER_SID, status=None, pid=None,
                                                  state="completed")]))

    def test_arm2_corpse_survives_the_real_sweep_while_it_holds_the_claim(
            self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="dead")
        # Exactly what kill arm 2 leaves behind: dead record + "killed"
        # tombstone, claim still naming the corpse.
        fleet.write_tombstone_outcome(SUP_PIPE, HOLDER_SID, "killed")
        self._roster_with_corpse(monkeypatch)
        rmd = []
        monkeypatch.setattr(fleet, "_rm_native_session_status",
                            lambda sid, **k: (rmd.append(sid), (True, "gone"))[1])

        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert fleet._record_is_supervisor_claim_holder(rec) is True
        eligible, reason = fleet._archive_eligible(
            SUP_PIPE, rec, [], datetime.now(timezone.utc))
        assert eligible is False
        assert "claim-holder" in reason

        removed, _deferred = fleet._sweep_husks(dry_run=False)
        assert HOLDER_SID not in rmd, rmd
        assert all(HOLDER_SID not in str(r) for r in removed), removed

    def test_after_a_seizure_both_mechanisms_release_the_corpse(
            self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="dead")
        # Exactly what kill arm 2 leaves behind: dead record + "killed"
        # tombstone, claim still naming the corpse.
        fleet.write_tombstone_outcome(SUP_PIPE, HOLDER_SID, "killed")
        self._roster_with_corpse(monkeypatch)
        rmd = []
        monkeypatch.setattr(fleet, "_rm_native_session_status",
                            lambda sid, **k: (rmd.append(sid), (True, "gone"))[1])

        # A successor seizes: the claim now names a different body.
        _held_claim(sid=NEW_SID, incarnation_id="inc-next")
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert fleet._record_is_supervisor_claim_holder(rec) is not True

        # (a) archive: the tombstoned corpse is now TTL-eligible.
        old = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        rec = dict(rec, last_activity=old)
        eligible, reason = fleet._archive_eligible(
            SUP_PIPE, rec, [], datetime.now(timezone.utc))
        assert eligible is True, reason

        # (b) husk sweep, in the real B1/B9 order: archive stamps
        # `archived_at`, which moves the sid from PROTECTED to merely OWNED,
        # and only then does the sweep rm it. (While the corpse held the
        # claim, gate 0 blocked step (a), so the sweep never got here at all
        # -- that is the whole ordering guarantee.)
        data = fleet.load_registry()
        data["workers"][SUP_PIPE]["archived_at"] = fleet.now_iso()
        fleet.save_registry(data)
        fleet._sweep_husks(dry_run=False)
        assert rmd == [HOLDER_SID], rmd

    def test_the_claim_holder_is_never_swept_even_when_archived(self, native_home,
                                                                monkeypatch):
        """Belt-and-braces: the §7.2 holder-alone gate in `_sweep_husks` is
        keyed on the CLAIM, not on `archived_at`, so even a record that
        somehow acquired an archive stamp stays protected while it holds."""
        _held_claim()
        _seed_pipe_worker(status="dead", archived_at=fleet.now_iso())
        self._roster_with_corpse(monkeypatch)
        rmd = []
        monkeypatch.setattr(fleet, "_rm_native_session_status",
                            lambda sid, **k: (rmd.append(sid), (True, "gone"))[1])
        fleet._sweep_husks(dry_run=False)
        assert rmd == [], rmd


# ---------------------------------------------------------------------------
# §7 test 9 -- tombstone kinds.
# ---------------------------------------------------------------------------
class TestTombstoneKinds:
    def test_kill_writes_killed_in_both_arms(self, native_home, monkeypatch):
        for silent in (False, True):
            fleet.registry_path().unlink(missing_ok=True)
            for p in (fleet.FLEET_HOME / "state" / "outcomes").glob("*"):
                p.unlink()
            _held_claim()
            _seed_pipe_worker()
            # Mid-turn path keeps the sid stable so this test stays about
            # KINDS; the fork case is covered by TestCrit1StaleSidStop.
            (_silent_send if silent else _releasing_send)(monkeypatch, fork=False)
            monkeypatch.setattr(fleet, "_stop_native_session_status",
                                lambda *a, **k: (True, "gone"))
            clock = _Clock()
            fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                           which=lambda _: "claude",
                           sleep=_stepping_sleep(clock), clock=clock)
            kinds = {r["kind"] for r in fleet.read_outcomes(SUP_PIPE, sid=HOLDER_SID)}
            assert kinds == {"killed"}, silent

    def test_respawn_writes_stopped(self, native_home, monkeypatch):
        assert _respawn_happy(native_home, monkeypatch) == 0
        # The steer fork-steered the idle holder, so the tombstone names the
        # sid respawn actually stopped -- the fork (CRIT-1).
        kinds = {r["kind"] for r in fleet.read_outcomes(SUP_PIPE, sid=FORK_SID)}
        assert kinds == {"stopped"}

    def test_kinds_stay_within_the_declared_tuple(self):
        assert fleet.TOMBSTONE_KINDS == ("killed", "interrupted", "stopped")


# ---------------------------------------------------------------------------
# §7 test 10 -- parser lint. Cross-cutting condition 4: the 4-0 votes ratify
# the FLAGLESS forms only; any bypass needs a NEW council ruling.
# ---------------------------------------------------------------------------
class TestNoForceEscape:
    def test_sup_release_has_no_force_or_confirm_escape(self):
        parser = fleet.build_parser()
        actions = {a.dest for a in _subparser(parser, "sup-release")._actions}
        assert "force" not in actions
        assert "confirm_inc" not in actions

    def test_no_bypass_flag_on_either_ruled_refusal(self):
        """`kill --force` / `respawn --supervisor-anyway` must not exist as a
        way past the limited-parked or handoff-in-flight refusals."""
        parser = fleet.build_parser()
        kill_dests = {a.dest for a in _subparser(parser, "kill")._actions}
        assert "force" not in kill_dests
        for dest in ("supervisor_anyway", "no_release", "skip_release"):
            for verb in ("kill", "respawn"):
                assert dest not in {a.dest for a in _subparser(parser, verb)._actions}

    def test_the_refusals_are_unconditional_in_source(self):
        src = inspect.getsource(fleet._supervisor_lifecycle_interaction_refusals)
        assert "force" not in src


def _subparser(parser, name):
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            if name in action.choices:
                return action.choices[name]
    raise AssertionError(f"no subparser named {name!r}")


# ---------------------------------------------------------------------------
# §7 test 11 -- ruling 1, condition 1: the abort surface and its tested
# landing spot for a LATE async release.
# ---------------------------------------------------------------------------
class TestAbortLandingSpot:
    def test_abort_surface_carries_phase_escalations_and_the_async_warning(
            self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _silent_send(monkeypatch)
        clock = _Clock()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), run=_fake_run_factory(),
                              which=lambda _: "claude",
                              sleep=_stepping_sleep(clock), clock=clock)
        msg = str(exc.value)
        assert exc.value.rc != 0
        assert re.search(r"SUP-RESPAWN-ABORTED T_release-expired:", msg)
        # Escalation commands, verbatim.
        assert f"fleet peek {SUP_PIPE}" in msg
        assert "fleet kill supervisor" in msg
        assert "fleet sup-spawn" in msg
        # The async-late-release warning + the sup-status-first instruction.
        assert "sup-status" in msg
        assert "asynchronously" in msg

    def test_steer_refused_phase_is_named(self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _refusing_send(monkeypatch, "suspicious roster (G9)")
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "SUP-RESPAWN-ABORTED steer-refused:" in str(exc.value)
        assert "suspicious roster (G9)" in str(exc.value)

    def test_late_release_lands_on_the_released_refusal_arm(self, native_home,
                                                            monkeypatch):
        """The steer completed AFTER the abort. A re-run must land on the
        resolver's released-claim refusal with the sup-spawn pointer -- not on
        a second destructive attempt."""
        _held_claim()
        _seed_pipe_worker()
        _silent_send(monkeypatch)
        clock = _Clock()
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_respawn(_respawn_args(), run=_fake_run_factory(),
                              which=lambda _: "claude",
                              sleep=_stepping_sleep(clock), clock=clock)
        _released_claim()                       # the late async release lands
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert exc.value.rc == 2
        assert "released" in str(exc.value)
        assert "sup-spawn" in str(exc.value)
        # Still exactly one record, still alive: the abort destroyed nothing.
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "working"


# ---------------------------------------------------------------------------
# §7 test 12 -- council condition 5: the freeze window is diagnosable from the
# PERSISTENT surface, not only from the one-shot SUP-KILL-FROZEN line.
# ---------------------------------------------------------------------------
class TestFreezeWindowStatusSurface:
    def _goals(self, native_home):
        goals = native_home / "supervisor" / "GOALS.md"
        goals.parent.mkdir(exist_ok=True)
        goals.write_text("# GOALS\n\nstatus: active\n", encoding="utf-8")

    def test_dead_holder_renders_seizable_in_remaining(self, native_home, monkeypatch):
        self._goals(native_home)
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        beat = NOW - timedelta(seconds=600)
        _held_claim(heartbeat_at=_iso(beat))
        _seed_pipe_worker(status="dead")
        line = fleet.supervisor_status_line(now=NOW)
        assert line is not None
        assert "dead" in line.lower()
        assert "seizable in" in line
        remaining = int(fleet.SUPERVISOR_CLAIM_STALE_SECONDS - 600)
        assert str(remaining) in line

    def test_remaining_decreases_with_a_stepped_clock(self, native_home, monkeypatch):
        self._goals(native_home)
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        beat = NOW - timedelta(seconds=600)
        _held_claim(heartbeat_at=_iso(beat))
        _seed_pipe_worker(status="dead")
        first = fleet.supervisor_status_line(now=NOW)
        later = fleet.supervisor_status_line(now=NOW + timedelta(seconds=300))
        assert _remaining_of(first) - _remaining_of(later) == 300

    def test_released_branch_still_wins(self, native_home, monkeypatch):
        """FIX WAVE 1, rb MIN-3. This was VACUOUS as written: hoisting the
        freeze branch above the released branch left it green, because
        `_claim_holder_dead_note` returns None for a released claim BY
        CONSTRUCTION (`_record_is_supervisor_claim_holder` answers False on a
        released claim, so no holder is ever found).

        Rewritten as a real precedence assertion: force the note function to
        return a sentinel, so the only thing that can keep it out of the
        output is the released branch returning FIRST. Now a hoist goes red."""
        self._goals(native_home)
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        monkeypatch.setattr(fleet, "_claim_holder_dead_note",
                            lambda claim, inc, age: "SENTINEL-FREEZE-NOTE")
        _released_claim()
        _seed_pipe_worker(status="dead")
        line = fleet.supervisor_status_line(now=NOW)
        assert "released" in line
        assert "SENTINEL-FREEZE-NOTE" not in line

    def test_stale_heartbeat_branch_still_wins(self, native_home, monkeypatch):
        """Same precedence question one branch down: a claim already past the
        stale threshold is seizable NOW, so the "seizable in <remaining>s"
        countdown must not claim otherwise."""
        self._goals(native_home)
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        _held_claim(heartbeat_at=_iso(
            NOW - timedelta(seconds=fleet.SUPERVISOR_CLAIM_STALE_SECONDS + 60)))
        _seed_pipe_worker(status="dead")
        line = fleet.supervisor_status_line(now=NOW)
        assert "stale" in line
        assert "seizable in" not in line

    def test_live_holder_is_unaffected(self, native_home, monkeypatch):
        self._goals(native_home)
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        _held_claim(heartbeat_at=_iso(NOW - timedelta(seconds=60)))
        _seed_pipe_worker(status="working")
        line = fleet.supervisor_status_line(now=NOW)
        assert "live" in line
        assert "seizable in" not in line


def _remaining_of(line):
    m = re.search(r"seizable in (\d+)s", line)
    assert m, line
    return int(m.group(1))


# ---------------------------------------------------------------------------
# F1 (RATIFICATION-BLOCKING) -- steer refused.
# ---------------------------------------------------------------------------
class TestF1SteerRefused:
    def test_kill_falls_through_with_zero_wait(self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _refusing_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        slept = []
        clock = _Clock()
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                       which=lambda _: "claude",
                       sleep=_stepping_sleep(clock, slept), clock=clock)
        assert slept == [], slept
        assert clock.t == 0.0

    def test_respawn_abort_leaves_everything_byte_identical(self, native_home,
                                                            monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _refusing_send(monkeypatch)
        before_registry = _registry_bytes()
        before_claim = _claim_bytes()
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert _registry_bytes() == before_registry
        assert _claim_bytes() == before_claim
        assert fleet.read_outcomes(SUP_PIPE, sid=HOLDER_SID) == []

    def test_respawn_abort_shares_no_branch_with_kills_arm_two(self, native_home,
                                                               monkeypatch):
        """Structural: the arm-2 helper is never reached from respawn's call
        graph in the abort fixture."""
        _held_claim()
        _seed_pipe_worker()
        _refusing_send(monkeypatch)

        def _boom(*a, **k):
            raise AssertionError("respawn abort fell through into kill's arm 2")
        monkeypatch.setattr(fleet, "_cmd_kill_native", _boom)
        monkeypatch.setattr(fleet, "_cmd_kill_supervisor", _boom)
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_respawn(_respawn_args(), **_timed())


# ---------------------------------------------------------------------------
# F2 (RATIFICATION-BLOCKING) -- the bounded wait fires at exactly T_release.
# ---------------------------------------------------------------------------
class TestF2BoundedWait:
    def test_kill_falls_through_at_exactly_t_release(self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _silent_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        slept = []
        clock = _Clock()
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(),
                       which=lambda _: "claude",
                       sleep=_stepping_sleep(clock, slept), clock=clock)
        assert sum(slept) == fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS
        assert clock.t == fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS

    def test_respawn_aborts_at_exactly_t_release_with_a_scoped_effect_set(
            self, native_home, monkeypatch):
        """FIX WAVE 1, MAJ-D. Ruling 1's condition 2 asks for byte-identical
        state after ANY abort. On the `T_release-expired` phase that is
        PHYSICALLY UNSATISFIABLE: the steer was delivered before the timeout
        could exist, and a delivered steer either queues mail or fork-steers
        the body. The build only appeared to satisfy it because the steer was
        stubbed into a no-op.

        So this asserts the honest contract instead -- steer-DELIVERY effects
        only, and NOTHING from the destructive tail. Queued for operator
        ratification as a narrowing of a binding condition; see the proposal's
        Build record."""
        _held_claim()
        _seed_pipe_worker(status="idle")
        _silent_send(monkeypatch)
        before_claim = _claim_bytes()
        slept = []
        clock = _Clock()
        stops = _record_stops(monkeypatch)

        def _boom(*a, **k):
            raise AssertionError("dispatch reached from an aborted respawn")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)

        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), run=_fake_run_factory(),
                              which=lambda _: "claude",
                              sleep=_stepping_sleep(clock, slept), clock=clock)
        assert sum(slept) == fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS

        # PERMITTED effect set: steer delivery only.
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert rec["session_id"] == FORK_SID          # restamped by the steer
        assert HOLDER_SID in rec["retired_sids"]

        # FORBIDDEN: everything in the destructive tail.
        assert rec["status"] != "dead"
        assert _claim_bytes() == before_claim         # no claim-file change
        assert fleet.read_outcomes(SUP_PIPE, sid=FORK_SID) == []
        assert fleet.read_outcomes(SUP_PIPE, sid=HOLDER_SID) == []
        assert stops == []                            # nothing was stopped
        assert set(fleet.load_registry()["workers"]) == {SUP_PIPE}   # no successor

        # And the message says so, rather than claiming the body is untouched.
        msg = str(exc.value)
        assert "steer WAS DELIVERED" in msg
        assert "FORK-STEERED" in msg
        assert "no tombstone" in msg

    def test_the_final_sleep_is_clamped_to_the_remaining_budget(self, native_home,
                                                                monkeypatch):
        """FIX WAVE 1, rb MIN-1. The clamp `sleep(min(poll, timeout - elapsed))`
        was UNPINNED: the shipped poll (5.0) divides T_release (300.0) exactly,
        so replacing the clamp with a bare `sleep(poll)` left F2 green. With a
        poll that does NOT divide the timeout, an unclamped loop overshoots.

        Verified RED with the clamp removed (`sleep(poll)`): total wait 308.0
        != 300.0. Restored."""
        monkeypatch.setattr(fleet, "SUPERVISOR_RELEASE_POLL_SECONDS", 7.0)
        _held_claim()
        clock = _Clock()
        slept = []
        released = fleet._await_claim_released(
            timeout=fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS,
            poll=fleet.SUPERVISOR_RELEASE_POLL_SECONDS,
            clock=clock, sleep=_stepping_sleep(clock, slept))
        assert released is False
        assert sum(slept) == fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS
        assert clock.t == fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS
        # The overshoot the clamp exists to prevent: 43 polls of 7.0 = 301.0.
        assert slept[-1] < 7.0, slept[-3:]

    def test_release_midway_returns_early(self, native_home, monkeypatch):
        """Not an unbounded wait AND not a fixed one: a release at t=15 is
        observed at t=15, not at T_release."""
        clock = _Clock()
        state = {"n": 0}

        def fake_send(name, message, **kw):
            return 0
        monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)
        _held_claim()

        real_status = fleet.read_incarnation_status

        def flipping_status():
            state["n"] += 1
            if clock.t >= 15.0:
                _released_claim()
            return real_status()
        monkeypatch.setattr(fleet, "read_incarnation_status", flipping_status)
        released = fleet._await_claim_released(
            timeout=fleet.SUPERVISOR_RELEASE_TIMEOUT_SECONDS,
            poll=fleet.SUPERVISOR_RELEASE_POLL_SECONDS,
            clock=clock, sleep=_stepping_sleep(clock))
        assert released is True
        assert clock.t == 15.0


# ---------------------------------------------------------------------------
# F3 -- the caller-side B6 gate: stop reports success, roster still shows the
# sid, successor dispatch is NOT reached.
# ---------------------------------------------------------------------------
class TestF3B6CallerGate:
    def test_respawn_does_not_dispatch_while_the_old_sid_is_live(self, native_home,
                                                                 monkeypatch):
        _held_claim()
        _seed_pipe_worker()
        _releasing_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, [make_roster_entry(HOLDER_SID)]),
            (True, [make_roster_entry(HOLDER_SID)]),
        ))

        def _boom(*a, **k):
            raise AssertionError("successor dispatched past the B6 gate")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "B6" in str(exc.value)
        assert HOLDER_SID in str(exc.value)

    def test_kill_warns_rc1_with_the_b6_message(self, native_home, monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker()
        _releasing_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (False, "timeout"))
        rc = fleet.cmd_kill(_kill_args(), **_timed())
        assert rc == 1
        assert "B6" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# F4 -- dispatch fails after release + stop: rollback, claim still released.
# ---------------------------------------------------------------------------
class TestF4DispatchFailureRollback:
    def test_claim_stays_released_and_rc_is_one(self, native_home, monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker()
        _releasing_send(monkeypatch)
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence((True, [])))

        def _explode(*a, **k):
            raise fleet.NativeDispatchError("daemon refused")
        monkeypatch.setattr(fleet, "dispatch_bg", _explode)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "daemon refused" in str(exc.value)
        # The durable recovery point: the claim is RELEASED, boot-ready.
        assert fleet.read_incarnation()["state"] == "released"
        # The pre-claim was rolled back -- no half-created successor record.
        workers = fleet.load_registry()["workers"]
        assert set(workers) == {SUP_PIPE}
        assert workers[SUP_PIPE]["status"] == "dead"


# ---------------------------------------------------------------------------
# F5 -- RELEASED journalled, then death before write_incarnation.
# ---------------------------------------------------------------------------
class TestF5CrashBetweenWrites:
    """FIX WAVE 1, rb MIN-2. The build's F5 wrote a `RELEASED` entry and then
    passed `latest_entry=None`, so the `freeze` it asserted came from the
    GENERIC "holder roster-gone but heartbeat fresh" arm and the test pinned
    nothing about the F5 scenario -- deleting the transition-in-flight branch
    left it green. It now feeds its own journal entry through the real reader,
    and the roster-gone arm is neutralised (the holder IS live, which is the
    actual crash-between-writes shape: the body journalled RELEASED and died
    or hung before `write_incarnation`)."""

    def test_journal_says_released_while_the_claim_is_still_live_shaped(self, native_home):
        beat = datetime.now(timezone.utc) - timedelta(seconds=30)
        claim = _held_claim(heartbeat_at=_iso(beat))
        fleet.supervisor_journal_append("RELEASED", claim["incarnation_id"],
                                        HOLDER_SID, "released cleanly: crash test")
        latest = fleet.supervisor_journal_latest()
        assert latest is not None and latest["kind"] == "RELEASED"
        assert latest["inc"] == claim["incarnation_id"]

        # Holder still roster-live, so the generic roster-gone arm cannot be
        # what answers here. FIX WAVE 2, rs MIN-C: the fixture is deterministic,
        # so assert the EXACT verdict -- a disjunction pins neither doctrine.
        verdict, reason = fleet.supervisor_claim_decision(
            fleet.read_incarnation(), live_sids={HOLDER_SID},
            latest_entry=latest, now=datetime.now(timezone.utc),
            caller_sid="somebody-else")
        assert verdict == "refuse", (verdict, reason)
        assert "live" in reason, reason

    def test_a_fresher_incarnation_in_the_journal_refuses_the_boot(self, native_home):
        """The transition-in-flight branch itself, pinned: the journal names
        an incarnation the claim does not, with a timestamp AFTER the claim's
        heartbeat. Verdict is `refuse` (not `freeze`) -- a fresher checkpoint
        is evidence, not ambiguity. Deleting the branch goes red here."""
        beat = datetime.now(timezone.utc) - timedelta(seconds=30)
        _held_claim(heartbeat_at=_iso(beat))
        fleet.supervisor_journal_append("RELEASED", "inc-fresher", HOLDER_SID,
                                        "a newer incarnation journalled first")
        latest = fleet.supervisor_journal_latest()
        assert latest["inc"] == "inc-fresher"
        verdict, reason = fleet.supervisor_claim_decision(
            fleet.read_incarnation(), live_sids=set(), latest_entry=latest,
            now=datetime.now(timezone.utc))
        assert verdict == "refuse", (verdict, reason)
        assert "inc-fresher" in reason, reason


# ---------------------------------------------------------------------------
# The §10.4 gap the fix wave flagged for this build to rule: respawn of a
# NON-holder supervisor-shaped husk used to relaunch WITHOUT a boot ritual,
# producing a claimless supervisor-shaped body. Ruled at build time: every
# supervisor-shaped respawn routes through the same choreography, so the husk
# path also gets the boot ritual and `sup-boot` makes the claim decision.
# ---------------------------------------------------------------------------
class TestHuskRespawnGetsTheBootRitual:
    def test_non_holder_husk_relaunches_with_the_ritual(self, native_home, monkeypatch):
        _seed_pipe_worker(sid=SID, status="dead")     # no claim at all
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),                                # husk liveness gate
            (True, []),                                # caller-side B6 gate
            (True, []),                                # dispatch pre-snapshot
            (True, [make_roster_entry(NEW_SID, status="idle")]),
        ))
        rc = fleet.cmd_respawn(_respawn_args(name=SUP_PIPE),
                               **_timed())
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        new_names = [n for n in workers if n != SUP_PIPE]
        assert len(new_names) == 1, workers
        body = fleet.task_file_path(new_names[0]).read_text(encoding="utf-8")
        assert "sup-boot" in body
        assert "SUP-BOOT-REFUSED" in body

    def test_ordinary_worker_respawn_is_untouched(self, native_home, monkeypatch):
        _seed_pipe_worker(sid=SID, name="w1", status="idle")
        journal = fleet.journals_dir() / "w1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("JOURNAL-SENTINEL-88", encoding="utf-8")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),
            (True, []),
            (True, [make_roster_entry(NEW_SID, name="w1", status="idle")]),
        ))
        rc = fleet.cmd_respawn(_respawn_args(name="w1"),
                               **_timed())
        assert rc == 0
        body = fleet.task_file_path("w1").read_text(encoding="utf-8")
        assert "JOURNAL-SENTINEL-88" in body
        assert "sup-boot" not in body
