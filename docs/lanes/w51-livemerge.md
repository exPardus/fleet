# `w51-livemerge` — merging `w50/live`, and paying the citation cost the merge creates

| | |
|---|---|
| Branch | `w51/livemerge` |
| Started at | `a914708` (= `main` at dispatch) |
| Merged | `w50/live` @ `f0550a6`, merge-base `4d78f6c`, merge commit `ff38e77` |
| Lane | merge-prep. **`bin/fleet.py` NOT modified — by the merge or by me.** |
| Interpreters | `py -3.13` → 3.13.x; `py -3.10` → 3.10.1 |
| Floor | **4636 collected → 4621 / 14 / 1 / 0 on BOTH interpreters** |
| Live fleet verbs run | **NONE.** No `fleet init`, no write to `~/.claude/settings.json`, no append to `~/.claude/fleet-homes.list`; `~/.claude/fleet-statusline-chain.json` verified ABSENT after the run. |
| Fence | commits on `w51/livemerge` only; no push; `main` untouched; no other ref moved. |

Every line is tagged **MEASURED** (I ran it in this lane and read the output) or **BELIEVED**
(reasoning, or arithmetic over numbers I did not myself produce).

---

## 0. HEADLINE

**MEASURED. The merge is additive and conflict-free, and it is conflict-free structurally rather
than luckily: `w50/live` adds three files that do not exist on either `main` or the merge base,
and modifies nothing.** `git merge-tree` reports three `added in remote` and zero `changed in
both`. **`bin/fleet.py` is byte-identical at the base and at `w50/live` (blob `c759e8c`)**, so the
overlap this merge creates is **citation-only, not functional** — the condition the brief said
would make this a different job does not hold, and I did not stop.

**The citation cost is 108 stale line numbers, not 33, and none of them is a self-citation.**
`tests/test_self_citations.py` — the oracle the brief names — resolves line numbers *against
`bin/fleet.py`, about `bin/fleet.py`*, and nothing else. Since this merge does not touch
`bin/fleet.py`, **its self-citation cost is exactly zero, and that oracle was green before the
merge, after the merge, and after my re-pins.** What the merge actually creates is *cross-document*
rot, which that file's own docstring says is **pinned by nothing**: the two new files cite
`bin/fleet.py` as it stood at `4d78f6c`, and `main` has since taken slice (d) (+250/−37, 21453 →
21666 lines). **15 citations in the live test moved; 93 of 96 in the lane report moved.**

**I re-pinned the 15 and deliberately did not re-pin the 93.** A live test's prose is a claim about
the current tree. A lane report is dated history by the repo's own classification, its header
already declares its base, and rewriting its numbers would make it claim a measurement it never
made.

**Every floor prediction hit, including the falsifiable by-product.** Predicted before running:
+34 collected / +34 passed / +0 skipped / +0 xfailed / +0 failed, absolute 4636 → 4621 / 14 / 1 / 0
on both interpreters. **Measured: exactly that, on both.** The prediction also *derived* slice (d)'s
own test contribution as +364 collected; I then measured the merge base directly at **4238** and
`main`'s share at **4602**, so **+364 is now measured too, and it hit.**

---

## 1. THE MERGE

### 1.1 Lane verification

**MEASURED.** cwd `C:/proga/fleet-w51-livemerge`, `git rev-parse --abbrev-ref HEAD` →
`w51/livemerge`, `git rev-parse HEAD` → `a9147089beb66d7c6713ce661c40bae5ae7c2bf0`, working tree
clean. Agrees with the brief; I proceeded.

### 1.2 The merge base, and why `git diff main w50/live` is the wrong instrument

**MEASURED:**

```
# at a914708
$ git merge-base main w50/live
4d78f6cdc6a8c94a9e258ae74ab07ca7d17f2228
```

The brief's prior re-derives. And the naive diff is wrong by an order of magnitude, exactly as
warned:

| instrument | files | insertions | deletions |
|---|---|---|---|
| `git diff --stat 4d78f6c w50/live` — **correct, base-relative** | **3** | **3036** | **0** |
| `git diff --stat main w50/live` — naive, reports the UNION of both sides | 45 | 3221 | 15876 |

