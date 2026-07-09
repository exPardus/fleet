---
description: Resume workers parked on a Claude plan usage limit whose reset horizon has passed.
argument-hint: [worker-name] [--force-now]
---

Resume usage-limit-parked fleet workers: `$ARGUMENTS`

Run `fleet resume-limited $ARGUMENTS` via Bash.

This relaunches only `limited` workers whose `limit_reset_at` has passed, through
the ordinary lock-guarded launch path with their mailbox and journal drained into
the prompt. It skips workers still before their reset horizon, and workers whose
reset horizon is unknown (`limit_reset_at: null`) unless `--force-now` names them.

A `weekly` park can last days. Do not `--force-now` past an unknown horizon without
the operator explicitly asking — it will just hit the wall again.
