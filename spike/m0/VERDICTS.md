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
