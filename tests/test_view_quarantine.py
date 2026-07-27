"""The quarantine rename stops firing from paths that were never entitled to it.

WHAT WAS MEASURED, 2026-07-27, in an isolated `FLEET_HOME` with an invalid-JSON
`state/fleet.json` -- re-driven for this task rather than taken from the report:

    fleet status                    | rc=1 | fleet.json=RENAMED-ASIDE
    fleet status --json --stale-ok  | rc=0 | fleet.json=SURVIVES
    fleet peek w                    | rc=1 | fleet.json=RENAMED-ASIDE
    fleet result w                  | rc=1 | fleet.json=RENAMED-ASIDE
    fleet doctor                    | rc=1 | fleet.json=RENAMED-ASIDE

Four of the five renamed the operator's registry aside. `docs/specs/terminal-surface.md`
D4 and root `CLAUDE.md` have both said, for days, that the view surface *"never
quarantines a corrupt registry"*. **Prose is proven not to be a guard here**, which
is why every property below is a test and why `tests/test_load_registry_callers.py`
gained a named pin for the view surface alongside its existing identity-surface one.

TWO SEPARATE REASONS THIS MATTERS, and they are not the same reason:

  1. **Operator evidence.** The rename destroys the file the operator was about to
     look at, from a command whose whole job is to look at things. `fleet doctor`
     is the extreme case: it quarantined what it was invoked to diagnose.
  2. **Privilege escalation.** The rename converts *corrupt* into *absent*, and the
     §9 legacy-claim upgrade abstains on corrupt but is GRANTED on absent. The
     refusal message at `bin/fleet.py:12640` walked the caller through that door by
     name (*"Repair `state/fleet.json` (see `fleet doctor`)"*), and `fleet doctor`
     was the step that performed it. That message now names `--repair`.

OPERATOR GATE (2026-07-27, `docs/OPERATOR-GATES.md`): *"flag-gated -- diagnose by
default, quarantine behind `--repair`"*. Strictly read-only was REJECTED, because
then no repair path would exist at all and the refusal above would name a command
that no longer repairs. So the rename does not disappear; it moves.

WHAT IS DELIBERATELY NOT HERE. `cmd_status` still takes `fleet.lock` and still
writes. `docs/specs/terminal-surface.md` D2 says verbatim *"`fleet status` (no flag)
remains the authoritative, recomputing command"*, and that spec is the source of
record for this surface. What changed is that its PRE-PROBE read no longer
quarantines, and that the `/fleet:*` templates -- the surface the doctrine actually
names -- now shell out to `fleet status --stale-ok`, which never locked or wrote.
"""
import argparse
import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


CORRUPT = "{ this is not json"

SRC = Path(fleet.__file__).read_text(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
COMMANDS_DIR = REPO / "commands"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME. Never the live fleet -- every command below is one
    of the four that were measured renaming `state/fleet.json` aside."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    (tmp_path / "state" / "worker-settings.json").write_text(
        '{"hooks": {}}', encoding="utf-8")
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


def _corrupt(home):
    fleet.registry_path().write_text(CORRUPT, encoding="utf-8")
    return home / "state" / "fleet.json"


def _rec(**over):
    base = {"session_id": "sid-1", "cwd": "C:/proj", "task": "t",
            "mode": "dontask", "status": "idle", "turns": 1,
            "cost_usd": 0.0, "last_activity": fleet.now_iso(),
            "dispatch_kind": "bg", "retired_sids": []}
    base.update(over)
    return base


def _registry(workers):
    fleet.save_registry({"workers": workers})


def _quarantine_artifacts(home):
    return sorted(p.name for p in (home / "state").glob("fleet.json.corrupt.*"))


def _assert_registry_untouched(home, path):
    """The whole property, in one place: the corrupt file is still there, under
    its own name, with its own bytes, and nothing was renamed aside."""
    assert path.exists(), "state/fleet.json was renamed aside"
    assert path.read_text(encoding="utf-8") == CORRUPT
    assert _quarantine_artifacts(home) == []


def _doctor(args=None, **over):
    """`cmd_doctor` with both subprocess seams stubbed -- the registry
    behaviour is what is under test, not `claude --version`."""
    if args is None:
        args = argparse.Namespace(**dict({"repair": False}, **over))
    return fleet.cmd_doctor(
        args,
        which=lambda _n: None,
        run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )


# ---------------------------------------------------------------------------
# 1. `fleet doctor` is report-only by default (operator gate, 2026-07-27)
# ---------------------------------------------------------------------------

class TestDoctorIsReportOnlyByDefault:

    def test_the_parser_exposes_repair_and_it_defaults_off(self):
        assert fleet.build_parser().parse_args(["doctor"]).repair is False
        assert fleet.build_parser().parse_args(["doctor", "--repair"]).repair is True

    def test_default_doctor_leaves_a_corrupt_registry_exactly_as_it_found_it(
            self, home, capsys):
        """THE HEADLINE. A diagnostic verb that destroys its own evidence is the
        operator-facing surprise the gate was raised about."""
        path = _corrupt(home)
        rc = _doctor()
        capsys.readouterr()
        assert rc != 0
        _assert_registry_untouched(home, path)

    def test_default_doctor_reports_the_corruption_and_names_the_flag(
            self, home, capsys):
        """Reporting it is not optional. A doctor that silently skipped a
        registry it could not read would be worse than one that quarantined,
        and the row has to say which verb repairs it."""
        _corrupt(home)
        _doctor()
        out = capsys.readouterr().out
        assert "[FAIL] registry:" in out
        assert "fleet doctor --repair" in out

    def test_the_row_names_the_flag_exactly_ONCE(self, home, capsys):
        """First draft named it twice in one sentence -- once from the loader's
        generic `REGISTRY_REPAIR_HINT` and once from the row's own, richer
        sentence. A message that repeats itself reads like a bug and buries the
        half the operator has not already been told (that every worker-keyed
        check below just ran against an EMPTY registry)."""
        _corrupt(home)
        _doctor()
        row = [ln for ln in capsys.readouterr().out.splitlines()
               if ln.startswith("[FAIL] registry:")]
        assert len(row) == 1, row
        assert row[0].count("fleet doctor --repair") == 1, row[0]
        assert "EMPTY registry" in row[0]

    def test_default_doctor_still_runs_every_other_check(self, home, capsys):
        """The corrupt registry no longer ABORTS the run. Before this change
        `load_registry` raised straight out of `cmd_doctor` into `main`, so the
        operator got one `registry error:` line and not a single check."""
        _corrupt(home)
        _doctor()
        out = capsys.readouterr().out
        for row in ("claude-on-path", "pin-version", "hook-errors",
                    "supervisor-claim", "tzdata"):
            assert row in out, f"{row} did not run behind the corrupt registry"

    def test_default_doctor_appends_no_registry_corrupt_event(self, home, capsys):
        """`_quarantine_registry` writes the event as well as the rename. A
        report-only doctor writes neither -- `state/events.jsonl` is operator
        evidence too."""
        _corrupt(home)
        _doctor()
        capsys.readouterr()
        assert not fleet.events_path().exists()

    def test_a_healthy_registry_passes_the_row(self, home, capsys):
        _registry({"w1": _rec()})
        _doctor()
        out = capsys.readouterr().out
        assert "[PASS] registry:" in out

    def test_the_registry_row_is_checked_FIRST(self, home, capsys):
        """Registered ahead of every other check on purpose: when it fails,
        every worker-keyed check below it is running against an empty worker
        map and its [PASS] means only "nothing to check"."""
        _registry({"w1": _rec()})
        _doctor()
        out = capsys.readouterr().out
        assert out.index("registry:") < out.index("claude-on-path")