The three files are `docs/lanes/w50-live.md` (1659), `tests/test_liveness_readers.py` (1157),
`tools/mutate_liveness.py` (220). **MEASURED:** all three are ABSENT on both `main` and `4d78f6c`
(`git cat-file -e` non-zero for each on both refs).

### 1.3 The conflict census — control first, and the 25-vs-26 reconciled

The brief warns that a marker grep over empty output returns zero and reads as "no conflicts". So
the control ran **first**, and both counts are reported over a **byte count of the output**, which
is what distinguishes "found nothing" from "was handed nothing".

**MEASURED, all at `main = a914708`:**

| | command | output bytes | anchored `grep -cE '^\+?<<<<<<<'` | unanchored `grep -cE '<<<<<<<'` |
|---|---|---|---|---|
| **control** | `git merge-tree 0726914 main w35/nd4c` | 154 364 | **25** | **26** |
| **subject** | `git merge-tree 4d78f6c main w50/live` | 187 812 | **0** | **0** |

`0726914` is `git merge-base main w35/nd4c`; `w35/nd4c` is `1e810f7`.

**The control reproduces the brief's `25` exactly, and this lane can also say why two parties
declared 25 and 26 for the same pair and never reconciled it. It is the grep anchor, not the
merge.** **MEASURED** — the one hit the unanchored form adds is not a conflict marker at all, it is
prose:

```
knowledge/lessons.md:994:  - `lessons.md#2026-08-05-w42-landing` — ... the `<<<<<<<` marker grep read **0 on the
                            branch known to conflict** — caught only because the control ran first. ...
```

A markdown bullet, inside backticks, in the very lesson that records this class of error. **25 is
the correct number and the anchored form is the correct instrument;** 26 is that form's own
documentation counting itself.

**The subject's zero is structural, not lucky.** `git merge-tree` reports the shape:

```
added in remote
  their  100644 eb49a6b… docs/lanes/w50-live.md
added in remote
  their  100644 4c0c67c… tests/test_liveness_readers.py
added in remote
  their  100644 22c2e07… tools/mutate_liveness.py
```

Three `added in remote`, **zero `changed in both`** — against nine `changed in both` in the
control's first ten header lines. Three new files cannot conflict with a side that does not have
them.

**Merged at `ff38e77`**, `Merge made by the 'ort' strategy`, 3 files changed, 3036 insertions.

### 1.4 Lost-hunk check — Python, digit-masked, seeded both ways

Every line added by `w50/live` **measured from the base** must survive into the merge, with `:NNNN`
and `:NNNN-NNNN` digit-masked on both sides so a moved citation is not miscounted as a lost hunk.
Written in Python because an added line beginning `- ` makes `grep -Fqx` parse it as a flag.

**MEASURED:**

```
real     files=3  added_lines_checked=3036  lines_beginning_with_dash_space=0
         LOST HUNKS: 0   exit=0
seed +   (append a line known to BE in the merged tree)        LOST HUNKS: 0   exit=0
seed -   (append "- a hunk that was never merged, cited at bin/fleet.py:99999")
         LOST HUNKS: 1  ->  docs/lanes/w50-live.md: '- a hunk that was never merged…'   exit=1
