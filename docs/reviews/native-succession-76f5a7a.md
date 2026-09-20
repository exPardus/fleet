# GREEN — native supervisor succession final rereview

**Head:** `76f5a7aeafa482214d901963ac51c5508c4fa948` atop `03afecf0806d7883e89bf32ed8521e4b47999b4d`.

**Verdict:** GREEN. A direct `turn/start` `HostRejected` alone restores the predecessor and removes the unstarted successor. Once `turn/start` returns, response parsing and public verification use a separate failure path: post-read rejection, transport error, incomplete view, wrong turn, or multiple turns preserve successor `activating`/uncertain, predecessor `retiring`, and the pending operation. A repeated handoff refuses before any provider call, so no second turn is issued.

Distinctness from predecessor and every registry row, the exact idle/zero-turn read before transfer, lock-held collision recheck, and exactly one active full-view matching returned turn before `held` remain enforced. Checkpoint, release, stale-predecessor, reconcile-only-resume/read, mail/evidence preservation, and released-guard behavior remain intact.

**Checks:** Fail-fast `claude`/`mcx` stubs; focused suites passed on Python 3.10 and 3.12 (`173 passed` each). Independent post-acceptance error/incomplete/mismatch matrix passed; `git diff --check` passed. No provider launched.

**Blockers:** None.
