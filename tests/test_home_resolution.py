"""§5's resolution order and the global `--fleet-home` flag (multi-fleet slice
a2: `docs/specs/multi-fleet.md` §5 steps 1-5, `docs/mf-slice-a-price.md` §a2).

WHAT a2 OWES AND WHAT IT DOES NOT. The five-step order, the flag, the rb7 C-2
dest reconciliation, and the two refusals §5's own steps specify (the terminus,
and the flag/lookup disagreement). The verb-effect table, the arming rule and
the destructive-tier guard are slice a3's and are deliberately absent from this
file -- `TERMINUS_VIEW_VERBS` is a2's *"does this verb write at the terminus?"*
split and must not be read as the ratified tiering.

THREE THINGS THIS FILE PINS THAT ARE EASY TO GET WRONG, each with the
measurement that made it a pin rather than a preference:

 1. **Resolve BEFORE validate** (ga1 N5). `registry_path_at` documents *"no
    resolution"*, so `home_is_initialized(".")` reads the process CWD --
    measured returning the CWD's own roster. Validation ordered the other way
    accepts `--fleet-home .` because the shell happened to be standing in a
    fleet home, and hands the verb a relative string whose meaning changes on
    the next chdir. `test_the_resolved_home_survives_a_chdir` is the
    order-sensitive half: it goes RED under the mutant and cannot be satisfied
    by a validator that merely happens to say no.

 2. **The flag is taken out of argv, not added to the parser** (rb7 C-2). An
    argparse optional on the top-level parser must precede the subcommand, so
    `fleet clean --fleet-home H` would be a usage error while `fleet autoclean
    --fleet-home H` worked -- luck of position, which the pin file's own
    docstring says *"cannot be step 1 of a resolution order"*. Both positions
    are driven here and required to agree.

 3. **A miss falls through for every verb class.** v6's miss-refusal is DELETED
    and `test_a_miss_falls_through_for_every_verb_class` is what stops it being
    reinvented: it drives the four classes the deletion was argued over (a
    manager with a sid nothing claims, a freshly dispatched body inside the
    pre-claim window, a plain human shell, a worker) and requires all four to
    reach dispatch.

ISOLATION: `homes_list_path` is redirected per test -- conftest's autouse home
sandbox enumerates three helpers by name and this is not one of them -- and
`INSTALL_ROOT` is already redirected to an empty fixture install by conftest,
which is exactly the *"legacy home that is not initialized"* shape §5 step 2's
population term needs.
"""
import argparse
import json
import os
from pathlib import Path

import pytest

import fleet

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"


@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


