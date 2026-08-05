"""Every line number `bin/fleet.py` cites ABOUT ITSELF resolves to what it claims.

THE DEFECT THIS FILE EXISTS FOR. `bin/fleet.py` explains itself with bare
line-number citations -- `` `_sweep_husks` (:8427) `` -- and a line number is the
one kind of evidence in this repo that rots on every unrelated edit above it.
`tests/test_retired_sid_citations.py` pinned ONE family of them (the
`retired_sids` writers) and that family is the only one that survived: at
`b3ec8d7` **19 of the file's 27 self-citations were stale**, at 13 sites --
five of them wrong the day they were written (`a7e1319`), seven of them right
at `11acca1` and drifted since. A supervisor reported "four". Four was the
subset that happened to get looked at, which is this project's named recurring
defect one level up: an inherited enumeration smaller than reality.

WHAT IS PINNED HERE, AND WHAT IS NOT -- read this before trusting the name.

  PINNED: the SET of self-citations is DERIVED by scanning the file, so a
  citation cannot be added without being registered here (one that no
  expectation covers is RED), and a registered one cannot be deleted without
  its expectation going dead (also RED). Coverage is therefore not an
  allowlist. What is declared per entry is the citation's MEANING; its
  membership is measured.

  PINNED: for the three ENUMERATING sites -- the `_quarantine_artifacts`
  reader list, the `_record_sids` union sites, the `retired_sids` writers --
  the cited set is compared against a set derived from the source, so the
  citation cannot silently under-count. That is why those sites carry
  `exactly=` rather than a per-line anchor: at `b3ec8d7` the `_record_sids`
  site said "seven" while TWELVE other sites keyed on the union.

  NOT PINNED, said plainly:

    * Citations of OTHER documents -- `SPEC.md:204`, `SPEC:1196-1198`,
      `three-tier-command.md :432-437`, `knowledge/lessons.md:756`,
      `skills/fleet/SKILL.md:54`, `spike/m0/VERDICTS.md:441`, `CN:1671-1675`,
      `SPAWN:461-471`. This file resolves line numbers against `bin/fleet.py`
      and nothing else. They are classified here only so the scanner can prove
      it has not quietly dropped a self-citation into the "not mine" bucket --
      `test_no_number_is_left_unclassified` is that proof, and it is the only
      reason `_document_prefixed` exists.

    * Anything inside an f-string. Deliberate: 3.10 emits one `STRING` token
      for an f-string while 3.12+ splits it into `FSTRING_*` with the
      `{expr}` parts as CODE, so `f"{owner[:8]}"` classifies as prose on one
      interpreter and code on the other. A pin that measures a different
      population on the two interpreters in this project's floor is worse than
      one with a stated boundary, so f-strings are excluded on BOTH and
      `test_no_citation_shape_hides_outside_prose` guards the hole: the
      distinctive citation shapes ``(:N)`` and `` `:N` `` cannot occur outside
      the prose this file reads.

    * The prose AROUND a citation. A citation can point at the right line
      while the sentence about it lies.

HOW A CITATION IS RE-PINNED. Change the number in `bin/fleet.py`; nothing here
moves. Expectations key on the citing SENTENCE, never on a line number, so they
survive the edits that break the citations they guard. Adding a citing site is
a deliberate new entry in `CITED_SITES`, exactly as re-pinning a receipt's
`# at <sha>` is deliberate.

The scan is seeded against vacuity four ways -- a floor on the citations found,
a no-dead-expectation check, a non-empty check on every derivation, and the
three-way classification check -- because a scanner that finds nothing passes
everything, which is the failure `tools/verify_receipts.py --self-test` exists
for one level up.
"""
import io
import re
import tokenize
from pathlib import Path

import fleet


SRC_PATH = Path(fleet.__file__)
SRC_RAW = SRC_PATH.read_text(encoding="utf-8")
SRC = SRC_RAW.splitlines()

# Every `:NNNN` anywhere in the file. The classifier below decides what each
# one IS; this regex deliberately over-matches.
_NUMBER_RE = re.compile(r":(\d+)")

# The two shapes a citation is written in, and neither is valid Python outside
# a string or comment -- `foo(:` does not parse and backticks are not Python.
# That is what makes `test_no_citation_shape_hides_outside_prose` sound.
_CITATION_SHAPE_RE = re.compile(r"[(`]:\d+")

# A string literal this file will read as prose: any prefix EXCEPT an f-string.
_PLAIN_STRING_RE = re.compile(r"^[rRbBuU]*['\"]")

