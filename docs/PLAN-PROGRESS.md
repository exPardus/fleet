# PLAN-PROGRESS — wave ledger (cross-session cursor)

The mutable cursor against the immutable contract `docs/PLAN.md`. A resuming manager reads this **first** (runbook step 2). Status vocab: `pending | dispatched | done | blocked | deferred`. Updated at each task close + gate; committed in every campaign's knowledge-loop step (§0.3h).

**Readiness boundary (this manager's mandate):** execute through **C2 merge gate**, then STOP for Soak Gate 1 sign-off. Do NOT start C3+. C1 doc-only in main repo; C2 code in worktree `C:\proga\claude-fleet-wt\c2`.

**Turn-one decisions (2026-07-08):** POSIX box = dev server 192.168.1.202; Max-20x plan, generous cap; new feature UL1 (usage-limit resilience) folded into C1 (`spec-amend-4-usagelimit`) + C2 (kernel item 11) — binding input `docs/reviews/USAGE-LIMIT-RESILIENCE-INTENT-2026-07-08.md`. See `knowledge/lessons.md`.

---

| Campaign | Wave / task | Status | Commit / evidence | Date |
|---|---|---|---|---|
| C1 | 1A-1 `spec-amend-1-state` (B1/M2/M3/M4) | done | c458641 (F17–F20; truth-gate PASS) | 2026-07-08 |
| C1 | 1A-2 `spec-amend-2-schema` (M1/M5/M6/M18/B2 + additive rule) | done | 8b01179 (F21–F25; truth-gate PASS) | 2026-07-08 |
| C1 | 1A-3 `spec-amend-3-testing` (M7/M8/M25 + 12 drift items) | done | ac59100 (F26–F30 + numbered invariants; truth-gate PASS) | 2026-07-08 |
| C1 | 1A-4 `spec-amend-4-usagelimit` (UL1 — new feature) | done | 9cbdf45 (F31=UL1; detection DEFERRED-TO-KERNEL-PROBE; truth-gate PASS) | 2026-07-08 |
| C1 | 1B stub-inject ×7 (watchtower/telegram/providers/portability/phase5/kernels-webui/roadmap) | done | fd85798/c38813f/dbea73a/d2ade0a/fe54334/a8ad2b9/f11e083 (anchor+witness gate PASS; all Invariants-touched present) | 2026-07-08 |
| C1 | 1C review split (`c1-review-spec-core` ∥ `c1-review-spec-stubs`) | done | e2e5ca5 (3 major, UL1 clean) / 93fe929 (3 MED/3 LOW) | 2026-07-08 |
| C1 | 1A-5 `spec-amend-5-subagents` (UL2 — new feature) | done | 8ff424a (F32; default-on, doc-only, no C2 code owed; truth-gate PASS) | 2026-07-08 |
| C1 | 1D fixes (FIX-1..7) | done | 06dedb7/117d1d3/6a75f5b/a73a114/5860b92 (all 7 landed + truth-gate PASS) | 2026-07-08 |
| C1 | 1D re-review `c1-review-spec-2` (loop 1 of ≤3) | done | fc5666e (C1 ready-to-close; 3 LOW → fixed 5708e59/198cfe3/85e1c41) | 2026-07-08 |
| C1 | 1E verify checkpoint + `c1-knowledge` ∥ `c1-playbook` | done | 782f306 (postmortem, anti-ritual PASS) / 0d8699b (campaign-template + project file) | 2026-07-08 |
| C1 | **✅ CAMPAIGN 1 CLOSED** — SPEC v2.1 (F17–F32, numbered invariants, UL1+UL2); all 30 findings homed; ~$62 spend | done | doc-only, no merge gate; awaiting UL1/UL2 ratification | 2026-07-08 |
| C2 | 2A `harness-live` ∥ `harden-hooks` | done | dfa6050 (hooks, 50 pytest, PostCompact verified real) ∥ bff99cb (harness, 11 tests, 6-log corpus, 409 suite) | 2026-07-08 |
| C2 | 2A-close gate (FLEET_LIVE=1 hook-source=worktree) | done | PASS 11/11 manager-run (111s live haiku); changed hooks' first live exec pre-merge | 2026-07-08 |
| C2 | 2B chain `harden-fleet-a`→`-b`→`-c`→`-d`→`-e` (UL1 item 11 = new 5th link) | done | -a 6a44c53(426) · -b f8c9513(438) · -c c3b42f7(453) · -d ca495f0(471, demo both halves) · -e 784a73f(496); all truth-gate PASS | 2026-07-08 |
| C2 | 2C reviews (`c2-review-code` ∥ `c2-review-adversarial`) | done | 37fff85 (11/11 conformant, 1 MED) / 066d618 (2 breaks: HIGH double-launch, MED false-park) | 2026-07-08 |
| C2 | 2D fix wave 1 (`harden-fleet-e`, all 5 fixes) | done | 614ec3a (506 pytest; FIX-1/FIX-2 regression-pinned; 2 empty turns from transient API 529) | 2026-07-08 |
| C2 | 2E merge gate (pre-merge pytest → merge → live tier → doctor → hook-smoke; revert-on-red) + `c2-knowledge` | in-progress | pre-merge checks running | 2026-07-08 |
| C2 | **>>> STOP: hand to Altai for SOAK GATE 1 <<<** | pending | — | — |
| C3 | Phase-1 close (`p1-docs-sync` + external campaign + workload queue + SOAK GATE 1) | pending | GATED: readiness boundary | — |
| C4 | Phase 1.5 portability (spec→build→ci→posix-smoke→SOAK 1.5) | pending | GATED | — |
| C5 | Phase 2 watchtower (spec→chain→accept-tests→SOAK 2) | pending | GATED | — |
| C5b | Phase 2.5 providers (spec always; build demand-gated) | pending | GATED | — |
| C6 | Phase 3 telegram (spec→2 reviews→chain→tg-live→SOAK 3) | pending | GATED | — |
| C7 | Phase 4 web UI read-only (demand-gated build) | pending | GATED | — |
| C8 | Phase 5 intelligence flag-sized (demand-gated build) | pending | GATED | — |
| P6 | Reach backlog (demand-driven, per-item stub+gate) | pending | GATED | — |
