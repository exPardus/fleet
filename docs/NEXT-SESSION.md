# Next session — build M-B (native dispatch), starting with usage-limit continuity

Updated 2026-07-14, after M-A (supervisor identity) shipped. Previous handoff ("author the M-A implementation plan", also 2026-07-14) is superseded — that plan was written and fully executed.

## State

- **M-0 native-substrate spike: COMPLETE and ratified.** Contract = `docs/specs/native-substrate.md` (all 13 G-rows verdicted, 4 gate ratifications recorded at the end — fork-steer, v2.3, G9 deferred, M-A go). Evidence = `spike/m0/VERDICTS.md`. Everything pushed to `origin/main`.
- **M-A supervisor milestone: COMPLETE.** `bin/fleet.py` now ships the full supervisor layer — soul files (`supervisor/GOALS.md`, append-only `supervisor/JOURNAL.md`), claim mechanics (`supervisor/INCARNATION`, epoch check before claim decision, refuse/seize/freeze rules), boot ritual, checkpoint/heartbeat discipline, and the handoff protocol. CLI surface added:
  - `fleet sup-boot [--handoff-inc <id>]` — boot ritual: epoch check → claim/seize/refuse/freeze + boot bundle. Exit 0=hold, 2=refuse, 3=freeze.
  - `fleet sup-checkpoint <text|@file> [--kind CHECKPOINT|PROPOSAL]` — journal checkpoint (claim holder only) + heartbeat refresh.
  - `fleet sup-heartbeat` — heartbeat refresh without a journal write.
  - `fleet sup-status [--json]` — read-only claim/handshake/nag view.
  - `fleet sup-handoff-begin` / `sup-handoff-complete` / `sup-handoff-abort` — context-exhaustion succession protocol (trigger band: begin ~300k tokens, hard-latest 500k).
  - `doctor` gained `supervisor-claim` (advisory) and `supervisor-handoff` (PASS/FAIL) checks; SessionStart gained a nag line.
  - Operator doc: `skills/fleet/supervisor.md` (boot ritual, checkpoint discipline, handoff protocol, binding rules). `skills/fleet/SKILL.md` startup ritual gained step 4 (run the supervisor boot ritual when GOALS.md is active). 761+ tests green (53 supervisor tests added in M-A).
- **Spec of record**: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3, ratified through the M-0 gate. §4 = supervisor design (M-A, now built). §5.1 = operator features (M-B, next).
- **Execution ledger** (M-0 + M-A campaigns): `.superpowers/sdd/progress.md`.
- **G9 probe**: deferred; operator instructions at the end of native-substrate.md. Do not block on it.
- **Repo is public-facing now**: README overhauled, docs/README.md audience index, CONTRIBUTING.md. Keep them true as things ship.

## The job

Author the **M-B plan** (`superpowers:writing-plans` → `docs/superpowers/plans/2026-07-1X-native-pivot-mB-dispatch.md`), then execute via subagent-driven-development on operator go.

M-B scope (spec §5, native `--bg` dispatch + operator-directed features from §5.1):

**Build order — §5.1.1 usage-limit resilience continuity is the FIRST M-B feature after the launch contract itself (operator ASAP directive).** Today's UL1 park (`limited` status + `limit_reset_at`, `bin/fleet.py:1508-1649`) detects the wall by parsing the turn process's stderr tail — a channel that does not exist under `--bg` (daemon owns stderr). Rehomed design (per G11, spec §5.1.1): a limit wall kills the turn silently — no Stop hook fires, roster unchanged — so detection rides the dead-suspected investigation path instead: worker idle/roster-alive with no fresh outcome record ⇒ supervisor's watchtower beat scans the transcript tail with the existing `_parse_limit_signal` regexes ⇒ limit-shaped ⇒ park `limited` with the parsed reset horizon. `limited` stays a sticky park (never `dead-suspected`, never auto-respawned before the horizon); `resume-limited` = fork-steer per G2(b) (or respawn) once `now >= limit_reset_at`. The boot ritual and watchtower beat must treat `limited` workers as parked; the roster-epoch freeze rule must not demote them.

Rest of M-B scope, after usage-limit continuity lands:
1. Launch contract on `--bg` (dispatch pattern, `-n` conventions, fork-steer semantics per G2(b)).
2. Outcome discriminator + Stop-hook result capture (supersedes M-A's interim "today's registry verdicts" reconciliation).
3. Kill via `claude stop` (`fleet interrupt` contract change: transcript survives, worker does not die — is unsatisfiable under daemon-owned sessions; interrupt becomes `claude stop` + overlay mark `interrupted`, respawn stays a separate explicit operator decision).
4. §5.1.2 auto-archival of stale agents (watchtower beat, `claude rm`, never auto-delete).
5. §5.1.3 fleet categories in the agents menu (`-n "<cat>|<name>|<hint>"` dispatch-time encoding).
6. Coexistence rules for the M-B deploy window: legacy name-keyed PID-probed workers become read-only legacy.
7. Pin tests (FLEET_LIVE analog): dispatch haiku bg worker, assert JSON contract per state, hook firing incl. Stop, `claude stop` behavior — run before campaigns.
8. Doctor checks: `claude --version` drift since last pin-test pass, legacy-worker mix flag.

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
