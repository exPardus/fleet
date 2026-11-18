"""Turns that end on an API error: in-session stream retry and LANE-DEAD (§8).

THE INCIDENT THIS FILE PINS. Lanes died mid-turn with `API Error: Connection
lost mid-response`. Claude Code ends such a turn through StopFailure, not Stop,
so no outcome was written; fleet marked the rows dead-suspected and told nobody,
and their supervisor idled for 95 minutes waiting for LANE-DONE.

Fault injection uses transcript tails with the real error strings. Each arm:
the transient-error retry (bounded, in the same session), LANE-DEAD when the
retries run out, the supervisor arm in `sup-guard`, the keeper's once-per-death
worker-anomaly dedup, and the StopFailure hook bridge.
"""
import io
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
import fleet_keeper as k

PARENT = "sup|inc-test|boot"
PARENT_SID = "parent-sid"
LANE = "lane"
LANE_SID = "lane-sid"
HOOK = Path(__file__).resolve().parents[1] / "bin" / "hooks" / "stopfailure_recover.py"

NOW = datetime(2026, 11, 18, 16, 0, 0, tzinfo=timezone.utc)

# Measured tails (tests/test_respawn_dead_stream.py) plus overloaded and 5xx.
CONNECTION_LOST = ("API Error: Connection lost mid-response. "
                   "The response above may be incomplete.")
TRANSIENT_TEXTS = (
    "API Error: stream closed before completion",
    CONNECTION_LOST,
    "API Error: Server error mid-response. The response above may be incomplete.",
    "API Error: The response stopped arriving. The response above may be incomplete.",
    'API Error: 529 {"type":"error","error":{"type":"overloaded_error",'
    '"message":"Overloaded"}}',
    'API Error: 500 {"type":"error","error":{"type":"api_error",'
    '"message":"Internal server error"}}',
)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _api_error(text, *, at, status=None, error="unknown"):
    rec = {"type": "assistant", "isApiErrorMessage": True, "error": error,
           "timestamp": _iso(at),
           "message": {"role": "assistant", "model": "<synthetic>",
                       "content": [{"type": "text", "text": text}]}}
    if status is not None:
        rec["apiErrorStatus"] = status
    return json.dumps(rec)


def _chatter(text, *, at):
    return json.dumps({"type": "assistant", "timestamp": _iso(at),
                       "message": {"role": "assistant",
                                   "content": [{"type": "text", "text": text}]}})


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "supervisor", "mailbox", "logs"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}")
    parent = fleet.new_worker_record(PARENT_SID, str(tmp_path), "supervise", "bypass")
    parent["status"] = "idle"
    lane = fleet.new_worker_record(LANE_SID, str(tmp_path), "work", "bypass",
                                   spawned_by=PARENT_SID, dispatch_kind="bg")
    dispatched = _iso(NOW - timedelta(hours=1))
    lane.update(status="working", created=dispatched, last_activity=dispatched,
                last_dispatch_at=dispatched)
    fleet.save_registry({"workers": {PARENT: parent, LANE: lane}})
    fleet.write_incarnation({"state": "held", "session_id": PARENT_SID,
                             "heartbeat_at": _iso(NOW)})
    transcript = tmp_path / "lane.jsonl"
    monkeypatch.setattr(fleet, "find_transcript_path",
                        lambda _n, _s, _p=transcript: _p)
    return tmp_path


def _tail(home, *records, marker=(LANE_SID,)):
    """Write the transcript tail; `marker` sids also get the StopFailure marker
    `stream-recover` writes when the hook fires (P2-4 provenance)."""
    (home / "lane.jsonl").write_text("".join(r + "\n" for r in records),
                                     encoding="utf-8")
    for sid in marker:
        fleet._write_stopfailure_marker(sid)


def _jittered(delay, sid=LANE_SID):
    return delay * (1 + fleet.STREAM_RETRY_JITTER_FRACTION
                    * fleet._stream_retry_jitter(sid))


IDLE = [{"sessionId": LANE_SID, "status": "idle", "state": "working", "pid": 7}]


def _lane():
    return fleet.load_registry()["workers"][LANE]


