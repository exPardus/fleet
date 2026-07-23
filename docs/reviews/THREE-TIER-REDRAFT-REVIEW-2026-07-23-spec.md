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
