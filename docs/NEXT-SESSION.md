# Next session — day-6 handoff (written 2026-07-27 evening by the interface session)

## YOU ARE THE INTERFACE TIER. NEVER RUN `fleet sup-boot`.

You bootstrap a supervisor with `fleet sup-spawn --task @<brief>` and steer it with
`fleet send supervisor @<file>`. A handoff once told the incoming session to `sup-boot`; it did, and
wedged the claim for hours. **The claim belongs to a role, not to a body.**

**If the fleet is stopped when you arrive, reviving it is YOUR job and nothing else's.** GOALS active
+ no live supervisor ⇒ `sup-spawn` one and say so out loud. This is step 5 of the skill's startup
ritual and it is the only restart path that exists, by operator ruling: a fleet-side watcher would
have to fire in a session nobody asked to be fleet-aware (D7) or dispatch with no operator in the
loop. On 2026-07-27 the absence of this cost **3h38m of machine-up time** across two windows.

## Operator's standing directives

1. **Work fully autonomously** when the operator is away. Never stall waiting for them.
2. **4-councilor council rule** for anything operator-gated and genuinely blocking: four subagents of
   differing personalities (risk auditor / delivery pragmatist / strategist / incident responder) +
   synthesis; act on the synthesis; record it in the day's ledger.
3. **PUSH `main` TO ORIGIN AS WORK COMPLETES** — explicit standing order, 2026-07-27. Not at the end
   of a session; at every green milestone. 29 commits once sat local-only through a power cut.
4. **Keep 5–6 builders saturated.** Operator wants more of fleet done, faster. Slice by disjoint FILE
   SETS. Merge `bin/fleet.py` slices one at a time, re-running both floors after each.
5. **Steer interactively — short waits, frequent `status`/`peek`, correct drift immediately.** Do not
   fire-and-forget for an hour.
6. **YOU choose targets and own the plan; the supervisor slices, dispatches, gates and merges.** If it
   starts re-planning the queue, pull it back.

## State (verify, do not inherit — that is the point of this line)

`main` = **`c318224`** at the time of writing, pushed. Last figure measured directly by the interface:
2563/11 both floors at `2dec694`; the supervisor measured 2600/11 at `d543691`. **Re-measure.**

## What shipped 2026-07-27 (a heavy day — do not re-litigate any of it)

identity merge + the corrupt-glob gate and its CRITICAL fix wave; `views-doctrine` (D4 measured,
split, pinned); `respawn-ceiling`; `doctrine-citations`; `unbuilt-sweep` (18 stale `[UNBUILT]` tags
retired on grep receipts); b6 retired; `fix/sup-release-tombstone`; the §11.3 ratified edit; the
terminal-surface command-tier statusline. **All twelve operator gates ruled and the docket is empty.**

## Queue

1. **The idx stack — the critical path.** Merge order is FIXED: `idx-fix` first, then `idx/q`, then
   `idx/teach`. Both q-branches were cut from an escalated base, so their own green tallies are
   meaningless for merge purposes. `idx/q`'s gate returned ESCALATE with F1 CONFIRMED CRITICAL.
2. **Graceful succession** (operator-ordered). Ratified shape: machine-readable succession-needed fact
   **with its cause** (200k ceiling AND usage-limit park), rendered as an **outage** on
   statusline/`sup-status`/`doctor`, plus one verb for the maneuver. **Not a hook. Not auto-spawn.**
   Both refused on the record. Note the target shrank when `sup-release` began tombstoning its own
   record — verify how much.
3. **Retire the autoclean timer.** `fleet autoclean` moves onto the supervisor's beat and the
   interface ritual; the scheduled-task install surface goes. **Ordering: uninstall the live task with
   `--autoclean-remove` FIRST, while that flag still exists, then delete install+remove together.**
   Doctor's check is replaced, not deleted: *"when did autoclean last run"*.
4. `fleet q` M2 once M1 lands. Then the remaining `[UNBUILT]` sweep toward launch-ready.

## Interface maneuvers that actually work

