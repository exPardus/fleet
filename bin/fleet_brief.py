"""Render a small, checkable brief from one dispatched task file."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fleet_errors import FleetCliError


_DONE_RE = re.compile(r"^DONE means:\s+\S.*$")
_SERVES_RE = re.compile(
    r'^Serves:\s*(?P<section>[^—]+?)\s+—\s+"(?P<phrase>.+)"\s*$')
_HEADING_RE = re.compile(r"^## (?!#)(?P<title>.+?)\s*$")
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:bin|docs|skills|tests|state|product)"
    r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|md|json|txt)")

_STRUCTURED_RESULT = (
    "docs/lanes/<lane>.json with exactly fields lane, base, files_changed, "
    "tests, claims, blockers; test entries command, rc, passed, failed, "
    "skipped; claim entries claim and command"
)


def _git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        suffix = f": {detail[-1][:300]}" if detail else ""
        raise FleetCliError(
            f"brief: git {' '.join(args)} failed (rc={result.returncode}){suffix}")
    return (result.stdout or "").strip()


def _repo_root() -> Path:
    raw = _git_output(Path.cwd(), "rev-parse", "--show-toplevel")
    if not raw:
        raise FleetCliError("brief: current directory is not a Git worktree")
    return Path(raw).resolve()


def _task_path(item: str, repo: Path) -> Path:
    requested = Path(item)
    candidates = [requested]
    if not requested.is_absolute():
        candidates.extend([
            repo / requested,
            repo / "state" / "tasks" / requested,
        ])
        if requested.suffix:
            candidates.append(repo / "state" / "tasks" / "lens" / requested)
        else:
            candidates.extend([
                repo / "state" / "tasks" / f"{requested}.md",
                repo / "state" / "tasks" / "lens" / f"{requested}.md",
            ])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    raise FleetCliError(f"brief: task file not found: {item}")


def _done_line(lines: list[str]) -> str:
    positions = [index for index, line in enumerate(lines) if line.strip()]
    if len(positions) < 2 or not lines[positions[0]].strip().startswith("# "):
        raise FleetCliError(
            "brief: task file must start with a title followed by DONE means")
    done_index = positions[1]
    if not _DONE_RE.fullmatch(lines[done_index].strip()):
        raise FleetCliError(
            "brief: task file must start with a title followed by DONE means")
    # Markdown permits a long DONE sentence to wrap physically. Preserve the
    # authored sentence as one line in the emitted brief, stopping at its blank
    # separator rather than treating the next section as part of the outcome.
    end = next((index for index in range(done_index + 1, len(lines))
                if not lines[index].strip()), len(lines))
    return " ".join(line.strip() for line in lines[done_index:end])


def _serves_line(lines: list[str], product: Path) -> str:
    candidates = [line.strip() for line in lines if line.strip().startswith("Serves:")]
    if not candidates:
        raise FleetCliError("brief: task file is missing a Serves: citation")
    if len(candidates) != 1:
        raise FleetCliError("brief: task file has more than one Serves: citation")
    line = candidates[0]
    match = _SERVES_RE.fullmatch(line)
    if not match:
        raise FleetCliError(
            'brief: Serves: must be `<section> — "<exact phrase>"`')
    try:
        product_lines = product.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise FleetCliError(f"brief: cannot read product.md: {exc}") from exc
    section = match.group("section").strip()
    starts = [
        index for index, raw in enumerate(product_lines)
        if (heading := _HEADING_RE.fullmatch(raw))
        and heading.group("title").strip() == section
    ]
    if not starts:
        raise FleetCliError(f"brief: product.md has no ## {section} section")
    if len(starts) != 1:
        raise FleetCliError(f"brief: product.md has multiple ## {section} sections")
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(product_lines))
         if _HEADING_RE.fullmatch(product_lines[index])),
        len(product_lines),
    )
    phrase = match.group("phrase")
    if phrase not in "\n".join(product_lines[start + 1:end]):
        raise FleetCliError(
            f"brief: Serves phrase does not occur under ## {section} in product.md")
    return line


def _file_list(text: str) -> list[str]:
    found: list[str] = []
    in_suite = False
    in_files_block = False
    in_file_bullet = False
    for line in text.splitlines():
        if line.lstrip().startswith("SUITES"):
            in_suite = True
            in_files_block = False
            in_file_bullet = False
            continue
        # Suite bullets and their indented continuations are the task's authored
        # file list; the command must not invent files from its own implementation.
        if ((in_suite or in_files_block) and line.lstrip().startswith("-")
                and ("**" in line or "`" in line)):
            source = line
            in_file_bullet = True
        elif ((in_suite or in_files_block) and in_file_bullet
              and line.startswith((" ", "\t"))):
            source = line
        elif re.match(r"^\s*(?:Files?(?: changed)?):", line, re.I):
            in_files_block = True
            in_suite = False
            in_file_bullet = False
            continue
        else:
            if in_suite and line.strip():
                in_suite = False
            if in_files_block and line.strip():
                in_files_block = False
            in_file_bullet = False
            continue
        for path in _PATH_RE.findall(source):
            if path not in found:
                found.append(path)
    return found


def _test_commands(text: str) -> list[str]:
    commands: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("env -u CLAUDE_CODE_SESSION_ID"):
            continue
        parts = [line.strip().rstrip("\\").strip()]
        cursor = index + 1
        while cursor < len(lines) and (line.rstrip().endswith("\\") or
                                       lines[cursor].strip().startswith("uv run")):
            line = lines[cursor]
            parts.append(line.strip().rstrip("\\").strip())
            cursor += 1
            if not line.rstrip().endswith("\\"):
                break
        command = " ".join(part for part in parts if part)
        if command not in commands:
            commands.append(command)
    return commands


def cmd_brief(args) -> int:
    """Emit a validated, intentionally incomplete lane brief."""
    repo = _repo_root()
    task = _task_path(args.item, repo)
    try:
        text = task.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FleetCliError(f"brief: cannot read task file {task}: {exc}") from exc
    lines = text.splitlines()
    done = _done_line(lines)
    serves = _serves_line(lines, repo / "product.md")
    files = _file_list(text)
    commands = _test_commands(text)
    base = _git_output(repo, "rev-parse", "HEAD")

    print(f"# Brief: {task.stem}")
    print(done)
    print(f"Base SHA: {base}")
    print("File list:")
    if files:
        for path in files:
            print(f"- {path}")
    else:
        print("- (model supplies)")
    print("Test command:")
    if commands:
        for command in commands:
            print(f"- {command}")
    else:
        print("- (model supplies)")
    print(f"Structured result contract: {_STRUCTURED_RESULT}")
    print("Judgement:")
    print()
    print(serves)
    return 0


__all__ = ["cmd_brief"]
