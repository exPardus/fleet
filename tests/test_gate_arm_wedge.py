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
import re
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


@pytest.fixture(autouse=True)
def _never_dispatch(monkeypatch):
    """MAJ-4, applied to the CLASS. See the twin fixture in
    `tests/test_supervisor_gate.py` for the incident this closes: the gate is
    the ONLY thing between a `spawn` test and a real, billable claude session,
    and this file is where that was learned the expensive way -- four sessions
    launched into pytest tmp dirs on the first RED run. The lesson belongs to
    every test in the file, not to the one that paid for it."""
    monkeypatch.setattr(fleet, "dispatch_bg", lambda *a, **k: pytest.fail(
        "a gate test reached dispatch_bg -- that dispatches a REAL claude session"))


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


def _forked_releaser_record(pre="sid-pre-fork", post="sid-post-fork",
                            name="sup|inc-old|boot", created="2020-01-01T00:00:00Z",
                            save=True):
    """THE UN-RESTAMPED FORK-STEER WINDOW (ND4a), which is what the union arm
    is for: the releasing body was fork-steered after it released, so
    `_restamp_after_steer` eagerly restamped its record IN PLACE (`session_id`
    = the post-fork sid, the pre-fork sid appended to `retired_sids`) while
    INCARNATION still carries the PRE-fork sid it was written with.

    `created` predates the release BY CONSTRUCTION -- a body cannot release a
    claim before its own record exists, and a fork-steer does not mint a new
    record -- and that is exactly the boundary separating this record from a
    respawn's (fix-wave item 3)."""
    rec = fleet.new_worker_record(post, "C:/proj", "t", "acceptEdits",
                                  dispatch_kind="bg")
    rec["retired_sids"] = [pre]
    rec["created"] = created
    if save:
        data = fleet.load_registry()
        data["workers"][name] = rec
        fleet.save_registry(data)
    return rec


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
        # §7's no-sid exemption is unchanged by the wedge: a human shell (and,
        # until 2026-07-27, autoclean's scheduled task) lands here, and a
        # caller with no sid cannot be the divergent body a fork produced.
        # Distinct from `autoclean`'s OWN verb exemption, which is not keyed on
        # the sid at all -- see `cmd_archive`'s `as_autoclean_tier`.
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

    def test_the_roster_ok_flag_is_what_disarms_not_the_payload_shape(
            self, wedge_home, monkeypatch):
        # Measured, not assumed: with the shipped contract (`roster_ok=False`
        # => payload is a REASON STRING) deleting the `not roster_ok` guard
        # changes nothing, because `_roster_live_sids` over a string yields the
        # empty set and the gate disarms by the back door. That makes the guard
        # look redundant and invites a future reader to delete it.
        #
        # It is not redundant, and this is the arm that proves it: a failed
        # fetch whose payload is off-contract -- entries rather than a reason,
        # which is what a partial result or a CLI drift would produce -- must
        # STILL disarm. Correctness must rest on the flag fleet checked, never
        # on `_roster_live_sids` happening to tolerate whatever came back.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (
            False, [{"sessionId": RELEASER, "status": "idle", "pid": 4242}]))
        _tombstone()
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    def test_scheduled_autoclean_still_runs_under_a_wedge(
            self, wedge_home, monkeypatch):
        # `cmd_autoclean` routes its first tier through `cmd_archive`, which IS
        # gated -- so arming a NEW state on the gate reaches autoclean whether
        # or not §7 calls it exempt. THIS COMMENT WAS RIGHT AND WAS NOT READ:
        # the 2026-07-27 timer retirement shipped on a check that asserted
        # `_supervisor_gate` was absent from `cmd_autoclean`'s SOURCE and
        # concluded the sweep was exempt, contradicting the call-graph fact
        # stated right here. The regression it predicted happened (fixed
        # 2026-07-28, `cmd_archive(..., as_autoclean_tier=True)`; the sid-
        # bearing condition is pinned by
        # `tests/test_autoclean.py::TestTheSweepUnderAHeldClaim`).
        #
        # What THIS test still covers, and why it is not redundant: the NO-SID
        # caller -- a human at a shell, and formerly the Scheduled Task -- under
        # the wedged-release arm specifically. A sweep that starts erroring the
        # moment a supervisor retires would be a silent, permanent regression
        # nobody watches.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        _released()
        _roster(monkeypatch, RELEASER)
        rc = fleet.main(["autoclean", "--fleet-home", str(wedge_home)])
        assert rc == 0

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
        assert f"stop session(s) {RELEASER}" in msg
        assert "operator" in msg.lower()
        assert "speed-bump" in msg.lower()

    def test_the_union_arm_names_the_session_that_is_actually_live(
            self, wedge_home, monkeypatch):
        # Break-lens MAJ-1, fix-wave item 2. The test above drives the BARE arm,
        # where `released_by_sid` IS the live sid, so it cannot see this: on the
        # UNION arm the releaser's own sid is roster-GONE by construction -- the
        # arm exists for precisely that case -- and the refusal used to tell the
        # operator to "stop session sid-pre-fork", a session that has already
        # exited. That is R2's defect exactly: a named remedy that always
        # no-ops, which this branch refused to commit for `--nonce` and then
        # committed here.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-pre-fork")
        _roster(monkeypatch, "sid-post-fork")
        _forked_releaser_record()
        with pytest.raises(fleet.SupervisorClaimGateError) as exc:
            fleet._supervisor_gate("clean", nonce=None)
        msg = str(exc.value)
        # the remedy must name the session an operator can actually stop
        assert "stop session(s) sid-post-fork" in msg
        assert "stop session(s) sid-pre-fork" not in msg
        # and the sid that released is still named, as identity, not as remedy
        assert "sid-pre-fork" in msg

    def test_the_refusal_never_names_a_roster_gone_session_as_the_remedy(
            self, wedge_home, monkeypatch):
        # The general form of the same rule, so it cannot regress for a shape
        # nobody wrote a fixture for: EVERY sid the refusal offers as something
        # to stop must be one the roster says is live.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-pre-fork")
        _roster(monkeypatch, "sid-post-fork")
        _forked_releaser_record()
        with pytest.raises(fleet.SupervisorClaimGateError) as exc:
            fleet._supervisor_gate("clean", nonce=None)
        offered = set(re.findall(r"stop session\(s\) ([^.]+?) directly",
                                 str(exc.value))[0].split(", "))
        assert offered == {"sid-post-fork"}, (
            f"the refusal offers sessions that are not roster-live: {offered}")

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


