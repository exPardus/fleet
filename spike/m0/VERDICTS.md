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

### G7: Does a `--bg` session survive as a self-driven heartbeat, and what happens to the scheduler when `claude stop` kills it? — heartbeat primitive **CONFIRMED**; same-sid restart anomaly: rate-limit block **CONFIRMED**, resume trigger **UNOBSERVED** (leading hypothesis: operator reply via agents menu — not asserted; daemon-autonomous resume NOT established); post-`stop` scheduler death **CONFIRMED**

**Task/dispatch (by the now-dead originating agent, not reconstructed here).** `spike/m0/proj/heartbeat-task.md`:
```
# Heartbeat probe
1. Append one line containing the current time to `beats.log` in this directory
   (use the Bash tool: `date >> beats.log`).
2. If you have ANY capability to schedule yourself to wake up again in ~2
   minutes (a ScheduleWakeup tool, a /loop skill, a self-reminder), invoke it
   now to repeat step 1. If you have no such capability, reply with exactly:
   NO-SCHEDULER and stop.
```
Dispatched as `-n m0-beat`, sid `8beb709a-bacf-4575-97d3-fdf13176358a`, model haiku, `--settings ..\worker-settings.json --permission-mode acceptEdits`, cwd `spike/m0/proj`.

**Method.** Read-only inspection of three sources for the same sid: (1) `spike/m0/out/events.jsonl` (89 hook events for `8beb709a` at final count: 2 SessionStart + 35 PreToolUse + 35 PostToolUse + 17 Stop), (2) the session's own transcript (307 records, path from any Stop event's `transcript_path`: `C:\Users\Techn\.claude\projects\C--proga-claude-fleet-spike-m0-proj\8beb709a-bacf-4575-97d3-fdf13176358a.jsonl`), (3) the daemon's internal job record `~/.claude/jobs/8beb709a/{timeline.jsonl,state.json}` (unsanctioned per G3's pre-registered rule — corroboration only, no verdict rests solely on it). Then one live action: `claude stop 8beb709a`, followed by a 5-minute poll of `beats.log`'s line count.

**Heartbeat mechanism — CONFIRMED, tool call quoted verbatim.** Every steady-state beat is two assistant turns of one API call each: a `Bash` call (`date >> beats.log`) immediately followed by a `ScheduleWakeup` tool call — exactly 17 of each in the transcript (counted: 17 `ScheduleWakeup` + 17 `Bash` tool_use records), one pair per beat. Exact tool_use input, unchanged across all 17 beats:
```json
{"delaySeconds":120,"prompt":"Read heartbeat-task.md in this directory and follow it.","reason":"Repeating heartbeat probe every ~2 minutes"}
```
Its tool_result, exact text (timestamps vary):
```
Next wakeup scheduled for 03:06:00 (in 166s). Nothing more to do this turn — the harness re-invokes you when the wakeup fires or a task-notification arrives.
```
At the scheduled instant the harness delivers a fresh **user** turn with `isMeta:true`, `promptSource:"system"`, `queuePriority:"later"`, literal content `"Read heartbeat-task.md in this directory and follow it."` — e.g. transcript record 40, `timestamp:"2026-07-13T22:06:00.614Z"`, immediately preceded by two `queue-operation` records at the identical timestamp. This confirms the loop is entirely self-driven: the session's own `ScheduleWakeup` tool call is both necessary and sufficient — no external cron, no fleet-side poller, re-arms the next beat.

**Evidence: 17 beats total, spanning session state (run 1 = 10 beats, run 2 = 7 beats).** `spike/m0/proj/beats.log` final count 17 lines, cross-checked line-for-line against `events.jsonl`'s 17 Stop events for `8beb709a` (03:03:18 → 05:05:12) and the transcript's 17 `Bash`/17 `ScheduleWakeup` tool_use pairs — every `beats.log` timestamp has a matching `PreToolUse(Bash)/PostToolUse/PreToolUse(ScheduleWakeup)/PostToolUse/Stop` quintet in `events.jsonl`, e.g. beat 1: `beats.log` line `"Tue, Jul 14, 2026 03:03:13 AM"` ↔ `events.jsonl` `PostToolUse` at `03:03:13`, `Stop` at `03:03:18`. Cadence measured from `events.jsonl` Stop timestamps in run 1: `03:03:18, 03:06:11, 03:09:11, 03:12:09, 03:15:11, 03:18:10, 03:21:10, 03:24:10, 03:27:11, 03:29:19` — intervals `173, 180, 178, 182, 179, 180, 180, 181, 128` s, mean 173s, range **128–182s**. Eight of nine intervals are `delaySeconds:120` plus ~50–60s harness delivery latency, in the ~3-min band per the brief. **Disclosed outlier:** interval 9→10 is 128s — the 10th beat fired at `03:29:19`, ~51s *before* its scheduled `03:30:00` (the prior tool_result said `"Next wakeup scheduled for 03:30:00"`; the queue-operation records land at `22:29:08.758Z` = 03:29:08 local). Run 2 shows the same early-fire once more (interval `04:57:10→04:59:29` = 139s, against a stated `05:00:00` schedule) — the early-delivery mechanism is **UNOBSERVED** (two occurrences, both ~40–50s early, no pattern derivable from n=2).

