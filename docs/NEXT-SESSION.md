# Next session — after M-D (merged + pushed, closed 2026-07-18)

Previous handoff (M-C) is superseded and closed. M-D campaign record: `knowledge/lessons.md#2026-07-18-md`. Supervisor journal has the blow-by-blow.

## State (all verified at close)

- **M-D shipped and pushed.** `main` = `fleet-impl`, pushed. Both code branches merged: `md/ulparser` (UL local-format horizon parser) and `md/contract` (claude 2.1.212 transient-daemon rehome). **1136 unit tests + 6-pin FLEET_LIVE tier green; doctor all-PASS; pin-gate stamped at claude 2.1.214.**
- **`docs/SPEC.md` v3 now binds MULTI-PLATFORM** (operator directive 2026-07-17, header + invariant 8): everything must work Win/macOS/Linux; the Windows box is the *reference*, not the only target. Known gaps enumerated in the header as in-scope (autoclean schtasks-only, attach Windows-only, POSIX adapter raises).
- **Vendor break handled:** claude went 2.1.211→2.1.212→2.1.214 across the campaign. 2.1.212 made the native daemon **transient** (idle-exits 5s after last client, no service install; `rm`/`stop` rc=1 is 3-way ambiguous; `agents --json` serves a stale roster). Fleet now classifies rm/stop by message not exit code, kills by captured roster id, surfaces starved husk sweeps to doctor. G-rows in `docs/specs/native-substrate.md` amended **`[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]`** — see "Operator gates open" below.
- **Token-efficiency clause** folded into campaign-template (v1.7) + spawn-etiquette: compressed tier-boundary messages, full-precision code/commits/specs/verdicts.
- Residual fleet: 4 idle `md-*` workers + `C:/proga/fleet-md-*` worktrees, plus the older `mc-*` set — **autoclean retires the workers on TTL; then the worktrees are removable** (`git worktree remove` + branch delete; `md/ulparser` + `md/contract` are merged, safe to delete; the `mc/*` branches too).

## Operator gates open (need Altai, not buildable without a decision)

1. **Ratify the 2.1.212 contract amendments** in `docs/specs/native-substrate.md` (the `[PENDING OPERATOR RATIFICATION]` G-rows). Three dead-daemon claims remain **manager-report-only** — both branch workers were `--bg` sessions and physically cannot observe the dead-daemon path (a bg session holds the daemon open). Capture them on a quiet machine from an interactive session: the manager's post-merge FLEET_LIVE run already exercised the hygiene path once green, but the raw dead-daemon `rm`/`stop` receipts want an operator's eyes. Findings: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q2 + operator items list.
2. **Three-tier command: RESTRUCTURE ratified by review, not yet by operator.** Both design-lens reviews returned `restructure` (same root cause: claim keyed on session_id, fork-steer rotates it → first beat breaks the claim). Binding merged 10-item list + sequencing: `docs/reviews/THREE-TIER-ADJUDICATION-2026-07-17.md`. Nothing is spec-ratified. **The gate promoted the per-body claim nonce to a hard prerequisite slice** — that is the next build-shaped M-E candidate, but it wants an operator green-light on the restructure first.

## The job: pick and run M-E

Priority-ordered:

1. **Claim-nonce spec slice** — draft written: `docs/specs/claim-nonce.md` (PROPOSAL, awaiting dual-lens review + operator ratification). (adjudication items 1–3, and it independently fixes the handoff-fork gap + the two claim warts found live this campaign: `sup-boot` refuses its own holder on a stale heartbeat, and can't distinguish an operator-authorized `claude stop` from a daemon restart → no `sup-release` verb). Spec task → dual-lens review → build **gated on operator ratification**. This unblocks a re-drafted three-tier.
2. **Two shipped-code defects surfaced by the design gate (grep-proven, small):** (a) `cmd_sup_handoff_begin` hand-rolls argv and bypasses `dispatch_bg`, so **successor supervisor sessions launch with no hooks** — SPEC §6 "one choke point" is inaccurate; fix + SPEC correction. (b) `_autoclean_task_is_ours` matches fleet.py path only → voids the F4 guard the moment a second scheduled task exists (latent until three-tier adds `--supervisor-beat`). Both are small reviewed fix tasks.
3. **ND-4 + nits** from the contract review (`docs/reviews/MD-CONTRACT-REVIEW-2026-07-17.md` RE-REVIEW 2): ND-4 (the `_daemon_alive` gate re-introduces a narrow false-SKIP window, test-only) + n2/n3/n4 comment-vs-code nits. Cheap, fold into (2)'s wave.
4. **Dogfood outward** (standing goal 5): overdue — last external run was stupidbox 2026-07-09. A non-fleet campaign is the highest-value defect report.
5. **UL parser follow-ups** (ulparser review D1–D4, non-blocking) + the now-vestigial wall-clock default at `_parse_limit_signal`'s helper (make `now` required to kill the latent footgun). Cheap.

## Standing rules (unchanged, they keep earning it)

- CLAUDE.md binds (py -3.13; forward slashes in hook commands; no Git-Bash `&`; views read-only). On Windows post-restart the Git-Bash PATH can come up broken — call `py -3.13 bin/fleet.py` directly + `export PATH=/usr/bin:/bin:/mingw64/bin` in Bash.
- **Run the live pin tier on every `claude` version bump, not just at merge** (v1.7 vendor-bump gate) — the 8th live catch was a vendor change, invisible to a review-clean tree. **State the probe context** in any daemon-lifecycle finding: a `--bg` worker cannot observe the dead-daemon path; the manager's interactive post-merge FLEET_LIVE run is the standing verification.
- Adversarial+spec review pairs on every branch; **new-defect hunt on every fix wave** (fired 4/4 waves in M-D); grep-receipt gate on every enumeration; no author promotes its own spec; **ESCALATE beats a 3rd fix wave** (held — both branches closed in 2 waves + final gate).
- `git log` is the only truth a turn landed (529/403/restart all freeze cost+journal). `fleet wait ... run_in_background` dies on session teardown with no marker — a Monitor until-loop survives better.
- Push `fleet-impl` + ff `main` at every green milestone. Supervisor GOALS.md binds the manager (frugality, long beats, 300–500k handoff band). **Claim wart:** after a >60m heartbeat gap, `sup-boot` refuses the same-sid holder — recover with `sup-heartbeat` (doesn't gate on staleness), not `sup-boot`, until the nonce lands.
