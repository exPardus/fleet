#!/usr/bin/env python3
"""fleet keeper -- a page-only liveness timer for a headless fleet.

Runs from a systemd user timer every 15 minutes (`--once`). It OBSERVES
fleet state read-only and TYPES one-line pages into the dedicated tmux
interface window (`work:fleet`), whose Claude session relays them to
Telegram through the ccgram bridge. It never takes `fleet.lock`, never
writes fleet state, and never dispatches a session -- revival is a human
message from the phone (operator ruling 2026-09-08, spec
docs/superpowers/specs/2026-09-08-server-persistent-fleet-design.md).

stdlib only; floor is fleet.MIN_PYTHON_VERSION.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

_INSTALL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_INSTALL_ROOT / "bin"))

import fleet  # noqa: E402

Page = namedtuple("Page", "rule fingerprint text")

HEARTBEAT_STALE_SECONDS = 3600
UNPUSHED_PAGE_SECONDS = 6 * 3600
REPAGE_SECONDS = 6 * 3600
ANOMALOUS_STATUSES = ("dead-suspected", "limited")


# --------------------------------------------------------------------- rules

def _sup_alive(obs) -> bool:
    return any(str(n).startswith("sup|") for n in obs.get("sup_sessions", []))


def rule_registry_unreadable(obs, now):
    if obs.get("registry_ok", True):
        return None
    reason = obs.get("registry_reason") or "unknown"
    return Page("registry-unreadable", reason,
                f"KEEPER: registry unreadable ({reason}). Report it; do not repair.")


def rule_login_expired(obs, now):
    if obs.get("agents_ok", True):
        return None
    return Page("login-expired", "agents-failed",
                "KEEPER: claude login appears expired (`claude agents` failed). "
                "Operator must /login on the box.")


def rule_supervisor_dead(obs, now):
    if not obs.get("goals_active"):
        return None
    if not obs.get("agents_ok", True):
        return None  # cannot tell dead from unlisted; login rule covers it
    if _sup_alive(obs):
        return None
    state = obs.get("claim_state")
    beat = obs.get("heartbeat_age_seconds")
    if state in ("released", "none", "unknown"):
        reason = f"claim {state}"
    elif beat is not None and beat > HEARTBEAT_STALE_SECONDS:
        reason = f"heartbeat {int(beat // 60)} min stale, no sup session"
    else:
        return None
    return Page("supervisor-dead", f"{state}:{reason}",
                f"KEEPER: supervisor dead ({reason}). Report state; "
                "await operator before sup-spawn.")


def rule_supervisor_frozen(obs, now):
    q = obs.get("pending_decision")
    if not q:
        return None
    return Page("supervisor-frozen", str(q),
                f"KEEPER: supervisor parked on decision: {q} "
                "Carry it to the operator.")


def rule_worker_anomaly(obs, now):
    names = []
    for w in obs.get("workers", []):
        status = w.get("status")
        if status in ANOMALOUS_STATUSES:
            names.append(f"{w.get('name')}({status})")
        elif status == "idle" and (w.get("mail") or 0) > 0:
            names.append(f"{w.get('name')}(idle+mail)")
    if not names:
        return None
    joined = ", ".join(sorted(names))
    return Page("worker-anomaly", joined,
                f"KEEPER: {len(names)} worker anomalies: {joined}. "
                "Summarise for the operator.")


def rule_unpushed(obs, now):
    n = obs.get("unpushed") or 0
    oldest = obs.get("oldest_unpushed_ts")
    if n <= 0 or oldest is None:
        return None
    age = now - oldest
    if age < UNPUSHED_PAGE_SECONDS:
        return None
    hours = int(age // 3600)
    return Page("unpushed", f"{n}:{int(oldest)}",
                f"KEEPER: {n} commits unpushed for {hours}h. Push or explain.")


def rule_hook_errors(obs, now):
    cur = obs.get("hook_error_lines") or 0
    prev = obs.get("prev_hook_error_lines") or 0
    if cur <= prev:
        return None
    return Page("hook-errors", f"{prev}->{cur}",
                f"KEEPER: hook-errors.log grew by {cur - prev} lines. Read it.")


RULES = (
    rule_registry_unreadable,
    rule_login_expired,
    rule_supervisor_dead,
    rule_supervisor_frozen,
    rule_worker_anomaly,
    rule_unpushed,
    rule_hook_errors,
)


def evaluate(obs, now) -> list:
    pages = []
    for rule in RULES:
        page = rule(obs, now)
        if page is not None:
            pages.append(page)
    return pages


# --------------------------------------------------------------------- dedup

def dedup(pages, state, now):
    """Send a page when its rule is new, its fingerprint changed, or the
    re-page window elapsed. Rules that stopped firing drop out of state."""
    send = []
    new_state = {}
    for page in pages:
        prev = state.get(page.rule)
        if (prev is None or prev.get("fingerprint") != page.fingerprint
                or now - float(prev.get("at", 0)) > REPAGE_SECONDS):
            send.append(page)
            new_state[page.rule] = {"fingerprint": page.fingerprint, "at": now}
        else:
            new_state[page.rule] = prev
    return send, new_state


def load_state(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------- collect

SUBPROCESS_TIMEOUT = 30


def _run_text(run, argv, *, cwd=None, env=None):
    """(rc, stdout) with every failure class folded into rc != 0."""
    kwargs = {"capture_output": True, "text": True, "timeout": SUBPROCESS_TIMEOUT}
    if cwd is not None:
        kwargs["cwd"] = cwd
    if env is not None:
        kwargs["env"] = env
    try:
        cp = run(argv, **kwargs)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return cp.returncode, cp.stdout or ""


def _sup_status(home, run):
    argv = [sys.executable, str(Path(home) / "bin" / "fleet.py"),
            "sup-status", "--json"]
    rc, out = _run_text(run, argv, env={**os.environ, "FLEET_HOME": str(home)})
    if rc != 0:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _agents(run):
    rc, out = _run_text(run, ["claude", "agents", "--json"])
    if rc != 0:
        return False, []
    try:
        rows = json.loads(out)
    except ValueError:
        return False, []
    names = [str(r.get("name", "")) for r in rows if isinstance(r, dict)]
    return True, [n for n in names if n.startswith("sup|")]


def _git_unpushed(home, run):
    rc, out = _run_text(run, ["git", "rev-list", "--count", "origin/main..main"],
                        cwd=str(home))
    try:
        n = int(out.strip()) if rc == 0 else 0
    except ValueError:
        n = 0
    if n <= 0:
        return 0, None
    rc, out = _run_text(run, ["git", "log", "--format=%ct", "--reverse",
                              "origin/main..main"], cwd=str(home))
    first = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    try:
        return n, float(first)
    except ValueError:
        return n, None


def _count_lines(path):
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def collect(home, *, now, run=subprocess.run, snapshot_fn=fleet.status_snapshot,
            prev_state=None):
    home = Path(home)
    prev_state = prev_state or {}
    snap = snapshot_fn()
    sup = snap.get("supervisor") or {}
    status = _sup_status(home, run)
    if status is not None:
        claim_state = (status.get("incarnation") or {}).get("state") or (
            "none" if status.get("incarnation") is None else "unknown")
        goals_active = bool(status.get("goals_active"))
        beat = status.get("heartbeat_age_seconds")
        pending = status.get("pending_decision")
    else:
        claim_state = sup.get("state") or "unknown"
        goals_active = bool(sup.get("goals_active"))
        beat = sup.get("heartbeat_age_seconds")
        pending = None
    agents_ok, sup_sessions = _agents(run)
    unpushed, oldest = _git_unpushed(home, run)
    workers = [{"name": w.get("name"), "status": w.get("status"),
                "mail": w.get("mail") or 0, "limit_kind": w.get("limit_kind")}
               for w in (snap.get("workers") or [])]
    return {
        "goals_active": goals_active,
        "claim_state": claim_state,
        "heartbeat_age_seconds": beat,
        "pending_decision": pending,
        "sup_sessions": sup_sessions,
        "agents_ok": agents_ok,
        "registry_ok": bool(snap.get("ok", True)),
        "registry_reason": snap.get("reason"),
        "workers": workers,
        "unpushed": unpushed,
        "oldest_unpushed_ts": oldest,
        "hook_error_lines": _count_lines(home / "state" / "hook-errors.log"),
        "prev_hook_error_lines": int(prev_state.get("_hook_error_lines", 0) or 0),
    }


# ---------------------------------------------------------------------- tmux

def _tmux(run, out, *args):
    argv = ["tmux", *args]
    rc, _ = _run_text(run, argv)
    if rc != 0:
        print(f"keeper: tmux failed: {argv}", file=out)
    return rc == 0


def window_alive(run, target):
    rc, text = _run_text(run, ["tmux", "list-panes", "-t", target,
                               "-F", "#{pane_current_command}"])
    return rc == 0 and "claude" in text.split()


def _window_exists(run, target):
    rc, _ = _run_text(run, ["tmux", "list-panes", "-t", target])
    return rc == 0


def ensure_window(run, *, session, window, cwd, launch, out=sys.stdout):
    target = f"{session}:{window}"
    if window_alive(run, target):
        return False
    if _window_exists(run, target):
        _tmux(run, out, "kill-window", "-t", target)
    _tmux(run, out, "new-window", "-d", "-t", session, "-n", window,
          "-c", cwd, launch)
    return True


def page(run, target, text, out=sys.stdout):
    ok = _tmux(run, out, "send-keys", "-t", target, "-l", text)
    ok = _tmux(run, out, "send-keys", "-t", target, "Enter") and ok
    return ok


# ---------------------------------------------------------------------- main

def _parser():
    p = argparse.ArgumentParser(prog="fleet_keeper",
                                description="page-only liveness tick for a headless fleet")
    p.add_argument("--once", action="store_true", required=True,
                   help="run one tick and exit (the only mode; a timer supplies cadence)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be paged; touch neither tmux nor state")
    p.add_argument("--fleet-home", default=str(_INSTALL_ROOT))
    p.add_argument("--tmux-session", default="work")
    p.add_argument("--window", default="fleet")
    p.add_argument("--profile", default=None,
                   help="interface profile the window's claude is told to read")
    return p


def main(argv=None, *, run=subprocess.run, now_fn=time.time,
         snapshot_fn=fleet.status_snapshot, out=sys.stdout):
    args = _parser().parse_args(argv)
    home = Path(args.fleet_home).resolve()
    profile = Path(args.profile) if args.profile else (
        home / "docs" / "operator" / "server-interface-profile.md")
    launch = ('claude --permission-mode bypassPermissions '
              f'"Read {profile} and follow it exactly."')
    target = f"{args.tmux_session}:{args.window}"
    state_path = home / "state" / "keeper" / "last-page.json"
    now = float(now_fn())

    state = load_state(state_path)
    obs = collect(home, now=now, run=run, snapshot_fn=snapshot_fn, prev_state=state)
    pages = evaluate(obs, now)
    rule_state = {k_: v for k_, v in state.items() if not k_.startswith("_")}
    send, rule_state = dedup(pages, rule_state, now)

    if args.dry_run:
        for p in pages:
            print(f"[dry-run] {p.rule}: {p.text}", file=out)
        if not window_alive(run, target):
            print(f"[dry-run] would create {target}: {launch}", file=out)
        return 0

    created = ensure_window(run, session=args.tmux_session, window=args.window,
                            cwd=str(home), launch=launch, out=out)
    if created:
        print(f"keeper: created {target}", file=out)
    for p in send:
        page(run, target, p.text, out=out)
        print(f"keeper: paged {p.rule}", file=out)

    rule_state["_hook_error_lines"] = obs["hook_error_lines"]
    save_state(state_path, rule_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
