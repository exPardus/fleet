"""Bind `tools/verify_receipts.py` to the suite.

CLAUDE.md rule: every pasted receipt in `docs/specs/**` is verified by
`tools/verify_receipts.py`, enforced here. Without this file the harness is a
tool nobody runs, and the class it exists to prevent -- a pasted receipt that
no longer reproduces -- stays *detected* rather than *prevented*. That is not
hypothetical: the pin-proof block in `claim-nonce.md` was fixed by hand in two
consecutive waves and was stale again both times by the next commit.

Precedent: `tests/test_terminal_surface.py`, which lints a doctrine rule the
same way.

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

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
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
    "three-tier-command.md": "PROPOSAL - RESTRUCTURE REQUIRED; carries no receipts.",
    "native-substrate.md": "G-row contract; prose + quoted CLI output, no pinned receipts.",
    "autoclean.md": "predates the convention; no fenced receipts.",
    "terminal-surface.md": "predates the convention; no fenced receipts.",
    "providers.md": "predates the convention; no fenced receipts.",
    "phase1-hardening-kernels.md": "predates the convention; no fenced receipts.",
    "phase-2-watchtower.md": "predates the convention; no fenced receipts.",
    "phase-3-telegram.md": "predates the convention; no fenced receipts.",
    "phase-4-webui.md": "predates the convention; no fenced receipts.",
    "phase-5-intelligence.md": "predates the convention; no fenced receipts.",
}


def _all_specs():
    return sorted(SPEC_DIR.glob("*.md")) if SPEC_DIR.is_dir() else []


def _is_enforced(path):
    return any(line.startswith("# at ")
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


def test_volatile_marker_is_honoured(vr):
    """`# volatile` must suppress a failure -- and only for the marked block."""
    doc = (
        "```\n"
        "# volatile: drifts\n"
        "$ echo actual\n"
        "stale expected\n"
        "```\n"
        "```\n"
        "$ echo actual\n"
        "stale expected\n"
        "```\n"
    )
    _n, failures, warnings = vr.check(doc, REPO, quiet=True)
    assert len(failures) == 1, "the unmarked stale receipt must still fail"
    assert len(warnings) == 1, "the volatile stale receipt must warn, not fail"

    _n, failures, _w = vr.check(doc, REPO, quiet=True, skip_volatile=True)
    assert len(failures) == 1, "skip_volatile must not suppress the unmarked failure"
