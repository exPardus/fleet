"""three-tier-command.md §11.2 -- band measurement (`fleet sup-context`).

The supervisor (and, §11.4, a worker) self-monitors its context occupancy. The
only rotation-safe source is the running process's OWN CLAUDE_CODE_SESSION_ID
(G4): resolve the transcript by that sid, sum the THREE prompt summands
(input + cache_creation + cache_read, the B2-correct occupancy), compare to
**that body's tier band**. Absent/stale/unparseable data FAILS TOWARD THE BAND
-- never "plenty of room" on missing data, for a ceiling nobody else enforces.

The two tiers had ONE band (150k/200k) until the 2026-08-05 operator ruling
raised them apart: supervisor 350-400k, worker 250-300k. So this file now pins
two things the old one could not ask: the numbers themselves, and which band a
given body is measured against.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

REPO = Path(__file__).resolve().parents[1]


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
    @pytest.mark.parametrize("tier", ["supervisor", "worker"])
    def test_below_band_does_not_trigger_handoff(self, tier):
        soft, _ = fleet.band_thresholds(tier)
        v = fleet.supervisor_band_verdict(soft - 1, tier)
        assert v["verdict"] == "below-band" and v["hand_off"] is False

    @pytest.mark.parametrize("tier", ["supervisor", "worker"])
    def test_in_band_triggers_handoff_at_boundary(self, tier):
        soft, hard = fleet.band_thresholds(tier)
        v = fleet.supervisor_band_verdict((soft + hard) // 2, tier)
        assert v["verdict"] == "in-band" and v["hand_off"] is True

    @pytest.mark.parametrize("tier", ["supervisor", "worker"])
    def test_over_band_is_hard(self, tier):
        _, hard = fleet.band_thresholds(tier)
        v = fleet.supervisor_band_verdict(hard + 5000, tier)
        assert v["verdict"] == "over-band" and v["hand_off"] is True

    @pytest.mark.parametrize("tier", ["supervisor", "worker"])
    def test_none_fails_toward_the_band(self, tier):
        # The safe direction for a ceiling nobody else enforces: assume near-band
        # and hand off -- NEVER below-band on missing data.
        v = fleet.supervisor_band_verdict(None, tier)
        assert v["verdict"] == "assume-near-band" and v["hand_off"] is True


class TestTheRaisedNumbers:
    """The 2026-08-05 operator ruling, pinned as NUMBERS rather than as "some
    band exists" -- `docs/OPERATOR-GATES.md` §Settled, `knowledge/lessons.md`
    #2026-08-05-ceilings-raised. A test that tolerates any number is not a pin,
    which is why every assertion here is a literal and none reads a constant to
    compare it against itself."""

    def test_the_supervisor_band_is_350k_to_400k(self):
        assert fleet.SUPERVISOR_BAND_SOFT_TOKENS == 350000
        assert fleet.SUPERVISOR_BAND_HARD_TOKENS == 400000
        assert fleet.band_thresholds("supervisor") == (350000, 400000)

    def test_the_worker_band_is_250k_to_300k(self):
        assert fleet.WORKER_BAND_SOFT_TOKENS == 250000
        assert fleet.WORKER_BAND_HARD_TOKENS == 300000
        assert fleet.band_thresholds("worker") == (250000, 300000)

    def test_band_entry_keeps_the_ratified_50k_margin(self):
        # The margin is the part the interface TRANSCRIBED rather than the
        # operator dictating it (gates entry: "if that margin misreads intent,
        # the 400k/300k hard numbers are the ruling"). Pinned so that if the
        # operator later restates the entry, exactly one test goes red and says
        # which half moved.
        assert (fleet.SUPERVISOR_BAND_HARD_TOKENS
                - fleet.SUPERVISOR_BAND_SOFT_TOKENS) == 50000
        assert (fleet.WORKER_BAND_HARD_TOKENS
                - fleet.WORKER_BAND_SOFT_TOKENS) == 50000

    def test_the_boundaries_are_inclusive_at_the_bottom_of_each_step(self):
        assert fleet.supervisor_band_verdict(350000, "supervisor")["verdict"] == "in-band"
        assert fleet.supervisor_band_verdict(400000, "supervisor")["verdict"] == "over-band"
        assert fleet.supervisor_band_verdict(250000, "worker")["verdict"] == "in-band"
        assert fleet.supervisor_band_verdict(300000, "worker")["verdict"] == "over-band"

    def test_the_worker_band_is_the_STRICTER_one_at_every_occupancy(self):
        # Load-bearing for `band_tier_for_sid`: an INDETERMINATE tier resolves
        # to "worker" because that is the fail-toward-the-band direction. That
        # is only true while the worker band sits at or below the supervisor's.
        assert fleet.WORKER_BAND_SOFT_TOKENS <= fleet.SUPERVISOR_BAND_SOFT_TOKENS
        assert fleet.WORKER_BAND_HARD_TOKENS <= fleet.SUPERVISOR_BAND_HARD_TOKENS

    def test_the_old_tier_agnostic_constants_are_GONE_not_aliased(self):
        # An alias would let a site keep asking the tier-free question and get
        # the supervisor's laxer number by accident. Absence makes a missed
        # site a NameError.
        assert not hasattr(fleet, "BAND_SOFT_TOKENS")
        assert not hasattr(fleet, "BAND_HARD_TOKENS")

    def test_the_tier_is_required_and_unknown_tiers_raise(self):
        with pytest.raises(TypeError):
            fleet.supervisor_band_verdict(100000)          # no tier at all
        with pytest.raises(ValueError):
            fleet.supervisor_band_verdict(100000, "interface")
        with pytest.raises(ValueError):
            fleet.band_thresholds(None)


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
        # No claim file in this home -> the caller is provably not the holder
        # -> the WORKER band, and the rendering says which band it used.
        assert info["tier"] == "worker"
        assert info["soft_threshold"] == 250000
        assert info["hard_threshold"] == 300000

    def test_missing_transcript_assumes_near_band(self, ctx_home, monkeypatch):
        rc, info = self._run_json(monkeypatch, transcript=None)
        assert info["occupancy"] is None
        assert info["verdict"] == "assume-near-band"
        assert info["hand_off"] is True

    def test_no_session_id_assumes_near_band(self, ctx_home, monkeypatch):
        rc, info = self._run_json(monkeypatch, sid=None, transcript=None)
        assert info["verdict"] == "assume-near-band"

    def test_sid_override_resolves(self, ctx_home, tmp_path, monkeypatch):
        p = _transcript(tmp_path, [{"input_tokens": 260000}])
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


def _held(session_id):
    return {"incarnation_id": "inc-x", "session_id": session_id,
            "state": "active", "nonce_hash": "deadbeef", "nonce_seq": 3,
            "heartbeat_at": fleet.now_iso()}


class TestTierResolution:
    """Which band a body is measured against, since the 2026-08-05 raise made
    the two differ. `sup-context` and `_ceiling_refuses_dispatch` READ the same
    tri-state (`_caller_holds_supervisor_claim`) — one identity concept, not two
    — so neither can be looking at evidence the other cannot see.

    What they do with `None` is NOT the same, and deliberately so: the ceiling
    applies ND4(b) and treats it as the supervisor; the measurement reports the
    worker band. Same read, different resolution, both in the strict direction.
    The last test in this class pins exactly that."""

    def test_the_claim_holder_is_measured_against_the_supervisor_band(
            self, ctx_home, monkeypatch):
        fleet.write_incarnation(_held("sid-holder"))
        assert fleet._caller_holds_supervisor_claim("sid-holder") is True
        assert fleet.band_tier_for_sid("sid-holder") == "supervisor"

    def test_a_body_that_is_provably_not_the_holder_gets_the_worker_band(
            self, ctx_home, monkeypatch):
        fleet.write_incarnation(_held("sid-holder"))
        fleet.save_registry({"workers": {
            "sup": {"session_id": "sid-holder", "retired_sids": []},
            "w1": {"session_id": "sid-worker", "retired_sids": []}}})
        assert fleet._caller_holds_supervisor_claim("sid-worker") is False
        assert fleet.band_tier_for_sid("sid-worker") == "worker"

    def test_an_INDETERMINATE_tier_fails_toward_the_band(
            self, ctx_home, monkeypatch):
        # A held claim whose holder sid is placed by no record, and a caller
        # placed by no record either: `_caller_holds_supervisor_claim` -> None.
        # §11.2's direction is the STRICT band, which is the worker's.
        fleet.write_incarnation(_held("sid-ghost"))
        fleet.save_registry({"workers": {
            "other": {"session_id": "sid-else", "retired_sids": []}}})
        assert fleet._caller_holds_supervisor_claim("sid-mystery") is None
        assert fleet.band_tier_for_sid("sid-mystery") == "worker"

    def test_no_sid_at_all_fails_toward_the_band(self, ctx_home):
        assert fleet._caller_holds_supervisor_claim(None) is None
        assert fleet.band_tier_for_sid(None) == "worker"

    def test_the_measurement_and_the_CEILING_diverge_on_indeterminate_by_design(
            self, ctx_home, monkeypatch):
        """Pinned because it is the one place the two consumers of the same
        tri-state answer differently, and an unpinned deliberate divergence is
        indistinguishable from a bug.

        ND4(b) makes the ceiling treat an indeterminate caller AS the supervisor
        (apply the 400k refusal); the measurement reports the 300k worker band.
        Both are the strict move for what they do."""
        fleet.write_incarnation(_held("sid-ghost"))
        fleet.save_registry({"workers": {
            "other": {"session_id": "sid-else", "retired_sids": []}}})
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, s: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 320000)

        # The measurement: worker band -> 320k is OVER it.
        assert fleet.band_tier_for_sid("sid-mystery") == "worker"
        assert fleet.supervisor_band_verdict(320000, "worker")["verdict"] == "over-band"
        # The ceiling: supervisor threshold -> 320k is UNDER it, so the dispatch
        # is permitted even though the advisory says hand off.
        assert fleet._ceiling_refuses_dispatch("spawn") is None
        # ...and it does fire once the SUPERVISOR threshold is crossed, which is
        # the control proving the assertion above is not vacuous.
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 405000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_the_command_reports_the_supervisor_band_for_the_holder(
            self, ctx_home, tmp_path, monkeypatch):
        fleet.write_incarnation(_held("sid-holder"))
        p = _transcript(tmp_path, [{"input_tokens": 360000}])
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, s: p)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fleet.cmd_sup_context(SimpleNamespace(sid=None, json=True))
        info = json.loads(buf.getvalue())
        assert info["tier"] == "supervisor"
        assert (info["soft_threshold"], info["hard_threshold"]) == (350000, 400000)
        # 360k is IN the supervisor band and OVER the worker band -- the one
        # occupancy that proves the tier actually selected the numbers.
        assert info["verdict"] == "in-band"
        assert fleet.supervisor_band_verdict(360000, "worker")["verdict"] == "over-band"

    def test_the_text_rendering_names_the_tier(
            self, ctx_home, tmp_path, monkeypatch):
        p = _transcript(tmp_path, [{"input_tokens": 10000}])
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, s: p)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-nobody")
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fleet.cmd_sup_context(SimpleNamespace(sid=None, json=False))
        out = buf.getvalue()
        assert "worker band 250,000-300,000" in out, out


class TestTheDoctrineSurfacesQuoteTheSHIPPEDBand:
    """The band numbers live in FOUR places a body actually reads: the two
    constants, the skill table an interface session opens, and the ritual doc a
    supervisor boots on. Before this class, **nothing pinned the last two** --
    the same shape as this repo's recorded recurrences, where a false sentence
    survives on a RUNNING surface because only the code was tested.

    The expected strings are DERIVED from the constants, so raising the band
    again cannot leave this test green against stale doctrine: it will name the
    file and the string it wanted.
    """

    SURFACES = ("skills/fleet/SKILL.md", "skills/fleet/supervisor.md")

    def _text(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    @staticmethod
    def _band_renderings(soft, hard):
        """How doctrine writes a band: `350–400k`, either dash."""
        lo, hi = soft // 1000, hard // 1000
        return (f"{lo}–{hi}k", f"{lo}-{hi}k")

    @pytest.mark.parametrize("rel", SURFACES)
    def test_the_surface_states_both_shipped_bands(self, rel):
        body = self._text(rel)
        for tier in ("supervisor", "worker"):
            wanted = self._band_renderings(*fleet.band_thresholds(tier))
            assert any(w in body for w in wanted), (
                f"{rel} does not state the {tier} band as any of {wanted}, "
                f"which shipped code enforces. A doctrine surface that quotes "
                f"a band nobody enforces is the defect class this test exists "
                f"for -- update the surface, do not relax the assertion.")

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_superseded_band_is_stated_as_current(self, rel):
        # The 2026-08-05 raise superseded "150-200k" as a BAND. The string may
        # legitimately survive inside a dated citation; it may not survive as
        # the band a reader is told to observe -- and this file has no dated
        # citations of it, so any occurrence is stale doctrine.
        body = self._text(rel)
        for dead in ("150\u2013200k", "150-200k"):
            assert dead not in body, (
                f"{rel} still states the superseded {dead} band as current "
                f"(operator ruling 2026-08-05 raised it).")

    def test_the_detector_can_see_a_stale_surface(self, tmp_path):
        # A doc-sync pin that cannot fail proves nothing. Seed the exact defect
        # (a surface reverted to the old band) and prove the assertions catch
        # both halves.
        stale = "Trigger band: enter at 150k, hard ceiling 200k (150\u2013200k)."
        for tier in ("supervisor", "worker"):
            wanted = self._band_renderings(*fleet.band_thresholds(tier))
            assert not any(w in stale for w in wanted)   # "states both bands" fires
        assert "150\u2013200k" in stale                  # "no superseded band" fires
