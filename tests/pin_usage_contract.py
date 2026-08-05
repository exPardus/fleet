"""The usage-provenance contract the live pin tier holds `bin/hooks/stop_outcome.py`
to, extracted so a DETERMINISTIC unit test can prove it and the live tier can
merely exercise it.

WHY THIS EXISTS (operator ruling A, 2026-08-05 -- WITHHOLD; today's behaviour
STANDS). The Stop hook publishes the four usage fields only when the payload's
`last_assistant_message` string-equals the text of the message the transcript's
usage came from (`bin/hooks/stop_outcome.py:324-326`). It reads the transcript
FILE while the harness is still appending to it, so on a long turn it usually
loses that race and all four fields are `None` -- correct, ratified behaviour.
`tests/integration/test_native_pin.py` used to assert

    assert rec.get("input_tokens") is not None, rec
    assert rec.get("output_tokens") is not None, rec

which is WRONG BY RULING on any racing turn. The naive repair -- delete those two
lines, or weaken them to "None is fine" -- is worse than the defect: it makes the
pin tier's step 2 unable to fail, and step 2 is the only thing standing between
fleet and a vendor that silently stops emitting usage at all.

WHY NOT "`model` IS PRESENT" ALONE. The w41 probe found `model` present on every
nulled record and read that as positive proof the parse reached the usage block.
It is weaker than that. `_transcript_result` resets `text` when `message.id`
changes but NEVER resets `model` (`stop_outcome.py:246-260`), so `model` is
sticky across the whole file: it proves *some* assistant record carried a
`model`, not that the message the turn ended on carried a `usage` dict. If a
vendor bump renamed or dropped `usage`, every record would arrive with `model`
present and all four counters `None` -- indistinguishable, to a model-only
predicate, from the ratified withheld case. The pin would stay green through
exactly the drift it exists to catch. `model` is still checked here (its absence
is a genuine failure: no assistant record was parsed at all), but it is not the
discriminator.

THE DISCRIMINATOR. The record names its own `transcript_path`. By the time the
pin reads the record, `fleet wait` has returned and the turn is over, so the
append race the hook lost has finished -- that file is a second, RACE-FREE
vantage on the same turn. Locate THE MESSAGE THE RECORD IS ABOUT in it, and the
two cases separate:

  * WITHHELD (ratified): all four fields `None`, and the turn's own message in
    the settled transcript DOES carry an integer `output_tokens`. The numbers
    existed; the hook could not prove it had seen the end of the turn and
    declined to publish them. Correct.
  * PUBLISHED: the four fields equal, exactly, that message's usage. The hook won
    the race AND published the right message's numbers.
  * ANYTHING ELSE is a failure, including the two shapes a tolerant assertion
    would have swallowed: the turn's own message carrying no usage at all (the
    counters are gone at the SOURCE, not lost to the race), and published
    counters that disagree with it (the stale-counter defect the withholding gate
    was built to cure, returning through the publish branch).

"THE MESSAGE THE RECORD IS ABOUT", NOT "THE LAST MESSAGE IN THE FILE. This
distinction was measured, not reasoned: the first version of this module read the
tail of the settled transcript, and the real store refuted it. A transcript is
per-SESSION and accumulates across TURNS, so days later its tail belongs to some
LATER turn -- 38 of 45 pre-gate records whose text matched the file's tail still
disagreed on usage, with `cache_read_input_tokens` monotonically higher in the
file than in the record, which is the signature of a later turn and not of a
stale counter. Keying the lookup by `result_text` (the last `message.id` group
whose text equals the stored report) is turn-scoped and immune to that.

MEASURED ON THE REAL STORE, 2026-08-05, read-only, 154 `kind=="result"` records
in `C:/proga/claude-fleet/state/outcomes` (THIS predicate, as written below, run
over every one of them):
  * POST-gate (ts >= 2026-07-30, n=10): 10 withheld, 0 rejected. The turn's own
    message was located in the settled transcript 10/10 times and carried an
    integer `output_tokens` 10/10 times. Zero false REDs on ratified data.
  * PRE-gate (n=144): 24 published, 120 rejected -- 67 "published counters
    disagree with this turn's own message" and 53 "message not locatable". The 67
    are this predicate independently reproducing the 2026-07-30 finding (95/130
    records carried the second-to-last message's usage) from a different
    direction, which is also the proof that it is not vacuous: it fails, in bulk,
    on real records that are genuinely wrong.
  * The lookup's ONLY observed failure mode is those 53, and 53/53 of them carry
    the `â€`/`Â` signature of the cp1252 double-decode that
    `_read_stdin_payload` fixed in the same change as the gate. Zero post-gate.
    Zero from truncation. Zero from any other cause.
  * NOT MEASURED: a post-gate PUBLISHED record. There are none in the store --
    every post-gate turn is a long fleet report and loses the race. The publish
    branch's equality is therefore argued (publication means the hook's text
    matched the message its usage came from, so its numbers ARE that message's
    numbers) and proved on synthetic-but-real-hook records in the gate test, not
    observed in the wild.

Proved deterministically in `tests/test_pin_usage_contract.py`, which drives the
REAL hook as a REAL subprocess and feeds its real output back through this
predicate -- a live tier run is supporting evidence, never the proof, because
that tier is FLAKY not RED (probe at claude 2.1.222: 3 published / 1 withheld
over four samples of the same unmodified code; pin turns are trivial enough that
the hook usually wins a race it nearly always loses on a real turn).
"""
import json
from pathlib import Path

