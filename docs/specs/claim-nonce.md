# Per-body supervisor claim nonce

Status: PROPOSAL — awaiting dual-lens review + operator ratification.
Author: fleet worker `flt-nonce-spec`, 2026-07-20. The author may not promote this spec.
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
  decision matrix adjudicate. Re-reading defeats the fence; the boot ritual is the
  sanctioned recovery. `sup-status` prints the nonce only under `--show-nonce`
  (operator debugging), with this doctrine in its output.

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
  accepted only under the §5 grace rule; prevents a crash between rotation-write and the
  body reading the new value from becoming a self-lockout (the freeze-page failure this
  spec exists to eliminate).
- `lineage` — every sid this claim has inhabited, append-at-rotation, capped at the
  newest 32. Feeds `spawned_by` continuity (§9). Cap prevents unbounded file growth; a
  worker older than 32 supervisor rotations falls back to the explicit `--yes` path,
  which is the pre-existing behavior, not a new failure.
- `worker_name` — null today. Reserved for a future fleet-managed supervisor body
  (three-tier item 10); when set, the registry's name→sid mapping becomes continuity
  evidence (§5 fork-steer row). Reserved now so the schema does not need a v3 for the
  re-draft this spec is a prerequisite of.
- All writes under `fleet_lock`, atomic (`_write_json_atomic`) — unchanged invariant.

## 4. Nonce lifecycle: rotation rules

The nonce rotates ONLY at **boot-shaped events** — never per verb. Rationale: every
rotation is a chance for the file and the body's memory to desync (crash between the
write and the body seeing the new value). Per-verb rotation maximizes fencing but makes
desync routine; boot-shaped rotation confines desync to rare, loud events. The verbs
that rotate print the new nonce as the LAST line of stdout (`NONCE: b-…`), so a truncated
read fails toward the body re-running boot, not toward acting on a guess.

