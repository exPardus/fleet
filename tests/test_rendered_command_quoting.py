"""Every command string fleet renders quotes every path it interpolates.

THE DEFECT THIS EXISTS FOR, measured at `4d78f6c` under `py -3.10`, whose
`sys.executable` on this machine really is `C:\\Program Files\\Python310\\
python.exe` -- no synthetic fixture was needed:

    RENDERED by `_install_statusline` into settings.json["statusLine"]["command"]:
        C:/Program Files/Python310/python.exe C:/.../bin/fleet_statusline.py
    CONTROL, the same two paths quoted:
        "C:/Program Files/Python310/python.exe" "C:/.../bin/fleet_statusline.py"

    git-bash `sh -c`        SUBJECT rc=127  "/usr/bin/bash: C:/Program: No such file or directory"
                            CONTROL rc=0    "[fleet]: not initialized"
    cmd `/d /s /c "<cmd>"`  SUBJECT rc=1    "'C:/Program' is not recognized as an internal
                                             or external command"
                            CONTROL rc=0    "[fleet]: not initialized"

`fleet init --statusline` is README quickstart STEP 4, so this broke the fourth
thing a new user does, on every statusline refresh, for anyone whose Python
lives under a path with a space -- which on Windows is the default location for
a machine-wide install.

WHY THE PIN THAT ALREADY EXISTED COULD NOT SEE IT.
`tests/test_hook_fleet_home_argv.py::TestEveryRenderedCommandQuotesItsPaths
::test_no_bare_path_placeholder_is_left_anywhere_in_fleet_py` scans the whole
file -- but through `re.compile(r"(.?)\\{(fleet_py|py)\\}(.?)")`, i.e. it is
scoped to two placeholder NAMES. `_install_statusline` interpolates
`{Path(sys.executable).resolve().as_posix()}` and `{script}`. Neither name
matches, so the scan walked past a shipped, user-facing defect. Gate `w49-gc2`
proved the scoping IS the gate with a discriminating pair: unquoting a render
while keeping the names `{py}`/`{fleet_py}` goes RED, and the SAME unquoting
with the placeholders renamed `{interp}`/`{script_path}` goes GREEN and
survives the full floor. A pin a rename defeats is pinning a name.

THE PROPERTY, AND HOW IT IS DERIVED WITHOUT NAMING ANYTHING.
A site is censused as a COMMAND RENDER when, by AST:

  (i)  the f-string is the value of a `"command"` key in a dict literal, or is
       passed to a subprocess call with `shell=True`, or follows `-c` in an
       argv list -- it flows into a shell SINK; or
  (ii) it interpolates two path-valued expressions separated by nothing but
       whitespace and quote characters -- the `<interpreter> <script>` SHAPE.

"Path-valued" is decided by the shape of the EXPRESSION, never by the name of
the placeholder: `Path(...)`, any `.as_posix()/.resolve()/.absolute()/
.expanduser()` call, `sys.executable`, the module globals `INSTALL_ROOT` /
`FLEET_HOME`, or a call to a helper in the same file annotated `-> Path`.
Names are followed only as an alias step -- a name resolves to the expression
it was assigned -- so renaming `py` to `interp` changes nothing.

WHAT THIS CENSUS DOES NOT REACH (wave 45: a pin shipping a carve-out ships the
census of what it exempts):

  * A command render that interpolates exactly ONE path, is not a `"command"`
    dict value, and reaches no shell sink this file can see. Rule (ii) needs
    two paths; rule (i) needs a visible sink. Such a render is invisible here.
  * A path that arrives as an unannotated FUNCTION PARAMETER. The shape test
    runs inside one function; it does not read call sites.
  * `.format()` / `%` / string-concatenation renders. Only f-strings are
    walked. The `{{PLACEHOLDER}}` template surface is covered separately below
    (`TestTheTemplateSurfaceQuotesToo`) precisely because it is not an f-string.
  * Anything outside `bin/**/*.py` and `worker-settings.template.json`.

All four gaps are backstopped for the renders that exist today by the
BEHAVIOURAL half: every censused site is driven with a real space in the
interpreter path and in both roots, and the rendered command lines are re-parsed
with `shlex` -- the consumer's own parser, not a regex that agrees with the bug.
The census and the drivers are cross-checked against each other, so a render
added tomorrow cannot land without either a driver or a deliberate edit to the
pinned count.
"""
import ast
import json
import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import fleet  # noqa: E402

