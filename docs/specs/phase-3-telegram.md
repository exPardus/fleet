# Spec: Telegram bridge (Phase 3) — fleet in your pocket

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md. Requires watchtower (events feed the bridge).

## Goal

Two-way Telegram control: events out, steering in, and manager-on-call — a message can wake a headless manager turn that reads fleet state, decides, acts, replies.

## Scope

In: bot long-polling loop (inside `fleet watch` or sibling process — decide), outbound notifier, inbound command grammar, reply-to threading → worker addressing, manager-on-call turn, auth. Out: web UI, voice, group-chat workflows, multi-user.

<!-- needs-input-dep -->
**Dependency note (needs-input out-flow) — carry into C6.** The "worker needs input → you get the question" out-flow depends on the Phase-2 needs-input detectability decision (see C5 `spec-watchtower` OQ1 / the F20-style disposition). This bridge cannot deliver a worker's blocking question to the phone until Phase-2 defines how a needs-input state is *detected*; state it here so `spec-telegram` (C6) carries the dependency forward rather than re-deriving it.
Witness: *"the worker needs input → you get the question out-flow depends on the Phase-2 needs-input detectability decision"*.

## Fixed constraints

- Single authorized chat id (owner). Token + chat id in state/ (never git). Every inbound message hard-checked against chat id before ANY action.
- Long-polling only (no public webhook, no exposed ports).
- stdlib HTTP (urllib) is enough for Bot API — keep no-deps rule unless file uploads make it miserable (then justify).
- Manager-on-call turns: budget-capped, cooldown-limited, permission mode fixed (accept? bypass? — decide and justify; it can spawn workers, so this is the highest-privilege path in the system).
- Note: machine already runs Claude Code Telegram channel infra (`telegram:configure` skill, ~/.claude/channels) — investigate reusing/wrapping it vs own bot before building own. Own bot = full control of threading/commands; channel infra = free auth+plumbing. Decide with evidence.

<!-- B4 -->
- **Manager-on-call IS a registry entry (confirmed constraint, review B4 — NOT an open question).** The manager-on-call session MUST be a registry entry (reserved name, e.g. `manager`; cwd = FLEET_HOME, immutable), so every existing guard applies for free: pre-claim under fleet_lock, send-while-working → mailbox queueing. Consequences fixed here, not deferred: exactly one manager turn in flight; queued messages coalesce into the next wake; cooldown = minimum gap between turn STARTS.
  Witness: *"the manager-on-call session MUST be a registry entry (reserved name, e.g. `manager`; cwd = FLEET_HOME, immutable)"*.

