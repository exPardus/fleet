> **RESCUED REPORT — provenance header, added by lane `w47-durable` on 2026-08-09.**
>
> This report was recovered by the wave-47 retro-sweep from
> `C:/proga/fleet-w41-rc/state/journals/w41-rc.md`, where it was the **only** copy: it was in no
> commit on any branch (`git log --all` over the filename and over its content returns nothing),
> and it existed in no other worktree and not in the fleet home's own `state/journals/`. It would
> have died with that worktree, exactly as the `w44-ceil` report did. See `docs/lanes/README.md`.
>
> It describes branch `w41/rc-constant` (commit `1191833`). **Its presence here is not a claim
> that that branch merged** — as of the rescue it had not been. Nothing in the text below was
> edited; everything above this line is the rescue header.

---

# w41-rc — `verify_receipts.py`: INCONCLUSIVE vs FAILED

Worker `w41-rc`, worktree `C:/proga/fleet-w41-rc`, branch `w41/rc-constant`, forked from main at
`28df49b`.

## Goal

`tools/verify_receipts.py` collapses "the harness could not run the self-test" and "the harness
proved itself broken" into a single `False` → `rc=1`. Split them into a tri-state that propagates
through `self_test`, `self_test_extraction`, `_extraction_seed` and `main`, **without** turning any
genuine failure into silence.

## Status — COMPLETE. `1191833` on `w41/rc-constant`. Not pushed, not merged.

- [x] Re-derived the line map against my own tree — all nine hold, nothing moved
- [x] Baseline re-measured both interpreters: 3647 passed / 14 skipped / 1 xfail of 3662, rc=0
- [x] 43 tests written and watched RED (41/41 red for the right reasons, then +2)
- [x] Fix: tri-state through all four functions
- [x] Fault injection: 22 mutants, 22 killed (one genuine survivor found and closed)
- [x] Floors: 3690 / 14 / 1 of 3705, rc=0, **identical on py3.13 and py3.10**, predicted exactly
- [x] Adversarial self-gate — found two real defects in my own diff, both fixed

**Files changed (fences honoured):** `tools/verify_receipts.py`, `tests/test_receipts.py`,
`tests/test_verify_receipts_tristate.py` (new). `bin/hooks/stop_outcome.py`,
`tests/test_outcome_usage_provenance.py` and `tests/integration/test_native_pin.py` untouched.
No ref pushed, nothing merged, no fleet verb run, no `state/pin-pass.json` stamp.

**For a fresh session:** the work is done and committed. What is left is the operator's adversarial
gate before landing. Read §7 (my own gate) and §8 (what I did not prove) first — §8 names the three
places where a reviewer should push hardest.

## 1. Re-derived line map (at `28df49b`, `tools/verify_receipts.py`, 870 lines)

Every one of wave-40r's nine coordinates holds **exactly**. Nothing moved.

| brief | line at `28df49b` | statement | 40r class |
|---|---|---|---|
| :742 | 742 | `return False` after `SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate` | INCONCLUSIVE |
| :761 | 761 | `return False` after `SELF-TEST INCONCLUSIVE: could not locate the expected line to seed` | INCONCLUSIVE |
| :766 | 766 | `return False` after `SELF-TEST INCONCLUSIVE: mutation did not change the document` | INCONCLUSIVE |
| :777 | 777 | `return False` after `SELF-TEST FAILED: … did not catch a seeded paraphrase` | FAILURE |
| :781 | 781 | `return False` after `SELF-TEST FAILED: the seeded receipt also fails unmutated` | FAILURE |
| :794 | 794 | `return False` after `EXTRACTION SELF-TEST INCONCLUSIVE […]: the seed removed no receipt` | INCONCLUSIVE |
| :799 | 799 | `return False` after `EXTRACTION SELF-TEST FAILED […]: … NOTHING was reported` | FAILURE |
| :817 | 817 | `return False` after `EXTRACTION SELF-TEST INCONCLUSIVE: no classified fenced block to seed` | INCONCLUSIVE |
| :821 | 821 | `return False` after `EXTRACTION SELF-TEST INCONCLUSIVE: … already carries an evasion` | INCONCLUSIVE |
| :829-830 | 829-830 | the `ok` accumulator in `self_test_extraction` | — |
| :856-857 | 856-857 | `if args.self_test and not self_test(text, root): rc = 1` | — |

