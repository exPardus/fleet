#!/usr/bin/env python3
"""Check and maintain the boot knowledge index and dated lesson rolls."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path


CAP = 12
DATE_HEADING = re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2})(?:\s|$)")
INDEX_ENTRY = re.compile(r"^- `(?P<path>[^`]+)`(?:\s+—\s+(?P<description>.*))?$")


def knowledge_files(root: Path) -> list[Path]:
    directory = root / "knowledge"
    return sorted(path for path in directory.rglob("*")
                  if path.is_file() and path.suffix == ".md"
                  and not path.name.startswith(".") and path.name != "INDEX.md")


def _index_parts(text: str) -> tuple[str, dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    bullet_indices = [i for i, line in enumerate(lines)
                      if INDEX_ENTRY.match(line.rstrip("\r\n"))]
    if not bullet_indices:
        return text, {}, ""
    first, last = bullet_indices[0], bullet_indices[-1]
    descriptions: dict[str, str] = {}
    for i in bullet_indices:
        match = INDEX_ENTRY.match(lines[i].rstrip("\r\n"))
        assert match
        descriptions[match.group("path")] = match.group("description") or ""
    return "".join(lines[:first]), descriptions, "".join(lines[last + 1:])


def render_index(root: Path) -> str:
    index = root / "knowledge" / "INDEX.md"
    prefix, descriptions, suffix = _index_parts(index.read_text(encoding="utf-8"))
    entries = []
    for path in knowledge_files(root):
        relative = path.relative_to(root / "knowledge").as_posix()
        description = descriptions.get(relative, "")
        entries.append(f"- `{relative}`" + (f" — {description}" if description else "") + "\n")
    return prefix + "".join(entries) + suffix


def index_is_current(root: Path) -> bool:
    index = root / "knowledge" / "INDEX.md"
    return index.exists() and index.read_text(encoding="utf-8") == render_index(root)


def _dated_entries(text: str):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines)
              if line.startswith("## ")]
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        heading = DATE_HEADING.match(lines[start].rstrip("\r\n"))
        if heading:
            yield heading.group("date"), "".join(lines[start:end]), start, end


def roll_lessons(root: Path, today: date | None = None) -> list[str]:
    """Move dated entries older than thirty days to the archive verbatim."""
    today = today or date.today()
    lessons_path = root / "knowledge" / "lessons.md"
    archive_path = root / "docs" / "archive" / "lessons-history.md"
    source = lessons_path.read_text(encoding="utf-8")
    entries = list(_dated_entries(source))
    cutoff = today - timedelta(days=30)
    rolled = []
    for stamp, block, start, end in entries:
        try:
            parsed = date.fromisoformat(stamp)
        except ValueError:
            continue
        if parsed < cutoff:
            rolled.append((parsed, block, start, end))
    if not rolled:
        return []
    removed = {(start, end) for _, _, start, end in rolled}
    lines = source.splitlines(keepends=True)
    lessons_path.write_text("".join(line for i, line in enumerate(lines)
                                    if not any(start <= i < end for start, end in removed)),
                            encoding="utf-8")
    archive = archive_path.read_text(encoding="utf-8") if archive_path.exists() else "# Archived lessons\n"
    heading = f"\n\n## {today.isoformat()} — lessons rolled from knowledge/lessons.md\n"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(archive.rstrip("\n") + heading + "\n" +
                            "".join(block for _, block, _, _ in rolled),
                            encoding="utf-8")
    return [stamp.isoformat() for stamp, _, _, _ in rolled]


def violations(root: Path) -> list[tuple[str, int, bool]]:
    result = []
    for path in knowledge_files(root):
        text = path.read_text(encoding="utf-8")
        if path.name == "lessons.md":
            lines = text.splitlines(keepends=True)
            starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
            for position, start in enumerate(starts):
                end = starts[position + 1] if position + 1 < len(starts) else len(lines)
                count = len(lines[start:end])
                if count > CAP:
                    result.append((path.relative_to(root).as_posix(), count, True))
            continue
        count = len(text.splitlines())
        if count > CAP:
            result.append((path.relative_to(root).as_posix(), count, False))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--roll-lessons", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.roll_lessons:
        rolled = roll_lessons(root)
        if rolled:
            print(f"rolled {len(rolled)} lesson entr{'y' if len(rolled) == 1 else 'ies'}")
    if args.write:
        (root / "knowledge" / "INDEX.md").write_text(render_index(root), encoding="utf-8")
    bad = False
    if args.check or not args.write:
        if not index_is_current(root):
            print("knowledge/INDEX.md: stale index")
            bad = True
        for path, count, loaded in violations(root):
            print(f"{path}: {count} lines (cap {CAP})")
            if loaded:
                bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
