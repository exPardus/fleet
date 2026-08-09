"""Pin the entry docs' mechanical claims to measurements, not to prose.

THE DEFECT THIS EXISTS FOR, AND WHY IT IS A RECURRENCE.

`knowledge/lessons.md` (2026-07-23, "doc pass 2") records this exact class:

    Second: `21 checks` was wrong in three files at once, because it is a
    derived number pasted by hand. README, `getting-started` (twice) and
    `SPEC.md` §13 all said 21 against an actual 23.

That was found by hand and fixed by hand, and nothing was left behind to hold
it. Measured again 2026-08-05 at `f457a57`, the same three-file drift had
returned with different digits: README said **25** health checks,
`getting-started.md` said **22** in its install section and **23** in its
command table -- three numbers, two files, one campaign apart, against an
actual **28**.

A number that is derived from code and pasted into prose by hand will drift
every time the code moves. The lesson was written down and it did not hold,
because a lesson is not a guard. This file is the guard.

WHAT IT PINS -- and nothing wider. Three claim shapes, each re-derived from
`bin/fleet.py` rather than from any document:

  1. a `fleet <verb>` written as a command -- inside a backtick span, or
     inside a shell-ish fenced block with its comment lines stripped -- names
     a verb `build_parser()` actually ships (the day-5 rule: a doc describing
     a CLI is re-derived from `--help`, never from memory);
     SCOPE: the six `ENTRY_DOCS`.
  2. a claim about how many checks `fleet doctor` has -- in ANY markup and in
     any of its phrasings (`28 checks`, `**28** checks`, `28 doctor checks`,
     `28 fleet health checks`, `checks: 28`, `checks -> 28`, and the separate
     `N PASS / M FAIL` tally) -- equals the number `cmd_doctor` registers.
     SCOPE: `CHECK_COUNT_DOCS`, DERIVED as every tracked markdown file minus
     `_HISTORICAL_PREFIXES`. Widened from `ENTRY_DOCS` and from the literal
     phrasing on 2026-08-09 (w50); see `_CHECK_COUNT` for why.
  3. a floor written `Python <M>.<N>+` (or the README badge's
     `python-<M>.<N>%2B`) equals `fleet.MIN_PYTHON_VERSION`.
     SCOPE: the six `ENTRY_DOCS`.

THE TWO SCOPES DIFFER ON PURPOSE, AND THE ASYMMETRY IS A KNOWN GAP RATHER
THAN A DESIGN. Shapes 1 and 3 were not widened with shape 2 because widening
them over `CLAUDE.md`, `commands/**` and `skills/**` needs its own
false-positive measurement, and w50's lane was the check count. A `fleet
frobnicate` in `skills/fleet/SKILL.md` is still unheld today.

WHAT IT DOES NOT PIN. An adversarial pass on 2026-08-05 planted 15 false
claims across these six docs and all 15 stayed green. Read fairly that is the
shape of a NARROW pin rather than a broken one -- the three shapes above are
held in their canonical phrasing, and the seed test proves the detectors fire.
But a green run here must not be read as a wider promise than it is, so the
holes are written down rather than left to be rediscovered:

  * ABSENCE. Only claims that are PRESENT get checked. Deleting a whole
    `fleet kill` row out of a command table is green. This is the hole worth
    knowing, because omission -- not invention -- is the drift that actually
    recurred in these docs: the pass that wrote this file found seven shipped
    verbs missing from the entry surface and zero invented ones.
  * FLAGS. No flag is ever checked against its verb; `fleet doctor
    [--frobnicate]` is green.
  * PHRASING, for shapes 1 and 3 ONLY. Canonical forms each. `Python 3.13 or
    newer` and `MIN_PYTHON_VERSION == (3, 13)` are not floor restatements.

    `28 doctor checks`, `checks: 28` AND `28 PASS / 0 FAIL` USED TO BE ON THAT
    LIST and none of them is any more. Each came off it the expensive way, and
    the pattern is the point:

      - `28 PASS / 0 FAIL` (2026-08-09, `_PASS_FAIL_TALLY`): gate `w48-gc`
        finding 1 measured a branch drifting that exact phrasing in
        `docs/launch-readiness.md`, one bullet away from the `<N> checks`
        claim it did update, with this file reporting `20 passed` throughout.
      - `28 doctor checks` / `checks: 28`, and the whole class of MARKUP
        (2026-08-09, w50): `docs/SPEC.md` read `**23** checks` against an
        actual 28, behind a pasted `grep -c` receipt that really does return
        28 today -- a falsehood wearing evidence. Bold defeated the regex;
        the file was also not in scope at all, which would have hidden it on
        its own. Both halves were fixed.

    Twice now, a hole this docstring NAMED as its worked example is the hole
    that shipped a defect. Enumerating a hole buys nothing. Read every entry
    below as the next defect, not as a disclaimer.

  * WHAT THE WIDENED CHECK-COUNT PIN STILL EXEMPTS, censused (wave 45: any pin
    shipping a carve-out ships the census of what it exempts):

      - DATED HISTORY, by path pattern (`_HISTORICAL_PREFIXES`). 94 hits
        across 21 files at w50 -- lane reports, gate arguments, dated reviews,
        `docs/specs/**`, `knowledge/`, `supervisor/JOURNAL.md` and the working
        ledgers. Ratified 2026-08-05: *a reference is rot only when it claims
        the CURRENT tree; a pinned receipt and a quoted argument are claims
        about a PAST tree and stay true.* Fixing them would FABRICATE.
      - THE `N -> M` DRIFT NARRATIVE, in every file. `CONTRIBUTING.md:41`
        (*"it drifted twice -- 21->23 ... against an actual 28"*) and
        `docs/SPEC.md:17` wear the identical shape, and one is true history
        while the other was a stale claim about the current tree. No regex
        separates them, so neither is held: SPEC.md:17 was rewritten by hand
        at w50 to ALSO state `28 checks` in the canonical form, which is what
        put it back under the pin. Any future `N -> M` line is unheld.
      - PROSE ENDING IN "check". The qualifier set is closed to
        `fleet`/`doctor`/`health`, so `the pending_decision check` and
        `a third grammar check` are invisible. Opening it matched twelve
        unrelated sites at w50; the seed test pins those as must-not-fire.
      - ABSENCE, still. A document that never states the count is green.
      - THE RECEIPT TEXT ITSELF. `docs/SPEC.md`'s pasted
        `grep -c "def _doctor_check_" bin/fleet.py -> 28` is held only as a
        NUMBER by this pin. `tools/verify_receipts.py` re-executes fenced
        receipts under `docs/specs/**` (`SPEC_DIR = REPO/"docs"/"specs"`, a
        glob) and `docs/SPEC.md` is not in that directory, so nothing
        re-executes the command. If the grep's output and the registration
        count ever diverge, this pin follows the registrations and the pasted
        arrow rots silently.
  * DOTTED INVOCATION. `_FLEET_INVOCATION` wants whitespace after the literal
    `fleet`, and a dot is not whitespace, so `bin/fleet.py <verb>` and
    `fleet.cmd <verb>` are invisible -- including in this module's own failure
    message, which is where a reader is taught that form. (`bin/fleet`, the
    POSIX shim, has no dot and IS seen.)
  * SUBCOMMANDS. Only the first token after `fleet ` is read, so
    `fleet index <subcommand>` is unheld.
  * EVERY OTHER NUMBER. Test counts, file counts and subcommand counts pasted
    into these docs are hand-derived and unheld here; they will drift the same
    way `21 checks` did.

WHY AST AND NOT `grep -c "def _doctor_check_"`. `SPEC.md` once pasted exactly
that grep as its receipt for the check count. It is the wrong measurement: it
counts *definitions*, and what the operator sees is the *registrations* in
`cmd_doctor`'s `check_calls` list. The two agree at `f457a57` (28 == 28) and
nothing makes them agree tomorrow -- a check defined and never wired in would
inflate the grep and not the output. `_registered_doctor_checks()` below reads
the list itself.

WHY THERE IS A SEED TEST. Root `CLAUDE.md`: "a verifier without its own seed
test proves nothing." A detector that silently matches nothing is green for the
same reason a correct doc is green, and this one lives or dies on its regexes.
`test_the_detector_catches_planted_drift` plants each of the three drifts in a
synthetic document and asserts the detector reports it.
"""
import ast
import functools
import re
import subprocess
from pathlib import Path

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parents[1]

