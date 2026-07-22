# claude-fleet roadmap — the ultimate multi-session programming tool

**Status:** vision v1 (2026-07-07) — **the thesis and design principles below still bind; the phase *sequencing* no longer describes how this project is run.** See the reality banner immediately below before using this as a plan.

> ### ⚠ Reality check (2026-07-23) — this doc and the build record have diverged
>
> This roadmap references "SPEC.md M1–M5". **`SPEC.md` is v3 and has no M1–M5** — its §18 milestone list is `M-0 / M-A / M-B / M-C / M-D / M-E / Reconcile / M-F / M-G`, the track the native-substrate pivot started on 2026-07-13. Everything built since then ran on that track, not on the phases below.
>
> What that means concretely:
> - **Phase 1.5 (Portability) is partly shipped and its spec is superseded.** `docs/specs/portability.md` is `SUPERSEDED` — the daemon owns liveness now, so the probe-matrix design it specced is dead. But the *goal* shipped anyway: `_PosixPlatform` is a real backend, Linux is verified by the suite, macOS is unreceipted. The `FLEET_HOME` / `fleet init` moves shipped long ago.
> - **Phase 1.6 (Terminal surface) shipped**, 2026-07-09.
> - **The soak gates below are not being enforced.** `SOAK GATE 1 SIGNED` appears nowhere in `knowledge/lessons.md`, yet `docs/PLAN-PROGRESS.md` marks every C3+ row GATED on that signature — while four milestones shipped around it.
> - Phases 2 through 6 (watchtower, providers, telegram, web UI, intelligence, reach) are **untouched and still accurate as intent.**
>
> **Which framing governs is an open operator gate** (`docs/OPERATOR-GATES.md`). Until it is settled, treat the design principles and the Phase 2–6 stubs as live, and the sequencing/soak machinery as history.

## Why ours wins (thesis)

Survey (PRIOR-ART.md) shows every competitor picked one surface and married it: tmux (Claude Squad), web kanban (Vibe Kanban), macOS app (Conductor), swarm framework (claude-flow). Fleet's bet: **state is plain files + a CLI; every surface is a disposable view.** Terminal, manager session, web dashboard, Telegram — all read/write the same registry, mailbox, journals, knowledge. Add or drop surfaces without touching the core. Plus the two things nobody has (first-party included): **durable resumable workers across projects** and **a manager that learns** (git-tracked knowledge loop).

Design principles (all phases):
1. **One state, many views.** No surface owns data. Core never depends on any surface.
2. **Daemon is additive, never required.** CLI + hooks work standalone forever; the watchtower/web/telegram layers degrade away cleanly if not running.
3. **The intelligence is Claude.** Dashboards don't make decisions; the manager session (or an on-call manager turn) does. Surfaces route information to and from intelligence.
4. **Steal shamelessly, stay small.** Each phase ships a usable increment; no framework-building.
5. **Runs everywhere.** Windows, Linux, macOS are all first-class. All OS-specific behavior (launch, kill, attach, notify, service install, liveness) lives in ONE platform-adapter module; everything else is pure pathlib/stdlib. No surface or phase may add an OS-specific dependency outside the adapter.

## Phase 1 — Core — **SHIPPED**

Spawn/steer/attach/respawn, mailbox+hooks, journals, doctor, skill, knowledge loop. Done-criterion ("first real multi-worker campaign completes and writes lessons") was met by Campaign 2, 2026-07-09; many campaigns have run since. The v2 "M1–M5" numbering this section used to cite died with the SPEC v3 rewrite — see `SPEC.md` §18 for the live milestone list.

## Phase 1.5 — Portability (Win/Linux/macOS) — **GOAL SHIPPED, SPEC SUPERSEDED**

**Status 2026-07-23:** `_PosixPlatform` is a real backend (crontab autoclean, POSIX atomic append), `grep -c "raise UnsupportedPlatformError" bin/fleet.py` → 0, the interpreter floor is 3.10 and the suite runs green at it, and **Linux is verified — 200 Ubuntu failures went to 0** in the reconcile campaign. macOS shares that backend but is **unreceipted**. The *spec* below is `SUPERSEDED`: the native daemon owns liveness now, so its probe-matrix / `boot_identity` / `killpg` design is dead — the bullets survive as intent, not as a build plan. Remaining: a macOS receipt, and CI matrix (never built).

