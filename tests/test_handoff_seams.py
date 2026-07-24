"""Handoff-path seams found LIVE during the 2026-07-24 supervisor succession
(inc-651f -> inc-7d7d, two stillborn attempts before the third took).

D1 -- ABORT-VS-MISSING-PENDING. `sup-handoff-begin` recorded the successor it
dispatched NOWHERE the abort path could read it: the token hash went into the
claim, and the abort FLAG is written only on begin's own dispatch-failure/DOA
branches. A successor that dispatched, joined the roster, and then died before
writing HANDSHAKE therefore matched nothing, and `sup-handoff-abort` refused it
twice on the real incident -- "no HANDSHAKE and successor-sid matches no
recorded limbo successor". The handoff was UNABORTABLE in exactly the window
the abort verb exists for. The fix is the missing record (a pending-successor
marker in the claim), NOT a relaxed refusal: refusing to stop a session that
ties to no recorded successor is the safety property.

D2 -- STALE TASK-FILE GC. Each attempt writes `state/supervisor-handoff-<inc>.md`
carrying the successor's PLAINTEXT one-shot token. §5.9 unlinks on complete and
on abort; neither ran for the two stillborn attempts, so three plaintext bearer
tokens sat in `state/` with no owner. The predicate is tested directly here --
the bug worth trading for would be deleting the ACTIVE pending successor's file.

D3 -- the abort recipe is not exempt from the §7 continuity gate; a doc that
shows it without `--nonce` earns an rc 4 mid-succession. Linted below.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sup_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME, same shape as tests/test_supervisor.py's."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    sup = tmp_path / "supervisor"
    sup.mkdir()
    (sup / "GOALS.md").write_text("# Supervisor Goals\n\nThe Target: test.\n",
                                  encoding="utf-8")
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("# Knowledge Index\n- entry one\n",
                                                     encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                             encoding="utf-8")
    return tmp_path


def _fake_which(name):
    return "C:/fake/claude.cmd"


def _dispatch_then_roster(successor_sid="succ0001-full", short_id="succ0001"):
    """Stateful `subprocess.run` double: the successor appears in the roster
    only after the `--bg` dispatch has been observed (contract G6 join)."""
    assert successor_sid.startswith(short_id)
    state = {"dispatched": False}
    def run(argv, **kw):
        if "--bg" in argv:
            state["dispatched"] = True
            return SimpleNamespace(returncode=0,
                                   stdout=f"backgrounded \u00b7 {short_id} \u00b7 sup\n",
                                   stderr="")
        entries = [{"sessionId": "sid-old", "status": "busy"}]
        if state["dispatched"]:
            entries.append({"sessionId": successor_sid, "status": "busy"})
        return SimpleNamespace(returncode=0, stdout=json.dumps(entries), stderr="")
    return run


class _Clock:
    """Injectable monotonic clock; pairing `sleep=advance` runs the real join
    window in zero wall-clock time."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _stop_ok(calls=None):
    def run(argv, **kw):
        if calls is not None:
            calls.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


class _HandoffBase:
    """A live claim-holding predecessor, plus `begin` driven to a successful
    roster join. The generation is captured off begin's own stdout, exactly
    where a real body reads it."""

    def _hold(self, sid="sid-old", inc="inc-old"):
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": inc, "session_id": sid,
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})

    def _begin(self, capsys, run=None, sid="sid-old", nonce=None):
        """Returns `(rc, generation)`. A legacy first-contact claim is upgraded
        by begin and its generation delivered on stdout (§9); a claim that is
        already live gets `notices == []` and prints nothing, so the caller
        keeps presenting the value it already holds."""
        args = SimpleNamespace(sid=sid, model=None, permission_mode=None, nonce=nonce)
        rc = fleet.cmd_sup_handoff_begin(args, which=_fake_which,
                                         run=run or _dispatch_then_roster(),
                                         sleep=lambda s: None)
        out = capsys.readouterr().out
        delivered = re.findall(r"^NONCE: (?!unchanged)(\S+)$", out, re.M)
        return rc, (delivered[0] if delivered else nonce)


