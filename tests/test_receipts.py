"""Bind `tools/verify_receipts.py` to the suite.

CLAUDE.md rule: every pasted receipt in `docs/specs/**` is verified by
`tools/verify_receipts.py`, enforced here. Without this file the harness is a
tool nobody runs, and the class it exists to prevent -- a pasted receipt that
no longer reproduces -- stays *detected* rather than *prevented*. That is not
hypothetical: the pin-proof block in `claim-nonce.md` was fixed by hand in two
consecutive waves and was stale again both times by the next commit.

Precedent: `tests/test_terminal_surface.py`, which lints a doctrine rule the
same way.

RECEIPTS ARE VERIFIED AT THEIR PINNED COMMIT, NOT AT HEAD. The first version of
this binding re-ran every receipt against the working tree, so when `me/ul` and
`me/daemon` landed ahead of this branch and moved `bin/fleet.py` by ~620 lines,
every line-anchored receipt went red and the merge was reverted. The receipts
were correct; the tree was wrong. `verify_receipts.pinned_tree()` now
materialises each block's `# at <sha>` and runs its commands there, so an
unrelated commit cannot rot a receipt and re-pinning is a deliberate edit.
`test_pinned_receipt_survives_head_drift` is the regression test for exactly
that, and `test_working_tree_has_drifted_from_the_pin` keeps it from passing
vacuously.

Hermeticity: no network, no `~/.claude`, no live daemon, no `claude` binary.
Receipts whose evidence lives outside the repo are marked `# volatile` in the
document and are **not executed** here (`skip_volatile=True`). That marker is
the only sanctioned way to opt a receipt out; a receipt the harness cannot
classify is a FAILURE, never a skip -- see `test_unclassified_receipt_fails`,
which exists because this campaign has now shipped three separate
green-while-blind defects (a fabricated fixture, a 17-test silent skip, and the
harness's own dropped receipts).
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

# Markdown gutter: indentation, blockquote markers, one list bullet. Kept in sync
# with `verify_receipts._GUTTER_RE` by `test_gutter_regex_matches_the_harness` --
# this module needs it at COLLECTION time (`_is_enforced` drives the
# parametrisation), before the `vr` fixture can load the harness.
_GUTTER_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:[-*+][ \t]+|\d+[.)][ \t]+)?[ \t]*(?:\*\*|__)?")

REPO = pathlib.Path(__file__).resolve().parents[1]

# THE FOUNDING ARTIFACT of the parser-evasion class (H1, break-lens FINAL GATE r3,
# `docs/reviews/THREE-TIER-REDRAFT-REVIEW-2026-07-23-break.md` §2.4-§2.5).
#
# `4e540f8` is "three-tier fix-wave 2"; its parent is the tree in which four
# receipt blocks sat behind `> ` blockquote and 2-space list gutters. The old
# parser matched `$ `/`# at ` on RAW lines, so those blocks were never parsed:
# it printed `34/34 receipts reproduce exactly (37 fenced blocks ...)` and exited
# 0 on a document holding 38 blocks. Four unverified claims shaped like receipts.
#
# The fixture IS the artifact -- it is read out of git history at test time, never
# hand-transcribed, so it cannot be tuned to the detector.
FOUNDING_ARTIFACT = "4e540f8~1:docs/specs/three-tier-command.md"

# The eight gutter-hidden fence markers in that artifact, by line number, as
# reconstructed independently by the r3 census (blockquote §7.2 B1; 2-space list
# indent §10.4 B5, §11.2 B3, §11.3 B4).
FOUNDING_GUTTER_FENCES = {519, 523, 783, 787, 909, 914, 954, 958}

# Per-spec receipt floor. A spec may GAIN receipts freely; losing them below the
# floor fails here. Without this, a whole spec's receipts could stop being
# extracted -- exactly what H1 did -- with the suite still green, because
# `test_receipts_reproduce` only asserts that whatever WAS extracted reproduces.
# `test_every_enforced_spec_has_a_receipt_floor` keeps this dict exhaustive.
RECEIPT_FLOOR = {
    "claim-nonce.md": 59,
    "three-tier-command.md": 39,
}

# A commit whose bin/fleet.py predates the me/ul + me/daemon merges, used by the
# drift tests below. Any commit reachable from this branch works.
PIN = "091d5fa"
PINNED_LINE = "6849:def incarnation_path() -> Path:"
HARNESS = REPO / "tools" / "verify_receipts.py"
SPEC_DIR = REPO / "docs" / "specs"

# A spec is ENFORCED iff it carries the pinned-receipt convention -- a `# at <sha>`
# line inside a fenced block. That convention is what makes a pasted block a
# literal transcript rather than a hand-summarised illustration.
#
# Specs predating the convention are listed here WITH A REASON. They are not
# silently globbed away: `test_every_spec_is_classified` fails on any spec that
# is neither enforced nor listed, so adding a spec is a decision rather than an
# omission. This is gap 2's lesson one level up -- exclude explicitly, or the
# exclusion is invisible.
UNENFORCED = {
    "portability.md": (
        "[SUPERSEDED - native-substrate pivot 2026-07-13]. Its one receipt-shaped "
        "block is a hand-summarised line-number roll-up "
        "('tests/test_core.py:371,377,... # 10x fleet.pid_alive(...)'), never "
        "literal grep output, and it greps for probe_liveness/pid_alive which the "
        "pivot deleted. Pre-existing; flagged to the manager, not fixed here."),
    # me/daemon added a 2.1.216 daemon-lock row here carrying pasted evidence.
    # It carries no `# at <sha>` pin, so it stays out of the enforced set -- and
    # that is a real gap, not a clean exclusion: its evidence is a manager report
    # of a machine-wide outage, exactly the kind of claim the harness exists to
    # hold. Flagged to the manager; adopting the pin convention there is that
    # spec owner's call, not this slice's.
    "native-substrate.md": ("G-row contract; prose + quoted CLI output. The 2.1.216 "
                            "row from me/daemon pastes evidence but carries no "
                            "`# at <sha>` pin, so it cannot be resolved to a commit."),
    "autoclean.md": "predates the convention; no fenced receipts.",
    "terminal-surface.md": "predates the convention; no fenced receipts.",
    "providers.md": "predates the convention; no fenced receipts.",
    "phase1-hardening-kernels.md": "predates the convention; no fenced receipts.",
    "phase-2-watchtower.md": "predates the convention; no fenced receipts.",
    "phase-3-telegram.md": "predates the convention; no fenced receipts.",
    "phase-4-webui.md": "predates the convention; no fenced receipts.",
    "phase-5-intelligence.md": "predates the convention; no fenced receipts.",
    # Specs unbuilt behaviour (M1 ready-for-build, M2/M3 draft), so there is
    # nothing to re-execute yet: `fleet index` does not exist. Written
    # deliberately receipt-free -- no `$ `-prefixed lines in any fence, and all
    # format examples use synthetic placeholders rather than this repo's real
    # symbols. Its adversarial review (docs/reviews/IDX-ADVERSARIAL-2026-07-22.md)
    # failed an earlier draft for exactly the opposite: hand-written output that
    # looked like a transcript and encoded six wrong coordinates. Promote to
    # pinned receipts when M1 ships and `fleet index build` can be run.
    "fleet-index.md": ("specs unbuilt behaviour (M1 ready-for-build); no fenced "
                       "receipts by construction -- promote when M1 ships."),
}


def _all_specs():
    return sorted(SPEC_DIR.glob("*.md")) if SPEC_DIR.is_dir() else []


def _is_enforced(path):
    """A spec is enforced iff it carries a `# at <sha>` pin ANYWHERE in it.

    Deliberately gutter-blind: a pin hidden behind `> ` or list indentation still
    puts the spec in the enforced set. Matching `startswith("# at ")` here would
    let a spec whose every receipt was indented drop OUT of the enforced set --
    the H1 evasion one level up, where the whole document goes unscanned rather
    than four blocks. Such a spec is enforced and then FAILS on the evasion.
    """
    return any(_GUTTER_RE.sub("", line).startswith("# at ")
               for line in path.read_text(encoding="utf-8").splitlines())


def _load():
    spec = importlib.util.spec_from_file_location("verify_receipts", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def vr():
    if not HARNESS.exists():
        pytest.fail(f"receipt harness missing: {HARNESS}")
    mod = _load()
    try:
        mod.BASH = mod.resolve_bash()
    except SystemExit as exc:  # no POSIX bash on this machine
        pytest.skip(f"no bash available to run receipts: {exc}")
    return mod


def _specs():
    """The enforced set: specs carrying the pinned-receipt convention."""
    return [p for p in _all_specs() if _is_enforced(p)]


def test_spec_dir_is_present():
    """Guards the parameterisation below from silently covering nothing."""
    assert _all_specs(), f"no specs found under {SPEC_DIR}"
    assert _specs(), (
        "no spec carries the pinned-receipt convention -- the enforced set is "
        "empty and test_receipts_reproduce would pass vacuously")


def test_every_spec_is_classified():
    """No spec may be silently outside the harness.

    A spec is either enforced (carries `# at <sha>` receipts) or listed in
    UNENFORCED with a reason. A new spec that is neither fails here, which is
    the point: the author has to decide, and the decision is reviewable.
    """
    enforced = {p.name for p in _specs()}
    unclassified = sorted(
        p.name for p in _all_specs()
        if p.name not in enforced and p.name not in UNENFORCED)
    assert not unclassified, (
        f"spec(s) neither receipt-enforced nor declared in UNENFORCED: "
        f"{unclassified}. Add pinned `# at <sha>` receipts, or add an entry to "
        f"UNENFORCED in this file stating why not.")

    stale = sorted(n for n in UNENFORCED if n in enforced)
    assert not stale, (
        f"spec(s) listed UNENFORCED now carry pinned receipts and should be "
        f"enforced: {stale}")

    gone = sorted(n for n in UNENFORCED
                  if not (SPEC_DIR / n).exists())
    assert not gone, f"UNENFORCED names a spec that no longer exists: {gone}"


@pytest.mark.parametrize("path", _specs(), ids=lambda p: p.name)
def test_receipts_reproduce(vr, path):
    """Every pasted receipt in every spec still reproduces byte-for-byte."""
    text = path.read_text(encoding="utf-8")
    _n, failures, _warnings = vr.check(
        text, REPO, quiet=True, strict=True, skip_volatile=True)
    if failures:
        detail = "\n".join(
            f"  line {r.line}: {r.cmd}\n    " + "\n    ".join(problems)
            for r, problems in failures)
        pytest.fail(f"{path.name}: {len(failures)} receipt(s) do not reproduce:\n{detail}")


def test_harness_can_fail(vr):
    """The seed test: a verifier that cannot fail proves nothing.

    Mutates one word of a pasted receipt and requires the harness to catch it.
    If this ever passes vacuously, `test_receipts_reproduce` is theater.
    """
    target = None
    for path in _specs():
        text = path.read_text(encoding="utf-8")
        receipts, _unclassified, _blocks = vr.parse(text)
        if any(not r.volatile and r.expected for r in receipts):
            target = text
            break
    if target is None:
        pytest.skip("no non-volatile receipt with expected output to seed")
    assert vr.self_test(target, REPO), \
        "the harness did not catch a seeded one-word paraphrase"


def test_unclassified_receipt_fails(vr):
    """A receipt the harness cannot check must FAIL, never be skipped.

    This is the green-while-blind guard. An earlier harness filtered
    unclassifiable receipts out of its own result set, so a `$ ` line with no
    pasted output was neither verified nor reported.
    """
    doc = "```\n$ echo unverifiable\n```\n"
    receipts, unclassified, _blocks = vr.parse(doc)
    assert receipts == [], "a receipt with no expected output must not be checkable"
    assert len(unclassified) == 1, "the unclassifiable receipt was dropped, not reported"

    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures, "strict mode must fail on an unclassified receipt"


def test_language_tagged_fence_is_a_boundary(vr):
    """A ```lang opener must not invert every block boundary after it."""
    doc = (
        "```text\n"
        "$ echo tagged\n"
        "tagged\n"
        "```\n"
        "prose that is not inside a block\n"
        "```\n"
        "$ echo plain\n"
        "plain\n"
        "```\n"
    )
    receipts, unclassified, blocks = vr.parse(doc)
    assert blocks == 2, f"expected 2 fenced blocks, parsed {blocks}"
    assert [r.cmd for r in receipts] == ["echo tagged", "echo plain"]
    assert unclassified == []


