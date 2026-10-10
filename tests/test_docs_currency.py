"""Forward-only docs currency and DONE pins, adopted by w123 on 2026-10-05.

The lint deliberately checks a small proxy for currency, not prose correctness.
Only direct bin/*.py edits are in its code population. The adoption base excludes
all of its ancestors (including merged lanes); the remaining window is the last
20 non-merge commits. A missing cutoff object is an error, never a silent skip.

Runtime tasks are gitignored: their explicit mtime cutoff is separate from the
git cutoff. Check FLEET_HOME at dispatch, since a fresh clone has no live tasks.
"""
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
ADOPTION_BASE = "117bfa75b755e8cc566f3a608484e0023ab0e636"
# Wave 76 is the first dispatch covered by the product-line citation pin.
# Older runtime briefs stay grandfathered; rewriting one puts it in scope.
TASK_CUTOFF = datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc).timestamp()
_SERVES_RE = re.compile(
    r'^Serves:\s*(?P<section>[^—]+?)\s+—\s+"(?P<phrase>.+)"\s*$')
WINDOW = 20
# This target ancestor refreshed only executable self-citation prose. Its
# missing trailer cannot be repaired without rewriting the shared merge base.
HISTORICAL_METADATA_EXEMPTIONS = {
    # 7f405164 changed the parser's top-level help formatting without the
    # docs-currency surface in the same commit. The follow-up docs/reference
    # repair is intentionally a new commit, so keep this immutable history
    # violation explicit rather than pretending a later docs edit repairs it.
    "7f405164fc1c20d5eca3d9a9b81e21d063ed0942",
    "ffd1197836ef2f5a586f35434d58b97ab5c3f892",
}


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
    ).strip()


def _forward_documentation_receipt(repo, commit, code_paths):
    """Verify an immutable descendant documentation repair, never a SHA waiver.

    The receipt's introducing commit must change the live docs it pins. Both
    committed and working document bytes must still match; archive/untracked
    documents, changed receipts, unrelated ancestry and incomplete scope refuse.
    Semantic coverage still requires independent review of that repair commit.
    """
    path = f"docs/currency-remediations/{commit}.json"
    try:
        raw = (Path(repo) / path).read_bytes()
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict)
                or set(receipt) != {"schema", "code_commit", "code_paths", "documents"}
                or type(receipt["schema"]) is not int or receipt["schema"] != 1
                or receipt["code_commit"] != commit
                or receipt["code_paths"] != sorted(code_paths)
                or not isinstance(receipt["documents"], dict)
                or not receipt["documents"]):
            return False
        introduced = git(repo, "log", "--diff-filter=A", "--format=%H", "--", path).splitlines()
        if len(introduced) != 1:
            return False
        repair = introduced[0]
        if repair == commit or git(repo, "merge-base", commit, repair) != commit:
            return False
        if git(repo, "merge-base", repair, "HEAD") != repair:
            return False
        if any(subprocess.check_output([
                "git", "-C", str(repo), "show", f"{revision}:{path}"]) != raw
               for revision in (repair, "HEAD")):
            return False
        changed = git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only",
                      "--no-renames", "-r", repair).splitlines()
        for document, digest in receipt["documents"].items():
            parts = PurePosixPath(document).parts
            if (not parts or parts[0] != "docs" or len(parts) < 2
                    or parts[1] in {"archive", "currency-remediations"}
                    or ".." in parts or document not in changed
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                return False
            committed = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"HEAD:{document}"])
            repaired = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{repair}:{document}"])
            working = (Path(repo) / document).read_bytes()
            if any(hashlib.sha256(data).hexdigest() != digest
                   for data in (committed, repaired, working)):
                return False
        return True
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return False


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
        #
        # The surface is docs/, skills/ and knowledge/ (operator ruling,
        # 2026-09-11). docs/ alone was too narrow to be true: `skills/fleet/`
        # became the operating manual when 314ea3e absorbed
        # docs/operator/server-interface-profile.md into it, and a host fact
        # belongs in knowledge/projects/<p>.md by the brief template. A bin/
        # change documented in either was properly documented and still failed.
        docs = any((p.startswith("docs/") and not p.startswith("docs/archive/"))
                   or p.startswith("skills/") or p.startswith("knowledge/")
                   for p in names)
        message = git(repo, "show", "-s", "--format=%B", commit)
        exempt = (commit in HISTORICAL_METADATA_EXEMPTIONS
                  or re.search(r"^Docs: n/a(?:\s*--\s*\S.*)?$", message, re.M))
        code_paths = sorted(p for p in names if PurePosixPath(p).parent == PurePosixPath("bin")
                            and p.endswith(".py"))
        repaired = code and not docs and not exempt and _forward_documentation_receipt(
            repo, commit, code_paths)
        if code and not docs and not exempt and not repaired:
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
    """Current lane reports, excluding ignored per-home operator files."""
    root = repo / "docs" / "lanes"
    if not root.is_dir():
        return []
    try:
        names = git(repo, "ls-files", "--cached", "--others",
                    "--exclude-standard", "--", "docs/lanes").splitlines()
        candidates = [repo / name for name in names]
    except (OSError, subprocess.CalledProcessError):
        # The focused helper tests use an uninitialised temporary directory;
        # retain their filesystem-only population there.
        candidates = list(root.glob("*.md"))
    return [path for path in sorted(candidates)
            if path.name not in {"README.md", "BRIEF-TEMPLATE.md"}]


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