# What a document reference looks like immediately before the colon: a path
# ending `.md`, an all-caps short name (`SPEC`, `CN`, `SPAWN`), or the one
# document this file cites by lowercase nickname. Derived from shape rather
# than held as a list of names, so a newly cited document does not silently
# become a self-citation.
_DOCUMENT_TAIL_RE = re.compile(r"(?:[\w./-]*\.md|[A-Z]{2,}|three-tier[\w.-]*)$")

# Trailing citation punctuation to peel off before asking that question.
_TAIL_PUNCT = "`( ,[-"

# How far back the document reference may sit. Citations wrap across comment
# lines (``(three-tier`` / newline / ``# `:429` ``), so the window is taken
# over raw file text with the comment gutter collapsed.
_LOOKBEHIND = 60

# A FLOOR, not a count. `test_every_self_citation_has_an_expectation` is what
# makes coverage total; an exact count would go RED whenever an unrelated lane
# adds a citation it also registers. This exists only to stop a broken scanner
# passing everything.
MINIMUM_SELF_CITATIONS = 20


def _tokens():
    return list(tokenize.generate_tokens(io.StringIO(SRC_RAW).readline))


def _line_starts():
    offsets, pos = [], 0
    for line in SRC_RAW.split("\n"):
        offsets.append(pos)
        pos += len(line) + 1
    return offsets


_LINE_STARTS = _line_starts()


def _offset(rowcol):
    row, col = rowcol
    return _LINE_STARTS[row - 1] + col


def _prose_spans():
    """`(start, end)` character offsets of every comment and plain string.

    Positions only -- never token TEXT -- so the spans are identical on 3.10
    and 3.13 for the tokens this file accepts.
    """
    spans = []
    for tok in _tokens():
        if tok.type == tokenize.COMMENT or (
                tok.type == tokenize.STRING and _PLAIN_STRING_RE.match(tok.string)):
            spans.append((_offset(tok.start), _offset(tok.end)))
    return spans


PROSE_SPANS = _prose_spans()


def _in_prose(offset):
    return any(start <= offset < end for start, end in PROSE_SPANS)


def _collapse_gutter(text):
    """Newlines plus comment hash plus indentation collapsed to one space.

    So a lookbehind window can see a document reference sitting at the end of
    the PREVIOUS comment line. Without this the `three-tier` / `` `:429` ``
    citation reads as a claim about `bin/fleet.py:429`, which is how the first
    draft of this file misfiled it.
    """
    return re.sub(r"\s*\n\s*#?\s*", " ", text)


def _document_prefixed(before):
    window = _collapse_gutter(before[-_LOOKBEHIND:]).rstrip(_TAIL_PUNCT)
    return bool(_DOCUMENT_TAIL_RE.search(window))


def _classified_numbers():
    """`(line, number, kind)` for every `:NNNN` in prose.

    `kind` is `timestamp`, `other-document` or `self`, and the fall-through is
    `self` on purpose: a misfiled self-citation surfaces as an unresolvable
    citation (RED), never as a silent pass.
    """
    out = []
    for match in _NUMBER_RE.finditer(SRC_RAW):
        if not _in_prose(match.start()):
            continue
        before = SRC_RAW[:match.start()]
        line = before.count("\n") + 1
        if before and before[-1].isdigit():
            kind = "timestamp"               # 23:25:27, 4:40am, +00:00
        elif _document_prefixed(before):
            kind = "other-document"
        else:
            kind = "self"
        out.append((line, int(match.group(1)), kind))
    return out


CLASSIFIED = _classified_numbers()
SELF_CITATIONS = [(line, n) for line, n, kind in CLASSIFIED if kind == "self"]


# --------------------------------------------------------------------------
# Derivations. Each computes a set of line numbers FROM THE SOURCE, so an
# enumerating citation is compared against reality instead of against the
# author's memory of it.
# --------------------------------------------------------------------------

def _code_lines():
    """Lines carrying at least one token that is neither prose nor layout.

    A docstring mentioning `_record_sids(rec)` must not count as a call site,
    and every derivation below rests on that distinction.
    """
    skip = {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            tokenize.ENDMARKER, tokenize.COMMENT}
    out = set()
    for tok in _tokens():
        if tok.type in skip:
            continue
        if tok.type == tokenize.STRING and _PLAIN_STRING_RE.match(tok.string):
            continue
        for n in range(tok.start[0], tok.end[0] + 1):
            out.add(n)
    return out


