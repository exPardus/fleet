# Native Codex fleet integration design

**Status:** Option A approved and native is the default for new Codex workers
and Codex supervisor bodies. The explicit mcx compatibility selector remains.
**Evidence baseline:** fleet `6fa06c9`; reviewed `codex-cli` 0.155.1,
0.160.0 and 0.161.0 v2 JSON Schemas generated from isolated installs with
`codex app-server generate-json-schema`.
**Implementation plan:** `docs/plans/2026-09-20-codex-native-integration.md`.

## 1. Decision

New Codex workers and Codex supervisor bodies will use a home-scoped Fleet host
that persistently owns one supported `codex app-server --listen stdio://` child.
Fleet will speak only the documented JSON-RPC protocol over that child's stdio.
Separate fleet CLI invocations will reach the host through a Fleet-owned,
authenticated local endpoint. A durable Fleet operation journal will make a
host restart conservative and reviewable.

Existing mcx-backed rows remain mcx-backed. They are neither rewritten nor
silently adopted. New `codex:<model>` dispatch defaults to app-server; explicit
`--codex-adapter mcx` remains during migration. Removing mcx is a later
operator decision backed by a zero-row census and a completed soak.

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

### 3.2 Reviewed Codex v2 schemas

For a new host, the adapter selects an explicit reviewed manifest from exact
`codex --version` output. Versions 0.155.1, 0.160.0 and 0.161.0 are reviewed; any other
version refuses before host startup, and an installed schema whose digest
differs from its selected manifest never publishes ready. An already-live host
is instead authenticated against the reviewed version and digest recorded in
its metadata, so upgrading the installed CLI does not strand native work owned
by the prior reviewed host. The adapter begins with `initialize` and
`initialized`. Both reviewed generated schemas expose:

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

Fleet reads thread metadata with `thread/read(includeTurns=false)`. Worker and
supervisor observations fetch at most the two newest turns through
`thread/turns/list(sortDirection=desc, itemsView=notLoaded, limit=2)`; this
preserves the bound-turn-is-newest check without transferring rollout history.
The exact newest turn's items are read through `thread/items/list` in ascending
pages of at most 16. An oversized item page is retried with a smaller limit;
one item that cannot fit the IPC frame remains an explicit failure. Empty or
single-turn launch proofs use the same bounded read and refuse an older-turn
cursor. Provider status, thread ID, cwd, host generation, turn ID, and item
validation remain required before a mutation or terminal verdict.
Every `thread/resume` used by worker, supervisor, and queue recovery sets
`excludeTurns=true`, then obtains any needed turn evidence from those pages.

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

Review of 0.160.0 against 0.155.1 found no change to any Fleet-used method,
required parameter, thread/turn/permission type, server notification, effective
thread-start field, or no-inference RPC sequence. Its only extracted contract
delta is the additive error codes `flexUnavailable` and `tooManyDenials`.

Review of 0.161.0 against 0.160.0: the extracted contract is byte-identical
(same `contract_sha256`): no change to any Fleet-used method, required
parameter, thread/turn/permission type, server notification, error code, or
no-inference RPC sequence. Only the raw schema digest differs. The generator
had to learn that 0.161 emits `CodexErrorInfo` variants under `anyOf` rather
than `oneOf`; without that, `activeTurnNotSteerable` and the object-form
connection error codes silently dropped out of the extraction.

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
under `state/codex/`. Codex host platform decisions use the shared
`bin/fleet_platform.py` `PLATFORM` adapter, including Linux process evidence
and Windows refusal. The initial native adapter refuses on Windows: enabling a
named-pipe implementation requires explicit owner-only DACL creation and a
negative cross-user connection test. Inherited default ACLs are not evidence of
confinement. Peers exchange
length-bounded UTF-8 JSON bytes, never pickle. A random host secret is written
to an owner-only temporary file, synced, then renamed to `host.key`, so pre-lock
readers only see a complete key. It is stored
owner-only through the platform adapter. It authenticates local Fleet IPC; it
is not a Codex ID, supervisor nonce, or model-visible authority token.
If a host response exceeds the 1 MiB IPC frame limit, the host returns the
correlated error `host response exceeds MAX_IPC_BYTES; page the request` and
keeps serving. For a mutation, the client treats that error as an uncertain
outcome because the provider may already have accepted it; read-only callers
can shrink their requested page.

