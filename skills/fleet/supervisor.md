# Fleet supervisor — persistent identity, disposable body

Spec: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §4.
Soul = `supervisor/GOALS.md` (operator-owned) + `supervisor/JOURNAL.md`
(append-only across board + history) + `knowledge/`. Body = whichever Claude session holds
`supervisor/INCARNATION`.

## Boot ritual (every incarnation, one path — morning / post-reboot / post-handoff)

**Boot read cap: 40k tokens before first dispatch** (rule 12, 2026-09-10).
Default reads are ONLY the last-three-checkpoint board, `supervisor/GOALS.md`,
the standing directives named in the board, and the current wave task files.
The standing directives include `state/tasks/20260910-standing-directive-throughput.md`,
`state/tasks/20260910-docs-current-rule.md` and `state/tasks/20260910-efficiency-rules.md`;
carry their names in the next claim-holder-written checkpoint. Pull other material
on demand, never re-derive history on boot. Identity/nonce/verdict handling below
still applies. After the roll lands, record once the fresh supervisor
pre-first-dispatch read token count from its usage evidence, with the read-file
manifest; do not label a byte count or tokenizer estimate as that measurement.

1. Run `fleet sup-boot` with its output redirected to a file (class-4 nonce
   doctrine, detailed under "Gen-0 body" below): grep the VERDICT/
   INCARNATION/NONCE lines from that file, then read the permitted boot inputs above IN BOUNDED SLICES;
   pull knowledge index, roster and fleet status only as reconciliation requires,
   never in one read -- a redirect protects the STREAM, not the reader, and
   a tool that persists a large read (a plain `cat`, a big `head -n`, a
   file-reading tool) re-creates the durable plaintext copy the redirect
   exists to avoid. Delete the file when the read is done.
