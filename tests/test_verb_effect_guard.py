"""§5's verb-effect table, the arming rule, and the wrong-home guard
(multi-fleet slice a3: `docs/specs/multi-fleet.md` §5's table + Arming
paragraph + §7's two pins; `docs/mf-slice-a-price.md` §a3).

WHAT a3 OWES, AND WHERE THE SEAM WITH a2 IS. a2 built §5's five-step ORDER and
the two refusals the steps themselves specify (the terminus, and the
flag/lookup disagreement). a3 builds the tier that sits on top of a resolved
home: *"when armed, destructive via env/legacy requires the flag; disruptive
via env/legacy proceeds but renders its resolution provenance in output;
ordinary flows. Lookup-hit resolutions are exempt from both."* Those two
sentences are the whole feature, and every test below drives one clause of
them.

THE ARMING QUESTION IS NOT a2's TERMINUS GATE, and conflating them is the
mistake this file exists to make impossible. `_multi_fleet_population_is_live`
answers *"is this machine in multi-fleet territory at all?"* -- a yes/no that
gates whether the terminus refuses. `multi_fleet_arming` answers §5's stricter
question: *">=2 distinct homes counting valid AND unreadable, and any
indeterminate population state arms"*. A machine can be "live" (one listed
home) without being armed (one home is not two).

THE NAME IS DELIBERATE AND IS ITSELF PINNED (`docs/mf-slice-a-price.md`
Risk 4). This module's 19.7k-line neighbour already ships a claim-nonce
"armed" concept -- the supervisor claim gate (`tests/test_gate_arm_wedge.py`,
`tests/test_supervisor_gate.py`) -- and a bare `armed`/`_is_armed` in
`bin/fleet.py` would put two unrelated meanings of the word one grep apart.
`TestTheArmingSymbolsCannotBeConfusedWithTheClaimGate` is the enforceable form
of that risk note.

FAIL-SAFE DIRECTION, STATED ONCE. Every unknown in this file resolves toward
GUARDING: an unclassified verb is treated destructive, a home whose registry
cannot be read counts toward the population, and a homes list carrying a record
nobody can parse arms. §5 says it in one clause -- *"indeterminacy never
selects the permissive branch"* -- and the round-6 arming-fails-open family is
what it was written against.

ISOLATION: `homes_list_path` is redirected per test (conftest's autouse home
sandbox enumerates three helpers by name and this is not one of them), and
`INSTALL_ROOT` is already redirected to an empty fixture install by conftest --
which is exactly the *"legacy home that is not initialized"* shape §5 step 2's
population term needs, and the reason two listed homes make a population of
three whose counted size is two.
"""
import ast
import json
import re
from pathlib import Path

import pytest

import fleet

SRC = Path(fleet.__file__).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


@pytest.fixture
def home(tmp_path):
    """An INITIALIZED home: `state/fleet.json` exists and parses."""
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


def _run(argv, monkeypatch, sid=None):
    monkeypatch.delenv("FLEET_HOME", raising=False)
    if sid is None:
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)
    return fleet.main(argv)


def _reached(monkeypatch, verb):
    """Replace one `cmd_*` with a sentinel and return the call log.

    The §7 destructive-tier pin's own words are *"env-resolved `spawn`
    proceeds"* -- PROCEEDS, i.e. reaches dispatch. Asserting a return code
    would let a verb that refused for its own unrelated reason read as a pass,
    so what is pinned is that `main()` handed control to the verb."""
    log = []
    name = "cmd_" + verb.replace("-", "_")
    monkeypatch.setattr(fleet, name, lambda args: log.append(verb) or 0)
    return log


# ---------------------------------------------------------------------------
# The table itself -- transcription, totality, and the two granularities
# ---------------------------------------------------------------------------

class TestTheVerbEffectTableIsTheRatifiedOne:
    """The three tuples in `bin/fleet.py` are a hand copy of a ratified table,
    which is the shape that rots when the table is edited. The spec-facing
    transcription pin lives in `tests/test_round7_defect_pins.py`; what is
    pinned HERE is that production's copy and that file's copy are the same
    copy, so the guard cannot tier a verb differently from the enumeration the
    read-only-grant lint keys on."""

    def test_production_and_the_pin_file_transcribe_the_same_table(self):
        pins = _sibling_pins()
        assert fleet.VERB_EFFECT_DESTRUCTIVE == pins.RATIFIED_DESTRUCTIVE
        assert fleet.VERB_EFFECT_DISRUPTIVE == pins.RATIFIED_DISRUPTIVE
        assert fleet.VERB_EFFECT_ORDINARY == pins.RATIFIED_ORDINARY

    def test_every_shipped_verb_gets_a_tier(self):
        """Totality, driven over `build_parser()` rather than over the tuples:
        a verb landing tomorrow must come out of `verb_effect_tier` with a word,
        not a `KeyError` inside `main()`."""
        for verb in _shipped_verbs():
            assert fleet.verb_effect_tier(verb) in (
                "destructive", "disruptive", "ordinary")

    def test_no_verb_is_in_two_rows(self):
        rows = [{t.split()[0] for t in tup} for tup in (
            fleet.VERB_EFFECT_DESTRUCTIVE, fleet.VERB_EFFECT_DISRUPTIVE,
            fleet.VERB_EFFECT_ORDINARY)]
        assert not (rows[0] & rows[1]) and not (rows[0] & rows[2]) \
            and not (rows[1] & rows[2])

    def test_an_unknown_verb_is_treated_destructive(self):
        """FAIL-SAFE. The pin file's own words: *"a wrong `ordinary` is a
        destructive verb running unguarded in a foreign home"*. A verb this
        table has never heard of is the same risk with less warning."""
        assert fleet.verb_effect_tier("obliterate") == "destructive"