Each request carries `protocol_version`, `host_generation`, `operation_id`,
`method`, `fleet_home`, a thread ID when known, and immutable payload
digest. One operation ID has one digest/result. Responses echo those values;
the client rejects another home, generation, operation, or digest.

An accepted or uncertain operation from an older host generation is rejected
with an explicit "reconcile before retry" uncertainty; generation rollover
never turns a lost provider response into a replay.

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
verifies version/schema, then publishes ready. It supervises protocol stdio,
bounds and redacts app-server stderr in memory, and rejects invalid/oversized
messages. The detached host's own stdout/stderr are currently discarded and
there is no durable host lifecycle log, so an unexpected predecessor exit can
be unclassifiable after `host.json` is replaced. It stays alive while native
rows, a Codex supervisor claim, or unresolved operations exist. Idle shutdown
cannot occur during an accepted operation.

Host and app-server PIDs are paired with a kernel start identity so a reused PID
cannot validate stale metadata. Linux retains `/proc/<pid>/stat` field 22.
Darwin reads `KERN_PROC_PID` through libc `sysctl` and uses
`kinfo_proc.kp_proc.p_starttime` seconds plus microseconds; if that read is
unavailable it falls back to `ps -o lstart= -p <pid>` under the C locale.
Because those sources have incompatible precision and representation, a
source change is treated as unknown and falls back to a conservative PID
existence check; it never proves the owner dead or permits lock/host theft.
Windows retains its existing unsupported identity result. A missing identity
still prevents ready metadata from being accepted.

The app-server notification queue is bounded at 8,192 events by default so a
single busy home can multiplex several active lanes without the former 1,024-
event burst failure. `FLEET_CODEX_EVENT_QUEUE_MAX` (or the compatibility
spelling `FLEET_CODEX_MAX_EVENTS`) may select another positive bound, capped at
65,536; no setting permits an unbounded queue. A queue overflow never makes a
mutation replayable. The host marks the original operation uncertain, replaces
only the failed stdio child, and attempts exact public reconciliation: a
`thread/start` carries a provider-persisted `threadSource` derived from its
operation ID, so recovery can list the exact-cwd app-server threads and load the
one tagged empty thread under a separate durable `thread/resume` intent to
recover its effective model and permission tuple; a `turn/start` reads the
already-bound thread and requires exactly one turn beyond its recorded history
watermark. The original journal entry is adopted only after those identities,
cwd, effective settings, and turn counts agree. Missing, duplicate, malformed,
or repeatedly overflowing evidence leaves the original intent uncertain and
reports the `FLEET_CODEX_EVENT_QUEUE_MAX`/lane-concurrency remedy. Read-only
requests may be repeated once after replacing the failed stdio child. If the
client was already failed before a spawn request could be written, the protocol
reports that fact explicitly; the replacement child then receives the first and
only provider dispatch under the already-accepted journal intent.

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
   Its public `threadSource` is the operation-derived recovery correlation.
   Queue-bound transport failures follow §7.1 reconciliation; the mutation is
   never retried.
3. Call `thread/start`; on a valid response, persist the genuine thread/cwd.
4. Reacquire `fleet.lock` only to conditionally bind that same preclaim to the
   thread, then release it. Bind failure records an orphan empty thread and
   starts no turn.
5. Immediately before `turn/start`, reserve the exact bound row under
   `fleet.lock`, then release it. A terminal mutation that commits first fences
   the launcher; once reserved, terminal mutation refuses until reconciliation.
6. Prepare and call `turn/start` once outside the lock; record the real turn;
   reacquire only to conditionally commit active state from the complete
   reserved row.

