# Next session — day-4 handoff (written 2026-07-26 by the interface session)

## READ THIS FIRST — do NOT run `fleet sup-boot`

**If you are the operator's own interactive session, you are the INTERFACE tier and you must never
run `sup-boot`.** You bootstrap a supervisor with `sup-spawn` and steer it with
`fleet send supervisor`. The previous handoff told the incoming session to `sup-boot`, that session
did, and the result was a wedged claim (full record: `docs/AUTONOMOUS-2026-07-26.md` §G-D).

**Live wedge status.** The claim `inc-20260725T220334Z-5675` is `released`, but B6
(`bin/fleet.py:10172-10176`) refuses to let any body consume a released claim whose
`released_by_sid` is still roster-live — and that releaser is the interface session, alive by
design. So no supervisor can boot while that session lives.

- **If the wedging session (`adfda529-ee84-457e-a181-682dedefef1b`) has ended**, the wedge is gone.
  Just launch a supervisor and hand it the queue:
  `py -3.13 bin/fleet.py sup-spawn --task @state/tasks/sup-campaign-day4.md`
- **If it is still alive** and you want a supervisor now, the only other exit is the operator's
  §5.7 lever: delete the `"released_by_sid"` line from `supervisor/INCARNATION`. Operator's call
  alone — no agent takes it.

## SECOND BLOCKER — the daemon leaks the first dispatch's `FLEET_WORKER` into every later session

Found and verified this run. **Unwedging the claim is not sufficient on its own; read this before
you `sup-spawn`.**

<!-- MERGE NOTE (hs merge, 2026-07-27): the `fix/handoff-seams` side of this conflict was the
day-3 numbered operator queue. Items 1-5 are spent (G-1..G-4 ratified, cc-oracle pushed, both
GOALS proposals applied, fleet-index build ordered, providers.md parked as an open gate); item 6's
A1/A2/A3 detail moved to "Operator ratification stack" below, where main already carried the R9
stub. Nothing from that side was dropped unrecorded. -->

<!-- SUPERSEDED-QUEUE (day 3, kept for the audit trail):
1. **Ratify/reverse the council verdicts** in `docs/OVERNIGHT-2026-07-23.md` G-1..G-4 (boxes in OPERATOR-GATES untouched — only you tick). Headline: the freeze-verdict live catch (G-1) — council majority was wrong, dissent was right; worth a lessons-grade read.
2. **Push cc-oracle**: `cd C:\proga\claude-oracle && git checkout main && git merge mf/integration && git push` (+ version bump if releasing).
3. **Apply or reject three GOALS.md proposals**: `docs/proposals/GOALS-threetier-sync-proposal.md`, `docs/proposals/GOALS-tier-chain-proposal.md` (incl. its "Operator follow-ups": the §7.2 holder-alone one-line spec amendment).
4. **fleet-index M1 go/no-go** with the fresh evidence (it undercuts; the queued decision wanted exactly this data).
5. `docs/specs/providers.md` re-base-or-park: still parked by you, still not surfaced as a blocker.
6. **Ratify or reject three DESCRIPTIVE spec amendments** on branch `fix/handoff-seams` (unmerged): `docs/specs/claim-nonce.md` **A1** (§6.4 — `sup-handoff-abort` now has three arms, and the abort-flag arm is deleted as unreachable) and **A2** (§5.9/§8 — a fail-closed age-gated sweep of `supervisor-handoff-*.md` at four sites, where §5.9 said "written once and never deleted" and §8 said `cmd_sup_boot` is the only authorized sweep site). Both describe **shipped** behaviour a live incident forced; neither is self-promoted. The code is merge-ready independently — the amendments are the paperwork, and the branch is where they live until you rule.

   Context for the ruling: the 2026-07-24 succession (inc-651f → inc-7d7d, three attempts in sixteen minutes) hit a handoff that was **unabortable in exactly the window the abort verb exists for**, and the wave-1 fix for it reproduced the same failure one attempt later because it modelled the successors as a slot instead of a collection. Both amendments are consequences of that.

   **A3** (§6.4/§5.9, 2026-07-26, fix wave 2) is the one that needs a real ruling rather than paperwork: **it changes the protocol shape**, and says so in its first line. A1's collection plus A2's fail-closed sweep together left a *superseded* successor fully bootable on top of a single-valued HANDSHAKE, so a late rival clobbered the winner's handshake and the claim transferred to **nobody** — complete refused, abort on the winner refused, and aborting the rival deleted the handshake the winner would never rewrite. A3 adds an explicit `superseded` state and a **boot refusal**: at most one successor may boot, a superseded attempt stays abortable and auditable but not bootable, and there is deliberately **no promote verb** (abort, then begin again). It also adds `sup-handoff-abort --retire-all` / `--force` and makes `fleet doctor` FAIL on a stranded or superseded entry. Reproduced live both ways (with the refusal: claim transfers; without it: `CLOBBERED: True`, both verbs refuse, claim stays with the predecessor).