class TestTheWedgedArmCannotCrashAVerb:
    """MIN-1, fix-wave item 6. `_supervisor_gate` wraps `read_incarnation()` in
    `except Exception: return` with the comment *"speed-bump: never crash a verb
    on this"*. The wedged arm was called OUTSIDE that guard and performs two IO
    calls -- a `claude agents` subprocess and a registry read -- so anything
    either surface raised became an unhandled traceback on EVERY mutating verb.
    Both production surfaces are defensively coded today, which is exactly why
    this is pinned rather than argued: the structural asymmetry is the defect.

    The refusal itself must still escape, or the fix would disarm the gate on
    its own armed path -- pinned by every other test in this file, and by the
    third test here explicitly."""

    @pytest.mark.parametrize("surface,exc", [
        ("_fetch_agents_roster", RuntimeError("roster exploded")),
        ("_registry_records_or_none", OSError("registry exploded")),
    ])
    def test_a_raising_surface_does_not_crash_the_verb(
            self, wedge_home, monkeypatch, surface, exc):
        # Driven through the LAST VERB and asserted on its effect: `clean --yes`
        # must complete and delete, exactly as it does on the gate's other
        # fail-open arms, rather than traceback.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        _tombstone()

        def _boom(*a, **k):
            raise exc

        monkeypatch.setattr(fleet, surface, _boom)
        assert fleet.main(["clean", "--yes"]) == 0
        assert _names() == []

    @pytest.mark.parametrize("surface", ["_fetch_agents_roster",
                                         "_registry_records_or_none"])
    def test_the_raise_does_not_escape_the_gate_frame(
            self, wedge_home, monkeypatch, surface):
        # The same fault at the frame the break lens drove it out of, so a
        # future caller that does not go through `fleet.main` is covered too.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)

        def _boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(fleet, surface, _boom)
        fleet._supervisor_gate("kill", nonce=None)      # returns, does not raise

    def test_the_never_crash_guard_does_not_swallow_the_refusal(
            self, wedge_home, monkeypatch):
        # The one exception the guard must NOT catch. A bare `except Exception:
        # return` around the arm would disarm the gate in the exact state it
        # exists for, and every arming test in this file would still pass if the
        # refusal were re-raised as something else -- so pin the type.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released()
        _roster(monkeypatch, RELEASER)
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("kill", nonce=None)


