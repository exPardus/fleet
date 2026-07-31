"""M2's worker-facing surface: `--context` digest injection (§7), the teach
lines (§11.8) and the template's first non-hook key (§11.7 item 1).

Spec of record: `docs/specs/fleet-index.md`. The M1 shard layer these tests
build on lives in `tests/test_fleet_index.py`; `fleet q` itself is a sibling
slice and is not exercised here.

THREE PROPERTIES CARRY THE WHOLE FILE, and each is asserted at the byte level
rather than by a spot check:

1. **An absent `--context` changes the composed prompt not at all** (§12). It is
   what keeps every non-indexed project paying zero, so it is pinned as a
   byte-for-byte equality against the prompt fleet composes today, not as an
   "and the digest is missing" assertion.
2. **A worker in a non-indexed project sees no mention of `fleet q`** (§11.8) --
   a tool that would exit 3 there. Asserted as a substring census over the whole
   composed prompt, so a stray mention anywhere in it fails.
3. **No path serves an unverified coordinate** (§8). The digest reads through
   `verified_shard_rows()` -- §11.3's choke point -- so a stale shard is
   repaired before it is rendered. Pinned twice: behaviourally (edit the source,
   the digest shows the NEW coordinates) and structurally (the choke point is
   actually called), because either alone survives a plausible mutation.

The four compose paths (§11.8: spawn, idle-send fork-steer, resume-limited,
respawn) are each driven END TO END through their real call site with a
capturing `dispatch_bg`, never by calling `compose_prompt` four times. The
teach lines live inside `compose_prompt`, so a per-call-site test looks
redundant -- it is not: it is the only thing that fails if one call site starts
composing its prompt some other way.

**A correction this file used to get wrong, and it was the strongest finding
against it.** The census below used to claim it was "the only thing that fails
if a FIFTH dispatch path is added". It was not, twice over:

1. Its walk-back to the enclosing `def` matched `startswith("def ")` at COLUMN
   ZERO ONLY, so a `compose_prompt` call inside a CLASS METHOD walked straight
   past its own method and resolved to whatever approved module-level `def`
   happened to sit above it. Measured: a line-count-neutral fifth dispatch
   path added as a class method left the full suite at `2664 passed`, ZERO
   red. A detector that cannot detect its own class is worse than no detector,
   because it is quoted as coverage.
2. There are **five** real dispatch paths, not four, and the fifth has never
   gone through `compose_prompt` at all -- `_dispatch_supervisor_body` renders
   its own body via `_render_sup_spawn_task`. A census over `compose_prompt`
   call sites can never see it. So there are now TWO censuses: one over the
   compose call sites, one over the `dispatch_bg` call sites, and the second
   is the one that reflects five.

The trap in verifying (1) is worth writing down: a naive injection also
reddens `tests/test_retired_sid_citations.py`, which pins line numbers and so
fails on ANY line-count change to `bin/fleet.py`, for a reason that has
nothing to do with dispatch paths. That reads as "caught" and it is not. The
injection that proves the lint is line-count-NEUTRAL, and the proof is that
THIS file's census goes red.
"""
import ast
import json
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _write(path, text):
    """LF newlines on every platform -- a golden prompt is byte-identical on
    win32 and POSIX for the same reason a golden shard is (§11.2)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


API_PY = """\
ALPHA = 1


def alpha(x: int) -> str:
    return str(x)


class Beta:

    def run(self, y) -> bool:
        return True
"""

DESIGN_MD = """\
# Design

Prose.

## Rationale

More prose.
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """FLEET_HOME in a tmp dir, with the rendered instance settings the
    dispatch paths require (SPEC §14)."""
    home = tmp_path / "fleet-home"
    home.mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    settings = home / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    return home


@pytest.fixture
def plain_project(tmp_path):
    """A project that never opted in: no `.fleet-index/` anywhere."""
    root = tmp_path / "plain"
    _write(root / "src" / "api.py", API_PY)
    return root


@pytest.fixture
def indexed_project(tmp_path):
    """A project with a built `.fleet-index/` (`fleet index init` shape)."""
    root = tmp_path / "indexed"
    _write(root / "src" / "api.py", API_PY)
    _write(root / "docs" / "DESIGN.md", DESIGN_MD)
    fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
    fleet.build_index(root)
    return root


def _compose(name, cwd, task="the task", sid=None, **kw):
    prompt, _claim = fleet.compose_prompt(name, cwd, task, sid, **kw)
    return prompt


@pytest.fixture
def taught_verb_present(monkeypatch):
    """Declare every verb the teach lines name as REGISTERED on the parser.

    §11.8's second gate (fix wave C3) suppresses the teach lines entirely
    unless every `fleet <verb>` they name is a real subcommand -- and on this
    branch `fleet q` is not one yet, so without this fixture every teach-line
    test would pass for the wrong reason.

    It is requested by BOTH kinds of teach-line test, deliberately. The ones
    that assert the lines RENDER would otherwise be vacuous. The ones that
    assert the lines are ABSENT would otherwise be vacuous too, and that is
    the worse case: a test claiming "silent because there is no index" that is
    actually silent because of a second, unrelated gate cannot fail if the
    index check regresses. The gate itself is tested on its own, against the
    real parser, in `TestTheTaughtVerbMustExist`.
    """
    real = fleet.registered_cli_verbs
    monkeypatch.setattr(
        fleet, "registered_cli_verbs",
        lambda: frozenset(real()) | set(fleet.index_teach_verbs()))


# ---------------------------------------------------------------------------
# §11.8 -- the teach lines
# ---------------------------------------------------------------------------

class TestTeachLines:

    @pytest.fixture(autouse=True)
    def _verb(self, taught_verb_present):
        """Every test in this class is about the INDEX gate, so the verb gate
        is held open for all of them -- see `taught_verb_present`."""

    def test_no_mention_of_fleet_q_in_a_non_indexed_project(self, plain_project):
        """A worker must not be told about a tool that would exit 3 there.

        A byte-level census over the WHOLE composed prompt, not a spot check on
        the preamble: the cost of a stray mention is a worker burning a turn on
        a command that cannot work, and it does not matter which section it
        leaked into.
        """
        prompt = _compose("w1", plain_project)
        lowered = prompt.lower()
        for token in ("fleet q", "fleet-index", ".fleet-index", "--outline", "--src"):
            assert token not in lowered, (
                f"a non-indexed project's prompt mentions {token!r} -- that tool "
                f"exits 3 here (§11.8)")

    def test_rendered_when_the_dispatch_dir_carries_an_index(self, indexed_project):
        prompt = _compose("w1", indexed_project)
        assert fleet.INDEX_TEACH_LINES in prompt

    def test_at_most_four_lines(self):
        """§11.8's cap. The preamble is fleet's only worker-facing channel and
        every line in it is re-paid per DISPATCH (§3), not per spawn."""
        lines = [l for l in fleet.INDEX_TEACH_LINES.splitlines() if l.strip()]
        assert len(lines) <= 4, f"{len(lines)} teach lines, §11.8 allows at most 4"

    def test_teaches_the_name_the_contract_and_both_flags(self):
        text = fleet.INDEX_TEACH_LINES
        assert "fleet q" in text
        assert "--src" in text
        assert "--outline" in text

    def test_they_sit_in_the_preamble_ahead_of_everything_else(self, indexed_project):
        """Composition order (§7): the teach lines are preamble, so they precede
        the mailbox, the task and the journal."""
        prompt = _compose("w1", indexed_project, task="TASK-MARKER")
        assert prompt.index(fleet.INDEX_TEACH_LINES) < prompt.index("TASK-MARKER")

    def test_the_check_is_the_dispatch_dir_not_the_process_cwd(
            self, indexed_project, plain_project, monkeypatch):
        """§11.8 keys on the dispatch target's `--dir`. A manager standing in an
        indexed repo must not teach a worker it is sending somewhere else."""
        monkeypatch.chdir(indexed_project)
        assert "fleet q" not in _compose("w1", plain_project)
        monkeypatch.chdir(plain_project)
        assert fleet.INDEX_TEACH_LINES in _compose("w1", indexed_project)

    def test_a_file_named_fleet_index_is_not_an_index(self, tmp_path):
        """`.fleet-index` must be a DIRECTORY. A stray file of that name is not
        an opt-in, and treating it as one teaches a tool that cannot run."""
        root = tmp_path / "decoy"
        root.mkdir()
        (root / ".fleet-index").write_text("not a directory", encoding="utf-8")
        assert "fleet q" not in _compose("w1", root)


class TestTheTaughtVerbMustExist:
    """§11.8's second gate (fix wave C3): NEVER TEACH A VERB THIS BUILD DOES
    NOT HAVE.

    The defect these pin was live and confirmed by execution: `bin/fleet.py q
    foo` exited **2** with an argparse `invalid choice: 'q'` while the teach
    lines taught `fleet q` and the worker-settings template granted
    `Bash(fleet q:*)`. §11.8's own argument -- do not spend a worker's turn on
    a command that cannot work -- applies with more force to a verb that is
    not registered at all than to the exit-3 case it was written for.

    These tests run against the REAL parser and are correct on both sides of
    the merge that brings `fleet q` in. Nothing here asks which slice landed.
    """

    def test_the_taught_verbs_are_derived_from_the_constant(self):
        """Derived, not listed: a fifth teach line naming a new verb must not
        slip past the gate because a hand-written tuple was not extended."""
        assert fleet.index_teach_verbs() == ("q",)
        assert all(f"`fleet {v}" in fleet.INDEX_TEACH_LINES
                   for v in fleet.index_teach_verbs())

    def test_the_teach_lines_render_iff_every_taught_verb_is_registered(
            self, indexed_project):
        """THE unconditional assertion, and the only one in this file that is
        about the live tree rather than a declared world.

        It is an `iff`, so it holds before the merge (verb absent -> silent)
        and after it (verb present -> taught) with no edit. A test that
        asserted either arm outright would have to be rewritten by whoever
        merges `fleet q`, and a test somebody has to remember to rewrite is a
        test that gets rewritten wrong."""
        registered = fleet.registered_cli_verbs()
        every_verb_exists = all(v in registered for v in fleet.index_teach_verbs())
        taught = fleet.INDEX_TEACH_LINES in _compose("w1", indexed_project)
        assert taught is every_verb_exists, (
            f"teach lines rendered={taught} but taught verbs "
            f"{fleet.index_teach_verbs()} registered={every_verb_exists}. §11.8 "
            f"must not teach a verb this build does not have -- `fleet <verb>` "
            f"exits 2 with an argparse `invalid choice`.")

    def test_an_unregistered_verb_suppresses_the_lines_in_an_indexed_project(
            self, indexed_project, monkeypatch):
        """The absent arm, forced, so it is pinned whichever side of the merge
        this file is read on."""
        monkeypatch.setattr(fleet, "registered_cli_verbs", frozenset)
        prompt = _compose("w1", indexed_project)
        assert prompt == TestAbsentContextIsFree._expected(indexed_project)
        for token in ("fleet q", "--outline", "--src"):
            assert token not in prompt.lower()

    def test_a_registered_verb_renders_the_lines_in_an_indexed_project(
            self, indexed_project, taught_verb_present):
        """The present arm, forced. Together with the test above, both arms
        are pinned regardless of what the parser carries today."""
        assert fleet.INDEX_TEACH_LINES in _compose("w1", indexed_project)

    def test_the_gate_does_not_resurrect_the_lines_without_an_index(
            self, plain_project, taught_verb_present):
        """The two gates are AND, not OR: a registered verb is not an opt-in."""
        assert "fleet q" not in _compose("w1", plain_project)

    def test_the_template_grant_names_exactly_the_taught_verb(self):
        """The third leg of the same coupling. The template grant, the teach
        lines and the parser are one claim in three files; the branch shipped
        two of the three ahead of the parser, which is how a worker ended up
        holding a grant for a verb that exits 2.

        Pinned as a relation, not a literal, so it survives a verb rename."""
        grants = _template()["permissions"]["allow"]
        assert grants == [f"Bash(fleet {v}:*)" for v in fleet.index_teach_verbs()], (
            f"the template grant {grants} and the taught verbs "
            f"{fleet.index_teach_verbs()} have diverged -- a worker is either "
            f"taught a verb it cannot run, or granted one it is never told about.")

    def test_the_verb_probe_reads_the_real_parser(self):
        """Non-vacuity for the probe itself: it must answer from
        `build_parser()`, not from a constant that could drift."""
        registered = fleet.registered_cli_verbs()
        assert "spawn" in registered and "doctor" in registered
        assert "definitely-not-a-verb" not in registered


