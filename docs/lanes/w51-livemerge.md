# `w51-livemerge` — merging `w50/live`, and paying the citation cost the merge creates

| | |
|---|---|
| Branch | `w51/livemerge` |
| Started at | `a914708` (= `main` at dispatch) |
| Merged | `w50/live` @ `f0550a6`, merge-base `4d78f6c` |
| Lane | merge-prep. **`bin/fleet.py` NOT modified — by the merge or by me.** |
| Interpreters | `py -3.13`, `py -3.10` |
| Live fleet verbs run | **NONE.** No `fleet init`, no write to `~/.claude/settings.json`, no append to `~/.claude/fleet-homes.list`. |
| Fence | commits on `w51/livemerge` only; no push; `main` untouched; no other ref moved. |

Every line is tagged **MEASURED** (I ran it in this lane and read the output) or **BELIEVED**
(reasoning, or arithmetic over numbers I did not myself produce).

---

## 3. FLOOR PREDICTION — written and committed BEFORE the run

**This section is committed in a commit that contains no floor results.** The run happens after it.

### 3.1 What the merge can move, derived statically

**MEASURED** — the merge adds exactly three files and changes nothing else:

```
git diff --stat 4d78f6c w50/live
 docs/lanes/w50-live.md         | 1659 ++++++
 tests/test_liveness_readers.py | 1157 ++++++
 tools/mutate_liveness.py       |  220 ++++
 3 files changed, 3036 insertions(+)
```

So there are exactly three routes by which the floor could move, and I derived each **without
running the suite**:

1. **`tests/test_liveness_readers.py` — the only route that is open.** **MEASURED:** the file
   contains **no `parametrize`** at all (`grep -n 'parametrize' tests/test_liveness_readers.py`
   → no output), so its collected count is a fixed number that cannot differ between
   interpreters through the derived-population mechanism. **MEASURED** in this tree on `py -3.13`:
   `34 passed`, no skips, no xfails.
2. **`tools/mutate_liveness.py` — closed.** `pytest.ini` declares only markers, no `testpaths`;
   collection is by filename pattern and `mutate_liveness.py` matches neither `test_*.py` nor
   `*_test.py`.
3. **`docs/lanes/w50-live.md` — closed, and this is the route the brief flags.**
   `CHECK_COUNT_DOCS` (`tests/test_doc_claims.py:506`, `current_tree_docs()`) is every tracked
   `*.md` minus `_HISTORICAL_PREFIXES`, and **MEASURED** at `tests/test_doc_claims.py:445-447`
   that tuple begins `"docs/lanes/", "docs/reviews/", …`. Both new markdown files this branch
   adds — `docs/lanes/w50-live.md` and this report — are under `docs/lanes/`, so **neither enters
   `CHECK_COUNT_DOCS` and the two pins parametrised over it gain no cases.** `ENTRY_DOCS` is a
   literal tuple; `test_receipts.py` globs `docs/specs/*.md` only; `HOOK_SCRIPTS` is `bin/hooks/*`.
   **Predicted docs contribution: 0.**

### 3.2 The arithmetic, from the merge base

Two inputs I did **not** measure (both **BELIEVED**, inherited): `main` @ `a914708` =
**4602 collected → 4587 / 14 / 1 / 0**, from the dispatching brief; `w50/live` @ `f0550a6` =
**4257 / 14 / 1** = **4272 collected**, from that branch's own report.

Route A — forward from `main`:

```
main a914708                        4602 collected  (4587 / 14 / 1 / 0)
+ tests/test_liveness_readers.py    +  34 collected, all passing
= merged                            4636 collected  (4621 / 14 / 1 / 0)
```

Route B — from the merge base, which is what the brief asks for:

```
w50/live f0550a6 on base 4d78f6c    4272 collected  (4257 / 14 / 1)
- its own new test file             -  34
= base 4d78f6c                      4238 collected  (4223 / 14 / 1)
+ slice (d), i.e. main - base       + 364            (4602 - 4238)
+ w50/live's new test file          +  34
= merged                            4636 collected  (4621 / 14 / 1 / 0)
```

**The two routes agree at 4636.** Route B additionally *derives* slice (d)'s own test
contribution as **+364 collected**, which nothing told me and which is a falsifiable by-product
of the prediction: if the merged floor lands at 4636, that number was right too.

### 3.3 THE PREDICTION

**Δ against `main` — this is the real claim, and it does not depend on either inherited number:**

> **+34 collected, +34 passed, +0 skipped, +0 xfailed, +0 failed**, identically on `py -3.13` and
> `py -3.10`.

**Absolute, conditional on the inherited `main` = 4602 → 4587 / 14 / 1 / 0:**

> **4636 collected → 4621 passed / 14 skipped / 1 xfailed / 0 failed, on BOTH interpreters.**

**Stated so it can be scored honestly:** the Δ is mine and I own it. The absolute inherits the
brief's measurement of `main`, which I did not re-run — I have one worktree and it is not on
`main`. **If the absolute misses but the Δ holds, the inherited number was wrong, not the
prediction**; if the Δ misses, I was wrong.

**Where I expect to be wrong, if I am:** the `py -3.10` count. `tests/test_self_citations.py`'s
own docstring records that 3.10 emits one `STRING` token for an f-string while 3.12+ splits it
into `FSTRING_*`, so a population derived by tokenising source **can** differ across this
project's two floor interpreters. I checked that the new file has no `parametrize`, but I have
**not** run it on 3.10, and a skip-guard keyed on `sys.version_info` would move `skipped` without
moving `collected`. **BELIEVED, not measured: 14 skipped on both.**

**Not predicted, because it is not a floor claim:** nothing in this branch touches `bin/fleet.py`,
so `tests/test_self_citations.py` must stay at **17 passed** — it was 17 before the merge and 17
after the re-pins (§2), and a change there would mean I broke something I never edited.
