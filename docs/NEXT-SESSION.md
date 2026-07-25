# Next session — continue the day-3 autonomous build-out (handoff written 2026-07-24 ~12:15Z)

You are the fresh manager session. The claim is **RELEASED** (predecessor supervisor `inc-...7d7d`
released cleanly at 12:09Z — ceiling-locked at 207k). `fleet sup-boot` claims fresh via rule 1b:
no seizure, no freeze window. Operator wants: **same work, autonomous — churn the spec backlog +
testing until fleet is a full build, launch-ready.**

## Boot ritual (exact order)

1. Invoke the `fleet` skill. `git pull` first.
2. `supervisor/JOURNAL.md` is MODIFIED-uncommitted (predecessor's release entry) — commit+push it
   before anything else.
3. `py -3.13 bin/fleet.py sup-boot > <scratchpad>/boot.txt 2>&1` then grep
   `^(VERDICT|INCARNATION|NONCE):` from the FILE. **Never pipe sup-* output through head/tail —
   the NONCE is the last line and truncation cost a claim once already (lessons day-3, class-4).**
   Carry the nonce; present `--nonce` on every mutating verb; sup-checkpoint rotates it.
4. Read (in order): `supervisor/JOURNAL.md` last ~10 entries (the full 5-generation day-3 arc +
   release state), `docs/AUTONOMOUS-2026-07-24.md` (run ledger: G-A..G-C councils, gate ledger,
   build queue), `knowledge/lessons.md#2026-07-24` day-3 entry.

## Standing operator directives (verbatim intent, unchanged)

- Autonomous. Operator-gated questions → **4-councilor council of differing personalities
  (risk auditor / delivery pragmatist / strategist / incident responder) + synthesis**; act on
  synthesis; record every gated item in `docs/AUTONOMOUS-2026-07-24.md` for morning ratification.
- **Full spec build-out, launch-ready** — when this queue drains, sweep `docs/specs/**` for
  remaining `[UNBUILT]` and keep building+testing (v2-deferred rows stay deferred).
- Band 150–200k binds you: checkpoint at wave boundaries; at the band, RELEASE (proven path) —
  **do NOT use sup-handoff until the handoff-seams fixes are merged; the handoff path is
  defective** (successors dispatch into dontAsk auto-deny and can never sup-boot; 5 stillborn
  attempts today).

## Immediate queue (in order)

1. **handoff-seams fix wave 2** — brief ALREADY WRITTEN at `state/tasks/hs-fixwave2.md`
   (predecessor wrote it while ceiling-locked). Branch `fix/handoff-seams` (worker
   `handoff-seams`, idle; check `git worktree list` for its worktree). Dispatch the wave, then
   the gate cycle per the 09:43+ journal checkpoints (hs-rs/hs-rb verdicts recorded there),
   re-gate, merge, push. This unblocks safe supervisor handoffs forever.
2. **Merge `build/sup-tombstone`** — §10.4 kill/respawn choreography, went through 3 fix waves +
   1 escalation + micro-confirm (see 06:53–08:10 checkpoints for exactly where it stopped).
   Still owed: the FLEET_LIVE=1 haiku integration run
   (`tests/integration/test_sup_tombstone_live.py`, written, UNEXECUTED) before merge. Then
   merge no-ff, both floors, push.
3. **fleet-q M1+M2 build** — spec gated-sound on main (`docs/specs/fleet-index.md`,
   `ready-for-gate`; operator ORDERED full build). Honor §11.7 [UNVERIFIED] live-receipt
   acceptance item + §16 doc-sync list. Worktree recipe: manager-side `fleet index init` step.
4. **Cleanup owed**: 5 leaked plaintext-token files `state/supervisor-handoff-inc-*.md` (§5.9
   violation — unlink once no handoff is pending; the D2 sweep from wave-1 may handle some);
   stillborn successor husk records (`sup|inc-...|successor`, working/0-turn — verify sessions
   dead, then kill/clean); old worktrees for merged branches; ~17 pre-run idle workers age
   toward autoclean.
5. **Doc-sync owed**: SPEC.md §18 rows for tombstone+handoff-seams when they merge; claim-nonce
   §5.9 marker/sweep prose; `skills/fleet/supervisor.md` abort recipe gains `--nonce` (doc
   defect, 08:20 checkpoint). `claim-nonce §7` taxonomy row for sup-spawn + the §7.1 amendment
   are **OPERATOR-owned — queue, never edit**.

## Operator ratification stack (present when operator returns; only they tick)

claim-nonce §7.1 interface-send amendment (council 4-0 (a), built+merged, provisional);
tombstone rulings 1+2 + ruling-1 cond-2 honest narrowing + husk-respawn boot-ritual call +
six-token terminal contract; abort-recipe doc defect; G-A..G-C ledger records;
fleet-index OPERATOR-GATES settled row (order of record: lessons day-3 entry).

## Hard-won warnings (today's blood)

- Fix waves mint defects: **8/8 lifetime**. Always re-gate; ESCALATE beats a 3rd wave (fired
  once today, correctly).
- FI discipline: commit BEFORE injecting (a `git checkout --` restore destroyed uncommitted work
  once); fabricated-state fixtures are a live defect class (found twice today).
- Windows: `os.replace` onto open files raises (registry + INCARNATION now retry; shards
  specced); pipe chars invalid in paths (`name_fs_stem` maps `|`→`~` — use it for ANY name-keyed
  path).
- Worker fences in worker vocabulary: "no `git push` of ANY ref". Reviewers get "run, don't
  read" + mandatory FI-theater checks — 3 green test-theater survivors were caught that way
  today.
- `git log` is the only truth; push main at every green milestone.

## State at handoff

main = `fd49071` (pushed, 2039/8 both floors). Unmerged gated branches: `build/sup-tombstone`
(2137/11 at tip), `fix/handoff-seams` (2063/8 at tip, wave 2 pending). Suite floor: both
`py -3.13` and `py -3.10` must stay zero-failure. Claim: released-clean. Prior handoff's own
content (overnight run close-out) is fully executed and superseded — its record lives in
`docs/OVERNIGHT-2026-07-23.md`, the ledger, and lessons day-2/day-3 entries.
