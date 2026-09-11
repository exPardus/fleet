"""The interface's registered pane survives a manual resume/window rename."""
import io
import json
import subprocess

import pytest

import fleet
import fleet_keeper as k


class TmuxRunner:
    def __init__(self, *, window="claude", command="claude", dead=False,
                 named_pane=None, scan_rc=0, send_rc=0):
        self.calls = []
        self.panes = {"%42": (window, command, dead)}
        if named_pane:
            self.panes[named_pane] = ("fleet", "claude", False)
        self.scan_rc = scan_rc
        self.send_rc = send_rc

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        assert argv[0] == "tmux", argv
        rc, output = 0, ""
        if argv[1] == "list-panes":
            if "-a" in argv:
                assert argv == ["tmux", "list-panes", "-a", "-F",
                                "#{pane_id} #{pane_current_command} #{pane_dead}"]
                rc = self.scan_rc
                output = "".join(f"{pid} {cmd} {int(dead)}\n"
                                 for pid, (_, cmd, dead) in self.panes.items())
            else:
                assert argv[argv.index("-t") + 1] == "work:fleet"
                rows = [(pid, cmd, dead) for pid, (win, cmd, dead)
                        in self.panes.items() if win == "fleet"]
                rc = 0 if rows else 1
                fmt = argv[argv.index("-F") + 1]
                output = "".join(
                    fmt.replace("#{pane_id}", pid)
                    .replace("#{pane_current_command}", cmd)
                    .replace("#{pane_dead}", str(int(dead))) + "\n"
                    for pid, cmd, dead in rows)
        elif argv[1] == "send-keys":
            rc = self.send_rc
        return subprocess.CompletedProcess(argv, rc, stdout=output, stderr="")

    def tmux(self, verb):
        return [argv for argv in self.calls if argv[:2] == ["tmux", verb]]


def tick(home, runner, monkeypatch, *extra):
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    # Keep the real rule, dedup, tmux selection/delivery and state handling;
    # isolate only the unrelated fleet/git/roster observation subprocesses.
    monkeypatch.setattr(k, "collect", lambda *a, **kw: {
        "goals_active": True, "claim_state": "none", "hook_error_lines": 0})
    monkeypatch.setattr(k, "_supervisor_guard", lambda *a, **kw: {
        "verdict": "DISPATCH", "reason": "claim none", "state": "none"})
    out = io.StringIO()
    k.main(["--once", "--fleet-home", str(home), *extra], run=runner,
           now_fn=lambda: 1_800_000_000.0, out=out)
    return out.getvalue()


def register(home, pane="%42\n"):
    (home / "state").mkdir(exist_ok=True)
    (home / "state" / "interface-pane").write_text(pane, encoding="utf-8")


