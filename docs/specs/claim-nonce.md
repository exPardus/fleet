# Per-body supervisor claim nonce

Status: PROPOSAL — awaiting dual-lens review + operator ratification.
Author: fleet worker `flt-nonce-spec`, 2026-07-20. The author may not promote this spec.
Amended 2026-07-20: the first dual-lens pass returned AMEND-THEN-SOUND from both
lenses (break: 2 CRIT / 2 HIGH / 3 MED / 3 LOW; spec: 2 HIGH / 2 MED / 4 LOW), with
the same two headline holes (grace-print treadmill; absent-nonce reclaim laundering).
This revision folds in the manager-adjudicated amendment list. Status unchanged.
Scope: `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md` items 1–3 ONLY (per-body
nonce; what the claim gates; `spawned_by` continuity). Items 4–10 (beat verb, scheduler
bridge, operator-gate routing, `sup-spawn`, …) are OUT of scope — the three-tier
re-draft builds on this spec later, per the adjudication's binding sequencing. Code
anchors below are `bin/fleet.py` at 771e4ee; symbol names are the stable reference.

## 1. Why

The claim is keyed on `session_id` and enforced by exact sid equality
(`_require_claim_holder`, ~:7301). Fleet itself rotates sids: every fork-steer
(`_restamp_after_steer`, ~:6432), every `--fork-session` rehost, every respawn. Anything
that rotates the sid breaks or splits the claim. Three dated live incidents:

- **2026-07-17 (M-C zombie).** A host restart re-hosted the manager conversation with
  `--fork-session`: two live bodies, identical context, identical claim, identical sid,
  independently dispatching (7 phantom sends). The claim cannot see this — both bodies
  pass the sid check (`lessons.md#2026-07-17-mc`).
- **2026-07-17/18 (M-D gate analysis).** Both design-review lenses independently proved
  the three-tier draft's first scheduled beat (a fork-steer) permanently breaks the
  claim: the beat body's new sid fails every `sup-*` verb, then `sup-boot` degrades into
  freeze-page-the-operator (N<1h) or hourly self-seizure polluting the append-only
  journal (N>1h) (break-lens C1, spec-lens X1).
- **2026-07-20 (NFC arc).** A conversation fork rotated the sid under the LIVE claim
  mid-shift; `sup-checkpoint` refused its own holder; `--sid <old>` override is the
  standing workaround (`lessons.md#2026-07-20-nfc`).

Two adjacent live warts, same root:

- **No self-recognition.** After a >60m heartbeat gap, `sup-boot` refuses its own
  same-sid holder (verdict refuse is only for live holders; roster-gone + stale =
  seize-your-own-claim, roster-gone + fresh = freeze). Only `sup-heartbeat` (which does
  not gate on staleness) recovers it (`lessons.md#2026-07-18-md`).
- **No `sup-release`.** An operator-authorized `claude stop` is indistinguishable from a
  daemon restart (both = roster-gone + fresh heartbeat = freeze). The only lever is a
  manual `rm supervisor/INCARNATION` — which bypasses `fleet_lock`, violating the
  invariant `write_incarnation`'s own docstring declares mandatory (break-lens M4).

## 2. Identity model

Terms, normative for everything below:

- **Soul** — the git-tracked identity: `supervisor/GOALS.md` + `supervisor/JOURNAL.md`.
  Survives everything. Unchanged by this spec.
- **Incarnation** — one continuous tenure of duty under one `inc-*` id. Begins at
  claim/seize/handoff-complete, ends at release/seizure/handoff. Unchanged.
- **Body** — one host process + context lineage executing an incarnation. An incarnation
  may pass through many bodies (fork-steer, rehost, respawn). NEW: each body is named by
  a **body nonce** (`b-` + 8 hex, minted with `uuid4`), stored in `INCARNATION`.
