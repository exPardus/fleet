# TT-BUILD three-tier slice — SPEC-conformance review

**Lens:** conformance (independent of the break lens; no coordination).
**Branch:** `tt/review-spec` @ `49e2b89` — 9 commits over base `31a21f8`.
**Authority:** `docs/specs/three-tier-command.md` (RATIFIED 2026-07-23).
**Method:** anchor+witness grep per claim; receipts + both floors re-run.
**Reviewer:** fleet worker `tt-rs`, 2026-07-24.

**MERGE VERDICT: sound** — 0 Critical / 0 Major / 2 minor. Build conforms to the ratified
spec; receipts 55/55, both floors 1888/8, scope clean. The two minors are documentation
follow-ups (one ratified-spec one-liner, one merge-time SPEC.md fold-in) — neither blocks the
code merge; both filed below.

---

## 1. Appendix-A reconciliation — CONFORMS

Spec Appendix A is a set of no-match `[UNBUILT]` receipts pinned at author commit `235421e5`.
The build slice's status contract lives in `state/journals/tt-build.md` (lines 176-184 + the
successor map). Reconciled row-by-row:

**BUILT — code + tests present (grep receipts):**
| Item | Code (fleet.py unless noted) | Tests |
|---|---|---|
| tier resolver (§3.1/3.3/3.5) | `read_tier_policy`@8606, `resolve_model_for_role`@8626, `_parse_tier_policy_block`@8565 | test_tier_resolver.py |
| band measurement (§11.2) | `_transcript_occupancy`@1792, `supervisor_band_verdict`@1829, `BAND_SOFT/HARD`@1783-84; stop_outcome.py cache fields | test_supervisor_context.py, test_hooks.py |
| reserved name (§10.3) | `SUPERVISOR_BODY_NAME`@731, `RESERVED_NAMES`@732, `validate_name(allow_reserved=)`@756 | test_core.py |
| gate state file (§8) | `sup-decision`/`cmd_sup_decision`@?, `pending_decision_path`@8692, `_doctor_check_pending_decision`@10158 | test_supervisor_decision.py |
| 200k ceiling (§11.3/B4) | `_ceiling_refuses_dispatch`@1966, `_caller_holds_supervisor_claim`@1878, `_record_sids`@1855 | test_supervisor_ceiling.py |
| archive/husk exemption (§7.2/B1/B9) | `_record_is_supervisor_claim_holder`@1935, gate-0 in `_archive_eligible`@5395, `_sweep_husks`@5397 | test_archive_exemption.py |
| send provenance (§5.3/B7) | `caller_sid` on `mail_sent`, `_interface_divergence`@9922, `INTERFACE_DIVERGENCE_WINDOW_SECONDS`@9919 | test_send_provenance.py |
| §10.1 family regex | `_SUPERVISOR_SHAPED_WORKER_RE`@1313, `_is_supervisor_shaped`@1321 | test_supervisor.py |

**DEFERRED — spec text supports the deferral:**
- **beat verb (§5.2/§9.1)** — spec defers the *scheduled* beat to v2, citing operator decision
  2026-07-23 (*"event-driven only in v1; scheduled heartbeat deferred until a campaign
  demonstrably stalls"*, §5/§9.1). Confirmed absent: `grep -c 'add_parser("beat")'` → 0. Deferral
  reading is sound.
- **worker allowlist "never Haiku" (§3.4)** — spec: enforcement at spawn is `[UNBUILT]`, *"until
  built it is doctrine in GOALS.md, not a guard"*. A `haiku` model-id literal would break the §3.2
  no-model-id invariant. Kept as doctrine; resolver exposes `worker_tiers`. The one `haiku`
  occurrence (`bin/fleet.py:8558`) is a comment on the `worker_tiers` default, not a model id
  (`grep -c 'claude-haiku' bin/fleet.py` → 0). Deferral reading is sound.

**NOT-BUILT — successor map names each; nothing in Appendix A silently dropped:**
- **sup-spawn verb (§10.1)** — successor map REMAINING SCOPE #1 (blocked-then-unblocked by the
  49e2b89 regex; verb itself unbuilt). Absent: no `add_parser`/`def cmd_sup_spawn`.
