"""`read_registry_at` -- the path-parameterized tolerant registry reader
(multi-fleet slice a1, deliverable 1).

WHY IT IS NEW WORK RATHER THAN A RENAME OF THE SIBLING. `docs/specs/multi-fleet.md`
M1 says it plainly -- *"the tolerant path-parameterized reader is NEW work -- rs6
C-4 corrects v6's 'zero raises': that property was driven on a round-3 prototype;
the shipped reader raises"*. The shipped sibling is `_read_registry_readonly`
(`bin/fleet.py`), whose except clause reads:

    except (json.JSONDecodeError, UnicodeDecodeError, OSError):

MEASURED ON THIS WORKTREE AT `0ab74ed`, both floors, before a line of production
code was written (transcribed into `state/journals/w43-a1.md`):

    py -3.13  _read_registry_readonly() on a 200000-deep JSON document
              -> RecursionError: maximum recursion depth exceeded
    py -3.10  same input -> RecursionError

`RecursionError` is a `RuntimeError`, `MemoryError` is a `BaseException`-tier
builtin; neither is in that three-tuple, so both escape a function whose own
docstring promises *"Never writes, never quarantines, never raises."*

WHY THAT BOUNDED DEFECT BECOMES AN UNBOUNDED ONE UNDER MULTI-FLEET. Today only
your own home is ever read, so one corrupt registry breaks one machine's own
fleet. §5.2 makes it **one lock-free `read_registry_at` snapshot per LISTED home
on every sid-carrying invocation** -- so a single corrupt (or adversarial)
registry in ANY listed home would take down every verb and every view on the
machine, the statusline included, whose standing rule (root `CLAUDE.md`) is that
it always exits 0.

DELIBERATELY NOT FIXED HERE: `_read_registry_readonly` itself. It is a
view-surface function with its own doctrine and its own caller set; changing it
is a separate decision (escalated in the a1 report, not taken by this lane). What
this file pins is that the NEW function does not INHERIT the defect.

AND THE NON-VACUITY GUARD IS NOT *"the sibling raises"*. A test that asserts
`_read_registry_readonly` raises would go RED the day someone correctly fixes it,
which would make this file an obstacle to the very fix it argues for. So the
fixtures prove their own discriminating power directly: each of the two
known-missed shapes is shown to raise something the shipped three-tuple does NOT
catch (`test_the_bomb_escapes_the_shipped_three_tuple`,
`test_memoryerror_escapes_the_shipped_three_tuple`). That property is what makes
the fixture non-vacuous, and it survives any future fix to the sibling.

THE TWELVE CORRUPTION SHAPES. `docs/specs/multi-fleet.md` M1 calls for *"the
prototype's 12 corruption shapes as its RED-first fixture set"*. That list is NOT
transcribed anywhere in this repo -- `docs/mf-slice-a-price.md` Ambiguity #3 says
so, and a search of the tracked tree confirms it (the round-3 prototype's fixtures
live outside this repo; the round-6/7 reports record only the COUNT plus the two
shapes the sweep missed). **These twelve are RE-DERIVED from scratch, not
recovered**, and they are enumerated in `SHAPES` below with the known-missed pair
marked. Shapes 11 and 12 are the pair rs6 C-4 named.
"""
import json
from pathlib import Path

import pytest

import fleet


# ---------------------------------------------------------------------------
# The twelve shapes, as data. Each entry is (id, writer, expected_reason).
# `writer` takes the registry path and puts the shape on disk (or does not, for
# the absent shape). RE-DERIVED, not recovered -- see the module docstring.
# ---------------------------------------------------------------------------

# 200_000 nesting levels. Measured to raise `RecursionError` out of `json.loads`
# on py 3.13 and py 3.10 alike; `test_the_bomb_escapes_the_shipped_three_tuple`
# is what stops this constant from silently becoming a document that parses.
BOMB_DEPTH = 200_000
RECURSION_BOMB = "[" * BOMB_DEPTH + "]" * BOMB_DEPTH


def _w(text, encoding="utf-8"):
    def write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
    return write


