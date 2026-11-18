"""Messaging contracts and store primitives (docs/specs/messaging.md §4, §5).

This module freezes the envelope, the store layout, the two write
primitives `publish()` and `enqueue()`, and `ingest()`, the one receiver path
every transport calls. Every messaging path goes through them.

Doctrine: stdlib only, Python 3.10. No `fleet.py` or `fleet_lock` import, no
`fleet.lock`, no registry write. Locks are OS-released (mailman's lock
backend) and lock files are never unlinked. No function here deletes a
message, marker or ledger line; the only unlink removes the private tmp name
of a file that is already hard-linked into place, and every rename checks
its target is absent under the owning lock.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import fleet_mailman
from fleet_platform import PLATFORM

SCHEMA = 1
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
ID_RE = re.compile(r"^[0-9a-f]{32}$")
KINDS = ("note", "task", "receipt")
NEEDS_ANSWER_DEFAULT = False    # no reply required; adapters never auto-reply
METHODS = ("lane-registry", "supervisor-nonce", "supervisor-sid",
           "interface-registration", "bound-holder", "unverified",
           "legacy-unverified")
REJECT_REASONS = ("size", "rate", "auth", "stale", "future", "schema",
                  "corrupt", "retired")
BODY_MAX_WORDS = 120
BODY_MAX_BYTES = 8 * 1024
# Bound on raw envelope bytes, checked before any decode. The largest valid
# envelope (an 8 KiB body of control characters, each escaped to 6 bytes,
# plus a full path) is about 55 KiB, so this never refuses a valid one.
ENVELOPE_MAX_BYTES = 64 * 1024
DETAIL_MAX = 128
PATH_MAX = 64
MAX_SKEW_S = 300
DEDUP_DAYS = 30
LOCK_TIMEOUT_S = 10.0
LOCK_RETRY_S = 0.02
QSEQ_WIDTH = 12
SPOOL_STATES = ("tmp", "new", "cur", "done")
MOVES = {("new", "cur"): "read", ("cur", "done"): "acked"}
FIELDS = frozenset({
    "schema", "id", "from", "to", "from_auth", "kind", "needs_answer", "re",
    "thread", "hop", "path", "seq", "sent_at", "body", "body_sha256"})
_SENT_AT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_COUNTER_RE = re.compile(r"[0-9]+\n?")
_QFILE_RE = re.compile(r"([0-9]+)-([0-9a-f]{32})\.json")
_DETAIL_RE = re.compile(r"^[\x20-\x7e]*$")


class EnvelopeError(ValueError):
    """An envelope fails §4. `reason` is one of REJECT_REASONS."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class Refused(Exception):
    """A §11 rule refused the send before any seq was allocated."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StoreError(Exception):
    """The store is unusable: no lock backend, lock timeout or corrupt counter."""


# --- names and envelope (§3, §4) -------------------------------------------

def valid_name(name) -> bool:
    return isinstance(name, str) and NAME_RE.fullmatch(name) is not None


def split_qualified(qualified) -> tuple[str, str]:
    """`name@site` -> (name, site). Both parts use the identity grammar."""
    if not isinstance(qualified, str) or qualified.count("@") != 1:
        raise EnvelopeError("schema", f"not name@site: {qualified!r}")
    name, site = qualified.split("@")
    if not (valid_name(name) and valid_name(site)):
        raise EnvelopeError("schema", f"bad name@site: {qualified!r}")
    return name, site


def new_id() -> str:
    """128-bit random hex; the dedup key, never compared by order."""
    return secrets.token_hex(16)


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(int(epoch), timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(text: str) -> float:
    if not isinstance(text, str) or not _SENT_AT_RE.fullmatch(text):
        raise EnvelopeError("schema", f"bad sent_at: {text!r}")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise EnvelopeError("schema", f"bad sent_at: {text!r}") from None
    return parsed.replace(tzinfo=timezone.utc).timestamp()


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def canonical(envelope: dict) -> bytes:
    """The one serialisation (§4); stored bytes always equal this."""
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def make_draft(frm: str, to: str, body: str, *, from_auth: dict,
               sent_at: str, kind: str = "note", needs_answer: bool = NEEDS_ANSWER_DEFAULT,
               parent: dict | None = None, msg_id: str | None = None) -> dict:
    """An envelope without `seq`; `enqueue()` allocates it.

    A root has `re` null, `thread` = its own id, `hop` 0 and `path` [from].
    A reply has `re` = parent id, `thread` = parent thread, `hop` = parent
    hop + 1 and `path` = parent path + [from]. A retry passes the same
    `msg_id`.
    """
    msg_id = new_id() if msg_id is None else msg_id
    if parent is None:
        re_, thread, hop, path = None, msg_id, 0, [frm]
    else:
        re_, thread = parent["id"], parent["thread"]
        hop, path = parent["hop"] + 1, list(parent["path"]) + [frm]
    draft = {
        "schema": SCHEMA, "id": msg_id, "from": frm, "to": to,
        "from_auth": dict(from_auth), "kind": kind,
        "needs_answer": needs_answer, "re": re_, "thread": thread, "hop": hop,
        "path": path, "seq": None, "sent_at": sent_at, "body": body,
        "body_sha256": None,
    }
    _check_body(body)
    draft["body_sha256"] = body_sha256(body)
    validate(draft, draft=True)
    return draft


def _check_body(body) -> None:
    if not isinstance(body, str):
        raise EnvelopeError("schema", "body is not a string")
    try:
        encoded = body.encode("utf-8")
    except UnicodeEncodeError:
        raise EnvelopeError("schema", "body is not valid UTF-8 text") from None
    if len(encoded) > BODY_MAX_BYTES:
        raise EnvelopeError("size", f"body over {BODY_MAX_BYTES} bytes")
    if len(body.split()) > BODY_MAX_WORDS:
        raise EnvelopeError("size", f"body over {BODY_MAX_WORDS} words")


def validate(env, *, draft: bool = False) -> dict:
    """Raise EnvelopeError unless `env` is a §4 envelope; return it."""
    if not isinstance(env, dict):
        raise EnvelopeError("schema", "envelope is not an object")
    if set(env) != FIELDS:
        raise EnvelopeError("schema", "field set differs: " + ",".join(
            sorted(set(env) ^ FIELDS)))
    if env["schema"] != SCHEMA or type(env["schema"]) is not int:
        raise EnvelopeError("schema", f"unknown schema {env['schema']!r}")
    if not (isinstance(env["id"], str) and ID_RE.fullmatch(env["id"])):
        raise EnvelopeError("schema", "bad id")
    split_qualified(env["from"])
    split_qualified(env["to"])
    auth = env["from_auth"]
    if not (isinstance(auth, dict) and set(auth) == {"method", "detail"}
            and auth["method"] in METHODS):
        raise EnvelopeError("schema", "bad from_auth")
    detail = auth["detail"]
    if detail is not None and not (isinstance(detail, str)
                                   and len(detail) <= DETAIL_MAX
                                   and _DETAIL_RE.fullmatch(detail)):
        raise EnvelopeError("schema", "bad from_auth.detail")
    if env["kind"] not in KINDS:
        raise EnvelopeError("schema", f"bad kind {env['kind']!r}")
    if type(env["needs_answer"]) is not bool:
        raise EnvelopeError("schema", "needs_answer is not a bool")
    for key in ("re", "thread"):
        value = env[key]
        if value is not None and not (isinstance(value, str) and ID_RE.fullmatch(value)):
            raise EnvelopeError("schema", f"bad {key}")
    if env["thread"] is None:
        raise EnvelopeError("schema", "thread is null")
    hop, path = env["hop"], env["path"]
    if type(hop) is not int or hop < 0:
        raise EnvelopeError("schema", "bad hop")
    if not (isinstance(path, list) and 1 <= len(path) <= PATH_MAX):
        raise EnvelopeError("schema", "bad path")
    for item in path:
        split_qualified(item)
    if len(path) != hop + 1 or path[-1] != env["from"]:
        raise EnvelopeError("schema", "path does not end at from after hop entries")
    if (env["re"] is None) != (hop == 0):
        raise EnvelopeError("schema", "re and hop disagree")
    if env["re"] is None and env["thread"] != env["id"]:
        raise EnvelopeError("schema", "root thread is not its own id")
    seq = env["seq"]
    if draft:
        if seq is not None:
            raise EnvelopeError("schema", "draft carries a seq")
    elif type(seq) is not int or seq < 1:
        raise EnvelopeError("schema", "bad seq")
    parse_iso_utc(env["sent_at"])
    _check_body(env["body"])
    if env["body_sha256"] != body_sha256(env["body"]):
        raise EnvelopeError("corrupt", "body_sha256 mismatch")
    if not draft and len(canonical(env)) > ENVELOPE_MAX_BYTES:
        raise EnvelopeError("size", f"envelope over {ENVELOPE_MAX_BYTES} bytes")
    return env


def parse(raw: bytes) -> dict:
    """Bytes -> validated envelope. Every failure is an EnvelopeError.

    The size bound runs before any decode. Non-canonical bytes are `corrupt`.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise EnvelopeError("corrupt", "envelope is not bytes")
    raw = bytes(raw)
    if len(raw) > ENVELOPE_MAX_BYTES:
        raise EnvelopeError("size", f"envelope over {ENVELOPE_MAX_BYTES} bytes")
    try:
        env = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise EnvelopeError("corrupt", f"not JSON: {type(exc).__name__}") from None
    try:
        validate(env)
    except EnvelopeError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        # Defence in depth: hostile bytes must never escape unclassified.
        raise EnvelopeError("corrupt", f"unclassified: {type(exc).__name__}") from None
    if canonical(env) != raw:
        raise EnvelopeError("corrupt", "not canonical JSON")
    return env


