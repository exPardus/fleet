# Explore: `claude agents` TUI row display surfaces (CLI 2.1.207, Windows)

Scope: every CLI/env/flag surface that controls what a session row **displays**
in the `claude agents` background-session menu, for claude-fleet to render its
own categories/status/graphics into. Non-destructive probe per brief; 2 live
disposable sessions used (`m0-ui-*`), both stopped and cleaned up.

Cross-reference: `spike/m0/VERDICTS.md` (concurrent task, not modified here)
already did deep, independent work on `claude agents --json` schema (G3,
G2's roster-name anomaly). This report cites it where it overlaps and adds
new evidence (esp. the plain-dispatch ai-title negative control, and the
terminal-title/OSC escape channel) that VERDICTS.md does not cover.

## 1. Hidden command sweep — result: only `daemon` is real

`claude <word> --help` for: rename, title, summary, describe, tag, label,
note, status, tasks, jobs, sessions, ls, list, watch, tui →
**ABSENT, all 15**. Each falls through verbatim to the top-level `claude
--help` usage text (Commander.js treats the unknown word as the positional
`prompt` argument and `--help` short-circuits to main help regardless).
Evidence: captured full stdout for all 15, each byte-identical in its first
~400 chars to `claude --help`'s own output.

`daemon` **EXISTS** (not in the original candidate list but caught by the
sweep) — real subcommand tree:
```
claude daemon [subcommand]
  run [json-path]   Run the supervisor in the foreground
  status            Show daemon pid, version, uptime
  logs              Tail the daemon log
  uninstall         Remove the background service
  stop              Shut down the supervisor and terminate background sessions
```
`claude daemon status` (read-only, run live) confirms the daemon is the
transient process backing `claude agents`; it is a bg-session-management
layer, not itself a display surface — no title/label/color options in its
help text. **Not exploitable for row display**, only useful as an existence
check / process-liveness probe.

`agents`, `sessions`(as a bare word) both fall through as above; the *real*
inventory command is `claude agents` (with `agents` as a full subcommand,
distinct from the sweep's bare-word test, which used `--help` immediately
after — `claude agents --help` on its own IS real; see §2).

## 2. Full flag inventory

### `claude --help` (top-level, session-dispatch flags) — display-relevant subset

- `-n, --name <name>` — **the** display-name control. Doc text verbatim:
  *"Set a display name for this session (shown in the prompt box, /resume
  picker, and terminal title)"*. This is the single sanctioned channel for
  fleet to stamp a custom label into the agents row (`name` field in
  `--json`) — see §4 for live verification of what survives.
- `--bg, --background` — *"Start the session as a background agent and
  return immediately (manage with `claude agents`)"*. This is what makes a
  session show up in the agents view kind=`"background"` at all (vs
  `kind:"interactive"` for a normal foreground session, which also appears
  in the roster but with a different field set — see §4/VERDICTS G3 table).
- `--effort <level>` — sets effort (low/medium/high/xhigh/max) for the
  session. **UNOBSERVED whether effort is surfaced anywhere in the agents
  row** — not present in any `--json` key inventory across ~20 sampled
  entries (see §4); if the TUI shows it at all it is TTY-only rendering not
  reflected in `--json`.
  - `--ax-screen-reader` — *"Render screen-reader friendly output (flat
  text, no decorative borders or animations)"*. Global rendering-mode flag.
  Plausibly affects the agents TUI's own chrome (borders/spinners) if passed
  to the `claude agents` invocation itself, but **UNOBSERVED** — agents
  requires a TTY per the brief's constraint, so this was not interactively
  verified; only the existence of the flag and its doc text are confirmed.
- `--brief` — *"Enable SendUserMessage tool for agent-to-user
  communication"*. This grants a dispatched agent a tool to push messages
  back to the user/operator. **UNOBSERVED whether SendUserMessage output
  surfaces anywhere in the `agents` roster/row** (e.g. as a status line or
  toast) — not exercised live; no such field appeared in any `--json` roster
  entry sampled (§4), so if it does surface it is TTY-only, not JSON-visible.
- `--model` — model alias/full name. Confirmed live (§4, VERDICTS G3): the
  model IS recorded, but only in the **transcript**'s
  `message.model` (e.g. `"claude-haiku-4-5-20251001"`), **not** in
  `agents --json` — the roster has no `model` key on any of ~20 sampled
  entries across both this task and VERDICTS.md's inventory.
- `--agent <agent>` — custom agent persona for the session. Same story as
  `--effort`: no corresponding key in `--json`; **UNOBSERVED** whether the
  TUI shows it (not TTY-tested).

