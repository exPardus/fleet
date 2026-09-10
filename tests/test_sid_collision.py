"""No caller sid a test hands a CHILD may be a sid `claude` could have issued.

WHY THIS FILE EXISTS (w61, and it was driven before it was written).

`bin/fleet.py`'s §5 step 2 resolves a home from the caller's session id BEFORE
`FLEET_HOME` is consulted, and step 2 OUTRANKS steps 3 and 4. The search space is
`resolution_population()` = the folded homes list UNION the legacy `INSTALL_ROOT`
home, and `INSTALL_ROOT` is `Path(__file__).resolve().parent.parent` --
deliberately not overridable by any environment variable, which is exactly why
w60's `child_env` `$HOME` redirect does not reach it (`conftest.child_env`'s own
docstring says so, and `docs/lanes/w60-homeseam.md` §6 filed it).

So: a suite run from a checkout that is ALSO a live fleet home -- which is how
this repo is routinely developed -- resolves every subprocess drive's caller sid
against that home's registry. Membership is the sid UNION (`_record_sids` =
`session_id` u `retired_sids`), so one ARCHIVED record carrying the sid is
enough. Until w61 three of those caller sids were real historical session ids of
this project, kept verbatim from measurement receipts.

MEASURED (docs/lanes/w61-sidcollision.md §2), driving the shipped
`TestAWorkerCallerIsNotExempt` against a planted bystander home:

    lookup(1a9374bd..) -> hit -> resolved step "lookup"
    $ fleet kill victim
    bystander/state/fleet.json  workers.victim.status  idle -> "dead"   WRITTEN
    fixture   /state/fleet.json  workers.victim.status  idle            UNTOUCHED

WHAT THIS FILE DOES AND DOES NOT DO. It removes the COLLISION, not the seam.
`INSTALL_ROOT` is still unoverridable and every one of those drives still READS
the install-root home's registry; `TestTheRetargetIsRealAndStillOpen` below
exists to keep that honest -- it PASSES by demonstrating the retarget, so nobody
reads this file as "the hole is closed".

THE PROPERTY, and why it is checkable rather than a convention: every session id
this project has ever been observed to carry is an RFC-4122 version-4 UUID --
MEASURED over all 22 sids in the operator's live registry plus the five real
historical sids quoted in this tree's receipts, 0 exceptions. A caller sid that
is NOT an RFC-4122 v4 therefore cannot be a sid `claude` issued, and so cannot
collide with any record in any home. The replacements stay UUID-SHAPED so
`fleet._SID_SHAPE_RE` sees what it always saw; they carry version nibble 0 and
the NCS variant, which `uuid.UUID(...).version is None` reports.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402
from conftest import child_env  # noqa: E402

TESTS = Path(__file__).resolve().parent
KEY = "CLAUDE_CODE_SESSION_ID"

# `test_destructive_guard.TestAWorkerCallerIsNotExempt.WORKER_SID`, duplicated
# as a literal so the census below can resolve it; the two are asserted equal
# where it is used.
SHIPPED_WORKER_SID = "fa15e51d-0000-0000-0000-000000000001"


def is_an_issuable_sid(value) -> bool:
    """True iff `value` has the shape of a session id `claude` can issue.

    RFC-4122 **and** version 4. Both halves matter: `uuid.UUID` happily parses
    `fa15e51d-0000-0000-0000-000000000001`, and it is `.version is None` (the
    variant bits say NCS, so the version field is not even meaningful) that
    makes it unissuable. A shape test alone would call it a real sid."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and parsed.variant == uuid.RFC_4122


