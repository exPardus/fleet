"""Every doctrinal citation in `bin/fleet.py` names a clause a reader can check.

THE DEFECT THIS FILE EXISTS FOR, and it is this repo's named recurring one: a
comment in prescriptive voice that cites nothing, or cites something nobody can
open. Three sites in `bin/fleet.py` cited *"an identity inference derived from
the environment may never be the sole basis of a refusal"* as if it bound the
code. It did not: it originated in a supervisor's own task brief, and the only
place it appeared in `docs/specs/**` was inside the unratified §16 amendment
this branch adds. A supervisor instruction wearing the clothes of doctrine.

The operator ruled on 2026-07-27 (`docs/OPERATOR-GATES.md`) and the clause
became doctrine, **scoped**, at `docs/specs/claim-nonce.md` §17:

    Inference may select the SUBJECT of a measurement, but may not supply the
    GROUNDS of a refusal. Donation can only ever ADD a `FLEET_WORKER` stamp and
    nothing anywhere removes one, therefore presence of the stamp is unsound
    evidence and absence is sound.

**RE-PINNED 2026-07-30: the second sentence was falsified and replaced.** The
daemon does not ADD to a hosted session's environment, it SUBSTITUTES that
environment wholesale, so absence is produced routinely by an unstamped
cold-starter and nothing strips anything. The operator replaced the scope half
in the same docket pass; §17's HEAD sentence survives, §17 stays in the corpus
as the record, and the ratified clause the code now cites lives at
`docs/specs/claim-nonce.md` §18:

    The daemon substitutes the session environment wholesale, therefore no
    `FLEET_WORKER` observation, present or absent, is evidence about this body.
    The sid is trustworthy: the vendor stamps each hosted session's own sid over
    the substituted environment, closed in the safe direction by counting, and
    every other env observation on a hosted body is evidence about the daemon's
    cold-starter, not about the body; the registry sid union is the only sound
    identity channel.

Re-pinning `CLAUSE_HEAD`/`CLAUSE_SCOPE` after an operator ruling is the same
kind of deliberate edit as re-pinning a receipt's `# at <sha>`: the constants
below are the third independent copy, so changing them is what makes the new
ruling checkable rather than merely asserted.

This file is the reason the citation cannot rot back into an assertion. It is
deliberately of the same shape as `tests/test_retired_sid_citations.py` and
`tools/verify_receipts.py`: a claim about a document is a claim until something
re-runs it. It asserts, on every run:

  1. the citation marker is present at the expected number of sites (the seed
     check -- without it every assertion below could pass vacuously);
  2. every cited section NUMBER resolves to a real heading in the cited spec;
  3. that section is RATIFIED, and is not inside the unratified amendment;
  4. every citing site quotes the ratified clause VERBATIM, and the same
     sentence is what the ratified section actually says -- so re-pointing a
     citation at a different clause is caught;
  5. the SCOPE half travels with it -- a citation that keeps the headline and
     drops the registry-sid-union sentence has taken the environment away
     without naming what replaces it, which leaves every guard in the file
     grounded on nothing;
  6. no site still cites the unratified amendment or the `[PROPOSED]` marker.

Re-pinning `EXPECTED_SITES` after deliberately adding or removing a citing site
is a one-line change, exactly as re-pinning a receipt's `# at <sha>` is.
"""
import re
from pathlib import Path

import fleet


REPO = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO / "docs" / "specs" / "claim-nonce.md"
SRC_RAW = Path(fleet.__file__).read_text(encoding="utf-8")
SPEC_RAW = SPEC_PATH.read_text(encoding="utf-8")

# The citing sites in `bin/fleet.py`, by count. Three today: the identity-block
# banner, `_ceiling_refuses_dispatch` (the site the clause EXEMPTS) and
# `_require_claim_holder` (the site it was aimed at).
EXPECTED_SITES = 3

# The marker. Deliberately one unbroken phrase so a raw-text scan can report a
# line number; the clause text after it may wrap freely.
_MARKER_RE = re.compile(r"RATIFIED DOCTRINE -- claim-nonce §(\d+(?:\.\d+)*)")

# The ratified clause, held here as an INDEPENDENT third copy -- neither the
# code's nor the spec's. Two copies that agree because one was derived from the
# other prove nothing.
CLAUSE_HEAD = ("The daemon substitutes the session environment wholesale, "
               "therefore no FLEET_WORKER observation, present or absent, is "
               "evidence about this body.")
