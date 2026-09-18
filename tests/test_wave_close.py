"""Focused proofs for the deterministic pieces of ``fleet wave-close``.

The expensive floor and real commit/push arm belong to the supervisor merge;
these tests pin their input parsing and the fail-closed accounting seams.
"""
import argparse
import json
import pathlib
import subprocess

import pytest

import fleet


def test_parser_requires_base_and_changelog():
    parser = fleet.build_parser()
    args = parser.parse_args(["wave-close", "--changelog", "@landing.md"])
    assert args.command == "wave-close"
    assert args.base is None
    args = parser.parse_args(["wave-close", "--base", "1556986",
                              "--changelog", "@landing.md"])
    assert args.base == "1556986"
    assert args.changelog == "@landing.md"


def test_numstat_uses_non_overlapping_buckets(tmp_path):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0,
            "1\t2\tbin/fleet.py\n3\t4\ttests/test_wave_close.py\n"
            "5\t6\tdocs/SPEC.md\n7\t8\tsupervisor/JOURNAL.md\n"
            "9\t10\tsupervisor/journal-history/x.md\n11\t12\tREADME.md\n"
            "-\t-\tassets/blob\n", "")

    buckets, paths = fleet._wave_numstat(tmp_path, "base", run=run)
    assert buckets == {"bin": [1, 2], "tests": [3, 4], "docs": [5, 6],
                       "journal": [16, 18], "other": [11, 12]}
    assert paths[-1] == "assets/blob"
    assert calls[0][-1] == "base..HEAD"


def test_roster_tokens_are_unmeasured_when_roster_omits_usage():
    assert fleet._wave_roster_claude_tokens([]) == "0"
    assert fleet._wave_roster_claude_tokens([{"sessionId": "sid"}]) == \
        "UNMEASURED (roster has no token field)"
    assert fleet._wave_roster_claude_tokens([
        {"usage": {"input_tokens": 11, "output_tokens": 7}},
        {"usage": {"input_tokens": 3, "output_tokens": 2}},
    ]) == "23"
    assert fleet._wave_roster_claude_tokens([
        {"tokens": "tokens:in=11 out=7"},
    ]) == "18"


def test_codex_result_usage_is_summed_without_double_counting_events(tmp_path):
    job = tmp_path / ".mcx" / "codex-job"
    job.mkdir(parents=True)
    (job / "result").write_text("tokens:in=11 out=7\n", encoding="utf-8")
    (job / "events.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":99,"output_tokens":99}}\n',
        encoding="utf-8")
    assert fleet._wave_codex_tokens(tmp_path) == "18"
    assert fleet._wave_codex_tokens(tmp_path / "missing") == \
        "UNMEASURED (mcx result files missing)"


def test_codex_usage_reads_the_landed_lane_worktree_events_once(tmp_path):
    lane = tmp_path / "lane"
    job = lane / ".mcx" / "job"
    job.mkdir(parents=True)
    (job / "result").write_text("completed prose\n", encoding="utf-8")
    (job / "events.jsonl").write_text(
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":30,"output_tokens":4}}\n',
        encoding="utf-8")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, f"worktree {lane}\nbranch refs/heads/w82/codex\n\n", "")

    assert fleet._wave_codex_tokens(
        tmp_path, [("w82/codex", "codex", "abc")], run=run) == "34"


def test_claude_usage_reads_wave_session_from_outcomes(tmp_path):
    lane = tmp_path / "lane"
    outcomes = tmp_path / "state" / "outcomes"
    outcomes.mkdir(parents=True)
    (tmp_path / "state" / "fleet.json").write_text(
        '{"workers":{"worker":{"cwd":"' + str(lane) + '",'
        '"session_id":"sid-current"}}}', encoding="utf-8")
    (outcomes / "worker.jsonl").write_text(
        '{"kind":"result","session_id":"sid-old","input_tokens":99,'
        '"output_tokens":99}\n'
        '{"kind":"result","session_id":"sid-current","input_tokens":11,'
        '"output_tokens":7,"cache_creation_input_tokens":5,'
        '"cache_read_input_tokens":3}\n', encoding="utf-8")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, f"worktree {lane}\nbranch refs/heads/w82/claude\n\n", "")

    assert fleet._wave_outcomes_claude_tokens(
        tmp_path, [("w82/claude", "claude", "abc")], run=run) == "26"


def test_new_usage_sources_remain_unmeasured_when_their_source_is_missing(tmp_path):
    lanes = [("w82/codex", "codex", "abc")]
    assert fleet._wave_codex_tokens(tmp_path, lanes=lanes,
                                    run=lambda *a, **k: subprocess.CompletedProcess(
                                        a[0], 0, "", "" )).startswith("UNMEASURED")
    assert fleet._wave_outcomes_claude_tokens(
        tmp_path, [("w82/claude", "claude", "abc")],
        run=lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", "")
    ).startswith("UNMEASURED")


