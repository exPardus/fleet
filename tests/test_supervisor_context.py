"""three-tier-command.md §11.2 -- band measurement (`fleet sup-context`).

The supervisor (and, §11.4, a worker) self-monitors its context occupancy. The
only rotation-safe source is the running process's OWN CLAUDE_CODE_SESSION_ID
(G4): resolve the transcript by that sid, sum the THREE prompt summands
(input + cache_creation + cache_read, the B2-correct occupancy), compare to the
150k/200k band. Absent/stale/unparseable data FAILS TOWARD THE BAND -- never
"plenty of room" on missing data, for a ceiling nobody else enforces.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def ctx_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs"):
        (tmp_path / sub).mkdir()
    return tmp_path


def _transcript(tmp_path, usages):
    """usages: list of dicts merged into message.usage, one assistant rec each."""
    p = tmp_path / "t.jsonl"
    lines = [json.dumps({"type": "assistant", "message": {"usage": u}})
             for u in usages]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestOccupancy:
    def test_sums_the_three_prompt_summands(self, ctx_home, tmp_path):
        p = _transcript(tmp_path, [{"input_tokens": 10000,
                                    "cache_creation_input_tokens": 40000,
                                    "cache_read_input_tokens": 90000,
                                    "output_tokens": 500}])
        assert fleet._transcript_occupancy(p) == 140000

    def test_uses_the_last_assistant_record(self, ctx_home, tmp_path):
        p = _transcript(tmp_path, [
            {"input_tokens": 1, "cache_read_input_tokens": 2},
            {"input_tokens": 100000, "cache_creation_input_tokens": 100000},
        ])
        assert fleet._transcript_occupancy(p) == 200000

    def test_missing_summands_count_as_zero_when_at_least_one_present(
            self, ctx_home, tmp_path):
        p = _transcript(tmp_path, [{"input_tokens": 5000}])
        assert fleet._transcript_occupancy(p) == 5000

    def test_no_usage_returns_none(self, ctx_home, tmp_path):
        p = tmp_path / "t.jsonl"
        p.write_text(json.dumps({"type": "assistant", "message": {}}) + "\n",
                     encoding="utf-8")
        assert fleet._transcript_occupancy(p) is None

    def test_absent_transcript_returns_none(self, ctx_home, tmp_path):
        assert fleet._transcript_occupancy(tmp_path / "nope.jsonl") is None


class TestVerdict:
    def test_below_band_does_not_trigger_handoff(self):
        v = fleet.supervisor_band_verdict(120000)
        assert v["verdict"] == "below-band" and v["hand_off"] is False

    def test_in_band_triggers_handoff_at_boundary(self):
        v = fleet.supervisor_band_verdict(160000)
        assert v["verdict"] == "in-band" and v["hand_off"] is True

    def test_over_band_is_hard(self):
        v = fleet.supervisor_band_verdict(210000)
        assert v["verdict"] == "over-band" and v["hand_off"] is True

    def test_none_fails_toward_the_band(self):
        # The safe direction for a ceiling nobody else enforces: assume near-band
        # and hand off -- NEVER below-band on missing data.
        v = fleet.supervisor_band_verdict(None)
        assert v["verdict"] == "assume-near-band" and v["hand_off"] is True

    def test_boundaries_are_150k_and_200k(self):
        assert fleet.BAND_SOFT_TOKENS == 150000
        assert fleet.BAND_HARD_TOKENS == 200000
        assert fleet.supervisor_band_verdict(150000)["verdict"] == "in-band"
        assert fleet.supervisor_band_verdict(200000)["verdict"] == "over-band"


class TestCommand:
    def _run_json(self, monkeypatch, sid="sid-me", transcript=None):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, s: transcript)
        if sid is not None:
            monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        else:
            monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fleet.cmd_sup_context(SimpleNamespace(sid=None, json=True))
        return rc, json.loads(buf.getvalue())

    def test_reports_occupancy_and_below_band(self, ctx_home, tmp_path, monkeypatch):
        p = _transcript(tmp_path, [{"input_tokens": 100000,
                                    "cache_read_input_tokens": 20000}])
        rc, info = self._run_json(monkeypatch, transcript=p)
        assert rc == 0
        assert info["occupancy"] == 120000
        assert info["verdict"] == "below-band"
        assert info["soft_threshold"] == 150000
        assert info["hard_threshold"] == 200000

    def test_missing_transcript_assumes_near_band(self, ctx_home, monkeypatch):
        rc, info = self._run_json(monkeypatch, transcript=None)
        assert info["occupancy"] is None
        assert info["verdict"] == "assume-near-band"
        assert info["hand_off"] is True

    def test_no_session_id_assumes_near_band(self, ctx_home, monkeypatch):
        rc, info = self._run_json(monkeypatch, sid=None, transcript=None)
        assert info["verdict"] == "assume-near-band"

    def test_sid_override_resolves(self, ctx_home, tmp_path, monkeypatch):
        p = _transcript(tmp_path, [{"input_tokens": 190000}])
        seen = {}
        def fake_find(name, s):
            seen["sid"] = s
            return p
        monkeypatch.setattr(fleet, "find_transcript_path", fake_find)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fleet.cmd_sup_context(SimpleNamespace(sid="sid-explicit", json=True))
        info = json.loads(buf.getvalue())
        assert seen["sid"] == "sid-explicit"
        assert info["verdict"] == "in-band"
