"""fs transport: homes on one machine (docs/specs/messaging.md §7.1).

Pull-only, so no cross-home write: every method reads the peer's `state/msg/`
and writes only the local one. The five `Transport` methods map as:

- `hello` reads the peer's `site.json` (`{"site": LABEL}`) and asks the
  injected prims which identities the peer hosts.
- `push` is a no-op: envelopes stay in the local `outbox/<peer>/q/` and the
  peer pulls them.
- `pull` lists the peer's `outbox/<local>/q/`. A file failing JSON or
  `body_sha256` is withheld for two passes, then returned so the receiver's
  `ingest()` rejects it `corrupt` (the strike count is a local counter file).
- `commit(ids)` writes one `kind: receipt` envelope per id into the local
  outbox (`delivered`, or `rejected: <why>` from the local reject record)
  through `core.enqueue()`. Committing a receipt moves the envelope it
  answers from the local `q/` to `sent/`. A receipt is never receipted.
- A receipt entry moves to `sent/` on a later `pull`, once its source
  envelope is no longer in the peer's `q/`.

Receipt ids are derived from the id they answer, so re-emitting `delivered`
for a duplicate finds the stored receipt (`enqueue` retry dedup) and never
makes a second one. This module publishes nothing itself: the sync driver
calls `fleet_msg_core.ingest()` on each pulled envelope, then `commit()`.

Doctrine: stdlib only, Python 3.10. No `fleet.py` or `fleet_lock` import, no
`fleet.lock`, no registry write, no unlink or overwrite of a message, marker or
ledger line; fleet helpers arrive as an injected prims object.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Iterable, Protocol

import fleet_msg_core as core
import fleet_msg_transport as transport

STRIKE_PASSES = 3                      # corrupt file: withheld twice, rejected on the third pass
SITE_JSON_MAX = 4096
REJECT_RECORD_MAX = 256 * 1024
RECEIPT_AUTH = {"method": "unverified", "detail": "receipt"}


class FsPrims(Protocol):
    """Fleet helpers the fs transport never imports from `fleet.py`."""

    def hosted(self, home: Path) -> Iterable[str]:
        """Identity names the home at `home` hosts (lanes, supervisor, interface, roles)."""
        ...


def receipt_id(msg_id: str) -> str:
    """The id of the receipt answering `msg_id`: derived, so a re-emit dedups."""
    return hashlib.sha256(b"fleet-msg-receipt\0" + msg_id.encode("ascii")).hexdigest()[:32]


def read_site_label(home: Path) -> str:
    """The site label in `home`'s `state/msg/site.json`, read-only."""
    path = Path(home) / "state" / "msg" / "site.json"
    _require_plain_chain(Path(home), path.parent)
    try:
        raw = core._read_regular(path, SITE_JSON_MAX)
    except core.StoreError as exc:
        raise transport.TransportError(f"peer site.json: {exc}") from None
    if raw is None or len(raw) > SITE_JSON_MAX:
        raise transport.TransportError("peer has no readable site.json")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise transport.TransportError("peer site.json is not JSON") from None
    site = data.get("site") if isinstance(data, dict) else None
    if not core.valid_name(site):
        raise transport.TransportError("peer site.json has no valid site label")
    return site


def _require_plain_chain(home: Path, target: Path) -> None:
    """Refuse a symlinked or non-directory component between `home/state` and
    `target`. A missing component ends the check (nothing to read)."""
    relative = target.relative_to(home)
    current = home
    for part in relative.parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise transport.TransportError(f"peer path {part!r} is not a plain directory")


