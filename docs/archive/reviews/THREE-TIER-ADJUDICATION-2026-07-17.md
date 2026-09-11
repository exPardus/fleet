# Three-tier command — manager adjudication of the dual-lens design gate

**Date:** 2026-07-17. **Adjudicator:** supervising manager (inc-20260717T011200Z-f1d0).
**Inputs:** `THREE-TIER-DESIGN-REVIEW-2026-07-17-break.md` (17 findings: 5 CRIT / 5 HIGH / 5 MED / 2 LOW, 18 receipts) and `THREE-TIER-DESIGN-REVIEW-2026-07-17-spec.md` (16 claims audited, 8 false/partly-false, 7 contradictions, 18 receipts). Both independent, both `VERDICT: restructure`.

## Ruling

**RESTRUCTURE — upheld.** `docs/specs/three-tier-command.md` stays `PROPOSAL`; no spec task may claim it as-is; no build delta from it may start. The operator's tier model itself is NOT refuted (both lenses agree the split is sound); the drafted mechanism is.

**The root cause, named identically by both lenses working independently:** fleet identifies actors by session id, and every steering primitive the draft relies on (fork-steer — the only way to start a turn in an idle session) mints a new session id. The claim protocol (`INCARNATION` sid key, `_require_claim_holder` exact-compare, `supervisor_claim_decision` roster join) breaks deterministically on the first beat, and degrades into the worst available failure mode: freeze-page against a healthy supervisor, then hourly self-seizure polluting the append-only journal.

## The binding restructure list (merged, deduped; break-lens MF# / spec-lens D#)

1. **Per-body claim nonce is a hard PREREQUISITE, its own slice, own review** (MF1, D1). Identity that survives fork-steer/respawn/handoff; enumerate every touchpoint by grep (INCARNATION schema, `_require_claim_holder`, `supervisor_claim_decision`, HANDSHAKE `--expect-sid`, `_SUPERVISOR_ENTRY_RE`, `_restamp_after_steer`); preserve the roster-liveness two-supervisor guard.
2. **Decide what the claim gates** (MF2). Journal-only + body-fencing, or claim-gate the mutating verbs. Silence ships the zombie class.
3. **`spawned_by` continuity across supervisor body changes** (MF-adjacent, D2) — without normalizing reflexive `--yes`.
4. **Substrate re-pin FIRST** (MF4, D4): `md-contract`'s 2.1.212 transient-daemon findings land in `native-substrate.md` before any spec is written against the daemon; the ratified three-tier spec states its daemon-lifecycle assumptions and the beat's G9 behavior explicitly (a stale roster currently PASSES the epoch check; a beat is a `send`, and `send` refuses under a suspicious roster — scheduler ignores exit codes ⇒ silently dropped beats).
5. **Beat = first-class `fleet beat` verb** (MF6, H3/H4): own error semantics (limited/freeze/handoff-in-flight/pending-decision without burning a model turn), run-stamp, the only thing `--supervisor-beat` installs. Consider the break-lens beat-worker split (claimless haiku beat that only decides "wake the supervisor?") — it is also the only drafted-mechanism answer to beat cost (D8: `send` has no `--model`; `model` is spawn-immutable).
6. **Scheduler bridge through the platform adapter, generalized** (MF8, D3): generic installer (`task_name`+`command`+`interval`); fix `_autoclean_task_is_ours` path-only predicate (silently voids the F4 guard the moment a second task exists); per the 2026-07-17 portability directive — three backends or an explicit `UnsupportedPlatformError` seam + tracked gap; doctor check for the new task; multi-flag refusal semantics. Also reconcile with the existing ScheduleWakeup heartbeat primitive the draft never mentions.
7. **Heartbeat decoupled from beat period; supervisor record archive/autoclean-protected by construction** (MF3: S=3600 vs N-hour beats ⇒ seizable N−1h of every N; archive TTL 24h vs schtasks 23h clamp ⇒ autoclean rm's the supervisor).
8. **Operator-gate routing = a state file, not a journal kind** (MF7, H5): answerable, un-re-derivable, nag-visible, stops the beat from burning turns while open.
9. **Drop the event-driven arm** (MF9, D7): its stated blocker misreads SPEC §8(a) (mailbox writes ARE sanctioned); the real blockers (hooks can't dispatch, target sid rotates, lost events are silent) make poll-on-beat strictly safer.
10. **`sup-spawn` routes through `dispatch_bg`; reserved-name check at `validate_name`** (D5, D6, MF-adjacent): `--settings`/`--add-dir`/registry record/`_worker_env` implications stated; rule on `respawn supervisor`/`kill supervisor` semantics (each stop-shaped verb owes a tombstone); reserve the body name mechanically (no RESERVED list exists today).

## Defects in SHIPPED code surfaced by this gate (filed separately from the design)

- **`cmd_sup_handoff_begin` hand-rolls argv, bypassing `dispatch_bg`: successor supervisor sessions have no hooks at all today** (spec-lens X3). SPEC §6 "one choke point" is inaccurate as written. Fix + SPEC correction owed regardless of three-tier's fate.
- **`_autoclean_task_is_ours` matches fleet.py path only** — latent F4-guard hole, harmless until a second fleet scheduled task exists (spec-lens C7/X5).
- Non-blocking, same-milestone candidates (break-lens M5, L2): caller provenance in `events.jsonl` + foreign-claim warn on `send`/`spawn`/`kill`; file the agents-menu retired-fork nag upstream.

## Sequencing (binding for M-D)

1. `md-contract` lands (substrate re-pin, pins 6/6, G-rows amended `[PENDING OPERATOR RATIFICATION]`).
2. Claim-nonce slice: spec task (drafting status, addresses items 1–3 above) → dual-lens review → build gated on operator ratification of the spec.
3. Three-tier re-draft ON TOP of the nonce spec + re-pinned substrate, answering items 4–10; then a fresh dual-lens gate. The draft's "plausibly cheap" section is withdrawn (spec-lens: false on receipt in three independent places).
4. Shipped-code defects (handoff-dispatch, ownership predicate) as small reviewed fix tasks after `md-contract` merges (same-file discipline).

**Both review verdict files are the authority for finding details; this adjudication only merges and sequences — no finding is re-interpreted.** Per the promotion rule, nothing here ratifies any spec; operator gates stay.
