"""The two round-7 defect pins the operator made CONDITIONS of the multi-fleet
ratification (`docs/OPERATOR-GATES.md`, 2026-07-30):

    "build slices 0/a-e with the round-7 defect pins (the silently-dropped
     `['--fleet-home','H','autoclean']` flag; `doctor --repair` absent from
     every destructive enumeration) as slice conditions"

BOTH CLAIMS WERE RE-MEASURED BEFORE BEING PINNED, AND BOTH NEEDED CORRECTING.
The corrections are the reason this file exists in the shape it does; read them
before trusting either name.

--- B1: the flag is NOT silently dropped today. It is a usage error. ----------

`docs/specs/multi-fleet.md` §5 calls this a "Shipped-defect slice condition
(rb7 C-2, measured both interpreters)" and says `['--fleet-home','H',
'autoclean'] -> None` **today**. Driven against `build_parser()` at `09995f9`:

    py -3.13 / py -3.10, both identical:
      ['--fleet-home', 'H', 'autoclean'] -> SystemExit(2)
          "fleet: error: argument command: invalid choice: 'H'"
      ['autoclean', '--fleet-home', 'H'] -> fleet_home='H'

There is no global `--fleet-home`: `autoclean` is the ONLY one of the 32
subparsers that defines it (census in `test_autoclean_is_the_only_verb_
defining_the_flag`), and the top-level parser defines no options at all beyond
`-h/--help`. A flag argparse never heard of cannot be clobbered by a namespace
copy -- argparse refuses the whole invocation instead.

So the defect is **LATENT, not shipped**: it is created by the act of promoting
`--fleet-home` to a global flag (Sequencing slice (a)) while `autoclean` keeps
its own. The clobber itself is real and is measured here on a synthetic parser
rather than asserted, because that measurement is the entire justification for
the lint below.

WHY A LINT AND NOT A FIX. There is nothing to fix in slice 0 -- manufacturing
the defect in order to fix it would be worse than the defect. What slice 0 owes
the ratification is that slice (a) **cannot land the clobbering shape silently**,
which is what `test_no_subparser_redefines_a_top_level_dest` does. The spec's own
remedy sentence ("share one parser object or reconcile the two dests explicitly")
is exactly what that lint enforces, one slice early.

AND THE CHOICE THE BRIEF ASKED FOR, MADE DELIBERATELY: given a global flag and a
verb-local one, the fix is to **reconcile the dests, never to let the global
value survive by luck of position**. §5's resolution order makes `--fleet-home`
step 1, "applied in `main()` before dispatch" -- a value that depends on which
side of the verb the operator typed it cannot be step 1 of a resolution order.
The lint therefore bans the collision outright rather than pinning one winning
position, because a silently-ignored home selector is how a destructive verb
runs in the wrong fleet, and "worse than one that errors" is a floor, not the
target.

--- B2: `doctor --repair` is absent from ONE enumeration, not from every one ---

Census taken 2026-07-31 over the whole repo (`grep -rn 'doctor --repair'`, then
every list-shaped verb enumeration). It is ALREADY PRESENT in:

  * `docs/specs/multi-fleet.md` §5 verb-effect table -- destructive row, cited
    to rb7 C-3. The ratified spec is not missing it.
  * `tests/test_view_quarantine.py::test_no_read_only_grant_pre_approves_the_
    repair_flag` (+ its seed) -- enumerates the flag against all five read-only
    commands via the measured `allowed-tools` matcher.
  * `tests/test_view_quarantine.py::test_no_read_only_command_inline_execs_
    repair` (+ its seed) -- the inline-exec mechanism.

It is genuinely ABSENT from `tests/test_terminal_surface.py::TestCommandFiles.
DESTRUCTIVE_VERBS`, which `docs/reviews/ULTRAREVIEW-2026-07-30.md` P1-3 named
and which was not closed when the two `test_view_quarantine` guards landed. That
one gap is real and is closed in the same commit as this file.

AND THE MISS-THE-NEXT-SITE CHECK, run because this project's named recurring
defect is an inherited enumeration smaller than reality: `DESTRUCTIVE_VERBS` was
missing FOUR of the ratified destructive class, not one -- `archive`,
`autoclean`, `doctor --repair` and `sup-handoff-abort`. Fixing only the reported
site would have reproduced the miss three times over. That is what
`test_every_ratified_destructive_verb_reaches_the_read_only_grant_lint` measures,
and it is the assertion that went RED before the fix.

TWO ENUMERATIONS ARE DELIBERATELY NOT EDITED, and this is a finding, not an
oversight:

  * `tests/test_supervisor_gate.py::GATED_VERBS` / `fleet.GATE_VERBS_ACCEPTING_
    NONCE` are the claim-nonce §7 mutating-lifecycle taxonomy. Adding `doctor`
    there would arm the supervisor gate on a diagnostic verb and require it to
    declare `--nonce` -- a live behaviour change to a RATIFIED section that the
    2026-07-30 ruling does not mention. A builder does not ratify that.
  * `tests/test_terminal_surface.py::MUTATING_COMMANDS` enumerates `commands/
    *.md` FILES, and `doctor.md` is a read-only slash command that cannot reach
    `--repair` (pinned above). Moving it would break
    `test_every_expected_command_exists` and would be false besides.
"""
import argparse
import importlib.util
import re
from pathlib import Path