- **§10.4 kill/respawn supervisor tombstone** — successor map REMAINING SCOPE #2. Absent.
  (Note: `cmd_sup_release` @9814 *does* exist, but it is **base/claim-nonce code**, present at
  `31a21f8`, not this slice's work; the §10.4 receipt's `grep …→0` is a valid pinned claim about
  the older `235421e5` tree, not a claim about base.)
- **§3.3 CLAUDE_CONFIG_DIR** — successor map REMAINING SCOPE #3; correctly judged **descriptive /
  covered by `_worker_env`'s parent-env inheritance**, not a literal build item.
  `grep -c 'CLAUDE_CONFIG_DIR\|ANTHROPIC_' bin/fleet.py` → 0 (§3.2/§3.3 boundary intact).

No Appendix-A row is silently dropped.

## 2. §-conformance of the built — CONFORMS

- **§3 resolver.** `read_tier_policy` reads the `<!-- fleet-tier-policy -->` block from
  `supervisor/GOALS.md` over documented defaults (`supervisor_chain [top, second]`,
  `worker_tiers [second, third]`, `tier_model {}`). Chain `[top, second]` is policy, never a code
  constant. **§3.2 receipt reproduced live:** `grep -c "claude-opus\|claude-sonnet\|claude-haiku\|
  claude-fable" bin/fleet.py` → **0**. No model-id literal anywhere.
- **§11 band.** `BAND_SOFT_TOKENS=150_000` / `BAND_HARD_TOKENS=200_000` sourced as named constants
  per spec. **§11.3 interface exemption:** `_ceiling_refuses_dispatch` returns None (allow) when
  the caller is not the supervisor claim-holder; interface is structurally exempt (no `FLEET_WORKER`
  ⇒ never a claim-holder). **Read-only reconciliation carve-out matches §11.3's enumeration by
  construction:** the ceiling is wired to **exactly two** call sites — `spawn`@3186 and `send`@4273
  — so `status`/`wait`/`result`/`peek` and the hand-rolled handoff dispatch are never refused,
  which is precisely §11.3's allowed set. Unreadable occupancy fails **toward** the band (None ⇒
  refuse), per §11.2. The 150k soft band does not refuse (directive only). Faithful.
- **§7.2** archive/husk exemption: first gate in both `_archive_eligible` and `_sweep_husks`
  (protected-set union), keyed on the claim-holder predicate, under any name (closes B1);
  released-away/non-holder husk stays archivable (closes B9). See §3(a) below for the holder-alone
  judgment.
- **§5.3 provenance:** all three `mail_sent` events stamp the caller's sid; `_interface_divergence`
  warns on ≥2 distinct interface sids within the window, surfaced in `sup-status`. Detection only,
  never a refusal — exactly the spec's *"deliberately weaker"* interface-tier analog.
- **§10.1 family regex** widened `^sup\|[^|]+\|successor$` → `^sup\|[^|]+\|[a-z][a-z0-9-]*$`.
  **Citation verified:** the code comment (fleet.py:1300-1312) attributes it to the council E(2)
  grounding — *"the exempt shape must be unforgeable via `fleet spawn`"* — and that grounding is
  recorded in `docs/OVERNIGHT-2026-07-23.md` **G-4** (*"shape is unforgeable (NAME_RE forbids `|`
  in all spawnable names)"*, plus *"spec-defect disclosure filed for the three-tier build slice"*).
  The claim's logic holds: `NAME_RE = ^[a-z0-9-]+$` forbids `|` in every spawnable name, so the
  whole `|`-bearing family is unforgeable, not only the `successor` role. Extension, not reversal —
  the citation's claim is accurate against G-4 and the claim-nonce §13 disclosure.

## 3. Two disclosed judgments

### (a) §7.2 holder-alone vs verbatim "holder AND roster-live" — **ACCEPT**

The ratified spec §7.2 twice specifies the predicate as *"the record is the body that currently
holds the claim **and that body is roster-live**"*. The build (`5a8860b`,
`_record_is_supervisor_claim_holder`) keys on **holder ALONE** — no roster-live conjunct — and
discloses the deviation (build journal + inline comment fleet.py:5383-5394).

