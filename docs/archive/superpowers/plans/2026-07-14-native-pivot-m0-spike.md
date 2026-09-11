# Native Pivot M-0 Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the G1–G10 experiments from spec §2, producing `docs/specs/native-substrate.md` — the contract doc that confirms or refutes every load-bearing native-surface assumption before any pivot code is built.

**Architecture:** A tracked `spike/m0/` harness (hook probe script, worker settings, scratch project) dispatches disposable haiku background sessions via `claude --bg` and records what actually happens in `spike/m0/out/events.jsonl` and `spike/m0/VERDICTS.md`. The final tasks promote verdicts into the contract doc and run the operator gate review. Spike artifacts are kept — they seed the M-B pin-test tier.

**Tech Stack:** `py -3.13` (stdlib only), PowerShell, `claude` CLI (`--bg`, `agents --json`, `stop/logs/attach`), haiku model for all dispatched sessions.

## Global Constraints

- Spec of record: `docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md` v2.2 (ready-for-plan). G-table + halt vocabulary in §2.
- Python is `py -3.13` (bare `python` resolves to 3.10). Stdlib only.
- Hook commands in settings JSON use FORWARD slashes (Git Bash `sh -c` eats backslashes).
- Never launch background processes via Git-Bash `&` — `claude --bg` and `Start-Process`/detached flags only.
- `~/.claude/daemon/` and `~/.claude/jobs/` may be **inspected read-only for research** in this spike; no experiment may write to them, and no verdict may depend on their contents (contract = CLI + `--json` only).
- Every dispatched session: model haiku, name prefixed `m0-`, cwd `spike/m0/proj/`. Clean up (`claude stop`) at each task's end.
- Every experiment ends by appending its verdict to `spike/m0/VERDICTS.md` (`### G<N>: CONFIRMED | REFUTED | DISPUTED — evidence`) and committing.
- G9 (daemon kill) is destructive to ALL background sessions on the machine — it runs LAST and only after the operator confirms no foreign sessions are live.
- HALT / HALT-grade / no vocabulary per spec §2: a REFUTED HALT item stops the spike and escalates to the operator immediately.

---

### Task 1: Spike harness scaffolding

**Files:**
- Create: `spike/m0/hook_probe.py`
- Create: `spike/m0/worker-settings.json`
- Create: `spike/m0/proj/task.md`
- Create: `spike/m0/VERDICTS.md`
- Create: `spike/m0/.gitignore`
- Test: standalone invocation of `hook_probe.py` (below)

**Interfaces:**
- Produces: `hook_probe.py <EventName>` — reads a hook JSON payload on stdin, appends one JSON line to `spike/m0/out/events.jsonl` with fields `t, event, env_fleet_worker, env_claude_session, session_id, transcript_path, cwd, payload_keys`. If invoked as `Stop` while `spike/m0/out/BLOCK_ONCE` exists, deletes that marker and emits `{"decision": "block", "reason": "M0 stop-block probe: reply BLOCKED-ACK then stop."}` on stdout (exit 0). All later tasks read `out/events.jsonl`.

- [ ] **Step 1: Write `spike/m0/hook_probe.py`**

