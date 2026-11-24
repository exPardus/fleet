"""Native Claude subagent pin suite (migration step 1 of
docs/specs/native-subagent-lanes-proposal.md).

Each test runs one headless parent, `claude -p --output-format stream-json`,
that dispatches one native subagent with the Agent tool. It pins what the
installed Claude Code exposes about that child:

  1. identity, terminal evidence, per-child usage, and the durable record
     beside the parent transcript;
  2. continuation: SendMessage revives the same child id with a new run id;
  3. worktree isolation: an unchanged worktree is removed (meta records
     `worktreeCleanlyRemoved`), a changed one is kept on its own branch;
  4. permissions: the child inherits the parent's mode and --allowedTools;
     a project agent's `permissionMode` does not narrow an acceptEdits parent;
  5. parent death: the child dies with the parent and never completes, and
     a resumed parent reports the run as `stopped` (the meta `finished` flag
     may still be set, so it is not completion evidence);
  6. compaction: /compact leaves the child's transcript and meta intact.

A failure here means the substrate changed under the proposal: re-read the
findings section of the proposal before acting on it.

GATING: tests/conftest.py marks everything under tests/integration/ as `live`
and skips it unless FLEET_LIVE=1. Budget: about ten haiku turns, cents.

CONTAINMENT: the project is a fresh git repo under pytest's tmp_path, which
must be outside the Claude config directory; there every write is a
sensitive-file denial, which would confound the permission pins. The parent
loads only project and local settings, so operator plugins and hooks do not
run. The module uses one private CLAUDE_CONFIG_DIR, so later pins can
resume sessions earlier pins created and nothing lands in the operator's
config. Tests run sequentially, so at most one child session is alive.
Teardown removes this run's worktrees and its private config directory, and
nothing else.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_subagent_evidence import (  # noqa: E402
    child_runs, child_write, read_until, session_id, sidechain_usage,
    stop_parent,
    stream_events,
    subagent_files)

pytestmark = pytest.mark.live

MODEL = os.environ.get("FLEET_LIVE_MODEL", "haiku").strip()
TURN_TIMEOUT = 300


@pytest.fixture(scope="module")
def claude_config(tmp_path_factory):
    """One Claude config directory for the whole module.

    conftest gives every test its own CLAUDE_CONFIG_DIR. A later pin must
    resume a session an earlier pin created, so this module pins one.
    """
    return tmp_path_factory.mktemp("claude-config")


@pytest.fixture(autouse=True)
def _module_claude_config(_never_touch_the_real_home, claude_config,
                          monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_config))


@pytest.fixture(scope="module")
def project(tmp_path_factory, claude_config):
    if shutil.which("claude") is None:
        pytest.skip("claude is not installed")
    root = tmp_path_factory.mktemp("native-subagent-pin") / "proj"
    root.mkdir()
    for config in (claude_config, Path.home() / ".claude"):
        if config.resolve() in root.resolve().parents:
            pytest.skip("pin project must be outside a Claude config directory")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=pin", "-c", "user.email=pin@invalid",
                    "commit", "-q", "--allow-empty", "-m", "init"],
                   cwd=root, check=True)
    yield root
    worktrees = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=root,
        capture_output=True, text=True).stdout
    for line in worktrees.splitlines():
        if line.startswith("worktree ") and "/.claude/worktrees/" in line:
            path = line.split(" ", 1)[1]
            subprocess.run(["git", "worktree", "unlock", path], cwd=root,
                           capture_output=True)
            subprocess.run(["git", "worktree", "remove", "--force", path],
                           cwd=root, capture_output=True)
    shutil.rmtree(claude_config, ignore_errors=True)


def _parent(project, prompt, *flags, resume=None):
    argv = ["claude", "-p", "--model", MODEL,
            "--setting-sources", "project,local",
            "--output-format", "stream-json", "--verbose", *flags]
    if resume:
        argv += ["--resume", resume]
    done = subprocess.run([*argv, "--", prompt], cwd=project,
                          capture_output=True, text=True, timeout=TURN_TIMEOUT)
    events = stream_events(done.stdout)
    assert events, done.stderr[-2000:]
    return events


def _agent_requests(events):
    """The Agent tool inputs the parent actually sent."""
    found = []
    for event in events:
        message = event.get("message")
        if (event.get("type") != "assistant" or event.get("parent_tool_use_id")
                or not isinstance(message, dict)):
            continue
        for block in message.get("content") or []:
            if (isinstance(block, dict) and block.get("type") == "tool_use"
                    and block.get("name") in {"Agent", "Task"}):
                found.append(block.get("input") or {})
    return found


def _parent_requesting(project, prompt, *flags, isolation=False):
    """Run the parent; retry once if the model dropped the requested shape.

    The pin is about the substrate, not about haiku's instruction following:
    a parent that did not ask for a worktree proves nothing about worktrees.
    """
    for _attempt in range(2):
        events = _parent(project, prompt, *flags)
        requests = _agent_requests(events)
        if requests and all(
                (request.get("isolation") == "worktree") is isolation
                for request in requests):
            return events
    pytest.fail(f"parent never sent the requested Agent shape: {requests}")


def _dispatch(description, child_prompt, *, isolation=False, background=True):
    iso = 'isolation "worktree", ' if isolation else ""
    return (f"Use the Agent tool exactly once with subagent_type general-purpose, "
            f"{iso}run_in_background {str(background).lower()}, description "
            f"'{description}', and prompt '{child_prompt}'. Wait for it to "
            "finish. Then reply with exactly the child's answer.")


def _only_child(events):
    runs = child_runs(events)
    assert len(runs) == 1, runs
    (agent, agent_runs), = runs.items()
    return agent, agent_runs


def _worktrees(project):
    out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                         cwd=project, capture_output=True, text=True).stdout
    return [line.split(" ", 1)[1] for line in out.splitlines()
            if line.startswith("worktree ") and "/.claude/worktrees/" in line]


STATE = {}


def test_1_child_identity_terminal_usage_and_durable_record(project):
    token = "CHILD-OK-" + uuid.uuid4().hex[:6].upper()
    events = _parent_requesting(
        project, _dispatch("pin identity", f"Reply with exactly: {token}",
                           isolation=True),
        "--permission-mode", "acceptEdits", isolation=True)
    sid = session_id(events)
    agent, runs = _only_child(events)
    assert re.fullmatch(r"a[0-9a-f]{16}", agent), agent
    assert runs[0]["tool_use_id"].startswith("toolu_")
    terminal = runs[0]["terminal"]
    assert terminal and terminal["status"] == "completed", runs
    assert token in (terminal["summary"] or "")
    assert isinstance(terminal["usage"]["total_tokens"], int)
    assert terminal["usage"]["total_tokens"] > 0
    meta_path, transcript = subagent_files(sid, agent)
    assert meta_path and transcript, (sid, agent)
    meta = json.loads(meta_path.read_text())
    assert meta["toolUseId"] == runs[0]["tool_use_id"]
    assert meta["finished"] is True
    usage = sidechain_usage(transcript.read_text(), agent)
    assert usage["messages"] >= 1 and usage["output_tokens"] > 0
    # An unchanged worktree is removed when the child finishes, and the meta
    # record drops its path in favour of a removal flag (2.1.331).
    assert meta.get("worktreeCleanlyRemoved") is True, meta
    assert "worktreePath" not in meta
    assert not [path for path in _worktrees(project) if agent in path]
    STATE["completed"] = (sid, agent, meta_path, transcript)


def test_2_send_message_revives_the_same_child_with_a_new_run(project):
    token = "SECOND-" + uuid.uuid4().hex[:6].upper()
    events = _parent(
        project,
        "Step 1: use the Agent tool once with subagent_type general-purpose, "
        "run_in_background true, description 'pin continue', prompt 'Reply "
        "with exactly: FIRST'. Step 2: after it completes, use SendMessage "
        f"with to set to that agent's id and message 'Reply with exactly: "
        f"{token}'. Step 3: wait, then reply with exactly the second answer.",
        "--permission-mode", "acceptEdits")
    agent, runs = _only_child(events)
    assert len(runs) == 2, runs
    assert runs[0]["run_id"] != runs[1]["run_id"]
    assert all(run["terminal"]["status"] == "completed" for run in runs)
    assert token in runs[1]["terminal"]["summary"]


def test_3_changed_worktree_is_kept_and_the_child_inherits_accept_edits(project):
    for _attempt in range(2):
        name = f"pin-{uuid.uuid4().hex[:6]}.txt"
        events = _parent_requesting(project, _dispatch(
            "pin write", f"Use the Write tool to create {name} containing PIN "
            "in your current directory, then reply WROTE or DENIED.",
            isolation=True), "--permission-mode", "acceptEdits", isolation=True)
        agent, runs = _only_child(events)
        if _attempted_write(events, runs[0]["tool_use_id"], name):
            break
    else:
        pytest.fail("the child never attempted the Write; nothing was pinned")
    sid = session_id(events)
    assert runs[0]["terminal"]["status"] == "completed"
    meta = json.loads(subagent_files(sid, agent)[0].read_text())
    path, outcome = child_write(events, runs[0]["tool_use_id"], name)
    assert outcome == "ok", (path, outcome)
    assert meta["worktreePath"] in _worktrees(project)
    assert meta["worktreeBranch"] == f"worktree-agent-{agent}"
    assert Path(path) == Path(meta["worktreePath"]) / name
    assert Path(path).is_file()
    assert not (project / name).exists()


def _attempted_write(events, tool_use_id, name):
    """Haiku sometimes skips the step; only a Write with a result pins anything."""
    found = child_write(events, tool_use_id, name)
    return found is not None and found[1] is not None


def _denials(events, agent):
    return [event for event in events
            if event.get("subtype") == "permission_denied"
            and event.get("agent_id") == agent]


@pytest.mark.parametrize("flags, allowed", [
    (("--permission-mode", "default"), False),
    (("--permission-mode", "default", "--allowedTools", "Write"), True),
])
def test_4_child_inherits_the_parent_permission_mode(project, flags, allowed):
    for _attempt in range(2):
        name = f"pin-{uuid.uuid4().hex[:6]}.txt"
        events = _parent_requesting(project, _dispatch(
            "pin perm", f"Use the Write tool to create {name} containing PIN "
            "in your current directory, then reply WROTE or DENIED."), *flags)
        agent, runs = _only_child(events)
        if _attempted_write(events, runs[0]["tool_use_id"], name):
            break
    else:
        pytest.fail("the child never attempted the Write; nothing was pinned")
    assert runs[0]["terminal"]["status"] == "completed"
    path, outcome = child_write(events, runs[0]["tool_use_id"], name)
    assert outcome == ("ok" if allowed else "denied"), (path, outcome)
    assert Path(path).is_file() is allowed
    assert bool(_denials(events, agent)) is not allowed


def test_4b_project_agent_permission_mode_does_not_narrow_accept_edits(project):
    agents = project / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "pin-narrow.md").write_text(
        "---\nname: pin-narrow\ndescription: Pin probe with a narrower "
        "permission mode.\npermissionMode: default\n---\nFollow the task "
        "exactly.\n")
    for _attempt in range(2):
        name = f"pin-{uuid.uuid4().hex[:6]}.txt"
        events = _parent(project, _dispatch(
            "pin narrow", f"Use the Write tool to create {name} containing "
            "PIN in your current directory, then reply WROTE or DENIED.").replace(
                "general-purpose", "pin-narrow"),
            "--permission-mode", "acceptEdits")
        agent, runs = _only_child(events)
        if _attempted_write(events, runs[0]["tool_use_id"], name):
            break
    else:
        pytest.fail("the child never attempted the Write; nothing was pinned")
    sid = session_id(events)
    assert json.loads(subagent_files(sid, agent)[0].read_text())[
        "agentType"] == "pin-narrow"
    # The child's own Write, tied to its dispatching tool use, succeeded:
    # the narrower declared mode is not applied (2.1.331).
    path, outcome = child_write(events, runs[0]["tool_use_id"], name)
    assert outcome == "ok", (path, outcome)
    assert Path(path) == project / name and Path(path).is_file()
    assert not _denials(events, agent)


def test_5_parent_death_kills_the_child_and_resume_reports_stopped(project):
    token = "DEATH" + uuid.uuid4().hex[:6].upper()
    prompt = _dispatch(
        "pin death", f"Run this Bash command and wait for it: sleep 40; echo "
        f"{token} > {token}.txt . Then reply DONE.", isolation=True)
    argv = ["claude", "-p", "--model", MODEL, "--setting-sources",
            "project,local", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "bypassPermissions", "--", prompt]
    parent = subprocess.Popen(argv, cwd=project, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True,
                              start_new_session=True)
    seen = []
    try:
        reached = read_until(parent, seen, lambda event: (
            event.get("subtype") == "task_progress"
            and event.get("last_tool_name") == "Bash"), timeout=120)
        assert reached, "child never ran Bash within 120 s"
        time.sleep(3)
        # The probe: signal the parent process alone. Group cleanup below
        # must not be what stops the child.
        parent.send_signal(signal.SIGTERM)
        parent.wait(30)
        time.sleep(45)  # past the child's sleep: nothing may complete it later
        assert not list(project.rglob(f"{token}.txt"))
        residue = subprocess.run(["pgrep", "-f", token], capture_output=True,
                                 text=True).stdout.split()
        assert residue == []
    finally:
        stop_parent(parent)
    sid = session_id(seen)
    agent, runs = _only_child(seen)
    assert runs[0]["terminal"] is None
    meta = json.loads(subagent_files(sid, agent)[0].read_text())
    # A graceful parent shutdown may still write `finished: true` for a child
    # that never completed (seen on 2.1.331), so the flag is not completion
    # evidence; the missing completed notification and output are.
    assert meta.get("finished") in (None, True), json.dumps(meta)
    # The worktree outlives its dead child; its owner must remove it.
    assert meta["worktreePath"] in _worktrees(project)
    resumed = _parent(project, "Do not start any agent. Reply with one word: OK.",
                      "--permission-mode", "bypassPermissions", resume=sid)
    assert session_id(resumed) == sid
    after = child_runs(resumed)[agent]
    assert after[-1]["terminal"]["status"] == "stopped", after
    assert not [event for event in resumed
                if event.get("subtype") == "task_started"]


def test_6_compaction_keeps_the_child_record(project):
    if "completed" not in STATE:
        pytest.skip("test 1 did not record a completed child")
    sid, agent, meta_path, transcript = STATE["completed"]
    before = (meta_path.read_bytes(), transcript.read_bytes())
    events = _parent(project, "/compact", "--permission-mode", "acceptEdits",
                     resume=sid)
    assert [event for event in events
            if event.get("subtype") == "compact_boundary"], json.dumps(
                events[-1:])[:2000]
    assert (meta_path.read_bytes(), transcript.read_bytes()) == before
