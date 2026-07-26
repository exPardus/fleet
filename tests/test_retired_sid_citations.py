"""The `retired_sids` safety invariant, re-derived on every run.

Two load-bearing comments in `bin/fleet.py` -- `_releaser_is_roster_live`'s
docstring and the §7.1 `send` carve-out's SAFETY INVARIANT block -- justify a
fleet-wide guard with the sentence *"no FOREIGN sid ever enters a record's
`retired_sids` (every writer appends that record's OWN prior sid alone: :A, :B,
:C, :D)"*.

The spec lens re-derived the invariant and it holds. The four line numbers did
not: at `badd568` they pointed at a docstring fragment, an unrelated assignment,
a comment about a 2026-07-17 review, and a blank line -- stale on `main` too, but
re-asserted by this branch as the justification for a predicate that had just
become fleet-wide load-bearing (S-7).

This file is the reason the numbers cannot rot again, and it is deliberately of
the same shape as `tools/verify_receipts.py`: a claim about the code is a claim
until something re-runs it. It asserts three things:

  1. every cited line really is a `retired_sids` write;
  2. every `retired_sids` write in the file is cited -- so a NEW writer (the one
     that could break the invariant) cannot be added silently;
  3. every cited writer appends only its OWN record's sid, which is the
     invariant itself rather than its citation.

Re-pinning after an edit that moves those lines is a deliberate one-line change,
exactly as re-pinning a receipt's `# at <sha>` is.
"""
import re
from pathlib import Path

import fleet


SRC = Path(fleet.__file__).read_text(encoding="utf-8").splitlines()

# The two citing sites. Both carry the SAME four numbers by construction: they
# are two spellings of one invariant, and the §7.1 carve-out and the wedge
# predicate must never come to rest on different evidence.
_CITATION_RE = re.compile(r"OWN prior sid alone[^:]*((?::\d+,?\s*(?:--|#)?\s*)+)")

# A write to `retired_sids` -- the assignment form every writer uses. Excludes
# reads (`rec.get("retired_sids", [])` on the right of an assignment to
# something else) and the record template's `"retired_sids": []`.
_WRITE_RE = re.compile(r'^\s*\S+\["retired_sids"\]\s*=')


def _cited_line_numbers():
    text = "\n".join(SRC)
    found = set()
    for match in re.finditer(
            r"OWN prior sid alone[^)]*?((?::\d+[,\s#*-]*)+)", text, re.S):
        found.update(int(n) for n in re.findall(r":(\d+)", match.group(1)))
    return found


def _writer_line_numbers():
    return {i for i, line in enumerate(SRC, start=1) if _WRITE_RE.match(line)}


class TestRetiredSidWritersAreWhereTheyAreCited:

    def test_the_citation_block_is_found_at_all(self):
        # The harness's own seed check: if the sentence is reworded and this
        # regex silently matches nothing, every assertion below passes
        # vacuously. That is the failure mode the receipts verifier's
        # self-test exists for, so it is checked here too.
        cited = _cited_line_numbers()
        assert len(cited) == 4, (
            f"expected the four-writer citation, parsed {sorted(cited)} -- if the "
            f"sentence was reworded, update _CITATION_RE with it")

    def test_every_cited_line_is_a_retired_sids_write(self):
        for n in sorted(_cited_line_numbers()):
            line = SRC[n - 1]
            assert _WRITE_RE.match(line), (
                f"bin/fleet.py:{n} is cited as a `retired_sids` writer and is "
                f"not one: {line.strip()!r}")

    def test_every_retired_sids_writer_is_cited(self):
        # The direction that matters for SAFETY. A writer nobody cited is a
        # writer nobody checked, and the invariant is a claim about ALL of them.
        writers = _writer_line_numbers()
        assert writers == _cited_line_numbers(), (
            f"uncited `retired_sids` writers: {sorted(writers - _cited_line_numbers())}; "
            f"citations pointing at no writer: {sorted(_cited_line_numbers() - writers)}")

    def test_no_writer_appends_a_foreign_sid(self):
        """The invariant itself, not its citation.

        Each writer's appended value must be traceable to the record being
        written -- its own `session_id`, the `old_sid` the caller retired off
        it, or that record's own prior list. Asserted on the source text
        because the alternative is trusting the sentence."""
        allowed = ("old_sid", 'record["session_id"]', "prior_retired", "prior")
        for n in sorted(_writer_line_numbers()):
            rhs = SRC[n - 1].split("=", 1)[1]
            assert any(tok in rhs for tok in allowed), (
                f"bin/fleet.py:{n} appends something that is not this record's "
                f"own prior sid: {rhs.strip()!r}")
