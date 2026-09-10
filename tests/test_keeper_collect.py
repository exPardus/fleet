"""collect() turns four read-only sources into one observation dict.
Every subprocess goes through the injected `run`; nothing here touches a
real fleet, tmux, or claude.

The w56 git tests at the bottom DO drive real git -- through that same `run`
seam, with the real `subprocess.run` behind it, in a throwaway repo under
`tmp_path`. A stub can pin the argv the keeper sends; only git can answer what
that argv MEANS in the two situations this host was actually in."""
import io
import json
import os
import shutil
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
           count_rc=0, oldest="1799990000\n",
           remote_refs="refs/remotes/origin/main\n", remote_refs_rc=0,
           head_ref="server/persistent-fleet\n", head_ref_rc=0):
    """`remote_refs` is the w56 probe: `--not --remotes` subtracts NOTHING in a
    repo with no remote-tracking refs, so the count there is the whole history
    at rc 0. The probe is what turns that into "cannot tell", and it is the
    first git call the keeper makes."""
    return [
        (lambda a: "sup-status" in a, 0, sup),
        (lambda a: a[:2] == ["claude", "agents"], agents_rc, agents),
        (lambda a: a[:2] == ["git", "for-each-ref"], remote_refs_rc, remote_refs),
        (lambda a: a[:2] == ["git", "rev-parse"], head_ref_rc, head_ref),
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
    assert obs["claim_in_roster"] is True
    assert obs["claim_row_status"] == "busy"
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
    assert obs["claim_sid"] is None and obs["claim_in_roster"] is False
    assert obs["claim_row_status"] is None


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
    assert obs["claim_in_roster"] is True and obs["claim_row_status"] == "busy"


def test_a_supervisor_shaped_name_from_another_launch_is_not_the_claim(home):
    other = json.dumps([{"name": "sup|other-launch|boot",
                         "sessionId": "some-other-sid", "status": "busy"}])
    obs = _collect(home, _runner(_table(agents=other)))
    assert obs["claim_sid"] == SUP_SID
    assert obs["claim_in_roster"] is False and obs["claim_row_status"] is None


def test_a_non_string_session_id_is_normalised_before_the_roster_test(home):
    """Re-review minor 2: the roster membership test used to run on the RAW
    projection value, while `claim_sid` just above it was already
    type-normalised. A non-str `session_id` (a dict, from a malformed or
    hostile sup-status projection) made `in` on a set raise `TypeError`,
    which killed the tick. C swapped that set for a sid->status mapping and
    a dict key lookup hashes its operand exactly the same way, so the
    normalisation is still what stands between a bad projection and a dead
    tick. The normalised value must be what every roster field is built
    from."""
    weird = json.dumps({"goals_active": True,
                        "incarnation": {"state": None, "session_id": {"x": 1},
                                        "released_at": None},
                        "heartbeat_age_seconds": 30.0, "pending_decision": None})
    obs = _collect(home, _runner(_table(sup=weird)))
    assert obs["claim_sid"] is None
    assert obs["claim_in_roster"] is False and obs["claim_row_status"] is None


def test_an_absent_claim_sid_is_never_live(home):
    no_sid = json.dumps({"goals_active": True, "incarnation": None,
                         "heartbeat_age_seconds": None, "pending_decision": None})
    obs = _collect(home, _runner(_table(sup=no_sid)))
    assert obs["claim_sid"] is None and obs["claim_in_roster"] is False
    assert obs["claim_row_status"] is None


# --- C (G-K6 wave 1): the row's `status`, not merely the row ---------------

def test_the_claim_rows_status_reaches_the_observation(home):
    """MEASURED (w61 §3, claude 2.1.267): a background session reads
    `status: "busy"` inside its turn and `"idle"` between turns, with a live
    pid either way. The keeper used to keep only the sid and throw the value
    away, which is why it watched a dark fleet for 8h10m."""
    idle = json.dumps([{"name": "sup|l1|boot", "sessionId": SUP_SID,
                        "kind": "background", "state": "working",
                        "status": "idle", "pid": 303182}])
    obs = _collect(home, _runner(_table(agents=idle)))
    assert obs["claim_in_roster"] is True
    assert obs["claim_row_status"] == "idle"
    stale = {**obs, "heartbeat_age_seconds": 29451.0}
    assert "supervisor-stalled" in [p.rule for p in k.evaluate(stale, NOW)]


def test_a_dead_row_keeps_its_sid_and_carries_no_status_key(home):
    """MEASURED (w61 §2): a dead body's row is exactly
    `['cwd','id','kind','name','sessionId','startedAt','state']` -- `status`
    and `pid` are ABSENT from the object, not present-and-null -- and such a
    row stays in the PLAIN spelling indefinitely (one was 22h05m old when
    measured). `row["status"]` here would raise and kill the tick, failing
    the alarm CLOSED. It must read as listed-with-no-live-process."""
    corpse = json.dumps([{"name": "sup|l1|boot", "sessionId": SUP_SID,
                          "kind": "background", "state": "blocked",
                          "cwd": "/home/altai/proga/fleet",
                          "startedAt": "2026-09-09T16:29:31Z"}])
    obs = _collect(home, _runner(_table(agents=corpse)))
    assert obs["claim_in_roster"] is True
    assert obs["claim_row_status"] is None
    stale = {**obs, "heartbeat_age_seconds": 29451.0}
    assert "supervisor-stalled" in [p.rule for p in k.evaluate(stale, NOW)]


def test_a_non_string_status_on_the_claim_row_is_not_a_working_body(home):
    """The roster crosses a process boundary. A `status` that is not a
    non-empty string is normalised to None -- the corpse reading -- so a
    malformed row can never silence the alarm."""
    for bad in ({"x": 1}, [], 7, "", None):
        weird = json.dumps([{"name": "s", "sessionId": SUP_SID, "status": bad}])
        obs = _collect(home, _runner(_table(agents=weird)))
        assert obs["claim_in_roster"] is True, bad
        assert obs["claim_row_status"] is None, bad


def test_the_keeper_asks_the_plain_spelling_and_never_all(home):
    """The two spellings are different lists: `--all` adds the terminal-state
    rows (`done`/`failed`/`stopped`). Every claim the keeper makes is about
    the plain one, and `bin/fleet.py`'s roster call -- which DOES use
    `--all` -- is a different surface. Pinned so nobody mixes them."""
    run = _runner(_table())
    _collect(home, run)
    agents = [argv for argv, _ in run.calls if argv[:2] == ["claude", "agents"]]
    assert agents == [["claude", "agents", "--json"]]


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
    assert obs["claim_in_roster"] is False and obs["claim_row_status"] is None


def test_a_subprocess_timeout_degrades_to_not_ok(home):
    def run(argv, **kw):
        if argv[:2] == ["claude", "agents"]:
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        return _runner(_table())(argv, **kw)
    obs = _collect(home, run)
    assert obs["agents_ok"] is False and obs["agents_missing"] is False


def test_garbage_from_claude_agents_is_not_a_live_session(home):
    obs = _collect(home, _runner(_table(agents='{"not": "a list"}')))
    assert obs["agents_ok"] is False and obs["claim_in_roster"] is False
    assert obs["claim_row_status"] is None


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


# --- w56: the unpushed measure is about RISK, not a fixed pair of ref names --
#
# Measured on this host 2026-09-09. `_git_unpushed` asked `origin/main..main`,
# which is a claim about two ref NAMES; this fleet works on
# `server/persistent-fleet`. At `f4aa63f` (the page at 01:26:01Z) the rule said
# **2** while **21** commits existed on one disk and on no remote -- the entire
# server bring-up, 19 commits, invisible to the rule during the exact window it
# exists to cover. Four hours later those same 2 commits were fully contained
# in `origin/server/persistent-fleet` and at no risk at all, and the rule would
# have re-paged about them every six hours forever. Both numbers are re-derived
# from real git below.

def test_the_unpushed_count_is_measured_against_every_remote_not_origin_main():
    """The ref pair is gone. `HEAD --not --remotes` names no branch, so it
    cannot go blind when the work moves off `main` -- which is the only reason
    the old measure missed 19 of 21 at-risk commits."""
    run = _runner(_table(count="21\n"))
    n, oldest, ref = k._git_unpushed(".", run, out=io.StringIO())
    git = [a for a, _ in run.calls if a[0] == "git"]
    assert n == 21
    joined = " ".join(" ".join(a) for a in git)
    assert "origin/main..main" not in joined, joined
    rev_list = [a for a in git if a[:2] == ["git", "rev-list"]]
    log = [a for a in git if a[:2] == ["git", "log"]]
    assert rev_list == [["git", "rev-list", "--count", "HEAD", "--not", "--remotes"]]
    # the age half must move with the count, or the gate and the fingerprint
    # go stale in a new way: the same rev set, not a second one
    assert log and log[0][-3:] == ["HEAD", "--not", "--remotes"]


def test_a_repo_with_no_remote_tracking_refs_cannot_tell_and_never_counts_history(home):
    """The single most likely way to make this rule WORSE than it was. With no
    remote-tracking ref, `--not --remotes` subtracts nothing, so `rev-list`
    counts the ENTIRE history and exits 0 -- a fresh repo pages "5 commits
    unpushed", this one would page about ten thousand. The probe runs first and
    the count is not even attempted."""
    out = io.StringIO()
    run = _runner(_table(remote_refs="", count="10000\n"))
    obs = _collect(home, run, out=out)
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None
    assert "keeper: git unpushed check unavailable" in out.getvalue()
    assert not [a for a, _ in run.calls if a[:2] == ["git", "rev-list"]]
    assert "unpushed" not in [p.rule for p in k.evaluate(obs, NOW)]


def test_a_failed_remote_ref_probe_is_cannot_tell_too(home):
    """`for-each-ref` exiting non-zero means the home is not a readable repo at
    all. Same direction: say so, page nothing."""
    out = io.StringIO()
    run = _runner(_table(remote_refs="", remote_refs_rc=128, count="9\n"))
    obs = _collect(home, run, out=out)
    assert obs["unpushed"] == 0
    assert "keeper: git unpushed check unavailable" in out.getvalue()
    assert not [a for a, _ in run.calls if a[:2] == ["git", "rev-list"]]


def test_the_oldest_timestamp_is_the_minimum_not_whatever_traversal_printed_first(home):
    """`git log` orders by commit date subject to a topological constraint, so
    with a skewed clock (or a merge of an old local branch) the first line of
    `--reverse` is not necessarily the oldest. The age gate and the fingerprint
    both depend on this being the true minimum."""
    obs = _collect(home, _runner(_table(count="3\n",
                                        oldest="1799990000\n1700000000\n1799995000\n")))
    assert obs["unpushed"] == 3
    assert obs["oldest_unpushed_ts"] == 1700000000.0


def test_an_unreadable_count_is_cannot_tell_not_zero(home):
    out = io.StringIO()
    obs = _collect(home, _runner(_table(count="not a number\n")), out=out)
    assert obs["unpushed"] == 0 and obs["oldest_unpushed_ts"] is None
    assert "keeper: git unpushed check unavailable" in out.getvalue()


def test_the_observation_names_the_ref_it_measured(home):
    obs = _collect(home, _runner(_table(count="3\n")))
    assert obs["unpushed_ref"] == "server/persistent-fleet"


def test_a_detached_head_is_named_as_one(home):
    """`rev-parse --abbrev-ref HEAD` prints the literal string `HEAD` when
    detached -- which is also a legal branch name-shaped answer, and reads as
    nonsense in a page. A detached HEAD is the state where naming the ref
    matters most: nothing but the reflog points at that work."""
    obs = _collect(home, _runner(_table(count="1\n", head_ref="HEAD\n",
                                        oldest="1799000000\n")))
    assert obs["unpushed_ref"] == "a detached HEAD"
    page = [p for p in k.evaluate(obs, NOW) if p.rule == "unpushed"][0]
    assert "on a detached HEAD" in page.text


def test_a_ref_that_cannot_be_named_still_pages_the_count(home):
    """The name is for the operator's benefit only; failing to read it must
    never suppress the page."""
    obs = _collect(home, _runner(_table(count="4\n", head_ref="", head_ref_rc=128,
                                        oldest="1799000000\n")))
    assert obs["unpushed"] == 4 and obs["unpushed_ref"] is None
    page = [p for p in k.evaluate(obs, NOW) if p.rule == "unpushed"][0]
    assert "4 commits unpushed for" in page.text


# --- w56: the two situations this host was actually in, against real git ----

def _rule_obs(n, oldest, ref):
    """A quiet observation carrying only the git half, so `evaluate` sees the
    unpushed rule and nothing else."""
    return {"goals_active": True, "claim_state": "held", "claim_sid": None,
            "claim_in_roster": True, "claim_row_status": "busy",
            "heartbeat_age_seconds": 1.0,
            "agents_ok": True, "agents_missing": False, "registry_ok": True,
            "pending_decision": None, "workers": [],
            "unpushed": n, "oldest_unpushed_ts": oldest, "unpushed_ref": ref,
            "hook_error_lines": 0, "prev_hook_error_lines": 0}


GIT_ENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def _git_or_skip():
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    return git


def _git_runner():
    """The same `run` seam, with REAL git behind it and the two non-git sources
    still stubbed -- `claude agents` must not shell out to the operator's real
    claude, and there is no fleet install in a tmp home."""
    stub = _runner([(lambda a: "sup-status" in a, 1, ""),
                    (lambda a: a[:2] == ["claude", "agents"], 0, AGENTS)])

    def run(argv, **kw):
        if list(argv)[:1] == ["git"]:
            return subprocess.run(list(argv), env=GIT_ENV, **kw)
        return stub(argv, **kw)
    run.calls = stub.calls
    return run


class _Repo:
    """A real repository with a real remote, built in tmp_path."""

    def __init__(self, path):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args, check=True):
        cp = subprocess.run([_git_or_skip(), "-c", "commit.gpgsign=false", *args],
                            cwd=str(self.path), env=GIT_ENV,
                            capture_output=True, text=True)
        if check:
            assert cp.returncode == 0, (args, cp.stdout, cp.stderr)
        return cp

    def commit(self, name):
        (self.path / name).write_text(name, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", name)

    def count(self, *revs):
        return int(self.git("rev-list", "--count", *revs).stdout.strip())


def _seeded(tmp_path):
    """`main` with one commit, pushed to a bare `origin`."""
    _git_or_skip()
    bare = tmp_path / "origin.git"
    subprocess.run([_git_or_skip(), "init", "-q", "--bare", "-b", "main", str(bare)],
                   env=GIT_ENV, capture_output=True, text=True, check=True)
    repo = _Repo(tmp_path / "work")
    repo.commit("seed")
    repo.git("remote", "add", "origin", str(bare))
    repo.git("push", "-q", "-u", "origin", "main")
    return repo


def test_a_branch_ahead_of_its_remote_pages_the_true_count_while_main_is_not(tmp_path):
    """THE HOST AT `f4aa63f`. `main` carries 2 commits `origin/main` has not
    seen; the working branch carries those 2 plus 3 more that exist nowhere
    else. The old measure answered 2. What is at risk is 5."""
    repo = _seeded(tmp_path)
    for name in ("m1", "m2"):
        repo.commit(name)                      # main, ahead of origin/main by 2
    repo.git("checkout", "-q", "-b", "server/persistent-fleet")
    for name in ("s1", "s2", "s3"):
        repo.commit(name)
    assert repo.count("origin/main..main") == 2       # what the old rule saw
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=io.StringIO())
    assert n == 5, "the count must be every commit on no remote, not origin/main..main"
    assert ref == "server/persistent-fleet"
    assert oldest is not None
    page = [p for p in k.evaluate(_rule_obs(n, oldest, ref), NOW) if p.rule == "unpushed"]
    assert page and "5 commits unpushed on server/persistent-fleet" in page[0].text


