# Spec: Autoclean — staleness is cleaned up without anyone remembering

**Status:** ready-for-build (mc-autoclean, 2026-07-16)
**Inherits:** SPEC.md invariants, terminal-surface views doctrine, native-agents pivot §5.1.2 (auto-archival, shipped as `fleet archive`), CLAUDE.md irreversibility doctrine (`fleet clean` is the only deleter).

## Problem

`fleet archive` (TTL sweep) and `fleet clean` exist but require someone to run them. Between campaigns nothing runs, so retired workers and daemon husks accumulate (observed 2026-07-16: 13 stale workers, 15 `m0-*` daemon husks sitting for days).

## Decisions

<!-- ac-trigger -->
**D1 — trigger is an OS scheduler running a new first-class command, `fleet autoclean`; no opportunistic piggyback.** The stated gap is *"between campaigns nothing runs"* — piggybacking on mutating commands cannot close that gap by definition (between campaigns, no mutating commands run either), while a scheduler closes both the between-campaigns case and the while-in-use case (it fires on its interval regardless). Piggyback would also add a roster fetch + best-effort `claude rm` subprocesses to every `spawn`/`send` hot path and mint a new failure-isolation surface inside commands that already carry delicate lock/commit choreography — the C4/M-B lesson that fix waves and riders mint new Criticals argues against it for no coverage gain. Views stay untouched: `fleet autoclean` is an ordinary *mutating* CLI command (terminal-surface doctrine unamended); it is invocable by the Windows Scheduled Task (`fleet init --autoclean` installs it), by a supervisor watchtower beat, or by hand — one code path, three callers.

Scheduler mechanics live in the platform adapter (`autoclean_task_install/query/remove` on `_WindowsPlatform`, `schtasks`-based; `_PosixPlatform` raises `UnsupportedPlatformError` — the clean seam invariant 8 requires; cron/systemd-timer fills it in Phase 1.5).

<!-- ac-tiers -->
**D2 — three tiers; only the reversible two are default-on.**

- **Tier 1 (default-on): archive TTL pass.** `cmd_autoclean` invokes the existing `cmd_archive` full pass (all workers, TTL default 24 h, `--ttl-hours` forwarded). Every T9 gate rides along unchanged: terminal status only, roster-live skip, no-outcome ⇒ never archived, `limited` never archived, conditional commit under lock, G9 epoch freeze.
- **Tier 2 (default-on): daemon-husk removal.** `claude rm` of roster sessions that fleet spawned but no longer tracks live. **Ownership discriminator (precise, sid-based, default-deny):**
  - *owned(sid)* ⇔ sid appears in ≥1 of: (a) any registry record's `session_id` or `retired_sids` (tombstones included), (b) a sid-shaped (UUID) filename under `logs/archive/*/` (evidence files are sid-named; survives tombstone deletion), (c) any `session_id` field in `state/events.jsonl` (fleet stamps `turn_started`/`archived`/`cleaned` events with sids; survives `fleet clean`).
  - *protected(sid)* ⇔ sid is the `session_id` or a retired sid of a **non-archived** registry record — a live worker's history is `fleet archive`'s territory, swept at retirement, never out from under a tracked record.
  - *husk* ⇔ roster sid where owned ∧ ¬protected ∧ roster entry not live (no `status`/`pid` keys — the same liveness test archive/status use) ∧ no pending `mailbox/<sid>.md`.
  - Everything else — foremost the operator's own interactive sessions — is *foreign* and untouchable. A sid fleet has no record of is **never** selected, even if its name matches fleet's `cat|name|hint` convention (names are ai-title-mutable — 5.1.3 hazard — and convention-matching would be exactly the "touch sessions fleet didn't spawn" failure the directive forbids).
  - Consequence, accepted: husks whose sids fleet never recorded (M-0 hand-spike sessions, pin-test runs against temp `FLEET_HOME`s) stay foreign; they need one manual `claude rm` pass and cannot recur for fleet-spawned sessions.
