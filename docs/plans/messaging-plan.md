# Build plan: `fleet msg`

Spec: `docs/specs/messaging.md`. This plan orders the build into small PRs,
splits them across at most three parallel lanes with disjoint files, and
names the tests, risks and exclusions.

Every PR carries its own tests and the doc changes for what it ships (the spec
section it implements moves from "proposed" to "built", plus `docs/SPEC.md`
§9, `docs/cli-reference.md` and `skills/fleet/SKILL.md` rows when a verb
becomes user-visible). Gates for every PR:
`uv run --no-project --python 3.10 --with pytest python -m pytest -q` and the
3.12 equivalent, over the PR's tests plus `tests/test_receipts.py`,
`tests/test_views_doctrine.py`, `tests/test_docs_currency.py`,
`tests/test_doc_claims.py` and `tests/test_public_hygiene.py`.

## 1. Where this sits

Messaging is fleet tooling, not one of the platform's fourteen pieces. It
depends on no platform piece and on no `kernel.v1` contract, and no platform
piece depends on it. **Assumption about the master build plan:** it lists
Track F as a tooling track that may run beside any step, with no ordering edge
into or out of the piece graph. If the master plan instead gates platform lanes
on cross-machine messaging (for example for supervisor coordination), PR 4
(ssh) becomes the critical item and moves before PR 3.

## 2. Frozen before lanes start

Lanes build in parallel against three contracts fixed by the spec. A change to
any of them is a spec PR first, then the code.

1. **Envelope** (spec §4): field names, types, canonical JSON form, id format.
2. **Store layout** (spec §5): paths, the maildir publish rule, the dedup
   marker rule, ledger line shape.
3. **Transport interface** (spec §7): the five methods and their result
   values.

PR 1 writes these three as code (`bin/fleet_msg_core.py` data classes,
`bin/fleet_msg_transport.py` Protocol) and pins them with tests before lanes B
and C start building on them.

## 3. PRs in order

| # | PR | Files (owner lane) | Tests | Depends on |
|---|---|---|---|---|
| 1 | **Contracts**: envelope build/parse/validate, canonical JSON, id mint, store paths, `Transport` Protocol, `SiteInfo` | `bin/fleet_msg_core.py`, `bin/fleet_msg_transport.py` (A) | `tests/test_msg_contracts.py`: round-trip, canonical bytes stable, bad schema refused, id ordering by time | — |
| 2 | **Local core**: `fleet msg init/send/inbox/ack/status/queue/ids/whois` inside one home; symbolic bindings `lane`, `supervisor`, `interface`; sender auth from existing provenance helpers; ledger | `bin/fleet_msg.py`, `bin/fleet.py` (subparser + `_msg_prims` only) (A) | `tests/test_msg_local.py` | 1 |
| 3 | **Anti-gridlock rules**: words/bytes bound, `--long`, hop guard, `path` loop guard, ping-pong guard, rate limit, receipts-never-receipt | `bin/fleet_msg_rules.py` (B) | `tests/test_msg_rules.py`: pure functions, each rule at bound and bound+1 | 1 |
| 4 | **fs transport**: pull-only ingest from peer homes via the homes list, receipts through own outbox, outbox drop on receipt | `bin/fleet_msg_fs.py` (B) | `tests/test_msg_fs.py`: two homes in `tmp_path` | 1 |
| 5 | **Wake adapters**: notice/steer/none per harness, extended drain block, `inbox --wait` | `bin/fleet_msg_wake.py` (C) | `tests/test_msg_wake.py`: injected prims, no live harness | 1 |
| 6 | **Wiring**: rules into `send`, fs transport into `sync` and `inbox`, wake call after delivery, `## MESSAGES` block in `compose_prompt` | `bin/fleet_msg.py`, `bin/fleet.py` (A) | extend `tests/test_msg_local.py`; `tests/test_msg_two_home.py` | 2, 3, 4, 5 |
| 7 | **ssh transport**: frame codec, `fleet msg serve`, `sync --peer`, relay of one hop, failure exit 4 | `bin/fleet_msg_ssh.py` (B) | `tests/test_msg_ssh.py` (fake pipe), `tests/integration/test_msg_ssh_live.py` (gated) | 1, 4 |
| 8 | **Role bindings**: `bind/retire`, concrete bindings, `follows:`, epoch, supervisor handoff carry, claim/nonce gate | `bin/fleet_msg_bind.py` (C) | `tests/test_msg_bind.py` | 2 |
| 9 | **Migration**: render to `to-fleet/`, `relay-ack` acks the message, `fleet msg import`, `mail verify` reads both stores, receipt fold | `bin/fleet_msg_migrate.py` (C), small hooks in `bin/fleet.py` and `bin/fleet_mailman.py` (A applies) | `tests/test_msg_migrate.py`; existing `tests/test_mailman.py`, `tests/test_interface_watch.py` unchanged and green | 6 |
| 10 | **Views**: queue counts in `status_snapshot()` and the statusline, file listing only | `bin/fleet_statusline.py`, `bin/fleet.py` (A) | `tests/test_views_doctrine.py` pin extended; `tests/test_msg_views.py` | 6 |