# ---------------------------------------------------------------------------
# The census: every value a test puts into a CHILD's CLAUDE_CODE_SESSION_ID.
# ---------------------------------------------------------------------------
#
# SCOPE, STATED SO THE GAP IS NOT MISTAKEN FOR COVERAGE. This walks the three
# spellings that reach a child ENVIRONMENT -- a call keyword, a dict-literal
# key, and `env[KEY] = ...` -- and NOT `monkeypatch.setenv(KEY, ...)`, which is
# in-process only. In-process callers are sandboxed by conftest's autouse
# `_never_touch_the_real_home` (which redirects `homes_list_path`) and
# `_never_touch_the_real_install` (which redirects `fleet.INSTALL_ROOT`), so a
# real sid there resolves against a tmp population and can retarget nothing. A
# subprocess re-imports `fleet` and gets neither redirect. There ARE real-shaped
# v4 sids left in `monkeypatch.setenv` calls elsewhere in this tree (measured:
# 5 files, 9 constants) and they are deliberately not touched here.


class Site:
    __slots__ = ("path", "lineno", "how", "value", "resolved")

    def __init__(self, path, lineno, how, value, resolved):
        self.path, self.lineno, self.how = path, lineno, how
        self.value, self.resolved = value, resolved

    def __repr__(self):
        shown = repr(self.value) if self.resolved else "<unresolved>"
        return f"{Path(self.path).name}:{self.lineno} {self.how} {shown}"


def _string_constants(tree):
    """`{name: literal}` for module scope, `{(class, name): literal}` for class
    bodies. Only str constants -- anything computed is left unresolved rather
    than guessed at, and an unresolved site is a FAILURE below, not a skip."""
    mod, cls = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    mod.setdefault(target.id, node.value.value)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                        and isinstance(stmt.value.value, str):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            cls.setdefault((node.name, target.id), stmt.value.value)
    return mod, cls


def _scopes(tree):
    """node id -> (enclosing class name, enclosing FunctionDef node)."""
    out = {}

    def walk(node, cls, fn):
        for child in ast.iter_child_nodes(node):
            c, f = cls, fn
            if isinstance(child, ast.ClassDef):
                c = child.name
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f = child
            out[id(child)] = (c, f)
            walk(child, c, f)

    walk(tree, None, None)
    return out


def caller_sid_sites(path):
    """Every value this file puts into a child's `CLAUDE_CODE_SESSION_ID`.

    ONE HOP OF DATAFLOW IS FOLLOWED, and it is not optional: the two shipped
    drives spell the value as a `_run(..., session=<sid>)` parameter, so a lint
    that only read literals at the assignment would see a bare `Name` at both of
    the sites that actually matter and report a clean tree."""
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    mod, cls = _string_constants(tree)
    scopes = _scopes(tree)
    sites = []

    def resolve(node, classname):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return True, node.value
        if isinstance(node, ast.Name) and node.id in mod:
            return True, mod[node.id]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "self" and (classname, node.attr) in cls:
                return True, cls[(classname, node.attr)]
            if (node.value.id, node.attr) in cls:
                return True, cls[(node.value.id, node.attr)]
        if isinstance(node, ast.Constant) and node.value is None:
            # `env[KEY] = None` cannot happen (os.environ rejects it), but a
            # `session=None` parameter default is the "human shell" case and
            # carries no sid at all.
            return True, None
        return False, None

    def follow_parameter(anchor, name_node, how):
        """The value is a bare name; if it is a parameter of the enclosing
        function, check the default and every call to that function here."""
        classname, fn = scopes.get(id(anchor), (None, None))
        if fn is None:
            return False
        positional = [a.arg for a in fn.args.args]
        kwonly = [a.arg for a in fn.args.kwonlyargs]
        param = name_node.id
        if param not in positional and param not in kwonly:
            return False
        seen_any = False
        # the default, if the parameter has one
        if param in kwonly:
            idx = kwonly.index(param)
            default = fn.args.kw_defaults[idx]
        else:
            idx = positional.index(param)
            offset = len(positional) - len(fn.args.defaults)
            default = fn.args.defaults[idx - offset] if idx >= offset else None
        if default is not None:
            ok, val = resolve(default, classname)
            sites.append(Site(str(path), fn.lineno, how + f" (default {param}=)",
                              val, ok))
            seen_any = True
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            called = func.attr if isinstance(func, ast.Attribute) else (
                func.id if isinstance(func, ast.Name) else None)
            if called != fn.name:
                continue
            arg = None
            for kw in call.keywords:
                if kw.arg == param:
                    arg = kw.value
            if arg is None and param in positional:
                # a bound method's `self` occupies positional[0] at the def but
                # never at the call site.
                pos = idx - 1 if positional and positional[0] == "self" else idx
                if 0 <= pos < len(call.args):
                    arg = call.args[pos]
            if arg is None:
                continue
            call_cls, _ = scopes.get(id(call), (None, None))
            ok, val = resolve(arg, call_cls)
            sites.append(Site(str(path), call.lineno, how + f" (via {param}=)",
                              val, ok))
            seen_any = True
        return seen_any

    def record(anchor, value_node, how):
        classname, _ = scopes.get(id(anchor), (None, None))
        ok, val = resolve(value_node, classname)
        if ok:
            sites.append(Site(str(path), anchor.lineno, how, val, True))
            return
        if isinstance(value_node, ast.Name) and follow_parameter(anchor, value_node, how):
            return
        sites.append(Site(str(path), anchor.lineno, how, None, False))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == KEY:
                    record(node, kw.value, "kwarg")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == KEY:
                    record(node, value, "dict-literal")
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == KEY):
                record(node, node.value, "env[...]=")
    return sites