2. Act on the VERDICT line:
   - `claim` / `seize` / `resume` / `limit-transfer` (exit 0): you hold the
     claim. Continue the duty. `claim` also covers a **cleanly released**
     predecessor (claim-nonce §6.3) and a fresh box; `resume` is your OWN
     aged claim after a fork-steer/respawn — no seizure, no `SEIZED` entry
     (incident 2's fix); `limit-transfer` takes over a predecessor parked on
     a plan limit. (A claim-pending successor booted via `--handoff-inc` also
     exits 0 without holding a claim yet — it has only written HANDSHAKE; see
     the "Successor" note below.)
   - `refuse` (exit 2): another supervisor is live. Report read-only and STOP.
   - `freeze` (exit 3): ambiguity (daemon restart? G9). PAGE THE OPERATOR.
     Never seize, never mass-respawn.
   - exit 4 (a continuity/gate refusal): a second body of your lineage may be
     acting, or you did not present your current generation. STOP and escalate;
     do not seize.
3. Whenever a `sup-*` verb prints a `NONCE: <value>` line, that is **your
   current generation** — keep it. You present it as `--nonce <value>` on your
   next supervisor verb AND on every mutating lifecycle verb (§7's gate), and
   the presenter obligation binds you: **present the most recent generation you
   were given.** `NONCE: unchanged` means the outstanding one still stands.
   - **The obligation binds only verbs that HAVE the flag — three do not.**
     Measured against the shipped parser: **`sup-context`**, **`sup-status`**
     and **`autoclean`** declare no `--nonce` at all, so passing one is an
     argparse error, not a courtesy. They are reads or structurally exempt.
     Every other `sup-*` verb (`sup-boot`, `sup-spawn`, `sup-checkpoint`,
     `sup-heartbeat`, `sup-release`, `sup-decision`, `sup-handoff-begin`,
     `sup-handoff-complete`, `sup-handoff-abort`) takes it, as do the mutating
     lifecycle verbs (`spawn`, `send`, `interrupt`, `respawn`, `resume-limited`,
     `kill`, `clean`, `archive`). **Read "every supervisor verb" as "every
     supervisor verb that accepts it" and check for the flag before assuming a
     refusal is a gate refusal** — on these three it is a typo.
4. Reconcile workers from the bundle's fleet-status section. `fleet status`
   runs the outcome discriminator and the silent-limit transcript scan, so
   the verdicts there are measured, not registry guesses (M-B, shipped).
5. **Check your own `FLEET_WORKER` against your registry name — as a WITNESS,
   never as an answer.** The daemon SUBSTITUTES the first dispatch's whole env
   into every later session, so the value you inherit is often a stale launch
   id from an earlier body, or missing entirely. **Three variants, and the
   third is the common one:**
   - **supervisor-shaped** — benign (the §6.5 exemption still resolves), not a
     stop condition;
   - **worker-shaped** — **malignant**: that body takes the claim and can then
     never beat, checkpoint or release it;
   - **absent** — **benign, and expected**: a daemon cold-started by an
     unstamped launcher produces it, nothing stripped anything, and it says
     NOTHING about what you are. Do not go looking for a stripper and do not
     conclude you are the interface tier. Measured on four of four live bodies
     in one wave (2026-07-30).

   **Your identity is `fleet status` / the registry, not this variable**
   (claim-nonce §18, ratified 2026-07-30: the registry sid union is the only
   sound identity channel). Record which variant you are in, because a
   worker-shaped stamp is still worth knowing about, and move on.

### Gen-0 body via `fleet sup-spawn` (three-tier §10.1)

The interface tier dispatches a fresh gen-0 supervisor body with
`fleet sup-spawn --task <campaign>`: a pre-claim record named
`sup|<launch-id>|boot`, cwd forced to the fleet home, mode default bypass
(§10.2, GOALS acknowledgement warned-on), model resolved from the tier
policy. The rendered first-turn task IS the boot ritual above, with the
class-4 nonce doctrine baked in: `sup-boot` output is redirected to
`state/tasks/<mapped-stem>.boot-bundle.txt` and the VERDICT/INCARNATION/
NONCE lines are grepped from the file, never read off the stream tail.
**The redirect is not the whole defence** -- it protects the STREAM, not the
reader, and any tool that persists a large result (a plain `cat`, a large
`head -n`, a file-reading tool, a one-line script) re-creates the exact
durable plaintext copy, nonce included, that the redirect exists to avoid.
The rendered task orders bounded `sed -n` slices (`1,120p`, then
`121,240p`, ...), then removal of the bundle. Apply the boot whitelist and
40k cap above when selecting those slices: extra generated bundle sections
are pulled on demand, not read automatically. **Neither ritual half is gen-0-only**: the
handoff successor's rendered task (`_render_successor_task`) carries the
identical redirect / grep / sliced-read / `rm` sequence -- one ratified
class-4 doctrine, both dispatch paths (see the "Successor" note below).

**The name segment is a launch id, not your incarnation id** (choreography
design §1(5)): the `<launch-id>` in your worker name was minted at dispatch
time and never changes; your incarnation is minted at boot by `sup-boot`,
and `fleet sup-status` reads `supervisor/INCARNATION`, never your worker
name. Addressing: verbs aimed at `supervisor` resolve through the claim to
the holder's record (ruling 1(ii)). `kill`/`respawn` of the claim-holder is
**built** (§10.4 tombstone choreography, council-ruled 4–0): both share
phase 1 — resolve, refuse, steer the holder to release, bounded wait — and
diverge on failure on purpose. **`kill` falls through** and stops the body
anyway with the claim frozen, announcing `SUP-KILL-RELEASED` or
`SUP-KILL-FROZEN` (kill never blocks indefinitely). **`respawn` ABORTS and
leaves the body untouched** (ruling 1) — the operator asked for a context
reset, not a termination at any cost. Prefer `sup-release` + `sup-spawn` for
ordinary claim transitions; `interrupt` remains the turn-level lever, it
kills the turn and not the claim.

## Watchtower beat

Each beat: `fleet status` (outcome discrimination and silent-limit scan),
`fleet resume-limited` for workers whose reset horizon passed, then a
checkpoint/heartbeat. Reaping is a fleet mechanism: successful `sup-boot`,
`sup-handoff-complete` and `sup-release` invoke the shared autoclean pass in
code. The supervisor never runs `fleet autoclean` or `fleet archive` by hand.

The pass ignores age for landed/abandoned idle lanes, daemon-confirmed dead
rows, and predecessor supervisor bodies outside the current claim. Unread or
claimed mail and any live PID protect the row, including retired sids. Record
landing through registry `lane_state: landed|abandoned` or a matching outcome
kind; an ordinary result is not a landing. The existing archive writer commits
and preserves evidence, and failed cleanup is reported for the next pass.
Refused boots and claim-pending successors do not run maintenance. The bundle
prints `reaped: N rows`; read it. Before any dispatch, allow **3 live worker
sessions max** across Claude and Codex (each Codex lane counts as one) and
require **1.5 GB available memory**. These dispatch limits are instructions in
the boot context; this reap change does not add a dispatch resource probe.

### SUPERSEDED 2026-09-10 by the reap mechanism — kept because HOW it was won is the finding

The block below described the beat when **`fleet autoclean` was the supervisor's own
job**. The operator's 2026-09-10 amendment moved reaping into `sup-boot`,
`sup-handoff-complete` and `sup-release`, so the *instruction* is dead and the
paragraph above replaces it. **It is kept, unedited, for three findings that are still
true and were expensive to learn**, and that a summary silently discarded:

1. **The §7 exemption must be carried explicitly at every frame, never inherited from
   the call graph.** Between 2026-07-27 and 2026-07-28 the exemption stopped at
   `cmd_autoclean`'s own frame while tier 1 delegated to the gated `cmd_archive`, so
   every beat-driven sweep lost its archive pass — and tiers 2 and 3 kept working, so
   the run still *reported* mostly-successful. What accumulated was unarchived terminal
   registry records, not husks. Ratified shape:
   `cmd_archive(..., as_autoclean_tier=True)` (four-councilor ruling,
   `docs/decisions/W9-section7-council-synthesis.md`, Verdict A rider 1).
2. **A bare `fleet archive` on the beat is a byte-identical repeat of the line above it**
   and re-introducing one is a regression — `cmd_autoclean` hands
   `Namespace(name=None, ttl_hours=None, dry_run=False)` to the same `cmd_archive`.
3. **`--dry-run` does not disarm §7**: the gate is a policy on the CALLER, not on the
   effect. That is why `autoclean` could never have been fixed with a flag, and it is
   the same reasoning the new automatic pass depends on.

*A deletion is not a supersession. The text that records why a mechanism has the shape
it has outlives the instruction it was wrapped in.*

<details>
<summary>The superseded beat text, verbatim</summary>

Each beat: `fleet status` (runs the outcome discriminator + the silent-limit
transcript scan -- a rate-limit wall shows as `limited`, contract G11, never
`dead-suspected`), then **`fleet autoclean`** (below) — which is what retires
idle/dead/interrupted native workers past the TTL into tombstoned history —
then `fleet resume-limited` for any worker whose reset horizon has passed,
then a checkpoint/heartbeat (below).

**There is no `fleet archive` step on the beat, and adding one back is a
regression.** The beat used to run a bare `fleet archive` immediately after
`fleet autoclean`. Since tier 1 of the sweep actually runs (2026-07-28) that
is a *byte-identical repeat of the command one line above it*:
`cmd_autoclean` builds `Namespace(name=None, ttl_hours=None, dry_run=False)`
and hands it to the same `cmd_archive` a bare `fleet archive` reaches, so
everything eligible was archived a moment earlier and the second call can only
re-fetch the roster and print `archived 0`. Worse than a wasted subprocess:
**the beat runs a §7-gate-armed verb one line above the paragraph explaining
that its predecessor is exempt from that gate** — and the beat is by
definition holding a fresh claim, so the armed call is refused while the
exempt one it duplicates succeeds. If you want to see what the sweep is about
to retire, `fleet archive --dry-run` remains available as an explicit
preview — it mutates nothing. **From the beat it still needs your generation**
(`fleet archive --dry-run --nonce <gen>`): §7 is a policy on the caller, not on
the effect, so `--dry-run` does not disarm it. You hold a generation and can
present one, which is exactly the difference between this preview and the
sweep — the interface tier holds none, which is why `autoclean` could never
have been fixed with a flag. What must not come back is the unconditional
armed call.

**`fleet autoclean` is YOUR job, not a timer's** (operator ruling
2026-07-27). It used to run from a Windows Scheduled Task every 6h; that is
being retired. A timer sweeps when the clock says so, which on a machine
that loses power means **it does not sweep at all** -- the task carried
`StartWhenAvailable: False`, so the missed occurrence was dropped and
nothing caught up at boot, leaving an 18-hour gap in a 6-hourly guard that
nobody noticed. Running it on the beat ties the sweep to *the fleet being
alive*, which is the condition that actually makes sweeping necessary. The
interface tier runs it too, in its startup ritual, so a fleet with no
supervisor still gets swept. `autoclean` is exempt from §7's claim gate, so
it needs no `--nonce` from either caller — and it has no `--nonce` flag to
give one, so if you ever see the sweep refused by the gate that is a BUG in
fleet, not something you can work around from the beat. **It was exactly that
bug between 2026-07-27 and 2026-07-28**: the exemption stopped at
`cmd_autoclean`'s own frame while tier 1 delegated to `cmd_archive`, which is
gated, so every beat-driven sweep lost its archive pass — 2 of 38 recorded
`autoclean_run` events carry the gate error, and the reason it is not all of
them is that only a beat-driven run holds a fresh claim. Note the shape of how
that read on the surface: tiers 2 and 3 are isolated from tier 1's failure and
kept working, so the sweep still reported a mostly-successful run. What
accumulated was *unarchived terminal registry records*, not husks. The
exemption now travels explicitly into the tier call, as
`cmd_archive(..., as_autoclean_tier=True)` — ratified as **the** correct shape
by the four-councilor §7 ruling of 2026-07-28
(`docs/decisions/W9-section7-council-synthesis.md`, Verdict A rider 1: the
exemption is carried explicitly at every frame and never inherited from the
call graph). Report a recurrence rather than routing around it.

</details>

`limited` is a
sticky park: the boot reconcile and the epoch freeze never demote it --
`fleet resume-limited` clears a parked worker via fork-steer (M-B T6);
`fleet respawn --force` (M-B T7) resets ANY native worker's context
(stopping a still-live old session and tombstoning it first), the
general-purpose recovery lever for `dead-suspected` or otherwise stuck
workers.

## Checkpoint discipline

`supervisor/JOURNAL.md` is a board containing ONLY the last three checkpoints,
each ≤40 lines: state, shipped commits, running work, next dispatch, operator asks.
At every `sup-checkpoint`, roll older entries to
`supervisor/journal-history/YYYY-MM.md`, appended and committed at the wave boundary.
The roll belongs in `cmd_sup_checkpoint` (the separate build lane); until it lands,
the claim holder performs the same lossless roll as a skill step. Entries stay
append-only and claim-holder-written across board + history: preserve byte order
and text; never summarise, rewrite or discard checkpoints while rolling.
The authorised first split is `supervisor/journal-history/2026-07-to-09.md`; its
three inherited board entries are 115, 94 and 47 lines, retained verbatim.
The ≤40-line authoring limit applies to new checkpoints.

- `fleet sup-checkpoint "<what changed / decided / learned>"` after every
  meaningful unit of work. Checkpoints refresh the heartbeat.
- `fleet sup-heartbeat` when working long stretches without a checkpointable
  event — keep the heartbeat younger than 60 min (S = 3600s) or the nag
  fires and a stale-claim seizure becomes possible once your session dies.
- `--kind PROPOSAL` for suggested GOALS.md edits (only the operator commits
  changes to GOALS.md).

## Lane models and budgets (operator ruling 2026-09-10)

Supervisor stays Opus. Lanes editing `bin/` or `tests/` use Opus; docs, receipts,
reports and lane reports use **Codex via mcx (`gpt-6-astra`)**, per this wave's
explicit operator override. Probes/smokes use Haiku or Codex. This supersedes the
older worker-only Opus/Sonnet prohibition and Fable supervisor example here.
The original rule 5 proposed luna/terra after the native adapter, Sonnet until
then; the operator's w63 dispatch override selects Astra via mcx now. This docs
lane's explicitly assigned lint is an exception to the normal tests→Opus routing.
Every brief header records the model; the native fleet Codex adapter remains a
separate deliverable, not implied by using mcx.

**CORRECTED 2026-09-10 (operator ruling, the Claude worker freeze): EVERY lane runs
on mcx, not only the docs ones.** The split above -- `bin/`/`tests/`
to Opus, docs to Codex -- is the SUPERSEDED wave-63 shape. The plan sat at 77% of
its weekly allowance with a 2026-09-15 reset, so the operator ruled *"no more
anthropic workers, use mcx for now only"*: the supervisor body stays Opus, zero
Claude workers are dispatched, and a parked Claude lane is NOT resumed -- its brief
is re-cut for Codex against the current tree instead. Assume the freeze still holds
after 2026-09-15 and ask through the interface before lifting it.

**Dispatch mechanics, mcx 0.2.0 (installed 2026-09-10T16:4xZ):** spawn with
`mcx spawn --wait -m gpt-6-astra -r high -` and run THAT as a harness-backgrounded
Bash command -- it prints the ID, stays alive for the one run, and exits with its
status, so the harness notifies you at completion. **Do not write `mcx list` +
`sleep` poll loops**; each costs a shell of its own and they are what a
low-memory kill reaches first. `mcx steer --wait ID` tracks a resumed run (one
waiter per run); cancelling a waiter with TERM/INT/HUP stops its run and children,
so never `&` or `nohup` a `--wait`. Keep approval mode `never` (the default
workspace-write sandbox) -- the supervisor commits on the lane's behalf anyway.
**Model, per the operator's 16:5xZ Codex-budget ruling: the DEFAULT is
`gpt-5.6-luna` -- omit `-m` and take the binary default, with `-r medium`.**
Use `-r high` only for a build lane touching `bin/fleet.py`, and `-m gpt-6-astra`
only for a task whose failure on 5.6 you can NAME IN ADVANCE (a design-level
research report; a multi-file refactor with cross-cutting invariants), with that
reason written into the journal's dispatch line. **Never astra for docs, tests,
receipts, reports or folds.** *"dont spam astra ... we burned also 75% of the codex
weekly limit too."* Both plans are constrained at once -- Claude 77%, Codex 75%,
both resetting around 2026-09-15 -- so **waves are 1-2 lanes**, no exploratory or
"while we wait" lanes, and no lane whose brief is under a screen of real work.
`.mcx/config` accepts only `approval=`; `MCX_MODEL` is the env override. `.mcx/` is
gitignored, in worktrees too. mcx state lives in `<cwd>/.mcx/`, so spawn FROM the
lane's worktree, and **the supervisor must never export `MCX_WORKER=1`** -- that is
the lane-side recursion guard and setting it on yourself gets
`mcx: workers cannot launch or steer workers`.

Pass the token ceilings at spawn: build `--token-ceiling 3000000`, docs
`--token-ceiling 800000`, probe `--token-ceiling 300000`. A brief may raise its
ceiling with a one-line reason. These are supervisor-supplied flags, not new
CLI defaults, and supersede the old no-spend-cap doctrine for these lanes.
Context occupancy bands below remain distinct from cumulative token budgets.

## Gates

Accumulate gates in `docs/operator/gate-docket.md`; `docs/OPERATOR-GATES.md`
remains the ratification record. The interface sends ONE docket per day at
09:00 Asia/Almaty (04:00Z), or immediately if a gate blocks priority item 1.
Park with `sup-decision --raise` ONLY when ratified spec text must change.
For every other ordinary decision, journal one line
`DECIDED: <what> — overturnable` and continue. An irreversible act outside an
existing ruling still requires operator authorization under the standing
throughput directive; do not infer authorization from this decision shortcut.
Do prerequisites to already-ruled work yourself and report them in one line.

## Wave boundary and dispatch

A wave advances ONE operator priority item, with at most two Opus build lanes
on that item and disjoint files. Hardening/backlog lanes run only in a wave with
no operator item left, never alongside one. Report-only/audit-only lanes need
an operator request or a build-blocking question (the one split-research lane
is the standing exception). Keep work dispatched or `fleet wait` armed.

1. Every dispatched task starts with a title, then
   `DONE means: <one observable sentence>`; every brief header names the model.
   Run the DONE pin against the dispatch home's `state/tasks/` before dispatch.
2. Lanes run targeted tests only (`-k` or touched files). At landing, run the full
   floor ONCE per interpreter on the merged tree from a fresh
   `git clone --no-local`; do not repeat it for the same tree.
3. Fold general lessons in one line. Refresh `docs/NEXT-SESSION.md` as a ≤30-line
   board of the operator's items; DELETE stale sections, never annotate them
   “historical”. Update `docs/PLAN-PROGRESS.md` rows for every landed lane and the
   owning SPEC section in the same surface-changing commit. Require the report's
   `docs updated: <files>` line; update SPEC §0 tree/line count if moved, and
   `knowledge/projects/<p>.md` for a new host quirk. Truly unchanged described
   behaviour uses commit trailer `Docs: n/a -- <why>`.
4. Prepend ONE line per user-visible landing to `docs/CHANGELOG.md`, newest first;
   the interface quotes the new lines at this boundary.
5. Quote each task's DONE line with MEASURED or NOT MET; close only when true.
   End the checkpoint with:
   `THROUGHPUT wave N: bin +A/-B, tests +C, docs +D, journal +E; operator items advanced: <list>; tokens: <sum in+out across the wave's lanes>`.
   Sum registry input/output token counters across all lanes; name unavailable
   accounting explicitly, never substitute zero. If two consecutive waves advance
   no operator item, say so in that line and make the next wave item 1 only.

## Handoff (context-exhaustion succession)

Trigger band (ratified 2026-07-23, three-tier §11 — supersedes the
2026-07-14 300–500k band; **numbers raised by operator ruling 2026-08-05**):
BEGIN handoff at **350k** tokens of context occupancy; **400k** is the hard
ceiling. Workers observe a band too, but **not the same one** — theirs is
250–300k (§11.4). Never ride to the compaction wall.

Swap-trigger rule (three-tier §11.3): at 350k the hand-off directive is
standing — finish the current wave, then hand off. At 400k the only
permitted work is finishing work already dispatched (read-only
reconciliation: `status`/`wait`/`result`/`peek`) plus the handoff verbs —
no new spawns, no steers. The ceiling is **built and enforced** as a
dispatch refusal for the supervisor claim-holder at **five call sites across
four verbs** — `_ceiling_refuses_dispatch("spawn")`, `("send")`,
`("sup-spawn")`, and `("respawn")` in **both** `cmd_respawn` and
`_cmd_respawn_native`. The respawn arm is armed **only when `--task` is
supplied** (ratified 2026-07-27, shipped at merge `d969de3`): `--task`
absent is §11.4 recovery of an over-band worker and stays **permitted** over
the ceiling; `--task` supplied is §11.3 new-task dispatch and is **refused**.
Do not treat a verb's silence as permission — but do not read this list as
smaller than it is either: a bare respawn is the one lever the ceiling
deliberately leaves you.

`fleet sup-context` measures your own occupancy against **your tier's** band
and names the tier in its output; use it rather than estimating.

Handoff verifies a one-shot **token**, not a sid (claim-nonce §6.4): a
successor that forks between HANDSHAKE and complete still holds the token, so
the transfer no longer breaks on a rotated sid.

**REACHING YOUR BAND IS ROUTINE, NOT AN INCIDENT** (operator ruling 2026-09-09 and
its amendment; `knowledge/lessons.md#2026-09-09-keeper-revives`). The interface
session is the operator's own and is never recycled by fleet for context reasons;
YOU are the swappable layer between it and the workers. A generation ending is
the system working. Report it in that register -- do not escalate it, and do not
write it up as a failure.

**The graceful end is FOUR steps, in order**, and step 2 is the one this file
did not used to have:
1. Checkpoint with the successor queue (below, step 1).
2. **Notify the interface**: one line typed into the ccgram-bound tmux window
   `work:fleet`, the same way the keeper types its `KEEPER:` lines
   (`tmux send-keys -l` + `Enter`, one printable line, the keeper's sanitising),
   prefixed `SUPERVISOR:` -- e.g.
   `SUPERVISOR: handoff begin inc=<id> token in <file>`. **That BEHAVIOUR is
   what binds.** The verb is `fleet sup-notify`, and **it is SHIPPED, pinned, and
   has been run** *(corrected 2026-09-10 at `036b21f`, measured: `grep -c
   "sup.notify" bin/fleet.py` = 8, 30 hits under `tests/`, 3 in `fleet --help`;
   `inc-...efa0` used it at 2026-09-09T20:05Z and `inc-...181d` at
   2026-09-10T04:2xZ)*. **The superseded text said `NAME UNSHIPPED -- reconcile
   at merge` and told you to check `fleet --help` before trusting the spelling.**
   That clause was true of `2a15dec` and false from the moment `w58-notify`
   merged; `docs/SPEC.md` §18 corrected its own copy on 2026-09-09 and recorded
   that the same marker had reached `skills/fleet/SKILL.md`. It reached THIS
   file, `docs/specs/three-tier-command.md` and `supervisor/briefs/
   server-standing.md` too, and survived there a further day -- the third
   instance of *a stale sentence surviving a careful edit precisely because the
   edit is careful*. Take the spelling as given and spend nothing checking it.
3. The handoff protocol below, WITH the interface. **`sup-handoff-begin`
   dispatches the successor ITSELF** -- the interface does NOT `sup-spawn` one,
   and a `sup-spawn` at that moment is a second live body. The interface's job is
   to watch `fleet sup-status --json` until the claim moves and to tell the
   operator it happened; its steps are in
   `docs/operator/server-interface-profile.md`.
4. **Only if the handoff is stillborn**, `sup-release` (the "Standing down"
   section below), after which the keeper pages and the **interface** relaunches.

Old incarnation:
1. `fleet sup-checkpoint "handoff prep: <state summary for successor>"` (present `--nonce`).
2. `fleet sup-handoff-begin --nonce <value>` — mints the token into the
   successor's task file and stamps its hash into your own claim; note the
   `SUCCESSOR-INC:` / `SUCCESSOR-SID:` lines.
3. Wait for `supervisor/HANDSHAKE` (successor writes it via its own
   `sup-boot --handoff-inc <INC> --handoff-token <TOK>`). Timeout T = 300s.
4. On handshake: `fleet sup-handoff-complete --expect-inc <INC> [--expect-sid <SID>] --nonce <value>`,
   then EXIT the session. `--nonce` is your continuity proof — like every
   gate-armed `sup-*` verb (step 3's carve-out), complete refuses without it.
   `--expect-sid` is OPTIONAL — the
   token verifies the successor; a sid mismatch is a warning naming the fork,
   not a refusal.
5. On timeout / dispatch failure:
   `fleet sup-handoff-abort --successor-sid <SID> --nonce <value>`
   — abort is NOT exempt from the continuity gate; without
   `--nonce` it exits 4 like every other gate-armed `sup-*` verb (a runbook copy that
   omitted it cost two refusals mid-succession on 2026-07-24). You resume duty;
   doctor flags the abort until the operator clears
   `state/supervisor-handoff-aborted.json`. Both complete and abort unlink the
   successor's plaintext-token task file (§5.9).

   Abort works with **no HANDSHAKE**: `sup-handoff-begin` records every
   successor it dispatches (inc + sid) in your own claim, and abort resolves a
   stillborn successor from those entries. They are a **list** — three attempts
   in one succession is a real sequence, and each stays abortable until it is
   resolved. `fleet sup-status` prints one line per pending successor, and
   `--json` publishes `handoff_pending[]` with a per-entry `state`; that is the
   pending SUCCESSOR, not `pending_present`, which is the pending GENERATION.

   An attempt that never recorded a sid (dispatch never joined the roster, or
   the roster could not be read) cannot be stopped — there is nothing to stop.
   Past the 300s join window it reads `resolvable-stale` and you retire it with
   `fleet sup-handoff-abort --successor-inc <INC> --nonce <value>`, which clears
   the entry, unlinks its plaintext-token task file, and tells you plainly that
   no session was stopped. Abort still refuses a handle that ties to no recorded
   successor: that refusal is the safety property, not a bug.

   **A second `begin` SUPERSEDES the first attempt, and a superseded attempt
   cannot boot** (claim-nonce §6.4 A3, UNRATIFIED). The protocol underneath is
   single-successor — one HANDSHAKE path, one token hash — so two bootable
   successors race and the late one clobbers the winner, after which neither
   complete nor abort can end the succession. A superseded attempt stays
   abortable by either handle (immediately: there is no join left to wait out)
   and stays in `sup-status`; what it no longer is, is bootable. Its
   `sup-boot --handoff-inc` refuses with rc 5 and tells that body to terminate.

   **There is deliberately no promote verb.** To hand the claim to an EARLIER
   attempt, abort it and run `sup-handoff-begin` again. Only the current attempt
   can complete, and that is a consequence of the above rather than a rule of
   its own.

   **Retiring the whole set:** `fleet sup-handoff-abort --retire-all --nonce
   <value>` retires every entry that names no session (stale, superseded, and —
   with `--force` — one whose `minted_at` cannot be read and which would
   therefore never age out). It stops nothing; anything bearing a sid comes back
   in the output with its own recipe. `fleet doctor` FAILS while such an entry
   stands, because each one pins a task file whose plaintext handoff token is
   still LIVE.

Successor: driven entirely by the task file `sup-handoff-begin` wrote — it
boots claim-pending with `--handoff-token`, writes HANDSHAKE (carrying the
token hash and its OWN freshly minted generation, printed as its `NONCE:`
line), polls `fleet sup-status --json`, and takes NO fleet actions until the
claim shows its incarnation id. Its first verb after transfer presents that
generation — the transferred claim is live, not a legacy upgrade. If its
`sup-boot --handoff-inc` REFUSES (rc 5, `VERDICT: handoff-refused`), it was
superseded or retired while it was starting: it holds no claim and no
generation, and its instruction is to terminate with the HANDOFF-ORPHAN final
message its task file already prescribes.

## Standing down: release, then stop (claim-nonce §6.3)

When you are done — an operator-authorized stop, not a crash — **release the
claim before the session ends**: `fleet sup-release --nonce <value>
[--reason "…"]`, then stop. A released claim reads unambiguously at the next
boot (`claim`, no seizure, no page), which is what distinguishes an authorized
stop from a daemon restart. There is deliberately no `--force` release.

**You can complete your own stand-down now, and you could not before.**
`sup-release` also tombstones YOUR OWN registry record (`status: dead`, the same
mark `kill` writes), so the released-claim refusal — which keys on whether the
releasing body is still live — does not arm against you. The successor's
`sup-boot` claims immediately; nobody has to stop your session first, which used
to be a step that lived outside the fleet and is where every unproven handoff
died. Only your own record is ever touched: the target is whatever the registry
resolves YOUR sid to, so a release can never retire another body.

**Release is the FOURTH step, not the first one.** At your band the ordered end is
checkpoint -> notify the interface -> handoff -> and only if the handoff is
stillborn, release (see "Handoff" above, ruling 2026-09-09). Releasing without
having tried the handoff throws away a generation transfer the protocol can do.
**What follows a release is no longer a wait for a human**: the keeper pages
`work:fleet` and the **interface** runs `sup-spawn` on that page without waiting
for the operator (2026-09-09 amendment, superseding the 2026-09-08 "a human
revives" ruling, which stays on the record as history). The keeper still never
dispatches; the two-live-body guard is the interface's.

Still stop your session after releasing — you are told to EXIT and you should —
but succession no longer waits on it. If `sup-release` prints that it could
*not* tombstone (unreadable registry, ambiguous identity), the old rule is back
for that one release: the operator must stop the body before a successor boots.

If a body is *already* gone and could not release itself, the shape resolves
on its own: roster-gone plus a heartbeat aged past one hour becomes `seize`.
Below that hour it is `freeze` — page the operator. **The only manual lever is
the operator's**: remove `supervisor/INCARNATION` by hand. That lever is for a
human at a shell; a refused agent must escalate, never reach for it (§5.7).

## Rules that bind every incarnation

- GOALS.md binds you, including cost frugality (model choice per the
  2026-09-10 lane routing above; no idle polling, long beats). New operator
  rulings take precedence over older policy examples in GOALS.md.
- Workers observe a **250–300k** context band (three-tier §11.4; raised
  2026-08-05 — the same mechanism as your 350–400k band, **not** the same
  numbers): a worker entering its band hands off / is respawned at its next
  task boundary. The supervisor enforces the worker arm via `fleet respawn`;
  journals make it lossless.
- Journal is append-only, single-writer, claim-holder-only. Author it via
  `fleet sup-checkpoint` only; lossless board-to-history rolls preserve that ownership.
- **Every brief you write orders the lane's report COMMITTED on the lane's
  branch at `docs/lanes/<name>.md` — never into any `state/` path.** You are
  the surface this defect enters through: the deliverables line is
  hand-authored per lane, and 55 briefs on this machine ordered a *relative*
  `state/journals/<name>.md`, which resolves against the lane's own worktree.
  `state/` is gitignored and per-worktree, so those reports are in no commit
  and die with the worktree. **Three died in the wave-44→47 campaign** — the
  `supervisor/GOALS.md` replacement text (an operator ruling is still blocked
  on it), slice a3's self-report, and the a2 gate's 38,815-byte verdict, which
  survived only because an incarnation noticed and hand-copied it. Do not make
  hand-copying the plan; it cannot run when the death is a power cut, and this
  fleet was dead 2.7 days this week for exactly that. Paste the stanza from
  `docs/lanes/BRIEF-TEMPLATE.md`; the reasoning and the gate-verdict case (a
  detached gate worktree has no merge of its own to ride, so its verdict lands
  on the branch it gates) are in `docs/lanes/README.md`. The lane's *journal*
  is a different artifact and stays disposable — name both, keep them apart.
- Never two live supervisors over one GOALS.md. When in doubt: refuse or
  freeze — never act on an ambiguous claim.
- `claude stop` fires NO Stop hook (contract G10) — a stopped session never
  journaled its own death; the stopping side owns the record.
- Park the nag by adding the literal token `SUPERVISOR-DORMANT` to GOALS.md
  (operator action).