Lost `thread/start` and `turn/start` responses never retry automatically.
Queue-overflow recovery has the exact correlation described in §7.1; other
transport loss still has no reliable `thread/start` correlation and leaves a
possible empty orphan. Turn recovery reads the bound thread and turns. Exactly
one new genuine turn may be adopted only when it is strictly after the history
watermark and the thread is exclusively Fleet-bound. Zero, multiple, wrong-cwd,
wrong-effective-settings, or conflicting observations become
`uncertain`/`dead-suspected` and PAGE.

### 8.2 State, send, and wake

**Implemented 2026-10-04:** ordinary native worker `status` and `wait` validate
the exact recorded thread, newest recorded turn, canonical cwd, and host
generation through the existing exact-home host. They also read the bounded
public-evidence file for the exact bound thread and turn: a durable
`completed` event yields `idle` after `notLoaded` or `systemError` only when
the validated live read finds that same exact newest turn and also reports it
`completed`. In-progress, failed, interrupted, missing, or conflicting live
turn evidence stays non-idle. An unresolved mutation prevents an older
completion from vouching for unknown provider work. Host loss, a failed live
read, malformed evidence, or conflicting identity maps to
`dead-suspected`, never to a proved death. File-only views remain file-only.
`fleet doctor --repair` backfills rows that were already committed
`dead-suspected` before this completion rule shipped. It requires the same
exact bound thread/turn in durable evidence and a validated live `thread/read`,
with both reporting `completed`; every other status, route, archived row,
pending operation, evidence mismatch, and host ambiguity stays unchanged.
Candidate rows are snapshotted under `fleet.lock`, host IPC runs unlocked, and
the repair commits by complete-row compare-and-swap so a concurrent kill,
resume reservation, or other mutation wins. Bare `doctor` remains report-only.
Busy `send` uses one
`turn/steer(expectedTurnId=...)`; idle `send` starts one new turn on the same
thread. Each mutation is reserved durably before IPC, and an uncertain response
keeps that reservation and retained mail instead of retrying.

| Public observation | Fleet verdict |
| --- | --- |
| active, no wait flags, matching turn | `working` |
| active + `waitingOnApproval` | `waiting` with approval metadata |
| active + `waitingOnUserInput` | `waiting` with input metadata |
| idle + persisted terminal current turn | terminal mapping, usually `idle` |
| exact newest turn is `completed` in both durable evidence and validated live read | `idle`, including after live-view eviction |
| `notLoaded` with missing or disagreeing completion evidence | `dead-suspected`; explicit recovery is required, never inferred death |
| `systemError` with missing or disagreeing completion evidence | `dead-suspected`/PAGE |
| host loss, schema mismatch, wrong cwd, or conflicting turn | `dead-suspected`/PAGE |
| limit error + authoritative future reset | `limited` |
| limit error without authoritative recovery evidence | `limited` with no reset horizon; resume refuses |

Send to a matching active steerable turn calls
`turn/steer(expectedTurnId=codex_turn_id)`. Active mismatch or
`activeTurnNotSteerable` leaves mail pending and starts no turn. Idle send
claims mail and calls one `turn/start`; failure restores/leaves the claim
recoverable. Mail deletes only after accepted public observation. Send and
interrupt refuse a committed `dead-suspected`, unknown, waiting, or uncertain
row and any unresolved operation before provider IPC, except that `send` may
recover the exact `dead-suspected`/`uncertain` shape produced solely by a host
generation change. When the existing host generation differs, `send` reserves
one `thread/resume`, validates the real thread's ID, cwd, model, permission
profile, and unchanged newest turn, and conditionally adopts the new generation
before steering or waking. Reservation compares the complete pre-resume row,
and adoption compares the complete reserved row; any concurrent state change,
including a terminal action, wins and cannot be overwritten by adoption. The
resume creates no turn; a lost response or any identity conflict freezes the
reservation and is never replayed. A down host with no replacement still
creates no send reservation. A known-local mailbox failure before the provider
call releases its reservation; only a possibly accepted provider call freezes
the row and keeps the reservation for reconciliation.

### 8.3 Interrupt and terminal operations

