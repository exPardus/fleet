# Knowledge Index

One line per entry. The manager reads this file at every session start; keep entries short and pointer-like.

- `playbooks/spawn-etiquette.md` — doctrine for spawning and running workers (one task per worker, respawn over marathons, wait-in-background, permission modes, budget caps, batch spawns).
- `lessons.md#2026-07-07` — Campaign 0 (building fleet): dual-lens review doctrine, live-smoke-beats-unit-tests, Stop-block race is by-design (check idle+mail), sticky dead + respawn recovery, cost model.
- `lessons.md#2026-07-08` — Campaign 1 (haiku demo): full lifecycle green; fleet.cmd needs full path (not on PATH); mid-turn steering proven; respawn re-executes done tasks (not idempotent); "Final message = X" output contract works.
- `lessons.md#2026-07-08-c1` — Campaign 1 (SPEC v2.1 amendment pass, ~15 workers): PROCESS CHANGE #1 — tag folded findings `[UNBUILT — owned by <kernel>]` + split regressions passes-today vs pins-unbuilt (prevents the 1D fix wave); amend campaign-template.md.
- `lessons.md#2026-07-08-c1` — doc-adapted truth gate: anchor+witness grep per finding (not anchor-only) + manager spot-checks spec-vs-code claims against bin/fleet.py before ordering a fix; amend campaign-template.md.
- `lessons.md#2026-07-08-c1` — ops: mid-campaign feature-fold via `*-INTENT-*.md` binding note through the same gate (UL1/UL2); 7-wide disjoint commits = zero index.lock; `fleet result` cp1252 unicode crash → `PYTHONIOENCODING=utf-8` (C2 fix candidate); UL2 subagents default-on, doctor-safe.
