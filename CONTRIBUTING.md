# Contributing

## Dev setup

- **Python 3.10+.** The floor is declared once as `fleet.MIN_PYTHON_VERSION` and `TestInterpreterFloor` checks every restatement of it (including the prose in `SPEC.md`) against that constant. This project's dev machine drives `py -3.13`, but 3.13 is a *preference*, not a requirement.
- `bin/fleet.py` is stdlib-only, single file. No pip dependencies get added to it or to the hook scripts under `bin/hooks/`.
- Claude Code CLI ≥ 2.1.202 if you're running live-integration tests (pin-tested at 2.1.217).
- **Windows and Linux are both supported and both verified.** macOS shares the POSIX backend but has no receipt in this repo yet.

## Running the tests

```
py -3.13 -m pytest tests/
py -3.10 -m pytest tests/     # the declared floor — run this too, before you push
```

That runs the default tiers: unit (registry/parser/prompt logic, no `claude` invoked) and hooks (subprocess tests against the real hook scripts, still no `claude`). Both are fast — around a minute.

**Run the floor, don't grep for it.** Twice now a change has shipped a 3.11+ API past a careful grep — `datetime.fromisoformat("…Z")` once and `BaseException.add_note` a second time — and both were caught only by *executing* the suite on 3.10. A version floor you never run at is a claim, not a constraint.

A third tier exists: live integration (`tests/integration/`), gated behind `FLEET_LIVE=1`. It spends real (small, haiku-model) money dispatching an actual worker in a temp `FLEET_HOME` sandbox, and is required — not optional — before merging any change to `dispatch_bg`, the hook scripts, or the outcome-store parsers:

```
FLEET_LIVE=1 py -3.13 -m pytest tests/integration/
```

It's skipped cleanly (not failed) when `FLEET_LIVE` isn't set, so your default `pytest tests/` run never spends money by accident.

## Binding rules

These aren't style preferences — violating them breaks the tool on this platform or defeats a safety property the design depends on. They're enforced by lint tests, not just written down:

- **Forward slashes in hook commands.** Anything written into `worker-settings.json` (or its template) that Git Bash's `sh -c` will parse must use forward slashes — backslashes get eaten.
- **Never launch background processes via Git-Bash `&`.** Use detached `Popen` flags or `Start-Process`; a `&`-backgrounded process under Git Bash does not survive the way you'd expect on Windows.
- **Runtime dirs stay gitignored.** `state/`, `logs/`, `mailbox/` never get tracked; `knowledge/` always does — it's fleet's persistent memory, not scratch space.
- **Views are read-only, always.** The statusline and the `/fleet:*` slash commands must never take `fleet.lock`, never probe a PID, never write anything, and never quarantine a corrupt registry — they read `fleet.status_snapshot()` and exit 0, full stop. See `docs/specs/terminal-surface.md`. A lint in `tests/test_terminal_surface.py` checks this.
- **Fleet never injects itself into a session.** The plugin ships no hooks (terminal-surface D7). A plugin hook runs in *every* session on the machine, including every unrelated project — which is exactly how the old SessionStart briefing leaked this fleet's operator gates and worker table into other people's repos. Surfaces are pull-only; a test asserts the manifest has no `hooks` key.
- **Mutating slash commands are prompt templates, never inline `` !`cmd` ``.** Inline exec substitutes before the model ever sees the prompt — no permission prompt, no confirmation. `fleet kill` and `fleet clean` are irreversible, so the commands that can trigger them must route through the model so the normal permission gate applies. Also lint-enforced in `tests/test_terminal_surface.py`.
- **A plugin can't ship a `statusLine`** (a Claude Code platform constraint, not fleet's choice). `fleet init --statusline` installs fleet's separately, and refuses to clobber a statusline it doesn't own.

`CLAUDE.md` at the repo root carries the authoritative, current version of these rules — if this file and that one ever disagree, `CLAUDE.md` wins and this file has drifted.

## How review works here

Every non-trivial spec or code change goes through an adversarial review before it's considered done — a second, independent pass whose explicit job is to attack the work, not rubber-stamp it. This isn't a suggestion; campaign process requires it, and it has caught real bugs that green test suites missed. Two examples worth reading before you open a PR:

- [`docs/reviews/SPEC-PORTABILITY-REVIEW-2026-07-10.md`](docs/reviews/SPEC-PORTABILITY-REVIEW-2026-07-10.md) — five hostile review passes against the portability spec, including a live WSL repro, surfacing 19 findings (1 critical) across two fix waves.
- [`docs/reviews/c2-review-adversarial.md`](docs/reviews/c2-review-adversarial.md) — an adversarial pass against shipped code that found a HIGH-severity double-launch race a code-conformance review had missed.

`docs/reviews/` has the full history. If you're touching architecture, expect (and please invite) the same scrutiny: state exactly what you changed, why it doesn't violate one of `docs/SPEC.md`'s nine numbered invariants, and don't be surprised if a reviewer tries to break it before it merges.

## PR expectations

- Run `py -3.13 -m pytest tests/` green before opening a PR. If your change touches `dispatch_bg`, `bin/hooks/*`, or an outcome-store parser, also run the `FLEET_LIVE=1` tier and say so in the PR description.
- Say which of `docs/SPEC.md`'s numbered invariants your change touches, and why it's still preserved, if it touches the core lifecycle at all.
- Keep `bin/fleet.py` stdlib-only — no new dependencies.
- Small, focused PRs beat large ones. This is a solo-maintainer project with a heavy review culture; a PR that's easy to attack adversarially is a PR that merges faster.
