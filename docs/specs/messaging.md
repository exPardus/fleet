# Spec: `fleet msg` — one messaging layer for every harness

**Status:** revision 2 after review. Build plan:
`docs/plans/messaging-plan.md`. **Built (plan PR 1):** §4 envelope, §5 store
paths and the `publish()`/`enqueue()` primitives in `bin/fleet_msg_core.py`,
`ingest()`, the one receiver path, and the §7 `Transport` Protocol in
`bin/fleet_msg_transport.py` (§5.1 lists
what PR 1 fixed that this spec left open). **Built (plan PR 3):** the §11
rules as pure functions in `bin/fleet_msg_rules.py` (§11.1). **Built (plan PR 4):**
the §7.1 fs transport in `bin/fleet_msg_fs.py` (§7.1.1). **Built (plan PR 5):** the §9 notice and
`## MESSAGES` block as functions in `bin/fleet_msg_wake.py` (§9.1). Every other section is proposed,
not built; no `fleet msg` verb ships yet. Where this spec and later code differ, the
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

- Grammar `^[a-z][a-z0-9-]{0,39}$`; qualified form `name@site`. A site
  label uses the same grammar.
- An unqualified name always means the local site. No cross-site search.
- A **site** is one home's label, set by `fleet msg init --site LABEL`. `init`
  and `sync` refuse a label that another listed home uses; `hello` refuses a
  peer with the local label. Labels are local config; tracked files name none.

| identity | holder resolved at each read | file |
|---|---|---|
| lane `<worker>` | the registry row's current sid, Codex thread or pi job (read lock-free) | none: implicit from the row; its epoch is the row's `created` value |
| `supervisor` | the claim holder (INCARNATION) | none |
| `interface` | the current Interface registration | none |
| `ops` and other named roles (`hub`, `reviewer`, …) | `lane:<worker>` (resolved through the registry, as a lane identity is) or, only for a body outside the registry, a concrete `session:<sid>`, `codex-thread:<id>` or `pi-job:<id>` | `ids/<name>.json` `{schema, name, role, binding, epoch, bound_at, bound_by}` |

Lane, supervisor and interface identities follow fork-steer, respawn,
handoff and reboot with no rebind, because the registry, the claim and the
registration already follow them. A named role bound `lane:<worker>` follows
the same way, so after a fork-steer the retired body fails the holder check and
the live body passes with no rebind. Only a concrete binding needs
`fleet msg bind` after a body swap. `ops` is its own identity with its own
queue; unbound, it queues. Each bind increments `epoch` and appends a `bound`
ledger line.

**Archived lanes.** A send to an archived lane is `rejected: retired`. On
archive the lane's spool moves to `archive/`, so a reused worker name starts
with an empty queue.

## 4. Envelope

One JSON object, UTF-8, canonical form `json.dumps(sort_keys=True,
separators=(",", ":"))`. Immutable once written. Stored and transferred bytes
equal the canonical form; other bytes are `rejected: corrupt`. The field set
is exact: a missing or extra field is `rejected: schema`.
`from_auth.detail` is null or printable ASCII of at most 128 characters.