class TestPendingSuccessorMarker(_HandoffBase):
    """D1: begin must leave a marker the abort path can grab."""

    def test_begin_records_the_pending_successor_in_the_claim(self, sup_home, capsys):
        self._hold()
        rc, _gen = self._begin(capsys)
        assert rc == 0
        pending = fleet.handoff_pending_from(fleet.read_incarnation())
        assert pending is not None, "begin left no pending-successor marker (D1)"
        assert pending["successor_inc"].startswith("inc-")
        assert pending["successor_sid"] == "succ0001-full"
        assert pending["task_file"].endswith(f"supervisor-handoff-{pending['successor_inc']}.md")
        assert pending["minted_at"]
        assert Path(pending["task_file"]).exists()

    def test_the_marker_is_durable_before_the_dispatch_that_could_strand_it(
            self, sup_home, capsys):
        """The ordering is the whole point: a crash between the claim write and
        the roster join must still leave an abortable record. Observed from
        inside the dispatch call, which runs after the claim commit."""
        self._hold()
        seen = {}
        base = _dispatch_then_roster()
        def run(argv, **kw):
            if "--bg" in argv:
                seen["marker"] = fleet.handoff_pending_from(fleet.read_incarnation())
            return base(argv, **kw)
        self._begin(capsys, run=run)
        assert seen["marker"] is not None
        assert seen["marker"]["successor_sid"] is None   # not joined yet
        assert seen["marker"]["successor_inc"].startswith("inc-")

    def test_sup_status_json_publishes_the_pending_successor(self, sup_home, capsys):
        """The live confusion: `pending_present: false` is about the pending
        GENERATION and says nothing about a pending SUCCESSOR, so the operator
        read it as "no successor recorded" while a task file and a registry
        record both existed. Distinct keys, both published."""
        self._hold()
        self._begin(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        inc = json.loads(capsys.readouterr().out)["incarnation"]
        assert inc["handoff_successor_sid"] == "succ0001-full"
        assert inc["handoff_successor_inc"].startswith("inc-")
        assert inc["handoff_pending_since"]
        assert inc["pending_present"] is False        # the nonce pending: unrelated

    def test_the_view_never_publishes_the_task_file_path(self, sup_home, capsys):
        """§5.8: the marker's `task_file` names a LIVE plaintext token. The
        presence bits are publishable; the path to the secret is not."""
        self._hold()
        self._begin(capsys)
        assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0
        raw = capsys.readouterr().out
        assert "task_file" not in raw and "supervisor-handoff-" not in raw


class TestAbortResolvesAStillbornSuccessor(_HandoffBase):
    """D1, the live failure: no HANDSHAKE, no abort flag, and abort refused."""

    def test_abort_with_no_handshake_succeeds_off_the_marker_and_clears_it(
            self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        pending = fleet.handoff_pending_from(fleet.read_incarnation())
        task_file = Path(pending["task_file"])
        assert fleet.read_handshake() is None            # the stillborn case
        assert not fleet.handoff_abort_flag_path().exists()   # and no flag either
        calls = []
        args = SimpleNamespace(sid="sid-old", successor_sid="succ0001-full", nonce=gen)
        assert fleet.cmd_sup_handoff_abort(
            args, which=_fake_which, run=_stop_ok(calls)) == 0
        assert calls, "the recorded limbo successor was never stopped"
        assert calls[0][-2:] == ["stop", fleet._native_job_ref("succ0001-full")]
        claim = fleet.read_incarnation()
        assert fleet.handoff_pending_from(claim) is None      # marker cleared
        assert claim["incarnation_id"] == "inc-old"           # old resumed duty
        assert not task_file.exists()                         # §5.9 token unlinked
        assert fleet.supervisor_journal_latest()["kind"] == "HANDOFF-ABORT"

    def test_abort_still_refuses_an_unrelated_sid_with_a_marker_present(
            self, sup_home, capsys):
        """The safety property, unchanged: the marker adds a recorded
        successor, it does not widen abort into a "stop any sid" verb."""
        self._hold()
        _rc, gen = self._begin(capsys)
        before = fleet.read_incarnation()
        calls = []
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-SOMEONE-ELSE", nonce=gen)
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok(calls))
        assert not calls                                        # nothing stopped
        assert not fleet.handoff_abort_flag_path().exists()     # no flag written
        pending = fleet.handoff_pending_from(fleet.read_incarnation())
        assert pending is not None and pending == fleet.handoff_pending_from(before)

    def test_a_sidless_marker_ties_nothing_and_still_refuses(self, sup_home):
        """A marker written before the roster join carries no sid. `--successor-sid`
        is a sid handle, so there is nothing to tie the caller's sid to -- refuse,
        exactly as with a `successor_sid: null` abort flag (roll-up item 8)."""
        self._hold()
        claim = fleet.read_incarnation()
        claim[fleet.HANDOFF_PENDING_KEY] = {
            "successor_inc": "inc-20260724T081049Z-754f", "successor_sid": None,
            "task_file": "x.md", "minted_at": fleet.now_iso()}
        fleet.write_incarnation(claim)
        calls = []
        args = SimpleNamespace(sid="sid-old", successor_sid="succ0001-full", nonce=None)
        with pytest.raises(fleet.FleetCliError, match="matches no recorded limbo successor"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok(calls))
        assert not calls

    def test_the_refusal_names_the_pending_successor_it_did_not_match(
            self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        args = SimpleNamespace(sid="sid-old", successor_sid="sid-typo", nonce=gen)
        with pytest.raises(fleet.FleetCliError, match="succ0001-full"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok())

    def test_a_live_handshake_still_wins_over_the_marker(self, sup_home, capsys):
        """Arm order is unchanged: HANDSHAKE first. A HANDSHAKE naming a
        different sid than --successor-sid still refuses, marker or no."""
        self._hold()
        _rc, gen = self._begin(capsys)
        fleet.write_handshake("inc-succ", "sid-from-handshake")
        calls = []
        args = SimpleNamespace(sid="sid-old", successor_sid="succ0001-full", nonce=gen)
        with pytest.raises(fleet.FleetCliError, match="does not match HANDSHAKE sid"):
            fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok(calls))
        assert not calls


class TestMarkerLifecycle(_HandoffBase):
    def test_complete_clears_the_marker(self, sup_home, capsys):
        self._hold()
        _rc, gen = self._begin(capsys)
        pending = fleet.handoff_pending_from(fleet.read_incarnation())
        succ_inc = pending["successor_inc"]
        token_hash = fleet.read_incarnation()["handoff_token_hash"]
        fleet.write_handshake(succ_inc, "succ0001-full",
                              handoff_token_hash=token_hash,
                              nonce_hash=fleet.nonce_digest(fleet.mint_nonce()))
        args = SimpleNamespace(sid="sid-old", expect_inc=succ_inc,
                               expect_sid="succ0001-full", nonce=gen)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        claim = fleet.read_incarnation()
        assert claim["incarnation_id"] == succ_inc
        assert fleet.handoff_pending_from(claim) is None
        assert not Path(pending["task_file"]).exists()

    def test_dispatch_failure_drops_the_marker_and_the_token_file(self, sup_home):
        """Nothing was launched, so no body can be reading the task file and
        there is nothing for a later abort to stop."""
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=1, stdout="", stderr="boom")
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None)
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                        sleep=lambda s: None)
        assert fleet.handoff_pending_from(fleet.read_incarnation()) is None
        assert not list((sup_home / "state").glob("supervisor-handoff-*.md"))

    def test_a_DOA_successor_keeps_its_marker(self, sup_home, capsys):
        """The deliberate asymmetry: DOA means the roster never showed the
        successor, which is not the same as knowing no body exists. Deleting a
        live successor's bootstrap file out from under it is the bug this would
        be trading for; the next begin supersedes and sweeps instead."""
        self._hold()
        def run(argv, **kw):
            if "--bg" in argv:
                return SimpleNamespace(returncode=0,
                                       stdout="backgrounded \u00b7 nope0001 \u00b7 sup\n",
                                       stderr="")
            return SimpleNamespace(returncode=0,
                                   stdout=json.dumps([{"sessionId": "sid-old"}]), stderr="")
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None)
        # Injected clock, sleep=advance: the real join window elapses in zero
        # wall-clock time (same pattern as test_supervisor's _Clock).
        clock = _Clock()
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which, run=run,
                                           sleep=clock.advance, clock=clock) == 1
        assert "successor DOA" in capsys.readouterr().out
        pending = fleet.handoff_pending_from(fleet.read_incarnation())
        assert pending is not None and pending["successor_sid"] is None
        assert Path(pending["task_file"]).exists()


