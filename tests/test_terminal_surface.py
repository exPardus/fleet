"""Phase 1.6 terminal surface (docs/specs/terminal-surface.md)."""
import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def _write_registry(home, workers):
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8"
    )


def _rec(**over):
    base = {
        "session_id": "sid-1", "cwd": "C:/proj", "task": "t", "mode": "dontask",
        "model": None, "max_budget_usd": None, "setting_sources": None,
        "created": "2026-07-09T12:00:00Z", "status": "working",
        "turn_pid": 123, "turn_pid_ctime": "2026-07-09T12:00:00Z",
        "attached_since": None, "limit_reset_at": None, "limit_kind": None,
        "turns": 3, "cost_baseline": 0.0, "cost_usd": 1.25,
        "last_activity": "2026-07-09T12:00:00Z",
    }
    base.update(over)
    return base


class TestStatusSnapshot:
    def test_missing_registry_reports_not_initialized(self, home):
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "not_initialized"
        assert snap["workers"] == []

    def test_corrupt_registry_reports_unreadable_and_does_not_quarantine(self, home):
        path = home / "state" / "fleet.json"
        path.write_text("{not json", encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"
        assert snap["workers"] == []
        # D4: the view reports; it never quarantines (that is a write).
        assert path.exists()
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []
        assert not (home / "state" / "events.jsonl").exists()

    def test_workers_not_an_object_reports_unreadable(self, home):
        (home / "state" / "fleet.json").write_text('{"workers": [1, 2]}', encoding="utf-8")
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "unreadable"

    def test_empty_registry_is_ok_with_zero_totals(self, home):
        _write_registry(home, {})
        snap = fleet.status_snapshot()
        assert snap["ok"] is True
        assert snap["reason"] is None
        assert snap["totals"]["workers"] == 0
        assert snap["totals"]["cost_usd"] == 0.0
        assert snap["totals"]["mail"] == 0

    def test_rows_carry_status_cost_turns_and_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("hi", encoding="utf-8")
        snap = fleet.status_snapshot()
        row = snap["workers"][0]
        assert row["name"] == "pmbot"
        assert row["status"] == "working"
        assert row["turns"] == 3
        assert row["cost_usd"] == 1.25
        assert row["mail"] == 1
        assert snap["totals"]["mail"] == 1
        assert snap["totals"]["cost_usd"] == 1.25

    def test_empty_mailbox_file_counts_as_no_mail(self, home):
        _write_registry(home, {"pmbot": _rec()})
        (home / "mailbox" / "sid-1.md").write_text("", encoding="utf-8")
        assert fleet.status_snapshot()["workers"][0]["mail"] == 0

    def test_totals_count_every_status_generically(self, home):
        # Shipped code has statuses beyond SPEC's five (over_budget,
        # over_ceiling); totals must not hardcode a fixed set.
        _write_registry(home, {
            "a": _rec(status="working", session_id="s-a"),
            "b": _rec(status="idle", session_id="s-b"),
            "c": _rec(status="over_ceiling", session_id="s-c"),
        })
        totals = fleet.status_snapshot()["totals"]
        assert totals["workers"] == 3
        assert totals["by_status"] == {"working": 1, "idle": 1, "over_ceiling": 1}

    def test_stale_seconds_derived_from_last_activity(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="2026-07-09T12:00:00Z")})
        snap = fleet.status_snapshot(now=fleet._parse_iso("2026-07-09T12:05:00Z"))
        assert snap["workers"][0]["stale_seconds"] == pytest.approx(300.0)

    def test_unparseable_last_activity_yields_none_stale_seconds(self, home):
        _write_registry(home, {"pmbot": _rec(last_activity="garbage")})
        assert fleet.status_snapshot()["workers"][0]["stale_seconds"] is None

    def test_missing_additive_fields_default(self, home):
        # Additive-schema rule (SPEC §4): an old record lacking cost_baseline /
        # limit_reset_at / limit_kind reads as 0.0 / None / None, never raises.
        old = {"session_id": "s-old", "status": "idle", "turns": 1,
               "last_activity": "2026-07-09T12:00:00Z"}
        _write_registry(home, {"legacy": old})
        row = fleet.status_snapshot()["workers"][0]
        assert row["cost_usd"] == 0.0
        assert row["limit_reset_at"] is None
        assert row["limit_kind"] is None
        assert row["resume_eligible"] is False

    def test_limited_past_reset_is_flagged_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2020-01-01T00:00:00Z", limit_kind="session_5h")})
        row = fleet.status_snapshot()["workers"][0]
        assert row["status"] == "limited"
        assert row["resume_eligible"] is True

    def test_limited_before_reset_is_not_resume_eligible(self, home):
        _write_registry(home, {"probe": _rec(
            status="limited", limit_reset_at="2099-01-01T00:00:00Z")})
        assert fleet.status_snapshot()["workers"][0]["resume_eligible"] is False

    def test_workers_sorted_by_name(self, home):
        _write_registry(home, {"zed": _rec(session_id="s-z"), "abe": _rec(session_id="s-a")})
        assert [w["name"] for w in fleet.status_snapshot()["workers"]] == ["abe", "zed"]


class TestStatusSnapshotIsPure:
    def test_never_probes(self, home, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("status_snapshot must never probe a PID")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()

    def test_never_takes_the_lock(self, home):
        _write_registry(home, {"pmbot": _rec()})
        fleet.status_snapshot()
        assert not (home / "state" / "fleet.lock").exists()

    def test_never_writes_the_registry(self, home):
        _write_registry(home, {"pmbot": _rec()})
        path = home / "state" / "fleet.json"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        fleet.status_snapshot()
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before


class TestStatusJsonFlags:
    def _args(self, **over):
        base = {"name": None, "json": False, "stale_ok": False}
        base.update(over)
        return argparse.Namespace(**base)

    def test_stale_ok_json_prints_snapshot_and_never_probes(self, home, capsys, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("--stale-ok must never probe")
        monkeypatch.setattr(fleet.PLATFORM, "get_process_info", boom)
        _write_registry(home, {"pmbot": _rec()})

        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))

        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["workers"][0]["name"] == "pmbot"
        assert not (home / "state" / "fleet.lock").exists()

    def test_stale_ok_on_corrupt_registry_exits_zero_and_reports(self, home, capsys):
        (home / "state" / "fleet.json").write_text("{bad", encoding="utf-8")
        rc = fleet.cmd_status(self._args(json=True, stale_ok=True))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["reason"] == "unreadable"
        assert list((home / "state").glob("fleet.json.corrupt.*")) == []

    def test_stale_ok_without_json_prints_the_table(self, home, capsys):
        _write_registry(home, {"pmbot": _rec()})
        rc = fleet.cmd_status(self._args(stale_ok=True))
        assert rc == 0
        assert "pmbot" in capsys.readouterr().out

    def test_parser_accepts_the_flags(self):
        args = fleet.build_parser().parse_args(["status", "--json", "--stale-ok"])
        assert args.json is True and args.stale_ok is True

    def test_parser_defaults_both_flags_off(self):
        args = fleet.build_parser().parse_args(["status"])
        assert args.json is False and args.stale_ok is False
