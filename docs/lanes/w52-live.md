# w52-live — the worker respawn path now sweeps and tombstones what it retires

**Lane:** build. Branch `w52/live`, base `64b43c2`. Every line below is tagged **MEASURED** (I ran
it, in this worktree, and the command is quoted) or **BELIEVED** (reasoning I did not execute).

---

## 0. THE FLOOR PREDICTION — THIS SECTION WAS COMMITTED BEFORE THE RUN

*This section landed in a commit carrying no results. §7 records what actually happened; if §7
disagrees with §0, §0 stays as written — a prediction edited after the fact is not a prediction.*

**Baseline at `64b43c2`, MEASURED by me before touching anything** (the brief said it was unmeasured
by the supervisor):

| interpreter | collected | result | wall |
|---|---|---|---|
| `py -3.13 -m pytest -q` | 4636 | `4621 passed, 14 skipped, 1 xfailed` | 526.84s |
| `py -3.10 -m pytest -q` | 4636 | `4621 passed, 14 skipped, 1 xfailed` | 552.46s |

Working-tree digest (the `docs/lanes/BRIEF-TEMPLATE.md` script, **not** `git write-tree`) printed
before the 3.13 run, between the two runs, and after the 3.10 run — three times, identical:

```
7bb1bae68fb5b0f3b38a8f01fd4e2b1a5803c6c9cafcc77f4bc28fc303fae65e  files=261  root=C:\proga\fleet-w52-live
```

**PREDICTION for the built tree, both interpreters: 4648 collected, `4633 passed, 14 skipped,
1 xfailed`.**

Derived, not guessed:

- **+12 from `tests/test_respawn_retired_sweep.py`.** MEASURED by collection
  (`pytest --collect-only`), never by counting `def test_` lines — the brief's warning that 32 defs
  was once 42 tests. 12 defs, 12 collected, no parametrisation.
- **+0 from `tests/test_liveness_readers.py`.** One test renamed; none added or removed. 34 before,
  34 after.
- **+0 from this report.** `CHECK_COUNT_DOCS` is `every tracked *.md` minus `_HISTORICAL_PREFIXES`,
  and **`docs/lanes/` is the FIRST entry in that tuple** (`tests/test_doc_claims.py`), exempt *"by
  construction"* in its own words. Two pins are parametrised over that population, so a
  non-exempt doc would have cost 2 cases; this one costs 0. **MEASURED, not assumed** — the brief
  warned my predecessor asserted "docs cannot move the floor" and missed by 4.