class TestHandoffTaskFileSweepPredicate:
    """D2, the predicate on its own -- a pure function over filenames + claim."""

    PENDING = "inc-20260724T082006Z-696e"
    HOLDER = "inc-20260724T045450Z-0dea"
    DEAD = "inc-20260724T081049Z-754f"

    def _claim(self, pending_inc=None, holder=HOLDER):
        claim = {"incarnation_id": holder}
        if pending_inc:
            claim[fleet.HANDOFF_PENDING_KEY] = {
                "successor_inc": pending_inc, "successor_sid": "sid-succ",
                "task_file": f"state/supervisor-handoff-{pending_inc}.md",
                "minted_at": fleet.now_iso()}
        return claim

    def _names(self, *incs):
        return [f"supervisor-handoff-{i}.md" for i in incs]

    def test_the_active_pending_successors_file_is_never_swept(self):
        names = self._names(self.PENDING, self.HOLDER, self.DEAD)
        dead = fleet.handoff_task_files_to_sweep(names, self._claim(self.PENDING))
        assert dead == self._names(self.DEAD)

    def test_the_current_holders_own_file_is_never_swept(self):
        names = self._names(self.HOLDER, self.DEAD)
        dead = fleet.handoff_task_files_to_sweep(names, self._claim(None))
        assert dead == self._names(self.DEAD)

    def test_with_no_handoff_in_flight_every_non_holder_file_is_dead(self):
        names = self._names(self.PENDING, self.DEAD)
        dead = fleet.handoff_task_files_to_sweep(names, self._claim(None))
        assert dead == sorted(self._names(self.PENDING, self.DEAD))

    def test_an_unparseable_name_is_left_for_a_human(self):
        names = ["supervisor-handoff-notes.md", "supervisor-handoff-.md",
                 "supervisor-handoff-INC-20260724T081049Z-754F.md", "README.md"]
        assert fleet.handoff_task_files_to_sweep(names, self._claim(None)) == []

    def test_a_missing_or_corrupt_claim_sweeps_nothing_it_cannot_vouch_for(self):
        """No claim = no holder and no pending successor, so nothing is
        protected -- which is correct: every token on disk is ownerless."""
        names = self._names(self.PENDING, self.DEAD)
        assert fleet.handoff_task_files_to_sweep(names, None) == sorted(names)
        assert fleet.handoff_task_files_to_sweep(names, {}) == sorted(names)

    def test_a_non_dict_marker_reads_as_absent_not_as_a_crash(self):
        claim = {"incarnation_id": self.HOLDER, fleet.HANDOFF_PENDING_KEY: "corrupt"}
        assert fleet.handoff_pending_from(claim) is None
        assert fleet.handoff_task_files_to_sweep(self._names(self.DEAD), claim) == \
            self._names(self.DEAD)


