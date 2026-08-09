# w51-slicee — what multi-fleet slice (e) actually is, measured

**Lane:** build. Branch `w51/slicee`, dispatched at `7b2ff75`. Worktree
`C:/proga/fleet-w51-slicee`. No push, no merge, no other ref moved.

**Every line below is tagged MEASURED or BELIEVED.** MEASURED means a command was run in this
worktree and its output is the ground for the sentence. BELIEVED means it is a reading of prose,
and the prose is quoted.

---

## 0. The answer in one paragraph

MEASURED: slice (e) is **four categories, not ten**. Six of §7's ten are landed AND non-vacuous
(a mutant reddens each). Two more are landed but **cannot fail** — a "real-list-untouched pin"
that is a tautology, and a no-rewrite lint whose population is two functions and excludes the
verb. Two were never built. **Nothing in (e) is blocked on (b) or (d)**, and the contested
(a)/(e) split resolves by measurement without a fifth operator gate: the two documents were
never in conflict, because `docs/mf-slice-a-price.md`'s Ambiguity #1 parenthetical names
*plumbing*, not pin categories (§2 below). The headline finding is not a missing pin but a green
one: **a whole-file rewrite of the append-only homes list, planted in `cmd_homes`, is a proven
full-suite survivor — 4235 passed / 14 skipped / 1 xfailed, byte-identical to the clean
baseline.**

---

## 1. THE CENSUS — §7's ten categories against the shipped tree

MEASURED at `7b2ff75`, working tree clean, digest
`a3c031a778733e31592f735644c402ad429748fa9719011d19f8e14ea4c5778f files=245`.

Clean floor, `py -3.13`: **4250 collected, 4235 passed / 14 skipped / 1 xfailed** (436.45s).
Every mutant below was applied by an AST-scoped byte-safe planter that asserts its own patch
applied, and every one was restored to that same digest (§7).

