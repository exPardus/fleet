---
description: 'Fleet overview — status table, health warnings, and the knowledge index in one screen.'
allowed-tools: 'Bash(fleet status:*), Bash(fleet doctor:*), Bash(cat:*)'
---

# Fleet overview

## Status

!`fleet status`

## Health

!`fleet doctor`

## Knowledge

!`cat "${FLEET_HOME:-$(cat ~/.claude/fleet-home 2>/dev/null)}/knowledge/INDEX.md" 2>/dev/null || echo "(no knowledge index -- run 'fleet init')"`

---

Summarize the fleet's state in three lines or fewer: what is running, what needs
attention, and what the operator should do next. If `doctor` reported nothing and
every worker is healthy, say so plainly and stop.
