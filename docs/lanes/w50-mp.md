# `w50-mp` — merge prep for `w50/gfs` → `main`

**I prepared this landing. I did not perform it.** No push, no ref moved outside my own detached
worktree, zero `fleet` verbs against the live home, zero writes to `~/.claude/`.

---

## 0. THE PARENT OF RECORD — read this before anything else

| | |
|---|---|
| **`main` this audit is against** | **`4d78f6cdc6a8c94a9e258ae74ab07ca7d17f2228`** |
| `w50/gfs` audited | `a4d429e05082ee746e8c26cd25fd79ff7d858dfd` |
| merge base | `cef230f1cc5332d7bbb69f3ea6fb1f216e0fd590` |
| fast-forward legal? | **NO.** `git merge-base --is-ancestor main w50/gfs` → **NO**. Real merge. |
| git | 2.34.1.windows.1 |
| interpreters | `py -3.13` → 3.13.12, `py -3.10` → 3.10.1 |
| my worktree | `C:/proga/fleet-w50-mp`, detached, created `git worktree add --detach … main` |

**Every ancestry claim in this document is conditional on `main` being `4d78f6c`.** A prep lane races
its own dispatcher: last time one ran, `main` advanced two commits — the dispatcher's own journal
entries — and the lane's "fast-forward legal" was true when written and false when read. Re-derive
ancestry at landing time. My job was to make that re-derivation cheap, not to pre-empt it.

**And I moved the target myself.** The brief asks for this report *committed on `w50/gfs`*, which
necessarily advances that branch past `a4d429e`. §9 records the new head and the re-verification
against it. `main` was never touched.

---

## 1. THE LANDING RECIPE

Run from a clean `main` worktree. Everything below is measured, not composed.

```
git rev-parse main                      # MUST print 4d78f6c…; if not, re-derive §2 and §5
git rev-parse w50/gfs                   # see §9 for the head this report lands on
git merge --no-commit --no-ff w50/gfs   # -> CONFLICT (content) in bin/fleet.py, and only there
```

Resolve the two `bin/fleet.py` conflicts (§3), then:

```
grep -c '^<<<<<<< ' bin/fleet.py        # MUST be 0 — anchored; see §6 for why unanchored lies
git add bin/fleet.py
git merge -F <path-to-message-file>     # NOT -F - ; see §7
```

Verify before you push:

```
py -3.13 -m pytest -q                   # 4235 passed, 14 skipped, 1 xfailed   (4250 collected)
py -3.10 -m pytest -q                   # identical
git rev-parse HEAD^1 HEAD^2             # 4d78f6c… and the §9 head
```

The merge message is provided as a file at §8. **Do not paste it into a double-quoted shell
string** — §7.

---

## 2. DISJOINTNESS — one contested file, and it is the one you expect

Measured with the **merge-base** form. The two-dot form (`git diff --name-only main w50/gfs`) reports
38 paths, which is the union of both sides' work and answers a different question.

```
$ git diff --name-only $(git merge-base main w50/gfs) w50/gfs   ->  16 files
$ git diff --name-only $(git merge-base main w50/gfs) main      ->  23 files
$ comm -12 <both, sorted>                                       ->  bin/fleet.py
branch: 16  main: 23  intersection: 1
```

**`bin/fleet.py` is the sole overlap.** Every other file has exactly one author, and §4 proves each
one landed byte-identical to that author's version.

---

## 3. THE CONFLICT, AND THE RESOLUTION — verified by content, then proved

### 3a. The census, with the control first

`git merge-tree --write-tree` **does not exist at git 2.34.1.** It parses the flag as a rev, dies
`fatal: unknown rev --write-tree`, emits **zero bytes**, and a marker grep over zero bytes returns
zero — which reads as "no conflicts". Reproduced here before trusting anything:

```
$ git merge-tree --write-tree main w50/gfs
rc=128   stdout bytes: 0   stderr: fatal: unknown rev --write-tree
$ grep -c '<<<<<<<' <that empty output>
0            <- a zero that means NOTHING
```