```python
"""M-0 spike hook probe. Appends one JSON line per hook event.

Usage in settings hooks: py -3.13 C:/proga/claude-fleet/spike/m0/hook_probe.py <EventName>
Stop-block experiment: create out/BLOCK_ONCE; the next Stop event consumes it
and emits a block decision.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "out"
OUT_DIR.mkdir(exist_ok=True)
EVENTS = OUT_DIR / "events.jsonl"
BLOCK_ONCE = OUT_DIR / "BLOCK_ONCE"

def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else "?"
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    rec = {
        "t": time.time(),
        "event": event,
        "env_fleet_worker": os.environ.get("FLEET_WORKER"),
        "env_claude_session": os.environ.get("CLAUDE_CODE_SESSION_ID"),
        "session_id": payload.get("session_id"),
        "transcript_path": payload.get("transcript_path"),
        "cwd": payload.get("cwd"),
        "payload_keys": sorted(payload.keys()),
    }
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    if event == "Stop" and BLOCK_ONCE.exists():
        BLOCK_ONCE.unlink()
        print(json.dumps({
            "decision": "block",
            "reason": "M0 stop-block probe: reply BLOCKED-ACK then stop.",
        }))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write `spike/m0/worker-settings.json`** (forward slashes — global constraint)

```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "py -3.13 C:/proga/claude-fleet/spike/m0/hook_probe.py SessionStart"}]}
    ],
    "PreToolUse": [
      {"matcher": "", "hooks": [{"type": "command", "command": "py -3.13 C:/proga/claude-fleet/spike/m0/hook_probe.py PreToolUse"}]}
    ],
    "PostToolUse": [
      {"matcher": "", "hooks": [{"type": "command", "command": "py -3.13 C:/proga/claude-fleet/spike/m0/hook_probe.py PostToolUse"}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "py -3.13 C:/proga/claude-fleet/spike/m0/hook_probe.py Stop"}]}
    ]
  }
}
```

- [ ] **Step 3: Write `spike/m0/proj/task.md`**

```markdown
# M-0 probe task
You are a disposable probe session. Use the Read tool to read this file, then
reply with exactly: DONE-M0
```

- [ ] **Step 4: Write `spike/m0/VERDICTS.md`**

```markdown
# M-0 G-table verdicts (working log)
Spec: docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md §2.
One `### G<N>:` section per experiment, appended as executed.
Vocabulary: CONFIRMED / REFUTED / DISPUTED — evidence quoted inline.
```

- [ ] **Step 5: Write `spike/m0/.gitignore`**

```
out/
```

- [ ] **Step 6: Test hook_probe standalone**

Run (PowerShell):
```powershell
'{"session_id": "test-123", "cwd": "X"}' | py -3.13 C:\proga\claude-fleet\spike\m0\hook_probe.py PreToolUse
Get-Content C:\proga\claude-fleet\spike\m0\out\events.jsonl -Tail 1
```
Expected: one JSON line, `"event": "PreToolUse"`, `"session_id": "test-123"`.

Then the Stop-block path:
```powershell
New-Item C:\proga\claude-fleet\spike\m0\out\BLOCK_ONCE -ItemType File
'{}' | py -3.13 C:\proga\claude-fleet\spike\m0\hook_probe.py Stop
Test-Path C:\proga\claude-fleet\spike\m0\out\BLOCK_ONCE
```
Expected: stdout prints the block JSON; `Test-Path` prints `False`.

- [ ] **Step 7: Commit**

```bash
git add spike/m0/
git commit -m "spike(m0): harness — hook probe, worker settings, scratch project"
```

---

### Task 2: Core dispatch experiment — G6 (sid mint), G4 (env), G1 (hooks fire)

One dispatched session answers three gates.

**Files:**
- Modify: `spike/m0/VERDICTS.md` (append G6, G4, G1 sections)

**Interfaces:**
- Consumes: Task 1 harness.
- Produces: verdicts G1 (HALT), G4 (HALT), G6 — and the dispatched session's sid for Task 3.

- [ ] **Step 1: Clear state, dispatch with minted sid + env markers**

Run (PowerShell):
```powershell
Remove-Item C:\proga\claude-fleet\spike\m0\out\events.jsonl -ErrorAction SilentlyContinue
$env:FLEET_WORKER = "1"
Remove-Item Env:CLAUDE_CODE_SESSION_ID -ErrorAction SilentlyContinue
$sid = [guid]::NewGuid().ToString()
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-core --session-id $sid --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read task.md in this directory, then follow it."
"minted sid: $sid"
```
Expected: `--bg` accepts all flags and prints a short id + `claude attach/logs/stop` hints. If any flag is rejected, record REFUTED for that gate with the exact error and continue with the flag dropped.

- [ ] **Step 2: Verify roster identity (G6)**

Run:
```powershell
claude agents --json --all | py -3.13 -c "import json,sys; [print(json.dumps(s, indent=1)) for s in json.load(sys.stdin) if s.get('name','').startswith('m0-')]"
```
Expected for CONFIRMED: entry with `sessionId` equal to the minted `$sid` (not merely prefixed). Record G6 verdict.

- [ ] **Step 3: Wait for completion, read events (G1, G4)**

Run (repeat until the session shows `state: done`, ~1–2 min):
```powershell
claude agents --json --all | py -3.13 -c "import json,sys; [print(s.get('name'), s.get('status'), s.get('state')) for s in json.load(sys.stdin) if s.get('name','').startswith('m0-')]"
Get-Content C:\proga\claude-fleet\spike\m0\out\events.jsonl
```
Expected for G1 CONFIRMED: events for `SessionStart`, `PreToolUse` (the Read), `PostToolUse`, `Stop`, each with `session_id` == minted sid.
Expected for G4: inspect `env_fleet_worker` and `env_claude_session` in the records. CONFIRMED = `env_fleet_worker == "1"` (dispatching shell's env reached the daemon-spawned child) and `env_claude_session` is null or the worker's own sid — NOT an inherited foreign sid. If `env_fleet_worker` is null, env does NOT propagate through the daemon: record G4 REFUTED (**HALT — escalate to operator before continuing; spec §2 G4 has no fallback**).
Also record: full `payload_keys` list per event (raw material for G3).

- [ ] **Step 4: Append G6/G4/G1 verdicts to VERDICTS.md, with evidence lines quoted. Commit**

```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdicts G1/G4/G6 — core dispatch experiment"
```

---

### Task 3: G1-sharp — Stop-block semantics under the daemon

**Files:**
- Modify: `spike/m0/VERDICTS.md` (append G1-sharp section)

**Interfaces:**
- Consumes: Task 2's still-registered `m0-core` session (or dispatch a fresh `m0-stopblock` the same way).
- Produces: verdict G1-sharp (stop-block honored? roster state during block?).

- [ ] **Step 1: Arm the block, dispatch**

```powershell
New-Item C:\proga\claude-fleet\spike\m0\out\BLOCK_ONCE -ItemType File -Force
$env:FLEET_WORKER = "1"
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-stopblock --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Reply with exactly: FIRST-ANSWER"
```

- [ ] **Step 2: Observe the block cycle**

Poll every ~15 s:
```powershell
claude agents --json --all | py -3.13 -c "import json,sys; [print(s.get('name'), s.get('status'), s.get('state')) for s in json.load(sys.stdin) if s.get('name','').startswith('m0-')]"
Get-Content C:\proga\claude-fleet\spike\m0\out\events.jsonl -Tail 5
```
Expected for CONFIRMED: two `Stop` events (first consumed BLOCK_ONCE and blocked; session continued — the model acknowledged the block reason — then second Stop passed). Roster shows the session as working/busy during the block window, idle/done after.
REFUTED if: only one Stop event and the session ends anyway (block ignored), or the session wedges (daemon idle-detection conflicts with stop-block — record exact observed state).

- [ ] **Step 3: Stop the session, append verdict, commit**

```powershell
claude agents --json --all | py -3.13 -c "import json,sys; [print(s['id']) for s in json.load(sys.stdin) if s.get('name')=='m0-stopblock']"
claude stop <that-id>
```
```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G1-sharp — stop-block under daemon"
```

---

### Task 4: G8 — prompt delivery size

**Files:**
- Create: `spike/m0/gen_bigprompt.py`
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Produces: verdict G8 — which channels carry a >32,767-char prompt: argv / stdin / task-file bootstrap.

- [ ] **Step 1: Write `spike/m0/gen_bigprompt.py`**

```python
"""Generate a >32k-char prompt whose successful delivery is provable:
the needle sits at the END, so truncation is detectable."""
from pathlib import Path

