"""`fleet init --home <PATH>` -- multi-fleet slice (b), the last unbuilt slice
(`docs/specs/multi-fleet.md` v8 §4/§5/§Definitions; operator ruling
`docs/OPERATOR-GATES.md` `## Settled`, 2026-08-10).

WHAT THE VERB IS FOR. §Definitions makes an initialized home *"a directory whose
`state/fleet.json` exists and parses as a registry by the tolerant reader"*, and
before this slice NOTHING on the CLI could produce one deliberately:
`--fleet-home <fresh dir>` refuses `not_initialized`, `fleet homes --add` refuses
the same and says *"lists an existing fleet home and never creates one"*, and
bare `fleet init` then wrote `state/worker-settings.json` only -- the registry
appeared on the first `save_registry`, i.e. as a side effect of the first spawn.
So a second home could not be brought into existence except by using it.
§Definitions answers that in its own sentence: *"verbs whose contract is creation
(`init --home`) create"*.

THE TIER AND ITS SHAPE ARE THE OPERATOR'S, NOT DERIVED HERE (2026-08-10):
*"split `init` the same way. `init --home` is a second writer of the same
machine-global `fleet-homes.list` whose append E2 already ruled irreversible. …
the `w47-homes` idiom: flagged tokens in the destructive tuple, **the bare verb
in NO tuple**, tier carried in `VERB_EFFECT_RESIDUAL`, which fails SAFE (drop the
flagged tokens and the verb is unclassified, hence destructive) where the naive
two-row form fails OPEN."* `TestTheRulingsFailSafeDirection` below is that
sentence made executable in BOTH directions -- the shipped shape degrading safe
AND the rejected shape degrading open -- because a pin that only shows the
shipped shape working does not show why the other one was rejected.

WHAT THIS SLICE DELIBERATELY DOES NOT BUILD: cwd-based home resolution. §5's
order is flag -> sid lookup -> `FLEET_HOME` -> legacy install root, and no step
resolves by cwd. `TestNoCwdResolutionWasAdded` is the fence, asserted rather than
promised.

ISOLATION: `homes_list_path` is redirected per test with a seed proving the
redirect is in force -- conftest's autouse sandbox does cover it since slice (e),
and this file re-pins it locally anyway because the file APPENDS, and an append
to the operator's real list is RATIFIED DESTRUCTIVE. `INSTALL_ROOT` is already an
empty fixture install (conftest), so every test that needs the worker-settings
template plants its own.
"""
import argparse
import ast
import inspect
import json
from pathlib import Path

import pytest

import fleet

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Bare init creates in cwd; never let that mean the source checkout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def planted_template(monkeypatch, tmp_path):
    """The git-tracked install-plane template, in the fixture install.

    conftest points `INSTALL_ROOT` at an empty tmp dir, so `init` finds no
    template unless a test plants one. Both placeholders are present because
    `render_worker_settings_template` raises on any `{{NAME}}` it cannot
    substitute -- a template missing one would make every test below fail for a
    reason that has nothing to do with `--home`."""
    path = fleet.INSTALL_ROOT / "worker-settings.template.json"
    path.write_text(
        json.dumps({"python": "{{PYTHON}}", "home": "{{FLEET_HOME}}",
                    "install": "{{FLEET_INSTALL}}"}),
        encoding="utf-8")
    return path


@pytest.fixture
def fresh(tmp_path):
    """An EXISTING, EMPTY directory -- what `init --home` takes."""
    def make(name):
        d = tmp_path / "dirs" / name
        d.mkdir(parents=True)
        return d
    return make


