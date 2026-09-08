"""collect() turns four read-only sources into one observation dict.
Every subprocess goes through the injected `run`; nothing here touches a
real fleet, git, tmux, or claude."""
import io
import json
import subprocess

import pytest

import fleet_keeper as k

NOW = 1_800_000_000.0
SUP_SID = "11111111-2222-3333-4444-555555555555"


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


# The projection `sup-status --json` really publishes for a HELD claim: the
# allowlist copies the claim's raw `state` key, which ONLY `sup-release` ever
# writes -- so a live claim publishes `state: None`. That is C1's whole story,
# and the fixture states it rather than an idealised shape.
HELD_PROJECTION = {"incarnation_id": "inc-x", "session_id": SUP_SID,
                   "state": None, "released_at": None}
SUP_STATUS = json.dumps({"goals_active": True, "incarnation": HELD_PROJECTION,
                         "heartbeat_age_seconds": 30.0, "pending_decision": None})
AGENTS = json.dumps([{"name": "sup|l1|boot", "sessionId": SUP_SID,
                      "kind": "background", "status": "busy"},
                     {"name": "w1", "sessionId": "w1-sid",
                      "kind": "background", "status": "idle"}])


def _table(sup=SUP_STATUS, agents=AGENTS, agents_rc=0, count="2\n",
           count_rc=0, oldest="1799990000\n"):
    return [
        (lambda a: "sup-status" in a, 0, sup),
        (lambda a: a[:2] == ["claude", "agents"], agents_rc, agents),
        (lambda a: a[:2] == ["git", "rev-list"], count_rc, count),
        (lambda a: a[:2] == ["git", "log"], 0, oldest),
    ]


@pytest.fixture
def home(tmp_path):
    (tmp_path / "state").mkdir()
    return tmp_path


def _collect(home, run, snapshot_fn=_snapshot, prev_state=None, out=None):
    return k.collect(home, now=NOW, run=run, snapshot_fn=snapshot_fn,
                     prev_state=prev_state or {}, out=out or io.StringIO())


def test_happy_path_observation(home):
    (home / "state" / "hook-errors.log").write_text("a\nb\n", encoding="utf-8")
    obs = _collect(home, _runner(_table()), prev_state={"_hook_error_lines": 1})
    assert obs["goals_active"] is True
    assert obs["claim_state"] == "held"
    assert obs["claim_sid"] == SUP_SID
    assert obs["claim_sid_live"] is True
    assert obs["heartbeat_age_seconds"] == 30.0
    assert obs["pending_decision"] is None
    assert obs["agents_ok"] is True and obs["agents_missing"] is False
    assert obs["registry_ok"] is True and obs["registry_reason"] is None
    assert obs["workers"] == [{"name": "w1", "status": "idle", "mail": 1, "limit_kind": None}]
    assert obs["unpushed"] == 2 and obs["oldest_unpushed_ts"] == 1799990000.0
    assert obs["hook_error_lines"] == 2 and obs["prev_hook_error_lines"] == 1


# --- C1: the claim state comes from the snapshot, always -------------------

def test_a_held_claim_reads_as_held_not_unknown(home):
    """C1, measured live: `_project_claim` copies the claim's `state` key and
    only `sup-release` writes it, so a HELD claim's projection carries
    `state: None`. Deriving `claim_state` from that put every live
    supervisor into the dead-trigger set. The snapshot's
    `_supervisor_tier_snapshot` is the normaliser, so it is the source."""
    obs = _collect(home, _runner(_table()))
    assert obs["claim_state"] == "held"


def test_the_snapshot_wins_even_when_sup_status_says_otherwise(home):
    contradicting = json.dumps({"goals_active": False,
                                "incarnation": {"state": "released",
                                                "session_id": SUP_SID},
                                "heartbeat_age_seconds": 5.0,
                                "pending_decision": None})
    obs = _collect(home, _runner(_table(sup=contradicting)))
    assert obs["claim_state"] == "held"      # from the snapshot
    assert obs["goals_active"] is True       # from the snapshot
    assert obs["heartbeat_age_seconds"] == 5.0   # from sup-status
    assert obs["claim_sid"] == SUP_SID           # from sup-status


def test_sup_status_garbage_falls_back_to_the_snapshot(home):
    obs = _collect(home, _runner(_table(sup="not json")),
                   snapshot_fn=lambda: _snapshot(supervisor={
                       "goals_active": True, "state": "released",
                       "incarnation_id": None, "heartbeat_age_seconds": None}))
    assert obs["claim_state"] == "released"
    assert obs["pending_decision"] is None
    assert obs["claim_sid"] is None and obs["claim_sid_live"] is False


def test_the_released_timestamp_is_carried_for_the_since_clause(home):
    released = json.dumps({"goals_active": True,
                           "incarnation": {"state": "released",
                                           "session_id": SUP_SID,
                                           "released_at": "2026-09-08T04:00:00Z"},
                           "heartbeat_age_seconds": None,
                           "pending_decision": None})
    obs = _collect(home, _runner(_table(sup=released)))
    assert obs["released_at"] == "2026-09-08T04:00:00Z"


# --- C2: the roster join is on the claim's sid -----------------------------

def test_the_claim_session_is_looked_up_by_sid_not_by_name(home):
    """An `ai-title` rename can overwrite `name` after a resume, and the
    prefix `sup|` matches a body from ANY launch. The sid identifies one
    session."""
    renamed = json.dumps([{"name": "Investigating the flaky pin",
                           "sessionId": SUP_SID, "status": "busy"}])
    obs = _collect(home, _runner(_table(agents=renamed)))
    assert obs["claim_sid_live"] is True


