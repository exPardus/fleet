## 2026-09-11T16:52:47Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=e061dbdf-894a-48cc-a9c3-e1c31ca40d09

Wave 76 CLOSED and pushed: 5f50ac0..2255cc2, close 950678a, host rules e95f57f. bin +230/-8, tests +169/-6, docs +99/-0; one lane. Landed: fleet brief with a VERIFIED product.md Serves: citation (absent phrase, right phrase under the wrong section, and no citation each refuse with exit 1; valid exits 0 -- I ran all four), the dispatched-task pin scoped from 2026-09-11T21:00Z so wave 75 and earlier are grandfathered, and the docs-currency surface widened to docs/ + skills/ + knowledge/ per the operator ruling B.
The wave-close pruner fix from wave 75 is PROVEN: worktrees removed 3 (w78, w79, w80 with their branches), skipped 5 (1 genuinely unmerged, 4 dirty). Under the old base comparison this wave own lanes would all have been called unmerged and kept.
Four failed closes before this one, all mine, all refused before the commit/push phase: changelog cited the lane sha not the merge sha; I monitored a wrapper pid, read its death as the close finishing, and started a SECOND concurrent close; I rm -rf the live close working clone thinking it stray; and I rotated the generation mid-flight with sup-heartbeat. All four rules now in knowledge/projects/claude-fleet.md.

## 2026-09-11T17:23:55Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77 dispatched: w81/band-gate (J15MrUc2, luna medium) at 10c24f3. The band gate the manager asked for is an EXTENSION, not a new mechanism: _ceiling_refuses_dispatch (bin/fleet.py:2100) already refuses at the hard 400k ceiling and is already wired into spawn :4229, send :5116, respawn :5414 and :5638, sup-spawn :12779. The lane adds the soft 350k arm, --force-band overriding SOFT ONLY, and occupancy in the sup-checkpoint header. Brief points at those line numbers rather than describing the behaviour.
Named three constraints that outrank the feature: --force-band must not pass the hard ceiling (own test), the structural exemptions and the fail-toward-band rule for unknown occupancy survive unchanged, and the handoff verbs stay exempt -- a gate that blocks the remedy is worse than no gate.
The third path the instruction named does not exist: fleet only READS mcx records for token accounting (:11421, :11475); mcx lanes are dispatched by hand. Told the lane to confirm by grep and report it, not to build one. First brief validated through fleet brief: the Serves: citation passes.

## 2026-09-11T17:39:40Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=660602df-e190-4ab8-b334-af98a171ca27

Wave 77: w81/band-gate merged b2a8dc7. Soft-band refusal live on spawn/send/respawn/sup-spawn; --force-band clears soft only and is structurally unable to clear the hard ceiling (gated on verdict == in-band, pinned by its own test). Verified 999 passed/4 skipped on 3.10, 769/1 on the 3.12 subset.
Lane changed four verbs and left skills/fleet/SKILL.md untouched though its CLI list claims to be derived from build_parser(); I added --force-band to all four lines and stated what it cannot override. Same doc-gap class as the --nonce list earlier this generation -- worth a standing brief line: a lane that adds a FLAG updates the CLI list, not just a lane that adds a verb.
MEASURED and reported by the lane: there is no mcx dispatch helper to gate.
