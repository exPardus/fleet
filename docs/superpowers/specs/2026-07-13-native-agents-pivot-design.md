# Native Agents Pivot — Design

**Date:** 2026-07-13
**Status:** v2.2 — v2 per adversarial review (`docs/reviews/NATIVE-PIVOT-REVIEW-2026-07-13.md`); v2.1 fixed re-review N1–N11; v2.2 fixed promotion-review F1–F4; re-promotion pending
**Approach:** B — native substrate, fleet sidecar (chosen over pure-native replacement and agent-teams bet)

## 1. Problem and decision

claude-fleet currently owns the entire worker lifecycle: detached-Popen launch, PID probing, liveness verdicts, reaping. Claude Code now ships a native background-agent substrate — the agents screen (`claude agents` TUI), a per-user daemon, background dispatch (`claude --bg`), scriptable `claude stop/logs/attach <id>`, and a scriptable roster (`claude agents --json`). Part of fleet's lifecycle machinery duplicates it.

Decision: rebase fleet onto the native substrate. The daemon owns **process hosting** (spawn, liveness, attach UX). Fleet keeps the **semantic layer**: task identity, mailbox steering, per-worker budgets, journal + respawn-with-journal, result capture, the knowledge loop — and, critically, **re-implements SPEC v2's lifecycle discipline (launch contract, completed-vs-died discrimination, never-demote-unknown, one-live-claude) on the new substrate rather than deleting it**. Additionally: a long-lived **supervisor** — a persistent-identity manager session surviving reboots and context exhaustion.

Rejected alternatives:

- **A. Pure native replacement** — loses mid-turn steering, budget caps, journal carry, knowledge loop; transcript format explicitly unstable. C0–C4 capabilities discarded for no gain.
- **C. Agent teams** — experimental (env-flag gated), in-process only on Windows, session resume loses teammates — fatal for a persistent supervisor. Revisit when stable.

## 2. Native surface: verified, refuted, and gated

### Verified (2026-07-13, this machine — receipts in the review doc)

- `claude agents --json [--all]` — lists interactive and background sessions across all projects, no TTY. **Fields are optional and state-dependent**: done background entries may lack `pid`/`name`/`status`; `status` (interactive) and `state` (background) are distinct axes and can co-occur contradictorily. The M-0 contract doc must pin field presence per state; nothing may depend on `pid` existing.
- `claude --bg "<task>"` — dispatches a daemon-hosted background session (a PTY-hosted interactive TUI, **not** print mode). Prints a short id that prefixes the full `sessionId`.
- `claude stop <id>` / `claude logs <id>` / `claude attach <id>` — real, scriptable, hidden from top-level help. `stop` transitions the session to `state: done`. `logs` returns a raw ANSI screen dump — **unusable as a data source**.
- `claude --session-id <uuid>` — caller-minted session ids exist; `-n/--name` exists. Daemon auto-naming is unreliable — fleet always passes `-n`.
- Daemon/job state: `~/.claude/daemon/` (roster.json, control/pipe keys, dispatch/) **and `~/.claude/jobs/`** (per-job dirs, pins.json). Both are private: fleet never reads or writes either; sanctioned interface = `claude` CLI + `--json` only.

### Refuted (print-only features that vanish under `--bg`)

- `--output-format stream-json` and `--max-budget-usd` work only with `--print`. The current per-turn log pipeline (`logs/<name>.jsonl`) and the budget-cap flag **do not exist** under `--bg`.

### M-0 gate list — each item load-bearing; refuted ⇒ named fallback or halt

