---
description: Compact fleet status table — every worker's status, turns, cost, idle time, pending mail.
allowed-tools: Bash(fleet:*)
---

!`fleet status`

Report anomalies only (`idle+mail`, stale attach, `dead`, `limited`, `resume-eligible`).
If there are none, say "fleet healthy" and stop.
