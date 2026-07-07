# claude-fleet roadmap — the ultimate multi-session programming tool

**Status:** vision v1 (2026-07-07). SPEC.md M1–M5 = Phase 1 here; this doc layers the rest. Nothing in later phases changes Phase-1 architecture — that's the point.

## Why ours wins (thesis)

Survey (PRIOR-ART.md) shows every competitor picked one surface and married it: tmux (Claude Squad), web kanban (Vibe Kanban), macOS app (Conductor), swarm framework (claude-flow). Fleet's bet: **state is plain files + a CLI; every surface is a disposable view.** Terminal, manager session, web dashboard, Telegram — all read/write the same registry, mailbox, journals, knowledge. Add or drop surfaces without touching the core. Plus the two things nobody has (first-party included): **durable resumable workers across projects** and **a manager that learns** (git-tracked knowledge loop).

Design principles (all phases):
1. **One state, many views.** No surface owns data. Core never depends on any surface.
2. **Daemon is additive, never required.** CLI + hooks work standalone forever; the watchtower/web/telegram layers degrade away cleanly if not running.
3. **The intelligence is Claude.** Dashboards don't make decisions; the manager session (or an on-call manager turn) does. Surfaces route information to and from intelligence.
4. **Steal shamelessly, stay small.** Each phase ships a usable increment; no framework-building.

## Phase 1 — Core (= SPEC.md M1–M5, in progress)

Spawn/steer/attach/respawn, mailbox+hooks, journals, doctor, skill, knowledge loop. Done when: first real multi-worker campaign completes and writes lessons.

## Phase 2 — Watchtower (continuous monitoring)

The one deliberate v1 exclusion (no daemon) gets revisited — continuous monitoring needs a resident process. `fleet watch` (same fleet.py, subcommand; Scheduled Task on logon, survives reboot):

- Tails `logs/*.jsonl` + registry; evaluates **rules**: worker idle > N min with mail pending, turn crashed, context burn high (token counts from stream events), budget threshold crossed, needs-input detected, journal not updated in > N turns.
- Emits typed events to `state/events.jsonl` (single writer stays fleet.py) and fans out to pluggable **notifiers** (Phase 2: Windows toast + file; Phase 3: Telegram).
- **Context management goes automatic here** (steal: agent-farm context thresholds): watchtower flags "worker at ~70% context" → notifies manager/human; `--auto-respawn` opt-in policy respawns from journal at threshold. Journal-quality gate: respawn refuses if journal stale, pings worker to update first.
- `fleet status --delta` (steal: sitrep) ships here — watchtower keeps last-seen cursor per consumer.

Done when: phone-free day — you leave, come back, nothing silently died.

## Phase 3 — Telegram bridge (fleet in your pocket)

Two-way. Bot (existing Telegram bot infra on this machine can be reused):

- **Out:** watchtower events → Telegram messages. Worker needs input → you get the question with worker name + 5-line context.
- **In:** replies map to `fleet send <name>` (reply-to threading = worker addressing); commands `/status`, `/peek <name>`, `/spawn`, `/kill`. 
- **Manager-on-call (the killer feature):** a Telegram message can wake a *manager turn* — headless claude session with the fleet skill — that reads status, decides, acts, replies. You're not steering workers from your phone; you're messaging your chief-of-staff who steers them. Nobody in the survey has this.
- Auth: single-chat-id allowlist, token in fleet state, never in git.

Done when: full campaign run start-to-finish from phone only.

## Phase 4 — Web UI (mission control)

Local FastAPI (or stdlib http) server, same machine, reads state dir; no build-step frontend (single HTML + htmx/alpine or similar — keep it boring):

- Fleet board: worker cards (status, cost, context %, last activity) — kanban-ish columns by status (steal: Vibe Kanban), but cards are *sessions*, not tasks.
- Live peek pane (SSE tail of digest, not raw jsonl), send box, attach button (launches terminal via local endpoint), journal + diff viewer per worker (steal: Crystal/Conductor diff-first review).
- Events timeline + spend telemetry per worker/project/day (steal: mission-control cost focus).
- Knowledge browser: INDEX/lessons/projects rendered, editable.
- Serve over Tailscale later → remote mission control without exposing anything public.

Done when: you stop running `fleet status` by hand.

## Phase 5 — Intelligence layer (the moat)

Everything here is doctrine + knowledge, mostly prose and small CLI additions — this is what compounds:

- **Trust ledger** (steal: fleet-cli trust scoring): structured results-per-task-type in knowledge; manager consults before choosing mode/model/decomposition.
- **Plan-approval gate as first-class flow** (steal: Agent Teams): `fleet spawn --gated` = plan-mode first turn, manager approves plan → auto-respawn in accept mode.
- **Definition-of-done contracts:** task spec includes checks; Stop-hook veto bounces premature completion claims with the failing check (steal: TaskCompleted exit-2 pattern).
- **Session seeding** (`fleet spawn --from <name>`, steal: ccmanager): warm-start related work from predecessor journal.
- **Campaign templates:** playbooks graduate into parameterized recipes (review-pipeline, migration-fanout, research-sweep) the manager instantiates.
- **Broadcast + named addressing** (`fleet send --all`).
- Periodic **knowledge distillation**: manager turn that compacts lessons.md, prunes stale project notes — memory that stays sharp instead of accreting.

## Phase 6 — Reach (optional, demand-driven)

- Adopt/wrap native Agent View once out of research preview (re-evaluate; PRIOR-ART decision point).
- GitHub-Issues-as-queue adapter (steal: code-conductor) for issue-shaped work.
- Multi-machine: registry/state sync via git or Tailscale-mounted state; workers on the exPardus dev server.
- Other agent CLIs as workers (Codex etc.) behind the same registry — the mailbox/hook layer is Claude-specific, launcher+registry aren't.

## Sequencing & discipline

Strict order 1→2→3; 4 and 5 can interleave after 3. Each phase gets its own short spec + adversarial review before build (same process that caught 3 blockers in SPEC v1). Phase never starts until previous phase survived a week of real use — features earn their way in by friction actually felt, not imagined.