@pytest.fixture
def initialized(tmp_path):
    def make(name, workers=None):
        h = tmp_path / "homes" / name
        (h / "state").mkdir(parents=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        return h
    return make


def _run(argv, monkeypatch, capsys, sid=None):
    monkeypatch.delenv("FLEET_HOME", raising=False)
    if sid is None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
    rc = fleet.main(argv)
    return rc, capsys.readouterr()


def _ns(**kw):
    return argparse.Namespace(**kw)


def _subparser(parser, name):
    action = next(a for a in parser._actions
                  if isinstance(a, argparse._SubParsersAction))
    return action.choices[name]


# ---------------------------------------------------------------------------
# 0. Isolation seed -- everything below appends to a machine-global file
# ---------------------------------------------------------------------------

def test_the_redirect_is_actually_in_force(sandboxed_list):
    """A negative-space seed. Every test in this file appends to
    `~/.claude/fleet-homes.list` through `homes_list_path()`, and that file is
    APPEND-ONLY FOREVER -- only the fold reverses a record. If the redirect ever
    stops applying, the suite starts editing the operator's real machine list
    and every other assertion here would still pass."""
    assert fleet.homes_list_path() == sandboxed_list
    assert fleet.homes_list_path() != REAL_LIST


# ---------------------------------------------------------------------------
# 1. The parser surface
# ---------------------------------------------------------------------------

class TestTheParserSurface:
    def test_init_takes_home_with_a_value(self):
        p_init = _subparser(fleet.build_parser(), "init")
        opts = {o for a in p_init._actions for o in a.option_strings}
        assert "--home" in opts

    def test_the_home_flag_needs_no_residual_flags_entry(self):
        """`sup-decision --raise` needs `VERB_EFFECT_RESIDUAL_FLAGS` because
        argparse maps `--raise` to dest `question`, defeating the table's
        mechanical `--x-y` -> `x_y` rule. `--home` overrides no `dest=`, so it
        does not. Measured off `build_parser()` so the claim cannot rot -- this
        is the same check `homes --add/--retire` carries, and it is the reason
        the destructive token can be written as plain `init --home`."""
        p_init = _subparser(fleet.build_parser(), "init")
        dests = {tuple(a.option_strings): a.dest
                 for a in p_init._actions if a.option_strings}
        assert dests[("--home",)] == "home"
        assert "init" not in fleet.VERB_EFFECT_RESIDUAL_FLAGS

    def test_a_valueless_home_is_a_usage_error(self):
        with pytest.raises(SystemExit) as exc:
            fleet.build_parser().parse_args(["init", "--home"])
        assert exc.value.code == 2

    def test_the_global_fleet_home_flag_is_still_a_different_token(self):
        """`--fleet-home` is consumed out of argv before the parser runs
        (`strip_global_fleet_home`), so the two flags cannot collide by
        abbreviation or by dest. Driven rather than reasoned: the strip must
        take the global one and leave `--home` alone."""
        stripped, value = fleet.strip_global_fleet_home(
            ["init", "--home", "/srv/a", "--fleet-home", "/srv/b"])
        assert stripped == ["init", "--home", "/srv/a"]
        assert value == "/srv/b"


# ---------------------------------------------------------------------------
# 2. The tier -- the operator's ruling, as behaviour and as shape
# ---------------------------------------------------------------------------

class TestTheTier:
    def _tier(self, argv):
        parser = fleet.build_parser()
        args = parser.parse_args(argv)
        return fleet.verb_effect_tier(args.command, args)

    def test_the_write_is_destructive_and_the_bare_verb_is_not(self):
        """Driven through the REAL parser, not a hand-built namespace: the whole
        mechanism is that argparse's default dest (`home`) is what the table's
        mechanical rule produces, so a namespace this test invented could agree
        with the table while the CLI did not."""
        assert self._tier(["init"]) == "ordinary"
        assert self._tier(["init", "--home", "/srv/newfleet"]) == "destructive"

    def test_the_bare_verb_is_ordinary_BY_RESIDUAL_not_by_a_second_row(self):
        """HOW the split is expressed, pinned separately from THAT it holds --
        the ruling named the shape as well as the tier."""
        assert "init" not in fleet.VERB_EFFECT_ORDINARY
        assert "init" not in fleet.VERB_EFFECT_DISRUPTIVE
        assert "init" not in fleet.VERB_EFFECT_DESTRUCTIVE
        assert fleet.VERB_EFFECT_RESIDUAL["init"] == "ordinary"
        assert "init --home" in fleet.VERB_EFFECT_DESTRUCTIVE

    def test_an_empty_home_value_is_still_destructive(self):
        """PRESENCE, NOT TRUTH. `--home ''` is a write the verb will refuse, and
        it must be classified as the write it attempted -- ga3 B1 measured the
        other reading letting `--answer ''` walk past the guard as ORDINARY.
        `""` is neither `None` nor `False`, which is what `verb_effect_tier`'s
        `not in (None, False)` predicate is built on."""
        assert self._tier(["init", "--home", ""]) == "destructive"


class TestTheRulingsFailSafeDirection:
    """*"…which fails SAFE (drop the flagged tokens and the verb is
    unclassified, hence destructive) where the naive two-row form fails OPEN."*

    THIS IS THE RULING'S ACTUAL CONTENT. Both rows below are driven, because a
    test that only shows the shipped shape degrading safely does not show why
    the rejected shape was rejected -- and the rejected shape resolves
    IDENTICALLY on today's table, so nothing else in the suite can tell them
    apart."""

    def test_deleting_the_classification_leaves_init_DESTRUCTIVE(self, monkeypatch):
        """The shipped shape. Drop `init --home` from the destructive tuple --
        a merge that loses one line, a re-transcription that misses one row --
        and `init` is named by no tuple at all, so `verb_effect_tier` returns
        `destructive` from its `if not rows` arm for EVERY invocation, flagged
        or not. The residual dict is not even consulted: it only answers when
        rows exist and none matched."""
        monkeypatch.setattr(
            fleet, "VERB_EFFECT_DESTRUCTIVE",
            tuple(t for t in fleet.VERB_EFFECT_DESTRUCTIVE if t != "init --home"))
        assert fleet.verb_effect_tier("init", _ns(home="/srv/x")) == "destructive"
        assert fleet.verb_effect_tier("init", _ns(home=None)) == "destructive"

    def test_the_naive_two_row_form_would_have_failed_OPEN(self, monkeypatch):
        """The rejected shape, built and measured rather than described: bare
        `init` left in `VERB_EFFECT_ORDINARY` while the flagged token joins the
        destructive tuple. It answers the same three questions correctly today
        -- and the same dropped line sends the WRITE back to `ordinary`, which
        is a destructive verb running unguarded and a read-only `/fleet:*` grant
        reaching an irreversible append."""
        monkeypatch.setattr(fleet, "VERB_EFFECT_ORDINARY",
                            fleet.VERB_EFFECT_ORDINARY + ("init",))
        # the naive form agrees with the shipped one while it is intact...
        assert fleet.verb_effect_tier("init", _ns(home="/srv/x")) == "destructive"
        assert fleet.verb_effect_tier("init", _ns(home=None)) == "ordinary"
        # ...and diverges the moment the flagged token is lost
        monkeypatch.setattr(
            fleet, "VERB_EFFECT_DESTRUCTIVE",
            tuple(t for t in fleet.VERB_EFFECT_DESTRUCTIVE if t != "init --home"))
        assert fleet.verb_effect_tier("init", _ns(home="/srv/x")) == "ordinary", (
            "the naive two-row form did NOT fail open -- if this is now green "
            "the resolver changed, and the ruling's stated ground for choosing "
            "the residual shape has to be re-derived rather than assumed")

    def test_the_verb_is_in_no_more_than_one_row(self):
        """The partition, restated at the one place this slice could break it.
        `test_no_verb_is_in_two_rows` covers the whole table; this names the
        verb, so a failure reads as *this* landing rather than as a mystery."""
        rows = [{t.split()[0] for t in tup} for tup in (
            fleet.VERB_EFFECT_DESTRUCTIVE, fleet.VERB_EFFECT_DISRUPTIVE,
            fleet.VERB_EFFECT_ORDINARY)]
        assert sum("init" in r for r in rows) == 1


class TestTheExemptionAndTheTierAgree:
    """The two layers key on the SAME dest with the SAME presence predicate, and
    that is load-bearing rather than tidy. If they disagreed there would be an
    invocation the table calls destructive that still takes §5's order (a
    deadlock), or one the table calls ordinary that skips it (a hole)."""

    @pytest.mark.parametrize("value,exempt", [
        (None, False), ("/srv/x", True), ("", True), (False, False),
    ])
    def test_the_exemption_fires_exactly_where_the_destructive_tier_does(
            self, value, exempt):
        args = _ns(home=value)
        assert bool(fleet.machine_exempting_flags("init", args)) is exempt
        assert (fleet.verb_effect_tier("init", args) == "destructive") is exempt

    def test_the_exemption_reports_the_option_spelling_not_the_dest(self):
        assert fleet.machine_exempting_flags("init", _ns(home="/x")) == ("--home",)
        assert fleet.machine_exempting_flags("homes", _ns()) == ()

    def test_the_whole_verb_tuple_still_only_names_homes(self):
        """Explicit --fleet-home and statusline setup still take §5's order.
        Bare cwd creation has its own dispatch path, not a whole-verb exemption.
        The machine exemption stays at FLAG granularity for --home."""
        assert fleet.TERMINUS_EXEMPT_VERBS == ("homes",)
        assert "init" in fleet.TERMINUS_EXEMPT_FLAGS


# ---------------------------------------------------------------------------
# 3. The exemption as behaviour -- the two deadlocks it exists to prevent
# ---------------------------------------------------------------------------

class TestTheVerbCannotBeDeadlockedByTheResolver:
    """Both of §5's blocking states name `--fleet-home` as the remedy, and
    `--fleet-home` structurally cannot name a home that does not exist yet
    (`validate_named_home` demands an INITIALIZED home). So a guarded
    `init --home` would be a guard that eats its own remedy -- the same defect
    `TERMINUS_EXEMPT_VERBS` was minted for when `fleet homes --add` printed
    `[fleet]: no home` and exited 0 without appending."""

    def test_it_runs_at_the_terminus(self, monkeypatch, capsys, fresh,
                                     initialized, sandboxed_list):
        """§5 step 5. `INSTALL_ROOT` is an empty fixture install and
        `FLEET_HOME` is pointed at it, so no step resolves a home -- which is
        exactly the fresh box `init --home` exists to populate. `init` is not in
        `TERMINUS_VIEW_VERBS`, so without the exemption this is
        `_terminus_refusal`."""
        monkeypatch.setattr(fleet, "FLEET_HOME", fleet.INSTALL_ROOT)
        sandboxed_list.write_text(
            f"{fleet.home_identity(initialized('L'))}\n", encoding="utf-8")
        assert fleet.resolve_home()["step"] is None, "the fixture is not at the terminus"
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        assert fleet.home_is_initialized(target)

    def test_bare_init_creates_here_even_at_the_terminus(
            self, monkeypatch, capsys, initialized, sandboxed_list, isolated_cwd):
        """G-K5 Reading A inverts the old refusal: init creates its subject.
        The resolver itself still reaches the terminus before AND after init.
        Creating a cwd home neither registers it nor selects it for other verbs.
        """
        monkeypatch.setattr(fleet, "FLEET_HOME", fleet.INSTALL_ROOT)
        sandboxed_list.write_text(
            f"{fleet.home_identity(initialized('L'))}\n", encoding="utf-8")
        before = sandboxed_list.read_bytes()
        assert fleet.resolve_home()["step"] is None
        rc, out = _run(["init"], monkeypatch, capsys)
        assert rc == 0, out.err
        assert fleet.home_is_initialized(isolated_cwd)
        assert sandboxed_list.read_bytes() == before
        assert fleet.resolve_home()["step"] is None
        rc, out = _run(["home"], monkeypatch, capsys)
        assert rc == 0 and "[fleet]: no home" in out.out

    def test_it_runs_on_an_armed_machine_resolved_by_the_legacy_default(
            self, monkeypatch, capsys, fresh, initialized, sandboxed_list):
        """The wrong-home guard, the other blocking state. Two listed homes arm
        the machine; the ambient home is resolved at step 4 with no flag and no
        sid membership, which is exactly `_refuse_wrong_home_destructive`'s
        trigger for a DESTRUCTIVE verb -- and `init --home` is destructive."""
        ambient = initialized("ambient")
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        monkeypatch.setattr(fleet, "state_dir", lambda: ambient / "state")
        sandboxed_list.write_text(
            "".join(f"{fleet.home_identity(initialized(n))}\n" for n in "AB"),
            encoding="utf-8")
        assert fleet.multi_fleet_arming()["armed"], "the fixture is not armed"
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        assert fleet.home_is_initialized(target)

    def test_a_destructive_verb_that_is_NOT_exempt_still_refuses_there(
            self, monkeypatch, capsys, initialized, sandboxed_list):
        """The control arm. The test above proves `init --home` is not refused;
        on its own that is also what a broken guard looks like. `clean` is
        ratified destructive and carries no exemption, so the same fixture must
        refuse it -- which is what makes the row above evidence."""
        ambient = initialized("ambient")
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        monkeypatch.setattr(fleet, "state_dir", lambda: ambient / "state")
        sandboxed_list.write_text(
            "".join(f"{fleet.home_identity(initialized(n))}\n" for n in "AB"),
            encoding="utf-8")
        rc, out = _run(["clean"], monkeypatch, capsys)
        assert rc == 1
        assert "--fleet-home" in out.err


class TestTheGlobalFlagIsRefusedRatherThanIgnored:
    def test_fleet_home_with_home_refuses_and_writes_nothing(
            self, monkeypatch, capsys, fresh, initialized, sandboxed_list):
        """One invocation names one home. `--fleet-home` would be validated,
        assigned, and then never used -- and silently ignoring a flag the
        operator typed is the defect `apply_resolved_home` already names for the
        exempt-verb arm above it."""
        target, other = fresh("new"), initialized("other")
        rc, out = _run(["--fleet-home", str(other), "init", "--home", str(target)],
                       monkeypatch, capsys)
        assert rc == 1
        assert "--fleet-home" in out.err and "--home" in out.err
        assert not (target / "state").exists()
        assert not sandboxed_list.exists()


# ---------------------------------------------------------------------------
# 4. What the verb actually does
# ---------------------------------------------------------------------------

class TestItCreatesAnInitializedHome:
    def test_it_writes_a_parsing_registry(self, monkeypatch, capsys, fresh):
        target = fresh("new")
        assert not fleet.home_is_initialized(target)
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        assert fleet.home_is_initialized(target), (
            "§Definitions: an initialized home is one whose `state/fleet.json` "
            "exists and parses -- that is the whole contract of this verb")
        assert json.loads(
            (target / "state" / "fleet.json").read_text(encoding="utf-8")
        ) == {"workers": {}}

    def test_it_renders_the_worker_settings_into_the_NAMED_home(
            self, monkeypatch, capsys, fresh, initialized):
        """Both creation forms render the TARGET, or the new home's hook
        commands would point at whichever home happened to be ambient."""
        ambient = initialized("ambient")
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        rendered = json.loads(
            (target / "state" / "worker-settings.json").read_text(encoding="utf-8"))
        assert rendered["home"] == Path(target).resolve().as_posix()
        assert rendered["home"] != Path(ambient).resolve().as_posix()
        assert rendered["install"] == Path(fleet.INSTALL_ROOT).resolve().as_posix()

    def test_the_ambient_home_is_untouched(self, monkeypatch, capsys, fresh,
                                           initialized):
        """`--home` must not write into the home §5 would have resolved. The
        ambient home starts initialized with a worker in it; nothing about it may
        change."""
        ambient = initialized("ambient", workers={"w": {"session_id": "S"}})
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        monkeypatch.setattr(fleet, "state_dir", lambda: ambient / "state")
        before = sorted(p.name for p in (ambient / "state").iterdir())
        rc, out = _run(["init", "--home", str(fresh("new"))], monkeypatch, capsys)
        assert rc == 0, out.err
        assert sorted(p.name for p in (ambient / "state").iterdir()) == before
        assert json.loads((ambient / "state" / "fleet.json").read_text(
            encoding="utf-8"))["workers"] == {"w": {"session_id": "S"}}


class TestItRecordsTheHomeOnTheMachine:
    def test_it_appends_exactly_one_record(self, monkeypatch, capsys, fresh,
                                           sandboxed_list):
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        assert sandboxed_list.read_text(encoding="utf-8") == \
            f"{fleet.home_identity(target)}\n"
        assert fleet.read_homes_list()["members"] == [fleet.home_identity(target)]

    def test_re_running_appends_nothing_and_keeps_the_registry(
            self, monkeypatch, capsys, fresh, sandboxed_list):
        """IDEMPOTENT ON DISK, not merely in effect. The list is append-only
        forever, so a second `init --home` that re-appended would leave a
        permanent duplicate; and the registry is this home's ROSTER, so a second
        run that rewrote it would delete live workers."""
        target = fresh("new")
        assert _run(["init", "--home", str(target)], monkeypatch, capsys)[0] == 0
        registry = target / "state" / "fleet.json"
        registry.write_text(json.dumps({"workers": {"w": {"session_id": "S"}}}),
                            encoding="utf-8")
        before = registry.read_bytes()
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 0, out.err
        assert registry.read_bytes() == before, "the roster was rewritten"
        assert sandboxed_list.read_text(encoding="utf-8") == \
            f"{fleet.home_identity(target)}\n"
        assert "already listed" in out.out

    def test_a_home_already_listed_by_homes_add_is_not_re_appended(
            self, monkeypatch, capsys, initialized, sandboxed_list):
        ident = fleet.home_identity(initialized("H"))
        sandboxed_list.write_text(f"{ident}\n", encoding="utf-8")
        rc, out = _run(["init", "--home", ident], monkeypatch, capsys)
        assert rc == 0, out.err
        assert sandboxed_list.read_text(encoding="utf-8") == f"{ident}\n"

    def test_the_home_is_initialized_BEFORE_it_is_listed(
            self, monkeypatch, capsys, fresh, sandboxed_list):
        """ORDER IS THE FAILURE CONTRACT. The append is the irreversible half,
        so it must come last: a failure before it leaves a usable home and a
        clean machine list, while the reverse order would leave a permanent
        record of a home §4's reader drops. Driven by making the predicate fail
        after the writes -- the verb must refuse and append nothing."""
        monkeypatch.setattr(fleet, "home_is_initialized", lambda home: False)
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 1
        assert "not initialized" in out.err
        assert not sandboxed_list.exists(), (
            "a home §4's reader would drop was appended to an append-only list")

    def test_an_unreadable_list_refuses_the_append_and_says_the_home_is_made(
            self, monkeypatch, capsys, fresh, sandboxed_list):
        """`cmd_homes`'s ground, inherited: appending to a list *"whose current
        membership is unknown"* can duplicate a record nothing removes. The
        message must not read as total failure -- the home IS created by then,
        and the remedy is one `fleet homes --add`."""
        target = fresh("new")
        real = fleet.read_homes_list

        def unreadable():
            out = real()
            out.update(ok=False, reason="unreadable")
            return out
        monkeypatch.setattr(fleet, "read_homes_list", unreadable)
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 1
        assert fleet.home_is_initialized(target), "the home was rolled back"
        assert "homes --add" in out.err
        assert not sandboxed_list.exists()


# ---------------------------------------------------------------------------
# 5. The refusals -- each one leaves the machine exactly as it found it
# ---------------------------------------------------------------------------

class TestTheRefusals:
    def test_an_empty_value_refuses(self, monkeypatch, capsys, sandboxed_list):
        """ga1 N1's shape, one verb along: `fleet homes --add ""` once fell into
        the view arm and exited 0. Here the empty value is a REFUSAL, and the
        tier pin above proves it is still classified as the write it attempted."""
        rc, out = _run(["init", "--home", ""], monkeypatch, capsys)
        assert rc == 1
        assert "empty value" in out.err
        assert not sandboxed_list.exists()

    def test_a_nonexistent_directory_refuses_and_creates_nothing(
            self, monkeypatch, capsys, tmp_path, sandboxed_list):
        """`cmd_homes`'s doctrine, inherited verbatim: *"a typo'd path refuses,
        and leaves no directory behind to make the typo look right the second
        time."* This is the one narrowing of *"verbs whose contract is creation
        create"* -- what this verb creates is the `state/fleet.json` that makes a
        directory a home, not the directory."""
        missing = tmp_path / "dirs" / "typo" / "deep"
        rc, out = _run(["init", "--home", str(missing)], monkeypatch, capsys)
        assert rc == 1
        assert "does not exist" in out.err and "mkdir" in out.err
        assert not missing.exists()
        assert not missing.parent.exists(), "a typo left a plausible home behind"
        assert not sandboxed_list.exists()

    def test_a_file_where_the_home_should_be_refuses_with_DIFFERENT_advice(
            self, monkeypatch, capsys, tmp_path, sandboxed_list):
        """`mkdir -p` is the remedy for a path that is ABSENT, and it is not the
        remedy for a path that is a FILE -- telling the operator to `mkdir -p`
        over an existing file is advice that cannot work. Measured on the live
        drive before it was split."""
        f = tmp_path / "afile"
        f.write_text("x", encoding="utf-8")
        rc, out = _run(["init", "--home", str(f)], monkeypatch, capsys)
        assert rc == 1
        assert "not a directory" in out.err and "mkdir" not in out.err
        assert not sandboxed_list.exists()
        assert f.read_text(encoding="utf-8") == "x"

    def test_an_existing_corrupt_registry_is_never_overwritten(
            self, monkeypatch, capsys, fresh, sandboxed_list):
        """THE ARM THAT MATTERS MOST. A registry that exists and does not parse
        is a home with an incident in it. Rewriting it here would destroy the
        evidence `doctor --repair` is classified DESTRUCTIVE for merely renaming
        aside -- and would do it from a verb the operator ran to CREATE
        something."""
        target = fresh("new")
        (target / "state").mkdir()
        registry = target / "state" / "fleet.json"
        registry.write_text("{not json", encoding="utf-8")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 1
        assert registry.read_text(encoding="utf-8") == "{not json"
        assert "doctor" in out.err
        assert not sandboxed_list.exists()

    def test_statusline_and_home_do_not_compose(
            self, monkeypatch, capsys, fresh, sandboxed_list):
        """`--statusline` writes ONE machine-global file and `--chain` captures
        the incumbent into `state/` of the home §5 RESOLVED -- not the one
        `--home` names. The pair would write two different homes from one
        invocation, so it refuses before either."""
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target), "--statusline"],
                       monkeypatch, capsys)
        assert rc == 1
        assert not (target / "state").exists()
        assert not sandboxed_list.exists()
        assert not fleet.user_settings_path().exists()

    def test_a_missing_template_refuses_before_anything_is_written(
            self, monkeypatch, capsys, fresh, sandboxed_list, planted_template):
        planted_template.unlink()
        target = fresh("new")
        rc, out = _run(["init", "--home", str(target)], monkeypatch, capsys)
        assert rc == 1
        assert "template not found" in out.err
        assert not (target / "state").exists()
        assert not sandboxed_list.exists()


