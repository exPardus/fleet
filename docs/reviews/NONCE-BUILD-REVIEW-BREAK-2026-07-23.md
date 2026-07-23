# BREAK-LENS review — claim-nonce build (`nonce/review-break` @ 01e54af)

**Lens:** adversarial / repro authority. **Base:** `e01765c..01e54af` (19 commits,
`bin/fleet.py` +1576). **Spec of record:** `docs/specs/claim-nonce.md` (ratified, option (b)).
**Reviewer worktree:** `C:\proga\fleet-nonce-rb` (repro authority here only; the live repo was
inspected READ-ONLY).

## Verification harness (all green)

- Full suite BOTH floors: `py -3.13 -m pytest -q` → **1779 passed, 8 skipped**;
  `py -3.10 -m pytest -q` → **1779 passed, 8 skipped**. Matches the claimed 1779/8.
- `py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/claim-nonce.md` →
  **pass, 58/59 reproduce, 0 failures, 1 warning** (the one `# volatile` transcript-count block —
  expected). The verifier's own seed test passes (paraphrase + extraction-drop both caught).
- After every code injection below the worktree was restored; final `git status` clean.

---

## TRAP 1 — LIVE BACK-COMPAT (highest stakes)

Live claim (read-only): `inc-20260723T043246Z-cd54`, 5-key legacy shape, no nonce fields, no `state`
⇒ `_claim_is_legacy` True. Built a test-fixture replica of the exact shape and drove every verb.

- **CLEAN** `_require_claim_holder` legacy branch (fleet.py:9261) upgrades in place on sid match,
  mints the live generation, `mint=False`. Repro: replica + `cmd_sup_checkpoint`/`cmd_sup_heartbeat`/
  `cmd_sup_release` all rc 0 through the legacy branch; post-verb keys correct
  (release drops `session_id`/`heartbeat_at`/`nonce_hash`, carries `state:released`).
- **CLEAN** full handoff from a legacy predecessor: `sup-handoff-begin` upgrades the legacy claim
  and stamps `handoff_token_hash` (fleet.py:9636-9649); successor `sup-boot --handoff-token` writes
  HANDSHAKE with token hash + its own `nonce_hash`; `sup-handoff-complete` transfers on token match.
  Repro (external preflights/dispatch stubbed): holder→successor transfer rc 0, `via=handoff`,
  `nonce_seq=1`, task file unlinked.
- **CLEAN** the gate does NOT arm against a legacy claim (fleet.py:8920 `_claim_is_legacy` → return),
  so a running manager's `spawn`/`kill`/etc. keep working WITHOUT `--nonce` until it voluntarily
  upgrades via a `sup-*` verb. Merge does **not** brick the running supervisor; after a routine
  `sup-checkpoint` upgrades the claim, subsequent lifecycle verbs require `--nonce` and the exit-4
  message names the fix — self-correcting, the disclosed option-(b) cost, not a regression.

No regression found. Legacy → new-code path is sound.

---

## TRAP 2 — Founding-incident replay (independent re-derivation)

Re-derived §5.4(c) with two bodies of one lineage holding generation G.

- **CLEAN** Before divergence both `real` and `fork` present live G ⇒ both ACCEPT (the mechanism
  cannot prefer either — §5.4(c), disclosed); a fork with no generation ⇒ REFUSE.
- **CLEAN** After the real body advances the chain (checkpoint mints P, next verb acknowledges,
  `nonce_seq` 1→2, G retired), the fork presenting stale G ⇒ **REFUSE** on `fleet send`. Under
  option (b) `send` IS gated (fleet.py:3983), so the 2026-07-16 send-only zombie class becomes a
  refusal after the first divergence, exactly as the §7 table claims for (b). "Gate absent → class
  reproduces" is confirmed structurally: injection 1 below (gate neutralized) turns the divergent-body
  refusals green, i.e. the class sails through as under option (a).
- **CLEAN** the wart's cousin — same-sid stale-heartbeat recovery: `sup-heartbeat` on a stale,
  same-sid legacy claim recovers (rc 0); `_require_claim_holder` gates on continuity, never on
  staleness. Incident-2 self-recognition is the `resume` verdict (T14(ii), passing).

---

## TRAP 3 — the `init` gating flag

