# Configuration

Fleet has few settings. Most behaviour comes from the verbs' options, listed in
[cli-reference.md](cli-reference.md). This page covers the files and the
environment that the rest of the system reads.

## Choosing a fleet home

A command acts on one fleet home. Fleet picks it in this order:

1. The `--fleet-home PATH` option. It works in any position on the command line.
2. The home that the current Claude Code session belongs to, when that session is
   listed in a registered home.
3. The `FLEET_HOME` environment variable, if set.
4. The checkout that contains `bin/fleet.py`.

When you run more than one home on a machine, pass `--fleet-home` on every
mutating command. Do not rely on an ambiguous default.

`fleet homes` lists the homes registered on this machine. `fleet init --home PATH`
registers one. `fleet homes --add PATH` registers an already-initialised home.
`fleet homes --retire PATH` appends a retirement record. The registry file is
`~/.claude/fleet-homes.list`. It is append-only, so a mistaken entry is reversed
with a retirement record, not by editing the file.

## Files inside a fleet home

`fleet init` creates these. It never replaces existing local content.

| Path | Written by | Purpose | Commit it? |
|---|---|---|---|
| `state/fleet.json` | `fleet init` | the worker registry; only fleet writes it, under a lock | no (git-ignored) |
| `state/worker-settings.json` | `fleet init` | hook wiring for worker sessions, rendered from the template | no (git-ignored) |
| `state/interface/` | `fleet interface-register` and the interface | the interface's board and handover notes | no |
| `supervisor/GOALS.md` | you | what "done" means for the campaign, the departments, the repository's rules | no |
| `supervisor/wave-close.json` | you, optional | the test floor that `wave-close` and `land` use for this repository | no |
| `logs/`, `mailbox/`, `docs/lanes/`, `knowledge/projects/` | fleet | worker logs, mail, lane results, per-project notes | no |

The runtime directories are local. The fleet source checkout ignores them by
default. In another repository, add them to that repository's `.gitignore`.

## `worker-settings.json`

Each Claude Code worker is started with a settings file. Native Codex lanes do
not use this file; they communicate through the persistent Codex host for the
fleet home. `fleet init` renders `state/worker-settings.json` from the template at
[`worker-settings.template.json`](../worker-settings.template.json). The rendered
file contains:

- **`permissions.allow`**: tool permissions granted to every worker. The template
  allows `Bash(fleet q:*)` so workers can query the project's symbol index.
- **`crossSessionInbound`**: set to `accept`, so a worker receives steering messages
  from the supervisor.
- **`hooks`**: three hook commands, each started with the Python interpreter that
  ran `fleet init`:
  - `PostToolUse` runs `bin/hooks/posttooluse_mailbox.py`. It delivers queued
    steering messages at the next tool boundary.
  - `Stop` runs `bin/hooks/stop_outcome.py` and `bin/hooks/stop_mailbox.py`. The
    first records the turn's outcome. The second checks for mail that arrived
    during the turn.
  - `PostCompact` runs `bin/hooks/postcompact_journal.py`. It writes a marker to the
    worker's journal after a context compaction.

Every hook path is written with forward slashes on every platform, including
Windows. The hook scripts exit 0 on failure, so a broken hook does not stop a
worker. It shows up in `fleet doctor` and in missing outcomes instead.

After you change the template or move the checkout, run `fleet init` again. The
`instance-freshness` health check reports a rendered file that is older than the
template and names this command.

## `wave-close.json`

`fleet wave-close` runs the test floor in a fresh clone of the repository before it
lands a wave. With no configuration, the floor is fleet's own: Python 3.10 and 3.12,
`uv run --no-project --with pytest`, and the `tests/` directory. Your repository
usually needs something else. Put a JSON object in `supervisor/wave-close.json`.
Every key is optional:

```json
{
  "interpreters": ["3.12"],
  "uv_run_args": ["--no-project", "--python", "{python}", "--with", "pytest"],
  "test_paths": ["tests"],
  "pytest_args": [],
  "expected_failures": [],
  "env": {"UV_CACHE_DIR": null},
  "uv_offline": true,
  "gates": []
}
```

| Key | Meaning |
|---|---|
| `interpreters` | distinct `X.Y` Python versions to run. With two or more, their totals and failures must agree. |
| `uv_run_args` | arguments before the test command. Must contain `{python}`, which is replaced by each interpreter. |
| `test_paths` | test paths relative to the repository. Absolute paths and `..` are refused. |
| `pytest_args` | extra arguments for pytest. |
| `expected_failures` | test IDs that are known to fail on the host. Empty when omitted. |
| `env` | environment variables for the test run. A `null` value unsets the variable. |
| `uv_offline` | whether `uv` runs without network access. |
| `gates` | landing gates for `fleet land`. See below. |

An unknown key or a malformed value refuses the close before any state changes.
The receipt for the run records the config it used.

**Landing gates.** Without `wave-close.json`, `fleet land` runs fleet's own
`docs-currency` and `receipts` gates. A repository with a config runs no
fleet-specific gate by default. Set `gates` to a list of built-in gate names, or to
`{"name": ..., "command": ...}` objects for your own checks.

## Status line

`fleet init --statusline` adds fleet's row to the Claude Code status line. It writes
into `~/.claude/settings.json`, which is machine-wide. Plugins cannot ship a status
line, so this command is the only way to install one.

- If another status line is already configured, the command refuses to overwrite it.
- `--chain` keeps the existing status line and prints fleet's row beneath it. The
  chained command is recorded in `~/.claude/fleet-statusline-chain.json`.
- `--force` replaces a foreign status line. Use it only when you no longer need the
  old one.

Fleet's row shows the home's tag, so two homes on one machine are easy to tell apart.
Run `fleet home --tag` to print the tag for the current home. The status line reads
the registry through a read-only snapshot. It never takes a lock, and it never
repairs state.

## Environment variables

| Variable | Effect |
|---|---|
| `FLEET_HOME` | default home when no `--fleet-home` option is given |
| `FLEET_PYTHON` | interpreter used by the `bin/fleet` shim, if you do not want the first one it finds |
| `CLAUDE_CODE_OAUTH_TOKEN` | a long-lived token that makes Claude Code's remote control refuse to start. Unset it for interface sessions: `env -u CLAUDE_CODE_OAUTH_TOKEN claude` |

## Keeper

The keeper is optional and off by default. Run it on a schedule with
`bin/fleet_keeper.py --once --fleet-home PATH`, once per home. It pages the
interface's tmux pane, wakes an idle supervisor, and never dispatches work. Service
units and schedules are host-specific. Keep them in your own operator storage, not
in the repository. See [getting-started.md](getting-started.md#unattended-on-a-server).
