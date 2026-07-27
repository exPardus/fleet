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