- **The nonce is a fencing token, not a secret.** `INCARNATION` is machine-local and
  world-readable; any local session — including a zombie — can read it. The nonce
  therefore authenticates nothing. What it does: a body must present the nonce it was
  *handed at its last rotation event*; a body acting on a stale world-model presents a
  stale nonce and is fenced loudly. This stops the observed failure class (a confused
  fork re-deriving work from old context — fleet's standing threat model, per
  `_confirm_destructive`'s docstring: "an over-helpful agent", not an adversary). It does
  not stop a body that deliberately re-reads the file before each verb; no file-based
  scheme can, and this spec does not claim to.
- Doctrine, normative: **a body never re-reads the nonce to satisfy a check.** A body
  that has lost its nonce (context compaction, crash) runs `sup-boot` and lets the
  decision matrix adjudicate — and a contested boot pages the operator (§6 R3); boot is
  the sanctioned recovery, not a self-service one. Re-reading defeats the fence.
  `sup-status` prints the nonce only under `--show-nonce` (operator debugging), with
  this doctrine in its output.

## 3. INCARNATION schema delta (v2)

```json
{
  "schema": 2,
  "incarnation_id": "inc-20260720T090000Z-ab12",
  "body_nonce": "b-3f9c1a2e",
  "prev_nonce": "b-91d0e4b7",
  "session_id": "<current body sid>",
  "lineage": ["<sid-1>", "<sid-2>", "..."],
  "worker_name": null,
  "claimed_at": "...", "heartbeat_at": "...",
  "claimed_via": "fresh|seize|handoff|reclaim|rejoin"
}
```

- `schema` — absent = v1 (sid-keyed). Discriminates migration (§10). Without it, v2 code
  meeting a v1 file could not tell "no nonce yet" from "nonce field corrupt".
- `body_nonce` — the current body. `prev_nonce` — exactly one rotation of history,
  honored only by the §5 rule-2 **single-use** grace; prevents a crash between the
  rotation-write and the body reading the new value from becoming a self-lockout (the
  freeze-page failure this spec exists to eliminate). **At first mint** (fresh claim,
  seize, handoff transfer) `prev_nonce` is null: no grace exists before the first
  rotation — a grace slot predating any rotation would be a free pass with no desync to
  excuse. Consuming the grace nulls it (§5 rule 2).
- `lineage` — every sid this claim has inhabited, appended at rotation and **compacted**
  at rotation (§9): only sids still present as some registry record's `spawned_by`
  survive, plus always the current sid; a hard backstop cap of 32 applies AFTER
  compaction (corruption backstop, not the working bound). Feeds `spawned_by`
  continuity (§9).
- `worker_name` — null today. Reserved for a future fleet-managed supervisor body
  (three-tier item 10); when set, the registry's name→sid mapping becomes continuity
  evidence (§4 row 4). Reserved now so the schema does not need a v3 for the re-draft
  this spec is a prerequisite of. The §4.1 machinery that keys on it ships DORMANT (§4.1
  sequencing note).
- All writes under `fleet_lock`, atomic (`_write_json_atomic`) — unchanged invariant.

## 4. Nonce lifecycle: rotation rules

The nonce rotates ONLY at **boot-shaped events** — never per verb. Rationale: every
rotation is a chance for the file and the body's memory to desync (crash between the
write and the body seeing the new value). Per-verb rotation maximizes fencing but makes
desync routine; boot-shaped rotation confines desync to rare, loud events. Rotation
semantics: `prev_nonce := body_nonce; body_nonce := fresh mint`. The verbs that rotate
print the new nonce as the FINAL line of stdout (`NONCE: b-…`) — for `sup-boot` this
**displaces `VERDICT` as the last line** (`cmd_sup_boot` prints VERDICT last today,
~:7297; VERDICT moves immediately above it). The rationale requires last position: a
truncated read must lose the nonce and force a re-boot, never keep an old value.

