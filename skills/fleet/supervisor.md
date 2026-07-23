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
4. Reconcile workers from the bundle's fleet-status section (M-A interim:
   registry verdicts; the outcome discriminator arrives in M-B).

## Watchtower beat

Each beat: `fleet status` (runs the outcome discriminator + the silent-limit
transcript scan -- a rate-limit wall shows as `limited`, contract G11, never
`dead-suspected`), then `fleet archive` (cautious operators: `fleet archive
--dry-run` first to preview) to retire idle/dead/interrupted native workers
past the TTL into tombstoned history, then `fleet resume-limited` for any
worker whose reset horizon has passed, then a checkpoint/heartbeat (below).
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
2026-07-14 300–500k band): BEGIN handoff at **150k** tokens of context
occupancy; **200k** is the hard ceiling. The band binds supervisors AND
workers (§11.4). Never ride to the compaction wall.

Swap-trigger rule (three-tier §11.3): at 150k the hand-off directive is
standing — finish the current wave, then hand off. At 200k the only
permitted work is finishing work already dispatched (read-only
reconciliation: `status`/`wait`/`result`/`peek`) plus the handoff verbs —
no new spawns, no steers. The 200k ceiling is specified as a
fleet-enforced dispatch refusal for the supervisor claim-holder
`[UNBUILT — three-tier build slice]`; until built, treat it as binding
doctrine.

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
   `sup-*` verb, complete refuses without it. `--expect-sid` is OPTIONAL — the
   token verifies the successor; a sid mismatch is a warning naming the fork,
   not a refusal.
5. On timeout / dispatch failure: `fleet sup-handoff-abort --successor-sid <SID>`
   — you resume duty; doctor flags the abort until the operator clears
   `state/supervisor-handoff-aborted.json`. Both complete and abort unlink the
   successor's plaintext-token task file (§5.9).

Successor: driven entirely by the task file `sup-handoff-begin` wrote — it
boots claim-pending with `--handoff-token`, writes HANDSHAKE (carrying the
token hash and its OWN freshly minted generation, printed as its `NONCE:`
line), polls `fleet sup-status --json`, and takes NO fleet actions until the
claim shows its incarnation id. Its first verb after transfer presents that
generation — the transferred claim is live, not a legacy upgrade.

## Standing down: release, then stop (claim-nonce §6.3)

When you are done — an operator-authorized stop, not a crash — **release the
claim before the session ends**: `fleet sup-release --nonce <value>
[--reason "…"]`, then stop. A released claim reads unambiguously at the next
boot (`claim`, no seizure, no page), which is what distinguishes an authorized
stop from a daemon restart. There is deliberately no `--force` release.

If a body is *already* gone and could not release itself, the shape resolves
on its own: roster-gone plus a heartbeat aged past one hour becomes `seize`.
Below that hour it is `freeze` — page the operator. **The only manual lever is
the operator's**: remove `supervisor/INCARNATION` by hand. That lever is for a
human at a shell; a refused agent must escalate, never reach for it (§5.7).

## Rules that bind every incarnation

- GOALS.md binds you, including cost frugality (model choice per the
  ratified tier table — three-tier §3, superseding the cheapest-capable
  doctrine; no idle polling, long beats).
- Workers observe the same 150–200k context band (three-tier §11.4): a
  worker entering the band hands off / is respawned at its next task
  boundary. The supervisor enforces the worker arm via `fleet respawn`;
  journals make it lossless.
- Journal is append-only, single-writer, claim-holder-only. Write it via
  `fleet sup-checkpoint` only.
- Never two live supervisors over one GOALS.md. When in doubt: refuse or
  freeze — never act on an ambiguous claim.
- `claude stop` fires NO Stop hook (contract G10) — a stopped session never
  journaled its own death; the stopping side owns the record.
- Park the nag by adding the literal token `SUPERVISOR-DORMANT` to GOALS.md
  (operator action).
