# RED — native supervisor lifecycle

**Head:** `b50e5dd104342e2927c575e620e8c94180abd759` on `3f168c1eaaeca02e76f5246880e1a70f1b6410ab`.

**Verdict:** RED. Exact-home claim/row binding, file-only status, connect-existing reads, active steer, idle start, durable reservation, wrong-home/stale-holder refusal, pending-operation PAGE, genuine returned thread/turn IDs, claimed-mail retention after uncertain mutation, and unchanged default Claude/mcx routing are implemented and focused tests pass.

**Blockers:** `_codex_supervisor_observe()` accepts `itemsView="notLoaded"` and `"summary"`; guard/send do not reject them despite the committed plan’s incomplete-evidence refusal. A direct send probe on idle `summary` evidence called `turn/start`, committed it, and deleted the queued mail. The observer also accepts a bound completed turn when a newer completed turn exists. A second send probe called `turn/start` and advanced the claim again instead of refusing stale turn identity. Require `itemsView == "full"` for guard/send and require the bound current turn to be the unique newest turn before mutation; preserve mail on either refusal.

**Checks:** fail-fast `claude`/`mcx` stubs preceded every test. Python 3.10 and 3.12 focused suites: `120 passed` each; native compatibility: `27 passed`; diff check passed. No provider, default, interface, bridge, network, or live process ran.
