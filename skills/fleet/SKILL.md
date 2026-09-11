---
name: fleet
description: Use for fleet planning, worker dispatch, supervisor operations, handoff, and review.
---

# Fleet operating manual

Use this skill when managing multiple Claude Code or Codex sessions. Resolve the
active home with `fleet home`; do not hardcode a home path. This machine has two
fleet homes, so `--fleet-home <path>` is required whenever a command selects a
home.

## Tiers

- Interface: the operator's own persistent session; decide intent and choices; never recycle this session.
- Supervisor: a swappable body; split work into lanes, dispatch, review, land, and close waves.
- Worker: a long-lived session on its own branch; own the assigned work, subagents, and structured result.

Output is compressed. Facts, numbers, paths, commands. No preamble, no recap, no
narration of tool calls, no praise, no hedging, no essays. One line per finding.
A journal checkpoint is at most three model-written lines plus computed state. A
lane report is the structured result plus at most 40 lines. Quote errors exact,
shortest decisive line only.

## You are the interface

The interface is a role stored in the fleet home, not an identity stored in a
conversation. Any session may become it after `fleet init` creates a fleet in a
repository or directory, and any fresh session may continue it from home state.
The role does not assume a model; choose the model as the operator directs.
Store operator preferences in the repository's per-repo memory directory, not
in the fleet home or the interface state files.

The interface state lives in the selected home. Read and append
`state/interface/board.md` (at most 30 lines: supervisor state, lanes in flight,
last `THROUGHPUT`, pending operator rulings with their task files, and the last
relayed wave) and append one line per relay, ruling, wake, or spawn to
`state/interface/log.md`. Every interface action appends to the log. These
files belong to the interface-state implementation; this manual only defines
the ritual that reads and appends them.

### Become the interface

After `fleet init` in a repository or directory, execute these steps:

1. Register the session with `fleet interface-register`.
2. Read `state/interface/board.md` from the selected fleet home.
3. Run `fleet sup-status`.
4. Run `fleet sup-guard` and follow its verdict.
5. List `state/inbox/` and read each pending item that belongs to this role.
6. Report exactly five lines: home and role, supervisor state, lanes in flight, last throughput and relayed wave, and pending rulings with the next action.

### Continue as the interface

In a fresh session with no prior conversation, execute these same steps from
the selected fleet home:

1. Register the session with `fleet interface-register`.
2. Read `state/interface/board.md` from the selected fleet home.
3. Run `fleet sup-status`.
4. Run `fleet sup-guard` and follow its verdict.
5. List `state/inbox/` and read each pending item that belongs to this role.
6. Report exactly five lines: home and role, supervisor state, lanes in flight, last throughput and relayed wave, and pending rulings with the next action.

### Interface rules

- Never run `sup-spawn` over a live supervisor body; run `fleet sup-guard --fleet-home <path>` first. Only the interface acts on `DISPATCH` with `sup-spawn`. For `WAKE`, `sup-guard --do` re-verifies and sends `@supervisor/briefs/wake.md`; it never spawns. `PAGE` needs an interface report; `OK` means a fresh heartbeat with a live busy or idle body and needs no page or wake.
- Never tick an operator gate; carry open decisions to the operator and record the ruling with its task file.
- Ask the operator before every destructive verb, including `kill`, `clean`, `archive`, repair, release, retirement, and home registration changes.
- When more than one home is listed, pass `--fleet-home <path>` on every mutating verb.
- Treat a `KEEPER:` page as an observation: read the board, run `fleet status`, `fleet sup-status`, and `fleet sup-guard`, then follow the guard; page the operator on `PAGE` or ambiguity. `supervisor limited` means wait for the recorded roster horizon; do not wake or spawn around that limit. The keeper pages it once until that horizon.
- `bin/fleet_keeper.py --once --fleet-home <PATH> ...` accepts repeatable homes; it observes, wakes, and pages each independently, prefixes every page/wake line with that home's statusline tag, and stores dedup state under that home's `state/keeper/last-page.json`.
- Treat a `SUPERVISOR:` line as a graceful generation handoff: acknowledge it, read `fleet sup-status --json`, record the transfer, and use the guard before any stillborn-successor dispatch.
- Relay every `THROUGHPUT` line and offer one idea per wave; record the relay in the interface log.

## Startup