No flag among `--allowedTools/--disallowedTools/--permission-mode/--add-dir/
--mcp-config/--system-prompt/--fallback-model/--output-format/...` has any
display-row bearing — all are session-behavior flags, confirmed absent from
`--json` schema.

### `claude agents --help` (full, verbatim options list)

```
--add-dir <directory>          Additional directory for dispatched sessions
--agent <agent>                Default agent for sessions dispatched from agent view
--all                          With --json: include completed sessions (the full agent view list)
--allow-dangerously-skip-permissions
--cwd <path>                   Show only background sessions started under <path>
--dangerously-skip-permissions Alias for --permission-mode bypassPermissions
--effort <level>                Default effort level for dispatched sessions
-h, --help
--json                         Print active sessions as a JSON array and exit (for scripting)
--mcp-config <config>
--model <model>                Default model for dispatched sessions
--permission-mode <mode>
--plugin-dir <path>
--setting-sources <sources>
--settings <file-or-json>
--strict-mcp-config
```

Display-relevant here: **only `--json` and `--all`**, both scripting/filter
controls, not rendering controls.
- `--json` alone shows only *active* sessions (busy/idle-but-alive);
  `--json --all` is the union including `done`/`stopped`/`failed` — this
  is a **filter**, not a display-format switch (no alternate JSON shape, no
  `--format table|json|csv`, no column selection flag).
- `--cwd <path>` filters rows by project directory — a *filter*, not a
  display customization, but relevant to fleet: it's the only built-in
  grouping/scoping primitive; fleet could shell out per-project rather than
  parsing cwd client-side.
- **ABSENT, explicitly checked and not present**: `--sort`, `--color`,
  `--no-color`, `--columns`, `--format`, `--label`, `--tag`, `--category`,
  `--group`, `--watch`/`--follow`, `--limit`/`-n <count>`. None of these
  exist on `claude agents`. There is no server-side row-formatting hook at
  all — the JSON schema in §4 is the entire display contract.

### `claude agents --json` / `--json --all` schema (live-sampled, this task + cross-ref VERDICTS.md G3)

Full key union observed across ~20 live entries (this session's own
snapshot plus the concurrent task's larger sample):
```
pid, id, cwd, kind, startedAt, sessionId, name, status, state
```
No `title`, `summary`, `label`, `tag`, `category`, `note`, `description`,
`color`, `icon`, or `result`/`cost`/`tokens` key exists anywhere in this
schema, confirmed independently by this task's fresh probe and by
VERDICTS.md's G3 (which additionally scanned transcript/Stop-payload/
`~/.claude/jobs/<id>/state.json` for a cost/result field and found none in
any sanctioned source). **`name` is the only free-text field claude-fleet
can drive**, and it is set exclusively via `-n/--name` at dispatch time
(§4 confirms it is stable thereafter for a plain, non-resumed dispatch).

Field presence rules (own observation, consistent with VERDICTS.md G3's
table): `pid`/`status` only appear while the backing process is alive;
`kind:"interactive"` rows never carry `state`/`id`; `kind:"background"`
rows carry `state` always, `status`/`pid` only while running. `state`
literals observed across both tasks: `working, done, blocked, stopped,
failed` (no `killed`/`error` seen).

## 3. Env vars

`claude doctor` output (live, this task) lists **no environment variables
at all** — only version/commit/platform/path/search/auto-update/remote-
control status. No documented display-bound `CLAUDE_CODE_*` var appears
here or anywhere in `claude --help`'s flag descriptions except two
non-display ones surfaced incidentally by other flags' doc text:
`CLAUDE_CODE_SIMPLE=1` (set by `--bare`) and `CLAUDE_CODE_SAFE_MODE=1` (set
by `--safe-mode`) — both are mode switches, not row-display controls.

Per the brief's fallback rule (documented-only, no brute-force env sweep):
**no exploitable display-bound env var found**. Undocumented
`CLAUDE_CODE_*` candidates (e.g. a hypothetical `NO_COLOR`/theme override
reaching the agents view specifically) are **UNOBSERVED** — out of scope
for this probe per the brief's own guidance to skip undocumented vars.

## 4. Live probes (2 disposable `m0-ui-*` sessions, both dispatched from
`spike/m0/proj`, `--settings ..\worker-settings.json --permission-mode
acceptEdits --model haiku`, both stopped after)

### Probe A — `m0-ui-🔴A|pmbot|steer-me|QQQ…` (120 chars, emoji+pipe+ASCII tail)

