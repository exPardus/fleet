# Lane report — `w51-dmerge`: landing slice (d), and its fourth re-pin pass

**Lane:** merge-prep. Branch `w51/dmerge`, forked at `75aa4eb` (== `main`). Mode bypass.
**Fence honoured:** commits on `w51/dmerge` only. No push. `main` not touched. No other ref moved.

Every line below is tagged **MEASURED** (I ran it, in this worktree or in an isolated clone, and the
command is quoted) or **BELIEVED** (inherited, derived, or argued but not driven).

---

## §0. THE FLOOR, PREDICTED BEFORE ANY RUN

**This section is committed with no measurement of the merged tree in existence.** At the moment of
this commit no `pytest` has been invoked in this working tree, on any interpreter. What follows is
arithmetic over three floors measured on three OTHER commits, in a throwaway `git clone --local`
with detached checkouts — no ref moved, no worktree added, this tree untouched.

### The three inputs — MEASURED, by me, today

| commit | what it is | collected | passed | skipped | xfailed | failed |
|---|---|---|---|---|---|---|
| `4d78f6c` | the merge base | **4238** | 4223 | 14 | 1 | 0 |
| `75aa4eb` | `main`, the ours side | **4351** | 4336 | 14 | 1 | 0 |
| `2cc4410` | `w51/dtype`, the theirs side | **4489** | 4474 | 14 | 1 | 0 |

```
# at 4d78f6c   (isolated clone, py -3.13)
py -3.13 -m pytest -q
  4223 passed, 14 skipped, 1 xfailed in 412.86s (0:06:52)

# at 75aa4eb
py -3.13 -m pytest -q
  4336 passed, 14 skipped, 1 xfailed in 415.82s (0:06:55)

# at 2cc4410
py -3.13 -m pytest -q
  4474 passed, 14 skipped, 1 xfailed in 436.21s (0:07:16)
```

The brief supplied `main` and `w51/dtype` as given numbers. **Both are confirmed exactly** — but they
are quoted above as my own measurements, because the brief's own instruction is to inherit nothing,
and because the third row is the one it did not supply and the arithmetic cannot be done without.

### The arithmetic

Each side's contribution is its delta over the **merge base**, never its diff against `main`:

```
  main   - base  =  4351 - 4238  =  +113 tests   (all passing: 4336 - 4223 = +113)
  dtype  - base  =  4489 - 4238  =  +251 tests   (all passing: 4474 - 4223 = +251)

  merged = base + 113 + 251 = 4238 + 364 = 4602
```

### PREDICTION

> **`w51/dmerge` at its final commit collects 4602 → 4587 passed / 14 skipped / 1 xfailed / 0 failed,
> identically on `py -3.13` and `py -3.10`.**

Consistency: 4587 + 14 + 1 = 4602. Skips and xfails are predicted flat at 14/1 because all three
input trees measure 14/1: both sides added 364 tests between them and neither added a skip or an
xfail.

### Why the cross-terms are zero — the part the arithmetic does not prove on its own

Simple addition is only valid if no test population is derived from a tree fact **both** sides moved.
The brief names the live example: `CHECK_COUNT_DOCS` (`tests/test_doc_claims.py:506`,
`current_tree_docs()`) is every tracked `*.md` minus `_HISTORICAL_PREFIXES`, and **two pins are
parametrised over it**, so a docs-only change can move the floor. Measured in this worktree:

- `CHECK_COUNT_DOCS` is **present** at `tests/test_doc_claims.py:506`, exactly as the brief says.
  *(The brief's parenthetical is right and `w51-gdtype` was wrong: it reads absent only on that
  gate's own branch, which predates the launchfix merge.)* — **MEASURED**
- It is **30** files on the merged tree, and **30** at `main`. `_HISTORICAL_PREFIXES` exempts
  `docs/lanes/`; `docs/operator/` is **not** exempt and both of its files are among the 30. —
  **MEASURED**
- The merge adds exactly three `.md` — `docs/lanes/w50-d.md`, `docs/lanes/w50-gd2.md`,
  `docs/lanes/w51-dtype.md` — **all under `docs/lanes/`, all exempt.** So dtype's contribution to
  this population is **0**, which is precisely the condition under which the additive formula stays
  valid. — **MEASURED**
- **This report is `docs/lanes/w51-dmerge.md` and is therefore also exempt**, so committing it — and
  every later section of it — moves the floor by 0. — **MEASURED** (its path is in the exempt set)
- At the base `4d78f6c` the constant does not exist at all (`test_doc_claims.py` collects 26 there),
  and dtype never touches that file, so the merged tree inherits `main`'s copy with `main`'s
  population. The additive formula reproduces that correctly. — **MEASURED**
- `tests/test_self_citations.py` contains **no** `parametrize`: 20 fixed tests. So the 31 citation
  re-pins in the next commit move the collected count by **0**. — **MEASURED**

### What could still falsify this, stated in advance

- **BELIEVED:** that no parametrisation inside `tests/test_statusline_home.py` (dtype's 1540-line new
  file) is derived from a `bin/fleet.py` population that `main` also grew. If one is, its collected
  count on the merged tree differs from its count on dtype's tree and the prediction is low.
- **BELIEVED:** that no other tree-derived parametrisation (`HOOK_SCRIPTS`, `BRIEF_DRIVERS`,
  `SURFACES`, `VERBS`, `TOMBSTONE_KINDS`, the install-plane helper lists) has a population both
  sides moved. I argued this rather than driving each one.
- **BELIEVED:** that `py -3.10` matches `py -3.13`. Both sides measure identically on both today, per
  the brief; I measured only `3.13` for the three inputs.
- The merge commit `b058d1e` itself is expected **RED** on `tests/test_self_citations.py` — 31 of its
  42 citations are stale by construction at that commit. The prediction above is for the **branch
  tip**, after the re-pin pass. That is the tree that has to be landable.

> **CORRECTION to the paragraph above, added after the run (the text is left standing, not edited,
> because a prediction that is quietly repaired is not a prediction).** §0 says
> `tests/test_self_citations.py` is *"20 fixed tests"*. It is **17** — seven in
> `TestTheScannerActuallySeesSomething`, ten in `TestEverySelfCitationResolves`. I counted the
> `def test_` lines from a grep instead of collecting them, which is the exact substitution the
> brief forbids for a test-count delta, made in the sentence arguing that a count would not move.
> The claim the number was serving is unaffected and is separately true: the file carries no
> `parametrize`, so its contribution is constant whatever its size.

---

## §1. THE MERGE — `w51/dtype` @ `2cc4410` into `w51/dmerge`

Committed at **`b058d1e`**.

### The conflict control, run first, with its commit named — MEASURED

The brief's instruction, and `BRIEF-TEMPLATE.md`'s: quote the command, the commit and the number
together, or quote none of them.

```
# at 75aa4eb
git merge-tree $(git merge-base main w35/nd4c) main w35/nd4c | grep -cE '^\+?<<<<<<<'
  25
```

Unanchored, the same pair answers **26**. That is the one prose hit `BRIEF-TEMPLATE.md` records — a
document quoting the marker in its own text — reproduced here at a **named** commit, which is what
the bare `25` in that file was corrected this wave for lacking. `main`'s merge-base with `w35/nd4c`
is `0726914` at this commit.

I did not reconcile the supervisor's 25 with gate `w51-glaunch2`'s 26/31, and I do not need to: my
own anchored run at my own base is 25, and both values discharge the duty the control exists for,
which is to be non-vacuous.

### The subject pair — MEASURED

```
# at 75aa4eb
git merge-tree 4d78f6c w51/dmerge w51/dtype | grep -cE '^\+?<<<<<<<'
  12
```

Anchored **12**, unanchored **12** — no prose markers on this pair. The real `git merge --no-commit
--no-ff` then produced **12** markers in the working tree (`grep -cE '^<<<<<<<' bin/fleet.py`), so
the trivial three-way and the recursive merge agree on the number. All twelve are in `bin/fleet.py`;
no other file conflicted.

**The brief's prior of 12 is confirmed.** It was checked, not reused.

### The change set is measured from the MERGE BASE — MEASURED

`w51/dtype`'s merge-base with both `main` and `w51/dmerge` is `4d78f6c`, a dozen wave-50 commits
back. The two framings:

| framing | files | insertions | deletions |
|---|---|---|---|
| `git diff 4d78f6c w51/dtype` — **the branch's work** | **9** | +5108 | −63 |
| `git diff main w51/dtype` — the wrong one | 41 | +5230 | −10230 |

The wrong framing inflates a 9-file change set to 41 and invents 10,167 deletions that are simply
`main`'s own wave-50 commits seen backwards.

### All twelve conflicts are citation-only — MEASURED, and by an instrument that has returned non-zero

Each conflict block's `.our` and `.their` sides were compared after masking `:NNNN` **and**
`:NNNN-NNNN`. Result: **12 of 12 CITATION-ONLY, 0 functional overlap.**

A "0" from an instrument that has never returned anything else is not a measurement, so the
classifier was seeded twice before I believed it:

- a synthetic two-block input, one citation-only and one differing by an operator (`a + b` vs
  `a - b`) inside an otherwise identical line: reports 1 functional overlap;
- **the control pair itself** — `main × w35/nd4c` — where it reports 25 blocks of which **13 are
  genuinely functional overlap**, including one where the two sides differ in line count.

**The first version of that classifier was wrong and said 12 of 12 FUNCTIONAL.** `git merge-tree`
prefixes the `.our` side of a conflict with a diff **space** and the `.their` side with `+`; stripping
only `+` left the two sides differing by one column of indentation that exists in neither file. Had I
trusted it, this lane would have stopped and reported "functional overlap — different job", which is
the brief's explicit escape hatch, on an artefact of my own parser. The fix strips exactly one prefix
column from both sides.

### Resolution — MEASURED

Both sides of every block are byte-identical under the mask **and** equal in line count (asserted per
block), so the file's length is the same whichever side is kept. Ours was kept, and **neither side's
digits were believed**: both were computed against trees that no longer exist, and all 42 citations
are re-derived against the merged tree in §2. The wave-50 landing's lesson — *"neither side of a
citation conflict was right and the merged tree's own value was the answer"* — is honoured by not
resolving citations at the conflict at all, and paying them once, from the merged tree, afterwards.

Zero conflict markers survive (`^<<<<<<<`, `^=======`, `^>>>>>>>` all 0; neither side's `bin/fleet.py`
contains a line-initial `=======` legitimately, checked first so the assertion is not vacuous), and
`ast.parse` accepts the result.

### Lost-hunk check — MEASURED, and it carries the shape of the data

**0 lost lines**, across all **41** files either side touched since the base, multiset semantics
(a line added N times must survive N times), digit-masked on both halves.

Written in Python rather than as `grep -Fqx`. The brief warns that a line beginning `- ` is parsed by
grep as an **option**; this data set contains **59** such added lines, all in `docs/lanes/w50-d.md`,
so the grep form would have been silently vacuous over exactly the lines it was warned about. Seeded
both ways, and it fires on both:

```
  drop bin/fleet.py     'TYPE_FAULT = "?type"'                    -> LOST LINES: 1
  drop docs/lanes/w50-d.md  '- `rate_limits.five_hour...'         -> LOST LINES: 1
```

### The brief's escape hatch was not needed

*"If the merge turns out to have functional overlap rather than citation overlap, STOP and report."*
It does not. 12/12 citation-only, 0 functional overlap, 0 lost hunks — MEASURED, with the detector
demonstrated capable of saying otherwise.

---

## §2. THE FOURTH RE-PIN PASS

Committed at **`a70b1ab`**.

**42 self-citations. 11 already correct. 31 stale, all re-pointed. Plus one range END the `:NNNN`
census cannot see.** — MEASURED

The brief's prior was *"31–36 of 42, and treat it as a lower bound."* It is **31** — the bottom of
the band. The bound was the honest way to state it and it held.

### Why the count is 31 and not 34

The first pass reported 8 correct / 29 re-pointable / 5 refused. Three of the five refusals were
citations that were **already correct**: the trio of `:1063` citations for *"`load_registry`
QUARANTINES a corrupt registry — it renames the file aside"* sit in a two-member `one_of` set
(`{1063, 1073}`, both `_quarantine_registry` calls inside `load_registry`, which spans 1045–1077).
`one_of` asks for **membership, not uniqueness**, and `load_registry` sits above every line this
merge moved, so `:1063` still resolves. Re-pointing them would have been an unforced edit to a
correct citation. They are counted as correct.

### Derived from the oracle's own constraints — not from a grep

For each citation the re-pointer intersects **everything `tests/test_self_citations.py` will hold it
to**: the `anchor` substring, the `one_of`/`exactly` derivation, the `in_named_function` span, and
the span of any `` `func:NNNN` `` qualifier. It rewrites only when that intersection is a **single**
line, and otherwise **refuses and says so**.

That refusal is the whole design. The brief's warning — *"a re-pin that auto-resolves to the first
grep hit is a citation generator, not a citation fixer; that shipped green and wrong once, resolving
into an unrelated docstring 7800 lines from the function it named"* — describes precisely what a
tool built on `anchor` alone would have done here. Two examples from this run, both of which an
anchor-only tool would have got wrong:

| citing site | anchor | anchor alone | with the function constraint |
|---|---|---|---|
| *"the presence-only refusal that closes it lives in `_require_claim_holder`"* | `_quarantine_artifacts()` | **15 lines** | `:16561` (unique in `_require_claim_holder`, 16339–16617) |
| *"verbatim as `_sweep_husks` spells it at"* | `registry present or not` | 2 lines — and the **first** is `:905`, in a different function's docstring | `:10870` (unique in `_sweep_husks`, 10827–10959) |

The `_sweep_husks` case is the named defect exactly: the first grep hit is 9,965 lines away from the
function the citation names. Both sites name their target function in their **own citing prose** but
carry no `in_named_function` (the oracle's marker does not capture the name), so the constraint is
declared as a rule the tool applies and **re-derives on every pass**, rather than being resolved by
hand once.

### The range END — the half a `:NNNN` census cannot count

```
  cmd_respawn:8521-8523  ->  cmd_respawn:8617-8619
```

The end moves by the start's own displacement (+96), then is **validated**: `8619 >= 8617`, and
inside `cmd_respawn` (8560–8648). Lines 8617–8619 are the three-line *"resolve under the lock so a
corrupt registry surfaces through load_registry's quarantine"* comment — the passage the citation
claims to bracket. — MEASURED

This is the `cmd_respawn:7443-7343` shape the brief names: a start moved, an end left behind,
producing a backwards range that four instruments were blind to. It is also why **31 is a floor on
the work rather than the work**: the oracle's own `:NNNN` scan is colon-keyed, so the `-8523` was
never a token to it.

### The comma lists — the other half of that blind spot

The sid-union site enumerates **13** numbers across two lines; the `retired_sids` writers enumerate
**4**, cited **twice** in different parts of the file. `exactly=` sites are resolved as a **set** —
equal cardinality, both sequences ascending, assigned positionally — never member by member.

An early version of the tool took an "already a valid member, leave it" shortcut on them. Five of the
sid-union's thirteen (`:2822, :2903, :3164, :3314, :4700`, all above the merge's insertion point and
therefore unmoved) were individually valid, got claimed by the shortcut, and dropped out of the
group — which broke the cardinality match and left the other **eight** unresolvable. The shortcut is
now refused for every `exactly=` site, because there a member that is individually valid can still be
the **wrong** member.

### Two guards that fired

- **`occurrences == 1` on every replacement**, asserted on the citing line before writing. All 32
  writes reported 1.
- **A position assert caught a real collision.** A ranged citation's start and its whole
  `:START-END` span begin at the *same column*, so emitting both edits made the second operate on
  text the first had already rewritten. It aborted **before touching the file** rather than writing
  `:8617-8523` — the backwards-range shape, manufactured by the fixer. `git status` confirmed the
  working tree was untouched after the abort. The range edit now supersedes the scalar edit at that
  position instead of following it.

### Fixpoint — MEASURED, not a single read

19 lines touched, **+19 / −19**: no line moves, so this pass cannot cascade. Then:

```
  re-pin planner, pass 2   ->  already correct: 42   repointable: 0   AMBIGUOUS: 0
                               RANGE cmd_respawn:8617-8619 defect=None
                               FIXPOINT: nothing to change.
  py -3.13 -m pytest -q tests/test_self_citations.py   ->  17 passed
  py -3.13 -m pytest -q tests/test_self_citations.py   ->  17 passed   (no edit between)
  py -3.13 -m pytest -q tests/test_retired_sid_citations.py  ->  4 passed
```

Green **twice in a row with no edit between**, as the brief requires — wave 35 saw only 3 of 7 on a
first run, and a single red/green read is a lower bound, never a census.

---

## §3. THE FLOORS — the prediction met exactly, on both interpreters

**MEASURED.** Digest printed immediately before and after each run, `files=` included; never
`git write-tree`, which hashes the index and cannot fail.

```
=== DIGEST BEFORE ===
1fa799774ae146c96b355f224dfdd9be8c755024c624dd108c5591dfffb3c2f9  files=257  root=C:\proga\fleet-w51-dmerge

py -3.13 -m pytest -q
  4587 passed, 14 skipped, 1 xfailed in 440.05s (0:07:20)

=== DIGEST AFTER 3.13 / BEFORE 3.10 ===
1fa799774ae146c96b355f224dfdd9be8c755024c624dd108c5591dfffb3c2f9  files=257  root=C:\proga\fleet-w51-dmerge

py -3.10 -m pytest -q
  4587 passed, 14 skipped, 1 xfailed in 399.56s (0:06:39)

=== DIGEST AFTER ===
1fa799774ae146c96b355f224dfdd9be8c755024c624dd108c5591dfffb3c2f9  files=257  root=C:\proga\fleet-w51-dmerge
```

And the count **collected**, never inferred from `def test_` lines and never back-computed from the
pass line:

```
py -3.13 -m pytest -q --collect-only   ->  4602 tests collected in 1.65s
py -3.10 -m pytest -q --collect-only   ->  4602 tests collected in 5.32s
```

| | predicted (`f8ea89a`, no results in it) | measured 3.13 | measured 3.10 |
|---|---|---|---|
| collected | **4602** | **4602** | **4602** |
| passed | **4587** | **4587** | **4587** |
| skipped | 14 | 14 | 14 |
| xfailed | 1 | 1 | 1 |
| failed | **0** | **0** | **0** |

**Exact, on both interpreters.** The digest is byte-identical across all five printings at
`files=257`, so neither run modified anything — and the digest is compared **only against itself, in
this one working tree**, since it is checkout-relative and cannot answer whether two trees match.

The interpreter floor is `fleet.MIN_PYTHON_VERSION` (3.10), not this machine's `py -3.13` preference,
which is why both were run rather than only the preferred one.

### The floor above is `a70b1ab`. The BRANCH TIP was floored separately — MEASURED

A floor measured one commit below the tip is an argument about the tip, not a measurement of it, and
this report's §8 makes claims about the tip. So both suites were re-run at `34d6945` — the commit
that added this report — after it was committed:

```
=== TIP 34d69456c82ad90aef3e8c6b20f7782c5496c98d ===
=== DIGEST BEFORE ===
d73ea349fdb50d8172b4a0e349aa6b22db8740e10d76b1d4cf4a1e2408d22bb5  files=257  root=C:\proga\fleet-w51-dmerge
py -3.13 -m pytest -q   ->  4587 passed, 14 skipped, 1 xfailed in 431.30s (0:07:11)
=== DIGEST MID ===
d73ea349fdb50d8172b4a0e349aa6b22db8740e10d76b1d4cf4a1e2408d22bb5  files=257  root=C:\proga\fleet-w51-dmerge
py -3.10 -m pytest -q   ->  4587 passed, 14 skipped, 1 xfailed in 392.38s (0:06:32)
=== DIGEST AFTER ===
d73ea349fdb50d8172b4a0e349aa6b22db8740e10d76b1d4cf4a1e2408d22bb5  files=257  root=C:\proga\fleet-w51-dmerge
py -3.13 --collect-only  ->  4602 tests collected in 1.55s
py -3.10 --collect-only  ->  4602 tests collected in 5.14s
```

**Identical: 4602 → 4587/14/1/0 on both.** The docs commit moved the floor by 0, which is what §0
predicted from the mechanism rather than from hope — `docs/lanes/` is in `_HISTORICAL_PREFIXES`, so
this file was never in `CHECK_COUNT_DOCS`.

The digest differs from the `a70b1ab` bracket (`d73ea349…` vs `1fa79977…`) at the same `files=257`
**because this report's own bytes changed between them** — the file existed at both points, so the
count is flat while the content is not. That is the digest answering the only question it can answer:
*did anything change in this tree between these two printings?* Yes — I wrote §1–§8.

*(The single commit after `34d6945` adds this subsection and nothing else. It is a `docs/lanes/`
append of the same exempt class, so it cannot move the floor by the same argument; I state that
rather than claiming a run I did not make at that sha.)*

---

## §4. WHAT THE SUCCESSOR MUST STILL DO — a specified queue

The three findings from gate `w51-gdtype` (NOT-GATING, 0 BLOCKING) **ride in unfixed**. This lane
fixed none of them and was not asked to. Each is re-driven **on this merged tree** below, so the
successor inherits a measurement rather than a citation.

### QUEUE ITEM 1 — MAJOR — the cap exemption was applied to one of two sibling words

`TYPE_FAULT` (`?type`) is exempt from the unknown-bucket cap; `FIELD_UNKNOWN` (`?`) is not — both
authored by `registry_status`, in the same function, in the same commit.

Driven here, **MEASURED on `a70b1ab`**, three foreign statuses sorting below `?` (ASCII `0x3F`):

```
buckets: work, ?type, ?, !a, "b, #c
order  = ['?type', '!a', '"b', '#c']   hidden = 2
  ?type present: True      ? present: False
```

**The same three statuses suppress `?` and leave `?type` standing.** A foreign home hides the word
meaning *"this home has records with no status recorded"* for the price of three status strings, on
the surface the operator reads continuously, at rc 0 — the exemption's own stated threat, on its own
sibling constant. The line declares the loss as `+N unknown`, a count of buckets, so the operator
cannot tell that the hidden one was fleet's own word.

The gate's further receipts, which I did **not** re-drive (BELIEVED, from `w51-gdtype`):

- the exemption docstring's ground is false three ways — `interrupted` (written by `cmd_interrupt`,
  its own shipped verb) and `dead-suspected` (written by the liveness recompute) are also outside
  `_ORDER`/`_LABEL` and also inside the capped region the docstring says only an attacker occupies;
- `test_the_cap_can_hide_only_names_the_attacker_chose` **passes unchanged under the X7 mutant it is
  cited as covering** (keep the last three instead of the first three), because its third assertion
  re-states `_bucket_order`'s own filter comprehension and therefore cannot fail for any mutant that
  keeps the filter.

**Not a regression** — the behaviour is driven at `920266c`, which is what keeps this off BLOCKING.
Gate's suggested remedy: exempt `FIELD_UNKNOWN` alongside `TYPE_FAULT`, **or** state in the docstring
which fleet-authored names the cap may hide and why; and replace the tautological assertion with one
that distinguishes the two orderings.

### QUEUE ITEM 2 — MINOR — `_reset_clock` is not total over types, and its docstring says it is

Contract: *"Any other TYPE → `_safe`'s refusal word."* False for **five falsy non-strings**, because
`if not iso: return ""` sits **above** the `try`. **MEASURED on `a70b1ab`:**

```
  _reset_clock(int       ) -> '?type'
  _reset_clock(int-zero  ) -> ''      <<< non-string, no refusal word
  _reset_clock(float-zero) -> ''      <<<
  _reset_clock(bool-false) -> ''      <<<
  _reset_clock(list-empty) -> ''      <<<
  _reset_clock(dict-empty) -> ''      <<<
  _reset_clock(none      ) -> ''
```

`limit_reset_at: []` and `limit_reset_at: null` render byte-identical — the P1-13 property this slice
already spent a MAJOR on, and exactly the distinction `FIELD_UNKNOWN`'s own comment calls *"a
different fact"*. Small blast radius: the rendered word is `reset?`, honest about not knowing, and no
attacker text reaches the screen. What is wrong is the docstring's universal quantifier.

### QUEUE ITEM 3 — MINOR — `_safe`'s refusal path ignores its own `limit`

`_safe(text, limit=_FIELD_LIMIT)` promises *"Bounded, with `~` marking the cut"*; the refusal returns
before the bound is consulted. **MEASURED on `a70b1ab`:**

```
  _safe([1, 2], limit=3)  ->  '?type'   len=5
```

Five characters, whatever `limit` said — the one unbounded branch of a function whose contract is
"bounded". **Latent**: no call site passes `limit` today, so this is a trap for the next caller
rather than a live defect. It is filed because `_safe` is now the module's declared single place that
decides what a wrong-typed field looks like, and a second caller with a tighter bound is what that
centralisation invites.

---

## §5. SAFETY — what this lane touched

- **No `fleet` verb was invoked at all**, in any home, at any point. There is nothing to enumerate in
  the `FLEET_HOME IS NOT A FENCE` sense, because no fleet command ran. — MEASURED (no `fleet`
  invocation appears in this session's commands)
- `~/.claude/fleet-statusline-chain.json`: **ABSENT before, ABSENT after.** — MEASURED, checked at
  both ends.
- `~/.claude/fleet-homes.list`: **absent throughout**; never created, never appended to. — MEASURED
- `~/.claude/settings.json`: never written. No `fleet init` of any kind.
- **No ref other than `w51/dmerge` moved.** No push. `main` is still `75aa4eb`. No worktree was added
  or removed.
- The three input floors were measured in a **`git clone --local`** under the job's scratch
  directory, with detached checkouts. A clone was chosen over the existing `fleet-w50-mp` worktree
  (which sits at `4d78f6c`) specifically so that no other lane's worktree acquired `__pycache__` or
  `.pytest_cache` from my run, and over `git worktree add` so that this repository's
  `.git/worktrees/` was not modified either.
- Scratch files (classifier, lost-hunk checker, re-pointer, digest, the clone) live in
  `$CLAUDE_JOB_DIR/tmp` and are in no commit.

---

## §6. WHERE THIS BRIEF WAS WRONG

The brief predicted its own likeliest errors — *"that 12 conflicts is still the number; that
'all citation-only' survives re-derivation; that 31–36 is the true count rather than a lower bound;
and that one fixpoint pass will do it."* **All four of those predictions were wrong in the brief's
favour: every one of the four claims survived.** 12 was still 12, all twelve were citation-only, the
count landed at 31, and one pass reached fixpoint. That is worth stating plainly, because a brief
that hedges correctly and a brief that hedges reflexively look identical from inside.

What was actually wrong:

1. **"`w51-gdtype` reported this constant absent from the tree. It is present"** — the brief is
   **right**, and its instruction to verify in my own cwd is what makes it checkable.
   `CHECK_COUNT_DOCS = current_tree_docs()` is at `tests/test_doc_claims.py:506`, the exact line the
   brief names, and it is **30** files. — MEASURED. Not a defect; recorded because the brief asked to
   be doubted here and survived.

2. **The re-pin count's units are understated.** The brief says *"31–36 of 42 citations stale"* and
   frames the fixpoint requirement around that number. But the population it names — `:NNNN` — is
   **structurally incapable of including a range END**, since the oracle's scan is colon-keyed and
   `-8523` carries no colon. The brief warns about backwards ranges in the very next paragraph
   without noting that they are **not in the 42**. The true unit of work here was **31 starts + 1
   range end**, and "42" is the denominator of a different set. The brief's two halves are each
   correct and do not compose.

3. **"Resolve every conflict by reading the cited line and confirming what it actually points at."**
   Followed literally this is wasted work and mildly dangerous. At the conflict, *both* sides' digits
   are known-wrong by construction — computed against two trees, neither of which is the merged one.
   Reading them tells you only which of two wrong answers you prefer. The right move is the one the
   brief describes two sections later: resolve the conflict **without** deciding the citation, then
   pay all 42 once, from the merged tree, with the oracle as the judge. I did that. Under the literal
   reading, a lane that "confirms" `.their` looks diligent and ships 12 stale citations.

4. **"Assert `occurrences == 1` on each replacement"** is a weaker guard than it sounds, and is not
   the one that mattered. All 32 of my replacements satisfied it — including the one that was about
   to write `:8617-8523`, because `:8521-8523` genuinely occurs once on its line. What caught that
   was a **position** assert (does the text at this exact column still read what the plan said?). An
   occurrence count is blind to an earlier edit on the same line having already moved the ground.

5. **The floor arithmetic cannot be done from the numbers the brief supplies.** It gives `main`
   (4351) and `w51/dtype` (4489) but not the **merge base**, and the merged floor is
   `main + dtype − base`. Without `base` = 4238 the prediction is unfalsifiable arithmetic. Measuring
   it took a third full suite run. Any brief ordering a merged-floor prediction should hand over the
   base's floor, or say explicitly that measuring it is part of the job.

6. **The `docs/lanes/` exemption makes the floor property the brief teaches inapplicable here.** The
   brief's hard-won lesson — *"a docs-only change CAN move the floor"*, missed by exactly 4 — is
   real, and it is also **inert for this lane**: every `.md` this merge adds is a lane report, and so
   is this file. The warning is correct and the situation it warns about does not arise. Worth
   recording because the useful form of the lesson is the mechanism (`CHECK_COUNT_DOCS`, and which
   prefixes are exempt), not "docs can move the floor" — the latter would have had me predicting
   movement that a check of `_HISTORICAL_PREFIXES` rules out in one command.

7. **A brief-adjacent claim I could not confirm, stated as unresolved.** `BRIEF-TEMPLATE.md` reports
   the same declared pair measured as 25 by the supervisor and 26/31 by gate `w51-glaunch2` on the
   same day, unreconciled. My run says **25 anchored / 26 unanchored** at `75aa4eb` — consistent with
   the supervisor's number, and consistent with the gate's *unanchored* count being a different
   quantity, but the gate's **anchored 26** is reproduced by neither. I did not chase it; it is not
   this lane's job and it does not affect any number here. Flagged so the next reader knows the
   discrepancy is still open. — **BELIEVED**

## §7. WHERE THIS REPORT AND THIS LANE WERE WRONG

Three defects of my own, all caught in-run, all recorded because the shape outlives the incident.

1. **The conflict classifier's first version answered "12 of 12 FUNCTIONAL OVERLAP"** — the opposite
   of the truth — because it stripped `git merge-tree`'s `+` prefix from one side and left the diff's
   space prefix on the other, so every line differed by one column of indentation present in neither
   file. It was caught only because the answer was *implausible* against a prior I had been told to
   check rather than trust. **An instrument whose failure mode is a false alarm is not safe just
   because it is conservative:** the brief's escape hatch ("STOP and report") would have fired on a
   parser bug and cost the wave a lane.

2. **The re-pointer's "already a valid member" shortcut silently broke an `exactly=` group.** It was
   added to handle the `:1063` trio correctly, and it was correct for them; applied to the sid-union
   site it claimed 5 of 13 members and left the remaining 8 unresolvable through a cardinality check
   that no longer matched. Visible only because the tool **refuses** rather than guessing — a version
   that resolved ambiguity by picking something would have shipped 8 wrong citations, green.

3. **§0 of this report says the citation oracle is "20 fixed tests". It is 17.** I counted `def test_`
   lines instead of collecting them — the precise substitution the brief forbids for test-count
   deltas — inside the sentence arguing that a test count would not move. The correction is recorded
   at the point of the error rather than by editing it away.

---

## §8. STATE OF THE BRANCH

```
a70b1ab  fix(w51-dmerge): the fourth re-pin pass -- 31 of 42, plus the range END no census sees
f8ea89a  docs(w51-dmerge): the merged floor predicted, in a commit carrying no result
b058d1e  merge(w51): slice (d) -- 12 conflicts, all citations, re-derived rather than inherited
75aa4eb  (main) merge(w51): slice (e) -- ...
```

`w51/dmerge` vs `main`: 10 files, +5209 / −63. **4602 → 4587/14/1/0 on `py -3.13` and `py -3.10`.**

**LANDABLE.** It needs no further derivation to be pushed: the merge is paid, the citations are at
fixpoint, both floors are green and predicted, and the three inherited findings are specified above
as the successor's queue rather than left to be rediscovered.
