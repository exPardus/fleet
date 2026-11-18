# Spec: `fleet msg` — one messaging layer for every harness

**Status:** proposed, not built; revision 2 after review. Build plan:
`docs/plans/messaging-plan.md`. Where this spec and later code differ, the
code is the authority and this file is updated in the same PR.

**Builds on:** `docs/specs/mailman.md` (mail format, crash-safe filing,
classification), `docs/specs/peer-messaging.md` (`fleet address`, native
`SendMessage`), `docs/specs/multi-fleet.md` (homes list, verb-effect tiers,
no cross-home writes), `docs/specs/claim-nonce.md` (supervisor continuity),
`docs/SPEC.md` §9. Root `CLAUDE.md` rules hold: stdlib only, Python 3.10,
pull-only, views never take `fleet.lock`.

## 1. Problem

Fleet has partial channels: `fleet send` steers one worker of one home;
`mailbox/<sid>.md` carries mid-turn text to Claude lanes; `mailbox/to-fleet/`
plus `mailman` sorts Interface mail; cross-machine mail is an operator-local
script writing mailman-format files into an outbound directory that the other
machine copies over ssh. None addresses a stable name, survives a body swap,
gives a receipt, or works the same for Claude, Codex and pi.

`fleet msg` is one store-and-forward layer. Any agent sends to a name. The
message is durable (fsynced) before `send` returns. A wake is a notice after
delivery, never the delivery, and never a steer.

## 2. What is reused, replaced, kept

```
# at 36602bbfb90c5d45b7e007a6a709b68f103fe3bc
$ grep -n "^def append_mailbox\|^def _registered_interface_mail_source\|^def _registered_lane_mail_sender\|^def _issue_verified_supervisor_mail\|^def cmd_mail_verify\|^def compose_prompt" bin/fleet.py
1424:def append_mailbox(sid: str, message: str) -> None:
1476:def _registered_interface_mail_source() -> dict | None:
1573:def _registered_lane_mail_sender() -> str | None:
1608:def _issue_verified_supervisor_mail(target: str, body: str) -> tuple[str, str | None]:
1657:def cmd_mail_verify(args) -> int:
1710:def compose_prompt(name: str, cwd, task: str, sid: str | None, journal_path=None,
$ grep -n "^def classify\|^def cmd_run" bin/fleet_mailman.py
498:def classify(raw: bytes | None, problem: str | None, cfg: Config | None,
731:def cmd_run(home, prims: Prims, *, timeout=None, interval=DEFAULT_INTERVAL,
$ grep -n "^def cmd_steer" bin/fleet_pi.py
871:def cmd_steer(args) -> int:
```

| Existing | Fate |
|---|---|
| `_atomic_append_bytes` | **Reused** for ledger lines. |
| `_write_json_atomic` | **Not reused** for spool, seq or ids: it has a fixed tmp name and no fsync. `publish()` (§5) replaces it there. |
| `_registered_interface_mail_source`, `_registered_lane_mail_sender`, claim nonce gate | **Reused** as caller authentication (§10). |
| `append_mailbox` + PostToolUse injection + the universal drain rule | **Reused** as the only wake channel (§9). |
| `fleet address` + `SendMessage` | **Kept** as an optional accelerator. |
| mailman `classify` and `mailman.json` | **Reused** to sort the Interface's inbox. |
| `fleet send` | **Kept** unchanged. Steering stays an explicit `fleet send` with its own gates; messaging never steers. |
| `state/mail-receipts/` + `fleet mail verify` | **Folded**: the stored envelope is the receipt (§12). |
| Operator-local outbound directory, script and bridge pull | **Replaced** by `fleet msg send` and the ssh transport. |
| `mailbox/to-fleet/` | **Kept** during migration as a rendered view. |

## 3. Identities and holders

An **identity** is a stable name. A **holder** is the body that reads for it
now. Messages address identities, never bodies.

- Grammar `^[a-z][a-z0-9-]{0,39}$`; qualified form `name@site`.
- An unqualified name always means the local site. No cross-site search.
- A **site** is one home's label, set by `fleet msg init --site LABEL`. `init`
  and `sync` refuse a label that another listed home uses; `hello` refuses a
  peer with the local label. Labels are local config; tracked files name none.

