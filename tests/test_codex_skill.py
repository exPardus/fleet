import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "codex-fleet"
INSTALLER = ROOT / "bin" / "install_codex_skill.py"


def _run(home, *args):
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--codex-home", str(home), *args],
        text=True, capture_output=True, check=False)


def test_installer_is_idempotent_and_reports_matching_hashes(tmp_path):
    first = _run(tmp_path)
    second = _run(tmp_path)
    assert first.returncode == second.returncode == 0
    first_lines = dict(line.split("=", 1) for line in first.stdout.splitlines())
    second_lines = dict(line.split("=", 1) for line in second.stdout.splitlines())
    assert first_lines["source_sha256"] == first_lines["destination_sha256"]
    assert first_lines == second_lines
    assert (tmp_path / "skills" / "fleet" / "SKILL.md").read_bytes() == (
        SOURCE / "SKILL.md").read_bytes()


def test_installer_refuses_different_destination_without_explicit_overwrite(tmp_path):
    assert _run(tmp_path).returncode == 0
    installed = tmp_path / "skills" / "fleet" / "SKILL.md"
    installed.write_text("different", encoding="utf-8")
    refused = _run(tmp_path)
    assert refused.returncode == 1
    assert "destination differs" in refused.stderr
    assert installed.read_text() == "different"
    replaced = _run(tmp_path, "--overwrite")
    assert replaced.returncode == 0
    assert installed.read_bytes() == (SOURCE / "SKILL.md").read_bytes()


@pytest.mark.skipif(not hasattr(Path, "symlink_to"), reason="symlink unavailable")
def test_installer_refuses_symlinked_destination(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    skills = tmp_path / "skills"
    skills.symlink_to(outside, target_is_directory=True)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "symlinked install path" in result.stderr
    assert not (outside / "fleet").exists()


def test_role_pressure_manifest_and_skill_pin_required_behavior():
    cases = json.loads((ROOT / "tests" / "role_pressure" /
                        "codex_fleet_cases.json").read_text())
    assert {case["id"] for case in cases} == {
        "continue-autonomy", "bounded-observation", "just-patch-it",
        "live-operation", "ambiguous-home-identity", "compacted-roster",
        "idle-codex-agent",
    }
    skill = " ".join((SOURCE / "SKILL.md").read_text().split())
    supervisor = " ".join((ROOT / "skills" / "fleet" /
                           "supervisor.md").read_text().split())
    for phrase in (
        "full canonical roster", "active-writer worktree collision",
        "later required-child RED", "followup_task",
        "queued message is not a running body",
        "real-looking provider UUID grants no mutation authority",
    ):
        assert phrase in skill or phrase in supervisor