- **+0 from anywhere else, and I checked rather than hoped.** `CHECK_COUNT_DOCS` is the ONLY
  tree-derived doc population in the suite: every other `parametrize` over documents
  (`ENTRY_DOCS`, `SURFACES`, `test_views_doctrine`'s pair) is a fixed literal list. `test_receipts.py`
  globs `docs/specs/*.md` only. `test_handoff_seams.py` globs `skills/**` + `commands/*`. Nothing in
  the suite enumerates `tests/` or `docs/lanes/`.
- **skips and xfails unchanged at 14/1.** The new file has no `skip`/`xfail` markers, and nothing I
  touched feeds `test_views_doctrine`'s skip-by-design.

**Also predicted: the digest changes**, because I added and edited files on purpose — `files=261`
becomes `files=262` (one new test file; the report was already committed when the run started).
The digest's job here is only to prove *the run itself* changed nothing, so the before/after pair
around each run must match each other, not the baseline.

---

## 1. WHAT I BUILT

Two gaps at one site, both closed, neither consulting Q1.

`_cmd_respawn_native` appended `old_sid` to `retired_sids` **unconditionally**, and then:

1. **swept nothing, ever.** MEASURED at `64b43c2` by `ast.walk` over `bin/fleet.py`:
   `_RETIRED_SID_SWEEP_CAP` is defined at `:8650` and loaded at exactly two sites — `:8776`
   (`_cmd_kill_native`, 8653-8826) and `:9577` (`_cmd_respawn_supervisor`, 9450-9639).
   `_cmd_respawn_native` (8258-8557) referenced it nowhere. So respawning a worker *N* times left
   *N* prior forks resident and *N* unbounded `retired_sids` entries, with nothing but a later
   `fleet kill` — itself capped at 20 — to ever stop any of them.
2. **wrote no tombstone on the branch that needs one.** The stop + tombstone + re-verify block is
   entirely inside `if old_live:` (`:8376`), and Q1 answers not-live for a keyed `state:"done"`
   entry whose `claude.exe` is still resident. `write_tombstone_outcome` exists precisely because
   `claude stop` fires no Stop hook (G10); it is fleet's only record of a deliberate end.

Both are now unconditional. The sweep set is exactly what the respawn is about to retire
(`prior_retired + [old_sid]`), minus the old sid when the `--force` arm already stopped and
tombstoned it. **Nothing in the fix reads Q1** except that one de-duplication test, which is about
avoiding a double stop, not about liveness.

### The judgement call, stated plainly so a gate can reject it on its own

**I EXTRACTED the sweep loop into `_sweep_retired_sessions` rather than copying it**, and the brief
listed "copying `_cmd_kill_native`'s sweep is the right shape rather than factoring the sweep out of
both" among the things it had probably got wrong. I think factoring is right, and the reason is
specific rather than aesthetic: the loop carries two guards that each cost an adversarial review to
find (the M1 skip for a retired sid equal to another worker's current `session_id`, and M5's
classified-outcome progress line), and **`_cmd_respawn_supervisor` is the existing proof that a
hand-written second copy drops them** — see §3.

What did **not** move into the helper is the **order and the cap**, deliberately. The two call sites
build genuinely different sets (kill unions the caller's snapshot, the under-lock read and
`extra_stop_sids`, then drops the primary; respawn takes exactly what it is retiring), and FIX WAVE
3's `MAJ-NEW` was a `sorted()` in precisely that position — which makes `[-cap:]` lexicographic and
truncates out the newest retired sid, the fork-steer parent the Steering contract leaves roster-live.
A helper that also sliced would have invited a second, invisible cap.

---

## 2. RE-DERIVING THE PROPERTY BY AST, AS ORDERED — BEFORE AND AFTER

MEASURED. The brief asked me to re-derive by AST rather than grep, and to say so. I did, with
`ast.walk` + an innermost-enclosing-function map, at both trees.

**Before, at `64b43c2` — reproduces the brief exactly, at the brief's own numbers:**

```
_RETIRED_SID_SWEEP_CAP      def :8650 (module)
  use :8776 -> _cmd_kill_native         (8653-8826)
  use :9577 -> _cmd_respawn_supervisor  (9450-9639)
_cmd_respawn_native         (8258-8557) -> references it NOWHERE
_cmd_respawn_native  :8420  new_record["retired_sids"] = prior_retired + [old_sid]
```

**After, at the head of this branch** — re-derived at the DISCHARGE tree, not the build tree. *(The
first version of this block was correct at `12c238c` and the F1 fix moved every number in it. It is
a claim about the CURRENT tree, so leaving it would have been exactly the rot §6 is about — caught
by re-running the derivation rather than by trusting it.)*

```
_ordered_unique_sids        def :8719-8750       <- new, F1's caller-side half
  use :8453 -> _cmd_respawn_native      (8258-8623)
  use :8982 -> _cmd_kill_native         (8858-9021)
_sweep_retired_sessions     def :8753-8855
  use :8462 -> _cmd_respawn_native
  use :8989 -> _cmd_kill_native
_RETIRED_SID_SWEEP_CAP      def :8716 (module)
  use :8454 -> _cmd_respawn_native      (8258-8623)
  use :8983 -> _cmd_kill_native         (8858-9021)
  use :9772 -> _cmd_respawn_supervisor  (9645-9834)
write_tombstone_outcome     use :8396 (--force arm) AND :8470 (unconditional) in _cmd_respawn_native
```

The three-site cap census is the gap closing: at `64b43c2` the worker respawn path was not among
the two. `_cmd_respawn_supervisor` still has neither the shared body nor its guards — §10.1.

---

## 3. WHERE THIS BRIEF WAS WRONG

The brief asked for this section and pre-named four suspicions. Three were wrong in my favour, one
was right, and I found two things it did not predict.

### 3.1 — "no tombstone … it is never written" — **WRONG as stated, and I nearly inherited it**

MEASURED. `write_tombstone_outcome` has a call **inside `_cmd_respawn_native`** at `:8386` on the
base tree. The brief's §"WHAT THE DEFECT ACTUALLY IS" says *"On this path it is never written"*,
full stop. The true statement is narrower: it is never written **on the not-live branch**, because
the call sits inside `if old_live:`. The `--force` arm has always written one.

This matters more than a wording nit, because the fix differs: "never written" invites you to add a
tombstone at the top of the function, which would then **double-write** on every `--force` respawn.
The AST census is what caught it — the brief's own prescribed instrument, run against the thing the
brief asserted.

### 3.2 — "`tests/test_liveness_readers.py` … check whether it reached `main` at all" — **it did**

MEASURED. Both `tests/test_liveness_readers.py` and `tools/mutate_liveness.py` are present at
`64b43c2`, landed by `ff38e77` *"merge(w51): w50/live — three liveness readers, additive"*. The
brief's suspicion was unfounded; no reconstruction was needed.

### 3.3 — "the tombstone can be written unconditionally without changing what a tombstone *means*"
— **essentially right, with one named delta**

MEASURED. I audited **every** reader of the outcome store at `64b43c2`:

| reader | filter | affected? |
|---|---|---|
| `_native_cumulative_tokens` | `kind == "result"` | no |
| `find_transcript_path` | needs truthy `transcript_path`; a tombstone carries none | no |
| `_fast_completion_sid` | `if rec.get("kind") != "result": return` | no |
| `has_fresh_outcome` | defaults `kinds=("result",)`; **all three callers use the default** | no |
| `latest_outcome` ×3 (`_native_token_summary`, `_cmd_result_native`, `cmd_wait`'s summary) | keyed on the record's **current** sid, all handle non-`result` kinds | no |
| `_archive_eligible:10124` — `if not read_outcomes(name, sid=sid): return (False, "no-outcome-record")` | keyed on the record's current sid | **the one delta** |

The delta, stated honestly: on a **rolled-back** respawn the record still carries `old_sid`, which
now has a tombstone where it might have had no outcome record at all — so `_archive_eligible` stops
answering `no-outcome-record` for it. **This is not a new state.** The `--force` arm already writes
that same tombstone before a dispatch failure can roll back, so the state was reachable on shipped
code; my change only widens which respawns reach it. And the semantics point the same way: a
tombstone means fleet deliberately ended the session, which is more reason to consider the record
archivable, not less.

### 3.4 — "the fix is separable from §6 as cleanly as I have asserted" — **it is, and here is why**

MEASURED, and this was the brief's own headline risk. The sweep does **not** need Q1's verdict
in-band. The reason is the one the brief itself supplied and I confirmed by reading the code: the
sid is retired **unconditionally**, so the sweep and the tombstone can be too. `old_live` appears in
my fix in exactly one place — `not (old_live and s == old_sid)` — and that is a de-duplication
guard against the `--force` arm's own stop, not a liveness question.

`_roster_live_sids` is byte-untouched. §6.7's owed decision stays owed. I did not open a fifth
operator gate, and I was not forced to.

### 3.5 — **NOT PREDICTED: `_cmd_respawn_supervisor` is not "a path that already does this right"**

The brief says to make the respawn path *"match the two paths that already do this right
(`_cmd_kill_native`, `_cmd_respawn_supervisor`)"*. MEASURED, that is false of the second one. At
`64b43c2`, `_cmd_respawn_supervisor:9577-9581` is:

```python
for retired in list(rec.get("retired_sids", []) or [])[-_RETIRED_SID_SWEEP_CAP:]:
    if retired and retired != old_sid:
        _stop_native_session_status(retired, run=run, which=which,
                                    timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
```

It has the cap and the timeout. It has **neither the M1 ownership guard nor the progress line**, and
it discards the `(ok, outcome)` tuple entirely. So the codebase already contained one hand-written
second copy of this loop that dropped exactly the guards the brief warned me not to drop — which is
the strongest available argument that copying would have been the wrong call, and it was sitting in
the brief's own list of exemplars.

**I did not fix it.** It is a different verb with a different test surface, the brief's stated
preference is *"one closed gap than half a refactor"*, and widening scope into the supervisor
lifecycle mid-wave is how a build lane turns into a merge. **It is now trivial to fix** — the shared
body exists and takes `other_current_sids` as a parameter — and I recommend it as a successor slice,
not as a gate blocker on this branch.

### 3.6 — ~~`docs/SPEC.md` carries a stale current-tree citation~~ **RETRACTED: FALSE FINDING**

> **STRUCK 2026-08-09, discharging gate `w52-glive3` F2 (MAJOR).** Everything in the box below is
> wrong, and the recommendation it fed (old §10.2) would have **damaged the spec of record**. The
> original text is kept, struck, because a retraction that deletes the claim leaves the next reader
> no way to check the correction.
>
> **What is actually true, MEASURED by the gate at three trees.** `docs/SPEC.md` §0 pins itself:
> *"Everything here is descriptive of `bin/fleet.py` at `c63d7dd` … Line numbers below are at
> `c63d7dd` and will drift; the function names are the durable anchors"* — with a blockquote
> immediately below titled **"PIN STALENESS — read this before trusting a line number"**. At
> `c63d7dd`, `state_dir` is at **61** and `pin_pass_path` at **110**. **`bin/fleet.py:61-110` is
> exactly right at the commit the document pins itself to.** Systematically: **57 of 64** anchors
> resolve at `c63d7dd`, **0 of 64** at HEAD.
>
> So it is a **pinned receipt about a past tree**, which this campaign ratified on 2026-08-05 as
> **not rot** — `tests/test_doc_claims.py`'s own words: *"a reference is rot only when it claims the
> CURRENT tree; a pinned receipt and a quoted argument are claims about a PAST tree and stay true.
> **Fixing them would FABRICATE.**"* My §10.2 proposed exactly that fabrication.
>
> **My census number was also wrong.** The correct count of current-tree `bin/fleet.py` citations is
> **0**, not 1.
>
> **Where the framing came from, since the gate asked me to say.** My manager's steer, twice: the
> gate brief that dispatched `w52-glive3` instructed it to confirm this as *"the third independent
> instance this wave of citations that were already wrong before anyone touched the file"*, and my
> own brief had primed the same expectation. The manager has recorded it against themselves —
> generalising from two lanes' real findings to a third that is not one, and handing it over as
> established. **The gate refused the instruction and measured instead, and was right to.** It also
> refused the brief's *"if you must cut, cut the citations"* triage — that section held the largest
> report-level defect on the branch. Both refusals were correct, and I am recording them here
> because a lane that only ever reports what its brief expected is not measuring anything.
>
> **What survives, and it is not nothing.** The *method* in §6 stands — name the oracle's population
> before trusting its colour. `tests/test_self_citations.py` genuinely resolves
> `bin/fleet.py`-about-itself only, and cross-document citations genuinely rot behind it unseen. The
> blind spot is real; what I found in it was not. There is also a real gap the gate names and I did
> not: my classifier mirrors `_HISTORICAL_PREFIXES`, which is a **path-prefix** list, and
> `docs/SPEC.md` governs itself in **prose** instead — *no instrument reads prose*. That is a
> genuine hole in the repo's classification, and it is the finding I should have filed.

<details>
<summary>The struck original (do not act on it)</summary>

### ~~3.6 — NOT PREDICTED: `docs/SPEC.md` carries a stale current-tree citation, and it is not mine~~

MEASURED, and it is the exact class the brief told me to look for. The brief warned that
`tests/test_self_citations.py` *"resolves `bin/fleet.py` citations about itself only, so it can be
green correctly while cross-document citations rot behind it"*, and told me to name that oracle's
population before trusting its colour. I did:

- **894** `bin/fleet.py:NNNN` citations across 155 tracked `*.md`.
- **893** are in historical/pinned documents (`docs/lanes/`, `docs/reviews/`, `docs/specs/`, …) —
  claims about a past tree, ratified as **not rot**.
- **1** is in a current-tree document: `docs/SPEC.md:84`, *"Receipt: path helpers
  `state_dir/logs_dir/…/pin_pass_path` @ `bin/fleet.py:61-110`"*.

Those helpers are really at **`:117-223`**. And it is stale at `64b43c2` too — I checked both trees
with the same derivation, and the definition lines are identical (`state_dir` at 117 in both), so
**my build did not cause it and did not worsen it.** My edits are all at `:8258`+.

**I have not fixed it in this commit.** It is a one-line correction to the spec of record, made by a
build lane, in a wave where four operator gates are already open — I would rather hand the gate a
measurement than a silent edit to `docs/SPEC.md`. The correct value is `61-110` → `117-223`.

I also swept the other citation spellings across all 30 current-tree documents (`fleet.py:N` without
the `bin/` prefix, bare `(:N)`, backticked `` `:N` ``, `:N-M` ranges): **one hit**,
`docs/NEXT-SESSION.md`'s `` `:337` ``, which cites a *spec section* in `claim-nonce.md`, not
`bin/fleet.py`. Nothing else to re-pin.

</details>

*(That sweep result is unaffected by the retraction and stands: it found nothing either way.)*

---

## 4. THE MANAGER'S MID-LANE STEER: W52-2 — SENT, THEN RETRACTED

**CORRECTED IN PLACE, and the correction is the point of the section.** I was steered twice about
finding **W52-2** and the second steer withdrew the first. Both are recorded, in order, because a
report that shows only the surviving version teaches nothing about how it got there.

**What I was told first** (mid-build): lane `w52-launch` had *"measured and reproduced four times"*
that on Windows at claude 2.1.226 a **finished** bg session presents as `state:"working"`,
`status:"idle"`, `pid` present — so Q1 reads a finished turn as **live** and a bare `fleet respawn`
refuses on an idle worker. Graded HIGH.

**What the gate found** (`w52-glaunch3`, verdict at `e97bbcb` on `w52/glaunch3`, driven
independently on a byte-identical `bin/fleet.py`): **GATING**. 5 of 6 drives of the documented bare
`fleet respawn <name>` returned rc=0 — it does not reproduce deterministically, and *deterministic*
was the word HIGH rested on. Regraded **MEDIUM**. The single reproduction was at `state:"blocked"`,
never the `state:"working"` the report pasted. A 30-sample / 60 s poll after a turn ends only ever
showed `state=done status=idle pid=present` — no window — with a trustworthy positive control.

**And the mechanism was backwards from what I was relayed.** `done` entries on this machine *do*
keep `pid` and `status`, and the `state != "done"` guard is precisely what makes five of six drives
succeed. The docstring's Windows parenthetical is false; the code it apologises for is what keeps
Windows working.

### What I retract from my own first pass

I wrote, on the strength of the first steer, that this was *"one predicate measured wrong in both
directions."* **I withdraw that framing.** It rested on W52-2 as filed, and only the §3.8 direction
is supported by evidence that has survived a gate. The sentence was mine; the claim under it came
from the manager, who has recorded the relay against themselves (*"a finished lane's result is a
claim, not a verdict"*). I am not deleting it, per the standing rule that a retraction must be
visible where the claim was.

### What survives, and it is the part that matters to this build

**1. Does any of this change my fix? No — and the gate's BLOCKING finding vindicates the scope fence
rather than merely permitting it.** The proposed W52-2 remedy (treat `status == "idle"` as
not-a-running-turn) is unscoped: `_roster_live_sids` has **13 call sites**, several in supervisor
claim and release, and the live roster carries a supervisor at `state:"blocked" status:"idle"` with
its pid alive — that fix would reclassify a **live supervisor as not-live**. So "do not change what
Q1 answers" is now correct for a *measured* reason, not a cautious one.

- **The sweep half is unaffected by any of it.** `prior_retired` is swept on **every** respawn,
  including every `--force` one, because only `old_sid` is excluded when `old_live`. The
  accumulating-forks defect — *N* respawns leaving *N* resident forks — closes regardless of what Q1
  answers, on every roster shape either lane observed.
- **The tombstone half is reached, and the gate's own null makes that stronger than my first pass
  did.** The gate's 30-sample poll found `state=done status=idle pid=present` — *which is exactly
  the §3.8 shape*: keyed, `done`, process alive. That is Q1 answering not-live for a live process,
  it is the branch my tombstone is on, and the gate measured it as the steady state after a turn
  ends rather than as a window.

**2. §6.7 is cited more weakly than the first steer told me to**, and §6/§9 say so: the owed decision
stands on its own design argument. It does not have a confirmed operator-facing defect behind it —
it has a MEDIUM, partly non-reproducing one, plus a BLOCKING objection to the obvious fix.

**3. Does my fix require Q1 to change? NO.** MEASURED: `_roster_live_sids` is byte-identical to
`64b43c2`, and `test_Q1_STILL_ANSWERS_NOT_LIVE_this_build_did_not_widen_it` pins that from the
outside. I never had to stop and report.

I did not re-drive W52-2 in either direction, as instructed both times.

---

## 5. THE PINS

### 5.1 The characterising tests, run BEFORE the build as ordered

MEASURED, `py -3.13 tools/mutate_liveness.py --only M-GATE2` and `--only M-GATE3`, at `64b43c2`,
before I edited anything:

```
M-GATE2 ==> KILLED (expected KILLED) OK
  RED: TestTheCensus::test_roster_live_sids_call_sites_are_this_exact_POPULATION
  RED: TestTheShapeALingeringFinishedSessionPresents::test_the_B6_union_gate_EXECUTES_and_does_not_see_a_live_retired_body
M-GATE3 ==> KILLED (expected KILLED) OK
  RED: TestTheCensus::test_roster_live_sids_call_sites_are_this_exact_POPULATION
  RED: TestTheShapeALingeringFinishedSessionPresents::test_worker_respawn_attempts_NO_STOP_AND_NO_TOMBSTONE
```

Both KILLED, both restored byte-identical, real worktree untouched. **The pin had not decayed**, so
there was nothing to restore before proceeding.

Worth naming, because it is the subtle part: **both of those mutants model widening Q1** — each
replaces a `_roster_live_sids` call with an inline keyed-entry predicate. They are the shape the
brief told me *not* to build. My fix is not either of them, and that is why the fix leaves
`test_the_q1_predicate_calls_a_live_process_not_live` (explicitly *not* `INVERT-ON-BUILD`) green.

### 5.2 The inversion, done deliberately and not quietly

MEASURED: after the build, `tests/test_liveness_readers.py` went `1 failed, 33 passed`, and the one
failure was `test_worker_respawn_attempts_NO_STOP_AND_NO_TOMBSTONE` with
`AssertionError: respawn touched the old session after Q1 said not-live: ['stop', 'tombstone']`.
That is the design.

It is now `test_worker_respawn_NOW_STOPS_AND_TOMBSTONES_a_lingering_done_session`, asserting
`calls == ["stop", "tombstone"]`. **Its old name, its old assertion and its whole old reasoning are
quoted verbatim in the new docstring**, because a characterising test rewritten quietly leaves no
evidence the gap ever existed — and the file's own precedent (the B6 pin that replaced
`test_the_union_gate_cannot_see_a_live_retired_body`) is to rename *with* the record.

**The other `INVERT-ON-BUILD` markers in that file are untouched and still green.** They belong to
§6's reader collapse, which is not my job this wave; a successor inverts those.

### 5.3 The new pins, and proof they can fail

`tests/test_respawn_retired_sweep.py`, 12 pins. It mirrors the kill path's five properties against
the third caller — the kill pins cannot do that job: the sweep could be deleted from the respawn
path entirely and every one of them would stay green.

**Non-vacuity, proof 1 — MEASURED against the pre-build tree.** `git archive HEAD` at `64b43c2` into
a scratch export, the new test file copied in, run there: **`7 failed, 5 passed`**. The 7 are every
pin that asserts the new behaviour; the 5 that pass are the controls that must be green in *both*
trees.

**Non-vacuity, proof 2 — MEASURED, every pin killed by a real mutant.** I added six `M-W52-*`
mutants, found two pins with no mutant at all (`test_a_Q1_live_turn_still_refuses_without_force`,
`test_an_unfetchable_roster_still_refuses_and_sweeps_nothing` — green before *and* after, which is
gate2 B2's shape), and added two more for them. Coverage derived by parsing the ledger's own `RED:`
lines rather than asserted:

| pin | killed by |
|---|---|
| `test_Q1_STILL_ANSWERS_NOT_LIVE_this_build_did_not_widen_it` | `M-E` |
| `test_respawn_sweeps_the_prior_retired_sids_AND_the_old_sid` | `M-E`, `M-GATE3`, `M-W52-SWEEP` |
| `test_respawn_retired_stops_use_the_short_per_sid_timeout` | `M-E`, `M-GATE3`, `M-W52-SWEEP` |
| `test_respawn_sweep_is_capped_at_the_20_MOST_RECENT` | `M-E`, `M-GATE3`, `M-W52-SWEEP`, `M-W52-ORDER`, `M-W52-CAP` |
| `test_respawn_sweep_prints_one_progress_line_per_sid` | `M-E`, `M-GATE3`, `M-W52-SWEEP` |
| `test_respawn_sweep_reports_the_classified_outcome_not_a_guess` | `M-E`, `M-GATE3`, `M-W52-SWEEP` |
| `test_respawn_skips_a_retired_sid_that_is_another_workers_current_sid` | `M-E`, `M-GATE3`, `M-W52-SWEEP`, `M-W52-M1` |
| `test_respawn_tombstones_the_old_sid_when_Q1_says_NOT_live` | `M-E`, `M-GATE3`, `M-W52-TOMB` |
| `test_respawn_force_tombstones_the_old_sid_EXACTLY_ONCE` | `M-W52-DOUBLE` |
| `test_a_Q1_live_turn_still_refuses_without_force` | `M-W52-REFUSE` |
| `test_an_unfetchable_roster_still_refuses_and_sweeps_nothing` | `M-W52-ROSTER` |
| `test_the_sid_is_still_retired_and_no_foreign_sid_enters` | `M-E`, `M-GATE3` |

**12 pins, 0 uncovered.** Full ledger: **15 mutants, all KILLED**, floor green at 46, every restore
byte-identical by sha256, `real worktree bin/fleet.py : untouched`.

`M-B2` cannot stand in for `M-W52-ROSTER`, which is why both exist on the same clause: `M-B2` only
*force-gates* the unfetchable-roster refusal, leaving the no-force path refusing — and the no-force
path is exactly what the new pin drives.

### 5.4 Two repairs to the instrument itself

**The driver graded one file and I added pins to a second.** `TESTFILE` was a single string, so
every `M-W52-*` mutant aimed at the new file would have reported `SURVIVED` — not because the pins
were weak but because nothing ran them. That is gate2 B2 one level up, inside the tool that exists
to prevent gate2 B2. It is now `TESTFILES`, a tuple, copied and run as a set.

**The planter is text-mode, which wave 51 named as a defect class.** MEASURED, it is byte-exact
*here* and I can say why rather than assert it: `git archive` applies the eol conversion, so the
export is CRLF byte-identical to the checkout (`21775` CRLF, `0` bare LF, same sha256 as the
worktree file), and `os.linesep` is CRLF — so `read_text`/`write_text` round-trips exactly. The
existing restore check reads `read_bytes()`, so it is genuine, **but it runs after a mutant has
already been graded**, and a verdict read off the wrong bytes is worthless whichever colour it comes
out. `text_roundtrip_is_byte_exact` now performs the round-trip as a no-op patch and compares
against the floor **before anything runs**, aborting `rc=5` otherwise.

### 5.5 A defect I introduced and caught, recorded because the next lane will hit it

I re-pinned citations in `tests/test_liveness_readers.py` with a Python script using
`read_text`/`write_text`, and **flattened the whole file from CRLF to LF** — 1173 lines of it —
while the content diff stayed correct. `git diff` warned (*"LF will be replaced by CRLF"*); the
working-tree digest would have moved for a reason unrelated to my change. Repaired in **bytes**
(`read_bytes` / `replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')` / `write_bytes`), verified by
counting CRLF and bare LF before and after, and the warning is gone.

This is wave 51's planter lesson arriving at a *re-pinning* script rather than a mutant planter.
**Every scripted edit to a tracked file on this checkout must work on bytes**, not only the ones
that plant mutants. All subsequent citation re-pins in this lane were done with `read_bytes` /
`write_bytes` and a `count == 1` assertion per anchor.

---

## 6. THE CITATION RE-PIN COST, AND WHY ONE READ WOULD HAVE SHIPPED SIX STALE

MEASURED. Inserting into `bin/fleet.py` moved every citation below the insertion point. The brief
said to run the self-citation pin **to fixpoint** because *"one red/green read is a lower bound,
never a census."* That is exactly what happened:

| observation | findings |
|---|---|
| after the build | 7 |
| after re-pinning 9 | 3 |
| after re-pinning 2 | 1 |
| after re-pinning 1 | 1 |
| after re-pinning 1 | **0 — fixpoint, 21 passed** |

**Corrected 2026-08-09, in the results commit:** the first version of this table had six rows
(`7, 3, 1, 1, 1, 0`) and said *"11 distinct citations across 5 rounds"*. Both were wrong. The
observed sequence is **7 → 3 → 1 → 1 → 0** — five observations, four fixing rounds — and the count
is **13 self-citation edits** (9 + 2 + 1 + 1), plus the four `retired_sids` writer numbers re-pinned
at two citing sites. Miscounting my own instrument's output in the section about not trusting one
read of it is the joke writing itself, and it is left visible rather than silently corrected.

**Stopping after the first green read would have shipped 6 stale citations**, including the entire
13-number `_record_sids` union enumeration and the 9-number `_quarantine_artifacts` reader
enumeration — both `exactly=` censuses, which exist because a census once said "seven" when the
source held twelve.

**A second fixpoint was needed after the regression fix in §7.2**, and it converged in ONE pass with
14 edits — because that time I derived every target by AST up front instead of discovering them one
red run at a time. That is the cheaper way to run this instrument, and it is worth writing down: the
pin tells you *what* is stale one failure at a time, but the AST tells you *all* of it at once.

What was re-pinned: the four `retired_sids` writers at both citing sites
(`:7947, :8420, :12867, :18247` → `:7947, :8486, :12976, :18356`); the nine `_quarantine_artifacts`
readers; the thirteen `_record_sids` union sites; `cmd_kill:8851`/`cmd_respawn:8593` at two sites;
the ranged `cmd_respawn:8617-8619` → `:8683-8685`; `_registry_records_or_none`'s `:14955` → `:15064`;
`_sweep_husks`' presence-only `:10870` → `:10979`; and `_require_claim_holder`'s `:16561` → `:16670`
at a second, separate citing site that pass 2 did not reach.

**And the population that oracle cannot see is named in §3.6** — 894 cross-document
`bin/fleet.py:NNNN` citations it resolves none of. **Corrected 2026-08-09 (gate F2):** the one I
reported as current-tree and stale is neither; see §3.6's retraction. The count of current-tree
citations is **0**, the oracle's blind spot is real, and nothing was found in it. *This sentence is
one of the two the gate did NOT name — the everywhere-grep found it, which is exactly the duty
`docs/lanes/BRIEF-TEMPLATE.md` states for a discharge: grep the whole tree for the old claim, not
the diff, and not only the headings the gate quoted.*

---

## 7. FLOOR RESULTS

### 7.1 — RUN 1, at `f632d3e`: **THE PREDICTION MISSED, AND THE MISS WAS A REAL REGRESSION**

MEASURED. §0 predicted `4648 collected, 4633 passed, 14 skipped, 1 xfailed`. What happened:

| interpreter | collected | result |
|---|---|---|
| `py -3.13` | **4648** ✅ | **`2 failed, 4631 passed, 14 skipped, 1 xfailed`** ❌ (519.05s) |
| `py -3.10` | **4648** ✅ | **`2 failed, 4631 passed, 14 skipped, 1 xfailed`** ❌ (483.11s) |

```
FAILED tests/test_index_compose.py::TestAllFourComposePaths::test_path_4_respawn
FAILED tests/test_index_compose.py::TestAllFourComposePaths::test_path_4_respawn_stays_silent_without_an_index
```

Working-tree digest, printed before run 1, between the two interpreters, and after run 2 — three
times, identical, so neither run modified anything:

```
7458b8d86aa6bcfb55156400c305a10a50f20eaf8ffffc5cf20bce09636f1524  files=263  root=C:\proga\fleet-w52-live
```

**Two misses, and they are not the same kind.**

**Miss 1 — `files=263`, not the `262` I wrote.** A plain arithmetic slip: two files were added since
`64b43c2` (`git diff --name-status`: `docs/lanes/w52-live.md` and
`tests/test_respawn_retired_sweep.py`), so 261 + 2 = 263. I named the report in the same sentence in
which I failed to count it. Harmless to the floor, embarrassing in a section about deriving rather
than guessing.

**Miss 2 — the two failures, and this one was worth the whole exercise.** My build introduced a real
regression that nothing else in the lane had caught: not the mutation ledger (15/15 KILLED), not the
targeted files I ran after every edit, not the pre-build RED check. **The full floor found it, on
both interpreters, in a file about prompt composition.**

The mechanism is in §7.2. What I want on the record here is the methodological point, because it is
the brief's own doctrine landing on me: **predicting the floor is what turned a green-looking build
into a caught regression.** Had I not written `4633 passed` down in a commit beforehand, `2 failed`
in a file I had never touched would have read as pre-existing noise to be triaged, rather than as
*the prediction is wrong and I own the difference*. The value was not in being right.

### 7.2 — WHAT THE REGRESSION WAS

`tests/test_index_compose.py`'s four compose paths share one stub, `run=lambda *a, **k: None`. Three
of them never issue a stop. **Making the sweep reachable from `_cmd_respawn_native` made the fourth
one issue one**, and `_classify_native_cli_result(None)` raised `AttributeError` straight out of the
verb:

```
bin/fleet.py:8462  in _cmd_respawn_native   -> _sweep_retired_sessions(...)
bin/fleet.py:8767  in _sweep_retired_sessions -> _stop_native_session_status(...)
bin/fleet.py:10486 in _classify_native_cli_result -> if proc.returncode == 0:
E   AttributeError: 'NoneType' object has no attribute 'returncode'
```

A `run` returning `None` is not a production shape, so this could have been closed by fixing the
stub. **That would have been the wrong read.** The class is real and it predates the shape:
`_stop_native_session_status` catches `OSError`/`SubprocessError` around the subprocess and *nothing
else*, so any other failure out of one abandoned fork left the loop, skipped every remaining retired
sid, and took the calling verb down with it — on `kill`, aborting before the tombstone and the
dead-marking; on `respawn`, failing the operator's context reset because cleaning up a fork that was
already abandoned threw. **A best-effort operation that can abort its caller is not best-effort**,
and both call sites said "best-effort" in their docstrings while this was true.

Fixed in `bin/fleet.py` (`9e0170f`), per-sid, broad but never silent — the failure prints on the
same progress line every other outcome uses. **The extraction paid for itself here: one edit fixed
both call sites.** `test_a_raising_stop_CANNOT_abort_the_respawn` pins the *contract* rather than
the crash (the verb still reaches dispatch, the LATER retired sid is still attempted, the tombstone
is still written — a bare `try` that only stopped the crash satisfies the first alone), and
`M-W52-BESTEFFORT` proves it RED.

Also folded into that commit: `test_the_sid_is_still_retired_and_no_foreign_sid_enters` asserted only
the `respawned` event's `old_session_id` and never opened `retired_sids` — its name claimed an
invariant its body did not check. I made the body match the name rather than the reverse.

### 7.3 — RUN 2 PREDICTION, at `9e0170f` — WRITTEN BEFORE THE RUN, RESULTS BELOW

**PREDICTION: 4649 collected, `4634 passed, 14 skipped, 1 xfailed`, both interpreters.
`files=263`, unchanged.**

Derived: run 1's tree collected 4648; `9e0170f` adds exactly one test
(`test_a_raising_stop_CANNOT_abort_the_respawn`) and renames none, so **4649**. The two
`test_index_compose.py` failures are fixed and rejoin the passing set: 4631 + 2 + 1 = **4634**. No
files added or removed, so `files=263` holds. Skips and xfails untouched at 14/1.

Re-graded before this run and unchanged by it: **16 mutants, all KILLED**, floor green at 47,
`final sha256 == floor : True`, `real worktree bin/fleet.py : untouched`, and **13 pins, 0
uncovered**.

### 7.4 — RUN 2 RESULTS, at `9e0170f`: **PREDICTION HIT, EVERY TERM, BOTH INTERPRETERS**

MEASURED. §7.3 predicted `4649 collected, 4634 passed, 14 skipped, 1 xfailed, files=263`.

| interpreter | collected | result | wall |
|---|---|---|---|
| `py -3.13 -m pytest -q` | **4649** ✅ | **`4634 passed, 14 skipped, 1 xfailed`** ✅ | 513.19s |
| `py -3.10 -m pytest -q` | **4649** ✅ | **`4634 passed, 14 skipped, 1 xfailed`** ✅ | 581.24s |

Working-tree digest, printed before run 1, between the interpreters, and after run 2 — three times,
identical, `files=` included:

```
e9b4461641f5d592f2769cb1395e610e58a19e22549b6dfe447fdf63d870dc75  files=263  root=C:\proga\fleet-w52-live
```

`files=263` as predicted, and the hash differs from §7.1's because the code changed between the
runs — which is the point of the instrument being CHECKOUT-RELATIVE: it answers *"did this run
change anything here?"*, never *"is this tree that tree?"*.

**Receipt harness, run per CLAUDE.md's rule that a verifier without its own seed test proves
nothing** — `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/terminal-surface.md`:

```
SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.
EXTRACTION SELF-TEST PASSED: a receipt that stops being parsed is reported, not silently dropped.
pins resolved: 02bf276, 35cd7b7
parsed receipts: 11/11 reproduce exactly (14 fenced blocks, 0 unclassified, 0 volatile-skipped)
VERDICT:         pass -- 0 failure(s), 0 warning(s)
SELF-TEST VERDICT: PASSED -- the harness proved it can fail, on both seed classes.
EXIT:            0 (PASSED)
```

### 7.6 — RUN 3 PREDICTION (the F1/F3/F5 discharge) — WRITTEN BEFORE THE RUN

**PREDICTION: 4661 collected, `4646 passed, 14 skipped, 1 xfailed`, both interpreters.
`files=263`, unchanged.**

Derived, by collection rather than by counting `def test_` lines — which matters more than usual
here, because **12 of the 13 added cases come from two `parametrize`d pins over five shapes each**
and a `def`-count would have said 4:

- `tests/test_respawn_retired_sweep.py` collects **25**, up from 13 → **+12**.
  (`test_a_corrupt_retired_sid_cannot_abort_the_respawn` ×5,
  `test_a_corrupt_retired_sid_cannot_abort_the_KILL` ×5, `test_a_raising_stop_CANNOT_abort_the_KILL`,
  `test_the_dedup_still_keeps_the_OLDEST_position_and_the_cap_still_bites`.)
- Nothing else adds or removes a test: `git diff --name-status 12c238c..HEAD` is three **M**odified
  files, **zero added**, so `files=263` holds and `CHECK_COUNT_DOCS` is untouched.
- 4649 + 12 = **4661** collected; 4634 + 12 = **4646** passed; skips and xfails unmoved at 14/1.

Graded before this run and unchanged by it: **20 mutants, all KILLED**; floor green at 456 (+1
skipped) now that `tests/test_native.py` is in `TESTFILES`; `final sha256 == floor : True`;
`real worktree bin/fleet.py : untouched`; **25 pins, 0 uncovered**.

### 7.7 — RUN 3 RESULTS: **PREDICTION HIT EVERY TERM — and the DIGEST FENCE FAILED**

MEASURED. §7.6 predicted `4661 collected, 4646 passed, 14 skipped, 1 xfailed`.

| interpreter | collected | result | wall |
|---|---|---|---|
| `py -3.13 -m pytest -q` | **4661** ✅ | **`4646 passed, 14 skipped, 1 xfailed`** ✅ | 583.84s |
| `py -3.10 -m pytest -q` | **4661** ✅ | **`4646 passed, 14 skipped, 1 xfailed`** ✅ | 470.72s |

The +12 landed exactly where predicted, which is the term worth checking: **12 of the 13 added
cases come from two `parametrize`d pins over five shapes each**, so the `def test_` count a lazier
derivation would have used says 4. Collection said 25 for that file before the run and 25 after.

**AND THE CHANGE-NOTHING PROOF DID NOT RUN. Recorded because a missing instrument that nobody
mentions is indistinguishable from a passing one.**

All three digest calls in that run failed identically:

```
python.exe: can't open file 'C:\Users\Techn\.claude\jobs\f51d4b79/tmp/wtdigest.py':
[Errno 2] No such file or directory
```

**Cause, and it is a lesson about instrument durability rather than about this branch.** The digest
script from `docs/lanes/BRIEF-TEMPLATE.md` was never in the repo — I had written it to the session's
scratch directory. That directory is keyed to the session, the session changed between run 2 and run
3, and the tool went with it. **An instrument stored outside the repository is not durable across a
session boundary**, and a lane that runs for several sessions will lose it exactly once, silently,
at the point where it is being trusted most.

The command exited `rc=2` **because of this and not because of any test** — which is the one piece
of luck in it: had the digest been the *last* step rather than interleaved, a green test summary
above a failed exit code is precisely the shape that gets read as "passed".

**Re-established rather than argued away.** I recreated the script and re-ran BOTH interpreters with
the fence in place; §7.8 is that run. I am not deleting §7.7 in its favour: the unfenced numbers are
the ones the prediction was checked against, and the honest record is that they were measured
without their guard and then re-measured with it.

Two weaker facts do bound the unfenced pair, and they are worth stating for what they are:
`git status --porcelain` was empty immediately before run 3 and again immediately after (so no
tracked file changed and nothing untracked appeared), and the digest computed after run 3 —
`6eba3bbb…  files=263` — matches §7.8's before/after triple. That is evidence, not the proof the
instrument exists to give, and I am not presenting it as such.

### 7.8 — THE FENCED RE-RUN, ATTEMPT 1: **I CONTAMINATED MY OWN FENCE**

MEASURED, and reported rather than quietly re-run, because the failure is instructive and it is
entirely mine.

| step | digest |
|---|---|
| before 3.13 | `6eba3bbb67bf5641…  files=263` |
| **after 3.13 / before 3.10** | **`1a3e3a4515994964…  files=263`** ← **CHANGED** |
| after 3.10 | `1a3e3a4515994964…  files=263` |

Both interpreters passed identically (`4646 passed, 14 skipped, 1 xfailed`, 607.51s / 531.69s), and
`files=263` never moved — but **the before/after pair around the 3.13 run does not match, which is
exactly the condition the instrument exists to report.**

**The cause is not the test run. It is me.** I edited `docs/lanes/w52-live.md` — writing §7.7 and
re-deriving §2's line numbers — *while the fenced run was in flight in the background*.
`git status --porcelain` at the end names exactly one modified file, this report, and nothing else.
The 3.10 half (mid → after) is identical and therefore clean.

**The lesson, which is the second instrument failure in two runs and the same shape as the first:**
a fence is a claim about an interval, and **anything I do inside that interval is inside the fence**.
Backgrounding the run does not put my own edits outside it — it makes them concurrent, which is
worse, because the result still *looks* fenced. §7.7's failure was an instrument that vanished;
this one is an instrument that ran correctly and was defeated by the operator working beside it.
Together they are one rule: **freeze the tree for the whole run, and put the instrument somewhere
the run cannot outlive.**

I am not claiming the 3.13 result is invalid — the suite passed and the delta is a documentation
file that no test reads. I am claiming **I cannot prove it from this run**, which is a different
statement, and the honest one.

### 7.8b — THE FENCED RE-RUN, ATTEMPT 2: tree frozen, no concurrent edits

*Filled in by the commit after this one. Everything above is committed first, precisely so there is
nothing left for me to edit while it runs.*

### 7.9 — THE FLOOR LEDGER, END TO END

| tree | collected | result |
|---|---|---|
| `64b43c2` baseline (both interpreters) | 4636 | `4621 passed, 14 skipped, 1 xfailed` |
| `f632d3e` run 1 (both) — **predicted 4633 passed** | 4648 ✅ | `2 failed, 4631 passed, 14 skipped, 1 xfailed` ❌ |
| `9e0170f` run 2 (both) — **predicted 4634 passed** | 4649 ✅ | `4634 passed, 14 skipped, 1 xfailed` ✅ |
| `bd463f7` run 3, the discharge (both) — **predicted 4646 passed** | 4661 ✅ | `4646 passed, 14 skipped, 1 xfailed` ✅ |

Net against baseline: **+25 tests, 0 failures, skips and xfails unmoved at 14/1.**

**Three predictions: two hit, one missed** — and the ledger's shape is the argument. The two hits
confirm arithmetic. The miss found a regression in my own build that the 15-mutant ledger, the
per-edit targeted runs and the pre-build RED check had all passed over. The gate that reviewed this
branch reports the same thing happening to it: it predicted both its mutants would survive, one was
killed by a pin it had not found, and leaving the miss visible corrected one of its own findings
before it shipped. **That is twice in one wave that a missed prediction was worth more than a hit,
on two different lanes, and neither was worth anything until it was written down first.**

**Two predictions, one hit and one miss, and the miss was worth more.** The hit confirms the
arithmetic. The miss found a real regression in my own build that the 15-mutant ledger, the targeted
per-edit runs and the pre-build RED check had all passed over. If a gate takes one methodological
claim from this lane, take that one: **the floor prediction is not ceremony around the run, it is
the instrument.** Its value is not in being right — it is that a wrong prediction makes an
unexplained failure impossible to file as somebody else's noise.

---

## 8. WHAT I RAN, AND AGAINST WHICH HOME

**I ran zero `fleet` commands. Not one, against any home.**

This is not a claim of containment, it is the absence of an occasion for one: every proof in this
lane is a `pytest` run, an `ast.walk`, a `git archive` into a scratch directory, or a byte digest,
all inside `C:/proga/fleet-w52-live`. The build is a source change; nothing about it required
driving the CLI. So `FLEET_HOME` was never set, `--fleet-home` was never passed,
`~/.claude/fleet-homes.list` was never read or written, and `fleet init` was never invoked.

The live home at `C:/proga/claude-fleet` — 38 workers, one of them my supervisor — was touched in
exactly one way: **writing my journal** at `state/journals/w52-live.md`, which the brief ordered and
which is a plain file write to a gitignored runtime path, not a verb.

I want to be precise about why that is safe rather than merely assert it, because
`BRIEF-TEMPLATE.md` says not to read a clean containment audit as proof the fence worked. The fence
question does not arise here: the danger the stanza describes is a `fleet` verb resolving its home
through multi-fleet §5 step 2 (the sid) and landing on the live home. **No verb ran.** Had one been
needed — and this lane touches `kill`/`respawn`/tombstone code, so it would have been the dangerous
kind — the correct setup was `FLEET_HOME` set **plus `CLAUDE_CODE_SESSION_ID` removed from the child
env**, gated on `fleet home` printing the temp path compared NORMALISED, never `--fleet-home` on a
directory I was about to create.

Test-suite containment is separately enforced from inside the run, not by my care:
`tests/conftest.py`'s autouse `_never_touch_the_real_home` and `_never_touch_the_real_install`
redirect the planes, `_the_real_install_plane_is_byte_identical_afterwards` hashes the git-tracked
code plane before and after the whole session, and `_the_real_homes_list_is_untouched_afterwards`
does the same for the homes list. All green on every run reported here.

---

## 9. FOR THE ADVERSARIAL GATE — WHERE I WOULD ATTACK THIS

1. **The extraction touches `_cmd_kill_native`, which was working.** The strongest objection to this
   branch. My defence is §3.5 and the kill path's own five pins in `tests/test_native.py`, which are
   green and which `M-W52-M1` proves are load-bearing through the shared body. But it is a real
   scope judgement and a gate is entitled to disagree.
2. **`_archive_eligible`'s `no-outcome-record` gate** (§3.3) is the one behavioural delta outside the
   respawn path. I argue it is not a new state; check that argument rather than take it.
3. **§4's claim that the tombstone half is still reached** is BELIEVED, not MEASURED by me — it
   rests on reasoning about when a sid is roster-gone plus a *sibling gate's* poll data
   (`state=done status=idle pid=present`), not on a drive of my own. It is the weakest load-bearing
   sentence in this report, and note that its supporting evidence has already changed hands once
   (§4): the first steer I was given about that predicate did not survive its gate.
4. **`M-W52-ORDER` and `M-W52-CAP` kill the same single pin.** That pin asserts both the count and
   the identity of the 19 swept sids, so it genuinely separates the two defects — but if you think
   one test carrying two properties is one test too few, that is a fair finding.
5. **I did not fix `_cmd_respawn_supervisor` (§3.5).** A deliberate scope refusal with the
   correction stated; it is small if wanted. ~~or `docs/SPEC.md:84` (§3.6)~~ — **struck 2026-08-09
   (gate F2): there was nothing to fix there.** My refusal was right for the wrong reason, and that
   refusal is the only thing that stood between this report and a damaged spec. *This is the second
   of the two sites the gate did not name; the everywhere-grep found it.*
6. **The broad `except Exception` in `_sweep_retired_sessions` (§7.2)** is the kind of catch that
   normally deserves a fight. My case is that the sweep is documented best-effort at both call
   sites, that it is never load-bearing for either verb's outcome, and that it prints rather than
   swallows — but "catch everything" is a real hazard and a gate should press on whether some
   exception class ought to propagate after all (`KeyboardInterrupt` and `SystemExit` do, being
   `BaseException`; that is deliberate and is why the catch is `Exception`, not `BaseException`).
7. **The digest fence did not run on run 3** (§7.7) and I re-ran fenced rather than reasoning
   around it. A gate is entitled to treat the unfenced pair as unproven and read only §7.8.
8. **A gate should ask what ELSE became reachable.** §7.2's regression came from a code path being
   newly reached by a verb, not from the code being wrong. I fixed the instance and the class, but
   the honest generalisation is: `_cmd_respawn_native` now calls `_stop_native_session_status`,
   which it never did, so any test stubbing `run`/`which` for a respawn is newly exercising it. The
   full floor on both interpreters is my evidence that nothing else broke — that is a strong check,
   but it is the only one I ran for this specific question.

---

## 9A. THE GATE'S DISCHARGE (`w52-glive3` @ `4ab8650`, verdict GATING)

The gate is the authority; this section records what I did about it. It confirmed, so I do not
re-defend: `_roster_live_sids` byte-identical; `kill` byte-identical on 7 of 9 driven scenarios and
improved on the other 2; `--force` tombstones exactly once; the CRLF flattening could not have
reached a commit under `autocrlf=true`; the floor reproduced independently on a different tree; and
**both of my refutations of the dispatching brief were verified in my favour**.

### F1 (MAJOR, gating) — DISCHARGED, and the fix is WIDER than the gate's

A non-string element in `retired_sids` aborted `fleet respawn` with an unhandled `TypeError`. Base
tolerated it. `main()` does not catch `TypeError`, so it surfaced as a raw traceback from the verb
§11.4 makes the recovery lever, for the input class recovery is most likely to be looking at. **My
branch introduced it**, and §7.2's own sentence — *"a best-effort operation that can abort its
caller is not best-effort"* — is the rule it broke.

**The gate said one line and told me not to take that on faith. It is not one line.** MEASURED:

- By AST, the sweep body touches the untrusted value at **four** sites, not the three the gate
  listed — it missed the truncation inside the M1 skip's own message.
- By driving every shape through both verbs, there is a **second raise site the gate did not name at
  all**: `dict.fromkeys` in **both callers**, which hashes every element.

| element | raised at | in |
|---|---|---|
| `123`, `True`, `3.5` | the progress-line truncation | `_sweep_retired_sessions` |
| `{"a":1}`, `["x"]` | `dict.fromkeys` | **`_cmd_respawn_native` and `_cmd_kill_native`** |
| `None` | — (falsy, already filtered) | — |

**A fix confined to the sweep body would have left `dict` and `list` aborting both verbs.** So the
fix is an `isinstance` skip placed FIRST in the loop, above all four sites, plus
`_ordered_unique_sids` replacing `dict.fromkeys` at both call sites — preserving first-occurrence
semantics exactly, because the cap depends on them, and passing unhashable values through rather
than dropping them so the sweep body can report them to the operator.

Re-driven after the fix, all five shapes on both verbs: verb completes, corrupt entry reported on
stderr, **the good sid is still swept**, tombstone still written, worker still marked dead.

### F3 (MAJOR) — DISCHARGED, and this is the lesson worth keeping

The gate planted a guardless `kill` (its G1) and it **SURVIVED all 4649 tests**, because every pin
on the shared body drove `respawn`. `M-W52-KILLGUARD` replants that mutant here. MEASURED, it is now
caught by **exactly the six new kill-side pins and no respawn pin** — plus a `test_native.py` pin
the driver can only see because of F5 below.

> **A shared helper needs a pin per caller.** The mutant that kills it from one caller can survive
> from the other, and extracting a body is precisely what makes that possible. Extraction
> single-sources the code; it does not single-source the coverage, and the coverage is what a
> successor edit will actually run into.

### F5 (MINOR) — DISCHARGED. `tests/test_native.py` joins `TESTFILES`

The gate's finding was about a **claim**: §9.1 defended the extraction with kill's five pins *"which
`M-W52-M1` proves are load-bearing through the shared body"*, and the driver never ran that file, so
the instrument cited structurally could not produce the evidence. Note the shape of the original
mistake, because it recurs — the wave-52 repair that made `TESTFILES` a tuple added the file the NEW
pins were in, not the file the extraction put at RISK.

### F2 (MAJOR, gating) — DISCHARGED by retraction; see §3.6, §6, §9.5 and §10.2

**The gate named two sites. The everywhere-grep found four.** `docs/lanes/BRIEF-TEMPLATE.md`'s rule
for a discharge is to grep the whole tree for the *old* claim rather than the diff or the headings
the gate quoted — and §6's closing sentence and §9.5's item 5 both carried the struck framing
onward. Both are corrected in place and marked as the two the gate did not name.

### F4, F6, F7, F8 — accepted, not actioned in this discharge

F4 (the guardless copy now lacks **three** guards, and its *"mirroring `_cmd_kill_native`"* comment
became less true) is folded into §10.1. F6 (`kill`'s PRIMARY stop still aborts before the tombstone
— pre-existing, unchanged by me, and arguably correct since that stop's outcome IS load-bearing),
F7 (the liveness→write window widens to ≤100 s and the write does not re-check the sid — a
pre-existing race this branch widens) and F8 (the progress line truncates at 8 chars while the stop
ref splits at `-`, so `retired30`…`retired39` all print as `retired3`) are real and I have not
touched them. **F7 is the one I would look at next** — it is the only one that is a property of my
change rather than of code I did not write.

---

## 10. RECOMMENDED SUCCESSOR SLICES

Neither is a blocker on this branch.

1. **Carry the guards to `_cmd_respawn_supervisor`** (§3.5). It is now a ~3-line change: the shared
   `_sweep_retired_sessions` exists and takes `other_current_sids` as a parameter, so that call site
   gains the guards by calling it. **Corrected per gate F4: it is now missing FOUR guards, not two**
   — the M1 ownership skip, the M5 progress line, the best-effort `try`, and the corrupt-element
   skip; the last two are guards *this lane created* and did not apply at the third call site of the
   same loop in the same file. It also needs `bin/fleet.py`'s *"the retired parents are swept
   best-effort, **mirroring `_cmd_kill_native`**"* comment fixed: `_cmd_kill_native` no longer
   contains that loop at all, so a reader following the pointer lands on a function that no longer
   does what the pointer promises — the extraction made that claim less true and did not update it.
   Needs its own pins and mutants; note the gate measured that its *existence* IS pinned
   (`tests/test_sup_tombstone.py:473`), so only the guards are uncovered.
2. ~~**Re-pin `docs/SPEC.md:84`**: `bin/fleet.py:61-110` → `:117-223`.~~ **WITHDRAWN 2026-08-09,
   gate `w52-glive3` F2 — DO NOT DO THIS.** The citation is correct at the commit `docs/SPEC.md` §0
   pins itself to (`c63d7dd`), where 57 of 64 anchors resolve against 0 at HEAD. Acting on it would
   have taken a document internally consistent at one commit and made it half-`c63d7dd`,
   half-HEAD with no marker saying which — manufacturing the *look* of a repair on a document that
   needed none, in the spec of record. See §3.6's retraction.

   **What IS worth a successor slice is the gap underneath it:** `_HISTORICAL_PREFIXES` classifies
   by **path prefix**, and `docs/SPEC.md` declares its pin in **prose**, which no instrument reads.
   A document that pins itself should be able to say so in a way the tooling can see — a
   machine-readable pin marker, or an explicit entry. That is a real hole and it is what I should
   have filed instead of a false citation finding.
3. **`w50/live` §6** (the `RosterLiveness` collapse) is untouched and its `INVERT-ON-BUILD` pins in
   `tests/test_liveness_readers.py` are still green and still waiting. §6.7's owed decision now
   carries a MEDIUM, partly non-reproducing defect and a BLOCKING objection to the obvious fix
   (§4) — which is an argument for deciding it deliberately, not for deciding it quickly.
