"""§10.4 tombstone choreography -- FIX WAVE 2 (re-gate of `206a648`).

Every finding in this wave lives INSIDE fix-wave-1 code, which is the pattern
this repo keeps hitting: a fix wave mints its own defects.

  rb MAJ-A  kill announced a success it could not substantiate when the
            post-steer re-fetch failed          TestUnverifiedRefetchKill
  rb MAJ-B  respawn dispatched a successor on the same unverifiable state
                                                TestUnverifiedRefetchRespawn
  rb MIN-A  residual double-fork TOCTOU between re-fetch and stop
                                                TestConcurrentRestampTOCTOU
  rb MIN-B  `_replace_with_retry` docstring claimed a fast-fail it does not do
                                                TestReplaceRetryDocstringTruth
  rb MIN-C  `_write_json_atomic` had no retry; the harm path is a transient
            file lock becoming an up-to-3600s freeze
                                                TestWriteJsonAtomicRetry

rs MIN-A/B/C are message/verdict tightenings applied in place, in
`test_sup_tombstone.py` and `test_sup_tombstone_fixwave1.py`.
"""
import inspect
import os
from datetime import datetime, timedelta, timezone

import pytest

import fleet

from test_sup_tombstone import (          # noqa: E402 -- sibling test helpers
    FORK_SID, HOLDER_SID, NEW_SID, SUP_PIPE,
    _held_claim, _kill_args, _record_stops, _releasing_send, _respawn_args,
    _roster_sequence, _seed_pipe_worker, _silent_send, _timed,
    make_roster_entry, native_home,
)

__all__ = ["native_home"]

FORK2_SID = "abcdabcd-9999-8888-7777-666655554444"


def _delete_record(name=SUP_PIPE):
    data = fleet.load_registry()
    data["workers"].pop(name, None)
    fleet.save_registry(data)


def _steer_then(monkeypatch, after):
    """A steer that lands (fork-steers an idle holder), releases the claim, and
    THEN triggers `after` -- the real ordering of both MAJ-A/B scenarios.

    The claim release is what drops the §7.2 gate-0 protection, so
    `autoclean`/`clean` becoming able to take the record is a CONSEQUENCE of a
    successful arm 1, not an unrelated race. Hooking the disappearance to a
    call counter on `load_registry` (the first attempt at this) fires during
    the steer instead of after it."""
    def fake_send(name, message, **kw):
        from test_sup_tombstone import _fork_steer, _released_claim
        _fork_steer(name)
        _released_claim()
        after(name)
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)


def _vanished(monkeypatch):
    _steer_then(monkeypatch, lambda name: _delete_record(name))


def _quarantined(monkeypatch):
    """`load_registry` QUARANTINES a corrupt file and REINITIALISES it, so
    subsequent reads SUCCEED against an empty registry -- the record is simply
    gone. That is the shape the re-fetch has to survive; the raising shape is
    covered at unit level in TestRefetchReportsVerification."""
    def _wipe(_name):
        monkeypatch.setattr(fleet, "load_registry",
                            lambda *a, **k: {"workers": {}, "version": 1})
    _steer_then(monkeypatch, _wipe)


class TestRefetchReportsVerification:
    """The contract the two verbs are built on: the re-fetch says whether it
    could actually see the record, instead of quietly handing back the
    pre-steer snapshot -- the exact value CRIT-1 proved dangerous."""

    def test_verified_when_the_record_is_there(self, native_home):
        rec = _seed_pipe_worker()
        fresh, verified = fleet._refetch_holder_record(SUP_PIPE, rec)
        assert verified is True
        assert fresh["session_id"] == HOLDER_SID

    def test_unverified_when_the_record_is_gone(self, native_home):
        rec = _seed_pipe_worker()
        _delete_record()
        fresh, verified = fleet._refetch_holder_record(SUP_PIPE, rec)
        assert verified is False
        assert fresh is rec                      # the snapshot, and flagged as such

    def test_unverified_when_the_registry_is_corrupt(self, native_home, monkeypatch):
        rec = _seed_pipe_worker()

        def _raise(*a, **k):
            raise fleet.RegistryCorruptError("quarantined")
        monkeypatch.setattr(fleet, "load_registry", _raise)
        fresh, verified = fleet._refetch_holder_record(SUP_PIPE, rec)
        assert verified is False
        assert fresh is rec


