# Lane w68-caps

DONE means: loaded context prose is compact, caps are pinned, and history is
kept out of the startup load.

Implemented:

- Removed self-correction and receipt narrative from `CLAUDE.md`, the server
  interface profile, and the standing supervisor brief.
- Moved lesson entries verbatim to `docs/archive/lessons-history.md`; the
  loaded lessons file is now a five-line pointer and `knowledge/INDEX.md` is
  15 lines.
- Added `docs/operator/goals-trim-proposal.md`; `supervisor/GOALS.md` was not
  edited and needs an operator PROPOSAL.
- Added `tests/test_prose_caps.py`, including every cap in the brief, and
  updated the D4 test seed for the deleted root-doc sentence.

Green caps: CLAUDE 37/60; profile 64/100; briefs 41/60; loaded knowledge
20/400 with no oversized entries.

Xfails (strict=false): docs total 94,744/15,000 (`w69-docs-cap`); fleet.py
prose 12,314/4,000 (`w69-code-prose`); skills/fleet 707/400
(`w69-skill-caps`); GOALS 133/80 (operator proposal); forbidden-prose lint,
136 matches (`w69-zero-prose`).

Checks: py_compile passed on Python 3.10 and 3.12; archive preservation and
equivalent cap assertions passed; `git diff --check` passed. Pytest could not
run because pytest is absent and uv cannot reach PyPI in this environment.

PATH LIST:

- `CLAUDE.md`
- `docs/operator/server-interface-profile.md`
- `docs/operator/goals-trim-proposal.md`
- `docs/archive/lessons-history.md`
- `knowledge/INDEX.md`
- `knowledge/lessons.md`
- `supervisor/briefs/server-standing.md`
- `tests/test_prose_caps.py`; `tests/test_views_doctrine.py`
- `docs/lanes/w68-caps.md`; `state/journals/w68-caps.md`