| # | Question | Halt-grade? | Fallback if refuted |
|---|----------|-------------|---------------------|
| G1 | Do fleet hooks (`--settings worker-settings.json`) fire inside a `--bg` session — PreToolUse, PostToolUse, **and Stop**? Sharper Stop experiment: stop-block honored? roster state during block? does the reap timer treat a stop-blocked session as active? | **HALT** | none — pivot dies at M-A |
| G2 | Second-prompt delivery to an idle bg session (steer-idle). Any of: `claude --bg` composing with `--resume`, a send CLI, dispatch-into-existing-session? | **HALT-grade** | respawn-to-steer: `claude stop` the idle session first, verify roster transition, then dispatch replacement with drained mailbox; sid swap atomic under `fleet.lock`. Never two live sessions under one name. Semantics + cost change — §5 states it |
| G3 | Result/cost source under `--bg`: does any structured artifact expose per-turn result text and cost (roster field? result file? hook payload)? | HALT-grade | result capture moves fully into fleet's Stop hook (writes result + transcript-derived cost to fleet journal); if hooks can't see cost, cost column declared dead and budget = token-ceiling hook only |
| G4 | Env propagation: do `--settings`, env vars (`FLEET_WORKER` stamp), and the `CLAUDE_CODE_SESSION_ID` strip reach the daemon-spawned child? | **HALT** | none — D5 + SPEC §5.1 provenance guard are non-negotiable |
| G5 | Scriptable pin/unpin, or any reap exemption? What is the actual reap window? | no | heartbeat-respawn becomes primary: supervisor beat period < reap window; supervisor self-preservation via G7 |
| G6 | `--session-id` composes with `--bg` (fleet mints sids → pre-claim launch contract preserved)? | no | short-id capture from `--bg` stdout + `agents --json` join; concurrent-spawn attribution via `-n`. **Crash-safety degrades on this path**: sid unknown between dispatch and stamp — recovery = roster join on `-n`; no roster match within the verify window ⇒ claimed entry marked DOA |
| G7 | In-session scheduling primitive for heartbeats (name the real one — /loop or equivalent; "ScheduleWakeup" unverified). Cost per beat? | HALT-grade for watchtower duties | event-driven only: supervisor acts when user opens it or hooks poke it; watchtower scoped out until primitive exists |
| G8 | Prompt delivery size: can a large composed prompt (preamble + mailbox + task + carried journal, > 32,767 chars) reach a `--bg` session — stdin, prompt file, or argv only? | no | task-file bootstrap: argv carries a tiny fixed prompt ("read `<task-file>` and execute it"); the composed body lives in a fleet-written file the worker Reads as its first action. No size cap. (SessionStart `additionalContext` is NOT a viable channel — hard-capped at 10,000 chars, 3× smaller than the problem) |
| G9 | Daemon restart (incl. `claude update`) with workers live: do sessions survive? Does roster persist or reset? Do pins survive? | no | roster-epoch sanity check (§5) is mandatory regardless |
| G10 | Daemon reaction to external `claude stop` / process kill: roster marking, zombie risk? | no | informs kill/interrupt design (§5) |

**Halt vocabulary:** `HALT` = refuted ⇒ pivot stops at M-A and the design is revisited; no fallback exists. `HALT-grade` = refuted ⇒ the named fallback becomes the design, but only after the operator ratifies it in the M-0 verdict doc — a builder may not silently proceed on a fallback. `no` = refuted ⇒ fallback applies without ratification.

M-0 output = `docs/specs/native-substrate.md`: the contract doc pinning exact flags, JSON fields per state, and behaviors fleet depends on, plus the G-table verdicts and any fallback ratifications.

## 3. Architecture

```
agents screen (claude agents TUI)          ← user's window (Anthropic UX)
        │
native daemon (~/.claude/daemon, ~/.claude/jobs)   ← process hosting: spawn, attach, reap
        │
worker = claude --bg session               ← spawned from project cwd, fleet hooks inside
        │
fleet sidecar (bin/fleet.py + hooks)       ← semantics: task, mailbox, budget, journal,
        │                                     result capture, launch contract, knowledge
supervisor = pinned/heartbeat session      ← persistent identity in files, disposable body
```

