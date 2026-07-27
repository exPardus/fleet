---
description: 'Fleet overview — status table, health warnings, and the knowledge index in one screen.'
allowed-tools: 'Bash(fleet status:*), Bash(fleet doctor:*), Bash(fleet knowledge:*)'
---

# Fleet overview

## Status

!`fleet status --stale-ok`

## Health

!`fleet doctor`

## Knowledge

!`fleet knowledge`

---

Summarize the fleet's state in three lines or fewer: what is running, what needs
attention, and what the operator should do next. If `doctor` reported nothing and
every worker is healthy, say so plainly and stop.

Status rows are **last-committed plus staleness**, not a fresh liveness probe — this
screen never writes (terminal-surface D1/D4). If `doctor` reports `[FAIL] registry:`,
say so and name `fleet doctor --repair`; do not run it yourself.
