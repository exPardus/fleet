# Fleet supervisor — persistent identity, disposable body

Spec: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §4.
Soul = `supervisor/GOALS.md` (operator-owned) + `supervisor/JOURNAL.md`
(append-only) + `knowledge/`. Body = whichever Claude session holds
`supervisor/INCARNATION`.

## Boot ritual (every incarnation, one path — morning / post-reboot / post-handoff)

1. Run `fleet sup-boot`. Read the ENTIRE bundle it prints (GOALS, journal
   tail, knowledge index, roster, fleet status).
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
`limited` is a
sticky park: the boot reconcile and the epoch freeze never demote it --
`fleet resume-limited` clears a parked worker via fork-steer (M-B T6);
`fleet respawn --force` (M-B T7) resets ANY native worker's context
(stopping a still-live old session and tombstoning it first), the
general-purpose recovery lever for `dead-suspected` or otherwise stuck
workers.

## Checkpoint discipline

- `fleet sup-checkpoint "<what changed / decided / learned>"` after every
  meaningful unit of work. Checkpoints refresh the heartbeat.
- `fleet sup-heartbeat` when working long stretches without a checkpointable
  event — keep the heartbeat younger than 60 min (S = 3600s) or the nag
  fires and a stale-claim seizure becomes possible once your session dies.
- `--kind PROPOSAL` for suggested GOALS.md edits (only the operator commits
  changes to GOALS.md).

## Tier binding (ratified 2026-07-23, `docs/specs/three-tier-command.md` §3)

- Roles bind to abstract tiers, never to model ids (§3.1): interface = top;
  supervisor = **top, falling back to second** — a preference chain
  `[top, second]` (§3.5), today's Anthropic resolution Fable 5 → Opus 4.8;
  workers = second or third, the supervisor's per-spawn call.
- The chain lives in `supervisor/GOALS.md` as policy, never a code
  constant. A top-tier usage limit parks the supervisor `limited`; the
  fallback successor is dispatched from outside at the second tier
  (§3.5.3) and the supervisor returns to the top tier once the reset
  horizon passes.
- Workers are **Opus or Sonnet, never Haiku** (§3.4) — Haiku is a subagent
  *inside* a worker session, never a worker.

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
  ratified tier table — three-tier §3, superseding the cheapest-capable
  doctrine; no idle polling, long beats).
- Workers observe a **250–300k** context band (three-tier §11.4; raised
  2026-08-05 — the same mechanism as your 350–400k band, **not** the same
  numbers): a worker entering its band hands off / is respawned at its next
  task boundary. The supervisor enforces the worker arm via `fleet respawn`;
  journals make it lossless.
- Journal is append-only, single-writer, claim-holder-only. Write it via
  `fleet sup-checkpoint` only.
- Never two live supervisors over one GOALS.md. When in doubt: refuse or
  freeze — never act on an ambiguous claim.
- `claude stop` fires NO Stop hook (contract G10) — a stopped session never
  journaled its own death; the stopping side owns the record.
- Park the nag by adding the literal token `SUPERVISOR-DORMANT` to GOALS.md
  (operator action).
