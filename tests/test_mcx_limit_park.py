"""mcx Codex lanes killed by a usage limit park `limited` with a horizon.

A failed mcx job whose newest failure event is a usage-limit error is a
recoverable park (spec 5.1.1), never `dead`. Any other failure stays `dead`.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import fleet
from test_codex_substrate import _job, _set_state, _spawn, codex_home  # noqa: F401

LIMIT_MESSAGE = ("You've hit your usage limit. Upgrade to Pro or try again at "
                 "Oct 27th, 2026 12:37 PM.")


def _events(worktree, mcx_id, *events):
    (_job(worktree, mcx_id) / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _failed(message):
    return {"type": "turn.failed", "error": {"message": message}}


class TestParse:
    def test_reset_is_read_as_local_time(self):
        out = fleet._mcx_parse_limit_reset(LIMIT_MESSAGE)
        want = datetime(2026, 10, 27, 12, 37).astimezone(timezone.utc)
        assert out == want.strftime("%Y-%m-%dT%H:%M:%SZ")

    @pytest.mark.parametrize("text", [
        "You've hit your usage limit.",
        "try again at Octember 27th, 2026 12:37 PM",
        "try again at Oct 32nd, 2026 12:37 PM",
        "try again at Oct 27th, 2026 13:37 PM",
    ])
    def test_unparseable_is_none(self, text):
        assert fleet._mcx_parse_limit_reset(text) is None


class TestProbe:
    def test_limit_failure_parks_limited_with_horizon(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        _events(worktree, rec["mcx_id"],
                {"type": "thread.started", "thread_id": "t"},
                _failed(LIMIT_MESSAGE))
        out = fleet.recompute_worker_codex("cx1", rec)
        assert out["status"] == "limited"
        assert out["limit_kind"] == "usage_limit"
        assert out["limit_reset_at"] == fleet._mcx_parse_limit_reset(
            LIMIT_MESSAGE)

    def test_unparseable_time_is_limited_without_horizon(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "error")
        _events(worktree, rec["mcx_id"],
                _failed("You've hit your usage limit. Try later."))
        out = fleet.recompute_worker_codex("cx1", rec)
        assert out["status"] == "limited"
        assert out["limit_reset_at"] is None

    def test_other_failure_stays_dead(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        _events(worktree, rec["mcx_id"], _failed("model refused the request"))
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "dead"

    def test_failed_without_events_stays_dead(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "dead"

    def test_stale_limit_before_newer_other_failure_is_dead(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        _events(worktree, rec["mcx_id"], _failed(LIMIT_MESSAGE),
                _failed("sandbox crashed"))
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "dead"

    def test_limited_row_is_sticky(self, codex_home):
        worktree, rec = _spawn(codex_home)
        rec["status"] = "limited"
        _set_state(worktree, rec["mcx_id"], "failed")
        assert fleet.recompute_worker_codex("cx1", rec)["status"] == "limited"


class TestResume:
    def _park(self, codex_home, reset):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        with fleet.fleet_lock():
            data = fleet.load_registry()
            row = data["workers"]["cx1"]
            row.update(status="limited", limit_reset_at=reset,
                       limit_kind="usage_limit")
            fleet.save_registry(data)
        return worktree, rec

    def _resume(self, **kw):
        args = SimpleNamespace(name="cx1", force_now=False, nonce=None, **kw)
        return fleet.cmd_resume_limited(args)

    def test_past_horizon_resumes_via_mcx_steer(self, codex_home, capsys):
        worktree, rec = self._park(codex_home, "2020-01-01T00:00:00Z")
        assert self._resume() == 0
        row = fleet.load_registry()["workers"]["cx1"]
        assert row["status"] == "working"
        assert row["limit_reset_at"] is None
        assert (_job(worktree, rec["mcx_id"]) / "state").read_text() == "running"
        assert "reset horizon has passed" in (
            _job(worktree, rec["mcx_id"]) / "prompt").read_text()
        assert "resumed" in capsys.readouterr().out

    def test_future_horizon_stays_parked(self, codex_home, capsys):
        worktree, rec = self._park(codex_home, "2999-01-01T00:00:00Z")
        assert self._resume() == 0
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "limited"
        assert "still before reset horizon" in capsys.readouterr().out

    def test_unknown_horizon_needs_force_now(self, codex_home, capsys):
        worktree, rec = self._park(codex_home, None)
        assert self._resume() == 0
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "limited"
        args = SimpleNamespace(name="cx1", force_now=True, nonce=None)
        assert fleet.cmd_resume_limited(args) == 0
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "working"

    def test_send_refuses_limited_and_points_at_resume(self, codex_home):
        self._park(codex_home, "2999-01-01T00:00:00Z")
        _events(codex_home / "lane", "00000001", _failed(LIMIT_MESSAGE))
        with pytest.raises(fleet.FleetCliError, match="resume-limited"):
            fleet.cmd_send(SimpleNamespace(
                name="cx1", message="hi", nonce=None, force_band=False))


class TestResumeClaim:
    """Concurrent resume-limited never double-steers one mcx lane (w342)."""

    _park = TestResume._park
    _resume = TestResume._resume

    def _count_steers(self, monkeypatch, during=None):
        real = fleet._mcx_run
        steers = []

        def wrapped(rec, args, **kw):
            if args and args[0] == "steer":
                steers.append(args)
                if during is not None and len(steers) == 1:
                    during()
            return real(rec, args, **kw)

        monkeypatch.setattr(fleet, "_mcx_run", wrapped)
        return steers

    def test_racing_resumer_cannot_double_steer(self, codex_home, monkeypatch):
        self._park(codex_home, "2020-01-01T00:00:00Z")
        second = []

        def race():
            second.append(fleet._resume_one_limited(
                "cx1", fleet.shutil.which, lambda s: None))

        steers = self._count_steers(monkeypatch, during=race)
        assert fleet._resume_one_limited(
            "cx1", fleet.shutil.which, lambda s: None) is True
        assert second == [False]
        assert len(steers) == 1
        row = fleet.load_registry()["workers"]["cx1"]
        assert row["status"] == "working"
        assert "limit_resume_claim" not in row
        assert row["limit_reset_at"] is None

    def test_failed_steer_restores_limited_and_drops_claim(
            self, codex_home, monkeypatch):
        self._park(codex_home, "2020-01-01T00:00:00Z")
        monkeypatch.setattr(fleet, "_mcx_run", lambda rec, args, **kw:
                            SimpleNamespace(returncode=1, stdout="", stderr="boom"))
        with pytest.raises(fleet.FleetCliError, match="stays limited"):
            self._resume()
        row = fleet.load_registry()["workers"]["cx1"]
        assert row["status"] == "limited"
        assert "limit_resume_claim" not in row

    def test_row_change_after_steer_reports_launch(
            self, codex_home, monkeypatch, capsys):
        self._park(codex_home, "2020-01-01T00:00:00Z")

        def change():
            with fleet.fleet_lock():
                data = fleet.load_registry()
                data["workers"]["cx1"]["status"] = "dead"
                data["workers"]["cx1"].pop("limit_resume_claim", None)
                fleet.save_registry(data)

        steers = self._count_steers(monkeypatch, during=change)
        assert self._resume() == 0
        assert len(steers) == 1
        out = capsys.readouterr().out
        assert "no longer limited" not in out
        assert "launched" in out
        assert fleet.load_registry()["workers"]["cx1"]["status"] == "dead"


class TestReprobeClaim:
    """A probing status between claim and steer keeps the claim (w343)."""

    _park = TestResume._park
    _count_steers = TestResumeClaim._count_steers

    def test_status_probe_between_claim_and_steer_cannot_double_steer(
            self, codex_home, monkeypatch):
        worktree, rec = self._park(codex_home, "2020-01-01T00:00:00Z")
        _events(worktree, rec["mcx_id"], _failed(LIMIT_MESSAGE))
        second, probed = [], []

        def probe_then_race():
            fleet.cmd_status(SimpleNamespace(
                name="cx1", all=False, stale_ok=False, json=False))
            probed.append(fleet.load_registry()["workers"]["cx1"]["status"])
            second.append(fleet._resume_one_limited(
                "cx1", fleet.shutil.which, lambda s: None))

        steers = self._count_steers(monkeypatch, during=probe_then_race)
        assert fleet._resume_one_limited(
            "cx1", fleet.shutil.which, lambda s: None) is True
        assert len(steers) == 1
        assert probed == ["working"] and second == [False]
        row = fleet.load_registry()["workers"]["cx1"]
        assert row["status"] == "working"
        assert "limit_resume_claim" not in row

    def test_expired_claim_reparks_and_drops_claim(self, codex_home):
        worktree, rec = _spawn(codex_home)
        _set_state(worktree, rec["mcx_id"], "failed")
        _events(worktree, rec["mcx_id"], _failed(LIMIT_MESSAGE))
        rec.update(status="working", limit_resume_claim="crashed",
                   last_activity="2020-01-01T00:00:00Z")
        out = fleet.recompute_worker_codex("cx1", rec)
        assert out["status"] == "limited"
        assert "limit_resume_claim" not in out
