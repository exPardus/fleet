# `w49-fs` — the fork-steer defect: reproduced, root-caused, pinned, patch attached

| | |
|---|---|
| Branch | `w49/fs` |
| Base | `cef230f` (`docs(w48): journal the wave-48 clean release`) |
| Lane | Research. **`bin/fleet.py` NOT touched** — sha256 verified unchanged, §7c |
| Adds | `tests/test_fork_steer_delivery.py` (new), this report, the journal |
| Vendor | `claude --version` → `2.1.226 (Claude Code)` |
| Interpreters | `py -3.13` → 3.13.12; `py -3.10` → 3.10.1 |
| Stamped? | **NO.** `state/pin-pass.json` byte-identical before and after — §7b |
| Live spawns | **61 workers, 154 sessions, all stopped + `rm`'d, 0 leftovers** — §7d/§7e |

Every line is **MEASURED** (I ran it in this lane) or **BELIEVED** (reasoning I did not execute).
The gate should read §0, §1e, §2b and §6c first.

---

## 0. READ THIS FIRST — THIS BRANCH LANDS A RED SUITE, DELIBERATELY

`py -3.13 -m pytest -q` on this branch: **2 failed, 4141 passed, 14 skipped, 1 xfailed.**
Identical on `py -3.10`. Both failures are the new pin, and they are red because **the defect they
pin is unfixed in `bin/fleet.py`, which another lane holds this wave.** The brief ordered exactly
this: write the pin, watch it red, deliver the fix as a patch.

> *[Added 2026-08-09, turn 2 — the line above is left as measured on 2026-08-08 rather than edited.]*
> Turn 2 adds one unit-tier test, so the current count is **2 failed, 4142 passed, 14 skipped,
> 1 xfailed** on both interpreters. **The two failures are the same two**, and everything else in
> this section still holds. Receipts and the prediction that named the +1 in advance: §11e.

**Applying §6's patch turns both green** — proven, §6c. If the supervisor lands this branch and
the patch in the same merge there is no red window at all. If they land separately, main is red in
between, and that is a scheduling decision, not a defect. If a green main is required in the
interim, the minimal reversible lever is `@pytest.mark.xfail(strict=True, reason="w49 fork-steer
defect, fix in docs/lanes/w49-fs.md §6")` on the two named tests — `strict=True` so it converts to
a failure the moment the fix lands and nobody can forget to remove it. **I did not apply that**:
this repo's doctrine is that a red catching a real defect is not weakened, and a lane that
pre-silences its own finding is doing the reader a disservice.

**Headline.** The w48 claim is CONFIRMED in substance and WRONG in three particulars. The
fork-steer defect is real and I reproduced it live with the two alternative explanations
eliminated by construction. But it is **not** interpreter-dependent (the dispatch is byte-identical
on 3.10 and 3.13 — proven without spawning anything), it is **not** a race between two program
events (there is exactly one actor and no window), and it is **not** 1-in-5 (**1 in 92 driven
samples**). The property pin is RED on **both** interpreters, **100% of runs**, because the defect
is unconditional in the code and only its *consequence* is stochastic. **That gap — 100% in the
code, ~1% in the outcome — is the whole reason this evaded five waves of green pin runs.**

---

## 1. WHERE THIS BRIEF WAS WRONG

The brief named four likely errors and invited a fifth. Three were right to flag, one was right in
the brief's favour, and one — the fifth, which the brief framed as unlikely — is true in a
direction the brief did not consider.

### 1a. "the wave-35 brief-store conflation is the mechanism" — **NO. Different defect.** — MEASURED

The brief flagged this as the hypothesis most likely to stop me looking, and it was right to. The
w35 fix is working exactly as designed and is not implicated.

* `write_brief` has **4 callers**, and **not one is a steer path** — AST census over
  `bin/fleet.py` at `cef230f`: `read_brief:1855`, `cmd_spawn:6547`, `_cmd_respawn_native:8306`,
  `_dispatch_supervisor_body:17262`. `_cmd_send_native` does not appear. A fork-steer does not
  write the brief store, so it cannot destroy it.
* The steer body **reaches disk every time**: `steer_on_disk: true` in **92 of 92** live samples —
  and in the one failing sample the *old* task's token was verifiably **gone** from the file
  (`a_tok_still_on_disk: false`) while the worker answered it anyway.

So this is the **read side**, and it is a different conflation. w35 split *brief* from *payload* —
two jobs in one file. What is still conflated is one level down and needs saying plainly:

> **the payload file has a per-WORKER identity, not a per-DISPATCH identity.**

