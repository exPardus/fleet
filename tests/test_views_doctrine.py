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
    r"|read\s+surface\s+never\s+takes"
    # The architecture-diagram sentence and the error-handling table note. Both
    # were missed by the first draft of this regex, and fault injection 2 is what
    # surfaced it: restoring their original wording left the pin green. They are
    # named here because a claim site the regex cannot see is a claim site the
    # pin does not hold.
    r"|never\s+contend\s+for\s+a\s+lock"
    r"|views\s+report,\s+the\s+writer\s+quarantines"
    r"|a\s+view\s+must\s+do\s+\W*none\W*\s+of\s+that",
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


_BULLET_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")


def _blocks(path):
    """(first_line_number, lines) per blank-line-separated block."""
    out, cur, start = [], [], 1
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            if not cur:
                start = n
            cur.append(line)
        elif cur:
            out.append((start, cur))
            cur = []
    if cur:
        out.append((start, cur))
    return out


def _paragraphs(path):
    """(first_line_number, text) per CLAIM UNIT.

    A claim unit is a blank-line block, EXCEPT that a block containing top-level
    bullets is split one unit per bullet, each carrying the block's lead-in text.

    Granularity is the whole game here. Root `CLAUDE.md`'s rules are one
    unbroken bullet list, so at block granularity a qualifier in ANY rule
    satisfies the D4 rule -- an unqualified doctrine sentence would sail through
    the moment some unrelated bullet happened to say "REQUIREMENT". Splitting per
    bullet removes that coupling. The lead-in travels with each bullet because
    D4's CURRENT STATE states the qualification once and then enumerates, which
    is the right way to write it and must not be punished.
    """
    out = []
    for start, lines in _blocks(path):
        idx = [i for i, l in enumerate(lines) if _BULLET_RE.match(l)]
        if not idx:
            out.append((start, "\n".join(lines)))
            continue
        lead = "\n".join(lines[:idx[0]])
        for j, i in enumerate(idx):
            end = idx[j + 1] if j + 1 < len(idx) else len(lines)
            out.append((start + i, lead + "\n" + "\n".join(lines[i:end])))
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


# The six restatements as they read BEFORE the views-doctrine slice corrected
# them -- i.e. the exact prose the measurement showed false. Verbatim from
# `02bf276`. `_CLAIM_RE` must recognise every one of them: these are precisely
# the sentences a future author would restore, and a regex that stops seeing them
# is a disarmed pin regardless of what the documents currently say.
#
# Fault injection 2 is why this list exists. The first draft of `_CLAIM_RE`
# missed two of these (the architecture-diagram sentence and the table note), and
# a count-based non-vacuity check could not tell.
ORIGINAL_CLAIMS = {
    "CLAUDE.md rules bullet":
        "Views (statusline, `/fleet:*`) never take `fleet.lock`, never probe a "
        "PID, never write, and never quarantine a corrupt registry — they read "
        "`fleet.status_snapshot()` and exit 0.",
    "architectural constraint, No view writes":
        "**No view writes.** Nothing in this phase writes `state/fleet.json`, "
        "`state/events.jsonl`, or takes `state/fleet.lock`.",
    "D4 heading":
        "**D4 — a view reports registry corruption; it does not quarantine.**",
    "D4 body":
        "A view must do **none** of that: quarantine is a write, and a "
        "statusline refiring every 10 s would quarantine in a loop.",
    "architecture diagram":
        "The read surface and the write surface never contend for a lock, "
        "because the read surface never takes one.",
    "error-handling table note":
        "The corrupt-registry row is D4: views report, the writer quarantines.",
    "invariant 6":
        "**6 single-writer registry** — no surface in this phase writes "
        "`fleet.json` or `events.jsonl`, and none takes `fleet.lock`.",
}


