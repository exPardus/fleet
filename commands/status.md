---
description: 'Compact fleet status table — every worker''s status, turns, cost, idle time, pending mail.'
allowed-tools: 'Bash(fleet status --stale-ok)'
---

!`fleet status --stale-ok`

Report anomalies only (`idle+mail`, stale attach, `dead`, `limited`, `resume-eligible`).
If there are none, say "fleet healthy" and stop.

Rows show each worker's **last-committed** status plus how stale it is — this view
never probes, never takes `fleet.lock`, and never writes (terminal-surface D1/D2/D4).
A `working` row that has not moved in a while is stale, not verified-alive. Run
`fleet status` (no flag) when you need the authoritative recompute.
