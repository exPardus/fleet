# claude-fleet

![tests](https://img.shields.io/badge/tests-720%20passing-brightgreen) ![python](https://img.shields.io/badge/python-3.13%20stdlib--only-blue) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

One Claude Code session — the **manager** — that spawns, monitors, steers, and hands off many headless Claude Code **worker** sessions across different projects on one machine. Workers are durable sessions on disk, not fire-and-forget processes: they survive crashes, reboots, and the manager's own death, and you can drop into any of them for an interactive hand-off at any time. It's a stdlib-only Python CLI plus a handful of hooks, built so a solo operator can run days-long, multi-project campaigns without babysitting a terminal.

## Why

Claude Code's own background agents (`claude --bg`, `claude agents`) cover spawn, list, and monitor. They do not cover a named registry with per-task permission modes, mid-turn mailbox steering, journals with respawn continuity, attach/headless conflict guards, budget and token ceilings, or a knowledge base that gets smarter across sessions. `claude-fleet` is exactly that layer — currently sitting on top of its own detached-launch machinery, and mid-pivot onto the native substrate (see [Status](#status) below).

## See it in action

```
$ fleet spawn migrate-users --dir C:\proga\billing-service --mode bypass \
    --task "Port the users table migration from Knex to raw SQL, see MIGRATION.md" \
    --token-ceiling 200000
migrate-users a1b2c3d4-... (native bg, short id a1b2c3d4)

$ fleet status
NAME                STATUS       TURNS     COST      AGE  MAIL  FLAGS
migrate-users        working         1      0.00       2m     0  -

$ fleet send migrate-users "also add a down-migration, I forgot to ask"
migrate-users: turn running -- message queued to mailbox

$ fleet peek migrate-users
[tool] Read MIGRATION.md
[tool] Write migrations/0042_users.sql
[mail] delivered: "also add a down-migration, I forgot to ask"
[tool] Write migrations/0042_users.down.sql
[assistant] Added the down-migration and re-ran the local suite; both pass.

$ fleet wait migrate-users
migrate-users: idle (turn ended)

$ fleet result migrate-users
Migrated 0042_users to raw SQL with a matching down-migration. Ran
`npm test -- migrations` locally: 14 passed. Diff is 2 files, no schema drift.
```

One task, one worker, one budget cap, mid-turn steering delivered without ever attaching a terminal. `fleet doctor` (18 health checks), `fleet attach`/`fleet release` for a full interactive hand-off, and `fleet respawn` to reset a worker's context while carrying its journal forward round out the loop — see the [CLI reference](#cli) below.

## Architecture

```
                    ┌──────────────────────────┐
                    │   manager session         │
                    │   (you, or another        │  reads/writes
                    │   Claude Code session)     │◄──────────────┐
                    └────────────┬──────────────┘                │
                                 │ fleet CLI                      │
                                 ▼                                │
                    ┌──────────────────────────┐                 │
                    │  state/fleet.json          │  single writer:
                    │  registry (single-writer,  │  bin/fleet.py only
                    │  lock-guarded)              │                 │
                    └────────────┬──────────────┘                 │
                 ┌───────────────┼───────────────┐                │
                 ▼               ▼               ▼                │
           ┌──────────┐   ┌──────────┐    ┌──────────┐            │
           │ worker A │   │ worker B │    │ worker C │  each a    │
           │ claude -p│   │ claude -p│    │ claude -p│  durable   │
           │ session  │   │ session  │    │ session  │  session,  │
           └────┬─────┘   └────┬─────┘    └────┬─────┘  short-lived
                │              │               │        turns
        PostToolUse/Stop hooks (mailbox drain, journal write, budget check)
                │              │               │
                ▼              ▼               ▼
        mailbox/*.md    logs/*.jsonl    state/journals/*.md
                │                               │
                └───────────────┬───────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │  knowledge/ (git-tracked)  │  playbooks, per-project
                    │  INDEX · lessons · projects │  quirks, append-only
                    └──────────────────────────┘  lessons — read by every
                                                    manager session at start
```

No daemon in the core loop: every `fleet` command is a short-lived CLI invocation, and the registry is the single source of truth every view (`status`, `peek`, the statusline, `/fleet:*` slash commands) derives from — never independent state.

## Features (shipped, not aspirational)

- **Mid-turn steering.** `fleet send` delivers a message into a running worker's mailbox; it's injected at the next tool boundary, no attach required.
- **Token caps.** `--token-ceiling` is enforced fleet-side before every resume turn — a worker that would blow its cap refuses to continue. (Native `--bg` dispatch carries no cost field at all — `--max-budget-usd` is refused at spawn; USD caps only ever applied to the pre-pivot legacy launch path.)
- **Respawn with journal continuity.** `fleet respawn` gives a worker a fresh session (new context, same name/cwd/mode) while carrying its journal and any drained mailbox forward — the context-reset lever for long campaigns.
- **Usage-limit park/resume.** A worker that hits a Claude plan usage limit parks itself (`limited` status, recorded reset horizon) instead of dying silently; `fleet resume-limited` relaunches it once the window passes.
- **Knowledge loop.** `knowledge/` is git-tracked: an index, playbooks, per-project quirks, and append-only lessons that every manager session reads at startup and writes back to after every campaign.
- **`fleet doctor`.** 18 health checks in one command — hook wiring, stale PIDs, orphaned mailboxes, stale attaches, log sizes, elevation mismatches, and more.
- **Statusline + `/fleet:*` slash commands + SessionStart briefing.** Fleet state is visible without typing a command, shipped as a normal Claude Code plugin (see [Install](#install)).
- **Attach/release for real interactive hand-off.** `fleet attach` opens a worker's actual session in its own terminal; `fleet release` hands it back to headless operation.
- **cwd-scoped, crash-safe sessions.** A worker is a durable Claude Code session addressed by `--session-id`/`--resume`, not a process fleet has to keep alive.

## Status

**Native dispatch shipped end-to-end, pin-verified.** M-0 (native-substrate spike) through M-B (native dispatch: registry v2, outcome capture/discriminator, usage-limit continuity, `claude stop`/tombstone teardown, doctor pin-gate) are complete — fleet hands process hosting and liveness to Claude Code's native background-agent daemon (`claude --bg`, the agents menu) and keeps the semantic layer (mailbox steering, budgets, journals, the knowledge loop) on top. Live pin suite: `FLEET_LIVE=1 pytest tests/integration/test_native_pin.py` — 6/6 green, three consecutive runs, at commit `76eca87`. Design: [`docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md`](docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md); contract: [`docs/specs/native-substrate.md`](docs/specs/native-substrate.md).

**In progress: M-C — deletion + SPEC v3.** Retiring the now-superseded detached-launch/PID-probe machinery (bannered, not deleted, in [`docs/SPEC.md`](docs/SPEC.md) and [`docs/specs/portability.md`](docs/specs/portability.md)) and rewriting SPEC.md against the native substrate, gated on a soak campaign of real usage before it lands. `docs/SPEC.md` remains the spec of record for the architecture, its invariants, and the full command surface until that rewrite ships.

## Quickstart

**Requirements today:** Windows 10+, PowerShell, Git Bash, Python via `py -3.13`, Claude Code CLI ≥ 2.1.202. Portability to Linux/macOS is specced and `ready-for-build` ([`docs/specs/portability.md`](docs/specs/portability.md)) — not yet shipped.

```powershell
# 1. Clone, add bin\ to PATH
git clone https://github.com/exPardus/fleet.git
# add <repo>\bin to PATH (contains fleet.cmd)

# 2. Render machine-local hook wiring
fleet init

# 3. Install the plugin (manager skill, /fleet:* commands, SessionStart briefing)
claude plugin marketplace add <path-or-github-repo-of-this-clone>
claude plugin install fleet@claude-fleet
# restart Claude Code, verify with: claude plugin details fleet

# 4. Optional: the always-on statusline (can't ship inside a plugin)
fleet init --statusline
```

Full install detail, including the collaborator/multi-machine setup and the `--statusline --chain` composition flag, lives in the [CLI reference](#cli) section below and in [`docs/SPEC.md`](docs/SPEC.md).

## CLI

| Command | Purpose |
|---|---|
| `fleet init` | Render machine-local `worker-settings.json` from the template |
| `fleet spawn` | Spawn a new worker session |
| `fleet status` | Show the worker status table |
| `fleet peek` | Digest of recent stream events |
| `fleet result` | Final result text of the last completed turn |
| `fleet wait` | Block until turn(s) end |
| `fleet send` | Send a message to a worker (mailbox or resume) |
| `fleet interrupt` | Kill a worker's running turn |
| `fleet attach` | Attach an interactive terminal to a worker |
| `fleet release` | Release an attached worker back to idle |
| `fleet respawn` | Fresh session for a worker (context-reset lever) |
| `fleet resume-limited` | Relaunch workers parked on a usage limit past their reset horizon |
| `fleet kill` | Interrupt (if running) and mark a worker dead |
| `fleet clean` | Remove dead workers and their logs/mailboxes/journals |
| `fleet doctor` | Run fleet health checks |

## Roadmap

Shipped: core lifecycle (spawn/steer/attach/respawn/knowledge), the terminal surface (statusline, slash commands, plugin package). Specced and ready-for-build: cross-platform portability. Ahead: watchtower (continuous monitoring, no daemon required until then), a Telegram bridge, a local web UI, and a "trust ledger" intelligence layer — plus the native-substrate pivot described in [Status](#status) above. Full detail, sequencing, and the soak-gate discipline that gates each phase: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Docs

[`docs/README.md`](docs/README.md) indexes every doc in this repo with an audience tag — what's for using the tool, what's for contributing to it, and what's fleet's own internal working record (design reviews, campaign plans, accumulated knowledge). Start there if you're not sure where to look.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE) © exPardus
