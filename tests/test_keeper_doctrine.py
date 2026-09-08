"""The keeper is a reader plus two tmux actions. These pins make the
spec's 'never dispatches, never locks' claim mechanical, and prove the
detector can see a violation by planting one."""
import ast
from pathlib import Path

import fleet
import fleet_keeper

SRC = Path(fleet_keeper.__file__).read_text(encoding="utf-8")

FORBIDDEN = {
    "dispatch_bg", "cmd_spawn", "cmd_sup_spawn", "_dispatch_supervisor_body",
    "cmd_send", "_cmd_send_native", "cmd_respawn", "_cmd_respawn_native",
    "fleet_lock", "load_registry", "cmd_kill", "cmd_clean", "cmd_archive",
    "cmd_autoclean", "cmd_init", "_quarantine_registry",
}


def _referenced_names(source):
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def test_the_keeper_references_no_dispatching_or_locking_name():
    hits = sorted(FORBIDDEN & _referenced_names(SRC))
    assert hits == [], (
        f"fleet_keeper.py references {hits}. The keeper pages; it never "
        "dispatches, locks, or repairs (spec §3.3, operator ruling 2026-09-08).")


def test_the_detector_sees_a_planted_dispatch():
    """The seed test for the pin above, and it must fail the SAME check that
    pin makes -- not merely prove that `_referenced_names` extracts a name.
    A detector whose extraction works while its comparison is vacuous passes
    the weaker form and catches nothing."""
    planted = SRC + "\n\ndef _mutant():\n    return fleet.dispatch_bg('x', '.', '', 'bypass')\n"
    hits = sorted(FORBIDDEN & _referenced_names(planted))
    assert hits == ["dispatch_bg"], (
        "the planted dispatch must FAIL the forbidden-name check that "
        "test_the_keeper_references_no_dispatching_or_locking_name runs")


def test_the_only_fleet_attributes_used_are_read_only_ones():
    """`FLEET_HOME` joined the set in fix wave 1 (I3): `main` compares the
    imported module's frozen home against `--fleet-home` and refuses a
    mismatch, because `status_snapshot()` reads the former while every other
    source reads the latter. It is a READ -- the test below pins that."""
    tree = ast.parse(SRC)
    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "fleet"}
    assert used <= {"status_snapshot", "MIN_PYTHON_VERSION", "FLEET_HOME"}, used


def _assigned_fleet_attributes(source):
    targets = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets.append(node.target)
    return {t.attr for t in targets
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
            and t.value.id == "fleet"}


def test_the_keeper_never_assigns_a_fleet_attribute():
    """The keeper READS `fleet.FLEET_HOME`; rebinding it would make this
    module a second definition of where the fleet lives, and would turn the
    I3 refusal into a silent redirection of `status_snapshot()`."""
    assert _assigned_fleet_attributes(SRC) == set()


def test_the_assignment_detector_sees_a_planted_rebind():
    planted = SRC + "\n\ndef _mutant(home):\n    fleet.FLEET_HOME = home\n"
    assert _assigned_fleet_attributes(planted) == {"FLEET_HOME"}


def test_the_only_writer_is_save_state():
    # Every open(..., 'w'|'x'|'a') / write_text / os.replace target in the
    # module is the keeper's own state file. Audited by name: the module
    # has exactly one writer, save_state.
    tree = ast.parse(SRC)
    writers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr in ("write_text", "replace")]
    assert writers, "no write call found at all -- the detector is broken"
    for w in writers:
        fn = next((p for p in ast.walk(tree)
                   if isinstance(p, ast.FunctionDef)
                   and any(c is w for c in ast.walk(p))), None)
        # A write at MODULE level has no enclosing function, and `next`
        # without a default raised StopIteration there -- an error that
        # reads as a broken test rather than as the violation it is.
        assert fn is not None, (
            f"a module-level `{w.attr}` call: the keeper's only writer must "
            f"be save_state, and a top-level write runs on import")
        assert fn.name == "save_state", (fn.name, w.attr)


def test_the_keeper_parses_at_the_interpreter_floor():
    # 3.10 floor: no `match`, no PEP 695 generics, no `except*`.
    feature_version = fleet.MIN_PYTHON_VERSION
    ast.parse(SRC, feature_version=feature_version)