1. Read `$(fleet home)/docs/OPERATOR-GATES.md`; ask the operator about every open decision before dispatching or changing work.
2. Run `fleet status`, `fleet sup-status`, and `fleet autoclean`.
3. Read `$(fleet home)/knowledge/INDEX.md` and the relevant project note before touching a project.
4. If the active campaign has no live supervisor, run `fleet sup-spawn --task @<brief>`; the interface never runs `sup-boot`.

## Dispatch

- Pass `--setting-sources project,local` to worker and supervisor dispatches unless the operator specifies another supported source list.
- Pass `--fleet-home <path>` on every command that selects a home; never rely on an ambiguous default between the two homes.
- Select a permission mode from `bypass`, `accept`, `dontask`, `plan`, or `omit`; use the narrowest mode that lets the task complete.
- Keep at most 3 live workers host-wide, counting Claude and Codex workers together.
- Dispatch only when at least 1.5 GB of memory is available.
- Give each lane a disjoint write set, its branch snapshot, a bounded task, and a structured result format.
- A lane works on the snapshot it received; do not assume later changes are present.
- Codex workers cannot commit; the supervisor or interface lands their changes.

## mcx worker control

- Run `mcx spawn` detached with no `--wait`; save the worker ID and keep its logs in files.
- Run one observer per lane; break its loop when `mcx result` returns anything other than 2 (`2` live, `0` done, `1` stopped or unknown).
- Re-arm the observer after every `mcx steer`; steering starts a new run.
- Use `gpt-5.6-luna` by default; use Astra only by exception and run at most one Astra lane at a time.
- Do not use mcx to commit, steer unrelated workers, or create a second worker for a lane without an explicit split.

## CLI verbs

Each line below is derived from `build_parser()` in `bin/fleet.py`.

- `fleet home [--tag]`: print the resolved home or its statusline tag.
- `fleet knowledge`: print `knowledge/INDEX.md`.
- `fleet homes [--add PATH|--retire PATH]`: list registered homes or append one add/retire record.
- `fleet init [--home PATH] [--statusline] [--chain] [--force]`: initialize a home and optionally register it or install its statusline.
- `fleet spawn NAME --dir PATH --task TEXT`: dispatch one worker with its mode, model, budget, category, settings, and context options.
- `fleet status [NAME] [--json] [--stale-ok] [--all]`: show worker state, optionally including archived rows.
- `fleet peek NAME [-n LINES]`: print a bounded recent event digest.
- `fleet result NAME`: print the last completed turn's result.
- `fleet wait NAME... [--any|--all] [--timeout SECONDS]`: wait for one or more turns to finish.
- `fleet send NAME MESSAGE`: deliver a worker message or start its next turn.
- `fleet interrupt NAME`: stop the worker's current turn.
- `fleet attach NAME [--force]`: attach an interactive terminal to a worker.
- `fleet release NAME`: release an attached worker to idle.
- `fleet respawn NAME [--task TEXT] [--force] [--yes]`: start a fresh session while retaining the worker identity and recorded brief.
- `fleet resume-limited [NAME] [--force-now]`: resume workers whose usage horizon permits it.
- `fleet kill NAME [--yes]`: interrupt a worker and mark it dead.
- `fleet clean [--dead-only|--tombstones] [--yes]`: remove eligible dead records and their disposable artifacts.
- `fleet archive [NAME] [--ttl-hours HOURS] [--dry-run]`: tombstone terminal native workers past the TTL, or preview eligibility.
- `fleet autoclean [--ttl-hours HOURS] [--expire-tombstones-hours HOURS] [--dry-run]`: run archive, daemon-husk, and optional tombstone-expiry maintenance.
- `fleet index init [--path PATH]`: create and build a project symbol index.
- `fleet index build [--path PATH] [--force]`: build or rebuild an existing symbol index.
- `fleet index update [--path PATH] --files PATHS`: refresh named index files.
- `fleet index status [--path PATH]`: show index counts and stale shards.
- `fleet q [QUERY] [--outline PATH] [--src] [--path GLOB] [--kind KIND] [--limit N] [--no-refresh]`: query the project symbol index.
- `fleet doctor [--repair]`: run health checks; use `--repair` only when the operator authorizes quarantine of corrupt state.
- `fleet sup-boot [--sid SID] [--nonce VALUE] [--handoff-inc ID] [--handoff-token TOKEN]`: claim or resume supervisor duty and emit the boot bundle.
- `fleet sup-spawn --task TEXT [--model MODEL] [--permission-mode MODE] [--setting-sources LIST] [--nonce VALUE]`: dispatch a gen-0 supervisor body.
- `fleet sup-checkpoint BODY [--kind CHECKPOINT|PROPOSAL] [--nonce VALUE]`: append a supervisor journal checkpoint and refresh its heartbeat.
- `fleet journal-roll`: roll older supervisor journal entries into the archive.
- `fleet interface-register`: register the current tmux pane as the interface.
- `fleet wave-close --base SHA --changelog TEXT [--nonce VALUE]`: close one wave by reaping, flooring, accounting, landing, pushing, and notifying.
- `fleet sup-heartbeat [--nonce VALUE]`: refresh the supervisor claim heartbeat without a journal entry.
- `fleet sup-release [--reason TEXT] [--nonce VALUE]`: release the supervisor claim and stop the releasing body.
- `fleet sup-status [--json]`: read supervisor claim, handshake, and handoff state.
- `fleet sup-guard [--do] [--json]`: verify the two-live-body guard: fresh heartbeat + live busy/idle PID → `OK` (no page or wake), stale + live idle PID → `WAKE <body>`, stale + no live PID → `DISPATCH`, fresh + no live PID or unreadable registry/roster → `PAGE`. Existing ambiguity checks still page, and a live body never permits `DISPATCH`. `--do` re-verifies and sends the wake brief only on `WAKE`; `OK` and `PAGE` perform no action. `DISPATCH` pages the interface, which alone owns `sup-spawn`; neither guard nor keeper spawns.
- `fleet sup-context [--sid SID] [--json]`: report this session's context occupancy against its tier band.
- `fleet sup-decision [--raise QUESTION|--answer TEXT|--clear] [--context-ref REF] [--json] [--nonce VALUE]`: route an operator-only decision.
- `fleet sup-notify TEXT [--tmux-session SESSION] [--window WINDOW] [--dry-run] [--nonce VALUE]`: notify the interface through its tmux window.
- `fleet sup-handoff-begin [--model MODEL] [--permission-mode MODE] [--nonce VALUE]`: dispatch the handoff successor.
- `fleet sup-handoff-complete --expect-inc ID [--expect-sid SID] [--nonce VALUE]`: verify the successor handshake and transfer the claim.
- `fleet sup-handoff-abort [--successor-sid SID|--successor-inc ID|--retire-all] [--force] [--nonce VALUE]`: stop or retire a pending successor and resume duty.