class TestTheFlagGranularityTheTableActuallyStates:
    """FOUR of the fourteen destructive tokens carry a flag -- `doctor --repair`,
    `sup-decision --clear`, and `homes --add`/`homes --retire` since the
    2026-08-08 E2/homes ruling -- and one deliberately does not (`autoclean`,
    whose tier 2 husk sweep runs by default). The table is transcribed at the
    granularity it is written at, and the residual (the verb with none of its
    qualifying flags) is declared with its ground rather than guessed."""

    def test_doctor_repair_is_destructive_and_bare_doctor_is_not(self):
        assert fleet.verb_effect_tier("doctor", _ns(repair=True)) == "destructive"
        assert fleet.verb_effect_tier("doctor", _ns(repair=False)) == "ordinary"

    def test_sup_decision_clear_is_destructive_and_the_show_form_is_not(self):
        assert fleet.verb_effect_tier(
            "sup-decision", _ns(clear=True)) == "destructive"
        assert fleet.verb_effect_tier(
            "sup-decision", _ns(clear=False, question=None,
                                answer=None)) == "ordinary"

    @pytest.mark.parametrize("dest,value", [("question", "why?"),
                                            ("answer", "because")])
    def test_the_unruled_sup_decision_writers_fail_safe_destructive(
            self, dest, value):
        """§5's E3 sub-item, carried as an OPEN question by the ratified text
        itself: *"`sup-decision --raise`/`--answer` ... write foreign supervisor
        decision state and are also unclassified"*. Unclassified is not
        ordinary. a3 does not rule it -- it guards it and escalates."""
        flags = {"clear": False, "question": None, "answer": None, dest: value}
        assert fleet.verb_effect_tier(
            "sup-decision", _ns(**flags)) == "destructive"

    def test_autoclean_is_destructive_with_no_flag_at_all(self):
        """Not `autoclean --something`. The ratified token is bare, because
        tier 2's husk sweep (`claude rm`) runs on a plain `fleet autoclean`."""
        assert fleet.verb_effect_tier("autoclean", _ns()) == "destructive"

    def test_the_homes_writes_are_destructive_and_the_bare_read_is_not(self):
        """The operator's 2026-08-08 E2/homes ruling, as behaviour.

        *"Split the verb. Reading `fleet homes` stays ORDINARY; `--add`/
        `--retire` become DESTRUCTIVE."* Both grounds are in
        `docs/OPERATOR-GATES.md`: `--add` irreversibly appends to the
        machine-global `~/.claude/fleet-homes.list` (only the FOLD reverses it,
        which is the ratified E2 ground), and ORDINARY meant a read-only
        `/fleet:*` grant of `Bash(fleet homes)` reached `--add`.

        Driven through the REAL parser, not a hand-built namespace: the whole
        mechanism is that argparse's default dests (`add`, `retire`) are what
        the table's mechanical `--x-y` -> `x_y` rule produces, so a namespace
        this test invented could agree with the table while the CLI did not."""
        parser = fleet.build_parser()

        def tier(argv):
            args = parser.parse_args(argv)
            return fleet.verb_effect_tier(args.command, args)

        assert tier(["homes"]) == "ordinary"
        assert tier(["homes", "--add", "C:/some/home"]) == "destructive"
        assert tier(["homes", "--retire", "C:/some/home"]) == "destructive"

    def test_the_homes_read_is_ordinary_BY_RESIDUAL_not_by_a_second_row(self):
        """HOW the split is expressed, pinned separately from THAT it holds.

        The tempting shape -- bare `homes` left in `VERB_EFFECT_ORDINARY` while
        the flagged tokens join `VERB_EFFECT_DESTRUCTIVE` -- produces the same
        three answers above and is still wrong twice over: it puts one verb in
        two rows (`test_no_verb_is_in_two_rows`, and its spec-side twin
        `test_no_verb_IS_NAMED_BY_TWO_spec_rows`, both forbid it), and it
        degrades fail-OPEN, because dropping the flagged tokens would send the
        writes back to ORDINARY -- the exact hole the ruling closed. In the
        residual shape the same slip leaves `homes` in no tuple at all, and an
        unknown verb is destructive."""
        assert "homes" not in fleet.VERB_EFFECT_ORDINARY
        assert "homes" not in fleet.VERB_EFFECT_DISRUPTIVE
        assert fleet.VERB_EFFECT_RESIDUAL["homes"] == "ordinary"
        assert "homes --add" in fleet.VERB_EFFECT_DESTRUCTIVE
        assert "homes --retire" in fleet.VERB_EFFECT_DESTRUCTIVE
        # and the fail-safe direction, measured rather than argued
        assert fleet.verb_effect_tier("homes", _ns(add=None, retire=None)) == "ordinary"
        assert fleet.verb_effect_tier("nosuchverb", _ns()) == "destructive"

    def test_no_homes_entry_is_needed_in_the_residual_flags_escape_hatch(self):
        """`sup-decision --raise` needed `VERB_EFFECT_RESIDUAL_FLAGS` because
        argparse maps `--raise` to dest `question`, defeating the mechanical
        `--x-y` -> `x_y` rule. `--add`/`--retire` override no `dest=`, so they
        do not. Measured off `build_parser()` so the claim cannot rot."""
        homes = _subparser(fleet.build_parser(), "homes")
        dests = {tuple(a.option_strings): a.dest
                 for a in homes._actions if a.option_strings}
        assert dests[("--add",)] == "add"
        assert dests[("--retire",)] == "retire"
        assert "homes" not in fleet.VERB_EFFECT_RESIDUAL_FLAGS


