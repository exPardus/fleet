"""Regression: the Windows descendant walk must never assign to $pid.

PowerShell variable names are case-insensitive, and $PID is a read-only
automatic variable. Assigning to $pid fails silently, so the walk sees the
shell's own PID instead of each child's.
"""

import re
import subprocess

import pytest

import fleet_platform


ASSIGNS_PID = re.compile(r"\$pid\b\s*=(?!=)", re.IGNORECASE)
ANY_PID_VAR = re.compile(r"\$pid\b", re.IGNORECASE)


@pytest.fixture
def captured_script(monkeypatch):
    seen = {}

    def fake_run(argv, **_kwargs):
        seen["script"] = argv[-1]
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr(fleet_platform.subprocess, "run", fake_run)
    fleet_platform._WindowsPlatform().process_tree(1234)
    return seen["script"]


def test_windows_descendant_walk_never_assigns_pid_variable(captured_script):
    assert not ASSIGNS_PID.search(captured_script), captured_script


def test_windows_descendant_walk_uses_child_pid_variable(captured_script):
    assert "$childPid=[int]$child.ProcessId" in captured_script
    assert not ANY_PID_VAR.search(captured_script), captured_script
