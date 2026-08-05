"""The self-test's three outcomes must stay three, all the way to the exit code.

`tools/verify_receipts.py` used to return a bare `bool` from `self_test`, and
`main()` turned every `False` into `rc=1`. Two populations produced that `False`:

* the harness **could not run** the check (no clean receipt to mutate, the seed
  removed nothing, the document already carries an evasion) -- nothing is known
  to be wrong; and
* the harness **proved itself broken** (a seeded paraphrase went uncaught, a
  seeded receipt fails unmutated, receipts stopped being parsed and nothing was
  reported).

Collapsing them is over-loud: an operator who runs `--self-test` on a document
with no mutable receipt gets the same red as one whose verifier is lying. The
tempting fix -- make `main()` ignore the falsy return -- is over-QUIET, and that
is strictly worse: it converts every genuine failure into silence. So the
tri-state propagates through all four functions and lands on three distinct exit
codes, and **every genuine-failure path still exits non-zero with `EXIT_FAILED`**.

THE TRAP THIS FILE EXISTS TO HOLD SHUT. Three pins in `tests/test_receipts.py`
assert the *bool* these functions return -- `assert vr.self_test(...)` and
`assert vr.self_test_extraction(...)`. A tri-state whose members are all truthy
(a string constant, a plain `enum.Enum`) leaves both of those passing on
INCONCLUSIVE: the corpus's two strongest anti-vacuity pins go green-while-blind
on the day the tri-state lands. So `Verdict` **refuses to be coerced to bool**;
any surviving truthiness use raises `TypeError` instead of silently picking a
branch. `test_verdict_refuses_to_be_a_bool` is what keeps that property.

Hermetic: every fixture document is a `# live` `echo`, so nothing is
materialised out of git and nothing outside this repo is read.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
HARNESS = REPO / "tools" / "verify_receipts.py"


@pytest.fixture(scope="module")
def vr():
    if not HARNESS.exists():
        pytest.fail(f"receipt harness missing: {HARNESS}")
    spec = importlib.util.spec_from_file_location("verify_receipts_tristate", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.BASH = mod.resolve_bash()
    except SystemExit as exc:  # no POSIX bash on this machine
        pytest.skip(f"no bash available to run receipts: {exc}")
    return mod


# A document whose single receipt reproduces and carries a multi-word expected
# line: the one shape on which both seeds can actually run.
GOOD = (
    "```\n"
    "# live: unit fixture, deliberately about the working tree\n"
    "$ echo one two\n"
    "one two\n"
    "```\n"
)

# Same, but the expected line is a single word -- so `self_test` has nothing it
# can paraphrase and must say so without claiming anything is broken.
SINGLE_WORD = (
    "```\n"
    "# live: unit fixture, deliberately about the working tree\n"
    "$ echo solo\n"
    "solo\n"
    "```\n"
)

# A receipt whose pasted output is flatly false. `check()` fails on it, and
# `self_test` cannot use it as a seed target because it does not reproduce.
FALSE_RECEIPT = (
    "```\n"
    "# live: unit fixture, deliberately about the working tree\n"
    "$ echo actual\n"
    "this is not what that prints\n"
    "```\n"
)


# ---------------------------------------------------------------------------
# The verdict type itself.
# ---------------------------------------------------------------------------

def test_verdict_has_exactly_three_states(vr):
    """Two states is the bug; four would mean something else drifted in."""
    assert {v.name for v in vr.Verdict} == {"PASSED", "INCONCLUSIVE", "FAILED"}
    assert vr.Verdict.PASSED is not vr.Verdict.INCONCLUSIVE
    assert vr.Verdict.INCONCLUSIVE is not vr.Verdict.FAILED


@pytest.mark.parametrize("name", ["PASSED", "INCONCLUSIVE", "FAILED"])
def test_verdict_refuses_to_be_a_bool(vr, name):
    """THE anti-silence property, and the reason this is not a string enum.

    `tests/test_receipts.py` carries `assert vr.self_test(...)` and
    `assert vr.self_test_extraction(...)`. If a verdict were truthy, both would
    pass on INCONCLUSIVE and the two strongest anti-vacuity pins in the corpus
    would stop testing anything -- silently, on the day the tri-state landed.
    A verdict that cannot be coerced makes that failure loud instead.
    """
    verdict = getattr(vr.Verdict, name)
    with pytest.raises(TypeError):
        bool(verdict)
    with pytest.raises(TypeError):
        if verdict:  # pragma: no cover - the raise is the assertion
            pass
    with pytest.raises(TypeError):
        not verdict


def test_exit_codes_are_three_distinct_values(vr):
    """A gate that greps for a specific code has to be able to tell them apart."""
    assert vr.EXIT_OK == 0
    assert vr.EXIT_FAILED == 1
    assert vr.EXIT_INCONCLUSIVE == 2
    assert len({vr.EXIT_OK, vr.EXIT_FAILED, vr.EXIT_INCONCLUSIVE}) == 3


def test_neither_bad_verdict_exits_zero(vr):
    """INCONCLUSIVE is quieter than FAILED; it is never SILENT.

    Doctrine (CLAUDE.md): a receipt the harness cannot classify is a failure,
    never a skip. The same holds one level up -- a self-test that could not run
    has proved nothing, so `set -e` and `if rc:` gates must both still fire.
    """
    assert vr.EXIT_CODE[vr.Verdict.PASSED] == 0
    assert vr.EXIT_CODE[vr.Verdict.FAILED] != 0
    assert vr.EXIT_CODE[vr.Verdict.INCONCLUSIVE] != 0


def test_no_two_verdicts_share_a_severity(vr):
    """`worse()` is `max(..., key=...)`, which returns the FIRST maximal element.

    That makes a tie silently order-dependent: with INCONCLUSIVE and FAILED at
    equal severity, `worse(INCONCLUSIVE, FAILED)` returns INCONCLUSIVE and a real
    failure exits 2. Mutant M16 is exactly that, and it was only caught because
    the ranking test happens to assert both argument orders -- nothing pinned the
    property the tie-break depends on. This does.
    """
    assert len(set(vr._SEVERITY.values())) == len(vr.Verdict), \
        f"two verdicts share a severity, so worse() is order-dependent: {vr._SEVERITY}"
    assert set(vr._SEVERITY) == set(vr.Verdict), \
        "every verdict must be rankable, or worse() raises KeyError at runtime"


def test_failed_outranks_inconclusive_outranks_passed(vr):
    """The accumulator's whole job: the worst verdict seen must win."""
    V = vr.Verdict
    assert vr.worse(V.PASSED, V.INCONCLUSIVE) is V.INCONCLUSIVE
    assert vr.worse(V.INCONCLUSIVE, V.PASSED) is V.INCONCLUSIVE
    assert vr.worse(V.INCONCLUSIVE, V.FAILED) is V.FAILED
    assert vr.worse(V.FAILED, V.INCONCLUSIVE) is V.FAILED
    assert vr.worse(V.PASSED, V.FAILED) is V.FAILED
    assert vr.worse(V.PASSED, V.PASSED) is V.PASSED


