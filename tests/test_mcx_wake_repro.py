"""Integration regression for mcx completion wake delivery."""

import os
import stat
import subprocess
from datetime import datetime, timezone

import fleet


FAKE_MCX = """#!/usr/bin/env python3
import os
import sys
from pathlib import Path

root = Path(os.environ[\"MCX_DIR\"])
if len(sys.argv) != 3 or sys.argv[1] != \"result\":
    raise SystemExit(1)
state = (root / sys.argv[2] / \"state\").read_text(encoding=\"utf-8\").strip()
if state == \"done\":
    print(\"finished\")
    raise SystemExit(0)
if state == \"running\":
    raise SystemExit(2)
raise SystemExit(1)
"""


def _setup_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for directory in ("state", "supervisor", "mailbox"):
        (tmp_path / directory).mkdir()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    mcx = fake_bin / "mcx"
    mcx.write_text(FAKE_MCX, encoding="utf-8")
    mcx.chmod(mcx.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    parent_sid = "supervisor-sid"
    parent_name = "sup|inc-test|boot"
    parent = fleet.new_worker_record(parent_sid, str(tmp_path), "supervise", "bypass")
    parent["status"] = "idle"
    worktree = tmp_path / "lane"
    worktree.mkdir()
    job = worktree / ".mcx" / "job-0001"
    job.mkdir(parents=True)
    (job / "state").write_text("done", encoding="utf-8")

    lane = fleet.new_worker_record(
        None, str(worktree), "work", "dontask", spawned_by=parent_sid,
        dispatch_kind="mcx", substrate="codex",
    )
    lane.update({"mcx_id": "job-0001", "status": "working"})
    fleet.save_registry({"workers": {parent_name: parent, "lane": lane}})
    fleet.write_incarnation({
        "state": "held", "session_id": parent_sid,
        "heartbeat_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return parent_name


def test_sweep_probes_finished_mcx_and_wakes_supervisor(tmp_path, monkeypatch):
    """A finished mcx job must reach the same lane-done bridge as native lanes."""
    parent_name = _setup_home(tmp_path, monkeypatch)

    sends = []
    monkeypatch.setattr(
        fleet, "_cmd_send_native",
        lambda name, message: sends.append((name, message)) or 0,
    )

    assert fleet.sweep_lane_done(run=subprocess.run) == ["lane"]
    assert sends == [(parent_name, "LANE-DONE lane idle none")]
    assert fleet.load_registry()["workers"]["lane"]["lane_done_notified"]


def test_sweep_refuses_mcx_identity_changed_during_probe(tmp_path, monkeypatch):
    """A respawn racing the probe must not wake for the replacement job."""
    _setup_home(tmp_path, monkeypatch)
    before = fleet.load_registry()["workers"]["lane"]
    expected = dict(before)
    expected["mcx_id"] = "job-0002"

    def mutate_during_probe(*_args, **_kwargs):
        data = fleet.load_registry()
        data["workers"]["lane"]["mcx_id"] = "job-0002"
        fleet.save_registry(data)
        return "idle"

    monkeypatch.setattr(fleet, "_mcx_probe", mutate_during_probe)
    sends = []
    monkeypatch.setattr(
        fleet, "_cmd_send_native",
        lambda name, message: sends.append((name, message)) or 0,
    )

    assert fleet.sweep_lane_done(run=subprocess.run) == []
    assert sends == []
    after = fleet.load_registry()["workers"]["lane"]
    assert after["mcx_id"] == "job-0002"
    assert "lane_done_pending" not in after
    assert "lane_done_notified" not in after
    assert after == expected


def test_sweep_refuses_same_mcx_id_new_turn_during_probe(tmp_path, monkeypatch):
    """A same-id steer must not turn an old idle observation into a wake."""
    _setup_home(tmp_path, monkeypatch)
    data = fleet.load_registry()
    data["workers"]["lane"]["status"] = "idle"
    fleet.save_registry(data)
    before = fleet.load_registry()["workers"]["lane"]
    expected = dict(before)
    expected.update({"status": "working", "last_dispatch_at": "new-turn"})

    def mutate_during_probe(*_args, **_kwargs):
        data = fleet.load_registry()
        data["workers"]["lane"].update(
            {"status": "working", "last_dispatch_at": "new-turn"})
        fleet.save_registry(data)
        return "idle"

    monkeypatch.setattr(fleet, "_mcx_probe", mutate_during_probe)
    sends = []
    monkeypatch.setattr(
        fleet, "_cmd_send_native",
        lambda name, message: sends.append((name, message)) or 0,
    )

    assert fleet.sweep_lane_done(run=subprocess.run) == []
    assert sends == []
    assert fleet.load_registry()["workers"]["lane"] == expected
