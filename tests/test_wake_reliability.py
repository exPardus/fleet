"""w104: a supervisor that ends its turn while lanes run is woken when a lane
finishes, every time. One regression per root cause found in the PX home's
events (2026-09-26..28), plus the sup-guard backstop and the sup-boot
generation loss."""
import io
import json
import runpy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


PARENT = "sup|inc-test|boot"
FIRST_SID = "sup-sid-1"      # the sid that spawned the lanes
WOKEN_SID = "sup-sid-2"      # the sid after one `fleet send` wake
LINEAGE = "lin-test"
LANE_SID = "lane-sid"
STOP_HOOK = Path(__file__).resolve().parents[1] / "bin" / "hooks" / "stop_mailbox.py"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """The PX shape: the supervisor was woken once since it spawned the lane."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "supervisor").mkdir()
    parent = fleet.new_worker_record(WOKEN_SID, str(tmp_path), "supervise", "bypass")
    parent["status"] = "idle"
    parent["retired_sids"] = [FIRST_SID]
    lane = fleet.new_worker_record(LANE_SID, str(tmp_path), "work", "bypass",
                                   spawned_by=FIRST_SID, spawned_by_lineage=LINEAGE)
    lane["status"] = "working"
    fleet.save_registry({"workers": {PARENT: parent, "lane": lane}})
    fleet.write_incarnation({"state": "held", "session_id": WOKEN_SID,
                             "lineage_id": LINEAGE,
                             "heartbeat_at": _iso(datetime.now(timezone.utc))})
    monkeypatch.setattr(fleet.time, "sleep", lambda s: None)
    return tmp_path


@pytest.fixture
def sends(monkeypatch):
    got = []
    monkeypatch.setattr(fleet, "_cmd_send_native",
                        lambda name, message: got.append((name, message)) or 0)
    return got


def _no_git(*a, **k):
    return SimpleNamespace(returncode=1, stdout="")


# RC1 -- supervisor sid rotation -------------------------------------------

def test_lane_spawned_by_a_retired_supervisor_sid_is_delivered(home, sends):
    """px-w12-llmfc: spawned_by 8bbc14f6, holder 894cc69f after a wake."""
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def test_lineage_alone_proves_ownership(home, sends):
    data = fleet.load_registry()
    data["workers"]["lane"]["spawned_by"] = "sid-not-in-any-row"
    fleet.save_registry(data)
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def test_foreign_lineage_and_foreign_sid_are_not_delivered(home, sends):
    data = fleet.load_registry()
    data["workers"]["lane"].update({"spawned_by": "sid-of-another-body",
                                    "spawned_by_lineage": "lin-other"})
    fleet.save_registry(data)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID)
    assert sends == []


def _load_hook():
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_hook_w104", STOP_HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("variant", ["retired-sid", "lineage-only"])
def test_stop_precheck_passes_after_supervisor_sid_rotation(home, monkeypatch, variant):
    if variant == "lineage-only":
        data = fleet.load_registry()
        data["workers"]["lane"]["spawned_by"] = "sid-not-in-any-row"
        fleet.save_registry(data)
    mod = _load_hook()
    assert mod._lane_done_candidate(LANE_SID, str(home)) is True


def test_stop_precheck_still_skips_a_foreign_lane(home):
    data = fleet.load_registry()
    data["workers"]["lane"].update({"spawned_by": "sid-of-another-body",
                                    "spawned_by_lineage": "lin-other"})
    fleet.save_registry(data)
    assert _load_hook()._lane_done_candidate(LANE_SID, str(home)) is False


# RC2 -- per-dispatch dedupe key -------------------------------------------

def _transcript(path, uuids):
    path.write_text("".join(
        json.dumps({"type": "assistant", "uuid": u, "message": {}}) + "\n"
        + json.dumps({"type": "system", "uuid": u + "-sys"}) + "\n"
        for u in uuids), encoding="utf-8")


def test_a_second_finish_in_the_same_dispatch_is_delivered(home, sends, monkeypatch):
    """px-w12-streak: an interim Stop at 20:00 set the marker; the real finish
    at 22:31 had the same [sid, last_dispatch_at] and was dropped."""
    transcript = home / "lane.jsonl"
    monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: transcript)
    _transcript(transcript, ["a1"])
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    # Stop, hook, and a later observation of the same finish: one delivery.
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    _transcript(transcript, ["a1", "a2"])   # the lane continued and stopped again
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert len(sends) == 2


def test_turn_key_without_a_transcript_is_the_dispatch_pair(home, monkeypatch):
    monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: None)
    rec = fleet.load_registry()["workers"]["lane"]
    assert fleet._lane_done_turn_key("lane", rec) == [LANE_SID, rec["last_dispatch_at"]]


# RC3 -- an idle supervisor does not heartbeat ------------------------------

def test_stale_heartbeat_of_an_idle_holder_still_delivers(home, sends):
    claim = fleet.read_incarnation()
    claim["heartbeat_at"] = _iso(datetime.now(timezone.utc) - timedelta(hours=3))
    fleet.write_incarnation(claim)
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


# RC4 -- transient G9 refusal ----------------------------------------------

def test_one_g9_refusal_is_retried(home, monkeypatch):
    calls, pauses = [], []

    def send(name, message):
        calls.append(name)
        if len(calls) == 1:
            raise fleet.TransientSendRefusal("roster fetch unavailable/suspicious (G9)")
        return 0

    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                                  run=_no_git, sleep=pauses.append)
    assert calls == [PARENT, PARENT]
    assert pauses == [fleet.LANE_DONE_RETRY_SECONDS]


def test_two_g9_refusals_leave_the_turn_retryable(home, monkeypatch):
    def send(name, message):
        raise fleet.TransientSendRefusal("(G9)")

    monkeypatch.setattr(fleet, "_cmd_send_native", send)
    with pytest.raises(fleet.TransientSendRefusal):
        fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID,
                               run=_no_git, sleep=lambda s: None)
    assert "lane_done_notified" not in fleet.load_registry()["workers"]["lane"]


def test_send_raises_transient_refusal_on_a_suspicious_roster(home, monkeypatch):
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "boom"))
    with pytest.raises(fleet.TransientSendRefusal, match="G9"):
        fleet._cmd_send_native(PARENT, "hello")


# Backstop -- sup-guard sweep ----------------------------------------------

def _roster(status="idle"):
    return lambda: (True, [{"sessionId": LANE_SID, "status": status, "pid": 7},
                           {"sessionId": WOKEN_SID, "status": "idle", "pid": 8}])


def test_sweep_delivers_a_finish_the_hook_never_delivered(home, sends, monkeypatch):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    assert fleet.sweep_lane_done(_roster(), run=_no_git) == ["lane"]
    assert fleet.sweep_lane_done(_roster(), run=_no_git) == []
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def test_sweep_skips_running_foreign_and_archived_lanes(home, sends, monkeypatch):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    assert fleet.sweep_lane_done(_roster("busy"), run=_no_git) == []
    data = fleet.load_registry()
    other = fleet.new_worker_record("other-sid", str(home), "w", "bypass",
                                    spawned_by="sid-of-another-body")
    other["status"] = "idle"
    data["workers"]["other"] = other
    data["workers"]["lane"]["archived_at"] = _iso(datetime.now(timezone.utc))
    fleet.save_registry(data)
    assert fleet.sweep_lane_done(_roster(), run=_no_git) == []
    assert sends == []


def test_sweep_defers_on_a_failed_roster(home, sends, monkeypatch):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    assert fleet.sweep_lane_done(lambda: (False, "timeout"), run=_no_git) == []
    assert sends == []


def test_sup_guard_do_runs_the_sweep_and_reports_it(home, sends, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: _roster()())
    monkeypatch.setattr(fleet.subprocess, "run", _no_git)
    fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True),
                        snapshot_fn=lambda: {"ok": True, "workers": [],
                                             "supervisor": {"state": "held"}},
                        roster_fn=_roster())
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["lane_done_sent"] == ["lane"]
    assert sends[0] == (PARENT, "LANE-DONE lane idle none")


def test_sup_guard_preview_never_sweeps(home, sends, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    fleet.cmd_sup_guard(SimpleNamespace(do=False, json=True),
                        snapshot_fn=lambda: {"ok": True, "workers": [],
                                             "supervisor": {"state": "held"}},
                        roster_fn=_roster())
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["lane_done_sent"] == []
    assert sends == []


# sup-boot -- a refused bundle must not swallow the minted generation --------

def test_boot_bundle_refusal_still_delivers_the_nonce(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# Goals\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(fleet, "SUPERVISOR_BUNDLE_MAX_CHARS", 50)
    roster = json.dumps([{"sessionId": "sid-me", "status": "busy"}])
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=roster, stderr="")
    with pytest.raises(fleet.FleetCliError, match="exceeds"):
        fleet.cmd_sup_boot(SimpleNamespace(sid="sid-me", handoff_inc=None),
                           which=lambda n: "/fake/claude", run=run)
    out = capsys.readouterr().out
    claim = fleet.read_incarnation()
    nonce = next(line.split(": ", 1)[1] for line in out.splitlines()
                 if line.startswith("NONCE: "))
    assert fleet.nonce_digest(nonce) == claim["nonce_hash"]
    assert "VERDICT: claim" in out


# Y1 -- a seize or limit-transfer successor hears the seized claim's lanes ---

def _seized_lane(home, *, adopted):
    """The PX shape at 10:21Z 09-28: gen-19 seized fc6b; the lane was spawned
    by fc6b's body under fc6b's lineage, which no current row carries."""
    data = fleet.load_registry()
    data["workers"]["lane"].update({"spawned_by": "sid-of-the-seized-body",
                                    "spawned_by_lineage": "lin-seized"})
    fleet.save_registry(data)
    claim = fleet.read_incarnation()
    claim["claimed_via"] = "seize"
    if adopted is not None:
        claim["adopted_lineages"] = adopted
    fleet.write_incarnation(claim)


def test_seized_predecessor_lane_is_delivered_to_the_successor(home, sends):
    _seized_lane(home, adopted=["lin-seized"])
    assert fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def test_without_adoption_a_seized_lane_is_still_silent(home, sends):
    _seized_lane(home, adopted=None)
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == []


def test_adoption_does_not_reach_an_unrelated_lineage(home, sends):
    _seized_lane(home, adopted=["lin-some-other-generation", 7, None])
    assert not fleet.notify_lane_done("lane", "idle", expected_sid=LANE_SID, run=_no_git)
    assert sends == []


def test_stop_precheck_passes_for_an_adopted_lineage(home):
    _seized_lane(home, adopted=["lin-seized"])
    assert _load_hook()._lane_done_candidate(LANE_SID, str(home)) is True
    _seized_lane(home, adopted=["lin-other"])
    assert _load_hook()._lane_done_candidate(LANE_SID, str(home)) is False


def test_sweep_delivers_an_adopted_lane(home, sends, monkeypatch):
    monkeypatch.setattr(fleet, "has_fresh_outcome", lambda *a, **k: True)
    _seized_lane(home, adopted=["lin-seized"])
    assert fleet.sweep_lane_done(_roster(), run=_no_git) == ["lane"]
    assert sends == [(PARENT, "LANE-DONE lane idle none")]


def test_adoption_is_lane_done_only_never_mutation_ownership():
    """§6.2: the seizing body proves its OWN new lineage; the old body's
    workers stay foreign to kill/send-style guards."""
    rec = {"spawned_by": "sid-of-the-seized-body", "spawned_by_lineage": "lin-seized"}
    assert fleet._worker_is_foreign(rec, "sid-new", claim_lineage="lin-new")


def _sup_boot(tmp_path, monkeypatch, claim):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text("# Goals\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    fleet.write_incarnation(claim)
    roster = json.dumps([{"sessionId": "sid-me", "status": "busy"}])
    run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout=roster, stderr="")
    fleet.cmd_sup_boot(SimpleNamespace(sid="sid-me", handoff_inc=None),
                       which=lambda n: "/fake/claude", run=run)
    return fleet.read_incarnation()


def test_seize_adopts_the_seized_claims_lineage_chain(tmp_path, monkeypatch, capsys):
    stale = _iso(datetime.now(timezone.utc) - timedelta(hours=3))
    claim = _sup_boot(tmp_path, monkeypatch, {
        "incarnation_id": "inc-seized", "session_id": "sid-dead",
        "claimed_at": stale, "heartbeat_at": stale, "claimed_via": "seize",
        "lineage_id": "lin-seized", "adopted_lineages": ["lin-older", "lin-seized"]})
    assert "VERDICT: seize" in capsys.readouterr().out
    assert claim["claimed_via"] == "seize"
    assert claim["lineage_id"] not in ("lin-seized", "lin-older")   # re-minted (§6.2)
    assert claim["adopted_lineages"] == ["lin-seized", "lin-older"]


def test_seize_chain_is_bounded():
    pred = {"lineage_id": "lin-0",
            "adopted_lineages": [f"lin-{i}" for i in range(1, 40)]}
    chain = fleet._seize_adopted_lineages(pred)
    assert chain[0] == "lin-0" and len(chain) == fleet.ADOPTED_LINEAGES_MAX


def test_a_fresh_claim_after_release_adopts_nothing(tmp_path, monkeypatch, capsys):
    claim = _sup_boot(tmp_path, monkeypatch, {
        "incarnation_id": "inc-released", "lineage_id": "lin-released",
        "adopted_lineages": ["lin-older"], "state": "released",
        "released_at": _iso(datetime.now(timezone.utc))})
    assert "VERDICT: claim" in capsys.readouterr().out
    assert "adopted_lineages" not in claim


def test_handoff_carries_the_adopted_chain():
    new = {"lineage_id": "lin-kept"}
    fleet._carry_adopted_lineages({"lineage_id": "lin-kept",
                                   "adopted_lineages": ["lin-seized"]}, new)
    assert new["adopted_lineages"] == ["lin-seized"]
    empty = {}
    fleet._carry_adopted_lineages({"lineage_id": "lin-kept"}, empty)
    assert empty == {}
