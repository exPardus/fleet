# claude-fleet

One Claude Code **manager** session that spawns, monitors, steers, and hands off multiple **worker** Claude Code sessions across arbitrary projects on a single machine.

The manager is "another you": parallel fan-out, long-running babysitting, cross-project routing, and review pipelines — driven from a single stdlib-only Python CLI, with a persistent, git-tracked knowledge base that grows over time.

> **Status:** design-complete (SPEC v2.1, post adversarial review) and implementing milestone by milestone. See [`docs/SPEC.md`](docs/SPEC.md).

## Why

CLI-native background agents cover spawn + list + monitor, but not a named registry with per-task permission modes, mid-turn mailbox steering, journals + respawn continuity, attach/headless conflict guards, or a shared knowledge loop. `claude-fleet` adds exactly that layer.

## Core design

- **Sessions, not processes.** A worker is a durable Claude Code *session* on disk (`--session-id` / `--resume`); each turn is a short-lived `claude -p` process. Crash-safe by construction.
- **Daemonless.** No resident supervisor. Every action is a short-lived CLI invocation.
- **Single-writer registry.** Only `fleet.py` writes `state/fleet.json`, guarded by a lock file.
- **One live claude per session.** Attach/headless guards prevent two live processes on one session.
- **cwd-scoped resume.** A worker resumes only in its recorded, immutable working directory.
- **Steering via mailbox.** Append-only `mailbox/<sid>.md`, claimed atomically via `os.replace`, injected at tool boundaries.
- **Knowledge loop.** `knowledge/` is git-tracked — playbooks, per-project quirks, and append-only lessons that improve the fleet across sessions.

The nine load-bearing architectural invariants are enumerated in [`docs/SPEC.md`](docs/SPEC.md).

## Requirements

- Windows 10 + PowerShell + Git Bash
- Python 3.13 via `py -3.13` (the CLI is single-file, stdlib-only)
- Claude Code CLI ≥ 2.1.202

## Install

1. Add `bin\` to your `PATH` (contains `fleet.cmd`, the CLI shim).
2. Run `fleet init` once — renders the machine-local `state\worker-settings.json` (hook wiring: real interpreter path + `FLEET_HOME`, forward slashes) from the git-tracked `worker-settings.template.json`. Re-run after editing the template or moving the repo; idempotent.
3. Copy `skill\SKILL.md` to `%USERPROFILE%\.claude\skills\fleet\SKILL.md`.

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
| `fleet kill` | Interrupt (if running) and mark a worker dead |
| `fleet clean` | Remove dead workers and their logs/mailboxes/journals |
| `fleet doctor` | Run fleet health checks |

## Repo layout

```
bin/                           # single-file CLI (fleet.py), shim, hooks
worker-settings.template.json  # hook-wiring template; `fleet init` renders it
skill/SKILL.md                 # manager skill, installed into ~/.claude/skills/fleet/
knowledge/                     # git-tracked: playbooks, per-project notes, lessons
docs/                          # SPEC, plan, roadmap, phase specs, reviews
tests/                         # pytest unit/hook tests
state/  logs/  mailbox/        # runtime, gitignored
```

## License

[MIT](LICENSE) © exPardus
