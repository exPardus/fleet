"""Unit tests for `fleet q`, the fleet-index M2 read path (docs/specs/fleet-index.md).

Scope: the CLI contract and index discovery (§11.1), the three query forms and
their short-circuit order (§11.2), the read-path staleness contract (§11.3),
the output format and its 400-line cap (§11.4), the exit-code table and both
failure tables (§11.5), and the concurrency/no-fleet-state posture (§11.6).

Out of scope here, deliberately: §11.7 (the template permissions grant), §11.8
(`compose_prompt` teach lines) and §11.9 (adoption measurement) are the OTHER
M2 slice; nothing in this file touches `worker-settings.template.json` or
`compose_prompt`.

Two disciplines this file holds throughout, both from §11.2/§12:

* Every fixture is written with explicit `\\n` bytes (`_write`), never text-mode
  `write_text`, and every asserted path is a forward-slash string -- so a
  golden that passes here passes byte-identically on POSIX.
* Nothing here touches fleet state (invariant 9): the projects are throwaway
  trees under `tmp_path`, and `TestNoFleetState` asserts that structurally
  rather than by inspection.
"""
import os
import subprocess
from pathlib import Path

import pytest

import fleet


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _write(path, text):
    """Write `text` with LF newlines on every platform, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


# Line numbers are load-bearing in the goldens below, so they are spelled out:
#   L3  VERSION      const     3-3
#   L6  alpha        func      6-9
#   L12 Beta         class     12-17
#   L13 Beta.run     method    13-14
#   L16 Beta.solo    method    16-17
# The comment on L7 and the blank L8 are deliberate: neither appears in any
# shard column, so a `--src` slice that did not come from the FILE cannot
# reproduce them (§11.4, "coordinates from the index, bytes from the file").
API_PY = '''\
"""module docstring"""

VERSION = "1.0"


def alpha(x: int) -> str:
    # a comment that appears in no shard column

    return str(x)


class Beta:
    def run(self, y) -> bool:
        return bool(y)

    def solo(self):
        return 1
'''

#   L1 alpha  func  1-2
#   L5 run    func  5-6
UTIL_PY = """\
def alpha(z):
    return z


def run(q):
    return q
"""

#   L1 gamma  func  1-2
ROOT_PY = """\
def gamma():
    return 0
"""

#   L1 Guide  section  1-7
#   L5 Setup  section  5-7
GUIDE_MD = """\
# Guide

intro

## Setup

steps
"""


def _project(tmp_path, extra=None):
    """A built index over the fixture tree above, plus any `extra` files."""
    root = tmp_path / "proj"
    files = {"src/api.py": API_PY, "src/util.py": UTIL_PY,
             "root.py": ROOT_PY, "docs/guide.md": GUIDE_MD}
    files.update(extra or {})
    for rel, body in files.items():
        _write(root / rel, body)
    assert fleet.main(["index", "init", "--path", str(root)]) == 0
    return root


@pytest.fixture
def proj(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    monkeypatch.chdir(root)
    capsys.readouterr()          # drop the `index init` report
    return root


def _run(capsys, *argv):
    """Run `fleet q ...` and return `(rc, stdout, stderr)`."""
    rc = fleet.main(["q", *argv])
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def _tree(root):
    """Every file under `.fleet-index/` as `{posix-rel: bytes}` -- the
    write-detector for `--no-refresh` (§11.3)."""
    base = fleet.index_dir(root)
    return {p.relative_to(base).as_posix(): p.read_bytes()
            for p in base.rglob("*") if p.is_file()}


def _dir_mtimes(root):
    """Every directory mtime under `.fleet-index/`, including the root itself.

    §12 asks for this specific assertion because a prune shows up as a
    directory mtime change even when no file's bytes moved."""
    base = fleet.index_dir(root)
    return {".": os.stat(base).st_mtime_ns,
            **{p.relative_to(base).as_posix(): os.stat(p).st_mtime_ns
               for p in base.rglob("*") if p.is_dir()}}


# ---------------------------------------------------------------------------
# §11.1 -- CLI contract and index discovery
# ---------------------------------------------------------------------------

class TestIndexDiscovery:
    def test_finds_the_index_by_walking_up_from_a_subdirectory(
            self, proj, monkeypatch, capsys):
        monkeypatch.chdir(proj / "src")
        rc, out, _err = _run(capsys, "gamma")
        # Pointers stay relative to the INDEX ROOT, not to cwd (§11.2).
        assert rc == 0
        assert out.splitlines() == ["root.py:1-2\tfunc\tgamma\t()"]

    def test_no_index_anywhere_exits_3_with_the_shipped_constant(
            self, tmp_path, monkeypatch, capsys):
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(bare)
        rc, out, err = _run(capsys, "alpha")
        assert rc == 3
        assert out == ""
        # The message is specified twice in the spec with different bytes
        # (§6 vs §11.5) and the SHIPPED constant is the one that must be
        # asserted -- never a literal, or this test pins the wrong spelling.
        assert fleet.INDEX_NO_INDEX_MESSAGE in err

    def test_a_nested_worktree_without_its_own_index_exits_3(
            self, proj, tmp_path, monkeypatch, capsys):
        # §11.1's named correctness hazard. The nested worktree's `.git` is a
        # FILE (that is what a linked worktree has), and without the boundary
        # stop the walk-up would resolve the PARENT's `.fleet-index/`, whose
        # staleness checks pass against the PARENT's files -- silently wrong
        # slices for a tree on a different branch, and a refresh writing into
        # the parent's index from inside a fenced worktree.
        nested = proj / ".claude" / "worktrees" / "x"
        nested.mkdir(parents=True)
        _write(nested / ".git", "gitdir: /elsewhere/.git/worktrees/x\n")
        _write(nested / "src" / "api.py", API_PY)
        monkeypatch.chdir(nested / "src")
        rc, out, err = _run(capsys, "alpha")
        assert rc == 3
        assert out == ""
        assert fleet.INDEX_NO_INDEX_MESSAGE in err
        # And nothing was written into the parent's index on the way past.
        assert fleet.find_index_root(nested / "src") is None

    def test_a_boundary_directory_with_its_own_index_still_answers(
            self, proj, monkeypatch, capsys):
        # The boundary rule stops the walk; it does not disable an index that
        # sits ON the boundary. `proj` is where a real repo root would be.
        _write(proj / ".git" / "HEAD", "ref: refs/heads/main\n")
        monkeypatch.chdir(proj / "src")
        rc, _out, _err = _run(capsys, "gamma")
        assert rc == 0


class TestUsageErrors:
    """§11.5 row 2: usage errors are argparse's, and argparse exits 2."""

    @pytest.mark.parametrize("argv", [
        [],                                        # neither query nor --outline
        ["alpha", "--outline", "src/api.py"],      # both forms at once
        ["--outline", "src/api.py", "--src"],      # --src is not an outline flag
        ["--outline", "src/api.py", "--kind", "func"],
        ["--outline", "src/api.py", "--path", "src/*"],
        ["--outline", "src/api.py", "--limit", "3"],
        ["alpha", "--kind", "nosuchkind"],
        ["alpha", "--limit", "notanumber"],
    ])
    def test_exit_2(self, proj, capsys, argv):
        with pytest.raises(SystemExit) as excinfo:
            fleet.main(["q", *argv])
        assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# §11.2 -- query semantics and the short-circuit order
# ---------------------------------------------------------------------------

