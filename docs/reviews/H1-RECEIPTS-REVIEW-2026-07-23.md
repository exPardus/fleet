# H1 hostile review — `verify_receipts` parser-evasion fix

**Under review:** `2e4279e` "fix: verify_receipts fails on receipt-shaped text it never parses (H1)"
(diff `4dab64f..2e4279e`: `tools/verify_receipts.py` +380/-23, `tests/test_receipts.py` +304, 13→35 tests).

**Vantage.** Worktree `C:\proga\fleet-mf-h1-review`, branch `mf/h1-review` at `2e4279e`,
Windows 10, `py -3.13` and `py -3.10`, Git-Bash `C:\Program Files\Git\bin\bash.exe`.
Read-only against the branch: this review edits nothing but this file, and the review
worktree was verified clean (`git status --porcelain` empty) before and after.

**Method for fault injection.** Every mutation was applied in a **scratch detached worktree**
(`git worktree add --detach … 2e4279e`), never in the review worktree. Each mutation restores
with `git checkout --` in a `finally:` and asserts a byte-identical restore before the next runs.
The scratch worktree was removed at the end. One mistake is disclosed for the record: an early
batch was launched in parallel against a single scratch worktree, which is unsound (mutations
clobber each other); it was discarded, the tree re-verified clean, and every mutation re-run
serially. All results below come from the serial runs.

---

## Verdict

The fix is **architecturally right and does what it claims on its founding incident.** The
reject-rather-than-absorb decision is well argued and correct; the founding artifact goes red;
no prior test was weakened or deleted; both interpreters are green; there are zero false
positives on the enforced corpus.

It is **not yet sound**, on one critical and three major grounds. The headline result: **two
single-line edits, each of which the 35-test suite passes, together restore the exact
founding-incident failure mode** — a receipt block whose pasted output is flatly false reports
`0 failures, 0 warnings` under `--strict`. The suite is load-bearing for the shapes the founding
artifact happens to contain and thin everywhere else.

**`fix-list(H1-C1, H1-M1, H1-M2, H1-M3, H1-m1, H1-m2, H1-m3, H1-m4)`**

---

## Findings

| id | sev | one line |
|----|-----|----------|
| **H1-C1** | CRITICAL | The orphan-block geometry has **zero** test coverage; two mutually-redundant paths guard it, neither individually tested. Compound mutation → founding bug restored, suite green. |
| **H1-M1** | MAJOR | A **tab** after `$` / `# at` / `# volatile` is neither parsed nor reported. Silent skip, exit 0 — the H1 class is not closed, contrary to the docstring. |
| **H1-M2** | MAJOR | A CommonMark 4-backtick **inline code span** is misread as a fence, silently losing a real receipt from parsing. A live instance is already in this repo. |
| **H1-M3** | MAJOR | `blocks_yielding_nothing()` is vacuous: never called by `check()`, and every test asserts it returns `[]`. The advertised 34-vs-37 reconciliation is never proven able to fire. |
| **H1-m1** | MINOR | The `marker` shape is untested — killing `_MARK_SHAPE_RE` leaves the suite green. |
| **H1-m2** | MINOR | The `stray-directive` shape is untested. |
| **H1-m3** | MINOR | The non-vacuity arm of `_extraction_seed` is untested. |
| **H1-m4** | MINOR | `self_test()`'s chaining into `self_test_extraction()` is untested — `--self-test` can silently lose its H1 half. |
| **H1-m5** | MINOR | `**$ cmd**` (bold-wrapped) is not detected. |
| **H1-m6** | INFO | The summary line reads `34/34 parsed receipts reproduce exactly (… 16 FAILED)` — internally contradictory at a glance, which is the founding incident's own failure mode. |
| **H1-i1** | INFO | Disposition of `portability.md:334` (check 6) — confirmed, see below. |

---

## Check 1 — founding-incident replay, independently

**RED, as required.** Replayed the real artifact out of git, not the builder's fixture:

```
$ git show 4e540f8~1:docs/specs/three-tier-command.md > founding.md
$ py -3.13 tools/verify_receipts.py --strict founding.md ; echo "exit $?"
…
34/34 parsed receipts reproduce exactly (34 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 16 FAILED)
16 EVASION(S): receipt-shaped text the parser never classified …
exit 1
```

