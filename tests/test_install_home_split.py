"""Slice 0 of `docs/specs/multi-fleet.md`: `FLEET_HOME` was two variables
wearing one name, and this file pins them apart.

  * **home** (data plane) -- one fleet's soul: registry, journals, mailbox,
    supervisor, the rendered settings instance. Moves with `$FLEET_HOME`.
  * **install** (code plane) -- `INSTALL_ROOT`, where this source tree is.
    `Path(__file__).resolve().parent.parent`, never overridable.

THE DEFECT, DRIVEN RATHER THAN INHERITED. The spec says a data-only home yields
"four dead hooks, silently". Four is not taken on faith here: the count is
DERIVED from the git-tracked template (every hook command it declares) and then
each script is checked on disk. Measured against the pre-split code at `176c6b4`
with `FLEET_HOME` pointed at a directory containing `state/fleet.json` and
nothing else:

    hook commands declared by the template: 4
      ...of which resolve under {{FLEET_HOME}}: 4
    DEAD  <home>/bin/hooks/posttooluse_mailbox.py
    DEAD  <home>/bin/hooks/stop_outcome.py
    DEAD  <home>/bin/hooks/stop_mailbox.py
    DEAD  <home>/bin/hooks/postcompact_journal.py
    DEAD HOOKS: 4 of 4
    statusline script under that home: False

So the four are: PostToolUse mailbox delivery, the Stop outcome record, the Stop
mailbox drain, and the PostCompact journal reminder -- plus a fifth casualty the
spec's number does not include, the statusline, which is why slice 0 names it
separately. And "silently" is the load-bearing word: `claude` does not fail a
turn because a hook command names a file that is not there, so every worker turn
runs with no mail, no outcome record and no journal reminder while the fleet
looks healthy.

WHAT MUST NOT CHANGE. Install == home is the legacy layout and stays legal
forever (spec Definitions). Every helper below resolves to exactly what it
resolved to before the split whenever the two roots coincide, which is the case
for every caller that exists today. `TestTheLegacyLayoutIsUnchanged` is that
guarantee, and it is the one that decides whether this slice shipped or failed.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import fleet

REPO = Path(__file__).resolve().parents[1]
HOOKS = REPO / "bin" / "hooks"


def _template_text():
    return (REPO / "worker-settings.template.json").read_text(encoding="utf-8")


def _is_os(node):
    import ast
    return isinstance(node, ast.Name) and node.id == "os"


def _is_environ(node):
    import ast
    return isinstance(node, ast.Attribute) and node.attr == "environ" and _is_os(node.value)


def _hook_commands(text):
    """Every hook command the template declares, derived from the JSON rather
    than grepped -- a new hook event is covered on the day it lands."""
    doc = json.loads(text)
    return [h["command"]
            for event in doc["hooks"].values()
            for group in event
            for h in group["hooks"]]


class TestTheFourDeadHooksAreExactlyFour:
    def test_the_template_declares_exactly_four_hook_commands(self):
        assert len(_hook_commands(_template_text())) == 4

    def test_and_they_are_these_four(self):
        """Named, not counted. If a fifth lands, this says which four it joined
        rather than merely that the number moved."""
        scripts = sorted(re.search(r"/bin/hooks/(\S+?)\"", c).group(1)
                         for c in _hook_commands(_template_text()))
        assert scripts == ["postcompact_journal.py", "posttooluse_mailbox.py",
                           "stop_mailbox.py", "stop_outcome.py"]

    def test_every_hook_command_is_rooted_at_the_install_placeholder(self):
        """THE FIX. Each of the four used to render under `{{FLEET_HOME}}`; all
        four now render under `{{FLEET_INSTALL}}`, which is what stops a
        data-only home killing them."""
        commands = _hook_commands(_template_text())
        assert all("{{FLEET_INSTALL}}/bin/hooks/" in c for c in commands)
        assert not any("{{FLEET_HOME}}/bin/" in c for c in commands)

    def test_a_data_only_home_now_leaves_every_hook_alive(self, tmp_path):
        """The defect drive, re-run against shipped code. Same shape as the
        pre-split measurement in this module's docstring: a home with state and
        no code. Every rendered hook path must exist."""
        home = tmp_path / "data-only-home"
        (home / "state").mkdir(parents=True)
        (home / "state" / "fleet.json").write_text('{"workers":{}}', encoding="utf-8")

        rendered = fleet.render_worker_settings_template(
            _template_text(), sys.executable, home, fleet_install=REPO)

        commands = _hook_commands(rendered)
        assert len(commands) == 4
        dead = [c for c in commands
                if not Path(re.search(r'"\s*"([^"]+)"\s*$', c).group(1)).exists()]
        assert not dead, f"still dead against a data-only home: {dead}"

    def test_the_statusline_is_the_fifth_casualty_and_is_also_fixed(self, tmp_path, monkeypatch):
        """The spec counts four hooks; the statusline dies the same way and is
        named separately in slice 0. `fleet init --statusline` writes this path
        into ~/.claude/settings.json, so a home-derived value installed a
        statusline pointing at a file that does not exist."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path / "data-only-home")
        monkeypatch.setattr(fleet, "INSTALL_ROOT", REPO)
        assert fleet.statusline_script_path().exists()


