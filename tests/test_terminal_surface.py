"""Phase 1.6 terminal surface (docs/specs/terminal-surface.md)."""
import argparse
import io
import json
import subprocess
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


@pytest.fixture
def statusline(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
    import fleet_statusline
    return fleet_statusline


class TestStatuslineRender:
    def test_not_initialized(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "not_initialized", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: not initialized"

    def test_unreadable_registry(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "unreadable", "workers": [], "totals": {}}, color=False)
        assert line == "⚑ fleet: registry unreadable"

    def test_no_workers(self, statusline):
        snap = {"ok": True, "reason": None, "workers": [],
                "totals": {"workers": 0, "mail": 0, "cost_usd": 0.0, "by_status": {}}}
        assert statusline.render_statusline(snap, color=False) == "⚑ fleet: no workers"

    def _snap(self, workers):
        by_status = {}
        for w in workers:
            by_status[w["status"]] = by_status.get(w["status"], 0) + 1
        return {"ok": True, "reason": None, "workers": workers,
                "totals": {"workers": len(workers),
                           "mail": sum(w["mail"] for w in workers),
                           "cost_usd": sum(w["cost_usd"] for w in workers),
                           "by_status": by_status}}

    def _w(self, **over):
        base = {"name": "w", "status": "working", "turns": 1, "cost_usd": 1.0,
                "mail": 0, "stale_seconds": 5.0, "limit_reset_at": None,
                "limit_kind": None, "resume_eligible": False, "attached_since": None}
        base.update(over)
        return base

    def test_counts_and_cost(self, statusline):
        snap = self._snap([
            self._w(name="a", status="working", cost_usd=1.02),
            self._w(name="b", status="idle", cost_usd=0.41),
            self._w(name="c", status="dead", cost_usd=0.71),
        ])
        line = statusline.render_statusline(snap, color=False)
        assert "1 working" in line.replace("●", " ").replace("○", " ").replace("✗", " ")
        assert "$2.14" in line

    def test_idle_with_mail_renders_as_idle_plus_mail(self, statusline):
        snap = self._snap([self._w(name="b", status="idle", mail=1)])
        assert "idle+mail" in statusline.render_statusline(snap, color=False)

    def test_limited_shows_reset_time(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2026-07-09T14:20:00Z")])
        assert "resets 14:20" in statusline.render_statusline(snap, color=False)

    def test_limited_without_reset_shows_unknown(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at=None)])
        assert "reset?" in statusline.render_statusline(snap, color=False)

    def test_limited_past_reset_flags_resume_eligible_only(self, statusline):
        snap = self._snap([self._w(status="limited", limit_reset_at="2020-01-01T00:00:00Z",
                                   resume_eligible=True)])
        line = statusline.render_statusline(snap, color=False)
        assert "resume-eligible" in line

    def test_stale_worker_gets_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "~40m" in statusline.render_statusline(snap, color=False)

    def test_fresh_worker_has_no_age_suffix(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=299.0)])
        assert "~" not in statusline.render_statusline(snap, color=False)

    def test_color_false_emits_no_escapes(self, statusline):
        snap = self._snap([self._w(status="working", stale_seconds=2400.0)])
        assert "\x1b" not in statusline.render_statusline(snap, color=False)

    def test_color_true_emits_escapes(self, statusline):
        snap = self._snap([self._w(status="working")])
        assert "\x1b" in statusline.render_statusline(snap, color=True)


class TestStatuslineMain:
    def test_main_exits_zero_and_prints_a_line(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO('{"model":{}}'))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0
        assert "⚑" in capsys.readouterr().out

    def test_main_swallows_every_exception_and_prints_nothing(self, statusline, capsys, monkeypatch):
        def boom():
            raise RuntimeError("registry exploded")
        monkeypatch.setattr(statusline.fleet, "status_snapshot", boom)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO(""))
        assert statusline.main() == 0
        assert capsys.readouterr().out == ""

    def test_main_tolerates_garbage_stdin(self, home, statusline, capsys, monkeypatch):
        _write_registry(home, {})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("not json at all"))
        monkeypatch.setenv("NO_COLOR", "1")
        assert statusline.main() == 0

    def test_main_spawns_no_subprocess(self, home, statusline, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("the statusline must spawn no subprocess")
        monkeypatch.setattr(subprocess, "Popen", boom)
        monkeypatch.setattr(subprocess, "run", boom)
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        _write_registry(home, {"pmbot": _rec()})
        assert statusline.main() == 0


class TestStatuslineAsciiFallback:
    """A Windows console is cp1252 and cannot encode the fleet glyphs. Printing
    them raises UnicodeEncodeError, the exit-0 guard swallows it, and the
    operator sees a permanently BLANK statusline. Caught live during Task 3."""

    def test_ascii_only_render_is_pure_ascii(self, statusline):
        snap = {"ok": True, "reason": None,
                "workers": [{"name": "a", "status": "working", "turns": 1, "cost_usd": 1.0,
                             "mail": 0, "stale_seconds": 5.0, "limit_reset_at": None,
                             "limit_kind": None, "resume_eligible": False,
                             "attached_since": None}],
                "totals": {"workers": 1, "mail": 0, "cost_usd": 1.0,
                           "by_status": {"working": 1}}}
        line = statusline.render_statusline(snap, color=False, ascii_only=True)
        line.encode("ascii")  # raises if any glyph slipped through
        assert "working" in line

    def test_ascii_only_degrades_the_error_lines_too(self, statusline):
        line = statusline.render_statusline(
            {"ok": False, "reason": "unreadable", "workers": [], "totals": {}},
            color=False, ascii_only=True)
        line.encode("ascii")
        assert "registry unreadable" in line

    def test_main_prints_ascii_when_stdout_cannot_encode_glyphs(
            self, home, statusline, monkeypatch, capsys):
        _write_registry(home, {"pmbot": _rec()})
        monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{}"))
        monkeypatch.setenv("NO_COLOR", "1")
        # Simulate a cp1252 console: no reconfigure(), encoding that rejects glyphs.
        monkeypatch.setattr(statusline, "_stdout_can_encode", lambda text: False)

        assert statusline.main() == 0
        out = capsys.readouterr().out
        assert out.strip()  # the bug was: silently empty
        out.encode("ascii")
        assert "working" in out

    def test_stdout_can_encode_rejects_cp1252(self, statusline, monkeypatch):
        class _Cp1252:
            encoding = "cp1252"
        monkeypatch.setattr(statusline.sys, "stdout", _Cp1252())
        assert statusline._stdout_can_encode("⚑ fleet") is False
        assert statusline._stdout_can_encode("# fleet") is True