# The entry surface: what a reader who has never seen this repo actually lands
# on. Deliberately NOT every *.md in the tree -- `docs/specs/**` has its own
# receipt harness (`tools/verify_receipts.py`), and the INTERNAL campaign docs
# (`PLAN-PROGRESS.md`, `NEXT-SESSION.md`, ...) are working ledgers whose stale
# numbers are history rather than defects. These five are the files whose job
# is to be true for a stranger.
ENTRY_DOCS = (
    "README.md",
    "docs/getting-started.md",
    "docs/concepts.md",
    "docs/README.md",
    "CONTRIBUTING.md",
    # Not an entry surface a newcomer lands on, but a claim-dense one written
    # from measurements: it goes stale the same way and is cheap to hold.
    "docs/launch-readiness.md",
)


def _entry_doc_paths():
    return [REPO_ROOT / rel for rel in ENTRY_DOCS]


# --------------------------------------------------------------------------
# Measurements -- each re-derived from bin/fleet.py, never from a document
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _shipped_verbs():
    """Every subcommand `build_parser()` ships, straight off the parser."""
    verbs = set()
    for action in fleet.build_parser()._actions:
        if hasattr(action, "_name_parser_map"):
            verbs |= set(action._name_parser_map)
    return verbs


@functools.lru_cache(maxsize=None)
def _registered_doctor_checks():
    """Count `cmd_doctor`'s `check_calls` entries by AST.

    Not `grep -c "def _doctor_check_"`: that counts definitions, and the
    number the docs claim is the number of rows an operator sees, which is the
    number of REGISTRATIONS.

    CACHED because this parses 21k lines of `bin/fleet.py` and w50 widened the
    check-count pin from 6 documents to 27, so it is called ~54 times per run.
    Per-process, and nothing mutates `bin/fleet.py` inside a run -- the mutant
    planters each start a fresh pytest process.
    """
    tree = ast.parse((REPO_ROOT / "bin" / "fleet.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_doctor":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "check_calls"
                    for t in sub.targets
                ):
                    return len(sub.value.elts)
    raise AssertionError(
        "cmd_doctor no longer assigns a `check_calls` list -- this detector "
        "is measuring the wrong thing and must be re-pointed, not deleted"
    )


# --------------------------------------------------------------------------
# Detectors -- pure functions over text, so the seed test can drive them
# --------------------------------------------------------------------------

# `fleet <verb>` only where it is being used as a COMMAND: inside a backtick
# span or a fenced code block. Unquoted prose ("fleet knows", "fleet treats the
# whole picture") is English, not a command claim, and matching it would make
# this test a liar in the noisy direction.
#
# Two narrowings, each earned by a false positive this detector produced on its
# first run against the real docs:
#   * FENCE LANGUAGE. ```mermaid blocks are diagrams. `concepts.md`'s layer
#     diagram has nodes reading "fleet sidecar" and "fleet hooks running
#     inside" -- English inside a fence, flagged as bogus verbs.
#   * COMMENT LINES. A `#` line inside a shell fence is prose too:
#     `getting-started.md` explains "(no hooks: installing fleet does not
#     change ...)" in a PowerShell block, which read as the verb `does`.
_BACKTICK_SPAN = re.compile(r"`([^`\n]+)`")
_FENCED_BLOCK = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)
_FLEET_INVOCATION = re.compile(r"\bfleet\s+([a-z][a-z0-9-]*)")