@pytest.mark.parametrize("site", sorted(ORIGINAL_CLAIMS), ids=lambda s: s)
def test_the_original_false_wording_is_still_recognised(site):
    """Non-vacuity for `_CLAIM_RE`. Narrow it and this goes red, not silent."""
    assert _CLAIM_RE.search(ORIGINAL_CLAIMS[site]), (
        f"`_CLAIM_RE` no longer recognises the {site!r} restatement of D4 as a "
        f"claim. Restoring that exact sentence would now pass the pin.")


def test_known_claim_sites_are_all_found():
    """...and the regex must still find them where they actually live.

    A floor, not an exact count: the documents may gain restatements. Six is what
    the views-doctrine slice measured after its corrections (CLAUDE.md's rule
    bullet; and in terminal-surface.md the 'No view writes' constraint, D4's
    heading, D4's CURRENT STATE enumeration, the architecture-diagram sentence,
    the error-handling table note, and invariant 6). The floor is set one below
    that because D4's CURRENT STATE bullets are this slice's own prose and a
    later rewrite may merge them away without weakening anything.
    """
    assert len(_claim_paragraphs(CLAUDE_MD)) >= 1, (
        "the D4 restatement in CLAUDE.md is no longer recognised as a claim")
    found = len(_claim_paragraphs(TERMINAL_SURFACE))
    assert found >= 5, (
        f"only {found} D4 restatement(s) recognised in terminal-surface.md, "
        f"floor is 5. Either restatements were deleted, or `_CLAIM_RE` / "
        f"`_paragraphs` stopped seeing them -- which silently disarms the pin.")


# ---------------------------------------------------------------------------
# The OTHER clause of the same paragraph, and the one it got wrong.
#
# Root `CLAUDE.md`'s D4 paragraph asserted, beside the views doctrine: *"`fleet
# doctor --repair` is now the sole path that performs the quarantine rename"*.
# Measured at `b3ec8d7` in an isolated `FLEET_HOME`, that is FALSE: `fleet
# clean`, `fleet kill`, `fleet archive` and `fleet wait` each renamed a corrupt
# `state/fleet.json` aside. The rename was never a property of `--repair` -- it
# lives in `load_registry`, and an AST walk finds thirty scopes reaching that.
#
# The true statement is weaker in exactly the way the paragraph exists to police:
# `--repair` is the only verb whose PURPOSE is the rename, and the only
# quarantining path reachable from the READ surface. Both halves are measured
# above and below rather than asserted.
#
# THE NEGATIVE HALF IS PINNED TOO, and that is deliberate. A sentence reading
# "not only `--repair`" goes wrong in the *other* direction the day a slice
# routes the last lock-holding verb off `load_registry` -- and the pin that only
# ever fires in one direction is the defect terminal-surface D4 filed against
# itself twice. So the doc assertion below is CONDITIONAL on the live
# measurement, the same shape the D4 restatement pin uses: it goes green on its
# own, with nothing to delete.
# ---------------------------------------------------------------------------

# A paragraph claiming that ONE path/verb/site performs the quarantine rename.
# Deliberately generous, for the same reason `_CLAIM_RE` is: the regression being
# pinned is a fresh unqualified restatement, not a byte-for-byte revert.
#
# The gap between the noun and the verb is bounded by `[^.;,]` rather than
# `[^.]`, and that bound is a correction this regex made to itself on its first
# run: at `[^.]{0,70}` it read across clause boundaries and flagged two innocent
# paragraphs -- the quarantine receipt's own legend (*"one surface per row; ...
# `RENAMED ASIDE` means ..."*) and a call-site note (*"gone from the read path,
# replaced by the non-quarantining reader"*). Neither claims exclusivity of
# anything. A doc pin with false positives is a pin that gets its assertion
# loosened by the next author who trips over it.
_SOLE_PERFORMER_RE = re.compile(
    # "the sole PATH that performs the ... rename", "the only SURFACE that still
    # quarantines" -- noun first, then the act.
    r"\**(?:sole|only|one)\**\s+(?:\w+\s+){0,3}\**(?:path|verb|site|surface)\**"
    r"[^.;,]{0,40}?(?:quarantin|renam)"
    # "the one remaining QUARANTINE site" -- the act first, then the noun. Both
    # orders ship in this tree, and the second was missed by the first draft.
    r"|\**(?:sole|only|one)\**\s+(?:\w+\s+){0,2}(?:quarantin\w*|renam\w*)\s+"
    r"(?:\w+\s+){0,2}(?:path|verb|site|surface)"
    r"|quarantine\s+site\s+(?:left|remaining)",
    re.I,
)

