# Spec: `fleet msg` — one messaging layer for every harness

**Status:** proposed, not built. Build plan: `docs/plans/messaging-plan.md`.
Where this spec and later code differ, the code is the authority and this file
is updated in the same PR.

**Builds on:** `docs/specs/mailman.md` (mail format, crash-safe filing,
classification), `docs/specs/peer-messaging.md` (`fleet address`, native
`SendMessage`), `docs/specs/multi-fleet.md` (homes list, verb-effect tiers,
no cross-home writes), `docs/SPEC.md` §9 (mailbox, receipt-backed Interface
mail, lane labels). Root `CLAUDE.md` rules hold: stdlib only, Python 3.10,
pull-only, views never take `fleet.lock`.

## 1. Problem

Fleet has partial channels: `fleet send` steers one worker of one home;
`mailbox/<sid>.md` carries mid-turn text to Claude lanes; `mailbox/to-fleet/`
plus `mailman` sorts Interface mail; cross-machine mail is an operator-local
script writing mailman-format files into an outbound directory that the other
machine copies over ssh. None addresses a stable name, survives a body swap,
gives a receipt, or works the same for Claude, Codex and pi.

`fleet msg` is one store-and-forward layer. Any agent sends to a name. The
message is durable before `send` returns. A wake is a best-effort nudge after
delivery, never the delivery.

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
| `_atomic_append_bytes`, `_write_json_atomic`, mailman's claim-then-link move | **Reused** for every store write (§5). |
| `_registered_interface_mail_source`, `_registered_lane_mail_sender`, supervisor claim holder | **Reused** as sender authentication (§10). |
| `append_mailbox` + PostToolUse injection + the universal drain rule | **Reused** as the Claude wake adapter (§9). |
| `_cmd_send_codex_native`, mcx steer, `fleet_pi.py steer` | **Reused** as the Codex and pi wake adapters. |
| `fleet address` + `SendMessage` | **Kept** as an optional accelerator. |
| mailman `classify` and `mailman.json` | **Reused** to sort the Interface's inbox (WAKE/FILE). |
| `fleet send` | **Kept** unchanged: it is steering (dispatch, fork-steer, gates), not messaging. |
| `state/mail-receipts/` + `fleet mail verify` | **Folded**: the stored envelope is the receipt; `mail verify` reads both stores during migration (§12). |
| Operator-local outbound directory + shell script + mailman bridge pull | **Replaced** by `fleet msg send` and the ssh transport (§8). |
| `mailbox/to-fleet/` | **Kept** during migration as a rendered view for mailman and `watch`. |

## 3. Identities and holder binding

An **identity** is a stable name. A **holder** is the body that reads for it
now. Messages address identities, never bodies.

- Name grammar: `^[a-z][a-z0-9-]{0,39}$`. Qualified form `name@site`.
- A **site** is one fleet home's messaging label, set once by
  `fleet msg init --site LABEL`. Labels are operator-chosen and local; tracked
  files never name a real host.
- Identity record: `state/msg/ids/<name>.json`
  `{schema, name, role, binding, epoch, bound_at, bound_by}`.
- Roles: `lane`, `supervisor`, `interface`, `ops`, `role` (any other named
  seat such as `hub` or `kernel`). `ops` is first-class: it has its own
  inbox and binding, and is not an alias of the supervisor.

**Bindings are symbolic where possible**, so a body swap needs no rebind:

| binding | resolves at delivery to | survives |
|---|---|---|
| `lane:<worker>` | the registry row's current sid / Codex thread / pi job | fork-steer, respawn, reboot |
| `supervisor` | the current claim holder (INCARNATION) | handoff, succession, reboot |
| `interface` | the current Interface registration | re-register, reboot |
| `session:<sid>`, `codex-thread:<id>`, `pi-job:<id>` | that body | nothing; rebind on swap |
| `follows:<name>` | the holder of another identity (e.g. `ops` follows `supervisor` until bound) | whatever the target survives |

`fleet spawn` creates a lane identity; archive retires it. A role identity
lives from `fleet msg bind` to `fleet msg retire`. An identity with no live
holder still receives; messages queue. Each rebind increments `epoch` and
appends a `bound` ledger line; unread messages stay with the identity.

## 4. Envelope

One JSON object, UTF-8, canonical form `json.dumps(sort_keys=True,
separators=(",", ":"))`.

