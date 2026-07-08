# Project: claude-fleet (the self-build)

Facts learned live while the fleet builds itself. Amended in each campaign's knowledge wave. See `knowledge/playbooks/campaign-template.md` for the campaign instrument; `docs/PLAN.md` for the contract; `docs/SPEC.md` for the design.

## Interpreter & CLI invocation
- Python is **`py -3.13`**. Bare `python` resolves to **3.10** — never use it.
- `bin/fleet.py` is **stdlib-only, single file** (~3000 lines). Grep named anchors; never read end-to-end.
- The `fleet` CLI is **NOT on PATH** in the manager's PowerShell. Call it by full path — `C:\proga\claude-fleet\bin\fleet.cmd` — or `py -3.13 bin/fleet.py`.

## Known live bugs
- **`fleet result` crashes on the Windows console (cp1252)** when output contains unicode (e.g. the `→` arrow): a stdout-encoding bug in `bin/fleet.py`. Workaround: set `PYTHONIOENCODING=utf-8`. Real fix candidate for a **C2 worktree** task (fleet.py stdout should force utf-8, not inherit the console codepage).

## Bootstrap hazard (the reason for worktrees)
- The manager and all workers execute via the **live** install at `C:\proga\claude-fleet` (registry + hooks resolved through `state/worker-settings.json`).
- **Code-touching workers NEVER run in `C:\proga\claude-fleet`.** One git worktree per code campaign (`C:\proga\claude-fleet-wt\<campaign>`); worktree edits to `bin/fleet.py`/`bin/hooks/*` cannot hot-swap the live CLI/hooks — this is the version-pin.
- **At most ONE `bin/fleet.py` writer alive fleet-wide** at any moment, across all campaigns. Same-file work must serialize; `tests/*`, `bin/hooks/*`, `docs/*` are separate write sets.
- Doc/spec-only workers **may** run in the main repo on strictly disjoint files.

## Parallelism facts (proven live)
- **Disjoint-file parallelism is safe** — proven to **7-wide** with exact-path staging + index.lock retry (Campaign-0/1).
- **Same-file parallelism is not** — serialize all `bin/fleet.py` work into a chain with the per-link truth gate.

## SPEC v2.1 landmarks
- Numbered **9-invariant section** (added by C1 `spec-amend-3-testing`; ROADMAP + stubs cite it by number).
- Appendix **F1–F16 are SETTLED** — never relitigate them. **F17–F32 are the v2.1 amendments** (incl. UL1 usage-limit resilience, UL2 worker-subagents).
- **Prescriptive amendments tagged `[UNBUILT — owned by <kernel>]`** — spec text describing behavior a later code kernel must build, not behavior true of the code today. Do not demand green tests for `[UNBUILT]` items.

## Operational facts
- `fleet doctor` **`wt`-absent is a known-fine fallback** (detached PowerShell attach) — not a failure.
- **`dead` is sticky** (operator kill survives recompute); `respawn` is the only recovery lever.
- **Respawn re-executes a completed task** — the journal carries context, not idempotence. Respawn is for stuck/long-context workers, not to preserve a finished worker's state.
- Cost per worker = `cost_baseline` (respawn carry) + sum of the current log's result events. `cost_usd` reflects only *completed* turns — a runaway resume turn shows $0 until it ends.
- `--max-budget-usd` **overshoots ~3×** on tiny caps — circuit breaker, not a precise ceiling.
- **Stop-block race is real:** a `send` in a turn's last seconds queues to the mailbox (idle+mail) instead of same-turn delivery — by design (universal drain rule). Check `idle+mail` in status; don't assume same-turn.