def _wb(raw):
    def write(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return write


def _absent(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def _directory(path):
    path.mkdir(parents=True, exist_ok=True)


SHAPES = [
    #  1. the file was never written -- a directory that is not a fleet home.
    ("absent", _absent, "not_initialized"),
    #  2. zero bytes: a create that never got its content (crash between
    #     open and write).
    ("empty-file", _wb(b""), "unreadable"),
    #  3. torn prefix: a write interrupted mid-document.
    ("torn-prefix", _w('{"workers": {"w1": {"session_id": '), "unreadable"),
    #  4. trailing garbage after a complete document -- an append where a
    #     replace was meant.
    ("trailing-garbage", _w('{"workers": {}}{"workers": {}}'), "unreadable"),
    #  5. not UTF-8 at all: raw bytes no codec accepts as utf-8.
    ("invalid-utf8", _wb(b'{"workers": \xff\xfe\x00}'), "unreadable"),
    #  6. a UTF-8 BOM in front of an otherwise valid document (an editor
    #     "helpfully" re-saved the registry).
    ("utf8-bom", _wb(b"\xef\xbb\xbf" + b'{"workers": {}}'), "unreadable"),
    #  7. valid JSON, but the top level is a scalar/null rather than an object.
    ("top-level-scalar", _w("null"), "unreadable"),
    #  8. valid JSON, top level is an array.
    ("top-level-array", _w('[{"workers": {}}]'), "unreadable"),
    #  9. `workers` present but the wrong TYPE (F2's fuzz finding: setdefault
    #     is a no-op when the key exists with a bad shape).
    ("workers-not-an-object", _w('{"workers": ["w1", "w2"]}'), "unreadable"),
    # 10. `workers` is an object, but its VALUES are not records.
    ("workers-values-not-objects", _w('{"workers": {"w1": "running"}}'), "unreadable"),
    # 11. KNOWN-MISSED PAIR, first half (rs6 C-4): a recursion bomb. Raises
    #     `RecursionError` out of `json.load`, which the shipped sibling's
    #     three-tuple does not catch.
    ("recursion-bomb", _w(RECURSION_BOMB), "unreadable"),
    # 12. KNOWN-MISSED PAIR, second half (rs6 C-4): an oversize document,
    #     which reaches `MemoryError` by the same route. Driven here in two
    #     halves -- a genuinely large (4 MiB) document that must parse rather
    #     than explode, and an INJECTED `MemoryError` for the true
    #     allocation-failure case, which cannot be provoked honestly on a
    #     developer box without exhausting it. See
    #     `test_memoryerror_escapes_the_shipped_three_tuple` and the a1 report:
    #     this half is proven by injection and is REPORTED as such.
    ("oversize-document", _w('{"workers": {"w1": {"note": "'
                             + "x" * (4 * 1024 * 1024) + '"}}}'), None),
]

# Two further shapes driven below that are NOT part of the twelve, recorded so
# the count in the report is honest: `registry-is-a-directory` and an injected
# `OSError` (a deny-read ACL / exclusive handle, which cannot be manufactured
# portably).
EXTRA_SHAPES = [
    ("registry-is-a-directory", _directory, "unreadable"),
]


@pytest.fixture
def home(tmp_path):
    """A bare home DIRECTORY. Deliberately not `FLEET_HOME` -- the whole point
    of this function is that it reads a home it was handed, and a test that went
    through the module global could not tell the two apart."""
    h = tmp_path / "somefleet"
    h.mkdir()
    return h


def _registry(home):
    return home / "state" / "fleet.json"


# ---------------------------------------------------------------------------
# 1. The path parameter is real
# ---------------------------------------------------------------------------

class TestItReadsTheHomeItWasHanded:
    def test_registry_path_at_agrees_with_the_module_global_spelling(
            self, tmp_path, monkeypatch):
        """The parameterized join and `registry_path()` must never disagree --
        two spellings of `state/fleet.json` is how a cross-home read looks at a
        file the single-home path would not have."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        assert fleet.registry_path_at(tmp_path) == fleet.registry_path()

    def test_it_reads_a_foreign_home_not_the_module_global(
            self, home, tmp_path, monkeypatch):
        """The load-bearing property. Point `FLEET_HOME` at a DIFFERENT home
        carrying a DIFFERENT roster and prove the answer came from the argument."""
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path / "mine")
        (tmp_path / "mine" / "state").mkdir(parents=True)
        fleet.registry_path().write_text(
            json.dumps({"workers": {"mine": {"session_id": "s-mine"}}}),
            encoding="utf-8")
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text(
            json.dumps({"workers": {"theirs": {"session_id": "s-theirs"}}}),
            encoding="utf-8")

        ok, reason, data = fleet.read_registry_at(home)
        assert (ok, reason) == (True, None)
        assert list(data["workers"]) == ["theirs"]

    def test_it_accepts_a_string_path_as_well_as_a_Path(self, home):
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")
        assert fleet.read_registry_at(str(home))[0] is True

    def test_a_good_registry_projects_only_workers(self, home):
        """Same projection contract as `_read_registry_readonly`: the third
        value is `{"workers": ...}` and nothing else, so a cross-home reader can
        never be mistaken for a full loader that could be saved back."""
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text(
            json.dumps({"workers": {"w1": {"session_id": "s1"}},
                        "some_future_top_level_key": 7}),
            encoding="utf-8")
        ok, reason, data = fleet.read_registry_at(home)
        assert (ok, reason) == (True, None)
        assert set(data) == {"workers"}


# ---------------------------------------------------------------------------
# 2. The twelve shapes -- none of them may raise
# ---------------------------------------------------------------------------

class TestTheTwelveCorruptionShapes:
    """RE-DERIVED, not recovered (module docstring). Twelve shapes, driven; the
    two rs6 C-4 named as missed by the round-3 sweep are 11 and 12."""

    @pytest.mark.parametrize("shape,writer,expected",
                             SHAPES + EXTRA_SHAPES,
                             ids=[s[0] for s in SHAPES + EXTRA_SHAPES])
    def test_the_shape_never_raises_and_reports_its_reason(
            self, shape, writer, expected, home):
        writer(_registry(home))
        ok, reason, data = fleet.read_registry_at(home)
        if expected is None:                      # the 4 MiB document parses
            assert (ok, reason) == (True, None)
        else:
            assert (ok, reason) == (False, expected), shape
            assert data == {"workers": {}}, (
                f"{shape}: a failed read must still hand back the empty "
                f"projection, never a partial one")

    def test_there_are_exactly_twelve(self):
        """The count is a claim from the spec (`M1`: *"the prototype's 12
        corruption shapes"*) and this file re-derives rather than recovers it,
        so the number is asserted rather than assumed."""
        assert len(SHAPES) == 12
        assert [s[0] for s in SHAPES[10:]] == ["recursion-bomb", "oversize-document"]


# ---------------------------------------------------------------------------
# 3. The known-missed pair, and the proof the fixtures are not vacuous
# ---------------------------------------------------------------------------

SHIPPED_THREE_TUPLE = (json.JSONDecodeError, UnicodeDecodeError, OSError)


class TestTheKnownMissedPair:
    def test_the_bomb_escapes_the_shipped_three_tuple(self):
        """NON-VACUITY, without pinning the sibling's defect.

        `_read_registry_readonly`'s except clause is exactly
        `(json.JSONDecodeError, UnicodeDecodeError, OSError)`. This proves the
        recursion bomb raises something OUTSIDE that tuple -- which is the whole
        reason `read_registry_at` needs a wider one. If a future interpreter
        stopped raising `RecursionError` here, or the bomb became a document
        that merely fails to parse, this goes RED and the fixture is exposed as
        toothless rather than passing quietly."""
        with pytest.raises(RecursionError):
            try:
                json.loads(RECURSION_BOMB)
            except SHIPPED_THREE_TUPLE:            # pragma: no cover - the point
                pytest.fail(
                    "the shipped three-tuple caught the recursion bomb -- this "
                    "fixture no longer discriminates and must be re-derived")

    def test_memoryerror_escapes_the_shipped_three_tuple(self):
        """The second half of the pair, stated honestly: a REAL oversize
        document cannot be driven on a developer box without exhausting it, so
        the allocation failure is injected. What is measured here is the only
        thing that matters for the except clause -- `MemoryError` is not in the
        shipped three-tuple."""
        assert not issubclass(MemoryError, SHIPPED_THREE_TUPLE)
        assert not issubclass(RecursionError, SHIPPED_THREE_TUPLE)

    @pytest.mark.parametrize("boom", [RecursionError, MemoryError])
    def test_a_raise_from_the_parse_is_absorbed(self, boom, home, monkeypatch):
        """Injected at `json.load`, which is where both shapes actually surface.
        This is the assertion that would go RED if someone copied the sibling's
        three-tuple into the new function -- and it covers `MemoryError`, whose
        natural fixture is not manufacturable."""
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")

        def explode(*a, **k):
            raise boom("injected")

        monkeypatch.setattr(fleet.json, "load", explode)
        assert fleet.read_registry_at(home) == (False, "unreadable", {"workers": {}})

    def test_an_OSError_from_the_open_is_absorbed(self, home, monkeypatch):
        """The deny-read ACL / exclusive-handle shape, which also cannot be
        manufactured portably. Recorded as an EXTRA shape, not one of the
        twelve."""
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")

        def explode(*a, **k):
            raise OSError("injected: sharing violation")

        monkeypatch.setattr(fleet, "open", explode, raising=False)
        assert fleet.read_registry_at(home) == (False, "unreadable", {"workers": {}})


# ---------------------------------------------------------------------------
# 4. The reader is a READ -- views doctrine, cross-home edition
# ---------------------------------------------------------------------------

class TestItIsAPureRead:
    def test_it_never_quarantines_a_foreign_registry(self, home):
        """Root `CLAUDE.md`: the rename lives in `load_registry` and nowhere
        else. A cross-home reader that quarantined would rename a file in
        SOMEONE ELSE'S home -- the one thing multi-fleet's own interference
        audit rules out (*"Cross-home writes: none"*)."""
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text("{ not json", encoding="utf-8")
        before = _registry(home).read_bytes()

        assert fleet.read_registry_at(home)[1] == "unreadable"

        assert _registry(home).read_bytes() == before
        assert not list((home / "state").glob("fleet.json.corrupt.*"))

    def test_it_creates_nothing(self, tmp_path):
        """The no-`mkdir` rule (multi-fleet §6 *"binds resolution and read
        paths"*). Handed a home that does not exist at all, it reports and
        touches nothing."""
        ghost = tmp_path / "never-existed"
        assert fleet.read_registry_at(ghost) == (
            False, "not_initialized", {"workers": {}})
        assert not ghost.exists()

    def test_it_does_not_take_the_lock(self, home, monkeypatch):
        """§5.2: *"one lock-free snapshot"* per home. A lock-taking cross-home
        read would let one wedged foreign fleet stall every verb on the box."""
        def forbidden(*a, **k):                    # pragma: no cover - the point
            raise AssertionError("read_registry_at took fleet_lock")

        monkeypatch.setattr(fleet, "fleet_lock", forbidden)
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")
        assert fleet.read_registry_at(home)[0] is True

    def test_it_does_not_call_load_registry(self, home, monkeypatch):
        """`tests/test_load_registry_callers.py` pins WHO may reach the
        quarantining loader by AST. This is the behavioural twin for the one
        function that reads other people's homes."""
        def forbidden(*a, **k):                    # pragma: no cover - the point
            raise AssertionError("read_registry_at called load_registry")

        monkeypatch.setattr(fleet, "load_registry", forbidden)
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")
        assert fleet.read_registry_at(home)[0] is True


# ---------------------------------------------------------------------------
# 5. `quarantined` is distinguishable from `not_initialized`, cross-home
# ---------------------------------------------------------------------------

class TestTheQuarantinedReasonCrossesHomes:
    """P1-13's ambiguity does not stop at the home boundary -- it gets WORSE.
    The rename turns *corrupt* into *absent*, and absent is what a machine that
    never ran `fleet init` looks like. Under multi-fleet that same ambiguity
    decides whether a listed home counts toward the population."""

    def test_an_artifact_makes_the_absence_read_as_quarantined(self, home):
        state = home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json.corrupt.2026-08-05T000000Z").write_text(
            "{ not json", encoding="utf-8")
        assert fleet.read_registry_at(home) == (
            False, "quarantined", {"workers": {}})

    def test_a_bare_absence_still_reads_as_not_initialized(self, home):
        (home / "state").mkdir(parents=True)
        assert fleet.read_registry_at(home)[1] == "not_initialized"

    def test_the_artifact_glob_is_still_spelled_once(self):
        """The parameterized artifact scan must REUSE the one spelling, not add
        a second. `tests/test_identity_quarantine_glob.py::test_the_glob_string_
        is_written_once_in_the_source` counts the literal; this states why the
        cross-home reader is allowed to ask the question at all."""
        src = Path(fleet.__file__).read_text(encoding="utf-8")
        assert src.count('"fleet.json.corrupt.*"') == 1


# ---------------------------------------------------------------------------
# 6. `home_is_initialized` -- the spec's own definition, as code
# ---------------------------------------------------------------------------

class TestHomeIsInitialized:
    """multi-fleet §Definitions, verbatim: *"Initialized home, defined (rs6
    C-3 -- v6 used the term undefined): a directory whose `state/fleet.json`
    exists and parses as a registry by the tolerant reader."*

    Named once here so §4's read-time membership filter, §5 step 1's flag
    validation and the `fleet homes` view cannot drift into three predicates."""

    def test_a_home_with_a_parsing_registry_is_initialized(self, home):
        _registry(home).parent.mkdir(parents=True)
        _registry(home).write_text('{"workers": {}}', encoding="utf-8")
        assert fleet.home_is_initialized(home) is True

    @pytest.mark.parametrize("writer", [_absent, _wb(b""), _w("null")],
                             ids=["absent", "empty", "not-an-object"])
    def test_anything_the_tolerant_reader_rejects_is_not_initialized(
            self, writer, home):
        writer(_registry(home))
        assert fleet.home_is_initialized(home) is False

    def test_a_freshly_init_ed_home_with_no_registry_is_NOT_initialized(self, home):
        """A consequence of the ratified definition, pinned because it is
        surprising: `fleet init` writes `state/worker-settings.json` and does
        NOT create `state/fleet.json` (the registry appears on the first
        `save_registry`). So a home that has been `fleet init`-ed but never
        spawned into does not satisfy §Definitions.

        This is the SPEC's call, not this lane's. It is pinned rather than
        worked around because `init --home` (slice (b)) is the verb whose
        contract is creation, and it is the one that must leave the home
        satisfying this predicate before adding it to the list."""
        (home / "state").mkdir(parents=True)
        (home / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
        assert fleet.home_is_initialized(home) is False