# Fence languages whose contents are commands. Anything else (mermaid, json,
# ...) is not a command context. An unlabelled fence counts: this repo's own
# receipts use them.
_SHELL_FENCES = frozenset({"", "console", "powershell", "pwsh", "bash", "sh", "shell", "text"})

# Words that legitimately follow a backticked/fenced `fleet ` without naming a
# subcommand. Kept short and explicit: every entry here is a place the pin does
# not reach, so it must be cheap to audit.
_NOT_A_VERB = frozenset({
    "sup",       # the `fleet sup-*` family shorthand
    "lock",      # `fleet.lock`, the file
    "status_snapshot",
})


def _command_spans(text):
    """Every span of `text` that is a command context, comments stripped."""
    spans = list(_BACKTICK_SPAN.findall(text))
    for lang, body in _FENCED_BLOCK.findall(text):
        if lang.strip().lower() not in _SHELL_FENCES:
            continue
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.lower().startswith("rem "):
                continue
            spans.append(line)
    return spans


def find_bogus_verbs(text, shipped):
    """`fleet <word>` used as a command that `build_parser()` does not ship."""
    bogus = set()
    for span in _command_spans(text):
        for match in _FLEET_INVOCATION.finditer(span):
            verb = match.group(1)
            if verb in _NOT_A_VERB or verb in shipped:
                continue
            # `fleet sup-*`, the docs' shorthand for the supervisor family:
            # the glob yields the bare token `sup-`, and only that token is
            # exempt. A `startswith("sup-")` here exempted all 11 shipped
            # `sup-*` verbs AND every bogus one alongside them -- measured
            # 2026-08-05, `fleet sup-frobnicate` in README's own CLI table
            # was green.
            if verb == "sup-":
                continue
            bogus.add(verb)
    return bogus


