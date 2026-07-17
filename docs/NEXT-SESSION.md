# Next session — after M-C (pivot COMPLETE, closed 2026-07-17)

Previous handoff (M-C: deletion + SPEC v3) is superseded — fully executed and closed. Campaign record: `knowledge/lessons.md#2026-07-17-mc`. Supervisor journal has the blow-by-blow.

## State (all verified at close)

- **The native-substrate pivot is DONE: M-0, M-A, M-B, M-C shipped.** `main` = `fleet-impl` = `187ce0f`, pushed. fleet.py 7378 lines (was 9345); **1054 unit tests + 6-pin FLEET_LIVE tier green at close**; doctor all-PASS.
- **`docs/SPEC.md` is v3, SPEC OF RECORD** (authored `mc-spec`, adversarial review fix-wave `30e2441` applied, manager-promoted — no self-promotion). v2.3 history intact in `docs/SPEC-v2-history.md`. The G-row contract stays `docs/specs/native-substrate.md` (pin-tested at 2.1.211; doctor pin-gate enforces re-runs on version bumps).
- **Autoclean is LIVE on this machine**: schtasks `claude-fleet-autoclean` every 6h, `--fleet-home` pinned to `C:/proga/claude-fleet`, doctor-monitored. Tier 1 archives stale workers (24h TTL), tier 2 sweeps fleet-owned daemon husks (sid-based default-deny), tier 3 (tombstone expiry) default-OFF. `fleet clean` remains the only file deleter.
- M-C also delivered: 9 debt items, supersession banners, §6 deletions (every class grep-receipted to 0), dispatch hardening — grace window (roster startup transient) + attach-verify/single-verified-wedge-retry (C1 double-launch caught pre-merge by the review gate).
- Residual fleet: 5 idle `mc-*` workers + their `C:/proga/fleet-mc-*` worktrees — **leave them; autoclean retires the workers, then the worktrees are removable** (`git worktree remove` + branch delete; branches all merged).

## The job: pick and run M-D

Priority-ordered candidates (operator signals from 2026-07-16 conversation embedded):

1. **Three-tier command** (`docs/specs/three-tier-command.md`, DRAFT-PROPOSAL — operator-originated: human-facing interface session / background supervisor-as-fleet-worker with scheduled beats / workers). Run an **adversarial design review first** (no build before the gate; the draft's own Hazards section is the review brief seed). Build deltas if ratified: `fleet sup-spawn`, `fleet init --supervisor-beat N` (reuse the autoclean schtasks plumbing + its N1 guard lessons verbatim), `NEEDS-OPERATOR` journal kind + interface-tier nag, **per-body claim nonce** (closes the zombie-manager class — a fork-session restart created a second live supervisor sharing claim+sid; the claim protocol is blind to it).
2. **Token-efficiency clause** (operator ask): fold terse compressed-output contracts into `knowledge/playbooks/campaign-template.md` + `spawn-etiquette.md` task-brief boilerplate (tier-boundary messages only; code/commits/specs/review-verdicts stay full-precision). Cheap, do it alongside whatever else runs.
3. **UL horizon-parser gap**: "resets 12am (Asia/Qyzylorda)" unparsed → null-horizon park needing `resume-limited --force-now`. Small scanner fix + test (the exact message text is in the journal and lessons).
4. **Dogfood outward** (standing goal 5): a non-fleet campaign. Overdue — last external run was stupidbox 2026-07-09.
5. Small/cosmetic backlog: retired-fork sessions sitting `blocked` in the agents menu (consider autoclean tier-2 stop-then-rm extension or file upstream); live-test marker-isolation verify (post-N1 guards likely close it — confirm and delete the open-defect note from M-B lessons); zombie transcript `c787a667*.jsonl` kept as evidence — delete when the claim nonce lands.

## Standing rules (unchanged, they keep earning it)

- CLAUDE.md binds (py -3.13; forward slashes in hook commands; no Git-Bash `&`; views read-only).
- Adversarial+spec review pairs on every branch; **new-defect hunt on every fix wave** (fired 3/5 waves in M-C, including a reopened double-launch); grep-receipt gate on every enumeration; no author promotes its own spec.
- Never trust a mocked `run=` test as proof a real CLI call works — the live pin tier has caught production Criticals **seven times**. Run it at every merge gate and on every `claude` version bump.
- Roster/contract field-presence rules need a TIME AXIS — steady-state truths can be false during transitions (the M-C grace-window lesson).
- One steer per worker turn (two-message scope confusion is real); phantom steers in your own vocabulary → suspect your own lineage first (fork-session zombie), event-timeline + process census + `claude stop`, keep the transcript.
- During 529 storms: don't resume 100k-token subagent transcripts — re-brief a fresh lean agent; backoff 3m/10m/20m.
- Push `fleet-impl` + ff `main` at every green milestone. Supervisor GOALS.md binds the manager (frugality, long beats, 300–500k handoff band).
