# Proposal: native subagent lanes under Claude supervisors

**Status:** proposal only. No behavior changes are specified as shipped here.

## Current state

A depth-two native Claude Code subagent was observed doing work much like a Fleet lane: a supervisor delegated a bounded task and received a child result. That observation motivates a substrate test; it does not establish durable identity, recovery, accounting, or cleanup guarantees.

Fleet currently makes each Claude lane a daemon-hosted `claude --bg` session. `cmd_spawn` preclaims a registry row, dispatches, then stamps the session ID (`bin/fleet.py:7222`); `new_worker_record` stores the task, worktree, branch, mode, model, ceiling, and creator lineage (`bin/fleet.py:1196`). The native verdict engine joins the daemon roster and terminal outcomes (`bin/fleet.py:4957`; `docs/SPEC.md:164`). `fleet send` steers an idle Claude worker by fork and session-ID rotation (`bin/fleet.py:9426`; `docs/SPEC.md:656`). The token ceiling sums recorded outcomes, with no native dollar source (`bin/fleet.py:4108`; `docs/SPEC.md:660`). The supervisor is a home-scoped claim holder with a durable journal and heartbeat (`docs/SPEC.md:759`), and its procedure requires a full child roster after compaction and nonce continuity before mutation (`skills/fleet/supervisor.md:3`, `skills/fleet/supervisor.md:27`).

The messaging layer already has stable lane, supervisor, and interface identities, role bindings, and a store-and-forward transport (`docs/specs/messaging.md:73`; `bin/fleet_msg.py`). Claude peer messaging is an optional live-session accelerator (`docs/SPEC.md:658`). This proposal extends that address book; it does not create a second naming system.

The native Codex host currently chooses a manifest by exact `codex --version` and refuses an unknown version before launch (`bin/fleet_codex.py:47`, `bin/fleet_codex.py:112`, `bin/fleet_codex.py:2259`). It verifies the SHA-256 of the **whole** generated schema bundle (`bin/fleet_codex_host.py:465`) and checks running-host metadata against the version's manifest (`bin/fleet_codex.py:2336`).

## Proposal

Keep supervisors as Fleet identities: the home, claim, nonce, journal, and resume note survive any one Claude or Codex body. For a Claude supervisor on the same machine, make the default short-lived, bounded child lane a native Claude subagent. Fleet assigns its stable lane name and records parent claim lineage, native child handle, task/brief digest, worktree, model, permission mode, dispatch time, observed status, result evidence, and measured token use. Reads remain lock-free views; writes use the existing single-writer registry rule. A subagent result is accepted only with evidence tied to that child handle and dispatch generation. Unknown liveness stays advisory, never an automatic redispatch.

Use one address book and two delivery transports. A live Claude-to-Claude pair on one machine can use native messaging; Fleet resolves the current child handle and records a delivery receipt. Other pairs, including Codex and cross-machine peers, use Fleet's durable `msg` queue and filesystem/SSH transport. An address always names an identity, not a session. If native delivery is unavailable or unacknowledged, retain the message in the durable queue and wake through the applicable adapter; deduplicate by message ID. `fleet send` remains a distinct steering operation, with its existing authorization and recovery gates.

Keep independent Fleet lanes for Codex, other machines, and work that must outlive a supervisor. A caller selects that lifecycle explicitly; the supervisor procedure should state when to choose each kind. A native subagent never silently changes into an independent session. Fleet should expose both kinds through `status`, `peek`, `result`, `wait`, and `msg whois`, with the same stable lane name and a visible kind/parent column.

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
4. Route same-machine Claude messages through native delivery with durable queue/receipt fallback. Add explicit lifecycle selection to the supervisor procedure. Migrate only new short-lived Claude lanes by default; let existing rows finish on their original substrate.
5. Replace the Codex version gate with used-schema comparison, fixtures for unrelated additions and used-shape drift, and a live pin run. Update `docs/specs/codex-native-integration.md` when the implementation changes.
6. After a successful mixed-fleet period, remove retired Claude daemon-lane paths and their tests/docs. Keep supervisor-body and independent-lane paths wherever they still use the daemon.

## What gets deleted after migration

For **Claude worker lanes only**, retire the `--bg` spawn/steer/resume machinery in `dispatch_bg`, `_cmd_send_native`, `_resume_one_limited_native`, and `_cmd_respawn_native` (`bin/fleet.py:16546`, `bin/fleet.py:9426`, `bin/fleet.py:10846`, `bin/fleet.py:11531`). Retire Claude worker stop/reap helpers `_cmd_interrupt_native`, `_cmd_kill_native`, `_native_job_ref`, and `_rm_native_session` when no supervisor or legacy path calls them (`bin/fleet.py:11153`, `bin/fleet.py:12224`, `bin/fleet.py:13941`, `bin/fleet.py:14024`). This is removal of call sites or now-unused functions, not a promise to delete shared code by name. Retain `fleet spawn/send/respawn/archive/clean` for independent lanes and supervisors; retire only their Claude daemon-lane branches. Replace the exact-version `REVIEWED_SCHEMA_MANIFESTS` lookup and whole-bundle equality gate, while keeping a reviewed used-schema contract (`bin/fleet_codex.py:47`; `bin/fleet_codex_host.py:484`).

## Open questions

1. Does the supported native subagent API expose stable child identity, per-child usage, terminal evidence, and a parent-independent result record across compaction and death?
2. Can a child work in an isolated worktree with a specified effective permission mode and model, and who owns cleanup if its supervisor disappears?
3. Which native message API yields an acknowledgement that can be tied to Fleet's durable message ID? If none does, should native messaging be notice-only?
4. Should a native child's maximum lifetime be one supervisor incarnation, one claim lineage, or one supervisor turn?
