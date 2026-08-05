# Next session — handoff

## ⛔ 2026-08-06 STAND-DOWN — read this block first, the rest of this file is a day stale

**The fleet is deliberately STOPPED** (operator needed the machine, 2026-08-06; supervisor
released cleanly 22:24:12Z). Revival = the fleet skill's startup ritual, as always. First
reads, in order: the release note in `fleet sup-status` (revival pointer), the stand-down
checkpoint in `supervisor/JOURNAL.md` (committed at `1a23aee`), then this block.

State at stand-down, session of 2026-08-05/06 (waves 40r–45, ~6 supervisor bodies, first
THREE consecutive live handoffs proven):
- **Landed + pushed**: MF slice a1 (`read_registry_at`, homes list, `fleet homes` verb);
  §5 verb table COMPLETE under the four-part operator ruling; claim-nonce `:337` + §8
  restated (deleted-file-reference rule ratified); launch-docs + doc-claims pin;
  verify_receipts tri-state rc; ruling-A pin reconcile + pin-pass stamped 2.1.222;
  **ceilings raised: supervisor 400k hard (band 350–400k), worker 300k (250–300k)** —
  landed as `feat(band)!`.
- **In flight at stop**: pins branch `bc1ad91` gated GATING-F1, needs a one-line repair +
  landing; a2 branch `39f84d0` awaits the verdict of gate lane `w45-ga2` (was still working
  at release — read `state/verdicts/w45-ga2.md` first).
- **Docket open**: E5 (doctor --repair row wording), E2/homes tension (self-opened
  2026-08-05), ND4(c) Option B (occupies the sup-decision slot), w35/nd4c third wave.
- Operator directives standing: LAUNCH FOCUS (multi-fleet + launch readiness the priority
  axis), MORE PARALLELISM (file-set disjointness the only bound, merge-base form).

*(Everything below was written 2026-08-05 ~12:0xZ, before waves 41–45 — historical.)*

## THE LONG-TERM GOAL and where it stands

**Multi-fleet v8 was RATIFIED ready-for-build 2026-07-30** (whole docket cleared same
sitting — see OPERATOR-GATES Settled, docket pass). Slice 0 (install/home split) LANDED
wave 35. The build continues at Sequencing §3 slices a–e (global `--fleet-home` in or
before the arming slice; round-7 defect pins are slice conditions). MF slice a pricing is
in wave 40r's mission. 17 of 32 verbs still unclassified in MF §5; SS7 install-plane
isolation half owed.

## FIRST ACT — a supervisor is LIVE, do not spawn over it

At handoff: **wave 40-retry (`sup|inc-20260805T115735Z-5a11|boot`, inc-20260805T115801Z-99cd)
is WORKING** — vendor pin tier first, then four lanes (verify_receipts rc-constant fix;
P1-7 outcome-reporting; cross-doc citation lane; MF slice a pricing). Sequence:

1. `fleet sup-status` — fresh heartbeat → alive; arm `fleet wait <name> --any` in background
   Bash, work the loop on its release.
