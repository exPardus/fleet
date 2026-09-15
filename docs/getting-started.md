# Getting started

From a clone to a supervisor working on your repository. Read
[concepts.md](concepts.md) once if you want the mechanics; this page is the
commands.

## Requirements

- **Linux or macOS** with a POSIX shell; **Windows** works through Git Bash or
  PowerShell with the caveat under [Windows](#windows).
- **Python 3.10 or newer** on `PATH`. `bin/fleet.py` is stdlib only; nothing
  to pip install. The floor is declared once as `fleet.MIN_PYTHON_VERSION`.
- **Claude Code CLI 2.1.202 or newer**, logged in. Fleet shells out to
  `claude` for every dispatch.
- Optional: **Codex CLI** and [mcx](https://github.com/exPardus/multi-codex)
  for Codex workers; **tmux** and **systemd** for the unattended keeper.

## Install

```sh
git clone https://github.com/exPardus/fleet.git
cd fleet
export PATH="$PWD/bin:$PATH"      # put this line in your shell rc to keep it
fleet --help
```

`bin/fleet` is a shim that picks the first interpreter it finds at or above
the floor, honouring `$FLEET_PYTHON` if you set it.

Install the Claude Code plugin. It ships the `fleet` skill and the `/fleet:*`
slash commands and declares no hooks, so sessions that do not use fleet are
untouched:

```sh
claude plugin marketplace add /absolute/path/to/your/clone
claude plugin install fleet@claude-fleet
```

Restart Claude Code and check with `claude plugin details fleet`.

## First run in a repository

```sh
cd ~/code/my-project
fleet init
```

`fleet init` creates the repository's **fleet home**: `state/fleet.json` (the
worker registry) and `state/worker-settings.json` (the hook wiring, rendered
with this machine's Python path). It registers the calling terminal as the
home's interface when run inside tmux, and prints the startup ritual.

Add the runtime directories to `.gitignore` if they are not already:

```
state/
logs/
mailbox/
.mcx/
```

Then:

```sh
fleet doctor            # health: registry, claude on PATH, hooks fire end to end
fleet status            # the worker table, empty for now
fleet init --statusline # optional: fleet's row in the Claude Code status line
```

`fleet init` does not register the home in the machine-wide list
(`~/.claude/fleet-homes.list`). Do that with `fleet homes --add <path>` when
you want `fleet homes` and the keeper to see it; the list is append-only and a
mistaken add is reversed with `fleet homes --retire`.

## Your first job

Open Claude Code in the repository. The plugin's skill carries the interface
ritual: say what you want built, and the session writes the brief with you,
spawns a supervisor, and relays what lands. By hand, the same thing is:

```sh
fleet sup-spawn --task @supervisor/briefs/<your-brief>.md --model opus \
  --setting-sources project,local
fleet sup-status          # the claim, its heartbeat, any pending handoff
fleet sup-guard           # OK, WAKE <body>, DISPATCH, or PAGE <reason>
```

The supervisor reads `supervisor/GOALS.md` (yours to write: what done means,
what the departments are, what the repo's rules are), splits the job, and
dispatches workers. To steer it: `fleet send 'sup|<inc>|boot' "..."`.

A single worker without a supervisor:

```sh
fleet spawn migrate-users --dir . --mode bypass --model sonnet \
  --task "Port the users table migration from Knex to raw SQL, see MIGRATION.md"
fleet peek migrate-users
fleet send migrate-users "also add a down-migration"
fleet result migrate-users
```

## Resuming

Fleet keeps its state in the home, not in any session. In a fresh Claude Code
session in the same repository, say "continue as the interface": it runs
`fleet interface-register`, reads `state/interface/board.md`, checks the
supervisor, and reports. Supervisors hand off to a successor at their context
band on their own.

## Unattended, on a server

The keeper is a systemd user timer that runs `bin/fleet_keeper.py --once` for
every home you name. It pages the interface's tmux pane when a human is
needed, wakes an idle supervisor with `fleet send` when it only needs a turn,
and never dispatches. Templates: `docs/operator/systemd/`. Recipe:
`docs/operator/keeper-wake.md`. If your shell exports a long-lived
`CLAUDE_CODE_OAUTH_TOKEN`, launch interface sessions with
`env -u CLAUDE_CODE_OAUTH_TOKEN claude` or Remote Control will refuse.

## Windows

The library runs at Python 3.10, but the `bin\fleet.cmd` shim invokes
`py -3.13` with no fallback, so through that shim Windows needs Python 3.13.
Without it every `fleet` command fails with the `py` launcher's
`No suitable Python runtime found`. Workarounds: use Git Bash, whose `bin/fleet`
shim falls back through `python3.13` to `python3.10`, or run
`py -3.10 bin\fleet.py ...` directly. Hook commands in `worker-settings.json`
use forward slashes on every platform.

## Running the tests

```sh
uv run --no-project --python 3.10 --with pytest python -m pytest -q
uv run --no-project --python 3.12 --with pytest python -m pytest -q
```

Run from a fresh `git clone --no-local`, never from a home with live workers;
the suite reads the live registry through the install-root seam. Six failures
are known host assumptions on Linux (Windows drive-letter paths and venv
shims).