class TestTheWorstMatchingTierWins:
    """ga3 A-1: *"the worst matching tier wins" is a safety claim nothing can
    exercise*. The gate planted `max` -> `min` in `verb_effect_tier` and the
    full suite came back BYTE-IDENTICAL to the clean floor.

    WHY NOTHING CAUGHT IT, and it is not that the rule is wrong: no shipped verb
    matches two tiers at once. All three flag-qualified verbs express *"bare
    read ordinary, flagged write destructive"* through `VERB_EFFECT_RESIDUAL`,
    which yields exactly ONE matched tier per invocation, and `max` of a
    one-element list is that element whichever comparator you use.

    So the rule is pinned on a CONSTRUCTED two-tier verb. That is not a weaker
    pin -- `max` is a property of the resolver, not of any particular verb, and
    a synthetic verb exercises the resolver exactly as a real one would. It also
    keeps the pin alive on a table whose whole design is to avoid two-tier
    verbs, which is the shape A-1 would otherwise leave permanently unguarded.

    The class is named in `verb_effect_tier`'s own docstring so the next reader
    of that `max` finds what stands behind it."""

    @staticmethod
    def _two_tier(monkeypatch, bare_tier, flagged_tier):
        """A verb that is `bare_tier` bare and `flagged_tier` under `--purge`."""
        tup = {"ordinary": "VERB_EFFECT_ORDINARY",
               "disruptive": "VERB_EFFECT_DISRUPTIVE",
               "destructive": "VERB_EFFECT_DESTRUCTIVE"}
        monkeypatch.setattr(fleet, tup[bare_tier],
                            getattr(fleet, tup[bare_tier]) + ("adopt",))
        monkeypatch.setattr(fleet, tup[flagged_tier],
                            getattr(fleet, tup[flagged_tier]) + ("adopt --purge",))

    def test_the_plant_really_creates_two_matching_tiers(self, monkeypatch):
        """Seed for the seed. If the construction stopped producing a two-tier
        match -- a renamed tuple, an index that de-duplicates by verb -- every
        assertion below would pass for the wrong reason, because `max` of one
        element equals `min` of it. This asserts the precondition itself."""
        self._two_tier(monkeypatch, "ordinary", "destructive")
        rows = fleet._verb_effect_index()["adopt"]
        assert (None, "ordinary") in rows and ("purge", "destructive") in rows
        args = _ns(purge=True)
        matched = [t for dest, t in rows
                   if dest is None or getattr(args, dest, None) not in (None, False)]
        assert sorted(matched) == ["destructive", "ordinary"], (
            "the plant no longer produces two matching tiers, so the pins below "
            "cannot distinguish max from min")

    @pytest.mark.parametrize("bare,flagged,worst", [
        ("ordinary", "destructive", "destructive"),
        ("ordinary", "disruptive", "disruptive"),
        ("disruptive", "destructive", "destructive"),
    ])
    def test_a_verb_matching_two_tiers_takes_the_worse(
            self, monkeypatch, bare, flagged, worst):
        """THE A-1 PIN. Each row reddens under `max` -> `min`.

        Three rows rather than one because `min` is not the only wrong
        comparator: a resolver that always returned `destructive` would satisfy
        row 1 while being just as broken, and row 2 catches it."""
        self._two_tier(monkeypatch, bare, flagged)
        assert fleet.verb_effect_tier("adopt", _ns(purge=True)) == worst

    @pytest.mark.parametrize("bare,flagged", [
        ("ordinary", "destructive"),
        ("ordinary", "disruptive"),
    ])
    def test_the_flag_being_absent_leaves_the_bare_tier(
            self, monkeypatch, bare, flagged):
        """The other direction, so `max` cannot be satisfied by a resolver that
        ignores the flag and always escalates. Only ONE tier matches here, so
        this row is deliberately green under both comparators -- it is bounding
        the pin above, not duplicating it."""
        self._two_tier(monkeypatch, bare, flagged)
        assert fleet.verb_effect_tier("adopt", _ns(purge=False)) == bare

    def test_the_shipped_table_still_cannot_exercise_this_rule(self):
        """A-1's FINDING, as an executable statement rather than a comment --
        this file's idiom for a fact a future change should have to notice.

        Every shipped verb matches at most one tier, which is why the pins above
        must construct their own. If this goes RED a real two-tier verb has
        landed: that is not a defect, but `max` has just become load-bearing on
        the real table, so re-read `verb_effect_tier` and move the named verb
        into the parametrisation above before deleting this."""
        multi = {}
        for verb in _shipped_verbs():
            rows = list(fleet._verb_effect_index().get(verb, ()))
            rows += list(fleet.VERB_EFFECT_RESIDUAL_FLAGS.get(verb, ()))
            # every flag the table keys on, all set at once -- the most
            # generous possible reading of "could two tiers match?"
            args = _ns(**{dest: True for dest, _ in rows if dest is not None})
            matched = {t for dest, t in rows
                       if dest is None or getattr(args, dest, None) not in (None, False)}
            if len(matched) > 1:
                multi[verb] = sorted(matched)
        assert not multi, (
            f"these shipped verbs now match two effect tiers at once: {multi}. "
            f"ga3 A-1 recorded that none did, which is why "
            f"TestTheWorstMatchingTierWins builds a synthetic verb. `max` in "
            f"`verb_effect_tier` is now load-bearing on the shipped table -- "
            f"pin the real verb here.")


