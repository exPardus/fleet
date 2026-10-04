"""Public-tree leak guard.

The optional local denylist belongs to the user, not the repository.  Built-in
checks cover machine identity and high-confidence credential shapes even when
that file is absent.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DENYLIST = Path("state/leak-denylist.txt")

_HOME_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:home|Users)/([^/\s]+)/")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@"
    r"([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?![A-Za-z0-9.-])")
_SECRET_SHAPES = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("OpenAI-style token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


def _tracked_files(repo: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True,
        check=True)
    return [repo / raw.decode("utf-8", errors="surrogateescape")
            for raw in result.stdout.split(b"\0") if raw]


def _local_denylist(repo: Path) -> list[str]:
    try:
        lines = (repo / DENYLIST).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [line.strip() for line in lines
            if line.strip() and not line.lstrip().startswith("#")]


def public_hygiene_violations(repo: Path) -> list[str]:
    denylist = _local_denylist(repo)
    violations = []
    for path in _tracked_files(repo):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        rel = path.relative_to(repo).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in _HOME_PATH.finditer(line):
                if match.group(1) != "user":
                    violations.append(
                        f"{rel}:{line_number}: personal absolute home path")
            for match in _EMAIL.finditer(line):
                local, domain = match.groups()
                if local.lower() != "noreply" and domain.lower() != "example.com":
                    violations.append(
                        f"{rel}:{line_number}: non-placeholder email address")
            for label, pattern in _SECRET_SHAPES:
                if pattern.search(line):
                    violations.append(f"{rel}:{line_number}: {label}")
            for denied in denylist:
                if denied in line:
                    violations.append(
                        f"{rel}:{line_number}: local denylist entry {denied!r}")
    return violations


def _seed_repo(tmp_path: Path, tracked_text: str, denylist: str | None = None) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tracked.txt").write_text(tracked_text, encoding="utf-8")
    if denylist is not None:
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "leak-denylist.txt").write_text(
            denylist, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
    return tmp_path


def test_tracked_files_are_public_hygienic():
    assert not public_hygiene_violations(REPO)


def test_builtin_checks_work_without_a_local_denylist(tmp_path):
    private_header = "-----BEGIN " + "PRIVATE KEY-----"
    personal_path = "/home/" + "alice/work"
    personal_email = "alice@" + "corp.test"
    text = personal_path + "\n" + personal_email + "\n" + private_header + "\n"
    repo = _seed_repo(tmp_path, text)
    violations = public_hygiene_violations(repo)
    assert any("personal absolute home path" in item for item in violations)
    assert any("non-placeholder email address" in item for item in violations)
    assert any("private key" in item for item in violations)


def test_neutral_paths_and_placeholder_emails_are_allowed(tmp_path):
    repo = _seed_repo(
        tmp_path, "/home/user/work\n/Users/user/work\n"
        "noreply@openai.com\ndev@example.com\n")
    assert public_hygiene_violations(repo) == []


def test_untracked_local_denylist_extends_the_guard(tmp_path):
    marker = "operator" + "-local-marker"
    repo = _seed_repo(tmp_path, f"public {marker}\n", f"# local only\n{marker}\n")
    violations = public_hygiene_violations(repo)
    assert len(violations) == 1
    assert "local denylist entry" in violations[0]
    assert "state/leak-denylist.txt" not in "\n".join(violations)