# ---------------------------------------------------------------------------
# `_extraction_seed` -- the innermost of the four functions. Returning `False`
# here for an INCONCLUSIVE seed poisoned the `ok` accumulator in
# `self_test_extraction`, which is why a fix confined to `main()` cannot work.
# ---------------------------------------------------------------------------

def test_extraction_seed_passes_when_the_seed_is_caught(vr):
    unfenced = "# live: x\n$ echo seeded\nseeded\n"
    assert vr._extraction_seed("fences removed", unfenced, before=1) is vr.Verdict.PASSED


def test_extraction_seed_that_removes_nothing_is_inconclusive(vr):
    """Was `False`, indistinguishable from a broken harness.

    Deleting a block's two fence lines re-pairs every later fence in the
    document, so in a multi-block document the parsed count can stay flat. The
    seed did not do what it intended; nothing is known to be wrong.
    """
    clean = GOOD + "$ loose command outside any fence\n"
    receipts, unclassified, _blocks = vr.parse(clean)
    before = len(receipts) + len(unclassified)
    assert before == 1 and vr.scan_evasions(clean), \
        "fixture must keep its receipt AND report an evasion, or this is vacuous"
    assert vr._extraction_seed("no-op", clean, before=before) is vr.Verdict.INCONCLUSIVE


