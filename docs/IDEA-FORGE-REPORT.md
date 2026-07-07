# Idea Forge Report

Date: 2026-07-07
Pipeline: idea forge → red-team → 4-judge panel (greybeard-cynic, shipit-pragmatist, product-visionary, ops-auditor), approval threshold avg ≥ 6.5
Input: 10 candidate ideas. Survivors: **0**. Killed: **10**.

---

## 1. Executive summary

The forge produced zero judge-approved ideas out of ten candidates. Scores ranged 2.0–3.0 average against a 6.5 bar — not a near-miss round; every idea failed by a wide margin, and the failure modes were consistent enough to be diagnostic:

1. **Premature framework-building.** The highest-effort ideas (Unified Policy Engine, Spawn Router, Cost-Routed Spawn Topology) pre-abstracted across 3–5 unbuilt phases, directly violating the project's own "steal shamelessly, stay small" principle. Judges repeatedly found the claimed unification cosmetic (action sets that partition cleanly by call site).
2. **Fighting the architecture instead of exploiting it.** Several ideas contradicted load-bearing invariants: the daemonless detached-launch model (no waiter → no exit-code capture), the deliberate exit-0 swallow in hooks, the single-file atomic mailbox, journal-injection-at-respawn (which forecloses the "amnesia" problem entirely), and the sessions-not-processes model (a mailbox DLQ would turn normal inter-turn delivery into data loss).
3. **Un-enforceable guarantees sold as hard floors.** Guard hooks and detectors that structurally cannot see their own motivating case (opaque SQL, MCP bypass, same-turn edit races, registration typos) were scored as worse than nothing — leaky safety a solo operator would trust.
4. **Poisoning scarce channels.** Two ideas would spend the credibility of the exit-2 Stop-hook block channel — the single most valuable feedback mechanism in the system — on false alarms.

**However, the round was not a total loss.** Judges explicitly flagged small salvageable kernels inside six of the ten corpses (§4). These are afternoon-sized tasks, not features, and should be folded into existing phase specs rather than re-proposed as ideas.

**Recommendation for the next forge round:** constrain ideation to (a) Phase 1/1.5 hardening kernels listed in §4, and (b) ideas that exploit the actual moat — durable sessions + the git-tracked knowledge loop — rather than generic git/cost/safety plumbing. Require each idea to name the architectural invariants it touches (daemonless launch, exit-0 hooks, atomic mailbox, journal injection, cwd-scoped resume) and state why it does not violate them.

---

## 2. Ranked survivor table

| Rank | Idea | Score | Phase | Effort |
|------|------|-------|-------|--------|
| — | *(no survivors — all 10 candidates scored below the 6.5 bar)* | — | — | — |

Highest-scoring corpses, for calibration only (none approved):

| Idea | Avg score | Best judge score |
|------|-----------|------------------|
| Cross-Session Collision & Pre-Merge Conflict Radar | 3.0 | 4 (greybeard-cynic) |
| Knowledge-Aware Context Assembly at Spawn/Respawn | 3.0 | 4 (product-visionary) |
| Forced typed journal checkpoints (Pre/PostCompact) | 3.0 | 3 |
| Fail-loud nervous system (hooks + mailbox dead-letters) | 3.0 | 3 |
| Spawn Router: reserve fleet workers for fleet's moat | 3.0 | 3 |
| Unified Policy Engine w/ Ack/Suppress Escalation | 2.8 | 3 |
| Pre-Execution Guard Hooks (scope + spend ceiling) | 2.8 | 3 |
| Liveness truth & crash context | 2.8 | 3 |
| Subagent Spend Ledger → Cost-Routed Spawn Topology | 2.3 | 3 |
| Amnesia Check (verify respawn read its journal) | 2.0 | 2 |

---

## 3. Mini-specs for top ideas

None. No idea cleared the approval threshold, so no mini-specs are issued this round. Do **not** spec any of the ten candidates as pitched — the graveyard entries (§5) record the cause of death for each. The only actionable output is the salvage list in §4.

---

## 4. Roadmap-integration recommendations (salvaged kernels)

The judges did not approve any *idea*, but they repeatedly isolated small, grounded kernels worth folding into existing phase specs as line items — not as standalone specs, not as re-runs through the forge.