CLAUSE_SCOPE = ("The sid is trustworthy: the vendor stamps each hosted "
                "session's own sid over the substituted environment, closed in "
                "the safe direction by counting, and every other env "
                "observation on a hosted body is evidence about the daemon's "
                "cold-starter, not about the body; the registry sid union is "
                "the only sound identity channel.")

# The clause this one REPLACED. Nothing may cite it as current doctrine again:
# it is the falsified half, and its shape (an asymmetry argument about
# donation) is exactly what a re-derivation from first principles produces.
SUPERSEDED_SCOPE = ("therefore presence of the stamp is unsound evidence and "
                    "absence is sound")

# How much normalised text after a marker counts as that site's citation.
_WINDOW = 700


def _norm(text):
    """Comment/markdown gutter stripped, whitespace collapsed.

    The same sentence has to be recognisable through a `# ` comment gutter, a
    docstring, a markdown blockquote and bold markers, or the check only ever
    works in whichever medium it was written against.
    """
    text = re.sub(r"[*`>#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


SRC_NORM = _norm(SRC_RAW)
SPEC_NORM = _norm(SPEC_RAW)


def _cited_sections():
    """(line number, section number) for every citing site, in file order."""
    out = []
    for match in _MARKER_RE.finditer(SRC_RAW):
        line = SRC_RAW.count("\n", 0, match.start()) + 1
        out.append((line, match.group(1)))
    return out


def _citation_windows():
    """(line number, section number, normalised citation text) per site."""
    windows = [SRC_NORM[m.start():m.start() + _WINDOW]
               for m in _MARKER_RE.finditer(SRC_NORM)]
    return [(ln, sec, win) for (ln, sec), win in zip(_cited_sections(), windows)]


def _spec_section(number):
    """The body of `## <number>. ...` in the cited spec, heading included.

    Returns None when no such heading exists -- which is the whole point: a
    citation pointing at a section that was never written must not pass.
    """
    lines = SPEC_RAW.splitlines()
    start = None
    for i, line in enumerate(lines):
        # `## 17. RATIFIED ...` and `### 6.5 D5 ...` are both real heading
        # shapes in this document, so the number may be followed by a dot OR by
        # whitespace. Requiring the dot made a citation of a real subsection
        # report as "not a heading", which is a true-but-misleading RED.
        if re.match(rf"^#+\s+{re.escape(number)}(?=[.\s])", line):
            start = i
            break
    if start is None:
        return None
    depth = len(lines[start]) - len(lines[start].lstrip("#"))
    for j in range(start + 1, len(lines)):
        stripped = lines[j].lstrip("#")
        level = len(lines[j]) - len(stripped)
        if lines[j].startswith("#") and 0 < level <= depth and stripped.startswith(" "):
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


class TestTheDoctrineCitationsNameARatifiedClause:

    def test_the_marker_is_found_at_all(self):
        """The harness's own seed check.

        If the marker is reworded and this regex silently matches nothing,
        every assertion below passes vacuously -- the green-while-blind failure
        `tools/verify_receipts.py --self-test` exists for, one level up.
        """
        sites = _cited_sections()
        assert len(sites) == EXPECTED_SITES, (
            f"expected {EXPECTED_SITES} doctrine citations in bin/fleet.py, "
            f"found {len(sites)} at lines {[ln for ln, _ in sites]} -- if a site "
            f"was deliberately added or removed, re-pin EXPECTED_SITES")

    def test_the_clause_is_in_the_spec_at_all(self):
        """Second seed check: `_norm` must actually recognise the clause.

        Without this, a normalisation bug makes every containment assertion
        below fail-open on the spec side.
        """
        assert _norm(CLAUSE_HEAD) in SPEC_NORM, (
            f"the ratified clause is not in {SPEC_PATH.name} at all")
        assert _norm(CLAUSE_SCOPE) in SPEC_NORM, (
            f"the clause's SCOPE half is not in {SPEC_PATH.name} at all")

    def test_every_cited_section_exists(self):
        for line, number in _cited_sections():
            assert _spec_section(number) is not None, (
                f"bin/fleet.py:{line} cites claim-nonce §{number}, which is "
                f"not a heading in {SPEC_PATH.name}")

    def test_every_cited_section_is_ratified(self):
        """A citation is only checkable if what it points at is DOCTRINE.

        §16 is the branch's own amendment and is stamped `REQUIRES OPERATOR
        RATIFICATION`; a citation that lands inside it is the original defect
        with a new address.
        """
        for line, number in _cited_sections():
            body = _spec_section(number)
            assert "RATIFIED" in body, (
                f"bin/fleet.py:{line} cites claim-nonce §{number}, which "
                f"carries no RATIFIED marker")
            # The DATE is derived, not hardcoded: pinning a literal date here
            # meant that re-pointing the citations at a later ruling (2026-07-30
            # replaced this clause once already) went RED for the wrong reason
            # and taught the next editor to loosen the assertion instead.
            assert re.search(r"RATIFIED by \w+, \d{4}-\d{2}-\d{2}", _norm(body)), (
                f"bin/fleet.py:{line} cites claim-nonce §{number}, which names "
                f"no ratification date in the form 'RATIFIED by <who>, "
                f"<YYYY-MM-DD>'")
            assert "REQUIRES OPERATOR RATIFICATION" not in body, (
                f"bin/fleet.py:{line} cites claim-nonce §{number}, which is "
                f"still awaiting ratification")

    def test_every_citation_quotes_the_ratified_clause(self):
        """The direction that matters: re-point a citation and this goes RED.

        Both halves are checked at the citing site AND in the cited section, so
        neither the code nor the spec can drift alone.
        """
        for line, number, window in _citation_windows():
            assert _norm(CLAUSE_HEAD) in window, (
                f"bin/fleet.py:{line} cites claim-nonce §{number} without "
                f"quoting the ratified clause")
            body = _norm(_spec_section(number) or "")
            assert _norm(CLAUSE_HEAD) in body, (
                f"claim-nonce §{number}, cited from bin/fleet.py:{line}, "
                f"does not state the clause the citation quotes")

    def test_the_scope_clause_travels_with_it(self):
        """The unscoped form condemned more than it was aimed at.

        Read strictly, *"inference may never be the sole basis of a refusal"*
        takes down `_ceiling_refuses_dispatch` too -- it rests on an
        environment-derived identity. The scope half is what makes the ceiling
        sound (it reads ABSENCE) and the old claim guard unsound (it read
        PRESENCE), so a citation that keeps the headline and drops the scope is
        back to condemning the whole ceiling.
        """
        for line, number, _window in _citation_windows():
            body = _norm(_spec_section(number) or "")
            assert _norm(CLAUSE_SCOPE) in body, (
                f"claim-nonce §{number}, cited from bin/fleet.py:{line}, "
                f"states the clause without its scope half")

    def test_no_site_still_cites_the_unratified_amendment(self):
        """The disease, not the symptom: `[PROPOSED]` in prescriptive voice."""
        assert "NOT RATIFIED DOCTRINE" not in SRC_RAW, (
            "bin/fleet.py still carries a `[PROPOSED -- NOT RATIFIED DOCTRINE]` "
            "marker for a clause the operator ratified on 2026-07-27")
        assert "§16.4 item 3" not in SRC_RAW, (
            "bin/fleet.py still cites claim-nonce §16.4 item 3 -- the OPEN "
            "QUESTION, not the answer to it")

    def test_no_citation_quotes_the_superseded_scope_half(self):
        """The 2026-07-30 direction: the dead clause must not come back.

        *"Presence of the stamp is unsound evidence and absence is sound"* was
        falsified by measurement -- the daemon SUBSTITUTES the environment
        rather than adding to it -- and it is exactly the sentence a
        re-derivation from first principles reproduces. §17 still contains it,
        as the record of what was ratified in 2026-07-27; a CITING SITE must
        not.
        """
        for line, number, window in _citation_windows():
            assert _norm(SUPERSEDED_SCOPE) not in window, (
                f"bin/fleet.py:{line} cites claim-nonce §{number} and quotes "
                f"the SUPERSEDED scope half -- replaced 2026-07-30 by the "
                f"substitution model (§18)")

    def test_every_cited_section_sits_after_the_amendment(self):
        """A cited section must sit AFTER §16, not within it.

        A ratified clause filed inside a document region headed *"not ratified:
        an author does not ratify their own amendment"* would be checkable and
        still wrong. Derived per citation rather than pinned to one section
        number, so re-pointing the citations at a later ruling keeps the check.
        """
        amendment = SPEC_RAW.index("\n## 16. ")
        for line, number in _cited_sections():
            heading = re.search(rf"^#+\s+{re.escape(number)}(?=[.\s])",
                                SPEC_RAW, re.M)
            assert heading is not None and heading.start() > amendment, (
                f"claim-nonce §{number}, cited from bin/fleet.py:{line}, does "
                f"not follow §16 -- the ratified clause is filed inside the "
                f"unratified amendment")
