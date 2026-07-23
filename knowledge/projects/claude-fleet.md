# Project: claude-fleet (the self-build)

Facts learned live while the fleet builds itself. Amended in each campaign's knowledge wave. See `knowledge/playbooks/campaign-template.md` for the campaign instrument **and the live home of PLAN §0 campaign doctrine**; `docs/SPEC.md` (§18 M-track) for the plan of record and design. `docs/PLAN.md` / `docs/ROADMAP.md` were **retired to superseded history (2026-07-24)** — read them for the C1→C8 record, not as a live contract. The "Bootstrap hazard" section below is the live home of the worktree-isolation doctrine.

## Interpreter & CLI invocation
- Python is **`py -3.13`**. Bare `python` resolves to **3.10** — never use it.
- `bin/fleet.py` is **stdlib-only, single file** (~3000 lines). Grep named anchors; never read end-to-end.
- The `fleet` CLI is **NOT on PATH** in the manager's PowerShell. Call it by full path — `C:\proga\claude-fleet\bin\fleet.cmd` — or `py -3.13 bin/fleet.py`.

## Known live bugs
- **`fleet result` / `peek` crashes on the Windows console (cp1252)** when output contains unicode (e.g. the `→` arrow): a stdout-encoding bug in `bin/fleet.py`. Workaround: set `PYTHONIOENCODING=utf-8`. **STILL LIVE after C2** — C2 did NOT fix it (out of scope). Keep the workaround; still a fix candidate for a future worktree task (fleet.py stdout should force utf-8, not inherit the console codepage).
- **Transient Anthropic API 529 (Overloaded) leaves an empty turn:** a worker can die mid-turn to a 529 → goes idle, `cost_usd` stays FROZEN, no commit, journal unchanged, and `fleet result` may itself 529. **`git log` in the worktree is the ONLY reliable "did the turn land" signal** — not `fleet result`/cost. Re-sending a git-committed fix task is safe; revert partial uncommitted artifacts (e.g. dirtied fixtures) before re-send. (C2, 2×.)

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

## C2 facts (self-modification proven — 2026-07-09)
- **The revert path WORKS and was exercised end-to-end:** merge → post-merge gate RED → `git revert -m 1 <merge>` (known-good install restored, stayed live) → worktree fix → re-merge → green. The C2 checkpoint claim **"the fleet can safely modify itself" is EARNED**, not theoretical.
- **Re-merge after a reverted merge:** a plain re-merge is a **no-op** (git sees the branch as already merged). Sequence: `git revert <the-revert>` (restores the reverted code) then `git merge <branch>` (picks up the new fix commit).
- **The `FLEET_LIVE` harness is non-idempotent on the tracked fixture corpus:** it re-captures `tests/fixtures/streams/*.jsonl` every run. Restore with `git checkout -- tests/fixtures/streams/` before any git-state check. (Backlog: gate corpus capture behind `FLEET_CAPTURE_CORPUS=1`, else write to temp.)
- **Hook-source-specific live demo tests must `pytest.skip` (not hard-assert) under the merge-gate default `FLEET_HOOK_SOURCE=main`** — a `assert HOOK_SOURCE == "worktree"` turns the post-merge gate RED (cost C2 a full revert cycle for a one-line scoping bug).

## New CLI surface (C2)
- `fleet resume-limited` — restart workers parked by a usage limit (UL1).
- `--token-ceiling` on `spawn`/`respawn`; new statuses `over_budget` / `over_ceiling` / `limited`; spawn echoes the resolved model.
- **New standing post-merge live checks:** FLEET_LIVE integration tier (default = main hooks); `fleet init` re-render when `worker-settings.template.json` changes (PostCompact hook added in C2); `fleet doctor` now also checks hook-registration, unreadable-starttime, limited-parks, ceiling-file-sweep, hook-errors; live hook-smoke.
