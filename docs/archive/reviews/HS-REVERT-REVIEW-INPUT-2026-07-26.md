# REVIEW-INPUT — `hs-revert`: R1 executed on `fix/handoff-seams`

Branch `fix/handoff-seams`, worktree `C:\proga\fleet-handoff-seams`, base `a9d2c64`.
Executing `docs/AUTONOMOUS-2026-07-26.md` §R1 (4–0: delete the un-supersede, then merge),
framed per c2 as a **revert of `cb9f078`'s self-contained code hunk**, not a third fix wave.

Nothing was pushed. No merge into `main`. No `sup-*` verb was run, no daemon touched, no
other worktree read or written, `supervisor/GOALS.md` and `docs/OPERATOR-GATES.md`
untouched. `_supervisor_gate` and the B6 surface were not opened (`gate-arm` owns them).

---

## 1. What changed

### Edit 1 — the revert (`_drop_pending_marker`, inside `cmd_sup_handoff_begin`)

| file:line | change |
|---|---|
| `bin/fleet.py:11726-11731` | the un-supersede loop and the `or restored` write condition are **gone**; the body is back to `if entry is not None: drop_handoff_entry(...); write_incarnation(...)` |
| `bin/fleet.py:11706-11719` | the R9 paragraph is replaced by one that records *why the un-supersede is gone* — it named the reverted commit, so leaving it would have left a docstring arguing for code that no longer exists |

Exactly the hunk `cb9f078` added to this function, in reverse. Nothing else in
`cmd_sup_handoff_begin` moved.

**KEPT, as ordered:** `cb9f078`'s successor task-file paragraph at `bin/fleet.py:11487-11490`
("IF THAT COMMAND REFUSES … HANDOFF-ORPHAN"). It is the honesty surface, and after this
revert it is *more* load-bearing, not less: it is now the text a superseded body reads on the
path this wave restores. It does not appear in the diff.

### Edit 2 — `--force` consults `_entry_age_seconds` (fail-closed narrowing)

| file:line | change |
|---|---|
| `bin/fleet.py:9525-9526` | `if force:` → `unageable = _entry_age_seconds(entry, "minted_at", now=now) is None` / `if force and unageable:` |
| `bin/fleet.py:9536-9543` | arm 4's refusal gains a declined-`--force` clause: on a readable entry it says `--force does not apply here` and why |
| `bin/fleet.py:12090-12092` | `--retire-all`'s predicate: `or force` → `or (force and _entry_age_seconds(entry, "minted_at", now=now) is None)` |
| `bin/fleet.py:12102-12107` | `--retire-all`'s "nothing to retire" recipe no longer advertises `--force` as a way out of the join window |
| `bin/fleet.py:9449-9458` | `resolve_handoff_abort` arm-4 docstring: the predicate is stated as EVALUATED, with the MAJOR-2 history |
| `bin/fleet.py:12059-12063` | `_cmd_sup_handoff_retire_all` docstring: "and ONLY those" |
| `bin/fleet.py:12804-12807` | `--force` argparse help: "…and is DECLINED on an entry whose minted_at reads fine" |

The code now matches the surfaces that documented it. `skills/fleet/supervisor.md:169`
already said "one whose `minted_at` cannot be read" and needed no edit — it was correct
about code that was not.

**On the report's original claim.** Confirmed as c4 found it: the **journal row is honest**.
`supervisor_journal_append` on this path writes `retire-all: retired N pending successor(s)
… NO session was stopped` — no age predicate is asserted there. Only the printed reason
(`bin/fleet.py:12232-12233`, `"--force: it recorded no sid and could not be aged"`) claimed a
predicate the code never evaluated. That string is unchanged and is now **true**, because the
predicate under it is finally checked. The journal was not chased.

### Edit 3 — `docs/specs/claim-nonce.md` §6.4 A1: re-read, not edited

**Not edited.** Zero doc files are in this diff. See §5 for what re-reading it actually
established, including the part that does not fully confirm.

### Tests

| file:line | change |
|---|---|
| `tests/test_handoff_seams.py` (deleted) | `TestASupersessionIsUndoneWhenItsAttemptNeverLaunched`, both methods |
| `tests/test_handoff_seams.py:1686-1766` | new `TestEveryAdmittedBodyReachesATerminalState` (2 tests) |
| `tests/test_handoff_seams.py:1769-1817` | new `TestForceConsultsTheAgeItClaimsToHaveConsulted` (3 tests) |

---

## 2. Deleted tests, justified by name

Both belong to the class `cb9f078` added for the hunk being reverted, and they are the only
two tests in the repo that assert the *un*-supersede. `grep -rn "superseded_by" tests/` has
three other hits (`tests/test_handoff_seams.py:1025,1027,1081`), all three inside
`TestAtMostOneBootableSuccessor` and all three asserting supersession being *laid* —
untouched by this wave and still green.