def test_extraction_seed_that_reports_nothing_is_a_failure(vr):
    """Receipts stopped being parsed and NOTHING was reported. Still red."""
    assert vr._extraction_seed("no-evasion", GOOD, before=99) is vr.Verdict.FAILED


# ---------------------------------------------------------------------------
# `self_test_extraction`
# ---------------------------------------------------------------------------

def test_extraction_self_test_passes_on_a_clean_document(vr):
    assert vr.self_test_extraction(GOOD, REPO) is vr.Verdict.PASSED


def test_extraction_self_test_without_a_classified_block_is_inconclusive(vr):
    assert vr.self_test_extraction("just prose, no receipts here\n", REPO) \
        is vr.Verdict.INCONCLUSIVE


def test_extraction_self_test_on_a_document_that_already_evades_is_inconclusive(vr):
    """A seeded evasion proves nothing when an unseeded one is already reported.

    The document's own problem is `check(--strict)`'s to fail on, not the
    self-test's -- so this must not read as "the harness is broken".
    """
    doc = GOOD + "$ loose command outside any fence\n"
    assert vr.scan_evasions(doc), "fixture must carry an evasion or this is vacuous"
    assert vr.self_test_extraction(doc, REPO) is vr.Verdict.INCONCLUSIVE


def test_extraction_self_test_takes_the_worst_of_its_two_seeds(vr, monkeypatch):
    """Two seeds run; the verdict is the worse one, never the last one.

    `ok = seed1; ok = seed2 and ok` was a boolean AND. Its tri-state form must
    not let a PASSED second seed bury a FAILED first one -- which is exactly
    what `return seed2` or a plain overwrite would do.
    """
    V = vr.Verdict
    for first, second, expected in [
        (V.FAILED, V.PASSED, V.FAILED),
        (V.PASSED, V.FAILED, V.FAILED),
        (V.INCONCLUSIVE, V.PASSED, V.INCONCLUSIVE),
        (V.PASSED, V.INCONCLUSIVE, V.INCONCLUSIVE),
        (V.FAILED, V.INCONCLUSIVE, V.FAILED),
        (V.PASSED, V.PASSED, V.PASSED),
    ]:
        verdicts = iter((first, second))

        def fake_seed(name, seeded, before, _v=verdicts):
            return next(_v)

        monkeypatch.setattr(vr, "_extraction_seed", fake_seed)
        assert vr.self_test_extraction(GOOD, REPO) is expected, (first, second)


# ---------------------------------------------------------------------------
# `self_test`
# ---------------------------------------------------------------------------

def test_self_test_passes_on_a_clean_document(vr):
    assert vr.self_test(GOOD, REPO) is vr.Verdict.PASSED


def test_self_test_with_no_multi_word_receipt_is_inconclusive(vr):
    """The operator-facing case: a document offering nothing to paraphrase.

    This is the whole reason the task exists -- it used to exit 1, identical to
    a verifier that had proved itself broken.
    """
    assert vr.self_test(SINGLE_WORD, REPO) is vr.Verdict.INCONCLUSIVE


def test_self_test_reports_failure_when_a_seeded_paraphrase_is_not_caught(vr,
                                                                          monkeypatch):
    """A harness that cannot catch its own seed. Genuine failure, stays exit 1."""
    monkeypatch.setattr(vr, "check", lambda *a, **k: (1, [], []))
    assert vr.self_test(GOOD, REPO) is vr.Verdict.FAILED


def test_self_test_reports_failure_when_the_seeded_receipt_fails_unmutated(vr,
                                                                           monkeypatch):
    """The catch was for the wrong reason, so the proof is void.

    Reachable for real on a non-deterministic receipt: it reproduced during
    target selection and did not reproduce on the clean re-check. Injected here
    rather than seeded with a flaky command, so the pin itself is deterministic.
    """
    receipts, _u, _b = vr.parse(GOOD)
    target = receipts[0]

    def always_fails(text, root, **kw):
        return (1, [(target, ["injected"])], [])

    monkeypatch.setattr(vr, "check", always_fails)
    assert vr.self_test(GOOD, REPO) is vr.Verdict.FAILED


