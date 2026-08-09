# w51-dtype — the statusline render made total over field TYPES

**Subject:** `w51/dtype`, branched from `w50/gd2` @ `920266c` (which contains `w50/d` @ `5a47819`
plus that gate's verdict — `git merge-base --is-ancestor w50/d w50/gd2` returns 0, MEASURED).
**Discharges:** gate `w50-gd2`'s single MAJOR, its mutant X4, and its X7 equivalence question.
**Fence held:** commits on `w51/dtype` only. No push, no merge, no other ref moved.

---

## 0. FLOOR PREDICTION — WRITTEN BEFORE THE FLOORS WERE RUN

This section is committed in a commit that contains **no results**. A missed prediction is a
STOP-and-report event.

| | predicted |
|---|---|
| collected, `py -3.13` | **4483** |
| collected, `py -3.10` | **4483** |
| passed | **4468** |
| skipped | **14** |
| xfailed | **1** |
| failed | **0** |

**Where 4483 comes from.** The base at `920266c` collects **4365** — measured on an extracted copy
of that commit, and equal to the number gate `w50-gd2` §7.4 reported, so the base is agreed rather
than assumed. This branch adds **118** collected tests, counted as parametrize PRODUCTS rather than
as `def test_` lines (32 defs were 42 tests once, and that gap was the whole distance between two
predictions being credible):

| class | tests | how |
|---|---|---|
| `TestAForeignHomeCannotEraseTheOperatorsRow` | 83 | 10 + 1 + 1 + (10×2) + (5×10) + 1 |
| `TestTheNarrowingComesBeforeTheSanitiser` | 16 | 1 + 1 + 1 + 10 + 1 + 1 + 1 |
| `TestTheTierFieldIsTotalToo` | 13 | 10 + 1 + 1 + 1 |
| `TestTheOverflowCounterIsRenderedInColour` | 6 | six unparametrized |
| **total** | **118** | |

`4468 + 14 + 1 = 4483`. The skipped and xfailed counts are predicted UNCHANGED: nothing in this
branch adds a skip, an xfail, or a platform guard.

---

*(Results, findings and the WHERE THIS BRIEF WAS WRONG section are appended after the floors run.)*
