"""G-K5 item (1): the statusline row CARRIES the home's identity.

Operator ruling 2026-09-10, G-K5 Reading A, verbatim: *"fleet statusbar must be
different per fleet home."*

WHAT WAS ALREADY BUILT, AND IS NOT RE-TESTED HERE. Per-home RESOLUTION is
multi-fleet slice (d) and ships: the blob's sid is looked up and
`fleet.FLEET_HOME` moves before the roster is read, so two sessions on one
machine already render two different COUNTS. `tests/test_statusline_home.py`
owns that and nothing below re-derives it. What was missing -- measured by this
lane against two real homes before a line was written -- is that both rows said
`[fleet]`, so the operator could see that the numbers differed and not which
fleet either row belonged to.

THE FIELD. The nameplate becomes `[fleet:<tag>]`, where `<tag>` is
`fleet.home_tag()`: four hex digits of a digest over `fleet.home_identity()`.
Three properties are what this file pins, because they are the three the ruling
and the brief actually constrain:

  1. IT IS A PURE FUNCTION OF THE HOME. Not the session, not the population --
     "one home must not look different from itself across sessions".
  2. THE SINGLE-HOME MACHINE DOES NOT PAY. No homes list => no tag => the row
     is byte-identical to the pre-ruling row. §5's arming paragraph already
     required exactly this of slice (d) and the tag inherits it rather than
     inventing a second rule.
  3. TWO HOMES NEVER RENDER ONE NAMEPLATE without something saying so. Bounded
     width cannot be injective over paths, so the collision is not designed
     away -- it is surfaced, in `fleet homes`, which is the tag's legend.

ISOLATION. Same belt as `test_statusline_home.py`: `homes_list_path` is
redirected per test, and the operator's real machine-global list is compared as
BYTES at the end of the module.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_statusline as sl  # noqa: E402

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"
_REAL_LIST_AT_IMPORT = REAL_LIST.read_bytes() if REAL_LIST.exists() else None

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


# --- fixtures (deliberately the same shapes as test_statusline_home.py) -----

@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


@pytest.fixture
def home(tmp_path):
    def make(name, workers=None):
        h = tmp_path / name
        (h / "state").mkdir(parents=True, exist_ok=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        return h
    return make


def worker(sid, status="idle", name="w"):
    return {name: {"session_id": sid, "status": status, "cwd": "C:/x",
                   "last_activity": fleet.now_iso(), "turns": 1, "cost_usd": 0.0}}


@pytest.fixture
def listed(sandboxed_list):
    def add(*homes):
        sandboxed_list.write_text(
            "".join(fleet.home_identity(h) + "\n" for h in homes), encoding="utf-8")
    return add


@pytest.fixture
def at(monkeypatch):
    def go(install, default=None):
        monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
        monkeypatch.setattr(fleet, "FLEET_HOME", default or install)
    return go


@pytest.fixture
def run_main(monkeypatch, capsys):
    def go(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        rc = sl.main()
        return rc, capsys.readouterr().out
    return go


def blob(sid):
    return json.dumps({"session_id": sid})


# --- 1. the tag is a pure function of the home ------------------------------

class TestTheTagIsDerivedFromTheHomeAndNothingElse:
    """The brief's second constraint, verbatim: *"One home must not look
    different from itself across sessions -- the identity must be derived from
    the home, not from the session that happens to be reading it."*"""

    def test_the_same_home_tags_the_same_every_time(self):
        assert fleet.home_tag("/srv/fleet") == fleet.home_tag("/srv/fleet")

    def test_the_spellings_home_identity_folds_together_tag_together(self):
        """`home_identity` is what the homes-list fold keys on, and it declares
        `C:\\f`, `C:/f/` and `C:/f` to be ONE home. A tag derived from the raw
        text instead would give one fleet two nameplates depending on which
        spelling reached the renderer -- which is the defect the field exists
        to prevent, one layer down."""
        base = fleet.home_tag("C:/f")
        for spelling in ("C:\\f", "C:/f/", "C:/f//", "  C:/f  "):
            assert fleet.home_tag(spelling) == base, spelling

    def test_two_different_homes_tag_differently(self):
        assert fleet.home_tag("/srv/a") != fleet.home_tag("/srv/b")

    def test_the_tag_takes_no_session_and_no_population(self):
        """A signature pin, not a behaviour pin, and it is the cheapest possible
        guard on the constraint above: a tag that cannot SEE the session or the
        population cannot vary with either."""
        import inspect
        params = list(inspect.signature(fleet.home_tag).parameters)
        assert params == ["home"], params

    def test_the_tag_is_hex_of_the_declared_width(self):
        tag = fleet.home_tag("/srv/fleet")
        assert len(tag) == fleet.HOME_TAG_HEX
        assert re.fullmatch(r"[0-9a-f]+", tag), tag

    @pytest.mark.parametrize("weird", [
        Path("/srv/fleet"), 17, None, "", "/\x1b[2K/evil", "/srv/\udcff/f",
        "/srv/" + "x" * 5000,
    ])
    def test_it_is_total_and_always_hex(self, weird):
        """TOTAL, and the hostile entries are the point rather than padding. A
        member path comes out of `~/.claude/fleet-homes.list`; since slice (d)
        the reader is not necessarily its writer, and the tag lands INSIDE the
        nameplate -- the one token `_safe` strips brackets to protect. Hex
        digits cannot carry an escape, a CR or a bracket, so the digest is the
        sanitiser and there is no second one to forget."""
        tag = fleet.home_tag(weird)
        assert re.fullmatch(r"[0-9a-f]{%d}" % fleet.HOME_TAG_HEX, tag), (weird, tag)


