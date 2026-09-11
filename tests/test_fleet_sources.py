"""The safety-detector source population must include both extracted leaves."""
import ast

import pytest

import fleet_sources
from test_index_compose import call_counts
from test_load_registry_callers import _callers


def test_implementation_population_has_every_module():
    paths = fleet_sources.fleet_implementation_paths()
    assert {path.name for path in paths} == {
        "fleet.py", "fleet_index.py", "fleet_errors.py", "fleet_land.py",
        "fleet_brief.py"}
    names = {node.name for node in ast.parse(
        fleet_sources.fleet_implementation_source()).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
    assert {"main", "cmd_q", "FleetCliError"} <= names


@pytest.mark.parametrize("filename", fleet_sources.IMPLEMENTATION_FILES)
def test_dispatch_and_registry_censuses_detect_a_site_in_each_module(
        filename, tmp_path, monkeypatch):
    paths = tuple(tmp_path / name for name in fleet_sources.IMPLEMENTATION_FILES)
    for path in paths:
        source = ("def planted():\n    dispatch_bg()\n    load_registry()\n"
                  if path.name == filename else "")
        path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(fleet_sources, "fleet_implementation_paths", lambda: paths)
    assert call_counts("dispatch_bg") == {"planted": 1}
    assert "planted" in _callers(fleet_sources.fleet_implementation_source())


def test_a_missing_implementation_file_is_a_loud_error(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet_sources, "fleet_implementation_paths",
                        lambda: (tmp_path / "missing.py",))
    with pytest.raises(FileNotFoundError):
        fleet_sources.fleet_implementation_source()
