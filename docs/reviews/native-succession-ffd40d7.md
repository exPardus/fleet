# GREEN — Native succession journal settlement review

**Head:** `ffd40d768fc49b8b229ab0505574d9734d89acb9` atop integrated base `44472878184eb62fd75ef0d6418f937242517d97` (immediate parent `69dee0311caa53189babad96142abcfeb16d202a`).

**Verdict:** GREEN. Reconciliation first obtains one complete exact-home, exact-thread, sole-turn public read, then settles the original accepted/uncertain handoff `turn/start` journal row. The transition requires its immutable method, recovery identity, empty-history watermark, cwd, thread, incarnation, and fleet name; observed/committed turn mismatches refuse unchanged. Only after settlement may a replacement generation resume. Same-generation adoption clears the predecessor gate, allowing its durable interrupt reservation exactly once; later reconciles only observe/finalize. No path starts another thread, turn, or body. Claim/row identity, activating uncertainty, terminal proof, mail/usage/result/limit preservation, and stale-predecessor denial remain intact. The explicit native route leaves the Claude default regression green.

**Checks:** Python 3.10 and 3.12: `46 passed` each under fail-fast `claude`/`mcx`/`codex` stubs; independent immutable-field/unchanged-state/idempotence probe passed; py_compile and diff check passed.

**Blockers:** None. No provider or network use.