One name, N different contents, handed to a session that caches by name. Same class ("one
identifier, two jobs"), different granularity. The w35 fix could not have caught it because it was
not about briefs.

### 1b. "the failure rate is 1 in 5 on your hardware" — **NO: 1 in 92** — MEASURED

Full accounting in §3c. Exact Clopper–Pearson intervals, computed not eyeballed:

| | rate | 95% CI |
|---|---|---|
| w48, n=5 | 20% | **0.51% – 71.64%** |
| this lane, n=92 | **1.09%** | **0.03% – 5.91%** |

They overlap, so my measurement does not *refute* theirs — but an interval seventy points wide is
not a rate, and the operationally useful sentence is: **rare, real, and nowhere near one in five.**
Anyone quoting "~20%" is quoting a sample of five.

### 1c. "3.13-vs-3.10 is a code-path difference" — **NO, and it is not a race either** — MEASURED

Settled in §2b without spawning a single session: the dispatch `py -3.13` and `py -3.10` emit for
a fork-steer is **byte-identical**. There is no channel by which the interpreter could reach the
outcome. Corroborated the expensive way too — the new pin is RED on both.

It is also **not a race** in the sense the brief meant. §2c walks the ordering: one writer, no
concurrency, every write complete before the only reader is launched. The brief asked me to "name
the two things racing" if it is a race; **the finding is that there is only one thing, and the
question presupposes one too many.** The nondeterminism is in the worker's reading of an ambiguous
turn, not in fleet's ordering — which is why no amount of locking or sequencing would fix it and
why changing the turn does.

### 1d. "the fix is small" — **RIGHT** — MEASURED

Exactly **2 of 5** `dispatch_bg` call sites pass `resume_sid` (§2e), and only a resumed session can
replay. Net **+34 lines**, one signature, one constant, two call sites. §6.

But "small" hides a real cost the brief half-anticipated: the patch moves **13 of the 21** distinct
self-cited line numbers in `bin/fleet.py`, and six citation tests go red until they are re-pinned.
§6d has the old→new table so the follow-up does not have to re-derive it.

### 1e. "it may be the TEST's defect" — **NO for the RED. YES for a GREEN nobody should trust.** — MEASURED

The brief asked me to rule this in or out early and called it a welcome finding. Ruled out for the
failure: the pin asserts a property `fleet send` genuinely owes, and shipped code genuinely fails
to guarantee it.

**But the inverse is true, and nobody has said it.** `dispatch_bg` renders the dispatched session's
roster name as `cat|name|hint` with `hint = message[:NATIVE_NAME_HINT_MAX]`, and
`NATIVE_NAME_HINT_MAX = 40`. The pin steers with `Reply with exactly: STEER-OK` — **28 characters,
entirely inside that window** — so **the pin's success token is handed to the forked session as its
own title**, on a channel with nothing to do with whether the steer was delivered.

`docs/lanes/w48-pin.md` §4b already contains the evidence and reads past it: *"`STEER-OK` appears
6× in the transcript and only in `custom-title` / `agent-name` metadata."* That is offered there as
proof the steer was absent from the user message. It is equally proof that **a fork which answered
`STEER-OK` need not have read anything.**

Consequence: `test_3_pin_fork_steer` **can pass while the path it tests is broken**, so every GREEN
it has produced across five waves is weaker evidence than it looks. My probe was designed around
this — the nonced arm's answer token sits past character 40, so a fork that answers it
demonstrably read the file (§3a). Remedy is one line in `tests/integration/test_native_pin.py`
(push the token past the window, or make it per-run unique); not applied, that file is not mine
this wave. **This is the finding the brief did not anticipate, and it is the one I would route
first**, because it governs whether the *next* green means anything.

### 1f. What the brief got right and I want to reinforce

"`FLEET_HOME` is not a fence" is correct, and the reason it did not bite me is again the absent
homes list, not the mechanism. §7a, with the before/after snapshot the brief asked for — including
the one artifact that **did** change and what it turned out to be.

---

## 2. ROOT CAUSE — derived, not inferred

### 2a. The mechanism, in code — MEASURED

`bin/fleet.py:13123` and `:13133` (`dispatch_bg`):

```python
task_path = task_file_path(name)
task_path.write_text(prompt_body, encoding="utf-8")
...
tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
```

`tiny_prompt` is a **pure function of the worker NAME** (`task_file_path(name)` →
`tasks_dir()/f"{name}.md"`). Nothing about *this* dispatch — not the sid, not the turn count, not
the content, not the fact that it is a resume — reaches it.

`_cmd_send_native` (`bin/fleet.py:7607-7616`) composes with `task=""` (F6: the message rides the
mailbox), so `compose_prompt` yields *preamble + `<MANAGER MESSAGE>` block*, which `dispatch_bg`
writes over the payload file and then points at with that same, unchanged string.

**Answer to the brief's first question — what makes the dispatched pointer byte-identical: the
pointer is derived from the worker's name and from nothing else.**

### 2b. Proved without a live session, on both interpreters — MEASURED

`capture_argv.py` drives the **real** `cmd_spawn` → `cmd_send` fork-steer with only `claude` faked
— the same fake-`run`/fake-roster shape `tests/test_brief_preservation.py` uses, chosen for its
stated reason: `dispatch_bg`'s own `write_text` is the act under test, so a double that
re-implemented it would be asserting against the harness's copy of the defect. Output, py 3.13.12:

```
"spawn_prompt": "Read <HOME>/state/tasks/probe-w1.md and follow it exactly.",
"steer_prompt": "Read <HOME>/state/tasks/probe-w1.md and follow it exactly.",
"prompt_identical":       true,
"taskfile_changed":       true,
"steer_text_in_prompt":   false,
"steer_text_in_taskfile": true
```

The same capture under `py -3.10` (3.10.1), normalised only for the tempdir name, is
**byte-identical** across `spawn_argv`, `steer_argv`, both prompts and the task-file text:

```
py 3.13.12 vs py 3.10.1
NORMALIZED DISPATCH IDENTICAL ACROSS INTERPRETERS: True
```

**This is the discriminator the brief asked for, and it costs nothing to run.** Two interpreters
emitting identical bytes cannot produce different worker behaviour through any mechanism inside
fleet. The 3.13-RED / 3.10-GREEN split in `docs/lanes/w48-pin.md` §3 is n=1 against n=1 — a coin
landing differently twice, reported as a version dependency. Stronger still: **the new pin is RED
on both interpreters, deterministically** (§4). If the interpreter mattered, 3.10 would be green
there.

### 2c. Not a race — MEASURED (ordering) + MEASURED (92 probes)

In `_cmd_send_native` → `dispatch_bg`, every write strictly precedes the only read:

1. `append_mailbox(old_sid, message)` — the steer hits the mailbox file.
2. `compose_prompt(...)` — **claims and drains** that mailbox into `prompt`, synchronously.
3. `task_path.write_text(prompt_body)` — the payload file now contains the steer.
4. `run(argv, ...)` — `claude --bg --resume <old_sid>` launches. Only now can anything read.

One writer, no concurrency, no window. Empirically the same: `steer_on_disk` was **true in 92/92**
samples **including the failing one**. Wave 48 measured this at n=3 and drew the same conclusion; I
reproduce it at n=92 and extend it to the failing case, which its tier could not observe because
the tier deletes the evidence in teardown.

So the correct sentence is: **the nondeterminism is the worker's, and fleet's design is what makes
the worker's choice matter.** A turn identical to one already answered, sent to a session that
still holds the old answer *and* the old file contents, does not *ask* for a re-read. Replaying is
not the model malfunctioning — it is the cheapest correct reading of the question actually asked.

The clearest statement of this came from a worker, unprompted. In an early calibration sample the
fork enumerated its own situation before answering:

```
Original user instruction (twice): Read file and follow exactly
```

**The model can see the duplication. Fleet is the thing that created it.**

### 2d. What would make the receiving session re-read — MEASURED, by planting (§5)

The brief's second question. Two things do, and both survive planting:

* **Carry the steer in the turn itself** — re-reading leaves the critical path entirely, so
  delivery stops depending on a choice.
* **Point the turn at a payload identity the session has never dereferenced** — no cached content
  exists for that identifier, so no replay can satisfy the turn.

Three things do **not**, and I planted each rather than reasoning about it: a per-dispatch nonce, a
content digest in the pointer, and an explicit *"the file has been REWRITTEN — read it again"*
notice. All three make the turn *different*; none makes the steer *determined by* the turn. **They
move the probability; they do not remove the dependency.** The defect lives exactly in that gap —
which is what the brief predicted when it said the defect lives between what makes the pointer
identical and what would force a re-read.

### 2e. Scope: exactly two call sites, and one of them is unreported — MEASURED

AST census of `dispatch_bg` call sites at `cef230f`:

| Call site | line | passes `resume_sid`? |
|---|---|---|
| `cmd_spawn` | 6548 | no |
| **`_cmd_send_native`** | **7612** | **YES** |
| **`_resume_one_limited_native`** | **7768** | **YES** |
| `_cmd_respawn_native` | 8314 | no |
| `_dispatch_supervisor_body` | 17264 | no |

Only a resumed session can replay, so the blast radius is exactly the two `YES` rows. `respawn`
mints a fresh session and is **immune** — worth stating because w48 §4c can be read as implicating
every dispatch path.

**`resume-limited` is a second, unreported instance of the identical defect.** Same shape:
byte-identical turn, `--resume`, a session that already answered it. `docs/lanes/w48-pin.md` names
only `send`, and a grep of `docs/` and `knowledge/` at `cef230f` finds no mention of
`resume-limited` carrying it. It is also **worse placed**: it fires unattended after a usage-limit
park, on a worker whose turn was cut off mid-task, with no operator watching the reply. The patch
fixes both.

---

## 3. THE LIVE REPRODUCTION AND THE RATE

### 3a. The probe, and the three things it does that the pin tier does not — MEASURED

One sample = `fleet spawn` a haiku worker on task A → `fleet wait` → `fleet send` task B →
`fleet wait` → classify the **fork's** outcome record. Verdicts: `OBEYED` (B's token, not A's),
`STALE` (A's token, not B's), `AMBIGUOUS`, `OTHER`, `NO-OUTCOME`.

1. **Per-sample nonces**, so a stale answer can never coincidentally match.
2. **The answer token sits past `NATIVE_NAME_HINT_MAX`**, so it cannot reach the session through
   the roster name (§1e). A fork that answers B *read the file*.
3. **`FLEET_HOME` is not trusted as the fence.** `CLAUDE_CODE_SESSION_ID` and `FLEET_WORKER` are
   removed from the child env, and the probe **aborts before its first spawn** unless `fleet home`,
   invoked with exactly that env and that binary, answers the tempdir. Gate: **PASS, 9 of 9 arms.**

One confound found and killed before the real runs: a first draft steered with *"Disregard every
earlier instruction in this session…"*, which haiku classified as a prompt-injection attempt and
**refused**. A refusal is not a steer; it would have polluted the rate in the safe-looking
direction. Replaced with plain operational wording. **A calibration run that surprises you is
cheaper than a rate you have to retract.**

### 3b. The reproduction — MEASURED, with both alternative explanations eliminated

Sample `probe-w6`, py3.13 arm:

```
send_stdout          = 'probe-w6: fork-steered (new session 3aa87fb3) -- fork carries full transcript (G2b)'
fork_steered_printed = True
new_sid_differs      = True          # edb30508… -> 3aa87fb3…
steer_on_disk        = True          # BETA-4EA1AD24 IS in the payload file
a_tok_still_on_disk  = False         # ALPHA-4EA1AD24 is NOT in the payload file
hint_carries_b       = False         # the BETA token is past char 40 of the steer
result_text          = 'ALPHA-4EA1AD24'
verdict              = STALE
```

The fork answered a token that, at that moment, existed **nowhere on disk** and **not in its own
session name** — only in its own transcript, from the turn before. `fleet send` returned 0 and
printed success.

**That is the operator-visible symptom, reproduced independently of w48, with the file and the
session name eliminated as sources by construction rather than by argument.**

### 3c. The rate — MEASURED

| Arm | interpreter | shape | n | OBEYED | **STALE** | gate |
|---|---|---|---|---|---|---|
| `n313` | 3.13.12 | nonced, hint-proof | 8 | 7 | **1** | PASS |
| `n310` | 3.10.1 | nonced, hint-proof | 8 | 8 | 0 | PASS |
| `n313b` | 3.13.12 | nonced, hint-proof | 12 | 12 | 0 | PASS |
| `n310b` | 3.10.1 | nonced, hint-proof | 12 | 12 | 0 | PASS |
| `f313` | 3.13.12 | **the pin's own wording** | 6 | 6 | 0 | PASS |
| `f310` | 3.10.1 | **the pin's own wording** | 6 | 6 | 0 | PASS |
| `ch313` | 3.13.12 | chained, depth 1–5 | 20 | 20 | 0 | PASS |
| `ch310` | 3.10.1 | chained, depth 1–5 | 20 | 20 | 0 | PASS |
| **total** | | | **92** | **91** | **1** | 9/9 |

**1 failure in 92 = 1.09%, 95% CI 0.03%–5.91%** (Clopper–Pearson, computed). Limits stated because
a rate is a measurement: one event cannot pin a percentage, and I would not defend "1.09%" to two
decimal places on n=92 either. What n=92 *does* establish, which n=5 could not, is the order of
magnitude — **~1%, not ~20%**.

Two honesty notes an adversarial reader should hold me to:

* **The 12 `f*` samples are not evidence the path works.** They use the pin's own steer text, whose
  success token fits inside the roster-name window (§1e), so their GREENs cannot distinguish "read
  the file" from "read my own title." I report them because they are the faithful reproduction of
  the pin's conditions, and I exclude them from any claim about the path. The **80** nonced samples
  carry the load.
* **The one failure landed in a 3.13 arm.** With exactly one event, which arm it lands in is
  chance, and §2b is why that is not evidence for the interpreter hypothesis. If the byte-identity
  result did not exist, this single sample would be the entire basis for a version-dependence
  claim — which is precisely how w48's arose.

### 3d. The mechanism's own prediction, tested and NOT confirmed — MEASURED

If a fork replays because it has *already answered this exact turn*, then a session that has
answered it N times should replay more often. `probe_chain.py` spawns one worker and steers it five
times in a row, fresh nonce each time, classifying every steer by depth.

| depth | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| `ch313` (py3.13) | 4/4 OBEYED | 4/4 | 4/4 | 4/4 | 4/4 |
| `ch310` (py3.10) | 4/4 OBEYED | 4/4 | 4/4 | 4/4 | 4/4 |

**No depth effect at n=40.** I report a failed prediction because a failed prediction is data, and
because it forecloses a plausible-sounding workaround: **"the risk is only in long steer chains" is
false**, and nobody should be told to respawn instead of steering on that basis. It also means the
1-in-92 is not concentrated anywhere I could find — which is the worst distribution for an operator,
because there is no rule of thumb that avoids it.

---

## 4. THE PIN — RED first, verbatim

`tests/test_fork_steer_delivery.py`, a **new** file, so no merge conflict with the lane holding
`bin/fleet.py`. It drives the real `cmd_spawn` and `cmd_send`; only `claude` is faked.

Nothing in it names `tiny_prompt`, the task file, or the mailbox. Both assertions are stated over
one observable: **what the dispatched session is handed, and what it already had.**

| test | role |
|---|---|
| `test_the_steer_actually_reached_the_dispatch_layer` | guard — so the two below cannot red for the wrong reason (delivery losing the message is a *different* defect) |
| `test_a_fork_steer_is_not_a_turn_the_session_already_answered` | **necessary** condition; deliberately weak (a bare nonce passes it), kept because when it reds the one-line prompt diff *is* the diagnosis |
| `test_the_steer_is_determined_by_the_dispatched_turn_alone` | **the property.** Computes the bytes the resumed session receives *that it did not already have* — a pointer already dereferenced contributes nothing, one never dereferenced contributes its content — and requires the steer to be among them |
| `test_the_steer_text_is_copied_into_the_dispatched_session_name` | characterisation, green, carrying §1e's warning to whoever writes the next live delivery test |

**RED, verbatim, `py -3.13`:**

```
E       AssertionError: the fork-steer handed the resumed session ZERO bytes it did not
E       already have: the steer sits behind a pointer this session already dereferenced, so
E       obeying it depends entirely on the worker CHOOSING to re-read a file it believes it
E       has read.
E           dispatched turn : 'Read C:/…/fleet-home/state/tasks/steer-w1.md and follow it exactly.'
E           already read    : ['C:\…\fleet-home\state\tasks\steer-w1.md']
E           named this time : ['C:\…\fleet-home\state\tasks\steer-w1.md']
E       assert 'STEER-SENTINEL-9c3b: the steered instruction, and the whole point.' in
E              'Read C:/…/fleet-home/state/tasks/steer-w1.md and follow it exactly.'
tests\test_fork_steer_delivery.py:290: AssertionError
```

```
# py -3.13 -m pytest tests/test_fork_steer_delivery.py -q -rf     (rc=1)
FAILED tests/test_fork_steer_delivery.py::test_a_fork_steer_is_not_a_turn_the_session_already_answered
FAILED tests/test_fork_steer_delivery.py::test_the_steer_is_determined_by_the_dispatched_turn_alone
2 failed, 2 passed in 1.39s

# py -3.10 -m pytest tests/test_fork_steer_delivery.py -q -rf     (rc=1)
FAILED tests/test_fork_steer_delivery.py::test_a_fork_steer_is_not_a_turn_the_session_already_answered
FAILED tests/test_fork_steer_delivery.py::test_the_steer_is_determined_by_the_dispatched_turn_alone
2 failed, 2 passed in 1.31s
```

**RED on both interpreters, every run.** That is the sharpest form of the finding: the *defect* is
unconditional and interpreter-independent; only its *consequence* is stochastic. A test that
samples the consequence sees ~1%; a test that asserts the property sees 100%. **The reason this
survived five waves is that the only test looking at it was sampling.**

---

## 5. THE PIN IS NOT WRITTEN AGAINST MY OWN FIX — six shapes planted

A pin is only non-vacuous for the shapes someone actually planted against it
(`knowledge/lessons.md`, wave 35, four mutants and four full-suite greens). Six candidate patches,
each planted into its **own** throwaway tree by a driver that **asserts its anchor matched exactly
once, re-reads the file, and byte-compiles it before pytest is allowed to run** — wave 47's lesson
that a planter which refuses and runs the suite anyway costs a whole verdict.

| Planted shape | result | still RED |
|---|---|---|
| **FIX-A** inline the steer in the dispatched turn | **4 passed** | — |
| **FIX-B** per-dispatch payload path the session has never read | **4 passed** | — |
| SHAM-1 per-dispatch nonce appended to the turn | 1 failed, 3 passed | `…determined_by_the_dispatched_turn_alone` |
| SHAM-2 *"the file changed — read it again"* notice | 1 failed, 3 passed | `…determined_by_the_dispatched_turn_alone` |
| SHAM-3 content digest in the pointer | 1 failed, 3 passed | `…determined_by_the_dispatched_turn_alone` |
| SHAM-4 rewrite the payload harder, no dispatch change | 2 failed, 2 passed | both |

**Two structurally unrelated real fixes both go green** — one changes the turn's content, the other
changes the payload's identity and leaves the turn's shape alone. The pin is about the property,
not about my patch. **Three shams that change the turn but leave delivery contingent on a re-read
stay red on the property pin while greening the weak one** — which is exactly the discrimination
the weak pin is not there to provide alone.

SHAM-2 deserves its own paragraph because it is the patch a reviewer is most likely to propose and
it is not stupid: telling the worker the file changed would probably raise the live success rate a
lot. **The pin refuses it deliberately, and that refusal is a design position, stated here so it
can be argued with rather than discovered:** a steer whose arrival depends on the worker choosing
to comply cannot be reported as delivered, because nothing downstream can tell the difference —
which is the original operator complaint, unchanged. If the supervisor disagrees, the place to
overrule me is `test_the_steer_is_determined_by_the_dispatched_turn_alone`, in one edit, with the
reason written down.

---

## 6. THE FIX — a patch, not an edit

`bin/fleet.py` belongs to another lane this wave, so this is delivered as a diff. It was applied in
a **separate scratch tree** (never the worktree), proven, and §7c shows the worktree file is
byte-identical to `cef230f`.

### 6a. Shape and why this one

`dispatch_bg` gains an optional `inline_body`; when present the dispatched turn carries the steer
verbatim ahead of the pointer. The pointer stays — it still carries the preamble, any residual
queued mail, and an over-length tail. Both `resume_sid` call sites pass it.

**Why FIX-A over FIX-B, since the pin accepts both** — MEASURED: `task_file_path` has **4** callers
(`_recovered_brief:1788`, `_remove_worker_files:9532`, `_archive_file_pairs:10026`,
`dispatch_bg:13123`). FIX-B changes the payload's *identity*, so cleanup and archive both have to
learn to glob, and every unswept dispatch leaves a file behind. FIX-A touches one function and two
call sites and changes no path. **BELIEVED**, and worth someone's second opinion: I judged the
identity change the larger risk in a file this size, but FIX-B is the structurally cleaner answer
and a wave with room should price it properly rather than inherit my judgement.

### 6b. Stated residual, not hidden

A steer longer than `NATIVE_INLINE_STEER_MAX` (4000) is truncated **in the turn** with an explicit
marker naming the file. The cap exists because Win32 caps a command line at 32767 characters and
`fleet send @file` accepts arbitrarily large input — without a cap, a large steer would make
`dispatch_bg` fail outright, converting a rare silent miss into a common loud one.

**For those steers the guarantee degrades to SHAM-2** — the turn is distinguishable and says the
file was rewritten — **which I have just argued is insufficient.** I am not going to pretend
otherwise. A follow-up that wants the guarantee unconditionally should compose FIX-A with FIX-B for
the over-length case only: inline what fits, and when it does not, hand the turn a payload identity
the session has never seen. I did not build that; it is a second patch and this lane owes one.

### 6c. Evidence

```
# scratch tree, fix planted; the planter asserted all 5 anchors matched 1x,
# re-read the file, and byte-compiled it BEFORE pytest was allowed to run
PLANT OK  5 edits
  before sha256 89812b14ea55b1814f2d30cf3c6a0f35ea4998f3e72dee197bcafa3cfab98635
  after  sha256 74b931bdcd2ed27e7eedb17c3ca81affde7931ea507e7576c54db05fb091fa43

# py -3.13 -m pytest tests/test_fork_steer_delivery.py -q -rf   (in the scratch tree)
....                                                                     [100%]
4 passed in 0.73s
```

**Full suite, patched vs unpatched, in the SAME scratch tree** — the comparison is baseline-vs-
patched rather than against the worktree, so the 38 failures caused by the scratch having no `.git`
(receipts, citations-over-history, LF-pinning) cancel out instead of being argued about:

| | baseline (unpatched) | patched | delta |
|---|---|---|---|
| passed | 4103 | 4099 | −4 |
| failed | 40 | 44 | +4 |
| skipped | 14 | 14 | — |
| xfailed | 1 | 1 | — |

Set difference, exactly:

* **−2**: both of my new pins go GREEN. That is the fix working.
* **+6**: `test_self_citations.py` (4) and `test_retired_sid_citations.py` (2) go red. **This is
  citation rot, not a behavioural regression** — see 6d.

**Zero behavioural tests changed state in either direction.** Nothing in `test_native.py`,
`test_steering.py`, `test_send_provenance.py`, `test_index_compose.py` or `test_steer_seams.py`
moved, which is the result I was most worried about since the patch changes the dispatched argv.

### 6d. The citation cost, priced so the follow-up does not re-derive it — MEASURED

The patch inserts lines at four points, which shifts every line after them. **13 of the 21 distinct
self-cited line numbers in `bin/fleet.py` move.** This is a function of insertion *position*, not
size: trimming my comment block would not reduce the count by one.

| cited line (at `cef230f`) | becomes |
|---|---|
| 7804 | 7808 |
| 8446 | 8450 |
| 8470 | 8474 |
| 8472 | 8476 |
| 8704 | 8708 |
| 10723 | 10727 |
| 10730 | 10734 |
| 11838 | 11842 |
| 12376 | 12380 |
| 14742 | 14776 |
| 16069 | 16103 |
| 16348 | 16382 |
| 16505 | 16539 |

*"N tests went red" is not "N things were wrong"* (`knowledge/lessons.md`): **6 tests, 13
artifacts.** The re-pin belongs in the **same commit** as the patch — a commit that leaves the
citation suite red is one no later bisect can trust.

### 6e. The patch

```diff
--- a/bin/fleet.py
+++ b/bin/fleet.py
@@ -7611,9 +7611,10 @@
     try:
         result = dispatch_bg(
             name, cwd, prompt, mode, model=model, category=category,
             hint=message[:NATIVE_NAME_HINT_MAX], resume_sid=old_sid,
-            setting_sources=setting_sources, run=run, which=which, sleep=sleep,
+            setting_sources=setting_sources, inline_body=message,
+            run=run, which=which, sleep=sleep,
         )
         finalize_mailbox_claim(claim)
     except BaseException:
         restore_mailbox_claim(claim)
@@ -7767,9 +7768,12 @@
     try:
         result = dispatch_bg(
             name, cwd, body, mode, model=model, category=category,
             hint="resume past limit", resume_sid=old_sid,
-            setting_sources=setting_sources, run=run, which=which, sleep=sleep,
+            setting_sources=setting_sources,
+            inline_body=("The usage-limit reset horizon has passed. "
+                         "Continue the task from where you left off."),
+            run=run, which=which, sleep=sleep,
         )
         finalize_mailbox_claim(claim)
     except BaseException:
         restore_mailbox_claim(claim)
@@ -12901,8 +12905,14 @@
 # slow spawn.
 NATIVE_WEDGE_CLEANUP_TIMEOUT_SECONDS = 10
 DEFAULT_CATEGORY = "fleet"
 NATIVE_NAME_HINT_MAX = 40
+# w49: how much of a steer rides the dispatched turn ITSELF rather than
+# the payload file. A resumed session is handed a turn it has already
+# answered unless something new arrives IN the turn, and Win32 caps a
+# command line at 32767 chars -- so inline generously, but bounded, and
+# say so in the text when the tail is left in the file.
+NATIVE_INLINE_STEER_MAX = 4000
 
 # · = MIDDLE DOT (the daemon's literal separator glyph). Previously a
 # duplicate-codepoint char class `[··]` (same character twice) -- collapsed
 # to a single literal, behavior-identical.
@@ -13075,9 +13085,9 @@
 
 
 def dispatch_bg(name, cwd, prompt_body, mode, model=None, category=None,
                 hint="", resume_sid=None, settings_path=None,
-                setting_sources=None,
+                setting_sources=None, inline_body="",
                 run=subprocess.run, which=shutil.which, sleep=time.sleep,
                 roster_fetch=None, clock=time.monotonic):
     # Defense in depth (adversarial trap 6): every current caller
     # pre-validates `name`, but this is the choke point for every --bg
@@ -13130,8 +13140,32 @@
     # pinned by Q8-3; same bare `-n` the handoff successor dispatch uses).
     rendered = (name if _is_supervisor_shaped(name)
                 else render_native_name(category, name, hint))
     tiny_prompt = f"Read {task_path.as_posix()} and follow it exactly."
+    # w49 fork-steer defect: a `--resume` dispatch whose turn is a pure
+    # function of the worker NAME is BYTE-IDENTICAL to one the resumed
+    # session has already answered, and everything that changed sits
+    # behind a pointer it already dereferenced -- so replaying the
+    # previous answer is the cheapest correct reading of the turn, and
+    # `send` prints "fork-steered" over a worker that never saw the
+    # steer. Measured live at 2.1.226: 1 silent miss in 92 driven
+    # samples (docs/lanes/w49-fs.md). Carrying the message IN
+    # the turn is what makes delivery independent of the worker
+    # CHOOSING to re-read; the pointer stays for the preamble, any
+    # residual queued mail, and an over-length tail.
+    if inline_body and inline_body.strip():
+        _body = inline_body.strip()
+        if len(_body) > NATIVE_INLINE_STEER_MAX:
+            _body = (_body[:NATIVE_INLINE_STEER_MAX].rstrip()
+                     + "\n[truncated here -- the full text is in the file "
+                       "named below]")
+        tiny_prompt = (
+            f"<MANAGER MESSAGE>\n{_body}\n</MANAGER MESSAGE>\n\n"
+            f"That message is a NEW instruction and it supersedes "
+            f"anything earlier in this session. {tiny_prompt} That file "
+            f"has been REWRITTEN since you last read it -- read it again "
+            f"rather than reusing an earlier copy."
+        )
     argv = [exe, "--bg"]
     if resume_sid:
         argv += ["--resume", resume_sid]
     argv += ["-n", rendered, "--settings", settings.as_posix()]
```

**What the patch does NOT do, deliberately:** it does not make `send` verify the steer landed. w48
§4f raised that as a third item and it is a genuinely different feature — a post-dispatch
verification would need a definition of "landed" that survives a worker legitimately deciding the
steer is already satisfied. Out of scope here; named so it is not lost.

---

## 7. CONTAINMENT — why I was contained, not merely that I was

The brief was explicit that a clean audit is not proof, because wave 48's came back clean for the
wrong reason. So: the mechanism first, the evidence second, and the one artifact that **did** change
third.

### 7a. Why the fence held — MEASURED, and it is still the wrong reason

```
my sid                    : 4dc4cacf-2c84-4592-a9fb-27af3f3b0ca2
my sid in the LIVE registry: YES, under worker 'w49-fs'
FLEET_WORKER (inherited)  : sup|inc-20260808T173831Z-c6d4|boot     <- donated-env leak, not mine
~/.claude/fleet-homes.list: ABSENT
fleet home (no override)  : C:/proga/fleet-w49-fs                  <- my worktree, NOT the live home
```

Multi-fleet §5 step 2 (sid→home lookup) outranks step 3 (validated env), and **my sid is in the
live registry** — so the hazard's precondition is met on the identity side. It does not fire only
because `~/.claude/fleet-homes.list` does not exist, so `resolution_population()` falls back to the
legacy/install home alone and **`C:/proga/claude-fleet` is never a candidate to hit.** Confirmed
behaviourally rather than inferred: `fleet home` with no override answers my worktree.

**So the fence held for the same wrong reason it held in wave 48, one wave later, with nothing
changed.** One `fleet homes --add` still converts every `FLEET_HOME`-fenced lane on this machine
into one that mutates the operator's live fleet.

What I did instead of relying on it, per the brief: every child process had
`CLAUDE_CODE_SESSION_ID` **and** `FLEET_WORKER` **removed**, and each probe arm **refused to
spawn** until `fleet home` — same binary, same env, same invocation — answered its tempdir.
**Gate PASS on 9 of 9 arms; zero spawns occurred before a gate.** Stripping the sid also disarms
`_supervisor_gate`, which arms on the sid's mere presence and would otherwise have refused every
`spawn`/`send` I made.

### 7b. Before/after, `(mtime_ns, size)` and sha256 as the brief asked

| artifact | baseline sha256 | after | verdict |
|---|---|---|---|
| `~/.claude/fleet-homes.list` | ABSENT | ABSENT | **UNCHANGED** |
| `~/.claude/settings.json` | `578bde7b…` (mtime_ns 1786210442854189800, 1859 B) | `578bde7b…` | **UNCHANGED** |
| live `state/pin-pass.json` | `d3b4bd15…` (75 B) | `d3b4bd15…` | **UNCHANGED — NOT STAMPED** |
| live `state/worker-settings.json` | `642bdcbe…` (858 B) | `642bdcbe…` | **UNCHANGED** |
| live `state/fleet.json` | `ced1f0e5…` (161157 B) | `b5ad4357…` (161210 B) | **CHANGED — investigated below** |

**The live registry moved, and I did not do it.** Rather than assert that, I bounded the window and
enumerated it. The file's mtime moved `2026-08-09T02:07:19.955946Z` → `02:27:28.397330Z`. Every
event the live fleet recorded strictly inside that window:

```
2026-08-09T02:07:19Z turn_started    w49-fs      <- my own spawn, i.e. the baseline instant itself
2026-08-09T02:09:27Z status_changed  w48-gc      <- sibling lane finishing a turn
2026-08-09T02:24:40Z status_changed  w49-dcap    <- sibling lane
2026-08-09T02:27:18Z respawned       w49-dcap    <- the live supervisor respawning a sibling
2026-08-09T02:27:28Z turn_started    w49-dcap
```

**Zero events name anything I dispatched.** Worker count 145 before and after; no `probe-w*`,
`chain-w*` or `steer-w*` anywhere in the live registry, `state/tasks/`, `state/journals/`,
`state/outcomes/` or `state/briefs/`. The registry moved because the live fleet was running other
lanes — which it does whether or not I exist.

*(Method note, offered because the brief asked me to explain rather than assert: the reason I can
say this at all is that the baseline captured `mtime_ns`, which turned the question "did it change"
into the far more answerable "what happened between these two instants". A sha256 alone would have
left me arguing.)*

### 7c. `bin/fleet.py` was never edited — MEASURED

```
worktree bin/fleet.py sha256      : 14526760d9f1d707866517788cf60ac7ea204e617ec52845c30cab446c6a9181
git status --porcelain            : (empty)
git diff --name-only cef230f HEAD : docs/lanes/w49-fs.md
                                    tests/test_fork_steer_delivery.py
```

Two files, both new, neither of them `bin/fleet.py`. No ref but `w49/fs` was moved; nothing was
pushed or merged.

The fix was never applied in place. It went into a **separate full copy** of the tree under the job
scratch dir, and the planter refuses outright if its target path is not inside a scratch tree or is
inside `fleet-w49-fs` — a guard that fired for real once, when I pointed a diff-generation run at a
temp dir whose name did not contain `scratch`.

### 7d. Every `fleet` command, and which home it touched

| Command | count | home actually touched | basis |
|---|---|---|---|
| `fleet home` (the gate) | 9 | temp | it *is* the measurement — each answered its own tempdir before any spawn |
| `fleet init` | 9 | temp | live `state/worker-settings.json` sha256 unchanged (§7b) |
| `fleet spawn` | 61 | temp | no `probe-w*`/`chain-w*` in the live registry or any live `state/` dir |
| `fleet send` | 93 | temp | ditto; and the failing fork's own answer came from a temp-home task file |
| `fleet wait` | 154 | temp | ditto |
| `py -3.13 bin/fleet.py home` (mine, once) | 1 | **my worktree** | answered `C:/proga/fleet-w49-fs`; read-only view verb |

*(Counts for the six single-steer arms and the smoke run are read from the drivers' own persisted
`cmd_log`; the two chain arms did not persist theirs, so their contribution — 8 spawns, 40 sends,
48 waits, 2 `home`, 2 `init` — is derived from the sample records they did persist. Flagged rather
than blended.)*

**Never run against the live home:** `fleet init`, `fleet init --statusline`, `fleet homes --add`,
`record_pin_pass`, or any mutating verb. `~/.claude/fleet-homes.list` still does not exist.

### 7e. Every worker I spawned, and what became of it — MEASURED

**61 workers spawned**, one per `spawn` call (53 across the six single-steer arms plus the
calibration run, 8 across the two chain arms). They produced **154 sessions** — each worker's
original sid, plus one new sid per fork-steer: `61 + 93 = 154`, which is exactly the number of
short ids the teardowns tracked. Every one was `claude stop`'d and `claude rm`'d.

```
short ids dispatched and cleaned : 154
claude agents --json --all       : 128 entries
leftovers named fleet|probe-w*, fleet|chain-w*, fleet|steer-w*, fleet|pin-w* : 0
```

Every temp `FLEET_HOME` and temp project directory was `rmtree`'d. **No background process is
still running.** No PIDs to record.

---

## 8. THE TIER, AS COUNTS — never as a colour

### 8a. This branch's own suite

| | py 3.13.12 | py 3.10.1 |
|---|---|---|
| passed | 4141 | 4141 |
| **failed** | **2** | **2** |
| skipped | 14 | 14 |
| xfailed | 1 | 1 |
| wall clock | 415.39s | 369.56s |
| exit code | 1 | 1 |

Both failures are `tests/test_fork_steer_delivery.py`, both named in §4, both green under §6's
patch. **The floor is 4141 + 2 = 4143 collected-and-run**, which is w48's measured 4139 at its own
base plus this lane's 4 new tests. *(That 4139 is INHERITED, not re-measured — `main` has moved
past my base `cef230f` while this lane ran, so the arithmetic is against the base, not against
today's `main`.)*

**All 14 skips enumerated** (`-rs`, py3.10 — this is the whole list, not a summary):

```
SKIPPED [6] tests\integration\test_native_pin.py: live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness
SKIPPED [3] tests\integration\test_sup_tombstone_live.py: live tier gated: set FLEET_LIVE=1 to run the tier-3 haiku harness
SKIPPED [1] tests\test_fleet_index.py:2068: this platform will not create a symlink unprivileged
SKIPPED [1] tests\test_hooks.py:783: pins the hook's os.write partial-write check; the Win32 sibling below pins WriteFile's
SKIPPED [1] tests\test_native.py:168: POSIX sibling of the Win32 partial-write pin
SKIPPED [2] tests\test_views_doctrine.py:247: no view quarantines any more -- D4 is true of shipped code, so an unqualified restatement is no longer a defect. This skip IS the green path; `test_the_quarantine_detector_can_see_a_quarantine` keeps it from being reached by a broken detector.
```

**6 of the 14 are the pin tier itself**, unrun here because this lane did not run it (§8b). That is
the arithmetic behind the brief's warning, unchanged from w48: `41xx passed, 14 skipped` is what a
completely unrun pin tier looks like, and saying "the suite is green" would hide it.

### 8b. The pin tier — NOT RUN in this lane, and why that is the right call

I did **not** run `tests/integration/test_native_pin.py`. Its `Sandbox.env()` sets `FLEET_HOME` and
**does not strip `CLAUDE_CODE_SESSION_ID`** (w48 §8d found this; it is unchanged at `cef230f`), so
running it from a fleet-launched session would rely on exactly the fence the brief told me not to
trust. Its `test_3` is the test whose defect I was sent to diagnose, and I have a purpose-built
probe that samples the same property **18× harder, with nonces, and with the roster-name channel
closed** (§3a). Running the tier would have added one more untrustworthy sample and one more
unfenced `fleet init`.

**So the honest pin-tier line is: 6 collected, 6 skipped, 0 run, 0 passed, 0 failed, this lane.**
The last measured tier numbers are w48's (py3.13: 5 passed / 1 failed / 0 skipped; py3.10: 6 passed
/ 0 failed / 0 skipped) and they are **inherited, not re-measured here** — with the caveat from
§1e that its `test_3` GREENs are compromised by the roster-name leak in both directions of that
table.