def _sends(monkeypatch):
    sends = []

    def send(name, message, *args, **kwargs):
        sends.append((name, message, kwargs.get("stream_retry", False)))
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    return sends


# ---------------------------------------------------------------- classifier

@pytest.mark.parametrize("text", TRANSIENT_TEXTS)
def test_transient_tails_classify_as_stream(home, text):
    _tail(home, _chatter("working", at=NOW - timedelta(minutes=5)),
          _api_error(text, at=NOW - timedelta(minutes=4)))
    assert fleet.transcript_api_error_tail(LANE_SID, home / "lane.jsonl")[0] == "stream"


def test_structured_5xx_status_is_stream_without_text_marker(home):
    _tail(home, _api_error("API Error", at=NOW, status=503))
    assert fleet.transcript_api_error_tail(LANE_SID, home / "lane.jsonl")[0] == "stream"


def test_usage_limit_tail_is_limit_never_stream(home):
    _tail(home, _api_error("You've hit your limit · resets 5pm", at=NOW,
                           status=429, error="rate_limit"))
    assert fleet.transcript_api_error_tail(LANE_SID, home / "lane.jsonl")[0] == "limit"


def test_credit_wall_is_a_non_transient_api_error(home):
    _tail(home, _api_error("API Error: 402 Insufficient credits", at=NOW))
    assert fleet.transcript_api_error_tail(LANE_SID, home / "lane.jsonl")[0] == "api-error"


def test_chatter_after_an_old_error_is_no_error(home):
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=9)),
          _chatter("recovered", at=NOW - timedelta(minutes=8)))
    assert fleet.transcript_api_error_tail(LANE_SID, home / "lane.jsonl") == (None, None)


def test_respawn_evidence_stays_the_measured_marker_set(home):
    """Overloaded is retried but is not item-31 respawn evidence."""
    _tail(home, _api_error(TRANSIENT_TEXTS[4], at=NOW))
    assert not fleet.transcript_stream_death_scan(LANE_SID, home / "lane.jsonl")
    _tail(home, _api_error(CONNECTION_LOST, at=NOW))
    assert fleet.transcript_stream_death_scan(LANE_SID, home / "lane.jsonl")


# ---------------------------------------------------------------- the plan

def test_stream_death_inside_launch_grace_is_dead_suspected(home):
    data = fleet.load_registry()
    fresh = _iso(datetime.now(timezone.utc) - timedelta(seconds=30))
    data["workers"][LANE].update(last_dispatch_at=fresh, created=fresh)
    fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=datetime.now(timezone.utc)))
    assert fleet.recompute_worker_native(LANE, _lane(), IDLE)["status"] == "dead-suspected"


def test_an_inherited_error_older_than_the_dispatch_is_not_this_turn(home):
    """A fork-steer copies history; an older death must not trigger a retry."""
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(hours=2)))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "none"


def test_running_turn_is_never_retried(home):
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=1)))
    busy = [{**IDLE[0], "status": "busy"}]
    assert fleet.stream_retry_plan(LANE, _lane(), busy, now=NOW)["action"] == "none"


def test_backoff_waits_then_retries(home):
    died = NOW - timedelta(seconds=10)
    _tail(home, _api_error(CONNECTION_LOST, at=died))
    plan = fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)
    assert plan["action"] == "wait"
    assert plan["due_at"] == died + timedelta(
        seconds=_jittered(fleet.STREAM_RETRY_DELAYS_SECONDS[0]))
    later = died + timedelta(seconds=_jittered(fleet.STREAM_RETRY_DELAYS_SECONDS[0]))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=later)["action"] == "retry"


def test_limit_tail_parks_and_is_never_retried_or_reported(home, monkeypatch):
    sends = _sends(monkeypatch)
    _tail(home, _api_error("You've hit your limit · resets 5pm", at=NOW,
                           status=429, error="rate_limit"))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "none"
    step = fleet.recover_lane(LANE, IDLE, now=NOW)
    assert step["done"] is None and sends == []


# ---------------------------------------------------------------- retry arm

