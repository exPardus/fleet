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

## Where things stand

`main` = `a2358f2`, pushed. **`build/sup-tombstone` is MERGED** (§10.4 kill/respawn tombstone) —
both floors on main measured **2147 passed / 16 skipped on py3.13 AND py3.10**, receipts 56/56.
GitHub PR #9 carried that branch and needs closing/reconciling.

Two builds were in flight when this was written, both on their own branches, **neither gated,
neither merged**:

1. `fix/handoff-seams` — worker `hs-fix2`, **fix wave 2** (rulings R9 + R10), brief
   `state/tasks/hs-fixwave2-dispatch.md`. Base `90e0ddf`, cut from main@`fd49071`. **Last wave
   before the final gate; a 3rd needs escalation.** When it reports green: advance the review
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
