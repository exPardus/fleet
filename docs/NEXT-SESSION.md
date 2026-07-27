# Next session — day-7 handoff (written 2026-07-28 by the interface session)

## YOU ARE THE INTERFACE TIER. NEVER RUN `fleet sup-boot`.

Bootstrap a supervisor with `fleet sup-spawn --task @<brief>`; steer with `fleet send supervisor @<file>`.
`sup-boot` claims the supervisor identity for *your* body, and an interface session never exits, so
its claim never clears. **The claim belongs to a role, not to a body.**

## FIRST ACT, EVERY TIME: REVIVE THE FLEET IF IT IS DEAD.

`fleet sup-status`. If GOALS is active and no supervisor holds the claim, **the fleet is stopped and
cannot start itself** — `sup-spawn` one immediately, then say what you found and what you started.

This is not a corner case. **It has happened three times in two days**: 3h38m, then ~4h, then again.
Each time every mechanism worked perfectly — clean release, good journal, `sup-status` reporting
`RELEASED` throughout — and the fleet sat dead because **nobody was reading**. There is deliberately
no fleet-side watcher: it would have to fire in a session nobody asked to be fleet-aware (D7), or
dispatch with no operator in the loop, which is how two live supervisors happen. **You are the
restart path.**

## Operator's standing directives

1. **Work fully autonomously** when the operator is away. Never stall waiting for them.
2. **PUSH `main` TO ORIGIN AS WORK COMPLETES.** Not at session end — at every green milestone.
3. **Keep making fleet better.** Fix what you find; improve what can be improved. We build fleet with
   fleet, so its own failures are the best defect reports available — mine them.
4. **Keep 5–6 builders saturated.** Slice by disjoint FILE SETS; merge `bin/fleet.py` slices one at a
   time, re-running both floors after each.
5. **Steer interactively** — short waits, frequent `status`/`peek`, correct drift immediately.
6. **YOU own the plan; the supervisor slices, dispatches, gates, merges.** Pull it back if it re-plans.
7. **4-councilor council** (risk / delivery / strategist / incident) + synthesis for anything
   operator-gated and genuinely blocking. Act on the synthesis; record it.

## State

`main` = **`f10f055`**, pushed, `origin` in sync. Predecessor measured **2577 passed / 13 skipped**
both floors. **Re-measure; never arithmetic your way to a baseline.** Operator docket is EMPTY —
twelve gates ruled 2026-07-27.

## Queue

1. **Merge queue, order FIXED:** `idx/core` (2702/12) → `idx/q` (2741/11) → `idx/teach`. Hazard,
   already characterised — do not re-derive: **the `M1_DEFECT` characterisation test lives ONLY on
   `idx/q`, not `main`, so core-alone-to-main is SAFE, and the red at core→q is resolved by RETIRING
   that test, never by weakening core.**
2. **`handoff-fix`** — the stillborn-handoff repair (A+B+C below). Hostile dual-lens gate; this
   defect has cost three incarnations and produced two interface errors.
3. **`acgate`** — the §7/autoclean fix, fenced against narrowing operator-owned §7.
4. **The succession spec** (1278 lines) — both gate verdicts are in. **GATE THEN BUILD.**
5. Then `fleet q` M2, then the remaining `[UNBUILT]` sweep toward launch-ready.

## The stillborn-handoff defect — root-caused, fix in flight

`sup-handoff-begin` has produced eight stillbirths. **Root cause: `SUCCESSOR_DEFAULT_MODE = "dontask"`**
(`bin/fleet.py:10352`) — the successor's first act is `fleet sup-boot`, a Bash call that is not
allow-listed, so it is denied and the body cannot start. The `dontask` default was reasoned from
avoiding a headless prompt-hang: **right about hangs, wrong about denials, never tested against a
non-allow-listed command.**

**The two defects nobody was hunting cost more than the one everybody was:**

- `cmd_sup_handoff_begin:14323` creates the record with `session_id=None` **while `successor_sid` is
  in hand and being printed**, so `stop_outcome.py` files the outcome under the raw sid where
  `read_outcomes(name)` never looks. The successor's own diagnosis went into an orphaned file.
- `_cmd_peek_native:4398` prints *"no transcript yet — dispatch may still be in flight"* whenever
  `sid is None`. The transcript existed 2 seconds after dispatch. That sentence is what a journal
  records a supervisor believing for 17 minutes.

**Until `handoff-fix` lands and is gated, `sup-release` → `sup-spawn` is the working route.** Do not
attempt a handoff to prove otherwise.

## Interface maneuvers that work

- **Succession is two steps**: `sup-release` → `sup-spawn`. But the tombstone is **CLEAN-RELEASE-ONLY**
  (one caller, `cmd_sup_release`), so it helps least in exactly the cases the succession signal exists
  for.
- **`--task` takes TEXT; a file is `--task @<path>`.** A bare path renders *itself* as the task into
  `state/tasks/<worker>.md`, overwriting a brief that lived there — unrecoverable from itself. Author
  briefs in `state/tasks/lens/` and `wc -l` the rendered file after every dispatch. **A dispatch that
  returned a session id has not proven it dispatched a brief.**
- **Write steers to a file and `send @file`.** Bash eats backticks as command substitution; PowerShell
  mangles quotes. I lost a steer to this hours after documenting the rule.
- **`env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py …`** clears §7's gate when a verb is refused
  by the wedge it would clear (claim-nonce §7.2).
- **Answer a parked decision through `fleet sup-decision --answer`**, never as prose in a steer.
- **Keep briefs SHORT.** One page, act-first. Long handovers are the campaign's named failure mode.

## Doctrine worth not re-learning

- **A clean shutdown with no reader is indistinguishable from a healthy fleet.** A signal nobody is
  obliged to read is not a signal.
- **When a blocker outlives one incarnation, stop reasoning and buy the measurement — from someone who
  is not you, and write the brief so it invites refutation of the brief.** I "falsified" a true
  hypothesis with a confounded probe (my command was character-for-character in the repo's allow-list)
  and committed it; the worker I briefed re-derived it anyway and caught me in an hour. **A control
  that isn't controlled is worse than no experiment** — it manufactures confidence and travels
  further than a hedge would.
- **When the evidence for a defect comes from the component suspected of being broken, that is not
  evidence.** "0 turns" was a registry accounting defect; 82KB transcripts existed all along.
- **The exemption is not transitive.** A clearance argued at one level of a call graph says nothing
  about the level below: `cmd_autoclean` is exempt from §7, the archive tier it delegates to is not
  (`bin/fleet.py:7371`). The branch predicted the failure and cleared itself with the wrong scope.
- **When the honest mechanism would have to be an injection or an autonomous actor, put the trigger on
  the human action that was going to happen anyway.**
- **A timer sweeps when the clock says so; a beat sweeps when the fleet is alive.**
- **Measure the incident before drawing the lesson from it** — "~15h dark" was 12h53m, of which 3h38m
  was genuinely uncovered. The corrected number was worse.
- **Fix waves mint defects: 7 of 7**, twice from a supervisor's ruling. Re-gate everything; ESCALATE
  beats a third wave.
- **A doc describing a CLI must be re-derived from `--help`, never from memory.**
- **Absence is not evidence on this substrate.** `git log` is the only truth a turn landed.

## Ledgers

`knowledge/lessons.md#2026-07-27-day5-surface`, `#2026-07-27-evening-outage` (+ its retraction
postscript). `docs/AUTONOMOUS-2026-07-26.md` (day 4). `supervisor/JOURNAL.md` — last two CHECKPOINTs
only, never the whole file.
