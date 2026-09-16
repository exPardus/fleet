# w88 — sup-guard reads blocked daemon corpses as a second live body

DONE means: `sup-guard` never `PAGE`s "another live supervisor body is present" for a
`state: blocked`, no-pid roster row, and the keeper does not page `supervisor-stalled`
while a decision is parked; both pinned by tests replaying this host's 09-15 roster.

## Defect 1 — guard: ALREADY FIXED, not reproducible at HEAD
Replayed the exact 09-15 roster (three `sup|inc-...|successor` rows, all `state: blocked,
status: None, pid: None`, claim naming one as its live sid) against `_sup_guard_observe`/
`_sup_guard_decide`. Result: `DISPATCH` (stale) or `PAGE fresh heartbeat but body is not
roster-live` (fresh) — never "another live body"; `claim_sids` is never `[]` (it's the sid
union, non-empty by construction). `_sup_guard_live_rows` drops any row whose pid is in
`(None, "", 0)`, present since the guard's first commit `6327ea9` (2026-09-11, `git log
-S`) — before this incident. No code change; fixture pinned as 2 regression tests, plus a
control proving a genuine live corpse (real pid, outside the sid union) still trips the
arm: the fix is the pid filter, not a disabled arm.

## Defect 2 — keeper: fixed
`rule_supervisor_stalled` now yields to `rule_supervisor_frozen` (returns `None`) when
`obs["pending_decision"]` is truthy, only on the plain-`PAGE` branch. `DISPATCH` and `PAGE
supervisor limited` still page through: a dead/limited body can't answer the decision, so
DISPATCH still gets a replacement running and limited still respects its reset horizon.
Dedup (`dedup()`/`save_state`): fingerprint-keyed, atomically written, no bug found — two
existing tests already pin a stable fingerprint. The 09-15 repeats at 19:12Z/21:0xZ are
explained by `reason` legitimately changing across three live fork-steers (new diagnosis,
correctly a new page); only 21:1xZ, after the decision was parked with reason unchanged,
was the actual bug this fix removes.

## Tests / Docs
New: 2 fixture tests + 1 corpse control + 1 guard-through-keeper integration test
(`tests/test_sup_guard.py`); 3 pure-rule tests (`tests/test_keeper_rules.py`). Guard/keeper/
views suites, both interpreters: 407 passed, 2 skipped, 0 failed. Full floor (claim, not
gate): 3.10, 6 failed/5345 passed/16 skipped — same 6 pre-existing venv-artifact failures
as w87's floor claim, untouched by this lane. Updated `keeper-wake.md`'s table with the
pending-decision exception; `docs/SPEC.md` G-K8 C prose still accurate, unchanged. Re-ran
`tools/verify_receipts.py` on all 9 `docs/specs/**` files citing `bin/fleet.py`/
`bin/fleet_keeper.py`: all PASS (2 pre-existing unrelated WARNs, volatile-tagged).

## Blockers: none.
