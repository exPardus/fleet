---
description: 'Fleet health check — claude version, hook wiring, stale attaches, orphaned mailboxes, limited parks, autoclean last-run age.'
allowed-tools: 'Bash(fleet doctor:*)'
---

!`fleet doctor`

For each reported problem, give the one command that fixes it. Do not run any
of them without being asked.

`fleet doctor` is **report-only**. The one mutating remedy it has is
`fleet doctor --repair`, which quarantines a corrupt `state/fleet.json` by
renaming it aside — name it if `[FAIL] registry:` appears, and let the operator
run it.
