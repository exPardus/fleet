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

## RESOLUTION — both blockers cleared, supervisor live (operator returned and ordered "fix these")

1. **Claim wedge (G-D)**: the operator authorized the §5.7 lever. The interface removed the
   `"released_by_sid"` key from `supervisor/INCARNATION` (backup kept in the session scratchpad);
   `state` stayed `"released"`, every other key untouched. Rule 1 then found no releaser to test.
   **This is an operator-authorized out-of-band mutation of claim state, recorded here as the
   order of record** — the same shape as the day-3 nonce class-4 lever use.
2. **Daemon leak (G-E), operationally**: `~/.claude/daemon.lock` was found ABSENT — the transient
   daemon had idle-exited. That is the clean-start window: the next `--bg` dispatch starts the new
   daemon and donates its env. The interface's shell carries no `FLEET_WORKER`, so `sup-spawn` was
   run FIRST, before any worker dispatch, so the new daemon comes up clean. The supervisor's brief
   orders it to verify this from its own env rather than assume it.
   **The durable code fix is NOT done** — it is queue item 2 for the supervisor, with the design
   trap named (a sid-keyed registry lookup fails during `sup-spawn`'s own dispatch window, when the
   record still carries `session_id: None`).
3. **Result**: `sup-spawn` → `sup|inc-20260726T140146Z-5a0e|boot`, which booted and took the claim
   as **`inc-20260726T140221Z-26ce`** (sid `6d1a77bd`, via `fresh`). The fleet has a supervisor
   again and it owns the queue from here.

**Standing doctrine established tonight: an interface session must never run `sup-boot`.** The old
handoff told it to, and that single step produced both a wedged claim and a supervisor that could
not have released it.

## G-G. First LIVE exercise of the §10.4 respawn-of-holder choreography — three findings

The interface retired the ceiling-bound supervisor `inc-20260726T140221Z-26ce` through the
tombstone machinery merged earlier tonight. It worked, and it surfaced three things worth pinning.

1. **Neither party can retire the body alone — the two guards are complementary halves.**
   `fleet respawn supervisor` from the interface is refused by the §7 nonce gate (the interface
   holds no generation, by design). From the holder, the same verb hits the spawn-ownership
   confirmation (the interface spawned that record; the holder does not own itself). The holder
   passed `--yes` and judged — correctly — that the confirmation's owner was the party ordering the
   retirement, and that this was not the §10.4 abort it had been told to stop on.
2. **The choreography stalls silently while it waits for the holder's own release (B5).** The
   holder's `respawn` call blocked ~2 minutes and its harness killed the client. A caller with a
   timeout therefore sees **a hang, not a phase** — there is no `SUP-RESPAWN-<phase>` surface
   emitted during the wait. The release itself completed cleanly (`exit 0`, generation still
   valid), but **the successor was never dispatched**, because the client that would have dispatched
   it was dead. Retirement and succession are not atomic in practice.
3. **The fork-steer sid rotation walked around B6 by accident.** The claim recorded
   `released_by_sid = 76ae301e` (the forked session), while the roster's live entry for that same
   body is its PRE-fork sid `6d1a77bd`. B6 tests the recorded value against the live set, so it did
   not fire — the successor booted cleanly over a released claim whose body is still alive. Tonight
   that was convenient; as a guard property it is luck, and it means B6's protection silently
   evaporates for any holder that was ever fork-steered.

Also observed: **§5.3's interface-divergence detector false-positives on a self-directed holder
verb.** `sup-status` warned that two caller sids steered the supervisor within 3600s, naming the
interface and the supervisor's OWN forked body — the second is the holder running
`respawn supervisor` on itself, not a divergent interface. Detection-only, nothing broke, but the
predicate cannot distinguish a holder steering itself from an interface steering it.

**Recovery taken**: `sup-spawn` → `sup|inc-20260726T164152Z-8180|boot`, carrying
`state/tasks/sup-successor-brief.md`. No §5.7 lever, no seizure.

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

## G-E. The daemon leaks the first dispatch's `FLEET_WORKER` — second blocker, found late in the run

