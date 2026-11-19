"""Named roles for `fleet msg` (docs/specs/messaging.md §3, §8, §10; plan PR 8).

A named role (`ops`, `hub`, `reviewer`, ...) is an identity with its own
queue. Its record is `state/msg/ids/<name>.json`:
`{schema, name, role, binding, epoch, bound_at, bound_by}` plus `retired_at`
once retired. The binding is concrete: `lane:<worker>` (resolved through the
registry at each read, so it follows fork-steer and respawn with no rebind), or
for a body outside the registry `session:<sid>`, `codex-thread:<id>` or
`pi-job:<id>`. Every bind and retire increments `epoch` and appends one ledger
line. Nothing is deleted: a retired role keeps its file and its history, and a
later bind revives the name at a higher epoch.

Doctrine: stdlib only, Python 3.10. Imports `fleet_msg_core` only; fleet
helpers come in as callables. No `fleet.lock`, no registry write.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from typing import Callable

import fleet_msg_core as core

SCHEMA = 1
LANE_PREFIX = "lane:"
CONCRETE_KINDS = ("session", "codex-thread", "pi-job")
_CONCRETE_RE = re.compile(r"^(session|codex-thread|pi-job):[A-Za-z0-9._-]{1,128}$")
ROLE_MAX_BYTES = 4096
BOUND_BY = ("supervisor-nonce", "interface-registration")


class BindError(Exception):
    """A refusal printed as one line."""


def role_path(store: core.Store, name: str):
    return store.root / "ids" / f"{name}.json"


def read_role(store: core.Store, name: str) -> "dict | None":
    """The role record, or None when absent or not a valid record."""
    if not core.valid_name(name):
        return None
    try:
        raw = core._read_regular(role_path(store, name), ROLE_MAX_BYTES)
        data = json.loads(raw.decode("utf-8")) if raw else None
    except (OSError, UnicodeError, ValueError, core.StoreError):
        return None
    if not isinstance(data, dict) or data.get("name") != name:
        return None
    epoch = data.get("epoch")
    if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
        return None
    return data


def is_retired(role: dict) -> bool:
    return role.get("retired_at") is not None


def role_holder(role: dict, lane_holder: Callable[[str], "str | None"]) -> "str | None":
    """The body that holds the role now: a concrete binding verbatim, or the
    registry's current holder of the bound lane. None when retired, unbound or
    the lane is gone."""
    if is_retired(role):
        return None
    binding = role.get("binding")
    if not isinstance(binding, str):
        return None
    if binding.startswith(LANE_PREFIX):
        worker = binding[len(LANE_PREFIX):]
        return lane_holder(worker) if core.valid_name(worker) else None
    return binding if _CONCRETE_RE.fullmatch(binding) else None


def role_names(store: core.Store) -> list:
    try:
        return sorted(n[:-5] for n in os.listdir(store.root / "ids")
                      if n.endswith(".json") and core.valid_name(n[:-5]))
    except OSError:
        return []


def check_binding(binding: str, lane_ok: Callable[[str], bool]) -> str:
    """Validate a binding; returns it. `lane_ok(worker)` is true for a live
    (not archived, not supervisor-shaped) registry lane."""
    if binding.startswith(LANE_PREFIX):
        worker = binding[len(LANE_PREFIX):]
        if not core.valid_name(worker) or not lane_ok(worker):
            raise BindError(f"refused: {binding!r} is not a live lane in this home")
        return binding
    if not _CONCRETE_RE.fullmatch(binding):
        raise BindError("refused: a binding is lane:WORKER, session:ID, "
                        "codex-thread:ID or pi-job:ID")
    return binding


def _write_role(store: core.Store, name: str, record: dict) -> None:
    """Replace the role file atomically: tmp, fsync, rename, fsync dir."""
    path = role_path(store, name)
    store._ensure_dir(path.parent)
    store._require_regular_or_absent(path)
    data = core.canonical(record)
    tmp = path.parent / f".{name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY | core._NOFOLLOW, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        store.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))      # the role record only, never a message
    store.fsync_dir(path.parent)


def bind(store: core.Store, name: str, binding: str, bound_by: str, *,
         reserved: Callable[[str], bool],
         lane_ok: Callable[[str], bool]) -> dict:
    """Bind (or rebind, or revive) role `name`. Epoch +1, one `bound` ledger
    line. `reserved(name)` is true for supervisor, interface and every lane."""
    if not core.valid_name(name):
        raise BindError(f"bad name {name!r}: use {core.NAME_RE.pattern}")
    if bound_by not in BOUND_BY:
        raise BindError("refused: bind needs supervisor-nonce or interface-registration")
    if reserved(name):
        raise BindError(f"refused: {name!r} is a lane, supervisor or interface identity; "
                        "those follow the registry and are never bound")
    check_binding(binding, lane_ok)
    with store.locked("spool", name):
        previous = read_role(store, name)
        if previous is None and os.path.lexists(role_path(store, name)):
            raise BindError(f"refused: role record {role_path(store, name)} is unreadable "
                            "(oversized, not UTF-8 JSON or bad schema); repair or move it "
                            "so the epoch is not reset")
        epoch = (previous["epoch"] if previous else 0) + 1
        record = {"schema": SCHEMA, "name": name, "role": name, "binding": binding,
                  "epoch": epoch, "bound_at": core.iso_utc(store.clock()),
                  "bound_by": bound_by}
        _write_role(store, name, record)
        store.ledger("bound", name=name, binding=binding, epoch=epoch, bound_by=bound_by,
                     previous=previous.get("binding") if previous else None)
    return record


def retire(store: core.Store, name: str, bound_by: str) -> dict:
    """Retire role `name`: sends to it are `rejected: retired`. The record and
    its queue stay; a later bind revives it at a higher epoch."""
    if bound_by not in BOUND_BY:
        raise BindError("refused: retire needs supervisor-nonce or interface-registration")
    with store.locked("spool", name):
        previous = read_role(store, name)
        if previous is None:
            raise BindError(f"refused: {name!r} is not a named role")
        if is_retired(previous):
            return previous
        record = dict(previous, binding=None, epoch=previous["epoch"] + 1,
                      retired_at=core.iso_utc(store.clock()), bound_by=bound_by)
        _write_role(store, name, record)
        store.ledger("retired", name=name, epoch=record["epoch"], bound_by=bound_by,
                     previous=previous.get("binding"))
    return record