# ---------------------------------------------------------------------------
# Arming -- §5's Arming paragraph, every direction
# ---------------------------------------------------------------------------

class TestArmingCountsHomes:
    """*"Armed when the population holds >=2 distinct homes counting valid AND
    unreadable."*"""

    def test_two_valid_homes_arm(self, home, sandboxed_list):
        _list(sandboxed_list, home("A"), home("B"))
        assert fleet.multi_fleet_arming()["armed"] is True

    def test_one_valid_home_does_not_arm(self, home, sandboxed_list):
        _list(sandboxed_list, home("A"))
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is False
        assert arming["reason"] == "population_below_two"

    def test_no_list_at_all_does_not_arm(self, home, monkeypatch):
        """§5: *"With a determinate population of <2: byte-identical to
        today."* This is every machine that exists right now."""
        assert fleet.multi_fleet_arming()["armed"] is False

    def test_an_unreadable_home_counts(self, home, sandboxed_list, monkeypatch):
        """*"counting valid AND unreadable"*. The home whose roster cannot be
        read is exactly the one that could be claiming this session."""
        a, u = home("A"), home("U")
        _list(sandboxed_list, a, u)
        real = fleet.read_registry_at
        monkeypatch.setattr(
            fleet, "read_registry_at",
            lambda h: (False, "unreadable", {"workers": {}})
            if fleet.home_identity(h) == fleet.home_identity(u) else real(h))
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is True
        assert fleet.home_identity(u) in arming["counted"]

    def test_a_quarantined_home_counts_with_the_unreadable_ones(
            self, home, sandboxed_list, monkeypatch):
        """a1 left this open in `homes_population`'s own docstring -- *"whether
        `quarantined` counts with `unreadable` (an incident happened) or with
        `not_initialized` (no roster is readable either way)"* -- for a3 to
        rule. RULED: with `unreadable`. The ground is the question arming asks,
        which is not *"can this home be used?"* but *"could this home be
        claiming my session?"*. A quarantined home HAD a roster, it was renamed
        aside after an incident, and nothing here can say what was in it. That
        is indeterminacy, and §5 sends indeterminacy to the armed branch."""
        a, q = home("A"), home("Q")
        _list(sandboxed_list, a, q)
        real = fleet.read_registry_at
        monkeypatch.setattr(
            fleet, "read_registry_at",
            lambda h: (False, "quarantined", {"workers": {}})
            if fleet.home_identity(h) == fleet.home_identity(q) else real(h))
        assert fleet.multi_fleet_arming()["armed"] is True

    def test_an_uninitialized_listed_home_does_not_count(
            self, home, bare, sandboxed_list):
        """ga2 A4, RULED and pinned in the direction the gate said was
        undocumented either way.

        A listed directory with no `state/fleet.json` is a FOURTH state -- §5's
        tri-state is hit/miss/unreadable and this is none of them -- and it does
        NOT count toward arming. Two grounds, neither of them "the spec's
        enumeration omits it":

          1. It is DETERMINATE. We read the home and got a complete answer:
             there is no roster. Arming's escape hatch is for what we could not
             find out, and we found this out.
          2. It cannot be the wrong home. `resolve_home` reaches steps 3/4 only
             through `home_is_initialized`, and a lookup cannot hit a home with
             no records -- so no resolution path can select it, and a verb
             cannot act destructively in a home it cannot be pointed at.

        It is still REPORTED (`skipped_not_initialized`), because an operator
        who listed a home that silently does nothing has to be able to see
        that."""
        a, u = home("A"), bare("U")
        _list(sandboxed_list, a, u)
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is False
        assert fleet.home_identity(u) in arming["skipped_not_initialized"]
        assert fleet.home_identity(u) not in arming["counted"]


