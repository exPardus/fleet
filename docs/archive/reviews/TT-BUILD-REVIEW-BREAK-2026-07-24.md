# TT-BUILD-REVIEW — BREAK-LENS — 2026-07-24

**Reviewer:** fleet worker `tt-rb` (adversarial break-lens), worktree `C:\proga\fleet-tt-rb`, branch `tt/review-break`.
**Scope:** `31a21f8..49e2b89` (9 commits) + diff + ratified `docs/specs/three-tier-command.md`.
**Authority:** full repro in this worktree only. No `git push` performed.

## Baseline (reproduced, not inherited)

| Claim | Result |
|---|---|
| suite `py -3.13` | **1888 passed, 8 skipped** ✓ |
| suite `py -3.10` (floor) | **1888 passed, 8 skipped** ✓ |
| `verify_receipts --self-test --strict three-tier-command.md` | **55/55 reproduce, self-test PASSED, 0 warn** ✓ |
| new slice test files (6) | 92 passed ✓ |

Suite claim **1888/8 both floors, receipts 55/55** — CONFIRMED.

## Test-theater probe (trap 8) — mutation testing, all caught

Injected 5 faults into the built predicates; each turned its guarding test(s) RED, then reverted (tree clean):

| Mutation | Guard test result |
|---|---|
| M1 ceiling boundary `< H` → `<= H` (200k must still refuse) | 1 failed ✓ |
| M2 occupancy-None `hand_off True` → `False` (fail-toward-band) | 2 failed ✓ |
| M3 `_SUPERVISOR_SHAPED_WORKER_RE` widened→successor-only | 4 failed ✓ |
| M4 remove interface `FLEET_WORKER` structural exemption in ceiling | 1 failed ✓ |
| M5 archive holder-alone protection dropped | 5 failed ✓ |

No un-red injections. Fault-injection tests are load-bearing.

---

# Per-trap adjudication

### Trap 1 — Tier resolver (98f6418) — CLEAN (one guard-gap MINOR)
- Malformed / missing / partial GOALS block → `read_tier_policy` merges found keys over documented defaults; `read_text` OSError caught → pure defaults; empty value keeps default (never empty list). Never crashes a verb. `test_malformed_block_falls_back_to_defaults_never_raises` pins it.
- Worker never resolves to interface tier: `worker` → `worker_tiers[0]` (default `second`), `interface` → `"top"`; disjoint by default.
- §3.2 invariant at **HEAD**: `grep -c "claude-opus\|claude-sonnet\|claude-haiku\|claude-fable" bin/fleet.py` → **0**; provider-env grep (`CLAUDE_CONFIG_DIR\|ANTHROPIC_\|--provider`) → **0**. Bare aliases `opus`/`sonnet` appear only in `proposed_goals_tier_block` example text — tier aliases, not model ids (§3.2). Invariant holds.
- **CLEAN line:** no model-id literal, no provider-env read surface, no crash path.
- **See MINOR-3:** the §3.2 receipt is pinned `# at 235421e` (pre-slice) — it verifies the *past* tree, not the slice's new resolver. The invariant is currently satisfied but **unpinned at the built commit**.
- Observation (not a defect): `resolve_model_for_role` + `read_tier_policy` are built & tested but have **no caller** — not wired into any dispatch `--model` default. Consistent with the spec's `[UNBUILT]` machine-read auto-select (operator types the alias by hand). A present-but-unwired building block; flagged so no future reader assumes auto-select is live.

