# w102 stop wakes supervisor

DONE means: one bounded completion line and idle wake for the exact live claim holder; no delivery to absent, dead, released, or stale claims; both interpreter floors and base comparison recorded.

A worker's allowed Stop now reports completion to the current supervisor that spawned it. The Stop mailbox hook invokes fleet's `lane-done` bridge after the outcome hook; observed Codex working-to-idle transitions use the same bridge. A per-turn registry marker suppresses duplicate mail and wakes. The bridge sends `LANE-DONE <name> <status> <head-or-none>` through the existing supervisor send path, so a busy body receives mail and an idle body wakes. Released, stale, mismatched, and dead claims are ignored. Hook failure permits Stop and records one error line.

No keeper or guard verdict changed. No deployment was performed.

Checks: targeted Stop, claim, view, notify and interface tests: 141 passed, 3 skipped on each of Python 3.10 and 3.12. Full suite on each: 5,664 passed, 71 failed, 18 skipped, 3 xfailed. Base `0ee3e67` has the same 71 failing test IDs; no new full-suite failure. Pytest came from the local installed package because `uv` could not use its read-only cache or fetch packages.
