---
name: 'fleet'
description: 'Use when managing multiple Claude Code sessions — "fleet", "spawn workers", "manage sessions", "dispatch task to <project>", "check on workers", parallel work across projects, long-running babysat jobs, or review pipelines. Makes this session the fleet manager: spawns/steers/monitors headless worker sessions via the fleet CLI, with a persistent knowledge loop at C:\proga\claude-fleet.'
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
| `fleet init` | Render the machine-local `state\worker-settings.json` from the git-tracked template (real interpreter path + FLEET_HOME). Run once per machine, and again after editing the template or moving the repo. `spawn`/`send` refuse with a clear error if this hasn't been run. |
| `fleet spawn <name> --dir <path> --task <text\|@file> [--mode bypass\|accept\|dontask\|plan\|omit] [--model m] [--max-budget-usd x] [--setting-sources <list>]` | New worker. Name `[a-z0-9-]+`. Task via @file for anything long. `--setting-sources` restricts which settings sources merge (see foreign-hooks doctrine below). |
| `fleet send <name> <text\|@file>` | Steer. Mid-turn → delivered at next tool boundary (seconds). Idle → starts new turn. |
| `fleet status [name]` | Compact fleet table. Your main dashboard. |
| `fleet peek <name>` | ~20-line live digest of current/last turn. Works mid-turn. |
| `fleet result <name>` | Final text of last completed turn only. |
| `fleet wait <name...> [--any\|--all]` | Block until done. ALWAYS run via Bash `run_in_background` — never sleep-poll. |
| `fleet attach <name>` / `fleet release <name>` | Human takeover in real TUI / hand back. |
| `fleet interrupt <name>` | Kill current turn (transcript survives). Follow with `send` to redirect. |
| `fleet respawn <name> [--task <text>] [--force]` | Fresh session_id, same name/cwd/mode/model + journal + drained mailbox. THE context-reset lever. Refuses while a turn is running unless `--force` (interrupts first). `--task` overrides the original task text. |
| `fleet kill <name>` | Interrupt (if running) and mark dead + event. Terminal — use `respawn` to bring the worker back. |
| `fleet clean` | Remove dead workers + their logs/mailboxes/journals; prints what was removed. |
| `fleet doctor` | Health check (claude/version, hook wiring + smoke test, stale PIDs/attaches, orphaned mailboxes, log sizes, ...). Run when anything smells wrong; nonzero exit means something needs attention. |

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
