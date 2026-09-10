# Append-only landing handoff
DONE means: the supervisor appends the exact entry below against the live changelog at landing.

**APPEND ONLY — do not replace the live docs/CHANGELOG.md from this snapshot.**
The lane deliberately leaves docs/CHANGELOG.md unchanged; the requested update
is handed over as these lines to append, re-derived against the live file.

- 2026-09-10 — Supervisor boot, handoff completion and release automatically reap eligible young rows through autoclean; boot reports the count and carries the three-worker / 1.5 GB dispatch rule. Unread mail, live PIDs and the current claim remain protected. Explicit lane landing and synthetic receipt: docs/lanes/w64-reap.md.

No supervisor/JOURNAL.md or knowledge/lessons.md edits are handed over.
