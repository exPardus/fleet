"""A gone native Codex host is detected once and reported once.

When the home's Codex host process dies, every native lane bound to it fails
at once. Before this, each lane flipped to dead-suspected on its own schedule
and produced its own LANE-DEAD mail and keeper page. `sup-guard --do` now
marks every affected row once with `codex_host_gone`, sends one
CODEX-HOST-GONE notice, and the keeper pages once per host generation.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet
import fleet_keeper

GEN_OLD = "11111111-2222-4333-8444-555555555555"
GEN_NEW = "66666666-7777-4888-9999-000000000000"


def _iso(age_seconds=60):
    at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _native(status="working", generation=GEN_OLD, **over):
    row = {"substrate": "codex", "dispatch_kind": "codex-app-server",
           "session_id": None, "codex_thread_id": "thread", "codex_turn_id": "turn",
           "codex_host_generation": generation, "status": status, "turns": 1,
           "last_dispatch_at": _iso()}
    row.update(over)
    return row


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for name in ("state", "mailbox", "supervisor", "logs"):
        (tmp_path / name).mkdir()
    return tmp_path


def _save(workers):
    fleet.save_registry({"workers": workers})


GONE = ("gone", None, "no ready Codex host (test)")


@pytest.mark.parametrize("presence, expected", [
    (GONE, {"a", "b"}),
    (("live", GEN_OLD, None), set()),
    (("live", GEN_NEW, None), {"a", "b"}),
    (("unknown", None, "unreadable"), set()),
])
def test_affected_rows_are_in_flight_native_rows_of_a_gone_generation(
        presence, expected):
    workers = {"a": _native("working"), "b": _native("dead-suspected"),
               "idle": _native("idle"), "dead": _native("dead"),
               "mcx": {"substrate": "codex", "mcx_id": "m", "session_id": None,
                       "status": "working"},
               "claude": {"session_id": "s", "status": "working"},
               "archived": _native("working", archived_at="2026-01-01T00:00:00Z")}
    assert set(fleet._codex_host_gone_rows(workers, presence)) == expected


def test_the_sweep_marks_every_row_once_and_sends_one_notice(home, monkeypatch):
    _save({"a": _native("working"), "b": _native("dead-suspected"),
           "c": _native("idle")})
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    monkeypatch.setattr(fleet, "read_incarnation", lambda: {"state": "held"})
    monkeypatch.setattr(fleet, "_claim_holder_row_name", lambda claim, data: "sup-body")
    mail = []
    monkeypatch.setattr(fleet, "_deliver_lane_mail",
                        lambda claim, parent, message, **k: mail.append((parent, message)))
    assert fleet.sweep_codex_host_gone() == ["a", "b"]
    workers = fleet.load_registry()["workers"]
    for name in ("a", "b"):
        assert workers[name]["status"] == "dead-suspected"
        assert workers[name]["adapter_state"] == "host-gone"
        assert workers[name]["codex_host_gone"]["generation"] == GEN_OLD
    assert "codex_host_gone" not in workers["c"]
    assert len(mail) == 1 and mail[0][0] == "sup-body"
    assert mail[0][1].startswith("CODEX-HOST-GONE 2 fresh in-flight lane(s): a b")
    # The next sweep finds nothing new: no second mark, no second notice.
    assert fleet.sweep_codex_host_gone() == []
    assert len(mail) == 1
    events = [json.loads(line) for line in
              fleet.events_path().read_text().splitlines()]
    assert [e["kind"] for e in events].count("codex_host_gone") == 1


def test_a_respawned_row_on_a_new_generation_is_marked_again(home, monkeypatch):
    marked = _native("working", generation=GEN_NEW,
                     codex_host_gone={"generation": GEN_OLD})
    _save({"a": marked})
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    monkeypatch.setattr(fleet, "read_incarnation", lambda: None)
    assert fleet.sweep_codex_host_gone() == ["a"]


def test_an_unreadable_host_marks_nothing(home, monkeypatch):
    _save({"a": _native("working")})
    monkeypatch.setattr(fleet, "_codex_host_presence",
                        lambda: ("unknown", None, "unreadable"))
    assert fleet.sweep_codex_host_gone() == []
    assert "codex_host_gone" not in fleet.load_registry()["workers"]["a"]


def test_a_marked_row_gets_no_per_lane_lane_dead(home, monkeypatch):
    _save({"a": _native("dead-suspected",
                        codex_host_gone={"generation": GEN_OLD})})
    monkeypatch.setattr(fleet, "read_incarnation",
                        lambda: pytest.fail("a marked row must stop before the claim"))
    assert fleet.notify_lane_dead("a", "no-outcome") is False


def test_a_marked_row_keeps_its_verdict_without_reading_the_host(monkeypatch):
    monkeypatch.setattr(fleet, "_codex_worker_binding",
                        lambda *a: pytest.fail("no host read for a marked row"))
    row = _native("dead-suspected", codex_host_gone={"generation": GEN_OLD})
    assert fleet.recompute_worker_codex("a", row)["status"] == "dead-suspected"


def test_the_keeper_pages_once_per_host_generation():
    obs = {"workers": [
        {"name": n, "status": "dead-suspected", "turns": 1,
         "codex_host_gone": {"generation": GEN_OLD}} for n in ("a", "b", "c")]
        + [{"name": "d", "status": "dead-suspected", "turns": 1}]}
    found = fleet_keeper.worker_anomalies(obs)
    assert found == {
        f"codex-host-gone:{GEN_OLD}": "codex-host-gone(3 lanes: a, b, c)",
        "d(dead-suspected):1": "d(dead-suspected)"}
    page = fleet_keeper.rule_worker_anomaly(obs, 0)
    seen_after = list(found)
    assert fleet_keeper.rule_worker_anomaly(
        dict(obs, anomaly_seen=seen_after), 0) is None
    assert page.text.count("codex-host-gone") == 1


def test_doctor_reports_marked_and_unmarked_lanes(home, monkeypatch):
    workers = {"a": _native("working", codex_host_gone={"generation": GEN_OLD}),
               "b": _native("working")}
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    name, ok, message = fleet._doctor_check_codex_host(workers)
    assert (name, ok) == ("codex-host", False)
    assert "marked: a" in message and "unmarked: b" in message
    monkeypatch.setattr(fleet, "_codex_host_presence",
                        lambda: ("live", GEN_OLD, None))
    assert fleet._doctor_check_codex_host(workers)[1] is True
    assert fleet._doctor_check_codex_host({})[1] is True


def test_sup_guard_runs_the_host_sweep_before_lane_dead(monkeypatch):
    order = []
    monkeypatch.setattr(fleet, "read_incarnation", lambda: {"provider": "codex"})
    monkeypatch.setattr(fleet, "_sup_guard_lane_sweep", lambda r: order.append("done") or [])
    monkeypatch.setattr(fleet, "_sup_guard_codex_host_sweep",
                        lambda: order.append("host") or ["a"])
    monkeypatch.setattr(fleet, "_sup_guard_dead_sweep",
                        lambda r: order.append("dead") or {"stream_retried": [],
                                                           "lane_dead_sent": []})
    monkeypatch.setattr(fleet, "_sup_guard_idle_sweep", lambda r: [])
    captured = {}
    monkeypatch.setattr(fleet, "_cmd_codex_sup_guard",
                        lambda args, lane_done, lane_dead: captured.update(lane_dead) or 0)
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True))
    assert order == ["done", "host", "dead"]
    assert captured["codex_host_gone"] == ["a"]


def test_the_sweep_wrapper_never_breaks_the_guard(monkeypatch, capsys):
    def boom():
        raise RuntimeError("host probe exploded")
    monkeypatch.setattr(fleet, "sweep_codex_host_gone", boom)
    assert fleet._sup_guard_codex_host_sweep() == []
    assert "codex-host sweep failed" in capsys.readouterr().err


# Review w598 of 1be2de40: a staged failed-client recovery replaces the host
# on purpose and rebinds rows one by one; the sweep must not mark them.
def _barrier(home, state):
    path = home / "state" / "codex" / "failed-client-recovery.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "home": str(home.resolve()),
                                "state": state}))
    path.parent.chmod(0o700)
    path.chmod(0o600)


@pytest.mark.parametrize("state", ["prepared", "authorized", "shutdown_sent",
                                   "shutdown_ack", "exited", "boot_requested",
                                   "rebind"])
def test_a_recovery_in_progress_marks_nothing(home, monkeypatch, state):
    _save({"a": _native("working")})
    _barrier(home, state)
    monkeypatch.setattr(fleet, "_codex_host_presence",
                        lambda: ("live", GEN_NEW, None))
    assert fleet.sweep_codex_host_gone() == []
    row = fleet.load_registry()["workers"]["a"]
    assert row["status"] == "working" and "codex_host_gone" not in row
    name, ok, message = fleet._doctor_check_codex_host(fleet.load_registry()["workers"])
    assert ok is True and f"state {state}" in message and "paused" in message


def test_an_unreadable_recovery_fence_marks_nothing(home, monkeypatch):
    _save({"a": _native("working")})
    path = home / "state" / "codex" / "failed-client-recovery.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    assert fleet.sweep_codex_host_gone() == []
    assert "codex_host_gone" not in fleet.load_registry()["workers"]["a"]


def test_after_a_complete_recovery_held_rows_stay_unmarked(home, monkeypatch):
    _save({"held": _native("dead"), "interrupted": _native("interrupted"),
           "live": _native("working")})
    _barrier(home, "complete")
    monkeypatch.setattr(fleet, "_codex_host_presence",
                        lambda: ("live", GEN_NEW, None))
    monkeypatch.setattr(fleet, "read_incarnation", lambda: None)
    assert fleet.sweep_codex_host_gone() == ["live"]
    workers = fleet.load_registry()["workers"]
    assert "codex_host_gone" not in workers["held"]
    assert "codex_host_gone" not in workers["interrupted"]


def test_a_failed_notice_is_sent_again_next_sweep(home, monkeypatch):
    _save({"a": _native("working"), "b": _native("working")})
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    monkeypatch.setattr(fleet, "read_incarnation", lambda: {"state": "held"})
    monkeypatch.setattr(fleet, "_claim_holder_row_name", lambda c, d: "sup-body")
    attempts = []

    def deliver(claim, parent, message, **k):
        attempts.append(message)
        if len(attempts) == 1:
            raise fleet.FleetCliError("supervisor busy")

    monkeypatch.setattr(fleet, "_deliver_lane_mail", deliver)
    assert fleet.sweep_codex_host_gone() == ["a", "b"]
    assert fleet.load_registry()["workers"]["a"]["codex_host_gone"]["notified"] is False
    assert fleet.sweep_codex_host_gone() == ["a", "b"]
    assert len(attempts) == 2 and attempts[1].startswith("CODEX-HOST-GONE 2 fresh in-flight lane(s)")
    assert fleet.load_registry()["workers"]["a"]["codex_host_gone"]["notified"] is True
    assert fleet.sweep_codex_host_gone() == []
    assert len(attempts) == 2
    events = [json.loads(line) for line in
              fleet.events_path().read_text().splitlines()]
    assert [e["kind"] for e in events].count("codex_host_gone") == 1


class _Client:
    def __init__(self, generation, live):
        self.generation, self.host_pid, self._live = generation, 4242, live

    def _owner_live(self):
        return self._live


def test_presence_maps_the_existing_client_facade(monkeypatch):
    from fleet_codex import HostUnavailable

    def gone(_home):
        raise HostUnavailable("no ready Codex host exists for this Fleet home")
    monkeypatch.setattr(fleet, "_codex_existing_client", gone)
    assert fleet._codex_host_presence()[0] == "gone"
    monkeypatch.setattr(fleet, "_codex_existing_client",
                        lambda _home: _Client(GEN_OLD, False))
    assert fleet._codex_host_presence()[:2] == ("gone", GEN_OLD)
    monkeypatch.setattr(fleet, "_codex_existing_client",
                        lambda _home: _Client(GEN_OLD, True))
    assert fleet._codex_host_presence() == ("live", GEN_OLD, None)

    def unsafe(_home):
        raise fleet.FleetCliError("Codex host metadata has wrong home")
    monkeypatch.setattr(fleet, "_codex_existing_client", unsafe)
    assert fleet._codex_host_presence()[0] == "unknown"


# Interface direction faecbc6d: the first sweep after #101 paged 84 Codex rows
# dead for weeks. Only fresh in-flight rows page, once per host loss.
def _wire_mail(monkeypatch):
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    monkeypatch.setattr(fleet, "read_incarnation", lambda: {"state": "held"})
    monkeypatch.setattr(fleet, "_claim_holder_row_name", lambda c, d: "sup-body")
    mail = []
    monkeypatch.setattr(fleet, "_deliver_lane_mail",
                        lambda claim, parent, message, **k: mail.append(message))
    return mail


def _old_rows(count=84):
    month = 30 * 24 * 3600
    rows = {}
    for i in range(count):
        status = ("dead-suspected", "working", "dead", "idle")[i % 4]
        rows[f"old{i:02d}"] = _native(status, last_dispatch_at=_iso(month + i))
    return rows


def test_84_old_dead_rows_produce_no_notice(home, monkeypatch):
    mail = _wire_mail(monkeypatch)
    _save(_old_rows())
    assert fleet.sweep_codex_host_gone() == []
    assert mail == []
    workers = fleet.load_registry()["workers"]
    assert not any("codex_host_gone" in row for row in workers.values())


def test_one_fresh_working_row_among_them_produces_exactly_one(home, monkeypatch):
    mail = _wire_mail(monkeypatch)
    workers = _old_rows()
    workers["fresh"] = _native("working")
    _save(workers)
    assert fleet.sweep_codex_host_gone() == ["fresh"]
    assert fleet.sweep_codex_host_gone() == []
    assert len(mail) == 1
    assert mail[0].startswith("CODEX-HOST-GONE 1 fresh in-flight lane(s): fresh ")


def test_a_dead_suspected_row_is_fresh_only_within_24_hours(home, monkeypatch):
    mail = _wire_mail(monkeypatch)
    day = fleet.LANE_DEAD_MAX_AGE_SECONDS
    _save({"recent": _native("dead-suspected", last_dispatch_at=_iso(day - 600)),
           "old": _native("dead-suspected", last_dispatch_at=_iso(day + 600))})
    assert fleet.sweep_codex_host_gone() == ["recent"]
    assert len(mail) == 1 and " recent " in mail[0] and "old" not in mail[0]


def test_a_host_loss_already_paged_is_not_paged_again(home, monkeypatch):
    mail = _wire_mail(monkeypatch)
    _save({"a": _native("working")})
    assert fleet.sweep_codex_host_gone() == ["a"]
    data = fleet.load_registry()
    data["workers"]["late"] = _native("working")
    fleet.save_registry(data)
    assert fleet.sweep_codex_host_gone() == []
    late = fleet.load_registry()["workers"]["late"]
    assert late["codex_host_gone"]["notified"] is True
    assert len(mail) == 1


def test_doctor_lists_old_rows_read_only_as_a_note(home, monkeypatch):
    monkeypatch.setattr(fleet, "_codex_host_presence", lambda: GONE)
    workers = _old_rows(8)
    name, ok, message = fleet._doctor_check_codex_host(workers)
    assert ok is True and message.startswith("NOTE ")
    assert "dead > 24 h, never paged: old00, old01, old04, old05" in message
    workers["fresh"] = _native("working")
    assert fleet._doctor_check_codex_host(workers)[1] is False


def test_the_keeper_skips_host_gone_rows_dead_past_its_horizon():
    old = fleet_keeper.WORKER_ANOMALY_MAX_AGE_SECONDS + 1
    obs = {"workers": [
        {"name": f"old{i}", "status": "dead-suspected", "turns": 1,
         "stale_seconds": old, "codex_host_gone": {"generation": GEN_OLD}}
        for i in range(84)]}
    assert fleet_keeper.worker_anomalies(obs) == {}
    obs["workers"].append({"name": "fresh", "status": "dead-suspected", "turns": 1,
                           "stale_seconds": 60,
                           "codex_host_gone": {"generation": GEN_OLD}})
    assert fleet_keeper.worker_anomalies(obs) == {
        f"codex-host-gone:{GEN_OLD}": "codex-host-gone(1 lanes: fresh)"}


def test_an_old_dispatch_with_recent_activity_is_fresh(home, monkeypatch):
    """Review w598 of 6ad34143 (P2): the Codex observation path updates
    last_activity, which the keeper ages by; a lane dispatched 30 h ago but
    seen working 5 minutes before the host died must be marked and paged."""
    mail = _wire_mail(monkeypatch)
    old = _iso(30 * 3600)
    _save({"long-lane": _native("working", created=old, last_dispatch_at=old,
                                last_activity=_iso(300))})
    assert fleet.sweep_codex_host_gone() == ["long-lane"]
    assert len(mail) == 1 and " long-lane " in mail[0]
    row = fleet.load_registry()["workers"]["long-lane"]
    assert row["status"] == "dead-suspected"
    name, ok, message = fleet._doctor_check_codex_host({"long-lane": row})
    assert ok is False and "never paged: none" in message

