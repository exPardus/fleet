#!/usr/bin/env python3
"""Re-execute every pasted `$ ` receipt in a markdown document and diff the output.

This repo's binding rule is that any document specifying a change to code it does
not own must enumerate the affected call sites BY grep, pasting the command AND
its output, pinned to a stated commit. That rule is only worth what the paste is
worth: a receipt nobody re-ran is a claim, and a receipt edited by hand after it
was run is a fabrication that reads exactly like a receipt.

This tool re-runs them. Read-only, stdlib-only, no network, no repo writes.

A RECEIPT IS A CLAIM ABOUT A COMMIT, NOT ABOUT `HEAD`.

That distinction is the whole design. An earlier version of this tool re-ran
every receipt against the *working tree*, which meant any unrelated commit to
`bin/fleet.py` rotted every line-anchored receipt in every spec and turned the
shared suite red. That happened for real: two sibling branches landed ahead of
this one, moved `bin/fleet.py` by ~620 lines, and the merge was reverted on red.
The receipts were not wrong -- they were being checked against the wrong tree.

So each fenced block declares `# at <sha>`, and this tool **materialises that
commit** (`git archive <sha>` piped through `tarfile` into a temp dir -- no
checkout, no `git worktree`, no mutation of the repo) and runs the block's
commands there. A receipt pinned at `ccbbc02` stays true forever; re-pinning
becomes a deliberate edit rather than merge-order roulette.

Format it understands, inside ``` fenced blocks:

    # at <sha>                 <- REQUIRED. commands run against this commit's tree
    # volatile: <reason>       <- evidence lives outside the repo; drift is a WARN
    # live: <reason>           <- deliberately about the working repo, not a commit
    $ <command>                <- executed with `bash -c`
    <expected stdout line>     <- compared exactly
    ...
    $ echo "exit $?"           <- asserts the PREVIOUS command's exit code
    exit 1

Blocks with no `$ ` line (quoted prose, journal entries) are skipped.

Pin rules, all of which fail loudly rather than falling back:

* **No pin** -- UNCLASSIFIED under `--strict` (see gap 2). Falling back to the
  working tree is exactly the rot this design removes, so it is never done
  silently; without `--strict` it runs at the repo root and WARNs.
* **A pin that is not a hex sha** (`# at HEAD`, `# at main`) is an error. A
  moving pin is not a pin -- it reintroduces the rot with extra steps.
* **A pinned commit not present in the repo** is an error, never a skip. On a
  shallow clone, or after a rebase/filter drops the object, the receipt *cannot
  be verified*, and reporting green for an unverifiable receipt is the failure
  this tool exists to prevent. Recovery is to fetch the object
  (`git fetch --unshallow`, or fetch the specific sha) or to re-pin the block
  deliberately against a commit that does exist -- both are decisions a human
  makes, not defaults a tool picks.
* **`# live`** is the escape for a receipt that is genuinely about the current
  repo rather than about a commit -- `git check-ignore` is the real case here:
  it asks git a question about the working repo's ignore rules, which an
  exported tree has no `.git` to answer. A `# live` receipt is still executed
  and diffed; it just runs against the working tree, so it rots if the thing it
  describes changes -- which for `.gitignore` is a deliberate act that *should*
  force the prose to be updated. `# live` requires a reason.

    py -3.13 tools/verify_receipts.py docs/specs/claim-nonce.md
    py -3.13 tools/verify_receipts.py --self-test docs/specs/claim-nonce.md

`--self-test` is not optional ceremony. A verifier that cannot fail reports
green on a document it never checked; this one proves it can fail by mutating a
single word of a pasted receipt in memory and requiring that the mutation is
caught. Run it before trusting any green run.

EXIT CODES -- three, because the self-test has three outcomes.

    0  everything checked, and the harness proved it can fail.
    1  FAILED. A receipt did not reproduce, or the harness did not catch its own
       seed. Something is wrong.
    2  INCONCLUSIVE. Every receipt that could be checked reproduced, but the
       self-test could not be RUN on this document -- no multi-word receipt to
       paraphrase, no classified block to unfence, or an evasion already present
       so a seeded one would prove nothing. Nothing is known to be wrong; the
       harness is simply unproven here.

2 is non-zero on purpose. An unproven verifier is not a verified one, so `set -e`
and `if rc:` gates both still fire -- what changes is that an operator can now
tell "your document gave my seed nothing to bite on" apart from "your verifier
is lying", which used to be the same red. Only 1 ever means a defect, and every
path that means a defect still returns 1: FAILED outranks INCONCLUSIVE wherever
the two meet, so an inconclusive self-test can never mask a receipt failure in
the same run.

KNOWN GAPS -- read these before pointing this tool at a second document.

1. **stderr is never captured or compared.** Only stdout is diffed. A receipt
   whose pasted output came from stderr (or from a `2>&1` the paste dropped)
   will read as an empty-output mismatch, and a command that succeeds on stdout
   while screaming on stderr reads as clean. Deliberate for now -- every receipt
   in `docs/specs/` is a `grep`/`sed`/`git` invocation whose evidence is on
   stdout -- but it is an assumption, not a property.

2. **A `$ ` line with neither expected output nor an exit assertion is
   UNCLASSIFIED.** It cannot be checked: there is nothing to compare against.
   Such a receipt is *reported* and, under `--strict` (which `tests/test_receipts.py`
   uses), *fails the run*. It is never silently dropped. An earlier version of
   this file filtered them out with a list comprehension, which is precisely the
   green-while-blind hole the tool exists to close: a receipt that is neither
   checked nor reported is worse than no tool at all.

3. **Fence detection accepts language tags** (```` ```python ````) as block
   boundaries. It did not always: matching only a bare ```` ``` ```` meant an
   opening tagged fence was treated as prose and the *closing* fence toggled the
   parser INTO a block, inverting every block boundary for the rest of the
   document. No document in `docs/specs/` uses tagged fences today, which is
   exactly why this could have sat unnoticed.

4. **stdout only, exit codes only.** See gap 1. Unchanged by H1.

THE PARSER-EVASION CLASS (H1, closed 2026-07-23).

Everything above assumes the parser SEES the receipt. Until H1 it often did not.
`_parse_block` matched `# at `/`$ ` on **raw** lines, and fence detection used
`lstrip()`, which does not strip `>`. So a receipt block behind a Markdown gutter
was invisible: a blockquoted fence was not a fence at all, and an indented block
was counted as a block that yielded zero receipts. Four such blocks sat in
`docs/specs/three-tier-command.md` through two full review waves while the tool
printed `34/34 receipts reproduce exactly (37 fenced blocks ... 0 FAILED)` and
exited 0 -- with 38 blocks really present. Two independent reviewers quoted that
`34/34 ... (37 fenced blocks)` line and neither reconciled it. A second,
independently written extractor agreed, because both shared the same *unstated*
assumption that receipts live at column 0: independence of implementation is not
independence of assumption.

The fix REJECTS the shapes rather than absorbing them. The canonical form of a
receipt is a **column-0 backtick fence**, and any receipt-shaped text that is not
inside one is an EVASION -- an error under `--strict`, a warning otherwise, never
a silent skip. Rejecting rather than quietly parsing is deliberate, on three
grounds:

* A gutter changes what a Markdown *reader* is told. `> ` means "I am quoting
  this", not "I ran this"; executing quoted text and reporting it as a verified
  receipt asserts something the document does not.
* Absorbing the shapes would leave the founding artifact reporting green. A
  detector that cannot go red on its own founding incident proves nothing, and
  `tests/test_receipts.py::test_founding_artifact_goes_red` replays that exact
  tree out of git history to hold this property.
* Stripping a gutter from *expected output* would change what is diffed, which
  is a new correctness surface on the one thing this tool exists to protect.
  Rejecting has no such surface.

Shapes detected (each after stripping indentation, `>` markers and one list
bullet -- `_GUTTER_RE`):

    gutter-fence   a ``` fence that is not at column 0
    tilde-fence    a ~~~ fence anywhere; not a fence to this tool
    command        a `$ <cmd>` line outside any classified block
    pin            a `# at <sha>` line outside any classified block
    marker         a `# volatile`/`# live` line outside any classified block
    inline-command a `` `$ <cmd>` `` span in prose
    stray-directive a gutter-hidden directive inside a block, before any `$ `
    unterminated-fence  a fence opened and never closed

Inside a block that *did* classify, nothing is scanned: its lines are pasted
output, which may legitimately look like anything, and every one of them is
already diffed byte-for-byte. A block that classifies NOTHING is scanned, so a
prose block is fine and a block full of hidden receipts is not.
"""