| Salvaged kernel | From (dead idea) | Fold into | Size |
|-----------------|------------------|-----------|------|
| Log swallowed hook exceptions to an append-only file; surface a count in `fleet status` | Fail-loud nervous system | Phase 1 (hooks/doctor) | ~5 lines |
| Static lint of settings.json hook registrations (event-name typos, schema drift) in `fleet doctor` | Fail-loud nervous system (judges' proposed replacement for the synthetic-event doctor) | Phase 1 (doctor) | small |
| `fleet conflicts` — one-shot pre-merge `git merge-tree` sweep across worker branches, gated on git ≥ 2.38, advisory output only | Collision & Conflict Radar | Phase 2 spec stub (or a bin/ utility any time) | ~50 lines, afternoon |
| Per-worker cumulative **token** ceiling checked in the Stop hook (no $-conversion, no price table) | Pre-Execution Guard Hooks; Spend Ledger | Phase 5 spec stub (DoD/Stop-hook section) — or earlier as a one-liner | tiny |
| Fail-**silent** PostCompact mechanical landmark appended to journal (turn count, token count, timestamp) | Forced typed journal checkpoints | Phase 1 (journals) | ~10 lines |
| "Turn ended abnormally" journal note + stat-the-cwd-exists preflight before spawn/resume | Liveness truth & crash context | Phase 1/1.5 (platform adapter, respawn path) | small bugfix |
| Mute-until-T flag + single timer for watchtower notifications (the only defensible piece of the ack ladder) | Unified Policy Engine | Phase 2 spec stub (notifier rules) | small |
| One-line spawn-time echo of `CLAUDE_CODE_SUBAGENT_MODEL` / effective model config | Subagent Spend Ledger | Phase 1 (spawn output) | one line |
| "Collapse subsystems into flags" as a *review discipline*: re-vet each Phase 2/3/5 subsystem for a flag-sized alternative at spec time, individually | Spawn Router | Process note in ROADMAP.md | doc-only |

Explicitly **not** salvaged (judges rejected even the kernel): amnesia/lexical-overlap checks of any kind; mailbox dead-letter queues; PreToolUse scope guards over Bash/SQL; live cross-worktree edit detectors; orphan auto-adoption; auto-injected cross-project knowledge retrieval (revisit only after first-party cross-project memory ships and only with a measurement plan).

---

## 5. Graveyard appendix

One line per corpse. Future speccing sessions: check here before proposing anything adjacent.

1. **Unified Policy Engine with Ack/Suppress Escalation** (2.8) — cosmetic unification: fast-path (block) and slow-path (notify/respawn) action sets partition cleanly by call site; unsolved multi-writer CAS; DoD gate defeated by native 8-block cap; PagerDuty machinery for one operator.
2. **Cross-Session Collision & Pre-Merge Conflict Radar** (3.0) — worktree isolation already prevents the headline lost-write; live detector structurally blind to the same-turn race it exists for while spamming lockfile false alarms; merge-tree half is version-fragile O(n²) text-scraping (kernel salvaged as `fleet conflicts`).
3. **Pre-Execution Guard Hooks: Blast-Radius Scope + Spend Ceiling** (2.8) — security theater: PreToolUse cannot see opaque SQL, leaky Bash, or MCP calls; duplicates native settings.json permissions; $-conversion is a price-table maintenance trap (token-ceiling kernel salvaged to Stop hook).
4. **Subagent Spend Ledger → Cost-Routed Spawn Topology** (2.3) — flagship "silent override" detection self-refuting (fleet sets the env var itself); subsumed by native /cost + ccusage; routing payoff is speculative Phase-5 re-derivation of a known heuristic behind an unbounded cold start.
5. **Knowledge-Aware Context Assembly at Spawn/Respawn** (3.0) — right moat, wrong build: grep-isn't-ranking, silently-rotting tag schema as load-bearing element, stale cross-project lore injected ahead of grounded journal replay is a fleet-wide prompt-poisoning vector, duplicates CLAUDE.md/MEMORY.md and sits in first-party's path.
6. **Forced typed journal checkpoints (PreCompact/PostCompact)** (3.0) — a model-free stdlib command hook provably cannot emit the promised semantic handoff schema; misses crash/OOM/kill modes respawn actually needs; fail-loud PreCompact can wedge compaction; duplicates native SessionStart(source=compact) (mechanical PostCompact landmark salvaged).
7. **Amnesia Check: verify a respawn actually read its journal** (2.0) — solves a foreclosed problem (respawn injects the journal into the prompt); lexical-overlap metric wrong in both directions; burns exit-2 channel credibility on the respawn's first turn, exactly when steering matters most.
8. **Fail-loud nervous system (hooks + mailbox dead-letters)** (3.0) — reraise violates the deliberate exit-0 hook invariant; DLQ mistakes normal inter-turn process absence for termination and destroys pending delivery; synthetic-event doctor false-greens on its own motivating typo case (exception-log + status-count kernel salvaged; static lint beats the smoke test).
9. **Liveness truth & crash context** (2.8) — phantom-liveness reconciliation already shipped in cmd_status; exit-code capture infeasible in daemonless detached-launch (nobody wait()s the turn; exit-2 collides with veto); orphan auto-adoption contradicts doctor's deliberate NOTE-only stance; branch guard mis-models the cwd-scoped (not branch-scoped) resume invariant.
10. **Spawn Router: reserve fleet workers for fleet's actual moat** (3.0) — routes the common case to a competitor, starving the knowledge-loop moat; couples spawn to brittle --help/version sniffing of undocumented internals; demotes the watchtower to a foreground flag, dismantling the crash-durable unattended property it just named as the moat; smuggles three unvetted refactors under one verdict (the "flag not subsystem" discipline salvaged as a review practice).
