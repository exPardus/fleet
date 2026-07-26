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

---

# Successor body — `inc-20260726T164216Z-3b33` (booted 16:42Z)

Fresh claim, `VERDICT: claim`, predecessor `inc-20260726T140221Z-26ce` had released cleanly. No
seizure, no transfer, no §5.7 lever. Baseline re-measured by this body: `main` = `8dee4b8`,
**2152 passed / 11 skipped on py3.13 AND py3.10** — the predecessor's figure reproduces exactly.

## G-H. The §G-E leak, measured on the supervisor's own body — and the registry vindicated

The identity check in this body's boot brief was expected to be a formality. It was not: **the
leak reproduced on me, at boot, unprompted.**

```
my env CLAUDE_CODE_SESSION_ID : 108300de-8d43-411e-8177-94843bee05ab
my env FLEET_WORKER           : sup|inc-20260726T140146Z-5a0e|boot

records whose sid union contains MY env sid: ['sup|inc-20260726T164152Z-8180|boot']
my actual dispatched worker name          : sup|inc-20260726T164152Z-8180|boot
env FLEET_WORKER names a DIFFERENT record :  True (status: idle )
```

`fleet doctor`, same minute: `daemon.lock held by pid 28812 since 2026-07-26T14:01:49Z` — the
daemon was started by the **14:01** dispatch and has been donating that dispatch's identity to
every session it has hosted since. Causal chain closed, no inference required.

**This is the council's proposed experiment, run for free, and it returns the council's answer.**
At one instant, on one body: resolving identity **from the registry by the acting session's own
sid** returned **exactly one** record and it was the correct one; resolving it **from
`FLEET_WORKER`** returned a different, idle worker. Registry right and environment wrong,
simultaneously, in the same process. The 4–0 synthesis is no longer a design argument — it has a
receipt.

It bit nobody: the donated name is supervisor-shaped, so §6.5 exempted me. That is luck about
which dispatch happened to start the daemon, not a property of the design.

Sid-union detail worth keeping: the leaking record `sup|inc-20260726T140146Z-5a0e|boot` carries
**two** sids (`6d1a77bd` pre-fork, `76ae301e` post-fork). Any registry-keyed resolver must match
on `_record_sids`, never on the bare `session_id`, or fork-steered bodies stop resolving.

## G-I. The council's framing is wrong on one load-bearing point: this is spec-vs-spec

The council recorded that *"the project already decided this; the code diverged from its own
ratified rule."* Having read both documents verbatim, **that is not what happened, and the
difference changes the remedy.**

- `docs/SPEC.md:196` (ratified): a guard enforcing *"a worker turn must never hold the supervisor
  claim"* **"must key on the registry or the claim itself, never on `FLEET_WORKER`."**
- `docs/specs/claim-nonce.md` **§6.5 D5** (ratified, ~line 1772): *"The design **depends on** a
  `FLEET_WORKER` refusal in `_require_claim_holder`, which does not exist today … That is a
  **shipped-code defect**, filed separately and not built here."*

**Two ratified specs mandate opposite things.** The guard at `:10899` did not go rogue — it
faithfully implements claim-nonce §6.5, and in doing so violates SPEC.md:196. So the fix is not
merely "correct the code": **one of the two specs must be amended, and no author ratifies their
own spec.** The build is therefore instructed to build to SPEC.md:196 and to file the
claim-nonce §6.5 amendment as `DESCRIPTIVE — REQUIRES OPERATOR RATIFICATION`.

Collateral: `docs/SPEC.md:334` cites this prohibition as *"§6.1"*. §6.1 is *"D1 — the boot
verdict order"*; the env-channel section is **§6.5**. A mis-citation in the spec of record —
queued as doc-sync, deliberately not fixed inside the build branch.

## G-J. The invariant added to the council's design, and why it is not optional

