# Contributing

## Development setup

Fleet supports Python 3.10 and newer. `bin/fleet.py` and hook scripts are
stdlib-only. Live integration requires a compatible Claude Code CLI; default
tests never start a provider process or spend money.

Run targeted tests on both supported verification interpreters:

```sh
uv run --no-project --python 3.10 --with pytest python -m pytest -q <test-files>
uv run --no-project --python 3.12 --with pytest python -m pytest -q <test-files>
```

Live integration under `tests/integration/` is explicitly gated by
`FLEET_LIVE=1` and must use a temporary `FLEET_HOME`.

## Binding rules

- Keep hook command paths slash-normalized on every platform.
- Do not launch background work with a shell `&`; use the platform adapter.
- Views never lock, probe, write, or quarantine. They read one tolerant status
  snapshot and exit successfully.
- Fleet is pull-only. Plugin surfaces do not inject hooks into unrelated
  sessions, and mutating slash commands remain prompt templates.
- Keep `bin/fleet.py` stdlib-only and compatible with Python 3.10.
- Update the owning public document when behavior changes.
- Tracked files are generic public source. Operator data is local and ignored:
  `state/`, `logs/`, `mailbox/`, `supervisor/`, `docs/lanes/`,
  `knowledge/projects/`, and `knowledge/lessons.md` must not be committed.
- Receipts in `docs/specs/` must reproduce through
  `tools/verify_receipts.py`; use `# live:` only for a deliberate claim about
  the current working tree.

To extend the public hygiene guard with local identifiers, create
`state/leak-denylist.txt` with one literal string per line. Blank lines and
lines beginning with `#` are ignored. The file is local and gitignored; the
guard skips the optional denylist when it is absent.

## Pull requests

Keep changes focused, name the affected lifecycle invariant, include tests on
both interpreters, and request an independent adversarial review for nontrivial
protocol or safety changes.