1. **`test_a_failed_begin_leaves_the_previous_attempt_bootable`** — deleted because it asserts
   the exact behaviour the council ruled out, and because *its name is the tell the ruling
   turns on*. "Bootable" is a precondition nobody wants for its own sake. It asserted
   `handoff_boot_refusal(...) is None` and `_boot_successor(...) == 0` and stopped there —
   one verb short of the verb that decides whether the body it admitted is worth anything.
   Driving one more verb (`sup-handoff-complete`) shows that body refused under every input.
   Its replacement, `test_a_dispatch_failure_admits_no_body_it_cannot_terminate`, drives the
   full sequence and asserts the terminal outcome instead.

2. **`test_a_THIRD_attempts_supersession_is_not_undone`** — deleted because it is a scoping
   test *for* the un-supersede loop (it asserts the loop lifts only marks keyed to its own
   `superseded_by`). With no loop there is nothing to scope. Its underlying invariant —
   a third attempt's supersession stands — is unchanged and still covered by
   `TestAtMostOneBootableSuccessor` (`tests/test_handoff_seams.py:1025-1027`), which asserts
   the `superseded_by` chain across three begins.

**Coverage is not reduced.** The DISPATCH-FAILED path retains a test that its own entry and
plaintext token are retired (`test_the_dead_attempts_own_entry_and_token_file_are_gone`),
which is the half of `_drop_pending_marker` the revert keeps, and which the deleted pair
never asserted.

---

## 3. RED → GREEN

New assertions, run **before** any source edit (both old classes still present):

```
$ py -3.13 -m pytest -q tests/test_handoff_seams.py -k "TestEveryAdmittedBodyReachesATerminalState or TestForceConsultsTheAgeItClaimsToHaveConsulted"
FAILED …::TestEveryAdmittedBodyReachesATerminalState::test_a_dispatch_failure_admits_no_body_it_cannot_terminate
    AssertionError: inc-20260726T175958Z-f75b booted -- a body was admitted that no verb can complete
    assert 0 == 5   +  where 5 = fleet.SUPERVISOR_BOOT_HANDOFF_REFUSED_RC
FAILED …::TestForceConsultsTheAgeItClaimsToHaveConsulted::test_force_is_refused_on_an_entry_that_can_be_aged
    Failed: DID NOT RAISE FleetCliError
FAILED …::TestForceConsultsTheAgeItClaimsToHaveConsulted::test_retire_all_force_leaves_an_ageable_joining_entry_standing
    Failed: DID NOT RAISE FleetCliError
3 failed, 2 passed, 104 deselected in 3.20s
```

The RED run also printed the MAJOR-2 defect live, on a **readable** `minted_at`:

```
stale successor inc-20260726T175959Z-acbe retired: NO session was stopped -- --force: it
recorded no sid and could not be aged, so no verb would ever have retired it (rs-MIN-B).
Its task file and handoff token are gone.
```

The two that passed RED are guards, not new behaviour, and are labelled as such in the source:
`test_the_dead_attempts_own_entry_and_token_file_are_gone` (the half of the function the revert
keeps) and `test_retire_all_force_still_takes_the_unageable_entry` (positive control that the
narrowing does not reach the one shape `--force` was built for). Both are killed by mutants
M1 and M5 respectively — they are load-bearing, just not RED-before.

GREEN after both edits:

```
$ py -3.13 -m pytest -q tests/test_handoff_seams.py
107 passed in 8.22s
```

---

## 4. Both floors, and the delta

| run | result |
|---|---|
| `py -3.13 -m pytest -q` — **branch baseline at `a9d2c64`** | `2142 passed, 8 skipped in 107.57s` |
| `py -3.10 -m pytest -q` — **branch baseline at `a9d2c64`** | `2142 passed, 8 skipped in 107.66s` |
| `py -3.13 -m pytest -q` — **this wave** | `2145 passed, 8 skipped in 100.49s` |
| `py -3.10 -m pytest -q` — **this wave** | `2145 passed, 8 skipped in 111.18s` |

Delta **+3 = −2 deleted +5 added**, identical on both floors, with **zero** other failures.
That is c2's measurement reproduced exactly: the revert removes precisely the two tests it
deletes and produces no collateral failure anywhere in the suite.

**The brief's stated baseline of 2152/11 is `main`'s, not this branch's, and I could not
reconcile it from here without touching `main`.** This branch is behind `main`
(`fleet-handoff-seams a9d2c64` vs `claude-fleet 6b748fd [main]` in `git worktree list`), and
other workers have landed on `main` since this branch forked, so `main` carries tests this
branch does not. Every number above is measured on this branch, before and after, on both
floors — which is the comparison that isolates this wave. A reviewer wanting the `main`
comparison should re-baseline after the merge, not against these.