from __future__ import annotations

import argparse
import atexit
import enum
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

EXIT_ECHO = 'echo "exit $?"'
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# --- shape recognition (H1) ------------------------------------------------
# A Markdown gutter: indentation, any depth of blockquote marker, and at most one
# list bullet. Stripping this is how receipt-shaped text is RECOGNISED; it is
# never how a block is PARSED (see the module docstring: shapes are rejected, not
# absorbed). `tests/test_receipts.py` keeps its collection-time copy in sync.
# The trailing `(?:\*\*|__)?` strips one bold wrapper: `**$ cmd**` renders as a
# command to a reader, and the bullet alternative does not catch it because that
# arm requires whitespace after `-*+` (H1-m5).
_GUTTER_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:[-*+][ \t]+|\d+[.)][ \t]+)?[ \t]*(?:\*\*|__)?")
_FENCE_MARK_RE = re.compile(r"^(?:`{3,}|~{3,})")
# HORIZONTAL WHITESPACE, not literal spaces (H1-M1). `$<TAB>grep …` renders
# identically to `$ grep …` in every Markdown renderer, and matching only ` `
# meant such a line was neither parsed nor reported -- a silent skip, exit 0.
# That is the H1 class again with a different whitespace byte.
#
# `$ ` followed by something: a bare `$ ` (the marker itself, which both enforced
# specs name in prose) is not a command.
_CMD_SHAPE_RE = re.compile(r"^\$[ \t]+\S")
# Deliberately narrow: the pin token must look like a pin. "Look at line 40" and
# "a commit at 235421e" in prose do not start a line with `# at`, and requiring a
# sha-or-moving-ref keeps a stray `# at the top` from tripping the check.
_PIN_SHAPE_RE = re.compile(
    r"^#[ \t]+at[ \t]+(?:[0-9a-fA-F]{7,40}|HEAD|head|main|master)\b")
_MARK_SHAPE_RE = re.compile(r"^#[ \t]+(?:volatile|live)\b")
_INLINE_CMD_RE = re.compile(r"`\$[ \t]+[^`\s][^`]*`")

