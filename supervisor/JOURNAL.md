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

## 2026-07-16T01:36:45Z CHECKPOINT inc=inc-20260715T114655Z-a938 sid=0eb3c88e-5638-41fa-aa08-6a1b89d08732

M-B MILESTONE COMPLETE (4f52f37 on main): native dispatch shipped end-to-end -- launch contract on --bg, outcome discriminator, UL continuity (spec 5.1.1, standing goal 2), fork-steer, claude-stop kill/interrupt w/ tombstones, auto-archival (5.1.2), categories (5.1.3), handoff fast-follows, doctor pin-gate, FLEET_LIVE pin tier GREEN at 2.1.211 + recorded. Campaign: 12 tasks + final wave, 13 fleet workers implementing the substrate they ran on, subagent review pairs + fix waves killed ~15 Criticals pre-merge, pin suite caught 3 more invisible to all unit tests. 1162 tests (from 764). Knowledge captured. Next: M-C (deletion + SPEC v3) per docs/NEXT-SESSION.md -- soak first, deferred items enumerated in final-review.md.

## 2026-07-16T13:08:03Z SEIZED inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

seized from inc-20260715T114655Z-a938: holder roster-gone, heartbeat stale (41478s > 3600s)

## 2026-07-16T13:09:40Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

M-C campaign start (inc-20260716T130803Z-5325): scope = NEXT-SESSION.md (deletions per pivot-spec 6, banners per 3, SPEC v3, soak) + operator directive 'automatic agent cleanup' folded in as feature task. Fleet mixed: 10 native mb-* under TTL, 3 legacy (mb-t2/t3/t4) to retire before refuse_if_legacy deletion. Plan: 3 parallel workers (mc-debt, mc-autoclean, mc-docs) in worktrees, review pairs gate, deletions last after native-only confirmed.

## 2026-07-16T13:40:25Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

M-C wave 1 built: mc-debt (9/9 items, 1175 tests), mc-autoclean (fleet autoclean + clean tiering + init --autoclean schtasks + doctor check, 1219 tests, sid-based default-deny husk discriminator), mc-docs (banners on 4 docs + SPEC 4 amend + README reword, 7 commits). 5 review subagents launched (adversarial+spec pairs on code branches, single on docs). Known merge conflict: README touched by both mc-docs and mc-autoclean. Fleet cleanup done earlier: 10 archived, 3 legacy cleaned, 15 husks rm'd, registry empty = native-only confirmed.

## 2026-07-16T14:23:27Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

M-C review gate: 5/5 verdicts in. Spec reviews both fully COMPLIANT (mutation-verified fault-inject tests). Adversarial: mc-debt 1 MED (OSError retry re-runs non-idempotent commit_fns -> false orphaned + ceiling skip) + 3 LOW; mc-autoclean 2 HIGH (corrupt-registry fail-open husk sweep rm's fleet's own protected sessions; schtasks install can pin worktree fleet.py, no FLEET_HOME guard) + 1 MED + 2 LOW, foreign-session default-deny HELD under all injections; mc-docs no-critical, 7 findings, 4 ordered fixed (F33 appendix banner stopgap etc). Fix waves dispatched to all 3 workers via fork-steer. Banner variant '(mechanism only)' recorded in mc-delete task file. Host process restarted twice mid-campaign -- workers + subagent reviewers all resumed lossless (soak evidence for native dispatch).

## 2026-07-16T14:25:27Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

M-C review gate: 5/5 verdicts in. Spec reviews both fully COMPLIANT (mutation-verified fault-inject tests). Adversarial mc-debt: 1 MED (OSError retry re-runs non-idempotent commit_fns -> false orphaned + ceiling skip) + 3 LOW -> fix wave running. Adversarial mc-autoclean: 2 HIGH (quarantine fail-open -> mass rm of own workers next tick; schtasks task pins worktree fleet.py + drops FLEET_HOME) + 1 MED + 3 LOW, verdict NOT-scheduler-safe until fixed -> fix wave running (note: predecessor host process had already dispatched an overlapping fix wave before dying; both messages delivered, compatible). Docs: 7 findings, no Critical -> fix wave DONE (F1-stopgap/F2/F4/F7), re-review with new-defect hunt running. mc-delete task file updated with banner-variant grep note.

