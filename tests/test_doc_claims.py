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

WHAT IT PINS. Three claim shapes, each re-derived from `bin/fleet.py` rather
than from any document:

  1. every `fleet <verb>` named in an entry doc is a verb `build_parser()`
     actually ships (the day-5 rule: a doc describing a CLI is re-derived from
     `--help`, never from memory);
  2. every "<N> checks" claim about `fleet doctor` equals the number of checks
     `cmd_doctor` actually registers;
  3. every Python-floor restatement equals `fleet.MIN_PYTHON_VERSION`.

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
import re
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

def _shipped_verbs():
    """Every subcommand `build_parser()` ships, straight off the parser."""
    verbs = set()
    for action in fleet.build_parser()._actions:
        if hasattr(action, "_name_parser_map"):
            verbs |= set(action._name_parser_map)
    return verbs


def _registered_doctor_checks():
    """Count `cmd_doctor`'s `check_calls` entries by AST.

    Not `grep -c "def _doctor_check_"`: that counts definitions, and the
    number the docs claim is the number of rows an operator sees, which is the
    number of REGISTRATIONS.
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
            # `fleet sup-*` shorthand and its glob forms
            if verb.startswith("sup-"):
                continue
            bogus.add(verb)
    return bogus


# "25 health checks", "runs 22 checks", "the 23 health checks". Anchored on the
# word `check` so it cannot swallow unrelated numbers.
_CHECK_COUNT = re.compile(r"\b(\d+)\s+(?:fleet\s+)?(?:health\s+)?checks?\b", re.I)


def find_check_count_claims(text):
    """Every "<N> checks" claim, as ints, in document order."""
    return [int(m.group(1)) for m in _CHECK_COUNT.finditer(text)]


# "Python 3.10+", "**Python 3.10+**", "python-3.10%2B" (the shields.io badge).
_PY_FLOOR = re.compile(r"[Pp]ython[-\s]+(\d+)\.(\d+)(?:%2B|\+)", re.I)


def find_python_floor_claims(text):
    return [(int(a), int(b)) for a, b in _PY_FLOOR.findall(text)]


# --------------------------------------------------------------------------
# The pins
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel", ENTRY_DOCS)
def test_every_fleet_verb_named_in_an_entry_doc_is_shipped(rel):
    """A doc describing a CLI is re-derived from `--help`, never from memory.

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


@pytest.mark.parametrize("rel", ENTRY_DOCS)
def test_doctor_check_counts_match_the_registered_checks(rel):
    """The recurrence pin. See this module's docstring."""
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

    # 2. a check count that disagrees with the code
    assert find_check_count_claims(f"runs {actual + 3} health checks") == [actual + 3]
    assert find_check_count_claims("`fleet doctor` runs 22 checks") == [22]

    # 3. a Python floor that disagrees with the constant
    floor = tuple(fleet.MIN_PYTHON_VERSION)
    bogus_floor = (floor[0], floor[1] + 3)
    planted_floor = f"Requires Python {bogus_floor[0]}.{bogus_floor[1]}+ or newer"
    assert find_python_floor_claims(planted_floor) == [bogus_floor]
    # the shields.io badge encoding is covered too -- it is where README states it
    assert find_python_floor_claims("badge/python-3.10%2B%20stdlib") == [(3, 10)]
