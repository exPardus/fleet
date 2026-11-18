"""Messaging wake: the notice line and the `## MESSAGES` drain block
(docs/specs/messaging.md §9, plan PR 5).

Both are functions over an injected `WakePrims`. This module never imports
`fleet.py`, takes no `fleet.lock`, writes no registry and steers nobody: the
only side effect is `prims.append_mailbox(sid, notice)` for a Claude holder.
Neither output carries a body. Stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import fleet_msg_core as core

CLAUDE, CODEX, PI = "claude", "codex", "pi"
INTERFACE, UNBOUND = "interface", "unbound"
ADAPTERS = (CLAUDE, CODEX, PI, INTERFACE, UNBOUND)
# Only these adapters get a mid-turn notice. Codex, pi, the Interface and an
# unbound role are reached by the drain block or by `fleet msg inbox`.
NOTICE_ADAPTERS = (CLAUDE,)
DRAIN_HEADING = "## MESSAGES"
DRAIN_MAX_LINES = 20


@dataclass
class WakePrims:
    """Fleet helpers, injected so this module never imports `fleet.py`."""
    fleet_home: str
    adapter_of: Callable[[str], str]
    """identity name -> one of ADAPTERS."""
    holder_sid: Callable[[str], "str | None"]
    """identity name -> the Claude session id that holds it, or None."""
    append_mailbox: Callable[[str, str], None]
    """Fleet's `append_mailbox(sid, message)`."""


def notice_line(env: dict, fleet_home: str) -> str:
    """The one wake line. Id, sender and method only; never the body."""
    return (f"FLEET MSG {env['id']} from {env['from']} "
            f"({env['from_auth']['method']}). "
            f"Run fleet --fleet-home {fleet_home} msg inbox.")


def unread(store: core.Store, name: str) -> list[dict]:
    """Envelopes in `new/` for `name`, oldest first. Listing and reads only:
    no lock, nothing moves. An entry that vanished or fails to parse is skipped."""
    out = []
    for msg_id in core.list_spool(store, name, "new"):
        try:
            raw = core._read_regular(store.spool(name, "new") / f"{msg_id}.json",
                                     core.ENVELOPE_MAX_BYTES)
            if raw is None:
                continue
            out.append(core.parse(raw))
        except (core.EnvelopeError, core.StoreError):
            continue
    out.sort(key=lambda e: (e["sent_at"], e["id"]))
    return out


def notice_due(env: dict, unread_envs: list[dict]) -> bool:
    """§9 coalescing: one pending notice per (identity, sender). No notice
    while another unread message from the same sender is waiting."""
    return not any(u["from"] == env["from"] and u["id"] != env["id"]
                   for u in unread_envs)


def wake(store: core.Store, prims: WakePrims, name: str, env: dict) -> str:
    """Notice for `env`, delivered to spool `name`. Returns what happened:
    `noticed`, `coalesced`, or `drain-only`. A failure raises, and
    `publish()` logs it as `notice-failed`."""
    adapter = prims.adapter_of(name)
    if adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter {adapter!r}")
    if adapter not in NOTICE_ADAPTERS:
        return "drain-only"
    if not notice_due(env, unread(store, name)):
        return "coalesced"
    sid = prims.holder_sid(name)
    if not sid:
        return "drain-only"
    prims.append_mailbox(sid, notice_line(env, prims.fleet_home))
    return "noticed"


def make_notify(store: core.Store, prims: WakePrims) -> Callable[[str, dict], None]:
    """The `notify(name, env)` hook for `core.publish()`."""
    def notify(name: str, env: dict) -> None:
        wake(store, prims, name, env)
    return notify


def drain_block(store: core.Store, prims: WakePrims, name: str) -> str:
    """The `## MESSAGES` block for `compose_prompt`: id, sender, method per
    unread message, then the inbox command. Empty string when nothing is
    unread. Never marks anything read and never prints a body."""
    envs = unread(store, name)
    if not envs:
        return ""
    lines = [DRAIN_HEADING, ""]
    for env in envs[:DRAIN_MAX_LINES]:
        lines.append(f"- {env['id']} from {env['from']} ({env['from_auth']['method']})")
    if len(envs) > DRAIN_MAX_LINES:
        lines.append(f"- ... {len(envs) - DRAIN_MAX_LINES} more")
    lines += ["", f"Run fleet --fleet-home {prims.fleet_home} msg inbox."]
    return "\n".join(lines) + "\n"