And the **pre-fix** tool on the same bytes, which reproduces the quoted founding line exactly:

```
$ git show 4dab64f:tools/verify_receipts.py > verify_old.py
$ py -3.13 verify_old.py --strict founding.md ; echo "exit $?"
34/34 receipts reproduce exactly (37 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
exit 0
```

The docstring's quotation of the founding incident is accurate, not reconstructed.

### The 16-vs-4 delta: **real, not over-matching**

The two numbers count different things. There are **4 evading blocks**; each contributes
**4 receipt-shaped lines** — an opening fence, a `# at` pin, a `$ ` command, a closing fence —
so 4 × 4 = 16. The pasted *output* lines inside those blocks are correctly **not** flagged.

I verified this with an independently written census (`census.py`) that deliberately does **not**
reuse `_GUTTER_RE` and strips a *broader* gutter class (any run of non-word characters: any depth
or mix of `>`, `-`, `*`, `+`, digits, `.`, `)`, `|`, tabs). It agrees line-for-line:

| block | gutter | fence | pin | command | output (correctly not flagged) |
|-------|--------|-------|-----|---------|--------------------------------|
| §7.2 B1 | `> ` blockquote | 519, 523 | 520 | 521 | 522 |
| §10.4 B5 | 2-space list indent | 783, 787 | 784 | 785 | 786 |
| §11.2 B3 | 2-space list indent | 909, 914 | 910 | 911 | 912–913 |
| §11.3 B4 | 2-space list indent | 954, 958 | 955 | 956 | 957 |

All 16 are genuine receipt-shaped lines inside those four blocks. **Each of the 16 is receipted
above by line number and gutter kind.** My broader census found **no seventeenth** gutter-hidden
shape in the artifact.

The block arithmetic also reconciles independently, which is worth recording because nobody
reconciled it during the incident: the artifact has **68 column-0 fence markers = 34 blocks**,
plus the 4 gutter blocks = **38 present**. The pre-fix tool printed **37** because `lstrip()`
strips spaces but not `>` — it counted the 3 indented blocks and missed the blockquoted one.
`34 + 3 = 37`. Exactly as the docstring claims.

One deliberate non-match, correctly handled: line 27 carries a bare `` `$ ` `` marker in prose.
`_CMD_SHAPE_RE`/`_INLINE_CMD_RE` require a non-space after `$ `, so it is exempt. Correct.

---

## Check 2 — fault injection

**20 mutations, run serially: 14 RED, 6 SURVIVED.** Plus one compound (below).

| id | mutation | result | caught by |
|----|----------|--------|-----------|
| M1 | `_GUTTER_RE` never strips | **RED** (9 failed) | `test_harness_can_fail`, `…_goes_red`, 4× `…evasion_shape…` |
| M2 | `_INLINE_CMD_RE` never matches | **RED** (1) | `test_every_evasion_shape_is_caught[inline-span]` |
| M3 | invert strict/warn arm for evasions | **RED** (9) | `…fails_strict_check`, 7× shapes, `…unterminated…` |
| M4 | drop the unterminated-fence case | **RED** (1) | `test_unterminated_fence_is_an_error` |
| **M5** | **neuter non-vacuity assert in `_extraction_seed`** | **SURVIVED** | — |
| M6 | `_shape_of` always returns `None` | **RED** (10) | 10 tests |
| M7 | `check()` never scans for evasions | **RED** (9) | 9 tests |
| M8 | `_evading_fences` returns `[]` | **RED** (1) | `test_founding_artifact_goes_red` |
| **M9** | **`blocks_yielding_nothing` always `[]`** | **SURVIVED** | — |
| **M10** | **`_parse_block` stops reporting strays** | **SURVIVED** | — |
| M11 | pre-fix `lstrip()` fence detection | **RED** (1) | `test_founding_artifact_goes_red` |
| **M12** | **`self_test` no longer chains to extraction seed** | **SURVIVED** | — |
| M13 | `_PIN_SHAPE_RE` never matches | **RED** (1) | `test_founding_artifact_goes_red` |
| **M14** | **`_MARK_SHAPE_RE` never matches** | **SURVIVED** | — |
| M15 | `_CMD_SHAPE_RE` never matches | **RED** (1) | `test_founding_artifact_goes_red` |
| M16 | `_FENCE_MARK_RE` never matches | **RED** (1) | `test_founding_artifact_goes_red` |
| M17 | `_DIRECTIVE_SHAPES` emptied | **RED** (10) | 10 tests |
| **M18** | **`scan_evasions` skips all fenced lines, not just classified** | **SURVIVED** | — |
| M19 | `FOUNDING_ARTIFACT` → an empty doc (`LICENSE`) | **RED** (3) | `…is_the_real_thing`, `…goes_red`, `…fails_strict_check` |
| M20 | `FOUNDING_ARTIFACT` → the post-fix (clean) tree | **RED** (3) | same three |