@pytest.fixture
def home(tmp_path):
    """An INITIALIZED home: `state/fleet.json` exists and parses (§Definitions).

    `fleet init` deliberately does NOT produce this -- the registry appears on
    the first `save_registry` -- so the fixture writes it directly rather than
    pretending a verb would have."""
    def make(name, workers=None):
        h = tmp_path / name
        (h / "state").mkdir(parents=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        return h
    return make


@pytest.fixture
def bare(tmp_path):
    def make(name):
        h = tmp_path / name
        h.mkdir()
        return h
    return make


def _list(sandboxed_list, *homes):
    sandboxed_list.write_text(
        "".join(f"{fleet.home_identity(h)}\n" for h in homes), encoding="utf-8")


def _rec(session_id=None, retired=(), spawned_by=None):
    return {"session_id": session_id, "retired_sids": list(retired),
            "spawned_by": spawned_by}


# ---------------------------------------------------------------------------
# Step 1 -- the flag, and ga1 N5's resolve-then-validate order
# ---------------------------------------------------------------------------

class TestTheFlagIsValidatedInSpecOrder:
    def test_an_initialized_home_validates_to_its_resolved_path(self, home):
        h = home("H")
        assert fleet.validate_named_home(str(h)) == h.resolve()

    def test_a_relative_argument_is_judged_at_its_resolved_location(
            self, home, bare, monkeypatch):
        """ga1 N5, the primary direction. With the process standing in an
        initialized home, `--fleet-home <subdir>` must be judged at
        `<cwd>/<subdir>` -- the resolved location -- and refused, not accepted
        because the CWD it would otherwise read happens to be a home."""
        h = home("H")
        (h / "sub").mkdir()
        monkeypatch.chdir(h)
        with pytest.raises(fleet.FleetCliError, match="not initialized") as exc:
            fleet.validate_named_home("sub")
        assert str((h / "sub").resolve()) in str(exc.value), (
            "the refusal named something other than the directory the flag "
            "actually reached -- validation ran on the typed string")

    def test_the_refusal_names_the_resolved_path_not_the_typed_one(
            self, home, bare, monkeypatch):
        """An operator told *"`.` is not initialized"* has been told nothing.
        The refusal must name the directory the flag actually reached."""
        b = bare("B")
        monkeypatch.chdir(b)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.validate_named_home(".")
        assert str(b.resolve()) in str(exc.value)

    def test_the_resolved_home_survives_a_chdir(self, home, monkeypatch, tmp_path):
        """THE ORDER-SENSITIVE PIN (ga1 N5's mutant). Validating before
        resolving -- or returning the operator's string instead of the resolved
        path -- yields a value whose meaning is the CWD at the moment it is
        USED, not at the moment it was named.

        MEASURED as the seed for this test: with `--fleet-home .` accepted from
        inside a home and returned verbatim, `home_is_initialized(result)` flips
        from True to False on the next chdir. Resolution first makes the value
        CWD-independent from the first line onward, which is the property this
        asserts."""
        h = home("H")
        monkeypatch.chdir(h)
        resolved = fleet.validate_named_home(".")
        monkeypatch.chdir(tmp_path)
        assert resolved.is_absolute()
        assert fleet.home_is_initialized(resolved)

    def test_an_uninitialized_directory_is_refused_and_nothing_is_created(
            self, bare):
        b = bare("B")
        with pytest.raises(fleet.FleetCliError, match="not initialized"):
            fleet.validate_named_home(str(b))
        assert not (b / "state").exists(), (
            "§Definitions binds the no-mkdir rule to resolution and read paths; "
            "a refused --fleet-home must leave no directory behind to make the "
            "typo look right on the second run")

    def test_the_not_a_directory_refusal_also_names_the_resolved_path(
            self, tmp_path, monkeypatch):
        """ga2 A8, CLOSED. `validate_named_home` refuses on three branches --
        empty, not-a-directory, not-initialized -- and ga1 N5's resolve-BEFORE-
        judge property was pinned on the third and on the success path, never on
        the second. The gate's `G3-ORDER` mutant moved `is_dir` ahead of
        `resolve()` so the refusal named the raw string `'nosuchdir'` instead of
        `<cwd>/nosuchdir`, and 225 targeted tests passed under it.

        THIS IS ga1 N5's OWN DEFECT SURVIVING ON THE SIBLING BRANCH OF THE
        FUNCTION BUILT TO CLOSE IT -- this repo's named recurring class (fix the
        reported site, miss the sibling) reappearing inside the fix. The
        operator harm is the one N5 named: a refusal that says *"`.` is not a
        directory"* has told the operator nothing, because which directory `.`
        meant depends on where the shell was standing."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.validate_named_home("nosuchdir")
        assert (tmp_path / "nosuchdir").resolve().as_posix().replace(
            "/", os.sep) in str(exc.value).replace("/", os.sep), (
            "the not-a-directory refusal names the typed string, not the "
            "resolved path -- `is_dir` is being judged before `resolve()`")

    def test_a_nonexistent_path_is_refused_and_nothing_is_created(self, tmp_path):
        missing = tmp_path / "nope" / "deeper"
        with pytest.raises(fleet.FleetCliError, match="does not exist"):
            fleet.validate_named_home(str(missing))
        assert not missing.exists()
        assert not (tmp_path / "nope").exists()

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_an_empty_flag_is_refused_rather_than_resolving_to_the_cwd(self, value):
        with pytest.raises(fleet.FleetCliError, match="empty value"):
            fleet.validate_named_home(value)

    def test_the_source_name_is_carried_into_the_refusal(self, bare):
        """One validator serves `--fleet-home`, `FLEET_HOME` and slice (b)'s
        `init --home`; each must name its own surface or the operator is told to
        fix a flag they did not use."""
        with pytest.raises(fleet.FleetCliError, match="FLEET_HOME"):
            fleet.validate_named_home(str(bare("B")), source="FLEET_HOME")


# ---------------------------------------------------------------------------
# rb7 C-2 -- the dest reconciliation
# ---------------------------------------------------------------------------

class TestTheGlobalFlagIsReconciledNotClobbered:
    """rb7 C-2, the slice condition the 2026-07-30 ratification named. The
    latent defect is a top-level `--fleet-home` sharing a dest with
    `autoclean`'s: argparse's subparser namespace copy writes the verb's default
    over the already-parsed global value, and only for that verb.

    `tests/test_round7_defect_pins.py::TestGlobalPositionFleetHome` is the lint
    that makes the clobbering shape unlandable; this class pins the mechanism
    a2 chose instead, and the property that mechanism buys."""

    @pytest.mark.parametrize("argv", [
        ["--fleet-home", "VALUE", "autoclean"],
        ["autoclean", "--fleet-home", "VALUE"],
        ["--fleet-home=VALUE", "autoclean"],
        ["autoclean", "--fleet-home=VALUE"],
    ])
    def test_every_position_yields_the_same_home(self, argv):
        """THE PROPERTY THE PIN'S OWN DOCSTRING DEMANDS: *"a value that depends
        on which side of the verb it was typed cannot be step 1 of a resolution
        order"*. Four spellings, one answer."""
        rest, value = fleet.strip_global_fleet_home(argv)
        assert value == "VALUE"
        assert rest == ["autoclean"]

    def test_the_flag_reaches_verbs_that_never_defined_it(self):
        """An argparse global could not do this: optionals must precede the
        subcommand, so `fleet clean --fleet-home H` is a usage error for the 32
        verbs that do not redefine the flag."""
        rest, value = fleet.strip_global_fleet_home(
            ["clean", "--yes", "--fleet-home", "H"])
        assert (rest, value) == (["clean", "--yes"], "H")

    def test_no_top_level_dest_exists_for_a_subparser_to_clobber(self):
        """THE RECONCILIATION, STATED AS THE ABSENCE IT IS. The collision needs
        two dests; a2 ships one, one layer above argparse. This is the
        assertion that goes RED if someone later "simplifies" the strip into a
        top-level `add_argument` -- which is also the exact shape
        `test_no_subparser_redefines_a_top_level_dest` refuses."""
        top = fleet.build_parser()
        top_opts = {o for a in top._actions
                    if not isinstance(a, argparse._SubParsersAction)
                    for o in a.option_strings}
        assert "--fleet-home" not in top_opts

    def test_the_flag_is_still_discoverable_from_help(self):
        """A global flag no `--help` mentions is a flag nobody finds. It rides
        the epilog rather than an action, because an action is the collision."""
        assert "--fleet-home" in fleet.build_parser().format_help()

    def test_repeating_the_flag_with_two_values_is_refused(self):
        with pytest.raises(fleet.FleetCliError, match="twice"):
            fleet.strip_global_fleet_home(
                ["--fleet-home", "A", "clean", "--fleet-home", "B"])

    def test_repeating_the_flag_with_one_value_is_not(self):
        rest, value = fleet.strip_global_fleet_home(
            ["--fleet-home", "A", "clean", "--fleet-home", "A"])
        assert (rest, value) == (["clean"], "A")

    def test_a_trailing_valueless_flag_is_left_for_argparse(self):
        """Same choice, same reason, as `_absorb_minted_flag_values` one screen
        below it: a usage error is argparse's exit 2, not fleet's exit 1."""
        assert fleet.strip_global_fleet_home(["clean", "--fleet-home"]) == (
            ["clean", "--fleet-home"], None)

    def test_tokens_after_a_bare_double_dash_are_values_not_flags(self):
        """`--` is argparse's own end-of-options marker. A `send` body or an
        index query that literally contains the flag's spelling is a value."""
        assert fleet.strip_global_fleet_home(
            ["send", "w", "--", "--fleet-home", "X"]) == (
            ["send", "w", "--", "--fleet-home", "X"], None)

    def test_the_collision_lint_still_fires_on_the_shape_a2_did_not_build(
            self, monkeypatch):
        """THE FAULT INJECTION THE SLICE CONDITION ASKS FOR, run from a2's own
        file rather than trusted from a1's. Plant the promotion a2 declined --
        a top-level `--fleet-home` over `autoclean`'s -- and require the
        shipped lint to name the offender."""
        pins = pytest.importorskip("test_round7_defect_pins")
        real = fleet.build_parser

        def planted():
            p = real()
            p.add_argument("--fleet-home", dest="fleet_home", default=None)
            return p

        monkeypatch.setattr(fleet, "build_parser", planted)
        with pytest.raises(AssertionError, match="autoclean"):
            pins.TestGlobalPositionFleetHome() \
                .test_no_subparser_redefines_a_top_level_dest()

    def test_the_clobber_the_lint_forbids_is_real_on_this_interpreter(self):
        """MEASURED, not inherited, and re-measured here because a2 is the
        slice whose mechanism choice depends on it being true. Both floors run
        this file."""
        p = argparse.ArgumentParser(prog="fleet")
        p.add_argument("--fleet-home", dest="fleet_home", default=None)
        sub = p.add_subparsers(dest="command", required=True)
        sub.add_parser("autoclean").add_argument(
            "--fleet-home", dest="fleet_home", default=None)
        sub.add_parser("clean")
        assert p.parse_args(["--fleet-home", "H", "autoclean"]).fleet_home is None
        assert p.parse_args(["--fleet-home", "H", "clean"]).fleet_home == "H"


# ---------------------------------------------------------------------------
# Step 2 -- the sid -> home lookup
# ---------------------------------------------------------------------------

class TestTheLookupPopulation:
    def test_the_population_is_the_folded_list_union_the_legacy_home(
            self, home, sandboxed_list):
        a, b = home("A"), home("B")
        _list(sandboxed_list, a, b)
        pop = fleet.resolution_population()
        assert pop["homes"] == [fleet.home_identity(a), fleet.home_identity(b),
                                fleet.home_identity(fleet.INSTALL_ROOT)]
        assert pop["legacy"] == fleet.home_identity(fleet.INSTALL_ROOT)

    def test_the_legacy_term_is_not_duplicated_when_it_is_also_listed(
            self, home, sandboxed_list, monkeypatch):
        a = home("A")
        monkeypatch.setattr(fleet, "INSTALL_ROOT", a)
        _list(sandboxed_list, a)
        assert fleet.resolution_population()["homes"] == [fleet.home_identity(a)]

    def test_a_retired_home_is_not_in_the_population(self, home, sandboxed_list):
        a = home("A")
        sandboxed_list.write_text(
            f"{fleet.home_identity(a)}\n!{fleet.home_identity(a)}\n",
            encoding="utf-8")
        assert fleet.home_identity(a) not in fleet.resolution_population()["homes"]


class TestTheLookupIsTriState:
    def test_exactly_one_member_home_resolves(self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-2")})
        _list(sandboxed_list, a, b)
        look = fleet.lookup_home_for_sid("SID-1")
        assert (look["state"], look["home"]) == ("hit", fleet.home_identity(a))

    def test_two_member_homes_are_ambiguous(self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        assert fleet.lookup_home_for_sid("SID-1")["state"] == "ambiguous"

    def test_no_member_home_is_a_miss(self, home, sandboxed_list):
        _list(sandboxed_list, home("A", {"w": _rec("SID-1")}))
        assert fleet.lookup_home_for_sid("SID-OTHER")["state"] == "miss"

    def test_a_sidless_caller_is_its_own_state(self, home, sandboxed_list):
        """*"Nobody asked"* and *"asked and nothing matched"* are different
        facts. Both fall through; only one of them is evidence about the
        registry."""
        _list(sandboxed_list, home("A", {"w": _rec("SID-1")}))
        for sid in (None, "", "   "):
            assert fleet.lookup_home_for_sid(sid)["state"] == "no_sid"

    def test_an_unreadable_home_is_counted_and_never_raises(
            self, home, bare, sandboxed_list):
        """§5.2: an unreadable home is reported, and a lookup that would have
        matched only it is *"indistinguishable from a miss -- which is why the
        destructive tier below exists"*. a2 reports; a3 tiers."""
        a = home("A")
        (a / "state" / "fleet.json").write_text("{not json", encoding="utf-8")
        b = home("B", {"w": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        look = fleet.lookup_home_for_sid("SID-1")
        assert look["unreadable"] == [fleet.home_identity(a)]
        assert (look["state"], look["home"]) == ("hit", fleet.home_identity(b))

    def test_two_spellings_of_one_directory_are_one_hit(self, home, sandboxed_list):
        """§5's two-plus refusal is about a sid claimed by two FLEETS. A home
        listed twice with different separators is one fleet, and refusing there
        would make the escape hatch fire on a spelling."""
        a = home("A", {"w": _rec("SID-1")})
        ident = fleet.home_identity(a)
        sandboxed_list.write_text(f"{ident}\n{ident.replace('/', chr(92))}\n",
                                  encoding="utf-8")
        assert fleet.lookup_home_for_sid("SID-1")["state"] == "hit"


class TestMembershipIsTheUnionAndSpawnedByNeverGrantsIt:
    def test_the_current_session_id_grants_membership(self, home, sandboxed_list):
        _list(sandboxed_list, home("A", {"w": _rec("SID-1")}))
        assert fleet.lookup_home_for_sid("SID-1")["state"] == "hit"

    def test_a_retired_sid_grants_membership(self, home, sandboxed_list):
        """§5.2's membership is `session_id` u `retired_sids`. A fork-steered or
        respawned body carries its prior sid in `retired_sids` and must not stop
        being a member of its own home mid-rotation."""
        _list(sandboxed_list, home("A", {"w": _rec("SID-NEW", retired=["SID-OLD"])}))
        assert fleet.lookup_home_for_sid("SID-OLD")["state"] == "hit"

    def test_spawned_by_never_grants_membership(self, home, sandboxed_list):
        """PINNED BY THE SPEC IN THOSE WORDS. `spawned_by` is the MANAGER's sid,
        so honouring it would make every manager a member of every home it ever
        dispatched into -- ambiguity by construction, on the one caller class §5
        most needs to serve."""
        a = home("A", {"w": _rec("SID-W", spawned_by="SID-MANAGER")})
        b = home("B", {"x": _rec("SID-X", spawned_by="SID-MANAGER")})
        _list(sandboxed_list, a, b)
        assert fleet.lookup_home_for_sid("SID-MANAGER")["state"] == "miss"

    def test_the_membership_union_is_the_repos_one_spelling(self):
        """A second copy of *"every sid this record has ever been"* is how a
        fork-steered body stops matching its own home. This is a derivation, not
        a transcription: it fails if the lookup grows its own union."""
        import inspect
        src = inspect.getsource(fleet.lookup_home_for_sid)
        assert "_record_sids" in src
        assert "retired_sids" not in src.split('"""')[-1], (
            "the lookup re-derives the sid union instead of calling "
            "`_record_sids` -- two spellings of membership is the defect")


# ---------------------------------------------------------------------------
# The order itself, and the terminus
# ---------------------------------------------------------------------------

class TestTheFiveStepOrder:
    def test_the_flag_outranks_a_lookup_hit(self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a, b)
        res = fleet.resolve_home(flag=str(b), sid="SID-1", default_home=a)
        assert (res["step"], res["home"]) == ("flag", b.resolve())

    def test_a_lookup_hit_outranks_the_env_and_the_default(
            self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a)
        res = fleet.resolve_home(sid="SID-1", default_home=b, env=str(b))
        assert (res["step"], Path(res["home"])) == ("lookup", Path(a))

    def test_a_matching_env_var_is_labelled_env(self, home, sandboxed_list):
        a = home("A")
        res = fleet.resolve_home(sid=None, default_home=a, env=str(a))
        assert (res["step"], res["home"]) == ("env", a)

    def test_an_unset_env_var_is_labelled_legacy(self, home, sandboxed_list):
        a = home("A")
        res = fleet.resolve_home(sid=None, default_home=a, env=None)
        assert res["step"] == "legacy"

    def test_a_monkeypatched_home_that_no_longer_matches_the_env_reads_legacy(
            self, home):
        """The suite's own shape, and the reason steps 3 and 4 are evaluated
        against the module global rather than re-derived from `os.environ`:
        re-deriving them would resolve every test to conftest's empty fixture
        install instead of its own tmp home."""
        a, b = home("A"), home("B")
        res = fleet.resolve_home(sid=None, default_home=a, env=str(b))
        assert (res["step"], res["home"]) == ("legacy", a)

    def test_no_step_resolving_is_the_terminus(self, bare, home, sandboxed_list):
        res = fleet.resolve_home(sid=None, default_home=bare("B"), env=None)
        assert res["step"] is None and res["home"] is None

    def test_ambiguity_refuses_naming_every_home(self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.resolve_home(sid="SID-1", default_home=a)
        for h in (a, b):
            assert fleet.home_identity(h) in str(exc.value)

    def test_a_refusal_embeds_the_homes_view_and_prefills_no_home(
            self, home, sandboxed_list):
        """§5's refusal contract: *"Refusals print facts + the `fleet homes`
        view, never a paste-ready command with a chosen home."*"""
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        with pytest.raises(fleet.FleetCliError) as exc:
            fleet.resolve_home(sid="SID-1", default_home=a)
        text = str(exc.value)
        assert "fleet homes:" in text
        assert f"--fleet-home {fleet.home_identity(a)}" not in text
        assert f"--fleet-home {fleet.home_identity(b)}" not in text


class TestResolutionNeverWrites:
    def test_resolution_creates_nothing_at_the_terminus(self, bare, sandboxed_list):
        """§Definitions: the no-mkdir rule *"binds resolution and read paths"*.
        The terminus is the path most likely to be tempted."""
        b = bare("B")
        fleet.resolve_home(sid="SID-1", default_home=b, env=None)
        assert list(b.iterdir()) == []
        assert not sandboxed_list.exists()

    def test_resolution_takes_no_lock(self, home, sandboxed_list, monkeypatch):
        a = home("A", {"w": _rec("SID-1")})
        _list(sandboxed_list, a)

        def explode(*_a, **_k):
            raise AssertionError("resolution took fleet.lock")

        monkeypatch.setattr(fleet, "fleet_lock", explode)
        assert fleet.resolve_home(sid="SID-1", default_home=a)["step"] == "lookup"


# ---------------------------------------------------------------------------
# main() -- the wiring, the terminus split, the disagreement
# ---------------------------------------------------------------------------

def _run(argv, monkeypatch, sid=None):
    monkeypatch.delenv("FLEET_HOME", raising=False)
    if sid is None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
    return fleet.main(argv)


def _shortest_parsing_argv(parser, verb):
    """The shortest of `[verb]`, `[verb, X]`, `[verb, X, Y]` that argparse
    accepts, or None when the verb needs named options a mechanical sweep does
    not supply. Mechanical on purpose: a hand table of per-verb argv would rot
    exactly the way the three-name list it replaces would."""
    for tail in ([verb], [verb, "X"], [verb, "X", "Y"]):
        try:
            parser.parse_args(tail)
        except SystemExit:
            continue
        return tail
    return None


class TestMainAppliesTheOrderBeforeDispatch:
    def test_the_flag_moves_the_home_from_either_position(
            self, home, monkeypatch, capsys):
        a, b = home("A"), home("B")
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["--fleet-home", str(b), "home"], monkeypatch) == 0
        first = capsys.readouterr().out.strip()
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["home", "--fleet-home", str(b)], monkeypatch) == 0
        assert capsys.readouterr().out.strip() == first == b.resolve().as_posix()

    def test_a_lookup_hit_moves_the_home(self, home, sandboxed_list,
                                         monkeypatch, capsys):
        a = home("A")
        b = home("B", {"w": _rec("SID-1")})
        _list(sandboxed_list, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["home"], monkeypatch, sid="SID-1") == 0
        assert capsys.readouterr().out.strip() == b.resolve().as_posix()

    def test_a_miss_leaves_the_home_where_it_was(self, home, sandboxed_list,
                                                 monkeypatch, capsys):
        a = home("A")
        _list(sandboxed_list, home("B", {"w": _rec("SID-1")}))
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["home"], monkeypatch, sid="SID-NOBODY") == 0
        assert capsys.readouterr().out.strip() == a.resolve().as_posix()

    @pytest.mark.parametrize("sid", [None, "SID-NOBODY", "SID-PRECLAIM", "SID-WORKER"])
    def test_a_miss_falls_through_for_every_verb_class(
            self, sid, home, sandboxed_list, monkeypatch, capsys):
        """v6's miss-refusal is DELETED and must not be reinvented. The four
        callers it was killed over: a plain human shell (no sid), a manager
        whose sid nothing claims, a freshly dispatched body still inside the
        6.8-63s pre-claim window (its record's `session_id` is still None), and
        a worker of a home that is not this one. All four reach dispatch."""
        a = home("A")
        _list(sandboxed_list, home("B", {"pending": _rec(None),
                                         "other": _rec("SID-ELSEWHERE")}))
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["home"], monkeypatch, sid=sid) == 0
        assert capsys.readouterr().out.strip() == a.resolve().as_posix()


class TestTheTerminus:
    """§5 step 5: *"mutating verbs refuse with the named remedy (`--fleet-home`
    or `FLEET_HOME`), and views render `[fleet]: no home` and exit 0."*

    GATED ON THE MULTI-FLEET POPULATION BEING LIVE, and the gate is a2's, not
    the spec's -- see `_multi_fleet_population_is_live` for the two measured
    reasons (§5's own *"<2: byte-identical to today"*, and the fact that no
    shipped verb creates `state/fleet.json` except a spawn the terminus would
    itself refuse). Both directions are pinned here."""

    def test_a_view_renders_the_words_and_exits_zero(
            self, bare, home, sandboxed_list, monkeypatch, capsys):
        _list(sandboxed_list, home("L"))
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        assert _run(["status"], monkeypatch) == 0
        assert capsys.readouterr().out.strip() == fleet.NO_HOME_LINE

    def test_a_mutating_verb_refuses_naming_the_remedy(
            self, bare, home, sandboxed_list, monkeypatch, capsys):
        _list(sandboxed_list, home("L"))
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        assert _run(["clean", "--yes"], monkeypatch) == 1
        err = capsys.readouterr().err
        assert "--fleet-home" in err and "FLEET_HOME" in err

    def test_the_refusal_names_no_chosen_home(
            self, bare, home, sandboxed_list, monkeypatch, capsys):
        listed = home("L")
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        _list(sandboxed_list, listed)
        assert _run(["clean", "--yes"], monkeypatch) == 1
        assert f"--fleet-home {fleet.home_identity(listed)}" not in \
            capsys.readouterr().err

    def test_the_terminus_does_not_fire_on_a_single_fleet_machine(
            self, bare, monkeypatch, capsys):
        """§5's arming paragraph: *"With a determinate population of <2:
        byte-identical to today"*. No homes list, one fleet, one home -- a
        refusal here is a behaviour change on every machine that exists today,
        and it would brick a fresh home, because nothing but a spawn writes the
        `state/fleet.json` that would end the terminus."""
        b = bare("B")
        monkeypatch.setattr(fleet, "FLEET_HOME", b)
        assert _run(["home"], monkeypatch) == 0
        assert capsys.readouterr().out.strip() == b.resolve().as_posix()

    def test_an_unreadable_list_arms_the_terminus(
            self, bare, sandboxed_list, monkeypatch, capsys):
        """§4: an unreadable list is *"armed-with-unknown-population"*;
        indeterminacy never selects the permissive branch."""
        sandboxed_list.write_text("x", encoding="utf-8")
        monkeypatch.setattr(fleet, "read_homes_list",
                            lambda: {"path": sandboxed_list, "ok": False,
                                     "reason": "unreadable", "members": [],
                                     "retired": [], "invalid_lines": 0,
                                     "decode_note": None})
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        assert _run(["clean", "--yes"], monkeypatch) == 1

    def test_doctor_repair_is_not_a_view_at_the_terminus(
            self, bare, home, sandboxed_list, monkeypatch):
        """`doctor` reports and `doctor --repair` renames a registry aside. One
        of those is a view."""
        _list(sandboxed_list, home("L"))
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        assert _run(["doctor", "--repair"], monkeypatch) == 1

    def test_the_list_manager_is_never_intercepted_by_the_terminus(
            self, bare, home, sandboxed_list, monkeypatch, capsys):
        """THE DEADLOCK THIS FILE'S FIRST DRAFT SHIPPED, now a pin. `homes` was
        in the view tuple, so at the terminus `fleet homes --add <PATH>` printed
        *"[fleet]: no home"* and exited 0 without appending -- the guard eating
        its own remedy. §5 step 5's remedy is *"name a home"*, and this is the
        verb that names one; it acts on the MACHINE list, not on a home, so no
        home needs to resolve for it to run."""
        target = home("T")
        _list(sandboxed_list, home("L"))
        monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
        assert _run(["homes", "--add", str(target)], monkeypatch) == 0
        assert "added" in capsys.readouterr().out
        assert fleet.home_identity(target) in fleet.read_homes_list()["members"]

    def test_the_list_manager_runs_under_a_lookup_ambiguity(
            self, home, sandboxed_list, monkeypatch, capsys):
        """THE SECOND HALF OF THE SAME DEADLOCK, and it survived the first fix.
        A sid claimed by two homes raises §5 step 2's ambiguity refusal for
        every verb -- including `fleet homes --retire`, which is the ONLY way
        an operator un-claims one of the two. Both of the resolver's blocking
        states name `fleet homes` as their remedy, so the exemption has to sit
        above both, not just above the terminus."""
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["homes", "--retire", str(b)], monkeypatch, sid="SID-1") == 0
        assert fleet.home_identity(b) not in fleet.read_homes_list()["members"]

    def test_the_list_manager_still_validates_the_flag(
            self, bare, monkeypatch, capsys):
        """Exempt from the ORDER, not from step 1's own contract. Silently
        ignoring a `--fleet-home` the operator typed is its own defect."""
        assert _run(["--fleet-home", str(bare("B")), "homes"], monkeypatch) == 1
        assert "not initialized" in capsys.readouterr().err

    def test_the_view_set_is_not_the_verb_effect_table(self):
        """a3 owns the ratified tiering. If someone later points this tuple at
        `RATIFIED_ORDINARY`, `spawn` and `init` become views at the terminus and
        write into a directory no step selected.

        ga2 A1, CLOSED, AND THE FIX IS THE DERIVATION RATHER THAN A LONGER
        LIST. This asserted absence for exactly NINE hand-listed verbs, and the
        gate measured what that left open: adding `"autoclean"` -- a RATIFIED
        DESTRUCTIVE verb -- to `TERMINUS_VIEW_VERBS` made `fleet autoclean`
        render `[fleet]: no home` and exit 0 at the terminus while the full
        suite read `3999 passed, 14 skipped, 1 xfailed`, byte-identical to the
        clean floor. Nine of the twenty-three classified verbs were watched;
        ten of the unwatched fourteen were ratified destructive. The tuple's
        docstring defends the DEFAULT (absence => refuse), which holds; what was
        unguarded was ADDITION.

        A hand list cannot close that -- a longer hand list is the same defect
        with a later expiry date, and this repo's named recurring class is
        exactly an enumeration smaller than reality. The forbidden set is now
        DERIVED from the tiering itself, so a verb classified destructive or
        disruptive tomorrow is forbidden here the moment it is classified,
        without anyone remembering to come back."""
        tokens = fleet.VERB_EFFECT_DESTRUCTIVE + fleet.VERB_EFFECT_DISRUPTIVE
        forbidden = {t for t in tokens if " " not in t}
        assert len(forbidden) >= 17, "the derivation went vacuous"
        leaked = sorted(forbidden & set(fleet.TERMINUS_VIEW_VERBS))
        assert not leaked, (
            f"{leaked} are ratified destructive/disruptive and are in "
            f"`TERMINUS_VIEW_VERBS`, so at the terminus they would render "
            f"`{fleet.NO_HOME_LINE}` and exit 0 instead of refusing")

    def test_a_flag_qualified_row_reaches_the_terminus_through_a_carve_out(self):
        """THE HALF THE DERIVATION ABOVE CANNOT DO, AND IT IS NOT A DETAIL --
        it is what the ga2 A1 remedy gets wrong if applied literally.

        Two ratified rows carry a FLAG (`doctor --repair`, `sup-decision
        --clear`), so at verb granularity the derived set forbids `doctor` --
        and `doctor` is in `TERMINUS_VIEW_VERBS` deliberately and correctly,
        because `doctor` reports and only `doctor --repair` renames a registry
        aside. Forbidding the bare verb would delete a2's own pinned split
        (`test_doctor_repair_is_not_a_view_at_the_terminus`) in the name of
        closing a gap.

        So the derivation covers the BARE tokens, and this covers the other
        kind: every flag-qualified row whose verb IS a terminus view must have
        its dest checked in `apply_resolved_home`, or the flag reaches the view
        arm and the destructive form renders `[fleet]: no home` and exits 0.
        Derived from the source, so the third such row is caught the day it is
        transcribed."""
        import inspect
        body = inspect.getsource(fleet.apply_resolved_home)
        for token in (fleet.VERB_EFFECT_DESTRUCTIVE
                      + fleet.VERB_EFFECT_DISRUPTIVE):
            if " " not in token:
                continue
            verb, flag = token.split()[0], token.split()[1]
            if verb not in fleet.TERMINUS_VIEW_VERBS:
                continue
            dest = flag.lstrip("-").replace("-", "_")
            assert f'"{dest}"' in body, (
                f"`{token}` is ratified destructive/disruptive and `{verb}` is "
                f"a terminus view, but `apply_resolved_home` never reads "
                f"`{dest}` -- so `fleet {verb} {flag}` renders "
                f"`{fleet.NO_HOME_LINE}` and exits 0 at the terminus")

    def test_the_seed_the_derived_forbidden_set_can_see_a_leak(self,
                                                               monkeypatch):
        """A negative over a derived set proves nothing until it is shown
        firing, and the mutant the gate planted is the exact shape to plant:
        one ratified-destructive verb added to the view tuple."""
        monkeypatch.setattr(fleet, "TERMINUS_VIEW_VERBS",
                            fleet.TERMINUS_VIEW_VERBS + ("autoclean",))
        with pytest.raises(AssertionError, match="autoclean"):
            TestTheTerminus().test_the_view_set_is_not_the_verb_effect_table()

    def test_the_seed_the_carve_out_check_can_see_a_missing_one(self,
                                                                monkeypatch):
        monkeypatch.setattr(fleet, "TERMINUS_VIEW_VERBS",
                            fleet.TERMINUS_VIEW_VERBS + ("sup-decision",))
        with pytest.raises(AssertionError, match="sup-decision --clear"):
            TestTheTerminus() \
                .test_a_flag_qualified_row_reaches_the_terminus_through_a_carve_out()


class TestTheFlagLookupDisagreement:
    """§5 step 1: *"Flag/lookup disagreement -> mutating verbs refuse without
    `--yes` + witness line."*"""

    def test_agreement_is_not_a_disagreement(self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        _list(sandboxed_list, a)
        res = fleet.resolve_home(flag=str(a), sid="SID-1", default_home=a)
        assert res["disagreement"] is None

    def test_a_different_home_is_reported_as_the_disagreement(
            self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a)
        res = fleet.resolve_home(flag=str(b), sid="SID-1", default_home=a)
        assert res["disagreement"] == fleet.home_identity(a)

    def test_a_mutating_verb_refuses_without_yes(
            self, home, sandboxed_list, monkeypatch, capsys):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["--fleet-home", str(b), "clean"], monkeypatch, sid="SID-1") == 1
        assert "WITNESS" in capsys.readouterr().err

    def test_yes_proceeds_and_prints_the_witness_line(
            self, home, sandboxed_list, monkeypatch, capsys):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        rc = _run(["--fleet-home", str(b), "clean", "--yes"], monkeypatch, sid="SID-1")
        out = capsys.readouterr().out
        assert rc == 0
        assert "WITNESS" in out
        assert b.resolve().as_posix() in out and a.resolve().as_posix() in out

    @pytest.fixture
    def disagreeing(self, home, sandboxed_list, monkeypatch):
        """The flag names B; the session belongs to A. §5 step 1's own row."""
        a = home("A", {"w": _rec("SID-1")})
        b = home("B")
        _list(sandboxed_list, a)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        return b

    def _refuse(self, tail, disagreeing, monkeypatch, capsys):
        capsys.readouterr()   # argparse's own usage text is not this refusal
        assert _run(["--fleet-home", str(disagreeing), *tail],
                    monkeypatch, sid="SID-1") == 1
        return capsys.readouterr().err

    def test_the_refusal_does_not_name_yes_on_a_verb_that_has_no_yes(
            self, disagreeing, monkeypatch, capsys):
        """ga3 B2, and ga2's F2 as ga2 actually stated it. `--yes` exists on
        3 of 33 verbs (`clean`, `kill`, `respawn`); for the other 30 the
        sentence *"Re-run with `--yes`"* names a remedy that is
        `SystemExit(2)`, an argparse usage error. That is the exact class
        `TestFleetHomesSitsAboveEveryBlockingStateTheResolverEnters` was built
        to prevent -- A REFUSAL THAT NAMES A REMEDY THE MACHINE WILL NOT
        ACCEPT -- and it missed this one by construction, because it drives
        the disagreement row with `clean`, one of the three.

        WHAT IS FIXED HERE IS THE MESSAGE, NOT §5. Whether step 1's `--yes`
        escape should be narrowed in text or `--yes` promoted globally the way
        `--fleet-home` was is an edit to a ratified section and is filed as an
        operator gate. This pin only says the sentence must be honest about
        the tree as it stands."""
        err = self._refuse(["archive"], disagreeing, monkeypatch, capsys)
        assert "--yes" not in err
        assert "drop `--fleet-home`" in err.lower()

    def test_the_refusal_still_names_yes_on_a_verb_that_has_one(
            self, disagreeing, monkeypatch, capsys):
        """THE HALF THE FIX MUST NOT EAT. Making the sentence conditional is
        not licence to delete it: where `--yes` exists it IS the remedy, and
        `test_yes_proceeds_and_prints_the_witness_line` above proves it
        works."""
        err = self._refuse(["clean"], disagreeing, monkeypatch, capsys)
        assert "--yes" in err
        assert "drop `--fleet-home`" in err.lower()

    def test_the_yes_sentence_appears_exactly_where_the_verb_takes_it(
            self, disagreeing, monkeypatch, capsys):
        """The general form, driven over `build_parser()` rather than over the
        three verb names that carry `--yes` today, so a later slice that grows
        or drops one cannot leave the message behind. Argv for each verb is
        found MECHANICALLY -- the shortest of `[]`, `[X]`, `[X, Y]` that
        parses -- rather than from a hand table that would rot the same way.

        NOT EVERY VERB IS REACHABLE THIS WAY and the shortfall is asserted
        rather than swallowed: six verbs need named options to parse (`index`,
        `spawn`, `sup-checkpoint`, `sup-handoff-complete`, `sup-spawn`,
        `wait`), so the sweep requires that every `--yes`-carrying verb was
        actually driven and that the rest of the parser's verbs are accounted
        for either as driven or as unreachable."""
        parser = fleet.build_parser()
        subs = next(a.choices for a in parser._actions
                    if hasattr(a, "choices") and isinstance(a.choices, dict))
        wants_yes = {v for v, s in subs.items()
                     if any(getattr(a, "dest", None) == "yes"
                            for a in s._actions)}
        driven, unreachable = set(), set()
        for verb in sorted(subs):
            if verb in fleet.TERMINUS_EXEMPT_VERBS:
                continue
            tail = _shortest_parsing_argv(parser, verb)
            if tail is None:
                unreachable.add(verb)
                continue
            err = self._refuse(tail, disagreeing, monkeypatch, capsys)
            assert ("--yes" in err) is (verb in wants_yes), verb
            driven.add(verb)
        assert wants_yes <= driven, f"never exercised: {wants_yes - driven}"
        assert driven | unreachable | set(fleet.TERMINUS_EXEMPT_VERBS) \
            == set(subs)


class TestTheAmbiguousLookupIsAlsoADisagreement:
    """ga2 A2, CLOSED. §5 step 1's clause is unconditional -- *"Flag/lookup
    disagreement -> mutating verbs refuse without `--yes` + witness line"* --
    and a2 computed `disagreement` only when `look["state"] == "hit"`. The gate
    measured the consequence: with `--fleet-home C` and a sid claimed by A AND
    B, `fleet --fleet-home C clean` returned rc 0 with no witness line and no
    `--yes` required. A session belonging to two homes, told to act on a third,
    is the strongest disagreement this resolver can see and it was silent.

    WHY THIS IS CLOSED RATHER THAN ESCALATED. The gate called shipped behaviour
    *"arguably defensible"* because the ambiguity refusal's own remedy text is
    *"Name the one you mean with `--fleet-home <PATH>`"*, so the flag is the
    sanctioned escape. That argument licenses exactly one case -- the flag
    naming ONE OF the claimants -- and the tests below keep that case silent
    while refusing the case the argument never covered, where the flag names a
    home no claimant is. Both halves are pinned, so a later reading cannot
    collapse them into either extreme."""

    def test_a_third_home_is_a_disagreement_naming_every_claimant(
            self, home, sandboxed_list):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        c = home("C")
        _list(sandboxed_list, a, b)
        res = fleet.resolve_home(flag=str(c), sid="SID-1", default_home=a)
        assert res["lookup"]["state"] == "ambiguous"
        assert res["disagreement"] is not None
        assert set(res["disagreement_homes"]) == {fleet.home_identity(a),
                                                  fleet.home_identity(b)}

    def test_a_mutating_verb_refuses_and_the_witness_names_both(
            self, home, sandboxed_list, monkeypatch, capsys):
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        c = home("C")
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        assert _run(["--fleet-home", str(c), "clean"], monkeypatch,
                    sid="SID-1") == 1
        err = capsys.readouterr().err
        assert "WITNESS" in err
        assert a.resolve().as_posix() in err and b.resolve().as_posix() in err

    def test_naming_one_of_the_claimants_is_the_sanctioned_escape(
            self, home, sandboxed_list, monkeypatch, capsys):
        """THE HALF THE FIX MUST NOT EAT. The ambiguity refusal tells the
        operator to name one; if naming one then refused as a disagreement, the
        refusal's own remedy would be unreachable -- the same shape as the
        deadlock a2 shipped twice with `fleet homes`."""
        a = home("A", {"w": _rec("SID-1")})
        b = home("B", {"x": _rec("SID-1")})
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        res = fleet.resolve_home(flag=str(b), sid="SID-1", default_home=a)
        assert res["disagreement"] is None
        assert _run(["--fleet-home", str(b), "home"], monkeypatch,
                    sid="SID-1") == 0
        assert capsys.readouterr().out.strip() == b.resolve().as_posix()

    def test_a_miss_is_still_not_a_disagreement(self, home, sandboxed_list):
        """A sid nothing claims disagrees with nothing. v6's miss-refusal is
        DELETED and this fix must not smuggle it back in through step 1."""
        a, b = home("A"), home("B")
        _list(sandboxed_list, a)
        res = fleet.resolve_home(flag=str(b), sid="SID-NOBODY", default_home=a)
        assert res["lookup"]["state"] == "miss"
        assert res["disagreement"] is None


class TestProvenanceRendering:
    @pytest.mark.parametrize("step,needle", [
        ("flag", "--fleet-home"), ("lookup", "session membership"),
        ("env", "$FLEET_HOME"), ("legacy", "legacy install-root"),
    ])
    def test_every_step_renders_a_word(self, step, needle, tmp_path):
        line = fleet.resolution_provenance({"step": step, "home": tmp_path})
        assert needle in line and tmp_path.as_posix() in line

    def test_the_terminus_renders_the_specs_own_words(self):
        assert fleet.resolution_provenance(
            {"step": None, "home": None}).startswith(fleet.NO_HOME_LINE)

    def test_unreadable_homes_are_reported_in_the_provenance(
            self, home, sandboxed_list, monkeypatch):
        """ga2 A3, CLOSED. §5:154-155 is a three-clause sentence -- *"Unreadable
        homes: reported in provenance, counted by arming, and any lookup that
        WOULD have matched only an unreadable home is indistinguishable from a
        miss"* -- and a2 shipped the second and dropped the first: the lookup
        record carried `unreadable=['U']` while this renderer printed
        `"[fleet] home .../R (via session membership)"` and never mentioned it.

        It matters more than a missing word. The unreadable home is precisely
        the one that could have been claiming this session, so a provenance line
        that omits it presents a resolution as unambiguous when the resolver
        knows it is not -- and since a2's §10 tells a3 to REUSE this renderer
        rather than mint a second spelling, following that instruction with the
        clause unmet would have shipped §5's requirement unimplemented on every
        surface at once."""
        r = home("R", {"w": _rec("SID-1")})
        u = home("U")
        _list(sandboxed_list, r, u)
        real = fleet.read_registry_at
        monkeypatch.setattr(
            fleet, "read_registry_at",
            lambda h: (False, "unreadable", {"workers": {}})
            if fleet.home_identity(h) == fleet.home_identity(u) else real(h))
        res = fleet.resolve_home(sid="SID-1", default_home=r)
        line = fleet.resolution_provenance(res)
        assert res["step"] == "lookup"
        assert fleet.home_identity(u) in line

    def test_a_record_with_no_lookup_still_renders(self, tmp_path):
        """The renderer serves hand-built records (the parametrised test above
        passes one) and is called from a refusal path. A view that raised on a
        missing key would be a view that fails."""
        assert "[fleet] home" in fleet.resolution_provenance(
            {"step": "legacy", "home": tmp_path})


class TestTheComparatorErrsTowardArming:
    """ga2 A9. `homes_are_same`'s docstring claims *"A comparison it cannot make
    answers False -- two homes it cannot prove identical are treated as
    different, which OVER-counts distinctness and therefore errs toward arming,
    the direction §5 requires"*. The gate flipped BOTH `except` arms to `return
    True` and the full suite stayed `3999 passed, 14 skipped, 1 xfailed`: the
    claim was made in words and backed by nothing.

    REACHABILITY IS LOW AND THAT IS NOT THE POINT. Every caller today passes
    strings or `Path`s and `resolve()` rarely raises on Windows -- but this
    comparator is what merges two spellings of one directory into one hit, so
    an arm that answers True on an error turns two distinct homes into one and
    the ambiguity refusal fails open. a3 makes the comparator load-bearing in a
    second place (arming counts DISTINCT homes), which is why the claim now gets
    a pin rather than a docstring."""

    def test_an_uncomparable_value_is_not_the_same_home(self):
        assert fleet.homes_are_same(object(), "C:/f") is False

    class _Planted:
        """A duck for `fleet.Path`, DELIBERATELY NOT A `Path` SUBCLASS.

        MEASURED, and it is the reason this note exists rather than a neater
        subclass: `class Exploding(Path)` is fine on py 3.13 and raises
        `AttributeError` out of `pathlib.py:585` on py 3.10, which does not
        support subclassing `Path`. Both of these tests passed on 3.13 and
        failed on 3.10 in that shape -- this repo's floor is `py -3.10` and a
        green 3.13 certifies nothing. `homes_are_same` only ever calls
        `exists`, `samefile`, `resolve` and `str`, so a duck covers it on both
        interpreters."""

        def __init__(self, raw, exists=True, samefile=None, resolve=None):
            self.raw = str(raw)
            self._exists = exists
            self._samefile = samefile
            self._resolve = resolve

        def __str__(self):
            return self.raw

        def exists(self):
            return self._exists

        def samefile(self, other):
            if self._samefile is not None:
                raise self._samefile
            return self.raw == str(other)

        def resolve(self):
            if self._resolve is not None:
                raise self._resolve
            return self.raw

    def test_a_samefile_that_raises_falls_to_the_fallback_not_to_true(
            self, tmp_path, monkeypatch):
        """THE FIRST `except` ARM, and the reason it needs two DIFFERENT
        directories: the arm is a `pass`, so a `samefile()` that raises merely
        drops through to the `normcase(resolve())` fallback -- which is correct
        behaviour and answers on its own evidence. What the mutant does is
        `return True` from there, and only a pair the fallback would call
        DIFFERENT can tell those two apart. A pair it would call the same
        passes under both."""
        monkeypatch.setattr(
            fleet, "Path",
            lambda raw: self._Planted(raw, samefile=OSError("planted")))
        assert fleet.homes_are_same(tmp_path / "a", tmp_path / "b") is False, (
            "`samefile` raised and the answer was True -- two distinct homes "
            "merged into one hit, which is the ambiguity refusal failing open")

    def test_a_resolve_that_raises_answers_false(self, monkeypatch):
        """THE SECOND `except` ARM. Here there is no further fallback, so the
        docstring's claim is the whole behaviour: a comparison that cannot be
        made answers False and over-counts distinctness."""
        monkeypatch.setattr(
            fleet, "Path",
            lambda raw: self._Planted(raw, exists=False,
                                      resolve=OSError("planted")))
        assert fleet.homes_are_same("C:/f", "C:/f") is False, (
            "a comparison that could not be made answered True, which merges "
            "two homes the resolver has not proved identical -- the ambiguity "
            "refusal failing open")


# ---------------------------------------------------------------------------
# ga1 N1 -- `fleet homes --add ""`
# ---------------------------------------------------------------------------

class TestAnEmptyHomesArgumentIsRefused:
    """ga1 N1. `args.add or args.retire` treated an empty `--add` as absent, so
    a write that never happened reported rc 0 and rendered the view -- absence
    presented as evidence, on a verb whose file is append-only forever."""

    @pytest.mark.parametrize("flag", ["--add", "--retire"])
    @pytest.mark.parametrize("value", ["", "   "])
    def test_both_writers_refuse_an_empty_value(
            self, flag, value, sandboxed_list, monkeypatch, capsys):
        rc = _run(["homes", flag, value], monkeypatch)
        assert rc == 1
        assert "empty value" in capsys.readouterr().err
        assert not sandboxed_list.exists(), "an empty argument appended a record"

    def test_the_view_still_renders_when_neither_flag_is_given(
            self, sandboxed_list, monkeypatch, capsys):
        assert _run(["homes"], monkeypatch) == 0
        assert "fleet homes:" in capsys.readouterr().out

    def test_the_real_list_is_untouched(self):
        """§7's real-list-untouched pin, restated for this file: every test
        above writes through `sandboxed_list`."""
        before = REAL_LIST.exists()
        fleet.read_homes_list()
        assert REAL_LIST.exists() == before
