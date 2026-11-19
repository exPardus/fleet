# Build plan: `fleet msg`

Spec: `docs/specs/messaging.md` (revision 2). This plan orders the build into
small PRs, splits them across at most three parallel lanes with disjoint
files, and names the tests, risks and exclusions.

**Status:** PRs 0 to 6 merged. PR 7 (ssh transport) built: `bin/fleet_msg_ssh.py`, `msg serve`,
`sync` over ssh peers, `tests/test_msg_ssh.py` (T15, T15b-e) and the gated
`tests/integration/test_msg_ssh_live.py` (T16). PR 6 (wiring) built: rules, fs `sync` and
inbox pull, notice, drain block, the `msg send --kind task` gate, the PR 2
deferrals and T10b, with `tests/test_msg_two_home.py` (T13, T14, T14b, T14c).
`bind` and its gate arm wait for PR 8. PR 10 (retention) built: `msg compact`,
the `purge` seam, and the windowed `_history`, with `tests/test_msg_compact.py`.

Every PR carries its own tests and the doc changes for what it ships: the
spec section it implements moves from "proposed" to "built", plus
`docs/SPEC.md` §9, `docs/cli-reference.md` and `skills/fleet/SKILL.md` rows
when a verb becomes user-visible.

**Gates for every PR:**
`uv run --no-project --python 3.10 --with pytest python -m pytest -q` and the
3.12 equivalent, over the PR's tests plus `tests/test_receipts.py`,
`tests/test_views_doctrine.py`, `tests/test_doc_claims.py` and
`tests/test_public_hygiene.py`. **Repaired by PR 0:**
`tests/test_docs_currency.py::test_branch_docs_currency` failed on commits
1942a432 and 6085e308 ("bin/*.py changed without docs/ or Docs: n/a"); PR 0
adds both to `HISTORICAL_METADATA_EXEMPTIONS`. A lane branched before PR 0
merges reports the failure as pre-existing and does not fix it.

**No irreversible deletion.** No PR adds a code path that deletes a message,
marker, receipt or ledger line. Retention moves data into `archive/`. Any
purge sits behind one `purge` seam, off by default (spec §6).

## 1. Frozen before lanes start

Three contracts are fixed by the spec and written as code in PR 1. A change to
any of them is a spec PR first.

1. **Envelope** (spec §4): fields, types, canonical JSON, random id.
2. **Store and primitives** (spec §5): paths, `publish()` and `enqueue()`
   with their locks, fsync and marker-after-file order.
3. **Transport** (spec §7): five methods; `pull` returns every entry still in
   `q/` (the qseq is a paging hint only), `commit(ids)` by exact id; `qseq`
   allocated and written under one per-outbox lock.

## 2. PRs in order

