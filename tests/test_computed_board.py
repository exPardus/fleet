"""Computed supervisor board and checkpoint prose bounds."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


def _run(argv, **kwargs):
    if argv[:2] == ["git", "worktree"]:
        return SimpleNamespace(returncode=0, stdout="worktree /tmp/lane\nbranch refs/heads/w1\n", stderr="")
    if argv[:2] == ["git", "rev-parse"]:
        out = "/tmp/repo\n" if argv[-1] == "--show-toplevel" else "w83/computed-board\n" if argv[-1] == "--short" else "abc123\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    if argv[:2] == ["git", "symbolic-ref"]:
        return SimpleNamespace(returncode=0, stdout="w83/computed-board\n", stderr="")
    if argv[:2] == ["git", "status"]:
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    if argv[:2] == ["git", "rev-list"]:
        return SimpleNamespace(returncode=0, stdout="0 2\n", stderr="")
    if argv[:1] == ["free"]:
        # `free -m` prints six numbers after `Mem:`; available is the last.
        return SimpleNamespace(returncode=0, stdout="Mem: 100 20 80 1 2 77\n", stderr="")
    raise AssertionError(argv)


def test_each_computed_board_section_is_rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state/journals").mkdir(parents=True)
    (tmp_path / "state/tasks").mkdir(parents=True)
    (tmp_path / "state/journals/j.md").write_text("## Next steps\n1. pick me\n")
    (tmp_path / "state/tasks/d.md").write_text("# STANDING DIRECTIVE\nnot discharged\n")
    (tmp_path / "state/tasks/done.md").write_text("# STANDING DIRECTIVE two\nDISCHARGED 2026-09-11\n")
    (tmp_path / "state/tasks/prose.md").write_text("# Ordinary task\nmentions a standing directive in prose\n")
    snap = {"ok": True, "workers": [{"name": "w1", "status": "working", "tier": "worker", "branch": "w1"}]}
    board = fleet._render_computed_board(snap, run=_run)
    text = "\n".join(board)
    assert "pick me" in text
    assert "w1: w1 -> /tmp/lane" in text
    assert "STANDING DIRECTIVE" in text
    assert "available_memory_mb=77" in text


def test_unreadable_registry_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    result = fleet._supervisor_live_lanes({"ok": False, "reason": "bad JSON"})
    assert result == ["UNREADABLE (registry: bad JSON)"]


def test_checkpoint_refuses_four_lines_before_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    args = SimpleNamespace(body="a\nb\nc\nd", kind="CHECKPOINT", sid=None, nonce=None)
    with pytest.raises(fleet.FleetCliError, match=r"4 lines"):
        fleet.cmd_sup_checkpoint(args)


def test_bundle_cap_refuses_instead_of_truncating(monkeypatch):
    monkeypatch.setattr(fleet, "SUPERVISOR_BUNDLE_MAX_CHARS", 10)
    with pytest.raises(fleet.FleetCliError, match="exceeds"):
        fleet._render_boot_bundle([], {"ok": True, "totals": {"workers": 0, "mail": 0, "cost_usd": 0}, "workers": []}, [])


def test_a_directive_saying_not_discharged_is_not_dropped(tmp_path, monkeypatch):
    # MEASURED: unanchored, `\bDISCHARGED\b` matches the words "not
    # discharged" and the board silently omits a live directive. Anchoring
    # both markers to a line is what makes the omission impossible.
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state/tasks").mkdir(parents=True)
    (tmp_path / "state/tasks/live.md").write_text(
        "# STANDING DIRECTIVE one\nthis is NOT discharged yet\n")
    (tmp_path / "state/tasks/done.md").write_text(
        "# STANDING DIRECTIVE two\nDISCHARGED 2026-09-11\n")
    (tmp_path / "state/tasks/prose.md").write_text(
        "# Ordinary task\nbody mentions a standing directive in prose\n")
    rows = fleet._supervisor_standing_directives()
    assert any("STANDING DIRECTIVE one" in row for row in rows), rows
    assert not any("STANDING DIRECTIVE two" in row for row in rows), rows
    assert not any("Ordinary task" in row for row in rows), rows


def test_an_operator_ruling_does_not_discharge_a_directive(tmp_path, monkeypatch):
    # MEASURED against state/tasks/20260910-mechanise-batch2.md: it carries a
    # `RULED:` line and still had item 4 in flight. Treating RULED as
    # DISCHARGED hid a live directive from the board.
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state/tasks").mkdir(parents=True)
    (tmp_path / "state/tasks/ruled.md").write_text(
        "# STANDING DIRECTIVE three\nRULED: 2026-09-11 answered on its date\n")
    rows = fleet._supervisor_standing_directives()
    assert any("STANDING DIRECTIVE three" in row for row in rows), rows