def test_working_tree_has_drifted_from_the_pin(vr):
    """Guards the drift test below from passing vacuously.

    If HEAD's bin/fleet.py ever equals the pinned one, `test_pinned_receipt_survives_head_drift`
    proves nothing, because there would be no drift to survive.
    """
    rc, head = vr._git(REPO, "hash-object", "bin/fleet.py")
    assert rc == 0
    rc, pinned = vr._git(REPO, "rev-parse", f"{PIN}:bin/fleet.py")
    assert rc == 0
    if head.strip() == pinned.strip():
        pytest.skip("bin/fleet.py at HEAD equals the pinned blob -- no drift to test")


def test_pinned_receipt_survives_head_drift(vr):
    """THE regression this whole mechanism exists for.

    `me/ul` and `me/daemon` moved `bin/fleet.py` by ~620 lines. A receipt pinned
    at a commit before that must still reproduce; the same receipt checked
    against the working tree must not. Both halves are asserted, because only
    the pair proves the pin is what is doing the work.
    """
    cmd = 'grep -n "def incarnation_path" bin/fleet.py'

    pinned_doc = f"```\n# at {PIN}\n$ {cmd}\n{PINNED_LINE}\n```\n"
    _n, failures, _w = vr.check(pinned_doc, REPO, quiet=True, strict=True)
    assert not failures, (
        "a receipt pinned at a commit rotted when HEAD moved -- pin resolution "
        f"is not in effect: {[p for _r, p in failures]}")

    live_doc = f"```\n# at {PIN}\n# live: deliberately checked against the working tree\n$ {cmd}\n{PINNED_LINE}\n```\n"
    _n, failures, _w = vr.check(live_doc, REPO, quiet=True, strict=True)
    assert failures, (
        "the same receipt against the working tree should NOT reproduce after "
        "HEAD drifted; if it does, this test is not exercising the drift")