- **CLEAN** No false-refusal on any setup path. Repro (`_supervisor_gate("init", …)`):
  fresh-machine setup (no INCARNATION) ⇒ ACCEPT; `fleet init --statusline` from a plain shell
  (no `CLAUDE_CODE_SESSION_ID`) ⇒ ACCEPT; CI / human shell (no sid) ⇒ ACCEPT. Only a **sid-bearing**
  caller against a **live fresh non-legacy** claim without the generation is refused
  (fleet.py:2821, docstring 2816-2820 accurate).
- **CLEAN** taxonomy: §7's mutating-lifecycle row (claim-nonce.md:1949) lists `init`; SKILL.md:49
  lists `init` among gated verbs. Consistent.

---

## TRAP 4 — Autoclean exemption

- **CLEAN** `cmd_autoclean` contains **no** `_supervisor_gate` call (structural, not merely an
  arming carve-out). The gate's exemption is "no `CLAUDE_CODE_SESSION_ID`", which the scheduled task
  and a human shell both get. Repro: a no-sid caller ⇒ ACCEPT; a sid-bearing caller ⇒ REFUSE.
- **CLEAN / not spoofable by a worker.** Nothing marks a caller "autoclean"; the exemption is the
  generic no-sid path. A worker carries its own sid at runtime (its harness sets it; `_worker_env`'s
  strip only affects the launch env), so a worker CANNOT wear the exemption — it is gated like any
  other sid-bearing caller. The only way to reach the no-sid path is the documented shell bypass that
  option (b) explicitly tolerates. No WORKER-reachable bypass of the exemption specifically.

---

## TRAP 5 — Handoff token

- **CLEAN** succession turns on the token, not the sid (fleet.py:9791-9802). Repro of the break
  cases:
  - token mismatch ⇒ refuse, claim untransferred (`test_complete_refuses_on_token_mismatch…`, and
    injection B below: removing the check ⇒ 2 failed).
  - absent token (old-code predecessor) ⇒ `not expected_hash` fail-closed refuse
    (`test_complete_is_fail_closed_when_the_claim_carries_no_token`).
  - successor crash before HANDSHAKE ⇒ `hs is None` ⇒ "no HANDSHAKE" refuse.
  - abort-after-token-write ⇒ `sup-handoff-abort` pops `handoff_token_hash` (fleet.py:9925) and
    writes the doctor-visible abort flag; a replayed `complete` then hits `not expected_hash` refuse.
    No failure path leaves a half-transferred claim.
- **CLEAN** `--expect-sid` optional does not weaken verification: the token (256-bit, delivered only
  via the unlinked task file) is the check; a sid mismatch is a warning naming the fork
  (fleet.py:9805-9810), which is the §6.4 fork-tolerance the redesign exists for.
- **MIN** `skills/fleet/supervisor.md:102` — the handoff-complete template
  `fleet sup-handoff-complete --expect-inc <INC> [--expect-sid <SID>]` omits `--nonce`, and so does
  the begin template at `:97`, while `complete` requires a continuity proof (`_require_claim_holder`,
  fleet.py:9779). Step 1 (`:96`) bothers to annotate "(present `--nonce`)"; steps 2 and 4 do not —
  an inconsistency an LLM manager copying the numbered template can trip on at the exact moment the
  redesign protects. **Repro:** legacy handoff harness — `complete` without the predecessor's
  begin-printed NONCE raises `SupervisorContinuityError` (exit 4); passing it ⇒ rc 0.
  **Not-blocking:** the general rule at `:27-29` ("present `--nonce` on your next supervisor verb")
  covers it and the exit-4 message ("Present the current generation with `--nonce <value>`") is
  self-correcting. **Fix:** add `--nonce <value>` to the `:97` and `:102` command templates.

---

## TRAP 6 — View purity (§5.8 + terminal-surface)

- **CLEAN** No view path takes a lock, writes, or gates: `cmd_sup_status`, `supervisor_status_line`,
  `_project_claim`, `_project_handshake`, `_doctor_check_supervisor_claim` all show
  `fleet_lock=0 write_incarnation=0 _supervisor_gate=0 save_registry=0`.
- **CLEAN** No hash leaks. Repro: a claim carrying `nonce_hash`/`pending_nonce_hash`/
  `prior_pending_hash`/`handoff_token_hash` + a HANDSHAKE with token+nonce hashes ⇒
  `sup-status --json` leaks **NONE** of the four; projection publishes
  `nonce_present`/`pending_present`/`pending_age_seconds` (observables, not material); the handshake
  projection publishes `handoff_token_present` only. `_project_claim` is an allowlist (fleet.py:9420)
  excluding every `*_hash`. Rejection record carries `presented_prefix` = 8 hex only, never the value.