The synthesis replaces an env-derived predicate (`FLEET_WORKER`) with a registry lookup **keyed
by an env-derived value** (`CLAUDE_CODE_SESSION_ID`). That improves blame-assignment but **does
not leave the medium**: both variables arrive through the same donated daemon environment. Under
C4's still-open hypothesis (ii) — the vendor passes the environment through — a registry-by-sid
judge inherits the identical defect one level down, and the whole synthesis rests on sand exactly
as C4 warned.

The pre-flight that would settle it needs the machine-wide daemon restarted from a shell that
*holds* a sid, which kills live sessions including the supervisor's. **It remains an
operator-shell experiment and this body did not attempt it.**

So rather than block on it, the build is required to be sound under **both** hypotheses, via one
added invariant:

> **An identity inference derived from the environment may never be the sole basis of a refusal.
> The nonce and the claim refuse; inference may only inform and announce.**

With that, a misidentification costs a wrong *measurement* or a spurious *announcement* — never
a wrongly-refused claim verb. Plus a **uniqueness** rule: exactly one matching record is an
identity; two or more live matches is itself a leak signature, reported distinctly and treated as
unresolved rather than silently taking the first match.

## G-K. `fleet spawn` silently destroys an operator-authored task file — found by hitting it

Dispatching the ruling council cost four workers a wasted start, and the mechanism is a real
defect.

`dispatch_bg` writes the worker's prompt to `state/tasks/<name>.md` with an **unconditional**
`task_path.write_text(prompt_body)` (`bin/fleet.py:9250`) — no existence check, no warning — and
then dispatches the body with the tiny prompt `Read <task_path> and follow it exactly.`
(`:9259`).

I had authored each councilor's brief at `state/tasks/rule-c1.md` … `rule-c4.md` — the natural
path, in fleet's own directory, under fleet's own naming scheme — and passed
`--task "Read state/tasks/rule-c1.md and follow it exactly."`. The dispatch **overwrote each
brief with its own preamble plus my task line**, so all four workers booted holding a file whose
only instruction was to read the file they were already reading. Content destroyed, silently,
before the body ever read it.

Why it is latent rather than obvious: the predecessor avoided it only by accident, because it
named its brief files after the *task* (`hs-fixwave2-dispatch.md`, `b6-interface-release.md`)
rather than after the *worker*. Anyone naming a brief after its worker — the obvious
convention — loses it.

Recovery taken: rewrote the four briefs under `state/tasks/lens/`, then `fleet send` to all four
with the corrected pointers and an explicit instruction to discard anything concluded from the
broken file. All four picked the correction up at their next tool boundary (mail drained to 0)
and none had produced anything from the stub. Subsequent briefs live under
`state/tasks/briefs/`.

Queued fixes, **not built here**: `dispatch_bg` should refuse (or at minimum warn loudly) when
`state/tasks/<name>.md` already exists and was not written by a prior dispatch of that same
worker; and the self-referential case — a task line that points at the task file itself — is
mechanically detectable at dispatch time and should be refused outright. Secondary hazard worth
recording: `state/tasks/` is also swept by cleanup paths, so an operator brief parked there is
exposed to deletion as well as to clobbering.

## G-L. `doctor` FAIL carried forward: the native contract is unverified at claude 2.1.220

`[FAIL] pin-version: claude 2.1.220 != 2.1.218 at last pin pass (2026-07-23)`. Standing doctrine
from M-D is explicit — **run the pin tier on every `claude` bump, not only at merges** — and the
8th live-tier catch in this project's history *was* a vendor change. Two patch versions have gone
by unverified, and the council separately noted `--setting-sources` is still marked UNOBSERVED at
2.1.207 while the live daemon is 2.1.220. Queued for this body: run the `FLEET_LIVE=1` pin tier
and re-stamp, or record what broke.

# Successor body — `inc-20260726T170625Z-55bb` (claim received 17:07:25Z via handoff)

Lineage `lin-20260726T164216Z-6908` preserved, so the five in-flight workers were
lineage-owned by me on arrival (claim-nonce §6.2). I took no fleet action between
`sup-boot` and claim transfer (spec §4 double-spawn guard).

## G-M. The one item my predecessor certified "safe to fix" is the wrong correction