class TestIndeterminacyAlwaysArms:
    """§7's **arming-indeterminacy pin**, and §5's *"an unreadable list, an
    unreadable home, or any indeterminate population state arms -- indeterminacy
    never selects the permissive branch."*"""

    def test_an_unreadable_list_arms(self, monkeypatch, sandboxed_list):
        sandboxed_list.write_text("x", encoding="utf-8")
        monkeypatch.setattr(fleet, "read_homes_list",
                            lambda: {"path": sandboxed_list, "ok": False,
                                     "reason": "unreadable", "members": [],
                                     "retired": [], "invalid_lines": 0,
                                     "decode_note": None})
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is True
        assert arming["indeterminate"] is True
        assert arming["reason"] == "list_unreadable"

    def test_a_list_that_is_a_directory_arms(self, tmp_path, monkeypatch):
        """The shape ga2 measured as already correct, pinned so it stays that
        way: a list path that is a directory is `ok: False, 'unreadable'`."""
        d = tmp_path / "as-a-dir"
        d.mkdir()
        monkeypatch.setattr(fleet, "homes_list_path", lambda: d)
        assert fleet.multi_fleet_arming()["armed"] is True

    def test_a_list_of_unparseable_records_arms(self, sandboxed_list):
        """ga2 A5, CLOSED. The gate measured `read_homes_list()` on
        `b"\\xff\\xfe\\x00bad\\x00\\x00"` returning
        `{'ok': True, 'members': [], 'invalid_lines': 1}` -- a list that is 100%
        unparseable classified as DETERMINATE-and-empty, which DISARMED the
        guard. `ok` answers *"could the bytes be read?"* and it answers it
        correctly; what it does not answer is *"how many homes does this file
        name?"*, and
        an invalid record is a home we may have failed to see.

        THE FIX IS IN THE ARMING RULE, NOT IN a1's CLASSIFIER. §4's *"Invalid
        lines never invalidate others"* is about the OTHER records staying
        valid, and it stays true: the classifier still reports every good line.
        What a3 adds is that an unparseable record makes the population COUNT
        indeterminate, and §5 sends that to the armed branch."""
        sandboxed_list.write_bytes(b"\xff\xfe\x00bad\x00\x00")
        read = fleet.read_homes_list()
        assert read["ok"] is True and read["members"] == [] \
            and read["invalid_lines"] == 1, "the a1 classifier moved"
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is True
        assert arming["indeterminate"] is True
        assert arming["reason"] == "list_has_unparseable_records"

    def test_one_bad_line_beside_one_good_one_still_arms(
            self, home, sandboxed_list):
        """The half that makes the rule bite: a single valid home would be a
        determinate population of one and would NOT arm, so the invalid line
        has to be what carries it over."""
        sandboxed_list.write_text(
            f"{fleet.home_identity(home('A'))}\nnot-an-absolute-path\n",
            encoding="utf-8")
        assert fleet.multi_fleet_arming()["armed"] is True

    def test_a_blank_line_is_not_an_unparseable_record(
            self, home, sandboxed_list):
        """`parse_homes_list_line` keeps "blank" and "invalid" apart on purpose
        -- *"a blank line is not a defect"*. Arming honours that split, or every
        trailing newline on every single-fleet machine arms the guard."""
        sandboxed_list.write_text(
            f"\n{fleet.home_identity(home('A'))}\n\n\n", encoding="utf-8")
        assert fleet.multi_fleet_arming()["armed"] is False


class TestArmingDoesNotReadHomesItDoesNotNeedTo:
    def test_the_machine_every_operator_has_today_reads_no_home(
            self, monkeypatch):
        """§5's *"<2: byte-identical to today"* is a COST claim as well as a
        behaviour claim -- `docs/mf-slice-a-price.md` Risk 3 is that §5.2 turns
        an O(1) surface into O(N-homes). A population that cannot REACH two
        cannot arm however each member reads, so it is answered without touching
        the disk.

        MEASURED, AND THE BOUNDARY IS NARROWER THAN IT FIRST LOOKS: the
        population is the folded list UNION the legacy install-root home, so a
        list naming ONE home already makes a population of two and does cost two
        reads. The zero-read case is the machine with no list at all, which is
        every machine that exists right now -- which is exactly the machine
        §5's byte-identical clause is about."""
        reads = []
        real = fleet.read_registry_at
        monkeypatch.setattr(fleet, "read_registry_at",
                            lambda h: reads.append(h) or real(h))
        assert fleet.multi_fleet_arming()["armed"] is False
        assert reads == []

    def test_one_listed_home_costs_its_own_read_and_still_does_not_arm(
            self, home, monkeypatch, sandboxed_list):
        """The other side of the boundary above, pinned so the cost is a
        measured number rather than an impression: population two (the listed
        home + the legacy term), two reads, counted one, not armed."""
        _list(sandboxed_list, home("A"))
        reads = []
        real = fleet.read_registry_at
        monkeypatch.setattr(fleet, "read_registry_at",
                            lambda h: reads.append(h) or real(h))
        arming = fleet.multi_fleet_arming()
        assert arming["armed"] is False
        assert len(reads) == 2 and len(arming["counted"]) == 1

    def test_the_lookup_itself_reads_each_home_exactly_once(
            self, home, sandboxed_list, monkeypatch):
        """FOUND BY a3's OWN MUTANT, not by the gate's. `A3-LOOKUP-READS-TWICE`
        adds a second `read_registry_at(ident)` inside `lookup_home_for_sid`'s
        loop and the whole targeted suite -- 296 tests -- stayed GREEN. §5.2's
        contract is *"per home, ONE lock-free snapshot"*, `docs/mf-slice-a-
        price.md` Risk 3 is that this surface has been O(1) forever and nobody
        has measured N, and `tests/test_homes_verb.py` already pins the same
        property for the `fleet homes` VIEW -- so the resolution path was the
        one place the count was a comment.

        A doubled read is the shape that ships green because nothing about it is
        WRONG; it is only twice the cost, on every sid-carrying invocation, per
        listed home."""
        a = home("A", {"w": _rec("SID-1")})
        _list(sandboxed_list, a, home("B"), home("C"))
        reads = []
        real = fleet.read_registry_at
        monkeypatch.setattr(fleet, "read_registry_at",
                            lambda h: reads.append(fleet.home_identity(h)) or real(h))
        look = fleet.lookup_home_for_sid("SID-1")
        assert look["state"] == "hit"
        assert len(reads) == len(set(reads)) == len(look["population"]), (
            f"{len(reads)} reads for {len(look['population'])} homes: "
            f"{sorted(reads)}")

    def test_a_lookup_that_already_read_every_home_is_not_re_read(
            self, home, sandboxed_list, monkeypatch):
        """§5.2's contract is *"per home, ONE lock-free snapshot"*. The lookup
        reads them all; arming reuses that census rather than doubling it."""
        a = home("A", {"w": _rec("SID-1")})
        _list(sandboxed_list, a, home("B"))
        look = fleet.lookup_home_for_sid("SID-1")
        reads = []
        real = fleet.read_registry_at
        monkeypatch.setattr(fleet, "read_registry_at",
                            lambda h: reads.append(h) or real(h))
        assert fleet.multi_fleet_arming(look)["armed"] is True
        assert reads == []


