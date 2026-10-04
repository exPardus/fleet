---
description: 'Read-only GitHub pull-request head polling.'
allowed-tools: 'Bash(fleet pr-poll:*)'
---

!`fleet pr-poll $ARGUMENTS`

Use `/fleet:pr-poll <PR> --since <SHA>` to compare a recorded commit with the
pull request's current `headRefOid`. Add `--json` for script consumption or
`--repo OWNER/REPO` when `gh` cannot infer the repository. The command invokes
the GitHub CLI once with a 15-second timeout, never updates the recorded SHA,
and never writes fleet state. PR and repository selectors are capped at 512
characters.