def valid_serves(text, product=None):
    """Return whether one task has one exact, section-scoped product citation."""
    product = REPO / "product.md" if product is None else Path(product)
    citations = [line.strip() for line in text.splitlines()
                 if line.strip().startswith("Serves:")]
    if len(citations) != 1:
        return False
    match = _SERVES_RE.fullmatch(citations[0])
    if not match:
        return False
    try:
        lines = product.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return False
    section = match.group("section").strip()
    headings = [i for i, line in enumerate(lines)
                if re.fullmatch(r"## (?!#).+?\s*", line)
                and line[3:].strip() == section]
    if len(headings) != 1:
        return False
    start = headings[0] + 1
    end = next((i for i in range(start, len(lines))
                if re.fullmatch(r"## (?!#).+?\s*", lines[i])), len(lines))
    return match.group("phrase") in "\n".join(lines[start:end])


def test_branch_docs_currency():
    assert_currency(REPO)


def test_new_lane_documents_have_done():
    bad = [str(p.relative_to(REPO)) for p in lane_documents(REPO)
           if not has_done_after_title(p.read_text(encoding="utf-8"))]
    assert not bad, f"Missing DONE means immediately after title: {bad}"


def test_dispatched_tasks_have_done():
    configured = os.environ.get("FLEET_HOME")
    if not configured:
        return
    home = Path(configured)
    bad = [str(p) for p in dispatched_tasks(home)
           if not has_done_after_title(p.read_text(encoding="utf-8"))]
    assert not bad, f"Dispatched task missing DONE means immediately after title: {bad}"


def test_dispatched_tasks_have_valid_serves():
    configured = os.environ.get("FLEET_HOME")
    if not configured:
        return
    home = Path(configured)
    bad = [str(path) for path in dispatched_tasks(home)
           if not valid_serves(path.read_text(encoding="utf-8"))]
    assert not bad, f"Dispatched task missing a valid Serves citation: {bad}"


def init_repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "lint@example.com")
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