def census():
    out = []
    for path in sorted(TESTS.rglob("test_*.py")):
        out.extend(caller_sid_sites(path))
    return out


def offending_sites(sites):
    """The property, as a function rather than as an expression inside one test.

    IT LIVES HERE FOR A REASON. The first cut of this file spelled the filter
    inline in `test_no_caller_sid_is_an_rfc4122_v4_uuid`, and a mutant that
    replaced it with `offenders = []` left all 14 tests GREEN -- the exact
    tautology this repo has shipped before. Pulled out, the selector is seed-
    tested in both directions by `TestTheDetectorCanSeeACollision`, so a version
    of it that can no longer see an armed tree fails on its own."""
    return [s for s in sites if s.resolved and is_an_issuable_sid(s.value)]


class TestNoTestHandsAChildAnIssuableSid:
    """The property itself. A mutant that puts any of the three historical sids
    back into either shipped constant fails this test by name and value."""

    def test_no_caller_sid_is_an_rfc4122_v4_uuid(self):
        offenders = offending_sites(census())
        assert not offenders, (
            "these tests hand a CHILD process a session id shaped like one "
            "`claude` issues, which §5 step 2 will resolve against every home in "
            "`resolution_population()` -- INCLUDING the `INSTALL_ROOT` home, "
            "which no environment variable moves. If that home's registry "
            "carries the sid (in `session_id` OR in an archived record's "
            "`retired_sids`), the drive is RETARGETED off its fixture and a "
            "destructive verb writes into the bystander. Use a UUID-shaped sid "
            "with version nibble 0, e.g. "
            "'fa15e51d-0000-0000-0000-000000000009'.\n  "
            + "\n  ".join(map(repr, offenders)))

    def test_every_site_resolves(self):
        """A site whose value the census cannot see is a hole, not a pass.

        This is the failure mode the repo has been bitten by twice: a lint that
        is green because its detector reached nothing."""
        blind = [s for s in census() if not s.resolved]
        assert not blind, (
            "the caller-sid census could not resolve these to a literal, so it "
            "cannot vouch for them. Spell the sid as a module- or class-level "
            "string constant, or as a literal at the call site.\n  "
            + "\n  ".join(map(repr, blind)))

    def test_the_census_is_not_vacuous(self):
        """A resolver that silently found nothing would pass both tests above."""
        sites = census()
        files = {Path(s.path).name for s in sites}
        assert len(sites) >= 5, sites
        assert {"test_destructive_guard.py", "test_subprocess_home_seam.py"} <= files, files

    def test_the_shipped_constants_are_not_issuable(self):
        """Named directly, so the pin does not depend on the AST walker at all.

        Two independent detectors, because a single one that breaks silently is
        how a green suite covers a live hole."""
        import test_destructive_guard as tdg
        import test_subprocess_home_seam as tshs
        for value in (tdg.TestAWorkerIsNotExempt.WORKER_SID,
                      tdg.TestAWorkerCallerIsNotExempt.WORKER_SID,
                      tdg.TestAWorkerCallerIsNotExempt.MANAGER_SID,
                      tshs.SID):
            assert not is_an_issuable_sid(value), value
            # still a sid to `fleet` itself: the shape refusals are unchanged.
            assert fleet._SID_SHAPE_RE.match(value), value
        assert len({tdg.TestAWorkerCallerIsNotExempt.WORKER_SID,
                    tdg.TestAWorkerCallerIsNotExempt.MANAGER_SID}) == 2