# ---------------------------------------------------------------------------
# The AST census.
# ---------------------------------------------------------------------------

_PATH_ATTRS = frozenset({"as_posix", "resolve", "absolute", "expanduser"})
_PATH_GLOBALS = frozenset({"INSTALL_ROOT", "FLEET_HOME"})
# A separator that a shell treats as nothing: whitespace, and the quote
# characters that a CORRECT render puts around the paths themselves.
_SEPARATOR_CHARS = frozenset(" \t\r\n\"'")


def _path_returning_helpers(tree):
    """Names of functions in this module annotated `-> Path`.

    Derived, not listed: `statusline_script_path()` is path-valued because of
    its annotation, and so is any helper someone adds next week."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann = getattr(node, "returns", None)
            if isinstance(ann, ast.Name) and ann.id == "Path":
                out.add(node.name)
    return out


def _directly_path_valued(node, helpers):
    """True when the expression itself has the shape of a filesystem path."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name) and (fn.id == "Path" or fn.id in helpers):
                return True
            if isinstance(fn, ast.Attribute) and fn.attr in _PATH_ATTRS:
                return True
        if (isinstance(sub, ast.Attribute) and sub.attr == "executable"
                and isinstance(sub.value, ast.Name) and sub.value.id == "sys"):
            return True
        if isinstance(sub, ast.Name) and sub.id in _PATH_GLOBALS:
            return True
    return False


def _local_bindings(fn):
    """`{name: [assigned expressions]}` for one function body.

    The ALIAS step, and the reason a rename cannot defeat this pin: `py` is not
    special, it is a name bound to `Path(sys.executable).as_posix()`."""
    bindings = {}
    if fn is None:
        return bindings
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, []).append(node.value)
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                and node.value is not None):
            bindings.setdefault(node.target.id, []).append(node.value)
    return bindings


def _path_valued(node, bindings, helpers, seen=()):
    if _directly_path_valued(node, helpers):
        return True
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in bindings and sub.id not in seen:
            for value in bindings[sub.id]:
                if _path_valued(value, bindings, helpers, seen + (sub.id,)):
                    return True
    return False


def _enclosing_function(tree):
    """`{id(node): enclosing FunctionDef or None}` for every node in the tree."""
    table = {}

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            nested = (child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                      else fn)
            table[id(child)] = nested
            walk(child, nested)

    walk(tree, None)
    return table


def _shell_sink_fstrings(tree):
    """f-strings that flow into something that executes them (rule (i))."""
    sinks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "command"
                        and isinstance(value, ast.JoinedStr)):
                    sinks.add(id(value))
        elif isinstance(node, ast.Call):
            shell = any(kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                        and kw.value.value is True for kw in node.keywords)
            if shell:
                for arg in node.args:
                    if isinstance(arg, ast.JoinedStr):
                        sinks.add(id(arg))
        elif isinstance(node, (ast.List, ast.Tuple)):
            items = list(node.elts)
            for i, item in enumerate(items[:-1]):
                if (isinstance(item, ast.Constant) and item.value in ("-c", "/c")
                        and isinstance(items[i + 1], ast.JoinedStr)):
                    sinks.add(id(items[i + 1]))
    return sinks


def _rendered_line_of_each_part(parts):
    """Which RENDERED line each part of an f-string lands on.

    THE UNIT IS THE LINE, NOT THE F-STRING, and that correction is load-bearing.
    A supervisor task body is ONE triple-quoted f-string holding both command
    lines and prose: `_render_sup_spawn_task` opens with *"running in
    {FLEET_HOME.as_posix()} (three-tier §10.1)"* -- prose, six lines above the
    `sup-boot` command line, and correctly unquoted because no shell ever reads
    it. Censusing per f-string flagged it, which would have been a false
    positive on the shipped tree: the scan was wrong, not the tree."""
    lines = []
    current = 0
    for part in parts:
        lines.append(current)
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            current += part.value.count("\n")
    return lines