| field | meaning |
|---|---|
| `schema` | `1` |
| `id` | sender-minted, time-ordered: 48-bit ms timestamp + 80 random bits, hex. The **dedup key**. Minted once per logical send; every retry reuses it. |
| `from` | `name@site` of the sender identity |
| `from_epoch` | sender identity epoch at send |
| `to` | `name@site` after resolution |
| `kind` | `note` (default), `question`, `task`, `answer`, `receipt` |
| `needs_answer` | default `false` |
| `re` | id of the message answered, or `null` |
| `thread` | root id (`id` when `re` is null) |
| `hop` | 0 for a new thread; parent `hop` + 1 for `re` |
| `path` | identities this thread has visited, in order, capped at `max_hop` + 1 |
| `seq` | per (`from`, `to`) monotonic counter, sender-side |
| `sent_at` | sender clock, ISO-8601 UTC, advisory only |
| `words`, `body`, `body_sha256` | body and its integrity check |
| `auth` | `{method, site, detail}` written by the sending site (§10) |

The envelope is immutable. Receiver facts (`received_at`, `via`, state) live
beside it.

## 5. Store layout

Under each home's ignored `state/msg/`:

```
site.json                  site label, protocol version
peers.json                 transports per peer site (operator-local)
ids/<name>.json            identity + binding
outbox/<site>/<id>.json    envelopes waiting for a remote site
spool/<name>/tmp/          in-flight writes, ignored by readers
spool/<name>/new/<id>.json delivered, unread
spool/<name>/cur/<id>.json read, not acked
spool/<name>/done/<id>.json acked
rejected/<id>.json         refused on ingest, with reason
seen/<id[:4]>/<id>         dedup markers (exclusive create)
seq/<from>__<to>           last seq sent
ledger.jsonl               append-only: sent, delivered, read, acked, rejected, bound
```

Publish is write `tmp/`, fsync, `rename` into `new/` (maildir). `new → cur →
done` are renames inside one spool. Ledger lines use `_atomic_append_bytes`;
JSON records use `_write_json_atomic`. No `fleet.lock`: the registry is read
lock-free, as mailman does. Binds serialise on `ids/<name>.lock`.

## 6. Delivery, receipts, acks

```
queued ──transfer──▶ delivered ──inbox──▶ read ──ack──▶ acked
   │                     │
   └──────────────▶ rejected (size, hop, path, rate, auth, stale, schema)
```

- **queued**: in `outbox/` (remote only). `send` prints `QUEUED <id>`.
- **delivered**: in `spool/<name>/new/`, the durable point. A local `send`
  prints `DELIVERED <id>`.
- **read**: `fleet msg inbox` moved it to `cur/` (`--peek` does not).
- **acked**: `fleet msg ack <id>` moved it to `done/`.
- **Receipts** are `kind: receipt` envelopes (`delivered`, `read`, `acked`,
  `rejected` + reason) routed back to `from`. A receipt never produces a
  receipt. `fleet msg status <id>` prints the latest state the sender knows.

**Guarantees.** At-least-once transfer, exactly-once delivery per site.
Ingest first creates `seen/<id>` (`O_CREAT|O_EXCL`); an existing marker is
`duplicate`, which the sender treats as success. A marker without a spool file
(crash between the two) is repaired on the next ingest from the source, which
still holds the envelope. Markers live `dedup_days` (default 30); older
`sent_at` is rejected `stale`.

**Ordering.** FIFO per (`from`, `to`) by `seq`. A gap is shown (`gap: seq 7
missing`) and blocks nothing. No global order; `re`/`thread` give causal order.
No order uses `sent_at`, so clock skew reorders nothing.

## 7. Transport interface

One interface in `bin/fleet_msg_transport.py`; the core never knows which
transport runs.

```python
class Transport(Protocol):
    def hello(self, local: SiteInfo) -> SiteInfo: ...          # versions, clocks, identity lists
    def push(self, envelopes: list[bytes]) -> dict[str, str]: ...  # id -> accepted|duplicate|rejected:<why>
    def pull(self, cursor: str | None) -> tuple[list[bytes], str]: ...
    def commit(self, cursor: str) -> None: ...                  # peer may drop what it sent up to cursor
    def close(self) -> None: ...
```

`peers.json` maps `<site>` to `{"transport": "fs"|"ssh", ...}`. A later
transport (for example tailnet) implements the same five methods under a new
`transport` value. Same-home delivery skips the transport.

### 7.1 fs transport (homes on one machine)

Pull-only, so it adds **no cross-home write** (multi-fleet M1):

- A sender writes only its own home: `outbox/<site>/<id>.json`.
- The recipient home's `fleet msg sync` (also run by `inbox`) reads peer
  outboxes listed through `~/.claude/fleet-homes.list`, ingests envelopes
  addressed to its identities, and writes receipts into its own outbox.
