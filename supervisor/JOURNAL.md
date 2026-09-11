## 2026-09-11T14:14:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

claim received via handoff from inc-20260910T153011Z-0a56

THROUGHPUT wave 75 (6537949ace0b3cb25808e086057c1d497b93a37e..5e2d14cc728caffa2a21bc2d9c041f2342a2502d): bin +346/-1, tests +166/-4, docs +127/-0, journal +122/-71, other +156/-6; workers: 2 (w78/fleet-land: codex, w79/knowledge-caps: codex); tokens: UNMEASURED (roster has no token field; mcx result files missing); reaped: 0; protected: 0 (unread mail)

## 2026-09-11T14:20:01Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

Wave 75 dispatched, 2 lanes, base e87c049. w78/fleet-land (bu8raFEv, luna high): `fleet land <lane>` as leaf bin/fleet_land.py + docs/lanes/<lane>.json contract -- mechanise batch 2 items 1+2; sole bin/fleet.py writer this wave. w79/knowledge-caps (6pqOeS32, luna medium): tools/knowledge_index.py, item 5; fenced off bin/fleet.py and SKILL.md.
Brief defect caught pre-dispatch: a fresh UV_CACHE_DIR under UV_OFFLINE=1 cannot resolve pytest. Both briefs now name /tmp/w64-initrepo-uv-cache, the one populated cache on this host. docs-currency pin green against the dispatch home before dispatch.
Context 110k/350k at dispatch; available 3812 MB; observers armed detached per lane, break on rc != 2.

## 2026-09-11T14:36:59Z CHECKPOINT inc=inc-20260911T141417Z-699c sid=3a0004fd-cbd4-43ea-9389-3e639caadbc3

w79/knowledge-caps landed (merge b6c1d20 -> server/persistent-fleet). tools/knowledge_index.py: --check exits 1 on a stale index, --write regenerates, --roll-lessons appends dated lessons >30d verbatim. Verified by me in the worktree, not from the report: 205 passed / 2 xfailed on 3.10 and 3.12 both; the 2 xfailed are the pre-existing docs-cap and GOALS-cap items. INDEX.md content unchanged -- the generated index matches the hand-written one once placeholders are excluded.
Lane reported DONE the first time with a JSON carrying no test rc and a report citing results 'recorded in the handoff' (no handoff exists), and it had indexed projects/.gitkeep into the file the boot bundle reads. One steer fixed all three. The verify-at-landing rule earned its cost again.
Over-cap on-demand notes MEASURED, none moved: campaign-template 238, claude-fleet 114, pmbot 50, claude-oracle 21, stupidbox 20, spawn-etiquette 14 (cap 12). w78 still running.