**Implemented 2026-10-04:** worker `interrupt` issues one supported request and
then requires an exact same-turn terminal read before committing the terminal
state. A lost response remains `dead-suspected` with an unresolved operation;
it is not retried. A live-host `kill` uses the same proof rule; only proof that
the recorded host incarnation itself is gone can bypass the turn read. Kill
refuses any pending native operation, including `thread/resume`, and revalidates
the unchanged row at its terminal write; a concurrent reattachment can never be
silently reported as killed. An expired launch preclaim with no provider thread
binding is cleared by that unchanged-row path. A bound row with no recorded turn
first requires an exact same-generation `thread/read`: only an idle thread with
zero turns is safe to clear. Any observed provider turn may be the accepted turn
whose registry commit was lost, so kill refuses with that identity instead of
allowing a later respawn to duplicate its work.
`respawn` requires old-turn terminal proof, creates a new
provider-minted thread only after a full-row reservation of that actionable
post-proof state, records the retired thread/turn/proof tuple, and carries the
durable brief, journal, and pending mail. A concurrent kill that commits first
wins that compare-and-swap; fresh-thread and turn commits also require their
complete reserved rows and cannot resurrect it. `resume-limited` reads public
rate-limit state, records an authoritative future reset when supplied, and
starts one same-thread turn only after explicit allowance or an elapsed reset.
If respawn finds a replacement host generation, it first performs the same
exact-thread `thread/resume` and conditional generation adoption as send. The
re-attached thread supplies the required terminal proof; respawn never treats
host loss alone as proof and never creates the fresh thread before that proof.

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

**Implemented 2026-10-04:** worker `peek` and `result` are file-only views of
the bounded exact-turn public-evidence file. `result` exposes text only when
thread, turn, item ID, text, untruncated marker, terminal status, and token
totals form one complete matching record; it takes no lock, performs no RPC,
and writes nothing. `wait` uses the same durable exact-turn item for its
terminal summary. No worker path derives USD from token counts.

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

**Implemented 2026-10-04 for native workers:** every new worker thread,
including a context-reset respawn, reads `configRequirements/read` before
`thread/start`, refuses an explicitly requested approval or sandbox mode that
managed requirements exclude, and records the effective approval, reviewer,
and sandbox returned by the provider. App-server blocking requests are stored
atomically under the exact home with their real request/thread and applicable
turn/item identity plus host generation before status exposes them. They survive a host
restart as visible generation-bound waits; a request from a replaced
generation is stale and cannot be answered on the new connection.

`fleet codex-respond NAME REQUEST_ID DECISION` is the only response path.
`DECISION` is an offered literal, an explicit JSON response object, or `@file`;
the host validates it against the stored request, marks the request consumed
before writing the JSON-RPC response, and never retries an uncertain write.
Repeated, resolved, wrong-home, wrong-thread, wrong-turn, stale-generation,
and unknown-kind responses refuse. `serverRequest/resolved` closes the durable
wait; user-input and elicitation values are not retained in response evidence.
No mode supplies `acceptForSession` or user input implicitly.

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
unchanged on Claude routes. A handoff never switches provider: `sup-handoff-begin --model
codex:<model>` on a Claude-held claim refuses before dispatch. Move a Claude
supervisor to Codex by checkpoint, `sup-release`, then `sup-spawn --model
codex:<model>`.