# What makes such a claim honest: it names the SCOPE that makes it true. Either
# it says the rename is not exclusive to `--repair`, or it restricts itself to
# `--repair`'s purpose or to the read surface. "still quarantines" is
# deliberately NOT in here -- terminal-surface's table note satisfied that phrase
# by accident while making the unrestricted claim.
_SOLE_PERFORMER_QUALIFIER_RE = re.compile(
    r"not the (?:sole|only)"
    r"|whose PURPOSE"
    r"|reachable from the read"
    r"|lock-holding",
    re.I,
)


# The claim shape that is FALSE OUTRIGHT rather than merely under-scoped: "the
# sole/only/one PATH (or verb, or site) that PERFORMS the rename" / "...left" /
# "...remaining". No qualifier elsewhere in the paragraph can rescue it, because
# the sentence itself asserts exclusivity of the rename.
#
# THIS REGEX EXISTS BECAUSE THE QUALIFIER RULE ABOVE FAILED ITS OWN FAULT
# INJECTION. Restoring the exact false clause -- *"is now the sole path that
# performs the quarantine rename"* -- into the corrected CLAUDE.md paragraph left
# the pin GREEN, because the surrounding grounds this lane added still contained
# a qualifier token. A paragraph that says both the true thing and the false
# thing is the LIKELY regression, not the unqualified one: the next author
# re-tightens a clause and leaves the context alone. Qualifier-presence cannot
# see that; this can.
_FALSE_PERFORMER_RE = re.compile(
    # "the sole path that performs ...", "the one quarantine site left ..."
    r"\**(?:sole|only|one)\**\s+(?:\w+\s+){0,2}\**(?:path|verb|site)\**\s+"
    r"(?:that\s+)?(?:performs|performing|left|remaining)"
    # "the one remaining quarantine site ..." -- the exhaustiveness word lands
    # BEFORE the noun. Missed by the first draft, and caught by this file's own
    # non-vacuity corpus rather than by a reader.
    r"|\**(?:sole|only|one)\**\s+(?:remaining|surviving|last)\s+(?:\w+\s+){0,2}"
    r"\**(?:path|verb|site)\**",
    re.I,
)

# ...unless the sentence is negating it, or quoting it as history. Both are
# legitimate and both appear in the corrected prose: the CLAUDE.md paragraph says
# "**not the only path that performs it**", and terminal-surface D4's residual
# quotes its own superseded wording so a reader can recognise it.
_FALSE_PERFORMER_EXEMPT_RE = re.compile(
    r"\bnot\b|used\s+to\s+(?:say|read)|no\s+longer", re.I)


def _false_performer_claims(text, window=60):
    """Every unexempted occurrence of the outright-false claim shape.

    The exemption is judged on the `window` characters immediately BEFORE the
    match rather than on the whole paragraph -- which is the whole lesson of the
    failed injection. Paragraph-wide exemption is what let the false clause back
    in under cover of the true one beside it."""
    return [m.group(0) for m in _FALSE_PERFORMER_RE.finditer(text)
            if not _FALSE_PERFORMER_EXEMPT_RE.search(
                text[max(0, m.start() - window):m.start()])]


def _quarantining_mutator():
    """A lock-holding mutating verb, as a callable. `fleet clean` is chosen
    because it reaches its `load_registry` inside `with fleet_lock():` with
    nothing else in front of it, so a corrupt registry is the only thing being
    measured -- and in a throwaway `FLEET_HOME` there is nothing for it to
    delete even if it got that far."""
    return lambda: fleet.cmd_clean(argparse.Namespace(
        dead_only=False, tombstones=False, nonce=None, yes=True, force=True))


