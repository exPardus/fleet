"""Source index and query operations; fleet supplies replace and parser capabilities."""
from __future__ import annotations

import ast
import fnmatch
import functools
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path, PureWindowsPath

from fleet_errors import FleetCliError

# The facade injects late-bound capabilities without sharing its home or claim
# state. Importing this module never imports the CLI or creates a parser.
_replace_with_retry = None
build_parser = None

# fleet-index shard layer (docs/specs/fleet-index.md). One path-mirrored
# shard per source keeps disjoint edits independent without a global table.
# The index uses only the target tree and its gitignored index, never fleet
# registry, locks, mailboxes or PID probes.

INDEX_DIR_NAME = ".fleet-index"
INDEX_SYMBOLS_DIR_NAME = "symbols"
INDEX_CONFIG_FILE_NAME = "config.toml"
INDEX_SHARD_SUFFIX = ".tsv"

# §5. `sig` carries the remainder of the line, so the column count is fixed at
# five and a row is parsed by a plain `split("\t")` with no quoting rules.
SHARD_KINDS = ("func", "class", "method", "const", "section")

# Use 64 hash bits for staleness: a 32-bit collision with equal line count
# can validate coordinates for the wrong source. TestShaWidth pins this guard.
INDEX_SHA_HEX_LEN = 16

# Always ignore the index, including config.toml. _ensure_index_excluded
# chooses the clone-local ignore file without dirtying tracked files.
INDEX_GITIGNORE_ENTRY = INDEX_DIR_NAME + "/"

INDEX_CONFIG_KEYS = ("include", "exclude")
INDEX_CONFIG_DEFAULTS = {
    "include": ["**/*.py", "**/*.md"],
    "exclude": ["**/node_modules/**", "**/.venv/**", "**/target/**"],
}
# Written verbatim by `init`; `load_index_config` parses it back to
# INDEX_CONFIG_DEFAULTS (pinned by a test, so the two cannot drift).
INDEX_CONFIG_DEFAULT_TOML = (
    "[index]\n"
    'include = ["**/*.py", "**/*.md"]\n'
    'exclude = ["**/node_modules/**", "**/.venv/**", "**/target/**"]\n'
)

# Never descended into during a build, whatever `include` says: the index's
# own tree (indexing the index is circular) and git's object store.
INDEX_SKIP_DIR_NAMES = frozenset({INDEX_DIR_NAME, ".git"})

INDEX_NO_INDEX_MESSAGE = "no index -- run 'fleet index init'"


class IndexConfigError(FleetCliError):
    """The index configuration contains keys or values outside its fixed schema.
    Reject unsupported settings so users cannot believe an unimplemented mode
    is active."""


class IndexPathError(FleetCliError):
    """An index path escapes its root or fails the relative-path grammar.
    _index_posix_rel rejects traversal and non-relative spellings;
    _index_require_inside rejects filesystem escapes through links/junctions.
    Callers obtain both guards together through _index_entry_paths."""


class IndexDigestTooLargeError(FleetCliError):
    """The complete --context digest exceeds INDEX_DIGEST_REFUSE_CHARS.
    Refuse instead of truncating: a partial symbol table hides real symbols.
    Compose before the spawn registry commit so refusal leaves no phantom
    worker. Raise outside the per-path catch, which demotes individual path
    errors to warning-and-skip."""


# --- paths ------------------------------------------------------------------

def index_dir(root) -> Path:
    return Path(root) / INDEX_DIR_NAME


def index_symbols_dir(root) -> Path:
    return index_dir(root) / INDEX_SYMBOLS_DIR_NAME


def index_config_path(root) -> Path:
    return index_dir(root) / INDEX_CONFIG_FILE_NAME


