#!/usr/bin/env python3
"""claude-fleet SessionStart hook (docs/specs/terminal-surface.md §4.6).

Injects the fleet briefing into a MANAGER session's context at startup --
the SPEC §10 startup ritual, automated.

Two guards, both load-bearing:
  * D5: suppressed when FLEET_WORKER is set. A globally-enabled fleet plugin
    fires this hook in every Claude Code session on the machine, workers
    included; without the guard, every worker turn burns tokens on a fleet
    briefing it must ignore.
  * invariant 2: exits 0 on every path, printing `{}` on any failure. It
    writes nothing at all -- not even state/hook-errors.log. This is a
    manager-side hook; its failures are invisible-by-design, and the
    operator's own `fleet doctor` is the alarm.

Unlike posttooluse_mailbox.py / stop_mailbox.py -- which run INSIDE worker
turns and therefore never import fleet.py -- this hook is manager-side and
imports it, degrading to `{}` if the import fails.
"""
import json
import os
import sys
from pathlib import Path

MAX_CONTEXT_CHARS = 10_000


def _resolve_fleet_home() -> Path:
    """$FLEET_HOME -> ~/.claude/fleet-home marker -> this script's repo root.

    The marker is load-bearing for a PLUGIN install: the plugin may be a
    marketplace cache copy of this repo, so `parent.parent.parent` points at
    the cache, not at the fleet the operator's CLI actually writes. `fleet
    init` stamps the marker with the real home."""
    env = os.environ.get("FLEET_HOME")
    if env:
        return Path(env)
    try:
        marker = Path.home() / ".claude" / "fleet-home"
        recorded = marker.read_text(encoding="utf-8").strip()
        if recorded and Path(recorded).is_dir():
            return Path(recorded)
    except (OSError, ValueError):
        pass
    return Path(__file__).resolve().parent.parent.parent


_FLEET_HOME = _resolve_fleet_home()
sys.path.insert(0, str(_FLEET_HOME / "bin"))

try:
    import fleet
except Exception:  # noqa: BLE001 -- degrade silently, never break a session start
    fleet = None


def _emit(context: str = "") -> int:
    if not context:
        print("{}")
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context[:MAX_CONTEXT_CHARS],
    }}))
    return 0


def _worker_line(w: dict) -> str:
    flags = []
    if w["status"] == "idle" and w["mail"]:
        flags.append("idle+mail")
    if w["resume_eligible"]:
        flags.append("resume-eligible")
    if w["status"] == "limited" and w["limit_reset_at"]:
        flags.append(f"resets {w['limit_reset_at']}")
    if w["stale_seconds"] is not None and w["stale_seconds"] > 300:
        flags.append(f"~{w['stale_seconds'] / 60:.0f}m since activity")
    suffix = f"  [{', '.join(flags)}]" if flags else ""
    return f"  {w['name']}: {w['status']}, {w['turns']} turns, ${w['cost_usd']:.2f}{suffix}"


def _index_lines(limit: int = 20) -> list:
    path = _fleet_home() / "knowledge" / "INDEX.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][:limit]


def _fleet_home() -> Path:
    """Re-read fleet's FLEET_HOME when available so tests that monkeypatch it
    (and an operator who moves the repo) stay consistent with the snapshot."""
    if fleet is not None:
        return Path(fleet.FLEET_HOME)
    return _FLEET_HOME


def _build_context() -> str:
    snap = fleet.status_snapshot()
    if not snap["ok"]:
        return ""

    out = []
    totals = snap["totals"]
    if totals["workers"]:
        out.append(f"FLEET: {totals['workers']} worker(s), ${totals['cost_usd']:.2f} lifetime spend.")
        # Budget: worker rows are truncated FIRST (spec §4.6), so a large
        # fleet never crowds out the knowledge index.
        rows = [_worker_line(w) for w in snap["workers"]]
        room = MAX_CONTEXT_CHARS - 1_500
        kept = []
        used = 0
        for row in rows:
            if used + len(row) + 1 > room:
                kept.append(f"  ... and {len(rows) - len(kept)} more (run `fleet status`)")
                break
            kept.append(row)
            used += len(row) + 1
        out.extend(kept)
    else:
        out.append("FLEET: no workers registered.")

    try:
        sup_line = fleet.supervisor_status_line()
    except Exception:  # noqa: BLE001 -- invariant 2: the briefing must never break
        sup_line = None
    if sup_line:
        out.append(sup_line)

    index = _index_lines()
    if index:
        out.append("")
        out.append("knowledge/INDEX.md:")
        out.extend(f"  {ln}" for ln in index)

    return "\n".join(out)


def main() -> int:
    try:
        try:
            sys.stdin.read()
        except (OSError, ValueError):
            pass
        # D5: never brief a worker about the fleet it belongs to.
        if os.environ.get("FLEET_WORKER"):
            return _emit()
        if fleet is None:
            return _emit()
        return _emit(_build_context())
    except BaseException:  # noqa: BLE001 -- invariant 2: exit 0, always
        try:
            print("{}")
        except BaseException:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
