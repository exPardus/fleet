"""`fleet homes` -- view / `--add` / `--retire` (multi-fleet M1 scope + §4,
slice a1 deliverable 3).

WHAT THE VERB IS FOR, beyond editing a file. §5's refusal contract says
*"Refusals print facts + the `fleet homes` view, never a paste-ready command
with a chosen home"* -- so the view is not decoration, it is the thing a
wrong-home refusal shows the operator instead of choosing for them. That is why
the rendering is a pure function (`render_homes_view`) rather than a pile of
`print()` calls inside the verb: slice a3's destructive-tier refusal has to be
able to embed it, and a renderer that only exists as side effects cannot be
embedded. `test_the_view_is_renderable_as_a_string_for_a3s_refusals` is the pin
that keeps that seam open.

TIER: ordinary. §5's verb-effect table classifies `homes --add/--retire` as
*"ordinary (list-reversible)"* -- the list is append-only and a wrong `--add` is
undone by a `--retire`, so nothing here is guarded. The coupled edit that moves
`homes` out of `RATIFIED_BUT_UNBUILT` and into `RATIFIED_ORDINARY` lands in
`tests/test_round7_defect_pins.py` in the same commit as this verb; without it
`test_every_shipped_verb_is_classified_or_declared_unclassified` goes RED on a
verb with no effect disposition, which is exactly what that pin is for.

THE VIEW IS A VIEW (root `CLAUDE.md`): no `fleet.lock`, no probe, no write, no
quarantine, and it exits 0 on every input including an unreadable list.

ISOLATION: the same `homes_list_path` redirect and the same escalation as
`tests/test_homes_list.py` -- conftest's autouse home sandbox enumerates three
helpers by name and does not cover this one.
"""
import argparse
import json
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
    def make(name, workers=None):
        h = tmp_path / name
        (h / "state").mkdir(parents=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        return h
    return make


def _run(argv, capsys):
    rc = fleet.main(argv)
    return rc, capsys.readouterr()


def _ident(p):
    return fleet.home_identity(str(p))


# ---------------------------------------------------------------------------
# 0. The verb exists, with the surface the spec names
# ---------------------------------------------------------------------------

class TestTheParserSurface:
    def test_homes_is_a_subcommand(self):
        parser = fleet.build_parser()
        sub = next(a for a in parser._actions
                   if isinstance(a, argparse._SubParsersAction))
        assert "homes" in sub.choices

    def test_it_offers_exactly_add_and_retire(self):
        parser = fleet.build_parser()
        sub = next(a for a in parser._actions
                   if isinstance(a, argparse._SubParsersAction))
        opts = {o for a in sub.choices["homes"]._actions for o in a.option_strings}
        assert opts == {"-h", "--help", "--add", "--retire"}

    def test_add_and_retire_are_mutually_exclusive(self, capsys):
        """One record per invocation. `--add X --retire X` has no defined fold
        order and would be an operator asking for a coin flip."""
        with pytest.raises(SystemExit) as exc:
            fleet.build_parser().parse_args(["homes", "--add", "C:/a",
                                             "--retire", "C:/a"])
        assert exc.value.code == 2

    def test_the_bare_verb_takes_no_positional(self, capsys):
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["homes", "C:/a"])


# ---------------------------------------------------------------------------
# 1. The view
# ---------------------------------------------------------------------------