**Nothing to report as moved.** The map is ground truth at this commit.

## 2. What the brief did not say, and it is the load-bearing finding

Three pins in `tests/test_receipts.py` assert the *bool* the four functions return:

- `:274` `assert vr.self_test(target, REPO)` — truthiness
- `:843` `assert vr.self_test_extraction(doc, REPO)` — truthiness
- `:751`/`:763` `assert vr._extraction_seed(...) is False` — identity, **and it uses the same
  `is False` for one FAILURE case and one INCONCLUSIVE case**, i.e. the existing suite bakes in the
  very conflation this task removes
- `:786` `assert result is False` in `test_self_test_chains_into_extraction` — identity, on a spy

The first two are the trap. **Any tri-state whose members are all truthy** (a string constant, a
plain `enum.Enum`) leaves `assert vr.self_test(...)` passing on `INCONCLUSIVE` — the two strongest
anti-vacuity pins in the corpus go green-while-blind on the same day the tri-state lands. That is
exactly the "converts a real failure into silence" shape the brief warns about, arriving through the
*tests* rather than through `main()`.

So the verdict type **refuses to be coerced to bool** (`__bool__` raises `TypeError`). Any surviving
truthiness use fails loudly instead of silently choosing a branch.

## 3. Classification, argued from the code (two reclassifications)

I move **`:761` and `:766` from INCONCLUSIVE to FAILURE**. Both are self-consistency guards on the
harness, not "we could not run the check":

- `:761` — `line` comes from `r.expected`, and `_parse_block` appends `cur.expected.append(raw)`
  **verbatim** (`:585`). `r.line` is the 1-based document line of the receipt's own `$ ` line
  (`Receipt(cmd, n, volatile)`, `:567`, where `n` is the document line number). `self_test` searches
  `doc_lines[r.line:]` — 0-based, so it starts on the line *after* the `$ ` line, which is where that
  receipt's expected output begins. Parser and mutator both use `text.splitlines()` on the same
  `text`. So the expected line is **always** at or after the search start, and the guard can only
  fire if the harness's own line accounting is wrong. That is something known to be wrong.
- `:766` — reaching it requires `line.strip()` and `len(line.split()) > 1` (`:735`), so
  `line.split(" ")` has at least one word with `w.strip()` truthy, and the mutation is
  `w + "X"` or `"PARAPHRASED"` — both always change the word. The document therefore always changes.
  Firing means the mutator did not mutate.

Left as INCONCLUSIVE, with reasons:

- `:742` no clean multi-word receipt — a document of only volatile / single-word receipts genuinely
  offers nothing to seed. Nothing is known to be wrong.
- `:794` the seed removed no receipt — legitimately reachable: deleting the two fence lines of one
  block **re-pairs every later fence in the document**, so the parsed count can stay flat or rise in
  a multi-block document. The seed did not do what it intended; that is not evidence of a defect.
- `:817` no classified fenced block / zero receipts — nothing to seed.
- `:821` the document already carries an evasion — a seeded evasion proves nothing when an unseeded
  one is already reported. `check(--strict)` is what fails the document for that, not the self-test.

Direction of both reclassifications is **louder**, never quieter, so neither can create silence.

## 4. Design

`tools/verify_receipts.py` gains a three-member `Verdict` enum plus three exit-code constants, and
the four functions return `Verdict` instead of `bool`.

```
Verdict.PASSED       -> EXIT_OK           = 0
Verdict.INCONCLUSIVE -> EXIT_INCONCLUSIVE = 2
Verdict.FAILED       -> EXIT_FAILED       = 1
```

Four decisions worth defending:

1. **`Verdict.__bool__` raises `TypeError`.** See §2. A truthy tri-state silently voids
   `assert vr.self_test(...)`. Verified the override survives `enum.Enum` machinery on 3.10 and 3.13
   before relying on it.
2. **INCONCLUSIVE exits 2, not 0.** Non-zero, so `set -e` and `if rc:` gates keep firing — an
   unproven verifier is not a verified one, and CLAUDE.md's doctrine is that what the harness cannot
   classify is never a skip. What changes is only that the operator can now tell "your document gave
   my seed nothing to bite on" from "your verifier is lying". **1 remains the only code that means a
   defect**, so nothing that was rc=1-for-a-real-reason moved.