```

**0 lost of 3036.** The negative seed carries the *shape* of the hazard — leading `- `, and a
citation so masking cannot rescue it — and is caught.

**A measured difference from the sibling lane, reported because it changes what the check proves
here:** that lane had 59 added lines beginning `- `; **this one has 0**. Confirmed independently —
`grep -c '^- '` is 0 on all three files, because `w50/live` writes bullets with `*`. **So the shell
hazard was latent in this data, not exercised by it.** The negative seed is the only reason I can
say the check would have caught it, and that is precisely why the brief demands a seed with the
shape rather than an instance.

---

## 2. THE CITATION COST

### 2.1 The self-citation pass costs zero, and the brief's 7 + 26 is a forward budget

**MEASURED:** `py -3.13 -m pytest -q tests/test_self_citations.py` → **17 passed**, green on the
first read, and green at fixpoint (§2.5). That is not a lower bound hiding a census — it is
correct, and the reason is structural.

**MEASURED,** from that file's own docstring: it pins *"every line number `bin/fleet.py` cites
ABOUT ITSELF"*, and lists under **NOT PINNED**: *"Citations of OTHER documents … This file resolves
line numbers against `bin/fleet.py` and nothing else."* **MEASURED:** `w50/live` does not touch
`bin/fleet.py` — blob `c759e8ca…` at `4d78f6c` and at `w50/live`, `3661d1f9…` at `main` and at the
merge commit. **A merge that adds no line to `bin/fleet.py` can create no self-citation.**

**The brief's `7 at _roster_live_sids` and `26 at recompute_worker_native` are not a merge cost at
all.** **MEASURED** at `docs/lanes/w50-live.md` §6.5, they are a **forward budget for an unbuilt
feature** — the projected re-pin cost of inserting ~80 lines into `bin/fleet.py` at two candidate
insertion points, tabulated to argue that `:14656` is the right one and `:3714` costs ~4× for no
benefit. `w50/live` inserted nothing. The section even says so itself: *"Re-derive the absolute
number against `tests/test_self_citations.py`'s own scanner before quoting it — do not inherit 36,
or 42."* The brief inherited 26 and 7.

### 2.2 What the merge does cost: 108 stale cross-document citations

The two new files cite `bin/fleet.py` at `4d78f6c`. `main` has since taken slice (d):
**MEASURED**, `git diff --stat 4d78f6c HEAD -- bin/fleet.py` → **+250 / −37**, 21453 → 21666 lines.

I built an **OLD → NEW line map** by diffing the base blob against the merged one, then applied it
to every citation. **The map is self-checked, totally**: every carried mapping must satisfy
`old[i] == new[map[i]]`, and the detector is seeded by corrupting one mapping.

**MEASURED:**

```
line map: base=21454 new=21667  carried=21417  deleted=37
SELF-CHECK: mappings whose text does not match: 0  (map is sound)
SEED (one mapping deliberately corrupted): detector reports 1 bad, was 0 -> CAN FAIL
```

| file | citations resolving into the base | **moved** | unmoved | deleted | unverified | AST disagreements |
|---|---|---|---|---|---|---|
| `tests/test_liveness_readers.py` | 15 | **15** | 0 | 0 | 0 | 0 |
| `docs/lanes/w50-live.md` | 96 | **93** | 3 | 0 | 0 | 0 |

**108 of 111.** Not one cited line was deleted by slice (d) — it is a pure displacement.

*(The `docs/lanes/w50-live.md` row is measured on the file as merged, before I added the note
described in §2.4; that note itself contains line numbers and would be counted by a re-run.)*

### 2.3 Re-pinned: the 15 in the live test, each verified three ways before any edit

`tests/test_liveness_readers.py` is a **live test in the floor**. **MEASURED:** all 15 of its
citations sit in comments and docstrings — none is load-bearing, and the file was green (34 passed)
both before and after. But a live test's prose is a claim about the **current** tree: a reader
following `:8230` today lands 143 lines short. So they rot, and they were re-pinned.

**No target was accepted from a grep hit.** Each had to pass three independent conditions, checked
*before* the file was opened for writing:

1. **TEXT** — the new line is **byte-identical** to the base line that was cited;
2. **RANGE** — `end >= start` after the remap (four of the fifteen are ranges);
3. **AST** — for a named citation, the new line lies inside the definition the citation names.

**MEASURED: 15 proposed, 0 failed.** And the seed matters more than the pass:

```
SEED (target deliberately off by 5): text=FAIL ast=OK -> DETECTED
   (note AST alone says OK: name-containment is the WEAKER of the two checks)
