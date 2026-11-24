# Proposal: native subagent lanes under Claude supervisors

**Status:** proposal only. No behavior changes are specified as shipped here.

## Current state

A depth-two native Claude Code subagent was observed doing work much like a Fleet lane: a supervisor delegated a bounded task and received a child result. That observation motivates a substrate test; it does not establish durable identity, recovery, accounting, or cleanup guarantees.

Fleet currently makes each Claude lane a daemon-hosted `claude --bg` session. `cmd_spawn` preclaims a registry row, dispatches, then stamps the session ID; `new_worker_record` stores the task, worktree, branch, mode, model, ceiling, and creator lineage. The native verdict engine (`recompute_worker_native`; `docs/SPEC.md` §5) joins the daemon roster and terminal outcomes. `fleet send` steers an idle Claude worker by fork and session-ID rotation (`_cmd_send_native`; `docs/SPEC.md` §9). The token ceiling sums recorded outcomes, with no native dollar source (`_native_cumulative_tokens`; `docs/SPEC.md` §9). The supervisor is a home-scoped claim holder with a durable journal and heartbeat (`docs/SPEC.md` §12), and its procedure requires a full child roster after compaction and nonce continuity before mutation (`skills/fleet/supervisor.md`).

The messaging layer already has stable lane, supervisor, and interface identities, role bindings, and a store-and-forward transport (`docs/specs/messaging.md` §3; `bin/fleet_msg.py`). Claude peer messaging is an optional live-session accelerator (`docs/specs/peer-messaging.md`): `fleet address` resolves the exact target name, and only the calling Claude session can send with `SendMessage`. The Fleet CLI cannot send that message or obtain an acknowledgement for it. This proposal extends the existing address book; it does not create a second naming system.

The native Codex host currently chooses a manifest by exact `codex --version` and refuses an unknown version before launch (`REVIEWED_SCHEMA_MANIFESTS`, `_reviewed_schema_manifest`, `CodexHostClient.ensure` in `bin/fleet_codex.py`). It verifies the SHA-256 of the **whole** generated schema bundle (`Host._verify_installed_schema` in `bin/fleet_codex_host.py`) and checks running-host metadata against the version's manifest (`CodexHostClient._existing`).

## Proposal

Keep supervisors as Fleet identities: the home, claim, nonce, journal, and resume note survive any one Claude or Codex body. For a Claude supervisor on the same machine, make the default short-lived, bounded child lane a native Claude subagent. Fleet assigns its stable lane name and records parent claim lineage, native child handle, task/brief digest, worktree, model, permission mode, dispatch time, observed status, result evidence, and measured token use. Reads remain lock-free views; writes use the existing single-writer registry rule. A subagent result is accepted only with evidence tied to that child handle and dispatch generation. Unknown liveness stays advisory, never an automatic redispatch.

Use one address book. Durable delivery stays on Fleet's `msg` queue and filesystem/SSH transport for every pair, including two live Claude sessions on one machine; an address always names an identity, not a session. Native Claude messaging is **notice-only**: after `fleet msg` has queued a message, the sending Claude session may call `SendMessage` to the target that `fleet address` resolves, carrying the durable message ID so the receiver reads that queued message. Fleet never records a native send as delivered and never removes a queued message because of one. A native transport may carry delivery only after a pin proves an acknowledgement that Fleet can verify and tie to the durable message ID, plus deduplication by that ID (open question 3). `fleet send` remains a distinct steering operation, with its existing authorization and recovery gates.

Keep independent Fleet lanes for Codex, other machines, and work that must outlive a supervisor. Independent Claude lanes keep their full current `--bg` lifecycle: spawn, fork-steer, resume-limited, respawn, interrupt, kill, archive, and clean. A caller selects the lifecycle explicitly; the supervisor procedure should state when to choose each kind. A native subagent never silently changes into an independent session. Fleet should expose both kinds through `status`, `peek`, `result`, `wait`, and `msg whois`, with the same stable lane name and a visible kind/parent column.

For Codex, replace the exact-version allowlist with a capability check: generate the installed schema, extract the request, response, notification, and server-request shapes for **every method and field the adapter sends or consumes**, and compare those shapes to a reviewed contract. Launch when all compared shapes are unchanged, even if `codex --version` is new; refuse if any used shape differs or cannot be read or compared. Keep the installed version and full digest as diagnostics, not launch gates. The used-method inventory must be derived or checked against actual adapter call sites; unlisted calls fail the gate. Preserve runtime validation for behavior the schema cannot express. Update the host startup and existing-host checks cited above together; a new binary must not be assumed compatible merely because an old host remains live.

