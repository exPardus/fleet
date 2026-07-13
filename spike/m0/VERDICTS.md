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
