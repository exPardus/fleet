# FAQ

## What is fleet, in one sentence?

A command-line layer that runs several Claude Code (and optionally Codex) sessions
on one job, keeps their state on disk, and lands their verified work, so the job
survives limits, crashes and reboots. See [concepts.md](concepts.md) for the longer
answer.

## Is fleet a coding assistant?

No. A plain Claude Code session is one. Fleet runs after you stop watching. It
starts sessions, tracks them, and decides when a worker's output is ready to land.

## Do I need Codex?

No. The Claude Code CLI is the only hard requirement. Codex is optional and is used
only for workers you start with `--model codex:<model>`. See
[codex-lanes.md](codex-lanes.md).

## Does fleet send my code somewhere?

Fleet has no server of its own. It starts Claude Code or Codex sessions. Those
sessions read your code and send it to their model provider, as they would in any
session. Fleet's own state (the registry, mail, journals, logs) stays in the fleet
home on your machine.

## Where does fleet keep its state?

In the fleet home: `state/`, `supervisor/`, `logs/`, `mailbox/`, `docs/lanes/`,
`knowledge/projects/`. These paths are git-ignored. Do not commit them. See
[configuration.md](configuration.md#files-inside-a-fleet-home).

## Can I use fleet in more than one repository?

Yes. Each repository gets its own fleet home. Run `fleet init` in each one, then
register them with `fleet homes --add PATH` if you want `fleet homes` and the keeper
to see them. Pass `--fleet-home PATH` on every mutating command when more than one
home is registered.

## Does fleet change my main branch?

Workers do their work on their own branches. Work reaches a target branch only
when it is landed with `fleet land`, which rebases the lane and runs its checks.
Review the lane's result before you land it.

## How do I stop a worker?

- `fleet interrupt NAME` stops the current turn. The session stays.
- `fleet kill NAME` stops the turn and marks the worker dead. Only `respawn` brings
  it back.

`kill` asks for `--yes` when the current session did not spawn the worker.

## How do I remove finished workers?

`fleet clean --dead-only` removes workers that are confirmed dead. Before it deletes
anything, it moves the evidence to `logs/archive/<name>/`, and it prints that path.
If the move fails, the row stays. `fleet archive` marks terminal workers past a
time-to-live. `fleet autoclean` runs that step together with cleanup of daemon
leftovers.

## What is a nonce?

A short value that the current supervisor generation prints once. Mutating
supervisor verbs require the newest printed nonce. It detects some divergent-body
continuity failures, but it is a knowingly bypassable speed-bump, not authorization
or proof of single-supervisor ownership. Record each nonce as it is printed. Do not
invent one, and do not reuse an old one. See
[troubleshooting.md](troubleshooting.md#lost-supervisor-nonce).

## Why do some verbs start with `sup-`?

They act on the supervisor role: its claim, heartbeat, handoff and journal. The
full list is in [cli-reference.md](cli-reference.md).

## Do the `/fleet:*` slash commands work without the CLI?

The slash commands call the `fleet` CLI, so `fleet` must be on `PATH`. The plugin
adds the skill and the slash commands only. It declares no hooks.

## How do I update fleet?

Pull the new version of the clone, then run `fleet init` again in each home. The
`instance-freshness` check in `fleet doctor` tells you when a home's rendered
settings are older than the template.

## Does fleet work on Windows?

Through Git Bash, or through PowerShell with the `py` launcher. The Windows shim
has a Python version requirement. The details and workarounds are in
[getting-started.md](getting-started.md#windows).

## Can I run fleet without the unattended keeper?

Yes. The keeper is off by default. Without it, you check on the fleet yourself with
`fleet status` and `fleet sup-guard`. See
[configuration.md](configuration.md#keeper).

## Where are the design rules?

[SPEC.md](SPEC.md) is the design record. [CONTRIBUTING.md](../CONTRIBUTING.md) lists
the rules that bind changes to the code.

## Who maintains fleet, and how do I report a problem?

Open an issue on the repository. For a security problem, follow
[SECURITY.md](../SECURITY.md). Do not put credentials or private repository content
in an issue.
