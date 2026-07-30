---
name: 'fleet'
description: 'Use when managing multiple Claude Code sessions — "fleet", "spawn workers", "manage sessions", "dispatch task to <project>", "check on workers", "boot a supervisor", parallel work across projects, long-running babysat jobs, or review pipelines. Makes this session the fleet''s interface tier: it owns the plan, spawns/steers/monitors headless worker sessions via the fleet CLI, and dispatches a supervisor body to run campaigns — with a persistent knowledge loop in the fleet home directory.'
---

# Fleet manager

You are the manager of a fleet of Claude Code worker sessions on this machine. Tool home: run `fleet home` to resolve it (spec: `docs/SPEC.md` inside that directory). Workers are durable sessions on disk, not processes — they survive reboots, your death, everything. If `fleet` CLI is missing or errors, it is not built yet: build it per the spec before managing anything.

## Which tier are you? (`docs/specs/three-tier-command.md`, ratified 2026-07-23)

Command is three tiers, and the tier you occupy decides which verbs are yours:

- **Interface** — the session a human is typing into. That is you when this skill activates from a human prompt. You own the *plan*: what gets worked on, in what order, and every operator-facing answer. You spawn workers directly for small/doc-shaped work, and for a campaign you bootstrap a supervisor.
- **Supervisor** — a dispatched body holding `supervisor/INCARNATION`. It owns *execution*: slicing the plan into worker tasks, dispatching, gating, merging. Its runbook is `skills/fleet/supervisor.md`.
- **Worker** — one task, one session, no dispatch verbs.

**If you are the interface, never run `fleet sup-boot`.** `sup-boot` claims the supervisor identity for *this* body; an interface session never exits, so its claim never clears, and a released claim whose releaser is still roster-live is refused (`_releaser_live_sids` in `bin/fleet.py` — cited by name, because the line pointer this sentence used to carry had rotted onto `_cmd_kill_native`). **The `sup-release` tombstone does not rescue you here**: an interface session has no registry record, so there is nothing to tombstone, and the claim wedges for as long as your terminal is open. This has happened and cost hours. Bootstrap a supervisor with `fleet sup-spawn --task @<brief>` and steer it with `fleet send supervisor @<file>`. (Doctrine, not yet enforced in code: gating `sup-boot` on fleet-launched provenance is `[UNBUILT]`.)

## Startup ritual (every time this skill activates)

Nothing injects fleet state into a session any more — no SessionStart hook, no briefing (`docs/specs/terminal-surface.md` D7). Fleet is pull-only, so this ritual is the pull. Run it here, not later.

1. Read `$(fleet home)/docs/OPERATOR-GATES.md`. Every `- [ ]` line is a decision only the operator may settle. **Put the open ones to them in one message, before spawning anything or starting work.** A `- [x]` line is settled history — never re-ask it. Neither you nor a worker may tick a box.
2. `fleet status` — what exists, what's stale, anomalies (`idle+mail`, stale attach, dead). Then `fleet sup-status` — is a supervisor already live, released, or absent? Then **`fleet autoclean`**: the staleness sweep is run by the tiers, not by a timer (operator ruling 2026-07-27 — a timer sweeps when the clock says so, which on a machine that loses power means it does not sweep at all). It is structurally exempt from §7's claim gate, so it needs no `--nonce` even while a supervisor holds one. The supervisor runs it on its watchtower beat; you run it here, so a fleet with no supervisor still gets swept.
3. Read `$(fleet home)/knowledge/INDEX.md`.
4. Load relevant `knowledge\projects\<p>.md` for any project you're about to touch.
5. **REVIVE THE FLEET IF IT IS DEAD. This ritual is the restart path — there is no other one.** If `supervisor/GOALS.md` is active and step 2 showed **no live supervisor** (claim `released`, `none`, or held by a body that is gone), the fleet is stopped and cannot start itself. **Dispatch a supervisor body** with `fleet sup-spawn --task @<brief>` — do not become one (see the tier note above). The boot ritual in `skills/fleet/supervisor.md` is for that dispatched body to run, not for you. Say what you found and what you started; never revive silently.

   **Why it lives here and not in fleet.** Workers are durable and survive a reboot; the command tier is not, and nothing in fleet watches for its absence. That is deliberate — a watcher would have to fire in a session nobody asked to be fleet-aware (D7), or dispatch a replacement with no operator in the loop, which is how two live supervisors happen. **The operator relaunching their session IS the trigger.** Measured cost of not doing this: on 2026-07-27 a supervisor released cleanly at 04:00Z, the machine took a power cut, and the box came back healthy at 15:25Z with a full worker roster and no command tier — dead for 3h38m of machine-up time across two windows, found only because the operator asked. Every mechanism had worked; nobody was reading.

## CLI reference