def test_moving_pin_is_an_error(vr):
    """`# at HEAD` is not a pin. It reintroduces the rot with extra steps."""
    doc = "```\n# at HEAD\n$ echo hi\nhi\n```\n"
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures and "not a hex sha" in failures[0][1][0]


def test_absent_pinned_commit_is_an_error_not_a_skip(vr):
    """A sha the repo does not have cannot be verified -- that is a failure.

    Shallow clones and history rewrites both produce this. Reporting green for
    an unverifiable receipt is the exact failure the harness exists to prevent.
    """
    doc = "```\n# at deadbeefdeadbeef\n$ echo hi\nhi\n```\n"
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures, "an absent pinned commit must fail, never skip"
    assert "not present in this repo" in failures[0][1][0]


def test_unpinned_receipt_fails_under_strict(vr):
    """No pin and no `# live` means it would be checked against HEAD."""
    doc = "```\n$ echo hi\nhi\n```\n"
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures and "UNPINNED" in failures[0][1][0]


def test_volatile_marker_is_honoured(vr):
    """`# volatile` must suppress a failure -- and only for the marked block."""
    doc = (
        "```\n"
        f"# at {PIN}\n"
        "# volatile: drifts\n"
        "$ echo actual\n"
        "stale expected\n"
        "```\n"
        "```\n"
        f"# at {PIN}\n"
        "$ echo actual\n"
        "stale expected\n"
        "```\n"
    )
    _n, failures, warnings = vr.check(doc, REPO, quiet=True)
    assert len(failures) == 1, "the unmarked stale receipt must still fail"
    assert len(warnings) == 1, "the volatile stale receipt must warn, not fail"

    _n, failures, _w = vr.check(doc, REPO, quiet=True, skip_volatile=True)
    assert len(failures) == 1, "skip_volatile must not suppress the unmarked failure"


