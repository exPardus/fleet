"""Targeted tests for the interface's two-live-body supervisor guard."""

import json
from types import SimpleNamespace

import pytest

import fleet


SID = "sid-current"
RETIRED = "sid-retired"
BODY = "sup|inc-guard|boot"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(fleet, "_reap_current_supervisor_forks", lambda **_: [])
    for name in ("state", "supervisor", "mailbox", "logs"):
        (tmp_path / name).mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# active\n")
    (tmp_path / "state" / "worker-settings.json").write_text("{}")
    record = fleet.new_worker_record(SID, str(tmp_path), "standing", "bypass",
                                     dispatch_kind="bg")
    record["retired_sids"] = [RETIRED]
    fleet.save_registry({"workers": {BODY: record}})
    claim = {"incarnation_id": "inc-guard", "session_id": SID,
             "claimed_via": "handoff", "heartbeat_at": "2026-09-09T00:00:00Z"}
    fleet.write_incarnation(claim)
    return tmp_path


def snapshot(age=4000, state="held", **extra):
    sup = {"goals_active": True, "state": state,
           "heartbeat_age_seconds": age}
    sup.update(extra)
    return {"ok": True, "workers": [], "supervisor": sup}


def roster(*rows):
    return lambda: (True, list(rows))


def row(sid, *, status="idle", pid=42, name=BODY, state="working"):
    return {"sessionId": sid, "status": status, "pid": pid,
            "name": name, "state": state}


def run_guard(monkeypatch, snap, rows=(), **args):
    monkeypatch.setattr(fleet, "status_snapshot", lambda: snap)
    return fleet.cmd_sup_guard(
        SimpleNamespace(do=False, json=False, **args),
        roster_fn=roster(*rows),
    )


def test_live_idle_body_under_retired_sid_is_wake_not_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(RETIRED)])
    assert capsys.readouterr().out == f"WAKE {BODY}\n"


@pytest.mark.parametrize("status", ["idle", "busy"])
def test_fresh_live_body_is_ok(home, monkeypatch, capsys, status):
    run_guard(monkeypatch, snapshot(age=10), [row(RETIRED, status=status)])
    assert capsys.readouterr().out == "OK\n"


def test_stale_claim_with_no_live_union_sid_is_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot())
    assert capsys.readouterr().out == "DISPATCH\n"


def test_unreadable_registry_is_page_not_dispatch(home, monkeypatch, capsys):
    broken = {"ok": False, "reason": "quarantined", "workers": [],
              "supervisor": {"goals_active": True, "state": "held",
                              "heartbeat_age_seconds": 4000}}
    run_guard(monkeypatch, broken)
    assert capsys.readouterr().out == (
        "PAGE registry unavailable: quarantined\n")


def test_unreadable_roster_is_page(home, capsys):
    fleet.cmd_sup_guard(SimpleNamespace(do=False, json=False),
                        snapshot_fn=snapshot,
                        roster_fn=lambda: (False, "unreadable"))
    assert capsys.readouterr().out == "PAGE roster unavailable: unreadable\n"


def test_live_busy_body_is_page_not_dispatch(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(SID, status="busy")])
    assert capsys.readouterr().out == "PAGE roster says busy\n"


def test_pidless_listed_body_can_dispatch_when_stale(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(), [row(SID, pid=None)])
    assert capsys.readouterr().out == "DISPATCH\n"


def test_fresh_claim_with_missing_body_pages(home, monkeypatch, capsys):
    run_guard(monkeypatch, snapshot(age=10))
    assert capsys.readouterr().out == (
        "PAGE fresh heartbeat but body is not roster-live\n")


def test_fresh_seized_claim_uses_ordinary_held_rule(home, monkeypatch, capsys):
    claim = fleet.read_incarnation()
    claim["claimed_via"] = "seize"
    fleet.write_incarnation(claim)
    run_guard(monkeypatch, snapshot(age=10))
    assert capsys.readouterr().out == (
        "PAGE fresh heartbeat but body is not roster-live\n")