Sample tail (M11, the most important single RED — it is the original bug restored):

```
$ py -3.13 -m pytest tests/test_receipts.py -q -rf
FAILED test_founding_artifact_goes_red - AssertionError: gutter-hidden fence markers not reported: [783, 787, 909, 9…
1 failed, 34 passed in 12.59s
```

### H1-C1 (CRITICAL) — the orphan-block geometry is untested, and two edits restore the bug

M10 and M18 each survive **because they are mutually redundant**, not because either is
unnecessary. Two independent code paths report a receipt directive hidden behind a gutter
*inside a column-0 fence*: `scan_evasions`'s `orphaned` path, and `_parse_block`'s `stray` path.
Kill one and the other still reports. **Kill both and the geometry goes dark.**

That geometry is not exotic — it is the founding incident with the fence at column 0:

```
$ py -3.13 probe_compound.py
COMPOUND M10+M18 on orphan-block geometry:
  scan_evasions: []
  blocks_yielding_nothing: [(1, 5)]
  check(strict): 0 failure(s), 0 warning(s)  <- receipt with FALSE output
  baseline for comparison:
  check(strict): 2 failure(s), 0 warning(s)
```

The document under test is a column-0 fence whose every directive sits behind a 2-space gutter,
with deliberately false pasted output. Baseline reports 2 failures; the compound reports **none**,
and would exit 0. And the suite does not notice:

```
$ py -3.13 -m pytest tests/test_receipts.py -q     # with M10+M18 both applied
35 passed in 15.29s
rc= 0
```

**This is the founding incident, reachable again, with a green suite.** The founding artifact
cannot catch it because all four of its blocks are *gutter-fenced* (the fence marker itself is
indented or quoted) and are therefore caught by `_evading_fences` — a third, different path. The
orphan geometry — **column-0 fence, gutter-hidden contents** — appears in no test at all.

Note `blocks_yielding_nothing` **does** still return `[(1, 5)]` under the compound, i.e. the
information needed to catch this exists and is discarded. See H1-M3.

**Fix:** add a test asserting the orphan geometry fails under `--strict`, and assert *both*
mechanisms independently (parametrise, or assert the specific shapes `pin`/`command` and
`stray-directive` are each produced by their own path). A single test of the geometry kills M10,
M18 and the compound together.

### H1-M3 (MAJOR) — `blocks_yielding_nothing()` is a vacuous check

M9 survives. The function is **never called by `check()`** — only by
`test_every_fenced_block_is_accounted_for`, which asserts it returns `[]`, as does
`test_indented_code_snippet_is_not_an_evasion`. Every assertion in the suite is satisfied by a
function that unconditionally returns `[]`. The docstring calls it "the checkable form" of the
reconciliation the founding incident failed to make; nothing proves it can ever fire. It can:

```
$ py -3.13 probe.py
M9 PROBE -- can blocks_yielding_nothing() ever report anything?
doc: '```\n  # at 235421e…\n  $ echo hidden\n  hidden\n```\n'
blocks_yielding_nothing -> [(1, 5)]
parse -> 0 receipts, 0 unclassified, 1 blocks
```

**Fix:** one positive assertion (`== [(1, 5)]` on the doc above). Consider also wiring it into
`check()` so the reconciliation is enforced at runtime, not only in the suite.

### H1-m1 … H1-m4 (MINOR) — four untested surfaces

* **H1-m1 / M14** — `_MARK_SHAPE_RE` killed, suite green. The `marker` shape is real and
  load-bearing: a loose `# volatile:` in prose is an evasion the tool does detect
  (`MARKER_ONLY check(strict) : 1 failure(s)` baseline → `0 failure(s)` mutated). It survives
  because both `EVASION_SHAPES` fixtures that contain a marker (`unfenced`, `indent4-unfenced`)
  also contain a `$ ` command, so the command shape carries the test. **Fix:** a marker-only fixture.