Host restart never transfers/seizes. It reinitializes app-server, resumes the
real holder thread, pages history, and recomputes guard. Unknown freezes and
never creates a second supervisor body.
The effective policy in a successful public `thread/resume` response is checked
against the supervisor row's requested Fleet mode before generation adoption.
For example, `workspaceWrite` under a recorded `bypass`/`dangerFullAccess`
holder is a mismatch even if the thread and newest turn still match. Fleet
keeps the original generation and uncertain claim, preserves the accepted or
observed new-generation journal and all mail, and never repeats that resume
or starts a turn. The normal resume builder supplies only the existing thread
ID and `excludeTurns=true`.
For an original `bypass` holder with an exact observed `workspaceWrite` resume,
the current registered Codex Interface first runs
`sup-reconcile --prepare-recorded-policy-restore` with explicit `--fleet-home`
and exact expected incarnation, thread, turn, original resume operation, and
observed host generation. This records a five-minute claim-bound proof of the
original journal, current managed requirements, and bounded public
idle/completed/no-new-turn evidence. A loaded thread may be idle, and pinned
0.155.1 ignores resume policy overrides for a loaded thread; `thread/unsubscribe`
does not unload it. The exact observed Platform host and app-server child must
exit and its heartbeat become stale. Then `--restore-recorded-policy` with the
same pins creates only a fresh Platform host, validates the preflight and cold
boundary, and reserves a new auditable resume intent. The pinned public
`thread/resume` request supplies `threadId`,
`excludeTurns=true`, canonical `cwd`, recorded `model`, `approvalPolicy=never`,
`approvalsReviewer=user`, and `sandbox=danger-full-access`. A narrow host
journal gate permits this linked request behind only the matching observed
original intent from the prior generation. The original journal stays observed.
Fleet adopts the fresh generation only after an exact effective bypass response,
repeat public header, and locked claim/row/source/host/journal comparison. An
accepted but unverified new response remains uncertain; read-only reconcile can
settle only its exact observed new operation. No turn is replayed or newly
started.

### 10.4 Retiring an absent legacy Claude claim

From the **current registered native Codex Interface process**, use
`fleet --fleet-home <exact-home> sup-retire-legacy --expect-inc <legacy-incarnation> --expect-sid <old-Claude-session-id>`
only after `sup-guard` reports `DISPATCH` and the old body and predecessors have
been stopped or otherwise proved absent. This command does not take a nonce,
accept a replacement SID, dispatch a thread, or start a turn. It requires an
explicit home, the process-bound exclusive Codex Interface registration, and
the exact legacy Claude claim and unique supervisor registry row. It refuses a
Codex, released, pending, corrupt, changed, or fresh claim; any present
`handoff_pending` field (including empty or malformed values) or handshake;
missing or ambiguous identity; and a failed, empty, malformed,
or suspicious `claude agents --json --all` roster. Two fresh roster observations
must show every home-scoped supervisor body and predecessor in documented
terminal state `done` or `stopped` with neither `pid` nor `status` fields,
as observed for reaped `done` and supported `claude stop` in
`docs/specs/native-substrate.md` §G3/G10. Even `pid: false` or a status field
on an otherwise terminal row is malformed proof.
A registry `dead-suspected` label alone is never proof. The claim, complete
supervisor row identity set, and Interface registration are compared again under
`fleet.lock`; a newer journal checkpoint or concurrent change refuses. An idle
resumable holder is refused because the legacy guard would offer `WAKE`.

Success stores the original claim, holder row, roster evidence, and Interface
source under `state/supervisor-retirements/<incarnation>.json` with a prepared
phase; rewrites the
claim to `released` without legacy nonce or holder fields; and tombstones only
the old holder row. Only after the registry and event writes succeed does it
mark the evidence complete. The released claim names the old SID in `released_by_sid`
so the existing boot liveness gate still protects against a returning body.
The operator's queue, all mail (including claimed mail), worker rows, briefs,
and journals remain in place. Normal `sup-spawn --model codex:<model>` can then
create a new supervisor incarnation; it rechecks the public Claude roster and
old supervisor absence before creating a thread. It also requires matching
complete retirement evidence and the exact old-holder tombstone, rechecked
under `fleet.lock`. Run `sup-guard` again immediately before that dispatch.
An interrupted write may leave prepared evidence, a released claim, or an
incomplete tombstone. Native spawn refuses that state; the operator preserves
the evidence and resolves it through reviewed recovery, without an automatic
retry or overwrite.

