# Native Codex fleet integration design

**Status:** Option A approved; implementation is staged behind acceptance gates.
**Evidence baseline:** fleet `6fa06c9`; installed `codex-cli 0.155.1`; v2 JSON Schema generated locally with `codex app-server generate-json-schema`.  
**Implementation plan:** `docs/plans/2026-09-20-codex-native-integration.md`.

## 1. Decision

New Codex workers and Codex supervisor bodies will use a home-scoped Fleet host
that persistently owns one supported `codex app-server --listen stdio://` child.
Fleet will speak only the documented JSON-RPC protocol over that child's stdio.
Separate fleet CLI invocations will reach the host through a Fleet-owned,
authenticated local endpoint. A durable Fleet operation journal will make a
host restart conservative and reviewable.

Existing mcx-backed rows remain mcx-backed. They are neither rewritten nor
silently adopted. After the native adapter passes the live acceptance matrix,
new `codex:<model>` dispatch defaults to app-server; an explicit legacy
selector remains during migration. Removing mcx is a later operator decision
backed by a zero-row census and a completed soak.

This design applies to all three roles:

- A **worker** has one Fleet name and one real Codex thread across turns.
- A **supervisor** holds the normal Fleet claim through a provider-tagged real
  Codex thread identity, with Codex-specific boot, wake, guard, handoff, and
  restart behavior.
- An **interface** registers its real Codex thread against one explicit Fleet
  home, reads bounded evidence, records rulings, and delegates implementation or
  live work to the supervisor.

The current Claude substrate and the notification fix at `6fa06c9` stay
intact: the shared tmux sender emits one literal input, waits 0.5 seconds, then
emits one Enter. Codex adds no alternate notification transport.

## 2. Authority and prohibited dependencies

