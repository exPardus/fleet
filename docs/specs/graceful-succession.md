# Spec: The graceful-succession signal — a fleet that says when it has no command tier

**Status:** DRAFT, gated (dual-lens ESCALATE from both lenses, 2026-07-27), **revised 2026-07-28** for
the findings that are not blocked on the operator. Nothing here is built. Written by the
`succession-spec` slice on `spec/succession-signal`, **rebased onto `main` @ `cebae4f`**.

**Vantage.** Every receipt is pinned `# at cebae4f` and re-executed against that commit's materialised
tree by `tools/verify_receipts.py`. `bin/fleet.py` is untouched by this slice; the deliverable is this
document plus one `RECEIPT_FLOOR` entry (§8.1).

**THE PIN MOVED, AND EVERY RECEIPT WAS RE-MEASURED RATHER THAN RE-PINNED.** The previous base was
`c318224`, and the previous revision of this paragraph explained that the pin was deliberately *not*
chased because the intervening rebases were **docs-only**. That reasoning was correct then and it
**expired**: this rebase crosses `wave2/doctor-repair`, `idx/core` and the autoclean retirement, which
move `bin/fleet.py` by ~2,375 lines. The document's own rule applied to itself —

> *If a later rebase crosses a commit that does touch `bin/`, every receipt here must be re-measured,
> not just re-pinned.*

— so **R1–R14 were each re-executed against `cebae4f` and their outputs replaced with what was
measured**, not with their old text under a new sha. Every one still holds structurally; only line
numbers moved. Eight new receipts (R15–R22) were added for the claims this revision makes. **What did
not survive re-measurement is called out where it lived**: the doctor check count (§3, §6.3) and D4's
lock-free/quarantine framing (§6.2), both of which the rebase changed under this document.

**The rule, restated for the next author, because the previous revision's version of it read as a
standing exemption:** the pin is chased when — and only when — the crossed commits touch a file a
receipt reads. Verify it, do not assume it: `git diff <old-base> <new-base> --stat`. A docs-only
crossing is churn; a `bin/`-touching crossing is a re-measurement, and a re-measurement is not the same
job as an `sed` over the sha.

**The shape is RATIFIED** (operator, 2026-07-27 evening docket). This document specifies it; it does
not relitigate it. The ratified elements, restated so a reader can check the spec against them:

1. a **loud PULL signal** plus **ONE VERB**;
2. **not a session hook** — the interface is an ordinary Claude Code session, so a hook that reaches it
   fires in every session on this machine (D7);
3. **not auto-spawn** — a body dispatching its own replacement is how two live supervisors happen;
4. the signal **carries its cause** and covers **both walls** — the 200k ceiling and a usage-limit park;
5. the verb **includes the middle step only the interface can perform**.

Where this spec believes a ratified element is not implementable as written, it says so as a finding
rather than designing around it quietly. **There are two such findings: §4.9 and §4.1's D-GS1.**

*(An earlier draft said "there is one such finding, and it is §4.9", and filed D-GS1 in §10.1 as **O1,
a design choice — mine**. That was the wrong shelf. The ratified text of item 1 is not "the fleet
publishes a machine-readable succession-needed fact"; it is that **"a supervisor that can no longer
dispatch RECORDS a machine-readable succession-needed fact with its cause"** (`OPERATOR-GATES.md`,
evening docket). D-GS1 answers **no writer, nothing records it** — which is a deviation from ratified
wording, exactly the class this document's own rule two paragraphs up says must be stated as a finding.
Filing it as a design choice made it look overturnable by the gate; it is not, because the element it
deviates from is the operator's. **The technical argument in §4.1 is unchanged and is not
re-litigated** — only its status is corrected. See §4.11.)*

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
`sup-handoff-begin` **three times** — every successor stillborn, no handoff completed — released the
claim cleanly at `04:00:41Z`, and stopped. Nothing restarted it. Twenty-nine commits of finished work
sat unpushed the whole time.

> **A retraction this document is built on, stated before anything cites the stillbirths.** An earlier
> draft of this spec described those successors as *"registry row `working`, **0 turns, no
> transcript**"* and *"none ever took a turn"*, and used that as the proof of D-GS1. **It is false and
> it has been retracted on `main`** (`knowledge/lessons.md`, *"retract the falsification"*): *"**'0
> turns' is a registry accounting defect, not a fact about the session.**" Transcripts exist — 82 KB
> each, 26–27 messages, Stop hooks fired clean.* The successors **did** take turns; they were denied
> at the permission layer and died in 25–33 s. Root cause, confirmed 17/17 mode↔outcome by
> `handoff-autopsy`: `SUCCESSOR_DEFAULT_MODE = "dontask"` — auto-deny-everything-unlisted.
>
> Every sentence in this document that rested on *"0 turns"* has been removed rather than softened,
> because the number came from the component under investigation. **The stillbirths remain real and
> remain cited; what they are cited FOR has changed** — see §4.1 and §5.7.

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

## 3. CURRENT STATE, re-measured at `cebae4f`

Descriptive. Every row has a receipt in §9. **Every row below was re-executed for the 2026-07-28
revision** — this table was stale on arrival at the gate and one row was numerically wrong.

| Surface | What it does today when the fleet has no command tier |
|---|---|
| statusline | renders `sup released` / `sup none` in the ordinary command-tier hue — calm words (R1) |
| statusline | **drops every live supervisor-shaped body out of the worker buckets** (R2), so a `limited` supervisor body appears in no bucket at all |
| `status_snapshot()` | `supervisor` carries four keys: `goals_active`, `state`, `incarnation_id`, `heartbeat_age_seconds` (R3). No verdict |
| `fleet sup-status --json` | eight keys, none a succession verdict (R4) |
| `fleet doctor` | **25** checks (R23). *This row said **24**, which was **correct at `c318224`** and went stale when `idx/core` merged — verified by re-running R23 against the old pin, where it still returns 24.* `supervisor-claim` and `supervisor-handoff` are the only supervisor rows (R5) |
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
At `cebae4f` it refuses at **five** call sites — `spawn`, `send`, `sup-spawn`, and `respawn` twice,
gated on `--task` (R10). *(Five at `c318224` too; re-measured across the rebase rather than carried.)*

The operator has since **ratified the extension** (evening docket), with a **binding process
condition** — *do not trust the cited line numbers; grep the enumeration and edit what is measured*,
because line-number citations in prose have rotted twice in this repo and nothing tests them. **The
doc-sync edit landed at `d543691`**, so §11.3 now names `fleet spawn`, `fleet send`, `fleet sup-spawn`
and **task-bearing** `fleet respawn`, with the `--task` discriminator marked normative. That closes the
three-tier half of this correction; this spec keeps the practice, citing
`_ceiling_refuses_dispatch` **by grep** (R10) and by function name, never by line.

