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
3. Install the plugin — it carries the manager skill, the `/fleet:*` slash commands, and the SessionStart briefing:

   ```bash
   claude plugin marketplace add <path-or-github-repo-of-this-clone>
   claude plugin install fleet@claude-fleet
   ```

   Then restart Claude Code. Verify with `claude plugin details fleet`.

   > `claude --plugin-dir <path>` loads the commands for one session but **does not register the plugin's SessionStart hook** (verified 2026-07-09, claude 2.1.204) — the briefing never fires. Use a real install, not `--plugin-dir`, when you care about the hook.

4. Optional — install the fleet statusline into `~/.claude/settings.json`:

   ```powershell
   fleet init --statusline
   ```

   It is a separate step because a Claude Code plugin cannot ship a `statusLine`. The command backs up your settings first and refuses to overwrite a statusline it does not own.

   Already running another statusline (`ccusage`, `caveman`, …)? Claude Code allows only one, so compose them:

   ```powershell
   fleet init --statusline --chain
   ```

   Your existing statusline keeps its row; fleet's prints beneath it. A delegate that fails or hangs is dropped — fleet's row always renders. Use `--force` instead to replace the incumbent outright.

## Installing for collaborators

`fleet` is a *system-wide tool with machine-local state*, so installing the plugin is not the whole install. Each person needs:

1. **A clone of this repo**, with `bin/` on `PATH` (Windows uses `bin\fleet.cmd`).
2. **`fleet init` run once** — this renders `state/worker-settings.json` *and* stamps `~/.claude/fleet-home` with the absolute path of their fleet.
3. **The plugin installed** (step 3 above).

Step 2 is load-bearing and easy to miss. A marketplace-installed plugin runs from a **cache copy** of this repo, whose `state/` is gitignored and therefore empty. Without the `~/.claude/fleet-home` marker, the SessionStart hook would read that empty cache and cheerfully report a fleet of zero workers while the real one is running. The marker is how the hook finds the fleet the `fleet` CLI actually writes. `$FLEET_HOME` overrides it.

Requirements: Python ≥ 3.10 on `PATH` (the hook finds it via `bin/hooks/run_py.sh`, which tries `py -3.13`, then `python3.x`, then `python`; set `$FLEET_PYTHON` to force one), Claude Code ≥ 2.1.202, and `git`.

Not yet portable: worker launch, kill, attach and PID liveness are Windows-only until Phase 1.5 (`docs/specs/portability.md`). The plugin surface itself — commands, statusline, briefing — is not.

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
skills/fleet/SKILL.md          # manager skill (shipped by the plugin)
commands/                      # /fleet:* slash commands (shipped by the plugin)
.claude-plugin/                # plugin + marketplace manifests
knowledge/                     # git-tracked: playbooks, per-project notes, lessons
docs/                          # SPEC, plan, roadmap, phase specs, reviews
tests/                         # pytest unit/hook tests
state/  logs/  mailbox/        # runtime, gitignored
```

## License

[MIT](LICENSE) © exPardus
