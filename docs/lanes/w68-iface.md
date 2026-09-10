# w68-iface
DONE means: every home has `state/interface/{board.md,log.md}`; bare `fleet init` registers its caller and prints the startup ritual; session-id registration works outside tmux; the keeper names an unregistered interface instead of creating a window.

Implemented home-scoped interface state in `bin/fleet.py`.

- `board.md` is refreshed from durable supervisor, registry, journal, task,
  and interface-log evidence. It reports `UNMEASURED` where no source exists.
- `log.md` is append-only for register, relay, ruling, wake, and spawn events.
- Bare repo init creates/upgrades interface state, registers `TMUX_PANE` in
  tmux or `CLAUDE_CODE_SESSION_ID` outside it, and prints board, supervisor,
  inbox, and ruling status. A plain shell with neither identity remains usable.
- `fleet_keeper.py` recognizes session registration and pages the fact of an
  unregistered home rather than creating a window.

Computed board fields: supervisor state, working registry names, latest numbered
`THROUGHPUT` line, ruling task paths, and latest relayed wave. Human-written
fields: none; missing evidence is rendered `UNMEASURED`, never guessed.
`log.md` is strictly append-only; board refreshes never rewrite the log.

Checks: `py_compile` passed on Python 3.10 and 3.12; throwaway-home init,
outside-tmux registration, idempotent second init, and no-registration keeper
drive passed. The requested `-k init` command: 9 passed, 105 deselected on
both Python 3.10 and 3.12. Complete `tests/test_keeper*.py` glob plus
interface pins: 228 passed, 1 skipped on each interpreter. The new pins plant
both an unrelated fresh claim (init succeeds) and a target-home fresh claim
(§7 continuity refusal); results do not depend on an ambient claim.

Init gate rule: §7 evaluates the home being initialized; a different new home
is ungated, while init of the claim-holding home remains gated unchanged.

Initialized homes with no registration page through `work:fleet` without
calling `ensure_window`; legacy homes lacking `state/interface/` retain their
pre-interface fallback while init upgrades them.

Full logs: `/tmp/w68-iface-py310-init-followup.log`,
`/tmp/w68-iface-py312-init-followup.log`, `/tmp/w68-iface-py310-keeper-final.log`,
`/tmp/w68-iface-py312-keeper-final.log`, and `/tmp/w68-iface-repoint-final.log`
(repointed 39/51 citations; citation suites: 26 passed on each interpreter).
