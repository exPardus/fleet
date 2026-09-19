# AGENTS.md — claude-fleet

Start with `CLAUDE.md` (repo rules) and `docs/SPEC.md`. This file says how an agent session
takes a ROLE in the fleet. It is deliberately timeless: what is true today — which homes are
busy, which models are allowed, what the operator last ruled — lives in the interface
handover, never here.

## The roles

- **Interface**: the one session a human talks to. Rules, relays, dispatches, stops things.
  It does not write lane code. State lives in each home's `state/interface/` (`board.md`,
  `log.md`, the newest `HANDOVER-*.md`). Any CLI can hold this role — Claude, Codex, or
  another — because the job is `fleet` commands plus judgement.
- **Supervisor**: owns a home's campaign, dispatches lanes, reviews and lands them, closes
  waves. Holds the home's claim.
- **Lane**: a worker in its own git worktree, one brief, one result contract.

## Taking the interface role

1. Read, in this order: the newest `state/interface/HANDOVER-*.md` in each home, then that
   home's `state/interface/board.md` and the tail of `log.md`.
2. `fleet interface-register` in every home you are driving.
3. `fleet status --fleet-home <home>` for each home, and check the substrate's spend.

Every fleet command takes `--fleet-home <path>` or `FLEET_HOME=<path>`. Without it you act
on the install-root default, which is usually the wrong repo.

## The commands the role uses

```bash
fleet status | peek <name> | result <name>      # observe
fleet send supervisor "<orders>"                 # steer or wake the supervisor
fleet interrupt <lane> | respawn <lane> --yes    # stop / revive a lane
fleet sup-status | sup-spawn --task @<brief>     # the supervisor's claim and boot
```

`fleet send supervisor` reaches a mid-turn body through its mailbox, or wakes an idle one.
**An idle supervisor never wakes itself: when the interface stops, the fleet stops.** If you
must leave, say so in the handover and tell the supervisor to report idleness instead of
waiting silently.

## Standing habits of the role

- Log every ruling and measurement to `state/interface/log.md`: UTC timestamp, then a verb —
  `RULING`, `RELAY`, `MEASURED`, `DEPLOY`, `INCIDENT`.
- A number without a command that reproduces it is not a measurement.
- Anything irreversible, outward-facing or money-shaped goes to the operator as a one-line
  go/no-go with the numbers, before it happens.
- Model and budget policy is per home, in `supervisor/GOALS.md` inside the
  `<!-- fleet-tier-policy -->` comment. A `tier-model:` line outside that comment is invisible
  to the parser and the body boots on the default instead.
- Fleet's own defects are tracked in `state/tasks/20260916-self-improve-standing.md`; read the
  open items before blaming a home. `fleet archive` before `fleet clean` — clean deletes
  briefs and journals.
- When a verb cannot work in a foreign home (its gates and floor are this repo's), land by
  hand and record the wave "closed by record" in the interface log.
