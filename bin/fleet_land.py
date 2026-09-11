"""Prepare one lane branch from its structured result.

The land command owns only Git and verification subprocesses.  Fleet state is
not a source of lane identity, so this module deliberately has no dependency
on the fleet kernel or its parser globals.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from fleet_errors import FleetCliError


REPORT_LIMIT = 40
_LANE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_BRANCH_LANE = re.compile(r"^w\d+/.+$")
_REQUIRED_RESULT_KEYS = {
    "lane", "base", "files_changed", "tests", "claims", "blockers",
}
_TEST_KEYS = {"command", "rc", "passed", "failed", "skipped"}
_CLAIM_KEYS = {"claim", "command"}


def _git(repo: Path, *args: str, cwd: Path | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    """Run one Git command and turn a failed command into a CLI refusal."""
    run_cwd = str(cwd or repo)
    result = subprocess.run(
        ["git", *args], cwd=run_cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        suffix = f": {detail[-1][:300]}" if detail else ""
        raise FleetCliError(
            f"land: git {' '.join(args)} failed (rc={result.returncode}){suffix}")
    return result


def _git_output(repo: Path, *args: str, cwd: Path | None = None) -> str:
    return (_git(repo, *args, cwd=cwd).stdout or "").strip()


def _repo_root() -> Path:
    raw = _git_output(Path.cwd(), "rev-parse", "--show-toplevel")
    if not raw:
        raise FleetCliError("land: current directory is not a Git worktree")
    return Path(raw).resolve()


def _validate_lane_name(lane: object) -> str:
    if not isinstance(lane, str) or not _LANE_NAME.fullmatch(lane):
        raise FleetCliError(
            f"land: invalid lane name {lane!r} (expected one path component)")
    return lane


def _worktree_entries(repo: Path) -> list[tuple[Path, str | None]]:
    """Return the paths and branches recorded by ``git worktree``."""
    output = _git_output(repo, "worktree", "list", "--porcelain")
    entries: list[tuple[Path, str | None]] = []
    path: Path | None = None
    branch: str | None = None
    for line in output.splitlines() + [""]:
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):].strip()).resolve()
            branch = None
        elif line.startswith("branch refs/heads/"):
            branch = line[len("branch refs/heads/"):].strip()
        elif not line and path is not None:
            entries.append((path, branch))
            path = None
            branch = None
    return entries


def _resolve_lane(repo: Path, lane: str) -> tuple[str, Path]:
    """Resolve a lane name to its unique branch and registered worktree."""
    entries = [(path, branch) for path, branch in _worktree_entries(repo)
               if branch]
    exact = [(branch, path) for path, branch in entries if branch == lane]
    if exact:
        if len(exact) > 1:
            raise FleetCliError(f"land: lane {lane!r} has multiple worktrees")
        return exact[0]
    matches = [(branch, path) for path, branch in entries
               if branch == lane or branch.startswith(lane + "/")]
    if not matches:
        raise FleetCliError(
            f"land: unknown lane {lane!r} (no registered lane worktree)")
    if len(matches) != 1:
        names = ", ".join(sorted(branch for branch, _ in matches))
        raise FleetCliError(f"land: lane {lane!r} is ambiguous: {names}")
    return matches[0]


def _repo_rel(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise FleetCliError(f"land: {field} contains an invalid path {value!r}")
    path = Path(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise FleetCliError(f"land: {field} path must be repo-relative: {value!r}")
    return path.as_posix()


def _validate_result(lane: str, worktree: Path) -> tuple[dict, str, str]:
    result_path = worktree / "docs" / "lanes" / f"{lane}.json"
    report_rel = f"docs/lanes/{lane}.md"
    result_rel = f"docs/lanes/{lane}.json"
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FleetCliError(f"land: missing lane result {result_rel}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FleetCliError(f"land: malformed lane result {result_rel}: {exc}")
    if not isinstance(payload, dict) or set(payload) != _REQUIRED_RESULT_KEYS:
        actual = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
        raise FleetCliError(
            f"land: {result_rel} must contain exactly {_REQUIRED_RESULT_KEYS}; got {actual}")
    if payload["lane"] != lane:
        raise FleetCliError(
            f"land: {result_rel} names lane {payload['lane']!r}, not {lane!r}")
    base = payload["base"]
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-fA-F]{7,40}", base):
        raise FleetCliError(f"land: {result_rel} has an invalid base commit")
    files = payload["files_changed"]
    if not isinstance(files, list):
        raise FleetCliError(f"land: {result_rel} files_changed must be a list")
    normalised_files = []
    for item in files:
        normalised_files.append(_repo_rel(item, "files_changed"))
    payload["files_changed"] = normalised_files
    tests = payload["tests"]
    if not isinstance(tests, list):
        raise FleetCliError(f"land: {result_rel} tests must be a list")
    for index, item in enumerate(tests):
        if not isinstance(item, dict) or set(item) != _TEST_KEYS:
            raise FleetCliError(f"land: {result_rel} tests[{index}] has the wrong shape")
        if not isinstance(item["command"], str) or not item["command"].strip():
            raise FleetCliError(f"land: tests[{index}] has no command")
        for key in ("rc", "passed", "failed", "skipped"):
            value = item[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise FleetCliError(f"land: tests[{index}].{key} is not a count")
    claims = payload["claims"]
    if not isinstance(claims, list):
        raise FleetCliError(f"land: {result_rel} claims must be a list")
    for index, item in enumerate(claims):
        if not isinstance(item, dict) or set(item) != _CLAIM_KEYS:
            raise FleetCliError(f"land: {result_rel} claims[{index}] has the wrong shape")
        if not isinstance(item["claim"], str) or not item["claim"].strip():
            raise FleetCliError(f"land: claims[{index}] has no claim")
        if not isinstance(item["command"], str) or not item["command"].strip():
            raise FleetCliError(f"land: claims[{index}] has no command")
    blockers = payload["blockers"]
    if not isinstance(blockers, list) or any(
            not isinstance(item, str) or not item.strip() for item in blockers):
        raise FleetCliError(f"land: {result_rel} blockers must be a list of strings")
    report_path = worktree / report_rel
    try:
        line_count = len(report_path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        raise FleetCliError(f"land: missing lane report {report_rel}")
    except (OSError, UnicodeError) as exc:
        raise FleetCliError(f"land: cannot read lane report {report_rel}: {exc}")
    if line_count > REPORT_LIMIT:
        raise FleetCliError(
            f"land: lane report {report_rel} is {line_count} lines; maximum is {REPORT_LIMIT}")
    return payload, report_rel, result_rel


def _status_paths(repo: Path, worktree: Path) -> list[str]:
    result = _git(repo, "status", "--porcelain=v1", "-z",
                   "--untracked-files=all", cwd=worktree)
    raw = result.stdout or ""
    fields = raw.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        record = fields[index]
        index += 1
        if len(record) < 3:
            continue
        status, path = record[:2], record[3:]
        paths.append(path)
        if status[0] in "RC" or status[1] in "RC":
            if index < len(fields) and fields[index]:
                paths.append(fields[index])
                index += 1
    return [_repo_rel(path, "dirty path") for path in paths]


def _tracked(repo: Path, worktree: Path, rel: str) -> bool:
    result = _git(repo, "ls-files", "--error-unmatch", "--", rel,
                   cwd=worktree, check=False)
    return result.returncode == 0


def _commit_dirty(repo: Path, worktree: Path, lane: str, files: list[str],
                  report_rel: str, result_rel: str) -> None:
    dirty = _status_paths(repo, worktree)
    allowed = set(files) | {report_rel, result_rel}
    unexpected = sorted(set(dirty) - allowed)
    if unexpected:
        raise FleetCliError(
            f"land: lane {lane!r} has unlisted dirty paths: {', '.join(unexpected)}")
    if not dirty:
        return
    stage = []
    for rel in sorted(allowed):
        path = worktree / Path(rel)
        if path.exists() or _tracked(repo, worktree, rel):
            stage.append(rel)
    if not stage:
        raise FleetCliError(f"land: lane {lane!r} is dirty but has nothing stageable")
    _git(repo, "add", "--", *stage, cwd=worktree)
    staged = _status_paths(repo, worktree)
    staged_unexpected = sorted(set(staged) - allowed)
    if staged_unexpected:
        raise FleetCliError(
            f"land: staging exposed unlisted paths: {', '.join(staged_unexpected)}")
    _git(repo, "commit", "-m", f"fleet land {lane}: record lane result", cwd=worktree)


def _base_branch(repo: Path, lane_branch: str, base: str,
                 entries: list[tuple[Path, str | None]]) -> str:
    current = _git_output(repo, "branch", "--show-current")
    candidates: list[str] = []
    if current and current != lane_branch and not _BRANCH_LANE.fullmatch(current):
        candidates.append(current)
    if not candidates:
        candidates.extend(
            branch for _, branch in entries
            if branch and branch != lane_branch and not _BRANCH_LANE.fullmatch(branch))
    valid = []
    for branch in dict.fromkeys(candidates):
        if _git(repo, "merge-base", "--is-ancestor", base, branch,
                check=False).returncode == 0:
            valid.append(branch)
    if len(valid) != 1:
        if not valid:
            raise FleetCliError(
                f"land: cannot derive the source branch containing base {base}")
        raise FleetCliError(
            f"land: base branch is ambiguous: {', '.join(sorted(valid))}")
    return valid[0]


def _rebase(repo: Path, worktree: Path, lane_branch: str,
            source_branch: str) -> None:
    result = _git(repo, "rebase", source_branch, cwd=worktree, check=False)
    if result.returncode == 0:
        return
    conflicts = _git_output(repo, "diff", "--name-only", "--diff-filter=U",
                            cwd=worktree)
    conflict_paths = [line for line in conflicts.splitlines() if line]
    abort = _git(repo, "rebase", "--abort", cwd=worktree, check=False)
    if abort.returncode:
        detail = (abort.stderr or abort.stdout or "").strip().splitlines()
        suffix = f": {detail[-1][:240]}" if detail else ""
        raise FleetCliError(
            f"land: rebase {lane_branch!r} failed and abort failed{suffix}")
    names = ", ".join(conflict_paths) if conflict_paths else "(paths not reported by Git)"
    raise FleetCliError(
        f"land: rebase {lane_branch!r} conflicted; aborted cleanly; paths: {names}")


def _run_shell(command: str, cwd: Path, log_dir: Path,
               label: str) -> int:
    """Run a recorded command and preserve complete stdout/stderr in a log."""
    result = subprocess.run(command, cwd=str(cwd), shell=True,
                            executable="/bin/sh", capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{label}.log").write_text(
        f"$ {command}\n\n{result.stdout or ''}\n--- stderr ---\n"
        f"{result.stderr or ''}", encoding="utf-8")
    return result.returncode


def _check_commands(worktree: Path, tests: list[dict]) -> list[tuple[str, int]]:
    log_dir = Path(tempfile.mkdtemp(prefix="fleet-land-"))
    checks = []
    for index, item in enumerate(tests, start=1):
        checks.append((f"tests[{index}]", _run_shell(
            item["command"], worktree, log_dir, f"test-{index}")))
    python = shlex.quote(sys.executable)
    checks.append(("docs-currency", _run_shell(
        f"{python} tests/test_docs_currency.py .", worktree, log_dir,
        "docs-currency")))
    checks.append(("receipts", _run_shell(
        f"{python} tools/verify_receipts.py --strict --skip-volatile docs/specs/*.md",
        worktree, log_dir, "receipts")))
    return checks


def cmd_land(args) -> int:
    """Stage, rebase and verify one lane without moving another ref."""
    lane = _validate_lane_name(getattr(args, "lane", None))
    repo = _repo_root()
    lane_branch, worktree = _resolve_lane(repo, lane)
    payload, report_rel, result_rel = _validate_result(lane, worktree)
    base = payload["base"]
    _git(repo, "cat-file", "-e", f"{base}^{{commit}}")
    _commit_dirty(repo, worktree, lane, payload["files_changed"],
                  report_rel, result_rel)
    entries = _worktree_entries(repo)
    source_branch = _base_branch(repo, lane_branch, base, entries)
    if source_branch == lane_branch:
        raise FleetCliError("land: lane branch cannot be its own source branch")
    _rebase(repo, worktree, lane_branch, source_branch)
    checks = _check_commands(worktree, payload["tests"])
    tip = _git_output(repo, "rev-parse", f"refs/heads/{lane_branch}")
    stat = _git_output(repo, "diff", "--shortstat", f"{base}..{tip}") or "0 files changed"
    red = [name for name, rc in checks if rc != 0]
    if payload["blockers"]:
        red.append("blockers")

    lines = [f"lane: {lane}", f"range: {base}..{tip}", f"diff: {stat}"]
    available = 10 - 1 - len(lines)
    if len(checks) <= available:
        lines.extend(f"check {name}: rc={rc}" for name, rc in checks)
    else:
        lines.extend(f"check {name}: rc={rc}" for name, rc in checks[:available - 1])
        lines.append(f"checks: {len(checks)} total; output capped at ten lines")
    lines.append("verdict: RED" if red else "verdict: GREEN")
    print("\n".join(lines[:10]))
    return 1 if red else 0


__all__ = ["cmd_land"]