def test_default_base_is_newest_wave_close_commit(tmp_path):
    def run(argv, **kwargs):
        assert argv[:3] == ["git", "log", "--format=%H%x09%s"]
        return subprocess.CompletedProcess(
            argv, 0,
            "deadbeef1234567\tfleet wave-close: wave 68\n"
            "old0000\tfleet wave-close: wave 67\n", "")

    assert fleet._wave_previous_close(tmp_path, run=run) == "deadbeef1234567"


def test_landed_lanes_are_merge_branches_with_substrate(tmp_path):
    lane_worktree = tmp_path / "lane-worktree"
    job = lane_worktree / ".mcx" / "mcx-job"
    job.mkdir(parents=True)
    (job / "cwd").write_text(str(lane_worktree), encoding="utf-8")
    (job / "codex").write_text("/usr/local/bin/codex\n", encoding="utf-8")

    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0, "abcdef1234567\tmerge(w68/alpha): landed\n", "")
        if argv[1] == "worktree":
            return subprocess.CompletedProcess(
                argv, 0,
                f"worktree {lane_worktree}\n"
                "HEAD abcdef1234567\n"
                "branch refs/heads/w68/alpha\n\n", "")
        # A merge trailer is deliberately misleading: substrate comes from
        # the lane record, not commit-message prose.
        return subprocess.CompletedProcess(argv, 0, "Claude-Session: fake\n", "")

    assert fleet._wave_landed_lanes(tmp_path, "base", run=run) == [
        ("w68/alpha", "codex", "abcdef1")]


def test_landed_lane_with_an_openrouter_substrate_record_is_not_claude(tmp_path):
    """item 24: a native `dispatch_kind="bg"` record with an explicit
    `openrouter/<slug>` substrate must not fall through to the pre-item-24
    "bg means claude" inference -- that would double-count OpenRouter tokens
    (real, but irrelevant to Claude spend) as Claude spend."""
    lane_worktree = tmp_path / "lane-worktree"
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "fleet.json").write_text(json.dumps({
        "workers": {"w93": {"cwd": str(lane_worktree),
                            "dispatch_kind": "bg",
                            "substrate": "openrouter/z-ai/glm-5.3-flash"}}}),
        encoding="utf-8")

    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0, "abcdef1234567\tmerge(w93/openrouter): landed\n", "")
        if argv[1] == "worktree":
            return subprocess.CompletedProcess(
                argv, 0,
                f"worktree {lane_worktree}\nbranch refs/heads/w93/openrouter\n\n", "")
        raise AssertionError(argv)

    assert fleet._wave_landed_lanes(tmp_path, "base", run=run) == [
        ("w93/openrouter", "openrouter/z-ai/glm-5.3-flash", "abcdef1")]


def test_openrouter_lane_contributes_a_measured_zero_not_unmeasured(tmp_path):
    """DONE (state/tasks/w93.md): wave-close accounts an OpenRouter lane as
    cost 0, not UNMEASURED. `_wave_outcomes_claude_tokens` only sums lanes
    whose substrate is exactly "claude" (`cmd_wave_close` applies the same
    "codex" guard before ever calling `_wave_codex_tokens`), so an
    OpenRouter-only lane list is real, measured evidence of zero Claude
    tokens -- not a gap this helper papers over."""
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "fleet.json").write_text(
        json.dumps({"workers": {}}), encoding="utf-8")
    lanes = [("w93/openrouter", "openrouter/z-ai/glm-5.3-flash", "abc")]
    never_called = lambda *a, **k: (_ for _ in ()).throw(  # noqa: E731
        AssertionError("must not touch git for a non-claude lane"))
    assert fleet._wave_outcomes_claude_tokens(tmp_path, lanes, run=never_called) == "0"


def test_landed_lane_without_a_substrate_record_is_unknown(tmp_path):
    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0, "abcdef1234567\tmerge(w68/alpha): landed\n", "")
        if argv[1] == "worktree":
            return subprocess.CompletedProcess(
                argv, 0,
                f"worktree {tmp_path / 'lane-worktree'}\n"
                "branch refs/heads/w68/alpha\n\n", "")
        return subprocess.CompletedProcess(argv, 0, "Codex\n", "")

    assert fleet._wave_landed_lanes(tmp_path, "base", run=run) == [
        ("w68/alpha", "unknown", "abcdef1")]


def test_merge_audit_names_a_merge_with_gits_own_default_subject(tmp_path):
    """`Merge <branch>: ...` (git's own default subject) matches nothing --
    the wave-83 defect (queue item 14). The audit must report it as
    unparsed, not silently drop it from the lane count.
    """
    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0, "1234567890abcd\tMerge branch 'w83/x' into main\n", "")
        raise AssertionError(argv)

    lanes, unparsed = fleet._wave_merge_audit(tmp_path, "base", run=run)
    assert lanes == []
    assert unparsed == ["1234567"]