* **H1-m2 / M10** — `stray-directive` is in `_EVASION_DETAIL` and fires in practice
  (`scan_evasions -> [(2, 'stray-directive')]`) but appears in no test. Covered by the H1-C1 fix.
* **H1-m3 / M5** — the `if after >= before: … INCONCLUSIVE` arm of `_extraction_seed` can be
  deleted with the suite green. It is a guard on a guard; I did **not** construct a working
  exploit, and I grade it MINOR rather than critical on that basis — but it is the exact
  "vacuous pass" class this campaign has now shipped three times.
* **H1-m4 / M12** — `self_test()` ends `return self_test_extraction(text, root)`. Replace that
  with `return True` and the suite stays green, because `test_self_test_proves_extraction_completeness`
  calls `self_test_extraction` **directly** and `test_harness_can_fail` only asserts `self_test`
  is truthy. The `--self-test` CLI contract — the thing CLAUDE.md tells operators to run before
  trusting a green run — could silently lose its entire H1 half. **Fix:** assert the chaining.

### Mutations that pleasingly did *not* survive

M13/M15/M16 (pin, command and fence shape regexes each blinded) are all caught, but **only** by
`test_founding_artifact_goes_red`'s `len(evasions) >= 16`. That single assertion is carrying
three shapes. It is a strong assertion and I am not asking for it to be replaced — but it means
the per-shape coverage is thinner than the 35-test count suggests.

---

## Check 3 — false-positive sweep

**Zero false positives on the enforced corpus.** All 13 `docs/specs/**` files plus all 5
`docs/superpowers/specs/**` files, including every one that mentions `$` in prose:

```
docs/specs/claim-nonce.md            lines= 2383 $lines=  69 blocks= 55 receipts= 59 EVASIONS=  0 orphans=0
docs/specs/three-tier-command.md     lines= 1122 $lines=  40 blocks= 39 receipts= 39 EVASIONS=  0 orphans=0
docs/specs/portability.md            lines=  410 $lines=   9 blocks=  2 receipts=  1 EVASIONS=  0 orphans=0
docs/specs/terminal-surface.md       lines=  277 $lines=   6 blocks=  3 receipts=  0 EVASIONS=  0 orphans=0
… (18 files total)
TOTAL EVASIONS across sweep: 0
```

I widened the sweep to **all 97 markdown files in the repo**, since 18 mostly-`$`-free files is a
weak stress test. 20 evasions appear, all in the unenforced `docs/reviews/`. Adjudicated:

* **12 × `inline-command`** — prose *quoting the receipt grammar itself*, e.g.
  `` `$ cmd` `` and `` `$ echo "exit $?"` ``. These are **false positives in spirit**: the
  document describes the notation rather than claiming to have run it. They are harmless today
  because reviews are unenforced, but they mean the doctrine **cannot be extended to
  `docs/reviews/**` as-is**, which is worth knowing before someone tries. The specs dodge this
  only by using the exempt bare `` `$ ` `` marker.
* **6 × `gutter-fence` + `command`** — e.g. `MD-CONTRACT-REVIEW-2026-07-17.md:1145-1147`, a real
  2-space-indented fence holding two `$ ` commands. **True positives** by the tool's own rule.
* **1 × `unterminated-fence`** — `THREE-TIER-REDRAFT-REVIEW-2026-07-23-spec.md:478`. This one is
  a genuine bug; see H1-M2.