# MARKUP IS NOT PHRASING, added 2026-08-09 (w50).
#
# `docs/SPEC.md:281` read *"**23** checks"* against an actual 28, behind a
# pasted `grep -c "def _doctor_check_" bin/fleet.py -> 23` receipt -- a
# falsehood wearing evidence, which is worse than a bare wrong number because a
# reader who checks the citation finds a command that looks authoritative. The
# `**` sits between the digits and the space, so `\d+\s+` cannot reach across
# it: the bold form defeated this regex exactly as it defeated the ad-hoc
# `grep -rnoE "[0-9]+ checks"` that went looking for it.
#
# So emphasis is REMOVED before matching rather than enumerated in the pattern.
# `*`, `` ` `` and `~` are stripped wholesale (none of them occur inside a
# number or a word this pin reads); `_` is stripped only where it wraps a bare
# number, because it is a word character and `_doctor_check_` is a real token.
_EMPHASIS_RUN = re.compile(r"[*`~]+")
_UNDERSCORE_EMPHASIS = re.compile(r"(?<![A-Za-z0-9_])_(\d+)_(?![A-Za-z0-9_])")


def strip_markup(text):
    """Emphasis removed, so a claim cannot hide behind its own formatting."""
    return _EMPHASIS_RUN.sub("", _UNDERSCORE_EMPHASIS.sub(r"\1", text))


# "25 health checks", "runs 22 checks", "the 23 health checks", "28 doctor
# checks", and the comma-form "checks: 28" / "checks -> 28". Anchored on the
# word `check` so it cannot swallow unrelated numbers.
#
# The qualifier set is CLOSED (`fleet` / `doctor` / `health`) and that is a
# deliberate narrowing, measured: an open `(?:\w+\s+){0,2}` gap matched
# `4 demand check`, `9 redefine check`, `6 SPURIOUS-FIX check` and
# `4493 builds checks` across the tree -- none of them about `fleet doctor`.
# A pin that fires on unrelated prose gets suppressed, and then holds nothing.
_CHECK_COUNT = re.compile(
    r"\b(?P<before>\d+)\s+(?:fleet\s+)?(?:doctor'?s?\s+)?(?:health\s+)?checks?\b"
    r"|\bchecks?\b\s*(?::|=|→|->)\s*(?P<after>\d+)",
    re.I,
)

# THE SECOND PHRASING OF THE SAME NUMBER, added 2026-08-09.
#
# The hole this closes was written down in this module's own docstring, under
# PHRASING, using this exact string as its worked example of what the pin does
# NOT hold -- and then a branch drifted it. Gate `w48-gc` finding 1:
# `docs/launch-readiness.md` was left reading *"29 checks ... goes to 28 PASS /
# 0 FAIL"* inside ONE bullet, self-contradictory, with
# `pytest tests/test_doc_claims.py` reporting `20 passed`. Green and wrong.
#
# A doctor run's own tally is the same derived number wearing different words.
# `N PASS / M FAIL` is pinned as a PAIR, against `N + M == <registered checks>`,
# for two reasons: the sum is the row count whether or not the run was clean
# (so the pre-`init` `25 PASS / 4 FAIL` shape is held too), and requiring both
# halves keeps the regex from firing on any lone number that happens to sit
# before the word PASS.
#
# `re.I` is safe here and was checked rather than assumed: `\bPASS\b` cannot
# match inside "passed" (the boundary fails on the following `e`), so a pytest
# line like `1403 passed / 8 skipped` is invisible to it.
_PASS_FAIL_TALLY = re.compile(r"\b(\d+)\s+PASS\s*/\s*(\d+)\s+FAIL\b", re.I)