- The sender drops an outbox entry when it reads a `delivered` or
  `rejected` receipt for it.

Readers ignore `tmp/` and dotfiles. An envelope failing JSON or
`body_sha256` is retried, then `rejected: corrupt` after three passes.

### 7.2 ssh transport (two machines, one dials)

The reachable machine is the **server**. The other machine is the **client**
and is the only side that dials. Nothing assumes the server can reach the
client.

- Client: `fleet msg sync --peer <site>` runs
  `ssh -p <port> <alias> fleet msg serve` (port and alias from `peers.json`;
  a non-default port is expected). One connection carries push and pull.
- Server: `authorized_keys` pins the key to a forced command,
  `command="fleet msg serve --peer <client-site>",restrict`. The **server
  decides the client's site from the key**, never from the client's words.
- Protocol on stdin/stdout, one frame per line:
  `{"op", "len", "sha256"}` header then exactly `len` bytes. Ops:
  `hello`, `push`, `result`, `pull`, `batch`, `commit`, `bye`.
- Session: `hello` both ways → client `push` its `outbox/<server-site>/`
  → server ingests, answers `result` per id → client `pull` with its cursor
  → server sends `batch` of envelopes and receipts queued for the client site
  → client ingests, sends `commit` → `bye`.
- **Relay**: the server stores envelopes for other client sites in its own
  `outbox/<site>/` until those clients dial. One relay hop only.

**Failure handling.**

| failure | effect |
|---|---|
| connection drops mid-push | un-`result`ed ids stay in the client outbox; resent next session; server dedups |
| drop mid-pull | no `commit`; server resends the batch; client dedups |
| partial or corrupt frame | length or sha mismatch: frame discarded, session ends non-zero, nothing published |
| server unreachable | `sync` exits 4 after `max_failures` consecutive failures (same contract as the mailman bridge); queue stays visible |
| clock skew | `hello` exchanges clocks; skew over 300 s prints a warning; ordering and dedup never use clocks; `stale` uses a 30-day window |
| replay of old frames | ssh protects the channel; inside it, `seen/` markers make a replayed id a `duplicate`; ids older than `dedup_days` are `stale` |
| server site sends as a name it does not host | rejected `auth` on the client (directory check, §10) |

Client wake latency is its sync interval. The client runs `fleet msg sync
--peer P --watch --interval S` under the caller's background runner, or as the
mailman bridge command `["fleet","msg","sync","--once"]`. No daemon.

## 8. CLI

```
fleet msg init   --site LABEL
fleet msg send   TO (TEXT | @FILE | -) [--re ID] [--kind K] [--needs-answer] [--long] [--as NAME]
fleet msg inbox  [NAME] [--peek] [--all] [--json] [--wait S]
fleet msg ack    ID... [--note TEXT]
fleet msg status ID
fleet msg queue  [--all-sites] [--json]
fleet msg ids    | whois NAME
fleet msg bind   NAME --binding B [--role R]   |   retire NAME
fleet msg sync   [--peer P] [--once | --watch --interval S]
fleet msg serve  --peer SITE          (ssh forced command only)
```

The sender is resolved from the caller (§10); `--as` must name an identity
the caller provably holds. `inbox --wait` blocks until a message or timeout
(exit 3), like `fleet watch`.

## 9. Wake adapters

Delivery completes before any wake; a wake failure is logged only. The
adapter follows the holder's harness and the identity's `wake` policy:
`notice` (default), `steer`, `none`.