class TestRepairIsTheOnlyQuarantine:

    def test_repair_quarantines_the_corrupt_registry(self, home, capsys):
        path = _corrupt(home)
        rc = _doctor(repair=True)
        capsys.readouterr()
        assert rc != 0
        assert not path.exists(), "`--repair` did not rename the corrupt registry aside"
        artifacts = _quarantine_artifacts(home)
        assert len(artifacts) == 1, artifacts
        assert artifacts[0].startswith("fleet.json.corrupt.")

    def test_repair_says_it_quarantined_rather_than_telling_you_to(self, home, capsys):
        _corrupt(home)
        _doctor(repair=True)
        out = capsys.readouterr().out
        assert "[FAIL] registry:" in out
        assert "quarantined" in out
        # It already did the thing; pointing at the flag again would be a loop.
        assert "rerun as `fleet doctor --repair`" not in out

    def test_repair_appends_the_registry_corrupt_event(self, home, capsys):
        _corrupt(home)
        _doctor(repair=True)
        capsys.readouterr()
        kinds = [json.loads(line)["kind"]
                 for line in fleet.events_path().read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        assert "registry_corrupt" in kinds

    def test_repair_on_a_HEALTHY_registry_changes_nothing(self, home, capsys):
        _registry({"w1": _rec()})
        before = fleet.registry_path().read_text(encoding="utf-8")
        _doctor(repair=True)
        capsys.readouterr()
        assert fleet.registry_path().read_text(encoding="utf-8") == before
        assert _quarantine_artifacts(home) == []

    def test_a_doctor_args_object_without_the_attribute_does_not_repair(
            self, home, capsys):
        """Several suites call `cmd_doctor(SimpleNamespace())` with no `repair`
        attribute at all. The default for an absent attribute must be the SAFE
        one -- an `args.repair` that raised, or a `getattr(..., True)`, would
        make report-only depend on how the caller built its namespace."""
        path = _corrupt(home)
        _doctor(args=SimpleNamespace())
        capsys.readouterr()
        _assert_registry_untouched(home, path)


# ---------------------------------------------------------------------------
# 2. The refusal names the FLAG, not the command that used to open the door
# ---------------------------------------------------------------------------

class TestTheSection9RefusalNamesTheRepairFlag:
    """`bin/fleet.py:12640`. As written it named `fleet doctor`, which (a) will
    now do nothing by default, and (b) previously performed step 2 of the
    escalation -- corrupt refuses, the rename makes it absent, absent grants the
    upgrade. Driven end-to-end rather than grepped out of the source: a message
    nothing executes is a message nothing keeps honest."""

    def _legacy(self, sid):
        fleet.write_incarnation({
            "incarnation_id": "inc-legacy", "session_id": sid,
            "lineage_id": "lin-x", "claimed_at": fleet.now_iso(),
            "heartbeat_at": fleet.now_iso()})

    def _ckpt(self, sid):
        return fleet.cmd_sup_checkpoint(SimpleNamespace(
            body="did a thing", kind="CHECKPOINT", sid=sid, nonce=None))

    def test_the_refusal_points_at_the_flag(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        self._legacy("sid-w1")
        _corrupt(home)
        with pytest.raises(fleet.FleetCliError) as exc:
            self._ckpt("sid-w1")
        assert "fleet doctor --repair" in str(exc.value)

    def test_the_refusal_no_longer_names_the_bare_verb(self, home, monkeypatch):
        """The bare spelling is what made the message a walkthrough. Asserted
        as a NEGATIVE on the exact substring, so restoring the old text is red
        even if the new text is appended alongside it."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        self._legacy("sid-w1")
        _corrupt(home)
        with pytest.raises(fleet.FleetCliError) as exc:
            self._ckpt("sid-w1")
        assert "see `fleet doctor`)" not in str(exc.value)

    def test_the_refused_verb_still_leaves_the_registry_alone(self, home, monkeypatch):
        """The other half, and the one the escalation actually turns on: the
        refusal must not itself convert corrupt into absent."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-w1")
        self._legacy("sid-w1")
        path = _corrupt(home)
        with pytest.raises(fleet.FleetCliError):
            self._ckpt("sid-w1")
        _assert_registry_untouched(home, path)


# ---------------------------------------------------------------------------
# 3. The three views: report the corruption, exit, touch nothing
# ---------------------------------------------------------------------------

class TestTheViewsDoNotQuarantine:
    """`cmd_status` (bare), `cmd_peek` and `cmd_result`. Each raises
    `RegistryCorruptError`, which `main` already grades to rc 1 with a
    `fleet: registry error:` line -- so "report the corruption and exit
    cleanly" needs no new plumbing, only a loader that does not rename."""

    def test_status_leaves_a_corrupt_registry_where_it_found_it(self, home):
        path = _corrupt(home)
        args = fleet.build_parser().parse_args(["status"])
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_status(args)
        _assert_registry_untouched(home, path)

    def test_peek_leaves_a_corrupt_registry_where_it_found_it(self, home):
        path = _corrupt(home)
        args = fleet.build_parser().parse_args(["peek", "w1"])
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_peek(args)
        _assert_registry_untouched(home, path)

    def test_result_leaves_a_corrupt_registry_where_it_found_it(self, home):
        path = _corrupt(home)
        args = fleet.build_parser().parse_args(["result", "w1"])
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_result(args)
        _assert_registry_untouched(home, path)

    @pytest.mark.parametrize("argv", [["status"], ["peek", "w1"], ["result", "w1"]])
    def test_the_view_names_the_repair_flag_through_main(self, home, capsys, argv):
        """End to end, the way the operator meets it: rc 1, a named message,
        the file still on disk. The message must point at the one verb that
        now repairs -- otherwise the operator is told a registry is broken and
        given nothing to do about it."""
        path = _corrupt(home)
        rc = fleet.main(argv)
        err = capsys.readouterr().err
        assert rc == 1
        assert "registry" in err.lower()
        assert "fleet doctor --repair" in err
        _assert_registry_untouched(home, path)

    def test_a_view_over_a_corrupt_registry_appends_no_event(self, home):
        path = _corrupt(home)
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_peek(fleet.build_parser().parse_args(["peek", "w1"]))
        assert not fleet.events_path().exists()
        _assert_registry_untouched(home, path)

    def test_resolving_the_logical_supervisor_name_does_not_quarantine(self, home):
        """THE HOLE THE BRIEF DOES NOT NAME. `_resolve_worker_target` is the
        first thing all three views call, and it called `load_registry` too. It
        short-circuits for ordinary names (`bin/fleet.py:2414`), so the measured
        table -- driven with `fleet peek w` -- never reached it; `fleet peek
        supervisor` did, and quarantined there instead. Converting only the
        three verbs would have left the property false for exactly the name the
        supervisor tier types."""
        path = _corrupt(home)
        fleet.write_incarnation({
            "incarnation_id": "inc-x", "session_id": "sid-holder",
            "state": "active", "lineage_id": "lin-x",
            "heartbeat_at": fleet.now_iso()})
        with pytest.raises((fleet.FleetCliError, fleet.RegistryCorruptError)):
            fleet._resolve_worker_target(fleet.SUPERVISOR_BODY_NAME)
        _assert_registry_untouched(home, path)


class TestPeekAndResultTakeNoLock:
    """D1/D4. `peek` and `result` read ONE field (`session_id`) and then print
    from files. Taking `fleet.lock` to do that contends with a live respawn
    mid-rotation (invariant 6) for no read the lock protects -- `save_registry`
    is atomic, so a lock-free read of a whole file is already consistent."""

    @pytest.fixture
    def lock_is_poison(self, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("this path took fleet.lock")
        monkeypatch.setattr(fleet, "fleet_lock", _boom)

    def test_peek_does_not_take_the_lock(self, home, lock_is_poison, capsys):
        _registry({"w1": _rec(session_id=None)})
        fleet.cmd_peek(fleet.build_parser().parse_args(["peek", "w1"]))
        capsys.readouterr()

    def test_result_does_not_take_the_lock(self, home, lock_is_poison, capsys):
        _registry({"w1": _rec(session_id=None)})
        assert fleet.cmd_result(fleet.build_parser().parse_args(["result", "w1"])) == 1
        capsys.readouterr()

    def test_peek_still_refuses_an_unknown_worker(self, home, lock_is_poison):
        _registry({"w1": _rec()})
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_peek(fleet.build_parser().parse_args(["peek", "nope"]))
        assert "unknown worker" in str(exc.value)

    def test_result_still_refuses_an_unknown_worker(self, home, lock_is_poison):
        _registry({"w1": _rec()})
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.cmd_result(fleet.build_parser().parse_args(["result", "nope"]))
        assert "unknown worker" in str(exc.value)

    def test_a_missing_registry_is_still_unknown_worker_not_a_crash(self, home):
        """`read_registry_no_repair` keeps `load_registry`'s missing-file
        contract (`{"workers": {}}`), so a fresh install refuses by name
        instead of raising a KeyError out of a view."""
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_peek(fleet.build_parser().parse_args(["peek", "w1"]))


class TestReadRegistryNoRepair:
    """The loader itself. It is `load_registry` minus the rename, and the two
    must never disagree about what "corrupt" MEANS -- a validator that drifts
    would let a shape `load_registry` quarantines sail through a view."""

    def test_missing_file_is_an_empty_registry(self, home):
        assert fleet.read_registry_no_repair() == {"workers": {}}

    def test_a_healthy_registry_round_trips_whole(self, home):
        _registry({"w1": _rec()})
        assert fleet.read_registry_no_repair()["workers"]["w1"]["session_id"] == "sid-1"

    def test_unknown_top_level_keys_are_preserved(self, home):
        """It must be a FULL loader, not `_read_registry_readonly`'s
        `{"workers": ...}` projection. `cmd_status` re-reads under the lock and
        calls `save_registry(data)`; a loader that silently dropped sibling
        keys would delete them on the next status."""
        fleet.registry_path().write_text(
            json.dumps({"workers": {}, "schema_version": 7}), encoding="utf-8")
        assert fleet.read_registry_no_repair().get("schema_version") == 7

    @pytest.mark.parametrize("text", [
        "{ this is not json",
        "[]",
        '{"workers": [1, 2]}',
        '{"workers": {"w1": "not-a-dict"}}',
    ])
    def test_every_shape_load_registry_quarantines_is_refused_here_too(
            self, home, text):
        """The agreement check, driven against BOTH loaders on the same bytes
        rather than asserted in prose."""
        fleet.registry_path().write_text(text, encoding="utf-8")
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.read_registry_no_repair()
        # ... and the corrupt file is STILL THERE for `load_registry` to find.
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()
        assert len(_quarantine_artifacts(home)) == 1

    def test_it_names_the_repair_flag(self, home):
        _corrupt(home)
        with pytest.raises(fleet.RegistryCorruptError) as exc:
            fleet.read_registry_no_repair()
        assert "fleet doctor --repair" in str(exc.value)


# ---------------------------------------------------------------------------
# 4. Static pins -- prose has already been proven not to be a guard here
# ---------------------------------------------------------------------------

def _calls_in(func_name: str, callee: str) -> list:
    """Line numbers of every `callee(...)` call inside top-level `func_name`."""
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return sorted({n.lineno for n in ast.walk(node)
                           if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name)
                           and n.func.id == callee})
    raise AssertionError(f"{func_name} is not a top-level function in bin/fleet.py")


class TestTheViewSurfaceCannotRegainTheLock:
    """`tests/test_load_registry_callers.py` pins the `load_registry` half by
    name. This pins the OTHER half of D1 for the two verbs that genuinely have
    no business locking."""

    def test_the_matcher_finds_a_real_lock_call(self):
        """Seed check. `_calls_in` returning [] for everything would make both
        assertions below pass vacuously -- which is the exact failure mode
        `tools/verify_receipts.py --self-test` exists for."""
        assert _calls_in("cmd_kill", "fleet_lock"), (
            "the matcher found no `fleet_lock` call in `cmd_kill` -- it rotted, "
            "and the assertions below were about to pass vacuously")

    @pytest.mark.parametrize("verb", ["cmd_peek", "cmd_result"])
    def test_the_view_takes_no_fleet_lock(self, verb):
        assert _calls_in(verb, "fleet_lock") == [], (
            f"{verb} takes `fleet.lock` again. It reads ONE field and then "
            f"prints from files; locking there contends with a live respawn "
            f"mid-rotation (invariant 6) for a read the lock does not protect.")


# ---------------------------------------------------------------------------
# 5. D1's "never probe a PID" clause, in its POST-PIVOT spelling
# ---------------------------------------------------------------------------

@pytest.fixture
def spawn_log(monkeypatch):
    """Every process spawn, counted at the ONE seam that cannot be evaded.

    `subprocess.run` IS THE WRONG SEAM, and a test built on it passes
    VACUOUSLY -- measured, not assumed. `_fetch_agents_roster(which=shutil.
    which, run=subprocess.run)` binds that default AT DEF TIME, so after
    `monkeypatch.setattr(fleet.subprocess, "run", spy)` the check
    `_fetch_agents_roster.__defaults__[1] is subprocess.run` is still True and
    the spy sees nothing. A "no subprocess" assertion built there would be
    green against a view that spawns on every call.

    `subprocess.run` looks `Popen` up in its OWN module globals at CALL time,
    so patching the class catches the roster spawn no matter how the default
    was bound -- and catches anything a future refactor reaches for, which a
    per-helper patch would not."""
    seen = []
    real = fleet.subprocess.Popen

    class _Spy(real):
        def __init__(self, args, *a, **k):
            seen.append(list(args) if isinstance(args, (list, tuple)) else [args])
            raise OSError("spawn blocked: this surface is not allowed to spawn")

    monkeypatch.setattr(fleet.subprocess, "Popen", _Spy)
    return seen


class TestTheViewSurfaceSpawnsNoSubprocess:
    """D1's four clauses are: never take `fleet.lock`, never probe a PID, never
    write, never quarantine. The PID probe is GONE -- the native pivot deleted
    it -- so the clause reads as satisfied and a doc-only check would tick it.

    IT HAS A LIVE SUCCESSOR. `cmd_status` spawns `claude agents --json --all`
    (`_fetch_agents_roster`, ~1.7 s measured on this box, 30 s timeout). Same
    D1 violation, post-pivot spelling: a view doing expensive,
    environment-touching work on a path that refires after every assistant
    message. The clause survived the pivot unnoticed because its ORIGINAL
    WORDING went vacuously true.

    So the assertion is written against the PROPERTY (no spawn), never against
    the obsolete mechanism (no `get_process_info`)."""

    def test_the_seed_bare_status_DOES_spawn_the_roster(self, home, capsys, spawn_log):
        """The seed, and it is the whole reason the rest is not vacuous. If the
        counter intercepted nothing, every zero below would be a lie. It also
        records WHICH subprocess, so a future roster that spawns something else
        does not silently satisfy this."""
        _registry({"w1": _rec(status="working")})
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]))
        capsys.readouterr()
        assert len(spawn_log) == 1, spawn_log
        assert spawn_log[0][1:] == ["agents", "--json", "--all"], spawn_log[0]

    @pytest.mark.parametrize("label,argv", [
        ("/fleet:status + /fleet:overview", ["status", "--stale-ok"]),
        ("statusline (--json --stale-ok)", ["status", "--json", "--stale-ok"]),
        ("/fleet:peek", ["peek", "w1"]),
        ("/fleet:result", ["result", "w1"]),
    ])
    def test_the_view_surface_spawns_nothing(self, home, capsys, spawn_log,
                                             label, argv):
        _registry({"w1": _rec(status="working", session_id=None)})
        try:
            fleet.main(argv)
        finally:
            capsys.readouterr()
        assert spawn_log == [], f"{label} spawned {spawn_log}"

    def test_status_snapshot_itself_spawns_nothing(self, home, spawn_log):
        """The statusline IMPORTS this rather than shelling out, so it is the
        single derivation four surfaces share -- and the one surface D4's
        sentence was always true of."""
        _registry({"w1": _rec(status="working")})
        fleet.status_snapshot()
        assert spawn_log == []

    def test_no_spawn_helper_is_even_REACHABLE_from_a_view(self):
        """The static half. The behavioural tests above prove nothing spawned
        on the paths they happened to walk; this proves there is no path at
        all, including arms a fixture did not reach (an attached worker, a
        limited park, an archived record)."""
        tree = ast.parse(SRC)
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        spawny = {"_fetch_agents_roster", "resolve_claude_executable"}
        for entry in ("cmd_peek", "cmd_result", "status_snapshot"):
            seen, stack = set(), [entry]
            while stack:
                fn = stack.pop()
                if fn in seen or fn not in funcs:
                    continue
                seen.add(fn)
                stack.extend(c.func.id for c in ast.walk(funcs[fn])
                            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name))
            assert not (seen & spawny), (
                f"{entry} can reach {sorted(seen & spawny)} -- a view must not "
                f"spawn a subprocess (D1). The clause's original wording ('never "
                f"probe a PID') went vacuous at the native pivot; the roster "
                f"subprocess is its live successor.")
            direct = {f for f in seen for c in ast.walk(funcs[f])
                      if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                      and getattr(c.func.value, "id", "") == "subprocess"}
            assert direct == set(), f"{entry} reaches subprocess.* via {sorted(direct)}"


