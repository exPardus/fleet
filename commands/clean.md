---
description: 'Remove dead workers and their logs, mailboxes, and journals. Destructive and irreversible.'
---

Clean dead fleet workers.

**This deletes files.** It removes every `dead` worker's registry entry, its
`.jsonl` and `.err` logs plus rotated `.jsonl.1`/`.err.1`, its mailbox and any
orphaned claim files, and its journal.

First run `fleet status` via Bash and show the operator exactly which workers are
`dead` and will be swept. Ask for confirmation. Only then run `fleet clean`.

A journal is the only record of what a worker learned. If any dead worker's journal
looks worth keeping, say so before sweeping it.