def clock_check(env: dict, now: float, *, max_skew: int = MAX_SKEW_S,
                dedup_days: int = DEDUP_DAYS) -> str | None:
    """Receiver bound (§6): `future`, `stale`, or None, by the receiver's clock."""
    sent = parse_iso_utc(env["sent_at"])
    if sent > now + max_skew:
        return "future"
    if sent < now - dedup_days * 86400:
        return "stale"
    return None


# --- store (§5) -------------------------------------------------------------

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _noop(_point: str) -> None:
    return None


@dataclass
class Store:
    """One home's `state/msg/`. Every hook is injectable for tests.

    `fault(point)` runs at each named step of `publish()` and `enqueue()`;
    a test raises from it to simulate a crash there. No path under
    `state/msg/` may be a symlink: the store refuses one instead of following
    it (spec §5.1).
    """
    home: Path
    site: str
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    fsync: Callable[[int], None] = os.fsync
    fsync_dir: Callable[[Path], None] = PLATFORM.fsync_dir
    append: Callable[[Path, bytes], None] = PLATFORM.atomic_append_bytes
    fault: Callable[[str], None] = _noop
    lock_timeout: float = LOCK_TIMEOUT_S

    def __post_init__(self):
        self.home = Path(self.home)
        if not valid_name(self.site):
            raise StoreError(f"bad site label {self.site!r}")

    @property
    def root(self) -> Path:
        return self.home / "state" / "msg"

    def spool(self, name: str, state: str) -> Path:
        _require_name(name)
        if state not in SPOOL_STATES:
            raise StoreError(f"bad spool state {state!r}")
        return self.root / "spool" / name / state

    def marker(self, msg_id: str) -> Path:
        _require_id(msg_id)
        return self.root / "seen" / msg_id[:2] / msg_id

    def seq_path(self, frm: str, to: str) -> Path:
        split_qualified(frm)
        split_qualified(to)
        return self.root / "seq" / f"{frm}__{to}"

    def outbox(self, site: str, state: str) -> Path:
        _require_name(site)
        if state not in ("tmp", "q", "sent"):
            raise StoreError(f"bad outbox state {state!r}")
        return self.root / "outbox" / site / state

    def qseq_path(self, site: str) -> Path:
        _require_name(site)
        return self.root / "outbox" / site / "qseq"

    def lock_path(self, kind: str, name: str) -> Path:
        # Fixed prefixes keep the three lock families disjoint for every
        # name the grammar allows (spec §5.1).
        if kind not in ("from", "spool", "outbox"):
            raise StoreError(f"bad lock kind {kind!r}")
        _require_name(name)
        return self.root / "locks" / f"{kind}-{name}.lock"

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def rejected_dir(self) -> Path:
        return self.root / "rejected"

    def ledger(self, event: str, **fields) -> None:
        """One operational log line. Never a body, never a nonce."""
        record = {"ts": iso_utc(self.clock()), "event": event, **fields}
        self._ensure_dir(self.root)
        self._require_regular_or_absent(self.ledger_path)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        self.append(self.ledger_path, line.encode("utf-8"))

    def _require_regular_or_absent(self, path: Path) -> bool:
        """True if `path` is a regular file, False if absent; else refuse."""
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(st.st_mode):
            raise StoreError(f"{path.name} is not a regular file")
        return True

    def _ensure_dir(self, path: Path) -> None:
        """mkdir -p under `state/msg/`, refusing any symlinked component and
        fsyncing each parent whose entry was created."""
        path = Path(path)
        root = self.root
        if path != root and root not in path.parents:
            raise StoreError(f"{path} is outside the message store")
        if not root.parent.is_dir():
            os.makedirs(root.parent, exist_ok=True)
        chain = [root] + [root.joinpath(*path.relative_to(root).parts[:i])
                          for i in range(1, len(path.relative_to(root).parts) + 1)]
        for component in chain:
            try:
                st = os.lstat(component)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700)
                except FileExistsError:
                    st = os.lstat(component)
                else:
                    self.fsync_dir(component.parent)
                    continue
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise StoreError(f"{component} is not a plain directory")

    @contextmanager
    def locked(self, kind: str, name: str):
        """Hold one OS-released lock (mailman backend); fail closed without one."""
        if fleet_mailman._fcntl is None and fleet_mailman._msvcrt is None:
            raise StoreError("fleet msg requires an OS-supported file lock")
        path = self.lock_path(kind, name)
        self._ensure_dir(path.parent)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_RDWR | _NOFOLLOW, 0o600)
        except OSError as exc:
            raise StoreError(f"cannot open lock {path.name}: {exc}") from None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StoreError(f"lock {path.name} is not a regular file")
            deadline = self.monotonic() + self.lock_timeout
            while True:
                try:
                    fleet_mailman._acquire_owner_lock(fd, initialize=True)
                    break
                except OSError:
                    if self.monotonic() >= deadline:
                        raise StoreError(f"lock timeout: {path.name}") from None
                    self.sleep(LOCK_RETRY_S)
            yield
        finally:
            os.close(fd)

    def _write_new(self, tmp_dir: Path, final: Path, data: bytes, tag: str) -> bool:
        """Write `data` durably at `final` unless it exists. True if written.

        tmp name, fsync, link() (never overwrites), fsync dir, unlink tmp.
        """
        self._ensure_dir(tmp_dir)
        self._ensure_dir(final.parent)
        tmp = tmp_dir / f"{tag}.{os.getpid()}.{secrets.token_hex(4)}"
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            self.fsync(fd)
        finally:
            os.close(fd)
        self.fault("tmp-written")
        try:
            os.link(str(tmp), str(final))
            linked = True
        except FileExistsError:
            linked = False
        if linked:
            self.fault("linked")
            self.fsync_dir(final.parent)
            self.fault("dir-synced")
        os.unlink(str(tmp))  # the private name only; `final` keeps the inode
        return linked

    def _counter_next(self, path: Path) -> int:
        """Read, increment, write a unique tmp name, fsync, rename."""
        self._ensure_dir(path.parent)
        if self._require_regular_or_absent(path):
            text = path.read_text(encoding="ascii", errors="replace")
            if not _COUNTER_RE.fullmatch(text):
                raise StoreError(f"corrupt counter {path.name}")
            current = int(text)
        else:
            current = 0
        value = current + 1
        tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600)
        try:
            os.write(fd, f"{value}\n".encode("ascii"))
            self.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(path))  # the counter only, never a message
        self.fsync_dir(path.parent)
        return value

    def last_seq(self, frm: str, to: str) -> int:
        path = self.seq_path(frm, to)
        if not self._require_regular_or_absent(path):
            return 0
        text = path.read_text(encoding="ascii", errors="replace")
        if not _COUNTER_RE.fullmatch(text):
            raise StoreError(f"corrupt counter {path.name}")
        return int(text)

    def _held(self, name: str, msg_id: str) -> Path | None:
        """The envelope file for `msg_id` in new|cur|done, or None.

        A non-regular entry (a planted symlink) is refused, never treated as
        absent or as the message.
        """
        for state in ("new", "cur", "done"):
            path = self.spool(name, state) / f"{msg_id}.json"
            if self._require_regular_or_absent(path):
                return path
        return None

    def _marked(self, msg_id: str) -> bool:
        return self._require_regular_or_absent(self.marker(msg_id))

    def _mark(self, msg_id: str) -> None:
        path = self.marker(msg_id)
        self._ensure_dir(path.parent)
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY | _NOFOLLOW, 0o600)
        except FileExistsError:
            self._require_regular_or_absent(path)
            return
        try:
            self.fsync(fd)
        finally:
            os.close(fd)
        self.fsync_dir(path.parent)


