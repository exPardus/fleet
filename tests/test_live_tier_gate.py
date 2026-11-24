"""The live tier spends real Claude sessions; only an explicit opt-in runs it."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import live_tier_enabled

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value, enabled", [
    ("1", True), ("true", True), ("TRUE", True), (" 1 ", True),
    ("0", False), ("false", False), ("", False), ("no", False),
    ("yes", False), ("2", False),
])
def test_only_an_exact_opt_in_enables_the_live_tier(value, enabled):
    assert live_tier_enabled(value) is enabled


@pytest.mark.skipif(os.name == "nt", reason="the fake claude is a POSIX script")
@pytest.mark.parametrize("value", ["0", "false"])
def test_an_opt_out_spelling_never_starts_claude(value, tmp_path):
    """Run the live module with a fake `claude` that records any call."""
    marker = tmp_path / "claude-was-called"
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 3\n", encoding="utf-8")
    fake.chmod(0o700)
    env = {**os.environ, "FLEET_LIVE": value,
           "PATH": f"{fake.parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
         "tests/integration/test_native_subagent_pin.py"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert "passed" not in done.stdout.splitlines()[-1]
    assert "skipped" in done.stdout.splitlines()[-1]
    assert not marker.exists()