def find_check_count_claims(text):
    """Every check-count claim, as ints, in document order, markup ignored."""
    return [int(m.group("before") or m.group("after"))
            for m in _CHECK_COUNT.finditer(strip_markup(text))]


def find_pass_fail_totals(text):
    """Every `N PASS / M FAIL` tally as its implied row count `N + M`."""
    return [int(m.group(1)) + int(m.group(2))
            for m in _PASS_FAIL_TALLY.finditer(strip_markup(text))]


# --------------------------------------------------------------------------
# The population the CHECK-COUNT claim is held over -- DERIVED, not listed.
# --------------------------------------------------------------------------
#
# `ENTRY_DOCS` is a hand-written list of six files, and `docs/SPEC.md` was
# never on it. That is why w50 found `**23** checks` there: the bold form
# defeated the regex, but even written plainly the file was out of scope, and
# the file-scope miss is the one that would have held on its own. A list
# scoped to the files its author had in front of them is the same defect this
# lane fixed in `_install_statusline`'s quoting pin, one surface over.
#
# So the population is every tracked markdown file MINUS a pattern-based
# exemption. Pattern-based on purpose: the next lane report drops into
# `docs/lanes/` and is exempt by construction, without anyone editing a list.
#
# WHAT IS EXEMPT, AND WHY (ratified 2026-08-05): *a reference is rot only when
# it claims the CURRENT tree; a pinned receipt and a quoted argument are claims
# about a PAST tree and stay true.* Fixing those would FABRICATE. Measured at
# w50, the exempt set holds 94 hits across 21 files -- lane reports and gate
# arguments quoting the counts they were arguing about, dated reviews, spec
# documents describing their own moment, `knowledge/` lessons, the supervisor
# journal, and the working ledgers (`PLAN-PROGRESS.md`, `NEXT-SESSION.md`).
# `docs/OPERATOR-GATES.md:24` is the clearest case: it quotes both `29 checks`
# and `23 checks` inside an argument whose own prose says *"the truth is 28"*.
_HISTORICAL_PREFIXES = (
    # dated, per-wave working records
    "docs/lanes/", "docs/reviews/", "docs/proposals/", "docs/superpowers/",
    "docs/decisions/", "docs/AUTONOMOUS-", "docs/OVERNIGHT-", "docs/mf-",
    "spike/", "FIX-WAVE-", "REVIEW-INPUT-",
    # specs describe the tree at the moment they were ratified, and carry
    # their own receipt harness (`tools/verify_receipts.py`)
    "docs/specs/",
    # ledgers and history, named as such by their own contents
    "docs/PLAN.md", "docs/PLAN-PROGRESS.md", "docs/NEXT-SESSION.md",
    "docs/SPEC-v2-history.md", "docs/OPERATOR-GATES.md",
    "docs/IDEA-FORGE-REPORT.md", "docs/PRIOR-ART.md",
    "docs/longcat-fleet-usage.md",
    "knowledge/", "supervisor/",
)


@functools.lru_cache(maxsize=None)
def _tracked_markdown():
    proc = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"`git ls-files` failed in {REPO_ROOT}: {proc.stderr.strip()!r}. This "
        f"population is derived, never listed -- a harness that cannot derive "
        f"it must fail, not silently hold nothing."
    )
    return tuple(sorted(p for p in proc.stdout.split() if p))


def current_tree_docs():
    """Tracked markdown whose claims are about the tree AS IT IS NOW."""
    return tuple(p for p in _tracked_markdown()
                 if not p.startswith(_HISTORICAL_PREFIXES))