def _adjacent_path_pair_lines(parts, path_indexes, part_lines):
    """Rendered lines carrying the `<interpreter> <script>` shape (rule (ii))."""
    hit = set()
    for first, second in zip(path_indexes, path_indexes[1:]):
        if second == first + 1:
            hit.add(part_lines[first])
        elif second == first + 2 and isinstance(parts[first + 1], ast.Constant):
            between = parts[first + 1].value
            if between and set(between) <= _SEPARATOR_CHARS:
                hit.add(part_lines[first])
    return hit


def census_command_renders(source, filename):
    """Every command-render site in one source file, AST-derived.

    Each entry: `(filename, lineno, function, (unquoted path expressions...))`,
    where `lineno` anchors the f-string, not the rendered line -- adjacent
    f-string literals parse into ONE JoinedStr whose content newlines are
    escapes, so a precise per-line source number would be fabricated. An entry
    with an empty tuple is a render that holds the property."""
    tree = ast.parse(source)
    helpers = _path_returning_helpers(tree)
    enclosing = _enclosing_function(tree)
    sinks = _shell_sink_fstrings(tree)
    bindings_cache = {}
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        fn = enclosing.get(id(node))
        key = id(fn)
        if key not in bindings_cache:
            bindings_cache[key] = _local_bindings(fn)
        bindings = bindings_cache[key]
        parts = node.values
        part_lines = _rendered_line_of_each_part(parts)
        path_indexes = [
            i for i, part in enumerate(parts)
            if isinstance(part, ast.FormattedValue)
            and _path_valued(part.value, bindings, helpers)
        ]
        if not path_indexes:
            continue
        command_lines = _adjacent_path_pair_lines(parts, path_indexes, part_lines)
        if id(node) in sinks:
            # The whole string IS the command: every rendered line of it counts.
            command_lines = set(part_lines)
        if not command_lines:
            continue
        unquoted = []
        for i in path_indexes:
            if part_lines[i] not in command_lines:
                continue
            before = parts[i - 1].value if i and isinstance(parts[i - 1], ast.Constant) else ""
            after = (parts[i + 1].value if i + 1 < len(parts)
                     and isinstance(parts[i + 1], ast.Constant) else "")
            if not (before.endswith('"') and after.startswith('"')):
                unquoted.append(ast.unparse(parts[i].value))
        sites.append((filename, node.lineno,
                      fn.name if fn is not None else "<module>", tuple(unquoted)))
    return sorted(sites, key=lambda s: (s[0], s[1]))


def code_plane_files():
    """Every Python file fleet ships in its code plane, DERIVED by glob.

    A new module cannot escape the census by not being listed here."""
    return sorted(p for p in (REPO / "bin").rglob("*.py"))


def census_code_plane():
    sites = []
    for path in code_plane_files():
        rel = path.relative_to(REPO).as_posix()
        sites.extend(census_command_renders(path.read_text(encoding="utf-8"), rel))
    return sorted(sites, key=lambda s: (s[0], s[1]))


# The census, pinned by COUNT and by identity. A fifth render moves both, and
# moving them is a deliberate edit with a driver attached (see below).
EXPECTED_RENDERS = (
    ("bin/fleet.py", "_steer_supervisor_release"),
    ("bin/fleet.py", "_install_statusline"),
    ("bin/fleet.py", "_render_sup_spawn_task"),
    ("bin/fleet.py", "_render_successor_task"),
)