An authenticated `sup-reconcile` may also settle an uncertain supervisor send
whose original operation journal proves rejection before provider acceptance.
The current registered Codex Interface must match the exact home and process
source. The pending operation, holder, host generation, journal recovery
identity, and newest public thread/turn must agree, and the claim and registry
row must still match under `fleet.lock`. The old Darwin host's precise
authentication-refusal response may promote its still-prepared journal entry to
failed only after those checks; a newer host records that rejection as failed
before responding. The one claimed mail file is restored to an empty inbox by
an exclusive link before the held claim is unblocked. Concurrent new inbox mail
leaves both files and the uncertain claim intact for ordered recovery. A failed
initial `thread/start` preclaim with no
bound thread may instead be retired to a released claim and dead row, retaining
its incarnation, journal, and brief. Accepted, uncertain, missing, conflicting,
or unreadable evidence stays frozen. Neither path repeats `thread/start`,
`turn/start`, or `turn/steer`; after a host generation change a separate
`sup-reconcile` reattaches the exact thread without creating a turn.
Queue-overflow recovery counts the entire persisted turn history through
`thread/turns/list` pages of at most 32 with items omitted, after validating a
metadata-only `thread/read`; it requires exactly one turn beyond the durable
watermark before adopting an uncertain `turn/start`.
The host journal's 64 KiB metadata bound can be reached by a successful
provider reply before the 1 MiB IPC response bound. If recording that reply
fails after the durable `accepted` transition, the host retains or marks the
operation uncertain. The client checks the exact journal state for every
correlated mutation error: `accepted`, `uncertain`, `observed`, and `committed`
raise an uncertain outcome, never a definitive rejection. A handoff therefore
keeps its activating claim and predecessor disarmed until exact public proof;
it cannot roll back a live successor because an oversized journal write failed.

## 11. Explicit home and interface registration

`interface-register` gains a Codex route. It resolves exactly one explicitly
named initialized home before identity. One Interface whose cwd remains the
Fleet repository may explicitly register against and drive the Fleet, PX, and
projecty homes. There is no cwd or ambient-home fallback for this route. Worker and
supervisor canonical cwd binding remains strict.

Registration requires a genuine public thread plus supported caller/source
authorization tying the invoking Interface to that thread and target home.
`thread/read`, a caller-supplied UUID, source shape, or cwd coincidence proves
membership only; none authenticates the caller or grants mutation authority.
If the installed public protocol cannot provide genuine caller/source proof,
registration refuses without writing state.

The reviewed protocol exposes thread ID, session ID, and source as readable
membership metadata, but no credential authenticating the process invoking
Fleet. On Linux and Darwin, Fleet therefore combines an exact public
`thread/read` with kernel-owned Unix-socket peer credentials and process
ancestry. Linux reads `/proc`; Darwin reads `KERN_PROC_PID` start identity,
`PROC_PIDTBSDINFO` for parent/uid/command, `PROC_PIDVNODEPATHINFO` for cwd,
and same-uid `KERN_PROCARGS2` for environment. Darwin sockets provide
`LOCAL_PEERPID` and `LOCAL_PEERCRED`. Registration binds the exact
`CODEX_THREAD_ID`, nearest Codex ancestor PID and start identity,
and explicit home in an owner-only rotating claim. The host rechecks the peer's
thread and ancestry for every app-server mutation. A different UUID, unrelated
same-user process, reused PID, nearer forked Codex process, or stale predecessor
fails closed. Windows remains unsupported until it has equivalent
peer-process and PID-reuse acceptance proof.

Interface provider registration is exclusive. A successful native Codex
registration removes the Claude session and tmux pane identities; a successful
Claude/tmux registration removes the native Codex claim. Both routes take the
target home's same `fleet.lock` and perform the competing-provider cleanup
inside it, so concurrent cross-provider registrations cannot leave both
families present. Receipt verification
also rejects a home containing both provider families, so legacy or raced stale
identity files cannot preserve authority after a provider rotation.

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
3. New `codex:<model>` uses app-server by default; explicit
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
| P1 | Schema | Generate 0.155.1, 0.160.0 and 0.161.0 v2 schemas; validate each fixture digest | Either reviewed exact version/digest accepted; unknown version or drift disables native only |
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
