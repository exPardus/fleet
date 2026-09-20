# Native Codex Fleet Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full Codex worker, supervisor, and interface lifecycle support through public app-server while preserving Claude and legacy mcx behavior.

**Architecture:** One authenticated host per Fleet home persistently owns `codex app-server --listen stdio://`. Focused protocol/host/adapter modules return public observations; `fleet.py` remains the sole registry and claim writer and never holds `fleet.lock` over process, IPC, RPC, or wait.

**Tech Stack:** Python 3.10+ standard library, JSON-RPC, owner-only local IPC, pytest, generated Codex 0.155.1 v2 schema.

**Spec:** `docs/specs/codex-native-integration.md`

## Global Constraints

- Use only supported Codex CLI/app-server surfaces; never inspect private Codex daemon/socket/rollout/database state.
- Only Codex mints thread/turn IDs. Keep Codex `session_id=null`; invent no Claude SID or nonce.
- Resolve one explicit absolute Fleet home; remove `CLAUDE_CODE_SESSION_ID` from Codex infrastructure.
- Release `fleet.lock` immediately after preclaim writes and before all external work; never nest it with `codex-host.lock`.
- Use `turn/interrupt(threadId, turnId)` and require terminal public proof; never signal a Codex PID.
- Never retry an uncertain mutation blindly.
- Preserve Claude, existing mcx rows, and literal input → 0.5-second wait → one Enter notification behavior.
- Run targeted and full checks on Python 3.10 and 3.12; report exact pre-existing failure IDs.

## Review Focus

- Host loss after Codex accepts a mutation but before Fleet records the response must not duplicate a body.
- Wrong-home, fake, or cross-provider identities must refuse without a state write.
- Approval/input requests must persist and surface without automatic approval.
- Native Codex, mcx, and Claude rows must route independently.
- Symlinked, wrong-owner, stale-generation, oversized, or hostile host state must refuse safely.

---

### Task 1: Pin the public protocol contract

**Files:**
- Create: `tools/codex_schema_fixture.py`
- Create: `tests/fixtures/codex_app_server/0.155.1/{manifest.json,v2-contract.json}`
- Create: `tests/test_codex_schema_fixture.py`

**Interfaces:**
- Produces: `generate_contract(codex: str, destination: Path) -> ContractManifest`

- [ ] Write failing tests that require initialize/initialized, thread start/read/list/resume, paged turns/items, turn start/steer/interrupt, exact state/error enums, permission fields, and steer/interrupt required IDs.
- [ ] Run `uv run --no-project --python 3.10 --with pytest python -m pytest -q tests/test_codex_schema_fixture.py`; expect missing-fixture failure.
- [ ] Implement deterministic bounded extraction from `codex app-server generate-json-schema`, storing the CLI version and full v2 schema SHA-256.
- [ ] Generate the 0.155.1 fixture and review that it contains no private path.
- [ ] Run the test on Python 3.10 and 3.12; expect PASS.
- [ ] Commit as `test(codex): pin the app-server protocol contract`.

### Task 2: Build the bounded JSON-RPC client

**Files:**
- Create: `bin/fleet_codex_protocol.py`
- Create: `tests/test_codex_protocol.py`
- Modify: `tests/test_index_compose.py`

**Interfaces:**
- Produces: `AppServerClient.start(...)`, `request(method, params, timeout)`, `respond(request_id, result)`, `notifications()`, `close()`; `ProtocolViolation`; `TransportLost`.

- [ ] Write failing tests for initialization ordering, response correlation, server requests, EOF, malformed/oversized frames, timeouts, bounded stderr, and secret/prompt redaction.
- [ ] Implement a reader thread with bounded queues and JSON-RPC 2.0 validation; no registry/claim imports or writes.
- [ ] Add an import-boundary test proving stdlib plus `fleet_errors` only.
- [ ] Run protocol/import tests on both interpreters; expect PASS.
- [ ] Commit as `feat(codex): add app-server protocol client`.

### Task 3: Add per-home host and authenticated IPC

**Files:**
- Create: `bin/fleet_codex.py`
- Create: `bin/fleet_codex_host.py`
- Create: `tests/test_codex_host_ipc.py`
- Modify: `bin/fleet.py`

**Interfaces:**
- Produces: `CodexHostClient.ensure(home: Path)`; `call(operation, timeout) -> CodexObservation`; host entrypoint with exact home/generation.