# ---------------------------------------------------------------------------
# 6. The fence: no cwd-based home resolution was added
# ---------------------------------------------------------------------------

class TestNoCwdResolutionWasAdded:
    """§5 resolves flag -> sid lookup -> `FLEET_HOME` -> legacy install root, and
    NO STEP RESOLVES BY CWD. The operator's phrasing for multi-fleet
    (*"independent per repo/dir"*) reads like a request for a cwd walk-up, and
    whether §5 should gain that step is an OPEN question with the operator.
    Building it under this slice would be a ratified-spec breach committed in the
    name of urgency, so the absence is asserted rather than promised."""

    def test_the_resolver_still_answers_with_exactly_the_five_steps(self):
        source = inspect.getsource(fleet.resolve_home)
        assert '"flag"' in source and '"lookup"' in source
        assert '"env"' in source and '"legacy"' in source
        for banned in ("cwd", "getcwd", "parents", "walk_up", "git"):
            assert banned not in source, (
                f"`resolve_home` mentions {banned!r} -- if a cwd step was added, "
                f"§5 was edited without the operator")

    def test_the_new_scopes_never_read_the_process_directory_to_find_a_home(self):
        """`_home_to_create` DOES resolve a relative `--home` against the process
        CWD -- `Path.resolve()` is what makes the recorded identity
        CWD-independent from the first line on (ga1 N5). That is one operator-
        typed path being made absolute, not a search. What must not exist is a
        WALK: no parent iteration, no marker file, no git root."""
        tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
        scopes = {"_home_to_create", "_init_named_home", "_write_new_home_state",
                  "_record_home_on_this_machine"}
        # ATTRIBUTES and STRINGS, not a substring sweep over the dump. Measured:
        # a substring sweep flags `mkdir(parents=True)`, whose `parents` is an
        # argparse-shaped KEYWORD and not a walk at all -- and a pin that cries
        # wolf on the one legal `mkdir` in a creation verb is a pin that gets
        # deleted. What a walk-up actually looks like is `p.parents`, `Path.cwd`,
        # `os.getcwd`, or a literal marker filename.
        banned_attrs = {"cwd", "getcwd", "parents", "rglob", "glob"}
        banned_strings = {".git", ".fleet-home", "fleet-home"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in scopes:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute):
                    assert sub.attr not in banned_attrs, (
                        f"{node.name} reaches `.{sub.attr}` -- that is a walk, "
                        f"and §5 has no cwd step")
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert sub.value not in banned_strings, (
                        f"{node.name} names the marker {sub.value!r}")

    def test_no_marker_file_was_reintroduced(self):
        """The `~/.claude/fleet-home` marker was deleted on 2026-07-22 with its
        only reader, and terminal-surface D7 makes fleet PULL-ONLY. A slice that
        wanted cwd resolution would most cheaply get it by bringing the marker
        back."""
        src = Path(fleet.__file__).read_text(encoding="utf-8")
        assert 'Path.home() / ".claude" / "fleet-home"' not in src