CODE_LINES = _code_lines()


def _function_span(name):
    """`(first, last)` line of top-level `def <name>`, or None."""
    start = None
    for i, line in enumerate(SRC, start=1):
        if re.match(rf"^def\s+{re.escape(name)}\s*\(", line):
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(SRC) + 1):
        line = SRC[j - 1]
        if line and not line[0].isspace() and not line.startswith(")"):
            return (start, j - 1)
    return (start, len(SRC))


def _enclosing_function(n):
    best = None
    for i, line in enumerate(SRC, start=1):
        if i > n:
            break
        match = re.match(r"^def\s+(\w+)", line)
        if match:
            best = match.group(1)
    return best


def _call_lines(callee):
    """Code lines that CALL `callee`, its own `def` excluded."""
    needle = callee + "("
    return {i for i, line in enumerate(SRC, start=1)
            if needle in line and i in CODE_LINES
            and not line.lstrip().startswith("def ")}


def _quarantine_artifact_readers():
    return _call_lines("_quarantine_artifacts")


def _record_sids_sites_other_than_the_citing_one():
    """`_record_sids` call sites outside the citing function and its delegate.

    The citing docstring is `_releaser_is_roster_live`'s, which describes
    itself there as "the boolean spelling of `_releaser_live_sids`" -- one
    reader in two functions -- so "other sites" excludes both.
    """
    own = {"_releaser_is_roster_live", "_releaser_live_sids"}
    return {n for n in _call_lines("_record_sids")
            if _enclosing_function(n) not in own}


def _retired_sid_writers():
    """The same `_WRITE_RE` shape `tests/test_retired_sid_citations.py` uses.

    That file still owns the INVARIANT (no writer appends a foreign sid); what
    is checked here is only that the numbers citing it resolve.
    """
    return {i for i, line in enumerate(SRC, start=1)
            if re.match(r'^\s*\S+\["retired_sids"\]\s*=', line)}


def _load_registry_quarantine_calls():
    span = _function_span("load_registry")
    return {n for n in _call_lines("_quarantine_registry")
            if span and span[0] <= n <= span[1]}


_NAMED_CITATION_RE = re.compile(r"`(\w+):(\d+)(?:-\d+)?`")


def _function_qualified_citations():
    """Citations written `func:NNNN`, where the NAME is part of the claim.

    A bare `:NNNN` says only *"this line"*. `cmd_kill:6488` says *"this line,
    and it is inside cmd_kill"* -- a second claim that is checkable straight
    from the source with no expectation entry behind it, so it is checked
    EVERYWHERE the shape occurs rather than only where someone remembered to
    register a site.

    This is the guard that survives two numbers on one citing line. `Cite`'s
    `in_named_function` reads ONE name per citing site (its marker's group 1),
    so a line enumerating `cmd_kill:A` / `cmd_respawn:B` can only ever be tested
    against one of the two names -- and a pair of numbers SWAPPED between their
    functions keeps every anchor and every `exactly` set intact. Measured, not
    assumed: that swap was planted at `bin/fleet.py:6597` and passed the whole
    file before this existed.
    """
    found = []
    for i, line in enumerate(SRC, start=1):
        if i in CODE_LINES:
            continue
        for m in _NAMED_CITATION_RE.finditer(line):
            found.append((i, m.group(1), int(m.group(2))))
    return found


FUNCTION_QUALIFIED = _function_qualified_citations()


def _supervisor_lifecycle_preflight_calls():
    """The pre-flight `_supervisor_lifecycle_target` calls P1-6's comments name.

    `_call_lines` matches a substring, and `_resolve_supervisor_lifecycle_target(`
    CONTAINS `_supervisor_lifecycle_target(` -- so the delegate's own call would
    join the set and make the enumeration look one short of reality. The
    word-boundary check is what keeps the two callers the comments enumerate
    distinct from the delegate they hand off to.
    """
    return {n for n in _call_lines("_supervisor_lifecycle_target")
            if re.search(r"(?<!\w)_supervisor_lifecycle_target\(", SRC[n - 1])}


DERIVATIONS = {
    "_quarantine_artifacts readers": _quarantine_artifact_readers,
    "_record_sids union sites": _record_sids_sites_other_than_the_citing_one,
    "retired_sids writers": _retired_sid_writers,
    "load_registry quarantine calls": _load_registry_quarantine_calls,
    "supervisor-lifecycle pre-flight calls": _supervisor_lifecycle_preflight_calls,
}


