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
import subprocess
import threading
import time
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
        #
        # Asserted on the STRING, not on the two Path objects: on win32
        # `Path("bin\\fleet.py")` already splits on the backslash, so the
        # Path-equality form passed with the normalisation deleted -- it was
        # testing pathlib on the only platform that runs it, and would have
        # gone red only on POSIX, where the bug it guards cannot occur.
        assert fleet._index_posix_rel("bin\\fleet.py") == "bin/fleet.py"
        assert fleet._index_posix_rel(".\\bin\\\\deep\\a.py") == "bin/deep/a.py"
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
        header = {"sha": "a3f21c8e5b04d917", "lines": 120, "lang": "python"}
        rows = [("alpha", 12, 28, "func", "(x: int) -> str"),
                ("Beta", 31, 95, "class", "")]
        assert fleet.render_shard(header, rows) == (
            "#\ta3f21c8e5b04d917\t120\tpython\n"
            "alpha\t12\t28\tfunc\t(x: int) -> str\n"
            "Beta\t31\t95\tclass\t\n"
        )

    def test_header_only_shard_is_just_the_header_line(self):
        header = {"sha": "0000000000000000", "lines": 0, "lang": "text"}
        assert fleet.render_shard(header, []) == "#\t0000000000000000\t0\ttext\n"

    def test_rows_are_sorted_by_line(self):
        header = {"sha": "a3f21c8e5b04d917", "lines": 9, "lang": "python"}
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
        #
        # The rows come from PARSING a tabbed source, not from calling
        # `_index_tsv_field` here. Calling the escaper in the test made the
        # assertion true by construction: with sanitisation deleted from the
        # parser this test still passed, because the test was doing the
        # parser's job for it. `TestParseTimeSanitisation` below is the
        # end-to-end pin; this one keeps the render/read half.
        src = _write(tmp_path / "d.md", "## a\tb\n")
        rows = fleet.parse_source_symbols(src, "markdown")
        assert rows == [("a\\tb", 1, 1, "section", "")]
        header = fleet.source_header(src, "d.md")
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
    def test_sha_is_the_leading_hex_of_the_sha256_of_the_bytes(self, tmp_path):
        import hashlib
        src = _write(tmp_path / "a.py", "X = 1\n")
        want = hashlib.sha256(b"X = 1\n").hexdigest()[:fleet.INDEX_SHA_HEX_LEN]
        assert fleet.source_header(src, "a.py")["sha"] == want

    def test_line_count_and_lang(self, tmp_path):
        src = _write(tmp_path / "a.py", "X = 1\nY = 2\n")
        assert fleet.source_header(src, "a.py") == {
            "sha": fleet.source_header(src, "a.py")["sha"], "lines": 2, "lang": "python"}

    def test_empty_file_is_zero_lines(self, tmp_path):
        src = _write(tmp_path / "a.py", "")
        assert fleet.source_header(src, "a.py")["lines"] == 0

    def test_the_hash_is_over_BYTES_never_over_decoded_text(self, tmp_path):
        # The pin against hashing `read_text()`: universal newlines translate
        # CRLF to LF while decoding, so a text hash cannot tell the two files
        # apart -- and their line NUMBERS are identical, so nothing downstream
        # would catch it either. A CRLF/LF change is a real change to every
        # consumer of a byte offset, and it must invalidate the shard.
        import hashlib
        crlf = tmp_path / "crlf.py"
        crlf.write_bytes(b"X = 1\r\nY = 2\r\n")
        lf = tmp_path / "lf.py"
        lf.write_bytes(b"X = 1\nY = 2\n")
        assert (fleet.source_header(crlf, "crlf.py")["sha"]
                == hashlib.sha256(b"X = 1\r\nY = 2\r\n")
                .hexdigest()[:fleet.INDEX_SHA_HEX_LEN])
        assert (fleet.source_header(crlf, "crlf.py")["sha"]
                != fleet.source_header(lf, "lf.py")["sha"])
        # ...and both are still 2 lines, so `lines` cannot be the thing that
        # notices. The hash is.
        assert fleet.source_header(crlf, "crlf.py")["lines"] == 2
        assert fleet.source_header(lf, "lf.py")["lines"] == 2

    def test_a_source_that_is_not_utf8_still_gets_a_header(self, tmp_path):
        # Second half of the same pin: decoding at header time would have to
        # choose between raising (a build abort) and lossy replacement (a hash
        # that no longer identifies the file). Hashing bytes has neither
        # problem, and §6 wants a header-only shard here.
        import hashlib
        src = tmp_path / "bin.py"
        src.write_bytes(b"\xff\xfe\x00def x(\n")
        assert (fleet.source_header(src, "bin.py")["sha"]
                == hashlib.sha256(b"\xff\xfe\x00def x(\n")
                .hexdigest()[:fleet.INDEX_SHA_HEX_LEN])

    def test_a_CRLF_to_LF_rewrite_is_seen_as_stale(self, tmp_path):
        # The property the two above exist for, end to end.
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        (root / "a.py").write_bytes(b"def f():\r\n    pass\r\n")
        first = fleet.verified_shard_rows(root, "a.py")
        assert first["refreshed"] is True
        (root / "a.py").write_bytes(b"def f():\n    pass\n")
        second = fleet.verified_shard_rows(root, "a.py")
        assert second["refreshed"] is True


