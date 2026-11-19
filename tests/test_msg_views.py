"""Plan PR 11: queue counts in status_snapshot() and the statusline.

Counts come from directory listings only (spec §11, §13): no envelope parse,
no fleet.lock, no registry write, no ledger write.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_msg_core as core  # noqa: E402
import fleet_statusline as sl  # noqa: E402

ID = "{:032x}"


def _seed(home, spool=None, outbox=None):
    root = home / "state" / "msg"
    for name, states in (spool or {}).items():
        for state, n in states.items():
            d = root / "spool" / name / state
            d.mkdir(parents=True)
            for i in range(n):
                (d / (ID.format(i) + ".json")).write_text("not an envelope")
    for site, n in (outbox or {}).items():
        d = root / "outbox" / site / "q"
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"{i + 1:012d}-{ID.format(i)}.json").write_text("garbage")
    root.mkdir(parents=True, exist_ok=True)


def test_counts_match_seeded_store(tmp_path):
    _seed(tmp_path, spool={"interface": {"new": 3, "cur": 2, "done": 5},
                           "w1": {"new": 1}},
          outbox={"peer": 4})
    got = core.view_counts(tmp_path)
    assert {i["name"]: i["unread"] for i in got["identities"]} == {"interface": 3, "w1": 1}
    assert got["outbox"] == [{"site": "peer", "depth": 4}]
    assert got["unread"] == 4 and got["outbox_depth"] == 4


def test_absent_store_is_none_and_snapshot_has_no_row(tmp_path, monkeypatch):
    assert core.view_counts(tmp_path) is None
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    assert "msg" not in fleet.status_snapshot()


def test_corrupt_store_never_raises(tmp_path, monkeypatch):
    root = tmp_path / "state" / "msg"
    root.mkdir(parents=True)
    (root / "spool").write_text("a file, not a dir")
    (root / "outbox").mkdir()
    (root / "outbox" / "peer").write_text("file")
    got = core.view_counts(tmp_path)
    assert got["unread"] == 0 and got["outbox_depth"] == 0
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    fleet.status_snapshot()
    (tmp_path / "state" / "msg").rename(tmp_path / "state" / "msg-x")
    (tmp_path / "state" / "msg").write_text("file, not a dir")
    assert core.view_counts(tmp_path) is None


def test_symlinked_spool_is_not_followed(tmp_path):
    outside = tmp_path / "outside" / "new"
    outside.mkdir(parents=True)
    (outside / (ID.format(1) + ".json")).write_text("x")
    root = tmp_path / "home" / "state" / "msg" / "spool"
    root.mkdir(parents=True)
    os.symlink(tmp_path / "outside", root / "evil")
    assert core.view_counts(tmp_path / "home")["unread"] == 0


def test_snapshot_takes_no_lock_and_writes_nothing(tmp_path, monkeypatch):
    _seed(tmp_path, spool={"interface": {"new": 2}}, outbox={"peer": 1})
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)

    def boom(*a, **k):
        raise AssertionError("lock taken")

    monkeypatch.setattr(fleet, "fleet_lock", boom)
    snapshot = lambda: sorted(  # noqa: E731
        (str(p), p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    before = snapshot()
    snap = fleet.status_snapshot()
    assert snap["msg"]["unread"] == 2 and snap["msg"]["outbox_depth"] == 1
    assert snapshot() == before
    assert not (tmp_path / "state" / "msg" / "ledger.jsonl").exists()


def _snap(msg):
    snap = {"ok": True, "workers": [{"name": "w", "status": "idle", "tier": "worker",
                                     "stale_seconds": 1}],
            "supervisor": {}}
    if msg is not None:
        snap["msg"] = msg
    return snap


def test_statusline_silent_when_zero_or_absent():
    base = sl.render_statusline(_snap(None), color=False)
    assert "msg" not in base
    zero = {"unread": 0, "outbox_depth": 0, "identities": [], "outbox": []}
    assert sl.render_statusline(_snap(zero), color=False) == base


def test_statusline_shows_counts_short():
    base = sl.render_statusline(_snap(None), color=False)
    line = sl.render_statusline(_snap({"unread": 3, "outbox_depth": 0}), color=False)
    assert line == base + "  msg 3 unread"
    line = sl.render_statusline(_snap({"unread": 0, "outbox_depth": 2}), color=False)
    assert line == base + "  msg 0 unread 2 out"
    junk = sl.render_statusline(_snap({"unread": "x", "outbox_depth": True}), color=False)
    assert junk == base