def test_merge_audit_separates_parsed_lanes_from_unparsed_merges(tmp_path):
    lane_worktree = tmp_path / "lane-worktree"

    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0,
                "abcdef1234567\tmerge(w68/alpha): landed\n"
                "1234567890abcd\tMerge branch 'w83/x' into main\n", "")
        if argv[1] == "worktree":
            return subprocess.CompletedProcess(
                argv, 0, f"worktree {lane_worktree}\nbranch refs/heads/w68/alpha\n\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    lanes, unparsed = fleet._wave_merge_audit(tmp_path, "base", run=run)
    assert lanes == [("w68/alpha", "unknown", "abcdef1")]
    assert unparsed == ["1234567"]


def test_merge_audit_zero_merges_is_not_the_same_as_unparsed(tmp_path):
    """A genuinely empty range is the legitimate no-lanes wave, distinct from
    a range with merges wave-close could not attribute -- said explicitly
    per the brief, so the next reader knows it was considered."""
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    lanes, unparsed = fleet._wave_merge_audit(tmp_path, "base", run=run)
    assert lanes == []
    assert unparsed == []


def test_wave_close_refuses_an_unattributable_range_before_any_mutation(
        tmp_path, monkeypatch):
    """Replays the wave-83 defect end to end, through the real `git`: a
    merge landed with git's own default subject cannot be attributed to a
    lane, so `wave-close` must refuse -- naming the unparsed count -- rather
    than publish workers/tokens/external_lines as a confident MEASURED
    zero. The refusal must land before the claim, the reap and the floor
    (all mutating or expensive), so this reaches it with none of that
    machinery mocked: if the refusal came any later, this test would hang
    or fail for an unrelated reason (no FLEET_HOME, no `uv`) instead of
    exercising the refusal itself.
    """
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True, encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q")
    git("config", "user.email", "wave-close-tests@example.invalid")
    git("config", "user.name", "wave-close tests")
    (repo / "docs").mkdir()
    (repo / "docs" / "CHANGELOG.md").write_text("# Operator changelog\n\n", encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()
    git("checkout", "-qb", "w83/x")
    (repo / "lane.txt").write_text("work\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "lane work")
    git("checkout", "-q", "-")
    git("merge", "--no-ff", "--no-edit", "w83/x")
    merge_sha = git("rev-parse", "HEAD").stdout.strip()
    changelog_before = (repo / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    log_before = git("log", "--oneline").stdout

    monkeypatch.chdir(repo)
    args = argparse.Namespace(
        base=base, changelog=f"- `{merge_sha[:7]}` lane work landed",
        sid=None, nonce=None)
    with pytest.raises(fleet.FleetCliError, match=r"UNPARSED: 1 of 1"):
        fleet.cmd_wave_close(args)

    assert (repo / "docs" / "CHANGELOG.md").read_text(encoding="utf-8") == changelog_before
    assert git("log", "--oneline").stdout == log_before
    assert not git("status", "--porcelain").stdout.strip()


def test_unparsed_merge_refusal_precedes_every_mutation_in_cmd_wave_close():
    """Static ordering guard alongside the real-git proof above: the
    UNPARSED refusal must sit, in source, before the first
    `with fleet_lock():` -- the claim heartbeat write -- and therefore
    before the changelog prepend, the journal prepend and the commit that
    all follow it later in the function.
    """
    import inspect
    src = inspect.getsource(fleet.cmd_wave_close)
    refusal_at = src.index("UNPARSED:")
    lock_at = src.index("with fleet_lock():")
    assert refusal_at < lock_at


def _worktree_run(lane_worktree, branch):
    def run(argv, **kwargs):
        if argv[1:3] == ["worktree", "list"]:
            return subprocess.CompletedProcess(
                argv, 0, f"worktree {lane_worktree}\nbranch refs/heads/{branch}\n\n", "")
        raise AssertionError(argv)
    return run


def _home(tmp_path, monkeypatch, workers):
    home = tmp_path / "home"
    (home / "state").mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    fleet.save_registry({"workers": workers})
    return home


def test_mark_landed_lanes_joins_by_worktree_cwd(tmp_path, monkeypatch):
    lane_worktree = tmp_path / "lane-worktree"
    _home(tmp_path, monkeypatch, {
        "w68": {"cwd": str(lane_worktree), "status": "idle"},
        "other": {"cwd": str(tmp_path / "elsewhere"), "status": "idle"},
    })
    marked = fleet._wave_mark_landed_lanes(
        tmp_path, [("w68/alpha", "claude", "abcdef1")],
        run=_worktree_run(lane_worktree, "w68/alpha"))
    assert marked == ["w68"]
    workers = fleet.load_registry()["workers"]
    assert workers["w68"]["lane_state"] == "landed"
    assert "lane_state" not in workers["other"]


def test_mark_landed_lanes_skips_already_terminal_records(tmp_path, monkeypatch):
    lane_worktree = tmp_path / "lane-worktree"
    _home(tmp_path, monkeypatch, {
        "w68": {"cwd": str(lane_worktree), "status": "idle", "lane_state": "abandoned"},
    })
    marked = fleet._wave_mark_landed_lanes(
        tmp_path, [("w68/alpha", "claude", "abcdef1")],
        run=_worktree_run(lane_worktree, "w68/alpha"))
    assert marked == []
    assert fleet.load_registry()["workers"]["w68"]["lane_state"] == "abandoned"


def test_mark_landed_lanes_skips_an_unresolvable_worktree(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, {
        "w68": {"cwd": str(tmp_path / "lane-worktree"), "status": "idle"},
    })

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    marked = fleet._wave_mark_landed_lanes(
        tmp_path, [("w68/alpha", "claude", "abcdef1")], run=run)
    assert marked == []
    assert "lane_state" not in fleet.load_registry()["workers"]["w68"]


def test_prune_removes_only_clean_merged_lane_worktrees(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    live = tmp_path / "live"
    merged = tmp_path / "fleet-w68-merged"
    unmerged = tmp_path / "fleet-w69-unmerged"
    dirty = tmp_path / "fleet-w67-dirty"
    for path in (repo, live, merged, unmerged, dirty):
        path.mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", live)
    porcelain = (
        f"worktree {repo}\nHEAD base\nbranch refs/heads/server/persistent-fleet\n\n"
        f"worktree {merged}\nHEAD one\nbranch refs/heads/w68/merged\n\n"
        f"worktree {unmerged}\nHEAD two\nbranch refs/heads/w69/unmerged\n\n"
        f"worktree {dirty}\nHEAD three\nbranch refs/heads/w67/dirty\n\n")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:4] == ["worktree", "list", "--porcelain"]:
            return subprocess.CompletedProcess(argv, 0, porcelain, "")
        if argv[1] == "merge-base":
            return subprocess.CompletedProcess(argv, 0 if argv[3] != "w69/unmerged" else 1,
                                               "", "")
        if argv[1] == "-C":
            status = " M file.py\n" if argv[2] == str(dirty) else ""
            return subprocess.CompletedProcess(argv, 0, status, "")
        if argv[1:3] == ["worktree", "remove"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[1:3] == ["branch", "-d"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)

    stats = fleet._wave_prune_landed_worktrees(repo, "tip", run=run)
    assert stats == {"removed": 1, "skipped": 2, "unmerged": 1,
                     "dirty": 1, "protected": 0, "failed": 0}
    # Merged-ness is measured against the wave's TIP, never its base. Against
    # the base, every lane that landed in the wave being closed is by
    # construction not an ancestor, so it is reported unmerged and never
    # pruned -- the pruner then only ever reaches the previous wave's lanes.
    assert [call[2:] for call in calls if call[1] == "merge-base"] == [
        ["--is-ancestor", "w68/merged", "tip"],
        ["--is-ancestor", "w69/unmerged", "tip"],
        ["--is-ancestor", "w67/dirty", "tip"]]
    assert [call[1:] for call in calls if call[1] in {"worktree", "branch"}][-2:] == [
        ["worktree", "remove", str(merged)], ["branch", "-d", "w68/merged"]]
    assert all("--force" not in call for call in calls)


def test_changelog_gate_names_merge_without_a_line(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CHANGELOG.md").write_text(
        "- `good123` landed\n", encoding="utf-8")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "bad456789abcdef\n", "")

    assert fleet._wave_changelog_gaps(tmp_path, "base", run=run) == ["bad4567"]


def test_reap_accounting_exposes_unread_mail_protection():
    assert fleet._wave_protected_unread_mail({
        "mail": (False, "unread-mail"),
        "landed": (True, "lane-landed"),
        "live": (False, "roster-live"),
    }) == 1


def test_pytest_parser_counts_and_failure_nodes():
    stdout = ("FAILED tests/test_x.py::TestX::test_one - nope\n"
              "================ 1 failed, 10 passed, 2 skipped, 1 xfailed in 1s ================\n")
    counts, failures = fleet._wave_parse_pytest_result(stdout, "", 1)
    assert counts == {"failed": 1, "passed": 10, "skipped": 2,
                      "xfailed": 1, "xpassed": 0, "errors": 0,
                      "collected": 14, "returncode": 1}
    assert failures == {"tests/test_x.py::TestX::test_one"}


def test_prepend_helpers_keep_markdown_title_and_journal_entries(tmp_path):
    changelog = tmp_path / "docs" / "CHANGELOG.md"
    changelog.parent.mkdir()
    changelog.write_bytes(b"# Operator changelog\n\n- old\n")
    fleet._wave_prepend_after_title(changelog, "- new")
    assert changelog.read_text() == "# Operator changelog\n- new\n\n- old\n"

    journal = tmp_path / "supervisor" / "JOURNAL.md"
    journal.parent.mkdir()
    journal.write_text("# Supervisor Journal\n\n## 2026-01-01 CHECKPOINT inc=x sid=y\n\nold\n")
    fleet._wave_prepend_journal(journal, "THROUGHPUT wave 66: test")
    text = journal.read_text()
    assert "THROUGHPUT wave 66: test" in text
    assert text.index("THROUGHPUT") < text.index("## 2026-01-01")


class TestTheFloorActuallyRuns:
    """Both defects found on `wave-close`'s FIRST REAL RUN (2026-09-11, wave 67).

    The existing tests above inject `run`, so neither was reachable from them:
    one is about the argv the verb builds, the other about what it does with a
    half that produced nothing. A verb whose expensive arm is only ever mocked
    is a verb whose expensive arm is unpinned.
    """

    def _clone_stub(self, tmp_path, calls, stdout):
        """Drive `_wave_floor` with a real tests/ tree and a recording runner."""
        def fake_run(argv, **kwargs):
            if argv[:2] == ["git", "clone"] or "clone" in argv[:3]:
                dest = pathlib.Path(argv[-1])
                (dest / "tests").mkdir(parents=True, exist_ok=True)
                (dest / "tests" / "test_a.py").write_text("", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        return fake_run

    def test_the_floor_runs_pytest_through_uv_not_a_bare_interpreter(self, tmp_path):
        """NO interpreter on PATH has pytest importable on this host -- the
        china-infra venv included -- so `python3.10 -m pytest` dies with "No
        module named pytest". That is what happened on the first real run: four
        halves produced no summary and the verb aborted on an EMPTY failure set.
        `uv` supplies the interpreter and the dependency both (CLAUDE.md)."""
        calls = []
        summary = "1 passed in 0.01s\n"
        # The stub's clean run will not match the expected host-failure set, and
        # that refusal is correct -- it is the argv this test is about.
        with pytest.raises(fleet.FleetCliError):
            fleet._wave_floor(tmp_path, 99,
                              run=self._clone_stub(tmp_path, calls, summary),
                              which=lambda name: f"/usr/bin/{name}",
                              log_root=tmp_path / "logs")
        assert calls, "the floor ran no pytest at all"
        for argv in calls:
            assert argv[0].endswith("uv"), f"floor did not go through uv: {argv}"
            assert argv[1:4] == ["run", "--no-project", "--python"], argv
            assert "--with" in argv and argv[argv.index("--with") + 1] == "pytest", argv
            assert argv[argv.index("pytest") + 1:][:3] == ["python", "-m", "pytest"], argv

    def test_a_half_that_produced_no_summary_is_not_a_clean_floor(self, tmp_path):
        """The deeper defect. A half with no pytest summary parsed as zero of
        everything, and zero failures compares EQUAL to an empty expected set --
        so a floor that never ran could have read as a floor that ran clean and
        licensed the push. It must raise instead."""
        calls = []
        with pytest.raises(fleet.FleetCliError) as excinfo:
            fleet._wave_floor(tmp_path, 99,
                              run=self._clone_stub(tmp_path, calls, "No module named pytest\n"),
                              which=lambda name: f"/usr/bin/{name}",
                              log_root=tmp_path / "logs")
        assert "did not run" in str(excinfo.value)

    def test_uv_absent_is_a_loud_refusal(self, tmp_path):
        """Fail closed on the tool the floor depends on, rather than falling
        back to the bare interpreter that cannot work here."""
        with pytest.raises(fleet.FleetCliError) as excinfo:
            fleet._wave_floor(tmp_path, 99, run=self._clone_stub(tmp_path, [], ""),
                              which=lambda name: None if name == "uv" else "/usr/bin/x",
                              log_root=tmp_path / "logs")
        assert "uv" in str(excinfo.value)


def test_wave_id_survives_the_journal_board_roll(tmp_path, monkeypatch):
    """The board roll migrates the highest wave number out of JOURNAL.md.

    A first-match scan then reads a stale low number from the board and reuses a
    wave id that is already spent -- measured on wave 68, which closed labelled
    67. The derivation takes the MAX across the board, the changelog and every
    history file.
    """
    (tmp_path / "supervisor" / "journal-history").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "supervisor" / "JOURNAL.md").write_text(
        "THROUGHPUT wave 66 (aaa..bbb): bin +1/-0\n", encoding="utf-8")
    (tmp_path / "supervisor" / "journal-history" / "roll.md").write_text(
        "THROUGHPUT wave 67 (bbb..ccc): bin +1/-0\n", encoding="utf-8")
    (tmp_path / "docs" / "CHANGELOG.md").write_text("no throughput here\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "detached\n", "")

    assert fleet._wave_id(tmp_path, run=fake_run) == "68"


def test_wave_close_refreshes_the_heartbeat(monkeypatch, tmp_path):
    """A close is a turn; the holder must not look stale for the whole wave.

    Measured 2026-09-11: heartbeat_at sat 7h stale while waves 70 and 71 were
    actively closed, because wave-close replaced sup-checkpoint in the routine
    and only sup-checkpoint refreshed the beat. The keeper paged a working body.
    """
    import inspect
    src = inspect.getsource(fleet.cmd_wave_close)
    marker = 'verb="wave-close"'
    assert marker in src
    after = src.split(marker, 1)[1].split("write_incarnation", 1)[0]
    assert 'claim["heartbeat_at"] = now_iso()' in after, (
        "wave-close writes the claim without advancing heartbeat_at")


def test_external_lines_counts_a_sibling_worktree_as_inside_this_repo(tmp_path):
    # MEASURED against the live repo before this test existed: a lane worktree
    # is a SIBLING of the repository root, not a child of it, so a path-prefix
    # test calls a lane of this very repo "external". `git worktree list`
    # enumerates only this repository's worktrees, so resolution IS the answer.
    sibling = tmp_path.parent / (tmp_path.name + "-w82-lane")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, f"worktree {sibling}\nbranch refs/heads/w82/a\n\n", "")

    assert fleet._wave_external_lines(
        tmp_path, [("w82/a", "codex", "abc")], "base", run=run) == (
        "0 (MEASURED: 1 landed lane(s), all worktrees of this repo)")


def test_external_lines_refuses_to_call_an_unresolvable_lane_zero(tmp_path):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    verdict = fleet._wave_external_lines(
        tmp_path, [("w82/a", "codex", "abc")], "base", run=run)
    assert verdict.startswith("UNMEASURED (no cross-repo line receipt")
    assert "w82/a" in verdict


def test_external_lines_measured_zero_when_no_lane_landed(tmp_path):
    assert fleet._wave_external_lines(
        tmp_path, [], "base", run=lambda *a, **k: None) == (
        "0 (MEASURED: no lanes landed this wave)")


def test_tokens_per_bin_line_names_its_denominator_and_guards_zero(tmp_path):
    source = (pathlib.Path(__file__).resolve().parents[1] / "bin" / "fleet.py").read_text(
        encoding="utf-8")
    # The ratio is printed with the operands that produced it, so a reader can
    # check the division; and an unknown token total or a wave that landed no
    # `bin/` lines stays UNMEASURED rather than dividing by zero.
    assert "added bin lines" in source
    assert 'tokens_per_bin_line = ("UNMEASURED' in source
    # `reasons` also carries an unreadable lane substrate, so a wave whose
    # tokens are short by an unknown amount cannot print a ratio either.
    assert "if reasons or bin_added == 0 else" in source


def test_wave_close_marks_landed_lanes_under_the_lock_before_write_incarnation():
    """The lane-arm writer must run while `fleet_lock()` is still held, so a
    landed row's `lane_state` is durable before the claim heartbeat commits.
    """
    import inspect
    src = inspect.getsource(fleet.cmd_wave_close)
    marker = "roll_supervisor_journal(home=repo)"
    assert marker in src
    after = src.split(marker, 1)[1]
    before_write = after.split("write_incarnation(claim)", 1)[0]
    assert "_wave_mark_landed_lanes(repo, lanes, run=run)" in before_write, (
        "wave-close does not mark landed lanes before writing the claim")


def test_wave_close_stops_landed_sessions_outside_the_lock_then_reaps_again():
    """`_stop_native_session_status` can block up to its timeout, so stopping
    a just-landed lane's session must never run under `fleet_lock()`; and it
    must be followed by a SECOND `_supervisor_reap` pass, after
    `_wave_mark_landed_lanes` records the landing, so `_reap_eligible`'s lane
    arm can fire inside this same wave-close run rather than the next one.
    """
    import ast
    import inspect
    import re

    src = inspect.getsource(fleet.cmd_wave_close)
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    stop_calls = {c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name)
                 and c.func.id == "_wave_stop_landed_sessions"}
    assert stop_calls, (
        "cmd_wave_close no longer calls _wave_stop_landed_sessions -- if "
        "that is intended, this test (and the fix it pins) should be "
        "revisited")
    locked = set()
    for w in ast.walk(fn):
        if isinstance(w, ast.With) and any(
                isinstance(i.context_expr, ast.Call)
                and isinstance(i.context_expr.func, ast.Name)
                and i.context_expr.func.id == "fleet_lock" for i in w.items):
            locked |= {c.lineno for c in ast.walk(w) if isinstance(c, ast.Call)
                      and isinstance(c.func, ast.Name)
                      and c.func.id == "_wave_stop_landed_sessions"}
    assert stop_calls.isdisjoint(locked), (
        f"cmd_wave_close calls _wave_stop_landed_sessions INSIDE "
        f"fleet_lock() at {sorted(stop_calls & locked)} -- each stop can "
        "block up to its timeout and must run unlocked")

    mark_at = src.index("_wave_mark_landed_lanes(repo, lanes, run=run)")
    stop_at = src.index("_wave_stop_landed_sessions(")
    reap_calls = [m.start() for m in re.finditer(r"_supervisor_reap\(", src)]
    assert len(reap_calls) >= 2, (
        "wave-close no longer reaps twice -- the lane arm needs a pass "
        "after the stop, not just the pre-landing reap")
    assert mark_at < stop_at < reap_calls[-1], (
        "wave-close must mark landed lanes, then stop their sessions, then "
        "reap a second time, in that order")


# ---------------------------------------------------------------------------
# Queue items 26 and 16: the merge subject must JOIN, and the join key must
# not be a directory the routine tidy-up deletes.
# ---------------------------------------------------------------------------

def test_worktree_branch_reads_a_linked_worktree_head(tmp_path):
    """Item 16: the branch `fleet spawn` records is read from the worktree's
    own HEAD, so a dispatch pays no subprocess for it. Proved through real
    git for both shapes -- a linked worktree (`.git` is a file naming a
    gitdir) and a plain checkout (`.git` is a directory)."""
    def git(*args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or repo), *args], check=True,
                              capture_output=True, text=True, encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q")
    git("config", "user.email", "wave-close-tests@example.invalid")
    git("config", "user.name", "wave-close tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    linked = tmp_path / "lane"
    git("worktree", "add", "-q", "-b", "w99/lane-join", str(linked))

    assert fleet._worktree_branch(linked) == "w99/lane-join"
    assert fleet._worktree_branch(repo) in ("main", "master")
    assert fleet._worktree_branch(tmp_path / "not-a-repo") is None
    git("checkout", "-q", "--detach", cwd=linked)
    assert fleet._worktree_branch(linked) is None, (
        "a detached HEAD has no branch; None must not read as a branch name")


def test_lane_join_keeps_the_branch_after_the_worktree_is_removed(tmp_path):
    """Queue item 16, the headline: the join key is the lane BRANCH on the
    registry record, not the worktree directory. MEASURED 2026-09-16: the
    supervisor merged three lanes, removed their worktrees to tidy up, and
    `wave-close` could no longer join any of them -- a join key that the
    routine cleanup step deletes is the defect."""
    gone = tmp_path / "removed-worktree"
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "fleet.json").write_text(json.dumps({
        "workers": {"w99": {"cwd": str(gone), "branch": "w99/lane-join",
                            "dispatch_kind": "bg",
                            "substrate": "openrouter/deepseek/deepseek-v4.1-flash"}}}),
        encoding="utf-8")

    def run(argv, **kwargs):
        if argv[1:3] == ["worktree", "list"]:
            return subprocess.CompletedProcess(
                argv, 0, f"worktree {tmp_path}\nHEAD base\n"
                "branch refs/heads/server/persistent-fleet\n\n", "")
        raise AssertionError(argv)

    worktree, name, record = fleet._wave_lane_join(
        tmp_path, "w99/lane-join", run=run)
    assert worktree is None, "the worktree really is gone in this fixture"
    assert name == "w99"
    assert record["branch"] == "w99/lane-join"


def test_landed_lane_reads_substrate_from_the_branch_join_without_a_worktree(
        tmp_path):
    """The same join, through the audit that feeds every wave figure: a lane
    whose worktree is gone still reports its substrate, so `substrate:
    unknown` no longer means "the tidy-up ran" (queue items 16 and 26)."""
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "fleet.json").write_text(json.dumps({
        "workers": {"w99": {"cwd": str(tmp_path / "removed-worktree"),
                            "branch": "w99/lane-join",
                            "substrate": "openrouter/deepseek/deepseek-v4.1-flash"}}}),
        encoding="utf-8")

    def run(argv, **kwargs):
        if argv[1] == "log":
            return subprocess.CompletedProcess(
                argv, 0, "abcdef1234567\tmerge(w99/lane-join): landed\n", "")
        if argv[1:3] == ["worktree", "list"]:
            return subprocess.CompletedProcess(
                argv, 0, f"worktree {tmp_path}\nHEAD base\n"
                "branch refs/heads/server/persistent-fleet\n\n", "")
        raise AssertionError(argv)

    assert fleet._wave_landed_lanes(tmp_path, "base", run=run) == [
        ("w99/lane-join", "openrouter/deepseek/deepseek-v4.1-flash", "abcdef1")]


def test_mark_landed_lanes_joins_by_branch_after_the_worktree_is_removed(
        tmp_path, monkeypatch):
    """Item 19's stop-then-reap arm reads the names this writes. With the
    worktree pruned before the close -- the supervisor's natural tidy-up --
    the old cwd-only join marked nothing, so no session was stopped and the
    lane arm could not fire (queue items 16, 19 and 25)."""
    _home(tmp_path, monkeypatch, {
        "w99": {"cwd": str(tmp_path / "removed-worktree"), "status": "idle",
                "branch": "w99/lane-join"},
        "other": {"cwd": str(tmp_path / "elsewhere"), "status": "idle"},
    })

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "", "")

    marked = fleet._wave_mark_landed_lanes(
        tmp_path, [("w99/lane-join", "openrouter/deepseek/deepseek-v4.1-flash",
                    "abcdef1")], run=run)
    assert marked == ["w99"]
    assert fleet.load_registry()["workers"]["w99"]["lane_state"] == "landed"
    assert "lane_state" not in fleet.load_registry()["workers"]["other"]