| # | PR | Files (lane) | Tests | Depends on |
|---|---|---|---|---|
| 0 | **Gate repair**: docs-currency exemption for the two main commits | `tests/test_docs_currency.py` (A) | the test itself green | — |
| 1 | **Contracts and primitives**: envelope build/parse/validate, `publish()`, `enqueue()` (seq under the sender lock, rules hook before allocation), locks via the mailman lock backend, `Transport` Protocol | `bin/fleet_msg_core.py`, `bin/fleet_msg_transport.py` (A) | `tests/test_msg_core.py` (T1–T6) | — |
| 2 | **Local core**: `msg init/send/inbox/ack/status/queue/whois` in one home; implicit lane/supervisor/interface identities from registry, claim and registration; caller methods; holder check on read and ack; ledger | `bin/fleet_msg.py`, `bin/fleet.py` (subparser, `_msg_prims`) (A) | `tests/test_msg_local.py` (T7–T10) | 1 |
| 3 | **Anti-gridlock rules** as pure functions | `bin/fleet_msg_rules.py` (B) | `tests/test_msg_rules.py`: each rule at bound and bound+1 | 1 |
| 4 | **fs transport** per spec §7.1 | `bin/fleet_msg_fs.py` (B) | `tests/test_msg_fs.py` (T11) | 1 |
| 5 | **Notice wake + drain block** as functions over injected prims | `bin/fleet_msg_wake.py` (C) | `tests/test_msg_wake.py` (T12) | 1 |
| 6 | **Wiring**: rules into `enqueue`, fs into `sync`/`inbox`, notice after publish, `## MESSAGES` in `compose_prompt`, `msg` into `GATE_VERBS_ACCEPTING_NONCE` for `--kind task` and `bind`; PR 2 review deferrals (spec §8.1): unverified `--from` seq namespace, `done/` gap high-water mark, refused-nonce log | `bin/fleet_msg.py`, `bin/fleet.py` (A) | `tests/test_msg_two_home.py` (T13–T14) | 2, 3, 4, 5 |
| 7 | **ssh transport**: frame codec, `serve` (refuses without `--peer`), `sync --peer`, exit 4 | `bin/fleet_msg_ssh.py` (B) | `tests/test_msg_ssh.py` (T15), `tests/integration/test_msg_ssh_live.py` (T16, gated) | 1, 4 |
| 8 | **Named roles**: `bind/retire`, concrete bindings, epoch | `bin/fleet_msg_bind.py` (C) | `tests/test_msg_bind.py` (T17) | 2, 6 |
| 9a | **Migration module**: render to `to-fleet/`, `import`, receipt-store fold reader | `bin/fleet_msg_migrate.py` (C) | `tests/test_msg_migrate.py` | 6 |
| 9b | **Migration hooks**: `relay-ack` acks rendered mail, `mail verify` reads both stores, `_issue_verified_supervisor_mail` writes an envelope, bridge argv in the mailman seed | `bin/fleet.py`, `bin/fleet_mailman.py` (A) | existing `tests/test_mailman.py`, `tests/test_interface_watch.py` green; new hook tests | 9a |
| 10 | **Retention**: `msg compact` into `archive/`, `purge` seam off by default | `bin/fleet_msg_core.py` (A) | `tests/test_msg_compact.py`: nothing leaves the tree; purge refuses unless enabled | 2 |
| 11 | **Views**: queue counts in `status_snapshot()` and the statusline, by listing only | `bin/fleet_statusline.py`, `bin/fleet.py` (A) | `tests/test_views_doctrine.py` extended; `tests/test_msg_views.py` | 6 |
| 12 | **Tier machinery** (ruling given, spec §13; unblocked): per-subcommand tiers in `verb_effect_tier`, table and pin edits | `bin/fleet.py`, multi-fleet pins (A) | `tests/test_round7_defect_pins.py` and tier tests | 2 |

`bin/fleet.py` is edited only by lane A (PRs 0, 2, 6, 9b, 11, 12), so the
file stays single-writer. Lanes B and C import only `fleet_msg_core` and
`fleet_msg_transport` and take fleet helpers as an injected `prims` object,
as `bin/fleet_mailman.py` does. They never import `bin/fleet.py`.

## 3. Lane split (at most three in parallel)

| Wave | Lane A (core, `bin/fleet.py`) | Lane B (rules, transports) | Lane C (wake, roles, migration) |
|---|---|---|---|
| 0 | PR 0, PR 1 | — | — |
| 1 | PR 2 | PR 3, then PR 4 | PR 5 |
| 2 | PR 6 | PR 7 | review PR 6 |
| 3 | PR 9b, PR 10 | review | PR 8, PR 9a |
| 4 | PR 11, PR 12 | — | — |

File ownership is disjoint inside every wave. One reviewer lane reviews each
wave's PRs as a batch.

## 4. Test strategy

Unit tests use `tmp_path` homes, fake `clock` and `sleep`, and no harness or
network. Tests are named by the PR that owns the code.