G-I's collateral says `docs/SPEC.md:334` mis-cites the `FLEET_WORKER` prohibition as
§6.1 when the env-channel section is `claim-nonce` §6.5, and handed it to me as "my
finding, mine to hand you, safe to fix". I verified before editing. It does not hold.

`docs/SPEC.md`'s **own** §6.1 ("The second dispatch path — supervisor successor") spans
lines 173–201 — the next heading is §7 at :202 — and the prohibition itself is at
`SPEC.md:196`, **inside** it. G-I's own text cites :196 as the source of the
prohibition. So :334 is a correct *internal* cross-reference. The mis-diagnosis came
from reading a bare "§6.1" as `claim-nonce`'s §6.1 (boot verdict order) when the
containing document is SPEC.

Had I applied it, I would have repointed a correct reference at `claim-nonce` §6.5 D5 —
a different rule which, per G-I itself, *depends on* a `FLEET_WORKER` refusal and so
mandates the opposite of what :334 asserts. The edit would have inverted the sentence
while looking like a typo fix.

**Unaffected:** G-I's load-bearing claim stands — `SPEC.md:196` and `claim-nonce` §6.5 D5
are both ratified and mandate opposite things, so the guard at :10899 faithfully
implements one spec and thereby violates the other. Only the collateral sub-item is
withdrawn. **Lesson:** a handoff's "safe to fix, do not re-derive" carries no
verification; the single item certified safe was the only wrong one handed over, and it
cost two greps to falsify. A bare section number is ambiguous across a multi-document
spec set — a cross-doc citation must name its document.

---

# THE RULING — both escalated branches, synthesised from a 4-councilor council

Doctrine: the operator is AWAY and both dispositions are operator-gated, so the question
goes to four councilors of differing personalities plus synthesis, and I act on the
synthesis (standing since 2026-07-24). I did **not** rule solo and I did not stall for a
sleeping operator. Each councilor booted contextless, independently re-drove both
mandatory repros on both floors, and was required to name the most plausible opposite
ruling. Three of the four explicitly flagged convergence-with-the-predecessor as a risk
rather than a comfort; c3 put it best — *"a council that ratifies its predecessor's
conclusion while inheriting its predecessor's reasoning has produced nothing."*

Reports: `RULING-RISK-AUDITOR.md` (c1), `RULING-DELIVERY.md` (c2),
`RULING-ARCHITECT.md` (c3), `RULING-HISTORIAN.md` (c4), in the matching
`C:/proga/fleet-rule-c*` worktrees.

## R1 — Branch A `fix/handoff-seams`: DELETE the un-supersede, then merge. **4–0.**

| councilor | disposition |
|---|---|
| c1 risk-auditor | (a) delete the un-supersede |
| c2 delivery | (e) **revert** `cb9f078`'s hunk — same code change |
| c3 architect | (a) delete |
| c4 historian | (a) = (e-narrow) delete |

Unanimous on the code change; the only split was procedural framing, and **c2's framing
wins**: this is a revert of a self-contained hunk, not a third fix wave, so it is not a
bet against fix-waves-mint-defects 11/11. c2 measured it — on both floors the revert
removes exactly the two tests it deletes, produces **zero** other failures, and 3 of the
34 mutants stop applying.

Three councilors reached the same place by three independent routes, and each route
kills option (b) — "just restore the hash" — on its own:

- **c1: the rescue path has never once rescued anybody.** The token hash it needs is
  overwritten and only cleared when the pending list empties, so the resurrected
  successor is refused at `complete` under *every* input. (b) does not preserve a benefit
  that (a) discards; it preserves a path with a 0% success rate.
- **c3: part 3 of `begin`'s write is not compensable.** After the failed `begin`,
  `sha(tokA)` is absent from the entire claim JSON and the only surviving copy of the
  token is the **plaintext in the successor's task file**. So (b) as the brief words it
  "is recommending code that cannot be written" — any real (b) either re-reads a
  plaintext secret off disk or moves the hash onto the entry, a protocol-shape change on
  top of an unratified amendment.
