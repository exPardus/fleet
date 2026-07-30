# Next session — handoff (written 2026-07-29 by the interface session)

## THE LONG-TERM GOAL, set by the operator 2026-07-29

**Get fleet to launch-ready, and the completion criterion is MULTI-FLEET: independent fleets scoped
per session, per repo, or per dir.** Today there is exactly one fleet on this machine. That is the
gap between where the tool is and where it ships.

**It is a future-item stub, not a spec.** Derive it yourself — do not inherit a design from this
handoff, because there isn't one and anything I invented here would travel as authority without
evidence, which is the failure this repo has paid for twice this week. Where to start reading, in
this order:

- `docs/ROADMAP.md` **Phase 6 — Reach**, the `F26`/`M25` multi-machine bullet. It is the closest
  ratified precedent and it already ruled the shape of the adjacent problem:
  *"per-machine registries with a read-only federation view — never a shared writable `fleet.json`
  or git-synced `state/`."* Multi-machine is not multi-fleet, but the reasoning transfers and the
  refusal it encodes is load-bearing.
- `docs/SPEC.md` — the **numbered nine-invariant section**. Three bind this hardest: **(6)
  single-writer registry, (7) one-live-claude-per-session, (9) one-state-many-views.** Every phase
  stub carries a mandatory `## Invariants touched` section citing numbers and saying why each is
  preserved. Yours must too.
- `docs/ROADMAP.md` "Review disciplines" — **flag, not subsystem** (re-vet for a flag-sized
  alternative delivering 80%), **check the graveyard first** (`docs/IDEA-FORGE-REPORT.md` §5, ten
  dead ideas with causes of death), and the soak/demand-check rule: **specs always run; BUILD is
  what's gated.**

**Process, non-negotiable and already ratified: GATE THEN BUILD.** Spec it, dual-lens gate it, put
it to the operator, then build. A 1278-line spec that cleared neither lens is sitting in the queue
right now as the standing example of what happens otherwise.

**Advertising is downstream of this and is NOT yours to execute.** Preparing assets is fine.
Publishing anything outward — a post, a landing page, a release — is irreversible and needs the
operator's explicit go-ahead each time. Prepare, then ask.

## THE SECOND GOAL: THIS IS A STRESS TEST OF THE ARCHITECTURE

**Can ONE overhead session clear this job?** That is a live question about the three-tier design, and
you are the experiment. Wave 10 hit the 200k ceiling in 31 minutes and merged nothing. Wave 9 lasted
32 minutes and merged one branch. If one interface session cannot hold the plan across a queue this
size, that is a finding about the architecture — **report it as a result, not as a personal failure.**

Track it deliberately: your own context burn against work cleared, how many supervisor incarnations
the queue costs, and where the overhead actually goes. **Deliver an honest verdict at the end.**
"One overhead session is not enough, here is the measurement" is a valid and valuable outcome.

## YOU ARE THE INTERFACE TIER — AND YOU DO NOT TOUCH WORKERS

Two hard rules. The second is a **correction to how the previous session ran**, so do not copy the
pattern you will find in this session's transcript or commits.

**1. Never run `fleet sup-boot`.** Bootstrap with `fleet sup-spawn --task @<brief>`; steer with
`fleet send supervisor @<file>`. `sup-boot` claims the supervisor identity for *your* body, and an
interface session never exits, so its claim never clears. **The claim belongs to a role, not a body.**

**2. NEVER DIRECTLY DRIVE A WORKER.** No `fleet spawn`, no `fleet send <worker>`, no `respawn`, no
`kill` against any worker. **The supervisor owns every worker without exception.** You own the plan
and the operator channel; it owns execution. If a worker needs dispatching, steering, unsticking or
retiring, you tell the supervisor and *it* acts.

The previous session broke this — it spawned four councilors, two builders, and steered a stuck
worker directly. It worked, and that is exactly why the rule needs stating: **a shortcut that works
is the one that gets copied.** It also contaminates the stress test above, because an interface doing
the supervisor's job is not a measurement of the supervisor tier.

**Read-only verbs stay yours** — `status`, `peek`, `result`, `sup-status`, `doctor`, `autoclean`.
Watch everything; drive only the supervisor.

**Tension you must resolve rather than route around: the 4-councilor council needs workers.** Under
this rule you cannot spawn them, so the supervisor dispatches the council at your request and returns
the verdicts. Independence is the council's whole value, so specify it explicitly in what you hand
the supervisor: no shared context between councilors, no visibility of each other's verdicts. If the
council is adjudicating the supervisor's *own* work, say so and decide how to keep it honest — that
is a real design question this handoff is deliberately not pre-answering.

## FIRST ACT, EVERY TIME: REVIVE THE FLEET IF IT IS DEAD.

