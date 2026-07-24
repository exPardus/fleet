"""§10.4 tombstone choreography -- FIX WAVE 1 (dual-lens gate, 2026-07-24).

Spec lens `tomb-rs`: CONFORMS-WITH-FINDINGS 0C/3M/5m.
Break lens `tomb-rb`: 1C/3M/6m (`state/journals/tomb-rb.md`).

Findings fixed HERE (CRIT-1 and the two rewritten fault injections live in
`tests/test_sup_tombstone.py` beside the contracts they belong to):

  MAJ-A  launch-in-flight guard dropped on both §10.4 routes
         (rs MAJ-1 + rb MAJ-2)                     TestMajALaunchInFlight
  MAJ-B  limited-parked refusal fails open two ways
         (rs MAJ-2 + rb MAJ-3)                     TestMajBLimitedPredicate
  MAJ-C  `sup-status` human branch never printed the freeze-window note
         (rs MAJ-3)                                TestMajCSupStatusSurface
  MIN-1  real-pipe-name route missed a corrupt INCARNATION
         (rs MIN-1)                                TestMin1CorruptClaimByRealName
  MIN-5  no retry around `os.replace` (win32 sharing violation)
         (rb MIN-5)                                TestMin5RegistryReplaceRetry

Helpers are IMPORTED from `test_sup_tombstone`, not re-declared: CRIT-1 was
caused by a test double drifting from the production behaviour it stood in
for, and two copies of `_fork_steer` would be the same mistake one level up.
"""
import inspect
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet

from test_sup_tombstone import (          # noqa: E402 -- sibling test helpers
    FORK_SID, HOLDER_SID, NEW_SID, NOW, SUP_PIPE,
    _held_claim, _iso, _kill_args, _record_stops, _registry_bytes,
    _releasing_send, _respawn_args, _roster_sequence, _seed_pipe_worker,
    _silent_send, _timed, _events_kinds, make_roster_entry, native_home,
)

__all__ = ["native_home"]                 # re-exported fixture, used by every class


class TestMajALaunchInFlight:
    """MAJ-A: ordinary kill/respawn refuse a pre-claim record (`session_id is
    None`, launch claim unexpired) with "launch in flight ... retry". The
    §10.4 routes ran ahead of those checks and lost the guard -- fail-OPEN
    exactly where respawn's claim arm is fail-closed.

    Reachable today: the respawn husk arm marked the pre-claim dead and
    dispatched a SECOND body; kill arm 2 marked it dead and bought the full
    3600s freeze."""

    def _preclaim(self, **over):
        fields = dict(last_activity=fleet.now_iso())
        fields.update(over)
        return _seed_pipe_worker(sid=None, status="working", **fields)

    def test_kill_supervisor_refuses_a_pre_claim_holder(self, native_home, monkeypatch):
        _held_claim(sid=HOLDER_SID)
        self._preclaim(retired_sids=[HOLDER_SID])   # claim resolves via the union
        _silent_send(monkeypatch)
        before = _registry_bytes()
        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_kill(_kill_args(), **_timed())
        # Fail-closed means untouched: no dead-marking, no freeze bought.
        assert _registry_bytes() == before
        assert "killed" not in _events_kinds()

    def test_respawn_husk_refuses_a_pre_claim(self, native_home, monkeypatch):
        self._preclaim()                            # no claim at all: husk arm

        def _boom(*a, **k):
            raise AssertionError("second body dispatched over a pre-claim")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)
        before = _registry_bytes()
        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_respawn(_respawn_args(name=SUP_PIPE), **_timed())
        assert _registry_bytes() == before

    def test_an_expired_launch_claim_is_not_refused(self, native_home, monkeypatch):
        """The guard is about an IN-FLIGHT dispatch, not a stuck one: once the
        launch claim expires the record is fair game again."""
        stale = _iso(datetime.now(timezone.utc) - timedelta(hours=2))
        self._preclaim(last_activity=stale)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []),
            (True, [make_roster_entry(NEW_SID, status="idle")])))
        assert fleet.cmd_respawn(_respawn_args(name=SUP_PIPE), **_timed()) == 0