class TestTheGateFiresAheadOfTheCeiling:
    """Evidence for a NEGATIVE result, recorded rather than assumed.

    The brief asks whether the same released early-out at `:2005`
    (`_caller_holds_supervisor_claim`) wrongly strips band/ceiling recognition
    in the wedged state. It cannot be shown to, because that predicate's only
    consumer is `_ceiling_refuses_dispatch`, and every one of its five call
    sites (`spawn` :3769, `send` :4868, `_cmd_respawn_native` :5326, `respawn`
    :5539, `sup-spawn` :13329) runs strictly AFTER `_supervisor_gate` -- the
    respawn pair by way of `cmd_respawn`'s own `_supervisor_gate("respawn")`,
    which is the only route into `_cmd_respawn_native`. In the wedged state the
    gate refuses first and harder, so the dormant ceiling is unreachable. Not
    widened on speculation. (`respawn`'s two sites arm only on `--task`; see
    `tests/test_respawn_ceiling.py`.)"""

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
        # The stub that makes that impossible is now the file-wide autouse
        # `_never_dispatch` fixture (MAJ-4), not a line in this one test.
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

    def test_the_record_wedging_the_fleet_through_the_UNION_is_protected_too(
            self, wedge_home, monkeypatch):
        """Break-lens MAJ-3, fix-wave item 4 -- the half of the result above
        that this branch's OWN Task 2 falsified.

        The test above holds only for the BARE arm, where the record's
        `session_id` IS the releaser and gate 3 sees a roster-live entry. The
        union arm arms the §7 gate on records whose `session_id` is roster-GONE
        while a RETIRED sid is live. For those, gate 0 answers False (released,
        by design, B9) and a `session_id`-only gate 3 answered "not live" -- so
        the very record wedging every mutating verb fleet-wide was fully
        archive-eligible -- so `autoclean` could delete the state the gate
        reads out from under it.

        The fix is gate 3b, NOT a union re-key of gate 3: T9's finding C1
        ruled that a live retired sid is skipped by the rm loop and is "not a
        reason to block the whole worker"
        (`test_rm_skips_a_live_retired_sid_but_rms_current_sid`), and re-keying
        gate 3 reverses that for every ordinary fork-steered worker. Measured,
        not reasoned: the union re-key was written first and that test caught
        it. Gate 3b keys on the SAME predicate the §7 gate arms on, so the two
        cannot disagree about what a wedge is, and it protects nothing else.

        Both halves are asserted in one test on ONE record, because the claim
        being made is that they are the same state."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", THIRD)
        _released(released_by="sid-parent-live")
        # the live sid sits in retired_sids; session_id is roster-gone
        rec = _forked_releaser_record(pre="sid-parent-live", post="sid-child-dead")
        rec["status"] = "idle"
        rec["last_activity"] = "2020-01-01T00:00:00Z"       # far past the TTL
        data = fleet.load_registry()
        data["workers"]["sup|inc-old|boot"] = rec
        fleet.save_registry(data)
        # Gate 3 must be the ONLY thing left standing, or this test would pass
        # for the wrong reason: without an outcome record `_archive_eligible`
        # stops at gate 4 ("no-outcome-record") and reports ineligible even with
        # the defect present. Measured -- that is exactly what the pre-fix run
        # returned.
        fleet.write_tombstone_outcome("sup|inc-old|boot", "sid-child-dead", "stopped")
        roster = [{"sessionId": "sid-parent-live", "status": "idle", "pid": 4242}]

        # half 1: this record ARMS the gate -- the wedge is real
        _roster(monkeypatch, "sid-parent-live")
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet._supervisor_gate("clean", nonce=None)

        # half 2: and it is NOT archive-eligible
        assert fleet._record_is_supervisor_claim_holder(rec) is False, (
            "B9's ratified answer for a released claim -- the premise of this test")
        eligible, reason = fleet._archive_eligible(
            "sup|inc-old|boot", rec, roster, datetime.now(timezone.utc))
        assert eligible is False, "the record wedging the fleet is archivable"
        assert reason == "wedging-released-claim"

    def test_an_ordinary_worker_with_a_live_retired_sid_is_still_archivable(
            self, wedge_home, monkeypatch):
        # The boundary of gate 3b, and the reason it is not a union re-key of
        # gate 3. T9 finding C1: a fork-steer leaves the PARENT's roster entry
        # untouched, so an ordinary worker can carry a live retired sid
        # indefinitely; the rm loop skips that sid and archives the worker
        # anyway. Gate 3b must not quietly reverse that for every worker on the
        # box -- it fires only for the record a released claim is wedging on.
        _released(released_by="sid-someone-else")       # a wedge, but not THIS record
        rec = _forked_releaser_record(pre="sid-parent-live", post="sid-child-dead",
                                      save=False)
        rec["status"] = "idle"
        rec["last_activity"] = "2020-01-01T00:00:00Z"
        fleet.write_tombstone_outcome("w", "sid-child-dead", "stopped")
        roster = [{"sessionId": "sid-parent-live", "status": "idle", "pid": 4242}]
        eligible, reason = fleet._archive_eligible(
            "w", rec, roster, datetime.now(timezone.utc))
        assert (eligible, reason) == (True, "eligible")


