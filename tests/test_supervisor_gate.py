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
import re
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


@pytest.fixture(autouse=True)
def _never_dispatch(monkeypatch):
    """MAJ-4: NOTHING in this file may reach the dispatcher, and the guard is
    applied to the CLASS rather than to the tests that happened to be caught.

    Every test here drives a mutating verb expecting the gate to refuse it. The
    armed gate is therefore the ONLY thing between `fleet.main(["spawn", ...])`
    and a real, billable `claude` session -- which is precisely the assumption
    the whole slice exists to distrust. It was already wrong once: the break
    lens found 18 `state: blocked` sessions in `claude agents --json --all`,
    from nine prior runs of the two `spawn`-driving tests below, launched into
    pytest tmp dirs because the fix for the first incident was applied to one
    test instead of to every test that could produce it.

    A test that legitimately needs a dispatcher stubs its own after this one."""
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
        "a gate test reached dispatch_bg -- that dispatches a REAL claude session"))


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

    def test_a_CLEANLY_released_claim_disarms_the_gate(self, gate_home, monkeypatch):
        # NARROWED 2026-07-26 (§R3, councilor 4): "released" alone no longer
        # disarms. A released claim whose releaser is still roster-LIVE is the
        # wedged state and it ARMS -- see tests/test_gate_arm_wedge.py. What
        # disarms is release+stop having COMPLETED, which is this test.
        # The roster is stubbed rather than left live: without the stub this
        # passes only because the developer's own roster happens not to list
        # `sid-x`, which is a test outcome that depends on who ran it.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
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
        #
        # Still true after the §R3 narrowing, and now carrying MORE weight: the
        # released branch runs first and answers for this claim entirely, so an
        # anomalous fresh beat and an anomalous nonce_hash are both ignored --
        # a released claim is decided by its releaser's roster state alone.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-anyone")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
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


class TestTheSendCarveOutNeverQuarantinesTheRegistry:
    """The §7.1 `send` carve-out reads the registry, and that read must not be
    `load_registry`.

    `load_registry` QUARANTINES a corrupt registry -- it RENAMES the file aside
    (`bin/fleet.py:812`), which is a write, and this gate documents itself
    "READ-ONLY: no lock, no mint, no write". Shipped code called it here, so
    `fleet send` on a corrupt registry destroyed the operator's evidence from
    the one path that promises to touch nothing.

    WHY IT SURVIVED A PIN THAT LOOKS LIKE IT COVERS IT.
    `tests/test_b6_sid_union.py::test_the_gate_never_quarantines_a_corrupt_
    registry` asserts exactly this property and is CORRECT -- but it drives a
    RELEASED claim, and a released claim returns or raises inside
    `_wedged_release_gate` several branches earlier. The carve-out's read sits
    behind `if verb == "send" and send_target is not None`, reachable ONLY on a
    claim that is HELD and FRESH. So the two registry reads in this function
    are not one property with one pin: the wedged arm was pinned, the carve-out
    was never reachable from that fixture, and the gap is invisible unless you
    ask which STATE each arm needs rather than which verb. Injection-checked in
    both directions: swap this back to `load_registry` and this class fails
    while that one stays green."""

    def _corrupt_registry(self):
        fleet.registry_path().write_text("{ not json", encoding="utf-8")

    def test_a_corrupt_registry_survives_the_send_carve_out(
            self, gate_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-other-body")
        _fresh_claim()
        self._corrupt_registry()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None, send_target="some-worker")
        assert fleet.registry_path().exists(), \
            "the send carve-out quarantined the registry"
        assert not list(fleet.registry_path().parent.glob("fleet.json.corrupt.*"))

    def test_an_unreadable_registry_fails_toward_the_gate(
            self, gate_home, monkeypatch):
        # The degradation `_registry_records_or_none` promises: None is
        # "decide without the registry", never "let the caller through".
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-other-body")
        _fresh_claim()
        self._corrupt_registry()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None, send_target="supervisor")


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

GATED_VERBS = ["spawn", "sup-spawn", "send", "respawn", "kill", "clean",
               "interrupt", "archive", "resume-limited", "release", "init"]


