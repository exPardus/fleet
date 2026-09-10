"""THE SUBPROCESS HALF OF `~/.claude` ISOLATION -- the seam `conftest.py`'s
autouse `_never_touch_the_real_home` cannot reach.

WHAT WAS BROKEN, AND WHY THE EXISTING SANDBOX DID NOT COVER IT. That fixture
monkeypatches four helpers BY NAME inside the pytest interpreter. A subprocess
is a fresh interpreter: it re-imports `fleet` and gets the SHIPPED
`homes_list_path`, which resolves from `Path.home()` -- i.e. from `$HOME`, which
nothing overrode. So every test that launched a real `fleet.py` or
`fleet_statusline.py` with `{**os.environ, "FLEET_HOME": tmp_path}` overrode the
home fleet ACTS on and left the home fleet RESOLVES `~/.claude` from pointing at
the operator's real machine. Two seams, two populations. Conflating them is how
this survived from multi-fleet slice (a) to w60.

SEVERITY, MEASURED RATHER THAN ASSERTED (`docs/lanes/w60-homeseam.md` §5). It is
not merely a read. `resolve_home` runs `lookup_home_for_sid` BEFORE step 1, on
every non-exempt verb, so a listed home that claims the child's sid RETARGETS
the verb off `FLEET_HOME` entirely. Driven end to end with a one-home list and
`fleet kill --yes`: the bystander home's registry gained `"status": "dead"` and
the sandbox `FLEET_HOME` was untouched. A destructive verb wrote outside the
fixture. That is what the seam below prevents.

WHAT COVERS WHICH POPULATION, stated plainly because the conflation is the
defect:

  * IN-PROCESS tests -> `conftest._never_touch_the_real_home` (monkeypatch by
    name). Pinned by `test_slice_e_pins.py::TestTheConftestRedirectReaches
    EveryFile`.
  * SUBPROCESS drives -> `conftest.child_env` (a redirected `$HOME` /
    `%USERPROFILE%` in the child environment). Pinned HERE.
  * WRITES to the real list, from either population -> the session-scoped
    `conftest._the_real_homes_list_is_untouched_afterwards`. That guard sees an
    append. It does NOT see a read, and it does not see a write into a home the
    list merely NAMES -- which is the hazard measured above.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import fleet
from conftest import child_env, subprocess_home  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FLEET_PY = REPO / "bin" / "fleet.py"
STATUSLINE = REPO / "bin" / "fleet_statusline.py"
HOOKS = REPO / "bin" / "hooks"

# The REAL home, resolved the way a child resolves it. Deliberately not
# `fleet.homes_list_path()`, which the autouse sandbox has already redirected --
# the same reason `conftest.real_homes_list_path` spells it out by hand.
REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"

# SYNTHETIC. This value is handed to a CHILD as `CLAUDE_CODE_SESSION_ID` and
# the child drives a real `fleet kill`, so it is the input to §5 step 2's
# lookup over `resolution_population()` -- which always includes the
# `INSTALL_ROOT` home, whatever `$HOME` this seam redirects. The value that
# stood here until w61 was a real historical session id of this project;
# `tests/test_sid_collision.py` pins that no caller sid a test hands a child
# is an RFC-4122 v4 UUID, which is the only shape `claude` issues.
SID = "fa15e51d-0000-0000-0000-000000000004"

_PROBE = (
    "import sys, json\n"
    f"sys.path.insert(0, {str(REPO / 'bin')!r})\n"
    "import fleet\n"
    "print(json.dumps({'path': str(fleet.homes_list_path()),\n"
    "                  'members': fleet.read_homes_list()['members']}))\n"
)


def _probe(env):
    """`(path, members)` as a FRESH interpreter resolves them."""
    proc = subprocess.run([sys.executable, "-c", _PROBE], env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return Path(data["path"]), data["members"]


def _seed_home(d, workers):
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("state", "mailbox", "logs"):
        (d / sub).mkdir(exist_ok=True)
    (d / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8")
    return d


def _rec(session_id=None, status="idle"):
    return {"status": status, "spawned_by": "a-manager", "session_id": session_id,
            "task": "t", "dir": ".", "started_at": 0}


def _plant_list(sandbox, homes):
    """Write a homes list into the home a `child_env(sandbox)` child will see."""
    path = subprocess_home(sandbox) / ".claude" / "fleet-homes.list"
    path.write_text("".join(f"{h}\n" for h in homes), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. The seam, both directions. These are the discriminator: each one goes RED
#    if `child_env` stops redirecting, and RED if `Path.home()` stops reading
#    the variable it redirects.
# ---------------------------------------------------------------------------

class TestTheSeamDecidesWhichListAChildReads:

    def test_with_the_seam_a_child_resolves_the_sandbox_list(self, tmp_path):
        a, b = tmp_path / "homeA", tmp_path / "homeB"
        _plant_list(tmp_path, [a, b])
        path, members = _probe(child_env(tmp_path, FLEET_HOME=str(tmp_path)))
        assert path == subprocess_home(tmp_path) / ".claude" / "fleet-homes.list"
        assert members == [fleet.home_identity(a), fleet.home_identity(b)], (
            "the child resolved a homes list, but not the sandbox's -- so "
            "`child_env` is not in force and the drive is reading the "
            "operator's machine.")

    def test_without_the_seam_the_same_child_resolves_the_real_one(self, tmp_path):
        """THE CONTROL. Reproduces the pre-fix environment EXACTLY -- the
        `{**os.environ, "FLEET_HOME": ...}` the four shipped sites built -- and
        asserts it reaches the operator's real path.

        This test is the reason the fix is not decorative: without it, every
        assertion above would pass just as happily on a machine where
        `Path.home()` ignored `$HOME`, and the seam would be a no-op nobody
        noticed. It RESOLVES the real path and reads it; it never creates it,
        and the session guard beside it proves the file did not move."""
        pre_fix = {**os.environ, "FLEET_HOME": str(tmp_path)}
        path, _ = _probe(pre_fix)
        assert path == REAL_LIST, (
            "the pre-fix environment no longer reaches the real home. Either "
            "`homes_list_path` stopped resolving from `Path.home()` or the "
            "harness changed -- either way `child_env`'s docstring is now "
            "wrong and this whole file needs re-deriving.")

    def test_the_two_arms_disagree(self, tmp_path):
        """Belt and braces: a seam that resolved the same path either way would
        satisfy both tests above only if the sandbox WERE the real home."""
        _plant_list(tmp_path, [tmp_path / "homeA"])
        with_seam, _ = _probe(child_env(tmp_path, FLEET_HOME=str(tmp_path)))
        without, _ = _probe({**os.environ, "FLEET_HOME": str(tmp_path)})
        assert with_seam != without


# ---------------------------------------------------------------------------
# 2. The three ways to get the redirect WRONG. All measured on this host; each
#    is a shape a reader would reasonably reach for instead.
# ---------------------------------------------------------------------------

class TestUnsettingIsNotTheSeam:
    """`Path.home()` is `os.path.expanduser("~")`, and on POSIX a MISSING `HOME`
    falls back to `pwd.getpwuid(os.getuid()).pw_dir` -- straight back to the
    operator's real home. Deleting the variable looks like isolation and is
    not."""

    @pytest.mark.skipif(os.name == "nt", reason="the pwd fallback is POSIX-only")
    def test_deleting_home_still_reaches_the_real_home(self, tmp_path):
        env = {**os.environ, "FLEET_HOME": str(tmp_path)}
        env.pop("HOME", None)
        path, _ = _probe(env)
        assert path == REAL_LIST

    @pytest.mark.skipif(os.name == "nt", reason="POSIX expanduser semantics")
    def test_an_empty_home_is_a_third_wrong_answer(self, tmp_path):
        """`posixpath.expanduser` takes the empty string at its word rather than
        falling back, so `HOME=""` yields `/.claude/...` -- neither the sandbox
        nor the real home, and on a writable root a place a stray append could
        actually land."""
        env = {**os.environ, "FLEET_HOME": str(tmp_path), "HOME": ""}
        path, _ = _probe(env)
        assert path != REAL_LIST
        assert path != subprocess_home(tmp_path) / ".claude" / "fleet-homes.list"
        assert path == Path("/") / ".claude" / "fleet-homes.list"

    def test_child_env_never_produces_an_empty_or_missing_home(self, tmp_path):
        env = child_env(tmp_path)
        assert env.get("HOME"), "child_env produced an empty or missing HOME"
        assert Path(env["HOME"]).is_dir()


class TestTheWindowsArmIsCarried:
    """`ntpath.expanduser` NEVER reads `HOME`. It takes `USERPROFILE` if present,
    else `HOMEDRIVE` + `HOMEPATH`. This repo still supports the Windows host, so
    a POSIX-only redirect would be a seam that silently does nothing there.

    The env dict is what is asserted, because that is the part observable from
    every host. The Windows RESOLUTION itself is read from the stdlib rather
    than driven (`Lib/ntpath.py::expanduser`), and is BELIEVED, not measured, on
    a POSIX box."""

    def test_userprofile_is_set_to_the_same_directory(self, tmp_path):
        env = child_env(tmp_path)
        assert env["USERPROFILE"] == env["HOME"] == str(subprocess_home(tmp_path))

    def test_the_homedrive_pair_is_dropped_rather_than_left_standing(self, tmp_path):
        """`USERPROFILE` outranks the pair today, so a leftover pair is dead
        weight -- but it would become live the moment a caller overrode
        `USERPROFILE` through `**over`, and a seam that fails open on a keyword
        argument is not a seam."""
        env = child_env(tmp_path)
        assert "HOMEDRIVE" not in env
        assert "HOMEPATH" not in env

    def test_over_wins_over_the_defaults(self, tmp_path):
        env = child_env(tmp_path, FLEET_HOME="X", HOME="Y")
        assert env["FLEET_HOME"] == "X"
        assert env["HOME"] == "Y"


# ---------------------------------------------------------------------------
# 3. The teeth, at the verb. Path resolution is not the claim that matters --
#    the claim is that a REAL verb's ANSWER was a function of the machine.
# ---------------------------------------------------------------------------

class TestARealKillsAnswerFollowsTheSeam:
    """`apply_resolved_home` -> `resolve_home` -> `lookup_home_for_sid` ->
    `resolution_population` -> `read_homes_list` runs BEFORE step 1, on every
    verb outside `TERMINUS_EXEMPT_VERBS`. So `fleet kill` reads the list, and
    what the list says changes what `kill` does."""

    def _drive(self, sandbox, *argv, **over):
        # The env is built HERE rather than passed in, so the census lint below
        # can see `child_env` at the launch site. A helper that takes an opaque
        # `env` parameter is exactly the shape that hid the defect.
        return subprocess.run([sys.executable, str(FLEET_PY), *argv],
                              capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=90,
                              env=child_env(sandbox, **over))

    def test_two_sandbox_homes_claiming_the_sid_reach_the_ambiguity_refusal(
            self, tmp_path):
        """The reach proof. If `child_env` stopped redirecting, the child would
        read the real machine's list -- absent on an ordinary single-fleet box
        -- and this refusal would never fire."""
        a = _seed_home(tmp_path / "homeA", {"w": _rec(SID)})
        b = _seed_home(tmp_path / "homeB", {"w": _rec(SID)})
        work = _seed_home(tmp_path / "work", {"victim": _rec(None)})
        _plant_list(tmp_path, [a, b])
        out = self._drive(tmp_path, "kill", "victim",
                          FLEET_HOME=str(work), CLAUDE_CODE_SESSION_ID=SID)
        blob = out.stdout + out.stderr
        assert out.returncode == 1, blob
        assert "member of 2 fleet homes" in blob, blob
        assert str(a) in blob and str(b) in blob, blob

    def test_a_listed_home_that_claims_the_sid_retargets_a_destructive_verb(
            self, tmp_path):
        """THE HAZARD ITSELF, reproduced against a FAKE machine. One listed home
        claims the sid, `FLEET_HOME` names a different one -- and `kill --yes`
        marks the record dead in the LISTED home while `FLEET_HOME`'s registry
        is untouched.

        Stated as a test rather than a paragraph because the pre-fix four sites
        were one `fleet homes --add` away from this, with the operator's own
        fleet in the bystander role."""
        listed = _seed_home(tmp_path / "listed", {"prod": _rec(SID)})
        work = _seed_home(tmp_path / "work", {"prod": _rec(None)})
        _plant_list(tmp_path, [listed])
        out = self._drive(tmp_path, "kill", "prod", "--yes",
                          FLEET_HOME=str(work), CLAUDE_CODE_SESSION_ID=SID)
        assert out.returncode == 0, out.stdout + out.stderr

        def status(home):
            return json.loads((home / "state" / "fleet.json")
                              .read_text(encoding="utf-8"))["workers"]["prod"]["status"]
        assert status(listed) == "dead", (
            "the retarget did not happen -- if `resolve_home` no longer "
            "outranks FLEET_HOME on a lookup hit, this whole file's severity "
            "argument needs re-deriving")
        assert status(work) == "idle"


class TestTheStatuslineRenderFollowsTheSeam:
    def test_the_render_changes_with_the_sandbox_list(self, tmp_path):
        """The statusline calls `fleet.resolution_population()` too, so its
        RENDER was a function of the operator's machine even though its exit
        code was not -- which is why the two shipped statusline tests (rc == 0,
        no traceback) stayed green over the defect."""
        a = _seed_home(tmp_path / "homeA", {"w": _rec(SID)})
        b = _seed_home(tmp_path / "homeB", {"w": _rec(SID)})
        work = _seed_home(tmp_path / "work", {})
        _plant_list(tmp_path, [a, b])
        proc = subprocess.run(
            [sys.executable, str(STATUSLINE)],
            input=json.dumps({"session_id": SID}), capture_output=True,
            text=True, timeout=60,
            env=child_env(tmp_path, FLEET_HOME=str(work)))
        assert proc.returncode == 0, proc.stderr
        assert "ambiguous" in proc.stdout, proc.stdout


# ---------------------------------------------------------------------------
# 4. The census pin. The four sites w59 reported were what ONE lane happened to
#    see; the AST found more, and it will keep finding them. A fix to four named
#    line numbers is a fix that rots on the next `git mv`.
# ---------------------------------------------------------------------------

# Tokens that identify a child as "a real fleet interpreter" -- something whose
# `main()`/`render` reaches `Path.home()`. Matched against the UNPARSED first
# argument, so a helper that builds the path in a variable is caught by the
# variable's own name (`fleet_py`, `STATUSLINE`) rather than needing constant
# folding.
_FLEET_CHILD_TOKENS = ("fleet.py", "fleet_statusline.py", "fleet_py",
                       "fleet.__file__", "STATUSLINE", "FLEET_PY")

_LAUNCHERS = ("run", "Popen", "call", "check_call", "check_output")

# EVERY EXEMPTION IS A SENTENCE, NOT A LINE NUMBER. Keyed by
# `(relative path, enclosing scope)`.
_EXEMPT = {
    ("tests/integration/test_native_pin.py", "Sandbox.fleet"):
        "LIVE TIER, AND THE SEAM WOULD BREAK IT. `Sandbox.fleet` drives real "
        "`fleet spawn`, which launches the real `claude` binary through "
        "`_worker_env` -- a plain `dict(os.environ)`, so a redirected $HOME "
        "propagates to `claude` and takes its credentials in `~/.claude` with "
        "it. This lane could not measure that (the tier is FLEET_LIVE-gated "
        "and costs real sessions), so it is REPORTED rather than changed: "
        "docs/lanes/w60-homeseam.md §7, open item 1.",
    ("tests/integration/test_sup_tombstone_live.py", "Sandbox.fleet"):
        "Same shape, same tier, same reason as the entry above.",
}


def census_home_seam_sites(src, relpath):
    """Every subprocess launch in `src` that drives a real fleet interpreter,
    as `(relpath, lineno, scope, env_source, ok)`.

    `ok` is True when the environment handed to the child is derived from
    `conftest.child_env` -- directly, or through a local name assigned from it.
    Module-level and parameterised on the source text so the seeds below can
    drive it against a planted offender; a lint that can only be run over the
    real tree is a lint nobody has watched fail.

    WHERE THIS LINT DELIBERATELY STOPS, said out loud so the next reader does
    not mistake it for completeness. Its subject is *"a child whose argv NAMES
    `bin/fleet.py` or `bin/fleet_statusline.py`"*. It does NOT census
    `[sys.executable, "-c", <payload>]` children that import fleet from a
    string, and there are five of those in this suite
    (`test_core.py::_fleet_home_in_fresh_interpreter`,
    `test_install_home_split.py`'s three probes, and `_probe` in this file).
    Four of the five were read at w60 and print an import-time attribute --
    `fleet.FLEET_HOME`, `fleet.INSTALL_ROOT`, a hook's `_fleet_home()` -- none
    of which resolves `Path.home()`. `fleet.py` reaches `Path.home()` from no
    module-level assignment at all, so the bare import is inert: verified by
    AST over `ast.parse(...).body`, not by reading. The fifth is `_probe` in
    THIS file, which calls `homes_list_path()` and `read_homes_list()` on
    purpose -- it is the measuring instrument, and it is handed a `child_env`
    in every arm except the two controls that exist to reach the real path.
    All of that is a MEASURED fact about today's five, not a property of the
    shape: a `-c` payload that called `main()` would slip past this lint. Widening the matcher to unparse string payloads was
    rejected as guesswork over a moving target; the honest boundary is written
    here instead of implied."""
    import ast
    tree = ast.parse(src)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def scope_of(node):
        names, cur = [], parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(cur.name)
            cur = parents.get(cur)
        return ".".join(reversed(names)) or "<module>"

    def enclosing_func(node):
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
            cur = parents.get(cur)
        return None

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr in _LAUNCHERS
                and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
            continue
        if not node.args:
            continue
        argv = ast.unparse(node.args[0])
        if not any(tok in argv for tok in _FLEET_CHILD_TOKENS):
            continue
        env_src = None
        for kw in node.keywords:
            if kw.arg == "env":
                env_src = ast.unparse(kw.value)
        sources = [env_src or ""]
        if env_src and env_src.isidentifier():
            func = enclosing_func(node)
            for a in ast.walk(func) if func else []:
                if isinstance(a, ast.Assign):
                    for t in a.targets:
                        if isinstance(t, ast.Name) and t.id == env_src:
                            sources.append(ast.unparse(a.value))
        ok = any("child_env" in s for s in sources)
        out.append((relpath, node.lineno, scope_of(node), env_src, ok))
    return out


def _tests_root():
    return Path(__file__).resolve().parent


class TestEveryFleetInterpreterDriveCarriesTheSeam:
    """The lint, over the real tree."""

    def _census(self):
        root = _tests_root()
        rows = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            rows += census_home_seam_sites(
                path.read_text(encoding="utf-8"), rel)
        return rows

    def test_the_census_is_not_empty(self):
        """A lint whose subject list silently goes empty passes vacuously
        forever. This is the seed that says it found something to check."""
        rows = self._census()
        assert len(rows) >= 6, rows

    def test_every_site_carries_child_env_or_a_written_exemption(self):
        offenders = [(rel, line, scope, env) for rel, line, scope, env, ok
                     in self._census()
                     if not ok and (rel, scope) not in _EXEMPT]
        assert not offenders, (
            "these subprocess drives launch a real fleet interpreter with an "
            "environment not derived from `conftest.child_env`, so the child "
            "resolves `~/.claude` from the OPERATOR's home rather than the "
            "fixture's: " + repr(offenders) + ". Either route the env through "
            "`child_env(<a tmp dir>, ...)` or add an entry to `_EXEMPT` "
            "saying, in a sentence, why this child cannot be redirected.")

    def test_no_exemption_is_stale(self):
        """An exemption for a site that no longer exists is a sentence nobody
        will re-read, and it hides the next one that lands on the same scope."""
        live = {(rel, scope) for rel, _, scope, _, _ in self._census()}
        stale = sorted(k for k in _EXEMPT if k not in live)
        assert not stale, (
            f"these `_EXEMPT` entries no longer name a real drive: {stale}")


class TestTheCensusLintCanActuallyFire:
    """Seeds. Each drives the lint over planted source, so a lint that
    silently stopped recognising the shape is caught here rather than by the
    next incident."""

    def test_a_bare_environ_copy_is_flagged(self):
        src = ('import subprocess, os, sys\n'
               'def d(tmp_path):\n'
               '    subprocess.run([sys.executable, str(FLEET_PY), "kill"],\n'
               '                   env={**os.environ, "FLEET_HOME": str(tmp_path)})\n')
        rows = census_home_seam_sites(src, "x.py")
        assert [(r[2], r[4]) for r in rows] == [("d", False)], rows

    def test_dict_os_environ_is_flagged_too(self):
        """The spelling the w59 brief's grep would have missed -- and the one
        the majority of this repo's drives actually use."""
        src = ('import subprocess, os, sys\n'
               'def d(tmp_path):\n'
               '    env = dict(os.environ)\n'
               '    env["FLEET_HOME"] = str(tmp_path)\n'
               '    subprocess.run([sys.executable, str(fleet_py)], env=env)\n')
        rows = census_home_seam_sites(src, "x.py")
        assert [(r[2], r[4]) for r in rows] == [("d", False)], rows

    def test_a_missing_env_kwarg_is_flagged(self):
        """`env=` omitted inherits the WHOLE parent environment, real $HOME
        included -- the same defect, spelled shorter."""
        src = ('import subprocess, sys\n'
               'def d():\n'
               '    subprocess.run([sys.executable, str(FLEET_PY), "status"])\n')
        rows = census_home_seam_sites(src, "x.py")
        assert [(r[2], r[3], r[4]) for r in rows] == [("d", None, False)], rows

    def test_a_child_env_site_is_clean(self):
        src = ('import subprocess, sys\n'
               'def d(tmp_path):\n'
               '    subprocess.run([sys.executable, str(FLEET_PY), "kill"],\n'
               '                   env=child_env(tmp_path, FLEET_HOME="x"))\n')
        assert [(r[2], r[4]) for r in census_home_seam_sites(src, "x.py")] \
            == [("d", True)]

    def test_child_env_through_a_local_name_is_clean(self):
        src = ('import subprocess, sys\n'
               'def d(tmp_path):\n'
               '    env = child_env(tmp_path, FLEET_HOME="x")\n'
               '    env.pop("CLAUDE_CODE_SESSION_ID", None)\n'
               '    subprocess.run([sys.executable, str(FLEET_PY)], env=env)\n')
        assert [(r[2], r[4]) for r in census_home_seam_sites(src, "x.py")] \
            == [("d", True)]

    def test_a_non_fleet_child_is_not_censused(self):
        """`git`, `sh`, and the hook scripts are a different population -- see
        `TestTheHookExemptionIsStructural` below."""
        src = ('import subprocess\n'
               'def d():\n'
               '    subprocess.run(["git", "status"])\n')
        assert census_home_seam_sites(src, "x.py") == []


class TestTheHookExemptionIsStructural:
    """THE LARGEST SUB-POPULATION OF SUBPROCESS DRIVES IN THIS SUITE IS THE
    HOOKS, and they are exempt for a reason that can stop being true.

    `bin/hooks/*.py` are standalone by doctrine (`stop_outcome.py`'s own
    docstring: *"Never imports bin/fleet.py -- duplicates its own tiny helpers"*)
    and none of them resolves a home from `Path.home()`. So a hook drive with an
    inherited `$HOME` reads nothing under `~/.claude` at all. That is a
    STRUCTURAL exemption, not a judgement call -- and this is what keeps it
    structural, instead of a fact that was true in w60."""

    HOME_READS = ("Path.home()", "expanduser", "USERPROFILE", "HOMEDRIVE",
                  '"HOME"', "'HOME'")

    def test_the_hook_scripts_exist(self):
        scripts = sorted(p.name for p in HOOKS.glob("*.py"))
        assert scripts, "no hook scripts found -- this pin went vacuous"

    @pytest.mark.parametrize("script", sorted(p.name for p in HOOKS.glob("*.py")))
    def test_no_hook_resolves_a_home_from_the_user_profile(self, script):
        src = (HOOKS / script).read_text(encoding="utf-8")
        found = [tok for tok in self.HOME_READS if tok in src]
        assert not found, (
            f"bin/hooks/{script} now reads {found} -- so the hook-drive "
            f"population is no longer exempt from the subprocess home seam. "
            f"Route those drives through `conftest.child_env` and move them "
            f"out of the exemption in docs/lanes/w60-homeseam.md §6.")

    def test_no_hook_imports_fleet(self):
        for path in sorted(HOOKS.glob("*.py")):
            src = path.read_text(encoding="utf-8")
            offending = [ln for ln in src.splitlines()
                         if ln.strip() in ("import fleet", "from fleet import")
                         or ln.strip().startswith("from fleet import ")]
            assert not offending, (
                f"{path.name} imports fleet, so it inherits every "
                f"`Path.home()` fleet resolves: {offending}")
