# M-0 G-table verdicts (working log)
Spec: docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §2.
One `### G<N>:` section per experiment, appended as executed.
Vocabulary: CONFIRMED / REFUTED / DISPUTED — evidence quoted inline.

### G6: `--session-id` composes with `--bg`? — **REFUTED** (halt-grade: no; fallback applies without ratification)

Dispatch command (PowerShell, from `spike/m0/proj`):
```
$sid = [guid]::NewGuid().ToString()   # 3ddc50ce-3015-45d2-8865-319f479851dc
claude --bg -n m0-core --session-id $sid --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read task.md in this directory, then follow it."
```

Exact stderr emitted at dispatch:
```
warning: --bg manages the session id; ignoring --session-id (use --resume <id> to continue an existing session)
```

Exact stdout emitted at dispatch (verbatim):
```
Starting background service…
backgrounded · 0ac6e5d0 · m0-core
  claude agents             list sessions
  claude attach 0ac6e5d0    open in this terminal
  claude logs 0ac6e5d0      show recent output
  claude stop 0ac6e5d0      stop this session
```

`claude agents --json --all` roster entry for the dispatched session:
```json
{
 "pid": 38072,
 "id": "0ac6e5d0",
 "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj",
 "kind": "background",
 "startedAt": 1783975713627,
 "sessionId": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5",
 "name": "m0-core",
 "status": "idle",
 "state": "done"
}
```

Minted sid `3ddc50ce-3015-45d2-8865-319f479851dc` != actual roster `sessionId` `0ac6e5d0-f96f-499a-bac7-d33979e3acc5`. `--bg` silently mints its own sid (short id `0ac6e5d0`, printed at dispatch, is the prefix of the real sid) and discards the caller-supplied `--session-id`. This matches the spec's pre-registered "no" fallback exactly: **short-id capture from `--bg` stdout + `agents --json` join by `-n`**. No operator ratification required (G6 is not HALT-grade). Fleet's launch contract must pre-claim by name, not by pre-minted sid; sid is only knowable after dispatch returns.

### G4: Env propagation (`FLEET_WORKER` stamp, `CLAUDE_CODE_SESSION_ID` strip) reaches the daemon-spawned child? — **CONFIRMED**

Dispatching shell state immediately before dispatch: `$env:FLEET_WORKER = "1"`; `Env:CLAUDE_CODE_SESSION_ID` removed (unset) beforehand.

Every hook-probe event record for this session carries `"env_fleet_worker": "1"` and `"env_claude_session"` equal to the session's own sid (`0ac6e5d0-f96f-499a-bac7-d33979e3acc5`) — never null, never a foreign/inherited sid:
```
{"event": "SessionStart", "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", ...}
{"event": "PreToolUse",   "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", ...}
{"event": "PostToolUse",  "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", ...}
{"event": "Stop",         "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", ...}
```