def test_a_supervisor_shaped_name_from_another_launch_is_not_the_claim(home):
    other = json.dumps([{"name": "sup|other-launch|boot",
                         "sessionId": "some-other-sid", "status": "busy"}])
    obs = _collect(home, _runner(_table(agents=other)))
    assert obs["claim_sid"] == SUP_SID
    assert obs["claim_sid_live"] is False


def test_an_absent_claim_sid_is_never_live(home):
    no_sid = json.dumps({"goals_active": True, "incarnation": None,
                         "heartbeat_age_seconds": None, "pending_decision": None})
    obs = _collect(home, _runner(_table(sup=no_sid)))
    assert obs["claim_sid"] is None and obs["claim_sid_live"] is False


# --- C4: the pending decision is a dict, and an answered one is not a freeze -

def test_the_pending_decision_yields_the_question_string(home):
    pending = json.dumps({"goals_active": True, "incarnation": HELD_PROJECTION,
                          "heartbeat_age_seconds": 30.0,
                          "pending_decision": {"question": "ship M-F?",
                                               "raised_by_inc": "inc-x",
                                               "raised_at": "2026-09-08T04:00:00Z",
                                               "answer": None}})
    obs = _collect(home, _runner(_table(sup=pending)))
    assert obs["pending_decision"] == "ship M-F?"


def test_an_answered_decision_is_not_a_freeze(home):
    answered = json.dumps({"goals_active": True, "incarnation": HELD_PROJECTION,
                           "heartbeat_age_seconds": 30.0,
                           "pending_decision": {"question": "ship M-F?",
                                                "answer": "yes, ship it"}})
    obs = _collect(home, _runner(_table(sup=answered)))
    assert obs["pending_decision"] is None
    assert "supervisor-frozen" not in [p.rule for p in k.evaluate(obs, NOW)]


def test_a_bare_string_pending_decision_is_accepted(home):
    older = json.dumps({"goals_active": True, "incarnation": HELD_PROJECTION,
                        "heartbeat_age_seconds": 30.0,
                        "pending_decision": "ship M-F?"})
    obs = _collect(home, _runner(_table(sup=older)))
    assert obs["pending_decision"] == "ship M-F?"


# --- I2: a missing binary is not a failed one ------------------------------

def test_a_missing_claude_binary_is_reported_distinctly(home):
    def run(argv, **kw):
        if argv[:2] == ["claude", "agents"]:
            raise FileNotFoundError(2, "No such file or directory: 'claude'")
        return _runner(_table())(argv, **kw)
    obs = _collect(home, run)
    assert obs["agents_ok"] is False and obs["agents_missing"] is True


def test_agents_failure_is_reported_not_raised(home):
    obs = _collect(home, _runner(_table(agents="", agents_rc=1)))
    assert obs["agents_ok"] is False and obs["agents_missing"] is False
    assert obs["claim_sid_live"] is False


def test_a_subprocess_timeout_degrades_to_not_ok(home):
    def run(argv, **kw):
        if argv[:2] == ["claude", "agents"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return _runner(_table())(argv, **kw)
    obs = _collect(home, run)
    assert obs["agents_ok"] is False and obs["agents_missing"] is False


def test_garbage_from_claude_agents_is_not_a_live_session(home):
    obs = _collect(home, _runner(_table(agents='{"not": "a list"}')))
    assert obs["agents_ok"] is False and obs["claim_sid_live"] is False


# --- registry ---------------------------------------------------------------

def test_unreadable_registry_is_an_observation_not_an_exception(home):
    obs = _collect(home, _runner(_table()),
                   snapshot_fn=lambda: {"ok": False, "reason": "quarantined",
                                        "workers": [], "supervisor": {
                                            "goals_active": True, "state": "unknown",
                                            "incarnation_id": None,
                                            "heartbeat_age_seconds": None}})
    assert obs["registry_ok"] is False and obs["registry_reason"] == "quarantined"
    assert obs["workers"] == []


def test_a_never_initialised_home_keeps_its_own_reason(home):
    obs = _collect(home, _runner(_table()),
                   snapshot_fn=lambda: {"ok": False, "reason": "not_initialized",
                                        "workers": [], "supervisor": {
                                            "goals_active": False, "state": "none",
                                            "incarnation_id": None,
                                            "heartbeat_age_seconds": None}})
    assert obs["registry_reason"] == "not_initialized"
    assert [p.rule for p in k.evaluate(obs, NOW)] == ["not-initialised"]


# --- git --------------------------------------------------------------------

def test_git_is_run_in_the_fleet_home(home):
    run = _runner(_table())
    _collect(home, run)
    git_calls = [kw for a, kw in run.calls if a[0] == "git"]
    assert git_calls and all(kw["cwd"] == str(home) for kw in git_calls)


def test_no_unpushed_when_rev_list_is_zero(home):
    obs = _collect(home, _runner(_table(count="0\n", oldest="")))
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None


def test_an_unavailable_upstream_says_so_and_pages_nothing(home):
    """A clone with no `origin/main` makes `rev-list` exit non-zero. That is
    "cannot tell", not "nothing unpushed" -- and it is certainly not a page."""
    out = io.StringIO()
    run = _runner(_table(count_rc=128, count=""))
    obs = _collect(home, run, out=out)
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None
    assert "keeper: git unpushed check unavailable" in out.getvalue()
    assert not [a for a, _ in run.calls if a[:2] == ["git", "log"]]
    assert "unpushed" not in [p.rule for p in k.evaluate(obs, NOW)]


def test_missing_hook_errors_log_counts_as_zero(home):
    obs = _collect(home, _runner(_table()))
    assert obs["hook_error_lines"] == 0