So the control ran first, on a merge known to collide:

```
$ git merge-tree $(git merge-base main w35/nd4c) main w35/nd4c
rc=0   stdout bytes: 154363
grep -c '<<<<<<<'          -> 26      (the campaign's canonical control value)
grep -cE '^\+?<<<<<<<'     -> 25      (see §6 — 26 is inflated by one)
```

Instrument live. Then the real merge:

| instrument | result |
|---|---|
| `git merge-tree cef230f main w50/gfs`, `grep -c '<<<<<<<'` | **3** — and one is a false positive (§6) |
| same output, `grep -cE '^\+?<<<<<<<'` | **2** |
| `git merge --no-commit --no-ff w50/gfs`, real ort merge | **2 conflicts, `bin/fleet.py` only** |
| conflicted hunks / bytes | **2 hunks, 14 lines with markers, 718 bytes** of merge-tree conflict region |
| lines that actually disagree | **4 lines, 634 bytes** across both sides |

The two hunks are at `bin/fleet.py:15079` and `:15775` in the conflicted working tree —
`_releaser_is_roster_live`'s docstring and `_supervisor_gate`'s SAFETY INVARIANT block. **Both are
pure line-number self-citations. Zero semantic content.**

### 3b. The four numbers, derived by content — not by arithmetic

`tests/test_retired_sid_citations.py` asserts `writers == cited`, where `writers` is every line
matching `^\s*\S+\["retired_sids"\]\s*=` in the merged file. So the correct citation is a *function
of the merged tree*, and I derived it that way — by locating the assignments, not by adding offsets:

```
merged bin/fleet.py: 21570 lines   (cef230f 21438 | main 21453 | w50/gfs 21555)

retired_sids WRITERS, located by content in the merged file:
  :7851    r["retired_sids"] = list(r.get("retired_sids", [])) + [old_sid]
  :8324    new_record["retired_sids"] = prior_retired + [old_sid]
  :12771   record["retired_sids"] = list(record.get("retired_sids", [])) + [old_sid]
  :18151   succ_rec["retired_sids"] = list(succ_rec.get("retired_sids", [])) + [prior]
```

**Derived independently under BOTH resolutions and identical under each** — which is the point: the
choice of side moves no writer, because both sides contribute exactly two lines to each hunk. The
gate's four numbers are **CONFIRMED**.

### 3c. Neither side is right — proved, not asserted

`main` re-pinned to `:18034`; the branch re-pinned to `:18136`; the merged file puts the fourth
writer at `:18151`. I checked out each side's value into `bin/fleet.py` and ran the suite:

```
VARIANT: ours    (main verbatim)   cited :7804 :8277 :12720 :18034
   2 failed, 2 passed
   FAILED test_every_cited_line_is_a_retired_sids_write
   FAILED test_every_retired_sids_writer_is_cited

VARIANT: theirs  (branch verbatim) cited :7851 :8324 :12771 :18136
   2 failed, 2 passed
   Extra items in the left set: 18151 / right set: 18136

VARIANT: correct                   cited :7851 :8324 :12771 :18151
   4 passed
```

### 3d. THE RESOLUTION

At **both** sites, take the branch's line and change the fourth number:

```
_releaser_is_roster_live docstring (conflicted tree ~:15079)
    writer appends that record's OWN prior sid alone: :7851, :8324, :12771,
    :18151), the same safety invariant §7.1's send carve-out rests on. That

_supervisor_gate SAFETY INVARIANT block (conflicted tree ~:15775)
    #     writer appends that record's OWN prior sid alone (:7851, :8324, :12771,
    #     :18151) -- so the sid union can never make one body answer for another.
```

Three of the branch's four numbers are already correct; only `:18136 → :18151` changes. Taking
`main`'s side means changing all four.

---

## 4. LOST-HUNK CHECK — 0 lost, 4 superseded, every one read