Ship before Phase 2 (watchtower multiplies OS surface). Spec: `docs/specs/portability.md` *(superseded — read its banner)*. Core moves:

- `fleet init` command generates machine-local artifacts (worker-settings.json with correct python path + FLEET_HOME, shims, PATH help) — nothing machine-specific committed to git.
- `FLEET_HOME` env var (default: resolved from fleet.py location) replaces every hardcoded `C:/proga/claude-fleet`.
- Platform adapter isolates: detached spawn (Win32 flags vs `start_new_session`), kill-tree (taskkill /T vs killpg), PID+ctime liveness (PowerShell/wmic vs /proc vs ps), attach terminal (wt/PowerShell vs $TERMINAL/gnome-terminal/tmux vs Terminal.app/iTerm osascript), notifications (toast vs notify-send vs osascript).
- Python invocation via `sys.executable` / `python3`, never `py -3.13` outside Windows shims.
- CI: GitHub Actions matrix (windows/ubuntu/macos) running unit tests + hook smoke tests.

## Phase 1.6 — Terminal surface (fleet inside the Claude Code TUI) — **SHIPPED** (2026-07-09)

Spec: `docs/specs/terminal-surface.md`. Independent of watchtower; buildable any time after Phase 1. Statusline, `/fleet:*` commands and the plugin package all shipped; its binding view rules (no lock, no probe, no write) are now enforced by `tests/test_terminal_surface.py` and restated in `CLAUDE.md`. The SessionStart briefing also shipped here and was **removed on 2026-07-22** (D7) — see below.

Pure UX and packaging — no new capability, no new state, no daemon. One read-only derivation (`fleet.status_snapshot()`: reads `fleet.json` + `mailbox/`, takes no lock, spawns no probe, writes nothing) fed four views, of which three survive:

- **statusline** — always-on one-line fleet readout under the input box. Dims stale rows rather than asserting liveness it never probed for.
- **`/fleet:*` slash commands** — read-only commands inline their CLI output; mutating ones route through the model so the permission prompt applies (`fleet kill` is terminal, `fleet clean` deletes journals).
- ~~**SessionStart briefing** — the SPEC §10 startup ritual, automated. Suppresses itself inside workers via a `FLEET_WORKER` env stamp.~~ **REMOVED 2026-07-22 (D7).** It suppressed itself inside workers but not inside *other projects*: a globally-enabled plugin fires its SessionStart hook in every session on the machine, so opening any unrelated repo injected this fleet's open operator gates, whole worker table and knowledge index into that session. The ritual moved back into the `fleet` skill, where it runs when someone has actually chosen to manage a fleet.
- **plugin package** — commands + skill, and (since D7) no hooks. Cannot ship the statusline (Claude Code forbids it); `fleet init --statusline` installs that separately, refusing to clobber a foreign one.

Done when: fleet state is visible without typing a command, and `/fleet:overview` answers "where am I" in one screen.

## Phase 2 — Watchtower (continuous monitoring)

The one deliberate v1 exclusion (no daemon) gets revisited — continuous monitoring needs a resident process. `fleet watch` (same fleet.py, subcommand; auto-start via platform adapter: Scheduled Task / systemd user unit / launchd agent):

