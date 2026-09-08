import io
import json
import subprocess

import pytest

import fleet_keeper as k

NOW = 1_800_000_000.0


def _cp(argv, rc=0, out=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")


class Runner:
    """Scripted subprocess.run. tmux calls are recorded; everything else is
    answered from `table` like tests/test_keeper_collect.py."""

    def __init__(self, *, pane_cmd="claude", tmux_rc=0, agents_rc=0):
        self.calls = []
        self.pane_cmd = pane_cmd
        self.tmux_rc = tmux_rc
        self.agents_rc = agents_rc

    def __call__(self, argv, **kw):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "tmux":
            if argv[1] == "list-panes":
                return _cp(argv, 0 if self.pane_cmd else 1, (self.pane_cmd or "") + "\n")
            return _cp(argv, self.tmux_rc)
        if "sup-status" in argv:
            return _cp(argv, 0, json.dumps({"goals_active": True,
                                            "incarnation": None,
                                            "heartbeat_age_seconds": None,
                                            "pending_decision": None}))
        if argv[:2] == ["claude", "agents"]:
            return _cp(argv, self.agents_rc, "[]")
        if argv[:2] == ["git", "rev-list"]:
            return _cp(argv, 0, "0\n")
        if argv[:2] == ["git", "log"]:
            return _cp(argv, 0, "")
        raise AssertionError(argv)

    def tmux(self, verb):
        return [a for a in self.calls if a[:2] == ["tmux", verb]]


def _snapshot():
    return {"ok": True, "reason": None, "workers": [],
            "supervisor": {"goals_active": True, "state": "none",
                           "incarnation_id": None, "heartbeat_age_seconds": None}}


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "fleet.py").write_text("", encoding="utf-8")
    (tmp_path / "docs" / "operator").mkdir(parents=True)
    (tmp_path / "docs" / "operator" / "server-interface-profile.md").write_text(
        "# profile\n", encoding="utf-8")
    return tmp_path


def _main(home, runner, *extra):
    out = io.StringIO()
    rc = k.main(["--once", "--fleet-home", str(home), *extra],
               run=runner, now_fn=lambda: NOW, snapshot_fn=_snapshot, out=out)
    return rc, out.getvalue()


def test_once_is_required():
    with pytest.raises(SystemExit) as e:
        k.main([], run=Runner(), now_fn=lambda: NOW, snapshot_fn=_snapshot,
               out=io.StringIO())
    assert e.value.code == 2


def test_dead_supervisor_is_paged_into_the_window(home):
    r = Runner()
    rc, out = _main(home, r)
    assert rc == 0
    sends = r.tmux("send-keys")
    assert len(sends) == 2
    assert sends[0][2:] == ["-t", "work:fleet", "-l", sends[0][-1]]
    assert sends[0][-1].startswith("KEEPER: supervisor dead")
    assert sends[1][-1] == "Enter"
    state = json.loads((home / "state" / "keeper" / "last-page.json").read_text())
    assert "supervisor-dead" in state and state["_hook_error_lines"] == 0


def test_second_tick_inside_the_window_sends_nothing(home):
    r = Runner()
    _main(home, r)
    n = len(r.tmux("send-keys"))
    _main(home, r)
    assert len(r.tmux("send-keys")) == n


def test_missing_window_is_created_before_paging(home):
    r = Runner(pane_cmd=None)
    _main(home, r)
    new = r.tmux("new-window")
    assert len(new) == 1
    argv = new[0]
    assert argv[argv.index("-t") + 1] == "work"
    assert argv[argv.index("-n") + 1] == "fleet"
    assert argv[argv.index("-c") + 1] == str(home)
    launch = argv[-1]
    assert launch.startswith("claude --permission-mode bypassPermissions ")
    assert "server-interface-profile.md" in launch
    # created first, paged second
    assert r.calls.index(new[0]) < r.calls.index(r.tmux("send-keys")[0])


def test_window_with_a_dead_shell_is_recycled(home):
    r = Runner(pane_cmd="zsh")
    _main(home, r)
    assert len(r.tmux("kill-window")) == 1 and len(r.tmux("new-window")) == 1


def test_dry_run_performs_no_tmux_action_and_writes_no_state(home):
    r = Runner(pane_cmd=None)
    rc, out = _main(home, r, "--dry-run")
    assert rc == 0
    assert not [a for a in r.calls if a[0] == "tmux" and a[1] != "list-panes"]
    assert "KEEPER: supervisor dead" in out
    assert not (home / "state" / "keeper" / "last-page.json").exists()


def test_tmux_failure_is_reported_and_exit_stays_zero(home):
    r = Runner(tmux_rc=1)
    rc, out = _main(home, r)
    assert rc == 0 and "keeper: tmux failed" in out


def test_window_and_session_flags(home):
    r = Runner()
    _main(home, r, "--tmux-session", "s2", "--window", "ops")
    assert r.tmux("send-keys")[0][3] == "s2:ops"