# --- 2. the nameplate -------------------------------------------------------

class TestTheNameplate:

    def test_the_untagged_nameplate_is_the_prefix_itself(self):
        assert sl.nameplate() == sl.PREFIX
        assert sl.nameplate(None) == sl.PREFIX
        assert sl.nameplate("") == sl.PREFIX

    def test_the_tagged_nameplate_is_derived_from_prefix_not_retyped(
            self, monkeypatch):
        """`f"[fleet:{tag}]"` would be a SECOND literal spelling of the
        nameplate, and this surface already treats that as a defect class
        (`test_the_terminus_text_is_not_a_retyped_literal`). Renaming the
        prefix must rename both forms or the row grows two nameplates."""
        monkeypatch.setattr(sl, "PREFIX", "[flt]")
        assert sl.nameplate("9c3a") == "[flt:9c3a]"

    def test_the_tag_lives_inside_the_brackets(self):
        assert sl.nameplate("9c3a") == "[fleet:9c3a]"

    def test_the_tagged_nameplate_costs_five_columns(self):
        """The brief: *"a home identity that doubles the row's width is a
        regression in the surface it is meant to improve."* Five columns on a
        row that is ~45 wide is ~11%."""
        assert len(sl.nameplate("9c3a")) - len(sl.PREFIX) == 5


# --- 3. the single-home machine does not pay --------------------------------

