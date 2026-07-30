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
  re-derived from source on every run, tied by set-equality to the drivers below.
  A new dispatch path cannot be added without owing an end-to-end driver here --
  which is what stops the census degenerating into an allowlist, the failure this
  repo has already paid for once ("the first thing to check about a detector is
  not what it catches but what it excuses").
"""
import re
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


def respawn(name, monkeypatch, sid=SID_2, task=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        _roster((True, []), (True, []), (True, [_entry(sid)])))
    args = SimpleNamespace(name=name, task=task, force=False, yes=True,
                           max_budget_usd=None, setting_sources=None,
                           token_ceiling=None, nonce=None)
    rc = fleet.cmd_respawn(args, run=_run_for(sid), which=_claude,
                           sleep=lambda s: None, clock=lambda: 0.0)
    assert rc == 0
    return sid


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

from test_index_compose import _call_sites  # noqa: E402


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


#: Every `dispatch_bg` call site in `bin/fleet.py`, mapped to a driver that
#: runs it END TO END. The set-equality test below is what makes this a
#: contract rather than a list: a new dispatch path cannot be added without
#: owing a driver here, and a driver that does not preserve the brief fails
#: behaviourally. Neither half alone is coverage.
BRIEF_DRIVERS = {
    "cmd_spawn": _driver_spawn,
    "_cmd_respawn_native": _driver_respawn,
    "_cmd_send_native": _driver_send,
    "_resume_one_limited_native": _driver_resume_limited,
    "_dispatch_supervisor_body": _drive_supervisor_body,
}


def test_every_dispatch_site_owes_a_brief_driver():
    sites = _call_sites("dispatch_bg(", skip_defs=("dispatch_bg",))
    assert sites == set(BRIEF_DRIVERS), (
        f"the set of dispatch_bg call sites changed: {sorted(sites)}. Every "
        f"dispatch overwrites `state/tasks/<name>.md`, which is the file the "
        f"worker is told to read and follow -- decide what the new path does "
        f"to the brief, add a driver to BRIEF_DRIVERS, and re-pin this set. "
        f"Fixing only the site that was wrong reproduces the miss at the next "
        f"one; that is exactly how wave 34 happened.")


@pytest.mark.parametrize("site", sorted(BRIEF_DRIVERS), ids=lambda s: s)
def test_no_dispatch_site_leaves_a_brief_it_cannot_read_back(
        site, project, monkeypatch):
    """Driven through every census entry: after the dispatch, the brief on
    file is still the whole brief. Asserted on the LAST LINE, which is what
    makes it mechanism-independent -- a cap, a slice, a marker misparse and an
    off-by-one all lose it, while "the file is big enough" survives them."""
    name = BRIEF_DRIVERS[site](project, monkeypatch)
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