| holder | notice | steer (only `kind: task` from the holder's supervisor or the Interface) |
|---|---|---|
| Claude lane (bg) | `append_mailbox(sid, "FLEET MSG <id> from <from>: <first 80 chars>. Run fleet msg inbox.")`; PostToolUse injects it mid-turn; idle lanes get it through the drain rule at the next launch | through the existing `fleet send` gates (fork-steer or native) |
| Codex native lane | same notice through the `_cmd_send_codex_native` followup path while a turn runs | existing native steer |
| Codex mcx / pi lane | notice composed into the next steer or respawn prompt (drain rule) | `mcx steer` / `fleet_pi.py steer` with the notice |
| Supervisor | notice into its mailbox; the keeper's existing wake picks up `idle+mail` | existing supervisor wake |
| Interface (interactive) | none injected; the Interface runs `fleet msg inbox --wait` or `mailman run` itself | never |
| Unbound identity | none; queue visible in `fleet msg queue` | never |

**Drain rule extended.** `compose_prompt` adds a `## MESSAGES` block (unread
ids, senders, first lines) for the lane's identity. It does not mark read.

**Native accelerator.** A Claude sender may follow a send with
`SendMessage(to=<fleet address>, "msg <id> waiting")`. Fleet never calls it;
its absence loses nothing.

**Pull-only.** Adapters touch only bodies fleet dispatched and bound, through
channels they already accept. Nothing reaches any other session.

## 10. Security and verification

**Not a privilege boundary.** Homes on one machine share one OS user who can
write `state/` (SPEC §17b). Verification is provenance and integrity, as for
`fleet mail verify`. Message text is never authority by content.

**Sending as a name (local).** `send` sets `auth.method` from evidence the
caller cannot pick by argument:

| method | evidence |
|---|---|
| `lane-registry` | `_registered_lane_mail_sender()` matches exactly one lane |
| `supervisor-claim` | caller is the current claim holder |
| `interface-registration` | `_registered_interface_mail_source()` |
| `bound-holder` | caller's sid / thread / job equals the identity's concrete binding |
| `unverified` | none of the above; delivered, shown as `UNVERIFIED` |

**Who may bind.** Lane identities: only `spawn`/`respawn`/`archive`. `bind` and
`retire` for role identities require the supervisor claim holder (nonce gate)
or the registered Interface. A worker turn cannot bind.

**Across machines.** A site vouches only for identities it hosts. The
receiver checks that the transport-authenticated peer (ssh key → forced
`--peer`, or fs home path) is `from`'s site, that `hello`'s directory lists
`from` there, and `body_sha256`. Failure is `rejected: auth`. The inbox prints
`VERIFIED <from> via <method>/<transport>` or `UNVERIFIED <reason>`.
Interface direction to a supervisor keeps its existing rule: act only on a
`VERIFIED … interface-registration` message.

## 11. Anti-gridlock

Defaults live in `state/msg/config.json`; each is a setting.

- **Size**: body at most 120 words and 8 KiB. Over the bound `send` refuses and
  says "put it in a file or PR and send the link". `--long` raises the bound to
  600 words and is marked in the inbox.
- **No reply-required default**: `needs_answer` is false unless set. Wake
  adapters never auto-reply.
- **Hop guard**: `send --re` refuses at `hop > max_hop` (default 6) with
  "escalate to the supervisor or the Interface instead".
- **Loop guard**: a `task` cannot be sent to an identity already in its
  `path`. A thread whose last four messages alternate between the same two
  identities with `kind: task` refuses a fifth (ping-pong).
- **Rate**: at most 20 messages per hour per (`from`, `to`); over it, refuse.
- **Receipts** never produce receipts or wakes.
- **Visible queue**: `fleet msg queue` prints per identity unread, unacked,
  needs-answer, oldest age, and outbox depth per peer. `status_snapshot()` may
  add counts by directory listing only.

## 12. Migration

1. **Ship beside.** `fleet msg` lands with mailman, `to-fleet/`, `fleet send`
   and `mail verify` unchanged.
2. **Render for mailman.** A message delivered to `interface` is also rendered
   into `mailbox/to-fleet/` as mailman-format mail (`from`, `kind`,
   `needs-answer`, `re`, plus `msg-id`). `relay-ack` of a rendered file acks the
   message. Mailman's rules keep working unchanged.
3. **Import legacy mail.** `fleet msg import --dir <outbound dir> --to <name@site>`
   turns each mailman-format file into an envelope with
   `auth.method: legacy-unverified` and files the original into `done/`. It
   reads the same headers the operator-local script writes.
4. **Swap the bridge.** The mailman bridge command becomes
   `fleet msg sync --once`. The operator replaces the local script with
   `fleet msg send`. The outbound directory is retired once `import` finds it
   empty.
5. **Fold receipts.** `_issue_verified_supervisor_mail` writes an envelope
   instead of `state/mail-receipts/<id>.json`; `fleet mail verify <id>` reads
   the message store first and the old receipt store second, until the old
   store is empty.
6. **Retire.** The `to-fleet/` render becomes opt-in when the Interface reads
   `fleet msg inbox` directly.

## 13. Doctrine

- `fleet msg` verbs never take `fleet.lock` and never write the registry.
- Proposed verb-effect tiers (pending operator ratification, multi-fleet §5):
  `send`, `inbox`, `ack`, `status`, `queue`, `ids`, `whois` ordinary;
  `bind`, `retire`, `sync`, `serve`, `import` disruptive.
- Views (statusline, `/fleet:*`) only count files; they never move a message.
- All runtime data lives under ignored `state/msg/`. Tracked files carry no
  site labels, hosts, ports or keys.