class TestThePlanesAreSeparate:
    HOME_PLANE = ("state_dir", "logs_dir", "mailbox_dir", "knowledge_dir",
                  "instance_settings_path", "lock_path")
    INSTALL_PLANE = ("template_settings_path", "statusline_script_path")

    @pytest.mark.parametrize("helper", HOME_PLANE)
    def test_the_data_plane_follows_the_home(self, helper, tmp_path, monkeypatch):
        home, install = tmp_path / "home", tmp_path / "install"
        monkeypatch.setattr(fleet, "FLEET_HOME", home)
        monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
        assert home in getattr(fleet, helper)().parents or getattr(fleet, helper)() == home

    @pytest.mark.parametrize("helper", INSTALL_PLANE)
    def test_the_code_plane_follows_the_install(self, helper, tmp_path, monkeypatch):
        home, install = tmp_path / "home", tmp_path / "install"
        monkeypatch.setattr(fleet, "FLEET_HOME", home)
        monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
        resolved = getattr(fleet, helper)()
        assert install in resolved.parents, f"{helper}() -> {resolved}"
        assert home not in resolved.parents

    def test_the_doctor_legacy_settings_check_stays_home_plane(self):
        """Named explicitly by slice 0 as the one that must NOT move. The legacy
        `worker-settings.json` it looks for is a stale rendered INSTANCE left at
        a home's root by an old `fleet init` -- per-fleet state, not source."""
        src = (REPO / "bin" / "fleet.py").read_text(encoding="utf-8")
        assert 'legacy = FLEET_HOME / "worker-settings.json"' in src

    def test_no_bin_path_is_still_resolved_from_the_home(self):
        """The census, derived: after the split nothing under `bin/` -- the code
        plane by definition -- may hang off FLEET_HOME. This is what catches the
        NEXT site rather than the ones slice 0 happened to list."""
        src = (REPO / "bin" / "fleet.py").read_text(encoding="utf-8")
        offenders = re.findall(r'FLEET_HOME\s*/\s*"bin"', src)
        assert not offenders, (
            f"{len(offenders)} path(s) still resolve bin/ from the home; a "
            f"data-only home has no bin/")


