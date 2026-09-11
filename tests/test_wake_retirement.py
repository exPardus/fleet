"""Synthetic daemon proof: repeated wakes do not retain idle parent processes."""
import json
from types import SimpleNamespace

import pytest

import fleet


OLD = "11111111-aaaa-4bbb-8ccc-000000000001"
NEW = "22222222-aaaa-4bbb-8ccc-000000000002"
OTHER = "33333333-aaaa-4bbb-8ccc-000000000003"
NAME = "sup|inc-wake|boot"


def row(sid, **fields):
    return dict(id=sid[:8], sessionId=sid, name=NAME,
                state="working", status="idle", pid=4242, **fields)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MCX_WORKER", "1")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for directory in ("state", "logs", "mailbox", "supervisor"):
        (tmp_path / directory).mkdir()
    record = fleet.new_worker_record(NEW, str(tmp_path), "wake", "accept",
                                     dispatch_kind="bg")
    record.update(status="idle", retired_sids=[OLD])
    fleet.save_registry({"workers": {NAME: record}})
    fleet.write_incarnation({"incarnation_id": "inc-wake", "session_id": OLD,
                             "claimed_at": fleet.now_iso()})
    return tmp_path


def fake_daemon(entries):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
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
    return [argv[2] for argv, _kwargs in calls if argv[1] == "stop"]


def test_only_retired_process_stops_and_registry_survives(home):
    run, calls = fake_daemon([row(OLD), row(NEW)])
    assert fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude") == [OLD]
    assert stops(calls) == [OLD[:8]]
    record = fleet.load_registry()["workers"][NAME]
    assert record["session_id"] == NEW and record["retired_sids"] == [OLD]
    assert not record.get("archived_at")
    assert fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude") == []
    assert stops(calls) == [OLD[:8]]


@pytest.mark.parametrize("veto", ["missing-fork", "no-pid", "done-fork", "busy-parent",
                                 "mail", "claimed-mail", "different-claim", "released",
                                 "ambiguous", "caller", "duplicate-fork"])
def test_no_retirement_without_live_fork_and_clear_ownership(home, monkeypatch, veto):
    entries = [row(OLD), row(NEW)]
    if veto == "missing-fork":
        entries.pop()
    elif veto == "no-pid":
        entries[1].pop("pid")
    elif veto == "done-fork":
        entries[1]["state"] = "done"
    elif veto == "busy-parent":
        entries[0]["status"] = "busy"
    elif veto in ("mail", "claimed-mail"):
        suffix = ".md" if veto == "mail" else ".md.claimed.9"
        (home / "mailbox" / f"{OLD}{suffix}").write_text("unread instruction")
    elif veto in ("different-claim", "released"):
        claim = fleet.read_incarnation()
        claim.update({"session_id": OTHER} if veto == "different-claim" else {"state": "released"})
        fleet.write_incarnation(claim)
    elif veto == "ambiguous":
        data = fleet.load_registry()
        data["workers"]["other"] = dict(data["workers"][NAME])
        fleet.save_registry(data)
    elif veto == "caller":
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", OLD)
    elif veto == "duplicate-fork":
        entries.append(row(NEW))
    run, calls = fake_daemon(entries)
    assert fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude") == []
    assert not stops(calls)


@pytest.mark.parametrize("change", ["mail", "claim", "fork-gone"])
def test_retirement_rechecks_just_before_stop(home, change):
    entries = [row(OLD), row(NEW)]
    run, calls = fake_daemon(entries)
    reads = []

    def fetch():
        reads.append(1)
        if len(reads) == 2:
            if change == "mail":
                (home / "mailbox" / f"{OLD}.md").write_text("racing message")
            elif change == "claim":
                claim = fleet.read_incarnation()
                claim["session_id"] = OTHER
                fleet.write_incarnation(claim)
            else:
                entries.pop()
        return True, entries

    assert fleet._reap_current_supervisor_forks(
        run=run, which=lambda _: "claude", roster_fn=fetch) == []
    assert not stops(calls)


def test_delayed_fork_is_observed_before_parent_stops(home):
    entries = [row(OLD)]
    run, calls = fake_daemon(entries)
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        assert not stops(calls)
        entries.append(row(NEW))

    assert fleet._reap_current_supervisor_forks(
        run=run, which=lambda _: "claude", sleep=sleep, attempts=3) == [OLD]
    assert sleeps == [1]


def test_unobserved_fork_defers_after_bounded_poll_and_later_pass_retries(home):
    entries = [row(OLD)]
    run, calls = fake_daemon(entries)
    sleeps = []
    assert fleet._reap_current_supervisor_forks(
        run=run, which=lambda _: "claude", sleep=sleeps.append, attempts=99) == []
    assert sleeps == [1, 1] and not stops(calls)
    entries.append(row(NEW))
    assert fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude") == [OLD]


