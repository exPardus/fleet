"""THE BRIEF SURVIVES EVERY DISPATCH.

Wave 34 measured `fleet respawn` silently destroying the task file it exists to
reuse: two respawned lanes' briefs were cut to 784/783 bytes mid-sentence while a
lane spawned fresh in the same wave stayed intact at 8927. Root cause, established
by byte-exact reconstruction rather than by inspection: the registry's `task`
snapshot is capped (`new_worker_record`), respawn recomposes a prompt from that
remnant, and `dispatch_bg` then *overwrites* `state/tasks/<name>.md` with it. The
file was never read; it was clobbered.

**These tests are written against the PROPERTY, not against that mechanism.** The
recorded failure mode in this repo is that a pin written against the mechanism you
fixed misses the one you introduced (four instances in `knowledge/lessons.md`), and
that fixing only the site that was wrong reproduces the miss at the next site (two
more). So:

* Nothing here names the registry cap, the brief file, or any other storage
  decision. Every assertion is about what a worker RECEIVES and about what
  survives on disk afterwards, so a future author who replaces the mechanism
  wholesale still owes these greens.
* The sentinel is the brief's LAST line. "The last line survived" fails for a
  registry cap, a marker misparse, a slice, an off-by-one, and for whatever is
  invented next -- unlike "the file is big enough", which a padded stub passes.
* Coverage is a CENSUS over every `dispatch_bg` call site in `bin/fleet.py`,
  re-derived from source on every run. It is derived **by AST and compared as
  COUNTS**, and each driver **proves it reached the site it is keyed under**.
  All three of those are load-bearing and none of them was true of the first
  version: a substring scan set-compared over qualnames was blind to an alias
  (`_launch = dispatch_bg`), to a whitespace variant (`dispatch_bg (`), to a
  second call inside a function already on the list, and to a driver repointed
  at a different path -- four planted mutants, four full-suite greens at 3522.
  A detector is only ever non-vacuous for the shapes someone actually planted
  against it; see `BRIEF_DRIVERS` for what these three now cover.
"""
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


# ---------------------------------------------------------------------------
# fixtures / drivers -- the REAL dispatch_bg runs in every one of them
# ---------------------------------------------------------------------------
#
# `dispatch_bg` is never stubbed. Its unconditional `task_path.write_text` IS
# the destructive act under test, so a double that re-implemented the write
# would be asserting against the test's own copy of the defect. Only `claude`
# itself is faked: `run`, `which`, and the roster.

SID_1 = "11111111-1111-2222-3333-444455556666"
SID_2 = "22222222-1111-2222-3333-444455556666"
SID_3 = "33333333-1111-2222-3333-444455556666"

SENTINEL = "LANE-SENTINEL-9f2c: the last line of the brief, and the whole point."

BRIEF = (
    "# The mission\n\n"
    "You are a worker on a real task with fences that matter.\n\n"
    "## Discipline\n\n"
    + ("- Do the thing carefully, completely, and in the stated order.\n" * 60)
    + "\n## Fences -- hard\n\n- NO PUSH OF ANY REF.\n- One writer per tree.\n\n"
    "## Report\n\n"
    + SENTINEL + "\n"
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """FLEET_HOME in a tmp dir with the rendered instance settings every
    dispatch path requires (SPEC §14)."""
    home = tmp_path / "fleet-home"
    (home / "state").mkdir(parents=True)
    (home / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (home / "logs").mkdir()
    (home / "mailbox").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    return home


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


def _entry(sid):
    return {"id": sid[:8], "sessionId": sid, "name": "fleet|w1|t",
            "cwd": "C:/proj", "startedAt": 1783986489446, "kind": "background",
            "state": "working", "status": "idle", "pid": 4321}


def _roster(*answers):
    """Answer each `_fetch_agents_roster` call in order; repeat the last."""
    box = {"i": 0}

    def _fetch(**_kw):
        i = min(box["i"], len(answers) - 1)
        box["i"] += 1
        return answers[i]
    return _fetch


def _run_for(sid, calls=None):
    def _run(argv, **kw):
        if calls is not None:
            calls.append(argv)
        return types.SimpleNamespace(
            returncode=0,
            stdout=f"backgrounded \u00b7 {sid[:8]} \u00b7 fleet|w1|t\n",
            stderr="")
    return _run


def settle(name):
    """Put a worker in the state a finished turn leaves it in: an outcome
    record for its sid, and an idle label. Without this a `fleet send` takes
    the in-flight mailbox-queue branch and never dispatches at all -- which is
    how a driver here can silently stop exercising the path it names."""
    data = fleet.load_registry()
    rec = data["workers"][name]
    fleet.append_outcome(name, {"ts": fleet.now_iso(),
                                "session_id": rec["session_id"], "kind": "result"})
    rec["status"] = "idle"
    fleet.save_registry(data)


def _claude(_name):
    return "claude"


def spawn(name, cwd, task, monkeypatch, sid=SID_1):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, [_entry(sid)])))
    args = SimpleNamespace(name=name, dir=str(cwd), task=task, mode="bypass",
                           model=None, max_budget_usd=None, setting_sources=None,
                           token_ceiling=None, category=None, context=None,
                           yes=True, nonce=None)
    rc = fleet.cmd_spawn(args, run=_run_for(sid), which=_claude,
                         sleep=lambda s: None, clock=lambda: 0.0)
    assert rc == 0
    return sid


