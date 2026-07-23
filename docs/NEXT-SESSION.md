# Next session — after the M-F re-draft campaign (closed 2026-07-23)

Previous handoff (M-E + reconcile) is superseded and closed; its still-live residuals are carried in §"Residuals" below, re-verified where noted. Campaign records: `knowledge/lessons.md#2026-07-23-three-tier-ratified` (this campaign), `#2026-07-23-operator-decisions` / `-council` / `-caps` (the three dockets). The ledger (`docs/PLAN-PROGRESS.md`) has every wave and verdict; the supervisor journal has the blow-by-blow.

---

# FIRST ACTION — dispatch M-F dogfood; there is no docket bottleneck this time

**Every operator gate is closed except one low-urgency item** (`docs/specs/providers.md` re-base-or-park — parked by the operator until the providers line next moves; do not surface it as a blocker). The startup ritual's gate read will show exactly that one open box. Do not manufacture a docket.

The operator has already decided the sequencing (all dated in lessons, all ticked in `docs/OPERATOR-GATES.md`):

1. **M-F dogfood-outward run PREEMPTS everything** — unblocked to dispatch, overdue since stupidbox 2026-07-09. **No budget envelope exists and none is owed**: cap doctrine (third docket) says no fleet-enforced token/USD ceilings for anyone; the plan's own limits cap workers and managers, limit-park/resume is the recovery path. Discipline is structural: small worker count, the 150–200k context band (binds workers AND supervisors), escalate on anomaly. Your first-turn asks to the operator are only: **which external project**, and anything project-specific — not budget, not permission to start.
2. **Then the claim-nonce build slice** (spec-of-record, gate = option (b)). Its build backlog is enumerated in §"Residuals" items 1–2.
3. **Then the three-tier build** on the ratified spec. SDD v4 is build-ready and also waits on an M-F-adjacent slot (R1 sequences Phase 1 first, `sdd.enabled` default off).
4. **fleet-index M1 is fully unblocked but queued behind M-F** — deliberately, because the dogfood run generates the read-duplication data that tests its economics. When M-F closes, bring M1's evidence question back to the operator with the fresh data.

## State (all verified at close, 2026-07-23)