class TestTheView:
    def test_an_empty_machine_says_so_and_exits_0(self, capsys, sandboxed_list):
        rc, out = _run(["homes"], capsys)
        assert rc == 0
        assert "no homes listed" in out.out
        assert not sandboxed_list.exists(), "the view created the list"

    def test_each_listed_home_renders_with_its_read_time_state(
            self, capsys, home, tmp_path, sandboxed_list):
        good = home("good", {"w1": {"session_id": "s1"}, "w2": {"session_id": "s2"}})
        bare = tmp_path / "bare"
        bare.mkdir()
        broken = tmp_path / "broken"
        (broken / "state").mkdir(parents=True)
        (broken / "state" / "fleet.json").write_text("{ not json", encoding="utf-8")
        sandboxed_list.write_text(
            "".join(_ident(p) + "\n" for p in (good, bare, broken)), encoding="utf-8")

        rc, out = _run(["homes"], capsys)
        assert rc == 0
        lines = {ln.split()[0]: ln for ln in out.out.splitlines() if ln.startswith("  ")}
        assert "ok" in lines[_ident(good)] and "2 worker" in lines[_ident(good)]
        assert "not initialized" in lines[_ident(bare)]
        assert "unreadable" in lines[_ident(broken)]

    def test_a_retired_home_is_not_rendered_as_a_member(
            self, capsys, home, sandboxed_list):
        h = home("h")
        sandboxed_list.write_text(f"{_ident(h)}\n!{_ident(h)}\n", encoding="utf-8")
        rc, out = _run(["homes"], capsys)
        assert rc == 0
        assert _ident(h) not in out.out
        assert "no homes listed" in out.out

    def test_an_unreadable_list_renders_and_still_exits_0(
            self, capsys, sandboxed_list, monkeypatch):
        """A view never fails on the operator. §4 makes an unreadable list a
        LOUD state (a3 arms on it); it is not an error code here."""
        sandboxed_list.write_text("C:/a\n", encoding="utf-8")

        def denied(*a, **k):
            raise OSError("injected: deny-read ACL")

        monkeypatch.setattr(Path, "read_bytes", denied)
        rc, out = _run(["homes"], capsys)
        assert rc == 0
        assert "unreadable" in out.out

    def test_the_decode_note_and_the_invalid_count_are_surfaced(
            self, capsys, sandboxed_list):
        """§4 asks for a doctor NOTE on the fallback decode. `doctor` wiring is
        not a1's (see the a1 report); the reader produces the note and the view
        is where it is visible today."""
        sandboxed_list.write_bytes(b"C:/\xef\xf0\xee\xe3\xe0\n<<garbage>>\n")
        rc, out = _run(["homes"], capsys)
        assert rc == 0
        assert "UTF-8" in out.out
        assert "1 unparseable" in out.out

    def test_the_view_is_renderable_as_a_string_for_a3s_refusals(
            self, home, sandboxed_list):
        """§5: *"Refusals print facts + the `fleet homes` view"*. a3's
        destructive-tier refusal must be able to EMBED this, so the renderer is
        a pure function and the verb is a thin printer over it. Pinned so a
        later edit cannot dissolve it back into `print()` calls."""
        h = home("h")
        sandboxed_list.write_text(_ident(h) + "\n", encoding="utf-8")
        text = fleet.render_homes_view()
        assert isinstance(text, str)
        assert _ident(h) in text
        assert text.endswith("\n")

    def test_the_view_reads_each_home_exactly_once(
            self, capsys, home, sandboxed_list, monkeypatch):
        """§5.2's contract is *"one lock-free snapshot"* per home, and the cost
        of getting it wrong is not theoretical: resolution becomes O(N-homes)
        where today it is O(1), and no number for N on a real machine exists
        anywhere in this repo (`docs/mf-slice-a-price.md` Risk 3). A renderer
        that re-read each home to count its workers would silently double it."""
        homes = [home(f"h{i}") for i in range(3)]
        sandboxed_list.write_text(
            "".join(_ident(h) + "\n" for h in homes), encoding="utf-8")

        reads = []
        real = fleet.read_registry_at
        monkeypatch.setattr(fleet, "read_registry_at",
                            lambda h: (reads.append(str(h)), real(h))[1])
        fleet.render_homes_view()
        assert sorted(reads) == sorted(_ident(h) for h in homes), (
            f"each listed home must be read exactly once per view; got {reads}")

    def test_the_view_takes_no_lock_and_never_quarantines(
            self, capsys, tmp_path, sandboxed_list, monkeypatch):
        broken = tmp_path / "broken"
        (broken / "state").mkdir(parents=True)
        (broken / "state" / "fleet.json").write_text("{ not json", encoding="utf-8")
        sandboxed_list.write_text(_ident(broken) + "\n", encoding="utf-8")

        def forbidden(*a, **k):                       # pragma: no cover - the point
            raise AssertionError("the homes view took fleet_lock")

        monkeypatch.setattr(fleet, "fleet_lock", forbidden)
        rc, _ = _run(["homes"], capsys)
        assert rc == 0
        assert (broken / "state" / "fleet.json").exists()
        assert not list((broken / "state").glob("fleet.json.corrupt.*"))