**Session-state-between-beats: CONFIRMED context-preserving, not a fresh process per beat.** Each beat's `cache_read_input_tokens` monotonically increases across the whole run (steady-state beats, transcript `message.usage`): `39870 → 40414 → 41692 → 41858 → 42219 → 42338 → …→ 49090 → 49306` — the growing cache-read count is only possible if the same underlying conversation/session context is reused turn over turn; a fresh process per beat would reset it. Steady-state per-beat cost (2 API calls per beat, haiku): call 1 (do the work) `in≈10, out≈200, cache_creation≈120, cache_read≈(running total)`; call 2 (wrap-up text) `in≈8, out≈40, cache_creation≈330, cache_read≈(running total + call-1's cache_creation)`. Example, beat at `23:51` (steady state, post-restart): call 1 `{"input_tokens":10,"output_tokens":203,"cache_creation_input_tokens":119,"cache_read_input_tokens":46751}`; call 2 `{"input_tokens":8,"output_tokens":40,"cache_creation_input_tokens":329,"cache_read_input_tokens":46870}`. **USD cost: same REFUTED-for-contract finding as G3** — no dollar figure in any sanctioned source; only token counts, confirmed here as a second independent sample.

**The same-sid restart anomaly (03:32 → 04:48, 76 min) — the block's cause is CONFIRMED (rate limit killed the loop mid-turn); the resume's trigger is UNOBSERVED, with the evidence leaning toward an operator action, not a daemon auto-retry.**

At the 10th beat's next-scheduled wakeup (`03:32:00`), the harness re-invoked the session normally (transcript record 198, `isMeta` user turn, identical shape to every prior beat), but the API call itself failed. Exact assistant record (transcript record 201, verbatim):
```json
{"model":"<synthetic>","role":"assistant","stop_details":null,"stop_reason":"stop_sequence",
 "content":[{"type":"text","text":"You've hit your session limit — resets 4:40am (Asia/Qyzylorda)"}]},
"error":"rate_limit","isApiErrorMessage":true,"apiErrorStatus":429
```
`usage` on this record is all-zero — no real model call was made. **Critically, this error turn contains no tool_use at all**, so no `ScheduleWakeup` was re-armed: the self-driven loop terminated here, not by the scheduler's own choice but because the 429 pre-empted the turn before the assistant could reach its `ScheduleWakeup` call. This is corroborated independently by `~/.claude/jobs/8beb709a/timeline.jsonl`, whose state transitions from `working` straight to `blocked` at the identical instant (`"at":"2026-07-13T22:32:01.933Z","state":"blocked","detail":"You've hit your session limit · resets 4:40am (Asia/Qyzylorda)"`) — and `state.json`'s `"selfWake": true` / `"inFlight":{"kinds":["session_cron"]}` fields show the daemon *models* this session as a self-waking cron-kind job (which says nothing about who later resumed it — see below), distinct from `--bg --resume` steering (G2).

`beats.log` and `events.jsonl` both go silent for exactly this window (last run-1 Stop `03:29:19`; no SessionStart until `04:48:10` — a 79-minute gap from the 03:29 Stop, 76 minutes from the 03:32 block). The stated reset (`4:40am`) came and went with **no** automatic resume at 4:40 — the actual resume landed 8 minutes later, at `04:48:10`/`23:48:10Z`.

Transcript records 205–207 (verbatim, same `promptId:"2a993c97-fd27-4571-bb96-7caec20f083c"` on both):
```json
{"type":"user","message":{"content":[{"type":"text","text":"Continue from where you left off."}]},
 "isMeta":true,"timestamp":"2026-07-13T23:48:10.741Z"}
{"type":"assistant","message":{"content":[{"type":"text","text":"No response requested."}]},
 "isApiErrorMessage":false,"timestamp":"2026-07-13T23:48:10.741Z"}   // synthetic, all-zero usage
{"type":"user","message":{"content":"continue"},
 "origin":{"kind":"human"},"promptSource":"typed","timestamp":"2026-07-13T23:48:14.901Z"}
