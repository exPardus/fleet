"""Lane garbage collection (SPEC §11): idle sessions stop, their state stays.

THE DEFECT THIS FILE PINS. On a busy host autoclean reported
`husks_removed=0` while 36 idle background sessions held memory: the husk
sweep only removes sessions whose process is gone, and every fork-steer
leaves its old sid's process idle and protected by the live row. Landed lanes
were stopped only at wave-close, and nothing stopped a lane that sat idle.

Arms: a landed/abandoned lane stops at once; an idle lane stops after
`gc.idle_ttl_minutes`; autoclean stops idle retired forks; `fleet status`
shows the home's live process count and memory; spawn refuses over
`gc.memory_budget_mb` or under `gc.min_available_mb`.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet

LANE, SID, OLD = "lane", "lane-sid", "lane-old-sid"
SUP, SUP_SID = "sup|inc-gc|boot", "sup-sid"
NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "supervisor", "mailbox", "logs"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}")
    lane = fleet.new_worker_record(SID, str(tmp_path), "work", "bypass",
                                   dispatch_kind="bg")
    finished = _iso(NOW - timedelta(hours=2))
    lane.update(status="idle", created=finished, last_activity=finished,
                last_dispatch_at=finished, retired_sids=[OLD])
    sup = fleet.new_worker_record(SUP_SID, str(tmp_path), "supervise", "bypass")
    sup["status"] = "idle"
    fleet.save_registry({"workers": {LANE: lane, SUP: sup}})
    fleet.append_outcome(LANE, {"ts": _iso(NOW - timedelta(minutes=90)),
                                "session_id": SID, "kind": "result"})
    monkeypatch.setattr(fleet, "find_transcript_path", lambda *_a: None)
    return tmp_path


def _entry(sid, status="idle", pid=10):
    return {"sessionId": sid, "status": status, "pid": pid, "state": "working"}


ROSTER = [_entry(SID, pid=11), _entry(OLD, pid=12), _entry(SUP_SID, pid=13)]


def _stops(monkeypatch):
    stops = []
    monkeypatch.setattr(fleet, "_stop_native_session_status",
                        lambda sid, **_: stops.append(sid) or (True, "stopped"))
    return stops


def _config(home, **gc):
    (home / "state" / "config.json").write_text(json.dumps({"gc": gc}))


def _run(**kw):
    return fleet.stop_idle_sessions(roster_fn=lambda: (True, list(ROSTER)), **kw)


def test_idle_retired_fork_and_ttl_expired_lane_are_stopped(home, monkeypatch):
    stops = _stops(monkeypatch)
    assert sorted(_run()) == [f"{LANE}:idle-ttl", f"{LANE}:retired"]
    assert sorted(stops) == sorted([SID, OLD])
    assert SUP_SID not in stops
    rec = fleet.load_registry()["workers"][LANE]
    assert rec["session_id"] == SID and rec["status"] == "idle"  # state kept


def test_lane_idle_under_the_ttl_keeps_its_session(home, monkeypatch):
    stops = _stops(monkeypatch)
    _config(home, idle_ttl_minutes=240)
    assert _run() == [f"{LANE}:retired"]
    assert stops == [OLD]


def test_ttl_zero_disables_the_idle_stop(home, monkeypatch):
    _stops(monkeypatch)
    _config(home, idle_ttl_minutes=0)
    assert fleet.gc_config()["idle_ttl_minutes"] is None
    assert _run() == [f"{LANE}:retired"]


@pytest.mark.parametrize("guard", ["mail", "busy", "caller"])
def test_mail_running_turn_and_caller_are_never_stopped(home, monkeypatch, guard):
    stops = _stops(monkeypatch)
    roster = list(ROSTER)
    caller = None
    if guard == "mail":
        fleet.append_mailbox(SID, "follow-up")
    elif guard == "busy":
        roster[0] = _entry(SID, status="busy", pid=11)
    else:
        caller = SID
    fleet.stop_idle_sessions(roster_fn=lambda: (True, roster), caller=caller)
    assert SID not in stops


def test_landed_lane_stops_regardless_of_ttl(home, monkeypatch):
    stops = _stops(monkeypatch)
    _config(home, idle_ttl_minutes=10_000)
    data = fleet.load_registry()
    data["workers"][LANE]["lane_state"] = "landed"
    fleet.save_registry(data)
    assert f"{LANE}:landed" in _run()
    assert SID in stops


def test_green_land_stops_the_lane_by_branch(home, monkeypatch):
    stops = _stops(monkeypatch)
    data = fleet.load_registry()
    data["workers"][LANE]["branch"] = "fleet/w1-thing"
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, list(ROSTER)))
    fleet._stop_landed_lane("fleet/w1-thing", home)
    assert sorted(stops) == sorted([SID, OLD])  # its idle forks go too


def test_abandon_stops_the_session_at_once(home, monkeypatch):
    stops = _stops(monkeypatch)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, list(ROSTER)))
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    monkeypatch.setattr(fleet, "_reconcile_working_row", lambda *a, **k: None)
    fleet.cmd_abandon(SimpleNamespace(name=LANE, reason="superseded", force=True,
                                      nonce=None))
    assert SID in stops
    assert fleet.load_registry()["workers"][LANE]["lane_state"] == "abandoned"


def test_autoclean_reports_idle_stops(home, monkeypatch, capsys):
    """The 36-idle-sessions shape: nothing is a husk, yet memory comes back."""
    stops = _stops(monkeypatch)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, list(ROSTER)))
    monkeypatch.setattr(fleet, "cmd_archive", lambda *a, **k: 0)
    fleet.cmd_autoclean(SimpleNamespace(dry_run=False, ttl_hours=None,
                                        expire_tombstones_hours=None))
    out = capsys.readouterr().out
    assert "husks_removed=0" in out and "idle_stopped=2" in out
    stamp = json.loads(fleet.autoclean_stamp_path().read_text())
    assert stamp["idle_stopped"] == 2
    assert sorted(stops) == sorted([SID, OLD])


def test_autoclean_dry_run_stops_nothing(home, monkeypatch, capsys):
    stops = _stops(monkeypatch)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, list(ROSTER)))
    monkeypatch.setattr(fleet, "cmd_archive", lambda *a, **k: 0)
    fleet.cmd_autoclean(SimpleNamespace(dry_run=True, ttl_hours=None,
                                        expire_tombstones_hours=None))
    assert stops == [] and "idle: would stop" in capsys.readouterr().out


def _own_lane(home):
    """Make the lane owned by a held claim whose holder is the SUP row."""
    data = fleet.load_registry()
    data["workers"][LANE]["spawned_by"] = SUP_SID
    fleet.save_registry(data)
    fleet.write_incarnation({"state": "held", "session_id": SUP_SID,
                             "heartbeat_at": _iso(NOW)})


def test_sup_guard_do_runs_the_idle_sweep(home, monkeypatch, capsys):
    stops = _stops(monkeypatch)
    _own_lane(home)
    monkeypatch.setattr(fleet, "status_snapshot", lambda: {
        "ok": True, "workers": [], "supervisor": {"goals_active": False,
                                                  "state": "held"}})
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                        roster_fn=lambda: (True, list(ROSTER)))
    out = json.loads(capsys.readouterr().out)
    assert sorted(out["idle_stopped"]) == [f"{LANE}:idle-ttl", f"{LANE}:retired"]
    assert SUP_SID not in stops


# ---------------------------------------------------------------- memory

def test_status_usage_counts_this_homes_processes(home, monkeypatch):
    monkeypatch.setattr(fleet.PLATFORM, "process_rss_mb", lambda pid: 100 + pid)
    workers = fleet.load_registry()["workers"]
    foreign = _entry("not-ours", pid=99)
    assert fleet.home_process_usage(workers, ROSTER + [foreign]) == (3, 336)
    _config(home, memory_budget_mb=4000)
    line = fleet._process_usage_line(workers, ROSTER)
    assert line == "processes: 3 live, rss=336 MB (budget 4000 MB)"


def test_unreadable_rss_is_reported_not_guessed(home, monkeypatch):
    def unreadable(pid):
        raise fleet.UnsupportedPlatformError("no /proc")
    monkeypatch.setattr(fleet.PLATFORM, "process_rss_mb", unreadable)
    workers = fleet.load_registry()["workers"]
    assert fleet._process_usage_line(workers, ROSTER) == "processes: 3 live, rss=UNREADABLE"


def test_spawn_refuses_over_the_memory_budget(home, monkeypatch):
    _config(home, memory_budget_mb=300)
    monkeypatch.setattr(fleet.PLATFORM, "process_rss_mb", lambda pid: 100 + pid)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, list(ROSTER)))
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail("dispatched"))
    with pytest.raises(fleet.FleetCliError, match="gc.memory_budget_mb 300"):
        fleet.cmd_spawn(SimpleNamespace(dir=str(home), task="t", name="new", nonce=None))


def test_spawn_refuses_under_the_available_floor(home, monkeypatch):
    _config(home, min_available_mb=2048)
    monkeypatch.setattr(fleet.PLATFORM, "memory_available_mb", lambda: 900)
    assert "below gc.min_available_mb 2048" in fleet._memory_budget_refusal()


def test_unset_budget_never_refuses(home, monkeypatch):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: pytest.fail("no budget, no probe"))
    assert fleet._memory_budget_refusal() is None


def test_linux_rss_reads_proc(monkeypatch):
    import os
    if not fleet.PLATFORM.is_linux:
        pytest.skip("Linux /proc only")
    assert fleet.PLATFORM.process_rss_mb(os.getpid()) > 0


# ---------------------------------------------------------------- w485 review pins

def _set(**fields):
    data = fleet.load_registry()
    data["workers"][LANE].update(fields)
    fleet.save_registry(data)


@pytest.mark.parametrize("where", ["row-sid", "retired-sid"])
def test_p1_registered_interface_session_is_never_stopped(home, monkeypatch, where):
    """#75 P1-1: a lane that continued as interface keeps its session, in
    both arms, with the TTL long expired and no caller sid (keeper tick)."""
    stops = _stops(monkeypatch)
    sid = SID if where == "row-sid" else OLD
    (home / "state" / "interface-session").write_text(sid + "\n")
    _run(caller=None)
    assert sid not in stops and stops == []


def test_p1_codex_interface_thread_is_protected(home, monkeypatch):
    stops = _stops(monkeypatch)
    (home / "state" / "interface-codex.json").write_text(json.dumps({"thread_id": OLD}))
    _run()
    assert OLD not in stops and SID not in stops


@pytest.mark.parametrize("payload", ["pane-only", "unreadable-codex"])
def test_p1_unresolvable_interface_registration_stops_nothing(home, monkeypatch, payload):
    stops = _stops(monkeypatch)
    if payload == "pane-only":
        (home / "state" / "interface-pane").write_text("%3\n")
    else:
        (home / "state" / "interface-codex.json").write_text("{not json")
    assert _run() == [] and stops == []


def test_p1_supervisor_claim_sid_on_a_lane_row_is_never_stopped(home, monkeypatch):
    stops = _stops(monkeypatch)
    fleet.write_incarnation({"state": "held", "session_id": SID,
                             "heartbeat_at": _iso(NOW)})
    _run()
    assert SID not in stops and OLD not in stops


@pytest.mark.parametrize("kind", [None, "codex-app-server", "mcx"])
def test_p1_rows_fleet_did_not_bg_spawn_are_never_stopped(home, monkeypatch, kind):
    stops = _stops(monkeypatch)
    _set(dispatch_kind=kind)
    assert _run() == [] and stops == []


def test_p1_attached_row_keeps_every_session(home, monkeypatch):
    stops = _stops(monkeypatch)
    _set(status="attached")
    assert _run() == [] and stops == []


def test_p2_1_row_that_moves_after_classification_is_not_stopped(home, monkeypatch):
    """A send pre-claims the row while the roster is being fetched."""
    stops = _stops(monkeypatch)

    def roster():
        _set(status="working", last_dispatch_at=fleet.now_iso())
        return True, list(ROSTER)
    stopped = fleet.stop_idle_sessions(roster_fn=roster)
    assert SID not in stops and f"{LANE}:idle-ttl" not in stopped


def test_p2_1_mail_arriving_before_the_stop_keeps_the_session(home, monkeypatch):
    stops = _stops(monkeypatch)

    def roster():
        fleet.append_mailbox(SID, "late follow-up")
        return True, list(ROSTER)
    fleet.stop_idle_sessions(roster_fn=roster)
    assert SID not in stops


def test_p2_2_retired_fork_with_live_background_work_is_kept(home, monkeypatch):
    stops = _stops(monkeypatch)
    monkeypatch.setattr(fleet, "_lane_background_live",
                        lambda name, sid, now=None: ["task"] if sid == OLD else [])
    _run()
    assert OLD not in stops and SID in stops


def test_p2_3_guard_sweep_never_stops_a_lane_its_claim_does_not_own(home, monkeypatch):
    stops = _stops(monkeypatch)
    fleet.write_incarnation({"state": "held", "session_id": SUP_SID,
                             "heartbeat_at": _iso(NOW)})
    assert fleet._sup_guard_idle_sweep(lambda: (True, list(ROSTER))) == []
    assert stops == []
    _own_lane(home)
    assert sorted(fleet._sup_guard_idle_sweep(lambda: (True, list(ROSTER)))) == [
        f"{LANE}:idle-ttl", f"{LANE}:retired"]


def test_p2_4_respawn_refuses_under_the_available_floor(home, monkeypatch):
    _config(home, min_available_mb=2048)
    monkeypatch.setattr(fleet.PLATFORM, "memory_available_mb", lambda: 900)
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail("dispatched"))
    with pytest.raises(fleet.FleetCliError, match="respawn: .*gc.min_available_mb 2048"):
        fleet._cmd_respawn_native(SimpleNamespace(name=LANE, task=None),
                                  fleet.load_registry()["workers"][LANE])


def test_p2_4_stream_retry_defers_under_the_available_floor(home, monkeypatch):
    _config(home, min_available_mb=2048)
    monkeypatch.setattr(fleet.PLATFORM, "memory_available_mb", lambda: 900)
    monkeypatch.setattr(fleet, "stream_retry_plan", lambda *a, **k: {
        "action": "retry", "attempt": 1, "due_at": NOW, "error_at": NOW})
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda *a, **k: pytest.fail("retried under the floor"))
    step = fleet.recover_lane(LANE, list(ROSTER))
    assert step == {"action": "deferred", "done": None}
    assert "stream_retry" not in fleet.load_registry()["workers"][LANE]


@pytest.mark.parametrize("guard", [
    "supervisor-body", "roster-only-sid", "background-live", "epoch-suspicious",
    "retired-mail"])
def test_p2_5_gc_guards_hold(home, monkeypatch, guard):
    """Each guard the GC claims, by fault injection; TTL expired throughout."""
    stops = _stops(monkeypatch)
    roster = list(ROSTER)
    if guard == "supervisor-body":
        data = fleet.load_registry()
        data["workers"][SUP].update(dispatch_kind="bg", last_activity=_iso(
            NOW - timedelta(hours=5)))
        fleet.save_registry(data)
    elif guard == "roster-only-sid":
        roster.append(_entry("spare-pool-sid", pid=40))
    elif guard == "background-live":
        monkeypatch.setattr(fleet, "_lane_background_live",
                            lambda name, sid, now=None: ["task"])
    elif guard == "epoch-suspicious":
        _set(status="working")
        roster = []
    else:
        fleet.append_mailbox(OLD, "for the old fork")
    fleet.stop_idle_sessions(roster_fn=lambda: (True, roster))
    assert SUP_SID not in stops and "spare-pool-sid" not in stops
    if guard == "background-live":
        assert stops == []
    if guard == "epoch-suspicious":
        assert stops == []
    if guard == "retired-mail":
        assert OLD not in stops
