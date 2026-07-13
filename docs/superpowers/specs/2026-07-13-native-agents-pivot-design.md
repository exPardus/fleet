# Native Agents Pivot — Design

**Date:** 2026-07-13
**Status:** approved-design (pre-plan)
**Approach:** B — native substrate, fleet sidecar (chosen over pure-native replacement and agent-teams bet)

## 1. Problem and decision

claude-fleet currently owns the entire worker lifecycle: detached-Popen launch, PID probing, liveness verdicts, reaping. Claude Code now ships a native background-agent substrate — the agents screen (`claude agents` TUI), a per-user daemon (`~/.claude/daemon/`), background dispatch (`claude --bg`), attach/peek/pin/stop, and a scriptable roster (`claude agents --json`). Roughly half of fleet's registry/lifecycle machinery duplicates it.

Decision: rebase fleet onto the native substrate. The daemon owns **process lifecycle** (spawn, liveness, reap, attach). Fleet keeps what native lacks — the **semantic layer**: task identity, mailbox mid-turn steering, per-worker budget caps, journal + respawn-with-journal, the knowledge loop. Additionally, introduce a **long-lived supervisor**: a persistent-identity manager session that survives reboots and context exhaustion, visible and pinned in the agents screen.

Rejected alternatives:

- **A. Pure native replacement** — loses mid-turn steering, budget caps, journal carry, and the knowledge loop; transcript format is explicitly unstable, so results-by-transcript-scraping is fragile. The C0–C4 capabilities live in hooks and would be discarded for no gain.
- **C. Agent teams** — closest match to the "supervisor in tandem with agents" vision, but experimental (env-flag gated), in-process only on Windows, and session resume loses teammates, which is fatal for a persistent supervisor. Revisit when stable.

## 2. Verified native surface (2026-07-13, this machine)

Confirmed by direct probing:

- `claude agents --json [--all]` — lists interactive **and** background sessions across all projects, with `sessionId`, `cwd`, `pid`, `kind`, `name`, `status`/`state`. No TTY required.
- `claude --bg "<task>"` — dispatches a background session managed by the daemon; session appears in the agents screen.
- Agents screen TUI — attach, peek+reply, rename, pin (`pins.json` exists), stop.
- Daemon state at `~/.claude/daemon/`: `roster.json`, `pins.json`, `control.key`, `pipe.key`, `dispatch/`, per-job dirs. Treated as **private** — fleet never reads or writes daemon files; the only sanctioned interfaces are the `claude` CLI and its `--json` output.

Reported but **unverified** (research-agent claims; M-0 must confirm or refute):

- `--bg` composing with `--settings`, `--permission-mode`, `--model`, naming.
- Hooks firing inside background sessions.
- Idle non-pinned sessions reaped after ~1 hour; pinned sessions exempt.
- Sessions do not survive machine reboot (show failed/gone in roster).
- Mid-turn steering has no public CLI (peek+reply is TUI-only).

## 3. Architecture

```
agents screen (claude agents TUI)          ← user's window (Anthropic-provided UX)
        │
native daemon (~/.claude/daemon)           ← process lifecycle: spawn, liveness, reap, attach
        │
worker = claude --bg session               ← spawned from project cwd, fleet hooks inside
        │
fleet sidecar (bin/fleet.py + hooks)       ← semantics: task, mailbox steering, budget, journal, knowledge
        │
supervisor = pinned session                ← persistent identity in files, disposable body
```

The registry becomes an **overlay keyed by native `sessionId`**: task snapshot, budget cap, journal path, mailbox pointer, knowledge links, campaign tags. Liveness truth comes from `claude agents --json`, never from PID probing. One worker, two views: the agents screen shows liveness and offers attach/peek; `fleet status` merges the roster with the overlay to show task, cost, budget, and mail.

### Superseded prior-spec surface

This pivot supersedes — it does not silently contradict — the following:

- `docs/specs/portability.md`: the probe-ctime / boot_id / `killpg` liveness machinery solves a problem the daemon now owns. Mark superseded sections with a `[SUPERSEDED — native-substrate pivot 2026-07-13]` banner and a pointer here. MOVE stale pins, never delete (C4 lesson).
- `docs/SPEC.md` v2.2: launch plumbing (§ detached spawn), PID-based liveness verdicts, and quarantine paths tied to PID truth. Same banner treatment. SPEC v3 amendment lands in M-C.
- Unaffected and still binding: terminal-surface rules (views read-only, no locks, exit 0), mailbox protocol, budget hooks, knowledge loop, campaign-template doctrine.

## 4. Supervisor — persistent identity, disposable body

**Soul** = git-tracked files in the claude-fleet repo:

- `supervisor/GOALS.md` — the single target plus standing goals; user-editable at any time.
- `supervisor/JOURNAL.md` — append-only decision/checkpoint log: campaign state, in-flight workers, pending decisions, next actions. The supervisor writes a checkpoint after every meaningful decision, not just at shutdown.
- `knowledge/` — unchanged, already the cross-session memory.

**Body** = a pinned session in the agents screen. Any incarnation is disposable.

**Boot ritual** (SessionStart hook extension + skill step): read `GOALS.md`, tail of `JOURNAL.md`, `knowledge/INDEX.md`, `claude agents --json`, and `fleet status`; reconcile the overlay against the live roster (roster-gone workers → sticky dead → respawn decisions); then continue where the journal left off. The same ritual covers a fresh morning, a post-reboot recovery, and a context-exhaustion respawn — one code path.

**Context management** = checkpoint discipline, not eternal compaction. When context nears the limit, the supervisor writes a handoff checkpoint to the journal, dispatches a successor (`claude --bg`, pinned, boot ritual), and ends its own session. Continuity lives in the files, so the successor resumes mid-campaign.

**Liveness between events**: ScheduleWakeup/loop heartbeats inside the session for watchtower duties (worker health, mail routing, respawn-on-death).

**Scope fence**: standing goals and self-improvement behaviors are a later layer on top of this substrate. This build delivers the identity + boot ritual + checkpoint mechanics only.

## 5. Native dispatch

`fleet spawn` rewires to: run `claude --bg "<task>"` from the project cwd with `--settings worker-settings.json --permission-mode <mode> --model <model>`, capture the sessionId, and write the overlay entry. Workers appear in the agents screen; attach/peek/pin come free.

- **Steering**: mailbox + hooks, unchanged. Hooks fire inside the bg session (M-0 verifies), so `fleet send` mid-turn steering, budget ceilings, journaling, and the knowledge loop all keep working — hooks do not care who spawned the process.
- **Respawn**: `fleet respawn` = new `--bg` dispatch, same overlay identity, carried journal + drained mailbox, new native sessionId. The `--task @file` re-pass rule stands.
- **Kill/interrupt**: signal the pid exposed in `agents --json`, or use the native stop path if one is scriptable — exact mechanism resolved in M-0/plan. Never touch daemon files.
- **Status/views**: merge roster + overlay. Terminal-surface rules hold: views never lock, never probe, never write, exit 0.
- **Reap awareness**: the daemon may stop idle non-pinned sessions (~1 h). Normal workers finish well inside that; long-soak workers get pinned or respawned by the supervisor's watchtower beat.

## 6. Deletions (M-C)

Dies from `bin/fleet.py`: detached-Popen launch machinery, PID probing, probe-ctime/boot_id portability code, registry liveness fields, quarantine paths premised on PID truth.

Stays: mailbox, journal, budget, knowledge, and `spawn`/`respawn`/`send`/`status`/`kill` as thin wrappers over the native surface plus the overlay.

## 7. Risk and its gate

**THE risk**: coupling to an undocumented `--bg`/daemon surface that can drift under `claude` updates.

Mitigations:

1. **M-0 spike first** — verify every "unverified" item in §2 before any build. Findings become `docs/specs/native-substrate.md`, the contract doc listing exactly which flags, JSON fields, and behaviors fleet depends on. If the spike refutes a load-bearing assumption (hooks not firing in bg sessions would be the killer), the pivot halts at M-A and the design is revisited.
2. **Pin-test tier** (like FLEET_LIVE): dispatch a tiny haiku bg worker, assert the JSON contract fields and hook firing, tear down. Run in CI-equivalent and before campaigns.
3. **Doctor check**: `claude --version` changed since the last pin-test pass → warn before spawning.
4. **No daemon-file access**: CLI-only interface keeps drift surface minimal.

## 8. Milestones

- **M-0 — spike + contract.** Probe the native surface (§2 unverified list), write `docs/specs/native-substrate.md`. Cheap; kills or confirms everything downstream.
- **M-A — supervisor identity.** Soul files, boot ritual, checkpoint discipline, successor handoff. Runs against today's backend unchanged — value even if M-B stalls.
- **M-B — native dispatch.** Spawn/status/kill rewired onto `--bg` + roster, overlay registry, pin-test tier, doctor check.
- **M-C — deletion + SPEC v3.** Retire duplicated lifecycle code, banner superseded spec sections, soak campaign (external-dogfood style) before declaring done.

## 9. Testing

- pytest units: overlay read/merge, roster-JSON parsing (fixture-based), boot-ritual assembly, checkpoint write/read round-trip.
- Integration: haiku worker dispatched via `--bg` in a temp dir — full lifecycle spawn → steer → result → respawn.
- Pin tests: native-surface contract assertions (§7.2), version-gated skip when `claude agents` unavailable.
- Existing suites keep passing until M-C removes the code they cover; removals delete tests in the same commit.