def test_manual_resume_in_claude_window_pages_registered_pane_without_creating(
        tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner(window="claude")  # No window named fleet exists.
    tick(tmp_path, runner, monkeypatch)

    assert runner.tmux("new-window") == [], runner.calls
    assert runner.tmux("kill-window") == [], runner.calls
    sends = runner.tmux("send-keys")
    assert len(sends) == 2, runner.calls
    assert sends[0][:5] == ["tmux", "send-keys", "-t", "%42", "-l"]
    assert sends[0][-1].startswith("KEEPER: supervisor stalled")
    assert sends[1] == ["tmux", "send-keys", "-t", "%42", "Enter"]
    assert (tmp_path / "state" / "interface-pane").read_text() == "%42\n"


def test_claude_registration_is_the_only_registered_pane(tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner(command="claude")
    tick(tmp_path, runner, monkeypatch)
    assert runner.tmux("new-window") == []
    assert runner.tmux("kill-window") == []
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["%42", "%42"]


def test_shell_registration_falls_back_to_window_and_still_pages(
        tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner(window="fleet", command="zsh")
    out = tick(tmp_path, runner, monkeypatch)
    assert out.count("keeper: registered pane %42 runs zsh, not claude; "
                     "falling back to window") == 1
    assert len(runner.tmux("kill-window")) == 1
    assert len(runner.tmux("new-window")) == 1
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["work:fleet"] * 2
    assert not (tmp_path / "state" / "interface-pane").exists()


def test_dead_registration_falls_back_to_window_and_still_pages(
        tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner(window="fleet", command="claude", dead=True)
    tick(tmp_path, runner, monkeypatch)
    assert len(runner.tmux("kill-window")) == 1
    assert len(runner.tmux("new-window")) == 1
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["work:fleet"] * 2
    assert not (tmp_path / "state" / "interface-pane").exists()


@pytest.mark.parametrize("registered_window, warnings", [("claude", 1), ("fleet", 0)])
def test_duplicate_window_warns_only_when_registration_is_elsewhere(
        tmp_path, monkeypatch, registered_window, warnings):
    register(tmp_path)
    runner = TmuxRunner(window=registered_window, named_pane="%9")
    out = tick(tmp_path, runner, monkeypatch)
    assert out.count("keeper: two interface candidates") == warnings
    assert runner.tmux("kill-window") == []
    assert runner.tmux("new-window") == []
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["%42", "%42"]


@pytest.mark.parametrize("registration", ["absent", "gone", "dead"])
def test_missing_or_dead_registration_falls_back_to_window_creation(
        tmp_path, monkeypatch, registration):
    if registration != "absent":
        register(tmp_path, "%99\n" if registration == "gone" else "%42\n")
    runner = TmuxRunner(dead=registration == "dead")
    tick(tmp_path, runner, monkeypatch)
    creates = runner.tmux("new-window")
    assert len(creates) == 1
    assert creates[0][:8] == ["tmux", "new-window", "-d", "-t", "work",
                            "-n", "fleet", "-c"]
    if registration == "dead":
        assert len(runner.tmux("send-keys")) == 2
    else:
        assert runner.tmux("send-keys") == []  # Existing startup deferral.


def test_gone_registration_pages_existing_named_window(tmp_path, monkeypatch):
    register(tmp_path, "%99\n")
    runner = TmuxRunner(named_pane="%9")
    tick(tmp_path, runner, monkeypatch)
    assert runner.tmux("new-window") == []
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["work:fleet"] * 2


def test_dry_run_recognises_registered_pane_without_mutating(tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner()
    out = tick(tmp_path, runner, monkeypatch, "--dry-run")
    assert "would create" not in out
    assert "interface pane %42" in out
    assert all(argv[1] == "list-panes" for argv in runner.calls)
    assert not (tmp_path / "state" / "keeper").exists()


@pytest.mark.parametrize("failure", ["scan", "invalid", "unreadable", "encoding"])
def test_unknown_registration_defers_without_creating_or_recording_pages(
        tmp_path, monkeypatch, failure):
    register(tmp_path, "work:fleet\n" if failure == "invalid" else "%42\n")
    path = tmp_path / "state" / "interface-pane"
    if failure == "unreadable":
        path.unlink()
        path.mkdir()
    elif failure == "encoding":
        path.write_bytes(b"\xff")
    runner = TmuxRunner(scan_rc=1 if failure == "scan" else 0)
    out = tick(tmp_path, runner, monkeypatch)
    assert "interface pane unavailable" in out
    assert len(runner.tmux("new-window")) == 1
    assert "pages deferred to next tick" in out


def test_failed_pane_send_retries_without_creating_a_window(tmp_path, monkeypatch):
    register(tmp_path)
    runner = TmuxRunner(send_rc=1)
    tick(tmp_path, runner, monkeypatch)
    state = json.loads((tmp_path / "state" / "keeper" / "last-page.json").read_text())
    assert "supervisor-stalled" not in state
    assert len(runner.tmux("send-keys")) == 1  # No Enter after a failed literal send.
    runner.send_rc = 0
    tick(tmp_path, runner, monkeypatch)
    assert [argv[3] for argv in runner.tmux("send-keys")] == ["%42"] * 3
    assert runner.tmux("send-keys")[-1] == ["tmux", "send-keys", "-t", "%42", "Enter"]
    assert runner.tmux("new-window") == []
    assert runner.tmux("kill-window") == []
