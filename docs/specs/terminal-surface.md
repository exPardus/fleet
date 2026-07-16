# Spec: Terminal surface (Phase 1.6) — fleet inside the Claude Code TUI

**Status:** ready-for-build (design approved 2026-07-09, Altai)
**Inherits:** SPEC.md architecture + numbered invariants, ROADMAP.md principles (esp. #1 one-state-many-views, #2 daemon-is-additive).
**Independent of:** Watchtower (Phase 2), Web UI (Phase 4). Buildable any time after Phase 1.

## Goal

Fleet is visible and operable from inside the manager's Claude Code session without typing `fleet status` by hand: an always-on statusline, `/fleet:*` slash commands, a session-start briefing, all packaged as an installable plugin. Pure UX and packaging — **no new fleet capability, no new state, no new daemon.**

## Scope

**In:** a read-only snapshot function + `--json`/`--stale-ok` flags on `fleet status`; a statusline script; a `commands/` set; a SessionStart hook; a `.claude-plugin/plugin.json`; `fleet init --statusline`.

**Also in (doc deliverables):** ROADMAP gains **Phase 1.6 — Terminal surface** (after Portability, independent of Watchtower); SPEC §3's repo-layout block gains the new paths; SPEC gains a short §15 pointing at this stub. No SPEC body rewrite, no M1–M5 change.

**Out:** any change to worker lifecycle, registry schema, hooks that run inside workers, or the launch path (except one env stamp, §4.6). No interactive TUI (not supported — §2). No new surface state.

## Fixed constraints

### Platform facts (verified against Claude Code 2.1.202+, 2026-07-09)

These are the constraints the design is built on. A builder must not assume otherwise.

- **`statusLine` is read-only.** No click handling, no keyboard events, no widgets. The only clickable affordance is an OSC 8 hyperlink, and only in terminals that support it (iTerm2, Kitty, WezTerm). **There is no supported way to render an interactive panel or TUI inside the Claude Code interface.** "Interactive fleet control" therefore means: statusline displays, slash commands act, `fleet attach` opens the real TUI in its own window.
- **`statusLine` re-runs event-driven** (after each assistant message, after `/compact`, on permission-mode change, on vim-mode toggle) plus optionally every `refreshInterval` seconds (minimum 1). It is a hot path.
- **stdout is rendered line-by-line**; multi-line is supported; ANSI colour escapes are supported.
- **A plugin CANNOT ship a `statusLine`.** Plugin `settings.json` accepts `agent` and `subagentStatusLine` only. A fleet statusline must be installed into the user's `~/.claude/settings.json`. This is why §4.7 exists.
- **Slash commands** are markdown with frontmatter (`description`, `argument-hint`, `allowed-tools`, `model`, `disable-model-invocation`, …). Inline shell output via `` !`cmd` `` is substituted **at prompt-expansion time, before the model sees the prompt** — no permission prompt, no confirmation, no undo. `$ARGUMENTS`, `$1`, `$N` interpolate arguments.
- **SessionStart hook** emits `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}` (≤10,000 chars), with `source` matchers `startup | resume | clear | compact`.

### Architectural constraints

- **stdlib only, no pip deps** (SPEC §14). `fleet_statusline.py` and the SessionStart hook obey the same rule as `fleet.py`.
- **No view writes.** Nothing in this phase writes `state/fleet.json`, `state/events.jsonl`, or takes `state/fleet.lock`. The single exception in the whole phase is `fleet init --statusline` writing `~/.claude/settings.json` — outside `state/`, once, explicitly, with a backup.
- **No view probes.** No surface here calls `PLATFORM.get_process_info` or spawns any subprocess on a refresh path.
- **One derivation, many entry points.** All four surfaces read `fleet.status_snapshot()`. The statusline **imports** it rather than shelling out, so registry-schema knowledge stays inside `fleet.py` and the additive-schema rule (SPEC §4) binds exactly one reader.
- **Views degrade, never fail.** A view exits 0 on every error path and prints degraded output. It never mutates state to repair itself (§5).
- **No OS branching outside the platform adapter** (invariant 8). The lint suite is extended to scan the new files.

## Decisions

<!-- ts-readonly-hot-path -->
**[SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13]** The rule itself (a view never probes, mutates, or contends for the lock on a hot path) stays binding. What's superseded is the cited mechanism: `PLATFORM.get_process_info` / the Windows PowerShell probe is going away with PID-liveness (see `docs/SPEC.md` §6, `docs/specs/portability.md`); a native-substrate `status_snapshot()` must stay just as probe-free against whatever the daemon-roster equivalent turns out to be. See `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §3 and `docs/specs/native-substrate.md`.

**D1 — the hot path is probe-free, lock-free, write-free.** `fleet status` today recomputes status (spawning one `PLATFORM.get_process_info` subprocess per working worker) and writes the registry under `fleet.lock`. A statusline firing after every assistant message cannot do either: it would contend with a live `respawn` mid-rotation (invariant 6) and make a derived view a writer (invariant 9). Therefore a new read-only path, `fleet.status_snapshot()`, reads `fleet.json` + counts `mailbox/*.md` and stops.

This is **not** a PowerShell-cost workaround. On Linux the probe is a `/proc/<pid>/stat` read costing microseconds and the design would be identical — the hazard is *mutation from a view* and *lock contention on a hot path*, both OS-independent. The Windows PowerShell probe is already correctly quarantined inside `_WindowsPlatform.get_process_info` (`bin/fleet.py`), enforced by `TestPlatformAdapterBoundary`; nothing here needs it moved.

<!-- ts-stale-honesty -->
**D2 — the statusline never asserts liveness it did not probe for.** `--stale-ok` returns each worker's **last-committed** status plus `stale_seconds` derived from `last_activity`. A `working` row untouched for 40 minutes renders `working~40m` dimmed. It is never silently relabelled, and never presented as freshly verified. `fleet status` (no flag) remains the authoritative, recomputing command — **[SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13]**: "probing" here names the PID-probe recompute that native dispatch replaces with a daemon-roster query; the D2 honesty rule (never assert unverified liveness) is unchanged.

<!-- ts-mutating-commands -->
**D3 — read-only commands inline; mutating commands go through the model.** `` !`cmd` `` executes at prompt-expansion time with no permission prompt and no undo. `fleet kill` is terminal (only `respawn` exits `dead`) and `fleet clean` deletes logs, journals and mailboxes. A typo in an inline-exec `/fleet:kill` is unrecoverable.

- **Inline `` !` `` (read-only):** `/fleet:overview`, `/fleet:status`, `/fleet:peek`, `/fleet:result`, `/fleet:doctor`.
- **Prompt templates the model executes via Bash (mutating):** `/fleet:spawn`, `/fleet:send`, `/fleet:interrupt`, `/fleet:respawn`, `/fleet:kill`, `/fleet:clean`, `/fleet:attach`, `/fleet:release`, `/fleet:resume-limited`.

Direct control is preserved — `/fleet:kill pmbot` still kills `pmbot` — it merely passes the ordinary permission prompt on the way. Both classes call the same `fleet.py` code paths; there is no parallel logic. This mirrors the Phase-4 `<!-- webui-readonly -->` decision: derived views do not mutate, and the mutating surface stays the lock-guarded CLI.

**Enforced by test, not convention:** a lint asserts no mutating command file contains `` !` ``.

<!-- ts-corrupt-registry -->
**D4 — a view reports registry corruption; it does not quarantine.** SPEC §11 requires the single writer to quarantine an unparseable `fleet.json` to `fleet.json.corrupt.<ts>`, append a `registry_corrupt` event, and exit 1 loudly. A view must do **none** of that: quarantine is a write, and a statusline refiring every 10 s would quarantine in a loop, shredding operator evidence. Views print `⚑ fleet: registry unreadable` and exit 0. The next real `fleet` command performs the quarantine. Direct consequence of invariant 6.

<!-- ts-worker-suppression -->
**D5 — the SessionStart hook suppresses itself inside workers.** A globally-enabled fleet plugin fires its SessionStart hook in **every** Claude Code session on the machine, including every worker turn — injecting a fleet briefing into worker context, wasting tokens and confusing the worker about its role. Guard: `launch_turn` stamps `FLEET_WORKER=<name>` into the child environment; the hook returns empty context when it sees that variable. This is the one `fleet.py` change outside the read path.

<!-- ts-statusline-install -->
**D6 — `fleet init --statusline` is opt-in and refuses conflicts.** Because a plugin cannot ship a `statusLine` (platform fact above), installation is an explicit, separate step: back up `~/.claude/settings.json`, merge the `statusLine` key without disturbing siblings, and **refuse if a different statusline is already configured** unless `--force`. Plain `fleet init` never touches user settings. Operators commonly run `ccusage` or similar; silently overwriting it is unacceptable.

## Architecture

One source, one derivation, four consumers. Nothing on this diagram writes.

```
state/fleet.json ──┐
                   ├──▶ fleet.status_snapshot()   read-only · no lock · no probe · no write
mailbox/*.md ──────┘             │
                                 ├──▶ bin/fleet_statusline.py     (import; every ~10 s)
                                 ├──▶ fleet status --json          (/fleet:* inline exec)
                                 ├──▶ bin/hooks/sessionstart_fleet.py  (once per manager session)
                                 └──▶ [future] watchtower, web UI
```

Mutating `/fleet:*` commands bypass this path entirely: they invoke the ordinary CLI, which takes `fleet.lock` and recomputes exactly as before. The read surface and the write surface never contend for a lock, because the read surface never takes one.

## Components

### 4.1 `fleet.status_snapshot()` — the single derivation

Signature: `status_snapshot(home: Path | None = None) -> dict`

Reads `state/fleet.json`; counts `mailbox/<sid>.md` per worker. Never opens `fleet.lock`, never calls `PLATFORM.*`, never writes. Returns:

```python
{
  "ok": True,                      # False if registry missing/unreadable
  "reason": None,                  # "not_initialized" | "unreadable" when ok=False
  "generated_at": "2026-07-09T…Z",
  "totals": {"workers": 3, "working": 1, "idle": 1, "limited": 1,
             "attached": 0, "dead": 0, "mail": 2, "cost_usd": 2.14},
  "workers": [
    {"name": "pmbot", "status": "working", "turns": 7, "cost_usd": 1.02,
     "mail": 0, "stale_seconds": 12, "limit_reset_at": None, "limit_kind": None,
     "attached_since": None},
    …
  ],
}
```

Honours the additive-schema rule: every field read with a default (`cost_baseline` → `0.0`, `limit_reset_at`/`limit_kind`/`max_budget_usd`/`setting_sources` → `None`). Unknown keys ignored, never dropped (it does not write, so round-trip preservation is trivially satisfied).

`ok=False` cases return `workers: []` and a `reason`; **no exception escapes.**

### 4.2 `fleet status --json [--stale-ok]`

`--json` prints `status_snapshot()` as JSON to stdout. `--stale-ok` selects the probe-free path (no recompute, no lock, no write). Without `--stale-ok`, `--json` prints the same schema after the ordinary authoritative recompute.

Bare `fleet status` behaviour — the human table, the recompute, the anomaly flags — is **unchanged**.

### 4.3 `bin/fleet_statusline.py`

- Resolves `FLEET_HOME` (env var, else from its own location — SPEC §14), `sys.path.insert`s `FLEET_HOME/bin`, `import fleet`, calls `fleet.status_snapshot()`.
- Reads the Claude Code session JSON on stdin and discards it (accepted; the schema may grow, and fleet needs none of it today).
- Renders **one line**, ANSI-coloured:

```
⚑ 3●working 1◐idle+mail 1⏸limited  $2.14
```

- Rows/states not present are omitted. `limited` workers append ` resets 14:20` from `limit_reset_at`, or ` reset?` when it is null. A worker whose `limit_reset_at` has passed renders `resume-eligible` — a **flag only**, never a launch (invariant 1: a view does not start turns; SPEC §5 `status` row states this same rule).
- Any worker with `stale_seconds > 300` renders dimmed with a `~<age>` suffix (D2).
- `NO_COLOR` env (or a non-tty) → plain ASCII, no escapes.
- **Exit 0 on every path.** On any exception: print nothing, exit 0. This is the statusline analogue of invariant 2 (exit-0 hooks) — a traceback in a statusline is rendered under the operator's input box on every keystroke-adjacent refresh.
- Wall-clock budget: **< 20 ms**, zero subprocesses. Asserted by test.

Installed via `settings.json` with `refreshInterval: 10`.

### 4.4 `commands/` — the slash-command set

Read-only (inline `` !` ``, `allowed-tools: Bash(fleet:*)`):

| Command | Body |
|---|---|
| `/fleet:overview` | status table + doctor warnings + `knowledge/INDEX.md` lines (via `fleet knowledge`) |
| `/fleet:status` | `` !`fleet status` `` |
| `/fleet:peek <name>` | `` !`fleet peek $1` `` |
| `/fleet:result <name>` | `` !`fleet result $1` `` |
| `/fleet:doctor` | `` !`fleet doctor` `` |

Mutating (prompt template → model runs the CLI via Bash → permission prompt applies): `/fleet:spawn`, `/fleet:send`, `/fleet:interrupt`, `/fleet:respawn`, `/fleet:kill`, `/fleet:clean`, `/fleet:attach`, `/fleet:release`, `/fleet:resume-limited`. Each carries `argument-hint` and a one-line `description`.

### 4.5 `.claude-plugin/plugin.json`

Bundles `commands/` and `skills/fleet/SKILL.md` (moved from `skill/SKILL.md`) by convention discovery, and inlines the SessionStart hook registration. Worker hooks stay in `state/worker-settings.json` — unrelated wiring. Ships **no** statusline.

**Plugin name is `fleet`, not `claude-fleet`** — the slash-command namespace derives from the plugin name, so `claude-fleet` would yield `/claude-fleet:status`.

**Build findings (verified live 2026-07-09, claude 2.1.204), corrections to the original design:**
- Declaring `"commands": "./commands"` / `"skills": "./skills"` / `"hooks": "./hooks/hooks.json"` path keys did not work; the reference plugin that does work on this machine (caveman) declares none of them and inlines its hooks object. The manifest now matches that shape. Do not re-add the path keys without evidence. `claude plugin validate .` is the check; it also rejects a string `author` (must be an object) and unquoted YAML frontmatter beginning with `[`.
- `claude --plugin-dir <path>` loads the plugin for a session but **does not register its SessionStart hook** — the briefing never fires. Testing plugin hooks requires a real install (`claude plugin marketplace add` + `claude plugin install`), not `--plugin-dir`.

### 4.5.1 Making it installable for someone else

Three defects surfaced only when the plugin was actually installed and driven. Each was silent.

- **`FLEET_HOME` cannot be resolved from the script's own location.** A marketplace-installed plugin runs from a **cache copy** of this repo, whose `state/` is gitignored and empty. The hook would report a fleet of zero workers while the operator's real fleet is running. Fix: `fleet init` stamps `~/.claude/fleet-home` with the absolute home; the hook resolves `$FLEET_HOME` → marker → own location, and ignores a marker pointing at a missing directory. Verified against a real clone with an empty `state/`.
- **`py -3.13` is Windows-only.** A plugin hook command is one string run through a shell and cannot branch on OS. Fix: `bin/hooks/run_py.sh` resolves an interpreter (`$FLEET_PYTHON` → `py -3.13` → `python3.x` → `python`, requiring ≥ 3.10) and exits 0 when none exists, preserving invariant 2.
- **`fleet` did not resolve from bash.** `bin/fleet.cmd` only works from cmd.exe/PowerShell; bash ignores `PATHEXT`. Every read-only slash command inlines `` !`fleet status` ``, which runs under a shell — so `/fleet:status` produced **silent empty output**. Fix: `bin/fleet`, an extensionless POSIX shim, committed mode 755.

Both shell scripts are pinned to LF in `.gitattributes`: a CRLF checkout on Linux fails with `\r: command not found`, and the exit-0 rule would swallow it.

The SPEC §3 repo-layout block gains the new paths.

### 4.6 `bin/hooks/sessionstart_fleet.py`

- Matcher: `startup` and `resume`.
- Emits `additionalContext`: the snapshot rendered as a compact table, plus doctor-visible anomalies already derivable without probing (`idle+mail`, stale attach, `limited` past reset), plus `knowledge/INDEX.md` lines. Automates the SPEC §10 startup ritual.
- **Suppressed when `FLEET_WORKER` is set in the environment** (D5) — returns `{}` and exits 0.
- Exit 0 on every failure path (invariant 2). Read-only (SPEC §4 hook write boundary: this hook writes nothing at all, not even `hook-errors.log`, since it is a manager-side hook and its failures are invisible-by-design).
- Hard-capped at 10,000 chars; truncates worker rows first, then INDEX lines.

**Required `fleet.py` change:** `launch_turn` adds `FLEET_WORKER=<name>` to the child env passed to `Popen`. Nothing else in the launch-sequence contract (SPEC §6) moves — the env stamp happens where the child env is already constructed, before the pre-claim is released.

### 4.7 `fleet init --statusline [--chain | --force]`

1. Locate `~/.claude/settings.json` (create if absent).
2. If a `statusLine` key exists and does not point at `fleet_statusline.py` → **refuse, exit 1**, naming the incumbent. `--force` overrides.
3. Back up to `settings.json.bak.<YYYYMMDD-HHMMSS>`.
4. Merge only the `statusLine` key; every sibling key preserved byte-for-byte in value.
5. Print the interpreter path used and remind the operator to restart Claude Code.

Idempotent: re-running against a fleet-owned statusline rewrites it in place without a second backup churn (backup still taken; harmless).

Plain `fleet init` (existing behaviour: render `state/worker-settings.json`) never touches user settings.

**`--chain` — composing with an existing statusline.** Claude Code allows exactly ONE `statusLine` command, so an operator already running `ccusage` or `caveman` would otherwise have to choose. `--chain` captures the incumbent command into `state/statusline-chain.json` and installs fleet's; at render time fleet runs each delegate, prints its rows, then prints fleet's row beneath.

This is the **one** place fleet's statusline spawns a subprocess, and a deliberate, opt-in exception to D1: the delegate is a command the operator was already paying for on every refresh, and fleet's own row still costs zero subprocesses. Guards:
- A delegate that exits nonzero, hangs past `DELEGATE_TIMEOUT_SECONDS` (4 s), or emits unencodable bytes is **dropped** — fleet's row always prints.
- A fleet-owned incumbent is never captured as a delegate: chaining fleet's statusline into itself would make it invoke itself once per refresh, forever.
- `--force` overwrites the incumbent outright and chains nothing.
- The delegate command is executed through a shell. It comes from the operator's own `settings.json`, which is already an arbitrary-command surface; chaining moves no trust boundary.

## Error handling

Governing rule: **a view never fails loudly and never mutates to repair itself.**

| Condition | statusline | `/fleet:*` | SessionStart hook |
|---|---|---|---|
| `fleet.json` missing | `⚑ fleet: not initialized` | CLI's own message | empty context, exit 0 |
| `fleet.json` unparseable | `⚑ fleet: registry unreadable` | CLI quarantines + exits 1 (§11) | empty, exit 0 |
| `FLEET_HOME` unresolvable | print nothing, exit 0 | CLI error | empty, exit 0 |
| `mailbox/` missing | mail counts = 0 | idem | idem |
| any unexpected exception | print nothing, exit 0 | CLI's own handling | empty, exit 0 |

The corrupt-registry row is D4: views report, the writer quarantines.

## Testing

Unit tier (no claude binary, no OS calls, runs in the CI matrix):

- `status_snapshot()` — golden rows across all five statuses; **monkeypatch `PLATFORM.get_process_info` to raise and assert it is never called** [SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13: `PLATFORM.get_process_info` is going away with PID-liveness; the assertion this test encodes (the read-only path calls nothing live) still applies to whatever the daemon-roster equivalent is]; assert `state/fleet.lock` is never created; assert `fleet.json` mtime is unchanged after the call; missing-registry and corrupt-registry paths return `ok=False` with the right `reason` and raise nothing.
- Statusline render — empty registry, missing registry, corrupt registry, all five statuses, `limited` with and without `limit_reset_at`, `limited` past reset (renders `resume-eligible`, launches nothing), stale dimming above/below the 300 s boundary, `NO_COLOR`. Assert **zero subprocesses spawned** and exit 0 on every path including a forced exception.
- `sessionstart_fleet.py` — exit 0 on every failure path; emits `{}` when `FLEET_WORKER` is set (D5); truncates at 10,000 chars.
- `launch_turn` — asserts `FLEET_WORKER=<name>` present in the child env; asserts no other launch-sequence step reordered (SPEC §6).
- `fleet init --statusline` — creates a backup; merges without clobbering sibling keys; refuses a foreign statusline and exits 1; `--force` overwrites; idempotent re-run; plain `fleet init` leaves user settings untouched.
- Command-file lint — every `commands/*.md` has a `description`; every inline-exec command declares `allowed-tools`; **no mutating command file contains `` !` ``** (D3 enforced, not merely documented).
- `TestPlatformAdapterBoundary` extended to scan `bin/fleet_statusline.py` and `bin/hooks/sessionstart_fleet.py` — invariant 8 stays lint-enforced as the file set grows.

Tier-3 live suite (`FLEET_LIVE=1`): **unaffected.** This phase adds no claude invocation anywhere.

## Invariants touched

Cites the numbered "Architectural invariants" section of `docs/SPEC.md`. All four are **preserved**; none is modified.

- **1 daemonless launch** — every surface here is optional and additive. The CLI works fully with the statusline uninstalled, the plugin absent, and the hook unregistered. The statusline *flags* a resume-eligible `limited` worker; it never launches the resume turn (that stays the explicit `fleet resume-limited` sweep, SPEC §5).
- **6 single-writer registry** — no surface in this phase writes `fleet.json` or `events.jsonl`, and none takes `fleet.lock`. D4 is this invariant made literal: even registry *corruption* is not repaired from a view.
- **8 platform-adapter-only OS branching** — the new files add no `os.name`/`sys.platform` branch; the boundary lint is extended to cover them. The Windows PowerShell probe stays where it already is, inside the adapter, untouched. [SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13: that probe is going away with PID-liveness (`docs/SPEC.md` §6); the invariant itself — no OS branching outside the adapter — is unaffected and stays binding.]
- **9 one-state-many-views** — `status_snapshot()` is the single derivation; the statusline, the slash commands, the SessionStart hook, and (later) watchtower and the web UI are four views of it holding no independent state. The statusline importing `fleet.py` rather than re-parsing `fleet.json` is this invariant applied to code, not just to data.

## Done criteria

- A manager session shows live fleet state under the input box without any command being typed, and the statusline survives a missing, empty, and corrupt registry without ever printing a traceback.
- `/fleet:overview` answers "where am I" in one screen; `/fleet:kill` still requires a permission prompt.
- A worker session, spawned while the plugin is globally enabled, receives **no** fleet SessionStart briefing (D5 verified against a real spawn).
- `fleet init --statusline` refuses to clobber a pre-existing foreign statusline.
- Unit tier green on all three OSes in CI; `TestPlatformAdapterBoundary` green unmodified in spirit (extended file list only).

## Notes for the builder

- **[SUPERSEDED — native-substrate pivot 2026-07-13, F2 correction]** The note below is wrong-directioned post-pivot: it was correct in 2026-07-09 (the probe had shipped and SPEC's tag was stale-unbuilt), but its prescribed fix — "reclassify F20 from prescriptive to descriptive" — is no longer the right doc-only pass to run. The probe machinery it describes as shipped-and-current is itself now superseded, scheduled for M-C deletion (`docs/SPEC.md` §4/§6), not a candidate for reclassifying to permanently-descriptive. See `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §6/§8. Kept below for history — MOVE, not delete.
- **SPEC drift discovered while writing this stub (not fixed here, do not fold silently):** SPEC §4/F20 tags the three-way PID probe `[UNBUILT — owned by C2 hardening kernel item 9]`, but it is **shipped** — `probe_liveness` returns three verdicts (`bin/fleet.py:556`), the `ACCESS_DENIED` marker and `Get-CimInstance` fallback exist (`:199-237`), alive-unknown is never demoted (`:816`), and `_doctor_check_unreadable_starttime` exists (`:3772`). SPEC §12 likewise files `probe_three_way` under "pins unbuilt fixes". A separate doc-only pass should reclassify F20 from prescriptive to descriptive. This phase depends on none of it.
