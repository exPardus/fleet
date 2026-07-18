# Native Substrate Contract (M-0 verdicts)

> **[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** The CLI moved 2.1.207 →
> 2.1.212 and the daemon's lifecycle changed underneath this document: it is now
> **transient** (see `## 2.1.212 re-verification` at the foot of this file, and
> the receipts in `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md`). Rows
> below carry inline `[OBSERVED 2.1.212 …]` amendments where the evidence touches
> them. **No verdict status in this file has been changed by the amending author**
> — an amendment records what was observed; only the operator ratifies.

Date: 2026-07-14. `claude --version`: 2.1.207. Windows 10 Pro 10.0.19045 (controller-provided environment fact, not in spike artifacts).
Spec of record: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.3 §2.

This doc pins EVERY native-surface behavior fleet may depend on. Anything not
listed here is out of contract. Re-verify via the pin-test tier (§7 below)
whenever `claude --version` changes.

Primary sources: `spike/m0/VERDICTS.md` (§`G<N>` sections, all quoted evidence
verbatim from live probes on this machine); `spike/m0/explore-ui-cli-report.md`
(copied here from the gitignored `.superpowers/sdd/explore-ui-cli-report.md` so
every cited receipt lives in the repo — G13 evidence). No claim in this doc
lacks a pointer to one of these two files or to the design spec itself.

---

## G-table verdicts

13 gates. Halt vocabulary per spec §2: `HALT` = refuted ⇒ pivot stops, no
fallback. `HALT-grade` = refuted ⇒ named fallback becomes the design, but
only after operator ratification. `no` = refuted ⇒ fallback applies without
ratification.

| G | Halt-grade | Verdict | Evidence | Consequence for design |
|---|---|---|---|---|
| G1 | HALT | **CONFIRMED** (for the two tested sub-questions: hooks fire; stop-block honored). SessionStart/PreToolUse/PostToolUse/Stop all fire inside a `--bg` session, in order, each event's `session_id` matches the daemon-minted sid. Stop-block (`{"decision":"block","reason":...}`) is honored: consumed exactly once, fed back as a synthetic user turn, session continues and replies before the second Stop. **UNOBSERVED:** the gate's third sub-question — whether the reap timer treats a stop-blocked session as active — was never tested anywhere in the spike (the observed block window was ~3s, far too short to interact with any reap timer, and no experiment held a session blocked long enough to observe reap behavior). | VERDICTS.md §G1, §G1-sharp | Fleet's hook pipeline (mailbox, budget, journal via PostCompact, Stop-hook outcome record) is buildable as designed on `--bg`. One naming quirk: a session that passed through a consumed Stop-block reports terminal `state: "blocked"`, not `"done"` — status-surface logic must key off `status` (`idle`/`busy`), never assume `state` is only `working`/`done`. |
| G2 | **HALT-grade** | **CONFIRMED-with-caveat — outcome (b).** `--bg --resume <sid> "<prompt>"` works but **forks**: a brand-new `sessionId`/pid appears, full prior transcript is carried into it verbatim, the *original* session's roster entry and event count are untouched. `-p --resume <sid>` (no `--fork-session`) against a daemon-owned session is flatly rejected: `Error: Session <sid> is currently running as a background agent (bg). Use \`claude agents\` to find and attach to it, or add --fork-session to branch off a copy.` No same-session prompt-injection channel exists over the CLI. | VERDICTS.md §G2 | **RATIFICATION PENDING — Task 12.** Design fallback in effect per spec §5: steering an idle worker = fork-and-restamp, never same-session injection. Every `--bg --resume` steer mints a new sid the overlay must adopt as the worker's new canonical identity; mailbox/journal re-point to it. The new sid must be captured from `--bg --resume`'s own stdout (it prints a short id exactly like initial `--bg` dispatch), never re-derived by polling the roster for a name match — see roster-name instability below. |
| G3 | HALT-grade | **CONFIRMED** (result text + tokens); **USD REFUTED-for-contract**, matching the spec's own pre-declared partial fallback. Roster (`agents --json --all`) carries **no** result/cost/token/turn-metadata field on any of 17+ sampled entries, in any state — REFUTED as a source. Sanctioned source is the Stop hook payload (`last_assistant_message` key present 6/6, `transcript_path` present 6/6, path always valid) plus the transcript's last `type:"assistant"` record. | VERDICTS.md §G3 | Result/cost capture moves fully into the Stop hook + transcript tail read, per spec §5's outcome record. No fallback ratification needed — G3 was not wholly refuted. The pre-declared USD sub-fallback ("cost column declared dead, budget = token-ceiling hook only") is already in effect since no sanctioned source carries a dollar figure anywhere. |
| G4 | HALT | **CONFIRMED.** `FLEET_WORKER=1` set in the dispatching shell reaches every hook subprocess of the daemon-spawned child (`env_fleet_worker: "1"` on 100% of records). `CLAUDE_CODE_SESSION_ID`, unset in the dispatching shell, is set by the daemon to the child's **own** sid — never a stale/foreign one. Negative control (deliberately un-set `FLEET_WORKER`) confirmed `env_fleet_worker: null` on all 3 records of that session, ruling out ambient leakage as a false positive. | VERDICTS.md §G4 (incl. G4 addendum negative control) | D5 / SPEC §5.1's provenance guard (stamp `FLEET_WORKER`, treat `CLAUDE_CODE_SESSION_ID` as untrusted/self-set) is buildable as designed. No fallback needed. |
| G5 | no | **REFUTED** (pin scriptability: no CLI/flag/subcommand surface exists anywhere — TUI-only, `Ctrl+T`). **REFUTED** (the "~1h idle reap" claim, for *done* background sessions: an unpinned, finished session's roster entry survived ≥3h21m unevicted). **UNOBSERVED**: process-level reap of a *live, not-yet-done* idle session — no experiment dispatched a never-completing session and watched its process. | VERDICTS.md §G5 | Fallback applies without ratification: heartbeat-respawn is primary (G7 confirms the primitive exists); pin is unavailable to automation. The "~1h" figure is real but describes **process stop with state retained on disk**, not roster eviction (primary-source quote in Hazards §below) — do not conflate the two. The live-idle-process-reap gap is flagged by VERDICTS.md itself for Task 12 discussion (not a ratification-blocking HALT-grade row, but an open question before the overlay assumes heartbeats alone keep a long-idle interactive-style worker's *process* alive). |
| G6 | no | **REFUTED.** `--session-id <uuid>` does not compose with `--bg`: dispatch emits `warning: --bg manages the session id; ignoring --session-id (use --resume <id> to continue an existing session)` and the daemon mints its own sid, discarding the caller-supplied one entirely (verified: minted sid ≠ roster `sessionId`). | VERDICTS.md §G6 | Fallback applies without ratification (pre-registered, non-HALT): fleet cannot pre-claim by sid. Launch contract = capture the short id from `--bg`'s own stdout, join to the full sid via `claude agents --json --all` filtered by `-n` name within a verify window; no roster match ⇒ claimed entry marked DOA. Crash-safety degrades on this path by design (sid unknown between dispatch and stamp). |
| G7 | HALT-grade (watchtower only) | **CONFIRMED.** `ScheduleWakeup(delaySeconds, prompt, reason)` is a real in-session self-rearming tool: 17 beats observed across two runs at ~173s mean cadence (range 128–182s), session context (`cache_read_input_tokens`) provably continuous across beats — not a fresh process per beat. Two sub-findings feed G11/hazards below: a 429 rate-limit silently killed the loop mid-turn (no `ScheduleWakeup` re-armed because the turn never reached it); `claude stop` permanently kills the self-wake loop — a wakeup already scheduled at stop time never fires (5-minute poll, zero new lines). | VERDICTS.md §G7 | Confirmed, not refuted — the watchtower fallback is not invoked; heartbeats are buildable. Supervisor beat period still must stay under whatever reap window G5 leaves open for live sessions (G5's UNOBSERVED gap). Stop is a true kill, not a pause — the overlay cannot rely on a stopped worker's self-wake resuming. |
| G8 | no | **REFUTED (argv):** a >32,767-char prompt on argv fails at the Win32 `CreateProcess` layer (`ERROR_FILENAME_EXCED_RANGE`, "The filename or extension is too long") — below PowerShell's own layer, no shell workaround helps; no zombie/partial dispatch. **REFUTED-stdin:** piped stdin dispatch does not hang the dispatch command itself, but the spawned session wedges — zero hook events, no `SessionStart`, for the full ~171s observed window, no self-recovery seen. **CONFIRMED (task-file bootstrap, the must-pass fallback):** a 42,054-char payload written to a file and Read by the worker round-trips intact — needle recovered verbatim from the transcript. | VERDICTS.md §G8 | Fallback applies without ratification and already validated: fleet's composed prompt (preamble + mailbox + task + journal) must always go through task-file bootstrap — tiny fixed argv prompt ("Read `<task-file>` and follow it"), body in a fleet-written file. Never argv for size-unbounded content; never stdin as a prompt channel at all. |
| G9 | no | **DEFERRED-proposed.** Experiment not run in this spike: live foreign sessions were present, and the controller session itself is daemon-hosted, so a daemon restart could not be safely exercised. Operator to run the probe standalone.<br><br>**[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** (receipts: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q4, §Q5) — still DEFERRED as a gate (the restart probe remains unrun, and for the *same* reason: the amending worker was itself a `--bg` session and its M-D siblings were live, so the only routes to a dead daemon were the banned `claude daemon stop` or ending sessions it did not own). But the **idle-exit half is now answered from the daemon's own logs**:<br>• **An idle-exit cannot strand a live-looking roster entry.** Every `cause=idle_exit` shutdown in 10 days of `~/.claude/daemon.log` (2026-07-07 → 2026-07-17, 25 daemon starts) carries **`leases=0, live_workers=0`** — 15/15, no counter-example (count receipts: findings §Q4; an earlier draft of this row said 16/16, a miscount corrected under review). The daemon waits for workers to settle before exiting; its own `daemon status` text says so verbatim ("daemon waits for them to settle"), and the log shows settle-then-exit ordering with the 5s idle gap.<br>• **Structural corroboration:** `~/.claude/daemon/roster.json` holds only *live* workers (`workers` dict, each with a `pid`), while `claude agents --json --all` is backed by the `~/.claude/jobs/<short>/` dirs. `status`/`pid` — the two keys fleet's liveness test reads — appear only for entries the live `workers` dict vouches for, so an exit at `live_workers=0` leaves no status/pid-bearing entry to false-positive on.<br>• **The residual vector is `cause=upgrade`, not idle-exit:** 4/4 upgrade shutdowns happened **with live workers** (`live_workers=1`, `1`, `4`, `1` — log lines 147, 165, 223, 515), followed by adopt/respawn — with an observed **`respawned 0/1 stale workers, 1 refused`**, i.e. a worker neither adopted nor respawned. That ambiguity is exactly what the epoch-freeze exists for. | design spec §2 G9 row; operator note (2026-07-14); `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q4, §Q5 | The roster-epoch freeze rule (spec §5: roster suddenly empty while workers were live moments ago ⇒ freeze + page operator, never mass-respawn) is **mandatory regardless of G9's eventual answer** — it does not wait on this gate.<br><br>**[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** A full audit of every `claude agents --json` read in `bin/fleet.py` against the idle-exit timeline (grep receipt + per-call-site table: §Q4) found **zero reads needing a change** — each is already behind `native_epoch_suspicious`/`supervisor_epoch_check` or fails safe. Nothing was "fixed" here on suspicion: G9 doctrine is *never assume dead on ambiguity*, and the evidence shows no idle-exit ambiguity to defend against. |
| G10 | no | **REFUTED** (Stop-hook-on-external-stop): an externally issued `claude stop` against a session that has not yet naturally ended its turn fires **no Stop hook** — confirmed on two independent, unconfounded samples (pre-turn-start kill: 1 event total, only `SessionStart`; mid-turn permission-pending kill: 2 events, `SessionStart`+`PreToolUse` only, no `PostToolUse`, no `Stop`), both re-checked 10–20s after stop. **CONFIRMED zombie hazard** (raw `taskkill`): the daemon supervisor auto-respawns the killed process under a new pid, identical `sessionId`, within an observed window bounded between +6s (still dead, stale roster) and +36s (new pid live) — full new `SessionStart`+`PreToolUse` hook cycle re-fires on the same sid, session resumes sitting on the same pending permission prompt. | VERDICTS.md §G10 | Fallback applies without ratification: spec §5's outcome discriminator/stop-then-mark flow must write its **own tombstone** on `claude stop` rather than assume the Stop hook already recorded one — a stopped session with zero Stop-hook record is a real, reproducible case. Raw pid kill is confirmed empirically unsafe (not hypothetical) — CLAUDE.md's "never raw-kill" rule is load-bearing, not merely cautious. |
| G11 | no | **NATURALLY PINNED, CONFIRMED.** The rate-limit wall dies silently: **no Stop hook fires**, roster state is unaffected (the daemon's own unsanctioned job tracker shows `working → blocked`, but nothing sanctioned changes), the only evidence is a synthetic 429 assistant record in the transcript with the reset time. No native auto-resume observed at the stated reset time; the loop resumed 8 minutes past reset via a same-sid, non-forked `"continue"` prompt tagged `origin.kind:"human"`/`promptSource:"typed"` — operator-confirmed peek+reply, not a daemon-autonomous retry. This also refines G2: a same-sid injection channel exists **interactively** (agents-menu peek+reply / attach), just not over the CLI. Operator confirmation of the peek+reply trigger postdates VERDICTS §G7 (which honestly records the trigger as UNOBSERVED at experiment time); the confirmation is recorded in the spec-of-record §2 G11 row. | VERDICTS.md §G7 (same-sid restart anomaly section); design spec §2 G11 row | Detection cannot ride Stop hooks (spec §5.1.1): a limit wall must be detected via the dead-suspected investigation path — worker idle/roster-alive with no fresh outcome record for its latest turn ⇒ supervisor beat scans the transcript tail with the existing `_parse_limit_signal` regexes. Fleet's layer carries the full recovery load; native auto-resume does not exist. |
| G12 | no | **CONFIRMED.** `claude rm <id>` cleanly removes exactly the targeted roster entry (verified by exact pre/post roster set-difference: one id removed, zero added, no collateral change on remaining entries) and deletes the backing `~/.claude/jobs/<short-id>/` directory. No error on a long-dead `failed`-state target. `--help` text: "Delete a background session and its worktree. Unlike `stop`, works on already-exited sessions."<br><br>**[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** (receipts: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q1, §Q3) — the row's core claim still holds; three sub-questions it left open are now answered and one prior assumption is refuted:<br>• **Live-session behavior — OBSERVED** (was "UNOBSERVED and out of contract"): rm against a **live, mid-turn** session **removes** it — no refusal, no prior `stop` required. Entry gone from `--all` and from the default listing, backing jobs dir deleted, all within <1s (§Q1.2, 1/1; plus §Q1.1 settled and §Q1.3 stopped-then-rm'd, 3/3 overall).<br>• **Idempotency — REFUTED IN FORM, held in effect** (was UNOBSERVED): an already-removed (or never-existing) id exits **rc=1** with `No job matching '<id>'`, not rc=0. The sid does stay gone, so the *effect* is idempotent; the *exit code* is not (§Q3).<br>• **Dead-daemon failure mode — NEW, and the WEAKEST-EVIDENCED claim in this row:** with the transient daemon down, rm reportedly exits **rc=1** with `couldn't remove <id> — the background service may be restarting. Try again in a moment.` and does **not** revive the daemon. **[OBSERVED interactive 2026-07-17 manager session — NOT RE-OBSERVED BY TWO SUBSEQUENT WAVES]**: this is a *manager report*, not a capture. The dead-daemon state is unreachable from a `--bg` session (§Q2), and both the amending worker and its adversarial reviewer are `--bg` sessions, so neither could reach it. The exact bytes, the rc, and even the stream (stdout vs stderr) are unverified. Fleet's matcher therefore keys ONLY on the dash-free middle phrase `background service may be restarting`, and an unrecognised message falls through to a `failed` verdict that is behaviourally identical to `daemon-transient` on every axis that touches state — so a wording/locale drift degrades diagnosis, never correctness. **Ratify this bullet only after capturing the string on a quiet machine (see the G9 probe).**<br>• **Consequence: `rc=1` from `claude rm` is three-way ambiguous** (already-gone / dead-daemon / real failure) and **the message is the only discriminator.**<br>• Still UNOBSERVED: whether `rm` clears the transcript under `~/.claude/projects/`. | VERDICTS.md §G12; `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q1, §Q3 | Confirmed as the archival primitive for spec §5.1.2 (auto-archival). UNOBSERVED and out of contract: ~~behavior against a *live* session (force-stop-first vs. refuse — untested)~~ **[SUPERSEDED by the 2.1.212 amendment in this cell — OBSERVED, §Q1.2: rm removes a live session; do NOT add a defensive stop-before-rm]**; ~~idempotency against an already-removed id~~ **[SUPERSEDED — OBSERVED, §Q3: rc=1 `No job matching`, idempotent in effect, not in form]**; whether `rm` also clears the transcript file under `~/.claude/projects/` **(this third item is still genuinely UNOBSERVED)**.<br><br>**[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** Fleet must classify rm by **message, not exit code** — implemented as `_classify_native_cli_result` / `_rm_native_session_status` in `bin/fleet.py`: `gone` counts as success (else every already-clean sid is reported as a failure), `daemon-transient` is a **loud, non-fatal deferral** (husk stays on the roster, the autoclean husk tier retries it). No hygiene pass may revive the daemon: only a dispatch does, and a dispatch mints a new billable session. The live-session finding also retires the T9-era worry behind `_archive_move_and_rm`'s live-sid skip (rm of a live retired sid would remove a *running* session — now confirmed real, so the skip stays). |
| G13 | no | **REFUTED.** No `claude rename`, no per-session title/tag/label/note/status/summary CLI surface exists anywhere. Exhaustive sweep: 15 candidate hidden-command words (`rename, title, summary, describe, tag, label, note, status, tasks, jobs, sessions, ls, list, watch, tui`) all fall through byte-identical to top-level `claude --help`; `claude agents --help`'s full verbatim option list has no `--sort/--color/--format/--columns/--label/--tag/--category/--group` flag. Roster `--json` schema is closed at 8-9 keys — no `title`/`summary`/`label`/`tag`/`category`/`note`/`color`/`icon` key exists. | `spike/m0/explore-ui-cli-report.md` §1, §2 (copied from the gitignored source per the untraceable-source lesson); design spec §2 G13 row | Fallback applies without ratification: category/status encoding happens **only** at dispatch time via `-n/--name` (confirmed unicode/pipe/120-char clean pass-through, no truncation) and gets re-stamped at every fork-restamp (spec §5.1.3) — no post-hoc rename channel exists, so mid-turn category changes render only at the next natural steer/respawn. |

---

## Dispatch contract

**Exact working argv** (PowerShell, from the project cwd — verified across every G1–G13 dispatch in this spike):

```powershell
Set-Location <project-cwd>
claude --bg -n <name> --settings <settings-path> --permission-mode <mode> --model <model> "<prompt>"
```

**Shell caveat (failed-husk lesson, VERDICTS.md §G2):** this argv must be run
via **PowerShell**, not the Bash tool / Git Bash `sh -c`. Three dispatches in
this spike failed identically (`state: "failed"`, zero `events.jsonl` lines)
when issued from Git Bash with a relative backslash path (`..\worker-settings.json`)
as a **CLI argument** — Git Bash's `sh -c` ate the backslash, producing the
literal string `..worker-settings.json`, which the daemon correctly reported
as "not found" (`claude attach` surfaced: `Error: Settings file not found:
..worker-settings.json`). This extends CLAUDE.md's existing forward-slash rule
(previously scoped to hook *commands* inside `worker-settings.json`) to CLI
*arguments* as well: either invoke from PowerShell, or use forward slashes /
absolute paths for every path-bearing flag regardless of invoking shell.

**Flags — CONFIRMED list** (VERDICTS.md, all sections; cross-refs noted):
- `--bg` / `--background` — CONFIRMED. Dispatches a daemon-hosted PTY session; prints `backgrounded · <short-id> · <name>` and hint lines.
- `-n` / `--name <name>` — CONFIRMED. Display name; echoed at dispatch, stored in roster `name`, written to the terminal title via OSC 0 (`explore-ui-cli-report.md` §4). Free text: emoji + `|` + 120 chars survive with **no truncation**, stable through completion for a plain (non-resumed) dispatch (`explore-ui-cli-report.md` Probe A/B).
- `--settings <file>` — CONFIRMED. Hooks fire reliably when the path resolves (G1, G4). Settings composition failure must **hard-fail the spawn** per design §5 — never a hookless worker looking healthy in the roster.
- `--permission-mode acceptEdits` — CONFIRMED, used throughout this spike. Auto-approves file edits; does **not** auto-approve Bash tool calls — a Bash call under this mode can sit pending, surfacing as roster `status: "waiting"` / `waitingFor: "permission prompt"` (VERDICTS.md §G10 sample 2).
- `--model <model>` — CONFIRMED accepted; recorded only in the transcript's `message.model` (e.g. `"claude-haiku-4-5-20251001"`), **never** in `agents --json` (VERDICTS.md §G3; `explore-ui-cli-report.md` §2).
- `--session-id <uuid>` — **REFUTED when composed with `--bg`** (G6): explicit warning emitted, value discarded, daemon mints its own sid. Do not pass it expecting it to take effect under `--bg`.
- `--bg --resume <sid> "<prompt>"` — CONFIRMED, but **forks** (G2 outcome b): new sid, new pid, full prior transcript carried forward, original session's roster entry/events untouched.
- `-p --resume <sid> "<prompt>"` (no `--fork-session`) against a daemon-owned session — **REFUTED**: rejected outright by the CLI before any turn is attempted (exact error text quoted in the G2 row above). `--fork-session` itself was not additionally exercised (UNOBSERVED whether it behaves like `--bg --resume`'s silent fork or differently).

**`-n` conventions:**
- Emoji, the `|` character, and length up to 120 chars are all OK — confirmed clean pass-through with no truncation at any layer observed (dispatch stdout echo, `--json` `name` field, OSC-0 terminal title) (`explore-ui-cli-report.md` Probe A).
- `name` is **display-only** for the purpose of category/status encoding (spec §5.1.3) — it is not a stable join key after a resume/fork. Roster join must be by **sid**, captured from dispatch/resume stdout at the moment of the call, not re-derived by polling the roster for a name match later.
- Rationale: the daemon's own `ai-title` mechanism can silently overwrite `name` after a `--bg --resume` fork/second turn (observed once, 40-char+ellipsis auto-summary replacing the `-n` value — VERDICTS.md §G2 anomaly), while a plain, never-resumed `--bg` dispatch keeps its exact `-n` name for its entire lifecycle including after completion (2/2 negative-control cases, `explore-ui-cli-report.md` Probe B). Sample size for the resume-triggers-retitle claim is small (n=1 positive, n=2 negative) — treat as a real, not hypothetical, hazard rather than a proven-deterministic one.

---

## Roster contract (`claude agents --json --all`)

**Closed schema, 8-9 keys** (VERDICTS.md §G3, cross-ref `explore-ui-cli-report.md` §2): `pid, id, cwd, kind, startedAt, sessionId, name, status, state`. No other key (`title`, `summary`, `label`, `tag`, `category`, `note`, `result`, `cost`, `tokens`, `model`) exists anywhere in this schema, on any state, on ~20+ live-sampled entries across the whole spike.

**Field-presence-per-state table** (VERDICTS.md §G3 Step 1, extended by §G10's `waiting`/`waitingFor` finding; Y = present, - = absent):

| state / status context | pid | name | status | state | sessionId | id | cwd | startedAt | kind |
|---|---|---|---|---|---|---|---|---|---|
| `state: "done"` — dead/reaped | - | Y (usually¹) | - | Y | Y | Y | Y | Y | `background` |
| `state: "done"` — process still briefly live | Y | Y | Y (`idle`) | Y | Y | Y | Y | Y | `background` |
| `state: "stopped"` | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `state: "failed"` | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `state: "working"` — live | Y | Y | Y (`busy`) | Y | Y | Y | Y | Y | `background` |
| `state: "working"` — wedged, never started a turn (G8 stdin hazard) | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `state: "blocked"` — passed a consumed Stop-block (G1-sharp) | Y | Y | Y (`idle`) | Y | Y | Y | Y | Y | (not observed) |
| `state: "blocked"` — pending on a permission prompt (G10) | Y | Y | Y (`waiting`, + `waitingFor: "permission prompt"`) | Y | Y | Y | Y | Y | `background` |
| *(no `state` key at all)* — interactive sessions | Y | Y | Y (`busy`/`idle`) | - | Y | - | Y | Y | `interactive` |

¹ one dead `done` background entry was observed with **no `name` key at all** — `name` is not guaranteed even on background entries (VERDICTS.md §G3 footnote).

**State literals observed:** `done, stopped, blocked, working, failed` (no `killed`/`error` literal ever seen). `status` literals observed: `idle, busy, waiting` (the last paired with a `waitingFor` field, e.g. `"permission prompt"`). **`state` and `status` are disjoint, overloaded axes, not a single vocabulary** — the literal `"blocked"` means two different things depending on which fields co-occur (consumed Stop-block vs. permission-gate stall); a status surface must inspect both fields together, never `state` alone.

**Stickiness facts:**
- **`blocked` persists post-cycle.** A session that passed through a consumed Stop-block reported `state: "blocked"` (not `"done"`) at every poll for 35+ seconds after its Stop-block cycle completed and no further hook activity occurred — the session was genuinely finished, `status` correctly read `idle` (VERDICTS.md §G1-sharp).
- **`claude stop` does not rewrite terminal literals.** Every already-terminal session stopped in this spike (three `state: "failed"` false-start husks, multiple `state: "done"` sessions) retained its pre-stop `state` literal after `claude stop` — it was never rewritten to `"stopped"`. Only a session stopped while genuinely `working`/`blocked` (mid-turn) transitions to `state: "stopped"` (VERDICTS.md §G2, §G10, §G7 — m0-beat's `working` → stop → `stopped` transition is the exact positive pattern).

**`startedAt` jitter — nothing may key on its stability.** Observed to change value across transitions that involve **no respawn at all** (e.g. a dead-entry read after a raw kill, before any new pid existed; a final read after `claude stop`), not just across genuine respawns — confirmed on three independent sessions (`0ac6e5d0` across days, VERDICTS.md §G6/§G3; `8beb709a` across a `claude stop`, §G7; `b2079061` a 3-way drift across kill→dead-read→respawn→cleanup, §G10). Treat `startedAt` as informational only, never as a stable dispatch timestamp or respawn signal.

**`status`/`state` disjoint axes (restated as a design rule):** interactive entries carry `status` only, never `state`, never `id`; dead background entries carry `state` only, never `status`, never `pid`; only live background entries carry both. A consumer must treat `pid`/`status` as present-only-while-the-backing-process-lives — their absence means "dead, read `state` instead," and their presence (e.g. `state: "working"` with no `pid`) does not by itself prove liveness either (VERDICTS.md §G3, §G8 stdin-wedge row).

**Startup transient (amended 2026-07-16, live pin-suite finding):** state-only is dead ONLY outside the dispatch grace window. A freshly dispatched `--bg` session's roster entry exists for its first seconds with STATE ONLY (`{'state': 'working'}`, no `status`, no `pid`) — `status`+`pid` appear once the process attaches. Empirically confirmed: the same entry later showed `status: 'idle'` + `pid` and the session's outcome landed normally (PIN-OK), while the pre-amendment rule verdicted it dead-suspected ~1.5 s after spawn and `fleet wait` returned instantly. Consumers must treat a state-only (or roster-gone) entry with no fresh outcome as *still launching*, not dead, while within a grace window anchored on the record's `last_dispatch_at` (fleet: `_dispatch_grace_active`, sharing `LAUNCH_CLAIM_MAX_AGE_SECONDS` with the sid=None pre-claim guard).

---

## Result/cost contract

**Sanctioned source: Stop hook payload + transcript.** Roster is REFUTED as a source (no result/cost/token key anywhere).

- **Result text — CONFIRMED.** Stop hook payload key `last_assistant_message` is present in **6/6** observed Stop events. **Value/shape is UNOBSERVED** — the spike's hook probe logged `payload_keys` only, never the value itself. Design must **feature-detect**: try `last_assistant_message` from the payload, verified fallback = parse the transcript. `transcript_path` is present in 6/6 payloads and every path resolved to a real, readable file.
- **Transcript fallback — CONFIRMED, exact shape.** The final result text is at the **last record with `"type": "assistant"`**, field `message.content[]` where `content[].type == "text"`, key `text` (verified verbatim across all six spike transcripts: `DONE-M0`, `BLOCKED-ACK`, `REAP-BAIT`, `NEEDLE-9317`, `DONE-G2`, `PONG-G2`). The tail of the file is **not** the assistant message — trailing records are `attachment`/`system` bookkeeping; a naive "read last line" fails.
- **Token usage — CONFIRMED.** `message.usage` on the same assistant record, identical key set across all samples: `cache_creation, cache_creation_input_tokens, cache_read_input_tokens, inference_geo, input_tokens, iterations, output_tokens, server_tool_use, service_tier, speed`. Model is co-located at `message.model`.
- **USD cost — REFUTED-for-contract.** Zero `*cost*`-named key found anywhere (roster, Stop payload key set, transcript, case-insensitive scan of two full transcripts). USD must be **computed** by the overlay from summed `message.usage` token counts × `message.model` pricing — there is no sanctioned source that carries a dollar figure.
- **Version pin, tolerant parsing required.** All observed transcripts are CLI `version: "2.1.207"`. The transcript JSONL format is an unversioned internal contract; key names above are **pin-tested observations at 2.1.207**, not a guaranteed stable API. The Stop-hook outcome-record implementation must feature-detect and fail soft, never assume these keys survive a version bump untested (re-verification requirement, §7 below).

---

## Steering contract

- **Idle-worker steering = fork-with-transcript (G2 outcome b).** `claude --bg --resume <sid> "<prompt>"` delivers the new prompt but **mints a new sid**; the forked session's transcript contains the entire prior conversation verbatim, followed by the new turn. The original session's roster entry, sid, and event count are left untouched — it is not the same live session going busy.
- **Overlay obligation:** every steer via `--bg --resume` restamps the worker's canonical sid to the new one, generates a fresh `-n` name (per spec §5.1.3, since G13 confirms there is no post-hoc rename), and re-points mailbox/journal bookkeeping. Capture the new sid from `--bg --resume`'s own stdout at call time — never re-poll the roster by name afterward (roster-name instability, dispatch contract §above).
- **`-p --resume` is a dead end for daemon-owned sessions.** Rejected outright without `--fork-session`; `--fork-session` itself was not tested against a `--bg`-managed session in this spike (UNOBSERVED whether it matches `--bg --resume`'s fork behavior).
- **A same-sid injection channel exists, but only interactively, only via the TUI.** G11's rate-limit recovery landed a `"continue"` prompt on the *original* sid with no fork — tagged `origin.kind:"human"` / `promptSource:"typed"`, operator-confirmed as a peek+reply through the agents menu (or `claude attach`), corroborated by PTY-pid churn at the same instant. This is **not** a CLI-scriptable channel — no `claude` subcommand was found (or exists per G13) that performs it headlessly. Fleet's automation cannot rely on this path; it is documented here only because it changes what "same-sid delivery is impossible" means (it's impossible *for the CLI*, not impossible in principle).

---

## Known hazards

- **[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION] The daemon is TRANSIENT — every CLI verb that needs it can fail when nothing holds it open.** (receipts: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q2, §Q4) `claude daemon --help` @2.1.212: *"Service install is disabled in this version — the daemon runs on demand and exits when the last client disconnects."* It starts on demand at dispatch (`origin=transient` on every `daemon start` line in the log) and idle-exits ~5s after the last client disconnects **and** its live-worker count reaches 0. A live `--bg` session holds it open; so does an open `claude agents`. With the daemon down, `claude rm`/`claude stop` fail (rc=1, *"the background service may be restarting"*) and **do not revive it — only a dispatch does**. `claude agents --json [--all]` still answers, from the on-disk roster/jobs snapshot.<br>**Why this bites fleet specifically:** the hygiene tier is, by construction, the code path most likely to meet a dead daemon and the least able to revive it — `fleet archive` and the `fleet autoclean` scheduled task only ever run against workers that are *not* live, which is exactly the zero-live-worker state in which the daemon has idle-exited. A hygiene pass must never dispatch to wake the daemon (that mints a new billable session); it defers loudly and retries next pass. **Corollary for every observer:** a fleet process running *inside* a `--bg` session (a supervisor, a worker, this contract's own probes) always sees a live daemon and therefore **cannot reproduce the dead-daemon path at all** — identical commands genuinely behave differently from an interactive session on a quiet machine. Anything measuring rm/stop must record `claude daemon status` alongside its verdict, or it is measuring an uncontrolled variable (this is precisely what made the pin tier's `test_5_pin_archive_rm` look RED — §Q1.4).
- **[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION] `claude daemon stop` has machine-wide blast radius — never automate it.** Its own `--help` reads *"Shut down the supervisor and terminate background sessions"*, with `--any` (also stop a transient daemon) and `--keep-workers` (leave detached sessions running). Default behavior kills background sessions **that are not the caller's**, including other operators' and other fleet workers'. No fleet code path, test, or probe may run `daemon stop`/`daemon uninstall`; a probe that seems to need it is BLOCKED, not run (§Q2).
- **stdin-dispatch wedge (G8 channel 2).** Piping a prompt via stdin to `claude --bg` does not hang the *dispatch command* — it returns normally with a `backgrounded · ...` line — but the **spawned session never starts a turn**: zero hook events (not even `SessionStart`), no transcript file created, for the entire ~171s window observed, with no self-recovery seen inside it. Never use stdin as a prompt channel for `--bg`; use task-file bootstrap (G8, CONFIRMED) instead. (VERDICTS.md §G8)
- **`taskkill` triggers a silent respawn (G10).** Killing a `--bg` session's pid directly does not durably stop it: the daemon supervisor detects the dead child and restarts it under a **new pid, identical `sessionId`**, within an observed window bounded between +6s and +36s — a full new `SessionStart`+`PreToolUse` hook cycle re-fires, and the session resumes sitting on whatever it was doing (e.g. the same pending permission prompt). This is the empirically confirmed, not hypothetical, reason raw pid kills are forbidden. **Never raw-kill; `claude stop <id>` only.** (VERDICTS.md §G10)
- **`claude stop` on a not-yet-naturally-ended session fires no Stop hook (G10).** Confirmed on two unconfounded samples (pre-turn-start kill, mid-turn permission-pending kill): the session transitions straight to `state: "stopped"` with zero corresponding Stop event, even after a 10–20s settle-and-recheck. **[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]** (receipts: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md` §Q1.3, §Q3) — re-verified and timed. On a **live** session: rc=0, `stopped <id>`, and the roster entry drops to a **`state`-only `stopped` record (no `status`, no `pid`)** — i.e. fleet's gone-or-dead gate is satisfied — in **1.5s** (the pin's 60s `_wait_for_roster_gone_or_dead` window is ~40× the observed need). On an **already-gone/never-existing** id: rc=1, `No job matching '<id>'. Run 'claude agents' to list running sessions.` — the same leading phrase as `rm`'s gone-message plus a hint sentence. With a **dead daemon**, `stop` fails like `rm` does and does not revive it (same manager-report provenance as G12's dead-daemon bullet — unverified by two waves). **CORRECTED (M5, review `MD-CONTRACT-REVIEW-2026-07-17.md`):** an earlier draft of this line claimed fleet deliberately left `_stop_native_session`'s bool semantics unchanged because "callers re-check the roster, which is fail-safe". **That justification was false at 2 of its 5 call sites** — `_cmd_kill_native`'s two stops re-check nothing; an already-gone sid made `fleet kill` exit 1, print "investigate the session manually" about a verifiably-gone session, report a retired sid as `timeout` (a mechanism that did not occur), and stamp `interrupt_outcome=False` into the durable event log. `stop` now shares rm's 3-way discriminator (`_stop_native_session_status`): `gone` is success, so `fleet kill` on an already-gone sid succeeds — while the G10 tombstone obligation and the mark-dead-regardless rule are unchanged.<br><br>**[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION] The `gone`→success inference has a precondition, and it is load-bearing:** it is sound **only if the ref the CLI rejected was the right ref**. `No job matching '<id>'` means "I have no job under *this identifier*" — which is the desired end state only when the identifier was correct. Fleet must therefore pass the CLI's **own** id (the roster entry's `id`, or the `native_short_id` captured from `--bg` stdout) and never a derived one wherever that inference is drawn — `rm` and `stop` alike. Derivation (`_native_job_ref`, `sid.split("-", 1)[0]`) remains only a fallback for refs fleet never captured (retired forks). **Repro'd consequence when this was violated on the `stop` path (ND-1, re-review):** a CLI that answers only to its own short id made `fleet kill` report success, exit 0, stamp `interrupt_outcome=True` and mark the worker dead **while the session kept running** — untracked, and skipped by every husk sweep forever because it is `status`/`pid`-live. Note the residual: `native_short_id` is itself derived on 2 of its 6 write paths, so the guarantee is only as strong as the capture. **This precondition is the single most important thing to re-check if the CLI's short-id format ever drifts.** **Tombstone obligation:** spec §5's outcome discriminator / stop flow must write its own tombstone record on an operator-initiated stop rather than assume the Stop hook already ran — a stopped worker with no outcome record is a real case that would otherwise misclassify as `dead-suspected` forever, or worse, as silently completed. (VERDICTS.md §G10)
- **Limit walls are silent (G7 / G11).** A rate-limit 429 kills the session's turn/self-wake loop mid-flight with **no Stop hook, no roster state change** — the only sanctioned-surface evidence is a synthetic 429 assistant record inside the transcript itself. A roster snapshot taken during a limit wall looks like a healthy idle/working entry. Detection must ride the dead-suspected investigation path (transcript-tail scan for limit-shaped text), never a hook. (VERDICTS.md §G7 same-sid restart anomaly section; design spec §2 G11 row)
- **"~1h" is process stop, not roster eviction — quoted from the primary source (VERDICTS.md §G5):** *"Once a session finishes and sits unattached for about an hour, the supervisor stops its process to free resources. A session you have pinned with `Ctrl+T` is exempt and keeps its process running while idle. The transcript and state stay on disk either way, and the next time you attach, peek, or reply to a stopped session, the supervisor starts a fresh process from where it left off."* (`https://code.claude.com/docs/en/agent-view.md`, fetched 2026-07-14). This spike's own bait session's roster entry survived unpinned and unevicted for **≥3h21m** — the two concepts (process stop vs. roster retention) must not be conflated in fleet's reap/heartbeat design.
- **`ai-title` can mutate a forked session's name (G2 anomaly, `explore-ui-cli-report.md` Probe B).** A `--bg --resume` fork's `name` was silently overwritten by the daemon's auto-titling shortly after its second turn (40-char+ellipsis auto-summary replacing the `-n` value). Plain, never-resumed dispatches were confirmed stable (2/2 negative controls). Sample size for the positive case is n=1 — a real hazard, not proven-deterministic, but the overlay must never rely on `name` surviving a resume/fork.
- **Reap of live idle sessions is UNOBSERVED (G5 sub-verdict b).** This spike confirmed the ~1h reap does not apply to *done* sessions' roster entries, but no experiment dispatched a long-lived, never-completing session and watched its **process** for eviction. If the documented pin behavior is actually targeting live-idle-process reap (as the primary-source quote above suggests), and pin has no scriptable surface (G5 sub-verdict a, REFUTED), the supervisor's heartbeat-only design could have an unguarded gap. Flagged by VERDICTS.md itself for Task 12 — not yet resolved.

---

## Re-verification

Per design spec §7 ("Risk and its gate"):

1. **Pin-test tier is required before any campaign.** A pin-test suite (haiku `--bg` worker: dispatch, assert the JSON contract per state above, confirm hook firing including Stop, confirm `claude stop` behavior) must pass before fleet dispatches real work on this substrate. This spike's own harness (`spike/m0/hook_probe.py`, `spike/m0/worker-settings.json`) is the seed for that tier.
2. **`fleet doctor` must warn on a `claude --version` change since the last pin-test pass.** Every contract fact in this document — the roster's closed 8-9-key schema, the transcript's `message.usage`/`message.content[].text` key names, the `--session-id`/`--bg` composition failure, the `--bg --resume` fork behavior — was observed at exactly `claude --version` 2.1.207 and is explicitly **not** guaranteed to survive an update; the transcript format in particular is stated by Anthropic to be an unversioned internal contract (§ Result/cost contract above).
3. **No daemon/jobs file access in production.** `~/.claude/daemon/` and `~/.claude/jobs/` were inspected read-only for research in this spike only (e.g. `state.json`'s `tokens`/`output` fields, `timeline.jsonl`'s undocumented `text` key, `roster.json`'s empty `workers` dict despite 17 live sessions) — none of that research backs any verdict above, and fleet's production code must use the CLI + `--json` only, per the pre-registered spike rule.

## 2.1.212 re-verification

**Status: `[OBSERVED 2.1.212 — PENDING OPERATOR RATIFICATION]`. Nothing here is
self-ratified.** Author: fleet worker `md-contract` (M-D wave), 2026-07-17.
Full receipts: `docs/reviews/CLAUDE-2.1.212-CONTRACT-2026-07-17.md`.

### The break

The FLEET_LIVE pin tier went RED on 2.1.212 (8th live catch). The trigger was a
**daemon-lifecycle change, not a contract break**: the daemon is now transient —
no service install, started on demand by a dispatch, gone ~5s after the last
client disconnects and the last worker settles. `claude rm`/`claude stop` fail
while it is down and cannot revive it.

**The brief's central premise did not survive re-verification and was not built
on.** It held that with a *live* daemon, `claude rm` leaves the sid in
`claude agents --json --all`, and that this was what failed the pin. **REFUTED,
3/3 samples** (§Q1): rm with a live daemon removes the entry *and* its jobs dir
in <1s, including against a live mid-turn session. The pin suite passes **6/6
unmodified** on this machine (§Q1.4). The RED is real but **environment-
dependent**: it needs the daemon to be down at rm time, which needs no `--bg`
session to be holding it open.

### What actually changed for fleet

`claude rm`'s **`rc=1` is three-way ambiguous** — already-gone / dead-daemon /
real failure — and the message is the only discriminator (§Q3). G12's
idempotency assumption is refuted in form (an already-gone id is rc=1
`No job matching`, not rc=0), though the effect is unchanged. Fleet had
collapsed all three to "failed", which both cried wolf on already-clean sids and
made a retryable dead-daemon skip indistinguishable from a permanent one.

### The adaptation (shipped on `md/contract`)

- `bin/fleet.py`: `_classify_native_cli_result` + `_rm_native_session_status`
  classify by message. `gone` ⇒ success. `daemon-transient` ⇒ **loud, non-fatal
  deferral** naming the reason; the husk stays on the roster and the autoclean
  husk tier retries it next pass. Never a crash, never a silent success-claim.
  The brief's preferred "retry-after-nudge" is **not** implemented **because no
  sanctioned nudge exists**: only a dispatch revives the daemon, and a hygiene
  pass that mints a billable session as a side effect would be a worse bug than
  the one it fixes (§Q2).
- **Roster reads: zero changes**, on evidence. An idle-exit is gated on
  `live_workers=0` (15/15 receipts) and so cannot strand a live-looking entry;
  every roster call site was audited by grep against that timeline and is
  already behind the epoch-freeze or fails safe (§Q4 table). G9 doctrine —
  never assume dead on ambiguity — argues against "hardening" what the evidence
  clears.
- `tests/integration/test_native_pin.py`: step 5's roster-gone assertion is now
  conditioned on `_daemon_alive()` and every verdict pastes `claude daemon
  status`, so the tier stops silently depending on daemon liveness and a future
  RED names the daemon state instead of blaming rm. The rm taxonomy is pinned
  live.

### Open, for the operator (NOT resolved here)

1. **Ratify or reject** every `[OBSERVED 2.1.212 …]` amendment in this file
   (G12, G9, the two new hazards, the G10/stop timing). No author ratifies their
   own contract amendment.
2. **`claude daemon run` detached as a revival nudge — UNPROBED, deliberately.**
   Starting a second supervisor while other workers are live risks a
   takeover/adopt, which the daemon log shows is a real, worker-affecting path
   (`bg adopt: adopted=1 …`; `post-takeover prewarm burst — respawned 0/1 stale
   workers, 1 refused`). Needs a quiet machine — **fold it into the G9 standalone
   probe below**, which is already parked for the same reason.
3. **The `cause=upgrade` shutdown path** (4/4 shut down with live workers, up to
   `live_workers=4`, with an observed "1 refused" respawn) is the one remaining
   stale-roster vector. It belongs to the G9 probe, not to any idle-exit claim.
4. **`FLEET_LIVE` pin runs are not environment-neutral.** A green pin run from a
   `--bg` worker does not prove the dead-daemon path works — that path is
   unreachable from inside a bg session. Ratifying the hygiene fix on live
   evidence requires a run from an interactive session on a quiet machine.
5. **Audit `native_short_id`'s two derived write paths** (added by the ND-1 fix
   wave). Fleet now stops/rms by the CLI's own captured id wherever it draws the
   `gone`→success inference, but `native_short_id` is captured from `--bg`
   stdout on only 4 of its 6 writes; two fast-sid paths derive it
   (`fast_sid.partition("-")[0] or fast_sid[:8]`) — the same "derive rather than
   read" pattern, one layer up. Harmless at 2.1.212 (the derivation is correct
   today) and out of scope for this wave, but it is the residue that would make
   the ND-1 guarantee only partial under a short-id format drift.