-->



`_worker_env` (`bin/fleet.py:1431-1464`) stamps `FLEET_WORKER=<name>` and `dispatch_bg` passes it
as `Popen(env=...)` (`:9315`, `:12005`) — but that only sets the env of a **launcher that asks the
daemon**. The daemon hosts the actual session. Evidence from `~/.claude/daemon.lock` while
`hs-fix2` was running:

```
"pid": 36476, "origin": "transient",
"spawnedBy": {"label": "claude --bg", "cwd": "C:\\proga\\fleet-handoff-seams", "pid": 34700}
```

That cwd is `hs-fix2`'s worktree: the daemon was started by the FIRST `--bg` dispatch, inherited
that worker's `FLEET_WORKER`, and every later session inherits it. The gen-0 supervisor body
launched afterwards carried `FLEET_WORKER=hs-fix2` — its own sid was correct, only this variable
was stale. This answers the question the source itself marks **UNOBSERVED** at `:11876-11879`
("whether the daemon actually propagates the launcher's environment into the hosted session").

**Why it is a blocker, not a nuisance:** `_is_supervisor_shaped("hs-fix2")` is False, and §6.5
refuses `_require_claim_holder` for a non-supervisor-shaped `FLEET_WORKER` (probed in a temp fleet
home: `REFUSED -- this is a worker turn ... claim-nonce §6.5`). `cmd_sup_boot` does NOT call
`_require_claim_holder`, but all seven holder verbs do (`sup-checkpoint`, `sup-heartbeat`,
`sup-release`, `sup-decision`, `sup-handoff-begin/complete/abort`). So such a supervisor **takes
the claim and can then never beat, checkpoint, or release it** — a fresh wedge, and B6-shaped
again because it cannot release.

**Operational remedy until this is fixed:** make sure the hosting daemon was not started by a
worker dispatch — dispatch the **supervisor first** from a clean shell (an interface session's env
has no `FLEET_WORKER`), or let the transient daemon idle-exit with no `--bg` sessions alive and
have the supervisor's `sup-spawn` be the dispatch that starts the new one. Verify before trusting
it: the hosted body should report `FLEET_WORKER=sup|<inc>|boot`, which IS supervisor-shaped and
therefore exempt.

**Not yet fixed in code, and not yet gated** — it is a finding, with a repro, filed for the
supervisor's queue. The real fix is that the hosted session's identity must not depend on which
dispatch happened to start the daemon.

## Where things stand

`main` = `a2358f2`, pushed. **`build/sup-tombstone` is MERGED** (§10.4 kill/respawn tombstone) —
both floors on main measured **2147 passed / 16 skipped on py3.13 AND py3.10**, receipts 56/56.
GitHub PR #9 carried that branch and needs closing/reconciling.

Two builds were in flight when this was written, both on their own branches, **neither gated,
neither merged**:

1. `fix/handoff-seams` — **fix wave 2 is GREEN and complete** (`02df553`, `1570491`, `daed33c`,
   `cb9f078`, `a9d2c64`; tip `a9d2c64`). **2142 passed / 8 skipped on both floors**, receipts pass,
   rb-CRIT-2 closed with two real successor boots, R10 8/8 mutate→RED→restore. **Last wave before
   the final gate; a 3rd needs escalation.** Amendment **A3 is UNRATIFIED and changes the protocol
   shape.** Next step is the gate, not more building: advance the review
   worktrees `C:/proga/fleet-hs-rs` and `C:/proga/fleet-hs-rb` to the new sha, run a delta-only
   dual-lens gate (verdict contract CONFIRM-CLEAN | ESCALATE), then merge no-ff, both floors, push.
2. `fix/b6-interface-release` — the gen-0 supervisor body acting as a **builder** (it holds no
   claim), brief `state/tasks/b6-interface-release.md`. Ships `sup-release --interface` (council
   4–0), a truthful `sup-status` releaser-live branch, and a `fleet doctor` FAIL for this wedge.
   Same gate-then-merge treatment.

## Queue after those two land

1. **fleet-q M1+M2 build** — `docs/specs/fleet-index.md` is gated-sound on main (`ready-for-gate`);
   operator ORDERED the full build. Honor the §11.7 `[UNVERIFIED]` live-receipt acceptance item and
   the §16 doc-sync list. Worktree recipe includes a manager-side `fleet index init` step.
2. **Doc-sync owed**: SPEC §18 rows for the tombstone merge (landed) and for handoff-seams when it
   merges; claim-nonce §5.9 marker/sweep prose; `skills/fleet/supervisor.md` abort recipe gains
   `--nonce`. **OPERATOR-owned, queue but never edit**: claim-nonce §7 taxonomy row for `sup-spawn`
   and the §7.1 amendment.
