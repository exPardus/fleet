---
description: 'Steer a worker — mid-turn message delivered at the next tool boundary, or a new turn if idle.'
argument-hint: '<worker-name> <message|@file>'
---

Send a message to a fleet worker: `$ARGUMENTS`

Run `fleet send $ARGUMENTS` via Bash.

If the worker is mid-turn the message lands at its next tool boundary (seconds).
If it is idle, this starts a new turn. If it is attached, the message queues until
the next headless turn — say so, because fleet hooks do not fire during attach.