CHECK_COUNT_DOCS = current_tree_docs()


# "Python 3.10+", "**Python 3.10+**", "python-3.10%2B" (the shields.io badge).
_PY_FLOOR = re.compile(r"[Pp]ython[-\s]+(\d+)\.(\d+)(?:%2B|\+)", re.I)


def find_python_floor_claims(text):
    return [(int(a), int(b)) for a, b in _PY_FLOOR.findall(text)]


# --------------------------------------------------------------------------
# The pins
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ENTRY_DOCS)
def test_fleet_verbs_written_as_commands_in_entry_docs_are_shipped(rel):
    """A doc describing a CLI is re-derived from `--help`, never from memory.

    Scope, precisely: a `fleet <verb>` inside a backtick span or a shell-ish
    fence names a verb `build_parser()` ships. PRESENCE ONLY -- a shipped verb
    the docs never mention is invisible here, and so is every other invocation
    form. This module's docstring lists the holes.

    The expensive precedent (2026-07-27, day-5 interface tier): the manager
    skill was missing four shipped verbs and `supervisor.md` carried two
    `[UNBUILT]` tags on BUILT features. Six drifts, found by one `--help`.
    """
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    bogus = find_bogus_verbs(text, _shipped_verbs())
    assert not bogus, (
        f"{rel} names `fleet <verb>` for verbs build_parser() does not ship: "
        f"{sorted(bogus)}. Re-derive from `py -3.13 bin/fleet.py --help`."
    )


@pytest.mark.parametrize("rel", CHECK_COUNT_DOCS)
def test_doctor_check_counts_match_the_registered_checks(rel):
    """The recurrence pin. See this module's docstring.

    Held over `CHECK_COUNT_DOCS` -- every tracked markdown file that is not
    dated history -- and not over `ENTRY_DOCS`, since w50: `docs/SPEC.md` was
    not on the six-file list and carried `**23** checks` behind a real,
    re-runnable, WRONG receipt for the whole time this pin has existed."""
    actual = _registered_doctor_checks()
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    claims = find_check_count_claims(text)
    wrong = [n for n in claims if n != actual]
    assert not wrong, (
        f"{rel} claims fleet doctor runs {wrong} check(s); cmd_doctor registers "
        f"{actual}. This number is derived from code and has now drifted twice "
        f"(21->23 in 2026-07-23's doc pass, 23->25/22/23 by 2026-08-05). Do not "
        f"hand-paste it."
    )


@pytest.mark.parametrize("rel", CHECK_COUNT_DOCS)
def test_doctor_pass_fail_tallies_sum_to_the_registered_checks(rel):
    """The same number in its OTHER phrasing. See `_PASS_FAIL_TALLY`.

    Held separately from the `<N> checks` pin rather than folded into it,
    because the two are different claims about the same fact and a reader who
    sees only one of them fail should be told which phrasing drifted -- the
    third drift of this number was exactly a document stating BOTH, one stale.
    """
    actual = _registered_doctor_checks()
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    wrong = [n for n in find_pass_fail_totals(text) if n != actual]
    assert not wrong, (
        f"{rel} states a `N PASS / M FAIL` tally summing to {wrong}; cmd_doctor "
        f"registers {actual} check(s). Gate w48-gc finding 1 is this exact "
        f"drift, in this exact file, invisible to the `<N> checks` pin beside "
        f"this one."
    )


@pytest.mark.parametrize("rel", ENTRY_DOCS)
def test_python_floor_restatements_match_the_constant(rel):
    """`MIN_PYTHON_VERSION` is declared once; prose may only restate it.

    A README that overstates the floor turns away users who would have been
    fine. One that understates it ships a broken install.
    """
    floor = fleet.MIN_PYTHON_VERSION
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    wrong = [c for c in find_python_floor_claims(text) if c != tuple(floor)]
    assert not wrong, (
        f"{rel} states a Python floor of {wrong} against "
        f"fleet.MIN_PYTHON_VERSION == {tuple(floor)}."
    )


def test_the_registered_doctor_check_count_is_derivable():
    """Guard the measurement itself.

    If `cmd_doctor` is refactored so `check_calls` no longer exists, the three
    pins above would go green by measuring nothing. `_registered_doctor_checks`
    raises in that case; this asserts it returns a plausible count instead.
    """
    assert _registered_doctor_checks() > 0


