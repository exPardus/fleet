"""TASK 8 -- a detector for the class *"`load_registry` is not a read"*.

FIVE INDEPENDENT FINDINGS EARNED A DETECTOR RATHER THAN A SIXTH FIX. Three
agents found it in the previous wave, `gate-arm`'s `_registry_records_or_none`
docstring found it a fourth time and says so in prose, and the break lens found
it again in this one. `load_registry`'s own docstring has said it all along:

    corrupt/unreadable file is quarantined (renamed aside) and raises
    RegistryCorruptError -- callers must abort, not catch-and-continue.

The rename is a WRITE. Every recurrence has the same shape: a function that
documents itself as read-only calls `load_registry`, wraps it in
`except RegistryCorruptError`, and thereby destroys operator evidence on a path
that promises to touch nothing. This file enumerates the call sites OUT OF THE
SOURCE so a new one cannot be added silently.

IT EARNED ITS KEEP BEFORE IT SHIPPED, which is the argument for the shape. The
first run flagged `_caller_holds_supervisor_claim` -- *"Read-only, never raises:
it runs on the dispatch hot path"* -- catching `RegistryCorruptError` around
`load_registry` on the 200k ceiling path. That site was in neither review and
not in the fix wave's brief; it is the sixth finding of the class and the first
one a harness found rather than a person.

WHAT THIS FILE CAN AND CANNOT DECIDE, stated because the brief asked for the
honest answer rather than an approximated one. The brief's proposed assertion
was *"each call site is an allowlisted mutating-under-lock site"*.
**"Mutating-under-lock" is NOT decidable from the source** and the allowlist
below is therefore drawn differently:

  * `fleet_lock()` is taken by the CALLER, often several frames up (`cmd_kill`
    -> `_cmd_kill_native`), and sometimes conditionally. Deciding lock-holding
    from the text of the file would need an interprocedural analysis, and one
    that is wrong in the unsafe direction whenever it guesses.
  * Several sites genuinely READ under `load_registry` and are correct to:
    `cmd_wait` is a CLI verb that persists the transitions it observes, and
    quarantining a corrupt registry from a verb that is about to write is the
    designed behaviour. So "non-mutating => forbidden" would be false.

    **THAT PARAGRAPH USED TO NAME FOUR MORE VERBS, AND IT WAS WRONG ABOUT ALL
    FOUR.** It read: *"`cmd_status`, `cmd_peek`, `cmd_result`, `cmd_wait` are
    CLI verbs, NOT THE VIEW SURFACE"*. Measured 2026-07-27 in an isolated
    `FLEET_HOME`: `fleet status`, `fleet peek`, `fleet result` and `fleet
    doctor` each renamed a corrupt `state/fleet.json` aside -- and
    `commands/status.md`, `commands/peek.md`, `commands/result.md` and
    `commands/overview.md` inline-exec exactly those bare verbs, so `/fleet:*`,
    the surface `docs/specs/terminal-surface.md` D4 names by name, WAS the
    surface doing the writing. The allowlist did not merely fail to catch it;
    its own rationale asserted the thing that was false. An allowlist entry is
    a claim, and this one went unchecked for as long as the prose above it did.
    `TestTheViewSurfaceIsNotAmongTheCallers` is the pin that makes the return
    of any of the four loud rather than merely unallowlisted.

So the decidable, load-bearing assertion is the ALLOWLIST ITSELF: the set of
SCOPES that call `load_registry` -- top-level functions, class methods, class
bodies and module level, through the name or a module-level alias of it -- is
pinned by name. Adding a call from a new one is then a deliberate one-line edit
with a reviewer looking at it, which is the whole property the five findings
wanted. `tests/test_identity_fixwave.py` is the behavioural companion that
catches the same class from the outside.

**IT IS NOT TOTAL, and fix wave 2 made it say so.** The confirmation review
confirmed four evasions by planting real calls. Three were static and are now
closed (`TestTheDetectorCannotBeWalkedAround`). The fourth --
`getattr(sys.modules[__name__], 'load_registry')()` -- is not statically
decidable and never will be; `_callers`'s docstring states that limit rather
than implying totality, because a detector a plausible refactor evades trains
its reader to ignore it.
"""
import ast
from pathlib import Path

