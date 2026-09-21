# GREEN — Codex zero-inference acceptance repair

**Source:** `53ad638ae0ee8e51b4e5c1fe0b69a58aaef6da09`

**Verdict:** GREEN; prior RED blockers are closed.

Public initialize canonically resolves returned `codexHome` and requires equality with configured `CODEX_HOME`; a mismatch cannot publish ready. The sealed receipt and fixture hashes recompute exactly. They bind a canonical UUIDv7 thread/session, distinct UUIDv4 host generations, start/resume journal generations and input/output hashes, and host/app-server PID plus start-identity pairs.

All four recorded processes are absent. The harness waits for zero tree references before deletion, checks task-prefixed stale trees similarly, repeats process/tree/lock checks, and the prior and active trees are now absent. The acceptance path removes API-key variables, creates no turn, supplies no model, and reads no private Codex database or rollout. Review launched no Codex/provider process.

One start, post-restart public reads, and same-ID resume establish lifecycle continuity. `thread/list` returning zero rows remains truthfully `BLOCKED_ZERO_TURN`; no recovery or broader lifecycle claim depends on list membership.

Checks: focused nine on Python 3.10 and 3.12 each passed 8 with 1 gated real-reproduction skip. Exact diff-check passed. Blockers: none.
