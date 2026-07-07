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

## Source tables

Full agent reports (project tables + URLs) preserved in git history of this file's first commit; key repos: smtg-ai/claude-squad, kbwo/ccmanager, Jedward23/Tmux-Orchestrator, Dicklesworthstone/claude_code_agent_farm + ntm, devflowinc/uzi, stravu/crystal, BloopAI/vibe-kanban, builderz-labs/mission-control, escapeboy/agent-fleet-o, ruvnet/ruflo, SethGammon/Citadel, oguzhnatly/fleet, code.claude.com/docs/en/{agent-view,agent-teams,agents}, factory.ai/news/missions, openhands.dev.