class TestTheSingleHomeRowDoesNotRegress:
    """The brief's third constraint: *"Most operators have one fleet; a row
    that suddenly grows a redundant tag on a one-fleet machine is a cost paid
    by everyone for a case almost nobody has."*"""

    def test_render_statusline_defaults_to_the_untagged_row(self):
        """The default is the whole non-regression argument: every caller and
        every test that existed before this field renders exactly what it
        rendered before, so the property is enforced by the suite that was
        already there rather than by this file alone."""
        snap = {"ok": True, "workers": [{"status": "working"}]}
        assert sl.render_statusline(snap, color=False) == f"{sl.PREFIX}  work 1"

    def test_a_machine_with_no_homes_list_renders_the_bare_nameplate(
            self, home, at, run_main):
        """END TO END through `main()`, which is where the short-circuit
        actually fires. No list => `population_is_multi_home` is False =>
        `HOME_SINGLE` => no tag."""
        h = home("only", worker("s-1", "working"))
        at(h)
        rc, out = run_main(blob("s-1"))
        assert rc == 0
        assert plain(out).strip() == f"{sl.PREFIX}  work 1", out

    def test_a_failed_resolution_also_renders_the_bare_nameplate(
            self, home, at, monkeypatch, run_main):
        """`HOME_SINGLE` is `resolve_blob_home`'s error value as well as its
        short-circuit, and the tag inherits that on purpose: a view's failure
        mode is the surface it always had."""
        h = home("only", worker("s-1", "working"))
        at(h)
        monkeypatch.setattr(fleet, "resolution_population",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        rc, out = run_main(blob("s-1"))
        assert rc == 0
        assert plain(out).strip() == f"{sl.PREFIX}  work 1", out


# --- 4. two homes, two nameplates -------------------------------------------

class TestTwoHomesRenderTwoNameplates:
    """The ruling itself: *"fleet statusbar must be different per fleet home."*"""

    def test_each_session_gets_its_own_homes_tag(
            self, home, at, listed, run_main):
        a = home("alpha", worker("sid-a", "working"))
        b = home("bravo", worker("sid-b", "idle"))
        listed(a, b)
        at(a)

        rc_a, out_a = run_main(blob("sid-a"))
        rc_b, out_b = run_main(blob("sid-b"))
        assert (rc_a, rc_b) == (0, 0)
        line_a, line_b = plain(out_a).strip(), plain(out_b).strip()

        assert line_a.startswith(sl.nameplate(fleet.home_tag(a))), line_a
        assert line_b.startswith(sl.nameplate(fleet.home_tag(b))), line_b
        assert line_a != line_b

    def test_the_nameplate_differs_even_when_the_counts_are_identical(
            self, home, at, listed, run_main):
        """THE CASE THE COUNTS CANNOT COVER, and the reason the field exists.
        Two fleets in the same shape rendered byte-identical rows before this
        change -- the operator could not tell the windows apart at all."""
        a = home("alpha", worker("sid-a", "working"))
        b = home("bravo", worker("sid-b", "working"))
        listed(a, b)
        at(a)

        line_a = plain(run_main(blob("sid-a"))[1]).strip()
        line_b = plain(run_main(blob("sid-b"))[1]).strip()
        assert line_a.split(None, 1)[1:] == line_b.split(None, 1)[1:], (
            "the rosters are the same shape; only the nameplate may differ")
        assert line_a != line_b, (line_a, line_b)

    def test_one_home_looks_the_same_from_two_sessions(
            self, home, at, listed, run_main):
        """The constraint stated as a test: two sids CLAIMED BY ONE HOME must
        produce one nameplate."""
        a = home("alpha", {**worker("sid-1", "working", name="w1"),
                           **worker("sid-2", "idle", name="w2")})
        b = home("bravo", worker("sid-b"))
        listed(a, b)
        at(a)
        one = plain(run_main(blob("sid-1"))[1]).strip().split()[0]
        two = plain(run_main(blob("sid-2"))[1]).strip().split()[0]
        assert one == two == sl.nameplate(fleet.home_tag(a))

    def test_the_unclaimed_session_still_names_the_home_it_read(
            self, home, at, listed, run_main):
        """`HOME_DEFAULT`: nothing claimed this session, so the default home's
        roster is what renders. On a multi-fleet machine an UNTAGGED row among
        tagged ones would be the one row the operator could not place."""
        a = home("alpha", worker("sid-a", "working"))
        b = home("bravo", worker("sid-b"))
        listed(b)
        at(a)
        line = plain(run_main(blob("nobody-claims-this"))[1]).strip()
        assert line.startswith(sl.nameplate(fleet.home_tag(a))), line

    @pytest.mark.parametrize("snap,tail", [
        ({"ok": False, "reason": "unreadable"}, ": registry unreadable"),
        ({"ok": False, "reason": "quarantined"}, ": registry quarantined"),
        ({"ok": True, "workers": []}, ": no workers"),
        ({"ok": True, "workers": [{"status": "dead"}]},
         "  no live workers  +1 dead"),
    ])
    def test_every_row_shape_carries_the_nameplate_it_was_given(self, snap, tail):
        """The tag is on the NAMEPLATE, so it rides every shape the row can
        take -- including the fault rows, where *which* fleet is broken is the
        whole of the news. Driven at the renderer because the resolver cannot
        reach `ok: False` on the `default` branch: §5 steps 3/4 require
        `home_is_initialized(default_home)`, which is exactly the predicate a
        broken registry fails. See `test_the_terminus_is_deliberately_untagged`
        for where a broken default home actually lands."""
        assert sl.render_statusline(snap, color=False, tag="9c3a") == \
            f"[fleet:9c3a]{tail}"

    def test_a_broken_default_home_lands_on_the_terminus_not_on_a_fault_row(
            self, home, bare_home, at, listed, run_main):
        """MEASURED, and it corrected this lane's own first draft of the test
        above. A corrupt default home is not `HOME_DEFAULT` with a fault -- it
        fails `home_is_initialized`, falls to §5 step 5, and the TERMINUS takes
        the line. The fault is named; the home is not. See
        `test_the_terminus_is_deliberately_untagged`."""
        broken = bare_home("broken")
        (broken / "state").mkdir(parents=True)
        (broken / "state" / "fleet.json").write_text("{ not json", encoding="utf-8")
        listed(home("other", worker("sid-o")))
        at(broken)
        line = plain(run_main(blob("unclaimed"))[1]).strip()
        assert line == f"{sl.PREFIX}: {fleet.NO_HOME_LINE.split(': ', 1)[1]}" \
                       " -- registry unreadable", line


@pytest.fixture
def bare_home(tmp_path):
    def make(name):
        h = tmp_path / name
        h.mkdir(parents=True, exist_ok=True)
        return h
    return make


# --- 5. rendered_home_tag, state by state -----------------------------------

class TestWhichStatesCarryATag:

    @pytest.mark.parametrize("state", [sl.HOME_LOOKUP, sl.HOME_DEFAULT])
    def test_the_roster_states_carry_one(self, state):
        assert sl.rendered_home_tag({"state": state}, "/srv/f") == \
            fleet.home_tag("/srv/f")

    @pytest.mark.parametrize("state", [sl.HOME_SINGLE, sl.HOME_NONE,
                                       sl.HOME_AMBIGUOUS, "nonsense"])
    def test_every_other_state_carries_none(self, state):
        assert sl.rendered_home_tag({"state": state}, "/srv/f") == ""

    @pytest.mark.parametrize("record", [None, {}, {"state": None}, []])
    def test_a_hand_built_record_degrades_to_no_tag(self, record):
        """Tolerant of a record it did not build, like every other renderer on
        this surface -- and the degradation is the SHIPPED row, never a
        traceback the exit-0 guard would turn into a blank line."""
        assert sl.rendered_home_tag(record, "/srv/f") == ""

    def test_a_raising_tag_costs_the_tag_and_not_the_row(self, monkeypatch):
        monkeypatch.setattr(fleet, "home_tag",
                            lambda h: (_ for _ in ()).throw(RuntimeError("x")))
        assert sl.rendered_home_tag({"state": sl.HOME_LOOKUP}, "/srv/f") == ""

    def test_the_terminus_is_deliberately_untagged(self, home, at, listed,
                                                   run_main):
        """§5 step 5 and the ambiguity word both say *"there is no home"*, so
        there is nothing to name. `render_home_terminus` takes the line first;
        this pins that the tag did not sneak a nameplate into either word."""
        b = home("bravo", worker("sid-b"))
        listed(b)
        at(tmp := b.parent / "absent")
        assert not tmp.exists()
        line = plain(run_main(blob("unclaimed"))[1]).strip()
        assert line.startswith(sl.PREFIX + ":"), line
        assert ":" not in line[:len(sl.PREFIX)], line


# --- 6. the legend, and the collision -------------------------------------

class TestTheLegend:
    """Four hex digits name no directory on their own. The tag is only usable
    if it is readable next to its path somewhere, and both surfaces below use
    the SAME pure function, so they cannot disagree with the bar."""

    def test_fleet_homes_renders_the_tag_the_bar_renders(
            self, home, at, listed, run_main):
        a = home("alpha", worker("sid-a", "working"))
        b = home("bravo", worker("sid-b"))
        listed(a, b)
        at(a)
        bar = plain(run_main(blob("sid-a"))[1]).strip().split()[0]
        view = fleet.render_homes_view()
        assert fleet.home_tag(a) in view and fleet.home_tag(b) in view, view
        assert bar == sl.nameplate(fleet.home_tag(a))
        # the tag stands in the same row as its path
        for row in view.splitlines():
            if fleet.home_identity(a) in row:
                assert row.strip().startswith(fleet.home_tag(a)), row
                break
        else:
            raise AssertionError(f"no row for {a} in\n{view}")

    def test_fleet_home_tag_agrees_with_the_bar(self, home, at, capsys):
        a = home("alpha")
        at(a)
        import argparse
        fleet.cmd_home(argparse.Namespace(tag=True))
        assert capsys.readouterr().out.strip() == fleet.home_tag(fleet.FLEET_HOME)

    def test_bare_fleet_home_is_unchanged(self, home, at, capsys):
        """`$(fleet home)` is substituted into paths by the skill, the slash
        commands and the briefs. One extra word breaks every one of them."""
        a = home("alpha")
        at(a)
        import argparse
        fleet.cmd_home(argparse.Namespace())
        out = capsys.readouterr().out
        assert out == Path(a).resolve().as_posix() + "\n", out

    def test_a_tag_collision_is_named_rather_than_silent(
            self, home, listed, monkeypatch):
        """Bounded width cannot be injective over paths, so a collision is not
        designed away -- it is SURFACED. Two homes sharing a nameplate while
        the operator still believes the nameplate separates them is worse than
        no tag at all."""
        a, b = home("alpha"), home("bravo")
        listed(a, b)
        monkeypatch.setattr(fleet, "home_tag", lambda h: "dead")
        view = fleet.render_homes_view()
        assert "dead" in view
        assert "shared by two or more homes" in view, view

    def test_no_collision_note_when_the_tags_are_distinct(self, home, listed):
        listed(home("alpha"), home("bravo"))
        assert "shared by two or more homes" not in fleet.render_homes_view()


# --- 7. the doctrine this surface is bound by -------------------------------

def test_the_tag_adds_no_read_to_the_view(home, at, listed, monkeypatch,
                                          run_main):
    """Root `CLAUDE.md` / terminal-surface D4: views take no lock, probe
    nothing, write nothing, quarantine nothing. The tag is a pure string
    function over a path the process already holds, so the number of registry
    reads a render performs is unchanged by it.

    Counted rather than asserted-in-prose: `read_registry_at` is the one read
    the resolution and the roster share, and this drives a two-home machine and
    requires the count to be what slice (d) already cost."""
    a = home("alpha", worker("sid-a", "working"))
    b = home("bravo", worker("sid-b"))
    listed(a, b)
    at(a)

    reads = []
    real = fleet.read_registry_at
    monkeypatch.setattr(fleet, "read_registry_at",
                        lambda h: (reads.append(str(h)), real(h))[1])
    tagged = run_main(blob("sid-a"))
    assert tagged[0] == 0

    reads_with_tag = list(reads)
    reads.clear()
    monkeypatch.setattr(sl, "rendered_home_tag", lambda *a, **k: "")
    assert run_main(blob("sid-a"))[0] == 0
    assert reads_with_tag == reads, (reads_with_tag, reads)


def test_the_real_homes_list_is_untouched_by_this_file():
    """BYTES, not existence -- the same belt `test_statusline_home.py` wears.
    The machine-global list is append-only and RATIFIED DESTRUCTIVE."""
    now = REAL_LIST.read_bytes() if REAL_LIST.exists() else None
    assert now == _REAL_LIST_AT_IMPORT