def test_a_lock_holding_verb_still_quarantines(tmp_path, monkeypatch):
    """THE MEASUREMENT that falsifies "sole path".

    If this ever goes red the doctrine paragraph must be re-grounded, not
    patched: `--repair` would then really be the only performer, and the
    conditional pin below would stop asking.
    """
    assert _quarantines(_quarantining_mutator(), tmp_path, monkeypatch), (
        "`fleet clean` no longer quarantines a corrupt registry. That may be an "
        "improvement, but it makes root CLAUDE.md's D4 paragraph wrong in the "
        "other direction -- it says the rename is NOT exclusive to "
        "`fleet doctor --repair`. Re-measure and re-word the paragraph.")


def test_the_rename_has_exactly_one_caller(tmp_path):
    """The GROUNDS the corrected paragraph cites, pinned so the citation stays
    checkable. The paragraph tells its reader to re-derive the property by AST;
    this is that walk, so a reader who trusts the sentence is trusting something
    a test re-runs.

    One caller is the whole reason the false clause was false: because the rename
    sits behind `load_registry` rather than behind a verb, *every* caller of
    `load_registry` performs it, and no property of `--repair` can change that.
    """
    import ast

    src = pathlib.Path(fleet.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "_quarantine_registry":
            continue                      # the definition itself
        lines = sorted({c.lineno for c in ast.walk(node)
                        if isinstance(c, ast.Call)
                        and isinstance(c.func, ast.Name)
                        and c.func.id == "_quarantine_registry"})
        if lines:
            callers[node.name] = lines
    assert sorted(callers) == ["load_registry"], (
        f"`_quarantine_registry` is called from {sorted(callers)}, not from "
        f"`load_registry` alone. Root CLAUDE.md's D4 paragraph cites 'exactly "
        f"one caller' as the reason the rename is a property of the LOADER "
        f"rather than of any verb; re-word it before adding a second caller.")


@pytest.mark.parametrize("doc", [CLAUDE_MD, TERMINAL_SURFACE],
                         ids=lambda p: p.name)
def test_no_document_calls_repair_the_only_performer_of_the_rename(
        doc, tmp_path, monkeypatch):
    """While a lock-holding verb still quarantines, no paragraph may claim that
    one path/verb/site performs the rename without naming the scope that makes
    the claim true.

    This is the pin the false clause never had. It stood in the project's
    constitution for three days, was caught by a worker reading the call graph
    rather than by any test, and was deliberately left for a dedicated lane --
    which is a correct process and a missing guard at the same time.
    """
    if not _quarantines(_quarantining_mutator(), tmp_path, monkeypatch):
        pytest.skip(
            "no lock-holding verb quarantines any more -- `fleet doctor "
            "--repair` may now genuinely be the only performer, so an "
            "unrestricted claim is no longer false. "
            "`test_a_lock_holding_verb_still_quarantines` is what stops a "
            "broken measurement from reaching this skip.")

    # The strict half first: a sentence asserting the rename is performed by one
    # path is false whatever else the paragraph says around it.
    outright = {n: claims for n, t in _paragraphs(doc)
                if (claims := _false_performer_claims(t))}
    assert not outright, (
        f"{doc.name}: {outright} -- each asserts that ONE path/verb/site "
        f"performs (or is all that is left of) the quarantine rename. That is "
        f"false outright, not merely under-scoped, and no qualifier elsewhere in "
        f"the paragraph rescues it. Measured at `b3ec8d7`: `fleet clean`, "
        f"`fleet kill`, `fleet archive` and `fleet wait` all perform the rename. "
        f"Say '`--repair` is the only verb whose PURPOSE is the rename' or 'the "
        f"only quarantining path reachable from the read surface' instead -- and "
        f"if you are quoting the old wording as history, say `used to say`.")

    offenders = [n for n, t in _paragraphs(doc)
                 if _SOLE_PERFORMER_RE.search(t)
                 and not _SOLE_PERFORMER_QUALIFIER_RE.search(t)]
    assert not offenders, (
        f"{doc.name}: paragraph(s) at line(s) {offenders} claim that one "
        f"path/verb/site performs the quarantine rename, without saying which "
        f"scope makes that true. Measured at `b3ec8d7` in an isolated "
        f"FLEET_HOME: `fleet clean`, `fleet kill`, `fleet archive` and `fleet "
        f"wait` all perform it. The rename lives in `load_registry`, which has "
        f"thirty calling scopes -- so the honest claims are '`--repair` is the "
        f"only verb whose PURPOSE is the rename' and 'the only quarantining "
        f"path reachable from the read surface'. Both are much weaker, and the "
        f"difference is what the D4 paragraph is for.")


def test_the_sole_performer_regex_recognises_the_wording_it_replaced(tmp_path,
                                                                    monkeypatch):
    """Non-vacuity for `_SOLE_PERFORMER_RE`, in the idiom this file already uses
    for `_CLAIM_RE`: the exact sentences a future author would restore must all
    be recognised, and each must be an OFFENDER against the qualifier rule.
    Narrow either regex and this goes red rather than silent."""
    replaced = {
        "CLAUDE.md D4 paragraph":
            "`fleet doctor --repair` is now the sole path that performs the "
            "quarantine rename, and it is never a view.",
        "terminal-surface D4 residual 2":
            "`fleet doctor --repair` is the **one** quarantine site left in the "
            "tree, and it is not a view.",
        "terminal-surface post-fix receipt note":
            "The one remaining quarantine site in the tree is `fleet doctor "
            "--repair`, which is absent from this table because it is not a "
            "view.",
        "terminal-surface error-handling table note":
            "The only surface that still quarantines is `fleet doctor "
            "--repair`, which is the operator's explicit repair verb and not a "
            "view.",
    }
    for site, text in replaced.items():
        assert _SOLE_PERFORMER_RE.search(text), (
            f"`_SOLE_PERFORMER_RE` no longer recognises the {site!r} wording. "
            f"Restoring that exact sentence would now pass the pin.")
        assert not _SOLE_PERFORMER_QUALIFIER_RE.search(text), (
            f"the {site!r} wording now counts as QUALIFIED, so the pin would "
            f"accept the sentence it exists to reject.")

    # The strict half, and the one that matters: three of the four assert
    # exclusivity of the RENAME and must be caught even when dropped into a
    # paragraph full of correct grounds -- which is exactly how the fault
    # injection defeated the first draft of this pin.
    for site in ("CLAUDE.md D4 paragraph", "terminal-surface D4 residual 2",
                 "terminal-surface post-fix receipt note"):
        text = replaced[site]
        assert _false_performer_claims(text), (
            f"`_FALSE_PERFORMER_RE` no longer catches the {site!r} wording. It "
            f"asserts the rename has one performer, which is false at any "
            f"scope, so restoring it must go red no matter what surrounds it.")
        surrounded = (
            "The rename lives in `load_registry`, so every lock-holding verb "
            "that loads the registry still quarantines a corrupt one. "
            + text)
        assert _false_performer_claims(surrounded), (
            f"the {site!r} wording passed once TRUE grounds were placed beside "
            f"it. That is the exact failure this regex was added for: the "
            f"exemption must be judged on the words before the claim, never on "
            f"the paragraph as a whole.")

    # ...and the corrected prose must NOT trip it, or the pin is unusable.
    for ok in (
            "the only quarantining path reachable from the read surface — but "
            "**not the only path that performs it**",
            "this residual used to say it was the \"one quarantine site left in "
            "the tree\"",
            "`fleet doctor --repair` is the only verb whose PURPOSE is the "
            "quarantine rename"):
        assert not _false_performer_claims(ok), (
            f"the corrected wording {ok!r} is flagged as an outright-false "
            f"claim. A doc pin that rejects the true sentence gets loosened by "
            f"the next author instead of obeyed.")


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
