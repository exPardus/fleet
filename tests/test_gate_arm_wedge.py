"""The WEDGED STATE: a `released` claim whose releaser is still roster-live.

Two findings from the 2026-07-26 council ruling (`docs/AUTONOMOUS-2026-07-26.md`
§R3) interact adversarially, and this file pins both halves plus the binding
build order between them.

  * **Task 1 (c4).** `_supervisor_gate` -- the claim-nonce §7 speed-bump --
    returned early on ANY `released` claim, disarming itself for every caller
    and every mutating lifecycle verb. Measured live on `main`: with a held
    claim, `kill`/`clean`/`interrupt` from a third body are gated; with a
    wedged record all three were ungated and `fleet clean --yes` -- the
    irreversible one -- simply ran. The wedge has no heartbeat to age out of,
    so the ungated window was INDEFINITE.
  * **Task 2 (c1).** B6 compared a bare `released_by_sid` against the roster
    while `_record_sids` -- whose own docstring says matching `session_id`
    alone fails open (ND4a) -- keys seven other sites. So B6 failed open for a
    fork-steered releaser: it tested the post-fork sid and the roster held the
    pre-fork one.

The ordering is the ruling: Task 2 converts B6 from fail-open to fail-closed
and therefore CREATES wedges where a successor previously booted through. Every
created wedge was, before Task 1, an indefinite fleet-wide ungated window. Task
1 lands first.

**Every arming test here drives the LAST VERB and asserts on its EFFECT** (the
council's transferable rule): a test that asserts `_supervisor_gate` returned
non-None asserts the precondition, and asserting the precondition is the exact
smell that produced the defect this ruling is about.
"""
from datetime import datetime, timezone

import pytest

import fleet


RELEASER = "sid-releaser"
THIRD = "sid-third-body"


@pytest.fixture
def wedge_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs", "supervisor"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    return tmp_path


def _released(released_by=RELEASER, **extra):
    """§6.3's post-release key set, written as the literal `cmd_sup_release`
    writes it: no `session_id`, no `heartbeat_at`, no `nonce_hash`."""
    claim = {"incarnation_id": "inc-old", "lineage_id": "lin-L",
             "claimed_via": "fresh", "released_at": fleet.now_iso(),
             "released_by_sid": released_by, "state": "released"}
    claim.update(extra)
    fleet.write_incarnation(claim)
    return claim


def _roster(monkeypatch, *live_sids, ok=True):
    """Stub the ONE roster surface. `status`/`pid` present and `state` != done
    is what `_roster_live_sids` counts as live (native-substrate roster
    contract)."""
    entries = [{"sessionId": s, "status": "idle", "pid": 4242} for s in live_sids]
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda **_: (ok, entries if ok else "roster unavailable"))
    return entries


def _tombstone(name="ghost", sid="sid-ghost"):
    """An ARCHIVED record: `cmd_clean` deletes it by pure file deletion and
    never enters the roster fetch, so `clean --yes` is deterministic here."""
    rec = fleet.new_worker_record(sid, "C:/proj", "task", "acceptEdits",
                                  dispatch_kind="bg")
    rec["status"] = "dead"
    rec["archived_at"] = fleet.now_iso()
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _victim(name="victim", spawned_by=THIRD):
    rec = fleet.new_worker_record("sid-victim", "C:/proj", "task", "acceptEdits",
                                  dispatch_kind="bg", spawned_by=spawned_by)
    rec["status"] = "idle"
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _spy(monkeypatch, attr):
    """Replace a verb's REAL WORK function. `reached` empty == the verb never
    ran; the status flip is the effect a passing gate would have produced. This
    is the "assert on the last verb" rule made concrete for two verbs whose
    real work is a `claude` subprocess."""
    reached = []

    def _fake(name, rec, **kw):
        reached.append(name)
        data = fleet.load_registry()
        data["workers"][name]["status"] = "dead"
        fleet.save_registry(data)
        return 0

    monkeypatch.setattr(fleet, attr, _fake)
    return reached


def _names():
    return sorted(fleet.load_registry()["workers"])


def _status(name):
    return fleet.load_registry()["workers"][name].get("status")


# --- Task 1: the wedged state ARMS the gate --------------------------------