def _receipt_fixture(repo, *, document="docs/repaired.md", wrong=None):
    cutoff = init_repo(repo)
    bad = commit_file(repo, "bin/example.py", "bad", "missing documentation")
    content = "Reviewed description of the original behavior.\n"
    receipt = {"schema": 1, "code_commit": bad, "code_paths": ["bin/example.py"],
               "documents": {document: hashlib.sha256(content.encode()).hexdigest()}}
    if wrong == "scope":
        receipt["code_paths"] = ["bin/unrelated.py"]
    if wrong == "code":
        receipt["code_commit"] = cutoff
    if wrong == "hash":
        receipt["documents"][document] = "0" * 64
    path = Path(repo) / "docs/currency-remediations" / (bad + ".json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(receipt))
    commit_file(repo, document, content, "Forward documentation repair")
    return cutoff, bad, path, document


def test_forward_receipt_repairs_only_exact_historical_omission(tmp_path):
    cutoff, bad, _path, _doc = _receipt_fixture(tmp_path)
    assert_currency(tmp_path, cutoff)
    new_bad = commit_file(tmp_path, "bin/example.py", "new behavior", "new omission")
    violations = currency_violations(tmp_path, cutoff)
    assert any(new_bad in failure for failure in violations)
    assert not any(bad in failure for failure in violations)


def test_forward_receipt_rejects_changed_document_or_receipt(tmp_path):
    cutoff, bad, path, document = _receipt_fixture(tmp_path)
    (tmp_path / document).write_text("changed documentation")
    assert any(bad in failure for failure in currency_violations(tmp_path, cutoff))
    git(tmp_path, "checkout", "--", document)
    path.write_text(path.read_text() + " ")
    assert any(bad in failure for failure in currency_violations(tmp_path, cutoff))


def test_forward_receipt_rejects_incomplete_or_wrong_binding(tmp_path):
    for wrong in ("scope", "code", "hash"):
        repo = tmp_path / wrong
        repo.mkdir()
        cutoff, bad, _path, _doc = _receipt_fixture(repo, wrong=wrong)
        assert any(bad in failure for failure in currency_violations(repo, cutoff))


def test_forward_receipt_rejects_archived_or_untracked_document(tmp_path):
    cutoff, bad, path, document = _receipt_fixture(
        tmp_path, document="docs/archive/repaired.md")
    assert any(bad in failure for failure in currency_violations(tmp_path, cutoff))
    receipt = json.loads(path.read_text())
    document = "docs/untracked.md"
    (tmp_path / document).write_text("untracked")
    receipt["documents"] = {document: hashlib.sha256(b"untracked").hexdigest()}
    commit_file(tmp_path, str(path.relative_to(tmp_path)), json.dumps(receipt), "receipt edit")
    assert any(bad in failure for failure in currency_violations(tmp_path, cutoff))


def test_done_detector_rejects_absent_empty_or_late_line():
    assert has_done_after_title("# Task\n\nDONE means: visible outcome.\n")
    assert not has_done_after_title("# Task\nNo done line\n")
    assert not has_done_after_title("# Task\nDONE means: \n")
    assert not has_done_after_title("# Task\nPreface\nDONE means: result.\n")


def test_serves_detector_checks_section_and_verbatim_phrase(tmp_path):
    product = tmp_path / "product.md"
    product.write_text(
        "# product\n\n## Never\n\nNever build this.\n\n"
        "## Other\n\nA phrase that must not cross sections.\n",
        encoding="utf-8")
    good = 'Serves: Never — "Never build this."'
    assert valid_serves(good, product)
    assert not valid_serves('Serves: Other — "Never build this."', product)
    assert not valid_serves('Serves: Never — "A phrase that must not cross sections."', product)
    assert not valid_serves("", product)


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


def test_main_runs_the_done_checks_not_just_currency_violations():
    """`fleet land` shells this module's `__main__` directly, not through
    pytest (queue item 12): it must run the same DONE checks the wave
    floor's pytest pass does, not only `currency_violations`, or a lane
    report missing its DONE-means line shows `land` GREEN and only fails
    later, at the floor, after the whole two-interpreter run (w90,
    2026-09-16). See test_fleet_land.py for the behavioral replay through
    `fleet_land._check_commands`.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    main_block = source.split('if __name__ == "__main__":', 1)[1]
    assert "test_new_lane_documents_have_done" in main_block
    assert "test_dispatched_tasks_have_done" in main_block


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--cutoff", default=ADOPTION_BASE)
    args = parser.parse_args()
    errors = currency_violations(args.repo, args.cutoff)
    # `fleet land` shells this module directly rather than through pytest (no
    # pytest dependency guaranteed present), so __main__ must run every check
    # the wave floor's pytest pass does -- not just `currency_violations` --
    # or a lane can show `land`'s GREEN while failing the floor's DONE pin
    # (w90, 2026-09-16).
    for check in (test_new_lane_documents_have_done, test_dispatched_tasks_have_done):
        try:
            check()
        except AssertionError as exc:
            errors.append(str(exc))
    print("\n".join(errors) if errors else "PASS: docs currency (last 20 non-merge commits after cutoff)")
    raise SystemExit(bool(errors))


def test_forward_receipt_requires_document_change_in_introducing_commit(tmp_path):
    cutoff = init_repo(tmp_path)
    bad = commit_file(tmp_path, "bin/example.py", "bad", "missing docs")
    commit_file(tmp_path, "docs/repaired.md", "late", "ordinary late docs")
    record = {"schema": 1, "code_commit": bad, "code_paths": ["bin/example.py"],
              "documents": {"docs/repaired.md": hashlib.sha256(b"late").hexdigest()}}
    commit_file(tmp_path, f"docs/currency-remediations/{bad}.json", json.dumps(record), "receipt only")
    assert any(bad in error for error in currency_violations(tmp_path, cutoff))


def test_forward_receipt_requires_repair_descendant_of_original_source(tmp_path):
    cutoff = init_repo(tmp_path)
    main = git(tmp_path, "branch", "--show-current")
    bad = commit_file(tmp_path, "bin/example.py", "bad", "missing docs")
    git(tmp_path, "checkout", "-qb", "unrelated-repair", cutoff)
    document = "docs/repaired.md"
    record = {"schema": 1, "code_commit": bad, "code_paths": ["bin/example.py"],
              "documents": {document: hashlib.sha256(b"coverage").hexdigest()}}
    receipt_path = tmp_path / f"docs/currency-remediations/{bad}.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(record))
    commit_file(tmp_path, document, "coverage", "unrelated source repair")
    git(tmp_path, "checkout", "-q", main)
    git(tmp_path, "merge", "--no-ff", "-qm", "merge unrelated docs", "unrelated-repair")
    assert any(bad in error for error in currency_violations(tmp_path, cutoff))


def test_forward_receipt_cannot_use_working_only_document(tmp_path):
    cutoff = init_repo(tmp_path)
    bad = commit_file(tmp_path, "bin/example.py", "bad", "missing docs")
    document = "docs/untracked.md"
    (tmp_path / "docs").mkdir()
    (tmp_path / document).write_text("working only")
    record = {"schema": 1, "code_commit": bad, "code_paths": ["bin/example.py"],
              "documents": {document: hashlib.sha256(b"working only").hexdigest()}}
    receipt = f"docs/currency-remediations/{bad}.json"
    (tmp_path / receipt).parent.mkdir()
    (tmp_path / receipt).write_text(json.dumps(record))
    git(tmp_path, "add", receipt)
    git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", "untracked docs receipt")
    assert git(tmp_path, "ls-files", "--", document) == ""
    assert any(bad in error for error in currency_violations(tmp_path, cutoff))


def test_forward_receipt_requires_head_even_when_working_copy_is_reverted(tmp_path):
    cutoff, bad, path, document = _receipt_fixture(tmp_path)
    original = path.read_bytes()
    edited = json.loads(original)
    edited["code_paths"] = ["bin/unrelated.py"]
    commit_file(tmp_path, str(path.relative_to(tmp_path)), json.dumps(edited), "alter receipt")
    path.write_bytes(original)
    assert any(bad in failure for failure in currency_violations(tmp_path, cutoff))