# ---------------------------------------------------------------------------
# H1 -- the parser-evasion class.
#
# Doctrine (CLAUDE.md): "A receipt the harness cannot classify is a failure,
# never a skip." Until H1 that covered unclassifiable *fenced blocks* only. A
# receipt-shaped block behind a `> ` or an indent was never classified at all --
# the parser never saw it -- so it was not even eligible to be a failure. These
# tests extend the doctrine to receipt-shaped text the parser never sees.
#
# The canonical form is a COLUMN-0 backtick fence. The fix is to REJECT every
# other shape, not to quietly start parsing it: a gutter changes what a Markdown
# reader is being told (`> ` means "I am quoting this", not "I ran this"), and
# silently absorbing the shapes would leave the founding artifact reporting green
# -- a detector that cannot go red on its own founding incident is theater.
# ---------------------------------------------------------------------------

def _founding_artifact(vr):
    """The artifact, read out of git history. Absent object = failure, not skip."""
    rc, text = vr._git(REPO, "show", FOUNDING_ARTIFACT)
    assert rc == 0 and text.strip(), (
        f"cannot read the founding artifact {FOUNDING_ARTIFACT}. It is the fixture; "
        f"without it this suite proves nothing about H1. Fetch the object rather "
        f"than skipping.")
    return text


def test_gutter_regex_matches_the_harness(vr):
    """This module's collection-time copy must not drift from the harness's."""
    assert _GUTTER_RE.pattern == vr._GUTTER_RE.pattern


def test_founding_artifact_is_the_real_thing(vr):
    """Non-vacuity guard: the fixture IS the artifact, unmodified.

    If this ever passes on a hand-written stand-in, the RED proof below is
    theater. So the artifact is checked for the exact evasion geometry the r3
    census reconstructed independently from the committed trees.
    """
    text = _founding_artifact(vr)
    lines = text.splitlines()
    gutter_fences = {
        n for n, raw in enumerate(lines, start=1)
        if _GUTTER_RE.sub("", raw).startswith("```") and not raw.startswith("```")}
    assert gutter_fences == FOUNDING_GUTTER_FENCES, (
        f"the founding artifact does not carry the 8 gutter-hidden fence markers "
        f"the r3 census found; got {sorted(gutter_fences)}")
    assert 'name = f"sup|{successor_inc}|successor"' in text