- Tails `logs/*.jsonl` + registry; evaluates **rules**: worker idle > N min with mail pending, turn crashed, context burn high (token counts from stream events), budget threshold crossed, needs-input detected, journal not updated in > N turns.
- Emits typed events to `state/events.jsonl` (single writer stays fleet.py) and fans out to **notifier functions** (Phase 2: desktop notification via platform adapter + file sink; Phase 3: Telegram) — a static `notify(event)` dispatch over a fixed sink list, **not a plugin framework**.
- <!-- phase2-mirror --> **Context management surfaces here** (steal: agent-farm context thresholds): watchtower flags "worker at ~70% context" → notifies manager/human. **Auto-respawn is cut from Phase-2 v1 (notify-only); it is re-vetted post-Phase-3** once remote manual respawn exists — v1 detects and notifies context-threshold / dead / idle-with-mail and never autonomously mutates state. (M10/F20: an unattended respawn loop on a context-burning task has no hard per-worker cap and no fleet-wide cost rule in v1; the "auto-respawn demonstrated lossless" done-criterion is deleted, not deferred.)
- `fleet status --delta` (steal: sitrep) ships here — watchtower keeps last-seen cursor per consumer.

<!-- phase2-mirror --> **v1 scope notes (mirrored from `docs/specs/phase-2-watchtower.md` — must read identically):** **auto-respawn cut from Phase-2 v1 (notify-only); notifier functions not a plugin framework; service install → docs snippets** (logon-triggered interactive schtasks / systemd user unit / launchd shown as documented commands through the platform adapter, not a fleet-run installer). The **needs-input / journal-staleness rule disposition is a placeholder pending the C5 watchtower spec decision** — journal-staleness is trivially detectable (journal mtime / turn-count delta) and expected to ship v1; needs-input ships as a heuristic OR is deferred to a Phase-3 re-vet. Not resolved here: see `docs/specs/phase-2-watchtower.md` OQ1 and the C5 spec task.

Done when: phone-free day — you leave, come back, nothing silently died.

## Phase 2.5 — Provider profiles (proxies & alternate backends)

Spec: `docs/specs/providers.md`. Named provider profiles (git-tracked config, gitignored secrets) injected as env per worker turn AND attach: API proxies (LiteLLM-style Anthropic-compatible gateways → any model behind them), alternate Anthropic accounts, Bedrock/Vertex. `fleet spawn --provider <profile>`; provenance in registry; token-based accounting where $ figures lie. Independent of watchtower — can build any time after Phase 1.5. Non-Claude worker CLIs stay Phase 6.

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
- **fleet-index — context assembly from a derived code index** (`docs/specs/fleet-index.md`, M1 ready-for-build). Attacks the largest recurring cost in the fleet: every worker, subagent and respawn re-reading the same files to orient. A stdlib indexer emits one plain-text shard per source file; `fleet spawn --context <files>` renders those shards into the prompt so a worker starts knowing where things are. **This is the graveyard's entry 5 rebuilt** ("Knowledge-Aware Context Assembly at Spawn/Respawn" — right moat, wrong build): the load-bearing objection was a *silently-rotting tag schema*, answered here by SHA-256-keyed shards that repair or refuse but never serve an unverified coordinate. Ranking, embeddings and semantic chunking stay dead — this is exact line-anchored fact only, and grep on the raw repo keeps working untouched. **Sharding per source file is what makes it safe under fleet's concurrency:** a single global symbol table conflicts at N=2 workers on *disjoint* files, retiring the proven 7-wide disjoint-file parallelism; per-file shards cannot collide at any N.

## Phase 6 — Reach (optional, demand-driven)