def test_due_stream_error_is_retried_in_the_same_session(home, monkeypatch):
    sends = _sends(monkeypatch)
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)))
    step = fleet.recover_lane(LANE, IDLE, now=NOW)
    assert step["done"] == "retried" and step["attempt"] == 1
    assert sends == [(LANE, fleet.STREAM_RETRY_MESSAGE, True)]
    assert _lane()["stream_retry"]["attempts"] == 1


def test_stream_retry_flag_fork_steers_a_dead_suspected_row(home, monkeypatch):
    """The real send path: the flag turns a proven stream death into an idle
    fork-steer of the same session; without it the row is refused."""
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)))
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, IDLE))

    class Reached(Exception):
        pass

    seen = {}

    def dispatch(name, cwd, prompt, mode, **kw):
        seen.update(kw)
        raise Reached()
    monkeypatch.setattr(fleet, "dispatch_bg", dispatch)
    with pytest.raises(fleet.FleetCliError, match="dead-suspected"):
        fleet._cmd_send_native(LANE, "hello")
    with pytest.raises(Reached):
        fleet._cmd_send_native(LANE, fleet.STREAM_RETRY_MESSAGE, stream_retry=True)
    assert seen["resume_sid"] == LANE_SID
    assert fleet.STREAM_RETRY_MESSAGE in seen["inline_body"]


def test_completed_turn_resets_the_attempt_count(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][LANE]["stream_retry"] = {"attempts": 3,
                                             "last_at": _iso(NOW - timedelta(minutes=50))}
    fleet.save_registry(data)
    fleet.append_outcome(LANE, {"ts": _iso(NOW - timedelta(minutes=40)),
                                "session_id": "older-sid", "kind": "result"})
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "retry"


# ---------------------------------------------------------------- LANE-DEAD arm

def _exhaust(home):
    data = fleet.load_registry()
    data["workers"][LANE]["stream_retry"] = {
        "attempts": len(fleet.STREAM_RETRY_DELAYS_SECONDS),
        "last_at": _iso(NOW - timedelta(minutes=10))}
    fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=2)))


def test_retries_exhausted_send_lane_dead_once(home, monkeypatch):
    sends = _sends(monkeypatch)
    _exhaust(home)
    step = fleet.recover_lane(LANE, IDLE, now=NOW)
    assert step["action"] == "exhausted" and step["done"] == "lane-dead"
    assert sends == [(PARENT, f"LANE-DEAD {LANE} stream-error-retries-exhausted", False)]
    assert fleet.recover_lane(LANE, IDLE, now=NOW)["done"] is None
    assert len(sends) == 1


def test_non_transient_api_error_is_lane_dead_without_retry(home, monkeypatch):
    sends = _sends(monkeypatch)
    _tail(home, _api_error("API Error: 401 authentication_error", at=NOW))
    assert fleet.recover_lane(LANE, IDLE, now=NOW)["done"] == "lane-dead"
    assert sends == [(PARENT, f"LANE-DEAD {LANE} api-error", False)]


def test_busy_supervisor_gets_lane_dead_as_mail_and_is_not_woken(home, monkeypatch):
    data = fleet.load_registry()
    data["workers"][PARENT]["status"] = "working"
    fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [
        {"sessionId": PARENT_SID, "status": "busy", "state": "working", "pid": 1}]))
    _exhaust(home)
    assert fleet.notify_lane_dead(LANE, "stream-error-retries-exhausted", now=NOW)
    mail = (home / "mailbox" / f"{PARENT_SID}.md").read_text()
    assert f"LANE-DEAD {LANE} stream-error-retries-exhausted" in mail


def test_failed_lane_dead_send_is_retried_next_observation(home, monkeypatch):
    calls = []

    def send(name, message, *a, **kw):
        calls.append(message)
        if len(calls) == 1:
            raise fleet.FleetCliError("injected")
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    _exhaust(home)
    with pytest.raises(fleet.FleetCliError):
        fleet.notify_lane_dead(LANE, "stream-error-retries-exhausted", now=NOW)
    assert fleet.notify_lane_dead(LANE, "stream-error-retries-exhausted", now=NOW)
    assert len(calls) == 2


