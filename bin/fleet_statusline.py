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
        # it today; read and discard so the writer never blocks on a full pipe.
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass

        # Prefer real UTF-8 output; fall back to ASCII glyphs when the console
        # cannot carry them rather than dying silently.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
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
