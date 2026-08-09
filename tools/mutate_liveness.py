"""Mutation driver + ledger for `tests/test_liveness_readers.py`.

WHY THIS FILE IS COMMITTED (w50 gate2 finding m2). The w50 report called this
driver "a deliverable, not a one-off" and then did not commit it, so the
`KILLED` verdicts pasted into the report were claims -- which is exactly what
this repo's receipt rule forbids. The gate re-derived two of five by hand in
about ten minutes; the other three stood on prose. Now anyone can re-run all of
them:

    py -3.13 tools/mutate_liveness.py            # or 3.10
    py -3.13 tools/mutate_liveness.py --list     # ledger only, no runs

BINDING CONTRACT, enforced in code rather than in prose:
  * all mutation happens on a `git archive HEAD` scratch export -- the real
    worktree's `bin/fleet.py` is NEVER written (re-checked and reported);
  * every patch asserts `occurrences == 1` BEFORE anything runs; 0 or >1 aborts;
  * the FLOOR runs first on the clean export and must be green;
  * every restore is proved byte-identical by sha256 against the floor digest;
  * no run ever starts with a mutant on disk.

A mutant that SURVIVES is a defect in the test file, not in the mutant. Adding a
test to `tests/test_liveness_readers.py` without adding its mutant here is how
gate1 F3 and gate2 B2 both happened: three tests asserting source text, and one
`INVERT-ON-BUILD` pin that stayed green when the defect it named was fixed.
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTFILE = "tests/test_liveness_readers.py"

# ---------------------------------------------------------------------------
# THE LEDGER. (id, claim, anchor, replacement, expect)
#   expect="KILLED"  -- the test file must go RED. The property is pinned.
# Every anchor must appear EXACTLY ONCE in bin/fleet.py or the driver aborts.
# ---------------------------------------------------------------------------
MUTANTS = [
    ("M-A", "the stale-beat DISARM of _supervisor_gate is deleted",
     "    if age > SUPERVISOR_CLAIM_STALE_SECONDS:\n        return                      # stale: disarmed",
     "    if False:  # MUTANT M-A\n        return                      # stale: disarmed",
     "KILLED"),

    ("M-B2", "respawn gains a --force bypass of the unfetchable-roster refusal",
     '''    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        raise FleetCliError(
            f"{name}: could not fetch the native roster -- refusing respawn "
            "until the old session's liveness can be verified"
        )''',
     '''    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
    if not roster_ok and not getattr(args, "force", False):  # MUTANT M-B2
        raise FleetCliError(
            f"{name}: could not fetch the native roster -- refusing respawn "
            "until the old session's liveness can be verified"
        )''',
     "KILLED"),

    ("M-C", "clean DOOMS instead of sparing on an unreadable roster",
     "    live_sids = _roster_live_sids(roster_entries) if roster_ok else None",
     "    live_sids = _roster_live_sids(roster_entries)  # MUTANT M-C",
     "KILLED"),

    ("M-D", "a Q1 call site is relocated out of _wedged_release_gate "
            "(a decoy keeps the AST call count unchanged)",
     "    live_now = _releaser_live_sids(claim, _roster_live_sids(payload),",
     "    live_now = _releaser_live_sids(claim, _mutant_d_decoy(payload),",
     "KILLED"),

    ("M-E", "the state != 'done' clause is deleted from _roster_live_sids",
     '        and e.get("state") != "done"\n',
     '        and True  # MUTANT M-E\n',
     "KILLED"),

    # --- added after gate2 -------------------------------------------------
    ("M-GATE2", "THE B6 UNION GATE IS FIXED: _any_live also counts a keyed "
                "entry whose state is 'done' (_roster_live_sids untouched, "
                "exactly as the build brief prescribes)",
     "            return bool(gate_sids & _roster_live_sids(entries))",
     "            return bool(gate_sids & {e.get('sessionId') for e in entries "
     "if isinstance(e, dict) and ('status' in e or 'pid' in e)})  # MUTANT M-GATE2",
     "KILLED"),

    ("M-GATE3", "THE WORKER PATH IS FIXED: respawn also stops a keyed-but-done "
                "old session instead of skipping the whole stop block",
     "    old_live = old_sid in _roster_live_sids(entries)",
     "    old_live = old_sid in {e.get('sessionId') for e in entries "
     "if isinstance(e, dict) and ('status' in e or 'pid' in e)}  # MUTANT M-GATE3",
     "KILLED"),
]

# M-D needs a compensating definition so the AST CALL COUNT is unchanged --
# that is the whole point: a count assertion cannot see the relocation.
M_D_DECOY = '''

def _mutant_d_decoy(entries):
    return _roster_live_sids(entries)  # MUTANT M-D pt2
'''


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", shell=True)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_scratch(scratch):
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    r = sh(f'git archive HEAD | tar -x -C "{scratch.as_posix()}"', cwd=REPO)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit(2)
    # The test file under development may be UNCOMMITTED -- grade the working
    # copy, or this driver certifies the wrong bytes.
    shutil.copy2(REPO / TESTFILE, scratch / TESTFILE)


def run_tests(scratch, py):
    """(rc, summary_line, [failed test ids]).

    The failure NAMES matter, not just the count: a mutant that kills two tests
    might be killing the pin it targets plus its control (good), or two
    unrelated tests while the pin stays green (which is the gate2 B2 shape
    wearing a KILLED label). Reporting the ids is what lets a reader tell those
    apart without re-running anything.
    """
    r = sh(f"py -{py} -m pytest {TESTFILE} -q", cwd=scratch)
    out = (r.stdout or "").splitlines()
    tail = [l for l in out if l.strip()]
    # `FAILED tests/x.py::Cls::test_name - AssertionError: ...` -> `Cls::test_name`.
    # NOT `l.split(" ")[0]`, which yields the literal "FAILED" -- the first
    # version of this line did exactly that and printed `RED: FAILED` seven
    # times, which is a report that cannot distinguish a targeted kill from an
    # incidental one. Caught by reading the output instead of the exit code.
    failed = [l[len("FAILED "):].split(" ")[0].split("::", 1)[-1]
              for l in out if l.startswith("FAILED ")]
    return r.returncode, (tail[-1] if tail else "<no output>"), failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--py", default="3.13", help="interpreter tag for `py -X`")
    ap.add_argument("--scratch", default=None)
    ap.add_argument("--list", action="store_true", help="print the ledger and exit")
    ap.add_argument("--only", default=None, help="run one mutant id")
    args = ap.parse_args()

    if args.list:
        for mid, claim, *_ in MUTANTS:
            print(f"{mid:<9} {claim}")
        return 0

    scratch = Path(args.scratch) if args.scratch else REPO / ".mutate-scratch"
    build_scratch(scratch)
    target = scratch / "bin" / "fleet.py"
    floor = sha(target)
    print(f"scratch      : {scratch}")
    print(f"FLOOR sha256 : {floor}")

    rc, line, _ = run_tests(scratch, args.py)
    print(f"=== FLOOR (clean export, no mutant) === rc={rc}  {line}")
    if rc != 0:
        print("FLOOR IS NOT GREEN -- every verdict below would be meaningless. ABORT.")
        return 2
    print()

    results, bad = [], False
    for mid, claim, old, new, expect in MUTANTS:
        if args.only and args.only != mid:
            continue
        src = target.read_text(encoding="utf-8")
        n = src.count(old)
        if n != 1:
            print(f"{mid}: ANCHOR MATCHED {n} TIMES (need exactly 1) -- ABORT")
            return 3
        patched = src.replace(old, new) + (M_D_DECOY if mid == "M-D" else "")
        target.write_text(patched, encoding="utf-8")
        if sha(target) == floor:
            print(f"{mid}: patch did not change the file -- ABORT")
            return 3

        rc, line, failed = run_tests(scratch, args.py)
        got = "KILLED" if rc != 0 else "SURVIVED"
        ok = got == expect
        bad |= not ok
        print(f"{mid}  {claim}")
        print(f"      -> rc={rc}  {line}")
        for tid in failed:
            print(f"         RED: {tid}")
        print(f"      ==> {got} (expected {expect}) {'OK' if ok else '*** MISMATCH ***'}")

        target.write_text(src, encoding="utf-8")
        if sha(target) != floor:
            print(f"{mid}: RESTORE FAILED -- ABORT")
            return 4
        print(f"      restored byte-identical (sha256): True")
        results.append((mid, got, expect, failed))
        print()

    print("=== SUMMARY ===")
    for mid, got, expect, failed in results:
        print(f"  {mid:<9} {got:<9} (expected {expect})  "
              f"{'; '.join(failed) if failed else ''}")
    print(f"final sha256 == floor      : {sha(target) == floor}")
    clean = sh("git diff --quiet HEAD -- bin/fleet.py", cwd=REPO).returncode == 0
    print(f"real worktree bin/fleet.py : {'untouched' if clean else '*** MODIFIED ***'}")
    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if (bad or not clean) else 0


if __name__ == "__main__":
    sys.exit(main())
