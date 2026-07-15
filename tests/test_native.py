"""M-B native-substrate tests: registry v2 fields, outcome store, dispatch
helper, discriminator, limit rehome, steering, stop/tombstones, archival."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with state/ and a rendered instance settings file."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="fleet|w1|task", state="working",
                      status="busy", pid=1234, kind="background"):
    """Roster entry per the contract field-presence table. Pass status=None /
    pid=None to model dead entries (keys OMITTED, not null)."""
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def seed_native_worker(home, name="w1", sid="aaaabbbb-1111-2222-3333-444455556666",
                       status="working", last_dispatch_at=None, **overrides):
    rec = fleet.new_worker_record(sid, "C:/proj", "do the thing", "accept",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = last_dispatch_at or _iso(NOW - timedelta(minutes=5))
    rec.update(overrides)
    data = {"workers": {name: rec}}
    fleet.save_registry(data)
    return rec


class TestRegistryV2:
    def test_new_record_native_fields_default_off(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept")
        assert rec["dispatch_kind"] is None
        assert rec["category"] is None
        assert rec["native_short_id"] is None
        assert rec["last_dispatch_at"] is None
        assert rec["retired_sids"] == []
        assert rec["archived_at"] is None

    def test_new_record_bg_kind(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept",
                                      dispatch_kind="bg", category="camp5")
        assert rec["dispatch_kind"] == "bg" and rec["category"] == "camp5"

    def test_is_native_and_legacy_refusal(self, native_home):
        native = {"dispatch_kind": "bg"}
        legacy = {"session_id": "old"}  # pre-pivot record: key absent entirely
        assert fleet.is_native(native) is True
        assert fleet.is_native(legacy) is False
        with pytest.raises(fleet.FleetCliError, match="pre-pivot"):
            fleet.refuse_if_legacy("w1", legacy, "send")
        fleet.refuse_if_legacy("w1", native, "send")  # no raise


class TestOutcomeStore:
    def test_append_and_read_roundtrip(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1",
                                    "kind": "result", "result_text": "done ✓"})
        recs = fleet.read_outcomes("w1")
        assert recs[0]["result_text"] == "done ✓"

    def test_read_merges_sid_fallback_file_and_skips_junk(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        fleet.append_outcome("s1", {"ts": _iso(NOW + timedelta(seconds=9)),
                                    "session_id": "s1", "kind": "result"})
        fleet.outcome_path("w1").open("a", encoding="utf-8").write("{not json\n")
        recs = fleet.read_outcomes("w1", sid="s1")
        assert len(recs) == 2
        assert recs[-1]["ts"] > recs[0]["ts"]  # sorted by ts

    def test_read_filters_by_sid(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-sid", "kind": "result"})
        assert fleet.read_outcomes("w1", sid="new-sid") == []

    def test_has_fresh_outcome_boundary_and_slack(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        # record 3s OLDER than since still counts (5s slack)
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=3)))
        assert not fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=30)))
        assert not fleet.has_fresh_outcome("w1", "other", _iso(NOW))

    def test_tombstone_shape(self, native_home):
        fleet.write_tombstone_outcome("w1", "s1", "interrupted")
        rec = fleet.read_outcomes("w1", sid="s1")[-1]
        assert rec["kind"] == "interrupted" and rec["result_text"] is None
        with pytest.raises(ValueError):
            fleet.write_tombstone_outcome("w1", "s1", "exploded")