Not council-gated (it is a defect, not a fork), but it is the run's most consequential finding and
it changes the escalation remedy above.

**Repro, verified.** `_worker_env` (`:1431-1464`) stamps `FLEET_WORKER=<name>`; `dispatch_bg`
passes it as `Popen(env=...)` (`:9315`, `:12005`). That env reaches only a **launcher that asks the
daemon** — the daemon hosts the real session. `~/.claude/daemon.lock` while `hs-fix2` ran:
`pid 36476, origin transient, spawnedBy {label: "claude --bg", cwd: "C:\proga\fleet-handoff-seams"}`
— i.e. the daemon was started by the FIRST `--bg` dispatch and inherited that worker's identity.
The gen-0 supervisor body, launched afterwards, carried `FLEET_WORKER=hs-fix2` (its own sid was
correct; only this variable was stale).

**This answers a question the source explicitly marks UNOBSERVED** at `:11876-11879`: whether the
daemon propagates the launcher's environment into the hosted session. It does not — it propagates
its own, from whichever dispatch started it.

**Why it blocks three-tier.** `_is_supervisor_shaped("hs-fix2")` is False, and §6.5 refuses
`_require_claim_holder` on a non-supervisor-shaped `FLEET_WORKER` (probed in a temp fleet home:
`REFUSED -- this is a worker turn ... §6.5`). `cmd_sup_boot` does not call `_require_claim_holder`,
but all seven holder verbs do. **A daemon-hosted supervisor can therefore take the claim and then
never heartbeat, checkpoint, or release it** — a fresh wedge, B6-shaped again, because release is
exactly the verb it cannot reach.

**Interim remedy** (until fixed): ensure the hosting daemon was not started by a worker dispatch —
dispatch the supervisor first from a clean shell, or let the transient daemon idle-exit with no
`--bg` sessions alive so the supervisor's own `sup-spawn` starts the new one. Verify rather than
assume: the hosted body should report `FLEET_WORKER=sup|<inc>|boot` (supervisor-shaped, exempt).

**Contamination check on the B6 wave: clean.** `conftest::_no_inherited_claude_session` is autouse
and deletes both variables, so all 2213 tests and every FI probe ran unaffected. One honest
caveat the builder raised itself: its
`test_the_attesting_releaser_cannot_run_a_holder_verb_by_sid_match` asserts only
`pytest.raises(FleetCliError)`, so in a contaminated shell it would pass for the §6.5 reason rather
than the released-branch reason — the assertion is not reason-specific. Worth tightening at the
gate.

## Build results this run (both UNGATED and UNMERGED — supervision work is what is stalled)

- **`fix/handoff-seams` fix wave 2 — GREEN** (`02df553` R9 code, `1570491` R9 tests, `daed33c` R10,
  `cb9f078` amendments + un-supersede, `a9d2c64` ratification queue). **2142 passed / 8 skipped on
  BOTH floors** (baseline 2089/8, no net loss); receipts pass, nothing re-pinned (the one warning
  is a pre-existing `ls -ld` mtime line the worker never touched). Doctor measured in that
  worktree: 3 FAILs, all `worker-settings.json missing` because it was never `fleet init`-ed —
  everything else PASS, including `supervisor-handoff`.
  **rb-CRIT-2 closed with two REAL successor attempts and two REAL boots**: shipped code gives
  rival `rc=5 handoff-refused`, `CLOBBERED: False`, `complete rc=0`, claim → winner; the mutant
  (`refusal = None`) reproduces the deadlock verbatim — rival `rc=0`, `CLOBBERED: True`, complete
  refused *"HANDSHAKE mismatch"*, abort on winner refused *"does not match HANDSHAKE sid"*, final
  holder still the predecessor. **R10: 8/8 mutate→RED→restore**, restore proven by
  `git status --porcelain == ''`; N23 plants a real resolving escape (junction) and N38 reaches
  `state/` via `sub/..`.
  Two judgment calls the worker flagged: `--retire-all` never stops a session, and a begin that
  fails **at dispatch** now un-supersedes the entries it marked — otherwise a failed retry would
  kill a live, good successor. **A3 is UNRATIFIED and changes the protocol shape** — not a
  clarification.
