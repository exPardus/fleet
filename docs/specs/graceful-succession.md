# Spec: The graceful-succession signal — a fleet that says when it has no supervisor

**Status:** DRAFT, ready-for-gate. Nothing here is built. Written 2026-07-27 by the `succession-spec`
slice on `spec/succession-signal`, cut from `main` @ `2dec694`.

**Vantage.** Every receipt in this document is pinned `# at 2dec694` — the tip of `main` at the time of
writing — and is re-executed against that commit's materialised tree by `tools/verify_receipts.py`.
Nothing in `bin/fleet.py` was changed by this slice; the deliverable is this document.

**Reads as binding:** `docs/specs/claim-nonce.md` (§5.8–5.9, §6.1, §6.3, §6.4, §6.6, §7, §7.2, §17),
`docs/specs/three-tier-command.md` §10.1/§10.4/§11, `docs/specs/terminal-surface.md` (D1–D7, and D4's
REQUIREMENT/CURRENT-STATE split), `docs/specs/native-substrate.md` contract G11, and
`skills/fleet/supervisor.md`.

**Written on top of:** `fix/sup-release-tombstone` @ `25a6e1d` (worktree `C:/proga/fleet-tombstone`),
which is queued to merge into `main` ahead of this work. §5.1 states exactly which part of the problem
that branch closes and which part it does not.

---

## 0. The one-paragraph version

A supervisor that can no longer dispatch must produce a **fact a program can read**, not prose. This
spec specifies that fact as a **derived predicate** — `succession_needed` plus a closed-enum
`succession_cause` — computed from state already on disk, never stored, and therefore incapable of
going stale. It specifies how that predicate renders on the three pull surfaces the interface already
reads (statusline, `fleet sup-status`, `fleet doctor`), and it specifies one operator-run verb,
`fleet sup-recover`, that performs the whole succession maneuver without ever writing the claim — so
it cannot produce two live supervisors under any interleaving. **Nothing here injects anything into
any session** (terminal-surface D7), and **nothing here is automatic**: the operator typing the verb
*is* the human in the loop.

---

## 1. The incident, measured

On 2026-07-27 the supervisor `inc-20260727T024550Z-4743` hit the 200k context ceiling, attempted
`sup-handoff-begin` **three times**, and every successor was stillborn — registry row `working`,
0 turns, no transcript, forever. It released the claim cleanly and stopped. The fleet then sat with
every worker idle and nothing dispatching until a new body booted.

**The outage window, from the journal's own timestamps:**

| Event | Journal line |
|---|---|
| `RELEASED inc=inc-20260727T024550Z-4743` | `2026-07-27T04:00:41Z` |
| next `BOOT inc=inc-20260727T165406Z-e4e1` | `2026-07-27T16:54:06Z` |
| **elapsed** | **12 h 53 min 25 s** |

*(The brief that commissioned this spec says "roughly fifteen hours". The measured figure is 12 h 53 m.
The correction is recorded here rather than left to be re-derived; it does not change the argument.)*

The outgoing body's own account is journal entry **I-E**, and it is unusually candid. Two things in it
matter to this design and both are load-bearing:

- **The root cause of the *worker* dispatch failures is settled and is not a fleet defect at all:**
  four worktrees created fresh that incarnation had no `.claude/settings.local.json`, and `dontask`
  auto-denies. I-E names it, owns it, and reports it fixed.
- **The root cause of the *successor* stillbirths is NOT settled.** I-E's lead —
  `sup-handoff-begin` dispatches with `--permission-mode` defaulting to `dontask` and the successor's
  first instruction is a Bash `fleet sup-boot` — is flagged by its own author as *"a hypothesis, not a
  finding"*, with counter-evidence attached (that same author booted fine 50 minutes earlier through
  the same verb). **This spec does not assume the stillbirths are explained, and does not depend on
  them being explained.** That independence is deliberate: §7 specifies a verb whose success does not
  route through `sup-handoff-begin` at all.

**What made this an outage rather than an inconvenience.** `sup-release` recorded a free-text reason,
and last night's was accurate and detailed:

> `released cleanly: over 200k ceiling; handoff stillborn 3x (dontask permission lead); released so next boot reads clean per claim-nonce 6.3`

Every fact needed to act was in that string. **Nothing parses it.** The statusline rendered
`sup released` in the same hue and weight as `sup held`; `fleet doctor` reported
`[PASS] supervisor-claim`; `fleet sup-status` printed a correct, calm line. Every surface the interface
reads was honest and none of them was loud.

---

## 2. The hard constraint, restated before any design

**FLEET INJECTS NOTHING INTO ANY SESSION** — terminal-surface **D7**, ratified 2026-07-22. A
globally-enabled plugin's `SessionStart` hook fires in every session on the machine; this fleet's
operator gates, worker table and knowledge index leaked into unrelated repositories on this box. The
hook and the plugin `hooks` key were deleted and a test pins their absence.

Consequences this design accepts without argument:

- **No `SessionStart` hook, and no other surface that fires before the operator has opted into fleet
  work.** Every signal specified here is **PULL**: the operator's statusline, which they installed on
  purpose (`fleet init --statusline`, D6), or a verb they typed.
