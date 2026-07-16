# Spec: Watchtower (Phase 2) — continuous monitoring

**Status:** stub — amendment-injected 2026-07-08 (Wave 1B `stub-inject-watchtower`); OQs NOT resolved — awaiting C5 `spec-watchtower` for the ready-for-build flip.
**Inherits:** SPEC.md, ROADMAP.md principles. Requires portability spec built first.

**[SUPERSEDED — native-substrate pivot 2026-07-13]** This stub's PID-liveness polling premise (dead/crashed detection via `probe_liveness`, kill-a-PID fault injection) is superseded: liveness now comes from the daemon roster + the outcome discriminator, not a poll loop probing PIDs. Watchtower's detect-and-notify duties fold into the supervisor's heartbeat/beat loop instead of a standalone `fleet watch` process. See `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §3/§4 and `docs/specs/native-substrate.md`. MOVED, not deleted — kept below for history; do not build against it.

## Goal

Foreground `fleet watch` loop: nothing in the fleet fails silently; context/budget managed proactively. Core CLI must remain fully functional when watchtower is not running (principle #2 / invariant 1 daemonless launch — watchtower is additive).

## Scope

In: watch loop, rule engine, typed events, notifier functions (desktop + file), `fleet status --delta`, `fleet conflicts` advisory sweep. Out: Telegram (Phase 3), any web endpoint (Phase 4), modifying worker hooks, auto-respawn (see F20 decision below).

<!-- F20 -->
**DECISION (F20 = review M10 — auto-respawn CUT from Phase 2):** cut auto-respawn from Phase-2 scope (v1 detects and notifies context-threshold/dead/idle-with-mail); move it to a post-Phase-3 re-vet gated on felt friction. Rationale: auto-respawn is a safety-critical autonomous-mutation subsystem with no hard caps (respawn-loop risk), and the human-vetted lever — remote MANUAL respawn — arrives Phase 3; shipping an unbounded autonomous mutator before that lever exists is the wrong order. v1 watchtower is DETECT-AND-NOTIFY only. (The lossless-auto-respawn done-criterion is deleted accordingly — see Done criteria.)

<!-- F21 -->
**DECISION (F21 = review M11 — notifier is NOT a plugin framework):** the notifier interface is a single notify(event) iterating a static in-code sink list — no registration, no routing config file. Desktop + file are the two v1 sinks; Telegram (Phase 3) = append one sink function; revisit only if a fourth, out-of-repo sink materializes. (Constrains OQ5, which C5 still returns a verdict on.)

<!-- F22 -->
**DECISION (F22 = review M12 — service install → doc snippets):** v1 = foreground `fleet watch` + docs/ snippets for hand-installed per-OS autostart, which preserves OS-managed crash-restart (answering graveyard #10's cause of death — no bespoke restart wrapper to itself die). `fleet doctor` gains only a 'watchtower heartbeat stale' NOTE; install/uninstall subcommands are deferred to a post-use-week re-vet. No service-install command ships in Phase 2.

Salvaged kernels to include (from IDEA-FORGE-REPORT §4 — build as scoped, do not expand toward their dead parent ideas):
- `fleet conflicts` — one-shot advisory `git merge-tree` sweep across worker branches/worktrees, gated on git ≥ 2.38, plain-text output. NOT a live detector, NOT a lock system. (Input-universe pinned in OQ by F24 below.)
- Mute-until-T: per-rule notification mute flag with a single timer (`fleet mute <rule|worker> --for 2h`). NOT an ack/suppress escalation ladder.

## Fixed constraints

<!-- F8 -->
**READER/ACTION constraint (F8 = review M9 — rewritten; respawn clauses scoped per FIX-5):** watchtower is a reader for RULE EVALUATION; every ACTION (send, respawn) executes only via the same lock-guarded fleet.py command paths as the CLI — a direct function call within a short-lived lock scope, never holding the lock across the poll loop — inheriting pre-claim, sticky-dead, `--force` guards, and universal drain semantics. **In v1 the only ACTION is send/notify** (auto-respawn is CUT — F20): on send-path guard FAILURE (pre-claim rejected, lock unavailable) emit an event and back off; never retry-spin holding the lock. **The respawn action path + its loop cap are DEFERRED with F20; the lock-discipline here applies when auto-respawn is re-vetted** (post-Phase-3) — v1 keeps only the read + send/notify discipline. This supersedes the old "READER of logs/registry plus single-writer for events.jsonl" wording: the single writer of `fleet.json` stays `fleet.py` under `fleet.lock` (invariant 6); events.jsonl is a lock-guarded append by whichever `fleet.py` invocation runs.

<!-- B2 -->
**Reader handle discipline (B2 = review M9/B2 reader half):** all log/state readers open-read-seek-close within each poll cycle; no handle outlives a poll tick. Tailers tolerate replacement between polls (size shrink / file-ID change → reset cursor). This keeps the watch loop from pinning rotated/replaced files and from carrying a stale offset across a truncation.

<!-- F23 -->
**Autostart + desktop-notifier platform targets (F23 = review M13):** the Windows target is a LOGON-TRIGGERED INTERACTIVE scheduled task (schtasks /sc onlogon, run-only-when-logged-on, current user — no /ru SYSTEM, no service wrapper); macOS = launchd user agent in the gui domain; Linux = systemd --user unit. All three sit behind the platform adapter (invariant 8). Specify the Windows desktop notifier as the PowerShell WinRT toast shell-out through the platform adapter; the file notifier is the always-works fallback when the toast path is unavailable.

<!-- F29 -->
**[SUPERSEDED — native-substrate pivot 2026-07-13]** The "kill a live turn PID" fault-injection premise below assumes PID-liveness probing; a native-substrate equivalent would fault-inject against the daemon roster / outcome discriminator instead. See header.

**Rule-engine test strategy (F29 = review M16):** rules are pure functions (parsed stream events + registry snapshot → typed event or None), unit-tested against the git-tracked fixture corpus from M7. The file notifier is the test seam for fault-injection acceptance tests: kill a live turn PID → crash event within ≤1 poll interval; synthetic result events → thresholds fire at spec'd numbers; watchtower stopped → full CLI suite still green (principle #2, directly testable). The week-of-use soak stays IN ADDITION to, never instead of, the injectable tests.

- Rules and thresholds live in a config file in state/ or a git-tracked `watch.toml` — decide which (machine-specific overrides vs shared defaults). [C5 to resolve]
- Polling only (stdlib constraint): no watchdog/FS-event dependency.

## Open questions (answer all)

<!-- OQ1 -->
1. **Rule set v1 — the load-bearing six.** OQ1 must return an explicit detectability verdict for all six rules including needs-input-detected and journal-staleness. The full ROADMAP six-rule watchtower list — NOTHING may silently vanish:
   1. **dead/crashed** — turn errored / no `result` event (B1 crash path).
   2. **idle+mail** — worker idle with an unclaimed `mailbox\<sid>.md` > N min.
   3. **context-threshold** — context burn > X% (estimation pinned by F25/OQ2 below).
   4. **log-bloat** — log/state growth past a size ceiling.
   5. **journal-staleness** — journal unchanged > N turns (mtime vs turn count vs content marker — undecided).
   6. **needs-input-detected** — worker appears to be waiting on input; HOW is open (stream-json has no "waiting" event in `-p` mode since turns just end).
   C5 `spec-watchtower` must return a per-rule detectability verdict (detectable from stream logs / fixture corpus? with what signal?) for EACH of the six — neither needs-input-detected nor journal-staleness may be dropped for being hard.

<!-- F25 -->
2. **Context-% estimation (F25 = review M15 — rewritten, resolved-in-principle):** context % = most-recent-result-event input-side usage / model window. The remaining sub-question is the model-name → window-size mapping without a rot-prone hardcoded table. On attach, mark the worker's context estimate UNTRUSTED, re-baseline from the first post-release headless turn's result event, and add a rule state 'context estimate stale (attached N h)'. C5 to settle only the model→window resolution mechanism.

<!-- F24 -->
3. **`fleet conflicts` input universe (F24 = review M14 — new OQ):** resolve git common dir per worker cwd; HEAD of each worker's cwd at scan time with uncommitted-blindness noted in output; pairwise among co-repo workers + each vs configured base; skip non-repo/detached with a note. Decide whether spawn records branch-at-spawn — if so, flag the SPEC §4 registry-schema amendment NOW (additive field under invariant 6's single-writer schema rule) rather than after Phase-2 build.

4. Notifier interface final verdict — F21 decision above fixes it to a static in-code sink list; C5 confirms and specs the notify(event) signature. Keep it Phase-3-Telegram-ready without redesign.
5. `status --delta` cursor: per-consumer cursor file keyed how (tty? explicit --consumer name?), and does watchtower share the mechanism?
6. Watchtower liveness itself: who watches the watchman? (`fleet doctor` heartbeat NOTE per F22 + OS-managed autostart restart per F23 is probably enough — confirm.)
7. Manager wake-up: should watchtower trigger a headless manager turn on critical events (pre-Telegram manager-on-call)? If yes, spec guardrails (which events, budget cap, cooldown) — note this routes through the F8 lock-guarded action path, not a direct launch from the read loop.

## Invariants touched

- **Invariant 6 — single-writer registry.** Watchtower does NOT become a second writer of `fleet.json`. F8 pins every mutating ACTION to the lock-guarded `fleet.py` command path (short-lived lock scope, never held across the poll loop); the read loop only reads. Not broken.
- **Invariant 7 — one-live-claude-per-session.** Auto-respawn (the only path that could spawn a second live claude) is CUT from Phase 2 (F20); the remaining detect-and-notify loop launches no turns. Any future respawn/resume action reuses the CLI's pre-claim + one-live guard via F8. Not broken.
- **Invariant 1 — daemonless launch.** Watchtower is additive: an OPTIONAL foreground `fleet watch` loop (F22), never a required resident process. The core CLI works fully with it stopped (F29 test seam asserts this). It reads the single-source registry/logs and derives views (invariant 9); it does not become the system's heartbeat. Not broken.

## Done criteria

Week of real use: zero silently-dead workers; context-threshold notification observed firing before a worker degraded; CLI unaffected with watchtower stopped; fault-injection acceptance tests (F29) green (killed-PID → crash event ≤1 poll interval; synthetic thresholds fire at spec'd numbers). *(Auto-respawn done-criterion deleted per F20 — auto-respawn is out of Phase-2 scope.)*
