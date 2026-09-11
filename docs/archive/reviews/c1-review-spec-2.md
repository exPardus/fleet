# c1-review-spec-2 — Wave-1D re-review (fixes + UL2 + corpus)

**Reviewer:** `c1-review-spec-2` (read-only adversarial). **Date:** 2026-07-08.
**Scope:** (A) verify FIX-1..7 stuck + no new contradiction; (B) fresh adversarial review of UL2 (F32); (C) corpus consistency spot-check.
**Ground-truth greps run against `bin/fleet.py`** (anchors only, not whole-file): `recompute_status`/`_launch_claim_expired` @599–682, `build_turn_argv` @933, `_doctor_check_claude_agents` @3101–3129; plus `worker-settings.template.json`.

---

## 1. Verdict

**C1 is READY TO CLOSE.** All seven adjudicated fixes landed correctly and match shipped code where they cite it. UL2/F32 is sound on every attacked lens (doctor non-false-positive VERIFIED against code, invariant-7 airtight, security note honest, no invented flag, no invariant/§6/UL1 contradiction). No majors, no surviving 1C hazard.

**3 NEW findings, all LOW, none blocking** — cosmetic/cross-doc-hygiene residue of the fix wave (the expected "~1 new issue per wave," here split into three minor ones). C1 may close with these tracked as polish for the owning stub/spec builders; none re-creates the CM1/CM2/CM3 hazard class in a load-bearing spot.

**New findings by severity:** MAJOR 0 · MED 0 · LOW 3.

---

## 2. Findings (new only)

### L1 — SPEC.md header (line 3) never extended to include F32/UL2 `[owner: spec-amend header writer]`
The status line was carefully rewritten by FIX-3 to enumerate the amendment scope honestly, but the UL2 commit (`8ff424a`) added F32 without touching it. It still ends:
> "...plus the Altai-requested usage-limit resilience feature UL1 (appendix F31). ... §12 splits its regressions into "passes today" vs "pins unbuilt fixes" accordingly."
The enumeration stops at F31/UL1; F32/UL2 (worker-subagents, a NEW capability) is absent from the one line that claims to describe the v2.1 amendment scope. **Why it matters:** the header is the load-bearing honest-scope statement the whole fix wave cared about; a reader trusting it under-counts the corpus by one appendix entry + one capability. **Fix:** append "+ UL2 worker-subagents sanctioned (appendix F32, DOCUMENTATION-ONLY)" to line 3. Not a contradiction — an omission.

### L2 — portability carry block cites the alive-unknown tier as amended-current §4, missing the `[UNBUILT]` tag FIX-2 added `[owner: stub-inject-portability]`
FIX-4 correctly fixed the finding-number, but the same carry block still asserts the three-way-probe behavior as shipped §4:
> "Per SPEC §4 (as amended by the v2.1 state-machine amendment, F15/B1 — spec-amend-1-state), a query that returns "exists but unreadable" ... resolves to the alive-unknown tier — never demoted to `dead` ..."
After FIX-2, SPEC.md §4 + F20 label exactly this alive-unknown tier `[UNBUILT — owned by C2 hardening kernel item 9]`. So SPEC.md now says "unbuilt end-state," while `portability.md` presents it as an amendment already in §4. **Why it matters:** this is the same descriptive-vs-prescriptive class CM2 flagged, surviving in a sibling doc the FIX-2 scope didn't reach — a portability-OQ2 builder would read the alive-unknown tier as current §4 behavior. **Low, not med:** portability is a future Phase-6 spec and OQ2 is itself an open question, so the blast radius is a stale cross-ref, not a build-against-vapor trap. **Fix:** mirror SPEC.md's tag — note the alive-unknown tier is the UNBUILT C2 probe end-state, per §4/F20.

