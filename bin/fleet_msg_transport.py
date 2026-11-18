"""The messaging Transport contract (docs/specs/messaging.md §7).

A transport moves canonical envelope bytes between two sites. It never
publishes: the receiving side calls `fleet_msg_core.publish()`. Same-home
delivery does not use a transport. Stdlib only; never imports `fleet.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import fleet_msg_core as core

ACCEPTED = "accepted"
DUPLICATE = "duplicate"
REJECTED_PREFIX = "rejected:"
HELLO_SKEW_WARN_S = core.MAX_SKEW_S


class TransportError(Exception):
    """The session cannot continue; nothing in flight is committed."""


@dataclass(frozen=True)
class SiteInfo:
    """What `hello` exchanges: label, envelope schemas, clock, hosted names."""
    site: str
    schemas: tuple[int, ...]
    clock: str
    hosted: tuple[str, ...]

    def to_json(self) -> dict:
        return {"site": self.site, "schemas": list(self.schemas),
                "clock": self.clock, "hosted": list(self.hosted)}

    @classmethod
    def from_json(cls, data) -> "SiteInfo":
        try:
            info = cls(site=data["site"], schemas=tuple(data["schemas"]),
                       clock=data["clock"], hosted=tuple(data["hosted"]))
        except (TypeError, KeyError) as exc:
            raise TransportError(f"bad hello: {exc}") from None
        if not core.valid_name(info.site):
            raise TransportError("bad hello: site label")
        if not all(type(s) is int for s in info.schemas):
            raise TransportError("bad hello: schemas")
        if not all(core.valid_name(n) for n in info.hosted):
            raise TransportError("bad hello: hosted names")
        try:
            core.parse_iso_utc(info.clock)
        except core.EnvelopeError:
            raise TransportError("bad hello: clock") from None
        return info


@runtime_checkable
class Transport(Protocol):
    def hello(self, local: SiteInfo) -> SiteInfo:
        """Exchange versions, clock and hosted identities."""
        ...

    def push(self, envelopes: list[bytes]) -> dict[str, str]:
        """id -> `accepted` | `duplicate` | `rejected:<why>`. A missing id stays queued."""
        ...

    def pull(self, hint_qseq: int) -> list[tuple[int, bytes]]:
        """Every entry still in the peer's q/ for us, ascending. The hint never filters."""
        ...

    def commit(self, ids: list[str]) -> None:
        """Exactly these ids were published; the peer moves only them to sent/."""
        ...

    def close(self) -> None:
        ...


def rejected(reason: str) -> str:
    if reason not in core.REJECT_REASONS:
        raise ValueError(f"bad reject reason {reason!r}")
    return REJECTED_PREFIX + reason


def parse_push_result(value) -> tuple[str, str | None]:
    """`accepted` | `duplicate` | `rejected:<why>` -> (status, reason)."""
    if value in (ACCEPTED, DUPLICATE):
        return value, None
    if isinstance(value, str) and value.startswith(REJECTED_PREFIX):
        reason = value[len(REJECTED_PREFIX):]
        if reason in core.REJECT_REASONS:
            return "rejected", reason
    raise TransportError(f"bad push result {value!r}")


def check_hello(local: SiteInfo, remote: SiteInfo, now: float) -> list[str]:
    """Refuse a peer with the local label or no common schema; return warnings."""
    if remote.site == local.site:
        raise TransportError(f"peer uses the local site label {local.site!r}")
    if core.SCHEMA not in remote.schemas:
        raise TransportError(f"peer lacks envelope schema {core.SCHEMA}")
    warnings = []
    skew = core.parse_iso_utc(remote.clock) - now
    if abs(skew) > HELLO_SKEW_WARN_S:
        warnings.append(f"clock skew {int(skew)} s with site {remote.site}")
    return warnings