class TestQueryForms:
    def test_exact_match_is_the_first_form(self, proj, capsys):
        rc, out, err = _run(capsys, "alpha")
        assert rc == 0
        assert err == ""
        # Sorted by source path then line (§11.2).
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str",
            "src/util.py:1-2\tfunc\talpha\t(z)",
        ]

    def test_an_exact_hit_short_circuits_the_dotted_tail_tier(self, proj, capsys):
        # §11.2's own worked example: `q run` returns ONLY the top-level `run`.
        # `Beta.run` is a tail-tier hit and the tiers never mix in one result.
        rc, out, _err = _run(capsys, "run")
        assert rc == 0
        assert out.splitlines() == ["src/util.py:5-6\tfunc\trun\t(q)"]
        assert "Beta.run" not in out

    def test_the_tail_tier_runs_only_when_the_exact_tier_is_empty(self, proj, capsys):
        rc, out, _err = _run(capsys, "solo")
        assert rc == 0
        assert out.splitlines() == ["src/api.py:16-17\tmethod\tBeta.solo\t(self)"]

    def test_a_qualified_query_reaches_the_shadowed_method(self, proj, capsys):
        rc, out, _err = _run(capsys, "Beta.run")
        assert rc == 0
        assert out.splitlines() == ["src/api.py:13-14\tmethod\tBeta.run\t(self, y) -> bool"]

    def test_a_dotted_query_never_tail_matches(self, proj, capsys):
        # The tail form is defined only for a query with no `.` (§11.2), so a
        # dotted query that misses exactly is a miss, not a suffix search.
        rc, _out, _err = _run(capsys, "Gamma.run")
        assert rc == 1

    def test_glob_form_skips_forms_1_and_2(self, proj, capsys):
        rc, out, _err = _run(capsys, "Beta.*")
        assert rc == 0
        assert out.splitlines() == [
            "src/api.py:13-14\tmethod\tBeta.run\t(self, y) -> bool",
            "src/api.py:16-17\tmethod\tBeta.solo\t(self)",
        ]

    def test_matching_is_case_sensitive_on_every_platform(self, proj, capsys):
        # `fnmatchcase`, not `fnmatch`: the latter case-folds via
        # `os.path.normcase` on win32, so `beta.*` would match `Beta.run` on
        # Windows and not on Linux -- the one difference §11.2 pins against.
        assert _run(capsys, "beta.*")[0] == 1
        assert _run(capsys, "ALPHA")[0] == 1
        assert _run(capsys, "Alpha")[0] == 1

    def test_a_glob_matching_nothing_is_exit_1(self, proj, capsys):
        rc, out, err = _run(capsys, "zzz*")
        assert rc == 1
        assert out == ""
        assert "grep -r" in err

    def test_no_match_suggests_grep_over_the_shard_tree_then_the_repo(
            self, proj, capsys):
        rc, out, err = _run(capsys, "nosuch")
        assert rc == 1
        assert out == ""
        assert "grep -r nosuch .fleet-index/symbols/" in err


class TestFilters:
    def test_kind_filter_restricts_the_result(self, proj, capsys):
        assert _run(capsys, "alpha", "--kind", "class")[0] == 1
        rc, out, _err = _run(capsys, "Beta", "--kind", "class")
        assert rc == 0
        assert out.splitlines() == ["src/api.py:12-17\tclass\tBeta\t"]

    def test_kind_section_reaches_markdown_headings(self, proj, capsys):
        rc, out, _err = _run(capsys, "Setup", "--kind", "section")
        assert rc == 0
        assert out.splitlines() == ["docs/guide.md:5-7\tsection\tSetup\t"]

    def test_path_filter_restricts_the_result(self, proj, capsys):
        rc, out, _err = _run(capsys, "alpha", "--path", "src/util.py")
        assert rc == 0
        assert out.splitlines() == ["src/util.py:1-2\tfunc\talpha\t(z)"]

    def test_path_glob_is_the_double_star_dialect_not_fnmatch(self, proj, capsys):
        # THE dialect decision (see the module note in bin/fleet.py): `--path`
        # speaks the same `**`-aware, case-sensitive glob as the include and
        # exclude lists in `.fleet-index/config.toml`, because both are globs
        # over the same forward-slash source-relative path space and a worker
        # reads the dialect out of that config file.
        #
        # A single `*` does NOT cross `/`, so `*.py` is root-level only...
        rc, out, _err = _run(capsys, "alpha", "--path", "*.py")
        assert rc == 1                       # neither alpha is at the root
        rc, out, _err = _run(capsys, "gamma", "--path", "*.py")
        assert (rc, out.splitlines()) == (0, ["root.py:1-2\tfunc\tgamma\t()"])
        # ...and `**/*.py` matches at ANY depth, root included -- which is
        # exactly what `fnmatch.fnmatchcase` gets backwards on both counts.
        rc, out, _err = _run(capsys, "alpha", "--path", "**/*.py")
        assert rc == 0
        assert len(out.splitlines()) == 2
        rc, out, _err = _run(capsys, "gamma", "--path", "**/*.py")
        assert (rc, out.splitlines()) == (0, ["root.py:1-2\tfunc\tgamma\t()"])

    def test_path_glob_is_case_sensitive_on_every_platform(self, proj, capsys):
        assert _run(capsys, "alpha", "--path", "SRC/*.py")[0] == 1

    def test_a_path_glob_that_selects_no_shard_says_so(self, proj, capsys):
        rc, _out, err = _run(capsys, "alpha", "--path", "nowhere/*.py")
        assert rc == 1
        assert "--path" in err and "matched no indexed file" in err


class TestLimit:
    def test_default_limit_is_20_and_truncation_is_still_exit_0(
            self, tmp_path, monkeypatch, capsys):
        body = "".join(f"def sym{n:03d}():\n    return {n}\n\n\n" for n in range(25))
        root = _project(tmp_path, {"many.py": body})
        monkeypatch.chdir(root)
        capsys.readouterr()
        rc, out, err = _run(capsys, "sym*")
        assert rc == 0
        assert len(out.splitlines()) == 20
        assert "5" in err and "--path" in err and "--kind" in err

    def test_an_explicit_limit_is_honoured(self, proj, capsys):
        rc, out, err = _run(capsys, "Beta.*", "--limit", "1")
        assert rc == 0
        assert out.splitlines() == ["src/api.py:13-14\tmethod\tBeta.run\t(self, y) -> bool"]
        assert "1" in err


# ---------------------------------------------------------------------------
# §11.4 -- output format
# ---------------------------------------------------------------------------