class TestUnverifiedRefetchKill:
    """rb MAJ-A: fail-open is bad; fail-open-AND-ANNOUNCE is worse, because
    `SUP-KILL-RELEASED` + rc 0 ends the operator's investigation while a fork
    nobody saw may still be running."""

    def _seed(self, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        return _record_stops(monkeypatch)

    def test_deleted_record_degrades_loudly(self, native_home, monkeypatch, capsys):
        stops = self._seed(monkeypatch)
        _vanished(monkeypatch)
        rc = fleet.cmd_kill(_kill_args(), **_timed())
        cap = capsys.readouterr()
        assert rc == 1
        assert "SUP-KILL-UNVERIFIED" in cap.err
        assert "SUP-KILL-RELEASED" not in cap.out
        # It still stopped everything it knew about (the pre-steer union).
        assert HOLDER_SID in [s for s, _ in stops], stops

    def test_corrupt_registry_degrades_loudly(self, native_home, monkeypatch, capsys):
        stops = self._seed(monkeypatch)
        _quarantined(monkeypatch)
        rc = fleet.cmd_kill(_kill_args(), **_timed())
        cap = capsys.readouterr()
        assert rc == 1
        assert "SUP-KILL-UNVERIFIED" in cap.err
        assert "SUP-KILL-RELEASED" not in cap.out
        assert "fleet doctor" in cap.err
        assert stops, "nothing was stopped at all"

    def test_the_warning_says_a_later_fork_may_be_missing(self, native_home,
                                                          monkeypatch, capsys):
        """The honest part: the snapshot union is a FLOOR, not a guarantee. A
        fork minted after the last good read is not in it, and the operator
        must be told that rather than reassured."""
        self._seed(monkeypatch)
        _vanished(monkeypatch)
        fleet.cmd_kill(_kill_args(), **_timed())
        err = capsys.readouterr().err
        assert "FORK-STEERS" in err
        assert "DO NOT assume" in err
        assert "claude agents" in err

    def test_a_verified_refetch_still_announces_cleanly(self, native_home,
                                                        monkeypatch, capsys):
        """The degradation must not fire on the happy path."""
        self._seed(monkeypatch)
        _releasing_send(monkeypatch)
        rc = fleet.cmd_kill(_kill_args(), **_timed())
        cap = capsys.readouterr()
        assert rc == 0
        assert "SUP-KILL-RELEASED" in cap.out
        assert "SUP-KILL-UNVERIFIED" not in cap.err


class TestUnverifiedRefetchRespawn:
    """rb MAJ-B: the caller-side B6 gate cannot pass on state nobody can
    verify. Halt BEFORE the dispatch decision -- dispatching here is exactly
    how two live supervisor bodies happen."""

    def _seed(self, monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _record_stops(monkeypatch)

        def _boom(*a, **k):
            raise AssertionError("successor dispatched on unverifiable state")
        monkeypatch.setattr(fleet, "dispatch_bg", _boom)

    def test_deleted_record_halts_before_dispatch(self, native_home, monkeypatch):
        self._seed(monkeypatch)
        _vanished(monkeypatch)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "SUP-RESPAWN-HALTED-UNVERIFIED" in str(exc.value)
        assert exc.value.rc == 2

    def test_corrupt_registry_halts_before_dispatch(self, native_home, monkeypatch):
        self._seed(monkeypatch)
        _quarantined(monkeypatch)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "SUP-RESPAWN-HALTED-UNVERIFIED" in str(exc.value)

    def test_the_halt_names_what_to_check(self, native_home, monkeypatch):
        self._seed(monkeypatch)
        _vanished(monkeypatch)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        msg = str(exc.value)
        assert "NOT DISPATCHING" in msg
        assert "fleet doctor" in msg
        assert "fleet sup-status" in msg
        assert "claude agents" in msg

    def test_it_is_not_an_abort_token(self, native_home, monkeypatch):
        """Ruling 1 enumerated exactly three abort phases; this is a fourth,
        different state (the steer landed, the claim may be released), so it
        must not answer to the abort token."""
        self._seed(monkeypatch)
        _vanished(monkeypatch)
        with pytest.raises(fleet.SupervisorLifecycleRefusal) as exc:
            fleet.cmd_respawn(_respawn_args(), **_timed())
        assert "SUP-RESPAWN-ABORTED" not in str(exc.value)


class TestConcurrentRestampTOCTOU:
    """rb MIN-A: a restamp landing BETWEEN the post-steer re-fetch and the stop
    leaves fork2 running with the record marked dead -- the rogue-session
    class. Closed by taking the stop sid set from `_cmd_kill_native`'s OWN
    under-lock registry read, which is the narrowest correct place."""

    def test_a_fork_minted_after_the_refetch_is_still_stopped(self, native_home,
                                                              monkeypatch):
        _held_claim()
        _seed_pipe_worker(status="idle")
        _releasing_send(monkeypatch)             # fork 1: HOLDER -> FORK_SID
        stops = _record_stops(monkeypatch)

        # A second fork-steer lands after §10.4's re-fetch and before the stop.
        real_kill_native = fleet._cmd_kill_native

        def restamp_then_kill(name, rec, **kw):
            with fleet.fleet_lock():
                data = fleet.load_registry()
                fleet._restamp_after_steer(data["workers"][name], FORK2_SID,
                                           FORK2_SID[:8])
                fleet.save_registry(data)
            return real_kill_native(name, rec, **kw)
        monkeypatch.setattr(fleet, "_cmd_kill_native", restamp_then_kill)

        fleet.cmd_kill(_kill_args(), **_timed())
        stopped = [s for s, _ in stops]
        # fork2 is the live one and must be the PRIMARY stop.
        assert stopped[0] == FORK2_SID, stops
        # ...and neither ancestor is abandoned.
        assert FORK_SID in stopped, stops
        assert HOLDER_SID in stopped, stops

    def test_the_stop_set_comes_from_the_under_lock_read(self):
        src = inspect.getsource(fleet._cmd_kill_native)
        assert "_authoritative" in src
        # The primary sid must not be read from the caller's snapshot first.
        assert 'sid = _authoritative.get("session_id")' in src


class TestReplaceRetryDocstringTruth:
    """rb MIN-B: the docstring claimed a wrong destination "must still fail
    fast and loud rather than after five sleeps". False on win32 for a
    DIRECTORY destination, which raises PermissionError and is retried."""

    def test_a_directory_destination_is_retried_not_fast_failed(self, tmp_path):
        dest = tmp_path / "adir"
        dest.mkdir()
        src = tmp_path / "src.txt"
        src.write_text("x", encoding="utf-8")
        slept = []
        with pytest.raises(OSError):
            fleet._replace_with_retry(str(src), str(dest), sleep=slept.append)
        # Behaviour is what it is; the docstring must SAY what it is.
        if slept:
            assert slept == [0.1, 0.2, 0.4, 0.8]
            assert sum(slept) == 1.5

    def test_the_docstring_states_the_real_behaviour(self):
        doc = inspect.getdoc(fleet._replace_with_retry)
        assert "1.5s" in doc
        assert "does not always fail fast" in doc
        # And it must no longer make the false claim.
        assert "must still fail fast" not in doc

    def test_non_permission_errors_do_fail_on_the_first_attempt(self, tmp_path):
        def missing(src, dst):
            raise FileNotFoundError(2, "No such file")
        import unittest.mock as _mock
        slept = []
        with _mock.patch.object(os, "replace", missing):
            with pytest.raises(FileNotFoundError):
                fleet._replace_with_retry(str(tmp_path / "a"), str(tmp_path / "b"),
                                          sleep=slept.append)
        assert slept == []


class TestWriteJsonAtomicRetry:
    """rb MIN-C. Wave 1 left this writer alone and recorded it as "for the
    operator to scope". The re-gate produced the harm path that settles it:
    `sup-release`'s `write_incarnation` collides with `_await_claim_released`'s
    poller -> raises -> the claim never reads `released` -> kill falls to arm 2
    -> a millisecond file lock becomes an up-to-3600s freeze."""

    def test_write_incarnation_survives_a_transient_sharing_violation(
            self, native_home, monkeypatch):
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)
        monkeypatch.setattr(os, "replace", flaky)

        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released",
                                 "released_at": fleet.now_iso()})
        assert calls["n"] == 2
        assert fleet.read_incarnation()["incarnation_id"] == "inc-x"

    def test_the_release_still_lands_under_contention(self, native_home, monkeypatch):
        """The harm path end to end: a collision on the release write must not
        turn into a frozen claim."""
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] in (1, 2):
                raise PermissionError(32, "being used by another process")
            return real(src, dst)
        monkeypatch.setattr(os, "replace", flaky)
        fleet.write_incarnation({"incarnation_id": "inc-x", "state": "released",
                                 "released_at": fleet.now_iso()})
        state, claim = fleet.read_incarnation_status()
        assert state == "ok"
        assert claim["state"] == "released"

    def test_exhausting_the_retries_still_raises(self, native_home, monkeypatch):
        def always(src, dst):
            raise PermissionError(5, "Access is denied")
        monkeypatch.setattr(os, "replace", always)
        with pytest.raises(PermissionError):
            fleet.write_incarnation({"incarnation_id": "inc-x"})

    def test_it_routes_through_the_shared_helper(self):
        src = inspect.getsource(fleet._write_json_atomic)
        assert "_replace_with_retry(str(tmp), str(path))" in src
        assert "os.replace(" not in src
