"""Test bootstrap: make bin/fleet.py importable as `fleet` without turning bin/
into a package (fleet.py must stay a standalone single-file CLI).

Also auto-applies the SPEC §12 tier markers (unit/hooks/live) by file name so
individual test files need no per-test marker edits, and enforces the
`FLEET_LIVE=1` gate on the tier-3 live suite (tests/integration/) -- when the
env var is unset the live tier is SKIPPED cleanly (never failed), keeping the
unit/hook tiers claude-free by default.
"""
import os
import sys
from pathlib import Path

import pytest

BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))


def pytest_collection_modifyitems(config, items):
    """Tag every collected test with its tier (SPEC §12) and skip the live
    tier unless FLEET_LIVE=1 is set in the environment."""
    live_enabled = bool(os.environ.get("FLEET_LIVE"))
    live_skip = pytest.mark.skip(
        reason="live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness"
    )
    for item in items:
        name = Path(str(item.fspath)).name
        if name == "test_live_smoke.py" or "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.live)
            if not live_enabled:
                item.add_marker(live_skip)
        elif name == "test_hooks.py":
            item.add_marker(pytest.mark.hooks)
        else:
            item.add_marker(pytest.mark.unit)
