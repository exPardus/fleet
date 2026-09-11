# Usage-Limit Resilience — binding design-intent input (2026-07-08)

**Status:** binding input for Campaign 1 (spec) + Campaign 2 (kernel). Authored by the fleet manager at Altai's request (turn-one budget touchpoint, 2026-07-08). There is **no review-doc finding** for this feature — this document is its single binding input, quoted verbatim into the owning task files per PLAN §0.2.4 (one binding input, no re-interpretation). Plan ID for this item: **UL1** (does not collide with review-doc M-numbers or SPEC F1–F16).

---

## 1. Requirement (Altai, verbatim intent)

> "a way for the fleet to restart itself if it hits a usage limit for a 5 hour or weekly session"

Operator is on the **Claude Max 20x** plan. That plan meters usage on two windows: a **5-hour rolling session window** and a **weekly cap**. When a window is exhausted, `claude -p` turns fail until the window resets. Today a fleet that hits the limit strands: worker turns error out and the manager stalls, requiring a human to notice and restart everything after reset.

**Desired behavior:** when a turn ends because the account hit a usage limit, the fleet must **park** the affected worker (not mark it dead, not mark it idle-and-done), record the reset horizon, and **auto-resume** the pending work once the window resets — with the operator notified, and without a human babysitting the clock.

## 2. Why this is not already covered

- It is **not** `dead`: the worker did not crash and its task is not finished; killing/respawning loses the in-flight intent and (on weekly caps) would just re-hit the wall.
- It is **not** budget-exceeded (M5/M18/M24 territory): those are *dollar/token ceilings the operator sets per worker*. A usage-limit hit is an *account-wide plan wall* with a *reset time*, orthogonal to per-worker caps. A worker can hit the plan limit at $0.00 of its own budget.
- It is a **new turn-end classification** that the B1 state machine (spec-amend-1-state) does not enumerate, and a **new resume trigger** nothing in the CLI performs.

## 3. Concrete starting proposal (the spec task refines; does not restart from zero)

The spec worker MUST start from this proposal and either adopt or amend each clause with cited reasoning — not design afresh:

1. **New status / sub-state `limited`** (name negotiable) in the §4 schema, distinct from `working|idle|attached|dead`. A `limited` worker has an unfinished turn intent (its mailbox/journal preserved) and a recorded reset horizon field, e.g. `limit_reset_at` (ISO-8601) + `limit_kind` (`session_5h | weekly`).
2. **Detection at turn-end:** the launch/turn-end classifier recognizes a usage-limit turn end from the stream-json / exit / stderr signal the installed CLI actually emits, and extracts the reset time if the CLI provides one. → **This is an environment-dependent contract: §0.2.9 BLOCKED-with-evidence rule applies.** The spec task PROBES the installed `claude` (2.1.204) for the real limit signal + reset field and records the evidence; if the signal is not reliably detectable in `-p` stream output, the spec records `DECISION: usage-limit undetectable in -p — <fallback>` (candidate fallback: treat a turn that errored with no result event AND a limit-shaped stderr as limited-suspected, park conservatively, surface for operator confirmation) rather than building against a guessed contract.
3. **`limited` is sticky-until-reset, never demoted to dead by recompute.** It coordinates with the B1 recompute rules (spec-amend-1-state): a `limited` record is exempt from the working→dead crash path. When `now >= limit_reset_at`, the worker becomes **resume-eligible**.
4. **Resume trigger:** a manager/watchtower-invokable sweep (candidate: `fleet resume-limited`, or folded into `fleet status`/a launch-time check) that relaunches resume turns for any `limited` worker whose reset horizon has passed, draining mailbox per the universal drain rule. The spec decides whether resume is (a) an explicit operator/manager sweep, (b) an automatic check at status/launch time, or (c) watchtower-driven — and names the lock discipline (goes through the same `fleet_lock`-guarded launch path as every other turn; inherits pre-claim / one-live-claude).
5. **Surfacing:** `fleet status` flags `limited (resets <when>)`; `fleet doctor` NOTEs any worker parked past its reset horizon without resuming; the notifier (Phase 2) gets a limit event.
6. **Manager-level self-restart scope:** the manager session itself can hit the wall. SPEC §11 already says "manager dies → new manager runs `fleet status`, continues." The spec decides whether C1 covers only **worker-level** park+resume (recommended for the readiness boundary) and records manager-level auto-wake as an explicit deferral/OQ, OR specs a thin manager outer mechanism now. Do not silently drop the manager-level question.

## 4. Open questions the spec MUST resolve (silence = spec not done)

- **UL-OQ1 (env probe):** exact detection signal + reset-time field from installed `claude` — with evidence, or a recorded fallback per §0.2.9.
- **UL-OQ2:** state name + schema fields (additive rule per M1); recompute interaction with B1 (exemption from crash-dead path).
- **UL-OQ3:** resume trigger mechanism + lock discipline (sweep vs status-time vs watchtower); who invokes it and how often.
- **UL-OQ4:** 5h-session vs weekly distinction — a weekly park can last days; cap/notify behavior and whether weekly-parked workers auto-resume or require operator ack.
- **UL-OQ5:** interaction with `--max-budget-usd` / token ceiling (orthogonal; a limited turn is not a budget-trip and must classify distinctly, extending the M5/M18 classification work).
- **UL-OQ6:** manager-level scope (C1 worker-level only + deferral, or manager outer loop now).

## 5. Invariants touched

single-writer registry (resume goes through `fleet_lock`), one-live-claude-per-session (resume obeys pre-claim; a parked worker has no live claude), exit-0 hooks (detection is in fleet.py launch/classify paths, not hooks — hooks stay read-only per M6). The spec's `## Invariants touched` section names these.

## 6. Where this folds

- **Campaign 1 (spec):** new SPEC.md amendment link **`spec-amend-4-usagelimit`**, sequential last in the Wave-1A chain (after `spec-amend-3-testing`) — same-file (SPEC.md) single-writer rule. Adds the §4 schema fields, a §11 usage-limit row, a §4/§5 park+resume contract, and §12 required regressions, with an appendix-style disposition entry. Reviewed in Wave 1C (`c1-review-spec-core` scope extended to cover it) and read in full at the 1E checkpoint.
- **Campaign 2 (kernel):** implemented as **hardening kernel item 11** in `docs/specs/phase1-hardening-kernels.md` (added by `stub-inject-kernels-webui`), built in the C2 fleet.py chain (a new link or folded into an existing one at C2 planning) with a live harness demo (hook-source per §0.1.6) proving a limit-parked worker resumes after its recorded reset horizon passes.
- **Altai ratification:** the resulting design is surfaced at the C1 verification checkpoint (human touchpoint 4 — decision ratification) before C2 builds against it.
