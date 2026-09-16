"""Contract tests for the repository-only ``fleet land`` leaf."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

import fleet
import fleet_land


def _git(cwd, *args, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, text=True,
                            capture_output=True)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "land tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    lane = tmp_path / "lane"
    _git(repo, "worktree", "add", "-qb", "w1/example", str(lane), "main")
    return repo, lane, _git(repo, "rev-parse", "HEAD").stdout.strip()


def _result(lane, base, **overrides):
    payload = {
        "lane": "w1",
        "base": base,
        "files_changed": ["README.md"],
        "tests": [{"command": "true", "rc": 0, "passed": 1,
                    "failed": 0, "skipped": 0}],
        "claims": [{"claim": "the command is wired", "command": "true"}],
        "blockers": [],
    }
    payload.update(overrides)
    report = lane / "docs" / "lanes" / "w1.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Lane w1\nDONE means: result is landable.\n",
                      encoding="utf-8")
    (lane / "docs" / "lanes" / "w1.json").write_text(
        json.dumps(payload), encoding="utf-8")
    return payload


def test_parser_registers_land_and_dispatches_without_home_resolution(
        monkeypatch):
    args = fleet.build_parser().parse_args(["land", "w1"])
    assert args.command == "land"
    seen = []
    monkeypatch.setattr(fleet.fleet_land, "cmd_land",
                        lambda value: seen.append(value.lane) or 17)
    monkeypatch.setattr(fleet, "apply_resolved_home",
                        lambda *a, **k: pytest.fail("land resolved fleet home"))
    assert fleet.main(["land", "w1"]) == 17
    assert seen == ["w1"]


def test_land_commits_allowed_dirty_paths_rebases_and_is_idempotent(
        tmp_path, monkeypatch, capsys):
    repo, lane, base = _repo(tmp_path)
    _result(lane, base)
    (lane / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(fleet_land, "_check_commands",
                        lambda worktree, tests: [("tests[1]", 0)])
    assert fleet_land.cmd_land(argparse.Namespace(lane="w1")) == 0
    first_tip = _git(lane, "rev-parse", "HEAD").stdout.strip()
    assert not _git(lane, "status", "--porcelain").stdout
    out = capsys.readouterr().out
    assert "verdict: GREEN" in out
    # `wave-close` only attributes a lane through the `merge(<lane>):`
    # subject convention; a GREEN `land` prints the exact command so the
    # supervisor about to merge reads it, rather than the convention being
    # enforced by a regex documented nowhere (queue item 14).
    assert "next: git merge --no-ff -m 'merge(w1): <summary>' w1/example" in out
    assert fleet_land.cmd_land(argparse.Namespace(lane="w1")) == 0
    assert _git(lane, "rev-parse", "HEAD").stdout.strip() == first_tip


def test_land_red_verdict_prints_no_merge_command(tmp_path, monkeypatch, capsys):
    repo, lane, base = _repo(tmp_path)
    _result(lane, base)
    (lane / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(fleet_land, "_check_commands",
                        lambda worktree, tests: [("tests[1]", 1)])
    assert fleet_land.cmd_land(argparse.Namespace(lane="w1")) == 1
    out = capsys.readouterr().out
    assert "verdict: RED" in out
    assert "next: git merge" not in out


def test_land_refuses_dirty_paths_not_in_the_result(tmp_path, monkeypatch):
    repo, lane, base = _repo(tmp_path)
    _result(lane, base)
    (lane / "not-listed.txt").write_text("conflict\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    with pytest.raises(fleet.FleetCliError, match="unlisted dirty paths"):
        fleet_land.cmd_land(argparse.Namespace(lane="w1"))
    assert not _git(lane, "log", "-1", "--format=%s").stdout.startswith(
        "fleet land w1")


def test_check_commands_docs_currency_catches_a_lane_report_missing_done(tmp_path):
    """Replays w90 (2026-09-16): `land`'s docs-currency check shelled
    `tests/test_docs_currency.py`'s `__main__`, which called only
    `currency_violations` -- never `test_new_lane_documents_have_done` or
    `test_dispatched_tasks_have_done` -- so a lane report missing its
    DONE-means line passed `land` with rc=0 and only failed later, at the
    wave floor, after the whole two-interpreter run (queue item 12).
    """
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q")
    _git(worktree, "config", "user.email", "land-tests@example.invalid")
    _git(worktree, "config", "user.name", "land tests")
    (worktree / "README.md").write_text("base\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    _git(worktree, "commit", "-qm", "base")
    base = _git(worktree, "rev-parse", "HEAD").stdout.strip()

    # A verbatim copy of the real check, re-cut to this synthetic repo's own
    # history so it runs the SAME logic `land` shells in the real fleet repo.
    real_script = (Path(__file__).resolve().parents[1] / "tests" /
                  "test_docs_currency.py").read_text(encoding="utf-8")
    marker = 'ADOPTION_BASE = "708fa45246ca957263b3ce299add6f13efb8c330"'
    assert marker in real_script
    (worktree / "tests").mkdir()
    (worktree / "tests" / "test_docs_currency.py").write_text(
        real_script.replace(marker, f'ADOPTION_BASE = "{base}"'), encoding="utf-8")

    lane_doc = worktree / "docs" / "lanes" / "w1.md"
    lane_doc.parent.mkdir(parents=True)
    lane_doc.write_text("# Lane w1\nno DONE line here\n", encoding="utf-8")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "add lane report")

    checks = dict(fleet_land._check_commands(worktree, []))
    assert checks["docs-currency"] != 0


def test_result_requires_a_command_for_every_claim(tmp_path):
    report = tmp_path / "docs" / "lanes"
    report.mkdir(parents=True)
    (report / "w1.md").write_text("# w1\n", encoding="utf-8")
    (report / "w1.json").write_text(json.dumps({
        "lane": "w1", "base": "a" * 7, "files_changed": [], "tests": [],
        "claims": [{"claim": "missing proof", "command": ""}],
        "blockers": [],
    }), encoding="utf-8")
    with pytest.raises(fleet.FleetCliError, match=r"claims\[0\] has no command"):
        fleet_land._validate_result("w1", tmp_path)
