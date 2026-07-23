# Project: polymarket_experimenting (pmbot)

Dir: `C:\proga\polymarket_experimenting`. Rust latency-arb trading stack + Python data layer.
**Trunk CORRECTED 2026-07-23 (council audit, per `docs/HANDOVER.md` git/ops §, updated 2026-07-18): `origin/master` is the single source of truth.** The old `feat/skeleton-datalayer` guidance was ruled "wrong and actively harmful" by the repo's own HANDOVER. Read HANDOVER.md's READ-FIRST banner before every campaign here — it also carries an ordered "Open items, buildable now" backlog.

## Overnight/unattended hazards (2026-07-23 council audit — pmbot was VETOED for unattended work)
- **Token files sit in the repo root** (`pmbot-setup-token.txt`, `swap-lab-agent-token.ps1`, `SWAP-TOKEN.cmd`) — a bypass-mode worker can cat one into a log/commit.
- **The origin remote is shared with a LIVE VPS agent** that mints real Telegram-approved fence tokens and pushes `agent/*` branches (~40). Never push overnight; branch collisions hit an autonomous production system.
- **`C:\proga\pmbot-kalshi-research` is a twin clone of the SAME remote** running a pre-registered study; its `data/` is an unbackfillable OOS tape and its collector can respawn anytime. Workers in either clone can clobber the other via the shared remote.
- Untracked `docs/superpowers/specs/2026-07-21-trading-core-redesign-DRAFT.md` carries unresolved operator `[FIGHT]` decisions — building against it is redo-work; fence it in task files.
- Deploys are gated (`master → push → receive-bundle → agent-build → agent-install`, Telegram fence tokens) — local branch commits deploy nothing, but see push hazard above.

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
