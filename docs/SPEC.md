# claude-fleet — one Claude Code session managing many

**Status:** v2.1 (2026-07-08) — post adversarial review; v1 findings folded in. v2.1 amendment (SPEC-REVIEW-2026-07-08) folds state-machine defect B1 + guard/race/probe majors M2/M3/M4 into §4/§5/§11/§12 (appendix F17–F20). Body brings the spec TO the shipped code; no code change proposed.
**Owner:** Altai
**Location:** `C:\proga\claude-fleet` (system-wide tool, own repo — never part of any managed project)
**Target machine:** Windows 10, PowerShell, Git Bash present, Python via `py -3.13`, Claude Code CLI ≥ 2.1.202.

## 1. Problem & goals

One "manager" Claude Code session must spawn, monitor, steer, and collect results from multiple "worker" Claude Code sessions across arbitrary project directories on this machine. The human must be able to drop into any worker interactively at any time and hand it back. The manager acts as a general dispatcher ("another me"): parallel fan-out, long-running babysitting, cross-project routing, review pipelines — with a persistent, growing knowledge base.

**Non-goals (v1):**
- No daemon, no server, no background supervisor process.
- No true mid-turn conversational back-and-forth with a worker (mailbox injection at tool boundaries is the approximation).
- No cross-machine orchestration; no scheduling (manager does that itself).

## 2. Core design decisions

**Sessions, not processes.** A Claude Code session is durable state on disk addressable by `--session-id` / `--resume`. A worker is a *session*; each turn is a short-lived `claude -p` process. Crash-safe by construction. The registry tracks metadata plus the currently-running turn PID.

**Resume is cwd-scoped (load-bearing invariant).** `--resume <sid>` only finds the session from the same project directory (or its worktrees). Every turn launch and every attach MUST run with the worker's registered `cwd`. The `cwd` field in the registry is immutable after spawn.

**Why not the built-in `claude --bg` / `claude agents`?** CLI 2.1.202 ships background agents (`claude --bg`, `claude agents --json`). They cover spawn+list+monitor but provide none of: named registry with per-task permission modes, mailbox steering mid-turn, journals + respawn continuity, attach/headless conflict guards, or a knowledge loop. Fleet v1 uses its own detached launcher because the interaction of `--bg` with `--settings`-injected hooks and `--resume` turn cycling is undocumented; `fleet doctor` prints a note if `claude agents --json` shows fleet-unknown sessions. Revisit adopting `--bg` as the launch mechanism when its semantics are documented.

## 3. Repo layout

```
C:\proga\claude-fleet\
  bin\
    fleet.py              # single-file CLI, py -3.13, stdlib only
    fleet.cmd             # shim: @py -3.13 C:\proga\claude-fleet\bin\fleet.py %*  (dir added to PATH)
    hooks\
      posttooluse_mailbox.py   # mid-turn mailbox injection
      stop_mailbox.py          # turn-end mailbox drain / stop-block
  worker-settings.template.json  # hook wiring TEMPLATE (git-tracked, {{PYTHON}}/{{FLEET_HOME}} placeholders); `fleet init` renders it
  skill\SKILL.md          # manager skill; installed by copying to %USERPROFILE%\.claude\skills\fleet\ (README one-liner)
  knowledge\
    INDEX.md              # one line per entry; manager loads this at session start
    playbooks\            # e.g. review-pipeline.md, spawn-etiquette.md
    projects\             # per-project quirks: pmbot.md, expardus.md, ...
    lessons.md            # append-only postmortems
  state\                  # gitignored
    fleet.json            # registry (single writer: fleet.py, lock file)
    events.jsonl          # append-only lifecycle events, written by fleet.py ONLY
    worker-settings.json  # machine-local instance rendered by `fleet init` from the template above; passed to every worker via --settings (SPEC §14)
    journals\<name>.md    # worker journals (NOT in managed repos — keeps them git-clean)
  logs\                   # gitignored; <name>.jsonl (stdout) + <name>.err (stderr), per worker
  mailbox\                # gitignored; <session_id>.md pending messages
  docs\SPEC.md            # this file
```

`knowledge/` is git-tracked — the ever-improving part. `state/`, `logs/`, `mailbox/` are runtime, gitignored.