class TestOutputFormat:
    def test_pointer_paths_use_forward_slashes_on_every_platform(
            self, proj, capsys):
        rc, out, _err = _run(capsys, "alpha", "--path", "src/api.py")
        assert rc == 0
        assert out == "src/api.py:6-9\tfunc\talpha\t(x: int) -> str\n"
        assert "\\" not in out

    def test_src_slices_the_file_verbatim(self, proj, capsys):
        rc, out, err = _run(capsys, "alpha", "--src", "--path", "src/api.py")
        assert rc == 0
        assert err == ""
        # Coordinates from the index, BYTES FROM THE FILE (§11.4): the comment
        # and the blank line below exist in no shard column, so this golden
        # cannot be satisfied by anything the index knows.
        assert out == (
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str\n"
            "def alpha(x: int) -> str:\n"
            "    # a comment that appears in no shard column\n"
            "\n"
            "    return str(x)\n"
        )

    def test_the_slice_is_byte_exact_against_the_source_file(self, proj, capsys):
        rc, out, _err = _run(capsys, "Beta", "--src", "--kind", "class")
        assert rc == 0
        source = (proj / "src" / "api.py").read_bytes().decode("utf-8")
        expected = "".join(f"{line}\n" for line in source.split("\n")[11:17])
        assert out.split("\n", 1)[1] == expected

    def test_a_multi_hit_src_prints_pointers_and_exits_1(self, proj, capsys):
        rc, out, err = _run(capsys, "alpha", "--src")
        assert rc == 1
        # Pointers, never concatenated source -- a token blowout in the exact
        # place this tool exists to prevent one (§11.4).
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str",
            "src/util.py:1-2\tfunc\talpha\t(z)",
        ]
        assert "ambiguous" in err
        assert "--path" in err and "--kind" in err

    def test_limit_cannot_silence_a_src_ambiguity(self, proj, capsys):
        # §11.4 says `--src` must resolve to exactly one symbol AFTER FILTERS,
        # and `--limit` is not a filter -- it caps what is printed. Testing
        # ambiguity against the limited list instead of the full one would let
        # `--limit 1` turn a two-hit query into a confident wrong slice, which
        # is the failure this whole tool exists to prevent. Found by fault
        # injection: the first version of these tests missed it entirely.
        rc, out, err = _run(capsys, "alpha", "--src", "--limit", "1")
        assert rc == 1
        assert "ambiguous" in err
        # Pointers only -- not one line of source.
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str"]
        assert "def alpha" not in out

    def test_an_unreadable_source_at_slice_time_degrades_to_the_pointer(
            self, proj, monkeypatch, capsys):
        # §11.5's "unreadable source at slice time" row: readable when the
        # header was hashed, gone by the time the slice is read.
        def boom(_path):
            raise OSError("vanished mid-slice")

        monkeypatch.setattr(fleet, "_q_source_lines", boom)
        rc, out, err = _run(capsys, "alpha", "--src", "--path", "src/api.py")
        assert rc == 0
        assert out == "src/api.py:6-9\tfunc\talpha\t(x: int) -> str\n"
        assert "src/api.py" in err

    def test_the_same_row_against_a_REAL_unreadable_file(
            self, proj, monkeypatch, capsys):
        # The test above REPLACES `_q_source_lines`, so it pins the caller's
        # handling and nothing about the function itself. Measured: injecting
        # `except OSError: return []` into the real `_q_source_lines` left the
        # whole suite GREEN -- §11.5's unreadable-source row had no test that
        # touched the real read at all. This one does.
        #
        # The seam is `_q_pointer`, and it is used ONLY as a clock: it is the
        # last thing `_q_print_slice` does before reading the file, so
        # swapping the source out there reproduces §11.5's actual timing
        # ("readable when the header was hashed, unreadable by the time the
        # slice was read") while leaving the function under test REAL. A
        # directory in the file's slot is the portable way to be unreadable --
        # `IsADirectoryError` on POSIX, `PermissionError` on win32, `OSError`
        # on both -- with no permission bits to restore afterwards.
        real_pointer = fleet._q_pointer
        target = proj / "src" / "api.py"

        def swap_then_format(hit):
            if target.is_file():
                target.unlink()
                target.mkdir()
            return real_pointer(hit)

        monkeypatch.setattr(fleet, "_q_pointer", swap_then_format)
        rc, out, err = _run(capsys, "alpha", "--src", "--path", "src/api.py")
        assert rc == 0                       # a hit WAS printed
        assert out == "src/api.py:6-9\tfunc\talpha\t(x: int) -> str\n"
        assert "src/api.py: source unreadable at slice time" in err
        assert "pointer only, no slice" in err

    def test_q_source_lines_really_raises_on_an_unreadable_path(self, proj):
        # And the primitive itself, with no CLI around it: the `except OSError`
        # in `_q_print_slice` is only a contract if this actually raises.
        with pytest.raises(OSError):
            fleet._q_source_lines(proj / "src")            # a directory
        with pytest.raises(OSError):
            fleet._q_source_lines(proj / "no" / "such" / "file.py")


class TestOutputCap:
    """§11.4's 400-line cap, its exact trailer, and its unchanged exit code."""

    def test_a_long_src_slice_is_capped_with_the_trailer(
            self, tmp_path, monkeypatch, capsys):
        # `huge` spans lines 1..450, so 50 lines are suppressed.
        body = "def huge():\n" + "    x = 0\n" * 448 + "    return x\n"
        root = _project(tmp_path, {"big.py": body})
        monkeypatch.chdir(root)
        capsys.readouterr()
        rc, out, err = _run(capsys, "huge", "--src")
        assert rc == 0                     # truncation is not an error
        assert err == ""
        lines = out.splitlines()
        assert lines[0] == "big.py:1-450\tfunc\thuge\t()"
        assert len(lines) == 1 + fleet.Q_OUTPUT_LINE_CAP + 1
        assert lines[1] == "def huge():"
        assert lines[-1] == fleet.Q_TRUNCATION_TRAILER.format(n=50)
        assert lines[-1] == "[truncated 50 lines — narrow the query]"

    def test_a_slice_of_exactly_the_cap_gets_no_trailer(
            self, tmp_path, monkeypatch, capsys):
        body = "def exact():\n" + "    x = 0\n" * 398 + "    return x\n"
        root = _project(tmp_path, {"big.py": body})
        monkeypatch.chdir(root)
        capsys.readouterr()
        rc, out, _err = _run(capsys, "exact", "--src")
        assert rc == 0
        assert len(out.splitlines()) == 1 + fleet.Q_OUTPUT_LINE_CAP
        assert "truncated" not in out

    def test_a_long_outline_is_capped_with_the_trailer(
            self, tmp_path, monkeypatch, capsys):
        body = "".join(f"K{n:03d} = {n}\n" for n in range(500))
        root = _project(tmp_path, {"many.py": body})
        monkeypatch.chdir(root)
        capsys.readouterr()
        rc, out, err = _run(capsys, "--outline", "many.py")
        assert rc == 0
        assert err == ""
        lines = out.splitlines()
        # The cap applies to the RENDERING (§11.4), header line included:
        # 1 header + 500 bullets = 501, so 101 are suppressed.
        assert len(lines) == fleet.Q_OUTPUT_LINE_CAP + 1
        assert lines[0] == "## many.py (500 lines, python)"
        assert lines[-1] == "[truncated 101 lines — narrow the query]"

    def test_the_two_capped_paths_disagree_about_the_identity_line(
            self, tmp_path, monkeypatch, capsys):
        """The cap admits a different amount of PAYLOAD on each path.

        `--src` prints its pointer OUTSIDE `_q_print_capped`, so a capped slice
        is `1 pointer + 400 body + trailer` = 402 stdout lines. `--outline`
        feeds the whole rendering THROUGH the cap, header included, so a capped
        outline is `1 header + 399 rows + trailer` = 401. Both satisfy §11.4
        read literally -- the slice is 400 lines, the rendering is 400 lines --
        but "the cap" buys a worker 400 body lines on one path and 399 on the
        other, and nothing in the tree said so.

        Measured here rather than repaired: aligning them means changing which
        §12-pinned golden is right about what §11.4's 400 counts, and that is a
        spec decision, not a bug fix. Pinned so the asymmetry is a recorded
        choice instead of an accident, and so the numbers stop being
        mis-quoted -- an earlier report gave 401/400, having not counted the
        trailer that `_q_print_capped` always emits. NOTHING IS LOST SILENTLY
        on either path; this is a consistency defect only."""
        src_root = _project(tmp_path / "s", {
            "big.py": "def huge():\n" + "    x = 0\n" * 448 + "    return x\n"})
        monkeypatch.chdir(src_root)
        capsys.readouterr()
        _rc, src_out, _err = _run(capsys, "huge", "--src")

        outline_root = _project(tmp_path / "o", {
            "many.py": "".join(f"K{n:03d} = {n}\n" for n in range(500))})
        monkeypatch.chdir(outline_root)
        capsys.readouterr()
        _rc, outline_out, _err = _run(capsys, "--outline", "many.py")

        src, outline = src_out.splitlines(), outline_out.splitlines()
        assert (len(src), len(outline)) == (402, 401)
        assert "truncated" in src[-1] and "truncated" in outline[-1]
        # The asymmetry stated as the thing it is: body lines delivered.
        assert len(src) - 2 == fleet.Q_OUTPUT_LINE_CAP          # 400 body lines
        assert len(outline) - 2 == fleet.Q_OUTPUT_LINE_CAP - 1  # 399 rows