# ---------------------------------------------------------------------------
# §7's destructive-tier pin, in the words §7 writes it
# ---------------------------------------------------------------------------

class TestTheDestructiveTierPin:
    """§7, verbatim: *"the **destructive tier pin** -- armed machine,
    env-resolved `clean` refuses naming the flag; env-resolved `spawn`
    proceeds"*."""

    @pytest.fixture
    def armed(self, home, sandboxed_list, monkeypatch):
        a, b = home("A"), home("B")
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        monkeypatch.setenv("FLEET_HOME", str(a))
        return a, b

    def test_an_env_resolved_clean_refuses_naming_the_flag(
            self, armed, monkeypatch, capsys):
        log = _reached(monkeypatch, "clean")
        assert fleet.main(["clean", "--yes"]) == 1
        err = capsys.readouterr().err
        assert "--fleet-home" in err
        assert log == [], "the destructive verb ran anyway"

    def test_an_env_resolved_spawn_proceeds(self, armed, monkeypatch):
        log = _reached(monkeypatch, "spawn")
        assert fleet.main(["spawn", "w", "--dir", ".", "--task", "t"]) == 0
        assert log == ["spawn"]

    def test_the_refusal_names_no_chosen_home(self, armed, monkeypatch, capsys):
        """§5's refusal contract: *"Refusals print facts + the `fleet homes`
        view, never a paste-ready command with a chosen home."*"""
        a, b = armed
        _reached(monkeypatch, "clean")
        assert fleet.main(["clean", "--yes"]) == 1
        err = capsys.readouterr().err
        for h in (a, b):
            assert f"--fleet-home {fleet.home_identity(h)}" not in err

    def test_the_refusal_embeds_the_homes_view(self, armed, monkeypatch, capsys):
        _reached(monkeypatch, "clean")
        assert fleet.main(["clean", "--yes"]) == 1
        assert "fleet homes:" in capsys.readouterr().err

    def test_yes_does_not_buy_past_the_destructive_tier(
            self, armed, monkeypatch, capsys):
        """ga2 F2, and the half of it that turns out NOT to land on a3. §5
        step 1's `--yes` escape belongs to the flag/lookup DISAGREEMENT clause.
        The destructive tier's own remedy, in §5's own words, is *"destructive
        via env/legacy requires the flag"* -- the flag, not a confirmation. So
        `--yes` must not satisfy this refusal, and the 30 verbs that have no
        `--yes` are not blocked by its absence."""
        _reached(monkeypatch, "clean")
        assert fleet.main(["clean", "--yes"]) == 1

    def test_the_flag_is_what_lets_it_through(self, armed, monkeypatch):
        """The remedy the refusal names actually works -- otherwise the guard
        is a brick with a friendly message, which is the defect a2 shipped twice
        inside its own lane."""
        a, _b = armed
        log = _reached(monkeypatch, "clean")
        assert fleet.main(["--fleet-home", str(a), "clean", "--yes"]) == 0
        assert log == ["clean"]

    def test_a_lookup_hit_is_exempt(self, home, sandboxed_list, monkeypatch):
        """§5: *"Lookup-hit resolutions are exempt from both -- membership is
        affirmative evidence."*"""
        a = home("A", {"w": _rec("SID-1")})
        _list(sandboxed_list, a, home("B"))
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        log = _reached(monkeypatch, "clean")
        assert _run(["clean", "--yes"], monkeypatch, sid="SID-1") == 0
        assert log == ["clean"]

    def test_an_unarmed_machine_is_byte_identical_to_today(
            self, home, monkeypatch):
        """The other half of §7's arming pin: *"The arming pin's <2 baseline
        comparison stays."* One fleet, no list -- the guard must be invisible."""
        a = home("A")
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        log = _reached(monkeypatch, "clean")
        assert _run(["clean", "--yes"], monkeypatch) == 0
        assert log == ["clean"]

    @pytest.mark.parametrize("flag", ["--answer", "--raise"])
    def test_an_empty_residual_flag_does_not_fail_open(
            self, flag, armed, monkeypatch):
        """ga3 B1. The residual-flag rows decided *"is this flag set?"* by
        TRUTHINESS while `cmd_sup_decision` decides *"am I writing?"* by
        PRESENCE. The two predicates agree on every value but `""`, which is
        present and falsy -- so `fleet sup-decision --answer ''` classified
        ORDINARY, sailed past this guard, and read-modify-wrote a foreign
        home's pending-decision file, stamping `answered_at` under an answer
        that still reads OPEN. `fleet sup-decision --answer "$DECISION"` with
        an unset variable is the field shape of it.

        DRIVEN THROUGH `main()`, NOT THROUGH `_ns()`, AND THAT IS THE POINT.
        Every other test of this classification hand-builds a namespace, and
        the parametrised fail-safe test above happens to pass two truthy
        values -- which is exactly why 4061 tests did not see this. A pin that
        builds its own `Namespace(answer="")` would be the same weaker shape;
        this one takes the namespace `build_parser()` actually produces."""
        log = _reached(monkeypatch, "sup-decision")
        assert fleet.main(["sup-decision", flag, ""]) == 1
        assert log == [], "an empty residual flag walked past the guard"


