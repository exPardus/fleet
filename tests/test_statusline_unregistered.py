"""w302: an unregistered session gets no fleet row; old idle rows are not
advertised. Views doctrine unchanged (file reads only)."""

from __future__ import annotations

import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_statusline as sl  # noqa: E402


def ago(seconds):
    t = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(status, age, sid):
    return {"session_id": sid, "status": status, "cwd": "/x",
            "last_activity": ago(age), "turns": 1, "cost_usd": 0.0}


def make_home(path, workers):
    (path / "state").mkdir(parents=True, exist_ok=True)
    (path / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8")
    return path


@pytest.fixture
def machine(tmp_path, monkeypatch):
    listed = tmp_path / "fake-claude" / "fleet-homes.list"
    listed.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: listed)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")

    def build(workers, extra_homes=()):
        root = make_home(tmp_path / "root", workers)
        monkeypatch.setattr(fleet, "INSTALL_ROOT", root)
        monkeypatch.setattr(fleet, "FLEET_HOME", root)
        members = [make_home(tmp_path / n, {}) for n in extra_homes]
        if members:
            listed.write_text("\n".join(str(m) for m in members) + "\n",
                              encoding="utf-8")
        return root
    return build


@pytest.fixture
def run_main(monkeypatch, capsys):
    def go(sid):
        monkeypatch.setattr(sys, "stdin", io.StringIO(
            json.dumps({"session_id": sid, "cwd": str(REPO)})))
        rc = sl.main()
        return rc, capsys.readouterr().out
    return go


@pytest.mark.parametrize("extra", [(), ("other",)], ids=["single", "multi"])
def test_unregistered_session_renders_empty(machine, run_main, extra):
    machine({"w": rec("idle", 60, "member-sid")}, extra)
    rc, out = run_main("stranger-sid")
    assert rc == 0 and out == ""


@pytest.mark.parametrize("extra", [(), ("other",)], ids=["single", "multi"])
def test_registered_session_still_renders(machine, run_main, extra):
    machine({"w": rec("working", 5, "member-sid")}, extra)
    rc, out = run_main("member-sid")
    assert rc == 0 and "work 1" in out


def test_blob_without_session_id_renders_as_before(machine, run_main):
    machine({"w": rec("working", 5, "member-sid")})
    rc, out = run_main("")
    assert rc == 0 and "work 1" in out


def test_rows_older_than_the_threshold_are_not_advertised():
    old = sl.HIDE_STALE_ROW_SECONDS + 3600
    snap = {"ok": True, "workers": [
        {"status": "idle", "stale_seconds": old},
        {"status": "dead-suspected", "stale_seconds": old},
        {"status": "idle", "stale_seconds": 60},
    ]}
    line = sl.render_statusline(snap, color=False)
    assert "idle 1" in line and "dead-suspected" not in line
    assert "idle 2" not in line and "idle 3" not in line


def test_only_old_rows_means_no_live_workers():
    snap = {"ok": True, "workers": [
        {"status": "idle", "stale_seconds": 99 * 3600}]}
    line = sl.render_statusline(snap, color=False)
    assert "idle" not in line and "no live workers" in line


def test_a_working_row_is_never_hidden_by_age():
    snap = {"ok": True, "workers": [
        {"status": "working", "stale_seconds": 99 * 3600}]}
    assert "work 1" in sl.render_statusline(snap, color=False)