Both halves of the gate hold: (1) `FLEET_WORKER=1` set in the dispatching PowerShell process reached the daemon-spawned child's environment, visible to every hook subprocess for the life of the session; (2) `CLAUDE_CODE_SESSION_ID` was unset in the dispatching shell, yet the child's own environment carries its **own** sid (not a stale/foreign one — no other session's sid appears anywhere in these records) — i.e. the daemon sets it itself rather than inheriting it, satisfying the "null or worker's own sid" CONFIRMED clause. **No HALT.** D5 / SPEC §5.1's provenance guard (stamp `FLEET_WORKER`, treat `CLAUDE_CODE_SESSION_ID` as untrusted/self-set) is buildable as designed.

### G1: Do fleet hooks fire inside a `--bg` session (SessionStart / PreToolUse / PostToolUse / Stop)? — **CONFIRMED**

`spike/m0/out/events.jsonl` after the session reached `state: done` (4 lines, one per hook), each `session_id` equal to the actual dispatched sid `0ac6e5d0-f96f-499a-bac7-d33979e3acc5` (the daemon-minted one — see G6; not the pre-mint attempt):

```json
{"t": 1783975713.8485663, "event": "SessionStart", "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "transcript_path": "C:\\Users\\Techn\\.claude\\projects\\C--proga-claude-fleet-spike-m0-proj\\0ac6e5d0-f96f-499a-bac7-d33979e3acc5.jsonl", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "payload_keys": ["cwd", "hook_event_name", "model", "session_id", "session_title", "source", "transcript_path"]}
{"t": 1783975718.480691, "event": "PreToolUse", "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "transcript_path": "C:\\Users\\Techn\\.claude\\projects\\C--proga-claude-fleet-spike-m0-proj\\0ac6e5d0-f96f-499a-bac7-d33979e3acc5.jsonl", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "payload_keys": ["cwd", "hook_event_name", "permission_mode", "prompt_id", "session_id", "tool_input", "tool_name", "tool_use_id", "transcript_path"]}
{"t": 1783975718.6310487, "event": "PostToolUse", "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "transcript_path": "C:\\Users\\Techn\\.claude\\projects\\C--proga-claude-fleet-spike-m0-proj\\0ac6e5d0-f96f-499a-bac7-d33979e3acc5.jsonl", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "payload_keys": ["cwd", "duration_ms", "hook_event_name", "permission_mode", "prompt_id", "session_id", "tool_input", "tool_name", "tool_response", "tool_use_id", "transcript_path"]}
{"t": 1783975722.0749903, "event": "Stop", "env_fleet_worker": "1", "env_claude_session": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "session_id": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "transcript_path": "C:\\Users\\Techn\\.claude\\projects\\C--proga-claude-fleet-spike-m0-proj\\0ac6e5d0-f96f-499a-bac7-d33979e3acc5.jsonl", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "payload_keys": ["background_tasks", "cwd", "hook_event_name", "last_assistant_message", "permission_mode", "prompt_id", "session_crons", "session_id", "stop_hook_active", "transcript_path"]}
```

All four fired exactly once, in order, ~4-8s apart, ending with roster `state: done` and the worker's transcript reply verbatim `DONE-M0`. No HALT.

**`payload_keys` per event type (raw material for G3):**
- `SessionStart`: `cwd, hook_event_name, model, session_id, session_title, source, transcript_path`
- `PreToolUse`: `cwd, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_use_id, transcript_path`
- `PostToolUse`: `cwd, duration_ms, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_response, tool_use_id, transcript_path`
- `Stop`: `background_tasks, cwd, hook_event_name, last_assistant_message, permission_mode, prompt_id, session_crons, session_id, stop_hook_active, transcript_path`

Note: no `PostToolUse`/`PreToolUse` payload carries `env_fleet_worker`/`env_claude_session` — those two fields are hook-probe-computed (`os.environ.get(...)`), not part of the Claude Code hook payload itself; they are listed separately in each record, outside `payload_keys`.

Session cleanup: `claude stop 0ac6e5d0` → `stopped 0ac6e5d0`.

### G1-sharp: Stop-block semantics under the daemon — **CONFIRMED**

Dispatch (BLOCK_ONCE armed, PowerShell, from `spike/m0/proj`, `FLEET_WORKER` intentionally **not** set — see G4 addendum below):
```
New-Item C:\proga\claude-fleet\spike\m0\out\BLOCK_ONCE -ItemType File -Force
claude --bg -n m0-stopblock --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Reply with exactly: FIRST-ANSWER"
```
Dispatch stdout:
```
backgrounded · 55c82a69 · m0-stopblock
```
Roster immediately after dispatch (`claude agents --json --all`, filtered to `m0-*`):
```json
{"pid": 20848, "id": "55c82a69", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "startedAt": 1783976268850, "sessionId": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", "name": "m0-stopblock", "status": "busy", "state": "working"}
```

`spike/m0/out/events.jsonl` for this session (all 3 lines — no tool call in this prompt, so no Pre/PostToolUse):
```json
{"t": 1783976269.0834448, "event": "SessionStart", "env_fleet_worker": null, "env_claude_session": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", "session_id": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", ...}
{"t": 1783976275.2222342, "event": "Stop", "env_fleet_worker": null, "env_claude_session": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", "session_id": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", ...}
{"t": 1783976278.2544858, "event": "Stop", "env_fleet_worker": null, "env_claude_session": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", "session_id": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", ...}
```
`BLOCK_ONCE` existed at dispatch time and was gone by the first poll after the first `Stop` (`Test-Path C:\proga\claude-fleet\spike\m0\out\BLOCK_ONCE` → `False`), confirming `hook_probe.py`'s consume-on-first-Stop logic fired exactly once.

Transcript (`55c82a69-f318-42a7-8b5d-9853dc53b1c5.jsonl`) shows the block reason fed back into the conversation as a synthetic user turn and the model complying with it before the second `Stop`:
```
line 12 (user):      Reply with exactly: FIRST-ANSWER
line 24 (assistant):  FIRST-ANSWER
line 25 (user):      Stop hook feedback:
                     M0 stop-block probe: reply BLOCKED-ACK then stop.
line 30 (assistant):  BLOCKED-ACK
```
This is the exact reason string `hook_probe.py` emits on the consumed `Stop` (`"M0 stop-block probe: reply BLOCKED-ACK then stop."`), proving the daemon delivered the hook's `{"decision":"block","reason":...}` back to the model as a new turn rather than dropping it.

Roster polled twice more (15 s apart) after the second `Stop`, both identical:
```json
{"pid": 20848, "id": "55c82a69", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "startedAt": 1783976268850, "sessionId": "55c82a69-f318-42a7-8b5d-9853dc53b1c5", "name": "m0-stopblock", "status": "idle", "state": "blocked"}
```
Note: the terminal `state` the daemon reports for this session is the literal string `"blocked"`, not `"done"` (contrast `m0-core`'s `"state": "done"` above) — even though `status` correctly reads `"idle"` and no further Stop/hook activity occurred (event count held at 7 total across both sessions for 35+ s, `claude logs 55c82a69` showed the session sitting at an idle prompt, not looping). This is a **naming quirk, not a wedge**: the session is genuinely finished, but a status surface that branches on `state == "done"` to mean "turn complete" would misclassify a session that passed through a Stop-block as still stuck. M1's status/idle-detection logic (SPEC §5 UL1/UL2) must key off `status` (`idle`/`busy`), not assume `state` is only ever `working`/`done`.

Session cleanup: `claude stop 55c82a69` → `stopped 55c82a69`; final roster entry: `{"id": "55c82a69", ..., "name": "m0-stopblock", "state": "stopped"}`.

Two `Stop` events, session survived the first (continued, acknowledged the block reason, replied `BLOCKED-ACK`), second `Stop` passed (BLOCK_ONCE already consumed, no further block decision emitted). **Caveat — one sub-criterion UNOBSERVED:** the brief asked for roster state *during* the block window, but the window was ~3.03 s (first Stop `t=1783976275.222` → second Stop `t=1783976278.254`) against a ~15 s poll cadence — no roster poll landed inside it, and hitting a 3 s window on a 15 s cadence is practically infeasible. The `busy/working` snapshot quoted above is post-dispatch/pre-block, not in-window; the `idle/blocked` snapshots are post-second-Stop. In-window behavior is evidenced only indirectly by the transcript: the model received the block reason as a synthetic user turn and replied `BLOCKED-ACK` *before* the second Stop, which requires the session to have been alive and running through the window. The CONFIRMED verdict therefore rests on the two-Stop-events + continuation evidence; the during-block roster sub-criterion is explicitly UNOBSERVED. No wedge, no HALT. D-series stop-block handling (SPEC's Stop-hook feedback loop) is buildable as designed; flag the `state:"blocked"` terminal-state naming for the status-surface implementation (§5, `docs/specs/terminal-surface.md`).

**G4 addendum (negative control):** Per controller amendment, this dispatch deliberately omitted `$env:FLEET_WORKER = "1"` (confirmed unset in the dispatching shell beforehand — `$env:FLEET_WORKER` printed empty). Every event record for `m0-stopblock` carries `"env_fleet_worker": null` (see the three `events.jsonl` lines quoted above — all three, `SessionStart` and both `Stop`s, show `null`, never `"1"` and never a stale value from the earlier `m0-core` run). This is the expected negative-control result for G4: the daemon does not stamp or inherit `FLEET_WORKER` on its own — it only appears when the dispatching shell sets it, confirming G4's CONFIRMED verdict is not a false positive from ambient environment leakage.

### G8: Prompt delivery of a >32,767-char prompt — argv **REFUTED** / stdin **REFUTED-stdin** / task-file bootstrap **CONFIRMED**

Generator (`spike/m0/gen_bigprompt.py`, committed): builds `("FILLER " * 6000) + "\nIf you can read this, reply with exactly: NEEDLE-9317"`, needle placed at the *end* so truncation is detectable. `py -3.13 C:\proga\claude-fleet\spike\m0\gen_bigprompt.py` printed `42054` (Python `len()`, no trailing newline). PowerShell's own `Get-Content -Raw` measured the same file at `42055` chars (one more — CRLF/EOF-newline counting difference between the writer and the reader, not a content change); both figures are >32,767, satisfying the size gate either way.

**Channel 1 — argv: REFUTED (CreateProcess-level, not PowerShell-level).**

Dispatch attempted (PowerShell, from `spike/m0/proj`):
```
$big = Get-Content ..\out\bigprompt.txt -Raw   # $big.Length = 42055
claude --bg -n m0-g8-argv --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku $big
```
Exact exception surfaced (verbatim):
```
System.Management.Automation.ApplicationFailedException: Program 'claude.exe' failed to run: The filename or extension is too long
 ---> System.ComponentModel.Win32Exception: The filename or extension is too long
    at System.Diagnostics.Process.StartWithShellExecuteEx(ProcessStartInfo startInfo)
    at System.Management.Automation.NativeCommandProcessor.Complete()
```
This is the **Win32 CreateProcess** failure (`ERROR_FILENAME_EXCED_RANGE`, surfaced through .NET's `Process.Start`/`StartWithShellExecuteEx`), not a PowerShell-side argument-parsing error — the distinction the controller flagged as load-bearing for the contract doc. It fires below PowerShell's own layer, meaning no shell-level workaround (quoting, escaping) changes the outcome; the OS command-line buffer for `CreateProcess` (~32K char practical limit on Windows) is the hard ceiling, independent of which shell invokes `claude.exe`.

Confirmed no zombie/partial dispatch: `claude agents --json --all` immediately after showed no `m0-g8-argv` entry at all — the exception was thrown before any child process existed, so no cleanup was required for this channel.

**Channel 2 — stdin: REFUTED-stdin (session created but wedges; never fires SessionStart).**

Dispatch attempted (PowerShell, run inside a background `Start-Job` with a 30s `Wait-Job` guard per the brief's hang rule):
```
Get-Content ..\out\bigprompt.txt -Raw | claude --bg -n m0-g8-stdin --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku
```
The **dispatch command itself did not hang** — it returned inside the 30s window with normal-looking output:
```
backgrounded · f3f760c2 · m0-g8-stdin
  claude agents             list sessions
  claude attach f3f760c2    open in this terminal
  claude logs f3f760c2      show recent output
  claude stop f3f760c2      stop this session
```
But the **spawned session itself never made progress**: no prompt string was given on argv (piped stdin was the only prompt source attempted), and polling `claude agents --json --all` repeatedly showed it wedged for the entire ~171 s observation window (never self-recovered within it; killed manually at the end — not observed to terminate on its own). Roster entry at the ~+25s poll:
```json
{"id": "f3f760c2", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783977197785, "sessionId": "f3f760c2-1b7a-4bd6-9b0a-a9f889f45880", "name": "m0-g8-stdin", "state": "working"}
```
Roster entry at the ~+85s poll, quoted raw for the record (byte-identical — same `startedAt`, same `state`, no `status` field ever appeared):
```json
{"id": "f3f760c2", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783977197785, "sessionId": "f3f760c2-1b7a-4bd6-9b0a-a9f889f45880", "name": "m0-g8-stdin", "state": "working"}
```
`state: working` held identically across all polls, through a final check at **171 s** post-dispatch (`(now_ms - startedAt)/1000 = 170.961`) — never transitioned to `busy`/`idle`/`done`. Across that entire window, `spike/m0/out/events.jsonl` recorded **zero** events for session `f3f760c2` — not even `SessionStart`, which in every other G-series dispatch (G1, G4, G6, G8-file below) fired within 1-5 s. **Method for the zero-events claim:** session_id-filtered match against the shared `events.jsonl` — 0 of the file's 13 lines contain `f3f760c2` (every line carries a `session_id` field; all 13 belong to `0ac6e5d0` / `55c82a69` / `0fba0df4` / `0438096a`). **Concurrency caveat:** no other session was live in the bracketing window — the last event before this dispatch is m0-reap's Stop at `t=1783977002.98`, the next event after it is m0-g8-file's SessionStart at `t=1783977379.75` — so there was no *concurrent* positive control proving the log pipeline was live during those exact 171 s; the zero-events conclusion additionally rests on `hook_probe.py`'s per-invocation append design (each hook invocation appends one line stamped with its own payload's `session_id`, so a fired hook could not have been attributed to another session). No transcript file `f3f760c2-*.jsonl` was ever created under `C:\Users\Techn\.claude\projects\C--proga-claude-fleet-spike-m0-proj\`. This matches the brief's prediction (`--bg` is a PTY TUI dispatch, likely does not read stdin as the prompt) — but the failure mode is a **silent session-level wedge for as long as observed (~171 s, no self-recovery seen)**, not the fast, clean hang the brief's "Ctrl-C within 30s" language anticipated at the *dispatch-command* level. Distinguishing carefully: dispatch-command hang → did not occur (REFUTED as literally worded); session-level liveness → refuted (the session never starts a turn). Recorded verdict: **REFUTED-stdin**, with the caveat that the observed failure is "wedged with zero hook activity for the full observation window" rather than "dispatch call blocks the terminal." Cleaned up via `claude stop f3f760c2` → `stopped f3f760c2`.

**Channel 3 — task-file bootstrap fallback: CONFIRMED (must-pass gate; passed).**

Dispatch (PowerShell, from `spike/m0/proj`):
```
Copy-Item ..\out\bigprompt.txt .\bigtask.md -Force     # 42055 bytes
claude --bg -n m0-g8-file --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read bigtask.md in this directory and follow the instruction at its end."
```
Dispatch stdout: `backgrounded · 0438096a · m0-g8-file`.

`events.jsonl` shows the full expected sequence, fast and complete (~9 s total):
```json
{"t": 1783977379.7519724, "event": "SessionStart", "session_id": "0438096a-00aa-47d5-9698-5d03422e1894", ...}
{"t": 1783977384.1102705, "event": "PreToolUse",  "session_id": "0438096a-00aa-47d5-9698-5d03422e1894", ...}
{"t": 1783977384.5574362, "event": "PostToolUse", "session_id": "0438096a-00aa-47d5-9698-5d03422e1894", ...}
{"t": 1783977388.1883636, "event": "Stop",         "session_id": "0438096a-00aa-47d5-9698-5d03422e1894", ...}
```
(`hook_probe.py` logs `payload_keys` only, not the `last_assistant_message` value itself, so the needle is verified directly from the transcript per the controller's Task-6-substitute instruction, not from the events log.)

Transcript `C:\Users\Techn\.claude\projects\C--proga-claude-fleet-spike-m0-proj\0438096a-00aa-47d5-9698-5d03422e1894.jsonl`, final assistant turn (line 33, `stop_reason: "end_turn"`), quoted verbatim:
```json
{"parentUuid":"50e2e597-b669-4f0c-abd0-46a36df36d50", ..., "message":{"model":"claude-haiku-4-5-20251001","role":"assistant","content":[{"type":"text","text":"NEEDLE-9317"}],"stop_reason":"end_turn", ...},"sessionId":"0438096a-00aa-47d5-9698-5d03422e1894"}
```
The model's reply is the exact literal string `NEEDLE-9317` and nothing else — the needle that sits at the very end of the 42,054/42,055-char file, past 6000 repetitions of `FILLER `. Since the needle is only reachable by reading the file to its end, this is proof the `Read` tool delivered the **entire** oversized file content to the model with no truncation. This is the spec's mandatory G8 fallback and it passed cleanly, so G8 is **not** REFUTED outright — the task-file bootstrap channel is the buildable path for prompts >32,767 chars. Cleaned up via `claude stop 0438096a` → `stopped 0438096a`.

**Net G8 verdict:** argv REFUTED (hard CreateProcess ceiling, ~32K chars, confirmed via exact Win32 error text, no partial/zombie dispatch); stdin REFUTED-stdin (session-level wedge — created, never starts, zero hook activity, confirmed over a 171 s observation window, well past the brief's 30 s hang threshold); task-file bootstrap CONFIRMED (full 42,054-char payload round-tripped intact, needle recovered verbatim from the transcript). **No HALT** — G8 is not a HALT-grade gate per the spec's pre-registered fallback (task-file bootstrap was always the intended production path for large prompts; this run empirically validates it and additionally documents *why* argv/stdin are closed, which the spec's contract doc should cite verbatim). **UNOBSERVED caveat:** the exact byte-for-byte argv ceiling (e.g., is it 32,767, 8,191, or some other OS-reported constant) was not bisected — only that 42,055 chars fails and no smaller value was tested in this task, so the precise threshold is inferred from the well-known Windows `CreateProcess` command-line limit, not measured here.

### G2: Can a second prompt be delivered to an idle `--bg` session? — **CONFIRMED-with-caveat** (outcome (b): fork-with-transcript; steer = fork, overlay must restamp sid) — **HALT-grade: flag for operator ratification at Task 12**

**Deviation from brief (per controller instruction):** the brief's `<m0-core-sid>` (`0ac6e5d0-...` from Task 2) is `state: done`/`stopped` and long-idle; the controller directed dispatching a **fresh** probe session instead (`-n m0-g2`, task "reply DONE-G2") and using its sid. Done below (after two false starts caused by this task's own tooling, recorded honestly as an anomaly, not a G2 hazard).

**Step 1 — candidate-channel enumeration.**

```
claude --help 2>&1 | Select-String -Pattern "resume|send|prompt" -Context 0,2
claude agents --help 2>&1 | Select-String -Pattern "resume|send|dispatch" -Context 0,2
claude attach --help
claude stop --help
claude logs --help
```
(Run via the Bash tool's `grep -n -i -E` against captured help text rather than literal PowerShell `Select-String`, since only PowerShell has a live prompt tree here; content-equivalent, plain-text match on the same three patterns.)

Relevant `claude --help` lines (verbatim, from `claude --help 2>&1`):
```
  --fork-session                        When resuming, create a new session ID
                                        instead of reusing the original (use
                                        with --resume or --continue)
  -p, --print                           Print response and exit (useful for
                                        pipes)... only works with --print elsewhere for --resume interactions
  -r, --resume [value]                  Resume a conversation by session ID, or
                                        open interactive picker with optional
                                        search term
  --bg, --background                    Start the session as a background agent
                                        and return immediately (manage with
                                        `claude agents`)
```
`claude agents --help` has **no** `resume`/`send` flag at all — every `resume|send|dispatch` hit in that help text is just the word "dispatched" inside unrelated option descriptions (`--add-dir`, `--agent`, `--model`, etc., all "for sessions dispatched from agent view"). `claude attach --help`, `claude stop --help`, `claude logs --help` are each a single one-line command with no resume/steer-related flags (`attach <id>` opens the session in-terminal; `stop <id>` stops it; `logs <id>` prints recent output — none accept a new prompt argument).

**Candidate channels identified:** (1) `--bg --resume <sid> "<prompt>"` — background-resume composition; (2) `-p --resume <sid> "<prompt>"` — print-mode resume, with `--fork-session` as an available modifier; no hidden "send"/"push-prompt" subcommand exists anywhere in the enumerated help text.

**Fresh probe dispatch — two false starts (tooling anomaly, recorded per hazard-recording instructions, not a G2 finding):**

First attempt, run via the **Bash tool** (Git Bash) per the brief's literal channel-2 example syntax habit:
```
claude --bg -n m0-g2 --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read task.md in this directory, then reply with exactly: DONE-G2"
```
Dispatch stdout looked normal (`backgrounded · b53f232e · m0-g2`), but the roster immediately showed a **new `state` literal not seen in prior tasks**: `state: "failed"`. Roster entry:
```json
{"id": "b53f232e", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978256217, "sessionId": "b53f232e-f819-4264-b126-9807f5cfb416", "name": "m0-g2", "state": "failed"}
```
`claude logs b53f232e` → `Couldn't read logs for b53f232e — job not found — it may have already exited`. `events.jsonl` session_id-filtered count: `grep -c "b53f232e" spike/m0/out/events.jsonl` = **0** (of 13 lines at that point, all belonging to earlier sessions `0ac6e5d0`/`55c82a69`/`0fba0df4`/`f3f760c2`/`0438096a`). A second attempt with a different name (`m0-g2b`, same Bash-tool invocation pattern) failed identically: roster `state: "failed"`, `claude logs 163f11f2` → `Couldn't read logs for 163f11f2 — connect ENOENT \\.\pipe\cc-daemon-*-control`, 0 matching `events.jsonl` lines. A third attempt (`m0-g2c`) reproduced the same `state: "failed"` outcome, but this time `claude attach 76386689` surfaced the real underlying error (not visible from `claude logs` or the roster):
```
Session 76386689 can't start — exit 1 before init — Error: Settings file not found: ..worker-settings.json
```
Root cause: all three of these dispatches were issued through this session's **Bash tool**, which runs Git Bash `sh -c` — exactly the hazard CLAUDE.md documents ("Hook commands in worker-settings.json use FORWARD slashes (Git Bash `sh -c` eats backslashes)") — except here it ate the backslash in the **CLI argument** `..\worker-settings.json` itself (not inside a hook command), turning it into the literal string `..worker-settings.json`, which the daemon correctly reported as "not found." This is a **self-inflicted dispatch-tooling artifact**, not a G2-relevant daemon behavior — confirmed by the fact that switching to the **PowerShell tool** for the identical command immediately succeeded (see below). All three failed sessions were cleaned up: `claude stop b53f232e` → `stopped b53f232e`; `claude stop 163f11f2` → `stopped 163f11f2`; `claude stop 76386689` → `stopped 76386689` (roster `state` remained the literal `"failed"` after stop, not `"stopped"` — consistent with the pattern noted elsewhere in this file that `stop` on a session that never reached a live/working state does not rewrite `state`).

**Fresh probe dispatch — successful (PowerShell tool, forward-slash-safe):**
```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-g2d --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read task.md in this directory, then reply with exactly: DONE-G2"
```
Stdout: `backgrounded · 80380638 · m0-g2d`. Roster immediately after (busy):
```json
{"pid": 44480, "id": "80380638", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978443413, "sessionId": "80380638-3141-4768-8742-a79257914ffa", "name": "m0-g2d", "status": "busy", "state": "working"}
```
Roster ~8 s later (done):
```json
{"pid": 44480, "id": "80380638", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978443413, "sessionId": "80380638-3141-4768-8742-a79257914ffa", "name": "m0-g2d", "status": "idle", "state": "done"}
```
`events.jsonl` for this sid (4 lines, `session_id` filtered):
```json
{"t": 1783978443.6513352, "event": "SessionStart", "session_id": "80380638-3141-4768-8742-a79257914ffa", ...}
{"t": 1783978450.550122, "event": "PreToolUse", "session_id": "80380638-3141-4768-8742-a79257914ffa", ...}
{"t": 1783978450.7241342, "event": "PostToolUse", "session_id": "80380638-3141-4768-8742-a79257914ffa", ...}
{"t": 1783978456.6789217, "event": "Stop", "session_id": "80380638-3141-4768-8742-a79257914ffa", ...}
```
This is the idle probe session used for Steps 2–3 below. Sid: `80380638-3141-4768-8742-a79257914ffa`.

**Step 2 — `--bg --resume` composition on the idle session.**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg --resume 80380638-3141-4768-8742-a79257914ffa "Reply with exactly: PONG-G2"
```
Stdout (verbatim): `backgrounded · 2e94bbc6` (no `-n` name printed since none was passed this call). Roster **immediately after** (both entries side by side):
```json
{"pid": 44480, "id": "80380638", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978443413, "sessionId": "80380638-3141-4768-8742-a79257914ffa", "name": "m0-g2d", "status": "idle", "state": "done"}
{"pid": 25276, "id": "2e94bbc6", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978497871, "sessionId": "2e94bbc6-5c19-4266-9a16-e4a29a6f267e", "name": "m0-g2d", "status": "busy", "state": "working"}
```
This is the discriminator moment: **a brand-new roster entry appeared** (`sessionId` `2e94bbc6-5c19-4266-9a16-e4a29a6f267e`, new pid `25276`), while the **original entry `80380638-...` was untouched** (`status: idle`, `state: done`, unchanged). This is outcome **(b)**, not (a): a new session id spawned rather than the same session going busy.

Roster ~6 s later, both entries done (name of the new one had already auto-changed — see anomaly note below):
```json
{"pid": 44480, "id": "80380638", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978443413, "sessionId": "80380638-3141-4768-8742-a79257914ffa", "name": "m0-g2d", "status": "idle", "state": "done"}
{"pid": 25276, "id": "2e94bbc6", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978497871, "sessionId": "2e94bbc6-5c19-4266-9a16-e4a29a6f267e", "name": "i need more information about the job t�", "status": "idle", "state": "done"}
```
`events.jsonl` session_id-filtered count for the **original** sid `80380638`: `grep -c "80380638" spike/m0/out/events.jsonl` = **4** (unchanged from before Step 2 — no new turn landed on it). Count for the **new** sid `2e94bbc6`: **0** — expected and not a wedge signal: this dispatch's `--bg --resume` invocation did not repeat `--settings ..\worker-settings.json` (the brief's Step 2 command has no `--settings` flag), so `hook_probe.py` was never wired into the forked session; the absence of events here reflects a config omission, not a liveness failure.

Transcript continuity check — the forked session's transcript file `C:\Users\Techn\.claude\projects\C--proga-claude-fleet-spike-m0-proj\2e94bbc6-5c19-4266-9a16-e4a29a6f267e.jsonl` (42 lines) contains the **entire prior conversation** from `80380638`, verbatim, followed by the new turn:
```
user:      Use the Read tool to read task.md in this directory, then reply with exactly: DONE-G2
assistant: (tool_use Read task.md)
user:      (tool_result: task.md contents)
assistant: DONE-G2
user:      Reply with exactly: PONG-G2
assistant: PONG-G2
```
This proves the fork carried the **full transcript** forward (task.md read + `DONE-G2` reply are present, not just a fresh context), and the new turn's reply is the exact literal `PONG-G2` requested. **Step 2 verdict: CONFIRMED-with-caveat — outcome (b).** `--bg --resume` does not deliver a second prompt to the *same* session; it silently forks a new session id that inherits the full transcript. Any overlay/mailbox design that assumes same-sid continuity across a steer must restamp the sid after every `--bg --resume` call and re-key its own bookkeeping (roster join by `-n`/name survives across the fork here — both entries show `name: "m0-g2d"` immediately after the fork — but see the anomaly below: the name did not stay stable).

**Anomaly (recorded, not scored):** the forked session's `name`/`agent-name` field **changed itself** between the immediately-after-dispatch poll (`"m0-g2d"`) and the done poll (`"i need more information about the job t�"` — a mojibake-truncated auto-generated title). Transcript inspection of the `custom-title`/`agent-name`/`ai-title` records confirms the mechanism: two `custom-title`/`agent-name` entries carry `"m0-g2d"` (inherited from `-n`), then a later `ai-title` entry auto-generates `"i need more information about the job t�"` and overwrites `agent-name` with it. This means **roster join-by-name is not stable across a resumed/forked turn** — the daemon's own auto-titling can silently rename an entry after the fact. Flagging this for M1's roster-join design (join-by-name at dispatch time is fine; joining by name *later*, after an auto-retitle, is not reliable) — **UNOBSERVED:** whether this auto-retitle also happens to non-forked `--bg` sessions given enough turns (only observed here, on a forked session, after its second turn).

**Step 3 — print-mode resume against the daemon-registered session (two-live-claudes hazard).**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude -p --resume 80380638-3141-4768-8742-a79257914ffa "Reply with exactly: PONG-G2P"
```
Exact result (PowerShell wrapped a cosmetic stdin-timing warning as a `NativeCommandError` — same harmless artifact noted in Task 2's report re: `2>&1` capture — the load-bearing line is the `Error:` on the last line):
```
Warning: no stdin data received in 3s, proceeding without it. If piping from a slow command, redirect
stdin explicitly: < /dev/null to skip, or wait longer.
Error: Session 80380638-3141-4768-8742-a79257914ffa is currently running as a background agent (bg). Use
`claude agents` to find and attach to it, or add --fork-session to branch off a copy.
```
**Does it succeed?** No — rejected outright by the CLI before any turn is attempted; the daemon refuses to let `-p --resume` touch a session it still owns (even though that session's roster `status` is `idle`/`state` is `done`, not actively running a turn). The two-live-claudes hazard therefore never materialized — the CLI's own guard prevented it, rather than the daemon needing to detect and reject a live collision after the fact.

**Does the roster reflect the turn?** No turn occurred, so no change expected; confirmed — roster for `80380638` immediately after this command, byte-for-byte identical to the pre-Step-3 snapshot:
```json
{"pid": 44480, "id": "80380638", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978443413, "sessionId": "80380638-3141-4768-8742-a79257914ffa", "name": "m0-g2d", "status": "idle", "state": "done"}
```
**Does the roster entry corrupt?** No — `grep -c "80380638" spike/m0/out/events.jsonl` = **4**, unchanged from the pre-Step-3 count; no fifth event line, no partial/malformed roster JSON on the next poll. **Step 3 verdict: REFUTED** — `-p --resume` against a daemon-owned session is rejected outright (not silently forked, not corrupted); the CLI's own suggested escape hatch (`--fork-session`) was not additionally exercised in this task (out of the brief's literal scope for Step 3; **UNOBSERVED**: whether `-p --resume --fork-session` behaves identically to `--bg --resume`'s silent fork, or differently, was not tested here).

**Net G2 verdict: CONFIRMED-with-caveat — outcome (b) applies.** Of the two live channels enumerated in Step 1: `--bg --resume` **works** but forks (new sid, full transcript carried over, original session's roster entry and events untouched) — CONFIRMED-with-caveat per the brief's outcome (b) wording. `-p --resume` (without `--fork-session`) is flatly **REFUTED** — the CLI refuses it while the daemon owns the session. This is **not** outcome (c) (all channels rejected) — a working steering path exists — but it is also **not** outcome (a) (true same-session turn delivery), so per the brief's own framing this is **HALT-grade: flag for operator ratification at Task 12.** The concrete design implication for the fleet overlay: "steering an idle worker" must be implemented as **fork-and-restamp**, not same-session prompt injection — every `--bg --resume` steer mints a new sid that the overlay must adopt as the worker's new canonical identity (mailbox/journal keyed by name, re-pointed at the new sid; the old sid's transcript remains valid history but stops receiving events). The roster-name instability anomaly above (auto-retitle can silently change `name` after a fork) compounds this: name-based re-identification after a steer is not guaranteed stable either, so the overlay likely needs to capture the **new sid from `--bg --resume`'s own stdout** (it prints the new short id, exactly as `--bg`'s initial dispatch does) rather than re-polling the roster by name after the fact.

Cleanup: `claude stop 80380638` → `stopped 80380638`; `claude stop 2e94bbc6` → `stopped 2e94bbc6` (both roster entries retained `state: "done"` post-stop, not `"stopped"` — consistent with the same already-terminal-state pattern noted for the three failed `m0-g2`/`m0-g2b`/`m0-g2c` dispatches above and for `m0-core` in Task 2). No other session (including `m0-reap`, untouched throughout) was affected.

### G3: Where do result text and cost live for `--bg` sessions? — result text **CONFIRMED** (Stop payload `last_assistant_message` + transcript `message.content[].text`); token usage **CONFIRMED** (transcript `message.usage` only); USD cost **REFUTED-for-contract** (no sanctioned source carries it)

**Method.** Pure inspection, no new sessions dispatched (controller adaptation: brief's `m0-core` is long-stopped; the existing spread of DONE/stopped/blocked/failed `m0-*` sessions is the sample). Sources: (1) full `claude agents --json --all` roster (piped to temp file, parsed `utf-8-sig` per the known PS-pipe BOM hazard) — 17 entries, 9 of them `m0-*`; (2) the six existing transcripts named by `events.jsonl` Stop-event `transcript_path` values (m0-core `0ac6e5d0`, m0-stopblock `55c82a69`, m0-reap `0fba0df4`, m0-g8-file `0438096a`, m0-g2d `80380638`, plus the G2 fork `2e94bbc6`), last ~10 lines each; (3) research-only listings of `~/.claude/jobs/<short-id>/` for three m0 sessions and the `~/.claude/daemon/roster.json` schema (keys only). m0-reap's watcher and all foreign sessions untouched.

**Step 1 — roster: no result, no cost, no tokens, no turn metadata.**

Full key inventory across all 17 current roster entries — every entry's key set is a subset of:
`pid, id, cwd, kind, startedAt, sessionId, name, status, state`
No key resembling result text, cost, tokens, USD, turn count, or duration appears on any entry, in any state. Representative m0 entry (current snapshot, 2026-07-14):
```json
{"id": "0ac6e5d0", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783975710002, "sessionId": "0ac6e5d0-f96f-499a-bac7-d33979e3acc5", "name": "m0-core", "state": "done"}
```
**Roster as result/cost source: REFUTED.**

**Per-state field-presence table (spec §2 requirement).** Sources: current `--all` snapshot (2026-07-14) for done/stopped/failed/interactive rows; live-state rows cite the raw snapshots already quoted verbatim earlier in this file (G6, G1-sharp, G2, G8), values redacted for foreign entries. Y = present, - = absent.

| state literal (context) | pid | name | status | state | sessionId | id | cwd | startedAt | kind |
|---|---|---|---|---|---|---|---|---|---|
| `done` — dead/reaped, current snapshot, 7 entries | - | 6/7¹ | - | Y | Y | Y | Y | Y | `background` |
| `done` — process still live (G6 snapshot of `0ac6e5d0`, 2026-07-13) | Y | Y | Y (`idle`) | Y | Y | Y | Y | Y | `background` |
| `stopped` — current snapshot, 3 entries | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `failed` — current snapshot, 3 entries | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `working` — live (G2 snapshot of `80380638`) | Y | Y | Y (`busy`) | Y | Y | Y | Y | Y | `background` |
| `working` — wedged, never started a turn (G8-stdin snapshot of `f3f760c2`) | - | Y | - | Y | Y | Y | Y | Y | `background` |
| `blocked` — live (G1-sharp snapshot of `55c82a69`) | Y | Y | Y (`idle`) | Y | Y | Y | Y | Y | (not in quote) |
| *(no `state` key at all)* — interactive sessions, 4 foreign entries, values redacted | Y | Y | Y (`busy`×3, `idle`×1) | - | Y | - | Y | Y | `interactive` |

¹ one foreign `done` background entry (short-id `f80a808c`, this repo's cwd, started 4 days ago) has **no `name` key at all** — `name` is not guaranteed even on background entries.

Two structural findings, each on ≥2 snapshots:
- **`pid`/`status` are liveness fields, not state fields.** Same session `0ac6e5d0` observed twice: 2026-07-13 (G6, quoted above in this file) with `"pid": 38072, "status": "idle", "state": "done"`; 2026-07-14 (this task) with **no `pid`, no `status`**, same `state: "done"` (and `startedAt` drifted `1783975713627` → `1783975710002` across the daemon reap — even `startedAt` is not immutable). A consumer must treat `pid`/`status` as present-only-while-the-backing-process-lives, and absence of `status` as "dead, read `state`". The G8-stdin wedge row shows the converse hazard: `state:"working"` with **no** `pid`/`status` means "working" cannot be trusted as "alive" either.
- **`state` vs `status` are disjoint axes with different presence rules**: interactive entries carry `status` only (never `state`, never `id`); dead background entries carry `state` only (never `status`, never `pid`); only live background entries carry both.

**Step 2 — hook payload + transcript: the sanctioned result-text path; tokens yes, USD no.**

Every one of the 6 Stop events in `events.jsonl` (5 sessions; m0-stopblock fired twice) has the identical `payload_keys` set, including both keys that matter here:
```
['background_tasks', 'cwd', 'hook_event_name', 'last_assistant_message', 'permission_mode', 'prompt_id', 'session_crons', 'session_id', 'stop_hook_active', 'transcript_path']
```
- `last_assistant_message` is present in **6/6** Stop payloads. **Caveat — value UNOBSERVED:** `hook_probe.py` logs `payload_keys` only, so its value/shape (string vs object) was never captured in this spike; key presence is confirmed, content is not.
- `transcript_path` is present in 6/6 and every path existed on disk (all six transcripts found, 28–43 lines each).

Transcript tail inspection (last ~10 lines of each of the 6 transcripts). The tail is **not** the assistant message — the final records are `attachment` (hook results), `system/stop_hook_summary`, `system/turn_duration`, and a `last-prompt` index record; a naive "read last line" fails. The final assistant text lives in the **last record with `"type": "assistant"`**, at:
- result text: `message.content[]` where `content[].type == "text"`, key `text` — verified verbatim for all six: `DONE-M0`, `BLOCKED-ACK`, `REAP-BAIT`, `NEEDLE-9317`, `DONE-G2`, `PONG-G2`;
- model: `message.model` — `"claude-haiku-4-5-20251001"` in all six;
- usage: `message.usage`, identical key set in all six:
```
cache_creation, cache_creation_input_tokens, cache_read_input_tokens, inference_geo,
input_tokens, iterations, output_tokens, server_tool_use, service_tier, speed
```
Example (m0-g8-file final assistant record, quoted from the transcript): `"usage": {"input_tokens": 8, "cache_creation_input_tokens": 18935, "cache_read_input_tokens": 39322, "output_tokens": 65, ...}`.
- **USD cost: absent.** Case-insensitive scan for any `*cost*` key over two full transcripts (m0-core, m0-g8-file): **zero hits**. No dollar figure exists in roster, Stop payload key list, or transcript.
- Turn metadata: the `system/turn_duration` record near the tail carries `durationMs` and `messageCount` (e.g. `"durationMs": 6755, "messageCount": 18` for m0-g8-file) — the only turn-level timing found in any sanctioned source.

**Stability caveat (pin-tested, not guaranteed):** all six transcripts are CLI `version: "2.1.207"`. The transcript JSONL format is an unversioned internal contract — key names (`message.content[].text`, `message.usage.input_tokens`, `type: "assistant"`, `subtype: "turn_duration"`) are pin-tested observations at 2.1.207, and the Stop-hook outcome-record implementation must treat them as such (tolerant parsing, feature-detect, fail soft), not as a stable API.

**Step 3 — research-only: `~/.claude/jobs/<short-id>/` and daemon roster schema (no verdict depends on this).**

`~/.claude/jobs/` contains one dir per short-id (13 dirs incl. all m0 sessions, plus `pins.json`). For `0438096a`, `0ac6e5d0`, `80380638`, each dir holds: `state.json` (~1.0–1.2 KB), `timeline.jsonl` (~115–120 B), empty `tmp/`. `state.json` keys (values not relied on): `backend, children, cliVersion, createdAt, cwd, daemonShort, detail, firstTerminalAt, [inFlight,] intent, linkScanOffset, linkScanPath, name, nameSource, output, providerEnv, respawnFlags, resumeSessionId, sessionId, state, template, tempo, tokens, updatedAt`. Notably it has a `tokens` field (a bare number, e.g. `203` — far below the transcript's real token totals, unit/meaning unknown) and an `output` field (observed `null`). `timeline.jsonl` **does** carry the final assistant text in a `text` key (e.g. `{"at": ..., "state": "done", "detail": "...", "text": "DONE-M0"}`) — i.e. a result artifact exists here, but it is an undocumented internal file and per the pre-registered rule **no verdict depends on it**; corroboration only. `~/.claude/daemon/roster.json` schema: top-level keys `proto` (=1), `supervisorPid`, `updatedAt`, `workers` — `workers` was an **empty dict** at observation despite 17 sessions in `agents --json`, so this file is not the roster backing store one might assume; another reason it is unusable as a contract source.

**Sub-verdicts.**
- **(a) Result text — CONFIRMED.** Sanctioned source: **Stop hook payload + transcript**. The Stop payload carries `last_assistant_message` (key present 6/6; value shape UNOBSERVED) and `transcript_path` (6/6, always valid); the transcript's last `type:"assistant"` record carries the final text verbatim at `message.content[].text` (6/6 verified). The roster carries nothing. Design implication for the Stop-hook outcome record: prefer `last_assistant_message` from the payload if its shape checks out at build time, with transcript-tail parse as the verified fallback; never poll the roster for results.
- **(b) Cost — token usage CONFIRMED / USD REFUTED-for-contract.** Token counts (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) live **only** in the transcript's assistant records (`message.usage`), per-API-call; no sanctioned source (roster, Stop payload key set, transcript) carries a USD figure anywhere. USD must be **computed** by the overlay from summed usage × model pricing (`message.model` is in the same record). The only other numeric candidate (`jobs/<id>/state.json` `tokens`) is an unsanctioned internal file and is excluded by the pre-registered rule.

**UNOBSERVED, named:** (1) value/shape of `last_assistant_message` (probe logged keys only); (2) usage aggregation semantics across a multi-assistant-record turn (whether summing per-record `usage` double-counts given the nested `iterations` key — not decomposed here); (3) any state literal other than `done/stopped/failed/working/blocked` (no `killed`/`error` literal seen); (4) `state` field on a live interactive session — never observed, but only 4 foreign samples exist; (5) whether transcript key names survive a CLI version bump (single version 2.1.207 observed). **No HALT** — result text has a working sanctioned path; USD-cost absence is a compute-it-yourself gap, not a blocker, and matches the spec's Stop-hook outcome-record assumption that the hook, not the roster, is the outcome source.
