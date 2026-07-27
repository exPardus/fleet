"""Unit tests for the fleet-index M1 shard layer (docs/specs/fleet-index.md).

Scope: the shard format (§5), the deterministic parsers (§6), atomic shard
writes and their Windows sharing-violation contract (§6, §11.6), the staleness
primitive (§8, §11.3), the index-root walk-up (§11.1), the digest rendering
(§7) and the `fleet index` CLI family (§6, §8, §9).

Nothing here touches fleet state: the index is not fleet state (invariant 9),
so these tests build throwaway source trees under `tmp_path` and never read or
write the registry, a mailbox or a lock.

Every source file is written with explicit `\\n` newlines (`_write`), never
text-mode `write_text`, so a golden shard is byte-identical on win32 and POSIX
(§11.2). The same reason the shard writer pins `newline="\\n"`.
"""
import os
import shutil
from pathlib import Path

import pytest

import fleet


def _write(path, text):
    """Write `text` with LF newlines on every platform, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _read(path):
    """Read bytes and decode, so a stray CRLF shows up as a test failure."""
    return path.read_bytes().decode("utf-8")


PY_SAMPLE = """\
ALPHA = 1
BETA = (
    2,
    3,
)


def top(x: int = 3, *args, **kw) -> str:
    def nested():
        return 1
    return nested()


class Beta:
    ATTR = 9

    def run(self, y) -> bool:
        return True

    async def go(self):
        return None

    class Inner:
        def deep(self):
            return 0
"""

MD_SAMPLE = """\
# Title

intro

## First

body

### Deeper

more

## Second

tail

```
# Not a heading -- inside a fence
```