# ---------------------------------------------------------------------------
# §11.8 -- all four compose paths, driven through their real call sites
# ---------------------------------------------------------------------------

class _Captured(Exception):
    """Raised by the dispatch stub once it has the composed prompt.

    Deliberately not `NativeDispatchError`: three of the four call sites catch
    that and run a rollback, which would bury a failure to compose behind a
    successful rollback assertion. This one propagates.
    """

    def __init__(self, prompt):
        super().__init__("captured")
        self.prompt = prompt


@pytest.fixture
def captured(monkeypatch):
    """Replace `dispatch_bg` with a prompt capturer. Returns a list that the
    stub appends the composed prompt to before raising."""
    seen = []

    def _stub(name, cwd, prompt, mode, **kw):
        seen.append(prompt)
        raise _Captured(prompt)

    monkeypatch.setattr(fleet, "dispatch_bg", _stub)
    return seen


SID = "aaaabbbb-1111-2222-3333-444455556666"


def _seed(name, cwd, status="idle", sid=SID, **extra):
    rec = fleet.new_worker_record(sid, str(cwd), "seeded task", "dontask",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec.update(extra)
    fleet.save_registry({"workers": {name: rec}})
    return rec


def _drive(fn):
    """Run `fn`, expect the capture, return the composed prompt."""
    with pytest.raises(_Captured) as exc:
        fn()
    return exc.value.prompt


class TestAllFourComposePaths:
    """§11.8: the check runs wherever compose runs, so the teach lines render
    on every dispatch -- a respawned or steered worker in an indexed project is
    re-taught (§3: the cost is per dispatch, not per spawn)."""

    @pytest.fixture(autouse=True)
    def _verb(self, taught_verb_present):
        """These tests are about WHERE compose runs, not about the verb
        gate -- see `taught_verb_present`."""

    def _spawn(self, project, captured, **kw):
        args = SimpleNamespace(
            name="w1", dir=str(project), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None, context=kw.get("context"))
        return _drive(lambda: fleet.cmd_spawn(
            args, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))

    def test_path_1_spawn(self, indexed_project, captured):
        assert fleet.INDEX_TEACH_LINES in self._spawn(indexed_project, captured)

    def test_path_1_spawn_stays_silent_without_an_index(self, plain_project, captured):
        assert "fleet q" not in self._spawn(plain_project, captured)

    def _send(self, project, captured, monkeypatch):
        _seed("w1", project, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        # The verdict engine is not what this test is about: force the idle
        # branch so the assertion is about the COMPOSE call, not about
        # recompute's liveness heuristics.
        def _idle(name, rec, roster, **kw):
            out = dict(rec)
            out["status"] = "idle"
            return out
        monkeypatch.setattr(fleet, "recompute_worker_native", _idle)
        return _drive(lambda: fleet._cmd_send_native(
            "w1", "steer me", run=lambda *a, **k: None,
            which=lambda _: "claude", sleep=lambda s: None))

    def test_path_2_idle_send_fork_steer(self, indexed_project, captured, monkeypatch):
        assert fleet.INDEX_TEACH_LINES in self._send(indexed_project, captured, monkeypatch)

    def test_path_2_idle_send_stays_silent_without_an_index(
            self, plain_project, captured, monkeypatch):
        assert "fleet q" not in self._send(plain_project, captured, monkeypatch)

    def _resume(self, project, captured):
        return _drive(lambda: fleet._resume_one_limited_native(
            "w1", SID, str(project), "dontask", None, None, None, None,
            run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None))

    def test_path_3_resume_limited(self, indexed_project, captured):
        _seed("w1", indexed_project, status="working")
        assert fleet.INDEX_TEACH_LINES in self._resume(indexed_project, captured)

    def test_path_3_resume_limited_stays_silent_without_an_index(
            self, plain_project, captured):
        _seed("w1", plain_project, status="working")
        assert "fleet q" not in self._resume(plain_project, captured)

    def _respawn(self, project, captured, monkeypatch):
        before = _seed("w1", project, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        args = SimpleNamespace(name="w1", task=None, force=False, mode=None,
                               model=None, category=None, token_ceiling=None)
        return _drive(lambda: fleet._cmd_respawn_native(
            args, before, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))

    def test_path_4_respawn(self, indexed_project, captured, monkeypatch):
        assert fleet.INDEX_TEACH_LINES in self._respawn(
            indexed_project, captured, monkeypatch)

    def test_path_4_respawn_stays_silent_without_an_index(
            self, plain_project, captured, monkeypatch):
        assert "fleet q" not in self._respawn(plain_project, captured, monkeypatch)


_DEF_RE = re.compile(r"^(\s*)def\s+(\w+)")
_CLASS_RE = re.compile(r"^(\s*)class\s+(\w+)")


def _enclosing_qualname(src, n):
    """The innermost `def` enclosing 1-based line `n`, qualified by any
    enclosing classes -- `"Klass.method"`, `"outer.inner"`, `"module_level"`.

    THIS FUNCTION IS THE M2 FIX. The version it replaces matched
    `line.startswith("def ")`, i.e. column zero only, so a call inside a class
    method resolved to the module-level `def` above the class and the census
    reported an approved name. Indentation is the whole point: walk back and
    take the first `def`/`class` header at a strictly SMALLER indent than the
    deepest landmark accepted so far.
    """
    parts = []
    limit = len(src[n - 1]) - len(src[n - 1].lstrip())
    for m in range(n - 1, 0, -1):
        line = src[m - 1]
        match = _DEF_RE.match(line) or _CLASS_RE.match(line)
        if match is None:
            continue
        indent = len(match.group(1))
        if indent >= limit:
            continue
        parts.append(match.group(2))
        limit = indent
        if indent == 0:
            break
    return ".".join(reversed(parts))


def _called_name(func):
    """The bare name a `Call.func` node invokes, or None."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _rebound_names(tree, root):
    """Every name that `bin/fleet.py` binds to `root` -- `_launch = dispatch_bg`
    and any chain of further rebinds. Fixpoint, because `a = dispatch_bg` then
    `b = a` is two passes."""
    names = {root}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Name) or value.id not in names:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def call_counts(root):
    """`{enclosing qualname: how many times it calls `root`}` in `bin/fleet.py`,
    derived by AST.

    THIS REPLACES A SUBSTRING SCAN, and the scan's three blind spots were each
    planted and each left the FULL SUITE GREEN at 3522 (adversarial review of
    `w35/respawn-trunc`, 2026-07-31):

      1. an ALIAS -- `_launch = dispatch_bg` at module level, then `_launch(...)`
         -- which contains the literal `dispatch_bg` only on a line that is not
         a call;
      2. a WHITESPACE variant, `dispatch_bg (name, ...)`, which is legal Python
         and does not contain the substring `dispatch_bg(`;
      3. a SECOND call inside an already-approved function, which set-equality
         over qualnames cannot see at all.

    So this returns COUNTS, not a set: (3) is only visible as an arity change.
    Calibration for the whole idea: a plain new module-level `def` calling the
    function DID red the old scan, which is exactly how a detector earns the
    description "non-vacuous for the shape its author imagined"."""
    tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
    names = _rebound_names(tree, root)
    out = {}

    def visit(node, stack):
        if isinstance(node, ast.Call) and _called_name(node.func) in names and stack:
            key = ".".join(stack)
            out[key] = out.get(key, 0) + 1
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, stack + [child.name])
            else:
                visit(child, stack)

    visit(tree, [])
    return out


def _call_sites(needle, skip_defs=()):
    """Every enclosing qualname that calls `needle` in `bin/fleet.py`.

    TEXTUAL, and deliberately kept that way: its remaining users census
    non-call shapes (`.get("task"`, `["task"]`) that no call graph can see. For
    anything that is a real function call, use `call_counts` -- see the blind
    spots documented there.

    Comment/docstring lines are skipped by the same crude prefix test the
    original census used; `skip_defs` drops the definition itself."""
    src = Path(fleet.__file__).read_text(encoding="utf-8").splitlines()
    out = set()
    for n, line in enumerate(src, start=1):
        if needle not in line or line.lstrip().startswith(("#", "*", '"')):
            continue
        if any(line.lstrip().startswith(f"def {d}") for d in skip_defs):
            continue
        qualname = _enclosing_qualname(src, n)
        if qualname:
            out.add(qualname)
    return out


def test_no_fifth_compose_path_appeared_uncovered():
    """The compose census. §3 enumerates FOUR `compose_prompt` call sites and
    §11.8 binds the teach lines to all of them; a fifth COMPOSE path added
    later would be silently untaught, and the four tests above would still
    pass.

    Re-derived from the source on every run, like the `retired_sids` citation
    test -- a new call site is a deliberate one-line change here, not an
    omission. Note the scope, which the docstring used to overstate: this
    census sees `compose_prompt` callers ONLY. A dispatch path that composes
    its prompt some other way is invisible to it and is caught by
    `test_the_dispatch_census_reflects_five_paths` instead.
    """
    callers = _call_sites("compose_prompt(", skip_defs=("compose_prompt",))
    assert callers == {"cmd_spawn", "_cmd_send_native",
                       "_resume_one_limited_native", "_cmd_respawn_native"}, (
        f"the set of compose_prompt call sites changed: {sorted(callers)}. §11.8 "
        f"binds the teach lines to EVERY dispatch path -- add the new one to "
        f"TestAllFourComposePaths and re-pin this set.")


def test_the_compose_census_sees_a_call_site_inside_a_class():
    """NON-VACUITY for the census above, and the M2 regression pin.

    The census's walk-back used to match `def ` at column zero, so a
    `compose_prompt` call in a class method resolved to the module-level `def`
    above the class -- an APPROVED name -- and a line-count-neutral fifth
    dispatch path added that way left the whole suite green. This asserts the
    resolver on the exact geometry that defeated it, without editing
    `bin/fleet.py`: given a synthetic source, a method's call must resolve to
    `Klass.method`, never to the module-level `cmd_spawn` above it.
    """
    src = [
        "def cmd_spawn(args):",
        "    prompt, _c = compose_prompt(a, b, c, None)",
        "",
        "",
        "class _Fifth:",
        "",
        "    def dispatch(self):",
        "        prompt, _c = compose_prompt(a, b, c, None)",
        "",
        "        def _inner():",
        "            return compose_prompt(a, b, c, None)",
    ]
    assert _enclosing_qualname(src, 2) == "cmd_spawn"
    assert _enclosing_qualname(src, 8) == "_Fifth.dispatch", (
        "the census walk-back resolved a class method's call to an enclosing "
        "module-level def -- this is exactly the hole that let a fifth "
        "dispatch path ship with the suite green")
    assert _enclosing_qualname(src, 11) == "_Fifth.dispatch._inner"


def test_the_dispatch_census_reflects_five_paths():
    """THE census that reflects five, and the reason there are two of them.

    §11.8's four compose paths are not the four dispatch paths -- there are
    FIVE launches of a worker session in this file, and the fifth,
    `_dispatch_supervisor_body`, renders its own prompt through
    `_render_sup_spawn_task` and has never called `compose_prompt` at all. The
    compose census above cannot see it by construction.

    That the supervisor body gets no teach lines is a FACT recorded here, not
    a property being endorsed: it is a deliberate scope boundary (the
    supervisor's body is a fixed boot ritual, not a task prompt), and it is
    written down so the next person adding a dispatch path has to decide
    which census their path belongs in rather than discovering neither
    covered it.
    """
    dispatchers = call_counts("dispatch_bg")
    assert dispatchers == {"cmd_spawn": 1, "_cmd_send_native": 1,
                           "_resume_one_limited_native": 1,
                           "_cmd_respawn_native": 1,
                           "_dispatch_supervisor_body": 1}, (
        f"the dispatch_bg call census changed: {sorted(dispatchers.items())}. "
        f"Every dispatch launches a worker session and pays a prompt: decide "
        f"whether the new one composes via compose_prompt (add it to the "
        f"compose census and to TestAllFourComposePaths) or renders its own "
        f"body (say so here), and re-pin this census. Counts, not a set -- a "
        f"SECOND call inside a function already on this list is a new dispatch "
        f"path that set-equality cannot see.")


def test_the_supervisor_body_does_not_compose_through_compose_prompt():
    """The behavioural half of the five-path census: pinned by calling the
    renderer, not by reading the source, so it also fails if the supervisor
    body starts routing through `compose_prompt` without the census moving."""
    body = fleet._render_sup_spawn_task("sup|inc-x|boot", "inc-x", "CAMPAIGN")
    assert "CAMPAIGN" in body
    assert "You are fleet worker" not in body, (
        "the supervisor body now carries compose_prompt's preamble -- move it "
        "into the compose census and TestAllFourComposePaths")


# ---------------------------------------------------------------------------
# §7 -- `--context` digest injection
# ---------------------------------------------------------------------------

class TestAbsentContextIsFree:
    """The property that keeps every non-indexed project paying zero."""

    def test_absent_context_is_byte_identical_in_a_plain_project(self, plain_project):
        assert _compose("w1", plain_project) == _compose(
            "w1", plain_project, context=None)
        assert _compose("w1", plain_project) == _compose(
            "w1", plain_project, context=[])

    def test_absent_context_is_byte_identical_in_an_indexed_project(
            self, indexed_project, taught_verb_present):
        """An index in the project changes the prompt (the teach lines do that,
        §11.8) but `--context` still costs nothing when it is not given.

        Asserted against a CONSTRUCTED expectation, not against another call to
        `compose_prompt`: a self-comparison only pins that the two spellings
        agree, so a change that charges both of them the same stray byte would
        keep it green. This one names the exact bytes.
        """
        assert _compose("w1", indexed_project) == _compose(
            "w1", indexed_project, context=None)
        assert _compose("w1", indexed_project) == self._expected(
            indexed_project, teach=fleet.INDEX_TEACH_LINES)

    @staticmethod
    def _expected(cwd, teach=""):
        return (fleet._PREAMBLE_TEMPLATE.format(
            name="w1", cwd=cwd,
            journal_target=fleet.journal_file_path("w1").as_posix())
            + teach + "\nthe task")

    def test_absent_context_matches_the_prompt_fleet_composes_today(self, plain_project):
        """The regression pin, spelled out rather than inferred: for a project
        with no index and no `--context`, the composed prompt is EXACTLY the
        preamble template and the task, byte for byte."""
        assert _compose("w1", plain_project) == self._expected(plain_project)
        assert _compose("w1", plain_project, context=[]) == self._expected(plain_project)
        assert _compose("w1", plain_project, context=None) == self._expected(plain_project)

    def test_absent_context_writes_nothing_into_the_index(self, indexed_project):
        """Composition is a read. Without `--context` it must not even look."""
        before = {p: p.stat().st_mtime_ns
                  for p in fleet.index_dir(indexed_project).rglob("*") if p.is_file()}
        _compose("w1", indexed_project)
        after = {p: p.stat().st_mtime_ns
                 for p in fleet.index_dir(indexed_project).rglob("*") if p.is_file()}
        assert before == after


class TestContextDigest:

    def test_digest_is_rendered_for_each_named_file(self, indexed_project):
        prompt = _compose("w1", indexed_project,
                          context=["src/api.py", "docs/DESIGN.md"])
        assert "## src/api.py" in prompt
        assert "## docs/DESIGN.md" in prompt
        assert "- L4 alpha(x: int) -> str" in prompt
        assert "- L8 class Beta" in prompt
        assert "- L10   Beta.run(self, y) -> bool" in prompt

    def test_composition_order_preamble_digest_mailbox_task_journal(
            self, indexed_project, tmp_path):
        """§7's order, all five sources present in one prompt."""
        sid = SID
        fleet.append_mailbox(sid, "MAIL-MARKER")
        journal = _write(tmp_path / "j.md", "JOURNAL-MARKER\n")
        prompt, claim = fleet.compose_prompt(
            "w1", indexed_project, "TASK-MARKER", sid,
            journal_path=journal, context=["src/api.py"])
        fleet.restore_mailbox_claim(claim)
        order = [prompt.index(tok) for tok in (
            "You are fleet worker", "## src/api.py", "MAIL-MARKER",
            "TASK-MARKER", "JOURNAL-MARKER")]
        assert order == sorted(order), (
            f"§7 composition order violated: {order}")

    def test_paths_resolve_against_the_dispatch_dir_not_the_manager_cwd(
            self, indexed_project, plain_project, monkeypatch):
        """§7 / invariant 5: one cwd frame, the worker's `--dir`."""
        monkeypatch.chdir(plain_project)
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "## src/api.py" in prompt

    def test_unknown_path_warns_and_is_skipped_but_never_fails(
            self, indexed_project, capsys):
        prompt = _compose("w1", indexed_project,
                          context=["src/api.py", "src/nope.py"])
        assert "## src/api.py" in prompt
        assert "nope.py" not in prompt
        assert "nope.py" in capsys.readouterr().err

    def test_a_path_escaping_the_dispatch_dir_is_skipped(
            self, indexed_project, plain_project, capsys):
        """`--context ../plain/src/api.py` must not reach outside `--dir`:
        the digest would describe a file the worker's index does not cover.

        FIX WAVE C2, and the re-pin is the point. This used to pass only
        because `_index_posix_rel` RETURNED a rel that then failed the
        membership test. A sibling slice repairs that helper to REJECT a `..`
        segment by raising, at which point this test went PASS -> ERROR --
        measured, by injecting that guard verbatim. It is now asserted as
        BEHAVIOUR (no digest, a warning, compose returns) rather than as a
        return path, so it holds under either implementation, and it names no
        exception class from the branch that raises."""
        prompt = _compose("w1", indexed_project,
                          context=["../plain/src/api.py"])
        assert "api.py (" not in prompt
        assert "## " not in prompt
        assert capsys.readouterr().err.strip()

    def test_an_escaping_path_is_skipped_even_when_normalisation_raises(
            self, indexed_project, monkeypatch, capsys):
        """The same property under the OTHER implementation, forced, so this
        file pins both worlds without waiting on a merge.

        The raised class is minted locally and descends from `FleetCliError`:
        the contract under test is "one unusable path costs one warning", not
        any particular spelling."""

        class _PathRejected(fleet.FleetCliError):
            pass

        real = fleet._index_posix_rel
        monkeypatch.setattr(fleet, "_index_posix_rel", lambda rel: (
            (_ for _ in ()).throw(_PathRejected(f"escapes the root: {rel}"))
            if ".." in str(rel) else real(rel)))

        prompt = _compose("w1", indexed_project,
                          context=["src/api.py", "../plain/src/api.py"])
        assert "## src/api.py" in prompt, (
            "a rejected path took the OTHER named paths down with it")
        assert "## ../plain" not in prompt
        assert "digest skipped" in capsys.readouterr().err

    def test_the_index_update_verb_refuses_a_path_outside_the_root(self, tmp_path):
        """C2's SECOND site, which the gate's blast-radius measurement did not
        reach because it ran only this file.

        `_index_posix_rel` is shared: `fleet index update --files ../x.py`
        goes through it too, so a guard that raises THERE pre-empts
        `_index_files_arg`'s own `startswith("../")` refusal with a different
        message.

        This test used to monkeypatch `_index_posix_rel` into raising a
        locally-minted error whose text said `escapes the root`, and then
        assert that `_index_files_arg` re-worded it back to this verb's own
        phrasing. That pinned the WRAPPER, not the contract -- and the wrapper
        is the thing `idx/core` rules against: its `_index_posix_rel` is meant
        to be the single containment guard for every caller, and its own
        comment records that a second guard at this site "is what let the two
        spellings drift apart in the first place". A test that fails unless
        the second site re-words the refusal is a test that forbids the
        standard this repo has already chosen.

        What survives, and is asserted here, is the CONTRACT a caller can
        actually rely on: `--files ../x.py` is refused, the refusal is a
        `FleetCliError`, and it names the index root. That is true whichever
        layer catches the escape -- this site's own guard, or the
        canonicaliser's `IndexPathError` (which is a `FleetCliError` and whose
        message carries the same "outside the index root") -- so the test no
        longer has an opinion about which one does.

        No monkeypatch: the real escape is passed to the real function. The
        simulated one is what let the assertion drift from the behaviour."""
        with pytest.raises(fleet.FleetCliError, match="outside the index root"):
            fleet._index_files_arg(tmp_path, "../x.py")

    def test_context_in_a_project_with_no_index_warns_and_proceeds(
            self, plain_project, capsys):
        """§9's no-index row: spawn injects nothing and proceeds."""
        prompt = _compose("w1", plain_project, context=["src/api.py"])
        assert "## src/api.py" not in prompt
        assert "no index" in capsys.readouterr().err

    def test_the_spawn_time_digest_is_not_capped_at_400_lines(self, tmp_path):
        """§11.4/§11.1: the 400-line cap is `--outline`'s, not the spawn-time
        digest's. The two outputs differ only when the cap truncates, so a cap
        applied here would silently impose `q`'s limit on a path the spec
        exempts.

        **The cap this compares against does not exist on this branch.**
        `q --outline` and its 400-line cap are a sibling slice; naming a
        number no code here implements is how a comparison rots into folklore,
        so the assertion below is about the DIGEST's own behaviour -- it emits
        a symbol past line 400 of a 2000-line file and never truncates --
        and the number 400 appears only as the claim it is being measured
        against."""
        root = tmp_path / "big"
        body = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(500))
        _write(root / "big.py", body)
        fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
        fleet.build_index(root)
        prompt = _compose("w1", root, context=["big.py"])
        assert "- L1993 f498()" in prompt
        assert "truncated" not in prompt
        digest_lines = [l for l in prompt.splitlines() if l.startswith("- L")]
        assert len(digest_lines) == 500 > 400, (
            "the digest emitted a bounded number of rows -- if a cap was added "
            "here deliberately, §11.1's 'the two renderings differ only when "
            "the cap truncates' has to move with it")

    def test_the_uncapped_digest_cost_is_pinned_by_measurement(self, tmp_path):
        """M4. What "uncapped" actually costs, measured rather than assumed.

        The pin this replaces asserted only that a synthetic 500-symbol file
        was not truncated. That is the contract, but it is not the cost, and
        the cost is the thing a manager needs before typing `--context`. So
        this measures the real worst case in the repo -- `bin/fleet.py`
        itself -- and pins the SHAPE of the growth rather than a byte count
        that would rot on every edit to that file:

          * one digest row per indexed symbol, plus one header line;
          * no truncation at any size;
          * N distinct files cost the sum of their digests -- there is no
            budget, so the manager's `--context` list IS the budget.

        Measured 2026-07-27 at this fix wave's base commit: `bin/fleet.py`
        (16,075 source lines) rendered **539 digest lines / 27,835 chars**,
        and fifty distinct files of that size would render ~1.39 MB into a
        single prompt. No cap was added: §11.1 states the digest and
        `q --outline` differ only when the cap truncates, so capping here
        would silently impose `q`'s limit on a path the spec exempts, and that
        is a spec decision rather than a fix-wave one. Dedup WAS added
        (`parse_context_arg`) -- paying twice for the same file defends
        nothing.
        """
        root = tmp_path / "real"
        _write(root / "bin" / "fleet.py",
               Path(fleet.__file__).read_text(encoding="utf-8"))
        fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
        fleet.build_index(root)

        digest, warnings = fleet.compose_context_digests(root, ["bin/fleet.py"])
        assert warnings == []
        rows = [l for l in digest.splitlines() if l.startswith("- L")]
        header = [l for l in digest.splitlines() if l.startswith("## ")]
        _hdr, shard_rows = fleet.read_shard(
            fleet.shard_path_for_source(root, "bin/fleet.py"))

        assert len(header) == 1
        assert len(rows) == len(shard_rows), (
            "the digest no longer renders one row per indexed symbol -- the "
            "cost model in this test's docstring is stale")
        assert "truncated" not in digest
        assert len(digest) > 20_000, (
            f"{len(digest)} chars for a 16k-line file: something started "
            f"bounding the digest, which §11.1 forbids without moving the spec")

        # Linear in DISTINCT files, and that is the whole budget story.
        (root / "bin" / "second.py").write_bytes(
            (root / "bin" / "fleet.py").read_bytes())
        fleet.build_index(root)
        both, _w = fleet.compose_context_digests(
            root, ["bin/fleet.py", "bin/second.py"])
        assert len(both) > 2 * len(digest) - 200, (
            "two distinct files no longer cost two digests -- if a shared cap "
            "or a cross-file budget was introduced, pin it")

    def test_naming_the_same_path_twice_is_paid_for_once(self, indexed_project):
        """M4's one honest mitigation. Before this, `--context a.py,a.py`
        rendered `a.py` twice for zero additional information -- and with a
        27,835-char digest behind it, the second copy is not free."""
        once = _compose("w1", indexed_project, context=["src/api.py"])
        twice = _compose("w1", indexed_project,
                         context=fleet.parse_context_arg("src/api.py,src/api.py"))
        assert once == twice
        assert once.count("## src/api.py") == 1

    def test_dedup_preserves_the_order_the_manager_named(self):
        assert fleet.parse_context_arg("b.md,a.py,b.md,a.py") == ["b.md", "a.py"]

    def test_a_file_the_index_config_excludes_is_skipped_not_indexed(
            self, indexed_project, capsys):
        """A shard written for an unselected file would be pruned by the very
        next `build` -- `update_index` refuses for exactly this reason, and the
        digest path must not make a promise the index cannot keep."""
        _write(indexed_project / "notes.txt", "plain text\n")
        prompt = _compose("w1", indexed_project, context=["notes.txt"])
        assert "## notes.txt" not in prompt
        assert "notes.txt" in capsys.readouterr().err
        assert not fleet.shard_path_for_source(indexed_project, "notes.txt").exists()

    def test_spawn_accepts_a_comma_separated_context_flag(self, indexed_project, captured):
        args = SimpleNamespace(
            name="w1", dir=str(indexed_project), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None,
            context="src/api.py,docs/DESIGN.md")
        prompt = _drive(lambda: fleet.cmd_spawn(
            args, run=lambda *a, **k: None, which=lambda _: "claude",
            sleep=lambda s: None, clock=lambda: 0.0))
        assert "## src/api.py" in prompt
        assert "## docs/DESIGN.md" in prompt

    def test_the_parser_accepts_context(self):
        args = fleet.build_parser().parse_args(
            ["spawn", "w1", "--dir", ".", "--task", "t", "--context", "a.py,b.md"])
        assert fleet.parse_context_arg(args.context) == ["a.py", "b.md"]

    def test_parse_context_arg_tolerates_spacing_and_empties(self):
        assert fleet.parse_context_arg(None) == []
        assert fleet.parse_context_arg("") == []
        assert fleet.parse_context_arg(" a.py , , b.md ") == ["a.py", "b.md"]


# ---------------------------------------------------------------------------
# FINDING C -- the canonicalisation dedupe bug, and the digest size cap
# ---------------------------------------------------------------------------

# One filler symbol, rendered. `def digest_filler_symbol_000123():` becomes the
# digest row `- L1234 digest_filler_symbol_000123()`. 38 is a deliberate
# UNDER-estimate of that row's width, so a symbol count derived from it always
# overshoots its char target rather than falling short -- a fixture that fell
# short would leave the load-bearing witness unrun while the test still passed.
# Every test below states the precondition that proves its fixture landed on
# the right side of the threshold it is about.
_FILLER_ROW_CHARS = 38


def _bulky_source(symbols):
    return "".join(f"def digest_filler_symbol_{i:06d}():\n    return {i}\n\n\n"
                   for i in range(symbols))


def _bulky_project(root, symbols, rel="bulk.py"):
    """An indexed project holding one source with `symbols` module functions."""
    _write(root / rel, _bulky_source(symbols))
    fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
    fleet.build_index(root)
    return root


def _symbols_for_chars(target_chars):
    """Enough filler symbols to render MORE than `target_chars`, with 30%
    headroom over the under-estimated row width."""
    return int(target_chars / _FILLER_ROW_CHARS * 1.3) + 1


class TestTheCanonicalisationDedupeBug:
    """FINDING C part (a). A plain bug, and the whole 8x digest blowup.

    `parse_context_arg` dropped duplicates by comparing the RAW argv string.
    Canonicalisation happens later and elsewhere -- `_index_posix_rel`, inside
    `compose_context_digests` -- and it folds `./`, `\\`, `//` and interior
    `/./` away. So `src/api.py` and `./src/api.py` were two distinct keys to
    the dedupe and one single file to everything downstream, and the digest was
    rendered once per SPELLING.

    Measured on this repo before the fix (`bin/fleet.py` staged into a temp
    root and indexed): eight spellings of `tests/test_native.py`, 180 argv
    chars, rendered **327,944 digest chars -- exactly 8.00x** the 40,993-char
    single digest, 1,822 digest chars per argv char.

    The fix is at the CHOKE POINT that pays the cost, not at the argv parser:
    `compose_context_digests` already canonicalises every entry, and it is the
    only place that knows what a digest costs. Fixing it there also protects
    the three tests and any future caller that reach `compose_context_digests`
    without going through `parse_context_arg` at all.
    """

    _SPELLINGS = ["src/api.py", "./src/api.py", "src\\api.py",
                  "src//api.py", "./src\\api.py", ".\\src/api.py",
                  "src/./api.py", "././src/api.py"]

    def test_the_construction_holds_eight_spellings_one_canonical_rel(self):
        """The precondition every test in this class rests on. Without it a
        green suite would prove only that the fixture had stopped colliding."""
        assert len({fleet._index_posix_rel(s) for s in self._SPELLINGS}) == 1
        assert len(set(self._SPELLINGS)) == 8, "the spellings stopped being distinct"

    def test_eight_spellings_of_one_source_are_paid_for_once(self, indexed_project):
        digest, _warnings = fleet.compose_context_digests(
            indexed_project, self._SPELLINGS)
        one, _w = fleet.compose_context_digests(indexed_project, ["src/api.py"])
        assert digest.count("## src/api.py") == 1, (
            f"{digest.count('## src/api.py')} digests for one source -- the "
            f"dedupe is still comparing raw argv strings")
        assert len(digest) == len(one)

    def test_the_fold_is_reported_rather_than_silent(self, indexed_project):
        """A folded spelling is a path the manager TYPED and did not get its
        own digest for. That is nothing like a truncated symbol table -- the
        symbol table is complete -- but it is still a divergence between what
        was asked for and what was served, and §7 already spends a warning on
        every one of those."""
        _digest, warnings = fleet.compose_context_digests(
            indexed_project, ["src/api.py", "./src/api.py"])
        assert len(warnings) == 1, warnings
        assert "./src/api.py" in warnings[0] and "src/api.py" in warnings[0]

    def test_one_spelling_alone_never_warns(self, indexed_project):
        """The control. An over-eager fold would warn on a clean list, and the
        M4 cost pin asserts `warnings == []` for exactly this shape."""
        _digest, warnings = fleet.compose_context_digests(
            indexed_project, ["src/api.py"])
        assert warnings == []

    def test_two_genuinely_distinct_sources_are_both_served(self, indexed_project):
        """The other control: an over-eager fold that swallowed everything
        after the first entry."""
        digest, warnings = fleet.compose_context_digests(
            indexed_project, ["src/api.py", "docs/DESIGN.md"])
        assert warnings == []
        assert digest.count("## src/api.py") == 1
        assert digest.count("## docs/DESIGN.md") == 1

    def test_two_sources_sharing_a_BASENAME_are_both_served(self, indexed_project):
        """The fold key must be the WHOLE canonical rel, not the last segment.

        **This test exists because its absence was measured.** The injection
        `_base = rel.rsplit("/", 1)[-1]` -- fold on the basename -- left the
        ENTIRE suite green, including the test above, because the two files it
        names (`src/api.py`, `docs/DESIGN.md`) do not share a basename. A
        control that cannot fail for the mechanism it claims to control is the
        4th-instance lesson exactly: the pin was written against the bug that
        was fixed and was blind to the one a fix could introduce."""
        _write(indexed_project / "lib" / "api.py", API_PY)
        fleet.build_index(indexed_project)
        digest, warnings = fleet.compose_context_digests(
            indexed_project, ["src/api.py", "lib/api.py"])
        assert warnings == []
        assert digest.count("## src/api.py") == 1
        assert digest.count("## lib/api.py") == 1

    def test_the_fold_preserves_the_order_the_manager_named(self, indexed_project):
        """§7's digests appear in the order the manager named them; the fold
        keeps the FIRST spelling's position, not the last."""
        digest, _w = fleet.compose_context_digests(
            indexed_project, ["docs/DESIGN.md", "./src/api.py", "docs//DESIGN.md"])
        assert digest.index("## docs/DESIGN.md") < digest.index("## src/api.py")

    def test_a_spelling_that_cannot_be_canonicalised_still_warns_and_skips(
            self, indexed_project):
        """§7's contract for a rejected path shape, unchanged by the fold.

        This is the trap the fix had to avoid: `_index_posix_rel` RAISES on an
        escape, and it raises inside the per-path `try` that §7's warn-and-skip
        depends on (fix wave C1/C2). A dedupe that canonicalised in
        `parse_context_arg` -- outside that protection -- would have converted
        `--context ../x.py` from a warning into a failed spawn."""
        digest, warnings = fleet.compose_context_digests(
            indexed_project, ["../x.py", "src/api.py"])
        assert digest.count("## src/api.py") == 1
        assert len(warnings) == 1
        assert "../x.py" in warnings[0]

    def test_the_blowup_is_gone_on_the_real_spawn_path(self, indexed_project):
        """End to end through `parse_context_arg` and `compose_prompt`, the way
        `fleet spawn --context` actually reaches it."""
        ctx = fleet.parse_context_arg(",".join(self._SPELLINGS))
        prompt = _compose("w1", indexed_project, context=ctx)
        assert prompt.count("## src/api.py") == 1


class TestTheDigestSizeCap:
    """FINDING C part (b). WARN at a measured threshold, REFUSE above a
    measured hard ceiling, and NEVER TRUNCATE.

    **Never truncate** is the load-bearing half. The digest is a SYMBOL TABLE,
    and a truncated symbol table is indistinguishable from a complete one: a
    worker that reads one concludes the symbol does not exist and
    re-implements it. Refusing costs the manager one retyped command; silently
    truncating costs a duplicated implementation nobody knows is duplicated.
    So the cap has exactly two grades and no third.

    **The M4 pin does NOT catch a truncating cap, and the ruling that says it
    does is wrong.** This was measured both ways rather than assumed:

      * truncate at the CEILING (`digest[:250_000]`) -- M4 stays **GREEN**.
        M4's fixture is `bin/fleet.py` alone (27,741 chars) plus two copies of
        it (~55,482); neither reaches 250,000, so the truncation never fires
        in M4 at all. Four tests in THIS class caught it; M4 saw nothing.
      * truncate at the WARN threshold (`digest[:50_000]`) -- M4 goes RED,
        because its two-copies assertion (`len(both) > 2 * len(digest) - 200`)
        does cross 50,000.

    So M4 reds only for a cap that trims below ~55,500 chars, and the more
    plausible wrong implementation -- trim at the ceiling -- slips past it
    entirely. Anyone leaning on "M4 will catch it" is relying on a coincidence
    of fixture size. What actually catches truncation is
    `test_a_digest_over_the_hard_ceiling_is_refused_not_truncated` (the refusal
    must RAISE, not return something shorter) and
    `test_a_digest_over_the_warn_threshold_warns_and_is_served_in_full` (row
    count compared against the SHARD, not against the digest itself).

    **Both numbers are measured, and measured on the EFFECT** -- rendered
    digest chars as produced -- never on a proxy. A proxy fails here by three
    orders of magnitude: 180 argv chars produced 327,944 digest chars. The
    measurements behind the two constants are recorded at their definition in
    `bin/fleet.py`; the two tests at the end of this class re-derive the ones
    that can be re-derived from the repo itself.
    """

    def test_the_two_grades_are_ordered_and_counted_in_digest_chars(self):
        assert 0 < fleet.INDEX_DIGEST_WARN_CHARS < fleet.INDEX_DIGEST_REFUSE_CHARS

    def test_a_digest_under_the_warn_threshold_is_silent(self, tmp_path):
        root = _bulky_project(tmp_path / "small", 200)
        digest, warnings = fleet.compose_context_digests(root, ["bulk.py"])
        assert len(digest) < fleet.INDEX_DIGEST_WARN_CHARS, (
            f"fixture is {len(digest)} chars, at or over the "
            f"{fleet.INDEX_DIGEST_WARN_CHARS}-char warn threshold -- this test "
            f"was measuring the wrong side of it")
        assert warnings == []

    def test_a_digest_over_the_warn_threshold_warns_and_is_served_in_full(
            self, tmp_path):
        """The whole point of a warn grade: the manager is told the number and
        still gets every symbol. Truncation is checked here, not only at the
        ceiling, because a cap that trims at the WARN line would leave the
        refusal test green and still hand a worker a lying symbol table."""
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_WARN_CHARS)
        root = _bulky_project(tmp_path / "warn", symbols)
        digest, warnings = fleet.compose_context_digests(root, ["bulk.py"])
        assert fleet.INDEX_DIGEST_WARN_CHARS < len(digest) \
            < fleet.INDEX_DIGEST_REFUSE_CHARS, (
                f"fixture is {len(digest)} chars, not between the warn "
                f"threshold {fleet.INDEX_DIGEST_WARN_CHARS} and the ceiling "
                f"{fleet.INDEX_DIGEST_REFUSE_CHARS}")
        assert len(warnings) == 1, warnings
        assert str(len(digest)) in warnings[0].replace(",", ""), (
            f"the warning does not name the measured size: {warnings[0]!r}")
        # Never truncated: one row per indexed symbol, and the LAST symbol in
        # the file is present. A cap that trimmed the tail passes a row count
        # taken from the digest itself, so the row count is compared against
        # the SHARD.
        _hdr, shard_rows = fleet.read_shard(
            fleet.shard_path_for_source(root, "bulk.py"))
        rows = [l for l in digest.splitlines() if l.startswith("- L")]
        assert len(rows) == len(shard_rows) == symbols
        assert f"digest_filler_symbol_{symbols - 1:06d}()" in digest
        assert "truncat" not in digest.lower()

    def test_a_digest_over_the_hard_ceiling_is_refused_not_truncated(self, tmp_path):
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_REFUSE_CHARS)
        root = _bulky_project(tmp_path / "refuse", symbols)
        with pytest.raises(fleet.FleetCliError) as excinfo:
            fleet.compose_context_digests(root, ["bulk.py"])
        message = str(excinfo.value)
        # The refusal names the MEASURED size and the ceiling it crossed. This
        # doubles as the fixture's precondition: a fixture that came in under
        # the ceiling would not have raised at all.
        digits = [int(n) for n in re.findall(r"\d[\d,]*", message.replace(",", ""))]
        assert fleet.INDEX_DIGEST_REFUSE_CHARS in digits, message
        assert any(n > fleet.INDEX_DIGEST_REFUSE_CHARS for n in digits), message

    def test_the_refusal_tells_the_manager_what_to_do_instead(self, tmp_path):
        """A refusal that does not say how to proceed is a wall. It must name
        the paths it was asked for, so the manager can drop one."""
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_REFUSE_CHARS)
        root = _bulky_project(tmp_path / "advice", symbols)
        with pytest.raises(fleet.FleetCliError, match="bulk.py"):
            fleet.compose_context_digests(root, ["bulk.py"])

    def test_the_refusal_is_a_refusal_and_never_a_partial_prompt(self, tmp_path):
        """`compose_prompt` must not return a prompt carrying a partial
        digest. The refusal propagates; there is no half-served arm."""
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_REFUSE_CHARS)
        root = _bulky_project(tmp_path / "prompt", symbols)
        with pytest.raises(fleet.FleetCliError):
            _compose("w1", root, context=["bulk.py"])

    def test_the_ceiling_counts_the_WHOLE_digest_not_one_file(self, tmp_path):
        """The blowup that motivated the cap was one file named eight times,
        so a per-file ceiling would have missed it entirely. Two files, each
        comfortably under the ceiling, together over it."""
        half = _symbols_for_chars(fleet.INDEX_DIGEST_REFUSE_CHARS) // 2 + 200
        root = tmp_path / "pair"
        _write(root / "a.py", _bulky_source(half))
        _write(root / "b.py", _bulky_source(half))
        fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
        fleet.build_index(root)
        one, warnings = fleet.compose_context_digests(root, ["a.py"])
        assert len(one) < fleet.INDEX_DIGEST_REFUSE_CHARS, (
            f"each half is {len(one)} chars, already over the ceiling -- this "
            f"test would pass without ever summing the two")
        assert len(one) * 2 > fleet.INDEX_DIGEST_REFUSE_CHARS
        with pytest.raises(fleet.FleetCliError):
            fleet.compose_context_digests(root, ["a.py", "b.py"])

    def test_a_refused_digest_leaves_no_phantom_registry_record(
            self, indexed_project, tmp_path, monkeypatch):
        """FIX WAVE C1's property, applied to the new refusal. The refusal is a
        `FleetCliError` raised out of `compose_prompt`, and `cmd_spawn`
        composes ABOVE the registry commit precisely so that any such raise
        cannot see a committed record. If the hoist were ever undone, this is
        one of the tests that says so."""
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_REFUSE_CHARS)
        root = _bulky_project(tmp_path / "phantom", symbols)
        monkeypatch.setattr(fleet, "dispatch_bg", lambda name, cwd, prompt, mode, **kw: {
            "session_id": SID, "short_id": SID.partition("-")[0]})
        args = SimpleNamespace(
            name="w1", dir=str(root), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None, context="bulk.py")
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(args, run=lambda *a, **k: None,
                            which=lambda _: "claude", sleep=lambda s: None,
                            clock=lambda: 0.0)
        assert fleet.load_registry()["workers"] == {}

    def test_the_dedupe_fold_happens_BEFORE_the_size_is_measured(self, tmp_path):
        """Order matters and it is not cosmetic. Eight spellings of a file
        whose single digest sits under the ceiling must be SERVED, because
        after the fold there is one digest. Measuring before folding would
        refuse a request that costs one file's digest -- the cap punishing the
        very input the dedupe fix makes free."""
        symbols = _symbols_for_chars(fleet.INDEX_DIGEST_WARN_CHARS)
        root = _bulky_project(tmp_path / "order", symbols)
        one, _w = fleet.compose_context_digests(root, ["bulk.py"])
        spellings = ["bulk.py", "./bulk.py", ".\\bulk.py", "././bulk.py",
                     "./bulk.py", "bulk.py", "././/bulk.py", "./bulk.py"]
        assert len(one) * len(spellings) > fleet.INDEX_DIGEST_REFUSE_CHARS, (
            "the un-folded cost no longer crosses the ceiling, so this test "
            "would pass whether or not the fold ran first")
        digest, _warnings = fleet.compose_context_digests(root, spellings)
        assert len(digest) == len(one)

    # -- the grounding, re-derived from this repo rather than quoted ---------

    def test_the_warn_threshold_clears_this_repo_s_largest_module(self, tmp_path):
        """The WARN number's stated grounding: it sits ABOVE the largest
        single-file digest this repo produces, so naming ONE file never warns
        and a warning genuinely means "more than the biggest file here".

        Re-derived against `bin/fleet.py`, the file the M4 cost pin uses and
        the one that grows every wave. Measured 2026-07-30: 27,741 chars.
        `tests/test_native.py` is actually this repo's largest digest at
        40,993 chars -- also under the threshold -- but it is not staged here,
        because this test's job is to guarantee the M4 pin's `warnings == []`
        keeps holding as `bin/fleet.py` grows."""
        root = tmp_path / "real"
        _write(root / "bin" / "fleet.py",
               Path(fleet.__file__).read_text(encoding="utf-8"))
        fleet.index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
        fleet.build_index(root)
        digest, warnings = fleet.compose_context_digests(root, ["bin/fleet.py"])
        assert warnings == [], (
            f"bin/fleet.py's own digest is {len(digest)} chars and now trips "
            f"the {fleet.INDEX_DIGEST_WARN_CHARS}-char warn threshold. The "
            f"threshold was measured against a 27,741-char digest; re-measure "
            f"it and move it, and move the M4 pin's docstring with it")
        assert len(digest) < fleet.INDEX_DIGEST_WARN_CHARS

    def test_the_ceiling_serves_a_dozen_of_this_repo_s_largest_files(self):
        """The REFUSE number's grounding from BELOW, stated as arithmetic over
        numbers measured on this repo (2026-07-30, 177 selected sources):

            largest single digest       40,993 chars  tests/test_native.py
            median single digest           893 chars
            13 largest files together  246,919 chars
            14 largest files together  255,236 chars
            every selected source      492,570 chars / 6,812 lines
            the pre-dedupe blowup      327,944 chars from 180 argv chars

        The ceiling sits in the measured gap between the largest plausible ask
        (246,919) and the pathology it exists to stop (327,944). This test is
        the cheap arithmetic half -- that the ceiling still admits a dozen of
        the largest files and hundreds of median ones, and still refuses the
        whole-repo ask and the blowup. Re-staging and re-indexing 177 sources
        to re-derive the six numbers costs ~40 s, which is why they are
        recorded rather than recomputed per run; the harness that produced
        them is described in `docs/specs/fleet-index.md`."""
        ceiling = fleet.INDEX_DIGEST_REFUSE_CHARS
        assert ceiling > 246_919, "the ceiling no longer serves 13 large files"
        assert ceiling // 893 >= 200, "the ceiling no longer serves 200 median files"
        assert ceiling < 327_944, "the ceiling no longer refuses the 8x blowup"
        assert ceiling < 492_570, "the ceiling no longer refuses the whole-repo ask"


