# Project: polymarket_experimenting (pmbot)

Dir: `C:\proga\polymarket_experimenting`. Rust latency-arb trading stack + Python data layer.
Real trunk branch: `feat/skeleton-datalayer` (NOT `main`/`master` — those are stale stubs).

## Spawning workers here — quirks

- **Python is `.venv\Scripts\python` (3.13).** Bare `python` = 3.10. Tell workers explicitly.
- **Rust: run cargo from `rust/`. Use PER-CRATE commands** (`cargo test -p pmbot-hotloop`,
  `cargo clippy -p pmbot-hotloop --all-targets -- -D warnings`). Workspace-wide cargo FAILS on
  a pre-existing `pmbot-core-py` PyO3/py3.10 issue unless `PYO3_PYTHON` is exported first.
  Put "per-crate only, never workspace-wide" in every Rust worker's task file.
- **Kernel `pmbot-core` is FROZEN** — `tests/test_kernel_parity.py` must stay 4/4. Workers must
  not touch decision logic in pmbot-core. Only adapters/feeds/engine-wiring/new crates.
- **Hard rules the repo enforces (CLAUDE.md):** never read `data/collector.db` (stalls the live
  collector); never substitute Binance for Chainlink in resolution. Bake into task files.
- **Cold-build cost:** a fresh worktree has no `target/` → first `cargo build` compiles the whole
  workspace (alloy 1.6 + polymarket_client_sdk_v2 + tokio). Each of 2 parallel worktree workers
  cost ~$1.7 and ran a full cold build. Budget ≥ $6/worker for Rust TDD tasks; it's build-time,
  not tokens.

## Parallel-work pattern that worked (Campaign 2026-07-09)

Plan-3 tasks collide heavily on shared files (`main.rs`, `feeds/mod.rs`, `engine.rs`, `config.rs`).
To run tasks in PARALLEL safely: give each worker its own **git worktree**
(`git worktree add -b <br> ../pmbot-wt-<t> HEAD`), spawn one worker per worktree pointed at
`--dir <worktree>`, then merge branches back. Picked the 2 most file-independent tasks (both
create NEW files) to minimize even the merge overlap. Merged clean (one ff, one 3-way auto-merge
on main.rs). Verified on merged trunk: 86 tests pass, clippy clean.

## Task-file recipe (proven)

Point the worker at the committed plan doc + ONE task number; demand TDD steps verbatim; forbid
edits outside the task's files; add "use your own subagents to read the Python source and
cross-check the port before finalizing" for any Python→Rust port task (both workers' subagents
confirmed byte-for-byte fidelity; independent reviewer agreed — zero findings). Give a one-line
completion contract (`Final message: DONE TaskN — commit <sha>, <n> tests pass`).

## Known deviation that is CORRECT, not scope-creep

Adding an enum variant (`FeedEvent::ChainlinkPrice`) forces a new arm in every exhaustive `match`
— so a "don't touch main.rs" worker MUST add a no-op arm to keep the crate compiling. Expect and
accept this; it is a compile necessity, not the worker going off-task.
