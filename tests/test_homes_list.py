"""`~/.claude/fleet-homes.list` -- the homes-list format (multi-fleet §4,
slice a1 deliverable 2).

§4 IS THE WHOLE CONTRACT AND IT IS QUOTED, NOT PARAPHRASED, at each pin:

    Append-only forever (rewrite reading measured 95-100% loss; no-rewrite
    lint). Records: home path, or `!<home path>` retirement; **sequence fold,
    last record wins per identity** -- `add·retire·add` = member. Writers:
    `fleet init --home`, `fleet homes --add`, `fleet homes --retire`; never
    hooks, never dispatch, never session-implicit. Appends via adapter
    `atomic_append_bytes` (precedent `851e15f`, `a4f0079`); read-side verify
    verifies the **folded membership**, not the line. Read grammar: tolerant
    decode (`EF BB BF`/`FF FE`/`FE FF`; no-BOM non-UTF-8 -> `mbcs`/`latin-1` +
    doctor NOTE); absolute by the spec's own grammar (drive-letter/UNC on
    Windows, leading `/` POSIX -- never `os.path.isabs`, floor-divergent); no
    `..`; must name an initialized home at read time (also retires torn
    prefixes). Invalid lines never invalidate others. **Unreadable list =>
    treated as armed-with-unknown-population.**

WHY `os.path.isabs` IS BANNED, MEASURED RATHER THAN INHERITED. The spec calls
it "floor-divergent" without a receipt. Driven on this machine, same inputs,
the two interpreters this repo must both run on::

    py 3.13.12 (nt)  os.path.isabs('/x')  -> False   os.path.isabs('\\x') -> False
    py 3.10.1  (nt)  os.path.isabs('/x')  -> True    os.path.isabs('\\x') -> True

Same string, same OS, opposite answers -- Python 3.13's `ntpath.isabs` requires
a drive AND a root. A homes list read on 3.10 and on 3.13 would disagree about
which of its own records are listable, which means the ARMED POPULATION would
depend on which interpreter happened to run the verb. `posixpath.isabs('C:/x')`
is False on every version, so the same file read on a POSIX box would drop every
Windows home. The grammar below is one function, platform-independent and
version-independent, and `TestTheGrammarIsNotOsPathIsabs` pins both halves.

WHAT THIS FILE DELIBERATELY DOES NOT COVER: arming. §5's arming paragraph
(">=2 distinct homes counting valid AND unreadable", "any indeterminate
population state arms") lands with slice a3 together with the destructive-tier
and arming-indeterminacy pins. a1 exposes the raw material -- per-home state and
an `unreadable` list reason -- and counts nothing.

ISOLATION, AND A GAP THAT IS ESCALATED RATHER THAN ROUTED AROUND.
`tests/conftest.py`'s autouse `_never_touch_the_real_home` says in its own
docstring that *"any new `Path.home()` path added to fleet lands here by
default"*. **That is not true of a new helper**: it monkeypatches THREE helpers
BY NAME (`user_settings_path`, `claude_daemon_lock_path`,
`claude_daemon_log_path`), so `homes_list_path()` is NOT covered by it. Editing
`conftest.py` is outside this lane's fence, so the redirect lives here as an
autouse fixture with a seed (`test_the_redirect_is_actually_in_force`) that fails
loudly if it ever stops applying. §7's "real-list-untouched pin" wants the
conftest half; that is escalated in the a1 report.
"""
import ast
import json
import ntpath
import os.path
import posixpath
import re
import sys
import threading
from pathlib import Path

import pytest

import fleet

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"


@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    """Every test in this file writes to a tmp list, never the operator's.

    See the module docstring: conftest's autouse home sandbox enumerates three
    helpers by name and does not cover this one."""
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


def _write(path, text, encoding="utf-8"):
    path.write_text(text, encoding=encoding)


def _home(root, name, workers=None):
    """A real, INITIALIZED home on disk (§Definitions: `state/fleet.json` that
    parses by the tolerant reader)."""
    h = root / name
    (h / "state").mkdir(parents=True)
    (h / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers or {}}), encoding="utf-8")
    return h


# ---------------------------------------------------------------------------
# 0. The path, and the isolation seed
# ---------------------------------------------------------------------------

