# w65-verbs — journal board roll and interface registration
DONE means: `fleet journal-roll` retains the newest three CHECKPOINT entries,
losslessly appends older entry bytes to stable journal history, and is invoked by
`sup-checkpoint`; `fleet interface-register` validates and idempotently registers
the tmux pane; lane-targeted checks pass on Python 3.10 and 3.12.

- **Outcome:** both ritual steps are implemented in `bin/fleet.py`. Journal
  history uses the stable append-only sink
  `supervisor/journal-history/journal-roll.md`, avoiding the existing dated
  range filename becoming ambiguous. The roll partitions the original bytes,
  preserves the board seed and newest entries, and refuses malformed UTF-8 or
  entry-looking headers before changing either file. `sup-checkpoint` runs the
  roll inside its existing lock immediately after append. The interface verb
  accepts only the keeper’s `%<ASCII decimal>` pane shape, verifies the pane,
  repairs its window name to `fleet`, and writes `state/interface-pane` only
  after tmux succeeds; unset or invalid `TMUX_PANE` is a clear refusal.
- **Prediction before tests:** the new journal/interface tests and the
  supervisor `journal_board` pin should pass on both floors; self-citation,
  effect-tier, terminal-surface, and docs-currency pins were expected to be the
  touched regression surfaces.
- **Checks:** new lane tests: **10 passed** on Python 3.10 and **10 passed** on
  Python 3.12. `tests/test_supervisor.py -k journal_board`: **1 passed** on
  both floors. `tests/test_self_citations.py`: **17 passed** on both floors.
  Effect-tier plus docs-currency pins: **72 passed** on both floors.
  `git diff --check` and `python3 -m py_compile bin/fleet.py` pass.
- **Citation repair:** the pre-existing insertion had stale positional
  self-citations. `tools/repoint_self_citations.py 07042d5` repointed 36 of 48
  citations; the self-citation suite is green on both floors afterward.
- **Known environment blocker:** the first mandated offline uv cache was empty;
  the required commands succeeded with the existing `/tmp/w64-initrepo-uv-cache`.
  The broader terminal-surface run still has its two known copied-interpreter
  host-assumption failures on each floor (`test_fleet_python_*`); those failures
  are unrelated to this lane. No full suite was run.
- **Scope:** `bin/fleet_keeper.py`, live `supervisor/JOURNAL.md`,
  `knowledge/lessons.md`, and live `docs/CHANGELOG.md` were not edited. No live
  fleet verb, `sup-boot`, tmux input, git index/ref mutation, or sub-worker was
  used. No gate box was raised or ticked.
- **Changelog append text (do not rewrite the live file):**
  `2026-09-10 — Added idempotent interface pane registration and automatic, lossless supervisor journal board rolling via fleet ritual verbs.`

## PATH LIST — every worktree file created or modified

- `/home/altai/proga/fleet-w65-verbs/bin/fleet.py`
- `/home/altai/proga/fleet-w65-verbs/docs/PLAN-PROGRESS.md`
- `/home/altai/proga/fleet-w65-verbs/docs/SPEC.md`
- `/home/altai/proga/fleet-w65-verbs/docs/specs/multi-fleet.md`
- `/home/altai/proga/fleet-w65-verbs/docs/lanes/w65-verbs.md`
- `/home/altai/proga/fleet-w65-verbs/tests/test_journal_roll.py`
- `/home/altai/proga/fleet-w65-verbs/tests/test_interface_register.py`
- `/home/altai/proga/fleet-w65-verbs/tests/test_round7_defect_pins.py`
- `/home/altai/proga/fleet-w65-verbs/tests/test_terminal_surface.py`
- `/home/altai/proga/fleet-w65-verbs/state/journals/w65-verbs.md`
