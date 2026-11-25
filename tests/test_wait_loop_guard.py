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
    # Review of #112: detached wrappers, substitutions, `for`, functions, heredocs.
    'setsid sh -c "until ! pgrep -f X; do sleep 1; done" &',
    'systemd-run --user --unit=w -p Nice=5 sh -c "until ! pgrep -f X; do sleep 1; done"',
    'daemonize -c /tmp /bin/sh -c "while pgrep x; do sleep 1; done"',
    'bash -lc "while pgrep x; do sleep 1; done"',
    'until [ -z "$(pgrep -f X)" ]; do sleep 1; done',
    "while [ -n \"`pidof buf`\" ]; do sleep 1; done",
    "while [ $(pgrep -c pytest) -gt 0 ]; do sleep 1; done",
    "for i in $(seq 100); do pgrep -f pytest >/dev/null || break; sleep 5; done",
    'busy() { pgrep -f "pytest" >/dev/null; }\nwhile busy; do sleep 10; done',
    "function busy { ps -C pytest >/dev/null; }; until ! busy; do sleep 10; done",
    "bash <<EOF\nuntil ! pgrep -f pytest; do sleep 15; done\nEOF",
    "cat <<'EOF' | sh\nwhile pgrep -f pytest; do sleep 15; done\nEOF",
    "while true; do if pgrep -f pytest; then sleep 5; else break; fi; done",
    "while true; do\n  while pgrep x; do sleep 1; done\n  echo next\ndone",
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
    # Review of #112: `ps` counts only as a command word.
    "until docker ps | grep -q testdb; do sleep 1; done",
    "until docker compose ps --status running | grep -q db; do sleep 2; done",
    "until podman ps --format '{{.Names}}' | grep -q db; do sleep 1; done",
    "while read -r ps; do echo \"$ps\"; sleep 0.1; done < list.txt",
    "until pg_isready -h localhost; do sleep 1; done",
    "until curl -sf http://localhost:8080/health; do sleep 1; done",
    "while kill -0 \"$PID\"; do sleep 1; done",
    "for f in *.py; do ps -p 1; done",
    "sleep 5; pgrep pytest",
    "cat <<EOF > notes.md\nwhile pgrep x; do sleep 1; done\nEOF",
    "jq -r . <<<'while pgrep x; do sleep 1; done'",
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


def test_a_script_named_by_a_variable_path_is_read(guard, tmp_path, monkeypatch):
    """Lanes keep scratch scripts under `$CLAUDE_JOB_DIR/tmp`."""
    jobtmp = tmp_path / "job" / "tmp"
    jobtmp.mkdir(parents=True)
    (jobtmp / "plain.sh").write_text("until ! pgrep -f runtests.sh; do sleep 15; done\n")
    monkeypatch.setenv("JOBTMP", str(jobtmp))
    monkeypatch.setenv("HOME", str(tmp_path))
    for command in ("bash $JOBTMP/plain.sh", 'bash "$JOBTMP/plain.sh"',
                    "bash ${JOBTMP}/plain.sh", "$JOBTMP/plain.sh",
                    "nohup bash ~/job/tmp/plain.sh &"):
        assert guard.refusal(_bash(command, tmp_path)) is not None, command


def test_a_poller_behind_a_function_in_a_script_is_refused(guard, tmp_path):
    """The runner shape: `busy() { pgrep ...; }` then `while busy; do sleep`."""
    (tmp_path / "runtests.sh").write_text(
        "#!/bin/bash\n"
        "busy() {\n  pgrep -f 'pytest|buf' >/dev/null\n}\n"
        "while busy; do sleep 10; done\n"
        "python -m pytest -q\n")
    assert guard.refusal(_bash("bash runtests.sh", tmp_path)) is not None
    (tmp_path / "quiet.sh").write_text(
        "#!/bin/bash\nbusy() { echo hi; }\nwhile busy; do sleep 1; break; done\n")
    assert guard.refusal(_bash("bash quiet.sh", tmp_path)) is None


def test_the_monitor_tool_command_is_checked(guard, tmp_path):
    payload = {"tool_name": "Monitor", "cwd": str(tmp_path),
               "tool_input": {"command": "until ! pgrep -f pytest; do sleep 5; done",
                              "description": "x", "timeout_ms": 1000}}
    assert guard.refusal(payload) is not None
    payload["tool_input"]["command"] = "tail -f run.log | grep --line-buffered ERROR"
    assert guard.refusal(payload) is None


def test_the_template_hook_matcher_covers_monitor():
    template = json.loads((ROOT / "worker-settings.template.json").read_text(encoding="utf-8"))
    matcher = template["hooks"]["PreToolUse"][0]["matcher"]
    assert set(matcher.split("|")) >= {"Bash", "Monitor", "Grep", "Glob"}


def test_the_hook_process_denies_and_exits_zero(tmp_path):
    payload = _bash(REFUSED[1], tmp_path)
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "fleet exclusive" in decision["permissionDecisionReason"]
