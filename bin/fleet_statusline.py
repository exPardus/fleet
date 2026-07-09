#!/usr/bin/env python3
"""claude-fleet statusline (docs/specs/terminal-surface.md §4.3).

Renders one line under the operator's input box in Claude Code. Installed
into ~/.claude/settings.json by `fleet init --statusline` -- a plugin cannot
ship a statusLine (plugin settings.json accepts only `agent` and
`subagentStatusLine`).

Contract, all four points load-bearing:
  * imports fleet.status_snapshot() rather than shelling out, so registry
    schema knowledge lives in exactly one module (invariant 9);
  * no lock, no PID probe, no subprocess, no write (D1);
  * never asserts liveness it did not probe for -- stale rows carry an age
    suffix and are dimmed (D2);
  * exits 0 on every path, printing nothing on error. This is the statusline
    analogue of invariant 2 (exit-0 hooks): a traceback here would render
    under the input box on every refresh.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

_FLEET_HOME = (
    Path(os.environ["FLEET_HOME"]) if os.environ.get("FLEET_HOME")
    else Path(__file__).resolve().parent.parent
)
sys.path.insert(0, str(_FLEET_HOME / "bin"))

import fleet  # noqa: E402

FLAG = "⚑"
ASCII_FLAG = "#"
STALE_AFTER_SECONDS = 300

_DIM = "\x1b[2m"
_RESET = "\x1b[0m"
_STATUS_COLOR = {
    "working": "\x1b[32m",      # green
    "idle": "\x1b[36m",         # cyan
    "attached": "\x1b[35m",     # magenta
    "limited": "\x1b[33m",      # yellow
    "over_budget": "\x1b[33m",
    "over_ceiling": "\x1b[33m",
    "dead": "\x1b[31m",         # red
}
_STATUS_GLYPH = {
    "working": "●", "idle": "○", "idle+mail": "◐",
    "attached": "◆", "limited": "⏸", "dead": "✗",
}
# A Windows console defaults to cp1252, which cannot encode any glyph above.
# print() then raises UnicodeEncodeError, the exit-0 guard swallows it, and the
# operator gets a permanently BLANK statusline with no way to tell why. Render
# ASCII whenever stdout cannot carry the real glyphs.
_ASCII_GLYPH = {
    "working": "*", "idle": "o", "idle+mail": "@",
    "attached": "+", "limited": "=", "dead": "x",
}


def _fmt_age(seconds) -> str:
    if seconds is None:
        return "?"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.0f}h"


def _reset_clock(iso) -> str:
    """'2026-07-09T14:20:00Z' -> '14:20'. Any other shape -> the raw value."""
    if not iso:
        return ""
    try:
        return fleet._parse_iso(iso).strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        return str(iso)


def _bucket(worker: dict) -> str:
    if worker["status"] == "idle" and worker["mail"]:
        return "idle+mail"
    return worker["status"]


def render_statusline(snap: dict, color: bool = True, stale_after: int = STALE_AFTER_SECONDS,
                      ascii_only: bool = False) -> str:
    flag = ASCII_FLAG if ascii_only else FLAG
    glyphs = _ASCII_GLYPH if ascii_only else _STATUS_GLYPH

    if not snap.get("ok"):
        if snap.get("reason") == "not_initialized":
            return f"{flag} fleet: not initialized"
        return f"{flag} fleet: registry unreadable"

    workers = snap["workers"]
    if not workers:
        return f"{flag} fleet: no workers"

    def paint(text, code):
        return f"{code}{text}{_RESET}" if color and code else text

    buckets: dict = {}
    for w in workers:
        buckets.setdefault(_bucket(w), []).append(w)

    parts = []
    for bucket in sorted(buckets, key=lambda b: (-len(buckets[b]), b)):
        group = buckets[bucket]
        glyph = glyphs.get(bucket, "o" if ascii_only else "○")
        chunk = f"{len(group)}{glyph}{bucket}"

        # D2: a bucket where every worker is stale is rendered dimmed with the
        # freshest age, never silently presented as live.
        stalest = [w["stale_seconds"] for w in group if w["stale_seconds"] is not None]
        if stalest and min(stalest) > stale_after:
            chunk = paint(f"{chunk}~{_fmt_age(min(stalest))}", _DIM)
        else:
            chunk = paint(chunk, _STATUS_COLOR.get(bucket.split("+")[0], ""))

        if bucket == "limited":
            resets = {_reset_clock(w["limit_reset_at"]) for w in group}
            chunk += f" resets {sorted(resets)[0]}" if all(resets) else " reset?"
            if any(w["resume_eligible"] for w in group):
                # invariant 1: a view flags resume-eligibility, it never launches.
                chunk += " resume-eligible"
        parts.append(chunk)

    cost = snap["totals"].get("cost_usd", 0.0)
    return f"{flag} " + " ".join(parts) + f"  ${cost:.2f}"


def _want_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return True


# --- statusline chaining ---------------------------------------------------
#
# Claude Code allows exactly ONE `statusLine` command. An operator who already
# runs another statusline (ccusage, caveman, ...) would otherwise have to
# choose. `fleet init --statusline --chain` captures the incumbent command
# into state/statusline-chain.json; this script runs it, prints its rows, then
# prints fleet's row beneath.
#
# This is the ONE place fleet's statusline spawns a subprocess, and it is a
# deliberate, opt-in exception to the D1 no-subprocess-on-the-hot-path rule:
# the delegate is a command the operator was already paying for on every
# refresh. Fleet's own row still costs zero subprocesses. A delegate that
# fails, hangs, or writes garbage is DROPPED -- fleet's row always prints.

DELEGATE_TIMEOUT_SECONDS = 4


def _chain_path() -> Path:
    return Path(fleet.state_dir()) / "statusline-chain.json"


def _load_delegates() -> list:
    try:
        data = json.loads(_chain_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    delegates = data.get("delegates") if isinstance(data, dict) else None
    if not isinstance(delegates, list):
        return []
    return [d["command"] for d in delegates
            if isinstance(d, dict) and isinstance(d.get("command"), str) and d["command"].strip()]


def _run_delegate(command: str, payload: str) -> list:
    """Run one delegate statusline, return its output rows. Never raises."""
    try:
        proc = subprocess.run(
            command,
            shell=True,  # the command is a shell string straight out of settings.json
            input=payload,
            capture_output=True,
            text=True,
            timeout=DELEGATE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def _delegate_rows(payload: str) -> list:
    rows = []
    for command in _load_delegates():
        rows.extend(_run_delegate(command, payload))
    return rows


def _stdout_can_encode(text: str) -> bool:
    """Whether sys.stdout's encoding can carry `text`. A cp1252 console cannot
    encode the fleet glyphs; printing them there raises UnicodeEncodeError,
    which the exit-0 guard would swallow into a permanently blank statusline."""
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def main() -> int:
    try:
        # Claude Code passes a session JSON blob on stdin. Fleet needs none of
        # it, but a chained delegate might, so it is captured and forwarded
        # verbatim. Read it in full so the writer never blocks on a full pipe.
        try:
            payload = sys.stdin.read()
        except (OSError, ValueError):
            payload = ""

        # Prefer real UTF-8 output; fall back to ASCII glyphs when the console
        # cannot carry them rather than dying silently.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass

        # Delegates print above fleet's row. A delegate that fails, hangs, or
        # emits unprintable bytes is dropped -- it must never cost fleet's row.
        try:
            for row in _delegate_rows(payload):
                if _stdout_can_encode(row):
                    print(row)
        except BaseException:  # noqa: BLE001
            pass

        snap = fleet.status_snapshot()
        color = _want_color()
        line = render_statusline(snap, color=color)
        if not _stdout_can_encode(line):
            line = render_statusline(snap, color=color, ascii_only=True)
        print(line)
    except BaseException:  # noqa: BLE001 -- a statusline never surfaces a traceback
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