### Trap 2 — Band measurement (09cc2f6) — CLEAN
- `stop_outcome.py::_transcript_result` now returns and records all three summands (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`); `_transcript_occupancy` sums only `int` summands, newest-wins to the tail.
- **Which way each failure fails:** transcript missing/torn/no-usage → occupancy `None` → `supervisor_band_verdict` → `assume-near-band` (`hand_off True`). Never "below-band" on missing data. So *false under-band → riding to compaction* is structurally prevented; the only residual is a mild *false in/over-band → premature (safe) handoff*, which is the specified direction (§11.2). CLEAN.
- Never-ran-stop-hook / corrupt-cache paths: all reduce to `None` → fail toward band. Negative/absent int fields: absent → skipped; a (non-real) negative int would undercount, but usage tokens are never negative in substrate data — not attacker-reachable. CLEAN.

### Trap 3 — 200k ceiling (0cb0cd0) — CLEAN
- Boundary: `_ceiling_refuses_dispatch` allows iff `occupancy is not None and occupancy < BAND_HARD_TOKENS`. 199k → allow, 200k → refuse, 201k → refuse. `< H` off-by-one correct (spec "at and above H"). M1 mutation confirms the test pins it.
- Binds **only** the claim-holder: structural interface exemption first (`FLEET_WORKER` absent → `None`), then non-holder (`_caller_holds_supervisor_claim is False → None`), then holder/indeterminate → apply (ND4b fail-toward-band). A non-holder session and the ordinary manager (no `FLEET_WORKER`) are never refused. Workers don't dispatch → nothing to refuse.
- Holder-at-ceiling can still hand off: `_ceiling_refuses_dispatch` is called ONLY at `cmd_spawn:3186` and `_cmd_send_native:4273`. `sup-handoff-begin/-complete/-abort` hand-roll their own argv and never touch these paths → **exempt** as required. Read-only reconciliation (`status`/`result`/`peek`/`wait`) issues no spawn/send → allowed. CLEAN.

### Trap 4 — Archive/husk exemption (5a8860b) — CLEAN (documented divergence is CORRECT)
- Builder keyed the predicate on **holder ALONE** (`_record_is_supervisor_claim_holder`: `holder_sid in _record_sids(record)`), diverging from spec-verbatim "holder AND roster-live". Adjudicated with fault-injection both readings:
  - **holder-alone (shipped):** a still-holding but roster-GONE/idle supervisor crossing the 24h TTL **stays protected** — exactly the §7.2 disaster the exemption exists to prevent. B9 (release/seize away → `state==released` or holder sid leaves the record's sid union → `False`) still archives dead husks. Correct on both directions.
  - **conjunct (spec text):** would DROP protection from a roster-gone holder → the running-campaign manager gets archived on the next ≤23h autoclean pass, and during a transient G9 roster blip could delete a *live* supervisor's record. The conjunct is self-contradictory with §7.2's own stated disaster.
- Holder-alone opens **no** hole the conjunct closed: a "stale holder record" is protected only until seizure restamps `INCARNATION.session_id` off it (≤ `SUPERVISOR_CLAIM_STALE_SECONDS`), after which it archives — matching the freeze doctrine. Divergence is oracle-confirmed, disclosed in the commit body, and defensible. CLEAN. (Spec §7.2 prose should be corrected to holder-alone; noted for doc-sync, not a code defect.)
- Indeterminate identity (`None`) fails toward protection but only for `SUPERVISOR_BODY_NAME`/supervisor-shaped names (5397), so a briefly-unreadable INCARNATION cannot freeze archiving of ordinary workers. CLEAN.

### Trap 5 — Send-provenance + divergence (b785660) — CLEAN (residual is priced, not new)
- `caller_sid = current_caller_session()` rides all three `mail_sent` events (4058/4115/4173). `_interface_divergence` counts distinct `caller_sid` for `mail_sent` whose **target** is `supervisor`/supervisor-shaped, within a window; ≥2 → warn (detection only, never a refusal).
- **Steer-rotation vs zombie divergence (G2b):** the detector keys on the **caller** (interface) sid and filters targets by **name**, so a supervisor's own sid rotation (fork-steer) does NOT manufacture false divergence — the rotated sid is the *target*, matched by name, not counted. A supervisor's core loop (`send` to workers) targets non-supervisor names → never counted. CLEAN on the false-positive axis.
- Legit interface session-restart (new interface sid) within the window → 1 warning. Acceptable noise; the design is deliberately detection-only.
- **Spoofability = the priced residual, not a new defect:** a forked interface body can set `CLAUDE_CODE_SESSION_ID` to the legit interface sid and collapse to 1 distinct caller (evasion), and the interface holds no claim by construction. This is exactly B7/§13's scoped non-goal (full interface-fork *prevention* is out of v1 scope). CLEAN against the slice's own contract.

### Trap 6 — §10.1 family widening (49e2b89) — CLEAN (extension, not reversal)
- `_SUPERVISOR_SHAPED_WORKER_RE = ^sup\|[^|]+\|[a-z][a-z0-9-]*$` widens the exempt shape from `successor` to the whole `sup|<inc>|<role>` family.
- **NAME_RE shape-lock still red on the whole family:** `NAME_RE = ^[a-z0-9-]+$` forbids `|`. Every family member carries pipes → `validate_name` refuses it on `spawn`/`respawn` (and `_SID_SHAPE_RE`/RESERVED unaffected). Forging a family name via any *ordinary* creation path is impossible. Verified: no spawn path can mint a `|`-bearing name.
- **No existing worker name enters the family:** all existing worker names match `NAME_RE` (no pipes) → outside the family. Widening `successor`→`[a-z][a-z0-9-]*` cannot reclassify any of them.
- **`_require_claim_holder` env-forge:** the worker refusal exempts a `FLEET_WORKER` value that is supervisor-shaped. `FLEET_WORKER` is set by `_worker_env(name)` to the worker's registry name; since spawn can't create a pipe-name, only handoff/(unbuilt)sup-spawn dispatch a supervisor-shaped `FLEET_WORKER`. Env override requires environment control, which already defeats every guard (and the interface exemption). Council E(2) grounding ("unforgeable via `fleet spawn`") is intact — ANY `|`-bearing name satisfies it. CLEAN.
- Near-miss lock still red: `sup||role`, `sup|x|`, ` sup|x|role`, `SUP|x|role`, `sup|x|role|extra`, third-separator — all OUT (unit-tested `test_near_miss_shapes_are_refused` / `test_the_family_is_supervisor_shaped`; M3 mutation confirms).
- Observation: `sup-spawn`/`cmd_sup_spawn` is **not built** (no parser, no fn) — the widened members (`sup|<inc>|boot`, …) are produced by no shipped path yet; only `sup|<inc>|successor` (handoff) is live. Preparatory, spec-consistent. Extension-not-reversal claim HOLDS.

### Trap 7 — Cross-slice interaction (nonce gate ⊕ supervisor) — CLEAN
- **State-file schema collision:** operator-gate routing lives at `state/supervisor-pending-decision.json` (§8); the nonce claim at `supervisor/INCARNATION`. Different files, different dirs, disjoint schemas. No shared keys, no INCARNATION-field overlap (gate-state `ad4caa2` vs nonce INCARNATION). No collision.
- **Doctor checks:** `_doctor_check_pending_decision`, `_doctor_check_supervisor_claim`, `_doctor_check_supervisor_handoff`, `_doctor_check_daemon_wedge` are independent rows. No interaction.
- **Together:** the full suite (nonce-gate + supervisor + gate-routing tests) runs as ONE process and is green on both floors (1888/8). Strongest available evidence the merged nonce gate and this slice coexist. CLEAN.

### Trap 8 — Test-theater sample + flake — CLEAN
- Mutation table above (5/5 caught).
- **Disclosed flake `test_a_valid_proof_still_exits_0`:** present at base `31a21f8` (`git show 31a21f8:tests/test_supervisor.py` → 1 match) and **NOT modified by the slice** (the slice's `test_supervisor.py` diff is confined to `TestWorkerTurnsCannotHoldTheClaim`, lines ~1509–1600; the flake is at :2238, a claim-nonce continuity test). Ran 30× isolated on HEAD → 30 passed. **Adjudication: pre-existing base flake, NOT slice-caused.**

### Trap 9 — New-defect hunt — 3 MINOR (below)

---

# Findings

### MINOR-1 — pending-decision `--answer`/`--clear` are lock-free read-modify-write
`bin/fleet.py:10128` (`--answer`), `bin/fleet.py:10139` (`--clear`)
- **Problem:** `--raise` runs under `fleet_lock()` (10105) but `--answer` does read → mutate → `write_pending_decision` and `--clear` does `unlink`, both **without** the lock. A concurrent `--raise` (lock-held) can be lost, or a just-cleared decision resurrected, by a stale in-flight `--answer`.
- **Repro (constructed):** interface `--answer` reads decision A; supervisor consumes+clears A and (after refusal check passes on empty) `--raise`s decision B under lock; interface's `--answer` write lands last → B is overwritten by answered-A. Supervisor parks on B forever; the file shows answered-A.
- **Reachability:** very low — the surface is human/interface-paced and the supervisor parks while a gate is open, so the interleaving window is sub-second against human action. No path lets the supervisor *self-approve* an unanswered gate (answers are operator-written); worst case is a lost/duplicated routing record.
- **Fix:** wrap the `--answer` read-modify-write and `--clear` in `with fleet_lock():`, matching `--raise`.

### MINOR-2 — `--answer` over an unreadable pending-decision fabricates an answered record
`bin/fleet.py:10128-10135`
- **Problem:** on a corrupt file, `read_pending_decision` returns `{"_unreadable": True, "question": "(…unreadable)"}` (not `None`). `--answer` then sets `rec["answer"]` and writes it back, producing a synthetic `{_unreadable, question:"(…unreadable)", answer:<text>, answered_at, answered_by_sid}`. The original question is gone; the supervisor later consumes an answer bound to a placeholder question.
- **Repro:** write garbage to `state/supervisor-pending-decision.json`; `fleet sup-decision --answer yes` → file now presents as ANSWERED over a lost question.
- **Reachability:** low (requires file corruption), but it converts a *nag-visible corrupt gate* into a *silently-answered* one — the opposite of §8's intent.
- **Fix:** refuse `--answer` (and warn) when `read_pending_decision()` yields `_unreadable`; require `--clear` to reset a corrupt gate.

### MINOR-3 — §3.2 "zero model-id literals" invariant is not pinned at the built commit
`docs/specs/three-tier-command.md:114-118` (receipt `# at 235421e…`)
- **Problem:** the invariant grep is receipted only against the **pre-slice** tree `235421e` (all 53 model-id-relevant pins are `# at 235421e`; the 2 non-235421e pins are `# live:` ratification-status checks, unrelated). The slice adds the first code that names tier aliases (`proposed_goals_tier_block`), yet nothing — receipt or test — asserts `grep -c "claude-*" bin/fleet.py == 0` at `49e2b89`. `test_default_tier_model_is_empty_no_hardcoded_ids` checks the default map is empty, not the source-literal invariant. Current state is compliant (HEAD grep → 0), so this is a **guard gap**, not a live defect.
- **Fix:** add a `# live:` receipt (or a `TestNoHardcodedModelId` grepping `bin/fleet.py`) so the invariant is enforced against drift, matching the slice's own receipt discipline.

---

# MERGE VERDICT: sound

The slice is correctly built against the ratified spec, heavily and honestly tested (no test-theater; 5/5 mutations caught), and every named trap is clean under fault injection. The archive holder-alone divergence (Trap 4) is the *safer* reading and is oracle-confirmed/disclosed. `resolve_model_for_role` (unwired) and `sup-spawn` (unbuilt) are spec-consistent `[UNBUILT]` gaps, not regressions. The three MINOR findings are hardening items (lock discipline on a human-paced routing file, corrupt-file handling, an unpinned invariant) — none blocks merge, none is a correctness or security hole in a reachable path.

0 CRITICAL · 0 MAJOR · 3 MINOR.
