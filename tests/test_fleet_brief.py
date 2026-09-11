"""Contract tests for the repository-only ``fleet brief`` leaf."""

import argparse
import ast
import subprocess

import pytest

import fleet
import fleet_brief


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, text=True,
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "brief@example.invalid")
    _git(repo, "config", "user.name", "brief tests")
    (repo / "product.md").write_text(
        "# product\n\n## Never\n\n- Never build a fleet feature no downstream job asked for.\n\n"
        "## Other\n\nA different phrase.\n", encoding="utf-8")
    task = repo / "state" / "tasks" / "lens" / "w1.md"
    task.parent.mkdir(parents=True)
    task.write_text(
        "# Lane w1\n\nDONE means: the leaf emits a checkable brief.\n\n"
        "Serves: Never — \"Never build a fleet feature no downstream job asked for.\"\n\n"
        "Files:\n- `bin/fleet.py`, `tests/test_fleet_brief.py`\n\n"
        "```\n"
        "env -u CLAUDE_CODE_SESSION_ID -u FLEET_HOME UV_OFFLINE=1 UV_CACHE_DIR=/tmp/cache \\\n"
        "  uv run --no-project --python 3.10 --with pytest python -m pytest -q tests/test_fleet_brief.py\n"
        "```\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    return repo, task


def test_parser_registers_brief_and_dispatches_without_home_resolution(
        monkeypatch, tmp_path, capsys):
    repo, task = _repo(tmp_path)
    monkeypatch.chdir(repo)
    args = fleet.build_parser().parse_args(["brief", str(task)])
    assert args.command == "brief"
    monkeypatch.setattr(fleet, "apply_resolved_home",
                        lambda *a, **k: pytest.fail("brief resolved fleet home"))
    assert fleet.main(["brief", str(task)]) == 0
    assert "Serves: Never" in capsys.readouterr().out


def test_brief_emits_done_base_files_tests_contract_and_blank_judgement(
        tmp_path, monkeypatch, capsys):
    repo, task = _repo(tmp_path)
    monkeypatch.chdir(repo)
    assert fleet_brief.cmd_brief(argparse.Namespace(item="w1")) == 0
    output = capsys.readouterr().out
    assert "DONE means: the leaf emits a checkable brief." in output
    assert f"Base SHA: {_git(repo, 'rev-parse', 'HEAD')}" in output
    assert "- bin/fleet.py" in output
    assert "- tests/test_fleet_brief.py" in output
    assert "Test command:" in output
    assert "Structured result contract:" in output
    assert "Judgement:\n\nServes: Never" in output


@pytest.mark.parametrize("citation", [
    "",
    "Serves: Missing — \"Never build a fleet feature no downstream job asked for.\"",
    "Serves: Never — \"A different phrase.\"",
])
def test_brief_refuses_missing_or_unverified_citation(tmp_path, monkeypatch,
                                                     citation, capsys):
    repo, task = _repo(tmp_path)
    text = task.read_text(encoding="utf-8")
    original = 'Serves: Never — "Never build a fleet feature no downstream job asked for."'
    task.write_text(text.replace(original, citation), encoding="utf-8")
    monkeypatch.chdir(repo)
    with pytest.raises(fleet.FleetCliError, match="brief"):
        fleet_brief.cmd_brief(argparse.Namespace(item=str(task)))
    assert capsys.readouterr().out == ""


def test_leaf_does_not_import_fleet_or_copy_parser_globals():
    tree = ast.parse(open(fleet_brief.__file__, encoding="utf-8").read())
    imports = [node for node in ast.walk(tree)
               if isinstance(node, ast.Import) and
               any(alias.name == "fleet" for alias in node.names)]
    assert not imports