The registry stays **keyed by worker name** (as today); `session_id` is a mutable field stamped per incarnation (respawn mints a new one — a key must survive respawn, so sessionId cannot be the key). Liveness truth = `claude agents --json` roster joined on session_id, **filtered through the outcome discriminator (§5)** — never PID probing.

**Launch contract preserved** (SPEC §6 analog on the new substrate): pre-claim registry entry under `fleet.lock` → mint sid (`--session-id`, G6) → dispatch `--bg` → stamp/verify → rollback on DOA. A crash between dispatch and stamp leaves a claimed entry pointing at a mintable sid, not an untracked live session (fallback-path degradation: see G6). **DOA verdict consults the outcome record first**: roster-absent + outcome record **for the current sid** ⇒ completed (a fast worker can finish before verify runs — the haiku pin test will); roster-absent + no current-sid record + no roster appearance within the verify window ⇒ DOA rollback.

### Superseded prior-spec surface

Banner treatment (`[SUPERSEDED — native-substrate pivot 2026-07-13]`, MOVE never delete):

- `docs/specs/portability.md` — probe-matrix/`boot_identity`/`killpg` machinery: problem now owned by daemon.
- `docs/SPEC.md` v2.2 — §6 "Worker turn launch (Windows detail)" detached-spawn plumbing; PID-based liveness verdicts. The **unbuilt** F33 `turn_pid_boot_id` work is cancelled (it was never shipped — do not list it as a deletion).
- `docs/specs/phase-2-watchtower.md` — PID-liveness polling premise; watchtower duties fold into the supervisor's beat.
- `docs/specs/terminal-surface.md` — **rules remain binding** (views read-only, no locks, exit 0, D4 quarantine, D5 worker-suppression), but its probe-premised text (D2 "probing" recompute, builder notes citing `probe_liveness`) gets banners pointing here.
- `docs/SPEC.md` §4 hook write boundary — **explicitly amended, not silently contradicted** (the F25 precedent): the sanctioned hook-write list (mailbox, `hook-errors.log`, own journal via PostCompact) gains one entry — *the Stop hook may write the worker's terminal-outcome record (result text, cost if visible, `result_captured` marker) to the worker's fleet journal*. This is the data source for §5's outcome discriminator.
- Unaffected: mailbox protocol, budget-hook design, knowledge loop, campaign-template doctrine, corrupt-registry quarantine (stays — it guards JSON corruption, not PID truth).

## 4. Supervisor — persistent identity, disposable body

**Soul** = git-tracked files: `supervisor/GOALS.md` (single target + standing goals, user-editable), `supervisor/JOURNAL.md` (append-only checkpoint log), `knowledge/` (unchanged).

**Single-supervisor invariant** (invariant-7 analog): never two live supervisors over one GOALS.md. Mechanism: `supervisor/INCARNATION` claim file, written only under `fleet.lock` — holds incarnation id, session_id, and a **heartbeat timestamp the holder refreshes at every checkpoint/beat**. Journal is append-only, single-writer, claim-holder only — no exceptions (handshake uses a separate file, below).

**Claim rules at boot** (run **after** the roster-epoch sanity check — a suspiciously empty roster freezes the claim decision too, or a daemon restart would let a fresh boot seize a claim whose holder is actually alive):
- Claim's session live in roster, or a fresher incarnation's checkpoint in the journal ⇒ refuse: read-only report, exit.
- Claim's session roster-gone AND heartbeat stale (older than threshold S > beat period + margin) ⇒ **seize**: rewrite `INCARNATION` under `fleet.lock`, journal a `SEIZED` checkpoint naming the dead incarnation.
- Claim's session roster-gone but heartbeat fresh (ambiguous — daemon restart, G9) ⇒ freeze + page operator. Never seize on ambiguity.