## Supervisor guard and generations

- Present the latest printed `NONCE` to every mutating verb that accepts `--nonce`; do not invent or reuse an earlier generation. The claim-holding verbs that accept it are `sup-boot`, `sup-spawn`, `sup-checkpoint`, `sup-heartbeat`, `sup-release`, `sup-decision`, `sup-notify`, `wave-close`, and the three `sup-handoff-*` verbs; the worker verbs `init`, `spawn`, `send`, `interrupt`, `release`, `respawn`, `resume-limited`, `kill`, `clean` and `archive` accept it too. Omitting it on one of these is refused as a continuity failure naming a second body, which reads like an incident and is not one.
- Treat `sup-boot` exit 0 as a held or transferred claim, exit 2 as refusal, exit 3 as freeze, exit 4=continuity refusal, and exit 5 as handoff refusal.
- Reconcile `fleet status` outcomes before dispatching; do not treat a limited worker as dead.
- Context bands are supervisor 350–400k and worker 250–300k; the supervisor enters its band at **350k** and reaches its hard ceiling at **400k**, while the worker enters its band at **250k** and reaches **300k**.
- Freeze and page the operator when claim evidence is ambiguous; never seize or mass-respawn on an ambiguous snapshot.
- Keep journal checkpoints claim-bound and concise; use `sup-checkpoint` for durable working state.

## Wave boundary

Run `fleet wave-close --base <sha> --changelog @<file>` at the wave boundary. Reserve about 12 minutes, configure a git identity, and retry only after inspecting a failure because the operation is not idempotent across failure.

## Handoff

When approaching a context band, checkpoint, notify the interface with `sup-notify`, and run `sup-handoff-begin`; it dispatches the successor itself. The successor boots with its token, then the current body runs `sup-handoff-complete`. Run `sup-release` only when the handoff is stillborn, then stop.

## Safety

Use `env -u CLAUDE_CODE_SESSION_ID` when operating on another home. Confirm `fleet home --fleet-home <path>` resolves to the intended initialized home before other commands. Keep reports at `docs/lanes/<name>.md` on the lane branch and journals at `state/journals/<name>.md`.