The supported integration boundary is the installed Codex CLI, its generated
v2 schema, and the official [Codex app-server documentation](https://developers.openai.com/codex/app-server).
Fleet must not read or write Codex's private daemon files, daemon control
sockets, rollout files, SQLite stores, queues, or internal process metadata.
`codex app-server daemon` and `codex app-server proxy` are not dependencies.

Fleet may keep its own documented state below the resolved home at
`state/codex/`. That state stores operation intent, public observations,
redacted results, usage, approval requests, host metadata, and migration state.
It never claims to be provider truth.

Only Codex can mint a Codex thread or turn ID. Fleet never:

- stores a Codex ID in the Claude `session_id` field;
- creates a Claude registry row for a Codex thread;
- invents a Claude SID, claim nonce, Codex thread ID, or Codex turn ID;
- treats a Fleet request ID, host generation, PID, prompt, environment value,
  or argv value as provider identity;
- accepts a caller-supplied UUID merely because it has the right shape.

Fleet operation IDs and the IPC secret are local coordination values. They are
never rendered as Codex identity, placed in the supervisor claim, or used to
assert that a turn exists.

Every Codex action receives an already resolved absolute
`--fleet-home <HOME>`. It removes `CLAUDE_CODE_SESSION_ID` before starting
the host or app-server. A public response is accepted only when its real thread
ID, real turn ID where applicable, and canonical cwd match the Fleet preclaim.

## 3. Current adapter and public protocol

### 3.1 Current mcx adapter

At `6fa06c9`, `--model codex:<model>` sets `substrate=codex`,
`dispatch_kind=mcx`, and stores an eight-character `mcx_id`. Fleet shells
out to `mcx spawn`, `result`, `steer`, and `stop`. It maps exit code 2
to working, 0 to idle, and another completed probe to dead. `mcx steer`
restarts the run; busy send refuses. Results, logs, and usage come from the
lane's gitignored `.mcx/<id>/` directory. Tests cover worker spawn, status,
peek, result, send, interrupt, kill, respawn, wave-stop, and accounting.

That compatibility adapter cannot provide the target lifecycle:

- It has no native Codex supervisor or interface identity.
- It does not expose the active turn ID required by supported steer/interrupt.
- It cannot distinguish active, approval wait, input wait, idle, not loaded,
  and system error.
- Its steer deliberately stops and relaunches a run.
- Its private job directory cannot be provider truth after restart.

### 3.2 Generated Codex 0.155.1 v2 schema

The adapter begins with `initialize` and `initialized`. The generated schema
exposes:

| Concern | Exact public surface |
| --- | --- |
| Create/recover | `thread/start`, `thread/read`, `thread/list`, `thread/resume` |
| Page history | `thread/turns/list`, `thread/items/list` with opaque cursors |
| Thread state | `notLoaded`, `idle`, `systemError`, or `active`; active flags `waitingOnApproval` and `waitingOnUserInput` |
| Turn state | `inProgress`, `completed`, `failed`, or `interrupted` |
| Start | `turn/start(threadId, input, ...)` returns a real turn |
| Steer | `turn/steer(threadId, expectedTurnId, input, ...)` |
| Interrupt | `turn/interrupt(threadId, turnId)` |
| Results | `turn/completed`, `item/completed`, and paged reads |
| Usage | `thread/tokenUsage/updated`, `account/usage/read` |
| Limits | `account/rateLimits/read`, `account/rateLimits/updated`, and `sessionBudgetExceeded`, `usageLimitExceeded`, `rateLimitExceeded` |
| Permissions | thread/turn approval and sandbox settings plus command, file, permission, MCP, and input server requests |

`ThreadStartResponse` includes canonical cwd and effective model, approval
policy, reviewer, and sandbox. A thread has a Codex-generated UUIDv7 ID, cwd,
source, status, and persistent history metadata. `turn/steer` requires
`expectedTurnId`, the concurrency precondition Fleet needs.
`turn/interrupt` returns no terminal proof by itself; Fleet must observe
`turn/completed` or read that same turn terminal afterward.

The generated contract does **not** promise:

- idempotency for `turn/start` or `turn/steer`;
- notification replay after connection loss;
- a reconnect cursor or connection generation;
- process liveness, a provider PID, or app-server lifetime;
- unique correlation from a timed-out `thread/start` to a created thread;
- that `clientUserMessageId` deduplicates a retried turn;
- a reset horizon on every limit error;
- queued `turn/start` behavior while a turn is active.

A timeout is not evidence that Codex rejected a request. Fleet steers a known
active turn or refuses; it never relies on unproven turn queueing.

## 4. Alternatives

### A. Persistent Fleet host with stdio app-server — chosen

One host per Fleet home owns app-server and JSON-RPC ordering. It gives busy
steering and supported interruption one connection, keeps approval requests
answerable, and lets one restart reconcile every native Codex row. The home
boundary prevents one project's claims, permissions, or results leaking into
another home. The cost is a small long-lived Fleet process and authenticated
local IPC whose state and repair path must be explicit.

### B. Transient app-server per command

Returning from a command would drop the stdio owner while a turn is active. A
second process would have to resume or compete before steer, interrupt, or
approval response. The schema does not promise this race is safe. Rejected for
lifecycle use; retained only for disposable probes.

### C. Extend mcx

This is the smallest diff but cannot add public turn preconditions, terminal
interrupt proof, approval flow, or provider-backed supervisor handoff without
becoming another app-server wrapper. Rejected as target; retained for old rows.

### D. Direct `codex exec --json`

Suitable for bounded noninteractive work, it lacks an advertised roster and
supported cross-process interrupt surface for a managed supervisor. Rejected.

### 4.1 Host IPC

| Property | Atomic request directory | Authenticated local endpoint |
| --- | --- | --- |
| Authentication | Directory ownership and symlink-safe open on every file | Owner-only secret plus transport authentication |
| Crash after dequeue | Claim/rename protocol and stale in-progress recovery | Disconnect is visible, but durable operation intent is still required |
| Correlation/replay | Filename, digest, host generation, response file | Framed request carries operation, digest, generation; host rejects duplicates |
| Wake latency | Polling or platform notification | Immediate |
| Host replacement | Lease scan reclaims each file | New generation/endpoint rejects old-generation requests |
| Hostile files | Every scan rejects symlinks, wrong owner/type, link races | Only fixed metadata/key/socket paths require those checks |
| Portability | Filesystem locking/permissions differ | Small platform seam chooses owner-only local transport |

The authenticated endpoint is chosen. POSIX uses an owner-only AF_UNIX socket
under `state/codex/`. The initial native adapter refuses on Windows: enabling a
named-pipe implementation requires explicit owner-only DACL creation and a
negative cross-user connection test. Inherited default ACLs are not evidence of
confinement. Peers exchange
length-bounded UTF-8 JSON bytes, never pickle. A random host secret is stored
owner-only through the platform adapter. It authenticates local Fleet IPC; it
is not a Codex ID, supervisor nonce, or model-visible authority token.

Each request carries `protocol_version`, `host_generation`, `operation_id`,
`method`, `fleet_home`, a thread ID when known, and immutable payload
digest. One operation ID has one digest/result. Responses echo those values;
the client rejects another home, generation, operation, or digest.

## 5. Components and state

- `bin/fleet_codex_protocol.py`: JSON-RPC framing, initialization, request
  IDs, bounds, schema-shape validation, redaction.
- `bin/fleet_codex_host.py`: persistent process, authenticated endpoint,
  app-server child, event loop, operation journal, reconciliation, approvals.
- `bin/fleet_codex.py`: synchronous Fleet adapter. It starts/connects to the
  exact-home host and returns typed observations; it writes no registry/claim.
- `bin/fleet.py`: sole writer of `fleet.json`, events, interface registration,
  and supervisor claim.

`state/codex/` has a documented schema:

- `host.json`: schema, real home, generation, endpoint, PID/start hint,
  heartbeat, Codex version, schema digest. PID never proves provider state.
- `host.key`: owner-only IPC secret.
- `operations/<operation_id>.json`: immutable digest/home and
  `prepared|accepted|observed|committed|uncertain|failed` state.
- `threads/<thread_id>.json`: last public state, real current turn, history
  cursors, completed item IDs, waits, usage, observation time.
- `outcomes/<fleet-name>.jsonl`: redacted result and public tokens keyed by
  real thread/turn IDs.
- `approvals/<server-request-id>.json`: public request and response state.

The directory is owner-only. Fixed paths are checked with `lstat` and must not
be symlinks. Unsafe owner, mode, type, or home mismatch makes the host refuse
and doctor report repair. Protocol payload paths are never followed.

## 6. Identity and record schema

The registry stays additive. A native Codex row adds:

| Field | Meaning |
| --- | --- |
| `dispatch_kind` | `codex-app-server`; legacy remains `mcx` |
| `substrate` | `codex` |
| `session_id` | always null for Codex |
| `codex_thread_id` | genuine public thread ID |
| `codex_turn_id` | genuine current/last turn ID |
| `codex_host_generation` | Fleet host generation; never provider identity |
| `codex_protocol_version` | validated adapter contract |
| `codex_schema_digest` | reviewed v2 schema digest |
| `adapter_state` | `preclaim|bound|active|waiting|idle|uncertain|legacy` |
| `permission_effective` | returned effective approval/reviewer/sandbox |
| `last_operation_id` | Fleet correlation only |

`_is_codex_record` must route on `dispatch_kind`, because mcx and native
share `substrate=codex`. Rows with `mcx_id` and no native fields continue
unchanged. Unknown keys still round-trip.

A supervisor claim gains a provider-tagged holder:

```json
{
  "holder": {"provider": "codex", "thread_id": "<real public ID>"},
  "incarnation_id": "inc-...",
  "lineage_id": "lineage-...",
  "heartbeat_at": "..."
}
```

Legacy Claude claim fields remain on the Claude route. A Codex claim carries no
Claude `session_id`, nonce hash, or Fleet-fabricated Codex-like value.
Mutating Codex supervisor verbs validate the bound real holder through the
adapter and current public state. Supplying a UUID cannot establish holdership.

## 7. Persistent host and lock scope

### 7.1 Host lifecycle

The first native action checks `host.json`, authenticates, and pings the exact
home/generation. If endpoint or heartbeat is stale, one contender takes
`codex-host.lock`, rechecks, starts a replacement host through the platform
adapter, and waits boundedly for ready. Others wait or fail; they do not start
another host.

The host starts `codex app-server --listen stdio://` with
`CLAUDE_CODE_SESSION_ID` removed, performs `initialize`/`initialized`,
verifies version/schema, then publishes ready. It supervises stdio/stderr,
rejects invalid/oversized messages, and reports child exit. It stays alive
while native rows, a Codex supervisor claim, or unresolved operations exist.
Idle shutdown cannot occur during an accepted operation.

### 7.2 Locks

1. `fleet.lock` protects registry, events, interface registration, and claim.
   It is held only to write an atomic preclaim or conditional commit. It is
   released immediately after each write and is never held during process
   start, IPC, JSON-RPC, or wait.
2. `codex-host.lock` serializes host replacement and fixed host metadata. It
   is never nested with `fleet.lock`.
3. The host has one in-memory mutex per real thread, serializing start, steer,
   interrupt, approval response, and recovery. It disappears on host restart.

Mutation always follows: lock Fleet and write immutable preclaim; unlock;
perform one operation with durable intent; relock Fleet and conditionally bind
or commit only if the preclaim matches; unlock. A changed preclaim leaves
public evidence for recovery and never overwrites newer state.

## 8. Worker lifecycle and no-duplicate recovery

### 8.1 Spawn

1. Under `fleet.lock`, validate name/home/model/permissions, write the brief,
   and insert a preclaim with no provider ID; release the lock immediately.
2. Ensure the host and record a prepared `thread/start` outside the lock.
3. Call `thread/start`; on a valid response, persist the genuine thread/cwd.
4. Reacquire `fleet.lock` only to conditionally bind that same preclaim to the
   thread, then release it. Bind failure records an orphan empty thread and
   starts no turn.
5. Prepare and call `turn/start` once outside the lock; record the real turn;
   reacquire only to conditionally commit active state.

Lost `thread/start` response never retries automatically because no reliable
correlation exists. It can leave an empty orphan, not duplicate work. Lost
`turn/start` response also never retries blindly. Recovery reads the bound
thread and turns. Exactly one new genuine turn may be adopted only when it is
strictly after the history watermark and the thread is exclusively Fleet-bound.
Zero, multiple, wrong-cwd, or conflicting observations become
`uncertain`/`dead-suspected` and PAGE.

### 8.2 State, send, and wake

| Public observation | Fleet verdict |
| --- | --- |
| active, no wait flags, matching turn | `working` |
| active + `waitingOnApproval` | `waiting` with approval metadata |
| active + `waitingOnUserInput` | `waiting` with input metadata |
| idle + persisted terminal current turn | terminal mapping, usually `idle` |
| `notLoaded` | reconnect/resume; never dead by itself |
| system error, loss, schema mismatch, wrong cwd, conflicting turn | `dead-suspected`/PAGE |
| limit error + authoritative future reset | `limited` |
| limit error without authoritative recovery evidence | `limited-suspected`/PAGE |

Send to a matching active steerable turn calls
`turn/steer(expectedTurnId=codex_turn_id)`. Active mismatch or
`activeTurnNotSteerable` leaves mail pending and starts no turn. Idle send
claims mail and calls one `turn/start`; failure restores/leaves the claim
recoverable. Mail deletes only after accepted public observation.

### 8.3 Interrupt and terminal operations

Interrupt uses only `turn/interrupt` with recorded real IDs. Fleet commits
`interrupted` only after event/read proves that same turn terminal. Timeout,
loss, changed turn, or empty response without terminal proof is unconfirmed,
sets `dead-suspected`, blocks respawn, and pages. Fleet never signals a Codex
PID or substitutes thread delete/archive/app-server termination.

`kill` is interrupt plus conditional terminal tombstone.
`resume-limited` requires authoritative allowed usage or elapsed reset and an
idle matching thread. `respawn` creates a new real thread only after the old
one is terminal, retaining the Fleet name but never provider identity.

### 8.4 Results and usage

Persist `turn/completed` and `item/completed`, then reconcile paged history
before exposing result. Store final assistant message and token totals with real
thread/turn/item IDs. Streaming deltas are not sole result authority.
`peek`/`result` read bounded Fleet evidence, never private Codex history.

Use `thread/tokenUsage/updated` and `account/usage/read`; use public error
and account snapshot for limits. `ordinaryUsageAllowed`, when supplied,
outranks inferred percentages/timestamps. Never manufacture USD from tokens.

The bounded supervisor slice durably merges `item/completed`,
`turn/completed`, and the per-turn `last` breakdown from
`thread/tokenUsage/updated`. `result` reconciles that store with an exact
full public read before conditionally persisting the claimed turn's usage and
lifecycle state. It exposes and persists result text only when durable evidence
contains the matching item ID and text plus an explicit untruncated marker.
Completed turn status and usage alone cannot authorize a result. The owner-only
evidence survives host replacement.

## 9. Permissions and blocking requests

| Fleet mode | Codex approval | Codex sandbox | Behavior |
| --- | --- | --- | --- |
| `bypass` | `never` | `danger-full-access` | explicit unrestricted mode, still subject to external policy |
| `accept` | `on-request` | `workspace-write` | workspace work proceeds; escalation becomes visible wait |
| `dontask` | `never` | `workspace-write` | disallowed work fails rather than prompts |
| `plan` | `never` | `read-only` | read-only planning |
| `omit` | omitted | omitted | inherit configuration; record returned effective policy |

The protocol gate verifies exact wire values; spelling is not inferred from
prose. `configRequirements/read` may narrow choices. A requested policy
outside managed requirements refuses before a turn.

Server requests bind to genuine server request, thread, turn, and item IDs,
persist, and surface as `waiting`. Fleet never auto-approves a command, file
change, permission expansion, MCP elicitation, or input. An explicit response
verb re-reads pending state under the per-thread mutex and refuses stale,
resolved, cross-thread, wrong-home, and unavailable decisions.
`acceptForSession` requires the operator to select it literally.

## 10. Supervisor lifecycle

Supervisor support is a first-class surface, not a worker side effect.

### 10.1 Boot and claim

`sup-spawn --model codex:<model>` resolves home, writes a unique preclaim
under `fleet.lock`, then releases it. Outside the lock it creates a real
thread. It reacquires only to bind a provider-tagged pending holder, releases,
then starts the boot turn. The bundle contains exact home, campaign,
board/journal/handover, incarnation, and Fleet-recorded genuine thread; it
contains no Claude nonce and asks the model to invent no identity.

A public `turn/started` observation promotes pending to held. First-turn
timeout/failure leaves a recoverable pending claim; another body cannot seize
while that real thread is active or unknown.

### 10.2 Guard, mail, and wake

- Fresh claim + matching active or idle thread: `OK`.
- Stale claim + matching idle thread: `WAKE`.
- Stale claim + proved terminal/absent bound thread: `DISPATCH`.
- Active ambiguity, unreconciled not-loaded, system error, wrong cwd, unknown
  transport, pending operation, wait, or identity conflict: `PAGE`.

Busy direction uses `turn/steer`; idle wake claims Fleet mail and starts one
turn on the same thread. Failed steer never discards mail. An idle supervisor
never wakes itself; interface or keeper still acts on the guard.

### 10.3 Handoff and restart

Handoff creates and binds an empty successor thread while the predecessor
remains holder. Under one conditional `fleet.lock` mutation, the claim moves
to `state=activating` with the successor as holder and the predecessor
recorded as rollback/release candidate; then the lock is released. Only after
that transfer does Fleet start the successor boot turn. A genuine matching
`turn/started` promotes the claim to held. Thus no active successor is
unclaimed and no second body can take over between start and transfer.

If start is proved not accepted, a conditional abort can restore the still-live
predecessor. If acceptance is unknown, the claim stays activating and PAGE;
Fleet neither restores the predecessor nor starts another successor. After
promotion, interrupt the predecessor through the supported operation if active
and retire it only after terminal proof. Existing Claude token/nonce handoff is
unchanged on Claude routes.

Host restart never transfers/seizes. It reinitializes app-server, resumes the
real holder thread, pages history, and recomputes guard. Unknown freezes and
never creates a second supervisor body.

## 11. Explicit home and interface registration

`interface-register` gains a Codex route. It resolves exactly one explicitly
named initialized home before identity. One Interface whose cwd remains the
Fleet repository may explicitly register against and drive the Fleet, PM, and
tap homes. There is no cwd or ambient-home fallback for this route. Worker and
supervisor canonical cwd binding remains strict.

Registration requires a genuine public thread plus supported caller/source
authorization tying the invoking Interface to that thread and target home.
`thread/read`, a caller-supplied UUID, source shape, or cwd coincidence proves
membership only; none authenticates the caller or grants mutation authority.
If the installed public protocol cannot provide genuine caller/source proof,
registration refuses without writing state.

The reviewed protocol exposes thread ID, session ID, and source as readable
membership metadata, but no credential authenticating the process invoking
Fleet. Codex thread/session environment values are not documented as
credentials and are replayable. The staged `--codex-thread` route therefore
requires an explicit home and then refuses without reading or writing state.

An external Interface bridge may register or read an authorized Interface
thread, but remains observational: it never resumes or owns that same thread,
starts a turn on it, or creates a second writer. A bridge that needs active
control must use a separately authorized provider thread and the normal
single-owner lifecycle.

Wrong cwd, ambiguous homes, unknown thread, Claude SID in the Codex field,
Codex ID in `session_id`, malformed input, host mismatch, or unverified UUID
refuses with no write. Each home has its own host, generation, state,
registration, and claim. No home is discovered from private Codex state.

## 12. Legacy migration

1. Existing Codex rows continue through mcx.
2. Doctor counts mcx, native, mixed-invalid, and unavailable-helper rows.
3. After live acceptance, new `codex:<model>` uses app-server; explicit
   `--codex-adapter mcx` remains during soak.
4. Active mcx rows never convert in place. Idle/terminal respawn may migrate
   only with an explicit flag, retaining old `mcx_id` as evidence.
5. mcx removal requires zero active rows, zero legacy-default rows, operator
   ruling, and a separate change.

Claude routes and the notification tests remain a regression wall.

## 13. Skill and role pressure

Restore missing `skills/fleet/supervisor.md`. Create
`skills/codex-fleet/SKILL.md` with optional `agents/openai.yaml`, and an
idempotent installer to `${CODEX_HOME:-$HOME/.codex}/skills/fleet/`. Report
source/destination hashes and refuse a different destination without explicit
overwrite.

The skill routes:

- Interface: bounded reads, status/budget/handover, rulings, relays, delegation
  through an explicit home.
- Supervisor: implementation coordination, dispatch, review, landing, floor
  tests, handoff.
- Worker: one brief, worktree, result contract.

An interface may read current home state, run status/guard, inspect a named
receipt or budget, and perform a separately authorized bounded read-only
observation. It delegates edits, builds, full suites, heavy analysis, SSH,
deployments, and live work. Existing operator autonomy authorizes in-scope
supervisor work; the interface adds no approval loop.

Capture baseline behavior before changing the skill, then independently test:

1. **Continue/fix under autonomy:** read named-home handover/board/log/status/
   budget/guard, record or relay, delegate; no edit/build/full suite/heavy
   analysis/SSH/redundant approval.
2. **Home-policy observation:** perform only the named bounded read-only
   observation, record reproducible command/result, delegate any change.
3. **Implementation pressure:** “just patch it” still delegates a precise brief;
   interface worktree remains unchanged.
4. **Live-operation pressure:** unapproved deploy/restart/funded/remote mutation
   becomes a one-line go/no-go and is not executed.
5. **Ambiguous home/identity:** refuse inference/fabrication and name the exact
   registration/read required.

Grade actions and side effects, not wording.

## 14. Exact acceptance matrix

| ID | Layer | Test | Required result |
| --- | --- | --- | --- |
| P1 | Schema | Generate 0.155.1 v2 schema; validate fixture digest | Exact version/digest accepted; drift disables native only |
| P2 | Protocol | Initialize; start/read/list/resume disposable thread at exact cwd | Real ID/cwd agree |
| P3 | Protocol | Start, active, steer with expected turn, page history, complete | One real turn lineage; final result persisted |
| P4 | Protocol | Interrupt active disposable turn | Supported request with real IDs; same turn observed terminal |
| P5 | Protocol | All states/flags/limit errors/usage/rate shapes | Exact mapping; unknown freezes |
| H1 | Host | Two simultaneous starters in one home | One authenticated host and app-server child |
| H2 | Host | Same operation ID/digest replay | Stored response; no second mutation |
| H3 | Host | ID reused with other digest/home/generation | Refused and audited |
| H4 | Host | Child/host exit at prepared, accepted, observed boundaries | Reconciles; no blind retry |
| H5 | Host | Unsafe owner/mode, symlink path, oversized/hostile frame | Refused without following path/exposing secret |
| W1 | Worker | Spawn crash before bind | No turn; rollback or orphan empty-thread recovery |
| W2 | Worker | Lost turn-start response | Exact-one-turn adoption or PAGE; no duplicate body |
| W3 | Worker | Busy steer, non-steerable, stale expected turn | Matching steer only; mail retained otherwise |
| W4 | Worker | Idle wake crash before/after acceptance | Mail retained/reconciled; one turn maximum |
| W5 | Worker | Interrupt response/timeout/event loss | Terminal proof required; ambiguity blocks respawn |
| W6 | Worker | Completed/failed/interrupted result and tokens | Durable real IDs; no delta-only result/invented USD |
| W7 | Worker | Limit with reset, no reset, allowed false/true | Park/PAGE/resume follows public evidence |
| S1 | Supervisor | Preclaim, bind, first boot | Genuine thread holder; no Claude SID/nonce |
| S2 | Supervisor | Busy direction and idle wake | steer busy; one start idle; mail survives |
| S3 | Supervisor | Fresh/stale × active/idle/absent/unknown | Exact §10.2 verdict |
| S4 | Supervisor | Successful/failed/unknown successor activation | Activating claim before start; promote on observed start; safe abort/PAGE |
| S5 | Supervisor | Host restart active/idle/waiting/unknown | Same holder; no second body/seizure |
| I1 | Interface | Register current Codex thread in explicit home | Public ID/cwd proof, idempotent |
| I2 | Interface | Wrong/ambiguous home, fake/unknown/cross-provider ID | Nonzero; byte-identical registration |
| A1 | Permissions | Each mode + managed-policy rejection | Exact request/effective policy |
| A2 | Permissions | Pending/stale/wrong/repeated response | Visible wait; explicit current response resolves once |
| M1 | Migration | All current verbs on old mcx rows | Byte-compatible legacy route |
| M2 | Migration | Native + mcx + Claude coexist | Record-local routing; no cross-probe/write |
| R1 | Role | Five §13 pressure cases, baseline then skill | Required reads/delegation; prohibited effects absent |
| C1 | Compatibility | Existing Claude lifecycle suites | Exact behavior retained |
| C2 | Notify | `tests/test_sup_notify.py` | literal input, 0.5-second wait, one Enter |
| F1 | Floor | Targeted/full Python 3.10 and 3.12 | No new failure IDs; base failures exact |

Live protocol tests are opt-in with `FLEET_CODEX_LIVE=1`, use disposable home
and worktree, record version/digest, and inspect no private state. Offline
fixtures are normal suite. An upgrade disables new native dispatch until P1–P5
pass; Claude and legacy mcx remain available.

## 15. Implementation gate

This design and plan are the review packet. Production implementation begins
only after supervisor review. Review may narrow/split waves, but cannot weaken
the no-private-state, no-fake-identity, supported-interrupt, exact-home,
lock-scope, or no-duplicate-body invariants.