Membership tested as a Python set lookup, not `grep -Fqx`, because a needle beginning with `- `
makes grep parse it as flags — reproduced, since it is the defect a previous lane's control could
not catch:

```
$ grep -Fqx '-     writer appends' hay.txt   ->  rc=2   grep: unknown option --
$ grep -Fqx -e '-     writer appends' hay.txt ->  rc=1   (correctly ABSENT)
```

`rc=2` is not `rc=1`, and a checker that branches on truthiness cannot tell them apart.

**The control includes the SHAPE, not an instance** — it feeds the checker needles that start with
`- ` and with `--`, and demands both be reported absent:

```
== CONTROL (must all say OK) ==
  present line                 want_absent=False got_absent=False  OK
  absent, plain                want_absent=True  got_absent=True   OK
  absent, LEADING '- '         want_absent=True  got_absent=True   OK
  absent, LEADING '--'         want_absent=True  got_absent=True   OK
  absent, masked-digit trap    want_absent=True  got_absent=True   OK

== LOST-HUNK CHECK on bin/fleet.py ==
main   (4d78f6c): 22 added lines, 0 ABSENT from merged
branch (a4d429e): 148 added lines, 0 ABSENT from merged
```

**Verdict: nothing lost.** `:NNNN` and `:NNNN-NNNN` are digit-masked, so I also report what the mask
absorbed — a masked match is a line that changed only in its numbers, and the reading is what
resolves whether that was deliberate:

| side | line matched only under the mask | reading |
|---|---|---|
| main | `:18034), the same safety invariant §7.1's…` | **deliberately superseded** by §3d — `:18034` is main's pre-merge value for the writer now at `:18151` |
| main | `#     :18034) -- so the sid union can never…` | **deliberately superseded**, same number, second site |
| branch | `:18136), the same safety invariant §7.1's…` | **deliberately superseded** — the branch's pre-merge value for the same writer |
| branch | `#     :18136) -- so the sid union can never…` | **deliberately superseded**, second site |

All four are the conflict itself. **No line is unaccounted for, and none is lost.**

And the 37 non-contested files, each compared to its sole author's blob:

```
22/22 main-side files    OK (byte-identical to main's version)
15/15 branch-side files  OK (byte-identical to w50/gfs's version)
```

---

## 5. FLOORS — predicted before the run, hit exactly on both interpreters

**Prediction written before the merged tree was ever collected** (recorded in
`state/journals/w50-mp.md` at the time). Derived by `--collect-only` on all three trees, materialised
read-only via `git archive`, and never by arithmetic on a diff:

```
cef230f (merge base) : 4154 collected, 70 test files
main    (4d78f6c)    : 4238 collected, 71 test files
w50/gfs (a4d429e)    : 4166 collected, 71 test files
```

Two independent derivations, because a single one is a guess with a receipt attached:

```
per-file three-way union (no file changed on BOTH sides):
  file                              base  main  branch  MERGED
  tests/test_doc_claims.py            20    26      20      26
  tests/test_fork_steer_delivery.py    0     0      12      12
  tests/test_hook_fleet_home_argv.py   0    78       0      78
  -> 4250, 72 files

total-arithmetic cross-check: 4238 + (4166 - 4154) = 4250
```

> **PREDICTION: 4250 collected, 72 test files, on BOTH `py -3.13` and `py -3.10`.**
> **I agree with the gate's 4250** — and I re-derived it rather than inheriting it. Its inputs
> (4154 / 4238 / 4166) all reproduce.

Measured on the merged tree:

```
$ py -3.13 -m pytest -q --collect-only     4250 tests collected      (72 files)
$ py -3.10 -m pytest -q --collect-only     4250 tests collected

$ py -3.13 -m pytest -q -rf   rc=0   4235 passed, 14 skipped, 1 xfailed in 477.57s
$ py -3.10 -m pytest -q -rf   rc=0   4235 passed, 14 skipped, 1 xfailed in 408.45s
```