PR 6 and PR 9 are the only PRs that edit `bin/fleet.py` after PR 2, and both
are lane A's. That keeps the 30,000-line file single-writer.

## 4. Lane split (at most three in parallel)

| Wave | Lane A (core + `bin/fleet.py`) | Lane B (rules + transports) | Lane C (wake + bindings + migration) |
|---|---|---|---|
| 0 | PR 1 contracts | — | — |
| 1 | PR 2 local core | PR 3 rules, then PR 4 fs | PR 5 wake |
| 2 | PR 6 wiring | PR 7 ssh | PR 8 bindings |
| 3 | PR 10 views, applies PR 9's `bin/fleet.py` hooks | review of PR 9 | PR 9 migration |

File ownership is disjoint inside every wave. Lanes B and C import only
`fleet_msg_core` and `fleet_msg_transport` and take every fleet helper they
need as an injected `prims` object, as `bin/fleet_mailman.py` does through
`fleet._mailman_prims`. They never import `bin/fleet.py`.

Wave 0 is one small PR (about 300 lines). Waves 1 and 2 run three lanes each.
Wave 3 needs two. One reviewer lane reviews each wave's PRs as a batch.

## 5. Test strategy

**Unit (no harness, no network).** Pure functions for envelope, rules and
frame codec. Store operations against `tmp_path` homes with fake `clock` and
`sleep`, as `cmd_watch` and mailman tests do.

**Crash and concurrency.** Inject `OSError` and `KeyboardInterrupt` between
marker create, tmp write, rename and ledger append. At every point the message
exists in exactly one of: source outbox, spool, or `rejected/`, and a re-run
finishes without a duplicate. Two concurrent ingests of one id produce one
spool file and one `duplicate`.

**Two-home integration.** Two initialised homes in `tmp_path`, both appended to
a test homes list (the multi-fleet test-isolation fixtures redirect the real
list). Lane in home A sends to `supervisor@b`; home B's `sync` ingests; B's
receipt reaches A; A's outbox empties; ordering and gap display hold over
out-of-order arrival.

**Simulated two-machine ssh without sshd.** The ssh transport runs a
subprocess and speaks frames on its stdin/stdout. The test replaces
`["ssh", ...]` with `[sys.executable, "bin/fleet.py", "--fleet-home", B,
"msg", "serve", "--peer", "a"]`. That is the real server code on a real pipe.
A fault-injecting pipe wrapper covers: drop after N bytes, corrupt one byte,
duplicate a frame, replay a whole earlier session, delay `commit`. Clock skew
is a fake clock on one side.

**Live ssh (gated, `FLEET_LIVE_SSH=1`).** Starts a user-level `sshd` on a
random high localhost port with a temp host key and a forced-command
`authorized_keys`, then runs the two-home scenario through it. Proves the
forced-command peer pinning and the non-default port. Skips loudly when
`sshd` is absent. Never touches the user's real ssh config or keys.

**Wake adapters.** Injected `append_mailbox`, Codex followup and pi steer
fakes record calls. Pins: delivery happens before wake; a raising adapter
leaves the message delivered; `steer` refuses a non-task or a sender who is
not the holder's supervisor or the Interface; no adapter is called for the
Interface.

**Doctrine pins.** No `fleet_lock` or registry write in any `fleet_msg*`
module (source scan, as mailman's T17). Views read counts only. Every module
imports under Python 3.10. No tracked file contains a host, port or key
(public hygiene test).

## 6. Risks

| Risk | Mitigation |
|---|---|
| Same OS user can forge any local file, so "verified" is read as security | Spec §10 says so; inbox prints the method; Interface direction still needs `interface-registration` |
| Dedup markers grow without bound | `dedup_days` window; a compaction step in PR 4 removes markers past the window |
| Forced command misconfigured, so the server trusts a client-chosen site | `serve` refuses to start without `--peer`; doctor check later; live test pins the pinning |
| The client stops syncing and server-side messages to it sit unseen | `fleet msg queue` shows outbox depth and oldest age per peer; `sync` exits 4 on repeated failure |
| Steer policy overused, causing fork-steer cost and RAM pressure | default `notice`; `steer` only for `task` from the holder's supervisor or the Interface; rate limit |
| Verb-effect tier: an unclassified `msg` verb is destructive and would need `--fleet-home` on every lane send | proposed tiers in spec §13 go to the operator with PR 2; until ruled, PR 2 ships them in no tuple and tests pass `--fleet-home` |
| Mailman and `msg` both wake the Interface for one message during migration | rendered files carry `msg-id`; `inbox` skips ids already acked through `relay-ack` |
| Windows parity (`flock`, `ssh` path) | reuse `bin/fleet_platform.py`'s lock backend, as mailman does; Windows ships OpenSSH; fail closed where no lock backend exists |

## 7. Out of scope

- A tailnet or any third transport (the Protocol leaves the seam).
- Routing beyond one relay hop; groups, broadcast and topics.
- Attachments. Long content goes by reference (file path or PR link).
- Encryption at rest and a privilege boundary between local homes.
- Fleet calling native `SendMessage` itself (it cannot; peer-messaging.md).
- Changing `fleet send`'s steering gates, or the mailman classification rules.
- Any operator data, real site labels, hosts, ports or keys in tracked files.