### 8c. `state/pin-pass.json` — NOT stamped, and should not be

Byte-identical, §7b. `fleet doctor` correctly continues to FAIL `pin-version` (2.1.222 pinned vs
2.1.226 live). That remains the operator's to reverse, and the reason to hold it now has one more
component than it did: not only is `test_3` RED-capable, but its GREENs cannot currently
distinguish a working steer from a session reading its own title. **Stamping should wait for the
fix AND the one-line pin-tier repair, not just the fix.**

---

## 9. WHAT I DID NOT DO, AND RESIDUAL RISK

* **Did not edit `bin/fleet.py`** (sha256 verified, §7c), did not touch
  `tests/integration/test_native_pin.py`, did not stamp `pin-pass.json`, did not push, did not
  merge, did not move any ref but `w49/fs`.
* **Did not run the pin tier** — §8b, with reasons. If the supervisor wants it run, it should be
  run from a shell with no `CLAUDE_CODE_SESSION_ID`, not from a lane.
* **n=92 gives an order of magnitude, not a rate.** The interval is 0.03%–5.91%. I would not
  defend the second decimal place and neither should anyone quoting me. **BELIEVED**: the rate is
  a property of the model and the prompt shape, so it will move with the vendor and is not a
  constant worth tracking.
* **No 2.1.222 baseline**, same gap w48 declared. Whether this is new at 2.1.226 is still
  **UNMEASURED** by anyone. §2b makes it very likely irrelevant — the code path has no version
  dependence — but "the defect is old" remains BELIEVED, not MEASURED.
