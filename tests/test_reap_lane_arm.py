"""Pin the reap predicate's lane arm to a real `fleet land` + wave-close write.

Before this: `_reap_eligible`'s lane arm read `record["lane_state"]` and the
outcome kind, but nothing ever wrote either -- `TOMBSTONE_KINDS` (the only
`append_outcome` caller) never includes "landed"/"abandoned". Every row ever
reaped went through the predecessor-supervisor or daemon-dead arm instead.
`fleet land` is deliberately decoupled from the fleet kernel (it takes no
`--fleet-home` and resolves no home -- see test_fleet_land.py) and would
resolve the wrong `fleet.lock`/registry from a worktree whose FLEET_HOME is
unset, so it cannot safely be the writer. `wave-close` already holds
`fleet.lock` and already knows which lane branches landed
(`_wave_landed_lanes`), so it writes `lane_state=landed` on the matching
registry record (`_wave_mark_landed_lanes`), joined by worktree `cwd` --
the same join `_wave_record_substrate` uses.
"""
import argparse
import json
import subprocess

import pytest

import fleet
import fleet_land


SID = "aaaa1111-1111-2222-3333-444455556666"


def _git(cwd, *args, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if check:
        assert result.returncode == 0, result.stderr
    return result


def _repo_with_lane(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "land tests")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    lane = tmp_path / "lane"
    _git(repo, "worktree", "add", "-qb", "w1/example", str(lane), "main")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, lane, base


def _land_lane(lane, base, monkeypatch, repo):
    payload = {
        "lane": "w1", "base": base, "files_changed": ["README.md"],
        "tests": [{"command": "true", "rc": 0, "passed": 1, "failed": 0, "skipped": 0}],
        "claims": [{"claim": "the command is wired", "command": "true"}],
        "blockers": [],
    }
    report = lane / "docs" / "lanes"
    report.mkdir(parents=True, exist_ok=True)
    (report / "w1.md").write_text("# Lane w1\nDONE means: landable.\n", encoding="utf-8")
    (report / "w1.json").write_text(json.dumps(payload), encoding="utf-8")
    (lane / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(fleet_land, "_check_commands",
                        lambda worktree, tests: [("tests[1]", 0)])
    assert fleet_land.cmd_land(argparse.Namespace(lane="w1")) == 0


def _merge_lane_into_main(repo):
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "w1/example", "-m", "merge(w1/example): test lane")


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "state").mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    fleet.save_registry({"workers": {}})
    return home


def _seed_worker(lane, sid=SID, **fields):
    record = fleet.new_worker_record(sid, str(lane), "test", "accept", dispatch_kind="bg")
    record.update(status="idle", last_activity=fleet.now_iso())
    record.update(fields)
    data = fleet.load_registry()
    data["workers"]["w1"] = record
    fleet.save_registry(data)
    return record


def _entry(sid=SID, **fields):
    result = {"id": sid[:8], "sessionId": sid, "name": "fleet|w1|task",
              "kind": "background", "state": "done"}
    result.update(fields)
    return result


def test_a_real_landed_lane_is_reaped_by_the_lane_arm_specifically(
        tmp_path, monkeypatch, home):
    repo, lane, base = _repo_with_lane(tmp_path)
    _land_lane(lane, base, monkeypatch, repo)
    _merge_lane_into_main(repo)
    _seed_worker(lane)

    lanes = fleet._wave_landed_lanes(repo, base, run=subprocess.run)
    assert lanes and lanes[0][0] == "w1/example"

    with fleet.fleet_lock():
        marked = fleet._wave_mark_landed_lanes(repo, lanes, run=subprocess.run)
    assert marked == ["w1"]

    record = fleet.load_registry()["workers"]["w1"]
    assert record["lane_state"] == "landed"

    eligible, reason = fleet._reap_eligible(
        "w1", record, [_entry(status="idle")], None)
    assert (eligible, reason) == (True, "lane-landed")


def test_a_lane_that_has_not_landed_is_lane_not_terminal_and_survives(home, tmp_path):
    lane = tmp_path / "lane"
    lane.mkdir()
    record = _seed_worker(lane)

    eligible, reason = fleet._reap_eligible(
        "w1", record, [_entry(status="idle")], None)
    assert (eligible, reason) == (False, "lane-not-terminal")


def test_landed_lane_protections_survive_the_real_writer(
        tmp_path, monkeypatch, home):
    """A live PID vetoes reaping even once the writer records the landing."""
    repo, lane, base = _repo_with_lane(tmp_path)
    _land_lane(lane, base, monkeypatch, repo)
    _merge_lane_into_main(repo)
    _seed_worker(lane)

    lanes = fleet._wave_landed_lanes(repo, base, run=subprocess.run)
    with fleet.fleet_lock():
        fleet._wave_mark_landed_lanes(repo, lanes, run=subprocess.run)
    record = fleet.load_registry()["workers"]["w1"]
    assert record["lane_state"] == "landed"

    eligible, reason = fleet._reap_eligible(
        "w1", record, [_entry(status="idle", pid=4242)], None)
    assert (eligible, reason) == (False, "roster-live")
