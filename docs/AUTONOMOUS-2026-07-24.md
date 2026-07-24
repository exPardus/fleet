# Autonomous run — 2026-07-24 (day 3)

Operator directives (verbatim intent, given in-session before going hands-off):
1. Work autonomously as the previous session did; anything operator-gated goes to a council of
   **4 councilors of differing personalities + a synthesis agent**; act on the synthesis; record
   every gated item here with why it was gated and what the council said.
2. Investigate whether the cc-oracle plugin works for fleet workers, whether it works as intended,
   and whether it has measurable useful effects.
3. **Keep going through the spec** — when NEXT-SESSION runs dry, keep building: the target is a
   **full build of fleet, ready to launch properly**.
4. **Switch over to three-tier in this session if it lands and works properly**: once `sup-spawn`
   merges and smoke-tests green, this session releases its supervisor claim (`sup-release`, with
   continuity), runs `sup-spawn` to launch a gen-0 supervisor body, and becomes the interface
   tier — steering via `fleet send supervisor` (logical name), with the supervisor owning the
   fleet from then on. The live switch IS the acceptance test.
5. Multi-supervisor future note (§13.1): teams work on different things OR on one large campaign
   as coordinated fronts — both modes intended.

**Nothing in this file ticks a box in `docs/OPERATOR-GATES.md`** — only Altai ticks. Council
verdicts recorded here are provisional decisions acted on during the run, queued for ratification.

## Decisions the operator made in-session before going hands-off (already recorded in
`knowledge/lessons.md#2026-07-24-day3`, listed for continuity)

- G-1..G-4 overnight verdicts ratified (G-1 with a freeze-message harden order).
- fleet-index M1 economics deferred; **full M1+M2 `fleet q` build ordered** on the standalone
  value case (long-term multi-session codebase work).
- Both GOALS proposals applied (`3ccb2d5`); three-tier §7.2 amended holder-alone.
- cc-oracle v0.2.0 merged + pushed public (`8656f32`) by operator authorization.
- sup-spawn rulings: gen-0 = `sup|<launch-id>|boot`, `"supervisor"` = logical name resolved via
  claim; contradicting spec prose amended by operator order; bypass-ack check = warn-and-proceed.

## Operator-gated items encountered during the run

### G-A. §10.4 tombstone design — two rulings (2026-07-24)
- **What**: tomb-design's decision record left 2 genuinely-unsettled choices: (1) respawn
  steer-failure disposition — abort vs kill-style fall-through; (2) `kill supervisor` against a
  limited-parked holder — refuse vs proceed-with-warning.
- **Why gated**: both extend/interpret ratified contracts (SPEC never-block is kill-scoped; a
  loud-warning destruction is the shape CN §6.3 deleted) — operator-owned per the designer.
- **Council verdict**: **UNANIMOUS 4–0 (a)/(a)** — abort; refuse. Acted on: rulings + merged
  conditions steered to tomb-design for folding into the design doc.

## Council record

Four councilors (per directive 1), distinct personalities, each read the proposal + governing
specs independently; synthesis by manager (recorded here), queued for operator ratification.

| Docket | Cassandra (risk) | Brick (delivery) | Vista (strategy) | Mercer (incident-response) |
|---|---|---|---|---|
| 1. respawn steer-failure | (a) — ambiguity + irreversibility; (b)'s worst case destroys a healthy supervisor 3s from releasing | (a) — frozen claim is the ultimate blocked pipeline; fast honest failure beats slow guaranteed destruction | (a) — "failure disposition matches mandate"; never-block is kill-scoped on purpose | (a) — (b) yields a state indistinguishable from success from outside |
| 2. kill limited-parked holder | (a) — strictly-worse-in-every-branch; warnings on destructive verbs get reflex-confirmed | (a) — refusal that prints the two runnable commands is a redirect, not a round-trip | (a) — (b) reintroduces the `--force` shape CN deleted one docket later | (a) — scroll-back warning invisible an hour later when every sup-boot freezes |

**Synthesis (acted on)**: (a)/(a) with merged binding conditions — grep-able
`SUP-RESPAWN-ABORTED <phase>` surface printing escalation commands verbatim + async-late-release
warning; F1/F2 byte-identical-state fault-injections ratification-blocking; bounded abort at
exactly `SUPERVISOR_RELEASE_TIMEOUT_SECONDS`; refusal message prints ALL escapes (limit-transfer,
resume-limited, poisoned-park sequence w/ real-name kill + freeze cost) and asserts zero
mutations; **no bypass flag ever without a new council ruling**; new build requirement — during
any freeze window `sup-status`/statusline shows "claim held by dead sid, seizable in
<remaining>s".

## Dispatch record

- `supspawn-design` (worker, bypass, fleet worktree `fleet-supspawn-design`, branch
  `design/sup-spawn`): design pass DONE (`61b5943`, 472-line decision record); now applying the
  ruling-1(iii) spec prose amendments to `three-tier-command.md`.
- `fleetq-spec` (worker, bypass, worktree `fleet-q-spec`, branch `spec/fleet-q`): re-ground
  `docs/specs/fleet-index.md` M1+M2 to ready-for-gate per the operator order.
