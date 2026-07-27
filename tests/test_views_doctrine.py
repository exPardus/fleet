"""Pin the D4 doctrine sentence to what shipped code actually does.

THE DEFECT THIS EXISTS FOR. Root `CLAUDE.md` and `docs/specs/terminal-surface.md`
D4 both asserted, as a description of shipped behaviour:

    Views (statusline, `/fleet:*`) never take `fleet.lock`, never probe a PID,
    never write, and never quarantine a corrupt registry -- they read
    `fleet.status_snapshot()` and exit 0.

Measured 2026-07-27 at `02bf276`, that is true of `bin/fleet_statusline.py` and
false of every read-only `/fleet:*` command: `cmd_status` (bare path), `cmd_peek`,
`cmd_result` and `fleet doctor` each take `fleet_lock()` and then
`load_registry()`, which RENAMES a corrupt `state/fleet.json` aside. The receipts
are in `docs/specs/terminal-surface.md`, section
"Receipts -- D4 measured against shipped code".

A prose sentence stood for days while the code violated it, which is proof that
prose is not a guard. This file is the guard.

THE SHAPE, AND WHY IT IS THIS SHAPE.

The obvious pin -- "assert the docs say VIOLATED" -- is a pin the next slice has
to delete, and a pin that must be deleted by the slice that fixes the bug is
worse than no pin: it turns the fix into a test edit and trains the next author
to reach for the delete key. So the assertion is CONDITIONAL on a live
measurement:

    while a view still quarantines  ->  the docs may not restate D4 unqualified
    once no view quarantines        ->  the docs may say whatever they like

`doctor-repair` (the sibling slice routing the read verbs off `load_registry()`)
flips the measurement, and this file goes green on its own with nothing deleted.
The qualified prose it leaves behind is then merely historical, not wrong.

NON-VACUITY. A conditional assertion is only as good as its condition: a detector
stuck at False would pass this file forever while saying nothing.
`test_the_quarantine_detector_can_see_a_quarantine` holds the detector against
`load_registry()` itself, which SPEC §11 REQUIRES to quarantine and which
`doctor-repair` therefore cannot make stop. That guard stays meaningful after the
fix lands, which is the point.

The measurement is in-process (monkeypatched `fleet.FLEET_HOME`, `tmp_path`), so
it spawns nothing and touches no live fleet -- the receipts in the spec are the
subprocess-level version of the same fact.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402

CLAUDE_MD = REPO / "CLAUDE.md"
TERMINAL_SURFACE = REPO / "docs" / "specs" / "terminal-surface.md"

# The doctrine claim, in every spelling the two documents have used for it. A
# paragraph matching any of these is making the D4 claim and must therefore
# carry a qualifier while the claim is false. Deliberately generous: a new
# unqualified restatement in fresh words is exactly the regression being pinned,
# and `test_known_claim_sites_are_all_found` keeps it from silently narrowing.
_CLAIM_RE = re.compile(
    r"never\s+quarantine"
    r"|not?\s+quarantine"
    r"|does\s+not\s+quarantine"
    r"|never\s+take[s]?\s+.{0,20}fleet\.lock"
    r"|none\s+takes?\s+.{0,20}fleet\.lock"
    r"|no\s+view\s+writes"
    r"|not\s+repaired\s+from\s+a\s+view"
    r"|read\s+surface\s+never\s+takes",
    re.I,
)

# What makes a restatement QUALIFIED: it distinguishes the requirement from the
# current state, or points at the measurement or the slice that closes the gap.
# Any one of these in the same paragraph is enough -- the pin is about the reader
# being able to tell rule from reality, not about a magic word.
_QUALIFIER_RE = re.compile(
    r"CURRENT STATE"
    r"|REQUIREMENT"
    r"|VIOLATED"
    r"|doctor-repair"
    r"|not the shipped behaviour"
    r"|NOT met by",
    re.I,
)

# Paragraphs that mention quarantining or the lock but make no doctrine CLAIM --
# they describe the writer's duty, or an unrelated sense of the word. Listed by a
# distinguishing substring so the census below stays exhaustive without the claim
# regex having to be clever.
_NOT_A_CLAIM = (
    "The Windows PowerShell probe is already correctly quarantined",
)


def _paragraphs(path):
    """(first_line_number, text) per blank-line-separated paragraph."""
    out, cur, start = [], [], 1
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            if not cur:
                start = n
            cur.append(line)
        elif cur:
            out.append((start, "\n".join(cur)))
            cur = []
    if cur:
        out.append((start, "\n".join(cur)))
    return out


def _claim_paragraphs(path):
    return [(n, t) for n, t in _paragraphs(path)
            if _CLAIM_RE.search(t) and not any(s in t for s in _NOT_A_CLAIM)]


def _quarantines(call, tmp_path, monkeypatch):
    """Does `call()` rename a corrupt state/fleet.json aside?

    The honest measurement, run in-process against an isolated FLEET_HOME. No
    fixture asserts the answer; the filesystem does.
    """
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    registry = tmp_path / "state" / "fleet.json"
    registry.write_text("not json at all {{{", encoding="utf-8")
    try:
        call()
    except Exception:  # noqa: BLE001 -- every failure mode is fine; the file is the verdict
        pass
    return not registry.exists()


def _view_calls():
    """The bare verbs the read-only `/fleet:*` commands inline, as callables."""
    return {
        "fleet status": lambda: fleet.cmd_status(
            argparse.Namespace(name=None, all=False, stale_ok=False, json=False)),
        "fleet peek": lambda: fleet.cmd_peek(
            argparse.Namespace(name="w", lines=20)),
        "fleet result": lambda: fleet.cmd_result(
            argparse.Namespace(name="w")),
    }


def _any_view_still_quarantines(tmp_path, monkeypatch):
    for i, (_name, call) in enumerate(_view_calls().items()):
        if _quarantines(call, tmp_path / f"probe{i}", monkeypatch):
            return True
    return False


# ---------------------------------------------------------------------------
# The measurement, asserted directly so a reader of a failure knows which half
# moved: the code, or the docs.
# ---------------------------------------------------------------------------

def test_the_quarantine_detector_can_see_a_quarantine(tmp_path, monkeypatch):
    """NON-VACUITY. Without this, a detector stuck at False passes forever.

    `load_registry()` is held against the detector rather than a view, because
    SPEC §11 REQUIRES the single writer to quarantine -- so this guard keeps
    working after `doctor-repair` lands, which a guard aimed at `cmd_status`
    would not.
    """
    assert _quarantines(fleet.load_registry, tmp_path, monkeypatch), (
        "the detector did not see load_registry() quarantine a corrupt registry. "
        "SPEC §11 requires that it does, so the detector is broken -- and a "
        "broken detector makes every conditional assertion in this file vacuous.")


def test_the_statusline_read_path_does_not_quarantine(tmp_path, monkeypatch):
    """D4 held, and must keep holding, for the surface the sentence names first.

    `status_snapshot()` is what `bin/fleet_statusline.py` calls. This is the one
    clause of the doctrine sentence that was true all along; it is pinned so the
    fix for the other clauses cannot regress it.
    """
    assert not _quarantines(
        lambda: fleet.status_snapshot(), tmp_path, monkeypatch), (
        "status_snapshot() quarantined a corrupt registry -- D4 is now violated "
        "by the statusline itself, which refires every ~10 s and would shred the "
        "operator's evidence in a loop.")


# ---------------------------------------------------------------------------
# The pin proper.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("doc", [CLAUDE_MD, TERMINAL_SURFACE],
                         ids=lambda p: p.name)
def test_doctrine_is_not_restated_unqualified_while_it_is_false(
        doc, tmp_path, monkeypatch):
    """While a view still quarantines, no restatement of D4 may stand unqualified.

    GOES GREEN ON ITS OWN when `doctor-repair` routes the read verbs off
    `load_registry()`: the guard measures, it does not remember. Nothing in this
    test has to be deleted by the slice that fixes the bug.
    """
    if not _any_view_still_quarantines(tmp_path, monkeypatch):
        pytest.skip(
            "no view quarantines any more -- D4 is true of shipped code, so an "
            "unqualified restatement is no longer a defect. This skip IS the "
            "green path; `test_the_quarantine_detector_can_see_a_quarantine` "
            "keeps it from being reached by a broken detector.")

    unqualified = [n for n, t in _claim_paragraphs(doc)
                   if not _QUALIFIER_RE.search(t)]
    assert not unqualified, (
        f"{doc.name}: paragraph(s) at line(s) {unqualified} restate the D4 "
        f"doctrine as fact while shipped code violates it. Measured at "
        f"02bf276: `fleet status`/`peek`/`result`/`doctor` take `fleet.lock` "
        f"and quarantine-rename a corrupt `state/fleet.json`; only the "
        f"statusline honours D4. Either mark the claim as the REQUIREMENT and "
        f"state the CURRENT STATE beside it (see terminal-surface.md D4), or "
        f"land the `doctor-repair` fix and this test stops asking.")


def test_known_claim_sites_are_all_found():
    """Non-vacuity for the claim regex: it must still see the sites it was written for.

    If `_CLAIM_RE` is narrowed until it matches nothing, the test above passes
    with an empty list and the pin is gone. These are the five restatements the
    views-doctrine slice corrected; a regex that stops seeing them is broken
    regardless of what the documents say.
    """
    assert len(_claim_paragraphs(CLAUDE_MD)) >= 1, (
        "the D4 restatement in CLAUDE.md is no longer recognised as a claim")
    found = len(_claim_paragraphs(TERMINAL_SURFACE))
    assert found >= 4, (
        f"only {found} D4 restatement(s) recognised in terminal-surface.md; the "
        f"slice that wrote this pin found 4 (the 'No view writes' constraint, "
        f"D4 itself, the architecture-diagram sentence, and invariant 6). A "
        f"regex that stops seeing them silently disarms the pin.")


def test_the_receipt_section_is_present_and_cited():
    """The pin is worth nothing if the evidence it points at is deleted.

    Prose may be rewritten freely; the receipts are what make the CURRENT STATE
    a measurement rather than another assertion.
    """
    spec = TERMINAL_SURFACE.read_text(encoding="utf-8")
    assert "## Receipts — D4 measured against shipped code" in spec, (
        "the D4 receipts section is gone from terminal-surface.md -- the "
        "CURRENT STATE paragraphs now cite nothing.")
    assert "# at 02bf276" in spec, (
        "the D4 receipts lost their commit pin. A receipt is a claim about a "
        "commit; an unpinned one is checked against the working tree and rots.")
    assert "tests/test_views_doctrine.py" in spec and \
           "tests/test_views_doctrine.py" in CLAUDE_MD.read_text(encoding="utf-8"), (
        "the documents no longer name this pin, so a reader correcting D4 has "
        "no way to know a test is holding them to it.")
