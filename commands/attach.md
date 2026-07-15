---
description: 'Open an interactive terminal on a worker''s session — full TUI, whole history.'
argument-hint: '<worker-name> [--force]'
---

Attach an interactive terminal to fleet worker: `$ARGUMENTS`

Run `fleet attach $ARGUMENTS` via Bash.

This opens a real Claude Code TUI in a separate window (Windows Terminal, or a
PowerShell fallback). It refuses while a turn is running unless `--force`, which
interrupts the turn first.

Two things the operator must know: the attached TUI runs **without** fleet's
`--settings`, so fleet hooks do not fire and any mail queues until the next headless
turn; and closing the tab does not detach — they must run `fleet release <name>`.

Native (daemon-hosted) workers: `fleet attach` refuses outright (M-B scope fence) and
tells you the alternative — the agents menu (`Ctrl+T` in claude) or `claude attach
<sid>` directly.
