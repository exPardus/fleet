# Native Agents Pivot — Adversarial Review (2026-07-13)

Two independent hostile reviewers on `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` (spec v1, commit f2d0270). Lens A = spec-vs-reality (receipts from live CLI probes + bin/fleet.py greps; dispatched and cleaned up one live haiku bg session). Lens B = failure modes / design holes.

Shared root cause (both reviewers converged): **the design assumes observability/control primitives — sessionId capture, idle-turn injection, cost source, scriptable pin/stop, heartbeat wakeups — that are neither verified nor on the M-0 gate list**, so M-0 as scoped could pass while the design remains unbuildable. And it deletes SPEC v2's lifecycle discipline (launch contract, three-verdict liveness, never-demote-unknown, one-live-claude) without building equivalents on the new substrate.

## HIGH

- **H1 (B1)** No single-supervisor invariant; successor handoff (checkpoint → dispatch → exit) has no election, no verification, no failure branch. Dispatch-fails → no supervisor; both-alive window → double worker respawn (C2/C4 double-launch reintroduced one level up) + interleaved JOURNAL.md appends; reboot mid-handoff undetected.
- **H2 (B2)** Roster cannot distinguish "reaped because done" from "died". Boot-ritual rule "roster-gone → sticky dead → respawn decisions" re-executes completed tasks (respawn documented non-idempotent). Old fleet observed the result event before the process vanished; daemon can erase evidence first.
- **H3 (A1+B3)** No mechanism to deliver a new turn to an idle bg worker. Old send-to-idle = fleet launching `-p --resume <sid>` (bin/fleet.py:2703-2730, argv :1169) — deleted by pivot. Peek+reply TUI-only. Fleet's core feature silently lost; not on M-0 list.
- **H4 (A2+B4)** Result/cost/peek pipeline dies: turns currently run `-p --output-format stream-json` → `logs/<name>.jsonl` (:1168); `cmd_peek` :2549, `cmd_result` :2578, cost accounting parse it. `--output-format` and `--max-budget-usd` are **print-only** (claude --help receipt). Live probe: `claude logs <id>` on a bg session returns a 253 KB raw ANSI screen dump. No cost source in `agents --json`. Cost column dead, budget cap flag vanishes, peek/result absent from §6 "stays" list.
- **H5 (A4)** Child-env machinery deleted without replacement: `_worker_env` (:1220-1238) stamps `FLEET_WORKER` (terminal-surface D5) and strips `CLAUDE_CODE_SESSION_ID` (SPEC §5.1 provenance guard — a worker running `fleet kill` would look like the manager). Spec never mentions either; env propagation through daemon unknown.
- **H6 (A5+B6)** Pinning is load-bearing (supervisor body + long-soak workers) but TUI-only; no `claude pin` CLI (probed); `pins.json` sits in `~/.claude/jobs/` which the spec's own fence forbids touching. Idle supervisor gets reaped ~1 h and cannot pin itself. Also self-contradiction: §4 says successor dispatched "pinned" — pinned by whom?

## MED