**Handoff protocol** (triggered with **reserved headroom** — early enough that old can still execute the full protocol including its failure branch, never at hard context exhaustion): old writes handoff checkpoint → dispatches successor (`--bg`, `-n`, claim-pending) → successor boots and writes `supervisor/HANDSHAKE` (its incarnation id — **not** a journal write; it holds no claim yet) → old **verifies HANDSHAKE's incarnation id equals the successor it just dispatched**, transfers claim under `fleet.lock`, deletes HANDSHAKE, exits. Dispatch failure or timeout T ⇒ old resumes duty, **`claude stop`s the limbo successor** (old knows its sid — it dispatched it), removes any HANDSHAKE, raises a doctor-visible flag. Stale-HANDSHAKE hygiene: the **seize path** deletes any HANDSHAKE it finds (an orphan from a crash mid-handoff must never receive a claim transfer); the refuse branch stays strictly read-only — a bystander boot during a live handoff must not delete the in-flight HANDSHAKE. The claim-pending successor takes no spawn/respawn actions before claim transfer — kills the both-alive double-spawn window from both sides.

**Boot ritual** (one code path for morning / post-reboot / post-handoff): roster-epoch sanity check → claim rules (above) → read GOALS + JOURNAL tail + knowledge/INDEX + `agents --json` + fleet status → reconcile workers (M-B onward: §5's outcome discriminator; M-A interim: today's registry verdicts via `fleet status` — the discriminator's inputs don't exist until M-B) → continue.

**Resurrection scope (stated limitation):** nothing auto-restarts the supervisor after reboot or crash in this build. Human-restarted; `fleet doctor` + the manager SessionStart hook nag. **Nag predicate is file-only** (views/hooks never probe, never spawn subprocesses — terminal-surface rules): GOALS.md active AND (no claim file OR claim heartbeat older than S). No roster read needed — the heartbeat timestamp carries liveness. Logon-task auto-start = ROADMAP Phase-2, out of scope here.

**Heartbeats:** mechanism = G7's verified primitive; beat period < reap window when G5 refutes scriptable pin. **Supervisor gets its own per-incarnation budget cap and a beat-rate bound** — it is not exempt from the budget discipline it enforces. If G7 refutes, watchtower duties are scoped out and the supervisor is event-driven only; there S derives from the reap window + margin (no beat period exists), and the nag may false-fire on a live idle supervisor — accepted: the nag is advisory, and seizure stays gated on roster-gone regardless.

**Scope fence:** standing goals / self-improvement = later layer. This build: identity + invariant + boot ritual + handoff + checkpoint mechanics only.

## 5. Native dispatch

**Spawn:** per §3's launch contract, from project cwd: `claude --bg -n <name> --session-id <sid> --settings worker-settings.json --permission-mode <mode> --model <model>` + prompt per G8 (prompt-file indirection if argv-only). Settings composition failure ⇒ **hard-fail the spawn** — never a hookless worker looking healthy in the roster. Env: `FLEET_WORKER` stamped, `CLAUDE_CODE_SESSION_ID` stripped (G4).

**Outcome discriminator** (replaces roster-gone → dead): the Stop hook writes a terminal-outcome record (`result_captured`, result text, cost if visible) to the fleet journal **before** any reap can occur. The record is **keyed by incarnation sid + turn id**, and every verdict matches on the **current incarnation's sid + latest turn** — never mere record presence: the journal is name-keyed and survives respawn, so a dead predecessor's record must not vouch for a new body, and turn N−1's record must not vouch for a death mid-turn N. Reconciliation: roster-gone + current-sid `result_captured` ⇒ completed, never respawned; roster-gone + no current-sid record ⇒ `dead-suspected` — surfaced for decision, **never auto-respawned** (never-demote-unknown, respawn is non-idempotent). Roster-epoch sanity check: roster suddenly empty while workers were live moments ago (daemon restart, G9) ⇒ freeze + page operator, never mass-respawn.

**Result/peek/cost:** the stream-json stdout pipeline is dead under `--bg` (refuted, §2). Result capture moves into the Stop hook (G3); `fleet peek` reads hook-journaled events; cost source per G3 verdict — if none, the cost column is declared dead and budget enforcement = token-ceiling hook + fleet-side cumulative checks only. `--max-budget-usd` does not exist under `--bg`; the spec makes no claim it does.