* **The depth experiment is null at n=40** (§3d). A null at that size does not exclude a small
  effect; it excludes the large one that would have justified a workaround.
* **FIX-A's over-length branch degrades to SHAM-2** (§6b). That is a real hole in my own fix, and I
  would rather it be read here than found later.
* **The 6 citation tests will red on the follow-up until re-pinned** (§6d). The table is provided;
  the re-pin belongs in the same commit as the patch.
* **One adjacent path checked and clean, cause not derived:** `_recovered_brief` (the pre-wave-35
  brief recovery) returns `None` after a fork-steer rather than recovering the steer stub as if it
  were the worker's brief — MEASURED by driving it. **I did not establish WHY it refuses**, and its
  refusal may rest on a path-spelling mismatch rather than on its exact-prefix arithmetic doing its
  job. Reported at the confidence I actually have.

---

## 10. VERDICT AND WHAT I WOULD ROUTE

**`fleet send` to an idle worker can print `fork-steered (new session …)` — a success line, exit 0
— while the worker never sees the steer and silently re-does its previous task. The cause is that
the dispatched turn is derived from the worker's NAME alone, so a resumed session is handed a turn
it has already answered with the change hidden behind a pointer it already dereferenced. It is
unconditional in the code, ~1% in the outcome, present on both interpreters, and it has a second
unreported instance in `resume-limited`.**