def test_stale_seized_claim_still_pages_as_seized(home, monkeypatch, capsys):
    """Unsettled seize: claimed_at == heartbeat_at, the takeover never proved out."""
    claim = fleet.read_incarnation()
    claim["claimed_via"] = "seize"
    claim["claimed_at"] = claim.get("claimed_at") or "2026-09-10T15:30:11Z"
    claim["heartbeat_at"] = claim["claimed_at"]
    fleet.write_incarnation(claim)
    run_guard(monkeypatch, snapshot(age=4000))
    assert capsys.readouterr().out == "PAGE claim seized\n"


def test_a_seize_settled_by_a_heartbeat_is_an_ordinary_stale_claim(home, monkeypatch,
                                                                   capsys):
    """A seize is ambiguous only until the seizing body beats once.

    Measured twice on the live claim: a seizure 5h then 8h old, heartbeated many
    times since, still returned `PAGE claim seized` -- so the interface was told
    to page a healthy supervisor instead of waking an idle one. A seize hours old
    is not evidence about now; only the beat that followed it is.
    """
    claim = fleet.read_incarnation()
    claim["claimed_via"] = "seize"
    claim["claimed_at"] = "2026-09-10T15:30:11Z"
    claim["heartbeat_at"] = "2026-09-10T23:00:00Z"
    fleet.write_incarnation(claim)
    run_guard(monkeypatch, snapshot(age=4000), [row(RETIRED)])
    out = capsys.readouterr().out
    assert not out.startswith("PAGE claim seized"), out
    assert out.startswith("WAKE "), out


def test_handshake_always_pages(home, monkeypatch, capsys):
    (home / "supervisor" / "HANDSHAKE").write_text(
        json.dumps({"incarnation_id": "inc-guard"}))
    run_guard(monkeypatch, snapshot(), [row(RETIRED)])
    assert capsys.readouterr().out == "PAGE handoff in flight\n"


def test_no_claim_with_live_supervisor_body_pages(home, monkeypatch, capsys):
    fleet.incarnation_path().unlink()
    run_guard(monkeypatch, snapshot(state="none", age=None),
              [row(RETIRED)])
    assert capsys.readouterr().out == (
        "PAGE live supervisor body without a safe claim\n")


@pytest.mark.parametrize("name", [BODY, None, "adopted-host"])
def test_released_body_live_under_retired_sid_never_dispatches(
        home, monkeypatch, capsys, name):
    claim = fleet.read_incarnation()
    claim.update(state="released", released_by_sid=SID)
    fleet.write_incarnation(claim)
    run_guard(monkeypatch, snapshot(state="released"), [row(RETIRED, name=name)])
    assert capsys.readouterr().out == (
        "PAGE live supervisor body without a safe claim\n")


@pytest.mark.parametrize("status", ["idle", "busy"])
def test_do_ok_has_no_action(home, monkeypatch, capsys, status):
    def forbidden(*args, **kwargs):
        pytest.fail("OK must perform no action")
    monkeypatch.setattr(fleet, "cmd_send", forbidden)
    monkeypatch.setattr(fleet, "cmd_sup_spawn", forbidden)
    monkeypatch.setattr(fleet, "_reap_current_supervisor_forks", forbidden)
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=lambda: snapshot(age=10),
                               roster_fn=roster(row(SID, status=status))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["verdict"] == "OK"
    assert result["sent"] is False


@pytest.mark.parametrize("ambiguity,reason", [
    ({"state": "unknown"}, "claim state unknown"),
    ({"handshake_exists": True}, "supervisor/HANDSHAKE unreadable"),
    ({"pending": True}, "handoff in flight"),
    ({"claim_sids": None}, "claim session not in the roster, sid union unavailable"),
    ({"limited": True}, "supervisor limited"),
])
def test_fresh_live_body_still_pages_on_ambiguity(home, ambiguity, reason):
    obs = fleet._sup_guard_observe(snapshot_fn=lambda: snapshot(age=10),
                                  roster_fn=roster(row(SID)))
    obs.update(ambiguity)
    verdict, actual_reason, _ = fleet._sup_guard_decide(obs)
    assert (verdict, actual_reason) == ("PAGE", reason)


def test_held_over_band_claim_pages_with_recorded_context(home, monkeypatch):
    claim = fleet.read_incarnation()
    claim.update(context_occupancy=405000, context_verdict="over-band",
                 context_measured_at="2026-09-12T00:00:00Z")
    fleet.write_incarnation(claim)
    obs = fleet._sup_guard_observe(snapshot_fn=lambda: snapshot(age=10),
                                  roster_fn=roster(row(SID)))
    verdict, reason, detail = fleet._sup_guard_decide(obs)
    assert verdict == "PAGE"
    assert "occupancy=405000" in reason
    assert "ceiling=400000" in reason
    assert detail["context_verdict"] == "over-band"


