# Failed-client native Codex host recovery

**Source checkpoint only; execution remains HOLD.** The bounded source tests
do not establish a complete Linux lifecycle or an executable private procedure.
An exact-source independent Linux lifecycle test and independent procedure
review remain required before any live stage. This document grants no shutdown,
rebind, replay, policy change or interruption authority.

`fleet codex-recover-failed-client` is an explicit, staged Linux recovery for a
home whose authenticated Fleet host still responds but whose one app-server
stdio client cannot make provider requests. The Interface must use an explicit
`--fleet-home`, hold the current process-bound native Codex Interface claim,
and run the command from one clean, reviewed Fleet source checkout. That
checkout's HEAD and four recovery source hashes are pinned in the durable
intent. A different Interface source, home, or source tree refuses.

`prepare` requires the original host generation, host and child PIDs and start
identities, held supervisor incarnation, thread and turn. It snapshots the
claim, every same-generation registry row, operation and approval directories,
mail for those threads, supervisor queue and journal, and affected worktree
heads, tracked state and lane receipts. Every original operation must be
committed. An unresolved recorded callback refuses before interruption.
Tracked-state evidence includes raw Git index bytes, staged blob identities,
raw tracked file bytes, file types and permission modes, and symlink link bytes without following
their targets. This detects different edits with identical Git status, including
assume-unchanged files. Git read commands disable optional index refreshes.
Untracked files are outside this evidence contract. Submodules, unsupported file
types, index/path drift during inspection, more than 16384 tracked entries,
individual files above 4 MiB, or aggregate tracked bytes above 64 MiB refuse.
The operator also supplies an absolute `--codex-executable`; Fleet records
its file identity and SHA-256 and verifies that `--version` exactly matches
the old host. Boot uses this pinned executable for both app-server and schema
commands. It never silently selects the current PATH version.
Unrecorded callbacks in the failed child cannot be excluded. The home barrier
is written before any host or provider lifecycle action. It is enforced by
the reviewed client and replacement host; the already loaded old host cannot
hot-load it. The Interface must coordinate all callers away from that old
host before interruption, and the post-shutdown evidence CAS catches recorded
state drift. An unrecorded in-flight effect remains part of the explicit loss
decision. Other homes and
unrelated product rows may progress; a newly appeared same-generation row or
change to pinned evidence refuses subsequent stages.

`decision` accepts an owner-only JSON receipt matching the recovery ID, home,
old generation, literal `authority: founder`, literal
`decision: accept-controlled-interruption`, and the exact consequence text
exported as `LOSS_TEXT` by the module. The Interface must create this receipt
only after a specific founder decision. Recording it changes no host process.
`shutdown` checks the evidence, source, exact old host/child identities and
known descendants, durably records `shutdown_sent`, then sends one existing
generation-bound `host/shutdown`. A missing reply is unknown acceptance and
must never trigger a second shutdown.
The separate restored-continuation checked-shutdown verb is refused by both
client and host while a failed-client barrier exists, including after completion.
It cannot replace the single staged original-host shutdown.
`verify-exit` requires both old PIDs and
every inventoried descendant absent, with stale old heartbeat. PID reuse,
unavailable identity, a live child or descendant, or evidence drift blocks.

`boot` checks the old processes absent and all original journals still
committed before starting one reviewed replacement host. If a CLI crash leaves
`boot_requested`, `adopt-boot` verifies an already started host; it does not
launch a second one. The new host runs the same reviewed recovery source and
must match the old reviewed Codex version, schema and pinned executable. The new host barrier
allows only the exact staged `thread/resume` operation while `rebind` is open.

`rebind --name NAME` reads complete public paged turn and item history for the
exact existing thread, cwd and newest bound terminal turn.
The public history gate pages the items of **every** persisted turn, then
repeats the complete turn/item inventory and thread header. Different item
digests, duplicate identities, wrong turn bindings, cursor loops, incomplete
pages, unknown item kinds and nonterminal/unknown item statuses refuse. Known
status-free message/reasoning/review/search items are accepted; command, file,
tool and image-generation items require an explicit terminal status. The
inventory is bounded to 6400 turns, 4096 item pages per turn, 65536 items and
64 MiB of item JSON per pass. A bounded IPC-size failure reduces the item page
size to one; an oversized single item remains a refusal. These are persisted
record classifications, not proof that external effects or unrecorded callbacks
are complete.
It uses the row's recorded effective model, approval and sandbox policy and sends one
`thread/resume` with `excludeTurns: true`. It never starts a thread or turn and
never drains mail. A lost or accepted but unobserved reply leaves the one-shot
operation pending. `settle-rebind` uses only an exact observed or committed
operation whose immutable journal generation, payload digest and recovery
identity match the staged intent. It rechecks public history and conditionally writes the
row and, for the supervisor, the held claim. A partial claim/row save can be
settled without another provider call. Historical terminal rows are held
without resume after public inspection. `finish` requires every affected row
rebound or held and the supervisor rebound. The completed barrier still fences
held historical threads. Both client and new host validate the staged operation
ID, generation, target thread and complete payload digest before a provider
write; the host also checks that its IPC peer is the current exact Interface.

The original host cannot load a newly edited barrier. Therefore the reviewed
CLI must keep the pinned evidence stable through the single old-host shutdown
and recheck it afterwards. A concurrently accepted old-host side effect,
undrained callback, detached process, or external tool effect can remain
unknown. The founder's controlled-interruption decision covers that residual
uncertainty; it is not evidence of natural completion. The private home
procedure and receipt must be independently reviewed before any live stage.
