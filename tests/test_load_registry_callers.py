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
    `cmd_status`, `cmd_peek`, `cmd_result`, `cmd_wait` are CLI verbs, not the
    view surface, and quarantining a corrupt registry from a CLI verb the
    operator invoked directly is the designed behaviour (SPEC §12's view rule
    binds `status_snapshot` and the statusline, which use
    `_read_registry_readonly`). So "non-mutating => forbidden" would be false.

So the decidable, load-bearing assertion is the ALLOWLIST ITSELF: the set of
functions that call `load_registry` is pinned by name. Adding a call from a new
function is then a deliberate one-line edit with a reviewer looking at it, which
is the whole property the five findings wanted. `tests/test_identity_fixwave.py`
is the behavioural companion that catches the same class from the outside.
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


def _callers(source: str = SRC) -> dict:
    """{enclosing TOP-LEVEL function name: [line numbers]} for every real call
    to `load_registry`. Comments, docstrings and the `def` itself cannot
    appear: only `ast.Call` nodes count.

    Attribution is to the OUTERMOST enclosing function on purpose. Several
    verbs do their registry work in a nested `_commit()`/`_commit_native_stamp()`
    closure called inside `with fleet_lock():` in the parent; the question the
    allowlist answers is "which SURFACE may quarantine", and that is the
    parent's name, not a closure's."""
    tree = ast.parse(source)
    found = {}

    def calls_in(node):
        return sorted({n.lineno for n in ast.walk(node)
                       if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name)
                       and n.func.id == "load_registry"})

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "load_registry":
            continue
        lines = calls_in(node)
        if lines:
            found[node.name] = lines
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
    "_cmd_respawn_supervisor", "_resolve_supervisor_lifecycle_target",
    "_supervisor_lifecycle_target", "_refetch_holder_record", "_holder_is_limited",
    "_resolve_worker_target", "_supervisor_gate",
    # --- CLI verbs the operator invoked directly ---
    "cmd_status", "cmd_peek", "cmd_result", "cmd_wait", "wait_for_workers",
    "cmd_doctor",
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
