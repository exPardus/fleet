# Three-tier re-draft — SPEC-lens claims-audit review

**Lens:** spec (lens 2 of 2; break lens ran in parallel, independent, uncoordinated).
**Under review:** `docs/specs/three-tier-command.md` at **`0846d1c`** (branch `mf/tt-spec`).
**Receipt pin claimed by the draft:** `235421e56bfd328a7e913e519a1459ccf55918dc` (`235421e5`).
**Vantage:** worktree `C:\proga\fleet-mf-tt-spec`, branch `mf/tt-spec`, reviewer commit `0846d1c`. Every
`$` line below was executed here. `py -3.13` unless noted; the one enforced-test run is on `py -3.10`
(the floor).

**VERDICT: `fix-list(S1)`** — the factual base is reliable, all binding mandate items 4–10 are answered,
every operator requirement traces both directions, and no contradiction survives against the specs of
record. One MINOR finding: §12's stale-surface enumeration is incomplete (the 150–200k band lives on in
two user-facing surfaces §12 does not list). Additive one-paragraph fix; does not block the design gate.

---

## 1. Receipt re-execution — two independent verifiers, both green; both provably able to fail

### 1.1 The repo verifier (self-test + strict)

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md
seeding a one-word paraphrase into the receipt at line 111
  original: 7733:        argv += ["--model", model]
  seeded:   PARAPHRASED        argv += ["--model", model]
  harness reported 1 failure(s); seeded receipt caught: True
