## 2026-09-11T17:23:55Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77 dispatched: w81/band-gate (J15MrUc2, luna medium) at 10c24f3. The band gate the manager asked for is an EXTENSION, not a new mechanism: _ceiling_refuses_dispatch (bin/fleet.py:2100) already refuses at the hard 400k ceiling and is already wired into spawn :4229, send :5116, respawn :5414 and :5638, sup-spawn :12779. The lane adds the soft 350k arm, --force-band overriding SOFT ONLY, and occupancy in the sup-checkpoint header. Brief points at those line numbers rather than describing the behaviour.
Named three constraints that outrank the feature: --force-band must not pass the hard ceiling (own test), the structural exemptions and the fail-toward-band rule for unknown occupancy survive unchanged, and the handoff verbs stay exempt -- a gate that blocks the remedy is worse than no gate.
The third path the instruction named does not exist: fleet only READS mcx records for token accounting (:11421, :11475); mcx lanes are dispatched by hand. Told the lane to confirm by grep and report it, not to build one. First brief validated through fleet brief: the Serves: citation passes.

## 2026-09-11T17:39:40Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77: w81/band-gate merged b2a8dc7. Soft-band refusal live on spawn/send/respawn/sup-spawn; --force-band clears soft only and is structurally unable to clear the hard ceiling (gated on verdict == in-band, pinned by its own test). Verified 999 passed/4 skipped on 3.10, 769/1 on the 3.12 subset.
Lane changed four verbs and left skills/fleet/SKILL.md untouched though its CLI list claims to be derived from build_parser(); I added --force-band to all four lines and stated what it cannot override. Same doc-gap class as the --nonce list earlier this generation -- worth a standing brief line: a lane that adds a FLAG updates the CLI list, not just a lane that adds a verb.
MEASURED and reported by the lane: there is no mcx dispatch helper to gate.

## 2026-09-11T18:10:10Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

HANDOFF. Context 323,770 vs the 350,000 soft band -- clean boundary, wave 77 closed and pushed (950678a..baf28a1, close bc18650), nothing in flight, tree clean, no lanes running.
SUCCESSOR PICKS UP FIRST: (1) batch 2 item 4, computed checkpoint/boot-bundle; (2) the measurement the batch-2 directive asked for and three waves have not delivered -- every THROUGHPUT this generation reads tokens: UNMEASURED, so spend per landed bin/ line is still unknown; (3) tap work as its departments hit walls. Items 1 and 2 both write bin/fleet.py and serialise.
Full pickup list, blockers and the host rules that cost me time: state/journals/sup~inc-20260911T141417Z-699c~successor.md. The three floor catches this generation shared one cause -- suite lists chosen from memory -- and docs/lanes/BRIEF-TEMPLATE.md now derives them instead.