`py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md`:

```
SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.
EXTRACTION SELF-TEST PASSED: a receipt that stops being parsed is reported, not silently dropped.
WARN  line 1357 [pinned @ 091d5fa]: ls -ld ~/.claude/projects && find ~/.claude/projects -maxdepth 2 -name '*.jsonl' | wc -l
      EXPECTED: 'drwxr-xr-x 1 Techn 197609 0 Jul 21 20:54 /c/Users/Techn/.claude/projects'
      ACTUAL:   'drwxr-xr-x 1 Techn 197609 0 Jul 26 23:05 /c/Users/Techn/.claude/projects'
parsed receipts: 58/59 reproduce exactly (55 fenced blocks, 0 unclassified, 0 volatile-skipped)
VERDICT:         pass -- 0 failure(s), 1 warning(s)
```

The one warning is the mtime of `~/.claude/projects`, a directory outside this repo that this
wave does not touch. It is pre-existing drift in a receipt whose subject is "there is no
authorization input on this box", and it is a WARN, not a failure.

---

## 5. Edit 3 re-read: what A1 actually says now, and the part that is NOT confirmed

**Confirmed.** The clause `cb9f078` falsified is A1's last paragraph:

> Only `begin` writes it, and only for its newest attempt, so it belongs to whichever attempt
> is still outstanding: as shipped, `drop_handoff_entry` drops the entry, and when it was the
> LAST entry it drops `handoff_token_hash` too.

Under `cb9f078` a reader following that sentence would conclude the resurrected attempt could
complete. It could not: the failed `begin` had already overwritten `handoff_token_hash` with
the *dead* attempt's, and the doc pointed at a **bootable** body whose token verified against
nothing. That is the falsification, and it is gone — the body is no longer bootable.

Measured, on the reverted code, with a throwaway probe (added under `tests/`, run, deleted;
`git status --porcelain` shows no residue of it):

```
outstanding: ['inc-20260726T180532Z-c360']
hash==sha(tok1): False
hash changed by the failed begin: True
boot refusal for attempt 1: inc-…-c360 was SUPERSEDED by inc-…-a216:
abort rc: 0
hash present after last retire: False
```

Line 6 is A1's operative claim, verified true: retiring the LAST entry takes
`handoff_token_hash` with it, which is where the live credential dies.

**NOT confirmed, and I am flagging it rather than reporting a clean pass.** Line 2 shows the
hash is still not `sha(tok1)` while attempt 1 is the only outstanding entry — so A1's phrase
"it belongs to whichever attempt is still outstanding" is *still not literally exact* after
this revert. What changed is that the mismatch is now **inert**: the only outstanding attempt
is SUPERSEDED, so `sup-boot` refuses it before any token is examined, and no body can present
`tok1` to any verb. No reader can be led into a wrong action by the sentence.

This is exactly the residue the ruling names and declines to close — a single-valued
`handoff_token_hash` under a *set* of attempts, wave-1 shape, operator-owned as **A3**. It is
reachable without `cb9f078` at all. I did not close it, per the brief.

So: A1 stops being falsified in the sense that matters (nothing validates, nothing boots, the
credential dies with the last entry), and remains imprecise in a way that is bounded by A3.
**A reviewer who wants "A1 is now true, full stop" will not get it from me.**

---

## 6. Mutation ratio — 7 / 7 killed

Harness: each mutant's anchor must appear **exactly once** in the golden file or it is
reported NOT-APPLIED (a mutant that did not apply proves nothing). Applied to a saved golden
copy, run against `tests/test_handoff_seams.py`, restored from the same golden after each.

| # | mutant | verdict | first test to fall |
|---|---|---|---|
| M1 | un-supersede loop restored (the reverted hunk, put back) | **RED** | `test_a_dispatch_failure_admits_no_body_it_cannot_terminate` |
| M2 | `if force and unageable:` → `if force:` (the MAJOR-2 bug, put back) | **RED** | `test_force_is_refused_on_an_entry_that_can_be_aged` |
| M3 | `if force and unageable:` → `if unageable:` (operator opt-in dropped) | **RED** | `test_without_force_it_is_refused_and_the_refusal_names_force` |
| M4 | `--retire-all` predicate → `or force` | **RED** | `test_retire_all_force_leaves_an_ageable_joining_entry_standing` |
| M5 | `--retire-all` age predicate inverted (`is None` → `is not None`) | **RED** | `test_retire_all_force_leaves_an_ageable_joining_entry_standing` |
| M6 | declined `--force` says nothing about being declined | **RED** | `test_force_is_refused_on_an_entry_that_can_be_aged` |
| M7 | `resolve_handoff_abort` age predicate inverted | **RED** | `test_without_force_it_is_refused_and_the_refusal_names_force` |