def _respawn_args(name, task=None):
    return SimpleNamespace(name=name, task=task, force=False, yes=True,
                           max_budget_usd=None, setting_sources=None,
                           token_ceiling=None, nonce=None)


def respawn(name, monkeypatch, sid=SID_2, task=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, []), (True, [_entry(sid)])))
    rc = fleet.cmd_respawn(_respawn_args(name, task), run=_run_for(sid),
                           which=_claude, sleep=lambda s: None, clock=lambda: 0.0)
    assert rc == 0
    return sid


def respawn_refused_by_roster(name, monkeypatch, task=None):
    """A respawn that aborts BEFORE the pre-claim: the roster cannot be fetched,
    so liveness is unprovable and respawn refuses outright."""
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, []))

    def _never(*a, **kw):
        raise AssertionError("nothing may dispatch after a roster-fetch refusal")
    with pytest.raises(fleet.FleetCliError, match="could not fetch the native roster"):
        fleet.cmd_respawn(_respawn_args(name, task), run=_never, which=_claude,
                          sleep=lambda s: None, clock=lambda: 0.0)


def respawn_refused_by_dispatch(name, monkeypatch, task=None, sid=SID_2):
    """A respawn that aborts AFTER the pre-claim: the `--bg` launch itself
    fails, and the rollback restores the pre-respawn record."""
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, []), (True, [_entry(sid)])))

    def _failing_run(argv, **kw):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_respawn(_respawn_args(name, task), run=_failing_run,
                          which=_claude, sleep=lambda s: None, clock=lambda: 0.0)


def idle_send(name, message, monkeypatch, old_sid, sid=SID_3):
    """The fork-steer branch of `fleet send` -- the one that dispatches.

    The verdict engine is not what these tests are about: `recompute_worker_native`
    is forced to `idle` so the assertion is about the dispatch, not about
    liveness heuristics. The roster still has to carry the OLD sid, or the G9
    epoch guard refuses before any of that runs."""
    settle(name)

    def _idle(worker, rec, roster, **kw):
        out = dict(rec)
        out["status"] = "idle"
        return out
    monkeypatch.setattr(fleet, "recompute_worker_native", _idle)
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, [_entry(old_sid)]),
                                (True, [_entry(old_sid)]),
                                (True, [_entry(old_sid), _entry(sid)])))
    args = SimpleNamespace(name=name, message=message, yes=True, nonce=None)
    calls = []
    rc = fleet.cmd_send(args, run=_run_for(sid, calls), which=_claude,
                        sleep=lambda s: None)
    assert rc == 0
    assert any("--bg" in argv for argv in calls), (
        "the send queued to the mailbox instead of fork-steering -- this "
        "driver is not exercising a dispatch, so anything it 'proves' about "
        "dispatch is vacuous")
    return sid


