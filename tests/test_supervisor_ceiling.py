"""three-tier-command.md §11.3 -- the 200k hard ceiling (B4).

At and above `BAND_HARD_TOKENS` the dispatch verbs (`fleet spawn`/`fleet send`)
REFUSE to start new worker turns -- but for EXACTLY ONE caller: the supervisor
claim-holder (ND1). The interface tier is exempt STRUCTURALLY (ND4c: no
`FLEET_WORKER` in its env), a caller that holds no claim is never subject, the
identity gate resolves through `retired_sids` (ND4a) so the un-restamped
fork-steer window does not fail open, and an unresolvable identity fails TOWARD
the band (ND4b). Occupancy is the caller's OWN transcript (B2/B3).
"""
import json
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def ceil_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs"):
        (tmp_path / sub).mkdir()
    # A clean env each test: no interface/worker stamp, no session leaking in.
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _write_incarnation(claim):
    fleet.write_incarnation(claim)


def _write_registry(workers):
    fleet.save_registry({"workers": workers})


def _held(session_id, **extra):
    """A held (non-released, non-legacy) claim owned by `session_id`."""
    c = {"incarnation_id": "inc-x", "session_id": session_id, "state": "active",
         "nonce_hash": "deadbeef", "nonce_seq": 3, "heartbeat_at": fleet.now_iso()}
    c.update(extra)
    return c


# --------------------------------------------------------------------------
# _caller_holds_supervisor_claim -- the shared identity concept (ND4a).
# --------------------------------------------------------------------------
class TestIdentity:
    def test_no_claim_is_not_holder(self, ceil_home):
        assert fleet._caller_holds_supervisor_claim("sid-a") is False

    def test_released_claim_is_not_holder(self, ceil_home):
        _write_incarnation({"incarnation_id": "inc-x", "state": "released",
                            "released_at": fleet.now_iso()})
        assert fleet._caller_holds_supervisor_claim("sid-a") is False

    def test_direct_holder_by_session_id(self, ceil_home):
        _write_incarnation(_held("sid-holder"))
        assert fleet._caller_holds_supervisor_claim("sid-holder") is True

    def test_claim_without_holder_sid_is_indeterminate(self, ceil_home):
        c = _held("sid-holder")
        del c["session_id"]
        _write_incarnation(c)
        assert fleet._caller_holds_supervisor_claim("sid-a") is None

    def test_unrestamped_fork_steer_window_resolves_through_retired_sids(self, ceil_home):
        # After a fork-steer: the body runs under NEW sid, the registry record was
        # eagerly restamped (session_id=new, retired_sids=[old]), but INCARNATION
        # still holds the OLD sid (pull-restamp lags, claim-nonce §5.10a). The
        # new caller must still resolve to the holder (ND4a) -- else the ceiling
        # fails open on the path every supervisor turn starts with.
        _write_incarnation(_held("sid-old"))
        _write_registry({"supervisor": {"session_id": "sid-new",
                                        "retired_sids": ["sid-old"]}})
        assert fleet._caller_holds_supervisor_claim("sid-new") is True

    def test_other_worker_is_not_the_holder(self, ceil_home):
        _write_incarnation(_held("sid-old"))
        _write_registry({"supervisor": {"session_id": "sid-new",
                                        "retired_sids": ["sid-old"]},
                         "w1": {"session_id": "sid-worker", "retired_sids": []}})
        assert fleet._caller_holds_supervisor_claim("sid-worker") is False

    def test_holder_sid_matching_no_record_is_indeterminate(self, ceil_home):
        # Claim points at a sid no live record carries (record archived/removed).
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"w1": {"session_id": "sid-worker", "retired_sids": []}})
        assert fleet._caller_holds_supervisor_claim("sid-someone") is None

    def test_empty_caller_is_indeterminate(self, ceil_home):
        _write_incarnation(_held("sid-holder"))
        assert fleet._caller_holds_supervisor_claim(None) is None