# ---------------------------------------------------------------------------
# §11.1/§11.5 -- --outline
# ---------------------------------------------------------------------------

class TestOutline:
    def test_renders_the_digest_of_one_file(self, proj, capsys):
        rc, out, err = _run(capsys, "--outline", "docs/guide.md")
        assert rc == 0
        assert err == ""
        assert out == ("## docs/guide.md (7 lines, markdown)\n"
                       "- L1 Guide\n"
                       "- L5 Setup\n")

    def test_it_is_the_same_rendering_context_injects(self, proj, capsys):
        rc, out, _err = _run(capsys, "--outline", "src/api.py")
        assert rc == 0
        result = fleet.verified_shard_rows(proj, "src/api.py")
        assert out == fleet.render_digest("src/api.py", result["header"],
                                          result["rows"])

    def test_a_path_relative_to_the_cwd_resolves(self, proj, monkeypatch, capsys):
        monkeypatch.chdir(proj / "src")
        rc, out, _err = _run(capsys, "--outline", "api.py")
        assert rc == 0
        assert out.splitlines()[0] == "## src/api.py (17 lines, python)"

    def test_an_unknown_path_exits_1_with_a_basename_candidate_list(
            self, proj, capsys):
        rc, out, err = _run(capsys, "--outline", "api.py")
        assert rc == 1
        assert out == ""
        assert "src/api.py" in err

    def test_an_unknown_path_with_no_candidates_still_exits_1(self, proj, capsys):
        rc, out, err = _run(capsys, "--outline", "nowhere/absent.py")
        assert rc == 1
        assert out == ""
        assert "nowhere/absent.py" in err

    def test_a_header_only_shard_is_an_empty_outline_and_exit_0(
            self, tmp_path, monkeypatch, capsys):
        # §11.5: having no symbols is a fact about the file, not a failure.
        root = _project(tmp_path, {"broken.py": "def (:\n"})
        monkeypatch.chdir(root)
        capsys.readouterr()
        rc, out, err = _run(capsys, "--outline", "broken.py")
        assert rc == 0
        assert err == ""
        assert out == "## broken.py (1 lines, python)\n"

    def test_a_stale_shard_is_refreshed_then_answered(self, proj, capsys):
        _write(proj / "docs" / "guide.md", "# Renamed\n\nbody\n")
        rc, out, _err = _run(capsys, "--outline", "docs/guide.md")
        assert rc == 0
        assert out == ("## docs/guide.md (3 lines, markdown)\n"
                       "- L1 Renamed\n")

    def test_a_stale_shard_is_withheld_under_no_refresh(self, proj, capsys):
        _write(proj / "docs" / "guide.md", "# Renamed\n\nbody\n")
        rc, out, err = _run(capsys, "--outline", "docs/guide.md", "--no-refresh")
        assert rc == 1
        assert out == ""
        assert "docs/guide.md" in err


# ---------------------------------------------------------------------------
# §11.3 -- staleness on the read path
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_a_stale_shard_is_refreshed_before_it_is_answered_from(
            self, proj, capsys):
        # Two blank lines prepended: every coordinate in that file moves by 2.
        _write(proj / "src" / "util.py", "\n\n" + UTIL_PY)
        rc, out, _err = _run(capsys, "alpha")
        assert rc == 0
        assert "src/util.py:3-4\tfunc\talpha\t(z)" in out.splitlines()
        # ...and the repair landed on disk, not just in this process.
        header, rows = fleet.read_shard(fleet.shard_path_for_source(proj, "src/util.py"))
        assert ("alpha", 3, 4, "func", "(z)") in rows

    def test_a_stale_shard_never_yields_a_wrong_slice(self, proj, capsys):
        # The sharpest form of the §8 hazard: a stale line number does not
        # error, it silently slices the WRONG code. Two lines prepended move
        # `alpha` from 1-2 to 3-4; serving the shard's coordinates would emit
        # the two blank lines and nothing else, with no visible failure.
        _write(proj / "src" / "util.py", "\n\n" + UTIL_PY)
        rc, out, _err = _run(capsys, "alpha", "--src", "--path", "src/util.py")
        assert rc == 0
        assert out == ("src/util.py:3-4\tfunc\talpha\t(z)\n"
                       "def alpha(z):\n"
                       "    return z\n")

    def test_a_corrupt_shard_takes_the_same_path(self, proj, capsys):
        shard = fleet.shard_path_for_source(proj, "src/util.py")
        shard.write_bytes(b"#\tnot-a-header\n")
        rc, out, _err = _run(capsys, "alpha")
        assert rc == 0
        assert "src/util.py:1-2\tfunc\talpha\t(z)" in out.splitlines()

    def test_a_source_file_with_no_shard_is_invisible_to_a_query(
            self, proj, capsys):
        # SPEC TENSION, resolved in favour of §11.6 and recorded here so the
        # next reader does not "fix" it. §11.3 lists a MISSING shard among the
        # cases the read path repairs, but §11.2 says queries run "against the
        # name column of every SHARD under the index root" and §11.6 says `q`
        # "reads only the shards its filters select, and writes only the
        # SINGLE shard it found stale". Enumerating source files instead would
        # make every query walk the whole tree and write a shard per
        # unindexed file -- a build wearing a query's clothes, and flatly
        # against §11.6's one-write budget. So enumeration is over the shard
        # tree, and §11.3's "missing" case is live on the paths where the rel
        # is NAMED (`--outline`, and the mid-swap vanish below), not here.
        # Indexing is the manager's job (`fleet index build`/`update`, §8).
        fleet.shard_path_for_source(proj, "src/util.py").unlink()
        rc, out, _err = _run(capsys, "alpha")
        assert rc == 0
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str"]
        # ...and the query wrote nothing to repair it, per §11.6's budget.
        assert not fleet.shard_path_for_source(proj, "src/util.py").exists()

    def test_but_outline_does_repair_a_missing_shard(self, proj, capsys):
        # The other half of the tension: `--outline` names its rel, so §11.3's
        # missing-shard branch is reachable and does repair before answering.
        fleet.shard_path_for_source(proj, "src/util.py").unlink()
        rc, out, _err = _run(capsys, "--outline", "src/util.py")
        assert rc == 0
        assert out == ("## src/util.py (6 lines, python)\n"
                       "- L1 alpha(z)\n"
                       "- L5 run(q)\n")
        assert fleet.shard_path_for_source(proj, "src/util.py").is_file()

    def test_a_shard_that_vanishes_mid_swap_is_treated_as_stale(
            self, proj, monkeypatch, capsys):
        # §11.5's mid-swap row: the reader never crashes on a concurrent
        # writer, it re-parses.
        real = fleet.read_shard

        def flaky(shard_path):
            if Path(shard_path).name == "util.py.tsv":
                return None
            return real(shard_path)

        monkeypatch.setattr(fleet, "read_shard", flaky)
        rc, out, _err = _run(capsys, "alpha")
        assert rc == 0
        assert "src/util.py:1-2\tfunc\talpha\t(z)" in out.splitlines()