```
The second, `"continue"` (promptSource `"typed"`, `origin.kind:"human"`), is the one that actually resumes the loop: the very next assistant record (23:48:18.735Z) is a real haiku call (46,405 cache-creation tokens — a full context re-prime after the idle gap) that re-issues the `Bash`/`ScheduleWakeup` pair and the beat cadence resumes normally from there (7 further beats: `04:48:27, 04:51:07, 04:54:06, 04:57:07, 04:59:25, 05:02:07, 05:05:07` — run 2 total 7, identical shape to run 1).

`~/.claude/jobs/8beb709a/timeline.jsonl` independently records this exact moment as `{"at":"2026-07-13T23:48:15.758Z","state":"blocked","detail":"continue"}` — the daemon's job tracker logs the resume prompt's *text*; it does not record the prompt's author or delivery channel.

**Resume trigger — UNOBSERVED. Evidence, enumerated:**
- **(a) The `"continue"` record is tagged `origin.kind:"human"` / `promptSource:"typed"` — one of exactly two such records in the entire 307-record transcript** (verified by exhaustive scan; the only other is the original dispatch prompt at `22:02:56.698Z`, which was indisputably operator-issued). Every self-wake beat prompt is instead `isMeta:true` / `promptSource:"system"`. On its face this tag family marks operator-typed input, which points *away* from a daemon-autonomous retry.
- **(b) G2's channel enumeration makes a daemon-free same-sid injection surprising:** G2 established that `--bg --resume` silently forks (new sid) and `-p --resume` is rejected outright for daemon-owned sessions. Yet this `"continue"` landed on the *same* sid with no fork (same `8beb709a-bacf-4575-97d3-fdf13176358a` throughout — confirmed by `events.jsonl`'s second SessionStart on the identical `session_id` and `state.json`'s `resumeSessionId == sessionId`). A third, previously-unenumerated same-sid prompt channel therefore exists; the prime candidates are the interactive `claude agents` menu's reply affordance or `claude attach` — i.e. operator-driven TUI paths that G2 never probed.
- **(c) `~/.claude/daemon/pty-pids/` corroborates interactive activity in exactly that minute:** three `.pid` files, all touched at 04:48 (`9fbd1897.pid` and `c04687ad.pid` at `04:48:04`, `2e94bbc6.pid` at `04:48:56`), and **no `8beb709a.pid`**. PTY-pid churn at 04:48:04 — six seconds before the resume record — is consistent with someone opening/driving interactive surfaces at that moment; not decoded further.
- **(d) No daemon log exists to trace delivery:** `~/.claude/daemon/` holds only `control.key`, `pipe.key`, `roster.json`, `dispatch/`, `pty-pids/` — no `.log`.
- Checked and ruled out: the concurrent UI-probe agent (`explore-ui-cli-report.md`) — its own transcript shows it only touched disposable `m0-ui-*` sessions and read `m0-beat`'s roster row read-only, never `--resume`/`attach`/`stop` against `8beb709a`.

**Leading hypothesis (NOT asserted): an operator peek+reply from the agents menu or an attach** — the human/typed tag, the +8min-past-reset timing (4:40 reset, 4:48 resume — human-latency-shaped, not scheduler-shaped), and the 04:48 pty-pids churn all fit it; the controller is asking the operator directly. **Daemon-autonomous resume is NOT established:** `state.json`'s `selfWake:true`/`session_cron` proves only that the daemon *models* the job as self-waking; the timeline's `"continue"` entry records the prompt text, not its author; and the transcript's own tag on the record says human/typed. The `"Continue from where you left off."` isMeta preamble immediately before it (same `promptId`) is an unexplained artifact of whatever channel delivered the pair. **Named UNOBSERVED, not glossed over:** the actual trigger and channel of the `"continue"` delivery at `23:48:14.901Z`.

**Post-`stop` scheduler behavior — CONFIRMED: `claude stop` kills the self-wake loop; it does not survive the process.**

Method: two roster snapshots + a 5-minute `beats.log` poll.

Snapshot 1 (immediately before stop, `2026-07-14 05:05:27 AM`), session mid-loop with a wakeup already queued for `05:08:00` (per the transcript's last tool_result: `"Next wakeup scheduled for 05:08:00 (in 172s)."`, last beat logged `05:05:07`):
```json
{"pid": 47284, "id": "8beb709a", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background",
 "startedAt": 1783986489446, "sessionId": "8beb709a-bacf-4575-97d3-fdf13176358a", "name": "m0-beat",
 "status": "idle", "state": "working"}
```
`claude stop 8beb709a` → exact stdout: `stopped 8beb709a` (run `2026-07-14 05:05:34 AM`).

Snapshot 2 (immediately after stop, same poll):
```json
{"id": "8beb709a", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background",
 "startedAt": 1783980172298, "sessionId": "8beb709a-bacf-4575-97d3-fdf13176358a", "name": "m0-beat",
 "state": "stopped"}
