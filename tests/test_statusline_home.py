"""Multi-fleet slice (d): the statusline resolves its home from the blob sid.

`docs/specs/multi-fleet.md`, the paragraph above §6:

    **Statusline**: blob sid -> same lookup; single-home short-circuit; words,
    exit 0; resolver pure-function; capture experiment gates the slice.
    **Refusals print facts + the `fleet homes` view, never a paste-ready command
    with a chosen home.**

THE GATE, RE-DRIVEN BY THIS LANE. The two blobs below are not synthetic and are
not transcribed from a prior report: they are the VERBATIM bytes of invocation 1
and invocation 13 of a real Claude Code `--bg` session, captured to a file on
2026-08-09 and read back from that file (`docs/lanes/w50-d.md` §1). Two are
embedded rather than one because the FIRST render of a session carries a
strictly smaller key set than every later one -- no `prompt_id`, no
`rate_limits`, three `context_window` fields null -- so a consumer that reads the
blob unguarded works forever after failing exactly once per session, on the one
surface whose failures are swallowed by an exit-0 guard. `session_id` is in the
stable core of both, and these fixtures are what keeps that a measurement rather
than a memory.

WHAT THIS FILE OWES, AND WHAT IT DOES NOT. Slice (d) is the STATUSLINE half.
§5's five-step order, its two refusals, the arming rule and the verb-effect tier
belong to slices a2/a3 and are pinned in `tests/test_home_resolution.py` and
`tests/test_verb_effect_guard.py`; nothing here re-derives them. What is new is
exactly three things -- the blob->sid extractor, the single-home short-circuit,
and the rule that a VIEW renders a word where a verb would refuse -- plus the
proof that reusing `resolve_home()` costs the statusline none of its four
contract points (no lock, no probe, no subprocess, no write; exit 0 always).

ISOLATION. `homes_list_path` is redirected per test -- conftest's autouse home
sandbox enumerates three helpers by name and this is not one of them, so a test
that forgot would append to the operator's real machine-global
`~/.claude/fleet-homes.list`, which is RATIFIED DESTRUCTIVE and which only the
fold reverses. `test_the_real_homes_list_is_untouched_by_this_file` is the belt,
and it compares BYTES rather than existence.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))

import fleet  # noqa: E402
import fleet_statusline as sl  # noqa: E402

REAL_LIST = Path.home() / ".claude" / "fleet-homes.list"
#: The chain file's new home is machine-plane too, so it needs the same belt.
REAL_CHAIN = Path.home() / ".claude" / "fleet-statusline-chain.json"
#: Read ONCE, at import, before any test in this module has run. `None` = absent.
_REAL_LIST_AT_IMPORT = REAL_LIST.read_bytes() if REAL_LIST.exists() else None
_REAL_CHAIN_AT_IMPORT = REAL_CHAIN.read_bytes() if REAL_CHAIN.exists() else None
STATUSLINE_SOURCE = REPO / "bin" / "fleet_statusline.py"

# --- the gate's own bytes, verbatim (see the module docstring) --------------

BLOB_FIRST_RENDER = r'''{"session_id":"d3ebc580-85b8-4b62-8633-40991363c8ce","transcript_path":"C:\\Users\\Techn\\.claude\\projects\\C--Users-Techn-AppData-Local-Temp-w50d-probe\\d3ebc580-85b8-4b62-8633-40991363c8ce.jsonl","cwd":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","session_name":"w50d-probe","model":{"id":"claude-haiku-4-5-20251001","display_name":"Haiku 4.5"},"workspace":{"current_dir":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","project_dir":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","added_dirs":[]},"version":"2.1.226","output_style":{"name":"default"},"cost":{"total_cost_usd":0,"total_duration_ms":1236,"total_api_duration_ms":0,"total_lines_added":0,"total_lines_removed":0},"context_window":{"total_input_tokens":0,"total_output_tokens":0,"context_window_size":200000,"current_usage":null,"used_percentage":null,"remaining_percentage":null},"exceeds_200k_tokens":false,"fast_mode":false,"thinking":{"enabled":true}}
'''

BLOB_LATER_RENDER = r'''{"session_id":"d3ebc580-85b8-4b62-8633-40991363c8ce","transcript_path":"C:\\Users\\Techn\\.claude\\projects\\C--Users-Techn-AppData-Local-Temp-w50d-probe\\d3ebc580-85b8-4b62-8633-40991363c8ce.jsonl","cwd":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","prompt_id":"2b68ead4-48eb-4a9b-a2cd-a374788f0f79","session_name":"w50d-probe","model":{"id":"claude-haiku-4-5-20251001","display_name":"Haiku 4.5"},"workspace":{"current_dir":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","project_dir":"C:\\Users\\Techn\\AppData\\Local\\Temp\\w50d-probe","added_dirs":[]},"version":"2.1.226","output_style":{"name":"default"},"cost":{"total_cost_usd":0.16805900000000001,"total_duration_ms":91515,"total_api_duration_ms":4872,"total_lines_added":0,"total_lines_removed":0},"context_window":{"total_input_tokens":44295,"total_output_tokens":64,"context_window_size":200000,"current_usage":{"input_tokens":8,"output_tokens":64,"cache_creation_input_tokens":44287,"cache_read_input_tokens":0},"used_percentage":22,"remaining_percentage":78},"exceeds_200k_tokens":false,"fast_mode":false,"thinking":{"enabled":true},"rate_limits":{"five_hour":{"used_percentage":7.000000000000001,"resets_at":1786263600},"seven_day":{"used_percentage":75,"resets_at":1786406400}}}
'''

CAPTURED_SID = "d3ebc580-85b8-4b62-8633-40991363c8ce"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    return _ANSI.sub("", text)


# --- fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def sandboxed_list(tmp_path, monkeypatch):
    """Never the operator's real list. See the module docstring."""
    fake = tmp_path / "fake-claude" / "fleet-homes.list"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(fleet, "homes_list_path", lambda: fake)
    return fake


@pytest.fixture
def home(tmp_path):
    """An INITIALIZED home: `state/fleet.json` exists and parses (§Definitions).

    Written directly rather than via `fleet init`, which deliberately does not
    produce one -- the registry appears on the first `save_registry`."""
    def make(name, workers=None):
        h = tmp_path / name
        (h / "state").mkdir(parents=True, exist_ok=True)
        (h / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers or {}}), encoding="utf-8")
        return h
    return make


@pytest.fixture
def bare(tmp_path):
    """A directory that exists and is NOT an initialized home."""
    def make(name="bare"):
        h = tmp_path / name
        h.mkdir(parents=True, exist_ok=True)
        return h
    return make


def worker(sid, status="idle", name="w"):
    return {name: {"session_id": sid, "status": status, "cwd": "C:/x",
                   "last_activity": fleet.now_iso(), "turns": 1, "cost_usd": 0.0}}