Dispatch (PowerShell, forward-slash-safe per CLAUDE.md's Git-Bash hazard
note):
```
$name = "m0-ui-🔴A|pmbot|steer-me|" + ("Q" * 95)   # .Length = 120
claude --bg -n $name --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Reply with exactly: UI-PROBE-DONE"
```
Result: `backgrounded · bf37bbee · m0-ui-🔴A|pmbot|steer-me|QQQ…` (full name
echoed verbatim in dispatch stdout, id `bf37bbee`).

`claude agents --json --all` immediately after dispatch — `name` field
byte-identical to the 120-char input, **no truncation, no escaping,
emoji and `|` both survive intact**:
```json
{
  "pid": 43204, "id": "bf37bbee", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj",
  "kind": "background", "startedAt": 1783987274803,
  "sessionId": "bf37bbee-30e6-466f-a1a9-4920b6deb33b",
  "name": "m0-ui-🔴A|pmbot|steer-me|QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ",
  "status": "idle"
}
```
Same result after the session reached `state: "done"` (~12 s later) — name
unchanged, no truncation appeared post-completion either.

**Bonus finding — terminal-title (OSC 0) channel confirmed.** `claude logs
bf37bbee` dumps the session's raw captured PTY buffer (ANSI escapes and
all, not a structured log). It contains an OSC-0 window-title escape:
```
]0;✳ m0-ui-🔴A|pmbot|steer-me|QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ[?25l...
```
This proves the `--help` doc's claim ("shown in ... terminal title") is
literal: the full un-truncated `-n` value is written into the terminal
title via OSC 0, prefixed with a status glyph (`✳`, likely a busy/spinner
indicator swapped per session state — not decoded further, out of scope).
`claude logs <id>` is a **third display surface** beyond the `--json` roster
and the interactive TUI: it replays the session's own terminal output
(including its OSC-title-setting sequences), which is a raw-PTY capture,
not a documented API — fragile to depend on, but confirms the render
pipeline never truncates `-n` at any layer observed.

**Verdict — Unicode/pipe/length (probe 4a): CONFIRMED clean pass-through.**
Emoji, pipe, and a 120-char length all survive fully into `--json`'s `name`
field, the dispatch stdout echo, and the OSC terminal-title escape. **No
truncation observed at 120 chars** — the ellipsis-truncation seen elsewhere
(next paragraph) is a *different* mechanism (auto-generated titles), not a
length cap on `-n`-supplied names.

**Cross-reference — auto-title truncation length, measured this task.**
A foreign/concurrent roster entry (`2e94bbc6`, not touched, observed
read-only) carries an **auto-generated** title (see §4 Probe B and
VERDICTS.md G2's anomaly note for the mechanism — `ai-title` overwrite
after a resumed/forked turn): `"name": "i need more information about the
job t…"`. Measured length: the pre-ellipsis text is exactly **40
characters**, then a single `…` (U+2026) appended — i.e. **auto-titles
are capped at 40 chars + ellipsis**, distinct from and much shorter than
the 120-char clean pass-through confirmed for explicit `-n` names above.
This is a real, reproducible display constraint fleet must know: *only*
the ai-title path truncates; the user-supplied `-n` path does not (at
least not by 120 chars).

### Probe B — `m0-ui-title`, plain name, ai-title-overwrite negative control

Dispatch:
```
claude --bg -n m0-ui-title --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Reply with exactly: UI-PROBE-DONE"
```
`backgrounded · 0d8e459b · m0-ui-title`. Roster immediately after dispatch
and again after `state: "done"` (~12 s later, single poll sufficed since
this is a trivial one-turn task) — **byte-identical `name` both times**:
```json
{
  "pid": 43096, "id": "0d8e459b", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj",
  "kind": "background", "startedAt": 1783987296953,
  "sessionId": "0d8e459b-8aad-4cdb-9417-4a23eef26b2b",
  "name": "m0-ui-title", "status": "idle", "state": "done"
}
```
No extra `summary`/`title` key appeared beyond `name` at any point — the
roster schema is closed (same 8-9 keys as §2's inventory); a completed
session gains **no additional display metadata**, only the `status`/`pid`
disappearance-then-`state:"done"` transition already documented in §2.

**Verdict — ai-title overwrite (probe 4b): REFUTED for plain (non-resumed)
`--bg` dispatch.** `name` stayed exactly `"m0-ui-title"` through dispatch →
busy → done. This is a clean, controlled **negative control** that
complements VERDICTS.md's G2 anomaly (where the auto-retitle *did* fire,
but only after a `--bg --resume` fork/second-turn, immediately after
which the daemon's `ai-title` mechanism overwrote `name` with an
auto-generated 40-char+ellipsis summary of the task). **Combined
conclusion: the ai-title auto-rename is not a generic "session finished"
behavior — it appears specifically tied to the resume/fork code path (or
possibly a 2nd-turn threshold), not to plain single-turn `--bg` dispatch.**
This matters directly for fleet: a worker dispatched once with `-n
<fleet-name>` and never resumed via `--bg --resume` keeps that exact name
for its entire lifecycle, including after completion — safe to rely on for
join-by-name in that specific case. The moment fleet's own steering logic
uses `--bg --resume` to deliver a second prompt (already established as a
silent-fork operation per VERDICTS.md G2), the resulting forked session's
`name` is **at risk of being silently overwritten** by ai-title on its own
next completion. **UNOBSERVED, flagged explicitly:** whether the ai-title
overwrite is deterministic-on-every-resume or probabilistic/threshold-based
(N-th turn) — only one forked case (VERDICTS.md G2) and zero non-forked
cases (this task, 2/2) have been observed; sample size is too small to rule
out a partial/flaky trigger.