def test_work_contained_on_a_remote_under_another_name_never_pages(tmp_path):
    """THE HOST FOUR HOURS LATER, and the false page this task exists to end.
    `main` is still 2 commits ahead of `origin/main` -- but every one of them
    is contained in `origin/server/persistent-fleet`, so nothing is at risk and
    nothing may page. `main` has no upstream relationship to that ref, and the
    branch was pushed under a DIFFERENT name."""
    repo = _seeded(tmp_path)
    for name in ("m1", "m2"):
        repo.commit(name)
    repo.git("checkout", "-q", "-b", "local-name")
    repo.git("push", "-q", "origin", "local-name:server/persistent-fleet")
    assert repo.count("origin/main..main") == 2       # the old rule still says 2
    assert repo.git("rev-parse", "--abbrev-ref", "local-name@{u}",
                    check=False).returncode != 0      # and there is no upstream
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=io.StringIO())
    assert (n, oldest) == (0, None)
    assert k.evaluate(_rule_obs(n, oldest, ref), NOW) == []


def test_a_repo_with_no_remotes_at_all_counts_nothing_against_real_git(tmp_path):
    """Against real git, not a stub: five commits, no remote, and the naive
    command returns 5 at rc 0. The keeper must answer "cannot tell"."""
    _git_or_skip()
    repo = _Repo(tmp_path / "solo")
    for name in ("a", "b", "c", "d", "e"):
        repo.commit(name)
    assert repo.count("HEAD", "--not", "--remotes") == 5   # the hazard, measured
    out = io.StringIO()
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=out)
    assert (n, oldest) == (0, None)
    assert "keeper: git unpushed check unavailable" in out.getvalue()