# --------------------------------------------------------------------------
# _ceiling_refuses_dispatch -- the refusal predicate itself.
# --------------------------------------------------------------------------
class TestCeiling:
    def _occ(self, monkeypatch, occupancy):
        monkeypatch.setattr(fleet, "find_transcript_path",
                            lambda name, sid: "/fake" if sid else None)
        monkeypatch.setattr(fleet, "_transcript_occupancy",
                            lambda p: occupancy)

    def _as_supervisor(self, monkeypatch, sid="sid-holder"):
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
        _write_incarnation(_held(sid))

    def test_interface_is_exempt_even_over_ceiling(self, ceil_home, monkeypatch):
        # No FLEET_WORKER => interface: NEVER refused, no matter the occupancy
        # (ND1/ND4c). Structural, ahead of any sid resolution.
        monkeypatch.delenv("FLEET_WORKER", raising=False)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        self._occ(monkeypatch, 500000)
        assert fleet._ceiling_refuses_dispatch("send") is None

    def test_supervisor_holder_over_ceiling_is_refused(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 205000)
        reason = fleet._ceiling_refuses_dispatch("spawn")
        assert reason is not None
        assert "spawn" in reason and "200,000" in reason and "11.3" in reason

    def test_supervisor_holder_at_exact_ceiling_is_refused(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, fleet.BAND_HARD_TOKENS)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_soft_band_does_not_refuse_dispatch(self, ceil_home, monkeypatch):
        # 150k <= occ < 200k is a standing directive, NOT a fleet refusal (§11.3).
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 175000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_below_band_does_not_refuse(self, ceil_home, monkeypatch):
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, 40000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_unreadable_occupancy_refuses_holder(self, ceil_home, monkeypatch):
        # §11.2: None fails TOWARD the band -- an unreadable transcript for the
        # claim-holder refuses, never "plenty of room".
        self._as_supervisor(monkeypatch)
        self._occ(monkeypatch, None)
        assert fleet._ceiling_refuses_dispatch("send") is not None

    def test_non_holder_worker_is_not_refused(self, ceil_home, monkeypatch):
        # A worker turn (FLEET_WORKER set) that is not the claim-holder holds no
        # claim -> never subject, even if its own transcript is huge.
        monkeypatch.setenv("FLEET_WORKER", "w1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-worker")
        _write_incarnation(_held("sid-holder"))
        _write_registry({"w1": {"session_id": "sid-worker", "retired_sids": []}})
        self._occ(monkeypatch, 400000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None

    def test_indeterminate_identity_fails_toward_band(self, ceil_home, monkeypatch):
        # FLEET_WORKER present (not interface), a claim is held, but identity is
        # unresolvable (holder sid in no record). ND4b: treat as the supervisor
        # and apply the ceiling.
        monkeypatch.setenv("FLEET_WORKER", "sup|inc-x|successor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-mystery")
        _write_incarnation(_held("sid-ghost"))
        _write_registry({"other": {"session_id": "sid-else", "retired_sids": []}})
        self._occ(monkeypatch, 300000)
        assert fleet._ceiling_refuses_dispatch("spawn") is not None

    def test_no_session_id_is_not_refused(self, ceil_home, monkeypatch):
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        self._occ(monkeypatch, 400000)
        assert fleet._ceiling_refuses_dispatch("spawn") is None


# --------------------------------------------------------------------------
# Wiring: the dispatch verbs actually consult the ceiling (B4 "fleet-enforced").
# --------------------------------------------------------------------------
class TestWiring:
    def test_cmd_spawn_refuses_over_ceiling(self, ceil_home, monkeypatch):
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 205000)
        args = SimpleNamespace(name="w1", dir=str(ceil_home), task="do it",
                               nonce=None, max_budget_usd=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_spawn(args)
        assert "11.3" in str(ei.value)

    def test_cmd_send_refuses_over_ceiling(self, ceil_home, monkeypatch):
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 205000)
        args = SimpleNamespace(name="w1", message="hi", nonce=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_send(args)
        assert "11.3" in str(ei.value)

    def test_cmd_spawn_below_ceiling_passes_the_gate(self, ceil_home, monkeypatch):
        # Below the ceiling the ceiling raises nothing; the verb proceeds to its
        # NEXT guard (_require_instance_settings), proving the ceiling did not
        # itself block. We assert the failure is NOT the ceiling.
        monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
        monkeypatch.setenv("FLEET_WORKER", "supervisor")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-holder")
        _write_incarnation(_held("sid-holder"))
        monkeypatch.setattr(fleet, "find_transcript_path", lambda name, sid: "/fake")
        monkeypatch.setattr(fleet, "_transcript_occupancy", lambda p: 40000)
        args = SimpleNamespace(name="w1", dir=str(ceil_home), task="do it",
                               nonce=None, max_budget_usd=None)
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_spawn(args)
        assert "11.3" not in str(ei.value)
