"""three-tier-command.md §5.3 -- interface-caller provenance on `send` (B7).

The tier split moves the 2026-07-16 fork-divergence class UP to the (claimless)
interface tier: a fork-resumed interface body can re-derive and re-issue
`fleet send supervisor ...` steers, and `send` is not claim-gated. v1 mitigation
is DETECTION, never a refusal: stamp the caller's own CLAUDE_CODE_SESSION_ID onto
every `mail_sent` event, and have the supervisor SURFACE a divergence warning
when steers for its campaign arrive from two distinct interface sids in a window.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def _event(home, *, kind="mail_sent", name="supervisor", caller_sid=None, ts=None):
    rec = {"ts": ts or _iso(NOW), "kind": kind, "name": name}
    if caller_sid is not None:
        rec["caller_sid"] = caller_sid
    path = home / "state" / "events.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# --------------------------------------------------------------------------
# _interface_divergence -- the detector.
# --------------------------------------------------------------------------
class TestDetector:
    def test_two_distinct_callers_warns(self, home):
        _event(home, caller_sid="sid-A")
        _event(home, caller_sid="sid-B")
        div = fleet._interface_divergence(now=NOW)
        assert div is not None
        assert div["count"] == 2
        assert div["caller_sids"] == ["sid-A", "sid-B"]

    def test_single_caller_no_warning(self, home):
        _event(home, caller_sid="sid-A")
        _event(home, caller_sid="sid-A")
        assert fleet._interface_divergence(now=NOW) is None

    def test_successor_named_target_counts(self, home):
        # The manager runs as sup|<inc>|successor after a handoff; steers to it
        # are still steers to the supervisor.
        _event(home, name="sup|inc-3|successor", caller_sid="sid-A")
        _event(home, name="sup|inc-3|successor", caller_sid="sid-B")
        assert fleet._interface_divergence(now=NOW) is not None

    def test_non_supervisor_target_ignored(self, home):
        _event(home, name="w1", caller_sid="sid-A")
        _event(home, name="w2", caller_sid="sid-B")
        assert fleet._interface_divergence(now=NOW) is None

    def test_outside_window_ignored(self, home):
        _event(home, caller_sid="sid-A", ts=_iso(NOW - timedelta(days=2)))
        _event(home, caller_sid="sid-B")
        assert fleet._interface_divergence(now=NOW) is None

    def test_missing_caller_sid_ignored(self, home):
        # A human-shell send (no session id) and pre-§5.3 events carry no
        # caller_sid; they are not divergence signal.
        _event(home, caller_sid=None)
        _event(home, caller_sid="sid-A")
        assert fleet._interface_divergence(now=NOW) is None

    def test_non_mail_sent_events_ignored(self, home):
        _event(home, kind="steered", caller_sid="sid-A")
        _event(home, kind="turn_started", caller_sid="sid-B")
        assert fleet._interface_divergence(now=NOW) is None


# --------------------------------------------------------------------------
# sup-status surfaces the warning.
# --------------------------------------------------------------------------
class TestSupStatusSurface:
    def test_json_carries_divergence(self, home, capsys):
        _event(home, caller_sid="sid-A")
        _event(home, caller_sid="sid-B")
        fleet.cmd_sup_status(SimpleNamespace(json=True))
        info = json.loads(capsys.readouterr().out)
        assert info["interface_divergence"]["count"] == 2

    def test_human_line_warns(self, home, capsys):
        _event(home, caller_sid="sid-A")
        _event(home, caller_sid="sid-B")
        fleet.cmd_sup_status(SimpleNamespace(json=False))
        out = capsys.readouterr().out
        assert "interface divergence" in out and "§5.3" in out

    def test_no_divergence_no_warning(self, home, capsys):
        _event(home, caller_sid="sid-A")
        fleet.cmd_sup_status(SimpleNamespace(json=False))
        assert "interface divergence" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# Provenance is actually written onto mail_sent by the send engine.
# --------------------------------------------------------------------------
class TestProvenanceWritten:
    def test_idle_send_stamps_caller_sid(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-interface")
        rec = fleet.new_worker_record("s-old", str(home), "task", "accept",
                                      dispatch_kind="bg")
        rec["status"] = "idle"
        rec["last_activity"] = _iso(NOW - timedelta(hours=1))
        rec["last_dispatch_at"] = _iso(NOW - timedelta(hours=1))
        fleet.save_registry({"workers": {"w1": rec}})
        # A completed-turn outcome so recompute settles to idle (not in-flight).
        fleet.append_outcome("w1", {"ts": _iso(NOW - timedelta(hours=1)),
                                    "session_id": "s-old", "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **k: (True, []))

        def boom(*a, **k):
            raise fleet.NativeDispatchError("stop before real dispatch")
        monkeypatch.setattr(fleet, "dispatch_bg", boom)

        with pytest.raises(fleet.NativeDispatchError):
            fleet._cmd_send_native("w1", "wrap it up",
                                   run=lambda *a, **k: None, which=lambda _n: "claude")

        events = [json.loads(ln) for ln in
                  (home / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines() if ln]
        mail = [e for e in events if e.get("kind") == "mail_sent"]
        assert mail and mail[-1].get("caller_sid") == "sid-interface"