```
Terminal roster state is `"state": "stopped"` — `pid`/`status` both dropped (consistent with G3's dead-entry field-presence table). Note `startedAt` changed value across the stop (`1783986489446` → `1783980172298`), a second independent sample of the drift G3 first flagged.

`beats.log` line count at stop time: 17 lines, last line `"Tue, Jul 14, 2026 05:05:07 AM"`. Polled every 15s for 300s (5 min ≥ one full 172s beat period plus margin) starting `05:05:34`, spanning the already-queued `05:08:00` wakeup: line count and tail unchanged throughout — **no new line appeared**, confirming the queued `05:08:00` wakeup never fired once the backing process was killed. **Verdict: the `ScheduleWakeup` mechanism is entirely within-process — it does not survive `claude stop`, even when a wakeup was already committed/scheduled at stop time.** This directly answers the design-relevant question: fleet's overlay cannot rely on a stopped/killed worker's self-wake continuing in the background; `stop` is a true kill, not a pause.

**Net G7 verdict.** Heartbeat primitive: **CONFIRMED** — `ScheduleWakeup(delaySeconds, prompt, reason)` is a real, working, in-session self-rearming tool; 17 beats observed across two runs (10 + 7) at ~173s mean cadence (range 128–182s, two early-fire outliers disclosed above), session context (cache-read tokens) provably continuous across beats. Same-sid restart anomaly: **rate-limit block CONFIRMED (429 killed the loop mid-turn before `ScheduleWakeup` could re-arm); same-sid non-fork resume CONFIRMED (no new sid minted); resume trigger UNOBSERVED** — evidence (human/typed transcript tag, one of exactly 2 in the file; G2's channel gap; 04:48 pty-pids churn; no daemon log) leans toward an operator reply via the agents menu/attach, which remains a hypothesis pending the operator's own answer; daemon-autonomous resume is NOT established. Post-stop behavior: **CONFIRMED** — `claude stop` terminates the self-wake loop permanently; a previously-scheduled wakeup does not fire after the process is killed (5-minute poll, zero new `beats.log` lines, spanning a wakeup that was already queued at stop time).

Cleanup: only `8beb709a` was targeted by `claude stop`. `m0-reap`, `m0-ui-*`, and all foreign sessions untouched throughout this task.

### G5: Can a `--bg` session be pinned to skip the idle reap, and how wide is the reap window? — pin-scriptability **REFUTED** (no CLI surface exists; TUI-only); the "~1 h idle reap" claim **REFUTED** for done background sessions (persisted ≥3 h 23 min unpinned); process-reap of a *live* idle session remains **UNOBSERVED**

**Sub-verdict (a) — pin scriptability: REFUTED.** Three probes (Phase A, Task 7 report §Step 1), all negative, quoted verbatim:
- `claude pin --help` → exit `0`, but the output was the full top-level `claude --help` (identical to plain `claude --help`), i.e. `pin` fell through as an unrecognized subcommand rather than erroring. Its `Commands:` list has no `pin` entry — the exhaustive list is `agents, auth, auto-mode, doctor, gateway, install, mcp, plugin|plugins, project, setup-token, ultrareview, update|upgrade`.
- `claude agents pin --help` → exit `0`, output was the full `claude agents --help` (identical to plain `claude agents --help`) — `pin` was not recognized as a sub-subcommand either. The verbatim `claude agents` options block (`--add-dir, --agent, --all, --allow-dangerously-skip-permissions, --cwd, --dangerously-skip-permissions, --effort, -h/--help, --json, --mcp-config, --model, --permission-mode, --plugin-dir, --setting-sources, --settings, --strict-mcp-config`) contains no `pin`-named flag.
- `claude agents --help 2>&1 | Select-String -Pattern "pin"` → **empty**, zero matches, re-verified with `Out-String -Width 200 | Select-String` to rule out line-wrap truncation. The substring "pin" appears nowhere in `claude agents --help`, not even inside a longer word.

Exit code `0` on both `--help` probes is not evidence of a working `pin` command — it's an artifact of commander printing help and exiting 0 whenever `--help` is present, regardless of whether the preceding word was a real subcommand. The primary documentation corroborates this (secondary evidence; the REFUTED verdict stands on the three CLI probes alone): `https://code.claude.com/docs/en/agent-view.md`, fetched 2026-07-14 by this task, documents pin exclusively as an **agents-view TUI action** — "Organize the list" section: "Press `Ctrl+T` to pin a session to the top and keep its process running while idle"; keyboard-shortcuts table: "`Ctrl+T` | Pin or unpin the selected session". No CLI/flag pin path appears anywhere on that page. So: there is no `claude ... pin` flag, subcommand, or `--json`-adjacent option anywhere in the scriptable surface. **A fleet overlay cannot pin a session non-interactively; if pinning matters to the design, it requires either driving the interactive TUI (out of scope for a headless daemon-driven overlay) or is simply unavailable to the automation.**

**Sub-verdict (b) — reap window for the ~1 h claim: REFUTED for done background sessions.** Bait session `m0-reap` (short id `0fba0df4`, dispatched `2026-07-14T02:09:47.5367612+05:00`, went `state: "done"` almost immediately — confirmed via roster pull ~4 min post-dispatch, `status: "idle"`, `state: "done"`) was **not pinned** and was tracked two ways:

1. **`spike/m0/reap_watch.ps1`** (unmodified, watcher started `2026-07-14T02:09:58.9202802+05:00`, param `-Hours 2`), polling `claude agents --json --all` for a name match every 600 s. Full log, `spike/m0/out/reap_watch.log`, quoted in full — **12 of 12 polls report `present=True`, zero flips to absent**:
```
2026-07-14T02:10:00.7177509+05:00  present=True
2026-07-14T02:20:02.1392569+05:00  present=True
2026-07-14T02:30:03.6529664+05:00  present=True
2026-07-14T02:40:04.8656050+05:00  present=True
2026-07-14T02:50:06.2451221+05:00  present=True
2026-07-14T03:00:07.6337761+05:00  present=True
2026-07-14T03:10:08.6641792+05:00  present=True
2026-07-14T03:20:09.7276383+05:00  present=True
2026-07-14T03:30:10.9565463+05:00  present=True
2026-07-14T03:40:12.0843373+05:00  present=True
2026-07-14T03:50:13.3712630+05:00  present=True
2026-07-14T04:00:14.7522345+05:00  present=True
```
Honest accounting of the window: the intended deadline was `watcher-start + 2h` = `04:09:58`. The loop's `while (Get-Date) -lt $deadline { poll; sleep 600 }` structure means it evaluates the deadline check *before* each poll, not after the sleep — so after the `04:00:14` poll it slept another 600 s, woke at `~04:10:14`, found that past the `04:09:58` deadline, and exited **without a 13th poll**. That is 12 of a nominally-expected-13 polls; the last *confirmed-present* observation is `04:00:14`, i.e. **1 h 50 min 27 s after dispatch**, not the full 2 h. This report says so plainly rather than rounding up to "ran the full window."

