"""`fleet abandon` records lane_state=abandoned for a lane with nothing to land."""
import subprocess
import uuid

import pytest

import fleet


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    return r


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    return home


@pytest.fixture
def repo(tmp_path, monkeypatch):
    tmp_path = tmp_path / "repo"
    tmp_path.mkdir()
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a").write_text("a\n")
    _git(tmp_path, "add", "a")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "branch", "lane/one")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _seed(isolated_home, status="idle", branch="lane/one"):
    sid = str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, str(fleet.FLEET_HOME), "t", "dontask",
                                  dispatch_kind="bg", branch=branch)
    rec["status"] = status
    fleet.save_registry({"workers": {"w1": rec}})
    return sid


def _run(*argv):
    return fleet.cmd_abandon(fleet.build_parser().parse_args(["abandon", "w1", *argv]))


def test_records_state_reason_outcome_event(isolated_home, repo, capsys):
    sid = _seed(isolated_home)
    assert _run("--reason", "superseded by HEAD") == 0
    rec = fleet.load_registry()["workers"]["w1"]
    assert rec["lane_state"] == "abandoned"
    assert rec["abandoned_reason"] == "superseded by HEAD"
    assert fleet.latest_outcome("w1", sid)["kind"] == "abandoned"
    events = [e for e in fleet.events_path().read_text().splitlines() if '"abandoned"' in e]
    assert len(events) == 1 and "superseded by HEAD" in events[0]
    out = capsys.readouterr().out
    assert "next reap" in out and "left in place" in out


def test_reap_predicate_honours_it(isolated_home, repo):
    _seed(isolated_home)
    _run("--reason", "x")
    rec = fleet.load_registry()["workers"]["w1"]
    ok, why = fleet._reap_eligible("w1", rec, [], None)
    assert (ok, why) == (True, "lane-abandoned")


def test_refuses_branch_ahead_of_head_unless_force(isolated_home, repo):
    _seed(isolated_home)
    _git(repo, "checkout", "-q", "lane/one")
    (repo / "b").write_text("b\n")
    _git(repo, "add", "b")
    _git(repo, "commit", "-qm", "lane work")
    _git(repo, "checkout", "-q", "-")
    with pytest.raises(fleet.FleetCliError, match="1 commit"):
        _run("--reason", "x")
    assert "lane_state" not in fleet.load_registry()["workers"]["w1"] or \
        fleet.load_registry()["workers"]["w1"]["lane_state"] is None
    assert _run("--reason", "x", "--force") == 0
    assert fleet.load_registry()["workers"]["w1"]["lane_state"] == "abandoned"


@pytest.mark.parametrize("status", ["working", "attached"])
def test_refuses_busy_lane(isolated_home, repo, status):
    _seed(isolated_home, status=status)
    with pytest.raises(fleet.FleetCliError, match="interrupt"):
        _run("--reason", "x", "--force")


def test_missing_branch_ref_has_no_commits(isolated_home, repo):
    _seed(isolated_home, branch="lane/gone")
    assert _run("--reason", "x") == 0


def test_empty_reason_and_unknown_worker_refuse(isolated_home, repo):
    _seed(isolated_home)
    with pytest.raises(fleet.FleetCliError, match="reason"):
        _run("--reason", "  ")
    with pytest.raises(fleet.FleetCliError, match="unknown"):
        fleet.cmd_abandon(fleet.build_parser().parse_args(
            ["abandon", "nope", "--reason", "x"]))


def test_leaves_worktree_and_branch(isolated_home, repo):
    _seed(isolated_home)
    _run("--reason", "x")
    assert _git(repo, "rev-parse", "--verify", "refs/heads/lane/one").returncode == 0
