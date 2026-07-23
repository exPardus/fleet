"""claim-nonce §7 -- THE GATE (option (b), ratified 2026-07-23).

A knowingly-bypassable claim gate on the mutating lifecycle verbs. It is the
slice's point and it carries the heaviest fault-injection table, because the
whole reason it exists is to make the 2026-07-16 dual-supervisor class produce
a refusal instead of ~100 silent minutes.

The honest accounting §7 read the decision against, made executable here:
  * armed ONLY while the heartbeat is fresh (<= SUPERVISOR_CLAIM_STALE_SECONDS);
  * `autoclean` (and any no-sid caller) is STRUCTURALLY exempt -- a caller
    with no CLAUDE_CODE_SESSION_ID cannot be the divergent supervisor body a
    fork produced;
  * it validates WITHOUT minting (§5.3) -- rotation is a supervisor ritual,
    not a side effect of dispatching a worker;
  * it is a speed-bump, not authorization: the bypass is documented in the
    refusal itself, not pretended away.
"""
import json
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def gate_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _fresh_claim(sid="sid-sup", lineage="lin-L", beat_age_seconds=5, **extra):
    beat = (datetime.now(timezone.utc)
            - timedelta(seconds=beat_age_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    value = fleet.mint_nonce()
    claim = {"incarnation_id": "inc-me", "session_id": sid,
             "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
             "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3, "lineage_id": lineage}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return value


class TestGateArming:
    """The arming matrix -- the meat, and where the injection table aims."""

    def test_a_caller_with_no_sid_is_never_gated(self, gate_home, monkeypatch):
        # autoclean's scheduled task and a human shell both land here.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _fresh_claim()
        fleet._supervisor_gate("spawn", nonce=None)  # returns, does not raise

    def test_no_held_claim_disarms_the_gate(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        fleet._supervisor_gate("spawn", nonce=None)

    def test_a_released_claim_disarms_the_gate(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        fleet.write_incarnation({"incarnation_id": "inc-old", "lineage_id": "lin-L",
                                 "claimed_via": "fresh", "released_at": fleet.now_iso(),
                                 "released_by_sid": "sid-x", "state": "released"})
        fleet._supervisor_gate("spawn", nonce=None)

    def test_a_malformed_released_claim_with_a_fresh_beat_still_disarms(
            self, gate_home, monkeypatch):
        # §6.3 strips `heartbeat_at` from a released claim, so on the happy path
        # the fail-open-on-missing-beat branch already disarms one. This pins
        # the released check's OWN weight: a released claim that anomalously
        # kept a fresh heartbeat (and a nonce_hash) must STILL be inert -- a
        # released claim has no holder, so there is no divergent-second-body
        # question to gate. Without the `state == "released"` conjunct this
        # would arm and refuse a caller presenting no generation.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        value = fleet.mint_nonce()
        fleet.write_incarnation({"incarnation_id": "inc-old", "lineage_id": "lin-L",
                                 "claimed_via": "fresh", "released_at": fleet.now_iso(),
                                 "released_by_sid": "sid-x", "state": "released",
                                 "heartbeat_at": fleet.now_iso(),
                                 "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 2})
        fleet._supervisor_gate("spawn", nonce=None)  # inert, does not raise

    def test_a_stale_heartbeat_disarms_the_gate(self, gate_home, monkeypatch):
        # §4.13(e): with no automatic beat, the gate is absent in exactly the
        # quiet stretches an unattended second body would exploit. That is a
        # DISCLOSED weakness, not a bug -- pin it so no one "fixes" it into a
        # gate that fires against a body that has already been seized from.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        _fresh_claim(beat_age_seconds=fleet.SUPERVISOR_CLAIM_STALE_SECONDS + 60)
        fleet._supervisor_gate("spawn", nonce=None)

    def test_a_legacy_claim_disarms_the_gate(self, gate_home, monkeypatch):
        # No generation to demand; §9's mixed-code shape must not brick a body.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        fleet.write_incarnation({"incarnation_id": "inc-old", "session_id": "sid-anyone",
                                 "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
                                 "claimed_via": "fresh"})
        fleet._supervisor_gate("spawn", nonce=None)

    def test_an_unreadable_heartbeat_disarms_the_gate_fail_open(self, gate_home, monkeypatch):
        # A speed-bump fails OPEN: an unreadable beat must not brick every
        # mutating verb. (A held claim with a corrupt heartbeat is a different
        # problem, reported by its own doctor row.)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        _fresh_claim()
        claim = fleet.read_incarnation()
        claim["heartbeat_at"] = "not-a-timestamp"
        fleet.write_incarnation(claim)
        fleet._supervisor_gate("spawn", nonce=None)

    def test_armed_and_proven_passes(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        value = _fresh_claim()
        fleet._supervisor_gate("spawn", nonce=value)  # continuity proved -> passes

    def test_armed_and_unproven_refuses(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("spawn", nonce=None)

    def test_armed_and_wrong_generation_refuses(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("spawn", nonce=fleet.mint_nonce())

    def test_a_pending_generation_also_proves(self, gate_home, monkeypatch):
        # §5.3 rule 2: the pending value is a valid presentation. The gate
        # validates without minting, so it must not itself acknowledge/rotate,
        # but it must ACCEPT a pending just as _require_claim_holder does.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        claim = fleet.read_incarnation()
        pending = fleet.mint_nonce()
        claim["pending_nonce_hash"] = fleet.nonce_digest(pending)
        claim["pending_at"] = fleet.now_iso()
        fleet.write_incarnation(claim)
        fleet._supervisor_gate("spawn", nonce=pending)


class TestGateValidatesWithoutMinting:
    def test_the_gate_never_writes_the_claim(self, gate_home, monkeypatch):
        # §5.3: gated verbs validate WITHOUT minting. Passing the gate must not
        # rotate the generation, mint a pending, or restamp the sid -- rotation
        # is a supervisor ritual, and the gate runs on `fleet send`, a hot path.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        value = _fresh_claim()
        before = fleet.read_incarnation()
        fleet._supervisor_gate("send", nonce=value)
        assert fleet.read_incarnation() == before

    def test_a_refusal_writes_nothing_either(self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        before = fleet.read_incarnation()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("kill", nonce=None)
        assert fleet.read_incarnation() == before


class TestGateBypassIsDocumented:
    def test_the_refusal_names_the_bypass_not_a_lever_over_the_other_body(
            self, gate_home, monkeypatch):
        # §2.1/§7: the gate cannot be authorization and does not pretend to be.
        # The refusal documents the bypass (present the generation, or run
        # without a session) -- it is a speed-bump, and saying otherwise would
        # mislead a future reader.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        with pytest.raises(fleet.SupervisorClaimGateError) as exc:
            fleet._supervisor_gate("spawn", nonce=None)
        msg = str(exc.value).lower()
        assert "--nonce" in msg
        assert "speed-bump" in msg or "not a security boundary" in msg or "bypass" in msg


class TestTheDualSupervisorClassIsRefused:
    """§7's binding requirement: gate present -> the 2026-07-16 dual-supervisor
    class is refused. The gate-ABSENT arm (the class reproduces) is the fault
    injection in tests/tmp -- here we prove the present arm."""

    def test_a_divergent_body_holding_a_retired_generation_is_refused(
            self, gate_home, monkeypatch):
        # Two bodies of one lineage both held generation G. The real body ran a
        # sup verb and advanced the live generation to G+1 (acknowledged a
        # pending). The divergent fork still presents G -- neither live nor
        # pending -> the gate refuses its next mutating verb. Without the gate
        # (option (a)), a `send`-only divergent body sails through, which is the
        # incident-1 shape as recorded.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-fork")
        retired = fleet.mint_nonce()               # generation G, now retired
        live = fleet.mint_nonce()                  # generation G+1, current
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": "sid-real",
                                 "claimed_at": beat, "heartbeat_at": beat, "claimed_via": "fresh",
                                 "nonce_hash": fleet.nonce_digest(live), "nonce_seq": 4,
                                 "lineage_id": "lin-L"})
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=retired)


class TestGateDoesNotLeakIntoViewPaths:
    """§7: the gate must NOT sit on a view or an authoritative-read path. A
    fresh armed claim plus a sid plus no generation must still let a view run
    -- otherwise the SessionStart hook of every session on this box would
    refuse while a supervisor is live."""

    def test_sup_status_is_not_gated(self, gate_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-other")
        _fresh_claim()
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0

    def test_status_stale_ok_is_not_gated(self, gate_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-other")
        _fresh_claim()
        args = SimpleNamespace(name=None, json=True, stale_ok=True, all=False)
        assert fleet.cmd_status(args) == 0


# --- exit code -------------------------------------------------------------

class TestGateExitCode:
    def test_the_gate_error_shares_the_continuity_exit_code(self, gate_home, monkeypatch):
        # A gate refusal is a failed continuity proof; it must be scriptable
        # against the same distinct code (§4.13(b)) rather than collapse to 1.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        rc = fleet.main(["spawn", "w", "--dir", str(gate_home), "--task", "go"])
        assert rc == fleet.SUPERVISOR_CONTINUITY_RC


# --- every mutating lifecycle verb is behind the gate ----------------------

GATED_VERBS = ["spawn", "send", "respawn", "kill", "clean", "interrupt",
               "archive", "resume-limited", "release", "init"]


class TestEveryMutatingVerbIsGated:
    """§7's taxonomy is binding. Each mutating lifecycle verb refuses under an
    armed gate with no generation; `autoclean` (the gate's own primary caller)
    is structurally exempt. Driven through `fleet.main` so the parser wiring
    (the `--nonce` argument) is exercised too."""

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_verb_is_refused_under_an_armed_gate(self, gate_home, monkeypatch, verb):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        # a name that does not exist is fine: the gate runs BEFORE the verb's
        # own work, so the gate refusal (exit 4) precedes any unknown-worker
        # error (exit 1). That ordering is the assertion.
        argv = {"spawn": ["spawn", "w", "--dir", str(gate_home), "--task", "go"],
                "send": ["send", "w", "hi"],
                "respawn": ["respawn", "w"],
                "kill": ["kill", "w"],
                "clean": ["clean"],
                "interrupt": ["interrupt", "w"],
                "archive": ["archive"],
                "resume-limited": ["resume-limited"],
                "release": ["release", "w"],
                "init": ["init"]}[verb]
        assert fleet.main(argv) == fleet.SUPERVISOR_CONTINUITY_RC

    def test_autoclean_is_structurally_exempt(self, gate_home, monkeypatch):
        # Even with a sid and a fresh claim and no generation, autoclean is not
        # gated (§7): it is the gate's own primary caller and the scheduler
        # ignores its exit code anyway (docs/specs/autoclean.md:38).
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        rc = fleet.main(["autoclean", "--fleet-home", str(gate_home)])
        assert rc != fleet.SUPERVISOR_CONTINUITY_RC