2. **Live roster check performed now, at task time** (`2026-07-14 05:32:49 AM`, per `date`), using the temp-file + `utf-8-sig` recipe (direct-pipe-to-`py` avoided per Task 2's BOM/empty-stdin trap), quoting the exact line returned:
```json
{"id": "0fba0df4", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783976990915, "sessionId": "0fba0df4-5254-48c4-9a16-4a5b22c425a5", "name": "m0-reap", "state": "done"}
```
Still present, `state: "done"` unchanged, **3 h 23 min 2 s after dispatch** (`02:09:47` → `05:32:49`), roughly **3 h 21 min after the session actually finished** (~`02:11`). Note `pid`/`status` are absent from this entry (present at the ~4-min post-dispatch pull, dropped by this later pull) — consistent with G3's dead-entry field-presence pattern (fields drop once a session goes fully terminal/idle-untouched), not evidence of impending eviction.

Both data points — the 12-poll log and this live check — directly contradict the "idle non-pinned sessions reaped after ~1 h" claim being tested: an unpinned, `done`, background session survived unevicted for at least 1 h 50 min under continuous automated observation and was confirmed still present, unpinned, nearly 3.5 h after dispatch on a follow-up spot check. **The ~1 h reap window, as a claim about roster retention of done background sessions, is REFUTED on this machine/CLI version.**

**Two distinct concepts — do not conflate them.** The primary docs (`https://code.claude.com/docs/en/agent-view.md`, fetched 2026-07-14, "The supervisor process" section) state, verbatim: "Once a session finishes and sits unattached for about an hour, the supervisor stops its process to free resources. A session you have pinned with `Ctrl+T` is exempt and keeps its process running while idle. The transcript and state stay on disk either way, and the next time you attach, peek, or reply to a stopped session, the supervisor starts a fresh process from where it left off." — i.e. the documented ~1 h behavior is **process stop with state retained on disk**, not roster eviction; pin governs **process keep-alive**, a different mechanism from **roster retention of a *done* (already-terminated) session**, which is what the bait tested. (This also explains the original research claim's ~1 h figure: it is real, but it is about process stop, not roster removal — the docs' "stay on disk either way" is consistent with our observed ≥3 h 21 min roster persistence.) `m0-reap`'s process had already exited (haiku, single-line reply, terminal in seconds); what persisted for 3+ h was its **roster entry**, not a running process. Whether the daemon reaps the *process* of a live-but-idle (not-yet-done) `--bg` session after ~1 h — the scenario pin's documented behavior actually seems aimed at — is **UNOBSERVED**: no experiment in this spike dispatched a long-lived, never-completing session and watched its process (not just its roster row) for eviction. This is a real gap, not a rounding of the done-session result onto the live-session question.

**Consequence for the spec's heartbeat-period-vs-reap-window fallback.** The spec's fallback (heartbeat period must stay under the reap window, or pin must be used) is **moot for done sessions** — a finished `--bg` session's roster entry does not get reaped inside any window observed here (≥3 h 21 min and counting), so there's no race to guard against for sessions that reach `done` before the next heartbeat. It remains **UNKNOWN for live idle sessions** — if the daemon does reap the *process* of a long-idle-but-not-done session around some window (1 h or otherwise), and pin is genuinely required to prevent that, then the fact that pin has **no scriptable surface** (sub-verdict a) means fleet's supervisor cannot arm it programmatically. This is a live open question, not resolved here: **flagging for Task 12** (same HALT-grade escalation pattern as G2's resume-trigger gap) — before the overlay assumes heartbeats alone are sufficient to keep a long-running interactive-style worker alive, someone needs to either (i) run the live-idle-process reap experiment this spike did not, or (ii) find/confirm an operator-driven pin path is acceptable for the design.

**Evidence discipline.** All quoted material above is copied verbatim from Phase A's report (`.superpowers/sdd/task-7-report.md`), this phase's own `reap_watch.log` read + live roster pull, and a direct fetch of the primary docs page (`https://code.claude.com/docs/en/agent-view.md`, 2026-07-14) — no second-hand doc claims remain; methods are shown (watcher script content already on record in Phase A, live-check recipe named); the one substantive UNOBSERVED (live-idle-session process reap) is named rather than glossed into either verdict.

### G10: `claude stop` mid-turn Stop-hook semantics — **REFUTED** (no Stop hook fires on an external mid-turn stop); raw `taskkill` blast radius — **CONFIRMED zombie hazard** (daemon supervisor auto-respawns the killed process under a new pid, same session id, full new hook cycle)

**Method, Step 1.** Three `--bg` dispatches (PowerShell, from `spike/m0/proj`, `--settings ..\worker-settings.json --permission-mode acceptEdits --model haiku`), each `claude stop`-ped at a different, verified point in its turn, session_id-filtered against `spike/m0/out/events.jsonl` before and after. A fourth, confounded sample is disclosed separately and excluded from the verdict.