def test_long_dead_rows_never_send_lane_dead(home, monkeypatch):
    """A row that died in September must not flood today's supervisor."""
    sends = _sends(monkeypatch)
    old = NOW - timedelta(days=60)
    data = fleet.load_registry()
    data["workers"][LANE].update(last_dispatch_at=_iso(old), created=_iso(old),
                                 last_activity=_iso(old))
    fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=old + timedelta(minutes=5)))
    data["workers"][LANE]["stream_retry"] = {"attempts": 3, "last_at": _iso(NOW)}
    fleet.save_registry(data)
    assert not fleet.notify_lane_dead(LANE, "no-outcome", now=NOW)
    assert fleet.sweep_lane_dead(lambda: (True, IDLE), now=NOW) == {
        "stream_retried": [], "lane_dead_sent": []}
    assert sends == []


def test_no_outcome_death_reports_lane_dead(home, monkeypatch):
    sends = _sends(monkeypatch)
    _tail(home, _chatter("half way", at=NOW - timedelta(minutes=30)))
    # The lane's session process is gone and no outcome was written.
    result = fleet.sweep_lane_dead(lambda: (True, [{"sessionId": PARENT_SID,
                                                    "status": "idle", "pid": 1}]),
                                   now=datetime.now(timezone.utc))
    assert result["lane_dead_sent"] == [LANE]
    assert sends == [(PARENT, f"LANE-DEAD {LANE} no-outcome", False)]


def test_killed_lane_is_not_reported(home, monkeypatch):
    sends = _sends(monkeypatch)
    data = fleet.load_registry()
    data["workers"][LANE]["status"] = "dead"
    fleet.save_registry(data)
    fleet.write_tombstone_outcome(LANE, LANE_SID, "killed")
    assert fleet.recover_lane(LANE, IDLE, now=NOW)["done"] is None
    assert sends == []


def test_sweep_retries_due_lanes_and_guard_json_reports_it(home, monkeypatch, capsys):
    sends = _sends(monkeypatch)
    _tail(home, _api_error(CONNECTION_LOST, at=datetime.now(timezone.utc)
                           - timedelta(minutes=5)))
    monkeypatch.setattr(fleet, "status_snapshot", lambda: {
        "ok": True, "workers": [], "supervisor": {"goals_active": False,
                                                  "state": "held"}})
    monkeypatch.setattr(fleet, "sweep_lane_done", lambda *a, **k: [])
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                        roster_fn=lambda: (True, IDLE))
    out = json.loads(capsys.readouterr().out)
    assert out["stream_retried"] == [LANE] and out["lane_dead_sent"] == []
    assert sends == [(LANE, fleet.STREAM_RETRY_MESSAGE, True)]


# ---------------------------------------------------------------- the bridge

def test_stream_recover_waits_for_the_backoff_then_retries(home, monkeypatch):
    sends = _sends(monkeypatch)
    died = datetime.now(timezone.utc)
    _tail(home, _api_error(CONNECTION_LOST, at=died))
    clock = {"now": died}
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += timedelta(seconds=seconds)
    fleet.cmd_stream_recover(SimpleNamespace(sid=LANE_SID, wait=True),
                             roster_fn=lambda: (True, IDLE), sleep=sleep,
                             now_fn=lambda: clock["now"])
    assert sleeps and sleeps[0] == pytest.approx(
        _jittered(fleet.STREAM_RETRY_DELAYS_SECONDS[0]), abs=1.0)
    assert sends == [(LANE, fleet.STREAM_RETRY_MESSAGE, True)]


def test_stopfailure_hook_launches_the_detached_bridge(home, monkeypatch):
    sys.path.insert(0, str(HOOK.parent))
    import stopfailure_recover as hook
    launched = []
    monkeypatch.setattr(hook.subprocess, "Popen",
                        lambda argv, **kw: launched.append((argv, kw)))
    monkeypatch.setattr(hook, "_fleet_home", lambda: str(home))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(
        {"session_id": LANE_SID, "hook_event_name": "StopFailure",
         "error": "server_error"})))
    hook.main()
    (argv, kw), = launched
    assert argv[-4:] == ["stream-recover", "--sid", LANE_SID, "--wait"]
    assert kw.get("start_new_session") or kw.get("creationflags")
    assert kw["stdin"] is subprocess.DEVNULL


