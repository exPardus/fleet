---
description: 'Stop a worker''s currently running turn and mark it interrupted. The worker does not die.'
argument-hint: '<worker-name>'
---

Interrupt the running turn of fleet worker `$1`.

Run `fleet interrupt $1` via Bash.

Legacy (pre-native-pivot) workers: this kills the turn's process tree; the transcript
up to the kill persists and the worker is marked idle, resumable with `fleet send` or
`fleet respawn`.

Native (daemon-hosted) workers: this runs `claude stop` and marks the worker
`interrupted` (never `idle` -- an interrupted task is definitionally started, so
resuming it is never automatic). Respawn is a separate, explicit decision:
`fleet respawn $1`. Confirm what the worker was doing (via `fleet peek $1`) before
interrupting it.

Interrupt only ever fires on a worker whose last known status is actually a live
running turn. A `dead`/`interrupted`/`idle` worker is a friendly no-op (nothing to
stop); a `limited`/`dead-suspected`/parked worker refuses loudly instead of
silently overwriting its status -- `fleet status $1` first if unsure.