class TestHandoffTaskFileSweepSites(_HandoffBase):
    """D2, the effect at each authorized site."""

    def _seed(self, sup_home, *incs):
        for inc in incs:
            (sup_home / "state" / f"supervisor-handoff-{inc}.md").write_text(
                "TOKEN: plaintext-bearer-secret\n", encoding="utf-8")

    def _remaining(self, sup_home):
        return sorted(p.name for p in (sup_home / "state").glob("supervisor-handoff-*.md"))

    def test_begin_supersedes_the_previous_attempts_token_file(self, sup_home, capsys):
        """The live accumulation: three attempts, three plaintext tokens. The
        second begin supersedes the first."""
        self._hold()
        _rc, gen = self._begin(capsys)
        first = fleet.handoff_pending_from(fleet.read_incarnation())["successor_inc"]
        self._begin(capsys, run=_dispatch_then_roster("succ0002-full", "succ0002"),
                    nonce=gen)
        second = fleet.handoff_pending_from(fleet.read_incarnation())["successor_inc"]
        assert first != second
        assert self._remaining(sup_home) == [f"supervisor-handoff-{second}.md"]

    def test_complete_sweeps_earlier_attempts_too(self, sup_home, capsys):
        self._hold()
        self._seed(sup_home, "inc-20260724T045450Z-0dea")
        _rc, gen = self._begin(capsys)
        succ_inc = fleet.handoff_pending_from(fleet.read_incarnation())["successor_inc"]
        fleet.write_handshake(succ_inc, "succ0001-full",
                              handoff_token_hash=fleet.read_incarnation()["handoff_token_hash"],
                              nonce_hash=fleet.nonce_digest(fleet.mint_nonce()))
        args = SimpleNamespace(sid="sid-old", expect_inc=succ_inc,
                               expect_sid="succ0001-full", nonce=gen)
        assert fleet.cmd_sup_handoff_complete(args) == 0
        assert self._remaining(sup_home) == []

    def test_abort_sweeps_earlier_attempts_too(self, sup_home, capsys):
        self._hold()
        self._seed(sup_home, "inc-20260724T045450Z-0dea")
        _rc, gen = self._begin(capsys)
        args = SimpleNamespace(sid="sid-old", successor_sid="succ0001-full", nonce=gen)
        assert fleet.cmd_sup_handoff_abort(args, which=_fake_which, run=_stop_ok()) == 0
        assert self._remaining(sup_home) == []

    def test_sup_boot_sweeps_orphans_but_spares_the_pending_successor(
            self, sup_home, capsys):
        """§5.9 put the rejection log's out-of-band compaction in `sup-boot`
        for exactly this reason -- a `supervisor-handoff-<inc>.md` belongs to
        no worker record, so `fleet clean` cannot reach it. Same site here."""
        self._hold()
        self._begin(capsys)
        pending_inc = fleet.handoff_pending_from(fleet.read_incarnation())["successor_inc"]
        self._seed(sup_home, "inc-20260724T045450Z-0dea", "inc-20260724T081049Z-754f")
        args = SimpleNamespace(sid="sid-old", handoff_inc=None, nonce=None)
        def roster(argv, **kw):
            return SimpleNamespace(
                returncode=0, stdout=json.dumps([{"sessionId": "sid-old", "status": "busy"}]),
                stderr="")
        fleet.cmd_sup_boot(args, which=_fake_which, run=roster)
        capsys.readouterr()
        assert self._remaining(sup_home) == [f"supervisor-handoff-{pending_inc}.md"]