def test_founding_artifact_goes_red(vr):
    """THE regression this slice exists for.

    Pre-fix, the old parser reported this document as
    `34/34 receipts reproduce exactly (37 fenced blocks, 0 unclassified, ... 0 FAILED)`
    and exited 0 -- while four receipt blocks (38 blocks really present) were
    never parsed. It must now fail, naming every hidden line.
    """
    text = _founding_artifact(vr)
    evasions = vr.scan_evasions(text)
    assert evasions, (
        "the founding artifact reports clean -- the detector cannot go red on "
        "its own founding incident")
    lines = {e.line for e in evasions}
    assert FOUNDING_GUTTER_FENCES <= lines, (
        f"gutter-hidden fence markers not reported: "
        f"{sorted(FOUNDING_GUTTER_FENCES - lines)}")
    # The four `# at` pins and four `$ ` commands inside them are hidden too.
    assert len(evasions) >= 16, (
        f"expected the 8 fence markers plus the 4 pins and 4 commands they hide, "
        f"got {len(evasions)}: {[(e.line, e.shape) for e in evasions]}")


def test_founding_artifact_fails_strict_check(vr):
    """...and the evasion must reach the caller through `check()`, not just `scan_evasions()`."""
    text = _founding_artifact(vr)
    _n, failures, warnings = vr.check(
        text, REPO, quiet=True, strict=True, skip_volatile=True, execute=False)
    assert failures, "strict check() on the founding artifact must fail"
    _n, failures, warnings = vr.check(
        text, REPO, quiet=True, strict=False, skip_volatile=True, execute=False)
    assert warnings and not failures, "without --strict an evasion must WARN, never vanish"


# The r3 probe, replayed: four shapes that all exited 0 with `0 FAILED` on a
# receipt whose expected output is flatly false. Plus the two §2.4 also checked
# by hand -- an inline backtick command, and a bare unfenced receipt.
EVASION_SHAPES = {
    "blockquoted": "> ```\n> # live: probe\n> $ echo ok\n> WRONG\n> ```\n",
    "indent2": "  ```\n  # live: probe\n  $ echo ok\n  WRONG\n  ```\n",
    "indent4-unfenced": "    # live: probe\n    $ echo ok\n    WRONG\n",
    "tildefence": "~~~\n# live: probe\n$ echo ok\nWRONG\n~~~\n",
    "list-item": "- some prose\n\n  ```\n  # live: probe\n  $ echo ok\n  WRONG\n  ```\n",
    "inline-span": "Run `$ echo ok` and you get `ok`.\n",
    "unfenced": "# live: probe\n$ echo ok\nWRONG\n",
    # H1-m1 / mutation M14: every other fixture carrying a marker also carries a
    # `$ ` command, so the command shape was doing all the work and killing
    # `_MARK_SHAPE_RE` left the suite green. A marker with nothing to lean on.
    "marker-only": "# volatile: evidence lives elsewhere\n",
    # H1-M1 / review check 3: a TAB after `$`, `# at` or `# volatile` renders
    # identically to a space and was neither parsed nor reported -- exit 0,
    # genuinely green-while-blind.
    "tab-command": "$\techo ok\nWRONG\n",
    "tab-pin": "# at 235421e56bfd328a7e913e519a1459ccf55918dc\n$\techo ok\nWRONG\n",
    "tab-gutter": "  > $\techo ok\n  > WRONG\n",
    "tab-marker": "#\tvolatile: evidence lives elsewhere\n",
    # H1-m5: bold-wrapped, so `_GUTTER_RE`'s bullet arm (which requires
    # whitespace after `-*+`) does not strip it.
    "bold-command": "**$ echo ok**\n",
}


@pytest.mark.parametrize("shape", sorted(EVASION_SHAPES), ids=lambda s: s)
def test_every_evasion_shape_is_caught(vr, shape):
    """A flatly false receipt in any of these shapes must not pass.

    Every one of these exits 0 with `0 FAILED` on the pre-H1 harness.
    """
    doc = EVASION_SHAPES[shape]
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures, f"{shape}: a false receipt in this shape still passes"

    _n, _f, warnings = vr.check(doc, REPO, quiet=True, strict=False)
    assert warnings, f"{shape}: nothing reported at all without --strict"


