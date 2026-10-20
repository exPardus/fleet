#!/usr/bin/env python3
"""Check or refresh bin/fleet.py's self-citations using the pin-test oracle."""
from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))
import test_self_citations as pins  # noqa: E402 -- the single citation oracle
from fleet_sources import fleet_implementation_paths  # noqa: E402


def _install_source(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    if path.resolve() == pins.SRC_PATH.resolve() and source == pins.SRC_RAW:
        return source
    pins.SRC_PATH = path
    pins.SRC_RAW = source
    pins.SRC = source.splitlines()
    pins.CODE_LINES = pins._code_lines(source)
    pins.IMPLEMENTATION_RAW = "\n\n".join(
        [source] + [p.read_text(encoding="utf-8")
                    for p in fleet_implementation_paths()[1:]])
    pins.IMPLEMENTATION_SRC = pins.IMPLEMENTATION_RAW.splitlines()
    pins.CLASSIFIED = pins._classified_numbers(source)
    pins.SELF_CITATIONS = [(line, n) for line, n, kind in pins.CLASSIFIED
                           if kind == "self"]
    pins.FUNCTION_QUALIFIED = pins._function_qualified_citations()
    pins.RANGED_QUALIFIED = [c for c in pins.FUNCTION_QUALIFIED if c[3] is not None]
    pins.BY_CITATION, pins.BY_SITE = pins._assignment()
    return source


def _baseline(path: Path) -> list[str]:
    if path.resolve() != (ROOT / "bin" / "fleet.py").resolve():
        return (ROOT / "bin" / "fleet.py").read_text(encoding="utf-8").splitlines()
    result = subprocess.run(["git", "show", "HEAD:bin/fleet.py"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout.splitlines() if result.returncode == 0 else []


def _line_map(old: list[str], new: list[str]) -> dict[int, int]:
    mapping = {}
    prefix = 0
    while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
        prefix += 1
    for n in range(prefix):
        mapping[n + 1] = n + 1
    old_end, new_end = len(old), len(new)
    while old_end > prefix and new_end > prefix and old[old_end - 1] == new[new_end - 1]:
        mapping[old_end] = new_end
        old_end -= 1
        new_end -= 1
    for tag, a, b, c, d in difflib.SequenceMatcher(
            None, old[prefix:old_end], new[prefix:new_end], autojunk=True).get_opcodes():
        if tag == "equal":
            mapping.update((prefix + n + 1, prefix + c + n - a + 1)
                           for n in range(a, b))
    return mapping


def _candidate(site, citing: int, old: int, named: str | None,
               mapping: dict[int, int]) -> int:
    span = pins._function_span(named) if named else None
    if named and span is None:
        raise ValueError(f"named function {named!r} does not exist")
    if site.one_of or site.exactly:
        candidates = set(pins.DERIVATIONS[site.one_of or site.exactly]())
    elif site.anchor:
        candidates = {n for n, line in enumerate(pins.SRC, 1)
                      if site.anchor in line}
    else:
        raise ValueError(f"{site.name}: no target derivation")
    if span:
        candidates = {n for n in candidates if span[0] <= n <= span[1]}
    if site.anchor:
        candidates = {n for n in candidates if site.anchor in pins.SRC[n - 1]}
    if not candidates:
        raise ValueError(f"{site.name}: target is absent")
    if named and site.anchor and len(candidates) != 1:
        raise ValueError(f"{site.name}: anchor {site.anchor!r} is ambiguous in {named}")
    if len(candidates) == 1:
        return next(iter(candidates))
    mapped = mapping.get(old)
    if mapped in candidates:
        return mapped
    if old in candidates:
        return old
    raise ValueError(f"{site.name}: target is ambiguous: {sorted(candidates)}")


def refresh(path: Path, write: bool) -> tuple[int, list[str]]:
    source = _install_source(path)
    mapping = _line_map(_baseline(path), pins.SRC)
    issues = []
    changes: dict[int, str] = {}
    by_line: dict[int, list] = {}
    for (line, old), owners in pins.BY_CITATION.items():
        by_line.setdefault(line, []).append((old, owners))
    for line, entries in by_line.items():
        original = pins.SRC[line - 1]
        matches = [m for m in pins._NUMBER_RE.finditer(original)
                   if (line, int(m.group(1))) in pins.SELF_CITATIONS]
        if len(matches) != len(entries):
            issues.append(f"{path}:{line}: citation token count changed")
            continue
        replacements = []
        # Entries preserve scanner order, including duplicate numbers.
        for match, (old, owners) in zip(matches, entries):
            if old != int(match.group(1)) or len(owners) != 1:
                issues.append(f"{path}:{line}: missing or ambiguous site for :{old}")
                continue
            site = owners[0]
            named_match = site.match(line)
            named = named_match.group(1) if site.in_named_function else None
            prefix = original[:match.start()]
            qualified = re.search(r'`(\w+):$', prefix)
            if qualified:
                named = qualified.group(1)
            try:
                target = _candidate(site, line, old, named, mapping)
            except ValueError as exc:
                issues.append(f"{path}:{line}: {exc}")
                continue
            if target != old:
                issues.append(f"{path}:{line}: :{old} -> :{target} ({site.name})")
                replacements.append((match.start(1), match.end(1), str(target)))
        # Named ranges have a second number with no colon.
        for m in pins._NAMED_CITATION_RE.finditer(original):
            if not m.group(3):
                continue
            start, end = int(m.group(2)), int(m.group(3))
            refreshed_start = next((int(value) for begin, finish, value in replacements
                                    if (begin, finish) == (m.start(2), m.end(2))),
                                   start)
            if refreshed_start != start or mapping.get(start) == start:
                mapped = mapping.get(end)
            elif pins._range_defect(m.group(1), start, end) is None:
                # An already refreshed start no longer addresses its baseline
                # line. Preserve the current valid end on a second pass.
                mapped = end
            else:
                mapped = mapping.get(end)
            if mapped is None:
                span = pins._function_span(m.group(1))
                if span and end == span[1]:
                    mapped = span[1]
            if mapped is None:
                issues.append(f"{path}:{line}: range end :{end} is ambiguous")
            elif mapped != end:
                issues.append(f"{path}:{line}: range end :{end} -> :{mapped}")
                replacements.append((m.start(3), m.end(3), str(mapped)))
        updated = original
        for start, end, value in sorted(replacements, reverse=True):
            updated = updated[:start] + value + updated[end:]
        changes[line] = updated
    if write and issues and any("ambiguous" in issue or "absent" in issue or
                                "missing" in issue or "count changed" in issue
                                for issue in issues):
        return 1, issues
    if write and changes:
        lines = source.splitlines(keepends=True)
        for line, updated in changes.items():
            ending = "\n" if lines[line - 1].endswith("\n") else ""
            lines[line - 1] = updated + ending
        path.write_text("".join(lines), encoding="utf-8")
    return (1 if issues and not write else 0), issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--path", type=Path, default=ROOT / "bin" / "fleet.py",
                        help="fleet.py copy to check (for tests)")
    args = parser.parse_args()
    rc, issues = refresh(args.path, args.write)
    for issue in issues:
        print(issue)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