class TestThePathAndTheSandbox:
    def test_the_real_path_is_the_one_the_spec_names(self, monkeypatch):
        """`~/.claude/fleet-homes.list`, verbatim from §4. Asserted against the
        UNPATCHED helper, so the sandbox above cannot make this pass."""
        monkeypatch.undo()
        assert fleet.homes_list_path() == Path.home() / ".claude" / "fleet-homes.list"

    def test_the_redirect_is_actually_in_force(self, sandboxed_list):
        """THE SEED. A sandbox is a claim, and this is the only thing that makes
        it a measured one: if the autouse fixture stops applying, every writer
        test in this file starts appending to the developer's real list."""
        assert fleet.homes_list_path() == sandboxed_list
        assert fleet.homes_list_path() != REAL_LIST

    def test_reading_an_absent_list_creates_nothing(self, sandboxed_list):
        """The no-`mkdir` rule again: a machine with no list is a single-fleet
        machine, and asking the question must not make it look otherwise."""
        assert not sandboxed_list.exists()
        out = fleet.read_homes_list()
        assert (out["ok"], out["reason"], out["members"]) == (True, "absent", [])
        assert not sandboxed_list.exists()


# ---------------------------------------------------------------------------
# 1. The absolute-path grammar -- the spec's own, never `os.path.isabs`
# ---------------------------------------------------------------------------

ABSOLUTE = [
    ("drive-backslash", r"C:\fleet"),
    ("drive-forwardslash", "C:/fleet"),
    ("drive-lowercase", "c:/fleet"),
    ("unc-backslash", r"\\server\share\fleet"),
    ("unc-forwardslash", "//server/share/fleet"),
    ("posix-root", "/srv/fleet"),
]

NOT_ABSOLUTE = [
    ("empty", ""),
    ("bare-relative", "fleet"),
    ("dot-relative", "./fleet"),
    ("parent-relative", "../fleet"),
    ("drive-relative-no-root", "C:fleet"),
    ("root-relative-backslash", r"\fleet"),
    ("single-backslash-only", "\\"),
]


class TestTheAbsolutePathGrammar:
    @pytest.mark.parametrize("label,value", ABSOLUTE, ids=[a[0] for a in ABSOLUTE])
    def test_absolute_shapes_are_accepted(self, label, value):
        assert fleet.homes_path_is_absolute(value) is True

    @pytest.mark.parametrize("label,value", NOT_ABSOLUTE, ids=[a[0] for a in NOT_ABSOLUTE])
    def test_relative_and_drive_relative_shapes_are_rejected(self, label, value):
        assert fleet.homes_path_is_absolute(value) is False

    def test_unc_needs_a_server_AND_a_share(self):
        r"""`\\server` alone is not a UNC path, and treating it as one would
        list half a name as a home."""
        assert fleet.homes_path_is_absolute(r"\\server") is False
        assert fleet.homes_path_is_absolute(r"\\server\share") is True


