## 2026-09-16T19:06:25Z CHECKPOINT inc=inc-20260911T195615Z-a6c9 sid=acd22c30-c5ed-41e8-9f68-6fd6702625ca

Decision answered (b) and cleared: item 19 jumps ahead of item 5, the kill stays with the operator. Item 19's brief is drafted and ready at $CLAUDE_JOB_DIR/tmp/w92-task.md -- lane w92, branch w92/stop-landed-lanes, base 9ee2b35: stop a finished landed lane's session via _stop_native_session_status, then reap, so the lane arm fires; the live-PID protection stays exactly as strict and weakening it is named as a rejected fix.
Standing down from the slot watch on the interface's instruction -- it owns the wake. Every Monitor re-arm was a full-context turn, which is the occupancy-per-turn cost item 4 was re-scoped to measure; four re-arms bought nothing but a status line. Blocked purely on a free slot: w88/w90/w91 idle with live PIDs, live_lane_count=3, w88 idles out around 20:45Z if the operator's kill does not land first.
Wave 85 closed db4dc57 and pushed; tree clean bar these journal lines; nothing in flight; occupancy 250k against the 350k band, so this body can take w92 through without a handoff.

## 2026-09-16T20:57:11Z SEIZED inc=inc-20260916T205711Z-ad2a sid=d3779e11-2878-4ff7-a2cb-899b10b94949

seized from inc-20260911T195615Z-a6c9: holder roster-gone, heartbeat stale (6646s > 3600s)

## 2026-09-16T20:58:22Z CHECKPOINT inc=inc-20260916T205711Z-ad2a sid=d3779e11-2878-4ff7-a2cb-899b10b94949

SEIZED the claim from a6c9 (sid acd22c30): holder roster-gone, heartbeat stale 6646s > 3600s -- the vanishing the interface filed as item 21, and the seizure path handled it without operator action. Boot reap collected w88/w90/w91 as daemon-dead rows, so live_lane_count=0, available_memory=4479MB, and the slot block that parked a6c9 is gone; note that the lane arm still never fired (item 19 stands exactly as filed).
Inbox drained: the interface note of 20:30Z moved to state/inbox/done/. Queue order inherited and not re-raised: item 19 next, then 5, 6, 4 re-scoped, 8, 15, 16, 17, 7, with 20/21/22 after 19. a6c9's w92 brief was lost with its job dir; redrafting from item 19's own shape.
Dispatching lane w92 (branch w92/stop-landed-lanes, base 9ee2b35): wave-close stops a marked-landed session via _stop_native_session_status, then reaps, so the lane arm fires in the same wave-close; live-PID protection stays exactly as strict and weakening it is a named rejected fix.

## 2026-09-16T21:31:45Z CHECKPOINT inc=inc-20260916T205711Z-ad2a sid=d3779e11-2878-4ff7-a2cb-899b10b94949

w92 landed and merged at edd30f6: wave-close now stops each session it marks lane_state=landed via _stop_native_session_status (outside fleet_lock, after push/prune/notify) and reaps a second time, so the lane arm fires inside the same run. Item 19 closed; item 2's three-year-old complaint with it. The lane proved by real claude --bg + claude stop that a stopped session's roster entry disappears ENTIRELY, which is why _reap_protection needed no weakening -- the rejected fix stayed rejected. land GREEN, floor 5380 passed / 6 pre-existing host-venv failures on both interpreters.
Interface filed items 20-24 and reordered: 24 (OpenRouter substrate) jumps to right after 19, before 5. Operator widened it -- openrouter:stealth/union-alpha becomes the DEFAULT builder substrate for worker lanes in both homes once it lands, sonnet only with a written reason, opus keeps reviews and the supervisor tier. Roster of 16 measured slugs is in state/tasks/20260916-openrouter-roster.md; I am treating it as data and briefing the verb generic (--model openrouter:<slug>).
Dispatched w93 (branch w93/openrouter-substrate, base edd30f6, sonnet -- item 24 is not landed yet, so sonnet is still the builder tier). The brief names the one fork that decides the lane: whether env set on the dispatching process reaches a claude --bg session the daemon owns. If it does not, writing the key into state/worker-settings.json is forbidden and the lane must blocker out rather than let fleet report openrouter/<slug> while silently running on Anthropic.