### L3 — telegram OQ1 labels `/send /spawn /mute` "non-fixed / open placement" while B5 "fixed baseline" already assigns them `[owner: stub-inject-telegram]`
FIX-7/SL3 met its core ask (inventory stated ONCE in B5), but B5 and OQ1 now use colliding words for the same three commands. B5:
> "**Full v1 command inventory + confirm split (the fixed baseline ...)** ... **confirm-with-nonce** ...: `/send /spawn /respawn /kill`. ... **no-confirm** ...: `/status /peek /result /mute /manager`."
OQ1:
> "...open: where `/send`, `/spawn`, `/mute` land ... the still-open confirm *placement* for the **non-fixed** commands `/send`, `/spawn`, `/mute` ..."
So `/send` and `/spawn` sit in B5's "fixed baseline" confirm column yet are called "non-fixed / still-open" by OQ1; `/mute` likewise. **Why it matters:** partially re-creates the SL3 divergence FIX-7 was meant to close — the inventory is single-sourced now, but the fixed/non-fixed terminology overlaps on three entries, so a reader can't tell if their placement is decided or open. Defensible intent (B5 = single-sourced *proposal*; OQ1 = which entries C6 may still revise) but the wording contradicts itself. **Fix:** reword OQ1 to "the confirm-placement of `/send`/`/spawn`/`/mute` is the part C6 security sign-off may still revise relative to the B5 baseline" — drop "non-fixed," which fights B5's "fixed."

---

## 3. Fixes-verified-stuck checklist

| Fix | Landed? | Matches code / no new contradiction |
|---|---|---|
| **FIX-1** (CM1 pre-claim fresh-vs-stale; §4 bullet, F17(d), §11 reboot, §12) | ✅ | **Verified against code.** `recompute_status` @676–678: `working`+`pid is None` → `_launch_claim_expired(last_activity_iso)` → `dead` else `working`; const `LAUNCH_CLAIM_MAX_AGE_SECONDS = 600.0` @599; docstring @648–652 confirms stale→dead recoverable via kill/attach --force/respawn/clean. Spec text "matching shipped `recompute_status` (@677)" is exact. No over-correction. |
| **FIX-2** (CM2 three-way probe UNBUILT) | ✅ | `[UNBUILT — owned by C2 hardening kernel item 9]` tag present on §4 probe heading, §5 doctor elevation-mismatch clause, §11 crash-mid-turn row, F20 heading, and §12 `probe_three_way` (bucket b). Shipped probe grep confirms two-way (`recompute_status` @680–682: `pid_alive` → working, else idle/dead) — no alive-unknown tier in code. Consistent. |
| **FIX-3** (CM3 descriptive/prescriptive framing) | ✅ | Header rewritten (both branches named; UNBUILT tags listed). §12 split into **(a) passes today** / **(b) pins unbuilt fixes**, each (b) item names its kernel. F22/F23/F24 tagged. **Highest-value bucketing check PASSED:** builder placed corrected `preclaim_fresh_survives_stale_demotes` in bucket **(a)**, deviating from FIX-3-line-25 (which said bucket b) — and the deviation is CORRECT: FIX-1 + code @676–678 prove BOTH branches ship, so it passes today and cannot "fail-until-kernel." No mis-bucketed regression; no unbuilt item claimed as passing. Builder flagged the deviation inline and invited override — I confirm bucket (a). |
| **FIX-4** (portability F20→F15 cite) | ✅ | `117d1d3`: "(as amended by F20)" → "(as amended by the v2.1 state-machine amendment, F15/B1 — spec-amend-1-state)", verbatim per fix-list. Content correct. **Residual L2** (UNBUILT label not propagated) is a NEW cross-doc drift, not a failed fix. |
| **FIX-5** (watchtower F8 respawn-cap deferred) | ✅ | `6a75f5b`: respawn action path + loop cap scoped to "DEFERRED with F20 ... applies when auto-respawn is re-vetted (post-Phase-3)"; v1 keeps read + send/notify + lock discipline. Reader-discipline NOT orphaned (send-path pre-claim/lock rules retained). |
| **FIX-6** (webui CSRF done-criterion) | ✅ | `a73a114`: "CSRF protection verified" → "Host-header/same-origin rejection + mutating-POST→405 verified; CSRF-token machinery specced (not built until write forms earned)". Matches fix-list; consistent with read-only v1. |
| **FIX-7** (telegram OQ1/B5/`/manager`) | ✅ | `5860b92`: nine-command inventory stated ONCE in B5 (no-confirm 5 + confirm 4 = 9); `/manager` added with transitive-privilege-confirm disposition; OQ1 references baseline. Core SL1/SL2/SL3 asks met. **Residual L3** (fixed/non-fixed wording collision) is the only surviving nit. |

