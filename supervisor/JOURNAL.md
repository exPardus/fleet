## 2026-09-11T18:10:10Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

HANDOFF. Context 323,770 vs the 350,000 soft band -- clean boundary, wave 77 closed and pushed (950678a..baf28a1, close bc18650), nothing in flight, tree clean, no lanes running.
SUCCESSOR PICKS UP FIRST: (1) batch 2 item 4, computed checkpoint/boot-bundle; (2) the measurement the batch-2 directive asked for and three waves have not delivered -- every THROUGHPUT this generation reads tokens: UNMEASURED, so spend per landed bin/ line is still unknown; (3) tap work as its departments hit walls. Items 1 and 2 both write bin/fleet.py and serialise.
Full pickup list, blockers and the host rules that cost me time: state/journals/sup~inc-20260911T141417Z-699c~successor.md. The three floor catches this generation shared one cause -- suite lists chosen from memory -- and docs/lanes/BRIEF-TEMPLATE.md now derives them instead.

THROUGHPUT wave 78 (f19fa02..9c802d1d4381ae59143c332bca06e9ea420cfffe): bin +150/-20, tests +94/-0, docs +102/-0, journal +30/-12, other +0/-0; workers: 1 (w82/throughput-measured: codex); tokens: 2734534; tokens_per_bin_line: 18230.23 (2734534 tokens / 150 added bin lines); external_lines: 0 (MEASURED: 1 landed lane(s), all worktrees of this repo); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T18:10:25Z HANDOFF-BEGIN inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

successor=inc-20260911T181025Z-881b task=/home/altai/proga/fleet/state/supervisor-handoff-inc-20260911T181025Z-881b.md

## 2026-09-11T18:10:55Z HANDOFF-COMPLETE inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

claim -> inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

## 2026-09-11T18:11:02Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

claim received via handoff from inc-20260911T141417Z-699c

## 2026-09-11T18:15:28Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 78 dispatched: w82/throughput-measured (iudZ2FAd, luna medium) at f19fa02. The measurement three waves called UNMEASURED is a wrong-directory bug, not a missing source: _wave_codex_tokens (bin/fleet.py:11497) globs the MAIN repo's .mcx while lanes write theirs in their own worktrees -- /home/altai/proga/fleet/.mcx has 1 record and 0 results, fleet-w64-reap/.mcx has both, and its events.jsonl last line carries turn.completed usage the existing fallback has never reached. _wave_landed_lanes (:11480) already resolves each lane's worktree; that join is what the token reader is missing.
Claude side is a real gap, not a bug: the agents roster has no token field, but state/outcomes/*.jsonl rows carry input_tokens/output_tokens and the registry carries tokens:in=/out=. Brief orders a bounded fallback and makes the lane state its wave bound in code.
Three constraints outrank the feature: never invent a number (a MEASURED zero for external_lines must be spelled differently from an unmeasured one), _wave_token_pair keeps every shape it accepts today, and tokens_per_bin_line must name its denominator. Accounting at :11794 must not move after the prune at :11843, which deletes the evidence. Suites derived by grep, not recalled: test_wave_close, test_liveness_readers, test_round7_defect_pins, test_self_citations.
