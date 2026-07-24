"""§10.4 tombstone choreography -- FIX WAVE 3 (escalation-scoped).

Confirmation gate on `c443ee1`: spec lens CONFIRM-CLEAN (2 advisory MIN), break
lens ESCALATE on ONE new MAJ minted by wave 2.

  MAJ-NEW  the retired-sid sweep cap became LEXICOGRAPHIC, so the newest
           retired sid -- the fork-steer parent, which the Steering contract
           leaves roster-live -- could be truncated out
                                                TestSweepCapKeepsTheNewest
  rb MIN-E `_replace_with_retry`'s `sleep=time.sleep` default bound at def
           time, so timing tests written against `fleet.time.sleep` passed
           vacuously                            TestSleepSeamIsLateBound
  rs MIN-D `SUP-RESPAWN-HALTED-UNVERIFIED` never said what did NOT happen
                                                TestHaltedUnverifiedSaysWhatDidNotHappen
  rs MIN-E `SUP-KILL-UNVERIFIED` was stderr-only while both benign siblings
           went to stdout                       TestUnverifiedGoesToBothStreams
"""
import inspect
import time
from types import SimpleNamespace

import pytest

import fleet

from test_sup_tombstone import (          # noqa: E402 -- sibling test helpers
    FORK_SID, HOLDER_SID, SUP_PIPE,
    _held_claim, _kill_args, _record_stops, _releasing_send, _respawn_args,
    _seed_pipe_worker, _timed, native_home,
)
from test_sup_tombstone_fixwave2 import _vanished   # noqa: E402

__all__ = ["native_home"]

# 24 retired sids that all sort ABOVE the newest one, plus a newest that sorts
# first. Under `sorted(set)[-20:]` the newest is exactly what gets discarded.
OLD_SIDS = [f"f0000000-0000-0000-0000-{i:012d}" for i in range(24)]
NEWEST_SID = "0aaaaaaa-1111-2222-3333-444455556666"


class TestSweepCapKeepsTheNewest:
    """MAJ-NEW. `retired_sids` is oldest-first, so `[-cap:]` means "the 20 MOST
    RECENT" -- the contract `_cmd_kill_native`'s own docstring states -- ONLY
    while insertion order survives. Wave 2 built the union as a `set` and
    sorted it, which silently reordered by sid TEXT."""

    def test_the_newest_retired_sid_survives_the_cap(self, native_home, monkeypatch):
        """Repro from the break lens, verbatim: 24 `f0000000-*` retired sids
        plus a newest `0aaaaaaa-*`. Goes RED under the `sorted(set)` mutation."""
        _seed_pipe_worker(sid="cccccccc-0000-0000-0000-000000000001",
                          name="w1", status="idle",
                          retired_sids=OLD_SIDS + [NEWEST_SID])
        stops = _record_stops(monkeypatch)
        rc = fleet.cmd_kill(_kill_args(name="w1"), **_timed())
        assert rc == 0
        stopped = [s for s, _ in stops]
        assert NEWEST_SID in stopped, (
            "the newest retired sid -- the fork-steer parent, which the "
            "Steering contract leaves roster-live -- was truncated out")
        # The cap still binds: 25 retired sids, 20 swept + 1 primary.
        assert len(stopped) == fleet._RETIRED_SID_SWEEP_CAP + 1, stopped
        # And it discards the OLDEST, which is what the contract says.
        assert OLD_SIDS[0] not in stopped, stopped
        assert OLD_SIDS[-1] in stopped, stopped

    def test_order_is_preserved_oldest_first(self, native_home, monkeypatch):
        _seed_pipe_worker(sid="cccccccc-0000-0000-0000-000000000001",
                          name="w1", status="idle",
                          retired_sids=OLD_SIDS[:5] + [NEWEST_SID])
        stops = _record_stops(monkeypatch)
        fleet.cmd_kill(_kill_args(name="w1"), **_timed())
        swept = [s for s, _ in stops][1:]          # index 0 is the primary
        assert swept == OLD_SIDS[:5] + [NEWEST_SID], swept

    def test_the_supervisor_arm_keeps_the_newest_too(self, native_home, monkeypatch):
        """The path that actually matters: §10.4's kill, where the newest
        retired sid IS the body the release steer forked away from."""
        _held_claim()
        _seed_pipe_worker(status="idle", retired_sids=OLD_SIDS)
        _releasing_send(monkeypatch)               # HOLDER_SID -> FORK_SID
        stops = _record_stops(monkeypatch)
        fleet.cmd_kill(_kill_args(), **_timed())
        stopped = [s for s, _ in stops]
        assert stopped[0] == FORK_SID, stops       # the live fork is primary
        assert HOLDER_SID in stopped, stops        # its parent is not dropped

    def test_dedup_preserves_the_first_position(self, native_home, monkeypatch):
        """A sid present in both the under-lock record and the caller's
        snapshot must not be promoted to "newest" by the second mention."""
        _seed_pipe_worker(sid="cccccccc-0000-0000-0000-000000000001",
                          name="w1", status="idle",
                          retired_sids=[NEWEST_SID] + OLD_SIDS[:3])
        stops = _record_stops(monkeypatch)
        fleet.cmd_kill(_kill_args(name="w1"), **_timed())
        swept = [s for s, _ in stops][1:]
        assert swept[0] == NEWEST_SID, swept

    def test_the_cap_constant_is_unchanged(self):
        assert fleet._RETIRED_SID_SWEEP_CAP == 20


