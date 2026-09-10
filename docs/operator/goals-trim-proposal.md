# Proposal: trim `supervisor/GOALS.md`

This is a proposed replacement for the operator-owned goals file. It is not
the live goals file; an operator must review and apply it.

## Target

Make claude-fleet a reliable long-running multi-session tool: preserve work
across crashes, usage limits, context exhaustion, and reboots.

## Priorities

1. Ship the native-substrate pivot and keep its contract authoritative.
2. Detect usage-limit loss, park work, and resume after the reset horizon.
3. Keep fleet integration native and avoid writes to foreign surfaces.
4. End campaigns with concise lessons and tested process improvements.
5. Run external campaigns and use their friction as defect input.
6. Keep specifications and portability documentation ready for upstream use.

## Tier policy

Roles bind to abstract tiers. The interface uses the top tier; the supervisor
prefers top and falls back to second; workers use second or third. Workers are
never Haiku. The supervisor may use bypass permission mode in the fleet repo.

## Context and checkpoints

The context band is 150–200k for supervisors and workers. Hand off at the next
safe boundary after entering it; do no new work at 200k. Checkpoint the plan at
every wave boundary and before a usage-limit park.

## Operating constraints

- Keep destructive actions and specification promotion behind operator gates.
- Use revert-on-red, adversarial review, and fault injection for self-changes.
- Do not mass-respawn on a suspicious roster; freeze and page the operator.
- Prefer right-sized beats, disjoint tasks, fresh contexts, and batched work.