# --------------------------------------------------------------------------
# The expectations. `marker` finds the citing sentence; the rest says what the
# cited line has to BE.
# --------------------------------------------------------------------------

class Cite:
    """One citing site's claim about what its numbers point at.

    marker             regex identifying the citing sentence, searched on the
                       citing line and up to `window` lines above it. It must
                       fit on ONE line -- `bin/fleet.py` wraps its prose, and a
                       marker spanning a line break matches nothing, silently.
    anchor             substring the cited line must contain.
    one_of             derivation name; the cited line must be a member.
    exactly            derivation name; the site's WHOLE cited set must equal
                       it. The under-counting guard.
    in_named_function  the cited line must fall inside the function the citing
                       line names in the marker's group 1.
    """

    def __init__(self, name, marker, *, anchor=None, one_of=None, exactly=None,
                 in_named_function=False, window=2):
        self.name = name
        self.marker = re.compile(marker)
        self.anchor = anchor
        self.one_of = one_of
        self.exactly = exactly
        self.in_named_function = in_named_function
        self.window = window

    def match(self, citing_line):
        """The marker's match for this citing line, or None."""
        for probe in range(citing_line, citing_line - self.window - 1, -1):
            if 1 <= probe <= len(SRC):
                found = self.marker.search(SRC[probe - 1])
                if found:
                    return found
        return None


CITED_SITES = (
    # `_quarantine_artifacts`' docstring lists its readers, one bullet per
    # reader, each citing that reader's call. The bullet NAMES the function, so
    # the target is derivable from the citing text itself; `exactly` then makes
    # a sixth reader added without a bullet RED.
    Cite("quarantine-artifact readers",
         r"^\s+\* `(_\w+)`(?:'s \S+ arm)? \(:\d+\)",
         anchor="_quarantine_artifacts()",
         in_named_function=True,
         exactly="_quarantine_artifacts readers",
         window=0),

    # The §9 arm's presence-only refusal, cited from `_acting_worker_identity`
    # as the place the hole it deliberately leaves open is closed.
    Cite("the legacy-claim presence-only refusal",
         r"presence-only refusal that closes it lives in",
         anchor="_quarantine_artifacts()"),

    # `load_registry`'s rename, cited from three separate read-only sites as
    # the reason none of them may call it. Case distinguishes the first two.
    Cite("load_registry RENAMES (identity resolver)",
         r"QUARANTINES a corrupt registry -- it RENAMES the file aside",
         one_of="load_registry quarantine calls"),
    Cite("load_registry renames (records-or-none)",
         r"QUARANTINES a corrupt registry -- it renames the file aside",
         one_of="load_registry quarantine calls"),
    Cite("load_registry RENAMES (send carve-out)",
         r"which is a write\. Routing the identity read",
         one_of="load_registry quarantine calls"),

    # D4 itself, cited as the precedent the read-only helper extends.
    Cite("D4's view-path rule",
         r"rule for the view path",
         anchor="D4: it must NOT call load_registry()"),

    # The helper's definition, cited as "it names this gate as its reason".
    Cite("_registry_records_or_none's definition",
         r"names this gate as its reason",
         anchor="def _registry_records_or_none():"),

    # `_sweep_husks`' verbatim spelling of the presence-only rule, cited by the
    # sibling reader that claims to restate it word for word.
    Cite("_sweep_husks spells presence-only",
         r"spells it at",
         anchor="registry present or not"),

    # THE UNDER-COUNTING SITE, and the reason `exactly` exists: this said
    # "seven" while twelve other sites keyed on the union.
    Cite("the sid-union sites",
         r"sites that already key on the union",
         anchor="_record_sids(",
         exactly="_record_sids union sites"),

    # P1-6's two comments on the unlocked pre-flight read, each enumerating the
    # SAME pair of callers -- `cmd_kill:NNNN` / `cmd_respawn:NNNN`. Two numbers
    # on one line, naming two different functions, so `in_named_function` cannot
    # serve here (its group 1 is one name per citing line and would test both
    # numbers against `cmd_kill`). `exactly` is the stronger check anyway: a
    # THIRD caller of the pre-flight resolver added without joining these
    # enumerations goes RED, which is the under-counting class this file exists
    # for -- and it is the same class P1-6 itself was: a census that said two
    # when the source held three.
    Cite("P1-6's pre-flight callers (resolution site)",
         r"resolution that runs from",
         anchor="_supervisor_lifecycle_target(",
         exactly="supervisor-lifecycle pre-flight calls",
         window=0),
    Cite("P1-6's pre-flight callers (helper site)",
         r"ahead of either verb",
         anchor="_supervisor_lifecycle_target(",
         exactly="supervisor-lifecycle pre-flight calls",
         window=0),

    # The design sentence P1-6 says the unlocked read STOLE the quarantine from.
    # Cited as a range (`:6254-6256`); the scan takes the range's first number,
    # which is the line carrying the sentence itself.
    Cite("the lock-held resolve comment P1-6 restores",
         r"`(cmd_\w+):\d+-\d+` spells out that design",
         anchor="resolve under the lock",
         in_named_function=True,
         window=0),

    # The `retired_sids` writers, cited twice with identical numbers. One
    # expectation covers both sites, which is also the assertion that the two
    # spellings of the invariant cannot come to rest on different evidence.
    Cite("the retired_sids writers",
         r"OWN prior sid alone",
         anchor='["retired_sids"] =',
         exactly="retired_sids writers"),
)