def test_self_test_reports_failure_when_the_expected_line_cannot_be_located(vr,
                                                                           monkeypatch):
    """RECLASSIFIED from INCONCLUSIVE (brief's `:761`). Argued from the code.

    `_parse_block` appends expected lines VERBATIM, and `r.line` is the 1-based
    document line of that receipt's own `$ ` line, so the 0-based search
    `doc_lines[r.line:]` starts exactly on the receipt's first expected line.
    Parser and mutator both call `text.splitlines()` on the same `text`. The
    line is therefore always findable, and this guard can only fire when the
    harness's own line accounting is wrong -- which is something KNOWN to be
    wrong, not something unknown. Injected by giving the receipt a line number
    the document does not have.
    """
    receipts, unclassified, blocks = vr.parse(GOOD)
    receipts[0].line = 9999
    monkeypatch.setattr(vr, "parse", lambda text: (receipts, unclassified, blocks))
    assert vr.self_test(GOOD, REPO) is vr.Verdict.FAILED


def test_self_test_returns_the_extraction_verdict_not_its_own(vr, monkeypatch):
    """`self_test` ends `return self_test_extraction(...)`, and must keep doing so.

    The bool-era pin (`tests/test_receipts.py::test_self_test_chains_into_extraction`)
    could only distinguish two outcomes. All three have to survive the chain, or
    a PASSED paraphrase seed would launder an INCONCLUSIVE extraction seed into
    a green run.
    """
    for verdict in (vr.Verdict.PASSED, vr.Verdict.INCONCLUSIVE, vr.Verdict.FAILED):
        called = []

        def spy(text, root, _v=verdict):
            called.append(text)
            return _v

        monkeypatch.setattr(vr, "self_test_extraction", spy)
        assert vr.self_test(GOOD, REPO) is verdict
        assert called, "self_test() did not chain into self_test_extraction()"


# ---------------------------------------------------------------------------
# `main` -- where the tri-state becomes an exit code.
# ---------------------------------------------------------------------------

def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_main_exits_zero_on_a_clean_document(vr, tmp_path, capsys):
    rc = vr.main([_write(tmp_path, "good.md", GOOD), "--root", str(REPO),
                  "--self-test"])
    assert rc == vr.EXIT_OK, capsys.readouterr().out


def test_main_exits_inconclusive_not_failed_when_the_self_test_cannot_run(
        vr, tmp_path, capsys):
    """THE fix, end to end. Was 1, indistinguishable from a broken verifier."""
    rc = vr.main([_write(tmp_path, "single.md", SINGLE_WORD), "--root", str(REPO),
                  "--self-test"])
    out = capsys.readouterr().out
    assert rc == vr.EXIT_INCONCLUSIVE, out
    assert "INCONCLUSIVE" in out


def test_main_still_exits_failed_when_the_self_test_genuinely_fails(
        vr, tmp_path, monkeypatch, capsys):
    """The over-quiet bug, pinned. A FAILED self-test must never soften to 2."""
    monkeypatch.setattr(vr, "self_test", lambda text, root: vr.Verdict.FAILED)
    rc = vr.main([_write(tmp_path, "good.md", GOOD), "--root", str(REPO),
                  "--self-test"])
    assert rc == vr.EXIT_FAILED, capsys.readouterr().out


@pytest.mark.parametrize("verdict_name,expected_code", [
    ("PASSED", "EXIT_OK"),
    ("INCONCLUSIVE", "EXIT_INCONCLUSIVE"),
    ("FAILED", "EXIT_FAILED"),
])
def test_main_maps_every_self_test_verdict_to_its_own_exit_code(
        vr, tmp_path, monkeypatch, verdict_name, expected_code, capsys):
    monkeypatch.setattr(vr, "self_test",
                        lambda text, root: getattr(vr.Verdict, verdict_name))
    rc = vr.main([_write(tmp_path, "good.md", GOOD), "--root", str(REPO),
                  "--self-test"])
    assert rc == getattr(vr, expected_code), capsys.readouterr().out


