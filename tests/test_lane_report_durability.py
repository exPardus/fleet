"""Per-home operational artifacts stay local while generic design stays public."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def _ignored(paths: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"], cwd=REPO, input="\n".join(paths),
        text=True, capture_output=True)
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.splitlines())


@pytest.mark.unit
def test_operator_data_paths_are_gitignored():
    paths = [
        "supervisor/GOALS.md",
        "supervisor/JOURNAL.md",
        "supervisor/journal-history/journal-roll.md",
        "supervisor/briefs/wake.md",
        "knowledge/lessons.md",
        "knowledge/projects/projectx.md",
        "docs/lanes/w1.md",
        "docs/lanes/w1.json",
        "docs/operator/runbook.md",
    ]
    assert _ignored(paths) == set(paths)


@pytest.mark.unit
def test_generic_design_paths_remain_trackable():
    paths = [
        "docs/SPEC.md",
        "docs/specs/native-substrate.md",
        "knowledge/playbooks/campaign-template.md",
        "skills/fleet/SKILL.md",
    ]
    assert _ignored(paths) == set()
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", *paths], cwd=REPO, text=True).splitlines()
    assert set(tracked) == set(paths)


@pytest.mark.unit
def test_no_operator_data_path_is_tracked():
    tracked = set(subprocess.check_output(
        ["git", "ls-files"], cwd=REPO, text=True).splitlines())
    deleted = set(subprocess.check_output(
        ["git", "ls-files", "--deleted"], cwd=REPO, text=True).splitlines())
    tracked -= deleted
    forbidden = (
        "supervisor/", "knowledge/projects/", "docs/lanes/",
        "docs/operator/", "docs/reviews/", "docs/archive/",
        "docs/proposals/", "docs/decisions/",
    )
    offenders = [path for path in sorted(tracked) if path == "knowledge/lessons.md"
                 or path == "docs/OPERATOR-GATES.md"
                 or path.startswith(forbidden)]
    assert offenders == []


@pytest.mark.unit
@pytest.mark.parametrize("rel", [
    "CLAUDE.md", "docs/SPEC.md", "skills/fleet/SKILL.md",
])
def test_operating_surfaces_state_the_local_data_rule(rel):
    text = (REPO / rel).read_text(encoding="utf-8").lower()
    assert "operator data" in text
    assert "local" in text