def _require_name(name) -> None:
    if not valid_name(name):
        raise StoreError(f"bad identity or site name {name!r}")


def _require_id(msg_id) -> None:
    if not (isinstance(msg_id, str) and ID_RE.fullmatch(msg_id)):
        raise StoreError(f"bad message id {msg_id!r}")


def _read_regular(path: Path, limit: int) -> bytes | None:
    """Read a regular file without following a symlink, at most `limit` + 1
    bytes. None if the file is gone (a concurrent commit moved it)."""
    try:
        fd = os.open(str(path), os.O_RDONLY | _NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StoreError(f"cannot open {path.name}: {exc}") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise StoreError(f"{path.name} is not a regular file")
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _ledger_fields(env: dict) -> dict:
    return {"id": env["id"], "from": env["from"], "to": env["to"],
            "kind": env["kind"], "method": env["from_auth"]["method"]}


def _notify(store: Store, notify, name: str, env: dict) -> None:
    """§9: a wake failure is logged only; delivery already completed."""
    if notify is None:
        return
    try:
        notify(name, env)
    except Exception as exc:  # noqa: BLE001 -- wake never fails delivery
        store.ledger("notice-failed", id=env["id"], to=env["to"],
                     error=type(exc).__name__)


# --- the write primitives (§5) ----------------------------------------------

def _publish_locked(store: Store, name: str, env: dict) -> tuple[str, bool]:
    """publish() steps 1-3 under the spool lock. Returns (status, notice due)."""
    msg_id = env["id"]
    with store.locked("spool", name):
        # Refuse a planted ledger before anything is written.
        store._ensure_dir(store.root)
        store._require_regular_or_absent(store.ledger_path)
        marked, held = store._marked(msg_id), store._held(name, msg_id)
        if marked or held:
            if held and not marked:
                # Crash after step 2: repair once (marker, ledger, notice).
                store._mark(msg_id)
                store.ledger("delivered", repaired=True, **_ledger_fields(env))
                return "duplicate", True
            return "duplicate", False
        written = store._write_new(store.spool(name, "tmp"),
                                   store.spool(name, "new") / f"{msg_id}.json",
                                   canonical(env), msg_id)
        if not written:
            # _held() saw no regular file, yet link() hit EEXIST: something
            # unknown sits at the name. Never write a marker for it.
            raise StoreError(f"unexpected entry at new/{msg_id}.json")
        store._mark(msg_id)
        store.fault("marked")
        store.ledger("delivered", **_ledger_fields(env))
        store.fault("ledgered")
    return "delivered", True


def publish(store: Store, name: str, env: dict, *,
            notify: Callable[[str, dict], None] | None = None) -> str:
    """Deliver `env` into local spool `name`. Returns `delivered` or `duplicate`.

    Under `locks/spool-<name>.lock`:
    1. marker exists or `<id>.json` in new|cur|done: return `duplicate`. A
       file without a marker is a crash after step 2: the repair creates the
       marker and runs step 3's ledger line and the notice, once.
    2. tmp write, fsync, link() into new/, fsync new/, unlink the tmp name.
    3. create the marker, fsync; append `delivered` to the ledger.
    The notice runs after every lock is released.
    """
    validate(env)
    _require_name(name)
    if split_qualified(env["to"]) != (name, store.site):
        raise StoreError(f"envelope to {env['to']!r} is not spool {name!r} of this site")
    status, due = _publish_locked(store, name, env)
    if due:
        _notify(store, notify, name, env)
    return status


def _outbox_find(store: Store, site: str, msg_id: str) -> tuple[str, bytes] | None:
    """(`q`|`sent`, bytes) of an outbox entry for `msg_id`, or None."""
    for state in ("q", "sent"):
        directory = store.outbox(site, state)
        try:
            names = os.listdir(directory)
        except FileNotFoundError:
            continue
        for entry in sorted(names):
            match = _QFILE_RE.fullmatch(entry)
            if match and match.group(2) == msg_id:
                raw = _read_regular(directory / entry, ENVELOPE_MAX_BYTES)
                if raw is not None:
                    return state, raw
    return None


def enqueue(store: Store, draft: dict, *,
            rules: Callable[[dict], str | None] | None = None,
            notify: Callable[[str, dict], None] | None = None) -> tuple[str, dict | None]:
    """Send `draft` from a local identity. Returns (status, envelope).

    Under `locks/from-<name>.lock`: a retry of an id already stored returns
    the stored envelope and allocates nothing (`duplicate` locally; `queued`
    or `duplicate` for an outbox entry still in q/ or already in sent/; the
    envelope is None if only the marker remains). Otherwise run every §11
    rule (`rules(draft)` returns a refusal reason or None; a refusal raises
    Refused and allocates nothing), allocate `seq`, then deliver locally
    (`delivered`) or, for a remote `to`, allocate `qseq` and write
    `outbox/<site>/q/<qseq>-<id>.json` inside the one outbox lock (`queued`).
    The notice runs after every lock is released.
    """
    validate(draft, draft=True)
    from_name, from_site = split_qualified(draft["from"])
    to_name, to_site = split_qualified(draft["to"])
    if from_site != store.site:
        raise EnvelopeError("auth", "sender is not a local identity")
    msg_id = draft["id"]
    due = False
    with store.locked("from", from_name):
        if to_site == store.site:
            held = store._held(to_name, msg_id)
            if held is not None or store._marked(msg_id):
                stored = None
                if held is not None:
                    raw = _read_regular(held, ENVELOPE_MAX_BYTES)
                    stored = parse(raw) if raw is not None else None
                return "duplicate", stored
        else:
            found = _outbox_find(store, to_site, msg_id)
            if found is not None:
                state, raw = found
                return ("queued" if state == "q" else "duplicate"), parse(raw)
        if rules is not None:
            reason = rules(draft)
            if reason is not None:
                raise Refused(reason)
        seq = store._counter_next(store.seq_path(draft["from"], draft["to"]))
        store.fault("seq-allocated")
        env = validate(dict(draft, seq=seq))
        if to_site == store.site:
            status, due = _publish_locked(store, to_name, env)
        else:
            with store.locked("outbox", to_site):
                qseq = store._counter_next(store.qseq_path(to_site))
                store.fault("qseq-allocated")
                final = store.outbox(to_site, "q") / f"{qseq:0{QSEQ_WIDTH}d}-{msg_id}.json"
                if not store._write_new(store.outbox(to_site, "tmp"), final,
                                        canonical(env), msg_id):
                    raise StoreError(f"unexpected entry at {final.name}")
            store.ledger("queued", qseq=qseq, **_ledger_fields(env))
            status = "queued"
    if due:
        _notify(store, notify, to_name, env)
    return status, env


def ingest(store: Store, raw: bytes, *, peer_site: str, hosted, now: float | None = None,
           admit: Callable[[dict], str | None] | None = None,
           notify: Callable[[str, dict], None] | None = None) -> str:
    """The one receiver path for an envelope from another site (§6, §7, §10).

    Every transport calls this and nothing lower. In order: size and parse
    (`size`, `corrupt`, `schema`), `to` names this site, `from` is on
    `peer_site` (the transport-authenticated peer) and in its `hosted`
    names (`auth`), the §6 clock bounds by the receiver's clock (`future`,
    `stale`), then `admit(env)` for the §11 ingest cap and retired lanes
    (PR 3/PR 6 supply it; it returns a reject reason or None), then
    `publish()`. A refusal is kept by `reject()`. Returns `accepted`,
    `duplicate` or `rejected:<why>`, the §7 push-result vocabulary.
    """
    _require_name(peer_site)
    if peer_site == store.site:
        raise StoreError("ingest from the local site label")
    now = store.clock() if now is None else now
    msg_id = None
    try:
        env = parse(raw)
        msg_id = env["id"]
        from_name, from_site = split_qualified(env["from"])
        to_name, to_site = split_qualified(env["to"])
        if to_site != store.site:
            raise EnvelopeError("auth", "to is not this site")
        if from_site != peer_site or from_name not in set(hosted):
            raise EnvelopeError("auth", "from is not hosted by the peer")
        bound = clock_check(env, now)
        if bound is not None:
            raise EnvelopeError(bound, "sent_at outside the receiver bounds")
        if admit is not None:
            reason = admit(env)
            if reason is not None:
                raise EnvelopeError(reason, "refused by admit")
    except EnvelopeError as exc:
        if exc.reason not in REJECT_REASONS:
            raise StoreError(f"bad reject reason {exc.reason!r}") from None
        if msg_id is None:
            msg_id = _sniff_id(raw)
        reject(store, bytes(raw[:ENVELOPE_MAX_BYTES]) if isinstance(raw, (bytes, bytearray))
               else b"", exc.reason, msg_id=msg_id)
        return "rejected:" + exc.reason
    status = publish(store, to_name, env, notify=notify)
    return "accepted" if status == "delivered" else "duplicate"


def _sniff_id(raw) -> str | None:
    """Best-effort id of an unparseable envelope, for naming its reject file."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) > ENVELOPE_MAX_BYTES:
        return None
    match = re.search(rb'"id":"([0-9a-f]{32})"', bytes(raw))
    return match.group(1).decode("ascii") if match else None


# --- spool and outbox reads and moves ---------------------------------------

def list_spool(store: Store, name: str, state: str) -> list[str]:
    """Ids in one spool state, sorted. Listing only; no lock."""
    try:
        entries = os.listdir(store.spool(name, state))
    except FileNotFoundError:
        return []
    return sorted(e[:-5] for e in entries
                  if e.endswith(".json") and ID_RE.fullmatch(e[:-5]))


def move(store: Store, name: str, msg_id: str, src: str, dst: str, *,
         reader: str | None = None) -> bool:
    """new -> cur (read) or cur -> done (acked) under the spool lock.

    Holding the ingest lock means a concurrent ingest never sees the file in
    neither state (T3). An existing target is refused, never overwritten.
    Returns False if the file is not in `src`.
    """
    event = MOVES.get((src, dst))
    if event is None:
        raise StoreError(f"bad move {src}->{dst}")
    _require_id(msg_id)
    with store.locked("spool", name):
        source = store.spool(name, src) / f"{msg_id}.json"
        if not store._require_regular_or_absent(source):
            return False
        target_dir = store.spool(name, dst)
        store._ensure_dir(target_dir)
        target = target_dir / f"{msg_id}.json"
        if os.path.lexists(target):
            raise StoreError(f"{dst}/{msg_id}.json already exists")
        os.replace(str(source), str(target))  # target checked absent under the lock
        store.fsync_dir(target_dir)
        store.fsync_dir(source.parent)
    store.ledger(event, id=msg_id, to=f"{name}@{store.site}",
                 **({"reader": reader} if reader else {}))
    return True


def outbox_entries(store: Store, site: str, hint_qseq: int = 0) -> list[tuple[int, bytes]]:
    """Every entry still in `outbox/<site>/q/`, ascending by qseq (§7).

    `hint_qseq` orders paging only and never filters: an entry below it is
    still returned, so a late or slow-clock enqueue is never skipped. An
    entry a concurrent commit moved away is skipped (it is in sent/). An
    entry over ENVELOPE_MAX_BYTES is returned truncated to the bound plus one
    byte, so the receiver's parse() rejects it as `size` without reading it
    whole.
    """
    del hint_qseq
    directory = store.outbox(site, "q")
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    out = []
    for entry in names:
        match = _QFILE_RE.fullmatch(entry)
        if not match:
            continue
        raw = _read_regular(directory / entry, ENVELOPE_MAX_BYTES)
        if raw is not None:
            out.append((int(match.group(1)), raw))
    out.sort(key=lambda item: item[0])
    return out


def outbox_commit(store: Store, site: str, ids: list[str]) -> list[str]:
    """Move exactly these ids from q/ to sent/ under the outbox lock.

    Ids are matched exactly, never by high-water mark. An existing target in
    sent/ is refused, never overwritten. Returns the ids moved.
    """
    wanted = set(ids)
    for msg_id in wanted:
        _require_id(msg_id)
    moved = []
    with store.locked("outbox", site):
        q_dir, sent_dir = store.outbox(site, "q"), store.outbox(site, "sent")
        try:
            names = sorted(os.listdir(q_dir))
        except FileNotFoundError:
            return []
        for entry in names:
            match = _QFILE_RE.fullmatch(entry)
            if match and match.group(2) in wanted:
                store._ensure_dir(sent_dir)
                if os.path.lexists(sent_dir / entry):
                    raise StoreError(f"sent/{entry} already exists")
                os.replace(str(q_dir / entry), str(sent_dir / entry))  # checked absent
                moved.append(match.group(2))
        if moved:
            store.fsync_dir(sent_dir)
            store.fsync_dir(q_dir)
    for msg_id in moved:
        store.ledger("sent", id=msg_id, site=site)
    return moved


def reject(store: Store, raw: bytes, reason: str, *, msg_id: str | None = None) -> Path:
    """Keep a refused inbound envelope in `rejected/` with its reason.

    The file is `<id>-<sha256[:16]>.json` (or `sha-<sha256[:32]>.json`
    without an id), so distinct bytes never share a name and none are
    dropped. An identical re-reject is a no-op with no second ledger line.
    """
    if reason not in REJECT_REASONS:
        raise StoreError(f"bad reject reason {reason!r}")
    raw = bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if msg_id is not None and not (isinstance(msg_id, str) and ID_RE.fullmatch(msg_id)):
        msg_id = None
    key = f"{msg_id}-{digest[:16]}" if msg_id else f"sha-{digest[:32]}"
    record = {"schema": SCHEMA, "id": msg_id, "reason": reason,
              "rejected_at": iso_utc(store.clock()), "sha256": digest,
              "raw_b64": base64.b64encode(raw).decode("ascii")}
    final = store.rejected_dir / f"{key}.json"
    if store._write_new(store.rejected_dir / "tmp", final, canonical(record), key):
        store.ledger("rejected", id=msg_id, reason=reason, sha256=digest)
    return final