**Sample 1 — `m0-g10-stop` (`a3ec4f14`), killed before the assistant produced any turn at all.** Dispatch prompt: `"Use the Bash tool to run: sleep 120. Then reply DONE."` Roster ~15 s post-dispatch (busy/working, i.e. daemon reports it "running"):
```json
{"pid": 33152, "id": "a3ec4f14", ..., "sessionId": "a3ec4f14-53ce-4bbb-bd76-4cac7a58a6e6", "name": "m0-g10-stop", "status": "busy", "state": "working"}
```
`claude stop a3ec4f14` → `stopped a3ec4f14`. Roster immediately after: `{"id": "a3ec4f14", ..., "name": "m0-g10-stop", "state": "stopped"}` (pid/status dropped, per the established dead-entry pattern). `events.jsonl`, session_id-filtered, **1 of 1 lines**, re-checked 20 s later still 1 of 1 — only `SessionStart` ever fired:
```json
{"event": "SessionStart", "session_id": "a3ec4f14-53ce-4bbb-bd76-4cac7a58a6e6", ...}
```
Transcript inspection (`a3ec4f14-...jsonl`, 22 records) confirms why: **zero `"type":"assistant"` records exist** — the model had not yet produced a single turn (no tool_use, no text) when the kill landed; only the dispatched user prompt is on record. **No Stop hook. No PreToolUse/PostToolUse.**

**Sample 2 — `m0-g10-stop3` (`9f18a106`), killed while genuinely mid-turn, blocked on a pending permission prompt.** Same dispatch prompt pattern, substituting a non-guarded long-running command: `"Use the Bash tool to run: ping -n 40 127.0.0.1. Then reply DONE."` Polled `events.jsonl` every 3 s until `PreToolUse` appeared (confirming the tool call had actually started) before stopping — it appeared on the first 3 s poll. Roster at that instant, captured immediately before issuing `stop`:
```json
{"pid": 35620, "id": "9f18a106", ..., "sessionId": "9f18a106-de7d-4353-bcf3-65b314e8cb16", "name": "m0-g10-stop3", "status": "waiting", "waitingFor": "permission prompt", "state": "blocked"}
```
This surfaces a **new roster field not seen in any prior G-task**: `status: "waiting"` / `waitingFor: "permission prompt"` — `--permission-mode acceptEdits` auto-approves file edits but not this Bash command, so the tool call sat pending an approval no headless `--bg` operator can supply; `state: "blocked"` here means "stuck on a permission gate," a second, unrelated meaning for the same `"blocked"` literal G1-sharp used for "passed through a consumed Stop-block" — **the `state` value alone cannot distinguish these two very different situations.** `claude stop 9f18a106` → `stopped 9f18a106`. Roster after: `{"id": "9f18a106", ..., "state": "stopped"}`. `events.jsonl`, session_id-filtered, re-checked 10 s after the stop: **2 of 2 lines**, `SessionStart` + `PreToolUse` only — **no `PostToolUse` (the Bash call never actually ran) and no `Stop`.**

**Sample 3 (confounded, disclosed not scored) — `m0-g10-stop2` (`ca9462d3`).** Same `sleep 120` prompt as Sample 1. This project's own Bash-tool guard intercepted the standalone `sleep 120` call with `"<tool_use_error>Blocked: standalone sleep 120. ... use run_in_background: true.</tool_use_error>"`; the model retried with `run_in_background: true`, which succeeded near-instantly, then replied `"Sleep started (120s). Waiting for completion."` with `stop_reason: "end_turn"` — a **natural** turn completion, not a forced one. `events.jsonl` for this sid does show all four events including `Stop`, but converting the Stop event's epoch (`t=1783990196.056` → local `05:49:56.056`, Asia/Qyzylorda) against the `claude stop` PowerShell call (`$before` captured at local `05:49:55`, command itself taking some further sub-second-to-low-single-digit-second round trip) shows the two are separated by roughly a second either way — **too close to attribute the Stop hook to the kill rather than to the turn's own natural end.** Recorded honestly as **UNOBSERVED/confounded**, not counted toward the verdict either way.