2. Stale heartbeat + dead body → the LOGIN-EXPIRY pattern (killed waves 34 AND 40: the
   machine's Claude login lapses, every session dies instantly mid-turn, zero work saved).
   After the operator runs `/login`: `fleet autoclean`, then `sup-spawn` a retry brief —
   the stale claim seizes cleanly. Precedent retry briefs: `state/tasks/lens/
   sup-brief-wave34r.md`, `sup-brief-wave40r.md` (pattern: name what the predecessor
   verified, order re-verification of volatile facts, reuse surviving worktrees).

## THE LOOP (8 waves this session, ~40 lifetime)

`sup-spawn --task @state/tasks/lens/sup-brief-waveNN.md` → background `fleet wait --any` →
read the release note (`fleet sup-status` head; often an @file at
`C:/Users/Techn/.claude/jobs/<id>/tmp/release.md`) → author the next brief FROM it, one
page, ACT-FIRST, ending "WHAT THIS BRIEF GOT WRONG" → spawn. Briefs in
`state/tasks/lens/`, never `state/tasks/<name>.md`.

## TWO HARD RULES, unchanged

1. **Never `fleet sup-boot`** — sup-spawn a body; the claim belongs to a role.
2. **Never drive a worker directly** — everything through the supervisor.

## OPERATOR ITEMS PENDING (carry, nothing narrows while they wait)

1. **ND4(c) Option B** — OCCUPIES the sup-decision slot: close the fork-steer hole (a
   fork-steered unstamped claim-holder is still ceiling-exempt, reproduced at 500k) at the
   cost of amending the ratified "arm (c) ahead of any registry read" property. Option A
   (hole documented honestly) is what shipped. Needs Altai; doctor FAILs on the occupied
   slot by design.
2. **w35/nd4c park** — RED at terminal gate on 4 one-clause TEXT fixes (the reviewer wrote
   the replacement clauses); ESCALATE-beats-3rd-wave parked it; Altai may authorise the
   third wave. Branch @ 1e810f7; worktrees w35-nd4c + w36-rev-nd4c stand (their holder
   workers were archived 2026-08-05 — worktrees intact). Until resolved:
   `#2026-07-31-nd4c-ruled` stays unindexed (its INDEX line is owned by the parked branch),
   and note the correction of record: earlier handoffs claimed the ND4c predicate "reads
   the claim file, not the environment" — FALSE, it reads CLAUDE_CODE_SESSION_ID; that
   false sentence became two gate findings. Do not restate it.
3. **GitHub PR rule** — Altai ruled B (drop/scope the rule) 2026-07-30; the settings change
   on GitHub is NOT yet made; bypass events on every push remain expected, not violations.

## STATE — RE-MEASURE, never inherit

- main = origin = `349767f` at handoff (wave 40r moves it). Baseline **3647/14/1, both
  interpreters** at 2a25bdb — inherited iff `git diff --name-only 2a25bdb HEAD` touches
  only journal/knowledge-release files; else re-measure.
- Landed since 07-30: the docket pass (6 rulings), substitution model + §7 repair
  (w34/rulings), b6gate salvage (supervisor-claim wedge doctor row), MF slice 0,
  respawn-truncation fix, w36/refute, knowledge folds. Suite 3472 → 3647.
- Roster swept 2026-08-05: 54 archived, 7 daemon-deferred husks (next autoclean pass gets
  them). resid-probe TOMBSTONES are docket evidence — never tombstone-sweep.
- Parked/untouched: w35/nd4c, decoy branch `fix/outcome-usage-provenance` (points at main),
  §7 arm 3, no round 8, no clean, no --repair, no `fleet init` (instance-freshness doctor
  FAIL = init is a deploy with live workers = operator gate).
- Doctor: 3 known FAILs (identity-witness docketed; instance-freshness operator-gated;
  occupied decision slot by design).

## CONTEXT CEILINGS WERE RAISED 2026-08-05 — do not budget a body against 200k

Operator ruling, direct directive (`docs/OPERATOR-GATES.md` §Settled,
`knowledge/lessons.md#2026-08-05-ceilings-raised`): **supervisor hard dispatch ceiling
400k (band 350–400k); worker band top 300k (band 250–300k)**. Amends three-tier
§11.3/§11.4. Grounds: boot costs 85–130k, so 200k produced ~45-minute handoff
generations.

- **The ruling and the code landed apart.** `5c61ad5` on `main` is docs only; the code
  lands with branch `w44/ceiling`. **Until that branch is merged, shipped `fleet` still
  refuses at 200k** — the ruling itself says code is the authority meanwhile.
- The two tiers no longer share a band: `SUPERVISOR_BAND_*` / `WORKER_BAND_*`, and
  `fleet sup-context` resolves which one applies to the body running it and prints the
  tier. An indeterminate tier reports the **worker** band (the strict one).
- **Re-price anything sized against the old band.** `docs/mf-slice-a-price.md` concluded
  MF slice (a) "does not fit in one worker's 150–200k band" and drove the a1/a2/a3 split;
  that arithmetic was against a band that is now 250–300k. The split already shipped —
  this is a note for the NEXT sizing decision, not a call to unpick a landed one.

## MEASUREMENT DOCTRINE (hard-won waves 33–40; verbatim into merge briefs)

- `git merge-tree` THREE-ARG form only — `--write-tree` dies at git 2.34.1 and its empty
  output reads as "0 conflicts". Count `grep -cE '^\+?<<<<<<<'`; PREFER
  `grep -c '^changed in both'` (structural verdict, not rendering scan).
- A detector needs a known-ZERO control AND a known-NON-ZERO control; either alone
  certifies a broken detector.
- Lost-hunk check (mask `:N` and `:N-M` forms) is the only measurement distinguishing
  "conflicts resolved" from "conflicts narrated".
- Price a merge by what MOVED, not what collided (conflicted set is a lower bound on
  citation rot — wave 39 measured 25 corrections, only 21 inside conflict hunks). Run
  `tests/test_self_citations.py` TO FIXPOINT — one red/green read is a lower bound.
- Merge-prep-by-lane is doctrine WITH the rule: dispatcher commits+pushes its journal
  BEFORE cutting the lane branch, writes nothing to main while the lane works, re-derives
  ancestry at landing (a prep report is a claim about a PARENT).
- Parallelism by FILE-SET disjointness (`git diff --name-only base..branch`), not ordering.
- `fleet respawn` truncation is FIXED (w35/respawn-trunc landed wave 38); `fleet result`
  is lossless — read it before re-deriving anything a worker measured.
- `tools/verify_receipts.py` rc is a CONSTANT 1 over mixed spec dirs (INCONCLUSIVE
  mis-mapped) until wave 40r's lane 1 lands — read verdicts, not the exit code.
- Never pipe evidence (`| tail` collapsed 15 spec verdicts to 1). @file bodies for every
  prose-taking verb (bash executed backticks inside a double-quoted checkpoint, wave 35).

## LEDGERS

`knowledge/INDEX.md` newest-first (boot digest = top 20 lines). Key lessons anchors:
`#2026-07-30-operator-docket`, `#2026-07-31-w34-respawn-truncation`, the waves 35–38 fold
(merge-tree/marker-grep/merge-prep), `#2026-07-31-nd4c-ruled` (unindexed, see above).
Persistent memory: `MEMORY.md` → multi-fleet-docket-pending (RESOLVED — v8 ratified,
building), interface-tier-runbook. OPERATOR-GATES: Open has ONE entry (the ND4c collision
gate, ruled A 2026-07-31 and moved to Settled — verify on read; the slot's Option B
question is the live one).