## Cost

A native child may avoid a separate daemon session, Fleet prompt composition, mailbox drain, and fork-steer for each short Claude task. This is a hypothesis requiring a measured trial: compare wall time, input/output tokens, supervisor context growth, and recovery work on the same brief. Fleet still pays for a durable row, identity routing, result capture, and periodic reconciliation. Schema slicing adds a maintained used-method inventory and compatibility fixtures, but removes the release-by-release manifest entry when unrelated Codex schemas change. No dollar saving is claimed until a reliable per-child cost source exists.

## Risks

- **Supervisor death:** native children may die with, detach from, or become invisible to their parent. Freeze uncertain rows and preserve their briefs and evidence. Only explicit recovery may launch a replacement; long-lived work stays an independent Fleet lane.
- **Reaping:** parent shutdown, child completion, and name reuse can race. Require an authoritative child roster and terminal evidence before archive or name reuse; never infer completion from a missing child alone.
- **Budget visibility:** a parent total may not identify each child's tokens. Show `unknown` when per-child accounting is unavailable; do not enforce a token ceiling from a guessed allocation. Cap dispatches conservatively until measured child usage is available.
- **Permission modes:** a child may inherit or narrow parent permissions differently from `--bg`. Record effective mode, test workspace trust and prompt behavior, and refuse a mode whose effective privileges cannot be verified.
- **Messaging and compatibility:** native delivery may be ephemeral, and an unchanged JSON schema does not prove unchanged semantics. Durable receipts, deduplication, runtime validation, and a live pin suite remain necessary.

## Migration steps

1. Pin native subagent behavior in disposable homes: depth two, stable handles, result and usage fields, permission inheritance, parent death, compaction, messaging, and reap. Define a refusal or independent-lane fallback for each missing guarantee.
2. Add an additive `lane_kind` and child binding to registry rows; preserve unknown fields and old rows. Extend the existing message resolver and views without probing or mutating state in view paths.
3. Introduce opt-in native Claude subagent dispatch and result capture. Run the same briefs through both Claude paths, including parent death and ambiguous-result tests. Keep `--bg` as fallback until the evidence gates pass.
4. Add notice-only native messaging beside durable `fleet msg` delivery, using the protocol above. Add explicit lifecycle selection to the supervisor procedure. Default only new short-lived Claude lanes to native subagents; let existing rows finish on their original substrate. Promote native messaging to a delivery transport only after the acknowledgement pin passes.
5. Replace the Codex version gate with used-schema comparison, fixtures for unrelated additions and used-shape drift, and a live pin run. Update `docs/specs/codex-native-integration.md` when the implementation changes.
6. After a successful mixed-fleet period, remove only code paths that no lane kind still uses. Independent Claude lanes keep the `--bg` lifecycle.

## What gets deleted after migration

Nothing in the `--bg` lifecycle is deleted: independent Claude lanes still use `dispatch_bg`, `_cmd_send_native`, `_resume_one_limited_native`, `_cmd_respawn_native`, `_cmd_interrupt_native`, `_cmd_kill_native`, `_native_job_ref`, and `_rm_native_session`. Native subagents change which kind a short-lived lane defaults to; they do not replace these operations. After migration, delete only a branch that no supported lane kind reaches, with a test that proves the branch is unreachable, such as a short-lived-lane default or prompt path that native dispatch fully replaces. Replace the exact-version `REVIEWED_SCHEMA_MANIFESTS` lookup and whole-bundle equality gate, while keeping a reviewed used-schema contract (`_reviewed_schema_manifest`; `Host._verify_installed_schema`).

## Open questions

1. Does the supported native subagent API expose stable child identity, per-child usage, terminal evidence, and a parent-independent result record across compaction and death?
2. Can a child work in an isolated worktree with a specified effective permission mode and model, and who owns cleanup if its supervisor disappears?
3. Which native message API yields an acknowledgement that can be tied to Fleet's durable message ID? If none does, should native messaging be notice-only?
4. Should a native child's maximum lifetime be one supervisor incarnation, one claim lineage, or one supervisor turn?
