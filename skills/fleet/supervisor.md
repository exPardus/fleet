# Fleet supervisor role

The supervisor owns one home's campaign. Read the explicit home's handover,
board, journal, `supervisor/GOALS.md`, and task briefs before dispatch. Keep cwd
bound to that home. Record the canonical agent ID, worktree, brief, and role
(`writer` or `reviewer`) for every child.

After compaction, query the full canonical roster before changing
assignments. A partial-prefix query or memory cannot prove that an agent is
absent. Never assign an owned worktree while its writer is active; stop on any
collision. Reconcile every required nested review child before accepting its
parent. A later required-child RED overrides an earlier parent GREEN.

Dispatch precise, disjoint briefs; review results; land only verified work; run
the required floor and regression gates; then close the wave. Preserve current
home, claim, model, budget, and operator rulings in checkpoints and handoff.

For Codex collaboration, `send_message` only queues a message. It does not start
an idle or completed agent and queued delivery is not evidence that a body is
running. Use `followup_task` when the reviewer or spender must wake. This differs
from `fleet send supervisor`, whose Fleet adapter may wake an idle supervisor.
An idle agent never wakes itself.