def _index_posix_rel(rel) -> str:
    """Canonicalize a relative index path to forward-slash form on every OS.
    Drop empty and dot segments, including leading separators; reject .. and
    a remaining Windows drive or root. A drive-relative join can also replace
    its left side. Parse Windows syntax on every platform because persisted
    shard identities may cross platforms.
    Canonicalization prevents alternate slash spellings creating two shards
    for one file."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
    if ".." in parts:
        raise IndexPathError(
            f"index path {str(rel)!r} is outside the index root -- a '..' "
            f"segment never names a file this index describes")
    out = "/".join(parts)
    spelled = PureWindowsPath(out)
    if spelled.drive or spelled.root:
        named = spelled.drive or spelled.root
        raise IndexPathError(
            f"index path {str(rel)!r} is outside the index root -- an index "
            f"path is relative to the root, and this one names {named!r} of "
            f"its own")
    return out


def shard_path_for_source(root, rel) -> Path:
    """`.fleet-index/symbols/<source-path>.tsv` -- the shard mirrors the
    source path, which is why the source path is not a column (§5)."""
    return index_symbols_dir(root) / (_index_posix_rel(rel) + INDEX_SHARD_SUFFIX)


def _index_require_inside(base, path, rel, what) -> None:
    """Require path to resolve strictly inside base, excluding base itself.
    Resolve both sides so links/junctions cannot escape and a linked root still
    contains its files. A relative-path grammar alone cannot establish physical
    containment."""
    try:
        real_base = Path(base).resolve()
        real = Path(path).resolve()
    except OSError as exc:
        raise IndexPathError(
            f"index path {rel!r}: its {what} cannot be resolved ({exc}), so "
            f"nothing can say whether it is inside the index root")
    if real_base not in real.parents:
        raise IndexPathError(
            f"index path {rel!r} escapes the index root -- its {what} resolves "
            f"to {real}, which is not inside {real_base}. A path that is "
            f"spelled inside the root and lives outside it is a reparse point")


def _index_entry_paths(root, rel) -> tuple:
    """Return (canonical rel, source, shard) with both containment guards.
    Shared by read and write entry points so every caller-supplied path obeys
    the same relative grammar and filesystem containment rules."""
    root = Path(root)
    rel = _index_posix_rel(rel)
    source = root / rel
    shard = index_symbols_dir(root) / (rel + INDEX_SHARD_SUFFIX)
    _index_require_inside(root, source, rel, "source file")
    # Guard the shard path too: a linked mirror directory can redirect atomic
    # replace outside the allowed symbols tree just as it can redirect unlink.
    _index_require_inside(index_symbols_dir(root), shard, rel, "shard")
    return rel, source, shard


def source_rel_from_shard(root, shard_path) -> str:
    """Inverse of `shard_path_for_source`; ValueError off the shard tree."""
    rel = Path(shard_path).relative_to(index_symbols_dir(root)).as_posix()
    if not rel.endswith(INDEX_SHARD_SUFFIX):
        raise ValueError(f"not a shard path: {shard_path}")
    return rel[:-len(INDEX_SHARD_SUFFIX)]


def source_lang(rel) -> str:
    """The `lang` header column. `python`/`markdown` are the two parsed
    languages (§6); everything else names its own suffix so a header-only
    shard still says what it is."""
    suffix = Path(_index_posix_rel(rel)).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".md":
        return "markdown"
    return suffix[1:] if suffix else "text"


# --- shard bytes ------------------------------------------------------------

def _index_tsv_field(value) -> str:
    """Escape tabs as literal \\t and strip line breaks for one TSV cell.
    Normalize during parsing so fresh and cached rows are identical. Backslash
    itself is not escaped: the TSV format does not promise reversible escaping."""
    return str(value).replace("\r", "").replace("\n", "").replace("\t", "\\t")


_INDEX_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")


def _index_split_lines(text) -> list:
    """Split CRLF, CR and LF, dropping a trailing empty element.
    Match bytes.splitlines so header line counts and parser coordinates agree.
    str.splitlines also treats control and Unicode separator characters as
    line boundaries; splitting only LF misses CR-only files."""
    lines = _INDEX_LINE_BREAK_RE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _index_row_key(row):
    """Order rows by line, end, then name for both cached and fresh results.
    The name tie-break stabilizes multiple symbols sharing one source span."""
    name, line, end = row[0], row[1], row[2]
    return (line, end, name)


def render_shard(header: dict, rows) -> str:
    """Render the header and TSV symbol rows in _index_row_key order.
    Source order keeps edits localized; sorting here also guarantees stable
    bytes for callers supplying unsorted rows."""
    out = ["#\t{}\t{}\t{}".format(header["sha"], header["lines"], header["lang"])]
    for name, line, end, kind, sig in sorted(rows, key=_index_row_key):
        out.append(f"{name}\t{line}\t{end}\t{kind}\t{sig}")
    return "\n".join(out) + "\n"


_INDEX_HEX = frozenset("0123456789abcdef")


def read_shard(shard_path):
    """Return (header, rows) for a readable shard, otherwise None.
    Callers treat missing, corrupt or partially valid shards as stale and
    reparse the source. A missing final newline detects a mid-row torn write;
    truncation exactly at a row boundary is not detectable from these bytes."""
    try:
        raw = Path(shard_path).read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text or not text.endswith("\n"):
        return None
    lines = _index_split_lines(text)
    head = lines[0].split("\t")
    if len(head) != 4 or head[0] != "#":
        return None
    sha, count, lang = head[1], head[2], head[3]
    # Require the exact hash width; incompatible shards must refresh.
    if len(sha) != INDEX_SHA_HEX_LEN or not set(sha) <= _INDEX_HEX:
        return None
    if not count.isdigit():
        return None
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 5:
            return None
        name, s_line, s_end, kind, sig = fields
        if not s_line.isdigit() or not s_end.isdigit():
            return None
        if kind not in SHARD_KINDS:
            return None
        rows.append((name, int(s_line), int(s_end), kind, sig))
    return {"sha": sha, "lines": int(count), "lang": lang}, rows


def _index_unlink_quiet(path) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def write_shard_atomic(shard_path, header: dict, rows, sleep=None) -> bool:
    """Write through a same-directory temporary file and atomic replace.
    Return True on success, False on OSError, retaining the previous shard.
    Reuse bounded replace retry for Windows sharing violations. A stale shard
    is safe because readers verify its hash; an in-place torn write is not.
    Non-OSError exceptions propagate after temporary-file cleanup."""
    shard_path = Path(shard_path)
    try:
        shard_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(shard_path.parent),
                                        prefix=".idx.", suffix=".tmp")
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render_shard(header, rows))
        _replace_with_retry(tmp_name, str(shard_path), sleep=sleep)
        return True
    except OSError:
        _index_unlink_quiet(tmp_name)
        return False
    except BaseException:
        _index_unlink_quiet(tmp_name)
        raise


# --- parsers (§6) -----------------------------------------------------------

def header_for_bytes(raw, rel) -> dict:
    """Return the truncated SHA-256, byte line count and language for one buffer.
    Hash bytes so newline encodings and invalid UTF-8 still invalidate stale
    shards. Use the same buffer for parsing to avoid mixed-version coordinates."""
    return {"sha": hashlib.sha256(raw).hexdigest()[:INDEX_SHA_HEX_LEN],
            "lines": len(raw.splitlines()),
            "lang": source_lang(rel)}


def source_header(source_path, rel) -> dict:
    """`header_for_bytes` over the file at `source_path`. One read."""
    return header_for_bytes(Path(source_path).read_bytes(), rel)


def _index_decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _index_py_sig(node) -> str:
    """Render a Python signature using ast.unparse.
    Golden tests pin formatting because unparse has no output-stability promise."""
    try:
        sig = "(" + ast.unparse(node.args) + ")"
        if node.returns is not None:
            sig += " -> " + ast.unparse(node.returns)
        return sig
    except (ValueError, TypeError, AttributeError, RecursionError):
        return "()"


def _index_py_symbols(body, prefix, rows, module_level) -> None:
    """§6's four Python symbol kinds. Deliberately not a full `ast.walk`:
    a function nested inside a function is an implementation detail, not a
    symbol a worker looks up, and indexing it would put unreachable names in
    the lookup namespace."""
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append((prefix + node.name, node.lineno, node.end_lineno,
                         "func" if module_level else "method", _index_py_sig(node)))
        elif isinstance(node, ast.ClassDef):
            name = prefix + node.name
            rows.append((name, node.lineno, node.end_lineno, "class", ""))
            # A nested class qualifies as `Outer.Inner`, so its methods are
            # reachable as `Outer.Inner.m` and by the M2 dotted-tail form.
            _index_py_symbols(node.body, name + ".", rows, module_level=False)
        elif module_level and isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    rows.append((target.id, node.lineno, node.end_lineno, "const", ""))
        elif module_level and isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                rows.append((node.target.id, node.lineno, node.end_lineno, "const", ""))


def _index_parse_python(raw) -> list:
    text = _index_decode(raw)
    if text is None:
        return []
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        # §6/§9: an unparseable file never aborts a build -- it becomes a
        # header-only shard so staleness still tracks it.
        return []
    rows = []
    _index_py_symbols(tree.body, "", rows, module_level=True)
    return rows


_MD_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
_MD_CLOSING_HASHES_RE = re.compile(r"\s+#+\s*$")


def _index_parse_markdown(raw) -> list:
    """Parse ATX headings and section ends, excluding fenced code.
    Fence tracking prevents code comments from becoming phantom sections."""
    text = _index_decode(raw)
    if text is None:
        return []
    lines = _index_split_lines(text)
    heads = []
    fence = None
    for lineno, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence = stripped[:3]
            continue
        match = _MD_HEADING_RE.match(raw)
        if match:
            title = _MD_CLOSING_HASHES_RE.sub("", match.group(2).strip()).strip()
            heads.append((lineno, len(match.group(1)), title))
    eof = len(lines)
    rows = []
    for idx, (lineno, level, title) in enumerate(heads):
        end = eof
        for next_line, next_level, _title in heads[idx + 1:]:
            if next_level <= level:
                end = next_line - 1
                break
        rows.append((title, lineno, max(end, lineno), "section", ""))
    return rows


def parse_source_symbols(source_path, lang=None, raw=None) -> list:
    """Parse one source into _index_row_key-ordered rows, or [] on bad input.
    Accept an existing raw buffer so hashing and parsing describe the same
    version under concurrent writes. Unparseable, unreadable or undecodable
    sources produce header-only shards and remain tracked for staleness."""
    source_path = Path(source_path)
    if lang is None:
        lang = source_lang(source_path.name)
    if raw is None:
        try:
            raw = source_path.read_bytes()
        except OSError:
            return []
    if lang == "python":
        rows = _index_parse_python(raw)
    elif lang == "markdown":
        rows = _index_parse_markdown(raw)
    else:
        rows = []
    return sorted(
        ((_index_tsv_field(name), line, end, kind, _index_tsv_field(sig))
         for name, line, end, kind, sig in rows),
        key=_index_row_key)


# Fixed-schema config parser: Python 3.10 lacks tomllib and fleet is
# stdlib-only. Reject fields outside the schema instead of accepting unused TOML.

def _index_config_array(value, path, lineno, key) -> list:
    def bad(why):
        return IndexConfigError(
            f"{path}:{lineno}: {key!r} {why} -- expected a single-line array "
            f"of double-quoted strings, got {value!r}")

    if not (value.startswith("[") and value.endswith("]")):
        raise bad("is not an array")
    inner = value[1:-1]
    out, i, expect_item = [], 0, True
    while i < len(inner):
        char = inner[i]
        if char in " \t":
            i += 1
        elif char == ",":
            if expect_item:
                raise bad("has an empty array slot")
            expect_item = True
            i += 1
        elif char != '"':
            raise bad("has a non-string array item")
        elif not expect_item:
            raise bad("is missing a comma between items")
        else:
            close = inner.find('"', i + 1)
            if close < 0:
                raise bad("has an unterminated string")
            out.append(inner[i + 1:close])
            i = close + 1
            expect_item = False
    return out


def _parse_index_config(text, path) -> dict:
    config = {key: list(value) for key, value in INDEX_CONFIG_DEFAULTS.items()}
    table = None
    for lineno, raw in enumerate(_index_split_lines(text), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            if line != "[index]":
                raise IndexConfigError(
                    f"{path}:{lineno}: unrecognised table {line!r} -- the only "
                    f"table this schema accepts is [index]")
            table = "index"
            continue
        if table != "index":
            raise IndexConfigError(
                f"{path}:{lineno}: key outside a table -- every key must follow "
                f"the [index] header")
        key, sep, value = line.partition("=")
        if not sep:
            raise IndexConfigError(
                f"{path}:{lineno}: not a `key = [...]` assignment: {line!r}")
        key = key.strip()
        if key not in INDEX_CONFIG_KEYS:
            raise IndexConfigError(
                f"{path}:{lineno}: unrecognised key {key!r} -- this schema "
                f"accepts only {', '.join(INDEX_CONFIG_KEYS)}")
        config[key] = _index_config_array(value.strip(), path, lineno, key)
    return config


def load_index_config(root) -> dict:
    """`.fleet-index/config.toml`, or the defaults when it is absent (§8)."""
    path = index_config_path(root)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {key: list(value) for key, value in INDEX_CONFIG_DEFAULTS.items()}
    except OSError as exc:
        raise IndexConfigError(f"{path}: unreadable ({exc})")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise IndexConfigError(f"{path}: not valid UTF-8")
    return _parse_index_config(text, path)


@functools.lru_cache(maxsize=256)
def _index_glob_regex(pattern):
    """Compile case-sensitive include/exclude patterns on every platform.
    **/ is an optional directory prefix, ** crosses separators, and * / ? do
    not. fnmatch cannot supply these rules or match root files with **/*.py."""
    out, i, size = [], 0, len(pattern)
    while i < size:
        char = pattern[i]
        if pattern[i:i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("(?s:" + "".join(out) + r")\Z")


def _index_glob_match(path, pattern) -> bool:
    return _index_glob_regex(pattern).match(path) is not None


# --- digest rendering (§7) --------------------------------------------------

# Digest size uses aggregate rendered characters after canonical dedupe.
# Warn, then refuse; never truncate a symbol table and conceal symbols.
# Argument length and file count do not bound the generated context.
# The warning allows an ordinary single-file digest; refusal limits large
# combined requests. TestTheDigestSizeCap checks these operating margins.
INDEX_DIGEST_WARN_CHARS = 50_000
INDEX_DIGEST_REFUSE_CHARS = 250_000


def render_digest(rel, header: dict, rows) -> str:
    """Render one file's complete symbol digest, without truncation.
    compose_context_digests applies the aggregate warning/refusal thresholds;
    q --outline's line cap does not apply to context injection."""
    out = [f"## {rel} ({header['lines']} lines, {header['lang']})"]
    for name, line, _end, kind, sig in rows:
        indent = "  " if kind == "method" else ""
        label = f"class {name}" if kind == "class" else f"{name}{sig}"
        out.append(f"- L{line} {indent}{label}")
    return "\n".join(out) + "\n"


# --- index discovery (§11.1) ------------------------------------------------

def _index_is_repo_boundary(directory) -> bool:
    """Recognize a directory containing a .git entry, either file or directory.
    Use in both upward discovery and downward enumeration so linked worktrees
    and nested checkouts cannot borrow each other's indexes."""
    return (Path(directory) / ".git").exists()


def _index_is_reparse_point(path) -> bool:
    """Recognize symlinks and Windows junctions/mount points; True if unstattable.
    islink alone misses junctions. Probe st_reparse_tag without an OS branch
    so the walk refuses any entry it cannot safely inspect."""
    try:
        st = os.lstat(path)
    except OSError:
        return True
    return bool(stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0))


def find_index_root(start=None):
    """Find the nearest .fleet-index at or above start, stopping at .git entries.
    Accept a boundary directory's own index before stopping. A linked worktree
    uses a .git file and must not fall through to its parent's index, whose
    coordinates describe a different checkout."""
    try:
        current = Path(start if start is not None else os.getcwd()).resolve()
    except OSError:
        return None
    for directory in (current, *current.parents):
        if (directory / INDEX_DIR_NAME).is_dir():
            return directory
        if _index_is_repo_boundary(directory):
            return None
    return None


# --- the verify-then-get primitive (§8/§11.3) -------------------------------

def verified_shard_rows(root, rel, no_write=False, sleep=None) -> dict:
    """Verify source bytes before serving any shard coordinates.
    Reparse missing, stale or corrupt shards. Hash and parse one buffer so a
    concurrent edit cannot combine one file version's header with another's rows.
    Return status (ok/withheld/orphan), rows, refreshed, written, and note.
    Only ok carries rows. no_write withholds a shard needing repair; it does
    not relax verification. A failed atomic replace still returns verified
    fresh rows as ok, leaving disk stale for the next reader. Pruning an orphan
    counts as written. Source absence or unreadability yields orphan.
    A shard truncated exactly at a row boundary cannot be detected by the
    format alone; read_shard rejects malformed rows and missing final newlines."""
    root = Path(root)
    rel, source, shard = _index_entry_paths(root, rel)
    result = {"rel": rel, "status": "ok", "header": None, "rows": [],
              "refreshed": False, "written": False, "note": None}
    try:
        raw = source.read_bytes()
    except OSError as exc:
        result["status"] = "orphan"
        if source.exists():
            # Present but unreadable (a directory in the slot, a permission
            # denial). NOT pruned: the shard may well be the only surviving
            # description of a file whose readability is a transient problem.
            result["note"] = f"{rel}: source unreadable ({exc}) -- hits suppressed"
            return result
        result["note"] = f"{rel}: source file is gone -- hits suppressed"
        if not no_write and _index_prune_shard(root, rel):
            result["written"] = True
            result["note"] += "; orphan shard pruned"
        return result
    header = header_for_bytes(raw, rel)
    existing = read_shard(shard)
    if existing is not None and existing[0] == header:
        result["header"], result["rows"] = existing
        return result
    if no_write:
        result["status"] = "withheld"
        result["note"] = (f"{rel}: shard is stale or unreadable and no-write mode "
                          f"forbids repairing it -- hits withheld")
        return result
    rows = parse_source_symbols(source, header["lang"], raw=raw)
    result["header"] = header
    result["rows"] = rows
    result["refreshed"] = True
    result["written"] = write_shard_atomic(shard, header, rows, sleep=sleep)
    if not result["written"]:
        result["note"] = (f"{rel}: shard refresh could not land -- answering from "
                          f"this run's own parse, the on-disk shard stays stale")
    return result


# --- enumeration and the build (§6/§8) --------------------------------------

def _index_selects(rel, include, exclude) -> bool:
    if not any(_index_glob_match(rel, pattern) for pattern in include):
        return False
    return not any(_index_glob_match(rel, pattern) for pattern in exclude)


def index_source_files(root, config=None) -> list:
    """Yield selected source paths as sorted canonical relatives.
    Do not descend nested repository boundaries or reparse points, including
    Windows junctions. Reject linked files too. Test entries below root while
    allowing root itself to be a checkout."""
    root = Path(root)
    if config is None:
        config = load_index_config(root)
    include, exclude = config["include"], config["exclude"]
    out = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        base = Path(dirpath)
        dirnames[:] = [d for d in dirnames
                       if d not in INDEX_SKIP_DIR_NAMES
                       and not _index_is_repo_boundary(base / d)
                       and not _index_is_reparse_point(base / d)]
        for name in filenames:
            # `relative_to(...).as_posix()`, not a separator substitution:
            # invariant 8 confines OS branching to the platform adapter, and
            # pathlib already yields forward slashes everywhere (§11.2, §14).
            rel = (base / name).relative_to(root).as_posix()
            if _index_selects(rel, include, exclude) and not _index_is_reparse_point(
                    base / name):
                out.append(rel)
    return sorted(out)


def index_shard_rels(root) -> list:
    """Every source path the shard tree currently claims to describe."""
    symbols = index_symbols_dir(root)
    out = []
    for dirpath, _dirnames, filenames in os.walk(str(symbols)):
        base = Path(dirpath)
        for name in filenames:
            if not name.endswith(INDEX_SHARD_SUFFIX):
                continue        # a `.idx.*.tmp` from an in-flight write
            out.append(source_rel_from_shard(root, base / name))
    return sorted(out)


def _index_prune_shard(root, rel) -> bool:
    """Delete one contained shard, then its empty mirror directories.
    Resolve paths before unlink/rmdir so a linked mirror directory cannot
    redirect deletion outside the symbols tree."""
    shard = shard_path_for_source(root, rel)
    try:
        stop = index_symbols_dir(root).resolve()
        real = shard.resolve()
    except OSError:
        return False
    if real == stop or stop not in real.parents:
        return False
    try:
        shard.unlink()
    except OSError:
        return False
    # Leave no empty mirror directories behind, or the shard tree slowly
    # accumulates the skeleton of every directory a project ever had.
    current = real.parent
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    return True


def _new_index_report() -> dict:
    return {"indexed": 0, "skipped": 0, "failed": 0, "pruned": 0,
            "indexed_rels": [], "pruned_rels": [], "warnings": []}


def _index_refresh_one(root, rel, force, sleep, report) -> None:
    # Apply shared canonicalization and containment at the write entry point,
    # even when callers already checked: canonicalization is idempotent.
    root = Path(root)
    rel, source, shard = _index_entry_paths(root, rel)
    try:
        # Hash and parse one buffer so concurrent edits cannot tear shard versions.
        raw = source.read_bytes()
    except OSError as exc:
        report["failed"] += 1
        report["warnings"].append(f"{rel}: unreadable ({exc}) -- skipped")
        return
    header = header_for_bytes(raw, rel)
    if not force:
        existing = read_shard(shard)
        if existing is not None and existing[0] == header:
            report["skipped"] += 1
            return
    # §6/§9: an unparseable file yields no rows, so it becomes a header-only
    # shard and the build carries on. It is never a build failure.
    rows = parse_source_symbols(source, header["lang"], raw=raw)
    if write_shard_atomic(shard, header, rows, sleep=sleep):
        report["indexed"] += 1
        report["indexed_rels"].append(rel)
    else:
        report["failed"] += 1
        report["warnings"].append(
            f"{rel}: shard write abandoned after the bounded replace retries -- "
            f"the old shard is left in place (stale, not torn)")


def build_index(root, force=False, sleep=None) -> dict:
    """Rebuild the whole index: refresh every selected source file (skipping
    the ones whose SHA-256 already matches unless `force`), then prune every
    shard the selection no longer covers."""
    root = Path(root)
    config = load_index_config(root)
    selected = index_source_files(root, config)
    report = _new_index_report()
    for rel in selected:
        _index_refresh_one(root, rel, force, sleep, report)
    keep = set(selected)
    for rel in index_shard_rels(root):
        # Both a deleted source and a source the config no longer selects: a
        # shard that survived either one would keep answering for a file this
        # index does not describe.
        if rel not in keep and _index_prune_shard(root, rel):
            report["pruned"] += 1
            report["pruned_rels"].append(rel)
    return report


def update_index(root, rels, force=False, sleep=None) -> dict:
    """Refresh exactly the named selected files.
    Canonicalize the entire batch before comparison or writes: refuse a path
    escape without partially applying a batch aimed at the wrong root."""
    root = Path(root)
    rels = [_index_posix_rel(rel) for rel in rels]
    selected = set(index_source_files(root))
    report = _new_index_report()
    for rel in rels:
        if rel in selected:
            _index_refresh_one(root, rel, force, sleep, report)
        elif (root / rel).exists():
            # Honouring include/exclude here too is deliberate: a shard built
            # for an unselected file would be pruned by the very next `build`,
            # so writing it would be a promise this index cannot keep.
            report["warnings"].append(
                f"{rel}: not selected by this index's include/exclude -- skipped")
        elif _index_prune_shard(root, rel):
            report["pruned"] += 1
            report["pruned_rels"].append(rel)
            report["warnings"].append(f"{rel}: source file is gone -- orphan shard pruned")
        else:
            report["warnings"].append(f"{rel}: no such file, and no shard to prune")
    return report


def index_status(root) -> dict:
    """Counts plus the stale/orphan/unindexed shard lists. READ-ONLY: status
    reports staleness, it never repairs it, so an operator can see the true
    state of an index without the act of looking changing it."""
    root = Path(root)
    selected = index_source_files(root)
    selected_set = set(selected)
    shard_rels = index_shard_rels(root)
    stale, orphan, symbols = [], [], 0
    for rel in shard_rels:
        source = root / rel
        if rel not in selected_set or not source.exists():
            orphan.append(rel)
            continue
        existing = read_shard(shard_path_for_source(root, rel))
        try:
            header = source_header(source, rel)
        except OSError:
            stale.append(rel)
            continue
        if existing is None or existing[0] != header:
            stale.append(rel)
            continue
        symbols += len(existing[1])
    return {"root": root, "shards": len(shard_rels), "symbols": symbols,
            "stale": stale, "orphan": orphan,
            "unindexed": [rel for rel in selected if rel not in set(shard_rels)]}


# Compose-time index surface: opt-in per dispatch target; no fleet-state access.

# Keep teach text within four lines: it is paid on every dispatch, including steers.
INDEX_TEACH_LINES = (
    "This project carries a symbol index: `fleet q <symbol>` locates a symbol "
    "without reading the file it lives in.\n"
    "It prints one `<path>:<line>-<end>` pointer per hit, so a following Read "
    "can ask for exactly that range.\n"
    "`fleet q <symbol> --src` prints that symbol's source slice instead of the "
    "pointer -- prefer it to reading a large file.\n"
    "`fleet q --outline <path>` prints one file's symbol outline.\n"
)


def index_teach_verbs() -> tuple:
    """Every `fleet <verb>` the teach lines name, DERIVED from the constant.

    Derived, not listed: a fifth teach line naming a new verb must not be able
    to slip past the §11.8 gate below because someone forgot to extend a
    hand-written tuple."""
    return tuple(sorted(set(
        re.findall(r"`fleet ([a-z][a-z0-9-]*)", INDEX_TEACH_LINES))))


@functools.lru_cache(maxsize=1)
def registered_cli_verbs() -> frozenset:
    """Return the subcommands registered by build_parser, cached per module.
    Tests may invalidate the cache through registered_cli_verbs.cache_clear()."""
    parser = build_parser()
    for action in parser._actions:
        if action.dest == "command" and action.choices:
            return frozenset(action.choices)
    return frozenset()


def index_teach_lines(cwd) -> str:
    """Return index instructions only when cwd itself has an index directory.
    Also require every advertised verb to exist in the parser. Teaching an
    unavailable command wastes a worker turn. Do not walk upward: the dispatch
    target must opt in directly, and a plain .fleet-index file is not an index."""
    try:
        if not index_dir(cwd).is_dir():
            return ""
    except OSError:
        return ""
    available = registered_cli_verbs()
    if any(verb not in available for verb in index_teach_verbs()):
        return ""
    return INDEX_TEACH_LINES


def parse_context_arg(value) -> list:
    """Split comma-separated --context paths, strip and dedupe exact spellings.
    Preserve order; None or empty input yields []. Canonical dedupe belongs in
    compose_context_digests, where path errors can warn-and-skip instead of
    failing argument parsing."""
    if not value:
        return []
    out = []
    for part in str(value).split(","):
        entry = part.strip()
        if entry and entry not in out:
            out.append(entry)
    return out


def compose_context_digests(cwd, context, sleep=None) -> tuple:
    """Return (digest_text, warnings) for --context injection.
    Resolve paths against the worker cwd and require its own index directory.
    Read every row through verified_shard_rows. Unknown, excluded, escaping or
    unreadable paths warn and skip; missing index warns and injects nothing.
    Canonicalize and dedupe before selection, verification and size accounting,
    warning on folded spellings. Catch FleetCliError, ValueError and OSError
    per path; unexpected renderer bugs remain loud.
    Render complete digests in input order. Warn above INDEX_DIGEST_WARN_CHARS
    and refuse above INDEX_DIGEST_REFUSE_CHARS, never truncate a symbol table.
    Measure the full total and raise outside the per-path catch so an oversized
    request cannot be demoted to a successful warning-and-skip."""
    root = Path(cwd)
    warnings = []
    if not context:
        return "", warnings
    if not index_dir(root).is_dir():
        return "", [f"--context ignored: {INDEX_NO_INDEX_MESSAGE} "
                    f"(no {INDEX_DIR_NAME}/ in {root.as_posix()})"]
    # `IndexConfigError` is a `FleetCliError`; naming the base catches a
    # config-layer guard added later without re-editing this line.
    try:
        config = load_index_config(root)
    except (FleetCliError, OSError) as exc:
        return "", [f"--context ignored: {exc}"]
    # Enumerate selection once for all paths. If enumeration fails, warn and
    # inject nothing; no individual path can be verified against the selection.
    try:
        selected = set(index_source_files(root, config))
    except (FleetCliError, ValueError, OSError) as exc:
        return "", [f"--context ignored: cannot enumerate the index's sources "
                    f"under {root.as_posix()} ({exc})"]
    out = []
    # Record the first spelling at canonicalization, before selection or shard
    # work. Duplicate spellings then cost no rehash or digest, even if the first
    # path failed and already supplied the relevant warning.
    first_spelling = {}
    for raw in context:
        # The per-path arm. See the docstring: one unusable path is a warning
        # and a skip, never a raise out of compose.
        try:
            rel = _index_posix_rel(raw)
            if rel in first_spelling:
                warnings.append(
                    f"--context {raw}: the same source was already named as "
                    f"{first_spelling[rel]!r} -- one digest is rendered for "
                    f"{rel}, not one per spelling")
                continue
            first_spelling[rel] = raw
            if rel not in selected:
                why = ("not selected by this index's include/exclude"
                       if (root / rel).is_file()
                       else f"no such file under the worker's --dir {root.as_posix()}")
                warnings.append(f"--context {raw}: {why} -- digest skipped")
                continue
            result = verified_shard_rows(root, rel, sleep=sleep)
            if result["status"] != "ok":
                warnings.append(f"--context {raw}: {result['note']}")
                continue
            out.append(render_digest(rel, result["header"], result["rows"]))
        except (FleetCliError, ValueError, OSError) as exc:
            warnings.append(f"--context {raw}: {exc} ({type(exc).__name__}) "
                            f"-- digest skipped")
    digest = "".join(out)
    # The size grades. OUTSIDE the per-path `try` on purpose -- see the
    # docstring: that `try` demotes every `FleetCliError` to a warn-and-skip,
    # and a refusal that becomes a warning is not a refusal.
    size = len(digest)
    lines = digest.count("\n")
    if size > INDEX_DIGEST_REFUSE_CHARS:
        named = ", ".join(sorted(first_spelling))
        raise IndexDigestTooLargeError(
            f"--context refused: the digest for {len(out)} source(s) renders "
            f"{size:,} chars ({lines:,} lines), over the "
            f"{INDEX_DIGEST_REFUSE_CHARS:,}-char ceiling. It is NOT truncated "
            f"to fit -- a truncated symbol table reads exactly like a complete "
            f"one, so a worker given a trimmed digest concludes a symbol does "
            f"not exist and re-implements it. Name fewer paths and re-run; "
            f"nothing was registered. Asked for: {named}")
    if size > INDEX_DIGEST_WARN_CHARS:
        warnings.append(
            f"--context is large: {len(out)} source(s) render {size:,} digest "
            f"chars ({lines:,} lines), over the "
            f"{INDEX_DIGEST_WARN_CHARS:,}-char threshold; the worker re-reads "
            f"this once per dispatch. Served IN FULL -- nothing is truncated. "
            f"The ceiling is {INDEX_DIGEST_REFUSE_CHARS:,} chars")
    return digest, warnings


# --- `fleet index` CLI (§6) -------------------------------------------------

# Per-file lines are capped so a first build of a large repo does not dump
# thousands of lines into a manager's context. The suppressed count is always
# printed -- a cap nobody is told about reads as "that was everything".
INDEX_LIST_CAP = 20

# Use a distinct exit code for partial indexing failure: callers must
# distinguish retrying failed files from a command refusal requiring init.
# Codes 2 through 5 are reserved for lifecycle and continuity refusals.
INDEX_FAILED_RC = 6


def _index_root_arg(args) -> Path:
    """`--path DIR` names the INDEX ROOT on all four verbs, defaulting to cwd.

    Note the deliberate asymmetry with M2's `fleet q --path GLOB`, which is a
    filter: `q` takes no root argument (its root comes from the §11.1
    walk-up), so the flag name is free there for the job a querying worker
    actually needs."""
    raw = getattr(args, "path", None)
    try:
        root = (Path(raw).expanduser() if raw else Path.cwd()).resolve()
    except OSError as exc:
        raise FleetCliError(f"--path {raw!r}: {exc}")
    if not root.is_dir():
        raise FleetCliError(f"--path {root} is not a directory")
    return root


def _require_index(root) -> None:
    """`init` is the ONLY command that creates `.fleet-index/` (§6)."""
    if not index_dir(root).is_dir():
        raise FleetCliError(INDEX_NO_INDEX_MESSAGE)


def _index_files_arg(root, raw) -> list:
    """Parse --files into verified canonical relatives, or refuse the batch.
    Normalize shared path-guard exceptions into this command's error wording."""
    rels = []
    for chunk in str(raw).split(","):
        entry = chunk.strip()
        if not entry:
            continue
        candidate = Path(entry).expanduser()
        if candidate.is_absolute():
            try:
                rel = candidate.resolve().relative_to(root).as_posix()
            except (ValueError, OSError):
                raise FleetCliError(
                    f"--files entry {entry!r} is outside the index root {root}")
        else:
            # Use the shared canonicalizer for traversal and drive-relative refusal;
            # is_absolute alone does not reject a Windows C:x.py path.
            rel = _index_posix_rel(entry)
        if rel and rel not in rels:
            rels.append(rel)
    if not rels:
        raise FleetCliError("--files named no paths")
    return rels


def _index_git_common_dir(root):
    """Resolve the checkout's common Git directory, or None on invalid pointers.
    Follow .git files and commondir for linked worktrees using pathlib; index
    init requires no Git subprocess."""
    dot = Path(root) / ".git"
    if dot.is_dir():
        return dot
    try:
        text = dot.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    gitdir = ""
    for line in text.splitlines():
        if line.startswith("gitdir:"):
            gitdir = line[len("gitdir:"):].strip()
            break
    if not gitdir:
        return None
    path = Path(gitdir)
    if not path.is_absolute():
        path = Path(root) / path
    try:
        common = (path / "commondir").read_bytes().decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return path
    if not common:
        return path
    candidate = Path(common)
    return candidate if candidate.is_absolute() else path / candidate


def _ensure_index_excluded(root):
    """Idempotently ignore .fleet-index/ and return (path, added).
    Use the clone's common info/exclude so initializing linked worktrees does
    not dirty tracked files. Outside a checkout, use .gitignore so a later
    git init already ignores the index."""
    common = _index_git_common_dir(root)
    path = (common / "info" / "exclude") if common is not None \
        else (Path(root) / ".gitignore")
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as exc:
        raise FleetCliError(f"{path}: cannot read to add the index entry ({exc})")
    if any(line.strip() in (INDEX_GITIGNORE_ENTRY, INDEX_DIR_NAME)
           for line in text.splitlines()):
        return path, False
    if text and not text.endswith("\n"):
        text += "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((text + INDEX_GITIGNORE_ENTRY + "\n").encode("utf-8"))
    except OSError as exc:
        raise FleetCliError(f"{path}: cannot write the index entry ({exc})")
    return path, True


def _print_index_report(report) -> int:
    for rel in report["indexed_rels"][:INDEX_LIST_CAP]:
        print(f"  + {rel}")
    hidden = len(report["indexed_rels"]) - INDEX_LIST_CAP
    if hidden > 0:
        print(f"  ... and {hidden} more indexed")
    for rel in report["pruned_rels"][:INDEX_LIST_CAP]:
        print(f"  - {rel}")
    hidden = len(report["pruned_rels"]) - INDEX_LIST_CAP
    if hidden > 0:
        print(f"  ... and {hidden} more pruned")
    print("indexed {indexed}   skipped {skipped}   pruned {pruned}   "
          "failed {failed}".format(**report))
    for warning in report["warnings"]:
        print(f"fleet: {warning}", file=sys.stderr)
    # A file this run could not index is a file the index does not describe.
    # Exiting 0 on `failed 3` reads as success to every caller that checks a
    # return code instead of parsing the count line back out of stdout --
    # and exiting 1 reads as "the command did not run at all", which is the
    # collision `INDEX_FAILED_RC` exists to break.
    return INDEX_FAILED_RC if report["failed"] else 0


def cmd_index_init(args) -> int:
    root = _index_root_arg(args)
    index_symbols_dir(root).mkdir(parents=True, exist_ok=True)
    config = index_config_path(root)
    if not config.exists():
        config.write_bytes(INDEX_CONFIG_DEFAULT_TOML.encode("utf-8"))
    path, added = _ensure_index_excluded(root)
    print(f"index root: {root}")
    print(f"git exclude: {path} "
          + ("(entry added)" if added else "(entry already present)"))
    return _print_index_report(build_index(root))


def cmd_index_build(args) -> int:
    root = _index_root_arg(args)
    _require_index(root)
    return _print_index_report(build_index(root, force=args.force))


def cmd_index_update(args) -> int:
    root = _index_root_arg(args)
    _require_index(root)
    return _print_index_report(
        update_index(root, _index_files_arg(root, args.files)))


def cmd_index_status(args) -> int:
    root = _index_root_arg(args)
    _require_index(root)
    status = index_status(root)
    print(f"index root: {status['root']}")
    print("shards {shards}   symbols {symbols}   stale {stale_n}   "
          "orphan {orphan_n}   unindexed {unindexed_n}".format(
              stale_n=len(status["stale"]), orphan_n=len(status["orphan"]),
              unindexed_n=len(status["unindexed"]), **status))
    for label in ("stale", "orphan", "unindexed"):
        for rel in status[label][:INDEX_LIST_CAP]:
            print(f"{label} {rel}")
        hidden = len(status[label]) - INDEX_LIST_CAP
        if hidden > 0:
            print(f"{label} ... and {hidden} more")
    return 0


def cmd_index(args) -> int:
    return {"init": cmd_index_init, "build": cmd_index_build,
            "update": cmd_index_update, "status": cmd_index_status}[
        args.index_command](args)


# fleet q reads verified index shards without touching fleet state. All shard
# reads go through verified_shard_rows to prevent stale coordinates escaping.
# Path filters use the same **-aware, case-sensitive dialect as index config;
# name globs use fnmatchcase because names contain no path separators.

Q_LIMIT_DEFAULT = 20

# §11.4. Applies to a `--src` slice and to an `--outline` rendering; the
# spawn-time `--context` digest is deliberately NOT capped (§11.1), which is
# why `render_digest` stays uncapped and the cap lives here.
Q_OUTPUT_LINE_CAP = 400

# Preserve the exact trailer, including its em dash, for the output contract.
Q_TRUNCATION_TRAILER = "[truncated {n} lines — narrow the query]"

# Cap diagnostic lists and always print the suppressed count so bounded
# output cannot appear exhaustive.
Q_NOTE_CAP = 20


def _q_pointer(hit) -> str:
    """§11.4's pointer line: `<path>:<line>-<end>\\t<kind>\\t<name>\\t<sig>`.

    `rel` is already the index's canonical forward-slash form on every
    platform (§11.2) and is formatted as a plain string -- a `str(Path(rel))`
    anywhere here would emit `src\\api.py` on win32 and diverge §12's goldens
    from a Linux run."""
    rel, name, line, end, kind, sig = hit
    return f"{rel}:{line}-{end}\t{kind}\t{name}\t{sig}"


def _q_source_lines(source_path) -> list:
    """The lines of a source file, for a `--src` slice.

    BYTES FROM THE FILE (§11.4). The index supplies the range and the file
    supplies truth: source never comes from the shard, which is what makes the
    slice worth more than the pointer. Undecodable bytes are replaced rather
    than raised on -- a latin-1 source file still slices, and the only failure
    this reports is OSError, the §11.5 "unreadable at slice time" row."""
    text = Path(source_path).read_bytes().decode("utf-8", "replace")
    return _index_split_lines(text)


def _q_print_capped(lines) -> None:
    """Print at most `Q_OUTPUT_LINE_CAP` lines, then §11.4's trailer.

    Truncation does not change the exit code: an oversized symbol is the
    query's problem to narrow, not an error."""
    for line in lines[:Q_OUTPUT_LINE_CAP]:
        print(line)
    hidden = len(lines) - Q_OUTPUT_LINE_CAP
    if hidden > 0:
        print(Q_TRUNCATION_TRAILER.format(n=hidden))


def _q_print_notes(notes) -> None:
    """Staleness/orphan notes, on stderr (§11.4: stdout carries hits only, so
    a worker's tool result carries signal)."""
    for note in notes[:Q_NOTE_CAP]:
        print(f"fleet: {note}", file=sys.stderr)
    hidden = len(notes) - Q_NOTE_CAP
    if hidden > 0:
        print(f"fleet: ... and {hidden} more shard notes", file=sys.stderr)


def _q_collect_rows(root, rels, kind, no_refresh, notes) -> tuple:
    """Return kind-filtered verified rows and a count of unknown source contents.
    Count withheld/unreadable shards only while their source still exists:
    they can hide competing symbols. Deleted sources cannot compete and do
    not make results incomplete. Recheck existence rather than parsing notes."""
    rows, unknown = [], 0
    for rel in rels:
        result = verified_shard_rows(root, rel, no_write=no_refresh)
        if result["note"]:
            notes.append(result["note"])
        if result["status"] != "ok":
            if (Path(root) / rel).exists():
                unknown += 1
            continue
        for name, line, end, row_kind, sig in result["rows"]:
            if kind is None or row_kind == kind:
                rows.append((rel, name, line, end, row_kind, sig))
    return rows, unknown


def _q_match(rows, query) -> list:
    """§11.2's three forms, in their short-circuit order.

    The short-circuit is the whole point: ANY exact hit means tail matching
    never runs, so the two tiers never mix in one result. §11.2's own worked
    example -- `q run` returns the top-level `run` and NOT `Beta.run`, which
    stays reachable as `q Beta.run`. Ambiguity WITHIN a tier is still
    ambiguity; the short-circuit never resolves it by falling through."""
    if "*" in query or "?" in query:
        # Form 3, over the NAME. `fnmatchcase`, never `fnmatch`: the latter
        # case-folds via `os.path.normcase` on win32, so `beta.*` would match
        # `Beta.run` on Windows and not on Linux (§11.2).
        return [row for row in rows if fnmatch.fnmatchcase(row[1], query)]
    exact = [row for row in rows if row[1] == query]
    if exact or "." in query:
        # A dotted query is the qualified form; it never tail-matches, or
        # `q Gamma.run` would silently answer with `Beta.run`.
        return exact
    return [row for row in rows
            if "." in row[1] and row[1].rsplit(".", 1)[1] == query]


def _q_sorted(hits) -> list:
    """Sort hits by source path, line and name without relevance ranking.
    The name tie-break gives deterministic output for symbols sharing a line."""
    return sorted(hits, key=lambda row: (row[0], row[2], row[3], row[1]))


def _q_print_hits(hits, limit) -> None:
    """Pointer lines, `--limit`-capped. A truncated list is still exit 0
    (§11.5); the suppressed count goes to stderr with the narrowing hint."""
    for hit in hits[:limit]:
        print(_q_pointer(hit))
    hidden = len(hits) - limit
    if hidden > 0:
        print(f"fleet: {hidden} more hit(s) suppressed by --limit {limit} -- "
              f"narrow with `--path`/`--kind`", file=sys.stderr)


def _q_print_slice(root, hit, notes) -> int:
    """The pointer line, then lines `line..end` of the source file, verbatim."""
    rel, _name, line, end, _kind, _sig = hit
    print(_q_pointer(hit))
    try:
        lines = _q_source_lines(Path(root) / rel)
    except OSError as exc:
        # §11.5: readable when the header was hashed, unreadable by the time
        # the slice was read. The hit degrades to its pointer -- still useful,
        # still exit 0, because a hit WAS printed.
        notes.append(f"{rel}: source unreadable at slice time ({exc}) -- "
                     f"pointer only, no slice")
    else:
        _q_print_capped(lines[line - 1:end])
    _q_print_notes(notes)
    return 0


def _q_shard_rels(root, path_glob):
    """The shard set a query runs over, `--path`-filtered.

    Filtering happens BEFORE verification (§11.2: "after `--path`/`--kind`
    filtering"), which is not just an ordering detail -- it is what keeps a
    narrow query from re-hashing, refreshing and pruning every source file in
    the repo. Returns None when the glob selected nothing, which the caller
    reports rather than presenting as "no such symbol"."""
    rels = index_shard_rels(root)
    if path_glob is None:
        return rels
    selected = [rel for rel in rels if _index_glob_match(rel, path_glob)]
    if not selected:
        return None
    return selected


def _q_path_dialect_hint(path_glob) -> None:
    """Explain the --path glob dialect on stderr after an empty query result.
    Even a nonempty selection can miss the wanted nested file when *.py was
    used instead of **/*.py, so selection emptiness alone is insufficient."""
    print(f"fleet: --path {path_glob!r} is `**`-aware: `**/*.py` matches at "
          f"any depth, `*.py` only at the index root -- widen the glob if you "
          f"meant any depth", file=sys.stderr)


def _cmd_q_query(root, args) -> int:
    rels = _q_shard_rels(root, args.path)
    if rels is None:
        # Distinguished from "no such symbol" on purpose: under this dialect
        # `*.py` is root-level only, and a worker who typed the fnmatch form
        # would otherwise conclude the symbol does not exist.
        print(f"fleet: --path {args.path!r} matched no indexed file",
              file=sys.stderr)
        _q_path_dialect_hint(args.path)
        return 1
    notes = []
    rows, unknown = _q_collect_rows(root, rels, args.kind, args.no_refresh, notes)
    hits = _q_sorted(_q_match(rows, args.query))
    limit = Q_LIMIT_DEFAULT if args.limit is None else args.limit
    if not hits:
        _q_print_notes(notes)
        if unknown:
            # Unread selected shards make absence inconclusive. Print the unknown
            # count even if capped notes omit the relevant files.
            print(f"fleet: no hits, but {unknown} shard(s) could not be read "
                  f"-- this is NOT evidence that {args.query!r} is absent; "
                  f"re-run without `--no-refresh`", file=sys.stderr)
        else:
            # §11.5: stderr says which kind of nothing this is, and points at
            # the substring search this tool deliberately does not do (§11.2).
            print(f"fleet: no symbol matches {args.query!r} -- try "
                  f"`grep -r {args.query} .fleet-index/symbols/`, then a repo "
                  f"grep", file=sys.stderr)
        if args.path is not None:
            _q_path_dialect_hint(args.path)
        return 1
    if args.src and (len(hits) > 1 or unknown):
        # §11.4: dumping N slices is a token blowout in the exact place this
        # tool exists to prevent one, so ambiguity resolves to pointers.
        _q_print_hits(hits, limit)
        _q_print_notes(notes)
        if len(hits) > 1:
            print("fleet: ambiguous — narrow with `--path`/`--kind`",
                  file=sys.stderr)
        else:
            # One visible hit is not necessarily unique when selected shards went
            # unread. --src may choose one symbol only after reading every competitor.
            print(f"fleet: {unknown} shard(s) could not be read, so this hit "
                  f"is not known to be the only one -- `--src` will not commit "
                  f"to a slice; re-run without `--no-refresh`, or narrow with "
                  f"`--path`/`--kind`", file=sys.stderr)
        return 1
    if args.src:
        return _q_print_slice(root, hits[0], notes)
    _q_print_hits(hits, limit)
    _q_print_notes(notes)
    return 0


def _q_contained(root, rel) -> bool:
    """Require both derived paths to resolve inside their respective roots.
    Check the source against the index root and the shard against symbols/:
    they start at different depths, so a traversal can leave the source inside
    while escaping the shard tree. Resolving also rejects outward links.
    Caller paths may be relative to a subdirectory; containment must hold for
    the raw fallback candidate as well as a cwd-resolved candidate."""
    def inside(child, parent) -> bool:
        return child == parent or parent in child.parents

    try:
        base = Path(root).resolve()
        symbols = index_symbols_dir(base).resolve()
        target = (base / rel).resolve()
        shard = shard_path_for_source(base, rel).resolve()
    except OSError:
        return False
    except IndexPathError:
        # This is a boolean gate: convert the shared path guard's refusal to False.
        # An unspellable shard path cannot be contained.
        return False
    return inside(target, base) and inside(shard, symbols)


def _q_outline_rels(root, raw) -> list:
    """`--outline PATH` as index-root-relative posix paths, best first.

    A path that resolves against the process cwd and lands inside the index
    root wins: a worker that has cd'd into `src/` says `api.py` and means
    `src/api.py`. The raw argument is kept as a second candidate because
    pointer lines print index-root-relative paths, so a worker copying one
    back from a subdirectory must still hit."""
    out = []
    try:
        resolved = Path(raw).expanduser().resolve()
        out.append(resolved.relative_to(Path(root).resolve()).as_posix())
    except (ValueError, OSError):
        pass
    # An invalid raw spelling must not discard a valid resolved candidate: a
    # caller may use docs/../src/api.py while the canonical rel is src/api.py.
    try:
        rel = _index_posix_rel(raw)
    except IndexPathError:
        rel = None
    if rel and rel not in out:
        out.append(rel)
    if out:
        return out
    # Return no candidates for the caller's ordinary outside-root refusal;
    # do not let path parsing turn a usage refusal into a traceback.
    try:
        return [_index_posix_rel(raw)]
    except IndexPathError:
        return []


def _q_outline_known(root, rel) -> bool:
    """Is there something to outline at `rel`?

    Either a shard (which may be stale, missing its source, whatever -- the
    choke point sorts that out), or a source file this index's include/exclude
    actually SELECTS. The selection test is deliberate: outlining an excluded
    file would refresh a shard the very next `build` prunes, which is the same
    promise-it-cannot-keep `update_index` already refuses to make."""
    if shard_path_for_source(root, rel).is_file():
        return True
    if not (Path(root) / rel).is_file():
        return False
    config = load_index_config(root)
    return _index_selects(rel, config["include"], config["exclude"])


def _q_print_outline_candidates(root, rel) -> None:
    """§11.5's `--outline` unknown-path row: the same narrow-it hint shape as
    an ambiguous `--src` -- shard source paths whose final segment matches the
    argument's basename."""
    base = rel.rsplit("/", 1)[-1]
    candidates = [candidate for candidate in index_shard_rels(root)
                  if candidate.rsplit("/", 1)[-1] == base]
    print(f"fleet: no indexed file at {rel!r} -- nothing to outline",
          file=sys.stderr)
    for candidate in candidates[:INDEX_LIST_CAP]:
        print(f"fleet:   candidate {candidate}", file=sys.stderr)
    hidden = len(candidates) - INDEX_LIST_CAP
    if hidden > 0:
        print(f"fleet:   ... and {hidden} more", file=sys.stderr)
    if not candidates:
        print("fleet: no indexed file has that basename -- `fleet index "
              "status` lists what this index covers", file=sys.stderr)


