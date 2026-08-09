"""Multi-fleet slice (c): the dispatch bakes the home in, and the dispatched
plane reads it.

`docs/specs/multi-fleet.md` Sequencing §3 spells this slice *"hook argv +
witness + `_render_successor_task` argv"*, and its one-line normative summary
(the paragraph above "## §6") reads: *"**Hooks**: `--fleet-home` argv baked
per-home (survived six rounds; both `--settings` sites)."*

WHAT SLICE 0 LEFT STANDING, in the spec's own words (Slice 0 finding 2):
*"Their `__file__` fallback still derives the home from the install; that is
not fixable here -- a hook learns its home only when the dispatch tells it,
which is slice (c)'s baked argv."*

THE ORDER, AND WHY IT IS §5's ORDER AND NOT A NEW ONE. §5 is titled
*"Resolution -- one order for every caller"*. A hook is a caller. It runs
three of the five steps and skips two, and each skip is structural, not a
preference:

  step 1  `--fleet-home`      -- NEW HERE. The baked argv IS the flag.
  step 2  sid->home lookup    -- SKIPPED. It costs one `read_registry_at` per
                                 listed home, on every PostToolUse, i.e. per
                                 tool call. §4 already bars hooks from the
                                 homes list as writers; this bars them as
                                 readers on cost, and the argv makes the
                                 lookup unnecessary -- dispatch already knows.
  step 3  validated env       -- KEPT, unchanged. `FLEET_HOME` stays a working
                                 input: the daemon substitutes environments
                                 wholesale, and interactive sessions and this
                                 suite address a home through it.
  step 4  legacy install root -- KEPT, unchanged: the `__file__` fallback.
  step 5  terminus            -- SKIPPED. Its content is *"mutating verbs
                                 refuse"*, and SPEC invariant 2 is exit-0
                                 hooks. A hook cannot refuse, so it proceeds
                                 exactly as it does today.

ARGV BEATS ENV, AND IT IS NOT A TIE-BREAK OF CONVENIENCE. The spec's own
cross-fleet interference audit row for `Daemon env` says a hosted body's env
vars are *"donor facts; fenced by hook argv, blob sid, the lookup, and the
destructive tier"*. The argv is named as the fence; the thing it fences is the
env. Same shape as this file's older sibling doctrine at `bin/fleet.py`'s
identity block -- *"THE REGISTRY JUDGES, THE ENVIRONMENT ONLY WITNESSES"*.

AN ARGV HOME IS NOT VALIDATED, DELIBERATELY. §5 step 1 validates the flag and
lets a mutating verb refuse; a hook has no refusal available to it. If a hook
validated the baked home and fell through on failure, a broken bake would be
silently traded for the donor's env home -- a cross-home write, which is the
exact incident class this slice exists to close. So a present, non-empty argv
value wins outright and an individual failed write stays a logged, exit-0
event in the home the dispatch named.

EXIT-0 IS AN INVARIANT (SPEC invariant 2), and the four hooks are NOT equally
netted: `bin/hooks/stop_outcome.py`'s entrypoint is a bare `sys.exit(main())`
with no `except`, and its `_fleet_home()` call sits ABOVE its own inner `try`.
Three siblings wrap `main()` in `except Exception`. So argv parsing must be
structurally unable to raise, and this file drives all four with hostile argv
rather than reading the parser.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "bin" / "hooks"
HOOK_SCRIPTS = ("postcompact_journal.py", "posttooluse_mailbox.py",
                "stop_mailbox.py", "stop_outcome.py")

sys.path.insert(0, str(REPO / "bin"))
import fleet  # noqa: E402


def _template_text():
    return (REPO / "worker-settings.template.json").read_text(encoding="utf-8")


def _hook_commands(text):
    doc = json.loads(text)
    return [h["command"]
            for group in doc["hooks"].values()
            for entry in group
            for h in entry["hooks"]]


def _resolve_home(script, argv=(), env=None):
    """`_fleet_home()` as the hook itself computes it, in a fresh process."""
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('h', r'{HOOKS / script}')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print(str(m._fleet_home()))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code, *argv],
                          capture_output=True, text=True, timeout=60,
                          env=env if env is not None else _clean_env())
    assert proc.returncode == 0, f"{script}: {proc.stderr}"
    return proc.stdout.strip()


def _clean_env(**over):
    env = dict(os.environ)
    env.pop("FLEET_HOME", None)
    env.update(over)
    return env


def _drive_hook(script, argv=(), env=None, payload=None):
    """Run a hook end to end, exactly as the dispatch does: real argv, real
    JSON payload on stdin, exit code and stderr observed."""
    if payload is None:
        payload = {"session_id": "abc12345-0000-0000-0000-00000000beef",
                   "transcript_path": "", "last_assistant_message": "hi"}
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *argv],
        input=json.dumps(payload), capture_output=True, text=True, timeout=60,
        env=env if env is not None else _clean_env())


# ---------------------------------------------------------------------------
# (c)(i) -- the dispatch surface bakes it.
# ---------------------------------------------------------------------------

class TestTheTemplateBakesTheHome:
    def test_every_hook_command_carries_the_flag(self):
        for cmd in _hook_commands(_template_text()):
            assert '--fleet-home "{{FLEET_HOME}}"' in cmd, cmd

    def test_all_four_are_still_rooted_at_the_install(self):
        """Slice 0's split is not undone by slice (c): the SCRIPT comes from
        the install (code plane), the HOME argument from the home (data
        plane). Both placeholders in one command is the whole point."""
        cmds = _hook_commands(_template_text())
        assert len(cmds) == 4
        for cmd in cmds:
            assert "{{FLEET_INSTALL}}/bin/hooks/" in cmd, cmd

    def test_the_rendered_home_is_forward_slashed_and_quoted(self, tmp_path):
        """Root CLAUDE.md: hook commands use FORWARD slashes -- Git Bash's
        `sh -c` eats backslashes. A baked Windows path is exactly where this
        bites, and the quoting is what survives a space in the home."""
        home = tmp_path / "a home with spaces"
        home.mkdir()
        rendered = fleet.render_worker_settings_template(
            _template_text(), sys.executable, home, fleet_install=REPO)
        for cmd in _hook_commands(rendered):
            baked = re.search(r'--fleet-home "([^"]+)"', cmd)
            assert baked, cmd
            assert "\\" not in baked.group(1), cmd
            assert baked.group(1) == home.resolve().as_posix()

    def test_the_legacy_placeholder_contract_is_untouched(self):
        """Slice 0 finding 4: `{{FLEET_HOME}}` stays a legal placeholder and
        `fleet_install` still defaults to the home, so an out-of-tree template
        written against `{{FLEET_HOME}}` renders exactly what it rendered
        before. This slice USES `{{FLEET_HOME}}`; it must not redefine it."""
        legacy = ('{"hooks": {"Stop": [{"hooks": [{"type": "command", '
                  '"command": "\\"{{PYTHON}}\\" \\"{{FLEET_HOME}}/bin/x.py\\""}]}]}}')
        three_arg = fleet.render_worker_settings_template(
            legacy, sys.executable, REPO)
        assert "{{" not in three_arg
        assert (REPO.resolve().as_posix() + "/bin/x.py") in three_arg


# ---------------------------------------------------------------------------
# (c)(i) -- the dispatched plane reads it. §5's order, three steps of five.
# ---------------------------------------------------------------------------

class TestTheHooksReadTheBakedHome:
    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_step_1_argv_names_the_home(self, script, tmp_path):
        assert Path(_resolve_home(script, ["--fleet-home", str(tmp_path)])) == tmp_path

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_step_1_accepts_the_equals_spelling(self, script, tmp_path):
        """`fleet.strip_global_fleet_home` handles `--fleet-home=V`; a hook
        reading the same option string must not disagree about its grammar."""
        assert Path(_resolve_home(script, [f"--fleet-home={tmp_path}"])) == tmp_path

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_step_1_beats_step_3(self, script, tmp_path):
        """THE PRECEDENCE. The donor env names one home, the dispatch baked
        another; the dispatch wins."""
        baked = tmp_path / "baked"
        donor = tmp_path / "donor"
        baked.mkdir()
        donor.mkdir()
        got = _resolve_home(script, ["--fleet-home", str(baked)],
                            env=_clean_env(FLEET_HOME=str(donor)))
        assert Path(got) == baked

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_step_3_still_answers_with_no_argv(self, script, tmp_path):
        """The env var must stay a WORKING INPUT, not a deprecated one."""
        got = _resolve_home(script, env=_clean_env(FLEET_HOME=str(tmp_path)))
        assert Path(got) == tmp_path

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_step_4_is_byte_identical_to_today(self, script):
        """No argv, no env: the `__file__`-derived install root, unchanged."""
        assert Path(_resolve_home(script)) == REPO

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_an_unvalidated_home_is_still_the_answer(self, script, tmp_path):
        """A baked home that does not exist does NOT fall through to the
        donor env -- see this module's docstring. Falling through would trade
        a broken bake for a cross-home write."""
        missing = tmp_path / "not-there"
        donor = tmp_path / "donor"
        donor.mkdir()
        got = _resolve_home(script, ["--fleet-home", str(missing)],
                            env=_clean_env(FLEET_HOME=str(donor)))
        assert Path(got) == missing


class TestTheFourStillAgree:
    """Slice 0 built BEHAVIOURAL unification because the four hooks are
    deliberately not textually unified (`stop_outcome.py`'s module docstring:
    *"Standalone, stdlib only. Never imports bin/fleet.py"*). Slice (c) adds a
    second input to all four, so the agreement test grows a second axis rather
    than the hook plane growing its first cross-module import."""

    def test_all_four_resolve_the_same_baked_home(self, tmp_path):
        resolved = {s: _resolve_home(s, ["--fleet-home", str(tmp_path)])
                    for s in HOOK_SCRIPTS}
        assert len({os.path.normcase(v) for v in resolved.values()}) == 1, resolved
        assert Path(next(iter(resolved.values()))) == tmp_path

    def test_all_four_agree_under_argv_versus_env_conflict(self, tmp_path):
        baked, donor = tmp_path / "b", tmp_path / "d"
        baked.mkdir()
        donor.mkdir()
        env = _clean_env(FLEET_HOME=str(donor))
        resolved = {s: _resolve_home(s, ["--fleet-home", str(baked)], env=env)
                    for s in HOOK_SCRIPTS}
        assert {os.path.normcase(v) for v in resolved.values()} == \
            {os.path.normcase(str(baked))}, resolved

    def test_and_they_agree_with_fleet_pys_own_flag_reading(self, tmp_path):
        """hook-vs-fleet is the drift that matters: the hook writes the
        mailbox file `fleet.py` reads. Both consume the same option string, so
        both must extract the same value from the same token pair."""
        argv = ["--fleet-home", str(tmp_path), "status"]
        _, flag_value = fleet.strip_global_fleet_home(list(argv))
        hook_home = _resolve_home("stop_outcome.py", argv[:2])
        assert Path(flag_value) == Path(hook_home) == tmp_path


class TestHostileArgvNeverRaises:
    """HARD CONSTRAINT: a hook that raises renders a traceback into a worker's
    session on every tool call. Driven, not read -- and driven through the
    real entrypoint, because `stop_outcome.py` is `sys.exit(main())` with no
    outer `except` and calls `_fleet_home()` above its own inner `try`."""

    HOSTILE = [
        pytest.param(["--fleet-home"], id="trailing-valueless"),
        pytest.param(["--bogus"], id="unknown-flag"),
        pytest.param(["--fleet-home", "--bogus"], id="flag-eats-a-flag"),
        pytest.param(["--fleet-home="], id="empty-equals-value"),
        pytest.param(["positional"], id="bare-positional"),
        # NOT a NUL byte: `subprocess` rejects that in the PARENT, so it can
        # never reach a hook's argv and the param would only test the harness.
        pytest.param(["--fleet-home", "line1\nline2"], id="newline-in-value"),
        pytest.param(["--fleet-home", "x" * 5000], id="absurdly-long-value"),
    ]

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    @pytest.mark.parametrize("argv", HOSTILE)
    def test_the_hook_still_exits_zero(self, script, argv, tmp_path):
        proc = _drive_hook(script, argv, env=_clean_env(FLEET_HOME=str(tmp_path)))
        assert proc.returncode == 0, f"{script} {argv}: {proc.stderr}"
        assert "Traceback" not in proc.stderr, f"{script} {argv}: {proc.stderr}"

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_a_repeated_flag_with_two_values_degrades_it_does_not_raise(
            self, script, tmp_path):
        """`fleet.py` REFUSES this (*"One invocation names one home"*). A hook
        cannot refuse, so it declines the contradictory input and falls to the
        next step -- the same decision, tiered by what the plane can do."""
        a, b = tmp_path / "a", tmp_path / "b"
        env_home = tmp_path / "env"
        for p in (a, b, env_home):
            p.mkdir()
        got = _resolve_home(script,
                            ["--fleet-home", str(a), "--fleet-home", str(b)],
                            env=_clean_env(FLEET_HOME=str(env_home)))
        assert Path(got) == env_home

    @pytest.mark.parametrize("script", HOOK_SCRIPTS)
    def test_a_repeated_flag_with_one_value_is_not_a_contradiction(
            self, script, tmp_path):
        got = _resolve_home(script,
                            ["--fleet-home", str(tmp_path),
                             "--fleet-home", str(tmp_path)])
        assert Path(got) == tmp_path


class TestTheBakedHomeIsWhereTheHookActuallyWrites:
    """Resolving the home is not the deliverable -- writing into it is. Driven
    end to end: a real mailbox under the BAKED home is drained while the donor
    env names a different home entirely."""

    SID = "abc12345-0000-0000-0000-00000000beef"

    def test_posttooluse_drains_the_baked_homes_mailbox(self, tmp_path):
        baked, donor = tmp_path / "baked", tmp_path / "donor"
        (baked / "mailbox").mkdir(parents=True)
        (donor / "mailbox").mkdir(parents=True)
        (baked / "mailbox" / f"{self.SID}.md").write_text(
            "from the baked home", encoding="utf-8")
        (donor / "mailbox" / f"{self.SID}.md").write_text(
            "from the donor home", encoding="utf-8")
        proc = _drive_hook("posttooluse_mailbox.py",
                           ["--fleet-home", str(baked)],
                           env=_clean_env(FLEET_HOME=str(donor)),
                           payload={"session_id": self.SID})
        assert proc.returncode == 0, proc.stderr
        assert "from the baked home" in proc.stdout
        assert "from the donor home" not in proc.stdout
        assert (donor / "mailbox" / f"{self.SID}.md").exists(), \
            "the donor home's mailbox must not have been touched"


# ---------------------------------------------------------------------------
# (c)(ii) -- the supervisor-tier task renders.
# ---------------------------------------------------------------------------

def _fleet_py_invocations(body):
    """Every rendered line that invokes this repo's fleet.py."""
    return [ln.strip() for ln in body.splitlines() if "fleet.py" in ln]