def test_clean_prose_is_not_flagged(vr):
    """False-positive discipline: mentioning `$` or `at` is not a receipt.

    The detector is worth nothing if authors learn to route around it, and they
    will if ordinary prose trips it.
    """
    doc = (
        "# Costs\n"
        "\n"
        "It runs at $5 per month, or $0.02 per turn. Look at line 40.\n"
        "The `$` sigil, a bare `$ ` marker, and $HOME are all fine.\n"
        "> Quoted prose about a commit at 235421e is still prose.\n"
        "\n"
        "- a list item mentioning shell variables like $PATH\n"
        "  - and a nested one, indented, about `git log` at HEAD\n"
        "\n"
        "```\n"
        "# at 235421e56bfd328a7e913e519a1459ccf55918dc\n"
        "$ echo clean\n"
        "clean\n"
        "```\n"
    )
    evasions = vr.scan_evasions(doc)
    assert evasions == [], f"false positives on clean prose: " \
        f"{[(e.line, e.shape, e.cmd) for e in evasions]}"
    _n, failures, warnings = vr.check(doc, REPO, quiet=True, strict=True)
    assert not failures and not warnings


def test_indented_code_snippet_is_not_an_evasion(vr):
    """A gutter fence is only an evasion if it wraps a receipt DIRECTIVE.

    The shape of `docs/specs/portability.md:315-325`: an illustrative ```python
    block nested under a bullet. Flagging it caught nothing and would have taught
    authors to route around the check -- so a fence is judged by its contents.
    """
    doc = (
        "- make the expected value OS-conditional:\n"
        "\n"
        "  ```python\n"
        "  def test_detached_popen_kwargs(self):\n"
        "      assert kwargs == {\"start_new_session\": True}\n"
        "  ```\n"
        "\n"
        "- and a `~~~`-fenced diagram with no commands in it:\n"
        "\n"
        "~~~\n"
        "manager -> worker\n"
        "~~~\n"
    )
    assert vr.scan_evasions(doc) == [], \
        [(e.line, e.shape) for e in vr.scan_evasions(doc)]
    assert vr.blocks_yielding_nothing(doc) == []


def test_expected_output_is_never_mistaken_for_an_evasion(vr):
    """Pasted output inside a classified block may look like anything."""
    doc = (
        "```\n"
        "# at " + PIN + "\n"
        "$ printf '  $ not a receipt\\n> quoted\\n- $ bullet\\n'\n"
        "  $ not a receipt\n"
        "> quoted\n"
        "- $ bullet\n"
        "```\n"
    )
    assert vr.scan_evasions(doc) == []
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert not failures, [p for _r, p in failures]


def test_unterminated_fence_is_an_error(vr):
    """A fence that never closes swallows the rest of the document silently."""
    doc = "```\n# at " + PIN + "\n$ echo hi\nhi\n"
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures and any("unterminated" in p.lower()
                            for _r, ps in failures for p in ps), failures


def test_enforced_specs_carry_no_evasion(vr):
    """The corpus as it stands is clean -- and stays clean."""
    dirty = {}
    for path in _specs():
        evasions = vr.scan_evasions(path.read_text(encoding="utf-8"))
        if evasions:
            dirty[path.name] = [(e.line, e.shape) for e in evasions]
    assert not dirty, (
        f"receipt-shaped text the parser never sees: {dirty}. Move it to a "
        f"column-0 ``` fence; do not loosen the detector.")


@pytest.mark.parametrize("path", _specs(), ids=lambda p: p.name)
def test_every_fenced_block_is_accounted_for(vr, path):
    """No fenced block may hold receipt-shaped text and yield nothing.

    The only tell that H1 was live was the printed `34/34 ... (37 fenced blocks)`
    mismatch, which two independent reviewers quoted and neither reconciled. This
    reconciles it mechanically.
    """
    text = path.read_text(encoding="utf-8")
    orphans = vr.blocks_yielding_nothing(text)
    assert not orphans, (
        f"{path.name}: fenced block(s) containing receipt shapes but yielding no "
        f"receipt: {orphans}")


def test_every_enforced_spec_has_a_receipt_floor():
    """RECEIPT_FLOOR must cover the enforced set exactly -- no silent omission."""
    enforced = {p.name for p in _specs()}
    missing = sorted(enforced - set(RECEIPT_FLOOR))
    assert not missing, (
        f"enforced spec(s) with no entry in RECEIPT_FLOOR: {missing}. Add the "
        f"count the harness extracts today; a spec with no floor can drop to "
        f"zero extracted receipts with this suite green.")
    stale = sorted(set(RECEIPT_FLOOR) - enforced)
    assert not stale, f"RECEIPT_FLOOR names a spec that is not enforced: {stale}"