def test_a_dead_over_band_claim_still_dispatches_a_replacement(home):
    """The recorded verdict outlives the body that wrote it.

    An over-band supervisor is the one most likely to die, and its claim keeps
    saying `over-band` after it does. If the over-band arm fired on a stale
    claim it would answer PAGE where the guard used to answer DISPATCH, so the
    dead body would wait for a human instead of being replaced -- a downtime
    regression in exactly the case the feature exists for.
    """
    claim = fleet.read_incarnation()
    claim.update(context_occupancy=405000, context_verdict="over-band",
                 context_measured_at="2026-09-12T00:00:00Z")
    fleet.write_incarnation(claim)
    obs = fleet._sup_guard_observe(snapshot_fn=lambda: snapshot(age=4000),
                                  roster_fn=roster())
    verdict, reason, _ = fleet._sup_guard_decide(obs)
    assert (verdict, reason) == ("DISPATCH", "stale claim with no live body")


@pytest.mark.parametrize("status", ["idle", "busy", "unknown"])
@pytest.mark.parametrize("age", [None, 10, 4000])
def test_live_body_never_dispatches(home, status, age):
    obs = fleet._sup_guard_observe(snapshot_fn=lambda: snapshot(age=age),
                                  roster_fn=roster(row(RETIRED, status=status)))
    assert fleet._sup_guard_decide(obs)[0] != "DISPATCH"


def test_do_dispatch_never_spawns(
        home, monkeypatch, capsys):
    calls = []
    dispatch_observation = {
        "state": "held", "claim": {"claimed_via": "handoff"},
        "claim_sids": [SID], "roster_ok": True, "roster_reason": None,
        "live_rows": {}, "live_body_rows": [], "handshake_exists": False,
        "handshake": None, "pending": False, "body_name": BODY,
        "heartbeat_age_seconds": 4000, "goals_active": True,
    }
    observations = iter((dispatch_observation, dispatch_observation))
    monkeypatch.setattr(fleet, "_sup_guard_observe",
                        lambda **_: next(observations))
    monkeypatch.setattr(fleet, "cmd_sup_spawn",
                        lambda args: calls.append(args) or 0)
    rc = fleet.cmd_sup_guard(SimpleNamespace(do=True, json=False))
    assert rc == 0
    assert calls == []  # DISPATCH belongs to the interface, including --do
    assert capsys.readouterr().out == "DISPATCH\n"


def test_do_page_has_no_action(home, monkeypatch, capsys):
    calls = []
    observation = {
        "state": "held", "claim": {"claimed_via": "seize"},
        "claim_sids": [SID], "roster_ok": True, "roster_reason": None,
        "live_rows": {}, "live_body_rows": [], "handshake_exists": False,
        "handshake": None, "pending": False, "body_name": BODY,
        "heartbeat_age_seconds": 4000, "goals_active": True,
    }
    monkeypatch.setattr(fleet, "_sup_guard_observe", lambda **_: observation)
    monkeypatch.setattr(fleet, "cmd_sup_spawn",
                        lambda args: calls.append(args) or 0)
    monkeypatch.setattr(fleet, "cmd_send", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(fleet, "_reap_current_supervisor_forks",
                        lambda **_: calls.append("reap"))
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=False)) == 0
    assert not calls
    assert capsys.readouterr().out == "PAGE claim seized\n"


@pytest.mark.parametrize('second', ['busy', 'no-pid', 'fresh'])
def test_do_reverifies_wake_before_send(home, monkeypatch, capsys, second):
    calls = []
    snapshots = iter([snapshot(), snapshot(age=10) if second == 'fresh' else snapshot()])
    rows = iter([[row(SID)], [row(SID, status='busy')] if second == 'busy'
                 else [row(SID, pid=None)] if second == 'no-pid' else [row(SID)]])
    monkeypatch.setattr(fleet, 'cmd_send', lambda args: calls.append(args) or 0)
    monkeypatch.setattr(fleet, 'cmd_sup_spawn', lambda _: pytest.fail('spawn forbidden'))
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=lambda: next(snapshots),
                               roster_fn=lambda: (True, next(rows))) == 0
    assert not calls
    assert not json.loads(capsys.readouterr().out)['sent']


