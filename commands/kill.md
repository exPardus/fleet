---
description: 'Interrupt a worker if running, then mark it dead. Terminal — only respawn brings it back.'
argument-hint: '<worker-name>'
---

Kill fleet worker `$1`.

**This is terminal.** A `dead` worker is sticky: no log line and no recompute
resurrects it, and the only exit is `fleet respawn $1`.

Before running anything, confirm with the operator that they mean this worker and
not `fleet interrupt $1` (which kills only the current turn and leaves the worker
alive). Once confirmed, run `fleet kill $1` via Bash.