class TestNoRefresh:
    def test_a_stale_shard_is_withheld_with_a_note_and_never_served(
            self, proj, capsys):
        _write(proj / "src" / "util.py", "\n\n" + UTIL_PY)
        rc, out, err = _run(capsys, "alpha", "--no-refresh")
        assert rc == 0                                   # api.py still answered
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str"]
        assert "src/util.py" in err
        # The stale coordinates are never served, right or wrong.
        assert "src/util.py:1-2" not in out
        assert "src/util.py:3-4" not in out

    def test_all_matches_withheld_is_exit_1(self, proj, capsys):
        _write(proj / "src" / "util.py", "\n\n" + UTIL_PY)
        rc, out, err = _run(capsys, "alpha", "--no-refresh", "--path", "src/util.py")
        assert rc == 1
        assert out == ""
        assert "withheld" in err

    def test_it_writes_absolutely_nothing(self, proj, capsys):
        # §12 asks for the directory-mtime assertion specifically: a prune
        # moves a directory mtime even when no file's bytes move.
        _write(proj / "src" / "util.py", "\n\n" + UTIL_PY)          # stale
        (proj / "root.py").unlink()                                  # orphan
        fleet.shard_path_for_source(proj, "docs/guide.md").unlink()  # missing
        before_tree, before_mtimes = _tree(proj), _dir_mtimes(proj)
        for argv in (["alpha", "--no-refresh"],
                     ["Setup", "--no-refresh"],
                     ["gamma", "--no-refresh"],
                     ["--outline", "src/util.py", "--no-refresh"]):
            _run(capsys, *argv)
        assert _tree(proj) == before_tree
        assert _dir_mtimes(proj) == before_mtimes

    def test_an_orphan_is_withheld_and_not_pruned(self, proj, capsys):
        (proj / "root.py").unlink()
        rc, out, err = _run(capsys, "gamma", "--no-refresh")
        assert rc == 1
        assert out == ""
        assert "root.py" in err
        assert fleet.shard_path_for_source(proj, "root.py").is_file()


class TestOrphans:
    def test_an_orphan_shard_is_suppressed_and_pruned(self, proj, capsys):
        (proj / "src" / "util.py").unlink()
        rc, out, err = _run(capsys, "alpha")
        assert rc == 0
        assert out.splitlines() == [
            "src/api.py:6-9\tfunc\talpha\t(x: int) -> str"]
        assert "src/util.py" in err
        assert not fleet.shard_path_for_source(proj, "src/util.py").exists()

    def test_an_orphan_only_result_is_exit_1(self, proj, capsys):
        (proj / "root.py").unlink()
        rc, out, err = _run(capsys, "gamma")
        assert rc == 1
        assert out == ""
        assert "root.py" in err
        assert not fleet.shard_path_for_source(proj, "root.py").exists()


# ---------------------------------------------------------------------------
# Containment: a caller-supplied path may not escape the index root
# ---------------------------------------------------------------------------

class TestOutlinePathContainment:
    """`--outline <path>` is the only caller-supplied PATH in this tool.

    These are written as ATTACKS, not as unit tests, for a measured reason:
    before the guard existed, `fleet q --outline "a/../../../../victim/
    PRECIOUS"` exited 1 with an ordinary-looking orphan note AND deleted
    `../victim/PRECIOUS.tsv`. A test that asserted only the exit code passed
    against the deleting build. So every test here plants a real file outside
    the index root and asserts it SURVIVES.

    The underlying defect is in `verified_shard_rows`' orphan-prune path and
    belongs to `idx/core`; this guard is at the caller and stays correct
    however the primitive is repaired."""

    @pytest.fixture
    def victim(self, proj, tmp_path):
        # `tmp_path/victim` is a sibling of `tmp_path/proj`, so the shard-path
        # concatenation `.fleet-index/symbols/<rel>.tsv` reaches it with four
        # `..` segments -- the exact shape measured above.
        outside = tmp_path / "victim"
        outside.mkdir()
        planted = {}
        for name in ("PRECIOUS", "PRECIOUS.tsv", "api.py", "api.py.tsv"):
            planted[name] = _write(outside / name, f"do not delete: {name}\n")
        return outside, planted

    def _survives(self, outside, planted):
        assert outside.is_dir()
        for name, path in planted.items():
            assert path.is_file(), f"{name} was deleted outside the index root"
            assert path.read_bytes() == f"do not delete: {name}\n".encode("utf-8")

    @pytest.mark.parametrize("raw", [
        "a/../../../../victim/PRECIOUS",
        "a/../../../../victim/api.py",
        "../victim/api.py",
        "../../victim/api.py",
        "src/../../../../../victim/PRECIOUS",
        "./a/../../../../victim/PRECIOUS",
    ])
    def test_a_traversing_outline_path_is_refused_and_deletes_nothing(
            self, proj, capsys, victim, raw):
        outside, planted = victim
        rc, out, err = _run(capsys, "--outline", raw)
        assert rc != 0
        assert out == ""
        assert "outside the index root" in err
        self._survives(outside, planted)

    def test_an_absolute_path_outside_the_root_is_refused_too(
            self, proj, capsys, victim):
        outside, planted = victim
        rc, out, err = _run(capsys, "--outline", str(outside / "api.py"))
        assert rc != 0
        assert out == ""
        assert "outside the index root" in err
        self._survives(outside, planted)

    def test_an_interior_dotdot_that_stays_inside_still_works(self, proj, capsys):
        # The guard rejects ESCAPE, not `..` -- a path that normalises back
        # inside the root is a legitimate way for a worker to name a file.
        rc, out, _err = _run(capsys, "--outline", "docs/../src/api.py")
        assert rc == 0
        assert out.splitlines()[0] == "## src/api.py (17 lines, python)"

    def test_the_guard_runs_before_the_shard_layer_is_touched(
            self, proj, monkeypatch, capsys, victim):
        # Defence in depth means the primitive is never CALLED with an
        # out-of-root rel, not that it survives being called with one.
        def forbidden(*_args, **_kwargs):
            raise AssertionError("an out-of-root path reached the shard layer")

        monkeypatch.setattr(fleet, "verified_shard_rows", forbidden)
        assert _run(capsys, "--outline", "a/../../../../victim/PRECIOUS")[0] != 0
        self._survives(*victim)


class TestQueryPathsCannotEscapeTheRoot:
    """Measured, not assumed (the steer's item 4).

    `--path GLOB` cannot introduce a path: it FILTERS the rels
    `index_shard_rels` produced by walking the shard tree, so every candidate
    is inside the root by construction and a `..` in the glob simply matches
    nothing. That is why the containment guard lives on `--outline` alone."""

    @pytest.fixture
    def victim(self, proj, tmp_path):
        outside = tmp_path / "victim"
        outside.mkdir()
        return outside, {"api.py.tsv": _write(outside / "api.py.tsv", "x\n"),
                         "api.py": _write(outside / "api.py", "def alpha():\n    pass\n")}

    @pytest.mark.parametrize("argv", [
        ["alpha", "--path", "../victim/*.py"],
        ["alpha", "--path", "a/../../../../victim/*"],
        ["alpha", "--path", "**/../**"],
        ["alpha", "--src", "--path", "../../victim/api.py"],
        ["alpha", "--path", "../victim/*.py", "--no-refresh"],
    ])
    def test_a_traversing_path_glob_reaches_and_deletes_nothing(
            self, proj, capsys, victim, argv):
        outside, planted = victim
        rc, _out, _err = _run(capsys, *argv)
        assert rc == 1                          # the glob selects no shard
        for name, path in planted.items():
            assert path.is_file(), f"{name} was deleted outside the index root"

    def test_every_rel_a_query_visits_is_inside_the_root(self, proj, capsys):
        # THIS TEST USED TO BE ITS OWN ORACLE, and that is worth spelling out
        # because the shape recurs. It asserted only that `_q_contained` says
        # YES to the rels `index_shard_rels` produces -- all of which are clean
        # by construction -- so it passed unchanged against a guard stubbed to
        # `return True`. Measured: under that injection it was not among the
        # RED tests. A guard test that never exercises a REFUSAL measures
        # nothing; it certifies the very defect it is named after.
        for rel in fleet.index_shard_rels(proj):
            assert ".." not in rel.split("/")
            assert fleet._q_contained(proj, rel), rel
        # ...so the other half, which is what makes the assertion falsifiable:
        # the guard must also say NO. Both escape shapes are represented --
        # the source escaping the root, and the source staying inside while the
        # SHARD escapes `.fleet-index/symbols/` (see `_q_contained`).
        for rel in ("../victim/api.py",
                    "a/../../../../victim/PRECIOUS",
                    "../../victim/api.py",
                    f"../{proj.name}/src/api.py"):
            assert not fleet._q_contained(proj, rel), rel