class TestShaWidth:
    """M1's widening, pinned against a measured collision (§5).

    The pair below is not synthetic: it came out of a search over 109,096
    two-line modules -- under a second of CPU -- for two sources sharing the
    first 8 hex of their SHA-256. They also share a line count and a language,
    which is the REST of the staleness key, so under an 8-hex header swapping
    one for the other is invisible: the shard verifies, `refreshed` is False,
    `index status` reports 0 stale, and the worker is served the wrong file's
    symbols."""

    A = "sym_96178 = 1\nVALUE = 96178\n"
    B = "sym_109095 = 1\nVALUE = 109095\n"

    def test_the_collision_pair_really_collides_at_eight_hex(self):
        import hashlib
        digests = [hashlib.sha256(body.encode("utf-8")).hexdigest()
                   for body in (self.A, self.B)]
        assert digests[0][:8] == digests[1][:8]
        assert digests[0] != digests[1]

    def test_the_header_is_wide_enough_to_tell_them_apart(self, tmp_path):
        a = _write(tmp_path / "a.py", self.A)
        b = _write(tmp_path / "b.py", self.B)
        assert fleet.source_header(a, "a.py") != fleet.source_header(b, "b.py")
        assert len(fleet.source_header(a, "a.py")["sha"]) == fleet.INDEX_SHA_HEX_LEN

    def test_swapping_the_colliding_twin_is_detected_and_repaired(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": self.A})
        assert [r[0] for r in fleet.verified_shard_rows(root, "a.py")["rows"]] == [
            "sym_96178", "VALUE"]
        _write(root / "a.py", self.B)
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["refreshed"] is True
        assert [r[0] for r in got["rows"]] == ["sym_109095", "VALUE"]
        assert fleet.index_status(root)["stale"] == []

    def test_a_shard_written_by_the_eight_hex_draft_is_not_readable(self, tmp_path):
        # Migration, in one line: an old shard fails `read_shard`, so it takes
        # the stale path and the first read repairs it. No migration command,
        # no version column.
        shard = tmp_path / "s.tsv"
        shard.write_bytes(b"#\ta3f21c8e\t9\tpython\nalpha\t1\t2\tfunc\t()\n")
        assert fleet.read_shard(shard) is None


# ---------------------------------------------------------------------------
# §5/§9 -- reading a shard, and what counts as corrupt
# ---------------------------------------------------------------------------

class TestReadShard:
    def _good(self, tmp_path):
        shard = tmp_path / "s.tsv"
        shard.write_bytes(
            b"#\ta3f21c8e5b04d917\t9\tpython\nalpha\t1\t2\tfunc\t()\n")
        return shard

    def test_reads_header_and_rows(self, tmp_path):
        assert fleet.read_shard(self._good(tmp_path)) == (
            {"sha": "a3f21c8e5b04d917", "lines": 9, "lang": "python"},
            [("alpha", 1, 2, "func", "()")])

    def test_missing_shard_is_not_readable(self, tmp_path):
        assert fleet.read_shard(tmp_path / "absent.tsv") is None

    @pytest.mark.parametrize("blob", [
        b"",                                                    # empty
        b"alpha\t1\t2\tfunc\t()\n",                             # no header line
        b"#\ta3f21c8e5b04d917\t9\n",                            # short header
        b"#\tZZZZZZZZZZZZZZZZ\t9\tpython\n",                    # non-hex sha
        b"#\ta3f21c8e\t9\tpython\n",                            # 8-hex sha
        b"#\ta3f21c8e5b04d9170\t9\tpython\n",                   # 17-hex sha
        b"#\ta3f21c8e5b04d917\tmany\tpython\n",                 # non-int count
        b"#\ta3f21c8e5b04d917\t9\tpython\nalpha\t1\t2\tfunc\n",  # short row
        b"#\ta3f21c8e5b04d917\t9\tpython\nalpha\tx\t2\tfunc\t()\n",  # non-int line
        b"#\ta3f21c8e5b04d917\t9\tpython\nalpha\t1\t2\twidget\t()\n",  # bad kind
        b"#\ta3f21c8e5b04d917\t9\tpython\nalpha\t1\t2\tfunc\t()",  # torn: no LF
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

HEADER_A = {"sha": "aaaaaaaaaaaaaaaa", "lines": 1, "lang": "python"}
HEADER_B = {"sha": "bbbbbbbbbbbbbbbb", "lines": 2, "lang": "python"}


class TestAtomicShardWrite:
    def test_writes_the_rendered_bytes_and_creates_parents(self, tmp_path):
        shard = tmp_path / ".fleet-index" / "symbols" / "bin" / "a.py.tsv"
        assert fleet.write_shard_atomic(shard, HEADER_A, []) is True
        assert _read(shard) == "#\taaaaaaaaaaaaaaaa\t1\tpython\n"

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

    def test_any_other_oserror_abandons_too_instead_of_escaping(
            self, tmp_path, monkeypatch):
        # `PermissionError` was the only OSError this caught, so every other
        # one escaped `write_shard_atomic` and, through it, the
        # `verified_shard_rows` choke point -- which M2 hands a
        # caller-supplied path (`q --outline <path>`). A caller-supplied path
        # reaches shapes a build never does: on win32 a source named `nul.py`
        # renders a shard path `os.replace` refuses with `FileExistsError`.
        shard = tmp_path / "s.tsv"
        fleet.write_shard_atomic(shard, HEADER_A, [])
        before = shard.read_bytes()

        def deny(src, dst):
            raise FileExistsError(17, "cannot create a file that already exists")

        monkeypatch.setattr(fleet.os, "replace", deny)
        assert fleet.write_shard_atomic(
            shard, HEADER_B, [], sleep=lambda _d: None) is False
        assert shard.read_bytes() == before
        assert _tmp_leftovers(tmp_path) == []

    def test_the_choke_point_answers_through_a_non_permission_oserror(
            self, tmp_path, monkeypatch):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})

        def deny(src, dst):
            raise FileExistsError(17, "cannot create a file that already exists")

        monkeypatch.setattr(fleet.os, "replace", deny)
        got = fleet.verified_shard_rows(root, "a.py", sleep=lambda _d: None)
        assert got["status"] == "ok"
        assert got["written"] is False
        assert got["rows"] == [("f", 1, 2, "func", "()")]

    def test_a_non_oserror_still_propagates(self, tmp_path, monkeypatch):
        # The widening stops at OSError. A bug in this module is not a hazard
        # to swallow behind a "the shard stayed stale" return value.
        shard = tmp_path / "s.tsv"

        class Boom(RuntimeError):
            pass

        def explode(tmp_name, dest, sleep=None):
            raise Boom("not an OSError")

        monkeypatch.setattr(fleet, "_replace_with_retry", explode)
        with pytest.raises(Boom):
            fleet.write_shard_atomic(shard, HEADER_A, [])
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
        assert _read(shard) == "#\tbbbbbbbbbbbbbbbb\t2\tpython\n"


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
        header = {"sha": "a3f21c8e5b04d917", "lines": 120, "lang": "python"}
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
        header = {"sha": "a3f21c8e5b04d917", "lines": 3, "lang": "rs"}
        assert fleet.render_digest("a.rs", header, []) == "## a.rs (3 lines, rs)\n"

    def test_const_and_section_render_bare(self):
        header = {"sha": "a3f21c8e5b04d917", "lines": 9, "lang": "markdown"}
        rows = [("Intro", 1, 4, "section", ""), ("GAMMA", 7, 7, "const", "")]
        assert fleet.render_digest("d.md", header, rows) == (
            "## d.md (9 lines, markdown)\n"
            "- L1 Intro\n"
            "- L7 GAMMA\n"
        )

    def test_rendering_is_uncapped(self):
        # The 400-line cap is `q`'s concern, not the renderer's (§11.4).
        header = {"sha": "a3f21c8e5b04d917", "lines": 999, "lang": "python"}
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


def _fake_checkout(root):
    """The `.git` directory shape of an ordinary checkout."""
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return root / ".git" / "info" / "exclude"


class TestIndexInit:
    def test_creates_the_index_config_and_exclude_entry_then_builds(self, tmp_path):
        root = _project(tmp_path, {"a.py": "def f():\n    pass\n"})
        exclude = _fake_checkout(root)
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert fleet.index_symbols_dir(root).is_dir()
        assert (fleet.index_config_path(root).read_bytes()
                == fleet.INDEX_CONFIG_DEFAULT_TOML.encode("utf-8"))
        assert _read(exclude).splitlines() == [".fleet-index/"]
        assert fleet.shard_path_for_source(root, "a.py").is_file()

    def test_the_tracked_gitignore_is_never_touched(self, tmp_path):
        # THE M3 pin. `.gitignore` is tracked, and §8 mandates `fleet index
        # init --path <worktree>` for every campaign worktree -- so writing
        # there left every one of them dirty and un-removable. Measured, not
        # theoretical: `git worktree remove` refuses with "contains modified
        # or untracked files" (see the git-backed test below).
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        _fake_checkout(root)
        _write(root / ".gitignore", "*.log\n")
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert _read(root / ".gitignore") == "*.log\n"

    def test_appends_to_an_existing_exclude_without_clobbering_it(self, tmp_path):
        root = _project(tmp_path, {"a.py": ""})
        exclude = _fake_checkout(root)
        _write(exclude, "*.log\nbuild/\n")
        fleet.main(["index", "init", "--path", str(root)])
        assert _read(exclude) == "*.log\nbuild/\n.fleet-index/\n"

    def test_adds_a_final_newline_when_the_exclude_lacks_one(self, tmp_path):
        root = _project(tmp_path, {"a.py": ""})
        exclude = _fake_checkout(root)
        _write(exclude, "*.log")
        fleet.main(["index", "init", "--path", str(root)])
        assert _read(exclude) == "*.log\n.fleet-index/\n"

    def test_is_idempotent_and_never_duplicates_the_entry(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        exclude = _fake_checkout(root)
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert _read(exclude).count(".fleet-index/") == 1

    def test_the_entry_is_written_even_when_the_index_already_exists(self, tmp_path):
        # "unconditionally" (§8): a project whose entry was deleted by hand
        # gets it back on the next init, index present or not.
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        exclude = _fake_checkout(root)
        fleet.main(["index", "init", "--path", str(root)])
        exclude.unlink()
        fleet.main(["index", "init", "--path", str(root)])
        assert ".fleet-index/" in _read(exclude)

    def test_a_linked_worktree_writes_into_the_common_dir(self, tmp_path):
        # A linked worktree's `.git` is a FILE, and `info/` is a COMMON path,
        # so the entry belongs to the parent clone -- where it covers every
        # worktree of that repository at once.
        parent = _project(tmp_path, {"x.py": "X = 1\n"})
        common = parent / ".git"
        (common / "worktrees" / "w1").mkdir(parents=True)
        (common / "worktrees" / "w1" / "commondir").write_bytes(b"../..\n")
        worktree = _project(tmp_path / "wt", {"a.py": "X = 1\n"})
        (worktree / ".git").write_bytes(
            ("gitdir: " + str(common / "worktrees" / "w1") + "\n").encode("utf-8"))
        assert fleet.main(["index", "init", "--path", str(worktree)]) == 0
        assert ".fleet-index/" in _read(common / "info" / "exclude")
        assert not (worktree / ".gitignore").exists()

    def test_a_project_that_is_not_a_checkout_falls_back_to_gitignore(self, tmp_path):
        # Nothing is tracked outside a repository, so there is no file to
        # dirty -- and a later `git init` starts out already ignoring it.
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert _read(root / ".gitignore").splitlines() == [".fleet-index/"]

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
# §11.2 -- containment: a path handed to the index names a file INSIDE it
#
# These are ATTACKS, not unit tests, and the difference is load-bearing. The
# defect they pin was reproduced on a build whose own test asserted only an
# exit code -- the deleting build returned a non-zero code with a note that
# read like ordinary housekeeping, and the assertion passed. So every test
# here plants a REAL file and a REAL directory outside the index root, aims a
# traversal at them, and asserts THE FILE IS STILL THERE.
# ---------------------------------------------------------------------------

def _victim(tmp_path):
    """A real file and a real directory outside any index root."""
    victim_dir = tmp_path / "victim"
    victim_dir.mkdir(parents=True, exist_ok=True)
    precious = victim_dir / "precious.tsv"
    precious.write_bytes(b"do not delete\n")
    return victim_dir, precious


def _link_dir(link, target):
    """A directory reparse point -- symlink where that works, junction on
    win32, where an unprivileged symlink is refused but `mklink /J` is not.
    False if this platform will make neither."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return os.path.isdir(link)
    except (OSError, NotImplementedError, AttributeError):
        pass
    if os.name != "nt":
        return False
    try:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True)
    except OSError:
        return False
    return os.path.isdir(link)


# `<root>/.fleet-index/symbols/` + this = `<tmp_path>/victim/precious.tsv`,
# with the escape hidden in the MIDDLE of the path -- the shape the old
# "rejects a leading `../`" guard waved through.
ESCAPE_INTERIOR = "a/../../../../victim/precious"
ESCAPE_LEADING = "../../../victim/precious"


class TestPathContainment:
    @pytest.mark.parametrize("rel", [ESCAPE_INTERIOR, ESCAPE_LEADING])
    def test_the_choke_point_refuses_and_the_victim_survives(self, tmp_path, rel):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        victim_dir, precious = _victim(tmp_path)
        assert fleet.shard_path_for_source(root, "x").parent.resolve() \
            == fleet.index_symbols_dir(root).resolve()
        with pytest.raises(fleet.IndexPathError):
            fleet.verified_shard_rows(root, rel)
        assert precious.is_file()
        assert precious.read_bytes() == b"do not delete\n"
        assert victim_dir.is_dir()

    @pytest.mark.parametrize("rel", [ESCAPE_INTERIOR, ESCAPE_LEADING])
    def test_the_update_cli_refuses_and_the_victim_survives(
            self, tmp_path, capsys, rel):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        victim_dir, precious = _victim(tmp_path)
        capsys.readouterr()
        rc = fleet.main(["index", "update", "--path", str(root), "--files", rel])
        assert rc == 1
        assert "outside" in capsys.readouterr().err
        assert precious.is_file()
        assert victim_dir.is_dir()

    @pytest.mark.parametrize("rel", [ESCAPE_INTERIOR, ESCAPE_LEADING])
    def test_the_library_surface_refuses_too(self, tmp_path, rel):
        # `update_index` bypasses the CLI's argument parsing entirely. The
        # guard lives in the primitive, so this surface is closed by the same
        # repair rather than by a second copy of the check.
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        victim_dir, precious = _victim(tmp_path)
        with pytest.raises(fleet.IndexPathError):
            fleet.update_index(root, [rel])
        assert precious.is_file()
        assert victim_dir.is_dir()

    def test_building_a_shard_path_at_all_is_refused(self, tmp_path):
        with pytest.raises(fleet.IndexPathError):
            fleet.shard_path_for_source(tmp_path, ESCAPE_INTERIOR)

    @pytest.mark.parametrize("rel", ["..", "../x", "a/../../b", "a/..", "a\\..\\..\\b"])
    def test_a_dotdot_segment_anywhere_is_refused(self, rel):
        with pytest.raises(fleet.IndexPathError):
            fleet._index_posix_rel(rel)

    def test_a_plain_relative_path_is_still_ordinary(self):
        assert fleet._index_posix_rel("./a/b.py") == "a/b.py"
        assert fleet._index_posix_rel("a/..b/c.py") == "a/..b/c.py"

    def test_an_absolute_path_outside_the_root_is_still_refused(
            self, tmp_path, capsys):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        victim_dir, precious = _victim(tmp_path)
        capsys.readouterr()
        assert fleet.main(["index", "update", "--path", str(root),
                           "--files", str(precious)]) == 1
        assert "outside" in capsys.readouterr().err
        assert precious.is_file()

    def test_a_junctioned_mirror_directory_is_not_pruned_through(self, tmp_path):
        # The second half of the same defect, and the half a `..` check cannot
        # reach: `stop in current.parents` is a comparison of SPELLINGS. A
        # reparse point inside the shard tree is spelled inside it and lives
        # outside it, so the unlink and then the rmdir walk-up leave the root
        # entirely -- while every string in the code still looks contained.
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        victim_dir, precious = _victim(tmp_path)
        symbols = fleet.index_symbols_dir(root)
        symbols.mkdir(parents=True, exist_ok=True)
        if not _link_dir(symbols / "sub", victim_dir):
            pytest.skip("this platform will not create a directory reparse point")
        # The attack is real: that path IS the victim file, reached from
        # inside the shard tree with no `..` anywhere.
        assert (symbols / "sub" / "precious.tsv").read_bytes() == b"do not delete\n"
        assert fleet._index_prune_shard(root, "sub/precious") is False
        assert precious.is_file()
        assert victim_dir.is_dir()

    def test_an_ordinary_orphan_is_still_pruned_and_its_directory_removed(
            self, tmp_path):
        # The containment guard must not turn into a prune that never prunes.
        root = _indexed_tree(tmp_path, {"deep/er/a.py": "X = 1\n"})
        fleet.verified_shard_rows(root, "deep/er/a.py")
        shard = fleet.shard_path_for_source(root, "deep/er/a.py")
        assert shard.is_file()
        assert fleet._index_prune_shard(root, "deep/er/a.py") is True
        assert not shard.exists()
        assert not shard.parent.exists()
        assert not shard.parent.parent.exists()
        assert fleet.index_symbols_dir(root).is_dir()


# ---------------------------------------------------------------------------
# §8 -- the source is read ONCE, so a shard can never carry A's header over
# B's rows
# ---------------------------------------------------------------------------

def _atomic_source_write(path, raw):
    """Replace a source file's bytes atomically, so a concurrent reader always
    observes one whole version and never a partial write."""
    tmp = path.parent / (path.name + ".churn")
    try:
        tmp.write_bytes(raw)
        for _ in range(400):
            try:
                os.replace(str(tmp), str(path))
                return
            except PermissionError:
                time.sleep(0.001)
    except OSError:
        pass


class TestTheSourceIsReadOnce:
    A = "def alpha():\n    pass\n"
    B = "\n\n\ndef beta():\n    pass\n"
    # Bigger bodies for the concurrency probe: the race window is the gap
    # between the hash and the parse, and `read_shard` sits inside it -- so a
    # file with many symbols (a fat shard to read back) widens the window
    # without touching a line of production code.
    BIG_A = "".join("def a_%d():\n    pass\n" % i for i in range(200))
    BIG_B = "\n\n" + "".join("def b_%d():\n    pass\n" % i for i in range(200))

    def test_a_write_between_the_hash_and_the_parse_cannot_tear_the_shard(
            self, tmp_path, monkeypatch):
        # The race window, forced open rather than waited for. The write is
        # real and lands exactly where the second read used to be. With one
        # read the parse still describes the bytes that were hashed; with two
        # it describes the file that replaced them, and the shard that gets
        # written is header(A) over rows(B) -- which verifies CLEAN the moment
        # the tree returns to A, forever.
        root = _indexed_tree(tmp_path, {"a.py": self.A})
        real = fleet.parse_source_symbols

        def parse_after_a_concurrent_write(source_path, lang=None, raw=None):
            _write(root / "a.py", self.B)
            return real(source_path, lang, raw)

        monkeypatch.setattr(fleet, "parse_source_symbols",
                            parse_after_a_concurrent_write)
        got = fleet.verified_shard_rows(root, "a.py")
        assert [r[0] for r in got["rows"]] == ["alpha"]
        header, rows = fleet.read_shard(fleet.shard_path_for_source(root, "a.py"))
        assert header == fleet.header_for_bytes(self.A.encode("utf-8"), "a.py")
        assert [r[0] for r in rows] == ["alpha"]

    def test_the_build_path_reads_once_too(self, tmp_path, monkeypatch):
        # `_index_refresh_one` had the identical two-read shape, and it is the
        # path a MANAGER runs while a worker edits the tree -- the likelier of
        # the two to meet a concurrent writer, not the rarer.
        root = _project(tmp_path, {"a.py": self.A})
        fleet.main(["index", "init", "--path", str(root)])
        real = fleet.parse_source_symbols

        def parse_after_a_concurrent_write(source_path, lang=None, raw=None):
            _write(root / "a.py", self.B)
            return real(source_path, lang, raw)

        monkeypatch.setattr(fleet, "parse_source_symbols",
                            parse_after_a_concurrent_write)
        fleet.main(["index", "build", "--path", str(root), "--force"])
        header, rows = fleet.read_shard(fleet.shard_path_for_source(root, "a.py"))
        assert header == fleet.header_for_bytes(self.A.encode("utf-8"), "a.py")
        assert [r[0] for r in rows] == ["alpha"]

    def test_a_concurrent_writer_never_persists_a_torn_shard(self, tmp_path):
        # The same defect without any injection at all: a writer thread
        # flipping one file between two versions while the choke point
        # refreshes it. Measured at 2,037 torn shards in 9,811 refreshes (21%)
        # on the two-read build.
        root = _indexed_tree(tmp_path, {"a.py": self.BIG_A})
        shard = fleet.shard_path_for_source(root, "a.py")
        expected = {}
        for body in (self.BIG_A, self.BIG_B):
            raw = body.encode("utf-8")
            expected[fleet.header_for_bytes(raw, "a.py")["sha"]] = [
                r[0] for r in fleet.parse_source_symbols(
                    root / "a.py", "python", raw=raw)]
        stop = threading.Event()

        def churn():
            flip = 0
            while not stop.is_set():
                body = self.BIG_A if flip % 2 else self.BIG_B
                _atomic_source_write(root / "a.py", body.encode("utf-8"))
                flip += 1

        writer = threading.Thread(target=churn, daemon=True)
        writer.start()
        try:
            for _ in range(600):
                got = fleet.verified_shard_rows(root, "a.py")
                if got["status"] == "ok":
                    assert [r[0] for r in got["rows"]] \
                        == expected[got["header"]["sha"]]
                on_disk = fleet.read_shard(shard)
                if on_disk is not None:
                    assert [r[0] for r in on_disk[1]] \
                        == expected[on_disk[0]["sha"]]
        finally:
            stop.set()
            writer.join(timeout=10)


# ---------------------------------------------------------------------------
# §8 -- the staleness key is the WHOLE header, not just the hash
# ---------------------------------------------------------------------------

class TestHeaderComparisonUsesEveryColumn:
    """`existing[0] == header`, and each column earns its place.

    Not a hypothetical: this wave changed how `lines` is counted (a CR-only
    file used to count as one line while `ast` numbered its symbols 1..N), so
    shards written by the previous rule carry the SAME hash and a different
    line count. A hash-only comparison serves those shards forever."""

    def _corrupt_header_column(self, shard, index, value):
        head, _, body = _read(shard).partition("\n")
        fields = head.split("\t")
        fields[index] = value
        shard.write_bytes(("\t".join(fields) + "\n" + body).encode("utf-8"))

    @pytest.mark.parametrize("index,value", [(2, "99"), (3, "rust")])
    def test_a_matching_hash_with_another_column_wrong_is_stale(
            self, tmp_path, index, value):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        shard = fleet.shard_path_for_source(root, "a.py")
        self._corrupt_header_column(shard, index, value)
        assert fleet.read_shard(shard) is not None      # readable, just wrong
        got = fleet.verified_shard_rows(root, "a.py")
        assert got["refreshed"] is True
        assert fleet.read_shard(shard)[0] == fleet.source_header(
            root / "a.py", "a.py")

    @pytest.mark.parametrize("index,value", [(2, "99"), (3, "rust")])
    def test_status_reports_it_stale_too(self, tmp_path, index, value):
        root = _indexed_tree(tmp_path, {"a.py": "def f():\n    pass\n"})
        fleet.verified_shard_rows(root, "a.py")
        self._corrupt_header_column(
            fleet.shard_path_for_source(root, "a.py"), index, value)
        assert fleet.index_status(root)["stale"] == ["a.py"]


# ---------------------------------------------------------------------------
# §5/§6 -- where a line ends, and where a field is escaped
# ---------------------------------------------------------------------------

class TestLineSplittingRule:
    def test_only_the_three_real_terminators_split_a_line(self):
        assert fleet._index_split_lines("a\r\nb\rc\nd") == ["a", "b", "c", "d"]
        assert fleet._index_split_lines("a\n") == ["a"]
        assert fleet._index_split_lines("") == []
        # `str.splitlines()` breaks on all of these; nothing else in the
        # toolchain does -- not `bytes.splitlines`, not `ast`, not git.
        for exotic in ("\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85",
                       "\u2028", "\u2029"):
            assert fleet._index_split_lines("a" + exotic + "b") == ["a" + exotic + "b"]

    def test_the_text_rule_and_the_byte_rule_agree(self):
        for body in ("a\nb\n", "a\r\nb\r\n", "a\rb\r", "a\nb", "", "a\x0cb\n"):
            assert len(fleet._index_split_lines(body)) \
                == len(body.encode("utf-8").splitlines())

    def test_a_form_feed_does_not_move_a_markdown_coordinate(self, tmp_path):
        src = _write(tmp_path / "d.md", "# A\npage\x0cbreak\n## B\ntail\n")
        assert fleet.parse_source_symbols(src, "markdown") == [
            ("A", 1, 4, "section", ""), ("B", 3, 4, "section", "")]
        assert fleet.source_header(src, "d.md")["lines"] == 4

    def test_a_CR_only_python_source_counts_the_lines_its_parser_numbers(
            self, tmp_path):
        src = tmp_path / "a.py"
        src.write_bytes(b"A = 1\rB = 2\rC = 3\rD = 4\rE = 5\r")
        header = fleet.source_header(src, "a.py")
        rows = fleet.parse_source_symbols(src, "python")
        assert header["lines"] == 5
        assert rows[-1] == ("E", 5, 5, "const", "")
        # The defect stated as the property it broke: a shard's own rows may
        # not cite a line past the end its own header declares.
        assert max(r[2] for r in rows) <= header["lines"]

    def test_a_CR_only_markdown_source_is_split_into_its_headings(self, tmp_path):
        src = tmp_path / "d.md"
        src.write_bytes(b"# a\r# b\r")
        assert fleet.parse_source_symbols(src, "markdown") == [
            ("a", 1, 1, "section", ""), ("b", 2, 2, "section", "")]
        assert fleet.source_header(src, "d.md")["lines"] == 2


class TestParseTimeSanitisation:
    """Escaping happens in the PARSER, and the pin is a parsed source.

    The previous test called `_index_tsv_field` in the test body and compared
    the result to itself through render/read -- so deleting the escape from
    `parse_source_symbols` left it green. What the escape actually buys is
    that a fresh parse and a shard read return the SAME rows; that is only
    observable end to end."""

    def test_a_tab_in_a_heading_is_escaped_by_the_parser(self, tmp_path):
        src = _write(tmp_path / "d.md", "## a\tb\n")
        assert fleet.parse_source_symbols(src, "markdown") == [
            ("a\\tb", 1, 1, "section", "")]

    def test_a_tabbed_source_survives_a_round_trip_through_a_shard(self, tmp_path):
        root = _indexed_tree(tmp_path, {"d.md": "# top\n## a\tb\n### c\td\n"})
        refreshed = fleet.verified_shard_rows(root, "d.md")
        cached = fleet.verified_shard_rows(root, "d.md")
        assert refreshed["refreshed"] is True and cached["refreshed"] is False
        assert refreshed["rows"] == cached["rows"]
        assert [r[0] for r in cached["rows"]] == ["top", "a\\tb", "c\\td"]
        # And the shard is still a five-column TSV: an unescaped tab would
        # have made the second row six fields, which `read_shard` rejects
        # outright -- the shard would read as corrupt on every single access.
        body = _read(fleet.shard_path_for_source(root, "d.md")).splitlines()[1:]
        assert all(len(line.split("\t")) == 5 for line in body)

    def test_a_newline_bearing_field_cannot_add_a_row(self, tmp_path):
        # Same class, other substitution: a stripped newline is what keeps one
        # symbol from rendering as two shard rows.
        assert fleet._index_tsv_field("a\r\nb") == "ab"


# ---------------------------------------------------------------------------
# §5/§8 -- the rows handed back do not depend on whether a refresh happened
# ---------------------------------------------------------------------------

class TestRowOrderIsStableAcrossARefresh:
    @pytest.mark.parametrize("body", ["ZED = ALPHA = 1\n", "ZED = 1; ALPHA = 2\n"])
    def test_cached_and_refreshed_answer_identically(self, tmp_path, body):
        root = _indexed_tree(tmp_path, {"a.py": body})
        refreshed = fleet.verified_shard_rows(root, "a.py")
        cached = fleet.verified_shard_rows(root, "a.py")
        assert refreshed["refreshed"] is True
        assert cached["refreshed"] is False
        assert refreshed["rows"] == cached["rows"]
        assert [r[0] for r in cached["rows"]] == ["ALPHA", "ZED"]

    def test_the_digest_does_not_change_across_a_refresh(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "ZED = ALPHA = 1\n"})
        refreshed = fleet.verified_shard_rows(root, "a.py")
        cached = fleet.verified_shard_rows(root, "a.py")
        assert fleet.render_digest("a.py", refreshed["header"], refreshed["rows"]) \
            == fleet.render_digest("a.py", cached["header"], cached["rows"])

    def test_the_parser_itself_emits_the_shard_order(self, tmp_path):
        # Repaired at the cause: there is one order, `_index_row_key`, and the
        # parser emits it. `render_shard`'s sort is then a no-op on real rows
        # rather than a second, divergent definition.
        src = _write(tmp_path / "a.py", "ZED = ALPHA = 1\n")
        rows = fleet.parse_source_symbols(src, "python")
        assert rows == sorted(rows, key=fleet._index_row_key)
        assert [r[0] for r in rows] == ["ALPHA", "ZED"]


# ---------------------------------------------------------------------------
# §11.1 -- the boundary rule, applied to the BUILD walking down
# ---------------------------------------------------------------------------

class TestBuildSideRepositoryBoundary:
    def test_a_nested_linked_worktree_is_not_indexed(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n",
                                        ".claude/worktrees/w1/b.py": "Y = 2\n"})
        (root / ".claude" / "worktrees" / "w1" / ".git").write_bytes(
            b"gitdir: /elsewhere/.git/worktrees/w1\n")
        assert fleet.index_source_files(root) == ["a.py"]

    def test_a_nested_git_directory_stops_the_walk_too(self, tmp_path):
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n", "vendor/dep/c.py": "Z = 3\n"})
        (root / "vendor" / "dep" / ".git").mkdir(parents=True)
        assert fleet.index_source_files(root) == ["a.py"]

    def test_the_root_itself_is_allowed_to_be_a_checkout(self, tmp_path):
        # The root nearly always IS one, so the fence tests entries BELOW the
        # root only -- which is what filtering `dirnames` rather than `dirpath`
        # buys.
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        (root / ".git").mkdir()
        assert fleet.index_source_files(root) == ["a.py"]

    def test_a_junction_does_not_leak_a_file_from_outside_the_root(self, tmp_path):
        outside = tmp_path / "outside"
        _write(outside / "leak.py", "SECRET = 1\n")
        root = _indexed_tree(tmp_path, {"a.py": "X = 1\n"})
        if not _link_dir(root / "linked", outside):
            pytest.skip("this platform will not create a directory reparse point")
        # `os.walk` does not follow a POSIX symlink, but it descends a win32
        # junction quite happily -- and the shard it writes claims the file
        # lives inside this root.
        assert (root / "linked" / "leak.py").is_file()
        assert fleet.index_source_files(root) == ["a.py"]
        fleet.main(["index", "build", "--path", str(root)])
        assert not fleet.shard_path_for_source(root, "linked/leak.py").exists()


# ---------------------------------------------------------------------------
# §8/§13 -- `init` may not dirty a tracked file
# ---------------------------------------------------------------------------

class TestAWorktreeStaysRemovableAfterInit:
    """§13 finding 2b, re-measured.

    That row disposed the dirty-tracked-file hazard as unreachable once
    tracked mode was cut. §8 then mandated `fleet index init --path <worktree>`
    for every campaign worktree, and `init` wrote to the tracked `.gitignore`
    -- so every worktree fleet creates became un-removable. This is the
    measurement, against real git, that the disposition was false."""

    def _git(self, git, *args, cwd, env):
        return subprocess.run([git, *args], cwd=str(cwd), env=env,
                              capture_output=True, text=True)

    def test_git_worktree_remove_still_works(self, tmp_path):
        git = shutil.which("git")
        if git is None:
            pytest.skip("git is not on PATH")
        env = dict(os.environ,
                   GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        repo = tmp_path / "repo"
        repo.mkdir()
        run = lambda *a, cwd=repo: self._git(git, *a, cwd=cwd, env=env)
        assert run("init", "-q").returncode == 0
        _write(repo / "a.py", "X = 1\n")
        _write(repo / ".gitignore", "*.log\n")       # TRACKED, as in a real repo
        assert run("add", "-A").returncode == 0
        assert run("commit", "-q", "-m", "seed").returncode == 0
        worktree = tmp_path / "wt"
        added = run("worktree", "add", "-q", str(worktree), "-b", "side")
        assert added.returncode == 0, added.stderr

        assert fleet.main(["index", "init", "--path", str(worktree)]) == 0
        assert fleet.shard_path_for_source(worktree, "a.py").is_file()

        status = run("status", "--porcelain", cwd=worktree)
        assert status.stdout == "", status.stdout
        removed = run("worktree", "remove", str(worktree))
        assert removed.returncode == 0, removed.stderr
        assert _read(repo / ".gitignore") == "*.log\n"


# ---------------------------------------------------------------------------
# §6/§9 -- a build that could not index a file does not exit 0
# ---------------------------------------------------------------------------

class TestIndexExitCodes:
    def test_build_exits_nonzero_when_a_file_failed(
            self, tmp_path, capsys, monkeypatch):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        monkeypatch.setattr(fleet, "write_shard_atomic", lambda *a, **kw: False)
        capsys.readouterr()
        assert fleet.main(["index", "build", "--path", str(root), "--force"]) == 1
        assert "failed 1" in capsys.readouterr().out

    def test_update_exits_nonzero_when_a_file_failed(
            self, tmp_path, capsys, monkeypatch):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        fleet.main(["index", "init", "--path", str(root)])
        monkeypatch.setattr(fleet, "write_shard_atomic", lambda *a, **kw: False)
        _write(root / "a.py", "X = 2\n")
        capsys.readouterr()
        assert fleet.main(
            ["index", "update", "--path", str(root), "--files", "a.py"]) == 1

    def test_init_exits_nonzero_when_its_first_build_failed(
            self, tmp_path, capsys, monkeypatch):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        monkeypatch.setattr(fleet, "write_shard_atomic", lambda *a, **kw: False)
        capsys.readouterr()
        assert fleet.main(["index", "init", "--path", str(root)]) == 1

    def test_a_clean_run_still_exits_zero(self, tmp_path):
        root = _project(tmp_path, {"a.py": "X = 1\n"})
        assert fleet.main(["index", "init", "--path", str(root)]) == 0
        assert fleet.main(["index", "build", "--path", str(root)]) == 0


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