| # | Body event | Same body? | sid | nonce | Who proves continuity, how |
|---|---|---|---|---|---|
| 1 | Plain resume / same-sid continue (incl. G10 daemon auto-respawn: new pid, same sid) | same | unchanged | unchanged | Nobody — sid still matches the claim. No write. |
| 2 | Host restart, conversation re-hosted on the SAME sid | same | unchanged | unchanged | Body runs `sup-boot` → **reclaim** (§6 R3): sid + current nonce prove it, at any heartbeat age. Rotates. |
| 3 | Conversation fork / `--fork-session` rehost (sid rotates; fleet did not do it) | same logical body, new sid | new | rotate | Body runs `sup-boot` → **rejoin** (§6 R4): presents the CURRENT nonce; sid restamped, lineage appended. The 2026-07-20 incident, closed without `--sid`. |
| 4 | Fork-steer of a fleet-managed supervisor body (`send` idle path) | same incarnation, new body | new (captured from `--bg --resume` stdout) | pre-rotated | **Fleet proves it**, via the §4.1 two-lock protocol: nonce rotated BEFORE dispatch, new nonce rides the composed prompt, sid restamped after capture. DORMANT until `worker_name` exists. |
| 5 | Respawn of a fleet-managed supervisor body | new body, fresh context | new | rotate | Fresh context has no nonce. Registry name→sid continuity (`worker_name`) lets its first `sup-boot` reclaim; boot rotates. Until `worker_name` exists (three-tier), respawn does not apply to supervisors. |
| 6 | Handoff succession (`sup-handoff-*`) | new incarnation | new | successor mints its own | Successor's `sup-boot --handoff-inc` mints a nonce and writes it into `HANDSHAKE` beside inc + sid; `sup-handoff-complete` verifies `--expect-inc`/`--expect-sid` exactly as today (the old side cannot pre-know a nonce the successor mints — no `--expect-nonce`) and copies the handshake nonce into the new claim, `prev_nonce` null. Lineage carries over. |
| 7 | Seizure (stale heartbeat, roster-gone) | new incarnation | new | fresh mint, prev null | Seizer proves nothing about the predecessor — that is what seizure is. Lineage carries over (§9: the dead body's workers must not orphan). |
| 8 | Release (`sup-release`, §7) | none | — | cleared | Operator or holder. Next boot is a fresh claim. |
| 9 | Daemon restart / host restart with body dead, heartbeat fresh | — | — | unchanged | Nobody can — **freeze**, unchanged. The nonce must not weaken the never-seize-on-ambiguity rule; it only adds recognized paths OUT of the freeze (rows 2, 3, and §7). |

### 4.1 Fork-steer two-lock protocol (row 4)

The draft under-determined the steered body's nonce handoff, and both consistent
readings broke something (break-lens 3, spec-lens HIGH-2): prompt-carries-new-nonce
with a single post-dispatch restamp left a crash window in which R4 could not match
(freeze → hourly self-seizure — M-D re-minted); prompt-carries-old-nonce made grace the
steady-state channel. Normative protocol, replacing both:

1. **Hold 1 (pre-rotate).** Under `fleet_lock`, verify the steered record still names
   `claim.worker_name` with `registry sid == claim.session_id` (mirror
   `_restamp_after_steer`'s moved-on guard), then rotate: `prev := body, body := N2`,
   sid UNCHANGED. Write `INCARNATION`. Release the lock.
2. **Dispatch** outside any lock (F4 doctrine), the composed prompt carrying `N2` in
   its boot line. On a dispatch FAILURE that returns (error, DOA), a compensating hold
   rolls back `body := N1, prev := null` if the claim is still `{body:N2, sid:S1}`
   (the pre-hold-1 prev is unrecoverable; losing a stale grace slot is harmless — the
   rotation it excused was just rolled back).
3. **Hold 2 (sid restamp).** After sid capture, under `fleet_lock`: if the claim is
   still `{body:N2, sid:S1}`, write `INCARNATION` with `session_id := S2` and
   `lineage := compact(lineage + [S2])` **FIRST, then** the registry commit
   (`_restamp_after_steer` + status/event, one hold). **INCARNATION-first is
   normative**: a crash between the two writes leaves the CLAIM naming the true
   current body and only the registry stale (bookkeeping; heals at the next steer's
   hold-1 guard, doctor-visible). The reverse order re-opens C1 — a claim naming a
   retired sid while the registry moves on.

Crash windows and their required outcomes (§11 tests assert exactly these):

- **W1** — hard crash after hold 1, before capture, no successor launched: the
  predecessor holds `prev`; it gets one §5 rule-2 grace use for an in-flight verb, and
  its boot is **contested** (fresh heartbeat, non-current nonce → §6 R3) → operator
  ack → reclaim. Loud and rare; NEVER freeze, NEVER seize.
- **W2** — crash after capture, before hold 2: claim `{N2, S1}`; successor B2 runs
  with `(S2, N2)`. B2's verbs hit §5 rule 5 → boot → R2 refuses while `S1` lingers
  roster-live (see R2 caveat, §6) → once `S1` leaves liveness, **R4 rejoin** on the
  current nonce. Worst case is delay bounded by the predecessor's lingering entry;
  NEVER freeze, NEVER seize.
- **W3** — crash inside hold 2 between the INCARNATION and registry writes: claim
  names `S2`; B2 is fully operational via §5 rule 1; the stale registry heals at the
  next steer and is doctor-flaggable meanwhile.

**Sequencing (binding).** This machinery ships with this spec but is DORMANT until
`worker_name` is first set — which only the three-tier slice (adjudication item 10,
`sup-spawn`) may do. **No scheduled beat may be installed before item 10 lands**: until
row 4 is active, every scheduled beat is an external rotation (row 3) = one rejoin BOOT
journal entry per beat — journal pollution redux (break-lens 9, spec-lens 3).

## 5. The claim check (`_require_claim_holder`, post-nonce)

Every claim-gated `sup-*` verb takes `--sid` (existing) and `--nonce` (new). The check,
in order; first match wins:

1. **sid == claim.session_id AND nonce == claim.body_nonce** → pass. The normal case.
2. **sid == claim.session_id AND nonce == claim.prev_nonce AND prev_nonce not yet
   consumed** → pass ONCE: the check consumes the grace (`prev_nonce := null`, written
   under the caller's existing `fleet_lock` hold), logs a `nonce-resync` event, and
   prints ONLY "grace consumed — run sup-boot to resync". **The grace output NEVER
   contains the current nonce.** Purpose: an in-flight verb by a body whose
   rotation-write landed but whose turn died before reading the new value completes
   instead of freezing; the sanctioned resync is boot, which adjudicates contests
   (§6 R3). Why single-use and never-print: the drafted rule (replayable until the
   next rotation, printing the current nonce) re-armed an ACTIVE same-sid zombie at
   every rotation — a resync treadmill that made rule 4 unreachable and the headline
   guarantee below false. Both lenses found this independently; it was the review's
   top finding. A crash after the grace is consumed but before the graced verb's
   effect lands loses both the slot and the action; recovery is the body's next boot
   — contested page at a fresh heartbeat, reclaim at a stale one — never freeze.
3. **sid == claim.session_id AND nonce absent** → refuse: "claim is schema 2; pass
   --nonce (printed at your last rotation event). If you have LOST it, run sup-boot —
   an unproven reclaim against a fresh heartbeat is CONTESTED and pages the operator
   (§6 R3); boot will not silently hand you the claim." The drafted text — an
   unqualified "run sup-boot" — was itself the laundering instruction (break-lens 2).
4. **sid == claim.session_id AND nonce is neither current nor prev** → refuse, loudly
   named: "your sid matches but your nonce is stale — a newer body of your lineage has
   acted since your context was captured. You are likely a superseded fork
   (lessons.md#2026-07-17-mc). Take NO fleet actions; report to the operator." The
   M-C zombie, which today passes every check forever, is refused here.
5. **sid != claim.session_id** → refuse (unchanged text plus: "if your sid rotated
   under you, run sup-boot — rejoin requires your CURRENT nonce (§6 R4); a boot
   without it is contested and pages the operator"). Sid-mismatched callers go through
   the boot matrix, never through a verb-level side door.

`--sid` override survives (human operator repair path), but rule 3 applies to it too.

**First-writer-wins, honestly — the zombie-fencing bound.** Between a fork and the
first rotation by either body, both bodies hold (same sid, same nonce) and both pass
rule 1. The nonce does not prevent the fork; it bounds the damage. After any rotation:
a same-sid zombie can steal AT MOST ONE claim-gated action per rotation (the single
grace use), learns nothing from it (no nonce in the output), and its first boot
thereafter is contested — which pages the operator (§6 R3). The zombie may instead
BURN the true holder's grace first; then the HOLDER's next boot is the contested one.
Either way the split terminates at a human within one rotation plus one boot, instead
of two silent writers forever. Which body wins the pre-rotation race is deliberately
unadjudicated (no evidence prefers one identical body; M-C showed the zombie's work
can be good). The residual window — fork to first rotation, during which non-`sup-*`
mutating verbs are also open (§8) — is stated, not solved, at this layer.

## 6. Claim decision matrix (`supervisor_claim_decision`, rewritten)

Inputs: claim (v2), caller sid, caller nonce (optional), roster live-sids, journal
latest entry, heartbeat age. Verdicts: `claim`, `reclaim` (NEW), `rejoin` (NEW),
`contested` (NEW), `refuse`, `seize`, `freeze`. Rules in order, first match wins:

| R | Condition | Verdict | Failure this ordering prevents |
|---|---|---|---|
| R0 | Epoch check failed (roster unavailable/empty) | freeze | Unchanged, still FIRST: a daemon restart (G9) must never let any path below — including the new reclaim/rejoin — run against a blind roster. |
| R1 | No claim, OR the journal's latest entry is `RELEASED` naming `claim.incarnation_id` (§7: a crash between journal-and-delete leaves a released-but-present claim; R6 is structurally blind to it — R6 keys on inc DIFFERENCE and a self-release carries the SAME inc) | claim | Fresh claim; mint inc + nonce, prev null, lineage=[sid] (carried lineage if released file present). The boot also completes the interrupted delete under its lock hold. Without this rule the released-claim crash freezes every boot for up to `stale_seconds` (break-lens 5). |
| R2 | claim.session_id ∈ roster live-sids AND caller sid != claim.session_id | refuse | **The two-supervisor guard, preserved verbatim** (§6.1). Runs before every recognition rule: a live holder is never displaced by a booting body, nonce or no nonce. CAVEAT: liveness inherits the roster contract's artifacts — a lingering done-state entry (posix variant 2, OPEN in project memory) or an idle predecessor inside its reap window reads live, delaying a legitimate rejoin for that long. Fail direction: delay, never seizure; the refusal text names the suspect entry so an operator can adjudicate. |
| R3 | caller sid == claim.session_id | see sub-table | Self-recognition with contest adjudication (below). |
| R4 | caller nonce == claim.body_nonce (sid differs; R2 already proved the old sid is not live) | **rejoin** | Same inc, restamp sid, rotate nonce, append+compact lineage, refresh heartbeat, journal `BOOT` (body: `rejoin from <old-sid>`). Closes the 2026-07-20 incident. `prev_nonce` is NOT accepted here — cross-sid grace would let a twice-forked lineage rejoin over a once-forked one; only the current nonce proves the freshest body. |
| R5 | Heartbeat unreadable | freeze | Unchanged: never seize on ambiguity. |
| R6 | Journal's latest entry names a fresher incarnation than the claim | refuse | Unchanged: transition in flight. |
| R7 | Heartbeat stale (> `SUPERVISOR_CLAIM_STALE_SECONDS`) | seize | Unchanged mechanics; new inc + nonce (prev null); lineage carried over. |
| R8 | Otherwise (roster-gone, heartbeat fresh) | freeze | Unchanged — daemon restart vs authorized stop stays ambiguous BUT the freeze text now names the levers: "same body, same sid, nonce in hand → sup-boot reclaims; same body, new sid → sup-boot --nonce rejoins; operator authorized the stop → fleet sup-release." Freeze becomes a signpost instead of a dead end. |

R3 sub-table (caller sid == claim.session_id):

| Caller nonce | Heartbeat fresh | Heartbeat stale |
|---|---|---|
| current | **reclaim** — silent: same inc, rotate, refresh, journal `BOOT` (body: `reclaim`). Any age: fixes the 2026-07-18 wart. | reclaim (same). |
| prev / absent | **contested** — refuse (rc 3-adjacent, own code) paging the operator. Proceeds only via `sup-boot --ack-contested`, honored solely when `current_caller_session()` is None (human shell, §7's carve-out), or after `sup-release`. | **reclaim** — the returning holder after a gap (context compacted, or §4.1 W1 crash then sleep); no live-contest evidence exists. |
| stale (supplied, neither current nor prev) | refuse with §5 rule-4's zombie text — superseded lineage; `--ack-contested` is the operator override. | refuse (same). |

Paging a human on the first contested reclaim is the DESIGNED terminal state for a
same-sid fork: two bodies with one sid are mechanically indistinguishable, and any
rule that silently picks one (the draft's absent-nonce reclaim; a prev-nonce silent
reclaim) is a laundering path — the latter additionally enables a boot-level
ping-pong, each body alternately reclaiming via prev forever (break-lens 2's
compounding). Contested exists so the matrix can say "I cannot know" out loud.

`supervisor_claim_decision` stays a pure function (no IO); caller nonce, the grace
state, and the registry lookup (row 4/5 of §4, when `worker_name` lands) enter as
parameters, keeping the unit matrix (§11) exhaustive without a live fleet.

### 6.1 The two-supervisor roster guard, post-nonce

The guard today: `claim.session_id ∈ _roster_live_sids(entries)` → refuse
(`supervisor_claim_decision` ~:7147; `_roster_live_sids` ~:7100, including the
`state:"done"`-is-never-live rule from the 2026-07-19 posix finding). It MUST be
preserved: it is the only thing standing between a booting body and a live holder.

Post-nonce it is preserved **and becomes sound where it was vacuous**. The true
invariant, stated precisely: every FLEET-MEDIATED rotation restamps
`claim.session_id` atomically with the registry (§4.1, INCARNATION-first), so outside
the enumerated §4.1 crash windows — and outside the interval between an EXTERNAL
rotation (row 3: a fork fleet did not perform) and its rejoin — the guard tests the
CURRENT body's sid. Pre-nonce, after any un-restamped rotation, the guard tested a
retired sid that could never be roster-live — structurally disarmed, which is exactly
how C1's freeze/seize churn got past it. The guard's mechanics do not change: same
roster source (`claude agents --json --all`), same liveness predicate, same position
before every seize/recognition path (R2 precedes R3/R4/R7). `sup-handoff-complete`'s
`--expect-sid` dual verification is likewise unchanged (§4 row 6).

## 7. `sup-release`

`fleet sup-release --reason <text> [--sid S] [--nonce N]` — the missing authorized
release. Converts today's hand-`rm` (lockless, unlogged, invariant-violating) into a
recorded transition.

- **Who may call.** (a) The holder: passes the §5 check (sid + nonce). (b) A human
  operator at a plain shell: `current_caller_session()` is None — same carve-out, same
  rationale as `_confirm_destructive` (a human typing `sup-release` meant it; the
  threat model is agents). (c) A Claude session that is NOT the holder: refused —
  releasing someone else's claim from an agent session is seizure without the
  staleness evidence, exactly what R8 exists to prevent. No `--force` for agents; the
  operator path IS the force path.
- **Semantics.** Under `fleet_lock`: journal `RELEASED` (new kind, added to
  `SUPERVISOR_JOURNAL_KINDS`) with the reason and the released inc, then delete
  `INCARNATION`. Journal-then-delete, in that order: a crash between the two leaves a
  released-but-present claim, which the matrix reads as ABSENT via R1's
  latest-entry-RELEASED rule (§6) and cleans up at the next boot — R6 CANNOT provide
  this net (it keys on inc difference; a self-release entry carries the same inc —
  break-lens 5 caught the draft mis-citing it). The reverse order leaves an
  unexplained absence — the exact hand-`rm` illegibility this verb replaces.
  Refuse while a handoff is in flight (`HANDSHAKE` present, or latest journal entry is
  `HANDOFF-BEGIN` without a matching complete/abort): the successor limbo protocol
  (`sup-handoff-abort`) owns that state; two cleanup paths racing is how limbo
  successors leak. Known residual: a holder `sup-checkpoint` written between
  `HANDOFF-BEGIN` and the successor's boot makes CHECKPOINT the latest entry and
  defeats the latest-entry arm — a release in that gap orphans the successor loudly,
  bounded by the handshake timeout (~10 min, `sup-handoff-abort`/doctor visible);
  delay, not danger.
- **Journal record.** `## <ts> RELEASED inc=<inc> sid=<caller-sid|operator>` with body
  = reason. The `sid=operator` literal (impossible as a real sid) makes human releases
  greppable. Written via `supervisor_journal_append` — single-writer discipline holds
  because release IS a claim-holder-or-operator act.
- **What it fixes.** The operator-authorized `claude stop`: operator stops the body,
  runs `sup-release --reason "authorized stop"`, next `sup-boot` takes R1 (fresh
  claim) instead of R8 (freeze-page). The authorization finally has a place to live.

## 8. What the claim gates (adjudication item 2)

Complete verb enumeration at 771e4ee, by class:

- **Read-only, never gated** (views doctrine — no lock, no probe, no write): `home`,
  `knowledge`, `status`, `peek`, `result`, `wait`, `doctor`, `sup-status`.
- **Claim-gated, full §5 check** (`_require_claim_holder` callers): `sup-checkpoint`,
  `sup-heartbeat`, `sup-handoff-begin`, `sup-handoff-complete`, `sup-handoff-abort`;
  plus `sup-release` (§7, new). `sup-boot` gates itself via the decision matrix.
- **Mutating fleet verbs, claim-blind today**: `spawn`, `send`, `interrupt`, `attach`,
  `release`, `respawn`, `resume-limited`, `kill`, `clean`, `archive`, `autoclean`,
  `init`.

Two models, per the adjudication's framing:

**Model A — journal-writes-require-claim (status quo + nonce) with body-fencing.**
The claim guards only the soul (journal + INCARNATION). Superseded bodies are fenced
physically: `sup-handoff-complete` and the seize path `claude stop` the superseded sid
when it is roster-live (fleet already owns stop-then-verify — `respawn --force`'s
shape) and write its tombstone (G10: an external stop fires no Stop hook; the stopper
owes the record). Failure modes: (1) fencing only reaches bodies fleet can see — the
M-C zombie was an un-registered conversation fork; nothing stops what the roster does
not list as connected to the claim. (2) A body that dodges the stop (stop rc
ambiguity, 2.1.212 dead-daemon path) remains free to mutate: **Model A alone ships
the observed zombie class** (7 phantom sends were `send`s, not journal writes).

**Model B — mutations-require-claim (soft fence).** Every mutating fleet verb, when
(i) `INCARNATION` exists with schema ≥2 and a fresh heartbeat, (ii) the caller is a
Claude session (`current_caller_session()` non-None), and (iii) the caller's sid is
not `claim.session_id`, prints a
one-line warning naming the holder and refuses unless `--anyway` is passed. Humans at
a shell are exempt (carve-out as in §7). The holder passes silently.

**Flag surface, adjudicated (one rule, not two).** The full sid+nonce check (§5)
applies ONLY to the claim-gated `sup-*` verbs above; **mutating fleet verbs identify
the holder by sid alone and gain `--anyway` only — no `--nonce`, no `--sid`.** The
draft left a conflict: §5 rule 3 hard-refuses a nonce-less holder while Model B gives
strangers a warn+`--anyway` — inverted severity if both applied to the same verb.
Resolution: they never apply to the same verb. Costs, stated: a same-sid zombie
passes the fence on fleet verbs (sid matches) — the fence is ADVISORY against that
class; hard fencing lives at the `sup-*` layer, where the zombie is caught at its
first journal/heartbeat/boot touch (§5). Benefits: no `--nonce` sprawl across 12
verbs, no hard-lockout of fleet operations on a nonce desync, and the fence stays
fail-open per the views doctrine (a stale or corrupt claim disables it, because fleet
MUST remain drivable with no supervisor).

Failure modes of Model B, stated: (1) fail-open by design, as above; a zombie racing
inside the fork-to-first-rotation window (§5) also passes. (2) `--anyway`
normalization — same class as reflexive `--yes`, which D2 forbids normalizing;
doctrine + review-gate is the only backstop, and this spec says so rather than
pretending the flag is a wall. (3) Non-supervisor Claude sessions running legitimate
mutations (a worker spawning a sub-worker, WORKER-SUBAGENTS intent) eat a warning +
flag; acceptable friction today, revisit when that intent lands. (4) One
`read_incarnation()` per mutating verb — lock-free read of an atomically-written
file, no new contention.

**What the fence does NOT cover — the residual, enumerated (advisory-not-wall, per
§2's threat model).** (a) The raw substrate CLI: `claude --bg` dispatch/steer/stop
issued directly bypasses fleet entirely — the substrate equivalent of the 7 phantom
sends. (b) Direct filesystem writes: `supervisor/JOURNAL.md` append-only is a
discipline enforced only at the fleet chokepoint; nothing stops `echo >>`. (c) The
human carve-out keys on `CLAUDE_CODE_SESSION_ID` absence — a session that unsets it
silently becomes "human", disabling both this fence and the destructive guard, with
no argv evidence (unlike `--anyway`, which at least leaves a flag in the audit
trail). All three are open against a confused-or-worse body; the fence raises the
cost of accidents, not the impossibility of abuse.

**Recommendation: Model B (as adjudicated above), plus Model A's body-fencing at
handoff-complete/seize.** B closes the observed incident class (phantom mutations by
a confused body); A's fencing closes the beat-resurrection path C2 proved (a stopped
body cannot be fork-steered and its ScheduleWakeup dies with it, G7). Neither alone
covers both. The break lens reached the same "both" conclusion independently (C2,
named fix). Journal-only-forever (pure status quo) is rejected: the adjudication's
own words — "silence ships the zombie class."

## 9. `spawned_by` continuity (adjudication item 3)

`spawned_by` is spawn-immutable (SPEC §4/§5.1) and this spec does NOT amend that: a
record's `spawned_by` stays the sid that dispatched it, forever, as provenance.
What changes is the FOREIGNNESS TEST, not the field. `_worker_is_foreign` (~:2181)
today: `record.spawned_by != caller sid` → foreign → destructive verbs (`kill`,
`clean`, `respawn`) demand `--yes`. After any supervisor body change, every worker
the previous body spawned goes foreign to the new body — which either blocks the
supervisor on its own fleet or normalizes reflexive `--yes`, the exact two outcomes
D2 forbids.

Rule: `_worker_is_foreign` returns False additionally when **the caller passes the
§5 claim check AND `record.spawned_by ∈ claim.lineage`**. The lineage (§3) is
append-at-rotation, carried across handoff and seizure (§4 rows 6–7): ownership
follows the DUTY, not the process — the successor inherits the predecessor's
workers because it inherits the predecessor's obligations to them (respawn-fresh,
resume-limited, retirement). Failure prevented: a handoff successor unable to
`respawn` a wedged worker its predecessor spawned without ceremony, at 3am, on the
one path (`--yes`) whose reflexive use the destructive-guard threat model exists to
prevent.

**Compaction, not a raw cap.** At every rotation, under the same lock hold:
`lineage := [s for s in lineage + [current sid] if s == current sid or s appears as
some registry record's spawned_by]`, order preserved, deduped; a hard backstop cap
of 32 applies AFTER compaction (drop oldest — corruption backstop only). The draft's
raw 32-cap was sized for rare rotations; under three-tier a beat IS a rotation
(§4 row 4), so cap-eviction would become routine within days and re-normalize
`--yes` on the exact deployment this spec is a prerequisite of (break-lens 4).
Compaction keys retention on the thing the list exists for — sids that still own a
registered worker. Cost: one registry read inside rotation lock holds (registry
loads under `fleet_lock` are the standard pattern). An UNREADABLE registry at
rotation skips compaction entirely (lineage carried unchanged, backstop cap still
applied) — never compact against a falsely-empty view; the worst outcome on this
path is later `--yes` friction, never widened ownership and never danger.

Bounds, stated: (a) A worker spawned by a session that NEVER held the claim stays
foreign — lineage is claim history, not machine history. (b) Records predating
`spawned_by` stay foreign (unchanged fail-toward-asking). (c) A worker whose
spawner-sid was compacted away while the worker was temporarily absent from the
registry (cleaned then re-spawned under the same sid is impossible; absent =
cleaned) cannot recur — compaction against the live registry is exact. Post-cap
overflow → `--yes` with eyes open — documented, rare, not normalized. (d) The check
runs only when a claim exists and the caller is its holder; it never widens
ownership for non-holders. No SPEC §4 field-immutability amendment is required;
SPEC §5.1's foreignness prose gains one sentence and must cite this spec.

## 10. Migration

- **v2 code, v1 file (no `schema` key).** Sid-only: `_require_claim_holder` accepts a
  sid-equal caller for a v1 claim and **ignores any supplied `--nonce` entirely**
  (one-line notice, never checked): after a v1-writer downgrade (below), a v2 holder
  supplying its remembered nonce must not be routed into rule 4's "you are a fork,
  take NO fleet actions" text — a false zombie verdict aimed at the one body doing
  everything right (break-lens 6). Every rotation-writing verb upgrades the file in
  place (add `schema:2`, mint `body_nonce`, `prev:null`, `lineage=[session_id]`)
  under `fleet_lock`, printing the nonce. Upgrade-on-touch by the holder or the
  matrix — never by a view, never by a non-holder (a booting stranger upgrading a
  file it does not own would be a write outside the single-writer discipline).
- **v1 code, v2 file (worktree copies share one FLEET_HOME — real on this repo).**
  v1 `_require_claim_holder` reads only `session_id`, which v2 keeps current —
  sid-path verbs work. v1 write paths (`sup-boot` claim/seize, handoff-complete)
  write a v1-shaped file, silently DROPPING nonce/lineage/schema. Consequence: the
  claim degrades to sid-keyed until the next v2 touch re-upgrades; rejoin (R4) and
  lineage ownership (§9) are unavailable in the gap; nothing corrupts, and — with
  the ignore-nonce rule above — nothing locks out or mis-verdicts. Stated, accepted:
  fleet is a single stdlib file — mixed versions are transient worktree states, not
  a deployment mode.
- **Journal format: UNCHANGED.** The entry header stays
  `## <ts> <KIND> inc=<inc> sid=<sid>` — `_SUPERVISOR_ENTRY_RE` (~:7039) is anchored
  (`\s*$`), and a header gaining a field would make every v1 parser fold each v2
  entry into the PREVIOUS entry's body (`parse_supervisor_journal` appends
  unmatched lines to the current entry) — `latest_entry` would then name a STALE
  entry, quietly mis-feeding R6/R1's latest-entry rules. (The draft claimed the
  failure was an EMPTY `latest_entry` — wrong mechanism, same conclusion.) The nonce
  and rotation detail ride in the entry BODY (first line, `nonce: b-…`), greppable
  but not load-bearing for any parser. New kinds: `RELEASED` (§7) appended to
  `SUPERVISOR_JOURNAL_KINDS`; `parse_supervisor_journal` accepts unknown kinds
  already (regex is `[A-Z][A-Z-]*`) — v1 readers render RELEASED entries fine.
- **HANDSHAKE**: gains `body_nonce`. v1 `sup-handoff-complete` ignores it (writes a
  v1 claim; degradation case above). v2 complete against a v1 handshake (no nonce):
  mint one at transfer — the successor learns it from its first `sup-boot` reclaim.

## 11. Test plan

Unit (pytest, SPEC §12; `supervisor_claim_decision` stays pure — the matrix needs no
live fleet):

- **Decision matrix, exhaustive**: every R0–R8 row (including the R1 released-claim
  arm and the full R3 sub-table) × {nonce: current, prev, prev-consumed, stale,
  absent} × {heartbeat: fresh, stale, unreadable} × {holder sid: live, gone,
  done-lingering (posix 2026-07-19 rule)} × {schema: 1, 2}. Assert verdict AND
  reason text (the reasons are operator UI; R8's signpost and R3's contested page
  are load-bearing).
- **Ordering proofs**: R2 beats R3/R4 (live holder never reclaimed-over or
  rejoined-over); R0 beats everything (blind roster freezes even a sid-matched
  reclaim); R4 rejects prev_nonce cross-sid; R1's released arm beats R8 (released
  claim + fresh heartbeat = fresh claim, not freeze).
- **Grace single-use** (`test_grace_single_use`): (sid, prev) passes once, nulls
  `prev_nonce`, logs `nonce-resync`, output contains NO current nonce; the second
  (sid, prev) call refuses with rule-4 text. Treadmill regression: after a rotation,
  a zombie's grace use + subsequent verb → refused; its boot → contested, never a
  silent reclaim.
- **Contested reclaim** (`test_contested_reclaim_pages_operator`): same-sid boot
  with absent or prev nonce + fresh heartbeat → contested verdict, distinct rc,
  operator-paging text; `--ack-contested` honored only when
  `current_caller_session()` is None; same boot + stale heartbeat → reclaim.
  Ping-pong regression: two bodies alternating prev-nonce boots — the second boot in
  the chain is contested, never a third silent rotation.
- **Steer protocol** (`test_steer_crash_windows`, §4.1): W1 → predecessor grace-once
  then contested→ack→reclaim, never freeze/seize; W2 → successor refused by R2
  while the predecessor lingers, R4-rejoins once it is gone, never freeze/seize;
  W3 → successor passes §5 rule 1, registry divergence doctor-flagged and healed by
  the next steer's hold-1 guard. Dispatch-failure rollback restores `body:=N1,
  prev:=null` and only when the claim is still `{N2, S1}` (moved-on guard).
- **sup-release**: holder path, operator path (env cleared), non-holder agent
  refused, handoff-in-flight refused; journal-then-delete crash → next boot takes
  R1's released arm (fresh claim + file cleanup), NOT freeze
  (`test_released_crash_recovers_fresh`).
- **§9**: lineage ownership passes `_worker_is_foreign` for holder + lineage sid;
  non-holder unchanged. Compaction: spawner-sids with registered workers survive
  >32 rotations; sids with no surviving worker are evicted; current sid always
  survives (`test_lineage_compaction`).
- **Migration**: each cell of §10's 2×2, including the v1-writer downgrade
  round-trip AND `test_v1_downgrade_sid_only`: a v2 holder supplying its nonce
  against a v1 file passes sid-only with the ignore notice — rule-4's zombie text
  must NOT appear.

Fault injections that would have caught the three incidents (each is a regression
test, named for its incident):

1. **`test_zombie_fork_fenced` (M-C).** Two callers, same sid, same nonce. A
   reclaims (rotates); B's `sup-checkpoint` with the old nonce → one grace pass
   (nonce-free output), then refused with the §5 rule-4 text; B's `sup-boot` →
   contested. Pre-nonce code: B writes the journal — the test fails on v1
   semantics by construction.
2. **`test_first_beat_survives` (M-D gate).** Simulated fork-steer of a
   `worker_name` supervisor through the full §4.1 protocol: pre-rotate, dispatch,
   sid restamp; new sid + prompt nonce pass `sup-heartbeat`;
   `supervisor_claim_decision` for a subsequent boot never returns seize or freeze
   within the beat cadence. Pre-nonce: heartbeat raises at the first beat.
3. **`test_conversation_fork_rejoins` (2026-07-20).** Claim holds old sid, holder
   gone from roster; caller has new sid + current nonce → rejoin; `sup-checkpoint`
   then passes with NO `--sid` override. Pre-nonce: refuse, workaround required.
4. **Wart regressions**: `test_stale_heartbeat_reclaim` (same sid, current nonce,
   19h-stale beat → reclaim, not refuse/freeze); `test_authorized_stop_release`
   (stop + release + boot → fresh claim, no freeze).

Integration (haiku worker, temp dir, per CLAUDE.md): one end-to-end fork-steer of a
registered body with claim restamp, and one `sup-release` from a plain (env-stripped)
shell. The dead-daemon variants of stop-based fencing (§8 Model A) are
interactive-session-only per the probe-context lesson — mark them as such; a `--bg`
runner cannot observe that path and a green run there proves nothing.

## 12. Open questions for the dual-lens review

(Draft questions 1, 2, 4, 5 are answered and folded in above as normative: grace is
single-use and never prints the nonce; contested reclaim demands an operator ack on a
fresh heartbeat; lineage compacts against the registry; `worker_name`/row-4 machinery
ships dormant until item 10. Remaining:)

1. **Grace-burn contention.** A zombie that burns the holder's single grace slot
   forces the HOLDER's next boot into the contested page. One operator page per
   contest is the designed terminal state — but under three-tier's unattended
   premise, is that ops load acceptable, or does contested need an autonomous
   fallback (e.g. freeze-equivalent park + nag) after N unanswered pages?
2. **W2 delay vs R2 dominance.** In §4.1 W2 the successor holds the fleet-minted
   current nonce yet waits out the predecessor's roster-liveness (worst ~1h reap
   window; posix variant 2 could extend it). Accepted here as delay-not-danger.
   Should possession of the CURRENT nonce — which only fleet's own pre-rotate hands
   out — override R2 for exactly this window, or is that the first crack in the
   two-supervisor guard?
3. **The ack channel.** `--ack-contested` and the operator carve-outs key on
   `CLAUDE_CODE_SESSION_ID` absence, which §8(c) names as silently spoofable. Does
   the ack need a stronger channel (e.g. an operator-touched file under
   `supervisor/`, mirroring GOALS ownership), or is env-absence acceptable given
   the advisory-not-wall threat model?
