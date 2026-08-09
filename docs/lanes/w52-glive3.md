# w52-glive3 — adversarial gate on `w52/live` @ `12c238c`

**Lane:** gate. Branch `w52/glive3`, forked from the subject at `12c238c`. Subject range
`64b43c2..12c238c`.

## VERDICT: **GATING**

Two MAJOR findings, one of them a regression this branch introduces. Neither is a design objection:
**the gap is real, the extraction is the right shape, and I could not break `kill` with it.** Both
fixes are small. What gates is that one of them is a new failure on the recovery verb, and the other
is a false finding in the committed report whose recommended successor slice would damage the spec
of record.

| # | grade | finding | evidence |
|---|---|---|---|
| F1 | **MAJOR — gates** | a corrupt/hand-edited `retired_sids` element now aborts `fleet respawn` with an unhandled `TypeError`; base respawned fine | MEASURED, zero test doubles |
| F2 | **MAJOR — gates** | lane §3.6 is a false finding, and §10.2's successor slice would corrupt a correct citation in `docs/SPEC.md` | MEASURED |
| F3 | MAJOR | the new best-effort guard is pinned from only one of its two callers, and the unpinned one is `kill` | MEASURED — a mutant reintroducing the w52 regression on `kill` **survived all 4649 tests** |
| F4 | MINOR | `_cmd_respawn_supervisor`'s copy now lacks THREE guards, not two, and its "mirroring `_cmd_kill_native`" comment became less true | MEASURED |
| F5 | MINOR | the mutation driver structurally cannot support §9.1's defence of the extraction | MEASURED |
| F6 | MINOR | `kill`'s PRIMARY stop still aborts the verb before the tombstone — the consequence §7.2 names is still reachable | MEASURED |
| F7 | MINOR | respawn's liveness→write window widens from ~0 s to ≤100 s, and the write does not re-check the sid | DERIVED from measured constants |
| F8 | MINOR, not this lane's | the progress line truncates at 8 chars while the stop ref splits at `-`, so distinct sids print identically | MEASURED |

Confirmed and **not** findings: `_roster_live_sids` byte-identity; the `--force` tombstone written
exactly once; `kill` byte-identical on every non-exception scenario; the floor; the CRLF flattening.

---

## 0. WHAT I RAN, AND AGAINST WHICH HOME

**`fleet` commands run: ZERO. Not one, against any home.**

The brief's carve-out applies exactly as written: the subject lane ran no `fleet` verbs and neither
did I, so `fleet home` would have been my *sole* exposure rather than a fence. I skipped it and say
so here. `FLEET_HOME` was never exported, `--fleet-home` never passed, `~/.claude/fleet-homes.list`
never read or written.

Every drive in this report is an in-process call into `fleet.py` with `fleet.FLEET_HOME` assigned to
a fresh `tempfile.mkdtemp()` and `which=lambda _: ...`, so **no real `claude` executable was ever
resolved and no subprocess was ever spawned** — asserted, not assumed: the corrupt-registry probe
runs with a `run` that raises `AssertionError` if called at all, and reports `subprocess attempts: 0`.

The live home at `C:/proga/claude-fleet` (38 workers, one of them the supervisor that dispatched me,
three sibling lanes working in it) was touched in exactly one way: writing
`state/journals/w52-glive3.md`, which the brief ordered. That is a file write to a gitignored runtime
path, not a verb.

**Which tree every reading came from.** I am on `w52/glive3` @ `12c238c` in
`C:/proga/fleet-w52-glive3`. Readings are labelled `HEAD` (that worktree, or a `git archive 12c238c`
export byte-identical to it), `BASE` (a `git archive 64b43c2` export), or `c63d7dd` (the commit
`docs/SPEC.md` pins itself to). The two exports live under the job tmp dir and were verified
byte-identical to their checkouts by sha256 before use.

---

## 1. F1 — **MAJOR, GATING.** The new sweep aborts `respawn` on input that BASE tolerated

MEASURED, at BASE and HEAD, **with no `run` double at all**.

`_sweep_retired_sessions` performs **three** operations on each untrusted `retired` value. The w52
`try` wraps only the middle one:

```
bin/fleet.py:8758   for retired in retired_sids:
bin/fleet.py:8759       if retired in other_current_sids:                  <-- OUTSIDE the guard
bin/fleet.py:8787           _ok, outcome = _stop_native_session_status(..) <-- the only one INSIDE
bin/fleet.py:8792       print(f"... {retired[:8]} ... {outcome}")          <-- OUTSIDE the guard
```

`retired_sids` is read straight out of `state/fleet.json`. A non-string truthy element there is
exactly the input class this function's **own M1 docstring** names as its reason to exist — *"this
only guards a corrupted or hand-edited registry."* Every shape aborts the caller:

| `retired_sids` element | exception out of `_sweep_retired_sessions` | subprocess attempts |
|---|---|---|
| `123` | `TypeError: 'int' object is not subscriptable` | 0 |
| `{"a": 1}` | `TypeError: unhashable type: 'dict'` | 0 |
| `["x"]` | `TypeError: unhashable type: 'list'` | 0 |
| `True` | `TypeError: 'bool' object is not subscriptable` | 0 |
| `3.5` | `TypeError: 'float' object is not subscriptable` | 0 |

Driven with `which=lambda _: None` — which is precisely what `shutil.which("claude")` returns on a
machine where claude is not on PATH, so this is a faithful production state, not a stub shape — and
a `run` that raises if called. It was never called.

**The regression.** Same input, whole verb, `retired_sids=[123, "good-b"]`:

| verb | BASE `64b43c2` | HEAD `12c238c` |
|---|---|---|
| `cmd_respawn` (Q1 not-live) | **reached dispatch normally** | **aborts, `TypeError`, no tombstone, nothing stopped** |
| `cmd_kill` | aborts before tombstone + dead-marking (`AttributeError`) | aborts before tombstone + dead-marking (`TypeError`) |

`kill` was already broken on this input and is no better. **`respawn` was fine and is now broken.**
This branch introduced it, on the verb `w50/live` §11.4 makes the recovery lever, for the input class
recovery is most likely to be looking at.

**It surfaces as a raw traceback.** `main()` catches `FleetCliError, ClaudeNotFoundError, ValueError,
FleetLockTimeout, UnsupportedPlatformError` (`bin/fleet.py:21790`). `TypeError` is not among them, so
the operator gets an unhandled Python traceback from `fleet respawn`, not a `fleet:` refusal.

**Why this is the branch's own finding, not a pre-existing one.** §7.2 states the rule this
violates, in the lane's own words: *"A best-effort operation that can abort its caller is not
best-effort."* The fix applies that rule to one of the three statements that touch the untrusted
value. The lane then re-states the guarantee in the code comment — *"Per-sid, so one bad sid cannot
cost the rest of the sweep"* — which is false for every shape in the table above.

**Cost to fix:** one line. `f"{retired}"[:8]` (or `str(retired)[:8]`), plus moving the membership
test inside the `try`, or filtering non-`str` in both callers. I am a gate and have fixed nothing.

---

## 2. F2 — **MAJOR, GATING.** §3.6 is a false finding, and §10.2 would corrupt the spec of record

MEASURED, at three trees.

The lane reports (§3.6) that `docs/SPEC.md:84` carries a **stale current-tree citation**:
`bin/fleet.py:61-110` for path helpers *"really at `:117-223`"*, and recommends (§10.2) re-pinning
it. The brief that dispatched me asked me to confirm it as *"the third independent instance this
wave of citations that were already wrong before anyone touched the file."*

**I cannot confirm it. `docs/SPEC.md` is a pinned document and the citation is correct at its pin.**

`docs/SPEC.md` §0, first line: *"Everything here is **descriptive of `bin/fleet.py` at `c63d7dd`***
… Line numbers below are at `c63d7dd` and will drift; the function names are the durable anchors."*
Immediately below it, a blockquote titled **"PIN STALENESS — read this before trusting a line
number"** says *"**every `@NNNN` anchor below is off by hundreds of lines.** Grep the function name;
never seek to the number."*

At `c63d7dd`, resolved by AST:

| helper | `c63d7dd` | `64b43c2` | `12c238c` |
|---|---|---|---|
| `state_dir` | **61** | 117 | 117 |
| `pin_pass_path` | **110** | 223 | 223 |

`bin/fleet.py:61-110` is **exactly right** at the commit the document pins itself to. Systematically,
over all 64 `` `name` @NNN `` anchors in `docs/SPEC.md`:

```
anchors correct at c63d7dd :  57 / 64
anchors correct at 64b43c2 :   0 / 64
anchors correct at 12c238c :   0 / 64
```

The 7 non-matches are 3 non-definitions my resolver cannot bind (`dontask`, `release`,
`over_ceiling` — CLI verbs and status literals, not functions) and 4 anchors pointing a few lines
inside the function they name. Nothing there is rot.

**Consequences, in order of seriousness:**