<!-- B5 -->
- **Privilege bounds + confirm round-trip (confirmed constraint, review B5 — NOT an open question).** This is the highest-privilege inbound path, so its security is FIXED, not left to C6: (1) manager-on-call turns NEVER run --dangerously-skip-permissions; (2) transitive-privilege rule — any inbound path that would create a bypass-mode worker requires an explicit owner confirmation round-trip (bot replies with exact command + nonce, owner replies confirm); (3) /kill and /respawn require the same confirm; (4) the drafting session must enumerate the exact command set allowed without confirmation.
  Witness: *"manager-on-call turns NEVER run --dangerously-skip-permissions"*.
  - **Concrete starting command-set proposal (for Altai's C6 security sign-off to review a concrete proposal, not a blank):** no-confirm = `/status /peek /result /mute`; confirm-with-nonce = `/send /respawn /kill /spawn`.
    Witness (command-set): *"no-confirm = `/status /peek /result /mute`; confirm-with-nonce = `/send /respawn /kill /spawn`"*.

<!-- F17 -->
- **Inbound auth allowlist (confirmed constraint, review F17 = review-doc M20 — fixed, not deferred).** Accept ONLY update type `message` where chat.type=='private' AND chat.id==owner_id AND from.id==owner_id; silently drop every other update type including edited_message; unauthorized traffic logged rate-limited to a state/ audit line, never answered; >N attempts/hour raises an owner notification; token file owner-only permissions (0600 via platform adapter, doctor-checked) + a compromise runbook line.
  Witness: *"accept ONLY update type `message` where chat.type=='private' AND chat.id==owner_id AND from.id==owner_id; silently drop every other update type including edited_message"*.

<!-- F16 -->
- **getUpdates offset / dedup / 409 discipline (confirmed constraint, review F16 = review-doc M19 — folds into OQ6 on resolution; recorded here so it is not lost).** Persist the getUpdates offset atomically in state/, ack-after-successful-dispatch with a per-update_id dedup journal (restarts neither drop nor double-execute); key confirmation round-trips to update_id so a redelivered confirmation cannot double-fire; max command age for mutating commands (discard older than N minutes with a summary reply; decide read-only exemption); treat 409 as another-bridge-running and exit loudly, lock file secondary.
  Witness: *"persist the getUpdates offset atomically in state/, ack-after-successful-dispatch with a per-update_id dedup journal"*.

## Open questions (answer all — OQ resolution owned by C6 `spec-telegram`, NOT this stub)

1. Command grammar v1: `/status [--delta]`, `/peek <name>`, `/send <name> <msg>` (or reply-to a worker's last message = implicit send), `/spawn <name> <dir> <task...>`, `/kill`, `/manager <request>` — right set? What's dangerous enough to require confirmation round-trip (kill? spawn with bypass)? (See the B5 command-set proposal above for the concrete starting split.)
2. Reply-to threading: Telegram reply → map message id → worker name. Store outbound message-id → worker mapping where? TTL?
<!-- F18 -->
   - **Confirmed disposition to fold (review F18 = review-doc M21) — reply-target validation.** dead: offer inline /respawn confirmation, or queue to the old sid's mailbox so the respawn drain delivers it (compatible with journal-injection-at-respawn); cleaned: error reply with last-known result path. Must NOT auto-respawn.
     Witness: *"Must NOT auto-respawn"*.
3. Manager-on-call mechanics: `claude -p` with fleet skill in which cwd (fleet repo?), what preamble (fleet state digest injected vs manager runs `fleet status` itself), how does its reply route back (final result text → Telegram), and does it persist as a resumable manager session (probably yes — a durable "chief-of-staff" session with its own journal)? (Note: B4 above already fixes cwd = FLEET_HOME immutable + reserved registry name; this OQ resolves the remaining preamble/routing/persistence details.)
4. Message size/formatting: peek digests vs Telegram 4096-char limit; markdown escaping of code output.
5. Rate/spam control: watchtower event storm (5 workers crash) → digest batching window?
6. Failure modes: Telegram down (queue outbound in state/ and flush?), token revoked, two bridge processes (lock). (See the F16 constraint above for the confirmed offset/dedup/409 discipline that this OQ's answer must incorporate.)
7. Media: send diffs/journals as files? v1 or later?
<!-- F19 -->
8. **Two-manager arbitration (NEW open question, review F19 = review-doc M22).** Two manager-on-call turns (e.g. desktop-spawned + phone-spawned) could act on the fleet concurrently. Candidate dispositions: (a) act freely, document mailbox-merge and last-writer-wins for kill/respawn; (b) restrict destructive commands to confirmation round-trips (ties into OQ1); (c) share state via the durable chief-of-staff journal. Decide and name the carried invariants (single-writer registry untouched; one-live-claude enforced per-worker by existing guards).
   Witness: *"single-writer registry untouched; one-live-claude enforced per-worker by existing guards"*.

## Testing

<!-- F30 -->
**Test contract (review F30 = review-doc U7/M23).** All Bot API traffic through one transport function/class pointable at a local fake Bot API (stdlib http.server fixture with canned getUpdates/sendMessage). REQUIRED tests: wrong chat id → no fleet action AND no reply; command grammar parse table; reply-id→worker map incl. TTL expiry; >4096-char splitting; Telegram-down → outbound queued and flushed; second bridge refused; manager-on-call turn with a stubbed claude launcher. Phone-only campaign stays as acceptance soak.
Witness: *"wrong chat id → no fleet action AND no reply"*.

## Invariants touched

Cites the canonical numbered invariants (SPEC.md §2 "Architectural invariants (numbered)").

- **single-writer registry (invariant 6).** Preserved: the manager-on-call session is a registry entry (B4), so it is spawned/claimed only through `fleet.py` under `fleet.lock` like any worker — the bridge never writes `fleet.json` directly. Two-manager arbitration (OQ8) explicitly carries "single-writer registry untouched".
- **one-live-claude-per-session (invariant 7).** Preserved: because the manager is a registry entry, the existing pre-claim guard gives it exactly-one-live-turn for free — a send-while-working queues to the mailbox instead of launching a second live claude (B4). OQ8 carries "one-live-claude enforced per-worker by existing guards".
- **cwd-scoped resume (invariant 5).** Preserved: the manager-on-call cwd = FLEET_HOME is immutable (B4), so it resumes only in its recorded, immutable cwd exactly like every worker — no privileged session escapes cwd-scoping.

## Done criteria

Full campaign run phone-only: spawn via manager-on-call, mid-task steer via reply, needs-input question answered from phone, results collected — while the desktop stays untouched.