def test_a_failing_receipt_still_fails_the_run_without_the_self_test(
        vr, tmp_path, capsys):
    """`check()`'s own verdict is untouched by any of this."""
    rc = vr.main([_write(tmp_path, "false.md", FALSE_RECEIPT), "--root", str(REPO)])
    assert rc == vr.EXIT_FAILED, capsys.readouterr().out


def test_an_inconclusive_self_test_cannot_mask_a_real_receipt_failure(
        vr, tmp_path, capsys):
    """The dominance rule, and the single most important pin in this file.

    `FALSE_RECEIPT` does not reproduce, so it is not eligible as a seed target
    and the self-test is INCONCLUSIVE -- while `check()` fails on it. If
    INCONCLUSIVE were allowed to win, a document with a flatly false receipt
    would exit 2 and every `rc == 1` gate would read it as "not a failure".
    """
    path = _write(tmp_path, "false.md", FALSE_RECEIPT)
    assert vr.self_test(FALSE_RECEIPT, REPO) is vr.Verdict.INCONCLUSIVE, \
        "fixture must produce an INCONCLUSIVE self-test or this is vacuous"
    rc = vr.main([path, "--root", str(REPO), "--self-test"])
    assert rc == vr.EXIT_FAILED, capsys.readouterr().out


def test_the_worst_verdict_across_several_documents_wins(vr, tmp_path, capsys):
    """A clean file listed after a broken one must not lower the exit code."""
    inconclusive = _write(tmp_path, "single.md", SINGLE_WORD)
    good = _write(tmp_path, "good.md", GOOD)
    false = _write(tmp_path, "false.md", FALSE_RECEIPT)

    rc = vr.main([inconclusive, good, "--root", str(REPO), "--self-test"])
    assert rc == vr.EXIT_INCONCLUSIVE, capsys.readouterr().out

    rc = vr.main([false, good, "--root", str(REPO), "--self-test"])
    assert rc == vr.EXIT_FAILED, capsys.readouterr().out

    rc = vr.main([good, false, "--root", str(REPO), "--self-test"])
    assert rc == vr.EXIT_FAILED, capsys.readouterr().out


def test_main_names_the_verdict_it_exited_on(vr, tmp_path, capsys):
    """An exit code nobody can read is a number, not a diagnosis."""
    vr.main([_write(tmp_path, "single.md", SINGLE_WORD), "--root", str(REPO),
             "--self-test"])
    out = capsys.readouterr().out
    assert "SELF-TEST VERDICT" in out
    assert f"EXIT:            {vr.EXIT_INCONCLUSIVE} (INCONCLUSIVE)" in out


def test_main_names_which_accumulator_produced_a_failure(vr, tmp_path, capsys):
    """The genuinely confusing shape, found by reading this diff adversarially.

    A document whose self-test is INCONCLUSIVE and whose receipts also fail
    prints `SELF-TEST VERDICT: INCONCLUSIVE` immediately above `EXIT: 1
    (FAILED)`. The exit is correct -- dominance is what produces it -- but
    nothing on the page said WHICH accumulator produced the 1, so the only
    reading available to an operator was to guess. Now it is named.

    The FIRST version of this test asserted only the RECEIPT half of that line,
    so mutant M21 -- never name the self-test cause -- survived the whole suite.
    A pin written against the mechanism you just fixed misses the one you just
    introduced. Both arms are asserted now, and each is asserted in a case where
    the OTHER is absent, so neither can carry the other.
    """
    vr.main([_write(tmp_path, "false.md", FALSE_RECEIPT), "--root", str(REPO),
             "--self-test"])
    both = capsys.readouterr().out
    assert "SELF-TEST VERDICT: INCONCLUSIVE" in both
    assert "receipt failure(s)" in both, both
    assert "self-test INCONCLUSIVE" in both, both
    assert f"EXIT:            {vr.EXIT_FAILED} (FAILED)" in both, both

    # Self-test cause ALONE: receipts are fine, only the seed could not run.
    vr.main([_write(tmp_path, "single.md", SINGLE_WORD), "--root", str(REPO),
             "--self-test"])
    solo = capsys.readouterr().out
    assert "self-test INCONCLUSIVE" in solo, solo
    assert "receipt failure(s)" not in solo, solo

    # Receipt cause ALONE: no --self-test, so the self-test names nothing.
    vr.main([_write(tmp_path, "false.md", FALSE_RECEIPT), "--root", str(REPO)])
    receipts_only = capsys.readouterr().out
    assert "receipt failure(s)" in receipts_only, receipts_only
    assert "self-test" not in receipts_only, receipts_only

    # ...and a clean run says nothing about causes it does not have.
    vr.main([_write(tmp_path, "good.md", GOOD), "--root", str(REPO), "--self-test"])
    clean = capsys.readouterr().out
    assert "receipt failure(s)" not in clean
    assert "-- from" not in clean, clean
    assert f"EXIT:            {vr.EXIT_OK} (PASSED)" in clean, clean


