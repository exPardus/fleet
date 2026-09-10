# w66-wave-close
DONE means: `fleet wave-close --base <sha> --changelog @<file>` performs the guarded reap, strict two-interpreter fresh-clone floor, throughput landing, journal roll, bounded push, and exact `sup-notify` relay, with unexpected floor results aborting before the close.

## Result

Implemented the orchestration in `bin/fleet.py`. The floor is foregrounded and split from one sorted recursive `tests/**/test_*.py` walk in the fresh clone, including `tests/integration`; each half writes a complete log under `state/wave-close/<wave>/`. The implementation compares both interpreter totals and refuses any failure set other than the six documented host assumptions.

The supervisor supplies only `--base` and `--changelog`; the code derives the repository, wave id, numstat buckets, registry worker count, roster token total (or `UNMEASURED`), journal roll, and push outcome. Progress rows are refreshed only as a count of exact current-wave rows; prose acceptance, priority advancement, and content-bearing rows remain MODEL work.

The sandbox makes Git metadata read-only, so I cannot commit or push or exercise the commit/push arm end-to-end here. The supervisor must commit the lane and rerun the citation fixpoint at merge because `bin/fleet.py` line positions changed. No live fleet home, tmux window, or external project was touched.

## Human/model handoff

- CHANGELOG sentence(s): MODEL, because user-visible wording and commit evidence cannot be derived from a diff.
- Progress-row acceptance and priority advancement: MODEL, because filenames and DONE text do not establish semantic acceptance.
- Expected failure-set maintenance: MODEL/operator, because platform and interpreter-host assumptions may change and must be re-verified rather than silently broadened.
- Effect-table classification: MODEL/operator, because the ratified table does not yet define this new mutating verb; it remains fail-closed as unclassified until the supervisor explicitly ratifies its effect class.

## Checks

Predicted targeted movement before running: parser/CLI wiring, journal-roll compatibility, effect-table unclassified-verb pin, docs currency, self-citations, and the new wave-close unit tests; the full floor is intentionally not run in this lane. Final focused logs: `/tmp/w66-wave-close-final-3.10.log` and `/tmp/w66-wave-close-final-3.12.log`.

Results: `102 passed` on Python 3.10 and `102 passed` on Python 3.12. The expanded affected set also matched on both interpreters at `476 passed, 1 skipped`, with only the two known venv-shim re-exec failures from the documented six-host-assumption floor set; the four drive-qualified-path cases are POSIX-inapplicable here. `python3 -m py_compile bin/fleet.py`, `git diff --check`, and the citation repoint all passed (`4 of 48` positions repointed in the final pass). Full-floor execution is intentionally deferred to the supervisor merge, per lane scope.

APPEND TEXT — `docs/CHANGELOG.md`: `- 2026-09-11 — wave-close: one claim-holder verb now performs the guarded wave boundary, strict fresh-clone floors, throughput landing, bounded push, and exact interface relay.`

PATH LIST (supervisor commits):

- `bin/fleet.py`
- `tests/test_round7_defect_pins.py`
- `docs/SPEC.md`
- `docs/PLAN-PROGRESS.md`
- `supervisor/briefs/server-standing.md`
- `docs/lanes/w66-wave-close.md`
