---
description: ~20-line digest of a worker's current or last turn. Works mid-turn.
argument-hint: <worker-name> [-n 20]
allowed-tools: Bash(fleet:*)
---

!`fleet peek $ARGUMENTS`

Summarize what this worker is doing right now in two sentences. Do not speculate
beyond what the digest shows.