class TestTheDisruptiveTierIsLoudAndNotRefused:
    """§5, and the operator ruling that made it non-negotiable
    (`docs/OPERATOR-GATES.md`, quoted in `docs/mf-slice-a-price.md` §2):
    *"wrong-home disruptive verbs proceed loudly rather than refuse"* -- do not
    tighten it to a refusal during implementation."""

    @pytest.fixture
    def armed(self, home, sandboxed_list, monkeypatch):
        a, b = home("A"), home("B")
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        return a, b

    def test_a_disruptive_verb_proceeds(self, armed, monkeypatch):
        log = _reached(monkeypatch, "send")
        assert _run(["send", "w", "hi"], monkeypatch) == 0
        assert log == ["send"]

    def test_it_renders_its_resolution_provenance(self, armed, monkeypatch,
                                                  capsys):
        a, _b = armed
        _reached(monkeypatch, "send")
        assert _run(["send", "w", "hi"], monkeypatch) == 0
        out = capsys.readouterr().out
        assert "[fleet] home" in out and a.resolve().as_posix() in out

    def test_the_provenance_is_the_renderer_a2_built(self, armed, monkeypatch,
                                                     capsys):
        """a2's §10, verbatim: *"use them; do not mint a second spelling"*. The
        line the guard prints IS `resolution_provenance`'s output."""
        _reached(monkeypatch, "send")
        printed = []
        real = fleet.resolution_provenance
        monkeypatch.setattr(fleet, "resolution_provenance",
                            lambda res: printed.append(real(res)) or printed[-1])
        assert _run(["send", "w", "hi"], monkeypatch) == 0
        assert printed and printed[-1] in capsys.readouterr().out

    def test_an_ordinary_verb_stays_silent(self, armed, monkeypatch, capsys):
        """The tier is three-way, not two. `fleet status` on an armed machine
        must not grow a provenance banner it never had."""
        _reached(monkeypatch, "status")
        assert _run(["status"], monkeypatch) == 0
        assert "[fleet] home" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The rule a2 paid for twice, in the form the ga2 gate qualified it into
# ---------------------------------------------------------------------------

