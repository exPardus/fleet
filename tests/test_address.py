"""`fleet address`: the exact native session name a SendMessage `to` needs.

No claude process runs: the roster fetch is injected. Every test points
fleet.FLEET_HOME at a pytest tmp_path.
"""
import json
import uuid
from pathlib import Path

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    return tmp_path


def _seed(name, sid=None, retired=()):
    sid = sid or str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, "/x", "task", "dontask", dispatch_kind="bg")
    rec["retired_sids"] = list(retired)
    fleet.save_registry({"workers": {name: rec}})
    return sid


def _roster(monkeypatch, entries, ok=True):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda which=None, run=None: (ok, entries))


def _args(*argv):
    return fleet.build_parser().parse_args(["address", *argv])


def _row(sid, name, status="idle", pid=4242):
    return {"sessionId": sid, "name": name, "status": status, "pid": pid}


def test_prints_the_full_native_name_of_the_registry_sid(monkeypatch, capsys):
    sid = _seed("w1")
    _roster(monkeypatch, [_row(sid, "fleet|w1|do the thing")])
    assert fleet.cmd_address(_args("w1")) == 0
    assert capsys.readouterr().out.strip() == "fleet|w1|do the thing"


def test_json_carries_sid_status_and_mode(monkeypatch, capsys):
    sid = _seed("w1")
    _roster(monkeypatch, [_row(sid, "fleet|w1|h", status="busy")])
    assert fleet.cmd_address(_args("w1", "--json")) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["to"] == "fleet|w1|h" and out["session_id"] == sid
    assert out["status"] == "busy" and out["mode"] == "dontask"
    assert out["live_retired_sids"] == []


def test_waiting_session_is_addressable_with_a_note(monkeypatch, capsys):
    sid = _seed("w1")
    _roster(monkeypatch, [dict(_row(sid, "fleet|w1|h", status="waiting"),
                               waitingFor="permission prompt")])
    assert fleet.cmd_address(_args("w1")) == 0
    assert "permission prompt" in capsys.readouterr().err


def test_a_session_without_a_process_is_refused(monkeypatch):
    sid = _seed("w1")
    _roster(monkeypatch, [_row(sid, "fleet|w1|h", status=None, pid=None)])
    with pytest.raises(fleet.FleetCliError, match="not live"):
        fleet.cmd_address(_args("w1"))


def test_a_live_retired_body_is_named_and_never_returned(monkeypatch, capsys):
    """Fork-steer leaves the pre-fork body alive under the old name. The
    registry sid is authoritative even when only the retired body is live."""
    old = str(uuid.uuid4())
    sid = _seed("w1", retired=[old])
    _roster(monkeypatch, [_row(old, "fleet|w1|first brief"),
                          _row(sid, "fleet|w1|steer", status=None, pid=None)])
    with pytest.raises(fleet.FleetCliError, match="not live"):
        fleet.cmd_address(_args("w1"))
    err = capsys.readouterr().err
    assert old in err and "do not message it" in err


def test_two_live_sessions_with_one_name_warn(monkeypatch, capsys):
    sid = _seed("w1")
    _roster(monkeypatch, [_row(sid, "fleet|w1|h"),
                          _row(str(uuid.uuid4()), "fleet|w1|h")])
    assert fleet.cmd_address(_args("w1")) == 0
    assert "[ref]" in capsys.readouterr().err


def test_roster_failure_is_a_refusal(monkeypatch):
    _seed("w1")
    _roster(monkeypatch, "boom", ok=False)
    with pytest.raises(fleet.FleetCliError, match="roster unavailable"):
        fleet.cmd_address(_args("w1"))


def test_unknown_worker_is_refused(monkeypatch):
    _seed("w1")
    _roster(monkeypatch, [])
    with pytest.raises(fleet.FleetCliError, match="unknown worker"):
        fleet.cmd_address(_args("nope"))


def test_address_is_an_ordinary_verb():
    assert fleet.verb_effect_tier("address") == "ordinary"


def test_rendered_settings_accept_cross_session_messages():
    """A dontAsk lane holds a bypass supervisor's message for a user who never
    comes (spike F2, docs/specs/peer-messaging.md). The template opts in."""
    repo = Path(__file__).resolve().parent.parent
    template = json.loads((repo / "worker-settings.template.json")
                          .read_text(encoding="utf-8"))
    assert template["crossSessionInbound"] == "accept"