def _gated_argv(verb, home):
    """§7's taxonomy as argv, shared by BOTH arming arms (held and wedged) so
    the two taxonomies cannot drift apart -- which is what let a carve-out
    disarming seven of the eleven verbs survive the whole suite (CRIT-1).

    A name that does not exist is fine: the gate runs BEFORE the verb's own
    work, so the gate refusal (exit 4) precedes any unknown-worker error (exit
    1). That ordering is part of the assertion."""
    return {"spawn": ["spawn", "w", "--dir", str(home), "--task", "go"],
            "sup-spawn": ["sup-spawn", "--task", "go"],
            "send": ["send", "w", "hi"],
            "respawn": ["respawn", "w"],
            "kill": ["kill", "w"],
            "clean": ["clean"],
            "interrupt": ["interrupt", "w"],
            "archive": ["archive"],
            "resume-limited": ["resume-limited"],
            "release": ["release", "w"],
            "init": ["init"]}[verb]


class TestEveryMutatingVerbIsGated:
    """§7's taxonomy is binding. Each mutating lifecycle verb refuses under an
    armed gate with no generation; `autoclean` (the gate's own primary caller)
    is structurally exempt. Driven through `fleet.main` so the parser wiring
    (the `--nonce` argument) is exercised too."""

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_verb_is_refused_under_an_armed_gate(self, gate_home, monkeypatch, verb):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        assert fleet.main(_gated_argv(verb, gate_home)) == fleet.SUPERVISOR_CONTINUITY_RC

    def test_the_taxonomy_covers_every_call_site_in_fleet(self):
        """The list is not allowed to be shorter than the code.

        `GATED_VERBS` is the thing both arming arms are parametrised over, so a
        verb that reaches `_supervisor_gate` and is missing from this list is
        invisible to BOTH taxonomy tests at once -- the failure CRIT-1
        describes, one level up. Read out of the source rather than restated."""
        src = (Path(fleet.__file__)).read_text(encoding="utf-8")
        called = set(re.findall(r'_supervisor_gate\(\s*"([a-z-]+)"', src))
        assert called == set(GATED_VERBS), (
            f"call sites not in GATED_VERBS: {sorted(called - set(GATED_VERBS))}; "
            f"GATED_VERBS with no call site: {sorted(set(GATED_VERBS) - called)}")

    def test_autoclean_is_structurally_exempt(self, gate_home, monkeypatch):
        # Even with a sid and a fresh claim and no generation, autoclean is not
        # gated (§7): it is the gate's own primary caller and the scheduler
        # ignores its exit code anyway (docs/specs/autoclean.md:38).
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _fresh_claim()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        rc = fleet.main(["autoclean", "--fleet-home", str(gate_home)])
        assert rc != fleet.SUPERVISOR_CONTINUITY_RC


class TestEveryMutatingVerbIsGatedByTheWedge:
    """The SAME taxonomy, on the WEDGED arm -- fix-wave item 1, break-lens
    CRIT-1.

    The held-claim arm above has driven all of §7's verbs since the gate
    shipped. The wedged arm shipped with four (`clean`, `kill`, `interrupt`,
    `spawn`), and the break lens measured what that costs: two behavioural
    mutants of `_wedged_release_gate` survived the entire 2185-test suite --
    `if verb not in ("clean","kill","interrupt","spawn"): return`, which opens
    `respawn` and `release` while leaving the branch's own headline verb
    protected, and `if verb == "send": return`, which is the exact carve-out
    this branch's own report names as the first change it would make. Nothing in
    the suite could tell anyone whether such a change landed for one verb or
    took six others with it.

    Parametrised over the SAME `GATED_VERBS` list as the held arm, deliberately:
    one taxonomy, two arms, no way for them to drift.

    The discriminator -- that this refusal is the wedge and not something
    unconditional -- is not repeated per verb; it is
    `tests/test_gate_arm_wedge.py`'s roster-gone pair, which drives the same
    verbs to rc=0 with their real work reached."""

    @pytest.mark.parametrize("verb", GATED_VERBS)
    def test_verb_is_refused_under_a_wedged_claim(self, gate_home, monkeypatch, verb):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-third-body")
        fleet.write_incarnation({"incarnation_id": "inc-old", "lineage_id": "lin-L",
                                 "claimed_via": "fresh", "released_at": fleet.now_iso(),
                                 "released_by_sid": "sid-releaser", "state": "released"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (
            True, [{"sessionId": "sid-releaser", "status": "idle", "pid": 4242}]))
        assert fleet.main(_gated_argv(verb, gate_home)) == fleet.SUPERVISOR_CONTINUITY_RC