# ---------------------------------------------------------------------------
# 2. `--add`
# ---------------------------------------------------------------------------

class TestAdd:
    def test_it_appends_an_initialized_home(self, capsys, home, sandboxed_list):
        h = home("h")
        rc, out = _run(["homes", "--add", str(h)], capsys)
        assert rc == 0
        assert sandboxed_list.read_text(encoding="utf-8") == _ident(h) + "\n"
        assert _ident(h) in out.out

    def test_adding_twice_appends_once(self, capsys, home, sandboxed_list):
        """Append-only forever: a duplicate record is permanent noise, and the
        fold makes it a no-op anyway. Idempotent and rc 0 -- it IS listed, which
        is what the operator asked for."""
        h = home("h")
        _run(["homes", "--add", str(h)], capsys)
        rc, out = _run(["homes", "--add", str(h)], capsys)
        assert rc == 0
        assert "already listed" in out.out
        assert sandboxed_list.read_text(encoding="utf-8").count(_ident(h)) == 1

    def test_re_adding_a_retired_home_appends_a_new_record(
            self, capsys, home, sandboxed_list):
        """§4's `add·retire·add` = member, driven end to end through the verb."""
        h = home("h")
        _run(["homes", "--add", str(h)], capsys)
        _run(["homes", "--retire", str(h)], capsys)
        rc, _ = _run(["homes", "--add", str(h)], capsys)
        assert rc == 0
        assert sandboxed_list.read_text(encoding="utf-8") == (
            f"{_ident(h)}\n!{_ident(h)}\n{_ident(h)}\n")
        assert fleet.read_homes_list()["members"] == [_ident(h)]

    @pytest.mark.parametrize("bad,why", [
        ("relative/home", "not absolute by the grammar"),
        ("C:/fleet/../escape", "contains a `..` segment"),
    ], ids=["relative", "dotdot"])
    def test_it_refuses_what_the_read_grammar_would_reject(
            self, bad, why, capsys, sandboxed_list):
        """The write side applies the READ side's grammar, because append-only
        means a poisoned record cannot be taken back out."""
        rc, out = _run(["homes", "--add", bad], capsys)
        assert rc == 1, why
        assert not sandboxed_list.exists()

    def test_it_refuses_a_path_that_is_not_a_directory(
            self, capsys, tmp_path, sandboxed_list):
        f = tmp_path / "afile"
        f.write_text("x", encoding="utf-8")
        rc, out = _run(["homes", "--add", str(f)], capsys)
        assert rc == 1
        assert not sandboxed_list.exists()

    def test_it_refuses_an_uninitialized_directory_and_names_the_definition(
            self, capsys, tmp_path, sandboxed_list):
        """§5 step 1's validation shape -- *"resolve, `is_dir`, initialized; no
        side-effect `mkdir`"* -- applied to the writer, because a listed home
        that is not initialized is dropped at read time anyway and the operator
        should learn that now rather than from a silently short list."""
        bare = tmp_path / "bare"
        bare.mkdir()
        rc, out = _run(["homes", "--add", str(bare)], capsys)
        assert rc == 1
        assert "not initialized" in out.err
        assert not sandboxed_list.exists()

    def test_a_refused_add_creates_no_directories(self, capsys, tmp_path, sandboxed_list):
        """The no-`mkdir` rule. Validation must not manufacture the thing it is
        validating."""
        ghost = tmp_path / "ghost"
        rc, _ = _run(["homes", "--add", str(ghost)], capsys)
        assert rc == 1
        assert not ghost.exists()
        assert not sandboxed_list.exists()


