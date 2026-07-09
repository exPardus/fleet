---
description: 'Final result text of a worker''s last completed turn, nothing else.'
argument-hint: '<worker-name>'
allowed-tools: 'Bash(fleet result:*)'
---

!`fleet result $1`

Relay the result. If it reports a blocker, say what would unblock it.