class TestBareInitCreatesHere:
    @pytest.mark.parametrize("source", ["env", "legacy"])
    def test_creation_ignores_ambient_selection_without_changing_resolution(
            self, source, monkeypatch, capsys, initialized, sandboxed_list,
            isolated_cwd):
        ambient = initialized("ambient", workers={"w": {"session_id": "S"}})
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        if source == "env":
            monkeypatch.setenv("FLEET_HOME", str(ambient))
        else:
            monkeypatch.delenv("FLEET_HOME", raising=False)
        sandboxed_list.write_text("".join(
            f"{fleet.home_identity(initialized(n))}\n" for n in "AB"),
            encoding="utf-8")
        before = sandboxed_list.read_bytes()
        roster = (ambient / "state" / "fleet.json").read_bytes()
        assert fleet.multi_fleet_arming()["armed"]
        assert fleet.resolve_home()["step"] == source

        assert fleet.main(["init"]) == 0, capsys.readouterr().err
        assert json.loads((isolated_cwd / "state" / "fleet.json").read_text(
            encoding="utf-8")) == {"workers": {}}
        settings = json.loads((isolated_cwd / "state" / "worker-settings.json")
                              .read_text(encoding="utf-8"))
        assert settings["home"] == isolated_cwd.resolve().as_posix()
        assert settings["install"] == fleet.INSTALL_ROOT.resolve().as_posix()
        assert (ambient / "state" / "fleet.json").read_bytes() == roster
        assert not (ambient / "state" / "worker-settings.json").exists()
        assert sandboxed_list.read_bytes() == before
        assert fleet.FLEET_HOME == ambient
        assert fleet.resolve_home()["home"] == ambient
        capsys.readouterr()
        assert fleet.main(["home"]) == 0
        assert capsys.readouterr().out.strip() == ambient.as_posix()

    def test_new_home_is_accepted_by_a_later_global_flag_without_registration(
            self, monkeypatch, capsys, isolated_cwd, sandboxed_list):
        assert _run(["init"], monkeypatch, capsys)[0] == 0
        assert not sandboxed_list.exists()
        rc, out = _run(["--fleet-home", str(isolated_cwd), "home"],
                       monkeypatch, capsys)
        assert rc == 0, out.err
        assert out.out.strip() == isolated_cwd.as_posix()
        assert not sandboxed_list.exists()

    def test_rerun_preserves_roster_and_refreshes_settings(
            self, monkeypatch, capsys, isolated_cwd, sandboxed_list):
        assert _run(["init"], monkeypatch, capsys)[0] == 0
        registry = isolated_cwd / "state" / "fleet.json"
        registry.write_text('{"workers":{"w":{"session_id":"S"}}}\n',
                            encoding="utf-8")
        before = registry.read_bytes()
        settings = isolated_cwd / "state" / "worker-settings.json"
        settings.write_text("stale", encoding="utf-8")
        rc, out = _run(["init"], monkeypatch, capsys)
        assert rc == 0, out.err
        assert registry.read_bytes() == before
        assert json.loads(settings.read_text(encoding="utf-8"))["home"] == \
            isolated_cwd.as_posix()
        assert not sandboxed_list.exists()

    def test_corrupt_registry_is_preserved_and_settings_are_not_written(
            self, monkeypatch, capsys, isolated_cwd, sandboxed_list):
        (isolated_cwd / "state").mkdir()
        registry = isolated_cwd / "state" / "fleet.json"
        registry.write_text("{broken", encoding="utf-8")
        rc, out = _run(["init"], monkeypatch, capsys)
        assert rc == 1 and "refusing to overwrite" in out.err
        assert registry.read_text(encoding="utf-8") == "{broken"
        assert not (isolated_cwd / "state" / "worker-settings.json").exists()
        assert not sandboxed_list.exists()

    def test_missing_template_creates_nothing(
            self, monkeypatch, capsys, isolated_cwd, planted_template):
        planted_template.unlink()
        rc, out = _run(["init"], monkeypatch, capsys)
        assert rc == 1 and "template not found" in out.err
        assert not (isolated_cwd / "state").exists()

    def test_creation_uses_exact_cwd_without_a_repo_root_walk(
            self, monkeypatch, capsys, isolated_cwd):
        (isolated_cwd / ".git").mkdir()
        nested = isolated_cwd / "src"
        nested.mkdir()
        monkeypatch.chdir(nested)
        assert _run(["init"], monkeypatch, capsys)[0] == 0
        assert fleet.home_is_initialized(nested)
        assert not (isolated_cwd / "state").exists()

    def test_global_flag_still_selects_existing_home_for_settings_render(
            self, monkeypatch, capsys, initialized, isolated_cwd, sandboxed_list):
        selected = initialized("selected")
        rc, out = _run(["init", "--fleet-home", str(selected)],
                       monkeypatch, capsys)
        assert rc == 0, out.err
        assert (selected / "state" / "worker-settings.json").exists()
        assert not (isolated_cwd / "state").exists()
        assert not sandboxed_list.exists()

    def test_statusline_setup_keeps_using_the_resolved_home(
            self, monkeypatch, capsys, initialized, isolated_cwd):
        ambient = initialized("ambient")
        monkeypatch.setattr(fleet, "FLEET_HOME", ambient)
        calls = []
        monkeypatch.setattr(fleet, "_install_statusline",
                            lambda **kw: calls.append((fleet.FLEET_HOME, kw)))
        rc, out = _run(["init", "--statusline", "--chain"], monkeypatch, capsys)
        assert rc == 0, out.err
        assert calls == [(ambient, {"force": False, "chain": True})]
        assert (ambient / "state" / "worker-settings.json").exists()
        assert not (isolated_cwd / "state").exists()

    def test_creation_still_passes_the_supervisor_gate_before_writing(
            self, monkeypatch, capsys, isolated_cwd):
        def refuse(command, *, nonce=None):
            assert command == "init" and nonce == "proof"
            raise fleet.FleetCliError("gate refused")
        monkeypatch.setattr(fleet, "_supervisor_gate", refuse)
        rc, out = _run(["init", "--nonce", "proof"], monkeypatch, capsys)
        assert rc == 1 and "gate refused" in out.err
        assert not (isolated_cwd / "state").exists()