**Steering:** mid-turn = mailbox + PreToolUse/PostToolUse hooks, unchanged (G1). **Idle = G2's verdict**; fallback is respawn-to-steer per the G2 row — stop old session first, verify, dispatch replacement, atomic sid swap; never two live sessions under one name. Dearer, and non-idempotent-risk-free only for not-yet-started tasks — `send` must say which path it took.

**Kill/interrupt:** kill = `claude stop <id>` (verified) + overlay mark dead; never raw pid signals, never daemon files. `fleet interrupt`'s old contract ("transcript survives; worker does not die") is **unsatisfiable** under daemon-owned sessions unless G2/G10 reveal a native interrupt. Default plan: interrupt = `claude stop` + overlay mark `interrupted` — **respawn is a separate, explicit operator decision, never bundled** (an interrupted task is definitionally started; auto-respawn would re-run side effects). The `/fleet:interrupt` surface says so.

**Coexistence (M-B window):** legacy name-keyed PID-probed records become **read-only legacy** — status renders them flagged, mutating commands refuse ("pre-pivot worker — finish or kill via legacy path"), doctor's unknown-sessions check learns the overlay so fleet-native workers aren't false positives. M-B deploy requires an empty fleet or explicitly acknowledges the mix.

## 6. Deletions (M-C)

Dies: detached-Popen launch machinery, `probe_liveness` + probe-ctime code, PID-liveness registry fields, per-turn stdout log pipeline. Cancelled (never built): F33 `turn_pid_boot_id`.

Stays: mailbox, journal, budget hooks, knowledge, corrupt-registry quarantine, `spawn`/`respawn`/`send`/`status`/`kill`/`peek`/`result` as wrappers over the native surface + overlay + hook-journaled events.

## 7. Risk and its gate

THE risk: coupling to an undocumented `--bg`/daemon surface that drifts under `claude` updates.

1. **M-0 spike first** — the §2 G-table, each item with halt criteria/fallbacks pre-declared. Findings → `docs/specs/native-substrate.md`.
2. **Pin-test tier** (FLEET_LIVE analog): dispatch haiku bg worker, assert JSON contract per state, hook firing incl. Stop, `claude stop` behavior; run before campaigns.
3. **Doctor checks:** `claude --version` changed since last pin-test pass ⇒ warn; GOALS active + no claim-holder ⇒ nag; legacy-worker mix ⇒ flag.
4. **No daemon/jobs file access** — CLI + `--json` only.

## 8. Milestones

- **M-0 — spike + contract.** Execute the G-table, write native-substrate.md. Kills or confirms everything downstream.
- **M-A — supervisor identity.** Soul files, claim/invariant (incl. seizure rules + heartbeat), boot ritual, handoff protocol, checkpoint discipline — against today's backend, with the M-A interim reconciliation (today's registry verdicts). Value even if M-B stalls.
- **M-B — native dispatch.** Launch contract on `--bg`, outcome discriminator, Stop-hook result capture, steering per G2, kill via `claude stop`, coexistence rules, pin tests, doctor checks.
- **M-C — deletion + SPEC v3.** Retire per §6, banner superseded sections (§3 list), soak campaign before done.

## 9. Testing

- pytest: overlay merge, roster-JSON parsing per-state fixtures (incl. missing `pid`, contradictory status/state), boot ritual, claim/handoff/seizure state machine (stale-claim takeover, ambiguous-freeze, handshake timeout stopping the limbo successor), outcome-discriminator verdicts incl. the fast-completion DOA case.
- Integration: haiku `--bg` worker full lifecycle (spawn → mid-turn steer → result → respawn) + handoff drill (old supervisor → successor with forced dispatch failure).
- Pin tests: §7.2, version-gated skip when `claude agents` unavailable.
- Removals delete their tests in the same commit.
