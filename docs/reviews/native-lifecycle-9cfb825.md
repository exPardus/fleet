# GREEN — native supervisor lifecycle rereview

**Head:** `9cfb8255786f973c684e833c3e89dcad93c75dc7` atop `b50e5dd104342e2927c575e620e8c94180abd759`.

**Verdict:** GREEN. Guard and send require `itemsView=full`, a unique bound turn, and that turn as the newest returned turn. Independent `notLoaded`, `summary`, and newer-turn probes refused before steer/wake; queued mail and claim/registry bytes were preserved, with only the local reservation removed. Prior exact-home/claim/row authorization, file-only status, connect-existing reads/results, active steer versus idle wake, durable reservation/recovery, stale/wrong-home refusal, genuine returned IDs, and default Claude/mcx compatibility remain covered.

**Checks:** Fail-fast `claude`/`mcx` stubs preceded every run. Focused supervisor/IPC/guard suites passed on Python 3.10 and 3.12 (`126 passed` each); native-worker compatibility passed (`27 passed`). `git diff --check b50e5dd..9cfb825` passed. No provider process launched.

**Blockers:** None.

**Next:** Land `9cfb825` only.
