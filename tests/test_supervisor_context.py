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
import re
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

    # THE SEPARATE-TOKEN HOLE, and the numbers that close it.
    #
    # `test_no_superseded_band_is_stated_as_current` below forbids the JOINED
    # renderings and nothing else, so w45-gceil §3's mutant D reverted BOTH of
    # `supervisor.md`'s trigger sentences to the old ceiling while writing zero
    # joined tokens -- `**150k**`, `**200k**`, `at 150k`, `At 200k`. The
    # required renderings still appeared elsewhere in the file, so the sibling
    # assertion stayed green too. Measured: 36 passed in this file, and 493
    # passed across every test in the tree that reads `supervisor.md`. A
    # booting supervisor was told its hard ceiling was 200k and the whole suite
    # said nothing.
    #
    # A SUPERSEDED band is a historical fact; no constant in `bin/fleet.py`
    # remembers one, so the history is transcribed here and re-pinning it is a
    # deliberate edit. What is NOT transcribed is which of them are dead --
    # `_dead_edges` subtracts the CURRENTLY SHIPPED edges, because `300k` is
    # half of the 2026-07-14 band AND the live worker ceiling, so a list that
    # did not subtract would forbid a number shipped code enforces. That
    # subtraction is also what makes the next raise safe: whatever the operator
    # raises the band to leaves this list automatically.
    SUPERSEDED_BAND_EDGES_K = (150, 200,    # ratified 2026-07-23, raised 2026-08-05
                               300, 500)    # ratified 2026-07-14, superseded 2026-07-23

    # A dated citation may state a dead number; a live instruction may not.
    _DATED = re.compile(r"\d{4}-\d{2}-\d{2}")

    def _text(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    @staticmethod
    def _band_renderings(soft, hard):
        """How doctrine writes a band: `350–400k`, either dash."""
        lo, hi = soft // 1000, hard // 1000
        return (f"{lo}–{hi}k", f"{lo}-{hi}k")

    @classmethod
    def _dead_edges(cls):
        """Superseded band edges that are not ALSO a shipped one."""
        live = set()
        for tier in ("supervisor", "worker"):
            live.update(t // 1000 for t in fleet.band_thresholds(tier))
        return tuple(sorted(set(cls.SUPERSEDED_BAND_EDGES_K) - live))

    @classmethod
    def _stale_edge_hits(cls, body):
        """`(line number, line)` per line stating a dead band edge UNDATED.

        LINE-scoped, and that is the load-bearing choice rather than an
        implementation detail. `supervisor.md`'s trigger paragraph OPENS with a
        dated citation of the 2026-07-14 band (`supersedes the 2026-07-14
        300–500k band`) and mutant D's revert lands one and two lines below it,
        inside the same paragraph -- so a paragraph-scoped carve-out would wave
        the mutant through on its neighbour's date. Stated plainly: a revert
        that also writes a date onto its own line still escapes this, and that
        is a deliberate act rather than the drift this catches.
        """
        dead = cls._dead_edges()
        if not dead:
            return []
        alt = "|".join(str(k) for k in dead)
        # `(?<![\d,])` keeps `2,150,000` from reading as a `150,000`.
        edge = re.compile(rf"(?<![\d,])(?:{alt})(?:k\b|,000(?![\d,]))")
        return [(i, ln) for i, ln in enumerate(body.splitlines(), start=1)
                if edge.search(ln) and not cls._DATED.search(ln)]

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

    @pytest.mark.parametrize("rel", SURFACES)
    def test_no_superseded_band_EDGE_is_stated_undated(self, rel):
        """The assertion above, but on the spelling the surfaces actually use.

        These files write the trigger numbers as SEPARATE bold tokens
        (`**350k**` / `**400k**`), not as a joined band, so the joined-token
        assertion never looked at the sentence a supervisor actually reads.
        """
        hits = self._stale_edge_hits(self._text(rel))
        assert not hits, (
            f"{rel} states superseded band edge(s) {self._dead_edges()} on "
            f"undated line(s) {[n for n, _ in hits]}: "
            + " | ".join(ln.strip() for _, ln in hits)
            + f" -- the 2026-08-05 ruling raised the band; a live instruction "
              f"may not quote a dead edge. If the line is history, date it.")

    def test_the_dead_edge_set_SUBTRACTS_the_shipped_ones(self):
        """The derivation, pinned, because getting it wrong fails both ways.

        Forget to subtract and `300k` -- the live worker ceiling, printed by
        `sup-context` and quoted by both surfaces -- becomes forbidden and the
        pin above goes red on correct doctrine. Subtract too much and the pin
        forbids nothing.
        """
        dead = self._dead_edges()
        assert 150 in dead and 200 in dead, (
            f"the edges mutant D reverted to are not in the dead set: {dead}")
        assert 300 not in dead, (
            "300k is the shipped worker hard ceiling -- forbidding it would "
            "redden correct doctrine")
        for tier in ("supervisor", "worker"):
            for shipped in fleet.band_thresholds(tier):
                assert shipped // 1000 not in dead

    def test_the_edge_detector_sees_mutant_D_and_keeps_the_dated_carve_out(self):
        """MUTANT D, re-planted VERBATIM from `w45-gceil` §3's own quoted text.

        Verbatim includes its line 5, which the gate left at `350k` while
        reverting its line 6 -- a partial revert, and therefore the harder of
        the two to catch. The fuller revert is checked after it.
        """
        planted = (
            "BEGIN handoff at **150k** tokens of context occupancy; **200k** is the hard\n"
            "ceiling. Workers observe a band too, but **not the same one** — theirs is\n"
            "250–300k (§11.4). Never ride to the compaction wall.\n"
            "\n"
            "Swap-trigger rule (three-tier §11.3): at 350k the hand-off directive is\n"
            "standing — finish the current wave, then hand off. At 200k the only\n"
            "permitted work is finishing work already dispatched ...\n")

        # What the OLD assertion sees: nothing. This is the gap, executable.
        for dead in ("150–200k", "150-200k"):
            assert dead not in planted, (
                "mutant D writes zero joined tokens -- if this fires, the "
                "re-plant has drifted from the one that survived 493 tests")

        assert [n for n, _ in self._stale_edge_hits(planted)] == [1, 6], (
            "the edge detector must name every reverted line and only those: "
            "line 3's `250–300k` is the SHIPPED worker band and must stay "
            "green, and so must line 5, which the gate did not revert")

        # The fuller revert the gate's prose describes (both trigger sentences).
        fuller = planted.replace("at 350k the hand-off", "at 150k the hand-off")
        assert [n for n, _ in self._stale_edge_hits(fuller)] == [1, 5, 6]

        # The carve-out is real, and it is line-scoped rather than paragraph-
        # scoped -- the same text with and without a date on its own line.
        assert not self._stale_edge_hits(
            "supersedes the 2026-07-14 300–500k band")
        assert self._stale_edge_hits("supersedes the 300–500k band")

    def test_the_detector_can_see_a_stale_surface(self, tmp_path):
        # A doc-sync pin that cannot fail proves nothing. Seed the exact defect
        # (a surface reverted to the old band) and prove the assertions catch
        # both halves.
        stale = "Trigger band: enter at 150k, hard ceiling 200k (150\u2013200k)."
        for tier in ("supervisor", "worker"):
            wanted = self._band_renderings(*fleet.band_thresholds(tier))
            assert not any(w in stale for w in wanted)   # "states both bands" fires
        assert "150\u2013200k" in stale                  # "no superseded band" fires


class TestTheDoctorRowsQuoteTheSHIPPEDCeiling:
    """`fleet doctor`'s identity-witness rows tell an operator which ceiling a
    stamp-less body escapes, and both build that number by interpolating
    `SUPERVISOR_BAND_HARD_TOKENS`. Nothing pinned that they keep doing it.

    w45-gceil \u00a76's mutant F hardcoded both rows back to `"200,000-token"` and
    **166 tests stayed green** across `test_identity_registry`,
    `test_supervisor_context`, `test_supervisor_ceiling`, `test_doc_claims` and
    `test_doctor_claim_provenance`. Measured by grep in the same gate: the
    whole test tree carried exactly two `400,000` assertions and BOTH read the
    dispatch-REFUSAL message, never either doctor row. The one existing
    assertion that comes close (`test_identity_registry.py`'s
    ``assert "200k" in msg or "ceiling" in msg``) is satisfied by the second
    disjunct and so is blind to the number in both directions.

    HOMED HERE, not in `test_identity_registry.py`, because what is checked is
    not identity logic: it is the class above, one surface further out. A row
    an operator reads quotes a ceiling, and the ceiling it quotes has to be the
    one shipped code enforces. Expected renderings are derived from the
    constant for the same reason as the class above -- a future raise must not
    leave this green against a stale string.
    """

    # Every ceiling rendering in a row, however it got there. `[\d,]+-token`
    # matches the interpolation's own output and equally matches a hardcode,
    # which is what makes the comparison two-directional: a row carrying a
    # number that is not the constant's is RED whether it lost the
    # interpolation or gained a second one.
    _RENDERED = re.compile(r"[\d,]+-token")

    @staticmethod
    def _expected():
        return f"{fleet.SUPERVISOR_BAND_HARD_TOKENS:,}-token"

    @classmethod
    def _renderings(cls, text):
        return set(cls._RENDERED.findall(text))

    @staticmethod
    def _workers():
        return {"w1": {"session_id": "sid-w1", "retired_sids": [],
                       "status": "idle", "archived_at": None}}

    def _row(self, monkeypatch, *, sid, stamp):
        if stamp is None:
            monkeypatch.delenv("FLEET_WORKER", raising=False)
        else:
            monkeypatch.setenv("FLEET_WORKER", stamp)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        return fleet._doctor_check_identity_witness(self._workers())

    def test_the_RESOLVED_no_witness_row_quotes_the_shipped_ceiling(
            self, ctx_home, monkeypatch):
        """The FAIL row: the registry names this body, its stamp is gone, and
        the row's whole justification for being red is the ceiling that body is
        exempt from. Quoting the wrong number there is worse than silence."""
        _name, ok, msg = self._row(monkeypatch, sid="sid-w1", stamp=None)
        assert ok is False
        assert self._renderings(msg) == {self._expected()}, msg

    def test_the_UNRESOLVED_witness_row_quotes_the_shipped_ceiling(
            self, ctx_home, monkeypatch):
        """The NOTE row, which appends `DAEMON_ENV_LEAK_REMEDY` -- the second
        of the two interpolating sites, and the one reached by the common
        case."""
        _name, _ok, msg = self._row(monkeypatch, sid="sid-nobody", stamp="ghost")
        assert fleet.DAEMON_ENV_LEAK_REMEDY in msg
        assert self._renderings(msg) == {self._expected()}, msg

    def test_no_source_site_HARDCODES_a_token_ceiling(self):
        """THE MECHANISM, checked where mutant F was planted.

        The pair above pins the VALUE and would catch a raise that left a row
        behind. This pins the SHAPE: a thousands-separated literal spelled
        `NNN,NNN-token` anywhere in `bin/fleet.py` is a number that stopped
        tracking its constant, whether or not it happens to be right today.
        Measured at 238a4778: zero literals, three interpolations (the refusal
        message plus the two doctor rows).
        """
        # Read through `fleet.__file__` rather than off a repo-relative path,
        # so the file linted is provably the module the assertions above
        # rendered their rows from.
        src = Path(fleet.__file__).read_text(encoding="utf-8")
        hardcoded = [(i, ln.strip())
                     for i, ln in enumerate(src.splitlines(), start=1)
                     if re.search(r"(?<![\d,])\d{1,3},\d{3}-token", ln)]
        assert not hardcoded, (
            f"`bin/fleet.py` spells a token ceiling as a literal at "
            f"{[i for i, _ in hardcoded]}: {[t for _, t in hardcoded]} -- "
            f"interpolate the constant instead, or the next raise ships a "
            f"surface quoting a ceiling nothing enforces (w45-gceil \u00a76)")
        interpolated = re.findall(r"\{SUPERVISOR_BAND_HARD_TOKENS:,\}-token", src)
        assert len(interpolated) >= 2, (
            f"only {len(interpolated)} interpolated token ceiling(s) in "
            f"`bin/fleet.py` -- the two `fleet doctor` rows alone were two, so "
            f"the assertion above may now be passing over nothing")

    def test_the_detector_can_see_a_row_hardcoded_back_to_the_old_ceiling(
            self, ctx_home, monkeypatch):
        """MUTANT F, applied to the rendered row instead of to `bin/fleet.py`.

        A row-content pin that cannot fail proves nothing, and this is the
        exact substitution the gate made: `400,000-token` -> `200,000-token`,
        which 166 tests could not see.
        """
        _name, _ok, msg = self._row(monkeypatch, sid="sid-w1", stamp=None)
        assert self._expected() in msg
        mutated = msg.replace(self._expected(), "200,000-token")
        assert self._renderings(mutated) == {"200,000-token"}
        assert self._renderings(mutated) != {self._expected()}
