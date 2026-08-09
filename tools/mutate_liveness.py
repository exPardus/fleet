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
# TWO files since wave 52. It was one string, and a driver that grades only the
# file it was born with is the gate2 B2 shape one level up: the w52 build added
# seven pins in `tests/test_respawn_retired_sweep.py`, and every mutant aimed at
# them would have reported SURVIVED -- not because the pins were weak, but
# because nothing ran them. The ledger's own contract ("a mutant that SURVIVES
# is a defect in the test file") is only true if the driver runs every file the
# ledger's mutants are aimed at.
TESTFILES = ("tests/test_liveness_readers.py",
             "tests/test_respawn_retired_sweep.py")

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

    # --- added by the w52 build (§3.8). ------------------------------------
    # These aim at `tests/test_respawn_retired_sweep.py`, which is why
    # `TESTFILES` above stopped being a single string in the same commit. Each
    # one models the specific way the fix could be written wrong -- not merely
    # deleted -- because a build's own pins are the ones most likely to have
    # been shaped around the implementation instead of around the property.
    ("M-W52-SWEEP", "the retired-sid sweep is removed from the worker respawn "
                    "path, restoring the §3.8 gap (the tombstone stays, so the "
                    "kill path's pins and half of this file's cannot notice)",
     """        _sweep_retired_sessions(name, _sweep, other_current_sids,
                                run=run, which=which)""",
     "        pass  # MUTANT M-W52-SWEEP",
     "KILLED"),

    ("M-W52-TOMB", "the tombstone goes back inside the liveness branch: the "
                   "sweep still runs, so the process is stopped and the "
                   "DURABLE half of the finding silently reopens",
     """    if not old_live:
        # G10, for the branch that never reached the write above. Same kind""",
     """    if old_live and False:  # MUTANT M-W52-TOMB
        # G10, for the branch that never reached the write above. Same kind""",
     "KILLED"),

    ("M-W52-ORDER", "the respawn sweep sorts before capping -- FIX WAVE 3's "
                    "MAJ-NEW defect, replanted on the new call site: `[-cap:]` "
                    "becomes LEXICOGRAPHIC and discards whichever sids sort "
                    "low rather than the oldest",
     "    _sweep = [s for s in dict.fromkeys(prior_retired + [old_sid])",
     "    _sweep = [s for s in sorted(dict.fromkeys(prior_retired + [old_sid]))"
     "  # MUTANT M-W52-ORDER",
     "KILLED"),

    ("M-W52-CAP", "the respawn sweep loses its cap, so one respawn of a much-"
                  "steered worker can block for cap x timeout seconds with no "
                  "bound at all",
     "              if s and not (old_live and s == old_sid)][-_RETIRED_SID_SWEEP_CAP:]",
     "              if s and not (old_live and s == old_sid)]  # MUTANT M-W52-CAP",
     "KILLED"),

    ("M-W52-M1", "the M1 cross-worker ownership skip is disarmed in the SHARED "
                 "sweep body -- the guard the extraction exists to keep "
                 "single-sourced. A corrupted registry now lets one worker's "
                 "sweep stop another worker's LIVE session.",
     "        if retired in other_current_sids:",
     "        if False:  # MUTANT M-W52-M1",
     "KILLED"),

    ("M-W52-DOUBLE", "the --force arm's already-stopped sid is no longer "
                     "excluded from the sweep, so a forced respawn stops the "
                     "old session twice and tombstones around a redundant stop",
     "              if s and not (old_live and s == old_sid)][-_RETIRED_SID_SWEEP_CAP:]",
     "              if s][-_RETIRED_SID_SWEEP_CAP:]  # MUTANT M-W52-DOUBLE",
     "KILLED"),

    # The two CONTRACT-PRESERVATION pins the build must not have moved. Both
    # were green before the build and after it, so without a mutant each they
    # are exactly the shape gate2 B2 named -- a pin nobody has shown can fail.
    ("M-W52-REFUSE", "the no-force refusal on a Q1-live turn is deleted, so a "
                     "bare respawn walks into the sweep against a RUNNING turn "
                     "-- the one thing the unconditional stop must never do",
     """    stopped_ok = None
    if old_live:
        if not getattr(args, "force", False):""",
     """    stopped_ok = None
    if old_live:
        if False:  # MUTANT M-W52-REFUSE""",
     "KILLED"),

    ("M-W52-ROSTER", "the unfetchable-roster refusal is deleted outright (M-B2 "
                     "only force-gates it, and force-gating leaves the "
                     "no-force path refusing, so M-B2 cannot reach this pin): "
                     "an unreadable roster now reads as `old_live=False` and "
                     "the sweep stops sessions on ambiguous data",
     '''    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
    if not roster_ok:
        raise FleetCliError(
            f"{name}: could not fetch the native roster -- refusing respawn "
            "until the old session's liveness can be verified"
        )''',
     '''    roster_ok, entries = _fetch_agents_roster(which=which, run=run)
    if False:  # MUTANT M-W52-ROSTER
        raise FleetCliError(
            f"{name}: could not fetch the native roster -- refusing respawn "
            "until the old session's liveness can be verified"
        )''',
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


def text_roundtrip_is_byte_exact(target, floor):
    """Wave 51's rule -- *a mutant planter must work on BYTES* -- ENFORCED
    rather than trusted, added by w52.

    This driver patches with `read_text`/`write_text`, which translate line
    endings in BOTH directions. That is byte-exact only while the export's
    EOLs already match `os.linesep`, which is measurably true here (`git
    archive` applies the `.gitattributes`/eol conversion, so on win32 the
    export is CRLF exactly like the checkout, and `os.linesep` is CRLF) --
    and silently destructive the moment it is not: a mixed-ending file, an LF
    export graded on Windows, a CRLF file graded on Linux.

    `sha()` reads BYTES, so the existing post-restore check is genuine and
    would notice -- but only AFTER a mutant had already been graded against
    bytes that were never HEAD's, and a verdict from the wrong bytes is worth
    nothing whichever colour it comes out. Wave 51's other rule is the one
    that applies: a plant driver must prove its own mechanism sound BEFORE it
    runs anything. This does the round-trip as a NO-OP patch and compares.
    """
    target.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    return sha(target) == floor


def build_scratch(scratch):
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    r = sh(f'git archive HEAD | tar -x -C "{scratch.as_posix()}"', cwd=REPO)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        sys.exit(2)
    # The test files under development may be UNCOMMITTED -- grade the working
    # copies, or this driver certifies the wrong bytes.
    for rel in TESTFILES:
        shutil.copy2(REPO / rel, scratch / rel)


def run_tests(scratch, py):
    """(rc, summary_line, [failed test ids]).

    The failure NAMES matter, not just the count: a mutant that kills two tests
    might be killing the pin it targets plus its control (good), or two
    unrelated tests while the pin stays green (which is the gate2 B2 shape
    wearing a KILLED label). Reporting the ids is what lets a reader tell those
    apart without re-running anything.
    """
    r = sh(f"py -{py} -m pytest {' '.join(TESTFILES)} -q", cwd=scratch)
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

    if not text_roundtrip_is_byte_exact(target, floor):
        print("TEXT ROUND-TRIP IS NOT BYTE-EXACT on this platform/checkout -- "
              "every patch below would grade bytes that were never HEAD's. "
              "ABORT (see `text_roundtrip_is_byte_exact`).")
        return 5
    print(f"text round-trip byte-exact : True")

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
