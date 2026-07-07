# Spec: Telegram bridge (Phase 3) — fleet in your pocket

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md. Requires watchtower (events feed the bridge).

## Goal

Two-way Telegram control: events out, steering in, and manager-on-call — a message can wake a headless manager turn that reads fleet state, decides, acts, replies.

## Scope

In: bot long-polling loop (inside `fleet watch` or sibling process — decide), outbound notifier, inbound command grammar, reply-to threading → worker addressing, manager-on-call turn, auth. Out: web UI, voice, group-chat workflows, multi-user.

## Fixed constraints

- Single authorized chat id (owner). Token + chat id in state/ (never git). Every inbound message hard-checked against chat id before ANY action.
- Long-polling only (no public webhook, no exposed ports).
- stdlib HTTP (urllib) is enough for Bot API — keep no-deps rule unless file uploads make it miserable (then justify).
- Manager-on-call turns: budget-capped, cooldown-limited, permission mode fixed (accept? bypass? — decide and justify; it can spawn workers, so this is the highest-privilege path in the system).
- Note: machine already runs Claude Code Telegram channel infra (`telegram:configure` skill, ~/.claude/channels) — investigate reusing/wrapping it vs own bot before building own. Own bot = full control of threading/commands; channel infra = free auth+plumbing. Decide with evidence.

## Open questions (answer all)

1. Command grammar v1: `/status [--delta]`, `/peek <name>`, `/send <name> <msg>` (or reply-to a worker's last message = implicit send), `/spawn <name> <dir> <task...>`, `/kill`, `/manager <request>` — right set? What's dangerous enough to require confirmation round-trip (kill? spawn with bypass)?
2. Reply-to threading: Telegram reply → map message id → worker name. Store outbound message-id → worker mapping where? TTL?
3. Manager-on-call mechanics: `claude -p` with fleet skill in which cwd (fleet repo?), what preamble (fleet state digest injected vs manager runs `fleet status` itself), how does its reply route back (final result text → Telegram), and does it persist as a resumable manager session (probably yes — a durable "chief-of-staff" session with its own journal)?
4. Message size/formatting: peek digests vs Telegram 4096-char limit; markdown escaping of code output.
5. Rate/spam control: watchtower event storm (5 workers crash) → digest batching window?
6. Failure modes: Telegram down (queue outbound in state/ and flush?), token revoked, two bridge processes (lock).
7. Media: send diffs/journals as files? v1 or later?

## Done criteria

Full campaign run phone-only: spawn via manager-on-call, mid-task steer via reply, needs-input question answered from phone, results collected — while the desktop stays untouched.