class TestTheRosterSpawnIsLoadBearingForBareStatus:
    """WHY `cmd_status` KEEPS ITS SPAWN, measured rather than argued -- this is
    the evidence behind the scoped report, and it is a test so the claim cannot
    quietly stop being true.

    Take the roster away and `fleet status` does not degrade a little: G9's
    epoch freeze fires, NO record is recomputed, NOTHING is written, and the
    rows printed are last-committed. That is `--stale-ok` exactly. So removing
    the spawn does not make the authoritative verb cheaper -- it DELETES the
    authoritative verb, leaving two spellings of the view. `docs/specs/
    terminal-surface.md` D2 (*"`fleet status` (no flag) remains the
    authoritative, recomputing command"*) is the source of record and forbids
    that, so the spawn stays where it is and the VIEW surface is what moved off
    it (see the class above: `--stale-ok`, peek, result and the snapshot all
    spawn zero)."""

    @pytest.mark.parametrize("roster", [(False, []), (True, [])])
    def test_without_a_roster_status_freezes_and_writes_nothing(
            self, home, capsys, monkeypatch, roster):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda *a, **k: roster)
        _registry({"w1": _rec(status="working")})
        before = fleet.registry_path().read_text(encoding="utf-8")
        assert fleet.cmd_status(fleet.build_parser().parse_args(["status"])) == 0
        out = capsys.readouterr().out
        assert "EPOCH: roster suspicious" in out
        assert "verdicts frozen" in out
        # The row shown is the last-committed one, and the registry is untouched.
        assert "working" in out
        assert fleet.registry_path().read_text(encoding="utf-8") == before

    def test_the_frozen_output_carries_the_same_status_as_stale_ok(
            self, home, capsys, monkeypatch):
        """The equivalence stated as a measurement: roster-less bare `status`
        and `--stale-ok` report the same status for the same record. If a
        future change makes the recompute survive a missing roster, this goes
        red and the scoped report needs redriving."""
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda *a, **k: (False, []))
        _registry({"w1": _rec(status="working")})
        fleet.cmd_status(fleet.build_parser().parse_args(["status"]))
        bare = capsys.readouterr().out
        fleet.cmd_status(fleet.build_parser().parse_args(["status", "--stale-ok"]))
        stale = capsys.readouterr().out
        assert fleet.status_snapshot()["workers"][0]["status"] == "working"
        for text in (bare, stale):
            assert "working" in text