```

**That is the finding worth carrying: AST name-containment alone would have accepted a target five
lines wrong**, because a 300-line function contains both. Byte-identity of the cited line is what
actually pins it. A re-pin pass validated only by "does it still resolve inside the right function"
is a weaker instrument than it looks.

| test line | citation | base → merged | |
|---|---|---|---|
| 381 | `:14994` | 14994 → 15207 | |
| 421 | `bin/fleet.py:8230` | 8230 → 8373 | `old_live = old_sid in _roster_live_sids(entries)` |
| 425 | `bin/fleet.py:3760` | 3760 → 3772 | `live = entry is not None and (…)` |
| 447 | `recompute_worker_native:3760` | 3760 → 3772 | in span (3726–3792) |
| 502 | `:14663-14667` | 14663-14667 → **14876-14880** | in `_roster_live_sids` (14869–14891) |
| 536 | `_cmd_respawn_native:8230` | 8230 → 8373 | in span (8258–8557) |
| 542 | `:8240-8243` | 8240-8243 → **8383-8386** | |
| 543 | `:8277` | 8277 → 8420 | `new_record["retired_sids"] = …` |
| 545 | `:8629` | 8629 → 8776 | `…[-_RETIRED_SID_SWEEP_CAP:]` |
| 546 | `:9430` | 9430 → 9577 | `for retired in list(rec.get("retired_sids"…` |
| 584 | `:8244-8255` | 8244-8255 → **8387-8398** | |
| 637 | `:8483` | 8483 → 8630 | |
| 639 | `:9447-9451` | 9447-9451 → **9594-9598** | `def _any_live():` |
| 814 | `bin/fleet.py:2993` | 2993 → 3005 | `def _record_is_live(rec) -> bool:` |
| 1069 | `:8259` | 8259 → 8402 | |

**All four ranges satisfy `end >= start` after the remap** — the backwards-range class the brief
names did not occur here, because slice (d) displaced whole blocks rather than splitting any cited
range. **I did not find the "range END no census sees" that the sibling lane found**; §2.2's map
carries START and END through the same verified mapping, so a range whose END alone moved would
have surfaced as a text mismatch, and none did.

**One imprecision I preserved rather than fixed.** Line 637 cites `_is_supervisor_shaped` at
`:8483` → `:8630`. **MEASURED:** `_is_supervisor_shaped` is *defined* at 2046–2052; 8630 is the
comment immediately below its **call site** at 8629. The citation was already pointing at
explanatory prose rather than the definition, at `w50/live`'s own base. I moved the line and
changed nothing else — I am not re-reviewing that branch. **Flagged for the successor.**

### 2.4 NOT re-pinned: the 93 in the lane report, and why that is the correct answer

**MEASURED:** `docs/lanes/` is the first entry of `_HISTORICAL_PREFIXES`
(`tests/test_doc_claims.py:445-447`), the tuple whose comment reads *"dated, per-wave working
records"*. **MEASURED:** `docs/lanes/w50-live.md`'s own header table already declares
`Base | 4d78f6c`. And the repo's standing doctrine, `knowledge/lessons.md`: *"a pinned receipt and
a quoted argument are claims about a PAST tree and are still true."*

**Rewriting those 93 numbers would make the report claim a measurement it never made.** The
citations are true of `4d78f6c`; the file says which tree that is; the classification says the file
is history. **They stay.**

What does *not* stay is the operational hazard, because §6.5 is an **executable build brief** the
successor will act on by line number. So I added a note — additive, dated, attributed, **altering
no measured number in that file** — recording the drift and remapping the two numbers §6.5 actually
recommends: **`:3714 → :3726`** (`recompute_worker_native`) and **`:14656 → :14869`**
(`_roster_live_sids`). The ranking and the ~4× ratio that section tells a successor to budget
against are unaffected by the displacement.

### 2.5 Fixpoint

**MEASURED — run twice with no edit between, `git diff --numstat` identical (`15  15`) either
side:**

| | pass 1 | pass 2 |
|---|---|---|
| AST census on the re-pinned test | 2 named, **2 resolve, 0 stale, 0 backwards** | identical |
| `tests/test_self_citations.py` | **17 passed** | **17 passed** |
| `tests/test_liveness_readers.py` | **34 passed** | **34 passed** |

---

## 3. FLOORS

### 3.0 The prediction, as committed at `9b9af26` BEFORE any floor ran

*Reproduced verbatim from the commit that contains no results. Its provenance is `git show 9b9af26`.*

> **Δ against `main` — this is the real claim, and it does not depend on either inherited number:**
> **+34 collected, +34 passed, +0 skipped, +0 xfailed, +0 failed**, identically on `py -3.13` and
> `py -3.10`.
>
> **Absolute, conditional on the inherited `main` = 4602 → 4587 / 14 / 1 / 0:**
> **4636 collected → 4621 passed / 14 skipped / 1 xfailed / 0 failed, on BOTH interpreters.**

The three routes by which the merge could move the floor were enumerated and closed **statically**,
before running anything: the new test file (open — **MEASURED** to contain no `parametrize`, so a
fixed count); `tools/mutate_liveness.py` (closed — `pytest.ini` declares no `testpaths` and the
name matches no collection pattern); and the new markdown (closed — **`docs/lanes/` is in
`_HISTORICAL_PREFIXES`, so neither new `.md` enters `CHECK_COUNT_DOCS`** and the two pins
parametrised over it gain no cases). Predicted docs contribution: **0**.

Stated risk at the time: the `py -3.10` skipped count, BELIEVED not measured, because 3.10 and
3.12+ tokenise f-strings differently and a version-keyed skip-guard would move `skipped` without
moving `collected`.

### 3.1 The result

**MEASURED, full suite, both interpreters:**

```
py -3.13 -m pytest -q    4621 passed, 14 skipped, 1 xfailed in 414.03s (0:06:54)
py -3.10 -m pytest -q    4621 passed, 14 skipped, 1 xfailed in 386.33s (0:06:26)     (Python 3.10.1)
```

**COLLECTED, never counted from `def test_` lines — `--collect-only -q`, both interpreters:**

| | 3.13 | 3.10 |
|---|---|---|
| whole suite | **4636** | **4636** |
| `--ignore=tests/test_liveness_readers.py` | **4602** | **4602** |
| `tests/test_liveness_readers.py` alone | **34** | **34** |

| prediction | result | |
|---|---|---|
| Δ +34 collected / +34 passed / +0 skipped / +0 xfailed / +0 failed | +34 / +34 / +0 / +0 / +0 | **HIT** |
| absolute 4636 → 4621 / 14 / 1 / 0, both interpreters | 4636 → 4621 / 14 / 1 / 0, both | **HIT** |
| docs contribution 0 | 0 | **HIT** |
| `test_self_citations.py` stays at 17 | 17 | **HIT** |
| risk: 3.10 might differ | identical on both, 34 = 34 | **risk did not materialise** |

**Re-run on the FINAL tree, with this report committed in it** — because §3.0 predicted a docs
contribution of **0**, and a report is a docs change, so the claim has to be measured on the tree
that would actually land rather than on the tree that existed when the claim was made:

```
collected, final tree      py -3.13  4636      py -3.10  4636
full floor,  final tree    py -3.13  4621 passed, 14 skipped, 1 xfailed in 416.35s
                           py -3.10  4621 passed, 14 skipped, 1 xfailed in 394.47s
```

**Same numbers again. The docs contribution is now MEASURED at 0, not predicted at 0** — adding
1659 + 488 lines of markdown under `docs/lanes/` moved the floor by nothing, which is what
`_HISTORICAL_PREFIXES` is for.

### 3.2 The inherited number, and the by-product, both upgraded to MEASURED

The absolute prediction was *conditional* on a `main` figure I could not re-run. **Both halves of
that condition are now measured without ever checking out `main`:**

* **`--ignore` the one file the merge adds → 4602 collected, on both interpreters.** That is
  exactly the inherited `main` figure. **The brief's 4602 was right.**
* **The merge base was measured directly.** A worktree already sits at `4d78f6c`
  (`C:/proga/fleet-w50-mp`); a `--collect-only` run there with `PYTHONDONTWRITEBYTECODE=1` and
  `-p no:cacheprovider` wrote nothing and left it clean (`git status --porcelain` empty before and
  after): **4238 tests collected.**

So the whole chain is measured rather than believed, and it closes:

```
base 4d78f6c                                4238   MEASURED (read-only, in the base worktree)
+ slice (d)                                 + 364   MEASURED as 4602 - 4238  <- the by-product, PREDICTED
= main a914708                              4602   MEASURED via --ignore
+ tests/test_liveness_readers.py            +  34   MEASURED
= merged                                    4636   MEASURED, both interpreters
```

**The +364 was a falsifiable by-product of the prediction's Route B and it HIT.** It also confirms
`w50/live`'s own self-reported 4272 collected: 4238 + 34 = 4272. ✅

### 3.3 The runs changed nothing

**MEASURED — working-tree digest, `files=` included, printed immediately before and after each
floor run, in this one working tree (the digest is checkout-relative and is compared only against
itself):**

```
c70f5280368aaddde35cb013a163d4dcd53e6857aaf6b6d8a01a8ff7d773b7b5  files=261   before 3.13
c70f5280368aaddde35cb013a163d4dcd53e6857aaf6b6d8a01a8ff7d773b7b5  files=261   after  3.13
c70f5280368aaddde35cb013a163d4dcd53e6857aaf6b6d8a01a8ff7d773b7b5  files=261   before 3.10
c70f5280368aaddde35cb013a163d4dcd53e6857aaf6b6d8a01a8ff7d773b7b5  files=261   after  3.10
c70f5280368aaddde35cb013a163d4dcd53e6857aaf6b6d8a01a8ff7d773b7b5  files=261   after everything
```

**Byte-identical across all five readings, `files=261` included.** `git write-tree` was never used.
`git status --porcelain` is empty.

---

## 4. THE SURVIVING FINDING — carried forward UNFIXED, re-driven on the merged tree

The brief states it with two line numbers from before slice (d) landed. **Re-derived by AST on the
merged tree, not quoted — and the line numbers have both moved:**

```
_RETIRED_SID_SWEEP_CAP -- AST references on the merged tree: 3
  :8650   in <module>                     STORE (the definition)     _RETIRED_SID_SWEEP_CAP = 20
  :8776   in _cmd_kill_native             LOAD  (a call site)        if s and s != sid][-_RETIRED_SID_SWEEP_CAP:]
  :9577   in _cmd_respawn_supervisor      LOAD  (a call site)        for retired in list(rec.get("retired_sids", []) or [])[-_RETIRED_SID_SWEEP_CAP:]:

_cmd_respawn_native      (8258-8557):  _RETIRED_SID_SWEEP_CAP refs = NONE
_cmd_respawn_supervisor  (9450-9639):  _RETIRED_SID_SWEEP_CAP refs = [9577]
_cmd_kill_native         (8653-8826):  _RETIRED_SID_SWEEP_CAP refs = [8776]
```

> **`_RETIRED_SID_SWEEP_CAP` has exactly two call sites — `:8776` and `:9577` on the merged tree,
> was `:8629` and `:9430` before slice (d) — and NEITHER is `_cmd_respawn_native`.** So on the
> worker respawn path there is **no stop, no tombstone and no sweep** — backwards from its own
> docstring. `w50/live`'s §6 is an executable build brief for it.

**The finding survives the merge unchanged, and it is not fixed here.** Two independent instruments
agree on the new numbers: the AST walk above, and the §2.2 line map (8629 → 8776, 9430 → 9577)
which reached them by byte-identity of the cited line.

**One thing the AST sees that a grep would not.** There are **4** textual mentions of the constant
in the file — `[8650, 8679, 8776, 9577]` — but only **3** are code. `:8679` is prose. A grep-based
census would have reported three call sites, or two-plus-a-definition miscounted; the "exactly two
call sites" claim is only true of the AST reading, and that is how it should be re-derived next
time.

**For the successor**, the insertion-point guidance in `w50/live` §6.5 remaps to **`:3726`**
(`recompute_worker_native`) and **`:14869`** (`_roster_live_sids`) — the latter still the
recommended one, at roughly a quarter the citation cost.

---

## 5. FENCE AND SAFETY

**MEASURED.** Commits on `w51/livemerge` only: `ff38e77` (merge), `be3a94e` (re-pins), `9b9af26`
(prediction), and this report. **No push.** `main` untouched — it is still `a914708`, and the only
command run against another worktree was a read-only `--collect-only` that left
`C:/proga/fleet-w50-mp` clean. No other ref moved. No `fleet init`; `~/.claude/settings.json` never
opened for write; `~/.claude/fleet-homes.list` never appended to (**MEASURED: it does not exist**);
**`~/.claude/fleet-statusline-chain.json` verified ABSENT after the run.** No background process
was left running.

---

## 6. WHERE THIS BRIEF WAS WRONG

**1. "Pay the self-citation re-pin pass" — there is no self-citation cost, and the pass it names
cannot see the cost that exists.** The brief points at `tests/test_self_citations.py` as the oracle
and says "derive your own" numbers from it. **MEASURED:** that file resolves line numbers *against
`bin/fleet.py`, about `bin/fleet.py`*, and this merge does not touch `bin/fleet.py`. It was green
before, during and after, and it is green *correctly* — a fixpoint on it certifies nothing about
this merge. **The real cost is cross-document, which that file's own docstring lists under NOT
PINNED.** Running the named oracle to fixpoint and stopping there would have shipped 108 stale
citations green. The brief's own instruction to derive rather than inherit is what saved it.

**2. The `7` and `26` are not stale merge numbers — they are a forward budget for an unbuilt
feature.** The brief calls them "`w50/live`'s own §6 measured its self-citation cost", "stale by
construction". **MEASURED at §6.5:** they are the projected cost of *inserting ~80 lines* at two
candidate insertion points, tabulated to choose between them. They were never a cost this merge
could pay. The brief also inherited exactly the numbers §6.5 explicitly tells a successor not to
inherit.

**3. "Expect the same class" of range-END defect — it did not occur, and the reason is worth
recording.** All four ranges remapped with `end >= start`. Slice (d) displaced whole blocks; it did
not split any cited range. **The sibling lane's finding does not generalise to this merge**, and a
lane that went looking for it and "found" one would have been manufacturing it.

**4. The lost-hunk `- ` hazard was latent, not present.** The brief warns that the sibling lane had
59 added lines beginning `- `. **MEASURED: this change set has 0** — `w50/live` writes bullets with
`*`. The warning was still correct to give; the seed is the only thing that proves the check works
here.

**5. Right for a reason the brief did not give: "likeliest, that 0 conflicts survives
re-derivation".** It does, but not because slice (d) happened to miss. **`w50/live` adds three
files and modifies none**, so `merge-tree` reports three `added in remote` and zero `changed in
both`. Zero was structurally guaranteed. The brief's framing ("a clean auto-merge still leaves
stale citations, which is the whole reason you exist") was exactly right, and is the finding.

**6. Right, and now reconciled: the bare `25`.** The control re-derives at **25 anchored**, at
`main = a914708`, by `git merge-tree 0726914 main w35/nd4c`, over 154 364 bytes of output. **The
25-vs-26 disagreement between two parties is the grep anchor**: the unanchored form's 26th hit is a
prose bullet in `knowledge/lessons.md:994` — inside the lesson that documents this very failure.

**7. Correct on every remaining check, stated so it is not re-litigated:** merge-base `4d78f6c`
✅; subject 0 conflicts ✅; naive-diff inflation (9-vs-41 for the sibling; **3-vs-45** here) ✅;
`docs/lanes/` exempt from `CHECK_COUNT_DOCS` and `docs/operator/` not ✅; `main` = 4602 → 4587 /
14 / 1 / 0 ✅ (**independently confirmed by `--ignore`**); `w50/live` = 4257 / 14 / 1 ✅
(**confirmed: 4238 + 34 = 4272 collected**); the `_RETIRED_SID_SWEEP_CAP` finding ✅ (survives, and
`_cmd_respawn_native` still has no reference to it).

**8. An instrument defect of my own, recorded because it is the same class the campaign keeps
paying for.** My re-pin script read the target with `Path.read_text()` and wrote it back with
`newline=""`, which **silently converted the whole file from CRLF to LF** — the repo is
`core.autocrlf=true` with no `.gitattributes` rule for `*.py`, and every other `.py` on disk is
CRLF. `git diff` showed the intended 15 lines and nothing else, because git normalises; the change
was invisible to the diff and visible only in git's incidental *warning*. Restored to CRLF (61 344
bytes, 1157 CRLF, 0 bare LF) before any floor ran. **This is the `w50-gd2` line-ending finding
reached from a different direction: a whole-file byte change that `git diff` calls clean.** The
working-tree digest would have caught it only if taken across the edit — which is an argument for
taking it around *edits*, not only around *runs*.