class TestTheGrammarIsNotOsPathIsabs:
    """§4: *"never `os.path.isabs`, floor-divergent"*. MEASURED, both halves."""

    def test_os_path_isabs_really_does_disagree_across_the_two_floors(self):
        """The receipt behind the ban, as an executable claim rather than a
        quoted sentence. `ntpath.isabs` changed in 3.13: a root without a drive
        is no longer absolute. Both interpreters run this file, so whichever one
        is executing, one side of the pair is checked live and the constants are
        checked against the stdlib's own answer."""
        answers = {"3.10": {"/x": True, "\\x": True},
                   "3.13": {"/x": False, "\\x": False}}
        me = "%d.%d" % sys.version_info[:2]
        if me in answers and os.path is ntpath:
            for value, expected in answers[me].items():
                assert os.path.isabs(value) is expected, (
                    f"os.path.isabs({value!r}) on py{me} is no longer "
                    f"{expected} -- re-measure the divergence before citing it")
        # Version-independent half: the two dialects disagree with each other
        # about a Windows home, which is what would drop every listed Windows
        # home the moment this file is read on a POSIX box.
        assert posixpath.isabs("C:/fleet") is False
        assert ntpath.isabs("C:/fleet") is True

    def test_the_grammar_gives_one_answer_on_every_floor_and_platform(self):
        """The whole point of hand-rolling it. These four are the inputs the two
        dialects disagree about; the grammar's answers do not move."""
        assert fleet.homes_path_is_absolute("C:/fleet") is True   # posixpath says no
        assert fleet.homes_path_is_absolute("/srv/fleet") is True  # ntpath 3.13 says no
        assert fleet.homes_path_is_absolute(r"\fleet") is False    # ntpath 3.10 says yes
        assert fleet.homes_path_is_absolute("C:fleet") is False

    # The ONE pre-existing `os.path.isabs` call in `bin/fleet.py`, dispositioned
    # rather than banned. It asks a different question from §4's: given a path
    # `shutil.which` RETURNED, was it absolute -- i.e. is this the implicit
    # curdir-insert hijack (PATHEXT/`.` on PATH)? It is not deciding whether a
    # listed home is listable, so §4's ban does not reach it.
    #
    # NOTE FOR THE RECORD, not a finding this lane acts on: that call sits on
    # the same 3.10/3.13 divergence measured above. For every path
    # `shutil.which` actually returns on Windows (drive + root) the two floors
    # agree, so no behaviour differs today; a POSIX-shaped `/usr/bin/claude`
    # would be "absolute" on 3.10 and not on 3.13, and would then fall through
    # to the cwd-resolution check, which resolves it to nothing and returns
    # False either way. Reported in the a1 report, not changed here.
    ISABS_CALLERS_DISPOSITIONED = {"_resolved_from_current_directory"}

    def test_the_isabs_census_is_unchanged(self):
        """A CENSUS, not a ban, because a blanket ban would forbid a correct
        unrelated use and this project's own recurring defect is an inherited
        enumeration smaller than reality. Every `isabs` call site is derived
        from the AST every run; a new one goes RED and has to be dispositioned
        deliberately, right next to §4's reason for distrusting the function.

        AST rather than substring: the module explains the ban in prose at
        `_HOMES_LIST_ABSOLUTE`, and a grep-shaped lint would make documenting
        the rule the thing that breaks it."""
        tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
        callers = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and (
                        (isinstance(call.func, ast.Attribute) and call.func.attr == "isabs")
                        or (isinstance(call.func, ast.Name) and call.func.id == "isabs")):
                    callers.setdefault(node.name, []).append(call.lineno)
        assert set(callers) == self.ISABS_CALLERS_DISPOSITIONED, (
            f"isabs call sites are {callers}, dispositioned set is "
            f"{sorted(self.ISABS_CALLERS_DISPOSITIONED)}. multi-fleet §4 bans "
            f"it for HOME PATHS by name (floor-divergent; see the measurement "
            f"above). Add the new site here with its reason, or use "
            f"`fleet.homes_path_is_absolute`.")

    def test_no_homes_list_scope_calls_isabs(self):
        """The half of the census that is a hard rule: whatever else in the
        module may ask `isabs`, nothing that touches the homes list may."""
        tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
        homes_symbols = {"homes_list_path", "homes_path_is_absolute",
                         "fold_homes_list", "parse_homes_list_line",
                         "append_home_record", "read_homes_list",
                         "homes_population", "home_identity"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if not (names & homes_symbols):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and (
                        (isinstance(call.func, ast.Attribute) and call.func.attr == "isabs")
                        or (isinstance(call.func, ast.Name) and call.func.id == "isabs")):
                    offenders.append((node.name, call.lineno))
        assert not offenders, offenders

    def test_the_isabs_lint_can_see_a_call(self):
        """THE SEED. The lint above is a negative over a derived set."""
        planted = ast.parse("import os.path\nx = os.path.isabs('/a')\n")
        calls = [n for n in ast.walk(planted)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "isabs"]
        assert len(calls) == 1


class TestNoDotDot:
    """§4: *"no `..`"*. Segment-wise, not substring-wise."""

    @pytest.mark.parametrize("value", [
        "C:/fleet/../other", r"C:\fleet\..\other", "/srv/../etc", "C:/..",
    ])
    def test_a_parent_segment_makes_the_record_invalid(self, value):
        assert fleet.parse_homes_list_line(value)[0] == "invalid"

    @pytest.mark.parametrize("value", ["C:/fleet/..secret", "C:/a..b/fleet"])
    def test_dots_inside_a_segment_are_not_a_parent_segment(self, value):
        assert fleet.parse_homes_list_line(value)[0] == "add"


# ---------------------------------------------------------------------------
# 2. Tolerant decode
# ---------------------------------------------------------------------------

LINE = "C:/fleet-one\n!C:/fleet-two\n"


class TestTolerantDecode:
    def test_plain_utf8_decodes_with_no_note(self, sandboxed_list):
        sandboxed_list.write_bytes(LINE.encode("utf-8"))
        out = fleet.read_homes_list()
        assert out["decode_note"] is None
        assert out["members"] == ["C:/fleet-one"]

    @pytest.mark.parametrize("bom,encoding", [
        (b"\xef\xbb\xbf", "utf-8"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"),
    ], ids=["EF-BB-BF", "FF-FE", "FE-FF"])
    def test_each_bom_the_spec_names_is_decoded(self, bom, encoding, sandboxed_list):
        """§4 names exactly these three byte sequences. A BOM is not a defect,
        so none of them raises a NOTE -- an editor re-saving the file is not an
        incident, it is Tuesday."""
        sandboxed_list.write_bytes(bom + LINE.encode(encoding))
        out = fleet.read_homes_list()
        assert out["members"] == ["C:/fleet-one"], out
        assert out["retired"] == ["C:/fleet-two"]
        assert out["decode_note"] is None

    def test_no_bom_non_utf8_falls_back_and_NOTES_it(self, sandboxed_list):
        """§4: *"no-BOM non-UTF-8 -> `mbcs`/`latin-1` + doctor NOTE"*. The bytes
        below are a legal cp1251 home name and illegal UTF-8."""
        sandboxed_list.write_bytes(b"C:/\xef\xf0\xee\xe3\xe0\n")
        out = fleet.read_homes_list()
        assert out["ok"] is True, "a decodable list is not an unreadable list"
        assert out["decode_note"], "the fallback decode must be reported"
        assert "UTF-8" in out["decode_note"]
        assert len(out["members"]) == 1

    def test_the_fallback_never_raises_on_arbitrary_bytes(self, sandboxed_list):
        """The property that matters more than which codec wins: no byte string
        makes the reader raise. Driven over every single byte value."""
        sandboxed_list.write_bytes(bytes(range(256)) + b"\nC:/fleet-one\n")
        out = fleet.read_homes_list()
        assert out["ok"] is True
        assert "C:/fleet-one" in out["members"]

    def test_crlf_line_endings_are_tolerated(self, sandboxed_list):
        sandboxed_list.write_bytes(b"C:/fleet-one\r\n!C:/fleet-two\r\n")
        out = fleet.read_homes_list()
        assert out["members"] == ["C:/fleet-one"]
        assert out["retired"] == ["C:/fleet-two"]


# ---------------------------------------------------------------------------
# 3. The fold -- last record wins per identity
# ---------------------------------------------------------------------------

class TestTheSequenceFold:
    def test_add_retire_add_is_a_member(self):
        """§4's own worked example, verbatim: *"`add·retire·add` = member"*."""
        out = fleet.fold_homes_list("C:/f\n!C:/f\nC:/f\n")
        assert out["members"] == ["C:/f"]
        assert out["retired"] == []

    def test_add_retire_is_not_a_member(self):
        out = fleet.fold_homes_list("C:/f\n!C:/f\n")
        assert out["members"] == []
        assert out["retired"] == ["C:/f"]

    def test_a_retirement_with_no_prior_add_is_still_a_record(self):
        """It must NOT resurrect the home, and it must not be discarded either
        -- `retire·add` has to be able to re-list it."""
        assert fleet.fold_homes_list("!C:/f\n")["members"] == []
        assert fleet.fold_homes_list("!C:/f\nC:/f\n")["members"] == ["C:/f"]

    def test_homes_fold_independently(self):
        out = fleet.fold_homes_list("C:/a\nC:/b\n!C:/a\nC:/c\n")
        assert out["members"] == ["C:/b", "C:/c"]
        assert out["retired"] == ["C:/a"]

    def test_membership_order_is_first_appearance(self):
        """Stable order, because the view renders it and a list that reshuffles
        on every read is unreadable to an operator diffing two runs."""
        out = fleet.fold_homes_list("C:/b\nC:/a\n!C:/b\nC:/b\n")
        assert out["members"] == ["C:/b", "C:/a"]

    @pytest.mark.parametrize("spelling", [r"C:\f", "C:/f/", r"C:\f\\", "C:/f"])
    def test_separator_and_trailing_slash_spellings_are_ONE_identity(self, spelling):
        """The fold keys on an identity, not on the byte string, or
        `fleet homes --retire C:\\f` would not retire a home added as `C:/f`."""
        assert fleet.fold_homes_list(f"C:/f\n!{spelling}\n")["members"] == []

    def test_case_differing_spellings_are_TWO_identities_deliberately(self):
        """A JUDGEMENT CALL, recorded rather than hidden. §4 does not define
        identity. Case-insensitive equality would need an `os.name` branch,
        which only the PLATFORM adapter may carry (SPEC §14, enforced by a
        source scan) -- and the failure directions are not symmetric: folding
        `C:/f` and `c:/f` together UNDER-counts the population and selects the
        permissive branch, while keeping them apart OVER-counts it and ARMS.
        §5's arming paragraph is explicit that *"indeterminacy never selects the
        permissive branch"*, so this errs the way the spec errs."""
        out = fleet.fold_homes_list("C:/f\n!c:/f\n")
        assert out["members"] == ["C:/f"]
        assert out["retired"] == ["c:/f"]


class TestInvalidLinesNeverInvalidateOthers:
    """§4, verbatim: *"Invalid lines never invalidate others."*"""

    def test_garbage_between_two_good_records_costs_neither(self, sandboxed_list):
        _write(sandboxed_list, "C:/a\n<<<not a path at all>>>\nC:/b\n")
        out = fleet.read_homes_list()
        assert out["members"] == ["C:/a", "C:/b"]
        assert out["invalid_lines"] == 1
        assert out["ok"] is True

    def test_blank_lines_are_skipped_not_counted_invalid(self, sandboxed_list):
        _write(sandboxed_list, "C:/a\n\n   \n\nC:/b\n")
        out = fleet.read_homes_list()
        assert (out["members"], out["invalid_lines"]) == (["C:/a", "C:/b"], 0)

    def test_a_bare_retire_marker_is_invalid_not_a_retirement_of_nothing(self):
        assert fleet.parse_homes_list_line("!")[0] == "invalid"

    def test_a_relative_line_is_invalid_and_isolated(self, sandboxed_list):
        _write(sandboxed_list, "C:/a\n../escape\nfleet\nC:/b\n")
        out = fleet.read_homes_list()
        assert (out["members"], out["invalid_lines"]) == (["C:/a", "C:/b"], 2)


class TestTornPrefixes:
    """§4: *"must name an initialized home at read time (also retires torn
    prefixes)"*. A torn append leaves a PREFIX of a real path, which is
    grammar-valid -- so the grammar cannot catch it and the read-time
    initialized check is what does."""

    def test_a_torn_prefix_is_listed_but_not_an_initialized_home(self, tmp_path, sandboxed_list):
        real = _home(tmp_path, "realhome")
        torn = fleet.home_identity(str(real))[:-3]        # a prefix of a real path
        _write(sandboxed_list, f"{fleet.home_identity(str(real))}\n{torn}\n")

        pop = fleet.homes_population()
        by_path = {h["path"]: h for h in pop["homes"]}
        assert by_path[fleet.home_identity(str(real))]["ok"] is True
        assert by_path[torn]["ok"] is False
        assert by_path[torn]["reason"] == "not_initialized"

    def test_a_line_with_no_trailing_newline_still_folds(self, sandboxed_list):
        """The commonest torn shape of all: the process died between the last
        record's bytes and its newline."""
        sandboxed_list.write_bytes(b"C:/a\nC:/b")
        assert fleet.read_homes_list()["members"] == ["C:/a", "C:/b"]


# ---------------------------------------------------------------------------
# 4. The population -- read-time state per listed home
# ---------------------------------------------------------------------------

class TestThePopulationCarriesEachHomesReadTimeState:
    def test_each_listed_home_reports_its_own_reason(self, tmp_path, sandboxed_list):
        good = _home(tmp_path, "good", {"w1": {"session_id": "s1"}})
        bare = tmp_path / "bare"
        bare.mkdir()
        broken = tmp_path / "broken"
        (broken / "state").mkdir(parents=True)
        (broken / "state" / "fleet.json").write_text("{ not json", encoding="utf-8")

        _write(sandboxed_list, "".join(
            fleet.home_identity(str(p)) + "\n" for p in (good, bare, broken)))

        states = {h["path"].rsplit("/", 1)[-1]: h["reason"]
                  for h in fleet.homes_population()["homes"]}
        assert states == {"good": None, "bare": "not_initialized", "broken": "unreadable"}

    def test_a_retired_home_is_not_in_the_population(self, tmp_path, sandboxed_list):
        good = _home(tmp_path, "good")
        ident = fleet.home_identity(str(good))
        _write(sandboxed_list, f"{ident}\n!{ident}\n")
        assert fleet.homes_population()["homes"] == []

    def test_an_unreadable_list_says_so_and_lists_nothing(self, sandboxed_list, monkeypatch):
        """§4: *"Unreadable list => treated as armed-with-unknown-population"*.
        a1's half of that sentence is the honest REASON; a3 does the arming.
        The distinction that matters here is `unreadable` != `absent`: an absent
        list is a determinate population of zero."""
        sandboxed_list.write_text("C:/a\n", encoding="utf-8")

        def denied(*a, **k):
            raise OSError("injected: deny-read ACL")

        monkeypatch.setattr(Path, "read_bytes", denied)
        out = fleet.homes_population()
        assert (out["ok"], out["reason"]) == (False, "unreadable")
        assert out["homes"] == [] and out["members"] == []

    def test_the_population_read_takes_no_lock(self, tmp_path, sandboxed_list, monkeypatch):
        """One lock-free snapshot per home (§5.2). A lock-taking population read
        would let one wedged foreign fleet stall every verb on the machine."""
        _write(sandboxed_list, fleet.home_identity(str(_home(tmp_path, "h"))) + "\n")

        def forbidden(*a, **k):                       # pragma: no cover - the point
            raise AssertionError("homes_population took fleet_lock")

        monkeypatch.setattr(fleet, "fleet_lock", forbidden)
        assert len(fleet.homes_population()["homes"]) == 1


# ---------------------------------------------------------------------------
# 5. The writer -- append-only, through the adapter, and only through it
# ---------------------------------------------------------------------------

class TestTheWriterIsAppendOnly:
    def test_a_second_record_does_not_replace_the_first(self, sandboxed_list):
        fleet.append_home_record("C:/a")
        fleet.append_home_record("C:/b")
        assert sandboxed_list.read_text(encoding="utf-8") == "C:/a\nC:/b\n"

    def test_a_retirement_is_appended_with_the_bang_prefix(self, sandboxed_list):
        fleet.append_home_record("C:/a")
        fleet.append_home_record("C:/a", retire=True)
        assert sandboxed_list.read_text(encoding="utf-8") == "C:/a\n!C:/a\n"
        assert fleet.read_homes_list()["members"] == []

    def test_it_writes_the_identity_form_not_the_raw_argument(self, sandboxed_list):
        r"""So `--retire C:\a\` retires what `--add C:/a` added. Deliberately
        NOT `Path.resolve()`: resolve() would silently rewrite the operator's
        own path (symlink expansion, drive-letter case) into a spelling they
        never typed, and on Windows it turns a POSIX-shaped record into a
        drive-letter one."""
        fleet.append_home_record("C:\\a\\b\\")
        assert sandboxed_list.read_text(encoding="utf-8") == "C:/a/b\n"

    def test_it_refuses_a_record_the_read_grammar_would_reject(self, sandboxed_list):
        """Append-only forever means a bad record is permanent. The write side
        applies the READ side's grammar so the file cannot be poisoned."""
        for bad in ("relative/path", "C:/a/../b", "", "!"):
            with pytest.raises(fleet.FleetCliError):
                fleet.append_home_record(bad)
        assert not sandboxed_list.exists()

    def test_it_goes_through_the_platform_adapter(self, sandboxed_list, monkeypatch):
        """§4: *"Appends via adapter `atomic_append_bytes`"*. Behavioural, not a
        grep: silence the adapter and nothing reaches disk, which is only true
        if the adapter is the ONLY writer."""
        calls = []
        monkeypatch.setattr(fleet.PLATFORM, "atomic_append_bytes",
                            lambda path, data: calls.append((path, data)))
        fleet.append_home_record("C:/a")
        assert calls == [(sandboxed_list, b"C:/a\n")]
        assert not sandboxed_list.exists(), (
            "a byte reached disk with the adapter silenced -- something else "
            "in append_home_record writes the list")

    def test_the_no_rewrite_lint(self):
        """§4: *"Append-only forever (rewrite reading measured 95-100% loss;
        no-rewrite lint)"*. Derived from the AST rather than listed: any scope
        that mentions `homes_list_path` may not also perform a whole-file write,
        truncate, unlink or rename."""
        tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
        banned = {"write_text", "write_bytes", "unlink", "rename", "replace",
                  "writelines", "truncate"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "homes_list_path" not in names:
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr in banned:
                    offenders.append((node.name, call.func.attr))
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                        and call.func.id == "open":
                    offenders.append((node.name, "open"))
        assert not offenders, (
            f"these scopes touch the homes list and can rewrite it: {offenders}. "
            f"§4 is append-only FOREVER -- a rewrite reading measured 95-100% "
            f"loss. Append through `PLATFORM.atomic_append_bytes` only.")

    def test_the_lint_can_see_a_rewrite(self):
        """THE SEED. The lint above is a negative over a derived set, which is
        the shape that passes vacuously when the derivation rots. Plant the
        exact shape it bans and prove it still says yes."""
        planted = ast.parse(
            "def cmd_homes_bad():\n"
            "    homes_list_path().write_text('C:/a\\n')\n")
        offenders = []
        for node in ast.walk(planted):
            if not isinstance(node, ast.FunctionDef):
                continue
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if "homes_list_path" not in names:
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                        and call.func.attr == "write_text":
                    offenders.append((node.name, "write_text"))
        assert offenders == [("cmd_homes_bad", "write_text")]


class TestWriterContention:
    """§7's writer-contention pin, on the list. The adapter's own docstring
    records the measurement that forced it (`os.open`+`O_APPEND` on Windows lost
    ~17% of records with ZERO decode errors -- silent loss, not corruption), so
    a list built by concurrent writers is exactly the case that must not lose."""

    def test_concurrent_appends_lose_nothing(self, sandboxed_list):
        threads, per = 4, 25
        errors = []

        def writer(tid):
            try:
                for i in range(per):
                    fleet.append_home_record(f"C:/fleet-{tid}-{i}")
            except Exception as exc:                  # pragma: no cover - reported
                errors.append(exc)

        ts = [threading.Thread(target=writer, args=(t,)) for t in range(threads)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        assert not errors, errors
        out = fleet.read_homes_list()
        assert out["invalid_lines"] == 0, "a torn line means an append interleaved"
        assert len(out["members"]) == threads * per, (
            f"expected {threads * per} folded members, got {len(out['members'])} "
            f"-- records were lost or interleaved under contention")


# ---------------------------------------------------------------------------
# 6. Nothing here reads or writes the list implicitly
# ---------------------------------------------------------------------------

class TestNoImplicitReaders:
    def test_only_the_named_writers_append(self):
        """§4: *"Writers: `fleet init --home`, `fleet homes --add`,
        `fleet homes --retire`; never hooks, never dispatch, never
        session-implicit."* `init --home` is slice (b) and does not exist yet, so
        at a1 the only caller of the appender is `cmd_homes`.

        Derived from the AST so a new caller cannot appear quietly."""
        tree = ast.parse(Path(fleet.__file__).read_text(encoding="utf-8"))
        callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                        and call.func.id == "append_home_record":
                    callers.add(node.name)
        assert callers == {"cmd_homes"}, (
            f"`append_home_record` is called from {sorted(callers)}. §4 names "
            f"its writers exhaustively -- never hooks, never dispatch, never "
            f"session-implicit. Add the new writer to this pin deliberately.")

    def test_no_hook_script_mentions_the_homes_list(self):
        """The hooks plane is a separate stdlib-only process family and §4 bans
        it from the list by name."""
        for script in sorted((Path(fleet.__file__).parent / "hooks").glob("*.py")):
            assert "fleet-homes" not in script.read_text(encoding="utf-8"), script