- [ ] Write failing tests: two concurrent starters yield one host/child; wrong home/generation/auth/digest refuse; symlink, wrong owner/mode/type, hostile JSON, and oversized frames refuse without replacement.
- [ ] Implement owner-only AF_UNIX on POSIX, bounded UTF-8 JSON bytes only,
  owner-only secret, descriptor-relative fixed-path checks, and exact-home
  authentication. Refuse Windows until owner-only named-pipe DACL creation and
  a negative cross-user test prove the platform seam.
- [ ] Implement `host.json`, heartbeat, bounded ready wait, `codex-host.lock` replacement, initialize/schema gate, and graceful idle shutdown.
- [ ] Assert `fleet.lock` and host lock are never nested and PID is only a liveness hint.
- [ ] Run tests on 3.10/3.12; commit as `feat(codex): add per-home app-server host`.

### Task 4: Persist operations and reconcile restart

**Files:**
- Modify: `bin/fleet_codex.py`
- Modify: `bin/fleet_codex_host.py`
- Create: `tests/test_codex_host_recovery.py`
- Modify: `tests/test_views_doctrine.py`

**Interfaces:**
- Produces: durable `prepared|accepted|observed|committed|uncertain|failed` operations; `reconcile_home(home) -> ReconcileReport`.

- [ ] Write failing crash-injection tests before send, after send, after response, and before Fleet commit for thread start, turn start, steer, and interrupt.
- [ ] Persist immutable operation ID/digest/home/generation before send; replay same digest from stored result and refuse a changed digest.
- [ ] On restart, initialize app-server and reconcile real recorded IDs through read/resume and paged turns/items before any new mutation.
- [ ] Map wrong cwd, schema mismatch, system error, multiple new turns, and unknown transport to uncertain/PAGE with no retry.
- [ ] Pin views to committed file evidence only: no host start, live RPC, repair, quarantine, or `fleet.lock`.
- [ ] Run recovery/doctrine tests on both interpreters; commit as `feat(codex): reconcile host restarts`.

### Task 5: Implement native worker lifecycle

**Files:**
- Modify: `bin/fleet.py`
- Modify: `bin/fleet_codex.py`
- Create: `tests/test_codex_native_worker.py`
- Modify: `tests/test_codex_substrate.py`

**Interfaces:**
- Produces: `dispatch_kind=codex-app-server`; genuine thread/turn fields; native routes for spawn/status/send/wait/peek/result/interrupt/kill/resume/respawn.

- [ ] Write failing transition-table tests for active/waiting/idle/not-loaded/system-error/limit states and tests for preclaim/bind, exact cwd, lost responses, busy steer, idle wake, supported interrupt, result/usage, and no duplicate body.
- [ ] Route by `dispatch_kind`: existing `mcx` behavior stays byte-compatible; native rows use app-server; mixed-invalid rows refuse.
- [ ] Implement spawn sequence exactly: preclaim under `fleet.lock`; unlock; create thread; conditionally bind under lock; unlock; start one turn; conditionally commit under lock.
- [ ] Implement busy steer only with matching `expectedTurnId`; retain mail on mismatch/non-steerable.
- [ ] Implement interrupt terminal proof, result from completed public items, public token totals, and no inferred USD.
- [ ] Run native + existing mcx tests on 3.10/3.12; commit as `feat(codex): add native worker lifecycle`.

### Task 6: Implement provider-safe Codex supervisor

**Files:**
- Modify: `bin/fleet.py`
- Modify: `bin/fleet_codex.py`
- Create: `tests/test_codex_supervisor.py`
- Modify: `tests/test_supervisor.py`
- Modify: `tests/test_supervisor_gate.py`

**Interfaces:**
- Produces: `ProviderIdentity(provider, value)`; provider-tagged holder; Codex sup-spawn/boot/status/guard/wake/checkpoint/release.

**Bounded landings (2026-09-21):** explicit `sup-spawn --codex-adapter native
--model codex:<model>` implements preclaim, genuine public thread binding,
first-turn boot, and held-claim promotion. The next slice adds exact-home,
claim-bound `sup-status`, `sup-guard`, active `turn/steer`, stale-idle
`turn/start`, and public active/completed/failed result distinction. Status
remains a file-only view; guard and send use `thread/read(includeTurns=true)`
and refuse incomplete, waiting, not-loaded, system-error, generation-mismatched,
or conflicting evidence. Guard and send require a `full` item view and the
bound turn to be the unique newest returned turn before they may mutate. A
durable per-claim operation reservation prevents a
second mutation; ambiguous recovery queues no second turn and never resumes or
creates a thread. A stale predecessor or supplied UUID cannot authorize a
call. The default supervisor route remains unchanged. Checkpoint/release,
handoff, and explicit `sup-reconcile` now extend that same binding: checkpoint
requires complete current evidence; release enters a mutation-disarmed
`releasing` state until terminal public proof; handoff binds an empty successor,
transfers to `activating`, and only then starts its first turn; host restart uses
`thread/resume` plus a complete exact-ID read and never starts a thread or turn.
Lost activation/restart responses freeze without retry. Paged result hydration,
permissions, predecessor interruption/retirement, activating-state restart
adoption, and native Interface ownership remain unsupported; these slices do not enable
native dispatch by default or complete this task.