# ---------------------------------------------------------------------------
# The source-level census.
#
# `:766` ("mutation did not change the document") is UNREACHABLE by
# construction: reaching the mutation requires `line.strip()` and
# `len(line.split()) > 1`, so `line.split(" ")` holds at least one word with
# `w.strip()` truthy, and both mutation arms (`w + "X"`, `"PARAPHRASED"`) always
# change that word. No input can drive it, so no behavioural pin can hold it --
# and a label nothing holds is a label a refactor silently flips. This census
# holds all nine sites at once, including that one.
# ---------------------------------------------------------------------------

# message substring -> the verdict that site must return
GUARD_CENSUS = {
    "no clean multi-word receipt to mutate": "INCONCLUSIVE",
    "could not locate the expected line to seed": "FAILED",
    "mutation did not change the document": "FAILED",
    "did not catch a seeded paraphrase": "FAILED",
    "the seeded receipt also fails unmutated": "FAILED",
    "the seed removed no receipt": "INCONCLUSIVE",
    "stopped being parsed": "FAILED",
    "no classified fenced block to seed": "INCONCLUSIVE",
    "already carries an": "INCONCLUSIVE",
}

GUARDED_FUNCTIONS = ("self_test", "self_test_extraction", "_extraction_seed")


def _printed_text(node):
    """Every string constant reachable inside one `print(...)` call."""
    return "".join(
        n.value for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str))


def _collect(body, last_msg, out):
    for stmt in body:
        if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "print"):
            last_msg = _printed_text(stmt.value)
        elif isinstance(stmt, ast.Return):
            value = stmt.value
            if (isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "Verdict"):
                out.append((last_msg, value.attr))
        for field in ("body", "orelse", "finalbody"):
            inner = getattr(stmt, field, None)
            if isinstance(inner, list):
                _collect(inner, last_msg, out)
    return out


@pytest.fixture(scope="module")
def guard_sites():
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in GUARDED_FUNCTIONS:
            _collect(node.body, "", sites)
    return sites


def test_the_census_can_see_the_guards(guard_sites):
    """Non-vacuity: a walker that finds nothing would agree with everything."""
    assert len(guard_sites) >= len(GUARD_CENSUS), \
        f"the AST walk found {len(guard_sites)} `return Verdict.*` site(s): {guard_sites}"


@pytest.mark.parametrize("needle", sorted(GUARD_CENSUS), ids=lambda s: s[:34])
def test_every_guard_returns_its_declared_verdict(guard_sites, needle):
    """Each printed diagnosis must be followed by the verdict it claims to be.

    A site that prints INCONCLUSIVE and returns `Verdict.FAILED` (or the
    reverse) is a lie the exit code repeats.
    """
    matches = [attr for msg, attr in guard_sites if needle in msg]
    assert matches, f"no `return Verdict.*` guard prints {needle!r}"
    expected = GUARD_CENSUS[needle]
    assert set(matches) == {expected}, \
        f"{needle!r} returns {sorted(set(matches))}, declared {expected}"


def test_no_guard_returns_a_bare_bool(guard_sites):
    """The bug, pinned at the source. A `return False` here is the old collapse."""
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in GUARDED_FUNCTIONS:
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Return)
                        and isinstance(inner.value, ast.Constant)
                        and isinstance(inner.value.value, bool)):
                    offenders.append((node.name, inner.lineno))
    assert not offenders, (
        f"bare bool returned from a tri-state function: {offenders}. That is the "
        f"collapse this slice removed -- `main()` cannot tell the two apart again.")
