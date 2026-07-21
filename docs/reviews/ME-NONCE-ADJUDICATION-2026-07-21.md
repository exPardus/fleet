# Claim-nonce spec — manager adjudication of the dual-lens design gate

**Date:** 2026-07-21. **Adjudicator:** supervising manager (`inc-20260721T150630Z-2c07`).
**Under review:** `docs/specs/claim-nonce.md` @ `ccbbc02` (branch `me/nonce`, `Status: drafting`, 1258 lines, 31 grep receipts).
**Inputs, both independent:**
- `ME-NONCE-DESIGN-REVIEW-BREAK-2026-07-21.md` (`me-nonce-break`, 18 receipts) — **`VERDICT: restructure`**, 5 CRITICAL / 6 MAJOR / 4 MINOR / 1 nit + 1 DESIGN-QUESTION + 1 SPURIOUS.
- `ME-NONCE-DESIGN-REVIEW-SPEC-2026-07-21.md` (`me-nonce-spec`, all 31 receipts re-run) — **`VERDICT: fix-list(S1–S24)`**, factual base **reliable**, completeness short.

**This adjudication merges and sequences. It re-interprets no finding; the two verdict files are the authority for details. It ratifies nothing** — `docs/specs/claim-nonce.md` stays `drafting`, and no build may start from it. Promotion is the operator's alone.

## Ruling

**RESTRUCTURE — upheld.** The tier model and the *detection* mechanism are not refuted; the *authorization* framing is.

**Root cause, from the break lens, quoted:**

> the design uses a **bearer secret as an authorization credential** on a substrate with **no privilege separation**, and then, because a bearer secret on such a substrate is inevitably lost or unavailable, adds **three unauthenticated recovery paths** — each keyed on a value a public view prints. The recovery paths are not a lapse; they are forced by the substrate. Any spec that puts authorization on a bearer secret here will re-derive them.

The two lenses do not conflict; they cut at different depths. The spec-lens found the document's *facts* sound — all 31 receipts reproduce byte-for-byte, all three production incidents are verbatim at their cited sources, nothing confabulated, `[UNBUILT]` discipline clean, `Status:` untouched. The break-lens found the *design those facts support* unsound. A spec can be impeccably receipted and still specify the wrong thing; that is exactly what happened, and it is why the gate runs two lenses.

**Notably, the spec falsified its own decisions and did not notice.** §4.5 states honestly that two bodies of one lineage are byte-identical and mutual exclusion is therefore undecidable — which is the premise that voids §5.4 and §5.6. The break lens: *"The spec argued itself out of its own decisions and did not notice; that is a better failure mode than not arguing."* Concur.

## What survives, and should be built roughly as drafted

Recorded first, because a restructure verdict is not a rejection:

1. **The detection property.** §4.1's `nonce_hash` / `nonce_seq` / `lineage_id`, single-use rotation, §4.6's loud refusal + rejection record + doctor surface. Both lenses agree this converts incident 1 (the 2026-07-16 dual-supervisor fork: ~100 minutes, seven phantom dispatches, discovered by manual forensics) into **one refused command**. It needs no gate to be worth building.
2. **§3, the receipt section** — the break lens calls it "the best receipt section in this repo"; the spec lens re-ran all 31 byte-for-byte. Its five additions beyond the adjudication's starting list are real, and `sup-status --json` dumping the claim dict verbatim through a lock-free view is a genuine find a naive build would have shipped straight through.
3. **§5.3's `lineage_id` answer** to `spawned_by` continuity — correct, ships roughly as drafted.
4. **All three source corrections the author made to its own briefing** — independently confirmed by *both* lenses: the adjudication's 6-anchor list is incomplete; `_restamp_after_steer` has one call site plus an undocumented inline duplicate at `:3428`; the "stale roster PASSES the epoch check" line is the three-tier adjudication's claim, not `native-substrate.md`'s. (The spec lens marks one of the three "confirmed but overstated" — see its §B.)

## Binding re-draft list (merged, deduped; break-lens C#/M#/S#, spec-lens S#)

**Structural — from the break lens (its §7 is the authority):**