def _assignment():
    """Both directions: citation -> owning sites, site -> its citations."""
    by_citation = {}
    by_site = {site: [] for site in CITED_SITES}
    for citing_line, cited in SELF_CITATIONS:
        owners = [s for s in CITED_SITES if s.match(citing_line)]
        by_citation[(citing_line, cited)] = owners
        for site in owners:
            by_site[site].append((citing_line, cited))
    return by_citation, by_site


BY_CITATION, BY_SITE = _assignment()


class TestTheScannerActuallySeesSomething:
    """The seed checks. Without these, everything below can pass vacuously."""

    def test_the_scan_finds_self_citations(self):
        assert len(SELF_CITATIONS) >= MINIMUM_SELF_CITATIONS, (
            f"the scanner found only {len(SELF_CITATIONS)} self-citations in "
            f"{SRC_PATH.name}; at b3ec8d7 there were 27. A scan that finds "
            f"nothing passes every assertion in this file -- fix the scanner, "
            f"do not lower the floor")

    def test_the_scan_finds_function_qualified_citations(self):
        """Without this, the swap guard below passes on an empty set."""
        assert FUNCTION_QUALIFIED, (
            f"no `func:NNNN` citation found in {SRC_PATH.name} -- either the "
            f"shape has genuinely left the file, or the scanner stopped seeing "
            f"it. Either way the swap guard is asserting over nothing")

    def test_every_expectation_is_live(self):
        """No dead entries: a deleted citing site is noticed, not ignored."""
        dead = [s.name for s in CITED_SITES if not BY_SITE[s]]
        assert not dead, (
            f"these expectations matched no citation at all: {dead} -- either "
            f"the citing sentence was reworded (update the marker) or the site "
            f"was deleted (delete the entry). Matching nothing silently is how "
            f"a pin stops pinning")

    def test_every_derivation_is_non_empty(self):
        empty = [name for name, fn in DERIVATIONS.items() if not fn()]
        assert not empty, (
            f"these derivations found nothing: {empty} -- an empty derived set "
            f"makes `exactly` and `one_of` unfalsifiable")

    def test_no_number_is_left_unclassified(self):
        """Every `:NNNN` in prose is accounted for, in one of three ways.

        Not a totality claim about citations -- it is what stops the
        `other-document` bucket quietly swallowing a self-citation, the only
        way this file could under-report its own scope.
        """
        for kind in ("timestamp", "other-document", "self"):
            assert any(k == kind for _, _, k in CLASSIFIED), (
                f"no `:NNNN` classified as {kind} -- the classifier has "
                f"stopped distinguishing the three, so `self` is no longer a "
                f"measured set")

    def test_no_citation_shape_hides_outside_prose(self):
        """The f-string / code boundary this file declares it does not read.

        ``(:N`` and `` `:N `` are not valid Python outside a string or comment,
        so every occurrence must land in the prose the scanner reads. If one
        does not, a citation has been written somewhere this file is blind.
        """
        hidden = [SRC_RAW.count("\n", 0, m.start()) + 1
                  for m in _CITATION_SHAPE_RE.finditer(SRC_RAW)
                  if not _in_prose(m.start())]
        assert not hidden, (
            f"citation-shaped text outside the prose this file reads, at lines "
            f"{sorted(set(hidden))} -- probably inside an f-string, which is "
            f"excluded because 3.10 and 3.13 tokenize it differently")


