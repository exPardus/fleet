# fleet

**Run a team of Claude Code and Codex sessions on your repository, from one
interface session, while you are away.**

You describe a job. Fleet turns it into a brief, starts a supervisor session that
splits the work, starts worker sessions on their own git branches, reviews what
they produce, lands the verified changes, and reports back. Fleet keeps its state
on disk, so the work survives context limits, crashed sessions, reboots and
usage limits.

Fleet is not a coding assistant. A plain Claude Code session is one. Fleet is the
layer that keeps several of them working on one job over hours or days.

## How it fits together

Fleet has three tiers. Each tier is a Claude Code session with a defined role.

| Tier | What it is | What it does |
|---|---|---|
| **Interface** | your own Claude Code session in a repository | turns your intent into a brief, reports progress, and decides anything irreversible |
| **Supervisor** | a session that fleet starts and hands over at its context limit | splits the job into lanes, dispatches workers, reviews results, lands them, closes waves |
| **Workers** | Claude Code or Codex sessions, each on its own branch | do one bounded piece of the work and stop |

Mechanical steps are commands, not habits. Booting a supervisor reaps dead
sessions. `fleet sup-guard` decides whether a supervisor body is alive. `fleet land`
rebases a lane and runs its checks before a model reads the result. `fleet wave-close`
runs the full test floor, computes the wave's accounting, pushes and reports. Models
make decisions; scripts do the rest.

Fleet's state lives in a **fleet home**: a local directory inside your repository
(`state/`, `supervisor/`, `logs/`, `mailbox/` and similar), git-ignored. A fresh
session can resume a role from those files without the old conversation.

For the full picture, read [docs/concepts.md](docs/concepts.md).

## Requirements

