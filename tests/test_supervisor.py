"""M-A supervisor identity tests (spec §4): state files, journal format,
claim/seizure/handshake state machine, boot ritual, handoff, nag."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with an active GOALS.md and seeded journal."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state").mkdir()
    return tmp_path


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class TestStateFiles:
    def test_incarnation_roundtrip_atomic(self, sup_home):
        claim = {"incarnation_id": "inc-20260714T110000Z-abcd", "session_id": "sid-1",
                 "claimed_at": _iso(NOW), "heartbeat_at": _iso(NOW), "claimed_via": "fresh"}
        fleet.write_incarnation(claim)
        assert fleet.read_incarnation() == claim
        # atomic: no .tmp litter left behind
        assert not list((sup_home / "supervisor").glob("*.tmp"))

    def test_read_incarnation_missing_and_corrupt(self, sup_home):
        assert fleet.read_incarnation() is None
        fleet.incarnation_path().write_text("{not json", encoding="utf-8")
        assert fleet.read_incarnation() is None

    def test_handshake_roundtrip(self, sup_home):
        fleet.write_handshake("inc-x", "sid-9")
        hs = fleet.read_handshake()
        assert hs["incarnation_id"] == "inc-x" and hs["session_id"] == "sid-9"
        assert "written_at" in hs

    def test_mint_incarnation_id_format_and_uniqueness(self, sup_home):
        a, b = fleet.mint_incarnation_id(), fleet.mint_incarnation_id()
        assert a.startswith("inc-") and a != b
        import re
        assert re.fullmatch(r"inc-\d{8}T\d{6}Z-[0-9a-f]{4}", a)


class TestJournal:
    def test_append_creates_seed_and_parses_back(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "fresh claim")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "line one\nline two")
        text = fleet.supervisor_journal_path().read_text(encoding="utf-8")
        assert text.startswith("# Supervisor Journal")
        entries = fleet.supervisor_journal_entries()
        assert [e["kind"] for e in entries] == ["BOOT", "CHECKPOINT"]
        assert entries[1]["body"].strip() == "line one\nline two"
        assert entries[1]["inc"] == "inc-a" and entries[1]["sid"] == "sid-1"
        latest = fleet.supervisor_journal_latest()
        assert latest["kind"] == "CHECKPOINT"

    def test_append_rejects_unknown_kind(self, sup_home):
        with pytest.raises(ValueError):
            fleet.supervisor_journal_append("SABOTAGE", "inc-a", "sid-1", "x")

    def test_parser_tolerates_prose_between_entries(self, sup_home):
        fleet.supervisor_journal_append("BOOT", "inc-a", "sid-1", "ok")
        with open(fleet.supervisor_journal_path(), "a", encoding="utf-8") as f:
            f.write("\nstray human note, not an entry header\n")
        fleet.supervisor_journal_append("CHECKPOINT", "inc-a", "sid-1", "next")
        assert [e["kind"] for e in fleet.supervisor_journal_entries()] == ["BOOT", "CHECKPOINT"]

    def test_empty_journal(self, sup_home):
        assert fleet.supervisor_journal_entries() == []
        assert fleet.supervisor_journal_latest() is None