class TestTheCensusIsTheGate:
    """The census is the half that survives a render nobody has written yet."""

    def test_the_census_finds_exactly_the_renders_it_is_pinned_to(self):
        found = tuple(sorted((f, fn) for f, _, fn, _ in census_code_plane()))
        assert found == tuple(sorted(EXPECTED_RENDERS)), (
            f"the set of command renders moved: {found}. Add the new render to "
            f"EXPECTED_RENDERS *and* give it a driver in RENDER_DRIVERS, or "
            f"explain in this module's docstring why it is not a command."
        )

    def test_every_censused_render_quotes_every_path_it_interpolates(self):
        offenders = [(f, line, fn, bare)
                     for f, line, fn, bare in census_code_plane() if bare]
        assert not offenders, (
            f"unquoted path interpolation(s) in a rendered command: {offenders}. "
            f"A path under `C:/Program Files/...` word-splits: gate w49-gc2 "
            f"measured rc=127 under git-bash and rc=1 under cmd, with the quoted "
            f"form at rc=0."
        )


class TestTheCensusCanSeeWhatItClaimsToSee:
    """The seeds. An empty-set assertion is green for the same reason a correct
    file is green, so every discriminating power claimed above is exercised on
    a synthetic subject with a KNOWN answer."""

    def test_it_sees_a_bare_placeholder_under_the_original_names(self):
        src = ('def r():\n'
               '    py = Path(sys.executable).as_posix()\n'
               '    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()\n'
               '    return f"{py} {fleet_py} sup-status"\n')
        sites = census_command_renders(src, "x.py")
        assert [(s[2], s[3]) for s in sites] == [("r", ("py", "fleet_py"))]

    def test_a_RENAME_does_not_defeat_it(self):
        """The mutant that defeated the name-scoped pin. Same code, same defect,
        placeholders renamed -- the census must not care."""
        src = ('def r():\n'
               '    interp = Path(sys.executable).as_posix()\n'
               '    script_path = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()\n'
               '    return f"{interp} {script_path} sup-status"\n')
        sites = census_command_renders(src, "x.py")
        assert [(s[2], s[3]) for s in sites] == [("r", ("interp", "script_path"))]

    def test_an_INLINE_expression_with_no_placeholder_name_at_all(self):
        """`_install_statusline`'s actual shape: one interpolation is not a name."""
        src = ('def r():\n'
               '    script = statusline_script_path().resolve().as_posix()\n'
               '    return {"command": f"{Path(sys.executable).resolve().as_posix()} {script}"}\n')
        sites = census_command_renders(src, "x.py")
        assert len(sites) == 1 and len(sites[0][3]) == 2, sites

    def test_a_shell_sink_is_censused_even_with_one_path(self):
        """Rule (i) alone, with rule (ii)'s two-path shape absent.

        The helper carries its `-> Path` annotation IN THIS SNIPPET on purpose:
        path-valued-ness is derived per file, so a snippet that only CALLS a
        helper defined elsewhere is correctly not recognised -- which is the
        `unannotated parameter` gap the module docstring censuses."""
        src = ('def statusline_script_path() -> Path:\n'
               '    return INSTALL_ROOT / "bin" / "fleet_statusline.py"\n'
               'def r():\n'
               '    return subprocess.run(f"{statusline_script_path()} --x", shell=True)\n')
        sites = census_command_renders(src, "x.py")
        assert [(s[2], len(s[3])) for s in sites] == [("r", 1)], sites

    def test_a_correctly_quoted_render_is_censused_but_clean(self):
        src = ('def r():\n'
               '    py = Path(sys.executable).as_posix()\n'
               '    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()\n'
               '    return f\'"{py}" "{fleet_py}" sup-status\'\n')
        sites = census_command_renders(src, "x.py")
        assert [(s[2], s[3]) for s in sites] == [("r", ())]

    def test_prose_naming_a_path_is_NOT_a_command(self):
        """Zero false positives is half the claim. Measured with the predicate
        above, `bin/fleet.py` holds 142 path interpolations and 120 of them are
        unquoted -- prose, prints and error messages, essentially all of them.
        A census that demanded quotes there would be unshippable noise, would
        be suppressed, and would then hold nothing."""
        src = ('def r():\n'
               '    path = registry_path()\n'
               '    return f"registry unreadable: {path}"\n')
        assert census_command_renders(src, "x.py") == []

    def test_prose_on_another_line_of_a_COMMAND_blob_is_not_flagged(self):
        """The false positive that made me narrow the unit to the line.

        A task body is one f-string carrying both. The prose line must be
        ignored and the command line must still be judged -- proved together,
        so 'ignore the prose' cannot be satisfied by ignoring everything."""
        src = ('def r():\n'
               '    py = Path(sys.executable).as_posix()\n'
               '    fleet_py = (INSTALL_ROOT / "bin" / "fleet.py").as_posix()\n'
               '    return f"""running in {FLEET_HOME.as_posix()} (prose).\n'
               'Run: {py} {fleet_py} sup-status\n'
               '"""\n')
        sites = census_command_renders(src, "x.py")
        assert [(s[2], s[3]) for s in sites] == [("r", ("py", "fleet_py"))], sites

    def test_it_does_not_scan_an_empty_tree(self):
        """The real files have subjects at all, so an empty offender list above
        cannot be an empty scan."""
        assert len(census_code_plane()) == len(EXPECTED_RENDERS)


