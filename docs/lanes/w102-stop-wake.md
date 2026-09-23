# w102 stop wakes supervisor

DONE means: one bounded completion line and idle wake for the exact live claim holder; no delivery to absent, dead, released, or stale claims; both interpreter floors and base comparison recorded.

A worker's allowed Stop reports completion to the current supervisor that spawned it. The hook skips the bridge when no current claim holder matches `spawned_by`. Idle Codex observations use the same bridge. Supervisor-shaped source rows never notify, preventing successor and self-Stop loops. A per-turn marker suppresses duplicate mail and wakes; failed sends clear it for retry. The bridge sends `LANE-DONE <name> <status> <head-or-none>` through the existing supervisor send path, so a busy body receives mail and an idle body wakes. Released, stale, mismatched, and dead claims are ignored. Hook failure permits Stop and records one error line.

Checks: targeted tests: 147 passed, 3 skipped on Python 3.10 and 3.12. Review full suite on 3.12: 5,670 passed, 71 failed, 18 skipped, 3 xfailed. Base `0ee3e67` has the same 71 failing test IDs. Local pytest was used because `uv` could not use its read-only cache or fetch packages; 44 base failures are Codex host tests whose child host exits before ready in this sandbox.
