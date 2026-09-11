## 2026-09-11T14:36:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

w79/knowledge-caps landed (merge b6c1d20 -> server/persistent-fleet). tools/knowledge_index.py: --check exits 1 on a stale index, --write regenerates, --roll-lessons appends dated lessons >30d verbatim. Verified by me in the worktree, not from the report: 205 passed / 2 xfailed on 3.10 and 3.12 both; the 2 xfailed are the pre-existing docs-cap and GOALS-cap items. INDEX.md content unchanged -- the generated index matches the hand-written one once placeholders are excluded.
Lane reported DONE the first time with a JSON carrying no test rc and a report citing results 'recorded in the handoff' (no handoff exists), and it had indexed projects/.gitkeep into the file the boot bundle reads. One steer fixed all three. The verify-at-landing rule earned its cost again.
Over-cap on-demand notes MEASURED, none moved: campaign-template 238, claude-fleet 114, pmbot 50, claude-oracle 21, stupidbox 20, spawn-etiquette 14 (cap 12). w78 still running.

THROUGHPUT wave 76 (5f50ac0b3d1d4c8719cfa7911107ecb14d62f73a..2255cc2f9cf562792c8cdcedcc39b8d3785578a6): bin +230/-8, tests +169/-6, docs +99/-0, journal +24/-12, other +61/-0; workers: 1 (w80/fleet-brief: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T15:30:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

Wave 75 CLOSED and pushed: 6537949..5e2d14c, 5f50ac0. bin +346/-1, tests +166/-4, docs +127/-0. Landed: fleet land + docs/lanes/<lane>.json contract (batch 2 items 1+2), tools/knowledge_index.py (item 5), SKILL.md --nonce list fix.
Floor REFUSED the first close on 10 failures vs the 6-failure host baseline, both new defects from w78 and both missed by MY brief's suite list (it named neither test_round7_defect_pins nor test_sid_collision): fleet_land.py shipped outside tests/fleet_sources.IMPLEMENTATION_FILES, so no census scanned it and every install built from that tuple carried a fleet.py whose top-level fleet_land import died; and the land verb shipped with no effect disposition. Fixed in 5e2d14c. A new verb needs the effect-disposition pin and a new bin/ module needs the census tuple -- put both in every brief that ships either.
Then found closing: the worktree pruner asked merge-base against the wave's BASE, so it called this wave's own landed lanes unmerged and could only ever prune one wave late. Fixed + pinned in 569411d.

## 2026-09-11T16:02:15Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=e061dbdf-894a-48cc-a9c3-e1c31ca40d09

Wave 76 dispatched: one lane w80/fleet-brief (NtCl32NP, luna high) at base 6cfdd28 -- fleet brief as leaf bin/fleet_brief.py, carrying the product.md Serves: citation and REFUSING a citation whose phrase does not occur under the named section, plus a pin scoping the requirement to task files from 2026-09-11T21:00Z so wave 75 and earlier stay grandfathered. One lane only: everything left in batch 2 writes bin/fleet.py and the one-writer rule holds.
Brief carries the two shipping requirements wave 75 taught: a new verb needs an entry in UNCLASSIFIED_BY_THE_RATIFIED_TABLE, a new bin/ module needs tests/fleet_sources.IMPLEMENTATION_FILES. Both suites named.
BLOCKER RAISED, mine to own: 569411d is red on test_docs_currency::test_branch_docs_currency -- bin/fleet.py changed with a trailer naming knowledge/, and the lint takes only docs/ or a literal Docs: n/a. Green at 5f50ac0, so I introduced it. It blocks every wave close until it ages out of the 20-commit window. Decision raised: amend+force-push (recommended) vs widening the lint. I did not widen it myself: it would clear my own violation.
