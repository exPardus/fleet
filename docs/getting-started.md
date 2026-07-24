# Getting started

From zero to a running worker in a few minutes. If you haven't yet, skim **[How claude-fleet works](concepts.md)** first — it's five minutes and the rest of this makes more sense with the mental model in place.

---

## Requirements

Fleet runs today on:

- **Windows 10+** with **PowerShell** and **Git Bash** present, **or Linux**
- **Python 3.10+** — the reference box uses `py -3.13`, but the floor is `fleet.MIN_PYTHON_VERSION` and the suite runs green at it
- **Claude Code CLI** `2.1.202+` (pin-tested at `2.1.217`)

Zero third-party dependencies — `bin/fleet.py` is a single stdlib-only file.

> Windows and Linux are both verified by the test suite. macOS runs the same POSIX backend as Linux but has no receipt yet — treat it as untested, not unsupported. Remaining platform gaps are enumerated at the top of [`SPEC.md`](SPEC.md).

## Install

```powershell
# 1. Clone, and add bin\ to your PATH (it holds fleet.cmd)
git clone https://github.com/exPardus/fleet.git
#    add <repo>\bin to PATH

# 2. Render the machine-local hook wiring
#    (fills in this machine's Python path + FLEET_HOME; nothing machine-specific is committed)
fleet init

# 3. Install the plugin — manager skill + /fleet:* slash commands
#    (no hooks: installing fleet does not change how any other session starts)
claude plugin marketplace add <path-or-github-repo-of-this-clone>
claude plugin install fleet@claude-fleet
#    restart Claude Code, then verify:
claude plugin details fleet

# 4. (Optional) install the always-on statusline
#    (a plugin can't ship one, so it installs separately; it refuses to clobber a foreign one)
fleet init --statusline
```

Confirm the wiring is healthy any time:

```powershell
fleet doctor
```

`fleet doctor` runs 22 checks — hook registration, version pins, orphaned mailboxes, stale attaches, the autoclean scheduler, the supervisor claim, and more. A clean run means you're ready.

## Become the manager

Open a Claude Code session and say:

> **become the fleet manager**

That triggers the manager skill: the session reads `knowledge/INDEX.md` and the current fleet state, and from then on drives workers on your behalf. You can also run the `fleet` CLI directly in a shell — the manager session and the CLI operate on the exact same files.

## Spawn your first worker

One task, one worker. That's the doctrine — small, well-scoped tasks, not marathons.

```powershell
fleet spawn hello --dir C:\path\to\some\project `
  --task "List the top-level modules and write a one-paragraph summary to NOTES.md"
```

Watch it:

```powershell
fleet status              # the table: status, turns, cost, age, pending mail
fleet peek hello          # ~20-line digest of the current/last turn (works mid-turn)
fleet wait hello          # block until the turn ends
fleet result hello        # just the final result text
```

### Permission modes

Each worker runs at a trust level you pick at spawn with `--mode`:

| `--mode` | Behavior |
|---|---|
| `dontask` | Middle ground — the default. |
| `accept` | Auto-accept edits. |
| `plan` | Plan mode; proposes, doesn't execute. |
| `bypass` | `--dangerously-skip-permissions` — full autonomy. Use when you trust the task. |
| `omit` | Pass no permission flag; inherit whatever the session default is. |

```powershell
fleet spawn migrate --dir C:\proga\billing --mode bypass `
  --task "@C:\proga\billing\TASK.md" --token-ceiling 200000
```

`--task` accepts inline text or `@file` to read a task file. `--token-ceiling` caps total tokens — a worker that would exceed it refuses the next turn rather than burning through your budget unwatched.

## Steer, mid-flight

You don't have to wait for a worker to finish to change its course:

```powershell
fleet send migrate "also add a down-migration, I forgot to ask"
```

- If the worker is **working**, the message lands in its mailbox and is injected at the next tool boundary — no attach needed.
- If it's **idle**, the same command resumes it on a fresh turn with your message as the input.