## Third
"""


# ---------------------------------------------------------------------------
# §5 -- shard paths, header, rendering
# ---------------------------------------------------------------------------

class TestShardPaths:
    def test_shard_path_mirrors_the_source_path(self, tmp_path):
        got = fleet.shard_path_for_source(tmp_path, "bin/fleet.py")
        assert got == tmp_path / ".fleet-index" / "symbols" / "bin" / "fleet.py.tsv"

    def test_shard_path_round_trips_through_its_inverse(self, tmp_path):
        for rel in ("fleet.py", "bin/fleet.py", "docs/specs/a.b/c.md"):
            shard = fleet.shard_path_for_source(tmp_path, rel)
            assert fleet.source_rel_from_shard(tmp_path, shard) == rel

    def test_inverse_yields_forward_slashes_on_every_platform(self, tmp_path):
        shard = tmp_path / ".fleet-index" / "symbols" / "bin" / "fleet.py.tsv"
        assert fleet.source_rel_from_shard(tmp_path, shard) == "bin/fleet.py"

    def test_a_backslash_bearing_rel_is_normalised_to_forward_slashes(self, tmp_path):
        # A caller that hands over an os.sep-joined path must not produce a
        # different shard than the same path in posix form -- otherwise the
        # same source file has two shards on win32.
        assert (fleet.shard_path_for_source(tmp_path, "bin\\fleet.py")
                == fleet.shard_path_for_source(tmp_path, "bin/fleet.py"))

    def test_source_rel_from_shard_rejects_a_path_outside_the_shard_tree(self, tmp_path):
        with pytest.raises(ValueError):
            fleet.source_rel_from_shard(tmp_path, tmp_path / "elsewhere" / "x.tsv")


class TestSourceLang:
    def test_known_languages(self):
        assert fleet.source_lang("a/b.py") == "python"
        assert fleet.source_lang("a/b.md") == "markdown"

    def test_unknown_extension_is_its_own_suffix(self):
        assert fleet.source_lang("a/b.rs") == "rs"
        assert fleet.source_lang("a/b.TXT") == "txt"

    def test_extensionless_is_text(self):
        assert fleet.source_lang("Makefile") == "text"


class TestShardRendering:
    def test_header_then_rows_tab_separated_lf_terminated(self):
        header = {"sha8": "a3f21c8e", "lines": 120, "lang": "python"}
        rows = [("alpha", 12, 28, "func", "(x: int) -> str"),
                ("Beta", 31, 95, "class", "")]
        assert fleet.render_shard(header, rows) == (
            "#\ta3f21c8e\t120\tpython\n"
            "alpha\t12\t28\tfunc\t(x: int) -> str\n"
            "Beta\t31\t95\tclass\t\n"
        )

    def test_header_only_shard_is_just_the_header_line(self):
        header = {"sha8": "00000000", "lines": 0, "lang": "text"}
        assert fleet.render_shard(header, []) == "#\t00000000\t0\ttext\n"

    def test_rows_are_sorted_by_line(self):
        header = {"sha8": "a3f21c8e", "lines": 9, "lang": "python"}
        rows = [("b", 5, 5, "const", ""), ("a", 2, 2, "const", "")]
        body = fleet.render_shard(header, rows).splitlines()[1:]
        assert [line.split("\t")[0] for line in body] == ["a", "b"]


class TestFieldSanitisation:
    def test_literal_tab_in_a_field_is_escaped(self):
        assert fleet._index_tsv_field("a\tb") == "a\\tb"

    def test_newlines_are_stripped(self):
        assert fleet._index_tsv_field("a\r\nb") == "ab"

    def test_a_sanitised_row_round_trips_through_render_and_read(self, tmp_path):
        # Parse-time sanitisation (not render-time) is what makes this hold:
        # rows handed back by a fresh parse and rows read off a shard must be
        # the same objects, or `verified_shard_rows` would answer differently
        # depending on whether it refreshed.
        header = {"sha8": "a3f21c8e", "lines": 1, "lang": "markdown"}
        rows = [(fleet._index_tsv_field("a\tb"), 1, 1, "section", "")]
        shard = tmp_path / "s.tsv"
        shard.write_bytes(fleet.render_shard(header, rows).encode("utf-8"))
        assert fleet.read_shard(shard) == (header, rows)


# ---------------------------------------------------------------------------
# §6 -- parsers
# ---------------------------------------------------------------------------

class TestPythonParser:
    @pytest.fixture()
    def rows(self, tmp_path):
        src = _write(tmp_path / "m.py", PY_SAMPLE)
        return fleet.parse_source_symbols(src, "python")

    def test_golden(self, rows):
        assert rows == [
            ("ALPHA", 1, 1, "const", ""),
            ("BETA", 2, 5, "const", ""),
            ("top", 8, 11, "func", "(x: int=3, *args, **kw) -> str"),
            ("Beta", 14, 25, "class", ""),
            ("Beta.run", 17, 18, "method", "(self, y) -> bool"),
            ("Beta.go", 20, 21, "method", "(self)"),
            ("Beta.Inner", 23, 25, "class", ""),
            ("Beta.Inner.deep", 24, 25, "method", "(self)"),
        ]

    def test_nested_function_is_not_indexed(self, rows):
        assert "nested" not in [r[0] for r in rows]

    def test_class_body_assignment_is_not_a_module_level_const(self, rows):
        assert "ATTR" not in [r[0] for r in rows]
        assert "Beta.ATTR" not in [r[0] for r in rows]

    def test_rows_are_sorted_by_line(self, rows):
        assert [r[1] for r in rows] == sorted(r[1] for r in rows)

    def test_annotated_module_assignment_is_a_const(self, tmp_path):
        src = _write(tmp_path / "m.py", "X: int = 1\n")
        assert fleet.parse_source_symbols(src, "python") == [("X", 1, 1, "const", "")]

    def test_unparseable_python_yields_no_rows(self, tmp_path):
        src = _write(tmp_path / "bad.py", "def (:\n")
        assert fleet.parse_source_symbols(src, "python") == []

    def test_undecodable_bytes_yield_no_rows(self, tmp_path):
        src = tmp_path / "bin.py"
        src.write_bytes(b"\xff\xfe\x00def x(")
        assert fleet.parse_source_symbols(src, "python") == []


class TestMarkdownParser:
    @pytest.fixture()
    def rows(self, tmp_path):
        src = _write(tmp_path / "d.md", MD_SAMPLE)
        return fleet.parse_source_symbols(src, "markdown")

    def test_golden(self, rows):
        assert rows == [
            ("Title", 1, 21, "section", ""),
            ("First", 5, 12, "section", ""),
            ("Deeper", 9, 12, "section", ""),
            ("Second", 13, 20, "section", ""),
            ("Third", 21, 21, "section", ""),
        ]

    def test_end_is_the_line_before_the_next_same_or_higher_heading(self, rows):
        by_name = {r[0]: r for r in rows}
        # "## First" (L5) ends the line before "## Second" (L13).
        assert by_name["First"][2] == 12
        # "### Deeper" (L9) is deeper than "## Second", so it also stops there.
        assert by_name["Deeper"][2] == 12

    def test_last_heading_ends_at_eof(self, rows):
        # "## Third" is itself the last line of the file (21 lines), so its
        # range collapses to its own line rather than running past EOF.
        assert rows[-1] == ("Third", 21, 21, "section", "")

    def test_top_level_heading_spans_to_eof_when_nothing_outranks_it(self, rows):
        assert rows[0][2] == 21

    def test_a_hash_inside_a_fenced_block_is_not_a_heading(self, rows):
        assert "Not a heading -- inside a fence" not in [r[0] for r in rows]

    def test_tilde_fences_are_honoured_too(self, tmp_path):
        src = _write(tmp_path / "d.md", "~~~\n# nope\n~~~\n# yes\n")
        assert [r[0] for r in fleet.parse_source_symbols(src, "markdown")] == ["yes"]

    def test_heading_needs_a_space_after_the_hashes(self, tmp_path):
        src = _write(tmp_path / "d.md", "#nope\n# yes\n")
        assert [r[0] for r in fleet.parse_source_symbols(src, "markdown")] == ["yes"]

    def test_trailing_closing_hashes_are_stripped(self, tmp_path):
        src = _write(tmp_path / "d.md", "## Closed ##\n")
        assert fleet.parse_source_symbols(src, "markdown") == [
            ("Closed", 1, 1, "section", "")]

    def test_heading_ending_at_its_own_line_when_it_is_the_last_line(self, tmp_path):
        src = _write(tmp_path / "d.md", "# a\n# b\n")
        assert fleet.parse_source_symbols(src, "markdown") == [
            ("a", 1, 1, "section", ""), ("b", 2, 2, "section", "")]


class TestOtherLanguagesAreHeaderOnly:
    def test_no_rows_for_an_unknown_language(self, tmp_path):
        src = _write(tmp_path / "a.rs", "fn main() {}\n")
        assert fleet.parse_source_symbols(src, "rs") == []


class TestSourceHeader:
    def test_sha8_is_the_first_eight_hex_of_the_sha256_of_the_bytes(self, tmp_path):
        import hashlib
        src = _write(tmp_path / "a.py", "X = 1\n")
        want = hashlib.sha256(b"X = 1\n").hexdigest()[:8]
        assert fleet.source_header(src, "a.py")["sha8"] == want

    def test_line_count_and_lang(self, tmp_path):
        src = _write(tmp_path / "a.py", "X = 1\nY = 2\n")
        assert fleet.source_header(src, "a.py") == {
            "sha8": fleet.source_header(src, "a.py")["sha8"], "lines": 2, "lang": "python"}

    def test_empty_file_is_zero_lines(self, tmp_path):
        src = _write(tmp_path / "a.py", "")
        assert fleet.source_header(src, "a.py")["lines"] == 0


# ---------------------------------------------------------------------------
# §5/§9 -- reading a shard, and what counts as corrupt
# ---------------------------------------------------------------------------

class TestReadShard:
    def _good(self, tmp_path):
        shard = tmp_path / "s.tsv"
        shard.write_bytes(b"#\ta3f21c8e\t9\tpython\nalpha\t1\t2\tfunc\t()\n")
        return shard

    def test_reads_header_and_rows(self, tmp_path):
        assert fleet.read_shard(self._good(tmp_path)) == (
            {"sha8": "a3f21c8e", "lines": 9, "lang": "python"},
            [("alpha", 1, 2, "func", "()")])

    def test_missing_shard_is_not_readable(self, tmp_path):
        assert fleet.read_shard(tmp_path / "absent.tsv") is None

    @pytest.mark.parametrize("blob", [
        b"",                                            # empty
        b"alpha\t1\t2\tfunc\t()\n",                     # no header line
        b"#\ta3f21c8e\t9\n",                            # short header
        b"#\tZZZZZZZZ\t9\tpython\n",                    # non-hex sha
        b"#\ta3f21c8e\tmany\tpython\n",                 # non-int line count
        b"#\ta3f21c8e\t9\tpython\nalpha\t1\t2\tfunc\n",  # short row
        b"#\ta3f21c8e\t9\tpython\nalpha\tx\t2\tfunc\t()\n",  # non-int line
        b"#\ta3f21c8e\t9\tpython\nalpha\t1\t2\twidget\t()\n",  # unknown kind
        b"#\ta3f21c8e\t9\tpython\nalpha\t1\t2\tfunc\t()",  # torn: no final LF
    ])
    def test_corrupt_or_truncated_shard_is_not_readable(self, tmp_path, blob):
        shard = tmp_path / "s.tsv"
        shard.write_bytes(blob)
        assert fleet.read_shard(shard) is None

    def test_a_directory_in_the_shard_slot_is_not_readable(self, tmp_path):
        (tmp_path / "s.tsv").mkdir()
        assert fleet.read_shard(tmp_path / "s.tsv") is None


# ---------------------------------------------------------------------------
# §6/§11.6 -- atomic writes and the Windows sharing-violation contract
# ---------------------------------------------------------------------------

HEADER_A = {"sha8": "aaaaaaaa", "lines": 1, "lang": "python"}
HEADER_B = {"sha8": "bbbbbbbb", "lines": 2, "lang": "python"}


class TestAtomicShardWrite:
    def test_writes_the_rendered_bytes_and_creates_parents(self, tmp_path):
        shard = tmp_path / ".fleet-index" / "symbols" / "bin" / "a.py.tsv"
        assert fleet.write_shard_atomic(shard, HEADER_A, []) is True
        assert _read(shard) == "#\taaaaaaaa\t1\tpython\n"

    def test_written_bytes_use_lf_on_every_platform(self, tmp_path):
        shard = tmp_path / "s.tsv"
        fleet.write_shard_atomic(shard, HEADER_A, [("a", 1, 1, "const", "")])
        assert b"\r\n" not in shard.read_bytes()

    def test_a_crash_between_write_and_rename_leaves_the_old_shard_intact(
            self, tmp_path, monkeypatch):
        shard = tmp_path / "s.tsv"
        fleet.write_shard_atomic(shard, HEADER_A, [])
        before = shard.read_bytes()

        class Boom(RuntimeError):
            pass

        def explode(tmp_name, dest, sleep=None):
            raise Boom("crash between write and rename")

        monkeypatch.setattr(fleet, "_replace_with_retry", explode)
        with pytest.raises(Boom):
            fleet.write_shard_atomic(shard, HEADER_B, [])
        assert shard.read_bytes() == before
        assert _tmp_leftovers(tmp_path) == []

    def test_permission_error_retries_then_abandons_and_leaves_the_old_shard(
            self, tmp_path, monkeypatch):
        shard = tmp_path / "s.tsv"
        fleet.write_shard_atomic(shard, HEADER_A, [])
        before = shard.read_bytes()
        calls = []

        def deny(src, dst):
            calls.append((src, dst))
            raise PermissionError(13, "sharing violation")

        monkeypatch.setattr(fleet.os, "replace", deny)
        slept = []
        assert fleet.write_shard_atomic(
            shard, HEADER_B, [], sleep=slept.append) is False
        # Bounded, and bounded by the SAME constants the registry writer uses
        # -- one retry policy in this file, not two (§6).
        assert len(calls) == fleet.REGISTRY_REPLACE_RETRIES
        assert len(slept) == fleet.REGISTRY_REPLACE_RETRIES - 1
        assert shard.read_bytes() == before
        assert _tmp_leftovers(tmp_path) == []

    def test_a_transient_permission_error_still_lands(self, tmp_path, monkeypatch):
        shard = tmp_path / "s.tsv"
        fleet.write_shard_atomic(shard, HEADER_A, [])
        real = os.replace
        state = {"n": 0}

        def flaky(src, dst):
            state["n"] += 1
            if state["n"] == 1:
                raise PermissionError(13, "sharing violation")
            return real(src, dst)

        monkeypatch.setattr(fleet.os, "replace", flaky)
        assert fleet.write_shard_atomic(
            shard, HEADER_B, [], sleep=lambda _d: None) is True
        assert _read(shard) == "#\tbbbbbbbb\t2\tpython\n"


def _tmp_leftovers(root):
    return sorted(str(p) for p in root.rglob("*.tmp"))


# ---------------------------------------------------------------------------
# §11.1 -- index-root walk-up, stopping at a repository boundary
# ---------------------------------------------------------------------------

class TestFindIndexRoot:
    def test_finds_the_index_in_the_start_dir(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        assert fleet.find_index_root(tmp_path) == tmp_path.resolve()

    def test_walks_up_from_a_subdirectory(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert fleet.find_index_root(sub) == tmp_path.resolve()

    def test_none_when_no_index_anywhere(self, tmp_path):
        sub = tmp_path / "a"
        sub.mkdir()
        assert fleet.find_index_root(sub) is None

    def test_stops_at_a_git_directory_boundary(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        inner = tmp_path / "nested"
        (inner / ".git").mkdir(parents=True)
        assert fleet.find_index_root(inner) is None

    def test_stops_at_a_git_FILE_boundary(self, tmp_path):
        # A linked worktree's `.git` is a FILE, not a directory. This is the
        # exact shape the campaign worktrees have, and the reason the rule
        # says "entry, whether directory OR file" (§11.1).
        (tmp_path / ".fleet-index").mkdir()
        inner = tmp_path / "wt"
        inner.mkdir()
        (inner / ".git").write_bytes(b"gitdir: /elsewhere/.git/worktrees/wt\n")
        assert fleet.find_index_root(inner) is None

    def test_stops_at_a_boundary_reached_by_walking_up(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        inner = tmp_path / "wt"
        (inner / ".git").mkdir(parents=True)
        deep = inner / "src" / "pkg"
        deep.mkdir(parents=True)
        assert fleet.find_index_root(deep) is None

    def test_the_boundary_directory_own_index_still_wins(self, tmp_path):
        # ".fleet-index" is checked BEFORE the boundary stop, so an indexed
        # repository root resolves to itself rather than to no-index.
        inner = tmp_path / "wt"
        (inner / ".git").mkdir(parents=True)
        (inner / ".fleet-index").mkdir()
        deep = inner / "src"
        deep.mkdir()
        assert fleet.find_index_root(deep) == inner.resolve()


# ---------------------------------------------------------------------------
# §8 -- config
# ---------------------------------------------------------------------------

class TestIndexConfig:
    def test_absent_config_is_the_defaults(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        assert fleet.load_index_config(tmp_path) == {
            "include": ["**/*.py", "**/*.md"],
            "exclude": ["**/node_modules/**", "**/.venv/**", "**/target/**"],
        }

    def test_the_defaults_are_what_init_writes(self, tmp_path):
        (tmp_path / ".fleet-index").mkdir()
        (tmp_path / ".fleet-index" / "config.toml").write_bytes(
            fleet.INDEX_CONFIG_DEFAULT_TOML.encode("utf-8"))
        assert fleet.load_index_config(tmp_path) == fleet.INDEX_CONFIG_DEFAULTS

    def test_comments_and_blank_lines_are_tolerated(self, tmp_path):
        _write(tmp_path / ".fleet-index" / "config.toml",
               "# a comment\n\n[index]\n\ninclude = [\"a\"]\n# trailing\n")
        assert fleet.load_index_config(tmp_path)["include"] == ["a"]

    def test_a_partial_table_keeps_the_default_for_the_absent_key(self, tmp_path):
        _write(tmp_path / ".fleet-index" / "config.toml", "[index]\ninclude = [\"a\"]\n")
        cfg = fleet.load_index_config(tmp_path)
        assert cfg["include"] == ["a"]
        assert cfg["exclude"] == fleet.INDEX_CONFIG_DEFAULTS["exclude"]

    def test_an_empty_array_is_legal(self, tmp_path):
        _write(tmp_path / ".fleet-index" / "config.toml", "[index]\nexclude = []\n")
        assert fleet.load_index_config(tmp_path)["exclude"] == []

    @pytest.mark.parametrize("body,needle", [
        ("[index]\nmode = \"tracked\"\n", "mode"),
        ("[index]\nwhatever = [\"a\"]\n", "whatever"),
        ("[other]\ninclude = [\"a\"]\n", "other"),
        ("include = [\"a\"]\n", "[index]"),
        ("[index]\ninclude = \"a\"\n", "include"),
        ("[index]\ninclude = [1]\n", "include"),
        ("[index]\ninclude = [\"a\",\n", "include"),
        ("[index]\nnonsense\n", "nonsense"),
    ])
    def test_anything_outside_the_fixed_schema_is_a_loud_error(
            self, tmp_path, body, needle):
        _write(tmp_path / ".fleet-index" / "config.toml", body)
        with pytest.raises(fleet.IndexConfigError) as exc:
            fleet.load_index_config(tmp_path)
        assert needle in str(exc.value)

    def test_the_reserved_mode_key_names_itself_in_the_error(self, tmp_path):
        _write(tmp_path / ".fleet-index" / "config.toml", "[index]\nmode = \"tracked\"\n")
        with pytest.raises(fleet.IndexConfigError) as exc:
            fleet.load_index_config(tmp_path)
        assert "config.toml" in str(exc.value)

    def test_config_error_is_a_clean_cli_error_not_a_traceback(self):
        assert issubclass(fleet.IndexConfigError, fleet.FleetCliError)


class TestIndexGlobMatching:
    @pytest.mark.parametrize("path,pattern,want", [
        ("fleet.py", "**/*.py", True),          # root-level file must match
        ("bin/fleet.py", "**/*.py", True),
        ("a/b/c/fleet.py", "**/*.py", True),
        ("bin/fleet.md", "**/*.py", False),
        ("node_modules/x.py", "**/node_modules/**", True),
        ("a/node_modules/b/x.py", "**/node_modules/**", True),
        ("a/nodes/b.py", "**/node_modules/**", False),
        ("a/b.py", "*.py", False),              # single star does not cross /
        ("b.py", "*.py", True),
        ("a/B.py", "**/*.py", True),
        ("a/b.PY", "**/*.py", False),           # case-sensitive on every platform
    ])
    def test_matching(self, path, pattern, want):
        assert fleet._index_glob_match(path, pattern) is want


# ---------------------------------------------------------------------------
# §7 -- digest rendering
# ---------------------------------------------------------------------------

class TestRenderDigest:
    def test_the_exact_shape_from_the_spec(self):
        header = {"sha8": "a3f21c8e", "lines": 120, "lang": "python"}
        rows = [("alpha", 12, 28, "func", "(x: int) -> str"),
                ("Beta", 31, 95, "class", ""),
                ("Beta.run", 40, 62, "method", "(self, y) -> bool")]
        assert fleet.render_digest("src/api.py", header, rows) == (
            "## src/api.py (120 lines, python)\n"
            "- L12 alpha(x: int) -> str\n"
            "- L31 class Beta\n"
            "- L40   Beta.run(self, y) -> bool\n"
        )

    def test_a_symbol_free_shard_renders_its_header_line_only(self):
        header = {"sha8": "a3f21c8e", "lines": 3, "lang": "rs"}
        assert fleet.render_digest("a.rs", header, []) == "## a.rs (3 lines, rs)\n"

    def test_const_and_section_render_bare(self):
        header = {"sha8": "a3f21c8e", "lines": 9, "lang": "markdown"}
        rows = [("Intro", 1, 4, "section", ""), ("GAMMA", 7, 7, "const", "")]
        assert fleet.render_digest("d.md", header, rows) == (
            "## d.md (9 lines, markdown)\n"
            "- L1 Intro\n"
            "- L7 GAMMA\n"
        )

    def test_rendering_is_uncapped(self):
        # The 400-line cap is `q`'s concern, not the renderer's (§11.4).
        header = {"sha8": "a3f21c8e", "lines": 999, "lang": "python"}
        rows = [(f"f{i}", i, i, "func", "()") for i in range(1, 501)]
        assert len(fleet.render_digest("big.py", header, rows).splitlines()) == 501


# ---------------------------------------------------------------------------
# §8/§11.3 -- the verify-then-get choke point
#
# "No path serves an unverified coordinate." A stale line number does not
# error, it silently slices the wrong code, so every read path goes through
# `verified_shard_rows` and every test below is about that guarantee.
# ---------------------------------------------------------------------------

def _tree(root):
    """Every file under `root` as {relpath: bytes} -- the no-write assertion."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _indexed_tree(tmp_path, files=None):
    """A tiny opted-in project. Returns the root."""
    root = tmp_path / "proj"
    for rel, body in (files or {"a.py": "X = 1\n"}).items():
        _write(root / rel, body)
    fleet.index_dir(root).mkdir(parents=True, exist_ok=True)
    return root


