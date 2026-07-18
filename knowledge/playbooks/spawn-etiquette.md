# Spawn etiquette

Doctrine for spawning and running workers. Distilled from SPEC §10; see there for full context.

- **One task per worker.** Decompose a big goal into worker-sized tasks yourself before spawning — don't hand one worker an open-ended, multi-part goal.
- **Batch independent spawns.** When several tasks share no state, spawn them all in a single message rather than one at a time.
- **Prefer respawn over marathon sessions.** Respawn a worker past roughly 30-40 turns or when it acts confused (SKILL.md doctrine); never let a session approach 100 turns (SPEC §10). The journal makes the reset lossless.
- **Wait in background, never sleep-loop.** Run `fleet wait <name...>` via Bash `run_in_background` and let the notification wake you; never poll with a sleep loop.
- **Permission-mode doctrine.** Trusted grind in a known repo → `bypass`. Unfamiliar or destructive work → `accept` or `plan`. Middle ground → `dontask`. Record which mode you chose and why.
- **Budget caps.** Native dispatch carries no dollar figure — `--max-budget-usd` is **refused at spawn** (SPEC v3 G3); put `--token-ceiling` on any unbounded or open-ended task instead. Same circuit-breaker semantics as the old USD cap: enforced at turn boundaries (Stop hook + pre-steer check), not mid-stream — it bounds a runaway worker, it is not a precise ceiling. At/over ceiling the worker goes sticky `over_ceiling` and refuses `send`; recover via `respawn --task @file`.
- **Token-efficiency contract (operator ask 2026-07-16, mandatory in every task brief).** Tier-boundary messages are compressed; artifacts carry the substance. Every task file ends with a `RESULT:` line contract plus "final message terse — the artifact/commits carry the substance." Steers you send are equally terse: no restated task, no narration, pointers over pastes. **Full-precision zones, never compressed:** code, commit messages, specs, review verdict files, quoted error text. The clause lives in the task file, not in a plugin — a plugin the worker repo doesn't have installed is a silent no-op; a task-file clause always arrives.