class TestAPathGlobNeverProducesAConfidentAbsence:
    """`--path` speaks a `**`-aware dialect, and saying so is not optional.

    The dialect itself is settled (see the module note in `bin/fleet.py`); what
    was broken is WHEN the tool admits to it. The hint fired only when the glob
    selected ZERO shards -- i.e. only in the case where the empty result was
    already self-explanatory -- and stayed silent whenever the glob selected
    something that merely did not contain the symbol. That is the case where
    the dialect IS the reason for the empty answer, and it is the case a worker
    cannot diagnose."""

    def test_a_glob_that_selects_a_shard_but_finds_nothing_still_explains(
            self, proj, capsys):
        # `alpha` exists twice, in `src/`. `*.py` selects `root.py` -- a
        # non-empty selection with no `alpha` in it -- so the old code answered
        # with a flat "no symbol matches 'alpha'" and nothing else.
        rc, out, err = _run(capsys, "alpha", "--path", "*.py")
        assert rc == 1
        assert out == ""
        assert "`**`-aware" in err
        assert "**/*.py" in err and "any depth" in err
        # ...and the widened glob proves the absence was never real.
        rc, out, _err = _run(capsys, "alpha", "--path", "**/*.py")
        assert (rc, len(out.splitlines())) == (0, 2)

    def test_the_hint_still_fires_when_the_glob_selects_nothing(
            self, proj, capsys):
        rc, _out, err = _run(capsys, "alpha", "--path", "nowhere/*.py")
        assert rc == 1
        assert "matched no indexed file" in err
        assert "`**`-aware" in err

    def test_a_query_without_path_is_not_lectured_about_globs(
            self, proj, capsys):
        rc, _out, err = _run(capsys, "no_such_symbol_at_all")
        assert rc == 1
        assert "no symbol matches" in err
        assert "`**`-aware" not in err


class TestAnUnreadShardNeverBecomesAConfidentAnswer:
    """F3 x F4: the silent-wrong-answer chain, fixed and pinned as one.

    A shard this query could not read is a shard that may be hiding a
    competitor. Two separate defects let that fact vanish:

    * `--src` tested ambiguity against the hits it MANAGED to collect, so a
      withheld competitor turned a two-hit ambiguity (rc 1) into a confident
      one-hit slice (rc 0).
    * the empty-hits path printed no summary line at all when anything was
      suppressed, leaving only notes -- which `Q_NOTE_CAP` truncates.

    Separately each leaves a trace a careful reader might catch. TOGETHER the
    wrong answer is fully silent, which is why the composite is pinned below
    and not just the two halves."""

    @staticmethod
    def _noisy(tmp_path, monkeypatch, capsys, extra, noise=26):
        files = dict(extra)
        for n in range(noise):
            files[f"noise{n:02d}.py"] = f"def noise{n:02d}():\n    return {n}\n"
        root = _project(tmp_path, files)
        monkeypatch.chdir(root)
        capsys.readouterr()
        return root

    @staticmethod
    def _stale(root, rel):
        """Prepend a comment so the source no longer hashes to its header."""
        _write(root / rel, (root / rel).read_bytes().decode("utf-8") + "# drift\n")

    def test_a_withheld_competitor_cannot_turn_ambiguity_into_a_slice(
            self, tmp_path, monkeypatch, capsys):
        root = _project(tmp_path, {"a.py": "def only():\n    return 1\n",
                                   "b.py": "def only():\n    return 2\n"})
        monkeypatch.chdir(root)
        capsys.readouterr()
        # The control: over fresh shards this query is ambiguous and exits 1.
        assert _run(capsys, "only", "--src")[0] == 1
        self._stale(root, "b.py")
        rc, out, err = _run(capsys, "only", "--src", "--no-refresh")
        # Measured before the fix: rc 0, and a confident slice of `a.py`.
        assert rc == 1
        assert "return 1" not in out                  # not one line of source
        assert out.splitlines() == ["a.py:1-2\tfunc\tonly\t()"]
        assert "1 shard(s) could not be read" in err
        assert "will not commit" in err

    def test_the_composite_the_note_cap_cannot_swallow_the_signal(
            self, tmp_path, monkeypatch, capsys):
        # 26 stale shards sort ahead of `zzz_competitor.py`, so `Q_NOTE_CAP`
        # deletes the one note that named it. The count line is the fix: it is
        # not a note, so no cap can drop it.
        root = self._noisy(tmp_path, monkeypatch, capsys, {
            "a.py": "def only():\n    return 1\n",
            "zzz_competitor.py": "def only():\n    return 2\n"})
        for rel in [f"noise{n:02d}.py" for n in range(26)] + ["zzz_competitor.py"]:
            self._stale(root, rel)
        rc, out, err = _run(capsys, "only", "--src", "--no-refresh")
        assert rc == 1
        assert "return 1" not in out
        # The cap really did fire, and it really did hide the competitor --
        # this test is only worth anything while both remain true.
        assert "more shard notes" in err
        assert "zzz_competitor" not in err
        # ...and the answer is still not confident, because the count survives.
        assert "27 shard(s) could not be read" in err

    def test_empty_hits_plus_unread_shards_is_not_a_claim_of_absence(
            self, tmp_path, monkeypatch, capsys):
        root = self._noisy(tmp_path, monkeypatch, capsys,
                           {"target.py": "def onlyhere():\n    return 1\n"})
        for rel in [f"noise{n:02d}.py" for n in range(26)] + ["target.py"]:
            self._stale(root, rel)
        rc, out, err = _run(capsys, "onlyhere", "--no-refresh")
        assert rc == 1
        assert out == ""
        assert "more shard notes" in err          # the cap fired...
        assert "target.py" not in err             # ...and hid the only note that mattered
        assert "NOT evidence" in err and "27 shard(s) could not be read" in err
        # And the confident phrasing must NOT appear: the symbol is right there.
        assert "no symbol matches" not in err

    def test_a_gone_source_is_not_counted_as_hiding_anything(
            self, proj, capsys):
        # The other side of the rule, and the reason `_q_collect_rows` re-tests
        # existence: an orphan whose source is GONE cannot hide a competitor,
        # so it must not suppress the plain "no symbol matches" answer or turn
        # every routine deleted file into a refusal.
        (proj / "root.py").unlink()
        rc, out, err = _run(capsys, "gamma")
        assert rc == 1
        assert out == ""
        assert "no symbol matches" in err
        assert "could not be read" not in err

    def test_a_gone_source_does_not_block_a_src_slice_elsewhere(
            self, proj, capsys):
        (proj / "root.py").unlink()
        rc, out, err = _run(capsys, "Beta.solo", "--src")
        assert rc == 0
        assert out.splitlines()[1] == "    def solo(self):"
        assert "will not commit" not in err


