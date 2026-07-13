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