class TestSleepSeamIsLateBound:
    """rb MIN-E. `def f(sleep=time.sleep)` captures the function object at
    IMPORT time, so `monkeypatch.setattr(fleet.time, "sleep", ...)` never
    intercepts it and a timing test built that way asserts nothing."""

    def test_monkeypatching_fleet_time_sleep_is_intercepted(self, monkeypatch, tmp_path):
        slept = []
        monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
        calls = {"n": 0}
        real = __import__("os").replace

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)
        monkeypatch.setattr(__import__("os"), "replace", flaky)
        src = tmp_path / "s.txt"
        src.write_text("x", encoding="utf-8")
        fleet._replace_with_retry(str(src), str(tmp_path / "d.txt"))
        assert slept == [0.1, 0.2], slept          # vacuous before the fix

    def test_the_default_is_none_not_a_bound_function(self):
        sig = inspect.signature(fleet._replace_with_retry)
        assert sig.parameters["sleep"].default is None

    def test_an_explicit_sleep_still_wins(self, tmp_path, monkeypatch):
        slept = []
        monkeypatch.setattr(time, "sleep",
                            lambda s: pytest.fail("explicit sleep was ignored"))

        def always(src, dst):
            raise PermissionError(5, "denied")
        monkeypatch.setattr(__import__("os"), "replace", always)
        with pytest.raises(PermissionError):
            fleet._replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"),
                                      sleep=slept.append)
        assert len(slept) == fleet.REGISTRY_REPLACE_RETRIES - 1


class TestHaltedUnverifiedSaysWhatDidNotHappen:
    """rs MIN-D. The sibling `SUP-RESPAWN-HALTED-B6` fires AFTER the stop and
    tombstone, so "HALTED" has already taught operators that the body is down.
    Here nothing past the steer happened -- and an operator who assumes
    otherwise walks away from a live supervisor."""

    def _halt(self, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _record_stops(monkeypatch)

        def _boom(*a, **k):
            raise AssertionError("successor dispatched")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)
        _vanished(monkeypatch)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        return str(exc.value)

    def test_it_enumerates_the_untaken_actions(self, native_home, monkeypatch):
        msg = self._halt(monkeypatch)
        assert "no stop was attempted" in msg
        assert "no tombstone" in msg
        assert "NOT marked dead" in msg

    def test_it_says_the_body_is_probably_alive(self, native_home, monkeypatch):
        msg = self._halt(monkeypatch)
        assert "still alive" in msg

    def test_the_b6_sibling_still_says_the_opposite(self):
        """The two HALTED states are genuinely different, and the messages
        must keep saying so."""
        src = inspect.getsource(fleet._cmd_respawn_supervisor)
        assert "THIS IS NOT AN ABORT: the claim is already RELEASED and the body was" in src


class TestUnverifiedGoesToBothStreams:
    """rs MIN-E (decided): both benign kill outcomes print to stdout, so a
    stdout-redirecting grep for `SUP-KILL-` found every outcome except the one
    warning that a supervisor may still be running."""

    def _run(self, monkeypatch, capsys):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _record_stops(monkeypatch)
        _vanished(monkeypatch)
        rc = fleet.cmd_kill(_kill_args(), **_timed())
        return rc, capsys.readouterr()

    def test_it_is_on_stdout(self, native_home, monkeypatch, capsys):
        rc, cap = self._run(monkeypatch, capsys)
        assert rc == 1
        assert "SUP-KILL-UNVERIFIED" in cap.out

    def test_it_is_still_on_stderr(self, native_home, monkeypatch, capsys):
        _rc, cap = self._run(monkeypatch, capsys)
        assert "SUP-KILL-UNVERIFIED" in cap.err

    def test_every_kill_outcome_is_greppable_on_stdout(self, native_home,
                                                       monkeypatch, capsys):
        """The family property, asserted as a family: `SUP-KILL-*` on stdout
        must cover all three outcomes, not two."""
        _rc, cap = self._run(monkeypatch, capsys)
        assert [ln for ln in cap.out.splitlines() if ln.startswith("SUP-KILL-")]

    def test_the_return_code_is_unchanged(self, native_home, monkeypatch, capsys):
        rc, _cap = self._run(monkeypatch, capsys)
        assert rc == 1