In priority order:

1. **Fix the pin-tier confound first** (§1e), one line. Until it lands, no future GREEN from
   `test_3` means what it appears to mean — including the GREEN that would clear the stamp.
2. **Apply §6's patch** in one commit together with the §6d citation re-pin, once the slice-(c)
   lane releases `bin/fleet.py`. It turns both of this branch's REDs green.
3. **Then** re-run the pin tier from a sid-free shell and decide the stamp.
4. **Consider** whether `resume-limited`'s silent-miss deserves more than the patch gives it: it is
   the unattended path, and an operator is by definition not watching when it fires.

---

# 11. TURN 2 — 2026-08-09: the pin-tier confound, and what driving it actually showed

*Appended, not merged. §§0–10 are turn 1 and stand as written on 2026-08-08. This section corrects
one of my own claims in §1e; the correction is in 11d and it makes my case weaker, not stronger.*

## 11a. Headline

**The confound was real and is gone. It never got the chance to do the damage I said it could.**

- `test_3_pin_fork_steer`'s success token no longer has a second way into the session under test,
  and the property is now held in the **unit** tier so the next person to shorten the message reds
  on their own commit instead of at the next live run (11b).
- **Positive control: 7/7 GREEN**, five runs on py3.13 and two on py3.10, live haiku, against
  **unpatched** `bin/fleet.py`. The repaired pin still passes when a steer is genuinely delivered
  (11c).