import fleet


SRC = Path(fleet.__file__).read_text(encoding="utf-8")

# The enumeration is an AST walk, not a regex over the text, and that is a
# correction this file made to itself on its first run: a grep for
# `load_registry(` matched the PROSE in `_caller_holds_supervisor_claim`'s new
# docstring -- which describes the call it no longer makes -- and reported the
# site it had just been used to fix. A detector that cannot tell a call from a
# sentence about a call is a detector that trains its reader to ignore it.


def _alias_names(tree) -> set:
    """Every module-level name bound to `load_registry`, itself included.

    `_read = load_registry` at module level defeats a by-name matcher
    completely -- nothing downstream mentions the forbidden name at all -- and
    the confirmation review confirmed the evasion by planting one. Resolved as
    a FIXPOINT so that `b = a; a = load_registry` (or any chain) cannot buy
    what a single hop cannot."""
    names = {"load_registry"}
    changed = True
    while changed:
        changed = False
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Name) and node.value.id in names):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def _callers(source: str = SRC) -> dict:
    """{enclosing SCOPE name: [line numbers]} for every real call to
    `load_registry` or a module-level alias of it. Comments, docstrings and the
    `def` itself cannot appear: only `ast.Call` nodes count.

    SCOPE NAMES. A top-level function is its own name. A method is
    `Class.method`, a nested class `Outer.Inner.method`, a class body
    `Class.<class body>`, and a call at module level (including under an `if`)
    is `<module>` -- a name no allowlist entry can accidentally already carry,
    so an evasion surfaces as an offender rather than being silently permitted.

    Attribution within a function is to the OUTERMOST enclosing function on
    purpose. Several verbs do their registry work in a nested
    `_commit()`/`_commit_native_stamp()` closure called inside
    `with fleet_lock():` in the parent; the question the allowlist answers is
    "which SURFACE may quarantine", and that is the parent's name, not a
    closure's.

    WHAT THIS CANNOT DECIDE, said plainly rather than implied away (fix wave 2,
    MINOR 3). Dispatch through `getattr` --
    `getattr(sys.modules[__name__], 'load_registry')()` -- is **not statically
    decidable** and no walk of this shape will ever catch it; the name exists
    only as a string at runtime. This walk closes the three STATIC evasions the
    confirmation review confirmed by planting real calls (a call in a class
    method, a module-level alias, and a module-level call under an `if`) and
    claims nothing beyond them. The file's earlier scope line -- *"the set of
    functions that call `load_registry` is pinned by name"* -- read as total
    and was not, and a detector a plausible refactor evades trains its reader
    to ignore it."""
    tree = ast.parse(source)
    aliases = _alias_names(tree)
    found = {}

    def record(scope, node):
        lines = sorted({n.lineno for n in ast.walk(node)
                        if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name)
                        and n.func.id in aliases})
        if lines:
            found[scope] = sorted(set(found.get(scope, [])) | set(lines))

    def scan(body, prefix):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not prefix and node.name == "load_registry":
                    continue            # the definition itself
                record(prefix + node.name, node)
            elif isinstance(node, ast.ClassDef):
                for extra in (list(node.decorator_list) + list(node.bases)
                              + list(node.keywords)):
                    record((prefix + "<class body>") if prefix else "<module>",
                           extra)
                scan(node.body, prefix + node.name + ".")
            else:
                record((prefix + "<class body>") if prefix else "<module>", node)

    scan(tree.body, "")
    return found