class TestAbortRecipeCarriesTheNonce:
    """D3: `sup-handoff-abort` is NOT exempt from the §7 continuity gate. The
    runbook showed it without `--nonce`, and following it verbatim earned an
    rc 4 mid-succession on 2026-07-24 -- the moment a wrong recipe costs most.

    Linted rather than fixed-once because the same recipe is copied across the
    operator surface, and an under-swept doc fix is how the last three doc
    defects survived. Scope is the surfaces an operator READS AS INSTRUCTIONS
    (skills/, commands/) plus the hint fleet itself prints; pinned receipts in
    docs/specs quote OLD file contents on purpose and are not swept."""

    # An INVOCATION, not a mention: the verb plus at least one argument-shaped
    # token. Bare prose (`sup-handoff-abort` is also a _require_claim_holder
    # caller) is not a recipe and is not swept.
    RECIPE = re.compile(
        r"sup-handoff-(?:abort|complete)"
        r"(?:\s+(?:--[a-z-]+|<[^>\n]*>|\[[^\]\n]*\]|[A-Za-z0-9|._-]+))+")

    def _surfaces(self):
        return sorted(REPO_ROOT.joinpath("skills").rglob("*.md")) + \
            sorted(REPO_ROOT.joinpath("commands").glob("*.md"))

    def test_every_operator_facing_handoff_recipe_presents_a_nonce(self):
        offenders = []
        for path in self._surfaces():
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in self.RECIPE.finditer(line):
                    if "--nonce" not in match.group(0):
                        offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: "
                                         f"{match.group(0)}")
        assert not offenders, (
            "handoff recipe without --nonce (rc 4 for anyone who follows it):\n"
            + "\n".join(offenders))

    def test_the_hint_fleet_prints_after_begin_presents_a_nonce(self, tmp_path, monkeypatch,
                                                               capsys):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        (tmp_path / "supervisor").mkdir()
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "worker-settings.json").write_text('{"hooks": {}}',
                                                                 encoding="utf-8")
        beat = fleet.now_iso()
        fleet.write_incarnation({"incarnation_id": "inc-old", "session_id": "sid-old",
                                 "claimed_at": beat, "heartbeat_at": beat,
                                 "claimed_via": "fresh"})
        args = SimpleNamespace(sid="sid-old", model=None, permission_mode=None, nonce=None)
        assert fleet.cmd_sup_handoff_begin(args, which=_fake_which,
                                           run=_dispatch_then_roster(),
                                           sleep=lambda s: None) == 0
        out = capsys.readouterr().out
        for match in self.RECIPE.finditer(out):
            assert "--nonce" in match.group(0), match.group(0)
        assert "sup-handoff-abort" in out and "sup-handoff-complete" in out
