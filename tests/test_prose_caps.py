"""Keep context-loaded prose within its declared budgets."""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _files(root: Path):
    return sorted(path for path in root.rglob("*") if path.is_file())


def _loaded_entries(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.name == "INDEX.md":
        return [[line] for line in lines if line.startswith("- ")]
    entries, current = [], []
    for line in lines:
        if line.startswith("## "):
            if current:
                entries.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        entries.append(current)
    return entries


def test_claude_md_cap():
    assert _line_count(ROOT / "CLAUDE.md") <= 60


def test_server_interface_profile_is_absorbed_into_the_skill():
    """The profile was deleted into skills/fleet/SKILL.md, which has its own cap.

    Pinned as an absence so the file cannot come back as a second place for the
    interface role to be described.
    """
    assert not (ROOT / "docs/operator/server-interface-profile.md").exists()


@pytest.mark.parametrize("path", _files(ROOT / "supervisor/briefs"))
def test_supervisor_brief_cap(path):
    assert _line_count(path) <= 60, path


def test_loaded_knowledge_cap_and_entry_caps():
    loaded = [ROOT / "knowledge/INDEX.md", ROOT / "knowledge/lessons.md"]
    assert sum(_line_count(path) for path in loaded) <= 400
    for path in loaded:
        assert all(len(entry) <= 12 for entry in _loaded_entries(path)), path


def test_docs_total_cap():
    docs = [path for path in _files(ROOT / "docs")
            if not path.is_relative_to(ROOT / "docs" / "archive")]
    assert sum(_line_count(path) for path in docs) <= 15000


def _fleet_prose_lines():
    path = ROOT / "bin/fleet.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    doc_lines = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node, clean=False):
            expr = node.body[0]
            doc_lines.update(range(expr.lineno, expr.end_lineno + 1))
    comment_lines = {
        token.start[0]
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }
    return len(doc_lines | comment_lines)


@pytest.mark.xfail(strict=False,
                   reason="w69-code-prose will close the bin/fleet.py prose cap")
def test_fleet_py_docstring_and_comment_cap():
    assert _fleet_prose_lines() <= 4000


@pytest.mark.xfail(strict=False,
                   reason="w69-skill-caps will close the skills/fleet total cap")
def test_fleet_skill_total_cap():
    assert sum(_line_count(path) for path in _files(ROOT / "skills/fleet")) <= 400


@pytest.mark.xfail(strict=False,
                   reason="w69-zero-prose will close the repository prose lint")
def test_forbidden_prose_is_absent_from_scoped_surfaces():
    needles = ("corrected 20", "superseded", "SUPERSEDED", "CORRECTED")
    roots = [ROOT / name for name in ("bin", "CLAUDE.md", "skills",
                                      "supervisor", "docs/operator")]
    offenders = []
    for root in roots:
        paths = [root] if root.is_file() else _files(root)
        for path in paths:
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if any(needle in line for needle in needles):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, offenders


@pytest.mark.xfail(strict=False,
                   reason="operator must apply docs/operator/goals-trim-proposal.md")
def test_supervisor_goals_cap():
    assert _line_count(ROOT / "supervisor/GOALS.md") <= 80
