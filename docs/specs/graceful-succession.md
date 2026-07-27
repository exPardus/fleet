# Spec: The graceful-succession signal — a fleet that says when it has no command tier

**Status:** DRAFT, ready-for-gate. Nothing here is built. Written 2026-07-27 by the `succession-spec`
slice on `spec/succession-signal`, rebased onto `main` @ `c318224`.

**Vantage.** Every receipt is pinned `# at c318224` and re-executed against that commit's materialised
tree by `tools/verify_receipts.py`. `bin/fleet.py` is untouched by this slice; the deliverable is this
document plus one `RECEIPT_FLOOR` entry (§8.1).

**The shape is RATIFIED** (operator, 2026-07-27 evening docket). This document specifies it; it does
not relitigate it. The ratified elements, restated so a reader can check the spec against them:

1. a **loud PULL signal** plus **ONE VERB**;
2. **not a session hook** — the interface is an ordinary Claude Code session, so a hook that reaches it
   fires in every session on this machine (D7);
3. **not auto-spawn** — a body dispatching its own replacement is how two live supervisors happen;
4. the signal **carries its cause** and covers **both walls** — the 200k ceiling and a usage-limit park;
5. the verb **includes the middle step only the interface can perform**.

Where this spec believes a ratified element is not implementable as written, it says so as a finding
rather than designing around it quietly. There is one such finding, and it is §4.9.

**Reads as binding:** `docs/specs/claim-nonce.md` (§5.8–5.9, §6.1, §6.3, §6.4, §6.6, §7, §7.2, §17),
`docs/specs/three-tier-command.md` §10.1/§10.4/§11, `docs/specs/terminal-surface.md` (D1–D7 and D4's
REQUIREMENT/CURRENT-STATE split), `docs/specs/native-substrate.md` contract G11,
`knowledge/lessons.md#2026-07-27-evening-outage`, `docs/OPERATOR-GATES.md` (evening docket), and
`skills/fleet/supervisor.md`.

---

## 0. The one-paragraph version

A fleet whose command tier is gone must say so on a surface the operator already reads. This spec
specifies **one signal** — `succession_needed`, a **derived** predicate over state already on disk,
with the cause carried as metadata rather than as a second mechanism — because from fleet's side a
clean release, a usage-limit park and a body fleet has retired are **the same fact**. It specifies how that signal renders on the three pull surfaces (statusline, `fleet
sup-status`, `fleet doctor`), and one operator-run verb, **`fleet sup-recover`**, that performs the
whole maneuver without ever writing the claim — so it cannot produce two live supervisors under any
interleaving. Nothing here injects anything into any session, and nothing here is automatic: the
operator typing the verb *is* the human in the loop.

---

## 1. The incident — measured, not inferred

On 2026-07-27 the supervisor `inc-20260727T024550Z-4743` hit the 200k context ceiling, attempted
`sup-handoff-begin` **three times** — every successor stillborn, registry row `working`, 0 turns, no
transcript — released the claim cleanly at `04:00:41Z`, and stopped. Nothing restarted it. Twenty-nine
commits of finished work sat unpushed the whole time.

**The dark window was then measured against the Windows event log (6008 / 41 / 6005) rather than read
off worker staleness.** The numbers are the operator's, recorded at `9f3bfa8` in
`knowledge/lessons.md#2026-07-27-evening-outage`:

| window | span |
|---|---|
| total dark (release `04:00:41Z` → new claim `16:54:06Z`) | **12 h 53 m** |
| power cut (`06:10:40Z` → `15:25:07Z`) | 9 h 14 m |
| **window A** — up but stopped (release → shutdown) | **2 h 09 m** |
| **window B** — up but stopped (reboot `15:25:07Z` → restart `16:54:06Z`) | **1 h 28 m** |
| **genuinely uncovered** | **3 h 38 m** |

**The corrected figure is worse for this design, not better.** 3 h 38 m is the part no hardware
explains. *(An earlier draft of this document re-derived 12 h 53 m from journal timestamps and offered
it as a correction to its own brief. That re-derivation is superseded by the measurement above, which
is finer-grained and is the citation this spec uses.)*

**The operator's framing of the lesson, which is this document's motivation:**

> The predecessor's shutdown was clean, journaled and correct, and it still cost the fleet its day —
> because the statusline rendered `sup released` in the same calm white as `sup held`. **A signal
> nobody is obliged to read is not a signal.** The fix is not more recording; it is making the pull
> surfaces render an outage AS an outage.

### 1.1 Which window this design covers, and which it does not

**Window A is this design's.** The claim read `released` from `04:00:41Z`, GOALS were active, and
nothing held command. §4.4 row 3 fires on exactly that state, with no delay and no recompute: the
statusline would have rendered `sup DOWN released` from the first refresh after the release, for all
**2 h 09 m** of window A. That is the whole of what this spec claims against real data, and it is
enough — window A is the part that had a live machine, a live operator session, and a surface already
on screen.

**Window B is NOT this design's, and that is a ruling, not an omission.** See §1.2.

### 1.2 CONSIDERED AND REFUSED — a fleet-side post-reboot restart path

An earlier draft of this document widened the signal to fire *"whatever the cause"* and treated a
rebooted host as one more cause. **The operator refused that** (2026-07-27), and the refusal is
recorded here rather than silently dropped, because a spec that omits a rejected option invites the
next author to re-propose it.

**The ruling.** The fleet comes back to life when **the operator relaunches the interface session**.
That is **step 5 of the startup ritual in `skills/fleet/SKILL.md`**, landed at `c318224`: GOALS active
plus no live supervisor ⇒ the fleet is stopped, the interface `sup-spawn`s one and **says so out loud
rather than reviving silently**.

**The grounds, which generalise and are the reason this belongs in a spec rather than in a commit
message:**

> Any fleet-side watcher for a rebooted host would have to either fire in a session nobody asked to be
> fleet-aware — the **D7 leak** deleted on 2026-07-22 — or dispatch a replacement with **no operator in
> the loop**, which is how two live supervisors happen. **When the honest mechanism would have to be an
> injection or an autonomous actor, the trigger belongs on the human action that was going to happen
> anyway.**

Both horns are the two things §2 and §5.8 already forbid. There is no third mechanism, so there is
nothing for this spec to build.

**What this costs the design, stated plainly.** Nothing in this document shortens window B. A fleet
that is dark because the box was dark has no reader, and **a pull signal with no reader is not a
signal** — which is the same sentence as the lesson this whole document exists for, pointed at itself.

**One honest consequence, so no one is surprised by it.** After a reboot the claim survives reading
`held` and the heartbeat stops advancing, so once it ages past `SUPERVISOR_CLAIM_STALE_SECONDS` the
predicate *will* report `holder-silent` (§4.4 row 7). **That is incidental, not a feature.** Row 7
exists for the usage-limit park (§4.7) and is justified by it alone. **No part of this spec may be
cited as post-reboot coverage, and nothing may be built that depends on it for that** — the startup
ritual owns revival, exclusively.

*(Adjacent, out of scope, and already settled elsewhere: the `claude-fleet-autoclean` timer was
retired in the same ruling — the staleness sweep is now run by the tiers, at `c318224`, because a
timer sweeps when the clock says so, which on a machine that loses power means it does not sweep at
all. Same shape as the ruling above: the work moves onto an action that was going to happen anyway.)*

---

## 2. The hard constraint, restated before any design

**FLEET INJECTS NOTHING INTO ANY SESSION** — terminal-surface **D7**, ratified 2026-07-22. A
globally-enabled plugin's `SessionStart` hook fires in every session on the machine; this fleet's
operator gates, worker table and knowledge index leaked into unrelated repositories on this box. The
hook and the plugin `hooks` key were deleted and a test pins their absence.

- **No `SessionStart` hook, and no other surface that fires before the operator has opted into fleet
  work.** Every signal specified here is **PULL**: the statusline the operator installed on purpose
  (`fleet init --statusline`, D6), or a verb they typed.