1. **§10.2 as written is destructive.** Re-pinning `:61-110` → `:117-223` would take a document that
   is internally consistent at one commit and make it half-`c63d7dd`, half-`12c238c`, with no marker
   saying which is which — in the spec of record, whose own §0 tells the reader every number is at
   `c63d7dd`. This is the hazard the brief names (*"a re-pin that shifts an already-wrong citation by
   the diff's delta manufactures the look of a repair"*) running in the worse direction: re-pinning a
   **correct** citation to manufacture a repair on a document that needed none. The lane's §0 banner
   also records that re-pinning SPEC wholesale *"is a campaign, not an edit"* — §10.2 proposes
   exactly the one-line edit that banner forbids.
2. **The repo has already ratified the rule §10.2 breaks, in these words.**
   `tests/test_doc_claims.py`'s `_HISTORICAL_PREFIXES` docstring, ratified 2026-08-05: *"a reference
   is rot only when it claims the CURRENT tree; a pinned receipt and a quoted argument are claims
   about a PAST tree and stay true. **Fixing them would FABRICATE.**"* `docs/SPEC.md:84` is a claim
   about a past tree. §10.2 proposes the fabrication that sentence forbids.
3. **The lane's census number is wrong.** §3.6 reports *"894 citations across 155 tracked `*.md`;
   893 historical/pinned; **1** current-tree."* The correct count of current-tree `bin/fleet.py`
   citations is **0**.

**Root cause, stated fairly.** The lane's classifier is not arbitrary — it mirrors the repo's own
`_HISTORICAL_PREFIXES`, which is a **path-prefix** list (`docs/lanes/`, `docs/reviews/`,
`docs/specs/**`, `knowledge/`, …). `docs/SPEC.md` is not under any of those prefixes, so by the
tooling's rule it *is* a current-tree document. The governing statement is in its prose instead, and
no instrument reads prose. So this is a real gap in the repo's classification, not merely a lane
error — but the lane quoted §0's neighbourhood while reporting the opposite of what §0 says, which
is the part a gate has to call.
3. **The right instinct produced the wrong answer.** §6's closing move — *"name that oracle's
   population before trusting its colour"* — is correct method, and `tests/test_self_citations.py`
   does resolve `bin/fleet.py`-about-itself only (verified: its own docstring lists
   `SPEC.md:204`-style cross-document citations under **NOT PINNED**). The blind spot is real. What
   was found in it is not.

**The lane's decision not to fix it was right, for the wrong reason.** It refused on scope
(*"I would rather hand the gate a measurement than a silent edit to `docs/SPEC.md`"*). The correct
reason is that there is nothing to fix — and that refusal is the only thing standing between this
report and a damaged spec. §3.6 and §10.2 should be struck or corrected before this report is
treated as a record.

---

## 3. THE TWO REFUTATIONS — both verified, both in the lane's favour

### 3.1 "The tombstone is never written on this path" — the LANE is right, the BRIEF is wrong

MEASURED, independent drive written from the code rather than from the lane's test file, at both
trees. Tombstones counted for `old_sid`, stops counted by argv:

| drive | BASE tombstones / stops | HEAD tombstones / stops |
|---|---|---|
| `--force`, old sid roster-live | `["stopped"]` / `["aaaabbbb"]` | `["stopped"]` / `["aaaabbbb"]` |
| `--force`, + 2 prior retired | `["stopped"]` / `["aaaabbbb"]` | `["stopped"]` / `["aaaabbbb","p1","p2"]` |
| bare respawn, Q1 not-live | **`[]` / `[]`** | `["stopped"]` / `["aaaabbbb"]` |
| bare respawn, not-live + 2 prior | **`[]` / `[]`** | `["stopped"]` / `["p1","p2","aaaabbbb"]` |
| `--force`, re-verify still live (abort arm) | `["stopped"]` / `["aaaabbbb"]` | `["stopped"]` / `["aaaabbbb"]` |

The `--force` arm wrote a tombstone at BASE. The brief's *"On this path it is never written"* is
false as stated; the lane's narrower reading — never written **on the not-live branch**, because the
call sits inside `if old_live:` — is correct.

**And the build does not double-write.** `--force` yields exactly one `stopped` tombstone and
exactly one stop of the old sid at HEAD. The guard that achieves it is `if not old_live:` on the new
write plus `not (old_live and s == old_sid)` in the sweep set. Building on the brief's literal claim
would have produced `["stopped", "stopped"]` on every `--force` respawn, as the brief suspected.

Row 5 also confirms the abort arm is unchanged: a `--force` that cannot re-verify the stop aborts
*before* the sweep, so `p1` is never touched, at both trees.

### 3.2 `_cmd_respawn_supervisor` is NOT "a path that already does this right" — the LANE is right

MEASURED. `_cmd_respawn_supervisor` is **byte-identical between `64b43c2` and `12c238c`** (source
sha256 of the AST segment equal), and its copy of the loop at `bin/fleet.py:9708-9712` is:

```python
for retired in list(rec.get("retired_sids", []) or [])[-_RETIRED_SID_SWEEP_CAP:]:
    if retired and retired != old_sid:
        _stop_native_session_status(
            retired, run=run, which=which,
            timeout=_RETIRED_SID_SWEEP_TIMEOUT_SECONDS)
```

It has the cap and the timeout. It has neither the M1 ownership guard nor the progress line, and it
discards `(ok, outcome)`. The brief pointed at a defective exemplar. **This is the strongest
available argument that extracting beat copying, and I agree with the lane that it is.**

---

## 4. F4 — the guardless copy is now missing THREE guards, not two

MINOR, MEASURED. The lane's §3.5 and §10.1 count two missing guards. After §7.2 landed there are
**three**: the M1 ownership skip, the M5 progress line, and now the best-effort `try`. The third is
a guard *this commit created*, and it was not applied at the third call site of the same loop in the
same file.

**What that copy does NOT lack, corrected against my own wrong prediction (§6.3):** coverage of its
existence. `tests/test_sup_tombstone.py:473`
(`TestCrit1StaleSidStop::test_respawn_stops_the_fork_before_dispatching`) drives the supervisor
respawn and asserts the retired parent is stopped before dispatch; my G2 mutant, which neuters that
loop, goes RED there. I predicted it would survive and it did not. So the gap at that site is the
three guards, not the sweep.

**Grading the decision to leave it.** For M1 and the progress line: defensible, and I would not gate
on it — they are pre-existing, the site has its own test surface, and the brief's stated preference
is *"one closed gap than half a refactor."* For the best-effort guard the framing is what I object
to, not the scope: §7.2's *"The extraction paid for itself here: one edit fixed both call sites"* is
true of the two callers of the shared body and reads as though it covered the loop, which it does
not. `_cmd_respawn_supervisor` can still be aborted by one abandoned fork — and its
`write_tombstone_outcome(name, old_sid, "stopped")` sits **four lines below** the loop, so the
consequence is exactly the one §7.2 says must not happen.

**And the extraction made a claim at that site LESS true without updating it** — the brief asked
specifically whether each repair reached everywhere the repaired claim appears, "docstrings on both
callers especially, since the extraction moved shared prose." MEASURED, `bin/fleet.py:9703`:

> Primary gets the full timeout; the retired parents are swept best-effort, **mirroring
> `_cmd_kill_native`**.

At BASE that cross-reference was already only partly true. At HEAD it is worse on two counts:
`_cmd_kill_native` no longer contains the loop at all, and its sweep now carries a best-effort guard
this copy does not. A reader following the pointer is sent to a function that no longer does what
the pointer promises. That comment is one of the places the repaired claim appears, and the repair
did not reach it.

Successor slice §10.1 remains the right call. It should say three guards, and it should fix that
sentence.

---

## 5. THE BUILD — extraction is correct, and it did NOT break the caller it came from

### 5.1 The whole diff, reduced

MEASURED by AST at both trees, docstrings and comments stripped and re-emitted through
`ast.unparse`, so only executable code is compared. The 205-line `bin/fleet.py` diff is **exactly
three semantic edits**:

1. `_cmd_respawn_native` gains 7 statements (the sweep set, the locked `other_current_sids` read,
   the call, the `if not old_live:` tombstone).
2. `_sweep_retired_sessions` is added.
3. `_cmd_kill_native` loses 6 statements and gains 1 call.

Functions with **any** text change: 9. Functions with an executable-code change: **2**, plus the new
one. The other 7 are citation renumbers in comments and docstrings. Nothing was removed.

### 5.2 `kill` — driven, not read

MEASURED. Nine scenarios, driven through `fleet.cmd_kill` at BASE and HEAD, capturing rc, exception,
every `run` argv **with its `timeout` kwarg in order**, every stderr line, the registry record, the
outcome store and the event log, serialised to JSON and diffed.

**Seven of nine are byte-identical between the trees:**

- 2 retired sids, rc=0 — same stops, same order, same progress lines.
- 50 retired sids — same 20 swept (`retired30..retired49`), **`[-cap:]` still means most recent**,
  primary first at `timeout=30`, all 20 retired at `timeout=5`.
- rc=1 — same classified outcome (`failed`, never `timeout`).
- M1 collision — same skip, same stderr note, victim's sid never stopped.
- primary stop raises — identical abort at both trees (see F6).
- no sid — identical refusal.
- duplicate retired sids — identical dedup.

**The only two that differ are the deliberate exception-safety delta**, and in both the change is a
strict improvement: at BASE `kill` aborted with the record still `status:"working"`, no `killed`
outcome, no `killed` event and the second retired sid never attempted; at HEAD it prints the failure,
sweeps the rest, tombstones and marks dead.

I set out to break `kill` with this extraction and could not. **The brief's likeliest-wrong
suspicion — "that extraction is safe for `kill`" — was not wrong.**

### 5.3 The cap is a wall-time bound, and still is

MEASURED, both callers. `retired_sids` on the record after a kill of a worker with 50 retired sids
still holds **all 50** — the cap never truncates the stored list, exactly as `_cmd_kill_native`'s
docstring says. `[-cap:]` is applied after an order-preserving `dict.fromkeys` dedup at both call
sites and after the `old_live` filter on respawn; oldest-first order survives, so it still means
*most recent*. `sorted()` appears in neither.

### 5.4 Q1 is untouched — verified mechanically

MEASURED. `_roster_live_sids` source segments at `64b43c2` and `12c238c` hash to the identical
sha256. So do `_record_sids`, `_stop_native_session_status`, `_stop_native_session`,
`_classify_native_cli_result`, `write_tombstone_outcome`, `_archive_eligible`, `has_fresh_outcome`
and `_cmd_respawn_supervisor`. **§6.7's owed decision is still owed.** The load-bearing scope fence
of the whole lane holds.

I also checked the one delta §3.3 concedes. `has_fresh_outcome`'s signature default is
`kinds: tuple = ("result",)` and all **three** call sites (`recompute_worker_native` ×2,
`_cmd_send_native`) pass no `kinds` — MEASURED by AST — while `TOMBSTONE_KINDS = ("killed",
"interrupted", "stopped")`. So the new tombstone cannot reach the status engine. The §3.3 table is
correct where I checked it.

### 5.5 F7 — the window the extraction opened

MINOR. DERIVED from measured constants, not driven.

`_cmd_respawn_native` now takes `fleet_lock()` **twice**: once for `other_current_sids`, then again
for the record write. Between them it performs up to `_RETIRED_SID_SWEEP_CAP` (20) stops at
`_RETIRED_SID_SWEEP_TIMEOUT_SECONDS` (5 s) each — **up to ~100 s of subprocess work outside the
lock**, between Q1's roster read and the registry write.

On BASE the bare-respawn path went roster-fetch → lock → write with essentially no gap; the `--force`
arm already had one. The write block re-reads under the lock and refuses on `rec is None` and on
`not is_native(rec)`, but **does not check that `rec["session_id"]` is still `old_sid`** — so a
respawn or fork-steer that completes inside the window is overwritten, and the sid it minted never
enters `retired_sids` and is never swept. The race pre-exists; this branch widens it on the most
common path. I did not drive it and do not claim it is reachable in practice with one operator.

---

## 6. THE MISSED PREDICTION — the finding is real, the generalisation is not fully established

### 6.1 The defect reproduces beyond the stub — but I could not construct it with real
`subprocess.run`

MEASURED, and this materially changes the grade, as the brief said it would.

**What I could show.** The run-1 failure is not specific to a `run` that returns `None`. Driving
`kill` at BASE with a `run` that raises a plain `ValueError` on one retired sid gives the same
outcome: the verb aborts, the record stays `status:"working"`, no `killed` outcome, no event, the
next retired sid never attempted. So the class is wider than the one stub shape, and the lane's
refusal to close it by fixing the stub was correct.

**What I could not show.** I tried and failed to make an exception escape
`_stop_native_session_status` with `run=subprocess.run` and `which=shutil.which`. It is harder than
§7.2 implies: it catches `ClaudeNotFoundError` around the resolver and returns `(False, "no-claude")`;
it catches `OSError` **and** `subprocess.SubprocessError` around the call (so `TimeoutExpired` is in);
`_resolved_from_current_directory` catches `OSError` internally; and `_classify_native_cli_result`
only touches `returncode`/`stdout`/`stderr`, which a real `CompletedProcess` always has. Every
internal caller threads `run`/`which` down from a CLI entry point that defaults to the real pair —
MEASURED, no fleet code passes a wrapper.

So §7.2's *"any surprise from one abandoned fork"* is **BELIEVED, not established**, for the
production pair. The guard is defensive depth rather than a closed reachable hole — **except by the
route in F1, which is reachable, needs no double at all, and the guard does not cover.**

### 6.2 The fix does not silence what it swallows

MEASURED. The failure prints on the same progress line every other outcome uses
(`... error (ValueError) -- not retried`), one line per sid, and the sweep continues to the next sid.
`BaseException` is deliberately not caught, so `KeyboardInterrupt`/`SystemExit` still propagate. Of
the lane's own §9.6 concern I found nothing to add: best-effort did not become silent.

### 6.3 F3 — but the guard is pinned from only one of its two callers

**MAJOR, MEASURED.** `grep` over `tests/` finds exactly one test asserting that a raising stop cannot
abort a verb: `test_a_raising_stop_CANNOT_abort_the_respawn`. It drives **respawn**. `kill`'s five
sweep pins in `tests/test_native.py` (`test_stops_retired_sids_best_effort` and the four beside it)
assert the sweep happens, the timeouts, the cap, the progress line and the M1 skip — **none of them
asserts exception safety.**

This matters because §7.2's own reasoning says the `kill` consequence is the worse one: *"on `kill`,
aborting before the tombstone and the dead-marking."* The guard that prevents it is pinned only from
the caller where the consequence is milder.

**Planted, on bytes, in the working tree, line count preserved** — `tests/test_self_citations.py`
resolves every citation `bin/fleet.py` makes about itself, so a mutant that shifts line numbers goes
RED for a reason nobody can attribute:

- **G1** — the shared body grows `best_effort=True` and `_cmd_kill_native` passes `best_effort=False`.
  A realistic successor edit ("the terminal verb should surface stop errors"), not vandalism. Every
  respawn pin takes the default and stays green by construction.
- **G2** — `_cmd_respawn_supervisor`'s hand-written loop is neutered with `[:0]`, preserving both
  constant references and the line count, so only a *behavioural* pin on that sweep could kill it.

G1 verified live before grading: with it planted, `kill` against a raising retired stop aborts with
the record left `status:"working"` — **the exact w52 regression, reproduced on the caller the lane
did not pin** — while the benign scenario is unaffected.

**PREDICTION, written into my journal in the turn before the run: `4649 collected, 4634 passed, 14
skipped, 1 xfailed` — BOTH SURVIVED.**

**RESULT — the prediction MISSED, and the miss corrected one of my own findings before it shipped:**

```
FAILED tests/test_sup_tombstone.py::TestCrit1StaleSidStop::test_respawn_stops_the_fork_before_dispatching
1 failed, 4633 passed, 14 skipped, 1 xfailed in 580.45s (0:09:40)
```

| mutant | verdict | what it means |
|---|---|---|
| **G1** — `kill` loses the best-effort guard | **SURVIVED** | **nothing in 4649 tests notices.** F3 confirmed. |
| **G2** — the supervisor's sweep stops sweeping | **KILLED** | I was wrong; it IS behaviourally pinned. |

**G1 survived a full 4649-test suite on both the property and the collateral.** Collection was
unchanged (4649) because the plant preserved the line count, so `tests/test_self_citations.py` stayed
green and the one red is attributable. A future edit that reintroduces the exact w52 regression on
`kill` — the caller whose failure mode §7.2 calls the worse one — ships green.

**G2 killed my own hypothesis, by a pin I had not found.**
`tests/test_sup_tombstone.py:473` drives `cmd_respawn` against the supervisor and asserts
`HOLDER_SID in stopped` — the retired parent must be swept before dispatch. It never names
`_RETIRED_SID_SWEEP_CAP`, which is why my grep for that constant missed it and why I predicted
SURVIVED. **`_cmd_respawn_supervisor`'s sweep is pinned for the fact that it sweeps.** F4 is
corrected accordingly below: what that copy lacks is the M1 guard, the progress line and the
best-effort guard — not coverage of its existence.

I am leaving the wrong prediction visible rather than editing it out. It is the lane's own §7.5 point
landing on me: the value was not in being right. Had I not written `BOTH SURVIVED` down first, a red
in a supervisor tombstone file would have read as collateral to triage rather than as *my hypothesis
about the supervisor sweep is false and I own the difference* — and a softer, wrong version of F4
would have shipped.

---

## 7. THE INSTRUMENTS

### 7.1 F5 — the driver cannot support the defence §9.1 rests on

MINOR, MEASURED. `tools/mutate_liveness.py` grades every mutant by running **only `TESTFILES`** —
`tests/test_liveness_readers.py` and `tests/test_respawn_retired_sweep.py`. `tests/test_native.py`,
which holds `kill`'s five sweep pins, is not in it.

§9.1 defends the extraction with *"the kill path's own five pins in `tests/test_native.py`, which are
green and which `M-W52-M1` proves are load-bearing through the shared body."* **`M-W52-M1` cannot
prove anything about `tests/test_native.py`, because the driver never runs that file.** The claim may
well be true in substance — disarming the M1 guard in the shared body should redden kill's M1 pin —
but the instrument cited for it structurally cannot produce that evidence, and §5.4's own repair
("the driver graded one file and I added pins to a second") added the file the new pins were in, not
the file the extraction put at risk.

The driver's *stated* contract is honest about this — *"a mutant that SURVIVES is a defect in the
test file"* — but §9.1 reads the ledger as a statement about the whole suite.

### 7.2 The ledger, the byte-exactness proof, and the pin quality

MEASURED where I checked. The ledger holds **16** mutants, ids as claimed. `text_roundtrip_is_byte_exact`
runs before the floor and aborts `rc=5` otherwise, which is the right ordering and a real repair of
wave 51's lesson; I independently confirmed its premise — `git archive` output for this repo is
byte-identical to the checkout (sha256 equal, 21797 CRLF, 0 bare LF), so the text round-trip is
genuinely exact **here**.

One note on it, not a finding: the check **writes to the target before comparing**, so on a platform
where it fails it leaves the scratch export corrupted and returns without restoring. Harmless because
`build_scratch` rebuilds the export every run, but it is the wave-51 "a pin whose failing path
performs the act it forbids" shape, one notch down.

I read all 13 pins in `tests/test_respawn_retired_sweep.py`. **None of them is vacuous** — each
asserts an observable of a real `cmd_respawn` drive rather than restating the implementation, and the
cap pin is genuinely discriminating (its sid naming makes lexicographic and insertion order disagree,
and under `sorted()` the old sid itself is the element dropped). The two "control" pins that were
green before and after are exactly the gate2 B2 shape and the lane found and covered them itself.

**A real hole in the pin set, MEASURED:** nothing pins that the sweep and the tombstone happen
*before* the registry write, and nothing pins `kill`'s exception safety (F3). The first is cosmetic;
the second is the one that matters.

### 7.3 The three self-declared defects

**The CRLF flattening — NOT-GATING, and it could not have reached a commit.** MEASURED.
`core.autocrlf=true` in the system gitconfig, and `.gitattributes` sets `eol=lf` only for `*.sh` and
`bin/fleet` — `git check-attr` confirms `text: unspecified` for all four changed source files. So
git normalises to LF on `add`, and the blobs are LF at **both** `64b43c2` and `12c238c`:

| file | base blob | head blob |
|---|---|---|
| `bin/fleet.py` | 0 CRLF / 21666 LF | 0 CRLF / 21797 LF |
| `tests/test_liveness_readers.py` | 0 / 1157 | 0 / 1173 |
| `tools/mutate_liveness.py` | 0 / 220 | 0 / 362 |
| `tests/test_respawn_retired_sweep.py` | absent | 0 / 357 |

The working tree is pure CRLF, 0 bare LF, on all four. **No line-ending change reached any commit on
this branch, and under this configuration none could.** The instrument that *would* have seen it is
the working-tree digest, which is exactly what the lane says caught it. The repair was real and the
lesson (every scripted edit on bytes) is right; the blast radius was smaller than the section implies.

**`files=262` vs `263`.** Arithmetic slip, no load-bearing number touched. The digest's job is the
before/after comparison within one run, and both runs' triples matched.

**The fixpoint table miscount.** Corrected in place, visibly, which is the right handling. And the
fixpoint itself is **independently confirmed**: `tests/test_self_citations.py` is in the suite, and
my own floor run is green on both interpreters, so the self-citations do resolve at `12c238c` on a
tree that is not the author's.

---

## 8. F6 and F8 — two smaller ones

**F6 — MINOR, MEASURED.** `_cmd_kill_native`'s **primary** stop is not wrapped at either tree. Driven:
a raising primary stop aborts `kill` with the record still `status:"working"`, no `killed` outcome and
no event — identically at BASE and HEAD. The consequence §7.2 gives as its reason to fix ("on `kill`,
aborting before the tombstone and the dead-marking") therefore remains fully reachable at HEAD, by the
route the sweep no longer takes. Pre-existing, not a regression, and arguably correct by design since
that stop's outcome *is* load-bearing — but `_cmd_kill_native`'s docstring promises *"unconditionally
mark the worker dead — kill is terminal regardless of whether the stop could be verified"*, and on
this path it is not.

**F8 — MINOR, not this lane's, MEASURED.** The progress line prints `retired[:8]` while the stop uses
`_native_job_ref`, which splits at the first `-`. With 50 sids named `retired00-x`…`retired49-x`, the
sweep correctly stops `retired30`…`retired49` but prints `stopping retired session retired3... ok`
**ten times**. Identical at BASE. "One progress line per sid" is true; "one *distinguishable* line per
sid" is not. Note that the new respawn pin sidesteps it by choosing 8-character names.

---

## 9. THE FLOOR — reproduced independently, every term

MEASURED, on `w52/glive3` @ `12c238c` in `C:/proga/fleet-w52-glive3`, working tree clean
(`git status --porcelain` empty) before the run.

| interpreter | collected | result | wall |
|---|---|---|---|
| `py -3.13 -m pytest -q` | **4649** | **`4634 passed, 14 skipped, 1 xfailed`** | 639.61s |
| `py -3.10 -m pytest -q` | **4649** | **`4634 passed, 14 skipped, 1 xfailed`** | 514.70s |

Working-tree digest (the `BRIEF-TEMPLATE.md` script, not `git write-tree`) printed before the 3.13
run, between the interpreters, and after the 3.10 run — three times, identical, `files=` included:

```
efe51b3af02e288099e4d00b04fd35faa91ad49ff0f99c7c0e83695c72b47cdb  files=263  root=C:\proga\fleet-w52-glive3
```

**§7.4's claim reproduces exactly, on a different tree, on both interpreters.** `files=263` matches.
No flake, no red, nothing to wave through.

**I did not re-measure the baseline.** `64b43c2`'s 4636 / `4621 passed, 14 skipped, 1 xfailed` is
taken from the brief, which records it as measured independently twice this wave; re-running it would
have cost ~20 minutes to re-derive a twice-measured number. The arithmetic is consistent with my
readings in both terms: 4636 + 13 = 4649 collected, 4621 + 13 = 4634 passed, skips and xfails unmoved
at 14/1. That +13 is the 13 pins in `tests/test_respawn_retired_sweep.py`, and `docs/lanes/` is
exempt from `CHECK_COUNT_DOCS` via `_HISTORICAL_PREFIXES` (verified — which is also why **this**
report cannot move the floor either).

That last claim is MEASURED rather than asserted, after this report was committed at `4ab8650`:
`py -3.13 -m pytest -q --collect-only` → **4649 tests collected**, unchanged; and the four
document-facing files — `test_doc_claims.py`, `test_lane_report_durability.py`, `test_receipts.py`,
`test_self_citations.py` — run **171 passed** with it in the tree. The working-tree digest moves to
`files=264`, which is the one file I added and the only thing about this branch I changed.

The digest **hash** differs from §7.4's `e9b44616…` at the same `files=263`. That is the documented
behaviour of a checkout-relative instrument (`BRIEF-TEMPLATE.md`, measured by gate `w50-gd2`), not a
discrepancy: it answers *"did this run change anything here?"* and never *"is this tree that tree?"*
For the second question the answer is `git rev-parse HEAD` → `12c238c` and a clean status, both above.

---

## 10. WHERE THIS BRIEF WAS WRONG

The brief asked to be refuted where it deserved it, having been wrong twice already.

1. **"`docs/SPEC.md:84` … stale at `64b43c2` too, so not this lane's. That is the THIRD independent
   instance this wave of citations that were already wrong before anyone touched the file. Confirm
   it."** — **Refused, MEASURED.** It is not stale. `docs/SPEC.md` pins itself to `c63d7dd` in its own
   §0, the citation is exactly right there, and 57 of 64 anchors in the document resolve at that pin
   against 0 at HEAD. There is no third instance here. The instruction to "confirm it" would have had
   me ratify a false finding; the instruction to "grade the lane's decision to report rather than fix"
   assumed a defect that does not exist. §2 above.

2. **"If you must cut, cut the citation section."** — **I refuse this one too**, and it is the more
   useful refusal: the citation section is where the largest report-level defect on this branch lives.
   Cutting it would have left §3.6 and §10.2 standing, and §10.2 is the one recommendation on this
   branch that would actively damage the repo. The brief's triage ranked it last precisely because it
   assumed the lane's finding was correct.

3. **"Likeliest [wrong]: that extraction is safe for `kill`."** — **Not wrong.** Driven at nine
   scenarios, seven byte-identical and two deliberately improved. The extraction is the safest part of
   this branch (§5.2).

4. **"…that the run-1 defect reproduces without the test stub."** — **Half right, and it is the
   better half.** It reproduces beyond the *`None`-returning* stub (any non-`OSError` exception does
   it), but I could **not** construct it with the real `subprocess.run`/`shutil.which` pair, because
   `_stop_native_session_status` catches more than §7.2 credits it with. The brief was right to
   demand this and right that it changes the grade — it demotes §7.2's generalisation to BELIEVED
   (§6.1) while F1 supplies the reachable route the lane's guard misses (§1).

5. **"…that 16/16 killed means the mutant population was adequate rather than that it was the
   author's."** — **Right, and this is the brief's best call.** Two mutants the author did not build
   are in §6.3, and the population's boundary is structural, not merely psychological: the driver
   grades against two test files and `tests/test_native.py` is not one of them (§7.1).

6. **"…that leaving `_cmd_respawn_supervisor`'s guardless copy unfixed is acceptable."** — **Mostly
   acceptable**, but the brief and the lane both undercount: it is three guards now, not two (§4).

7. **"A best-effort sweep may not be able to abort the verb" (the lane's framing, endorsed by the
   brief).** — Correct as a rule and **not achieved**: F1 shows the sweep still aborts both verbs, and
   F6 shows the primary stop always could.

One thing the brief got exactly right and I want on the record: **"an instrument's answer is about the
tree it is STANDING IN."** F2 is that rule applied to a document instead of a tree, and it is the only
reason I did not inherit §3.6 whole.

---

## 11. WHAT I DID NOT DO

- I fixed nothing. Every correction above is stated, none applied. No file outside
  `docs/lanes/w52-glive3.md` is modified on this branch.
- I did not drive `_cmd_respawn_supervisor` end to end; §4's findings there are from AST and reading,
  plus the G2 mutant. Its full lifecycle setup (claim, INCARNATION, choreography) was more scaffolding
  than the finding warranted.
- I did not re-drive W52-2 in either direction, and I did not re-open §6.7.
- I did not run the mutation ledger itself. The lane's 16/16 is not independently re-graded here; what
  I checked is the population's boundary (§7.1) and the pins' non-vacuity by reading (§7.2), plus two
  mutants of my own.
- F7's race is derived from constants, not driven.
