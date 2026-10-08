# Troubleshooting

Start with two checks:

```sh
fleet doctor          # health: registry, claude on PATH, hooks, settings freshness
fleet status          # every worker: state, turns, pending mail
```

Neither is a pure view. `fleet status` and `fleet doctor` are authoritative: they
can update registry verdicts such as `dead-suspected` while they run. The
statusline and the `/fleet:*` views do not do that. They read a status snapshot
(`fleet.status_snapshot()`), take no lock, and write nothing. Use the verbs above
when you need a verdict to be recorded.

For the supervisor, add `fleet sup-status` and `fleet sup-guard`. The operating
rules behind each recovery step are in [skills/fleet/SKILL.md](../skills/fleet/SKILL.md)
and [skills/fleet/supervisor.md](../skills/fleet/supervisor.md). Those files
are the authority. This page is the short version.

## `fleet doctor` reports a FAIL

| Check | Meaning | Fix |
|---|---|---|
| `claude-on-path` | `claude` is missing from `PATH`, does not run, or is too old | install or update Claude Code, then restart the shell |
| `worker-settings-instance` | `state/worker-settings.json` is missing or does not parse | run `fleet init` in the home |
| `instance-freshness` | `state/worker-settings.json` is older than the template | run `fleet init` in the home |
| `posttooluse-hook-smoke`, `stop-hook-smoke` | a hook script does not run end to end | check the Python path in `state/worker-settings.json`; run `fleet init` again |
| `local-seeds` | a local storage file that `fleet init` seeds is missing | run `fleet init` in the home |

Run `fleet doctor` without `--repair` first. `--repair` quarantines a corrupt
`state/fleet.json` and reconciles finished Codex turns. It changes state, so run it
only when the operator has authorised it. See
[cli-reference.md](cli-reference.md#fleet-doctor).

## Lost supervisor nonce

Every supervisor verb that changes state needs the current nonce. The nonce is
printed once, when a verb mints it. If the supervisor's own session lost the value,
do not guess it and do not spawn a second body.

1. Wait until the supervisor's registry row is `idle`. Check with `fleet status`.
2. Run:

   ```sh
   fleet send supervisor "recover the lost nonce" --fleet-home <path>
   ```

Fleet wakes the same supervisor incarnation in a fresh body with a new nonce. Its
bootstrap then aborts any pending handoff successor before it does campaign work.

If the supervisor is still busy, `send` queues the message. The busy body receives
it at its next tool boundary, inside the running turn; it does not wait for the turn
to end. Do not spawn a replacement while the busy body is alive.

A verb that gets no nonce is refused with a message about a second body. That
refusal is the guard working. It is not a fault in the fleet.

## Stuck busy holder

A supervisor is "busy" when its process is running a turn. A busy body whose
heartbeat has gone stale is the case to watch.

1. Run `fleet sup-guard --json`. Read the verdict:
   - `OK`: the heartbeat is fresh and a live body holds the claim. Do nothing.
   - `WAKE <body>`: the heartbeat is stale and the holder is idle. Run
     `fleet sup-guard --do` to re-verify and send the wake brief. It never spawns.
   - `DISPATCH`: no live body remains and the guard allows a new one. Only the
     interface runs `fleet sup-spawn`.
   - `PAGE`: the guard cannot decide. Report it to the operator.
2. For a stale busy holder, `sup-guard` lists up to three long-running child
   executable names and how long each has run. Use that to judge whether the body
   is stuck. It never prints command arguments.
3. Do not run `sup-spawn` around a busy holder. Two live bodies is the failure the
   claim protocol exists to prevent.

## `dead-suspected`

`dead-suspected` means fleet cannot confirm that a worker is alive or finished. Fleet
never respawns such a worker on its own, because a respawn runs the worker's side
effects again.

1. Look before you act:

   ```sh
   fleet peek NAME        # the recent events
   fleet result NAME      # the last completed turn's answer, if there is one
   ```

2. `fleet wait NAME --timeout 600` ends promptly on a `dead-suspected` worker.
   Do not loop on `fleet status`.
3. If the turn is over and its result is in hand, record it. If the stream clearly
   died, `fleet respawn NAME` can recover it. If fleet cannot rule out a running turn,
   `respawn` refuses. Pass `--force` only after you have confirmed the turn is not
   running.

## Codex host restart

Native Codex workers keep their turns in a host process that fleet starts for each
home. When that process restarts, rows that were mid-turn can be left as
`dead-suspected`.

- **Supervisor on Codex:** run `fleet sup-reconcile`. It reconciles the native
  Codex supervisor after a host restart. It never creates a new thread or turn.
- **Worker rows:** `fleet doctor --repair` reconciles legacy `dead-suspected` native
  Codex rows whose durable record and live turn evidence both say the turn
  completed. A row with any doubt stays as it is. Repair is an operator decision.

For how Codex lanes are dispatched and recorded, see [codex-lanes.md](codex-lanes.md).

## A worker stopped at a usage limit

A worker that hit a plan usage limit is parked as `limited` with a reset horizon. It
is not dead. Check the horizon with `fleet status`. Then:

```sh
fleet resume-limited            # every limited worker whose horizon has passed
fleet resume-limited NAME       # one worker
```

`--force-now` resumes a worker before its horizon passes. Do not use it to work
around a limit that the provider has not lifted. A supervisor that is `limited`
waits for the recorded horizon. Do not wake or spawn around that limit.

## A worker is over its token ceiling

The status is `over_ceiling`. The worker refuses to continue. Raising a ceiling is a
cost decision, so the operator makes it. Either respawn with a new `--token-ceiling`
the operator has approved, or run `fleet kill NAME` if the work is no longer needed.

## Context band refusals

A supervisor past its soft context band (350k tokens) refuses `spawn`, `send`,
`respawn` and `sup-spawn`. It does this on purpose: a body near its limit should hand
off, not keep working. Hand off with `fleet sup-handoff-begin`. Use `--force-band`
only for a single call the operator has approved. It never overrides the hard
ceiling.

Measure a session's occupancy with `fleet sup-context`.

## Steering does not reach a worker

`fleet send` to a running worker queues the message for the next tool boundary.
Nothing happens until the worker makes a tool call. A worker that is only thinking
reads the message late. Wait for the next tool call, or use `fleet peek NAME` to see
whether the worker is still active.

## Keeper pages

A `KEEPER:` line is an observation, not an instruction. Read the board, run
`fleet status`, `fleet sup-status` and `fleet sup-guard`, then follow the guard's
verdict. Page the operator on `PAGE` or on any ambiguity.

## Windows

The `bin\fleet.cmd` shim needs Python 3.13 through the `py` launcher. Without it,
every command fails with `No suitable Python runtime found`. The workarounds are in
[getting-started.md](getting-started.md#windows).

## Tests fail on your machine

Run the suite from a clean `git clone --no-local`, not from a home with live
workers. Some tests assume a host layout. The getting-started page lists the known
host-dependent failures under [Running the tests](getting-started.md#running-the-tests).
Compare a failure with that list before you treat it as a regression.
