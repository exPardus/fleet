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
