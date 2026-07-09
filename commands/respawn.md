---
description: 'Fresh session for a worker — same name, cwd, mode; journal and drained mailbox carried over. The context-reset lever.'
argument-hint: '<worker-name> [--task <text>] [--force]'
---

Respawn fleet worker: `$ARGUMENTS`

Run `fleet respawn $ARGUMENTS` via Bash.

This mints a new session id and rebuilds context from the worker's journal plus its
drained mailbox — lossless if the journal is current. It refuses while a turn is
running unless `--force` (which interrupts first), and refuses a launch-in-flight
claim even with `--force`.

It also rotates the log. If rotation fails because a follower holds the log handle,
the respawn fails cleanly with no session swap — report that verbatim rather than
retrying blindly.