| # | case | asserts |
|---|---|---|
| T1 | crash injection in `publish` between every step | the message exists in exactly one place; a re-run finishes with no duplicate; never a marker without a file; repair after step 2 writes the ledger line and the notice exactly once |
| T2 | two concurrent `publish` of one id (threads and processes) | one file in `new/`, one `duplicate` |
| T3 | reader moves `new → cur` during a second ingest | no copy reappears in `new/` |
| T4 | concurrent senders on one (`from`, `to`) | distinct, gap-free seqs |
| T5 | a send refused by a rule, and a crash after seq allocation | no permanent seq gap from a refusal; a crash gap is shown and blocks nothing |
| T6 | fsync calls on file and directory | `publish` calls both before returning |
| T7 | fork-steer with unread messages, old sid still live; also for a named role bound `lane:<worker>` | the registry's new sid passes the holder check; the old body fails it; no rebind needed |
| T8 | respawn; Codex thread rotation; pi job change | the lane identity follows with no rebind |
| T9 | process restart and reboot simulation with messages in `new/`, `cur/` and outbox | all survive; outbox resumes |
| T10 | two bodies claim one identity; a lane runs non-peek `inbox supervisor` | the non-holder is refused; `--peek` works; ledger records the reader; `inbox --all` lists `cur/` with the reader |
| T10b | send to an archived lane; archive then reuse of the name | `rejected: retired`; the new lane's spool is empty and the old spool is in `archive/` |
| T11 | fs: duplicate after crash before receipt | `delivered` is re-emitted; the sender's outbox drains; receipt entries move to `sent/` |
| T12 | notice | no body text; one pending notice per (identity, sender); no steer, no `fleet.lock`, no registry write |
| T13 | two homes: lane in home A to `supervisor@b` | delivered, receipt back, outbox drains, FIFO with gap display |
| T14 | `--kind task` from the supervisor without a nonce; with a zombie sid | refused; a note is labelled `supervisor-sid` |
| T14b | a peer site sends `kind: task`, `from=supervisor@peer`, method `supervisor-nonce`; then the same with the peer marked `direct: true`; then from the configured `interface_site` | shown as `remote-task` note and not in the lane's direction set; direction; direction |
| T14c | nonce in `detail` and ledger (pin) | the envelope and ledger contain no nonce value, only `nonce_seq` and an 8-hex prefix |
| T15 | ssh on a pipe: the test replaces `ssh` with `python bin/fleet.py --fleet-home B msg serve --peer a`; a wrapper drops after N bytes, corrupts a byte, duplicates a frame, replays a session, delays `commit` | no loss, no duplicate, nothing torn published |
| T15b | clock skew across `commit`: one side's clock 10 min slow, a late enqueue below the cursor | the late envelope is still sent and committed by id |
| T15c | `from` not hosted by the peer; same label on both ends | `rejected: auth`; `hello` refuses |
| T15d | two concurrent remote senders to one site, the second's file made visible first (injected delay inside the first writer), client pulls between them | both are pulled and committed; no entry is ever skipped; qseq order equals visibility order |
| T15e | a peer sends 201 envelopes in an hour from many names | the 201st is `rejected: rate` |
| T16 | live, `FLEET_LIVE_SSH=1`: user-level `sshd` on a random high localhost port, temp keys, forced-command `authorized_keys` | the server pins the client site; non-default port; skips loudly without `sshd`; the user's real ssh config is never touched |
| T17 | bind without nonce; worker-turn bind; epoch on rebind; `lane:<worker>` binding across fork-steer and respawn | refused; refused; epoch +1 and ledger line; binding follows the lane with no rebind |

Doctrine pins: no `fleet_lock` import or registry write in any `fleet_msg*`
module (source scan); no unlink of a message, marker or ledger outside the
`purge` seam (source scan); every module imports under Python 3.10; every
shipped argv contains `--fleet-home`; no tracked file contains a site label,
host, port or key (public hygiene).

## 5. Risks

| Risk | Mitigation |
|---|---|
| "Verified" read as security on a same-user host | spec §10 and §14 say provenance only; inbox prints the method |
| Tier machinery not landed; `msg` destructive meanwhile | every shipped argv carries `--fleet-home`; PR 12 is unblocked and blocks nothing else |
| Forced command misconfigured | `serve` refuses without `--peer`; T16 pins the key-to-site mapping |
| Client sync stalls after reboot | the mailman bridge pass syncs; `queue` warns on outbox age |
| Archive growth | `compact` packs monthly; disk is the operator's call through the purge setting |
| Mailman and `msg` both wake the Interface for one message | rendered files carry `msg-id`; acking one acks the other |
| Windows parity (locks, `ssh` path) | reuse the mailman lock backend; Windows ships OpenSSH; fail closed without a lock backend |

## 6. Out of scope

- A tailnet or other third transport (the Protocol leaves the seam).
- Relay through a third site; groups, broadcast, topics; attachments.
- Encryption at rest; a privilege boundary between local homes.
- Fleet calling native `SendMessage`; messaging steering any body.
- Changes to `fleet send` gates or mailman classification rules.
- Operator data, real site labels, hosts, ports or keys in tracked files.

## 7. Review response (w483, PR #68 at f3f6fe4)