**What is not closed:** `skills/fleet/supervisor.md` still reads *"It does not yet cover `fleet
respawn`"* — re-verified present at `cebae4f`. That is stale in the under-claiming direction and now
contradicts a ratified decision as well as shipped code. **Filed, not fixed** (§10.2 A4).

*(Scope note, since it changed between revisions: `skills/**` was outside this slice's original fence.
The 2026-07-28 operator brief put **`skills/fleet/SKILL.md` explicitly in scope** — its succession
bullet was false on both walls, in the file an interface session reads at startup — and that file is
now fixed (§11). **`skills/fleet/supervisor.md` was not named and remains out of scope.** A widened
fence covers what it names, not the directory it lives in.)*

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
exactly the case it exists for.**

**The argument stands on the three rows of the table above and on nothing else.** An earlier draft
billed the stillbirths as *"the proof"* — *"none ever took a turn, and a body that never takes a turn
cannot write anything at all."* **That citation is withdrawn: the successors did take turns** (§1's
retraction). The stillbirths still support D-GS1, but as a **weaker and different** argument, stated at
its real strength: a successor dispatched under `dontask` was denied at the permission layer, so it
could not have written a flag *even though it was running* — which is the same conclusion by a worse
route, since a body can be alive, ticking and still unable to write. The **load-bearing** cases are the
ones no body survives at all: a usage-limit park (G11 — no turn ever arrives) and a power cut. Neither
needs the stillbirths to make the point.

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

`_supervisor_tier_snapshot()`'s dict gains **four** keys; `status_snapshot()["supervisor"]` therefore
carries eight:

```python
{
  "goals_active": True,
  "state": "released",                 # unchanged: held | released | none | unknown
  "incarnation_id": "inc-20260727T024550Z-4743",
  "heartbeat_age_seconds": None,       # unchanged; None on a released claim BY DESIGN (CN §6.3)

  "succession_needed": True,           # NEW. True | False | None -- tri-state, §4.4 row 1
  "succession_cause": "released",      # NEW. closed enum, §4.4
  "succession_age_seconds": 46405.0,   # NEW. float | None -- age of the CONDITION, §4.7
  "succession_reset_at": None,         # NEW. ISO str | None -- ONLY on `holder-limited`, §4.3.2
}
```

#### 4.3.1 BINDING — the registry read is THREADED IN, not taken here

`_supervisor_tier_snapshot`'s docstring is explicit and is not being relaxed:

> *File-only by the same mandate as `supervisor_status_line`: **no lock, no roster read, no probe, no
> subprocess**.*

But §4.4 rows 4–6 need the holder's **registry record**, which that function does not read. **The seam
is already there and the build must use it rather than adding a read** (R18):

```
status_snapshot():
  :3061   ok, reason, data = _read_registry_readonly()      <-- the registry is ALREADY in hand
  ...
  :3074   "supervisor": _supervisor_tier_snapshot(now),     <-- called AFTER, with nothing passed
```

> **BINDING.** `_supervisor_tier_snapshot` gains an optional `registry=None` parameter and
> `status_snapshot` passes the `data` it has already read. The function performs **no registry read of
> its own**, and `registry=None` is a **legal input** meaning *no registry evidence* — it falls through
> to rows 7/8 exactly as §4.4's note on `holder_record=None` requires, never to an error.
>
> **Why this is binding and not an implementation note.** A naive build reads the registry inside
> `_supervisor_tier_snapshot` — the docstring forbids a *lock* and a *probe*, and
> `_read_registry_readonly` is neither, so nothing would stop it. The result is **two full registry
> reads on every statusline refresh**, a surface that refires after every assistant message. It would
> be correct, it would pass every doctrine test (still lock-free, still non-quarantining), and it would
> double the file I/O of the one path D1 exists to keep cheap. **A defect that no existing pin can
> see** — so the seam is specified here, and §8 owes it a test.
>
> The two callers that are **not** `status_snapshot` (`supervisor_status_line` and anything reaching
> the projection directly) pass nothing and get `registry=None`, which is the honest answer for a
> caller that did not read one — and lands them on the heartbeat rows, which is where the always-fresh
> evidence is anyway (§4.9).

#### 4.3.2 The fourth key, and the render that could not be built without it

`succession_reset_at` exists because **§6.1's specified `holder-limited` render is not producible from
the other three keys.** Stated as the defect it was, since the fix is small and the reasoning is what a
builder needs:

§6.1 specifies `sup DOWN limited 3h resets 14:20`, *"reusing `_reset_clock`"*. Measured (R19):

- `_reset_clock(iso)` is a **pure ISO-string → `"HH:MM"` formatter** in `bin/fleet_statusline.py`. It
  takes a timestamp, not a record — so "reusing" it is fine, and it is **not** the problem.
- The problem is where the timestamp comes from. `limit_reset_at` lives on the **holder's registry
  record**. The statusline sees registry rows only through `snap["workers"]`, and those rows carry
  `limit_reset_at` but **no `session_id`**. `snap["supervisor"]` carries `incarnation_id` but **no
  holder sid**. **There is no join key between the claim and the holder's row**, so the statusline
  cannot find *which* limited row is the supervisor's — and `tier == "supervisor" and status ==
  "limited"` is not an answer, because retired supervisor husks are supervisor-shaped too.

**Two ways out; this spec takes the first.**

1. **A fourth derived key.** The predicate has already resolved the holder record (§4.2 input 3) to
   decide row 4, and that record carries `limit_reset_at`. Publish it: `succession_reset_at` is that
   ISO string on cause `holder-limited`, and **`None` on every other cause**. §6.1 then renders
   `resets {_reset_clock(sup["succession_reset_at"])}` with no join and no second lookup.
2. **Publish the holder sid** so consumers can join themselves. **Refused:** it puts an identifier on
   a view surface that nothing else needs, it invites every consumer to re-implement the join
   differently, and `_project_claim` (claim-nonce §5.8) would then owe a redaction ruling about a field
   this design does not require.

**It stays derived** — `succession_reset_at` is a projection of a record the predicate already read, so
D-GS1 is untouched: still no new file, no new registry key, no new claim key, no writer.

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
- **Row 0 also swallows an UNREADABLE `GOALS.md`, and that is stated rather than hidden.** Measured
  (R20): `supervisor_goals_active()` catches `OSError` and `ValueError` — the latter covering
  `UnicodeDecodeError` — and **returns `False`**. So *"the operator parked it"* and *"the file is
  corrupt, or its directory is unreadable"* are the **same answer**, and because row 0 is first in
  precedence it **silences every row beneath it**, including row 1's `undecidable`.
  **This is a real asymmetry against §7's stated failure direction** — *"an undecidable **claim** fails
  LOUD"* is true, but an undecidable **GOALS** fails **silent**, and it fails silent on the input that
  gates the entire predicate. A fleet whose `GOALS.md` became unreadable during an outage renders
  exactly like a fleet at rest.
  **Ruled, not left open:** row 0 keeps its behaviour and the predicate is **not** changed, because
  distinguishing the two requires `supervisor_goals_active` to grow a tri-state return, which is a
  change to a shipped function that eight other callers read as a bool — out of proportion to the risk,
  and a change that would make every one of those callers newly able to crash on a corrupt file. **What
  changes instead is that the asymmetry is now documented and testable**, and `fleet doctor` is given
  the one arm that can carry it without touching the predicate: the `supervisor-succession` row prints
  a `NOTE:` when GOALS is absent-or-dormant **and `goals_path()` exists but does not decode** (§6.3).
  Doctor may pay for a second read; the statusline may not. **Filed for the operator only as an
  observation, not as a question** — nothing here is ratified wording.
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

> **HALF of row 5 has no such string, and the build must not discover this by getting `None`.**
> Measured (R21): `_claim_holder_dead_note` returns `None` unless the resolved holder record's status
> is **exactly `"dead"`** — `if holder is None or holder.get("status") != "dead": return None`. Row 5
> deliberately folds `dead` **and `dead-suspected`** into one cause (§4.4's last note), so on the
> `dead-suspected` half the borrowed string does not exist.
>
> **Specified rather than left to fall out:** row 5's detail is
> `_claim_holder_dead_note(...) or <the fallback>`, and the fallback is composed from data the
> predicate already holds — the exact status word, the incarnation, and the same
> `max(0, SUPERVISOR_CLAIM_STALE_SECONDS - age)` remaining that the shipped string computes. The
> **wording** matches the shipped sentence so the two halves of one row do not read as two different
> conditions to an operator at 4 a.m.
>
> **Widening `_claim_holder_dead_note` to accept `dead-suspected` is the tempting one-line fix and it
> is refused here.** That function is `sup-status`'s and the statusline's *freeze-window* notice, keyed
> deliberately on the status `kill supervisor` arm 2 writes (its own docstring says so). `dead-suspected`
> is a different provenance — fleet's inference, not fleet's act — and quietly folding it in would
> change a shipped surface's meaning to save this spec a fallback branch. **Filed as a possible
> follow-up, not taken.**

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

### 4.9 FINDING 1 of 2 — "no live supervisor body" is not implementable as written

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

### 4.11 FINDING 2 of 2 — nothing RECORDS the fact, and the ratified wording says a supervisor does

**The ratified element, quoted exactly** (`docs/OPERATOR-GATES.md`, 2026-07-27 evening docket):

> (1) a supervisor that can no longer dispatch **records** a **machine-readable** succession-needed
> fact with its cause — both walls count, the 200k context ceiling *and* a plan usage-limit park,
> because today `sup-release` records only prose nobody parses

**What this spec delivers, and where it diverges.** The *machine-readable* half is delivered in full
and then some: §4.3's four keys, §6.2's `succession` object, §6.3's doctor row, and the cause enum
covering both named walls. **The divergence is one word — `records`.** D-GS1 rules that **nothing
writes it and no supervisor records anything**; the fact is derived at read time from state that is
already on disk.

**This is stated as a finding, not filed as a design choice, and the distinction is not bookkeeping.**
A design choice is mine and the gate may overturn it. A deviation from ratified wording is the
**operator's** to accept or refuse, and presenting one as the other quietly converts their decision
into mine. This document's own rule (§0, opening) requires the finding form; an earlier draft filed it
as O1 and that was the defect.

**The argument for D-GS1 is unchanged and is not re-opened here** — §4.1's table, plus the fourth
reason (a stored flag would be cleared by `sup-spawn`, silencing the alarm on exactly the dispatch that
failed). **It is a strong argument and I still believe it.** What follows is only what the operator is
being asked to accept:

| The ratified wording implies | This spec delivers | The gap |
|---|---|---|
| a supervisor performs an act of recording | no actor, no act | **a supervisor that can no longer dispatch does nothing at all.** On both named walls it *cannot* — a limit-parked body never gets another turn (G11), a ceiling death may not reach a verb |
| a fact exists as a record | a fact exists as a projection | it cannot be read by anything that is not running fleet's own code against fleet's own state. There is no file to `cat`, and no artifact survives fleet being uninstalled |
| the cause is recorded with it | the cause is derived with it | one cause (`holder-limited`) is only as fresh as the last `recompute_worker_native`; §4.7 owns that and row 7 bounds it at one hour |

**What would falsify D-GS1 and hand the ratified wording back its word:** a consumer that needs the
fact **when no reader is running**. I could not construct one — every consumer of this fact *is* a
reader (a statusline refresh, a typed verb, a doctor run). **If the operator can name one, D-GS1
falls**, and the honest replacement is not a flag written by the dying body (which is what fails) but a
writer on the *arrival* side: whichever verb next observes the condition. That is a different design,
and it is theirs to ask for.

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

> **[OPERATOR-GATED] — this table is blocked on a parked operator decision, and nothing below routes
> around it.** Both gate lenses returned ESCALATE independently and both made the same point their
> CRITICAL-1: **`sup-recover` is refused by `claim-nonce` §7's claim gate on exactly the states it
> exists to clear.** Arm 5's precondition is character-for-character `_supervisor_gate`'s unconditional
> ARM condition; arms 3, 6 and 8 are gated too, and **arm 6 is a freshly-parked `limited` supervisor —
> one of the two walls the ratified shape names.**
>
> **`claim-nonce` §7 is OPERATOR-OWNED and the question is on the operator docket right now:**
> `docs/decisions/W9-section7-exemption.md`, Route B (raised with the `fleet autoclean` half as one
> decision, because both ask *when the fleet's recovery machinery is itself gated by the guard it
> exists to recover from, which side gives*).
>
> **Nothing in this revision resolves it, proposes an exemption, or re-shapes an arm to evade the
> gate.** A builder cannot start on the gated arms until it is answered — an exemption **widens** the
> disarm envelope, which is the operator's, not this document's. The arm-3 gating, the arm ordering and
> the fall-through added below are corrections to *internal contradictions in the table*; none of them
> touches which arms §7 arms, and every one of them leaves the refusal exactly where the decision file
> found it.

| Arm | State | Action | rc |
|---|---|---|---|
| **0** | the **caller holds the claim** | **REFUSE** (§5.8) | 2 |
| **1** | GOALS dormant or absent | **REFUSE:** *"GOALS.md is dormant or absent — there is no supervisor doctrine to recover. The park is deliberate (`SUPERVISOR-DORMANT`); remove the token to resume."* | 2 |
| **2** | claim present but **unparseable** | **REFUSE, never decide blind** — the posture `_resolve_supervisor_lifecycle_target` takes and `sup-boot` calls `freeze`. Names `fleet doctor`. | 3 |
| **3** | claim `held`, **`succession_needed is True`**, and the holder session is **roster-live and steerable** (not `limited` — see arm 6) | **DELEGATE to `_cmd_respawn_supervisor`'s choreography verbatim.** No second implementation. | its own |
| **4** | claim `released`, releaser **tombstoned or roster-gone** | dispatch a gen-0 body (`_dispatch_supervisor_body`). Nothing to stop. **Post-tombstone this is the common case.** | 0 |
| **5** | claim `released`, releaser **still roster-live and untombstoned** (R-c) | **stop that session, tombstone its record, then dispatch** — the manual middle step, performed in-fleet | 0 |
| **6** | claim `held`, holder record `limited` | dispatch. `sup-boot` verdicts `limit-transfer`. | 0 |
| **7** | claim `held`, heartbeat **stale**, holder **not roster-live** (incl. the unobserved-death case, §4.5) | dispatch. `sup-boot` verdicts `seize` and journals `SEIZED`. | 0 |
| **8** | claim `held`, holder record `dead`, heartbeat **fresh** — the **freeze window** | **REFUSE by default**, printing the G9 ambiguity and the `seizable in <n>s` remaining. `--force-frozen` overrides. | 2 |
| **9** | no claim at all | dispatch. `sup-boot` verdicts `claim`. | 0 |
| **—** | **fall-through: nothing matched** | **REFUSE:** *"a supervisor is on duty (claim `<inc>`, heartbeat `<n>`m ago) — nothing is owed. To rotate a healthy or wedged supervisor deliberately, use `fleet respawn supervisor`."* | 2 |

> **BINDING — the arms are EVALUATED IN A STATED ORDER, and the table above is not that order.**
> Several preconditions genuinely overlap, and a table of independent-looking conditions is how two
> arms fire on one state. The order is:
>
> **0 → 1 → 2 → 8 → 3 → 6 → 7 → 4 → 5 → 9 → fall-through.**
>
> Only three of those edges are load-bearing; the rest are free because the arms sit on disjoint claim
> states (`held` for 3/6/7/8, `released` for 4/5, absent for 9):
>
> - **8 before 3.** A `dead` record with a fresh heartbeat *and* a roster-live session is precisely the
>   G9 ambiguity — a body fleet declared dead whose session is still answering. If arm 3 saw it first
>   it would release-steer the thing arm 8 exists to refuse, auto-resolving the one state §5.4 says
>   requires a human. `--force-frozen` is the only way past it.
> - **6 before 7, and arm 3 excluding `limited`.** A limit-parked body is roster-live and *not*
>   steerable — it never receives another turn (G11) — so "alive and steerable" must not read it as
>   steerable. `respawn supervisor` already refuses a `limited` holder rc 2 by ruling 2 (§5.2), so an
>   arm-3 delegation there would burn a refusal to reach the arm that works.
> - **3 before 7.** A stale heartbeat with a roster-live holder is a supervisor that is alive and
>   merely delinquent about beating. Steering it is cheaper and safer than seizing from it — arm 7's
>   `seize` is the §5.9 residual that produces two bodies believing they hold the claim, so it must be
>   the path taken only when no live session answers.
>
> **The arm NUMBERS are frozen.** `docs/decisions/W9-section7-exemption.md` — the parked operator
> docket entry — cites arms 3, 5, 6 and 8 **by number**. Renumbering would silently rot an operator
> decision that is waiting to be answered, so the missing state above is added as a **fall-through**
> rather than as an arm 10, and the evaluation order is stated over the existing numbers.

> **The fall-through is the repair of a real hole, not tidiness.** As first written, arm 3's
> precondition was *"claim `held`, holder alive and steerable"* with no `succession_needed` gate — so
> it fired on **§4.4 row 8**, a `held` claim with a fresh heartbeat and no evidence of death. That is
> a **perfectly healthy fleet**, which the statusline, `sup-status` and `doctor` all render calm.
> `sup-recover` would have rotated a working supervisor, at whatever hour, and the operator's evidence
> that this was safe would have been that the verb exited 0. **A recovery verb must refuse when there
> is nothing to recover** — the name is the contract, and `fleet respawn supervisor` is the verb that
> already owns deliberate rotation (§5.2).

**Arm 8 is the only place a human judgement is required, and the verb says so rather than guessing.**
`freeze` exists because roster-gone with a fresh heartbeat is genuinely ambiguous between "the body
died" and "the daemon restarted" (G9). Auto-resolving it is how a live supervisor gets a rival.
`--force-frozen` is the operator asserting they have checked; the flag exists so the assertion is
typed, not inferred.

**Arm 5's stop is the only mutation `sup-recover` performs to another body**, and it is
target-restricted by construction: the sid it stops is `claim["released_by_sid"]` and the record it
tombstones is the one whose `_record_sids` contains it. There is no name argument by which it could be
aimed elsewhere — the same structural property `_tombstone_releasing_body` relies on (R13).

> **Arm 5 when the releaser has NO registry record — specified, because this happens and has cost
> hours.** An **interface session has no registry record at all**: it is not a fleet-launched body. If
> such a session ever holds and releases the claim, `claim["released_by_sid"]` names a sid that **no
> record carries**, and arm 5's "tombstone its record" step has no target. Neither "abstain", "error"
> nor "no-op" was stated. **The answer, and it falls out of shipped semantics rather than being
> invented:**
>
> 1. **Stop the session anyway.** The stop is keyed on the sid, not on a record, so it needs no
>    registry at all. This is the step that reaches the postcondition.
> 2. **Abstain from the tombstone, print that it abstained and why, and exit 0.** Not an error — there
>    is nothing to stamp, and `_tombstone_releasing_body`'s own three abstain arms (`UNRESOLVED`,
>    `AMBIGUOUS`, unreadable registry) already set the precedent of printing and returning `None`
>    rather than failing. **`UNRESOLVED` is exactly this case**, so arm 5 is adopting a posture, not
>    coining one.
> 3. **The postcondition still holds, and this is why the abstention is safe.** §5.4's binding
>    postcondition is *"after this step, no roster-live session answers for the outgoing body"*, and
>    the stop delivers it. B6 then disarms on its **second** arm rather than its first: measured (R22),
>    `_releaser_body_is_tombstoned` answers `False` when no record carries the sid (*"a record must
>    CARRY the sid for its tombstone to count"*), but `_releaser_live_sids`' next test is
>    `released_by in live_sids` — and once the session is stopped and off the roster, that is false
>    too. **The disarm is reached by the roster arm instead of the tombstone arm, and B6 does not
>    care which.**
>
> **What must NOT happen:** inventing a record to tombstone. Writing a registry row for a session
> fleet never launched would put a fabricated body in the roster, in a verb whose entire safety
> argument is that it never writes the claim and never guesses.

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
                  HEALTHY = it CLAIMED. `fleet sup-status` reads
                  `succession.needed: false`.
                  STILLBORN = the claim never moved: `succession.needed` still
                  true, same cause, `age_seconds` still growing, ~60s after this
                  line. Then: `fleet peek <name>` (its sid is stamped above) and
                  `fleet doctor`.
```

> **THE STILLBIRTH HEURISTIC, AND WHY IT IS THIS ONE.** An earlier draft of this block told the
> operator: *"if it is still `working` with 0 turns after 300s it is stillborn — `fleet peek <name>`."*
> **Both halves of that were defective, and it was the operator-facing instance of the retraction in
> §1.**
>
> **`0 turns` is not a fact about a session.** It is a registry accounting artifact
> (`knowledge/lessons.md`), and the sentence told the operator to key on the very artifact that made
> three days of stillbirths unreadable. Worse, it is a detector that **cannot fire on this verb's own
> path** — measured, not assumed: `_dispatch_supervisor_body` stamps `session_id`, `status =
> "working"` **and `turns = 1`** in one locked commit before the verb returns (R15). A `sup-recover`
> successor therefore reads `working, 1 turn` from the first instant it exists, healthy or dead. The
> old heuristic would have printed for every operator and fired for none.
>
> *(`fix/stillborn-handoff` gives `sup-handoff-begin`'s successor record the same stamp, closing the
> one path that still showed `0 turns`. That branch **removes** the last place the old heuristic could
> have fired; it does not threaten the new one, which never reads `turns` at all.)*
>
> **And it named the tool that lies in exactly that state.** `peek` prints *"no transcript yet —
> dispatch may still be in flight"* whenever `sid is None` (R16), while the transcript existed 2 s
> after dispatch. On this path the sid **is** stamped in that same locked commit, so `peek` is safe to
> name here — but only because the line above it prints the sid, and only for a dispatch that
> returned.
>
> **The replacement keys on the claim, which is the only always-fresh evidence there is.** Stated so
> an operator has an answer:
>
> | | healthy successor | stillborn successor |
> |---|---|---|
> | the claim | **moves** — `sup-boot` writes a `held` claim under `fleet_lock` | **never moves** |
> | `succession.needed` | flips to `false` (§4.8) | stays `true`, same cause, `age_seconds` still climbing |
> | registry row | `working, 1 turn` | `working, 1 turn` — **identical, and useless** |
> | roster | joined, stays | joined, then gone |
>
> **The registry row is the same on both sides. The claim is not.** That is the whole heuristic, and it
> is a restatement of the property D-GS1 was chosen for: *the alarm clears when a body **claims**, not
> when a body is **dispatched*** (§4.8). The operator is being asked to read the same signal this
> document specifies, which is why it needs no new mechanism and cannot drift out of sync with one.
>
> **Two things deliberately NOT said, because they are not true of every arm.** The claim's
> `incarnation_id` is **not** promised to change — `sup-boot` mints a fresh one on `claim`/`seize`, but
> `limit-transfer` moves an existing claim to the successor's sid (§4.8), so "look for a new
> incarnation id" would read as stillborn on a healthy arm-6 recovery. And the roster departure is
> **not** given a duration: 25–33 s is the measured death window for the `dontask` cause specifically
> (§10.3), and a body stillborn for some future reason need not die on that schedule. **`needed` is the
> only line in this table that is true on every arm, which is why it is the one the block prints.**
>
> **Why ~60 s and not 300 s.** The `handoff-autopsy` measured stillborn successors dying in **25–33 s**
> (17/17 mode↔outcome), and a healthy body's `sup-boot` claim is its first act. 60 s is roughly twice
> the measured death window; 300 s was five more minutes of an outage for no evidence. The number is a
> **floor on the operator's patience, not a timeout in the code** — nothing in `sup-recover` waits.

Grep-able terminal contracts on **stdout**, mirroring `SUP-KILL-*` / `SUP-RESPAWN-*`:
`SUP-RECOVER-DISPATCHED`, `SUP-RECOVER-REFUSED`, `SUP-RECOVER-HALTED`.

> **The `next:` block is not decoration.** It is the countermeasure to the failure that actually
> happened: a dispatched body reads as success from every surface fleet has. **`sup-recover` exits 0
> when a body has been dispatched, not when a supervisor exists**, and its own output says so in those
> words. Anything stronger would be the verb asserting something it has not measured — and per §4.8
> `succession_needed` stays `True` until that body claims, so the operator's other surfaces do not go
> quiet either.

### 5.7 Relationship to `sup-handoff-*` — settled, not left ambiguous

Three routes. **An earlier draft of this table called them *"disjoint by the outgoing body's liveness,
the only classifier that needs no judgement"*. That was false, and §5.4 is where it is visible:** arm 3
fires on *"the holder is roster-live and steerable"* and **delegates to `respawn supervisor`** — so the
two are not disjoint on liveness, they **overlap on it deliberately**. The correction matters because a
reader who believes the routes are disjoint will read arm 3 as a contradiction and pick one of them to
delete.

**What is actually true:** `sup-recover` is a **dispatcher, not a fourth mechanism** (§5.3). It is
classified by **what is owed**, and the other two by **what the outgoing body can still do**:

| Route | Precondition | Driven by | Status |
|---|---|---|---|
| `sup-handoff-begin` / `-complete` | the outgoing body is **healthy and in-band** — it can mint a token, poll, complete | the outgoing body | the **designed** in-band route, and **currently UNREPAIRED** — see below. Unchanged by this spec. |
| `fleet respawn supervisor` | the holder is **alive and steerable** — invoked deliberately, whether or not anything is owed | the interface | **UNCHANGED.** It remains the verb for a *rotation*, and `sup-recover`'s fall-through hands a healthy fleet back to it. |
| **`fleet sup-recover`** | **`succession_needed is True`** — a supervisor is owed. The outgoing body may be released, parked, dead, silent, absent, **or alive and steerable** (arm 3, which delegates rather than duplicating) | the interface | **FALLBACK** to the first, **PEER** to the second. |

**So the honest one-line distinction is not liveness, it is: `respawn supervisor` answers "replace this
supervisor"; `sup-recover` answers "this fleet has no supervisor — fix that", and delegates to
`respawn supervisor` on the one state where that is the cheapest way to fix it.** On a fleet where
nothing is owed, `sup-recover` refuses and names the other verb (§5.4 fall-through).

> **An earlier draft of this table called the handoff route "PREFERRED". That was wrong and the
> correction is load-bearing.** `sup-handoff-begin` under its shipped default has been **stillborn on
> every attempt** — three during this incident, **eight across the two days** the corpus counts
> (`skills/fleet/SKILL.md`, `knowledge/lessons.md`) — and **three supervisors in a row have now
> released at the ceiling rather than hand off**, because `sup-spawn` is the route that demonstrably
> works. *(This spec previously said "three" throughout, which was this incident's count read as the
> total. The eight is the corpus figure and it is the one that matters for the word "unrepaired".)* The
> incarnation
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

> **Scoped by measurement: this refusal can only ever fire on a `held` claim — arms 3, 6, 7 and 8.**
> A *released* claim cannot carry the marker, because `cmd_sup_release` writes a fresh six-key dict and
> drops every other key unconditionally (R17). So **arms 4 and 5 are unreachable by this refusal**, and
> the earlier concern that a released claim might still carry a minted token is closed (§10.2 A2).
> **This narrows where the refusal bites; it does not weaken it** — and it does not touch the separate,
> parked question of whether the refusal should stay at all, which the operator docket carries
> alongside the §7 question (`docs/decisions/W9-section7-exemption.md`, Route B, second half). The
> break lens's point there stands and is not re-argued here: **repairing the handoff makes this
> refusal MORE frequent, not less.**

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
- **`resets HH:MM` is appended only on `holder-limited`**, rendered as
  `_reset_clock(sup["succession_reset_at"])` — **the fourth key from §4.3.2, not a join against
  `snap["workers"]`**, which is not producible: those rows carry `limit_reset_at` but no `session_id`,
  and `snap["supervisor"]` carries no holder sid (R19). `_reset_clock` is reused exactly as it stands,
  as the pure ISO→`HH:MM` formatter it already is. **When `succession_reset_at` is `None` the segment
  is omitted entirely** — never `reset?`, which the worker bucket prints for a *group* whose members
  disagree; a single claim holder has nothing to disagree with, and an unknown reset time is silence,
  not a rendered question mark. It is a flag; **the statusline never launches a resume** (invariant 1).
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
- `sup-status` stays a **read-only view**: no lock, no probe, no write. **This addition must not change
  that, and that REQUIREMENT is unchanged.**

  > **The framing this bullet used to carry has been retired, and the correction is a caution rather
  > than a relaxation.** It read: *"it is one of only **three** verbs measured lock-free and
  > non-quarantining in terminal-surface's D4 receipts."* That was true when written and is **false at
  > `cebae4f`**: `wave2/doctor-repair` merged, so `peek`, `result` and `doctor` are now lock-free too,
  > and **no read surface quarantines any more** — only bare `fleet status` still takes `fleet.lock`.
  > Measured on this base, not inferred from the merge commit.
  >
  > **D4's own receipts still say the old thing, and that is correct behaviour, not a second defect.**
  > They are pinned `# at 02bf276` — a receipt is a claim about a commit — so they will keep reporting
  > the pre-`doctor-repair` world until someone deliberately re-pins them. **The trap for the next
  > author is reading a green receipt as a description of shipped code.** It is a description of
  > `02bf276`. Root `CLAUDE.md` has already been updated to the post-repair statement; D4's prose in
  > `docs/specs/terminal-surface.md` has not, and that gap is filed as A9.
  >
  > **Why the requirement survives its framing dying.** `sup-status` being lock-free is not valuable
  > because it was rare; it is valuable because `/fleet:overview` shells out to it and the statusline's
  > doctrine forbids the alternative. **A scarcity argument for a correctness property was the weak
  > part of the sentence** — the property does not need company to be required.

### 6.3 The `fleet doctor` check

**Name: `supervisor-succession`.** A **26th** check, appended after `_doctor_check_supervisor_claim`.

> **The ordinal moved under this document, and it will move again — so here is the audit rather than
> just the new number.** Measured, not asserted: R23's command returns **24** at `c318224` and **25**
> at `cebae4f`. So this section's *"a 25th check"* and §3's *"24 checks"* were **both correct at the
> base they were written against**, and both went stale when `idx/core` merged. The new row is
> therefore the **26th**. `docs/SPEC.md` §13 says **23**, which was wrong before this branch existed
> and is not this slice's regression.
>
> **The lesson is not "someone miscounted".** It is that **a check count is a fact about `bin/fleet.py`
> on the day it is read**, and this document embedded it as a literal in two places written at
> different times. §3 and §6.3 now both cite **R23**, so the next re-measure updates one receipt
> instead of hunting prose. Doc-sync item: A3.

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

**Q. Does anything here depend on `sup-handoff-*`, which has never completed under its shipped
default — three times during this incident, eight across the corpus?** **No** (§5.7).
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

**New in the 2026-07-28 revision, one test per repaired defect** — each of these pins a hole that a
correct-looking build would fall into, so none of them is covered by the tables above:

- **The M5 seam (§4.3.1).** `status_snapshot()` must produce a complete verdict while calling
  `_read_registry_readonly` **exactly once**. Assert on the call count, not on the output — the output
  is identical either way, which is what makes the double-read invisible without this test.
- **`registry=None` is legal.** `_supervisor_tier_snapshot()` called with no registry returns rows 7/8
  by the heartbeat, never an exception and never a `holder-*` cause it has no evidence for.
- **The fall-through (§5.4).** `sup-recover` against a **healthy** fleet — `held`, fresh heartbeat, no
  evidence of death — exits **rc 2** and names `fleet respawn supervisor`. **It must not dispatch and
  must not delegate.** This is the row-8 hole and it is the one an operator would meet first.
- **Arm ordering, as three tests, not one.** 8 before 3 (a `dead` record with a fresh heartbeat and a
  roster-live session REFUSES rather than steering); 6 before 7 with arm 3 excluding `limited`; 3
  before 7 (stale heartbeat + roster-live steers rather than seizing).
- **Row 5's `dead-suspected` half has a detail string (§4.6).** Assert the fallback fires and that its
  wording matches the `dead` half's shape — a test that only checks "not None" would pass on a
  traceback repr.
- **`succession_reset_at` (§4.3.2).** Populated only on `holder-limited`; `None` on every other cause;
  and the statusline **omits the segment entirely** when it is `None` rather than rendering `reset?`.
- **Arm 5 with no carrier record (§5.4).** A releaser sid that no registry record carries: assert the
  stop happened, the tombstone **abstained without erroring**, and rc 0.
- **§5.6's `next:` block never mentions turns.** A literal string test over the emitted block. Cheap,
  and it is the pin that would have caught the retracted heuristic.

**Fault injections the gate should demand come back RED** — (i) clear the flag on `sup-spawn`;
(ii) render `succession_age_seconds` into `heartbeat_age_seconds`; (iii) make the statusline take
`fleet.lock`, or fetch the roster, to answer the predicate; (iv) let arm 0 key on `FLEET_WORKER`
instead of claim-holdership; (v) let `sup-recover` write `supervisor/INCARNATION` directly;
(vi) make `needed is None` PASS; (vii) decide the unobserved-death case from the registry status
alone; (viii) widen any cause to a condition fleet cannot observe without an injection (§1.2);
**(ix) let `_supervisor_tier_snapshot` read the registry itself instead of taking the threaded one
(§4.3.1) — this one goes red only against the call-count assertion, which is why it is named;
(x) let arm 3 fire with `succession_needed is False`, i.e. delete the fall-through (§5.4);
(xi) key any stillbirth advice on `turns` (§5.6).**

### 8.1 The one non-spec file this slice touches

`tests/test_receipts.py` gains a `RECEIPT_FLOOR` entry for this document. Every spec under
`docs/specs/**` is required to have one — `test_every_enforced_spec_has_a_receipt_floor` fails without
it — so adding a spec without adding the floor leaves the suite red. **`bin/fleet.py` is untouched**
(R9, and `git status --porcelain`).

---

## 9. Receipts

Re-executed against the materialised tree of `cebae4f` by `tools/verify_receipts.py`. No block is
`# volatile` or `# live`: every one is a `grep`, `sed` or `echo` over a file in the repo, so they are
ordinary pinned receipts and no evidence here lives outside it.

**Every block below was RE-EXECUTED for this revision, not re-pinned.** The base moved from `c318224`
to `cebae4f` across ~2,375 lines of `bin/fleet.py`, so the previous outputs' line numbers were all
stale. R1–R14 each still hold **structurally** — every anchor is still there and still says the same
thing — but not one of them still holds *textually*, which is the entire reason the rule exists.

**NO BLOCK BELOW QUOTES A MUTATING VERB.** Every command is a read: `grep`, `sed`, `echo`. This is
worth stating rather than assuming — a draft receipt on a sibling branch ran a real sweep three times
and archived six live records, because a receipt is *executed*, three times over (author, verifier,
CI), against whatever state it finds. **A receipt that mutates is a defect however true its output.**

**R1 — the statusline's four supervisor words. None means "outage".**

```
# at cebae4f
$ grep -n "_SUP_STATE_LABEL = " -A 1 bin/fleet_statusline.py
123:_SUP_STATE_LABEL = {"held": "sup held", "released": "sup released",
124-                    "none": "sup none", "unknown": "sup ?"}
```

**R2 — a live supervisor body leaves the worker buckets, so a `limited` supervisor is in no bucket.**

```
# at cebae4f
$ grep -n 'if w.get("tier") == "supervisor" and w.get("status") != "dead":' -A 1 bin/fleet_statusline.py
186:        if w.get("tier") == "supervisor" and w.get("status") != "dead":
187-            continue
```

**R3 — the supervisor projection carries four keys; none is a verdict.**

```
# at cebae4f
$ grep -n 'out = {"goals_active": False, "state": "none",' -A 1 bin/fleet.py
3029:    out = {"goals_active": False, "state": "none",
3030-           "incarnation_id": None, "heartbeat_age_seconds": None}
```

**R4 — `sup-status --json`'s eight keys; none is a succession verdict.**

```
# at cebae4f
$ grep -n '^        "goals_active"\|^        "incarnation"\|^        "heartbeat_age_seconds"\|^        "handshake"\|^        "abort_flag"\|^        "pending_decision"\|^        "interface_divergence"\|^        "nag"' bin/fleet.py
13078:        "goals_active": supervisor_goals_active(),
13083:        "incarnation": _project_claim(claim),
13084:        "heartbeat_age_seconds": beat_age,
13085:        "handshake": _project_handshake(hs),
13086:        "abort_flag": handoff_abort_flag_path().exists(),
13087:        "pending_decision": read_pending_decision(),   # §8: routing surface
13088:        "interface_divergence": _interface_divergence(),  # §5.3: B7 detection
13089:        "nag": supervisor_status_line(),
```

**R5 — the only two supervisor rows in doctor's check list.**

```
# at cebae4f
$ grep -n "functools.partial(_doctor_check_supervisor" bin/fleet.py
9122:        functools.partial(_doctor_check_supervisor_claim),
9123:        functools.partial(_doctor_check_supervisor_handoff),
```

**R6 — `limited-parks` is always `ok=True`, so a limit-parked supervisor reads `[PASS]`.**

```
# at cebae4f
$ grep -n 'return ("limited-parks"' bin/fleet.py
8163:        return ("limited-parks", True, "no usage-limit parks")
8176:    return ("limited-parks", True, " | ".join(parts))
```

**R7 — `respawn supervisor` on a released claim refuses and hands the operator back to `sup-spawn`.
This is window A's state, and it is what §5.1 R-a is about.**

```
# at cebae4f
$ grep -n 'is released -- there is no holder to respawn' -A 1 bin/fleet.py
5987:            detail = (f"claim {inc} is released -- there is no holder to respawn. "
5988-                      f"Boot a fresh body with `fleet sup-spawn --task <brief>`.")
```

**R8 — `sup-release`'s `reason` is free text on the claim: the string that was accurate and unread.**

```
# at cebae4f
$ grep -n 'released\["reason"\] = reason' -B 1 bin/fleet.py
12924-        if reason:
12925:            released["reason"] = reason
```

**R9 — `[UNBUILT]`: nothing this spec specifies exists yet, in either file.**

```
# at cebae4f
$ grep -c "succession_needed\|succession_cause\|sup-recover\|sup_recover" bin/fleet.py bin/fleet_statusline.py
bin/fleet.py:0
bin/fleet_statusline.py:0
$ echo "exit $?"
exit 1
```

**R10 — the ceiling refuses at FIVE call sites, `respawn` twice. Cited by grep, never by line number,
per the operator's binding process condition (§3.1).**

```
# at cebae4f
$ grep -n '_ceiling_refuses_dispatch("' bin/fleet.py
3838:    _ceiling_refusal = _ceiling_refuses_dispatch("spawn")
4956:    _ceiling_refusal = _ceiling_refuses_dispatch("send")
5414:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
5627:        _ceiling_refusal = _ceiling_refuses_dispatch("respawn")
13470:    _ceiling_refusal = _ceiling_refuses_dispatch("sup-spawn")
```

**R11 — the G11 limit-park writer: the seam that produces the input row 4 reads, and the reason row 4
is not always fresh.**

```
# at cebae4f
$ grep -n 'updated\["status"\] = "limited"' -B 2 -A 2 bin/fleet.py
2813-        is_limit, reset_at, kind = scan(sid, transcript_path=path)
2814-        if is_limit:
2815:            updated["status"] = "limited"
2816-            updated["limit_reset_at"] = reset_at
2817-            updated["limit_kind"] = kind
```

**R12 — the four functions §4.2 composes: the lock-free non-quarantining reader, the projection that
gains the four keys, the snapshot that publishes them, and the shipped precedent for reading the
holder's record from a view path (`_claim_holder_dead_note`, called by `supervisor_status_line`).**

```
# at cebae4f
$ grep -n "def _read_registry_readonly\|def status_snapshot\|def _claim_holder_dead_note\|def _supervisor_tier_snapshot" bin/fleet.py
2985:def _read_registry_readonly() -> tuple:
3005:def _supervisor_tier_snapshot(now=None) -> dict:
3050:def status_snapshot(now=None, include_archived: bool = False) -> dict:
14427:def _claim_holder_dead_note(claim, inc, age):
```

**R13 — the tombstone as SHIPPED, not as proposed: the disarm arm B6 decides through, the site that
consults it, and the own-record writer `sup-release` calls (§5.1).**

```
# at cebae4f
$ grep -n "def _releaser_body_is_tombstoned\|_releaser_body_is_tombstoned(released_by, registry)\|def _tombstone_releasing_body" bin/fleet.py
11218:def _releaser_body_is_tombstoned(released_by, registry) -> bool:
11339:    if _releaser_body_is_tombstoned(released_by, registry):
12759:def _tombstone_releasing_body(caller: str, inc: str):
```

**R14 — the tombstone's SCOPE: `_tombstone_releasing_body` has exactly one caller, and it is inside
`cmd_sup_release` (`:13146`). Nothing on the kill path, no timer, nothing that notices a body which
simply stopped — so a usage-limit park can never tombstone itself (§5.1.1).**

```
# at cebae4f
$ grep -n "_tombstone_releasing_body\|^def cmd_sup_release" bin/fleet.py
11223:    own record (`_tombstone_releasing_body`), so `_releaser_live_sids` below is
12759:def _tombstone_releasing_body(caller: str, inc: str):
12851:def cmd_sup_release(args) -> int:
12884:    that just released. See `_tombstone_releasing_body` for own-record-only and
12928:        retired = _tombstone_releasing_body(caller, inc)
```

Of the five hits, `11223` and `12884` are docstring prose, `12759` is the definition, `12851` is the
enclosing function, and **`12928` is the sole invocation**.

---

*Receipts below are NEW in the 2026-07-28 revision. They exist because this revision makes claims the
original did not, and every one of them replaced a sentence that had been asserted rather than
measured.*

**R15 — `sup-recover`'s own dispatch path stamps `session_id`, `status` AND `turns = 1` in one locked
commit before the verb returns. So a `sup-recover` successor NEVER reads `0 turns`, healthy or
stillborn, and §5.6's old heuristic could not have fired.**

```
# at cebae4f
$ grep -n "def _dispatch_supervisor_body\|def _commit_native_stamp" bin/fleet.py
3963:    def _commit_native_stamp():
13481:def _dispatch_supervisor_body(campaign, mode, model, *, run=subprocess.run,
13577:    def _commit_native_stamp():
$ sed -n '13582,13585p' bin/fleet.py
                rec["session_id"] = sid
                rec["native_short_id"] = short_id
                rec["status"] = "working"
                rec["turns"] = 1
```

**R16 — `peek`'s no-transcript sentence, which is the tool §5.6 used to send the operator to. It is
keyed on `sid is None`, and the sid is stamped by R15's commit — so on THIS path it is safe to name,
and only on this path.**

```
# at cebae4f
$ grep -n 'no transcript yet' bin/fleet.py
4299:        print(f"{name}: no transcript yet -- dispatch may still be in flight", file=sys.stderr)
```

**R17 — A2's hazard cannot occur: `cmd_sup_release` writes a FRESH dict, so every key not in this
literal — including `handoff_pending` and `handoff_token_hash` — is dropped on every release,
unconditionally.**

```
# at cebae4f
$ grep -n 'released = {"incarnation_id": inc,' -A 8 bin/fleet.py
12918:        released = {"incarnation_id": inc,
12919-                    "lineage_id": claim.get("lineage_id"),
12920-                    "claimed_via": claim.get("claimed_via"),
12921-                    "released_at": now_iso(),
12922-                    "released_by_sid": caller,
12923-                    "state": "released"}
12924-        if reason:
12925-            released["reason"] = reason
12926-        write_incarnation(released)
```

**R18 — the M5 seam: `status_snapshot` has ALREADY read the registry (`:3061`) by the time it calls
the projection (`:3074`), and passes it nothing. §4.3.1 threads it in rather than letting the build
read it twice on every statusline refresh.**

```
# at cebae4f
$ grep -n -A 25 "^def status_snapshot" bin/fleet.py | grep "_read_registry_readonly\|_supervisor_tier_snapshot"
3061-    ok, reason, data = _read_registry_readonly()
3073-        # File-only, never raises: see `_supervisor_tier_snapshot`.
3074-        "supervisor": _supervisor_tier_snapshot(now),
```

**R19 — §6.1's `resets HH:MM` is not producible from the specified data shape. `_reset_clock` is a pure
ISO→`HH:MM` formatter (fine); the snapshot's worker rows carry NO `session_id`, so there is no join key
from the claim to the holder's row. Hence §4.3.2's fourth key.**

```
# at cebae4f
$ grep -n "def _reset_clock" -A 1 bin/fleet_statusline.py
92:def _reset_clock(iso) -> str:
93-    """'2026-07-09T14:20:00Z' -> '14:20'. Any other shape -> the raw value."""
$ grep -n 'rows.append({' -A 26 bin/fleet.py | grep -c '"session_id"'
0
$ echo "exit $?"
exit 1
```

**R20 — row 0 swallows an UNREADABLE `GOALS.md`: `supervisor_goals_active` returns the same `False` for
"parked" and for "will not decode", and row 0 is first in precedence (§4.4).**

```
# at cebae4f
$ grep -n "def supervisor_goals_active" -A 9 bin/fleet.py
14415:def supervisor_goals_active() -> bool:
14416-    """GOALS.md exists, decodes, and is not parked. Operator parks the nag by
14417-    adding the literal token SUPERVISOR-DORMANT anywhere in GOALS.md.
14418-    ValueError covers UnicodeDecodeError: an undecodable GOALS.md must not
14419-    crash the unguarded read-only callers (cmd_sup_status, views)."""
14420-    try:
14421-        text = goals_path().read_text(encoding="utf-8")
14422-    except (OSError, ValueError):
14423-        return False
14424-    return "SUPERVISOR-DORMANT" not in text
```

**R21 — `_claim_holder_dead_note` answers for `dead` ONLY, so §4.4 row 5's `dead-suspected` half has no
borrowed string and needs the §4.6 fallback.**

```
# at cebae4f
$ grep -n 'if holder is None or holder.get("status") != "dead":' -A 1 bin/fleet.py
14459:    if holder is None or holder.get("status") != "dead":
14460-        return None
```

**R22 — why arm 5 may abstain from the tombstone when no record carries the releaser's sid: the
tombstone arm needs a carrier (`bool(carriers)`), but B6's disarm has a second, roster arm that the
stop alone satisfies (§5.4).**

```
# at cebae4f
$ grep -n "carriers = \[rec for rec in workers.values()" -A 2 bin/fleet.py
11265:    carriers = [rec for rec in workers.values()
11266-                if released_by in _record_sids(rec)]
11267-    return bool(carriers) and not any(_record_is_live(rec) for rec in carriers)
```

**R23 — the doctor check count, RE-MEASURED. It is 25, not the 24 this document carried and not the 26
a reader might infer from "a 25th check". §3's row and §6.3's ordinal both key on this.**

```
# at cebae4f
$ grep -c "functools.partial(_doctor_check" bin/fleet.py
25
```

*Cross-checked against a live run rather than trusted as a static count: `py -3.13 bin/fleet.py doctor`
emits exactly **25** `[PASS|FAIL|WARN]` rows, one per partial. The live run is deliberately **not**
pasted as a receipt — its output is machine- and moment-dependent (roster contents, hook smoke, an
uninitialised probe home), and a receipt that cannot reproduce is worse than a prose note that says so.*

---

## 10. Part 4 — what I could not settle

Split as required: **design choices I made** (overturnable by the gate) versus **ratifications the
operator owes** (which I may not make).

### 10.1 Design choices — mine, and why

| # | Choice | Reason | How to overturn |
|---|---|---|---|
| ~~**O1**~~ | ~~**Derived, never stored** (D-GS1).~~ **MOVED to §10.2 as A8 — this was misfiled.** | The technical argument (§4.1) is unchanged and still mine. Its **status** is not: D-GS1 deviates from the ratified word *"records"*, and a deviation from ratified wording is the operator's to accept, not a design choice the gate may overturn. **§4.11 states it as a finding.** | not overturnable at this table — see A8 |
| **O2** | Undecidable **claim** → FAIL; unreadable **registry** → quiet. | §4.5, §7. | Show that an unparseable `supervisor/INCARNATION` can occur transiently. If it can, this flips. |
| **O3** | Row 7 promotes an **admittedly false-fireable** heartbeat read from advisory nag to doctor FAIL. | §4.7. It is the only always-fresh detector of the silent half, and its "false" alarm is a true alarm about checkpoint discipline with a one-command remedy. | **The most attackable decision in the document; the gate should attack it.** |
| **O4** | `dead` and `dead-suspected` fold into one status test, split by heartbeat into rows 5/6. | §4.4. | One enum value; cheap to change. |
| **O5** | The alarm hue is **reused** for `sup DOWN` and `N bodies`. | §6.1. Same class of event; a second red is indistinguishable on one line. | A reviewer with a stronger claim about colour budget. |
| **O6** | Verb named `sup-recover`; `--task` optional. | §5.3, §5.5. | Cheap before build, expensive after. |
| **O7** | `sup-recover` **never writes the claim**; it dispatches and lets `sup-boot` adjudicate. | §5.9. This is what makes the two-bodies argument structural rather than promised. | Do not overturn without replacing the safety argument. |
| **O8** | **No worker-scoped hook**, though the brief permits one. | §2 — G11 says a limit wall fires no hook, and no hook fires for a body that never gets a turn. | Only by falsifying G11. |
| **O9** | The doctor row FAILs during the dispatch→claim window. | §6.3 note 4. That window was permanent three times on the night. | ~~If the stillbirths are root-caused and fixed, revisit.~~ **They now are** (§10.3, `fix/stillborn-handoff`) — and the choice **stands**, re-argued rather than inherited: the root cause was on the `sup-handoff-begin` path, which `sup-recover` does not use, and the window this row FAILs on is *"dispatched but not yet claimed"*, which is a true statement about the fleet whatever made the dispatch fail. A fixed cause makes the window shorter, not absent. |
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
| **A2** | ~~**`claim-nonce` §6.3's post-release key set does not say what happens to `handoff_pending` and `handoff_token_hash`.**~~ **DOWNGRADED — the hazard was measured and cannot occur; only the doc gap survives.** §6.3 enumerates seven keys kept and six removed and these two are in neither list, so the **documentation** gap is real. The **hazard** this row escalated — *"a released claim still carrying a minted token"* — **cannot happen in shipped code** (R17): `cmd_sup_release` does not mutate the claim, it **builds a fresh dict** of six keys (`incarnation_id`, `lineage_id`, `claimed_via`, `released_at`, `released_by_sid`, `state`) plus an optional `reason`, and hands that to `write_incarnation`. **Every key not in that literal is dropped on every release, unconditionally, including both handoff keys.** So `sup-recover`'s §5.7 refusal can never fire on a released claim, and no superseded successor can validate against a token that is not there. | ~~operator~~ **doc-sync** | **Closed as an escalation by measurement.** What remains is that §6.3's key set does not *say* this, so a future edit could regress it with nothing to catch it. That is a doc-sync item and a test obligation (§8), not a question for the operator. **This row escalated a question shipped code answers in six lines, and I should have grepped before escalating.** |
| **A8** | **D-GS1 deviates from the ratified word *"records"*** — the ratified shape says *"a supervisor that can no longer dispatch **records** a machine-readable succession-needed fact with its cause"*; this spec's answer is that **nothing records it and there is no writer** (§4.11). **Moved here from §10.1 O1**, where it was misfiled as a design choice of mine. | **operator** — it is their wording | The technical argument is sound and I stand behind it (§4.1), but *"is this deviation acceptable"* is not a question a supervisor may answer about an operator's ratified element. **Stated as a finding (§4.11), designed as specified, and flagged rather than smoothed over.** Falsifier named: a consumer that needs the fact when no reader is running. |
| **A3** | **A ~~25th~~ 26th doctor check that can FAIL changes `fleet doctor`'s exit-code contract for a new class of condition,** and `docs/SPEC.md` §13 records the roster and a check count. **Three documents now disagree about that count**: this spec said 24, `docs/SPEC.md` says **23**, and the measured value at `cebae4f` is **25** (R23). SPEC.md's number was wrong before this branch existed, so it is not this slice's regression — but it is now three-way, and the new row makes it 26. | operator / doc-sync | Adding a FAIL-capable row is a policy change about what makes doctor red, and the count is a ratified number. **The count itself is now measured rather than asserted (R23); what is owed is the ratification and SPEC.md's correction, not the arithmetic.** |
| **A9** | **`docs/specs/terminal-surface.md` D4's prose is stale in the *under*-claiming direction.** It reads *"a REQUIREMENT, not a description: VIOLATED by every read-only `/fleet:*` command at `02bf276`"*, and its receipt tables show `peek`/`result`/`doctor` taking the lock and quarantining. **`wave2/doctor-repair` merged and that is no longer true** — measured on this base: only bare `fleet status` still takes the lock, and **nothing quarantines from a read surface**. Root `CLAUDE.md` has been updated; D4 has not. Its receipts are correctly pinned at `02bf276` and are **not** the defect — the surrounding prose, which reads as present tense, is. | doc-sync (**not** operator: D4's REQUIREMENT is unchanged and nothing is being narrowed) | **Filed, not fixed — outside this slice's scope fence** (`docs/specs/terminal-surface.md` is another document's). Raised because §6.2 cited that framing and a reader following the citation lands on prose that contradicts shipped code. |
| **A4** | **`skills/fleet/supervisor.md` is stale about the respawn ceiling** (§3.1, R10) — it still says the ceiling covers *three* verbs and *"does not yet cover `fleet respawn`"*, which now contradicts a ratified decision (`d543691`) as well as shipped code. Still present at `c318224`. **Note for whoever fixes it: the sentence wraps as `It does` / `not yet cover`, so a single-line grep for the phrase returns nothing and reads as already-fixed.** I nearly recorded it as discharged on exactly that mistake. | doc-sync; **outside this slice's scope fence** (`skills/**`) | Filed, not fixed. |
| **A5** | ~~§11.3's enumeration must name task-bearing `respawn` and `sup-spawn`, edited by grep rather than by the three cited line numbers.~~ **DISCHARGED at `d543691`** while this spec was being written — §11.3 now names all four verbs and marks the `--task` discriminator normative. Left in the table rather than deleted, because a row that silently disappears is indistinguishable from one that was never raised. | ~~doc-sync~~ **done** | Nothing owed. Verified rather than assumed: `d543691` touches `docs/specs/three-tier-command.md` only, so re-pinning the receipts across it changed no output. |
| **A6** | **Whether a test pins "a released claim renders no age"** (§6.1). I did not read the statusline test suite. | builder + gate | Asserting either way would be a claim I had not measured. **Stated as unverified.** |
| **A7** | **`sup-recover`'s exact rc values.** This spec reuses `SupervisorLifecycleRefusal`'s rc 2 / rc 3 split and `sup-boot`'s rc 4. I did not re-derive every constant. | builder | Named so the build confirms rather than infers. |

### 10.3 Two things I could not determine at all — one has since been determined by someone else

- ~~**Why the three successors were stillborn.**~~ **ANSWERED on `main` while this document sat at the
  gate, and the answer inverts what an earlier draft of this section said.** Journal I-E's `dontask`
  lead — which this section recorded as *"a hypothesis, not a finding"* with counter-evidence attached,
  and which a subsequent entry declared **falsified** — **was correct.** `handoff-autopsy` re-derived it
  by measurement: 7/7 successors dispatched under `bypass` booted and completed; 10/10 under `dontask`
  were stillborn, showing two `permission-rule` denials and dying in 25–33 s. **17/17, no exceptions.**
  The falsification was a confounded probe and is retracted (`knowledge/lessons.md`); the fix lands in
  `fix/stillborn-handoff` (`SUCCESSOR_DEFAULT_MODE = "bypass"`, plus the sid stamp and the `peek`
  correction). **Recorded here rather than deleted**, because the retraction of a falsification is
  exactly the kind of fact a later reader needs and a tidied table would hide.
  **This spec was designed not to need the answer and still does not:** `sup-recover` routes through
  `_dispatch_supervisor_body` (the `sup-spawn` path, which has been working) rather than through
  `sup-handoff-begin` (the path that failed), and §5.6's exit-0 contract assumes a dispatch can be
  stillborn. What *did* change is §5.6's heuristic, which was built on the false half of the record.
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
| `docs/SPEC.md` | §13 doctor roster | **A3** — 26th check `supervisor-succession`; the roster count changes. **And SPEC.md's stated count is `23`, which was already wrong before this branch existed — measured 25 at `cebae4f` (R23).** Correcting that is doc-sync's, independent of this spec landing. | operator / doc-sync |
| `docs/specs/terminal-surface.md` | D4 prose | **A9** — D4 still reads *"VIOLATED by every read-only `/fleet:*` command"*; `wave2/doctor-repair` merged and it is not. Its **receipts** are correctly pinned at `02bf276` and are not the defect; the present-tense prose around them is. **Filed, not fixed — another document's.** | doc-sync |
| `skills/fleet/SKILL.md` | Succession bullet (`:95`) | **DONE in this slice.** It stated *"the old middle step is gone … nobody stops the retired body to make succession work"* **unqualified**, which is false on both walls the signal fires on, in the file an interface session reads at startup. Now qualified to the clean-release path, with both walls named, the retraction of *"0 turns"* carried, and the stillbirth root cause pointed at. **`skills/**` was outside the original scope fence; the operator brief for this revision put this file explicitly in scope.** | ~~doc-sync~~ done |
| `skills/fleet/supervisor.md` | Handoff section | **A4** — the respawn-ceiling paragraph is stale (R10). **Still outside scope and still filed, not fixed** — the widened fence named `SKILL.md`, not this file. Re-verified present at `cebae4f`. | doc-sync |
| `skills/fleet/supervisor.md` | Standing down | when `sup-recover` ships, the recipe becomes *release, then stop* for the supervisor and *`fleet sup-recover`* for the interface — one command, not three. **Outside scope; filed.** | doc-sync |
