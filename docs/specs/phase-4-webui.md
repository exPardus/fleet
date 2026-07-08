# Spec: Web UI (Phase 4) — mission control

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md. Requires watchtower; interleaves with Phase 5.

## Goal

Local dashboard: whole fleet at a glance, live peek, steering, diffs, spend — kills the habit of running `fleet status` by hand. View only — no data or logic the CLI doesn't have (principle #1/#3).

## Scope

In: local HTTP server (`fleet web`), fleet board, worker detail (peek stream, journal, send box, attach launcher), events timeline, spend telemetry, knowledge browser/editor. Out: auth/multi-user (localhost only; Tailscale serve later), task kanban (cards are SESSIONS not tasks — see PRIOR-ART, we're not rebuilding Vibe Kanban), mobile app.

## Fixed constraints

- Boring tech: stdlib http.server or single-file framework decision with justification; single HTML file + htmx/alpine-class frontend, NO build step, no node toolchain.
- Server is a reader of state/logs + an invoker of fleet.py functions for actions (send/spawn/kill call the same code paths as CLI — no parallel logic).
- Live updates: SSE (works with stdlib) over websockets unless justified.
- Binds 127.0.0.1 only by default. Remote access = Tailscale, never port-forward; document.
- <!-- B2-webui --> **SSE / reader handle-discipline (B2 reader half).** The SSE follow mode and the peek pane must open-read-seek-close per poll tick: **all log/state readers open-read-seek-close within each poll cycle; no handle outlives a poll tick**, and a reader tolerates log rotation between polls (shrink / file-ID reset → re-open from the top, never a stale fd holding a rotated inode).
- **ThreadingHTTPServer** (concurrent SSE streams + board polls must not head-of-line block each other), **127.0.0.1 bind** as above, and a **Host-header rebinding check** on every request (reject requests whose `Host` is not `127.0.0.1`/`localhost[:port]`, so a DNS-rebinding attack from a browser can't reach the server through a hostile hostname). (Lower-confidence constraints, retained for the Phase-4 spec task.)

## Decisions

- <!-- webui-readonly --> **v1 = READ-ONLY.** **v1 has zero write endpoints; attach = copy-command; send/spawn = use the CLI or telegram; all mutating POST → 405.** The board, worker detail, peek stream, events timeline, spend telemetry, and knowledge browser are all derived read views. "Attach from browser" (OQ5) becomes a displayed copy-command for the operator; send/spawn (OQ8's execution surface) are not offered in the UI — the operator uses the CLI or the Telegram channel. Any mutating POST that reaches the server returns `405 Method Not Allowed`. This resolves OQ7 (knowledge editing) as read-only for v1.
- <!-- webui-csrf --> **CSRF / same-origin is a hard precondition** for the future write-forms backlog item — whenever write forms are earned by demonstrated friction (the operator hitting real, repeated pain that read-only can't solve), the machinery must already be specced: a **CSRF token per session, checked on every mutating POST**, plus the same-origin/Host-header check above. It is spec'd as the gate now and built only when friction earns the write forms — never bolted on after the first write endpoint ships. This is the standing answer to OQ8.
  **Witness:** "CSRF/same-origin is a hard precondition for the future write-forms backlog item"

## Open questions (answer all)

1. Server lifecycle: part of `fleet watch` process or separate `fleet web`? (Separate keeps watchtower minimal; same process saves a service. Decide.)
2. Board columns: by status (working/idle/attached/needs-attention/dead)? What's the needs-attention aggregation from watchtower events?
3. Peek stream: SSE of digest lines — reuse peek's parser with a follow mode? How much history on page load?
4. Diff viewer: workers edit arbitrary repos — `git -C <cwd> diff` vs journal-declared changed files? Uncommitted vs branch diff? (Steal Conductor's diff-first review UX, but scope tightly.)
5. Attach from browser: can't launch a terminal from the server portably when accessed remotely — button copies the attach command? Local-only launches via platform adapter?
6. Spend telemetry: per worker/project/day aggregation from result events — where computed (watchtower pre-aggregates vs on-request scan)? Retention?
7. Knowledge editing in browser: raw markdown textarea + commit button (git commit from server?) or read-only v1?
8. Security review item: send box + spawn form = command execution surface even on localhost (CSRF from a malicious website hitting 127.0.0.1). CSRF token or same-origin check REQUIRED — spec it.

## Done criteria

A week where fleet interaction happens primarily through the board during campaigns; peek/send/attach round-trip demonstrably faster than terminal equivalents; Host-header/same-origin rejection + mutating-POST→405 verified; CSRF-token machinery specced (not built until write forms are earned). (v1 read-only: "send/attach round-trip" = the copy-command path + CLI/telegram; write-form round-trip is deferred until friction earns it.)

## Invariants touched

Cites the numbered "Architectural invariants (numbered)" section of `docs/SPEC.md`.

- **one-state-many-views (9)** — the web UI is another read-only view over the registry + logs; it derives everything and holds no independent state. The read-only v1 decision is this invariant made literal for Phase 4.
- **daemonless launch (1)** — `fleet web` is additive/optional; the CLI works fully with the web server stopped, and the server is a short-lived reader, not a required resident process.
- **single-writer registry (6)** — the server is read-only and never writes `fleet.json`; with zero write endpoints in v1 there is no second writer, and the CSRF/same-origin gate exists precisely so that any future write path still routes through `fleet.py`'s lock-guarded code paths rather than the server mutating state directly.