class TestTheDetectorCanSeeACollision:
    """Seeds for the detector, both directions and every spelling.

    Without these, a `caller_sid_sites` that returned `[]` -- or an
    `is_an_issuable_sid` that returned False for everything -- would leave the
    class above green over an armed tree."""

    def _sites(self, tmp_path, body):
        f = tmp_path / "test_seed.py"
        f.write_text(body, encoding="utf-8")
        return caller_sid_sites(f)

    def test_a_real_sid_is_issuable_and_the_synthetic_one_is_not(self):
        # the three that stood in this tree until w61
        for real in ("820762d0-5298-4b1b-9471-4048ea27e278",
                     "1a9374bd-df92-42ad-972a-06693aeef272",
                     "20fee653-f07e-4208-8c0e-1c737f9119f7"):
            assert is_an_issuable_sid(real), real
        for fake in ("fa15e51d-0000-0000-0000-000000000001", "sess-A",
                     "aaaabbbb-1111-2222-3333-444455556666", "", None, 17):
            assert not is_an_issuable_sid(fake), fake

    def test_a_literal_kwarg_is_seen(self, tmp_path):
        sites = self._sites(tmp_path,
                            'e = child_env(t, CLAUDE_CODE_SESSION_ID="820762d0-5298-4b1b-9471-4048ea27e278")\n')
        assert [s.value for s in sites] == ["820762d0-5298-4b1b-9471-4048ea27e278"]
        assert all(s.resolved for s in sites)

    def test_a_dict_literal_is_seen(self, tmp_path):
        sites = self._sites(tmp_path,
                            'e = {"FLEET_HOME": "x", "CLAUDE_CODE_SESSION_ID": SID}\n'
                            'SID = "1a9374bd-df92-42ad-972a-06693aeef272"\n')
        assert [s.value for s in sites] == ["1a9374bd-df92-42ad-972a-06693aeef272"]

    def test_a_subscript_assignment_is_seen(self, tmp_path):
        sites = self._sites(tmp_path,
                            'class T:\n'
                            '    MY = "20fee653-f07e-4208-8c0e-1c737f9119f7"\n'
                            '    def go(self, env):\n'
                            '        env["CLAUDE_CODE_SESSION_ID"] = self.MY\n')
        assert [s.value for s in sites] == ["20fee653-f07e-4208-8c0e-1c737f9119f7"]

    def test_the_parameter_hop_is_followed(self, tmp_path):
        """The shape both shipped drives actually use."""
        sites = self._sites(tmp_path,
                            'class T:\n'
                            '    SID = "1a9374bd-df92-42ad-972a-06693aeef272"\n'
                            '    def _run(self, *argv, session="an-agent"):\n'
                            '        env = child_env(t)\n'
                            '        env["CLAUDE_CODE_SESSION_ID"] = session\n'
                            '    def test_x(self):\n'
                            '        self._run("kill", session=self.SID)\n')
        values = {s.value for s in sites}
        assert "1a9374bd-df92-42ad-972a-06693aeef272" in values, sites
        assert "an-agent" in values, sites          # the default is checked too
        assert all(s.resolved for s in sites), sites
        # and the positional `*argv` is NOT mistaken for the kwonly parameter
        assert "kill" not in values, sites

    def test_the_selector_flags_an_armed_file_and_clears_a_synthetic_one(self, tmp_path):
        """The seed that kills a hardcoded-empty selector.

        `offending_sites` is what the property test asserts on; if it can no
        longer see a real sid, THIS goes red rather than the property test going
        quietly green."""
        armed = self._sites(tmp_path,
                            'e = child_env(t, CLAUDE_CODE_SESSION_ID='
                            '"820762d0-5298-4b1b-9471-4048ea27e278")\n')
        assert [s.value for s in offending_sites(armed)] == [
            "820762d0-5298-4b1b-9471-4048ea27e278"]
        clean = self._sites(tmp_path,
                            'e = child_env(t, CLAUDE_CODE_SESSION_ID='
                            '"fa15e51d-0000-0000-0000-000000000001")\n')
        assert offending_sites(clean) == []
        # an unresolved site is not an offender -- `test_every_site_resolves` is
        # what covers those, and conflating the two would make either one able
        # to hide the other.
        blind = self._sites(tmp_path,
                            'env["CLAUDE_CODE_SESSION_ID"] = compute_it()\n')
        assert offending_sites(blind) == []

    def test_an_unresolvable_value_is_reported_not_skipped(self, tmp_path):
        sites = self._sites(tmp_path,
                            'env["CLAUDE_CODE_SESSION_ID"] = compute_it()\n')
        assert len(sites) == 1 and not sites[0].resolved

    def test_the_walker_reads_the_real_shipped_sites(self):
        """Anchored on the two files this lane changed, by spelling."""
        guard = caller_sid_sites(TESTS / "test_destructive_guard.py")
        seam = caller_sid_sites(TESTS / "test_subprocess_home_seam.py")
        assert {"fa15e51d-0000-0000-0000-000000000001"} <= {s.value for s in guard}
        assert {"fa15e51d-0000-0000-0000-000000000004"} <= {s.value for s in seam}
        assert all(s.resolved for s in guard + seam)