class TestVerifiedShardRows:
    def test_missing_shard_is_parsed_and_written(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["status"] == "ok"
        assert got["refreshed"] is True and got["written"] is True
        assert got["rows"] == [("f", 1, 2, "func", "()")]
        assert fleet.read_shard(fleet.shard_path_for_source(root, "a.py"))[1] == got["rows"]

    def test_a_current_shard_is_served_without_a_refresh(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        before = _tree(root)
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["status"] == "ok"
        assert got["refreshed"] is False and got["written"] is False
        assert _tree(root) == before

    def test_a_stale_shard_is_refreshed_then_answered(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        _write(root / "a.py", "# moved down\n\ndef f():\n    pass\n")
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["refreshed"] is True
        assert got["rows"] == [("f", 3, 4, "func", "()")]
        assert fleet.read_shard(fleet.shard_path_for_source(root, "a.py"))[1] == got["rows"]

    def test_an_edit_that_preserves_the_line_count_is_still_stale(self, tmp_path):
        # The staleness key is the SHA-256, not the line count. An edit that
        # keeps the file the same length is the exact case a length check
        # would wave through, and it is not a rare shape: renaming a symbol,
        # or swapping two same-length lines, does it.
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        _write(root / "a.py", "def g():\n    pass\n")
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["refreshed"] is True
        assert [r[0] for r in got["rows"]] == ["g"]

    def test_a_mutated_source_never_yields_a_stale_coordinate(self, tmp_path):
        # §12 acceptance criterion 3, stated as a property: whatever the shard
        # on disk says, the rows handed back always agree with a fresh parse
        # of the bytes currently on disk.
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        for body in ("\n\ndef f():\n    pass\n",
                     "class C:\n    def f(self):\n        pass\n",
                     "def f():\n    pass\n"):
            _write(root / "a.py", body)
            got = fleet.verified_shard_rows(root, "a.py")
            assert got["rows"] == fleet.parse_source_symbols(root / "a.py", "python")

    @pytest.mark.parametrize("damage", ["corrupt", "truncated", "empty", "unknown-kind"])
    def test_a_damaged_shard_takes_the_stale_path_never_an_optimistic_parse(
            self, tmp_path, damage):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        shard = fleet.shard_path_for_source(root, "a.py")
        header_line = shard.read_bytes().split(b"\n")[0]
        # Each damaged body keeps a header that still MATCHES the unchanged
        # source, so nothing but the row damage can trigger a refresh. An
        # implementation that skipped malformed lines instead of refreshing
        # would serve the wrong rows here and never notice.
        blobs = {
            "corrupt": header_line + b"\nWRONG\t999\t999\twidget\t\n",
            "truncated": header_line + b"\nWRO",
            "empty": b"",
            "unknown-kind": header_line + b"\nWRONG\t999\t999\tsection\t\njunk\n",
        }
        shard.write_bytes(blobs[damage])
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["status"] == "ok"
        assert got["refreshed"] is True
        assert got["rows"] == [("f", 1, 2, "func", "()")]
        assert fleet.read_shard(shard) is not None

    def test_no_write_withholds_a_stale_shard_and_writes_nothing(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        _write(root / "a.py", "\ndef f():\n    pass\n")
        before = _tree(root)
        got = fleet.verified_shard_rows(root, "a.py", no_write=True)
        assert got["status"] == "withheld"
        assert got["rows"] == []
        assert got["note"]
        assert _tree(root) == before

    def test_no_write_withholds_a_missing_shard(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        before = _tree(root)
        got = fleet.verified_shard_rows(root, "a.py", no_write=True)
        assert got["status"] == "withheld"
        assert _tree(root) == before

    def test_no_write_still_serves_a_current_shard(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        fleet.verified_shard_rows(root, "a.py")
        got = fleet.verified_shard_rows(root, "a.py", no_write=True)
        assert got["status"] == "ok" and got["rows"] == [("X", 1, 1, "const", "")]

    def test_an_orphan_shard_is_suppressed_and_pruned(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        fleet.verified_shard_rows(root, "a.py")
        shard = fleet.shard_path_for_source(root, "a.py")
        (root / "a.py").unlink()
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["status"] == "orphan"
        assert got["rows"] == []
        assert got["note"]
        assert not shard.exists()

    def test_an_orphan_shard_is_not_pruned_under_no_write(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        fleet.verified_shard_rows(root, "a.py")
        (root / "a.py").unlink()
        before = _tree(root)
        got = fleet.verified_shard_rows(root, "a.py", no_write=True)
        assert got["status"] == "orphan" and got["rows"] == []
        assert _tree(root) == before

    def test_an_abandoned_replace_still_answers_from_the_in_memory_parse(
            self, tmp_path, monkeypatch):
        # §11.3: the on-disk shard stays stale, but THIS invocation answers
        # from its own verified parse -- it must not degrade to withholding
        # just because the write could not land.
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        shard = fleet.shard_path_for_source(root, "a.py")
        stale_bytes = shard.read_bytes()
        _write(root / "a.py", "\ndef f():\n    pass\n")

        def deny(src, dst):
            raise PermissionError(13, "sharing violation")

        monkeypatch.setattr(fleet.os, "replace", deny)
        got = fleet.verified_shard_rows(root, "a.py", sleep=lambda _d: None)
        assert got["status"] == "ok"
        assert got["written"] is False
        assert got["rows"] == [("f", 2, 3, "func", "()")]
        assert shard.read_bytes() == stale_bytes

    def test_an_unparseable_source_verifies_to_a_header_only_shard(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "def (:\n"})
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["status"] == "ok" and got["rows"] == []
        assert fleet.read_shard(fleet.shard_path_for_source(root, "a.py"))[1] == []


# ---------------------------------------------------------------------------
# §8 -- which files the index covers
# ---------------------------------------------------------------------------

class TestIndexSourceFiles:
    def test_defaults_take_python_and_markdown_at_any_depth(self, tmp_path):
        root = _indexed_tree(tmp_path, {
            "a.py": "", "docs/b.md": "", "deep/er/c.py": "",
            "d.rs": "", "e.txt": "",
        })
        assert fleet.index_source_files(root) == ["a.py", "deep/er/c.py", "docs/b.md"]

    def test_excludes_apply(self, tmp_path):
        root = _indexed_tree(tmp_path, {
            "a.py": "", "node_modules/x.py": "", "sub/.venv/y.py": "",
            "target/z.py": "",
        })
        assert fleet.index_source_files(root) == ["a.py"]

    def test_the_index_and_git_trees_are_never_walked(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "", ".git/hooks/x.py": ""})
        _write(fleet.index_dir(root) / "junk.py", "")
        assert fleet.index_source_files(root) == ["a.py"]

    def test_a_custom_include_is_honoured(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "", "b.rs": ""})
        _write(fleet.index_config_path(root), '[index]\ninclude = ["**/*.rs"]\n')
        assert fleet.index_source_files(root) == ["b.rs"]

    def test_order_is_deterministic_and_posix(self, tmp_path):
        root = _indexed_tree(tmp_path, {"b/a.py": "", "a/b.py": "", "a.py": ""})
        got = fleet.index_source_files(root)
        assert got == sorted(got)
        assert all("\\" not in rel for rel in got)


# ---------------------------------------------------------------------------
# §6/§8/§9 -- the `fleet index` CLI family
# ---------------------------------------------------------------------------

def _project(tmp_path, files):
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        _write(root / rel, body)
    return root


class TestIndexInit:
    def test_creates_the_index_config_and_gitignore_entry_then_builds(self, tmp_path):
        root = _project(tmp_path, {"a.py": "def f():\n    pass\n"})
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert fleet.index_symbols_dir(root).is_dir()
        assert (fleet.index_config_path(root).read_bytes()
                == fleet.INDEX_CONFIG_DEFAULT_TOML.encode("utf-8"))
        assert _read(root / ".gitignore").splitlines() == [".fleet-index/"]
        assert fleet.shard_path_for_source(root, "a.py").is_file()

    def test_appends_to_an_existing_gitignore_without_clobbering_it(self, tmp_path):
        root = _project(tmp_path, {"a.py": ""})
        _write(root / ".gitignore", "*.log\nbuild/\n")
        fleet.main(["index", "init", "--path", str(root)])
        assert _read(root / ".gitignore") == "*.log\nbuild/\n.fleet-index/\n"

    def test_adds_a_final_newline_when_the_gitignore_lacks_one(self, tmp_path):
        root = _project(tmp_path, {"a.py": ""})
        _write(root / ".gitignore", "*.log")
        fleet.main(["index", "init", "--path", str(root)])
        assert _read(root / ".gitignore") == "*.log\n.fleet-index/\n"

    def test_is_idempotent_and_never_duplicates_the_entry(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert _read(root / ".gitignore").count(".fleet-index/") == 1

    def test_the_gitignore_entry_is_written_even_when_the_index_already_exists(
            self, tmp_path):
        # "unconditionally" (§8): a project whose .gitignore entry was deleted
        # by hand gets it back on the next init, index present or not.
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        (root / ".gitignore").unlink()
        fleet.main(["index", "init", "--path", str(root)])
        assert ".fleet-index/" in _read(root / ".gitignore")

    def test_an_existing_config_is_not_overwritten(self, tmp_path):
        root = _project(tmp_path, {"a.py": "", "b.rs": ""})
        fleet.index_dir(root).mkdir(parents=True)
        _write(fleet.index_config_path(root), '[index]\ninclude = ["**/*.rs"]\n')
        fleet.main(["index", "init", "--path", str(root)])
        assert _read(fleet.index_config_path(root)) == '[index]\ninclude = ["**/*.rs"]\n'
        assert fleet.shard_path_for_source(root, "b.rs").is_file()

    def test_defaults_to_cwd(self, tmp_path, monkeypatch):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        monkeypatch.chdir(root)
        assert fleet.main(["index", "init"]) == 0
        assert fleet.index_symbols_dir(root).is_dir()

    def test_a_missing_path_is_a_clean_error(self, tmp_path, capsys):
        assert fleet.main(["index", "init", "--path", str(tmp_path / "nope")]) == 1
        assert "fleet:" in capsys.readouterr().err


class TestNoIndexRefusal:
    @pytest.mark.parametrize("argv", [
        ["index", "build"], ["index", "status"],
        ["index", "update", "--files", "a.py"],
    ])
    def test_build_update_status_refuse_without_an_index(self, tmp_path, capsys, argv):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        rc = fleet.main(argv + ["--path", str(root)])
        assert rc != 0
        assert "fleet index init" in capsys.readouterr().err

    def test_init_is_the_only_command_that_creates_the_directory(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        for argv in (["index", "build"], ["index", "status"],
                     ["index", "update", "--files", "a.py"]):
            fleet.main(argv + ["--path", str(root)])
            assert not fleet.index_dir(root).exists()


class TestIndexBuild:
    def test_indexes_every_selected_file(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "docs/b.md": "# H\n",
                                   "c.rs": "fn main() {}\n"})
        fleet.main(["index", "init", "--path", str(root)])
        assert fleet.shard_path_for_source(root, "a.py").is_file()
        assert fleet.shard_path_for_source(root, "docs/b.md").is_file()
        assert not fleet.shard_path_for_source(root, "c.rs").exists()

    def test_incremental_skip(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        capsys.readouterr()
        assert fleet.main(["index", "build", "--path", str(root)]) == 0
        out = capsys.readouterr().out
        assert "indexed 0" in out and "skipped 2" in out

    def test_force_rebuilds_everything(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        capsys.readouterr()
        fleet.main(["index", "build", "--path", str(root), "--force"])
        out = capsys.readouterr().out
        assert "indexed 2" in out and "skipped 0" in out

    def test_only_the_edited_file_is_rewritten(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        before = _tree(root)
        _write(root / "a.py", "X = 2\n")
        fleet.main(["index", "build", "--path", str(root)])
        after = _tree(root)
        assert sorted(k for k in after if after[k] != before.get(k)) == [
            ".fleet-index/symbols/a.py.tsv", "a.py"]

    def test_two_disjoint_edits_touch_two_disjoint_shards_and_merge_cleanly(
            self, tmp_path):
        # §4: there is no global file, so disjoint source edits cannot
        # conflict at any N. Proved structurally (only the matching shard
        # moves) and by outcome (both results are correct at the end).
        root = _project(tmp_path, {"a/x.py": "def one():\n    pass\n",
                                   "b/y.py": "def two():\n    pass\n"})
        fleet.main(["index", "init", "--path", str(root)])
        base = _tree(root)

        _write(root / "a" / "x.py", "\ndef one():\n    pass\n")
        fleet.main(["index", "update", "--path", str(root), "--files", "a/x.py"])
        after_a = _tree(root)
        assert [k for k in after_a if after_a[k] != base.get(k)
                and k.startswith(".fleet-index")] == [".fleet-index/symbols/a/x.py.tsv"]

        _write(root / "b" / "y.py", "\ndef two():\n    pass\n")
        fleet.main(["index", "update", "--path", str(root), "--files", "b/y.py"])
        after_b = _tree(root)
        assert [k for k in after_b if after_b[k] != after_a.get(k)
                and k.startswith(".fleet-index")] == [".fleet-index/symbols/b/y.py.tsv"]

        assert fleet.verified_shard_rows(root, "a/x.py")["rows"] == [
            ("one", 2, 3, "func", "()")]
        assert fleet.verified_shard_rows(root, "b/y.py")["rows"] == [
            ("two", 2, 3, "func", "()")]
        assert fleet.verified_shard_rows(root, "a/x.py")["refreshed"] is False

    def test_the_index_holds_no_global_file(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        assert sorted(p.name for p in fleet.index_dir(root).iterdir()) == [
            "config.toml", "symbols"]

    def test_two_builds_on_an_unchanged_tree_produce_identical_shards(self, tmp_path):
        # §12 acceptance criterion 2, byte-for-byte.
        root = _project(tmp_path, {"a.py": PY_SAMPLE, "d.md": MD_SAMPLE})
        fleet.main(["index", "init", "--path", str(root)])
        first = _tree(fleet.index_symbols_dir(root))
        fleet.main(["index", "build", "--path", str(root), "--force"])
        assert _tree(fleet.index_symbols_dir(root)) == first

    def test_an_unparseable_file_is_header_only_and_the_build_continues(
            self, tmp_path):
        root = _project(tmp_path, {"bad.py": "def (:\n", "good.py": "X = 1\n"})
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        bad = fleet.read_shard(fleet.shard_path_for_source(root, "bad.py"))
        assert bad is not None and bad[1] == []
        assert fleet.read_shard(fleet.shard_path_for_source(root, "good.py"))[1] == [
            ("X", 1, 1, "const", "")]

    def test_orphan_shards_are_pruned_on_build(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "gone.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        (root / "gone.py").unlink()
        fleet.main(["index", "build", "--path", str(root)])
        assert not fleet.shard_path_for_source(root, "gone.py").exists()
        assert fleet.shard_path_for_source(root, "a.py").is_file()

    def test_a_shard_dropped_by_a_config_change_is_pruned_too(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.md": "# H\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(fleet.index_config_path(root), '[index]\ninclude = ["**/*.py"]\n')
        fleet.main(["index", "build", "--path", str(root)])
        assert not fleet.shard_path_for_source(root, "b.md").exists()

    def test_a_bad_config_fails_the_build_loudly(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(fleet.index_config_path(root), '[index]\nmode = "tracked"\n')
        assert fleet.main(["index", "build", "--path", str(root)]) == 1
        assert "mode" in capsys.readouterr().err

    def test_shard_paths_are_forward_slashed_in_output(self, tmp_path, capsys):
        root = _project(tmp_path, {"deep/er/a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        out = capsys.readouterr().out
        assert "deep/er/a.py" in out
        assert "deep\\er" not in out


class TestIndexUpdate:
    def test_refreshes_only_the_named_files(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(root / "a.py", "X = 9\n")
        _write(root / "b.py", "Y = 9\n")
        fleet.main(["index", "update", "--path", str(root), "--files", "a.py"])
        assert fleet.verified_shard_rows(root, "a.py", no_write=True)["status"] == "ok"
        assert (fleet.verified_shard_rows(root, "b.py", no_write=True)["status"]
                == "withheld")

    def test_a_comma_list_names_several(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n", "b.py": "Y = 2\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(root / "a.py", "X = 9\n")
        _write(root / "b.py", "Y = 9\n")
        fleet.main(["index", "update", "--path", str(root), "--files", "a.py,b.py"])
        for rel in ("a.py", "b.py"):
            assert fleet.verified_shard_rows(root, rel, no_write=True)["status"] == "ok"

    def test_refreshes_a_named_file_even_when_its_shard_looks_current(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        shard = fleet.shard_path_for_source(root, "a.py")
        shard.write_bytes(b"garbage\n")
        fleet.main(["index", "update", "--path", str(root), "--files", "a.py"])
        assert fleet.read_shard(shard) is not None

    def test_a_deleted_named_file_prunes_its_orphan_shard_and_warns(
            self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        (root / "a.py").unlink()
        assert fleet.main(
            ["index", "update", "--path", str(root), "--files", "a.py"]) == 0
        assert not fleet.shard_path_for_source(root, "a.py").exists()
        assert "a.py" in capsys.readouterr().err

    def test_a_path_outside_the_root_is_refused(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        rc = fleet.main(["index", "update", "--path", str(root), "--files", "../x.py"])
        assert rc == 1
        assert "outside" in capsys.readouterr().err

    def test_an_unselected_path_is_skipped_with_a_warning(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.rs": "fn main() {}\n"})
        fleet.main(["index", "init", "--path", str(root)])
        capsys.readouterr()
        assert fleet.main(
            ["index", "update", "--path", str(root), "--files", "a.rs"]) == 0
        assert "a.rs" in capsys.readouterr().err
        assert not fleet.shard_path_for_source(root, "a.rs").exists()

    def test_an_empty_file_list_is_an_error(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        assert fleet.main(["index", "update", "--path", str(root), "--files", " , "]) == 1

    def test_files_is_the_flag_name_not_paths(self):
        # §6 renamed --paths to --files deliberately; a silent revival would
        # give `--path` three meanings across the CLI.
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["index", "update", "--paths", "a.py"])


class TestIndexStatus:
    def test_reports_counts_and_writes_nothing(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "def f():\n    pass\n", "b.md": "# H\n"})
        fleet.main(["index", "init", "--path", str(root)])
        before = _tree(root)
        capsys.readouterr()
        assert fleet.main(["index", "status", "--path", str(root)]) == 0
        out = capsys.readouterr().out
        assert "shards 2" in out
        assert "symbols 2" in out
        assert "stale 0" in out
        assert _tree(root) == before

    def test_names_the_stale_and_orphan_shards(self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n", "gone.py": "Y = 2\n",
                                   "fresh.py": "Z = 3\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(root / "a.py", "X = 2\n")
        (root / "gone.py").unlink()
        _write(root / "new.py", "W = 4\n")
        capsys.readouterr()
        fleet.main(["index", "status", "--path", str(root)])
        out = capsys.readouterr().out
        assert "stale 1" in out and "orphan 1" in out and "unindexed 1" in out
        assert "stale a.py" in out
        assert "orphan gone.py" in out
        assert "unindexed new.py" in out

    def test_status_does_not_repair_a_stale_shard(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        _write(root / "a.py", "X = 2\n")
        before = _tree(root)
        fleet.main(["index", "status", "--path", str(root)])
        assert _tree(root) == before


# ---------------------------------------------------------------------------
# §9 -- the safety property: the index is strictly additive
# ---------------------------------------------------------------------------

class TestSafetyProperty:
    def test_the_index_family_touches_no_fleet_state(self, tmp_path, monkeypatch):
        # Invariant 9: no registry, no fleet.lock, no mailbox, no PID probe.
        # Asserted structurally -- FLEET_HOME is an empty directory and must
        # still be empty once the whole family has run.
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(fleet, "FLEET_HOME", home)
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        for argv in (["index", "init"], ["index", "build"],
                     ["index", "update", "--files", "a.py"], ["index", "status"]):
            assert fleet.main(argv + ["--path", str(root)]) == 0
        assert list(home.iterdir()) == []

    def test_deleting_the_index_returns_fleet_to_baseline_with_no_errors(
            self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        shutil.rmtree(fleet.index_dir(root))
        # The project is untouched apart from the .gitignore line, discovery
        # reports no index, and the read path raises nothing.
        assert sorted(p.name for p in root.iterdir()) == [".gitignore", "a.py"]
        assert fleet.find_index_root(root) is None
        capsys.readouterr()
        assert fleet.main(["index", "status", "--path", str(root)]) != 0
        assert "fleet index init" in capsys.readouterr().err

    def test_no_temp_files_survive_a_build(self, tmp_path):
        root = _project(tmp_path, {"a.py": PY_SAMPLE, "b.md": MD_SAMPLE})
        fleet.main(["index", "init", "--path", str(root)])
        assert _tmp_leftovers(root) == []


# ---------------------------------------------------------------------------
# The 3.10 floor: `tomllib` is 3.11+, so it may not be imported
# ---------------------------------------------------------------------------

class TestIndexHoldsTheInterpreterFloor:
    def test_fleet_imports_no_module_newer_than_the_floor(self):
        import ast as _ast
        source = _read(Path(fleet.__file__))
        imported = set()
        for node in _ast.walk(_ast.parse(source)):
            if isinstance(node, _ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, _ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        # `tomllib` landed in 3.11; fleet.MIN_PYTHON_VERSION is (3, 10), so an
        # import of it would pass every grep and break the floor at runtime.
        # This repo has been bitten twice by exactly that shape.
        assert fleet.MIN_PYTHON_VERSION < (3, 11)
        assert "tomllib" not in imported

    def test_the_hand_written_parser_is_what_replaces_it(self, tmp_path):
        _write(tmp_path / ".fleet-index" / "config.toml",
               fleet.INDEX_CONFIG_DEFAULT_TOML)
        assert fleet.load_index_config(tmp_path) == fleet.INDEX_CONFIG_DEFAULTS