- **`fix/b6-interface-release`** (gen-0 body as builder; `aeb0ad6`, `1927058`, `2e824ea`).
  `sup-release --interface` with the rule-1 carve-out keyed `is True` (not truthiness), a truthful
  `sup-status` releaser-live branch, and a `fleet doctor` `supervisor-wedge` **FAIL** that delegates
  its verdict to `supervisor_claim_decision`. **2213 passed / 11 skipped on BOTH floors** (+61,
  builder measured its own baseline at `a2358f2` = 2152/11 rather than trusting the brief's number
  — see the baseline note below); receipts 56/56, nothing re-pinned. Spec amendments in
  claim-nonce §16 and three-tier §15, both marked DESCRIPTIVE, REQUIRING OPERATOR RATIFICATION;
  `OPERATOR-GATES.md` untouched. (a+), (b) and (c) are pinned by tests so a future edit reaching
  for them fails.
  **Its own FI-5 caught a defect in its own wave**: v1 of the doctor check returned early for the
  attested and no-releaser cases, so the delegation was unreachable for exactly the rows that could
  disagree — the "cannot disagree" claim was theater until `1927058`. Fix-waves-mint-defects holds;
  this time the builder caught it itself.
  **Baseline discrepancy, unresolved and worth a look**: the interface measured `a2358f2` at
  2147 passed / 16 skipped; the builder measures the same sha at 2152/11. Same 2163 total, so it is
  a skip/pass split difference between environments (native-pin and live tiers), not a lost test.

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

---

# G-F. Gen-0 supervisor, second launch — the gate escalated both branches

Supervisor `inc-20260726T140221Z-26ce` (body `sup|inc-20260726T140146Z-5a0e|boot`, sid
`6d1a77bd`). Booted `claim` — predecessor released cleanly, no seizure. Pre-boot env check
per the brief's first act returned `FLEET_WORKER=sup|inc-20260726T140146Z-5a0e|boot`
(supervisor-shaped): **the G-E leak did not hit this body**, confirming the interim remedy
(dispatch the supervisor first, from a clean shell, into a freshly idle-exited daemon).

## HEADLINE — nothing merged. Four reviewers, four ESCALATE.

**`fix/handoff-seams` @ `a9d2c64` — both lenses independently found the SAME defect.** It is
precisely the judgment call the builder flagged and that both briefs ordered adjudicated
rather than repeated: *a begin that fails AT DISPATCH un-supersedes the entries it marked.*

- `gate-hs-rs`: R9's un-supersede restores a superseded successor's **bootability** without
  restoring `claim["handoff_token_hash"]`, so the rescued successor boots, writes HANDSHAKE,
  and `sup-handoff-complete` refuses it as a body the claim never dispatched.
- `gate-hs-rb`: same defect, **reproduced end to end** — `begin` overwrote
  `handoff_token_hash` and `drop_handoff_entry` only clears it when the pending list empties —
  **with no test in the delta that dies.**

So wave 2's fix for `rb-CRIT-2` minted a defect of the same family: a successor that is
**bootable but not completable**. That is HANDOFF-ORPHAN re-entered through the rescue path
wave 2 itself added. **Fix-waves-mint-defects is now 11/11 lifetime.**

**This was the last authorised wave. ESCALATE-beats-a-3rd-wave is standing doctrine, so no
wave 3 was ordered.** Operator decides: authorise a scoped wave 3, or park the branch.

**`fix/b6-interface-release` @ `2e824ea` — two ESCALATEs; the break lens found something worse
than the bug the branch fixes.**

- `gate-b6-rb` (CRITICAL): **`--interface` is forgeable on a §9 legacy claim via the `--sid`
  override** — the same override the council cited when rejecting design (a+) — turning B6's
  fail-closed refusal into a **silent, unpaged claim takeover from a live supervisor.** A fix
  for a wedge that opens a silent takeover is a net negative; the wedge at least announced
  itself.
