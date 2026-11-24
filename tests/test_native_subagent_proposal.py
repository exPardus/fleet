"""The native subagent proposal cites durable anchors, never line numbers."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "docs" / "specs" / "native-subagent-lanes-proposal.md"


def _definitions():
    names = set()
    for path in sorted((ROOT / "bin").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        names.add(f"{node.name}.{item.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(target.id for target in node.targets
                             if isinstance(target, ast.Name))
    return names


def test_proposal_has_no_line_number_citations():
    text = PROPOSAL.read_text(encoding="utf-8")
    assert re.findall(r"[\w./-]+\.(?:py|md):\d+", text) == []


def test_every_cited_code_symbol_resolves():
    text = PROPOSAL.read_text(encoding="utf-8")
    cited = {
        token for token in re.findall(r"`([^`\s]+)`", text)
        if re.fullmatch(r"(?:[A-Z][A-Za-z0-9]*\.)?_?[a-z][a-z0-9_]*", token)
        and "_" in token
        or re.fullmatch(r"[A-Z][A-Z0-9_]+", token) and "_" in token
        or re.fullmatch(r"[A-Z][A-Za-z0-9]*\.[_a-z][A-Za-z0-9_]*", token)
    }
    assert cited, "the proposal should cite code by symbol"
    assert sorted(cited - _definitions()) == []