| # | §7 category | Covered? (by NAME and BEHAVIOUR) | Non-vacuous? — mutant and result | Blocked on | Whose |
|---|---|---|---|---|---|
| 1 | **env fixture** | **NO.** `tests/conftest.py`'s autouse `_never_touch_the_real_home` enumerates THREE helpers by name (`user_settings_path`, `claude_daemon_lock_path`, `claude_daemon_log_path`). `homes_list_path` is **not among them** — zero matches for it in `conftest.py`. | n/a — nothing to mutate | nothing | **(e)** |
| 2 | **homes-list-path monkeypatch** | **YES**, but as **four copies** of a file-scoped `autouse` `sandboxed_list` fixture (`test_homes_list.py:70`, `test_homes_verb.py:41`, `test_home_resolution.py:56`, `test_verb_effect_guard.py:57`), not one shared fixture. | **YES.** Seeded by `test_the_redirect_is_actually_in_force`, which asserts the patched path is not `REAL_LIST`. | nothing | landed (a1) |
| 3 | **real-list-untouched pin** | **YES by name** — `test_home_resolution.py::test_the_real_list_is_untouched`, docstring *"§7's real-list-untouched pin"*. | **NO — VACUOUS.** Mutants **C3b** and **C3c** append **122** and **117** records to the (simulated) real list; **all three** candidate pins stay green. C3b costs 1 unrelated failure, C3c 1, and neither names the breach. | nothing | **(e)** |
| 4 | **quiescent-home canary** (loud skip, delete-if-never-quiescent) | **NO.** `grep -rn quiescent` over the repo: 3 hits, all in prose (`multi-fleet.md:675`, `mf-slice-a-price.md:77,202`) plus one supervisor-journal line. Zero in `tests/`. `tests/test_resilience.py`'s "canary" is an unrelated timezone check. | n/a — does not exist | nothing | **(e)** |
| 5 | **membership + fold pins** | **YES.** Fold: `test_homes_list.py::TestTheSequenceFold` (7 tests). Membership: `test_home_resolution.py::TestMembershipIsTheUnionAndSpawnedByNeverGrantsIt` (4). | **YES, both.** **C5a** (fold → first-record-wins): **16 failed**, six of them in `TestTheSequenceFold`. **C5b** (`spawned_by` grants membership): **exactly 1 failed** — `test_spawned_by_never_grants_membership`. | nothing | landed (a1/a2) |
| 6 | **writer-contention pin** | **YES.** `test_homes_list.py::TestWriterContention::test_concurrent_appends_lose_nothing` (4 threads × 25). | **YES.** **C6** (replace the `FILE_APPEND_DATA` handle with the CRT `O_APPEND` emulation the adapter's own docstring measured at ~17% silent loss): **exactly 1 failed** — that pin. | nothing | landed (a1) |
| 7 | **no-rewrite lint** | **YES by name** — `test_homes_list.py::test_the_no_rewrite_lint`, AST-derived, with its own seed. | **NO — VACUOUS OVER THE VERB.** Its population is **2 functions** (`append_home_record`, `read_homes_list`); **ten** list-touching scopes are outside it, including `cmd_homes`. **C7b** — a whole-file rewrite in `cmd_homes` that destroys `add·retire·add` history — is a **proven FULL-SUITE survivor: 4235 / 14 / 1, identical to the clean baseline.** | nothing | **(e)** |
| 8 | **rendered "not initialized"** | **YES.** `test_homes_verb.py::TestTheView::test_each_listed_home_renders_with_its_read_time_state` asserts the word against `render_homes_view`. | **YES.** **C8** (drop the state-word mapping): **exactly 1 failed** — that test. | nothing | landed (a1) |
| 9 | **destructive-tier pin** | **YES.** `test_verb_effect_guard.py::TestTheDestructiveTierPin` (9 tests), armed machine, env-resolved `clean` refuses / `spawn` proceeds. | **YES.** **C9** (`_apply_wrong_home_guard` stops refusing destructive): **7 failed**, six of them in that class. | nothing | landed (a3) |
| 10 | **arming-indeterminacy pin** | **YES.** `test_verb_effect_guard.py::TestIndeterminacyAlwaysArms` (5 tests). | **YES.** **C10** (unreadable list no longer arms): **2 failed** — `test_an_unreadable_list_arms`, `test_a_list_that_is_a_directory_arms`. | nothing | landed (a3) |

**Slice (e)'s column: 1, 3, 4, 7. None of them blocked.**

BELIEVED, and stated because the brief predicted it: the ten are **not** a clean partition.
Categories 1, 2 and 3 are one mechanism seen from three angles (the redirect's *default*, the
redirect's *reach*, and the *proof* that the reach held) — which is exactly why 2 shipped and 1
and 3 did not: a1 could build the reach inside its own fence and could not build the default.
Category 5 is written as one item and is two independent pins with two independent mutants.

---

## 2. THE CONTESTED (a)/(e) SPLIT — resolved by measurement, no operator gate needed

The brief asked whether this can be settled without the operator, and instructed me to stop at
the table if it cannot. **It can.** MEASURED: the two documents were never in conflict.

The operator's binding sentence (`knowledge/lessons.md`, 2026-08-05 launch-directive section):

> slice (a) ships the two §7 pins that verify its own surface (destructive-tier,
> arming-indeterminacy — landing with a3); **§7 items that presuppose later slices' plumbing
> defer to slice (e)**.

The brief reads `docs/mf-slice-a-price.md`'s Ambiguity #1 as naming *"the things that genuinely
wait for (e)"* as **"hook argv, statusline capture-gating"**, and observes that these *"are not
among the ten categories at all"*. MEASURED — the observation is correct and the inference from
it is not. The sentence, quoted whole:

> the remaining §7 items **that presuppose later slices' plumbing (hook argv, statusline
> capture-gating)** genuinely wait for (e)

The parenthetical is attached to **"later slices' plumbing"**, not to **"§7 items"**. It names
slice (c) and slice (d). It is a gloss on the criterion, not a list of pins — which is why none
of the ten appears in it, and why nothing needs reconciling.

So the criterion is the operator's, unmodified: *does the item presuppose plumbing that had not
landed?* Applied to the shipped tree, each of the four (e) rows answers it for a **different**
reason, and none of the four reasons is "waiting on (b) or (d)":

* **Category 1 and 3 — (a) escalated them, in the tree, in writing.**
  `tests/test_homes_list.py`'s own module docstring, MEASURED verbatim:
  > **That is not true of a new helper**: it monkeypatches THREE helpers BY NAME […] so
  > `homes_list_path()` is NOT covered by it. **Editing `conftest.py` is outside this lane's
  > fence**, so the redirect lives here as an autouse fixture with a seed […] **§7's
  > "real-list-untouched pin" wants the conftest half; that is escalated in the a1 report.**

  The deferral ground is a1's *fence*, not later plumbing — a case the operator's sentence does
  not cover and does not need to, because the effect is the same: (a) did not ship it and said
  so. `docs/mf-slice-a-price.md:198-205` assigns four categories to (a) as deliverable #2
  (quiescent canary, writer-contention, no-rewrite lint, rendered "not initialized"); MEASURED,
  **three of those four shipped** (rows 6, 7, 8) and the fourth did not (row 4). The price doc
  was right about three and wrong about one; it never claimed rows 1 and 3.

* **Category 4 — never built and never escalated.** Falls to (e) by default.

* **Category 7 — landed, and green over a hole.** The brief's own rule decides it:
  *"A category that exists but whose pin cannot fail is slice (e) work, not landed work."*

**No fifth operator gate is opened by this report.** The four already open
(`docs/OPERATOR-GATES.md`) are unaffected; gate 3 (*does the E2 ground reach `init --home`*) is
what blocks slice (b), and nothing in (e) touches it.

---

## 3. FINDING 1 — the real-list-untouched pin is a tautology, and the machine's protection is an accident

### 3.1 The pin

MEASURED, `tests/test_home_resolution.py:1117`:

```python
def test_the_real_list_is_untouched(self):
    """§7's real-list-untouched pin, restated for this file: every test
    above writes through `sandboxed_list`."""
    before = REAL_LIST.exists()
    fleet.read_homes_list()
    assert REAL_LIST.exists() == before
```

Four independent reasons it cannot fail, each MEASURED:

1. The file's `sandboxed_list` fixture is `autouse=True`, so `fleet.read_homes_list()` here reads
   the **sandbox**. The one call it makes cannot reach `REAL_LIST` at all.
2. `read_homes_list` is a **read**. `test_reading_an_absent_list_creates_nothing` pins that it
   creates nothing. So `exists() == before` is true by construction even unsandboxed.
3. It compares **existence only**. An append to an existing real list leaves `True == True`.
4. Its docstring makes a claim about *other tests* (*"every test above writes through
   `sandboxed_list`"*) that the assertion never measures.

### 3.2 Proof that it is green over a hole

Mutants were run with `USERPROFILE` pointed at a throwaway directory, so `Path.home()` — and
therefore `REAL_LIST`, which those files compute at import as
`Path.home() / ".claude" / "fleet-homes.list"` — is a **simulated** real home. The simulation is
exact and the operator's list was never a candidate (§7).

| mutant | what it does | four homes files | records landing in the (simulated) real list | the three candidate pins |
|---|---|---|---|---|
| **C3** | `append_home_record` ignores `homes_list_path()` entirely | 15 failed / 232 passed | **119** | **all 3 green** |
| **C3b** | honours the redirect **and** shadow-appends the real list through the adapter | **1** failed / 246 passed | **122** | **all 3 green** |
| **C3c** | same, shadow write bypasses the adapter | **1** failed / 246 passed | **117** | **all 3 green** |

MEASURED: C3b's single failure is
`test_it_goes_through_the_platform_adapter`, which fails because the adapter was called **twice
instead of once** — a call-count assertion, not a real-list assertion. C3c's single failure is
the no-rewrite lint, which fires on the literal `open(` and would not fire from any scope outside
its two-function population (§4). **Neither failure names the breach, and a mutant that made the
shadow write from a third function would cost zero failures.**

### 3.3 The suite reads the real list today, and is unharmed for the wrong reason

MEASURED, three ways:

* `homes_list_path` does not appear in `tests/conftest.py`.
* AST reverse-BFS over `bin/fleet.py`: **15 scopes** transitively reach `read_homes_list` /
  `homes_list_path`, and **`main()` is one of them** (`main` → `apply_resolved_home` →
  `resolve_home` → `resolution_population` → `read_homes_list` → `homes_list_path`). **15 test
  files outside the sandboxed four drive `main()`.**
* A read-only pytest plugin wrapping `homes_list_path` over three of those files
  (`test_cli.py`, `test_view_quarantine.py`, `test_supervisor.py`, 574 tests):
  **19 calls resolved to the real `~/.claude/fleet-homes.list`, 0 to a sandbox.**

Those 19 are reads of an absent file and created nothing — I verified the file was still absent
afterwards. **That is not protection.** Per the brief's instruction: `~/.claude/fleet-homes.list`
**does not exist on this machine** (`ls` → `No such file or directory`), which is the same reason
wave 48's containment audit came back clean. The list is one `fleet homes --add` away from
existing, at which point 19 unsandboxed reads become 19 reads of the operator's real population —
and any future test that drives a *write* through an unsandboxed `main()` appends to a file the
campaign has **RATIFIED DESTRUCTIVE**, which only the fold reverses.

---

## 4. FINDING 2 — the no-rewrite lint's population is two functions, and a rewrite in the verb survives the full suite

### 4.1 The population

MEASURED by AST over `bin/fleet.py`. The lint (`test_homes_list.py:532`) collects every scope in
which the **`ast.Name` `homes_list_path`** appears, and bans `write_text`, `write_bytes`,
`unlink`, `rename`, `replace`, `writelines`, `truncate` and `open` there.

```
THE LINT'S POPULATION (scopes naming `homes_list_path`): 2
    append_home_record
    read_homes_list

SCOPES THAT REACH THE LIST BUT ARE OUTSIDE THAT POPULATION:
    _refuse_ambiguous_lookup   _refuse_wrong_home_destructive   _terminus_refusal
    apply_resolved_home        cmd_homes                        homes_population
    lookup_home_for_sid        multi_fleet_arming               render_homes_view
    resolution_population
```

`read_homes_list()` returns a dict whose **`"path"` key is the list's own `Path`**, so any of
those ten can rewrite the file while naming nothing the lint looks for. **`cmd_homes` — the verb,
and the only surface an operator drives — is one of the ten.**

### 4.2 The survivor

**C7b**: one line in `cmd_homes`, line-count neutral, realistic in shape (a "compaction" of the
list to its folded members):

```python
listed = read_homes_list(); listed["members"] and listed["path"].write_text(
    "\n".join(listed["members"]) + "\n", encoding="utf-8")
```

MEASURED that the mutant is **real, not inert** — driven directly against a list holding
`add · retire · add`:

```
BEFORE: ['<h>/a', '!<h>/a', '<h>/a']         3 records
AFTER : ['<h>/a', '<h>/b']                    2 records
RETIREMENT RECORD SURVIVED: False
HISTORY DESTROYED: True
```

That is precisely §4's *"Append-only forever (rewrite reading measured 95–100% loss)"* being
violated, and the fold's own `add·retire·add` history erased.

MEASURED full-suite result, `py -3.13`, with the mutant on disk:

```
4235 passed, 14 skipped, 1 xfailed in 423.69s
```

**Byte-identical to the clean baseline. Zero failures. A proven survivor.**

The first version of the same mutant (**C7**, +3 lines) produced exactly **4** failures —
`test_retired_sid_citations.py` ×2 and `test_self_citations.py` ×2 — **all four are `:NNNN`
citation pins reacting to the line-count change, none about the homes list**. That is the
campaign's own "a control must include the shape of the data" lesson landing on me: had I stopped
at C7 I would have reported "the suite catches it", and the suite catches only the *diff size*.

---

## 5. WHERE THIS BRIEF WAS WRONG

1. **"the assignment of those ten between (a) and (e) is contested in the record … nobody has
   reconciled them."** MEASURED: they do not conflict. Ambiguity #1's parenthetical
   *"(hook argv, statusline capture-gating)"* attaches to **"later slices' plumbing"**, not to
   **"§7 items"** — it names slices (c) and (d), which is why none of the ten appears in it. The
   brief's observation that they are *"not among the ten categories at all"* is correct; the
   inference that this makes the list and the criterion disagree is not. **§2.**

2. **"§7 is headed 'Unchanged from v6' as though it already exists; when the price doc was
   written it did **not**."** True then, materially stale now, and the staleness is the point:
   MEASURED, **six of the ten are landed and non-vacuous** and a seventh is landed-but-vacuous.
   The brief's framing (measure whether anything exists) under-describes the tree; the question
   that earns its keep is the brief's own second one — whether what exists can fail.

3. **"read the `FLEET_HOME IS NOT A FENCE` stanza in `docs/lanes/BRIEF-TEMPLATE.md`."** Correct
   and it is at `:31`. Noted only because a literal grep for the phrase as the brief spells it
   returns nothing — the heading is `` ## The safety stanza — `FLEET_HOME` IS NOT A FENCE ``,
   with backticks inside the phrase. A brief that names a stanza should quote it the way a grep
   will find it.

4. **"the standard this campaign holds is `w50/live`'s §6."** MEASURED: `docs/lanes/` holds 18
   files at `7b2ff75` and **there is no `w50-live.md`**. The nearest are `w50-fs2.md`,
   `w50-gfs.md`, `w50-mp.md`. I wrote §6 below against the *description* the brief gives (a build
   brief a successor can run without re-deriving anything) rather than against an artifact I
   could not read; if the intended model is one of the three that do exist, §6 should be
   re-graded against it.

5. **"I expect at least one category to be green over a hole."** MEASURED: **two** —
   rows 3 and 7 — and row 7's hole survives the full 4250-test floor, not a subset.

6. **"that slice (e) is small."** MEASURED: (e) is **four rows**, and the two that were never
   built are the small ones. The expensive half is the two that already exist and do not work,
   because widening a shipped lint means proving the widened population is green on the whole
   tree first (§6.4 — it is, zero banned-call hits across 12 scopes).

7. **Instrument correction the brief could not have known.** Its planter rule (*"a mutant planter
   must assert its own patch applied … assert the restore after"*) is necessary and **not
   sufficient on this machine**. `bin/fleet.py` is CRLF; a text-mode planter round-trips
   `\r\n → \n → \r\n` asymmetrically, so my v1 planter asserted `text == text` on restore, printed
   a **matching sha256**, and left `git status: M bin/fleet.py`. The working-tree digest caught
   it. **Amend the rule: the planter must operate on BYTES, and the restore assertion must be a
   byte comparison, not a text one.** `docs/lanes/BRIEF-TEMPLATE.md` should carry this next to
   the `git write-tree` amendment — same class, same cause (an instrument that reads a
   normalising view of the thing it is supposed to be hashing).

---

## 6. WHAT I BUILT

Four things, all in the test plane. **`bin/fleet.py` is not touched** — deliberately, see §8.

| # | Category | Where | What |
|---|---|---|---|
| 1 | env fixture | `tests/conftest.py` | `_never_touch_the_real_home` gains the `homes_list_path` redirect, and its docstring's false claim (*"any new `Path.home()` path added to fleet lands here by default"*) is corrected to say it enumerates helpers by name. |
| 3 | real-list-untouched | `tests/conftest.py` | `real_homes_list_path()` / `homes_list_snapshot()` / `homes_list_drift()` + session-scoped autouse `_the_real_homes_list_is_untouched_afterwards`. Compares **contents**, not existence. Never raises. |
| 3 | its seeds | `tests/test_slice_e_pins.py` | Seven seeds: append, creation, deletion, same-length rewrite, no-change, unreadable-is-a-state, and *the guard asks the real home, not the redirected helper*. |
| 4 | quiescent-home canary | `tests/test_slice_e_pins.py` | `home_is_quiescent()` (reusing `fleet._record_is_live`, the repo's one spelling), the canary over four verbs, the loud skip, the perturbation seed, and `delete-if-never-quiescent` discharged **by construction**. |
| 7 | no-rewrite lint | `tests/test_homes_list.py` | Population re-derived by pattern: 2 scopes → 12, `cmd_homes` in, `main` out. Five seeds, one per covered shape, plus a **control** that re-implements the old rule and proves it is blind to the shape that survived. |

### 6.1 RED, watched, before any of it was made to pass

MEASURED, `py -3.13`, fenced with a throwaway `USERPROFILE` (§9):

```
tests/test_slice_e_pins.py  --  conftest redirect NOT yet applied
4 failed, 13 passed, 6 errors

FAILED  TestTheConftestRedirectReachesEveryFile::test_the_default_homes_list_path_is_not_the_real_one
FAILED  TestTheConftestRedirectReachesEveryFile::test_the_default_lands_inside_the_conftest_home_sandbox
FAILED  TestTheConftestRedirectReachesEveryFile::test_a_write_through_the_default_lands_in_the_sandbox
FAILED  TestTheRealListGuardCanActuallySeeAChange::test_the_guard_asks_the_real_home_not_the_redirected_helper
ERROR   TestTheQuiescentHomeCanary  (x6 -- the fixture refuses to build a homes list at the real path)
```

**The very first RED run found a defect in my own new file, and the new guard is what found it.**
Before the guard-before-write was added, the canary's `two_homes` fixture called
`fleet.homes_list_path().write_text(...)` — with no redirect in place, that **created**
`~/.claude/fleet-homes.list`. It was contained (the run was fenced to a throwaway home) and it
was caught at session teardown by `_the_real_homes_list_is_untouched_afterwards`, added in the
same commit, on its first run. Nothing else in 4250 tests would have said a word.

That is the non-vacuity receipt for category 3 and I did not have to manufacture it: **a pin
whose failing path performs the act it forbids is a pin that damages the machine every time it
goes RED**, and both places that write the list now assert the path is not the machine's
*before* they write.

### 6.2 RED for the widened lint, which cannot come from the clean tree

A lint's RED has to come from a tree that has the defect. MEASURED, all three arms, at the same
commit with mutant **C7b** on disk:

```
widened lint, CLEAN tree              -> 13 passed
widened lint, C7b tree                -> FAILED: these scopes touch the homes list and can
                                         rewrite it: [('cmd_homes', 'write_text')]
SHIPPED (narrow) lint, C7b tree       -> offenders == []   # the mutant PASSES
```

### 6.3 Floor predictions — written before the floors were run

Collected, **not** counted from `def test_` lines:

| | py 3.13 | py 3.10 |
|---|---|---|
| baseline at `7b2ff75` | 4250 | 4250 |
| with this branch's tests | **4279** | **4279** |

Derivation of the +29: `tests/test_slice_e_pins.py` collects **23** (new file);
`tests/test_homes_list.py` goes **65 → 71**, i.e. **+6** — the lint block goes from 2 tests
(`test_the_no_rewrite_lint`, `test_the_lint_can_see_a_rewrite`) to 8 (the lint, the population
assertion, five parametrised seeds, and the old-rule control). 23 + 6 = 29.

**PREDICTION, both floors: `4264 passed, 14 skipped, 1 xfailed`.** (4264 + 14 + 1 = 4279.) The
14 skips are the `FLEET_LIVE`-gated live tier, unchanged; the xfail is unchanged; nothing this
branch adds is skipped or xfailed — the quiescent canary's skip arm is unreachable by
construction, which is the point of §7's `delete-if-never-quiescent` clause and is asserted by
`test_the_quiescent_arm_is_reachable_by_construction`.

**A missed prediction is a STOP-and-report event.** Results are appended in §10 and were not
known when this section was committed.