def test_stopfailure_hook_ignores_unknown_sessions_and_exits_zero(home):
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--fleet-home", str(home)],
        input=json.dumps({"session_id": "not-a-fleet-session"}),
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


# ---------------------------------------------------------------- supervisor arm

def _sup_obs(action, **plan):
    return {"goals_active": True, "registry_ok": True, "roster_ok": True,
            "state": "held", "claim": {}, "claim_sids": [PARENT_SID],
            "live_rows": {PARENT_SID: [{"sessionId": PARENT_SID, "status": "idle",
                                        "pid": 1, "name": PARENT}]},
            "live_body_rows": [{"sessionId": PARENT_SID, "status": "idle",
                                "pid": 1, "name": PARENT}],
            "body_name": PARENT, "heartbeat_age_seconds": 30.0,
            "unread_mail_age_seconds": None, "idle_resumable_holder": True,
            "stream_retry": {"action": action, **plan}}


def test_supervisor_stream_death_is_woken_even_with_a_fresh_heartbeat():
    verdict, reason, detail = fleet._sup_guard_decide(_sup_obs("retry", attempt=1))
    assert (verdict, reason) == ("WAKE", PARENT)
    assert detail["stream_retry_attempt"] == 1


def test_supervisor_retries_exhausted_pages_the_interface():
    verdict, reason, _ = fleet._sup_guard_decide(_sup_obs("exhausted", attempts=3))
    assert verdict == "PAGE" and "retries exhausted" in reason
    page = k.rule_supervisor_stalled({"supervisor_guard": {
        "verdict": f"PAGE {reason}", "reason": reason, "body_name": PARENT}}, 0)
    assert page is not None and "retries exhausted" in page.text


def test_supervisor_stream_wait_is_quiet():
    verdict, _, detail = fleet._sup_guard_decide(_sup_obs("wait"))
    assert verdict == "OK" and detail["quiet"] is True


def test_supervisor_body_plan_reads_its_own_transcript(home):
    data = fleet.load_registry()
    sup = data["workers"][PARENT]
    sup.update(status="working", last_dispatch_at=_iso(NOW - timedelta(hours=1)))
    fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)),
          marker=(PARENT_SID,))
    roster = [{"sessionId": PARENT_SID, "status": "idle", "pid": 1}]
    assert fleet.stream_retry_plan(PARENT, sup, roster, now=NOW)["action"] == "retry"


# ---------------------------------------------------------------- keeper dedup

def _worker(name, status="dead-suspected", stale=60.0, turns=1):
    return {"name": name, "status": status, "mail": 0, "limit_kind": None,
            "turns": turns, "stale_seconds": stale}


def test_keeper_never_pages_rows_dead_beyond_the_age_bound():
    old = [_worker(f"old{i}", stale=k.WORKER_ANOMALY_MAX_AGE_SECONDS + 60)
           for i in range(70)]
    assert k.rule_worker_anomaly({"workers": old}, 0) is None


def test_keeper_pages_each_death_once():
    obs = {"workers": [_worker("w1")]}
    page = k.rule_worker_anomaly(obs, 0)
    assert page is not None and "w1(dead-suspected)" in page.text
    seen = sorted(k.worker_anomalies(obs))
    assert k.rule_worker_anomaly({**obs, "anomaly_seen": seen}, 0) is None
    # A second death of the same row (new turn) is a new page.
    again = {"workers": [_worker("w1", turns=2)], "anomaly_seen": seen}
    assert k.rule_worker_anomaly(again, 0) is not None


# ---------------------------------------------------------------- w485 review pins

def _dispatch(at):
    data = fleet.load_registry()
    data["workers"][LANE].update(last_dispatch_at=_iso(at), status="working")
    fleet.save_registry(data)