import pytest

import fleet

REPO = Path(__file__).resolve().parents[1]


def _sibling(name):
    """Import a sibling test module by path, so this pin does not depend on
    pytest's sys.path insertion order or on collection order."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _subparsers_action(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("build_parser() has no subparsers action")


def _verbs():
    return dict(_subparsers_action(fleet.build_parser()).choices)


def _option_strings(parser):
    out = set()
    for action in parser._actions:
        out.update(action.option_strings)
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                out.update(_option_strings(child))
    return out


def _dests(parser):
    out = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                out |= _dests(child)
        out.add(action.dest)
    out.discard("help")
    return out


# ---------------------------------------------------------------------------
# B1 -- the global-position flag
# ---------------------------------------------------------------------------

class TestGlobalPositionFleetHome:
    def test_autoclean_is_the_only_verb_defining_the_flag(self):
        """The census the brief asked for, DERIVED rather than listed: fixing
        only the site that was reported is how this project reproduces a miss at
        the next site, so the population is measured every run."""
        defining = sorted(verb for verb, sp in _verbs().items()
                          if "--fleet-home" in _option_strings(sp))
        assert defining == ["autoclean"], (
            f"verbs defining --fleet-home: {defining}. If this grew, the global "
            f"flag was promoted (slice (a)) or a second verb-local copy landed; "
            f"either way re-read the collision lint below before proceeding.")

    def test_the_top_level_parser_defines_no_fleet_home_flag_today(self):
        """The load-bearing half of the correction. `--fleet-home` is verb-local,
        so there is no global value for a subparser namespace to clobber."""
        top = fleet.build_parser()
        top_opts = {o for a in top._actions
                    if not isinstance(a, argparse._SubParsersAction)
                    for o in a.option_strings}
        assert "--fleet-home" not in top_opts

    @pytest.mark.parametrize("argv,expected", [
        (["--fleet-home", "H", "autoclean"], "usage-error"),
        (["autoclean", "--fleet-home", "H"], "H"),
    ])
    def test_shipped_behaviour_of_both_positions(self, argv, expected, capsys):
        """What shipped code ACTUALLY does with both spellings, on this
        interpreter. The global position is refused (exit 2), not silently
        dropped -- which is the correction to the spec's `-> None today`.

        This is the pin that flips the day slice (a) promotes the flag without
        reconciling the dests: `--fleet-home H autoclean` would start PARSING,
        and yield None."""
        parser = fleet.build_parser()
        if expected == "usage-error":
            with pytest.raises(SystemExit) as exc:
                parser.parse_args(argv)
            assert exc.value.code == 2
            assert "invalid choice: 'H'" in capsys.readouterr().err
        else:
            assert parser.parse_args(argv).fleet_home == expected

    def test_the_clobber_is_real_on_this_interpreter(self):
        """MEASURED, not inherited. rb7 C-2's mechanism, reproduced on a
        synthetic parser: once a global and a subparser share a dest, argparse's
        namespace copy writes the subparser's default over the already-parsed
        global value -- and only for the verb that re-defines it.

        Both floors agree; this test is what proves that, since it runs on both.
        Without this, the lint below is a rule with no measured reason."""
        p = argparse.ArgumentParser(prog="fleet")
        p.add_argument("--fleet-home", dest="fleet_home", default=None)
        sub = p.add_subparsers(dest="command", required=True)
        redefines = sub.add_parser("autoclean")
        redefines.add_argument("--fleet-home", dest="fleet_home", default=None)
        sub.add_parser("clean")

        assert p.parse_args(["--fleet-home", "H", "autoclean"]).fleet_home is None, (
            "argparse no longer clobbers a global dest from a subparser default "
            "-- the lint below may be obsolete; re-derive it before deleting it")
        assert p.parse_args(["--fleet-home", "H", "clean"]).fleet_home == "H"
        assert p.parse_args(["autoclean", "--fleet-home", "H"]).fleet_home == "H"

    def test_no_subparser_redefines_a_top_level_dest(self):
        """THE PIN. A dest owned by the top-level parser and re-defined by any
        verb is silently position-dependent, and §5 step 1 requires
        `--fleet-home` to be resolved in `main()` before dispatch -- a value that
        depends on which side of the verb it was typed cannot be step 1.

        IT USED TO BE A NEGATIVE OVER AN EMPTY SET, and slice a1 fixed that
        without shipping a2's flag. The top-level parser declares no OPTIONS, so
        the set this iterated was literally empty and the assertion could not
        fail for any parser whatsoever. But the top level does own one dest --
        `command`, the subparsers action's own -- and it was being excluded by
        the very `isinstance` filter that skips the subparsers ACTION. The
        collision it hides is real and measured on both floors
        (`test_the_command_dest_clobber_is_real_on_this_interpreter`): a verb
        that defines `dest="command"` overwrites the verb NAME with its own
        default, `main()`'s dispatch chain sees `args.command is None`, and the
        verb becomes unreachable through its own flag.

        So the set is non-empty TODAY, over all shipped verbs, and it grows
        again the moment a2 promotes `--fleet-home`. Both readings of the
        round-7 condition are served by one assertion."""
        top = fleet.build_parser()
        top_dests = {a.dest for a in top._actions
                     if not isinstance(a, argparse._SubParsersAction)} - {"help"}
        top_dests |= {a.dest for a in top._actions
                      if isinstance(a, argparse._SubParsersAction)} - {"help"}
        assert top_dests, (
            "the top-level parser owns no dests at all, so this assertion is "
            "vacuous -- the subparsers action's own dest should be in here")
        offenders = {verb: sorted(_dests(sp) & top_dests)
                     for verb, sp in _verbs().items() if _dests(sp) & top_dests}
        assert not offenders, (
            f"these verbs re-define a global dest and will silently clobber it "
            f"in global position: {offenders}. Share one parser object or "
            f"reconcile the dests explicitly (multi-fleet.md §5); do NOT pin a "
            f"winning position -- a home selector that depends on argv order is "
            f"how a destructive verb runs in the wrong fleet.")

    def test_the_command_dest_clobber_is_real_on_this_interpreter(self):
        """MEASURED, not asserted -- the reason `command` belongs in the set
        above. The subparsers action sets the verb name on the namespace FIRST
        and the subparser's namespace copy runs SECOND, so a verb that owns the
        same dest overwrites the verb name with its own default.

        Both floors agree; this test is what proves that, since it runs on both.
        The consequence in this CLI specifically: `main()` dispatches on
        `args.command`, so the verb would fall through every arm and exit 2 with
        *"unknown command None"* -- a subcommand made unreachable by one of its
        own flags."""
        p = argparse.ArgumentParser(prog="fleet")
        sub = p.add_subparsers(dest="command", required=True)
        collides = sub.add_parser("go")
        collides.add_argument("--command", dest="command", default=None)
        sub.add_parser("clean")

        assert p.parse_args(["go"]).command is None, (
            "argparse no longer lets a subparser clobber the subparsers "
            "action's own dest -- re-derive the lint above before trusting it")
        assert p.parse_args(["clean"]).command == "clean"

    def test_the_seed_the_detector_can_see_a_command_dest_collision(self, monkeypatch):
        """THE SECOND SEED, for the half of the detector that is live TODAY.
        `test_the_seed_the_collision_detector_can_see_a_collision` plants a
        global `--fleet-home` -- i.e. it seeds the a2 shape. This one plants the
        shape a1 can already reach: a shipped verb growing a `--command` flag.

        Both seeds matter, because they exercise different halves of the derived
        set and either half can rot to empty on its own."""
        real = fleet.build_parser

        def planted():
            p = real()
            _subparsers_action(p).choices["status"].add_argument(
                "--command", dest="command", default=None)
            return p

        monkeypatch.setattr(fleet, "build_parser", planted)
        with pytest.raises(AssertionError, match="status"):
            TestGlobalPositionFleetHome().test_no_subparser_redefines_a_top_level_dest()

    def test_the_seed_the_collision_detector_can_see_a_collision(self, monkeypatch):
        """The lint above is a negative over a derived set -- the shape that
        passes vacuously when the derivation rots. Plant the exact shape slice
        (a) is about to build and prove the detector still says yes."""
        real = fleet.build_parser

        def planted():
            p = real()
            p.add_argument("--fleet-home", dest="fleet_home", default=None)
            return p

        monkeypatch.setattr(fleet, "build_parser", planted)
        with pytest.raises(AssertionError, match="autoclean"):
            TestGlobalPositionFleetHome().test_no_subparser_redefines_a_top_level_dest()


# ---------------------------------------------------------------------------
# B2 -- the destructive enumerations
# ---------------------------------------------------------------------------

SPEC = REPO / "docs" / "specs" / "multi-fleet.md"

# Transcribed from the RATIFIED §5 verb-effect table. Keys are the table's own
# tokens, flag included where the table carries one -- `doctor` is ordinary and
# `doctor --repair` is destructive, and a verb-only key cannot say that.
#
# THE 2026-08-05 §5-CRITERION RULING IS LANDED HERE, IN THE SAME COMMIT AS THE
# SPEC EDIT IT TRANSCRIBES. `TestRatifiedTableIsTranscribedFaithfully` re-reads
# the spec's `| **destructive** |` row, so moving this tuple without the spec --
# or the spec without this tuple -- goes RED in one direction or the other. That
# coupling is the reason `w42/mf5-verbs` was RED at its own tip: it edited the
# row and not this file, and disclosed that rather than routing around it.
#
# Where the seventeen names went (all four sub-rulings AS RECOMMENDED,
# `docs/OPERATOR-GATES.md` first settled entry):
#   * eleven by `w42/mf5`'s own derivations, landing under its gate;
#   * `wait` -> ORDINARY by B3, which also wrote the ground that separates it
#     from `release` into §5 (their effect-site sets are byte-identical, so
#     set-equality selected ordinary AND disruptive at once and could not pick);
#   * `sup-spawn` -> DESTRUCTIVE by E1 (the dispatch is the act). ITS ENTRY IN
#     THE LINT BELOW IS HAND-MAINTAINED AND CANNOT BE DERIVED -- no static walk
#     over `bin/fleet.py` sees what a dispatched body will do. Ruled as an
#     accepted cost; if you are pruning this file, that is the entry with no
#     mechanical backstop.
#   * `sup-checkpoint`, `sup-release` -> DESTRUCTIVE by E2 (an irreversible
#     append is an irreversible effect), E3 collapsing into it.
RATIFIED_DESTRUCTIVE = ("clean", "archive", "autoclean",
                        "doctor --repair", "sup-handoff-abort",
                        # [w42/mf5], landed under the same ruling
                        "sup-boot", "sup-handoff-begin", "sup-handoff-complete",
                        "sup-decision --clear",
                        # [w43/s5] E1, then E2/E3
                        "sup-spawn", "sup-checkpoint", "sup-release")
RATIFIED_DISRUPTIVE = ("kill", "interrupt", "send", "respawn", "release",
                       "resume-limited", "sup-heartbeat")
RATIFIED_ORDINARY = ("spawn", "init", "status", "peek", "result", "homes",
                     "home", "knowledge", "attach", "wait", "sup-status",
                     "sup-context", "q", "index")

# Named by the ratified table but NOT YET BUILT. Kept separate so the "the table
# cites no dead verb" pin cannot be satisfied by an unbuilt name.
#
# `homes` LIVED HERE UNTIL SLICE a1 BUILT IT (2026-08-05) and moved, in the same
# commit as the verb, to `RATIFIED_ORDINARY` -- §5's table classifies
# `homes --add/--retire` as *"ordinary (list-reversible)"*, and that row is the
# authority for where it goes, not this file.
#
# WHAT ACTUALLY CAUGHT THE STALENESS, measured before the move rather than
# assumed: with `homes` shipped and this tuple untouched,
# `test_every_shipped_verb_is_classified_or_declared_unclassified` went RED --
# *"these verbs have no effect disposition: ['homes']"*. The pin that reads like
# it should have caught it, `test_the_ratified_table_cites_no_verb_that_does_not_
# exist`, did NOT and structurally cannot: it computes
# `cited - set(_verbs()) - set(RATIFIED_BUT_UNBUILT)`, so every entry in this
# tuple is subtracted straight back out and the tuple is invisible to it in both
# directions. That is worth knowing before anyone leans on it for the next
# unbuilt verb -- `TestRatifiedButUnbuiltIsWatchedBySomething` below pins which
# assertion is actually load-bearing here.
RATIFIED_BUT_UNBUILT = ()

# Verbs `build_parser()` ships that the RATIFIED table classifies nowhere.
#
# THIS IS A FINDING, DELIBERATELY NOT A CLASSIFICATION. It held seventeen names
# because the spec's own closing paragraph says the table "rows are drafted
# against wave-26-era shipped verbs", and assigning a tier is a spec edit on a
# ratified section -- the operator's, not a builder's. So they were recorded here
# rather than guessed at, and that is exactly how they came to be ruled: the
# 2026-08-05 §5-criterion gate is the escalation this tuple existed to force.
#
# IT IS EMPTY NOW, AND EMPTY IS A REAL STATE, NOT A ROTTED ONE. All seventeen
# were classified by `w42/mf5` plus the four sub-rulings; the census closes
# exactly (measured at the landing tree: 33 shipped verbs, and 12 destructive +
# 7 disruptive + 14 ordinary first-tokens = 33, no verb in two rows).
#
# The pin's value is the SHAPE, not the contents: a verb added tomorrow is in
# neither the table nor this list, so it goes RED until someone dispositions it.
# That is the "cannot pass silently" the ratification asked for, and with this
# tuple empty `test_every_shipped_verb_is_classified_or_declared_unclassified`
# is now the ONLY thing standing between a new verb and a silent landing --
# there is no longer a second place a name could be parked. Its seed
# (`test_the_seed_a_new_verb_with_no_disposition_is_caught`) is what proves it
# still fires; do not delete that seed to save a test.
UNCLASSIFIED_BY_THE_RATIFIED_TABLE = ()


def _classified_verbs():
    tokens = RATIFIED_DESTRUCTIVE + RATIFIED_DISRUPTIVE + RATIFIED_ORDINARY
    return {t.split()[0] for t in tokens}


class TestRatifiedTableIsTranscribedFaithfully:
    """The constants above are a hand copy of a ratified table, which is the
    shape that rots when the table is edited. These re-read the spec."""

    @pytest.mark.parametrize("token", RATIFIED_DESTRUCTIVE)
    def test_the_spec_still_lists_each_destructive_token(self, token):
        row = [ln for ln in SPEC.read_text(encoding="utf-8").splitlines()
               if ln.startswith("| **destructive**")]
        assert len(row) == 1, "§5's destructive row is not where this pin looks"
        assert f"`{token}`" in row[0], (
            f"`{token}` is no longer in §5's destructive row -- re-transcribe "
            f"RATIFIED_DESTRUCTIVE from the spec rather than editing this list")

    def test_the_spec_row_names_no_destructive_verb_this_list_omits(self):
        row = next(ln for ln in SPEC.read_text(encoding="utf-8").splitlines()
                   if ln.startswith("| **destructive**"))
        # Backticked tokens in the row that name a fleet verb, i.e. resolve to a
        # shipped subcommand. Prose spans (`claude rm`, `state/`) do not.
        verbs = set(_verbs())
        named = {t for t in re.findall(r"`([^`]+)`", row) if t.split()[0] in verbs}
        assert named == set(RATIFIED_DESTRUCTIVE), (
            f"§5's destructive row names {sorted(named)}; this file transcribes "
            f"{sorted(RATIFIED_DESTRUCTIVE)}. The row moved -- re-transcribe.")


class TestEveryShippedVerbHasAnEffectDisposition:
    def test_no_verb_is_both_classified_and_declared_unclassified(self):
        overlap = _classified_verbs() & set(UNCLASSIFIED_BY_THE_RATIFIED_TABLE)
        assert not overlap, f"declared unclassified but the table names it: {sorted(overlap)}"

    def test_the_ratified_table_cites_no_verb_that_does_not_exist(self):
        cited = _classified_verbs() | set(RATIFIED_BUT_UNBUILT)
        missing = sorted(cited - set(_verbs()) - set(RATIFIED_BUT_UNBUILT))
        assert not missing, (
            f"§5's verb-effect table classifies verbs `build_parser()` does not "
            f"ship: {missing}")

    def test_every_shipped_verb_is_classified_or_declared_unclassified(self):
        """A new verb lands with no effect tier and this goes RED. That is the
        whole pin: the 2026-07-30 ratification asked that a verb added without an
        effect classification cannot pass silently, and until now nothing in the
        repo enumerated verbs by effect at all."""
        undisposed = sorted(set(_verbs())
                            - _classified_verbs()
                            - set(UNCLASSIFIED_BY_THE_RATIFIED_TABLE))
        assert not undisposed, (
            f"these verbs have no effect disposition: {undisposed}. Classify "
            f"them in `docs/specs/multi-fleet.md` §5's verb-effect table (an "
            f"operator-owned edit to a ratified section) or record them in "
            f"UNCLASSIFIED_BY_THE_RATIFIED_TABLE with the reason. Do not guess "
            f"a tier: a wrong `ordinary` is a destructive verb running unguarded "
            f"in a foreign home.")

    def test_the_seed_a_new_verb_with_no_disposition_is_caught(self, monkeypatch):
        """The assertion above is a negative over a derived set. Plant a new
        subparser -- exactly what a future feature does -- and prove it fires."""
        real = fleet.build_parser

        def planted():
            p = real()
            _subparsers_action(p).add_parser("obliterate")
            return p

        monkeypatch.setattr(fleet, "build_parser", planted)
        with pytest.raises(AssertionError, match="obliterate"):
            TestEveryShippedVerbHasAnEffectDisposition() \
                .test_every_shipped_verb_is_classified_or_declared_unclassified()


class TestRatifiedButUnbuiltIsWatchedBySomething:
    """WHICH ASSERTION ACTUALLY GUARDS `RATIFIED_BUT_UNBUILT`, measured when
    slice a1 emptied it.

    The tuple's own comment said it was kept separate *"so the 'the table cites
    no dead verb' pin cannot be satisfied by an unbuilt name"* -- and that pin
    subtracts the tuple back out of its own comparison, so it is blind to the
    tuple in both directions. When `homes` shipped with the tuple untouched, the
    assertion that went RED was `test_every_shipped_verb_is_classified_or_
    declared_unclassified`. This records that, so the next unbuilt verb is
    entered here knowing what will and will not notice it going stale."""

    def test_a_stale_unbuilt_entry_is_caught_by_the_disposition_pin(self, monkeypatch):
        """Plant the exact state a1 was in before its coupled edit: a verb that
        SHIPS while still being listed as unbuilt and classified nowhere."""
        real = fleet.build_parser

        def planted():
            p = real()
            _subparsers_action(p).add_parser("adopt")
            return p

        monkeypatch.setattr(fleet, "build_parser", planted)
        monkeypatch.setattr(__import__(__name__), "RATIFIED_BUT_UNBUILT", ("adopt",))
        with pytest.raises(AssertionError, match="adopt"):
            TestEveryShippedVerbHasAnEffectDisposition() \
                .test_every_shipped_verb_is_classified_or_declared_unclassified()

    def test_the_dead_verb_pin_is_blind_to_the_tuple_in_both_directions(self):
        """The finding, as an executable statement rather than a comment. If
        someone strengthens `test_the_ratified_table_cites_no_verb_that_does_
        not_exist` so that it DOES see the tuple, this goes RED and the comment
        above it has to be rewritten with it."""
        import test_round7_defect_pins as me
        src = Path(__file__).read_text(encoding="utf-8")
        body = src.split("def test_the_ratified_table_cites_no_verb_that_does_not_exist")[1]
        body = body.split("\n    def ")[0]
        assert "- set(RATIFIED_BUT_UNBUILT)" in body and "| set(RATIFIED_BUT_UNBUILT)" in body, (
            "the dead-verb pin no longer both adds and subtracts "
            "RATIFIED_BUT_UNBUILT -- it may now be load-bearing for that tuple, "
            "so re-read the comment on the tuple before trusting this file")
        assert me.RATIFIED_BUT_UNBUILT == ()


class TestDestructiveEnumerationsCarryTheRatifiedClass:
    """THE ASSERTION THAT WENT RED. `DESTRUCTIVE_VERBS` is the repo's one live
    verb-level destructive enumeration -- the guard that keeps a read-only
    `/fleet:*` grant from reaching a destructive subcommand, born of the
    2026-07-09 kill/clean data loss. Four of the five ratified destructive
    tokens were missing from it, `doctor --repair` among them."""

    def test_every_ratified_destructive_verb_reaches_the_read_only_grant_lint(self):
        listed = set(_sibling("test_terminal_surface").TestCommandFiles.DESTRUCTIVE_VERBS)
        missing = sorted(set(RATIFIED_DESTRUCTIVE) - listed)
        assert not missing, (
            f"`tests/test_terminal_surface.py::TestCommandFiles.DESTRUCTIVE_VERBS` "
            f"omits ratified destructive verbs {missing}, so a read-only "
            f"/fleet:* command could be granted them without the lint noticing.")

    def test_the_repair_flag_is_carried_as_the_flagged_spelling(self):
        """Not bare `doctor`. The lint asserts `f"fleet {verb}" not in grant`,
        and `commands/doctor.md` legitimately grants `Bash(fleet doctor)` -- the
        read-only invocation its own body inlines. A bare `doctor` entry would
        fail that file for doing the right thing; the destructive capability is
        the FLAG."""
        listed = set(_sibling("test_terminal_surface").TestCommandFiles.DESTRUCTIVE_VERBS)
        assert "doctor --repair" in listed
        assert "doctor" not in listed