def test_the_detector_catches_planted_drift():
    """The seed test: plant each drift and assert the detector reports it.

    Root `CLAUDE.md`: a verifier without its own seed test proves nothing. All
    three detectors here are regex-based, and a regex that matches nothing is
    green for the same reason a correct document is green.
    """
    shipped = _shipped_verbs()
    actual = _registered_doctor_checks()

    # 1. a verb that does not exist, in a backtick span and in a fence
    planted = "Run `fleet frobnicate` first.\n\n```\nfleet nonesuch --all\n```\n"
    assert find_bogus_verbs(planted, shipped) == {"frobnicate", "nonesuch"}

    # ...and a real verb in the same shapes is NOT reported
    clean = "Run `fleet doctor` first.\n\n```\nfleet spawn hello --dir .\n```\n"
    assert find_bogus_verbs(clean, shipped) == set()

    # prose is not a command claim
    assert find_bogus_verbs("fleet knows nothing about it", shipped) == set()

    # ...nor is a mermaid node, nor a comment inside a shell fence. Both are
    # real false positives this detector produced before it was narrowed; they
    # stay pinned so a future widening has to re-confront them.
    mermaid = '```mermaid\nD["fleet sidecar -- bin/fleet.py, fleet hooks inside"]\n```\n'
    assert find_bogus_verbs(mermaid, shipped) == set()
    commented = "```powershell\n# installing fleet does not change anything\nfleet doctor\n```\n"
    assert find_bogus_verbs(commented, shipped) == set()
    # but a real bogus verb in that same fence is still caught
    assert find_bogus_verbs(
        "```powershell\n# a comment\nfleet frobnicate\n```\n", shipped
    ) == {"frobnicate"}

    # the `fleet sup-*` exemption is the GLOB TOKEN ONLY, and this is the
    # assertion that keeps it that way. It was `verb.startswith("sup-")`
    # until 2026-08-05, which exempted all 11 shipped `sup-*` verbs and every
    # bogus one with them: `fleet sup-frobnicate` sat green in README's own
    # CLI table, which is 11 of 32 verbs unheld behind a one-line skip.
    assert find_bogus_verbs("`fleet sup-*`", shipped) == set()
    assert find_bogus_verbs("`fleet sup-spawn`", shipped) == set()
    assert find_bogus_verbs("`fleet sup-frobnicate`", shipped) == {"sup-frobnicate"}

    # 2. a check count that disagrees with the code
    assert find_check_count_claims(f"runs {actual + 3} health checks") == [actual + 3]
    assert find_check_count_claims("`fleet doctor` runs 22 checks") == [22]

    # 2b. MARKUP IS NOT PHRASING (w50). Every form below was invisible to this
    # detector until 2026-08-09, and the FIRST of them is the one that actually
    # shipped: `docs/SPEC.md` read "**23** checks" behind a `grep -c` receipt.
    # Each is planted and watched here rather than asserted in a docstring --
    # a widened regex nobody attacked is a claim, not a pin.
    for planted in (f"**{actual - 5}** checks",
                    f"*{actual - 5}* checks",
                    f"_{actual - 5}_ checks",
                    f"`{actual - 5}` checks",
                    f"~~{actual - 5}~~ checks",
                    f"{actual - 5} doctor checks",
                    f"{actual - 5} doctor's checks",
                    f"{actual - 5} fleet health checks",
                    f"**{actual - 5}** doctor checks",
                    f"checks: {actual - 5}",
                    f"checks → {actual - 5}",
                    f"checks -> {actual - 5}",
                    f"`checks`: **{actual - 5}**"):
        assert find_check_count_claims(planted) == [actual - 5], planted

    # ...and the same widening must not fire on prose that merely ends in the
    # word "check". Every string below is a REAL line from this tree that an
    # open `(?:\w+\s+){0,2}` qualifier gap matched at w50; a pin that cries
    # wolf on twelve unrelated sites gets suppressed and then holds nothing.
    for benign in ("4 demand check", "9 redefine check", "6 SPURIOUS-FIX check",
                   "4493 builds checks", "3 The doctor check",
                   "0 FAIL and checks", "5 doctor elevation-mismatch check",
                   "7 five-lists check", "8 Doctor-adjacent check"):
        assert find_check_count_claims(benign) == [], benign

    # the underscore rule is NARROW on purpose: `_` is a word character and
    # `_doctor_check_` is the token this whole pin is derived from.
    assert strip_markup('grep -c "def _doctor_check_" bin/fleet.py') == \
        'grep -c "def _doctor_check_" bin/fleet.py'
    assert strip_markup("**28** and _29_ and `30`") == "28 and 29 and 30"

    # 2c. the same claim in the OTHER phrasing, which the `<N> checks` regex
    # above cannot see at all -- that blindness IS gate w48-gc finding 1.
    assert find_pass_fail_totals(f"**{actual - 1} PASS / 1 FAIL**") == [actual]
    assert find_check_count_claims("goes to 28 PASS / 0 FAIL") == []
    assert find_pass_fail_totals("the same run goes to 28 PASS / 0 FAIL.") == [28]
    assert find_pass_fail_totals("**25 PASS / 4 FAIL**") == [29]
    assert find_pass_fail_totals(f"{actual} PASS / 0 FAIL") == [actual]
    # a pytest summary line is not a doctor tally: `\bPASS\b` cannot match
    # inside "passed", which is why `re.I` is safe on that regex.
    assert find_pass_fail_totals("1403 passed / 8 skipped") == []
    # and a lone number before PASS is not a tally either -- both halves required
    assert find_pass_fail_totals("28 PASS after init") == []

    # 3. a Python floor that disagrees with the constant
    floor = tuple(fleet.MIN_PYTHON_VERSION)
    bogus_floor = (floor[0], floor[1] + 3)
    planted_floor = f"Requires Python {bogus_floor[0]}.{bogus_floor[1]}+ or newer"
    assert find_python_floor_claims(planted_floor) == [bogus_floor]
    # the shields.io badge encoding is covered too -- it is where README states it
    assert find_python_floor_claims("badge/python-3.10%2B%20stdlib") == [(3, 10)]