## 4. UL2 verdict — SOUND, ship

| Attack lens | Result |
|---|---|
| **1. Doctor non-false-positive** | **VERIFIED against code.** `_doctor_check_claude_agents` @3101 consumes ONLY `claude agents --json` (`run([exe,"agents","--json"])` @3110) and correlates its `session_id`/`id` @3121–3126 against registered worker sids. Ephemeral in-turn Task subagents are not sessions → never in that inventory → never flagged. Anchor "@3101" is exact. The `--bg`-background vs Task-tool distinction is the honest basis; the "confirmed against help text" step is an inference, but OQ2's contingency clause ("if a future CLI DID surface them ... correlate to parent sid") hedges it honestly — not hand-waved. |
| **2. Invariant 7 airtight** | Yes. A Task subagent runs in-process within the single main claude turn — never a second `--resume` on the worker's `session_id`; no concurrent resume-breaking transcript write. Residual (a bypass worker's subagent could shell out a competing `claude --resume` via Bash) is identical to the main agent's existing capability and lives inside the OQ4 bypass-trust model — UL2 introduces no NEW invariant-7 break. |
| **3. Security (OQ4)** | Honest and adequate for v1. Discloses bypass inheritance ("subagents run `--dangerously-skip-permissions` too, widening the bypass blast radius") and picks DOCUMENT-not-restrict, consistent with the existing foreign-hooks posture. Nuance (not a finding): OQ4×OQ7 interaction — foreign-repo `.claude/agents/*` types run under inherited bypass — isn't explicitly connected, but it is the same accepted trust surface as foreign hooks, so no under-statement worth blocking. |
| **4. No invented flag** | Correct. Claims default-on/no-flag and grounds it in code: `build_turn_argv` @933 passes no `--disallowedTools`/tool restriction (grep for `disallowedTools`/`allowedTools` in fleet.py = zero hits), and `worker-settings.template.json` is hooks-only (restricts no tools). Both code claims TRUE. The one unverifiable-by-me claim is the literal `claude --help` output (no live process available) — presented as probe evidence, appropriately hedged and consistent with the `agents --json` subcommand the doctor code already calls. |
| **5. No contradiction w/ invariants/§6/UL1** | None. Cost note aligns with F21 (subagent tokens roll into parent `result` cost). "Invariants touched (UL2)" (1/2/6/7 preserved) is internally consistent and non-overlapping with the UL1 invariants section. §6 subagents block + §8 doctrine line + §5 doctor note are mutually consistent. F32 number does not collide (F1–F31 + UL1 distinct). |

## 5. Corpus spot-check (Part C)

- **Appendix numbering:** F17→F32 sequential, no gap/dup/collision (grepped `^\*\*F[0-9]`). "Invariants touched (UL1)" and "(UL2)" are distinct sections. UL2-OQ1..8 and UL1-OQ dispositions don't collide.
- **Header honesty:** the descriptive/prescriptive split is described correctly for F17–F31 — but **omits F32/UL2** (finding **L1**).
- **Moved/renamed sections:** none. All fixes were in-place edits; §12 gained (a)/(b) subsections under an unchanged `## 12`/heading, so no cross-ref to §12 is stale.
- **Cross-doc drift introduced by the wave:** one — portability's alive-unknown paraphrase vs SPEC.md's new UNBUILT tag (finding **L2**).

---

## Appendix — no-relitigation compliance
SPEC F1–F16, review-doc §6.1 refuted, IDEA-FORGE §5 graveyard: untouched. No 1C finding already fixed was re-raised (each verified-and-moved-on above). All three new findings are LOW and post-date the fix wave.

**RESULT:** files=docs/reviews/c1-review-spec-2.md tests=n/a-review spec=no-drift(review-only) criteria=FIX-1..7 all stuck (FIX-1 code-verified @676; FIX-3 bucketing correct — preclaim→(a) is right); UL2 verdict=SOUND (doctor claim code-verified @3101, inv-7 airtight, security honest, no invented flag); 3 new findings (LOW×3: header omits F32; portability alive-unknown missing UNBUILT tag; telegram OQ1 fixed/non-fixed wording); C1-ready-to-close=yes
