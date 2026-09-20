# RED — native supervisor succession review

**Head:** `a37d519b855e16dfe2625e97f31e802a4f8a5862` on `c2e645d199c7ec7260647b6246fc55af5fad6dd9`.

**Verdict:** RED. Checkpoint and releasing-terminal reads are full/newest and claim-bound; transfer precedes one `turn/start`; stale predecessors are refused; reconcile uses only resume/read and freezes ambiguity; mail, IDs, status/limit, usage, and result fields remain preserved. Released guard performs no provider call. The plan accurately marks predecessor interruption/retirement and activating-state restart adoption unsupported.

**Blocker:** Handoff never proves `thread/start` returned a new, empty successor. Adversarial responses containing an existing completed turn were accepted and promoted `held`. Returning the predecessor thread ID was also accepted, producing two registry rows for one thread and a held claim that `_codex_supervisor_binding` immediately refuses as ambiguous. Require a distinct thread ID plus an exact empty-thread read before transfer, then prove exactly one matching turn before promotion.

**Checks:** Fail-fast `claude`/`mcx` stubs; focused suites passed on Python 3.10 and 3.12 (`166 passed` each); diff check passed. No provider launched.