## 2026-07-16T14:44:46Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

M-C review loop closing: mc-docs CLOSED (db8a107, re-review ALL-FIXED + 2 LOW residuals fixed w/ grep receipts). mc-debt CLOSED (67cf788, re-review ALL-FIXED + fault-inject re-verified; _append_event_quiet mechanism kills retry-reruns-nonidempotent-commit_fn class; +N1 EPIPE guard, N2 fast-completion swaps). mc-autoclean fix wave 6/6 landed (96b9b34..6aed44a, 1246 tests, +27; no-registry-no-sweep, --fleet-home embedded, fail-closed query, path-based ownership, uuid-name refusal at choke point) -- final adversarial re-review running (2 HIGH demand re-verified repro before merge). Worker self-caught+removed a leaked uuid-named test session from real roster.

## 2026-07-16T14:46:11Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

mc/debt + mc/docs merged to fleet-impl (bfb6678), suite 1176 green, pushed. mc/debt: 9 roll-up items + retry-idempotency (_append_event_quiet mechanism) after re-review + polish. mc/docs: banners + SPEC v2.3 + README after 2 fix waves (fix wave minted a new MED, 4th confirmation of the doctrine). mc/autoclean fix wave done (6/6 incl both HIGHs: no-registry-no-sweep guard, --fleet-home embedded task command + worktree-install refusal); re-review with new-defect hunt running, focus on the new --fleet-home global flag. Merge of autoclean + main ff after its re-review returns clean.

## 2026-07-16T15:02:34Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

mc/autoclean waves: fix wave 1 (6/6 incl 2 HIGH), re-review minted N1/N2/N3 (5th fix-wave-mints-defect confirmation), micro-wave 2 fixed N2+N3 (2edadeb, quarantine-artifact presence guard — worker correctly rejected my suggested mtime comparison as unsound, rename preserves mtime), N1 dispatched separately after a two-message scope mixup the worker flagged honestly. LIVE FRICTION FINDINGS for lessons: (1) fleet wait returned early racing a fork-steer dispatch (worker status working + mail pending at wait exit); (2) two steer messages landed in one worker turn with conflicting scope — mailbox delivery batching needs a doctrine note (one steer per turn, or explicit supersede marker).

## 2026-07-16T15:21:22Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

PIN SUITE RED post-merge, root-caused live: --bg roster entries are STATE-ONLY for the first seconds (no status/pid until process attaches) -- contract's 'state-only = dead' rule false during startup transient; recompute verdicts a healthy newborn dead-suspected, fleet wait returns instantly. Deterministic today (2/2), green yesterday (window unsampled). NOT a merge regression -- latent since M-B, exposed by timing. Repro: temp-home spawn + wait -> dead-suspected in 1.5s, worker then completed PIN-OK fine. Fix dispatched to mc-autoclean: launch-grace window in recompute roster-dead branch (extend _launch_claim_expired precedent), contract doc amendment, tests. Pin rerun after. dbg husks rm'd (temp proj dir busy, cleans on reboot). 6th live-tier-catches-what-units-miss confirmation.

## 2026-07-16T15:28:32Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