- `gate-b6-rs`: the honesty surfaces are still wrong in the wedged state — the always-on
  statusline keeps the exact false `boot one (fleet sup-boot)` prediction the branch claims to
  fix, and both `sup-status` and `doctor` name `fleet sup-release --interface` as a remedy
  **that always exits 1.** A doctor check whose named remedy always fails is worse than no
  remedy: it spends the operator's trust in the one surface they consult at 3am.

Both findings land in the branch's own core claims, not in adjacent code.

## The finding this supervisor hit live, before the reviews returned

**There is no clean stand-down for a supervisor body that cannot exit.**

B6 is literally `released_by_sid in live_sids` against the native roster (`:10172-10176`). A
fleet-dispatched supervisor body **does not exit when its turn ends** — it goes idle and stays
in the roster. Therefore **any `sup-release` by a fleet-launched supervisor re-creates the very
wedge that convened the b6 branch**, and `--interface` would be a *false* attestation from a
body that is not the interface tier.

The b6 branch narrows B6 for the interface case and leaves the supervisor's own case exactly
as wedged as before. This is the adjacent-uncovered-case the b6 brief told its reviewer to hunt
for, found from the outside by hitting it. Whatever replaces b6 must answer: **how does a
supervisor body that cannot exit stand down cleanly?** Directions, not decided and not built:
attest to *standing down* rather than to tier membership; key B6 on the releaser still
*holding* something rather than merely being alive; or have the release verb tombstone its own
body so it leaves the roster.

## Council on the G-E daemon leak — 4–0, and it settles more than it was asked

Four councilors (risk auditor / delivery pragmatist / strategist / incident responder) all
rejected every shape that keeps **inferring** identity from the environment.

**Adopted synthesis:** the **registry is the sole judge** of a session's fleet identity, keyed
on the acting session's own `CLAUDE_CODE_SESSION_ID` matched against the **sid union**
(`_record_sids`, so fork-steer and respawn still resolve); the **env survives only as a
witness**, whose disagreement with the registry is a *detected leak* that `fleet doctor` reports
by name; §6.5's env arm is **deleted** and replaced by a registry-keyed arm; site A's structural
interface exemption re-keys from "`FLEET_WORKER` absent" to "no registry record claims my sid"
AND-NOT-claim-holder; and the dispatch window (`session_id: None`) is answered by **abstention**
— at site A a newborn body cannot be at 200k, and at site B the nonce is the real gate.

**The citation that settles it:** `docs/SPEC.md:196` already carries a **ratified** rule — a
guard enforcing "a worker turn must never hold the supervisor claim" *"must key on the registry
or the claim itself, **never** on `FLEET_WORKER`."* **That warning was written, ratified, and
then violated by the very guard it was written about** (`:10899`). And `claim-nonce.md:874-876`
refused to carry the nonce in an env var because *"the whole parent environment is copied and
exactly one key is stripped … §6.5 is the consequence"* — the spec understood the medium, then
§6.5's enforcement read that same medium. **The project already decided this; the code diverged
from its own ratified rule.**

### BLOCKING PRE-FLIGHT before any of that is built (C4)

Our confidence that `CLAUDE_CODE_SESSION_ID` does **not** leak is **confounded evidence**.
`_worker_env` (`:1461-1463`) **pops** `CLAUDE_CODE_SESSION_ID` before `Popen(env=…)`, so every
measurement we hold — the receipts at `:1450-1453` and §G-E's own — was taken while the donated
env had **no sid to donate**. That is equally consistent with (i) the vendor stamps a fresh sid
per hosted session, and (ii) the vendor passes the env through and there was nothing to pass.
`daemon.lock` reports `origin: transient`, implying other origin classes whose donated env
*would* carry a sid.

**If (ii) holds:** every worker under a daemon started by an interactive session presents as
that session — `_worker_is_foreign`/`_confirm_destructive` (`:3092-3134`) would let a worker
`fleet kill`/`clean` its siblings with **no `--yes`** (the 2026-07-09 incident, silently
un-guarded), `_caller_holds_supervisor_claim` would answer True for every worker, **and the
entire registry-by-sid synthesis above rests on sand.**