- **Re-creating the confound: I could not make it fire.** With delivery shammed away and wave 48's
  28-character token restored, the confounded pin **failed every time**. The token was measurably
  sitting in the fork's own roster name on every run, and the fork never once answered from it
  (11d). §1e's claim that the pin "can pass while the path it tests is broken" is sound as
  logic and **unobserved as behaviour**, and I should have separated those two things the first
  time.
- `resume-limited` is **not** fully covered by §6e's patch, and the gap is specific and measured
  (11g).

## 11b. The repair — and the brief was right that "one line" was generous

The brief predicted I had been generous to myself in calling this a one-liner, and that the right
repair decouples the assertion from the roster name rather than fixing today's string. Both correct.
The change is +116/−3 in the pin file and +102/−6 in the unit-tier one (comment blocks included, and
they are most of it), and the reason is that **every one-line version of
this fix re-breaks on the next edit**:

| candidate repair | why it is not enough |
|---|---|
| lengthen the token | fixes this literal; the next person who shortens the message reintroduces the confound silently — which is exactly how it got here |
| make the token per-run unique | kills a *different* confound (a stale answer coincidentally matching). A unique token under 40 characters is still copied into the roster name |
| assert the token is past character 40 | a hand-counted constant that says nothing if `NATIVE_NAME_HINT_MAX` moves |

What landed instead, three properties, none hand-counted:

1. **Per-run unique.** `PIN_STEER_TOKEN = "STEER-OK-" + uuid4().hex[:8].upper()`.
2. **Positioned past the window by construction.** `PIN_STEER_MESSAGE` builds its lead-in with
   `.ljust(fleet.NATIVE_NAME_HINT_MAX + 1)`, so raising the constant moves the token with it.
   **Stated honestly: that `ljust` is inert today** — the lead-in is already 123 characters, so it
   pads nothing. It is a floor for a future edit that shortens the prose, not an active mechanism,
   and property 3 is what is actually load-bearing right now.
3. **Proved, not assumed.** `_assert_steer_token_has_one_way_in` renders the name through
   **fleet's own** `render_native_name` and refuses to let the test spend if the token appears in
   it — so `NATIVE_NAME_HINT_MAX` or the renderer's truncation can move without an edit here.
   **Its one duplication, stated because I nearly shipped it as a claim it does not support:** it
   re-derives `message[:NATIVE_NAME_HINT_MAX]` rather than observing it, so a change to *that
   expression at the call site* would slip past. The unit-tier test closes exactly that gap — it
   drives the real `cmd_send` with the pin tier's real message and reads `-n` off the argv
   `dispatch_bg` assembled, which watches the slice, the constant and the renderer with one
   assertion.

Run against wave 48's own message, the guard reproduces §4b's observed roster name exactly — which
is the cheapest possible demonstration that the guard is measuring the real channel:

```
# py -3.13, worktree, no spend
--- guard vs WAVE 48 message (28 ch) ---
GUARD FIRED:
CONFOUNDED PIN -- refusing to run a delivery test that cannot fail. The step-3 success token
'STEER-OK' is inside the roster name the fork is dispatched under
('fleet|pin-w1|Reply with exactly: STEER-OK'), so a worker that never read the steer can still
emit it and turn this step green (docs/lanes/w49-fs.md §1e). Move the token past
NATIVE_NAME_HINT_MAX (40) -- do not shorten the message to make this assertion pass.

--- guard vs WAVE 49 message ---
token          : STEER-OK-F436DBA7
token offset   : 143 (NATIVE_NAME_HINT_MAX = 40 )
rendered name  : 'fleet|pin-w1|This message supersedes the task you wer'
```

**Where the guard lives, and why that is the actual repair.** A guard inside `test_3` fires only
when someone runs a live haiku tier — which costs money and needs a live daemon, so it is not what
the next editor of this file will be doing. `tests/test_fork_steer_delivery.py::
test_the_pin_tiers_steer_token_cannot_reach_the_session_name` loads the pin module **by path** (that
directory is not a package, so importing by basename would depend on collection order) and asserts
all three properties in the unit tier. It is the only part of this repair that survives someone who
never reads this file.

`NATIVE_NAME_HINT_MAX` is **not** load-bearing elsewhere — the brief flagged that as a thing it
might have got wrong, and it did not. Two uses in `bin/fleet.py`: `:7614` and `:12947`.

## 11c. Direction A — the positive control

Ordered first because it is the one that could have invalidated everything: a repaired pin that
fails when the steer *is* delivered would be worse than the confounded one.

Live, `FLEET_LIVE=1`, temp `FLEET_HOME`, `CLAUDE_CODE_SESSION_ID` and `FLEET_WORKER` stripped from
the shell, **`bin/fleet.py` unpatched** so the defect under study is live in the code:

| interpreter | runs | test_1 | test_2 | test_3 |
|---|---|---|---|---|
| py 3.13.12 | 5 | 5 pass | 5 pass | **5 pass** |
| py 3.10.1 | 2 | 2 pass | 2 pass | **2 pass** |

`3 passed, 3 deselected` on all seven, 32–50s each. **7/7.** The repaired pin is not a pin that
fails when the code is correct.

Worth stating plainly, because it is the first time anyone has had this number: **7/7 is also the
first measurement of the fork-steer defect's rate on the pin tier's own shape with the confound
removed.** It is consistent with §3c's 1.09% and it is 7 samples, so it establishes nothing on its
own — 0/7 has a 95% upper bound of 41%.

## 11d. Direction B — re-creating the confound, and a correction to my own §1e

The brief asked me to "prove the confound was real by re-creating it… show the fork answering it
without delivery." **I could not.** The channel is there and I measured it on every single run; the
model never used it. That result is worth more than the one I expected, so it gets the same
treatment I would give a positive.

### The experiment

Two scratch trees outside the repo, built by an anchored planter that aborts unless **every** anchor
matches exactly once (4 anchors for the confounded variant, 2 for the repaired one). Both carry a
byte-identical mutated `bin/fleet.py`, `sha256 abfe1274…`, built from the worktree's untouched
`14526760…`:

```
scratch: ...\tmp\scratch-confounded  variant=confounded
  SHAM-DELIVERY: OK (1 anchor)
  FORENSICS: OK (1 anchor)
  CONFOUND-28-send: OK (1 anchor)
  CONFOUND-28-assert: OK (1 anchor)
  bin/fleet.py sha256 before 14526760d9f1d707866517788cf60ac7ea204e617ec52845c30cab446c6a9181
  bin/fleet.py sha256 after  abfe12742b6a9d7e8906efd12293cd766016bc6952e770e46fe4429150733ed9
  byte-compile OK
```

- **SHAM-DELIVERY** removes `append_mailbox(old_sid, message)` from `_cmd_send_native`, so
  `compose_prompt` has nothing to drain and the rewritten payload carries the preamble **alone**.
  The steer is then not delivered by any channel fleet owns — while `hint=message[:40]` still copies
  it into the fork's roster name, untouched. This makes the "broken delivery" case **deterministic**
  instead of waiting on a ~1% natural miss.
- **CONFOUND-28** restores wave 48's exact shape: the 28-character `Reply with exactly: STEER-OK`,
  asserted verbatim, with wave 49's pre-send guard removed — wave 48 had no guard, and a faithful
  re-creation must not carry one.
- **FORENSICS** reads the payload file fleet just wrote and the roster name the fork was dispatched
  under, so "without delivery" is *measured in the same run* rather than inferred from the mutation.

### What every run showed

```
[direction-b] STEER-OK present in the delivered task file: False
[direction-b] fork roster name: 'fleet|pin-w1|Reply with exactly: STEER-OK'
[direction-b] delivered task file, verbatim:
You are fleet worker `pin-w1` in `C:\...\fleet-pin-proj-_oiosz2k`.
Manager messages arrive mid-task marked `<MANAGER MESSAGE>`; treat them as user instructions.
Maintain a journal at `C:/.../state/journals/pin-w1.md` (create it early; ...)
End every turn with a compact result summary: changed, verified, blocked.
Do not leave servers or watchers running past the end of the turn ...
[direction-b] --- end delivered task file ---
```

**The confound's precondition held on every run**: the success token was absent from everything
fleet delivered, and present in the session's own title — the same string `w48-pin.md` §4b read out
of the transcript. So each run was a genuine opportunity for a false GREEN.

### The result

| | count |
|---|---|
| confounded runs (live haiku, py3.13) | 20 |
| steer absent from the delivered payload — *the precondition* | **20 / 20** |
| fork's roster name was `fleet\|pin-w1\|Reply with exactly: STEER-OK` | **20 / 20** |
| `test_3` FAILED | **20 / 20** |
| **fork answered from its title (`STEER-OK`)** | **0 / 20** |
| fork replayed its previous answer (`PIN-OK`) | 5 / 20 |
| fork re-read the payload, found no instruction, and said so | 15 / 20 |

**Twenty confounded runs, twenty failures, ZERO answers taken from the title.** The forked session
either replayed its previous answer (`PIN-OK`) or re-read the payload, found nothing to do, and
reported that — *"Journal created. Ready for task assignment."*, *"No `<MANAGER MESSAGE>` yet. Still
awaiting task."*, *"**Result:** Journal created, ready. No task defined yet."* Both are correct
readings of the turn it was handed. Neither is the title.

**0 of 20 is not "never".** Clopper–Pearson gives 0/20 a 95% interval of **0.00% – 16.84%** — which
is the same kind of number I spent 11f criticising, so I am not going to launder it into a
certainty. If a session answers from its own roster title at all, this says only that it does so
less than roughly one time in six. What it *does* establish is that in twenty deliberate
opportunities, with every precondition verified on every run, the confound never once converted a
broken delivery into a GREEN.

