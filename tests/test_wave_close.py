"""Focused proofs for the deterministic pieces of ``fleet wave-close``.

The expensive floor and real commit/push arm belong to the supervisor merge;
these tests pin their input parsing and the fail-closed accounting seams.
"""
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