@pytest.mark.parametrize("path", _specs(), ids=lambda p: p.name)
def test_receipt_floor_holds(vr, path):
    """A spec may gain receipts; dropping below its floor is a regression."""
    receipts, unclassified, _blocks = vr.parse(path.read_text(encoding="utf-8"))
    floor = RECEIPT_FLOOR[path.name]
    total = len(receipts) + len(unclassified)
    assert total >= floor, (
        f"{path.name}: {total} receipts extracted, floor is {floor}. Either "
        f"receipts were deleted, or extraction silently stopped seeing them.")


# ---------------------------------------------------------------------------
# H1-C1 (CRITICAL, hostile review 2026-07-23) -- the ORPHAN-BLOCK geometry.
#
# Fault injection found that mutations M10 (`_parse_block` stops reporting
# strays) and M18 (`scan_evasions` skips every fenced line, not only classified
# ones) each SURVIVED the 35-test suite -- not because either path is
# unnecessary, but because they are mutually redundant. Applied together they
# blind the harness to a column-0 fence whose every directive sits behind a
# gutter: `check(strict)` reported 0 failures on a receipt with flatly false
# pasted output, with the suite green. That is the founding incident, reachable
# again.
#
# The founding artifact cannot catch it: all four of its blocks are
# GUTTER-fenced, so `_evading_fences` -- a third path -- carries them. The
# orphan geometry (column-0 fence, gutter-hidden contents) appeared in no test.
#
# So each path is asserted by the SHAPE only it can produce, never by "some
# failure happened": the redundancy is exactly what let a single-path kill hide.
# ---------------------------------------------------------------------------

ORPHAN_BLOCK = (
    "```\n"
    "  # at 235421e56bfd328a7e913e519a1459ccf55918dc\n"
    "  $ echo hidden\n"
    "  999999\n"
    "```\n"
)


def test_orphan_block_is_reported_by_the_scan_path(vr):
    """Kills M18. The `orphaned` arm of `scan_evasions` is the only source of
    `pin`/`command` here -- if it stops scanning unclassified fenced blocks,
    these shapes disappear and only `stray-directive` remains."""
    shapes = {(e.line, e.shape) for e in vr.scan_evasions(ORPHAN_BLOCK)}
    assert (2, "pin") in shapes, shapes
    assert (3, "command") in shapes, shapes


def test_orphan_block_is_reported_by_the_block_path(vr):
    """Kills M9. `blocks_yielding_nothing` had no positive assertion anywhere:
    every test asserted `== []`, so a function returning `[]` unconditionally
    satisfied the whole suite while the docstring called it the reconciliation
    the founding incident failed to make."""
    assert vr.blocks_yielding_nothing(ORPHAN_BLOCK) == [(1, 5)]


def test_orphan_block_fails_strict_check(vr):
    """Kills the M10+M18 compound end to end.

    The pasted output is flatly false (`999999` for `echo hidden`). Under the
    compound this reported `0 failure(s), 0 warning(s)` and would have exited 0.
    """
    _n, failures, _w = vr.check(ORPHAN_BLOCK, REPO, quiet=True, strict=True)
    assert failures, "a receipt with false output inside an orphan block passed"
    _n, _f, warnings = vr.check(ORPHAN_BLOCK, REPO, quiet=True, strict=False)
    assert warnings, "nothing reported at all without --strict"


def test_stray_directive_is_reported(vr):
    """Kills M10. The only geometry where the stray path is the sole reporter.

    The block DOES classify (it has a column-0 `$ ` receipt), so `scan_evasions`
    trusts its interior and the `orphaned` arm never looks -- but the gutter-
    hidden `# at` before the receipt is a directive `_parse_block` dropped, and
    dropping it silently is how a pinned receipt becomes an unpinned one.
    """
    doc = (
        "```\n"
        "  # at 235421e56bfd328a7e913e519a1459ccf55918dc\n"
        "$ echo ok\n"
        "ok\n"
        "```\n"
    )
    shapes = {(e.line, e.shape) for e in vr.scan_evasions(doc)}
    assert (2, "stray-directive") in shapes, shapes
    _n, failures, _w = vr.check(doc, REPO, quiet=True, strict=True)
    assert failures, "a dropped pin directive must not pass"


def test_blocks_yielding_nothing_reaches_check(vr):
    """M9's second arm: the reconciliation must be enforced at runtime.

    Before this it was called by nothing but the tests, so it could not fail a
    real run no matter what it found.
    """
    shapes = {e.shape for e in vr.scan_evasions(ORPHAN_BLOCK)}
    assert "unclassified-block" in shapes, shapes


