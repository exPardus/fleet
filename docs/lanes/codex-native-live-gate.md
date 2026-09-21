# Native Codex acceptance gate
DONE means: the bounded fake matrix and at most one authorized real lifecycle are recorded with unsupported rows left blocked.

## Original run verdict

- **MEASURED — BLOCKED, no full-native claim.** The deterministic fake gate ran
  12 exact lifecycle probes: supervisor boot/claim, idle wake, active steer,
  result distinction, supported predecessor interrupt, checkpoint/handoff,
  restart adoption, and stale-predecessor denial all passed. It started no
  `codex`, `claude`, or `mcx` provider process.
- **MEASURED — I1 blocked.** There is no native `interface-register` route with
  genuine Codex caller/source authorization. Thread membership or a supplied
  UUID cannot substitute for that proof.
- **MEASURED — usage blocked.** Native supervisor result observation does not
  persist public per-turn token totals. Existing transition tests prove only
  that already-recorded usage survives succession.

## Fake receipt

Command:

```text
python3 tools/codex_native_acceptance.py --fake
```

Result on Codex CLI `0.155.1`, reviewed schema SHA-256
`f0402dc8ce8d278108f1e68e9d46ec7e59ddd9d153f5e70668d84d56f258dda3`:

```text
overall=BLOCKED
pytest=12 passed in 0.64s
provider_processes_started=false
PASS supervisor_boot_claim idle_wake active_steer result interrupt checkpoint_handoff restart_adoption stale_predecessor_denial
BLOCKED interface_registration usage
```

The nonzero harness exit is deliberate: blocked rows never render as PASS.
`tests/test_codex_live.py` also proves that the default live entrypoint returns
`SKIP` without executing even a hostile `codex` stub.

## Real attempt

Public preflight reported ChatGPT auth, no stored API key, reachable ChatGPT
HTTP/WebSocket endpoints, Codex CLI `0.155.1`, and the reviewed schema version.
That permitted one fixed-prompt attempt under the no-paid-API rule:

```text
FLEET_CODEX_LIVE=1 python3 tools/codex_native_acceptance.py --live
```

The per-home host exited before ready with exit code 1. The harness therefore
reported `BLOCKED` and stopped without retry. No thread or turn ID existed, no
prompt reached a model, and usage remained unmeasured. The disposable home was
removed and a process check found no `fleet_codex_host.py` or `codex app-server`
process. Cleanup classification: `host=not_started`, `thread=not_created`.

## Supported lifecycle and remaining gaps

The original fake evidence supported the explicit native supervisor lifecycle
through claim-bound boot, wake/steer/result state, checkpoint, handoff,
successor adoption, one supported predecessor interrupt, and stale-holder
denial. Later bounded slices added fake acceptance for process-bound Interface
authority and per-turn usage accounting. A successful inference lifecycle on
the real protocol remains unproved on this machine. Native dispatch remains
opt-in; Claude and legacy mcx behavior remain the compatibility baseline.

## WHERE THIS BRIEF WAS WRONG

The requested real run was conditional on auth/quota, but those checks were not
the first live blocker. Public auth and reachability were healthy; the reviewed
per-home host itself exited before ready. Retrying would have weakened the
no-duplicate-run constraint, so the gate stopped and recorded no IDs or usage.

## Later bounded closure

The Linux process-bound Interface slice closes the fake I1 blocker without a
second real run. The fake gate now includes three-home registration, wrong-ID
refusal, claim handoff, fork/PID-reuse refusal, and external-thread write
refusal. The earlier real-run result and the prohibition on a full-native claim
remain unchanged.