# Mirrors `bin/hooks/stop_outcome.py`'s RESULT_TEXT_MAX. The stored report is
# truncated at this length, so the transcript text is truncated the same way
# before comparison -- otherwise every report over the cap would fail to locate
# its own message, which is precisely the class of turn whose token count anyone
# cares about. Pinned against the hook's own constant in the gate test.
RESULT_TEXT_MAX = 20000

# The four fields the gate nulls TOGETHER (`stop_outcome.py:326` is a single
# chained assignment). Publication is therefore all-or-nothing, and a
# partially-nulled record means something other than that gate wrote it.
USAGE_FIELDS = ("input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens")

# Keys the outcome record must CARRY, present-but-None included. Checked by
# presence rather than truthiness so a schema that drops the counters entirely is
# a loud failure and not a silent "withheld".
REQUIRED_KEYS = USAGE_FIELDS + ("model", "transcript_path", "result_text")

WITHHELD = "withheld"
PUBLISHED = "published"


class PinUsageContractError(AssertionError):
    """AssertionError subclass: a violation is a test FAILURE, not an ERROR,
    wherever this predicate is called from."""


def _is_count(value):
    """A token count is a non-negative int. `bool` is excluded explicitly --
    `isinstance(True, int)` is True in Python, so a JSON `true` that leaked into
    a counter would otherwise sail through every numeric check here."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _assistant_groups(raw):
    """[(message_id, joined_text_or_None, usage_or_None)] in file order.

    ONE assistant message is written as SEVERAL transcript records -- one per
    content block -- sharing a `message.id` and a `message.usage`, so grouping is
    what makes "the message the turn ended on" a well-defined thing to look for.
    A `None` id is treated as always-new, the same conservative reading the hook
    takes. Unparseable lines are skipped rather than fatal: a transcript's final
    line can be torn if the file is read mid-write."""
    groups = []
    cur = _NO = object()
    text = usage = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        msg_id = msg.get("id")
        if cur is _NO or msg_id is None or msg_id != cur:
            if cur is not _NO:
                groups.append((cur, text, usage))
            cur, text, usage = msg_id, None, None
        parts = [c.get("text") for c in msg.get("content") or []
                 if isinstance(c, dict) and c.get("type") == "text" and c.get("text")]
        if parts:
            text = "\n".join(parts)
        candidate = msg.get("usage")
        if isinstance(candidate, dict):
            usage = candidate
    if cur is not _NO:
        groups.append((cur, text, usage))
    return groups


def turn_usage(transcript_path, result_text):
    """`(usage_dict_or_None, note)` for THE TURN THIS RECORD DESCRIBES: the usage
    of the last `message.id` group in the SETTLED transcript whose text equals
    `result_text`.

    `usage` is None both when the message cannot be found and when it is found
    carrying no usage dict; `note` distinguishes them, and both are failures --
    the caller does not get to treat "not found" as benign."""
    try:
        raw = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError, TypeError) as exc:
        return None, f"settled transcript could not be read: {exc!r}"
    if not isinstance(result_text, str):
        return None, f"record has no text to key the lookup by: {result_text!r}"
    groups = _assistant_groups(raw)
    hit = _MISS = object()
    for _msg_id, text, usage in groups:
        if isinstance(text, str) and text[:RESULT_TEXT_MAX] == result_text:
            hit = usage
    if hit is _MISS:
        return None, (
            f"no assistant message in the settled transcript has this record's "
            f"text ({len(groups)} message(s) in the file). The turn's own record "
            f"is missing, or the stored text no longer round-trips -- the only "
            f"cause ever observed for the latter is the cp1252 double-decode "
            f"fixed on 2026-07-30 (53/53 of the historical misses carry its "
            f"`\u00e2\u20ac` signature; zero misses since)")
    if hit is None:
        return None, (
            f"the turn's own message was located in the settled transcript but "
            f"carries no `message.usage` dict ({len(groups)} message(s) in the "
            f"file)")
    return hit, f"{len(groups)} message(s) in the settled transcript"


def _fail(headline, rec, detail=""):
    trimmed = dict(rec) if isinstance(rec, dict) else rec
    if isinstance(trimmed, dict) and isinstance(trimmed.get("result_text"), str):
        trimmed["result_text"] = trimmed["result_text"][:200]
    raise PinUsageContractError(
        f"{headline}\n"
        f"  outcome record: {trimmed!r}\n"
        + (f"  {detail}\n" if detail else "")
        + "  contract: tests/pin_usage_contract.py (operator ruling A, 2026-08-05)"
    )


def check_outcome_usage_contract(rec):
    """Verdict for ONE `kind == "result"` outcome record.

    Returns `"withheld"` or `"published"`. Raises `PinUsageContractError`
    otherwise -- the caller need not assert anything about the return value; the
    verdict is for reporting the split across repeated live samples.
    """
    if not isinstance(rec, dict):
        raise PinUsageContractError(
            f"outcome record is not a dict: {type(rec).__name__} {rec!r}")

    missing = [k for k in REQUIRED_KEYS if k not in rec]
    if missing:
        _fail(
            f"OUTCOME SCHEMA DRIFT: key(s) {missing} absent from the record "
            "entirely. Withholding sets the counters to None; it never removes "
            "them (stop_outcome.py builds the dict with all of them). An absent "
            "key is a schema change, not a withheld counter.", rec)

    model = rec.get("model")
    if not (isinstance(model, str) and model.strip()):
        _fail(
            "NO MODEL ON THE OUTCOME RECORD. `model` is deliberately NOT "
            "withheld by the gate (stop_outcome.py:320-323: it is not a "
            "magnitude and is stable across a session's messages), so an absent "
            "model means the transcript parse found no assistant record at all "
            "-- a genuine failure, NOT the ratified withheld case.", rec)

    for field in USAGE_FIELDS:
        value = rec[field]
        if value is not None and not _is_count(value):
            _fail(
                f"USAGE FIELD {field!r} IS NEITHER None NOR A NON-NEGATIVE int: "
                f"{value!r} ({type(value).__name__}). The gate publishes the "
                "transcript's own integers or None; anything else means the "
                "field's type changed at the source.", rec)

    transcript_path = rec.get("transcript_path")
    if not (isinstance(transcript_path, str) and transcript_path.strip()):
        _fail(
            "NO TRANSCRIPT PATH ON THE OUTCOME RECORD. Without it the withheld "
            "case cannot be told apart from a vanished usage block, which is the "
            "whole job of this check. (Measured 2026-08-05: 0 of 154 real "
            "records lack one.)", rec)

    result_text = rec.get("result_text")
    if not (isinstance(result_text, str) and result_text):
        _fail(
            "NO RESULT TEXT ON THE OUTCOME RECORD. It is the key the turn's own "
            "message is located by; without it this record cannot be tied to a "
            "message and its counters cannot be judged at all.", rec)

    usage, note = turn_usage(transcript_path, result_text)
    if usage is None:
        _fail(
            "CANNOT READ THIS TURN'S USAGE FROM THE SETTLED TRANSCRIPT. The turn "
            "is over and the harness has stopped appending, so the append race "
            "the hook loses cannot explain it: either the counters are gone at "
            "the SOURCE (usage renamed, moved, or no longer emitted) or the "
            "turn's record never landed. This is the drift a counter-tolerant "
            "assertion would have reported as a healthy withhold.", rec, note)
    settled_out = usage.get("output_tokens")
    if not _is_count(settled_out):
        _fail(
            "THIS TURN'S `message.usage` HAS NO INTEGER `output_tokens` (got "
            f"{settled_out!r}). Same reading as above: the counter is gone at "
            "the source, not lost to the race.", rec,
            f"settled usage: {usage!r} -- {note}")

    if rec["output_tokens"] is None:
        still_set = {f: rec[f] for f in USAGE_FIELDS if rec[f] is not None}
        if still_set:
            _fail(
                "PARTIALLY-NULLED USAGE. `stop_outcome.py:326` nulls all four "
                "fields in one chained assignment, so a record with "
                f"`output_tokens` withheld but {sorted(still_set)} published was "
                "not written by that gate -- publication is all-or-nothing.",
                rec, f"still set: {still_set!r}")
        return WITHHELD

    if not _is_count(rec["input_tokens"]):
        _fail(
            "PARTIALLY-PUBLISHED USAGE: `output_tokens` is published but "
            f"`input_tokens` is {rec['input_tokens']!r}. Both come from the same "
            "`message.usage` dict in the same iteration; one without the other "
            "means that dict's shape changed.", rec)
    if rec["output_tokens"] == 0:
        _fail(
            "PUBLISHED `output_tokens` IS 0. A message the operator can read "
            "cost more than zero output tokens; a published zero is a wrong "
            "number rendered as this turn's, which is the class of defect the "
            "withholding gate exists to prevent.", rec)

    disagree = {f: (rec[f], usage.get(f)) for f in USAGE_FIELDS
                if rec[f] != usage.get(f)}
    if disagree:
        _fail(
            "PUBLISHED COUNTERS DISAGREE WITH THIS TURN'S OWN MESSAGE (record "
            f"value, settled value): {disagree!r}. Publication asserts the hook "
            "saw the end of the turn, so its numbers must be that message's "
            "numbers. A mismatch is the stale-counter defect (2026-07-30: 95/130 "
            "records carried the second-to-last message's usage) returning "
            "through the publish branch.", rec, note)
    return PUBLISHED