def _fake_retry_send(monkeypatch, clock):
    """`_cmd_send_native` stand-in that performs the real pre-claim stamp."""
    sends = []

    def send(name, message, *args, **kwargs):
        sends.append(message)
        with fleet.fleet_lock():
            data = fleet.load_registry()
            rec = data["workers"][name]
            rec["last_dispatch_at"] = _iso(clock["now"])
            if kwargs.get("stream_retry") and isinstance(rec.get("stream_retry"), dict):
                rec["stream_retry"]["dispatch_at"] = rec["last_dispatch_at"]
            fleet.save_registry(data)
        return 0
    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    return sends


def test_p1_exhausted_lane_stays_dead_after_hours_and_reports_once(home, monkeypatch):
    """#74 P1-1: the bound is per death; elapsed time never resets it."""
    sends = _sends(monkeypatch)
    _exhaust(home)
    first = fleet.recover_lane(LANE, IDLE, now=NOW)
    assert first["done"] == "lane-dead"
    assert _lane()["stream_retry"]["exhausted_at"]
    for hours in (7, 13, 23):
        later = NOW + timedelta(hours=hours)
        assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=later)["action"] == "exhausted"
        assert fleet.recover_lane(LANE, IDLE, now=later)["done"] is None
    assert sends == [(PARENT, f"LANE-DEAD {LANE} stream-error-retries-exhausted", False)]


def test_p1_retry_chain_counts_one_death_and_a_new_dispatch_resets(home, monkeypatch):
    """Attempts chain through the dispatches the retries wrote; a dispatch the
    retry did not write (operator/supervisor send) starts a fresh budget."""
    clock = {"now": NOW}
    sends = _fake_retry_send(monkeypatch, clock)
    t = NOW
    for attempt in range(1, len(fleet.STREAM_RETRY_DELAYS_SECONDS) + 1):
        _tail(home, _api_error(CONNECTION_LOST, at=t))
        t += timedelta(seconds=_jittered(fleet.STREAM_RETRY_DELAYS_SECONDS[attempt - 1]) + 1)
        clock["now"] = t
        step = fleet.recover_lane(LANE, IDLE, now=t)
        assert (step["done"], step["attempt"]) == ("retried", attempt)
        assert _lane()["stream_retry"]["dispatch_at"] == _iso(t)
        t += timedelta(seconds=30)
        # Age the spent attempt out of the in-flight window: this pin is the chain.
        data = fleet.load_registry()
        data["workers"][LANE]["stream_retry"]["last_at"] = _iso(NOW - timedelta(hours=1))
        fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=t))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=t + timedelta(hours=8))[
        "action"] == "exhausted"
    assert len(sends) == 3
    # A non-retry dispatch: the next death has its own budget.
    _dispatch(t + timedelta(minutes=1))
    _tail(home, _api_error(CONNECTION_LOST, at=t + timedelta(minutes=2)))
    plan = fleet.stream_retry_plan(LANE, _lane(), IDLE, now=t + timedelta(minutes=30))
    assert (plan["action"], plan["attempt"]) == ("retry", 1)


def test_p2_1_jitter_spreads_sessions_inside_the_bound():
    fractions = {fleet._stream_retry_jitter(f"sid-{i}") for i in range(20)}
    assert len(fractions) > 10 and all(0 <= f < 1 for f in fractions)
    assert fleet._stream_retry_jitter("a") == fleet._stream_retry_jitter("a")


def test_p2_1_in_flight_cap_defers_the_rest_to_the_next_sweep(home, monkeypatch):
    sends = _sends(monkeypatch)
    data = fleet.load_registry()
    for i in range(fleet.STREAM_RETRY_MAX_IN_FLIGHT):
        other = fleet.new_worker_record(f"o{i}-sid", str(home), "w", "bypass")
        other["stream_retry"] = {"attempts": 1, "last_at": fleet.now_iso()}
        data["workers"][f"o{i}"] = other
    fleet.save_registry(data)
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=30)))
    assert fleet.recover_lane(LANE, IDLE, now=NOW)["done"] is None
    assert sends == [] and "stream_retry" not in _lane()


