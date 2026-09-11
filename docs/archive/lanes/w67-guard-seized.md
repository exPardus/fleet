# Lane w67-guard-seized — seized claims and fresh heartbeats
DONE means: `fleet sup-guard` no longer returns `PAGE claim seized` for a seized claim whose heartbeat is fresh; seized + stale still pages; paired targeted tests pass on Python 3.10 and 3.12; and the interface/spec docs describe the distinction.

## Result

Updated `_sup_guard_decide` so `claimed_via: seize` or `state: seized` is ambiguous only when the heartbeat is stale or unreadable. A fresh seized claim now flows through the ordinary held-claim liveness rules, using the existing `SUPERVISOR_CLAIM_STALE_SECONDS` threshold. The conservative guards for live bodies, busy/unknown status, handoffs, releasing bodies, unavailable unions, and stale seized claims remain unchanged.

The sibling clauses were checked: no other `sup-guard` branch treats a past event as a persistent state. Seized is the sole event marker in this decision function; handoff and release branches represent current in-flight/current-body state and remain conservative.

Predicted targeted movement before running: two tests added in `tests/test_sup_guard.py`; fresh seized output changes from `PAGE claim seized` to the ordinary held-claim result, while stale seized remains `PAGE claim seized`. Citation, effect-table, view-doctrine, and docs-currency pins were expected to stay green.

## Checks

Required targeted guard tests passed on both interpreters:

- Python 3.10: `13 passed` — full log `/tmp/w67-guard-seized-3.10.log`.
- Python 3.12: `13 passed` — full log `/tmp/w67-guard-seized-3.12.log`.

Expanded targeted pins (`test_sup_guard`, self-citations, doctrine citations, docs currency, view doctrine, Round 7 defect pins, and liveness readers) also passed on both interpreters: `166 passed, 2 skipped`. Full logs: `/tmp/w67-guard-seized-pins-3.10.log` and `/tmp/w67-guard-seized-pins-3.12.log`. The first attempt at this expanded command passed all paths as one zsh argument and ran no tests; the corrected command was then run and is the result reported here, with no project effect from the malformed attempt.

`env UV_OFFLINE=1 UV_CACHE_DIR=/tmp/w64-initrepo-uv-cache python tools/repoint_self_citations.py 45d453f` repointed 3 of 51 positional self-citations and accepted the unchanged citation count. `git diff --check` and `python3 -m py_compile bin/fleet.py` passed.

Blocker: this snapshot's Git metadata is read-only, so the supervisor must commit the listed paths. No live fleet home, tmux, or outside project was touched.

APPEND TEXT — `docs/CHANGELOG.md`:

`2026-09-11 — w67-guard-seized: sup-guard treats seized claims as ambiguous only while their heartbeat is stale or unreadable.`

PATH LIST (supervisor commit scope):

- `bin/fleet.py`
- `tests/test_sup_guard.py`
- `docs/SPEC.md`
- `docs/operator/server-interface-profile.md`
- `docs/PLAN-PROGRESS.md`
- `docs/lanes/w67-guard-seized.md`
- `state/journals/w67-guard-seized.md`
