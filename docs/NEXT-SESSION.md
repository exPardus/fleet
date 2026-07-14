# Next session — author the M-A implementation plan

Updated 2026-07-14, after the M-0 spike closed. Previous handoff (C4 soak day 2, 2026-07-10) is superseded; the native-agents pivot overtook it.

## State

- **M-0 native-substrate spike: COMPLETE and ratified.** Contract = `docs/specs/native-substrate.md` (all 13 G-rows verdicted, 4 gate ratifications recorded at the end — fork-steer, v2.3, G9 deferred, M-A go). Evidence = `spike/m0/VERDICTS.md`. Everything pushed to `origin/main`.
- **Spec of record**: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3, ratified through the M-0 gate. §4 = supervisor design (M-A's scope). §5.1 = operator features (M-B, usage-limit continuity FIRST).
- **Supervisor soul seed exists**: `supervisor/GOALS.md` (operator-authored target + cost frugality). JOURNAL.md, INCARNATION, HANDSHAKE do not exist yet — M-A builds them.
- **Execution ledger** (this campaign): `.superpowers/sdd/progress.md` — full task/commit/review record of the spike.
- **G9 probe**: deferred; operator instructions at the end of native-substrate.md. Do not block on it.
- **Repo is public-facing now**: README overhauled, docs/README.md audience index, CONTRIBUTING.md. Keep them true as things ship.

## The job

Author the **M-A plan** (`superpowers:writing-plans` → `docs/superpowers/plans/2026-07-1X-native-pivot-mA-supervisor.md`), then execute via subagent-driven-development on operator go.

M-A scope (spec §4, against TODAY's backend — no --bg dispatch changes):
1. `supervisor/JOURNAL.md` conventions + checkpoint write helper.
2. Claim mechanics: `supervisor/INCARNATION` under `fleet.lock` — schema (incarnation id, session_id, heartbeat ts), claim rules (refuse / seize-on-stale / freeze-on-ambiguous), epoch check BEFORE claim decision.
3. Boot ritual (skill step + SessionStart extension): GOALS + JOURNAL tail + knowledge INDEX + `claude agents --json` + fleet status → M-A interim reconciliation = today's registry verdicts, NOT the outcome discriminator (its inputs are M-B).
4. Handoff protocol: checkpoint → dispatch successor → HANDSHAKE file (id-verified) → claim transfer → old exits; timeout ⇒ old resumes + `claude stop`s limbo successor. Trigger band: 300k begin / 500k hard (spec §4).
5. Nag predicate (file-only): GOALS active AND (no claim OR heartbeat stale) → doctor check + SessionStart hook line.
6. Tests: claim/seizure/handshake state machine, boot-ritual assembly, stale-HANDSHAKE hygiene (seize deletes, refuse is read-only), handoff-timeout drill.

Plan-authoring facts from the contract (do not re-derive): dispatch pattern + `-n` conventions, fork-steer semantics, `claude stop` fires no Stop hook, startedAt unstable, state literals incl. "waiting for permission prompt", ScheduleWakeup exists but scheduler dies with stop.

## Standing rules

- CLAUDE.md rules bind (py -3.13, forward slashes, no Git-Bash `&`, views read-only).
- Per-task adversarial review of EVIDENCE and code both — the spike caught overclaims in 5/8 tasks; keep the bar.
- Push `fleet-impl` and fast-forward `main` at every green milestone (operator standing directive).
- Controller-side research reports land in repo files BEFORE anything cites them.
- Supervisor GOALS.md binds the manager session too (cost frugality: cheapest-capable models, no idle polling; handoff at 300–500k context).

## Cleanup owed (cheap, any session)

- `claude rm` the remaining m0 husks when convenient (failed g2b/g2c, done probes) — or leave for M-B auto-archival to eat as its first meal.
- Spike artifacts under `spike/m0/` are tracked receipts — leave them.