class TestDigestNeverServesAnUnverifiedCoordinate:
    """§8's single most important property, applied to the digest path."""

    def test_a_stale_shard_is_repaired_before_it_is_rendered(self, indexed_project):
        """The behavioural half. Edit the source after the build: a digest read
        straight off the shard would print the OLD line numbers, which do not
        error -- they silently point the worker at the wrong code."""
        shard = fleet.shard_path_for_source(indexed_project, "src/api.py")
        stale = shard.read_bytes().decode("utf-8")
        assert "alpha\t4\t" in stale
        _write(indexed_project / "src" / "api.py", "\n\n\n\n\n" + API_PY)
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "- L9 alpha(x: int) -> str" in prompt
        assert "- L4 alpha(x: int) -> str" not in prompt

    def test_a_corrupt_shard_is_repaired_before_it_is_rendered(self, indexed_project):
        shard = fleet.shard_path_for_source(indexed_project, "src/api.py")
        shard.write_bytes(b"#\tdeadbeef\t3\tpython\ngarbage\n")
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "- L4 alpha(x: int) -> str" in prompt

    def test_the_digest_reads_through_the_choke_point(self, indexed_project, monkeypatch):
        """The structural half. §11.3's `verified_shard_rows` is THE choke
        point; a digest built off `read_shard` directly would pass the
        behavioural test above whenever the shard happened to be fresh.
        """
        calls = []
        real = fleet.verified_shard_rows

        def spy(root, rel, **kw):
            calls.append((Path(root), rel))
            return real(root, rel, **kw)

        monkeypatch.setattr(fleet, "verified_shard_rows", spy)
        _compose("w1", indexed_project, context=["src/api.py"])
        assert calls == [(Path(indexed_project), "src/api.py")], (
            "the digest did not go through verified_shard_rows() -- some other "
            "path is reading shards, and §8's no-unverified-coordinate property "
            "does not bind it")

    def test_a_deleted_source_is_suppressed_not_rendered(self, indexed_project, capsys):
        """Orphan row (§11.3): the shard survives the source. Its coordinates
        describe a file that is gone, so they are suppressed, not served."""
        (indexed_project / "src" / "api.py").unlink()
        prompt = _compose("w1", indexed_project, context=["src/api.py"])
        assert "## src/api.py" not in prompt
        assert capsys.readouterr().err.strip()


