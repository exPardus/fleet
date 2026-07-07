# Spec: Watchtower (Phase 2) — continuous monitoring

**Status:** stub — unclaimed
**Inherits:** SPEC.md, ROADMAP.md principles. Requires portability spec built first.

## Goal

Resident `fleet watch` process: nothing in the fleet fails silently; context/budget managed proactively. Core CLI must remain fully functional when watchtower is not running (principle #2).

## Scope

In: watch loop, rule engine, typed events, notifier plugin interface (desktop + file notifiers), `fleet status --delta`, auto-respawn policy, service install per OS (via platform adapter). Out: Telegram (Phase 3), any web endpoint (Phase 4), modifying worker hooks.

## Fixed constraints

- Same fleet.py/state model; watchtower is a READER of logs/registry plus the single-writer path for events.jsonl (resolve: CLI commands also write events — who owns the file? Likely: keep single-writer = fleet.py process whoever it is, lock-guarded append).
- Rules and thresholds live in a config file in state/ or a git-tracked `watch.toml` — decide which (machine-specific overrides vs shared defaults).
- Auto-respawn is OPT-IN per worker or global flag, never default.

## Open questions (answer all)

1. Rule set v1 (proposed: idle-with-mail > N min; turn crashed (dead status); context burn > X% estimated from cumulative tokens vs model window; budget > $Y; needs-input detection — how? stream-json has no "waiting" event in -p mode since turns just end; journal stale > N turns). Which are actually detectable from stream logs — verify each against real log samples before speccing detection logic.
2. Context-% estimation: cumulative input+output tokens per session vs model context window — is this derivable from result events across turns, and how wrong is it after auto-compaction inside the worker?
3. Polling vs filesystem watching: poll interval (5–15 s?) is simpler and portable; watchdog-style FS events need deps. (Constraint says stdlib → polling. Confirm cost is negligible.)
4. Auto-respawn safety: journal-quality gate — how does watchtower judge "journal fresh enough"? (mtime vs turn count vs content marker?) What if respawn loops (respawned worker burns context again immediately)? Cap per day?
5. Notifier interface: function-per-event-type or single notify(event) with routing config? Keep pluggable for Phase 3 Telegram without redesign.
6. `status --delta` cursor: per-consumer cursor file keyed how (tty? explicit --consumer name?), and does watchtower share the mechanism?
7. Watchtower liveness itself: who watches the watchman? (`fleet doctor` + a heartbeat file + service auto-restart is probably enough.)
8. Manager wake-up: should watchtower be able to trigger a headless manager turn on critical events (pre-Telegram version of manager-on-call)? If yes, that's a big power — spec guardrails (which events, budget cap, cooldown).

## Done criteria

Week of real use: zero silently-dead workers; context-threshold notification observed firing before a worker degraded; auto-respawn demonstrated lossless on a real task; CLI unaffected with watchtower stopped.