| # | Body event | Same body? | sid | nonce | Who proves continuity, how |
|---|---|---|---|---|---|
| 1 | Plain resume / same-sid continue (incl. G10 daemon auto-respawn: new pid, same sid) | same | unchanged | unchanged | Nobody — sid still matches the claim. No write. |
| 2 | Host restart, conversation re-hosted on the SAME sid | same | unchanged | unchanged | Body runs `sup-boot` → **reclaim** (§6 R3): sid match proves it, at any heartbeat age. Rotates. |
| 3 | Conversation fork / `--fork-session` rehost (sid rotates; fleet did not do it) | same logical body, new sid | new | rotate | Body runs `sup-boot` → **rejoin** (§6 R4): presents remembered nonce; sid restamped, lineage appended. The 2026-07-20 incident, closed without `--sid`. |
| 4 | Fork-steer of a fleet-managed supervisor body (`send` idle path) | same incarnation, new body | new (captured from `--bg --resume` stdout) | rotate | **Fleet proves it**: when the steered record's name equals `claim.worker_name`, the steer's commit restamps `INCARNATION` (new sid, new nonce, lineage append) in the same `fleet_lock` hold as `_restamp_after_steer`. Atomicity is the point: a claim restamp outside that lock re-opens C1's window. New body reads its nonce from the composed prompt's boot line. |
| 5 | Respawn of a fleet-managed supervisor body | new body, fresh context | new | rotate | Fresh context has no nonce. Registry name→sid continuity (`worker_name`) lets its first `sup-boot` reclaim; boot rotates. Until `worker_name` exists (three-tier), respawn does not apply to supervisors. |
| 6 | Handoff succession (`sup-handoff-*`) | new incarnation | new | successor mints its own | Successor's `sup-boot --handoff-inc` mints a nonce and writes it into `HANDSHAKE` beside inc + sid; `sup-handoff-complete` verifies `--expect-inc`/`--expect-sid` exactly as today (the old side cannot pre-know a nonce the successor mints — no `--expect-nonce`) and copies the handshake nonce into the new claim. Lineage carries over. |
| 7 | Seizure (stale heartbeat, roster-gone) | new incarnation | new | rotate (fresh mint) | Seizer proves nothing about the predecessor — that is what seizure is. Lineage carries over (§9: the dead body's workers must not orphan). |
| 8 | Release (`sup-release`, §7) | none | — | cleared | Operator or holder. Next boot is a fresh claim. |
| 9 | Daemon restart / host restart with body dead, heartbeat fresh | — | — | unchanged | Nobody can — **freeze**, unchanged. The nonce must not weaken the never-seize-on-ambiguity rule; it only adds recognized paths OUT of the freeze (rows 2, 3, and §7). |

## 5. The claim check (`_require_claim_holder`, post-nonce)

Every claim-gated verb takes `--sid` (existing) and `--nonce` (new). The check, in
order; first match wins:

1. **sid == claim.session_id AND nonce == claim.body_nonce** → pass. The normal case.
2. **sid == claim.session_id AND nonce == claim.prev_nonce** → pass, log a
   `nonce-resync` event, print the current nonce. Grace-of-one: a body whose
   rotation-write landed but whose turn died before reading the new value must not
   freeze-page an operator (that is the M4 lockout class, re-minted). Cost, stated
   honestly: a same-sid zombie is fenced at the true body's SECOND rotation after
   divergence, not its first. Grace is same-sid only and exactly one deep.
3. **sid == claim.session_id AND nonce absent** → refuse: "claim is schema 2; pass
   --nonce (yours was printed at your last sup-boot); if you have lost it, run
   sup-boot." A nonce-less habit replayed from pre-nonce context is exactly the zombie
   signature; omission must not be a bypass.
4. **sid == claim.session_id AND nonce is neither current nor prev** → refuse, loudly
   named: "your sid matches but your nonce is stale — a newer body of your lineage has
   acted since your context was captured. You are likely a superseded fork
   (lessons.md#2026-07-17-mc). Take NO fleet actions; report to the operator." This
   line is the entire point of the nonce: the M-C zombie, which today passes every
   check forever, is refused here with instructions.
5. **sid != claim.session_id** → refuse (unchanged text plus: "if your sid rotated
   under you, run sup-boot — it can rejoin"). Sid-mismatched callers go through the
   boot matrix, never through a verb-level side door.

`--sid` override survives (human operator repair path), but rule 3 applies to it too.

**First-writer-wins, honestly.** Between a fork and the first rotation by either body,
both bodies hold (same sid, same nonce) and both pass rule 1. The nonce does not
prevent the fork; it bounds the damage: the first body to complete a boot-shaped verb
rotates the pair under `fleet_lock`, and the other body's next claim-gated verb hits
rule 4. Which body wins is a race — deliberately unadjudicated (no evidence exists to
prefer one identical body over another; the M-C incident showed the zombie's work can
be good). What the spec guarantees is: the split becomes DETECTED and one-sided at the
first rotation, instead of two writers forever; the loser gets told what it is, instead
of a generic permission error it will route around. The residual window — fork to first
rotation, during which non-`sup-*` mutating verbs are also open (see §8) — is stated,
not solved, at this layer.

## 6. Claim decision matrix (`supervisor_claim_decision`, rewritten)

Inputs: claim (v2), caller sid, caller nonce (optional), roster live-sids, journal
latest entry, heartbeat age. Verdicts: `claim`, `reclaim` (NEW), `rejoin` (NEW),
`refuse`, `seize`, `freeze`. Rules in order, first match wins:

| R | Condition | Verdict | Failure this ordering prevents |
|---|---|---|---|
| R0 | Epoch check failed (roster unavailable/empty) | freeze | Unchanged, still FIRST: a daemon restart (G9) must never let any path below — including the new reclaim/rejoin — run against a blind roster. |
| R1 | No claim | claim | Fresh claim; mint inc + nonce, lineage=[sid]. |
| R2 | claim.session_id ∈ roster live-sids AND caller sid != claim.session_id | refuse | **The two-supervisor guard, preserved verbatim** (§6.1). Runs before every recognition rule: a live holder is never displaced by a booting body, nonce or no nonce. A rejoin attempt while the original body is still live is a live fork — refuse names it and directs the operator to keep one body. |
| R3 | caller sid == claim.session_id | **reclaim** | Self-recognition, at ANY heartbeat age: same inc, rotate nonce, refresh heartbeat, journal `BOOT` (body: `reclaim`). Fixes the 2026-07-18 wart (sup-boot refusing its own holder after an overnight gap). Nonce check: if the caller supplies a nonce and it is neither current nor prev → refuse per §5 rule 4 (a same-sid zombie must not launder itself through boot); supplied-and-matching or absent-with-fresh-context both reclaim — boot is the sanctioned recovery for a lost nonce, and rotation fences the loser either way. |
| R4 | caller nonce == claim.body_nonce (sid differs; R2 already proved the old sid is not live) | **rejoin** | Same inc, restamp sid, rotate nonce, append lineage, refresh heartbeat, journal `BOOT` (body: `rejoin from <old-sid>`). Closes the 2026-07-20 incident: a conversation fork whose predecessor is gone walks back into its own claim. prev_nonce is NOT accepted here — cross-sid grace would let a twice-forked lineage rejoin over a once-forked one; only the current nonce proves the freshest body. |
| R5 | Heartbeat unreadable | freeze | Unchanged: never seize on ambiguity. |
| R6 | Journal's latest entry names a fresher incarnation than the claim | refuse | Unchanged: transition in flight. |
| R7 | Heartbeat stale (> `SUPERVISOR_CLAIM_STALE_SECONDS`) | seize | Unchanged mechanics; new inc + nonce; lineage carried over. |
| R8 | Otherwise (roster-gone, heartbeat fresh) | freeze | Unchanged — daemon restart vs authorized stop stays ambiguous BUT the freeze text now names the levers: "same body, same sid → sup-boot reclaims; same body, new sid → sup-boot --nonce rejoins; operator authorized the stop → fleet sup-release." Freeze becomes a signpost instead of a dead end. |

`supervisor_claim_decision` stays a pure function (no IO); caller nonce and the
registry lookup (row 4 of §4, when `worker_name` lands) enter as parameters, keeping
the unit matrix (§11) exhaustive without a live fleet.

### 6.1 The two-supervisor roster guard, post-nonce

The guard today: `claim.session_id ∈ _roster_live_sids(entries)` → refuse
(`supervisor_claim_decision` ~:7147; `_roster_live_sids` ~:7100, including the
`state:"done"`-is-never-live rule from the 2026-07-19 posix finding). It MUST be
preserved: it is the only thing standing between a booting body and a live holder.

Post-nonce it is preserved **and becomes sound where it was vacuous**. Every
legitimate sid rotation now restamps `claim.session_id` at the rotation itself (§4
rows 3–7), so the guard always tests the CURRENT body's sid. Pre-nonce, after any
un-restamped rotation, the guard tested a retired sid that could never be roster-live
— structurally disarmed, which is exactly how C1's freeze/seize churn got past it.
The guard's mechanics do not change: same roster source (`claude agents --json
--all`), same liveness predicate, same position before every seize/recognition path
(R2 precedes R3/R4/R7). `sup-handoff-complete`'s `--expect-sid` dual verification is
likewise unchanged (§4 row 6).

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
  released-but-present claim, and R6 (journal names a fresher transition) plus the
  RELEASED entry make the next boot's evidence readable; the reverse order leaves an
  unexplained absence — the exact hand-`rm` illegibility this verb replaces.
  Refuse while a handoff is in flight (`HANDSHAKE` present, or latest journal entry is
  `HANDOFF-BEGIN` without a matching complete/abort): the successor limbo protocol
  (`sup-handoff-abort`) owns that state; two cleanup paths racing is how limbo
  successors leak.
- **Journal record.** `## <ts> RELEASED inc=<inc> sid=<caller-sid|operator>` with body
  = reason. The `sid=operator` literal (impossible as a real sid) makes human releases
  greppable. Written via `supervisor_journal_append` — single writer discipline holds
  because release IS a claim-holder-or-operator act.
- **What it fixes.** The operator-authorized `claude stop`: operator stops the body,
  runs `sup-release --reason "authorized stop"`, next `sup-boot` takes R1 (fresh
  claim) instead of R8 (freeze-page). The authorization finally has a place to live.

## 8. What the claim gates (adjudication item 2)

Complete verb enumeration at 771e4ee, by class:

- **Read-only, never gated** (views doctrine — no lock, no probe, no write): `home`,
  `knowledge`, `status`, `peek`, `result`, `wait`, `doctor`, `sup-status`.
- **Claim-gated today** (`_require_claim_holder` callers): `sup-checkpoint`,
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
Claude session (`current_caller_session()` non-None), and (iii) the caller fails the
§5 check, prints a one-line warning naming the holder and refuses unless `--anyway`
is passed. Humans at a shell are exempt (carve-out as in §7). Holder passes silently.
Failure modes, stated: (1) fail-open by design — a stale or corrupt claim disables
the fence, because fleet MUST remain drivable with no supervisor and a corrupt claim
must not brick every verb (views-never-quarantine doctrine, extended); a zombie
racing inside the fork-to-first-rotation window (§5) also passes, since it still
holds the current pair. (2) `--anyway` normalization: a body that habitually passes
`--anyway` re-opens the hole — same class as reflexive `--yes`, which D2 explicitly
forbids normalizing; doctrine + review-gate is the only backstop, and this spec says
so rather than pretending the flag is a wall. (3) Non-supervisor Claude sessions
running legitimate mutations (a worker spawning a sub-worker, WORKER-SUBAGENTS
intent) eat a warning + flag; acceptable friction today, revisit when that intent
lands. (4) One `read_incarnation()` per mutating verb — lock-free read of an
atomically-written file, no new contention.

**Recommendation: Model B, plus Model A's body-fencing at handoff-complete/seize.**
B closes the observed incident class (phantom mutations by a confused body); A's
fencing closes the beat-resurrection path C2 proved (a stopped body cannot be
fork-steered and its ScheduleWakeup dies with it, G7). Neither alone covers both.
The break lens reached the same "both" conclusion independently (C2, named fix).
Journal-only-forever (pure status quo) is rejected: the adjudication's own words —
"silence ships the zombie class."

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

Bounds, stated: (a) A worker spawned by a session that NEVER held the claim stays
foreign — lineage is claim history, not machine history. (b) Records predating
`spawned_by` stay foreign (unchanged fail-toward-asking). (c) Beyond the lineage
cap (32 rotations), `--yes` with eyes open — documented, rare, not normalized.
(d) The check runs only when a claim exists and the caller is its holder; it never
widens ownership for non-holders. No SPEC §4 field-immutability amendment is
required; SPEC §5.1's foreignness prose gains one sentence and must cite this spec.

## 10. Migration

- **v2 code, v1 file (no `schema` key).** Sid path only: `_require_claim_holder`
  accepts a sid-equal caller WITHOUT a nonce for a v1 claim (rule 3 of §5 applies
  only to schema ≥2), and every rotation-writing verb upgrades the file in place
  (add `schema:2`, mint `body_nonce`, `lineage=[session_id]`) under `fleet_lock`,
  printing the nonce. Upgrade-on-touch by the holder or the matrix — never by a
  view, never by a non-holder (a booting stranger upgrading a file it does not own
  would be a write outside the single-writer discipline).
- **v1 code, v2 file (worktree copies share one FLEET_HOME — real on this repo).**
  v1 `_require_claim_holder` reads only `session_id`, which v2 keeps current —
  sid-path verbs work. v1 write paths (`sup-boot` claim/seize, handoff-complete)
  write a v1-shaped file, silently DROPPING nonce/lineage/schema. Consequence: the
  claim degrades to sid-keyed until the next v2 touch re-upgrades; rejoin (R4) and
  lineage ownership (§9) are unavailable in the gap; nothing corrupts, nothing
  locks out. Stated, accepted: fleet is a single stdlib file — mixed versions are
  transient worktree states, not a deployment mode.
- **Journal format: UNCHANGED.** The entry header stays
  `## <ts> <KIND> inc=<inc> sid=<sid>` — `_SUPERVISOR_ENTRY_RE` (~:7039) is anchored
  (`\s*$`) and adding a header field would make every v1 parser read v2 entries as
  stray prose, silently emptying `latest_entry` and disarming R6. The nonce and
  rotation detail ride in the entry BODY (first line, `nonce: b-…`), greppable but
  not load-bearing for any parser. New kinds: `RELEASED` (§7) appended to
  `SUPERVISOR_JOURNAL_KINDS`; `parse_supervisor_journal` accepts unknown kinds
  already (regex is `[A-Z-]*`) — v1 readers render RELEASED entries fine.
- **HANDSHAKE**: gains `body_nonce`. v1 `sup-handoff-complete` ignores it (writes a
  v1 claim; degradation case above). v2 complete against a v1 handshake (no nonce):
  mint one at transfer — the successor learns it from its first `sup-boot` reclaim.

## 11. Test plan

Unit (pytest, SPEC §12; `supervisor_claim_decision` stays pure — the matrix needs no
live fleet):

- **Decision matrix, exhaustive**: every R0–R8 row × {nonce: current, prev, stale,
  absent} × {heartbeat: fresh, stale, unreadable} × {holder sid: live, gone, done-
  lingering (posix 2026-07-19 rule)} × {schema: 1, 2}. Assert verdict AND reason
  text (the reasons are operator UI; R8's signpost text is load-bearing).
- **Ordering proofs**: R2 beats R3/R4 (live holder never reclaimed-over or
  rejoined-over); R0 beats everything (blind roster freezes even a sid-matched
  reclaim); R4 rejects prev_nonce cross-sid.
- **§5 check**: grace-of-one accepts (sid, prev) once and logs `nonce-resync`;
  (sid, stale-nonce) refuses with the zombie text; nonce-absent on schema 2
  refuses; nonce-absent on schema 1 passes (migration).
- **Rotation atomicity**: fork-steer restamp writes registry + INCARNATION under one
  lock hold — inject a crash between them and assert the invariant that survives is
  detectable (claim names old sid, registry names new → next boot R4-rejoins).
- **sup-release**: holder path, operator path (env cleared), non-holder agent
  refused, handoff-in-flight refused, journal-then-delete order (crash injection
  between the two leaves a readable state).
- **§9**: lineage ownership passes `_worker_is_foreign` for holder + lineage sid;
  non-holder unchanged; cap overflow falls back to foreign.
- **Migration**: each cell of §10's 2×2, including the v1-writer downgrade round-trip.

Fault injections that would have caught the three incidents (each is a regression
test, named for its incident):

1. **`test_zombie_fork_fenced` (M-C).** Two callers, same sid, same nonce. A
   reclaims (rotates); B's `sup-checkpoint` with the old nonce → refused with the
   §5 rule-4 text. Pre-nonce code: B writes the journal — the test fails on v1
   semantics by construction.
2. **`test_first_beat_survives` (M-D gate).** Simulated fork-steer of a
   `worker_name` supervisor: registry restamp + claim restamp; new sid's
   `sup-heartbeat` passes; `supervisor_claim_decision` for a subsequent boot never
   returns seize or freeze within the beat cadence. Pre-nonce: heartbeat raises at
   the first beat.
3. **`test_conversation_fork_rejoins` (2026-07-20).** Claim holds old sid, holder
   gone from roster; caller has new sid + current nonce → rejoin; `sup-checkpoint`
   then passes with NO `--sid` override. Pre-nonce: refuse, workaround required.
4. **Wart regressions**: `test_stale_heartbeat_reclaim` (same sid, 19h-stale beat →
   reclaim, not refuse/freeze); `test_authorized_stop_release` (stop + release +
   boot → fresh claim, no freeze).

Integration (haiku worker, temp dir, per CLAUDE.md): one end-to-end fork-steer of a
registered body with claim restamp, and one `sup-release` from a plain (env-stripped)
shell. The dead-daemon variants of stop-based fencing (§8 Model A) are
interactive-session-only per the probe-context lesson — mark them as such; a `--bg`
runner cannot observe that path and a green run there proves nothing.

## 12. Open questions for the dual-lens review

1. **Grace-of-one (§5 rule 2)** trades one rotation of same-sid fencing delay for
   crash-lockout immunity. Is the trade right, or should grace require the
   `nonce-resync` event to be singular per rotation (replayable-once, then stale)?
2. **R3 reclaim with nonce absent** is the recovery path for lost context, and also
   the one place a same-sid zombie could re-legitimize before the true body's first
   rotation. Should reclaim-sans-nonce demand an operator ack when the heartbeat is
   FRESH (evidence someone was just alive)?
3. **Model B's fence on non-supervisor sessions** (§8 failure 3): warn+`--anyway`,
   or exempt registered fleet workers by registry lookup? The latter is cleaner and
   costs a registry read on every mutating verb from a session.
4. **Lineage cap 32**: arbitrary. Right bound, or should lineage compact to a set
   of spawned_by sids actually present in the registry at rotation time?
5. **`worker_name` reserved now (§3)** on the strength of three-tier item 10 —
   premature coupling, or correct pre-provisioning given this spec is that item's
   prerequisite?
