"""w52: the worker respawn path's retired-sid sweep and its tombstone.

WHAT THIS FILE PINS, AND WHY IT IS A SEPARATE FILE FROM THE KILL PATH'S PINS.
`tests/test_native.py` already pins the identical five properties on
`_cmd_kill_native` -- the cap at the 20 MOST RECENT, the per-sid short timeout,
one progress line per sid, the classified outcome on failure, and the M1
cross-worker ownership skip. Every one of them was absent from
`_cmd_respawn_native`, which had no sweep at all: `_RETIRED_SID_SWEEP_CAP` had
exactly two call sites at `64b43c2` and the worker respawn path was neither.

So these are not new properties. They are the SAME properties, asserted against
the third caller, and they exist because the shared body they now all run
(`_sweep_retired_sessions`) is only worth extracting if something proves each
caller reaches it with the discipline intact. The kill pins cannot do that: the
sweep could be deleted from the respawn path entirely and every one of them
would stay green.

EACH PIN HERE IS PROVEN RED BY A MUTANT in `tools/mutate_liveness.py`
(`M-W52-*`). A pin that restates the implementation cannot fail; the ledger is
what makes the claim checkable.

THE ONE THING THIS BUILD DELIBERATELY DOES NOT DO is change what Q1
(`_roster_live_sids`) answers -- `w50/live` §6.7 leaves that an owed decision.
`test_Q1_STILL_ANSWERS_NOT_LIVE_this_build_did_not_widen_it` is the guard on
that promise, and it is the reason the sweep is unconditional instead: the old
sid is retired unconditionally, so stopping and tombstoning it can be too.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet

SID = "b9b2124d-2c4a-4dde-88b1-c16a992baf8b"

# The shape a lingering finished session presents, measured on win32 2026-08-09
# and carried over verbatim from `tests/test_liveness_readers.py`: keyed
# (`status`/`pid` present, so a process exists) but `state:"done"`, so Q1 --
# correctly, for the question "is a TURN running" -- answers not-live.
LINGERING_DONE = {"sessionId": SID, "state": "done", "status": "idle",
                  "pid": 4436, "kind": "background", "cwd": "C:/proj"}


class _ReachedDispatch(Exception):
    """Control flow got past everything under test and would have launched."""


def _must_not_dispatch(*_a, **_k):
    raise _ReachedDispatch()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    (tmp_path / "proj").mkdir(exist_ok=True)
    fleet.save_registry({"workers": {}})
    return tmp_path


def _install(home, name="w", sid=SID, retired=()):
    rec = fleet.new_worker_record(sid, str(home / "proj"), "task", "bypass",
                                  dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _respawn_args(name="w", force=False, **over):
    ns = dict(name=name, task=None, force=force, yes=True, nonce=None,
              max_budget_usd=None, setting_sources=None, token_ceiling=None,
              permission_mode=None, model=None)
    ns.update(over)
    return SimpleNamespace(**ns)


def _run_factory(rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return SimpleNamespace(returncode=rc, stdout="", stderr="")
    return fake_run


def _drive(home, monkeypatch, roster, *, force=False, calls=None, rc=0,
           name="w"):
    """Drive a real `cmd_respawn` to the dispatch boundary and stop there.

    `run`/`which` are REAL enough that `_stop_native_session_status` executes:
    the fake `run` records the argv it was handed, so what is asserted is the
    stop the sweep actually issued, not a recorder standing in for one.
    """
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, roster))
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)
    with pytest.raises(_ReachedDispatch):
        fleet.cmd_respawn(_respawn_args(name, force=force),
                          run=_run_factory(rc=rc, calls=calls),
                          which=lambda _: "claude")


def _stops(calls):
    return [c[0][2] for c in calls if c[0][:2] == ["claude", "stop"]]


# ---------------------------------------------------------------------------
# The promise this build makes about Q1: it makes none.
# ---------------------------------------------------------------------------

def test_Q1_STILL_ANSWERS_NOT_LIVE_this_build_did_not_widen_it():
    """`w50/live` §6.7's owed decision stays owed.

    The two mutants that model widening Q1 (`M-GATE2`, `M-GATE3`) both work by
    replacing a `_roster_live_sids` call with an inline predicate that counts a
    keyed `done` entry. This build does neither, and the sweep below is
    correct regardless of how that decision eventually goes -- which is the
    whole reason it keys on "the sid is being retired" rather than on liveness.
    """
    assert fleet._roster_live_sids([LINGERING_DONE]) == set()


# ---------------------------------------------------------------------------
# The sweep.
# ---------------------------------------------------------------------------

def test_respawn_sweeps_the_prior_retired_sids_AND_the_old_sid(home, monkeypatch):
    _install(home, retired=["retired1-a", "retired2-b"])
    calls = []
    _drive(home, monkeypatch, [LINGERING_DONE], calls=calls)
    assert set(_stops(calls)) == {"retired1", "retired2",
                                  fleet._native_job_ref(SID)}


def test_respawn_retired_stops_use_the_short_per_sid_timeout(home, monkeypatch):
    _install(home, retired=["retired1-a"])
    calls = []
    _drive(home, monkeypatch, [LINGERING_DONE], calls=calls)
    by_ref = {c[0][2]: c[1] for c in calls if c[0][:2] == ["claude", "stop"]}
    assert by_ref["retired1"]["timeout"] == fleet._RETIRED_SID_SWEEP_TIMEOUT_SECONDS
    assert fleet._RETIRED_SID_SWEEP_TIMEOUT_SECONDS == 5


def test_respawn_sweep_is_capped_at_the_20_MOST_RECENT(home, monkeypatch):
    """The cap is `[-cap:]` over an OLDEST-FIRST list, so it must discard the
    OLDEST. The sids are named so that lexicographic order and insertion order
    disagree: `sorted()` would keep `retired00..retired19` and throw away the
    newest -- which, per the Steering contract, is the fork-steer parent and
    the one most likely to still be running."""
    _install(home, retired=[f"retired{i:02d}-x" for i in range(50)])
    calls = []
    _drive(home, monkeypatch, [LINGERING_DONE], calls=calls)
    swept = [s for s in _stops(calls) if s != fleet._native_job_ref(SID)]
    assert len(swept) == fleet._RETIRED_SID_SWEEP_CAP - 1, swept
    assert set(swept) == {f"retired{i:02d}" for i in range(31, 50)}, swept


def test_respawn_sweep_prints_one_progress_line_per_sid(home, monkeypatch, capsys):
    _install(home, retired=["retired1sid", "retired2sid"])
    _drive(home, monkeypatch, [LINGERING_DONE])
    err = capsys.readouterr().err
    assert "stopping retired session retired1... ok" in err
    assert "stopping retired session retired2... ok" in err


def test_respawn_sweep_reports_the_classified_outcome_not_a_guess(
        home, monkeypatch, capsys):
    _install(home, retired=["retired1sid"])
    _drive(home, monkeypatch, [LINGERING_DONE], rc=1)
    err = capsys.readouterr().err
    assert "stopping retired session retired1... failed" in err
    assert "timeout" not in err, (
        f"'timeout' names a mechanism that did not occur: {err}")


def test_respawn_skips_a_retired_sid_that_is_another_workers_current_sid(
        home, monkeypatch, capsys):
    """T8 adv M1, carried across. Only a corrupted or hand-edited registry can
    produce this, but the cost of the guard is one registry read."""
    victim_sid = "victim-live-sid"
    _install(home, name="attacker", retired=[victim_sid])
    _install(home, name="victim", sid=victim_sid)
    calls = []
    _drive(home, monkeypatch, [LINGERING_DONE], calls=calls, name="attacker")
    stopped = _stops(calls)
    assert victim_sid not in stopped
    assert fleet._native_job_ref(victim_sid) not in stopped
    assert "matches another worker's current session_id" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The tombstone.
# ---------------------------------------------------------------------------

def _tombstones(name, sid):
    return [o for o in fleet.read_outcomes(name, sid=sid)
            if o.get("kind") in fleet.TOMBSTONE_KINDS]


def test_respawn_tombstones_the_old_sid_when_Q1_says_NOT_live(home, monkeypatch):
    """The durable half of the finding. G10: `claude stop` fires no Stop hook,
    so `write_tombstone_outcome` is fleet's ONLY record that a session was
    deliberately ended -- and on this branch it was never reached. The
    orphaned process is reaped inside the residency window; the missing record
    is state fleet keeps rather than state the vendor reclaims."""
    _install(home)
    _drive(home, monkeypatch, [LINGERING_DONE])
    kinds = [o["kind"] for o in _tombstones("w", SID)]
    assert kinds == ["stopped"], kinds


def test_respawn_force_tombstones_the_old_sid_EXACTLY_ONCE(home, monkeypatch):
    """The --force arm already wrote a `stopped` tombstone and already stopped
    the old sid. The sweep must not do either a second time."""
    _install(home)
    working = dict(LINGERING_DONE, state="working", status="busy")
    fetches = []

    def _roster(**_):
        fetches.append(1)
        return (True, [working] if len(fetches) == 1 else [])

    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster)
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)
    calls = []
    with pytest.raises(_ReachedDispatch):
        fleet.cmd_respawn(_respawn_args("w", force=True),
                          run=_run_factory(calls=calls), which=lambda _: "claude")

    kinds = [o["kind"] for o in _tombstones("w", SID)]
    assert kinds == ["stopped"], kinds
    assert len(fetches) >= 2, "the --force re-verification did not run"
    assert _stops(calls) == [fleet._native_job_ref(SID)], _stops(calls)


# ---------------------------------------------------------------------------
# The contracts this build must NOT have moved.
# ---------------------------------------------------------------------------

def test_a_Q1_live_turn_still_refuses_without_force(home, monkeypatch):
    """The sweep must never be reachable while a turn is running: the refusal
    stands above it, so a stop issued below can only ever be aimed at a
    session Q1 has already said is not running a turn."""
    _install(home)
    working = dict(LINGERING_DONE, state="working", status="busy")
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [working]))
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)
    calls = []
    with pytest.raises(fleet.FleetCliError) as ei:
        fleet.cmd_respawn(_respawn_args("w"), run=_run_factory(calls=calls),
                          which=lambda _: "claude")
    assert "turn is running" in str(ei.value)
    assert _stops(calls) == [], "nothing may be stopped on the refusal path"
    assert _tombstones("w", SID) == []


def test_an_unfetchable_roster_still_refuses_and_sweeps_nothing(home, monkeypatch):
    _install(home, retired=["retired1-a"])
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, []))
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)
    calls = []
    with pytest.raises(fleet.FleetCliError) as ei:
        fleet.cmd_respawn(_respawn_args("w"), run=_run_factory(calls=calls),
                          which=lambda _: "claude")
    assert "could not fetch the native roster" in str(ei.value)
    assert _stops(calls) == []
    assert _tombstones("w", SID) == []


def test_the_sid_is_still_retired_and_no_foreign_sid_enters(home, monkeypatch):
    """The write at the heart of §3.8 is unchanged: the record still carries
    its own prior sid and nothing else."""
    _install(home, retired=["retired1-a"])
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [LINGERING_DONE]))
    monkeypatch.setattr(fleet, "dispatch_bg", _must_not_dispatch)
    with pytest.raises(_ReachedDispatch):
        fleet.cmd_respawn(_respawn_args("w"), run=_run_factory(),
                          which=lambda _: "claude")
    # the dispatch failure rolled the record back; read the event instead.
    events = [json.loads(l) for l in
              fleet.events_path().read_text(
                  encoding="utf-8").splitlines() if l.strip()]
    respawned = [e for e in events if e.get("kind") == "respawned"]
    assert respawned and respawned[-1]["old_session_id"] == SID
