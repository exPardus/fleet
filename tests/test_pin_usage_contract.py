"""THE DETERMINISTIC GATE for the pin tier's usage assertion (operator ruling A,
2026-08-05 -- WITHHOLD).

A live run of `tests/integration/test_native_pin.py` cannot serve as acceptance
evidence for a change to its step 2, because that step is FLAKY, NOT RED. The w41
probe ran the whole unmodified tier at claude 2.1.222 (6 passed in 57.03s) and
sampled `test_2`'s record four times with the assertion subject intact: 3
published, 1 nulled. A 6/6 after a fix is roughly 75% likely on unfixed code, and
wave 40-retry's two RED runs -- written up as "this is not a flake and I did not
stop at one sample" -- are two samples of a coin landing the same way.

So the contract is proved HERE instead, with no `claude` involved and nothing
hand-waved standing in for the thing under test:

  * The records fed to the predicate are produced by the REAL
    `bin/hooks/stop_outcome.py`, run as a REAL subprocess with UTF-8 bytes on
    stdin, exactly as Claude Code invokes it -- the same discipline
    `tests/test_outcome_usage_provenance.py` uses, and for the same reason.
  * The fixtures reproduce the RACE, not just its output: the withheld shape
    writes a transcript that stops one message short, runs the hook against
    THAT, and only then lets the harness catch up. That ordering is the whole
    mechanism, and a fixture that skips it would never notice that the settled
    file is what the pin actually reads.
  * Every mutant is then shown to be REJECTED, including the ones a
    counter-tolerant assertion would have reported as a healthy withhold.

The predicate itself lives in `tests/pin_usage_contract.py` and the live tier
calls THAT function, not a copy -- pinned by
`test_the_live_pin_tier_calls_this_contract_and_not_the_pre_ruling_assertion`
below, so the gate cannot drift away from the thing it certifies.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pin_usage_contract import (  # noqa: E402
    PUBLISHED, RESULT_TEXT_MAX, USAGE_FIELDS, WITHHELD, PinUsageContractError,
    check_outcome_usage_contract, turn_usage,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STOP_OUTCOME = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"
LIVE_PIN = REPO_ROOT / "tests" / "integration" / "test_native_pin.py"

SID = "sid-pin-contract-1"
FINAL_TEXT = "PIN-OK"
STALE_TEXT = "An earlier message, mid-turn."


def _assistant(msg_id, text, out_tokens, in_tokens=101, usage=True):
    msg = {"id": msg_id, "model": "claude-haiku-4-5-20251001",
           "content": [{"type": "text", "text": text}]}
    if usage:
        msg["usage"] = {"input_tokens": in_tokens, "output_tokens": out_tokens,
                        "cache_creation_input_tokens": 4000,
                        "cache_read_input_tokens": 9000}
    return {"type": "assistant", "message": msg}


def _write_transcript(home, records):
    path = home / "transcript.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in records), encoding="utf-8")
    return path


def _run_hook(home, transcript, last_assistant_message):
    """Fire the REAL hook as a subprocess with UTF-8 BYTES on stdin (bytes, not
    text=True: text=True encodes with the process locale, which is the very
    corruption `_read_stdin_payload` exists to stop)."""
    payload = {"session_id": SID, "hook_event_name": "Stop",
               "transcript_path": str(transcript),
               "last_assistant_message": last_assistant_message}
    r = subprocess.run([sys.executable, str(STOP_OUTCOME)],
                       input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, env={**os.environ, "FLEET_HOME": str(home)},
                       timeout=30)
    assert r.returncode == 0, (r.stdout, r.stderr)


def _sole_record(home):
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


# --------------------------------------------------------------------------
# The two ratified shapes, reproduced as SEQUENCES rather than as end states.
# --------------------------------------------------------------------------
def _withheld_record(home, text=FINAL_TEXT, settles_to=None):
    """THE RACE, in order: the harness has written only the previous message, the
    hook fires and reads THAT, and only afterwards does the harness append the
    message the turn ended on. `settles_to` overrides what it appends -- that is
    where the mutants go, because the settled file is what the pin reads."""
    transcript = _write_transcript(home, [_assistant("msg_earlier", STALE_TEXT, 234)])
    _run_hook(home, transcript, text)
    rec = _sole_record(home)
    if settles_to != "never":
        final = (settles_to if settles_to is not None
                 else _assistant("msg_final", text, out_tokens=15067, in_tokens=2))
        _write_transcript(home, [_assistant("msg_earlier", STALE_TEXT, 234), final])
    return rec


def _published_record(home, text=FINAL_TEXT):
    """The hook won the race: the final message is already on disk when it reads,
    its text matches the payload, and its numbers are published."""
    transcript = _write_transcript(home, [
        _assistant("msg_earlier", STALE_TEXT, 234),
        _assistant("msg_final", text, out_tokens=15067, in_tokens=2)])
    _run_hook(home, transcript, text)
    return _sole_record(home)


class TestTheRealHookProducesRecordsThisContractAccepts:
    """Acceptance: both ratified shapes, produced end-to-end by the real hook."""

    def test_the_race_shape_is_accepted_as_withheld(self, home):
        rec = _withheld_record(home)
        # The shape ruling A ratifies: report present, all four counters None.
        assert rec["result_text"] == FINAL_TEXT
        assert [rec[f] for f in USAGE_FIELDS] == [None, None, None, None]
        assert check_outcome_usage_contract(rec) == WITHHELD

    def test_the_complete_shape_is_accepted_as_published(self, home):
        rec = _published_record(home)
        assert rec["output_tokens"] == 15067 and rec["input_tokens"] == 2
        assert check_outcome_usage_contract(rec) == PUBLISHED

    def test_the_pre_ruling_assertion_rejects_the_record_the_ruling_ratifies(
            self, home):
        """THE DEFECT, stated as a test. `tests/integration/test_native_pin.py`
        asserted that both counters were not None. On the race shape --
        ratified-correct behaviour -- both ARE None, so the old assertion failed
        on code the operator has ruled is right, which is how this tier went RED
        twice in wave 40-retry. It also stops the opposite regression: if the
        hook ever went back to publishing the stale 234 here, the first assert
        below fails."""
        rec = _withheld_record(home)
        assert rec["input_tokens"] is None and rec["output_tokens"] is None
        assert check_outcome_usage_contract(rec) == WITHHELD

    def test_a_report_longer_than_the_truncation_cap_is_still_located(self, home):
        """The stored report is capped at RESULT_TEXT_MAX, so the transcript text
        must be truncated the same way before the lookup -- otherwise every
        report over the cap fails to find its own message, and those are exactly
        the turns whose token count anyone cares about."""
        long_text = "x" * (RESULT_TEXT_MAX + 5000)
        rec = _withheld_record(home, text=long_text)
        assert len(rec["result_text"]) == RESULT_TEXT_MAX
        assert check_outcome_usage_contract(rec) == WITHHELD


class TestTheContractRejectsTheDriftARulingATolerantPinWouldSwallow:
    """The mutants. Each is a shape that a "just tolerate None" repair reports as
    a healthy withhold. Every one must FAIL."""

    def test_a_turn_whose_own_message_carries_no_usage_is_rejected(self, home):
        """THE MUTANT THAT MATTERS. Vendor drift: `message.usage` is gone. The
        hook then behaves EXACTLY as it does in the ratified withheld case --
        model present, four counters None -- so a model-only or tolerance-only
        predicate stays green through the precise failure the pin tier exists to
        catch."""
        rec = _withheld_record(home, settles_to=_assistant(
            "msg_final", FINAL_TEXT, out_tokens=15067, usage=False))
        assert rec["model"] and rec["output_tokens"] is None  # indistinguishable
        with pytest.raises(PinUsageContractError, match="carries no"):
            check_outcome_usage_contract(rec)

    def test_a_turn_whose_message_never_reaches_the_transcript_is_rejected(self, home):
        """The other half of the same failure: the settled file never gains the
        message the record describes. Withholding is only ratified when the
        numbers exist and the hook merely could not prove it saw them."""
        rec = _withheld_record(home, settles_to="never")
        with pytest.raises(PinUsageContractError, match="has this record's text"):
            check_outcome_usage_contract(rec)

    def test_a_usage_block_whose_output_tokens_stopped_being_an_int_is_rejected(
            self, home):
        rec = _withheld_record(home)
        t = Path(rec["transcript_path"])
        t.write_text(t.read_text(encoding="utf-8").replace(
            '"output_tokens": 15067', '"output_tokens": "15067"'), encoding="utf-8")
        with pytest.raises(PinUsageContractError, match="NO INTEGER"):
            check_outcome_usage_contract(rec)

    def test_no_assistant_record_at_all_is_rejected(self, home):
        """`model` absent is the genuine-failure case the ruling names: the parse
        found no assistant record, so there was never anything to withhold."""
        transcript = _write_transcript(home, [{"type": "user",
                                               "message": {"content": "hello"}}])
        _run_hook(home, transcript, FINAL_TEXT)
        rec = _sole_record(home)
        assert rec["model"] is None
        with pytest.raises(PinUsageContractError, match="NO MODEL"):
            check_outcome_usage_contract(rec)

    def test_a_published_counter_that_disagrees_with_the_turn_is_rejected(self, home):
        """The stale-counter defect (95/130 records on 2026-07-30) returning
        through the PUBLISH branch. The record claims 15067; the turn's own
        message says 999. Publication asserts the hook saw the end of the turn,
        so its numbers must be that message's numbers."""
        rec = _published_record(home)
        _write_transcript(home, [_assistant("msg_final", FINAL_TEXT,
                                            out_tokens=999, in_tokens=2)])
        with pytest.raises(PinUsageContractError, match="DISAGREE"):
            check_outcome_usage_contract(rec)

    @pytest.mark.parametrize("field", USAGE_FIELDS)
    def test_a_published_counter_that_disagrees_in_any_single_field_is_rejected(
            self, home, field):
        """Parameterised over all four so the equality cannot be satisfied by
        checking only the pair the old assertion happened to name."""
        rec = _published_record(home)
        with pytest.raises(PinUsageContractError, match="DISAGREE"):
            check_outcome_usage_contract(dict(rec, **{field: 4242}))

    def test_a_transcript_that_has_gone_away_is_rejected_not_tolerated(self, home):
        rec = _withheld_record(home)
        Path(rec["transcript_path"]).unlink()
        with pytest.raises(PinUsageContractError, match="could not be read"):
            check_outcome_usage_contract(rec)

    def test_a_record_with_no_transcript_path_is_rejected(self, home):
        rec = _withheld_record(home)
        for empty in (None, "", "   "):
            with pytest.raises(PinUsageContractError, match="NO TRANSCRIPT PATH"):
                check_outcome_usage_contract(dict(rec, transcript_path=empty))

    def test_a_record_with_no_result_text_is_rejected(self, home):
        """`result_text` is the key the turn's message is located by. A record
        without one cannot be tied to a message, so its counters cannot be
        judged -- and silently passing it would reopen the tolerance hole."""
        rec = _withheld_record(home)
        for empty in (None, "", 7):
            with pytest.raises(PinUsageContractError, match="NO RESULT TEXT"):
                check_outcome_usage_contract(dict(rec, result_text=empty))

    @pytest.mark.parametrize("bad_model", [None, "", "   ", 7, ["haiku"]])
    def test_a_record_with_no_usable_model_is_rejected(self, home, bad_model):
        rec = _withheld_record(home)
        with pytest.raises(PinUsageContractError, match="NO MODEL"):
            check_outcome_usage_contract(dict(rec, model=bad_model))

    @pytest.mark.parametrize("field", USAGE_FIELDS)
    def test_a_withheld_record_with_one_counter_still_set_is_rejected(
            self, home, field):
        """`stop_outcome.py:326` nulls all four in ONE chained assignment, so a
        partially-nulled record was written by something else."""
        rec = _withheld_record(home)
        mutant = dict(rec, **{field: 1234})
        if field == "output_tokens":
            # output_tokens set alone lands in the PUBLISH branch instead, where
            # it fails on the other half of the same invariant.
            with pytest.raises(PinUsageContractError, match="PARTIALLY-PUBLISHED"):
                check_outcome_usage_contract(mutant)
        else:
            with pytest.raises(PinUsageContractError, match="PARTIALLY-NULLED"):
                check_outcome_usage_contract(mutant)

    def test_a_published_record_missing_its_input_counter_is_rejected(self, home):
        rec = _published_record(home)
        with pytest.raises(PinUsageContractError, match="PARTIALLY-PUBLISHED"):
            check_outcome_usage_contract(dict(rec, input_tokens=None))

    @pytest.mark.parametrize("field", USAGE_FIELDS)
    def test_usage_fields_are_rejected_when_they_stop_being_ints(self, home, field):
        """`True` is in this list on purpose: `isinstance(True, int)` is True in
        Python, so a JSON `true` in a counter passes every naive numeric check."""
        rec = _published_record(home)
        for bad in ("15067", 1.5, True, -1, {"n": 1}):
            with pytest.raises(PinUsageContractError, match="NEITHER None NOR"):
                check_outcome_usage_contract(dict(rec, **{field: bad}))

    def test_a_published_output_count_of_zero_is_rejected(self, home):
        """A message the operator can read cost more than zero output tokens.
        Rejected explicitly rather than left to the equality check, so a source
        that starts emitting 0 for every message is a failure and not a match."""
        rec = _published_record(home)
        _write_transcript(home, [_assistant("msg_final", FINAL_TEXT,
                                            out_tokens=0, in_tokens=2)])
        with pytest.raises(PinUsageContractError, match="IS 0"):
            check_outcome_usage_contract(dict(rec, output_tokens=0))

    @pytest.mark.parametrize("dropped", USAGE_FIELDS + ("model", "transcript_path",
                                                        "result_text"))
    def test_dropping_a_required_key_entirely_is_rejected(self, home, dropped):
        """Presence, not truthiness: withholding sets the counters to None, it
        never removes them. An absent key is a schema change and must not read as
        a withheld counter."""
        rec = _withheld_record(home)
        mutant = {k: v for k, v in rec.items() if k != dropped}
        with pytest.raises(PinUsageContractError, match="SCHEMA DRIFT"):
            check_outcome_usage_contract(mutant)

    def test_a_non_dict_record_is_rejected(self):
        for bad in (None, [], "rec", 7):
            with pytest.raises(PinUsageContractError, match="not a dict"):
                check_outcome_usage_contract(bad)

    def test_every_violation_is_an_assertion_error(self, home):
        """So a contract breach is reported as a test FAILURE, not an ERROR,
        wherever the predicate is called from."""
        assert issubclass(PinUsageContractError, AssertionError)
        rec = _withheld_record(home)
        with pytest.raises(AssertionError):
            check_outcome_usage_contract(dict(rec, model=None))

    def test_a_failure_message_does_not_paste_a_whole_report(self, home):
        """The diagnostic embeds the record, and a real `result_text` is up to
        20,000 characters. A pin whose failure output is a wall of report is a
        pin whose failure nobody reads."""
        rec = _withheld_record(home, text="y" * (RESULT_TEXT_MAX + 100))
        with pytest.raises(PinUsageContractError) as exc:
            check_outcome_usage_contract(dict(rec, model=None))
        assert len(str(exc.value)) < 2000, len(str(exc.value))