**Method caveat for Step 1's zero-Stop event counts (G8 concurrency-caveat pattern).** Both counts are session_id-filtered matches against the shared `events.jsonl`. Re-derived per-window: window 1 (a3ec4f14 dispatch → post-stop recheck, epoch ~1783990060–1783990135) contains exactly 1 event, a3ec4f14's own `SessionStart` — nearest neighbors are m0-beat's Stop at `t=1783987512` (~41 min earlier) before and ca9462d3's `SessionStart` at `t=1783990179` after; window 2 (9f18a106 dispatch → post-stop recheck, ~1783990295–1783990335) contains exactly 2 events, both 9f18a106's own, bracketed by ca9462d3's Stop at `t=1783990196` and b2079061's `SessionStart` at `t=1783990402`. No other session logged any event inside either window — which also means there was no *concurrent* positive control proving the log pipeline was live during those exact seconds. As in G8, the zero-Stop conclusion additionally rests on `hook_probe.py`'s per-invocation append design (each hook invocation appends one line stamped with its own payload's `session_id`, so a fired Stop hook could not have been attributed to another session), plus the pipeline demonstrably working seconds before and after each window (ca9462d3's and b2079061's complete event sequences at `t=1783990179–196` and `t=1783990402+`).

**Step 1 net verdict: REFUTED — an externally issued `claude stop` against a session that has not yet naturally ended its turn does not fire a Stop hook**, confirmed on two independent, unconfounded samples (pre-turn-start kill; mid-turn permission-pending kill), both showing the process transition straight to roster `state: "stopped"` with zero corresponding `Stop` event in `events.jsonl`, even after a 10-20 s settle-and-recheck window. This is the exact design-critical result the brief flagged: **the outcome discriminator cannot rely on the Stop hook to record an outcome for an operator-stopped worker — a stopped session with no Stop-hook record is a real, reproducible case, not a hypothetical, so spec §5's stop-then-mark flow must write its own tombstone rather than assume the Stop hook will have already done so.**

**Step 2 — raw `taskkill`, the blast radius.** Dispatch `m0-g10-kill` (`b2079061`), same `ping -n 40 127.0.0.1` prompt, polled to confirm `PreToolUse` fired (mid-turn, same permission-pending shape as Sample 2 above). Roster pre-kill:
```json
{"pid": 25080, "id": "b2079061", ..., "name": "m0-g10-kill", "status": "waiting", "waitingFor": "permission prompt", "state": "blocked"}
```
`taskkill /PID 25080 /F` → `SUCCESS: The process with PID 25080 has been terminated.` Roster snapshot 1 (~6 s later): `pid`/`status` dropped, `state: "blocked"` retained (stale — not yet reconciled to reflect the dead process):
```json
{"id": "b2079061", ..., "name": "m0-g10-kill", "state": "blocked"}
```
Roster snapshot 2 (~36 s after the kill, ~30 s after snapshot 1 — the second required ≥2-snapshots-≥30s-apart poll): **a new `pid` appears on the identical `id`/`sessionId`/`name`**:
```json
{"pid": 45592, "id": "b2079061", "startedAt": 1783990434737, "sessionId": "b2079061-58c9-4453-8eed-72c96e967a0f", "name": "m0-g10-kill", "status": "waiting", "waitingFor": "permission prompt", "state": "blocked"}
```
**`startedAt` disclosure — a 3-way drift, demoted from corroboration.** Across the five snapshots this session's `startedAt` took three distinct values: pre-kill live read `1783990402672` (pid 25080); snapshot-1 dead-entry read `1783990401412` (+6 s, no pid — **this hop happened with NO respawn**, the process was simply dead and not yet restarted); post-respawn live reads `1783990434737` (snapshots 2 and 3, pid 45592); and the post-cleanup final read **reverted** to `1783990401412` again. So `startedAt` jitters between values on transitions that involve no respawn at all (kill→dead-read, stop→final-read) — consistent with, and extending, the drift G3 and G7 each flagged once. **New contract fact: nothing may key on `startedAt` stability — it is not an immutable dispatch timestamp; it changes value across liveness transitions of the same session even without a respawn.** Consequently `startedAt` is *not* used as respawn evidence here; the respawn conclusion rests entirely on the process receipts and the re-fired hook pair below. `tasklist /FI "PID eq 25080"` → `INFO: No tasks are running which match the specified criteria.` (old pid genuinely dead); `tasklist /FI "PID eq 45592"` → a live `claude.exe`, 408 MB resident (new pid genuinely alive). `events.jsonl`, session_id-filtered for `b2079061`: **4 of 4 lines** — the original `SessionStart`/`PreToolUse` pair, **then a second `SessionStart` at `t=1783990435.826` and a second `PreToolUse` at `t=1783990442.233`, both carrying the exact same `session_id`**:
```json
{"event": "SessionStart", "session_id": "b2079061-58c9-4453-8eed-72c96e967a0f", "payload_keys": ["cwd", "hook_event_name", "session_id", "session_title", "source", "transcript_path"], ...}
{"event": "PreToolUse", "session_id": "b2079061-58c9-4453-8eed-72c96e967a0f", ...}
```
(Note: this second `SessionStart`'s `payload_keys` is missing `model` — present on every first-dispatch `SessionStart` recorded elsewhere in this file — a small but real payload-shape difference on a daemon-driven respawn vs. a fresh CLI dispatch, worth a feature-detect/tolerant-parse note alongside G3's stability caveat.)

**Does the roster mark it failed/done?** No — `state` read `"blocked"` at every poll taken (stale snapshot 1, then live-and-current at snapshot 2); the literal `"failed"` was never observed for this session **at our poll cadence**. Scoping that claim honestly: the five roster reads were spaced ~10 s / 48 s / 48 s / 7 s apart (snapshot-file mtimes 05:53:39 → :49 → 05:54:37 → 05:55:25 → :32), so a transient `"failed"` (or any other literal) flashing between polls — in particular inside the 48 s gap during which the respawn itself happened — is **UNOBSERVED**, not ruled out. The supported claim is "never observed at this cadence," not "never entered." **Does the daemon respawn it?** **Yes — confirmed**, on two independent legs: (1) process receipts — `tasklist` shows old pid 25080 dead and new pid 45592 a live `claude.exe`, with the roster binding pid 45592 to the same `id`/`sessionId`/`name`; (2) the re-fired `SessionStart`+`PreToolUse` hook pair on the identical `session_id`. (`startedAt` deliberately excluded as evidence per the drift disclosure above.) **Does the roster corrupt?** No — every poll across the whole sequence (pre-kill, +6 s, +36 s, post-cleanup) returned a single well-formed JSON object for `b2079061`, in every case a strict subset of the known key set; no malformed/partial/duplicate entries.

**This is the zombie hazard named in the brief, empirically confirmed, not hypothetical:** a raw `taskkill` against a fleet-managed session's pid does **not** durably stop it — the daemon supervisor detects the dead child and silently restarts the identical session (same sid), which then re-fires `SessionStart`/`PreToolUse` and resumes sitting on the same pending permission prompt. An operator (or a buggy overlay) that raw-kills a worker believing it is now dead is wrong within the observed ~30 s window; any process-liveness check keyed on the old pid would report "gone" while the session is, from the daemon's perspective, still alive and about to be re-driven. **This is the concrete, machine-verified reason CLAUDE.md's rule ("fleet must never do this") is a hard rule and not just caution** — the failure mode is not "the session dies cleanly," it's "the session comes back under your feet with a new pid, silently." The resurrected session was cleanly `claude stop`-ped afterward (`stopped b2079061`) rather than left running or re-killed raw.

**UNOBSERVED, named:** (1) how many times the daemon will keep respawning a raw-killed session if left unattended past the ~30 s window observed here — only one respawn cycle was captured before this task intervened with a clean `stop`; (2) whether the respawn behavior differs for a session that was actively executing a tool (not just pending on a permission prompt) at kill time; (3) exact reconciliation latency between the kill and the roster reflecting the new pid — bounded here only to "somewhere between +6 s (still showing dead-stale `state`, no `pid`) and +36 s (new pid live)," not measured more precisely.

Cleanup: `a3ec4f14`, `ca9462d3`, `9f18a106`, `b2079061` all confirmed `state: "stopped"` in a final roster pass. No foreign session or other `m0-*` husk touched.

### G12: live-verify `claude rm` as the archival primitive (spec §5.1.2) — **CONFIRMED** (roster entry removed, `~/.claude/jobs/<short-id>/` directory removed, no errors, no collateral changes)

**Target.** `b53f232e` (`m0-g2`), the disposable `state: "failed"` husk from Task 5/G2's documented false starts (see the G2 section above — one of three dispatches that hit the Git-Bash backslash-eating hazard).

**Pre-state.** Roster (`--json --all`, 24 total entries), filtered to `id == "b53f232e"`:
```json
{"id": "b53f232e", "cwd": "C:\\proga\\claude-fleet\\spike\\m0\\proj", "kind": "background", "startedAt": 1783978256217, "sessionId": "b53f232e-f819-4264-b126-9807f5cfb416", "name": "m0-g2", "state": "failed"}
```
`~/.claude/jobs/b53f232e/` (research-only, per G3's pre-registered rule) exists and contains `tmp/` (empty dir), `recap.trigger` (0 bytes), `state.json` (904 bytes) — note **no `timeline.jsonl`** here, unlike the three `jobs/<id>/` dirs sampled in G3 (`0438096a`, `0ac6e5d0`, `80380638`, all of which had one); this failed-at-dispatch session apparently never got far enough to produce a timeline, and has a `recap.trigger` file not seen in any of G3's samples.

**Command and exact output.** `claude rm --help`:
```
Usage: claude rm <id>

  Delete a background session and its worktree. Unlike `stop`, works on already-exited sessions.
```
`claude rm b53f232e` → exact stdout: `removed b53f232e`. No error, no prompt, no warning.

**Post-state.** Roster (`--json --all`, 23 total entries — exactly one fewer than pre-state), filtered to `id == "b53f232e"`: **zero matches.** Set-difference of pre/post roster ids confirms **exactly one** id removed (`{'b53f232e'}`) and **zero** ids added — no collateral roster change. `Test-Path ~/.claude/jobs/b53f232e` → `False` — the job directory (and everything under it: `tmp/`, `recap.trigger`, `state.json`) is gone.

**Verdict: CONFIRMED.** `claude rm <id>` is a clean, working archival primitive for spec §5.1.2: it removes exactly the targeted roster entry (no partial/corrupted state on the 23 remaining entries) and deletes the backing `~/.claude/jobs/<short-id>/` directory (research-only observation, consistent with the "delete a background session and its worktree" help text), with no error output on a `failed`-state, long-dead target. **UNOBSERVED, named:** (1) `claude rm` against a *live* (still-running) session — not tested, `--help` text doesn't say whether it force-stops first or refuses; (2) `claude rm` against a session that doesn't exist / already removed — idempotency/error-message shape untested; (3) whether `rm` also clears the session's transcript under `~/.claude/projects/<cwd-slug>/<sid>.jsonl` (out of scope for this check — not probed).

Cleanup: none required — `b53f232e` was already terminal (`failed`) before removal; no other session touched by this step.
