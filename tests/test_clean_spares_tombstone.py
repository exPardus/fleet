"""`fleet clean` must not delete the `sup-release` tombstone while the body it
vouches for is still in the roster (ULTRAREVIEW P1-10).

THE DEFECT, AS A SEQUENCE OF SHIPPED VERBS. `sup-release` tombstones the
releasing body's own registry record (`status = "dead"`), and that tombstone is
the entire reason a successor can boot without anyone stopping the retired
session first: `_releaser_body_is_tombstoned` reads it and B6 stands down. But
`"dead"` is in `_NATIVE_STICKY`, so `recompute_worker_native` hands it straight
back without consulting the roster, and `cmd_clean` deletes on the recomputed
status alone. One `fleet clean` in the release window pops the record --
`carriers` goes EMPTY, `_releaser_body_is_tombstoned` flips back to False,
`released_by_sid in live_sids` re-arms, and the successor's `sup-boot` refuses.

WHY THE WINDOW IS OPEN-ENDED AND NOT A RACE. `sup-release` runs no `claude
stop` -- the body is told to exit itself -- and `_roster_live_sids` only excludes
`state == "done"`, so the released session stays roster-live until something
stops it. That window is the design, not a hazard; `fleet clean` is a
first-class verb an operator may run inside it, and the tombstone DISARMS the §7
gate, so a sid-bearing caller is permitted to.

WHAT IS PINNED HERE IS BEHAVIOUR, NOT THE PREDICATE: a released supervisor's
successor can still `sup-boot` after a clean sweep. The internals may move; that
sentence may not stop being true.

THE COLLATERAL IS PINNED TOO, in both directions -- the spare must release the
moment the body leaves the roster (or `clean` would stop being able to sweep a
retired supervisor at all), and it must not spare any ordinary dead worker that
happens to be swept during the release window.
"""
from types import SimpleNamespace

import pytest

import fleet


RELEASER = "sid-releaser"
SUCCESSOR = "sid-successor"
BODY = "sup|inc-old|boot"
OTHER = "worker-unrelated"

# A record the releasing body already HAD is necessarily older than the release
# it performed -- the fork-steer boundary `_releaser_live_sids` draws.
BEFORE_RELEASE = "2020-01-01T00:00:00Z"


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME -- the twin of `test_sup_release_tombstone.py`'s."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


@pytest.fixture(autouse=True)
def _never_dispatch(monkeypatch):
    """No test in this file may reach a real claude session."""
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
        "a clean/boot test reached dispatch_bg -- that dispatches a REAL session"))


def _record(current, retired=(), created=BEFORE_RELEASE, **extra):
    rec = fleet.new_worker_record(current, "C:/proj", "t", "acceptEdits",
                                  dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    rec["created"] = created
    rec.update(extra)
    return rec


def _install(rec, name=BODY):
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _roster(monkeypatch, *live_sids, ok=True):
    entries = [{"sessionId": s, "status": "idle", "pid": 4242} for s in live_sids]
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (ok, entries if ok else "roster unavailable"))
    return entries


def _stand_down(sid=RELEASER, inc="inc-old"):
    """The real stand-down: hold the claim, then `sup-release` it. Returns the
    incarnation id. Uses the shipped verbs so the tombstone under test is the
    one `sup-release` actually writes, never a hand-planted `status: dead`."""
    beat = fleet.now_iso()
    value = fleet.mint_nonce()
    fleet.write_incarnation(
        {"incarnation_id": inc, "session_id": sid, "claimed_at": beat,
         "heartbeat_at": beat, "claimed_via": "fresh",
         "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 4,
         "lineage_id": "lin-20260101T000000Z-aaaa"})
    assert fleet.cmd_sup_release(
        SimpleNamespace(sid=sid, nonce=value, reason=None)) == 0
    return inc


def _boot(sid=SUCCESSOR):
    """A successor's `fleet sup-boot`, end to end. Returns (rc, stdout)."""
    return fleet.main(["sup-boot", "--sid", sid])


def _workers():
    return fleet.load_registry()["workers"]


# --- 1. THE PIN --------------------------------------------------------------