**Ratio: 7/7 killed, 0 survivors.** M1 is the important one: it proves the new gate is RED
against the exact code this wave removes, which is what the deleted pair could never do.

Restore integrity after the run:

```
$ cmp bin/fleet.py "$CLAUDE_JOB_DIR/tmp/fleet.golden.py" && echo "RESTORED: byte-identical to pre-mutation"
RESTORED: byte-identical to pre-mutation
$ git status --porcelain
 M bin/fleet.py
 M tests/test_handoff_seams.py
```

**The brief asked for `git status --porcelain` empty after each restore, and it is not — it
cannot be.** This wave itself modifies both files, so an empty porcelain would mean the
restore had thrown away my own changes. `cmp` against the golden copy is the check that
actually proves "no mutant residue", and it is byte-exact. Read the porcelain above as the
wave's own two files and nothing else: no `.orig`, no probe file, no stray scratch.

---

## 7. Push back on this

Six things a reviewer should attack. The first two are places I think the brief is wrong or
under-specified; the rest are mine.

1. **Edit 2 adds a predicate, and the brief forbids adding predicates.** The brief's framing
   section says "deleting code is the one change shape that cannot mint a defect… **Keep it
   that shape.** If you find yourself adding a predicate, stop and report instead" — and then
   scope item 2 orders me to add exactly one predicate. I read the fence as scoped to edit 1
   (keep the *revert* revert-shaped) and item 2 as the sanctioned exception, and I built it
   anyway. **If a reviewer reads that fence as absolute, edit 2 should be split into its own
   wave and this branch should ship edit 1 alone.** Everything in edit 2 is contiguous and
   separable; nothing in edit 1 depends on it. Attack this first — it is the one place I
   resolved an instruction conflict by judgement rather than by asking.

2. **The declined-`--force` message and the `--retire-all` recipe rewrite are mine, not the
   brief's.** The brief said "fix the printed reason and the predicate", and strictly the
   printed reason needed no edit — narrowing the predicate makes the existing string true. I
   went further because a fail-closed narrowing that says nothing reads to the operator as a
   broken flag: they pass `--force`, get the same refusal they got without it, and have no
   way to learn why. But that is four surfaces of new prose in a wave whose whole licence is
   "deleting code cannot mint a defect", and prose is where MAJOR-2 came from in the first
   place. A reviewer could reasonably cut the new clause at `bin/fleet.py:9540-9542` and the
   recipe rewrite at `12102-12107` and keep only the two predicate changes.

3. **The refusal string is now a nested conditional expression three branches deep**
   (`bin/fleet.py:9536-9543`): `unageable → …` / `force → …` / `""`. It is correct and M6
   kills the mutant that guts it, but it is dense, and the fourth reader of it will not enjoy
   it. If a reviewer wants it unrolled into an `if/elif` before the `return`, that is a fair
   ask and costs nothing.

4. **`test_a_dispatch_failure_admits_no_body_it_cannot_terminate` asserts
   `recorded == [first]` before it loops.** That pins the *count* of surviving entries, so a
   future change that legitimately leaves two attempts recorded fails this test for the wrong
   reason. I chose it deliberately — a loop over an empty list passes vacuously, and "drive
   every attempt" must not be satisfiable by recording none — but a reviewer may prefer
   `assert recorded` plus a separate membership assertion. It is the one assertion in the new
   class that is stricter than the rule it encodes.

5. **I did not test the DOA and INDETERMINATE returns against the reverted function.** The
   revert only touches DISPATCH-FAILED, and `_drop_pending_marker` is not called on the other
   two, so nothing changed for them — but "nothing changed" is my reading of the call sites,
   not something I drove. `TestMarkerLifecycle` covers those paths and stayed green, which is
   evidence, not proof.

6. **This branch is behind `main` and I never merged or rebased it, so nothing here has been
   run against the code it will merge into.** `gate-arm` is concurrently changing
   `_supervisor_gate` and B6 on `main`; my scope does not overlap, but "does not overlap" is
   a claim about function boundaries, not a test result. The +3 delta is honest about *this
   branch*; the number after a merge is unmeasured and I was fenced from producing it.

---

## 8. What was deliberately left alone

- The **root** — a single-valued `handoff_token_hash` under a set of attempts. Wave-1 shape,
  outside this delta, operator-owned as **A3**. Named in §5 above with a measurement.
- **`docs/SPEC.md:334`** — its `§6.1` is a correct self-reference. Not touched; not
  re-litigated.
- **`_supervisor_gate` / B6** — `gate-arm`'s. Not opened.
- **`state/tasks/hs-revert.md`** — never authored (§G-K: `fleet spawn` silently overwrites
  it). All scratch went to `$CLAUDE_JOB_DIR/tmp`.
