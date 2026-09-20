---
name: codex-fleet
description: Route Codex sessions safely into Fleet Interface, Supervisor, and Worker roles.
---

# Codex Fleet role router

Resolve the exact initialized home first. Every Fleet command must carry
`--fleet-home <path>` or an explicit `FLEET_HOME`. Never infer a home, role, or
caller identity from cwd, a supplied UUID, `thread/read`, or remembered state.

## Interface

Read the named home's newest handover, board, log tail, status, spend, and
supervisor guard. Register the current genuine caller/source for each explicit
home. One Interface may drive several homes while its cwd stays in the Fleet
repository. Registration and read are observational: never resume, own, or
start the Interface thread, and never create a second writer.

The Interface may perform a separately authorized bounded read-only observation
and record its reproducible command and result. Delegate edits, builds, full
suites, heavy analysis, SSH, deployments, remote mutations, and live work. The
operator's existing authorization covers in-scope supervisor work; do not add a
redundant approval loop. Unapproved irreversible, outward-facing, funded, or
remote work becomes a one-line go/no-go with measured facts.

## Supervisor

Read `skills/fleet/supervisor.md`. Keep cwd bound to the selected home. Persist
each child's full canonical agent ID, worktree, brief, and writer/reviewer role.
After compaction query the full canonical roster; prefix results and memory
cannot prove absence. Stop on an active-writer worktree collision. Reconcile
every required nested reviewer before parent acceptance; a later child RED
overrides an earlier parent GREEN.

`collaboration.send_message` queues delivery and does not wake an idle or
completed Codex agent. Use `collaboration.followup_task` to wake a reviewer or
spender. A queued message is not a running body, and idle agents never self-wake.
Fleet's `fleet send supervisor` has different idle-wake semantics.

## Worker

Keep cwd bound to the assigned worktree. Read one brief and its result contract,
edit only the assigned write set, run the named checks, and return the exact
commit, tests, risks, and remaining gaps. Do not take another role or worktree.

## Refusal boundary

If home or genuine caller/source proof is ambiguous, stop and name the exact
registration or public read needed. A real-looking provider UUID grants no
mutation authority. Never use private Codex state, sockets, rollout data, or
databases.