class TestMajBLimitedPredicate:
    """MAJ-B: ruling 2's limited-parked refusal failed OPEN two ways.

    Root cause: `_holder_is_limited` answers the limit-transfer BOOT question
    (truthy horizon + exact sid), which is right THERE and wrong for a
    refusal. It is deliberately left unchanged; the refusal gets its own
    predicate over the union-resolved holder record."""

    def test_null_horizon_park_still_refuses(self, native_home):
        """The poisoned park -- the exact case the refusal text teaches about
        -- carries no horizon and used to walk straight through."""
        _held_claim()
        _seed_pipe_worker(status="limited", limit_reset_at=None)
        assert fleet._holder_is_limited(HOLDER_SID) is False    # unchanged
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_kill(_kill_args(), **_timed())
        assert "usage limit" in str(exc.value)
        assert "poisoned park" in str(exc.value)

    def test_sid_union_lag_still_refuses(self, native_home):
        """ND4a: the claim carries the OLD sid while the record was eagerly
        restamped. Every other claim predicate matches on the union; the
        exact-sid one missed -- and a parked body cannot pull-restamp, so the
        window never self-heals."""
        _held_claim(sid=HOLDER_SID)
        _seed_pipe_worker(sid=FORK_SID, status="limited",
                          limit_reset_at=_iso(NOW + timedelta(hours=2)),
                          retired_sids=[HOLDER_SID])
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert fleet._record_is_supervisor_claim_holder(rec) is True
        assert fleet._holder_is_limited(HOLDER_SID) is False    # the miss
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_kill(_kill_args(), **_timed())

    def test_with_horizon_case_still_refuses(self, native_home):
        _held_claim()
        _seed_pipe_worker(status="limited",
                          limit_reset_at=_iso(NOW + timedelta(hours=2)))
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_kill(_kill_args(), **_timed())

    def test_respawn_refuses_the_null_horizon_park_too(self, native_home):
        _held_claim()
        _seed_pipe_worker(status="limited", limit_reset_at=None)
        with pytest.raises(fleet.SupervisorLifecycleRefusal):
            fleet.cmd_respawn(_respawn_args(), **_timed())

    def test_boot_predicate_is_untouched(self):
        """`_holder_is_limited` keeps BOTH conditions -- correct for the
        limit-transfer boot decision it actually serves."""
        src = inspect.getsource(fleet._holder_is_limited)
        assert 'rec.get("status") == "limited" and rec.get("limit_reset_at")' in src
        assert 'rec.get("session_id") != holder_sid' in src

    def test_a_non_limited_holder_is_not_refused(self, native_home, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _releasing_send(monkeypatch)
        _record_stops(monkeypatch)
        assert fleet.cmd_kill(_kill_args(), **_timed()) == 0


class TestMajCSupStatusSurface:
    """MAJ-C: council condition 5 names `sup-status` AND the statusline. The
    note reached the statusline, doctor and `sup-status --json`, but the HUMAN
    branch never printed it -- so the one surface an operator actually types
    after a `SUP-KILL-FROZEN` line was the one that stayed silent about the
    window."""

    def _frozen(self, monkeypatch):
        monkeypatch.setattr(fleet, "supervisor_goals_active", lambda: True)
        _held_claim(heartbeat_at=_iso(datetime.now(timezone.utc)
                                      - timedelta(seconds=600)))
        _seed_pipe_worker(status="dead")

    def _args(self, **kw):
        base = dict(json=False)
        base.update(kw)
        return SimpleNamespace(**base)

    def test_human_sup_status_prints_the_freeze_note(self, native_home,
                                                     monkeypatch, capsys):
        self._frozen(monkeypatch)
        assert fleet.cmd_sup_status(self._args()) == 0
        out = capsys.readouterr().out
        assert "seizable in" in out
        assert "DEAD sid" in out

    def test_json_surface_still_carries_it(self, native_home, monkeypatch, capsys):
        self._frozen(monkeypatch)
        assert fleet.cmd_sup_status(self._args(json=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert "seizable in" in payload["nag"]


class TestMin1CorruptClaimByRealName:
    """rs MIN-1: the real-pipe-name route asked
    `_record_is_supervisor_claim_holder`, which calls `read_incarnation` --
    collapsing corrupt to None, answering False, and routing a possible holder
    onto the ORDINARY kill path on an unreadable claim. Corrupt must freeze
    (rc 3) however the target was addressed."""

    def _corrupt(self):
        fleet.incarnation_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")

    def test_kill_by_real_pipe_name_freezes(self, native_home):
        self._corrupt()
        _seed_pipe_worker()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_kill(_kill_args(name=SUP_PIPE), **_timed())
        assert exc.value.rc == 3
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "working"

    def test_respawn_by_real_pipe_name_freezes(self, native_home):
        self._corrupt()
        _seed_pipe_worker()
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(name=SUP_PIPE), **_timed())
        assert exc.value.rc == 3

    def test_ordinary_workers_are_not_frozen_by_a_corrupt_claim(self, native_home,
                                                                monkeypatch):
        """The asymmetry: supervisor-shaped names fail toward refusal, plain
        ones must not -- a briefly unreadable INCARNATION cannot brick kills
        of every ordinary worker."""
        self._corrupt()
        _seed_pipe_worker(name="w1", status="idle")
        _record_stops(monkeypatch)
        assert fleet.cmd_kill(_kill_args(name="w1"), **_timed()) == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"


class TestMin5RegistryReplaceRetry:
    """rb MIN-5 (win32): `os.replace` onto a path another process has open
    fails with WinError 5/32 -- observed live crashing `cmd_kill`'s own
    `save_registry`. The §10.4 build widened that window on purpose-built hot
    paths: `_await_claim_released` polls INCARNATION up to 60x per verb, and
    `_claim_holder_dead_note` added a registry read to `supervisor_status_line`,
    which runs in the SessionStart hook of every session on this box."""

    def test_retries_then_succeeds(self, native_home, monkeypatch, tmp_path):
        calls = {"n": 0}
        real = os.replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)
        monkeypatch.setattr(os, "replace", flaky)
        slept = []
        src = tmp_path / "src.txt"
        src.write_text("payload", encoding="utf-8")
        dst = tmp_path / "dst.txt"
        fleet._replace_with_retry(str(src), str(dst), sleep=slept.append)
        assert calls["n"] == 4
        assert dst.read_text(encoding="utf-8") == "payload"
        assert slept == [0.1, 0.2, 0.4]          # exponential, not a busy loop

    def test_exhausting_the_retries_raises(self, native_home, monkeypatch, tmp_path):
        def always(src, dst):
            raise PermissionError(5, "Access is denied")
        monkeypatch.setattr(os, "replace", always)
        slept = []
        with pytest.raises(PermissionError):
            fleet._replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"),
                                      sleep=slept.append)
        assert len(slept) == fleet.REGISTRY_REPLACE_RETRIES - 1

    def test_other_oserrors_fail_fast(self, native_home, monkeypatch, tmp_path):
        """A genuinely wrong destination must fail immediately and loudly --
        not after five sleeps."""
        def wrong(src, dst):
            raise IsADirectoryError(21, "Is a directory")
        monkeypatch.setattr(os, "replace", wrong)
        slept = []
        with pytest.raises(IsADirectoryError):
            fleet._replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"),
                                      sleep=slept.append)
        assert slept == []

    def test_save_registry_survives_a_transient_sharing_violation(self, native_home,
                                                                  monkeypatch):
        """Behavioural, NOT a source-text check.

        The first version of this test asserted `"_replace_with_retry" in
        inspect.getsource(fleet.save_registry)` -- and the fault injection
        proved it was THEATER: swapping the call back to a bare `os.replace`
        left it GREEN, because the function's own DOCSTRING still names the
        helper. A test that greps the source cannot tell a call from a
        mention."""
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)
        monkeypatch.setattr(os, "replace", flaky)

        data = fleet.load_registry()
        data["workers"]["w1"] = fleet.new_worker_record(
            "s1", "C:/x", "t", "bypass", dispatch_kind="bg")
        fleet.save_registry(data)                    # must NOT raise
        assert calls["n"] == 2                       # failed once, then landed
        assert "w1" in fleet.load_registry()["workers"]
