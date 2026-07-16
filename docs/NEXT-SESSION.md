# Next session — after M-C (pivot COMPLETE, 2026-07-17)

Previous handoff (M-C: deletion + SPEC v3, 2026-07-16) is superseded — fully executed. See `knowledge/lessons.md#2026-07-17-mc` for the campaign record.

## State

- **The native-substrate pivot is DONE: M-0, M-A, M-B, M-C all shipped.** `main` = `fleet-impl` @ the mc/pinfix merge (pushed). fleet.py 7378 lines (was 9345); 1054 unit tests + 6-pin FLEET_LIVE tier, all green at close; doctor 12+/12 PASS.
- M-C delivered: 9 debt items; **autoclean** (`fleet autoclean`, `fleet clean --dead-only|--tombstones`, `fleet init --autoclean` schtasks install — **INSTALLED AND LIVE on this machine, every 6h**, doctor-monitored); supersession banners; §6 deletions (detached-Popen, probe-liveness, PID fields, stdout log pipeline, refuse_if_legacy — all grep-dead); dispatch hardening (grace window for the roster startup transient; attach-verify + verified single wedge-retry); **SPEC v3** (status at handoff time: see below).
- Every merge passed adversarial+spec review pairs, fix waves, and re-reviews with new-defect hunts (fired 3/5 — see lessons).

## SPEC v3 status

Drafted by `mc-spec` (branch `mc/spec`, 5 commits: v3 body 271 lines, v2.3 moved intact to `docs/SPEC-v2-history.md`, stale-corpus banners in ROADMAP/PLAN). Adversarial promotion review was in flight at the last checkpoint — **check the journal tail / mc/spec branch state before assuming it merged.** If the review returned PROMOTE and it merged: SPEC.md v3 is the spec of record. If not: finish that gate first; the reviewer prompt and rules (no self-promotion, MOVE-never-delete history) are in the journal.

## Open items (priority order)

1. **Three-tier command proposal** (`docs/specs/three-tier-command.md`, DRAFT) — operator-originated: human-facing interface session / background supervisor (a fleet worker with scheduled beats) / workers. Needs an adversarial design review before any build (M-D candidate). Includes the **per-body claim nonce** fix for the zombie-manager class (see lessons — a fork-session restart created a second live supervisor body sharing claim+sid; the claim protocol cannot see it).
2. **UL horizon-parser gap**: "resets 12am (Asia/Qyzylorda)" not parsed → null-horizon park requiring `resume-limited --force-now`. Small fix + test in the transcript scanner.
3. **Compressed output contracts at tier boundaries** (operator ask, token efficiency): fold a terse-output clause into campaign-template + spawn-etiquette task briefs (NOT a plugin prerequisite). Draft language in three-tier-command.md §hazards.
4. **Live-test marker isolation** (open defect from M-B lessons): temp-home `fleet init` in live tests clobbered the real `~/.claude/fleet-home` marker once; post-N1 init guards the marker, but verify the pin suite path and add an explicit isolation fixture if any gap remains.
5. **Dogfood outward** (standing goal 5): next campaign should be a non-fleet repo. External friction is the best defect report.
6. Cosmetic/upstream: retired fork-predecessor sessions can sit `blocked` in the agents menu ("requires input" on a husk nobody will answer) — fleet stops them on discovery; consider an autoclean tier-2 extension (stop-then-rm for retired-sid blocked entries) or file upstream.

## Standing rules (unchanged)

- CLAUDE.md binds (py -3.13, forward slashes in hooks, no Git-Bash `&`, views read-only).
- Adversarial review of evidence AND code; new-defect hunt on every fix wave; grep-receipt gate on every enumeration; no author promotes its own spec.
- Never trust a mocked `run=` test as proof a real CLI call works — the live pin tier has now caught production Criticals seven times.
- Push `fleet-impl` + ff `main` at every green milestone. Supervisor GOALS.md binds the manager (frugality, beats, 300–500k handoff band).
- One steer per worker turn until a supersede convention exists (two-message scope confusion, see lessons).

## Cleanup owed (cheap)

- Worktrees: `C:/proga/fleet-mc-*` (debt/autoclean/docs/delete/spec) removable after mc/spec merges (`git worktree remove` + branch delete); also stale `C:/proga/fleet-mb-*` and `C:/proga/claude-fleet-wt/c2` from earlier campaigns.
- `mc-*` fleet workers: idle, will auto-archive via the live schtasks autoclean past 24h — no action needed (that's the feature).
- Zombie transcript `c787a667*.jsonl` in the project dir: kept as incident evidence; delete when the per-body-nonce work lands.