Need the full interactive experience? A worker is a real Claude Code session, so you attach to it **through Claude Code**, not through fleet:

```powershell
# Ctrl+T in claude opens the agents menu, or address the session directly:
claude attach <session-id>        # fleet status --json shows the session_id

fleet release migrate             # flip a stale `attached` record back to idle
```

> `fleet attach` currently **refuses and redirects** to the above — a `--bg` worker has no fleet-owned terminal to spawn. Native attach integration is a later milestone (`SPEC.md` §7).

## Reset context without losing the work

Long campaigns fill a worker's context. Respawn gives it a **fresh session** — same name, cwd, and mode — while carrying its **journal** and any drained mailbox forward:

```powershell
fleet respawn migrate                    # fresh context, work history preserved
fleet respawn migrate --task "@NEW.md"   # …and re-scope the task
```

## When a worker hits a usage limit

It parks itself as `limited` with the reset time recorded — it does not die silently. Once the window passes:

```powershell
fleet resume-limited            # resume every parked worker whose reset horizon has passed
fleet resume-limited migrate    # …or just one
```

## Clean up

```powershell
fleet kill hello                # stop the turn (if running) and mark it dead
fleet clean --dead-only         # remove dead workers + their outcomes/mailboxes/journals
fleet clean                     # broader sweep (see fleet clean --help for tiers)
```

`fleet archive` and the scheduled `fleet autoclean` handle staleness automatically so you rarely have to remember to tidy up. Install the scheduler with `fleet init --autoclean`.

## A first real campaign: parallel workers

The point of fleet is *many* workers. Fan out independent tasks, then collect:

```powershell
fleet spawn lint-api    --dir C:\proga\api      --mode accept --task "@tasks\lint.md"
fleet spawn lint-web    --dir C:\proga\web      --mode accept --task "@tasks\lint.md"
fleet spawn lint-worker --dir C:\proga\jobs     --mode accept --task "@tasks\lint.md"

fleet wait lint-api lint-web lint-worker --all    # block until all three finish
fleet status                                       # review outcomes
fleet result lint-api                              # read each result
```

For dependent or review-style work (one worker builds, another attacks the diff), let the manager session orchestrate — it's what the manager skill and the `knowledge/playbooks/` doctrine are for. See [`../knowledge/playbooks/`](../knowledge/playbooks/) for the campaign template and spawn etiquette.

## The full command surface

| Command | Purpose |
|---|---|
| `fleet init` | Render machine-local `worker-settings.json` (add `--statusline`, `--autoclean`) |
| `fleet spawn` | Spawn a new worker session |
| `fleet status` | Worker status table |
| `fleet peek` | Digest of the last few substantive transcript records (works mid-turn) |
| `fleet result` | Final result text of the last completed turn |
| `fleet wait` | Block until turn(s) end |
| `fleet send` | Steer a worker (mailbox mid-turn, or a new turn if idle) |
| `fleet interrupt` | Stop a worker's running turn |
| `fleet attach` / `release` | `attach` refuses and points at `claude attach` / the agents menu; `release` returns a stale `attached` record to idle |
| `fleet respawn` | Fresh session, journal carried forward |
| `fleet resume-limited` | Relaunch usage-limit-parked workers past their reset |
| `fleet kill` | Interrupt (if running) and mark dead |
| `fleet clean` / `archive` / `autoclean` | Tiered cleanup and staleness sweeps |
| `fleet doctor` | Run the 23 health checks |
| `fleet sup-*` | Supervisor identity: boot, heartbeat, checkpoint, status, handoff |

Every command's exact contract lives in [`SPEC.md`](SPEC.md) §7.

---

## Next

- **[How claude-fleet works](concepts.md)** — the architecture and design bets, with diagrams.
- **[SPEC.md](SPEC.md)** — the binding architecture of record.
- **[Docs index](README.md)** — every doc, tagged by audience.