class FsTransport:
    """A `Transport` to the home at `peer_home`, labelled `peer_site`."""

    def __init__(self, store: core.Store, peer_home: Path, peer_site: str,
                 prims: FsPrims, *, strike_passes: int = STRIKE_PASSES):
        if not core.valid_name(peer_site):
            raise transport.TransportError(f"bad peer site label {peer_site!r}")
        if peer_site == store.site:
            raise transport.TransportError("peer uses the local site label")
        self.store = store
        self.peer_home = Path(peer_home)
        self.peer_site = peer_site
        self.prims = prims
        self.strike_passes = strike_passes
        self.warnings: list[str] = []
        self._ids: dict[int, str] = {}
        # A read-only view: this module only reads from it.
        self._peer = core.Store(self.peer_home, peer_site, clock=store.clock)

    # --- Transport -----------------------------------------------------------

    def hello(self, local: transport.SiteInfo) -> transport.SiteInfo:
        label = read_site_label(self.peer_home)
        if label != self.peer_site:
            raise transport.TransportError(
                f"peer home labels itself {label!r}, expected {self.peer_site!r}")
        hosted = sorted({n for n in self.prims.hosted(self.peer_home) if core.valid_name(n)})
        info = transport.SiteInfo(site=label, schemas=(core.SCHEMA,),
                                  clock=core.iso_utc(self.store.clock()), hosted=tuple(hosted))
        self.warnings = transport.check_hello(local, info, self.store.clock())
        return info

    def push(self, envelopes: list[bytes]) -> dict[str, str]:
        """No-op: the envelopes already wait in the local `outbox/<peer>/q/`
        and the peer pulls them. No id is answered, so every id stays queued
        until its receipt arrives."""
        return {}

    def pull(self, hint_qseq: int) -> list[tuple[int, bytes]]:
        try:
            self._settle_receipts()
            names = self._peer_names() or {}
            entries = core.outbox_entries(self._peer, self.store.site, hint_qseq)
        except core.StoreError as exc:
            raise transport.TransportError(str(exc)) from None
        out = []
        self._ids = {}
        for qseq, raw in entries:
            msg_id = names.get(qseq)
            if msg_id is not None:
                self._ids[qseq] = msg_id
            if msg_id is not None and self._is_corrupt(raw) and self._strike(msg_id) < self.strike_passes:
                continue
            out.append((qseq, raw))
        return out

    def commit(self, ids: list[str]) -> None:
        for msg_id in ids:
            if not (isinstance(msg_id, str) and core.ID_RE.fullmatch(msg_id)):
                raise transport.TransportError(f"bad message id {msg_id!r}")
        wanted = set(ids)
        answered = []
        try:
            for msg_id, env in self._peer_envelopes(wanted):
                if env["kind"] == "receipt":
                    answered.append(env["re"])      # the peer's receipt: its source is ours
                else:
                    self._emit_receipt(env)
            if answered:
                core.outbox_commit(self.store, self.peer_site, answered)
        except core.StoreError as exc:
            raise transport.TransportError(str(exc)) from None

    def close(self) -> None:
        return None

    def entry_id(self, qseq: int) -> str | None:
        """The id in the file name of an entry the last `pull` returned. A
        corrupt entry has no parseable id, so the driver commits by this."""
        return self._ids.get(qseq)

    # --- the peer's q/ (read only) -------------------------------------------

    def _peer_q(self) -> Path:
        path = self._peer.outbox(self.store.site, "q")
        _require_plain_chain(self.peer_home, path)
        return path

    def _peer_names(self) -> "dict[int, str] | None":
        """qseq -> id from the file names in the peer's `q/`, or None when the
        directory is absent (moved home, wrong path, mount not ready): then
        nothing is known about the peer's queue."""
        try:
            listing = os.listdir(self._peer_q())
        except FileNotFoundError:
            return None
        names = {}
        for entry in listing:
            match = core._QFILE_RE.fullmatch(entry)
            if match:
                names[int(match.group(1))] = match.group(2)
        return names

    def _peer_envelopes(self, wanted: set[str]) -> list[tuple[str, dict]]:
        """Parsed envelopes of the peer's `q/` entries whose id is in `wanted`.
        An id the peer no longer holds, or whose file is corrupt, is skipped."""
        self._peer_q()                  # same plain-chain check as `pull`
        found = []
        for _qseq, raw in core.outbox_entries(self._peer, self.store.site):
            try:
                env = core.parse(raw)
            except core.EnvelopeError:
                continue
            if env["id"] in wanted:
                found.append((env["id"], env))
        return found

    # --- corrupt-file strikes --------------------------------------------------

    @staticmethod
    def _is_corrupt(raw: bytes) -> bool:
        try:
            core.parse(raw)
        except core.EnvelopeError as exc:
            return exc.reason == "corrupt"
        return False

    def _strike(self, msg_id: str) -> int:
        """Count one more failed pass for `msg_id`, in a local counter file.
        The unit is one `pull` call, not one sync pass."""
        path = self.store.root / "fs-strikes" / self.peer_site / msg_id
        with self.store.locked("outbox", self.peer_site):
            return self.store._counter_next(path)

    # --- receipts --------------------------------------------------------------

    def _emit_receipt(self, env: dict) -> None:
        """Write the `delivered` or `rejected` receipt for a handled envelope
        into the local outbox, once. An envelope this home neither published
        nor rejected gets none."""
        to_name, to_site = core.split_qualified(env["to"])
        _from_name, from_site = core.split_qualified(env["from"])
        if to_site != self.store.site or from_site != self.peer_site:
            return                                   # not addressed through this transport
        held = self.store._held(to_name, env["id"])
        if held is not None and self._held_from(held) != env["from"]:
            # Another sender's envelope took this id (ids are global, §5): not
            # ours to confirm. No receipt; the entry stays queued, visibly.
            self.store.ledger("receipt-withheld", id=env["id"], reason="id-owner")
            return
        if self.store._marked(env["id"]) or held is not None:
            body = "delivered"
        else:
            reason = self._reject_reason(env["id"])
            if reason is None:
                return
            body = f"rejected: {reason}"
        try:
            draft = core.make_draft(
                f"{to_name}@{self.store.site}", env["from"], body, from_auth=RECEIPT_AUTH,
                sent_at=core.iso_utc(self.store.clock()), kind="receipt", parent=env,
                msg_id=receipt_id(env["id"]))
        except core.EnvelopeError as exc:
            self.store.ledger("receipt-failed", id=env["id"], reason=exc.reason)
            return
        core.enqueue(self.store, draft)

    @staticmethod
    def _held_from(path: Path) -> "str | None":
        try:
            raw = core._read_regular(path, core.ENVELOPE_MAX_BYTES)
            return core.parse(raw)["from"] if raw is not None else None
        except (core.EnvelopeError, core.StoreError):
            return None

    def _reject_reason(self, msg_id: str) -> str | None:
        try:
            listing = sorted(os.listdir(self.store.rejected_dir))
        except FileNotFoundError:
            return None
        for entry in listing:
            if entry.startswith(f"{msg_id}-") and entry.endswith(".json"):
                raw = core._read_regular(self.store.rejected_dir / entry, REJECT_RECORD_MAX)
                try:
                    reason = json.loads(raw.decode("utf-8")).get("reason") if raw else None
                except (ValueError, AttributeError):
                    continue
                if reason in core.REJECT_REASONS:
                    return reason
        return None

    def _settle_receipts(self) -> None:
        """Move a local receipt entry to `sent/` once the envelope it answers
        is no longer in the peer's `q/`. An absent peer `q/` settles nothing."""
        names = self._peer_names()
        if names is None:
            return                      # peer q/ not listed: settle nothing
        held = set(names.values())
        settled = []
        for _qseq, raw in core.outbox_entries(self.store, self.peer_site):
            try:
                env = core.parse(raw)
            except core.EnvelopeError:
                continue
            if env["kind"] == "receipt" and env["re"] not in held:
                settled.append(env["id"])
        if settled:
            core.outbox_commit(self.store, self.peer_site, settled)
