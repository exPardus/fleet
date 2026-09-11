# Lane w66-guard — `fleet sup-guard`
DONE means: `fleet sup-guard` emits exactly one `DISPATCH`, `WAKE <name>`, or `PAGE <reason>` verdict from claim/union/roster/handoff state, and `--do` re-verifies before only the permitted action.

Implemented the interface two-live-body guard in `bin/fleet.py`.

- Bare `sup-guard` is a lock-free/read-only view using `status_snapshot()` plus the claim-holder sid union, roster PIDs, pending handoff state, and `supervisor/HANDSHAKE`.
- A stale-claim live idle body, including one visible only under `retired_sids`, yields `WAKE <body>`; a stale held claim with no live body yields `DISPATCH`.
- Seized/unknown claims, fresh-heartbeat gaps, busy or unknown live status, handoffs, releasing-live bodies, unavailable unions, and other ambiguous states yield `PAGE <reason>`.
- `--do` performs a second complete observation immediately before acting. `DISPATCH` invokes `sup-spawn` with `@supervisor/briefs/server-standing.md` and `project,local`; `WAKE` sends that brief to logical `supervisor`; `PAGE` performs no action. Action chatter is suppressed so stdout stays one line.
- The D4 view pin now includes `sup-guard`; its ordinary/terminus classifications are pinned in the existing verb tests. The operator docs and SPEC command table describe the verb. The confirmation policy is drafted in the interface profile, not raised as an operator gate: confirm the printed verdict before `--do`, especially `DISPATCH`.

Checks:

- Python 3.10 targeted guard/claim/hand-off/spawn/view set: 230 passed, 2 skipped.
- Python 3.12 same set: 230 passed, 2 skipped.
- Python 3.10 citation/verb-effect/home-resolution/guard/view pins: 206 passed, 2 skipped.
- Python 3.12 citation/verb-effect/home-resolution/guard/view pins: 206 passed, 2 skipped.
- Final guard/view smoke: 26 passed, 2 skipped on each Python 3.10 and 3.12.
- Final post-registry-guard pins (`sup_guard`, self-citations, effect-table, view doctrine): 110 passed, 2 skipped on each Python 3.10 and 3.12.
- `git diff --check` and `py_compile` pass. `tools/repoint_self_citations.py 1556986` ran before the three new sid-union citations; current citation tests are green. Because the citation count increased, the supervisor owes one merge-tree fixpoint pass after sibling `w66-wave-close` merges.

Blockers: no implementation blocker. Sandbox prohibits commit/add/push; supervisor must commit and perform the post-merge citation fixpoint. `docs/CHANGELOG.md` is append-only; append the line supplied below.

APPEND TEXT for `docs/CHANGELOG.md`:

`2026-09-11 — w66-guard: fleet sup-guard now emits one lock-free two-live-body verdict and --do re-verifies before standing-brief wake/dispatch.`

PATH LIST (supervisor commit scope):

- `bin/fleet.py`
- `docs/PLAN-PROGRESS.md`
- `docs/SPEC.md`
- `docs/specs/multi-fleet.md`
- `docs/operator/server-interface-profile.md`
- `tests/test_round7_defect_pins.py`
- `tests/test_sup_guard.py`
- `tests/test_views_doctrine.py`
- `docs/lanes/w66-guard.md`
- `state/journals/w66-guard.md`
