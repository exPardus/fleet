"""Anti-gridlock rules as pure functions (docs/specs/messaging.md §11).

Every function here takes its inputs, including the clock and the history of
earlier sends, as arguments and returns a verdict. Nothing reads or writes a
file, takes a lock or imports `fleet.py`; the caller supplies the history.

`make_rules()` builds the `rules(draft)` hook that `fleet_msg_core.enqueue()`
runs under the sender lock before any seq is allocated. `make_admit()` builds
the `admit(env)` hook that `fleet_msg_core.ingest()` runs for the §11 per-peer
ingest cap and retired lanes. A refusal is a string `"<code>: <message>"`;
`refusal_code()` returns the code, which is a §6 reject reason or one of
`CODES`.

Stdlib only, Python 3.10.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, NamedTuple

import fleet_msg_core as core

HOUR_S = 3600.0
# Refusal codes that are not §6 reject reasons (a send refusal is not a reject).
CODES = ("hop", "loop", "task-budget")
ESCALATE = "escalate to the supervisor or the Interface"

DEFAULT_MAX_HOP = 6
DEFAULT_TASK_BUDGET = 4        # tasks per hour per (from, to)
DEFAULT_RATE = 20              # messages per hour per (from, to)
DEFAULT_PEER_INGEST = 200      # ingested envelopes per hour per peer site
DEFAULT_LOOP_ALTERNATING = 4   # alternating tasks between one pair; the next is refused

# `config.json` keys. Size is not a setting (§11: no override); a limit may
# only be lowered, never raised past the envelope bound (§4): `max_hop` above
# `core.PATH_MAX - 1` raises RulesError.
SETTINGS = ("max_hop", "task_budget", "rate", "peer_ingest", "loop_alternating")


class RulesError(ValueError):
    """A config value is not a positive integer."""


class Sent(NamedTuple):
    """One earlier send, as the caller reads it from the ledger or outbox."""
    ts: float    # when it was sent, epoch seconds
    frm: str     # `name@site`
    to: str      # `name@site`
    kind: str    # note | task | receipt


@dataclass(frozen=True)
class Limits:
    """Every §11 bound. Defaults are the spec's."""
    max_hop: int = DEFAULT_MAX_HOP
    task_budget: int = DEFAULT_TASK_BUDGET
    rate: int = DEFAULT_RATE
    peer_ingest: int = DEFAULT_PEER_INGEST
    loop_alternating: int = DEFAULT_LOOP_ALTERNATING
    max_words: int = core.BODY_MAX_WORDS
    max_bytes: int = core.BODY_MAX_BYTES

    @classmethod
    def from_config(cls, config: dict | None) -> "Limits":
        """Read the §11 settings from a parsed `config.json`; unknown keys are
        ignored. A bad value raises RulesError, never silently resets."""
        config = config or {}
        values = {}
        for key in SETTINGS:
            if key in config:
                value = config[key]
                if type(value) is not int or value < 1:
                    raise RulesError(f"{key} must be an integer >= 1, got {value!r}")
                if key == "max_hop" and value > core.PATH_MAX - 1:
                    raise RulesError(f"max_hop must be <= {core.PATH_MAX - 1} (envelope path bound), got {value}")
                values[key] = value
        return cls(**values)


def refusal_code(reason: str) -> str:
    return reason.split(":", 1)[0]


# --- the rules: each returns a refusal reason or None ------------------------

def check_size(body: str, limits: Limits = Limits()) -> str | None:
    """≤120 words and ≤8 KiB; there is no override."""
    try:
        encoded = body.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        return "schema: body is not valid UTF-8 text"
    if len(encoded) > limits.max_bytes:
        return f"size: body over {limits.max_bytes} bytes; send a file or PR link"
    if len(body.split()) > limits.max_words:
        return f"size: body over {limits.max_words} words; send a file or PR link"
    return None


def check_hop(hop: int, re_id: str | None, limits: Limits = Limits()) -> str | None:
    """Refuse a reply (`--re`) past `max_hop`. A root (no `re`) is never refused."""
    if re_id is not None and hop > limits.max_hop:
        return f"hop: reply chain past max_hop {limits.max_hop}; {ESCALATE}"
    return None


def check_loop(frm: str, to: str, kind: str, path: list[str], history: Iterable[Sent],
               limits: Limits = Limits()) -> str | None:
    """A `task` cannot go to an identity already in its `path`, and
    `loop_alternating` alternating tasks between one pair refuse the next.

    `path` is the draft's chain, root first and ending at `frm`. `history` is
    the pair's earlier tasks in either direction; oldest-first order is taken
    from `ts`. The next task continues the alternation when its sender differs
    from the latest task's sender.
    """
    if kind != "task":
        return None
    if to in path:
        return f"loop: {to} is already in the task path; {ESCALATE}"
    tasks = sorted((s for s in history if s.kind == "task" and {s.frm, s.to} == {frm, to}),
                   key=lambda s: s.ts)
    recent = tasks[-limits.loop_alternating:]
    if (len(recent) == limits.loop_alternating
            and recent[-1].frm != frm
            and all(a.frm != b.frm for a, b in zip(recent, recent[1:]))):
        return (f"loop: {limits.loop_alternating} alternating tasks between {frm} "
                f"and {to}; {ESCALATE}")
    return None


