"""Incident pin: a completed worker turn must always leave a READABLE outcome.

2026-07-27, worker `gate-hf-rb`: a 14,760-character ESCALATE report carrying a
CRITICAL finding was lost outright. Its text contained a lone surrogate
(`\\udc90`, inside the mojibake run `\u00e2\u2020\\udc90` -- a markdown-table arrow
mangled by a cp1252/utf-8 round-trip in the worker's own tool output).
`stop_outcome.py` built the record with `json.dumps(..., ensure_ascii=False)`
and then `.encode("utf-8")`, which raises `UnicodeEncodeError: surrogates not
allowed`. The exception was swallowed into `state/hook-errors.log` and NO
outcome record was written at all -- `fleet result gate-hf-rb` reported "no
outcome record for current session".

These tests drive the WHOLE path, hook subprocess -> on-disk JSONL ->
`fleet.cmd_result`, because the defect lived in the seam between the writer and
the reader, not inside either one. Asserting on a sanitiser in isolation would
not have caught it.

What each assertion is defending against (a pin nobody can make vacuous with a
one-line edit is the only pin worth having):

- `rc == 0` + the head/tail markers: kills "write the record but drop/null the
  text" and "truncate at the offending character". Priority-1 of the fix brief
  is that the report SURVIVES, not merely that a file appears.
- the legit-unicode marker: kills the lazy repair `text.encode("ascii",
  "ignore")`, which would make every surrogate test pass while silently
  eating every em-dash, accent and check mark a real report contains.
- the length floor: kills truncation at the offending index specifically
  (the incident's own failure offset was 7034 of ~14,760).
- parametrising the surrogate codepoint: kills a fix keyed to the one
  character this incident happened to produce.
- both input routes: `last_assistant_message` and the transcript-tail
  fallback are two independent producers of `result_text`; a fix applied to
  one leaves the other lost.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_OUTCOME = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"

SID = "aaaabbbb-1111-2222-3333-444455556666"

# Every lone surrogate is unencodable, not just the one this incident produced:
# the low end of the high range, the high end of the low range, and the actual
# character from the gate-hf-rb report.
LONE_SURROGATES = ["\ud800", "\udc90", "\udfff"]

# A legit non-ASCII run that MUST come back byte-for-byte. Any "fix" that
# reaches for ASCII-only sanitisation destroys this and fails the pin.
LEGIT_UNICODE = "caf\u00e9 \u2014 r\u00e9sum\u00e9 \u2713 \u00b1 \u03bc"

HEAD = "## ESCALATE -- CRITICAL"
TAIL = "END OF REPORT (this line must survive)"


def _report(surrogate: str) -> str:
    """A report shaped like the one that was lost: markers at both ends, the
    legit-unicode run intact, and the bad character buried in the middle of a
    markdown table exactly where the mojibake arrow was."""
    return (
        f"{HEAD}\n\n"
        f"Locale note: {LEGIT_UNICODE}\n\n"
        "| step | verdict |\n"
        "| ---- | ------- |\n"
        f"| decode \u00e2\u2020{surrogate} encode | CRITICAL |\n\n"
        "The finding: the gate stayed green under a line-count-identical reword.\n"
        f"{TAIL}\n"
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with a registry the hook can resolve sid -> name
    through, and which `fleet.cmd_result` can read back."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    rec = fleet.new_worker_record(SID, "C:/proj", "do the thing", "accept",
                                  dispatch_kind="bg")
    rec["status"] = "idle"
    rec["native_short_id"] = SID[:8]
    fleet.save_registry({"workers": {"w1": rec}})
    return tmp_path


def _run_stop_outcome(home_dir, payload: dict):
    """Fire the real hook as a real subprocess, exactly as Claude Code does.

    `json.dumps` defaults to ensure_ascii=True, so the surrogate travels to the
    hook as the seven ASCII bytes `\\udc90` and is reconstituted as a real lone
    surrogate by the hook's own `json.loads` -- the same way the live harness
    delivered it."""
    env = dict(os.environ)
    env["FLEET_HOME"] = str(home_dir)
    return subprocess.run(
        [sys.executable, str(STOP_OUTCOME)],
        input=json.dumps(payload), capture_output=True, text=True,
        env=env, timeout=30,
    )


def _make_transcript(home_dir, text):
    tdir = Path(home_dir) / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    path = tdir / "t.jsonl"
    path.write_text(json.dumps({
        "type": "assistant",
        "message": {"model": "claude-haiku-4-5-20251001",
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                    "content": [{"type": "text", "text": text}]},
    }) + "\n", encoding="utf-8")
    return path


def _hook_errors(home_dir):
    path = Path(home_dir) / "state" / "hook-errors.log"
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()]


def _assert_report_survived(out: str, report: str, surrogate: str):
    assert HEAD in out, "the head of the report was lost"
    assert TAIL in out, ("the tail of the report was lost -- the record was "
                         "truncated at the offending character, not sanitised")
    assert LEGIT_UNICODE in out, ("legitimate non-ASCII was destroyed; the fix "
                                  "must sanitise the unencodable character, not "
                                  "flatten the report to ASCII")
    assert surrogate not in out, "the lone surrogate reached the reader unsanitised"
    # -1, not ==: a one-character replacement keeps the length exactly, an
    # escaping replacement makes it longer; only truncation makes it shorter.
    assert len(out.strip()) >= len(report.strip()) - 1, (
        f"result shrank from {len(report.strip())} to {len(out.strip())} chars")


class TestOutcomeSurvivesALoneSurrogate:
    """Defect 1: the outcome record must be WRITTEN, sanitised, when the
    result text carries a character that cannot be encoded to utf-8."""

    @pytest.mark.parametrize("surrogate", LONE_SURROGATES)
    def test_result_is_readable_back_through_fleet_result(self, home, capsys, surrogate):
        report = _report(surrogate)
        proc = _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "last_assistant_message": report,
        })
        assert proc.returncode == 0, proc.stderr

        from types import SimpleNamespace
        rc = fleet.cmd_result(SimpleNamespace(name="w1"))
        captured = capsys.readouterr()
        assert rc == 0, (f"fleet result could not read the outcome back: "
                         f"{captured.err.strip()!r}")
        _assert_report_survived(captured.out, report, surrogate)

    @pytest.mark.parametrize("surrogate", LONE_SURROGATES)
    def test_transcript_fallback_route_also_survives(self, home, capsys, surrogate):
        """`result_text` has two producers. The transcript tail is the one that
        runs whenever the harness omits `last_assistant_message` -- a fix wired
        only into the payload branch leaves this half of the path still lossy."""
        report = _report(surrogate)
        transcript = _make_transcript(home, report)
        proc = _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "transcript_path": str(transcript),
        })
        assert proc.returncode == 0, proc.stderr

        from types import SimpleNamespace
        rc = fleet.cmd_result(SimpleNamespace(name="w1"))
        captured = capsys.readouterr()
        assert rc == 0, (f"fleet result could not read the outcome back: "
                         f"{captured.err.strip()!r}")
        _assert_report_survived(captured.out, report, surrogate)

    def test_nothing_is_swallowed_when_the_record_writes(self, home):
        """The fix is a WRITE that succeeds, not an error logged more loudly.
        A repair that still raises and merely reports better leaves this line
        in hook-errors.log -- and, per the doctor half of this incident, that
        is now a FAIL rather than the [PASS] it used to read."""
        proc = _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "last_assistant_message": _report("\udc90"),
        })
        assert proc.returncode == 0
        assert _hook_errors(home) == [], (
            "the outcome path still raised; the record was rescued by the "
            "reporter, not written cleanly")

    def test_a_surrogate_in_a_NON_result_field_is_survivable(self, home, capsys):
        """`result_text` is not the only payload-sourced field that lands in the
        JSON line -- `transcript_path`, `model` and `session_id` do too, and the
        encode that raised is applied to the WHOLE line. This case carries a
        perfectly clean report and puts the bad character only in
        `transcript_path`, so a fix scoped to `result_text` alone leaves it RED
        while every other test in this class goes green."""
        report = _report("")  # no surrogate anywhere in the report itself
        assert not any(0xD800 <= ord(c) <= 0xDFFF for c in report)
        proc = _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "last_assistant_message": report,
            "transcript_path": "C:/nope/t\udc90.jsonl",
        })
        assert proc.returncode == 0, proc.stderr

        from types import SimpleNamespace
        rc = fleet.cmd_result(SimpleNamespace(name="w1"))
        captured = capsys.readouterr()
        assert rc == 0, (f"the record was lost to a bad character in a field "
                         f"that is not the result: {captured.err.strip()!r}")
        assert HEAD in captured.out and TAIL in captured.out
        assert LEGIT_UNICODE in captured.out

    def test_all_four_surrogates_of_the_real_incident_survive_one_pass(self, home, capsys):
        """The gate-hf-rb report carried FOUR lone surrogates (result_text
        offsets 6817/6931/7012/7020), not the one the incident write-up
        described. A repair that reacts to `UnicodeEncodeError.start` and
        patches a single character would clear the first and raise on the
        second; the sanitisation has to be one whole-string pass."""
        report = (f"{HEAD}\n"
                  + "".join(f"| **`main \u00e2\u2020\udc90 sha{i}`** | ok |\n"
                            for i in range(4))
                  + f"Locale note: {LEGIT_UNICODE}\n{TAIL}\n")
        assert sum(1 for c in report if 0xD800 <= ord(c) <= 0xDFFF) == 4
        proc = _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "last_assistant_message": report,
        })
        assert proc.returncode == 0, proc.stderr

        from types import SimpleNamespace
        rc = fleet.cmd_result(SimpleNamespace(name="w1"))
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        _assert_report_survived(captured.out, report, "\udc90")
        # every one of the four rows is still there, not just the first
        for i in range(4):
            assert f"sha{i}" in captured.out

    def test_the_outcome_file_is_valid_utf8_on_disk(self, home):
        """`read_outcomes` opens the JSONL with a strict utf-8 decode. A record
        written as surrogate-escaped bytes would satisfy "a file exists" and
        still be unreadable by every reader fleet has."""
        _run_stop_outcome(home, {
            "session_id": SID, "hook_event_name": "Stop",
            "last_assistant_message": _report("\udc90"),
        })
        raw = (home / "state" / "outcomes" / "w1.jsonl").read_bytes()
        raw.decode("utf-8")  # strict: raises if the writer emitted CESU-8/WTF-8
        rec = json.loads(raw.decode("utf-8").strip())
        assert rec["kind"] == "result"
        assert isinstance(rec["result_text"], str)


class TestSiblingHooksSurviveTheSameClass:
    """Defect 1, constraint 4: the same codec seam exists in the other hooks
    under bin/hooks/. A guard written against the case we noticed does not
    cover the case we did not."""

    def test_postcompact_landmark_survives_an_unencodable_trigger(self, home):
        """`trigger` is payload-sourced and interpolated straight into the
        journal line, which is written with a strict utf-8 encode."""
        script = REPO_ROOT / "bin" / "hooks" / "postcompact_journal.py"
        env = dict(os.environ)
        env["FLEET_HOME"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps({"session_id": SID, "hook_event_name": "PostCompact",
                              "trigger": "auto\udc90"}),
            capture_output=True, text=True, env=env, timeout=30)
        assert proc.returncode == 0
        journal = home / "state" / "journals" / "w1.md"
        assert journal.exists(), "the compaction landmark was lost entirely"
        assert "[compact]" in journal.read_text(encoding="utf-8")
        assert _hook_errors(home) == []

    def test_postcompact_landmark_survives_an_undecodable_transcript(self, home):
        """`_transcript_stats` opened the transcript with a strict utf-8 decode
        and caught only OSError, so a UnicodeDecodeError escaped `main()` and
        took the whole landmark with it -- the stats are best-effort, the
        landmark is not."""
        script = REPO_ROOT / "bin" / "hooks" / "postcompact_journal.py"
        tdir = home / "transcripts"
        tdir.mkdir(parents=True, exist_ok=True)
        bad = tdir / "bad.jsonl"
        bad.write_bytes(b'{"type": "assistant", "x": "\xff\xfe"}\n')
        env = dict(os.environ)
        env["FLEET_HOME"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps({"session_id": SID, "hook_event_name": "PostCompact",
                              "trigger": "auto", "transcript_path": str(bad)}),
            capture_output=True, text=True, env=env, timeout=30)
        assert proc.returncode == 0
        journal = home / "state" / "journals" / "w1.md"
        assert journal.exists(), "the compaction landmark was lost entirely"
        assert _hook_errors(home) == []

    def test_stop_drain_survives_an_undecodable_transcript(self, home):
        """`_current_tokens` is reached only when a token ceiling is in force.
        It opened the transcript with a strict decode and caught only OSError,
        so a UnicodeDecodeError escaped main() and skipped the ENTIRE drain --
        pending mail left undelivered by a failure in a best-effort count."""
        script = REPO_ROOT / "bin" / "hooks" / "stop_mailbox.py"
        cdir = home / "state" / "ceilings"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / SID).write_text("999999", encoding="utf-8")   # ceiling in force
        tdir = home / "transcripts"
        tdir.mkdir(parents=True, exist_ok=True)
        bad = tdir / "bad.jsonl"
        bad.write_bytes(b'{"message": {"usage": {"input_tokens": 5}}, "x": "\xff\xfe"}\n')
        (home / "mailbox" / f"{SID}.md").write_text(
            "<MANAGER MESSAGE>\nstand down now\n", encoding="utf-8")

        env = dict(os.environ)
        env["FLEET_HOME"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps({"session_id": SID, "hook_event_name": "Stop",
                              "transcript_path": str(bad)}),
            capture_output=True, text=True, env=env, timeout=30)
        assert proc.returncode == 0
        assert proc.stdout.strip(), "the drain was skipped; mail was not delivered"
        assert "stand down now" in json.loads(proc.stdout)["reason"]
        assert _hook_errors(home) == []

    @pytest.mark.parametrize("script_name", ["stop_mailbox.py", "posttooluse_mailbox.py"])
    def test_mailbox_delivery_survives_an_undecodable_mailbox(self, home, script_name):
        """`_claim` RENAMES the mailbox and `_read_and_discard`'s finally block
        DELETES it -- so a decode failure between those two points destroys the
        manager's message instead of deferring it. Same class as the outcome
        loss: an irreversible step already happened when the codec raised."""
        script = REPO_ROOT / "bin" / "hooks" / script_name
        mailbox = home / "mailbox" / f"{SID}.md"
        mailbox.write_bytes("<MANAGER MESSAGE>\nstand down \u2014 ".encode("utf-8")
                            + b"\xff\xfe" + " now\n".encode("utf-8"))
        env = dict(os.environ)
        env["FLEET_HOME"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps({"session_id": SID, "hook_event_name": "Stop"}),
            capture_output=True, text=True, env=env, timeout=30)
        assert proc.returncode == 0
        assert proc.stdout.strip(), (
            "the message was claimed, deleted, and never delivered")
        payload = json.loads(proc.stdout)
        blob = json.dumps(payload)
        assert "stand down" in blob and "now" in blob, (
            "the message was delivered truncated at the bad byte")
        assert _hook_errors(home) == []