@pytest.fixture
def listed(sandboxed_list):
    """Set the SANDBOXED homes list to exactly these members."""
    def add(*homes):
        sandboxed_list.write_text(
            "".join(fleet.home_identity(h) + "\n" for h in homes), encoding="utf-8")
    return add


@pytest.fixture
def at(monkeypatch):
    """Point both planes at one directory -- the shipped single-fleet layout."""
    def go(install, default=None):
        monkeypatch.setattr(fleet, "INSTALL_ROOT", install)
        monkeypatch.setattr(fleet, "FLEET_HOME", default or install)
    return go


@pytest.fixture
def run_main(monkeypatch, capsys):
    """`fleet_statusline.main()` with a blob on stdin. Returns (rc, stdout)."""
    def go(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        rc = sl.main()
        return rc, capsys.readouterr().out
    return go


@pytest.fixture
def no_writes(monkeypatch):
    """ARMED ON DEMAND, never for a whole test.

    A guard that is up while the fixtures build their homes fails on the
    fixture rather than on the code under test, and the fix for that -- letting
    the guard through for `mkdir` -- is exactly the hole it exists to close. So
    it is a context manager: build the world, then arm, then call.
    """
    @contextlib.contextmanager
    def arm():
        real_open = builtins.open

        def guarded_open(file, mode="r", *a, **k):
            if isinstance(mode, str) and any(c in mode for c in "wxa+"):
                raise AssertionError(f"the resolution path opened {file!r} for write")
            return real_open(file, mode, *a, **k)

        def boom(what):
            def go(*a, **k):
                raise AssertionError(f"the resolution path called {what}")
            return go

        with monkeypatch.context() as m:
            m.setattr(builtins, "open", guarded_open)
            m.setattr(io, "open", guarded_open)
            for name in ("write_text", "write_bytes", "mkdir", "rename",
                         "replace", "unlink", "touch", "chmod"):
                m.setattr(Path, name, boom(f"Path.{name}"))
            for name in ("mkdir", "makedirs", "replace", "rename", "remove",
                         "unlink", "rmdir"):
                m.setattr(os, name, boom(f"os.{name}"))
            m.setattr(subprocess, "run", boom("subprocess.run"))
            m.setattr(subprocess, "Popen", boom("subprocess.Popen"))
            m.setattr(fleet, "fleet_lock", boom("fleet_lock"))
            m.setattr(fleet, "save_registry", boom("save_registry"))
            m.setattr(fleet, "load_registry", boom("load_registry"))
            yield
    return arm


# ===========================================================================
# 1. The blob -> sid extractor. A PURE FUNCTION over a raw stdin string.
# ===========================================================================

class TestBlobSessionId:
    def test_the_sid_comes_from_the_session_id_key(self):
        assert sl.blob_session_id(BLOB_LATER_RENDER) == CAPTURED_SID

    def test_the_first_render_of_a_session_carries_it_too(self):
        """The hazard the capture found: the first render has a strictly
        smaller key set. `session_id` is in the stable core, and this is the pin
        that keeps that measured rather than remembered."""
        assert sl.blob_session_id(BLOB_FIRST_RENDER) == CAPTURED_SID

    @pytest.mark.parametrize("payload", [
        "", "   ", "not json at all {{{", "{", '{"session_id":', "\x00\xff"],
        ids=["empty", "blank", "garbage", "truncated", "half-key", "binary"])
    def test_unparseable_input_yields_no_sid(self, payload):
        assert sl.blob_session_id(payload) == ""

    @pytest.mark.parametrize("payload", ["[]", "null", '"a string"', "3", "true"],
                             ids=["list", "null", "str", "int", "bool"])
    def test_a_non_dict_top_level_yields_no_sid(self, payload):
        assert sl.blob_session_id(payload) == ""

    def test_a_missing_session_id_yields_no_sid(self):
        assert sl.blob_session_id('{"cwd":"C:/x","version":"2.1.226"}') == ""

    @pytest.mark.parametrize("value", ["123", "null", "[]", "{}", "false"],
                             ids=["int", "null", "list", "dict", "bool"])
    def test_a_non_string_session_id_yields_no_sid(self, value):
        assert sl.blob_session_id('{"session_id":%s}' % value) == ""

    def test_a_whitespace_only_session_id_yields_no_sid(self):
        assert sl.blob_session_id('{"session_id":"   "}') == ""

    @pytest.mark.parametrize("payload", [None, b"{}", 3, [], {}, object()],
                             ids=["None", "bytes", "int", "list", "dict", "object"])
    def test_it_never_raises_on_a_non_string_payload(self, payload):
        assert sl.blob_session_id(payload) == ""

    def test_it_reaches_no_filesystem_at_all(self, no_writes):
        """The slice's one genuinely new pure function: answerable with no
        session, no home and no registry."""
        with no_writes():
            assert sl.blob_session_id(BLOB_LATER_RENDER) == CAPTURED_SID


# ===========================================================================
# 2. The single-home short-circuit.
#
# NOT A PERFORMANCE FEATURE, and the measurement says so: `lookup_home_for_sid`
# costs 1.35 ms inside a ~560 ms statusline process (w49-dcap §4.1; re-measured
# by this lane, §3 of the report). It exists so a machine with ONE home can
# never render a multi-home word -- neither the terminus nor an ambiguity --
# because §5's arming paragraph binds the whole feature to *"with a determinate
# population of <2: byte-identical to today"*, and a new word under the
# operator's input box is not byte-identical to today.
# ===========================================================================

class TestSingleHomeShortCircuit:
    def test_a_single_home_machine_never_runs_the_lookup(self, home, at, monkeypatch):
        """THE DETECTOR IS A COUNTER, NOT AN EXCEPTION, and that is not a style
        choice -- it is a defect this file already had. A spy that RAISED passed
        under the mutant that deletes the short-circuit, because
        `resolve_blob_home`'s exit-0 guard swallowed the spy's own AssertionError
        and returned the very verdict the test was asserting. A test whose
        detector the production code is contractually obliged to eat proves
        nothing (killed as M1, `docs/lanes/w50-d.md` §6)."""
        at(home("only", worker("sid-x")))
        real, calls = fleet.lookup_home_for_sid, []

        def counting(*a, **k):
            calls.append(a[:1])
            return real(*a, **k)
        monkeypatch.setattr(fleet, "lookup_home_for_sid", counting)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert calls == [], "the lookup ran on a single-home machine"
        assert d["state"] == sl.HOME_SINGLE

    def test_a_single_home_machine_resolves_no_home_and_says_no_word(self, home, at):
        at(home("only", worker("sid-x")))
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_SINGLE
        assert d["home"] is None
        assert sl.render_home_terminus(d, color=False) is None

    def test_the_env_home_still_outranks_a_membership_on_a_single_home_machine(
            self, home, at, monkeypatch, run_main):
        """THE SHORT-CIRCUIT'S ONE OBSERVABLE EFFECT, and the reason it is a
        correctness feature rather than a micro-optimisation.

        §5 step 2 outranks step 3, so WITHOUT the short-circuit a session whose
        sid happens to be claimed by the INSTALL root would drag a
        `$FLEET_HOME`-pointed statusline back to the install and render the
        wrong fleet -- on a machine with one home, where §5's arming paragraph
        requires *"byte-identical to today"*. Today, `$FLEET_HOME` wins."""
        install = home("install", worker(CAPTURED_SID, status="working"))
        data_only = home("data", worker("sid-other", status="dead"))
        at(install, default=data_only)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_SINGLE and d["home"] is None
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        # `no live workers` contains the substring `work`, so the negative half
        # is spelled against the BUCKET (`work 1`), not against a word fragment.
        assert "+1 dead" in out and "work 1" not in out, out

    def test_a_single_home_machine_renders_byte_identically_to_today(
            self, home, at, monkeypatch, run_main):
        """§5's arming paragraph, driven: with slice (d) in place, the line is
        the same bytes the shipped renderer produces on its own."""
        at(home("only", worker("sid-x", status="working")))
        expected = sl.render_statusline(fleet.status_snapshot(), color=False)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert out.strip() == expected.strip()

    def test_the_short_circuit_agrees_with_fleets_own_predicate(
            self, listed, home, at):
        """THE ADAPTER PIN. The short-circuit reads a `resolution_population()`
        record; fleet's `_multi_fleet_population_is_live` reads a
        `lookup_home_for_sid()` one. Two shapes, one question -- so they are
        driven against each other rather than compared by key name."""
        a, b = home("a", worker("sid-a")), home("b", worker("sid-b"))
        at(a)
        for members in ([], [a], [b], [a, b]):
            listed(*members)
            pop = fleet.resolution_population()
            look = fleet.lookup_home_for_sid("sid-a", population=pop)
            assert sl.population_is_multi_home(pop) is \
                fleet._multi_fleet_population_is_live(look), members

    def test_an_unreadable_homes_list_is_multi_home(self, home, at, monkeypatch):
        """§4: an unreadable list is *"armed-with-unknown-population"* --
        indeterminacy never selects the permissive branch."""
        at(home("a"))
        monkeypatch.setattr(fleet, "read_homes_list",
                            lambda: {"path": Path("x"), "ok": False,
                                     "reason": "unreadable", "members": [],
                                     "retired": [], "invalid_lines": 0,
                                     "decode_note": None})
        assert sl.population_is_multi_home(fleet.resolution_population()) is True

    def test_a_second_listed_home_is_multi_home(self, listed, home, at):
        a, b = home("a"), home("b")
        at(a)
        listed(b)
        assert sl.population_is_multi_home(fleet.resolution_population()) is True

    def test_the_legacy_home_alone_is_not_multi_home(self, listed, home, at):
        """A list that names only the install root is a determinate population
        of ONE, however it is spelled."""
        a = home("a")
        at(a)
        listed(a)
        assert sl.population_is_multi_home(fleet.resolution_population()) is False


# ===========================================================================
# 3. `blob sid -> same lookup`.
# ===========================================================================

class TestBlobSidResolvesTheHome:
    def test_the_home_that_claims_the_blob_sid_wins(self, home, listed, at):
        a, b = home("a", worker("sid-a")), home("b", worker(CAPTURED_SID))
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_LOOKUP
        assert fleet.homes_are_same(d["home"], b)

    def test_the_statusline_reads_the_resolved_homes_registry(
            self, home, listed, at, monkeypatch, run_main):
        """THE WHOLE SLICE, END TO END. Home `a` is the install and the default;
        home `b` claims the blob's session. The rendered row describes `b`."""
        a = home("a", worker("sid-a", status="dead", name="in-a"))
        b = home("b", {**worker(CAPTURED_SID, status="working", name="in-b"),
                       **worker("sid-b2", status="working", name="in-b2")})
        at(a)
        listed(a, b)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert "work 2" in out, out
        assert "dead" not in out, out

    def test_the_first_render_resolves_it_too(self, home, listed, at):
        """The smaller key set is not a different design for step 2."""
        a, b = home("a", worker("sid-a")), home("b", worker(CAPTURED_SID))
        at(a)
        listed(a, b)
        assert sl.resolve_blob_home(BLOB_FIRST_RENDER)["state"] == sl.HOME_LOOKUP

    def test_a_retired_sid_still_matches_its_home(self, home, listed, at):
        """Membership is the UNION of `session_id` and `retired_sids`
        (`_record_sids`), and the statusline gets it for free by calling the
        shipped resolver rather than re-spelling the match."""
        a = home("a", worker("sid-a"))
        b = home("b")
        (b / "state" / "fleet.json").write_text(json.dumps({"workers": {
            "w": {"session_id": "fresh-sid", "retired_sids": [CAPTURED_SID],
                  "status": "idle", "cwd": "C:/x",
                  "last_activity": fleet.now_iso()}}}), encoding="utf-8")
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_LOOKUP and fleet.homes_are_same(d["home"], b)

    def test_a_miss_falls_through_to_the_default_home(self, home, listed, at):
        a, b = home("a", worker("sid-a")), home("b", worker("sid-b"))
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_DEFAULT
        assert d["home"] is None
        assert sl.render_home_terminus(d, color=False) is None

    def test_a_blob_with_no_sid_falls_through(self, home, listed, at):
        a, b = home("a", worker(CAPTURED_SID)), home("b")
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home("not json at all")
        assert d["sid"] == ""
        assert d["state"] == sl.HOME_DEFAULT

    def test_the_environment_is_not_a_second_sid_source(
            self, home, listed, at, monkeypatch):
        """`resolve_home(sid=None)` reads `CLAUDE_CODE_SESSION_ID` from the
        environment. Slice (d)'s input is the BLOB, and a blob carrying no sid
        must not be quietly answered by the ambient environment -- one surface,
        one evidence source, or the pure function is not pure.

        This costs nothing today: measured 13/13, the statusline child's
        `CLAUDE_CODE_SESSION_ID` is byte-identical to `blob["session_id"]`
        (`docs/lanes/w50-d.md` §1.2). It is a seam, not a disagreement."""
        a, b = home("a"), home("b", worker(CAPTURED_SID))
        at(a)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", CAPTURED_SID)
        listed(a, b)
        assert sl.resolve_blob_home("{}")["state"] == sl.HOME_DEFAULT, (
            "the environment answered a question the blob did not")


# ===========================================================================
# 4. `words, exit 0` -- what a VIEW does where a verb refuses.
# ===========================================================================

class TestWordsExitZero:
    def test_the_terminus_renders_the_shipped_constant_verbatim(
            self, home, bare, listed, at):
        """§5 step 5: *"views render `[fleet]: no home` and exit 0"*.

        VERBATIM AS THE HEAD, not as the whole line: the fault that caused the
        terminus follows it (section 8), in the same `NO_HOME_LINE -- <why>`
        shape `fleet.resolution_provenance` already uses. A record with no
        `fault` -- which only a hand-built one has -- renders the constant
        alone."""
        empty, b = bare(), home("b", worker("sid-b"))
        at(empty)
        listed(empty, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_NONE
        assert sl.render_home_terminus(d, color=False).startswith(
            fleet.NO_HOME_LINE)
        assert plain(sl.render_home_terminus(d, color=True)) == \
            sl.render_home_terminus(d, color=False)
        assert sl.render_home_terminus({"state": "no_home"}, color=False) == \
            fleet.NO_HOME_LINE

    def test_the_terminus_text_is_not_a_retyped_literal(self):
        """A second spelling is a second place for §5's terminus to drift.
        Docstrings may quote the spec; CODE may not spell the words."""
        tree = ast.parse(STATUSLINE_SOURCE.read_text(encoding="utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docstrings.add(id(body[0].value))
        offenders = [n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and id(n) not in docstrings and "no home" in n.value]
        assert not offenders, (
            f"bin/fleet_statusline.py spells the terminus text itself instead "
            f"of using fleet.NO_HOME_LINE: {offenders}")

    def test_two_homes_claiming_one_session_render_a_word(
            self, home, listed, at, monkeypatch, run_main):
        a, b = home("a", worker(CAPTURED_SID)), home("b", worker(CAPTURED_SID))
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_AMBIGUOUS
        assert d["hits"] == 2
        line = sl.render_home_terminus(d, color=False)
        assert line == "[fleet]: home ambiguous (2)"
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and out.strip() == line

    def test_the_ambiguity_word_names_no_home_and_pastes_no_command(
            self, home, listed, at):
        """§5's refusal contract: *"never a paste-ready command with a chosen
        home"*. On a one-line surface the strongest available form of that rule
        is to name no home at all -- defended in `docs/lanes/w50-d.md` §4."""
        a, b = home("a", worker(CAPTURED_SID)), home("b", worker(CAPTURED_SID))
        at(a)
        listed(a, b)
        line = sl.render_home_terminus(sl.resolve_blob_home(BLOB_LATER_RENDER),
                                       color=False)
        for banned in ("--fleet-home", "FLEET_HOME", str(a), str(b),
                       a.as_posix(), b.as_posix(), "fleet homes"):
            assert banned not in line, f"the one-line refusal leaked {banned!r}"

    @pytest.mark.parametrize("state", ["no_home", "ambiguous"])
    @pytest.mark.parametrize("color", [True, False])
    def test_every_word_is_pure_ascii(self, state, color):
        """A Windows console defaults to cp1252, `print()` raises
        UnicodeEncodeError on a non-ASCII glyph, and the exit-0 guard turns
        that into a permanently BLANK statusline."""
        line = sl.render_home_terminus(
            {"state": state, "hits": 2, "home": None, "sid": ""}, color=color)
        line.encode("ascii")

    def test_the_renderer_tolerates_a_hand_built_record(self):
        """Every other renderer in this file does, for the same reason: unit
        tests hand it dicts, and a view that raises is not a view."""
        assert sl.render_home_terminus({}, color=False) is None
        assert sl.render_home_terminus({"state": "ambiguous"}, color=False)

    def test_main_exits_0_and_still_renders_when_resolution_explodes(
            self, home, at, monkeypatch, run_main):
        """A traceback here renders under the operator's input box on every
        refresh. A resolution that dies costs the fleet row NOTHING."""
        at(home("only", worker("sid-x", status="working")))

        def explode(*a, **k):
            raise RuntimeError("resolution is on fire")
        monkeypatch.setattr(fleet, "resolution_population", explode)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert "work 1" in out, out

    def test_a_resolver_that_explodes_mid_lookup_still_renders(
            self, home, listed, at, monkeypatch, run_main):
        a, b = home("a", worker("sid-a", status="working")), home("b")
        at(a)
        listed(a, b)

        def explode(*a, **k):
            raise RuntimeError("step 2 is on fire")
        monkeypatch.setattr(fleet, "resolve_home", explode)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and "work 1" in out, out

    @pytest.mark.parametrize("payload", [
        "", "   ", "not json", "[]", "null", '{"session_id":123}',
        BLOB_FIRST_RENDER, BLOB_LATER_RENDER],
        ids=["empty", "blank", "garbage", "list", "null", "int-sid",
             "first-render", "later-render"])
    def test_main_returns_0_for_every_blob_shape(
            self, payload, home, at, run_main):
        at(home("only", worker("sid-x")))
        assert run_main(payload)[0] == 0


# ===========================================================================
# 5. D1: no lock, no PID probe, no subprocess, no write -- ON THE NEW PATH.
#
# `resolve_home()` is documented pure and was MEASURED pure for `main()`'s use
# of it. This is a hot path that refires after every assistant message, so the
# property is DRIVEN here rather than inherited.
# ===========================================================================

class TestTheResolutionPathIsAView:
    @pytest.mark.parametrize("shape", ["single", "hit", "miss", "ambiguous",
                                       "terminus"])
    def test_resolution_takes_no_lock_writes_nothing_and_spawns_nothing(
            self, shape, home, bare, listed, at, no_writes):
        a = home("a", worker("sid-a"))
        b = home("b", worker(CAPTURED_SID))
        c = home("c", worker(CAPTURED_SID))
        d = home("d", worker("sid-d"))
        empty = bare()
        install, members = {
            "single": (a, []),
            "hit": (a, [a, b]),
            "miss": (a, [a, d]),
            "ambiguous": (a, [b, c]),
            "terminus": (empty, [empty, d]),
        }[shape]
        listed(*members)
        at(install)
        with no_writes():
            sl.resolve_blob_home(BLOB_LATER_RENDER)   # the fixture is the assertion

    def test_resolution_does_not_quarantine_a_corrupt_registry_in_any_home(
            self, home, listed, at, tmp_path):
        """The rename lives in `load_registry`. A view that reached it would
        shred the operator's evidence once per refresh -- and in every home in
        the population, not just its own."""
        a = home("a", worker("sid-a"))
        rotten = tmp_path / "rotten"
        (rotten / "state").mkdir(parents=True)
        registry = rotten / "state" / "fleet.json"
        registry.write_text("not json at all {{{", encoding="utf-8")
        at(a)
        listed(a, rotten)
        sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert registry.exists(), (
            "the statusline quarantined a corrupt registry in a FOREIGN home")
        assert registry.read_text(encoding="utf-8") == "not json at all {{{"

    def test_an_unreadable_foreign_home_does_not_blank_the_line(
            self, home, listed, at, tmp_path, monkeypatch, run_main):
        a = home("a", worker("sid-a", status="working"))
        rotten = tmp_path / "rotten"
        (rotten / "state").mkdir(parents=True)
        (rotten / "state" / "fleet.json").write_text("{{{", encoding="utf-8")
        at(a)
        listed(a, rotten)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and "work 1" in out, out

    def test_resolution_creates_no_directory_for_a_home_that_does_not_exist(
            self, home, listed, at, tmp_path):
        """§Definitions binds the no-`mkdir` rule to *"resolution and read
        paths"*, and the statusline is both."""
        a = home("a", worker("sid-a"))
        ghost = tmp_path / "never-existed"
        at(a)
        listed(a, ghost)
        sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert not ghost.exists()


# ===========================================================================
# 6. THE TRUST BOUNDARY (gate `w50-gd` BLOCKING 1).
#
# `_run_delegate` runs a chain-file command with `shell=True`. The first draft
# of this slice assigned the resolved home BEFORE `_delegate_rows`, so a home
# that merely appeared in `~/.claude/fleet-homes.list` and claimed a session id
# -- and NOTHING authenticates that claim; session ids are transcript filenames
# -- ran its own shell command in the operator's session every 10 seconds, with
# the rendered line unchanged. The gate demonstrated it end to end.
#
# THE FIX IS THE PLANE, NOT THE COMMAND. `statusline_chain_path()` now names
# `~/.claude/fleet-statusline-chain.json`: the delegate is a MACHINE-scoped fact
# (there is exactly one `statusLine` entry on a machine, and the delegate is
# whatever was in it) and it now lives beside the file it was captured from. A
# resolved home is never consulted for it, so there is nothing to sanitise and
# no ordering to get right. The legacy read below is anchored to the
# PRE-resolution home -- what the pre-slice script would have read -- which is
# operator-controlled by construction.
#
# `docs/reviews/ULTRAREVIEW-2026-07-30.md` examined this same `shell=True` sink
# and REFUTED it, correctly, for the scenario it was raised in: a worker with
# write access to its own FLEET_HOME can already edit `bin/fleet_statusline.py`,
# so the chain file granted it nothing. That reasoning does not reach here --
# a foreign LISTED home has no write access to the operator's install -- and the
# same review dismissed "moving the chain file to the user config dir" on
# exactly the ground that made it useless THERE. It is the fix HERE.
# ===========================================================================

def _delegate_command(script_dir, token, marker=None):
    """A delegate that prints `token` and, if asked, writes `marker` to disk.

    A printed row proves the delegate RAN; a marker file proves it even when the
    row is dropped. Written as a real script file rather than `-c "..."` because
    the command is a SHELL STRING and nested quoting is how
    `TestStatuslineChainRender`'s docstring records this repo losing a test to a
    space in an interpreter path."""
    script = Path(script_dir) / f"delegate_{token}.py"
    body = f"print({token!r})\n"
    if marker is not None:
        body += f"open({str(marker)!r}, 'w').write('RAN')\n"
    script.write_text(body, encoding="utf-8")
    return f"\"{Path(sys.executable).as_posix()}\" \"{script.as_posix()}\""


def _chain_at(path, command):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"delegates": [{"command": command}]}),
                    encoding="utf-8")


class TestAForeignHomeCannotRunACommand:
    def test_the_chain_file_is_on_the_machine_plane(self):
        """Next to the `settings.json` entry it was captured from -- and
        derived from `user_settings_path()` rather than re-spelling
        `Path.home()`, so conftest's autouse home sandbox covers it. A fresh
        `Path.home()` spelling would sit outside that sandbox exactly as
        `homes_list_path` does, and the suite would write the operator's real
        `~/.claude/`."""
        assert fleet.statusline_chain_path() == \
            fleet.user_settings_path().with_name("fleet-statusline-chain.json")

    def test_the_resolved_home_cannot_run_a_command(
            self, home, listed, at, tmp_path, monkeypatch, run_main):
        """THE EXPLOIT, INVERTED INTO A PIN. `homeEVIL` is merely listed and
        claims the blob's session id; the operator's own home does not (an
        ordinary interactive session is claimed by nobody). The marker file is
        the assertion -- a delegate whose row is dropped has still run."""
        good = home("good", worker("sid-good", status="working"))
        evil = home("evil", worker(CAPTURED_SID))
        marker = tmp_path / "EXPLOIT-MARKER"
        _chain_at(evil / "state" / "statusline-chain.json",
                  _delegate_command(tmp_path, "PWNED", marker))
        at(good)
        listed(good, evil)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert not marker.exists(), (
            "a home that merely appears in the homes list and claims a session "
            "id executed a shell command in the operator's session")
        assert "PWNED" not in out, out

    def test_the_operators_own_delegate_runs_from_the_machine_plane(
            self, home, listed, at, tmp_path, monkeypatch, run_main):
        good = home("good", worker("sid-good", status="working"))
        evil = home("evil", worker(CAPTURED_SID))
        _chain_at(fleet.statusline_chain_path(),
                  _delegate_command(tmp_path, "OPERATORS_OWN_ROW"))
        at(good)
        listed(good, evil)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and "OPERATORS_OWN_ROW" in out, out

    def test_the_legacy_home_chain_is_read_from_the_PRE_resolution_home(
            self, home, listed, at, tmp_path, monkeypatch, run_main):
        """MIGRATION, AND THE SECOND HALF OF THE FIX. Every install that ran
        `init --statusline --chain` before today has its delegate in a home. The
        legacy read keeps it working -- but anchored to the home the statusline
        was ALREADY in when it started, which is `$FLEET_HOME` or the install
        root, i.e. exactly what the pre-slice script read. Never the resolved
        one."""
        good = home("good", worker("sid-good", status="working"))
        evil = home("evil", worker(CAPTURED_SID))
        _chain_at(good / "state" / "statusline-chain.json",
                  _delegate_command(tmp_path, "LEGACY_HOME_ROW"))
        _chain_at(evil / "state" / "statusline-chain.json",
                  _delegate_command(tmp_path, "EVIL_HOME_ROW"))
        at(good)
        listed(good, evil)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert "LEGACY_HOME_ROW" in out, out
        assert "EVIL_HOME_ROW" not in out, out

    def test_the_machine_plane_wins_over_the_legacy_home(
            self, home, at, tmp_path, monkeypatch, run_main):
        """One delegate row, not two: the legacy file is a MIGRATION path, so it
        is read only when the machine-plane file says nothing."""
        good = home("good", worker("sid-good", status="working"))
        _chain_at(fleet.statusline_chain_path(),
                  _delegate_command(tmp_path, "MACHINE_ROW"))
        _chain_at(good / "state" / "statusline-chain.json",
                  _delegate_command(tmp_path, "LEGACY_ROW"))
        at(good)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert "MACHINE_ROW" in out and "LEGACY_ROW" not in out, out

    def test_capture_writes_the_machine_plane_and_no_home(
            self, home, at, tmp_path):
        h = home("only")
        at(h)
        fleet._capture_statusline_delegate("pwsh -c my-own-statusline.ps1")
        assert fleet.statusline_chain_path().exists()
        assert json.loads(fleet.statusline_chain_path().read_text(
            encoding="utf-8"))["delegates"][0]["command"] == \
            "pwsh -c my-own-statusline.ps1"
        assert not (h / "state" / "statusline-chain.json").exists()

    def test_a_terminus_does_not_cost_the_operator_their_own_statusline(
            self, home, bare, listed, at, tmp_path, monkeypatch, run_main):
        """Fleet failing to resolve a home is fleet's problem. The delegate is
        the operator's own statusline and must not vanish because fleet is
        lost."""
        empty, b = bare(), home("b", worker("sid-b"))
        _chain_at(fleet.statusline_chain_path(),
                  _delegate_command(tmp_path, "OPERATORS_OWN_ROW"))
        at(empty)
        listed(empty, b)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0
        assert "OPERATORS_OWN_ROW" in out, out
        assert fleet.NO_HOME_LINE in out, out


# ===========================================================================
# 7. WHAT A FOREIGN HOME MAY PUT ON THE OPERATOR'S SCREEN (gate BLOCKING 2).
#
# Two render paths took registry text verbatim: `_LABEL.get(bucket, bucket)`
# falls back to the raw `status` string, and `_reset_clock` returns `str(iso)`
# for any shape it cannot parse. Pre-slice both came from the operator's own
# home; slice (d) can resolve a foreign one, so both became foreign input.
#
# THE OLD PIN COULD NOT SEE IT. `test_the_rendered_line_is_pure_ascii` checks
# the CHARACTER SET, and `ESC` is `0x1b` -- `'\x1b[2K'.isascii()` is `True`. The
# property that matters is that the line carries no terminal CONTROL: no ESC
# outside fleet's own SGR palette, no CR, no BEL, no C0/C1 at all, and a bounded
# length. That is what `assert_no_terminal_control` below asserts, and
# `test_the_control_detector_can_see_an_escape` is why it is not vacuous.
# ===========================================================================

#: Every SGR sequence fleet itself emits. Anything else is not ours.
FLEET_SGR = None  # filled in by _fleet_sgr() at first use


def _fleet_sgr():
    global FLEET_SGR
    if FLEET_SGR is None:
        FLEET_SGR = {sl._RESET, sl._BOLD, sl._GREY, sl._NAME, sl._AGE,
                     sl._SUP, sl._ALARM} | set(sl._STATUS_COLOR.values())
    return FLEET_SGR


_SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def assert_no_terminal_control(line, limit=200):
    """The PROPERTY, not the character set.

    Fleet's own SGR codes are allowed and are checked against the palette by
    VALUE, so an attacker's `\\x1b[1;31m` is not waved through by a regex that
    merely recognises the shape. Everything else -- a bare `\\x1b`, `\\r`,
    `\\x07`, any C0 or C1 byte -- is a finding, and so is an unbounded line."""
    for seq in _SGR_RE.findall(line):
        assert seq in _fleet_sgr(), f"SGR sequence not in fleet's palette: {seq!r}"
    rest = _SGR_RE.sub("", line)
    bad = [(i, ch) for i, ch in enumerate(rest)
           if ord(ch) < 0x20 or 0x7f <= ord(ch) <= 0x9f]
    assert not bad, f"terminal control characters in the rendered line: {bad!r}"
    assert len(rest) <= limit, f"rendered line is {len(rest)} chars: {rest!r}"


HOSTILE_STATUS = {
    "ansi-clear-line": "\x1b[2K\x1b[1;31mFLEET COMPROMISED",
    "ansi-cursor-up": "\x1b[1A\x1b[2K",
    "cr-overwrite": "idle\r[fleet]  all clear",
    "bell-and-long": "\x07" + "X" * 400,
    "osc-title": "\x1b]0;pwned\x07",
    "nul-and-tab": "a\x00b\tc",
    "c1-csi": "\x9b2K",
    "newline": "one\ntwo",
}


class TestAForeignHomeCannotPaintTheOperatorsScreen:
    def test_the_control_detector_can_see_an_escape(self):
        """NON-VACUITY. Without this, a detector that never fires passes every
        test below forever."""
        with pytest.raises(AssertionError):
            assert_no_terminal_control("[fleet]  \x1b[2Kwork 1")
        with pytest.raises(AssertionError):
            assert_no_terminal_control("[fleet]  \x1b[1;31mwork 1")
        with pytest.raises(AssertionError):
            assert_no_terminal_control("[fleet]  work 1\rall clear")
        with pytest.raises(AssertionError):
            assert_no_terminal_control("[fleet]  " + "X" * 500)

    @pytest.mark.parametrize("shape", sorted(HOSTILE_STATUS))
    @pytest.mark.parametrize("color", [True, False])
    def test_a_hostile_status_word_cannot_carry_terminal_control(
            self, shape, color):
        snap = {"ok": True, "workers": [
            {"status": HOSTILE_STATUS[shape], "mail": 0, "stale_seconds": 1,
             "limit_reset_at": None, "resume_eligible": False}], "totals": {}}
        assert_no_terminal_control(sl.render_statusline(snap, color=color))

    @pytest.mark.parametrize("shape", sorted(HOSTILE_STATUS))
    def test_a_hostile_limit_reset_cannot_carry_terminal_control(self, shape):
        snap = {"ok": True, "workers": [
            {"status": "limited", "mail": 0, "stale_seconds": 1,
             "limit_reset_at": HOSTILE_STATUS[shape],
             "resume_eligible": False}], "totals": {}}
        assert_no_terminal_control(sl.render_statusline(snap, color=False))

    def test_a_forged_all_clear_cannot_be_rendered(self):
        """The specific forgery the gate built: a bare CR rewinds the cursor to
        column 0 and the tail overwrites fleet's own row, so the operator's
        statusline reads `[fleet]  all clear` while the fleet is on fire."""
        snap = {"ok": True, "workers": [
            {"status": "idle\r[fleet]  all clear", "mail": 0,
             "stale_seconds": 1, "limit_reset_at": None,
             "resume_eligible": False}], "totals": {}}
        line = sl.render_statusline(snap, color=False)
        assert "\r" not in line, line
        # Two properties, and the second is the one the CR strip alone does not
        # buy: the nameplate appears EXACTLY ONCE, at the head, because foreign
        # text cannot render brackets at all.
        assert line.count(sl.PREFIX) == 1, line
        assert line.startswith(sl.PREFIX), line

    @pytest.mark.parametrize("forgery", [
        "[fleet]  all clear", "[fleet]", "]x[", "[[[fleet]]]"])
    def test_no_foreign_status_can_render_the_nameplate(self, forgery):
        snap = {"ok": True, "workers": [
            {"status": forgery, "mail": 0, "stale_seconds": 1,
             "limit_reset_at": None, "resume_eligible": False}], "totals": {}}
        line = sl.render_statusline(snap, color=False)
        assert line.count(sl.PREFIX) == 1, line
        assert "[" not in line[len(sl.PREFIX):], line

    def test_a_hostile_registry_cannot_make_the_line_unbounded(self):
        """500 distinct hostile statuses. Per-field truncation alone does not
        bound the LINE -- the number of buckets does, and unknown statuses are
        the only attacker-chosen bucket names."""
        snap = {"ok": True, "workers": [
            {"status": f"{'Z' * 300}-{i}", "mail": 0, "stale_seconds": 1,
             "limit_reset_at": None, "resume_eligible": False}
            for i in range(500)], "totals": {}}
        line = sl.render_statusline(snap, color=False)
        assert_no_terminal_control(line)
        assert "unknown" in line, line

    def test_fleets_own_words_are_untouched(self):
        """The sanitiser must not cost the line its own vocabulary."""
        snap = {"ok": True, "workers": [
            {"status": "working", "mail": 0, "stale_seconds": 1,
             "limit_reset_at": None, "resume_eligible": False},
            {"status": "limited", "mail": 0, "stale_seconds": 1,
             "limit_reset_at": "2026-07-09T14:20:00Z", "resume_eligible": False},
            {"status": "dead", "mail": 0, "stale_seconds": 1,
             "limit_reset_at": None, "resume_eligible": False}], "totals": {}}
        line = sl.render_statusline(snap, color=False)
        assert "work 1" in line and "lim 1" in line and "resets 14:20" in line
        assert "+1 dead" in line

    def test_the_terminus_words_carry_no_control_either(
            self, home, bare, listed, at):
        empty, b = bare(), home("b", worker("sid-b"))
        at(empty)
        listed(empty, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        for color in (True, False):
            assert_no_terminal_control(sl.render_home_terminus(d, color=color))


# ===========================================================================
# 8. THE TERMINUS NAMES ITS FAULT (gate MAJOR 1 -- P1-13, re-opened and shut).
#
# P1-13's defect was two DISTINCT registry states rendering the SAME bytes on
# the one surface the operator reads continuously. The first draft of this slice
# re-opened it from the other side: on a multi-home machine all three faults
# reach §5 step 5 (`home_is_initialized` is False for every one of them) and
# rendered a bare `[fleet]: no home`, so an operator with a CORRUPT registry was
# told they had a configuration problem.
#
# The terminus keeps `fleet.NO_HOME_LINE` as its verbatim head -- §5 step 5
# names that line for views -- and appends the fault, in the same
# `NO_HOME_LINE -- <why>` shape `fleet.resolution_provenance` already uses. The
# three faults render three distinct byte sequences, which IS P1-13's property.
# ===========================================================================

class TestTheTerminusNamesItsFault:
    @staticmethod
    def _fault(root, kind):
        state = root / "state"
        state.mkdir(parents=True, exist_ok=True)
        if kind == "absent":
            return root
        if kind == "corrupt":
            (state / "fleet.json").write_text("not json at all {{{",
                                              encoding="utf-8")
        elif kind == "wrongshape":
            (state / "fleet.json").write_text('["a list"]', encoding="utf-8")
        elif kind == "quarantined":
            (state / "fleet.json.corrupt.20260809T000000Z").write_text(
                "{{{", encoding="utf-8")
        return root

    @pytest.mark.parametrize("kind,expected_tail", [
        ("absent", "not initialized"),
        ("corrupt", "registry unreadable"),
        ("wrongshape", "registry unreadable"),
        ("quarantined", "registry quarantined"),
    ])
    def test_the_terminus_names_the_default_homes_fault(
            self, kind, expected_tail, home, listed, at, tmp_path, run_main,
            monkeypatch):
        faulty = self._fault(tmp_path / f"faulty-{kind}", kind)
        b = home("b", worker("sid-b"))
        at(faulty)
        listed(faulty, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_NONE, d
        line = sl.render_home_terminus(d, color=False)
        assert line.startswith(fleet.NO_HOME_LINE), line
        assert line == f"{fleet.NO_HOME_LINE} -- {expected_tail}", line
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and out.strip() == line

    def test_the_three_faults_render_three_distinct_lines(
            self, home, listed, at, tmp_path):
        """P1-13's ACTUAL property, asserted as a property rather than as three
        string literals: distinct states must not render identical bytes."""
        b = home("b", worker("sid-b"))
        seen = {}
        for kind in ("absent", "corrupt", "quarantined"):
            faulty = self._fault(tmp_path / f"p113-{kind}", kind)
            at(faulty)
            listed(faulty, b)
            seen[kind] = sl.render_home_terminus(
                sl.resolve_blob_home(BLOB_LATER_RENDER), color=False)
        assert len(set(seen.values())) == 3, seen

    def test_the_fault_words_are_the_ones_the_roster_render_uses(
            self, home, listed, at, tmp_path):
        """ONE SPELLING. The terminus and `render_statusline` must not describe
        one registry state in two vocabularies -- that is P1-13 with extra
        steps."""
        for reason, snap_reason in (("corrupt", "unreadable"),
                                    ("quarantined", "quarantined"),
                                    ("absent", "not_initialized")):
            roster = sl.render_statusline(
                {"ok": False, "reason": snap_reason, "workers": [], "totals": {}},
                color=False)
            word = roster.split(":", 1)[1].strip()
            faulty = self._fault(tmp_path / f"vocab-{reason}", reason)
            b = home(f"vocab-b-{reason}", worker("sid-b"))
            at(faulty)
            listed(faulty, b)
            line = sl.render_home_terminus(
                sl.resolve_blob_home(BLOB_LATER_RENDER), color=False)
            assert line.endswith(word), (line, word)

    def test_a_single_home_machine_still_renders_the_roster_words(
            self, home, at, tmp_path, monkeypatch, run_main):
        """The short-circuit means none of this reaches a one-home machine: the
        roster's own three words are what render, byte-identically to
        pre-slice."""
        faulty = self._fault(tmp_path / "single-corrupt", "corrupt")
        at(faulty)
        monkeypatch.setenv("NO_COLOR", "1")
        rc, out = run_main(BLOB_LATER_RENDER)
        assert rc == 0 and out.strip() == "[fleet]: registry unreadable", out


# ===========================================================================
# 9. THE GATE'S FIVE SURVIVING MUTANTS (MAJOR 2).
#
# G2, G3, G6, G7, G16 all survived 386 tests. Four of the five live on
# `render_home_terminus`/`_paint_terminus`; the fifth (G3) hard-codes the
# ambiguity count to `2` -- and that count is the ENTIRE informational payload
# of this slice's refusal-clause defence, so a green suite over a lying count
# makes the defence vacuous.
#
# The count is now pinned SEMANTICALLY: a population where the claimant count
# differs from the member count, at >= 3, so `len(hits)`, `len(population)` and
# the literal `2` are three different numbers.
# ===========================================================================

class TestTheAmbiguityCountIsMeasured:
    def test_the_count_is_the_claimant_count_not_the_population(
            self, home, listed, at):
        """FIVE listed homes, THREE of which claim the session. `2` is wrong,
        `5` is wrong, and only `len(look["hits"])` is right."""
        claim = [home(f"c{i}", worker(CAPTURED_SID)) for i in range(3)]
        quiet = [home(f"q{i}", worker(f"sid-q{i}")) for i in range(2)]
        at(quiet[0])
        listed(*(claim + quiet))
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_AMBIGUOUS
        assert d["hits"] == 3, d
        assert sl.render_home_terminus(d, color=False) == \
            "[fleet]: home ambiguous (3)"

    def test_the_count_moves_with_the_claimants(self, home, listed, at):
        """Driven at two sizes, so a constant cannot satisfy both."""
        quiet = home("quiet", worker("sid-q"))
        claim = [home(f"c{i}", worker(CAPTURED_SID)) for i in range(4)]
        at(quiet)
        for n in (2, 3, 4):
            listed(*(claim[:n] + [quiet]))
            d = sl.resolve_blob_home(BLOB_LATER_RENDER)
            assert d["hits"] == n, (n, d)
            assert sl.render_home_terminus(d, color=False).endswith(f"({n})")

    def test_hits_is_populated_on_a_lookup_verdict_too(
            self, home, listed, at):
        """`hits: 0` on a hit is a trap for the next consumer -- the gate's
        §4.7 observation, closed rather than documented."""
        a, b = home("a", worker("sid-a")), home("b", worker(CAPTURED_SID))
        at(a)
        listed(a, b)
        d = sl.resolve_blob_home(BLOB_LATER_RENDER)
        assert d["state"] == sl.HOME_LOOKUP and d["hits"] == 1, d

    def test_a_hand_built_ambiguity_record_never_renders_a_python_value(self):
        """G2. The renderer is tolerant of hand-built records BY CONTRACT; a
        missing count must degrade to a word, never to `(None)`."""
        for record in ({"state": "ambiguous"},
                       {"state": "ambiguous", "hits": None},
                       {"state": "ambiguous", "hits": "two"},
                       {"state": "ambiguous", "hits": 0},
                       {"state": "ambiguous", "hits": 1}):
            line = sl.render_home_terminus(record, color=False)
            assert line == "[fleet]: home ambiguous (?)", (record, line)


class TestThePainterIsPinnedInBothDirections:
    def test_only_the_nameplate_is_painted(self):
        """G6. Painting the whole line survives a `plain()` round-trip, so the
        round-trip cannot be the pin -- the colour BOUNDARY has to be."""
        line = sl.render_home_terminus({"state": "no_home"}, color=True)
        assert line == f"{sl._NAME}[fleet]{sl._RESET}{fleet.NO_HOME_LINE[7:]}"

    def test_color_false_and_color_true_actually_differ(self):
        """G7. A painter that ignores `color` and never paints passed every
        test the branch shipped."""
        plainline = sl.render_home_terminus({"state": "no_home"}, color=False)
        painted = sl.render_home_terminus({"state": "no_home"}, color=True)
        assert plainline == fleet.NO_HOME_LINE
        assert painted != plainline
        assert sl._NAME in painted and sl._RESET in painted
        assert plain(painted) == plainline

    def test_the_ambiguity_word_is_painted_the_same_way(self):
        painted = sl.render_home_terminus({"state": "ambiguous", "hits": 2},
                                          color=True)
        assert painted.startswith(f"{sl._NAME}[fleet]{sl._RESET}")
        assert plain(painted) == "[fleet]: home ambiguous (2)"


# ===========================================================================
# 10. `NEVER RAISES` MADE TRUE (gate MINOR 5).
# ===========================================================================

class TestBlobSessionIdReallyNeverRaises:
    @pytest.mark.parametrize("depth", [200000])
    def test_deeply_nested_json_does_not_raise(self, depth):
        """`json.loads` recurses. `fleet.read_registry_at` catches
        `RecursionError, MemoryError` for exactly this reason and its comment
        calls copying the three-tuple *"the specific mistake this function
        exists to avoid"* -- which is the mistake this function made, one file
        over, in the same wave."""
        assert sl.blob_session_id("[" * depth + "]" * depth) == ""
        assert sl.blob_session_id('{"a":' * depth + "1" + "}" * depth) == ""

    def test_the_except_clause_names_the_two_on_the_end(self):
        """Pinned by AST rather than by behaviour, because the behavioural test
        above depends on this interpreter's recursion limit."""
        tree = ast.parse(STATUSLINE_SOURCE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "blob_session_id")
        caught = set()
        for handler in (h for n in ast.walk(fn) if isinstance(n, ast.Try)
                        for h in n.handlers):
            for name in (handler.type.elts if isinstance(handler.type, ast.Tuple)
                         else [handler.type]):
                if isinstance(name, ast.Name):
                    caught.add(name.id)
        assert {"RecursionError", "MemoryError"} <= caught, caught


# ===========================================================================
# 11. The belt.
# ===========================================================================

def test_the_real_homes_list_is_untouched_by_this_file():
    """`~/.claude/fleet-homes.list` is append-only FOREVER and only the fold
    reverses a record. Compared by BYTES, and ABSENCE IS A STATE: wave 48's
    containment audit came back clean because the file does not exist and the
    lookup population was therefore empty, which is not the same fact as a
    sandbox that held. `None` here means absent, and absent-then-present fails.

    Declared last on purpose -- pytest runs a module's tests in declaration
    order, so every test above has run by the time this compares."""
    now = REAL_LIST.read_bytes() if REAL_LIST.exists() else None
    assert now == _REAL_LIST_AT_IMPORT, (
        f"~/.claude/fleet-homes.list changed during this module: "
        f"{'absent' if _REAL_LIST_AT_IMPORT is None else len(_REAL_LIST_AT_IMPORT)} "
        f"-> {'absent' if now is None else len(now)} bytes")


def test_the_real_machine_plane_chain_file_is_untouched_by_this_file():
    """The chain file moved to `~/.claude/` this wave, so it joins the belt.

    It is derived from `user_settings_path()`, which conftest's autouse home
    sandbox already redirects by name -- that is WHY the derivation is from that
    helper rather than from a fresh `Path.home()`. This proves the inheritance
    actually held rather than assuming it."""
    now = REAL_CHAIN.read_bytes() if REAL_CHAIN.exists() else None
    assert now == _REAL_CHAIN_AT_IMPORT, (
        f"~/.claude/fleet-statusline-chain.json changed during this module: "
        f"{'absent' if _REAL_CHAIN_AT_IMPORT is None else 'present'} "
        f"-> {'absent' if now is None else 'present'}")