class TestTheTurnScopedReader:
    """The reader is the discriminator's only input. Its own behaviour is pinned
    so a reader that silently returns None for everything -- which would turn
    every branch above into a uniform failure and every green run into a
    coincidence -- cannot pass."""

    def test_it_reads_THIS_turns_usage_and_not_the_tail_of_the_file(self, home):
        """THE REGRESSION THIS READER EXISTS FOR, and it was found on real data,
        not reasoned about. A transcript is per-SESSION and accumulates across
        TURNS, so its tail belongs to whatever turn happened LAST -- 38 of 45
        pre-gate records in the real store whose text matched the file's tail
        still disagreed on usage, `cache_read_input_tokens` monotonically higher
        in the file than in the record: the signature of a later turn, not of a
        stale counter. Reading the tail would make the published branch fail on
        any session that went on to do more work."""
        path = _write_transcript(home, [
            _assistant("msg_this_turn", FINAL_TEXT, out_tokens=15067, in_tokens=2),
            _assistant("msg_next_turn", "a later turn's report", out_tokens=99999),
        ])
        usage, note = turn_usage(path, FINAL_TEXT)
        assert usage["output_tokens"] == 15067, "read the file tail, not the turn"
        assert "2 message(s)" in note

    def test_it_groups_the_records_of_one_message(self, home):
        """One message is written as several records sharing a `message.id` and a
        `message.usage`; the text block is not necessarily the last of them."""
        path = _write_transcript(home, [
            {"type": "assistant", "message": {
                "id": "msg_final", "model": "m",
                "usage": {"input_tokens": 2, "output_tokens": 15067},
                "content": [{"type": "thinking"}]}},
            _assistant("msg_final", FINAL_TEXT, out_tokens=15067, in_tokens=2),
        ])
        usage, _ = turn_usage(path, FINAL_TEXT)
        assert usage["output_tokens"] == 15067

    def test_it_takes_the_last_message_when_two_carry_the_same_text(self, home):
        """A worker can repeat itself verbatim across turns. The turn that ended
        LAST is the one the record describes."""
        path = _write_transcript(home, [
            _assistant("msg_first", FINAL_TEXT, out_tokens=111),
            _assistant("msg_again", FINAL_TEXT, out_tokens=222),
        ])
        usage, _ = turn_usage(path, FINAL_TEXT)
        assert usage["output_tokens"] == 222

    def test_it_skips_records_that_are_not_assistant_messages(self, home):
        path = _write_transcript(home, [
            {"type": "user", "message": {"content": "hi"}},
            _assistant("msg_final", FINAL_TEXT, out_tokens=15067),
            {"type": "system", "message": {"usage": {"output_tokens": 1}}},
        ])
        usage, _ = turn_usage(path, FINAL_TEXT)
        assert usage["output_tokens"] == 15067

    def test_a_torn_final_line_does_not_lose_the_turn(self, home):
        path = _write_transcript(home, [_assistant("msg_final", FINAL_TEXT,
                                                   out_tokens=15067)])
        with path.open("a", encoding="utf-8") as f:
            f.write('{"type": "assistant", "message": {"id": "msg_torn"')
        usage, _ = turn_usage(path, FINAL_TEXT)
        assert usage["output_tokens"] == 15067

    def test_a_missing_file_reports_rather_than_raises(self, tmp_path):
        usage, note = turn_usage(tmp_path / "nope.jsonl", FINAL_TEXT)
        assert usage is None and "could not be read" in note

    def test_a_none_path_reports_rather_than_raises(self):
        usage, note = turn_usage(None, FINAL_TEXT)
        assert usage is None and "could not be read" in note

    def test_a_none_result_text_reports_rather_than_raises(self, home):
        path = _write_transcript(home, [_assistant("m", FINAL_TEXT, out_tokens=1)])
        usage, note = turn_usage(path, None)
        assert usage is None and "no text to key the lookup by" in note

    def test_the_truncation_cap_matches_the_hooks_own_constant(self):
        """The lookup truncates the transcript text to RESULT_TEXT_MAX because
        the hook truncated the stored report to it. If the hook's cap ever moves
        and this copy does not, every report between the two values silently
        stops matching its own message."""
        src = STOP_OUTCOME.read_text(encoding="utf-8")
        m = re.search(r"^RESULT_TEXT_MAX\s*=\s*(\d+)\s*$", src, re.M)
        assert m, "RESULT_TEXT_MAX is no longer a module-level literal in the hook"
        assert int(m.group(1)) == RESULT_TEXT_MAX, (
            f"the hook truncates at {m.group(1)} but this contract truncates at "
            f"{RESULT_TEXT_MAX}")


