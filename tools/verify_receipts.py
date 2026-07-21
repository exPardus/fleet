#!/usr/bin/env python3
"""Re-execute every pasted `$ ` receipt in a markdown document and diff the output.

This repo's binding rule is that any document specifying a change to code it does
not own must enumerate the affected call sites BY grep, pasting the command AND
its output, pinned to a stated commit. That rule is only worth what the paste is
worth: a receipt nobody re-ran is a claim, and a receipt edited by hand after it
was run is a fabrication that reads exactly like a receipt.

This tool re-runs them. Read-only, stdlib-only, no network, no repo writes.

Format it understands, inside ``` fenced blocks:

    # at <sha>                 <- pin metadata, ignored
    # volatile: <reason>       <- rest of block may drift; mismatches become WARN
    $ <command>                <- executed with `bash -c` from --root
    <expected stdout line>     <- compared exactly
    ...
    $ echo "exit $?"           <- asserts the PREVIOUS command's exit code
    exit 1

Blocks with no `$ ` line (quoted prose, journal entries) are skipped.

    py -3.13 tools/verify_receipts.py docs/specs/claim-nonce.md
    py -3.13 tools/verify_receipts.py --self-test docs/specs/claim-nonce.md

`--self-test` is not optional ceremony. A verifier that cannot fail reports
green on a document it never checked; this one proves it can fail by mutating a
single word of a pasted receipt in memory and requiring that the mutation is
caught. Run it before trusting any green run.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys

EXIT_ECHO = 'echo "exit $?"'


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
    __slots__ = ("cmd", "expected", "exit_code", "line", "volatile")

    def __init__(self, cmd, line, volatile):
        self.cmd = cmd
        self.line = line
        self.volatile = volatile
        self.expected = []
        self.exit_code = None


def parse(text):
    """Extract receipts from fenced blocks. Returns (receipts, blocks_seen)."""
    receipts, blocks = [], 0
    in_block, block, block_start = False, [], 0
    for n, raw in enumerate(text.splitlines(), start=1):
        if raw.strip() == "```":
            if in_block:
                blocks += 1
                receipts.extend(_parse_block(block, block_start))
            in_block, block, block_start = not in_block, [], n + 1
            continue
        if in_block:
            block.append((n, raw))
    return receipts, blocks


def _parse_block(lines, _start):
    out, cur, volatile = [], None, False
    for n, raw in lines:
        if raw.startswith("# volatile"):
            volatile = True
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
        while r.expected and not r.expected[-1].strip():
            r.expected.pop()
    return [r for r in out if r.expected or r.exit_code is not None]


class _ExitCapture:
    __slots__ = ("target",)

    def __init__(self, target):
        self.target = target


def run(receipt, root):
    proc = subprocess.run([BASH, "-c", receipt.cmd], cwd=str(root),
                          capture_output=True)
    actual = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    while actual and not actual[-1].strip():
        actual.pop()
    return actual, proc.returncode


def check(text, root, quiet=False):
    """Returns (n_checked, failures, warnings). Prints a report unless quiet."""
    receipts, blocks = parse(text)
    failures, warnings = [], []
    for r in receipts:
        actual, rc = run(r, root)
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
            print(f"WARN  (volatile) line {r.line}: {r.cmd}")
            for p in problems:
                print(f"      {p}")
        for r, problems in failures:
            print(f"FAIL  line {r.line}: {r.cmd}")
            for p in problems:
                print(f"      {p}")
        print(f"\n{len(receipts) - len(failures) - len(warnings)}/{len(receipts)} "
              f"receipts reproduce exactly "
              f"({blocks} fenced blocks, {len(warnings)} volatile-drift, "
              f"{len(failures)} FAILED)")
    return len(receipts), failures, warnings


def self_test(text, root):
    """Prove the checker can fail: paraphrase one word of a pasted receipt.

    Mutates the first word of the first expected-output line of the first
    non-volatile receipt that currently reproduces, and requires that exactly
    that receipt is then reported as a failure.
    """
    receipts, _ = parse(text)
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
        print("SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate")
        return False
    r, line = target
    words = line.split(" ")
    for i, w in enumerate(words):
        if w.strip():
            words[i] = w + "X" if w.isalpha() else "PARAPHRASED"
            break
    mutated_line = " ".join(words)
    mutated_text = text.replace(line, mutated_line, 1)
    if mutated_text == text:
        print("SELF-TEST INCONCLUSIVE: mutation did not change the document")
        return False
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
        return False
    _, clean_failures, _ = check(text, root, quiet=True)
    if any(f[0].cmd == r.cmd for f in clean_failures):
        print("SELF-TEST FAILED: the seeded receipt also fails unmutated")
        return False
    print("SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="markdown file(s) to verify")
    ap.add_argument("--root", default=".", help="cwd for the commands (default: .)")
    ap.add_argument("--self-test", action="store_true",
                    help="prove the harness can fail, then verify")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    global BASH
    BASH = resolve_bash()
    print(f"shell: {BASH}\nroot:  {root}")
    rc = 0
    for p in args.paths:
        text = pathlib.Path(p).read_text(encoding="utf-8")
        print(f"=== {p} ===")
        if args.self_test and not self_test(text, root):
            rc = 1
        _, failures, _ = check(text, root)
        if failures:
            rc = 1
    return rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
