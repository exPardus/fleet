# Supervisor Journal

Append-only checkpoint log (spec §4). Single writer: the current claim
holder, via `fleet sup-*` commands only. Never edit or delete entries.
Entry header format: `## <utc-iso> <KIND> inc=<incarnation-id> sid=<session-id>`
Kinds: BOOT, CHECKPOINT, PROPOSAL, SEIZED, HANDOFF-BEGIN, HANDOFF-COMPLETE, HANDOFF-ABORT.

<!-- entries below -->

## 2026-07-15T11:46:55Z BOOT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

fresh claim: no existing claim -- fresh claim

## 2026-07-15T11:48:48Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B plan authoring started per NEXT-SESSION.md handoff: spec v2.3 s5/s5.1 + native-substrate contract read; 3 code-map explorers running over bin/fleet.py (UL1 limit machinery, spawn lifecycle, hooks+supervisor+doctor); plan lands at docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md

## 2026-07-15T12:16:10Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B plan authored + committed (1c1fc3f): docs/superpowers/plans/2026-07-15-native-pivot-mB-dispatch.md -- 12 tasks, T1-T5 launch-contract substrate (registry v2, outcome store, Stop-hook writer, dispatch_bg short-id join, discriminator+epoch freeze), T6 UL continuity FIRST feature (structured isApiErrorMessage/429 transcript gate, fork-steer resume), T7-T9 steer/stop-tombstones/archival, T10 M-A handoff fast-follows, T11 doctor pin-version+legacy-mix, T12 FLEET_LIVE pin tier + docs sweep. Key find: synthetic 429 record has structured keys (isApiErrorMessage/apiErrorStatus) -- detection gates on those, not text regex; observed reset time is local-format not ISO so null-horizon parks + --force-now are the realistic path. Awaiting operator go for subagent-driven execution.

## 2026-07-15T15:15:02Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B execution: T1-T3 substrate merged to fleet-impl (a4eecbf, pushed): registry v2 + outcome store (atomic CreateFileW append after PROVEN O_APPEND loss), Stop-hook outcome writer (shape guards + path tokens), dispatch_bg (pre-sid exclusion, error-contract, injectable clock). Hybrid pipeline: fleet workers implement in worktrees, subagent review pairs (spec + adversarial w/ repro+fault-inject), fix waves, re-review, merge-on-green. 6 fix-wave findings so far were brief-inherited -> process change mid-campaign: plan snippets demoted to indicative for T4+. T4 (cmd_spawn native) worker running.

## 2026-07-15T17:22:56Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B: T4+T5 merged (33d20ca pushed) -- cmd_spawn native + outcome discriminator live. Dogfood proof: mb-t5 was the first production --bg worker, its result arrived via the Stop-hook outcome record; mb-t6 (UL continuity, spec 5.1.1) now running natively. Review pairs killed: completed-task-rollback (2C), tombstone-laundering (1C), stamp-lock stranding (1C). Cross-cutting items parked for final review: cmd_clean native gap (T8 owns), OSError-escapes-commit-retry (4 sites), postcompact wrong-shape gap, persist-freeze stale print. OPS GUARDS active: no fleet clean while native workers live; wait via outcome-record polling.

## 2026-07-15T18:11:19Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

MILESTONE: spec 5.1.1 usage-limit continuity COMPLETE and merged (T6, review pair + fix wave + re-review ALL-FIXED clean). Detection = structured isApiErrorMessage/429 gate + last-substantive-record discipline (stale-429 false-parks killed), OSError-proof scan (locked transcript cannot crash fleet status), mtime-freshest transcript pick, null-horizon parks + resume-limited fork-steer per G2(b). Standing goal 2 substrate live. fleet-impl + main pushed. T7 (steering) next.

## 2026-07-15T22:52:09Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B T7-T11 merged (eec028b..now): steering w/ 2 fix waves (double-fork race killed), stop/tombstones + cp1252 fix, tombstone-first archival, handoff fast-follows + abort evidence rule, doctor pin-gate w/ per-check isolation. 11/12 tasks done. T12 next: FLEET_LIVE pin tier + docs sweep, then final whole-branch review.