# ---------------------------------------------------------------------------
# The mechanism, kept alive on purpose.
# ---------------------------------------------------------------------------

def _rec(**over):
    base = {"session_id": None, "cwd": "/tmp/p", "task": "t", "mode": "dontask",
            "model": None, "max_budget_usd": None, "setting_sources": None,
            "token_ceiling": None, "spawned_by": None,
            "created": "2026-09-10T00:00:00Z", "status": "idle",
            "attached_since": None, "limit_reset_at": None, "limit_kind": None,
            "turns": 1, "cost_baseline": 0.0, "cost_usd": 1.0,
            "last_activity": "2026-09-10T00:00:00Z", "dispatch_kind": "bg",
            "category": None, "native_short_id": None, "last_dispatch_at": None,
            "retired_sids": [], "archived_at": None}
    base.update(over)
    return base


def _seed(home, workers):
    for sub in ("state", "mailbox", "logs"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8")
    return home


def _status(home, name):
    data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
    return data["workers"][name]["status"]


class TestTheRetargetIsRealAndStillOpen:
    """THE SEAM IS NOT CLOSED, and this class passes by proving it.

    w61 removed the COLLISION -- the historical sids -- and nothing else. Every
    subprocess drive still reads the `INSTALL_ROOT` home's registry, because
    `INSTALL_ROOT` is `__file__`-derived and no environment variable moves it.
    If a later change ever fences it, THIS TEST GOES RED, and that red is the
    signal to delete it rather than to restore the hole.

    Staging one install tree costs one file copy and is affordable exactly once.
    Doing it for EVERY drive in the suite is the fence a test lane priced and
    correctly refused (`conftest.child_env`'s docstring, `docs/lanes/
    w60-homeseam.md` §6); this class is not that fence."""

    CALLER = "fa15e51d-0000-0000-0000-00000000ca11"

    def _install(self, tmp_path):
        """A throwaway tree whose `bin/fleet.py` is a real file, so a child's
        `Path(__file__).resolve().parent.parent` lands HERE. A symlink would
        not do: `resolve()` follows it straight back to the repo."""
        root = tmp_path / "install"
        (root / "bin").mkdir(parents=True)
        target = root / "bin" / "fleet.py"
        try:
            os.link(Path(fleet.__file__), target)      # same device: free
        except OSError:
            shutil.copy2(Path(fleet.__file__), target)
        return root

    def _drive(self, tmp_path, install, work, *argv, sid):
        env = child_env(tmp_path, FLEET_HOME=str(work), CLAUDE_CODE_SESSION_ID=sid)
        return subprocess.run([sys.executable, str(install / "bin" / "fleet.py"), *argv],
                              capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=env)

    def test_a_sid_the_install_root_home_carries_retargets_a_destructive_verb(self, tmp_path):
        install = self._install(tmp_path)
        # the bystander IS the install root, and it carries the caller's sid on
        # an ARCHIVED record -- `_record_sids` is the union, so `retired_sids`
        # alone is enough.
        _seed(install, {
            "archived": _rec(status="dead", session_id="unrelated",
                             retired_sids=[self.CALLER],
                             archived_at="2026-08-01T00:00:00Z"),
            "prod": _rec(status="idle", spawned_by=self.CALLER)})
        work = _seed(tmp_path / "work", {"prod": _rec(status="idle",
                                                      spawned_by=self.CALLER)})

        out = self._drive(tmp_path, install, work, "kill", "prod", sid=self.CALLER)

        assert out.returncode == 0, out.stdout + out.stderr
        assert _status(install, "prod") == "dead", (
            "the INSTALL_ROOT retarget no longer happens -- if that is because "
            "the seam was fenced, DELETE this class; do not restore the hole.")
        assert _status(work, "prod") == "idle", (
            "the fixture home was written after all: " + out.stdout + out.stderr)

    def test_without_the_collision_the_same_drive_stays_home(self, tmp_path):
        """The control. Without it the test above would pass on a world where
        `kill` wrote into the install root unconditionally."""
        install = self._install(tmp_path)
        _seed(install, {"prod": _rec(status="idle", spawned_by="somebody-else",
                                     session_id="a-different-sid")})
        work = _seed(tmp_path / "work", {"prod": _rec(status="idle",
                                                      spawned_by=self.CALLER)})

        out = self._drive(tmp_path, install, work, "kill", "prod", sid=self.CALLER)

        assert out.returncode == 0, out.stdout + out.stderr
        assert _status(work, "prod") == "dead", out.stdout + out.stderr
        assert _status(install, "prod") == "idle", out.stdout + out.stderr

    def test_the_shipped_sids_would_still_retarget_if_a_home_carried_them(self, tmp_path):
        """w61 changed WHICH sids the suite uses, not what a hit does.

        Stated as a test so the report's claim -- *the seam remains open* -- is
        checkable rather than a sentence someone can stop believing."""
        install = self._install(tmp_path)
        import test_destructive_guard as tdg
        # spelled as a module constant, not as the attribute chain, because
        # `test_every_site_resolves` above refuses a caller sid it cannot see --
        # this file is not exempt from its own lint. The equality is the tie.
        shipped = SHIPPED_WORKER_SID
        assert shipped == tdg.TestAWorkerCallerIsNotExempt.WORKER_SID
        _seed(install, {"holder": _rec(status="idle", session_id=shipped),
                        "prod": _rec(status="idle", spawned_by=shipped)})
        work = _seed(tmp_path / "work", {"prod": _rec(status="idle",
                                                      spawned_by=shipped)})

        out = self._drive(tmp_path, install, work, "kill", "prod",
                          sid=SHIPPED_WORKER_SID)

        assert out.returncode == 0, out.stdout + out.stderr
        assert _status(install, "prod") == "dead"
        assert _status(work, "prod") == "idle"