- **Everything is on `main` and pushed** (`02bf5f7` + the ratification/knowledge commits after it; `git log` is the truth). No feature branches remain (`mf/*` all merged and deleted).
- **Specs of record now:** `docs/specs/claim-nonce.md` (ratified, §7 = option (b)); **`docs/specs/three-tier-command.md` (RATIFIED 2026-07-23)** — interface tier at top model tier holds long-term goals; supervisor at TOP tier owns plans/task-splitting with a usage-limit fallback chain to second tier (limit-arm honestly lossy; doctrine: hand off on the band BEFORE the limit); 150–200k band binds supervisors and workers; tier-based provider-agnostic role→model resolver; cost caps flag-gated off. `docs/specs/native-substrate.md` is PARTIALLY ratified — three dead-daemon claims carry inline `RATIFICATION WITHHELD` pending a quiet-machine capture (the G9 probe).
- **Numbers:** unit suite **1420 passed / 8 skipped, identical on `py -3.13` and `py -3.10`**; `fleet doctor` all-PASS; `claude` **2.1.218**, pin tier 6/6 green interactive-vantage, `state/pin-pass.json` stamped 2.1.218 (10th vendor-bump exercise, no catch). `verify_receipts --self-test --strict`: three-tier 54/54 (0 warn), claim-nonce 58/59 (1 disclosed volatile mtime WARN).
- **The receipts harness is hardened (H1, this campaign):** `tools/verify_receipts.py` now ERRORS under `--strict` on any receipt-shaped text it cannot classify anywhere in a scanned file — gutters, tabs, tilde fences, inline `$ ` spans, stray directives, unterminated fences (the silent-drop class's third recurrence; founding artifact held 16 evasions where the review probe knew of 4). 20-mutation hostile review; every surviving mutation now has a named catching test. `tests/test_receipts.py` is 49 tests.
- **Historic test-count claims are noisy**: entries variously say 1383/1393/1403. Measured truth at close is 1420; the 1403 in the previous handoff was drift. Trust only a fresh run.
- **Registry:** 5 idle workers from this campaign (`threetier-draft`, `tt-review-break`, `tt-review-spec`, `h1-receipts`, `h1-review`) left to the autoclean TTL. Owner sid is this handoff's dead session — retiring them needs `--yes`, or just let autoclean take them.

## The job, priority-ordered

1. **Run M-F dogfood** (see FIRST ACTION). External friction is the highest-value defect report available (standing goal 5). Feed friction into `knowledge/` per the learning loop; the run doubles as fleet-index M1's evidence generator.
2. **Doc-sync owed by the ratified three-tier spec (§12 of the spec is the authoritative list)** — small, do early, it is the only place the repo still contradicts a ratified spec: `skills/fleet/supervisor.md:51` and `skills/fleet/SKILL.md:44` still say the 300–500k handoff band; `docs/SPEC.md:261` likewise; `supervisor/GOALS.md` still says "300–500k handoff band" and cheapest-capable-model doctrine that the ratified tier table supersedes (GOALS edits are OPERATOR-OWNED — propose via `sup-checkpoint --kind PROPOSAL`, never edit directly); plus the remaining §12 rows (autoclean.md, longcat doc, OPERATOR-GATES history note). Receipts for each edit; this is mechanical.
3. **Claim-nonce build slice** (after M-F per operator sequencing): the gate-(b) mechanism per the ratified spec, PLUS the build backlog in Residuals 1–2 below.
4. **Three-tier build slice** on the ratified spec — its `[UNBUILT]` inventory is Appendix A of the spec (tier resolver surfaces, band measurement, sup-spawn/reserved-name, gate state-file, beat verb deferred-v2).
5. **Point `verify_receipts.py` at `native-substrate.md`** (carried, still the highest-value unenforced doc — it is the vendor contract; now easier since H1 hardened the harness). Also still owed: the SPEC.md wholesale re-pin (a campaign, not an edit — every `@NNNN` anchor is ~4 milestones stale; the §0 banner says so honestly).
6. **C/soak framing retirement** (operator-decided, conditioned): re-home PLAN §0's still-binding doctrine (worktree isolation, W-V discipline, RESULT contract, dual-lens gates) to a live surface FIRST, then mark ROADMAP/PLAN superseded — never delete. Fold PLAN §0.4's ceiling-denomination retirement (cap doctrine) into the same pass.

## Residuals (carried, verified-still-true unless struck)

1. **Claim-nonce build backlog:** (a) three MINOR residuals from its final break gate (`a0bd194` — §6.1 roster precondition's missing `else` lands as a `KeyError` on the shipped rc map, plus two smaller); (b) `supervisor/INCARNATION.tmp` + `HANDSHAKE.tmp` not gitignored; (c) exit-code contract says 0/2/3, code has a 4 with no seam.
2. **Three prerequisites filed by the three-tier gates against the nonce build** (disclosed at ratification, gate the BUILD): B6's boot-rule-1 guard (release→stop two-live-body window), the `FLEET_WORKER` refusal arm, the `limited`-holder transfer branch.
3. **Dispatch residuals, both LOW, from M-E theirs' final gate** (re-verified 2026-07-23 in the prior handoff): (a) `_join_roster_by_short_id` roster-blackout returns `None` = live worker reads as join failure; (b) `cmd_sup_handoff_begin` name-join same shape → false `successor-doa` on blackout. Plus the reconcile's husk-binding LOW (name-join drops the life-signal requirement).
4. **`autoclean_task_remove` deletes by task name with no ownership predicate** (creation side is guarded, removal is not).
5. **M-E gate residuals**: nonce break-lens F1/F3 (fleet-clean double standard; "stops" = two-TTL bound); spec-lens F3's three latent harness gaps (partially closed by H1 — re-audit which remain); me/defects G1 lint candidate.
6. **H1 review's out-of-scope finding**: `docs/specs/portability.md:334` carries an unpinned receipt; file is UNENFORCED so nothing runs it. Reviewer recommends demoting the block (or pin + enforce the file). One-commit fix.
7. **macOS remains developed-on but unreceipted** — one `pytest -q` tail from the port author's macOS box closes the last platform. Ask.
8. **Worktree directories locked at close**: `C:\proga\fleet-mf-{threetier,tt-break,tt-spec,h1,h1-review}` — `git worktree remove` hit Permission denied (idle worker sessions hold the cwds). Branches are deleted. After autoclean retires the workers (or post-reboot): `git worktree remove` each, then `git worktree prune`.

## Standing rules (updated where this campaign moved them)

- CLAUDE.md binds (forward slashes in hooks; no Git-Bash `&`; views read-only; receipts re-executed and now shape-audited by `tools/verify_receipts.py`). Floor is `fleet.MIN_PYTHON_VERSION` (3.10) — run changes at it, not only 3.13. Post-restart Git-Bash PATH fix: `export PATH=/usr/bin:/bin:/mingw64/bin`.
- **Campaign template is v1.9** — new this campaign: **RULING-LANDS-FIRST** (a binding operator ruling is citable only once its dated record is a commit on the branch the citing wave writes to; a mid-turn steer is delivery, never provenance — violating this was a manager-owned CRITICAL that reversed a fit-for-ratification verdict); **mutation-test any detector you harden** (H1's own suite survived 6/20 mutations until forced); **operator-amendment waves don't burn the ≤3 reviewer-wave escalation budget** — say so in the brief.
- **Cap doctrine (operator, binding):** no `--token-ceiling`/USD caps on spawns; counting is a default-off flag; plan limits + limit-park/resume are the cost control. **Context band 150–200k binds workers and supervisors** — hand off/respawn at the next task boundary after entering the band; never ride to the limit (the fallback chain's limit-arm is lossy by design and says so).
- Run the live pin tier on every `claude` bump (10 exercises, 9 catches); state probe context AND vantage on every receipt; founding-incident replay before believing any detector; adversarial + spec lens pairs with new-defect hunts on every wave (now fired 8/8 lifetime); disputes carry receipts both directions; no author promotes its own spec — ratification is the operator's act, recorded as a dated lessons line FIRST, Status flip second.
- `git log` is the only truth a turn landed. Push `main` at every green milestone.
- **Claim wart, still live until the nonce ships:** after a >60m heartbeat gap `sup-boot` refuses the same-sid holder — recover with `sup-heartbeat`. The claim at close is held by incarnation `inc-20260722T233021Z-815c` (this handoff's dead session); a fresh session's `sup-boot` on a stale heartbeat should seize normally — if it refuses citing a live roster entry for the dead sid, that is the known wart class: verify the sid is genuinely dead (`state/events.jsonl` + roster), then seize per supervisor.md, never mass-respawn.
