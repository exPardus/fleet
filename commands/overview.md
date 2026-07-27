---
description: 'Fleet overview — command tier, status table, health warnings, and the knowledge index in one screen.'
allowed-tools: 'Bash(fleet status:*), Bash(fleet doctor:*), Bash(fleet knowledge:*), Bash(fleet sup-status:*)'
---

# Fleet overview

## Command tier

!`fleet sup-status`

## Status

!`fleet status`

## Health

!`fleet doctor`

## Knowledge

!`fleet knowledge`

---

Summarize the fleet's state in three lines or fewer: who holds command, what is
running, what needs attention, and what the operator should do next. If `doctor`
reported nothing and every worker is healthy, say so plainly and stop.

Read the tiers separately — a supervisor body is a registry row, so a fleet with
one worker and a pile of retired `sup|…|boot` husks is not a fleet of workers.
Never report a claim you could not read as "no supervisor".