# ---------------------------------------------------------------------------
# 3. `--retire`
# ---------------------------------------------------------------------------

class TestRetire:
    def test_it_appends_a_retirement_record(self, capsys, home, sandboxed_list):
        h = home("h")
        _run(["homes", "--add", str(h)], capsys)
        rc, out = _run(["homes", "--retire", str(h)], capsys)
        assert rc == 0
        assert sandboxed_list.read_text(encoding="utf-8").endswith(f"!{_ident(h)}\n")
        assert fleet.read_homes_list()["members"] == []

    def test_it_retires_a_home_that_no_longer_exists(
            self, capsys, home, sandboxed_list):
        """THE CASE THAT FORBIDS SYMMETRY WITH `--add`. Retiring is exactly what
        you do to a home you deleted, moved or reformatted -- requiring it to be
        an initialized directory would make the only escape hatch unusable
        precisely when it is needed."""
        h = home("gone")
        _run(["homes", "--add", str(h)], capsys)
        import shutil
        shutil.rmtree(h)

        rc, out = _run(["homes", "--retire", str(h)], capsys)
        assert rc == 0
        assert fleet.read_homes_list()["members"] == []

    def test_retiring_something_not_listed_is_a_no_op_not_an_error(
            self, capsys, sandboxed_list):
        rc, out = _run(["homes", "--retire", "C:/never-listed"], capsys)
        assert rc == 0
        assert "not listed" in out.out
        assert not sandboxed_list.exists(), (
            "a no-op retirement appended a record -- append-only means that "
            "record is permanent")

    def test_it_still_refuses_a_record_the_grammar_rejects(self, capsys, sandboxed_list):
        rc, _ = _run(["homes", "--retire", "relative/home"], capsys)
        assert rc == 1
        assert not sandboxed_list.exists()

    def test_retiring_by_a_different_spelling_still_retires(
            self, capsys, home, sandboxed_list):
        r"""`--add C:/a` then `--retire C:\a\` must fold to one identity, or the
        escape hatch depends on how the operator typed a separator."""
        h = home("h")
        _run(["homes", "--add", str(h)], capsys)
        rc, _ = _run(["homes", "--retire", str(h).replace("/", "\\") + "\\"], capsys)
        assert rc == 0
        assert fleet.read_homes_list()["members"] == []


# ---------------------------------------------------------------------------
# 4. Nothing outside the verb touches the list
# ---------------------------------------------------------------------------

class TestTheRestOfTheCliIsUnchanged:
    def test_the_real_homes_list_is_never_the_one_under_test(self, sandboxed_list):
        assert fleet.homes_list_path() == sandboxed_list != REAL_LIST

    def test_a_machine_with_a_populated_list_still_runs_every_other_verb(
            self, capsys, home, tmp_path, monkeypatch, sandboxed_list):
        """a1 ships the data layer and NOTHING ELSE. Resolution is a2, arming
        and the guard are a3 -- so a machine with two listed homes must behave
        byte-identically to one with none until those land. Driven on `status`,
        the view every surface reads."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path / "mine")
        (tmp_path / "mine" / "state").mkdir(parents=True)

        rc_before, before = _run(["status"], capsys)
        sandboxed_list.write_text(
            f"{_ident(home('one'))}\n{_ident(home('two'))}\n", encoding="utf-8")
        rc_after, after = _run(["status"], capsys)

        assert (rc_before, before.out) == (rc_after, after.out), (
            "a populated homes list changed an unrelated verb's output -- a1 "
            "must not resolve, arm or guard anything")