class TestEverySelfCitationResolves:

    def test_every_self_citation_has_an_expectation(self):
        """The anti-allowlist direction, and why this file is not one.

        Coverage is derived from the scan, so a citation nobody registered is a
        citation nobody checks -- and it goes RED here rather than being
        skipped for the next reader to trust.
        """
        orphans = [(ln, n) for (ln, n), owners in BY_CITATION.items()
                   if not owners]
        assert not orphans, (
            "these self-citations are covered by no expectation in "
            f"CITED_SITES: {sorted(orphans)} (as (citing line, cited line)). "
            "Add an entry saying what each one points at")

    def test_every_cited_line_is_in_range(self):
        for citing_line, cited in sorted(SELF_CITATIONS):
            assert 1 <= cited <= len(SRC), (
                f"{SRC_PATH.name}:{citing_line} cites :{cited} and the file "
                f"has {len(SRC)} lines")

    def test_no_citation_points_at_a_blank_line(self):
        """The coarsest rot, and one of the four original `badd568` failures."""
        for citing_line, cited in sorted(SELF_CITATIONS):
            assert SRC[cited - 1].strip(), (
                f"{SRC_PATH.name}:{citing_line} cites :{cited}, which is blank")

    def test_every_cited_line_carries_its_anchor(self):
        for (citing_line, cited), owners in sorted(BY_CITATION.items()):
            for site in owners:
                if site.anchor is None:
                    continue
                assert site.anchor in SRC[cited - 1], (
                    f"{SRC_PATH.name}:{citing_line} ({site.name}) cites "
                    f":{cited}, which does not contain {site.anchor!r}: "
                    f"{SRC[cited - 1].strip()!r}")

    def test_every_cited_line_is_a_member_of_its_derived_set(self):
        for (citing_line, cited), owners in sorted(BY_CITATION.items()):
            for site in owners:
                if site.one_of is None:
                    continue
                allowed = DERIVATIONS[site.one_of]()
                assert cited in allowed, (
                    f"{SRC_PATH.name}:{citing_line} ({site.name}) cites "
                    f":{cited}; the lines it may cite are {sorted(allowed)}")

    def test_every_cited_line_is_inside_the_function_it_names(self):
        """Stops a swap: two bullets trading numbers keeps both anchors happy."""
        for (citing_line, cited), owners in sorted(BY_CITATION.items()):
            for site in owners:
                if not site.in_named_function:
                    continue
                named = site.match(citing_line).group(1)
                span = _function_span(named)
                assert span is not None, (
                    f"{SRC_PATH.name}:{citing_line} names `{named}`, which is "
                    f"not a top-level function")
                assert span[0] <= cited <= span[1], (
                    f"{SRC_PATH.name}:{citing_line} cites :{cited} as being in "
                    f"`{named}`, which spans {span[0]}-{span[1]}")

    def test_every_function_qualified_citation_lands_in_that_function(self):
        """THE SWAP GUARD, and deliberately without an escape clause.

        No `if span is None: continue` here. Every `func:NNNN` in the file today
        names a real top-level function (measured: 5 of 5), so a name that does
        not resolve is a citation naming something that is not there -- which is
        the rot, not an exemption from checking it. An opt-out on an unresolvable
        name is the same shape as a pin gated behind a magic substring: whoever
        writes the next unresolvable name gets a free pass and never learns.
        """
        for citing_line, named, cited in FUNCTION_QUALIFIED:
            span = _function_span(named)
            assert span is not None, (
                f"{SRC_PATH.name}:{citing_line} cites `{named}:{cited}`, but "
                f"`{named}` is not a top-level function in this file")
            assert span[0] <= cited <= span[1], (
                f"{SRC_PATH.name}:{citing_line} cites `{named}:{cited}`, but "
                f"`{named}` spans {span[0]}-{span[1]} -- :{cited} is outside "
                f"it, so the name and the number disagree")

    def test_every_enumeration_matches_the_derived_set(self):
        """THE UNDER-COUNTING GUARD, and the reason this file exists twice over.

        An enumerating citation whose list is a subset of reality reads as a
        complete census to the next person. That is the single most-repeated
        defect in this project's record, so the list is compared against a set
        derived from the source rather than against itself.
        """
        for site in CITED_SITES:
            if site.exactly is None:
                continue
            cited = {n for _, n in BY_SITE[site]}
            expected = DERIVATIONS[site.exactly]()
            assert cited == expected, (
                f"{site.name}: cited {sorted(cited)}, but the source has "
                f"{sorted(expected)}. Missing from the citation: "
                f"{sorted(expected - cited)}; cited but not real: "
                f"{sorted(cited - expected)}")
