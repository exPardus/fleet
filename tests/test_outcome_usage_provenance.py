"""The Stop hook must never publish token counts that belong to a different
assistant message than the one the turn ended on.

BACKGROUND (measured, `state/outcomes` on 2026-07-30). `bin/hooks/stop_outcome.py`
derives `input_tokens`/`output_tokens` by re-reading the transcript FILE, which
the harness is still appending to. Over the 130 live sessions whose final
outcome record could be compared against its own completed transcript, 95 (73%)
carried the SECOND-TO-LAST assistant message's usage and only 35 the final one.
Nothing in the record distinguished the two, so `fleet status`'s `out=` counter
rendered an arbitrary earlier message's output as this turn's -- wrong by an
unbounded, unpatterned factor (9.5x-89x across the four workers that were
spot-checked).

The payload's `last_assistant_message` is not subject to that race, so the hook
now uses it as an exact test of whether it saw the end of the turn, and
withholds the four token fields when it did not.

These tests drive the REAL hook as a REAL subprocess with UTF-8 bytes on stdin,
exactly as Claude Code invokes it. Every assertion is unconditional: there is no
`if <literal> in output:` wrapper that a later author could satisfy by deleting
the behaviour.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STOP_OUTCOME = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"

SID = "sid-prov-1"

# The exact production shape: ONE assistant message is written as SEVERAL
# transcript records sharing one `message.id` and one `message.usage`.
FINAL_TEXT = "The final report of this turn."
STALE_TEXT = "An earlier message, mid-turn."


def _run(home: Path, payload: dict) -> subprocess.CompletedProcess:
    """Fire the hook as a subprocess with UTF-8 BYTES on stdin.

    Bytes, not `text=True`: `text=True` encodes with the process locale
    (cp1252 here), which is the very corruption `_read_stdin_payload` exists to
    stop. Encoding explicitly is what the harness does.
    """
    env = dict(os.environ)
    env["FLEET_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(STOP_OUTCOME)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, env=env, timeout=30,
    )


def _assistant(msg_id, text, out_tokens, in_tokens=101, block="text"):
    content = ([{"type": "text", "text": text}] if block == "text"
               else [{"type": block}])
    return {"type": "assistant",
            "message": {"id": msg_id, "model": "claude-haiku-4-5-20251001",
                        "usage": {"input_tokens": in_tokens,
                                  "output_tokens": out_tokens,
                                  "cache_creation_input_tokens": 4000,
                                  "cache_read_input_tokens": 9000},
                        "content": content}}


def _transcript(home: Path, records) -> Path:
    path = home / "transcript.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in records), encoding="utf-8")
    return path


def _record(home: Path) -> dict:
    lines = [ln for ln in (home / "state" / "outcomes" / "w1.jsonl")
             .read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1, f"expected exactly one outcome record, got {lines}"
    return json.loads(lines[0])


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"w1": {"session_id": SID}}}), encoding="utf-8")
    return tmp_path


class TestOutcomeUsageProvenance:

    def test_the_production_race_shape_withholds_the_stale_counter(self, home):
        """THE REGRESSION. The transcript on disk stops one message short of
        the one the turn ended on -- the 73% case. The stale message's 234
        output tokens must NOT be published as this turn's."""
        t = _transcript(home, [
            _assistant("msg_earlier", STALE_TEXT, out_tokens=234),
        ])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        # The report itself still lands -- the payload is not racy.
        assert rec["result_text"] == FINAL_TEXT
        # ...but the numbers describing a DIFFERENT message must not.
        assert rec["output_tokens"] is None
        assert rec["input_tokens"] is None
        assert rec["cache_creation_input_tokens"] is None
        assert rec["cache_read_input_tokens"] is None
        # Named explicitly, so that publishing the stale value can never pass
        # by coincidence of `None` being absent from the record.
        assert rec["output_tokens"] != 234

    def test_a_complete_transcript_publishes_the_final_message_usage(self, home):
        """The other half: when the hook DID see the end of the turn, the
        numbers must be present and exact. Without this, deleting the counter
        outright would satisfy the test above."""
        t = _transcript(home, [
            _assistant("msg_earlier", STALE_TEXT, out_tokens=234),
            _assistant("msg_final", FINAL_TEXT, out_tokens=15067, in_tokens=2),
        ])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        assert rec["result_text"] == FINAL_TEXT
        assert rec["output_tokens"] == 15067
        assert rec["input_tokens"] == 2
        assert rec["cache_creation_input_tokens"] == 4000
        assert rec["cache_read_input_tokens"] == 9000

    def test_a_multi_record_message_is_read_as_one_message(self, home):
        """One message is written as several records (thinking, then tool_use,
        then text) sharing one `message.id` and one `message.usage`. Grouping
        must not mistake those for separate messages, or the final message's
        own text would be discarded and every turn would look stale."""
        t = _transcript(home, [
            _assistant("msg_earlier", STALE_TEXT, out_tokens=234),
            _assistant("msg_earlier", "", out_tokens=234, block="tool_use"),
            _assistant("msg_final", "", out_tokens=15067, block="thinking"),
            _assistant("msg_final", FINAL_TEXT, out_tokens=15067, in_tokens=2),
        ])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        assert rec["output_tokens"] == 15067
        assert rec["input_tokens"] == 2

    def test_text_and_usage_must_come_from_the_SAME_message(self, home):
        """The false-positive the `message.id` grouping exists to stop.

        Here the payload's last_assistant_message is message A's text, and the
        transcript continues past A into message B, which carries no text of
        its own and a different usage. Tracking `text` and the usage fields
        independently -- the old reader -- leaves A's text sitting beside B's
        numbers: the comparison in `main` then PASSES (the text does match the
        payload) and publishes 999, a number belonging to a message the
        operator never saw. The counter must be withheld instead: B is the last
        message in the file and nothing proves B is where the turn ended."""
        t = _transcript(home, [
            _assistant("msg_A", FINAL_TEXT, out_tokens=15067, in_tokens=2),
            _assistant("msg_B", "", out_tokens=999, in_tokens=888,
                       block="tool_use"),
        ])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        assert rec["output_tokens"] is None
        assert rec["input_tokens"] is None
        assert rec["output_tokens"] != 999
        assert rec["input_tokens"] != 888

    def test_a_turn_ending_on_a_textless_message_withholds_rather_than_guesses(
            self, home):
        """The transcript's final message carries no text at all (a turn cut
        short after a tool call). There is then no way to prove the file is
        complete, so the counter is withheld -- it is not silently taken from
        whichever earlier message happened to have text."""
        t = _transcript(home, [
            _assistant("msg_earlier", STALE_TEXT, out_tokens=234),
            _assistant("msg_final", "", out_tokens=999, block="tool_use"),
        ])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        assert rec["output_tokens"] is None
        assert rec["output_tokens"] != 234
        assert rec["output_tokens"] != 999

    def test_a_report_longer_than_the_truncation_cap_still_verifies(self, home):
        """The stored `result_text` is capped at RESULT_TEXT_MAX (20,000). The
        comparison must happen BEFORE that truncation, or every long report --
        exactly the reports whose token count anyone cares about -- would be
        misjudged stale and lose its counter for the wrong reason."""
        long_text = "x" * 25000
        t = _transcript(home, [_assistant("msg_final", long_text, out_tokens=15067)])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": long_text})
        rec = _record(home)
        assert len(rec["result_text"]) == 20000
        assert rec["output_tokens"] == 15067

    def test_the_payload_is_decoded_as_utf8_not_the_process_codepage(self, home):
        """`sys.stdin.read()` decoded with the locale (cp1252), so U+2014 EM
        DASH arrived as the three characters `â€”` and was stored that way.
        76 of the 124 comparable live records carried exactly this corruption.
        It mangles the operator's report AND it is what made the staleness
        comparison above impossible to do exactly."""
        text = "verified — 24,529 bytes, sha256 `9f70e3bd…` → ok, ≥ 1 ⚠"
        t = _transcript(home, [_assistant("msg_final", text, out_tokens=15067)])
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "transcript_path": str(t),
                    "last_assistant_message": text})
        rec = _record(home)
        assert rec["result_text"] == text
        assert "—" in rec["result_text"]
        # The signature of the double-decode, named so it cannot creep back.
        assert "â€”" not in rec["result_text"]
        # And because the text now round-trips exactly, the counter verifies.
        assert rec["output_tokens"] == 15067

    def test_no_transcript_at_all_is_still_a_record_with_no_counter(self, home):
        """Unchanged behaviour, pinned so the new guard cannot be read as the
        reason the fields are absent here."""
        _run(home, {"session_id": SID, "hook_event_name": "Stop",
                    "last_assistant_message": FINAL_TEXT})
        rec = _record(home)
        assert rec["kind"] == "result"
        assert rec["result_text"] == FINAL_TEXT
        assert rec["output_tokens"] is None


class TestConsumersToleratePublishedNone:
    """The two fleet-side readers of the field must already behave correctly
    when it is None -- that is what makes withholding safe without touching
    them. Pinned here so a later change to either one cannot quietly turn a
    withheld counter back into a rendered zero."""

    def test_status_summary_omits_the_counter_entirely(self, monkeypatch):
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import fleet

        monkeypatch.setattr(fleet, "latest_outcome", lambda name, sid: {
            "kind": "result", "input_tokens": None, "output_tokens": None})
        summary = fleet._native_token_summary("w1", {"session_id": SID})
        assert summary == ""
        assert "out=" not in summary

    def test_cumulative_ceiling_sum_skips_it_instead_of_counting_zero_wrong(
            self, monkeypatch):
        sys.path.insert(0, str(REPO_ROOT / "bin"))
        import fleet

        monkeypatch.setattr(fleet, "read_outcomes", lambda name: [
            {"kind": "result", "input_tokens": None, "output_tokens": None},
            {"kind": "result", "input_tokens": 10, "output_tokens": 5},
        ])
        assert fleet._native_cumulative_tokens("w1") == 15