def test_send_retires_parent_only_after_actual_new_roster_pid(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][NAME].update(session_id=OLD, retired_sids=[], last_dispatch_at="2026-01-01T00:00:00Z")
    fleet.save_registry(data)
    fleet.append_outcome(NAME, {"kind": "result", "session_id": OLD, "ts": fleet.now_iso()})
    entries = [row(OLD)]
    run, calls = fake_daemon(entries)
    sleeps = []

    def dispatch(*args, **kwargs):
        assert kwargs["resume_sid"] == OLD
        assert not stops(calls)
        return {"session_id": NEW, "short_id": NEW[:8]}

    def sleep(seconds):
        assert not stops(calls)
        assert fleet.load_registry()["workers"][NAME]["session_id"] == NEW
        sleeps.append(seconds)
        entries.append(row(NEW))

    monkeypatch.setattr(fleet, "dispatch_bg", dispatch)
    assert fleet._cmd_send_native(NAME, "wake up", run=run, which=lambda _: "claude", sleep=sleep) == 0
    assert sleeps == [1] and stops(calls) == [OLD[:8]]


def test_lifecycle_retries_cleanup_without_archiving_current_body(home, monkeypatch):
    run, calls = fake_daemon([row(OLD), row(NEW)])
    count, error = fleet._supervisor_reap(run=run, which=lambda _: "claude", caller_sid=NEW)
    assert count == 0 and error is None
    assert stops(calls) == [OLD[:8]]
    assert not fleet.load_registry()["workers"][NAME].get("archived_at")


def test_send_success_without_live_replacement_never_stops_parent(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][NAME].update(session_id=OLD, retired_sids=[])
    fleet.save_registry(data)
    fleet.append_outcome(NAME, {"kind": "result", "session_id": OLD, "ts": fleet.now_iso()})
    run, calls = fake_daemon([row(OLD)])
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *args, **kwargs:
                        {"session_id": NEW, "short_id": NEW[:8]})
    sleeps = []
    assert fleet._cmd_send_native(NAME, "wake", run=run, which=lambda _: "claude",
                                  sleep=sleeps.append) == 0
    assert not stops(calls) and sleeps == [1, 1]
    assert fleet.load_registry()["workers"][NAME]["session_id"] == NEW


def test_repeated_wakes_leave_one_live_process(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][NAME].update(session_id=OLD, retired_sids=[])
    fleet.save_registry(data)
    entries = [row(OLD)]
    run, calls = fake_daemon(entries)
    forks = iter([NEW, OTHER, "44444444-aaaa-4bbb-8ccc-000000000004"])

    def dispatch(*args, **kwargs):
        sid = next(forks)
        entries.append(row(sid))
        return {"session_id": sid, "short_id": sid[:8]}

    monkeypatch.setattr(fleet, "dispatch_bg", dispatch)
    for _ in range(3):
        sid = fleet.load_registry()["workers"][NAME]["session_id"]
        fleet.append_outcome(NAME, {"kind": "result", "session_id": sid, "ts": fleet.now_iso()})
        assert fleet._cmd_send_native(NAME, "wake", run=run, which=lambda _: "claude",
                                      sleep=lambda _: None) == 0
        assert len([r for r in entries if r.get("pid")]) == 1
    assert stops(calls) == [OLD[:8], NEW[:8], OTHER[:8]]


def test_bounded_sweeps_eventually_reach_older_live_history(home):
    retired = [f"{i:08d}-aaaa-4bbb-8ccc-000000000001" for i in range(1, 7)]
    data = fleet.load_registry()
    data["workers"][NAME]["retired_sids"] = retired
    fleet.save_registry(data)
    claim = fleet.read_incarnation()
    claim["session_id"] = NEW
    fleet.write_incarnation(claim)
    run, calls = fake_daemon([row(sid) for sid in retired] + [row(NEW)])
    assert len(fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude")) == 4
    assert len(stops(calls)) == 4
    assert len(fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude")) == 2
    assert set(stops(calls)) == {sid[:8] for sid in retired}


def test_protected_recent_history_does_not_hide_older_idle_parent(home):
    retired = [OLD] + [f"{i:08d}-aaaa-4bbb-8ccc-000000000001" for i in range(1, 5)]
    data = fleet.load_registry()
    data["workers"][NAME]["retired_sids"] = retired
    fleet.save_registry(data)
    for sid in retired[1:]:
        (home / "mailbox" / f"{sid}.md").write_text("unread instruction")
    run, calls = fake_daemon([row(sid) for sid in retired] + [row(NEW)])
    assert fleet._reap_current_supervisor_forks(run=run, which=lambda _: "claude") == [OLD]
    assert stops(calls) == [OLD[:8]]
