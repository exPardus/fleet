# Spec: Phase-1 hardening kernels (salvaged from idea-forge run 1)

**Status:** ready-for-build (pre-vetted — these are the judge-salvaged kernels from `docs/IDEA-FORGE-REPORT.md` §4; do NOT expand them into the dead parent ideas, see report §5 graveyard)

Afternoon-sized line items for the Phase-1 build. Each is deliberately minimal; scope creep here is how the parent ideas died.

1. **Swallowed-hook exception log.** Hooks keep the exit-0-on-any-error invariant, but the except blocks append one line (timestamp, session_id, exception repr) to `state/hook-errors.log`. `fleet status` shows a total count when nonzero; `doctor` shows the tail. (~5 lines)
2. **Static hook-registration lint in `fleet doctor`.** Parse the rendered worker-settings.json: known event names, command paths exist, JSON schema shape. Catches typos the synthetic smoke test false-greens on. (small)
3. **Fail-silent PostCompact journal landmark.** PostCompact hook appends a mechanical line to the worker's journal: turn count, token count, timestamp, "context compacted here". Never blocks, never loud. (~10 lines)
4. **Abnormal-turn-end journal note + cwd preflight.** When status classification finds a crashed turn (stale PID, no result), append "turn ended abnormally at <time>" to the journal so respawn context knows. Before any spawn/resume: stat that registered cwd still exists, clear error if not. (small)
5. **Spawn-time model echo.** Spawn output includes the effective model/config line (incl. `CLAUDE_CODE_SUBAGENT_MODEL` if set) so cost surprises are visible at launch. (one line)

Explicitly rejected even as kernels (do not build): mailbox dead-letter queues, PreToolUse scope guards, amnesia/journal-read verification, orphan auto-adoption, hook reraise/fail-loud, exit-code capture of detached turns.