class TestTheSupervisorTaskRendersCarryTheHome:
    """The spec's supervisor-tier paragraph: the successor class has the
    widest measured pre-claim window (33.0-63.1s, 7 of 7 over 30s, vs 0.7s
    median for workers) *"while its task render carries no `--fleet-home` --
    so `_render_successor_task` gains the same baked argv the hooks have, in
    slice (c)"*. For that whole window §5 step 2 cannot answer for the body:
    it has no registry row to be a member of."""

    def test_successor_every_invocation_names_the_home(self):
        body = fleet._render_successor_task("inc-new", "inc-old", "tok")
        lines = _fleet_py_invocations(body)
        assert lines
        for ln in lines:
            assert '--fleet-home "' in ln, ln

    def test_sup_spawn_every_invocation_names_the_home(self):
        """`_render_sup_spawn_task` is NOT named by Sequencing §3 -- the spec
        names only `_render_successor_task`. It is fixed here because it has
        the identical hole and slice 0's own symbol list names both; leaving
        one of two sibling renders unfenced is this repo's named recurring
        defect (*"fixing only the reported site is how this project reproduces
        a miss at the next site"*). Reported in `docs/lanes/w48-c.md`."""
        body = fleet._render_sup_spawn_task("sup|l1|boot", "l1", "do things")
        lines = _fleet_py_invocations(body)
        assert lines
        for ln in lines:
            assert '--fleet-home "' in ln, ln

    @pytest.mark.parametrize("render", ["successor", "sup_spawn"])
    def test_the_value_is_the_live_home_forward_slashed(self, render, tmp_path,
                                                        monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        body = (fleet._render_successor_task("inc-new", "inc-old", "tok")
                if render == "successor"
                else fleet._render_sup_spawn_task("sup|l1|boot", "l1", "brief"))
        baked = set(re.findall(r'--fleet-home "([^"]+)"', body))
        assert baked == {tmp_path.as_posix()}, baked
        assert not any("\\" in b for b in baked)

    @pytest.mark.parametrize("render", ["successor", "sup_spawn"])
    def test_the_rendered_flag_survives_fleets_own_argv_reader(self, render,
                                                               tmp_path, monkeypatch):
        """Not a string check: the rendered token pair is fed back through the
        exact function `main()` uses, so a quoting or spelling slip is caught
        by the consumer rather than by a regex that agrees with the bug."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        body = (fleet._render_successor_task("inc-new", "inc-old", "tok")
                if render == "successor"
                else fleet._render_sup_spawn_task("sup|l1|boot", "l1", "brief"))
        import shlex
        for ln in _fleet_py_invocations(body):
            argv = shlex.split(ln, posix=True)
            rest, value = fleet.strip_global_fleet_home(argv)
            assert value == tmp_path.as_posix(), ln
            assert "--fleet-home" not in " ".join(rest), ln

# ---------------------------------------------------------------------------
# (c)(ii), continued -- the PATHS those same two renders emit are quoted.
# ---------------------------------------------------------------------------

def _render_by_kind(kind):
    if kind == "successor":
        return fleet._render_successor_task("inc-new", "inc-old", "tok")
    return fleet._render_sup_spawn_task("sup|l1|boot", "l1", "camp")


# Every `{fleet_py}` / `{py}` placeholder in bin/fleet.py, with the character
# on each side of it. A rendered command must write both quoted.
_PATH_PLACEHOLDER = re.compile(r"(.?)\{(fleet_py|py)\}(.?)")


def find_bare_path_placeholders(source):
    """`(name, line)` for every path placeholder not written `"{name}"`."""
    bare = []
    for m in _PATH_PLACEHOLDER.finditer(source):
        if m.group(1) != '"' or m.group(3) != '"':
            bare.append((m.group(2), source.count("\n", 0, m.start()) + 1))
    return bare


class TestEveryRenderedCommandQuotesItsPaths:
    """A rendered command naming an unquoted path breaks on somebody else's
    machine and on nobody's here.

    THE DEFECT, measured by gate `w48-gc` (finding 4) against an install root
    named `Fleet Install With Spaces`, with the sibling render as its control:

        CONTROL  _render_sup_spawn_task  sup-boot    (QUOTED)    rc=0
        SUBJECT  _render_successor_task  sup-status  (UNQUOTED)  rc=2,
                 "python.exe: can't open file 'C:/.../Fleet'"

    All three commands `_render_successor_task` emitted were affected. It is
    PRE-EXISTING -- `fa236cb` renders them identically unquoted -- and it only
    ever reproduces where somebody installs under `C:/Program Files/...`,
    which is the class this campaign's install rehearsal proved is real by
    finding three launch blockers on its first run off this machine.

    WHY THE PIN HAS THIS SHAPE. Slice (c) added a correctly quoted
    `--fleet-home "{home}"` to those very lines, so the rendered command LOOKED
    quoting-aware while the interpreter and script paths beside it stayed bare.
    A pin written against the three lines that were fixed would not have
    noticed that, and would not notice the next sibling render either. So the
    property is held twice:

      1. BEHAVIOURALLY, over both renders, through `shlex` -- the consumer's
         own parser rather than a regex that agrees with the bug. An unquoted
         path containing a space comes back as two argv tokens, so the
         membership assertion fails.
      2. IN SOURCE, over the WHOLE FILE -- every `{fleet_py}` / `{py}`
         placeholder in `bin/fleet.py`, in any function, must be written
         quoted. That is the half that survives a THIRD render being added:
         it needs no fixture, no signature and no call.

    `tests/test_supspawn_fixwave2.py::TestRenderedCommandQuoting` pins the same
    property for `_render_sup_spawn_task` alone, by literal string. This is not
    a replacement for it -- that class also holds the `{bundle}` redirect,
    which is not a path placeholder this file can see."""

    @pytest.mark.parametrize("kind", ["successor", "sup_spawn"])
    def test_a_space_in_either_root_survives_as_single_argv_tokens(
            self, kind, tmp_path, monkeypatch):
        import shlex
        install = tmp_path / "Fleet Install With Spaces"
        home = tmp_path / "Fleet Home With Spaces"
        monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
        monkeypatch.setattr(fleet, "FLEET_HOME", home)
        fleet_py = (install / "bin" / "fleet.py").as_posix()
        interpreter = Path(sys.executable).as_posix()
        # The fixture is evidence only if it actually carries the hazard.
        assert " " in fleet_py and " " in home.as_posix()

        lines = _fleet_py_invocations(_render_by_kind(kind))
        assert lines, kind
        for ln in lines:
            argv = shlex.split(ln, posix=True)
            assert fleet_py in argv, f"script path split by the space: {ln}"
            assert interpreter in argv, f"interpreter split by the space: {ln}"
            assert home.as_posix() in argv, f"home split by the space: {ln}"

    def test_no_bare_path_placeholder_is_left_anywhere_in_fleet_py(self):
        """The half a render nobody has written yet cannot escape.

        Scanned over the whole source rather than over the two functions
        above: the recurring shape in this repo is that a fix lands at the
        reported site and the next sibling is written with the same hole. Here
        the sibling does not have to be found -- if it writes `{fleet_py}` or
        `{py}` into a rendered command at all, it is scanned."""
        source = (REPO / "bin" / "fleet.py").read_text(encoding="utf-8")
        bare = find_bare_path_placeholders(source)
        assert not bare, (
            f"bare path placeholder(s), (name, line): {bare}. A bare "
            f"{{fleet_py}} breaks under `C:/Program Files/...` -- gate w48-gc "
            f"finding 4 measured rc=2, \"can't open file '.../Fleet'\"."
        )

    def test_the_scan_can_see_a_bare_placeholder(self):
        """The seed. A scanner that matches nothing is green for the same
        reason a correct file is green, and the assertion above is a claim
        that a set is EMPTY -- the shape that fails silently."""
        assert find_bare_path_placeholders('f\'"{py}" {fleet_py} sup-status\'') \
            == [("fleet_py", 1)]
        assert find_bare_path_placeholders('f\'{py} "{fleet_py}" sup-status\'') \
            == [("py", 1)]
        assert find_bare_path_placeholders('f\'"{py}" "{fleet_py}" sup-status\'') == []
        # half-quoted is bare too, in both directions
        assert find_bare_path_placeholders('"{fleet_py} ') == [("fleet_py", 1)]
        assert find_bare_path_placeholders(' {fleet_py}"') == [("fleet_py", 1)]
        # and the real file has a subject at all, so an empty result above
        # cannot come from scanning nothing
        source = (REPO / "bin" / "fleet.py").read_text(encoding="utf-8")
        assert source.count("{fleet_py}") >= 2, "the scan has no subject"