`fleet sup-status`. If GOALS is active and no supervisor holds the claim, **the fleet is stopped and
cannot start itself** — `sup-spawn` one immediately, then say what you found and what you started.

**This is now four dark windows: 3h38m, ~4h, 12h53m, and 46h.** The 46h one is live as you read
this. Every time, every mechanism worked perfectly and the fleet sat dead because nobody was
reading. There is deliberately no fleet-side watcher — it would fire in sessions nobody asked to be
fleet-aware (D7), or dispatch with no operator in the loop, which is how two live supervisors
happen. **You are the restart path. There is no other one.**

## Operator's standing directives

1. **Work fully autonomously** when the operator is away. Never stall waiting for them.
2. **PUSH `main` TO ORIGIN AS WORK COMPLETES** — at every green milestone, not at session end.
3. **Keep 6–8 builders saturated.** An idle roster is the defect, not a rest state. Slice by disjoint
   FILE SETS; merge `bin/fleet.py` slices ONE AT A TIME, re-running both floors after each.
4. **Keep making fleet better.** We build fleet with fleet, so its own failures are the best defect
   reports on the machine — mine them. Two of this session's best slices came from watching it break.
5. **Steer interactively** — short waits, frequent `status`/`peek`, correct drift immediately.
6. **YOU own the plan; the supervisor slices, dispatches, gates, merges.** Pull it back if it re-plans.
7. **4-councilor council** (risk / delivery / strategist / incident) + synthesis for anything
   operator-gated and genuinely blocking. Act on the synthesis; record it; file the ratification.

## State — RE-MEASURE, never inherit these numbers

`main` = **`7b9c9d8`**, pushed, `origin` in sync (verified with `git ls-remote`, not the tracking
ref). Last measured suite was **2811 passed / 13+1 skipped** identical on both floors — but that was
at `b7c5c85`, two commits back. **Measure it yourself.** The `+1` skip is the win32 symlink reparse
pin and skips LOUDLY by design — do not "fix" it.

**Fleet is DEAD** — supervisor released `2026-07-28T00:30:57Z` at the hard ceiling (refused at
201,149 tokens against 200,000; the ceiling worked). Six of seven workers read `dead-suspected`
"no outcome record" and **one idle** (`succ-spec-fix`, real result). **Do not trust
`dead-suspected` before checking `state/hook-errors.log`** — see the recovery pattern below.

**One operator gate is OPEN**: the §7 exemption envelope, ruled provisionally by council, awaiting
Altai's ratification. Nothing narrowed while it waits. `docs/decisions/W9-section7-council-synthesis.md`.

## Queue

1. **Merge queue, order FIXED:** `idx/q` (`bd1191b`) → `idx/teach` (`573a905`) →
   `fix/stillborn-handoff` (`87cbf9a`) → `fix/autoclean-archive-gate` (`e4a0730`).
   `fix/outcome-surrogate` is disjoint and slottable anywhere — **verify it exists as a branch; its
   worker died before reporting.** Hazard, already characterised, do not re-derive: the `M1_DEFECT`
   characterisation test lives ONLY on `idx/q`, so the red at core→q is resolved by RETIRING that
   test, never by weakening core.
2. **`state/tasks/lens/w10-permstall.md`** (140 lines) — written, worktree created, allow-listed,
   never dispatched. The ceiling refused the dispatch. **Free work, first act.**
3. **Verify the `:2174` repair landed** on the acgate branch (Task 6) — it is a *condition* of the
   council's Verdict A, not a follow-up.
4. **Sever the succession spec**: Parts 1+2 (~460 of 1278 lines, no gate content) are buildable now;
   the CRITICAL-1 quarantines to Part 3, which waits on the operator.
5. Then `fleet q` M2, the `[UNBUILT]` sweep (10 tags in `SPEC.md` + 3 shipped defects at `:344`),
   and the multi-fleet spec above.

## Launch-surface debt, measured 2026-07-29 — verify before acting

- **`README.md` badge says `tests-2022 passing`; actual is 2811.** Stale number on the front door.
- **macOS is unreceipted** — shares the POSIX backend, no run has ever executed on it. The badge is
  honest; the gap is real.
- **`docs/ROADMAP.md` opens with a ⛔ SUPERSEDED banner.** A public roadmap whose first line is
  "superseded" is a bad front door.
- **Root-level scratch files** — `FIX-WAVE-*.md`, `REVIEW-INPUT-*.md` sit in the repo root.
- **No packaging** — no `pyproject.toml`/`setup.py`; install is clone + `fleet init`.

## Patterns that worked this session — reuse these

Most are **brief-writing** patterns. You still write briefs; they now go to the supervisor, and the
brief-quality rules propagate down when you require the supervisor to apply them to its own workers.

