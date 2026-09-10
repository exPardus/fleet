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
    with pytest.raises(SystemExit):
        parser.parse_args(["wave-close", "--base", "1556986"])
    args = parser.parse_args(["wave-close", "--base", "1556986",
                              "--changelog", "@landing.md"])
    assert args.command == "wave-close"
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
    assert fleet._wave_roster_claude_tokens([{"sessionId": "sid"}]) == "UNMEASURED"
    assert fleet._wave_roster_claude_tokens([
        {"usage": {"input_tokens": 11, "output_tokens": 7}},
        {"usage": {"input_tokens": 3, "output_tokens": 2}},
    ]) == "23"


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
