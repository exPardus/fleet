"""Forward-only docs currency and DONE pins, adopted by w63 on 2026-09-10.

The lint deliberately checks a small proxy for currency, not prose correctness.
Only direct bin/*.py edits are in its code population. The adoption base excludes
all of its ancestors (including merged lanes); the remaining window is the last
20 non-merge commits. A missing cutoff object is an error, never a silent skip.

Runtime tasks are gitignored: their explicit mtime cutoff is separate from the
git cutoff. Check FLEET_HOME at dispatch, since a fresh clone has no live tasks.
"""
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
ADOPTION_BASE = "708fa45246ca957263b3ce299add6f13efb8c330"
TASK_CUTOFF = datetime(2026, 9, 10, 11, 54, tzinfo=timezone.utc).timestamp()
WINDOW = 20


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
    ).strip()


def currency_violations(repo, cutoff=ADOPTION_BASE):
    commits = git(repo, "rev-list", "--no-merges", f"--max-count={WINDOW}",
                  "HEAD", "--not", cutoff).splitlines()
    violations = []
    for commit in commits:
        names = git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only",
                    "--no-renames", "-r", commit).splitlines()
        code = any(PurePosixPath(p).parent == PurePosixPath("bin")
                   and p.endswith(".py") for p in names)
        # Archived prose is intentionally outside the current-tree currency
        # surface. A code change documented only by an archive move still needs
        # a live document or an explicit Docs: n/a trailer.
        docs = any(p.startswith("docs/") and not p.startswith("docs/archive/")
                   for p in names)
        message = git(repo, "show", "-s", "--format=%B", commit)
        exempt = re.search(r"^Docs: n/a(?:\s*--\s*\S.*)?$", message, re.M)
        if code and not docs and not exempt:
            violations.append(f"{commit}: bin/*.py changed without docs/ or Docs: n/a")
    return violations


def assert_currency(repo, cutoff=ADOPTION_BASE):
    violations = currency_violations(repo, cutoff)
    assert not violations, "\n".join(violations)


def has_done_after_title(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (len(lines) >= 2 and lines[0].startswith("# ")
            and re.fullmatch(r"DONE means: \S.*", lines[1]) is not None)


def lane_documents(repo, cutoff=ADOPTION_BASE):
    old = set(git(repo, "ls-tree", "-r", "--name-only", cutoff,
                  "--", "docs/lanes").splitlines())
    current = set(git(repo, "ls-files", "--cached", "--others", "--exclude-standard",
                      "--", "docs/lanes").splitlines())
    # All new lane documents, including reports, plus the live authoring template.
    return [repo / p for p in sorted((current - old) | {"docs/lanes/BRIEF-TEMPLATE.md"})
            if p.endswith(".md") and (repo / p).is_file()]


def dispatched_tasks(home):
    """Task files the supervisor DISPATCHES, which rule 7 governs.

    `sup~<inc>~{boot,successor}.md` is excluded: it is the task dispatched
    TO a supervisor body, machine-rendered by `_render_successor_task` /
    `sup-spawn` with a fixed preamble, not a brief anyone authors. Rule 7
    binds "every task the supervisor dispatches"; requiring the convention
    of the renderer's own output would redden the pin on a file no lane
    can edit, every time a body boots.
    """
    return [p for p in sorted((home / "state/tasks").rglob("*"))
            if p.is_file() and p.suffix in {".md", ".txt"}
            and not p.name.endswith(".boot-bundle.txt")
            and not p.name.startswith("sup~")
            # `YYYYMMDD-*.md` is an INBOUND operator ruling or wake, written by
            # the interface, not a brief the supervisor dispatched. Rule 7 binds
            # what the supervisor dispatches. These entered scope only because
            # marking them `RULED:` touched their mtimes, which is a fact about
            # the filesystem, not about who authored the file.
            and not re.fullmatch(r"\d{8}-.*", p.name)
            and p.stat().st_mtime >= TASK_CUTOFF]


def test_branch_docs_currency():
    assert_currency(REPO)


def test_new_lane_documents_have_done():
    bad = [str(p.relative_to(REPO)) for p in lane_documents(REPO)
           if not has_done_after_title(p.read_text(encoding="utf-8"))]
    assert not bad, f"Missing DONE means immediately after title: {bad}"


def test_dispatched_tasks_have_done():
    home = Path(os.environ.get("FLEET_HOME", str(REPO)))
    bad = [str(p) for p in dispatched_tasks(home)
           if not has_done_after_title(p.read_text(encoding="utf-8"))]
    assert not bad, f"Dispatched task missing DONE means immediately after title: {bad}"


def init_repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "lint@example.invalid")
    git(tmp_path, "config", "user.name", "Lint seed")
    return commit_file(tmp_path, "README.md", "baseline", "baseline")


