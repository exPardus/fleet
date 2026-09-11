# Nonce build — SPEC-LENS review (conformance + receipts)

**Branch:** `nonce/review-spec` @ `01e54af` (15 commits over base `e01765c`).
**Authority:** `docs/specs/claim-nonce.md` (ratified 2026-07-23, gate option (b), §7 verb taxonomy BINDING).
**Lens:** SPEC — claim-vs-reality conformance, anchor+witness. Independent of the break lens.
**Method:** every claim is a grep/receipt against the *built* `bin/fleet.py` at branch HEAD (the spec's §4 receipts pin `091d5fa`, the pre-build tree; the build implements §5–§13, verified against those sections).

## FINDINGS

- **MAJ — `supervisor/JOURNAL.md:6` kinds line is stale.** The live, git-tracked journal header still
  reads `Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT` —
  **missing `RELEASED` and `LIMIT-TRANSFER`**, both of which the build now writes. §8's doc table binds
  this edit to *this slice* verbatim (`| **supervisor/JOURNAL.md:6** | the live, git-tracked kinds line
  — never regenerated (§4.7), so RELEASED must be added there as well as to the seed | this slice |`),
  and §4.7 names it three times as the fifth, easily-missed kind-list. The build updated the other four
  loci (`SUPERVISOR_JOURNAL_KINDS` @8195, `_SUPERVISOR_JOURNAL_SEED` @8215, `SKILL.md:47`; `--kind`
  choices are the correct exception) and left exactly the one §4.7 warned about. It is **unmet and
  undisclosed** — no commit message or residual note explains the omission.
  *Tension:* CLAUDE.md's single-writer rule and checklist item 4 read the file as "must stay untouched".
  But single-writer governs *appended entries* (written by `fleet sup-*` only); line 6 is header/doc
  text, and §4.7 explicitly contemplates editing it. Resolution is an operator/author call: either land
  the one-line header edit (the correct reading — editing the doc line is not appending an entry), or
  waive §8's row explicitly. As shipped, a `RELEASED`/`LIMIT-TRANSFER` entry will appear under a header
  that does not list the kind. Not a functional break; a bound documentation obligation left open.

- **MIN — `claim-nonce.md` §6.1 verdict table omits `limit-transfer` and the B6 refuse-precondition.**
  The code ships a five-branch verdict order (0 fresh / 1 released **+ B6 `released_by_sid`-roster-live
  refuse** / 1b `limit-transfer` / 2 refuse / 3 resume / 4– ), but the ratified spec-of-record's §6.1
  table shows only 0/1(released)/2/3/4– — `grep -ni "limit-transfer" docs/specs/claim-nonce.md` → no
  match, and no B6 precondition on rule 1. Both branches ship under `three-tier-command.md` authority
  (`:432-437` limit-transfer, `:1184-1190` B6), which explicitly files them "owned by the claim-nonce
  build slice", so the *code* is authorized and correct. The gap is that a reader auditing code against
  the spec-of-record §6.1 finds two verdict branches with no anchor *in this spec*. The shipped-doc
  surfaces `SKILL.md:40` and `supervisor.md` **do** document both, so the operator-facing contract is
  complete; only the design spec's own table is behind.

No CRITICAL. The nonce mechanism itself conforms end to end.

---

## 1. §-by-§ conformance sweep

**§5.2 primitives — CONFORMS.** `PENDING_NONCE_TTL_SECONDS = 900.0` (@8094, TTL=900 not 300, §5.3's
asymmetry-toward-long). `mint_nonce` = `secrets.token_urlsafe(32)` (@8157). Comparison is
`hmac.compare_digest` over two **hex** strings — `nonce_digest(presented)` vs stored (@8183), the exact
shape §5.2 mandates and the "digest object vs hex string" shape it warns against is avoided. `secrets`,
`hashlib`, `hmac` imported @31/32/37; only `json` was pre-imported — stdlib-only, 3.10-floor safe
(`from __future__ import annotations` neutralises the `X | Y` hints).

**§5.3 five validation rules + legacy branch — CONFORMS.** `_require_claim_holder` (@9193) implements
rules 1–5 in order (@9279-9293): live⇒accept, pending⇒`_acknowledge_pending` (promote, `nonce_seq+1`,
clear all three slots @9117), prior⇒accept + quiet `superseded-pending` record (@9281-9288), legacy⇒
sid-equality-once-then-upgrade (@9261-9278), else⇒`_continuity_refusal` (@9293). Legacy predicate
`_claim_is_legacy` = `"nonce_hash" not in claim and "state" not in claim` (@8842) — **verbatim §9**.
Restamp `session_id ← caller` on every validated write (@9297, §6.6). One `write_incarnation` performed
by the caller after commit (checkpoint @9314, etc.); notices returned not printed, keeping delivery
outside the committed state change (§5.3). Minting: `_mint_pending_nonce` mints iff no outstanding
pending or aged past TTL, moves the replaced hash to `prior_pending_hash` (one slot), prints
`NONCE: unchanged (generation N+1 already outstanding)` otherwise (@9150-9180). `sup-handoff-begin`
carries `mint=…`; gated verbs validate without minting (§7 — the gate calls `_nonce_presentation` only,
@8922).

**§5.4(e) observable + F3 superseded NOTE wording — CONFORMS.** `_nonce_pending_age_note` NOTEs an
unacknowledged pending past `TTL × NONCE_PENDING_STALE_MULTIPLE` (@10031-10036), citing §5.4(e). The
`superseded-pending` doctor NOTE (@10081-10086) names **both** possibilities — "a second presenter OR a
violated presenter obligation … Not proof of either, and not a refusal — but not benign" — i.e. the
break-gate F3 wording that forbids "quiet" reading as "benign".

**§5.6 rejection log + ONE ok=False doctor condition — CONFORMS.** `_append_nonce_rejection` writes
`state/supervisor-nonce-rejections.jsonl` (@8990, gitignored) via `_atomic_append_bytes` (not RMW).
Fields per §5.6 (`ts`/`kind`/`verb`/`caller_sid`/`expected_seq`/`pending_at`/`presented_prefix`).
`_doctor_check_supervisor_claim` (@10039) flips `ok=False` for **exactly one** condition — a `refused`
record in the last 24 h (@10061-10062); `superseded-pending` is a NOTE, not `ok=False` (@10070-10086),
as §5.6 requires.

**§5.8 view redaction — CONFORMS.** `_project_claim` (@9391) is an **allowlist**: `nonce_hash`,
`pending_nonce_hash`, `prior_pending_hash` all omitted; publishes `nonce_present`/`pending_present`/
`pending_age_seconds`/`nonce_seq`/`lineage_id`/`state`. `_project_handshake` (@9429) redacts
`handoff_token_hash` → `handoff_token_present`. Scoped to the dict-dumping path (the human f-string is
correctly left alone, §5.8's reverted SPURIOUS-FIX). `cmd_sup_boot` stdout prints the minted plaintext
once and no hash (verified via `_deliver_notices` @9183 + boot bundle).

**§6.1 verdict order — CONFORMS (code); see MIN finding re §6.1 doc table.**
`supervisor_claim_decision(claim, live_sids, latest_entry, now, stale_seconds, caller_sid, nonce_valid,
holder_limited)` (@8492). Order @8531-8621: fresh → released (**B6**: `refuse` while `released_by_sid`
is roster-live, @8553-8557) → **limit-transfer** (`holder_limited and not resume_ok`, ahead of the
roster guard, @8563-8586) → refuse (roster-live UNLESS `holder_sid==caller_sid and nonce_valid` —
continuity-keyed, not sid-keyed, N1 fix @8587) → resume (@8590) → rules 4– with **explicit
`holder_live` precondition and stated `else: refuse`** (@8603-8605, break-gate F2). rc map
`SUPERVISOR_BOOT_RC` (@8206) carries `resume`/`limit-transfer`/`claim`/`seize`=0, `refuse`=2,
`freeze`=3 — no `KeyError` fall-through. Distinct exit code: `SupervisorContinuityError` (@2328),
`SUPERVISOR_CONTINUITY_RC = 4` (@2325), caught **ahead** of the generic `FleetCliError` arm in `main()`
(@10446-10450). `SupervisorClaimGateError` subclasses it, so the gate inherits code 4.

**§6.2 lineage — CONFORMS.** `spawned_by_lineage` additive field written at spawn (@2936) and carried
by respawn (@4458/@4509). `_worker_is_foreign(record, caller, claim_lineage=None)` treats a worker
not-foreign when `spawned_by_lineage == claim_lineage` proved this invocation (@2609-2617); unproven
caller ⇒ today's answer. `lineage_id` minted at fresh claim (@8770), **carried** across handoff
(@9828, never re-minted), **re-minted** on seize *and* limit-transfer (@8817 — correct: neither has a
predecessor alive to vouch). `spawned_by` untouched/spawn-immutable.

**§6.3 sup-release + status-line coupling — CONFORMS.** `cmd_sup_release` (@9334) rewrites (not
deletes) INCARNATION as a **literal** with exactly §6.3's key set: `incarnation_id`, `lineage_id`,
`claimed_via`, `released_at`, `released_by_sid`, `state:"released"`, optional `reason` (@9376-9383);
drops `session_id`/`heartbeat_at`/`nonce_hash`/etc. `mint=False`, notices discarded. Journals
`RELEASED`. `supervisor_status_line` (@…) has a **released branch ahead of the heartbeat read**
(cites §6.3 binding rule) so a clean release does not read as "heartbeat unreadable" across doctor /
sup-status / the SessionStart hook (N5 fix). No `--force` form.

**§6.4 handoff token — CONFORMS; legacy sid-refusal GONE.** `cmd_sup_handoff_complete` (@9…) verifies
`hs["incarnation_id"] == expect_inc` **and** `hs["handoff_token_hash"] == claim["handoff_token_hash"]`
(fail-closed on absent token). `--expect-sid` is optional: a mismatch is a **warning naming the fork**,
not a refusal (@9805). New claim literal carries the successor's `nonce_hash` (from HANDSHAKE),
`nonce_seq=1`, predecessor's `lineage_id`. **Grep proves the old refusal is gone**:
`grep -n 'session_id.*!=.*expect_sid\|!= args.expect_sid' bin/fleet.py` → only `9805` (the new warning
path); the pre-build `hs["session_id"] != args.expect_sid → NOT transferring` refusal has no match.

**§7 gate — CONFORMS; init gating supported by §7's text.** `_supervisor_gate` (@8857) is called at
the top of **10** mutating lifecycle verbs — `init`@2821, `spawn`@2911, `send`@3983,
`resume-limited`@4162, `interrupt`@4320, `release`@4354, `respawn`@4630, `kill`@4803, `clean`@4945,
`archive`@5523. §7's mutating-lifecycle row lists eleven — those ten plus `autoclean`. **`autoclean` is
correctly ungated** (the scheduled task has no `CLAUDE_CODE_SESSION_ID`, §7(b) structural exemption;
`cmd_autoclean` has no gate call). **Ruling on `init`:** §7's taxonomy explicitly places `init` in the
"Mutating lifecycle" class, so gating it is *supported by §7's text* — **ACCEPT**. Arming conditions
match §7 (no sid / no or released claim / stale beat / unreadable beat / legacy ⇒ disarmed; else
demand a validating generation, minting nothing). `--nonce` present on all 10 gated verbs and all
`sup-*` (@10158-10365), so the gate is satisfiable. It is a subclass of `SupervisorContinuityError`
(exit 4) and its message declares itself a speed-bump.

**§8 doc table + compaction site — CONFORMS except the JOURNAL.md:6 row (MAJ).** `SPEC.md` §4/§12/§13/
§15 rows updated (schema, INCARNATION v2, doctor `ok=False`-on-refused + orphan-handoff NOTE, lineage
guard). `SKILL.md` and `supervisor.md` updated (below). Compaction of the rejection log is
`_compact_nonce_rejection_log` called **only** inside `cmd_sup_boot`'s `fleet_lock` (@…), never
`fleet clean` — §8's "only sweep site" rule honored. *Note:* §8 says "check count stays 21"; SPEC.md
now reads 22 (M-D/M-E added `daemon_wedge`+`tzdata` before this slice). The build added **zero** new
doctor checks (it mutated `supervisor_claim`/`supervisor_handoff`), so the slice honors §8's intent;
the "21" is a stale design-time number, not a build defect.

**§9 dict literals — CONFORMS.** All three dict-literal writers carry `nonce_hash`/`nonce_seq`/
`lineage_id`: fresh @8768, seize/limit-transfer @8817, handoff-complete @9822 (nonce_hash conditional
on the successor's HANDSHAKE value, by §6.4 design — absent ⇒ legacy claim the next call upgrades).
`state` is correctly *not* carried by these (only a released claim has `state`).

**§13 disclosure — CONFORMS.** The three-tier `FLEET_WORKER=1` defect is disclosed in-code (@9231-9234,
"three-tier ~L1078 describes it as FLEET_WORKER=1; that text is wrong … its own receipt at :1402-1408
pastes the correct line") and in spec §13 item 1, without editing the ratified three-tier spec. The
ratified three-tier three-tier text is UNTOUCHED (git scope check §5 below).

## 2. Receipts — CONFORMS

`py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md`:
**`58/59 reproduce exactly, 0 failures, 1 warning`** — the one WARN is the disclosed `# volatile`
transcript-count block (`~/.claude/projects` mtime drifted `Jul 21 20:54 → Jul 23 23:25`, load-bearing
facts existence+readability unchanged). Self-test PASSED (paraphrase + extraction seeds caught). Pins
resolve to `091d5fa`. **Re-pin audit:** no `# at HEAD` in any receipt (`grep "# at HEAD"` matches only
§14 descriptive prose); every fenced block carries `# at 091d5fa` (or the single `# live` git-check-
ignore block, §4.13(f)). CLEAN.

## 3. Both floors — CONFORMS

- `py -3.13 -m pytest -q` → **1779 passed, 8 skipped**.
- `py -3.10 -m pytest -q` → **1779 passed, 8 skipped** (identical).
- `tests/test_receipts.py` → **49 passed**.

## 4. Doc surfaces — CONFORMS (one gap = the MAJ finding)

- `SKILL.md:40` sup-boot row: `Exit 0=hold/handshake-written, 2=refuse, 3=freeze, **4=continuity proof
  failed**`, verdicts `claim/resume/seize/limit-transfer/refuse/freeze` — **rc 4 documented**.
- `SKILL.md:43` documents `sup-release` (rewrites INCARNATION released, journals RELEASED, no `--force`).
- `SKILL.md:47` journal-kinds line carries `RELEASED` + `LIMIT-TRANSFER`.
- `supervisor.md` verdict table adds `resume`/`limit-transfer`; nonce presentation doctrine; handoff
  token with optional `--expect-sid`; release-then-stop section. No stale band/verb text.
- **`supervisor/JOURNAL.md` untouched by the branch** — `git log e01765c..01e54af -- supervisor/JOURNAL.md`
  empty; last touch is pre-branch merge `79664ce`. Single-writer preserved. *(This is also the root of
  the MAJ finding: the same untouched-ness leaves line 6's kinds list stale.)*

## 5. Regression scope — CONFORMS

`git diff --stat e01765c..01e54af --` for `docs/specs/three-tier-command.md`,
`docs/OPERATOR-GATES.md`, `docs/specs/native-substrate.md`, `supervisor/JOURNAL.md` → **all empty**.
The ratified three-tier spec, the operator-gates checkboxes, native-substrate, and the supervisor
journal are untouched by the branch.

## 6. Contradiction re-sweep

- §3 non-goals were reconciled with the ratified §7 (commit `df0209f`) — no residual "gate is deferred"
  contradiction.
- `spawned_by` immutability sentence in SPEC.md §4/§15 stands (§6.2 adds a field, renames nothing) — no
  sentence made false.
- The one substantive contradiction is the **MIN finding**: `claim-nonce.md` §6.1's verdict table is
  narrower than the shipped verdict order (no `limit-transfer`, no B6 precondition). It is a
  completeness gap against the spec-of-record, not a false statement — both branches are anchored in
  the ratified three-tier spec and reproduced faithfully in code and in the operator docs.

## 7. Dispositions

| Disclosed flag/residue | Ruling | Receipt |
|---|---|---|
| `init` gating | **ACCEPT** | §7's taxonomy lists `init` in "Mutating lifecycle"; gate call @2821; §7's text supports the reading |
| `path.exists()` early-out comment (`01e54af`) | **ACCEPT** | behavior-identical — `read_text` on an absent file raises FileNotFoundError, swallowed by the existing `except OSError`; comment sharpen only, suite stays green |
| conftest `FLEET_WORKER` strip | **ACCEPT** | necessary: `_worker_env` stamps `FLEET_WORKER`, the suite is run from a fleet worker, so without the autouse `delenv` every `sup-*` test would hit §6.5's refusal; arm-tests set it explicitly (mirrors the `CLAUDE_CODE_SESSION_ID` pattern) |
| ~6 injection-found coverage gaps | **ACCEPT** | commit messages disclose green-first injections (gate ×1, lineage ×3, handoff ×1, +1) each closed by adding a test *before* accepting the injection — the "green under injection = coverage gap" doctrine applied correctly; a strength, not a defect |

---

## MERGE VERDICT: sound-after-JOURNAL.md:6-kinds-line

The nonce mechanism conforms to `claim-nonce.md` end to end — validation, lifecycle, concurrency,
verdict order, gate taxonomy, schema writers, view redaction, exit-code seam, and both floors all
verified by receipt. The single MAJ is a **bound documentation obligation** (§8's `supervisor/JOURNAL.md:6`
kinds-line edit) left unmet and undisclosed; it is trivially fixable (one line) once the single-writer
tension is ruled (recommend: land the header edit — editing a doc line is not appending an entry) or
explicitly waived. The MIN (spec-of-record §6.1 table narrower than the shipped/operator-documented
verdict order) is a completeness gap with no functional consequence. Neither blocks the mechanism;
both should be closed before or at merge.

**Counts: 0 CRIT / 1 MAJ / 1 MIN. Receipts 58/59 (+1 disclosed volatile WARN). Floors 1779/8 on 3.13 and 3.10; test_receipts 49.**
