"""Keep test patches attached to the implementation after the index split."""
from pathlib import Path

import fleet
import fleet_index
import pytest

from fleet_patch_audit import moved_exports, scan_source, scan_tests, unsafe_sites

ROOT = Path(__file__).resolve().parents[1]


def test_patch_census_covers_aliases_and_all_patch_spellings():
    source = '''
import fleet as f
from unittest.mock import patch
alias = f
setattr(alias, "build_index", replacement)
monkeypatch.setattr(f, "cmd_q", replacement)
patch.object(f, "read_shard", replacement)
patch("fleet.index_status", replacement)
monkeypatch.setattr("fleet.cmd_index", replacement)
f.parse_context_arg = replacement
filename = f.__file__
tree = ast.parse(Path(filename).read_text())
source = inspect.getsource(f.build_index)
setattr(f, dynamic, replacement)
patch_fleet(dynamic, replacement)
patch(f"fleet.{dynamic}", replacement)
'''
    sites = scan_source(source)
    assert [site.kind for site in sites] == [
        "patch", "patch", "patch", "string-patch", "string-patch",
        "assignment", "file-reader", "source-reader", "source-reader",
        "patch", "routed", "string-patch",
    ]
    assert len(unsafe_sites(sites, moved_exports(ROOT))) == 9


def test_patch_census_has_no_silent_facade_or_dynamic_patches():
    sites = scan_tests(ROOT)
    # The validated fixture is the single intentional dynamic fleet patch.
    fixture_sites = [site for site in sites
                     if site.path == "tests/conftest.py" and site.scope == "_patch"
                     and site.kind == "patch"]
    assert len(fixture_sites) == 1
    assert not unsafe_sites([site for site in sites if site not in fixture_sites],
                            moved_exports(ROOT))
    assert {"patch", "routed", "file-reader", "source-reader"} <= {s.kind for s in sites}


def test_patch_fleet_mirrors_the_owner_and_facade(patch_fleet):
    sentinel = object()
    patch_fleet("build_index", sentinel)
    assert fleet.build_index is sentinel
    assert fleet_index.build_index is sentinel


def test_patch_fleet_keeps_injected_capabilities_on_kernel(patch_fleet):
    original = fleet_index.build_parser
    sentinel = object()
    patch_fleet("build_parser", sentinel)
    assert fleet.build_parser is sentinel
    assert fleet_index.build_parser is original


def test_patch_fleet_rejects_unknown_and_non_string_names(patch_fleet):
    with pytest.raises(AttributeError, match="unknown fleet patch name"):
        patch_fleet("not_a_fleet_symbol", object())
    pytest.raises(TypeError, patch_fleet, None, object(), match="literal string")


def test_census_catches_patch_aliases_and_indirect_dynamic_paths():
    source = '''
from unittest.mock import patch as p
target = "fleet." + dynamic
alias_target = target
p(alias_target, replacement)
p("fleet.cmd_q", replacement)
route = patch_fleet
route(dynamic, replacement)
'''
    sites = scan_source(source)
    assert [(site.kind, site.name) for site in sites] == [
        ("string-patch", None), ("string-patch", "cmd_q"), ("routed", None)]
    assert unsafe_sites(sites, moved_exports(ROOT)) == sites
