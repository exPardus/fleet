"""FIX WAVE 2 -- the worker-turn gate stops being contingent on a readable registry.

THE DEFECT (break-lens MAJOR 2, and the supervisor's own ruling produced it).
Wave 1 restored the §6.5 D5 worker-turn refusal as a GATE ahead of the claim
read, keyed on the registry per `SPEC.md`:196. The ordering closes rb MAJOR 5
**when the registry resolves**. `_acting_worker_name` returns `None` for three
states that are not "you are not a worker" but "I cannot say" -- a CORRUPT
registry, an AMBIGUOUS double match, and a typed `--sid` naming a sid no record
carries -- and on all three the gate is not there at all. Driven A/B against
`main` by the break lens: the same worker turn `main` refuses walks through on
the branch, and on a legacy claim mints itself generation 1 with **no `--nonce`
ever passed**. That is rb MAJOR 5 reached through the abstention door rather
than through the ordering wave 1 fixed.

THE ASYMMETRY THAT NAMES THE FIX. The same corrupt registry makes
`_ceiling_refuses_dispatch` fail **CLOSED** (ND4b) and this gate fail **OPEN**.
`_caller_holds_supervisor_claim` distinguishes *unreadable* (`None`) from
*provably-not* (`False`); `_acting_worker_name` collapsed both into `None`. The
information needed to fail closed was already computed and thrown away --
`_acting_body_is_worker_turn` is that information, kept.

WHAT THIS FILE PINS, and the shape it pins is deliberately NOT "fail closed
everywhere":

  * AMBIGUOUS with every candidate worker-shaped REFUSES. Which worker it is
    does not matter; every answer is a worker turn.
  * The §9 LEGACY-CLAIM UPGRADE -- the one arm that needs no nonce at all --
    requires an affirmative *"the registry read and you are not a worker"*.
    An abstention can no longer earn generation 1.
  * UNRESOLVED against a READABLE registry still passes, because that lane is
    the interface tier, a newborn body in its own dispatch window, and the
    handoff successor in window 1. Failing closed there would lock out bodies
    the confirmation review measured as passing.
  * The unreadable-registry lane still passes AT THE GATE. See §5 of
    `FIX-WAVE-IDENTITY.md` for what remains open there and why closing it would
    need the gate moved after the nonce arms.

`TestTheFailClosedRoster` is the confirmation review's roster, which every
member must survive: it is the regression suite for this change, not decoration.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


CORRUPT = "{ this is not json"


@pytest.fixture
def id2_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME. Nothing here touches the live fleet: every verb
    runs in-process against `tmp_path` with the roster subprocess faked."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Supervisor Goals\n\nThe Target: test.\n", encoding="utf-8")
    (tmp_path / "knowledge" / "INDEX.md").write_text(
        "# Knowledge Index\n- entry one\n", encoding="utf-8")
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _rec(session_id=None, retired=(), status="idle", archived_at=None):
    return {"session_id": session_id, "retired_sids": list(retired),
            "status": status, "archived_at": archived_at}


def _registry(workers):
    fleet.save_registry({"workers": workers})


def _corrupt():
    fleet.registry_path().write_text(CORRUPT, encoding="utf-8")


def _hold(sid):
    """A held claim carrying a live generation; returns its plaintext."""
    value = fleet.mint_nonce()
    fleet.write_incarnation({
        "incarnation_id": "inc-x", "session_id": sid, "state": "active",
        "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
        "lineage_id": "lin-x", "heartbeat_at": fleet.now_iso()})
    return value


def _legacy(sid):
    """The legacy INCARNATION of §9 -- no generation of any kind.

    `_claim_is_legacy` is *"`nonce_hash` absent AND `state` absent"*, and the
    second conjunct is load-bearing: a RELEASED claim also has no `nonce_hash`,
    so a predicate that looked only at the generation would let whoever matched
    the recorded sid resurrect a terminal claim. Nothing on either tree mints
    one of these today; the break lens wrote it by hand and so does this file,
    which is why the compound is MAJOR and not CRITICAL."""
    fleet.write_incarnation({
        "incarnation_id": "inc-legacy", "session_id": sid, "lineage_id": "lin-x",
        "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso()})


def _beat(sid, nonce=None):
    return fleet.cmd_sup_heartbeat(SimpleNamespace(sid=sid, nonce=nonce))


def _ckpt(sid, nonce=None):
    return fleet.cmd_sup_checkpoint(SimpleNamespace(
        body="did a thing", kind="CHECKPOINT", sid=sid, nonce=nonce))


def _fake_which(_name):
    return "C:/fake/claude.cmd"


def _fake_run_roster(entries):
    def run(argv, **kw):
        assert "--json" in argv and "--all" in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


# --------------------------------------------------------------------------
# 1. The predicate itself -- unreadable is not the same answer as not-a-worker
# --------------------------------------------------------------------------

class TestTheWorkerTurnPredicate:
    """`_acting_body_is_worker_turn` is tri-state, exactly as
    `_caller_holds_supervisor_claim` is, and for the same reason: a guard that
    cannot tell *"provably not"* from *"cannot say"* must pick one fail
    direction for both, and the two want opposite ones."""

    def test_a_resolved_worker_is_True(self, id2_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is True

    def test_a_resolved_supervisor_shaped_body_is_False(self, id2_home):
        _registry({"sup|inc-x|boot": _rec("sid-sup", status="working")})
        assert fleet._acting_body_is_worker_turn(sid="sid-sup") is False

    def test_UNRESOLVED_against_a_READABLE_registry_is_False(self, id2_home):
        """An affirmative verdict, not an abstention: the registry was read and
        no record carries this sid. The interface tier lives here."""
        _registry({"w1": _rec("sid-w1")})
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is False

    def test_an_UNINITIALISED_registry_is_still_a_readable_NO(self, id2_home):
        """`state/fleet.json` absent is *"there are no records"*, which is a
        definite answer. Only *unreadable* is indeterminate -- conflating the
        two would refuse the legacy upgrade on every fresh install."""
        assert not fleet.registry_path().exists()
        assert fleet._acting_body_is_worker_turn(sid="sid-nobody") is False

    def test_a_CORRUPT_registry_is_None(self, id2_home):
        _corrupt()
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is None

    def test_AMBIGUOUS_all_worker_shaped_is_True(self, id2_home):
        _registry({"a": _rec("sid-dup"), "b": _rec("sid-dup")})
        assert fleet._acting_body_is_worker_turn(sid="sid-dup") is True

    def test_AMBIGUOUS_all_supervisor_shaped_is_False(self, id2_home):
        """The symmetric argument to the one above, and it has to be made or
        the rule is *"ambiguity refuses"* rather than *"every answer is a
        worker turn"*: if every candidate is supervisor-shaped then no answer
        is a worker turn, and the body must not be refused."""
        _registry({"sup|inc-a|boot": _rec("sid-dup"),
                   "sup|inc-b|successor": _rec("sid-dup")})
        assert fleet._acting_body_is_worker_turn(sid="sid-dup") is False

    def test_AMBIGUOUS_with_MIXED_shapes_is_None(self, id2_home):
        _registry({"w1": _rec("sid-dup"), "sup|inc-a|boot": _rec("sid-dup")})
        assert fleet._acting_body_is_worker_turn(sid="sid-dup") is None

    def test_a_dead_husk_does_not_manufacture_an_ambiguous_refusal(self, id2_home):
        """`candidates = live or matches` is the identity helper's rule and the
        predicate must read the same set, or a husk left by a fork-steer would
        start refusing the live body it shares a sid with."""
        _registry({"sup|inc-a|boot": _rec("sid-dup", status="working"),
                   "husk": _rec("sid-dup", status="dead")})
        assert fleet._acting_body_is_worker_turn(sid="sid-dup") is False

    def test_no_sid_is_None_not_a_verdict(self, id2_home):
        _registry({"w1": _rec("sid-w1")})
        assert fleet._acting_body_is_worker_turn(sid=None) is None


# --------------------------------------------------------------------------
# 2. The gate -- AMBIGUOUS stops being a free pass
# --------------------------------------------------------------------------

class TestTheGateRefusesAnAmbiguousWorker:

    def test_an_AMBIGUOUS_worker_body_is_REFUSED_even_holding_the_live_nonce(
            self, id2_home, monkeypatch, capsys):
        """The brief's first bullet. Both candidates are ordinary workers, so
        it does not matter which one this body is -- every answer is a worker
        turn, and the supervisor claim is not a worker's to hold (§6.5 D5)."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"a": _rec("sid-dup", status="working"),
                   "b": _rec("sid-dup", status="working")})
        live = _hold("sid-dup")
        with pytest.raises(fleet.FleetCliError) as exc:
            _ckpt("sid-dup", nonce=live)
        assert "worker turn" in str(exc.value)
        capsys.readouterr()

    def test_the_ambiguous_refusal_names_every_candidate(self, id2_home, monkeypatch):
        """An operator facing this needs both record names: the state is two
        records carrying one sid, and the remedy is to retire the stale one."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"a": _rec("sid-dup"), "b": _rec("sid-dup")})
        _hold("sid-dup")
        with pytest.raises(fleet.FleetCliError) as exc:
            _ckpt("sid-dup", nonce=fleet.mint_nonce())
        assert "'a'" in str(exc.value) and "'b'" in str(exc.value)

    def test_an_AMBIGUOUS_supervisor_shaped_body_still_passes_to_the_nonce(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"sup|inc-a|boot": _rec("sid-dup"),
                   "sup|inc-b|successor": _rec("sid-dup")})
        live = _hold("sid-dup")
        assert _ckpt("sid-dup", nonce=live) == 0
        capsys.readouterr()

    def test_an_AMBIGUOUS_MIXED_body_still_passes_to_the_nonce(
            self, id2_home, monkeypatch, capsys):
        """Mixed shapes are the one ambiguity that stays an abstention: one
        answer is a worker turn and the other is not, so the registry genuinely
        cannot say, and the nonce remains the real gate."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"w1": _rec("sid-dup"), "sup|inc-a|boot": _rec("sid-dup")})
        live = _hold("sid-dup")
        assert _ckpt("sid-dup", nonce=live) == 0
        capsys.readouterr()

    def test_a_CORRUPT_registry_still_passes_the_gate_and_that_is_DISCLOSED(
            self, id2_home, monkeypatch, capsys):
        """NOT a fix -- a pin on the boundary this wave did not move, so that
        moving it later is a deliberate edit. The gate sits ahead of the claim
        read and therefore cannot consult the nonce; with no registry there is
        no way to tell a holder from a worker at this point in the function.
        What the wave DOES close on this lane is the legacy upgrade below."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        live = _hold("sid-w1")
        _corrupt()
        assert _ckpt("sid-w1", nonce=live) == 0
        capsys.readouterr()


# --------------------------------------------------------------------------
# 3. The legacy upgrade -- an abstention can no longer mint generation 1
# --------------------------------------------------------------------------

class TestTheLegacyUpgradeNeedsAnAffirmativeVerdict:
    """§5.3 rule 4 / §9. This is the one arm that needs NO nonce at all: bare
    sid equality against a five-key claim mints generation 1 and upgrades the
    claim in place. Reaching it through an abstention is a privilege
    escalation, and it is rb MAJOR 5's remaining door."""

    def test_a_CORRUPT_registry_cannot_earn_the_upgrade(
            self, id2_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError) as exc:
            _ckpt("sid-w1")
        assert "registry" in str(exc.value)
        assert "nonce_hash" not in fleet.read_incarnation()

    def test_an_AMBIGUOUS_registry_cannot_earn_the_upgrade(
            self, id2_home, monkeypatch):
        """Mixed shapes: the registry cannot say whether this is a worker, and
        the upgrade needs it to say."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-dup")
        _registry({"w1": _rec("sid-dup"), "sup|inc-a|boot": _rec("sid-dup")})
        _legacy("sid-dup")
        with pytest.raises(fleet.FleetCliError) as exc:
            _ckpt("sid-dup")
        assert "registry" in str(exc.value)
        assert "nonce_hash" not in fleet.read_incarnation()

    def test_a_typed_sid_in_no_record_can_STILL_earn_the_upgrade(
            self, id2_home, monkeypatch, capsys):
        """UNRESOLVED against a readable registry is an AFFIRMATIVE no, and the
        brief is explicit that this lane keeps passing: it is the interface
        tier, a newborn body, and the successor in handoff window 1. Refusing
        here would lock out the bodies the confirmation review measured."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        _legacy("sid-iface")
        assert _ckpt("sid-iface") == 0
        assert "NONCE:" in capsys.readouterr().out
        assert fleet.read_incarnation()["nonce_seq"] == 1

    def test_a_supervisor_shaped_body_can_still_earn_the_upgrade(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|inc-x|boot": _rec("sid-sup", status="working")})
        _legacy("sid-sup")
        assert _ckpt("sid-sup") == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["nonce_seq"] == 1

    def test_the_refusal_does_not_cry_second_body(self, id2_home, monkeypatch):
        """It is NOT filed as a continuity `refused` record, deliberately. The
        state is *"a legacy claim, a caller whose sid equals the holder's, and a
        registry that cannot be read"* -- overwhelmingly the real holder plus a
        broken file. `refused` is the row `SPEC.md`:273 makes the doctor fail on
        as evidence of a SECOND BODY, and filing it here would cry wolf on the
        holder's own turn. Disclosed in `FIX-WAVE-IDENTITY.md` §wave-2 rather
        than traded silently."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _legacy("sid-w1")
        _corrupt()
        with pytest.raises(fleet.FleetCliError):
            _ckpt("sid-w1")
        assert fleet._recent_nonce_rejections() == []


# --------------------------------------------------------------------------
# 4. `sup-boot` -- the verb that could take a claim it could never put down
# --------------------------------------------------------------------------

class TestSupBootIsGatedToo:
    """MINOR 1. `cmd_sup_boot` does not call `_require_claim_holder`, so it had
    no worker-turn gate at all: a worker-shaped body booted at rc 0, was handed
    a live generation, and was then refused by EVERY subsequent verb --
    `sup-release` included. It held a valid claim it could not put down, so the
    claim aged into staleness and someone else could seize it. Self-healing and
    time-bounded, hence MINOR, but it is the §16.2 wedge's cousin and it takes
    the same predicate at the same threshold."""

    def _boot(self, sid, entries=(), handoff=None):
        args = SimpleNamespace(sid=sid, handoff_inc=handoff, nonce=None,
                               handoff_token=None)
        return fleet.cmd_sup_boot(args, which=_fake_which,
                                  run=_fake_run_roster(list(entries)))

    def test_a_worker_shaped_body_is_REFUSED_at_sup_boot(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        with pytest.raises(fleet.FleetCliError) as exc:
            self._boot("sid-w1", [{"sessionId": "sid-w1", "status": "busy"}])
        assert "worker turn" in str(exc.value)
        capsys.readouterr()

    def test_the_refused_boot_writes_NOTHING(self, id2_home, monkeypatch, capsys):
        """The wedge is that a boot SUCCEEDS and then cannot be unwound. A
        refusal that still wrote an INCARNATION would be the same wedge with an
        error message on top."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        with pytest.raises(fleet.FleetCliError):
            self._boot("sid-w1", [{"sessionId": "sid-w1", "status": "busy"}])
        capsys.readouterr()
        assert fleet.read_incarnation() is None
        assert fleet.supervisor_journal_entries() == []

    def test_a_gen0_supervisor_shaped_body_still_BOOTS(
            self, id2_home, monkeypatch, capsys):
        """The `sup|<launch-id>|boot` family is exactly what sup-boot is for.
        Refusing it would brick the verb."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|launch-1|boot": _rec("sid-sup", status="working")})
        assert self._boot("sid-sup", [{"sessionId": "sid-sup", "status": "busy"}]) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["session_id"] == "sid-sup"

    def test_an_UNRESOLVED_interface_session_still_BOOTS(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1")})
        assert self._boot("sid-iface", [{"sessionId": "sid-iface", "status": "busy"}]) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["session_id"] == "sid-iface"

    def test_a_CORRUPT_registry_does_not_brick_sup_boot(
            self, id2_home, monkeypatch, capsys):
        """The abstention lane again: `sup-boot` is the recovery verb, and a
        broken `state/fleet.json` must not be what stops a fleet being
        recovered."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _corrupt()
        assert self._boot("sid-sup", [{"sessionId": "sid-sup", "status": "busy"}]) == 0
        capsys.readouterr()

    def test_successor_mode_is_not_refused(self, id2_home, monkeypatch, capsys):
        """`--handoff-inc` writes HANDSHAKE only and holds no claim. In window 1
        the successor's record carries `session_id=None`, so it is UNRESOLVED
        and must pass."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-successor")
        _registry({"sup|inc-x|successor": _rec(None)})
        assert self._boot("sid-successor", [], handoff="inc-x") == 0
        capsys.readouterr()

    def test_the_boot_gate_and_the_verb_gate_agree(self, id2_home, monkeypatch):
        """One predicate, two call sites. A body sup-boot admits must not be a
        body every other verb refuses -- that divergence IS the wedge."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        _registry({"w1": _rec("sid-w1", status="working")})
        assert fleet._acting_body_is_worker_turn(sid="sid-w1") is True
        with pytest.raises(fleet.FleetCliError):
            self._boot("sid-w1", [{"sessionId": "sid-w1", "status": "busy"}])
        _hold("sid-w1")
        with pytest.raises(fleet.FleetCliError):
            _beat("sid-w1", nonce=fleet.mint_nonce())


# --------------------------------------------------------------------------
# 5. The fail-closed roster -- the confirmation review's list, as a suite
# --------------------------------------------------------------------------

class TestTheFailClosedRoster:
    """Every body the break lens confirmed PASSES must still pass. This is the
    regression suite for the two tightenings above; the brief's instruction is
    *"pin the three disarms; do not un-pin the roster"*.

    Each case is a registry state plus an acting sid, driven through
    `sup-heartbeat` -- one of the seven `_require_claim_holder` verbs, and the
    one with no pre-flight of its own to muddy the result."""

    def test_the_claim_holder_itself(self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|inc-x|boot": _rec("sid-sup", status="working")})
        live = _hold("sid-sup")
        assert _beat("sid-sup", nonce=live) == 0
        capsys.readouterr()

    def test_a_gen0_sup_launch_id_boot_body(self, id2_home, monkeypatch, capsys):
        """The `<inc>` position accepts a LAUNCH id, not only an `inc-` id --
        checked separately by the confirmation review and pinned here."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"sup|launch-20260727T0100Z-abcd|boot":
                   _rec("sid-sup", status="working")})
        live = _hold("sid-sup")
        assert _beat("sid-sup", nonce=live) == 0
        capsys.readouterr()

    def test_the_successor_in_handoff_window_1(self, id2_home, monkeypatch, capsys):
        """Record exists, `session_id` still None -- UNRESOLVED, and the
        registry is readable, so this is an affirmative pass rather than an
        abstention."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-successor")
        _registry({"sup|inc-x|successor": _rec(None)})
        live = _hold("sid-successor")
        assert _beat("sid-successor", nonce=live) == 0
        capsys.readouterr()

    def test_the_successor_in_handoff_window_2(self, id2_home, monkeypatch, capsys):
        """Record restamped -- RESOLVED to a supervisor-shaped name. The two
        windows survive by INDEPENDENT mechanisms; either alone carries it."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-successor")
        _registry({"sup|inc-x|successor": _rec("sid-successor", status="working")})
        live = _hold("sid-successor")
        assert _beat("sid-successor", nonce=live) == 0
        capsys.readouterr()

    def test_a_fork_steered_body_carrying_retired_sids(
            self, id2_home, monkeypatch, capsys):
        """ND4a: the sid union is the key, so the steered body still resolves
        to its own record rather than falling into an abstention."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-forked")
        _registry({"sup|inc-x|boot": _rec("sid-forked", retired=["sid-sup"],
                                          status="working")})
        live = _hold("sid-forked")
        assert _beat("sid-forked", nonce=live) == 0
        capsys.readouterr()

    def test_a_body_parked_limited_and_resumed_under_a_rotated_sid(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-resumed")
        _registry({"sup|inc-x|boot": _rec("sid-resumed", retired=["sid-parked"],
                                          status="limited")})
        live = _hold("sid-resumed")
        assert _beat("sid-resumed", nonce=live) == 0
        capsys.readouterr()

    def test_the_16_2_wedge_stays_cured(self, id2_home, monkeypatch, capsys):
        """A supervisor body wearing a DONATED worker-shaped `FLEET_WORKER`.
        The stamp decides nothing at this site -- the cure is the re-key, and
        neither tightening in this wave reads the variable."""
        monkeypatch.setenv("FLEET_WORKER", "some-worker")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-sup")
        _registry({"some-worker": _rec("sid-long-dead", status="idle"),
                   "sup|inc-x|boot": _rec("sid-sup", status="working")})
        live = _hold("sid-sup")
        assert fleet.cmd_sup_release(
            SimpleNamespace(reason="done", sid="sid-sup", nonce=live)) == 0
        capsys.readouterr()
        assert fleet.read_incarnation()["state"] == "released"


# --------------------------------------------------------------------------
# 6. TASK 2 -- `_supervisor_gate` was the SEVENTH `load_registry` instance
# --------------------------------------------------------------------------

class TestTheSupervisorGateDoesNotQuarantine:
    """MAJOR 1. `_supervisor_gate` documents itself *"READ-ONLY: no lock, no
    mint, no write"* and runs *"at the top of every mutating lifecycle verb"*,
    and called `load_registry()` inside `except RegistryCorruptError` -- the
    catch-and-continue `load_registry`'s docstring forbids. So `fleet send w1
    hello` on a corrupt registry RENAMED `state/fleet.json` aside and refused
    with a message that never mentions the registry; `cmd_send`'s own
    sanctioned aborting read under the lock is never reached on that path.

    The call is byte-identical on `main` (`main:10930`), so this branch did not
    mint it. What the branch DID do is allowlist it in
    `tests/test_load_registry_callers.py` under *"supervisor lifecycle: all
    inside `fleet_lock()`"*, which is false -- it takes no lock and says so --
    and against the list's own admission rule. A detector that certifies a live
    defect is worse than no detector, so both halves are fixed here.

    THE PATH IS THE EVERYDAY ONE. The gate reaches this read only when a claim
    is held with a fresh heartbeat and the caller presented no generation,
    which is the interface tier's normal state BY DESIGN (§7 seam #1)."""

    def _send(self):
        return fleet.cmd_send(SimpleNamespace(name="w1", message="hello", nonce=None),
                              which=_fake_which, sleep=lambda _s: None,
                              run=lambda *a, **k: SimpleNamespace(
                                  returncode=0, stdout="", stderr=""))

    def test_a_corrupt_registry_SURVIVES_a_refused_send(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _hold("sid-sup")
        _corrupt()
        with pytest.raises(fleet.SupervisorClaimGateError):
            self._send()
        capsys.readouterr()
        path = fleet.registry_path()
        assert path.exists(), "state/fleet.json was renamed aside by the §7 gate"
        assert path.read_text(encoding="utf-8") == CORRUPT
        strays = sorted(p.name for p in path.parent.iterdir()
                        if p.name != "fleet.json" and p.name.startswith("fleet.json"))
        assert strays == [], f"quarantine copies appeared: {strays}"

    def test_the_send_carve_out_still_works_on_a_HEALTHY_registry(
            self, id2_home, monkeypatch, capsys):
        """Seam #1 must survive the read being swapped: a `send` whose resolved
        target record IS the claim's own holder body stays UNGATED, because the
        interface tier holds no nonce by design."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"sup|inc-x|boot": _rec("sid-sup", status="working")})
        _hold("sid-sup")
        fleet._supervisor_gate("send", send_target="sup|inc-x|boot")

    def test_a_send_to_a_NON_holder_is_still_gated(
            self, id2_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _registry({"w1": _rec("sid-w1"),
                   "sup|inc-x|boot": _rec("sid-sup", status="working")})
        _hold("sid-sup")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", send_target="w1")

    def test_an_unreadable_registry_fails_TOWARD_the_gate(
            self, id2_home, monkeypatch):
        """The carve-out's fail direction is unchanged by the fix: with no
        readable registry there is no way to prove the target IS the holder, so
        the gate stays armed."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-iface")
        _hold("sid-sup")
        _corrupt()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", send_target="sup|inc-x|boot")