class TestTheWedgedStateArmsTheGate:
    """c4's finding, driven through the verbs it measured ungated."""

    def test_clean_yes_from_a_third_body_is_refused_and_deletes_nothing(
            self, wedge_home, monkeypatch):
        # THE headline: `fleet clean --yes` is irreversible and it simply ran.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC
        assert _names() == ["ghost"], "clean deleted through a wedged claim"

    @pytest.mark.parametrize("verb,argv,work", [
        ("kill", ["kill", "victim", "--yes"], "_cmd_kill_native"),
        ("interrupt", ["interrupt", "victim"], "_cmd_interrupt_native"),
    ])
    def test_the_other_two_measured_verbs_never_reach_their_work(
            self, wedge_home, monkeypatch, verb, argv, work):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        _victim()
        reached = _spy(monkeypatch, work)
        assert fleet.main(argv) == fleet.SUPERVISOR_CONTINUITY_RC
        assert reached == [], f"{verb} ran through a wedged claim"
        assert _status("victim") == "idle"

    @pytest.mark.parametrize("verb,argv,work", [
        ("kill", ["kill", "victim", "--yes"], "_cmd_kill_native"),
        ("interrupt", ["interrupt", "victim"], "_cmd_interrupt_native"),
    ])
    def test_the_same_two_verbs_run_once_the_releaser_is_gone(
            self, wedge_home, monkeypatch, verb, argv, work):
        # The discriminator, so the refusal above cannot be passing for some
        # unrelated reason: byte-identical setup, releaser roster-GONE.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, "sid-someone-else")
        _victim()
        reached = _spy(monkeypatch, work)
        assert fleet.main(argv) == 0
        assert reached == ["victim"]

    def test_the_releaser_body_itself_is_refused_too(self, wedge_home, monkeypatch):
        # `cmd_sup_release` prints "this incarnation must EXIT: take no further
        # fleet actions". The gate is not a favour to the releaser -- a body
        # that released and kept acting is the shape §6.6 exists for.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RELEASER)
        _released()
        _roster(monkeypatch, RELEASER)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == fleet.SUPERVISOR_CONTINUITY_RC
        assert _names() == ["ghost"]

    def test_a_cleanly_released_claim_still_deletes(self, wedge_home, monkeypatch):
        # The releaser going roster-gone is what ends the wedge -- and it is
        # the ONLY thing that has to. Without this arm the fix would be a
        # permanent fleet-wide refusal rather than a containment.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, "sid-someone-else")
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    def test_a_no_sid_caller_keeps_its_structural_exemption(
            self, wedge_home, monkeypatch):
        # §7's structural exemption is unchanged by the wedge: autoclean's
        # scheduled task and a human shell both land here, and a caller with no
        # sid cannot be the divergent body a fork produced.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _released()
        _roster(monkeypatch, RELEASER)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    @pytest.mark.parametrize("released_by", [None, "", 0, ["sid-releaser"]])
    def test_a_released_record_naming_no_releaser_is_not_wedged(
            self, wedge_home, monkeypatch, released_by):
        # B6's own rule, mirrored: keyed on a non-empty STRING only, so a
        # `None` a drifted or hostile roster put in the live set can never
        # brick every mutating verb forever on a value nobody wrote.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by=released_by)
        _roster(monkeypatch, RELEASER, None, "")
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    def test_an_unavailable_roster_fails_open(self, wedge_home, monkeypatch):
        # DISCLOSED weakness, consistent with this function's own stated
        # doctrine for an unreadable heartbeat: a SPEED-BUMP must not brick
        # every mutating verb. `claude` missing from PATH would otherwise
        # refuse every verb for as long as a released claim sits on disk, which
        # is a strictly larger blast radius than the wedge it would contain.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, ok=False)
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    def test_the_wedge_refusal_writes_nothing(self, wedge_home, monkeypatch):
        # §7: READ-ONLY. No lock, no mint, no write -- a refusal least of all.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        before = fleet.read_incarnation()
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("kill", nonce=None)
        assert fleet.read_incarnation() == before

    def test_the_wedge_refusal_names_only_exits_that_execute(
            self, wedge_home, monkeypatch):
        # R2's binding rewrite doctrine: a remedy string whose named exit
        # always fails is worse than no string. A released claim carries NO
        # `nonce_hash` (§6.3), so `--nonce` can never open this gate and must
        # not be offered; `sup-release --interface` was ruled dead 4-0 and does
        # not exist. What DOES execute: stop the roster-live releaser by sid,
        # the §5.7 operator escalation, and §7's own no-sid bypass.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        with pytest.raises(fleet.SupervisorClaimGateError) as exc:
            fleet._supervisor_gate("clean", nonce=fleet.mint_nonce())
        msg = str(exc.value)
        assert "--nonce" not in msg
        assert "--interface" not in msg
        assert RELEASER in msg                      # the sid to stop
        assert "operator" in msg.lower()
        assert "speed-bump" in msg.lower()

    def test_presenting_a_generation_cannot_open_the_wedge(
            self, wedge_home, monkeypatch):
        # Belt-and-braces on the message test: a released claim has no
        # generation, so there is no value ANY caller could present. Pinned so
        # nobody "helpfully" restores a nonce path that can only ever refuse.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", RELEASER)
        _released(nonce_hash=fleet.nonce_digest("v"), nonce_seq=9)
        _roster(monkeypatch, RELEASER)
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean", nonce="v")

    def test_the_roster_is_not_fetched_when_the_claim_is_not_released(
            self, wedge_home, monkeypatch):
        # Cost pin. The gate runs at the top of EVERY mutating verb including
        # `send`, the beat contract's hot path. The roster subprocess (~1.7s
        # measured on this box) is paid ONLY in the released-with-a-releaser
        # state -- never on a held claim, an absent claim, or a no-sid caller.
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (calls.append(1), (True, []))[1])
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        fleet._supervisor_gate("send", nonce=None)          # no claim at all
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-h", "session_id": "sid-h",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh", "nonce_seq": 1,
                                 "nonce_hash": fleet.nonce_digest("x")})
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("send", nonce=None)      # held claim
        assert calls == []


