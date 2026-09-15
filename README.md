# fleet

**Another developer on your team, made of Claude Code and Codex sessions.**

Give fleet an idea, a bug, or a product and it works the way a good developer
does: understands the intent, proposes a shape, splits the work, builds, tests,
reviews, lands, and keeps going for days without supervision. It survives
context limits, crashes, reboots and plan limits, and it reports honestly.

Fleet is not a coding assistant. A plain Claude Code session is that. It is
what runs after you close the laptop.

- **[product.md](product.md)** — the one-page product definition. Binding.
- **[skills/fleet/SKILL.md](skills/fleet/SKILL.md)** — the operating manual: every tier, every verb, every rule.
- **[docs/getting-started.md](docs/getting-started.md)** — install and first run.
- **[docs/concepts.md](docs/concepts.md)** — how it works underneath.
- **[docs/CHANGELOG.md](docs/CHANGELOG.md)** — one line per user-visible change.

## How it works

Three tiers, one machine, any number of repositories.

| Tier | What it is | What it does |
|---|---|---|
| **Interface** | your own Claude Code session, in any repo | turns your intent into a brief, holds the vision, rules on the irreversible |
| **Supervisor** | a Claude session fleet spawns and hands off at its context band | splits a job into departments, dispatches, reviews, lands, closes waves |
| **Workers** | Claude Code sessions or Codex lanes, on their own branches | own an area of the work; long jobs get long-lived workers with subagents |

Everything mechanical is a verb, not a habit: booting a supervisor reaps dead
sessions, `fleet sup-guard` decides whether a body is alive, `fleet land`
rebases and checks a lane before a model reads it, `fleet wave-close` runs the
full suite from a clean clone, computes throughput, pushes and reports. Models
decide. Scripts do.

State lives on disk in a **fleet home** inside the repository (`state/`,
`supervisor/`, `knowledge/`), so any fresh session can pick the role back up
with no conversation history.

## Install

Linux and macOS:

```sh
git clone https://github.com/exPardus/fleet.git
cd fleet
export PATH="$PWD/bin:$PATH"       # POSIX shim; add this line to your shell rc to keep it
fleet --help
```

Requirements: Python 3.10 or newer on `PATH` (stdlib only, no pip install), the
`claude` CLI 2.1.202 or newer, and `codex` plus [mcx](https://github.com/exPardus/multi-codex)
if you want Codex workers. Windows: see the shim note in
[getting-started](docs/getting-started.md#windows).

Install the Claude Code plugin (skill plus `/fleet:*` slash commands; no hooks,
nothing changes for sessions that do not use fleet):

```sh
claude plugin marketplace add /absolute/path/to/fleet
claude plugin install fleet@claude-fleet
```

Restart Claude Code, then `claude plugin details fleet`.

## First run

In the repository you want fleet to work on:

```sh
cd ~/code/my-project
fleet init                 # creates this repo's fleet home and registers your session as its interface
fleet doctor               # every row should read [PASS]
fleet init --statusline    # optional: a status-line row for this home
```

Then, inside Claude Code in that repo, say what you want built. The skill's
"You are the interface" ritual takes it from there: it writes the brief with
you, spawns a supervisor with `fleet sup-spawn`, and relays what lands. To
resume in a fresh session later, say "continue as the interface".

Runtime directories (`state/`, `logs/`, `mailbox/`) are meant to be
gitignored; `fleet init` tells you if they are not.

## Everyday commands

```sh
fleet status                       # every worker, its state, turns, pending mail
fleet spawn NAME --dir PATH --task "..."   # one worker, its own session
fleet send NAME "..."              # steer a running worker, or start its next turn
fleet peek NAME                    # a short digest of what it is doing
fleet land NAME                    # rebase, test, check and summarise a lane
fleet sup-status                   # who holds the supervisor claim, and its health
fleet sup-guard                    # OK / WAKE / DISPATCH / PAGE, one line
fleet wave-close --base SHA --changelog @FILE
fleet homes                        # every fleet home on this machine
```

The same verbs exist as `/fleet:status`, `/fleet:spawn`, `/fleet:send` and so
on inside Claude Code. Full list with one line each: the manual.

## Unattended operation

For a fleet that runs on a server while you are away, a **keeper** systemd
timer watches every home, pages your interface session through tmux when a
human is needed, and wakes an idle supervisor when it only needs a turn. It
never dispatches. Templates and the recipe are under
[`docs/operator/`](docs/operator/). Off by default.

## Contributing and status

Fleet is used daily to build [a real product](docs/CHANGELOG.md) and to build
itself, in that order of priority: fleet features are added only when a
downstream job hits a wall. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
rules that bind changes here, `docs/SPEC.md` for the design record, and
`docs/OPERATOR-GATES.md` for decisions that are still open.

MIT licensed.
