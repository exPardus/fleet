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
    planted = SRC + "\n\ndef _mutant():\n    return fleet.dispatch_bg('x', '.', '', 'bypass')\n"
    assert "dispatch_bg" in _referenced_names(planted)


def test_the_only_fleet_attributes_used_are_read_only_ones():
    tree = ast.parse(SRC)
    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "fleet"}
    assert used <= {"status_snapshot", "MIN_PYTHON_VERSION"}, used


def test_the_keeper_writes_only_under_state_keeper():
    # Every open(..., 'w'|'x'|'a') / write_text / os.replace target in the
    # module is the keeper's own state file. Audited by name: the module
    # has exactly one writer, save_state.
    tree = ast.parse(SRC)
    writers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr in ("write_text", "replace")]
    for w in writers:
        fn = next(p for p in ast.walk(tree)
                  if isinstance(p, ast.FunctionDef)
                  and any(c is w for c in ast.walk(p)))
        assert fn.name == "save_state", (fn.name, w.attr)


def test_the_keeper_parses_at_the_interpreter_floor():
    # 3.10 floor: no `match`, no PEP 695 generics, no `except*`.
    feature_version = fleet.MIN_PYTHON_VERSION
    ast.parse(SRC, feature_version=feature_version)