- Adopt/wrap native Agent View once out of research preview (re-evaluate; PRIOR-ART decision point).
- GitHub-Issues-as-queue adapter (steal: code-conductor) for issue-shaped work.
- <!-- F26 --><!-- M25 --> Multi-machine: **per-machine registries with a read-only federation view — never a shared writable fleet.json or git-synced state/; liveness and interrupt stay machine-local.** (`turn_pid`/ctime probes and taskkill are meaningful only on the owning host — a shared writable registry would let machine B recompute machine A's live worker as `dead` and `interrupt` could taskkill an unrelated local PID; `state/` is gitignored by the SPEC layout and atomic-rename locking has no cross-network guarantee, so single-writer breaks over a network FS.) Workers on the exPardus dev server surface through the federation view; each host owns and writes only its own registry.
- Other agent CLIs as workers (Codex etc.) behind the same registry — the mailbox/hook layer is Claude-specific, launcher+registry aren't.

## Sequencing & discipline

Strict order 1→1.5→2→3; 2.5 anytime after 1.5; 4 and 5 can interleave after 3. Each phase gets its own short spec + adversarial review before build (same process that caught 3 blockers in SPEC v1). Phase never starts until previous phase survived a week of real use — features earn their way in by friction actually felt, not imagined.

<!-- soak-defs --> **Soak gates (usage-denominated, not calendar weeks).** "Survived a week of real use" above is shorthand; the binding gates are **usage-denominated — a slow week extends the gate, never passes on elapsed time alone** (PLAN soak-gate defs: Soak 1 = ≥15 spawns across ≥3 distinct days; Soak 1.5 = ≥5 green-matrix pushes across ≥3 days; Soak 2 = ≥5 workdays real load on ≥3 of them; etc.). **Spec drafting (docs-only) may proceed during the prior phase's soak while build may not** — a later demand "yes" must find a ready-for-build spec already waiting. Enforcement is mechanical, not manager memory: **each next-phase task file greps for the dated `SOAK GATE <n> SIGNED` line and blocks if absent** (PLAN §0.2.1) — the line being Altai's signature in `knowledge/lessons.md` against a defined audit artifact. **Demand-check valves (PLAN §0.4) gate the BUILD only — specs always run**, so unfelt features are never built on schedule-momentum.

Review disciplines (learned from idea-forge run 1, `docs/IDEA-FORGE-REPORT.md`):
- **Flag, not subsystem:** at spec time, re-vet every proposed subsystem for a flag-sized alternative that delivers 80% of the value.
<!-- F26 --><!-- M25 --> 
- **Name your invariants:** every spec/idea must list which architectural invariants it touches and why it doesn't violate them, by citing number against **SPEC's numbered nine-invariant section** ("Architectural invariants (numbered)") — all nine, not the five once listed here. The four this list previously omitted are exactly the ones Phases 2–4 stress hardest: **(6) single-writer registry, (7) one-live-claude-per-session, (8) platform-adapter-only OS branching, (9) one-state-many-views**. Every phase stub carries a mandatory `## Invariants touched` section naming the cited numbers and why each is preserved.
- **Check the graveyard first:** IDEA-FORGE-REPORT §5 records ten dead ideas with causes of death — don't re-propose adjacent things without answering the cause.
- <!-- F27 --><!-- M7 --> **Re-run the live tier at every gate:** the tier-3 scripted live-integration suite (SPEC §12; haiku worker, temp `FLEET_HOME` + throwaway repo, asserted budget ceiling) — **the live-integration tier is re-run at every phase gate**, and required before merging any change to `launch_turn`, hooks, or stream parsers. Campaign-0 proved 338 green unit tests coexisted with real bugs only a live worker exposed; each run also archives sanitized stream logs into `tests/fixtures/streams/` (the watchtower's rule-corpus source). **[STALE — 2026-07-17 SPEC v3 sweep: `tests/fixtures/streams/` and the stream-json tier were deleted with the stdout log pipeline (native-substrate pivot §6); the live tier is now the `FLEET_LIVE` native pin suite (`tests/integration/test_native_pin.py`) — see `docs/SPEC.md` v3 §17.]**

## Speccing workflow (multiple sessions in parallel)

Specs live in `docs/specs/`, one file per phase/topic; stubs are pre-seeded with scope, constraints, and open questions. A speccing session:

1. Claims a stub by setting its `Status:` line to `drafting (<date>)` and committing immediately (cheap lock against parallel sessions).
2. Reads SPEC.md + ROADMAP.md + PRIOR-ART.md first; inherits Phase-1 architecture and the design principles verbatim — a spec that violates "one state, many views", "daemon additive", or "platform adapter only" is wrong by definition.
3. Answers every open question in the stub (delete none; mark resolved with the decision + why).
4. Runs an adversarial review agent against the draft (the SPEC v1 process: verify CLI/API facts, attack races, YAGNI-kill features) and folds findings in with a disposition appendix.
5. Sets `Status: ready-for-build` — build sessions only build `ready-for-build` specs.