def test_wave_close_refuses_a_lane_that_parses_but_joins_to_nothing(
        tmp_path, monkeypatch):
    """Replays wave 86 end to end, through the real `git`: both merges used
    the subject `fleet land` printed, so `_wave_landed_lanes` parsed them
    happily and item 14's refusal never fired -- and then the join collapsed,
    publishing `workers: 2 (w93: unknown, w92: unknown); tokens: 0;
    tokens_per_bin_line: 0.00` on a 701-line wave. A parsed-but-unjoined lane
    is as unattributable as an unparsed merge and must refuse the same way,
    before the claim, the reap and the floor."""
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True, encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q")
    git("config", "user.email", "wave-close-tests@example.invalid")
    git("config", "user.name", "wave-close tests")
    (repo / "docs").mkdir()
    (repo / "docs" / "CHANGELOG.md").write_text("# Operator changelog\n\n",
                                                encoding="utf-8")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()
    git("checkout", "-qb", "w99/lane-join")
    (repo / "lane.txt").write_text("work\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "lane work")
    git("checkout", "-q", "-")
    git("merge", "--no-ff", "-m", "merge(w99/lane-join): lane work", "w99/lane-join")
    merge_sha = git("rev-parse", "HEAD").stdout.strip()
    changelog_before = (repo / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    log_before = git("log", "--oneline").stdout

    monkeypatch.chdir(repo)
    args = argparse.Namespace(
        base=base, changelog=f"- `{merge_sha[:7]}` lane work landed",
        sid=None, nonce=None)
    with pytest.raises(fleet.FleetCliError, match=r"UNJOINED: 1 of 1"):
        fleet.cmd_wave_close(args)

    assert (repo / "docs" / "CHANGELOG.md").read_text(encoding="utf-8") == changelog_before
    assert git("log", "--oneline").stdout == log_before
    assert not git("status", "--porcelain").stdout.strip()


def test_unjoined_refusal_precedes_every_mutation_in_cmd_wave_close():
    """Static ordering guard beside the real-git proof above: the UNJOINED
    refusal must sit, in source, before the first `with fleet_lock():`."""
    import inspect
    src = inspect.getsource(fleet.cmd_wave_close)
    assert src.index("UNJOINED:") < src.index("with fleet_lock():")


def test_claude_tokens_are_unmeasured_when_a_lane_substrate_is_unknown():
    """Wave 86 printed `tokens: 0` on a wave whose two lanes both read
    `substrate: unknown`. A lane whose substrate could not be read may have
    been a Claude lane whose usage this total then cannot see, so the total is
    UNMEASURED -- summing what remains would print the shortfall as measured."""
    never_called = lambda *a, **k: (_ for _ in ()).throw(  # noqa: E731
        AssertionError("an unreadable substrate must not reach git"))
    verdict = fleet._wave_outcomes_claude_tokens(
        pathlib.Path("/nonexistent-repo"), [("w99/lane-join", "unknown", "abc")],
        run=never_called)
    assert verdict.startswith("UNMEASURED")
    assert "w99/lane-join" in verdict


def test_new_worker_record_keeps_the_lane_branch():
    """Item 16's field, at the record builder: `wave-close` joins a merge
    subject to this value, so it must round-trip and stay nullable for the
    records that predate it."""
    record = fleet.new_worker_record(None, "/tmp/lane", "task", "accept",
                                     branch="w99/lane-join")
    assert record["branch"] == "w99/lane-join"
    assert fleet.new_worker_record(None, "/tmp/lane", "task", "accept")["branch"] is None
