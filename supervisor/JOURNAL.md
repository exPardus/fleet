## 2026-09-11T19:18:50Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 80 dispatched: w84/homes-inventory (UVX152Jj, luna medium) at c05d6c3 -- operator item 1, the first in three waves. Directive 20260910-standing-directive-throughput 4 is explicit: waves 78 and 79 advanced no item on the fixed 1-5 list, so the next wave is item 1 only.
MEASURED in-process, no verb run: resolution_population gives 2 homes, homes_population gives 1, and _refuse_wrong_home_destructive (bin/fleet.py:3163) builds ONE message from both -- it says this machine runs 2 fleets, prints both paths, then embeds a view showing one. The operator's inventory surface contradicts the guard that refuses their commands.
Raised the tap registration to the operator rather than doing it: the homes-list append is ratified destructive, and tap is live with its own supervisor but unregistered.

## 2026-09-11T19:55:13Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

Wave 80 closed and pushed ee2b756, operator item 1 advanced -- fleet homes and the arming guard now count the same homes. 52,997.94 tokens per added bin line, up from 12,099: the wave landed 79 bin lines, and the per-line figure is noisy at that size.
Filed the G-K5 registration gate at 191d3cd -- the one the ruling told the lane to file rather than build around. bin/fleet.py:4225 confirms bare init creates without registering, which is exactly why tap is a live home invisible to fleet homes, and why item 1's DONE criterion cannot be met as written.
My briefs, not the substrate, are why three lanes shipped untested code: UV_OFFLINE=1 with the warm cache works offline on both interpreters; I had dropped the flag. BRIEF-TEMPLATE.md now names the pair.

## 2026-09-11T19:55:59Z CHECKPOINT inc=inc-20260911T181025Z-881b sid=7761eab5-58c5-4707-bda1-57694cff0867

HANDOFF. Context 327k vs the 350k soft band -- clean boundary, wave 80 closed and pushed (c05d6c3..649054b), nothing in flight, tree clean, no lanes running.
SUCCESSOR PICKS UP FIRST: read the throughput standing directive 1 BEFORE choosing a lane -- item 1 is blocked on the G-K5 registration gate I filed at 191d3cd, so item 2 (zero downtime: sid-union join, G-K6 wave 2 waker) is the next unblocked one. Batch 2 is fully discharged.
Full pickup list, blockers and host rules: state/journals/sup~inc-20260911T181025Z-881b~successor.md. The generation's costliest defect was mine: briefs that named the uv cache without UV_OFFLINE=1, so two lanes shipped code they never executed.
