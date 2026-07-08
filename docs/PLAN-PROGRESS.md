# PLAN-PROGRESS — wave ledger (cross-session cursor)

The mutable cursor against the immutable contract `docs/PLAN.md`. A resuming manager reads this **first** (runbook step 2). Status vocab: `pending | dispatched | done | blocked | deferred`. Updated at each task close + gate; committed in every campaign's knowledge-loop step (§0.3h).

**Readiness boundary (this manager's mandate):** execute through **C2 merge gate**, then STOP for Soak Gate 1 sign-off. Do NOT start C3+. C1 doc-only in main repo; C2 code in worktree `C:\proga\claude-fleet-wt\c2`.

**Turn-one decisions (2026-07-08):** POSIX box = dev server 192.168.1.202; Max-20x plan, generous cap; new feature UL1 (usage-limit resilience) folded into C1 (`spec-amend-4-usagelimit`) + C2 (kernel item 11) — binding input `docs/reviews/USAGE-LIMIT-RESILIENCE-INTENT-2026-07-08.md`. See `knowledge/lessons.md`.

---

| Campaign | Wave / task | Status | Commit / evidence | Date |
|---|---|---|---|---|
| C1 | 1A-1 `spec-amend-1-state` (B1/M2/M3/M4) | done | c458641 (F17–F20; truth-gate PASS) | 2026-07-08 |
| C1 | 1A-2 `spec-amend-2-schema` (M1/M5/M6/M18/B2 + additive rule) | done | 8b01179 (F21–F25; truth-gate PASS) | 2026-07-08 |
| C1 | 1A-3 `spec-amend-3-testing` (M7/M8/M25 + 12 drift items) | dispatched | — | 2026-07-08 |
| C1 | 1A-4 `spec-amend-4-usagelimit` (UL1 — new feature) | pending | task file ready | — |
| C1 | 1B stub-inject ×7 (watchtower/telegram/providers/portability/phase5/kernels-webui/roadmap) | pending | — | — |
| C1 | 1C review split (`c1-review-spec-core` ∥ `c1-review-spec-stubs`) | pending | — | — |
| C1 | 1D fixes (original builders via send) + `c1-review-spec-2` re-review ≤3 | pending | — | — |
| C1 | 1E verify checkpoint + `c1-knowledge` ∥ `c1-playbook` | pending | — | — |
| C2 | 2A `harness-live` ∥ `harden-hooks` | pending | — | — |
| C2 | 2A-close gate (FLEET_LIVE=1 hook-source=worktree) | pending | — | — |
| C2 | 2B chain `harden-fleet-a` → `-b` → `-c` → `-d` (+ UL1 kernel) | pending | — | — |
| C2 | 2C reviews (`c2-review-code` ∥ `c2-review-adversarial`) | pending | — | — |
| C2 | 2D fix waves ≤3 (original builders) | pending | — | — |
| C2 | 2E merge gate (pre-merge pytest → merge → live tier → doctor → hook-smoke; revert-on-red) + `c2-knowledge` | pending | — | — |
| C2 | **>>> STOP: hand to Altai for SOAK GATE 1 <<<** | pending | — | — |
| C3 | Phase-1 close (`p1-docs-sync` + external campaign + workload queue + SOAK GATE 1) | pending | GATED: readiness boundary | — |
| C4 | Phase 1.5 portability (spec→build→ci→posix-smoke→SOAK 1.5) | pending | GATED | — |
| C5 | Phase 2 watchtower (spec→chain→accept-tests→SOAK 2) | pending | GATED | — |
| C5b | Phase 2.5 providers (spec always; build demand-gated) | pending | GATED | — |
| C6 | Phase 3 telegram (spec→2 reviews→chain→tg-live→SOAK 3) | pending | GATED | — |
| C7 | Phase 4 web UI read-only (demand-gated build) | pending | GATED | — |
| C8 | Phase 5 intelligence flag-sized (demand-gated build) | pending | GATED | — |
| P6 | Reach backlog (demand-driven, per-item stub+gate) | pending | GATED | — |