- **Tier 3 (default-OFF, opt-in flag): tombstone expiry.** `fleet autoclean --expire-tombstones-hours N` removes registry tombstone entries whose `archived_at` is older than N **and** whose evidence move is complete (`_archive_resume_pending` false). It deletes **no files** — `logs/archive/<name>/` stays on disk, so no journal that isn't preserved is ever destroyed and `fleet clean` remains the only file-deleter (doctrine intact). Trade-off, accepted and deliberate: an expired tombstone's archive dir becomes invisible to `fleet clean`'s tombstone sweep — history-on-disk outlives registry hygiene; deleting it stays a manual act. Absent the flag (and the scheduled task never passes it), tombstones live forever until an operator runs `fleet clean`.

**`fleet clean` tiering split (finding from today):** `clean` gains mutually exclusive `--dead-only` (spare tombstones — sweep only confirmed-dead workers) and `--tombstones` (sweep only archived tombstones — no probing, no legacy recompute). Default stays today's behavior (both).

<!-- ac-safety -->
**D3 — safety rails.**
- Never sweep pending mail or a live turn: tier 1 inherits archive's status/roster/outcome gates; tier 2 skips roster-live entries, protected sids, and any sid with a non-empty mailbox file.
- Lock discipline: registry snapshots under `fleet.lock`, roster fetch and every `claude rm` outside it (F4 doctrine); no lock held across subprocesses.
- Tier isolation: each tier runs in its own try/except — a tier-1 failure never blocks tier 2; errors are printed, recorded in the run stamp, and reflected in exit code 1 (the scheduler ignores exit codes; events carry the signal).
- Concurrency: two racing autocleans — registry writes are conditional-commit under lock (archive) or pop-under-lock (tier 3); `claude rm` is idempotent best-effort. Sweep racing a spawn: a just-dispatched sid is either roster-live (skipped) or not yet in any fleet record (unowned ⇒ default-deny skipped).
- Epoch: tier 2 refuses when the roster fetch fails or `native_epoch_suspicious` fires (same G9 line archive/clean use).

<!-- ac-observability -->
**D4 — observability.** Per-item events already exist (`archived`) or are added (`husk_removed` with sid, `tombstone_expired`); every run appends one `autoclean_run` summary event and rewrites `state/autoclean-last-run.json` (timestamp + counts + errors). `fleet doctor` gains a note-only `autoclean` check: scheduled task installed/missing (via the adapter query), and "installed but last run > 48 h ago" staleness from the stamp — note-only per doctor doctrine (only broken infrastructure turns doctor red).

## Command surface

- `fleet autoclean [--ttl-hours F] [--expire-tombstones-hours F] [--dry-run]` — tier 1 + tier 2; tier 3 only with its flag. `--dry-run` previews all tiers, mutates nothing, rm's nothing.
- `fleet init --autoclean [--autoclean-interval-hours N]` — idempotent install/update of Scheduled Task `claude-fleet-autoclean` (`schtasks /Create /F /SC HOURLY /MO N`, default every 6 h, valid 1–23) running `"<python>" "<fleet.py>" autoclean`. Refuses to clobber a same-named task whose command doesn't contain `autoclean` unless `--force`. Composable with `--statusline`.
- `fleet init --autoclean-remove` — uninstall (`schtasks /Delete /TN claude-fleet-autoclean /F`). Manual equivalent documented for operators without fleet at hand.
- `fleet clean [--dead-only | --tombstones]` — manual tiering split.

## Testing

Unit: ownership discriminator table incl. **fault-inject** (a foreign roster sid must never be selected — the test seeds a foreign session alongside a genuine husk and fails if the owned-set filter is bypassed); protected sids of live records spared; tombstone/events/archive-dir sid sources each recognized; live-entry and pending-mail gates; tier isolation (tier-1 crash ⇒ tier 2 still sweeps); tier-3 default-off (ancient tombstone untouched without the flag) + pending-move tombstone never expired + files untouched; dry-run mutates nothing; clean `--dead-only`/`--tombstones` semantics; init install/refuse-foreign/force/idempotent/remove via injected fake `run`; doctor check note-only on every path.
