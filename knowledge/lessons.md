# Lessons

Current operating notes are kept concise in this file. Historical and
oversized entries are stored verbatim in `docs/archive/lessons-history.md`,
which is not loaded.

## 2026-09-11 — the docs-currency surface is docs/, skills/ and knowledge/

Operator ruling. `tests/test_docs_currency.py` accepted only `docs/`, so a `bin/` change
documented in `skills/fleet/SKILL.md` (the operating manual since 314ea3e) or in
`knowledge/projects/<p>.md` (where the brief template sends host facts) failed the lint while
being properly documented. Ruled B over amending and force-pushing the commit that exposed it.