6. **Capture the transient message's actual bytes** (added by the M4 fix wave).
   `couldn't remove <id> — the background service may be restarting. Try again
   in a moment.` is a manager report that **two independent waves have now failed
   to re-observe** — the builder and its adversarial reviewer, both `--bg`
   sessions. Everything downstream of it (`_NATIVE_CLI_TRANSIENT_RE`, the
   `RM_TRANSIENT` test stub, the pin's skip branch, G12's dead-daemon bullet)
   inherits that provenance. Fold the capture into the G9 standalone probe: on a
   quiet machine with no bg session live, run `claude rm <id>` and `claude stop
   <id>` against a dead daemon and paste the exact stdout/stderr/rc. Two further
   load-bearing claims need the same treatment in that probe: **"rm does not
   revive the daemon; only a dispatch does"** (the entire justification for
   loud-non-fatal-deferral over retry-after-nudge) and **"with a dead daemon
   `claude agents --json [--all]` still answers from the on-disk snapshot"**
   (without which the husk tier cannot even see the husks it defers).

## Ratifications (Task 12 gate review, 2026-07-14)

- RATIFIED 2026-07-14: G2 fallback — steering an idle worker = fork-with-transcript via `--bg --resume`; overlay restamps the sid; fresh `-n` renders category on every steer.
- RATIFIED 2026-07-14: spec v2.3 delta (§5.1.1 usage-limit continuity as first M-B feature, §5.1.2 auto-archival, §5.1.3 agents-menu categories; gates G11–G13).
- RATIFIED 2026-07-14: G9 DEFERRED — operator runs the standalone probe below at a quiet moment; the roster-epoch freeze rule (spec §5) is binding regardless of outcome.
- RATIFIED 2026-07-14: M-A plan authoring green-lit.

### G9 standalone probe (operator, ~5 min — kills every background session on the machine)

1. `claude agents --json` — confirm nothing live that you care about.
2. `claude --bg -n g9-probe --model haiku "Use the Bash tool to run: sleep 300. Then reply DONE."`
3. Probe `claude daemon --help` for a native stop/restart; else find and stop the daemon supervisor process.
4. After restart: `claude agents --json --all` — record whether g9-probe survived, whether the roster reset, whether pinned entries persisted.
5. Paste outputs into a fleet session; the G9 row gets its verdict then.