**This document trips it too, which is the point.** Scanning this very file reports
`[(254, 'inline-command'), (268, 'gutter-fence'), (327, 'inline-command'), (476, 'gutter-fence')]`
— two prose mentions of the receipt grammar, one indented quotation of the offending line 478,
and one illustrative ```` ```python ```` block. All four are false positives on a document doing
nothing wrong. `docs/reviews/**` is outside the enforced set (`_specs()` globs `docs/specs/*.md`
only), so nothing breaks — but a review of the evasion detector being unable to *describe* the
evasion detector without tripping it is the clearest statement of the H1-M2 / inline-command
false-positive cost I can offer.

### H1-M2 (MAJOR) — a CommonMark inline code span is misread as a fence

Line 478 of the sibling review is:

    ```` ```\n# at ```` at column 0, so it also reported 34/34 in r2 and did **not** …

That is a **4-backtick inline code span** — CommonMark's standard way to write literal triple
backticks — and it is legal, ordinary Markdown that renders inline. `parse_doc` tests
`raw.startswith("```")`, which is true for four backticks, so it opens a phantom block.
CommonMark is explicit that a backtick fence's info string **may not contain a backtick**;
that rule is exactly what distinguishes the two, and the harness does not implement it.

This is gap 3 in a second guise, and it costs a real receipt:

```
$ py -3.13 trap.py
clean                          blocks=2 receipts=['echo one', 'echo two'] evasions=[] strict_failures=0
with 4-backtick inline span    blocks=2 receipts=['echo one'] evasions=[(10, 'pin'), (11, 'command'), (13, 'unterminated-fence')] strict_failures=3
```

The second receipt **stops being parsed**. To the fix's great credit it **fails closed** — three
evasions, `--strict` red — so this is *not* a green-while-blind hole, and the H1 promise ("a
receipt that stops being parsed is reported") holds. But the diagnosis names the wrong thing, and
by the task's own criterion a false positive on legitimate text is MAJOR: an author whose valid
Markdown is rejected with `unterminated-fence` learns to mangle their prose, which is precisely
how a check gets routed around.

**Fix (verified).** Add the info-string rule at the three sites that classify a fence:

```python
def _is_fence(raw):
    """CommonMark: a backtick fence's info string may not contain a backtick."""
    if not raw.startswith("```"):
        return False
    return "`" not in raw.lstrip("`")
```

used in `parse_doc`, in `scan_evasions`'s `shapes` comprehension, and mirrored in `_shape_of`
(`return "gutter-fence" if "`" not in degutterred.lstrip("`") else None`). Verified:

```
SUITE rc= 0 | ['35 passed in 13.91s']
founding artifact evasions: 16
trap AFTER full fix: blocks= 2 receipts= ['echo one', 'echo two'] evasions= []
```

35 tests still pass, the founding artifact still goes red at 16, the trap document recovers both
receipts with zero evasions, and the sibling review's spurious finding disappears.

### H1-M1 (MAJOR) — the class is not closed: a tab after `$` is invisible

The module docstring declares "THE PARSER-EVASION CLASS (H1, **closed** 2026-07-23)" and CLAUDE.md
says "A receipt the harness cannot classify is a failure, never a skip." Both are false for a tab:

```
MISSED  bare TAB-after-$, unfenced       receipts=0 evasions=[] fail=0 warn=0
MISSED  bare TAB-after-$, gutter         receipts=0 evasions=[] fail=0 warn=0
MISSED  bold command, unfenced           receipts=0 evasions=[] fail=0 warn=0
```

`_CMD_SHAPE_RE = ^\$ +\S`, `_PIN_SHAPE_RE = ^# +at +…` and `_MARK_SHAPE_RE = ^# +…` all require
literal **spaces**; `_parse_block` matches `raw.startswith("$ ")`. So `$<TAB>grep -c foo` is
**neither parsed nor reported** — a silent skip, exit 0. In any Markdown renderer it is
indistinguishable from `$ grep -c foo` to a reader. This is the same class as H1, with a
different whitespace byte, and it is the one shape here that is genuinely green-while-blind.

**Fix (verified).** Accept horizontal whitespace, not just spaces, in the three shape regexes:

```python
_CMD_SHAPE_RE  = re.compile(r"^\$[ \t]+\S")
_PIN_SHAPE_RE  = re.compile(r"^#[ \t]+at[ \t]+(?:[0-9a-fA-F]{7,40}|HEAD|head|main|master)\b")
_MARK_SHAPE_RE = re.compile(r"^#[ \t]+(?:volatile|live)\b")
```

Leaving `_parse_block` alone is correct — the shapes then become **evasions**, which is the
fix's own reject-not-absorb doctrine applied consistently. Verified:

```
SUITE rc= 0 | ['35 passed in 15.42s']
founding artifact evasions: 16
  bare TAB-after-$: evasions=[(1, 'command')] fail=1
  TAB gutter:       evasions=[(1, 'command')] fail=1
  TAB pin:          evasions=[(1, 'pin'), (2, 'command')] fail=2
  spec sweep after fix: 0 file(s) with evasions (expect 0)
```

**H1-m5**, same probe: `**$ cmd**` is undetected, because `_GUTTER_RE`'s bullet alternative
requires whitespace after `-*+` and so does not strip `**`. Lower value than the tab case
(bold-wrapping a command is unusual), but it is receipt-shaped text executed by nothing.

---

## Check 4 — seed-test integrity

**No prior test was weakened or deleted.** The entire test diff removes exactly **one** line:

```
$ git diff 4dab64f..2e4279e -- tests/test_receipts.py | grep -E "^-" | grep -v "^---"
-    return any(line.startswith("# at ")
```

and that line was **strengthened**, not weakened — `_is_enforced` became gutter-blind
(`_GUTTER_RE.sub("", line).startswith("# at ")`), which *broadens* the enforced set so a spec
whose every receipt is indented can no longer drop out of enforcement. Set comparison of test
function names before/after: **0 removed, 14 added.**

**The fixture is read from git, never a committed copy.** `_founding_artifact` calls
`vr._git(REPO, "show", "4e540f8~1:docs/specs/three-tier-command.md")`. There is no
`tests/fixtures/` directory and no committed transcript of the artifact; the only occurrence of
the artifact's marker string in `tests/` is the non-vacuity anchor
`assert 'name = f"sup|{successor_inc}|successor"' in text`. An absent object is an assertion
failure, not a skip.

**The non-vacuity assertion genuinely fires.** Both mutations the task asks for go RED:

```
RED  M19: FOUNDING_ARTIFACT repointed at an empty doc (LICENSE)
     FAILED test_founding_artifact_is_the_real_thing - AssertionError: the founding artifact does not carry the 8 gutter-hidden fe…
     FAILED test_founding_artifact_goes_red - AssertionError: the founding artifact reports clean …
     FAILED test_founding_artifact_fails_strict_check - AssertionError: strict check() on the founding artifact must fail
     3 failed, 32 passed

RED  M20: FOUNDING_ARTIFACT repointed at the POST-fix (cleaned) tree — same 3 failures
```

M20 is the sharper of the two: pointing the fixture at today's *fixed* `three-tier-command.md`
fails, so the test cannot pass on a document that no longer carries the defect.

---

## Check 5 — both interpreters

Full suite, not just `test_receipts.py`:

```
$ py -3.13 -m pytest -q
1406 passed, 8 skipped in 74.92s (0:01:14)

$ py -3.10 -m pytest -q
1406 passed, 8 skipped in 76.11s (0:01:16)
```

Identical counts on both. The 3.10 floor holds; the `tarfile` `filter="data"` fallback
(`TypeError` on <3.12) is exercised on 3.10 without incident.

---

## Check 6 — disposition of `portability.md:334`

**CONFIRMED, and worse than reported.** The builder flagged it as an unpinned receipt in an
unenforced file. Both halves hold:

```
$ py -3.13 tools/verify_receipts.py --strict docs/specs/portability.md
FAIL  line 334 [UNPINNED]: grep -rn "probe_liveness(\|pid_alive(" tests/ --include=*.py
      UNPINNED: no `# at <sha>` and not marked `# live` -- would be checked against the working tree …
0/1 parsed receipts reproduce exactly (2 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 1 FAILED)
```

The file is in `UNENFORCED`, so the suite never runs this. The additional finding: **the block
would fail even if pinned**, because the pasted text is not the command's output. Its own prose
says the sites were "enumerated by `grep` at `9b5954d`, not by reading". Running exactly that:

```
$ git archive --format=tar 9b5954d | tar -xf - -C /tmp/t9 && cd /tmp/t9
$ grep -rn "probe_liveness(\|pid_alive(" tests/ --include=*.py | wc -l
17
$ grep -rn "probe_liveness(\|pid_alive(" tests/ --include=*.py | head -3
tests/test_cli.py:1012:    def test_stays_working_when_pid_alive(self, isolated_home):
tests/test_core.py:371:        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True
tests/test_core.py:377:        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True
```

The real command emits **17 literal lines**; the document pastes a 4-line comma-joined roll-up
with `# 10x fleet.pid_alive(...)` annotations. Pinning it makes that explicit:

```
pinned @9b5954d -> 1 failure(s)
  line 335: grep -rn "probe_liveness(\|pid_alive(" tests/ --include=*.py
    output line 1
      EXPECTED: 'tests/test_core.py:371,377,383,387,391,396,408,413,418,427     # 10x fleet.pid_alive(...)'
      ACTUAL:   'tests/test_cli.py:1012:    def test_stays_working_when_pid_al…'
```

**In fairness: the claim is true, only the form is false.** 17 matches minus the 4 the block
itself annotates as names/prose = **13 call sites**, exactly as the prose says, and the
`test_core.py` (10) + `test_resilience.py` (3) split is correct. This is not a wrong claim; it is
a correct claim **wearing the costume of a transcript** — the precise thing the module docstring
calls "a fabrication that reads exactly like a receipt". The `UNENFORCED` entry's stated reason
is accurate. Also confirmed: the symbols are gone at HEAD
(`grep -c "def pid_alive\|def probe_liveness" bin/fleet.py` → `0`), so the block can never be
meaningful against the working tree.

**Recommendation — demote, do not enforce.** Strip the `$ ` prefix and relabel the block as an
explicit hand-summary (e.g. "13 call sites at `9b5954d`, summarised:"), so it stops impersonating
a transcript. This is the cheapest option, removes the fabrication surface, and is honest about a
`[SUPERSEDED]` document. Enforcing it properly (pin `# at 9b5954d` + paste the literal 17 lines)
is defensible but spends real effort on a superseded spec for no downstream consumer. Leaving it
exactly as-is is the one option I would argue against: it is the only `$ `-shaped block in the
corpus that the harness parses, reports, and then nobody ever runs.

---

## What is right, and should not be relitigated

* **Reject-rather-than-absorb is the correct call**, and the three grounds given for it
  (a gutter changes what the reader is told; absorbing leaves the founding artifact green;
  de-guttering expected output creates a new correctness surface) are sound. I tried to find a
  case where absorbing would be better and did not.
* **The founding artifact as a git-read fixture** is the right shape, and M19/M20 prove it is
  not vacuous.
* **`_evading_fences` judging a fence by its contents** rather than flagging every indented
  ```` ```python ```` block is correct, and `test_indented_code_snippet_is_not_an_evasion`
  defends the right thing. Zero false positives on the enforced corpus is a real result.
* **Evasions counted apart from the receipt fraction** (rather than folded into the numerator)
  is right; folding them in drove the numerator negative.
* **The `RECEIPT_FLOOR` / `UNENFORCED` / `test_every_spec_is_classified` triangle** is a genuinely
  good pattern — exclusion is explicit and reviewable rather than invisible.

---

## Recommended fix order

1. **H1-C1** — one test for the orphan-block geometry, asserting both paths independently.
   Kills H1-m2 and the compound with it. *(blocking)*
2. **H1-M1** — three regexes to `[ \t]+`; verified green above. *(blocking — the class is
   advertised as closed and is not)*
3. **H1-M2** — `_is_fence()` at three sites; verified green above. *(blocking — false positive
   on legal Markdown, live instance already in-repo)*
4. **H1-M3** — one positive assertion on `blocks_yielding_nothing`; consider calling it from
   `check()`.
5. **H1-m1, H1-m3, H1-m4** — a marker-only fixture; a test for the `INCONCLUSIVE` arm; an
   assertion that `self_test` chains into `self_test_extraction`.
6. **H1-m5, H1-m6** — bold-wrapped commands; reword the summary line so `N/N … reproduce exactly`
   cannot sit in the same sentence as `16 FAILED`.
7. **H1-i1** — demote `portability.md:333-339` to an explicit hand-summary.

Nothing here asks for the design to change. The mechanism is right; its test surface is thinner
than 35 tests implies, and two regexes are imprecise.

---

**`fix-list(H1-C1, H1-M1, H1-M2, H1-M3, H1-m1, H1-m2, H1-m3, H1-m4)`**