class TestOutlineShardPathContainment:
    """The SECOND path `--outline` derives, and the one the first guard missed.

    `verified_shard_rows` derives two paths from one rel -- the source
    (`root / rel`) and the shard (`.fleet-index/symbols/` + rel) -- and those
    climb from roots two levels apart. A rel whose `..` count is tuned to the
    symbols directory lands the SOURCE back inside the root, satisfying a
    source-only containment check, while the SHARD escapes entirely.

    THE PROCESS CWD IS PART OF THE ATTACK. From the index root the same
    argument resolves to a clean rel, `_q_outline_rels` offers that first, and
    `next(...)` takes it before the raw `..`-bearing string is ever considered
    -- there is NO escape at all. `test_the_cwd_is_the_precondition` below
    measures that non-escape explicitly, so that nobody reading this class
    concludes the root-relative case was simply an untested duplicate: a
    containment test written from the root passes against the DELETING build
    and reads as proof of safety.

    Both halves are asserted the way `TestOutlinePathContainment` asserts
    them -- against the filesystem, never against the exit code alone. The
    write half exited 0 with an empty stderr, and the unlink half exited 1 with
    a note that reads like routine housekeeping."""

    NAMES = ("VICTIM.py", "GONE.py")

    @pytest.fixture
    def jail(self, tmp_path, monkeypatch):
        # The root's last three segments and the rel's three `..` are a matched
        # pair: `root/../../../gp/par/proj/X` normalises back to `root/X`
        # (inside), while `symbols/../../../gp/par/proj/X.tsv` lands at
        # `tmp_path/gp/par/gp/par/proj/X.tsv` (outside).
        root = tmp_path / "gp" / "par" / "proj"
        (root / "sub").mkdir(parents=True)
        for name in self.NAMES:
            _write(root / name, "def victim():\n    pass\n")
        _write(root / "sub" / "keep.py", "def keep():\n    pass\n")
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        return root

    @staticmethod
    def _escaped(root, name):
        """Where the shard-path concatenation actually lands for the attack
        rel -- computed, not hardcoded, so it stays honest if the shard tree
        moves."""
        shard = fleet.shard_path_for_source(root, f"../../../gp/par/proj/{name}")
        resolved = Path(os.path.normpath(str(shard)))
        assert not str(resolved).startswith(str(Path(root).resolve()) + os.sep), (
            "the fixture no longer escapes -- this test would be vacuous")
        return resolved

    def test_a_shard_path_escape_writes_nothing_outside_the_root(
            self, jail, monkeypatch, capsys):
        monkeypatch.chdir(jail / "sub")
        capsys.readouterr()
        escaped = self._escaped(jail, "VICTIM.py")
        rc, out, err = _run(capsys, "--outline", "../../../gp/par/proj/VICTIM.py")
        assert rc != 0
        assert out == ""
        assert "outside the index root" in err
        # The measured failure was rc 0 with an empty stderr and this file on
        # disk -- a write outside the root that announced nothing at all.
        assert not escaped.exists(), f"a shard was written outside the root at {escaped}"

    def test_a_shard_path_escape_unlinks_nothing_outside_the_root(
            self, jail, monkeypatch, capsys):
        escaped = self._escaped(jail, "GONE.py")
        escaped.parent.mkdir(parents=True, exist_ok=True)
        _write(escaped, "do not delete\n")
        (jail / "GONE.py").unlink()          # -> the orphan-prune branch
        monkeypatch.chdir(jail / "sub")
        capsys.readouterr()
        rc, out, err = _run(capsys, "--outline", "../../../gp/par/proj/GONE.py")
        assert rc != 0
        assert out == ""
        assert "outside the index root" in err
        # The measured failure was rc 1 with `source file is gone -- hits
        # suppressed; orphan shard pruned`: a delete outside the root wearing
        # the exit code and the wording of routine housekeeping.
        assert escaped.is_file(), "a file outside the index root was deleted"
        assert escaped.read_bytes() == b"do not delete\n"

    def test_the_cwd_is_the_precondition_not_an_incidental_detail(
            self, jail, monkeypatch, capsys):
        # Run the IDENTICAL argument from the root. `_q_outline_rels` resolves
        # it against the cwd, lands inside the root, and offers `VICTIM.py` as
        # the first candidate -- so the raw rel is never reached and nothing
        # escapes even with the guard removed. Pinned so that a future rewrite
        # of these tests cannot quietly relocate them to the root and keep
        # measuring a non-escape.
        monkeypatch.chdir(jail)
        capsys.readouterr()
        escaped = self._escaped(jail, "VICTIM.py")
        rc, out, _err = _run(capsys, "--outline", "../../../gp/par/proj/VICTIM.py")
        assert rc == 0                                   # legitimate, not refused
        assert out.splitlines()[0] == "## VICTIM.py (2 lines, python)"
        assert not escaped.exists()

    def test_the_guard_runs_before_the_shard_layer_is_touched(
            self, jail, monkeypatch, capsys):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("an escaping rel reached the shard layer")

        monkeypatch.setattr(fleet, "verified_shard_rows", forbidden)
        monkeypatch.chdir(jail / "sub")
        capsys.readouterr()
        assert _run(capsys, "--outline", "../../../gp/par/proj/VICTIM.py")[0] != 0

    def test_the_guard_also_refuses_a_rel_that_only_leaves_the_shard_tree(
            self, jail):
        # One `..` is enough to leave `symbols/` without leaving the root: the
        # shard lands in `.fleet-index/` itself, where nothing enumerates it
        # and no prune ever reaches it. Not an escape from the repository, but
        # still a write the shard tree could not account for.
        #
        # Asserted at the guard rather than through the CLI ON PURPOSE. No
        # `--outline` argument reaches `_q_contained` with this rel as its ONLY
        # candidate -- `_q_outline_rels` always offers a cwd-resolved candidate
        # first, and here that one is clean -- so a CLI-level assertion would
        # be measuring the first candidate's fate, not the guard's. The guard
        # is nonetheless the thing that has to be right: it is the reason the
        # shard test is `inside(shard, symbols)` and not the weaker
        # `inside(shard, base)`, which would wave this through.
        rel = f"../{jail.name}/VICTIM.py"
        stray = Path(os.path.normpath(str(fleet.shard_path_for_source(jail, rel))))
        assert fleet.index_symbols_dir(jail).resolve() not in stray.parents
        assert Path(jail).resolve() in stray.parents        # inside the ROOT...
        assert not fleet._q_contained(jail, rel)            # ...and still refused


# ---------------------------------------------------------------------------
# Row order across a refresh -- an M1 defect, pinned rather than hidden
# ---------------------------------------------------------------------------

TIE_PY = """\
ZED = ALPHA = 1


def f():
    pass
"""


class TestRowOrderAcrossARefresh:
    """`verified_shard_rows` returns rows in a DIFFERENT ORDER depending on
    whether it just refreshed: shard order (`render_shard` sorts by
    `(line, end, name)`) when the shard was current, parse order when it was
    not. They diverge on any `(line, end)` tie, and `ZED = ALPHA = 1` is one.

    This is an `idx/core` defect, not a `q` defect, so it is pinned here
    rather than repaired here. The two tests below say exactly where `q`
    absorbs it and where it stays visible."""

    @pytest.fixture
    def tie(self, tmp_path, monkeypatch, capsys):
        root = _project(tmp_path, {"tie.py": TIE_PY})
        monkeypatch.chdir(root)
        capsys.readouterr()
        return root

    @staticmethod
    def _make_stale(root, rel):
        """A well-formed shard whose hash is wrong -- so the next read
        refreshes it and answers from the PARSE, not from these bytes."""
        fleet.shard_path_for_source(root, rel).write_bytes(
            b"#\t00000000\t5\tpython\n")

    def test_the_query_path_is_stable_because_q_sorts_totally(self, tie, capsys):
        # `_q_sorted` keys on (path, line, end, NAME), so a `(line, end)` tie
        # resolves the same way whichever order the primitive handed back.
        cached = _run(capsys, "*", "--path", "tie.py")
        self._make_stale(tie, "tie.py")
        refreshed = _run(capsys, "*", "--path", "tie.py")
        assert cached == refreshed
        assert cached[1].splitlines() == [
            "tie.py:1-1\tconst\tALPHA\t",
            "tie.py:1-1\tconst\tZED\t",
            "tie.py:4-5\tfunc\tf\t()",
        ]

    def test_outline_order_is_UNSTABLE_across_a_refresh_M1_DEFECT(
            self, tie, capsys):
        """CHARACTERISATION TEST -- it asserts a defect, on purpose.

        `--outline` renders `render_digest` over the primitive's rows
        directly, because §7 defines the digest as a rendering of the SHARD
        and the shard is sorted by line. Sorting in this output layer too
        would make `q` look right while hiding the primitive's instability in
        a second place, so instead the divergence is measured and pinned.

        WHEN `idx/core` FIXES `verified_shard_rows` TO RETURN SHARD ORDER
        UNCONDITIONALLY, THIS TEST GOES RED. That is the intended signal:
        invert it to `assert cached == refreshed` and delete this docstring."""
        _rc, cached, _err = _run(capsys, "--outline", "tie.py")
        assert cached == ("## tie.py (5 lines, python)\n"
                          "- L1 ALPHA\n"
                          "- L1 ZED\n"
                          "- L4 f()\n")
        self._make_stale(tie, "tie.py")
        _rc, refreshed, _err = _run(capsys, "--outline", "tie.py")
        assert refreshed == ("## tie.py (5 lines, python)\n"
                             "- L1 ZED\n"
                             "- L1 ALPHA\n"
                             "- L4 f()\n")
        assert cached != refreshed
        # The refresh landed, so a third read is cached again and flips back.
        _rc, again, _err = _run(capsys, "--outline", "tie.py")
        assert again == cached

    def test_no_other_golden_in_this_file_sits_on_a_tie(self, proj):
        # The fixture tree is deliberately tie-free, so every OTHER golden
        # here is immune to the defect above rather than accidentally lucky.
        for rel in fleet.index_shard_rels(proj):
            result = fleet.verified_shard_rows(proj, rel)
            keys = [(row[1], row[2]) for row in result["rows"]]
            assert len(keys) == len(set(keys)), f"{rel} has a (line, end) tie"