def test_extraction_seed_rejects_a_seed_that_removes_nothing(vr):
    """Kills M5 -- the non-vacuity arm of `_extraction_seed`.

    Deleting `if after >= before: ... INCONCLUSIVE` left the suite green, so the
    extraction self-test could have "passed" on a seed that never removed a
    receipt. That is the vacuous-pass class this campaign has shipped three
    times; it gets an assertion of its own.
    """
    clean = "```\n# at " + PIN + "\n$ echo seeded\nseeded\n```\n"
    assert vr._extraction_seed("no-evasion", clean, before=99) is False, \
        "a seed reporting no evasion must fail, not pass"

    # The guard must be what rejects this one. The doc DOES report an evasion
    # (the loose command), so the `if not evasions` arm returns True here and
    # only the `after >= before` arm can catch it -- without that arm the seed
    # "passes" while having removed no receipt at all.
    removes_nothing = clean + "$ loose command outside any fence\n"
    receipts, unclassified, _blocks = vr.parse(removes_nothing)
    before = len(receipts) + len(unclassified)
    assert before == 1 and vr.scan_evasions(removes_nothing), \
        "fixture must keep its receipt AND report an evasion, or this is vacuous"
    assert vr._extraction_seed("no-op", removes_nothing, before=before) is False, \
        "a seed that removes no receipt must be INCONCLUSIVE, not a pass"


def test_self_test_chains_into_extraction(vr, monkeypatch):
    """Kills M12. `self_test()` ends `return self_test_extraction(...)`.

    Replacing that with `return True` left the suite green, because the
    extraction test called `self_test_extraction` directly and
    `test_harness_can_fail` only asserted `self_test` was truthy. `--self-test`
    is what CLAUDE.md tells operators to run before trusting a green run; it
    could have silently lost its entire H1 half.
    """
    doc = "```\n# at " + PIN + "\n$ echo one two\none two\n```\n"
    called = []

    def spy(text, root):
        called.append(text)
        return False

    monkeypatch.setattr(vr, "self_test_extraction", spy)
    result = vr.self_test(doc, REPO)
    assert called, "self_test() did not chain into self_test_extraction()"
    assert result is False, \
        "self_test() must return the extraction seed's verdict, not its own"


def test_four_backtick_inline_span_is_not_a_fence(vr):
    """H1-M2. CommonMark: a backtick fence's info string may not contain a backtick.

    ```` ```x``` ```` is a four-backtick INLINE code span -- the standard way to
    write literal triple backticks in prose -- and `raw.startswith("```")` opened
    a phantom block on it. A live instance is in
    `docs/reviews/THREE-TIER-REDRAFT-REVIEW-2026-07-23-spec.md:478`. It cost a
    real receipt: the second block stopped being parsed. It failed CLOSED
    (`unterminated-fence`), so it was never green-while-blind -- but rejecting
    legal Markdown with the wrong diagnosis is how authors learn to route around
    a check.
    """
    tick4 = "`" * 4
    doc = (
        "```\n"
        "# at " + PIN + "\n"
        "$ echo one\n"
        "one\n"
        "```\n"
        # The live instance is at COLUMN 0, which is what makes it look like a
        # fence: the sibling review quotes the offending line verbatim.
        + tick4 + "```\\n# at " + tick4 + " at column 0, so it also reported 34/34.\n"
        "```\n"
        "# at " + PIN + "\n"
        "$ echo two\n"
        "two\n"
        "```\n"
    )
    receipts, unclassified, blocks = vr.parse(doc)
    assert blocks == 2, f"parsed {blocks} blocks, expected 2"
    assert [r.cmd for r in receipts] == ["echo one", "echo two"]
    assert unclassified == []
    assert vr.scan_evasions(doc) == [], \
        [(e.line, e.shape) for e in vr.scan_evasions(doc)]
    _n, failures, warnings = vr.check(doc, REPO, quiet=True, strict=True)
    assert not failures and not warnings


def test_self_test_proves_extraction_completeness(vr):
    """`--self-test` must seed an UNPARSED receipt, not only a paraphrased one.

    The old seed test mutated a word inside an already-parsed receipt, which is
    silent about everything the parser never parsed -- the entire H1 class. The
    extraction seed strips the fences off a real block and requires the harness
    to report the now-loose receipt.
    """
    doc = (
        "```\n"
        "# at " + PIN + "\n"
        "$ echo seeded\n"
        "seeded\n"
        "```\n"
    )
    assert vr.self_test_extraction(doc, REPO), \
        "the harness did not notice a receipt that stopped being parsed"