class TestInstallRootIsNotOverridable:
    """Every test here runs a FRESH interpreter on purpose. `conftest.py`
    redirects `fleet.INSTALL_ROOT` into a tmp dir for the whole suite (the
    code-plane sandbox), so the in-process value is the sandbox's by design and
    the import-time derivation is only observable from outside."""

    @staticmethod
    def _install_root_in_a_fresh_interpreter(env=None):
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import fleet; "
             "print(fleet.INSTALL_ROOT)" % str(REPO / "bin")],
            capture_output=True, text=True, timeout=60, env=env)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    def test_it_derives_from_this_files_location(self):
        assert self._install_root_in_a_fresh_interpreter() == str(REPO)

    @staticmethod
    def _env_keys_read_by(path):
        """Every environment variable `path` READS, derived by AST.

        Keyed on the read, not on the spelling: `bin/fleet.py` legitimately
        contains the string `FLEET_INSTALL` in the template placeholder and in
        the comment explaining why no such variable exists, and a substring lint
        would fire on its own documentation."""
        import ast
        keys, tree = set(), ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Subscript) and _is_environ(node.value):
                target = node.slice
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in ("get", "getenv") \
                        and (_is_environ(func.value) or _is_os(func.value)) and node.args:
                    target = node.args[0]
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                keys.add(target.value)
        return keys

    def test_nothing_reads_a_fleet_install_environment_variable(self):
        """Spec Definitions: "never overridable". A `FLEET_INSTALL` env var would
        hand back exactly the conflation this slice removes -- one variable
        moving both planes -- so the pin is that no such read exists."""
        keys = self._env_keys_read_by(REPO / "bin" / "fleet.py")
        assert "FLEET_HOME" in keys, (
            "the env-read detector found no FLEET_HOME read, so it would not "
            "have seen a FLEET_INSTALL one either -- fix the derivation")
        assert "FLEET_INSTALL" not in keys, (
            "bin/fleet.py reads a FLEET_INSTALL environment variable; the "
            "install just became overridable and the split is undone")

    @pytest.mark.parametrize("var", ["FLEET_INSTALL", "FLEET_HOME"])
    def test_no_environment_variable_moves_the_install(self, var, tmp_path):
        """Driven, both candidates. `FLEET_INSTALL` is the one that must never
        exist; `FLEET_HOME` is the one that DOES exist and used to move the
        install as a side effect -- that side effect is the defect."""
        env = {**os.environ, var: str(tmp_path)}
        assert self._install_root_in_a_fresh_interpreter(env) == str(REPO)


class TestTheCodePlaneSandbox:
    """`conftest.py` gained a code-plane sandbox in this slice because the split
    BROKE THE OLD ONE and the suite proved it on the first full run: with
    `template_settings_path()` re-pointed at `INSTALL_ROOT`, the tests that
    fixture a template overwrote the developer's real, git-tracked
    `worker-settings.template.json` with `{}`.

    Same class as the 2026-07-29T22:58:39Z incident in the spec's opening (fleet
    run inside the repo overwrote the real registry with fixture data), reached
    through the code plane rather than the data plane. §7's isolation pins cover
    the HOME only; these cover the other half."""

    def test_the_sandbox_points_the_install_away_from_the_real_repo(self):
        assert fleet.INSTALL_ROOT != REPO
        assert not fleet.template_settings_path().is_relative_to(REPO)

    def test_the_drift_detector_can_see_a_modification(self, tmp_path):
        """THE SEED. The session guard is a before/after hash comparison, which
        passes vacuously the day its file list goes empty or its hashing breaks.
        Plant the exact damage it exists to catch -- a rewritten template -- in a
        throwaway tree and prove it still says yes."""
        import conftest
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "fleet.py").write_text("x = 1\n", encoding="utf-8")
        template = tmp_path / "worker-settings.template.json"
        template.write_text('{"hooks": {}}', encoding="utf-8")

        assert len(conftest.code_plane_files(tmp_path)) == 2
        before = conftest.code_plane_snapshot(tmp_path)
        assert conftest.code_plane_drift(tmp_path, before) == []

        template.write_text("{}", encoding="utf-8")
        assert conftest.code_plane_drift(tmp_path, before) == [
            "worker-settings.template.json"]

    def test_the_detector_covers_the_real_repos_files(self):
        """The seed above runs on a synthetic tree, so it cannot notice that the
        real list is empty. This is the other half."""
        import conftest
        names = {p.name for p in conftest.code_plane_files(REPO)}
        assert {"fleet.py", "fleet_statusline.py", "run_py.sh",
                "worker-settings.template.json"} <= names