_EVASION_DETAIL = {
    "gutter-fence": (
        "fence marker is not at column 0 (blockquote or list/indent gutter), so "
        "this is not a fenced block to the harness and everything in it is "
        "unverified. Move the block to column 0."),
    "tilde-fence": (
        "`~~~` is not a fence to this harness, so this block is unverified. Use a "
        "column-0 ``` fence."),
    "command": (
        "`$ ` command outside any classified block -- it reads as a receipt and is "
        "executed by nothing. Put it in a column-0 ``` fence with its output."),
    "pin": (
        "`# at <sha>` pin outside any classified block -- it pins nothing. Put it "
        "in a column-0 ``` fence with the receipt it pins."),
    "marker": (
        "`# volatile`/`# live` marker outside any classified block -- it marks "
        "nothing, and a receipt it was meant to cover is unmarked."),
    "inline-command": (
        "a `$ ` command in an inline backtick span reads as a receipt and is "
        "executed by nothing. Promote it to a fenced block, or drop the `$ `."),
    "stray-directive": (
        "gutter-hidden receipt directive inside a fenced block, before any `$ ` "
        "line, so it is neither a directive nor pasted output -- it is dropped."),
    "unterminated-fence": (
        "unterminated fence -- the block opened here is never closed, so "
        "everything after it is swallowed and parsed as neither block nor prose."),
    "unclassified-block": (
        "this fenced block holds receipt directives but yielded no receipt at "
        "all. The founding incident's only tell was exactly this arithmetic -- "
        "`34/34 receipts ... (37 fenced blocks)` -- and nobody reconciled it."),
}


class PinError(Exception):
    """A pin that cannot be honoured. Never downgraded to a skip."""


_TREES = {}


def _git(root, *args, binary=False):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True)
    return proc.returncode, (proc.stdout if binary
                             else proc.stdout.decode("utf-8", "replace"))


def pinned_tree(sha, root):
    """Path to a materialised copy of `sha`'s tree. Cached per process.

    `git archive` + `tarfile` rather than `git worktree add`: exporting is a
    pure read, so this tool never writes to the repo it is auditing.
    """
    if sha in _TREES:
        return _TREES[sha].name
    if not SHA_RE.match(sha):
        raise PinError(
            f"pin {sha!r} is not a hex sha. A moving pin (HEAD, a branch name) "
            f"is not a pin -- it reintroduces exactly the working-tree rot that "
            f"pinning removes.")
    rc, _ = _git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    if rc != 0:
        raise PinError(
            f"pinned commit {sha} is not present in this repo, so its receipts "
            f"cannot be verified. This is an error, not a skip: reporting green "
            f"for an unverifiable receipt is the failure this tool prevents. "
            f"Fetch the object (`git fetch --unshallow`, or fetch that sha), or "
            f"re-pin the block deliberately.")
    rc, data = _git(root, "archive", "--format=tar", sha, binary=True)
    if rc != 0 or not data:
        raise PinError(f"`git archive {sha}` produced nothing")
    tmp = tempfile.TemporaryDirectory(prefix=f"receipts-{sha[:8]}-")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        try:
            tar.extractall(tmp.name, filter="data")
        except TypeError:
            # `filter=` landed in 3.12; this repo's floor is 3.10. The archive
            # comes from `git archive` on this repo, not from the network.
            tar.extractall(tmp.name)
    _TREES[sha] = tmp
    return tmp.name


def cleanup():
    for tmp in _TREES.values():
        try:
            tmp.cleanup()
        except OSError:
            pass
    _TREES.clear()


atexit.register(cleanup)