class TestASuccessorCanStillBootAfterACleanSweep:
    """The one sentence this slice exists to keep true."""

    def test_the_successor_boots_after_clean_swept_the_release_window(
            self, sup_home, monkeypatch, capsys):
        _install(_record(RELEASER))
        _stand_down()
        # The released session is STILL in the roster -- `sup-release` ran no
        # `claude stop`, and that is the documented design.
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        capsys.readouterr()
        rc = _boot()
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "VERDICT: claim" in out, out

    def test_the_control_the_successor_boots_when_no_clean_ran(
            self, sup_home, monkeypatch, capsys):
        # Without this, the pin above could pass because the tombstone never
        # worked in the first place.
        _install(_record(RELEASER))
        _stand_down()
        _roster(monkeypatch, RELEASER)
        capsys.readouterr()
        rc = _boot()
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "VERDICT: claim" in out, out

    @pytest.mark.parametrize("argv", [
        ["clean", "--yes"],
        ["clean", "--yes", "--dead-only"],
    ])
    def test_the_evidence_survives_every_clean_tier(self, sup_home, monkeypatch,
                                                    capsys, argv):
        # `--dead-only` spares tombstoned (archived) records but sweeps
        # confirmed-dead ones -- and the release tombstone is a confirmed-dead
        # NON-archived record, so it is in that tier's crosshairs too.
        _install(_record(RELEASER))
        _stand_down()
        _roster(monkeypatch, RELEASER)
        assert fleet.main(argv) == 0
        assert BODY in _workers(), f"{argv} deleted the release tombstone"

    def test_the_archived_carrier_is_spared_too(self, sup_home, monkeypatch,
                                                capsys):
        # An archived record is "ALWAYS doomed" in `cmd_clean` -- it never
        # enters the recompute at all -- so the sticky-status route is not the
        # only way to reach the deletion.
        _install(_record(RELEASER, archived_at=fleet.now_iso()))
        _stand_down()
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        assert BODY in _workers(), "clean deleted an archived release carrier"

    def test_an_unreadable_roster_never_deletes_the_evidence(
            self, sup_home, monkeypatch, capsys):
        # Sparing is reversible (run `clean` again); deleting is not. A roster
        # fleet cannot read must therefore abstain, not sweep -- and the
        # archived arm is not covered by the G9 epoch freeze.
        _install(_record(RELEASER, archived_at=fleet.now_iso()))
        _stand_down()
        _roster(monkeypatch, ok=False)
        assert fleet.main(["clean", "--yes"]) == 0
        assert BODY in _workers(), "clean deleted the evidence on a blind roster"


# --- 2. THE COLLATERAL, BOTH DIRECTIONS -------------------------------------

class TestTheSpareIsNarrowAndSelfReleasing:

    def test_clean_sweeps_the_retired_body_once_it_leaves_the_roster(
            self, sup_home, monkeypatch, capsys):
        # The spare exists only for the window in which deleting the record
        # would re-arm the wedge. Once the released session is gone from the
        # roster, B6 cannot arm on it and `clean` must be able to sweep --
        # otherwise a retired supervisor record becomes permanently unsweepable.
        _install(_record(RELEASER))
        _stand_down()
        _roster(monkeypatch)                     # the body exited
        assert fleet.main(["clean", "--yes"]) == 0
        assert BODY not in _workers()

    def test_an_ordinary_dead_worker_is_still_swept_in_the_release_window(
            self, sup_home, monkeypatch, capsys):
        # A released claim must not make every dead record unsweepable -- only
        # the record that carries the releasing body's sid.
        _install(_record(RELEASER))
        _install(_record("sid-other", status="dead"), name=OTHER)
        _stand_down()
        _roster(monkeypatch, RELEASER, "sid-other")
        assert fleet.main(["clean", "--yes"]) == 0
        assert OTHER not in _workers(), "the spare leaked onto an unrelated worker"
        assert BODY in _workers()

    def test_a_held_claim_spares_nothing(self, sup_home, monkeypatch, capsys):
        # Keyed on a RELEASED claim. A live held claim wedges nothing, so a
        # dead record whose sid the holder happens to match is ordinary refuse.
        _install(_record(RELEASER, status="dead"))
        beat = fleet.now_iso()
        value = fleet.mint_nonce()
        fleet.write_incarnation(
            {"incarnation_id": "inc-live", "session_id": RELEASER,
             "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
             "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 1,
             "lineage_id": "lin-20260101T000000Z-aaaa"})
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        assert BODY not in _workers()


# --- 3. THE OPERATOR CAN SEE IT ---------------------------------------------

class TestTheSpareIsNotSilent:

    def test_clean_names_what_it_spared_and_why(self, sup_home, monkeypatch,
                                                capsys):
        # A record `clean` declined to delete, with no line about it, reads as
        # "there was nothing to clean" -- and the next reader has no way to
        # learn that fleet is holding load-bearing evidence for them.
        _install(_record(RELEASER))
        inc = _stand_down()
        _roster(monkeypatch, RELEASER)
        assert fleet.main(["clean", "--yes"]) == 0
        out = capsys.readouterr().out
        assert BODY in out and inc in out and RELEASER in out, out