- `small-fixes` (worker, bypass, worktree `fleet-small-fixes`, branch `fix/small-batch`):
  G-1 freeze-message harden, `test_a_valid_proof_still_exits_0` flake root-cause, §3.3
  CLAUDE_CONFIG_DIR descriptive-vs-gap verification.
- Oracle-for-workers investigation: read-only subagent over plugin cache + worker logs/transcripts
  (installed version vs 0.2.0, injection presence, consult count + outcomes, stop-hook effects).
  **REPORTED + ACTED ON**: mechanically working as intended for headless workers (injection
  confirmed via SessionStart hook output in tt-build's transcript; agent dispatch works at
  `model: fable`; Stop hook runs silently, zero production blocks, no interference with fleet's
  own Stop hooks). Adoption light: 2 worker consults (~18 post-install workers never consulted) —
  tt-build §7.2 (CONFIRMATORY ruling, but the sid-union bridge + disclose-framing adopted verbatim)
  and ns-receipts (CONFIRMATORY, with one LOAD-BEARING ruling: the RATIFICATION-WITHHELD strings
  cannot be honest receipts). Zero negative effects found; both consults ran async without costing
  the worker a turn. Verdict: **earns its cost as a decision-quality tool, unproven as a rescue
  tool** (no worker has consulted from a stuck state; Stop-hook net never fired in production —
  cannot distinguish too-narrow detection from no-hedged-turn-ends on this data). Actioned: plugin
  cache was STALE (0.1.1 loaded vs 0.2.0 released — workers ran a 253-line hook vs the hardened
  517-line one) → `claude plugin update oracle@cc-oracle` run, now 0.2.0; sessions spawned from
  now get the hardened detector. Manager live-verified the Stop hook fires interactively
  (deliberate marker-phrase test — blocked turn-end with the dispatch-oracle demand, correct).

### Dispatch record additions (post-council)

- `supspawn-build` (bypass, worktree `fleet-supspawn-build`, branch `build/sup-spawn` @ ea49545):
  building the sup-spawn verb per the ratified design (merged to main in ea49545).
- `fleetq-rb` / `fleetq-rs` (bypass, read-only fences, on worktree `fleet-q-spec`): dual-lens gate
  on the fleet-index M1+M2 spec (`4011990`).
- `tomb-design` fork-steered with the G-A rulings + conditions to fold into its design doc.
- `github-polish` (bypass, worktree `fleet-gh-polish`, branch `docs/github-polish`):
  operator-ordered discoverability pass — README/CONTRIBUTING/docs-index + repo-settings
  PROPOSAL (no `gh repo edit` by the worker; manager applies).

### Gate ledger (running)

- **fleet-index M1+M2 spec**: gate 1 = rb 1C/3M/5m + rs 1C/1M/7m (CRIT-1 walk-up crossed worktree
  boundaries; CRIT-2 fresh-doc-born-stale citations, tree 11,288 vs spec's 8,706). Fix wave 1
  (`a63a9e7`) → re-gate **0C/0M/4m** — first wave on record minting no CRIT/MAJ. Manager
  micro-folded the 6 MINs (`71602ed`), merged to main `48ee2c8`. Status ready-for-gate; build
  proceeds on the operator's standing order; OPERATOR-GATES settled row owed.
- **sup-spawn build**: builder `4bb11ed` (1971/8 both floors, 69 tests). Gate: spec lens **0C/0M/5m**
  (all 4 disclosed deviations ACCEPT; choreography replica verified verbatim); break lens
  **3C/2M/4m** — CRIT-1 pipe-name crashes every name-keyed fs path beyond task files
  (tombstone/archive/journal), CRIT-2 `respawn supervisor` = bare body swap violating [UNBUILT]
  §10.4 (council 4-0 already rejected that shape), CRIT-3 resolver no-claim arm unpinned (1 of 7
  fault-injections survived green). Fix wave 1 dispatched: central `name_fs_stem` mapping, kill/
  respawn-of-holder FAIL CLOSED until §10.4 builds (interrupt stays, disclosed), FI-4 pin, boot
  ritual re-rendered per nonce class-4 doctrine. Re-gate follows.
- **github-polish**: merged `ad5e59a`; repo settings applied live (description, 15 topics,
  discussions on). Owed to operator: none — settings were the ordered deliverable.
- Doc item carried by manager: `claim-nonce.md` §7 taxonomy row for `sup-spawn`
  (operator-owned spec amendment).

## Build queue (the launch-ready ordering, updated as it drains)

1. Merge-gate the three in-flight branches (dual-lens where code/spec-bearing).
2. **sup-spawn build** (§10.1) per the ratified choreography design.
3. **§10.4 kill/respawn supervisor tombstone + `sup-release` continuity** (heaviest remaining
   three-tier item).
4. **fleet-q M1+M2 build** after the spec gate + operator ratification of the gated spec.
5. Remaining [UNBUILT]/deferred sweep across `docs/specs/**` toward launch-readiness
   (v2-deferred rows stay deferred unless the operator says otherwise).
6. Housekeeping: worktree cleanup once autoclean retires idle workers; macOS receipt still owed
   externally.

## Friction log

- *(manager)* Nonce refusal class #4 — self-truncation of the sup-boot bundle; §5.7 lever
  exercised with operator authorization. Doctrine: full-output-to-file for every `sup-*` verb.