- **c4: the counterfactual is strictly better.** Without the un-supersede the body is
  refused at its own `sup-boot` with `rc=5` and operator-actionable TERMINATE text,
  instead of writing a HANDSHAKE nobody can act on.

**The brief's own framing was defective and c1 caught it:** option (e) was posed as
"revert `cb9f078`, but is throwing away the deadlock fix and 12 mutants proportionate?"
That trade-off does not exist. `cb9f078`'s *only* functional change is the un-supersede;
`rb-CRIT-2`'s deadlock fix lives in earlier wave-2 commits and is untouched. A councilor
steered by the brief alone could have picked (b) to avoid a loss that would not occur.

**Scope — three edits, nothing else** (c1 A5, concurred by c3/c4):
1. `_drop_pending_marker`: revert the un-supersede loop and the `or restored` condition.
   **Keep** `cb9f078`'s task-file paragraph — it is the honesty surface and it is good.
2. `resolve_handoff_abort` + `_cmd_sup_handoff_retire_all`: make `--force` consult
   `_entry_age_seconds`, so the code matches the three surfaces documenting it. Rides in
   the same wave as a fail-closed narrowing. (MAJOR-2 is worse than its summary: it
   prints a predicate it never evaluated. Note c4 checked and the **journal row is
   honest** — the "and journals" half of that claim did not survive execution.)
3. `claim-nonce` §6.4 A1: re-read rather than edit; it stops being falsified once (1) lands.

**What the re-gate must assert, and it is a rule not a test** (c1, and this is the most
transferable thing the council produced):

> Assert on the **last verb of the sequence the change exists to enable** — not on the
> precondition the change manipulates. Take the benefit the change claims in its own
> docstring, name the verb sequence a user runs to collect it (`begin` → *fail* →
> `sup-boot` → **`complete`**), and assert on the final verb's outcome.

The existing test's name is the tell: *"leaves the previous attempt **bootable**"*.
Bootability is a precondition nobody wants for its own sake. Corollary: **a state-machine
change must drive every newly admitted body to a terminal state.**

**Parking A is the one disposition ruled clearly wrong** (c2, unrebutted): `main` today
has *no* pending-successor collection at all and *no* containment check on
`handoff_task_file_path` — the function composing the path to a file holding a live
plaintext handoff token. Parking discards that check along with its tests.

**Recorded against my own ruling** (c2's self-nomination, and it is correct on the
facts): merging A does **not** close the root — a single-valued `handoff_token_hash`
under a *set* of attempts. `rb`'s WAVE-1-CARRYOVER shows a sibling failure reachable
without `cb9f078` at all. It is wave-1 shape, outside this gate's delta, and A3-shaped —
operator-owned. I merge a bounded, documented, ratification-queued root rather than keep
two unbounded ones, and I am naming it so the operator can overrule me.

## R2 — Branch B `fix/b6-interface-release`: `--interface` dies (**4–0**); the detection half ships (**4–0 on substance**)

The nominal tally reads 3–1 for park. **That tally is misleading and I decline to rule on
it.** Read for substance rather than for the option letter, the council is unanimous
twice:

- **Drop `--interface` and its whole attestation surface: 4–0.** No councilor defends it.
- **Land corrected wedge-detection and honesty surfaces now: 4–0.** c1 carves them out
  and ships them alone; c2 keeps them as a subset merge; c4 lands them "separately
  against `main`"; and c3 — nominally park — says in its own dissent that if anyone wants
  value from this branch now, the honest form is a scoped fix wave *on the honesty
  surfaces*.

So the only live disagreement is the **vehicle**: cherry-pick branch B's detection
commits (c2), or rewrite equivalent code fresh against `main` (c1/c3/c4).

**I rule for c2's vehicle.** `_doctor_check_supervisor_wedge` is 66 lines with **26/26
mutants killed, zero survivors** — the break lens's own words, *"the strongest I have
measured on this project"* — plus FI-5 regression-pinned. Rewriting that fresh on `main`
discards verified work *and* takes a new bet against 11/11 to re-reach a place we have
already reached. The three's objection to c2's vehicle is that the branch's honesty
surfaces are still wrong as written; that objection is **already satisfied inside c2's
(d)**, which rewrites both remedy strings and fixes the statusline in the same motion. I
am not overruling the majority's requirement, I am accepting the minority's cheaper route
to it.

