"""w302: `sup-retire-legacy --stale-rows` retires supervisor rows that do not
belong to supervisor/INCARNATION's incarnation; status_snapshot flags them."""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402

CUR = "inc-20260101T000000Z-aaaa"
OLD = "inc-20250101T000000Z-bbbb"


def row(status):
    return {"session_id": "s-" + status, "status": status, "cwd": "/x",
            "last_activity": "2026-01-01T00:00:00Z", "turns": 1, "cost_usd": 0.0}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "INCARNATION").write_text(
        json.dumps({"incarnation_id": CUR, "state": "held",
                    "heartbeat_at": "2026-01-01T00:00:00Z"}), encoding="utf-8")
    fleet.save_registry({"workers": {
        f"sup|{CUR}|boot": row("idle"),
        f"sup|{OLD}|successor": row("idle"),
        f"sup|{OLD}|boot": row("working"),
        "lane": row("idle")}})
    return tmp_path


def args(**kw):
    base = dict(_fleet_home_explicit=True, stale_rows=True, dry_run=False,
                expect_inc=None, expect_sid=None)
    base.update(kw)
    return Namespace(**base)


def test_snapshot_flags_only_the_claims_incarnation_as_current(home):
    rows = {w["name"]: w for w in fleet.status_snapshot()["workers"]}
    assert rows[f"sup|{CUR}|boot"]["current_body"] is True
    assert rows[f"sup|{OLD}|successor"]["current_body"] is False
    assert "current_body" not in rows["lane"]


def test_stale_rows_retires_only_noncurrent_nonworking_supervisor_rows(home):
    assert fleet.cmd_sup_retire_legacy(args()) == 0
    w = fleet.read_registry_no_repair()["workers"]
    assert w[f"sup|{OLD}|successor"]["status"] == "dead"
    assert w[f"sup|{OLD}|successor"]["legacy_retired_incarnation_id"] == OLD
    assert w[f"sup|{OLD}|boot"]["status"] == "working"
    assert w[f"sup|{CUR}|boot"]["status"] == "idle"
    assert w["lane"]["status"] == "idle"


def test_dry_run_changes_nothing(home):
    before = fleet.read_registry_no_repair()
    assert fleet.cmd_sup_retire_legacy(args(dry_run=True)) == 0
    assert fleet.read_registry_no_repair() == before


def test_refuses_without_a_readable_claim(home):
    (home / "supervisor" / "INCARNATION").unlink()
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args())


def test_requires_explicit_home_and_rejects_claim_flags(home):
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(_fleet_home_explicit=False))
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args(expect_inc=OLD))


def test_a_handshake_successor_is_never_retired(home):
    fleet.write_handshake(OLD, "s-new")
    assert fleet.cmd_sup_retire_legacy(args()) == 0
    w = fleet.read_registry_no_repair()["workers"]
    assert w[f"sup|{OLD}|successor"]["status"] == "idle"


def test_a_pending_handoff_successor_is_never_retired(home):
    claim = fleet.read_incarnation()
    claim[fleet.HANDOFF_PENDING_KEY] = [{"successor_inc": OLD}]
    fleet.write_incarnation(claim)
    assert fleet.cmd_sup_retire_legacy(args()) == 0
    w = fleet.read_registry_no_repair()["workers"]
    assert w[f"sup|{OLD}|successor"]["status"] == "idle"


def test_a_torn_handoff_record_refuses(home):
    (home / "supervisor" / "HANDSHAKE").write_text("not json", encoding="utf-8")
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_retire_legacy(args())
    assert fleet.read_registry_no_repair()["workers"][
        f"sup|{OLD}|successor"]["status"] == "idle"


def test_the_claim_is_read_inside_the_lock(home, monkeypatch):
    """A handoff that completes before the lock is taken (claim moves to OLD)
    must be seen: the OLD body is then current and CUR is the stale one."""
    real = fleet.fleet_lock

    def lock_after_handoff():
        fleet.write_incarnation({"incarnation_id": OLD, "state": "held",
                                 "heartbeat_at": "2026-01-01T00:00:00Z"})
        return real()
    monkeypatch.setattr(fleet, "fleet_lock", lock_after_handoff)
    assert fleet.cmd_sup_retire_legacy(args()) == 0
    w = fleet.read_registry_no_repair()["workers"]
    assert w[f"sup|{OLD}|successor"]["status"] == "idle"
    assert w[f"sup|{CUR}|boot"]["status"] == "dead"
