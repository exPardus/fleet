# Spec: Terminal surface (Phase 1.6) — fleet inside the Claude Code TUI

**Status:** ready-for-build (design approved 2026-07-09, Altai)
**Inherits:** SPEC.md architecture + numbered invariants, ROADMAP.md principles (esp. #1 one-state-many-views, #2 daemon-is-additive).
**Independent of:** Watchtower (Phase 2), Web UI (Phase 4). Buildable any time after Phase 1.

## Goal

Fleet is visible and operable from inside the manager's Claude Code session without typing `fleet status` by hand: an always-on statusline, `/fleet:*` slash commands, a session-start briefing, all packaged as an installable plugin. Pure UX and packaging — **no new fleet capability, no new state, no new daemon.**

## Scope

**In:** a read-only snapshot function + `--json`/`--stale-ok` flags on `fleet status`; a statusline script; a `commands/` set; a SessionStart hook *(shipped, then removed — D7)*; a `.claude-plugin/plugin.json`; `fleet init --statusline`.

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

- **stdlib only, no pip deps** (SPEC §14). `fleet_statusline.py` obeys the same rule as `fleet.py` (as did the SessionStart hook, while it existed).
- **No view writes.** Nothing in this phase writes `state/fleet.json`, `state/events.jsonl`, or takes `state/fleet.lock`. The single exception in the whole phase is `fleet init --statusline` writing `~/.claude/settings.json` — outside `state/`, once, explicitly, with a backup. **This constraint is met — by the statusline and, since `doctor-repair` merged on 2026-07-27, by the read-only `/fleet:*` commands too.** *(It was NOT met by those commands at `02bf276`; that gap is closed. See D4's CURRENT STATE.)*
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
**D2 — the statusline never asserts liveness it did not probe for.** `--stale-ok` returns each worker's **last-committed** status plus `stale_seconds` derived from `last_activity`. A `working` row untouched for 40 minutes renders `work 1 40m`, the age in its own colour. It is never silently relabelled, and never presented as freshly verified. `fleet status` (no flag) remains the authoritative, recomputing command — **[SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13]**: "probing" here names the PID-probe recompute that native dispatch replaces with a daemon-roster query; the D2 honesty rule (never assert unverified liveness) is unchanged.

<!-- ts-mutating-commands -->
**D3 — read-only commands inline; mutating commands go through the model.** `` !`cmd` `` executes at prompt-expansion time with no permission prompt and no undo. `fleet kill` is terminal (only `respawn` exits `dead`) and `fleet clean` deletes logs, journals and mailboxes. A typo in an inline-exec `/fleet:kill` is unrecoverable.

- **Inline `` !` `` (read-only):** `/fleet:overview`, `/fleet:status`, `/fleet:peek`, `/fleet:result`, `/fleet:doctor`.
- **Prompt templates the model executes via Bash (mutating):** `/fleet:spawn`, `/fleet:send`, `/fleet:interrupt`, `/fleet:respawn`, `/fleet:kill`, `/fleet:clean`, `/fleet:attach`, `/fleet:release`, `/fleet:resume-limited`.

Direct control is preserved — `/fleet:kill pmbot` still kills `pmbot` — it merely passes the ordinary permission prompt on the way. Both classes call the same `fleet.py` code paths; there is no parallel logic. This mirrors the Phase-4 `<!-- webui-readonly -->` decision: derived views do not mutate, and the mutating surface stays the lock-guarded CLI.

**Enforced by test, not convention:** a lint asserts no mutating command file contains `` !` ``.

<!-- ts-corrupt-registry -->
**D4 — a view reports registry corruption; it does not quarantine.** *(A REQUIREMENT **and**, since 2026-07-27, a true description of shipped code. It was VIOLATED by every read-only `/fleet:*` command at `02bf276`; `doctor-repair` closed that. Both measurements are receipted below — read which is which before citing this decision.)*

**THE REQUIREMENT — binding, unchanged, and correct.** SPEC §11 requires the single writer to quarantine an unparseable `fleet.json` to `fleet.json.corrupt.<ts>`, append a `registry_corrupt` event, and exit 1 loudly. A view must do **none** of that: quarantine is a write, and a statusline refiring every 10 s would quarantine in a loop, shredding operator evidence. A view prints `[fleet]: registry unreadable` and exits 0. The next real `fleet` command performs the quarantine. Direct consequence of invariant 6.

**THE CURRENT STATE — the requirement is MET, by the statusline and by every read-only `/fleet:*` command.** Measured at `35cd7b7`; the receipts are in *Receipts — D4 measured against shipped code* below, in the **post-fix** subsection. The gap this paragraph used to record was closed by the `doctor-repair` slice on 2026-07-27 (merge `9739e74`, fix `0c873b6`), and root `CLAUDE.md` calls the REQUIREMENT/CURRENT-STATE split *now-discharged*. This document is the last place that still said otherwise.
- `bin/fleet_statusline.py` honours D4 on every clause: no lock, no quarantine, `[fleet]: registry unreadable`, exit 0. It always did; the sentence that names the statusline first was always true of the statusline.
- `fleet status --stale-ok`, `fleet peek`, `fleet result` and `fleet doctor` (without `--repair`) read through `read_registry_no_repair()` — *"`load_registry()` MINUS THE QUARANTINE"*, same validation, no rename. A corrupt `state/fleet.json` **survives** all four; they refuse loudly and print the `fleet doctor --repair` hint instead. `peek`, `result` and `doctor` take no lock at all.
- **Two residuals, stated so they are not mistaken for the closed gap.** (1) Bare `fleet status` — no `--stale-ok` — still takes `fleet_lock()`, at a point *after* its non-quarantining pre-probe read, so it contends for the lock but cannot quarantine. No `/fleet:*` template reaches it: `commands/status.md` and `commands/overview.md` both inline `` !`fleet status --stale-ok` ``, pinned by `tests/test_view_quarantine.py::test_the_inline_status_call_is_the_stale_ok_read`. (2) `fleet doctor --repair` is the only quarantining path a view could reach, and it is not a view — it is the operator's explicit repair verb. D4 governs views; `--repair` is outside it by construction. **It is NOT the only path that performs the rename, and this residual used to say it was the "one quarantine site left in the tree".** The rename lives in `load_registry`, whose sole caller of `_quarantine_registry` it is, so every lock-holding mutating verb that loads the registry still quarantines a corrupt one — measured at `b3ec8d7`, `fleet clean`/`kill`/`archive`/`wait` all do. That is SPEC §11's single writer behaving correctly and is outside D4 for the same reason `--repair` is; what D4 constrains is the read surface, and there the claim holds.
- `commands/peek.md` and `commands/result.md` still inline the bare verbs, but those verbs are now clean, so inlining them is no longer a D4 violation. What made bare-verb inlining dangerous was the verb, not the inlining.

Why the old gap was more than a wording defect, kept because the reasoning is what makes D4 binding rather than stylistic: each of those verbs performed **step 2 of the privilege-escalation repro** — a corrupt registry refuses, the rename converts *corrupt* into *absent*, and absent reads downstream as an affirmative "not a worker" answer. An operator whose registry was corrupt and whose first move was `/fleet:status` walked that step and was told nothing about it. That is the harm the fix removed, and the reason `--repair` must stay the operator's deliberate call.

**The gap is closed; `doctor-repair` was the slice that closed it.** The remedy was the code change this document declined to make — the read verbs were routed off `load_registry()` onto a non-quarantining read, which is the second of the two options sketched here. `tests/test_views_doctrine.py` pinned the pair and **went green on its own**, exactly as designed: its D4-restatement test now takes `pytest.skip` because an unqualified restatement is no longer a defect, and `test_the_quarantine_detector_can_see_a_quarantine` is what stops a broken detector from reaching that skip. **The unqualified rule is now the correct statement.**

> **A NOTE ON HOW THIS PARAGRAPH WENT STALE — the mechanism, not the incident.** The previous CURRENT STATE ended *"this paragraph is not to be deleted until they [the receipts] say something else."* The receipts were pinned `# at 02bf276`, a pre-fix commit — and a receipt pinned to a commit can never say something else. The instruction was therefore self-sealing: it made the paragraph permanent while promising it was conditional. That is the drift class, and the fix is structural, not editorial: **a CURRENT-STATE claim must cite a receipt pinned at or after the commit that makes it true, and gets re-pinned deliberately when the claim is re-measured.** Both measurements are now present below, each pinned to the commit it is true of.
>
> The pin that was supposed to catch this only ever fired in one direction — "code violates while docs claim compliance". Stale *"code violates"* prose is invisible to it, which is why this went unnoticed for three days across two documents that root `CLAUDE.md` names as a pair. **A bidirectional guard is owed and is not in this document's gift** — it needs a test asserting that no D4 CURRENT-STATE paragraph contradicts the live `_any_view_still_quarantines()` measurement *in either direction*. Filed rather than built here: the change belongs in `tests/`.

<!-- ts-worker-suppression -->
**D5 — the SessionStart hook suppresses itself inside workers.** **[SUPERSEDED — D7, 2026-07-22: the hook is gone, so there is nothing left to suppress. The `FLEET_WORKER` stamp D5 introduced stays, for the reasons in D7.]** A globally-enabled fleet plugin fires its SessionStart hook in **every** Claude Code session on the machine, including every worker turn — injecting a fleet briefing into worker context, wasting tokens and confusing the worker about its role. Guard: `launch_turn` stamps `FLEET_WORKER=<name>` into the child environment; the hook returns empty context when it sees that variable. This is the one `fleet.py` change outside the read path.

<!-- ts-no-sessionstart -->
**D7 — fleet injects nothing into any session; every fleet surface is pull-only.** *(Operator decision, 2026-07-22. Supersedes D5 and §4.6.)*

D5 got the diagnosis right and the remedy half-right. It saw that a globally-enabled plugin fires its SessionStart hook in **every** session on the machine, and guarded the one case where that was obviously wrong (workers). It did not follow the same reasoning to the case that matters more: **every unrelated project on the machine.** Opening a session in any other repo injected the fleet's whole internal state into that session's context — open operator gates verbatim from `docs/OPERATOR-GATES.md`, every worker in the registry with its name and status regardless of which project it belongs to, and 20 lines of `knowledge/INDEX.md`. Roughly 7,000 characters of one project's governance, delivered into an unrelated project's context window, on every startup, for as long as the plugin stayed installed.

That is cross-project data leakage, and it is a property of the *distribution model*, not of this machine's setup. Fleet is built to be installed the way any other Claude Code plugin is installed. A plugin that is enabled once and then narrates its own internals into every session on the machine is not shippable, and no amount of filtering fixes the shape — a briefing scoped to the current repo is still an injection nobody asked for, and still costs tokens in a session that will never touch the fleet.

Therefore: **no SessionStart hook, and no other injection surface.** `.claude-plugin/plugin.json` declares no `hooks` key at all. Fleet state reaches a session exactly one way — the session asks for it: `fleet status`, the `/fleet:*` commands, or the `fleet` skill's startup ritual, all of which run only when the operator has already chosen to do fleet work.

What the removal costs, stated plainly rather than waved away:

- **The SPEC §10 startup ritual is no longer automated.** It moves back into `skills/fleet/SKILL.md`, where it runs when the skill activates. This is strictly later than a hook, and that is the point: it fires when someone is managing a fleet, not when someone opens an unrelated repo.
- **Open operator gates no longer arrive before the first tool call.** The 2026-07-21 ask that ratification decisions be put to the operator *before* a session starts work is now met by the skill's startup ritual reading `docs/OPERATOR-GATES.md` as step 1, not by the hook's `_operator_gate_lines`, which is deleted along with it. A manager session still cannot start work without meeting the gates; a session in someone else's repo is no longer told the fleet has any.
- **A session no longer learns unprompted that a worker is idle with mail.** The statusline (`fleet init --statusline`, D6) remains the ambient surface for that, and unlike the hook it is opt-in, operator-installed, one line, and carries no gate text or knowledge index.

`FLEET_WORKER` survives the hook that motivated it. It is now load-bearing for the supervisor claim guard and the destructive-command guard (`tests/test_destructive_guard.py`, `tests/test_supervisor.py`), which is why `_worker_env` keeps stamping it. The caveat recorded in `docs/SPEC.md` §6.1 still binds: `FLEET_WORKER` means "not the manager session", never "is a registry worker".

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
                                 └──▶ [future] watchtower, web UI
```

Every consumer on this diagram is **pulled** by the operator or by a surface they installed on purpose (D7). Nothing here is pushed into a session that did not ask.

Mutating `/fleet:*` commands bypass this path entirely: they invoke the ordinary CLI, which takes `fleet.lock` and recomputes exactly as before. The read surface and the write surface never contend for a lock, because the read surface never takes one — **and since 2026-07-27 that is the shipped behaviour, not only the requirement.** The read-only `/fleet:*` commands reach it by a second route rather than through this diagram: they inline `fleet status --stale-ok` / `fleet peek` / `fleet result` / `fleet doctor`, which read through `read_registry_no_repair()` — lock-free for `peek`/`result`/`doctor`, and quarantining in no case. *(At `02bf276` they inlined the bare verbs and all four took `fleet.lock` and quarantined; only the statusline was on the arrow. See D4's CURRENT STATE for the closed gap.)*

## Components

### 4.1 `fleet.status_snapshot()` — the single derivation

Signature: `status_snapshot(now: datetime | None = None, include_archived: bool = False) -> dict`

Reads `state/fleet.json`; counts `mailbox/<sid>.md` per worker; reads the supervisor claim file. Never opens `fleet.lock`, never calls `PLATFORM.*`, never writes. Returns:

```python
{
  "ok": True,                      # False if registry missing/unreadable
  "reason": None,                  # "not_initialized" | "quarantined" | "unreadable"
                                   # when ok=False
  "generated_at": "2026-07-09T…Z",
  "totals": {"workers": 3, "mail": 2, "cost_usd": 2.14, "by_status": {…}},
  "supervisor": {"goals_active": True, "state": "held",
                 "incarnation_id": "inc-…", "heartbeat_age_seconds": 42.0},
  "workers": [
    {"name": "pmbot", "status": "working", "turns": 7, "cost_usd": 1.02,
     "mail": 0, "stale_seconds": 12, "limit_reset_at": None, "limit_kind": None,
     "attached_since": None, "tier": "worker", "dispatch_kind": "native",
     "archived_at": None},
    …
  ],
}
```

**The tier fields (three-tier §3).** One flat roster carries two tiers: a supervisor body is a registry row like any other, and the claim that makes one of them *the* supervisor lives in a different file. A view that reads only `workers` therefore projects two tiers as one and counts husks of a retired command tier as workers.

- `workers[].tier` is `"supervisor"` or `"worker"`, derived from the `sup|<inc>|<role>` name family through fleet's own `_is_supervisor_shaped` — no consumer re-implements the shape (invariant 9). It describes the **body**, never the claim: a released or seized supervisor keeps its name.
- `snap["supervisor"]` is the **claim**. `state` ∈ `held` | `released` | `none` | `unknown`. It is present on every path, `ok=False` included — the claim lives in a different file, so a corrupt worker table must not take the one field that says whether anything can be dispatched.
- `heartbeat_age_seconds` is `None` on a `released` claim **by design** (claim-nonce §6.3 strips `heartbeat_at`); a view must not render that as staleness.
- `unknown` is a rendered word, not silence. **Absence is not evidence on this substrate** — "the claim could not be read" must never present as "there is no supervisor". The projection never raises: every failure degrades to `unknown`.

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
[fleet]  sup held  work 3  mail 1  lim 1 resets 14:20  idle 1 15m  +4 dead
```

- **The command tier leads the line** (three-tier §3). `sup held` / `sup released` / `sup none` / `sup ?`, rendered only while `supervisor.goals_active` — a fleet not running supervisor doctrine carries no permanent scold. A `held` claim whose heartbeat is older than the D2 threshold appends its age (` sup held 2h`); a `released` one never does, because §6.3 leaves it no heartbeat to age.
- **A live supervisor body is not a worker.** Rows with `tier == "supervisor"` and a non-`dead` status leave the worker buckets entirely. A **dead** one rejoins the flat roster for the grey tail: a corpse is a corpse whatever tier it died in, and a second grey field would break the grey-means-inert rule below.
- **More than one live supervisor body is an alarm**, rendered `N bodies` in a reserved bold red — the count, not a boolean, because 2 and 9 are different incidents. This is the one condition three-tier exists to prevent.
- The tier fields are **not** live workers: an all-supervisor fleet still renders `no live workers`, so going live with GOALS.md never silently retires that message.
- **No cost field** (removed 2026-07-27, operator's call). Under the Max-20x cap doctrine the plan limits spend, fleet enforces no dollar ceiling, and native dispatch records no cost at all — so the running total summed rows that report nothing, and it was not something the operator could act on. `fleet status` still totals it.
- Rows/states not present are omitted. `limited` workers append ` resets 14:20` from `limit_reset_at`, or ` reset?` when it is null. A worker whose `limit_reset_at` has passed renders `resume-eligible` — a **flag only**, never a launch (invariant 1: a view does not start turns; SPEC §5 `status` row states this same rule).
- A bucket whose every worker has `stale_seconds > 300` appends the freshest ` <age>` (D2). The age is coloured, **not** dimmed: dimming the whole chunk rendered grey-on-dark counts that the operator could not read.
- **Buckets appear in a fixed order** (`work · mail · att · lim · budget · ceiling · idle`), never count-sorted — a count-sorted line reshuffles between refreshes, forcing a re-read, and lets a pile of corpses outrank the one live worker. `dead` is not a bucket at all: it collapses into a `+N dead` tail counter.
- **Colour is the second channel and it is exclusive.** One hue per status, plus a distinct hue each for the `[fleet]` nameplate, the age, the command-tier field, and the second-body alarm. **Grey is reserved for `dead`** — nothing else on the line may use it, or "greyed out" stops meaning "inert".
- **The line is pure ASCII by construction** — no glyphs, no box drawing. A cp1252 console cannot encode geometric glyphs; `print()` then raises `UnicodeEncodeError`, the exit-0 guard swallows it, and the operator gets a permanently **blank** statusline. Colour and word already carry the whole signal, so the glyphs bought nothing but width and that failure mode. Asserted by test, not convention.
- `NO_COLOR` env (or a non-tty) → no escapes; the same words, unpainted.
- **Exit 0 on every path.** On any exception: print nothing, exit 0. This is the statusline analogue of invariant 2 (exit-0 hooks) — a traceback in a statusline is rendered under the operator's input box on every keystroke-adjacent refresh.
- Wall-clock budget: **< 20 ms**, zero subprocesses. Asserted by test.

Installed via `settings.json` with `refreshInterval: 10`.

### 4.4 `commands/` — the slash-command set

Read-only (inline `` !` ``, `allowed-tools` granting **exactly what the body inlines** — an exact rule for a fixed span, `Bash(fleet <verb>:*)` only where a `$ARGUMENTS`/`$1` placeholder makes the literal unknowable). `Bash(fleet:*)` as written here originally is the grant that caused the 2026-07-09 kill/clean incident, and `X:*` is a **prefix** match, so even a per-verb `Bash(fleet doctor:*)` reaches `fleet doctor --repair` (P1-3/P1-14, 2026-07-30). Pinned by `tests/test_terminal_surface.py::TestCommandFiles::test_read_only_grants_are_no_wider_than_the_body_invokes`:

| Command | Body |
|---|---|
| `/fleet:overview` | status table + doctor warnings + `knowledge/INDEX.md` lines (via `fleet knowledge`) |
| `/fleet:status` | `` !`fleet status` `` |
| `/fleet:peek <name>` | `` !`fleet peek $1` `` |
| `/fleet:result <name>` | `` !`fleet result $1` `` |
| `/fleet:doctor` | `` !`fleet doctor` `` |

Mutating (prompt template → model runs the CLI via Bash → permission prompt applies): `/fleet:spawn`, `/fleet:send`, `/fleet:interrupt`, `/fleet:respawn`, `/fleet:kill`, `/fleet:clean`, `/fleet:attach`, `/fleet:release`, `/fleet:resume-limited`. Each carries `argument-hint` and a one-line `description`.

### 4.5 `.claude-plugin/plugin.json`

Bundles `commands/` and `skills/fleet/SKILL.md` (moved from `skill/SKILL.md`) by convention discovery. Worker hooks stay in `state/worker-settings.json` — unrelated wiring. Ships **no** statusline and, since D7, **no hooks at all**: the manifest has no `hooks` key, so installing the plugin adds slash commands and a skill and changes nothing about how any session starts.

**Plugin name is `fleet`, not `claude-fleet`** — the slash-command namespace derives from the plugin name, so `claude-fleet` would yield `/claude-fleet:status`.

**Build findings (verified live 2026-07-09, claude 2.1.204), corrections to the original design:**
- Declaring `"commands": "./commands"` / `"skills": "./skills"` / `"hooks": "./hooks/hooks.json"` path keys did not work; the reference plugin that does work on this machine (caveman) declares none of them and inlines its hooks object. The manifest now matches that shape. Do not re-add the path keys without evidence. `claude plugin validate .` is the check; it also rejects a string `author` (must be an object) and unquoted YAML frontmatter beginning with `[`.
- `claude --plugin-dir <path>` loads the plugin for a session but **does not register its SessionStart hook** — the briefing never fired. Testing plugin hooks requires a real install (`claude plugin marketplace add` + `claude plugin install`), not `--plugin-dir`. *(Historical: the plugin registers no hooks since D7. Kept because it is the only recorded evidence of this platform behaviour, and the next builder who adds any plugin hook will need it.)*

### 4.5.1 Making it installable for someone else

Three defects surfaced only when the plugin was actually installed and driven. Each was silent.

- **`FLEET_HOME` cannot be resolved from the script's own location.** A marketplace-installed plugin runs from a **cache copy** of this repo, whose `state/` is gitignored and empty. The hook would report a fleet of zero workers while the operator's real fleet is running. Fix: `fleet init` stamps `~/.claude/fleet-home` with the absolute home; the hook resolves `$FLEET_HOME` → marker → own location, and ignores a marker pointing at a missing directory. Verified against a real clone with an empty `state/`. **[RESOLVED BY DELETION — D7 follow-up, 2026-07-22.]** The hook was the marker's only reader; `fleet.py`, `fleet_statusline.py` and both shell shims resolve `$FLEET_HOME` → own location and never consulted it, and the autoclean scheduled task carries an explicit `--fleet-home`. With the reader gone the marker was removed rather than kept, because stamping it was fleet's only *unconditional* write to global machine state — plain `fleet init` wrote into `~/.claude/` on an invocation that had asked for nothing outside the repo, which is the same instinct D7 removed from the manifest. `fleet init --statusline` remains the one flag that may touch the user's home. **Do not reintroduce the marker as a resolution input:** a stale one would silently redirect the CLI — `fleet clean` and `fleet kill` included — at a different fleet's registry, which is a worse failure than the one it solved.
- **`py -3.13` is Windows-only.** A plugin hook command is one string run through a shell and cannot branch on OS. Fix: `bin/hooks/run_py.sh` resolves an interpreter (`$FLEET_PYTHON` → `py -3.13` → `python3.x` → `python`, requiring ≥ 3.10) and exits 0 when none exists, preserving invariant 2.
- **`fleet` did not resolve from bash.** `bin/fleet.cmd` only works from cmd.exe/PowerShell; bash ignores `PATHEXT`. Every read-only slash command inlines `` !`fleet status` ``, which runs under a shell — so `/fleet:status` produced **silent empty output**. Fix: `bin/fleet`, an extensionless POSIX shim, committed mode 755.

Both shell scripts are pinned to LF in `.gitattributes`: a CRLF checkout on Linux fails with `\r: command not found`, and the exit-0 rule would swallow it.

The SPEC §3 repo-layout block gains the new paths.

### 4.6 `bin/hooks/sessionstart_fleet.py` — **REMOVED (D7, 2026-07-22)**

The hook shipped in Phase 1.6 and was deleted on 2026-07-22 along with the `hooks` key of `.claude-plugin/plugin.json`. It emitted a briefing (open operator gates, the worker table, `knowledge/INDEX.md`) into every session on the machine that was not a worker — including every session in every unrelated project. See D7 for why filtering it was rejected in favour of deleting it.

Nothing replaces it. The startup ritual it automated lives in `skills/fleet/SKILL.md`; the gates it surfaced are read by that ritual's first step.

**The `fleet.py` change it required is retained:** `launch_turn` still stamps `FLEET_WORKER=<name>` into the child env, now for the supervisor and destructive-command guards rather than for hook suppression (D7).

A future injection surface is not forbidden by fiat, but it inherits D7's bar: it must not fire in a session that has not opted into fleet work.

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

The SessionStart-hook column is dropped here with the hook itself (D7).

| Condition | statusline | `/fleet:*` |
|---|---|---|
| `fleet.json` missing, no `fleet.json.corrupt.*` beside it | `[fleet]: not initialized` | CLI's own message |
| `fleet.json` missing, a `fleet.json.corrupt.*` artifact STANDS | `[fleet]: registry quarantined` | `fleet status --stale-ok` names the artifact and the remedy, exit 0; `fleet doctor` FAILs the registry row |
| `fleet.json` unparseable | `[fleet]: registry unreadable` | reports + leaves the file in place; `/fleet:status` exits 0, `/fleet:peek`/`/fleet:result`/`/fleet:doctor` exit 1 with the `--repair` hint |
| `FLEET_HOME` unresolvable | print nothing, exit 0 | CLI error |
| `mailbox/` missing | mail counts = 0 | idem |
| any unexpected exception | print nothing, exit 0 | CLI's own handling |

**The two missing-`fleet.json` rows used to be one row, and that was the defect** (P1-13, fixed 2026-07-31). `_quarantine_registry` RENAMES rather than deletes, so from the operator's side a repaired incident and a box that never ran `fleet init` are both *"absent"* — and both surfaces printed the identical string for them. Measured on one home with the artifact present and then removed, the statusline and `fleet status --stale-ok` were byte-identical across the two states, so the read surface could not distinguish them at all. The split is derived from `_quarantine_artifacts()`, a `Path.glob` that swallows `OSError` into `[]` — no lock, no probe, no write, never raises — so **D4 is preserved: the honest render is reachable from a pure read.** A fix that made the statusline truthful by making it *probe* would have violated D4 and invariant 6; this one does not.

The corrupt-registry row is D4: views report, the writer quarantines. The `/fleet:*` column of that row is written as the CLI's behaviour because it *is* the CLI — and since `doctor-repair`, D4 holds for both columns: a `/fleet:status` on a corrupt registry reports and exits 0, and `/fleet:peek`/`/fleet:result`/`/fleet:doctor` refuse without renaming anything. The only surface reachable from the read path that still quarantines is `fleet doctor --repair`, which is the operator's explicit repair verb and not a view — the lock-holding mutating verbs still quarantine too, and are not in this row's scope. *(At `02bf276` this row read "CLI quarantines + exits 1 (§11)" and was correct: the read verbs inlined the bare CLI and did quarantine. That was the D4 violation, stated in the table rather than hidden by it. See D4's CURRENT STATE and both receipt sets below.)*

## Testing

Unit tier (no claude binary, no OS calls, runs in the CI matrix):

- `status_snapshot()` — golden rows across all five statuses; **monkeypatch `PLATFORM.get_process_info` to raise and assert it is never called** [SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13: `PLATFORM.get_process_info` is going away with PID-liveness; the assertion this test encodes (the read-only path calls nothing live) still applies to whatever the daemon-roster equivalent is]; assert `state/fleet.lock` is never created; assert `fleet.json` mtime is unchanged after the call; missing-registry and corrupt-registry paths return `ok=False` with the right `reason` and raise nothing.
- Statusline render — empty registry, missing registry, corrupt registry, all five statuses, `limited` with and without `limit_reset_at`, `limited` past reset (renders `resume-eligible`, launches nothing), stale dimming above/below the 300 s boundary, `NO_COLOR`. Assert **zero subprocesses spawned** and exit 0 on every path including a forced exception.
- Plugin manifest — asserts the manifest declares **no** `hooks` key and that no `SessionStart` wiring returns (D7). The leak this removes is invisible from inside the fleet repo, where the briefing looks useful; only a test states that installing the plugin must not change how an unrelated session starts.
- `launch_turn` — asserts `FLEET_WORKER=<name>` present in the child env; asserts no other launch-sequence step reordered (SPEC §6).
- `fleet init --statusline` — creates a backup; merges without clobbering sibling keys; refuses a foreign statusline and exits 1; `--force` overwrites; idempotent re-run; plain `fleet init` leaves user settings untouched.
- Command-file lint — every `commands/*.md` has a `description`; every inline-exec command declares `allowed-tools`; **no mutating command file contains `` !` ``** (D3 enforced, not merely documented).
- `TestPlatformAdapterBoundary` extended to scan `bin/fleet_statusline.py` — invariant 8 stays lint-enforced as the file set grows. (The lint now globs `bin/**/*.py` and `tools/**/*.py` rather than naming files, so removing one does not shrink its coverage.)

Tier-3 live suite (`FLEET_LIVE=1`): **unaffected.** This phase adds no claude invocation anywhere.

## Invariants touched

Cites the numbered "Architectural invariants" section of `docs/SPEC.md`. All four are **preserved**; none is modified.

- **1 daemonless launch** — every surface here is optional and additive. The CLI works fully with the statusline uninstalled, the plugin absent, and the hook unregistered. The statusline *flags* a resume-eligible `limited` worker; it never launches the resume turn (that stays the explicit `fleet resume-limited` sweep, SPEC §5).
- **6 single-writer registry** — the requirement is that no surface in this phase writes `fleet.json` or `events.jsonl` and none takes `fleet.lock`. D4 is this invariant made literal: even registry *corruption* is not to be repaired from a view. **Shipped code holds this across the whole read surface as of 2026-07-27** — the statusline, `fleet status --stale-ok`, `peek`, `result` and `doctor` all read without quarantining, and `peek`/`result`/`doctor` without taking the lock. Two residuals, neither a violation of the invariant as stated: bare `fleet status` still takes `fleet.lock` (no `/fleet:*` template invokes it — they inline `--stale-ok`), and `fleet doctor --repair` still quarantines, which is the writer doing the writer's job. The invariant is unmodified and binding. *(Measured VIOLATED through the slash-command surface at `02bf276`; `doctor-repair` was the slice that closed it — merge `9739e74`. Both measurements receipted below.)*
- **8 platform-adapter-only OS branching** — the new files add no `os.name`/`sys.platform` branch; the boundary lint is extended to cover them. The Windows PowerShell probe stays where it already is, inside the adapter, untouched. [SUPERSEDED (mechanism only) — native-substrate pivot 2026-07-13: that probe is going away with PID-liveness (`docs/SPEC.md` §6); the invariant itself — no OS branching outside the adapter — is unaffected and stays binding.]
- **9 one-state-many-views** — `status_snapshot()` is the single derivation; the statusline, the slash commands, and (later) watchtower and the web UI are views of it holding no independent state. Removing a view (the SessionStart hook, D7) cost nothing elsewhere, which is the invariant paying out. The statusline importing `fleet.py` rather than re-parsing `fleet.json` is this invariant applied to code, not just to data.

## Done criteria

- A manager session shows live fleet state under the input box without any command being typed, and the statusline survives a missing, empty, and corrupt registry without ever printing a traceback.
- `/fleet:overview` answers "where am I" in one screen; `/fleet:kill` still requires a permission prompt.
- **No** session — worker, manager, or a session in an unrelated project — receives any fleet-injected context. The plugin manifest declares no hooks (D7). *(Originally: a worker receives no briefing, D5 verified against a real spawn. Widened to every session when the leak into unrelated projects was found, 2026-07-22.)*
- `fleet init --statusline` refuses to clobber a pre-existing foreign statusline.
- Unit tier green on all three OSes in CI; `TestPlatformAdapterBoundary` green unmodified in spirit (extended file list only).

## Receipts — D4 measured against shipped code

Added 2026-07-27 by the `views-doctrine` slice. D4 stood as a description of shipped behaviour for days while shipped behaviour violated it, and prose is not a guard — so the gap was pinned here as re-executable evidence rather than asserted. Every block creates its own throwaway `FLEET_HOME` in a `.probe/` directory inside the materialised temp tree and removes it. **Nothing here touches a live fleet's `state/`**, and no block is `# volatile` or `# live`: the probes are self-contained and deterministic, so they are ordinary pinned receipts.

Interpreter resolution goes through the repo's own `bin/hooks/run_py.sh` rather than a hardcoded `py -3.13`, for the reason §4.5.1 already records: `py` is Windows-only and a receipt hardcoding it would be unreproducible for anyone else.

**READ THE PINS. There are two measurements here and they disagree, because the code changed between them.**

| Subsection | Pin | What it proves |
|---|---|---|
| *§A — the gap, as measured* | `# at 02bf276` | The D4 violation was real. Four read verbs quarantined and took the lock. **History. Do not act on it as current.** |
| *§B — the gap, closed* | `# at 35cd7b7` | The same probes at a post-`doctor-repair` commit: nothing quarantines, and `peek`/`result`/`doctor` are lock-free. **This is the CURRENT STATE claim, measured.** |

§A is kept, not deleted, and its pin is **not** re-pointed: those blocks are true of `02bf276` and re-pinning them would destroy the evidence that the gap existed. §B is what makes the CURRENT STATE a measurement instead of another assertion — the defect this pair replaces was a CURRENT-STATE paragraph whose only evidence was pinned at a pre-fix commit, so it could never be contradicted by its own receipts.

### §A — the gap, as measured at `02bf276` (HISTORY)

**Quarantine.** A corrupt `state/fleet.json`, one surface per row; `survives` means the file is still there afterwards, `RENAMED ASIDE` means `load_registry()` quarantined it:

```
# at 02bf276
$ for v in "status" "status --json --stale-ok" "peek w" "result w" "doctor" "sup-status" "knowledge"; do rm -rf .probe; mkdir -p .probe/state; printf 'not json {{{' > .probe/state/fleet.json; FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet.py $v >/dev/null 2>&1; [ -f .probe/state/fleet.json ] && r=survives || r="RENAMED ASIDE"; printf '%-32s %s\n' "fleet $v" "$r"; done; rm -rf .probe; mkdir -p .probe/state; printf 'not json {{{' > .probe/state/fleet.json; echo '{}' | FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet_statusline.py >/dev/null 2>&1; [ -f .probe/state/fleet.json ] && r=survives || r="RENAMED ASIDE"; printf '%-32s %s\n' "statusline" "$r"; rm -rf .probe
fleet status                     RENAMED ASIDE
fleet status --json --stale-ok   survives
fleet peek w                     RENAMED ASIDE
fleet result w                   RENAMED ASIDE
fleet doctor                     RENAMED ASIDE
fleet sup-status                 survives
fleet knowledge                  survives
statusline                       survives
```

`sup-status` and `knowledge` are on this table because `/fleet:overview` shells out to all four of `sup-status`, `status`, `doctor` and `knowledge`; two of the four quarantine.

**Lock contention.** D4's sibling clause. A `state/fleet.lock` is pre-created (a live holder), the registry is valid, and the surface is run: a lock-free surface answers, a contending one blocks for `LOCK_TIMEOUT_SECONDS` and dies on `timed out waiting for lock`. This block is the slowest thing in the receipt suite (~20 s) precisely because four of these surfaces really do wait on a lock they are documented never to take:

```
# at 02bf276
$ for v in "status" "status --json --stale-ok" "peek w" "result w" "doctor" "sup-status"; do rm -rf .probe; mkdir -p .probe/state; printf '{"workers": {}}' > .probe/state/fleet.json; printf 'held-by-another-process' > .probe/state/fleet.lock; o=$(FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet.py $v 2>&1); case "$o" in *"timed out waiting for lock"*) r="TAKES fleet.lock";; *) r="lock-free";; esac; printf '%-32s %s\n' "fleet $v" "$r"; done; rm -rf .probe; mkdir -p .probe/state; printf '{"workers": {}}' > .probe/state/fleet.json; printf 'held-by-another-process' > .probe/state/fleet.lock; o=$(echo '{}' | FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet_statusline.py 2>&1); case "$o" in *"timed out waiting for lock"*) r="TAKES fleet.lock";; *) r="lock-free";; esac; printf '%-32s %s\n' "statusline" "$r"; rm -rf .probe
fleet status                     TAKES fleet.lock
fleet status --json --stale-ok   lock-free
fleet peek w                     TAKES fleet.lock
fleet result w                   TAKES fleet.lock
fleet doctor                     TAKES fleet.lock
fleet sup-status                 lock-free
statusline                       lock-free
```

**The call sites.** The behaviour above is not incidental — the three read-only verbs each open with the same two lines:

```
# at 02bf276
$ grep -n "^def cmd_status\|^def cmd_peek\|^def cmd_result\|^def load_registry\|^def _quarantine_registry" bin/fleet.py
812:def _quarantine_registry(path: Path) -> Path:
828:def load_registry() -> dict:
3646:def cmd_status(args) -> int:
3941:def cmd_peek(args) -> int:
3992:def cmd_result(args) -> int:
```

```
# at 02bf276
$ awk 'NR==3675||NR==3676||NR==3947||NR==3948||NR==3997||NR==3998 {print NR": "$0}' bin/fleet.py
3675:     with fleet_lock():
3676:         data = load_registry()
3947:     with fleet_lock():
3948:         data = load_registry()
3997:     with fleet_lock():
3998:         data = load_registry()
```

The quarantine is a rename, which is why it destroys the operator's evidence rather than merely annotating it:

```
# at 02bf276
$ grep -n "path.rename(quarantined)" bin/fleet.py
818:        path.rename(quarantined)
```

**The surface D4 names by name.** At `02bf276` every read-only slash command inlined a bare verb and none went through `status_snapshot()`. *(No longer true of `commands/status.md` and `commands/overview.md` — see §B.)*

```
# at 02bf276
$ grep -n '^!`fleet ' commands/status.md commands/peek.md commands/result.md commands/overview.md commands/doctor.md
commands/status.md:6:!`fleet status`
commands/peek.md:7:!`fleet peek $ARGUMENTS`
commands/result.md:7:!`fleet result $1`
commands/overview.md:10:!`fleet sup-status`
commands/overview.md:14:!`fleet status`
commands/overview.md:18:!`fleet doctor`
commands/overview.md:22:!`fleet knowledge`
commands/doctor.md:6:!`fleet doctor`
```

**On the "never probe a PID" clause of the doctrine sentence.** PID probing no longer exists anywhere in `bin/fleet.py` — the native-substrate pivot deleted it (D1's superseded marker), so that clause is now vacuously true of every surface. Its live successor is the roster subprocess, and `cmd_status` does spawn one:

```
# at 02bf276
$ grep -n "_fetch_agents_roster()" bin/fleet.py
3699:        roster_ok, payload = _fetch_agents_roster()
4041:            roster_ok, payload = _fetch_agents_roster()
4134:            roster_ok, payload = _fetch_agents_roster()
11506:    roster_ok, payload = _fetch_agents_roster()
```

`3699` is inside `cmd_status`, so `/fleet:status` spawns a subprocess on a path D1 forbids one on. That is the same gap in its post-pivot spelling and it closes with the same fix.

### §B — the gap, closed: the same probes at `35cd7b7` (CURRENT STATE)

Added 2026-07-30. `doctor-repair` merged on 2026-07-27 (`9739e74`, fix `0c873b6`) and this document was not revised with it, so for three days D4 asserted that shipped code violated D4 while root `CLAUDE.md` asserted the opposite. §A's pin could not catch that — a receipt pinned at a pre-fix commit reproduces forever and confirms nothing about later code. §B is the correction: **the same two probe shapes, byte-identical apart from the pin**, so the two tables are directly comparable and the difference is the fix.

**Quarantine, re-measured.** Identical command to §A's quarantine block:

```
# at 35cd7b7
$ for v in "status" "status --json --stale-ok" "peek w" "result w" "doctor" "sup-status" "knowledge"; do rm -rf .probe; mkdir -p .probe/state; printf 'not json {{{' > .probe/state/fleet.json; FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet.py $v >/dev/null 2>&1; [ -f .probe/state/fleet.json ] && r=survives || r="RENAMED ASIDE"; printf '%-32s %s\n' "fleet $v" "$r"; done; rm -rf .probe; mkdir -p .probe/state; printf 'not json {{{' > .probe/state/fleet.json; echo '{}' | FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet_statusline.py >/dev/null 2>&1; [ -f .probe/state/fleet.json ] && r=survives || r="RENAMED ASIDE"; printf '%-32s %s\n' "statusline" "$r"; rm -rf .probe
fleet status                     survives
fleet status --json --stale-ok   survives
fleet peek w                     survives
fleet result w                   survives
fleet doctor                     survives
fleet sup-status                 survives
fleet knowledge                  survives
statusline                       survives
```

Four rows flipped from `RENAMED ASIDE` to `survives`: `status`, `peek`, `result`, `doctor`. **No surface reachable from a view quarantines any more.** `fleet doctor --repair` is the one quarantining path a view could reach, and it is absent from this table because it is not a view — it is the operator's explicit repair verb, and D4 governs views. **It is not the only path in the tree that performs the rename, and this note used to say it was.** Every row here is a READ verb; the lock-holding mutating verbs are not probed by this block and still quarantine (measured at `b3ec8d7`: `fleet clean`/`kill`/`archive`/`wait`), because the rename lives in `load_registry` rather than behind any verb. What this table measures, and all it measures, is that nothing on the read surface performs it.

**Lock contention, re-measured.** Identical command to §A's lock block:

```
# at 35cd7b7
$ for v in "status" "status --json --stale-ok" "peek w" "result w" "doctor" "sup-status"; do rm -rf .probe; mkdir -p .probe/state; printf '{"workers": {}}' > .probe/state/fleet.json; printf 'held-by-another-process' > .probe/state/fleet.lock; o=$(FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet.py $v 2>&1); case "$o" in *"timed out waiting for lock"*) r="TAKES fleet.lock";; *) r="lock-free";; esac; printf '%-32s %s\n' "fleet $v" "$r"; done; rm -rf .probe; mkdir -p .probe/state; printf '{"workers": {}}' > .probe/state/fleet.json; printf 'held-by-another-process' > .probe/state/fleet.lock; o=$(echo '{}' | FLEET_HOME=.probe sh bin/hooks/run_py.sh bin/fleet_statusline.py 2>&1); case "$o" in *"timed out waiting for lock"*) r="TAKES fleet.lock";; *) r="lock-free";; esac; printf '%-32s %s\n' "statusline" "$r"; rm -rf .probe
fleet status                     TAKES fleet.lock
fleet status --json --stale-ok   lock-free
fleet peek w                     lock-free
fleet result w                   lock-free
fleet doctor                     lock-free
fleet sup-status                 lock-free
statusline                       lock-free
```

`peek`, `result` and `doctor` flipped to `lock-free`. **Bare `fleet status` still takes the lock, and that row is why this receipt is here rather than a sentence claiming total compliance.** It is not a D4 violation: its lock is taken *after* a non-quarantining pre-probe read, so it can block but cannot quarantine, and no `/fleet:*` template invokes it — both templates that used to inline the bare verb now inline `--stale-ok`:

```
# at 35cd7b7
$ grep -n '^!`fleet ' commands/status.md commands/peek.md commands/result.md commands/overview.md commands/doctor.md
commands/status.md:6:!`fleet status --stale-ok`
commands/peek.md:7:!`fleet peek $ARGUMENTS`
commands/result.md:7:!`fleet result $1`
commands/overview.md:10:!`fleet sup-status`
commands/overview.md:14:!`fleet status --stale-ok`
commands/overview.md:18:!`fleet doctor`
commands/overview.md:22:!`fleet knowledge`
commands/doctor.md:6:!`fleet doctor`
```

Compare §A's copy of this grep: `commands/status.md` and `commands/overview.md` read `!`fleet status`` there. `peek.md` and `result.md` still inline bare verbs in both — unchanged, and no longer a defect, because what made bare-verb inlining dangerous was the verb, not the inlining.

**The call sites, re-measured.** §A showed three read verbs each opening with `with fleet_lock(): data = load_registry()`. Those pairs are gone from the read path, replaced by the non-quarantining reader:

```
# at 35cd7b7
$ grep -n "read_registry_no_repair" bin/fleet.py
716:    Shared by `load_registry` (which quarantines) and `read_registry_no_repair`
742:    uses `read_registry_no_repair` (same validation, no rename) or
764:def read_registry_no_repair(hint: bool = True) -> dict:
2449:    data = read_registry_no_repair()
4064:    data = read_registry_no_repair()
4341:    # job is to look at things. Both are gone; `read_registry_no_repair`
4343:    data = read_registry_no_repair()
4394:    data = read_registry_no_repair()
9089:            data = read_registry_no_repair(hint=False)
```

`4064` is `cmd_status`'s pre-probe read, `4343` is `cmd_peek`, `4394` is `cmd_result`, `9089` is `cmd_doctor`'s non-`--repair` branch — the four verbs whose `RENAMED ASIDE` rows flipped above. `764`'s definition is documented *"same validation, no rename"*, and `716` states the split explicitly: `load_registry` quarantines, `read_registry_no_repair` does not.

**Live pins, so this subsection is not the only thing holding the fix.** `tests/test_view_quarantine.py` measures that no view quarantines and pins `commands/status.md`'s inline call as the `--stale-ok` read; `tests/test_load_registry_callers.py` pins which functions may reach `load_registry()` at all. `tests/test_views_doctrine.py` remains the doctrine pin named by root `CLAUDE.md`, and its D4-restatement test now skips **by design** — the skip is the green path, guarded by `test_the_quarantine_detector_can_see_a_quarantine` so a broken detector cannot reach it silently. All three are named because a receipt is evidence about one commit and a test is evidence about every commit; the pair is the point.

**What this pair still does not guard, stated plainly:** nothing fails if §B itself goes stale the way §A's prose did. The pins fire when *code* regresses, and `tools/verify_receipts.py` fires when a *paste* stops reproducing at its own commit — but a future fix that changes this behaviour again would leave §B green at `35cd7b7` and the prose above it wrong, which is the exact shape of the defect this section was rewritten to fix. Closing that needs a test comparing every D4 CURRENT-STATE paragraph against the live measurement in **both** directions. It is owed, it lives in `tests/`, and it is not in this document's gift.

## Notes for the builder

- **[SUPERSEDED — native-substrate pivot 2026-07-13, F2 correction]** The note below is wrong-directioned post-pivot: it was correct in 2026-07-09 (the probe had shipped and SPEC's tag was stale-unbuilt), but its prescribed fix — "reclassify F20 from prescriptive to descriptive" — is no longer the right doc-only pass to run. The probe machinery it describes as shipped-and-current is itself now superseded, scheduled for M-C deletion (`docs/SPEC.md` §4/§6), not a candidate for reclassifying to permanently-descriptive. See `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` §6/§8. Kept below for history — MOVE, not delete.
- **SPEC drift discovered while writing this stub (not fixed here, do not fold silently):** SPEC §4/F20 tags the three-way PID probe `[UNBUILT — owned by C2 hardening kernel item 9]`, but it is **shipped** — `probe_liveness` returns three verdicts (`bin/fleet.py:556`), the `ACCESS_DENIED` marker and `Get-CimInstance` fallback exist (`:199-237`), alive-unknown is never demoted (`:816`), and `_doctor_check_unreadable_starttime` exists (`:3772`). SPEC §12 likewise files `probe_three_way` under "pins unbuilt fixes". A separate doc-only pass should reclassify F20 from prescriptive to descriptive. This phase depends on none of it.