SELF-TEST PASSED: a one-word paraphrase inside a pasted receipt is caught.
pins resolved: 235421e56bfd328a7e913e519a1459ccf55918dc
32/32 receipts reproduce exactly (32 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
```
Exit 0. The self-test's RED sub-run (seeded paraphrase caught) proves the verifier is not a no-op.

### 1.2 My own independent verifier (all 32 blocks, second implementation)

Per the M-E precedent (a verifier that cannot fail proves nothing), I wrote an independent extractor +
tree-materialiser (`git archive <sha>` → tarfile → temp dir, no checkout) that re-runs every block and
diffs stdout. It shares no code with `tools/verify_receipts.py`. Source:
`$CLAUDE_JOB_DIR/tmp/indep_receipts.py`.

**GREEN (all 32):**
```
$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md
extracted 32 receipt blocks from three-tier-command.md
...
32/32 blocks reproduce; 0 FAILED        (exit 0)
```

**SEED / RED runs (harness proves it can fail) — two different blocks, one grep-count and one multiline
`sed`:**
```
$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 0
  [FAIL] block 0 @ 235421e5: grep -c "claude-opus\|claude-sonnet\|claude-haiku\|claude-fable" bin/fleet.py
     expected: '0\nPARAPHRASED-SEED-LINE'
     got:      '0'
31/32 blocks reproduce; 1 FAILED         (exit 1)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 3
  [FAIL] block 3 @ 235421e5: sed -n '8117,8126p' bin/fleet.py
31/32 blocks reproduce; 1 FAILED         (exit 1)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 19
  [FAIL] block 19 @ 235421e5: sed -n '8526,8531p' bin/fleet.py
31/32 blocks reproduce; 1 FAILED         (exit 1)
```
Two implementations, two vantages, same result: **all 32 pinned blocks reproduce byte-exact at
`235421e5`.** (Harness note: an early bytes-mode pass mis-flagged the two `§`-bearing blocks on a cp1252
console decode and CRLF; forcing UTF-8 + newline-normalisation cleared it — a decode artifact in my
tool's output layer, never a receipt discrepancy. Recorded for honesty.)

### 1.3 The enforced-test move is consistent

`0846d1c` dropped `three-tier-command.md` from `tests/test_receipts.py`'s `UNENFORCED` set (it now
carries pinned receipts, so it must be receipt-enforced). The enforced test passes on the floor:
```
$ py -3.10 -m pytest tests/test_receipts.py -q
13 passed in 11.89s
```

---

## 2. Mandate coverage — adjudication items 4–10 + the 2026-07-23 operator requirements

Legend: **FULL** = answered in spec text with receipt / design; **DEFER+cite** = explicitly deferred
with a named authority (never silent narrowing); every `[UNBUILT]` residual carries a no-match receipt.

| Mandate | §  | Status | Sub-clauses (the elided text binds) |
|---|---|---|---|
| **Item 4** — substrate re-pin first; daemon-lifecycle assumptions; G9 beat behaviour (stale roster PASSES epoch; beat is a `send`; `send` refuses under suspicious roster; scheduler eats exit code ⇒ silent drop) | §4 | **FULL** | §4.1 states transient-daemon/idle-exit/wedge/G10 against the actual rows; §4.2 receipts `supervisor_epoch_check` has no staleness test; §4.3 receipts `_cmd_send_native`'s refusal → names the silent-drop as *the* reason the v1 beat is not a scheduled `send`. Correctly inherits claim-nonce §6.6's decline of the staleness axis and files the residual `[MANAGER-VERIFICATION REQUIRED]` per claim-nonce §12 O4 — not re-opened. |
| **Item 5** — beat = first-class `fleet beat` verb; own error taxonomy w/o burning a turn; run-stamp; only thing `--supervisor-beat` installs; beat-worker split; **D8 `send` has no `--model` / model spawn-immutable** | §5 | **FULL** (v1 arm shipped; verb `[UNBUILT]`; split DEFER+cite) | §5.1 v1 = interface-originated `fleet send` (shipped). §5.2 specifies the verb's four-state taxonomy, run-stamp, and install-only role, all `[UNBUILT]` w/ no-match receipt. **D8 receipt present** (block 6, `sed 8865,8866p` → `p_send` takes only `name`+`message`, no `--model`). Beat-worker split recorded as v2 (§9), citing operator 2026-07-23. |
| **Item 6** — generic installer; **`_autoclean_task_is_ours` fix status**; 3 backends or `UnsupportedPlatformError` seam; doctor check; multi-flag refusal; **`ScheduleWakeup` reconciliation** | §6 | **FULL** (largely SHIPPED) | §6.1 receipts the generic `autoclean_task_install(task_name,command,interval_hours)`; two backends + adapter seam (honest: two, not three). **§6.2 confirms the path-only predicate was fixed in M-E to full-identity** (`_fleet_task_is_ours`, receipt @5946/@6022) — not left open. Doctor check + multi-flag CLI `[UNBUILT]`. **§6.3 reconciles `ScheduleWakeup`** with the G7 receipt (grep 0 in fleet.py) — states why it is *not* the mechanism (`claude stop` kills the loop). |
| **Item 7** — heartbeat decoupled from beat period; supervisor record archive/autoclean-protected by construction (S=3600 vs N-h; TTL 24h vs 23h clamp) | §7 | **FULL** (exemption `[UNBUILT]`) | §7.1 S is a standalone constant (receipt @7918), MF3 window mostly closed by claim-nonce §6.1 roster-liveness. §7.2 receipts TTL 24h (@4914) vs 23h clamp (@6033) and specifies the `SUPERVISOR_BODY_NAME` exemption on both `_archive_eligible` (@4917) and `_sweep_husks`. §7.3 keeps heartbeat/beat-period decoupled. |
| **Item 8** — operator-gate routing = a state file, not a journal kind; answerable, un-re-derivable, nag-visible, stops beat burning turns | §8 | **FULL** (`[UNBUILT]`) | `state/supervisor-pending-decision.json`; explicitly rejects the withdrawn PROPOSAL's `NEEDS-OPERATOR` journal kind (append-only can't be cleared); `sup-decision` verb; doctor + `sup-status` nag; routing-not-authorization stated. Absence receipt (block 15). |
| **Item 9** — drop the event-driven arm; its stated blocker misread SPEC §8(a); real blockers make poll-on-beat strictly safer | §9 | **FULL** | Names the wrong justification (mailbox writes ARE sanctioned) and the three real blockers (hooks can't dispatch, sid rotates, lost events silent). §9.1 defers the *scheduled* beat to v2 citing operator 2026-07-23 — deferral is explicit, not silence. |
| **Item 10** — `sup-spawn` via `dispatch_bg` (`--settings`/`--add-dir`/registry/`_worker_env` stated); `respawn/kill supervisor` each owes a tombstone; reserve body name mechanically | §10 | **FULL** (`[UNBUILT]`, w/ M-E precedent) | §10.1 `dispatch_bg` receipt (@7670) + handoff-fix precedent (@8526). §10.2 enumerates all four implications incl. the `FLEET_WORKER`→claim-nonce §6.5 prerequisite. §10.3 reserved name at `validate_name` (@721, F6-shape precedent). §10.4 respawn=release-continuity, kill=release-then-stop, both tombstone (G10). |
| **Op req** swap band 150–200k | §11 | **FULL** | §11.1 replaces the drafted 300–500k; §11.3 encodes both triggers verbatim to `lessons.md#2026-07-23-three-tier-inputs`; §11.2 states the measurement source **and its inadequacy** (no `cache_read` recorded — receipts blocks 22–24, 30). |
| **Op req** tier-model configurable, never hardcoded ids | §3.1 | **FULL** | Roles→abstract tiers→resolver; concrete ids illustrative. Receipt: zero model-id surface (block 0). |
| **Op req** workers Opus/Sonnet only, never Haiku | §3.4 | **FULL** | Doctrine in GOALS; allowlist enforcement `[UNBUILT]`; honest single-provider-moot note. |
| **Op req** beats event-driven only in v1 | §5/§9.1 | **FULL** | See items 5/9. |
| **Op addendum** tier-based, provider-agnostic | §3.1/§3.3 | **FULL** | Daemon-env-per-namespace resolution; every §3.3 citation to `longcat-fleet-usage.md` verified exact (§4 below). |

**No item is answered by silent narrowing.** Every deferral names its authority.

---

## 3. Contradiction sweep — specs of record

- **`claim-nonce.md` (spec-of-record, ratified 2026-07-23).** No contradiction. The draft consumes and
  does not redefine: INCARNATION v2 / boot verdict order §6.1 (`resume`/`refuse`), handoff-verifies-a-token
  §6.4 (§10 respawn/kill), `sup-release` §6.3 (§10.4 kill), the `FLEET_WORKER` refusal §6.5 (§10.2 names it
  a *prerequisite*, correctly not claiming it exists), gate **option (b)** §7 and the corrected verb
  taxonomy. §4.2's handling of the staleness axis matches claim-nonce §6.6 + §12 O4 word-for-word in intent.
- **`native-substrate.md`.** No contradiction; the draft changes no verdict. Every row it leans on is
  OBSERVED/CONFIRMED, **not** one of the three unverified dead-daemon claims:
  transient-daemon+idle-exit (`15/15 live_workers=0`), residual `cause=upgrade` (`4/4`), G7 (`17 beats ~173s`,
  `claude stop` kills the loop), 2.1.216 wedge (shipped `_doctor_check_daemon_wedge`, verified present at pin),
  G10 tombstone. **WITHHELD-reliance sweep: CLEAN** — see the vantage note in §6.
- **SPEC.md v3 invariants.** Additive schema (§10.2 `spawned_by_lineage`, §11.2 `cache_read` — both additive),
  single-writer (`dispatch_bg` choke point), one-live-session-per-name (§10.3 reserved name), platform-adapter-only
  branching (§6.1 two backends + seam, no hardcoded OS branch), G9 epoch freeze — all honoured.
- **`terminal-surface.md` views doctrine (D2/D7).** §8 keeps `sup-status` a lock-free projection; §2/§7
  correctly restate D7 pull-only (fleet injects nothing).

---

## 4. Cross-provider factual base (§3) — every citation re-executed against `longcat-fleet-usage.md`

All EXACT: daemon-env resolution fixed at daemon-boot / `model_not_found` from a pre-existing Anthropic
daemon (usage :12,:14); isolated `CLAUDE_CONFIG_DIR` namespace → separate daemon w/
`ANTHROPIC_DEFAULT_OPUS_MODEL=LongCat-2.0` etc. (:37,:39,:66,:67); "omit `--model`, let `ANTHROPIC_MODEL`
govern" is the doc's explicit instruction (:69); no per-worker mixing = one-daemon-one-backend
(:82,:84); shelved `--provider` flag `docs/specs/providers.md` (:117). §3.2's zero-model-surface and
zero-`CLAUDE_CONFIG_DIR`/`ANTHROPIC_` claims reproduce (blocks 0, 2, 31).

---

## 5. Findings

### S1 — MINOR — §12 doc-sync enumeration is incomplete: the 150–200k band survives in two user-facing surfaces it omits

**Severity:** MINOR (completeness gap in a forward-looking checklist; not a factual error, not a mandate
miss, not a contradiction; does not block the gate).

**Exact quote, §12 (line 776–777):** *"Every file below carries text this spec obsoletes or must be
reconciled with"* — the list names `skills/fleet/supervisor.md`, `supervisor/GOALS.md`, `docs/SPEC.md`,
`docs/specs/autoclean.md`, `docs/OPERATOR-GATES.md`, `knowledge/lessons.md`, `docs/longcat-fleet-usage.md`.
§11.1 likewise flags only *"`skills/fleet/supervisor.md` still quotes the old 300–500k band."*

**The gap — two live surfaces carry the obsoleted band and are not listed:**
```
$ git grep -nI "300k\|500k" -- skills docs/SPEC.md | grep -i "band\|handoff"
skills/fleet/SKILL.md:44:| `fleet sup-handoff-begin` / ... | ... Trigger band: begin ~300k tokens, hard-latest 500k. |
docs/SPEC.md:261:- **Handoff** ... Operator band: begin handoff at ~300k context tokens, hard-latest 500k.
```
`skills/fleet/SKILL.md:44` is a user-facing skill command table (sibling of the `supervisor.md` §12
*does* list) and is omitted entirely. `docs/SPEC.md:261` carries the band, yet §12's SPEC.md bullet
enumerates only the registry / `sup-spawn` / scheduled-task-family / gate-file changes — not the band
collision. This is exactly the "user-facing docs lie longest" class the 2026-07-23 doc-pass lesson warns
about: a doc-sync pass that follows §12 literally would leave both stale.

**Failure scenario:** the build slice runs the §12 doc-sync pass, updates `supervisor.md` to 150–200k,
and ships — leaving `SKILL.md` and `SPEC.md §6` telling the operator "begin ~300k, hard-latest 500k".
Two surfaces now disagree with the spec of record on the single operator-set number this draft exists to
change.

**Fix:** add `skills/fleet/SKILL.md` (the `sup-handoff` row's band) and the `docs/SPEC.md §6` handoff
band to §12's list (and, ideally, name them in §11.1 alongside `supervisor.md`). One additive edit.

*(Historical artifacts also carry the old band — `docs/superpowers/plans/2026-07-14-native-pivot-mA-supervisor.md`,
`docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md`, and the 2026-07-17 review files.
These are frozen records, not live operator surfaces; excluding them is correct. `docs/NEXT-SESSION.md`
already flags "down from 300–500k" and is rewritten each session — not a finding.)*

---

## 6. Checks that came back clean (recorded, not findings)

- **Status discipline.** Line 3 reads `**Status: `drafting`.**`; line 12 states *"An author never
  promotes its own spec."*; §13 non-goal *"Not building during the design gate."* No self-promoting
  language anywhere.
- **`[UNBUILT]` tags.** Every prescriptive future-behaviour claim carries `[UNBUILT — owned by the
  three-tier build slice]` with a no-match receipt; Appendix A collects eight, all reproduced. Untagged-
  prescriptive-prose triage (`grep -E "\bwill \b|\bshall \b"`) returns **zero** bare future-promises; no
  F20 drift-class sentence found.
- **Model-name leakage.** `git grep` for hardcoded model ids in `skills/`, `supervisor/GOALS.md`,
  `README`, `getting-started` → **empty**. The §3 provider-agnostic doctrine has no contradicting stale
  surface.
- **Out-of-write-set edits (both in `0846d1c`).** `tests/test_receipts.py`: single-line `UNENFORCED`
  drop — **required** (spec now carries pinned receipts), journaled in the commit body, not collateral,
  test green. `knowledge/lessons.md`: `@@ -744,3 +744,9 @@` — **append-only respected** (6 lines added,
  0 prior lines altered), matches §12's claim that the tier-based/provider-agnostic addendum was recorded
  "per manager instruction". Both justified.
- **Vantage note on the task's native-substrate authority.** The brief describes native-substrate as
  carrying a "PARTIAL ratification 2026-07-23" with three dead-daemon claims tagged inline
  `RATIFICATION WITHHELD`. **No such state exists in this worktree at `0846d1c`:** `git grep WITHHELD`
  returns nothing repo-wide, `docs/OPERATOR-GATES.md:17` still lists native-substrate's 11 markers as an
  **open** gate (`- [ ]`), and `lessons.md#2026-07-23-operator-decisions` records the operator
  **deferring** all 11 ("Everything else deferred… native-substrate's 11 ratification markers"). The
  three-tier draft's characterisation — *"all `[PENDING OPERATOR RATIFICATION]`; this spec changes no
  verdict there"* — is therefore **accurate to the committed record**, and the WITHHELD-reliance sweep is
  clean. The discrepancy is in the task brief's premise, not the spec; siding with the committed record.

---

## 7. Verdict

The re-draft's factual base is reliable (32/32 receipts × two independent verifiers, both provably able
to fail; every cross-spec citation re-executed and exact), it answers all binding items 4–10 with no
silent narrowing, every operator requirement traces both directions, and it contradicts none of
claim-nonce / native-substrate / SPEC v3 / terminal-surface. The sole defect is a MINOR completeness gap
in §12's doc-sync list (S1).

**`fix-list(S1)`**

---
---

# Re-review — r2 (fix wave 1)

**Trigger:** manager re-review of fix wave 1, commit **`1a3d4e5`** on `mf/three-tier` ("close B1–B10 + S1"),
merged into `mf/tt-spec` fast-forward (docs-only: `three-tier-command.md` +337, and the merged break
verdict file). **Vantage:** worktree `C:\proga\fleet-mf-tt-spec`, branch `mf/tt-spec`, HEAD `1a3d4e5`.
Reviewer commit for this section = the r2 commit below. Receipts still pinned `235421e5`; `bin/fleet.py`
byte-identical pin→HEAD, so every line receipt is valid at both.

**r2 VERDICT: `sound`** — all eleven findings (break B1–B10 + spec S1) are substantively closed, no
spurious fix, no receipt broken, and the one question the manager flagged (does §10.4 quietly redefine
claim-nonce boot rule 1?) resolves **NO — it stays descriptive and files the guard as a claim-nonce
prerequisite**. One nit-grade residual (R1) recorded below; it is below the fix-list bar and does not
block the gate.

## r2.1 Receipts — 34/34, two independent verifiers, both provably able to fail

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md
pins resolved: 235421e56bfd328a7e913e519a1459ccf55918dc
34/34 receipts reproduce exactly (37 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md        # my own extractor, no shared code
34/34 blocks reproduce; 0 FAILED                                      (exit 0)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 20   # new B1 receipt @8522
  [FAIL] block 20 @ 235421e5: sed -n '8526,8531p' bin/fleet.py
33/34 blocks reproduce; 1 FAILED                                      (exit 1 — harness can fail)

$ py -3.10 -m pytest tests/test_receipts.py -q
13 passed
```
The +2 receipts (32→34) are the wave's new evidence: `@8522` (`name = f"sup|{successor_inc}|successor"`,
the B1 successor-name proof), `@826-827` (`CLAUDE_CODE_SESSION_ID` read, the B3 rotation-safe source),
and the `mail_sent` provenance triad `@3654/3710/3767` (B7) — net +2 after the pre-existing blocks. All
reproduce under both verifiers.

## r2.2 Per-finding disposition — 11 FIXED, 0 SPURIOUS

| # | Sev | Section rewritten | Disposition | Evidence I re-checked |
|---|---|---|---|---|
| **B1** | CRIT | §7.2 | **FIXED** | Exemption re-keyed from `name == "supervisor"` to *current live claim-holder under any name*. New receipt `@8522` proves the successor runs `sup\|<inc>\|successor` — a name-equality protected only gen-0. Predicate: roster-live **and** holds the claim. |
| **B2** | MAJOR | §11.2 | **FIXED** | Occupancy = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` (correct Anthropic three-way prompt split; all three fields present per native-substrate:129). The mis-cited `cache_read` "continuity" line is now correctly labelled a *continuity* signal, not occupancy. |
| **B3** | MAJOR | §11.2 | **FIXED** | Transcript resolved from the running process's own `CLAUDE_CODE_SESSION_ID` (receipt `@826-827`; daemon-set per native-substrate G4) — not stale `INCARNATION.session_id` (claim-nonce §4.5: sid writers are registry-only, never touch INCARNATION — verified), not an absent-mid-turn outcome record. Absent/stale ⇒ fail toward the band. |
| **B4** | MAJOR | §11.3 | **FIXED** | "Urgent" replaced by a fleet-readable predicate (*dispatched-not-yet-reconciled*); 200k is a **hard fleet refusal** (`spawn`/`send` decline new worker turns for a supervisor caller above `H`), not self-discretion. Reuses B3's rotation-safe read. |
| **B5** | MAJOR | §10.4 | **FIXED** | `kill` cannot self-release (claim-nonce §6.3 requires continuity, `--force` deleted — both verified). Two honest arms: graceful steer-self-release-then-stop, else documented bounded-freeze-then-seize + G10 tombstone. |
| **B6** | MAJOR | §10.4 | **FIXED — and stays descriptive (manager's question)** | See r2.3. |
| **B7** | MAJOR | §5.3 (new) | **FIXED** | Fork-divergence relocated to interface tier is stated; mitigation = caller-provenance warn on `send` (receipt: `mail_sent` records the *target* sid, not the caller); full prevention a scoped §13 non-goal (the human tier is claimless by design). |
| **B8** | MINOR | §3.3 | **FIXED** (see R1) | Pre-flight recommendation dropped — it needed the provider-env read §3.2 disclaims (`CLAUDE_CONFIG_DIR\|ANTHROPIC_` = 0). §13 adds the non-goal. |
| **B9** | MINOR | §7.2 | **FIXED** | Same live-claim-holder predicate adds a liveness term ⇒ a dead husk is no longer protected forever. B1/B9 = one fix, opposite directions. |
| **B10** | MINOR | §5.3 | **FIXED** | Send-only worker churn recorded as option-(b)'s accepted blind spot, priced upstream; §8 routing (not the nonce) bounds a zombie's blast radius. |
| **S1** | MINOR | §11.1 / §12 | **FIXED — not spurious** | Both surfaces I named in r1 now listed: `skills/fleet/SKILL.md:44` and `docs/SPEC.md:261`; §11.1 names all three band surfaces. Tree re-grep confirms **§12 is now exhaustive** for the live 300–500k surfaces (`supervisor.md:51`, `SKILL.md:44`, `SPEC.md:261`); historical artifacts (superpowers/plans, superpowers/specs, reviews/) correctly excluded. |

**No spurious fix.** Every fix is honestly scoped: each `[UNBUILT]` prescriptive claim still has a
no-match receipt at the pin (re-ran all seven Appendix-A greps + `stop_outcome cache_read` → **all 0**),
and no fix over-claims a shipped behaviour. No fix broke a receipt (34/34).

## r2.3 The B6 question, answered: §10.4 does NOT redefine claim-nonce boot rule 1

claim-nonce §6.1 rule 1 (`state == "released" ⇒ claim` fresh) is checked **ahead of** rule 2
(roster-liveness refuse) with **no roster-liveness precondition** — verified exact against the spec of
record. So a `release → stop` window leaves INCARNATION `released` while the old body is still
roster-live, and a `sup-boot` in that window takes a fresh claim beside a live predecessor: the
dual-live-body class. The manager's concern is whether the wave papers over this by rewriting the
claim-nonce boot order inside the three-tier spec (forbidden — three-tier is a *consumer*).

**It does not.** §10.4's B6 block:
1. States the window and the new automated occupants (v2 scheduled beat, `sup-spawn`, in-flight handoff
   successor) — analysis the earlier draft lacked.
2. Explicitly says *"This spec does not own the boot verdict order (claim-nonce does)"* and files the real
   fix as a **claim-nonce build-slice prerequisite** — *"`sup-boot` must not consume a `released` record
   whose `released_by_sid` is still roster-live — either rule 1 gains a roster-liveness precondition, or
   release+stop is made atomic"* — **exactly mirroring how §10.2 files the `FLEET_WORKER` refusal** as a
   claim-nonce prerequisite rather than building it here.
3. Adds only a **three-tier-caller-side interim gate** it legitimately owns: its own automated callers
   "must gate their own `sup-boot` on `released_by_sid not in live_sids`". This changes no shared
   function; it constrains three-tier's own call sites. `released_by_sid` is a real field of the released
   record (claim-nonce §6.3 post-release key set — verified), so the gate is implementable against
   claim-nonce's own schema, inventing nothing.

That is the correct disposition for a consumer spec: state the constraint, file the shared-function fix
upstream, guard your own callers in the interim. **No redefinition of claim-nonce.**

## r2.4 Contradiction sweep — re-run against the rewritten sections, clean

Every load-bearing claim-nonce / native-substrate / SPEC-v3 citation the wave *added* re-verified exact:
claim-nonce §4.2 five `_require_claim_holder` callers all `sup-*` (B7); §4.5 sid writers registry-only,
never touch INCARNATION (B3); §6.1 rule-1-ahead-of-rule-2, no liveness precondition (B6); §6.3
continuity-required + `--force` deleted + `released_by_sid` field (B5/B6); native-substrate G4
daemon-set sid (B3), :129 three cache fields (B2). SPEC §16.7 `one-live-session-per-name` correctly
noted as blocking a second `supervisor`-named spawn **but not** a differently-named `sup-boot` (B6) —
accurate. No contradiction introduced by the wave; §13 non-goals now fence B7 (interface-fork
prevention) and B8 (provider-env read) explicitly.

## r2.5 Residual (nit-grade, non-blocking)

**R1 — nit — §12:998 still frames the tier-resolution pre-flight as a live `[UNBUILT]` deliverable the
B8 fix demoted.** §12 line 998: *"if `sup-spawn` gains a namespace-aware pre-flight (§3.3 `[UNBUILT]`),
that how-to gains a supervisor row."* The B8 fix (§3.3:162–170) **dropped** the pre-flight recommendation
and §13:1015–1017 records *"No tier-resolution pre-flight in v1"*, arguing the boundary *against* it. The
`(§3.3 [UNBUILT])` cross-ref still resolves (§3.3:169 keeps the string, framed "argues against, not
for"), and 998's *"if … gains"* is conditional, so this is not a false claim — but it carries none of
§3.3's "argued-against / own-scope" caveat and reads as a live roadmap item. The B8 fix propagated to
§3.3 and §13 but not to §12's conditional note. **Fix:** soften 998 to match §13 (e.g. *"should a
future, separately-scoped pre-flight be built (§3.3 argues against it for v1) …"*). Strictly weaker than
r1's S1 (which was a concrete stale-surface omission); below the fix-list bar.

## r2.6 Standing checks, re-confirmed

Status still `drafting` (line 3); *"An author never promotes its own spec"* intact; write-set is the
spec only (the wave's `--stat` shows `three-tier-command.md` + the merged break verdict, no code edit);
WITHHELD-reliance sweep still clean (no `WITHHELD` repo-wide; native-substrate rows still PENDING; §4.1
accurate). B-dep (break lens) and my r1 substrate note agree: the beat backstop inherits the unratified
2.1.212/2.1.216 rows — an operator-ratification sequencing flag, not a spec defect.

## r2.7 Verdict

Fix wave 1 closes all eleven findings correctly, introduces no spurious fix, breaks no receipt, and —
the point the manager singled out — keeps §10.4 a faithful *consumer* of claim-nonce rather than a
redefiner of its boot order. The lone residual R1 is a nit-grade cross-reference the B8 fix left
un-propagated into §12, below the fix-list threshold.

**r2: `sound`** (disposition: B1–B10 + S1 all FIXED, 0 SPURIOUS; nit R1 recorded).

---
---

# Final gate — r3 (fix wave 2), narrow scope

**Trigger:** manager final gate on wave 2, commit **`4e540f8`** on `mf/three-tier` ("close ND1–ND3 + R1"),
merged into `mf/tt-spec` fast-forward (docs-only). **Vantage:** worktree `C:\proga\fleet-mf-tt-spec`,
branch `mf/tt-spec`, HEAD `4e540f8`. Receipts pinned `235421e5`; `bin/fleet.py` byte-identical pin→HEAD.

**r3 VERDICT: `sound`** — 39/39 receipts under two verifiers, zero regression, R1 closed as recommended,
ND1–ND3 sound and contradiction-free. Three of the four resurrected blocks moved **byte-identical**; the
fourth had its command **extended** (a verified strengthening, flagged below). One residual is filed —
**H1, against `tools/verify_receipts.py`, not against the spec** — with an executable claim so the
follow-up code task inherits a reproducible failure.

## r3.1 Receipts — 39/39

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md
39/39 receipts reproduce exactly (39 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md          # my own extractor
39/39 blocks reproduce; 0 FAILED                                        (exit 0)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 5    → 38/39, 1 FAILED (exit 1)
$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md --seed 33   → 38/39, 1 FAILED (exit 1)

$ py -3.10 -m pytest tests/test_receipts.py -q
13 passed
```
Fenced blocks now equal receipts (39 = 39): every fenced block in the file is a parsed, verified receipt.

## r3.2 Zero-regression confirmation

- **Appendix-A no-match greps, all re-executed at the pin — all `0`:** `sup-spawn|cmd_sup_spawn`,
  `add_parser("beat")`, `RESERVED`, `NEEDS-OPERATOR|needs_operator|pending-decision|pending_decision`,
  `_doctor_check_supervisor_beat|supervisor-beat.jsonl|sup-context|sup-decision`,
  `CLAUDE_CONFIG_DIR|ANTHROPIC_`, `sup-release|cmd_sup_release`, `SUPERVISOR_BODY_NAME`, and
  `cache_read` in `stop_outcome.py`. Every `[UNBUILT]` tag still has a live absence proof.
- **Status discipline:** line 3 still `**Status: `drafting`.**`; *"An author never promotes its own
  spec"* intact. No self-promotion.
- **Change surface is exactly the declared one.** The `1a3d4e5..4e540f8` spec diff is five hunks —
  §7.2, §10.4, §11.2, §11.3, §12. **§3.3 is untouched** (correct: R1 was a §12-side wording fix, and the
  B8 decision it defers to was already final).
- **Contradiction sweep on the deltas — clean.**
  - **ND1** (§11.3, the ceiling's supervisor-identity gate): the interface exemption is *required*, not
    a loosening. It follows from §3.1 (the interface tier is outside fleet's launch surface — fleet
    cannot hand it off, respawn or reset it) and from the operator record, which bands **the second tier
    only** (`lessons.md#2026-07-23-three-tier-inputs`: *"supervisor self-monitors context; band
    150–200k"*). A caller-agnostic refusal would have blocked the human's only steering verb with no
    recourse. It also **unifies** identity: one `CLAUDE_CODE_SESSION_ID` vs `INCARNATION` resolution now
    serves B1 (archive exemption), B3 (occupancy read) and ND1 (ceiling gate) — three consumers, one
    concept, no divergence to contradict.
  - **ND2** (§11.3, past-`H` reconcile is read-only): decidable, and its escape-hatch claim is accurate —
    *"the handoff dispatch hand-rolls its own argv and routes through neither `cmd_spawn` nor
    `dispatch_bg`"* matches §10.1's shipped-code finding (verified in r1), so a `spawn`/`send`-scoped
    ceiling cannot deadlock the handoff it exists to force.
  - **ND3** (§10.4, bounded `T_release`): the precedent receipt `@7919`
    (`SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300.0`) reproduces; arm 1 always falls through to arm 2 on
    timeout or immediate `send` refusal, announcing which arm — so §10.4's kill can no longer hang. Arm 2's
    header correctly gained *"/ arm-1 timed out"*. Consistent with §4.3's G9 `send` refusal.
  - **R1** (§12): closed exactly as r2.5 recommended — the longcat bullet now reads *"only if … ever
    built as **separate scope** — which §3.3 argues *against* for v1 … and §13 records as a non-goal …
    **not** a live `[UNBUILT]` deliverable of this slice."* Matches §13:1068. Residual discharged.
  - **B6 disposition unchanged and re-confirmed:** §10.4 still files the boot-rule-1 guard as a
    claim-nonce build-slice prerequisite and still redefines nothing.

## r3.3 The four resurrected blocks — content audit vs `1a3d4e5`

Method: extracted every receipt-shaped fenced block from **both** revisions with an *lstrip-aware*
parser (strips `> ` blockquote markers and list indentation), then compared command→expected pairs.
Wave-1 lstrip-aware census = **38** receipt-shaped blocks against the 34 `verify_receipts` reported ⇒
**exactly 4 hidden**, matching the commit's claim. Located at wave-1 lines **520** (§7.2, `> `
blockquoted), **784** (§10.4), **910** (§11.2), **955** (§11.3) — the last three list-indented.

| # | Block | Verdict |
|---|---|---|
| §7.2 | `sed -n '8522p'` → `    name = f"sup\|{successor_inc}\|successor"` | **Byte-identical.** Diff is a pure dedent: every line matches modulo the `> ` prefix. No semantic change. |
| §10.4 | `grep -c "sup-release\|cmd_sup_release"` → `0` | **Byte-identical.** |
| §11.2 | `sed -n '826,827p'` → `    sid = os.environ.get(...)` | **Byte-identical to source.** Wave 1 carried 2-space list indent + the code's own 4 spaces (6 total); wave 2 at column 0 carries 4 — which is exactly `bin/fleet.py`'s real indentation at the pin (verified directly). *(My first-pass comparator flagged this; the flag was my own normaliser's blanket 2-space strip, not a content edit. Recorded because a false positive I raised is mine to retract explicitly.)* |
| §11.3 | `grep -c "sup-context\|supervisor-beat.jsonl\|_doctor_check_supervisor_beat"` **→ extended with** `\|SUPERVISOR_BODY_NAME` | **CONTENT CHANGED — a verified strengthening, not a weakening.** The alternation is a strict superset and the extended form independently returns `0` at the pin (re-executed). It is *purposeful*: ND1 introduced the caller-identity concept, and the block's own lead-in now reads *"neither the ceiling **nor the identity concept it must be gated on** exists today"* — the receipt was widened to prove that second claim. **Flagged for the record:** the commit message describes this operation as *"All moved to column 0"* and does not disclose that one command was also edited. Benign here (superset, still `0`, justified by adjacent prose), but a move-and-edit in one step is the shape under which a weakening would hide. |

**Net:** wave-1 38 → wave-2 39 receipt-shaped blocks = +1, the new ND3 `@7919`. No block was removed,
none weakened, none silently fixed-up to make a failing claim pass.

## r3.4 H1 — FILED RESIDUAL (against `tools/verify_receipts.py`) — the class is real, and worse than stated

**Claim:** `verify_receipts.py` cannot see receipt-shaped blocks that are indented or blockquoted, and
**fails open** — they are silently skipped, so an unverified claim shaped like a receipt reads as
verified. Line receipts at HEAD:

```
$ grep -n 'startswith' tools/verify_receipts.py
228:        if raw.lstrip().startswith("```")     <- fence detection DOES lstrip
250:        if raw.startswith("# at ")            <- pin match does NOT lstrip
255:        if raw.startswith("$ ")               <- command match does NOT lstrip
```
plus the docstring at `:38` — *"Blocks with no `$ ` line (quoted prose, journal entries) are skipped."*

**That asymmetry produces two distinct failure modes, not one:**
- **(a) List-indented block** — the fence *is* detected (`:228` lstrips) but `# at`/`$ ` are not
  (`:250`/`:255`), so the block is counted in the fenced-block census yet skipped as prose.
- **(b) Blockquoted block** — `"> ```".lstrip()` is still `"> ```"`, which does **not**
  `startswith("```")`, so **the fence is never detected at all**: the block is invisible, absent even
  from the census.

**Executable proof** (run at HEAD, on a document holding one TRUE column-0 receipt plus **two
deliberately FALSE** receipts — one list-indented `99999-THIS-IS-FALSE`, one blockquoted
`88888-ALSO-FALSE`):

```
$ py -3.13 tools/verify_receipts.py --strict gapdemo.md
pins resolved: 235421e56bfd328a7e913e519a1459ccf55918dc
1/1 receipts reproduce exactly (2 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)
EXIT: 0
```
Both false receipts pass. Exit 0. `0 unclassified, 0 FAILED`. And the census reports **2** fenced blocks
where **3** exist — mode (b) erasing the blockquoted one.

**Corroborated by the real document's own arithmetic:** wave 1 reported *"37 fenced blocks, 34
receipts"*; the lstrip-aware census is 38. `34` column-0 + `3` list-indented (counted as fences, skipped
— mode (a)) = **37** ✓, plus `1` blockquoted (invisible — mode (b)) = **38** ✓. The live document
exercised both modes simultaneously.

**Why it matters:** the tool's own green line is the false assurance — `0 unclassified` is precisely the
signal an operator reads as "nothing escaped". `tests/test_receipts.py` inherits the same blindness, so
the enforced test cannot catch it either. **And the repo rule is already being violated:** CLAUDE.md
binds *"A receipt the harness cannot classify is a failure, never a skip."* An indented receipt is a
receipt the harness cannot classify, and it is skipped — so the fix has a standing rule behind it, not
just a preference.

**Fix direction for the follow-up code task:** dedent (strip leading `> ` markers and whitespace) before
the `# at ` / `$ ` matches so they agree with `:228`'s fence handling; **and** fail closed — any fenced
block whose *dedented* first line matches `# at ` but which is not parsed must be reported
**unclassified**, never skipped. Ship it with a seed test asserting that an indented **and** a
blockquoted false receipt each turn the run red.

**Honest disclosure — my own harness shares the blind spot.** `indep_receipts.py` matches
```` ```\n# at ```` at column 0, so it also reported 34/34 in r2 and did **not** independently catch the
four hidden blocks; the wave-2 author self-found them. Two independently-written verifiers agreeing
proved nothing here, because independence of *implementation* did not buy independence of *parsing
assumption*. That is the sharper lesson for the follow-up task than the parser bug itself, and it is why
H1 is worth fixing in the shared tool rather than worked around per-document.

## r3.5 Verdict

Wave 2 closes ND1–ND3 and R1 correctly, regresses nothing (39/39 receipts, all absence proofs still `0`,
Status intact, change surface exactly as declared), and the contradiction sweep on the four touched
sections is clean — ND1's interface exemption in particular is required by §3.1 and the operator record
rather than a loosening. Three of four resurrected blocks moved byte-identical; the fourth's command was
extended into a verified superset, which I flag as a process note (move-and-edit in one step) rather than
a defect. The spec file is now fully parsed: 39 fenced blocks, 39 receipts, zero unclassified.

**The one open item is tooling, not the spec:** H1 is filed against `tools/verify_receipts.py` with a
reproducible red case, so the follow-up code task inherits an executable claim rather than a description.

**r3: `sound`** (spec). **H1 filed** (harness, follow-up code task).

---
---

# Re-gate — r4 (wave 3: operator amendments), narrow scope

**Trigger:** manager re-gate of wave 3, commit **`8a089bf`** on `mf/three-tier` ("operator amendments —
top tier, fallback chain, worker band, cap doctrine"), merged into `mf/tt-spec` fast-forward.
**Vantage:** worktree `C:\proga\fleet-mf-tt-spec`, branch `mf/tt-spec`, HEAD `8a089bf`. Pinned receipts
still `235421e5`; one receipt is deliberately `# live:`.

**r4 VERDICT: `fix-list(W1)`** — 46/46 receipts (all 7 new ones hand-executed), the worker-band sweep is
complete, every `[UNBUILT]` absence proof still holds, Status discipline intact, and the §3.1/§3.5/§11.4
amendments quote-match their in-tree authority. **One MAJOR finding (W1): §11.5's load-bearing operator
ruling is cited to a record that has not landed in this branch, and the anchor it cites still carries
the contradicting predecessor text.** The ruling is genuine — it exists on `main` — so W1 is a
merge-ordering defect, mechanically fixable, not a fabrication.

## r4.1 Receipts — 46/46, and all 7 new ones hand-executed

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md
46/46 receipts reproduce exactly (46 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md     # 45 pinned; `# live:` is outside its grammar
45/45 blocks reproduce; 0 FAILED                                   (exit 0)
$ … --seed 40  → 44/45, 1 FAILED (exit 1)
$ … --seed 12  → 44/45, 1 FAILED (exit 1)

$ py -3.10 -m pytest tests/test_receipts.py -q
13 passed
```
Receipt-command set diffed r3→r4: **exactly 7 added, 0 removed.** Each hand-executed by me — six against
the materialised pinned tree, one against the working tree — and **all seven match the pasted text
byte-for-byte**:

| # | Receipt | Hand-executed result | Match |
|---|---|---|---|
| 1 | `sed -n '858p' bin/fleet.py` | `        "token_ceiling": token_ceiling,` | ✓ |
| 2 | `sed -n '1284p' bin/fleet.py` | `    env["FLEET_WORKER"] = name` | ✓ |
| 3 | `sed -n '1635,1640p' bin/fleet.py` | 6 lines, `_limit_horizon_passed` docstring + null-horizon guard | ✓ |
| 4 | `sed -n '1920,1924p' bin/fleet.py` | 5 lines, limit scan → `status="limited"`, `limit_reset_at`, `limit_kind` | ✓ |
| 5 | `sed -n '3909,3912p' bin/fleet.py` | 4 lines, `dispatch_bg(... resume_sid=old_sid ...)` | ✓ |
| 6 | `sed -n '4367,4368p' bin/fleet.py` | 2 lines, `new_worker_record(None, cwd, …, model=model,` | ✓ |
| 7 | `grep -c "PENDING OPERATOR RATIFICATION" docs/specs/native-substrate.md` (`# live:`) | `0` | ✓ |

Receipt 7 is correctly classified `# live:` — *"ratification status is a property of the working tree,
not of this spec's pinned commit."* That is the right call, and it is the yardstick W1 fails.
No H1-class indented/quoted receipt blocks remain (`grep` for them returns none).

## r4.2 Amended-section contradiction sweep

- **§3.1 — supervisor promoted to TOP tier.** Quote-matches the in-tree Second addendum
  (`lessons.md:776`): the interface holds the *long-term goals*; the supervisor owns *solid plans,
  details, and splitting tasks*. No drift. The table's worker row moving from `third` to **`second or
  third`** is not a scope change but a forced re-derivation: the operator constraint is *"Opus and
  Sonnet only, never Haiku"*, and once the supervisor vacates second (Opus), `{Opus, Sonnet}` **is**
  `{second, third}`. Coherent.
- **§3.5 — preference chain.** Quote-matches: *"the top tier's usage limit is roughly **half** the
  standard limit"*, chain `[top, second]`, falls back when the top tier's limit is hit, returns once the
  reset horizon passes, built on the shipped G11/`limited`/`resume-limited` machinery. The addendum
  reserved the mechanism to the spec (*"the exact mechanism is the spec's call and goes through the
  gate"*), and §3.5 supplies it with receipts 3–6 rather than asserting it.
- **§11.4 + ND1 rebase — sound, and it closes a dependency the worker extension would have broken.**
  ND1's interface exemption was previously justified by *"the operator set the band for the second tier
  only"*. Extending the band to workers invalidates that basis, and §11.3's restatement retires it
  explicitly, rebasing onto **recourse and dispatch**: (a) the interface is outside fleet's launch
  surface so a refusal it cannot escape has no remedy; (b) workers observe the band but never call
  `spawn`/`send`, so there is nothing to refuse — their arm is respawn-at-task-boundary. The exemption
  survives on a durable basis rather than a retired one.
- **§4.1 — ratification correction is accurate.** Live tree: `RATIFIED 2026-07-23` ×8,
  `RATIFICATION WITHHELD` ×5, `PENDING OPERATOR RATIFICATION` ×0. The 5 WITHHELD hits are **3 inline
  claim markers** (G12's dead-daemon `rm` message `:46`, the `stop` twin `:151`, the
  rm/stop-do-not-revive sentence `:146`) plus 2 prose references (`:3`, `:170`) — so **8 ratified + 3
  withheld = 11 markers**, exactly the operator record. §4.1 names those three correctly and shows none
  is load-bearing (it leans on the transient-daemon idle-exit, `cause=upgrade`, G7, the 2.1.216 wedge,
  G10 — all ratified). My r1 vantage note is hereby superseded: the WITHHELD state I recorded as absent
  has since genuinely landed.
- **§11.5 — cap doctrine: see W1.**

## r4.3 Worker-band sweep — COMPLETE

`grep -niE "second tier only|supervisors only|only the supervisor|second tier"` over the whole file
returns four hits, **all legitimate**, none a residual scoping:

| Line | Text | Verdict |
|---|---|---|
| 87 | *"The earlier draft put the supervisor **on the second tier**"* | historical contrast for the promotion |
| 196 | *"prefers the top tier and automatically falls back to the **second tier**"* | fallback-chain semantics |
| 1007 | *"every 'supervisor only' / '**second tier only**' scoping in the earlier draft [is retired]"* | the sweep statement itself |
| 1136 | quotes *"the operator set the band for the **second tier only**"* and marks it **retired** | the ND1 rebase |

No surviving second-tier-only band scoping anywhere in the file. Sweep verified complete.

## r4.4 `[UNBUILT]` tags and Status discipline

All eight Appendix-A absence greps re-executed at the pin — `sup-spawn|cmd_sup_spawn`,
`add_parser("beat")`, `RESERVED`, `NEEDS-OPERATOR|…|pending_decision`,
`_doctor_check_supervisor_beat|supervisor-beat.jsonl|sup-context|sup-decision`,
`CLAUDE_CONFIG_DIR|ANTHROPIC_`, `sup-release|cmd_sup_release`, `SUPERVISOR_BODY_NAME` — **all `0`**.
Every `[UNBUILT]` tag still has a live absence proof. Status line still `**Status: `drafting`.**`;
*"An author never promotes its own spec"* intact.

## r4.5 W1 — MAJOR — §11.5 cites an operator ruling that has not landed in this branch, while the cited anchor asserts the opposite

**The claim.** §11.5 is titled *"Reconciliation with the third-docket cap doctrine — **SETTLED**
(operator ruling, 2026-07-23)"*, states *"**This is decided, not pending.** The manager's reading was put
to the operator and **confirmed** (`knowledge/lessons.md#2026-07-23-three-tier-inputs`, third addendum,
2026-07-23)"*, and block-quotes a **Third addendum**.

**At this commit, that citation does not resolve — and the anchor contradicts it.**
```
$ git grep -n "Third addendum"
docs/specs/three-tier-command.md:1248:> **Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** …
```
The only occurrence in the tracked tree is **the spec quoting itself**. `knowledge/lessons.md` is 781
lines and the cited entry ends at the **Second addendum**, whose final bullet reads, verbatim:

> **Manager reading of the cap doctrine vs the spec's B4 hard arm:** … Wave 3 states this reading
> in-spec; **the operator rules on it at ratification.**

So the tree says *pending an operator ruling at ratification* exactly where the spec says *settled*.

**The ruling is genuine — this is not a fabrication.** It exists on `main`:
```
$ git log -1 --format='%h %ci %s' 7d68b43
7d68b43 2026-07-23 06:32:47 +0500 docs(knowledge): operator ruling — spend caps flag-gated off, context band stays
$ git show 7d68b43:knowledge/lessons.md | sed -n '783p'
**Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — … Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before ratification.
```
The spec's quote is **faithful**, eliding only that closing sentence. The defect is purely that the
record was never merged:
```
$ git merge-base --is-ancestor 7d68b43 HEAD   → false (not an ancestor)
$ git log --oneline HEAD..main
f97fdc7  docs: ledger — wave 3 + H1 landed, re-gate + H1 review dispatched
7d68b43  docs(knowledge): operator ruling — spend caps flag-gated off, context band stays
ba5b415  docs: ledger — final gate sound, merge landed, wave 3 + H1 dispatched
```
The ruling (06:32:47) predates the wave-3 spec commit `8a089bf` (06:35:23) by under three minutes; the
author quoted it accurately but did not merge `main` to bring it into the branch.

**Why this is MAJOR rather than cosmetic.** On the strength of this citation the wave **deleted the
spec's own fallback**: *"the earlier draft's contingency branch ('if the operator rules the other way,
the band becomes advisory') is **withdrawn**, since the operator ruled."* A claims audit performed at
this commit — which is what a design gate is — finds a load-bearing status flip and a withdrawn
contingency resting on evidence that is absent from the tree and contradicted by the anchor cited. That
is precisely the failure mode this repo's receipt doctrine exists to prevent: *a pasted claim is a claim
until something re-runs it.*

**And this wave already knew the right discipline for this exact class.** §4.1's ratification status is
receipted `# live:` **because** *"ratification status is a property of the working tree, not of this
spec's pinned commit."* An operator ruling recorded in `lessons.md` is the same class of claim — a
working-tree property, not a pinned-commit property — and it received neither a `# live:` receipt nor a
landed record. The wave applied the correct standard to one such claim and not to the other.

**Fix (mechanical, no rewrite):** merge `main` into `mf/three-tier` so `7d68b43` lands alongside the
spec that depends on it, and re-run the gate. Optionally restore the elided closing sentence
(*"Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before ratification"*), since that is the clause
tying the ruling to the flag it discharges. Once merged, §11.5's "SETTLED" framing is fully supported
and no other text needs to change — a `# live:` receipt on the addendum's presence would make it
self-verifying.

## r4.6 Verdict

Wave 3 folds four operator amendments cleanly: the top-tier promotion and preference chain quote-match
their authority, the worker-band extension is swept through the whole file with no residual second-tier
scoping, ND1's exemption is rebased onto a basis that survives that extension, §4.1's ratification
correction is accurate to the marker counts, and the receipt base grew by exactly seven blocks — every
one of which I hand-executed and matched. Nothing regressed.

The single defect is W1: the wave's most consequential status change — *pending operator ruling* →
*settled doctrine*, with a contingency branch withdrawn on the strength of it — is cited to a record
sitting three commits away on `main` and absent from the branch, whose in-tree anchor still says the
opposite. The ruling is real; the merge is missing. One `git merge` closes it.

**r4: `fix-list(W1)`.**

---
---

# Final confirmation — r5 (wave 4), very narrow scope

**Trigger:** manager final confirmation on wave 4, commit **`d9c4a6f`** on `mf/three-tier` ("close
ND5/W1, ND6, ND7"), merged into `mf/tt-spec` fast-forward. **Vantage:** worktree
`C:\proga\fleet-mf-tt-spec`, branch `mf/tt-spec`, HEAD `d9c4a6f`. Pinned receipts `235421e5`; two
receipts deliberately `# live:`.

**r5 VERDICT: `fix-list(R2)`** — **W1 is FIXED** and fixed at the root; 50/50 receipts with all four new
ones hand-executed; Status discipline intact. The renumber audit the manager asked for surfaced one
MINOR stale cross-reference (R2). Nothing else regressed.

## r5.1 W1 — FIXED, at the root, and self-verifying

The r4 defect was that §11.5 declared the cap-doctrine ruling SETTLED while the third addendum recording
it existed only on `main`. Both halves are now closed:

**The record landed.**
```
$ git merge-base --is-ancestor 7d68b43 HEAD   → true (ancestor)
$ grep -n "Third addendum" knowledge/lessons.md
783:**Third addendum (2026-07-23, operator ruling on the cap-doctrine reading):** confirmed — …
```
`HEAD..main` now holds only two ledger commits (`8999905`, `c2b7853`) — no outstanding authority.

**Quote-match against the in-tree anchor — exact.** I diffed §11.5's block quote against
`knowledge/lessons.md:783` word for word:

| | Text |
|---|---|
| **In-tree `lessons.md:783`** | *"confirmed — **cost/spend ceilings are gone unless the counting flag puts them back** (flag default off; enabling it may re-arm spend caps). The context band (150–200k, supervisors AND workers) is a freshness mechanism, not a budget, and its enforcement stays. Resolves the `[OPERATOR RULES AT RATIFICATION]` flag before ratification."* |
| **§11.5 block quote** | identical, verbatim — **including the closing sentence** that r4 flagged as elided |

The only divergence is markdown emphasis (the spec bolds the final sentence); **no word differs, nothing
is added, nothing omitted**. The clause tying the ruling to the flag it discharges is restored, which was
r4's specific fix suggestion.

**The citation is now self-verifying**, and correctly classified — the receipt greps the addendum's exact
string out of the working tree, with a `# live:` reason that names the right class:
```
# live: a claim about the working tree's recorded operator decisions, not about this spec's pinned commit
$ grep -c "Third addendum (2026-07-23, operator ruling on the cap-doctrine reading)" knowledge/lessons.md
1
```
Hand-executed by me: `1`. This is precisely the discipline r4 said was owed — the same standard §4.1
already applied to ratification status, now applied to the operator ruling.

**And the sequence is recorded rather than repaired away.** §11.5 carries a wave-4 note stating that
wave 3 wrote the section SETTLED while the addendum existed only on `main`, *"so for one wave this spec
was the sole witness to a ruling that binds it — correctly caught as ND5/W1."* The spec keeps the
history instead of presenting a clean face. That is the right disposition: the defect was real, the
ruling was genuine, and both facts survive in the document. **W1 closed.**

## r5.2 Receipts — 50/50, all four new ones hand-executed

```
$ py -3.13 tools/verify_receipts.py --self-test --strict docs/specs/three-tier-command.md
50/50 receipts reproduce exactly (50 fenced blocks, 0 unclassified, 0 volatile-skipped, 0 warned, 0 FAILED)

$ py -3.13 indep_receipts.py docs/specs/three-tier-command.md      # 48 pinned; the two `# live:` are outside its grammar
48/48 blocks reproduce; 0 FAILED                                    (exit 0)
$ … --seed 22  → 47/48, 1 FAILED (exit 1)

$ py -3.10 -m pytest tests/test_receipts.py -q
13 passed
```
Command-set diff r4→r5: **exactly 4 added, 0 removed** (46→50; 48 pinned + 2 `# live:`). All four
hand-executed by me, all matching the pasted text byte-for-byte:

| # | Receipt | Hand-executed result | Match |
|---|---|---|---|
| 1 | `sed -n '2162p' bin/fleet.py` | `            "resume_eligible": status == "limited" and _limit_reset_passed(rec),` | ✓ |
| 2 | `sed -n '3681,3687p' bin/fleet.py` | 7 lines — the `limited` park refusal, *"never steer a parked worker"* | ✓ |
| 3 | `sed -n '8492p' bin/fleet.py` | `        claim, caller = _require_claim_holder(getattr(args, "sid", None))` | ✓ |
| 4 | `grep -c "Third addendum (…)" knowledge/lessons.md` (`# live:`) | `1` | ✓ |

Receipts 2 and 3 are the pair that makes ND6 a *receipted* design defect rather than an assertion: the
handoff ritual requires the claim holder (`@8492`), while the chain's only trigger parks the body
`limited`, after which `send` refuses it a turn outright (`@3681-3687`). The two together prove the
earlier draft mandated a ritual its own trigger makes impossible. No `[UNBUILT]` absence proof
regressed — all nine greps still `0` at the pin, including the new `tier_preferred|tier_current`.

## r5.3 §3.5.3 / §3.5.4 renumber cross-ref audit

Wave 4 inserted a new **§3.5.3** (ND6, outside-driven fallback) and pushed the band-interaction section
to **§3.5.4**. Every `§3.5.x` reference in the file, checked against its r4 referent:

| Line | Ref | r4 referent | Correct at HEAD? |
|---|---|---|---|
| 236 | `§3.5.4's band interaction` | was `§3.5.3` (band) | ✓ **correctly renumbered** |
| 281 | `See §3.5.3` (outside-driven dispatch) | new text | ✓ |
| **286** | `next body change (§3.5.3) is dispatched` | was `§3.5.3` = **band interaction** | ✗ **R2 — see below** |
| 405 | `§3.5.1` fresh context | unchanged | ✓ |
| 415 | `cannot act at all (§3.5.3)` | new text | ✓ |
| 1345 | `§3.5.1's receipt` | unchanged | ✓ |
| 1445 / 1449 / 1450 | `§3.5.3(c)`, `(§3.5.3)`, `§3.5.3(b)` | new text; §3.5.3 does carry (a)/(b)/(c) | ✓ |

Eight of nine resolve correctly, and the one that had to move (`:236`) was moved.

### R2 — MINOR — §3.5.2 step 3's "Return" cross-ref was not renumbered, and now points at a section whose scope excludes the case

**Quote (§3.5.2, step 3, line 286):**
> **Return.** Once `limit_reset_at` passes, the supervisor's *next* body change **(§3.5.3)** is
> dispatched at the preferred tier again.

At r4 this same sentence read `(§3.5.3)` when §3.5.3 was *"Interaction with the swap band"* — so it
pointed at the band/tier coordination that governs which body change happens and at which tier. The
sentence is byte-identical at HEAD, but §3.5.3 is now *"ND6 — the fallback cannot be performed BY the
parked body, so it is driven from outside"*. The referent changed silently under an untouched reference.

**Why the new target is wrong for this case.** §3.5.3 is scoped strictly to the **parked** body — its
whole premise is that the predecessor *"cannot act at all"*, which is why dispatch moves to the interface
tier. But step 3 describes the moment **after** `limit_reset_at` passes, when the body is by definition
**no longer parked**; and step 3 itself says the return *"is not itself a trigger for a body change — it
is a preference consulted at the next boundary that was going to happen anyway."* That boundary is the
band-triggered case, which §3.5.4 governs and explicitly handles both directions: *"a band handoff that
happens while the top tier is limited is dispatched at the fallback tier"* — the exact mirror of step 3's
return. A reader following `(§3.5.3)` lands on the outside-driven mechanism and finds a precondition
(parked predecessor) that cannot hold at return time.

**Severity MINOR:** no factual claim, receipt, or binding rule is affected — the sentence still reads
plausibly because §3.5.3 also concerns dispatch. It is a misdirected pointer, and precisely the hazard a
renumber audit exists to catch: the refs that *changed* were fixed, the ref that *stayed the same* was
not re-examined.

**Fix:** point step 3 at **§3.5.4** (its r4 meaning), or split the reference — tier selection §3.5.2,
ritual/coordination §3.5.4 — since §3.5.3 governs only the limit-triggered, parked-predecessor arm.

## r5.4 Standing checks

Status line still `**Status: `drafting`.**`; *"An author never promotes its own spec"* present (×1). No
H1-class indented or blockquoted receipt blocks (`grep` returns none) — wave 4 added receipts at column 0
throughout. All nine `[UNBUILT]` absence greps `0` at the pin. Write-set remains the spec file plus the
break-lens verdict and ledger docs; no code touched.

## r5.5 Verdict

Wave 4 closes W1 the right way: the missing authority was merged rather than argued around, the quote now
matches the in-tree anchor word for word with the previously-elided clause restored, the citation carries
a `# live:` receipt that makes it self-verifying, and a wave-4 note preserves the sequence instead of
erasing it. ND6's redesign is receipted at both ends (`@8492` and `@3681-3687`), which is what turns it
from an assertion into a demonstrated defect. Receipts grew by exactly four, every one hand-executed and
exact; nothing was removed and no absence proof regressed.

The single open item is R2, a stale `§3.5.3` pointer in §3.5.2's "Return" step that the renumber left
behind — one reference to repoint, no substantive text change.

**r5: `fix-list(R2)`.**