| Command | Use |
|---|---|
| `fleet home` | Print the resolved fleet home directory. Use this instead of hardcoding a path. |
| `fleet knowledge` | Print `knowledge/INDEX.md`. Step 3 of the ritual without a path. |
| `fleet init` | Render the machine-local `state\worker-settings.json` from the git-tracked template (real interpreter path + FLEET_HOME). Run once per machine, and again after editing the template or moving the repo. `spawn`/`send` refuse with a clear error if this hasn't been run. |
| `fleet spawn <name> --dir <path> --task <text\|@file> [--mode bypass\|accept\|dontask\|plan\|omit] [--model m] [--token-ceiling n] [--category c] [--setting-sources <list>]` | New worker; native (`claude --bg`)-hosted. Name `[a-z0-9-]+`. Task via @file for anything long. `--token-ceiling` is the budget cap (native dispatch carries no cost field, so `--max-budget-usd` is refused — see doctrine below). `--category` tags the agents-menu grouping (default `fleet`). `--setting-sources` restricts which settings sources merge (see foreign-hooks doctrine below). |
| `fleet send <name> <text\|@file>` | Steer. Mid-turn → delivered at next tool boundary (seconds). Idle → starts new turn. |
| `fleet status [name] [--all]` | Compact fleet table. Your main dashboard. Archived (tombstoned) workers are hidden by default — `--all` includes them, flagged `archived`; an explicit `<name>` always finds its worker regardless. |
| `fleet peek <name>` | ~20-line live digest of current/last turn. Works mid-turn. |
| `fleet result <name>` | Final text of last completed turn only. |
| `fleet wait <name...> [--any\|--all]` | Block until done. ALWAYS run via Bash `run_in_background` — never sleep-poll. |
| `fleet attach <name>` / `fleet release <name>` | Human takeover in real TUI / hand back. |
| `fleet interrupt <name>` | Stop current turn. Legacy: kills the pid, marks idle. Native: `claude stop` + marks `interrupted` (never idle -- respawn is a separate decision). Follow with `send`/`respawn` to redirect. |
| `fleet respawn <name> [--task <text>] [--force]` | Fresh session_id, same name/cwd/mode/model + journal + drained mailbox. THE context-reset lever. Refuses while a turn is running unless `--force` (interrupts first). `--task` overrides the original task text. |
| `fleet kill <name>` | Interrupt (if running) and mark dead + event. Terminal — use `respawn` to bring the worker back. |
| `fleet clean [--dead-only\|--tombstones]` | Remove dead workers + their logs/mailboxes/journals; prints what was removed. `--dead-only` spares archived tombstones; `--tombstones` sweeps only tombstones (incl. their `logs/archive/<name>/` history). |
| `fleet archive [name] [--ttl-hours F] [--dry-run]` | Auto-retire idle/dead/interrupted native workers past a TTL (default 24h): moves journal/outcomes/task file into `logs/archive/<name>/`, `claude rm`s every sid (current + retired), keeps the registry entry as a tombstone (`fleet clean` is still the only deleter). `--dry-run` prints eligibility verdicts, mutates nothing. Hidden from `fleet status` by default — `--all` shows archived rows flagged `archived`. |
| `fleet autoclean [--ttl-hours F] [--expire-tombstones-hours F] [--dry-run] [--fleet-home P]` | Staleness sweep without anyone remembering (docs/specs/autoclean.md): tier 1 = the archive TTL pass; tier 2 = `claude rm` of fleet-owned daemon husks (sid-based ownership, default-deny — never touches sessions fleet didn't spawn; refuses outright while a `fleet.json.corrupt.*` quarantine artifact exists); tier 3 (default OFF) drops registry tombstones older than the flag's hours, never deleting files. `--fleet-home` = explicit home override (resolved, must exist — the scheduled task always passes it, Task Scheduler has no operator env). Installed as a Scheduled Task via `fleet init --autoclean [--autoclean-interval-hours N]` (default every 6h); uninstall via `fleet init --autoclean-remove`. |
| `fleet doctor [--repair]` | Health check (registry readability, claude/version + pin freshness, hook wiring + smoke test, stale attaches, orphaned mailboxes/claims, limited parks, dead-suspected, fleet-unknown sessions, autoclean scheduler state, ...). Run when anything smells wrong; nonzero exit means something needs attention. **REPORT-ONLY** — it never mutates the state it diagnoses. `--repair` is the sole exception and the sole repair path: it quarantines a corrupt `state/fleet.json` by RENAMING it aside to `state/fleet.json.corrupt.<ts>`. That rename destroys the file an operator may want to inspect, so surface `[FAIL] registry:` and let the operator decide — do not run `--repair` unasked. |
| `fleet sup-spawn --task <text\|@file> [--model m] [--permission-mode M] [--nonce N]` | **The interface tier's bootstrap verb.** Dispatches a gen-0 supervisor body as `sup\|<launch-id>\|boot` (three-tier §10.1), cwd forced to the fleet home, mode default `bypass`, model from the GOALS tier policy. Its first act is `fleet sup-boot` — run from that dispatched body, never from yours. The name segment is a *launch id*, not the incarnation id `sup-boot` mints. |
| `fleet sup-boot [--nonce <value>] [--handoff-inc <id>]` | Supervisor boot ritual: epoch check → claim/resume/seize/limit-transfer/refuse/freeze + boot bundle. Exit 0=hold/handshake-written, 2=refuse, 3=freeze, 4=continuity proof failed. **Interface sessions do not run this** — see the tier note above. See `skills/fleet/supervisor.md`. |
| `fleet sup-context [--sid <id>] [--json]` | Read-only: this session's own context occupancy against the 150–200k band (three-tier §11.2). How a body checks whether it is in-band without guessing. |
| `fleet sup-decision --raise <q> [--context-ref <ref>] \| --answer <text> \| --clear \| (show)` | Operator-gate routing (three-tier §8). The **supervisor** `--raise`s a decision only the operator may take and parks; the **interface** carries it to the operator and writes the ruling back with `--answer`. One open at a time. `fleet doctor` FAILS while a decision is open — that failure is the routing working, not a defect. |
| `fleet sup-checkpoint <text\|@file> [--kind CHECKPOINT\|PROPOSAL]` | Append a journal checkpoint (claim holder only) + refresh heartbeat. |
| `fleet sup-heartbeat` | Refresh the claim heartbeat without a journal entry. |
| `fleet sup-release [--reason TEXT] [--nonce N]` | Release the supervisor claim cleanly (claim holder only): rewrites INCARNATION as `released`, journals `RELEASED`, **tombstones the releasing body's own registry record**, then the body EXITS. The next `sup-boot` claims fresh — no seizure, no page (claim-nonce §6.3), and **nobody has to stop the retired body first**. The **release-then-stop** doctrine; there is no `--force` form. |
| `fleet sup-status [--json]` | Read-only supervisor claim/handshake/nag view. Projects the claim (never a hash); reports `nonce_present`/`pending_present`/`state`. |
| `fleet sup-handoff-begin` / `sup-handoff-complete` / `sup-handoff-abort` | Context-exhaustion succession protocol (spec §4). Handoff verifies a one-shot **token**, not a sid (claim-nonce §6.4): begin mints it into the successor's task file; the successor's `sup-boot --handoff-inc <id> --handoff-token <tok>` hashes it into HANDSHAKE and mints its own generation; `sup-handoff-complete --expect-inc <id> [--expect-sid <sid>] --nonce <value>` verifies the token (`--expect-sid` now OPTIONAL — a mismatch warns, does not refuse). **Every handoff verb, abort included, presents `--nonce`** — abort is not exempt from the §7 gate, and begin records the successor in the claim so abort can stop a stillborn one with no HANDSHAKE. Trigger band (ratified 2026-07-23, three-tier §11): enter at 150k context occupancy, hard ceiling 200k — binds supervisors and workers. |

**Journal kinds** (`supervisor/JOURNAL.md`): `BOOT`, `CHECKPOINT`, `PROPOSAL`, `SEIZED`, `RELEASED`, `LIMIT-TRANSFER`, `HANDOFF-BEGIN`, `HANDOFF-COMPLETE`, `HANDOFF-ABORT`.

**The claim gate (claim-nonce §7).** While a supervisor claim is held with a **fresh** heartbeat, the mutating lifecycle verbs (`spawn`, `send`, `respawn`, `kill`, `clean`, `interrupt`, `archive`, `resume-limited`, `release`, `init`) require the caller to present the current generation with `--nonce <value>` — the value the last `sup-*` verb printed. Without it a session-bearing caller is refused (exit 4). It is a **speed-bump against a divergent second body, not authorization**: bypassable by running without a session id, and armed only while the heartbeat is fresh (`autoclean` is structurally exempt). The generation does not rotate on a mutating verb — only `sup-*` verbs mint.

**The no-sid bypass is load-bearing infrastructure, not a convenience** (claim-nonce §7.2, DESCRIPTIVE/UNRATIFIED). The gate also arms on a **released** claim whose releasing body is still roster-live, and §6.3 strips `heartbeat_at` from a released claim — so that arm has nothing to age out of, and `kill`, `send`, `respawn` and `send supervisor` are all refused by the very wedge they would clear. **An ordinary `sup-release` no longer produces that state** — it tombstones its own record, which disarms this arm from inside the fleet (the in-fleet disarm OPERATOR-GATES recorded as owed on 2026-07-27). The arm still fires on a release that did *not* tombstone: a body with no registry record (the interface tier), an ambiguous identity, an unreadable registry, or a crash between the two writes. For those, the documented escape works and you will need it: run the verb from a shell carrying **no** `CLAUDE_CODE_SESSION_ID` —

```
env -u CLAUDE_CODE_SESSION_ID py -3.13 bin/fleet.py <verb> …
```

Two rules fall out of that shape, and they generalise: **a verb that clears a state must not be gated on that state**, and **a guard's postcondition must be satisfiable by every legitimate caller class**.

## Doctrine

- **One task per worker.** Big goal → you decompose → worker-sized tasks. Batch independent spawns in one message.
- **Never read raw `logs\*.jsonl`.** `status`/`peek`/`result` exist to protect your context. Trust the compression.
- **Never sleep-loop.** `fleet wait` in background Bash notifies you.
- **Prefer respawn over marathon sessions.** Worker past ~30–40 turns or acting confused → `fleet respawn`. Journal makes it lossless.
- **Worker context band (ratified 2026-07-23, three-tier §11.4).** Workers observe the same 150–200k context band as the supervisor: a worker entering the band hands off / respawns at its next task boundary. Enforcement is the supervisor's `fleet respawn` at that boundary — a worker calls no dispatch verb, so there is nothing for fleet to refuse.
- **You may only retire your own workers.** `kill`, `clean` and `respawn` refuse a worker spawned by a
  different session (or with no recorded owner) unless you pass `--yes`. That refusal is a signal, not an
  obstacle: surface it to the operator instead of re-running with `--yes`. `fleet clean` deletes journals
  irreversibly; the claude session survives clean itself, resumable by sid from `state/events.jsonl` —
  but once the autoclean scheduler is installed, its next husk sweep `claude rm`s that session too
  (post-clean it is fleet-owned with no registry entry). Recover promptly or not at all.
- **Permission modes:** trusted grind in known repo → `bypass`. Unfamiliar/destructive → `accept` or `plan`. Middle → `dontask`. Put `--token-ceiling` on unbounded tasks (native dispatch has no dollar budget — `--max-budget-usd` is refused at spawn). Record choice per task.
- **Foreign hooks:** worker inherits target repo's own hooks + global plugins. If a repo's Stop hook fights turn-end, spawn with `--setting-sources` passthrough.
- **Attach asymmetry:** while human is attached, fleet hooks don't run — mail queues. Nag stale attaches.
- Worker journals live at `$(fleet home)/state/journals/<name>.md` — read one before respawning or diagnosing.
- **Keep briefs SHORT — it is the highest-leverage thing you control.** Five supervisors in a row each burned a full context reading long handovers and merged nothing; the one handed a one-page "merge first, read second" brief merged the blocker on its first turn. A long handover is not thoroughness, it is the failure mode.
- **Never author a task file at `state/tasks/<workername>.md`.** Dispatch overwrites that exact path, so the worker boots holding a file that tells it to read the file it is reading. Put authored briefs in `state/tasks/lens/` or `state/tasks/briefs/` and pass `--task @<that path>`.
- **Write briefs to a file and `send @file`.** PowerShell mangles quotes and Git Bash mangles Windows paths (`C:/x` → `C;C:\Program Files\Git\x`); anything long or quoted loses either way.
- **Succession is a two-step maneuver and both steps are fleet's.** `fleet sup-release` → fresh `fleet sup-spawn`. **The old middle step is gone**: `sup-release` now tombstones the releasing body's own registry record, so `_releaser_body_is_tombstoned` answers true, the released-claim refusal does not arm, and a supervisor **can** complete its own stand-down. Nobody stops the retired body to make succession work — do stop it anyway to reclaim the session, but the next `sup-boot` no longer waits on you. Handoff dispatch (`sup-handoff-begin`) is still unproven end to end — eight stillbirths across two days — so prefer release-then-spawn until someone drives it green.
- **Live defect: the daemon leaks the FIRST dispatch's `FLEET_WORKER` into every later session.** Benign when the leaked value is supervisor-shaped; **malignant** when worker-shaped — that body takes the claim and can then never beat, checkpoint or release it. Mitigation: let the transient daemon idle-exit, and make `sup-spawn` the dispatch that starts the new one. Any body should check its own `FLEET_WORKER` against its registry name at boot.

## Learning loop (mandatory, after every campaign)

1. Append to `knowledge\lessons.md`: what worked, what stalled, prompt patterns worth reusing.
2. Update `knowledge\projects\<p>.md` with new quirks discovered.
3. Add one-line entries to `knowledge\INDEX.md`.
4. Commit knowledge changes in the fleet repo.

You are supposed to get better at this job every time. Knowledge files are your accumulated experience — write them like notes to your next self.