# Every function permitted to call `load_registry`. Each entry is a verb or a
# helper that runs UNDER `fleet_lock()` on behalf of one, or a CLI verb the
# operator invoked directly and which is therefore entitled to quarantine.
#
# TO ADD AN ENTRY: satisfy yourself that quarantining a corrupt registry from
# this path is correct. If the function documents itself as read-only, or runs
# on a hot path, or is reached from a view, the answer is no and the fix is
# `_registry_records_or_none()` / `_read_registry_readonly()` instead.
ALLOWED = {
    # --- lifecycle verbs and their native halves: mutate under the lock ---
    "cmd_spawn", "cmd_send", "_cmd_send_native", "cmd_kill", "_cmd_kill_native",
    "cmd_respawn", "_cmd_respawn_native", "cmd_interrupt", "_cmd_interrupt_native",
    "cmd_attach", "cmd_release", "cmd_clean", "cmd_archive",
    "cmd_resume_limited", "_resume_one_limited", "_resume_one_limited_native",
    "_sweep_husks", "_expire_tombstones",
    # --- supervisor lifecycle: all inside `fleet_lock()` ---
    "cmd_sup_handoff_begin", "cmd_sup_handoff_complete", "_dispatch_supervisor_body",
    "_cmd_respawn_supervisor",
    # `_supervisor_gate` WAS HERE, and it was the seventh instance of the very
    # class this file exists to stop (fix wave 2, MAJOR 1). It was listed under
    # "all inside `fleet_lock()`", which is false -- it takes no lock and its
    # docstring says "READ-ONLY: no lock, no mint, no write" -- and it is on the
    # hot path of every mutating verb, so BOTH of the admission rule's
    # disqualifiers applied at the entry. The call now goes through
    # `_registry_records_or_none`. A detector shipping with a live defect
    # blessed, for a stated reason that was not true, is worse than no detector.
    # `_supervisor_lifecycle_target`, `_resolve_supervisor_lifecycle_target` and
    # `_refetch_holder_record` WERE HERE, and they were three more instances of
    # the class this file exists to stop (P1-6, 2026-07-30). All three sat under
    # the "all inside `fleet_lock()`" heading, and for all three that was FALSE:
    # the first two are
    # the PRE-FLIGHT holder lookup `cmd_kill`/`cmd_respawn` run at `:6488`/`:6230`
    # -- before either verb takes the lock -- and the third is called from
    # `_cmd_kill_supervisor`/`_cmd_respawn_supervisor`, neither of which holds it
    # either. Measured: `fleet kill w1` over a corrupt registry RENAMED
    # `state/fleet.json` aside from the unlocked read and then reported
    # `unknown worker: 'w1'`, stderr byte-identical to a genuinely mistyped name
    # against a healthy registry. All three now read via
    # `read_registry_no_repair`; `tests/test_unlocked_quarantine.py` is the
    # behavioural pin and also pins the LOCK axis this file declines to decide.
    #
    # This is the second heading in this file whose stated rationale was the
    # thing that was false (see `_supervisor_gate` above). An allowlist entry is
    # a claim, and grouping three entries under one unchecked sentence is how
    # three of them shipped at once.
    #
    # `_holder_is_limited` SURVIVES the same audit, and its reason is written here
    # rather than left to inherit the heading above -- inheriting a heading is
    # precisely what the paragraph above is about. It is NOT lexically inside
    # `fleet_lock()`; it is lock-held by its ONE caller, `cmd_sup_boot`, whose
    # `with fleet_lock():` block encloses the call.
    # `tests/test_unlocked_quarantine.py::test_holder_is_limited_really_is_lock_held_by_its_caller`
    # re-derives that from the AST on every run, so the entry stops being a claim
    # nobody checks the moment the call moves out of the block.
    "_holder_is_limited",
    # `_resolve_worker_target` WAS HERE. It is a PRE-FLIGHT NAME LOOKUP that runs
    # at the top of every verb -- the three views included -- before any of them
    # has taken the lock, so it carried the same disqualifier `_supervisor_gate`
    # did. It hid behind the short-circuit at `bin/fleet.py:2414`: the measured
    # table was driven with an ordinary worker name, which returns before the
    # read, so `fleet peek supervisor` was quarantining from a path the table
    # showed as clean. It now reads via `read_registry_no_repair`; the mutating
    # verbs that call it still quarantine at their own lock-held load.
    # --- CLI verbs that persist what they observe ---
    "cmd_wait", "wait_for_workers",
    # `cmd_status` keeps ONE call, and it is the merge read inside
    # `with fleet_lock():` immediately before `save_registry` -- a genuine
    # mutating-under-lock site, which is the admission rule as written.
    # terminal-surface D2 is why it is still here at all: *"`fleet status` (no
    # flag) remains the authoritative, recomputing command."* Its PRE-PROBE read
    # is now `read_registry_no_repair`, and since that one always runs first, a
    # corrupt registry refuses before this call is ever reached.
    # `TestTheViewSurfaceIsNotAmongTheCallers` pins both halves.
    "cmd_status",
    # `cmd_doctor` keeps ONE call, on the `--repair` branch only, under
    # `fleet_lock`. After the 2026-07-27 gate that call IS the quarantine
    # surface: the operator typed the flag, which is the entire point of the
    # flag. Default `doctor` reads through `read_registry_no_repair` and reports.
    "cmd_doctor",
    # `cmd_peek` and `cmd_result` WERE HERE and are gone. Neither writes, neither
    # locks, and each reads exactly one field.
}


