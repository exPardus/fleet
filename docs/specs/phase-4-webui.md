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

A week where fleet interaction happens primarily through the board during campaigns; peek/send/attach round-trip demonstrably faster than terminal equivalents; CSRF protection verified.