def commit_file(repo, name, text, message):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    git(repo, "add", "--all")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def test_synthetic_commit_fails_then_docs_or_trailer_pass(tmp_path):
    import pytest
    cutoff = init_repo(tmp_path)
    bad = commit_file(tmp_path, "bin/example.py", "changed", "undocumented change")
    with pytest.raises(AssertionError, match=bad):
        assert_currency(tmp_path, cutoff)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/example.md").write_text("described", encoding="utf-8")
    git(tmp_path, "add", "docs")
    git(tmp_path, "-c", "commit.gpgsign=false", "commit", "--amend", "--no-edit", "-q")
    assert_currency(tmp_path, cutoff)
    commit_file(tmp_path, "bin/example.py", "comment", "comment only\n\nDocs: n/a -- comment only")
    assert_currency(tmp_path, cutoff)


def test_old_history_excluded_but_later_violation_named(tmp_path):
    cutoff = init_repo(tmp_path)
    old = commit_file(tmp_path, "bin/example.py", "old", "before adoption")
    assert currency_violations(tmp_path, cutoff)
    assert_currency(tmp_path, old)
    new = commit_file(tmp_path, "bin/example.py", "new", "after adoption")
    assert currency_violations(tmp_path, old) == [
        f"{new}: bin/*.py changed without docs/ or Docs: n/a"]


def test_window_is_twenty_non_merge_commits(tmp_path):
    cutoff = init_repo(tmp_path)
    bad = commit_file(tmp_path, "bin/example.py", "bad", "missing docs")
    for i in range(19):
        commit_file(tmp_path, "README.md", str(i), f"readme {i}")
    assert bad in currency_violations(tmp_path, cutoff)[0]
    commit_file(tmp_path, "README.md", "20", "readme 20")
    assert_currency(tmp_path, cutoff)


def test_merge_commit_is_excluded(tmp_path):
    cutoff = init_repo(tmp_path)
    main = git(tmp_path, "branch", "--show-current")
    git(tmp_path, "checkout", "-qb", "side")
    commit_file(tmp_path, "side.md", "side", "side")
    git(tmp_path, "checkout", "-q", main)
    commit_file(tmp_path, "main.md", "main", "main")
    git(tmp_path, "merge", "--no-ff", "--no-commit", "side")
    commit_file(tmp_path, "bin/merge.py", "merge resolution", "merge")
    assert_currency(tmp_path, cutoff)


def test_docs_in_later_commit_do_not_repair_earlier_code_commit(tmp_path):
    cutoff = init_repo(tmp_path)
    bad = commit_file(tmp_path, "bin/example.py", "bad", "missing docs")
    commit_file(tmp_path, "docs/example.md", "late", "late documentation")
    assert bad in currency_violations(tmp_path, cutoff)[0]


def test_done_detector_rejects_absent_empty_or_late_line():
    assert has_done_after_title("# Task\n\nDONE means: visible outcome.\n")
    assert not has_done_after_title("# Task\nNo done line\n")
    assert not has_done_after_title("# Task\nDONE means: \n")
    assert not has_done_after_title("# Task\nPreface\nDONE means: result.\n")


def test_task_cutoff_checks_new_and_rewritten_tasks(tmp_path):
    tasks = tmp_path / "state/tasks/lens"
    tasks.mkdir(parents=True)
    old = tasks / "old.md"
    new = tasks / "new.txt"
    bundle = tasks / "worker.boot-bundle.txt"
    for p in (old, new, bundle):
        p.write_text("# Task\nmissing DONE\n", encoding="utf-8")
    os.utime(old, (TASK_CUTOFF - 1, TASK_CUTOFF - 1))
    for p in (new, bundle):
        os.utime(p, (TASK_CUTOFF, TASK_CUTOFF))
    assert dispatched_tasks(tmp_path) == [new]
    os.utime(old, (TASK_CUTOFF, TASK_CUTOFF))
    assert set(dispatched_tasks(tmp_path)) == {old, new}


def test_new_lane_document_is_in_pin_population(tmp_path):
    cutoff = init_repo(tmp_path)
    p = tmp_path / "docs/lanes/new-brief.md"
    p.parent.mkdir(parents=True)
    p.write_text("# Brief\nmissing DONE\n", encoding="utf-8")
    assert lane_documents(tmp_path, cutoff) == [p]
    assert not has_done_after_title(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--cutoff", default=ADOPTION_BASE)
    args = parser.parse_args()
    errors = currency_violations(args.repo, args.cutoff)
    print("\n".join(errors) if errors else "PASS: docs currency (last 20 non-merge commits after cutoff)")
    raise SystemExit(bool(errors))