class TestFleetHomesSitsAboveEveryBlockingStateTheResolverEnters:
    """a2's §10, as re-stated by the ga2 gate (§4 W1) with the qualification
    that survived its attack:

      Every blocking state **the resolver** enters names `fleet homes` as its
      remedy, so `fleet homes` must sit above every one of them.

    THE QUALIFICATION IS LOAD-BEARING AND IS CARRIED HERE RATHER THAN DROPPED.
    Two of the refusals on this surface are ARGV-level and are not the
    resolver's: `--fleet-home` with a bad value, and `--fleet-home` repeated
    with two different values. Those are states the OPERATOR entered and can
    leave by editing their own command line -- `fleet homes` is not their
    remedy and must not be advertised as one. The rule is about the states a
    session finds itself in that no edit to the argv escapes: the terminus, the
    lookup ambiguity, the flag/lookup disagreement, and (new in a3) the
    wrong-home destructive refusal."""

    RESOLVER_BLOCKING_STATES = ("terminus", "ambiguity", "disagreement",
                                "wrong_home")

    def _drive(self, which, home, bare, sandboxed_list, monkeypatch):
        if which == "terminus":
            _list(sandboxed_list, home("L"))
            monkeypatch.setattr(fleet, "FLEET_HOME", bare("B"))
            return _run(["clean", "--yes"], monkeypatch)
        if which == "ambiguity":
            a = home("A", {"w": _rec("SID-1")})
            b = home("B", {"x": _rec("SID-1")})
            _list(sandboxed_list, a, b)
            monkeypatch.setattr(fleet, "FLEET_HOME", a)
            return _run(["clean", "--yes"], monkeypatch, sid="SID-1")
        if which == "disagreement":
            a = home("A", {"w": _rec("SID-1")})
            _list(sandboxed_list, a)
            monkeypatch.setattr(fleet, "FLEET_HOME", a)
            return _run(["--fleet-home", str(home("B")), "clean"],
                        monkeypatch, sid="SID-1")
        a, b = home("A"), home("B")
        _list(sandboxed_list, a, b)
        monkeypatch.setattr(fleet, "FLEET_HOME", a)
        return _run(["clean", "--yes"], monkeypatch)

    @pytest.mark.parametrize("which", RESOLVER_BLOCKING_STATES)
    def test_every_blocking_state_names_the_list_manager(
            self, which, home, bare, sandboxed_list, monkeypatch, capsys):
        _reached(monkeypatch, "clean")
        assert self._drive(which, home, bare, sandboxed_list, monkeypatch) == 1
        assert "fleet homes:" in capsys.readouterr().err, (
            f"the {which} refusal does not embed the `fleet homes` view, so "
            f"its own stated remedy is invisible from inside it")

    @pytest.mark.parametrize("which", RESOLVER_BLOCKING_STATES)
    def test_the_list_manager_runs_under_every_blocking_state(
            self, which, home, bare, sandboxed_list, monkeypatch, capsys):
        """THE DEADLOCK HALF, which is the one a2 shipped twice. It is not
        enough for the refusal to NAME `fleet homes`; the verb has to actually
        run while the state holds, or the remedy is advice the machine refuses
        to take."""
        target = home("T")
        self._drive(which, home, bare, sandboxed_list, monkeypatch)
        capsys.readouterr()
        assert _run(["homes", "--add", str(target)], monkeypatch,
                    sid="SID-1") == 0
        assert fleet.home_identity(target) in fleet.read_homes_list()["members"]

    def test_the_argv_level_refusals_are_deliberately_not_in_that_set(
            self, bare, monkeypatch, capsys):
        """The ga2 qualification, as an executable statement. These two refuse
        WITHOUT the view, and that is correct: the operator edits their command
        line, not their homes list. If someone later "fixes" them into
        consistency with the four above, this goes RED and the qualification
        has to be re-argued rather than quietly lost."""
        assert _run(["--fleet-home", str(bare("B")), "clean"], monkeypatch) == 1
        assert "fleet homes:" not in capsys.readouterr().err
        assert _run(["--fleet-home", "A", "--fleet-home", "B", "clean"],
                    monkeypatch) == 1
        assert "fleet homes:" not in capsys.readouterr().err

    def test_the_guard_never_tiers_a_terminus_exempt_verb(self):
        """Belt to the braces above: `fleet homes` is exempt from the ORDER
        (a2's `TERMINUS_EXEMPT_VERBS`, checked before `resolve_home` runs) AND
        ordinary in the ratified table, so neither layer can block it. Both are
        required -- the exemption is what stops the resolver refusing first, and
        the tier is what stops the guard refusing second."""
        for verb in fleet.TERMINUS_EXEMPT_VERBS:
            assert fleet.verb_effect_tier(verb) == "ordinary"


# ---------------------------------------------------------------------------
# Risk 4 -- the bare-word collision, made enforceable
# ---------------------------------------------------------------------------

class TestTheArmingSymbolsCannotBeConfusedWithTheClaimGate:
    """`docs/mf-slice-a-price.md` Risk 4: multi-fleet's "armed" (population >=2)
    and claim-nonce's already-shipped "armed" supervisor-claim-gate concept
    share a word inside the same 19.7k-line module. *"Resolves: prefix
    multi-fleet's arming symbols distinctly (e.g. `_homes_population_armed`, not
    a bare `armed`/`_is_armed`) so a future grep or a tired reader doesn't
    conflate the two."*

    A convention nothing checks is a convention until the first tired reader.
    This derives the module's top-level names from the AST."""

    BARE = {"armed", "arm", "is_armed", "_is_armed", "_armed", "_arm",
            "arming", "_arming"}

    def test_no_top_level_name_is_the_bare_word(self):
        tree = ast.parse(SRC)
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets
                             if isinstance(t, ast.Name))
        collide = sorted(names & self.BARE)
        assert not collide, (
            f"{collide} is the bare word Risk 4 forbids -- `bin/fleet.py` also "
            f"carries claim-nonce's unrelated 'armed' concept, and one grep "
            f"must not return both")

    def test_every_arming_symbol_this_slice_adds_is_prefixed(self):
        tree = ast.parse(SRC)
        named = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and re.search(r"arm(ed|ing)?\b", n.name)]
        assert named, "the arming predicate vanished -- this pin is now vacuous"
        for name in named:
            assert name.lstrip("_").startswith("multi_fleet_"), (
                f"`{name}` names arming without the `multi_fleet_` prefix")

    def test_the_seed_the_detector_can_see_a_bare_name(self):
        """A negative over a derived set proves nothing until it is shown
        firing. Parse a planted source rather than the real one."""
        tree = ast.parse("def is_armed():\n    return True\n")
        names = {n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert names & self.BARE


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ns(**kw):
    import argparse
    return argparse.Namespace(**kw)


def _sibling_pins():
    import importlib
    return importlib.import_module("test_round7_defect_pins")


def _shipped_verbs():
    parser = fleet.build_parser()
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            return sorted(action.choices)
    raise AssertionError("no subparsers action on build_parser()")


def _subparser(parser, verb):
    """The subparser `build_parser()` ships for one verb, so a claim about a
    flag's dest is measured off the real CLI rather than restated."""
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            assert verb in action.choices, f"build_parser() ships no `{verb}`"
            return action.choices[verb]
    raise AssertionError("no subparsers action on build_parser()")
