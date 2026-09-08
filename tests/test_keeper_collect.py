"""collect() turns four read-only sources into one observation dict.
Every subprocess goes through the injected `run`; nothing here touches a
real fleet, git, tmux, or claude."""
import json
import subprocess
from pathlib import Path

import pytest

import fleet_keeper as k

NOW = 1_800_000_000.0


def _cp(argv, rc=0, out=""):
    return subprocess.CompletedProcess(argv, rc, stdout=out, stderr="")


def _runner(table):
    """table: list of (predicate(argv) -> bool, rc, stdout). First match wins."""
    calls = []

    def run(argv, **kw):
        calls.append((list(argv), kw))
        assert kw.get("capture_output") and kw.get("text") and kw.get("timeout")
        for pred, rc, out in table:
            if pred(argv):
                return _cp(argv, rc, out)
        raise AssertionError(f"unexpected subprocess: {argv}")
    run.calls = calls
    return run


def _snapshot(**over):
    snap = {"ok": True, "reason": None,
            "workers": [{"name": "w1", "status": "idle", "mail": 1, "limit_kind": None,
                         "turns": 3, "tier": "worker"}],
            "supervisor": {"goals_active": True, "state": "held",
                           "incarnation_id": "inc-x", "heartbeat_age_seconds": 30.0}}
    snap.update(over)
    return snap


SUP_STATUS = json.dumps({"goals_active": True, "incarnation": {"state": "held"},
                         "heartbeat_age_seconds": 30.0, "pending_decision": None})
AGENTS = json.dumps([{"name": "sup|l1|boot", "kind": "background", "status": "busy"},
                     {"name": "w1", "kind": "background", "status": "idle"}])


def _table(sup=SUP_STATUS, agents=AGENTS, agents_rc=0, count="2\n", oldest="1799990000\n"):
    return [
        (lambda a: "sup-status" in a, 0, sup),
        (lambda a: a[:2] == ["claude", "agents"], agents_rc, agents),
        (lambda a: a[:2] == ["git", "rev-list"], 0, count),
        (lambda a: a[:2] == ["git", "log"], 0, oldest),
    ]


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir()
    return tmp_path


def test_happy_path_observation(home):
    (home / "state" / "hook-errors.log").write_text("a\nb\n", encoding="utf-8")
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=lambda: _snapshot(),
                    prev_state={"_hook_error_lines": 1})
    assert obs["goals_active"] is True
    assert obs["claim_state"] == "held"
    assert obs["heartbeat_age_seconds"] == 30.0
    assert obs["pending_decision"] is None
    assert obs["sup_sessions"] == ["sup|l1|boot"]
    assert obs["agents_ok"] is True
    assert obs["registry_ok"] is True and obs["registry_reason"] is None
    assert obs["workers"] == [{"name": "w1", "status": "idle", "mail": 1, "limit_kind": None}]
    assert obs["unpushed"] == 2 and obs["oldest_unpushed_ts"] == 1799990000.0
    assert obs["hook_error_lines"] == 2 and obs["prev_hook_error_lines"] == 1


def test_git_is_run_in_the_fleet_home(home):
    run = _runner(_table())
    k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    git_calls = [kw for a, kw in run.calls if a[0] == "git"]
    assert git_calls and all(kw["cwd"] == str(home) for kw in git_calls)


def test_agents_failure_is_reported_not_raised(home):
    run = _runner(_table(agents="", agents_rc=1))
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["agents_ok"] is False and obs["sup_sessions"] == []


def test_sup_status_garbage_falls_back_to_the_snapshot(home):
    run = _runner(_table(sup="not json"))
    obs = k.collect(home, now=NOW, run=run,
                    snapshot_fn=lambda: _snapshot(supervisor={
                        "goals_active": True, "state": "released",
                        "incarnation_id": None, "heartbeat_age_seconds": None}),
                    prev_state={})
    assert obs["claim_state"] == "released" and obs["pending_decision"] is None


def test_unreadable_registry_is_an_observation_not_an_exception(home):
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run,
                    snapshot_fn=lambda: {"ok": False, "reason": "quarantined",
                                         "workers": [], "supervisor": {
                                             "goals_active": True, "state": "unknown",
                                             "incarnation_id": None,
                                             "heartbeat_age_seconds": None}},
                    prev_state={})
    assert obs["registry_ok"] is False and obs["registry_reason"] == "quarantined"
    assert obs["workers"] == []


def test_no_unpushed_when_rev_list_is_zero(home):
    run = _runner(_table(count="0\n", oldest=""))
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None


def test_missing_hook_errors_log_counts_as_zero(home):
    run = _runner(_table())
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["hook_error_lines"] == 0


def test_a_subprocess_timeout_degrades_to_not_ok(home):
    def run(argv, **kw):
        if argv[:2] == ["claude", "agents"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return _runner(_table())(argv, **kw)
    obs = k.collect(home, now=NOW, run=run, snapshot_fn=_snapshot, prev_state={})
    assert obs["agents_ok"] is False