def resolve_bash():
    """Absolute path to a POSIX bash that shares the Windows filesystem view.

    Bare "bash" is not safe to hand to subprocess on Windows: CreateProcess can
    resolve it to the WSL launcher, which sees `/mnt/c/...` instead of `/c/...`
    and cannot read a git worktree's `.git` file. A harness that silently runs
    receipts under a different shell than the author used reports differences
    that are its own fault -- so the shell is resolved explicitly and printed.
    """
    for cand in (os.environ.get("FLEET_VERIFY_BASH"),
                 r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe"):
        if cand and pathlib.Path(cand).exists():
            return cand
    found = shutil.which("bash")
    if not found:
        raise SystemExit("verify_receipts: no bash on PATH")
    return found


BASH = None


class Receipt:
    __slots__ = ("cmd", "expected", "exit_code", "line", "volatile", "pin", "live")

    def __init__(self, cmd, line, volatile, pin=None, live=False):
        self.cmd = cmd
        self.line = line
        self.volatile = volatile
        self.pin = pin
        self.live = live
        self.expected = []
        self.exit_code = None

    def where(self):
        if self.live:
            return "live working tree"
        return f"pinned @ {self.pin}" if self.pin else "UNPINNED"


class Evasion:
    """Receipt-shaped text the parser never sees. Never a skip -- see H1.

    Carries the same surface as `Receipt` (`line`, `cmd`, `where()`, `volatile`,
    `pin`, `live`) so the report printer, `check()` and `tests/test_receipts.py`
    handle it without special-casing.
    """

    __slots__ = ("line", "shape", "cmd", "detail", "volatile", "pin", "live")

    def __init__(self, line, shape, text):
        self.line = line
        self.shape = shape
        self.cmd = text.strip()[:120]
        self.detail = _EVASION_DETAIL[shape]
        self.volatile = False
        self.pin = None
        self.live = False

    def where(self):
        return f"EVASION {self.shape}"


# The shapes that make a line a receipt DIRECTIVE rather than a fence marker.
# A fence is only evidence of evasion when it wraps one of these -- an indented
# ```python snippet inside a bullet is ordinary Markdown, not a hidden receipt,
# and flagging it would teach authors to route around the check.
_DIRECTIVE_SHAPES = frozenset({"command", "pin", "marker"})
_FENCE_SHAPES = frozenset({"gutter-fence", "tilde-fence"})


def _is_fence(raw):
    """Is this line a real column-0 backtick fence?

    CommonMark: **a backtick fence's info string may not contain a backtick.**
    That rule is what distinguishes an opening fence from a four-backtick INLINE
    code span -- the standard way to write a literal ``` in prose. Testing only
    `startswith("```")` opened a phantom block on such a span, which cost a real
    receipt in `docs/reviews/THREE-TIER-REDRAFT-REVIEW-2026-07-23-spec.md:478`
    (H1-M2). It failed closed (`unterminated-fence`), so it was never
    green-while-blind -- but rejecting legal Markdown with the wrong diagnosis is
    how authors learn to route around a check.
    """
    if not raw.startswith("```"):
        return False
    return "`" not in raw.lstrip("`")


def _shape_of(degutterred):
    """The receipt shape of a gutter-stripped line, or None for prose."""
    if _FENCE_MARK_RE.match(degutterred):
        if degutterred[0] == "~":
            return "tilde-fence"
        # Same CommonMark rule as `_is_fence`: an inline span is not a fence,
        # gutter or no gutter.
        return "gutter-fence" if "`" not in degutterred.lstrip("`") else None
    if _CMD_SHAPE_RE.match(degutterred):
        return "command"
    if _PIN_SHAPE_RE.match(degutterred):
        return "pin"
    if _MARK_SHAPE_RE.match(degutterred):
        return "marker"
    return None


class _Doc:
    """Everything one pass over a document yields. `parse()` is the 3-tuple view."""

    __slots__ = ("lines", "receipts", "unclassified", "blocks", "spans",
                 "strays", "unterminated")

    def __init__(self, lines):
        self.lines = lines
        self.receipts, self.unclassified, self.strays = [], [], []
        self.blocks = 0
        self.spans = []          # (open_line, close_line, classified)
        self.unterminated = None


def parse_doc(text):
    """One pass: fenced blocks, their receipts, and where every block sat.

    A fence is a **column-0** ``` marker (gap 3: any language tag allowed). It is
    deliberately NOT `lstrip()`ed: an indented or blockquoted fence is not a
    fence, it is an evasion, and `scan_evasions` reports it as one. Treating it
    as a boundary here is what let four blocks be counted-but-empty in the
    founding incident.
    """
    doc = _Doc(text.splitlines())
    in_block, block, open_line = False, [], 0
    for n, raw in enumerate(doc.lines, start=1):
        if _is_fence(raw):
            if in_block:
                doc.blocks += 1
                ok, bad, stray = _parse_block(block)
                doc.receipts.extend(ok)
                doc.unclassified.extend(bad)
                doc.strays.extend(stray)
                doc.spans.append((open_line, n, bool(ok or bad)))
                in_block, block = False, []
            else:
                in_block, block, open_line = True, [], n
            continue
        if in_block:
            block.append((n, raw))
    if in_block:
        # Not parsed: an unterminated fence has no block. Its contents fall
        # outside every span and are scanned as loose text, which is the loud
        # outcome -- silently swallowing the tail is the failure mode here.
        doc.unterminated = open_line
    return doc


def parse(text):
    """Extract receipts from fenced blocks.

    Returns (checkable, unclassified, blocks_seen). `unclassified` holds
    receipts with nothing to compare against -- see gap 2 in the module
    docstring. They are returned, never dropped.
    """
    doc = parse_doc(text)
    return doc.receipts, doc.unclassified, doc.blocks


def _evading_fences(doc, shapes, fenced):
    """Non-column-0 / tilde fence markers that wrap actual receipt directives.

    Paired the way a Markdown reader pairs them, then judged by contents: a
    gutter-fenced ```python snippet in a bullet is not a receipt and must not be
    reported, or the check becomes noise and authors route around it. All four
    blocks of the founding incident carry a `# at` pin and a `$ ` command, so
    every one of them is still caught.
    """
    markers = [n for n in sorted(shapes)
               if shapes[n] in _FENCE_SHAPES and n not in fenced]
    out = []
    for i in range(0, len(markers) - 1, 2):
        open_n, close_n = markers[i], markers[i + 1]
        if any(shapes.get(n) in _DIRECTIVE_SHAPES
               for n in range(open_n + 1, close_n)):
            out.append(Evasion(open_n, shapes[open_n], doc.lines[open_n - 1]))
            out.append(Evasion(close_n, shapes[close_n], doc.lines[close_n - 1]))
    if len(markers) % 2:
        # An unpaired gutter fence: it hides whatever follows it just as well.
        last = markers[-1]
        if any(shapes.get(n) in _DIRECTIVE_SHAPES
               for n in range(last + 1, len(doc.lines) + 1)):
            out.append(Evasion(last, shapes[last], doc.lines[last - 1]))
    return out


def scan_evasions(text):
    """Every receipt shape the parser did not classify. See H1 in the docstring.

    Independent of `_parse_block`'s matching by construction: it re-reads the
    document through `_GUTTER_RE`, so a gutter form one of them handles and the
    other does not turns the suite red instead of reporting green.
    """
    doc = parse_doc(text)
    classified, orphaned, fenced = set(), set(), set()
    for start, end, ok in doc.spans:
        (classified if ok else orphaned).update(range(start, end + 1))
        fenced.update(range(start, end + 1))
    shapes = {n: _shape_of(_GUTTER_RE.sub("", raw))
              for n, raw in enumerate(doc.lines, start=1)
              if not _is_fence(raw)}            # a real fence is not a shape
    out = []
    if doc.unterminated is not None:
        out.append(Evasion(doc.unterminated, "unterminated-fence", "```"))
    for n, raw in enumerate(doc.lines, start=1):
        if n in classified:
            # Pasted output inside a classified block may look like anything,
            # and every line of it is already diffed byte-for-byte.
            continue
        shape = shapes.get(n)
        if shape in _DIRECTIVE_SHAPES:
            out.append(Evasion(n, shape, raw))
            continue
        if shape or n in orphaned:
            continue                      # a fence marker, or prose in a prose block
        m = _INLINE_CMD_RE.search(raw)
        if m:
            out.append(Evasion(n, "inline-command", m.group(0)))
    out.extend(_evading_fences(doc, shapes, fenced))
    # The block-level reconciliation, reported rather than merely computed. It
    # was previously called by nothing but the tests, so it could not fail a real
    # run no matter what it found (H1-M3). It deliberately overlaps the
    # `orphaned` arm above: killing either path alone must still leave the
    # geometry visible, which is the lesson of the M10+M18 compound.
    for start, _end in blocks_yielding_nothing(text):
        out.append(Evasion(start, "unclassified-block", doc.lines[start - 1]))
    seen = {e.line for e in out}
    for n, raw in doc.strays:
        if n not in seen:
            out.append(Evasion(n, "stray-directive", raw))
    out.sort(key=lambda e: e.line)
    return out


def blocks_yielding_nothing(text):
    """Fenced blocks that hold receipt-shaped text but classified nothing.

    The reconciliation `blocks == receipts + unclassified` does not hold in
    general (one block may carry several receipts), so this is the checkable form
    of it: a block is either receipt-bearing or shape-free. The founding incident
    printed `(37 fenced blocks)` against 34 receipts and nobody reconciled it.
    """
    doc = parse_doc(text)
    out = []
    for start, end, ok in doc.spans:
        if ok:
            continue
        for n in range(start + 1, end):
            if _shape_of(_GUTTER_RE.sub("", doc.lines[n - 1])) in _DIRECTIVE_SHAPES:
                out.append((start, end))
                break
    return out


def _parse_block(lines):
    out, cur, volatile, pin, live = [], None, False, None, False
    stray = []
    for n, raw in lines:
        if raw.startswith("# volatile"):
            volatile = True
            continue
        if raw.startswith("# live"):
            live = True
            continue
        if raw.startswith("# at "):
            # First token after `# at `; the rest of the line may carry prose.
            rest = raw[len("# at "):].strip()
            pin = rest.split()[0] if rest else None
            continue
        if raw.startswith("$ "):
            cmd = raw[2:]
            if cmd.strip() == EXIT_ECHO:
                # The exit-status idiom: the NEXT expected line belongs to the
                # previous command. Mark it so the loop below can attach it.
                if cur is not None:
                    cur = _ExitCapture(cur)
                continue
            cur = Receipt(cmd, n, volatile)
            out.append(cur)
            continue
        if cur is None:
            # Nothing to attach this line to. If it is receipt-SHAPED behind a
            # gutter, it is a directive the block dropped -- report it (H1)
            # rather than let a hidden `# at`/`$ ` vanish inside a real fence.
            if _shape_of(_GUTTER_RE.sub("", raw)) in _DIRECTIVE_SHAPES:
                stray.append((n, raw))
            continue
        if isinstance(cur, _ExitCapture):
            s = raw.strip()
            if s.startswith("exit "):
                try:
                    cur.target.exit_code = int(s.split()[1])
                except (ValueError, IndexError):
                    pass
            continue
        cur.expected.append(raw)
    for r in out:
        r.volatile = r.volatile or volatile
        r.pin = r.pin or pin
        r.live = r.live or live
        while r.expected and not r.expected[-1].strip():
            r.expected.pop()
    # Gap 2: split rather than filter. A receipt with nothing to compare
    # against is UNCLASSIFIED and is reported; it is never silently dropped.
    checkable = [r for r in out if r.expected or r.exit_code is not None]
    unclassified = [r for r in out if not (r.expected or r.exit_code is not None)]
    return checkable, unclassified, stray


class _ExitCapture:
    __slots__ = ("target",)

    def __init__(self, target):
        self.target = target


def run(receipt, root):
    """Execute a receipt in the tree it is a claim about.

    Pinned -> the materialised tree of that commit. `# live` or unpinned -> the
    working tree. Raises PinError if the pin cannot be honoured; callers turn
    that into a reported failure, never a skip.
    """
    cwd = root
    if receipt.pin and not receipt.live:
        cwd = pinned_tree(receipt.pin, root)
    proc = subprocess.run([BASH, "-c", receipt.cmd], cwd=str(cwd),
                          capture_output=True)
    actual = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    while actual and not actual[-1].strip():
        actual.pop()
    return actual, proc.returncode


def check(text, root, quiet=False, strict=False, skip_volatile=False,
          execute=True):
    """Returns (n_checked, failures, warnings). Prints a report unless quiet.

    `strict` promotes UNCLASSIFIED receipts (gap 2) and EVASIONS (H1) to
    failures. `execute=False` reports structure only -- extraction, pins and
    evasions -- without running any command; it is how the founding-artifact
    replay stays fast, and it never suppresses a finding, only the diffing.
    `skip_volatile` does not *execute* receipts marked `# volatile` at all --
    used by `tests/test_receipts.py`, which must stay hermetic. A volatile
    receipt is one whose evidence lives outside the repo (this repo has one:
    a count of session transcripts under ~/.claude). Marking it is how the
    document stays honest about it; skipping it is how the test stays
    machine-independent. Neither loosens what is checked about the rest.
    """
    receipts, unclassified, blocks = parse(text)
    evasions = scan_evasions(text)
    failures, warnings, skipped = [], [], 0
    for e in evasions:
        (failures if strict else warnings).append((e, [f"EVASION: {e.detail}"]))
    for r in unclassified:
        entry = (r, ["UNCLASSIFIED: no expected output and no exit assertion -- "
                     "nothing to verify against"])
        (failures if strict else warnings).append(entry)
    for r in receipts:
        if skip_volatile and r.volatile:
            skipped += 1
            continue
        # An unpinned receipt would be checked against the working tree, which
        # is the rot this design removes. Report it; never fall through quietly.
        if not r.pin and not r.live:
            entry = (r, ["UNPINNED: no `# at <sha>` and not marked `# live` -- "
                         "would be checked against the working tree, which any "
                         "unrelated commit can rot"])
            (failures if strict else warnings).append(entry)
            if strict:
                continue
        if not execute:
            # Structure only. Pin and extraction findings above are already
            # recorded; the diff is what is being skipped, not a finding.
            continue
        try:
            actual, rc = run(r, root)
        except PinError as exc:
            failures.append((r, [f"PIN ERROR: {exc}"]))
            continue
        problems = []
        if r.expected and actual != r.expected:
            for i in range(max(len(actual), len(r.expected))):
                a = actual[i] if i < len(actual) else None
                e = r.expected[i] if i < len(r.expected) else None
                if a != e:
                    problems.append(
                        f"output line {i + 1}\n      EXPECTED: {e!r}\n      ACTUAL:   {a!r}")
                    break
        if r.exit_code is not None and rc != r.exit_code:
            problems.append(f"exit code: expected {r.exit_code}, got {rc}")
        if not problems:
            continue
        entry = (r, problems)
        (warnings if r.volatile else failures).append(entry)
    if not quiet:
        for r, problems in warnings:
            print(f"WARN  line {r.line} [{r.where()}]: {r.cmd}")
            for p in problems:
                print(f"      {p}")
        for r, problems in failures:
            print(f"FAIL  line {r.line} [{r.where()}]: {r.cmd}")
            for p in problems:
                print(f"      {p}")
        pins = sorted({r.pin for r in receipts if r.pin and not r.live})
        if pins:
            print(f"\npins resolved: {', '.join(pins)}")
        total = len(receipts) + len(unclassified)
        # Evasions are counted apart from the receipt fraction: they are not
        # receipts that failed, they are receipts that were never extracted, and
        # folding them in drove the numerator negative.
        #
        # The verdict gets its own line and never shares a sentence with the
        # `N/N reproduce exactly` fraction (H1-m6). The old one-liner could read
        # `34/34 parsed receipts reproduce exactly (… 16 FAILED)` -- a sentence
        # that says green and red at once, which is precisely the shape of
        # reassuring arithmetic nobody reconciled during the founding incident.
        bad = sum(1 for r, _ in failures + warnings if not isinstance(r, Evasion))
        print(f"\nparsed receipts: {total - bad - skipped}/{total} reproduce exactly "
              f"({blocks} fenced blocks, {len(unclassified)} unclassified, "
              f"{skipped} volatile-skipped)")
        if evasions:
            print(f"NOT PARSED:      {len(evasions)} evasion(s) -- receipt-shaped "
                  f"text the harness never classified. Every parsed receipt can "
                  f"reproduce and the document still be unverified.")
        print(f"VERDICT:         {'FAILED' if failures else 'pass'} -- "
              f"{len(failures)} failure(s), {len(warnings)} warning(s)")
    return len(receipts), failures, warnings


# --- the self-test's three outcomes ----------------------------------------
#
# `self_test` used to return a bare bool and `main()` turned every `False` into
# `rc=1`. Two populations produced that `False`, and they mean opposite things:
# the harness COULD NOT RUN the check (nothing is known to be wrong), and the
# harness PROVED ITSELF BROKEN. Collapsing them is over-loud -- pointing
# `--self-test` at a document with no multi-word receipt to paraphrase read
# exactly like a verifier caught lying about a green run, so the signal that
# matters was buried under a red that usually meant nothing.
#
# The tempting fix -- let `main()` ignore the falsy return -- is over-QUIET, and
# that is strictly worse: it converts every genuine failure into silence. So the
# state is carried through all four functions, and INCONCLUSIVE is quieter than
# FAILED but never SILENT: it still exits non-zero, because a self-test that
# could not run has proved nothing, and the doctrine here is that what the
# harness cannot classify is never a skip.
#
# A verdict REFUSES to be coerced to bool. Two of the pins in
# `tests/test_receipts.py` were `assert self_test(...)` / `assert
# self_test_extraction(...)`, and any all-truthy tri-state (a string constant, a
# plain enum) leaves both of them passing on INCONCLUSIVE -- the corpus's two
# strongest anti-vacuity pins going green-while-blind on the day this landed,
# which is the same failure class one level up. `TypeError` makes it loud.
class Verdict(enum.Enum):
    PASSED = "passed"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"

    def __bool__(self):
        raise TypeError(
            "a self-test Verdict has three states and must not be coerced to a "
            "bool: `if verdict:` silently folds INCONCLUSIVE into one of the "
            "other two, which is the collapse this type exists to prevent. "
            "Compare explicitly -- `verdict is Verdict.FAILED`.")


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INCONCLUSIVE = 2

# Worst last. `worse()` replaces the boolean `and` that used to accumulate the
# two extraction seeds: both seeds still run, and the WORSE verdict wins, so a
# passing second seed can never bury a failing first one.
_SEVERITY = {Verdict.PASSED: 0, Verdict.INCONCLUSIVE: 1, Verdict.FAILED: 2}

EXIT_CODE = {
    Verdict.PASSED: EXIT_OK,
    Verdict.FAILED: EXIT_FAILED,
    Verdict.INCONCLUSIVE: EXIT_INCONCLUSIVE,
}

_VERDICT_NOTE = {
    Verdict.PASSED:
        "the harness proved it can fail, on both seed classes.",
    Verdict.INCONCLUSIVE:
        ("the harness could not RUN a seed on this document, so this run proves "
         "nothing about the harness. It is not a claim that any receipt is "
         "wrong -- the VERDICT line above is what says that. Still non-zero: an "
         "unproven verifier is not a verified one."),
    Verdict.FAILED:
        ("the harness did not catch its own seed. Its green runs mean nothing "
         "until this passes."),
}


def worse(*verdicts):
    """The worst of the verdicts given. FAILED > INCONCLUSIVE > PASSED."""
    return max(verdicts, key=_SEVERITY.__getitem__)


def self_test(text, root):
    """Prove the checker can fail: paraphrase one word of a pasted receipt.

    Mutates the first word of the first expected-output line of the first
    non-volatile receipt that currently reproduces, and requires that exactly
    that receipt is then reported as a failure.

    Returns a `Verdict`, never a bool. INCONCLUSIVE means this document gave the
    seed nothing to work with; FAILED means the harness is broken.
    """
    receipts, _unclassified, _blocks = parse(text)
    target = None
    for r in receipts:
        if r.volatile or not r.expected:
            continue
        actual, rc = run(r, root)
        if actual == r.expected and (r.exit_code is None or rc == r.exit_code):
            for line in r.expected:
                if line.strip() and len(line.split()) > 1:
                    target = (r, line)
                    break
        if target:
            break
    if target is None:
        # Nothing is known to be wrong: a document whose receipts are all
        # volatile, all single-word, or none of which currently reproduce simply
        # offers no seed target. `check()` below is what reports the last case.
        print("SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate")
        return Verdict.INCONCLUSIVE
    r, line = target
    words = line.split(" ")
    for i, w in enumerate(words):
        if w.strip():
            words[i] = w + "X" if w.isalpha() else "PARAPHRASED"
            break
    mutated_line = " ".join(words)
    # Seed the EXPECTED-OUTPUT line by index, not `text.replace(...)`. A receipt
    # like `$ echo one two` / `one two` contains its own expected text inside the
    # command, so a first-occurrence replace mutated the COMMAND instead -- the
    # seed then failed for the wrong reason and the self-test reported that it
    # could not catch a paraphrase it had never actually planted. Expected lines
    # always follow their `$ ` line, so the search starts there.
    doc_lines = text.splitlines()
    idx = next((i for i in range(r.line, len(doc_lines))
                if doc_lines[i] == line), None)
    if idx is None:
        # FAILED, not inconclusive. `_parse_block` appends expected lines
        # VERBATIM and `r.line` is the 1-based document line of this receipt's
        # own `$ ` line, so the 0-based search above starts exactly on its first
        # expected line; parser and mutator both split the same `text`. The line
        # is therefore always findable, and reaching here means the harness's own
        # line accounting is wrong -- something KNOWN to be broken, which is the
        # very class this self-test exists to surface.
        print("SELF-TEST FAILED: could not locate the expected line to seed, so "
              "the parser's line accounting disagrees with the document it just "
              "parsed. Nothing this harness reports can be trusted until that is "
              "explained.")
        return Verdict.FAILED
    doc_lines[idx] = mutated_line
    mutated_text = "\n".join(doc_lines) + "\n"
    if mutated_text == text:
        # FAILED, not inconclusive -- and unreachable by construction, which is
        # why it is labelled loudly. Getting here required `line.strip()` and
        # `len(line.split()) > 1`, so `line.split(" ")` holds a word with
        # `w.strip()` truthy, and both mutation arms (`w + "X"`, `"PARAPHRASED"`)
        # always change that word. A seeder that did not seed has broken the one
        # thing this function does; it has not merely run out of material.
        print("SELF-TEST FAILED: mutation did not change the document, so the "
              "seed never planted anything and any 'caught' verdict below would "
              "be about the unmutated text.")
        return Verdict.FAILED
    print(f"seeding a one-word paraphrase into the receipt at line {r.line}")
    print(f"  original: {line.strip()[:100]}")
    print(f"  seeded:   {mutated_line.strip()[:100]}")
    _, failures, _ = check(mutated_text, root, quiet=True)
    caught = any(f[0].cmd == r.cmd for f in failures)
    print(f"  harness reported {len(failures)} failure(s); "
          f"seeded receipt caught: {caught}")
    if not caught:
        print("SELF-TEST FAILED: the harness did not catch a seeded paraphrase. "
              "Its green runs mean nothing until this passes.")
        return Verdict.FAILED
    _, clean_failures, _ = check(text, root, quiet=True)
    if any(f[0].cmd == r.cmd for f in clean_failures):
        print("SELF-TEST FAILED: the seeded receipt also fails unmutated")
        return Verdict.FAILED
    print("SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.")
    return self_test_extraction(text, root)


def _extraction_seed(name, seeded, before):
    """One extraction seed's verdict. Returns a `Verdict`, never a bool.

    Returning a bare `False` for the INCONCLUSIVE arm is what poisoned
    `self_test_extraction`'s accumulator: a seed that could not be planted was
    indistinguishable there from a harness that failed to report a planted one.
    """
    doc = parse_doc(seeded)
    after = len(doc.receipts) + len(doc.unclassified)
    evasions = scan_evasions(seeded)
    print(f"  seed [{name}]: receipts {before} -> {after}, "
          f"{len(evasions)} evasion(s) reported")
    if after >= before:
        # Genuinely inconclusive, and genuinely reachable: deleting a block's two
        # fence lines re-pairs every LATER fence in the document, so in a
        # multi-block document the parsed count can stay flat or rise. The seed
        # did not do what it intended; that is not evidence of a defect.
        print(f"EXTRACTION SELF-TEST INCONCLUSIVE [{name}]: the seed removed no receipt")
        return Verdict.INCONCLUSIVE
    if not evasions:
        print(f"EXTRACTION SELF-TEST FAILED [{name}]: {before - after} receipt(s) "
              f"stopped being parsed and NOTHING was reported. Green runs mean "
              f"nothing until this passes.")
        return Verdict.FAILED
    return Verdict.PASSED


def self_test_extraction(text, root):
    """Prove the harness notices a receipt that stopped being PARSED.

    The paraphrase seed above proves a *parsed* receipt can fail, which is silent
    about everything unparsed -- the entire H1 class. This seeds the two shapes
    that produced the founding incident: a block whose fences are removed, and a
    block pushed behind a `> ` gutter. Both must drop the receipt count AND be
    reported. Structure only; nothing is executed.

    Returns a `Verdict`, never a bool: the worse of the two seeds' verdicts.
    """
    doc = parse_doc(text)
    before = len(doc.receipts) + len(doc.unclassified)
    target = next(((s, e) for s, e, ok in doc.spans if ok), None)
    if target is None or before == 0:
        print("EXTRACTION SELF-TEST INCONCLUSIVE: no classified fenced block to seed")
        return Verdict.INCONCLUSIVE
    if scan_evasions(text):
        # The document's own evasion is `check(--strict)`'s to fail on, not this
        # function's: a seeded evasion proves nothing when an unseeded one is
        # already being reported. Nothing here is known to be wrong.
        print("EXTRACTION SELF-TEST INCONCLUSIVE: the document already carries an "
              "evasion, so a seeded one proves nothing")
        return Verdict.INCONCLUSIVE
    start, end = target
    lines = text.splitlines()
    print(f"seeding an extraction failure into the block at lines {start}-{end}")
    unfenced = "\n".join(l for n, l in enumerate(lines, start=1)
                         if n not in (start, end)) + "\n"
    quoted = "\n".join("> " + l if start <= n <= end else l
                       for n, l in enumerate(lines, start=1)) + "\n"
    # Both seeds always run -- `worse()` is not short-circuiting, and neither was
    # the `and` it replaced (the call was evaluated before the conjunction). The
    # WORSE verdict wins, so a passing second seed cannot bury a failing first.
    verdict = worse(_extraction_seed("fences removed", unfenced, before),
                    _extraction_seed("blockquote gutter", quoted, before))
    if verdict is Verdict.PASSED:
        print("EXTRACTION SELF-TEST PASSED: a receipt that stops being parsed is "
              "reported, not silently dropped.")
    return verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="markdown file(s) to verify")
    ap.add_argument("--root", default=".", help="cwd for the commands (default: .)")
    ap.add_argument("--self-test", action="store_true",
                    help=(f"prove the harness can fail, then verify. Exits "
                          f"{EXIT_FAILED} if the harness failed its own seed or "
                          f"any receipt did not reproduce, {EXIT_INCONCLUSIVE} if "
                          f"the seed could not be RUN on this document (nothing "
                          f"known to be wrong), {EXIT_OK} otherwise"))
    ap.add_argument("--strict", action="store_true",
                    help="an unclassified receipt fails the run (see gap 2)")
    ap.add_argument("--skip-volatile", action="store_true",
                    help="do not execute receipts marked `# volatile`")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    global BASH
    BASH = resolve_bash()
    print(f"shell: {BASH}\nroot:  {root}")
    # Two accumulators, deliberately. Folding them into one would let the
    # printed self-test verdict absorb a receipt failure and read as though the
    # HARNESS were broken when it is the DOCUMENT that is -- and the operator
    # acts differently on those two. The exit code takes the worse of the pair,
    # so an INCONCLUSIVE self-test can never mask a receipt that did not
    # reproduce: FAILED outranks INCONCLUSIVE, always.
    self_test_verdict = Verdict.PASSED
    receipts_failed = False
    for p in args.paths:
        text = pathlib.Path(p).read_text(encoding="utf-8")
        print(f"=== {p} ===")
        if args.self_test:
            self_test_verdict = worse(self_test_verdict, self_test(text, root))
        _, failures, _ = check(text, root, strict=args.strict,
                               skip_volatile=args.skip_volatile)
        if failures:
            receipts_failed = True
    verdict = (worse(self_test_verdict, Verdict.FAILED) if receipts_failed
               else self_test_verdict)
    if args.self_test:
        print(f"\nSELF-TEST VERDICT: {self_test_verdict.name} -- "
              f"{_VERDICT_NOTE[self_test_verdict]}")
    # An exit code nobody can read is a number, not a diagnosis -- and it must
    # name WHICH of the two accumulators produced it. The confusing shape is a
    # document whose self-test is INCONCLUSIVE and whose receipts also fail:
    # `SELF-TEST VERDICT: INCONCLUSIVE` sits directly above `EXIT: 1 (FAILED)`,
    # and without this the reader can only guess that the 1 came from the
    # receipts rather than from the self-test.
    causes = []
    if self_test_verdict is not Verdict.PASSED:
        causes.append(f"self-test {self_test_verdict.name}")
    if receipts_failed:
        causes.append("receipt failure(s)")
    print(f"EXIT:            {EXIT_CODE[verdict]} ({verdict.name})"
          + (f" -- from {', '.join(causes)}" if causes else ""))
    return EXIT_CODE[verdict]


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
