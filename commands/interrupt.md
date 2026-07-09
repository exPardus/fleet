---
description: 'Kill a worker''s currently running turn. The transcript survives; the worker does not die.'
argument-hint: '<worker-name>'
---

Interrupt the running turn of fleet worker `$1`.

Run `fleet interrupt $1` via Bash.

This kills the turn's process tree. The transcript up to the kill persists and the
worker can be resumed with `fleet send` or continued with `fleet respawn`. Confirm
what the worker was doing (via `fleet peek $1`) before interrupting it.