Cleanup: `claude stop bf37bbee` → `stopped bf37bbee`; `claude stop
0d8e459b` → `stopped 0d8e459b`. No other session touched (`m0-reap`,
`m0-beat`, and the 4 foreign interactive/background sessions listed in
early `--json` snapshots were read-only-observed, never targeted).

## 5. TUI itself

Not interactively driven, per brief's constraint (`claude agents` requires
a TTY). All findings above are `--json`/`--help`/doc-text derived. This
means the following remain formally **UNOBSERVED**:
- Whether the interactive TUI renders anything beyond the `--json` field
  set (e.g. a spinner/color keyed off `state`, the `✳` glyph's exact
  meaning/variants, column layout, whether long names wrap vs. get
  ellipsis-clipped *in the TUI itself* despite surviving intact in `--json`
  and the OSC title).
- Whether `--ax-screen-reader` or `--brief`/SendUserMessage output changes
  agents-view rendering.
- Whether `--effort`/`--agent`/`--model` are shown as TUI-only columns not
  reflected in `--json` (schema says no, but TTY rendering could still add
  decoration not present in the scriptable output).

## Summary — exploitability for fleet display

| Surface | Exists | Exploitable for fleet | Evidence |
|---|---|---|---|
| `-n/--name` at dispatch | Yes | **Yes — primary channel.** Free text, unicode+pipe safe, no truncation observed to 120 chars, stable post-completion for plain dispatch | Probe A, Probe B (this task) |
| `claude agents --json`/`--json --all` | Yes | Yes — the entire scriptable read surface; 8-9 fixed keys, closed schema, no title/label/color/cost | §2, cross-ref VERDICTS G3 |
| `--cwd <path>` filter | Yes | Yes, as a grouping primitive (filter only, not a render hook) | §2 |
| OSC-0 terminal title via `claude logs <id>` | Yes (undocumented) | Marginal — raw PTY replay, not an API; confirms `-n` reaches title bar but too fragile to build on | Probe A bonus finding |
| `--sort/--color/--format/--columns/--label/--tag/--category` on `agents` | **No** | N/A — none exist | §2, exhaustively checked against full `--help` text |
| Hidden per-session `rename/title/tag/label/note/status` subcommands | **No** | N/A | §1, 15/15 fell through to main help |
| `daemon` subcommand | Yes | No display hook (process-lifecycle only) | §1 |
| ai-title auto-rename | Yes, but resume/fork-triggered only (UNOBSERVED: deterministic vs threshold) | Risk, not opportunity — fleet must not rely on `name` staying fixed across a `--bg --resume` steer | Probe B + VERDICTS G2 cross-ref |
| Display-bound env var | Not found (documented-only sweep) | No | §3 |
| `--effort`/`--agent`/`--model` shown in row | UNOBSERVED (absent from `--json`, TUI-only status unknown) | Unknown | §2, §5 |
| `--brief`/SendUserMessage surfacing in roster | UNOBSERVED | Unknown | §2 |
| Interactive TUI rendering beyond `--json` schema | UNOBSERVED (no TTY drive per brief) | Unknown | §5 |

**Bottom line for claude-fleet:** the only sanctioned, load-bearing lever is
`-n/--name` at dispatch time, read back via `claude agents --json --all`'s
closed 8-9-key schema. There is no tag/category/status/color field to
piggyback on — any "categories/status/graphics" fleet wants in the menu
must be **encoded into the `name` string itself** (e.g. a prefix/glyph
convention, as this probe's own `✳`-prefixed OSC title suggests the CLI
already does internally), not injected via a separate metadata channel,
because no such channel exists on this CLI version. The one hazard to
design around: that encoding is stable for plain dispatch but at risk of
being silently overwritten by `ai-title` the moment fleet's steering path
uses `--bg --resume` (per VERDICTS.md G2 + this task's Probe B negative
control).