| id | fix | section |
|---|---|---|
| P1-1 | ingest serialised per spool lock; publish by `link()`, then marker; no marker without a file | spec §5; T1–T3 |
| P1-2 | `pull(after_qseq)` by server enqueue counter; `commit(ids)` by exact id; random ids, never ordered | spec §4, §7; T15b |
| P1-3 | relay removed from v1 | spec §7, §13 |
| P1-4 | seq allocated under the sender lock after rules, unique tmp name, fsync | spec §5; T4–T5 |
| P1-5 | wake is a notice only; no adapter steers, takes `fleet.lock` or writes the registry | spec §9; T12 |
| P1-6 | no mcx or pi steer; drain block only | spec §9 |
| P1-7 | holder check on non-peek inbox and ack; `--peek` for anyone; ledger names the reader | spec §10; T10 |
| P1-8 | `supervisor-nonce` vs `supervisor-sid`; tasks need a nonce | spec §10; T14 |
| P1-9 | per-pair task budget ignoring threads; one pending notice per sender | spec §9, §11 |
| P1-10 | tier left to the operator with the ledger question stated; explicit `--fleet-home` in every argv; PR 12 for tier machinery | spec §7.2, §8, §13; plan PR 12 |
| P1-11 | lane, supervisor, interface identities implicit; nonce wiring in lane A's PR 6 | spec §3; plan PR 2, PR 6 |
| P1-12 | `publish()`/`enqueue()` in core PR 1 with crash tests; transports call them | spec §5; plan PR 1 |
| P1-13 | old plan §1 deleted; no outside structure named | plan |
| P1-14 | body-swap, takeover, concurrency, restart, skew and auth tests added | plan §4 |
| P2-1 | future `sent_at` rejected; markers kept `dedup_days + max_skew` by receiver clock | spec §6 |
| P2-2 | `publish` fsyncs file and directory; `_write_json_atomic` not reused for the store | spec §2, §5; T6 |
| P2-3 | duplicate re-emits `delivered`; receipt entries move to `sent/` | spec §6, §7.1; T11 |
| P2-4 | duplicate site labels refused by `init`, `sync`, `hello` | spec §3; T15c |
| P2-5 | unqualified name means the local site | spec §3 |
| P2-6 | `--long` removed | spec §11 |
| P2-7 | cut read/acked receipts, `follows:`, relay, kinds `question`/`answer`; ops has its own queue. Named roles kept (see deferred) | spec §3, §4, §6 |
| P2-8 | notice carries id, sender, method; no body | spec §9 |
| P2-9 | guards enforced sender-side; receiver re-checks only with the parent | spec §11 |
| P2-10 | fs mapped to the five methods | spec §7.1 |
| P2-11 | `msg compact` into `archive/`; purge seam off | spec §6; plan PR 10 |
| P2-12 | sync owned by the mailman bridge pass; outbox-age warning | spec §7.2 |
| P2-13 | PR 9 split into 9a (C) and 9b (A); `bin/fleet.py` owner list corrected | plan §2 |
| P2-14 | known failure named; PR 0 repairs it | plan gates, PR 0 |

Delta review (d60fb6b3):

| id | fix | section |
|---|---|---|
| N1 | `qseq` allocated and written under one per-outbox lock; `pull` returns every entry still in `q/`, the qseq is a hint only | spec §5, §7; T15d |
| N2 | direction decided by the receiver: local `supervisor-nonce`, the named `interface_site`, or a `direct: true` peer; else `remote-task` note | spec §10, §14; T14b |
| N3 | named roles may bind `lane:<worker>`, resolved through the registry; concrete bindings only outside the registry | spec §3, §14; T7, T17 |
| N4 | tiers ruled and recorded; `ids` restored; `init` ordinary, `compact` disruptive, `purge` destructive; PR 12 unblocked | spec §8, §13; plan PR 12 |
| N5 | "operator-confirmed" = confirmed at setup (`peers.json`, `authorized_keys`) plus the nonce gate | spec §13 |
| N6 | supervisor reads use `supervisor-sid`, ledger names the reader; `inbox --all` restored; zombie-reads row | spec §6, §8, §10, §14; T10 |
| N7 | `detail` and ledger hold no nonce, at most `nonce_seq` and an 8-hex prefix | spec §10, §14; T14c |
| N8 | 200/h per-peer ingest cap; residual corrected | spec §11, §14; T15e |
| N9 | repair runs the ledger line and the notice once; `done/` archived only with a marker | spec §5, §6; T1 |
| N10 | send to an archived lane `rejected: retired`; spool archived on archive; lane epoch = registry `created` | spec §3; T10b |

## 8. Deferred review items

- **P2-7, cutting the generic named-role identity**: refused. Persistent named
  roles beyond lanes, supervisor and interface (for example `ops`, `hub`) are
  a stated requirement of this work; they stay, with concrete bindings only.

## PR 6 review deferrals (PR #77)

- The §11 history in `msg send` (`_history`) scanned the whole ledger once per
  send. Done in PR 10: it reads a 24 h tail (spec §6.1); the per-sync-pass ingest cap and
  retired-name reads are cached in `sync_fs_peer`.