class TestTheLegacyLayoutIsUnchanged:
    """THE SLICE'S ACCEPTANCE CRITERION. Sequencing item 3 puts the flag "in or
    before arming"; until a home is named, install == home and every existing
    caller must behave byte-identically. A slice 0 that changes today's
    behaviour for today's users is a failed slice 0."""

    @pytest.mark.parametrize("helper", TestThePlanesAreSeparate.HOME_PLANE
                             + TestThePlanesAreSeparate.INSTALL_PLANE)
    def test_every_helper_resolves_under_the_single_root(self, helper, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        monkeypatch.setattr(fleet, "INSTALL_ROOT", tmp_path)
        assert tmp_path in getattr(fleet, helper)().parents

    def test_the_render_defaults_the_install_to_the_home(self, tmp_path):
        """The signature gained a parameter with a default, so every existing
        3-argument caller renders exactly what it rendered before -- including
        any out-of-tree template still written against `{{FLEET_HOME}}`."""
        text = '"{{PYTHON}}" "{{FLEET_HOME}}/bin/hooks/x.py"'
        three_arg = fleet.render_worker_settings_template(text, sys.executable, tmp_path)
        explicit = fleet.render_worker_settings_template(
            text, sys.executable, tmp_path, fleet_install=tmp_path)
        assert three_arg == explicit
        assert tmp_path.resolve().as_posix() in three_arg

    def test_both_placeholders_render_and_are_distinguishable(self, tmp_path):
        home, install = tmp_path / "home", tmp_path / "install"
        home.mkdir(); install.mkdir()
        rendered = fleet.render_worker_settings_template(
            '{{FLEET_HOME}}|{{FLEET_INSTALL}}', sys.executable, home,
            fleet_install=install)
        assert rendered == f"{home.resolve().as_posix()}|{install.resolve().as_posix()}"

    def test_an_unknown_placeholder_still_fails_loudly(self, tmp_path):
        """Non-vacuity: the alarm that exists because print-mode `claude`
        swallows invalid --settings JSON silently must still fire now that a
        third placeholder is legal."""
        with pytest.raises(ValueError, match="unrendered placeholder"):
            fleet.render_worker_settings_template(
                "{{NOPE}}", sys.executable, tmp_path, fleet_install=tmp_path)

    def test_the_shipped_template_renders_identically_in_the_legacy_layout(self):
        """End to end on the real template: with install == home, the rendered
        hook commands are byte-for-byte what the pre-split `{{FLEET_HOME}}`
        template produced. This is the whole backwards-compatibility claim."""
        root = REPO
        new = fleet.render_worker_settings_template(
            _template_text(), sys.executable, root, fleet_install=root)
        pre_split = _template_text().replace("{{FLEET_INSTALL}}", "{{FLEET_HOME}}")
        old = fleet.render_worker_settings_template(pre_split, sys.executable, root)
        assert new == old


class TestTheStatuslineNoLongerResolvesAHome:
    def test_it_puts_an_install_derived_path_on_sys_path(self):
        src = (REPO / "bin" / "fleet_statusline.py").read_text(encoding="utf-8")
        assert "_INSTALL_ROOT = Path(__file__).resolve().parent.parent" in src
        assert "sys.path.insert(0, str(_INSTALL_ROOT" in src

    def test_it_reads_no_fleet_home_env_var(self):
        src = (REPO / "bin" / "fleet_statusline.py").read_text(encoding="utf-8")
        assert "FLEET_HOME" not in src.split('"""', 2)[-1] or \
            'environ.get("FLEET_HOME")' not in src

    def test_it_imports_fleet_even_when_the_home_has_no_bin(self, tmp_path):
        """Driven. Before the split this inserted `$FLEET_HOME/bin` on sys.path;
        pointed at a data-only home that names a directory with no `fleet.py`,
        and the import survived only because a script's own directory is already
        `sys.path[0]` -- an accident, and one an `import fleet_statusline`
        (rather than a run) does not get."""
        proc = subprocess.run(
            [sys.executable, str(REPO / "bin" / "fleet_statusline.py")],
            input='{"session_id": "sid-x"}', capture_output=True, text=True,
            env={**os.environ, "FLEET_HOME": str(tmp_path)}, timeout=60)
        assert proc.returncode == 0, proc.stderr
        assert "ModuleNotFoundError" not in proc.stderr


class TestTheFourHookHomeResolversDoNotDrift:
    """Slice 0's sentence in the spec is *"the four worker hooks each carry a
    standalone `_fleet_home()`; slice 0 unifies them"*.

    THEY ARE NOT TEXTUALLY UNIFIED, DELIBERATELY, AND THIS IS A REPORTED
    SPEC/CODE DISAGREEMENT. The duplication is an existing, documented doctrine,
    not an oversight: `bin/hooks/stop_outcome.py` states it in its own module
    docstring -- *"Standalone, stdlib only. Never imports bin/fleet.py --
    duplicates its own tiny helpers (_fleet_home, _log_hook_error, _resolve_name)
    per the established pattern"*. Collapsing the four into a shared import would
    introduce the first cross-module import in a plane whose invariant 2 is
    `exit-0 hooks`, to save nine lines.

    So this pins what "unified" is FOR -- that the four cannot diverge -- by
    driving them instead of merging them. Behavioural unification, and it also
    covers `bin/fleet.py`'s own resolution, which a shared hook module would not
    have.

    The hooks' `__file__` fallback still derives the HOME from the INSTALL. That
    is not fixable here: a hook can only know which home it belongs to if the
    dispatch tells it, which is slice (c)'s baked `--fleet-home` argv. Slice 0's
    job is that the four agree and that the conflation is visible."""

    HOOK_SCRIPTS = ("postcompact_journal.py", "posttooluse_mailbox.py",
                    "stop_mailbox.py", "stop_outcome.py")

    def test_the_pinned_set_is_the_set_the_template_dispatches(self):
        dispatched = sorted(re.search(r"/bin/hooks/(\S+?)\"", c).group(1)
                            for c in _hook_commands(_template_text()))
        assert dispatched == sorted(self.HOOK_SCRIPTS)

    def _resolve(self, script, env):
        code = (
            "import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('h', r'{HOOKS / script}')\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "print(str(m._fleet_home()))\n"
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=60, env=env)
        assert proc.returncode == 0, f"{script}: {proc.stderr}"
        return proc.stdout.strip()

    @pytest.mark.parametrize("with_env", [False, True])
    def test_all_four_resolve_the_same_home(self, with_env, tmp_path):
        env = dict(os.environ)
        env.pop("FLEET_HOME", None)
        if with_env:
            env["FLEET_HOME"] = str(tmp_path)
        resolved = {s: self._resolve(s, env) for s in self.HOOK_SCRIPTS}
        assert len(set(map(os.path.normcase, resolved.values()))) == 1, resolved
        if with_env:
            assert Path(next(iter(resolved.values()))) == tmp_path

    def test_and_they_agree_with_fleet_pys_own_resolution(self, tmp_path):
        """The drift that matters is not hook-vs-hook, it is hook-vs-fleet: the
        hook writes the mailbox file that `fleet.py` reads."""
        env = dict(os.environ)
        env["FLEET_HOME"] = str(tmp_path)
        hook_home = Path(self._resolve("stop_outcome.py", env))
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'%s'); import fleet; "
             "print(fleet.FLEET_HOME)" % str(REPO / "bin")],
            capture_output=True, text=True, timeout=60, env=env)
        assert proc.returncode == 0, proc.stderr
        assert Path(proc.stdout.strip()) == hook_home == tmp_path