- **A worker-scoped hook in `worker-settings.json` would be permissible** — it is fleet's own dispatch
  surface and cannot escape to a foreign session. **This design uses none, and the reason is not
  restraint, it is physics:** contract G11 says a plan-limit wall fires **no Stop hook at all**
  (`docs/specs/native-substrate.md` G11: *"the rate-limit wall dies silently: no Stop hook fires,
  roster state is unaffected"*). A hook cannot observe the event this spec's harder half is about. If
  a later author reaches for a hook here, that is the fact to re-read first.
- **Succession is never automatic.** A supervisor that dispatches its own replacement is how two live
  supervisors over one GOALS.md happens, which is the single condition the whole claim system exists to
  prevent. §7.6 states the safety argument structurally rather than by promise.

---

## 3. What is already true — CURRENT STATE, measured

This section is descriptive. Every claim in it has a receipt in §10.

| Surface | What it does today with a fleet that has no supervisor |
|---|---|
| statusline | renders `sup released` / `sup none` in the ordinary command-tier hue — calm words (R1) |
| statusline | **drops every live supervisor-shaped body out of the worker buckets** (R2), so a `limited` supervisor body appears in no bucket at all |
| `status_snapshot()` | `supervisor` carries four keys: `goals_active`, `state`, `incarnation_id`, `heartbeat_age_seconds` (R3). No cause, no verdict |
| `fleet sup-status --json` | eight keys, none of which is a succession verdict (R4) |
| `fleet doctor` | 24 checks; `supervisor-claim` and `supervisor-handoff` are the only supervisor rows (R5) |
| `fleet doctor` | `limited-parks` is **always `ok=True`** (R6) — a limit-parked *supervisor* reads as `[PASS]` |
| `fleet respawn supervisor` | on a released claim, **refuses rc 2** and prints *"Boot a fresh body with `fleet sup-spawn --task <brief>`"* (R7) |
| `sup-release` | stores `reason` as free text on the claim (R8) |
| anywhere | **no `succession_needed` / `succession_cause` symbol exists** (R9) |

Two things in that table are the whole defect:

1. **The information exists and is calm.** `state == "released"` with `goals_active == True` is already
   in `status_snapshot()`. The projection distinguishes a released claim from a dormant fleet
   correctly — `_supervisor_chunk` returns `None` when GOALS are dormant, so `sup released` only ever
   renders while a supervisor is expected. **What is missing is not the datum. It is (a) urgency in the
   render and (b) a machine-readable verdict a doctor row can key on.** The brief asks whether a
   released claim with active GOALS is distinguishable from a fleet at rest: in the *snapshot*, yes,
   already; in the *rendering*, no. That is the honest split and it changes where the fix goes.
2. **`held` is not the same as healthy.** A claim `held` by a body that is limit-parked, dead, or
   simply silent renders `sup held` — the one calm word — and doctor passes.

### 3.1 A correction the brief needs, found while measuring

The brief states that `_ceiling_refuses_dispatch` *"already refuses `spawn`, `send` and `sup-spawn`"*.
At `2dec694` it refuses **five** call sites — `spawn`, `send`, `sup-spawn`, and `respawn` at two
sites, gated on `--task` (R10). The `respawn-ceiling` slice landed on `main` while the brief was being
written.

`skills/fleet/supervisor.md` is now **stale in the under-claiming direction** — it still reads *"It
does not yet cover `fleet respawn`; the operator ruled that a gap (2026-07-27) and ordered it
closed... Until that lands, respawn-with-`--task` over the ceiling is forbidden by doctrine with
nothing to refuse it."* It has landed. `skills/**` is outside this slice's scope fence, so this is
**filed, not fixed** (§9, amendment A4). It is recorded here because this project's docs reliably
drift in exactly that direction and the journal (G-X) names the pattern.

---

## 4. Part 1 — the succession-needed fact

### 4.1 The shape decision: DERIVE, do not store

**A stored flag is the wrong shape here, and the brief's own questions are why.** Three of them are
fatal to a stored flag and each is answered for free by a derived one:

| The brief asks | A stored flag | A derived predicate |
|---|---|---|
| *"What writes it when the body is parked and cannot act?"* | needs a third-party writer. A **view** writing it violates terminal-surface D1/D4 and invariant 6; a **mutating verb** writing it means the fact only appears when somebody runs a mutating verb — and during an outage nobody runs anything. | nothing writes it. It is computed at read time from files that already exist. |
| *"What clears the fact?"* | a clearing step somebody has to remember, on every one of `claim` / `seize` / `limit-transfer` / handoff-complete. A missed one is a permanent false alarm. | nothing clears it. The state that produces it stops existing, and the next read says so. |
| *"Can the fact go stale and lie?"* | yes, in both directions. | no. It has no persistence in which to be wrong. |

There is a fourth reason, and it is the one that would have mattered last night. **A stored flag would
naturally be cleared by `fleet sup-spawn`** — the verb that dispatches a successor. Last night that
would have been exactly wrong three times: a stillborn successor is dispatched, the flag clears, the
successor never takes a turn, and the fleet goes quiet again with the alarm silenced by the very act
that failed. **The derived predicate is immune to this by construction: it clears when a body
*claims*, not when a body is *dispatched*.**

> **DECISION D-GS1.** `succession_needed` is a derived projection, never a stored field. No new file, no
> new registry key, no new claim key. *(Design choice, mine, reasons above. §9 O1 records the one thing
> this costs.)*

### 4.2 The inputs — and there are exactly four, all already on disk

The predicate needs **nothing beyond state that already exists**, and nothing that is not already read
by a D4-compliant reader:

1. `supervisor/GOALS.md` — via `supervisor_goals_active()`; already read by `_supervisor_tier_snapshot`.
2. `supervisor/INCARNATION` — via `read_incarnation()`; already read by the same function. Supplies
   `state`, `released_at`, `heartbeat_at`, `session_id`, `incarnation_id`.
3. The claim holder's **registry record**, resolved through `_record_is_supervisor_claim_holder` over
   the sid union. Supplies `status` and `last_activity`. Read **lock-free and non-quarantining** via
   `_read_registry_readonly` — the same reader `_claim_holder_dead_note` already uses from inside
   `supervisor_status_line`, so the precedent and its D4 compliance are shipped, not proposed.
4. `SUPERVISOR_CLAIM_STALE_SECONDS` — an existing module constant (3600).

**No roster fetch. No subprocess. No lock. No write.** The one IO the gate at `claim-nonce` §7.2 pays
for — `_fetch_agents_roster`, ~1.7 s — is deliberately **not** in this predicate, because it would put
a subprocess on a statusline refresh path that terminal-surface D1 forbids one on.

### 4.3 The shape, exactly

`_supervisor_tier_snapshot()`'s dict gains three keys, and `status_snapshot()["supervisor"]` therefore
carries seven:

```python
{
  "goals_active": True,
  "state": "released",                 # unchanged: held | released | none | unknown
  "incarnation_id": "inc-20260727T024550Z-4743",
  "heartbeat_age_seconds": None,       # unchanged; None on a released claim BY DESIGN (CN §6.3)

  "succession_needed": True,           # NEW. True | False | None  -- tri-state, see §4.5
  "succession_cause": "released",      # NEW. closed enum, see §4.4
  "succession_age_seconds": 46405.0,   # NEW. float | None -- age of the condition, see §4.6
}
```

The derivation itself is a **pure function over two inputs and a clock**, so it has no IO of its own
and every caller supplies the reads it was already doing (invariant 9, one derivation many entry
points):

```python
def supervisor_succession_verdict(claim, holder_record, now=None) -> dict:
    """(needed, cause, age_seconds) from the claim and the holder's registry
    record. PURE: no file read, no lock, no roster, no subprocess.
    `holder_record` is None when the registry could not be read or no record
    carries the holder's sid -- that is a legal input, not an error."""
```

### 4.4 `succession_cause` — the closed enum, in precedence order

Evaluated top-down; the **first** matching row wins, so the most specific cause is the one published.

| # | Cause | Condition | `succession_needed` |
|---|---|---|---|
| 0 | `null` | `goals_active` is False | `False` |
| 1 | `"undecidable"` | the claim file is present and **unparseable** | `None` |
| 2 | `"no-claim"` | GOALS active, **no** claim file | `True` |
| 3 | `"released"` | `claim["state"] == "released"` | `True` |
| 4 | `"holder-limited"` | claim held; holder record `status == "limited"` | `True` |
| 5 | `"holder-gone"` | claim held; holder record `status` in `{"dead", "dead-suspected"}` | `True` |
| 6 | `"holder-silent"` | claim held; heartbeat age > `SUPERVISOR_CLAIM_STALE_SECONDS` | `True` |
| 7 | `null` | claim held, heartbeat fresh | `False` |

Notes that are part of the specification, not commentary:

- **Row 0 is how a resting fleet stays silent, and it is a shipped mechanism, not a new one.** An
  operator who is deliberately not running supervisor doctrine parks it by putting the literal token
  `SUPERVISOR-DORMANT` in `GOALS.md` (`supervisor_goals_active`), or by having no `GOALS.md` at all.
  This is the answer to *"when must the doctor check NOT fire"* (§6.3) and it required inventing
  nothing.
- **Row 6 is the always-decidable backstop and it is the heart of the parked-supervisor half.** See
  §4.7.
- **Row 5 folds `dead` and `dead-suspected` into one cause** and puts the exact registry status in the
  human-facing detail text. `dead-suspected` is fleet's own honest *"I believe this body is gone"*; the
  operator's action is identical either way, and two enum values for one action is a distinction a
  4 a.m. reader pays for and does not use.
- **Row 3 has no grace period, deliberately.** A `released` claim is the outgoing body's own signed
  statement that it is done. The planned in-band succession (`sup-handoff-complete`) **never passes
  through `released`** — it transfers the claim directly — so `released` while GOALS are active always
  means a body is owed. Adding a grace window here would have suppressed exactly last night's alarm.

### 4.5 Why `succession_needed` is a tri-state, and the failure direction

`None` means *"this predicate could not decide."* It is a **rendered word, never silence** — the day-5
lesson, and the same rule `_supervisor_tier_snapshot` already applies to `state: "unknown"`
(*"absence is not evidence on this substrate"*).

**The failure direction chosen, and its basis:**

- **Row 1 (`undecidable`) is treated as an alarm by `fleet doctor` — it FAILs.** The basis is that this
  condition **cannot flap.** Every writer of `supervisor/INCARNATION` writes it atomically, so the file
  is either parseable or absent; *absent* is row 2, which is decidable. A file that is present and
  unparseable means something outside fleet's writers touched it, and that is precisely doctor's stated
  job — *"fail on conditions that need a human."* It is therefore not a false-alarm generator, which is
  the property the named lesson is actually about.
- **Registry-side degradation fails QUIET, not loud.** If the registry cannot be read, `holder_record`
  is `None`, rows 4 and 5 cannot match, and the verdict falls through to row 6 (heartbeat) or row 7.
  The reason is asymmetry of blast radius: an unreadable registry already has its own loud surfaces
  (`[fleet]: registry unreadable`, `doctor`), and manufacturing a *second* supervisor alarm out of a
  registry fault would teach the operator that the succession row means "something is wrong somewhere",
  which is how a specific alarm becomes noise. **Row 6 is what keeps this safe:** a claim whose holder
  fleet cannot see is still caught within `SUPERVISOR_CLAIM_STALE_SECONDS` by the heartbeat alone.

> **DECISION D-GS2.** Undecidable **claim** → loud. Unreadable **registry** → quiet, bounded by row 6.
> *(Design choice, mine. §9 O2 records the residual.)*

### 4.6 `succession_age_seconds` — which clock, per cause

The brief's day-5 rule is that **a `released` claim never renders an age**. That rule exists because
`claim-nonce` §6.3 strips `heartbeat_at` from a released claim, so rendering a *heartbeat* age there
would invent staleness out of a correct stand-down. **This field does not violate that rule and must
not be confused with it:** it is not the heartbeat age, it is the age of the *outage condition*, drawn
from a different field with a different meaning.

| Cause | Clock | Rationale |
|---|---|---|
| `"released"` | `claim["released_at"]` | the moment the fleet lost its supervisor. This is the 12 h 53 m figure. |
| `"holder-silent"` | `claim["heartbeat_at"]` | identical to the existing stale-heartbeat age. |
| `"holder-limited"` / `"holder-gone"` | holder record `last_activity` | the last thing fleet actually observed. |
| `"no-claim"` | `None` | **nothing on disk dates this condition.** It renders with no age rather than with a guessed one. |
| `"undecidable"` | `None` | idem. |

> **BINDING for the build.** `succession_age_seconds` must be a **separate key** from
> `heartbeat_age_seconds`, and `heartbeat_age_seconds` stays `None` on a released claim exactly as it
> is today. A build that satisfies the age requirement by populating `heartbeat_age_seconds` from
> `released_at` re-introduces the §6.3 defect that `supervisor_status_line` carries a dedicated branch
> to avoid, and it would do so on the one surface every session reads.

### 4.7 The harder half: a supervisor parked on a plan usage limit

**The asymmetry, stated.** A limit wall is silent — contract G11: no Stop hook fires, the roster is
unaffected, and the only sanctioned evidence is a synthetic 429 record in the transcript. A parked
supervisor **can never be given a turn**, so nothing it could do is available. Whatever records the
fact cannot be something the supervisor does at park time.

**Who writes the input, and when.** Fleet already detects this and already has a name for it:
`_investigate_no_outcome` calls the module seam `_limit_scan_hook` (`transcript_limit_scan` in
production), and on a limit-shaped tail writes `status = "limited"` plus `limit_reset_at` /
`limit_kind` onto the record. The supervisor body is a registry row like any other
(`sup|<launch-id>|boot`), so this machinery already applies to it with no change.

**The actor is therefore: whichever caller next drives `recompute_worker_native`** — in practice
`fleet status` (bare), run by the interface, the operator, or any other body. **The moment is that
caller's invocation, not the park.**

**And that is a real hole, stated plainly rather than papered over: if nobody runs a recomputing verb,
the park is never written.** The statusline does not recompute — it must not, by D1 — so during a
genuine outage, where by definition nobody is driving the fleet, the registry can stay at whatever the
last recompute wrote. `holder-limited` is therefore **not** an always-fresh cause.

**What closes it: row 6, `holder-silent`.** A parked body cannot run `sup-checkpoint` or
`sup-heartbeat`, so its heartbeat ages. The heartbeat lives in the claim file, which the predicate
reads directly with no recompute, no registry and no roster. So:

> **A supervisor parked on a usage limit becomes visible within `SUPERVISOR_CLAIM_STALE_SECONDS`
> (3600 s) from the claim file alone — no recompute, no hook, no subprocess required. When a recompute
> has run, the cause is upgraded from `holder-silent` to `holder-limited` and the alarm arrives
> immediately instead.**
>
> **Worst case one hour. Best case immediate. The registry is what buys the difference, and its
> absence costs the operator the cause word, never the alarm.**

**The cost of row 6, owned.** `supervisor_status_line`'s own docstring records that its file-only
heartbeat read *"may false-fire on a live idle supervisor (accepted: the nag is advisory)"*. Row 6
promotes that same read from an advisory nag to a doctor FAIL, and inherits the false-fire. Two things
make that acceptable, and they are stated so a reviewer can reject them rather than have to find them:

1. A supervisor that has not beaten in an hour is **violating its own checkpoint discipline** —
   `skills/fleet/supervisor.md` requires the heartbeat kept younger than 60 minutes. The "false" alarm
   is a true alarm about a different obligation.
2. It **self-clears on the next beat**, and the remedy is one command the supervisor already owes
   (`fleet sup-heartbeat`). An alarm whose remedy is a shipped one-liner the actor should be running
   anyway is not the kind that trains an operator to ignore it.

### 4.8 What clears the fact — verified against all four boot routes

Nothing clears it. The condition stops existing. The brief specifically asks whether that is true for
`seize` and `limit-transfer` as well as `claim`:

| Route | What `sup-boot` writes | Predicate after |
|---|---|---|
| `claim` (fresh box, or a cleanly released predecessor) | a fresh `held` claim with a fresh `heartbeat_at` and the new body's `session_id` | row 7 → `False` ✓ |
| `seize` | ditto, plus a `SEIZED` journal entry | row 7 → `False` ✓ |
| `limit-transfer` | ditto. **The claim's `session_id` becomes the successor's**, so `_record_is_supervisor_claim_holder` now resolves to the *successor's* record — the parked predecessor's `limited` record is no longer the holder record and row 4 stops matching | row 7 → `False` ✓ |
| `resume` (own aged claim after a fork-steer) | restamped `heartbeat_at` | row 7 → `False` ✓ |
| `sup-handoff-complete` | the claim transfers to the successor with its own generation | row 7 → `False` ✓ |

**And the one that deliberately does NOT clear it: `fleet sup-spawn`.** Dispatching a body changes no
input to this predicate. The alarm stands until that body runs `sup-boot` and *claims*. **This is the
property that would have kept the alarm up through all three stillbirths**, and it is the single
strongest argument for D-GS1.

---

## 5. Part 3 (taken first, because Part 2 renders it) — folding the maneuver into one verb

### 5.1 What the tombstone branch already solves, and what remains

The three-step maneuver today, with the middle step that is undocumented folklore:

```
fleet sup-release   →   [the interface stops the retired body so its sid leaves the roster]   →   fleet sup-spawn
```

The middle step exists because **B6** (`claim-nonce` §6.1 rule 1) refuses a released claim whose
releaser is still roster-live, and a supervisor cannot therefore complete its own stand-down.

**`fix/sup-release-tombstone` @ `25a6e1d` closes exactly the middle step, and only for the
`sup-release` path.** `cmd_sup_release` now tombstones the releasing body's **own** registry record
(`status = "dead"`, the same field and literal `_cmd_kill_native` writes), and `_releaser_live_sids`
gains a first arm — `_releaser_body_is_tombstoned` — that dominates the roster. So
`_releaser_is_roster_live` is false **by construction** for the body that just released, and the next
`sup-boot` claims without anyone stopping anything. Order is release-then-tombstone inside one
`fleet_lock` section, so a process death between the two writes leaves today's B6 refusal, which
self-heals.

That is a genuine and well-built closure. **Four things it does not close, and they are what remains:**

| # | What remains | Why the tombstone cannot reach it |
|---|---|---|
| **R-a** | **The handover of intent across the tier boundary.** `sup-release` ends the supervisor's session; `sup-spawn` must be run by a *different* tier, later, by someone who noticed. Nothing carries the intent across that boundary. | The tombstone makes the *mechanism* work. Nothing makes the *interface* act. **This is the 12 h 53 m gap** — the release was clean, the mechanism was fine, and no one ran the second command. |
| **R-b** | **The already-gone case.** No `sup-release` ran, so no tombstone exists. The claim is `held` with an aging heartbeat, and `sup-boot` verdicts `refuse` (holder roster-live) or **`freeze` for up to 3600 s** (roster-gone, heartbeat fresh). | The tombstone is written *by* `sup-release`. A body that died cannot write one. |
| **R-c** | **The released-but-untombstoned case.** A release performed by pre-tombstone code, or one whose `_tombstone_releasing_body` legitimately abstained (identity `UNRESOLVED`/`AMBIGUOUS`, or an unreadable registry — all three arms print and return `None`). B6 refuses and the manual middle step is back for that release. | By design: the tombstone abstains rather than guessing, which is correct, and leaves the operator holding the step. |
| **R-d** | **`sup-spawn` requires `--task <text\|@file>`.** After an unplanned death the interface must author a campaign brief from nothing, at whatever hour the outage happened. | Out of the tombstone's scope entirely. |

### 5.2 `fleet respawn supervisor` is already most of this verb — for one state

This must be said before specifying anything new, because a spec that invents a verb next to an
existing one that does the same job is how a fleet ends up with two half-working paths.

`fleet respawn supervisor` (three-tier §10.4, council-ruled 4–0) already performs:

> resolve → refusal matrix → release-steer → bounded wait → stop + `"stopped"` tombstone →
> **caller-side B6 gate** → fresh gen-0 body

That **is** the whole maneuver, in one operator command, with a two-bodies gate — for a claim holder
that is **alive and steerable**. On a released claim it refuses rc 2 and hands the operator back to
`sup-spawn` (R7). On a `limited` holder it refuses rc 2 by ruling 2 and prints every cheaper escape.
On the `freeze` window it never gets that far.

> **So the gap is not "there is no verb". It is: the existing verb covers the state where the body can
> still cooperate, and every state in §5.1's R-a…R-d is a state where it cannot.**

### 5.3 The verb

```
fleet sup-recover [--task <text|@file>] [--force-frozen] [--yes] [--nonce N] [--json]
```

**Name.** `sup-recover` over `sup-succeed` (which a tired reader parses as "the supervisor succeeded")
and over `sup-replace` (which reads as though it replaces GOALS). It names the situation — an outage —
which is also what distinguishes it from the planned routes.

**It is the single front door.** The operator does **not** classify the outage; the verb resolves the
state and delegates. That is the whole of "fold the maneuver into one verb": not a new mechanism, a
**dispatcher over the mechanisms that exist**, plus the one arm (R-c) that nothing owns today.

### 5.4 The arms

Resolved under one `fleet_lock` for the read + the arm-3 mutation; the lock is **released before any
dispatch**, per F4 doctrine (never hold `fleet.lock` across a subprocess).

| Arm | State | Action | rc |
|---|---|---|---|
| **0** | the **caller holds the claim** | **REFUSE.** See §7.6. | 2 |
| **1** | GOALS dormant or absent | **REFUSE:** *"GOALS.md is dormant or absent — there is no supervisor doctrine to recover. Park is deliberate (`SUPERVISOR-DORMANT`); remove the token to resume."* | 2 |
| **2** | claim present but **unparseable** | **REFUSE, never decide blind:** the same posture `_resolve_supervisor_lifecycle_target` takes and the same posture `sup-boot` calls `freeze`. Names `fleet doctor`. | 3 |
| **3** | claim `held`, holder **alive and steerable** | **DELEGATE to `_cmd_respawn_supervisor`'s choreography verbatim.** No second implementation. | its own |
| **4** | claim `released`, releaser **tombstoned or roster-gone** | dispatch a gen-0 body (`_dispatch_supervisor_body`). Nothing to stop. | 0 |
| **5** | claim `released`, releaser **still roster-live and untombstoned** (R-c) | **stop that session, tombstone its record, then dispatch.** This is the manual middle step, performed in-fleet. | 0 |
| **6** | claim `held`, holder record `limited` | dispatch. `sup-boot` will verdict `limit-transfer`. | 0 |
| **7** | claim `held`, holder roster-gone, heartbeat **stale** | dispatch. `sup-boot` will verdict `seize` and journal `SEIZED`. | 0 |
| **8** | claim `held`, holder roster-gone, heartbeat **fresh** — the **freeze window** | **REFUSE by default.** Print the G9 ambiguity in full and name `--force-frozen`. | 2 |
| **9** | no claim at all | dispatch. `sup-boot` verdicts `claim`. | 0 |

**Arm 8 is the only place a human judgement is required, and the verb says so rather than guessing.**
The `freeze` verdict exists because roster-gone with a fresh heartbeat is genuinely ambiguous between
"the body died" and "the daemon restarted" (G9). Auto-resolving it is how a live supervisor gets a
rival. `--force-frozen` is the operator asserting they have checked; the flag exists so the assertion
is typed, not inferred.

**Arm 5's stop is the only mutation `sup-recover` performs to another body**, and it is
target-restricted by construction: the sid it stops is `claim["released_by_sid"]` and the record it
tombstones is the one whose `_record_sids` contains it. There is no name argument by which the stop
could be aimed elsewhere — the same structural property `_tombstone_releasing_body` relies on.

### 5.5 `--task`, and R-d

`--task` is **optional**. When omitted, `sup-recover` composes the gen-0 campaign from durable state:
the standing boot ritual (which `sup-spawn` already self-composes), plus a pointer — not a paste — to
`supervisor/GOALS.md` and to the journal tail. **A pointer, because the successor's first act is
`sup-boot`, which prints the whole bundle anyway;** pasting it into the task file would duplicate it
and put a second, staler copy in a file on disk.

> **BINDING.** `sup-recover` must **not** copy the outgoing body's `sup-release --reason` text into the
> successor's task as though it were an instruction. It is a free-text note written by a body under
> context pressure, and §4 exists precisely because it is not a fact. It may be **quoted, attributed
> and labelled** as the predecessor's last words. It may not be presented as a brief.

### 5.6 What it prints

```
SUP-RECOVER <arm>: <one line naming the state it resolved>
  cause         : released
  since         : 2026-07-27T04:00:41Z (12h53m)
  predecessor   : inc-20260727T024550Z-4743  (reason: "<verbatim, quoted, attributed>")
  action        : dispatching gen-0 body sup|<launch-id>|boot
SUP-RECOVER-DISPATCHED <name> sid=<sid>
  next          : that body's first act is `fleet sup-boot`. It holds NO claim yet.
                  Confirm with `fleet sup-status`; if it is still `working` with 0 turns
                  after 300s it is stillborn -- `fleet peek <name>` and see §5.7.
```

Terminal contracts, grep-able, on **stdout**, mirroring `SUP-KILL-*` / `SUP-RESPAWN-*`:
`SUP-RECOVER-DISPATCHED`, `SUP-RECOVER-REFUSED`, `SUP-RECOVER-HALTED`.

> **The `next:` block is not decoration.** It is the countermeasure to the failure that actually
> happened: a dispatched body reads as success from every surface fleet has. **`sup-recover` exits 0
> when a body has been dispatched, not when a supervisor exists**, and its own output says so in those
> words. Anything stronger would be the verb asserting something it has not measured — and per §4.8
> the `succession_needed` predicate stays `True` until that body claims, so the operator's other
> surfaces do not go quiet either.

### 5.7 Relationship to `sup-handoff-*` — settled, not left ambiguous

Three routes, **disjoint by the outgoing body's liveness**, which is the only classifier that does not
require judgement:

| Route | Precondition on the outgoing body | Driven by | Status |
|---|---|---|---|
| `sup-handoff-begin` / `-complete` | **healthy and in-band.** It can mint a token, poll, and complete. | the outgoing body | **PREFERRED.** In-band planned succession. Unchanged by this spec. |
| `fleet respawn supervisor` | **alive and steerable**, but the interface wants the swap. | the interface | **UNCHANGED.** `sup-recover` arm 3 delegates to it. |
| **`fleet sup-recover`** | **cannot participate** — released, parked, dead, silent, or absent. | the interface | **FALLBACK** to the first, **peer** to the second. |

> **Stated in one sentence, because an ambiguous relationship between two succession paths is how a
> fleet ends up with neither working: `sup-recover` is a FALLBACK to `sup-handoff-*` and a PEER to
> `respawn supervisor`. It is never a replacement for either.** It does not deprecate the handoff
> path, does not change its verbs, and does not compete with it: by the time any `sup-recover` arm
> matches, the handoff path has either succeeded (and there is nothing to recover) or is not available
> (and there is nothing to compete with).

**One interaction must be refused explicitly:** a claim carrying `handoff_token_hash` has a
token-verified successor possibly mid-boot. `_supervisor_lifecycle_interaction_refusals` already
refuses `kill`/`respawn` on exactly that marker. **`sup-recover` adopts the same refusal**, with the
same escapes (`sup-handoff-complete` / `sup-handoff-abort`), because dispatching through a live
handoff races the successor — which is the two-bodies hole, arriving by a new door.

### 5.8 The safety argument — why one verb ending in a body is allowed and a self-triggering loop is not

**The distinction the brief asks to be made explicit:**

> A verb that ends in a fresh supervisor body is acceptable **because a human typed it.** The operator
> typing `fleet sup-recover` *is* the human in the loop; the succession is not automatic, it is
> one-command. What is forbidden is a **self-triggering** path — a supervisor, a hook, a scheduler, or
> a view that starts a body with no human in the loop. That is not a matter of degree: a supervisor
> dispatching its own replacement produces two live supervisors over one GOALS.md, which is the one
> condition the entire claim system exists to prevent.

**Enforced, not promised, by four structural facts:**

1. **Arm 0 refuses the claim holder, on sound grounds.** The refusal is keyed on
   `_caller_holds_supervisor_claim(caller) is True` — a fact proven from the claim and the registry,
   never inferred. This matters: `claim-nonce` §17 (RATIFIED) says *"inference may select the SUBJECT
   of a measurement, but may not supply the GROUNDS of a refusal"*, and specifically that
   `FLEET_WORKER` **presence** is unsound evidence because donation can only ever add a stamp. **So
   this verb may not refuse on `FLEET_WORKER`.** Claim-holdership is the sound test, and it is exactly
   the right one: the body this must never run is the one holding the claim.
2. **No fleet surface invokes it.** It appears in no hook (the manifest declares none — D7), no
   scheduled task, and no view path. Its slash command is a **prompt template the model executes via
   Bash**, never inline `` !` `` — terminal-surface D3, lint-enforced by `tests/test_terminal_surface.py`,
   because inline exec skips the permission prompt.
3. **The detector may not call it.** The `fleet doctor` row of §6.3 and the statusline of §6.1 **flag**
   the condition and never act on it. This is invariant 1 in its shipped spelling — the same rule that
   keeps `resume-eligible` a rendered word rather than a launch.
4. **It never writes `supervisor/INCARNATION`.** See §7.6.

**Detection where enforcement is not possible.** A non-holder worker session *could* run
`sup-recover` — fleet's §7 gate is a knowingly-bypassable speed-bump by ratified operator decision
(option (b), 2026-07-23), and no sound test distinguishes an interface session from a worker one.
So: the journal entry `sup-recover` writes **records the caller sid**, making it detectable after the
fact. Stated rather than hidden — this design does not claim an enforcement it cannot deliver.

### 5.9 The races, walked

**The invariant that makes all of these boring: `sup-recover` never writes the claim.** In every
dispatching arm it starts a body and lets `sup-boot` make the claim decision under `fleet_lock` —
reusing the code's own doctrine, *"Fleet never decides claim-holdership from a respawn flag."*

| Interleaving | Outcome |
|---|---|
| **Two operators run `sup-recover` concurrently.** | Both dispatch. Both bodies run `sup-boot` under the lock. The first claims; the second gets `refuse` (§6.1 rule 2, holder roster-live) and terminates per the boot ritual. **One supervisor, one wasted body.** Two live supervisors cannot result, because holdership is adjudicated under the lock by a verb neither dispatcher controls. |
| **`sup-recover` arm 5 stops the releaser while it is mid-`sup-release`.** | Arm 5 fires only on an already-`released` claim, and `cmd_sup_release` commits the claim write *before* the tombstone, inside one lock section. So the release is durable before arm 5 can observe it. |
| **Arm 3 delegates the release-steer; the holder self-releases first.** | `_await_claim_released` polls and succeeds immediately. Unchanged from today's `respawn supervisor`. |
| **`sup-recover` dispatches (arm 6); the parked predecessor's limit resets and it wakes.** | The successor took the claim by `limit-transfer`. The woken predecessor's next `sup-*` verb fails the continuity gate (rc 4) and its instruction (§5.7 of claim-nonce) is to stop and escalate, never to seize. Shipped behaviour. |
| **Arm 8 forced with `--force-frozen` on a holder that is actually alive but silent.** | **The one real residual.** The successor seizes; two bodies both believe they hold the claim. The claim nonce is exactly the mechanism for this: the successor mints a new generation, the old body's next verb presents a stale one and is **REFUSED (rc 4)**, and a `refused` record inside the 24 h window makes `doctor supervisor-claim` **FAIL** with *"a second body of this lineage may be acting"*. **Divergence is detected and bounded, not prevented** — which is what claim-nonce claims for itself, and this verb neither strengthens nor weakens it. |
| **`sup-recover` runs while a handoff token is minted.** | Refused (§5.7). |

---

## 6. Part 2 — the pull surfaces, in priority order

### 6.1 The statusline

**The rule, in one line: `sup held` with a live holder is the only calm word. Every other state is an
outage while GOALS are active.** Today three of the four shipped labels render calm (R1), and a fourth
state — `held` with a limited or dead holder — renders calm too.

| `succession_cause` | today | specified |
|---|---|---|
| `null` (healthy) | `sup held` | `sup held` — **unchanged**, including the ` 2h` age when the heartbeat is stale |
| `"released"` | `sup released` | `sup DOWN released 12h` |
| `"no-claim"` | `sup none` | `sup DOWN no-claim` |
| `"holder-limited"` | `sup held` | `sup DOWN limited 3h resets 14:20` |
| `"holder-gone"` | `sup held` | `sup DOWN gone 40m` |
| `"holder-silent"` | `sup held 2h` | `sup DOWN silent 2h` |
| `"undecidable"` | `sup ?` | `sup ?` — **unchanged.** Already the word for "cannot read the claim" |
| GOALS dormant/absent | *(silent)* | *(silent)* — **unchanged** |

Binding render rules:

- **`DOWN` is painted in the reserved alarm hue** — the same bold red as the `N bodies` second-body
  alarm. This is a **deliberate reuse of one hue for two conditions**, against the line's usual
  one-hue-per-status rule, and the reason is that they are the same class of event: the command tier is
  not functioning and the operator must act now. Inventing a second red is a distinction the eye cannot
  make on a one-line surface. **They can co-occur** (`sup DOWN released 12h  2 bodies`), and the order
  is fixed: the tier field first, the body count second, exactly as the lead currently orders them.
- **The cause word is ASCII and one token.** Terminal-surface §4.3: the line is pure ASCII by
  construction, because a cp1252 console cannot encode glyphs and the exit-0 guard would swallow the
  `UnicodeEncodeError`, leaving a permanently blank statusline.
- **The age is `succession_age_seconds`, never `heartbeat_age_seconds`** (§4.6), and a cause with no
  clock renders with no age.
- **`resets HH:MM` is appended only on `holder-limited`**, reusing `_reset_clock` and the existing
  `limited` bucket convention. It is a flag; **the statusline never launches a resume** (invariant 1).
- **View doctrine is untouched and this is checkable:** everything above is a projection of
  `fleet.status_snapshot()`. The one registry read is `_read_registry_readonly` — lock-free,
  non-quarantining, the reader `_claim_holder_dead_note` already uses on this exact path. **No lock, no
  probe, no write, no subprocess, exit 0 on every path.**

**One shipped behaviour this changes, named so a reviewer can weigh it.** `_supervisor_chunk` today
appends an age only for `state == "held"`. The specified form appends one for `released`, `limited`,
`gone` and `silent`. If a test pins *"a released claim renders no age"*, it is pinning the §6.3
heartbeat rule and **must be re-pinned to that rule specifically** — *no `heartbeat_at`-derived age on
a released claim* — not deleted. Deleting it would drop the guard that keeps the §6.3 defect closed.

**What is deliberately NOT changed.** A live supervisor body still leaves the worker buckets (R2), so
a `limited` supervisor still appears in no `lim` bucket. Putting it back would double-count it — it is
already named by the tier field, now with its cause — and would break the tier split terminal-surface
§4.3 introduced.

### 6.2 `fleet sup-status`

**`--json` gains one top-level key. Its name is `succession`.**

```json
"succession": {
  "needed": true,
  "cause": "released",
  "since": "2026-07-27T04:00:41Z",
  "age_seconds": 46405.0,
  "detail": "claim inc-20260727T024550Z-4743 was released 12h53m ago and no body has claimed since"
}
```

**Top-level, not nested under `incarnation`**, and that placement is a requirement rather than taste:
`incarnation` is `_project_claim(claim)` — a redaction *projection of a file* (§5.8). A derived verdict
placed inside it would teach every reader that the claim file contains a field it does not.

**The human form gains one line, printed FIRST**, ahead of the `supervisor:` line, because the surface
an operator types mid-incident must lead with the verdict:

```
SUCCESSION NEEDED (released): claim inc-20260727T024550Z-4743 released 12h53m ago; nothing holds it.
  recover with: fleet sup-recover
supervisor: inc-20260727T024550Z-4743 RELEASED at 2026-07-27T04:00:41Z by sid=3430c962-... (over 200k ceiling; handoff stillborn 3x ...) -- no holder; `fleet sup-boot` claims fresh
```

- When `needed` is `False`, **no line is printed.** A health surface that prints a line saying nothing
  is wrong is how the operator learns to skip it.
- When `needed` is `None`, the line reads `SUCCESSION UNDECIDABLE: ...` — a rendered word, never
  silence.
- `sup-status` remains a **read-only view**: no lock, no probe, no write (R4's function already carries
  that contract, and it is one of only three verbs measured lock-free and non-quarantining in
  terminal-surface's D4 receipts). This addition must not change that.

### 6.3 The `fleet doctor` check

**Name: `supervisor-succession`.** A 25th check, appended to `check_calls` after
`_doctor_check_supervisor_claim`.

`fleet doctor` prints exactly two verdicts — `[PASS]` and `[FAIL]` — so **this spec does not specify a
`WARN`**. *(The brief asks for "PASS/FAIL/WARN wording"; there is no WARN tier in `cmd_doctor`.
Inventing one would mean changing every check's contract. The third tier is carried, as the shipped
rows already carry it, by a `NOTE:` prefix inside the message — the convention
`_doctor_check_supervisor_claim` and `_doctor_check_limited_parks` both use.)*

| Condition | Verdict | Message |
|---|---|---|
| GOALS dormant or absent | `[PASS]` | `GOALS absent or dormant -- no supervisor expected` — the same wording family the `supervisor-claim` row already uses |
| `needed is False` | `[PASS]` | `claim <inc> held, heartbeat <n>m ago -- a supervisor is on duty` |
| `needed is True` | **`[FAIL]`** | `SUCCESSION NEEDED (<cause>): <detail>. Nothing is dispatching. Recover with \`fleet sup-recover\`.` |
| `needed is None` | **`[FAIL]`** | `supervisor/INCARNATION is present but unparseable, so succession cannot be decided. Never decide blind: inspect the claim file.` |
| the check itself raises | `[FAIL]` | handled by `cmd_doctor`'s existing per-check isolation wrapper |

**When it must NOT fire — the requirement the brief asks for by name:**

1. **A resting fleet never FAILs.** Row 0 of §4.4: GOALS absent, or `SUPERVISOR-DORMANT` present. This
   is a shipped operator lever with a shipped token; nothing new is needed, and a fleet that has never
   run supervisor doctrine sees `[PASS]` forever.
2. **A healthy fleet with no campaign never FAILs.** `held` + fresh heartbeat is row 7.
3. **A handoff in flight never FAILs.** The claim stays `held` with a fresh heartbeat throughout —
   `sup-handoff-complete` transfers it directly and it never passes through `released`.
4. **The window between `sup-recover` dispatching and the successor claiming DOES FAIL, deliberately.**
   That is not a false alarm: no body holds the claim in that window, and last night proved that
   window can be permanent. It clears the moment `sup-boot` writes a held claim — typically under a
   minute, and never at all if the successor is stillborn, which is precisely when the operator needs
   to still be told.

**Why this row can FAIL where `supervisor-claim` stays advisory.** `supervisor-claim` was deliberately
kept `ok=True` because *"the nag is advisory"* and only one condition (a `refused` record) flips it.
This is a different question: not *"is the claim tidy"* but *"can this fleet dispatch at all"*. A fleet
that cannot dispatch is exactly the condition doctor's own contract describes — *fail on conditions
that need a human*. The two rows stay separate rather than merged, because they answer different
questions and merging them would make a claim-hygiene note able to silence an outage.

---

## 7. Answers to the brief's direct questions, collected

**Q. Is a released claim with active GOALS and no live body distinguishable from a fleet at rest?**
In the **snapshot**, already yes — `goals_active` gates the whole chunk and a dormant fleet renders
nothing. In the **rendering**, no: `sup released` and `sup held` are the same kind of calm word. So the
defect is in the render and in the absence of a machine-readable verdict, not in the data. What makes
it distinguishable is `succession_needed`/`succession_cause` (§4.3–4.4), and **the predicate needs
nothing beyond state already on disk** — four inputs, all already read by D4-compliant readers (§4.2).

**Q. What clears the fact?** Nothing. The condition stops existing when a body **claims**. Verified
across `claim`, `seize`, `limit-transfer`, `resume` and `sup-handoff-complete` (§4.8). `sup-spawn`
deliberately does **not** clear it.

**Q. Can the fact go stale and lie?** Not in the direction that matters — it has no persistence. The
failure direction chosen is D-GS2: an undecidable **claim** fails LOUD (it cannot flap), an unreadable
**registry** fails QUIET and is caught within one hour by the heartbeat row (§4.5, §4.7).

**Q. What writes it when the body is parked and cannot act?** **Nothing writes it.** The *input* that
names the cause (`status: "limited"`) is written by `_investigate_no_outcome`'s G11 transcript-tail
scan, by whichever caller next drives `recompute_worker_native` — in practice `fleet status`. If nobody
ever runs one, that cause never fires, **and that is why the design does not depend on it**: row 6
(`holder-silent`) reaches the same alarm from the claim file alone, bounded by
`SUPERVISOR_CLAIM_STALE_SECONDS` (§4.7).

**Q. Which part of the three-step problem does the tombstone already solve?** The middle step, for the
`sup-release` path — completely and well. R-a…R-d in §5.1 are what remain.

**Q. Is `sup-recover` a replacement, a fallback, or a peer?** A **fallback** to `sup-handoff-*` and a
**peer** to `respawn supervisor`, disjoint by the outgoing body's liveness (§5.7).

---

## 8. Test obligations (the builder writes these; this spec does not)

Enumerated so the gate has something to check the build against.

**The predicate** — `supervisor_succession_verdict` is pure, so every row of §4.4 is a table test with
no fixture: all seven causes, precedence between rows 4/5/6 when several conditions hold at once, and
`holder_record=None` falling through to row 6 rather than to a crash.

**Clearing** — one test per boot route in §4.8, asserting `needed` is `False` after
`write_incarnation`. **And the one that is the point: `sup-spawn` does NOT clear it.** That test is the
regression guard for last night.

**View doctrine** — the D4 receipt harness in `terminal-surface.md` is parametrised over surfaces.
`sup-recover` must be added to the **quarantine** table (it is a mutating verb; it may quarantine) and
the statusline/`sup-status` rows must stay `survives` / `lock-free` with the new fields present.

**Statusline** — every cause renders its specified word; `DOWN` and `N bodies` co-occur in the fixed
order; the line stays pure ASCII; **zero subprocesses**; exit 0 including on a forced exception; and a
released claim still renders **no `heartbeat_at`-derived age** (the §6.3 guard, re-pinned per §6.1, not
deleted).

**Doctor** — FAIL on each `needed is True` cause; PASS on dormant GOALS; PASS on a healthy claim; FAIL
on `undecidable`; **and the anti-false-alarm test: a fleet with `SUPERVISOR-DORMANT` never FAILs this
row however broken the rest of the supervisor state is.**

**`sup-recover`** — one test per arm; arm 0 refuses the claim holder; arm 8 refuses without
`--force-frozen`; the handoff-in-flight refusal; **arm 5 tombstones only the releaser's own record**;
and the concurrency test: two dispatches, one claim, the loser terminates.

**Fault injections the gate should demand come back RED** — (i) clear the flag on `sup-spawn`;
(ii) render `succession_age_seconds` into `heartbeat_age_seconds`; (iii) make the statusline take
`fleet.lock` to read the holder record; (iv) let arm 0 key on `FLEET_WORKER` instead of
claim-holdership; (v) let `sup-recover` write `supervisor/INCARNATION` directly instead of dispatching;
(vi) make `needed is None` PASS.

---

## 9. Part 4 — what I could not settle

Split as the brief requires: **design choices I made** (with reasons, overturnable by the gate) versus
**ratifications the operator owes** (which I may not make).

### 9.1 Design choices — mine, and why

| # | Choice | Reason | How to overturn |
|---|---|---|---|
| **O1** | **Derived, never stored** (D-GS1). | §4.1. The cost: the predicate is only as fresh as its inputs, and two of its five causes read a registry field whose freshness depends on a recompute having run (§4.7). | Show a consumer that needs the fact when no reader is running. I could not construct one: every consumer of this fact **is** a reader. |
| **O2** | **Undecidable claim → FAIL; unreadable registry → quiet** (D-GS2). | §4.5. | Show that an unparseable `supervisor/INCARNATION` can occur transiently. If it can, this flips. |
| **O3** | Row 6 (`holder-silent`) promotes an **admittedly false-fireable** read from advisory nag to doctor FAIL. | §4.7. It is the only always-fresh detector of the silent half, and its "false" alarm is a true alarm about checkpoint discipline with a one-command remedy. | This is the most attackable decision in the document and the gate should attack it. |
| **O4** | `dead` and `dead-suspected` fold into one cause. | §4.4. Same operator action; the exact status is in `detail`. | Trivially reversible — one enum value. |
| **O5** | The alarm hue is **reused** for `sup DOWN` and `N bodies`. | §6.1. Same class of event; a second red is indistinguishable on one line. | A reviewer with a stronger claim about colour budget. |
| **O6** | Verb named `sup-recover`; `--task` optional. | §5.3, §5.5. | Naming is cheap to change before build and expensive after. |
| **O7** | `sup-recover` **never writes the claim**; it dispatches and lets `sup-boot` adjudicate. | §5.9. This is what makes the two-bodies argument structural. | Do not overturn without replacing the safety argument. |
| **O8** | **No worker-scoped hook.** | §2 — G11 says a limit wall fires no hook, so a hook cannot see the event. | Only by falsifying G11. |
| **O9** | The doctor row FAILs during the dispatch→claim window. | §6.3 note 4. That window was permanent three times last night. | If stillbirths are root-caused and fixed, revisit. |

### 9.2 Ratifications the operator owes

> **`docs/specs/claim-nonce.md` §7 is OPERATOR-OWNED, and the supervisor may not ratify a narrowing of
> an operator-owned section.** Where this design needs one, it is marked below in those words and left
> undone.

| # | What is owed | Owner | Why I could not settle it |
|---|---|---|---|
| **A1** | **The §7.2 disarm table is now incomplete about shipped code.** `fix/sup-release-tombstone` adds a third disarm (releaser tombstoned) and the ratified table says *"releaser roster-**LIVE** → **ARMED, unconditionally**"*. The tombstone slice reported this and correctly refused to edit it. **This spec builds on that branch, so it inherits the debt and restates it rather than assuming it discharged.** | **operator** — §7 is operator-owned; **the supervisor may not ratify a narrowing of an operator-owned section** | Not mine to ratify. `docs/OPERATOR-GATES.md` already records *"an in-fleet disarm path is owed"*, so this discharges scheduled work rather than inventing a narrowing — but the shape still needs the tick. |
| **A2** | **`claim-nonce` §6.3's post-release key set does not say what happens to `handoff_pending` and `handoff_token_hash`.** It enumerates seven keys kept and six removed; these two are in neither list. `sup-recover` §5.7 refuses on `handoff_token_hash`, so its behaviour after a release depends on an unspecified key. | **operator** (§6.3 is a ratified D-decision) | A released claim that still carries a minted token means a superseded successor could in principle still validate against it. I could not determine from the text whether that is intended. **Flagged as a live ambiguity, not assumed either way.** |
| **A3** | **A 25th doctor check that FAILs changes `fleet doctor`'s exit code contract for a new class of condition.** `docs/SPEC.md` §13 records the doctor roster and a check count. | operator / doc-sync | Adding a FAIL-capable row is a policy change about what makes doctor red, and the count in SPEC §13 is a ratified number. |
| **A4** | **`skills/fleet/supervisor.md` is stale about the respawn ceiling** (§3.1) — it says the ceiling does not cover `respawn`; at `2dec694` it does, at two sites, gated on `--task` (R10). | doc-sync; **outside this slice's scope fence** (`skills/**`) | Filed, not fixed. Recorded because it is an under-claim, the direction this project's docs reliably drift. |
| **A5** | **The statusline's `released`-renders-no-age pin** (§6.1) may need re-pinning rather than deleting. Whether a test pins it today, I did not verify. | builder + gate | I did not read the statusline test suite; asserting either way would be a claim I had not measured. **Stated as unverified.** |
| **A6** | **`sup-recover`'s exact rc values.** This spec reuses `SupervisorLifecycleRefusal`'s rc 2 / rc 3 split and `sup-boot`'s rc 4 for continuity refusals. I did not re-derive every constant. | builder | Named so the build confirms rather than infers. |

### 9.3 Two things I could not determine at all, stated as such

- **Why the three successors were stillborn.** I-E's `dontask` lead is explicitly a hypothesis with
  attached counter-evidence, and I did not test it — this slice's fence forbids touching the live claim
  or any live worker. **This spec is designed not to need the answer:** `sup-recover` routes through
  `_dispatch_supervisor_body` (the `sup-spawn` path, which has been working) rather than through
  `sup-handoff-begin` (the path that failed), and §5.6's exit-0 contract assumes a dispatch can be
  stillborn.
- **Whether `recompute_worker_native` runs often enough in practice for `holder-limited` ever to beat
  `holder-silent` to the alarm.** That is a question about operator behaviour over weeks, not about
  code. §4.7 states the bound instead of guessing the distribution.

---

## 10. Receipts

Every block is re-executed against the materialised tree of `2dec694` by `tools/verify_receipts.py`.
No block is `# volatile` or `# live`: all of them are `grep`/`sed` over files in the repo, so they are
ordinary pinned receipts and there is no evidence here that lives outside it.

**R1 — the statusline's four supervisor words. None of them means "outage".**

```
# at 2dec694
$ grep -n "_SUP_STATE_LABEL = " -A 1 bin/fleet_statusline.py
123:_SUP_STATE_LABEL = {"held": "sup held", "released": "sup released",
124-                    "none": "sup none", "unknown": "sup ?"}
```

**R2 — a live supervisor body leaves the worker buckets, so a `limited` supervisor is in no bucket.**

```
# at 2dec694
$ sed -n '186,187p' bin/fleet_statusline.py
        if w.get("tier") == "supervisor" and w.get("status") != "dead":
            continue
```

**R3 — the supervisor projection carries four keys; none is a verdict.**

```
# at 2dec694
$ sed -n '3133,3134p' bin/fleet.py
    out = {"goals_active": False, "state": "none",
           "incarnation_id": None, "heartbeat_age_seconds": None}
```

**R4 — `sup-status --json`'s eight keys; none is a succession verdict.**

```
# at 2dec694
$ grep -n '^        "goals_active"\|^        "incarnation"\|^        "heartbeat_age_seconds"\|^        "handshake"\|^        "abort_flag"\|^        "pending_decision"\|^        "interface_divergence"\|^        "nag"' bin/fleet.py
13190:        "goals_active": supervisor_goals_active(),
13195:        "incarnation": _project_claim(claim),
13196:        "heartbeat_age_seconds": beat_age,
13197:        "handshake": _project_handshake(hs),
13198:        "abort_flag": handoff_abort_flag_path().exists(),
13199:        "pending_decision": read_pending_decision(),   # §8: routing surface
13200:        "interface_divergence": _interface_divergence(),  # §5.3: B7 detection
13201:        "nag": supervisor_status_line(),
```

**R5 — the only two supervisor rows in doctor's check list.**

```
# at 2dec694
$ grep -n "functools.partial(_doctor_check_supervisor" bin/fleet.py
9437:        functools.partial(_doctor_check_supervisor_claim),
9438:        functools.partial(_doctor_check_supervisor_handoff),
```

**R6 — `limited-parks` is always `ok=True`, so a limit-parked supervisor reads `[PASS]`.**

```
# at 2dec694
$ grep -n 'return ("limited-parks"' bin/fleet.py
8523:        return ("limited-parks", True, "no usage-limit parks")
8536:    return ("limited-parks", True, " | ".join(parts))
```

**R7 — `respawn supervisor` on a released claim refuses and hands the operator back to `sup-spawn`.
This is the state last night produced, and it is the state §5.1 R-a is about.**

```
# at 2dec694
$ sed -n '6079,6080p' bin/fleet.py
            detail = (f"claim {inc} is released -- there is no holder to respawn. "
                      f"Boot a fresh body with `fleet sup-spawn --task <brief>`.")
```

**R8 — `sup-release`'s `reason` is free text on the claim. This is the string that was accurate and
useless.**

```
# at 2dec694
$ sed -n '13041,13042p' bin/fleet.py
        if reason:
            released["reason"] = reason
```

**R9 — `[UNBUILT]`: nothing in this spec exists yet, in either file.**

```
# at 2dec694
$ grep -c "succession_needed\|succession_cause\|sup-recover\|sup_recover" bin/fleet.py bin/fleet_statusline.py
bin/fleet.py:0
bin/fleet_statusline.py:0
$ echo "exit $?"
exit 1
```

**R10 — the ceiling refuses at FIVE call sites, including `respawn` twice. Corrects the brief (§3.1)
and shows `skills/fleet/supervisor.md` is stale (§9.2 A4).**

```
# at 2dec694
$ grep -n "_ceiling_refuses_dispatch(\"" bin/fleet.py
3949:    _ceiling_refusal = _ceiling_refuses_dispatch("spawn")
5048:    _ceiling_refusal = _ceiling_refuses_dispatch("send")
5506:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
5719:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
13582:    _ceiling_refusal = _ceiling_refuses_dispatch("sup-spawn")
```

**R11 — the G11 limit-park writer, and the seam that writes the input `holder-limited` reads.**

```
# at 2dec694
$ sed -n '2917,2921p' bin/fleet.py
        is_limit, reset_at, kind = scan(sid, transcript_path=path)
        if is_limit:
            updated["status"] = "limited"
            updated["limit_reset_at"] = reset_at
            updated["limit_kind"] = kind
```

**R12 — the four functions §4.2 composes: the lock-free, non-quarantining reader, the projection that
gains the three keys, the snapshot that publishes them, and the shipped precedent for reading the
holder's record from a view path (`_claim_holder_dead_note`, called from `supervisor_status_line`).**

```
# at 2dec694
$ grep -n "def _read_registry_readonly\|def status_snapshot\|def _claim_holder_dead_note\|def _supervisor_tier_snapshot" bin/fleet.py
3089:def _read_registry_readonly() -> tuple:
3109:def _supervisor_tier_snapshot(now=None) -> dict:
3154:def status_snapshot(now=None, include_archived: bool = False) -> dict:
14539:def _claim_holder_dead_note(claim, inc, age):
```

---

## 11. Amendments this spec proposes to other documents

**PROPOSED, UNRATIFIED. Nothing below has been edited into the target documents by this slice** — a
supervisor may not ratify its own narrowing of an operator-owned section, and none of these is
mine to tick.

| Target | Section | Proposed change | Owner |
|---|---|---|---|
| `docs/specs/terminal-surface.md` | new **D8** (additive; no ratified decision edited) | The command-tier field on the statusline renders an **outage word**, not a state word: `sup held` is the only calm form. Points at §6.1 here. | operator / gate |
| `docs/specs/terminal-surface.md` | §4.1 `status_snapshot()` shape | the `supervisor` dict gains `succession_needed`, `succession_cause`, `succession_age_seconds` (additive, §4.3). | operator / gate |
| `docs/specs/terminal-surface.md` | D4 receipt tables | add `sup-recover` to the quarantine table; keep the statusline and `sup-status` rows unchanged. | builder |
| `docs/specs/claim-nonce.md` | §7.2 disarm table | **A1** — the third disarm shipped on `fix/sup-release-tombstone` is not in the ratified table. **§7 is operator-owned; the supervisor may not ratify a narrowing of an operator-owned section.** | **operator** |
| `docs/specs/claim-nonce.md` | §6.3 post-release key set | **A2** — say explicitly what happens to `handoff_pending` and `handoff_token_hash` on release. | **operator** |
| `docs/specs/three-tier-command.md` | §10.4 | record that `respawn supervisor` is one arm of a larger front door, and that `sup-recover` delegates to it rather than duplicating it. | operator / gate |
| `docs/SPEC.md` | §13 doctor roster | **A3** — 25th check `supervisor-succession`; the roster count changes. | operator / doc-sync |
| `skills/fleet/supervisor.md` | Handoff section | **A4** — the respawn-ceiling paragraph is stale (R10). **Outside this slice's scope fence; filed, not fixed.** | doc-sync |
| `skills/fleet/supervisor.md` | Standing down | when `sup-recover` ships, the stand-down recipe becomes *release, then stop* for the supervisor and *`fleet sup-recover`* for the interface — one command, not three. **Outside scope; filed.** | doc-sync |