**Land:** `_doctor_check_supervisor_wedge` + its `cmd_doctor` registration,
`cmd_sup_status`'s released-state branches, commit `1927058` in full (delegation to the
shared predicate, FI-5/M18 pinned).
**Drop:** the `--interface` argparse flag, `cmd_sup_release`'s attestation write,
`supervisor_claim_decision`'s attestation skip, the `--json` projection, and
`_project_claim`'s `released_by_interface` allowlist. `supervisor_claim_decision` reverts
to `main`'s already-ratified unconditional B6.
**Rewrite,** because a `doctor` row whose named remedy always exits non-zero is worse than
no row — `doctor` is the 3 a.m. surface and its credibility is the asset being spent:
both surfaces must name the two exits that actually execute (stop the roster-live session
by sid; the `claim-nonce` §5.7 operator lever), never `sup-release --interface`. Also fix
`supervisor_status_line`'s released arm at `bin/fleet.py:12292`, which promises a fresh
claim that will not happen — **that false prediction is already on `main`**; the branch
neither introduced nor fixed it.

That single rewrite closes `gate-b6-rs` F1/F2/F2b and `gate-b6-rb` FINDING 1 **by
deletion rather than by writing docs**, because those MAJORs exist only because the text
advertises a flag that is now gone.

**Why `--interface` dies, on the merits and not merely on the vulnerability** — three
independent reasons, any one sufficient:
- **c3, and this is the sharpest:** `--interface` asks a body to self-report a fact the
  substrate **already publishes**. Every roster entry carries `kind`; the live roster is
  72 `background` and exactly 1 `interactive` — the operator's own session. `kind` is read
  **nowhere** in `bin/fleet.py`. The branch adds a forgeable trust surface to recover a
  fact fleet could have read for free.
- **c4:** the branch repairs a path doctrine now forbids while leaving the universal case
  — every supervisor retirement — exactly as wedged.
- **c1:** B6 is already not providing the protection everyone believes it provides, so
  branch B carves an escape hatch beside a guard that does not currently guard.

**Parked, not rejected:** the B3 redesign (`sup-release` tombstoning its own body /
respawn-shaped retirement). c1 flags honestly that its own B3 design keys on roster
`status` and would be the *third* guard keyed on a substrate property this project does
not control — B6 on roster-liveness, §6.5 on env propagation, both of which bit. It also
depends on the confounded-sid pre-flight, which remains an operator-shell experiment.

## R3 — THE ORDERING CONSTRAINT. This is mine; no councilor could see it, and it inverts the obvious build order

The two best findings in the stack **interact adversarially**, and each councilor could
only see their own. c1's headline and c4's C1.1 are individually correct and, shipped in
the intuitive order, make the fleet *less* safe. I verified every fact below myself
against `main` @ `8252806`, not against the reports.

**c1's finding (verified):** B6 at `bin/fleet.py:10173` compares a bare
`released_by_sid` against the roster, while `_record_sids` — whose own docstring says
*"matching against `session_id` alone fails open"* — is used at **seven** other sites
(:2020, :2064, :2116, :5503, :5790, :6057, :7117). B6 is not one of them. That is exactly
why B6 evaporated for the fork-steered holder in G-G: it tested the post-fork sid, the
roster held the pre-fork one, and it **failed open**.

**c4's finding (verified):** `_supervisor_gate` — the claim-nonce §7 speed-bump — returns
early at `bin/fleet.py:10540` on *any* `released` claim, disarming it **for every caller
and every mutating lifecycle verb**. c4 measured it: with a held claim, `kill`/`clean`/
`interrupt` from a third body are all gated; with the wedged record, all three are
ungated and `fleet clean --yes` — the irreversible one — **simply ran**. The same
early-out at :2005 and :2059 also strips the supervisor body's band/ceiling recognition
and its archive protection. **This is live on `main` right now, independent of either
branch** — the only finding in this stack already true in production.