- [ ] Write failing tests for genuine thread holder with no Claude SID/nonce, cross-home/fake refusal, first-turn pending/held states, guard table, busy steer, idle wake, host restart, and unchanged Claude claims.
- [ ] Decode legacy Claude claims unchanged; write Codex `holder={provider:codex,thread_id:<real>}`; never infer provider from UUID shape.
- [ ] Boot with preclaim then unlock, create/bind real thread, write pending holder conditionally, unlock, start boot turn, promote only on matching `turn/started`.
- [ ] Implement exact §10.2 OK/WAKE/DISPATCH/PAGE table; uncertain identity/state always PAGE.
- [ ] Re-run `tests/test_sup_notify.py` and assert literal input, 0.5-second wait, one Enter.
- [ ] Run tests on both interpreters; commit as `feat(codex): add provider-safe supervisor lifecycle`.

### Task 7: Implement permissions and blocking requests

**Files:**
- Modify: `bin/fleet_codex_host.py`
- Modify: `bin/fleet_codex.py`
- Modify: `bin/fleet.py`
- Create: `tests/test_codex_permissions.py`

**Interfaces:**
- Produces: exact mode map; durable pending requests; `fleet codex-respond NAME REQUEST_ID DECISION`.

- [ ] Write failing parameterized tests for bypass/accept/dontask/plan/omit mapping and managed-policy rejection.
- [ ] Call `configRequirements/read`; refuse disallowed policy; record returned effective approval/reviewer/sandbox.
- [ ] Persist server request IDs with real thread/turn/item IDs before exposing waiting; unknown request kinds freeze.
- [ ] Implement explicit one-shot response, offered-decision validation, stale/wrong-home/wrong-thread/repeated refusal, and observed `serverRequest/resolved`.
- [ ] Never default to `acceptForSession` or fabricate user input.
- [ ] Run tests on 3.10/3.12; commit as `feat(codex): manage permission waits`.

### Task 8: Implement handoff and interface registration

**Files:**
- Modify: `bin/fleet.py`
- Modify: `bin/fleet_codex.py`
- Modify: `tests/test_codex_supervisor.py`
- Create: `tests/test_codex_interface.py`
- Modify: `tests/test_interface_state.py`
- Modify: `tests/test_home_resolution.py`

**Interfaces:**
- Produces: activating-state Codex handoff; `interface-register --codex-thread <real-id>`.

- [ ] Write failing tests for successful, rejected, timed-out, and unknown successor activation; exact-home registration; fake/unknown/cross-provider/wrong/ambiguous home with byte-identical state.
- [ ] Create/bind empty successor while predecessor holds; conditionally transfer claim to successor `state=activating` before starting work.
- [ ] Start successor boot after transfer; promote held only on matching `turn/started`. Proved no-start may restore predecessor; unknown acceptance stays activating/PAGE.
- [ ] After promotion, interrupt/retire predecessor only with supported terminal proof.
- [ ] Resolve an explicitly named home before public thread read. Permit the
  Interface cwd to remain the Fleet repo while it explicitly drives Fleet,
  PM, or tap; keep worker/supervisor cwd binding strict and allow no fallback.
- [ ] Require supported genuine caller/source authorization in addition to
  public thread membership. A supplied UUID plus `thread/read` never grants
  mutation; if caller/source proof is unavailable, refuse without a write.
- [ ] Keep external bridge registration/read observational: it never resumes
  or owns that Interface thread, starts a turn, or creates a second writer.
- [ ] Prove a stale predecessor cannot mutate after claim handoff.
- [ ] Run tests on both interpreters; commit as `feat(codex): add handoff and interface registration`.

### Task 9: Preserve mcx and stage migration

**Files:**
- Modify: `bin/fleet.py`
- Create: `tests/test_codex_migration.py`
- Modify: `tests/test_codex_substrate.py`
- Modify: `tests/test_doctor.py`

**Interfaces:**
- Produces: `--codex-adapter native|mcx`; record-local route; doctor census; explicit terminal-row migration.

