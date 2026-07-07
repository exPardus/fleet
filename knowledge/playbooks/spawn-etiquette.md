# Spawn etiquette

Doctrine for spawning and running workers. Distilled from SPEC §10; see there for full context.

- **One task per worker.** Decompose a big goal into worker-sized tasks yourself before spawning — don't hand one worker an open-ended, multi-part goal.
- **Batch independent spawns.** When several tasks share no state, spawn them all in a single message rather than one at a time.
- **Prefer respawn over marathon sessions.** Respawn a worker past roughly 30-40 turns or when it acts confused (SKILL.md doctrine); never let a session approach 100 turns (SPEC §10). The journal makes the reset lossless.
- **Wait in background, never sleep-loop.** Run `fleet wait <name...>` via Bash `run_in_background` and let the notification wake you; never poll with a sleep loop.
- **Permission-mode doctrine.** Trusted grind in a known repo → `bypass`. Unfamiliar or destructive work → `accept` or `plan`. Middle ground → `dontask`. Record which mode you chose and why.
- **Budget caps.** Put `--max-budget-usd` on any unbounded or open-ended task.
