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
