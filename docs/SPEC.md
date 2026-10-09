# claude-fleet — one Claude Code session managing many

**Status:** v3 — spec of record.
**Owner:** the Fleet maintainers.
**Interpreter floor:** Python 3.10+.
**Platform:** Python 3.10+ on Windows, macOS, and Linux. Platform-specific behavior belongs behind the adapter and requires tests or an explicit unsupported seam.

## 0. How to read this document

Code is the behavioral authority. Function names are durable anchors; pasted line numbers and historical measurements are context only unless an executable receipt explicitly pins them.

### Documentation currency and operator efficiency (2026-09-10)

A surface change is done only when its describing public document changes in
the same commit. Host quirks and project facts go in the fleet home's ignored
`knowledge/projects/<p>.md`, never in the public source tree. No described
behaviour change uses the commit trailer `Docs: n/a -- <why>`.
`tests/test_docs_currency.py` checks the last 20 non-merge
commits after adoption base `117bfa75` for direct `bin/*.py` edits with `docs/` or
that trailer; ancestors are excluded so pre-rule history is not retroactively red.
The same file pins DONE placement on local lane documents and post-cutoff
runtime tasks. `fleet init` creates the ignored
`docs/lanes/BRIEF-TEMPLATE.md`. `fleet land` shells
this module's `__main__` directly, without pytest, as its cheap docs-currency
gate; `__main__` runs the DONE checks too (not only `currency_violations`), so
`land`'s GREEN enforces exactly what the wave floor's pytest pass does -- a lane
report missing its DONE-means line no longer shows GREEN at `land` and only
fails later, after the whole two-interpreter floor (queue item 12, w90).

The supervisor procedure is `skills/fleet/supervisor.md`: last three journal
checkpoints (≤40 lines for new entries), lossless journal history rolls, 40k-token
boot-read cap, one priority item per wave, model routing and spawn token ceilings,
targeted lane checks, one merged floor per interpreter, and current boards plus
one-line changelog and throughput accounting at landing. These are generic procedures; `sup-checkpoint` performs the roll after
every append, and `fleet journal-roll` is available for an explicit pass.

## 1. Problem, decision, architecture

One manager Claude Code session spawns, monitors, steers, and collects results from many worker sessions across arbitrary project directories on this machine, with a persistent knowledge loop and a supervisor identity that survives reboots and context exhaustion.