def _within_hour(entries: Iterable[Sent], now: float) -> list[Sent]:
    return [s for s in entries if s.ts > now - HOUR_S]


def check_task_budget(frm: str, to: str, kind: str, history: Iterable[Sent], now: float,
                      limits: Limits = Limits()) -> str | None:
    """`task_budget` tasks per hour per (from, to), ignoring threads."""
    if kind != "task":
        return None
    used = sum(1 for s in _within_hour(history, now)
               if s.kind == "task" and s.frm == frm and s.to == to)
    if used >= limits.task_budget:
        return f"task-budget: {used} tasks to {to} in the last hour (limit {limits.task_budget})"
    return None


def check_rate(frm: str, to: str, history: Iterable[Sent], now: float,
               limits: Limits = Limits()) -> str | None:
    """`rate` messages per hour per (from, to). A receipt is not counted."""
    used = sum(1 for s in _within_hour(history, now)
               if s.kind != "receipt" and s.frm == frm and s.to == to)
    if used >= limits.rate:
        return f"rate: {used} messages to {to} in the last hour (limit {limits.rate})"
    return None


def check_peer_ingest(recent_ts: Iterable[float], now: float,
                      limits: Limits = Limits()) -> str | None:
    """At most `peer_ingest` envelopes per hour per peer site, however many
    names the peer hosts. `recent_ts` are the receive times for that peer;
    the caller leaves receipts out. A clock step back never shrinks the window."""
    used = sum(1 for ts in recent_ts if ts > now - HOUR_S)
    if used >= limits.peer_ingest:
        return f"rate: {used} envelopes from this peer in the last hour (limit {limits.peer_ingest})"
    return None


def notice_due(unread_from_sender: int) -> bool:
    """§9: one pending notice per (identity, sender). `unread_from_sender` is
    the identity's unread messages from that sender, the new one excluded."""
    return unread_from_sender == 0


# --- hooks for core.enqueue() and core.ingest() -------------------------------

def _is_receipt(draft: dict) -> bool:
    body = draft["body"]
    if draft["re"] is None:
        return False
    if body == "delivered":
        return True
    reason = body[len("rejected: "):]
    return body.startswith("rejected: ") and reason in core.REJECT_REASONS


def check_draft(draft: dict, history: Iterable[Sent], now: float,
                limits: Limits = Limits()) -> str | None:
    """Every sender-side rule over one draft, first refusal wins. A genuine
    receipt (`re` set, body `delivered` or `rejected: <reason>`) is system
    traffic: only size is checked, so receipts never gridlock. A draft that
    claims `kind: receipt` without that shape is refused as `schema`."""
    reason = check_size(draft["body"], limits)
    if reason:
        return reason
    if draft["kind"] == "receipt":
        return None if _is_receipt(draft) else "schema: not a receipt (needs re and a delivered/rejected body)"
    history = list(history)
    frm, to = draft["from"], draft["to"]
    return (check_hop(draft["hop"], draft["re"], limits)
            or check_loop(frm, to, draft["kind"], draft["path"], history, limits)
            or check_task_budget(frm, to, draft["kind"], history, now, limits)
            or check_rate(frm, to, history, now, limits))


def make_rules(limits: Limits, history: Callable[[dict], Iterable[Sent]],
               clock: Callable[[], float]) -> Callable[[dict], str | None]:
    """The `rules(draft)` hook for `core.enqueue()`. `history(draft)` returns
    the (from, to) pair's earlier sends in both directions; it runs under the
    sender lock, so it must not take one."""
    def rules(draft: dict) -> str | None:
        return check_draft(draft, history(draft), clock(), limits)
    return rules


def check_admit(env: dict, peer_site: str, recent_ts: Iterable[float], now: float,
                retired: Iterable[str] = (), limits: Limits = Limits()) -> str | None:
    """Receiver-side `admit` verdict: `retired` for a send to an archived
    lane (§3), `rate` past the per-peer ingest cap (§11)."""
    to_name, _site = core.split_qualified(env["to"])
    if to_name in set(retired):
        return "retired"
    if env["kind"] == "receipt":
        return None          # bounded by our own sends; never counted (§11.1)
    if check_peer_ingest(recent_ts, now, limits):
        return "rate"
    return None


def make_admit(limits: Limits, peer_site: str, recent_ts: Callable[[str], Iterable[float]],
               retired: Callable[[], Iterable[str]],
               clock: Callable[[], float]) -> Callable[[dict], str | None]:
    """The `admit(env)` hook for `core.ingest()`: returns a §6 reject reason
    (`retired`, `rate`) or None."""
    def admit(env: dict) -> str | None:
        return check_admit(env, peer_site, recent_ts(peer_site), clock(), retired(), limits)
    return admit