| field | meaning |
|---|---|
| `schema` | `1` |
| `id` | 128-bit random hex, sender-minted once per logical send; every retry reuses it. The **dedup key**. Never compared by order. |
| `from`, `to` | `name@site` after resolution |
| `from_auth` | `{method, detail}` set by the sending site from caller evidence (§10) |
| `kind` | `note` (default), `task`, `receipt` |
| `needs_answer` | default `false` |
| `re`, `thread` | parent id or null; root id (a root's `thread` is its own `id`) |
| `hop`, `path` | parent `hop` + 1 (root 0); the senders of the thread chain, root first and ending at `from`, so `len(path) = hop + 1` (sender-enforced, §11) |
| `seq` | per (`from`, `to`) counter (§5) |
| `sent_at` | sender clock, advisory, `YYYY-MM-DDTHH:MM:SSZ` |
| `body`, `body_sha256` | ≤120 words, ≤8 KiB |

Receiver facts (`received_at` by the receiver's clock, `via`, state) live in
the ledger and beside the envelope, never inside it.

## 5. Store layout and the two write primitives

Under each home's ignored `state/msg/`:

```
site.json, peers.json, config.json
ids/<name>.json              named roles only
locks/from-<name>.lock       sender lock (OS-released, mailman's lock backend)
locks/spool-<name>.lock      ingest lock, one per spool
locks/outbox-<site>.lock     one per outbox: qseq allocation and file write
seq/<from>__<to>             last seq allocated (both `name@site`)
outbox/<site>/qseq           last qseq allocated
outbox/<site>/tmp/           private tmp names
outbox/<site>/q/<qseq>-<id>.json   waiting for a remote site; qseq 12 digits
outbox/<site>/sent/          moved here when the peer confirms
spool/<name>/tmp|new|cur|done/<id>.json
rejected/<id>-<sha16>.json   with reason and the original bytes
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
message. A crash after step 2 leaves a file and no marker. Step 1 of the next
ingest repairs it: it creates the marker and runs step 3's ledger line and the
§9 notice once, then returns `duplicate`. The lock removes the
concurrent-ingest race.

**`enqueue(from, to, envelope)`**, under `locks/from-<name>.lock`: run every §11
rule first, then allocate `seq` (read, increment, write a unique tmp name,
fsync, rename), then `publish` (local `to`) or, for a remote `to`, take
`locks/outbox-<site>.lock`, allocate `qseq` and write
`outbox/<site>/q/<qseq>-<id>.json` with fsync inside that one lock. Visibility
order therefore equals `qseq` order. A refusal allocates nothing, so a refused
send leaves no seq gap.

No path takes `fleet.lock` or writes the registry.

### 5.1 Built contract (plan PR 1)

PR 1 fixed these points, which the text above left open:

- **Lock names carry a fixed prefix** (`from-`, `spool-`, `outbox-`).
  Revision 2 named the sender lock `locks/<identity>.lock`; an identity named
  `spool-x` then shared the ingest lock of spool `x`, and a send from
  `spool-x` to `x` deadlocked on its own lock. Lock order is always sender
  lock, then spool or outbox lock. Lock files are never unlinked.
- **`qseq` has its own counter** `outbox/<site>/qseq`, allocated like `seq`.
  Deriving it from a listing of `q/` and `sent/` would reuse numbers after
  `compact` moves `sent/` away.
- **Signatures**: `publish(store, name, env, notify=None)` returns
  `delivered` or `duplicate`; `enqueue(store, draft, rules=None,
  notify=None)` returns `delivered`, `duplicate` or `queued` with the
  envelope. `rules(draft)` returns a refusal reason or None and runs under
  the sender lock before any allocation. `notify(name, env)` is the §9 hook;
  it runs after every lock (sender and spool) is released, so a hook may
  itself send, and its failure is a `notice-failed` ledger line only.
- **Retry dedup at the sender.** Before allocating, `enqueue` looks for the
  id: locally the marker or the spool file, remotely `outbox/<site>/q|sent`.
  A found id returns the stored envelope (`duplicate`, or `queued` while
  still in `q/`) and allocates no seq or qseq, so one id never maps to two
  byte strings.
- **`ingest(store, raw, peer_site, hosted, now, admit, notify)`** is the
  one receiver path. Every transport calls it and nothing lower. In order:
  the raw size bound, `parse`, `to` names this site, `from` is on the
  transport-authenticated `peer_site` and in its hosted names (`auth`), the
  §6 clock bounds (`future`, `stale`), `admit(env)` for the §11 per-peer
  ingest cap and retired lanes (supplied by later PRs), then `publish`. A
  refusal goes to `reject()`. It returns the §7 push-result vocabulary:
  `accepted`, `duplicate`, `rejected:<why>`.
- **Hostile bytes.** `parse` checks `ENVELOPE_MAX_BYTES` (64 KiB, above the
  largest valid envelope) before decoding, and every failure is an
  `EnvelopeError` with a §6 reason, never another exception: a peer cannot
  wedge a queue with one unclassifiable entry. Digit classes are ASCII only.
  `outbox_entries` reads at most the bound plus one byte per entry and skips
  an entry a concurrent commit moved to `sent/`.
- **No symlinks under `state/msg/`.** Every directory component is checked
  with `lstat`; lock, tmp, marker and counter files open with `O_NOFOLLOW`;
  the ledger, spool and outbox entries must be regular files. A planted
  link is refused with `StoreError`, never followed, and never yields a
  marker without a message.
- **Directory fsync** goes through `PLATFORM.fsync_dir`: on POSIX every
  error raises; on Windows it is a documented no-op in the adapter only.
- **Renames never overwrite.** `move` and `outbox_commit` refuse an existing
  target under the owning lock.
- **Rejects never collide.** A rejected envelope is kept as
  `rejected/<id>-<sha256[:16]>.json` (`sha-<sha256[:32]>.json` without an
  id), so distinct bytes claiming one id are all kept; an identical re-reject
  writes nothing and logs nothing.
- **Reads and acks** move a file `new → cur` or `cur → done` with `move()`,
  under the same spool lock as ingest, so an ingest never sees the file in
  neither state.
- **Crash windows after the marker.** A crash after step 2 is repaired
  exactly once, as above. A crash between the marker and the ledger line
  loses that ledger line; a crash between the ledger line and the notice
  loses the notice (the drain rule still lists the message). Neither
  duplicates or loses the message.
- **Outbox reads and commits**: `outbox_entries(site, hint_qseq)` returns
  every entry in `q/` ascending (the hint never filters);
  `outbox_commit(site, ids)` moves exactly those ids to `sent/` under the
  outbox lock.
- **Ledger appends** use `fleet_platform.PLATFORM.atomic_append_bytes`, the
  backend `_atomic_append_bytes` calls, because the new modules never import
  `bin/fleet.py`.
- Reject reasons are those of §6 plus `retired` (§3).

## 6. Delivery, receipts, retention

```
queued ──transfer──▶ delivered ──inbox──▶ read ──ack──▶ acked
   └────────────────▶ rejected (size, rate, auth, stale, future, schema, corrupt)
```

- `send` prints `DELIVERED <id>` (local) or `QUEUED <id>` (remote).
- `inbox` moves `new → cur`; `--peek` moves nothing; `--all` also lists
  `cur/` (read, not acked) with the reader the ledger names. `ack` moves
  `cur → done`.
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
  files into `archive/<yyyymm>/` (packed, never dropped). A `done/` file is
  archived only when its marker exists. Any purge sits
  behind one `purge` seam, off by default, and needs an explicit setting.

## 7. Transport interface

```python
class Transport(Protocol):
    def hello(self, local: SiteInfo) -> SiteInfo: ...              # versions, clock, hosted identities
    def push(self, envelopes: list[bytes]) -> dict[str, str]: ...  # id -> accepted|duplicate|rejected:<why>
    def pull(self, hint_qseq: int) -> list[tuple[int, bytes]]: ...   # every entry still in q/, ascending
    def commit(self, ids: list[str]) -> None: ...                  # exactly these ids were published
    def close(self) -> None: ...
```

`commit` names ids, never a high-water mark. `pull` returns every entry still
in `q/` (committed entries are already in `sent/`); `hint_qseq` only orders
paging and never filters. With the per-outbox lock (§5), no entry can be
skipped. The peer moves only committed ids to `sent/`. `peers.json`
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

#### 7.1.1 Built contract (plan PR 4)

`bin/fleet_msg_fs.py` implements the five methods as `FsTransport(store,
peer_home, peer_site, prims)`. Fleet helpers come in as `prims`
(`hosted(home)` lists the identities a home hosts); the module imports only
`fleet_msg_core` and `fleet_msg_transport`. The sync driver, not this module,
calls `ingest()` on each pulled entry and then `commit()`.

- **`site.json`** holds `{"site": LABEL}`. `hello` refuses a peer whose label
  differs from the one in `peers.json`, or equals the local one. The reported
  clock is the local one: both homes share a machine, so fs never warns of skew.
- **Read-only peer.** `pull` and `commit` only read the peer's tree. A symlinked
  component under `state/msg/` or a symlinked entry makes `pull` or `commit`
  raise `TransportError`: the chain is checked at the start of each call. A
  swap between that check and the read is not defended (same-user homes get
  provenance, not privilege, §14).
- **`entry_id(qseq)`** returns the id in an entry's file name after `pull`, so
  the driver can commit an entry whose bytes do not parse.
- **Corrupt files.** Only `corrupt` (not JSON, non-canonical, `body_sha256`
  mismatch) is retried. `pull` withholds such an entry on its first two passes
  and returns it on the third, so `ingest()` keeps it as `rejected: corrupt`.
  The count lives in `state/msg/fs-strikes/<peer>/<id>`, so it survives
  `sync --once`; its unit is one `pull` call, so concurrent syncs or a retried
  `pull` add strikes faster. Other failures (`schema`, `size`) are returned at
  once.
- **Receipts.** `commit(ids)` writes one `kind: receipt` envelope per id
  through `enqueue()`: from the original `to`, to the original `from`, `re` the
  original id, body `delivered` or `rejected: <why>` (the reason from the local
  `rejected/` record), `from_auth` `unverified` with detail `receipt`. An id
  the home neither published nor rejected gets none. Receipt ids are derived
  from the id they answer (first 32 hex of a sha256), so a re-emitted
  `delivered` finds the stored receipt and makes no second one. Committing a
  receipt moves the local envelope it answers to `sent/`; a receipt is never
  receipted.
- **Settling.** Each `pull` moves a local receipt entry to `sent/` once the
  envelope it answers is no longer in the peer's `q/`. When the peer's `q/`
  directory is absent, `pull` settles nothing.
- **No receipt.** A corrupt entry never reaches a parseable `from`. An entry
  that fails `schema` (for example a future `SCHEMA`) or `size` is
  unparseable here, so `commit` finds nothing to answer. All three stay in the
  sender's `q/`, are re-pulled each pass, and show only as queue age in
  `fleet msg queue`. So does an envelope whose id another sender already used
  (ids are global, §5): the home's `delivered` is for the stored envelope's
  sender only, so the second sender gets no receipt and a `receipt-withheld`
  ledger line records it.

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
  `pull(hint_qseq)` → `batch` → client publishes → `commit(ids)` → `bye`.

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
fleet msg inbox   [NAME] [--peek] [--all] [--json] [--wait S]
fleet msg ack     ID...
fleet msg status  ID
fleet msg queue   [--json]
fleet msg ids     | whois NAME
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

### 9.1 Built contract (plan PR 5)

`bin/fleet_msg_wake.py` holds the wake as functions over an injected
`WakePrims` (`fleet_home`, `adapter_of(name)`, `holder_sid(name)`,
`append_mailbox(sid, text)`). It imports only `fleet_msg_core`, takes no lock
and writes no registry.

- **Notice.** `notice_line(env, home)` is the §9 line: id, sender, method. It
  never holds a body. `make_notify(store, prims)` is the `notify` hook for
  `publish()`; a failure raises and `publish()` logs `notice-failed`.
- **Per adapter.** `adapter_of` returns `claude`, `codex`, `pi`, `interface`
  or `unbound`. Only `claude` with a holder sid gets `append_mailbox`. The
  others return `drain-only`: their wake is the drain block or `msg inbox`.
- **Coalescing.** `notice_due`: no notice while another message from the same
  sender is in the identity's `new/`. After a read the next message notices.
- **Drain block.** `drain_block(store, prims, name)` returns `## MESSAGES`, one
  `- <id> from <from> (<method>)` line per unread message (at most 20, then
  `- ... N more`), and the inbox command; `""` when nothing is unread. It
  lists `new/` only and moves nothing.

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
  `send` refuses.
- **Direction** is decided by the receiving site, never by the stamp alone. A
  `task` is direction only when it is (a) `supervisor-nonce` from the
  receiver's own site, (b) `interface-registration` from the site named in
  `config.json` `interface_site`, or (c) from a peer that `peers.json` marks
  `direct: true`. Any other `task` is shown and handled as a note, labelled
  `remote-task`.
- **`detail` carries no secret.** For a nonce it holds at most `nonce_seq`
  and an 8-hex sha prefix (claim-nonce §5.9); never the nonce. The ledger
  follows the same rule.
- **Read and ack** of NAME (non-peek `inbox`, `ack`) require the caller to
  resolve as NAME's holder by the same evidence. For `supervisor` that
  evidence is `supervisor-sid` (a nonce per read is too costly); the ledger
  names the reading body, and `inbox --all` shows what another body read.
  Anyone may `--peek`.
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
- **Rate**: 20 messages per hour per (`from`, `to`), and at most 200
  ingested envelopes per hour per peer site (`rejected: rate`), however many
  names the peer hosts.
- **Visible queue**: `fleet msg queue` prints per identity unread, unacked,
  needs-answer, oldest age, and per-peer outbox depth and oldest age. Views
  may show counts by directory listing only.

### 11.1 Built contract (plan PR 3)

`bin/fleet_msg_rules.py` holds every rule above as a pure function: inputs,
including the clock and the history of earlier sends, are arguments, and the
result is a refusal string `"<code>: <message>"` or None. It reads no file,
takes no lock and imports only `fleet_msg_core`.

- **Hooks.** `make_rules(limits, history, clock)` returns the `rules(draft)`
  hook for `enqueue()`; `make_admit(...)` returns the `admit(env)` hook for
  `ingest()` (`retired`, and `rate` past the per-peer cap). The caller reads
  the history: `history(draft)` returns the (from, to) pair's earlier sends,
  both directions, as `Sent(ts, frm, to, kind)`.
- **Settings** in `config.json`: `max_hop` (6), `task_budget` (4),
  `rate` (20), `peer_ingest` (200), `loop_alternating` (4). A value is an
  integer of at least 1; a bad value raises `RulesError`. Size is not a
  setting: ≤120 words and ≤8 KiB, no override.
- **Windows.** Rate, task budget and ingest cap count entries newer than one
  hour (an entry exactly one hour old no longer counts). The sender bounds are
  per (`from`, `to`) pair: the 20th message in an hour is sent, the 21st is
  refused; the 4th task is sent, the 5th is refused; the 200th envelope from a
  peer is accepted, the 201st is `rejected: rate`.
- **Hop and loop.** A reply whose `hop` exceeds `max_hop` is refused
  (`hop`). A `task` to an identity in its `path` is refused (`loop`), and so
  is a task that would continue four alternating tasks between one pair.
- **Receipts** are system traffic: only the size rule checks them, and they
  do not count toward rate, budget or the ingest cap (`check_admit` accepts a
  receipt past the cap; the caller leaves receipts out of `recent_ts`). A draft
  is a receipt only with `re` set and body `delivered` or `rejected: <reason>`
  (a §6 reason); any other `kind: receipt` draft is refused as `schema`. PR 6
  `send` never accepts `--kind receipt`, and no adapter auto-replies
  (`core.NEEDS_ANSWER_DEFAULT` is False; pinned in PR 6).
- **Clock steps.** The windows have no upper bound: an entry stamped after
  `now` (clock stepped back) still counts. `max_hop` cannot exceed
  `PATH_MAX - 1` (63); a larger value raises `RulesError`.
- **Notice coalescing** (§9) is `notice_due(unread_from_sender)`.

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
- **Tiers: ruled (operator, 2026-11-18).** `ledger.jsonl` is an operational
  log, not evidence, so the E2 ground does not apply to its appends.
  Ordinary: `send`, `inbox`, `ack`, `status`, `queue`, `ids`, `whois`, and
  `init` by residual (like `fleet init`). Disruptive: `bind`, `retire`,
  `sync`, `serve`, `import`, `compact`. Destructive: a future `purge`.
- **"Operator-confirmed" means confirmed at setup**, not per call: `sync`
  and `serve` run unattended, so the confirmation is the operator writing
  `peers.json` and `authorized_keys`; `bind`, `retire` and `import` also need
  `supervisor-nonce` or `interface-registration`.
- Per-subcommand tiers need new `verb_effect_tier` machinery (plan PR 12).
  Until it lands, `msg` is in no tuple and every shipped argv carries
  `--fleet-home`.
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
| compromised lane | copies a pending id from a peer's outbox and sends it first | the receiver never confirms `delivered` to a sender other than the stored envelope's | the real message is `duplicate` and not delivered; it shows as queue age, not loss without trace (ids and markers are global, §5) |
| compromised lane | injects instructions via notices | notices carry no body; inbox prints the method | an agent may still obey an `UNVERIFIED` body it reads |
| zombie supervisor body | tasks lanes with the live sid | `supervisor-sid` is never direction; tasks need a live nonce | notes from the zombie still arrive, labelled `supervisor-sid` |
| zombie supervisor body | reads the supervisor queue first | ledger names the reading body; `inbox --all` shows read-but-unacked messages to the live body | the zombie sees the content; reads are not secret between same-sid bodies |
| retired lane body after fork-steer | reads a named role's queue | `lane:<worker>` bindings resolve to the registry's live sid | a concrete binding still needs a rebind |
| hostile peer site | forges names of another site | the peer may only send names it hosts; no relay | it can say anything as its own identities |
| hostile peer site | directs local lanes with a `task` stamped `supervisor-nonce` | direction only from the local supervisor, the named Interface site, or a `direct: true` peer; otherwise `remote-task` note | a `direct: true` peer is trusted fully |
| hostile peer site | replays or floods | markers, stale and future bounds, per-pair rate, 200/h per-peer ingest cap | disk grows by at most the cap; compaction packs and never deletes, so the operator watches `queue` |
| same-user process | plants a symlink under `state/msg/` to redirect writes or swallow an id | every component is `lstat`-checked, files open `O_NOFOLLOW`, a planted link is refused; never a marker without a message | it can still edit or move regular files directly (boundary 1) |
| hostile peer site | sends an oversized, deeply nested or invalid-UTF-8 envelope to wedge the queue | size bound before decode; every parse failure is a classified reject | none beyond disk use of the kept reject |
| any body | leaks a nonce through `detail` or the ledger | `detail` holds only `nonce_seq` and an 8-hex prefix | none |
| network attacker | tampers or replays on the wire | ssh channel; frame sha; dedup | none beyond ssh's own |
| misconfigured forced command | client chooses its own site | `serve` refuses without `--peer`; live test pins it | a wrong `--peer` in `authorized_keys` trusts the wrong site |