def _cmd_q_outline(root, args) -> int:
    # Containment BEFORE anything touches the shard layer: nothing derived
    # from an out-of-root argument may reach `verified_shard_rows`, whose
    # orphan-prune path unlinks what it is pointed at.
    candidates = [rel for rel in _q_outline_rels(root, args.outline)
                  if _q_contained(root, rel)]
    if not candidates:
        print(f"fleet: --outline {args.outline!r} resolves outside the index "
              f"root {root} -- refused", file=sys.stderr)
        return 1
    rel = next((c for c in candidates if _q_outline_known(root, c)), None)
    if rel is None:
        _q_print_outline_candidates(root, candidates[0])
        return 1
    notes = []
    result = verified_shard_rows(root, rel, no_write=args.no_refresh)
    if result["note"]:
        notes.append(result["note"])
    if result["status"] != "ok":
        # Withheld under --no-refresh, or the source is gone. §11.3 binds
        # `--outline` exactly as it binds a query: no path serves an
        # unverified coordinate.
        _q_print_notes(notes)
        return 1
    # A header-only shard renders to its `## path (N lines, lang)` line and
    # nothing else, and that is exit 0 (§11.5): having no symbols is a fact
    # about the file, not a failure.
    _q_print_capped(_index_split_lines(
        render_digest(rel, result["header"], result["rows"])))
    _q_print_notes(notes)
    return 0