# ---------------------------------------------------------------------------
# The BEHAVIOURAL half: drive every censused render with a real space in every
# root, and re-parse what came out with the consumer's own parser.
# ---------------------------------------------------------------------------

def _spaced_roots(tmp_path, monkeypatch):
    """Put a space in the interpreter path and in BOTH planes, and prove the
    fixture carries the hazard before any assertion depends on it."""
    install = tmp_path / "Fleet Install With Spaces"
    home = tmp_path / "Fleet Home With Spaces"
    interpreter = tmp_path / "Py Dir With Spaces" / "python.exe"
    (install / "bin").mkdir(parents=True)
    home.mkdir(parents=True)
    interpreter.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    monkeypatch.setattr(sys, "executable", str(interpreter))
    sentinels = {
        Path(sys.executable).resolve().as_posix(),
        Path(sys.executable).as_posix(),
        (install / "bin" / "fleet.py").as_posix(),
        (install / "bin" / "fleet_statusline.py").as_posix(),
        home.as_posix(),
    }
    assert all(" " in s for s in sentinels), sentinels
    return sentinels


def _drive_install_statusline(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(fleet, "user_settings_path", lambda: settings)
    fleet._install_statusline()
    return json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"]


def _drive_steer_supervisor_release(tmp_path, monkeypatch):
    captured = {}

    def fake_send(name, message, **kwargs):
        captured["message"] = message

    monkeypatch.setattr(fleet, "_cmd_send_native", fake_send)
    assert fleet._steer_supervisor_release(
        "sup|l1|boot", "w50 probe", run=None, which=None, sleep=None) is None
    return captured["message"]


def _drive_render_sup_spawn_task(tmp_path, monkeypatch):
    return fleet._render_sup_spawn_task("sup|l1|boot", "l1", "campaign brief")


def _drive_render_successor_task(tmp_path, monkeypatch):
    return fleet._render_successor_task("inc-new", "inc-old", "tok")


RENDER_DRIVERS = {
    "_install_statusline": _drive_install_statusline,
    "_steer_supervisor_release": _drive_steer_supervisor_release,
    "_render_sup_spawn_task": _drive_render_sup_spawn_task,
    "_render_successor_task": _drive_render_successor_task,
}


class TestEveryCensusedRenderSurvivesShlex:

    def test_every_censused_render_has_a_driver(self):
        """Cross-check, and the reason a new render cannot slip past the
        behavioural half by simply not having a test written for it."""
        censused = {fn for _, _, fn, _ in census_code_plane()}
        assert censused == set(RENDER_DRIVERS), (
            f"censused but undriven: {sorted(censused - set(RENDER_DRIVERS))}; "
            f"driven but not censused: {sorted(set(RENDER_DRIVERS) - censused)}"
        )

    @pytest.mark.parametrize("function", sorted(RENDER_DRIVERS))
    def test_a_space_in_any_root_survives_as_single_argv_tokens(
            self, function, tmp_path, monkeypatch):
        sentinels = _spaced_roots(tmp_path, monkeypatch)
        rendered = RENDER_DRIVERS[function](tmp_path, monkeypatch)

        # The driver must prove it reached its own site: a driver repointed at
        # another render, or one whose fixture never took, passes vacuously.
        interpreters = {s for s in sentinels if s.endswith("python.exe")}
        command_lines = [ln for ln in rendered.splitlines()
                         if any(i in ln for i in interpreters)]
        assert command_lines, (
            f"{function}: the fixture never reached the render -- no line "
            f"carries the spaced interpreter. Rendered:\n{rendered[:400]}"
        )

        for line in command_lines:
            argv = shlex.split(line, posix=True)
            for sentinel in sorted(sentinels):
                if sentinel in line:
                    assert sentinel in argv, (
                        f"{function}: {sentinel!r} was split by its space into "
                        f"{argv} -- line was: {line!r}"
                    )


# ---------------------------------------------------------------------------
# The second surface: the hook commands are rendered by TEMPLATE, not by an
# f-string, so the AST census above cannot see them at all.
# ---------------------------------------------------------------------------

TEMPLATE = REPO / "worker-settings.template.json"


def _template_hook_commands(payload):
    commands = []
    for entries in payload.get("hooks", {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                if "command" in hook:
                    commands.append(hook["command"])
    return commands


class TestTheTemplateSurfaceQuotesToo:
    """`worker-settings.template.json`'s hook commands are shell-executed by
    Claude Code exactly as `statusLine.command` is, and `fleet init` renders
    three path placeholders into them.

    HOW THIS RULE MEETS root `CLAUDE.md`'s FORWARD-SLASH RULE. They are two
    fixes for two different behaviours of the same consumer, and they do not
    conflict -- quoting is the stronger of the two. Measured in git-bash:

        $ bash -c 'echo "C:\\Users\\Techn\\x"; echo C:\\Users\\Techn\\x'
        C:\\Users\\Techn\\x
        C:UsersTechnx

    i.e. a double-quoted segment keeps its backslashes; an unquoted one loses
    them. Quoting therefore also neutralises the backslash hazard for the paths
    it wraps, but forward slashes stay required: the rendered value is written
    into JSON that other tooling reads, and the rule is stated in the SPEC."""

    def test_the_template_is_valid_and_has_hook_commands_at_all(self):
        payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        assert len(_template_hook_commands(payload)) == 4

    def test_every_placeholder_in_every_hook_command_is_quoted(self):
        payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        bare = []
        for command in _template_hook_commands(payload):
            for match in fleet._TEMPLATE_PLACEHOLDER_RE.finditer(command):
                before = command[match.start() - 1:match.start()]
                after = command[match.end():match.end() + 1]
                if before != '"' or after not in ('"', "/"):
                    bare.append((command, match.group(0)))
        assert not bare, f"unquoted placeholder(s) in a hook command: {bare}"

    def test_rendering_with_spaced_roots_survives_shlex(self, tmp_path):
        """The behavioural half of the same property, through the real
        renderer rather than through the template text."""
        python_exe = tmp_path / "Py Dir With Spaces" / "python.exe"
        home = tmp_path / "Fleet Home With Spaces"
        install = tmp_path / "Fleet Install With Spaces"
        rendered = fleet.render_worker_settings_template(
            TEMPLATE.read_text(encoding="utf-8"),
            python_exe=python_exe, fleet_home=home, fleet_install=install)
        payload = json.loads(rendered)
        commands = _template_hook_commands(payload)
        assert len(commands) == 4
        expect = {python_exe.resolve().as_posix(), home.resolve().as_posix()}
        assert all(" " in e for e in expect), expect
        for command in commands:
            argv = shlex.split(command, posix=True)
            assert install.resolve().as_posix() in argv[1], command
            for sentinel in expect:
                assert sentinel in argv, (
                    f"{sentinel!r} split by its space into {argv}")
