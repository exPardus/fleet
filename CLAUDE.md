# claude-fleet

System-wide tool: one Claude Code manager session spawns, monitors, steers, and hands off multiple worker sessions across projects on this machine.

**Start here: `docs/SPEC.md`** — the approved v2 design (post adversarial review; the appendix records every finding and its fix — do not re-litigate them). Build against it milestone by milestone (M1–M5, §13).

Rules:
- Python is `py -3.13` (bare `python` resolves to 3.10). `bin/fleet.py` is stdlib-only, single file.
- Hook commands in `worker-settings.json` use FORWARD slashes (Git Bash `sh -c` eats backslashes).
- Never launch background processes via Git-Bash `&` — detached Popen flags or Start-Process only.
- Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored; `knowledge/` is git-tracked.
- Tests: pytest for unit/hook tests (SPEC §12); integration tests use a haiku worker in a temp dir.