- **Succession is now TWO steps**: `sup-release` → `sup-spawn`. `sup-release` tombstones the releasing
  body's own record, so the released-claim refusal no longer arms and nobody has to stop the retired
  body for succession to work. (Stop it anyway to reclaim the session.)
- **`sup-handoff-begin` was 10-for-10 stillborn under its old `dontask` default** and ate context from
  three incarnations. Three supervisors in a row correctly released at the ceiling instead. The cause
  was found and fixed 2026-07-27: `dontAsk` does not prompt, it DENIES, and the successor's first act
  is `fleet sup-boot` through Bash. Measured over `state/events.jsonl`: 10/10 under `dontask`
  stillborn, 7/7 under `bypass` booted and completed. **No live drill has run under the fixed
  default**, so `sup-spawn` remains the route to use until someone drives one green.
- **`--task` takes TEXT; a file is `--task @<path>`.** A bare path is rendered *as the task* into
  `state/tasks/<worker>.md`, overwriting a brief that lived there with the string naming it —
  unrecoverable from itself. Author briefs in `state/tasks/lens/` and `wc -l` the rendered task after
  every dispatch. **A dispatch that returned a session id has not proven it dispatched a brief.**
- **Write steers to a file and `send @file`.** Bash eats backticks as command substitution and
  PowerShell mangles quotes; I lost a steer to this today after documenting the rule the same day.
- **`env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py …`** clears §7's gate when a verb is refused
  by the wedge it would clear (claim-nonce §7.2, load-bearing infrastructure).
- **Answer a parked decision through `fleet sup-decision --answer`**, never as prose in a steer —
  otherwise routing state and truth diverge and only `sup-status` shows it.
- **Keep briefs SHORT.** Five supervisors each burned a full context on long handovers and merged
  nothing; the one given a one-page "act first, read second" brief merged the blocker on turn 1.

## Known live defects, none blocking

- The daemon leaks the FIRST dispatch's `FLEET_WORKER` into every later session. Supervisor-shaped is
  benign; **worker-shaped is malignant** — that body takes the claim and can never beat, checkpoint or
  release it. Every body checks its own stamp at boot.
- `fleet doctor` may carry one FAIL from a historical continuity refusal inside its 24h window; it
  ages out. **A permanently-red doctor is a disabled doctor** — clear resolved flags.
- `fleet init --autoclean-remove` hits the §7 claim gate, so a *worker* cannot run it; the claim
  holder or a no-sid shell must.

## Doctrine worth not re-learning

- **A clean shutdown with no reader is indistinguishable from a healthy fleet.** Every mechanism can
  work and the fleet still sits dead. A signal nobody is obliged to read is not a signal.
- **Measure the incident before drawing the lesson from it** — "~15h dark" was really 12h53m, of which
  9h14m was a power cut and **3h38m** was genuinely uncovered. The corrected number was worse.
- **When the honest mechanism would have to be an injection or an autonomous actor, put the trigger on
  the human action that was going to happen anyway.**
- **A timer sweeps when the clock says so; a beat sweeps when the fleet is alive.** Retiring a timer
  can delete a class of problem that configuring it only patches.
- **Fix waves mint defects: 7 of 7 this campaign**, twice from a *supervisor's ruling*. Always re-gate;
  ESCALATE beats a third wave.
- **A doc describing a CLI must be re-derived from `--help`, never from memory.** Six drifts found that
  way in one pass, including four shipped verbs missing from the skill.
- **Run `fleet sup-context` at wave boundaries, never estimate by feel** — one body guessed 60k and
  measured 198,767.
- **Absence is not evidence on this substrate.** Records are deletable, archivable, born with
  `session_id: None`. Any predicate that permits on a missing record fails open.
- `git log` is the only truth a turn landed. Restore proof is `git status --porcelain` EMPTY.

## Ledgers

`docs/AUTONOMOUS-2026-07-26.md` (day 4). `knowledge/lessons.md#2026-07-27-day5-surface` and
`#2026-07-27-evening-outage` (day 5–6). `supervisor/JOURNAL.md` — read the last two CHECKPOINTs,
never the whole file.