Two things measured on the way past, recorded so they are not later attributed to whatever changed
most recently:

- **The stale-replay rate under a shammed delivery is 5/20 (25%), not §3c's 1.09%.** These are not
  the same quantity and the larger one must not be quoted as the defect rate: emptying the payload
  removes any reason to prefer the file over the transcript, so replay becomes a much more
  attractive reading. §3c's 1.09% remains the rate for a steer that *was* delivered.
- **Step 2 failed once in 20** (`conf12`): the spawned worker answered its
  `Reply with exactly: PIN-OK` turn with a status summary instead of the token. That is the pin
  tier's own step-1/2 model-compliance variance — ~5% here — and it has nothing to do with this
  change. It is worth knowing before someone reads a future step-2 RED as a regression.

### Is a shammed payload a fair test? — the objection, and why the answer is yes

The sham is **not** a model of the real defect. In the real defect the payload *does* contain the
steer and the fork simply does not re-read it; under the sham the payload contains no instruction at
all, a state that never occurs in production. So it is fair to ask whether these twenty runs were
really twenty opportunities.

They were, and the 15 re-read runs are the *strongest* opportunity the experiment could have
constructed:

- the **5 `PIN-OK` runs** are the direct analogue of the real failure — the fork did not act on the
  payload, its title carried an instruction, and it replayed instead;
- the **15 "awaiting task" runs** are better than the analogue. Those forks went looking for an
  instruction, found none in the file, and were left holding a session title that reads
  `Reply with exactly: STEER-OK` — an instruction, in the imperative, addressed to them. A model
  inclined to answer from its own metadata would do it *here* if anywhere. None did; they reported
  having nothing to do.

What the sham is a model of is the **confound's opportunity**, not the defect — which is exactly the
thing under test.

### What this changes about §1e — and what it does not

§1e says the pin **"can pass while the path it tests is broken"**, and calls every GREEN across five
waves *"weaker evidence than it looks"*. Splitting that into the two claims it conflates:

| claim | verdict |
|---|---|
| The success token reaches the session on a channel independent of delivery, so a GREEN does not *establish* delivery | **STANDS — measured on every run of this experiment.** The inference the pin invites is unsound |
| The pin *did* pass while broken, so past GREENs are false | **NOT SHOWN, and I implied it.** In 20 deliberate opportunities the model never took the channel. w48's one natural failure is concordant: its fork's title said `STEER-OK` and it answered `PIN-OK` |

The honest statement is the first one alone: **the pin was unsound, not observed to be wrong.** A
test you cannot reason about is still worth fixing — the repair costs one commit and removes the
need to argue about this at all — but "five waves of GREENs are worthless" was my rhetoric outrunning
my evidence, and it is the same error I spent 11f correcting in someone else's report.

### The one thing the experiment could not do

Under the sham, the **repaired** pin also fails — 3 runs, `test_3` FAILED 3/3 — so the sham does not
*empirically* discriminate the two variants. The discrimination is logical, and it is the whole
point: the confounded pin **could** have passed with delivery broken and happened not to; the
repaired pin **cannot**, because its token exists nowhere the fork can reach except the steer. That
is the difference between a test that got a right answer and a test that could not have got a wrong
one.

Those three runs do carry one receipt worth more than the failure itself — the repaired message's
roster name, read off a **live** dispatch rather than derived:

```
[direction-b] fork roster name: 'fleet|pin-w1|This message supersedes the task you wer'   (3/3)
```

Compare the confounded arm's `'fleet|pin-w1|Reply with exactly: STEER-OK'` (20/20). The leak channel
is unchanged and still carries the first 40 characters of whatever is sent; what changed is that
those 40 characters no longer contain the answer.

