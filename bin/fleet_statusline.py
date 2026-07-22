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
  * never asserts liveness it did not probe for -- a stale bucket carries a
    greyed age suffix (D2);
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

PREFIX = "[fleet]"
STALE_AFTER_SECONDS = 300

# The rendered line is PURE ASCII by construction -- no glyphs, no box drawing.
# A Windows console defaults to cp1252 and cannot encode the block/geometric
# glyphs an earlier design used; print() then raised UnicodeEncodeError, the
# exit-0 guard swallowed it, and the operator got a permanently BLANK
# statusline with no way to tell why. A fallback renderer only papered over
# that: colour and word are already the whole signal, so the glyphs bought
# nothing but width and a failure mode. `test_the_rendered_line_is_pure_ascii`
# is the invariant.
_RESET = "\x1b[0m"
_BOLD = "\x1b[1m"
# Grey is RESERVED for `dead`. Nothing else on the line may use it: the moment a
# second field is grey, "greyed out" stops meaning "inert" and the operator has
# to read the words to find out what is going on.
_GREY = "\x1b[90m"
_NAME = "\x1b[1;94m"       # bold bright blue -- the fleet nameplate
_AGE = "\x1b[33m"          # yellow: a clock, distinct from every status hue
_COST = "\x1b[1;37m"       # bold white: money
# Distinct hue per status, bright variants so they separate on a dark terminal.
_STATUS_COLOR = {
    "working": "\x1b[92m",       # bright green  -- burning tokens
    "idle+mail": "\x1b[95m",     # bright magenta -- waiting on its mail
    "idle": "\x1b[96m",          # bright cyan   -- alive, unengaged
    "attached": "\x1b[35m",      # magenta       -- an operator holds it
    "limited": "\x1b[93m",       # bright yellow -- parked on a plan limit
    # Spend exhausted, not merely parked -- red, which `dead` gave up for grey.
    "over_budget": "\x1b[91m",   # bright red
    "over_ceiling": "\x1b[31m",  # red
    "dead": _GREY,               # inert: never competes with a live bucket
}
_LABEL = {
    "working": "work", "idle+mail": "mail", "idle": "idle",
    "attached": "att", "limited": "lim", "over_budget": "budget",
    "over_ceiling": "ceiling", "dead": "dead",
}
# Fixed reading order, loudest first. Deliberately NOT sorted by count: a
# count-sorted line reshuffles between refreshes, so the operator has to re-read
# it every time, and a pile of dead workers outranks the one that is working.
_ORDER = ["working", "idle+mail", "attached", "limited",
          "over_budget", "over_ceiling", "idle"]


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


def _bucket_order(buckets) -> list:
    """Fixed order for the buckets present, unknown statuses last, `dead` never
    among them -- it is collapsed into the tail counter by the caller."""
    known = [b for b in _ORDER if b in buckets]
    unknown = sorted(b for b in buckets if b not in _ORDER and b != "dead")
    return known + unknown


def render_statusline(snap: dict, color: bool = True,
                      stale_after: int = STALE_AFTER_SECONDS) -> str:
    def paint(text, code):
        return f"{code}{text}{_RESET}" if color and code else text

    # A bracketed, brightly-coloured nameplate -- the operator's eye lands on
    # the row's owner before reading a single word of it. Foreground only: a
    # reverse-video block reads as a hard UI chrome element next to Claude
    # Code's own rows, which are all plain bracketed labels.
    head = paint(PREFIX, _NAME)

    if not snap.get("ok"):
        if snap.get("reason") == "not_initialized":
            return f"{head}: not initialized"
        return f"{head}: registry unreadable"

    workers = snap["workers"]
    if not workers:
        return f"{head}: no workers"

    buckets: dict = {}
    for w in workers:
        buckets.setdefault(_bucket(w), []).append(w)

    parts = []
    for bucket in _bucket_order(buckets):
        group = buckets[bucket]
        label = _LABEL.get(bucket, bucket)
        count = f"{_BOLD}{len(group)}" if color else str(len(group))
        chunk = paint(f"{label} {count}", _STATUS_COLOR.get(bucket, ""))

        # D2: a bucket where every worker is stale carries the freshest age, so
        # the line never presents an unverified status as freshly observed. The
        # age gets its own hue -- dimming it (the old behaviour dimmed the whole
        # chunk) put grey-on-dark text on the operator's screen, and grey now
        # means dead.
        stalest = [w["stale_seconds"] for w in group if w["stale_seconds"] is not None]
        if stalest and min(stalest) > stale_after:
            chunk += paint(f" {_fmt_age(min(stalest))}", _AGE)

        if bucket == "limited":
            resets = {_reset_clock(w["limit_reset_at"]) for w in group}
            clock = f"resets {sorted(resets)[0]}" if all(resets) else "reset?"
            if any(w["resume_eligible"] for w in group):
                # invariant 1: a view flags resume-eligibility, it never launches.
                clock = "resume-eligible"
            chunk += paint(f" {clock}", _STATUS_COLOR["limited"])
        parts.append(chunk)

    # `dead` is inert -- it cannot be steered, only respawned or cleaned. It gets
    # a grey tail counter rather than a bucket of its own, so eleven dead workers
    # never outshout the one that is actually running.
    dead = len(buckets.get("dead", ()))
    if not parts:
        parts = [paint("no live workers", _STATUS_COLOR["dead"])]
    if dead:
        parts.append(paint(f"+{dead} dead", _STATUS_COLOR["dead"]))

    cost = snap["totals"].get("cost_usd", 0.0)
    parts.append(paint(f"${cost:.2f}", _COST))
    # Two spaces between fields: wide enough to group `label count age` as one
    # unit without a separator glyph, which would cost width and ASCII purity.
    return "  ".join([head] + parts)


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

        # Fleet's own row is pure ASCII, so no console encoding can reject it
        # and there is no fallback renderer to get wrong.
        print(render_statusline(fleet.status_snapshot(), color=_want_color()))
    except BaseException:  # noqa: BLE001 -- a statusline never surfaces a traceback
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