def test_a_detached_head_counts_the_work_only_the_reflog_holds(tmp_path):
    repo = _seeded(tmp_path)
    repo.git("checkout", "-q", "--detach")
    repo.commit("orphan")
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=io.StringIO())
    assert n == 1 and oldest is not None
    assert ref == "a detached HEAD"


def test_a_repo_mid_rebase_is_measured_and_does_not_crash_the_tick(tmp_path):
    """A conflicted rebase leaves HEAD detached at the new base with the
    replayed commits already made. `rev-list` still answers; the tick must not
    raise and must not go silent."""
    repo = _seeded(tmp_path)
    repo.git("checkout", "-q", "-b", "topic")
    (repo.path / "f").write_text("topic\n", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "topic")
    repo.git("checkout", "-q", "main")
    (repo.path / "f").write_text("other\n", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "other")
    repo.git("checkout", "-q", "topic")
    conflicted = repo.git("rebase", "main", check=False)
    assert conflicted.returncode != 0, "the rebase was meant to conflict"
    assert (repo.path / ".git" / "rebase-merge").exists()
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=io.StringIO())
    assert n >= 1 and oldest is not None
    repo.git("rebase", "--abort")


def test_an_empty_repo_with_a_remote_is_cannot_tell(tmp_path):
    """No commits at all: `HEAD` is not a revision and `rev-list` exits 128."""
    _git_or_skip()
    bare = tmp_path / "origin.git"
    subprocess.run([_git_or_skip(), "init", "-q", "--bare", "-b", "main", str(bare)],
                   env=GIT_ENV, capture_output=True, text=True, check=True)
    repo = _Repo(tmp_path / "empty")
    repo.git("remote", "add", "origin", str(bare))
    out = io.StringIO()
    n, oldest, ref = k._git_unpushed(repo.path, subprocess.run, out=out)
    assert (n, oldest) == (0, None)
    assert "keeper: git unpushed check unavailable" in out.getvalue()