3. **Cleanup**: 5 leaked plaintext-token files `state/supervisor-handoff-inc-*.md` (§5.9); the 5
   stillborn `sup|…|successor` husk records; worktrees for merged branches (`fleet-sup-tomb`,
   `fleet-tomb-rs`, `fleet-tomb-rb`, and the older merged ones in `git worktree list`); archived
   tombstone worker records.
4. **Then**: sweep `docs/specs/**` for remaining `[UNBUILT]` and keep building (v2-deferred rows
   stay deferred).

## Operator ratification stack (only the operator ticks)

**New this run** — the G-D synthesis: `sup-release --interface` (council 4–0, built, provisional);
the two rejected repairs (a+)/(e) recorded with their refutations; and Vista's proposed doctrine —
*the claim belongs to a role, not a body; the interface never runs `sup-boot`*, *a guard keyed on a
proxy must name the predicate it proxies for*, plus the `[UNBUILT]` follow-up to gate `sup-boot` on
fleet-launched provenance so the interface cannot claim **by construction**.

**Carried from day 3**: claim-nonce §7.1 interface-send amendment (council 4–0, merged,
provisional); tombstone rulings 1+2, the ruling-1 cond-2 honest narrowing, the husk-respawn
boot-ritual call, the six-token terminal contract, the rb MIN-D lock-budget note; the abort-recipe
doc defect; G-A..G-C ledger records; the fleet-index OPERATOR-GATES settled row; R9 (it changes the
handoff protocol's shape — say so plainly, not as a clarification).

**Landed with the `fix/handoff-seams` merge (2026-07-27) and still owed a ruling** — three
DESCRIPTIVE amendments to `docs/specs/claim-nonce.md`, now on `main` rather than on a branch:

- **A1** (§6.4) — `sup-handoff-abort` has three arms, and the abort-flag arm is deleted as
  unreachable.
- **A2** (§5.9/§8) — a fail-closed age-gated sweep of `supervisor-handoff-*.md` at four sites,
  where §5.9 said "written once and never deleted" and §8 said `cmd_sup_boot` is the only
  authorized sweep site.
  A1 and A2 both describe **shipped** behaviour a live incident forced; neither is self-promoted.
  The 2026-07-24 succession (inc-651f → inc-7d7d, three attempts in sixteen minutes) hit a handoff
  that was **unabortable in exactly the window the abort verb exists for**, and the wave-1 fix
  reproduced the same failure one attempt later because it modelled the successors as a slot
  instead of a collection. Both amendments are consequences of that.
- **A3** (§6.4/§5.9, fix wave 2) — the one needing a real ruling rather than paperwork: **it
  changes the protocol shape**, and says so in its first line. A1's collection plus A2's
  fail-closed sweep together left a *superseded* successor fully bootable on top of a
  single-valued HANDSHAKE, so a late rival clobbered the winner's handshake and the claim
  transferred to **nobody**. A3 adds an explicit `superseded` state and a **boot refusal**: at
  most one successor may boot, a superseded attempt stays abortable and auditable but not
  bootable, and there is deliberately **no promote verb** (abort, then begin again). It also adds
  `sup-handoff-abort --retire-all` / `--force` and makes `fleet doctor` FAIL on a stranded or
  superseded entry. Reproduced live both ways.

The code merged on its own merits (the stillborn-handoff hole had cost six supervisors); the
amendments are the paperwork and are unratified until you tick them.

## Hard-won warnings

- **Fix waves mint defects: 10/10 lifetime.** Always re-gate; ESCALATE beats a 3rd wave. The
  sharpest instance was a supervisor RULING minting a CRIT — when you rule on a data-structure
  shape, check the protocol underneath is the same shape.
- **A skip-by-default live test is an unexecuted claim** (`test_sup_tombstone_live` shipped an
  impossible assertion through 3 waves, 2 gates and a CONFIRM-CLEAN). Run the live tier yourself
  before merging anything that touches it.
- **Absence is not evidence on this substrate** — records are deletable, archivable, and born with
  `session_id: None`. Any predicate that permits on a missing record fails open.
- **Every worker now boots contextless**: autoclean swept `state/journals/` and archived the day-3
  records (archived = history only; `send`/`respawn` refuse them, only `clean --tombstones` frees
  the name). Put branch, sha, baseline tallies and fences INSIDE every brief.
- Commit BEFORE injecting a fault (`git checkout --` reverts the whole uncommitted file);
  `core.autocrlf=true` makes naive sha compares lie — trust `git status --porcelain`.
- **Never pipe `sup-*` output through `head`/`tail`** — the NONCE is the last line.
- `git log` is the only truth; push main at every green milestone.