def test_p2_2_second_recoverer_cannot_spend_the_same_attempt(home):
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=30)))
    before = _lane()
    plan = fleet.stream_retry_plan(LANE, before, IDLE, now=NOW)
    assert fleet._record_stream_retry(LANE, before, plan)
    assert not fleet._record_stream_retry(LANE, before, plan)
    assert _lane()["stream_retry"]["attempts"] == 1


def test_p2_3_only_a_stream_wake_carries_the_retry_flag(home, monkeypatch):
    seen = []
    monkeypatch.setattr(fleet, "_sup_guard_lane_sweep", lambda *_: [])
    monkeypatch.setattr(fleet, "_sup_guard_dead_sweep",
                        lambda *_: {"stream_retried": [], "lane_dead_sent": []})
    monkeypatch.setattr(fleet, "_sup_guard_observe", lambda **_: {})
    monkeypatch.setattr(fleet, "_reap_current_supervisor_forks", lambda **_: None)
    monkeypatch.setattr(fleet, "_sup_guard_decide",
                        lambda _obs: ("WAKE", PARENT, {"body_name": PARENT}))
    monkeypatch.setattr(fleet, "cmd_send", lambda ns: seen.append(
        ns._fleet_stream_retry) or 0)
    try:
        fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True))
    except Exception:  # noqa: BLE001 -- output shaping is not this pin
        pass
    assert seen == [False]


def test_p2_4_transcript_text_without_stopfailure_marker_is_not_acted_on(home, monkeypatch):
    """A worker can append an error line to its own transcript; without the
    fleet-owned StopFailure marker it gets no retry and no api-error LANE-DEAD."""
    sends = _sends(monkeypatch)
    _tail(home, _api_error("API Error: 401 authentication_error",
                           at=NOW - timedelta(minutes=5)), marker=())
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "none"
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)), marker=())
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "none"
    step = fleet.recover_lane(LANE, IDLE, now=NOW)
    assert step.get("reason") != "api-error"
    assert all("api-error" not in m and m != fleet.STREAM_RETRY_MESSAGE
               for _, m, _ in sends)


def test_p2_4_marker_older_than_the_dispatch_does_not_vouch(home):
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=5)))
    marker = fleet.stopfailure_marker_path(LANE_SID)
    marker.write_text(json.dumps({"at": _iso(NOW - timedelta(hours=3))}))
    assert fleet.stream_retry_plan(LANE, _lane(), IDLE, now=NOW)["action"] == "none"


def test_p2_4_stream_recover_writes_the_marker(home, monkeypatch):
    sends = _sends(monkeypatch)
    _tail(home, _api_error(CONNECTION_LOST, at=NOW - timedelta(minutes=30)), marker=())
    assert not fleet.stopfailure_marker_path(LANE_SID).exists()
    fleet.cmd_stream_recover(SimpleNamespace(sid=LANE_SID, wait=False),
                             roster_fn=lambda: (True, IDLE), now_fn=lambda: NOW)
    assert fleet.stopfailure_marker_path(LANE_SID).exists()
    assert sends == [(LANE, fleet.STREAM_RETRY_MESSAGE, True)]


def test_p2_5_doctor_fails_an_instance_missing_a_template_event(home, monkeypatch):
    template = home / "template.json"
    template.write_text(json.dumps({"hooks": {"Stop": [], "StopFailure": []}}))
    monkeypatch.setattr(fleet, "template_settings_path", lambda: template)
    fleet.instance_settings_path().write_text(json.dumps({"hooks": {"Stop": []}}))
    name, ok, msg = fleet._doctor_check_hook_coverage()
    assert (name, ok) == ("hook-coverage", False)
    assert "StopFailure" in msg and "fleet init" in msg
    fleet.instance_settings_path().write_text(
        json.dumps({"hooks": {"Stop": [], "StopFailure": []}}))
    assert fleet._doctor_check_hook_coverage()[1] is True


def test_p2_5_shipped_template_registers_stopfailure():
    template = json.loads((HOOK.parents[2] / "worker-settings.template.json").read_text())
    assert "StopFailure" in template["hooks"]