1. **Drop the authorization framing; keep the mechanism as detection** (C1–C4, M4). The nonce proves *"the last body to act was the same body as this one"* — not *"I am authorized"*. Rewrite §4.5's guarantee as **at most one nonce-bearing actor after divergence**, and state plainly that the escape paths are unauthenticated and a refused body will use them.
2. **Delete Rule 0b (`re-issue`)** (C1) — a sid-keyed re-issue is a documented bypass of the whole mechanism. Safe only once (5) lands, because Rule 0b is today what silently repairs a rotate-then-fail. One change, not two.
3. **Run the roster-liveness guard *before* Rule 0** (C2), granting `resume` only when the recorded holder is roster-gone. Restores what adjudication item 1 binds the spec to preserve, and still fully resolves incident 2.
4. **Close the environment channel** (C4): strip `FLEET_SUP_NONCE` / `FLEET_CLAIM_OVERRIDE` in `_worker_env`, or offer no env-var channel at all.
5. **Fix the rotation contract** (M1, M2): rotation must survive a verb that fails after validation, and must not fire the two-body alarm on one body's concurrent tool calls. Then write the concurrency section the spec lacks and the tests §8 lacks.
6. **`sup-release` keeps its no-`--force` form; `--force --confirm-inc` goes** (C3) until an authorization input exists. Incident 3's real requirement — *an operator-authorized stop must be distinguishable from a daemon restart* — is satisfiable without an unauthenticated verb; §5.5's diagnosis is right, its `--force` form is not.
7. **Sections that must exist and do not:** threat model / trust boundary (the missing section that generates C1–C4); nonce lifecycle (delivery, acknowledgment, concurrency, rotate-then-fail); the transcript as the real secret store, including that `--fork-session` duplicates it; secret retention and rejection-log bounds; what a refused body does next; gate disarm / rollback; **what a view may publish**, given every escape is keyed on published values.

**Completeness — from the spec lens (its fix list is the authority):**

8. **§3 is short by five touchpoints**, each of which a builder implementing §3 literally would miss: S1 (§3.2's receipt is quote-sensitive and undercounts the sid equalities 2 → 4), S2 (`_render_successor_task` @7257-7274 hard-codes the successor protocol and is never mentioned), S8 (`state/supervisor-handoff-aborted.json` is a third supervisor store carrying a fifth sid equality inside the stop path), S9 (`_roster_live_sids` @6986-6999 *defines* the guard §5.6 must preserve and is never receipted), S6 (§4.3/§9's "never sees the hash either" is contradicted by §3.8's own receipt, with no build rule to close it).
9. **S4 — §5.2's verb partition contradicts the spec-of-record and is incomplete.** Reconcile against `docs/SPEC.md` before anything else in §5.2 is rewritten.
10. **S5 — §5.2's "Accepted cost" attributes to the three-tier adjudication a position it does not hold.** Correct the citation. (Same class as the author's own third source correction — this document is not exempt from the rule it enforces.)
11. **S3 — `skills/fleet/` is the shipped operator contract** for everything this spec changes; §3.8's "only consumer" sentence is scoped narrower than the sentence it supports.
12. **S10, S11, S12** — exit code 4 has no seam while the published contract says 0/2/3; §8's "all with injected clock/roster/run" is false for T3, T1, T10; `conftest` deletes the env var §4.2's fallback depends on.

## Defects in SHIPPED code surfaced by this gate (filed separately, as the M-D gate did)

- **A worker turn can hold the supervisor claim, and is prevented only by accident.** `_require_claim_holder` has no `FLEET_WORKER` refusal (break-lens §7 item 7). Independent of this spec's fate.
- **`supervisor/INCARNATION.tmp` is not gitignored** (S7) — §3.1's `.gitignore` receipt does not cover the file the writer actually creates. Tiny, real, one line.
- **Published exit-code contract mismatch** (S10) — the docs say 0/2/3; the code has a 4 with no seam.
- Stale docs outside any branch, manager-owned at close: `docs/specs/autoclean.md:48` (path-only ownership, now false) and `docs/NEXT-SESSION.md:23` (lists both M-D-gate defects as still outstanding).

## Sequencing

1. **Re-draft wave to `me-nonce`** — items 1–12 above, `Status:` stays `drafting`, author still may not promote. Re-put items the break lens says are the operator's as **open questions with a recommendation**, never as decisions.
2. **One fresh dual-lens gate on the re-draft**, then the operator's ratification decision. `ESCALATE beats a third fix wave` binds here as everywhere: if the re-draft's gate returns `restructure` again, the slice escalates to the operator with a named restructuring rather than a third wave.
3. **The detection-only slice may be worth shipping ahead of any gate decision** — both lenses independently say it stands alone. **Operator's call, not the manager's.**
4. **No build from this spec until the operator ratifies it.** Unchanged.

## Open for the operator (surfaced, deliberately not decided)

1. **Re-put of three-tier adjudication item 2 — what does the claim gate?** The break lens' position: a gate needs an authorization input *not derivable from any view and not an environment variable*, and **on this box, today, there is not one**. So the honest options are (a) detection-only, no gate; (b) a gate that is knowingly bypassable; (c) build an authorization input first (new scope, new slice). The draft chose "claim-gate the mutating verbs"; that choice is what the restructure unwinds.
2. **Does the detection-only slice ship on its own, ahead of the rest?**
3. **`sup-release --force`** — removed by item 6 until an authorization input exists. If you want the escape hatch anyway, that is a deliberate, documented acceptance of an unauthenticated seizure verb.
4. **Ratification of `docs/specs/native-substrate.md`'s `[PENDING OPERATOR RATIFICATION]` rows** (2.1.212 set, plus the new 2.1.216 daemon-wedge row) remains open from M-D and is untouched by this gate.