def test_the_check_count_population_is_derived_and_split_correctly():
    """The seed for the FILE SCOPE, which is the half that actually let
    `docs/SPEC.md` through.

    The bold form defeated the regex, but even written plainly the file was
    not on `ENTRY_DOCS` -- so the scope miss would have held on its own. A
    population that silently became empty, or silently became everything,
    would be green either way; both are asserted against here."""
    docs = set(CHECK_COUNT_DOCS)
    tracked = set(_tracked_markdown())
    assert tracked, "no tracked markdown found -- the derivation is measuring nothing"

    # present: the stranger-facing surfaces AND the spec of record
    for rel in ("README.md", "docs/getting-started.md", "docs/concepts.md",
                "docs/README.md", "CONTRIBUTING.md", "docs/launch-readiness.md",
                "docs/SPEC.md", "CLAUDE.md", "docs/ROADMAP.md",
                "skills/fleet/SKILL.md"):
        assert rel in tracked and rel in docs, rel

    # absent: dated history. Fixing a quoted argument FABRICATES -- ratified
    # 2026-08-05. `docs/OPERATOR-GATES.md:24` quotes both `29 checks` and
    # `23 checks` inside an argument whose own prose says "the truth is 28".
    for rel in ("docs/OPERATOR-GATES.md", "docs/PLAN-PROGRESS.md",
                "docs/SPEC-v2-history.md", "knowledge/lessons.md",
                "supervisor/JOURNAL.md"):
        assert rel in tracked and rel not in docs, rel

    # the exemption is by PATTERN, not by enumeration: a lane report written
    # tomorrow is exempt without anyone editing a list -- which is the exact
    # failure mode (a list scoped to what its author had in front of them)
    # that this lane exists to remove.
    assert any(p.startswith("docs/lanes/") for p in tracked)
    assert not any(p.startswith("docs/lanes/") for p in docs)
    assert "docs/lanes/some-future-lane.md".startswith(_HISTORICAL_PREFIXES)

    # neither empty nor everything
    assert 10 < len(docs) < len(tracked)