body = ("FILLER " * 6000) + "\nIf you can read this, reply with exactly: NEEDLE-9317"
assert len(body) > 40_000
Path(__file__).parent.joinpath("out", "bigprompt.txt").write_text(body, encoding="utf-8")
print(len(body))
```

Run: `py -3.13 C:\proga\claude-fleet\spike\m0\gen_bigprompt.py` — expected: prints a number > 40000.

- [ ] **Step 2: Attempt argv delivery**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
$big = Get-Content ..\out\bigprompt.txt -Raw
claude --bg -n m0-g8-argv --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku $big
```
Expected: either a CreateProcess/command-line-too-long error (argv REFUTED for >32k) or a dispatch. If dispatched, verify via Task 6's result channel that the reply contains `NEEDLE-9317` (truncation check).

- [ ] **Step 3: Attempt stdin delivery**

```powershell
Get-Content ..\out\bigprompt.txt -Raw | claude --bg -n m0-g8-stdin --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku
```
Expected: record whether `--bg` reads stdin at all (likely not — it is a PTY TUI dispatch). Any hang > 30 s = Ctrl-C and record REFUTED-stdin.

- [ ] **Step 4: Verify the fallback: task-file bootstrap**

```powershell
Copy-Item ..\out\bigprompt.txt .\bigtask.md
claude --bg -n m0-g8-file --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read bigtask.md in this directory and follow the instruction at its end."
```
Expected: session completes; reply contains `NEEDLE-9317` (confirm via events/result channel in Task 6). This is the spec's G8 fallback — it must pass; if even this fails, G8 is REFUTED outright (escalate).