**Ruling: ACCEPT the holder-alone reading**, with the spec's own disaster-statement as tiebreaker.
The §7.2 disaster is: *"If the supervisor's registry record goes idle, it crosses the 24h archive
threshold and an autoclean pass … archives/rm's it — deleting the running campaign's manager."* An
idle supervisor is roster-**gone** (transient-daemon idle-exit, 2.1.212). A literal
`holder AND roster-live` conjunct would therefore **fail to protect exactly the idle/roster-gone
claim-holder the disaster describes** — the collision would be live again. Additionally, gate 3 of
`_archive_eligible` already refuses every roster-live record (`return (False, "roster-live")`), so a
roster-live conjunct on gate 0 would make gate 0 a **no-op** against gate 3. B9 (release a dead
husk) is still closed, because the discriminator is *"no longer holds the claim"* (released/seized ⇒
predicate False ⇒ archivable), not roster-liveness. Holder-alone is strictly more correct.

**SPEC TEXT amendment needed (filed, not made — MINOR m1).** The ratified §7.2 body still literally
reads *"and that body is roster-live"* in the predicate statement and *"roster-gone and whose body
no longer holds the claim"* in the B9 direction — now contradicted by the shipped, correct
predicate. A future builder reading the ratified text could re-introduce the broken conjunct. **File
a one-line §7.2 amendment**: drop the `roster-live` conjunct from the predicate and re-state B9's
discriminator as *claim-ownership* (not roster-liveness), noting gate 3 already carries the
roster-live guard. This is NOT in the current §12 doc-sync list, so it is a new filing. Does not
block the code merge (code is correct); it is a ratified-doc precision fix.

### (b) §10.2 `FLEET_WORKER` =1→NAME correction — **CONFORMS**

The spec edit (hunk 2 of the diff over base) changes §10.2 from *"stamps `FLEET_WORKER=1`"* to
*"stamps `FLEET_WORKER=<name>` — the worker's **name**, not the value `1`"* with a parenthetical
citing the **claim-nonce §13 disclosure** and noting the shipped `_worker_env` writes
`env["FLEET_WORKER"] = name` (the §11.4 receipt already carried the correct line). Verified:
- The correction matches the sanctioned disclosure exactly — `OVERNIGHT G-4` records the
  spec-defect disclosure filed for this slice; the refusal keys on the name and *"an arm keyed on
  the value `1` would be a no-op"*.
- **Nothing else in §10 moved.** `git diff 31a21f8..HEAD -- docs/specs/three-tier-command.md` shows
  exactly two hunks: the §3.5.3(c) STATUS-BUILT block and this §10.2 correction. §10.1/10.3/10.4
  bodies are untouched; the §10.3 header immediately follows unchanged.

(The §3.5.3(c) STATUS-BUILT hunk — the other half of `917234b`'s two disclosed defects — verifies
the claim-nonce `limited`-holder prerequisite (verdict `1b`) as BUILT, with a receipt pinned to base
`31a21f8`; that receipt reproduces (see §4). Accurate.)

## 4. Receipts — CONFORMS

`py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md`:
- **55/55 reproduce exactly**, 0 failures, 0 warnings, 0 unclassified, 0 volatile-skipped.
- Self-test passed (one-word paraphrase caught; extraction-failure caught).
- Two pins resolved: `235421e5` (author) and `31a21f8` (base). **No `# at HEAD`** anywhere
  (`grep -c "# at HEAD"` → 0). Both pins are real commits (`git cat-file -t` → commit, commit).
- The one new/moved receipt (§3.5.3(c) verdict-`1b`, pinned at base `31a21f8`) reproduces — the
  merged claim-nonce branch is present there. `# live:` receipts (native-substrate ratification
  status, lessons.md third addendum) reproduce against the working tree.

## 5. Floors & scope — CONFORMS

- **Full suite 3.13:** `1888 passed, 8 skipped`. **Full suite 3.10 (floor):** `1888 passed,
  8 skipped`. Matches the expected 1888/8 on both interpreters.