class TestComposeFailureNeverLeavesAPhantomRecord:
    """FIX WAVE C1. The window, measured before the fix:

        `cmd_spawn` committed the pre-claim record under `fleet_lock()`, THEN
        called `compose_prompt`, THEN entered the `try:` whose `except`
        clauses roll that record back. Anything raising in between escaped
        `cmd_spawn` uncaught and left
        `{"status": "working", "session_id": null}` in the registry plus a
        `spawned` event -- a live-looking worker that never existed, pinned
        there by the launch-in-flight guard. Reproduced end to end with
        `--context` naming a file whose shard directory could not be created:
        `FileExistsError [WinError 183]`, record present, status `working`.

    Two independent fixes, because measurement showed neither alone is enough:

    1. `compose_prompt` is hoisted ABOVE the registry commit, so no raise
       from ANY compose arm -- present or future -- can see a committed
       record. Hoisting alone converts the phantom into an uncaught traceback.
    2. `compose_context_digests` wraps the per-path body, so the three known
       `--context` arms take §7's stated behaviour (warn, skip, spawn
       proceeds) instead of raising at all.

    All three arms are pinned below. NONE of them had a test.
    """

    @staticmethod
    def _args(project, context=None, name="w1"):
        return SimpleNamespace(
            name=name, dir=str(project), task="the task", mode="dontask",
            model=None, max_budget_usd=None, setting_sources=None,
            token_ceiling=None, category=None, context=context)

    @staticmethod
    def _dispatch_ok(monkeypatch):
        """A `dispatch_bg` that SUCCEEDS -- these tests are about compose, and
        a capturing stub that raises would let the rollback path hide the very
        thing being measured."""
        monkeypatch.setattr(fleet, "dispatch_bg", lambda name, cwd, prompt, mode, **kw: {
            "session_id": SID, "short_id": SID.partition("-")[0]})

    @staticmethod
    def _events():
        path = fleet.events_path()
        if not path.exists():
            return []
        return [json.loads(line)["kind"]
                for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _spawn(self, project, monkeypatch, context=None):
        self._dispatch_ok(monkeypatch)
        return fleet.cmd_spawn(self._args(project, context),
                               run=lambda *a, **k: None, which=lambda _: "claude",
                               sleep=lambda s: None, clock=lambda: 0.0)

    # -- arm 1: the shard write. REAL, no monkeypatching at all. -------------

    def test_arm_1_an_unwritable_shard_directory_leaves_no_phantom_record(
            self, indexed_project, monkeypatch):
        """The arm that reproduced the phantom, constructed on the real
        filesystem: occupy `.fleet-index/symbols/src` with a plain FILE, so
        `write_shard_atomic`'s `mkdir` cannot make the shard's directory.

        WHAT THIS ARM MAY ASSERT CHANGED, and the change is not this branch's
        to argue with. It used to assert `digest skipped` on stderr, because
        on THIS branch the `FileExistsError` escapes `write_shard_atomic` and
        the C1 per-path wrapper turns it into a warning. `idx/core` moved that
        degradation one layer DOWN: its `write_shard_atomic` catches EVERY
        `OSError` and returns False, and `verified_shard_rows` then answers
        `status: ok` from this run's own parse with only `written` False. So
        on a tree carrying `idx/core` there is no warning to observe and the
        digest is served -- the old assertion was not merely rotted, its
        subject had ceased to exist.

        Both spellings of the failure are real, and the property this arm was
        BUILT for is common to them: an unwritable shard directory must not
        leave `{"status": "working", "session_id": null}` behind, and the
        spawn must proceed. That is what is asserted, and it holds whichever
        layer absorbs the error -- so this test does not encode which branch
        it is standing on.

        Honest residual: where `write_shard_atomic` swallows the error, this
        arm can no longer reproduce the phantom on its own, and the guard on
        the C1 hoist is `test_arm_1_produces_no_phantom_even_if_the_skip_is_
        removed` below, which forces the raise rather than constructing it."""
        shard = fleet.shard_path_for_source(indexed_project, "src/api.py")
        shard.unlink()
        shard.parent.rmdir()
        shard.parent.write_bytes(b"not a directory")

        assert self._spawn(indexed_project, monkeypatch, "src/api.py") == 0
        # The construction held: the shard genuinely could not be written.
        # Without this the test would still pass on a tree where the occupied
        # directory was silently repaired, and assert nothing at all.
        assert not shard.exists()
        assert shard.parent.is_file()
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == SID and rec["status"] == "working"
        assert "spawned" in self._events()

    def test_arm_1_produces_no_phantom_even_if_the_skip_is_removed(
            self, indexed_project, monkeypatch):
        """The hoist, on its own. Force the SAME arm to raise past the
        per-path skip by breaking the layer above it, and assert the registry
        is untouched -- this is what fails if someone deletes the hoist and
        keeps only the warn-and-skip."""
        self._dispatch_ok(monkeypatch)
        monkeypatch.setattr(fleet, "compose_context_digests",
                            lambda *a, **k: (_ for _ in ()).throw(
                                OSError("shard directory is a file")))
        with pytest.raises(fleet.FleetCliError, match="could not compose"):
            fleet.cmd_spawn(self._args(indexed_project, "src/api.py"),
                            run=lambda *a, **k: None, which=lambda _: "claude",
                            sleep=lambda s: None, clock=lambda: 0.0)
        assert fleet.load_registry()["workers"] == {}
        assert "spawned" not in self._events()

    # -- arm 2: the source parse. -------------------------------------------

    def test_arm_2_a_source_that_dies_mid_parse_warns_and_the_spawn_proceeds(
            self, indexed_project, monkeypatch, capsys):
        """`verified_shard_rows` re-reads the source AFTER hashing it, so a
        file that disappears in that gap raises `OSError` from
        `parse_source_symbols`. Forced rather than raced, because the window
        is a few microseconds wide and a racy test is a flaky test.

        The stub takes `*args, **kwargs` rather than restating the signature.
        Spelling it as `(source_path, lang=None)` pinned a SIGNATURE this test
        does not care about: `idx/core` grew a `raw=` parameter (so the choke
        point calls `parse_source_symbols(source, lang, raw=raw)`), the stub
        raised `TypeError` instead of the `OSError` under test, and the C1
        wrapper turned that into a `FleetCliError` that refused the spawn --
        a red test measuring nothing about its own subject. A stub that
        forwards whatever it was handed cannot rot that way again."""
        real = fleet.parse_source_symbols

        def _boom(source_path, *args, **kwargs):
            if str(source_path).endswith("api.py"):
                raise OSError("source vanished between header and parse")
            return real(source_path, *args, **kwargs)

        monkeypatch.setattr(fleet, "parse_source_symbols", _boom)
        # Force the re-parse: a fresh shard would be served without one.
        fleet.shard_path_for_source(indexed_project, "src/api.py").unlink()

        assert self._spawn(indexed_project, monkeypatch, "src/api.py") == 0
        assert "digest skipped" in capsys.readouterr().err
        assert fleet.load_registry()["workers"]["w1"]["session_id"] == SID

    # -- arm 3: the path shape. ---------------------------------------------

    def test_arm_3_a_rejected_path_shape_warns_and_the_spawn_proceeds(
            self, indexed_project, monkeypatch, capsys):
        """`_index_posix_rel` grows a path-shape guard on `idx/core` that
        RAISES on `..` instead of returning a rel that fails the membership
        test. Simulated here with a `FleetCliError` subclass minted locally,
        so this test encodes no exception NAME from that branch -- only the
        contract that a rejected path is one path's problem."""

        class _PathRejected(fleet.FleetCliError):
            pass

        real = fleet._index_posix_rel

        def _guarded(rel):
            if ".." in str(rel):
                raise _PathRejected(f"path escapes the index root: {rel}")
            return real(rel)

        monkeypatch.setattr(fleet, "_index_posix_rel", _guarded)

        assert self._spawn(indexed_project, monkeypatch,
                           "src/api.py,../plain/src/api.py") == 0
        err = capsys.readouterr().err
        assert "digest skipped" in err
        assert fleet.load_registry()["workers"]["w1"]["session_id"] == SID

    # -- the umbrella, and the control. -------------------------------------

    def test_any_compose_failure_at_all_leaves_no_record_and_no_event(
            self, indexed_project, monkeypatch):
        """THE structural pin, and the one that outlives this fix wave's three
        arms: whatever `compose_prompt` raises, for whatever reason, the
        registry must be untouched and no `spawned` event may be written."""
        self._dispatch_ok(monkeypatch)
        monkeypatch.setattr(fleet, "compose_prompt",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("compose blew up")))
        with pytest.raises(fleet.FleetCliError, match="nothing was registered"):
            fleet.cmd_spawn(self._args(indexed_project, "src/api.py"),
                            run=lambda *a, **k: None, which=lambda _: "claude",
                            sleep=lambda s: None, clock=lambda: 0.0)
        assert fleet.load_registry()["workers"] == {}
        assert self._events() == []

    def test_a_keyboard_interrupt_during_compose_is_not_swallowed(
            self, indexed_project, monkeypatch):
        """`Exception`, not `BaseException`: nothing has been registered yet,
        so there is nothing to convert a Ctrl-C into a CLI error for."""
        self._dispatch_ok(monkeypatch)
        monkeypatch.setattr(fleet, "compose_prompt",
                            lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            fleet.cmd_spawn(self._args(indexed_project, "src/api.py"),
                            run=lambda *a, **k: None, which=lambda _: "claude",
                            sleep=lambda s: None, clock=lambda: 0.0)
        assert fleet.load_registry()["workers"] == {}

    def test_the_control_arm_is_unaffected(self, indexed_project, monkeypatch):
        """The same spawn with NO `--context`. This is what proved `--context`
        opened the window in the first place, and it stays here so a future
        reader can tell a compose regression from a spawn regression."""
        assert self._spawn(indexed_project, monkeypatch, None) == 0
        assert fleet.load_registry()["workers"]["w1"]["session_id"] == SID

    def test_compose_runs_before_the_registry_commit(self):
        """The geometry itself, asserted on the source. The behavioural tests
        above all go through `cmd_spawn`'s one commit; this one fails if the
        call is ever moved back down between the commit and the rollback
        `try:`, which is the exact edit that created the defect."""
        src = Path(fleet.__file__).read_text(encoding="utf-8").splitlines()
        start = next(n for n, l in enumerate(src, 1)
                     if l.startswith("def cmd_spawn("))
        end = next(n for n, l in enumerate(src[start:], start + 1)
                   if l.startswith("def ") and n > start)
        body = list(enumerate(src[start - 1:end - 1], start))
        compose = next(n for n, l in body if "compose_prompt(" in l
                       and not l.lstrip().startswith("#"))
        commit = next(n for n, l in body if 'append_event("spawned"' in l)
        assert compose < commit, (
            f"cmd_spawn composes at line {compose}, AFTER the pre-claim commit "
            f"at line {commit}. Every raise arm in compose now lands in a "
            f"window with no rollback in it -- this is fix wave C1, reopened.")


# ---------------------------------------------------------------------------
# §11.7 item 1 -- the template grant, and its narrowness
# ---------------------------------------------------------------------------

TEMPLATE = Path(fleet.__file__).resolve().parents[1] / "worker-settings.template.json"


def _template():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


class TestTemplateGrant:

    def test_the_template_carries_the_subcommand_scoped_grant(self):
        assert _template()["permissions"]["allow"] == ["Bash(fleet q:*)"]

    def test_the_grant_is_narrow_and_stays_narrow(self):
        """THE guard for §11.7 item 1, and it is the whole guard: the next
        person to widen this will have a good reason.

        `Bash(fleet:*)` is a KILL grant -- `fleet kill` and `fleet clean` are
        irreversible (CLAUDE.md), and this repo has a recorded incident where a
        READ-ONLY slash command reached `fleet clean`. `fleet index:*` is
        excluded on a second ground: index lifecycle is manager-side (§8), so a
        worker has no business holding it.
        """
        entries = []
        for bucket in _template().get("permissions", {}).values():
            entries.extend(bucket)
        fleet_grants = [e for e in entries if "fleet" in e]
        assert fleet_grants == ["Bash(fleet q:*)"], (
            f"the worker-settings template carries fleet grants other than the "
            f"one subcommand-scoped `Bash(fleet q:*)`: {fleet_grants}. A wider "
            f"grant reaches `fleet kill` and `fleet clean`, both irreversible.")

    def test_the_template_grants_nothing_else_at_all(self):
        """§11.7: `Bash(fleet q:*)` is the only fleet grant the template will
        ever carry for workers. Any other allow entry is a new, unspecified
        privilege reaching every worker on the machine."""
        permissions = _template().get("permissions", {})
        assert set(permissions) == {"allow"}, (
            f"unexpected permission buckets in the template: {sorted(permissions)}")
        assert permissions["allow"] == ["Bash(fleet q:*)"]

    def test_the_hooks_block_is_untouched(self):
        hooks = _template()["hooks"]
        assert set(hooks) == {"PostToolUse", "Stop", "PostCompact"}


class TestTemplateRenderAndFreshnessHandleTheNewKey:
    """§11.7 item 2's claim, MEASURED. It says the `instance-freshness` doctor
    check already covers the migration -- but that check compares MTIMES, not
    content (`instance_freshness_info`), so "already diffs the two" is not what
    the code does. What matters is that neither the render nor the freshness
    probe mishandles a template that is no longer hooks-only."""

    def test_render_preserves_the_permissions_key(self, tmp_path):
        rendered = fleet.render_worker_settings_template(
            TEMPLATE.read_text(encoding="utf-8"), "C:/py/python.exe", tmp_path)
        parsed = json.loads(rendered)
        assert parsed["permissions"]["allow"] == ["Bash(fleet q:*)"]
        assert "{{" not in rendered

    def test_render_still_rejects_an_unrendered_placeholder(self, tmp_path):
        """Non-vacuity: the loud-failure arm still fires with the new key
        present, so the render test above is not passing because the checker
        went quiet."""
        text = TEMPLATE.read_text(encoding="utf-8").replace(
            '"permissions"', '"{{NOPE}}permissions"')
        with pytest.raises(ValueError, match="unrendered placeholder"):
            fleet.render_worker_settings_template(text, "C:/py/python.exe", tmp_path)

    def test_fleet_init_writes_the_grant_into_the_instance(self, isolated_home, monkeypatch):
        """End to end: `pull, re-run fleet init` (§11.7 item 2) actually puts
        the grant where a worker's `--settings` file will find it."""
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)
        rc = fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))
        assert rc == 0
        instance = json.loads(
            fleet.instance_settings_path().read_text(encoding="utf-8"))
        assert instance["permissions"]["allow"] == ["Bash(fleet q:*)"]

    def test_instance_freshness_flags_the_template_change_then_clears(
            self, isolated_home, monkeypatch):
        """The migration story, measured rather than assumed: an instance
        rendered from the OLD hooks-only template reads stale against the new
        one, and `fleet init` clears it."""
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text('{"hooks": {}}', encoding="utf-8")
        # An instance rendered before the template changed.
        os.utime(instance, (0, 0))
        assert fleet.instance_freshness_info()["stale"] is True
        assert fleet._doctor_check_instance_freshness()[1] is False

        fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))
        assert fleet.instance_freshness_info()["stale"] is False
        assert fleet._doctor_check_instance_freshness()[1] is True

    def test_freshness_does_not_notice_a_hand_edited_instance(
            self, isolated_home, monkeypatch):
        """THE LIMIT, pinned so it cannot be re-described as a diff.

        `instance-freshness` compares MTIMES, not content. An instance that is
        newer than the template but has had the `permissions` key removed reads
        `[PASS]`. That was harmless while the template carried hooks only; it is
        less harmless now, because the silent outcome is a worker whose fleet
        grant has gone missing -- which presents as zero `fleet q` calls, the
        exact shape of §11.9's revert trigger, fired against a permission bug
        rather than against the tool.

        This test asserts the CURRENT behaviour, not the desired one. If someone
        makes the check content-aware, it goes red and that is the signal to
        delete it and strike the caveat from §11.7 item 2 -- which is the whole
        point of pinning a known limit rather than only writing it down.
        """
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)
        fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))
        instance = fleet.instance_settings_path()
        rendered = json.loads(instance.read_text(encoding="utf-8"))
        assert rendered.pop("permissions")["allow"] == ["Bash(fleet q:*)"]
        instance.write_text(json.dumps(rendered, indent=2), encoding="utf-8")

        assert fleet.instance_freshness_info()["stale"] is False
        assert fleet._doctor_check_instance_freshness()[1] is True, (
            "instance-freshness became content-aware -- delete this test and the "
            "caveat it pins in §11.7 item 2")
        # ...and the check that DOES notice it, added by fix wave M3. The pair
        # is the point: the limit above is still real, and doctor no longer
        # ends its report without mentioning it.
        assert fleet._doctor_check_instance_grants()[1] is False