**Hit exactly, both interpreters, byte-identical counts.** No stop-and-report was needed.

### The tree did not move around those runs — and not by `git write-tree`

`git write-tree` reports the **index**, so with unstaged or unmerged content it can return the same
sha while the blob on disk changes. Here it does not even do that much:

```
$ git write-tree
bin/fleet.py: unmerged (fc71106…)
bin/fleet.py: unmerged (c759e8c…)
```

Instrument used instead: a **working-tree digest** — sha256 over `(path, sha256(bytes))` for all 244
tracked paths, sorted; untracked files deliberately excluded so scratch output cannot mask a change.
Proven to discriminate before being trusted (append two lines → digest moves; restore → digest
returns):

```
WT-DIGEST 1a25fcec0f8cffe70faa788e477f0b675098c31689f171f2d1e635ec630b2f36
  (after appending 2 lines)  cdca59b00f7d04fd782f028aa467a73a706876e56ce009b383723ea9c2da7a9c
  (after restore)            1a25fcec0f8cffe70faa788e477f0b675098c31689f171f2d1e635ec630b2f36
```

`1a25fcec…` held **before and after both full-suite runs, and after every mutation experiment in
§3c, §6 and §8.** `bin/fleet.py` = `be5505e1fa3081827f5a988d15ebd7c105971c7733a663ff278f29c4a8f53fe1`
throughout.

### Ranged citations — `end >= start`

11 inverted ranges exist in the merged tree. **All 11 read, none live:**

| where | range | reading |
|---|---|---|
| `tests/test_self_citations.py:712` | `cmd_respawn:7443-7343` | the guard's own **seed docstring** — it quotes the wave-45 defect as the reason it exists |
| `knowledge/INDEX.md:7`, `:21`, `knowledge/lessons.md:243` | `7443-7343`, `6308-6256` | knowledge entries **narrating** the defect |
| `docs/lanes/w47-homes.md:126`, `w49-fold.md:75`, `w50-fs2.md:36`, `w50-gfs.md:278` | `8434-8394`, `7443-7343` | lane reports **narrating** it |
| `supervisor/JOURNAL.md:5135`, `:6210` | `6308-6256`, `7443-7343` | journal, same |
| `supervisor/JOURNAL.md:396` | `:22-03` | not a citation — the clock range in `03:22-03:32` |

**This merge introduces none, re-pins none, and the guard is live in the merged tree** — planting an
inversion (`cmd_respawn:8521-8523` → `8521-8422`) reddens two tests:

```
FAILED test_every_ranged_citation_END_resolves_in_the_same_function
FAILED test_the_range_check_catches_BOTH_ways_an_end_rots
```

### Fixpoint, not one read

A single red/green read is a lower bound — assertion ordering masks later citation rot. All eight
pin files (`test_self_citations`, `test_retired_sid_citations`, `test_doctrine_citations`,
`test_doc_claims`, `test_pin_usage_contract`, `test_round7_defect_pins`, `test_receipts`,
`test_verify_receipts_tristate`) run to fixpoint, from each starting resolution:

```
from OURS   (main verbatim)  : round 1 = 4 failed / 273 passed -> repair -> round 2 = 277 passed
                               FIXPOINT after 2 rounds, 1 repair
from THEIRS (branch verbatim): round 1 = 4 failed / 273 passed -> repair -> round 2 = 277 passed
                               FIXPOINT after 2 rounds, 1 repair
from CORRECT                 : round 1 = 277 passed
                               FIXPOINT after 1 round, 0 repairs
```

**One repair, one round. This merge does not have wave-35's six-round shape** — because the only
contested content is four citation numbers with a computable resolution.