- **Every brief ends with "WHAT THIS BRIEF GOT WRONG — assume it contains an error and go find it."**
  Hit rate this session: **4 of 4 councilors** found real errors, including a line number rotted by
  316 lines that four separate documents had propagated. Single highest-value line in a brief.
  **Require the supervisor to put it in every worker brief it writes.**
- **Councilors get NO shared context and are told not to guess each other's verdicts.** Two of them
  independently killed a false claim the whole chain had been carrying. Independence bought that —
  so make it an explicit instruction to whoever dispatches them, not an assumption.
- **Require driving, not arguing.** "Verify the diff yourself, do not take the description." The risk
  lens confirmed a non-narrowing claim by reading it; the incident lens drove a refusal from a third
  independent caller to escape *"evidence from the broken component is not evidence."*
- **Require RED-then-GREEN on every pin.** A test that would have passed before the change proves
  nothing. And: *break your own pin the way a future editor would, not the way the defect did* — this
  session's CRITICAL was a pin gated behind `if "in flight" in err:` that stayed green under a
  line-count-identical reword.
- **When a result is missing, check `state/hook-errors.log` before believing a worker died.** A hook
  that cannot write an outcome logs the whole payload verbatim. Recovered 14,760 characters of a gated
  review this way. `fleet result` returning empty is not evidence of failure — this is read-only and
  stays yours, and it is worth teaching the supervisor.
- **Verify the rendered brief with `wc -l` after `sup-spawn`.** A returned session id has not proven a
  brief was dispatched. Require the supervisor to do the same for every worker it dispatches, and to
  **verify a worktree's HEAD sha as a separate step before spawning into it** — it lost two dispatches
  that way this week.
- **`--task` takes TEXT; a file is `--task @<path>`.** A bare path renders *itself* as the task.
  Author briefs in `state/tasks/lens/`, never at `state/tasks/<workername>.md` — dispatch overwrites
  that exact path.
- **Write steers to a file and `send supervisor @file`.** Bash eats backticks; PowerShell mangles quotes.
- **`env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py …`** clears §7's gate when a `sup-*` verb is
  refused by the wedge it would clear. You will need it.
- **Answer a parked decision through `fleet sup-decision --answer`**, never as prose in a steer. It
  takes TEXT with no `@file` form — use shell command substitution.
- **Publish provisional rulings rather than holding them.** The wave-10 supervisor overturned part of
  mine within the hour and was right. A ruling that survives a hostile read is worth more than one
  nobody tested.
- **Keep briefs SHORT and act-first.** Five supervisors in a row each burned a full context reading
  long handovers and merged nothing; the one handed a one-page "merge first, read second" brief merged
  the blocker on its first turn. A long handover is not thoroughness, it is the named failure mode —
  and it is the direct enemy of the stress test above.

## Doctrine worth not re-learning

- **A clean shutdown with no reader is indistinguishable from a healthy fleet.**
- **A claim gains authority at every hop and evidence at none.** Twice this week: "0 turns" (a
  registry accounting defect — 82KB transcripts existed all along) and the handoff "inversion"
  (false; `cmd_sup_release` writes a fresh dict that never copies the token). When a claim arrives
  pre-endorsed by three documents, that is a reason to measure it, not to trust it.
- **The exemption is not transitive.** A clearance argued at one level of a call graph says nothing
  about the level below. When a finding says "I checked and we are safe", ask WHICH FRAME.
- **Verifying provenance is not verifying fitness.** A worker hung nine minutes on a hash-verified,
  known-good allow-list that was tuned for review workers and hard-denied `git merge`. **A hard deny
  beats bypass mode**, and a denial presents as a hang while status reads `working`.
- **A guard's postcondition must be satisfiable by every legitimate caller class**, and **a verb that
  clears a state must not be gated on that state.** Both are DESCRIPTIVE/UNRATIFIED — cite the
  measurement, never these sentences, as authority.
- **A doc describing a CLI must be re-derived from `--help`, never from memory.**
- **Measure the incident before drawing the lesson** — "~15h dark" was 12h53m; the corrected number
  was worse.
- **Fix waves mint defects: 7 of 7.** Re-gate everything; ESCALATE beats a third wave.
- **`sup-context` after any UNPLANNED unit of work, not only at wave boundaries** — wave 10's own
  rule, learned by hitting the ceiling when a mid-wave council ruling reshaped its plan.
- **Absence is not evidence on this substrate.** `git log` is the only truth a turn landed.

## Ledgers

`knowledge/lessons.md`, `docs/decisions/W9-section7-council-synthesis.md`,
`docs/AUTONOMOUS-2026-07-26.md`. `supervisor/JOURNAL.md` — **last two CHECKPOINTs only**, never the
whole file (3000+ lines; reading it whole costs your context for no gain).
