# Codex lanes

A **lane** is one worker on its own branch and worktree. A Codex lane is a worker
whose session runs on the Codex CLI instead of Claude Code. Fleet dispatches,
steers, inspects and stops Codex lanes with the same verbs it uses for Claude
workers. This page covers what is different.

For a Codex supervisor, read [skills/codex-fleet/SKILL.md](../skills/codex-fleet/SKILL.md),
which routes Codex sessions into the interface, supervisor and worker roles.

## Requirements

- The **Codex CLI**, installed and signed in on the machine that runs fleet.
- Nothing else for the default **native** adapter. Fleet starts one host process
  per fleet home, and the host talks to Codex over its own protocol.
- **mcx** only for the legacy `--codex-adapter mcx` route. See
  [the mcx route](#the-legacy-mcx-route) below.

`fleet doctor` includes a codex-adapters check. A failure there names the missing
piece.

## Dispatch

```sh
fleet spawn NAME --dir PATH --model codex:<model> --task "..."
fleet spawn NAME --dir PATH --model codex:<model> --codex-adapter mcx --effort high --task "..."
```

- `--model codex:<model>` selects a Codex model. The `codex:` prefix is what routes
  the lane to Codex. Use the model name your Codex installation accepts.
- `--effort` applies only to the legacy mcx adapter, where it accepts `low`,
  `medium`, `high` or `xhigh` and defaults to `medium`. The native adapter ignores
  this option; omit it on native lanes.
- `--codex-adapter native|mcx` picks the transport. The default is `native`. New
  rows use `native` unless you say otherwise.

The row records the adapter and the model. Every later verb on that lane uses the
recorded adapter. You do not pick it again.

## Driving a lane

These verbs work the same for Codex and Claude lanes:

| Verb | Codex behaviour |
|---|---|
| `fleet status`, `fleet peek`, `fleet result` | read the recorded adapter's state and output |
| `fleet send NAME TEXT` | steers the running turn, or starts the next turn when the lane is idle |
| `fleet interrupt NAME` | stops the current turn; the session stays |
| `fleet kill NAME` | stops the turn and marks the lane dead |
| `fleet respawn NAME` | starts a fresh session with the same worker identity and recorded brief |
| `fleet land NAME` | commits the lane's worktree if needed, rebases, and runs the checks |

**A Codex worker does not commit.** Its worktree is left dirty. `fleet land` then
commits the worktree on the worker's behalf, after it validates the lane's
structured result. The lane's brief should say what the commit message is about, not
ask the worker to commit.

### Approval and input requests

A Codex turn can pause to ask for approval or input. Answer each request once:

```sh
fleet codex-respond NAME REQUEST_ID DECISION
```

`DECISION` is one of the choices the request offers, a JSON object, or `@file`.
Answering the same request twice is refused. A request that no longer exists is
refused too. Check the lane with `fleet peek NAME` to find the current request.

## The native adapter

Native lanes talk to Codex through one persistent host per fleet home. That host
owns the protocol and the approval queue, so a steer or an interrupt reaches the
right turn, and an approval request stays answerable.

Because the host is shared, it is also the thing that can restart. After a host
restart, see [troubleshooting.md](troubleshooting.md#codex-host-restart).

## The legacy mcx route

`--codex-adapter mcx` runs the lane through the `mcx` helper instead. Use it only
for a lane that was started that way, or for a deliberate reason. The differences:

- Fleet maps its permission modes to mcx approval modes as
  `bypass` → `unrestricted`, `accept` → `auto`, and `dontask`, `plan` and `omit` →
  `never`. A `MCX_APPROVAL` variable in the caller's environment cannot weaken the
  mode fleet recorded.
- mcx runs `codex exec` under the `workspace-write` sandbox by default. A worktree's
  git directory lies outside the lane's working directory, so the lane cannot commit.
  `fleet land` commits instead.
- Steering an mcx run restarts the run. Re-arm any observer you started for the lane
  after each `send`.

## Limits and counting

Codex lanes count against the same worker limits as Claude lanes. The operating
manual in [skills/fleet/SKILL.md](../skills/fleet/SKILL.md) states the current
limits under Dispatch. Count Codex and Claude workers together.

## Troubleshooting

- A lane shows `dead-suspected` after a host restart: see
  [troubleshooting.md](troubleshooting.md#codex-host-restart).
- A lane is stuck on an approval request: `fleet peek NAME`, then
  `fleet codex-respond`.
- A lane's result is missing: `fleet result NAME` reads only completed turns. A turn
  still running has no result yet.