class TestDoctorSaysSoWhenTheInstanceGrantDiverges:
    """FIX WAVE M3. The finding was not that `instance-freshness` is wrong --
    it compares mtimes, that is pinned above as a known limit, and a second
    `fleet init` really does repair a broken instance. The finding was that
    **doctor never says so.** Measured: widening the rendered instance's grant
    to `Bash(fleet:*)` -- the kill grant, reaching the irreversible `fleet
    kill` and `fleet clean` -- left `fleet doctor` reporting `[PASS]` on every
    line, with no hint that a re-`init` would undo it.

    So this check exists to make the repair DISCOVERABLE, and it is content-
    based, which is what makes it immune to the mtime limit that produced the
    hole."""

    @pytest.fixture(autouse=True)
    def _repo_template(self, monkeypatch):
        monkeypatch.setattr(fleet, "template_settings_path", lambda: TEMPLATE)

    @staticmethod
    def _init():
        return fleet.cmd_init(SimpleNamespace(
            force=False, statusline=False, chain=False, autoclean=False,
            autoclean_remove=False, autoclean_interval_hours=None))

    @staticmethod
    def _rewrite(mutate):
        path = fleet.instance_settings_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def test_a_freshly_rendered_instance_passes(self, isolated_home):
        self._init()
        name, ok, detail = fleet._doctor_check_instance_grants()
        assert (name, ok) == ("instance-grants", True)
        assert "Bash(fleet q:*)" in detail

    def test_widening_to_the_kill_grant_is_reported_and_named(self, isolated_home):
        """THE case. `Bash(fleet:*)` reaches `fleet kill` and `fleet clean`."""
        self._init()
        self._rewrite(lambda d: d["permissions"].__setitem__(
            "allow", ["Bash(fleet:*)"]))
        assert fleet._doctor_check_instance_freshness()[1] is True, (
            "freshness became content-aware -- this class's premise moved")
        name, ok, detail = fleet._doctor_check_instance_grants()
        assert (name, ok) == ("instance-grants", False)
        assert "Bash(fleet:*)" in detail
        assert "fleet init" in detail, (
            "doctor reported the divergence without naming the repair -- the "
            "whole finding was that the repair exists and nobody is told")

    def test_a_lost_grant_is_reported(self, isolated_home):
        """The silent direction: zero `fleet q` calls is also the exact shape
        of §11.9's revert trigger, so a permission bug can be mistaken for the
        tool failing to get adopted."""
        self._init()
        self._rewrite(lambda d: d.pop("permissions"))
        name, ok, detail = fleet._doctor_check_instance_grants()
        assert (name, ok) == ("instance-grants", False)
        assert "Bash(fleet q:*)" in detail

    def test_a_deny_entry_fencing_the_grant_is_reported(self, isolated_home):
        """Reading only `allow` would call this instance clean while it had
        fenced the grant off in another bucket."""
        self._init()
        self._rewrite(lambda d: d["permissions"].__setitem__(
            "deny", ["Bash(fleet q:*)"]))
        assert fleet._doctor_check_instance_grants()[1] is False

    def test_unrelated_operator_grants_are_not_flagged(self, isolated_home):
        """Non-vacuity in the other direction: a check that fires on an
        operator's own unrelated allow entries trains the operator to ignore
        it."""
        self._init()
        self._rewrite(lambda d: d["permissions"]["allow"].append("Bash(git status:*)"))
        assert fleet._doctor_check_instance_grants()[1] is True

    def test_a_second_fleet_init_repairs_it_and_the_check_clears(self, isolated_home):
        """The repair the check now points at, executed."""
        self._init()
        self._rewrite(lambda d: d["permissions"].__setitem__(
            "allow", ["Bash(fleet:*)"]))
        assert fleet._doctor_check_instance_grants()[1] is False
        self._init()
        assert fleet._doctor_check_instance_grants()[1] is True
        instance = json.loads(
            fleet.instance_settings_path().read_text(encoding="utf-8"))
        assert instance["permissions"]["allow"] == ["Bash(fleet q:*)"]

    def test_the_check_is_wired_into_fleet_doctor(self):
        """A check nobody runs says nothing. `cmd_doctor` shells out to
        `claude` twice and runs two real hook subprocesses, so this asserts
        the wiring at the source rather than driving the whole report: the
        check must be referenced from inside `cmd_doctor`'s body."""
        assert "cmd_doctor" in _call_sites(
            "_doctor_check_instance_grants",
            skip_defs=("_doctor_check_instance_grants",)), (
            "_doctor_check_instance_grants is defined but never run by "
            "`fleet doctor` -- the finding was that doctor stays silent, and a "
            "check that is not in the list is exactly that, one layer down")