- **Scope clean.** `git diff --stat 31a21f8..HEAD` touches only: `bin/fleet.py`,
  `bin/hooks/stop_outcome.py`, `docs/specs/three-tier-command.md` (two sanctioned hunks),
  `docs/proposals/GOALS-tier-chain-proposal.md` (new), and 8 test files. **No** edits to
  `docs/OPERATOR-GATES.md`, `supervisor/GOALS.md`, `supervisor/JOURNAL.md`, `GOALS.md`, or
  `docs/specs/claim-nonce.md`. The only ratified-content edits are the two §13-cited/sanctioned
  spec corrections (§3.5.3(c), §10.2), verified against the disclosure in §3(b).
- (Pre-existing flake noted by the build journal: `test_a_valid_proof_still_exits_0`, a wall-clock
  isolation heisenbug in the existing suite, unrelated to slice work. Did not recur in these two
  full runs.)

## 6. Proposal file — CONFORMS

`docs/proposals/GOALS-tier-chain-proposal.md` is internally consistent with the resolver's actual
read paths and defaults:
- The proposed block keys (`supervisor-tier-chain`, `worker-tiers`, `tier-model`) are **exactly**
  the keys `_parse_tier_policy_block` recognises — no key the code does not read.
- The block is generated in-code by `proposed_goals_tier_block()` (fleet.py:8651), whose docstring
  states it is *"kept in code so the proposal doc and the parser never drift"* — the doc's verbatim
  block matches it line-for-line.
- Documented behaviour matches: `resolve_model_for_role("supervisor")` → `supervisor_chain[0]` →
  `tier_model` alias; empty `tier_model` ⇒ omit `--model` (§3.3(d)); `interface` advisory only.
- No model-id literal introduced; aliases (`opus`/`sonnet`) are CLI tier aliases per §3.2. No drift
  at birth.

## 7. Contradiction re-sweep — CONFORMS (1 merge-time fold-in, MINOR m2)

New code/docs vs `SPEC.md §18`, `SKILL.md`, `supervisor.md`:
- The 150–200k band is **already reconciled on base**: `SPEC.md:265` Handoff row
  (*"supersedes the drafted 300–500k … enter at 150k, hard ceiling 200k; binds supervisors AND
  workers"*), `SKILL.md:57` (worker band), `supervisor.md:78,138`. The build shipped
  `BAND_SOFT/HARD=150k/200k` — consistent, no new contradiction. (§11.1's pinned `500k` receipt is a
  claim about the older `235421e5` tree and does not reflect base — not drift.)
- **m2 (MINOR, pre-flagged doc-sync):** the branch adds `_doctor_check_pending_decision` (§8),
  taking the doctor-check count 22 → 23. `SPEC.md:273` enumerates *"**22** checks"* without
  `pending_decision`. This is **branch-local** (SPEC.md is descriptive-at-a-pin and the build branch
  is not `main`) and is **already enumerated** in three-tier §12's SPEC.md fold-in (*"the
  operator-gate state file (§8). Fold in when built."*). It becomes due at merge-to-main, not a
  silent/new contradiction. No `SPEC.md §18` milestone sentence is falsified (three-tier is a
  separate slice, correctly absent from §18).

No sentence in the three named docs is silently made false by the build.

---

## Findings (severity-ranked)

- **m1 (MINOR, ratified-spec text)** — §7.2 predicate text still says *"and that body is
  roster-live"* while the shipped, correct predicate keys holder-alone. File a one-line §7.2
  amendment (drop the roster-live conjunct; re-state B9 as claim-ownership). Disclosed in the build
  journal + inline comment, but the ratified §7.2 body is uncorrected and this is not yet in §12's
  doc-sync list. Non-blocking (code is correct).
- **m2 (MINOR, doc-sync owed at merge)** — `SPEC.md §13` "22 checks" enumeration will need
  22 → 23 + `pending_decision` at merge-to-main. Already covered by three-tier §12's SPEC.md
  fold-in. Non-blocking.

Zero Critical, zero Major. All BUILT surfaces conform to the ratified spec; receipts and both floors
are green; scope is clean; the two ratified-content edits match their sanctioned §13 disclosures.

**MERGE VERDICT: sound** (file m1 + m2 as doc-sync follow-ups; neither blocks the code merge).