**The interaction, which is the actual ruling:** c1's fix converts B6 from fail-open to
fail-closed. It therefore **creates wedges where today a successor boots through**. And
every wedge is, per c4, an indefinite fleet-wide *ungated* window — closable only by the
successful boot that B6 is now correctly refusing. **Shipping c1's one-liner alone
strictly increases exposure to the worst thing on this list.** c4 saw the shape of it —
*"B6 does not freeze the fleet safely; it maximises the duration of the least-protected
state it exists to shorten"* — but not that the council's other headline recommendation
would multiply the frequency.

**Therefore, binding build order:**
1. **c4's containment first, or in the same commit — never after.** Arm the §7 gate on a
   `released` record whose `released_by_sid` is still roster-live: exactly the state B6
   already computes. ~10 lines, fail-closed, no protocol change.
2. **Then c1's `_record_sids` union re-key of B6.** One line, no protocol change,
   independent of both branches, and a strict prerequisite for any future B3.

Never (2) alone. If only one lands this session, it must be (1).

## R4 — Record correction, 4–0: the forgery is **MAJOR**, not CRITICAL

`gate-b6-rb` graded it MAJOR and said so explicitly — c2 counts three times, including
*"That is why it is MAJOR and not CRITICAL."* Three downstream artifacts — the 16:29
checkpoint, §G-F, and **this council's own common brief §4** — render it "(CRITICAL)",
unmarked and unattributed. c1, c2 and c4 each caught this independently; c3 warned that
"ruling on an inflated severity is how a council launders a label into a decision."

The inflation was load-bearing: the brief framed the b6 disposition around it, so a
councilor working from the brief alone would have ruled against a CRITICAL its finder
declined to assign. c2 further established that a current `sup-boot` **cannot mint a
legacy claim** and the live claim here **is not legacy** — so the state the forgery needs
is not currently reachable on this machine.

**Standing process amendment, and it is cheap:** a verdict line carried across an
escalation must reproduce the reviewer's own severity token **verbatim**; any re-labelling
by the escalating body must be marked as theirs and given a reason. It protects the one
channel a councilor cannot audit without re-reading 145 KB. c1 files the same defect class
one level down: `gate-hs-rs` MAJOR-2 claims the false `--force` reason is *"printed and
journals"* — c4 drove it and the **journal row is honest**.

Note the shape: **G-M, R4, and the brief's false option-(e) trade-off are all the same
defect** — a claim that gained authority in transit and was never re-driven at the point
of decision.

## R5 — G-K confirmed independently, and it hit a councilor live

c1 and c2 both filed it; c2 filed it from *inside* the failure — it booted holding a task
file whose only instruction was to read the file it was already reading. Confirms G-K is
silent (the spawn succeeds; only a *suspicious* worker notices) and that its blast radius
is any dispatch writing a brief to `state/tasks/<worker>.md`. Queued fix stands: refuse or
warn on a pre-existing task file not written by a prior dispatch of that same worker, and
refuse the mechanically-detectable self-referential case.

## The pattern under R1, R4 and G-M — worth more than any single finding

This project reliably **writes down the right rule and then ships a guard that does not
follow it**, because nothing checks that ratified identity rules are actually keyed on.
`SPEC.md:196` said *never* key on `FLEET_WORKER`; the guard at :10899 does.
`_record_sids`' docstring says matching a bare sid fails open; B6 does exactly that. Two
instances, same shape, found by two councils. c1's proposed remedy generalises both: **a
lint or doctor check enumerating every predicate that compares a bare sid against a roster
or registry.** Filed as the highest-value process item from this council.

Nothing in this ruling ticks a box in `OPERATOR-GATES.md`. Ratifying amendment A3 (whose
`--force` clause describes the code *more narrowly than what ships*, so it must not be
ratified before R1 scope item 2 lands), `claim-nonce` §16 and `three-tier-command` §15
remain operator-only, as does the confounded-sid pre-flight.