- **Linux or macOS**, or Windows through Git Bash (see [Windows](docs/getting-started.md#windows)).
- **Python 3.10 or newer** on `PATH`. Fleet's `bin/fleet.py` uses only the standard
  library, so there is nothing to `pip install`.
- **Claude Code CLI 2.1.202 or newer**, logged in. Fleet starts Claude workers and supervisors through `claude`. Native Codex lanes do not use `claude`; they talk to the Codex app-server through a fleet host process.
- **Optional:** the Codex CLI, for Codex workers. [mcx](https://github.com/exPardus/multi-codex)
  is needed only for the legacy `--codex-adapter mcx` route. **tmux** and
  **systemd** are needed only for the unattended keeper.

## Install

Clone the repository and put its `bin/` directory on your `PATH`:

```sh
git clone https://github.com/exPardus/fleet.git
cd fleet
export PATH="$PWD/bin:$PATH"      # add this line to your shell rc to keep it
fleet --help
```

Then install the Claude Code plugin. It adds the `fleet` skill and the `/fleet:*`
slash commands. It declares no hooks, so sessions that do not use fleet are not
affected:

```sh
claude plugin marketplace add /absolute/path/to/fleet
claude plugin install fleet@claude-fleet
```

Restart Claude Code and check the install with `claude plugin details fleet`.

Full details: [docs/getting-started.md](docs/getting-started.md).

## Quickstart (about five minutes)

Run these in the repository you want fleet to work on.

```sh
cd ~/code/my-project
fleet init        # create this repository's fleet home
fleet doctor      # health checks; no line should read FAIL
fleet status      # the worker table, empty for now
```

Start one worker on a small, bounded task. It runs as a Claude Code session in
the directory you name. Its permission mode defaults to `dontask`, which runs
without interactive prompts. A worker uses your Claude usage, so start small:

```sh
fleet spawn hello --dir . --task "Add a short CONTRIBUTING section on running the tests"
fleet peek hello                           # what it is doing now
fleet send hello "keep the change small"   # steer it mid-turn, or start its next turn
fleet result hello                         # the final answer, once its turn ends
```

A worker that is part of a larger job writes a structured lane result. Then
`fleet land NAME` checks it, rebases the branch and runs the checks. See
[getting-started](docs/getting-started.md#your-first-job) for the lane format.

For a whole job, open Claude Code in the repository and say what you want built.
The plugin's skill takes it from there: it writes a brief with you, starts a
supervisor, and relays what lands. Later, in a fresh session, say
"continue as the interface" to pick the role back up.

## Core verbs

Every verb is listed with its options in [docs/cli-reference.md](docs/cli-reference.md).
These are the ones you will use most:

| Verb | Purpose |
|---|---|
| `fleet init` | create the fleet home in the current repository |
| `fleet doctor` | run health checks; `--repair` quarantines corrupt state and reconciles finished Codex turns |
| `fleet status` | every worker, its state, turns and pending mail |
| `fleet spawn NAME --dir PATH --task TEXT` | start one worker |
| `fleet send NAME TEXT` | steer a running worker, or start its next turn |
| `fleet peek NAME` / `fleet result NAME` | what a worker is doing / its final answer |
| `fleet land NAME` | rebase, check and summarise a worker's branch |
| `fleet sup-spawn`, `fleet sup-status`, `fleet sup-guard` | start a supervisor, read its claim, check that only one body is live |
| `fleet wave-close --base SHA --changelog TEXT` | close one wave: reap, run the floor, account, land, push |
| `fleet homes` | list the fleet homes on this machine |

## Safety model

Fleet is built so that a long unattended run stays recoverable and does not do
anything you did not ask for.

- **Pull-only.** Fleet injects nothing into sessions that do not ask for it. Plugin
  surfaces are prompt templates and read-only views.
- **Local state.** State stays in the fleet home, which is git-ignored. Tracked files
  are generic source and documentation.
- **Honest status.** A worker that fleet cannot confirm is alive or finished becomes
  `dead-suspected`. Fleet never respawns it automatically, because a respawn runs its
  side effects again.
- **Explicit destruction.** `kill`, `clean`, `archive`, repair and home retirement
  need an explicit confirmation flag or operator decision. `clean` moves evidence to
  `logs/archive/` before it deletes anything.
- **Ownership by nonce.** Supervisor verbs that change state require the nonce printed
  by the current supervisor generation, so two live supervisors cannot silently
  share one job.
- **Least permission.** Each worker runs in the permission mode you choose. The mode
  `bypass` skips permission prompts entirely; use it only for a task you have
  scoped tightly.
- **Land before trust.** A lane's work reaches its target branch through
  `fleet land`, which validates the lane's structured result, rebases the branch and
  runs the repository's checks.

The formal contract is in [docs/SPEC.md](docs/SPEC.md). Reporting a security issue:
see [SECURITY.md](SECURITY.md).

## Learn more

- [Getting started](docs/getting-started.md): install, first job, resuming, Windows, tests.
- [Concepts](docs/concepts.md): the problem fleet solves and how the state machine works.
- [CLI reference](docs/cli-reference.md): every verb and option, generated from the parser.
- [Configuration](docs/configuration.md): `worker-settings.json`, `wave-close.json`, the status line.
- [Troubleshooting](docs/troubleshooting.md): lost nonces, busy holders, Codex host restarts, `dead-suspected`.
- [Codex lanes](docs/codex-lanes.md): running Codex workers.
- [FAQ](docs/faq.md): short answers to common questions.
- [Operating manual](skills/fleet/SKILL.md): every tier, every rule, the full procedure.
- [Docs index](docs/README.md): every document in the repository, by audience.

## Unattended operation

A fleet can run on a server while you are away. A **keeper** script, run from a
systemd timer, checks each home. It pages your interface session through tmux when a
person is needed, and it wakes an idle supervisor when that supervisor only needs a
turn. The keeper never dispatches work. It is off by default, and host-specific
service files belong in your own operator storage, not in this repository. See
[docs/getting-started.md](docs/getting-started.md#unattended-on-a-server).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the binding rules, the test commands on
both supported interpreters, and the pull-request expectations. The design record is
[docs/SPEC.md](docs/SPEC.md).

## License

MIT. See [LICENSE](LICENSE).