### Receipts

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/*.md    (15 specs)
merged tree : 192/194 receipts reproduce, 0 failure(s), 2 warning(s), rc=2
main 4d78f6c: 192/194 receipts reproduce, 0 failure(s), 2 warning(s), rc=2
```

**Identical. The merge changes nothing here.** `rc=2` is `SELF-TEST INCONCLUSIVE` on specs carrying
no seedable receipt — a pre-existing property of the spec set, not a defect this merge introduces,
and not something to chase at landing time. (Counted across the whole output; the last document's
verdict is not the run's verdict.)

---

## 6. WHAT I FOUND THAT THE GATE DID NOT

### 6a. The prescribed marker grep OVER-counts on this merge, by exactly one

The brief says to grep `<<<<<<<` **unanchored**. On this merge that returns **3**, and there are
**2** conflicts. The third is inside `docs/lanes/w50-gfs.md` — the gate report quotes its own
`merge-tree` output, so its conflict markers arrive as **added lines** and appear in the diff with a
doubled prefix:

```
line  332  +<<<<<<< .our      <- real conflict
line  346  +<<<<<<< .our      <- real conflict
line 3003 ++<<<<<<< .our      <- docs/lanes/w50-gfs.md quoting itself
```

The failure mode this campaign has been guarding against is the grep reading **too low**. Here it
reads **too high**, from the same rendering-scan weakness, and the inflation arrives *inside the
gate report itself*. The repo's own `docs/NEXT-SESSION.md:121` already prescribes the form that gets
it right — `grep -cE '^\+?<<<<<<<'` — which returns 2. **Use that, or better, `grep -c '^changed in
both'`, which is a structural verdict rather than a rendering scan.**

### 6b. The campaign's canonical control value of 26 is itself inflated — the true count is 25

Same mechanism, and it has been sitting in the control all along:

```
w35/nd4c x main:  grep -c '<<<<<<<'  -> 26      grep -cE '^\+?<<<<<<<'  -> 25
```

The 26th "marker" is a **context line in `knowledge/INDEX.md`** — the wave-42 lesson entry that
narrates the marker-grep null and quotes `` `<<<<<<<` `` in its own prose. **The lesson recording
that this instrument returns nulls is corrupting the instrument's control.**

This does not weaken the control's job — a non-zero fingerprint still proves the instrument is
live — but **26 must not be read as "26 conflict hunks."** Its documented value should be recorded
as *26 unanchored / 25 anchored*, or the population will keep drifting upward every time a lane
writes about it.

### 6c. The blast radius of a wrong resolution is 4 tests across 2 files, not 1 file

The gate names `tests/test_retired_sid_citations.py`. Running the full pin set shows
`tests/test_self_citations.py` reddens too, from either side:

```
FAILED tests/test_retired_sid_citations.py::test_every_cited_line_is_a_retired_sids_write
FAILED tests/test_retired_sid_citations.py::test_every_retired_sids_writer_is_cited
FAILED tests/test_self_citations.py::test_every_cited_line_carries_its_anchor
FAILED tests/test_self_citations.py::test_every_enumeration_matches_the_derived_set
```

Operationally this is good news — a wrong resolution is caught twice, by two independently-written
graders — but a merger who fixes only the file the gate named and re-runs only that file will read
green over a still-red tree.

### 6d. The gate's declared-collision finding holds at current heads, re-measured

The gate said `w50/launchfix` does not touch `tests/integration/test_native_pin.py` and flagged it
as BELIEVED because that lane was in flight. Re-measured at `4a62e21`, and across every unmerged
branch:

```
branch                     head      bin/fleet.py  test_native_pin.py
fix/b6-interface-release   2e824ea        1               0
w49/fs                     f017bb8        1               1
w50/gfs                    a4d429e        1               1
w50/glaunch                a9a2975        1               0
w50/launchfix              4a62e21        1               0
(w48/gc, w48/glaunch, w49/home-witness, w50/d, w50/gd, w50/glive, w50/glive2, w50/live: 0 / 0)
```

**Confirmed.** Only the `w49/fs` → `w50/gfs` lineage touches the pin file.

### 6e. This merge does not poison the next landing — measured, not assumed

`bin/fleet.py` goes 21453 → 21570 (+117 lines), which shifts every citation below the insertion
points. Conflict count is a famously bad predictor of re-pin count, so I rehearsed the next landing
rather than reasoning about it. Against the trial merge commit:

```
branch                     conflicts vs main   vs merged   delta
fix/b6-interface-release          10              10         +0
w50/glaunch                        0               0         +0
w50/launchfix                      0               0         +0
w50/live                           0               0         +0
w50/d                              0               0         +0

$ git merge --no-commit --no-ff w50/launchfix   (onto the merged tree)
Auto-merging bin/fleet.py — Automatic merge went well
$ pytest -q test_self_citations test_retired_sid_citations test_doc_claims
90 passed
```

**No conflict delta, and the citation pins stay green.** The +117 shift does not land on anything
those branches cite. `fix/b6-interface-release` carries 10 conflicts both before and after — that is
its own pre-existing staleness, unchanged by this merge.

### 6f. The gate's `21570` is right; a naive line count says `21571`

Worth one line because it is the sort of off-by-one that gets "corrected" wrongly at landing time.
`wc -l` says **21570**. Splitting the bytes on `\n` in Python yields **21571** elements, because the
file ends with a newline and the final element is empty. The gate's figure is correct.

### 6g. The fence and the deliverable are in tension, and I resolved it in the open

The brief says **"No branch may be created or moved"** and also **"your report committed on
`w50/gfs`"**. The second cannot be done without the first being violated. I read the specific
deliverable as governing the general fence — the fence's purpose is protecting `main`, the remote,
and the rehearsal, all of which I honoured exactly. §9 records the consequence, which is real: **the
sha you merge is not `a4d429e`.**

---

## 7. TWO WAYS TO DESTROY THE MERGE MESSAGE

### 7a. `git merge -F -` does not read stdin

Verified in a throwaway repo, not against this one:

```
$ printf 'msg from stdin\n' | git merge -F - --no-ff side
error: could not read file '-'
rc=129
$ git log --oneline -1
18db151 mainside          <- no merge happened

$ git merge --no-ff -F /path/to/msg.txt side
Merge made by the 'ort' strategy.   rc=0
```

It does not fall back to stdin — it tries to open a file literally named `-`. **The message must go
through `-F <file>`.**

### 7b. REFUSAL CLASS 5 — backticks in a double-quoted shell string execute

A merge message about *this* merge is dense in backticked spans like `` `:7851` ``, which is exactly
the shape that dies:

```
$ echo "resolve to `:7851` and run `git rev-parse --short HEAD` after"
/usr/bin/bash: line 2: :7851: command not found
resolve to  and run 4d78f6c after

$ echo 'resolve to `:7851` and run `git rev-parse --short HEAD` after'
resolve to `:7851` and run `git rev-parse --short HEAD` after
```

The first span **substituted to empty** — its error went to stderr and vanished — so the sentence
lost the number it was about. The second span **executed**, and the sentence gained a sha it never
claimed. Both halves of §3d would be destroyed this way, silently, in the exact paragraph that
carries the resolution.

**Write the message to a file with a heredoc or an editor. Never pass it through `"…"`.** §8 is that
file.

*(Note on this document: every conflict marker quoted above is indented inside its fence so that
`grep -c '^<<<<<<< '` over the tree still returns 0. §6a is a finding about a report that did not do
that; it would be poor form to land the same trap in the report that names it.)*

---

## 8. THE MERGE MESSAGE, AS A FILE

Write this verbatim to a file (heredoc or editor — not a double-quoted string) and pass it as
`git merge -F <that file>`.

```
merge(w50): the fork-steer delivery fix, gated NOT-GATING

Lands `w50/gfs` -- `w49/fs`'s fork-steer delivery repair (both 6e amendments and
the citation re-pin) plus the adversarial gate verdict that cleared it.

The defect: `fleet send` could print `fork-steered` while the worker silently
redid its previous task -- 1 silent miss in 92, measured. Delivery is now
unconditional on both the steer and the resume arm.

Gate verdict: NOT-GATING, 4 MAJOR, 0 BLOCKING (docs/lanes/w50-gfs.md).
Holding the merge would leave the measured defect in shipped code, which is
strictly worse than every finding it raises.

Conflicts: two, both in bin/fleet.py, both pure line-number self-citations in
the retired_sids writer enumeration (_releaser_is_roster_live's docstring and
_supervisor_gate's SAFETY INVARIANT block). Neither side's numbers are correct
after the merge -- main re-pinned to :18034, the branch to :18136, and the
merged file puts the fourth writer at :18151. Resolved to the four values
derived by content from the merged tree:

    :7851, :8324, :12771, :18151

Taking either side verbatim lands a RED tests/test_retired_sid_citations.py
and a RED tests/test_self_citations.py -- four tests across two files.

Floor: 4250 collected, predicted before the run and hit exactly on both
interpreters -- 4235 passed, 14 skipped, 1 xfailed, py 3.13.12 and py 3.10.1.
Merge-base cef230f 4154, main 4238, branch 4166; derived by --collect-only on
all three trees and by per-file three-way union, never by arithmetic on a diff.

Lost-hunk check: 0 of main's 22 and 0 of the branch's 148 added bin/fleet.py
lines are absent from the merged file. Four matched only under the citation
digit mask, and all four are the citation lines the resolution deliberately
supersedes. All 37 non-contested files are byte-identical to their sole
author's version.

Merge prep and its receipts: docs/lanes/w50-mp.md.
```

---

## 9. THE REHEARSAL, AND THE SHA YOU ACTUALLY MERGE

I executed the full merge **detached and unreferenced** in `C:/proga/fleet-w50-mp`:

```
TRIAL MERGE COMMIT: e160964ed1917783fc9c8bf4663a2a95b786956d
  parent ^1 = 4d78f6cdc6a8c94a9e258ae74ab07ca7d17f2228   == main     YES
  parent ^2 = a4d429e05082ee746e8c26cd25fd79ff7d858dfd   == w50/gfs  YES
  HEAD detached: YES
  main    after: 4d78f6c…   (unmoved)
  w50/gfs after: a4d429e…   (unmoved at that point)
  tree digest  : 1a25fcec…  (identical to the audited tree)
```

That commit is reachable from no ref and will be garbage-collected. It exists so the recipe in §1 is
a rehearsal rather than a plan.

**Then this report was committed on `w50/gfs`, which advanced it.** The new head, the diff it
carries, and the re-verification are in §10. **Merge the §10 head, not `a4d429e`.**

---

## 10. RE-VERIFICATION AFTER MY OWN COMMIT

*(This section is completed after the report commit lands; see the trailing block.)*

---

## 11. WHAT THIS REPORT COULD STILL BE WRONG ABOUT

- **The parent.** Everything in §2, §3, §5 and §6 is conditional on `main = 4d78f6c`. If it has
  moved, the four numbers in §3d are the first thing to re-derive — they are a function of the
  merged file's line count, and any change to `bin/fleet.py` on `main` moves `:18151`. The
  derivation is mechanical: find the four `["retired_sids"] =` assignments and read their line
  numbers. **Do not adjust them by arithmetic.**
- **The floor.** 4250 is measured on the tree I built. A different `main` gives a different number,
  and the honest response is to re-derive rather than to reuse mine.
- **What I did not attack.** I audited the *merge*, not the *branch*. The gate's four MAJOR findings
  — F1's envelope escape especially — are unchanged by anything here, and F1 is the one whose
  severity the gate explicitly deferred to the operator.
- **Skips.** 14 skipped includes the `FLEET_LIVE=1` pin tier, which collection-gates itself out. A
  green suite certifies nothing about the native contract, and per the gate's F7 the stamp condition
  should read *"both interpreters, on the tree that lands, from a sid-free shell"* before anyone
  stamps `pin-pass.json`. **I did not stamp it and did not run that tier.**