- [ ] Write failing coexistence tests with Claude + mcx + native rows and assert each substrate receives only its own probes/writes.
- [ ] Default new rows to native only after version/schema gate; preserve explicit mcx rollback and every old row's recorded adapter.
- [ ] Doctor reports row counts, mixed-invalid rows, missing helpers, schema drift, unsafe host state, and uncertain operations without silent repair.
- [ ] Permit explicit migration only on a proved terminal mcx respawn; retain old `mcx_id`, result, usage, and adapter history.
- [ ] Run migration + existing mcx tests on 3.10/3.12; commit as `feat(codex): preserve mcx during migration`.

### Task 10: Build and pressure-test the Codex skill

**Files:**
- Restore: `skills/fleet/supervisor.md`
- Create: `skills/codex-fleet/SKILL.md`
- Create: `skills/codex-fleet/agents/openai.yaml`
- Create: `bin/install_codex_skill.py`
- Create: `tests/test_codex_skill.py`
- Create: `tests/role_pressure/codex_fleet_cases.json`
- Modify: `skills/fleet/SKILL.md`

**Interfaces:**
- Produces: idempotent hash-reporting installer; action-graded role-pressure cases.

- [ ] Capture a baseline failure for the five spec §13 cases in an isolated workspace, storing observable actions only.
- [ ] Write failing tests for install/idempotence/hash match, symlink refusal, and differing-destination refusal unless explicit overwrite.
- [ ] Restore/reconcile supervisor guidance and write the minimal role-routed Codex skill within prose caps.
- [ ] Install to `${CODEX_HOME:-$HOME/.codex}/skills/fleet/` via atomic replace; tests use a temporary Codex home.
- [ ] Independently evaluate that interface cases read named-home evidence and delegate, allow only separately authorized bounded observation, and avoid edits/build/full suite/heavy analysis/SSH/live mutation/redundant approval.
- [ ] Run skill validator and tests on both interpreters; commit as `feat(skill): add Codex fleet role routing`.

### Task 11: Update owning docs and run live acceptance

**Files:**
- Modify: `docs/SPEC.md`
- Modify: `docs/PLAN-PROGRESS.md`
- Modify: `.claude-plugin/plugin.json`
- Modify: `skills/fleet/SKILL.md`
- Create: `tests/test_codex_live.py`
- Create: `docs/lanes/codex-native-live-gate.md`
- Modify: `tests/test_doc_claims.py`
- Modify: `tests/test_docs_currency.py`
- Modify: `tests/test_receipts.py`

**Interfaces:**
- Produces: one consistent shipped contract; opt-in `FLEET_CODEX_LIVE=1` matrix.

- [ ] Add failing doc assertions for both adapters, Codex supervisor/interface, supported interrupt, permissions, exact home, schema gate, and notification preservation.
- [ ] Update owning docs and plugin wording; retain mcx as legacy; classify this design as unbuilt until implementation receipts can be pinned.
- [ ] Add default-skipped disposable live tests for spec P1–P5, worker, supervisor, handoff, interface, interrupt, host restart, and no-duplicate recovery.
- [ ] Prove the default live test makes no Codex call, then run the authorized live gate with `FLEET_CODEX_LIVE=1`; blocked account-dependent cases are BLOCKED, never PASS.
- [ ] Record version, schema digest, test IDs, terminal states, and cleanup without prompts, credentials, reasoning, transcripts, or private paths.
- [ ] Run docs/receipt/prose tests on 3.10/3.12; commit as `test(codex): verify native lifecycle live`.

### Task 12: Verify and gate default enablement

**Files:**
- Modify: `docs/PLAN-PROGRESS.md`
- Create: `docs/lanes/codex-native-final.md`

**Interfaces:**
- Produces: acceptance decision; native default only when every matrix row passes; mcx remains.

- [ ] Run all Codex, supervisor, interface, home, view-doctrine, and notification targeted tests on Python 3.10 and 3.12.
- [ ] Run full suites on both interpreters and compare exact failure IDs to base. Matching nonzero base is reported as matching base, never green.
- [ ] Review spec §14 row by row: P1–P5, H1–H5, W1–W7, S1–S5, I1–I2, A1–A2, M1–M2, R1, C1–C2, F1.
- [ ] Enable native default only if every row has evidence; otherwise leave it opt-in and name blockers.
- [ ] Keep explicit mcx fallback and all legacy code; removal requires its own operator ruling/change.
- [ ] Commit the evidence record as `docs(codex): record native enablement gate`.