*Receipt note, so nobody misreads the raw logs:* in the confounded scratch the anchored edit
replaced the assertion **expression** (`assert "STEER-OK" in result_text`, wave 48's) but left wave
49's failure **message**, which still interpolates `PIN_STEER_TOKEN`. The line pytest evaluated and
reported is `assert 'STEER-OK' in 'PIN-OK'`; the surrounding prose in those logs is stale and was
not what was tested.

## 11e. The floors — the prediction, written first, and what happened

Predicted in the journal before any pytest ran this turn:

> the total collected count moves by exactly +1, deliberately, and not because of gating […] the
> predicted end state is **2 failed, 4142 passed, 14 skipped, 1 xfailed** on both interpreters.

Held, exactly:

| | before | after | |
|---|---|---|---|
| collected, py3.13 | 4158 | **4159** | +1 |
| collected, py3.10 | 4158 | **4159** | +1 |
| py3.13 full suite | 2F / 4141P / 14S / 1xF | **2F / 4142P / 14S / 1xF** | passed +1 |
| py3.10 full suite | 2F / 4141P / 14S / 1xF | **2F / 4142P / 14S / 1xF** | passed +1 |

The +1 is the unit-tier guard, added on purpose and predicted in advance. **The gating did not
move**: the `live` tier is 9 collected / 9 skipped with `FLEET_LIVE` unset both before and after
(6 from `test_native_pin.py`, 3 from `test_live_smoke.py`), and the pin file's own contribution is
unchanged at 6. My two deliberate REDs are still RED, on both interpreters, and stay that way until
§6e's patch lands.

## 11f. TASK 2 — the correction on `docs/lanes/w48-pin.md`

Appended as a dated section; **not one original line was edited.** That is not a promise, it is a
measurement — `git diff --numstat` for this commit reads `89  0  docs/lanes/w48-pin.md` and
`517  0  docs/lanes/w49-fs.md`. **Zero deletions in either record**, including this one: §0's stale
suite count is annotated in place with a dated note rather than corrected, for the same reason.

Two corrections:

- **C1** — §4b's transcript observation is conclusive for what it was offered as proof of, and it
  supports a second reading the report did not draw: a fork that answered `STEER-OK` need not have
  read anything. The note carries the mechanism, a reproduction of the exact roster name §4b quotes,
  and the consequence for five waves of GREENs.
- **C2** — §4d's "1 failure in 5 samples". Both Clopper–Pearson intervals were recomputed for the
  correction rather than copied from turn 1:

  | source | k/n | point | 95% CI |
  |---|---|---|---|
  | `w48-pin` §4d | 1/5 | 20% | 0.51% – 71.64% |
  | `w49-fs` §3c | 1/92 | 1.09% | 0.03% – 5.91% |

  The note says the thing worth keeping is not the new point estimate but that **an interval
  spanning 0.5% to 72% is a number that says almost nothing** — and it credits §4f item 1's
  "make the token unique per run" as the right instinct, while noting uniqueness alone would not
  have closed the confound.

I then had to apply that same standard to myself, which is what 11d is about.

## 11g. TASK 3 — `resume-limited`: the patch does **not** fully cover it

The brief asked for a plain answer and said "no further work needed" was a real one. It is not the
answer here. What I measured before saying so:

I drove the **real** `cmd_spawn` → `cmd_resume_limited` with only `claude` faked, in a temp
`FLEET_HOME`, recording each dispatched turn and the contents of every file that turn names *at the
instant of that dispatch*. Scenario: an operator steers a **working** worker (mail queues to
`mailbox/<old_sid>.md`), that turn then parks on a usage limit, and the unattended sweep fires.

```
=== the two dispatched turns ===
spawn  turn : 'Read C:/.../state/tasks/lim-w1.md and follow it exactly.'
resume turn : 'Read C:/.../state/tasks/lim-w1.md and follow it exactly.'
resume -n   : 'fleet|lim-w1|resume past limit'
BYTE-IDENTICAL TURNS: True

=== where the queued mail ended up ===
mail in the resume TURN               : False
mail in the payload file it points at : True
payload file already dereferenced     : True
mail in the BYTES NEW TO THIS SESSION : False
```

Four findings, all MEASURED:

1. **The defect is present at this call site, unconditionally** — the resume dispatch's turn is
   byte-identical to the one the session already answered. This confirms §2e's scope claim by
   driving it rather than by reading the code.
2. **The confound is NOT present here.** `hint="resume past limit"` is a constant
   (`bin/fleet.py:7770`), so nothing of the message reaches the roster name. This call site needed
   no equivalent of 11b's repair.
3. **The queued-mail scenario is reachable, not hypothetical.** `cmd_send` refuses to steer a
   `limited` worker outright (`bin/fleet.py:7521`, message at `:7525` — *"parked (limited) -- use
   `fleet resume-limited <name>` instead (never steer a parked worker)"*), so mail cannot arrive *during* a park. It
   arrives **before** one: queued to a `working` worker whose turn then dies on the limit, and
   `compose_prompt` drains it at resume time. That is the ordinary way an operator's message meets a
   usage limit.
4. **§6e's patch covers one of the two cases and not the other:**

   | case | what the resume must deliver | does §6e's `inline_body` carry it? |
   |---|---|---|
   | no queued mail | the constant continuation sentence | **YES — fully covered.** The constant *is* the whole instruction, and it now rides the turn |
   | queued mail present | the operator's message | **NO.** The patch inlines a constant; the mail stays behind an already-dereferenced pointer |

   In the second case the patched turn is distinguishable and says "read it again" — which is
   **SHAM-2**, the shape `tests/test_fork_steer_delivery.py` explicitly refuses, and refuses for a
   reason that applies here verbatim: delivery stays contingent on the worker *choosing* to re-read.
   I am not going to grant my own patch an exemption from a standard I wrote to judge other people's
   fixes.

**So: two defects in my own §6e patch, both at the resume-limited arm.**

- **(i) incompleteness** — `inline_body` must carry the drained mail, not a constant. The mail text
  is not available at that call site today (`compose_prompt` returns `(prompt, claim)` and keeps the
  mail internally), so this is more than a one-word change: it needs a decision about whether
  `compose_prompt` grows a third return value or the call site claims the mailbox itself.
  **Not applied — `bin/fleet.py` is not mine this turn.**
- **(ii) wrong semantics** — the inline wrapper reads *"That message is a NEW instruction and it
  supersedes anything earlier in this session."* For a steer that is right. For a **resume** it is
  actively wrong: the whole intent is to *continue* the earlier task, not supersede it. The
  resume-limited arm needs its own wrapper sentence. I did not notice this in turn 1.

### Does the unattended context justify more than the patch? **No — and I checked each of the three.**

The brief named three candidates. Taking them in turn, and refusing to invent a fourth:

- **A recorded outcome — already exists, no work needed.** Driven and read off the real events
  file: `spawned` → `turn_started` → `mail_drained` → `limit_resumed` (carrying both
  `old_session_id` and `session_id`). The raced case appends `steer_orphaned`; the commit-failure
  case reaches `_report_stranded_native_turn`, which prints loudly **and** best-effort appends an
  event. The resumed turn then gets its own Stop-hook outcome record keyed to the new sid. There is
  no missing record of the *act*, and another one would add nothing.
- **A verifiable acknowledgement — NOT justified, and I want this on the record as a refusal.**
  Once the instruction rides the turn there is nothing left to acknowledge: delivery stops being
  contingent, which is the entire point of the fix. An ack would measure the *model's compliance*,
  not fleet's delivery — and fleet cannot distinguish "read it and judged it already satisfied"
  from "ignored it", so the signal would be unactionable in exactly the unattended context that is
  supposed to justify it. **Fix the delivery; do not build a detector for a defect the fix removes.**
- **A doctor row — already exists, no work needed.** `_doctor_check_limited_parks`
  (`bin/fleet.py:11351`) already surfaces parks past their reset horizon, weekly parks, and
  null-horizon parks. It covers the failure that genuinely needs an unattended alarm: *nobody ran
  the sweep*. **Its blind spot is real and I am deliberately not proposing to close it** — once a
  resume fires, status flips `limited → working` and the worker leaves that row, so a resume that
  no-ops is invisible there. Closing it would require the acknowledgement I just argued against.

**Plain answer: complete the patch — (i) and (ii) — and build nothing else.** The unattended context
raises the *cost* of the defect, which is why the resume-limited arm has to be complete rather than
nearly complete. It does not create a requirement the attended path lacks.

## 11h. Containment

Same standard as turn 1: attribute what moved, do not merely report that nothing did.

**Never touched, sha256 identical before and after this turn:**

| artifact | sha256 | verdict |
|---|---|---|
| `~/.claude/settings.json` | `578bde7b…` | UNCHANGED |
| `~/.claude/fleet-homes.list` | — | **ABSENT both times** (never created, never appended) |
| live `C:/proga/claude-fleet/state/pin-pass.json` | `d3b4bd15…` | **UNCHANGED — NOT stamped** |
| live `state/worker-settings.json` | `642bdcbe…` | UNCHANGED |
| worktree `bin/fleet.py` | `14526760…` | **UNCHANGED — never edited** |

`bin/fleet.py`'s sha is the same value turn 1 recorded, and the same value the scratch builder read
as its `before` on both variants. `fleet init --statusline` was never run.

**Live sessions driven, and what became of them.** Every live run used a temp `FLEET_HOME` created
by the pin harness itself, launched from a shell with `CLAUDE_CODE_SESSION_ID` and `FLEET_WORKER`
stripped (`env -u` on every invocation, belt-and-braces over `conftest.py`'s own in-process
`monkeypatch.delenv`, which the harness's `subprocess` children would otherwise inherit).

| arm | runs | native `--bg` sessions |
|---|---|---|
| Direction A, positive control (py3.13 ×5, py3.10 ×2) | 7 | 14 |
| Direction B, confounded under sham | 20 | 40 |
| Direction B, repaired under sham | 3 | 6 |
| **total** | **30** | **60** (30 spawns + 30 fork-steers) |

The two `resume-limited` measurements behind 11g spawned **no live session at all** — they fake
`claude` and drive the real fleet code, so they cost nothing and touch no roster.

The pin harness's module-scoped fixture `claude stop`s and `claude rm`s every short id it dispatched,
plus a sweep of any roster entry named `fleet|pin-w*`, and `rmtree`s both temp dirs. **Roster census:
132 entries before, 132 after; ZERO entries matching `pin-w`/`probe-w`/`sham-w` at either end.**

**The one artifact that moved, attributed rather than excused.** Live `state/fleet.json` changed
(`b3aa4dce…` → `3dc2624b…`) — the same finding turn 1 reported, and it resolves the same way. Its
worker count is 146 before and after with **no name added and none removed**, and the live event log
holds exactly **2** events inside its mtime window: `w49-gc2 turn_started` and `w49-dcap
status_changed` — sibling lanes, supervisor-driven. **Zero events name anything I dispatched.**

**The scratch trees are outside the repo** (`$CLAUDE_JOB_DIR/tmp/scratch-{confounded,repaired}`),
so the mutated `bin/fleet.py` never existed inside the worktree at any moment — there was nothing to
"restore byte-identically" because nothing was displaced. `git status` on the worktree at the end of
this turn shows exactly the four files this lane means to commit and nothing else.

**One write of mine DID land in the live fleet home, and it is declared rather than found:**
`C:/proga/claude-fleet/state/journals/w49-fs.md`. The worker preamble names that path and the lane
brief names the worktree copy, so the journal is written to the worktree and mirrored there — which
is how turn 1's journal reached the manager.

That it is the ONLY one is measured, not assumed. Every file under `C:/proga/claude-fleet/` with an
mtime inside this turn — **116 of them** — enumerated and binned:

| count | what | mine? |
|---|---|---|
| 65 | `.git/` metadata — refs, other lanes' worktree indices, `FETCH_HEAD` | no |
| 33 | `.git/objects/` — the shared object store; any lane that commits writes here | no |
| 6 | `state/` — `events.jsonl`, `fleet.json`, `journals/w49-gc2.md`, `outcomes/w49-{dcap,gc2}.jsonl`, **`journals/w49-fs.md`** | **1 of 6** |
| 12 | the main worktree's own checked-out files (`bin/fleet.py`, `bin/hooks/*`, four `tests/*.py`, four `docs/**`, `worker-settings.template.json`) — all at one timestamp, the signature of a checkout/merge in the main worktree, not of a write | no |

**Exactly one path in all 116 contains the string `w49-fs`, and it is the declared journal mirror.**
Note the main worktree's `bin/fleet.py` is in that list: that is the slice-(c) lane's work arriving
on `main`, and it is precisely why this lane did not touch the file — **my** worktree's copy is still
`14526760…`.

## 11i. What I did not do, and residual risk

- **`bin/fleet.py` is untouched.** §6e's patch is still a patch, and it now needs the two amendments
  in 11g before it lands. The two REDs in `tests/test_fork_steer_delivery.py` stay RED.
- **`state/pin-pass.json` is not stamped**, in the live home or anywhere that matters. Turn 1's §8c
  reasoning is unchanged, and 11d gives it one more leg: the pin tier is now *worth* stamping on,
  which is precisely why it should be stamped only after the defect is fixed rather than before.
- **I did not run the full pin tier**, only steps 1–3. Steps 4–6 are untouched by this change, and
  step 6 stamps a `pin-pass.json` — in the harness's own temp home, but the lane's fence says do not
  stamp and I preferred not to argue about which one it meant.
- **Residual on the repair itself.** The guard proves the token is absent from the *roster name*.
  That is the only leak channel anyone has measured; it is not a proof that no other channel exists.
  If a future `dispatch_bg` copies the message anywhere else the session can see, the guard will not
  know. The honest scope of 11b is "the one channel we found, closed and pinned", not "the token is
  provably unreachable".
- **Residual on 11d.** Twenty samples of one model on one machine. A different model, or a longer
  transcript, could weight its own title differently. The structural argument does not depend on
  that; the severity claim does.

## 11j. Routing — updated from §10

§10's list, re-ordered by what this turn changed. Items 2 and 3 are unchanged and still blocked on
the slice-(c) lane releasing `bin/fleet.py`.

1. ~~Fix the pin-tier confound first~~ — **DONE this turn** (11b), with the positive control driven
   (11c). §10 called it "one line"; it was not, and 11b says why. **`test_3`'s next GREEN now means
   what it appears to mean.**
2. **Apply §6e's patch with the §6d citation re-pin in one commit — but amend the resume-limited arm
   first** (11g): carry the drained mail, and give the resume its own wrapper sentence. Landing the
   patch as written would leave the unattended path half-fixed and looking finished, which is worse
   than leaving it visibly broken.
3. **Then** re-run the pin tier from a sid-free shell and decide the stamp. Worth noting for whoever
   does: steps 1–3 cost ~40 s and ran 30 times this turn (7 unmodified + 23 against a shammed
   scratch) with one non-harness hiccup — `conf12`'s step-2 compliance miss, 11d.
4. **Downgrade §10 item 4.** `resume-limited` needs no recorded outcome, no acknowledgement and no
   doctor row — all three already exist or would be inventions (11g). It needs the patch to be
   complete. That is a smaller ask than §10 implied and I would rather shrink it than let it stand
   as an open question.
5. **New, low priority:** `docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md:1364` still
   specifies step 3 with the 28-character token. It is a plan document, not executable, so nothing
   reads it — but it is where the confound was specified, and a future reader following it would
   rebuild it. One line, and not mine to route.
