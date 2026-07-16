---
description: 'Spawn a new fleet worker on a task in a project directory.'
argument-hint: '<name> --dir <path> --task <text|@file> [--mode bypass|accept|dontask|plan|omit] [--token-ceiling n]'
---

Spawn a fleet worker with these arguments: `$ARGUMENTS`

Run `fleet spawn $ARGUMENTS` via Bash.

Before running it:
- If `--mode` is absent, it defaults to `dontask` (auto-deny outside the allowlist). Do not silently substitute `bypass`.
- If the task looks unbounded, say so and suggest `--token-ceiling` (native dispatch has no dollar budget flag — `--max-budget-usd` is refused at spawn).
- If `--dir` does not exist, stop and say so rather than spawning.

After it succeeds, report the worker name, session id, and log path. Do not
immediately peek — the first turn needs time.
