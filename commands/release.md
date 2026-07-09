---
description: 'Hand an attached worker back to the fleet — attached → idle.'
argument-hint: '<worker-name>'
---

Release fleet worker `$1` back to idle.

Run `fleet release $1` via Bash.

Attach status is sticky and TUI-close detection is unreliable on Windows, so this
explicit release is the only exit. If the worker has mail queued from while it was
attached, `fleet status` will show `idle+mail` afterwards; the next turn drains it.