- **M1 (A6)** §2 "verified" daemon layout false: `pins.json` + per-job dirs live at `~/.claude/jobs/`, not `~/.claude/daemon/`. Fence must name both.
- **M2 (A7)** §6 deletes unbuilt code — F20 failure mode inside the pivot spec: `boot_id` has zero matches in bin/fleet.py (SPEC.md:102 marks `turn_pid_boot_id` UNBUILT). Probe-ctime does exist (`probe_liveness` :607). Reword: cancel unbuilt F33 work; delete shipped probe-ctime.
- **M3 (A8)** §6 "quarantine paths premised on PID truth" — no such code; the only quarantine is corrupt-registry (`_quarantine_registry` :429), premised on JSON corruption, required by SPEC §11 + terminal-surface D4 which §3 keeps. Deletion list contradicts §3.
- **M4 (A9)** Roster fields optional/inconsistent per state (live receipt): done bg entry has no `pid`/`name`/`status`; one entry carries `status: "idle"` AND `state: "done"`; interactive entries have `status`, never `state`. Kill-by-pid depends on a field that disappears. Contract doc must pin field presence per state.
- **M5 (A10)** Survey missed real scriptable surface: `claude stop/logs/attach <id>` are hidden CLI commands (printed by `--bg` stdout; each has --help). `claude stop` verifiably transitions session to `done`. §5's pid-signaling proposal moot.
- **M6 (A11)** Supersede list incomplete: `phase-2-watchtower.md` (:64,:75 PID-liveness polling, overlaps watchtower beats) unlisted; `terminal-surface.md` declared unaffected but premised on the deleted probe (D2 "probing" :49, builder note :251).
- **M7 (A12)** Prompt delivery: `--bg "<task>"` puts prompt on argv; fleet deliberately pipes via stdin because composed prompts (preamble + mailbox + task + carried journal) can exceed Windows' 32,767-char command-line cap (`compose_prompt` :1050, F-BLOCK stdin writer :1199).
- **M8 (B5)** Nothing restarts the supervisor after reboot/crash — "survives reboots" aspirational. Must name restart mechanism or scope as human-restarted with a doctor/SessionStart nag.
- **M9 (B7)** `fleet interrupt` contract ("transcript survives; worker does not die") unsatisfiable under stated kill mechanism; daemon reaction to external pid-kill unspecified.
- **M10 (B8)** sessionId both overlay key and unknown until after dispatch: capture race under concurrent spawns; crash between dispatch and overlay-write = live untracked session (drops SPEC §6 launch contract, re-opens U17). Respawn changes sessionId → the key the identity lives under. Key by name; sid mutable field; keep pre-claim→dispatch→stamp/rollback. Mitigant (A): `--session-id <uuid>` exists — fleet can mint its own sids; `--bg` also prints a short id prefix.
- **M11 (B9)** Daemon restart / `claude update` mid-campaign unaddressed: roster persistence across daemon restart unknown; feeds M2/H2 false-dead → mass re-execution. Watchtower needs roster-epoch sanity check (roster suddenly empty + workers live moments ago → freeze + page operator, never mass-respawn).
- **M12 (B10)** M-B coexistence window: old name-keyed PID-probed workers + native overlay workers, one `fleet status`/`send`/`kill`/doctor. Unspecified.
- **M13 (B11)** Heartbeat mechanism load-bearing, unverified, absent from M-0. "ScheduleWakeup" not found in CLI surface (A: DISPUTED — name the real primitive). Heartbeat = model turn = continuous spend; supervisor itself has no budget cap.

## LOW

- **L1 (B12)** Partial `--settings` composition failure = worker with no hooks looking healthy in roster. Spawn must hard-fail, not degrade. Env-var propagation → M-0 probe list.
- **L2 (B14, DISPUTED)** Stop-hook semantics under daemon: needs sharper M-0 experiment than "hooks fire" — stop-block honored? roster state during block? reap timer treats stop-blocked as active?
- **L3 (A, incidental)** Daemon auto-naming unreliable (test session named from unrelated text). Always pass `-n`.

## SPURIOUS (attacked, survived)

- sessionId capture workable (`--bg` prints short-id prefix; `--session-id` mint exists).
- §6 "stays" list — all verified present in bin/fleet.py (receipts in transcript).
- Core §2 claims: `--bg` real, `agents --json [--all]` real/no-TTY/cross-project, `-n` exists, portability.md supersede pointer accurate.
- Sticky-dead rule itself sound — danger is entirely in what feeds the verdict (H2).
- CLAUDE.md eight-rule sweep: no direct violation; indirect breaks filed as H5, M3, M6.

## Disposition

Spec v2 (same file) amends per all findings; every load-bearing unverified primitive becomes a named M-0 gate item with halt criteria. Re-review of v2 recommended before writing-plans.