class TestLoadRegistryCallSites:

    def test_the_matcher_finds_call_sites_at_all(self):
        """The seed check, and it is not optional: a regex that matches nothing
        would make every assertion below pass VACUOUSLY, which is precisely the
        failure mode `tools/verify_receipts.py --self-test` exists for. If this
        goes red, the matcher rotted -- not the code."""
        callers = _callers()
        assert len(callers) >= 20, (
            f"only {len(callers)} `load_registry` callers found -- the matcher "
            f"rotted, and every assertion in this file was about to pass "
            f"vacuously")

    def test_the_matcher_finds_a_planted_call_and_ignores_prose(self):
        """The other half of the seed check, and the regression for this file's
        own first-run defect. Every realistic call spelling must be FOUND, and
        a docstring that merely talks about `load_registry()` must not be."""
        planted = ast.parse(
            "def a():\n"
            "    data = load_registry()\n"
            "def b():\n"
            "    reg = load_registry()['workers']\n"
            "def c():\n"
            "    rec = load_registry().get('workers', {}).get(name)\n"
            "def prose():\n"
            "    '''It used to call load_registry() here. It does not now.'''\n"
            "    return _registry_records_or_none()  # load_registry() is a write\n")
        found = _callers(ast.unparse(planted))
        assert sorted(found) == ["a", "b", "c"], found

    def test_a_nested_closure_is_attributed_to_its_OUTERMOST_function(self):
        """The attribution rule, pinned rather than assumed. Several verbs do
        their registry work in a nested `_commit()` called inside
        `with fleet_lock():`, and the question the allowlist answers is *"which
        SURFACE may quarantine"* -- which is the verb's name, not a closure's."""
        planted = ast.parse(
            "def cmd_thing():\n"
            "    def _commit():\n"
            "        return load_registry()\n"
            "    return _commit()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["cmd_thing"]


class TestTheDetectorCannotBeWalkedAround:
    """MINOR 3 -- four evasions the confirmation review CONFIRMED by planting
    real calls and running this file alone. `_callers()` walked only top-level
    `FunctionDef`/`AsyncFunctionDef` in `tree.body`, so a call in a class
    method, at module level, or through an alias was invisible while the file
    described its scope as *"the set of functions that call `load_registry` is
    pinned by name"* -- which reads as total and was not.

    *A detector a plausible refactor evades trains its reader to ignore it* was
    this suite's own sentence one wave ago, and it applies to the suite."""

    def test_a_call_inside_a_CLASS_METHOD_is_found(self):
        """Evasion D2, and the most plausible of the four: `bin/fleet.py` is
        stdlib-only and single-file, and a helper class is the ordinary way
        that file grows."""
        planted = ast.parse(
            "class Reader:\n"
            "    def read(self):\n"
            "        return load_registry()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["Reader.read"]

    def test_a_call_in_a_NESTED_class_is_found(self):
        planted = ast.parse(
            "class Outer:\n"
            "    class Inner:\n"
            "        def read(self):\n"
            "            return load_registry()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["Outer.Inner.read"]

    def test_a_MODULE_LEVEL_ALIAS_is_resolved(self):
        """Evasion D3. The alias is the one that defeats a by-name matcher
        completely: after `_read = load_registry`, nothing downstream mentions
        the forbidden name at all."""
        planted = ast.parse(
            "_read = load_registry\n"
            "def peek():\n"
            "    return _read()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["peek"]

    def test_a_CHAINED_alias_is_resolved(self):
        """One hop is not the interesting number; the resolution is a fixpoint
        so that two hops cannot buy what one cannot."""
        planted = ast.parse(
            "_read = load_registry\n"
            "_read2 = _read\n"
            "def peek():\n"
            "    return _read2()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["peek"]

    def test_a_MODULE_LEVEL_call_under_an_if_is_found(self):
        """Evasion D5. Attributed to `<module>`, which is a name no allowlist
        entry can accidentally already carry -- so it surfaces as an offender
        rather than being silently permitted."""
        planted = ast.parse(
            "if True:\n"
            "    CACHE = load_registry()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["<module>"]

    def test_a_call_in_a_class_BODY_is_found(self):
        planted = ast.parse(
            "class Reader:\n"
            "    CACHE = load_registry()\n")
        assert sorted(_callers(ast.unparse(planted))) == ["Reader.<class body>"]

    def test_getattr_dispatch_is_UNDECIDABLE_and_the_docstring_says_so(self):
        """Evasion D4 is NOT closed, and this pins the honesty rather than the
        capability. `getattr(sys.modules[__name__], 'load_registry')()` is not
        statically decidable and no walk of this shape will ever catch it; the
        remedy the brief ordered is to SAY so instead of implying totality."""
        planted = ast.parse(
            "def sneaky():\n"
            "    return getattr(sys.modules[__name__], 'load_registry')()\n")
        assert _callers(ast.unparse(planted)) == {}
        # Whitespace-normalised: a docstring's honesty must not be hostage to
        # where the line happened to wrap.
        doc = " ".join(_callers.__doc__.split())
        assert "getattr" in doc
        assert "not statically decidable" in doc

    def test_the_evasions_are_offenders_against_the_REAL_allowlist(self):
        """The walk finding them is only half of it: the assertion has to
        REJECT them. Each planted evasion is checked against the shipped
        `ALLOWED` set exactly as `test_no_unallowlisted...` does."""
        for source in (
                "class Reader:\n    def read(self):\n        return load_registry()\n",
                "_read = load_registry\ndef peek():\n    return _read()\n",
                "if True:\n    CACHE = load_registry()\n"):
            callers = _callers(ast.unparse(ast.parse(source)))
            assert {n: v for n, v in callers.items() if n not in ALLOWED} != {}, (
                f"an evasion was allowlisted by accident: {source!r}")

    def test_no_unallowlisted_function_calls_load_registry(self):
        """THE DETECTOR. A new non-mutating reader cannot be added silently.

        The remedy when this goes red is almost never "add the name": it is
        `_registry_records_or_none()` (records-or-None) or
        `_read_registry_readonly()` ((ok, reason, data)) -- both of which
        *"never write, never quarantine, never raise"*."""
        callers = _callers()
        offenders = {n: lines for n, lines in callers.items() if n not in ALLOWED}
        assert offenders == {}, (
            f"function(s) calling `load_registry` without being allowlisted: "
            f"{ {n: v for n, v in sorted(offenders.items())} }. `load_registry` "
            f"QUARANTINES a corrupt registry -- it renames the file aside, which "
            f"is a WRITE. If this path is a read, use `_registry_records_or_none` "
            f"or `_read_registry_readonly`. If it genuinely mutates under "
            f"`fleet_lock()`, add it to ALLOWED with that reasoning.")

    def test_the_allowlist_has_no_dead_entries(self):
        """The direction that keeps the list honest. An entry for a function
        that no longer calls `load_registry` is a permission nobody is using
        and the next reader would take it as evidence that the call is fine."""
        callers = _callers()
        dead = sorted(ALLOWED - set(callers))
        assert dead == [], (
            f"allowlisted functions that no longer call `load_registry`: {dead} "
            f"-- delete the entries rather than leaving standing permission")

    def test_the_view_surface_is_not_among_the_callers(self):
        """THE PIN THE DOCTRINE NEVER HAD. `docs/specs/terminal-surface.md` D4
        and root `CLAUDE.md` have both said for days that views *"never
        quarantine a corrupt registry"*, while `fleet status`, `fleet peek`,
        `fleet result` and `fleet doctor` all did -- measured 2026-07-27. Prose
        is therefore PROVEN not to be a guard on this surface, and a sentence
        that has been false for days is worse than no sentence, because every
        reader downstream of it built on it.

        Named individually rather than left to the allowlist so a revert is
        LOUD: `test_no_unallowlisted_function_calls_load_registry` would also
        catch it, but it reports a generic offender, and the next reader's first
        instinct on that failure is to add the name back to `ALLOWED` -- which
        is exactly how these four got their standing permission."""
        callers = _callers()
        for name in ("cmd_peek", "cmd_result", "_resolve_worker_target"):
            assert name not in callers, (
                f"{name} calls `load_registry` again. It is on the VIEW surface: "
                f"`commands/{name.replace('cmd_', '')}.md` and `/fleet:*` "
                f"inline-exec it with no permission prompt, and `load_registry` "
                f"RENAMES a corrupt `state/fleet.json` aside -- destroying the "
                f"operator evidence, and converting *corrupt* into *absent*, "
                f"which the §9 legacy-claim upgrade grants on. Use "
                f"`read_registry_no_repair` (raises, never renames) or "
                f"`_read_registry_readonly` (never raises).")

    def test_cmd_status_quarantines_ONLY_under_the_lock(self):
        """`cmd_status` stays allowlisted (terminal-surface D2 keeps it the
        authoritative recomputing verb), so the allowlist alone cannot say
        whether its pre-probe read came back. This can: the ONE surviving call
        must be lexically inside a `with fleet_lock():` block.

        Without this, moving `read_registry_no_repair` back to `load_registry`
        in the pre-probe read is a one-word edit that no test in this repo
        notices -- the name is already allowlisted."""
        tree = ast.parse(SRC)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "cmd_status")
        locked = {c.lineno for w in ast.walk(fn) if isinstance(w, ast.With)
                  for item in w.items
                  if isinstance(item.context_expr, ast.Call)
                  and isinstance(item.context_expr.func, ast.Name)
                  and item.context_expr.func.id == "fleet_lock"
                  for c in ast.walk(w)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "load_registry"}
        calls = set(_callers().get("cmd_status", []))
        assert calls, "cmd_status stopped calling load_registry entirely -- if " \
                      "that is intended, drop it from ALLOWED and delete this test"
        assert calls == locked, (
            f"cmd_status calls `load_registry` outside `with fleet_lock():` at "
            f"{sorted(calls - locked)}. The pre-probe read must be "
            f"`read_registry_no_repair`: it runs before the lock, on the path "
            f"`/fleet:status` used to inline-exec, and quarantining there is "
            f"what made a view a writer.")

    def test_cmd_doctor_quarantines_ONLY_behind_the_repair_flag(self):
        """Same shape, different guard. `cmd_doctor` keeps its `load_registry`
        call, but it must sit inside the `if repair:` arm -- otherwise the
        operator gate's whole answer (*"diagnose by default, quarantine behind
        `--repair`"*) is one dedent away from being undone silently."""
        tree = ast.parse(SRC)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "cmd_doctor")
        guarded = {c.lineno for w in ast.walk(fn) if isinstance(w, ast.If)
                   and isinstance(w.test, ast.Name) and w.test.id == "repair"
                   for c in ast.walk(w)
                   if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == "load_registry"}
        calls = set(_callers().get("cmd_doctor", []))
        assert calls, "cmd_doctor stopped calling load_registry entirely -- " \
                      "`--repair` is then the flag that repairs nothing"
        assert calls == guarded, (
            f"cmd_doctor calls `load_registry` outside `if repair:` at "
            f"{sorted(calls - guarded)}. Default `fleet doctor` must not "
            f"quarantine the registry it was invoked to diagnose.")

    def test_the_identity_surface_is_not_among_the_callers(self):
        """The three sites this fix wave moved OFF `load_registry`, named
        individually so a revert is loud rather than merely unallowlisted.

        `_acting_worker_identity` is the fix wave's Task 1; the other two are
        the same class found before and during it."""
        callers = _callers()
        for name in ("_acting_worker_identity", "_caller_holds_supervisor_claim",
                     "_registry_records_or_none"):
            assert name not in callers, (
                f"{name} calls `load_registry` again. It is an IDENTITY read on a "
                f"hot path: `_require_claim_holder`'s seven verbs and the 200k "
                f"ceiling both reach it, and the quarantine renames "
                f"`state/fleet.json` aside while reporting rc=0.")