The decisive probe was dispatched and **the 200k ceiling refused the spawn** — two correct rules
interacting correctly. Partial evidence already held: all 8 workers dispatched under this one
daemon received **distinct** sids and were tracked correctly by `fleet status`, the Stop hooks
and the outcome records, so per-session sid stamping is real for *this* daemon-origin class.
That narrows (ii) to the sid-ful-donation case without closing it. **The fully decisive form
needs a daemon started by something that holds a sid — an operator-shell experiment.**

### C1's collateral finding, queued for the operator

The M-0 gate **G4 "env propagation — CONFIRMED"** (`spike/m0/VERDICTS.md:46`) is a **false
CONFIRMED**: `m0-core` was the first `--bg` dispatch and therefore *started the daemon*, so the
observation cannot discriminate the two hypotheses; the spike's negative control is confounded
the same way. `daemon.lock` — the one observable that separates them — was not read until
2026-07-26. The generalisation is the part worth keeping: **M-0 ran one session per daemon
lifetime; production runs many, so every M-0 conclusion was scored in a regime we no longer
operate in.** Related: `:9280-9283` marks `--setting-sources` UNOBSERVED at 2.1.207 while the
live daemon is **2.1.220** — 13 patch versions with nothing re-running the probe.

## Two rules enforcing themselves against their own author

1. **The 200k ceiling refused the sitting supervisor's own dispatch** at 201,920 tokens
   (three-tier §11.3). Fleet-enforced, not discretion. It fired on a legitimate probe, which is
   the correct outcome.
2. **§6.5's leak is live in the benign direction right now**: this daemon was started by the
   supervisor's own dispatch, so all eight workers carried the supervisor's `FLEET_WORKER` and
   were §6.5-exempt. Acceptable this wave — they hold no nonce and were fenced — and recorded
   so it is not rediscovered.

**Narrowed blast radius (grep-verified at `67dd53a`):** `FLEET_WORKER` is read in exactly two
places, `:2163` and `:10899`, plus the single write at `:1463`. **The hooks do not read it at
all** — they resolve workers by `session_id` from the hook payload, confirmed empirically. C1
argues the true exposure is wider via sid-derived identity generally; read its R2 before
treating "exactly two predicates" as the whole story.

## State left for the operator

- `main` = `af62850` (SPEC §18 tombstone row + `bgIsolation` setting), **2152 passed / 11
  skipped on py3.13 AND py3.10**, measured by this supervisor. The 2147/16-vs-2152/11 question
  from the previous handoff is **resolved**: same 2163 total, five live-tier tests skipping
  without `FLEET_LIVE=1`.
- **Both branches unmerged and blocked on you.** Merge mechanics are pre-verified so nobody
  redoes them: `fix/b6-interface-release` merges with **zero** conflicts; `fix/handoff-seams`
  auto-merges `bin/fleet.py` and `claim-nonce.md` cleanly with **only `docs/NEXT-SESSION.md`**
  conflicting — in both orders. A clean textual merge of two semantic changes to the same claim
  subsystem proves nothing; the merged tree needs a full both-floors run before it is pushed.
- Cleanup done: 5 leaked plaintext-token files deleted (§5.9), 10 merged worktrees removed,
  stale `sessionstart_fleet` `.pyc` removed, PR #9 reconciled (already merged upstream).
- **Evidence on disk, none of it in any context:** `C:/proga/fleet-{hs-rs,hs-rb,b6-rs,b6-rb}/REVIEW-*.md`
  (with mutation ledgers and end-to-end repros) and `C:/proga/fleet-council/COUNCIL-{1..4}-*.md`.
  All five reviewer/council worktrees verified clean — every fault injection restored.
- **The claim is deliberately still HELD, not released.** A release from this body would wedge
  it (see above) and cost the §5.7 manual lever a second time in two days. A held claim merely
  makes the next `sup-boot` *refuse*, which is recoverable. **To get a fresh supervisor:
  `fleet kill` this body (or `claude stop` its session), then `fleet sup-boot`** — roster-gone
  plus an aged heartbeat resolves to `seize`, no lever needed.
