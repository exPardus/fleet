# claude-fleet

System-wide tool: one Claude Code manager session spawns, monitors, steers, and hands off multiple worker sessions across projects on this machine.

**Start here: `docs/SPEC.md`** — the v3 spec of record, descriptive of the post-pivot `bin/fleet.py` (the v1→v2.3 body, including the F1–F33 finding record, is moved verbatim to `docs/SPEC-v2-history.md` — do not re-litigate it). Milestones are §18: M-0/M-A/M-B/M-C shipped there; M-D and M-E shipped after and are **not yet folded into §18** — read `docs/PLAN-PROGRESS.md` and `docs/NEXT-SESSION.md` for anything past M-C. Open operator decisions live in `docs/OPERATOR-GATES.md`.

Rules:
- Python is `py -3.13` (bare `python` resolves to 3.10) — that is this machine's *preference*, not the floor. The floor is `fleet.MIN_PYTHON_VERSION` (3.10), declared once and checked everywhere by `TestInterpreterFloor`; `bin/hooks/run_py.sh` may select any interpreter at or above it, so **changes must run on 3.10** (`py -3.10 -m pytest -q`), not only on 3.13. `bin/fleet.py` is stdlib-only, single file.
- Hook commands in `worker-settings.json` use FORWARD slashes (Git Bash `sh -c` eats backslashes).
- Never launch background processes via Git-Bash `&` — detached Popen flags or Start-Process only.
- Runtime dirs `state/`, `logs/`, `mailbox/` are gitignored; `knowledge/` is git-tracked.
- Tests: pytest for unit/hook tests (SPEC §12); integration tests use a haiku worker in a temp dir.
- Views (statusline, `/fleet:*`, SessionStart hook) never take `fleet.lock`, never probe a PID, never write, and never quarantine a corrupt registry — they read `fleet.status_snapshot()` and exit 0. See `docs/specs/terminal-surface.md`.
- Mutating slash commands are prompt templates, never inline `` !`cmd` `` — inline exec skips the permission prompt, and `fleet kill`/`fleet clean` are irreversible. A lint in `tests/test_terminal_surface.py` enforces this.
- A plugin cannot ship a `statusLine`; `fleet init --statusline` installs it, refusing to clobber a foreign one.
- Every pasted receipt in `docs/specs/**` is re-executed and diffed by `tools/verify_receipts.py`, enforced by `tests/test_receipts.py`. A pasted command+output block is a claim until something re-runs it. Run `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/<file>.md` before trusting a green run — a verifier without its own seed test proves nothing.
- **A receipt is a claim about a commit, not about `HEAD`.** Every fenced receipt block carries `# at <sha>` and is verified against that commit's materialised tree, so an unrelated change to `bin/fleet.py` cannot rot it and re-pinning is a deliberate edit. A moving pin (`# at HEAD`) and an absent commit are both errors. `# volatile: <reason>` = evidence lives outside the repo (drift warns; the test skips it); `# live: <reason>` = deliberately about the working repo (e.g. `git check-ignore`). A receipt the harness cannot classify is a failure, never a skip.
