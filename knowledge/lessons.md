# Lessons

Append-only postmortems. One entry per campaign: what worked, what stalled, prompt patterns worth reusing. Never edit or delete a past entry — add new ones below.

<!-- Add new entries below this line -->

## 2026-07-07 — Campaign 0: building fleet itself (subagent-driven, 30+ agents)

The fleet CLI was built by a multi-agent pipeline (implementer → spec reviewer + adversarial reviewer in parallel → supervisor-adjudicator → fixer → re-review, per task). Lessons that transfer to running fleet campaigns:

**What worked**
- Adversarial reviewers with repro authority found what spec reviewers approved: 4 of 5 tasks got "Approved" from the spec lens while the adversarial lens returned proven BREAKS (lock races, path traversal, stdin pipe deadlock, silent hook death on spaced paths). Always run both lenses on anything that manages processes or files.
- Live smoke beats unit tests for stream-json assumptions: 340 green unit tests coexisted with three High/Medium bugs only a real haiku worker exposed (hook events land AFTER the result line; kill-dead resurrected by recompute; cost is per-invocation on --resume). Budget ~$0.10 of haiku time at the end of any campaign that touches worker plumbing.
- Supervisor-adjudicator agents (read both reviews, emit ONE binding fix list with exact semantics) kept fixers from re-interpreting findings. Fix lists anchored to function roles, not line numbers, survived concurrent refactors.
- Disjoint-file parallelism is safe (hooks + docs + core in parallel, exact-path staging, index.lock retry); same-file parallelism is not — sequence all bin/fleet.py work.

**What stalled**
- Same-file fix waves queued behind implementers repeatedly; the file-ownership handoff was the pipeline's bottleneck.
- One fixer died mid-run on an API error AFTER committing — always `git log` before re-dispatching "failed" work.
- Every fix wave introduced ~1 new issue (lock-hold sleep, unconditional re-claim); re-review after EVERY wave, no matter how small.

**Fleet-specific operational facts learned live**
- The Stop-block race is real: a `send` landing in the last seconds of a turn queues to the mailbox instead of same-turn delivery — this is by design (universal drain rule); check `idle+mail` in status, don't assume same-turn.
- `dead` is sticky (operator kill survives recompute); `respawn` is the only recovery lever. Pre-fix records persisted as idle may need a re-kill.
- Cost per worker = cost_baseline (respawn carry) + sum of result events in the current log.

**Rigorous-testing addendum (same campaign)**
- Multi-process stress found what thread-based unit tests could not: the spawn commit-lock timeout zombie only appears under real OS-process contention with real PowerShell probe latency. Any future concurrency change to fleet.py should re-run the stress harness (kept at the session scratchpad's `stress/`; the fake-claude stub must be a compiled .exe — a .cmd stub hangs under launch_turn's pipe shape).
- Fuzzing paid off at the parser layer, not the hooks: hooks survived 1000 hostile inputs untouched; the registry/cost parsers crashed on shape mismatches. Fuzz the parsers of any new event/registry field.
- `--max-budget-usd` overshoots ~3x on tiny caps — circuit breaker, not a ceiling.
- Stop-block mid-turn continuation PROVEN live: time a send after the last tool call, before Stop fires.

## 2026-07-08 — Campaign 1: haiku demo (3 workers, full lifecycle showcase)

First real end-to-end run on the finished CLI. Spawn → status → peek → mid-turn send → background wait → result → respawn → doctor → kill/clean, all green, total spend ~$0.21 haiku.

**What worked**
- Batched 3 spawns in one message; all landed in ~seconds, no lock contention.
- Mid-turn steering delivered and OBEYED: `send` to a working haiku poet ("make third haiku about the manager") queued to mailbox, consumed at next tool boundary, worker revised exactly the targeted item and confirmed in its final message. Steering prompt pattern worth reusing: prefix "Steering update from manager:" + one concrete, verifiable change.
- Task prompts ending in "Final message = X" made `result` output clean and directly consumable — haiku workers follow output-contract phrasing well.
- `fleet doctor` 13/13 PASS on first real campaign; `wt` absent is a known-fine fallback (detached PowerShell attach).

**What to know**
- `fleet` is NOT on PATH in the manager's PowerShell — call `C:\proga\claude-fleet\bin\fleet.cmd` by full path (or add bin to PATH).
- Respawn on an already-DONE task re-executes it rather than no-op'ing: respawned poet read its journal but rewrote poems.txt from scratch, losing the steered revision. Journal carries context, not idempotence — don't respawn a completed worker expecting state preservation; respawn is for stuck/long-context workers only.
- Haiku workers at these task sizes finish in under a minute — `status` right after arming `wait` often already shows idle; results can be harvested before the wait notification lands.