# ---------------------------------------------------------------------------
# §8/§11.3 -- the choke point
# ---------------------------------------------------------------------------

class TestEveryReadGoesThroughTheChokePoint:
    """`verified_shard_rows` is the ONLY way `q` may reach a shard (§11.3).

    Reading a shard around it re-opens the hole §8 exists to close: a stale
    line number does not error, it silently slices the wrong code, and the
    worker cannot tell. So this is asserted at runtime rather than by reading
    the source -- a spy on `read_shard` that records any call made outside a
    `verified_shard_rows` frame."""

    @pytest.fixture
    def guard(self, monkeypatch):
        state = {"depth": 0, "direct": [], "verified": 0}
        real_verify, real_read = fleet.verified_shard_rows, fleet.read_shard

        def verified(*args, **kwargs):
            state["depth"] += 1
            state["verified"] += 1
            try:
                return real_verify(*args, **kwargs)
            finally:
                state["depth"] -= 1

        def read(shard_path):
            if state["depth"] == 0:
                state["direct"].append(str(shard_path))
            return real_read(shard_path)

        monkeypatch.setattr(fleet, "verified_shard_rows", verified)
        monkeypatch.setattr(fleet, "read_shard", read)
        return state

    @pytest.mark.parametrize("argv", [
        ["alpha"],
        ["alpha", "--src", "--path", "src/api.py"],
        ["Beta.*"],
        ["solo"],
        ["nosuch"],
        ["--outline", "src/api.py"],
        ["--outline", "docs/guide.md", "--no-refresh"],
        ["alpha", "--no-refresh"],
    ])
    def test_no_shard_is_read_off_the_choke_point(self, proj, capsys, guard, argv):
        _run(capsys, *argv)
        assert guard["direct"] == []
        assert guard["verified"] > 0


# ---------------------------------------------------------------------------
# §11.6 -- `q` never touches fleet state (invariant 9)
# ---------------------------------------------------------------------------

class TestNoFleetState:
    """The invariant that keeps `q` safe to hand a worker.

    `q` is a pure function of the target repo's working tree plus its
    gitignored index: no registry read or write, no `fleet.lock`, no mailbox,
    no PID probe, no subprocess at all."""

    @pytest.fixture
    def tripwires(self, monkeypatch, tmp_path):
        home = tmp_path / "fleet-home"
        home.mkdir()
        monkeypatch.setattr(fleet, "FLEET_HOME", home)

        def forbidden(name):
            def fail(*_args, **_kwargs):
                raise AssertionError(f"fleet q touched fleet state: {name}")
            return fail

        for name in ("load_registry", "save_registry", "fleet_lock",
                     "status_snapshot", "mailbox_dir"):
            monkeypatch.setattr(fleet, name, forbidden(name))
        for name in ("run", "Popen", "check_output", "call"):
            monkeypatch.setattr(subprocess, name, forbidden(f"subprocess.{name}"))
        return home

    @pytest.mark.parametrize("argv", [
        ["alpha"],
        ["alpha", "--src", "--path", "src/api.py"],
        ["alpha", "--no-refresh"],
        ["nosuch"],
        ["--outline", "src/api.py"],
        ["--outline", "nope.py"],
    ])
    def test_the_read_path_touches_no_fleet_state(
            self, proj, capsys, tripwires, argv):
        _run(capsys, *argv)
        assert list(tripwires.iterdir()) == []

    def test_the_no_index_path_touches_no_fleet_state_either(
            self, tmp_path, monkeypatch, capsys, tripwires):
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(bare)
        assert _run(capsys, "alpha")[0] == 3
        assert list(tripwires.iterdir()) == []


# ---------------------------------------------------------------------------
# §11.5 -- the exit-code table, end to end
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_0_is_at_least_one_hit_printed(self, proj, capsys):
        assert _run(capsys, "alpha")[0] == 0

    def test_0_survives_a_limit_truncated_list(self, proj, capsys):
        assert _run(capsys, "Beta.*", "--limit", "1")[0] == 0

    def test_0_survives_an_outline(self, proj, capsys):
        assert _run(capsys, "--outline", "src/api.py")[0] == 0

    def test_1_is_no_match(self, proj, capsys):
        assert _run(capsys, "nosuch")[0] == 1

    def test_1_is_everything_withheld(self, proj, capsys):
        _write(proj / "src" / "api.py", "\n" + API_PY)
        assert _run(capsys, "Beta", "--no-refresh")[0] == 1

    def test_1_is_an_ambiguous_src(self, proj, capsys):
        assert _run(capsys, "alpha", "--src")[0] == 1

    def test_1_is_an_outline_on_an_unknown_path(self, proj, capsys):
        assert _run(capsys, "--outline", "src/absent.py")[0] == 1

    def test_3_is_no_index(self, tmp_path, monkeypatch, capsys):
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(bare)
        assert _run(capsys, "alpha")[0] == 3

    def test_stdout_carries_hits_and_stderr_carries_diagnostics(self, proj, capsys):
        # §11.4's split: a worker's tool result must carry signal only.
        (proj / "src" / "util.py").unlink()
        rc, out, err = _run(capsys, "alpha")
        assert rc == 0
        assert out == "src/api.py:6-9\tfunc\talpha\t(x: int) -> str\n"
        assert err != ""


# ---------------------------------------------------------------------------
# platform invariance (§11.2, §12)
# ---------------------------------------------------------------------------

class TestPlatformInvariance:
    @pytest.mark.parametrize("argv", [
        ["alpha"],
        ["Beta.*"],
        ["alpha", "--src", "--path", "src/api.py"],
        ["--outline", "docs/guide.md"],
        ["Setup", "--kind", "section"],
    ])
    def test_no_backslash_ever_reaches_stdout(self, proj, capsys, argv):
        # A win32 `str(Path(rel))` anywhere on the output path would put
        # `src\api.py` here and diverge the goldens from a Linux run.
        _rc, out, _err = _run(capsys, *argv)
        assert "\\" not in out

    def test_no_backslash_reaches_a_stderr_path_either(self, proj, capsys):
        (proj / "src" / "util.py").unlink()
        _rc, _out, err = _run(capsys, "alpha")
        assert "src/util.py" in err
        assert "\\" not in err

    def test_output_ends_with_lf_never_crlf(self, proj, capsys):
        _rc, out, _err = _run(capsys, "alpha", "--src", "--path", "src/api.py")
        assert "\r" not in out
