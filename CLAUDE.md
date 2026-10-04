# claude-fleet

The document for a surface states what that surface is for and how to use it.
Code is the behavioural authority. Update the owning document when described
behaviour changes; otherwise report `Docs: n/a -- <reason>`.

Start with `docs/SPEC.md`. Milestones are in §18. Tracked files contain only
generic product, design, and implementation material. Operator data is local
to each fleet home under ignored runtime paths and must never be committed.

Rules:

- Run targeted checks with `uv run --no-project --python 3.10 --with pytest
  python -m pytest -q` and the equivalent 3.12 command. The minimum supported
  version is `fleet.MIN_PYTHON_VERSION` (3.10); the supervisor checks the
  merged tree on 3.10. `bin/fleet.py` is stdlib-only.
- Hook commands in `worker-settings.json` use forward slashes.
- Do not launch background processes with Git-Bash `&`; use detached Popen
  flags or `Start-Process`.
- `state/`, `logs/`, `mailbox/`, `supervisor/`, `docs/lanes/`,
  `knowledge/projects/`, and `knowledge/lessons.md` are local operator data.
  Generic knowledge indexes and playbooks remain tracked.
- Tests use pytest. Integration tests use a worker in a temporary directory.
- Every task brief names its model; use the assigned model and effort.
- Views (statusline and `/fleet:*`) never take `fleet.lock`, probe, write, or
  quarantine a corrupt registry; they read `fleet.status_snapshot()` and exit
  0. `fleet doctor --repair` is the only verb whose purpose is quarantine;
  lock-holding verbs may quarantine through `load_registry`. Pinned by
  `tests/test_views_doctrine.py`.
- Fleet is pull-only: it injects nothing into unrelated sessions.
- Mutating slash commands are prompt templates, never inline `!` commands.
- A plugin cannot ship a `statusLine`; `fleet init --statusline` installs one
  without clobbering a foreign status line.
- Receipts in `docs/specs/**` are re-executed by
  `tools/verify_receipts.py` and checked by `tests/test_receipts.py`. A receipt
  the harness cannot classify is a failure.
- Every receipt block carries `# at <sha>` and is checked against that commit's
  tree. `# volatile: <reason>` marks external evidence; `# live: <reason>`
  marks evidence about the working repository.
