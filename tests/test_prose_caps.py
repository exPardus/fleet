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
    return sorted(path for path in root.rglob("*")
                  if path.is_file() and "__pycache__" not in path.parts)


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


@pytest.mark.xfail(strict=False, reason="w69-docs-cap will close the docs total cap")
def test_docs_total_cap():
    assert sum(_line_count(path) for path in _files(ROOT / "docs")) <= 15000


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


def test_fleet_py_docstring_and_comment_cap():
    assert _fleet_prose_lines() <= 4000


@pytest.mark.xfail(strict=False,
                   reason="w69-skill-caps will close the skills/fleet total cap")
def test_fleet_skill_total_cap():
    assert sum(_line_count(path) for path in _files(ROOT / "skills/fleet")) <= 400


def test_forbidden_prose_is_absent_from_scoped_surfaces():
    """No history narrative in the surfaces that load into a tier's context.

    Scoped to PROSE -- comments, docstrings and markdown -- not to every line.
    The handoff protocol's own vocabulary is `superseded_at`,
    `HANDOFF_SUPERSEDED_KEY` and `HANDOFF_SUPERSEDED_BY_RELEASE`, and a doctor
    row tells the operator a legacy file is superseded. Those are identifiers
    and user-facing text, not a record of what a document used to say. A lint
    that cannot tell them apart can only ever be xfail, which is the same as
    not having it.
    """
    needles = ("corrected 20", "superseded", "SUPERSEDED", "CORRECTED")
    roots = [ROOT / name for name in ("bin", "CLAUDE.md", "skills",
                                      "supervisor", "docs/operator")]
    offenders = []
    for root in roots:
        paths = [root] if root.is_file() else _files(root)
        for path in paths:
            # The journal archive is history by definition and loads into no
            # tier's context, exactly like docs/archive/.
            if "journal-history" in path.parts:
                continue
            prose = _prose_lines(path)
            for line_no, line in prose:
                if any(needle in line for needle in needles):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, offenders


def _prose_lines(path):
    """(line_no, text) for comment, docstring and markdown lines only."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if path.suffix != ".py":
        return list(enumerate(lines, 1))
    out = [(i, ln) for i, ln in enumerate(lines, 1) if ln.lstrip().startswith("#")]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
            continue
        body = node.body
        if not (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            continue
        start = body[0].lineno
        end = getattr(body[0], "end_lineno", start)
        out += [(i, lines[i - 1]) for i in range(start, end + 1)]
    return sorted(set(out))


@pytest.mark.xfail(strict=False,
                   reason="operator must apply docs/operator/goals-trim-proposal.md")
def test_supervisor_goals_cap():
    assert _line_count(ROOT / "supervisor/GOALS.md") <= 80
