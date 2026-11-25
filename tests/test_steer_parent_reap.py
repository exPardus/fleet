"""A fork-steer stops the parent session it retired.

`fleet send` to an idle ordinary worker forks a new session with `--resume`;
the parent's process stayed resident until `fleet kill`, so lanes collected
one ~0.35 GB idle process per steer. After the fork commits, send now stops
the parent through the supervisor-fork retirement path, under its rules: the
fork must be roster-live, the parent idle with a pid, its mailbox empty, and
its sid owned by this row alone (never the caller's own session).
"""
import json
from types import SimpleNamespace

import pytest

import fleet


OLD = "a0000101-0000-4000-8000-000000000101"
NEW = "a0000102-0000-4000-8000-000000000102"
OLDER = "a0000100-0000-4000-8000-000000000100"
NAME = "lane-a"


def row(sid, state="working", status="idle", **fields):
    return dict(id=sid[:8], sessionId=sid, name=NAME, state=state,
                status=status, pid=4242, **fields)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MCX_WORKER", "1")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for directory in ("state", "logs", "mailbox", "supervisor"):
        (tmp_path / directory).mkdir()
    record = fleet.new_worker_record(OLD, str(tmp_path), "task", "accept",
                                     dispatch_kind="bg")
    record.update(status="idle", retired_sids=[],
                  last_dispatch_at="2026-01-01T00:00:00Z")
    fleet.save_registry({"workers": {NAME: record}})
    fleet.append_outcome(NAME, {"kind": "result", "session_id": OLD,
                                "ts": fleet.now_iso()})
    return tmp_path


def fake_daemon(entries):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "agents":
            return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
        assert argv[1] == "stop", argv
        matched = [r for r in entries if r["id"] == argv[2]]
        assert len(matched) == 1
        matched[0].pop("pid", None)
        matched[0]["state"] = "done"
        return SimpleNamespace(returncode=0, stdout="Stopped", stderr="")

    return run, calls


def stops(calls):
    return [argv[2] for argv in calls if argv[1] == "stop"]


def _steer(monkeypatch, entries, on_dispatch=None):
    run, calls = fake_daemon(entries)

    def dispatch(*args, **kwargs):
        assert kwargs.get("resume_sid") == OLD   # an ordinary worker forks
        assert not stops(calls)                  # never before the fork exists
        entries.append(row(NEW, status="busy"))
        if on_dispatch:
            on_dispatch()
        return {"session_id": NEW, "short_id": NEW[:8]}

    monkeypatch.setattr(fleet, "dispatch_bg", dispatch)
    sleeps = []
    rc = fleet._cmd_send_native(NAME, "next step", run=run,
                                which=lambda _: "claude", sleep=sleeps.append)
    return rc, calls


@pytest.mark.parametrize("parent_state", ["working", "done"])
def test_fork_steer_stops_the_idle_parent_and_keeps_history(home, monkeypatch,
                                                            parent_state):
    rc, calls = _steer(monkeypatch, [row(OLD, state=parent_state)])
    assert rc == 0
    assert stops(calls) == [OLD[:8]]
    record = fleet.load_registry()["workers"][NAME]
    assert record["session_id"] == NEW
    assert OLD in record["retired_sids"]
    assert record.get("status") == "working"
    events = [json.loads(line) for line in
              (home / "state" / "events.jsonl").read_text().splitlines()]
    retired = [e for e in events if e.get("kind") == "fork_retired"]
    assert [(e["name"], e["session_id"], e["live_fork"]) for e in retired] == [
        (NAME, OLD, NEW)]


def test_older_resident_parents_are_swept_by_the_next_steer(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][NAME]["retired_sids"] = [OLDER]
    fleet.save_registry(data)
    rc, calls = _steer(monkeypatch, [row(OLDER), row(OLD)])
    assert rc == 0
    assert sorted(stops(calls)) == sorted([OLD[:8], OLDER[:8]])


@pytest.mark.parametrize("veto", ["busy-parent", "claimed-mail",
                                  "no-pid", "caller", "shared-sid", "fork-not-live"])
def test_the_parent_survives_when_a_rule_protects_it(home, monkeypatch, veto):
    entries = [row(OLD)]
    on_dispatch = None
    if veto == "busy-parent":
        def on_dispatch():   # the parent took a turn of its own meanwhile
            entries[0]["status"] = "busy"
    elif veto == "no-pid":
        entries[0].pop("pid")
    elif veto == "caller":
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", OLD)
    elif veto == "shared-sid":
        data = fleet.load_registry()
        other = dict(data["workers"][NAME])
        other.update(session_id="a0000103-0000-4000-8000-000000000103",
                     retired_sids=[OLD])
        data["workers"]["lane-b"] = other
        fleet.save_registry(data)
    elif veto == "claimed-mail":
        def on_dispatch():   # a drain of the parent's mail is in progress
            (home / "mailbox" / f"{OLD}.md.claimed.9").write_text("unread instruction")
    elif veto == "fork-not-live":
        def on_dispatch():
            entries.pop()    # the fork never shows up in the roster
    rc, calls = _steer(monkeypatch, entries, on_dispatch)
    assert rc == 0
    assert not stops(calls)
    assert fleet.load_registry()["workers"][NAME]["session_id"] == NEW


def test_a_supervisor_reap_without_any_worker_ignores_ordinary_rows(home):
    data = fleet.load_registry()
    data["workers"][NAME].update(session_id=NEW, retired_sids=[OLD])
    fleet.save_registry(data)
    run, calls = fake_daemon([row(OLD), row(NEW, status="busy")])
    assert fleet._reap_current_supervisor_forks(
        NAME, expected_sid=NEW, run=run, which=lambda _: "claude") == []
    assert fleet._reap_current_supervisor_forks(
        NAME, expected_sid=NEW, run=run, which=lambda _: "claude",
        any_worker=True) == [OLD]
    assert stops(calls) == [OLD[:8]]


def test_unread_parent_mail_protects_it_at_the_stop_recheck(home):
    """Unmigrated mail on the parent (written after send moved the residue to
    the fork) keeps the parent alive: it may still be read there."""
    data = fleet.load_registry()
    data["workers"][NAME].update(session_id=NEW, retired_sids=[OLD])
    fleet.save_registry(data)
    run, calls = fake_daemon([row(OLD), row(NEW, status="busy")])
    (home / "mailbox" / f"{OLD}.md").write_text("unread instruction")
    assert fleet._reap_current_supervisor_forks(
        NAME, expected_sid=NEW, run=run, which=lambda _: "claude",
        any_worker=True) == []
    assert not stops(calls)