- **A worker-scoped hook in `worker-settings.json` would be permissible** — it is fleet's own dispatch
  surface and cannot escape to a foreign session. **This design uses none, and the reason is physics,
  not restraint:** contract G11 says a plan-limit wall fires **no Stop hook at all** (*"the rate-limit
  wall dies silently: no Stop hook fires, roster state is unaffected"*). A hook cannot observe that
  event. Nor can any hook observe a power cut. If a later author reaches for a hook here, those are the
  two facts to re-read first.
- **Succession is never automatic.** §5.8 states the safety argument structurally rather than by
  promise.

---

## 3. CURRENT STATE, measured at `c318224`

Descriptive. Every row has a receipt in §9.

| Surface | What it does today when the fleet has no command tier |
|---|---|
| statusline | renders `sup released` / `sup none` in the ordinary command-tier hue — calm words (R1) |
| statusline | **drops every live supervisor-shaped body out of the worker buckets** (R2), so a `limited` supervisor body appears in no bucket at all |
| `status_snapshot()` | `supervisor` carries four keys: `goals_active`, `state`, `incarnation_id`, `heartbeat_age_seconds` (R3). No verdict |
| `fleet sup-status --json` | eight keys, none a succession verdict (R4) |
| `fleet doctor` | 24 checks; `supervisor-claim` and `supervisor-handoff` are the only supervisor rows (R5) |
| `fleet doctor` | `limited-parks` is **always `ok=True`** (R6) — a limit-parked *supervisor* reads `[PASS]` |
| `fleet respawn supervisor` | on a released claim, **refuses rc 2**, pointing at `fleet sup-spawn --task <brief>` (R7) |
| `sup-release` | stores `reason` as free text (R8) — the string that was accurate and unread |
| anywhere | **no `succession_needed` / `succession_cause` symbol exists** (R9) |

Two things in that table are the whole defect:

1. **The datum exists and is calm.** `state == "released"` with `goals_active == True` is already in
   `status_snapshot()`, and the projection already distinguishes it from a dormant fleet —
   `_supervisor_chunk` returns `None` when GOALS are dormant, so `sup released` only renders while a
   supervisor is expected. **What is missing is not the datum. It is urgency in the render and a
   machine-readable verdict a doctor row can key on.**
2. **`held` is not the same as healthy.** A claim `held` by a body that is limit-parked, dead, or
   simply gone renders `sup held` — the one calm word — and doctor passes.

### 3.1 A correction the brief needs, now partly overtaken

The brief states that `_ceiling_refuses_dispatch` *"already refuses `spawn`, `send` and `sup-spawn`"*.
At `c318224` it refuses at **five** call sites — `spawn`, `send`, `sup-spawn`, and `respawn` twice,
gated on `--task` (R10).

The operator has since **ratified the extension** (evening docket), with a **binding process
condition** — *do not trust the cited line numbers; grep the enumeration and edit what is measured*,
because line-number citations in prose have rotted twice in this repo and nothing tests them. **The
doc-sync edit landed at `d543691`**, so §11.3 now names `fleet spawn`, `fleet send`, `fleet sup-spawn`
and **task-bearing** `fleet respawn`, with the `--task` discriminator marked normative. That closes the
three-tier half of this correction; this spec keeps the practice, citing
`_ceiling_refuses_dispatch` **by grep** (R10) and by function name, never by line.

**What is not closed:** `skills/fleet/supervisor.md` still reads *"It does not yet cover `fleet
respawn`"*. That is stale in the under-claiming direction and now contradicts a ratified decision as
well as shipped code. `skills/**` is outside this slice's scope fence — **filed, not fixed**
(§10.2 A4).

---

## 4. Part 1 — the signal

### 4.1 One predicate, one enumerated set of causes

> **`succession_needed` ⇔ `goals_active` AND the claim is UNMANNED.**
>
> **UNMANNED** means *no live supervisor body holds command*. Three ways to be unmanned, and the
> operator's phrase "released-or-absent" maps onto them exactly:
>
> - **`no-claim`** — there is no claim file. *(absent)*
> - **`released`** — a claim exists and was explicitly stood down. *(released)*
> - **`orphaned`** — a claim exists and says `held`, but no live body answers for it. *(absent — and
>   this is the branch that covers a usage-limit park and a body that died without fleet
>   observing it, §4.5)*

The two walls the ratified shape names — **the 200k context ceiling** and **a plan usage-limit park** —
plus the states fleet itself creates (`kill supervisor` arm 2, a stillborn successor) are **why** the
claim became unmanned. Those are `succession_cause` values: **metadata on one signal, not a second
signal.** One fact with a cause is item 1 of the ratified shape; a signal per cause would give the
operator three things to read and no single question to ask.

**Scoped, not universal.** The enum in §4.4 is closed and enumerates conditions fleet can observe from
its own state. It is deliberately **not** widened to "any reason a fleet might be dark" — §1.2 records
that widening as considered and refused, and the boundary matters: **a cause fleet cannot observe
without an injection or an autonomous actor is out of scope by ruling, not by oversight.**

> **DECISION D-GS1 — DERIVED, NEVER STORED.** `succession_needed` is a projection computed at read
> time. No new file, no new registry key, no new claim key, no writer.

The brief anticipated this shape, and the argument for it *is* the design:

| The question | A stored flag | A derived predicate |
|---|---|---|
| *"What writes it when the body is parked and cannot act?"* | needs a third-party writer. A **view** writing it violates terminal-surface D1/D4 and invariant 6; a **mutating verb** writing it means the fact appears only when somebody runs one — and during an outage nobody runs anything. | nothing writes it. |
| *"What writes it when the body dies without warning — a crash, an outside `claude stop`, a `kill supervisor` arm-2 freeze?"* | **nothing can.** There is no turn in which to write it. | nothing needs to. The claim file and the registry outlive the body; the predicate reads them. |
| *"What clears it?"* | a clearing step somebody must remember on `claim` / `seize` / `limit-transfer` / `resume` / handoff-complete. A missed one is a permanent false alarm. | nothing. The condition stops existing (§4.8). |
| *"Can it go stale and lie?"* | yes, both directions. | no. It has no persistence in which to be wrong. |

**A signal that depends on a dying body successfully writing something is a signal that fails in
exactly the case it exists for.** The three stillborn successors are the proof: each was dispatched,
none ever took a turn, and a body that never takes a turn cannot write anything at all.

There is a fourth reason, and it is the one that would have mattered on the night. **A stored flag
would naturally be cleared by `fleet sup-spawn`** — the verb that dispatches a successor. That would
have been exactly wrong three times: a stillborn successor is dispatched, the flag clears, the
successor never takes a turn, and the fleet goes quiet with the alarm silenced by the act that failed.
**The derived predicate clears when a body *claims*, not when a body is *dispatched*** (§4.8).

### 4.2 The inputs — four, all already on disk, none new

The predicate needs **nothing beyond state that already exists**, and nothing a D4-compliant reader
does not already read:

1. `supervisor/GOALS.md` — via `supervisor_goals_active()`; already read by `_supervisor_tier_snapshot`.
2. `supervisor/INCARNATION` — via `read_incarnation()`; already read by the same function. Supplies
   `state`, `released_at`, `heartbeat_at`, `session_id`, `incarnation_id`.
3. The claim holder's **registry record**, resolved through `_record_is_supervisor_claim_holder` over
   the sid union. Supplies `status` and `last_activity`. Read **lock-free and non-quarantining** via
   `_read_registry_readonly` — the reader `_claim_holder_dead_note` already uses from inside
   `supervisor_status_line` (R12), so the precedent and its D4 compliance are shipped, not proposed.
4. `SUPERVISOR_CLAIM_STALE_SECONDS` — an existing module constant (3600).

**No roster fetch. No subprocess. No lock. No write.** The ~1.7 s `_fetch_agents_roster` the §7.2 gate
pays for is deliberately **not** here: it would put a subprocess on a statusline refresh path that D1
forbids one on. §4.6 shows that the absence of the roster is not merely a limitation — it is what keeps
this signal cleanly separated from `sup-boot`'s freeze verdict.

### 4.3 The shape, exactly

`_supervisor_tier_snapshot()`'s dict gains three keys; `status_snapshot()["supervisor"]` therefore
carries seven:

```python
{
  "goals_active": True,
  "state": "released",                 # unchanged: held | released | none | unknown
  "incarnation_id": "inc-20260727T024550Z-4743",
  "heartbeat_age_seconds": None,       # unchanged; None on a released claim BY DESIGN (CN §6.3)

  "succession_needed": True,           # NEW. True | False | None -- tri-state, §4.5
  "succession_cause": "released",      # NEW. closed enum, §4.4
  "succession_age_seconds": 46405.0,   # NEW. float | None -- age of the CONDITION, §4.7
}
```

The derivation is a **pure function over two inputs and a clock** — no IO of its own, so every caller
supplies the read it was already doing (invariant 9: one derivation, many entry points):

```python
def supervisor_succession_verdict(claim, holder_record, now=None) -> dict:
    """(needed, cause, age_seconds) from the claim and the holder's registry
    record. PURE: no file read, no lock, no roster, no subprocess.
    `holder_record` is None when the registry could not be read or no record
    carries the holder's sid -- a legal input, not an error."""
```

### 4.4 `succession_cause` — the closed enum, in precedence order

First match wins, so the most specific cause is published.

| # | Cause | Condition | `needed` | Unmanned by |
|---|---|---|---|---|
| 0 | `null` | `goals_active` is False | `False` | — |
| 1 | `"undecidable"` | claim file present and **unparseable** | `None` | — |
| 2 | `"no-claim"` | GOALS active, **no** claim file | `True` | absent |
| 3 | `"released"` | `claim["state"] == "released"` | `True` | released |
| 4 | `"holder-limited"` | held; holder record `status == "limited"` | `True` | orphaned |
| 5 | `"holder-frozen"` | held; holder record `status` ∈ {`dead`, `dead-suspected`}; heartbeat **fresh** | `True` | orphaned |
| 6 | `"holder-gone"` | held; holder record `status` ∈ {`dead`, `dead-suspected`}; heartbeat **stale** | `True` | orphaned |
| 7 | `"holder-silent"` | held; heartbeat age > `SUPERVISOR_CLAIM_STALE_SECONDS`; no registry evidence | `True` | orphaned |
| 8 | `null` | held; heartbeat fresh; no evidence of death | `False` | — |

Specification notes, not commentary:

- **Row 0 is how a resting fleet stays silent, and it is a shipped lever.** An operator not running
  supervisor doctrine parks it with the literal token `SUPERVISOR-DORMANT` in `GOALS.md`
  (`supervisor_goals_active`), or by having no `GOALS.md`. This is the answer to *"when must the doctor
  check NOT fire"* (§6.3) and it required inventing nothing.
- **Row 3 has no grace period, deliberately.** A `released` claim is the outgoing body's own signed
  statement that it is done, and the planned in-band succession never passes through `released` —
  `sup-handoff-complete` transfers the claim directly. So `released` + GOALS active always means a body
  is owed. A grace window here would have suppressed exactly this incident's alarm.
- **Rows 5 and 6 split on the heartbeat, not on the registry status**, because that is where §6.3's
  seize/freeze boundary lives (§4.6).
- **A holder sid matching NO registry record adds no cause of its own.** It is claim/registry
  divergence, which is evidence of nothing about liveness; the heartbeat decides, so such a claim lands
  on row 7 or row 8. *(`_resolve_supervisor_lifecycle_target` already refuses destructive verbs on that
  state as "never auto-repaired" — a separate and correct posture, unchanged here.)*
- **`dead` and `dead-suspected` fold together** and the exact status goes in the detail text. The
  operator's action is identical; two enum values for one action is a distinction a 4 a.m. reader pays
  for and does not use.

### 4.5 What `absent` means, precisely — and the death fleet did not observe

The requirement is that "absent" must cover *a claim that is `held` by a body that no longer exists*.
That is the **orphaned** branch — rows 5/6/7. It is worth spelling out what a body that dies *without
fleet observing it* leaves on disk — an outside `claude stop`, a crash, a host that went away — because
the naive reading gets it wrong:

| After an unobserved death | on disk |
|---|---|
| `supervisor/GOALS.md` | survives. `goals_active` stays `True`. |
| `supervisor/INCARNATION` | survives, `state: "held"`, `session_id` naming a session that no longer exists. |
| the holder's registry record | **survives, with whatever status the last recompute wrote** — very possibly `working` or `idle`. |
| `heartbeat_at` | frozen at the last beat. |

**So the registry is the wrong detector for this case and the heartbeat is the right one.** Such a
record can read `working` indefinitely, because `recompute_worker_native` only runs when somebody
drives a recomputing verb and during an outage nobody does. Rows 4–6 would all miss it. **Row 7
catches it from the claim file alone** — no recompute, no registry, no roster, no hook.

*(This is also, incidentally, the shape a rebooted host leaves. §1.2 is explicit that revival after a
reboot is the startup ritual's job and not this signal's; the row is justified by the usage-limit park
and by unobserved death alone, and must not be cited as post-reboot coverage.)*

### 4.6 Coexistence with `seize` / `freeze` — which the operator sees first

`claim-nonce` §6.3's boot table draws a real and deliberate boundary: roster-gone plus a heartbeat aged
past `SUPERVISOR_CLAIM_STALE_SECONDS` becomes `seize`; below that hour it is `freeze` and pages the
operator. **This spec adds a signal. It moves no threshold in that table and adds no verdict to it.**

**They do not compete, because they are in series and they read different evidence:**

| | the signal | `sup-boot`'s verdict |
|---|---|---|
| kind | a **view**, ambient, rendered with no command typed | a **verb's** decision, existing only once someone runs it |
| evidence | claim file + registry, **no roster** | claim file + registry + **live roster** |
| when the operator meets it | **first, always** | after they have already acted on the signal |

The order is: **signal → operator runs `sup-recover` → the dispatched body runs `sup-boot` → `claim` /
`seize` / `limit-transfer` / `freeze`.** The signal says *a supervisor is owed*; `sup-boot` decides
*how the claim moves*, unchanged.

**And the partition is structural rather than negotiated.** The freeze window is *defined by roster
evidence* — roster-gone with a fresh heartbeat — and the signal reads no roster. So:

> **The signal fires exactly on the states where the next `sup-boot` would take the claim and exit 0 —
> `claim`, `seize`, `limit-transfer` — plus exactly one more: row 5 `holder-frozen`.**

Row 5 is the stated exception and it is deliberate. There, fleet has *positive* evidence of death (it
wrote `dead` itself, via `kill supervisor` arm 2, three-tier §10.4) while the heartbeat is still fresh,
so `sup-boot` would `freeze`. **Nobody holds command in that state, so the operator is owed the alarm
even though the remedy is time-gated.** The signal says *a supervisor is owed*; §6.3's freeze says *not
yet, and here is when* — and the "when" is already computed and already printed by
`_claim_holder_dead_note` on all three surfaces, so row 5's detail text carries that existing string
rather than a second computation of it.

Below the hour with a fresh heartbeat and **no** registry evidence of death, the signal is **silent**
and `sup-boot`'s freeze is the only surface that speaks. That is correct: it is the one state where
"is the body alive" genuinely requires a live probe and an operator's judgement, which is what the
freeze exists for.

### 4.7 Both walls, and how long each takes to surface

| Wall | How it becomes visible | Latency |
|---|---|---|
| **200k context ceiling** | loud and self-aware. The body knows, `fleet sup-context` measures it, `_ceiling_refuses_dispatch` refuses it at five sites (R10). It ends in a `sup-release`, so the signal fires on **row 3** the instant the claim is written. | **immediate** |
| **plan usage-limit park** | **silent** (G11: no Stop hook, roster unaffected). Two paths; the design does not depend on the faster one. | see below |
| **a death fleet did not observe** (outside `claude stop`, crash) | nothing writes anything (§4.5). | ≤ 1 h |

**The usage-limit park in detail, because it is the half a naive design gets wrong.**

*Who writes the input, and when.* `_investigate_no_outcome` calls the module seam `_limit_scan_hook`
(`transcript_limit_scan` in production) and, on a limit-shaped transcript tail, writes
`status = "limited"` plus `limit_reset_at` / `limit_kind` onto the record (R11). The supervisor body is
a registry row like any other (`sup|<launch-id>|boot`), so this machinery already applies to it
unchanged. **The actor is whichever caller next drives `recompute_worker_native`** — in practice
`fleet status` (bare) — **and the moment is that caller's invocation, not the park.**

*And that is a real hole, stated rather than papered over: if nobody runs a recomputing verb, the park
is never written.* The statusline does not recompute and must not, by D1. So `holder-limited` (row 4)
is **not** an always-fresh cause.

*What closes it: row 7.* A parked body cannot run `sup-checkpoint` or `sup-heartbeat`, so its heartbeat
ages, and the heartbeat lives in the claim file, which the predicate reads directly.

> **A supervisor parked on a usage limit becomes visible within
> `SUPERVISOR_CLAIM_STALE_SECONDS` (3600 s) from the claim file alone. When a recompute has run, the
> cause is upgraded to `holder-limited` and the alarm arrives immediately instead. Worst case one hour;
> best case immediate. The registry buys the *cause word*, never the *alarm*.**

**Row 7's latency is unmeasured against real data, and this document will not pretend otherwise.** The
2026-07-27 incident produced no supervisor park — it produced a clean release, which row 3 catches
instantly (§1.1) — so the one-hour bound above is derived from `SUPERVISOR_CLAIM_STALE_SECONDS`, not
observed. What *is* measured is the half this design does cover: window A, 2 h 09 m, on row 3, with
zero delay.

*The cost of row 7, owned.* `supervisor_status_line`'s docstring records that its file-only heartbeat
read *"may false-fire on a live idle supervisor (accepted: the nag is advisory)"*. Row 7 promotes that
same read from advisory nag to doctor FAIL and inherits the false-fire. Two things make that
acceptable, stated so a reviewer can reject them rather than have to find them:

1. A supervisor that has not beaten in an hour is **violating its own checkpoint discipline** —
   `skills/fleet/supervisor.md` requires the heartbeat kept younger than 60 minutes. The "false" alarm
   is a true alarm about a different obligation.
2. It **self-clears on the next beat**, and the remedy is one command the supervisor already owes
   (`fleet sup-heartbeat`).

`succession_age_seconds` per cause:

| Cause | Clock | Why |
|---|---|---|
| `"released"` | `claim["released_at"]` | the moment the fleet lost its command tier |
| `"holder-frozen"` / `"holder-silent"` | `claim["heartbeat_at"]` | the last sign of life |
| `"holder-limited"` / `"holder-gone"` | holder record `last_activity` | the last thing fleet observed |
| `"no-claim"` / `"undecidable"` | `None` | **nothing on disk dates these.** They render with no age rather than a guessed one |

> **BINDING for the build.** `succession_age_seconds` is a **separate key** from
> `heartbeat_age_seconds`, and `heartbeat_age_seconds` stays `None` on a released claim exactly as
> today. A build that satisfies the age requirement by populating `heartbeat_age_seconds` from
> `released_at` re-introduces the §6.3 defect that `supervisor_status_line` carries a dedicated branch
> to avoid — on the one surface every session reads. The day-5 rule *"a released claim never renders an
> age"* is a rule about the **heartbeat** age; `released_at` is a different field with a different
> meaning, and §6.1 keeps the two distinguishable in the render.

### 4.8 What clears it — checked against every route that takes the claim

Nothing clears it. The condition stops existing.

| Route | What is written | Predicate after |
|---|---|---|
| `claim` (fresh box, or a cleanly released predecessor) | a `held` claim, fresh `heartbeat_at`, the new body's `session_id` | row 8 → `False` ✓ |
| `seize` | ditto + a `SEIZED` journal entry | row 8 → `False` ✓ |
| `limit-transfer` | ditto. **The claim's `session_id` becomes the successor's**, so `_record_is_supervisor_claim_holder` resolves to the *successor's* record and the parked predecessor's `limited` record stops being the holder record | row 8 → `False` ✓ |
| `resume` (own aged claim after a fork-steer) | restamped `heartbeat_at` | row 8 → `False` ✓ |
| `sup-handoff-complete` | the claim transfers with the successor's own generation | row 8 → `False` ✓ |

**And the one that deliberately does NOT clear it: `fleet sup-spawn`.** Dispatching a body changes no
input. The alarm stands until that body runs `sup-boot` and **claims**. This is the property that would
have kept the alarm up through all three stillbirths, and it is the strongest argument for D-GS1.

### 4.9 The one place a ratified element is not implementable as written — stated as a finding

The ratified shape says the signal fires on *"no live supervisor body"*. **A view cannot determine
liveness.** Liveness on this substrate is a roster question, `_fetch_agents_roster` is a
`claude agents --json --all` subprocess measured at ~1.7 s with a 30 s worst case, and
terminal-surface D1 forbids a subprocess on a hot path that refires after every assistant message.

**This spec does not quietly redefine the requirement.** It implements *"no live supervisor body"* with
three **proxies**, and names them as proxies:

| Proxy | Evidence | Freshness |
|---|---|---|
| the holder record's `status` (rows 4–6) | fleet's own recompute verdict, incl. the G11 limit scan | only as fresh as the last recomputing verb |
| the heartbeat (rows 5–7) | the claim file, written by the body itself | **always fresh** |
| the claim's own `state` (rows 2–3) | the body's or the operator's explicit act | **always fresh** |

The residual, precisely: **a live supervisor that is beating but wedged reads as manned, and a dead one
that died within the last hour with no recompute reads as manned.** Both are bounded by
`SUPERVISOR_CLAIM_STALE_SECONDS`. The alternative — a roster fetch in the predicate — is refused
because it would put a 1.7 s subprocess on the statusline, the exact class of defect D1 was written
for, and because the first thing an operator does with a statusline that stutters is uninstall it.
`fleet doctor` **may** fetch the roster (it already does, in `_doctor_check_claude_agents`), so a later
slice could give the doctor row a roster-confirmed arm the statusline cannot have. **Filed, not built**
(§10.1 O10).

### 4.10 BINDING — every input is a measurement or a state, never a self-report

No input to `succession_needed` is anything a body *said about itself*. All four (§4.2) are either
state a body wrote as a durable fact (`state`, `heartbeat_at`, `released_at`) or a verdict fleet
computed itself (the registry `status`, via `recompute_worker_native`). **Nothing the predicate reads
is an estimate, an attestation, or prose.**

This is not fastidiousness. It is measured, twice, from this project's own record:

- **A supervisor body estimated its own context occupancy at roughly 60k "by feel". `fleet sup-context`
  measured 198,767 tokens.** Wrong by ~140k, in the direction that matters — the body believed it had
  room and was one refusal away from the ceiling. Four gate results at 2–5k output tokens each are most
  of a body's budget, and none of that is legible from the inside. **If any part of this design ever
  triggers on occupancy, it must trigger on `fleet sup-context`'s measurement and never on a
  self-report.** Today it triggers on occupancy nowhere: the ceiling is the only occupancy consumer,
  and `_ceiling_refuses_dispatch` already resolves the caller's own transcript and sums the three
  usage terms rather than asking anyone.
- **`sup-release --reason` is the counter-example, and it is why §4 exists.** It is prose written by a
  body under context pressure. It was accurate on the night and it changed nothing (R8). §5.5 therefore
  forbids `sup-recover` from presenting it as a brief.

This composes with `claim-nonce` §17's ratified clause — *"inference may select the SUBJECT of a
measurement, but may not supply the GROUNDS of a refusal"* — and stands slightly stronger than it: this
predicate grounds no refusal at all, but it still declines self-report as an **input**, because a
detector built on what a degrading actor believes about itself degrades with it.

---

## 5. Part 3 — folding the maneuver into one verb

### 5.1 What the tombstone merge already solved — it is now the base, not a branch

`fix/sup-release-tombstone` merged at `0cda9f6` and is in `main` @ `c318224`. As shipped (R13):

- `cmd_sup_release` tombstones the releasing body's **own** registry record —
  `_tombstone_releasing_body`, `status = "dead"`, the same field and literal `_cmd_kill_native` writes,
  read by the same `_record_is_live`. Own-record-only is **structural**: the target is whatever
  `_acting_worker_identity` resolves the *caller's own* sid to, so no input exists by which a release
  could be aimed elsewhere.
- `_releaser_live_sids` gained a first arm, `_releaser_body_is_tombstoned`, which **dominates the
  roster**: a body fleet has retired is not a live releaser however long its session lingers in
  `claude agents`. So `_releaser_is_roster_live` is false **by construction** for the body that just
  released.
- Order is release-then-tombstone inside one `fleet_lock` section, so a death between the two writes
  leaves today's B6 refusal, which self-heals.

> **The middle step of the three-step maneuver is solved — for the clean-release path, and only for
> it.** The recipe `sup-release` → *[the interface stops the retired body]* → `sup-spawn` has lost its
> middle term on that path. That is a real closure and this spec does not re-solve it.

#### 5.1.1 The scope, MEASURED — and why it changes item 3's justification without weakening it

`_tombstone_releasing_body` has **exactly one caller: `cmd_sup_release`** (R14, re-derived here rather
than accepted from the sentence). It is not on the kill path, not on a heartbeat path, not on any
timer, and **nothing anywhere notices a body that simply stopped.**

So the two-step succession holds for a narrow case: a *fleet-launched* body that *voluntarily* runs
`sup-release`, whose registry is readable, and whose sid resolves to exactly one record.

**It does not run at all for:**

1. **A usage-limit park.** The body never gets another turn — that is precisely what makes limit death
   silent (G11). It **cannot call `sup-release`, so it can never tombstone itself, by construction.**
2. **A body that dies at the ceiling without releasing**, crashes, or is stopped from outside.

**And it deliberately abstains in three more**, by its own docstring rather than by guessing:
`UNRESOLVED` (not a fleet-launched body), `AMBIGUOUS` (two records carry the sid — a leak signature),
and a registry that will not read. On the third it prints, in the shipped code's own words, that
*"B6 stays armed until the body leaves the roster, i.e. **the manual step is back for this one
release**."*

> **THE SENTENCE THAT MATTERS: the tombstone helps least in exactly the cases this signal exists for.**
> It removes the middle step from the **graceful** path — where a healthy body chose to stand down and
> could already have told someone. It leaves the middle step **fully intact on both walls the signal
> fires on**: the ceiling body that did not get to release, and the usage-limit park that *by
> construction can never release*.

**Two consequences for the wording of this spec, stated so the next author does not delete the middle
step as redundant after reading the tombstone commit:**

- **Do not say "a supervisor can never complete its own stand-down" unqualified.** Since `0cda9f6` a
  supervisor completing a *clean voluntary release* does exactly that. This document does not make that
  claim anywhere, and must not acquire it.
- **Do say:** `sup-recover` must still perform the middle step, because **the signal fires on the paths
  where no release ran**, and on those paths the row is still roster-live and B6 still refuses. See
  §5.4 arm 5, and its idempotence requirement.

**Four things it does not close, and they are what the verb owes:**

| # | What remains | Why the tombstone cannot reach it |
|---|---|---|
| **R-a** | **The handover of intent across the tier boundary.** `sup-release` ends the supervisor's session; `sup-spawn` must be run by a *different* tier, later, by someone who noticed. Nothing carries the intent across. | The tombstone makes the *mechanism* work. Nothing makes the *interface* act. **This is window A — 2 h 09 m** with a clean release, a working mechanism, and no second command. |
| **R-b** | **The already-gone case.** No `sup-release` ran, so no tombstone exists. The claim is `held` with an aging heartbeat, and `sup-boot` verdicts `refuse` or **`freeze` for up to 3600 s**. **This is the parked supervisor and every body that dies without fleet observing it.** | The tombstone is written *by* `sup-release`. A body that is parked, stopped from outside, or crashed cannot write one. |
| **R-c** | **Released-but-untombstoned.** A release by pre-tombstone code, or one whose `_tombstone_releasing_body` legitimately abstained (identity `UNRESOLVED`/`AMBIGUOUS`, or an unreadable registry — all three arms print and return `None`). B6 refuses and the manual middle step is back for that release. | By design: it abstains rather than guessing, which is correct, and leaves the operator holding the step. |
| **R-d** | **`sup-spawn` requires `--task <text\|@file>`.** After an unplanned death the interface must author a campaign brief from nothing, at whatever hour the outage happened. | Out of the tombstone's scope entirely. |

### 5.2 `fleet respawn supervisor` is already most of this verb — for one state

Said before specifying anything new, because a spec that invents a verb beside an existing one that
does the same job is how a fleet ends up with two half-working paths.

`fleet respawn supervisor` (three-tier §10.4, council-ruled 4–0) already performs:

> resolve → refusal matrix → release-steer → bounded wait → stop + `"stopped"` tombstone →
> **caller-side B6 gate** → fresh gen-0 body

That **is** the whole maneuver, in one operator command, with a two-bodies gate — for a claim holder
that is **alive and steerable**. On a released claim it refuses rc 2 and hands the operator back to
`sup-spawn` (R7). On a `limited` holder it refuses rc 2 by ruling 2, printing every cheaper escape. In
the freeze window it never gets that far.

> **So the gap is not "there is no verb". It is: the existing verb covers the one state where the body
> can still cooperate, and every state in R-a…R-d is a state where it cannot.**

### 5.3 The verb

```
fleet sup-recover [--task <text|@file>] [--force-frozen] [--yes] [--nonce N] [--json]
```

**Name.** `sup-recover` over `sup-succeed` (which a tired reader parses as "the supervisor succeeded")
and over `sup-replace` (which reads as though it replaces GOALS). It names the situation — an outage —
which is also what distinguishes it from the planned routes.

**It is the single front door.** The operator does **not** classify the outage; the verb resolves the
state and delegates. That is the whole of "one verb": not a new mechanism but a **dispatcher over the
mechanisms that exist**, plus the one arm (R-c) nothing owns today.

### 5.4 The arms

Resolved under one `fleet_lock` for the read and the arm-5 mutation; the lock is **released before any
dispatch** (F4 doctrine: never hold `fleet.lock` across a subprocess).

| Arm | State | Action | rc |
|---|---|---|---|
| **0** | the **caller holds the claim** | **REFUSE** (§5.8) | 2 |
| **1** | GOALS dormant or absent | **REFUSE:** *"GOALS.md is dormant or absent — there is no supervisor doctrine to recover. The park is deliberate (`SUPERVISOR-DORMANT`); remove the token to resume."* | 2 |
| **2** | claim present but **unparseable** | **REFUSE, never decide blind** — the posture `_resolve_supervisor_lifecycle_target` takes and `sup-boot` calls `freeze`. Names `fleet doctor`. | 3 |
| **3** | claim `held`, holder alive and steerable | **DELEGATE to `_cmd_respawn_supervisor`'s choreography verbatim.** No second implementation. | its own |
| **4** | claim `released`, releaser **tombstoned or roster-gone** | dispatch a gen-0 body (`_dispatch_supervisor_body`). Nothing to stop. **Post-tombstone this is the common case.** | 0 |
| **5** | claim `released`, releaser **still roster-live and untombstoned** (R-c) | **stop that session, tombstone its record, then dispatch** — the manual middle step, performed in-fleet | 0 |
| **6** | claim `held`, holder record `limited` | dispatch. `sup-boot` verdicts `limit-transfer`. | 0 |
| **7** | claim `held`, heartbeat **stale** (incl. the unobserved-death case, §4.5) | dispatch. `sup-boot` verdicts `seize` and journals `SEIZED`. | 0 |
| **8** | claim `held`, holder record `dead`, heartbeat **fresh** — the **freeze window** | **REFUSE by default**, printing the G9 ambiguity and the `seizable in <n>s` remaining. `--force-frozen` overrides. | 2 |
| **9** | no claim at all | dispatch. `sup-boot` verdicts `claim`. | 0 |

**Arm 8 is the only place a human judgement is required, and the verb says so rather than guessing.**
`freeze` exists because roster-gone with a fresh heartbeat is genuinely ambiguous between "the body
died" and "the daemon restarted" (G9). Auto-resolving it is how a live supervisor gets a rival.
`--force-frozen` is the operator asserting they have checked; the flag exists so the assertion is
typed, not inferred.

**Arm 5's stop is the only mutation `sup-recover` performs to another body**, and it is
target-restricted by construction: the sid it stops is `claim["released_by_sid"]` and the record it
tombstones is the one whose `_record_sids` contains it. There is no name argument by which it could be
aimed elsewhere — the same structural property `_tombstone_releasing_body` relies on (R13).

> **BINDING — arms 4 and 5 are one idempotent step, not two verbs.** The middle step is stated as a
> **postcondition, never as an action**: *after this step, no roster-live session answers for the
> outgoing body.* When the tombstone already fired (the clean-release path, §5.1.1) that postcondition
> already holds and the step is a **no-op that exits 0** — it must never become an error, a warning, or
> a second stop just because the row already reads `dead`. `_tombstone_releasing_body` sets the
> precedent in shipped code: *"already a tombstone — never re-stamp one"*, returning the name rather
> than failing.
>
> **Why this is binding rather than tidy.** The two paths differ by which body ran which verb minutes
> earlier, and that is invisible to the operator at the moment they type `sup-recover`. A verb that
> succeeds on the wall paths and errors on the graceful one would teach the operator to check *before*
> recovering — which is one more step, in the exact place this design exists to remove one.

### 5.5 `--task`, and R-d

`--task` is **optional**. Omitted, `sup-recover` composes the gen-0 campaign from durable state: the
standing boot ritual (which `sup-spawn` already self-composes), plus a **pointer** — not a paste — to
`supervisor/GOALS.md` and the journal tail. A pointer, because the successor's first act is `sup-boot`,
which prints the whole bundle anyway; pasting it would put a second, staler copy on disk.

> **BINDING.** `sup-recover` must **not** copy the outgoing body's `sup-release --reason` text into the
> successor's task as though it were an instruction. It is free text written by a body under context
> pressure, and §4 exists precisely because it is not a fact. It may be **quoted, attributed and
> labelled** as the predecessor's last words. It may not be presented as a brief.

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
                  after 300s it is stillborn -- `fleet peek <name>`.
```

Grep-able terminal contracts on **stdout**, mirroring `SUP-KILL-*` / `SUP-RESPAWN-*`:
`SUP-RECOVER-DISPATCHED`, `SUP-RECOVER-REFUSED`, `SUP-RECOVER-HALTED`.

> **The `next:` block is not decoration.** It is the countermeasure to the failure that actually
> happened: a dispatched body reads as success from every surface fleet has. **`sup-recover` exits 0
> when a body has been dispatched, not when a supervisor exists**, and its own output says so in those
> words. Anything stronger would be the verb asserting something it has not measured — and per §4.8
> `succession_needed` stays `True` until that body claims, so the operator's other surfaces do not go
> quiet either.

### 5.7 Relationship to `sup-handoff-*` — settled, not left ambiguous

Three routes, **disjoint by the outgoing body's liveness**, the only classifier that needs no judgement:

| Route | Precondition on the outgoing body | Driven by | Status |
|---|---|---|---|
| `sup-handoff-begin` / `-complete` | **healthy and in-band** — it can mint a token, poll, complete | the outgoing body | the **designed** in-band route, and **currently UNREPAIRED** — see below. Unchanged by this spec. |
| `fleet respawn supervisor` | **alive and steerable**, interface-initiated | the interface | **UNCHANGED.** `sup-recover` arm 3 delegates to it. |
| **`fleet sup-recover`** | **cannot participate** — released, parked, dead, silent, or absent | the interface | **FALLBACK** to the first, **PEER** to the second. |

> **An earlier draft of this table called the handoff route "PREFERRED". That was wrong and the
> correction is load-bearing.** `sup-handoff-begin` has been **stillborn three times** — registry row
> `working`, 0 turns, no transcript — and **three supervisors in a row have now released at the ceiling
> rather than hand off**, because `sup-spawn` is the route that demonstrably works. The incarnation
> that dispatched this slice released at the ceiling an hour later and said so in its own journal
> entry: *"This is exactly the maneuver the graceful-succession target exists to make one command
> instead of three — and I am, once again, the evidence for it."*
>
> So: the handoff path is the *designed* route and the *cheapest* one when it works, but **anything
> that depends on it depends on an unrepaired mechanism, and this spec says so rather than inheriting
> the word "preferred" from a document written before the failures.**
>
> **`sup-recover` does not depend on it.** Every dispatching arm routes through
> `_dispatch_supervisor_body` — the `sup-spawn` path, the one with a live track record — and **never**
> through `sup-handoff-begin`. That is a deliberate choice, not an accident of structure: a recovery
> verb built on the mechanism that fails is not a recovery verb. If the handoff path is repaired, this
> spec needs no change; if it is not, `sup-recover` still works.

> **In one sentence, because an ambiguous relationship between two succession paths is how a fleet ends
> up with neither working: `sup-recover` is a FALLBACK to `sup-handoff-*` and a PEER to
> `respawn supervisor`. It is never a replacement for either.** It does not deprecate the handoff path,
> changes none of its verbs, and cannot compete with it: by the time any `sup-recover` arm matches, the
> handoff has either succeeded (nothing to recover) or is unavailable (nothing to compete with).

**One interaction must be refused explicitly.** A claim carrying `handoff_token_hash` has a
token-verified successor possibly mid-boot. `_supervisor_lifecycle_interaction_refusals` already
refuses `kill`/`respawn` on exactly that marker; **`sup-recover` adopts the same refusal** with the
same escapes (`sup-handoff-complete` / `sup-handoff-abort`), because dispatching through a live handoff
races the successor — the two-bodies hole arriving by a new door.

### 5.8 The safety argument — why one verb ending in a body is allowed and a self-triggering loop is not

> A verb that ends in a fresh supervisor body is acceptable **because a human typed it.** The operator
> typing `fleet sup-recover` *is* the human in the loop; the succession is not automatic, it is
> one-command. What is forbidden is a **self-triggering** path — a supervisor, a hook, a scheduler, or
> a view that starts a body with no human in the loop. That is not a difference of degree: a supervisor
> dispatching its own replacement produces two live supervisors over one GOALS.md, the one condition
> the entire claim system exists to prevent.

**Enforced, not promised, by four structural facts:**

1. **Arm 0 refuses the claim holder, on sound grounds.** Keyed on
   `_caller_holds_supervisor_claim(caller) is True` — a fact proven from the claim and the registry,
   never inferred. This matters: `claim-nonce` §17 (RATIFIED) holds that *"inference may select the
   SUBJECT of a measurement, but may not supply the GROUNDS of a refusal"*, and specifically that
   `FLEET_WORKER` **presence** is unsound evidence because donation can only ever add a stamp. **So
   this verb may not refuse on `FLEET_WORKER`.** Claim-holdership is the sound test — and it is exactly
   the right one, since the body that must never run this is the one holding the claim.
2. **No fleet surface invokes it.** It appears in no hook (the manifest declares none — D7), no
   scheduled task, no view path. Its slash command is a **prompt template the model executes via Bash**,
   never inline `` !` `` — terminal-surface D3, lint-enforced by `tests/test_terminal_surface.py`,
   because inline exec skips the permission prompt.
3. **The detector may not call it.** The doctor row (§6.3) and the statusline (§6.1) **flag** the
   condition and never act on it — invariant 1 in its shipped spelling, the same rule that keeps
   `resume-eligible` a rendered word rather than a launch.
4. **It never writes `supervisor/INCARNATION`.** §5.9.

**Detection where enforcement is impossible.** A non-holder worker session *could* run `sup-recover` —
fleet's §7 gate is a knowingly-bypassable speed-bump by ratified operator decision (option (b),
2026-07-23), and no sound test distinguishes an interface session from a worker one. So the journal
entry `sup-recover` writes **records the caller sid**, making it detectable after the fact. Stated
rather than hidden: this design does not claim an enforcement it cannot deliver.

### 5.9 The races, walked

**The invariant that makes these boring: `sup-recover` never writes the claim.** Every dispatching arm
starts a body and lets `sup-boot` adjudicate under `fleet_lock` — the code's own doctrine, *"Fleet never
decides claim-holdership from a respawn flag."*

| Interleaving | Outcome |
|---|---|
| **Two operators run `sup-recover` concurrently.** | Both dispatch. Both bodies run `sup-boot` under the lock. The first claims; the second gets `refuse` (§6.1 rule 2, holder roster-live) and terminates per the boot ritual. **One supervisor, one wasted body.** Two live supervisors cannot result, because holdership is adjudicated under the lock by a verb neither dispatcher controls. |
| **Arm 5 stops the releaser while it is mid-`sup-release`.** | Arm 5 fires only on an already-`released` claim, and `cmd_sup_release` commits the claim write *before* the tombstone inside one lock section — so the release is durable before arm 5 can observe it. |
| **Arm 3 delegates the release-steer; the holder self-releases first.** | `_await_claim_released` polls and succeeds immediately. Unchanged from today's `respawn supervisor`. |
| **Arm 6 dispatches; the parked predecessor's limit resets and it wakes.** | The successor took the claim by `limit-transfer`. The woken predecessor's next `sup-*` verb fails the continuity gate (rc 4) and its instruction (claim-nonce §5.7) is to stop and escalate, never to seize. Shipped behaviour. |
| **Arm 7 dispatches on a stale heartbeat; the "gone" holder is alive and merely silent.** | **The one real residual.** The successor seizes; two bodies both believe they hold the claim. The nonce is exactly the mechanism for this: the successor mints a new generation, the old body's next verb presents a stale one and is **REFUSED (rc 4)**, and a `refused` record inside the 24 h window makes `doctor supervisor-claim` **FAIL** with *"a second body of this lineage may be acting"*. **Divergence is detected and bounded, not prevented** — which is what claim-nonce claims for itself. This verb neither strengthens nor weakens it. |
| **Arm 8 forced with `--force-frozen` on a holder that is actually alive.** | As above, with the operator having typed the assertion. |
| **`sup-recover` runs while a handoff token is minted.** | Refused (§5.7). |

---

## 6. Part 2 — the pull surfaces, in priority order

### 6.1 The statusline

**The rule, in one line: `sup held` with a live holder is the only calm word. Every other state is an
outage while GOALS are active.** Today three of the four shipped labels render calm (R1), and a fourth
state — `held` with a limited, dead or vanished holder — renders calm too.

| `succession_cause` | today | specified |
|---|---|---|
| `null` (healthy) | `sup held` | `sup held` — **unchanged** |
| `"released"` | `sup released` | `sup DOWN released 12h` |
| `"no-claim"` | `sup none` | `sup DOWN no-claim` |
| `"holder-limited"` | `sup held` | `sup DOWN limited 3h resets 14:20` |
| `"holder-frozen"` | `sup held` | `sup DOWN frozen 20m` *(the `seizable in <n>s` detail stays in `sup-status`/doctor, where there is room for it)* |
| `"holder-gone"` | `sup held` | `sup DOWN gone 2h` |
| `"holder-silent"` | `sup held 2h` | `sup DOWN silent 2h` |
| `"undecidable"` | `sup ?` | `sup ?` — **unchanged.** Already the word for "cannot read the claim" |
| GOALS dormant/absent | *(silent)* | *(silent)* — **unchanged** |

Binding render rules:

- **`DOWN` is painted in the reserved alarm hue** — the same bold red as the `N bodies` second-body
  alarm. A **deliberate reuse of one hue for two conditions**, against the line's usual
  one-hue-per-status rule, because they are the same class of event: the command tier is not
  functioning and the operator must act now. A second red is a distinction the eye cannot make on a
  one-line surface. **They can co-occur** (`sup DOWN released 12h  2 bodies`) and the order is fixed:
  tier field first, body count second, exactly as the lead already orders them.
- **The cause word is ASCII and one token** — terminal-surface §4.3: the line is pure ASCII by
  construction, because a cp1252 console cannot encode glyphs and the exit-0 guard would swallow the
  `UnicodeEncodeError`, leaving a permanently blank statusline.
- **The age is `succession_age_seconds`, never `heartbeat_age_seconds`** (§4.7); a cause with no clock
  renders with no age.
- **`resets HH:MM` is appended only on `holder-limited`**, reusing `_reset_clock` and the existing
  `limited` bucket convention. It is a flag; **the statusline never launches a resume** (invariant 1).
- **View doctrine is untouched and checkable:** everything above is a projection of
  `fleet.status_snapshot()`. The one registry read is `_read_registry_readonly` — lock-free,
  non-quarantining, the reader `_claim_holder_dead_note` already uses on this exact path (R12). **No
  lock, no probe, no write, no subprocess, exit 0 on every path.**

**One shipped behaviour this changes, named so a reviewer can weigh it.** `_supervisor_chunk` appends
an age only for `state == "held"`. The specified form appends one for `released`, `limited`, `frozen`,
`gone` and `silent`. If a test pins *"a released claim renders no age"*, it is pinning the §6.3
**heartbeat** rule and **must be re-pinned to that rule specifically** — *no `heartbeat_at`-derived age
on a released claim* — never deleted. Deleting it would drop the guard that keeps the §6.3 defect
closed.

**What is deliberately NOT changed.** A live supervisor body still leaves the worker buckets (R2), so a
`limited` supervisor still appears in no `lim` bucket. Putting it back would double-count it — it is
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

**Top-level, not nested under `incarnation`** — and that placement is a requirement, not taste:
`incarnation` is `_project_claim(claim)`, a redaction **projection of a file** (claim-nonce §5.8). A
derived verdict placed inside it would teach every reader that the claim file contains a field it does
not.

**The human form gains one line, printed FIRST**, ahead of the `supervisor:` line, because the surface
an operator types mid-incident must lead with the verdict:

```
SUCCESSION NEEDED (released): claim inc-20260727T024550Z-4743 released 12h53m ago; nothing holds it.
  recover with: fleet sup-recover
supervisor: inc-20260727T024550Z-4743 RELEASED at 2026-07-27T04:00:41Z by sid=3430c962-... -- no holder; `fleet sup-boot` claims fresh
```

- When `needed` is `False`, **no line is printed.** A health surface that prints a line saying nothing
  is wrong is how the operator learns to skip it.
- When `needed` is `None`, the line reads `SUCCESSION UNDECIDABLE: ...` — a rendered word, never
  silence.
- `sup-status` stays a **read-only view**: no lock, no probe, no write. It is one of only three verbs
  measured lock-free and non-quarantining in terminal-surface's D4 receipts, and this addition must not
  change that.

### 6.3 The `fleet doctor` check

**Name: `supervisor-succession`.** A 25th check, appended after `_doctor_check_supervisor_claim`.

`fleet doctor` prints exactly two verdicts, `[PASS]` and `[FAIL]`, so **this spec does not specify a
`WARN`**. *(The brief asks for "PASS/FAIL/WARN wording"; there is no WARN tier in `cmd_doctor`, and
inventing one would change every check's contract. The third tier is carried, as shipped rows already
carry it, by a `NOTE:` prefix inside the message — the convention `_doctor_check_supervisor_claim` and
`_doctor_check_limited_parks` both use.)*

| Condition | Verdict | Message |
|---|---|---|
| GOALS dormant or absent | `[PASS]` | `GOALS absent or dormant -- no supervisor expected` (the wording family `supervisor-claim` already uses) |
| `needed is False` | `[PASS]` | `claim <inc> held, heartbeat <n>m ago -- a supervisor is on duty` |
| `needed is True` | **`[FAIL]`** | `SUCCESSION NEEDED (<cause>): <detail>. Nothing is dispatching. Recover with fleet sup-recover.` |
| `needed is None` | **`[FAIL]`** | `supervisor/INCARNATION is present but unparseable, so succession cannot be decided. Never decide blind: inspect the claim file.` |
| the check raises | `[FAIL]` | handled by `cmd_doctor`'s existing per-check isolation wrapper |

**When it must NOT fire — the requirement by name:**

1. **A resting fleet never FAILs.** Row 0 of §4.4: GOALS absent, or `SUPERVISOR-DORMANT` present. A
   shipped operator lever with a shipped token; nothing new was needed, and a fleet that has never run
   supervisor doctrine sees `[PASS]` forever.
2. **A healthy fleet with no campaign never FAILs.** `held` + fresh heartbeat is row 8.
3. **A handoff in flight never FAILs.** The claim stays `held` with a fresh heartbeat throughout —
   `sup-handoff-complete` transfers it directly and it never passes through `released`.
4. **The window between `sup-recover` dispatching and the successor claiming DOES FAIL, deliberately.**
   Not a false alarm: no body holds the claim in that window, and this incident proved it can be
   permanent. It clears the moment `sup-boot` writes a held claim — typically under a minute, and never
   at all if the successor is stillborn, which is exactly when the operator must still be told.

**Why this row may FAIL where `supervisor-claim` stays advisory.** `supervisor-claim` was deliberately
kept `ok=True` (*"the nag is advisory"*), with one condition flipping it. This is a different question:
not *"is the claim tidy"* but *"can this fleet dispatch at all"*. A fleet that cannot dispatch is
exactly what doctor's own contract describes — *fail on conditions that need a human*. The two rows
stay separate rather than merged, because merging them would let a claim-hygiene note silence an
outage.

**And the counter-lesson, adopted from the operator's own evening ruling.** The `sup-handoff-aborted`
flag was cleared precisely because *"leaving a resolved flag standing makes `doctor` permanently red,
which trains everyone to ignore a red `doctor`."* This row is built so that cannot happen to it: it has
**no flag to leave standing**. It is derived (D-GS1), so it cannot outlive its condition, and there is
no state anyone must remember to clear.

---

## 7. The brief's direct questions, answered in one place

**Q. Is a released claim with active GOALS and no live body distinguishable from a fleet at rest?**
In the **snapshot**, already yes — `goals_active` gates the whole chunk, so a dormant fleet renders
nothing. In the **rendering**, no: `sup released` and `sup held` are the same kind of calm word. The
defect is in the render and in the absence of a machine-readable verdict, not in the data. **The
predicate needs nothing beyond state already on disk** — four inputs, all already read by D4-compliant
readers (§4.2).

**Q. What clears the fact?** Nothing. The condition stops existing when a body **claims**. Verified
across `claim`, `seize`, `limit-transfer`, `resume`, `sup-handoff-complete` (§4.8). `sup-spawn`
deliberately does **not** clear it.

**Q. Can the fact go stale and lie?** Not in the direction that matters — it has no persistence. The
failure direction chosen: an undecidable **claim** fails LOUD (it cannot flap — every writer writes
atomically, so present-and-unparseable means something outside fleet's writers touched it); an
unreadable **registry** fails QUIET and is caught within one hour by row 7 (§4.5, §4.7, §4.9).

**Q. What writes it when the body is parked and cannot act?** **Nothing writes it.** The *input* that
names the cause (`status: "limited"`) is written by the G11 transcript-tail scan in
`_investigate_no_outcome` (R11), by whichever caller next drives `recompute_worker_native`. If nobody
ever runs one, that cause never fires — **and that is why the design does not depend on it**: row 7
reaches the same alarm from the claim file alone, bounded by `SUPERVISOR_CLAIM_STALE_SECONDS`.

**Q. What does `absent` mean, and how does it avoid colliding with `seize`/`freeze`?** §4.5 and §4.6.
`absent` = *no live body holds command*, covering the no-claim case and the orphaned-claim case (a
park, or a death fleet did not observe). It collides with nothing: the signal reads **no roster** and
the freeze window is **defined by roster evidence**, so the signal fires exactly on the states where
`sup-boot` would take the claim, plus the one stated exception (`holder-frozen`), and moves no
threshold.

**Q. Does this signal cover a fleet that went dark because the host did?** **No, by ruling** (§1.2).
Revival after a reboot is step 5 of the interface startup ritual (`skills/fleet/SKILL.md`, `c318224`),
not a fleet-side watcher — because the only honest mechanisms for one would be an injection (D7) or an
autonomous dispatcher (two live supervisors). The predicate will *incidentally* report `holder-silent`
once the heartbeat ages, but **nothing may be built that relies on it for that.**

**Q. Does anything here depend on `sup-handoff-*`, which failed three times?** **No** (§5.7).
Every dispatching arm of `sup-recover` routes through `_dispatch_supervisor_body` — the `sup-spawn`
path — and never through `sup-handoff-begin`. The one thing that *does* touch the handoff path is a
**refusal** (a minted `handoff_token_hash` blocks recovery), which is safe in the direction that
matters: it declines to act, rather than depending on the broken mechanism to succeed.

**Q. Which does the operator see first?** **The signal, always** — it is ambient on a surface they
already installed. `seize` / `freeze` are boot verdicts that only exist after the operator has acted.

**Q. Which part of the three-step maneuver does the tombstone already solve?** The middle step, on the
**clean-release path and only there** — measured, not inferred: `_tombstone_releasing_body` has exactly
one caller, `cmd_sup_release` (R14). **So it helps least in the two cases this signal exists for.** A
usage-limit park can never tombstone itself *by construction*, because a parked body never receives
another turn (G11); a body that dies at the ceiling without releasing never ran the verb either. On
both walls the row stays roster-live and B6 still refuses, so `sup-recover` must still perform the
middle step — as an **idempotent postcondition** that no-ops on the clean-release path rather than
erroring (§5.1.1, §5.4). R-a…R-d remain.

**Q. Is `sup-recover` a replacement, a fallback, or a peer?** A **fallback** to `sup-handoff-*` and a
**peer** to `respawn supervisor`, disjoint by the outgoing body's liveness (§5.7).

---

## 8. Test obligations (the builder writes these; this spec does not)

**The predicate** — `supervisor_succession_verdict` is pure, so every row of §4.4 is a table test with
no fixture: all nine rows, precedence when several conditions hold at once, and `holder_record=None`
falling through to row 7 rather than crashing.

**The unobserved-death case, as its own test** — claim `held`, holder record `status: "working"`,
heartbeat aged past 3600 s ⇒ `needed is True`, cause `holder-silent`. **It must have a test of its
own**, because the naive implementation reads the registry first and calls it manned.

**Clearing** — one test per route in §4.8 asserting `needed is False` after `write_incarnation`. **And
the one that is the point: `sup-spawn` does NOT clear it.**

**View doctrine** — the D4 receipt harness in `terminal-surface.md` is parametrised over surfaces.
`sup-recover` joins the **quarantine** table (a mutating verb; it may quarantine); the statusline and
`sup-status` rows must stay `survives` / `lock-free` with the new fields present.

**Statusline** — every cause renders its specified word; `DOWN` and `N bodies` co-occur in the fixed
order; pure ASCII; **zero subprocesses**; exit 0 including on a forced exception; and a released claim
still renders **no `heartbeat_at`-derived age** (§6.1 — re-pinned, not deleted).

**Doctor** — FAIL on each `needed is True` cause; PASS on dormant GOALS; PASS on a healthy claim; FAIL
on `undecidable`; **and the anti-false-alarm test: a fleet with `SUPERVISOR-DORMANT` never FAILs this
row however broken the rest of the supervisor state is.**

**`sup-recover`** — one test per arm; arm 0 refuses the claim holder; arm 8 refuses without
`--force-frozen`; the handoff-in-flight refusal; **arm 5 tombstones only the releaser's own record**;
and the concurrency test: two dispatches, one claim, the loser terminates.

**The middle step's idempotence, as its own test** (§5.4): run `sup-recover` against a claim released
by a body whose record `cmd_sup_release` **already** tombstoned, and assert **rc 0, a dispatch, and no
second stop** — not an error and not a warning. Then run it against a released claim whose record is
still roster-live (the pre-tombstone / abstained shape) and assert the stop-then-tombstone-then-dispatch
sequence. **Both must reach the same postcondition**, which is the property, rather than the same code
path, which is not.

**Fault injections the gate should demand come back RED** — (i) clear the flag on `sup-spawn`;
(ii) render `succession_age_seconds` into `heartbeat_age_seconds`; (iii) make the statusline take
`fleet.lock`, or fetch the roster, to answer the predicate; (iv) let arm 0 key on `FLEET_WORKER`
instead of claim-holdership; (v) let `sup-recover` write `supervisor/INCARNATION` directly;
(vi) make `needed is None` PASS; (vii) decide the unobserved-death case from the registry status
alone; (viii) widen any cause to a condition fleet cannot observe without an injection (§1.2).

### 8.1 The one non-spec file this slice touches

`tests/test_receipts.py` gains a `RECEIPT_FLOOR` entry for this document. Every spec under
`docs/specs/**` is required to have one — `test_every_enforced_spec_has_a_receipt_floor` fails without
it — so adding a spec without adding the floor leaves the suite red. **`bin/fleet.py` is untouched**
(R9, and `git status --porcelain`).

---

## 9. Receipts

Re-executed against the materialised tree of `c318224` by `tools/verify_receipts.py`. No block is
`# volatile` or `# live`: every one is a `grep` over a file in the repo, so they are ordinary pinned
receipts and no evidence here lives outside it.

**R1 — the statusline's four supervisor words. None means "outage".**

```
# at c318224
$ grep -n "_SUP_STATE_LABEL = " -A 1 bin/fleet_statusline.py
123:_SUP_STATE_LABEL = {"held": "sup held", "released": "sup released",
124-                    "none": "sup none", "unknown": "sup ?"}
```

**R2 — a live supervisor body leaves the worker buckets, so a `limited` supervisor is in no bucket.**

```
# at c318224
$ grep -n 'if w.get("tier") == "supervisor" and w.get("status") != "dead":' -A 1 bin/fleet_statusline.py
186:        if w.get("tier") == "supervisor" and w.get("status") != "dead":
187-            continue
```

**R3 — the supervisor projection carries four keys; none is a verdict.**

```
# at c318224
$ grep -n 'out = {"goals_active": False, "state": "none",' -A 1 bin/fleet.py
3133:    out = {"goals_active": False, "state": "none",
3134-           "incarnation_id": None, "heartbeat_age_seconds": None}
```

**R4 — `sup-status --json`'s eight keys; none is a succession verdict.**

```
# at c318224
$ grep -n '^        "goals_active"\|^        "incarnation"\|^        "heartbeat_age_seconds"\|^        "handshake"\|^        "abort_flag"\|^        "pending_decision"\|^        "interface_divergence"\|^        "nag"' bin/fleet.py
13373:        "goals_active": supervisor_goals_active(),
13378:        "incarnation": _project_claim(claim),
13379:        "heartbeat_age_seconds": beat_age,
13380:        "handshake": _project_handshake(hs),
13381:        "abort_flag": handoff_abort_flag_path().exists(),
13382:        "pending_decision": read_pending_decision(),   # §8: routing surface
13383:        "interface_divergence": _interface_divergence(),  # §5.3: B7 detection
13384:        "nag": supervisor_status_line(),
```

**R5 — the only two supervisor rows in doctor's check list.**

```
# at c318224
$ grep -n "functools.partial(_doctor_check_supervisor" bin/fleet.py
9437:        functools.partial(_doctor_check_supervisor_claim),
9438:        functools.partial(_doctor_check_supervisor_handoff),
```

**R6 — `limited-parks` is always `ok=True`, so a limit-parked supervisor reads `[PASS]`.**

```
# at c318224
$ grep -n 'return ("limited-parks"' bin/fleet.py
8523:        return ("limited-parks", True, "no usage-limit parks")
8536:    return ("limited-parks", True, " | ".join(parts))
```

**R7 — `respawn supervisor` on a released claim refuses and hands the operator back to `sup-spawn`.
This is window A's state, and it is what §5.1 R-a is about.**

```
# at c318224
$ grep -n 'is released -- there is no holder to respawn' -A 1 bin/fleet.py
6079:            detail = (f"claim {inc} is released -- there is no holder to respawn. "
6080-                      f"Boot a fresh body with `fleet sup-spawn --task <brief>`.")
```

**R8 — `sup-release`'s `reason` is free text on the claim: the string that was accurate and unread.**

```
# at c318224
$ grep -n 'released\["reason"\] = reason' -B 1 bin/fleet.py
13219-        if reason:
13220:            released["reason"] = reason
```

**R9 — `[UNBUILT]`: nothing this spec specifies exists yet, in either file.**

```
# at c318224
$ grep -c "succession_needed\|succession_cause\|sup-recover\|sup_recover" bin/fleet.py bin/fleet_statusline.py
bin/fleet.py:0
bin/fleet_statusline.py:0
$ echo "exit $?"
exit 1
```

**R10 — the ceiling refuses at FIVE call sites, `respawn` twice. Cited by grep, never by line number,
per the operator's binding process condition (§3.1).**

```
# at c318224
$ grep -n '_ceiling_refuses_dispatch("' bin/fleet.py
3949:    _ceiling_refusal = _ceiling_refuses_dispatch("spawn")
5048:    _ceiling_refusal = _ceiling_refuses_dispatch("send")
5506:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
5719:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
13765:    _ceiling_refusal = _ceiling_refuses_dispatch("sup-spawn")
```

**R11 — the G11 limit-park writer: the seam that produces the input row 4 reads, and the reason row 4
is not always fresh.**

```
# at c318224
$ grep -n 'updated\["status"\] = "limited"' -B 2 -A 2 bin/fleet.py
2917-        is_limit, reset_at, kind = scan(sid, transcript_path=path)
2918-        if is_limit:
2919:            updated["status"] = "limited"
2920-            updated["limit_reset_at"] = reset_at
2921-            updated["limit_kind"] = kind
```

**R12 — the four functions §4.2 composes: the lock-free non-quarantining reader, the projection that
gains the three keys, the snapshot that publishes them, and the shipped precedent for reading the
holder's record from a view path (`_claim_holder_dead_note`, called by `supervisor_status_line`).**

```
# at c318224
$ grep -n "def _read_registry_readonly\|def status_snapshot\|def _claim_holder_dead_note\|def _supervisor_tier_snapshot" bin/fleet.py
3089:def _read_registry_readonly() -> tuple:
3109:def _supervisor_tier_snapshot(now=None) -> dict:
3154:def status_snapshot(now=None, include_archived: bool = False) -> dict:
14722:def _claim_holder_dead_note(claim, inc, age):
```

**R13 — the tombstone as SHIPPED, not as proposed: the disarm arm B6 decides through, the site that
consults it, and the own-record writer `sup-release` calls (§5.1).**

```
# at c318224
$ grep -n "def _releaser_body_is_tombstoned\|_releaser_body_is_tombstoned(released_by, registry)\|def _tombstone_releasing_body" bin/fleet.py
11533:def _releaser_body_is_tombstoned(released_by, registry) -> bool:
11654:    if _releaser_body_is_tombstoned(released_by, registry):
13054:def _tombstone_releasing_body(caller: str, inc: str):
```

**R14 — the tombstone's SCOPE: `_tombstone_releasing_body` has exactly one caller, and it is inside
`cmd_sup_release` (`:13146`). Nothing on the kill path, no timer, nothing that notices a body which
simply stopped — so a usage-limit park can never tombstone itself (§5.1.1).**

```
# at c318224
$ grep -n "_tombstone_releasing_body\|^def cmd_sup_release" bin/fleet.py
11538:    own record (`_tombstone_releasing_body`), so `_releaser_live_sids` below is
13054:def _tombstone_releasing_body(caller: str, inc: str):
13146:def cmd_sup_release(args) -> int:
13179:    that just released. See `_tombstone_releasing_body` for own-record-only and
13223:        retired = _tombstone_releasing_body(caller, inc)
```

Of the five hits, `11538` and `13179` are docstring prose, `13054` is the definition, `13146` is the
enclosing function, and **`13223` is the sole invocation**.

---

## 10. Part 4 — what I could not settle

Split as required: **design choices I made** (overturnable by the gate) versus **ratifications the
operator owes** (which I may not make).

### 10.1 Design choices — mine, and why

| # | Choice | Reason | How to overturn |
|---|---|---|---|
| **O1** | **Derived, never stored** (D-GS1). | §4.1. Cost: the predicate is only as fresh as its inputs, and one of its causes reads a registry field whose freshness depends on a recompute (§4.7). | Show a consumer that needs the fact when no reader is running. I could not construct one: every consumer of this fact **is** a reader. |
| **O2** | Undecidable **claim** → FAIL; unreadable **registry** → quiet. | §4.5, §7. | Show that an unparseable `supervisor/INCARNATION` can occur transiently. If it can, this flips. |
| **O3** | Row 7 promotes an **admittedly false-fireable** heartbeat read from advisory nag to doctor FAIL. | §4.7. It is the only always-fresh detector of the silent half, and its "false" alarm is a true alarm about checkpoint discipline with a one-command remedy. | **The most attackable decision in the document; the gate should attack it.** |
| **O4** | `dead` and `dead-suspected` fold into one status test, split by heartbeat into rows 5/6. | §4.4. | One enum value; cheap to change. |
| **O5** | The alarm hue is **reused** for `sup DOWN` and `N bodies`. | §6.1. Same class of event; a second red is indistinguishable on one line. | A reviewer with a stronger claim about colour budget. |
| **O6** | Verb named `sup-recover`; `--task` optional. | §5.3, §5.5. | Cheap before build, expensive after. |
| **O7** | `sup-recover` **never writes the claim**; it dispatches and lets `sup-boot` adjudicate. | §5.9. This is what makes the two-bodies argument structural rather than promised. | Do not overturn without replacing the safety argument. |
| **O8** | **No worker-scoped hook**, though the brief permits one. | §2 — G11 says a limit wall fires no hook, and no hook fires for a body that never gets a turn. | Only by falsifying G11. |
| **O9** | The doctor row FAILs during the dispatch→claim window. | §6.3 note 4. That window was permanent three times on the night. | If the stillbirths are root-caused and fixed, revisit. |
| **O10** | The predicate uses **liveness proxies, not liveness** (§4.9), and I named that as a deviation from the ratified wording rather than redefining the wording. | A roster fetch on a statusline refresh path is the exact defect D1 exists for. | A doctor-only roster-confirmed arm is a clean follow-up; **filed, not built.** |
| **O11** | The rejected post-reboot arm is **kept in the document as a recorded refusal** (§1.2) rather than deleted. | A spec that silently omits a rejected option invites the next author to re-propose it, and the grounds generalise beyond this case. | Not really overturnable — the deletion is the operator's ruling; only the *recording* of it is mine. |
| **O12** | §4.10 makes "**measurement or state, never self-report**" a binding property of every input, not just a habit. | A body estimated 60k where `sup-context` measured 198,767. A detector built on what a degrading actor believes about itself degrades with it. | Show an input that must be a self-report. I could not find one. |
| **O13** | §5.7 **downgrades** `sup-handoff-*` from "PREFERRED" to "designed but unrepaired", and `sup-recover` is specified to route through `_dispatch_supervisor_body` exclusively. | Three stillbirths; three supervisors in a row released at the ceiling rather than hand off. A recovery verb built on the mechanism that fails is not a recovery verb. | Repair the handoff path and the word can be restored. The routing choice should stand either way. |

### 10.2 Ratifications the operator owes

> **`docs/specs/claim-nonce.md` §7 is OPERATOR-OWNED, and the supervisor may not ratify a narrowing of
> an operator-owned section.** Where this design needs one it is marked below in those words and left
> undone.

| # | What is owed | Owner | Why I could not settle it |
|---|---|---|---|
| **A1** | **The §7.2 disarm table is now incomplete about shipped code.** The tombstone merge (`0cda9f6`, now in base) adds a third disarm — releaser tombstoned — and the ratified table says *"releaser roster-**LIVE** → **ARMED, unconditionally**"*. The tombstone slice reported this and correctly refused to edit it. **This spec is built on that code, so it inherits the debt and restates it rather than assuming it discharged.** | **operator** — §7 is operator-owned; **the supervisor may not ratify a narrowing of an operator-owned section** | Not mine to ratify. `docs/OPERATOR-GATES.md` already records *"an in-fleet disarm path is owed"*, so this discharges scheduled work rather than inventing a narrowing — the shape still needs the tick. |
| **A2** | **`claim-nonce` §6.3's post-release key set does not say what happens to `handoff_pending` and `handoff_token_hash`.** It enumerates seven keys kept and six removed; these two are in neither list. `sup-recover` §5.7 refuses on `handoff_token_hash`, so its behaviour after a release depends on an unspecified key. | **operator** (§6.3 is a ratified D-decision) | A released claim still carrying a minted token would mean a superseded successor could in principle validate against it. I could not determine from the text whether that is intended. **Flagged as a live ambiguity, not assumed either way.** |
| **A3** | **A 25th doctor check that can FAIL changes `fleet doctor`'s exit-code contract for a new class of condition,** and `docs/SPEC.md` §13 records the roster and a check count. | operator / doc-sync | Adding a FAIL-capable row is a policy change about what makes doctor red, and the count is a ratified number. |
| **A4** | **`skills/fleet/supervisor.md` is stale about the respawn ceiling** (§3.1, R10) — it still says the ceiling covers *three* verbs and *"does not yet cover `fleet respawn`"*, which now contradicts a ratified decision (`d543691`) as well as shipped code. Still present at `c318224`. **Note for whoever fixes it: the sentence wraps as `It does` / `not yet cover`, so a single-line grep for the phrase returns nothing and reads as already-fixed.** I nearly recorded it as discharged on exactly that mistake. | doc-sync; **outside this slice's scope fence** (`skills/**`) | Filed, not fixed. |
| **A5** | ~~§11.3's enumeration must name task-bearing `respawn` and `sup-spawn`, edited by grep rather than by the three cited line numbers.~~ **DISCHARGED at `d543691`** while this spec was being written — §11.3 now names all four verbs and marks the `--task` discriminator normative. Left in the table rather than deleted, because a row that silently disappears is indistinguishable from one that was never raised. | ~~doc-sync~~ **done** | Nothing owed. Verified rather than assumed: `d543691` touches `docs/specs/three-tier-command.md` only, so re-pinning the receipts across it changed no output. |
| **A6** | **Whether a test pins "a released claim renders no age"** (§6.1). I did not read the statusline test suite. | builder + gate | Asserting either way would be a claim I had not measured. **Stated as unverified.** |
| **A7** | **`sup-recover`'s exact rc values.** This spec reuses `SupervisorLifecycleRefusal`'s rc 2 / rc 3 split and `sup-boot`'s rc 4. I did not re-derive every constant. | builder | Named so the build confirms rather than infers. |

### 10.3 Two things I could not determine at all

- **Why the three successors were stillborn.** Journal I-E's `dontask` lead is explicitly *"a
  hypothesis, not a finding"* with counter-evidence attached, and I did not test it — this slice's
  fence forbids touching the live claim or any live worker. **This spec is designed not to need the
  answer:** `sup-recover` routes through `_dispatch_supervisor_body` (the `sup-spawn` path, which has
  been working) rather than through `sup-handoff-begin` (the path that failed), and §5.6's exit-0
  contract assumes a dispatch can be stillborn.
- **Whether `recompute_worker_native` runs often enough in practice for `holder-limited` to beat
  `holder-silent` to the alarm.** That is a question about operator behaviour over weeks, not about
  code. §4.7 states the bound instead of guessing the distribution.

---

## 11. Amendments this spec proposes to other documents

**PROPOSED, UNRATIFIED. Nothing below has been edited into the target documents by this slice** — a
supervisor may not ratify its own narrowing of an operator-owned section, and none of these is mine to
tick.

| Target | Section | Proposed change | Owner |
|---|---|---|---|
| `docs/specs/terminal-surface.md` | new **D8** (additive; no ratified decision edited) | the command-tier field renders an **outage word**, not a state word: `sup held` is the only calm form. Points at §6.1 here. | operator / gate |
| `docs/specs/terminal-surface.md` | §4.1 `status_snapshot()` shape | the `supervisor` dict gains `succession_needed`, `succession_cause`, `succession_age_seconds` (additive, §4.3). | operator / gate |
| `docs/specs/terminal-surface.md` | D4 receipt tables | add `sup-recover` to the quarantine table; the statusline and `sup-status` rows stay unchanged. | builder |
| `docs/specs/claim-nonce.md` | §7.2 disarm table | **A1** — the third disarm shipped at `0cda9f6` is not in the ratified table. **§7 is operator-owned; the supervisor may not ratify a narrowing of an operator-owned section.** | **operator** |
| `docs/specs/claim-nonce.md` | §6.3 post-release key set | **A2** — say explicitly what happens to `handoff_pending` and `handoff_token_hash` on release. | **operator** |
| `docs/specs/claim-nonce.md` | §6.3 boot table | additive note: the signal is a **view** over the same state and fires on `claim`/`seize`/`limit-transfer` plus `holder-frozen`; it moves no threshold in this table (§4.6). | operator / gate |
| `docs/specs/three-tier-command.md` | §10.4 | record that `respawn supervisor` is one arm of a larger front door, and that `sup-recover` delegates to it rather than duplicating it. | operator / gate |
| `docs/specs/three-tier-command.md` | §11.3 enumeration | **A5 — ALREADY DONE at `d543691`.** Named here so a reader of this table does not re-open it. | ~~doc-sync~~ done |
| `docs/SPEC.md` | §13 doctor roster | **A3** — 25th check `supervisor-succession`; the roster count changes. | operator / doc-sync |
| `skills/fleet/supervisor.md` | Handoff section | **A4** — the respawn-ceiling paragraph is stale (R10). **Outside this slice's scope fence; filed, not fixed.** | doc-sync |
| `skills/fleet/supervisor.md` | Standing down | when `sup-recover` ships, the recipe becomes *release, then stop* for the supervisor and *`fleet sup-recover`* for the interface — one command, not three. **Outside scope; filed.** | doc-sync |