def cmd_q(args) -> int:
    parser = args.q_parser
    # §11.5 row 2: usage errors are argparse's, and argparse exits 2. The two
    # forms in §11.1 are separate grammars, so mixing them is a usage error
    # rather than a silently-ignored flag -- an ignored flag reads as correct.
    if args.outline is None and args.query is None:
        parser.error("give a QUERY or --outline PATH")
    if args.outline is not None and args.query is not None:
        parser.error("--outline takes no QUERY -- they are two different forms")
    if args.outline is not None:
        extra = [name for name, given in (
            ("--src", args.src), ("--path", args.path is not None),
            ("--kind", args.kind is not None),
            ("--limit", args.limit is not None)) if given]
        if extra:
            parser.error("--outline takes only --no-refresh, not "
                         + ", ".join(extra))
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    # §11.1: the walk-up from the process cwd, stopping at the first
    # repository boundary. No flag overrides discovery -- a worker's cwd is
    # its registered `--dir` by construction (invariant 5).
    root = find_index_root()
    if root is None:
        # Exit 3, and the SHIPPED constant: §6 and §11.5 spell this message
        # with different bytes, so the constant is the only correct source.
        print(f"fleet: {INDEX_NO_INDEX_MESSAGE}", file=sys.stderr)
        return 3
    if args.outline is not None:
        return _cmd_q_outline(root, args)
    return _cmd_q_query(root, args)