## 4. Registry schema (`state\fleet.json`)

```json
{
  "workers": {
    "pmbot-probe": {
      "session_id": "uuid4",
      "cwd": "C:\\proga\\polymarket_experimenting",
      "task": "first ~200 chars of original task",
      "mode": "bypass | accept | dontask | plan | omit",
      "model": null,
      "created": "2026-07-07T12:00:00Z",
      "status": "working | idle | attached | dead",
      "turn_pid": 12345,
      "turn_pid_ctime": "2026-07-07T12:30:00Z",
      "attached_since": null,
      "turns": 3,
      "cost_usd": 1.23,
      "last_activity": "2026-07-07T12:34:56Z"
    }
  }
}
```

Names are human-chosen, unique, `[a-z0-9-]+`. Single-writer discipline: only `fleet.py` writes `fleet.json`, guarded by `state\fleet.lock` (atomic-rename lock with retry). Hooks never write registry or events; they touch only mailbox files.

**PID liveness — three-way probe (v2.1, M4).** The stored `turn_pid`/`turn_pid_ctime` classifies into exactly one of three verdicts, never a bare alive/dead boolean:
- **alive-and-matching** — PID exists AND image is claude AND creation time matches `turn_pid_ctime` (± 2 s). Turn is live.
- **definitely-gone** — PID absent, or present with non-matching image/ctime (PID reuse). Turn ended. (PID reuse would otherwise misclassify a dead worker as working and let `interrupt` kill an innocent worker's turn — so the ctime match is load-bearing.)
- **alive-unknown** — the process exists but the query itself failed, OR the stored `turn_pid`/`turn_pid_ctime` is null/corrupt. Real case: a worker spawned from a higher-integrity/elevated terminal, probed by a `fleet status` running unelevated — `Get-Process` returns the object but `.StartTime` throws `Win32Exception`, so a naive probe reads empty stdout and wrongly concludes "gone." The launch path itself stores `None` on a ctime-query failure, another source of alive-unknown.

The probe separates these via a try/catch marker in the PowerShell script (optional `Get-CimInstance` fallback). **alive-unknown is never demoted to `dead`, and is never respawn-/kill-eligible without `--force`.** A missing pid/ctime or any query failure counts as not-live, but **any `working`→`dead` transition first retries the probe once after a short delay**; only a stable `definitely-gone` may demote. Operating rule: run fleet at the SAME elevation as the workers it spawned — otherwise `taskkill` is access-denied and `interrupt` cannot clean up; `fleet doctor` checks for the elevation mismatch. Accepted residual: a genuinely-crashed turn whose PID is unreadable stays `working` (alive-unknown) until a retry succeeds or an operator runs `respawn --force` — fail-safe toward NOT launching a second live claude. Per-OS query-failure modes are carried into portability OQ2 (`docs/specs/portability.md`, owned separately).

**Status recompute is scoped (v2.1, B1).** Recompute derives status from the log tail + probe ONLY for records already in status `working` with a **non-None `turn_pid`**. Every other state is sticky or pre-claim and recompute leaves it untouched:
- **`dead` is sticky** — the sole exit is `fleet respawn`. An operator `kill` is terminal; recompute never resurrects it. (Without this, a `result` line in the log tail flips a killed worker back to idle and `fleet clean` becomes unreachable — SMOKE-D, pinned by `tests/test_core.py:497`.)
- **`attached` is sticky** — the sole exit is `fleet release` (or `respawn --force`). Recompute never demotes attached → idle; demoting it would let a `send` launch a resume turn against a session that may still hold a live TUI, breaking one-live-claude.
- **`working` + `turn_pid = None` = launch-in-flight (pre-claim)** — written under `fleet.lock` before `Popen` by every turn-starting path, and NEVER demoted. This window is exactly what enforces one-live-claude against a concurrent send/attach. Residual: a CLI killed between the pre-claim write and `Popen` leaves a pinned-`working` record with `turn_pid = None`; it is cleared by `respawn`, not by recompute.
- **Classification uses the last SUBSTANTIVE stream event**, scanning backwards past `type:"system"`, hook lines, and junk — NOT the literal last stdout line. §6 mandates `--include-hook-events`, so hook/system lines land AFTER the `result` line on every real launch (SMOKE-A); keying on the literal last line would mark every healthy completed turn as dead. For an in-scope `working` record: last substantive event is `result` → idle; no `result` and probe is definitely-gone → dead (crashed turn); probe alive-unknown → stays `working` (retry once first).

## 5. CLI commands

All output is **small** — the CLI does the compression; the manager never reads raw `logs\*.jsonl`.

| Command | Behavior |
|---|---|
| `fleet spawn <name> --dir <path> --task <text\|@file> [--mode bypass\|accept\|dontask\|plan\|omit] [--model m] [--max-budget-usd x]` | Generate uuid4; compose prompt (preamble §8 + task + any pending mailbox); launch detached turn (§6). Journals always on. Prints name, session_id, log path. |
| `fleet send <name> <text\|@file>` | Turn running → append to `mailbox\<sid>.md`. Idle → launch resume-turn whose prompt = drained mailbox + message. Attached → mailbox + warn (see §9 asymmetry). **(v2.1, M3)** the working/attached-branch mailbox append is serialized against a concurrent `respawn` sid-swap: either it happens under `fleet.lock`, or send re-reads the registry after appending and re-appends to the NEW sid if the sid changed. Without this, a respawn that drains+removes `mailbox\S1.md` and swaps to sid S2 under the lock races an in-flight send that recreates `mailbox\S1.md` — mail no drain rule (both keyed to the current sid) ever touches again, silently lost, breaking §5's "consumed, not orphaned" promise. |
| `fleet status [name]` | Table: name, status, turns, $cost, min since activity, pending-mail count, attach age. Flags anomalies: `idle+mail`, stale attach, dead. |
| `fleet peek <name> [-n 20]` | Digest of recent stream events: last tool calls (name + brief input), last assistant text (truncated), tokens/cost. Confirms fleet hooks fired (needs `--include-hook-events` at spawn). ~20 lines max. |
| `fleet result <name>` | Final `result` event text of last completed turn, nothing else. |
| `fleet wait <name...> [--any\|--all] [--timeout s]` | Block until turn(s) end. Manager runs via Bash `run_in_background` → notification instead of polling. Default `--all`. |
| `fleet attach <name>` | Guard: refuse while turn running (`--force` = interrupt first). Set status=attached + timestamp; launch `wt -d <cwd> -- claude --resume <sid>` if `wt` exists, else `Start-Process powershell -WorkingDirectory <cwd> -ArgumentList '-NoExit','-Command','claude --resume <sid>'`. |
| `fleet release <name>` | Manual detach → idle. (TUI-close detection on Windows unreliable; explicit release. `status`/`doctor` nag on stale attach.) |
| `fleet interrupt <name>` | Kill turn PID tree (taskkill /T) after ctime check. Transcript up to kill persists. **(v2.1, B1 face e)** clears `turn_pid` on commit and commits the resulting status DIRECTLY — turn left a `result` event → idle, no result → dead — rather than leaving a stale killed PID for a later recompute to re-derive (which, with the scoping above, would otherwise yield "dead" ambiguously). Killed-CLI residual: a `working`+`turn_pid=None` record left by a CLI killed mid-launch is cleared only by respawn. Respawn to continue after a dead commit. |
| `fleet respawn <name> [--task <text>]` | New session_id, same name/cwd/mode. Prompt = original task + journal contents + drained mailbox (old sid's mailbox is consumed, not orphaned). Old sid logged to events. Context-reset lever; rotates the log file. **(v2.1, M2 `--force` ladder)** refuses while a turn runs unless `--force` (which first interrupts via `_interrupt_worker`; a `kill_failed` verdict aborts with NO mutation); refuses an `attached` worker without `--force`; refuses a launch-in-flight (`working`+`turn_pid=None`) claim EVEN with `--force`. Log rotation renames `.jsonl`→`.jsonl.1` (and `.err`→`.err.1`) only AFTER the old turn is confirmed dead — never while the live claude holds the log open. **(v2.1, M3)** the drain of `mailbox\<old-sid>.md` + the sid-swap are atomic w.r.t. `send` (see the send row): the swap happens under `fleet.lock` so no in-flight send can strand mail on the retired sid. |
| `fleet kill <name>` / `fleet clean` | Interrupt + dead; clean removes dead entries + logs/mailboxes/journals. **(v2.1, M2)** kill refuses a launch-in-flight (`working`+`turn_pid=None`) claim; on a `not_running` verdict it re-probes once after `_DEAD_CONFIRM_DELAY_SECONDS` (0.5 s) before committing dead (guards the same alive-unknown false-negative §4 warns of); it clears `turn_pid` on commit; a `kill_failed` verdict marks nothing and **exits 1 loudly** (no silent success). clean's artifact sweep is the FULL set: dead entries + `<name>.jsonl`/`.err` + **rotated `.jsonl.1`/`.err.1`** + `mailbox\<sid>.md` + **orphaned `mailbox\*.claimed.*`** claim files + journals. |
| `fleet doctor` | Checks: claude on PATH + version; `worker-settings.json` validates (print mode ignores invalid settings SILENTLY — this check is the only alarm); end-to-end hook smoke test (fire posttooluse script with synthetic stdin, assert JSON out); wt present or fallback noted; stale PIDs; orphaned/pending mailboxes; stale attaches; fleet-unknown `claude agents` sessions; log sizes; **(v2.1, M4)** elevation mismatch (workers spawned at a higher integrity level than the fleet CLI now running). **(v2.1, M3) "orphaned mailbox" defined:** a `mailbox\<sid>.md` whose sid matches NO registered worker (the residue of a send that raced a respawn sid-swap). Disposition: doctor prints the sid + the mail's first line; the operator re-sends the content to the live worker or deletes the file. |

**The universal drain rule (closes all stranding races):** every turn launch — spawn, send-when-idle, respawn — first drains `mailbox\<sid>.md` into the prompt. A message can land in the mailbox after the Stop hook drained but before the process exits; it is picked up by the next launch, and `fleet status` flags `idle+mail` so the manager notices workers with undelivered mail. **(v2.1, M3)** the drain rule and the `idle+mail` flag are both keyed to the CURRENT sid, so mail stranded on a RETIRED sid (a send racing a respawn sid-swap) is invisible to them — that window is closed by the send-serialization rule (send row) and any residue caught by doctor's "orphaned mailbox" check, not by this drain rule.

## 6. Worker turn launch (Windows detail)

```
claude -p --output-format stream-json --verbose --include-hook-events
  [--resume <sid> | --session-id <sid>]
  --settings C:/proga/claude-fleet/worker-settings.json
  [--permission-mode acceptEdits|dontAsk|plan | --dangerously-skip-permissions]
  [--model <m>] [--max-budget-usd <x>]
```

- **Prompt via stdin, never argv** (32K CreateProcess limit; preamble+task+journal easily exceeds it). `claude -p` reads the prompt from stdin; Popen writes prompt then closes stdin. Never leave stdin open/inherited — non-TTY open stdin causes a 3 s stall + `Warning: no stdin data received` on stderr every turn.
- `--verbose` is mandatory with `-p --output-format stream-json` (CLI errors without it).
- Launched via `subprocess.Popen`, `creationflags=DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP`, `cwd=<worker cwd>` (resume invariant §2), stdout → `logs\<name>.jsonl`, **stderr → separate `logs\<name>.err`** (stderr in the jsonl breaks parsing). Parsers additionally skip non-JSON lines defensively. (Machine gotcha: never background via Git-Bash `&` — reaped. Win32 flags or Start-Process only.)
- First turn `--session-id <uuid>`; later turns `--resume <sid>`.
- Record `turn_pid` + creation time. **Concurrency guard:** never two claude processes on one session — send-while-working writes mailbox only; attach refuses while working.

**Permission modes** (per-task, validated against real CLI choices `acceptEdits, auto, bypassPermissions, manual, dontAsk, plan`):
- `bypass` → `--dangerously-skip-permissions` (trusted grind in known repo)
- `accept` → `--permission-mode acceptEdits`
- `dontask` → `--permission-mode dontAsk` (middle ground: auto-deny outside allowlist rather than stall)
- `plan` → `--permission-mode plan`
- `omit` → no flag; print mode *denies* un-allowlisted actions (does not hang) — worker likely ends early; only for workers you intend to attach to.

**Foreign hooks policy:** worker repos' own `.claude/settings.json` hooks and global plugin hooks (caveman, codex stop-gate) merge into worker turns. v1 policy: leave them on (project hooks are usually wanted, e.g. lint gates); if a foreign Stop-hook fights fleet's turn-end model, spawn supports `--setting-sources` passthrough to restrict sources. Documented in the skill; not automated in v1.

## 7. Mailbox + hooks (mid-turn steering)

`worker-settings.json` — **forward slashes only**: on Windows hook commands run under Git Bash (`sh -c`), which eats backslashes in unquoted strings; backslash paths silently break every hook.

Pre-render illustration; `fleet init` renders `{{PYTHON}}`/`{{FLEET_HOME}}` from the git-tracked `worker-settings.template.json` into the machine-local `state\worker-settings.json` instance (SPEC §14).

```json
{
  "hooks": {
    "PostToolUse": [{ "hooks": [{ "type": "command",
      "command": "py -3.13 C:/proga/claude-fleet/bin/hooks/posttooluse_mailbox.py" }] }],
    "Stop": [{ "hooks": [{ "type": "command",
      "command": "py -3.13 C:/proga/claude-fleet/bin/hooks/stop_mailbox.py" }] }]
  }
}
```

Both hooks read stdin JSON (`session_id` is provided), check `mailbox/<session_id>.md`:

- **PostToolUse:** non-empty → claim by `os.replace` to `<file>.claimed.<pid>`, emit `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "<MANAGER MESSAGE>\n..."}}`, delete claimed file. Worker sees it between tool calls — seconds-level mid-turn latency. Missing/empty → exit 0 silently.
- **Stop:** mailbox non-empty → claim, `{"decision": "block", "reason": "<contents>"}` → turn continues with the queued instruction. Empty → allow stop. Honor `stop_hook_active` politely; **no custom loop counter** — Claude Code force-allows stop after 8 consecutive blocks natively, and continuation requires fresh manager mail anyway.
- **Hook scripts are exception-proof:** everything in try/except, always exit 0 on any error (uncaught tracebacks surface stderr into the worker's transcript as noise). Parallel PostToolUse invocations race on the claim — `os.replace` loser catches FileNotFoundError and exits 0; concurrent append during rename can raise PermissionError on NTFS — claimer retries once then defers to the next boundary.
- Multiple sends append to one mailbox file (small `open(..., "a")` writes); first hook to claim drains all.
- Hooks are additive via `--settings` — managed projects' own settings still apply; fleet never edits project files.
- Silent-failure alarm: settings validation errors are swallowed in print mode, so `fleet doctor` validates `worker-settings.json` and smoke-tests both hook scripts; `fleet peek` shows whether hook events appear in the stream (`--include-hook-events`).

## 8. Worker rules preamble

`fleet spawn` prepends a standard preamble to every task:

- You are fleet worker `<name>` in `<cwd>`; manager messages arrive mid-task marked `<MANAGER MESSAGE>` — treat as user instructions.
- Maintain journal at `C:/proga/claude-fleet/state/journals/<name>.md` (create early; update each milestone): goal, done, in-progress, blockers, next steps. Must be enough for a fresh session to continue. (Journal lives in fleet state, not the project repo — managed repos stay git-clean.)
- End every turn with a compact result summary (changed, verified, blocked).
- No servers/watchers outliving the turn without recording PIDs in the journal.

The journal is the context backbone: `fleet respawn` = fresh context, zero lost state.

## 9. Hybrid interaction model (human ↔ worker)

1. Observe anytime: `fleet peek` (mid-turn, reads live log).
2. Steer anytime: `fleet send` — mailbox mid-turn, resume when idle.
3. Take over: `fleet attach <name>` → terminal tab (wt or PowerShell fallback), full TUI, whole history.
4. Hand back: close tab, `fleet release <name>`.

**Attach asymmetry (stated, not hidden):** the attached TUI runs WITHOUT `--settings`, so fleet hooks don't fire during attach — mailbox mail queues untouched until the next headless turn. `fleet status` shows attach age + pending mail; `doctor` nags attaches older than a few hours. One live claude process per session, ever: attach refuses while a turn runs (`--force` interrupts), sends never spawn turns while attached.

## 10. Manager skill (`~\.claude\skills\fleet\SKILL.md`)

Triggers: "fleet", "spawn workers", "manage sessions", "dispatch to <project>". Content:

- CLI reference (compressed §5 table).
- Startup ritual: `fleet status`; read `knowledge\INDEX.md`; load relevant `knowledge\projects\*.md`.
- Doctrine: one task per worker; prefer respawn over 100-turn sessions; `fleet wait` in background Bash, never sleep loops; never read raw logs; batch independent spawns; budget caps on unbounded tasks.
- Permission doctrine: destructive/unfamiliar → `accept`/`plan`; trusted grind → `bypass`; record choice.
- **Learning loop (mandatory):** after every campaign append to `knowledge\lessons.md`, update `knowledge\projects\<p>.md`, add INDEX.md lines, commit knowledge changes.

## 11. Edge cases & failure modes

| Case | Handling |
|---|---|
| Turn crashes mid-turn | Probe definitely-gone (ctime-checked) + no result line → dead; `fleet respawn` from journal. **(v2.1, M4)** an alive-unknown probe (unreadable PID) stays `working` and is retried once — never demoted to dead on a query failure. |
| Send races turn-end | Universal drain rule (§5) + `idle+mail` flag in status. |
| Two sends race | Append-only mailbox; claim-by-`os.replace`; loser exits 0. |
| Manager session dies | Nothing breaks; new manager runs `fleet status`, continues. |
| Worker burns context | Journal + respawn (mailbox carried over); CC auto-compaction inside worker still applies. |
| Resume while attached | Blocked by attach status; manual bypass = user's own risk; doctor flags double claude on one session. |
| Reboot | PIDs invalid → statuses recomputed on next CLI call, but recompute obeys §4 scoping: only `working`+non-None `turn_pid` records recompute (→ dead, since post-reboot PIDs are definitely-gone). **(v2.1, B1 face b/f) `attached` is EXEMPT** — never auto-recovered to idle by reboot recompute; recovery is a manual `fleet release` + `doctor` nag, preserving the explicit-release model of §5/§9. `dead` stays dead; launch-in-flight (`turn_pid=None`) stays working until respawn. Sessions resume fine. |
| Session file corrupt / resume fails | Respawn from journal (journal lives in fleet state, survives). |
| Runaway worker | `--max-budget-usd` passthrough (documented flag, better than undocumented `--max-turns`); `fleet interrupt`. |
| Invalid worker-settings.json | Print mode ignores silently → doctor validation + peek hook-event visibility are the alarms. |
| Log bloat | stream-json+verbose logs are fat: respawn rotates logs; clean removes dead workers' logs; doctor reports sizes. |

## 12. Testing

- Unit (pytest, no claude): registry CRUD+lock, mailbox claim races, stream-jsonl parsing (incl. junk lines), PID+ctime liveness matrix, prompt composition, drain rule.
- Hook tests: synthetic stdin JSON → assert emitted JSON + mailbox state; exception paths exit 0.
- Integration (manual, haiku, temp dir): spawn → status/peek/result; send mid-turn → injection visible in stream log; **headless Stop-block behaves as documented (first M2 test — only hook assumption not fully verified)**; attach/release; respawn continuity.

**v2.1 required regressions** (state machine, guards, races, probe — named, each pins a §4/§5/§11 amendment; correct code passes, spec-as-written-in-v2 would fail):
- `recompute_scoped_to_working_nonnull_pid` — recompute skips idle/dead/attached and `working`+`turn_pid=None`; touches only `working`+non-None pid.
- `dead_is_sticky` — a `result` log tail never resurrects a killed/dead worker; respawn is the only exit (SMOKE-D; pins `tests/test_core.py:497`).
- `attached_is_sticky` — recompute (incl. post-reboot) never demotes `attached` → idle.
- `preclaim_never_demoted` — `working`+`turn_pid=None` survives recompute unchanged.
- `classification_scans_past_system` — a `result` followed by trailing `type:"system"`/hook lines classifies idle, not dead (SMOKE-A).
- `interrupt_kill_clear_turn_pid` — interrupt and kill null `turn_pid` on commit and commit dead/idle directly (not recompute-derived).
- `respawn_force_ladder` — refuse live turn without `--force`; refuse `attached` without `--force`; refuse launch-in-flight EVEN with `--force`; `kill_failed` aborts with no mutation; log rotation only after old turn confirmed dead.
- `kill_dead_confirm_double_probe` — a `not_running` verdict is re-probed after 0.5 s (`_DEAD_CONFIRM_DELAY_SECONDS`) before dead; `kill_failed` → exit 1, no mutation.
- `clean_full_artifact_sweep` — clean removes rotated `.jsonl.1`/`.err.1` logs and orphaned `mailbox/*.claimed.*` files in addition to dead entries/logs/mailboxes/journals.
- `send_serialized_vs_respawn_sidswap` — a send racing a respawn sid-swap does not strand mail on the retired sid (append under `fleet.lock`, or re-read registry + re-append to new sid).
- `probe_three_way` — probe returns alive-and-matching / definitely-gone / alive-unknown; alive-unknown is never demoted to dead and never respawn/kill-eligible without `--force`; a `working`→`dead` transition retries the probe once first.
- `orphaned_mailbox_defined` — doctor reports a `mailbox/<sid>.md` whose sid matches no registered worker, printing sid + first line.

## 13. Milestones

1. **M1 — core loop:** spawn / status / peek / result / wait, registry, detached launch, drain rule. Worker completes a real task.
2. **M2 — steering:** hooks, send, interrupt. First test: headless Stop-block smoke test.
3. **M3 — hybrid:** attach / release / guards (incl. PowerShell fallback).
4. **M4 — resilience:** respawn, doctor, clean.
5. **M5 — manager brain:** skill, knowledge scaffolding, first campaign, first lessons.md entry.

Each milestone independently usable.

## 14. Portability requirements (added post-v2; full spec: `docs/specs/portability.md`)

Phase 1 builds and tests on Windows, but must not bake in Windows-isms beyond one boundary:

- ALL OS-specific behavior (detached spawn, kill-tree, PID+ctime liveness, attach terminal, notifications) goes through a single platform-adapter module. Nothing else may branch on `os.name`/`sys.platform`.
- No hardcoded `C:/proga/claude-fleet` outside generated files: resolve FLEET_HOME from `fleet.py` location (overridable via `FLEET_HOME` env var). `worker-settings.json` becomes a git-tracked TEMPLATE; `fleet init` generates the machine-local instance (correct interpreter path, absolute FLEET_HOME paths, forward slashes) into a gitignored location; doctor checks instance freshness.
- `pathlib` everywhere; `py -3.13` only inside Windows shims; code paths use `sys.executable`.
- Target floor: Python 3.10+ (distro pythons on Linux/macOS), stdlib only.

---

## Appendix: adversarial review disposition (v1 → v2)

Blockers fixed: hook paths → forward slashes + doctor smoke test (F1); universal drain rule (F2); attach PowerShell fallback (F3). Majors fixed: stdin DEVNULL-after-write + stderr split (F4); PID ctime (F5); doctor settings validation + `--include-hook-events` (F6); cwd-scope invariant + real mode names (F7); `--bg` comparison §2 (F8); respawn drains mailbox (F9). Minors: counter deleted (F10); exception-proof hooks (F11); attach age/mail visibility (F12); stdin prompt (F13); journals → fleet state (F14); list-projects/install-skill/hook-events-writer deleted, journals always-on (F15); wait --any/--all, cost in status, --max-budget-usd, foreign-hooks policy, log rotation (F16).

## Appendix (v2.1): state-machine & guard disposition (SPEC-REVIEW-2026-07-08)

Four findings from `docs/reviews/SPEC-REVIEW-2026-07-08.md` folded here. These bring the spec TO the already-shipped, already-correct code (commit/test anchors cited); no code change is proposed. Continues the F-series; the settled F1–F16 above are untouched and not relitigated (this doc's F9 = respawn drain-at-respawn-time is a DIFFERENT finding from the review's M3 lock-ordering rule below).

**F17 = review B1 — §4 status state machine scoped & made sticky (§4, §5 interrupt/kill, §11 reboot, §12).** One defect, five faces: (a) sticky-dead — a `result` log tail no longer resurrects an operator-killed worker; `dead` is sticky with `respawn` the sole exit (SMOKE-D, commit 641298d, `tests/test_core.py:497`). (b) sticky-attached — recompute never demotes `attached` → idle, so a `send` can't launch a resume turn onto a session that may hold a live TUI. (c) hook-tail — classification uses the last SUBSTANTIVE stream event, scanning backwards past `type:"system"`/hook/junk lines (SMOKE-A), not the literal last stdout line, so a healthy completed turn isn't misread as dead. (d) pre-claim — `working`+`turn_pid=None` = launch-in-flight, written under `fleet.lock` before `Popen` and never demoted; the killed-CLI pinned-`working` residual is documented (cleared by respawn). (e) interrupt contradiction resolved — interrupt/kill clear `turn_pid` and commit dead/idle DIRECTLY rather than leaving a stale PID for recompute. Recompute is scoped to `working`+non-None `turn_pid` only; §11 reboot row exempts `attached`. Named regressions in §12. **Cross-ref:** the phase-2-watchtower.md fixed constraint (auto-respawn rules written against §4-as-amended — never raw PID/tail heuristics — and must distinguish crash-dead from operator-kill-dead before keying on `dead`) is owned by `stub-inject-watchtower` (Wave 1B); not edited here.

**F18 = review M2 — §5 command table gains shipped guard semantics (§5 respawn/kill/clean, §12).** The table is the contract build sessions read, so the `--force` ladder is now explicit: respawn refuses a live turn / an `attached` worker without `--force` and a launch-in-flight claim even WITH `--force` (`kill_failed` aborts with no mutation; verified kill via `_interrupt_worker`); log rotation renames the old log only after the old turn is confirmed dead. Kill refuses launch-in-flight, re-probes a `not_running` verdict after 0.5 s (`_DEAD_CONFIRM_DELAY_SECONDS`), marks dead but exits 1 loudly on `kill_failed`. Clean's full artifact sweep includes rotated `.jsonl.1`/`.err.1` logs and orphaned `mailbox/*.claimed.*` files. Named regressions in §12.

**F19 = review M3 — send/respawn lock-ordering, mail after the drain (§5 send/respawn/doctor, §4, §12).** Distinct from this doc's settled F9 (drain-at-respawn-time); this is mail ARRIVING after that drain. The §4 lock guarded only `fleet.json` writes; a send resolved the sid under the lock but appended to the mailbox OUTSIDE it, so a respawn that swapped to sid S2 and removed `mailbox/S1.md` under the lock could race an in-flight send recreating `mailbox/S1.md` — mail no current-sid-keyed drain rule ever touches again, silently lost. Fix: the working/attached-branch mailbox append is serialized w.r.t. the respawn sid-swap (under `fleet.lock`, or re-read registry after append + re-append to the new sid); respawn's drain+sid-swap is atomic w.r.t. send. Doctor's "orphaned mailbox" is now defined — a `mailbox/<sid>.md` whose sid matches no registered worker — with a stated disposition (print sid + first line; operator re-sends or deletes). Named regression in §12. **Cross-ref:** the phase-2-watchtower fixed constraint (auto-respawn goes through `cmd_respawn` under `fleet_lock`) is owned by `stub-inject-watchtower` (Wave 1B).

**F20 = review M4 — PID probe three-way, query-failure direction specified (§4, §5 doctor, §11, §12).** The probe was one PowerShell call interpolating `$p.StartTime` with no try/catch: for a higher-integrity worker probed by an unelevated `fleet status`, `.StartTime` throws `Win32Exception` → empty stdout → a live turn wrongly classified stale → dead (sticky) → a false negative that could Popen a second live claude while the first turn still runs, with `taskkill` access-denied so interrupt can't clean up. Fix: the probe distinguishes alive-and-matching / definitely-gone / **alive-unknown** (exists-but-unreadable, or null/corrupt `turn_pid_ctime`) via a try/catch marker (optional `Get-CimInstance` fallback); alive-unknown is never demoted to dead and never respawn/kill-eligible without `--force`; a missing pid/ctime or query failure counts not-live but retries once after a short delay before any `working`→`dead`; a same-elevation operating rule + doctor check are documented; the accepted residual (a genuinely-crashed but unreadable turn stays `working` until retry or `respawn --force`) is stated. Named regression in §12. **Cross-ref:** the per-OS query-failure modes carried into portability OQ2 (`docs/specs/portability.md`) are owned by `stub-inject-portability` (Wave 1B).
