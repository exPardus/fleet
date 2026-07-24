# Next session — after the overnight+day autonomous run (closed 2026-07-24)

Previous handoff (post-M-F-re-draft) is fully executed and superseded. This run's complete record: `docs/OVERNIGHT-2026-07-23.md` (council ledger + friction log + TL;DR), `knowledge/lessons.md#2026-07-23-overnight-dogfood` and `#2026-07-24-day2` (campaign lessons), supervisor journal (blow-by-blow, now nonce-stamped).

## What shipped (all on `main`, pushed through `c6fde34`; `git log` is the truth)

1. **M-F dogfood-outward** — cc-oracle campaign: `mf/integration` in `C:\proga\claude-oracle`, 147/0, 3 hostile-review rounds, MERGE VERDICT sound. **UNPUSHED — operator merges/pushes** (public marketplace repo fence).
2. **Three-tier §12 doc-sync** (`1d878cf`) — band 150–200k across all doc surfaces.
3. **Claim-nonce build slice** (`2d58eba`) — per-body nonce, §7 gate live on 10 verbs, sup-release, handoff token, rc-4 seam. **The gate is armed in production**: every mutating verb from a sid-bearing session needs `--nonce` (sup-checkpoint mints+rotates; lifecycle verbs present-only). Battle-exercised same-day: 3 refusal classes hit and recovered.
4. **native-substrate.md receipts-enforced** (`d10e08c`) — 5 pinned + 1 volatile, floor 6; WITHHELD strings honestly left un-receipted.
5. **C/soak framing retired** (`31a21f8`) — re-home-before-supersede condition grep-receipted; PLAN/ROADMAP banners; ceiling denomination retired with band guard.
6. **Residuals 3+4 fixed** (`f09df14`) — blackout-indeterminate, husk life-signal, guarded autoclean removal.
7. **Three-tier build slice** (`c6fde34`) — tier resolver (GOALS-policy chain), band measurement (`sup-context`), 200k ceiling refusal, archive exemption, send-provenance, `sup-decision` state-file, §10.1 supervisor-shaped family. Dual-lens gated 0C/0M both lenses.
8. **fleet-index M1 evidence** (`docs/mf-oracle-m1-evidence.md`) — cross-worker read-dup 2.5% of fresh input: UNDERCUTS the M1 economics premise for fleet workers.

Suite at close: **1897 passed / 13 skipped identical on 3.13 and 3.10** (skip count is env-conditional ±5 vs quiet machine; totals + zero-failures are the signal). Receipts: three-tier 56/56, claim-nonce 58/59+1 disclosed volatile, native-substrate 5/6+1 volatile.

## FIRST ACTION — operator morning queue (nothing here blocks fleet work)

1. **Ratify/reverse the council verdicts** in `docs/OVERNIGHT-2026-07-23.md` G-1..G-4 (boxes in OPERATOR-GATES untouched — only you tick). Headline: the freeze-verdict live catch (G-1) — council majority was wrong, dissent was right; worth a lessons-grade read.
2. **Push cc-oracle**: `cd C:\proga\claude-oracle && git checkout main && git merge mf/integration && git push` (+ version bump if releasing).
3. **Apply or reject three GOALS.md proposals**: `docs/proposals/GOALS-threetier-sync-proposal.md`, `docs/proposals/GOALS-tier-chain-proposal.md` (incl. its "Operator follow-ups": the §7.2 holder-alone one-line spec amendment).
4. **fleet-index M1 go/no-go** with the fresh evidence (it undercuts; the queued decision wanted exactly this data).
5. `docs/specs/providers.md` re-base-or-park: still parked by you, still not surfaced as a blocker.

## The remaining build tail (design-open, deliberately not rushed)

- **`sup-spawn` verb choreography** — BUILT this run (branch `build/sup-spawn`: gen-0 dispatch per the ratified choreography decision record, + fix wave 1: `name_fs_stem` pipe-name mapping across every name-keyed fs path, §10.4-unbuilt kill/respawn fail-closed guard, resolver no-claim/released-arm pins, file-redirect boot ritual). What remains from the old bullet is only §10.4 below.
- **§10.4 kill/respawn tombstone + sup-release interaction** — same journal.
- Appendix-A v2-deferred rows stay deferred (beat verb §9.1; never-Haiku lives as GOALS doctrine).
- Claim-nonce F1/F3 build obligations landed; §6.3/§6.4/§6.2/§7 all built. M-E gate residual re-audit (item 5 of old handoff) — partially absorbed; re-audit which of spec-lens F3's harness gaps H1 left open remains owed.
- macOS pytest receipt still owed from the port author's box (ask when convenient).

## Housekeeping

- **Worktrees to remove once autoclean retires their idle workers** (`git worktree remove` + `prune`): old set `C:\proga\fleet-mf-*` (5), tonight's `oracle-wt-{stophook,config}`, `fleet-int-docs`, `fleet-nonce`, `fleet-nonce-r{b,s}`, `fleet-ns-receipts`, `fleet-soak-retire`, `fleet-tt-build`, `fleet-tt-r{b,s}`, `fleet-residuals`. Branches for merged work can be deleted freely; `mf/*` oracle branches stay until the operator pushes.
- Idle workers (~15) → autoclean TTL; owner sid is this run's session, `--yes` needed if retiring manually from a fresh session.
- Draft PR #8 on the fleet repo closes itself (branch deleted post-merge); if it lingers, close manually.
- Pre-existing flake `test_a_valid_proof_still_exits_0` — proven pre-existing on 31a21f8 by the break lens; file a fix when convenient.

## Standing rules (movement this run)

- CLAUDE.md + spawn-etiquette bind; spawn-etiquette gained: `dontask` allowlist doctrine (deny-rules-as-hard-fences), respawn/send truncation workarounds (200-char registry snapshot — fleet fix candidate), fence phrasing in worker vocabulary ("no `git push` of ANY ref").
- **Nonce protocol for every future supervisor session**: carry the value the last `sup-*` verb printed; sup-boot as normal (legacy claims exempt until first mint).
- Band doctrine held for workers (4 lossless BAND-HANDOFFs this run — the doctrine's first live exercises, all clean). Manager-band tension at 1M-window sessions is logged as friction; the 150–200k number assumes a 200k window — candidate operator question, not unilaterally changed.
- `git log` is the only truth; push main at every green milestone; RULING-LANDS-FIRST; no author promotes its own spec; adversarial + spec lens pairs with new-defect hunts (fired again: 9/9 lifetime; fix-waves-minted-defects now 5/5 with the wrong-marketplace-name SPURIOUS-FIX as the exhibit).