def resume_limited(name, cwd, old_sid, monkeypatch, sid=SID_3):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, [_entry(sid)])))
    fleet._resume_one_limited_native(
        name, old_sid, str(cwd), "bypass", None, None, None, None,
        run=_run_for(sid), which=_claude, sleep=lambda s: None)
    return sid


def delivered(name):
    """Exactly what the dispatched session is told to read and follow --
    `dispatch_bg`'s tiny prompt is `Read <task file> and follow it exactly`,
    so this file IS the worker's entire input."""
    return fleet.task_file_path(name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# THE PROPERTY, behaviourally -- no storage decision is named anywhere below
# ---------------------------------------------------------------------------

class TestAFreshSessionReceivesTheWholeBrief:
    """A dispatch that starts a session with NO prior context must hand it the
    whole brief. `respawn` is exactly that -- a fresh session under the same
    name (no `--resume`; the context reset is the point) -- so a respawned
    worker whose brief arrives cut off has been sent to do a job it cannot
    read the definition of."""

    def test_spawn_delivers_the_whole_brief(self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        assert SENTINEL in delivered("w1")

    def test_respawn_delivers_the_whole_brief(self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        respawn("w1", monkeypatch)
        body = delivered("w1")
        assert SENTINEL in body, (
            f"the respawned worker was handed {len(body)} bytes and the brief's "
            f"last line is not among them -- respawn destroyed the brief it "
            f"exists to reuse")

    def test_respawn_delivers_the_whole_brief_after_a_steer(self, project, monkeypatch):
        """The brief must survive a steer too, or respawn merely reuses
        whatever the last steer left behind."""
        old_sid = spawn("w1", project, BRIEF, monkeypatch)
        idle_send("w1", "check the logs", monkeypatch, old_sid=old_sid)
        respawn("w1", monkeypatch, sid=SID_2)
        assert SENTINEL in delivered("w1")

    def test_respawn_delivers_the_whole_brief_after_a_limit_resume(
            self, project, monkeypatch):
        sid = spawn("w1", project, BRIEF, monkeypatch)
        resume_limited("w1", project, sid, monkeypatch)
        respawn("w1", monkeypatch, sid=SID_2)
        assert SENTINEL in delivered("w1")

    def test_an_explicit_task_override_replaces_the_brief_and_is_delivered_whole(
            self, project, monkeypatch):
        """`--task` is the operator supplying new text on purpose: it replaces
        the brief rather than being refused for being shorter."""
        spawn("w1", project, BRIEF, monkeypatch)
        respawn("w1", monkeypatch, task="a much shorter but deliberate new task")
        body = delivered("w1")
        assert "a much shorter but deliberate new task" in body
        assert SENTINEL not in body

    def test_a_second_respawn_still_delivers_the_whole_brief(
            self, project, monkeypatch):
        """Two respawns in a row. A fix that reuses the previous DISPATCH's
        output as the next brief passes once and rots on the second."""
        spawn("w1", project, BRIEF, monkeypatch)
        respawn("w1", monkeypatch, sid=SID_2)
        respawn("w1", monkeypatch, sid=SID_3)
        assert SENTINEL in delivered("w1")

    def test_repeated_respawns_do_not_grow_the_delivered_brief_without_bound(
            self, project, monkeypatch):
        """The other half of the same trap: reusing the previous dispatch's
        output verbatim preserves the sentinel but re-stacks the preamble (and
        every carried section) on every respawn."""
        spawn("w1", project, BRIEF, monkeypatch)
        respawn("w1", monkeypatch, sid=SID_2)
        once = delivered("w1")
        respawn("w1", monkeypatch, sid=SID_3)
        twice = delivered("w1")
        assert twice.count("You are fleet worker") == 1, (
            "the preamble is stacking up: each respawn is reusing the previous "
            "dispatch's output as if it were the brief")
        assert len(twice) <= len(once) + len(BRIEF) // 4


NEW_SCOPE = "TOTALLY-NEW-TASK: a scope this worker was never dispatched on.\n"


class TestARefusedRespawnLeavesTheBriefAlone:
    """F1. `respawn --task X` that REFUSES must not record X.

    The registry rollback restores `before` verbatim on every abort; the brief
    is part of that state now, so a refusal that keeps X is the wave-34 defect
    inverted -- days later a routine bare `fleet respawn` hands the worker a
    scope from a dispatch that never happened, with no event and no warning.

    Both sides of the pre-claim are pinned, because they fail differently: a
    roster-fetch refusal aborts BEFORE anything is written, and a dispatch
    failure aborts AFTER, through the `except` arms. A fix that only moves the
    write inside the `try:` closes the first and leaves the second."""

    def test_a_respawn_refused_before_the_preclaim_does_not_record_the_override(
            self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        before = fleet.brief_file_path("w1").read_bytes()
        respawn_refused_by_roster("w1", monkeypatch, task=NEW_SCOPE)
        assert fleet.brief_file_path("w1").read_bytes() == before, (
            "a refused respawn recorded its --task anyway -- the next BARE "
            "respawn will dispatch a scope no respawn ever ran")

    def test_a_respawn_refused_at_dispatch_does_not_record_the_override(
            self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        before = fleet.brief_file_path("w1").read_bytes()
        respawn_refused_by_dispatch("w1", monkeypatch, task=NEW_SCOPE)
        assert fleet.brief_file_path("w1").read_bytes() == before

    def test_the_next_bare_respawn_after_a_refusal_still_gets_the_real_brief(
            self, project, monkeypatch):
        """The failure the operator actually experiences, end to end."""
        spawn("w1", project, BRIEF, monkeypatch)
        respawn_refused_by_roster("w1", monkeypatch, task=NEW_SCOPE)
        respawn("w1", monkeypatch)
        body = delivered("w1")
        assert NEW_SCOPE.strip() not in body
        assert SENTINEL in body


class TestTheOverrideIsRecordedWhenItSucceeds:
    """F4. The WRITE side of the brief store at respawn, which was unpinned:
    deleting the `write_brief` call outright left the whole suite green,
    because the only override test asserted the delivered body of that SAME
    dispatch. Assert it through a SECOND, bare respawn -- the read path is the
    only thing that proves the write happened."""

    def test_a_successful_override_survives_into_the_next_bare_respawn(
            self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        respawn("w1", monkeypatch, sid=SID_2, task=NEW_SCOPE)
        respawn("w1", monkeypatch, sid=SID_3)
        body = delivered("w1")
        assert NEW_SCOPE.strip() in body, (
            "the --task override was not recorded, so a bare respawn re-scoped "
            "the worker BACKWARDS to the brief it was originally spawned on")
        assert SENTINEL not in body


class TestTheBackstopIsIdentityNotAThreshold:
    """F3. `assert_brief_carried` had no direct test at all, so replacing its
    containment check with `len(prompt_body) < len(brief) // 2` -- the
    "materially shorter" threshold its own docstring and `knowledge/lessons.md`
    both name as unsound in BOTH directions -- left the suite green.

    These four call it directly. The second is the one that kills a threshold:
    same length, one character different."""

    def test_a_carried_brief_passes(self):
        brief = "line one\nline two\n"
        fleet.assert_brief_carried("w1", brief, "PREAMBLE\n" + brief + "\nJOURNAL")

    def test_a_same_length_body_that_is_not_the_brief_is_refused(self):
        brief = "line one\nline two\n"
        same_length = brief[:-2] + "X\n"
        assert len(same_length) == len(brief)
        with pytest.raises(fleet.FleetCliError, match="does not carry the whole brief"):
            fleet.assert_brief_carried("w1", brief, same_length)

    def test_a_proper_prefix_of_the_brief_is_refused_however_long_the_body(self):
        """The exact wave-34 shape, and the one a length threshold misses: a
        truncated brief padded back over any size bar by a carried journal."""
        brief = "the whole brief, ending in the part that matters\n"
        body = "PREAMBLE\n" + brief[:20] + "\n" + ("JOURNAL LINE\n" * 200)
        assert len(body) > len(brief)
        with pytest.raises(fleet.FleetCliError, match="does not carry the whole brief"):
            fleet.assert_brief_carried("w1", brief, body)

    @pytest.mark.parametrize("empty", ["", "   ", "\n\n"])
    def test_an_empty_brief_is_exempt(self, empty):
        """The steer paths compose with no task at all (F6); the backstop must
        not turn that into a refusal."""
        fleet.assert_brief_carried("w1", empty, "PREAMBLE only")


class TestTheCapIsOneNumber:
    """F8. `read_brief` calls a snapshot AT the cap a remnant and refuses it.
    That is only sound while the number it compares against is the number
    `new_worker_record` actually truncates to. They used to be two literals
    agreeing by luck: raising the record's cap made `read_brief` refuse every
    COMPLETE task between the old cap and the new one, and the one test that
    noticed read like a number to update.

    Behavioural, not textual, so it holds however the cap is spelled."""

    def test_the_record_truncates_to_exactly_the_length_read_brief_refuses(self):
        rec = fleet.new_worker_record("s", "C:/p", "x" * 5000, "bypass")
        assert len(rec["task"]) == fleet.LEGACY_TASK_SNAPSHOT_CHARS, (
            f"the registry truncates to {len(rec['task'])} but `read_brief` "
            f"calls {fleet.LEGACY_TASK_SNAPSHOT_CHARS} the remnant length -- "
            f"between the two, a COMPLETE task is refused as a remnant")

    def test_a_task_one_char_under_the_cap_is_dispatched_not_refused(
            self, project, monkeypatch):
        """The other side of the same equality: the refusal must fire on the
        remnant and on nothing else."""
        task = "y" * (fleet.LEGACY_TASK_SNAPSHOT_CHARS - 1)
        spawn("w1", project, task, monkeypatch)
        fleet.brief_file_path("w1").unlink()
        fleet.task_file_path("w1").unlink()
        respawn("w1", monkeypatch)
        assert task in delivered("w1")


class TestCleanSweepsTheBrief:
    """F6. The archive half was pinned and the clean half was not, so dropping
    `brief_file_path` from `_remove_worker_files` left the suite green -- and a
    name reused after `fleet clean` inherits the dead worker's brief, which a
    bare respawn then dispatches."""

    def test_removing_a_worker_removes_its_brief(self, project, monkeypatch):
        sid = spawn("w1", project, BRIEF, monkeypatch)
        assert fleet.brief_file_path("w1").exists()
        removed = fleet._remove_worker_files("w1", sid, [])
        assert fleet.brief_file_path("w1") in removed, (
            f"the brief was not swept: {[p.name for p in removed]}")
        assert not fleet.brief_file_path("w1").exists()


class TestNoDispatchDestroysTheBrief:
    """The universal half: a `--resume` steer legitimately composes a body with
    no task in it (F6 -- the message rides the mailbox, and the resumed session
    already holds the brief). What it may NOT do is take the brief down with
    it. Before wave 35 it did, and `archive` then filed the resulting mail stub
    as the worker's `task.md`."""

    def _brief_bytes(self, name):
        return fleet.brief_file_path(name).read_bytes()

    def test_an_idle_send_leaves_the_brief_untouched(self, project, monkeypatch):
        old_sid = spawn("w1", project, BRIEF, monkeypatch)
        before = self._brief_bytes("w1")
        idle_send("w1", "check the logs", monkeypatch, old_sid=old_sid)
        assert self._brief_bytes("w1") == before

    def test_a_limit_resume_leaves_the_brief_untouched(self, project, monkeypatch):
        sid = spawn("w1", project, BRIEF, monkeypatch)
        before = self._brief_bytes("w1")
        resume_limited("w1", project, sid, monkeypatch)
        assert self._brief_bytes("w1") == before

    def test_a_respawn_leaves_the_brief_untouched(self, project, monkeypatch):
        spawn("w1", project, BRIEF, monkeypatch)
        before = self._brief_bytes("w1")
        respawn("w1", monkeypatch)
        assert self._brief_bytes("w1") == before

    def test_archive_files_the_brief_not_just_the_last_payload(
            self, project, monkeypatch):
        """What `fleet archive` preserves as the answer to "what was this
        worker asked to do". Steered first, because that is the state in which
        the archived `task.md` is a mail stub."""
        old_sid = spawn("w1", project, BRIEF, monkeypatch)
        idle_send("w1", "check the logs", monkeypatch, old_sid=old_sid)
        pairs = dict((dest, src) for src, dest in
                     fleet._archive_file_pairs("w1", old_sid, []))
        assert "brief.md" in pairs, (
            "archive does not carry the brief -- the archived `task.md` is "
            "whatever the last dispatch composed")
        assert SENTINEL in pairs["brief.md"].read_text(encoding="utf-8")


class TestTheRemnantIsNeverDispatched:
    """`new_worker_record` still caps `task` at 200 chars, on purpose: the
    registry is read by every view and the statusline, and a second full copy
    of every brief there buys nothing the brief store does not. What changes is
    that the remnant is PROVENANCE and never a dispatch input again."""

    def test_a_poisoned_snapshot_never_reaches_the_prompt(self, project, monkeypatch):
        """Drives the D1-shaped regression directly: if any path goes back to
        reading `rec["task"]` as a brief, the poison shows up in the body."""
        spawn("w1", project, BRIEF, monkeypatch)
        data = fleet.load_registry()
        data["workers"]["w1"]["task"] = "POISON-REGISTRY-SNAPSHOT"
        fleet.save_registry(data)
        respawn("w1", monkeypatch)
        body = delivered("w1")
        assert "POISON-REGISTRY-SNAPSHOT" not in body
        assert SENTINEL in body

    def test_respawn_refuses_when_only_a_capped_remnant_survives(
            self, project, monkeypatch):
        """A truncated brief must FAIL LOUDLY, not dispatch silently. No brief
        on file, no recoverable payload, and a snapshot sitting at the cap: the
        only honest answer is a refusal that names the remedy."""
        spawn("w1", project, BRIEF, monkeypatch)
        fleet.brief_file_path("w1").unlink()
        fleet.task_file_path("w1").unlink()
        with pytest.raises(fleet.FleetCliError) as exc:
            respawn("w1", monkeypatch)
        assert "--task" in str(exc.value)
        assert "remnant" in str(exc.value)

    def test_a_short_complete_snapshot_is_not_mistaken_for_a_remnant(
            self, project, monkeypatch):
        """The refusal must not fire on a genuinely short task -- a guard that
        refuses a legitimate input is a liveness defect, not a strict guard."""
        short = "do the small thing"
        spawn("w1", project, short, monkeypatch)
        fleet.brief_file_path("w1").unlink()
        fleet.task_file_path("w1").unlink()
        respawn("w1", monkeypatch)
        assert short in delivered("w1")

    def test_a_pre_wave35_worker_recovers_its_brief_from_its_payload(
            self, project, monkeypatch):
        """Migration: every worker alive at the moment this ships has no brief
        file and a capped snapshot. Its payload is still `preamble + task` if
        it has not been steered, and that is recoverable EXACTLY."""
        spawn("w1", project, BRIEF, monkeypatch)
        fleet.brief_file_path("w1").unlink()          # the pre-wave-35 state
        respawn("w1", monkeypatch)
        assert SENTINEL in delivered("w1")
        assert SENTINEL in fleet.brief_file_path("w1").read_text(encoding="utf-8"), (
            "the recovery must be written back, or every later respawn re-pays it")

    def test_recovery_refuses_a_context_payload_rather_than_welding_in_a_digest(
            self, project, monkeypatch):
        """F5. `compose_prompt` inserts `--context` DIGESTS between the preamble
        and the task, so a spawn-time prefix test that stops at the preamble
        still passes and the recovered "brief" starts with a symbol table.
        `read_brief` writes recovery back, so that stale digest would be welded
        into the worker's task for every future respawn -- contamination, not
        truncation, and it survives the very repair that recorded it."""
        indexed = project / "indexed"
        (indexed / "src").mkdir(parents=True)
        (indexed / "src" / "api.py").write_text(
            "ALPHA = 1\n\n\ndef alpha(x):\n    return str(x)\n", encoding="utf-8")
        fleet.index_symbols_dir(indexed).mkdir(parents=True, exist_ok=True)
        fleet.build_index(indexed)

        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _roster((True, []), (True, [_entry(SID_1)])))
        args = SimpleNamespace(name="w1", dir=str(indexed), task=BRIEF,
                               mode="bypass", model=None, max_budget_usd=None,
                               setting_sources=None, token_ceiling=None,
                               category=None, context="src/api.py",
                               yes=True, nonce=None)
        assert fleet.cmd_spawn(args, run=_run_for(SID_1), which=_claude,
                               sleep=lambda s: None, clock=lambda: 0.0) == 0
        payload = delivered("w1")
        assert "L1 ALPHA" in payload, (
            "no digest landed in the payload -- this test is not exercising the "
            "shape it names")

        fleet.brief_file_path("w1").unlink()          # the pre-wave-35 state
        rec = fleet.load_registry()["workers"]["w1"]
        recovered = fleet._recovered_brief("w1", rec)
        assert recovered is None or not recovered.lstrip().startswith("##"), (
            f"the recovered brief begins with a --context digest: "
            f"{recovered[:80]!r}")
        if recovered is not None:
            assert recovered.startswith("# The mission")

    def test_recovery_refuses_a_steer_stub_rather_than_guessing(
            self, project, monkeypatch):
        """The recovery is exact-prefix arithmetic, never a parser. A payload
        whose task slot holds mail is NOT a brief, and guessing at it would
        hand a worker something that is subtly not its task."""
        old_sid = spawn("w1", project, BRIEF, monkeypatch)
        idle_send("w1", "check the logs", monkeypatch, old_sid=old_sid)
        fleet.brief_file_path("w1").unlink()          # force the recovery path
        rec = fleet.load_registry()["workers"]["w1"]
        assert fleet._recovered_brief("w1", rec) is None


# ---------------------------------------------------------------------------
# THE CENSUS -- coverage that a new site cannot slip past
# ---------------------------------------------------------------------------
#
# The resolver is imported, not re-implemented: `test_index_compose` already
# owns it and already pins the geometry that defeated its predecessor (a call
# inside a CLASS METHOD walking past its own method to an approved module-level
# name, which let a line-count-neutral fifth dispatch path ship green). Two
# copies of a census resolver is two chances for one of them to rot.

from test_index_compose import _call_sites, call_counts  # noqa: E402


def _drive_supervisor_body(project, monkeypatch, campaign=BRIEF):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, [_entry(SID_1)])))
    fleet._dispatch_supervisor_body(
        campaign, "bypass", None, run=_run_for(SID_1), which=_claude,
        sleep=lambda s: None, clock=lambda: 0.0)
    return next(iter(fleet.load_registry()["workers"]))


def _driver_spawn(project, monkeypatch):
    spawn("w1", project, BRIEF, monkeypatch)
    return "w1"


def _driver_respawn(project, monkeypatch):
    spawn("w1", project, BRIEF, monkeypatch)
    respawn("w1", monkeypatch)
    return "w1"


def _driver_send(project, monkeypatch):
    old_sid = spawn("w1", project, BRIEF, monkeypatch)
    idle_send("w1", "steer me", monkeypatch, old_sid=old_sid)
    return "w1"


def _driver_resume_limited(project, monkeypatch):
    sid = spawn("w1", project, BRIEF, monkeypatch)
    resume_limited("w1", project, sid, monkeypatch)
    return "w1"


#: Every `dispatch_bg` call site in `bin/fleet.py`, mapped to `(driver, calls)`
#: -- a driver that runs the site END TO END, and how many times that function
#: calls `dispatch_bg`.
#:
#: THREE things have to hold together, and each covers a hole the other two
#: leave (all three were planted and left the full suite GREEN at 3522):
#:   1. the census is derived by AST, so an alias or a whitespace variant is
#:      still seen (`call_counts`);
#:   2. it compares COUNTS, so a second call inside a function already listed
#:      here is seen;
#:   3. each driver PROVES it reached the site it is keyed under, so a driver
#:      repointed at another path stops vouching for this one.
#: Without (3) the table is an allowlist with a citation. This repo has already
#: paid once for a census that decayed into exactly that.
BRIEF_DRIVERS = {
    "cmd_spawn": (_driver_spawn, 1),
    "_cmd_respawn_native": (_driver_respawn, 1),
    "_cmd_send_native": (_driver_send, 1),
    "_resume_one_limited_native": (_driver_resume_limited, 1),
    "_dispatch_supervisor_body": (_drive_supervisor_body, 1),
}


@pytest.fixture
def dispatch_witness(monkeypatch):
    """Record which `bin/fleet.py` function actually called `dispatch_bg`, and
    still run the real one -- its unconditional task-file write is the act
    under test, so a double here would assert against a copy of the defect.

    `co_name`, not `co_qualname`: the interpreter floor is 3.10 and
    `co_qualname` is 3.11+. A class-method dispatch path would therefore be
    witnessed by its bare method name, which is why the census above (which
    DOES resolve qualnames) is the half that catches new shapes."""
    real = fleet.dispatch_bg
    seen = []

    def _witness(*a, **kw):
        seen.append(sys._getframe(1).f_code.co_name)
        return real(*a, **kw)

    monkeypatch.setattr(fleet, "dispatch_bg", _witness)
    return seen


def test_every_dispatch_site_owes_a_brief_driver():
    sites = call_counts("dispatch_bg")
    expected = {name: calls for name, (_driver, calls) in BRIEF_DRIVERS.items()}
    assert sites == expected, (
        f"the dispatch_bg call census changed: {sorted(sites.items())}. Every "
        f"dispatch overwrites `state/tasks/<name>.md`, which is the file the "
        f"worker is told to read and follow -- decide what the new path does "
        f"to the brief, add a driver to BRIEF_DRIVERS, and re-pin this census. "
        f"Fixing only the site that was wrong reproduces the miss at the next "
        f"one; that is exactly how wave 34 happened.")


@pytest.mark.parametrize("site", sorted(BRIEF_DRIVERS), ids=lambda s: s)
def test_each_driver_reaches_the_site_it_is_keyed_under(
        site, project, monkeypatch, dispatch_witness):
    """The half that stops the table being an allowlist. Repointing the `send`
    and `resume-limited` drivers at `_driver_spawn` left 121 tests green: they
    still passed, still "covered" their sites, and exercised neither."""
    BRIEF_DRIVERS[site][0](project, monkeypatch)
    assert site.rpartition(".")[2] in dispatch_witness, (
        f"the driver keyed under {site} dispatched from {dispatch_witness} -- "
        f"it never reached {site}, so every property it appears to prove about "
        f"that path is vacuous")


@pytest.mark.parametrize("site", sorted(BRIEF_DRIVERS), ids=lambda s: s)
def test_no_dispatch_site_leaves_a_brief_it_cannot_read_back(
        site, project, monkeypatch):
    """Driven through every census entry: after the dispatch, the brief on
    file is still the whole brief. Asserted on the LAST LINE, which is what
    makes it mechanism-independent -- a cap, a slice, a marker misparse and an
    off-by-one all lose it, while "the file is big enough" survives them."""
    name = BRIEF_DRIVERS[site][0](project, monkeypatch)
    text = fleet.brief_file_path(name).read_text(encoding="utf-8")
    assert SENTINEL in text, (
        f"{site} left a brief whose last line is gone -- whatever a later "
        f"respawn reads back, it is not what the operator wrote")


def test_the_capped_registry_snapshot_has_no_readers_outside_the_brief_store():
    """THE anti-regression pin for the defect itself. `task[:200]` was read as
    a brief by two call sites -- `_cmd_respawn_native` (the reported one) and
    `_cmd_respawn_supervisor` (invisible from the dispatch census, because it
    rebuilds a supervisor CAMPAIGN). Both are gone. A third would be the same
    defect wearing a new name, so the reader set is pinned, not the fix."""
    readers = _call_sites('.get("task"') | _call_sites('["task"]')
    assert readers <= {"_recovered_brief", "read_brief", "new_worker_record"}, (
        f"a new reader of the capped registry snapshot appeared: "
        f"{sorted(readers)}. That field is PROVENANCE -- 200 chars, cut "
        f"mid-sentence for any real task. Read the brief via `read_brief`, "
        f"which refuses a remnant instead of dispatching one.")