**The pivot decision (2026-07-13, spec of record: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md`):** Claude Code ships a native background-agent substrate — a per-user daemon, `claude --bg` dispatch, `claude agents --json` roster, `claude stop/logs/attach/rm`. Fleet rebased onto it. The **daemon owns process hosting** (spawn, liveness, attach UX, reap); **fleet owns the semantic layer** (task identity, mailbox steering, token budgets, journal + respawn continuity, outcome capture, archival hygiene, the knowledge loop) and re-implements v2's lifecycle discipline — launch contract, completed-vs-died discrimination, never-demote-unknown, one-live-session-per-name — on the new substrate rather than deleting it. A long-lived **supervisor** (persistent identity in files, disposable session body) sits on top.

```
agents screen (claude agents TUI)                ← the user's window (Anthropic UX)
        │
native daemon (~/.claude/daemon, ~/.claude/jobs) ← process hosting: spawn, attach, reap
        │
worker = claude --bg session                     ← dispatched from project cwd, fleet hooks inside
        │
fleet sidecar (bin/fleet.py + bin/hooks/)        ← semantics: registry, mailbox, ceiling, journal,
        │                                           outcome store, verdict engine, archival, knowledge
supervisor = claim-holding session               ← identity in supervisor/ files, body is any session
```

**Registry keyed by worker name; `session_id` is a mutable per-incarnation field.** Fork-steer and respawn mint new sids (retired ones accumulate in `retired_sids`); a key must survive that, so the sid cannot be the key. Liveness truth = `claude agents --json` roster joined on sid, filtered through the outcome discriminator (§5) — never PID probing (`grep -n "probe_liveness\|turn_pid\|DETACHED_PROCESS" bin/fleet.py` → no matches).

**Sanctioned native interface = the `claude` CLI + `--json` only.** Fleet never reads or writes `~/.claude/daemon/` or `~/.claude/jobs/`. Never raw pid kills: the daemon auto-respawns a `taskkill`-ed session under a new pid (contract G10) — `claude stop <id>` only.

## 2. The substrate contract (pointer, not duplicate)

`docs/specs/native-substrate.md` is the **G-row contract**: the 13 gate verdicts (G1–G13), the dispatch argv, the closed 8–9-key roster schema (field presence is state-dependent) with its field-presence-per-state table, the dispatch-grace startup transient, the result/cost contract (Stop-hook payload + transcript tail; **no USD figure exists anywhere** — G3), the steering contract (fork-with-transcript, G2(b) RATIFIED), and the known hazards (stdin wedge, silent limit walls, `ai-title` name mutation, stop-fires-no-Stop-hook). v3 references it and does not restate it. Everything there was observed at `claude` 2.1.207; the pin-test tier (§17) re-verifies on version change, and `fleet doctor` warns when `claude --version` has moved since the last recorded pin pass (`_doctor_check_pin_version` @5078, `record_pin_pass` @114).

## 3. Repo layout (as it exists today)

```
C:\projects\claude-fleet\
  bin\
    fleet.py                 # single-file CLI, Python >=3.10, stdlib only (23100 lines @ 708fa45; §0)
    fleet_statusline.py      # statusline renderer (imports fleet.py; read-only view)
    fleet.cmd / fleet        # PATH shims (cmd.exe + POSIX sh)
    hooks\
      posttooluse_mailbox.py # mid-turn mailbox injection
      stop_mailbox.py        # turn-end mailbox drain / stop-block
      stop_outcome.py        # Stop-hook terminal-outcome record (M-B; §8)
      postcompact_journal.py # compaction marker → worker journal
      run_py.sh              # interpreter resolver for non-Windows shells
  worker-settings.template.json  # git-tracked hook-wiring template; `fleet init` renders it
  .claude-plugin\plugin.json # plugin `fleet` (commands + skill only; NO hooks, NO statusline)
  commands\                  # /fleet:* slash commands (read-only inline; mutating = prompt templates)
  skills\fleet\SKILL.md      # manager skill
  supervisor\                # ignored per-home goals, journal, briefs, claim and handoff state
  knowledge\                 # tracked generic INDEX/playbooks; ignored per-home projects/lessons
  state\                     # gitignored
    fleet.json / fleet.lock  # registry (single writer: fleet.py) + atomic-rename lock
    events.jsonl             # append-only lifecycle events, fleet.py ONLY
    worker-settings.json     # rendered machine-local instance passed via --settings
    outcomes\<key>.jsonl     # terminal-outcome store (§8); key = name, sid fallback
    tasks\<name>.md          # task-file bootstrap bodies (§6)
    ceilings\<sid>          # token-ceiling files the Stop hook reads (extensionless; ceiling_file_path @86)
    journals\<name>.md       # worker journals
    hook-errors.log          # append-only swallowed-hook-exception log (§8 boundary item (b))
    pin-pass.json            # last pin-suite pass stamp (record_pin_pass @114; doctor pin_version)
    mail-receipts\<id>.json  # authenticated Interface direction; read by `mail verify`
    supervisor-handoff-aborted.json  # doctor-visible handoff-abort flag (§12)
    autoclean-last-run.json  # autoclean run stamp
  logs\                      # gitignored; logs\archive\<name>\ = archived evidence (§11)
  mailbox\                   # gitignored; <sid>.md pending messages
  docs\SPEC.md               # this tracked generic specification
  docs\lanes\                # ignored per-home lane reports and structured results
```

**Public-source boundary.** Every tracked file is generic product, design,
implementation, test, or template material. Operator data is local to a fleet
home: `supervisor/`, `state/`, `logs/`, `mailbox/`, `docs/lanes/`,
`knowledge/projects/`, and `local operator lessons` are ignored. `fleet init`
creates the stable local paths from generic seeds and never replaces existing
operator-owned content. Existing homes therefore keep the same paths while a
fresh public clone contains no campaign, identity, project, or operator record.

Receipt: path helpers `state_dir/mail_receipts_dir/logs_dir/mailbox_dir/journals_dir/ceilings_dir/outcomes_dir/tasks_dir/archive_root/pin_pass_path` in `bin/fleet.py`. There is **no per-worker `logs/<name>.jsonl` stdout pipeline** — that died with §6 of the pivot spec (the mc-delete wave, −7130 lines).

## 4. Registry schema (`state\fleet.json`) — as it is today

`new_worker_record` (@591-655) is the schema authority:

```json
{
  "workers": {
    "mc-spec": {
      "session_id": "uuid | null while dispatch is in flight",
      "cwd": "C:\\projects\\fleet-mc-spec",
      "branch": "the branch the lane was dispatched on, or null (non-git cwd, detached HEAD, pre-item-16 record)",
      "task": "first 200 chars of the original task",
      "mode": "bypass | accept | dontask | plan | omit",
      "model": null,
      "max_budget_usd": null,
      "setting_sources": null,
      "token_ceiling": null,
      "spawned_by": "CLAUDE_CODE_SESSION_ID of the spawner, or null (human shell)",
      "spawned_by_lineage": "the spawning claim's lineage_id, or null (claim-nonce §6.2)",
      "created": "ISO-8601 UTC",
      "status": "working | idle | attached | dead | dead-suspected | limited | over_budget | over_ceiling | interrupted",
      "attached_since": null,
      "limit_reset_at": null,
      "limit_kind": null,
      "turns": 0,
      "cost_usd": 0.0,
      "cost_baseline": 0.0,
      "last_activity": "ISO-8601 UTC",
      "dispatch_kind": "bg",
      "category": null,
      "substrate": "claude | codex | openrouter/<slug> | null (falls back to dispatch_kind==\"bg\" => claude)",
      "native_short_id": "short id from --bg stdout, or null",
      "last_dispatch_at": "ISO-8601 UTC; restamped at every dispatch/steer/resume",
      "retired_sids": [],
      "archived_at": null
    }
  }
}
```

- **Native discriminator:** `is_native(record)` ⇔ `dispatch_kind == "bg"` (@146). Every worker dispatched today is native. The deleted PID fields (`turn_pid`, `turn_pid_ctime`, `turn_pid_boot_id`) no longer exist in the schema; **tolerate-and-ignore**: a pre-pivot record carrying them loads fine (readers `.get()` what they need, `save_registry` round-trips unknown keys) and they decide nothing.
- **Additive-schema rule (carried from v2.1 M1, still binding):** fields are added, never renamed/removed; readers default missing fields; the single writer preserves unknown fields on round-trip. No migration step, no format-version gate.
- **Single-writer discipline:** only `fleet.py` writes `fleet.json`, under `state\fleet.lock` (`fleet_lock` @402 — atomic-create lock, 5 s timeout). After 30 s, a stale lock can be taken over only when its recorded owner is dead or its PID start identity differs; an ambiguous live owner keeps the lock until it releases or an operator reviews it. On POSIX, the owner holds a kernel lock on the lock-file inode through its registry transaction; a stale breaker must lock and recheck that same inode before unlinking, so two breakers cannot unlink a successor's lock. A present symlink, directory, or other non-regular lock path refuses without removal; a genuinely vanished path retries only within the monotonic deadline. A pre-install CLI writer without this kernel protocol must be absent during a protected whole-registry transaction. The journal-only `codex-settle-preaccept` operation never writes `fleet.json`; it requires positive continuous exclusion only of an old or new command capable of writing its exact target row or operation journal through postcheck. Unrelated CLI activity may progress when it cannot write that target; a clear process snapshot alone does not establish the exclusion. A JSON-unparseable registry is **quarantined** aside (`_quarantine_registry` @510 → `fleet.json.corrupt.<ts>`), a `registry_corrupt` event appended, exit 1 loud — never silently reset to empty.
- **Names:** human-chosen, `[a-z0-9-]+` (`NAME_RE` @472), and **never uuid-shaped** (`_SID_SHAPE_RE` @478, autoclean F6: a name-keyed archive filename must not be able to impersonate a session id).
- **Spawn-immutable fields:** `mode`/`cwd`/`model`/`setting_sources`/`token_ceiling`/`spawned_by`/`spawned_by_lineage` are recorded at spawn and re-passed by every later launch path (steer, resume-limited, respawn carry-forward). `spawned_by_lineage` (claim-nonce §6.2) is the spawning supervisor claim's `lineage_id`; a later body of that lineage that proves continuity owns the workers it spawned even after a sid rotation, and a seize (which re-mints the lineage) deliberately breaks that. `max_budget_usd` survives in the schema for legacy tolerance but is **refused at dispatch time** under native (G3, §9).
- **Cost fields (`cost_usd`/`cost_baseline`) are legacy-tolerated, not native-fed:** no sanctioned native source carries a dollar figure (contract: USD REFUTED-for-contract), so native accounting is **token-based** — `_native_cumulative_tokens` (@1060) sums `input+output` tokens across the worker's outcome records for the ceiling check, and `status` renders a token summary (`_native_token_summary` @2519).
- **Archived tombstones:** `archived_at` set ⇒ frozen history — hidden from default `status`, never recomputed, refused by every mutating verb via `refuse_if_archived` (@152); only `fleet clean` may delete it.

## 5. The verdict engine (replaces PID liveness)

`recompute_worker_native` (@1379) derives status for a native record from **one roster fetch + the outcome store**, in a binding order:

1. **Sticky statuses pass through:** `_NATIVE_STICKY = ("dead", "over_budget", "over_ceiling", "limited", "interrupted", "attached")` (@1310). `dead-suspected` is deliberately **not** sticky — it is a verdict, not a state, re-evaluated every recompute so a late-arriving outcome record can flip it back to idle.
2. **`session_id is None` = dispatch in flight:** stays `working` while the pre-claim is younger than `LAUNCH_CLAIM_MAX_AGE_SECONDS` (600 s, @778), aged on **`last_activity`** (@1424 — not `last_dispatch_at`, which anchors only the grace/fresh-outcome checks below); older demotes to `dead` (the launcher died between pre-claim and stamp).
3. **Roster entry present and live** — live ⇔ the entry carries `status` or `pid` keys (`state` alone is never live; contract field-presence table): roster `busy`/`waiting` → `working` (`waiting` additionally flags `waiting_for_permission`); roster `idle` → **fresh-outcome check**: `has_fresh_outcome(name, sid, since=last_dispatch_at)` (@5803) → `idle`, else → investigate.
4. **Roster entry dead (state-only) or roster-gone:** same fresh-outcome check → `idle`, else → investigate.

**The fresh-outcome predicate is sid- AND timestamp-filtered** — anchored on `last_dispatch_at` (fallback `created`), never on mere record presence: a dead predecessor's outcome, or this worker's own previous turn's outcome, must not vouch for the current turn.

**The no-outcome investigation** (`_investigate_no_outcome` @1344), shared by both no-outcome paths:
1. **Limit scan first (usage-limit continuity, §10):** `transcript_limit_scan` over the transcript tail; limit-shaped → park `limited` with parsed `limit_reset_at`/`limit_kind`.
2. **Dispatch grace window:** `_dispatch_grace_active` (@1314) — a freshly dispatched `--bg` session's roster entry is state-only (`{'state':'working'}`, no `status`/`pid`) for its first seconds, indistinguishable from dead by field presence (live pin-suite finding 2026-07-16); within the window (same 600 s constant, anchored on `last_dispatch_at`) the verdict holds at `working`.
3. Else **`dead-suspected`** — surfaced, advisory, **never auto-respawned** (never-demote-unknown carried to the new substrate; respawn is non-idempotent). Nothing starts on its own: the verdict never triggers a launch. An explicit `respawn` may accept such a row without `--force` when its transcript tail is an API stream death (§11.4, queue item 31), and still stops the old session first.

**G9 epoch-freeze discipline:** `native_epoch_suspicious` (@1448) — the roster fetch failed, OR came back empty while some native record's last-committed status is `working` with a real sid (a daemon restart must never read as "everything died"). While true, **no native record is recomputed or written**: `status`/`wait`/`clean` skip verdicts that pass, `send`/`respawn` refuse outright. The supervisor boot ritual runs the same check first (`supervisor_epoch_check` @6548).

**Lock shape (F4 doctrine, everywhere):** snapshot under one `fleet.lock`, release, do the roster fetch + every recompute with **no lock held**, re-acquire once to merge — and merge only records that still equal their pre-fetch snapshot (a concurrent mutation wins over a verdict computed against stale data). No lock is ever held across a subprocess.

## 6. Dispatch contract (`dispatch_bg` @6167)

Every native **worker** launch — spawn, fork-steer, resume-limited, respawn — funnels through one choke point. It is not the only `--bg` launch in the codebase: there are exactly **two** argv builders, and the second (the supervisor handoff successor, `cmd_sup_handoff_begin`, §12) is specified at the end of this section.

```
claude --bg [--resume <old-sid>] -n "<cat>|<name>|<hint>" --settings state/worker-settings.json
       --add-dir <FLEET_HOME>/state/tasks [--setting-sources <s>] <mode flags> [--model m]
       "Read <FLEET_HOME>/state/tasks/<name>.md and follow it exactly."
```

- **Task-file bootstrap (G8):** the composed prompt body (preamble + task + drained mailbox + journal) is written to `state/tasks/<name>.md`; argv carries only the tiny fixed prompt. Argv >32,767 chars fails at CreateProcess; stdin wedges the session (contract hazard) — neither is ever used.
- **Headless-worker preamble:** every composed worker prompt forbids `AskUserQuestion` and interactive waits; a decision is recorded in the journal or the worker ends with the question in its result. A roster permission stall whose `waitingFor` names `AskUserQuestion` is diagnosed explicitly as this deadlock, with interrupt/respawn recovery.
- **The brief store (`state/briefs/<name>.md`), wave 35 — and why `state/tasks/<name>.md` is NOT it.** That write is **unconditional and per dispatch**, so the task file is the LAST DISPATCH'S PAYLOAD, never a durable record of what the worker was asked to do. It was doing both jobs and the conflict was measured three times before it was fixed: `respawn` recomposed from the registry's capped `task` snapshot and left two lanes' briefs at 784/783 bytes cut mid-sentence (2026-07-31, byte-exactly reconstructed; the same defect was root-caused on 2026-07-23 and never built); `send`'s fork-steer and `resume-limited` compose with an empty task (F6 — the message rides the mailbox) and replaced briefs with a preamble plus a mail block; `archive` then filed that stub as the worker's `task.md`. The brief is now recorded once, by the paths where the task text is **authoritative** — `spawn`, `sup-spawn`, and an explicit `--task` override — and read back by `respawn`/`respawn supervisor`. It lives **outside `tasks_dir()`** deliberately: `--add-dir tasks_dir()` pre-authorizes every task file for every worker, and a brief is a dispatch input. **The narrow claim is the true one** — this removes the brief from the granted set, it does not make it unreachable: `bypass` is `--dangerously-skip-permissions` and is `SUP_SPAWN_DEFAULT_MODE`, so under the fleet's own default mode nothing inside FLEET_HOME is protected by anything. The gain is bounded and real: under `accept`/`dontask`/`plan` a stray write to another worker's brief meets a prompt instead of an open door. Swept by `clean`, moved by `archive` as `brief.md`.
- **The registry `task` field stays capped at 200 chars and is PROVENANCE, never a dispatch input** (`new_worker_record`). Raising the cap was the obvious fix and is the wrong one: it fixes `respawn` alone, leaves the steer paths and the archive copy, and puts a full copy of every brief on the hot read path of every view and the statusline. A pre-brief-store worker recovers its brief once, by exact-prefix arithmetic against its own payload; anything that does not match byte-for-byte **refuses** and names `--task @<path>` — a truncated brief fails loudly, it does not dispatch silently.
- **`--add-dir` pre-authorizes exactly `tasks_dir()`** (least privilege): the task file lives outside the worker's cwd, and under any non-bypass mode the first Read would otherwise hang forever on an unapprovable headless permission prompt.
- **Name guard at the choke point:** rejects non-`NAME_RE` and uuid-shaped names (F6) even from a future direct caller.
- **Settings are the rendered instance** (`state/worker-settings.json`), never the template; a missing instance hard-fails before any mutation (`_require_instance_settings` @1736) — never a hookless worker looking healthy in the roster.
- **Rendered name = `<category>|<name>|<hint>`** (`render_native_name` @6067; `DEFAULT_CATEGORY = "fleet"`, hint clamped to 40). Display-only: the roster join is by sid, never by name (`ai-title` can mutate a forked session's name — contract hazard).
- **Short-id join (G6 fallback — `--session-id` does not compose with `--bg`):** parse the short id from `--bg` stdout after **ANSI-stripping** it (`_ANSI_ESCAPE_RE` @6049, applied @6077 — the daemon's stdout can carry escapes), then join to the full sid via roster polling (`_join_roster_by_short_id` @6089, 60 s window, 3 s poll), **excluding every sid captured in a pre-dispatch roster snapshot** so a foreign session sharing the prefix can never be adopted. No join within the window ⇒ `NativeDispatchError` carrying the short id (the operator's only recovery handle; also `add_note`-ed onto any exception escaping mid-join).
- **Attach-verify (`_await_attach` @6114, 30 s window):** a joined roster entry is not a started session — rarely the daemon mints the entry and never attaches the runner (the never-attach wedge, live finding 2026-07-16). Life signals, any of: entry gains `status`/`pid`; entry reached a terminal/blocked state literal (it RAN — the discriminator owns the verdict); entry vanished post-join (reaped, not wedge-shaped); an outcome record for the sid exists (fast completion). **H1:** a full-window roster blackout (zero successful fetches) is CANNOT-VERIFY, never a wedge verdict — raises loudly and touches nothing, because a wedge verdict licenses stop/rm and must never be issued against a session never once observed.
- **Single safe wedge-retry (C1):** on a wedge verdict, `claude stop` + `claude rm` the wedged session with short timeouts, then **verify** the cleanup (re-fetch; entry gone or still status/pid-free = retry-safe; entry live or roster unavailable = **refuse the retry** — two live sessions on one task file is the disaster case). Retry the whole dispatch exactly once with a fresh pre-snapshot; a second consecutive wedge gives up loudly. Events: `dispatch_wedged`, `dispatch_retried`.

### 6.2 Codex launch settings

New `codex:<model>` lanes use the native app-server adapter by default and
persist `dispatch_kind=codex-app-server`. Explicit `--codex-adapter mcx`
selects the compatibility adapter and persists `dispatch_kind=mcx`; that
record-local discriminator, not the current default, routes every later verb.
Mixed rows fail closed without calling either adapter. On explicit mcx launches,
Fleet maps the worker's permission mode to mcx's approval/sandbox mode:

| Fleet `--mode` | mcx `MCX_APPROVAL` |
|---|---|
| `bypass` | `unrestricted` |
| `accept` | `auto` |
| `dontask`, `plan`, `omit` | `never` |

The mapped value is written as `mcx_approval` on the registry row and wins over an
inherited `MCX_APPROVAL` environment variable; a caller cannot weaken Fleet's
selected restriction. `--effort` is passed as mcx `-r` and persisted as
`mcx_effort` (default `medium`). Respawn and steer reuse both persisted values;
before a steer, Fleet verifies mcx's saved `approval` and `effort` files still
match the row and refuses on drift, because mcx reloads those files for the
restarted run. `fleet status` and `fleet peek` show the approval mode so a
sandboxed lane is visible. Legacy rows without these fields derive approval
from their saved Fleet mode and use medium effort.

**Launch contract around the choke point (spawn shape, `cmd_spawn` @2128):** pre-claim the record under `fleet.lock` with `session_id=None` + `last_dispatch_at` stamped → dispatch outside the lock → re-lock and stamp sid/short-id via `_commit_launched_turn` (@1769: 6 attempts, backoff — a lock timeout must not strand a live session; on exhaustion `_report_stranded_native_turn` prints the recovery handles and the pre-claim is **kept**, never popped, because a live session exists) → on dispatch failure, roll the pre-claim back. **Fast-completion exception:** a worker can finish before the join resolves; if an outcome record for this name is newer than the pre-claim, commit `idle` with the outcome's sid instead of rolling back a finished task (`_fast_completion_sid` @5927).

### 6.1 The second dispatch path — supervisor successor (`cmd_sup_handoff_begin`)

> **Pin:** this subsection and §11's scheduler-bridge bullet are descriptive of `bin/fleet.py` on branch `me/defects`, **not** of §0's global `c63d7dd` pin — at `c63d7dd` the successor argv was `[exe, "--bg", "-n", name]` with neither `--settings` nor `env=`, and ownership was path-only. §0's global pin is deliberately left where it is: moving it would implicitly re-assert every other unverified claim in this document at a newer commit. Anchors here are **function names, not line numbers** — the `@7280` this heading first carried was invalidated 74 lines later by this branch's own second commit.

The supervisor handoff dispatches its successor with its own argv. This is **sanctioned and enumerated**, not a bypass — three properties of the choke point are wrong for a handoff:

- **The name guard refuses it.** `NAME_RE` is `^[a-z0-9-]+$`; an incarnation id is `inc-<YYYYMMDD>T<HHMMSS>Z-<hex4>`, whose `T`/`Z` are uppercase. `dispatch_bg(name=<inc>)` raises before dispatching.
- **The task file already exists elsewhere.** The successor bootstrap is written to `state/supervisor-handoff-<inc>.md` and journaled **by path** in the HANDOFF-BEGIN entry; `task_file_path(name)` would create a second one and orphan the journaled reference.
- **The wedge-retry is the wrong remedy.** One re-dispatch of a worker is safe; one re-dispatch of a successor is two live sessions on one incarnation id — the double-spawn hazard §12/§4 exists to prevent.

What the second path therefore **must** carry, and does:

```
claude --bg -n "sup|<inc>|successor" --settings state/worker-settings.json
       --model m [--setting-sources s]
       <mode_flags(--permission-mode | inherited predecessor mode)>
       "Read <FLEET_HOME>/state/supervisor-handoff-<inc>.md and follow it exactly."
       cwd=<FLEET_HOME>  env=_worker_env("sup|<inc>|successor")
```

- **`--settings` (the rendered instance), pre-flighted by `_require_instance_settings`** before the lock, so a refusal writes neither the journal entry nor the task file. **Two claims that stood here are corrected, 2026-07-28** — both were already false when written and the stillborn-handoff incident is what they cost.

**(1) "A successor has no `state/fleet.json` record."** It has one. Seam #2 (`e9531ed`) files a supervisor-shaped body record on the success path, ~60 lines below the sid stamp, and `fleet archive` has since reaped four successors by name. Anything reasoning from "a successor has no record" is reasoning from a premise this spec's own §6.1 removed.

**(2) "All four hooks degrade cleanly to sid-keyed writes … verified empirically."** The degradation is real; **"cleanly" is not.** That fallback *is* defect B. `stop_outcome.py::_resolve_name` scans the registry for `session_id == sid`; with the record's `session_id` null it misses, keys on the raw sid, and files the turn's outcome at `state/outcomes/<raw-sid>.jsonl`. `read_outcomes(name, sid=sid)` would open exactly that path — but its callers take `sid` off the same null record, so the fallback was starved by the same missing field that created the need for it. Ten stillborn successors each stated their own diagnosis into a file nothing on the fleet side could read, for three days. The empirical verification was sound and measured the wrong thing: **rc=0 with an empty `hook-errors.log` is evidence that nothing crashed, not evidence that anything was readable.** A hook that silently writes to a path no reader opens is the exact failure mode a no-errors check cannot see.

Since 2026-07-27 the record carries the sid at dispatch, so `_resolve_name` hits and the sid-keyed arm is a genuine fallback rather than the normal path. Pinned end to end through the real hook in a real subprocess by `tests/test_stillborn_handoff.py::…::test_the_stop_hook_files_the_successors_outcome_where_the_fleet_reads_it`, which asserts the FILE and the READ, not the field. The successor's sid is also the handle `sup-handoff-complete --expect-sid` / `sup-handoff-abort --successor-sid` print and consume, so those files are addressable.
- **`resolve_claude_executable` is pre-flighted before the lock too**, beside its twin. It is the same class of check — a missing external prerequisite — and while it ran *after* the journal write, a `claude` that had dropped off PATH left HANDOFF-BEGIN journaled with no successor, a stale task file, the previous abort flag deleted, and **no** abort flag raised, contradicting this verb's promise that both failure paths raise it. Hoisting one pre-flight and leaving its twin is this repo's named recurring class.
- **Mode flags ARE carried, in one vocabulary.** `--permission-mode` takes a **fleet mode name** (argparse-constrained to `MODE_FLAGS`, the keyspace `fleet spawn --mode` uses); when omitted, it inherits the validated predecessor row. If that setting cannot be read, the handoff refuses rather than silently selecting `SUCCESSOR_DEFAULT_MODE`/`bypass`; explicit mode, model and setting-source flags override their corresponding inherited values. A missing, empty, or null predecessor model is unresolved because it cannot identify the provider model that actually ran; the handoff then requires `--model` explicitly. Both branches render through `mode_flags()`, so exactly one mode opinion reaches argv and a raw Claude spelling is refused at the parser. The successor row records the effective launched model (never `None`) and substrate/provider.
- **Supervisor launch-settings contract (receipt).** Gen-0 `sup-spawn` and successor `sup-handoff-begin` carry exactly `model`, `mode` (permission mode), and `setting_sources`, whether inherited or explicit. They have no supervisor `effort` field or flag; `--effort` remains worker/mcx-only in §6.2 and is never persisted on supervisor rows. The parser and row-shape exclusion are pinned by `tests/test_supervisor.py::TestHandoff::test_supervisor_launch_contract_has_no_effort`. Handoff inheritance resolves the predecessor from exactly one supervisor holder row matching the claim sid; `sup-handoff-begin` refuses, dispatching nothing, when several rows match or the match is not a supervisor body. Pinned by `tests/test_stillborn_handoff.py::TestHandoffPredecessorIdentityFailsClosed`.
- Native Codex handoff applies the same fail-closed rule: a missing predecessor `mode` or `setting_sources` field is unresolved and refuses unless the corresponding flag is supplied explicitly.
- **`env=_worker_env(name)`** — §5.1 provenance. `cmd_sup_boot` derives `caller_sid` from `CLAUDE_CODE_SESSION_ID` and writes it into the HANDSHAKE; an inherited value from the outgoing holder would make the successor hand back the **predecessor's** sid, and `sup-handoff-complete`'s §4 dual verification would then refuse forever. `[UNVERIFIED — whether the daemon propagates the launcher's environment into the hosted session is unobserved; the strip is defense-in-depth and costs nothing if the daemon already isolates. `dispatch_bg` applies it at every worker launch on the same reasoning.]`
- **`_worker_env` also stamps `FLEET_WORKER`, and that is intended** (ruling, this wave). *(2026-07-22: the SessionStart hook this ruling was written against is gone — terminal-surface D7 — so no briefing suppression is involved any more. The stamp stays, and the constraint below is unchanged. The original reasoning is kept because it is why the successor gets a boot bundle rather than a briefing. 2026-07-27, operator gate: the earlier claim that it is "load-bearing for the supervisor and destructive-command guards" was false of both halves and is restated here. It is load-bearing at exactly two sites, in opposite directions — its **absence** structurally exempts the human interface from the §11.3 dispatch ceiling (`_ceiling_refuses_dispatch`), and its **presence** with a non-supervisor-shaped value refuses the supervisor claim (§6.5), a self-declared speed-bump rather than a boundary. It is **not** load-bearing for the destructive-command guard, which keys on the caller sid and ownership — `tests/test_destructive_guard.py::TestAWorkerIsNotExempt` pins that a worker is not exempt. Per the ratified identity clause, only the absence arm is sound evidence.)* The SessionStart hook read it and suppressed the fleet briefing, so a successor started without one. That was correct: the successor's briefing is the **boot bundle** its bootstrap fetches from `sup-boot`, which is claim-aware, and §4 forbids it any action before claim transfer — a manager briefing arriving *before* it holds the claim invites exactly the actions §4 bans. **Constraint this creates, recorded so the next builder does not trip on it:** `FLEET_WORKER` here means "not the manager session", **not** "is a registry worker". A future guard enforcing *a worker turn must never hold the supervisor claim* must key on the registry or the claim itself, never on `FLEET_WORKER`, or it will refuse the one session whose whole purpose is to receive the claim.
- **No `--add-dir`** (cwd is `FLEET_HOME`; the task file is already inside it). `--setting-sources` inherits the validated predecessor unless explicitly supplied; an unresolved source setting refuses the handoff. Everything else — short-id join, pre-snapshot exclusion, G6 name-join fallback — is shared logic, called directly.
- **~~Known litter~~ — retired 2026-07-28, its premise was the one corrected above.** This read: *"each successor leaves `state/outcomes/<sid>.jsonl` and, on compaction, `state/journals/<sid>.md`; both `fleet archive` and `fleet clean` enumerate from registry records, and a successor has none, so these accumulate one pair per handoff … not reapable without giving the successor a registry identity."* The successor **has** a registry identity (Seam #2), and `fleet archive` has reaped four successors by name. The sid-keyed pair was never inherent litter — it was defect B's output, produced because the record's `session_id` was null; with the sid stamped at dispatch the hooks resolve the name and write name-keyed files the sweeps already enumerate. Historical `<raw-sid>` pairs from the incident window remain on disk and are owned by no sweep. `[UNBUILT — a one-off cleanup of the pre-2026-07-27 orphans]`

Pinned by `TestDispatchPathsAreDocumented` (`tests/test_supervisor.py`): the builder-count guard matches `"--bg"` inside **any** same-line list literal and additionally asserts both hits sit in `dispatch_bg` and `cmd_sup_handoff_begin`, so a third builder under any name — or one that *replaces* an existing builder, keeping the count at two — goes RED. The subsection pins assert against **§6.1 alone**, not §6 through §7, and require the tokens that carry its load; an earlier revision claimed protection it did not have, because §6's own lead sentence already contained the strings the test looked for and deleting §6.1 wholesale left it green.

## 7. Lifecycle verbs — native wrappers over roster + outcome store

| Verb | Native behavior (receipt) |
|---|---|
| `spawn <name> --dir --task [--mode dontask] [--model] [--effort medium] [--codex-adapter native\|mcx] [--category] [--token-ceiling] [--setting-sources]` | §6 launch contract. `--max-budget-usd` **refused** (G3: no USD under `--bg`); `--token-ceiling` is the only fleet-side cap. Ceiling file written after the sid is known (@2320). Default mode `dontask` (@7153); mode map `MODE_FLAGS` @949. Codex `--model codex:<model>` defaults to the native app-server adapter and accepts `--effort low|medium|high|xhigh`; explicit mcx persists its selected effort and approval on that row. |
| `send <name> <text\|@file>` | `_cmd_send_native` @2928. Working (roster busy/waiting) → mailbox append, unchanged mid-turn path (G1). An ordinary idle worker → **fork-steer** (RATIFIED G2(b)): ceiling check via summed outcome tokens, pre-claim, mailbox append rides the drain, `dispatch_bg(resume_sid=old_sid)` mints a NEW sid; `_restamp_after_steer` retires the old sid, restamps sid/short-id, and `_migrate_residual_mailbox` re-points late mail. An idle supervisor holder instead wakes unforked with a fresh wake nonce, resumes the same incarnation, and its fixed bootstrap aborts every pending handoff successor before campaign work. Refuses: dead-suspected, dead/interrupted (→ respawn), limited (→ resume-limited), other sticky states, and any G9-suspicious roster. Rollback restores the mailbox claim and the pre-claim **only if** the record still matches the claim this call wrote. |
| `mail verify <id>` | File-only Interface-mail verification. Reads one atomic `state/mail-receipts/<id>.json`, checks its body digest and source against the current Interface registration, and prints the canonical body only after `VERIFIED`; missing, malformed, forged, or superseded evidence prints `UNVERIFIED` and exits 1. It takes no `fleet.lock`, probes nothing live, writes nothing, and never trusts mailbox content as provenance. |
| `status [name] [--json] [--stale-ok] [--all]` | `cmd_status` @2355. Authoritative path: F4 lock shape, one roster fetch, recompute + conditional merge, table + anomaly flags. `--stale-ok` = the probe-free/lock-free/write-free view path (`status_snapshot` @1558). Archived records hidden by default (`--all` or a named query includes them) and **never recomputed**. Epoch-frozen ⇒ verdicts carried, not derived. |
| `pr-poll <PR> (--since SHA\|--since-file PATH) [--repo OWNER/REPO] [--json]` | Read-only GitHub PR head check through one bounded `gh pr view --json headRefOid` call. Reports whether the head differs from the recorded SHA; never persists the SHA or writes fleet state. See `commands/pr-poll.md`. |
| `peek <name> [-n]` | `_cmd_peek_native` @2607: last n substantive transcript records (assistant text/tool_use, user vs `isMeta`), tolerant parsing, works mid-turn (daemon writes the transcript live). No stream-json log exists to read. |
| `result <name>` | `_cmd_result_native` @2662: latest outcome record for the CURRENT sid; `kind=="result"` prints `result_text` on stdout (script-pure) + token/model line on stderr; a tombstone kind or missing/null record exits 1 with a distinct reason. |
| `address <name>` | `cmd_address`: read-only join of the registry sid to one live `claude agents --json --all` row; prints the exact native `name` for a `SendMessage` `to`. Refuses a sid with no process and refuses when several live sessions (pid present, live status) share the name (non-zero exit; `--json` carries `error` and each duplicate's pid and sid); warns on a live retired sid. See `docs/specs/peer-messaging.md`. |
| `wait <name...> [--any\|--all] [--timeout]` | `wait_for_workers` @2711: poll-recompute until `NATIVE_TERMINAL_STATUSES` (@1305: idle, dead, dead-suspected, limited, over_ceiling, interrupted). One roster fetch per poll shared across names; epoch-frozen polls trust nothing; archived records resolve immediately from frozen status. |
| `attach <name>` / `release <name>` | `cmd_attach` @3579 **refuses and redirects**: a native session has no fleet-owned terminal — use the agents menu (Ctrl+T) or `claude attach <sid>` (M-B scope fence; native attach integration is a later milestone). `release` @3595 still flips a stale `attached` record → idle. |
| `interrupt <name>` | `_cmd_interrupt_native` @3462: guard — only `status=="working"` is interruptible (T8 C1: nothing else is ever overwritten). Non-working branches (@3520-3546): `dead`/`interrupted`/`idle` → friendly "nothing to interrupt" no-op, rc 0; `limited` (would orphan the resume path), `dead-suspected` (inspect first), dispatch-in-flight, and any other status → refuse, rc 1. `claude stop <sid>` (never raw kill), write fleet's own `interrupted` tombstone (G10: stop fires no Stop hook), mark sticky `interrupted`. Respawn is a separate, explicit decision — an interrupted task is definitionally started; auto-respawn would re-run side effects. |
| `respawn <name> [--task]` | `_cmd_respawn_native` @3620: **fresh dispatch, no `--resume`** — the context reset is the point; journal + old-sid mailbox carried via `compose_prompt(journal_path=...)`. **The task text comes from the brief store (§7), not from the registry snapshot** (wave 35 — it used to come from `task[:200]`, which is what ate two lanes' briefs); `--task` replaces the recorded brief, a bare respawn reuses it, and an unrecoverable remnant is refused rather than dispatched. Old-sid liveness gated on the **roster**, not the stored label; roster-fetch failure refuses (never assume dead on ambiguity). **One disagreement between the two liveness verdicts is resolved by evidence, not by `--force`** (queue item 31): a stream death (`API Error: stream closed before completion` and the measured family around it) leaves the session process resident with no outcome record, so the roster still reports a live body while the status probe concludes `dead-suspected`. When the probe's verdict IS `dead-suspected` **and** the transcript tail's newest qualifying record is an API stream death (`transcript_stream_death_scan`), respawn accepts the row without `--force` — announcing the acceptance on stderr — and **still stops and tombstones the old session**, because the flag was never the safety property; the stop is. A genuinely running turn keeps the refusal: a roster `busy`/`waiting` entry (the probe then says `working`), a `limited` tail (429 is its own verdict with its own verb), no transcript evidence at all, or a tail whose newest record is chatter after an older death. `--force` on a live old session: stop → **always re-verify via roster** (reported success gets one 2 s grace re-fetch; reported failure aborts on first still-live check) → still-live aborts the respawn (never two live sessions under one name). Stopped tombstone written regardless of the stop's exit code. Carries forward cwd/mode/model/category/setting_sources/token_ceiling/spawned_by/cost fields; `retired_sids` += old sid. **An interrupted supervisor holder is the exception:** it cannot receive the release steer, so respawn wakes a fresh unforked turn under the same claim/incarnation and proves continuity with the wake nonce; an interrupted-holder `--task` override is refused because the same-incarnation wake payload cannot replace the campaign brief. No log rotation — there is no log. |
| `kill <name> [--yes]` / `clean [--dead-only\|--tombstones]` | `_cmd_kill_native` @3891: `claude stop` current sid + best-effort sweep of `retired_sids` (cap 20 most recent, 5 s each — T8 I1 wall-time bound; skips any sid that is another worker's current sid), tombstone, mark dead unconditionally; unverified stop still marks dead but exits 1 loudly. `cmd_clean` @4083: deletable = `dead` ONLY (never dead-suspected/limited/idle/interrupted/working); F4 lock shape + epoch freeze; archived tombstones are always swept (pure file deletion — their sids were already `claude rm`-ed at archive time); tiering flags per `docs/specs/autoclean.md` D2. A native Codex row is killed through its exact-home host (a gone host, dead host pid or other host generation proves that incarnation gone only while the row is unchanged and no recovery is pending; a live host gets one `turn/interrupt` and must then prove the exact turn terminal). An expired preclaim with no thread binding remains cleanable. An expired bound row with no recorded turn is cleanable only after an exact `thread/read` proves an idle thread with zero turns; any provider turn means a post-accept crash may have lost the registry commit, so kill refuses rather than permit duplicate execution. Kill conflicts with a pending `thread/resume` and revalidates the row at its terminal write, so it never reports success across concurrent reattachment. Lost or ambiguous interruption remains durably reserved and `dead-suspected`, never a successful tombstone or blind retry. Clean confirms ownership before moving evidence, then archives sid-keyed evidence by `_archive_evidence_sid` (the Codex `codex_thread_id` when `session_id` is null), rescans mail immediately before deletion, and rolls back partial moves into one stable `logs/archive/<name>/` destination; rows with no evidence key remain safe to remove without constructing `None` paths (w103). |
| `resume-limited [name] [--force-now]` | §10. Native resume = fork-steer per G2(b) (`_resume_one_limited_native` @3255). |
| `archive [--ttl-hours] [--dry-run]` / `autoclean` | §11. |
| `doctor [--repair]` | §13 roster. Bare `doctor` remains report-only. `--repair` also revisits unarchived native-Codex worker rows already committed as `dead-suspected`: only matching durable completion evidence plus a validated live `thread/read` whose exact newest bound turn is `completed` can move the row to `idle`. Host reads run without `fleet.lock`; the commit is a full-row compare-and-swap, so kill, resume, and every other concurrent mutation win. |
| `sup-boot / sup-checkpoint / journal-roll / sup-heartbeat / sup-status / sup-guard / sup-handoff-begin / sup-handoff-complete / sup-handoff-abort` | §12 supervisor protocol; `sup-guard` is the one-line interface verdict (`OK`, `WAKE <name>`, `DISPATCH`, or `PAGE <reason>`) over the claim, sid union, roster PIDs, and handoff files; the verdict is lock-free, and `--do` actions take `fleet.lock` (per lane in `notify_lane_done`, and through `send` on `WAKE`); `--do` re-verifies and executes only `WAKE` through `send` with `supervisor/briefs/wake.md`; `DISPATCH` and `PAGE` are returned for the keeper to page, and only the interface runs `sup-spawn`. A stale heartbeat with no roster-live PID yields `WAKE` when the holder registry row is an idle, unarchived, resumable body; no working lane or ownership match is required. A dead, archived, or absent holder still yields `DISPATCH`. `OK` means a fresh heartbeat with a live busy or idle body and performs no supervisor wake, including with `--do`; `--do` always first runs the lane-done backstop sweep (§ lane-done, `lane_done_sent` in JSON). The machine-global roster is home-scoped: supervisor rows in this home or its descendants/worktrees remain liveness evidence, while rows positively belonging to another registered home (or no fleet home) are excluded; unreadable or ambiguous ownership remains `PAGE`-safe. `sup-checkpoint` keeps the board at the newest three checkpoints by rolling older entry bytes into `supervisor/journal-history/journal-roll.md`. |
| `wave-close --base SHA --changelog @file [--alias MERGE_LANE=WORKER ...]` | Claim-holder wave boundary: attributes lanes by matching `merge(<lane>):` against every merge commit's subject in `base..HEAD` (`_wave_merge_audit`); a merge subject it cannot match -- including git's own default `Merge <branch>: ...` -- is UNPARSED, and `wave-close` refuses the whole close, naming the unparsed count and SHA(s), before the claim, the reap, or the floor (all mutating or expensive). A range with zero merges is the distinct, legitimate no-lanes wave and closes normally. A lane-internal base-sync merge (`merge: sync master`, `Merge branch 'master' into <lane>`) is identified structurally by `_wave_sync_merges` -- off the first-parent mainline, with every non-first parent an ancestor of the base side of the landing that brought it in -- and is neither a lane nor UNPARSED, and needs no CHANGELOG line of its own; a lane-internal merge of any other branch stays UNPARSED. A merge subject that PARSES but names a lane joining to no registry record and no worktree is refused the same way, as `UNJOINED: N of M`, for the same reason: it has no substrate, session or token total, so every figure derived from it would be a confident zero. The join (`_wave_lane_join`) tries, in order: an explicit `--alias MERGE_LANE=WORKER` (repeatable; the worker must be a registry row and the lane must have landed in the range, else the close refuses before the claim), the branch the row records, the lane worktree's `cwd`, then a registry worker named like the token whose row records no branch or the home's default branch, and no `cwd` other than the home root (a lane that ran on `master` in the home joins without an alias; a row whose branch or `cwd` points elsewhere needs `--alias`, whether or not the lane worktree still exists). More than one candidate row at any step refuses before the claim and names the candidates. Once attribution succeeds it runs the shared reap, verifies the home's floor from a fresh `git clone --no-local` -- by default python3.10 and python3.12 through `uv run --no-project --with pytest` over `tests/` against the fleet repo's expected host-failure set; a home whose suite differs (its own project and deps, interpreters, test paths, failures) names its floor in `supervisor/wave-close.json`, read from the home checkout so it works tracked or git-ignored (`_wave_floor_config`: `interpreters`, `uv_run_args` with a `{python}` slot, `test_paths`, `pytest_args`, `expected_failures` -- empty when omitted, `env` with identifier names and `null` to unset, `uv_offline`; unknown keys or malformed values refuse before the claim; a single interpreter skips the cross-interpreter comparison; the receipt records `floor_config`) -- computes one `THROUGHPUT` line from `git diff --numstat`, prepends the supplied landing sentences and accounting line, rolls the journal, marks each landed lane's registry record `lane_state=landed` (joined by the lane branch the record keeps, `cwd` as the fallback, under `fleet.lock`), commits, pushes with bounded retries, and relays the exact accounting line through `sup-notify`. A floor total or expected host-failure-set mismatch aborts before landing. After landing, pushing and notifying, it stops each newly landed lane's session through the sanctioned `claude stop` path (`_stop_native_session_status`, never under `fleet.lock`) and runs the shared reap a second time, so the lane-landed row's slot frees inside this same wave-close run rather than the next boot or wave close. |
| `interface-register` | Registers one Interface provider: a validated tmux pane (plus its hosted Claude session), a hosted Claude session outside tmux, or an explicitly homed authenticated native Codex claim. Both provider routes take the target home's same `fleet.lock` and clear the competing provider identity inside that lock, so cross-provider registration remains exclusive under interleaving; re-running the same exclusive registration is a no-op. |
| `watch [--fleet-home PATH ...] [--mcx-dir DIR ...] [--mem-floor-mb MB] [--disk-floor-gb GB] [--interval S] [--timeout S]` | Lock-free interface watcher. It persists `state/interface/watch-cursor.json` per home, reports exactly one first event (`MAIL`, `LANE`, `LOWMEM`, or `LOWDISK`) and exits 0; timeout exits 3. `--interval` must be finite and greater than zero; `--timeout`, when supplied, must be finite and non-negative. Fleet registry and `mcx list` state transitions use the durable cursor, with explicit per-source validity markers: a failed or schema-invalid source leaves its prior state and an as-yet-unobserved source establishes its first valid snapshot without emitting a transition. Registry rows must be objects and mcx output lines must contain an ID and state; malformed snapshots are invalid. LOWMEM is read through the platform adapter (Linux `/proc/meminfo`); platforms without an implementation print an explicit unsupported notice. Disk thresholds are checked for every selected home. |
| `relay-ack --fleet-home PATH --mail FILE --line TEXT [--mirror-log PATH ...]` | Refuses mail outside `mailbox/to-fleet` without writing; otherwise appends one UTC line to the interface log and mirrors, atomically moves the file to `mailbox/done/`, and marks it seen in the watch cursor. |
| `init [--home PATH] [--statusline [--chain\|--force]]` | Bare `init` creates an initialized fleet home in cwd: `state/fleet.json` plus rendered `state/worker-settings.json` (G-K5 Reading A, 2026-09-10). It does not register the home globally. Explicit `--home PATH` also appends its registration (DESTRUCTIVE, E2); it refuses with `--fleet-home` or `--statusline`. Explicit `--fleet-home` keeps settings rendering in the selected initialized home; `--statusline` keeps existing resolved-home setup and installs into `~/.claude/settings.json`, refusing foreign incumbents (terminal-surface D6). Scheduler flags remain removed. |
| `home` / `knowledge` | Print resolved `FLEET_HOME`; print `knowledge/INDEX.md`. |

**Native Codex worker route (2026-10-04).** New `codex:<model>` rows default to
this route; `sup-spawn --model codex:<model>` likewise selects the native Codex
supervisor route, while explicit worker `--codex-adapter mcx` remains available.
Rows with
`dispatch_kind=codex-app-server` keep `session_id=null` and route every worker
verb by that durable discriminator; they never fall through to mcx. Ordinary
`status`/`wait` validate the exact provider-minted thread and newest bound turn
through the existing exact-home host and reconcile that observation with the
bounded exact-turn public-evidence file. Durable `completed` evidence for the
current bound turn yields `idle` after `notLoaded` or `systemError` only when
the validated live read also reports that exact newest turn as `completed`.
An in-progress, failed, interrupted, missing, or conflicting live turn remains
non-idle; an unresolved mutation never lets older completion evidence vouch
for unknown provider work, and a failed live read remains uncertain.
`doctor --repair` applies that same two-witness rule to `dead-suspected` rows
committed before the rule shipped. It snapshots only unarchived native worker
rows under `fleet.lock`, probes unlocked, and changes only rows whose complete
registry value still equals the snapshot; a concurrent terminal or resume
write wins without being overwritten. Bare `doctor` performs no such probe or
write.
Stale/file-only views remain probe-free. `peek` and `result` read only the
bounded exact-turn public-evidence file; `result` requires complete durable
item text and token usage and takes no lock, performs no RPC, and writes
nothing. Busy `send` uses
`turn/steer` with `expectedTurnId`; idle send and `resume-limited` start one
turn on the same thread. When a replacement host has a new generation, `send`
and `respawn` first reserve one `thread/resume` for the exact recorded provider
thread, validate its cwd/model/permission profile and unchanged newest turn,
then conditionally adopt the new generation only if the complete reserved row is
unchanged; reattachment creates no turn. A concurrent terminal or other row
change wins and adoption refuses without overwriting it. Kill refuses while the
resume reservation is pending and rechecks for that race before marking dead.
Spawn reserves the exact bound row immediately before its initial
`turn/start`: a kill that commits first fences the delayed launcher, while a
reservation that commits first makes kill refuse until acceptance is resolved.
Lost or conflicting resume evidence remains reserved and uncertain without a
retry. Interrupt uses `turn/interrupt` and commits only after same-turn
terminal proof. Other ambiguous mutation responses are likewise durably
reserved and never retried. Respawn requires old-turn terminal proof before
creating a fresh provider thread, reserves only by full-row compare-and-swap,
and carries the brief, journal, and queued mail. A concurrent kill wins instead
of being resurrected; each accepted-thread/turn commit compares the complete
reserved row. The retired thread is recorded with its exact turn and terminal
status.
The queue-overflow sentinel has one non-replay recovery:
the host replaces its failed stdio child and adopts the original spawn journal
entry only from an operation-tagged empty thread with matching effective
settings, or exactly one public turn beyond the bound history watermark;
otherwise the row stays uncertain with a queue-bound/concurrency remedy.
Public rate-limit reads provide the recorded reset horizon. No path signals a
Codex PID or manufactures USD usage.

Native Codex blocking requests are durable, generation-bound status evidence.
Only `codex-respond NAME REQUEST_ID DECISION` answers one, after validating the
explicit offered decision against the exact current worker binding; stale,
wrong, unknown, and already-consumed requests refuse without an implicit
approval or blind retry.

The wave-close row's per-home configuration also owns landing gates: a missing
`supervisor/wave-close.json` preserves the fleet home's `docs-currency` and
`receipts` gates, while a configured foreign home defaults to no fleet-specific
gate and may select named built-ins or `{name, command}` checks. Merge subjects
`merge(hotfix/<name>): ...` are interface/supervisor bookkeeping, listed in
throughput with workers `0` and exempt from worker joining; unknown merge
subjects remain UNPARSED and refuse the close. Both the floor and landing-gate
configuration are resolved from the home checkout root, even when `fleet land`
is invoked from a nested directory or a linked lane worktree; refusal totals
count every merge in the range, including hotfix bookkeeping. Named gates use
one shared allowlist (`docs-currency` and `receipts`); unknown names refuse
before either landing or wave-close work begins.

## 8. Outcome store + the hook write boundary

**The outcome store** (`state/outcomes/<key>.jsonl`; key = worker NAME resolved from the registry, sid-keyed fallback on any resolution failure) is the discriminator's data source and the result surface. Writers, exactly two:

- **The Stop hook** (`bin/hooks/stop_outcome.py`): on every natural turn end, appends a `kind:"result"` record — result text from the payload's `last_assistant_message` (feature-detected; value shape UNOBSERVED at 2.1.207) with a transcript-tail fallback (last `type:"assistant"` record's `message.content[].text` — the contract's verified shape), plus token usage and model. Standalone stdlib, never imports `fleet.py`, never blocks, exits 0 on every path.
- **Fleet-side tombstones** (`write_tombstone_outcome` @5834, kinds `killed | interrupted | stopped` @5702): `claude stop` fires **no** Stop hook (G10), so every stop-shaped verb (interrupt, kill, respawn `--force`) records its own outcome — a stopped worker with no record would misclassify as `dead-suspected` forever, or worse as silently completed.

Both writers use a **single-syscall Win32 `FILE_APPEND_DATA` atomic append** (`_atomic_append_bytes` @5712, mirrored in the hook): plain buffered `open(...,"a")` appends lose whole records under concurrent writers on Windows, and the hook and a fleet tombstone can hit the same file in the same instant. Records are keyed by sid + timestamp; readers: `read_outcomes`/`latest_outcome`/`has_fresh_outcome` @5772-5833 (`OUTCOME_FRESH_SLACK_SECONDS = 5`).

**Hook write boundary (the sanctioned list, v2.3 item (d) carried forward).** Hooks NEVER write the registry or `events.jsonl`. Hooks MAY write, and only: (a) `mailbox\<sid>.md` + its `.claimed.<pid>` rename; (b) `state\hook-errors.log` (append-mode, best-effort, no lock); (c) their own worker's journal, via PostCompact only; (d) their own worker's terminal-outcome record, via the Stop hook only. Registry access from a hook is read-only and failure-tolerant; every hook exits 0 on every failure. `fleet doctor` smoke-tests both mailbox hooks and lints the registered hook events (`_KNOWN_HOOK_EVENTS = {PostToolUse, Stop, PostCompact}` @5576 — the plugin registers no hooks at all since D7, and `stop_outcome.py` is wired **ahead of** `stop_mailbox.py` in the template's Stop array — the outcome record lands before any stop-block continuation; receipt: `worker-settings.template.json`).

On an allowed worker Stop, `stop_mailbox.py` first reads the registry and claim to skip lanes the current claim does not own, then invokes the bounded `lane-done` bridge after the outcome hook. Ownership survives supervisor sid rotation (every `fleet send` wake gives the supervisor a new sid in the same incarnation): a lane is owned when its `spawned_by_lineage` equals the claim's `lineage_id` or is in the claim's `adopted_lineages`, or its `spawned_by` is in the holder row's sid union (current plus `retired_sids`). A seize or limit-transfer re-mints the lineage but records the seized claim's `lineage_id` plus its own `adopted_lineages` (newest first, at most `ADOPTED_LINEAGES_MAX`) as the successor's `adopted_lineages`, so lanes spawned by a seized supervisor still report to the successor; handoff carries the list unchanged and a fresh claim (after release or with no claim) starts empty. Adoption is LANE-DONE ownership only: `_worker_is_foreign` never reads it, so the seized body's workers stay foreign to kill/clean/respawn. The bridge re-verifies ownership and delivers `LANE-DONE <name> <status> <head-or-none>` to the holder's row through the existing send path: busy bodies receive mailbox mail and idle bodies wake. Claim heartbeat age is not a condition (an idle holder does not beat); a dead, interrupted, dead-suspected, limited or over-ceiling holder row is. Supervisor-shaped source rows never notify, including handoff successors and the supervisor's own Stop. A per-finished-turn marker (`[sid-or-mcx, last_dispatch_at, newest assistant uuid]`; the uuid is omitted when no transcript is readable) suppresses duplicate deliveries of one finish while a later Stop in the same dispatch still delivers; it is recorded only after the send returns: under the lock the bridge first stores a `lane_done_pending` claim `{key, at}`, which suppresses a concurrent duplicate, is cleared if send fails so the next observation can retry, and only advances the delivered marker if that turn is still the newest transcript finish, so a slower older send cannot move the marker backward; it becomes retryable after `LANE_DONE_PENDING_SECONDS` (300) if the process died mid-send (the keeper's 180 s timeout), so a killed send may re-deliver once but never loses the finish. A G9 roster refusal (`TransientSendRefusal`) is retried once after `LANE_DONE_RETRY_SECONDS`. A failed hook bridge is logged once in `hook-errors.log` and never blocks Stop. Idle Codex observations use the same bridge. Backstop: `sup-guard --do` (the keeper tick) first runs `sweep_lane_done`, which recomputes owned non-archived lanes' native status from one roster fetch (a suspicious roster defers the sweep) and delivers any idle lane's undelivered finish; its JSON reports the names as `lane_done_sent`. The bridge does not inspect a claim nonce.

## 9. Steering, mailbox, budget

**Mid-turn steering is unchanged from v2** (G1: hooks fire inside `--bg` sessions): `send` to a working worker appends to `mailbox\<sid>.md`; PostToolUse claims-by-`os.replace` and injects `<MANAGER MESSAGE>` at the next tool boundary; Stop drains-or-blocks. Exception-proof, exit-0, claim-race-tolerant — all v2 §7 semantics stand and the moved history file remains their reference; they are substrate-independent.

**Registered Interface direction to a supervisor is receipt-backed.** Before
mailbox delivery, `send` authenticates the caller against the registered Claude
session, native Codex process/thread claim, or (for a caller with no hosted
identity) tmux pane. It atomically stores the exact instruction plus digest and
registration identity under `state/mail-receipts/<id>.json`; the mailbox gets
only a `FLEET VERIFIED MAIL NOTICE <id>` telling the supervisor to run
`fleet mail verify <id>`. Verification re-checks current registration continuity
and emits the stored instruction only after `VERIFIED`. Interface registration
is single-provider: Claude/tmux registration removes the native Codex claim,
Codex registration removes the Claude session and pane bindings, and verification
fails closed if both provider families are nevertheless present. A forged mailbox
notice therefore has no authority by content alone. This is registration-backed
application provenance with an integrity check, not a privilege boundary
against another process running as the same OS user with write access to Fleet
state. When a supervisor send cannot authenticate a registered Interface
source, Fleet instead delivers an explicit `FLEET UNVERIFIED INTERFACE MAIL`
envelope. It includes the rejected body for diagnosis and tells the supervisor
not to act, to journal and surface the failure and body, and to request
registration plus a resend. Non-supervisor sends retain the ordinary raw-mail
path. Fleet-generated structured supervisor notices bypass this free-form
Interface envelope.

**Idle steering = fork-steer (RATIFIED G2(b)).** No CLI channel injects a prompt into an existing idle daemon session; `claude --bg --resume <sid>` **forks** — new sid, full transcript carried. Fleet adopts the fork as the worker's new canonical identity: old sid → `retired_sids`, mailbox re-pointed, ceiling file re-written, fresh `-n` restamp (which is also when a category change renders — no post-hoc rename channel exists, G13). The **universal drain rule** survives: every launch path (spawn, fork-steer, resume-limited, respawn) drains the current sid's mailbox into the composed prompt, and `status` flags `idle+mail`.

**Native peer messaging** (`docs/specs/peer-messaging.md`): a Claude session can steer a live fleet session in place with `SendMessage`, without a fork. Fleet cannot send natively; `fleet address` gives the caller the exact `to`. The worker settings template sets `crossSessionInbound: "accept"` so dontAsk lanes and bypass supervisors receive each other's messages.

**Budget = token ceiling, not dollars.** `--max-budget-usd` does not exist under `--bg` and no sanctioned source carries a USD figure (G3) — spawn and respawn **refuse** it outright (@2188, @3674). The fleet-side cap is `token_ceiling`: persisted spawn-immutable in the registry, written to the sid-keyed ceiling file (`_write_ceiling_file` @164) that the Stop hook reads to allow-stop despite pending mail, and enforced before every fork-steer — `_native_cumulative_tokens` (@1060) sums the outcome store; at/over ceiling the steer is refused and the worker flagged sticky `over_ceiling` (@3103-3117, event `ceiling_exceeded`). `over_budget` remains in the sticky set for legacy-record tolerance.

## 10. Usage-limit continuity (rehomed for the silent wall)

A plan-limit wall under `--bg` is **silent**: no Stop hook fires, roster state is unchanged — the only sanctioned evidence is a synthetic 429 assistant record with a reset time inside the transcript (G11, naturally pinned). Detection therefore rides the **no-outcome investigation path** (§5), not hooks and not stderr (neither channel exists any more): `transcript_limit_scan` (@1184) reads the transcript tail through the module seam `_limit_scan_hook`, parses limit-shaped text + reset instant (`_parse_limit_signal` @1100), and parks the worker **`limited`** — sticky, exempt from every demotion, never archived, never steered (`send` refuses and points at `resume-limited`).

Resume is the explicit sweep it always was: `fleet resume-limited [name] [--force-now]` relaunches each `limited` worker whose `limit_reset_at` has passed — **as a fork-steer** (`_resume_one_limited_native` @3255: drain old-sid mailbox + journal into a continuation body, `dispatch_bg(resume_sid=old_sid, hint="resume past limit")`, retire the old sid, restamp, clear the limit fields). Unknown horizon (`limit_reset_at = null`) is skipped without `--force-now`; failures roll the park back to `limited` cleanly. `status` flags `resets <when>` / resume-eligible (flag only — a view never launches); `doctor` NOTEs parks past their horizon and unknown horizons (`_doctor_check_limited_parks` @5300). Native auto-resume does not exist; fleet's layer carries the full recovery load.

## 11. Archive + autoclean (staleness is cleaned up without anyone remembering)

Full design: `docs/specs/autoclean.md` (ready-for-build → shipped M-C). As built:

**Lifecycle reap mechanism (2026-09-10):** successful `sup-boot` assembles its
bundle, then invokes the shared autoclean pass before printing `reaped: N rows`.
`sup-handoff-complete` and `sup-release` invoke it after their claim transition,
outside the lock. Refused/frozen boots and claim-pending handshakes do not reap.
Maintenance failures are reported without suppressing the one-shot nonce or
undoing a completed claim transition; an unreadable registry defers maintenance.
The boot context states the reap rule, **3 live worker sessions max** across
Claude and Codex (each Codex lane is one), and a **1.5 GB available-memory floor**
before any dispatch. These resource limits are supervisor instructions, not new
admission-control code. Supervisors have no hand-run autoclean/archive step.

Autoclean tier 1 reuses the archive writer with an age-independent criterion:
explicit registry `lane_state: landed|abandoned` or matching latest outcome kind
plus an idle session; an explicitly daemon-dead roster row (no status/pid) needs
no outcome; a predecessor supervisor body outside the current claim needs no
TTL. Result-only idle workers are not treated as landed. Current claim/incarnation,
pending successors, unread/claimed mail and live PID or busy-status evidence
protect a row; PID/mail checks include retired sids, except an idle PID-bearing
retired daemon spare on a landed/abandoned row. Roster absence alone is not
daemon-dead evidence. The legacy TTL fallback remains for ordinary older completed
workers, with the same stronger PID/mail protections in autoclean. Manual archive
keeps its existing TTL contract. Crash-resumes and husks share the same whole-row protection. Automatic archive
leaves mailbox files in place, including mail that arrives during evidence moves.
Lifecycle calls explicitly carry the validated caller SID through the pass:
the caller's whole current/retired SID union is protected even after release or
handoff removes its claim holdership. Any overlap in SID ownership between
registry rows also vetoes reaping for every involved row, including dead/archived
rows that the identity resolver may otherwise deprioritize. This shared veto
covers eligibility, pre-commit checks, archive resumes and husk removal; reaping
must not undo an ambiguous-identity abstention by the release path. Caller
protection lasts for that pass only, so a later body's pass can reap a uniquely
owned dead predecessor. Unreadable ownership evidence defers removal.
`reaped` counts newly archived registry rows, not retries or duplicate husk removals.
The rendered roster/status portion is the pre-pass snapshot; use the post-boot
roster for the after receipt. Codex rows (native app-server and mcx) archive by TTL
alone -- unarchived, idle/dead/interrupted, no unread mail on their thread, older than
the TTL -- with no `claude rm`, and Codex lanes still count toward the combined dispatch limit.

- **`fleet archive`** (@4443): TTL sweep. Eligibility gates in binding order (`_archive_eligible` @4250): native + not already archived; recomputed status ∈ {idle, dead, interrupted}; roster entry absent or dead (**never** a live-process entry); an outcome record exists for the current sid (any kind — no record is dead-suspected territory, never auto-archived); TTL elapsed (default 24 h) on a parseable `last_activity` (unparseable fails safe). `limited` is never archived. Archive = evidence files (outcomes, journal, task file) moved to `logs/archive/<name>/`, registry entry tombstoned (`archived_at`), native sessions removed via `claude rm` (current + retired sids, G12). Reversible history; deletion stays `fleet clean`.
- **`fleet clean` evidence guard:** before deleting a dead worker's brief, journal,
  task, outcome, mailbox, ceiling, or log files, clean moves any present artifacts
  to a recoverable `logs/archive/<name>/` directory and prints that location. If a
  move fails, clean leaves the registry row and source files untouched for retry.
  The final mailbox rescan and row deletion occur under one `fleet.lock` hold;
  after that hold is released, clean never unlinks mailbox content, so a late
  delivery remains in the inbox (or in the archive from the rescan) for recovery.
  Cleaning an already-archived tombstone still removes its existing archive tree.
- **`fleet autoclean`** (@4812): the scheduled first-class command (D1 — an ordinary mutating CLI verb; views untouched). Tier 1 (default-on) = the age-independent reap criterion above, then the legacy archive TTL fallback. Tier 2 (default-on) = daemon-husk removal under the sid-based **default-deny ownership discriminator** (owned ∧ ¬protected ∧ roster-not-live ∧ no pending mail; owned-evidence = registry sids/retired sids + archive-dir sid files + events sids, @4626-4688); refuses when the registry is absent-but-evidence-exists (F1) or any `fleet.json.corrupt.*` quarantine artifact exists (NEW-1); foreign sessions — above all the operator's own — are untouchable. Tier 3 (default-OFF, `--expire-tombstones-hours`) = registry tombstone expiry, deleting no files. `RegistryCorruptError` aborts the whole run; other tier failures are isolated. Run stamp `state/autoclean-last-run.json` + `autoclean_run`/`husk_removed`/`tombstone_expired` events.
- **Scheduler bridge — RETIRED 2026-07-27, kept as record.** The verb's callers are now automatic supervisor lifecycle transitions and the interface's startup ritual (`skills/fleet/supervisor.md`, `skills/fleet/SKILL.md`); fleet installs no OS-scheduler state on any platform, and both backends' `autoclean_task_*` methods are deleted rather than stubbed. The task carried `StartWhenAvailable=False`, so a 9h14m power cut dropped the 08:22Z sweep with no catch-up at boot — an 18-hour hole in a 6-hourly guard. A timer sweeps when the clock says so; a beat sweeps when the fleet is alive. The F2/F3/F4 ownership reasoning below stands as the requirement any FUTURE scheduled task inherits. *What it was:* `fleet init --autoclean` installed Windows Scheduled Task `claude-fleet-autoclean` (schtasks, default 6-hourly) with the F2/F3/F4 guards: home embedded in the command, refuse worktree/mismatched-fleet.py homes (a third guard, refusing a home that contradicted the machine's `~/.claude/fleet-home` marker, went with the marker on 2026-07-22), fail-closed on a query error, and **ownership by full identity** — an existing task is "ours" only if it runs this resolved `fleet.py` **and** the `autoclean` subcommand **and** `--fleet-home <this home>`, matched on whole slash/case-normalized tokens, never a substring (`_fleet_task_is_ours`). Path-only ownership silently voided the F4 guard the moment a second fleet-owned scheduled task existed — `fleet init --supervisor-beat` being the near-term case — because `/Create /F` would have overwritten it. Guards run before init writes anything (N1). Platform adapter seam: `autoclean_task_install/query/remove` on `_WindowsPlatform`; `_PosixPlatform` raises `UnsupportedPlatformError`.

## 12. Supervisor protocol (§4 of the pivot spec — survives unchanged, now with verbs)

**Soul = local files:** `supervisor/GOALS.md` (operator-owned) +
`supervisor/JOURNAL.md` (append-only, claim-holder-only) + the home's local
knowledge. The whole `supervisor/` tree is ignored public-source runtime data.
**Body = any session** holding the claim: `supervisor/INCARNATION`, written
only under `fleet.lock`, read lock-free (atomic `os.replace` writes), carrying
incarnation id, sid, and a heartbeat the holder refreshes at every
checkpoint/beat, lane dispatch, and `sup-notify`
(`SUPERVISOR_CLAIM_STALE_SECONDS = 3600`).

**Journal board maintenance.** `fleet journal-roll` and the post-append step in
`sup-checkpoint` retain the newest three `CHECKPOINT` entries on the board.
Entries before the oldest retained checkpoint, including older `BOOT`, `SEIZED`,
and `HANDOFF-*` entries, are copied as exact bytes to the stable append-only
sink `supervisor/journal-history/journal-roll.md`; the board's seed text and
retained entries remain in place. The roll verifies its byte partition and
refuses a malformed entry-looking header without changing either file. The
fixed sink avoids a date-range filename becoming stale or ambiguous.

**`interface-register`.** The interface runs this one command on resume. It
accepts only the `%<decimal>` pane shape already required by the keeper,
renames that pane's window to `fleet` when needed, and writes
`state/interface-pane` after successful tmux verification. When the pane caller
also has a Claude session id, registration binds that id in
`state/interface-session`; a later pane-only registration clears the stale
session binding. Outside tmux, a hosted Claude caller registers its session
identity directly. Both provider routes take the target home's same
`fleet.lock`; either Claude path removes a superseded native Codex claim inside
that lock, and native Codex registration removes both Claude registration files
inside it. An invalid
pane/session identity, or an unavailable tmux pane, is a clear refusal and never
writes a new registration.

**INCARNATION v2 (claim-nonce §5.2).** The claim additionally carries a per-body **generation** — `nonce_hash` (the live generation), optional `pending_nonce_hash`/`pending_at`/`prior_pending_hash`, `nonce_seq`, and a `lineage_id` — none of which is a stored secret (only sha256 hashes live in the file; the plaintext is printed once, on the minting verb's stdout). Continuity, not the sid, is the claim key: it survives fork-steer/respawn/handoff, and a stale generation is *evidence* rather than noise. A **released** claim (`state: "released"`) drops the generation and the sid entirely (§6.3). Additive-schema: a pre-nonce five-key INCARNATION is a **legacy** claim (`nonce_hash` absent AND `state` absent), honored once by sid equality and upgraded in place (§9).

- **`sup-boot`** (@6657): the one boot ritual — roster-epoch sanity check FIRST (`supervisor_epoch_check` @6548; suspicious roster freezes the claim decision too), then the claim rules (`supervisor_claim_decision` @6560): a **released** predecessor (roster-gone releaser) ⇒ `claim` fresh, no seizure, no page (§6.3); holder parked `limited` with a horizon ⇒ `limit-transfer` (re-mints lineage); holder live in roster **and not the caller proving continuity** ⇒ refuse read-only; the caller *is* the holder, roster-live, proving continuity on an aged claim ⇒ `resume` — no seize, no new incarnation, no `SEIZED` (incident 2's fix); roster-gone + heartbeat stale ⇒ seize (journal `SEIZED`, delete any orphan HANDSHAKE); roster-gone + heartbeat fresh ⇒ freeze + page operator, never seize on ambiguity. Prints `NONCE: <value>` whenever it mints. Emits the boot bundle — five parts (`_render_boot_bundle`): GOALS + journal tail (last `SUPERVISOR_BOOT_JOURNAL_TAIL`=5 entries; `_select_boot_journal_inline_indices` inlines bodies for `SUPERVISOR_JOURNAL_SUBSTANTIVE_KINDS` (CHECKPOINT/PROPOSAL/PARKED) only, newest-first, at least `SUPERVISOR_BOOT_INLINE_MIN`=2 when that many exist and more while under `SUPERVISOR_JOURNAL_INLINE_BUDGET_CHARS` — terse bookkeeping kinds (BOOT/SEIZED/...) are always one-line pointers, "full text: supervisor/JOURNAL.md", regardless of position, so a boot's own freshly-written BOOT entry never crowds out the checkpoints behind it; w90, 2026-09-16, supervisor gate v2) + `knowledge/INDEX.md` (first 20 non-blank lines) + roster counts + fleet status snapshot. Each inlined entry is capped at `SUPERVISOR_LATEST_ENTRY_MAX_CHARS` (2,000 chars) with a truncation pointer, GOALS is capped at `SUPERVISOR_BOOT_GOALS_MAX_CHARS` (8,000 chars) with a pointer to `supervisor/GOALS.md` (w104: a 15,234-char GOALS alone broke boot), and the whole rendered bundle is refused past `SUPERVISOR_BUNDLE_MAX_CHARS` (20,000 chars — lowered from an untested 40,000; pinned by `tests/test_boot_bundle_cost.py`); a refusal after the claim decision still prints `EPOCH`/`INCARNATION`/`VERDICT` and the minted `NONCE:` before exiting 1, so the generation is not lost. A GOALS.md or INDEX.md that is not UTF-8 renders as an `unreadable: not UTF-8` placeholder in the bundle rather than aborting after the claim is committed. The status snapshot and computed board count a lane as live only while its turn runs, it is attached, or it has unread mail (`live_lane_count`); other non-terminal rows are `idle_lane_count`, and only the 12 (`SUPERVISOR_IDLE_ROWS_LISTED`) most recently active idle rows are listed before one `+N idle` line (w103). After assembly, successful claim-holding boots run the automatic reap pass before printing its count and resource policy (§11); refused/frozen boots and pending successors defer it.
- **`sup-checkpoint` / `sup-heartbeat`** (@6741/@6755): journal append (claim holder only, kinds `SUPERVISOR_JOURNAL_KINDS` @6371 — now `BOOT`/`CHECKPOINT`/`PROPOSAL`/`PARKED`/`SEIZED`/`RELEASED`/`LIMIT-TRANSFER`/`HANDOFF-BEGIN`/`HANDOFF-COMPLETE`/`HANDOFF-ABORT`) / heartbeat refresh without a journal write. `sup-checkpoint --kind PARKED <reason>` records `parked_at`, `parked_reason`, and an optional `--wake-when` condition while refreshing the heartbeat; a later normal checkpoint clears the marker. Both require a continuity proof (`--nonce`) and mint the next pending inside the same lock.
- **`sup-release`** (claim-nonce §6.3): the claim holder rewrites INCARNATION as a `released` claim (enumerated key set — `incarnation_id`/`lineage_id`/`claimed_via`/`released_at`/`released_by_sid`/optional `reason`/`state`), journals `RELEASED`, then the body EXITS. The next `sup-boot` claims fresh with no seizure and no page — this is what distinguishes an operator-authorized stop from a daemon restart. No `--force` form. `supervisor_status_line` and `sup-status` learn the released state so a clean release never reads as corruption. After the claim write and own-body tombstone, the command invokes the shared reap pass outside the lock (§11).
- **`sup-guard`**: the interface verdict (lock-free; `--do` actions take `fleet.lock`) pages an unsettled seized claim when its heartbeat is stale or unreadable; a seizure settled by a later heartbeat and a fresh seized claim follow the ordinary held-claim liveness rules. This preserves `PAGE` for stale seizure ambiguity while treating a past seizure event with a fresh holder heartbeat as an ordinary held claim. G-K8 C makes this the keeper's sole supervisor-liveness decision: `supervisor-stalled` runs `fleet sup-guard --do --fleet-home <home> --json`. A stale roster-busy holder remains `PAGE`, but the guard now walks only that roster PID's bounded process tree and includes up to three descendants running at least five minutes, with executable basename and age; arguments are never captured or persisted. The keeper relays the same diagnostic without putting changing ages into its dedup fingerprint. This observation takes no fleet lock, writes nothing, and adds no registry read. A current claim marked `PARKED` by `sup-checkpoint --kind PARKED` reports `PARKED` (and the keeper does not page) even when its body is stale, reaped, or dead-suspected; the same projection applies to a native Codex claim with an idle provider. A current-sid result from an owned lane at or after `parked_at` proves the parked wait boundary was reached: if the holder has no live body, the guard returns `WAKE` for an idle resumable holder or `DISPATCH` otherwise, without waiting for heartbeat expiry. The marker expires after 24 hours, and future-dated markers are invalid, after which ordinary `PAGE`/`DISPATCH` rules resume. A successful `sup-guard --do` wake, `fleet send supervisor`, or `sup-boot` resume clears the marker. A stale idle current body with a live PID can yield `WAKE`; `--do` re-observes before sending `@supervisor/briefs/wake.md`. It never spawns: `DISPATCH` and `PAGE` reach the interface as pages; `OK` for fresh healthy state pages nobody and wakes nobody. A limited body yields `PAGE supervisor limited` once until its recorded roster horizon, with no wake before that horizon. The ISO `limit_reset_at` comes from a native body row or matching fleet status row; once it passes, the page asks the interface to resume rather than sending to a parked body. JSON `sent: true` records successful send plus the `parked_*` marker fields; `OK` suppresses the supervisor page independently of `quiet`; `quiet: true` also suppresses it for inactive goals. Guard/send failures also page.

  The heartbeat/liveness table (operator, 2026-09-11), after ambiguity checks:

  | Heartbeat | Body | Verdict |
  |---|---|---|
  | Fresh | Live PID, busy or idle | `OK` — no page, no wake |
  | Stale | Live PID, idle | `WAKE <body>` |
  | Stale | Live PID, busy | `PAGE` — name long-running descendant executables and age |
  | Stale | No live PID, idle resumable holder row | `WAKE <body>` |
  | Stale | No live PID, no idle resumable holder | `DISPATCH` |
  | Fresh | No live PID | `PAGE` — freeze |
  | Registry or roster unreadable | — | `PAGE` |

  A live body must never yield `DISPATCH`; the keeper only pages `DISPATCH` to the interface, which owns `sup-spawn`. Keep `PAGE` for unsettled stale/unreadable seizure, unknown claim state, handoff in flight, unreadable HANDSHAKE, a releasing body still roster-live, unavailable SID union, and limited state. A stale busy body or unreadable heartbeat remains ambiguous and pages. `--do` acts only on `WAKE`; `OK` and `PAGE` perform no action.

- **Handoff** (`sup-handoff-begin/complete/abort` @6823/@6931/@6963): old dispatches a claim-pending successor **on the sanctioned second dispatch path (§6.1), not through `dispatch_bg`** — which cannot be used here and is refused at its own name guard if attempted (successor task rendered by `_render_successor_task`). Verification turns on a one-shot **token, not a sid** (claim-nonce §6.4): begin mints the token into the successor's task file and stamps its hash into its own claim; the successor's `sup-boot --handoff-inc --handoff-token` writes `supervisor/HANDSHAKE` carrying the token hash and its OWN freshly minted generation (not a journal write — it holds no claim yet); `complete` verifies the token (its `--expect-sid` is now optional — a mismatch warns, does not refuse), carries the successor's generation into the transferred claim (live, not a legacy upgrade), transfers under `fleet.lock`, deletes HANDSHAKE and the plaintext-token task file; `abort` stops the limbo successor (`SUPERVISOR_HANDSHAKE_TIMEOUT_SECONDS = 300`), removes HANDSHAKE and the task file, raises the doctor-visible abort flag (@6407). `sup-handoff-begin --complete-timeout SECONDS` keeps the predecessor's already-proved generation in the same process, polls the atomic claim and HANDSHAKE files without `fleet.lock`, then runs the same completion transition. Its cleanup guard arms as soon as the full successor sid is verified, before pending-sid, registry and event bookkeeping, and aborts every later pre-transfer exception. It retains that original incarnation/SID/token proof immutably; the later locked claim reread is a separate comparison snapshot, so a concurrent begin can replace the live token hash without invalidating cleanup of the original body. Automatic abort makes one decision under `fleet.lock`: an unchanged predecessor claim runs the ordinary abort transition, a claim already transferred to this successor is a no-op, and any other changed claim prepares only the retained incarnation/token-proven successor cleanup. Scoped cleanup writes its diagnostic abort flag in that locked decision; only the selected external stop and console reporting run after the lock, so neither a competing transfer nor a newer flag can be overwritten afterward. Omitting the option preserves the two-verb path. Operator band (ratified 2026-07-23, `docs/specs/three-tier-command.md` §11 — supersedes the drafted 300–500k; **raised by operator ruling 2026-08-05**): the supervisor enters at **350k** context occupancy, hard ceiling **400k**; a worker enters at **250k**, band top **300k** (§11.4). Both tiers observe a band; since the raise they no longer share one, and `fleet sup-context` resolves which applies to the body running it. Completion invokes the shared reap pass after transfer, outside the lock (§11).
- **The claim gate (claim-nonce §7, option (b)):** while a claim is held with a **fresh** heartbeat, the mutating lifecycle verbs (`spawn`/`send`/`respawn`/`kill`/`clean`/`interrupt`/`archive`/`resume-limited`/`release`/`init`) require a session-bearing caller to present the current generation (`--nonce`) or be refused (`SupervisorClaimGateError`, exit 4). It validates without minting. A **knowingly-bypassable speed-bump against a divergent second body, not authorization** — bypassable by a caller with no session id, armed only while the heartbeat is fresh, `autoclean` exempt. **The `autoclean` exemption is NOT transitive and is not "structural"** (corrected 2026-07-28): `cmd_autoclean` does not call the gate, but its tier-1 delegate `cmd_archive` does, so the exemption is carried explicitly as `cmd_archive(..., as_autoclean_tier=True)`. Between 2026-07-27 and 2026-07-28 it was not carried at all and every beat-driven sweep lost its archive pass — see `docs/specs/autoclean.md`. The `archive` verb itself stays gated.
- **Nag predicate is file-only** (views never probe): GOALS active AND (no claim OR heartbeat older than S) — `supervisor_goals_active`/`supervisor_status_line` @7037/@7049, surfaced by `_doctor_check_supervisor_claim`/`_doctor_check_supervisor_handoff` @7079/@7088. The keeper can wake an existing idle supervisor through the guard; spawning a supervisor remains the interface's action.

The shared tmux notification sender used by both the keeper and `sup-notify`
waits `INTERFACE_PASTE_SETTLE_SECONDS` (0.5 seconds) after a successful literal
send before sending its single Enter. This bounded settle is required by
Codex's paste-burst composer behavior; a failed literal never sends Enter, and
an Enter failure is reported as a failed delivery. Unit tests inject the clock
sleep, so they do not incur the wall delay.

Heartbeat primitive: in-session `ScheduleWakeup` self-rearm, confirmed real (G7); `claude stop` permanently kills a scheduled wake — a stopped supervisor never self-resumes.

## 13. Doctor roster — as it is today

**31** checks (`grep -c "def _doctor_check_" bin/fleet.py` → 31; `cmd_doctor`'s `check_calls` list registers 31 as well, and a live `fleet doctor` against a fresh home prints 31 `[PASS]/[FAIL]/[WARN]` rows — all three re-measured 2026-10-04, on a temp `FLEET_HOME`, by the lane that moved the number. **The registrations are the authoritative number**, not the grep: the grep counts *definitions*, and a check defined but never wired in would inflate it alone. They agree today because the two name sets are identical, checked rather than assumed. `tests/test_doc_claims.py` derives the number from `check_calls` by AST and now holds this line.)

**Count history, re-derived 2026-08-09 rather than remembered** — 21 at §0's `c63d7dd` pin → 22 on the hook-removal branch → 23 once M-D/M-E added `daemon_wedge` and `tzdata`, `fleet_home_marker` was removed on 2026-07-22 with the marker itself, and the three-tier build slice added `pending_decision` §8 → **28** today. This section said **23** behind a pasted `grep -c` receipt that itself returned 23 when written and returns 28 now, and its roster below named only 23 of them — so the number and the roster were wrong together, which is why re-counting the roster reconstructs the delta exactly. The five it never gained, each with the commit that added it (`git log -S "def _doctor_check_<name>"`): `registry` (`875a46c`), `instance_grants` (`9f7fe26`), `permission_stalls` (`1b97efb`), `identity_witness` (`bd3dfd2`), `supervisor_wedge` (`346a747`). 23 + 5 = 28, so nothing here is reconstructed from memory and there is no unexplained gap. **28 → 29 on 2026-09-09**, when lane `w56-permvis` added `permission_denials` — the permission-DENIAL row, registered immediately after `permission_stalls` because the two answer the same operator question from the two different witnesses available. It is NOTE-only (`ok=True`) where the stall row is a FAIL, so it does not change what `fleet doctor` exits with: measured on a fresh home the same day, 4 FAIL before `fleet init` and 29 PASS and 0 FAIL after, exactly as before with one more PASS row. **29 → 30 on 2026-10-04**: `local_seeds` reports missing seeded local-storage files (wake brief, journal, knowledge index); a fresh `fleet init` home passes it, so initialization leaves no failures and adds one passing row. **30 → 31** on this lane: native Codex became the default and `codex_adapters` added the record-local migration census; a fresh `fleet init` home now passes all 31 checks (31 PASS / 0 FAIL).

Note-only unless infrastructure is actually broken, with the FAIL-capable rows named inline: `registry` (registered FIRST — could `state/fleet.json` be read at all; when it fails every worker-keyed row below it is vacuous. REPORT-ONLY, per root `CLAUDE.md`: the quarantine rename lives in `load_registry`, and `doctor --repair` is the only verb whose *purpose* is that rename), `claude_version` (≥ 2.1.202), `pin_version` (claude moved since last recorded pin pass — §17), `instance_settings` (validates + hook-path lint), `instance_freshness` (MTIME comparison against the template), `instance_grants` (the rendered instance still carries the template's fleet grants — `instance_freshness` compares mtimes and so cannot see a hand-edited instance that is merely *newer*), `hook_registration` (event-name lint), `legacy_settings`, `posttooluse_hook_smoke` + `stop_hook_smoke` (synthetic-stdin fire of both mailbox hooks), `terminal_launcher`, `mailboxes` (orphaned/pending), `stale_attaches`, `limited_parks` (past-horizon / unknown-horizon / weekly notes), `legacy_mix` (pre-pivot records present — read-only legacy, finish or kill), `codex_adapters` (**FAIL** on mixed/invalid rows or a helper required by an unarchived row being unavailable; otherwise reports native/mcx/invalid counts without probing either adapter), `dead_suspected` (surfaced verdicts awaiting decision), `permission_stalls` (**FAIL, deliberately not note-only** — a worker parked on a permission prompt nobody will answer is stalled, not healthy), `orphaned_claims`, `identity_witness` (`FLEET_WORKER` against the registry — a WITNESS, never evidence to be believed over the registry; claim-nonce §18), `claude_agents` (fleet-unknown roster sessions, overlay-aware), `daemon_wedge` (M-E: file-only stale-`daemon.lock` signal — starts no daemon), `autoclean` (task installed/stale-run via the adapter query), `hook_errors` (tail of `state/hook-errors.log`), `supervisor_claim` (note-only, EXCEPT it flips `ok=False` on a `refused` continuity record in the last 24 h — evidence of a second body — and NOTEs a `superseded-pending` acceptance or an over-age unacknowledged pending; claim-nonce §5.6), `supervisor_wedge` (**FAIL** — a `released` claim whose releaser is still roster-live: `sup-boot` REFUSES in that state, so the fleet has no supervisor and cannot get one, while every other surface reports a clean release), `supervisor_handoff` (also NOTEs an orphaned `state/supervisor-handoff-*.md` past the handoff timeout — spent-token residue, §5.9), `pending_decision` (three-tier §8: the operator-gate routing state file — FAIL while an operator decision is OPEN and unanswered, or the file is corrupt; an answered-but-uncleared decision is a NOTE), `tzdata` (M-E: `zoneinfo` can resolve named zones, which the usage-limit horizon parser needs).

The order above is `cmd_doctor`'s registration order, which is the order an operator sees. It is not alphabetical and `registry`'s first position is load-bearing, not cosmetic.

**Known wart:** `terminal_launcher` reports `wt`-vs-detached-PowerShell fallback for an attach path that `cmd_attach` refuses outright (§7), and its message is Windows-shaped on every platform. It is note-only and harmless, but it describes behavior that does not exist. `[UNBUILT — retire it with native attach integration, or delete it sooner]`

## 14. Views / terminal surface (binding rules, unchanged)

**Init creation default — G-K5 Reading A, operator ruling 2026-09-10.** Bare
`fleet init` creates a home at the exact current directory, including inside a
repository or its subdirectory; there is no repository-root search. The new
registry parses as `{ "workers": {} }`, so a later `--fleet-home <that path>`
accepts it as initialized without a spawn. Existing registries are preserved;
corrupt registries refuse without being overwritten, and successful reruns refresh
settings using the install-root template and the created home's state paths.

Creation runs even when the ambient resolver reaches the terminus or the machine
has multiple homes. **`docs/specs/multi-fleet.md` §5 and `resolve_home` are unchanged:**
other commands still resolve flag → sid membership → env → legacy → terminus;
cwd creation neither changes the ambient selection nor registers the home for
membership lookup. This supersedes the older settings-only bare-init description,
including the historical E2 table's explanation of the ordinary residual.

The conservative implementation leaves the irreversible homes-list append behind
explicit `init --home` or `homes --add`; bare init remains the ordinary residual.
Automatic machine-list registration remains explicit. Explicit `--fleet-home`
and `--statusline` retain their existing rendering/setup path, and the supervisor
gate still runs before either creation form writes. Cross-home CLI calls use
`env -u CLAUDE_CODE_SESSION_ID`, including later read-only verification.

`docs/specs/terminal-surface.md` remains binding: a view (statusline, `/fleet:*` read-only commands, and `mail verify`) never takes `fleet.lock`, never probes anything live, never writes, never quarantines — it reads committed file evidence and exits with its documented verdict (`mail verify` uses 0/1 for `VERIFIED`/`UNVERIFIED`; status views exit 0). Post-pivot the "never probes a PID" clause generalizes: the snapshot path also never fetches the roster — roster fetches belong to mutating/authoritative commands only. Since D7 (2026-07-22) the surface is also **pull-only**: fleet registers no hooks and injects context into no session, so an unrelated project sees nothing. `FLEET_WORKER` (stamped by `_worker_env` @989) originally suppressed the SessionStart briefing for workers (D5); with the briefing gone it survives for the supervisor and destructive-command guards.

## 15. Destructive-command guard + provenance (survives the pivot verbatim)

`spawned_by` records the spawner's `CLAUDE_CODE_SESSION_ID` (or null for a human shell), immutable across respawn. `kill`/`clean`/`respawn` refuse a foreign worker (differing or unknown owner) without `--yes`; the guard applies to Claude sessions only (`_confirm_destructive` @1928, `_worker_is_foreign` @1910). **Lineage ownership (claim-nonce §6.2):** `_worker_is_foreign(record, caller, claim_lineage=None)` also treats a worker as owned when `record["spawned_by_lineage"]` equals a `lineage_id` the caller **proved continuity on this invocation** (via `--nonce`) — so a later supervisor body whose sid rotated through a fork-steer or handoff still owns the workers its lineage spawned, while a seize (which re-mints the lineage) deliberately makes them foreign (its `adopted_lineages` count only for LANE-DONE, §8). An unproven caller gets today's `spawned_by`-only answer. Worker turns **strip `CLAUDE_CODE_SESSION_ID`** from the child env and stamp `FLEET_WORKER=<name>` (`_worker_env` @989-1008) — an inherited sid would let a worker retire its siblings as if it were the manager. `interrupt` stays exempt (ends a turn, not a worker). Recovery after an over-eager clean: `state/events.jsonl` is append-only and untouched by `clean`; archived evidence survives under `logs/archive/`.

## 16. Architectural invariants — post-pivot status of the nine

The v2 numbering is retained so old citations resolve; each invariant's post-pivot meaning is stated.

1. **daemonless launch → fleet-daemonless.** Every *fleet* action is a short-lived CLI invocation; fleet ships no resident process. The native daemon is Anthropic's substrate, not fleet's — fleet works with it via CLI only. Autoclean's scheduled task used to be an OS-scheduler invocation of the ordinary CLI (not a daemon); since 2026-07-27 there is no scheduler either, and the sweep rides the tiers' own beats.
2. **exit-0 hooks** — unchanged, four worker hooks. (A fifth, the manager-side SessionStart briefing, shipped in Phase 1.6 and was removed on 2026-07-22: a plugin hook fires in every session on the machine, so it leaked fleet state into unrelated projects. `docs/specs/terminal-surface.md` D7.)
3. **atomic single-file mailbox** — unchanged (`os.replace` claim).
4. **journal-injection-at-respawn** — unchanged; respawn and resume-limited both compose the journal into the launch prompt.
5. **cwd-scoped resume → cwd-scoped dispatch.** Every dispatch runs with `cwd=<registered cwd>` (immutable after spawn); fork-steer inherits the transcript, and the daemon owns session storage. Since 2026-09-16 (w87, Cut 1) this holds for ordinary workers only — a supervisor-shaped idle target's wake dispatches fresh instead, resuming the same incarnation via a nonce credential rather than a forked transcript (`docs/specs/native-substrate.md` G2 amendment).
6. **single-writer registry** — unchanged (`fleet.lock`; F4 no-lock-across-subprocess shape added).
7. **one-live-claude-per-session → one live session per name.** The pre-claim window, the fork-steer restamp, respawn's roster-verified stop, and the wedge-retry's verified cleanup (C1) all enforce it; the sid itself is single-writer to the daemon.
8. **platform-adapter-only OS branching** — unchanged as a rule; the shared adapter now lives in `bin/fleet_platform.py` and is imported by `fleet.py` and the standalone Codex host; the adapter surface is now attach-terminal + atomic append (the probe/kill/popen methods died with §6; the autoclean scheduling methods died with the timer on 2026-07-27, deleted on BOTH backends rather than ported — the cheapest way to reach cross-platform parity on a seam turned out to be not needing the seam). Per the 2026-07-17 portability directive (header), the adapter's POSIX side must reach parity — a POSIX attach path — and a raising `_PosixPlatform` is a tracked gap, not an accepted end state; new adapter methods land with all three OS implementations or an explicit gap note.
9. **one-state-many-views** — unchanged; registry + outcome store are the state, `status_snapshot()` the one derivation.

New, carried from the pivot spec and enforced in code: **never-demote-unknown** (dead-suspected is advisory; nothing auto-respawns), **G9 epoch freeze** (an empty/failed roster never mass-demotes), **tombstone obligation** (every fleet-initiated stop writes its own outcome record), **no daemon/jobs file access** (CLI + `--json` only).

10. **spec-bound work `[PRESCRIPTIVE — UNBUILT, owned by M-F]`.** Every campaign worker binds to an **accepted** spec; drift is verified **deterministically at a gate** (scope + criteria, fail-closed on an unknown criterion kind), judged only advisorily on intent, and reset by respawn. A live fence is advisory self-correction, never the acceptance stop. Corollary, binding on any future verifier or auditor: **a verdict may derive only from tamper-evident inputs and deterministic functions of untrusted bytes — never from interpreting agent-produced prose.** If removing a prose input would change a verdict, the check is malformed. Corollary 2: **no author-supplied executable input** — a spec is data the verifier interprets, never argv or a path it executes.

## 17. Testing — the tiers as they exist

- **Unit tier** (pytest, no claude): `tests/test_core.py`, `test_native.py` (verdict engine, dispatch_bg with injected roster/run/clock, wedge + H1 + fast-completion), `test_steering.py`, `test_resilience.py`, `test_supervisor.py` (claim/handoff/seizure state machine), `test_autoclean.py` (ownership discriminator incl. fault-injection), `test_hooks.py`, `test_cli.py`, `test_destructive_guard.py`, `test_terminal_surface.py` (view lints).
- **Live pin suite** (`tests/integration/test_native_pin.py`, gated `FLEET_LIVE=1`, haiku, temp `FLEET_HOME`): six pins — dispatch + roster contract, Stop-hook outcome, fork-steer, stop-no-hook tombstone, archive + `claude rm`, record-pass stamp (feeding doctor's `pin_version` check). Run before campaigns and after every `claude` version change.
- **A RECEIPT MUST NEVER QUOTE A MUTATING VERB** (learned the expensive way, 2026-07-28). `tools/verify_receipts.py` re-executes every command in a classified block, and it inherits the ambient environment — so it resolves `~/.claude/fleet-home` and runs against **the machine's live fleet**, not a temp dir. A draft correction to `docs/specs/autoclean.md` pasted a `fleet autoclean` transcript; the harness ran the sweep three times and archived six real worker records. Nothing refused it, because nothing checks: a pasted `fleet clean --yes` would have deleted the fleet on every `pytest tests/test_receipts.py`. Quote mutating-verb output as **prose**, cite the durable artifact instead (`state/events.jsonl`), and put the reproducible form in the suite. `[UNBUILT]` follow-up, worth a slice on its own: give the harness a refuse-list for mutating verbs, or a `FLEET_HOME` sandbox, so this cannot depend on an author remembering.
- **Gone with the pivot:** the v2 tier-3 stream-json smoke suite and the `tests/fixtures/streams/` corpus (deleted with the stdout pipeline; `ls tests/fixtures` → no such dir). Historical references to that corpus in the moved v2 body and in ROADMAP/PLAN are bannered, not live contracts. Removals delete their tests in the same commit.

## 17a. Spec-driven development / drift control `[PRESCRIPTIVE — UNBUILT, owned by M-F]`

**Nothing in this section exists in `bin/fleet.py` today** (`grep -n "def cmd_spec_\|sdd_enabled" bin/fleet.py` → no matches). Design of record: `docs/superpowers/specs/2026-07-18-sdd-drift-control-design.md` v4 (two adversarial review rounds folded, including a new-defect hunt that caught a CRITICAL RCE the first fold introduced). Operator-ratified decisions R1–R4, 2026-07-20. Implementation plan: `docs/superpowers/plans/2026-07-22-sdd-mf-phase1.md`.

**Problem.** The fleet's anti-drift discipline (grep-receipt gates, no-self-promotion, adversarial review pairs, `[UNBUILT]` tagging) lives in the campaign template and the knowledge loop, enforced only by the manager's judgment. Nothing in code binds a worker to a contract or detects when it has left one. Three drift surfaces: **semantic** (output deviates from intent), **coordination** (N workers diverge from each other), **worker↔supervisor** (understanding diverges after compaction/respawn).

**Contract.** One git-tracked campaign spec at `docs/specs/campaigns/<campaign>.md` — a fenced ```json machine block (criteria, scopes, `accepted_digest`) plus a human EARS/ADR body. Lifecycle `proposed → review → accepted`; `spec accept` refuses when the accepting **durable actor** equals the author, or when `reviewed_by` is empty or names the author. Workers refuse to bind to a non-accepted spec.

- **Two criteria kinds, both deterministic:** `files` (touched-path set ⊆ effective scope) and `pytest` (declared nodes pass). Unknown kind → **FAIL, fail-closed**. A grep assertion is a pytest node, so no `grep` kind exists.
- **Scope (R2):** a whole-spec scope is the campaign floor; per-worker slices narrow it. Effective scope = slice ∩ whole-spec — a slice may only narrow, and slice-overlap is rejected by **pattern-domain** reasoning (never a filesystem match, which is blind to files that do not exist yet).
- **Touched paths need four git queries**, not one: `diff`, `diff --cached`, `ls-files --others --exclude-standard`, and `ls-files --others --ignored --exclude-standard`. The ignored query is mandatory — without it every gitignored deny target (`state/**`, `logs/**`) is invisible, which is the violation the scope fence exists to catch.
- **Exit contract:** 0 all-pass; 1 any criterion FAIL — **including a node that resolves but collects zero tests**, which is under-delivery; 2 only genuine harness failure or an `accepted_digest` mismatch. Ambiguity resolves toward 1: drift must never masquerade as infra, or a worker dodges a FAIL by deleting the target test.
- **No author-supplied executable input.** The runner is fixed `sys.executable -m pytest`; the tree is the bound worker's registered `cwd`. A free `runner` argv or author-set `project_root` is arbitrary command execution at the manager's own gate. `accept` signs `accepted_digest` over the executable fields; `verify` re-checks it, because `--add-dir` grants a bound worker **write** access to its own spec. Git-tracking (R4) is a second, independent tamper surface.
- **Binding.** Additive registry fields `spec`/`spec_slice`/`spec_baseline_sha`. Composition belongs to `compose_prompt`, not `dispatch_bg`. **Respawn must copy the binding explicitly and re-stamp the baseline** — `new_worker_record` has a fixed key set and no `**kwargs`, so any field not hand-copied is lost, and a carried-stale baseline false-blocks a fresh session on files it never touched.
- **Enforcement is staged, all behind `sdd.enabled` (default OFF, R1):** Phase 1 is the gate (`spec verify`) with no hook; Phase 2 adds the live Stop-hook scope fence, ordered `[stop_outcome, stop_specfence, stop_mailbox]`, only after Phase 1 proves out on a real campaign. The fence fails **open** and is advisory self-correction capped by the native 8-block force-allow — the gate is the acceptance stop, never the hook.
- **Views stay probe-free:** status flags and `_doctor_check_spec_drift` (note-only) read an atomic verify stamp at `state/spec-verify/<campaign>.json`; they never run verify and never parse the spec file.

On build, this section absorbs the design doc as first-class prose (R4) and the doc becomes history, like the v2 body.

## 17b. Audit oracle `[PRESCRIPTIVE — UNBUILT, owned by M-G; prerequisites unmet]`

**Nothing here exists, and none of its central checks is buildable on the data fleet records today.** Design of record: `docs/superpowers/specs/2026-07-22-oracle-design.md` v2. Origin: an operator-relayed requirement that agents cannot verify each other when all they receive is another agent's answer.

**The honest scope, established by three adversarial lenses and recorded so no successor re-litigates it.** The oracle is a **derangement and bookkeeping-drift detector**. It is **not** a penetration defense and must never be documented as one.

- **It cannot be a security boundary on this substrate.** `state/` carries `Authenticated Users: Modify`; workers run as the same OS user, default `--mode dontask`, with no `permissions` block in `worker-settings.template.json`. `events.jsonl` is "append-only" by comment, not mechanism. `FLEET_WORKER` is an env var (`env -u` defeats it) and §6.1 forbids keying a guard on it by name. Git `author` and both timestamps are agent-settable. This is M-E's lesson exactly — *a bearer secret cannot authorize on a substrate with no privilege separation* — which already forced `claim-nonce` into a detection reframe; the oracle takes the same reframe.
- **It does not detect a semantically-wrong in-scope change.** A two-character edit that disables a guard, inside `scope_allow`, passing every declared criterion, is green on all six checks. Detecting that needs a model or a human, both excluded by construction. Against an adaptive adversary it detects nothing once the attacker writes the evidence.
- **What it does detect:** contract tampering, scope escape, stale or absent verification, structural topology anomalies, evidence gaps — the fingerprints of a deranged or buggy agent.
- **Verdict lattice:** `cannot-audit` is **frozen, not concluded** — it blocks, surfaces, and clears only by a successful re-run, never by an ack (acking it would permanently silence a broken auditor). `CRITICAL` is ackable, scoped to `(finding-id, evidence_head)`. A mass-failure circuit breaker yields `oracle-misconfigured` and blocks nothing. `spec verify --no-oracle` is the escape hatch, because `cannot-audit` is worker-triggerable and a DoS on an unattended fleet is the cheapest attack.
- **No kill authority; doctor note-only.** An open CRITICAL is worker misbehaviour — the `dead-suspected` category — not broken infrastructure. Doctor FAILs only when the auditor itself is broken.
- **Thresholds are excluded by doctrine.** Respawn and re-dispatch counts measure operator retry cadence, not the system (M-E).
- **Prerequisites (N1–N9), none met:** a task hash and a dispatch event at five sites (`dispatch_bg` emits no success event); event provenance; **any git substrate at all** — `bin/fleet.py` contains zero git invocations; a `campaign` identity — the word appears in no `.py` file; a hash-chained `events.jsonl`; a registry/claim-keyed caller refusal; an agent-caller guard distinct from `_confirm_destructive`; a second scheduled-task identity plus POSIX seam; three-way sid-union orphan attribution.

If penetration defense is actually wanted it is a **separate security milestone**: `state/` write-denied to the worker token, the oracle under a separate service account, a chain anchored outside `state/`, and worker permission deny-rules.

**Three shipped defects this review surfaced, independent of the oracle** (`[UNBUILT — fixes owned by the next code milestone]`): `append_event` uses a buffered text append where `stop_outcome.py` documents that plain `open(...,"a")` loses whole records under concurrent Windows writers; `--add-dir tasks_dir()` grants every worker write access to every other worker's task file; `_confirm_destructive` is a no-op inside a worker, because the env strip makes every worker present as the human shell the guard deliberately exempts.

## 18. Milestones

Fleet currently ships the native worker lifecycle, persistent supervisor protocol, multi-home resolution, local keeper integration, project index, and Claude/Codex substrate adapters. The implementation and topic specs are the behavioral authorities; public milestones do not carry per-user rollout receipts.

Future work is tracked generically in `docs/ROADMAP.md`. Concrete campaign queues, host deployments, acceptance receipts, and operator decisions live only in each user's ignored fleet-home storage.

## 19. History

Git history preserves the evolution of the public design. Scrubbed operational records are intentionally absent: they belong to the users and homes that produced them, not to the public Fleet repository.