- [ ] **Step 5: Stop all `m0-g8-*` sessions, append G8 verdict (per-channel), commit**

```bash
git add spike/m0/gen_bigprompt.py spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G8 — prompt delivery channels"
```

---

### Task 5: G2 — second-prompt delivery to an idle bg session

**Files:**
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Consumes: a done-but-registered `m0-core` session sid from Task 2 (or dispatch a fresh one).
- Produces: verdict G2 (HALT-grade) — the steering path for idle workers.

- [ ] **Step 1: Enumerate candidate channels**

```powershell
claude --help 2>&1 | Select-String -Pattern "resume|send|prompt" -Context 0,2
claude agents --help 2>&1 | Select-String -Pattern "resume|send|dispatch" -Context 0,2
claude attach --help
claude stop --help
claude logs --help
```
Record every relevant flag (hidden commands have help — Task 2's `--bg` output hinted them).

- [ ] **Step 2: Try `--bg --resume` composition on the idle session**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg --resume <m0-core-sid> "Reply with exactly: PONG-G2"
```
Expected outcomes to record: (a) new turn lands on the SAME session (roster same id goes busy; a new `PreToolUse`/`Stop` event pair with the same session_id in events.jsonl) = G2 CONFIRMED; (b) a NEW session id spawns with the old transcript = record as CONFIRMED-with-caveat (steer = fork; overlay must restamp sid); (c) rejected = continue.

- [ ] **Step 3: Try print-mode resume against a daemon-registered session**

```powershell
claude -p --resume <m0-core-sid> "Reply with exactly: PONG-G2P"
```
CAUTION: this is the two-live-claudes-one-session hazard — acceptable only because the session is idle/done and disposable. Record: does it succeed, does the daemon roster reflect the turn, does the roster entry corrupt?

- [ ] **Step 4: Append G2 verdict + which fallback applies, commit**

If all channels REFUTED: G2 verdict = REFUTED, fallback = respawn-to-steer per spec G2 row — **HALT-grade: flag for operator ratification in Task 10, do not silently proceed.**

```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G2 — idle steering channels"
```

---

### Task 6: G3 — result and cost source

**Files:**
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Consumes: done `m0-*` sessions from Tasks 2–5; their `payload_keys` records.
- Produces: verdict G3 — where result text and cost live; feeds the Stop-hook outcome-record design (spec §5).

- [ ] **Step 1: Roster fields on done sessions**

```powershell
claude agents --json --all | py -3.13 -c "import json,sys; [print(json.dumps(s, indent=1)) for s in json.load(sys.stdin) if s.get('name','').startswith('m0-')]"
```
Record: any field carrying result text, cost, tokens, or turn metadata. Also pin the field-presence-per-state table (spec §2 requires it): which of `pid/name/status/state/sessionId` appear for done vs busy vs interactive entries.

- [ ] **Step 2: Hook payload as the source**

From Task 2's events.jsonl `payload_keys`: does the Stop payload include `transcript_path`? Then:
```powershell
py -3.13 -c "import json,sys; from pathlib import Path; lines=[json.loads(l) for l in Path(r'C:\proga\claude-fleet\spike\m0\out\events.jsonl').read_text(encoding='utf-8').splitlines()]; stops=[r for r in lines if r['event']=='Stop']; print(stops[-1]['transcript_path'])"
```
Read the transcript's LAST few lines only (research inspection): does it contain the final assistant text and a cost/usage field? Record exact key names and a stability caveat (transcript format unstable — contract must treat key names as pin-tested, not guaranteed).

- [ ] **Step 3: Research-only inspection of `~/.claude/jobs/<id>/`**

```powershell
Get-ChildItem ~/.claude/jobs/<m0-core-short-id>/ -Recurse | Select-Object FullName, Length
```
Record what exists (state.json? result file?). REMINDER: research only — no verdict may DEPEND on these files; if the only cost source is a jobs/ file, G3's verdict is REFUTED-for-contract with a note.

- [ ] **Step 4: Append G3 verdict — name the sanctioned source for (a) result text, (b) cost — plus the per-state field table. Commit**

```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G3 — result/cost source + per-state roster fields"
```

---

### Task 7: G5 — pin scriptability and the reap window (start early; runs in background ~2 h)

**Files:**
- Create: `spike/m0/reap_watch.ps1`
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Produces: verdict G5 — scriptable pin yes/no; measured reap window for an idle done session.

- [ ] **Step 1: Probe pin surface**

```powershell
claude pin --help
claude agents pin --help
claude agents --help 2>&1 | Select-String -Pattern "pin"
```
Record: any scriptable pin = CONFIRMED (quote syntax). All rejected = REFUTED (fallback per spec: heartbeat-respawn primary).

- [ ] **Step 2: Write `spike/m0/reap_watch.ps1`**

```powershell
# Polls the roster every 10 min; logs presence of the named m0 session.
param([string]$Name = "m0-reap", [int]$Hours = 2)
$log = "C:\proga\claude-fleet\spike\m0\out\reap_watch.log"
$deadline = (Get-Date).AddHours($Hours)
while ((Get-Date) -lt $deadline) {
    $json = claude agents --json --all | Out-String
    $found = $json -match $Name
    Add-Content $log ("{0}  present={1}" -f (Get-Date -Format o), $found)
    Start-Sleep -Seconds 600
}
```

- [ ] **Step 3: Dispatch the bait session + start the watcher**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-reap --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Reply with exactly: REAP-BAIT"
Start-Process powershell -ArgumentList "-NoProfile","-File","C:\proga\claude-fleet\spike\m0\reap_watch.ps1" -WindowStyle Hidden
```
Continue with Tasks 4–6 while this runs.

- [ ] **Step 4: After the watch completes, read the log, append G5 verdict (pin + measured window / "no reap observed in 2 h"), commit**

```bash
git add spike/m0/reap_watch.ps1 spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G5 — pin scriptability + reap window"
```

---

### Task 8: G7 — heartbeat primitive inside a bg session

**Files:**
- Create: `spike/m0/proj/heartbeat-task.md`
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Produces: verdict G7 — whether a bg session can self-schedule turns; cost per beat if measurable via G3's source.

- [ ] **Step 1: Write `spike/m0/proj/heartbeat-task.md`**

```markdown
# Heartbeat probe
1. Append one line containing the current time to `beats.log` in this directory
   (use the Bash tool: `date >> beats.log`).
2. If you have ANY capability to schedule yourself to wake up again in ~2
   minutes (a ScheduleWakeup tool, a /loop skill, a self-reminder), invoke it
   now to repeat step 1. If you have no such capability, reply with exactly:
   NO-SCHEDULER and stop.
```

- [ ] **Step 2: Dispatch and observe for ~8 minutes**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-beat --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Read tool to read heartbeat-task.md in this directory and follow it."
```
Poll `beats.log` and the roster every 2 min. CONFIRMED = ≥3 beat lines with the session persisting between them (name the tool the session used — check events.jsonl PreToolUse records). REFUTED = single beat + `NO-SCHEDULER` (fallback per spec: event-driven supervisor, watchtower scoped out — HALT-grade for watchtower duties: flag for operator ratification).

- [ ] **Step 3: Stop `m0-beat`, append G7 verdict + cost-per-beat if G3's source exposes it, commit**

```bash
git add spike/m0/proj/heartbeat-task.md spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G7 — heartbeat primitive"
```

---

### Task 9: G10 — external stop and kill behavior

**Files:**
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Produces: verdict G10 — `claude stop` mid-turn semantics (Stop hook fired? roster state?) and daemon reaction to a raw process kill.

- [ ] **Step 1: `claude stop` on a RUNNING session**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-g10-stop --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Bash tool to run: sleep 120. Then reply DONE."
# wait ~15 s for the sleep to start, grab the id:
claude agents --json --all | py -3.13 -c "import json,sys; [print(s['id'], s.get('pid')) for s in json.load(sys.stdin) if s.get('name')=='m0-g10-stop']"
claude stop <id>
claude agents --json --all | py -3.13 -c "import json,sys; [print(json.dumps(s)) for s in json.load(sys.stdin) if s.get('name')=='m0-g10-stop']"
Get-Content C:\proga\claude-fleet\spike\m0\out\events.jsonl -Tail 3
```
Record: post-stop roster `state`; whether a `Stop` hook event fired (matters for the outcome discriminator — a stopped worker with no outcome record must land `dead-suspected`, not `completed`).

- [ ] **Step 2: Raw process kill (the thing fleet must never do — measure the blast radius anyway)**

```powershell
claude --bg -n m0-g10-kill --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Bash tool to run: sleep 120. Then reply DONE."
# grab pid as above, then:
taskkill /PID <pid> /F
claude agents --json --all | py -3.13 -c "import json,sys; [print(json.dumps(s)) for s in json.load(sys.stdin) if s.get('name')=='m0-g10-kill']"
```
Record: does the roster mark it failed/done, does the daemon respawn it (zombie hazard), does the roster corrupt.

- [ ] **Step 3: Append G10 verdict, commit**

```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G10 — stop and kill semantics"
```

---

### Task 10: G9 — daemon restart (DESTRUCTIVE — last, operator-gated)

**Files:**
- Modify: `spike/m0/VERDICTS.md`

**Interfaces:**
- Produces: verdict G9 — session/roster/pin fate across a daemon restart.

- [ ] **Step 1: Operator gate**

```powershell
claude agents --json | py -3.13 -c "import json,sys; [print(s.get('name'), s.get('kind'), s.get('status'), s.get('state')) for s in json.load(sys.stdin)]"
```
STOP: if ANY non-`m0-` session is live, ask the operator before proceeding. Killing the daemon touches every background session on the machine.

- [ ] **Step 2: Dispatch one live probe + locate daemon**

```powershell
Set-Location C:\proga\claude-fleet\spike\m0\proj
claude --bg -n m0-g9 --settings ..\worker-settings.json --permission-mode acceptEdits --model haiku "Use the Bash tool to run: sleep 300. Then reply DONE."
claude daemon --help          # probe for a native restart first
Get-Content ~/.claude/daemon.log -Tail 5 -ErrorAction SilentlyContinue   # research: daemon pid often logged
Get-Process | Where-Object { $_.ProcessName -match "claude|node" } | Select-Object Id, ProcessName, StartTime
```
Prefer a native `claude daemon stop/restart` if the probe reveals one; raw `Stop-Process` on the daemon pid only as last resort.

- [ ] **Step 3: Restart daemon, observe**

After the restart, run `claude agents --json --all` and record: did `m0-g9` survive (state?), did the roster reset to empty (the false-mass-dead scenario spec §5's epoch check guards), do pinned entries persist (`pins.json` is research-visible — note only).

- [ ] **Step 4: Append G9 verdict, stop all `m0-*` sessions, commit**

```bash
git add spike/m0/VERDICTS.md
git commit -m "spike(m0): verdict G9 — daemon restart behavior"
```

---

### Task 11: Contract doc — `docs/specs/native-substrate.md`

**Files:**
- Create: `docs/specs/native-substrate.md`
- Consumes: `spike/m0/VERDICTS.md` (all G sections present).

- [ ] **Step 1: Assemble the contract doc with this exact skeleton, filling every bracket from VERDICTS.md**

```markdown
# Native Substrate Contract (M-0 verdicts)
Date: [run date]. `claude --version`: [exact]. Windows 10 [build].
Spec of record: docs/superpowers/specs/2026-07-13-native-agents-pivot-design.md v2.2 §2.
This doc pins EVERY native-surface behavior fleet may depend on. Anything not
listed here is out of contract. Re-verify via the pin-test tier when
`claude --version` changes.

## G-table verdicts
| G | Verdict | Evidence (one line) | Consequence for design |
[10 rows from VERDICTS.md; HALT-grade REFUTED rows name the fallback and its ratification status]

## Dispatch contract
[exact `claude --bg` argv fleet uses, flag by flag, each marked CONFIRMED]

## Roster contract (`claude agents --json --all`)
[field-presence-per-state table from Task 6 Step 1]

## Result/cost contract
[G3's sanctioned source, exact field/key names, stability caveats]

## Steering contract
[G2's confirmed channel or ratified fallback]

## Known hazards
[reap window, daemon-restart roster behavior, stop-vs-outcome-record gap — from G5/G9/G10]
```

- [ ] **Step 2: Self-check — every spec §2 G-row has a verdict row; every HALT row is CONFIRMED or the spike already escalated. Commit**

```bash
git add docs/specs/native-substrate.md
git commit -m "spec: native-substrate contract — M-0 verdicts G1-G10"
```

---

### Task 12: Gate review (operator decision point)

**Files:**
- Modify: `docs/specs/native-substrate.md` (ratification lines)
- Modify: `knowledge/INDEX.md` + `knowledge/lessons.md` (M-0 lessons entry)

- [ ] **Step 1: Present to the operator:** the G-table verdict summary, every HALT-grade REFUTED row with its named fallback, and the recommendation (proceed to M-A plan / halt / amend spec §N).
- [ ] **Step 2: Record each operator ratification** as a line in native-substrate.md: `RATIFIED <date>: G<N> fallback — <one line>`.
- [ ] **Step 3: Append the M-0 lessons entry** to `knowledge/lessons.md` (what surprised, what refuted, cost of the spike) + one INDEX.md pointer line.
- [ ] **Step 4: Commit**

```bash
git add docs/specs/native-substrate.md knowledge/
git commit -m "spec: M-0 gate review — ratifications + lessons"
```

**After this task:** author the M-A plan (supervisor identity) against the ratified contract. M-A/M-B/M-C are separate plans by design — their content depends on these verdicts.
