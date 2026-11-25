"""PreToolUse guard: hand-rolled pgrep/sleep wait loops are refused.

Two reviewer lanes waited 2-3 hours in background loops shaped like
`while pgrep -f "pytest|buf" ...; do sleep N; done`: on a shared box some
pytest is nearly always running, so the loop never ended. `fleet exclusive`
replaces them; the search-guard hook now refuses the loop and names it. A
single pgrep with no loop, and quoted text that merely mentions one, pass.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "bin" / "hooks" / "pretooluse_search_guard.py"


def _guard():
    spec = importlib.util.spec_from_file_location("wait_guard_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard(monkeypatch, tmp_path):
    module = _guard()
    monkeypatch.setattr(module, "_home", lambda: "/home/user")
    return module


def _bash(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


# The two real shapes (reviewer lanes, 2026-11-25), plus close relatives.
REFUSED = [
    'waitfree() { while pgrep -f "pytest" >/dev/null; do sleep 20; done; }\nwaitfree; pytest -q',
    'while pgrep -f "python[0-9.]* -m pytest|bin/pytest|buf " >/dev/null; do sleep 30; done; pytest -q',
    "until ! pgrep -f pytest; do sleep 10; done && pytest",
    "while pidof buf >/dev/null 2>&1; do sleep 5; done",
    "while ps aux | grep -q '[p]ytest'; do sleep 15; done; make test",
    "while true; do pgrep -f pytest >/dev/null || break; sleep 20; done; pytest",
    "nohup bash -c 'while pgrep -f pytest; do sleep 30; done; pytest -q' &",
    "timeout 3600 sh -c \"while pgrep pytest >/dev/null; do sleep 60; done\"",
]

ALLOWED = [
    "pgrep -f pytest",
    "pgrep -fl 'pytest|buf' || echo none",
    "ps aux | grep pytest",
    "sleep 30",
    "for i in 1 2 3; do pytest -q tests/test_a.py; done",
    "while read -r line; do echo \"$line\"; done < list.txt",
    "while pgrep -f pytest; do echo busy; break; done",
    "git commit -m 'refuse while pgrep -f pytest; do sleep 20; done loops'",
    "echo \"while pgrep x; do sleep 1; done\"",
    "fleet exclusive --label w1 -- pytest -q",
]


@pytest.mark.parametrize("command", REFUSED)
def test_wait_loops_are_refused_with_the_replacement_named(guard, tmp_path, command):
    reason = guard.refusal(_bash(command, tmp_path))
    assert reason is not None
    assert "fleet exclusive --label <lane> -- <cmd>" in reason


@pytest.mark.parametrize("command", ALLOWED)
def test_a_single_pgrep_or_an_unrelated_loop_is_allowed(guard, tmp_path, command):
    assert guard.refusal(_bash(command, tmp_path)) is None


def test_a_wait_loop_inside_a_script_run_by_path_is_refused(guard, tmp_path):
    """The real waiter was a script: `bash waitrun2.sh`."""
    script = tmp_path / "waitrun2.sh"
    script.write_text(
        "#!/bin/bash\n"
        'waitfree() { while pgrep -f "pytest" >/dev/null; do sleep 20; done; }\n'
        "for n in 169 171; do\n"
        "  waitfree; echo start$n\n"
        "  python -m pytest tests -q > v$n.log 2>&1; echo rc$n=$?\n"
        "done\n")
    for command in ("bash waitrun2.sh", "nohup bash ./waitrun2.sh > out.log 2>&1 &",
                    "source waitrun2.sh", f"sh {script}", "./waitrun2.sh"):
        assert guard.refusal(_bash(command, tmp_path)) is not None, command
    clean = tmp_path / "run.sh"
    clean.write_text("#!/bin/bash\npgrep -f pytest\npython -m pytest -q\n")
    assert guard.refusal(_bash("bash run.sh", tmp_path)) is None


def test_the_hook_process_denies_and_exits_zero(tmp_path):
    payload = _bash(REFUSED[1], tmp_path)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "fleet exclusive" in decision["permissionDecisionReason"]
