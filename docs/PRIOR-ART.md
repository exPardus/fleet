# Prior art survey (2026-07-07)

Three parallel research sweeps: terminal/tmux orchestrators, native Anthropic capabilities, broader fleet-management ecosystem. Summary + implications for the spec.

## Headline findings

1. **Native "Agent View" overlaps M1 hard.** `claude --bg` + `claude agents` (research preview, CC ≥2.1.139; docs: code.claude.com/docs/en/agent-view) already ships: durable daemon-hosted background sessions surviving terminal close, `claude agents --json` machine-readable registry (`{id, cwd, state, pid, waitingFor, sessionId, name}`), `claude attach <id>` TUI takeover, `claude respawn`, peek-and-reply steering without attach, `Notification` hook firing `agent_needs_input`/`agent_completed`, automatic worktree isolation. Caveats: research preview (flags churn between versions), long-lived processes (not fleet's short-lived-turn model), interaction with `--settings`-injected hooks undocumented.
2. **Fleet's actual gap is real and unfilled**, even first-party: manager hierarchy + durable resumable workers + persistent cross-session knowledge/journals. Agent Teams (experimental) has mailbox/task-list/hooks but teammates are ephemeral — die with lead, no resume, no nesting. Platform Managed Agents API caps delegation at depth 1. Anthropic's own decision matrix (code.claude.com/docs/en/agents) confirms nothing native combines durability + hierarchy + memory.
3. **Ecosystem is crowded but orthogonal.** Big players are UI-first (Vibe Kanban 27k★, Crystal/Nimbalyst 3k★, Claude Squad 8k★ tmux+worktree, Conductor macOS, Devin Desktop/ACP, Warp). Frameworks (claude-flow/ruflo swarms, Citadel 634★ layered Marshal→Archon→Fleet) are heavyweight. Nobody does: plain-CLI durable sessions + hook-mailbox steering + git-tracked manager knowledge loop on Windows. Minor: a small "fleet" CLI exists (oguzhnatly/fleet, 13★) — name collision, ignorable.

## Decision point for the spec (flag to owner)

Spec §2 rejected `--bg` because hook/settings interaction is undocumented. Research strengthens the *wrap* case: `claude agents --json` + Notification hooks could replace fleet's registry/liveness/PID machinery. Recommendation: **keep spec as-is for M1–M2** (short-lived `-p` turns are load-bearing for mailbox-drain semantics and per-turn `--settings`), but add doctor visibility of `claude agents` sessions (already specced) and re-evaluate wrapping Agent View at M4 once its flags stabilize. Research-preview churn (2.1.139→2.1.202 changes) is a real breakage risk for a wrapper today.

## Steal-worthy ideas (dedup of 26 candidates, ranked)

Adopt cheap, now:
1. **Delta-only status** (`fleet sitrep` pattern, oguzhnatly/fleet): `fleet status --delta` shows only changes since last call — cuts manager-context churn per poll.
2. **Context-remaining warning** (agent-farm): stream-json result events expose token usage; `status` warns when a worker is likely deep into context → proactive respawn instead of degraded output.
3. **Stop-hook veto-with-feedback** (Agent Teams `TaskCompleted` exit-2 pattern): our Stop hook already blocks with mailbox contents; extend doctrine — manager can pre-load "definition of done" checks so a worker claiming completion too early gets bounced with feedback.
4. **Session seeding** (ccmanager): `fleet spawn --from <name>` seeds new worker prompt with predecessor's journal — related-task warm start.

Consider at M5:
5. **Plan-approval gate** (Agent Teams): risky task → spawn in `plan` mode, worker submits plan as turn result, manager approves → respawn/send in `accept`. Pure doctrine, zero code.
6. **Trust scoring** (oguzhnatly/fleet): quality×speed rolling record per project/task-type in knowledge base — informs mode/model choice. Prose in lessons.md is v1 version of this.
7. **Broadcast primitive** (NTM/Agent Teams): `fleet send --all` for fleet-wide notices.
8. **GitHub-Issues-as-queue** (code-conductor): for issue-shaped work, agents self-claim labeled issues — alternate task source, avoids bespoke queue bugs.

Rejected: tmux pane scraping/idle detection (our hooks are cleaner), DAG workflow engines (manager session IS the planner), web dashboards (CLI+skill is the point), swarm frameworks (YAGNI).

## Local prior art: exPardus knowledge librarian (added 2026-07-17)

Sibling project on this machine — `C:\proga\exPardus\expardus_knowledge\` (toolkit under `tools/knowledge/`, librarian under `tools/knowledge/librarian/`, design doc at `C:\proga\exPardus\docs\superpowers\specs\2026-06-18-knowledge-librarian-design.md`). A schema-enforced knowledge base with a nightly unattended maintenance loop: deterministic ref-check of each entry's `source:` anchors (ok/moved/missing/doc) → headless-Claude judge (holds/drifted/dead + dup clusters) over a `last_verified`-windowed candidate set → deterministic apply where destruction is corroboration-gated and circuit-breaker-capped. ~600 lines, stdlib+PyYAML, tested.

Adopted into `docs/specs/phase-5-intelligence.md` (fixed-constraints block) and campaign-template v1.5:
- **Evidence-gated destruction** — LLM verdict alone never retires knowledge; needs deterministic ref-miss corroboration (the grep-receipt gate, mechanized).
- **Circuit breaker** — per-run cap `min(abs, fraction×active)` + small-graph flag-only floor + trailing-window destruction ledger; on trip, destructive ops dropped and a visible "halted" note lands in the index.
- **Mass ref-miss = config-error abort** (broken checkout must not read as knowledge drift).
- **Supersede/move, never delete** (convergent with our existing pin doctrine).
- **Randomized fence tokens** around untrusted content in judge prompts (`secrets.token_hex` per run, evaluate-never-obey) — applies to fleet review pipelines embedding worker output today.
- **`last_verified` + `source:` anchor metadata** as the minimum to make staleness mechanically detectable; non-path provenance markers exempt from ref-checking.
- **Judge-empty alerting** (2 consecutive empty runs → alert) for any unattended LLM loop.
- Code idioms: `write_if_changed` with LF-normalization (no git churn), pure `apply_verdicts` core (no I/O) for testability.

Skipped: MAP/ generators (Django/env-var specific), ADR tier (unbuilt there), one-fact-per-file atomization of lessons.md (campaign narratives earn their freeform shape). Their KNOWLEDGE/ content itself was thin (4 notes); only transferable note: OneDrive silently reverts long-running agents' uncommitted edits — moot for `C:\proga` but reinforces git-log-is-truth.

## Source tables

Full agent reports (project tables + URLs) preserved in git history of this file's first commit; key repos: smtg-ai/claude-squad, kbwo/ccmanager, Jedward23/Tmux-Orchestrator, Dicklesworthstone/claude_code_agent_farm + ntm, devflowinc/uzi, stravu/crystal, BloopAI/vibe-kanban, builderz-labs/mission-control, escapeboy/agent-fleet-o, ruvnet/ruflo, SethGammon/Citadel, oguzhnatly/fleet, code.claude.com/docs/en/{agent-view,agent-teams,agents}, factory.ai/news/missions, openhands.dev.