class TestTheSlashCommandsUseTheViewPath:
    """D3 names `/fleet:status` and `/fleet:overview` as READ-ONLY inline-exec
    commands, and they shelled out to the bare verb -- which recomputes, takes
    the lock, and writes. The doctrine sentence names `/fleet:*` specifically,
    so this is the surface it was always about."""

    def _body(self, name):
        return (COMMANDS_DIR / f"{name}.md").read_text(encoding="utf-8").split("---\n", 2)[2]

    @pytest.mark.parametrize("name", ["status", "overview"])
    def test_the_inline_status_call_is_the_stale_ok_read(self, name):
        body = self._body(name)
        assert "!`fleet status --stale-ok`" in body, (
            f"commands/{name}.md must inline the probe-free read path; bare "
            f"`fleet status` is the authoritative RECOMPUTING verb (D2) and "
            f"takes `fleet.lock`")

    def test_the_grant_still_matches(self):
        """`Bash(fleet status:*)` must still cover the flagged spelling --
        a lint that changed the body and broke the grant would make the
        command prompt for permission on a read-only view."""
        for name in ("status", "overview"):
            text = (COMMANDS_DIR / f"{name}.md").read_text(encoding="utf-8")
            assert "Bash(fleet status:*)" in text.split("---\n", 2)[1]

    def test_no_read_only_command_inline_execs_repair(self):
        """`/fleet:doctor` and `/fleet:overview` inline-exec their command with
        no permission prompt (D3). Neither may EXECUTE `--repair`: the rename is
        irreversible-by-view and the gate put it behind an explicit flag
        precisely so a human types it.

        Scoped to the inline-exec spans, not the whole body -- and that scoping
        is the point rather than a convenience. `commands/doctor.md` SHOULD name
        `fleet doctor --repair` in prose (it is the remedy the model is meant to
        report), and a lint that banned the string outright would have forced
        the file to stop telling the operator what fixes their registry."""
        for name in ("doctor", "overview", "status", "peek", "result"):
            spans = re.findall(r"!`([^`]*)`", self._body(name))
            assert spans, f"commands/{name}.md inline-execs nothing"
            for span in spans:
                assert "--repair" not in span, (
                    f"commands/{name}.md inline-execs `{span}` -- D3's whole "
                    f"point is that inline exec has no permission prompt")

    def test_the_seed_a_planted_repair_span_is_caught(self):
        """The lint above is a negative assertion over a regex, which is the
        shape that passes vacuously when the regex rots. Plant the thing it
        exists to catch and prove the matcher still sees it."""
        spans = re.findall(r"!`([^`]*)`", "\n!`fleet doctor --repair`\n")
        assert spans == ["fleet doctor --repair"]