def test_do_wake_sends_exact_brief_once(home, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(fleet, 'cmd_send', lambda args: calls.append(args) or 0)
    monkeypatch.setattr(fleet, 'cmd_sup_spawn', lambda _: pytest.fail('spawn forbidden'))
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=snapshot, roster_fn=roster(row(SID))) == 0
    assert len(calls) == 1
    assert calls[0].name == 'supervisor'
    assert calls[0].message == '@supervisor/briefs/wake.md'
    assert json.loads(capsys.readouterr().out)['sent'] is True


@pytest.mark.parametrize('failure', ['return', 'raise'])
def test_send_failure_is_page_not_a_successful_wake(home, monkeypatch, capsys, failure):
    def send(args):
        if failure == 'raise':
            raise fleet.FleetCliError('refused')
        return 1
    monkeypatch.setattr(fleet, 'cmd_send', send)
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=snapshot, roster_fn=roster(row(SID))) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['verdict'].startswith('PAGE supervisor wake send failed')
    assert result['sent'] is False


@pytest.mark.parametrize('pid', [None, 42])
def test_native_limited_row_never_sends_or_dispatches(home, monkeypatch, capsys, pid):
    limited = row(SID, status='limited', pid=pid)
    limited['limit_reset_at'] = '2099-01-01T00:00:00Z'
    monkeypatch.setattr(fleet, 'cmd_send', lambda _: pytest.fail('send forbidden'))
    monkeypatch.setattr(fleet, 'cmd_sup_spawn', lambda _: pytest.fail('spawn forbidden'))
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=snapshot, roster_fn=roster(limited)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['verdict'] == 'PAGE supervisor limited'
    assert result['limit_reset_at'] == limited['limit_reset_at']


def test_projected_limited_park_overrides_idle_roster(home, monkeypatch, capsys):
    snap = snapshot()
    snap['workers'] = [{'name': BODY, 'status': 'limited',
                        'limit_reset_at': '2099-01-01T00:00:00Z'}]
    monkeypatch.setattr(fleet, 'cmd_send', lambda _: pytest.fail('send forbidden'))
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True), snapshot_fn=lambda: snap,
                        roster_fn=roster(row(SID)))
    assert json.loads(capsys.readouterr().out)['verdict'] == 'PAGE supervisor limited'


def test_guard_retries_deferred_fork_retirement_before_revalidation(home, monkeypatch):
    calls = []
    monkeypatch.setattr(fleet, '_reap_current_supervisor_forks',
                        lambda **_: calls.append('reap'))
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                        snapshot_fn=lambda: calls.append('observe') or snapshot(),
                        roster_fn=roster(row(SID)))
    assert calls == ['observe', 'reap', 'observe']


def test_limit_discovered_by_send_is_published_as_park_not_retry(home, monkeypatch, capsys):
    snap = snapshot()
    calls = []
    def send(args):
        calls.append(args)
        snap['workers'] = [{'name': BODY, 'status': 'limited',
                            'limit_reset_at': '2099-01-01T00:00:00Z'}]
        raise fleet.FleetCliError('parked (limited)')
    monkeypatch.setattr(fleet, 'cmd_send', send)
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                               snapshot_fn=lambda: snap, roster_fn=roster(row(SID))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['verdict'] == 'PAGE supervisor limited'
    assert result['limit_reset_at'] == '2099-01-01T00:00:00Z'
    assert not result['sent'] and len(calls) == 1


def test_a_done_row_with_a_live_pid_is_live(home, monkeypatch, capsys):
    """A bg-spare host reports `state: done` while still running.

    Measured 2026-09-11: two sids of the live claim holder appeared as
    `status: idle, state: done, pid: <live>` because the daemon had adopted
    spare hosts as session hosts. Excluding `done` made the guard page a body it
    could plainly see. The pid is the liveness fact.
    """
    run_guard(monkeypatch, snapshot(age=4000),
              [row(RETIRED, status="idle", pid=3531952, state="done")])
    assert capsys.readouterr().out == f"WAKE {BODY}\n"
