# Autonomous run — 2026-07-26 (day 4)

Operator directives for this run (given in-session):
1. Continue the day-3 autonomous build-out: churn the spec backlog + testing until fleet is a
   full build, launch-ready.
2. **"work autonomously, I will be away."**
3. **"you are supposed to use the supervisor not manually summon workers"** — this session is the
   INTERFACE tier; the supervisor owns dispatch.

Standing from day 3, unchanged: operator-gated questions go to a **4-councilor council of
differing personalities + synthesis**; act on the synthesis; record every gated item here for
morning ratification. **Nothing in this file ticks a box in `docs/OPERATOR-GATES.md`** — only the
operator ticks.

## Shipped this run

- **`build/sup-tombstone` MERGED to main** (`a2358f2`, pushed) — SPEC §10.4 kill/respawn supervisor
  tombstone. This was the step day-3's supervisor could not take: it ran as a background job whose
  harness forbids merging or pushing `main`, so it took the work to the edge (PR #9, draft) and
  stopped. Interface-side verification before merge was already manager-run at `46244b8` (both
  floors 2152/11, live tier 3/3, `merge-tree` vs main = zero files changed in both); post-merge on
  `main` measured here: **2147 passed / 16 skipped on py3.13 AND py3.10** (identical 2163 total;
  the 5-test shift is the live tier skipping without `FLEET_LIVE=1`), receipts **56/56 reproduce
  exactly, 0 failures**. PR #9 needs closing/reconciling.
- **handoff-seams fix wave 2 dispatched** — worker `hs-fix2` (opus, bypass) on `fix/handoff-seams`
  @ `90e0ddf`, carrying rulings R9 + R10. In flight at the time of writing.

## G-D. The interface-release wedge — the run's gated incident

### What happened

This session ran `fleet sup-boot` at startup (per `docs/NEXT-SESSION.md`, which was written for a
session that would BE the supervisor) and took the claim as `inc-20260725T220334Z-5675`. Directive
3 then redefined this session as the interface tier. Acting on it, the session checkpointed,
ran `fleet sup-release`, and `fleet sup-spawn`ed a gen-0 supervisor
(`sup|inc-20260725T221152Z-c31a|boot`, opus, bypass).

Gen-0's `sup-boot` returned **`refuse`** — correctly, and it stopped without retrying, spawning or
seizing. Rule 1 / **guard B6** (`bin/fleet.py:10172-10176`) refuses to consume a `released` claim
whose `released_by_sid` is still roster-live. Doctrine: *"release, THEN stop."*

**The releaser is this interface session, which is alive by design and does not exit.** Verified
in `claude agents --json`: that sid carries `pid` + `status: busy`, `state != "done"`, so
`_roster_live_sids` counts it live for the session's whole lifetime.

**Consequence: the fleet has no supervisor and cannot boot one while this session lives.** Rule 1
has no caller exception, so even the releaser cannot re-claim. This is a **liveness defect**, not a
mis-typed command: B6 encodes a postcondition ("the releaser exits") that one legitimate caller
class can never satisfy.

### Root cause (council's framing, adopted)

**B6 keys on a proxy.** Its real predicate is *"the released claim's prior holder may still act as
supervisor."* Liveness of `released_by_sid` is an exact proxy when the releaser is a supervisor
body on its way out, and simply **wrong** when the releaser is a body that by construction never
acts as supervisor (`three-tier-command.md:715`: the interface *"holds no claim by construction"*).
The guard did not misfire — it read a signal that stopped meaning what it meant.

Second, deeper reading (Vista): the day-3 directive describing the switch-over as *"this session
releases its supervisor claim… and becomes the interface tier"* is describing a **bootstrap, not a
state transition**. The interface never legitimately held the claim, so the real rule is **an
interface session must never run `sup-boot`** — a rule that is currently neither enforced nor
recoverable-from.

### Council record — 4 councilors, then two adversarial follow-up rounds

| Councilor | Verdict |
|---|---|
| Cassandra (risk) | (a) — the only option where the attesting party is the one with the knowledge |
| Brick (delivery) | (a) — "adds a *fact* instead of removing a *check*" |
| Vista (strategy) | (a) initially; switched to (e) on coherence grounds after (e) was raised |
| Mercer (incident response) | (a), plus escalate the live wedge now |

Options scored: **(a)** `sup-release --interface` — the releaser attests at release time that it
will not act; B6 skips liveness only for a record released that way. **(b)** time-box B6.
**(c)** boot-side `--accept-live-releaser`. **(d)** do nothing, escalate, stall.

- **(b) rejected**: converts a fail-closed guard into a fail-open one on a timer, opening in
  exactly B6's motivating case (a slow-exiting supervisor). The repo's own
  `SUPERVISOR_RELEASE_TIMEOUT_SECONDS = 300.0` contradicts the 60–120s window anyone would reach
  for, and no value makes it sound. Mercer: "trades a loud wedge for a quiet violation."
- **(c) rejected**: inverts the trust direction — the booter would assert a fact about *another*
  body's future behaviour, which it cannot know, and any body finding a released record could pass
  it. A skeleton key on the one guard that matters.

**Two repairs were proposed to unwedge the CURRENT record, and both were killed on evidence.**
Recorded so they are not re-litigated:

- **(a+) post-hoc attestation by the recorded releaser** (caller sid must equal the recorded
  `released_by_sid`) — **FAILS, forgeable.** `--sid` is an override on every `sup-*` verb
  (`:12608-12711`) and otherwise comes from one env var (`:949`); `released_by_sid` is published in
  the claim file, which every body can read (§2.1, no privilege separation). The check's expected
  answer is handed to the forger and its input is env-settable, so it would *authorize* on the
  exact value rule 2 uses only to *de-authorize*.
- **(e) provenance — refuse only when the live releaser has a `sup|`-shaped registry record.**
  Attractive: the name is daemon-minted and `validate_name` makes the shape unrepresentable to
  callers. **FAILS: it is an ABSENCE predicate.** (1) `fleet clean` deletes records, so a body that
  wants B6 gone deletes the releaser's record; (2) archived records read as "never fleet-launched"
  — the registry holds **40 archived vs 7 live** and `status_snapshot()` excludes archived rows;
  (3) **decisive** — `sup-spawn` creates the record via `new_worker_record(None, …)` (`:11573`), so
  a genuine fleet-launched supervisor has *no sid-matching record during its dispatch window*
  (verified: 5 of 7 `sup|` records currently carry `session_id: None`). (e) would fail **open** in
  precisely the release→stop window B6 exists for.

**The distinction that survives**: (e) reads the ABSENCE of a record to permit; a boot-side check
reads the PRESENCE of the caller's own record to permit, and refuses otherwise. A positive check
fails closed; an absence check cannot.

### Synthesis (acted on)

1. **Build (a)** — `sup-release --interface`, fail-closed by default, absence of the attestation =
   today's behaviour exactly. Dispatched to the gen-0 body as a **builder in a worktree** (branch
   `fix/b6-interface-release`); it holds no claim and §6.6 concerns two *acting* supervisors, so
   nothing is violated and the interface does not hand-spawn a worker (Brick's call).
2. **Ship the honesty fixes** (Mercer, unopposed): `sup-status` currently ends every released claim
   with `-- no holder; \`fleet sup-boot\` claims fresh` (`:11197-11201`) — **a false prediction in
   this state, making the wedge indistinguishable from a healthy post-release state on the one
   surface an operator types.** Plus a `fleet doctor` FAIL (not a NOTE — a NOTE that does not move
   the verdict is invisible) computed from the same `_roster_live_sids` B6 uses, so the two can
   never disagree.
3. **Do NOT build (e)**; propose instead, for ratification, Vista's doctrine set:
   - *The claim belongs to a role, not to a body. The interface tier never runs `sup-boot`; it
     bootstraps a supervisor with `sup-spawn`.*
   - *A guard keyed on a proxy must name the predicate it proxies for.*
   - `[UNBUILT]` follow-up: gate `sup-boot` on the caller being a fleet-launched supervisor body,
     making the interface unable to take the claim **by construction** rather than by discipline.
4. **Escalate the live wedge** — see below. No agent hand-edits claim state (§5.7 is the operator's
   lever; day-3's predecessor refused the same reach and was right to).

## ESCALATION — operator action needed to unwedge the live claim

The fleet cannot boot a supervisor while session `adfda529-ee84-457e-a181-682dedefef1b` is alive.
Two remedies, in preference order:

1. **No hand-edit (preferred).** The wedge **self-clears when this interface session ends** — the
   sid leaves the roster and rule 1 verdicts `claim` again. From a fresh session:
   `py -3.13 bin/fleet.py sup-spawn --task @state/tasks/sup-campaign-day4.md`
   — and that session must **not** run `sup-boot` (that is what created this state).
2. **§5.7 lever, if a supervisor is wanted before this session ends.** Delete the
   `"released_by_sid"` line from `supervisor/INCARNATION` (current content is a 7-key released
   literal; `state` stays `"released"`). Rule 1 then finds no releaser to test and claims fresh.
   This is an out-of-band mutation of claim state and is the operator's call alone.

## Dispatch record

- `hs-fix2` (opus, bypass, worktree `C:/proga/fleet-handoff-seams`, branch `fix/handoff-seams`):
  handoff-seams **fix wave 2** per rulings R9 + R10, brief `state/tasks/hs-fixwave2-dispatch.md`.
  Last wave before the final gate; a 3rd needs escalation.
- `sup|inc-20260725T221152Z-c31a|boot` (opus, bypass, own worktree, branch
  `fix/b6-interface-release`): the (a) build + honesty fixes, brief
  `state/tasks/b6-interface-release.md`. Dispatched as a **builder**, explicitly told not to retry
  `sup-boot` or take the claim.

## Honest status of the night's queue

Partially stalled, and it should be read that way rather than as a completed run. What can proceed
without a supervisor: the two builds above. What **cannot**: the final dual-lens gate on
handoff-seams and its merge, the `fleet q` M1+M2 build, and all cleanup — those are supervision
work and wait on a booted supervisor, hence the escalation above.

## New facts worth carrying (candidates for `knowledge/lessons.md`)

- **A guard's postcondition must be satisfiable by every legitimate caller class.** B6 says "wait
  for that body to exit" to a tier defined as never exiting. The doc defect is secondary; the code
  defect is that a universally-phrased postcondition met one caller class it could not bind.
- **Autoclean swept `state/journals/` and archived every day-3 worker record.** Archived records
  are history-only: `send` and `respawn` both refuse them, and only `fleet clean --tombstones`
  frees the name. Consequence for briefs: **every worker now boots contextless**, so orientation
  (branch, sha, baseline tallies, fences) must be written INTO the brief.
- **Absence is not evidence on this substrate** — records are deletable (`clean`), archivable
  (`autoclean`), and born with `session_id: None`. Any predicate that permits on a missing record
  fails open on all three paths.
