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


@pytest.fixture(autouse=True)
def _never_touch_the_real_home(tmp_path_factory, monkeypatch):
    """Redirect every path fleet resolves from `Path.home()` into a tmp dir.

    `cmd_init` stamps `~/.claude/fleet-home` (the marker the SessionStart hook
    reads to find the real FLEET_HOME) and `fleet init --statusline` writes
    `~/.claude/settings.json`. Tests that exercise those paths monkeypatched
    the settings path but not the marker -- so running the SUITE overwrote the
    developer's real marker with a pytest tmp dir, silently repointing their
    fleet hook at a directory that no longer exists. Caught 2026-07-09.

    Tests that assert on these paths override them again with their own value;
    this fixture only guarantees the default is never the real home."""
    import fleet
    sandbox = tmp_path_factory.mktemp("fake-home")
    (sandbox / ".claude").mkdir()
    monkeypatch.setattr(fleet, "fleet_home_marker_path",
                        lambda: sandbox / ".claude" / "fleet-home")
    monkeypatch.setattr(fleet, "user_settings_path",
                        lambda: sandbox / ".claude" / "settings.json")


@pytest.fixture(autouse=True)
def _no_inherited_claude_session(monkeypatch):
    """Run every test as a HUMAN SHELL, not as whichever Claude session invoked
    pytest.

    The destructive-command guard (SPEC §5.1) keys off CLAUDE_CODE_SESSION_ID.
    When pytest itself is launched from a Claude Code session, that variable is
    inherited, every fixture worker looks foreign, and `fleet kill`/`clean`
    tests get refused -- a test outcome that depends on who ran the tests.
    Tests that exercise the guard set the variable explicitly."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


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