| identity | holder resolved at each read | file |
|---|---|---|
| lane `<worker>` | the registry row's current sid, Codex thread or pi job (read lock-free) | none: implicit from the row; gone when the row is archived |
| `supervisor` | the claim holder (INCARNATION) | none |
| `interface` | the current Interface registration | none |
| `ops` and other named roles (`hub`, `reviewer`, …) | a concrete binding: `session:<sid>`, `codex-thread:<id>` or `pi-job:<id>` | `ids/<name>.json` `{schema, name, role, binding, epoch, bound_at, bound_by}` |

Lane, supervisor and interface identities follow fork-steer, respawn,
handoff and reboot with no rebind, because the registry, the claim and the
registration already follow them. A named role needs `fleet msg bind` after a
body swap. `ops` is its own identity with its own queue; unbound, it queues.
Each bind increments `epoch` and appends a `bound` ledger line.

## 4. Envelope

One JSON object, UTF-8, canonical form `json.dumps(sort_keys=True,
separators=(",", ":"))`. Immutable once written.

| field | meaning |
|---|---|
| `schema` | `1` |
| `id` | 128-bit random hex, sender-minted once per logical send; every retry reuses it. The **dedup key**. Never compared by order. |
| `from`, `to` | `name@site` after resolution |
| `from_auth` | `{method, detail}` set by the sending site from caller evidence (§10) |
| `kind` | `note` (default), `task`, `receipt` |
| `needs_answer` | default `false` |
| `re`, `thread` | parent id or null; root id |
| `hop`, `path` | parent `hop` + 1; identities visited in the thread (sender-enforced, §11) |
| `seq` | per (`from`, `to`) counter (§5) |
| `sent_at` | sender clock, advisory |
| `body`, `body_sha256` | ≤120 words, ≤8 KiB |