def test_the_live_pin_tier_calls_this_contract_and_not_the_pre_ruling_assertion():
    """The gate certifies the predicate; this is what ties the predicate to the
    tier. Without it the live pin could quietly keep its own copy -- or its old
    assertion -- and every test above would still pass while proving nothing
    about the thing that runs at 2.1.222."""
    src = LIVE_PIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    step2 = next((n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "test_2_pin_stop_hook_outcome"), None)
    assert step2 is not None, "test_2_pin_stop_hook_outcome vanished from the pin tier"
    called = {ast.unparse(n.func) for n in ast.walk(step2) if isinstance(n, ast.Call)}
    assert any("check_outcome_usage_contract" in c for c in called), (
        "the live pin's step 2 no longer calls check_outcome_usage_contract -- "
        f"calls found: {sorted(called)}")
    # AST, not text: step 2's comment QUOTES the pre-ruling assertion to record
    # why it went, and a substring lint would fire on the explanation as readily
    # as on the defect. Comments are not in the tree; a returned assertion is.
    # Written as a shape rather than two exact strings so the subscript form
    # (`rec["output_tokens"] is not None`) is caught by the same check.
    banned = sorted(c for c in
                    {ast.unparse(n) for n in ast.walk(step2)
                     if isinstance(n, ast.Compare)}
                    if "is not None" in c
                    and ("input_tokens" in c or "output_tokens" in c))
    assert not banned, (
        f"the pre-ruling assertion is back in the pin tier: {banned}. Ruling A "
        "(2026-08-05) makes 'the counter must be a number' wrong on any racing "
        "turn -- discriminate the withheld case instead.")