class TestTheGateFiresAheadOfTheCeiling:
    """Evidence for a NEGATIVE result, recorded rather than assumed.

    The brief asks whether the same released early-out at `:2005`
    (`_caller_holds_supervisor_claim`) wrongly strips band/ceiling recognition
    in the wedged state. It cannot be shown to, because that predicate's only
    consumer is `_ceiling_refuses_dispatch`, and every one of its three call
    sites (`spawn` :3380, `send` :4479, `sup-spawn` :11527) runs strictly AFTER
    `_supervisor_gate`. In the wedged state the gate refuses first and harder,
    so the dormant ceiling is unreachable. Not widened on speculation."""

    def test_a_wedged_spawn_is_refused_by_the_gate_not_the_ceiling(
            self, wedge_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        monkeypatch.setenv("FLEET_WORKER", "some-worker")   # ceiling's own gate
        _released()
        _roster(monkeypatch, RELEASER)
        ceiling_consulted = []
        monkeypatch.setattr(fleet, "_ceiling_refuses_dispatch",
                            lambda *a, **k: ceiling_consulted.append(1))
        # A REAL, BILLABLE session is what sits past this line -- measured the
        # hard way while this file was RED, which is itself the point: with the
        # gate disarmed, `spawn` from a third body ran all the way to dispatch.
        monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
            "spawn reached dispatch through a wedged claim"))
        rc = fleet.main(["spawn", "w", "--dir", str(wedge_home), "--task", "go"])
        assert rc == fleet.SUPERVISOR_CONTINUITY_RC
        assert ceiling_consulted == []


class TestArchiveProtectionIsNotStrippedByTheWedge:
    """The other half of the same negative result, for `:2059`
    (`_record_is_supervisor_claim_holder`).

    `_archive_eligible`'s gate 0 answers False for a released claim BY DESIGN
    (B9: a released-away husk stays archivable). In the wedged state that is
    not a hole, because the releaser is by definition roster-live and gate 3
    already refuses every roster-live record. Left unchanged, with the reason
    executable rather than asserted."""

    def test_a_roster_live_releaser_record_is_still_ineligible_for_archive(
            self, wedge_home, monkeypatch):
        _released()
        rec = fleet.new_worker_record(RELEASER, "C:/proj", "t", "acceptEdits",
                                      dispatch_kind="bg")
        rec["status"] = "idle"
        rec["last_activity"] = "2020-01-01T00:00:00Z"       # far past the TTL
        assert fleet._record_is_supervisor_claim_holder(rec) is False, (
            "B9's ratified answer for a released claim -- the premise of this test")
        roster = [{"sessionId": RELEASER, "status": "idle", "pid": 4242}]
        eligible, reason = fleet._archive_eligible(
            "sup|inc-old|boot", rec, roster, datetime.now(timezone.utc))
        assert eligible is False
        assert "holder" not in reason      # protected by roster-liveness, not by gate 0