Receiver facts (`received_at` by the receiver's clock, `via`, state) live in
the ledger and beside the envelope, never inside it.

## 5. Store layout and the two write primitives

Under each home's ignored `state/msg/`:

```
site.json, peers.json, config.json
ids/<name>.json              named roles only
locks/<identity>.lock        OS-released locks (fleet_platform / mailman backend)
seq/<from>__<to>             last seq allocated
outbox/<site>/q/<qseq>-<id>.json   waiting for a remote site
outbox/<site>/sent/          moved here when the peer confirms
spool/<name>/tmp|new|cur|done/<id>.json
rejected/<id>.json           with reason
seen/<id[:2]>/<id>           dedup markers
ledger.jsonl                 append-only operational log
archive/<yyyymm>/            compaction target (§6)
```

Both primitives live in `bin/fleet_msg_core.py`; every path calls them.

**`publish(spool, envelope)`**, under `locks/spool-<name>.lock`:
1. If `seen/<id>` exists or `<id>.json` is in `new|cur|done`, create the
   marker if missing and return `duplicate`.
2. Write `tmp/<id>.<pid>.<rand>`, fsync, `link()` into `new/<id>.json`
   (`EEXIST` = `duplicate`), fsync `new/`, unlink the tmp name.
3. Create `seen/<id>`, fsync. Append `delivered` to the ledger.

The marker is written after the file, so a marker never exists without a
message. A crash after step 2 leaves a file and no marker; step 1 of the next
ingest repairs that. The lock removes the concurrent-ingest race.

**`enqueue(from, to, envelope)`**, under `locks/<from>.lock`: run every §11
rule first, then allocate `seq` (read, increment, write a unique tmp name,
fsync, rename), then `publish` (local `to`) or write
`outbox/<site>/q/<qseq>-<id>.json` with fsync (remote `to`). A refusal
allocates nothing, so a refused send leaves no seq gap. `qseq` is the
server-local enqueue counter for that outbox.

No path takes `fleet.lock` or writes the registry.

## 6. Delivery, receipts, retention

```
queued ──transfer──▶ delivered ──inbox──▶ read ──ack──▶ acked
   └────────────────▶ rejected (size, rate, auth, stale, future, schema, corrupt)
```

- `send` prints `DELIVERED <id>` (local) or `QUEUED <id>` (remote).
- `inbox` moves `new → cur`; `--peek` moves nothing. `ack` moves `cur → done`.
- **Receipts**: only `delivered` and `rejected`, as `kind: receipt` envelopes
  to `from`. A duplicate re-emits `delivered`. A receipt never gets a receipt.
  Read and ack stay local ledger facts, shown by `fleet msg status`.
- **Ordering**: FIFO per (`from`, `to`) by `seq`. A gap is shown and blocks
  nothing. `re`/`thread` give causal order. No global order.
- **Dedup and clocks**: markers are the dedup proof. The receiver rejects
  `sent_at` more than `max_skew` (300 s) in the future, and older than
  `dedup_days` (30) by its own clock. Markers are kept at least
  `dedup_days + max_skew` after receipt by the receiver's clock.
- **Retention (no irreversible deletion).** `fleet msg compact` moves
  `done/`, `rejected/`, `outbox/*/sent/`, old markers and rotated ledger
  files into `archive/<yyyymm>/` (packed, never dropped). Any purge sits
  behind one `purge` seam, off by default, and needs an explicit setting.

## 7. Transport interface

```python
class Transport(Protocol):
    def hello(self, local: SiteInfo) -> SiteInfo: ...              # versions, clock, hosted identities
    def push(self, envelopes: list[bytes]) -> dict[str, str]: ...  # id -> accepted|duplicate|rejected:<why>
    def pull(self, after_qseq: int) -> list[tuple[int, bytes]]: ...  # (qseq, envelope), ascending
    def commit(self, ids: list[str]) -> None: ...                  # exactly these ids were published
    def close(self) -> None: ...
```

`commit` names ids, never a high-water mark, so a late enqueue below any
cursor is still sent. The peer moves only committed ids to `sent/`. `peers.json`
maps `<site>` to `{"transport": "fs"|"ssh", ...}`. A later transport (for
example tailnet) implements the same five methods. Same-home delivery calls
`publish` directly. Relay through a third site is out of scope (§13).

### 7.1 fs transport (homes on one machine)

Pull-only, so no cross-home write. Each home writes only its own `state/msg/`.
Mapping: `hello` reads the peer's `site.json`; `push` is a no-op that leaves
envelopes in the local `outbox/<peer>/q/`; `pull` lists the peer's
`outbox/<local>/q/`; `commit` writes the committed ids as `delivered`
receipts into the local outbox, and the peer moves its entries to `sent/` when
it pulls those receipts. A receipt entry moves to `sent/` once the source no
longer holds its envelope. Peers come from `~/.claude/fleet-homes.list`.
A file failing JSON or `body_sha256` is retried, then `rejected: corrupt` after
three passes.

### 7.2 ssh transport (two machines, one dials)

The reachable machine is the **server**; the other is the **client** and is
the only side that dials. Nothing assumes the server can reach the client.

- Client: `fleet --fleet-home H msg sync --peer <site>` runs
  `ssh -p <port> <alias> fleet --fleet-home <server-home> msg serve`. Port,
  alias and server home come from `peers.json`; a non-default port is expected.
- Server `authorized_keys`: `command="fleet --fleet-home <home> msg serve
  --peer <client-site>",restrict`. The server takes the client's site from the
  key entry, never from the client. `serve` refuses to start without `--peer`.
- Frames on stdin/stdout: a header line `{"op","len","sha256"}`, then exactly
  `len` bytes. Ops: `hello`, `push`, `result`, `pull`, `batch`, `commit`,
  `bye`.
- Session: `hello` both ways → `push` client outbox → `result` per id →
  `pull(after_qseq)` → `batch` → client publishes → `commit(ids)` → `bye`.

| failure | effect |
|---|---|
| drop mid-push | ids without `result` stay queued; resent; server dedups |
| drop mid-pull | no `commit`; resent next session; client dedups |
| partial or corrupt frame | discarded; session ends non-zero; nothing published |
| server unreachable | `sync` exits 4 after `max_failures` (mailman bridge contract) |
| clock skew | `hello` warns over 300 s; §6 bounds hold by the receiver's clock |
| replay | ssh protects the channel; markers make a replayed id `duplicate`; §6 rejects stale or future `sent_at` |
| envelope `from` not hosted by the peer site | `rejected: auth` |

**Client sync owner.** The client's mailman bridge command is
`["fleet","--fleet-home","<home>","msg","sync","--once"]`, so every mailman
pass syncs and no new daemon is needed; after a reboot the first Interface
mailman pass resumes delivery. `fleet msg queue` warns when the oldest
outbox entry for a peer is older than `outbox_warn_s` (default 900).

## 8. CLI

Every shipped argv, hook and notice names `--fleet-home` explicitly (§13).

```
fleet msg init    --site LABEL
fleet msg send    TO (TEXT | @FILE | -) [--re ID] [--kind note|task] [--needs-answer] [--nonce N]
fleet msg inbox   [NAME] [--peek] [--json] [--wait S]
fleet msg ack     ID...
fleet msg status  ID
fleet msg queue   [--json]
fleet msg whois   NAME
fleet msg bind    NAME --binding B --nonce N  |  retire NAME --nonce N
fleet msg sync    --peer P (--once | --watch --interval S)
fleet msg serve   --peer SITE        (ssh forced command only)
fleet msg compact
fleet msg import  --dir DIR --to NAME@SITE
```

`inbox --wait` blocks until a message or timeout (exit 3), like `fleet watch`.

## 9. Wake: notice only

Delivery completes before any wake; a wake failure is logged only. The only
wake is a notice line, `FLEET MSG <id> from <from> (<method>). Run fleet
--fleet-home <home> msg inbox.` No body text: content is never injected.

| holder | notice path |
|---|---|
| Claude lane, supervisor | `append_mailbox(sid, notice)`: PostToolUse injects it mid-turn; an idle lane gets it from the drain rule at its next launch; sup-guard wakes an idle supervisor on unread mail |
| Codex (native or mcx), pi | drain rule only: the `## MESSAGES` block in the next composed prompt |
| Interface | none injected; it runs `fleet msg inbox --wait` or `mailman run` |
| unbound role | none; `fleet msg queue` shows it |

- One pending notice per (identity, sender): no new notice while the identity
  has an unread message from that sender.
- `compose_prompt` adds `## MESSAGES` (ids, senders, methods) for the lane's
  identity. It does not mark anything read.
- No adapter steers, forks, dispatches, takes `fleet.lock` or writes the
  registry. To act on an idle body now, the sender runs `fleet send` itself,
  with its own gates. A Claude sender may also `SendMessage` a pointer;
  fleet never does.

## 10. Caller authentication

Same-user homes give provenance, not privilege (§14). `send` stamps
`from_auth.method` from evidence the caller cannot choose by argument:

| method | evidence |
|---|---|
| `lane-registry` | `_registered_lane_mail_sender()` matches exactly one lane |
| `supervisor-nonce` | a live nonce passed the claim-nonce gate |
| `supervisor-sid` | sid equals the claim holder, no nonce (claim-nonce §1.1: a zombie body can share the sid) |
| `interface-registration` | `_registered_interface_mail_source()` |
| `bound-holder` | sid / thread / job equals a named role's binding |
| `unverified` | none of the above |

- `kind: task` from `supervisor` requires `supervisor-nonce`; otherwise
  `send` refuses. Lanes treat only `supervisor-nonce` and
  `interface-registration` tasks as direction.
- **Read and ack** of NAME (non-peek `inbox`, `ack`) require the caller to
  resolve as NAME's holder by the same evidence. Anyone may `--peek`. The
  ledger records the reading body's evidence.
- `bind` and `retire` require `supervisor-nonce` or `interface-registration`;
  a worker turn cannot bind. `msg` joins `GATE_VERBS_ACCEPTING_NONCE`.
- **Across machines** the receiver checks that the transport-authenticated
  peer (ssh key → forced `--peer`; fs home path) is `from`'s site, that the
  peer's `hello` lists `from` as hosted, and `body_sha256`. The inbox prints
  `VERIFIED <from> <method> via <transport>/<peer>` or `UNVERIFIED <reason>`.

## 11. Anti-gridlock

Defaults in `config.json`; every bound is a setting. All run in `enqueue`
before seq allocation, on the sender side. A receiver re-checks `hop`/`path`
only when it holds the parent.

- **Size**: ≤120 words and ≤8 KiB, no override. Longer content goes in a file
  or PR, sent as a link.
- **No reply required** by default; adapters never auto-reply.
- **Hop**: refuse `--re` past `max_hop` (6): "escalate to the supervisor or
  the Interface".
- **Loop**: a `task` cannot go to an identity already in its `path`; four
  alternating `task`s between one pair refuse a fifth.
- **Task budget** per (`from`, `to`), ignoring threads: 4 `task`s per hour.
- **Rate**: 20 messages per hour per (`from`, `to`).
- **Visible queue**: `fleet msg queue` prints per identity unread, unacked,
  needs-answer, oldest age, and per-peer outbox depth and oldest age. Views
  may show counts by directory listing only.

## 12. Migration

1. **Beside.** `fleet msg` ships with mailman, `to-fleet/`, `fleet send` and
   `mail verify` unchanged.
2. **Render.** A message to `interface` is also rendered into
   `mailbox/to-fleet/` as mailman mail (`from`, `kind`, `needs-answer`, `re`,
   `msg-id`). `relay-ack` of a rendered file acks the message.
3. **Import.** `fleet msg import` turns each mailman-format file in an
   outbound directory into an envelope with method `legacy-unverified` and
   moves the original to `done/`.
4. **Bridge.** The mailman bridge command becomes the §7.2 sync argv. The
   operator replaces the local script with `fleet msg send`; the outbound
   directory retires when `import` finds it empty.
5. **Receipts.** `_issue_verified_supervisor_mail` writes an envelope;
   `fleet mail verify <id>` reads the message store first, then the old store.
6. **Retire.** The `to-fleet/` render becomes opt-in.

## 13. Doctrine and tiers

- No `fleet.lock`, no registry write, no steer, no injection outside fleet's
  own bound bodies. Views count files only.
- **Tier: pending operator ruling.** Every `msg` verb appends to
  `ledger.jsonl`, and multi-fleet's E2 ground says an irreversible append is
  an irreversible effect. The ruling must name the ledger's status: an
  operational log (then `send`, `inbox`, `ack`, `status`, `queue`, `whois`
  ordinary; the rest disruptive), or evidence (then `msg` stays destructive).
  Until then `msg` is in no tuple, so it is destructive, and every shipped
  argv carries `--fleet-home`. Per-subcommand tiers need new
  `verb_effect_tier` machinery and its own PR.
- Out of scope in v1: relay through a third site, groups, attachments,
  encryption at rest, fleet calling `SendMessage`.

## 14. Threat model

**Assets**: message integrity and origin, the queue (no loss, no theft of
reads), lane direction (who may task a lane), host capacity (RAM, turns).

**Trust boundaries**: (1) the OS user. All local homes and bodies share it
and can write `state/`; nothing below is a privilege boundary against it.
(2) The ssh peer: an authenticated key pinned to one site label. (3) Relay:
none in v1.

| actor | threat | mitigation | residual |
|---|---|---|---|
| compromised lane | sends `task` as the supervisor | method comes from caller evidence; supervisor tasks need a nonce | a same-user process can write files directly; provenance, not prevention |
| compromised lane | reads or acks another identity's queue | holder check on non-peek inbox and ack; ledger names the reader | direct file moves remain possible; ledger and spool disagree visibly |
| compromised lane | floods or ping-pongs | size, rate, task budget, hop, path, notice coalescing; no steer | 20 notes/hour per pair still cost reader attention |
| compromised lane | injects instructions via notices | notices carry no body; inbox prints the method | an agent may still obey an `UNVERIFIED` body it reads |
| zombie supervisor body | tasks lanes with the live sid | `supervisor-sid` is never direction; tasks need a live nonce | notes from the zombie still arrive, labelled `supervisor-sid` |
| hostile peer site | forges names of another site | the peer may only send names it hosts; no relay | it can say anything as its own identities |
| hostile peer site | replays or floods | markers, stale and future bounds, per-pair rate | disk growth until compaction |
| network attacker | tampers or replays on the wire | ssh channel; frame sha; dedup | none beyond ssh's own |
| misconfigured forced command | client chooses its own site | `serve` refuses without `--peer`; live test pins it | a wrong `--peer` in `authorized_keys` trusts the wrong site |
