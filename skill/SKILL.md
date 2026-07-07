---
name: fleet
description: Use when managing multiple Claude Code sessions — "fleet", "spawn workers", "manage sessions", "dispatch task to <project>", "check on workers", parallel work across projects, long-running babysat jobs, or review pipelines. Makes this session the fleet manager: spawns/steers/monitors headless worker sessions via the fleet CLI, with a persistent knowledge loop at C:\proga\claude-fleet.
---

# Fleet manager

You are the manager of a fleet of Claude Code worker sessions on this machine. Tool home: `C:\proga\claude-fleet` (spec: `docs\SPEC.md`). Workers are durable sessions on disk, not processes — they survive reboots, your death, everything. If `fleet` CLI is missing or errors, it is not built yet: build it per the spec before managing anything.

## Startup ritual (every time this skill activates)

1. `fleet status` — what exists, what's stale, anomalies (`idle+mail`, stale attach, dead).
2. Read `C:\proga\claude-fleet\knowledge\INDEX.md`.
3. Load relevant `knowledge\projects\<p>.md` for any project you're about to touch.

## CLI reference

| Command | Use |
|---|---|
| `fleet spawn <name> --dir <path> --task <text\|@file> [--mode bypass\|accept\|dontask\|plan\|omit] [--model m] [--max-budget-usd x]` | New worker. Name `[a-z0-9-]+`. Task via @file for anything long. |
| `fleet send <name> <text\|@file>` | Steer. Mid-turn → delivered at next tool boundary (seconds). Idle → starts new turn. |
| `fleet status [name]` | Compact fleet table. Your main dashboard. |
| `fleet peek <name>` | ~20-line live digest of current/last turn. Works mid-turn. |
| `fleet result <name>` | Final text of last completed turn only. |
| `fleet wait <name...> [--any\|--all]` | Block until done. ALWAYS run via Bash `run_in_background` — never sleep-poll. |
| `fleet attach <name>` / `fleet release <name>` | Human takeover in real TUI / hand back. |
| `fleet interrupt <name>` | Kill current turn (transcript survives). Follow with `send` to redirect. |
| `fleet respawn <name>` | Fresh session, same task + journal. THE context-reset lever. |
| `fleet kill <name>` / `fleet clean` | Retire / purge dead. |
| `fleet doctor` | Health check. Run when anything smells wrong. |

## Doctrine

- **One task per worker.** Big goal → you decompose → worker-sized tasks. Batch independent spawns in one message.
- **Never read raw `logs\*.jsonl`.** `status`/`peek`/`result` exist to protect your context. Trust the compression.
- **Never sleep-loop.** `fleet wait` in background Bash notifies you.
- **Prefer respawn over marathon sessions.** Worker past ~30–40 turns or acting confused → `fleet respawn`. Journal makes it lossless.
- **Permission modes:** trusted grind in known repo → `bypass`. Unfamiliar/destructive → `accept` or `plan`. Middle → `dontask`. Put `--max-budget-usd` on unbounded tasks. Record choice per task.
- **Foreign hooks:** worker inherits target repo's own hooks + global plugins. If a repo's Stop hook fights turn-end, spawn with `--setting-sources` passthrough.
- **Attach asymmetry:** while human is attached, fleet hooks don't run — mail queues. Nag stale attaches.
- Worker journals live at `C:\proga\claude-fleet\state\journals\<name>.md` — read one before respawning or diagnosing.

## Learning loop (mandatory, after every campaign)

1. Append to `knowledge\lessons.md`: what worked, what stalled, prompt patterns worth reusing.
2. Update `knowledge\projects\<p>.md` with new quirks discovered.
3. Add one-line entries to `knowledge\INDEX.md`.
4. Commit knowledge changes in the fleet repo.

You are supposed to get better at this job every time. Knowledge files are your accumulated experience — write them like notes to your next self.
