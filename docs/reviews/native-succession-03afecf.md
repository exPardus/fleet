# RED — native supervisor succession rereview

**Head:** `03afecf0806d7883e89bf32ed8521e4b47999b4d` atop `a37d519b855e16dfe2625e97f31e802a4f8a5862`.

**Verdict:** RED. The repair rejects predecessor/all-row thread-ID reuse, performs an exact idle/zero-turn public read before transfer, rechecks row uniqueness under lock, and requires one active full-view matching turn before `held`. Reused/nonempty threads freeze the predecessor pre-transfer. Ordinary incomplete/wrong response shapes remain `activating`; succession and reconcile gates otherwise remain intact.

**Blocker:** One exception handler cannot distinguish `HostRejected` from `turn/start` versus the subsequent verification `thread/read`. A probe let `turn/start` return success, then rejected only the post-start read. Fleet reported activation uncertainty but called rollback: the claim became predecessor `held` and the successor row was deleted despite a proven live successor turn. A retry can therefore create another supervisor turn. Roll back only a rejection of `turn/start`; every post-acceptance read failure must preserve `activating`/uncertain and refuse retry.

**Checks:** Fail-fast `claude`/`mcx` stubs; focused suites passed on Python 3.10 and 3.12 (`171 passed` each); diff check passed. No provider launched.
