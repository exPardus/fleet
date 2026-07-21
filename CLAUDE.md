# claude-fleet

System-wide tool: one Claude Code manager session spawns, monitors, steers, and hands off multiple worker sessions across projects on this machine.

**Start here: `docs/SPEC.md`** — the approved v2 design (post adversarial review; the appendix records every finding and its fix — do not re-litigate them). Build against it milestone by milestone (M1–M5, §13).

Rules:
- Python is `py -3.13` (bare `python` resolves to 3.10). `bin/fleet.py` is stdlib-only, single file.
- Hook commands in `worker-settings.json` use FORWARD slashes (Git Bash `sh -c` eats backslashes).
- Never launch background processes via Git-Bash `&` — detached Popen flags or Start-Process only.
- Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored; `knowledge/` is git-tracked.
- Tests: pytest for unit/hook tests (SPEC §12); integration tests use a haiku worker in a temp dir.
- Views (statusline, `/fleet:*`, SessionStart hook) never take `fleet.lock`, never probe a PID, never write, and never quarantine a corrupt registry — they read `fleet.status_snapshot()` and exit 0. See `docs/specs/terminal-surface.md`.
- Mutating slash commands are prompt templates, never inline `` !`cmd` `` — inline exec skips the permission prompt, and `fleet kill`/`fleet clean` are irreversible. A lint in `tests/test_terminal_surface.py` enforces this.
- A plugin cannot ship a `statusLine`; `fleet init --statusline` installs it, refusing to clobber a foreign one.
- Every pasted receipt in `docs/specs/**` is re-executed and diffed by `tools/verify_receipts.py`, enforced by `tests/test_receipts.py`. A pasted command+output block is a claim until something re-runs it. Mark a receipt whose evidence lives outside the repo `# volatile`; a receipt the harness cannot classify is a failure, never a skip. Run `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/<file>.md` before trusting a green run — a verifier without its own seed test proves nothing.