3. **`worse()` replaces the boolean accumulator.** `FAILED > INCONCLUSIVE > PASSED`, and both
   extraction seeds still run (`worse(a(), b())` is not short-circuiting, and neither was the
   `and` it replaced — the call was evaluated before the conjunction).
4. **`main()` keeps TWO accumulators** — `self_test_verdict` and `receipts_failed` — and takes the
   worse at the end. Folding them into one would let the printed self-test verdict absorb a receipt
   failure and read as though the HARNESS were broken when the DOCUMENT is; the operator acts
   differently on those. FAILED outranks INCONCLUSIVE wherever they meet, so an inconclusive
   self-test can never mask a receipt that did not reproduce.

`main()` also now prints `SELF-TEST VERDICT: <name> -- <what it means>` and `EXIT: <n> (<NAME>)`.
An exit code nobody can read is a number, not a diagnosis.

### Measured end to end

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/providers.md
SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate
parsed receipts: 0/0 reproduce exactly (0 fenced blocks, 0 unclassified, 0 volatile-skipped)
VERDICT:         pass -- 0 failure(s), 0 warning(s)
SELF-TEST VERDICT: INCONCLUSIVE -- ...
EXIT:            2 (INCONCLUSIVE)          [rc=2, was rc=1]
```

and the anti-masking case, which is the one that matters:

```
(a doc with one flatly false receipt, so the self-test has no clean seed target)
SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate
FAIL  line 3 [live working tree]: echo actual
VERDICT:         FAILED -- 1 failure(s), 0 warning(s)
SELF-TEST VERDICT: INCONCLUSIVE -- ...
EXIT:            1 (FAILED)                [rc=1 — INCONCLUSIVE did not win]
```

### Real-spec gate, all seven enforced specs, `--self-test --strict`, rc=0 each

| spec | receipts | verdict | exit |
|---|---|---|---|
| claim-nonce | 68/69 | pass, 1 warn (inherited volatile `~/.claude` count) | 0 |
| three-tier-command | 68/68 | pass | 0 |
| native-substrate | 5/6 | pass, 1 warn (inherited volatile `claude --version`) | 0 |
| fleet-index | 9/9 | pass | 0 |
| autoclean | 6/6 | pass | 0 |
| terminal-surface | 11/11 | pass | 0 |
| graceful-succession | 25/25 | pass | 0 |

Both self-tests PASSED on every one. The only two WARN lines in the whole corpus are the two
inherited volatile ones; there are no FAIL lines (checked by grepping every output for `^FAIL`,
not by eyeballing a tail).

## 5. Mutants

19 planted, each a plausible alternative implementation rather than a syntax break. Restore verified
byte-identical by sha256 after every run.

**A setup bug in my own harness scored 7/19 first.** The working file is CRLF; my multi-line anchors
were written with `\n`, so twelve anchors matched nothing and were reported as SETUP-FAIL. They were
only distinguishable from real survivors because the driver asserts each anchor occurs exactly once
— had it used a silent `str.replace`, that run would have read as a 7/19 result with twelve
mysterious survivors, or worse, as 19/19 with twelve no-op mutants.

**A second self-report defect, caught by re-measuring:** the first table attributed M13's kill to
`test_extraction_self_test_without_a_classified_block_is_inconclusive`, a pin its mutation cannot
touch. Re-running M13 alone without `-x` showed the true kill set — the two pins written for it.
The `-x` flag plus first-FAILED-line parsing produced a plausible, wrong attribution. The final
sweep runs without `-x` and records the complete kill set per mutant.

### The survivor, and it is the standing finding landing on me

The final sweep (22 mutants, after the adversarial pass added M20–M22 against the new EXIT-cause
line) came back **21/22 with M21 SURVIVING**: *"EXIT line never blames the self-test."*

The pin I wrote in the same edit that introduced the causes line
(`test_main_names_which_accumulator_produced_a_failure`) asserted `"receipt failure(s)" in out` and
**never asserted the self-test arm**. So half the mechanism I had just added was unpinned, by the
test I wrote to pin it. That is this repo's 7/7-wave finding — *a pin written against the mechanism
you fixed misses the one you introduced* — reproduced exactly, on the fix I made in response to
being told about it.

Remedy: the test now asserts each arm in a case where the **other is absent**, so neither can carry
the other — self-test cause alone (`SINGLE_WORD`, receipts fine), receipt cause alone (no
`--self-test`), both together (`FALSE_RECEIPT`), and neither (`GOOD`, asserting `-- from` is absent
entirely). M21 re-injected against the strengthened test: **KILLED**, restore byte-identical.

**Final: 22/22 killed, 0 survivors.** Every mutant is a plausible alternative implementation, not a
syntax break; restore sha256-verified after each.

| group | mutants | representative kill |
|---|---|---|
| over-quiet (a failure becomes silence) | M1–M5 | `test_neither_bad_verdict_exits_zero`, `test_an_inconclusive_self_test_cannot_mask_a_real_receipt_failure` |
| genuine failure softened to INCONCLUSIVE | M6–M9 | the four behavioural `self_test`/`_extraction_seed` pins |
| the original over-loud bug restored | M10–M13 | `test_self_test_with_no_multi_word_receipt_is_inconclusive` |
| accumulator / ranking | M14–M17 | `test_extraction_self_test_takes_the_worst_of_its_two_seeds` |
| truthiness trap | M18–M19 | `test_verdict_refuses_to_be_a_bool` **and nothing else in the corpus** |
| EXIT-cause line | M20–M22 | `test_main_names_which_accumulator_produced_a_failure` |

M18/M19 are the load-bearing evidence for §2: a truthy `Verdict` is killed by *no other test in the
repository*. With a plain `enum.Enum`, that mutant would have been the shipped state and the suite
would have stayed green.

## 6. Floors — predicted before running, hit exactly on both interpreters

Baseline re-measured by me on the clean tree at `28df49b`, not inherited:

| | collected | passed | skipped | xfail | rc |
|---|---|---|---|---|---|
| baseline py3.13 | 3662 | 3647 | 14 | 1 | 0 |
| baseline py3.10 | 3662 | 3647 | 14 | 1 | 0 |

New tests counted by `--collect-only`, never by counting `def test_` lines: **29 defs → 41 tests**
(the brief's 32-defs-42-tests trap, live), plus 2 added by the adversarial pass = **43**.
No test was added to `tests/test_receipts.py`; four assertions there were rewritten in place.

**Predicted: 3647 + 43 = 3690 passed / 14 skipped / 1 xfailed = 3705 collected.**

| | collected | passed | skipped | xfail | rc | time |
|---|---|---|---|---|---|---|
| py3.13 | 3705 | 3690 | 14 | 1 | 0 | 334.41s |
| py3.10 | 3705 | 3690 | 14 | 1 | 0 | 307.06s |

Exact, and identical on both floors. Zero regressions; skipped and xfail unchanged.

### The corpus effect, measured on both trees

`--self-test --strict` over all 15 files in `docs/specs/`:

| | pre-change rc | post-change rc |
|---|---|---|
| 7 receipt-carrying specs | 0 | 0 (both self-tests PASSED, unchanged) |
| 8 specs with no pinned receipts | **1** | **2** |

So **8 of 15 specs were reporting a red that never meant anything**, and were indistinguishable
from a verifier caught lying. The two WARN lines in the whole corpus (claim-nonce :1422, native-
substrate :246) are byte-identical on both trees — I ran the pre-change tool out of
`git show HEAD:tools/verify_receipts.py` rather than inheriting the claim, and the receipt
fractions (68/69, 5/6) match exactly. No FAIL line anywhere, checked by grepping every output for
`^FAIL`, not by reading a tail.

## 7. The adversarial gate on my own work

**The strongest argument I can make against this diff is that it cannot convert a real failure into
silence — and that is provable, not hoped for.** Old `rc=0` ⟺ `self_test` returned `True` and no
check failures. New `rc=0` ⟺ verdict is `PASSED` and no check failures, and `PASSED` is returned on
exactly the old `True` paths. The two reclassifications move only INCONCLUSIVE↔FAILED, both
non-zero. **The set of inputs that exit 0 is unchanged.** So the attack has to come from somewhere
else, and reading for it found two real defects in my own work:

1. **The misattributable exit.** A document whose self-test is INCONCLUSIVE *and* whose receipts
   fail printed `SELF-TEST VERDICT: INCONCLUSIVE` immediately above `EXIT: 1 (FAILED)`, with
   nothing on the page saying which accumulator produced the 1. The exit code was right; the
   operator's only available reading was a guess. Fixed: the EXIT line now names its causes
   (`-- from self-test INCONCLUSIVE, receipt failure(s)`), pinned by
   `test_main_names_which_accumulator_produced_a_failure`, and M20-M22 attack it.
2. **The tie-break nobody pinned.** `worse()` is `max(..., key=...)`, which returns the FIRST
   maximal element. With two verdicts at equal severity, `worse(INCONCLUSIVE, FAILED)` returns
   INCONCLUSIVE and a real failure exits 2 — the exact silence class. My own mutant M16 built that
   tie and was killed only because the ranking test happens to assert both argument orders; nothing
   pinned the property the tie-break *depends on*. Fixed by
   `test_no_two_verdicts_share_a_severity`.

Both were found by re-reading the diff, not by a failing test. That is the finding.

### The strongest argument against my design, which I could not fully answer

**The INCONCLUSIVE label is least honest exactly when the document is worst.**

`:742` is reached by a loop that RUNS every receipt and selects a seed target only if
`actual == r.expected`. So a document in which **every receipt is broken** yields no target, and the
tool prints *"SELF-TEST INCONCLUSIVE: no clean multi-word receipt to mutate"* — a sentence whose
whole meaning is "nothing is known to be wrong" — about a document where everything is wrong. I
confirmed this is real, not theoretical: it is precisely why `FALSE_RECEIPT` is a valid fixture for
`test_an_inconclusive_self_test_cannot_mask_a_real_receipt_failure`.

My defence is that the verdict describes the SELF-TEST, not the document; `check()` reports the
document; dominance keeps the exit at 1 (pinned); and the EXIT line now names `receipt failure(s)`
as a cause. That defence holds for the exit code, which is what the task asked for.

**It does not fully hold for the prose.** A reviewer can reasonably argue `:742` should split in
two — *no seedable receipt because the document has none* (INCONCLUSIVE) versus *no seedable receipt
because none of them reproduce* (FAILED, or at least a distinct diagnosis). The information to make
that distinction is right there in the loop: it already knows whether it ran any receipts and
whether any reproduced. **I did not build it**, because it widens the classification beyond the
task's four functions and the six/three split I was asked to argue. If the operator wants it, it is
a small, well-scoped follow-up: count reproducing receipts in the target loop and branch on zero.

That is the strongest argument I can make against this diff, and I am recording it as an open
finding rather than as a thing I closed.

## 8. What I did NOT prove — stated so it cannot read as news later

- **`:766` has no behavioural pin, and cannot have one.** It is unreachable by construction (§3), so
  its FAILED label rests on an argument plus the AST census. If my reachability argument is wrong,
  nothing here catches it.
- **The AST census is a restatement, not independent evidence.** I wrote both `GUARD_CENSUS` and the
  code, from the same belief. It kills label-flip mutants (M6-M13 all die to it as a second pin) but
  it cannot tell me a label is *wrong* — only that the printed word and the returned constant agree.
  The behavioural pins carry correctness; the census carries consistency. Do not read 22/22 as
  proof the six/three/two split is right.
- **`:761`'s reclassification is argued from reachability, and the injection that pins it is
  synthetic** (`monkeypatch` sets `r.line = 9999`). No real document produces it. If a future edit
  changes what `r.line` means, that guard starts firing on ordinary specs and now says FAILED — the
  loudest possible wrong answer. Exit code is non-zero either way, so the blast radius is wording.
- **Exit code 2 is conventional, not derived.** Nothing in the repo consumes the verifier's exit
  code — I checked: no CI workflow (`.github/` holds only `ISSUE_TEMPLATE/`), no hook, no script,
  only CLAUDE.md prose telling an operator to run it. If something later wants 2 for a different
  meaning, this collides.
- **I did not touch the fenced files** (`bin/hooks/stop_outcome.py`,
  `tests/test_outcome_usage_provenance.py`, `tests/integration/test_native_pin.py`) and did not
  push or merge. `git diff --stat` is two modified files plus one new test file.
- **I did not re-verify the corpus under py3.10** — the verifier gate was run on 3.13 only. The
  py3.10 floor exercises `main()` and all four functions through the new test file, but the
  15-spec `--self-test --strict` sweep is a 3.13 measurement.
- **Untested: concurrent/large-corpus behaviour and the `--skip-volatile` path through `main`.**
  Unchanged by this diff, but unpinned by it too.