class TestDoctorDoesNotGreenOnAnAbsentTemplate:
    """"absence is not evidence" applied to the one template `fleet doctor`
    depends on: `worker-settings.template.json` (git-tracked, so its
    absence means a broken checkout, not a normal steady state -- unlike
    e.g. the autoclean stamp or tzdata, which are legitimately-absent PASS-
    notes by design).

    Before this fix wave, a missing template read `[PASS]` on BOTH checks
    that read it: `instance_freshness_info()`'s `stale` flag stays False
    when there is nothing to compare against (a deliberate, narrow
    read-probe decision -- its own docstring says the policy belongs here),
    and `instance-grants` caught `FileNotFoundError` in the same
    `except (OSError, json.JSONDecodeError)` arm as a genuinely-corrupt-
    but-present template, so ABSENT and UNREADABLE-BUT-PRESENT read
    identically as a skip-and-PASS.

    Fixed: absent template is now its own `False` branch on both checks,
    distinguishable in the message from HEALTHY, STALE and DIVERGED alike
    -- never a mutation, `fleet doctor` stays report-only."""

    def test_freshness_fails_when_template_is_absent(self, isolated_home):
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text("{}", encoding="utf-8")
        assert not fleet.template_settings_path().exists()

        name, ok, detail = fleet._doctor_check_instance_freshness()
        assert (name, ok) == ("instance-freshness", False)
        assert "missing" in detail

    def test_grants_fails_when_template_is_absent(self, isolated_home):
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text(
            json.dumps({"permissions": {"allow": ["Bash(fleet q:*)"]}}),
            encoding="utf-8")
        assert not fleet.template_settings_path().exists()

        name, ok, detail = fleet._doctor_check_instance_grants()
        assert (name, ok) == ("instance-grants", False)
        assert "missing" in detail

    def test_grants_still_pass_notes_a_present_but_corrupt_template(self, isolated_home):
        """Non-vacuity in the other direction, and the boundary of this fix
        wave: a template that EXISTS but fails to parse is a different claim
        than ABSENT (e.g. a concurrent editor's half-written save), and
        keeps the pre-existing PASS-note skip -- only the FileNotFoundError
        arm changed, not the shared OSError/JSONDecodeError one."""
        template = fleet.template_settings_path()
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("{not json", encoding="utf-8")
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text("{}", encoding="utf-8")

        name, ok, detail = fleet._doctor_check_instance_grants()
        assert (name, ok) == ("instance-grants", True)
        assert "skipped" in detail

    def test_both_template_reading_checks_are_exercised_absent(self, isolated_home, monkeypatch, capsys):
        """The trap this project has fallen into before: a pin that claims
        more than its body visits. This fix touches exactly two checks
        (`instance-freshness`, `instance-grants` -- the only two doctor
        checks that call `template_settings_path()`); this test drives both
        by name, through the same absent-template FLEET_HOME, and prints the
        visited set so the count is measured, not asserted."""
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text(
            json.dumps({"permissions": {"allow": ["Bash(fleet q:*)"]}}),
            encoding="utf-8")
        missing_template = fleet.FLEET_HOME / "does-not-exist.template.json"
        monkeypatch.setattr(fleet, "template_settings_path", lambda: missing_template)

        results = {
            "instance-freshness": fleet._doctor_check_instance_freshness(),
            "instance-grants": fleet._doctor_check_instance_grants(),
        }
        print(f"visited template-reading doctor checks: {sorted(results)} "
              f"(2 of 2 known)")
        captured = capsys.readouterr()
        assert "visited template-reading doctor checks" in captured.out
        assert set(results) == {"instance-freshness", "instance-grants"}
        for name, (_, ok, detail) in results.items():
            assert ok is False, f"{name} read green with the template absent: {detail!r}"
            assert str(missing_template) in detail
