"""Focused proofs for the deterministic pieces of ``fleet wave-close``.

The expensive floor and real commit/push arm belong to the supervisor merge;
these tests pin their input parsing and the fail-closed accounting seams.
"""
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

    stats = fleet._wave_prune_landed_worktrees(repo, "base", run=run)
    assert stats == {"removed": 1, "skipped": 2, "unmerged": 1,
                     "dirty": 1, "protected": 0, "failed": 0}
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