---

## TRAP 7 — TTL / heartbeat-fresh arming (clock edges)

- **CLEAN** boundaries match the spec's stated choices:
  - gate arming (fleet.py:8918): `age > SUPERVISOR_CLAIM_STALE_SECONDS` ⇒ disarmed; at exactly S it
    is armed — matches "older than S → disarmed" (§4.13(e)).
  - pending TTL (fleet.py:9174): `age <= PENDING_NONCE_TTL_SECONDS` ⇒ unchanged, else replaced (old
    hash → `prior_pending_hash`); at exactly TTL it is unchanged — matches "older than TTL → replaced".
  - unreadable heartbeat ⇒ gate **fails OPEN** (fleet.py:8916-8917), matching §7's stated "fail OPEN";
    a corrupt claim is reported by its own doctor row.
  - clock step: a future-dated / negative-age heartbeat keeps the gate armed (no crash, fail-closed
    direction) and does not spuriously replace a pending. Every timestamp read is wrapped
    (`_parse_iso` in try/except) — no clock edge raises through a verb.

---

## TRAP 8 — Test theater on the injections

Re-ran **5** of the builder's fault-injection claims by patching `bin/fleet.py` and running the
named tests; every one goes red as claimed (worktree restored after each):

| # | injection | claimed | re-run result |
|---|---|---|---|
| A | gate never refuses (option a) — neutralize the `raise` | 16 failed | **16 failed** ✓ |
| B | `sup-handoff-complete` token check removed (`if False:`) | 2 failed | **2 failed** ✓ (`test_complete_refuses_on_token_mismatch…`, `…fail_closed_when…no_token`) |
| C | lineage-ownership arm removed from `_worker_is_foreign` | 2 failed | **2 failed** ✓ (`test_a_proven_later_body…`, `test_a_rotated_body_proving_lineage_kills…`) |
| D | N1 rule-2 flip (`holder_sid != caller_sid`) | (T14 iii) | **1 failed** ✓ (`test_iii_n1_attack_spoofed_sid_without_a_generation_refuses`) |
| E | legacy predicate drops the `state` check | (released) | **2 failed** ✓ (released-claim-is-not-legacy pins) |

- **CLEAN** No test theater found in the sample. Guards carry their own weight; the incarnation-2
  lesson ("a green run under injection is a coverage gap") is honored — the pins fail when the guard
  is removed.

---

## TRAP 9 — New-defect hunt

- **MIN** `bin/fleet.py:8859` — `_supervisor_gate`'s docstring says it fires "when a mutating
  lifecycle verb is run by a **supervisor-shaped caller**", but the implementation performs no
  shape check: it gates **any** sid-bearing caller that cannot prove continuity (fleet.py:8903-8924).
  Consequence: any legitimate second session with a sid — a non-supervisor operator-driven Claude
  session, or a worker — running `spawn`/`send`/`interrupt`/`archive`/`init`/etc. while a fresh
  supervisor claim is held is refused (even the verbs that had no prior guard). **This is more
  protective, not a security hole** — it is consistent with §5.6's "at most one nonce-bearing actor
  runs lifecycle verbs" and with the fleet's one-manager model, is bypassable (shell / `--nonce`),
  and `autoclean` is exempt — but it is a **behavior change broader than the docstring's stated
  scope** and worth stating precisely. **Fix:** reword the docstring to "any session-bearing caller"
  (the code is correct; the prose under-claims its reach).
- **CLEAN** no hash reaches any journal, event log, task file, or error message (grep + trap-6
  repro); `_SUPERVISOR_ENTRY_RE` header format unchanged; the rejection log append is atomic and
  writer-unbounded (`_atomic_append_bytes`), compacted only out-of-band under `fleet_lock` in
  `sup-boot`; `SUPERVISOR_BOOT_RC` maps every verdict (no `KeyError` fall-through); the three
  dict-literal writers (7145/7159/7404 equivalents at 8766/8813/8824) all carry the v2 fields.

---

## MERGE VERDICT: sound

No CRITICAL and no MAJOR findings survived verification. The suite reproduces 1779/8 on both floors,
receipts self-test passes, and 5/5 sampled fault injections go red as claimed. The live legacy claim
survives a merge on every verb path. The two MINOR findings are documentation/precision only
(supervisor.md handoff templates omit `--nonce`; the gate docstring under-claims its scope), both
non-blocking and self-correcting at runtime via the exit-4 message. Recommend merge; fold the two
MINOR fixes in at convenience.