mc-autoclean fully closed pending one gate: all review findings fixed (2edadeb residuals, bc92764 N1 marker-order, cd70ab3 doctor advisory), reviewer MERGE-READY + scheduler-safe YES. THEN worker's own live pin run found prod Critical #4-of-class: fresh --bg roster entry state-only for first seconds -> contract read as dead -> dead-suspected at 1.5s -> fleet wait returns instantly (pins 2/3/5 red; also explains this manager's own premature wait today). Fixed 8d04fe8 (dispatch grace window on last_dispatch_at, 600s shared constant, live-repro'd red pre-fix, suite 1267) + native-substrate.md contract amend. Final adversarial gate on that one commit running; merge x3 follows.

## 2026-07-16T15:32:04Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

MILESTONE: M-C wave 1 fully merged + soak-gated. fleet-impl 1d5174b pushed, main ff'd. 1278 unit tests, pin suite 3x consecutive 6/6 green. Discriminator dispatch-grace fix (startup state-only transient) merged after live pin catch + root-cause + red/green fix cycle. mc-delete spawned (387af19f) on the pivot-spec section-6 deletion wave: detached-Popen machinery, probe_liveness/probe-ctime, PID registry fields, logs pipeline, refuse_if_legacy retirement. Registry native-only precondition satisfied (fleet emptied this morning; all current workers native).

## 2026-07-16T15:41:03Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

POST-MERGE CHECKS: unit suite 1278/18 GREEN on merged fleet-impl (1d5174b, all three M-C branches). FLEET_LIVE pin tier RED 3/6 (pins 2/3/5 again) — grace fix treated symptom, real defect is fresh-outcome path live (worker stuck working forever, outcome never reads fresh). mc-autoclean steered to root-cause on mc/pinfix off merged tree with live repro + 6/6 bar. NOTE: merges/push/main-ff/mc-delete-spawn were done by the OPERATOR manually at green (standing directive) — reconstructed after initially suspecting a twin manager; predecessor host's pre-death fix-wave sends explain the doubled mailbox messages. main is ff'd+pushed WITH the red-pin defect — campaign progression blocked until pins green. mc-delete continues (deletion scope orthogonal to outcome-freshness surface).

## 2026-07-16T16:04:51Z PROPOSAL inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

Operator proposes three-tier split: human-facing interface session (thin context, brief-authoring) / background supervisor (claim holder, campaign mechanics, respawnable) / workers. Draft captured at docs/specs/three-tier-command.md — substrate mostly exists (durable bg sessions + mailbox + claim rituals + M-C scheduler bridge); deltas: fleet sup-spawn, fleet init --supervisor-beat, NEEDS-OPERATOR routing, doctrine that humans steer only via interface tier (today's phantom-steer incident is the motivating evidence). Token-efficiency: propose compressed output contracts mandatory at tier boundaries via campaign-template clause, NOT a plugin prerequisite. Candidate M-D campaign after SPEC v3; adversarial design review first, no self-promotion.

## 2026-07-16T16:11:19Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

INCIDENT RESOLVED: dual supervisor bodies. Phantom steers (14:23Z-16:03Z, 7 sends: 'final micro-wave', 'One last LOW advisory', 'URGENT root-cause task', ...) came from c787a667 -- a fork-session resume of THIS conversation created ~20:56 local during a host restart, running daemon-hosted with full campaign context, independently re-deriving and dispatching my decisions in paraphrase. Confirmed via transcript identity (same first user message), process census (fork-session --resume cmdline), event-timeline correlation (each phantom seconds-minutes after mine). Operator confirmed not-theirs. Zombie stopped via claude stop c787a667; transcript kept as evidence; user's own peek session 43c8e51d cleared (unrelated legit exploration). Claim-protocol gap exposed: both bodies share incarnation id + sid -- sup-claim cannot discriminate bodies of one lineage; logged as hazard in three-tier-command.md draft, lessons entry at close. mc-autoclean now on 0e9329c3 (zombie's steer) mid-turn on dispatch-path work, suite 1292 -- letting it finish, adjudicating output after.

## 2026-07-16T19:15:34Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

mc/delete merged to fleet-impl + pushed: pivot section-6 deletions complete, fleet.py 9345->7216, 1036 tests green, adversarial (no CRIT/HIGH, 5 injections red) + spec (fully compliant) + LOW sweep. Both workers rode a plan-limit park through midnight reset via resume-limited --force-now -- UL continuity battle-proven in production (note: 'resets 12am (Asia/Qyzylorda)' horizon format unparsed by scanner -> null-horizon park, G11 gap for lessons). mc/pinfix CRITICAL fix wave done (all 6 findings, injection red/green + live pin 6/6) -- re-review with new-defect hunt running. After pinfix verdict: merge onto post-delete base (dispatch_bg conflict expected), final live gate, SPEC v3.

## 2026-07-16T20:22:36Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

mc/pinfix merged (c63d7dd) after fresh-context re-reviewer returned merge-YES (4x 529 kills on the big-transcript reviewer -- lesson: resume-with-huge-context is 529-fragile, fresh lean agent with findings baked into brief got through). fleet-impl + main pushed @ c63d7dd: 1054 tests, live pin 6/6. M-C code COMPLETE. mc-spec spawned for SPEC v3 (draft-pending-review, no self-promotion). Remaining: spec review + promote, autoclean scheduled-task install from canonical home, lessons/INDEX/NEXT-SESSION, worktree cleanup.

## 2026-07-16T20:51:45Z CHECKPOINT inc=inc-20260716T130803Z-5325 sid=90bab65e-b4af-4c63-9c64-d4b4ea3d9037

CAMPAIGN CLOSE: M-C COMPLETE, NATIVE-SUBSTRATE PIVOT DONE (M-0 through M-C all shipped). main = 187ce0f: SPEC v3 promoted spec-of-record (author mc-spec, reviewer fix-wave applied, manager promotion), section-6 legacy deleted (-7130 lines), autoclean shipped + schtasks LIVE every 6h, dispatch hardening (grace window + attach-verify/wedge-retry after CRITICAL caught pre-merge), 1054 tests + pin 6/6 at close. Knowledge loop closed: lessons #2026-07-17-mc (zombie-manager class, roster time-axis, 529 re-brief-lean, UL prod proof), INDEX, NEXT-SESSION rewritten (M-D candidate: three-tier command + per-body claim nonce). M-B era worktrees pruned; mc-* worktrees await worker auto-archive (the new feature owns it). Incidents survived: dual-supervisor fork (stopped, evidenced), 2 host deaths, plan-limit park+resume, 529 storm. Operator asks delivered: automatic cleanup (live), three-tier proposal (drafted), token-efficiency plan (in draft + template clause pending M-D).

## 2026-07-17T01:12:00Z BOOT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

fresh claim: no existing claim -- fresh claim

## 2026-07-17T01:12:15Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

Succession: operator-authorized stop of stale body inc-20260716T130803Z-5325 (sid 90bab65e, bg session state=done, heartbeat 01:04:27Z). 'claude stop 90bab65e' verified; census clean (roster live=3, all mc-* husks; no second fleet-cwd session — no zombie evidence this time). sup-boot refuse->freeze (roster-gone+fresh-heartbeat, G9 heuristic blind to authorized stop); operator pre-ratified seize, INCARNATION cleared as delegate, fresh claim taken. G10: this record IS the old body's death record. New duties this incarnation: (1) operator directive — multi-platform (macOS+Linux) requirement into SPEC; (2) pin-gate re-run, claude 2.1.211->2.1.212; (3) M-D per docs/NEXT-SESSION.md: three-tier adversarial design review first, token clause, UL horizon parser.

## 2026-07-17T01:20:28Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

M-D open. Done: SPEC portability directive (21f3e77), token-clause template v1.6 (6c33f08). PIN TIER RED on claude 2.1.212 -- test_3 fork-steer: hooks did not fire in forked sid ('settings did not survive --bg --resume'), test_5 downstream. Fleet passes --settings on resume (fleet.py:6198). Re-running full tier for flake check; if repro -> contract break, 8th live catch, fork-steer (idle send + resume-limited) broken at 2.1.212. Task files written: md-review-break, md-review-spec (three-tier gate), md-ulparser. Spawns held until pin verdict.

## 2026-07-17T01:29:13Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

M-D wave dispatched (4 workers, all opus except ulparser=sonnet, bypass): md-contract (2.1.212 transient-daemon rehome, worktree md/contract, ceiling 4M, containment: temp FLEET_HOME + sid allowlist + daemon-stop ban), md-review-break + md-review-spec (three-tier dual-lens gate, docs-only on fleet-impl, briefs carry daemon-transiency evidence + today's succession-freeze evidence), md-ulparser (local-format limit horizons, worktree md/ulparser). ROOT CAUSE pinned before dispatch: 2.1.212 daemon origin=transient, idle-exit 5s (daemon.log receipts); rm/stop vs dead daemon fail without revival; agents --json reads stale roster.json; rm-with-live-daemon leaves --all entry. Pin tier = 8th live catch. Doctor pin-gate deliberately left RED until md-contract's pins go 6/6 (deviation from doctor-clean-before-spawn recorded: the spawns ARE the remedy).

## 2026-07-17T01:54:51Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

Design gate CLOSED: both lenses restructure, adjudication committed de4177a (10-item binding list; nonce prerequisite; event-driven arm dropped; beat must be first-class verb; scheduler bridge via platform adapter 3-OS). 2 shipped-code defects filed. ulparser: 1063/1063 manager-verified, hostile reviewer d8ea1ef2 running. md-contract still working. PR #2 (reviewer side-effect, off-main) closed after cherry-pick. Next: md-contract lands -> merge gate -> nonce spec slice.

## 2026-07-17T02:00:05Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

md-contract landed (4 commits on md/contract, unpushed): premise-correction — rm-with-live-daemon WORKS; confound was probe context (bg worker holds daemon open as client; dead-daemon path unreachable from bg sessions — my interactive runs hit idle-exited daemon). Fix: 3-way rm/stop outcome classification by message (already-gone/dead-daemon-retryable/real-failure), pins de-confounded 6/6, new test_native_daemon_transient.py, G-rows amended PENDING-RATIFICATION, zero roster reads changed (16/16 receipts cleared them). Q2 properly BLOCKED (daemon-run takeover risk with 10 live workers). Manager truth gate: 1075/1075 in worktree personally. md-contract-review (opus, injection-mandated) spawned; md-ulparser-review still working. Merge gates after both verdicts. NOTE for merge: post-merge FLEET_LIVE run from THIS interactive session doubles as the dead-daemon hygiene-path verification md-contract could not do.

## 2026-07-17T02:18:17Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

Waves in flight: md-ulparser fix ee68eb6 landed (anchor->record-timestamp, 1068/1068) -> re-review at md-ulparser-review (new-defect hunt mandated). md-contract-review verdict fix-wave (M1 starved-husk-sweep invisible to doctor/stamp -- injection stayed green; M2 grep receipt 14/16, omitted _sweep_husks own read; M3 miscounts; M4 RM_TRANSIENT provenance false for dead-daemon string + dash variants; M5 stop unclassified, kill-path spec claim false at both _cmd_kill_native sites; spurious_fix=none, 5/5 injections red, doctrine clean) -> M1-M5 fix wave sent to md-contract. Merge order after green: md/ulparser first (small), then md/contract; post-merge FLEET_LIVE from interactive session = dead-daemon hygiene verification.

## 2026-07-17T02:44:35Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

ulparser re-review: wave-1 3/3 FIXED but minted N2 BLOCKER (fromisoformat trailing-Z is 3.11+, floor is 3.10 -> C1 silently reverts on 3.10) + N1 fixture-vs-production + N3 wall-clock fallback should be null park. Wave 2 of max 3 sent to md-ulparser. Contract M-wave: 5/5 disposed, no disputes (both disputed receipts confirmed AGAINST builder), M5 took classify-stop option (kill on gone sid now exit 0 + real outcome, tombstone kept), m1 rm-by-roster-id, 1097/1097 + pins 6/6; re-review sent to md-contract-review (new-defect hunt: stop classification masks, rm-by-id absent-roster path, deferral surfaces, pin still tests daemon not bookkeeping). Operator open item logged: 3 dead-daemon claims remain manager-report-only (both waves are bg sessions, physically cannot observe) -- quiet-machine interactive G9 probe at merge gate covers it.

## 2026-07-17T03:28:00Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

md/ulparser MERGED (2 waves + merge verdict; post-merge 1080/1080; live tier deferred to contract merge with rationale). Contract wave 2: ND 3/3 disposed incl ND-1 fail-unsafe kill (stop-by-captured-id fix + repro re-run), builder self-identified error class 'fix at one call site, not its twin' as standing check. Final re-review dispatched (fail-direction check on _daemon_alive, streak boundary, residual derived-id paths). Reviewer process note: backticks in double-quoted commit body got shell-expanded silently -- lessons candidate.

## 2026-07-17T13:45:26Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

Host restart overnight (~10h gap): same sid resumed, heartbeat refreshed (NOTE claim wart: sup-boot REFUSES its own holder when heartbeat stale -- self-recognition missing, feeds nonce spec + lessons). md-contract-review final-gate turn died with restart (no commit = only truth; registry working was stale, fork sid gone from roster) -> interrupt + respawn --task rereview2. Awaiting verdict; then merge md/contract, FLEET_LIVE from interactive session, doctor, push, close-out wave.

## 2026-07-17T15:32:48Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

md-contract-review parked limited overnight-resume path: horizon 'resets ...' PARSED to 2026-07-17T15:30:00Z by the newly-merged local-format parser -- first production validation of md/ulparser -- resume-limited cleared it cleanly. Reviewer back working on final gate. Prior monitor loop was PATH-broken (grep not found post-restart) -- fixed with explicit PATH export.

## 2026-07-18T03:36:41Z CHECKPOINT inc=inc-20260717T011200Z-f1d0 sid=8b0d1ec8-a531-4a43-9a01-3827d786d1c3

M-D CLOSED + PUSHED (ea1dc1e, main=fleet-impl). Both branches merged: md/ulparser (UL local-format parser, 2 waves) + md/contract (2.1.212 transient-daemon rehome, 3 waves). Post-merge: unit 1136/1136, FLEET_LIVE 6/6 from interactive session (dead-daemon hygiene path verified -- the check bg workers structurally couldn't do), doctor all-PASS, pin-gate re-stamped 2.1.214 (claude bumped 211->212->214 across campaign). Knowledge wave: lessons#2026-07-18-md, INDEX, template v1.7 (probe-context + vendor-bump gates), NEXT-SESSION rewritten. OPERATOR GATES OPEN for M-E: (1) ratify native-substrate.md 2.1.212 G-row amendments [PENDING], 3 dead-daemon claims still manager-report-only; (2) three-tier RESTRUCTURE review-ratified not operator-ratified, nonce = prerequisite slice. Deferred to M-E: nonce spec, 2 shipped-code defects (handoff no-hooks, autoclean predicate), ND-4+nits, dogfood-outward overdue. Tasks 8/9 stay pending-next-campaign.

## 2026-07-21T15:06:30Z SEIZED inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca

seized from inc-20260717T011200Z-f1d0: holder roster-gone, heartbeat stale (300590s > 3600s)

## 2026-07-21T15:12:26Z CHECKPOINT inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca

M-E open. BOOT inc-20260721T150630Z-2c07 (predecessor heartbeat 300569s stale, roster empty, no zombie evidence). 9TH LIVE CATCH, vendor-bump gate fired on claude 2.1.216: pin tier RED at test_1 -- '--bg dispatch exited 1: Couldn't reach the background service (did not become reachable within 45s)'. ROOT CAUSE = STALE DAEMON LOCK + PID REUSE: ~/.claude/daemon.lock named pid=15740 (daemon started 2026-07-20T23:25Z, died); Windows recycled pid 15740 to WacomHost (a service whose StartTime is ACCESS-DENIED to a normal-token reader); every new daemon logs 'another daemon won the lock race (pid=15740) - exiting'; ALL --bg dispatch dead machine-wide. The lock DOES carry procStart ticks 639202047274516770 (= 2026-07-21T04:25:27 local, matches the dead daemon) so the vendor HAS the discriminator and did not use it (or could not read the impostor's start time and defaulted to alive). 'claude daemon stop --any' says 'no daemon running' and does NOT clear the lock -- recovery required rm of daemon.lock (backed up to scratchpad). After clear: pin tier 6/6 GREEN on 2.1.216, contract itself unchanged; record_pin_pass 2.1.216, doctor 21 PASS 0 FAIL. FLEET GAP (M-E item 0): doctor was ALL-PASS while every dispatch was dead -- no daemon-reachability check exists, and the dispatch error is surfaced raw. Probe context: interactive manager session, quiet machine, zero live workers.

## 2026-07-21T15:55:02Z CHECKPOINT inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca

M-E wave 1 all four branches landed, five reviewers in flight. me/ul 4b8a88e (1145 green, manager-verified). me/defects ef0747f+0cbc517 (1147): Defect A resolved as SANCTION-the-second-path -- grep proved TWO --bg argv builders, a re-route is unsafe (incarnation ids fail NAME_RE; task file already written+journaled by path; wedge-retry would double-spawn a successor) -> --settings + env=_worker_env + pre-lock settings pre-flight, SPEC 6 rewritten; Defect B whole-token identity (script+subcommand+--fleet-home). me/nonce ccbbc02 (1258-line spec, Status: drafting, 31 receipts) -- CORRECTED 3 of its own briefing sources incl. the adjudication's 6-anchor list being short by 5 and _restamp_after_steer having 1 call site + an undocumented inline duplicate @3428. me/daemon d97f6de..1015344 (1170 green). MANAGER TRUTH GATE CAUGHT A MAJOR on me/daemon: replayed the REAL outage artifacts (preserved stale lock + machine daemon.log) through the shipped _doctor_check_daemon_wedge -> ok=True, '1 late lock-race refusal (< 3) -- no wedge signature'. The detector PASSES on the exact 16h outage it was built from. Root data: the real log holds 4 lock-race refusals across a week and only one is the wedge -- benign races are routine (3 in a week, each naming a live-and-serving winner), so the threshold was defending real false-positive pressure and the SIGNAL is what is wrong, not the constant. Constraint on any fix: the check must not shell out to anything that can start a daemon (claude agents restarts it). Baked into me-daemon-review as mandated finding M1 with the replay receipt; M2 = the row cites docs/LEDGER.md which does not exist (ledger is docs/PLAN-PROGRESS.md). Reviewers live: me-ul-review, me-defects-break, me-defects-spec, me-nonce-break, me-nonce-spec, me-daemon-review. Nothing promoted, nothing ratified; both operator gates still open.

## 2026-07-21T16:06:26Z CHECKPOINT inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca

Nonce design gate CLOSED: both lenses in, adjudication committed (docs/reviews/ME-NONCE-ADJUDICATION-2026-07-21.md). break=restructure (5C: bearer secret as authorization credential on a substrate with no privilege separation -> three unauthenticated recovery paths forced, each keyed on a value sup-status prints; Rule 0 disables the roster-liveness guard for exactly the incident-1 class; FLEET_SUP_NONCE leaks via _worker_env). spec=fix-list(S1-S24), factual base RELIABLE -- 31/31 receipts reproduce byte-for-byte, 3 incidents verbatim at source, nothing confabulated, [UNBUILT] clean -- short only on completeness (5 missing touchpoints, S4 verb partition contradicts spec-of-record, S5 miscites the adjudication). Lenses do not conflict: facts sound, design unsound. Spec's own 4.5 (byte-identical bodies => undecidable) falsifies its own 5.4/5.6 and the author did not notice. SURVIVES: detection property (100min forensics -> 1 refused command), section 3 receipts, 5.3 lineage. Re-draft wave dispatched to me-nonce (items 1-12), Status stays drafting, 4 operator questions surfaced and deliberately NOT decided (chief: on this box no authorization input exists that is neither view-derivable nor an env var, so the honest options are detection-only / knowingly-bypassable gate / build an auth input first). 3 shipped-code defects filed: _require_claim_holder has no FLEET_WORKER refusal (a worker turn can hold the supervisor claim, prevented only by accident); supervisor/INCARNATION.tmp not gitignored; exit-code contract mismatch (docs say 0/2/3, code has a 4 with no seam). me/ul fix wave in flight. Awaiting me-defects-break + me-daemon-review.

## 2026-07-21T18:59:43Z CHECKPOINT inc=inc-20260721T150630Z-2c07 sid=4f3af931-099c-4bc4-bafa-077671feffca

M-E CLOSED + PUSHED (de9c62f, main=fleet-impl). Four branches merged: me/ul (UL D1-D4 + closed fixed-offset tz set, 4 waves), me/daemon (daemon-wedge doctor check + dispatch classifier + ND-4/nits, 2 waves), me/defects (successor dispatch settings+env+mode; autoclean full-identity ownership, 2 waves), me/nonce (claim-nonce spec at DRAFTING + tools/verify_receipts.py bound to tests/test_receipts.py; merged, REVERTED ON RED, fixed, re-merged). Post-merge: unit 1302/6skip, FLEET_LIVE 6/6 on 2.1.216 from this interactive session, doctor 23 PASS 0 FAIL, pin stamped 2.1.216. 9TH LIVE CATCH was the SUBSTRATE: stale daemon.lock + Windows PID reuse onto a service with unreadable StartTime -> all --bg dispatch dead ~16h while doctor read all-PASS. Knowledge wave done: lessons#2026-07-21-me, INDEX, template v1.8 (VANTAGE gate, FOUNDING-INCIDENT gate, demand-driven-evidence rule, reviewer-remedies-are-fix-waves, receipts-as-executable-claims, merge-target testing, commit-only, RESULT-line exemption), NEXT-SESSION rewritten. MANAGER ERRORS THIS CAMPAIGN, all worker-caught with receipts: M0 filed from the wrong VANTAGE (worktree vs canonical home) -- regression never existed, disproved by AST body diff; DQ1 tz ruling superseded (ZoneInfo guards unparseable, not resolvable-but-wrong); adjudication item 3 withdrawn as over-specification after the reviewer overturned its own CRITICAL's remedy on the author's receipts; sequencing item 3 rested on a false premise (detection-only does NOT close incident 1). AND a close-out error caught by myself: deleted the six reviewer branches as 'merged cleanup' when they were never merged -- 7336 lines of review evidence lived only there; recovered from the object store at the tips and committed. Standing rule added: a review branch is EVIDENCE, not scratch. OPERATOR GATES OPEN: (1) 8 [PENDING OPERATOR RATIFICATION] rows in native-substrate.md (2.1.212 set + the new 2.1.216 wedge row); (2) claim-nonce spec at drafting, both final gates sound/closed, FIVE questions waiting -- load-bearing one: no authorization input exists on this box that is neither view-derivable nor an env var, so options are detection-only (does NOT close the zombie incident) / knowingly-bypassable gate (the only one that does) / build an auth input first; (3) SDD v3 untouched; (4) three-tier re-draft gated on (2).
