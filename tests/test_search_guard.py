"""PreToolUse guard: searches rooted at `/` or the home directory are refused.

The worker preamble carries the host rule; this pins the cheap enforcement:
find/bfs/fd/rg/recursive grep in Bash, and the Grep/Glob tools' path. A
worktree under home stays searchable, and anything unparseable is allowed.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "bin" / "hooks" / "pretooluse_search_guard.py"
HOME = "/home/user"
CWD = "/home/user/work/lane-tree"


def _guard():
    spec = importlib.util.spec_from_file_location("search_guard_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard(monkeypatch):
    module = _guard()
    monkeypatch.setattr(module, "_home", lambda: HOME)
    return module


def _bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": CWD}


@pytest.mark.parametrize("command", [
    "find / -name '*.py'",
    "find -L / -name x",
    "find ~ -name settings.json",
    "find $HOME -type f",
    "find ${HOME}/ -maxdepth 3",
    "find /home -name x",
    "bfs / -name core",
    "fd pattern /",
    "fd -e py pattern ~",
    "fd --search-path / pattern",
    "fdfind x /home/user",
    "rg TODO /",
    "rg -n -i 'needle' ~",
    "rg -e needle -e other /home",
    "rg --files /",
    "grep -r needle /",
    "grep -rn needle ~/",
    "grep --recursive needle /home/user",
    "cd src && find / -name x",
    "ls; sudo find / -xdev -name x 2>/dev/null | head",
    "timeout 30 rg x /",
    "FOO=1 find / -name x",
    "find ../../.. -name x",
])
def test_broad_searches_are_refused(guard, command):
    reason = guard.refusal(_bash(command))
    assert reason and "never search / or the home directory" in reason


@pytest.mark.parametrize("command", [
    "find . -name '*.py'",
    "find src tests -type f",
    "find ~/work/lane-tree -name x",
    "rg TODO",
    "rg TODO src/",
    "rg -e / src",
    "fd pattern",
    "fd / src",
    "grep needle /etc/hosts",
    "grep -n needle file.txt",
    "grep -r needle .",
    "ls /",
    "du -sh /tmp",
    "echo 'find / -name x'",
    "git grep needle",
    "cat <<'EOF'\nunbalanced 'quote\nEOF",
])
def test_scoped_or_non_search_commands_are_allowed(guard, command):
    assert guard.refusal(_bash(command)) is None


@pytest.mark.parametrize("tool, path, refused", [
    ("Grep", "/", True), ("Grep", HOME, True), ("Glob", "/home", True),
    ("Grep", CWD, False), ("Glob", "src", False), ("Grep", "", False),
])
def test_grep_and_glob_tool_paths(guard, tool, path, refused):
    payload = {"tool_name": tool, "tool_input": {"path": path}, "cwd": CWD}
    assert (guard.refusal(payload) is not None) is refused


def _run(payload, home):
    env = dict(os.environ, HOME=home)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=15)


def test_the_hook_denies_through_the_pretooluse_contract(tmp_path):
    done = _run({"tool_name": "Bash", "tool_input": {"command": "find / -name x"},
                 "cwd": str(tmp_path)}, str(tmp_path / "home"))
    assert done.returncode == 0
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "deny"
    assert "never search /" in out["permissionDecisionReason"]


@pytest.mark.parametrize("stdin", ["not json", "[]", "{}",
                                   json.dumps({"tool_name": "Bash"})])
def test_the_hook_allows_silently_on_anything_it_cannot_read(tmp_path, stdin):
    env = dict(os.environ, HOME=str(tmp_path))
    done = subprocess.run([sys.executable, str(HOOK)], input=stdin,
                          capture_output=True, text=True, env=env, timeout=15)
    assert done.returncode == 0 and done.stdout == ""


def test_the_worker_settings_template_wires_the_guard():
    template = json.loads((ROOT / "worker-settings.template.json").read_text())
    entries = template["hooks"]["PreToolUse"]
    commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
    assert any("pretooluse_search_guard.py" in command for command in commands)
    matchers = {entry.get("matcher") for entry in entries}
    assert any(m and {"Bash", "Grep", "Glob"} <= set(m.split("|")) for m in matchers)


# Review w598 of 66a43d77: multi-line commands, cd, wrappers with values,
# nested shells, grep -d recurse, and Glob patterns.
@pytest.mark.parametrize("command", [
    "echo hi\nfind / -name x",
    "cd src\nrg TODO ~",
    "cd /\nfind . -name x",
    "cd / && find . -name x",
    "(cd /; find .)",
    "cd ~ && rg foo",
    "cd && rg foo",
    "pushd / && rg x",
    "cd /home && fd x",
    "nice -n 10 find /",
    "timeout -s KILL 60 find /",
    "sudo -u root find /",
    "bash -c 'find / -name x'",
    "sh -c \"rg foo /\"",
    "grep -d recurse foo /",
    "grep --directories=recurse foo ~",
    "cat <<EOF\ndata\nEOF\nfind / -name x",
])
def test_review_bypasses_are_refused(guard, command):
    assert guard.refusal(_bash(command)) is not None, command


@pytest.mark.parametrize("command", [
    "cat <<EOF\nfind / -name x\nEOF",
    "cat <<-'EOF'\n\trg foo ~\n\tEOF\necho done",
    "cd src && find . -name x",
    "cd /tmp/../home/user/work/lane-tree && rg foo",
    "cd - && find .",
    "grep -r --include '*.md' '/' docs",
    "rg --hyperlink-format default '/' src",
    "bash -c 'find . -name x'",
    "nice -n 10 find .",
    "cd / && ls",
    "cd / && sudo",
])
def test_review_false_positives_are_allowed(guard, command):
    assert guard.refusal(_bash(command)) is None, command


@pytest.mark.parametrize("pattern, refused", [
    ("/**/*.py", True), ("~/**/*.md", True), ("/home/" "*/x", True),
    ("/home/user/work/lane-tree/**/*.py", False), ("**/*.py", False),
    ("src/*.py", False),
])
def test_an_absolute_glob_pattern_without_a_path(guard, pattern, refused):
    payload = {"tool_name": "Glob", "tool_input": {"pattern": pattern}, "cwd": CWD}
    assert (guard.refusal(payload) is not None) is refused

