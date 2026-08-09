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
