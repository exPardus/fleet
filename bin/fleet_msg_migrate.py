"""Migration from mailman mail to `fleet msg` (docs/specs/messaging.md §12
steps 2-3, §8 `msg import`; plan PR 9a).

Three independent pieces, none wired into a verb here:

* `render_to_fleet` writes one envelope addressed to `interface` into
  `mailbox/to-fleet/` as mailman-format mail (headers `from`, `kind`,
  `needs-answer`, `re`, `msg-id`). The file name is derived from the message id, so
  a replay writes nothing twice, and mailman's own filing into `done/` is
  recognised as "already rendered".
* `import_dir` turns each mailman-format file of an outbound directory into an
  envelope with method `legacy-unverified` and sends it with `core.enqueue`.
  The message id is derived from the file bytes (or taken from a `msg-id`
  header), so a crash or a second run re-sends nothing. The source is never
  moved or deleted (spec §12 step 3 says "moves the original to `done/`"; that
  step is left to the operator or PR 9b so no message is ever removed here).
* `fold` reads one id from the message store (spool, outbox, rejected, ledger)
  and folds it into one `Folded` record: the replacement for
  `state/mail-receipts/` that `fleet mail verify` reads first (§12 step 5).

Doctrine (spec §14): every path component under `mailbox/` is `lstat`-checked
and files open `O_NOFOLLOW`; a planted link or a non-regular file is skipped or
refused, never followed. Stdlib only, Python 3.10. Imports `fleet_msg_core`
only; every fleet helper it needs (fsync, clock, fault hooks) is on the
`core.Store` it is handed. No `fleet.lock`, no registry
write, no deletion of a message.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

import fleet_msg_core as core

MAIL_MAX_BYTES = 1024 * 1024          # mailman's bound (docs/specs/mailman.md §3)
LEGACY_SENDER = "legacy"
RENDER_PREFIX = "msg-"
INTERFACE = "interface"
_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):[ \t]*(.*)$")
_FROM_STRIP_RE = re.compile(r"[^a-z0-9-]+")
_NL_RE = re.compile(r"\r\n?")


class MigrateError(Exception):
    """A refusal printed as one line."""


# --- mailman format ---------------------------------------------------------

def mail_name(msg_id: str) -> str:
    return f"{RENDER_PREFIX}{msg_id}.mail"


def render_text(env: dict) -> str:
    """The mailman-format text of `env`. Header values are single-line: a
    qualified name is `[a-z0-9@-]` and the rest is a fixed vocabulary."""
    core.validate(env)
    lines = [f"from: {env['from']}", f"kind: {env['kind']}",
             f"needs-answer: {'yes' if env['needs_answer'] else 'no'}"]
    if env["re"] is not None:
        lines.append(f"re: {env['re']}")
    lines.append(f"msg-id: {env['id']}")
    return "\n".join(lines) + "\n\n" + env["body"] + "\n"


def parse_mail(raw: bytes) -> dict:
    """`{headers: {name: [values]}, body}` of a mailman-format file; raises
    MigrateError on anything mailman would call malformed."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise MigrateError("not valid UTF-8") from None
    if not text.strip():
        raise MigrateError("empty file")
    lines = _NL_RE.sub("\n", text).split("\n")
    headers: dict = {}
    idx = 0
    while idx < len(lines) and lines[idx].strip():
        match = _HEADER_RE.match(lines[idx])
        if not match:
            raise MigrateError("bad header line")
        headers.setdefault(match.group(1).lower(), []).append(match.group(2).strip())
        idx += 1
    if not headers:
        raise MigrateError("no header block")
    kinds = headers.get("kind", [])
    if not kinds or not kinds[0]:
        raise MigrateError("kind missing")
    answers = [a.lower() for a in headers.get("needs-answer", [])]
    if any(a not in ("yes", "no") for a in answers):
        raise MigrateError("bad needs-answer")
    body = "\n".join(lines[idx + 1:]).strip("\n")
    return {"headers": headers, "body": body, "needs_answer": "yes" in answers}


# --- path safety ------------------------------------------------------------

def _plain_dir(path: Path, *, create: bool) -> None:
    """Refuse `path` unless it is a real directory (never a symlink)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        if not create:
            raise MigrateError(f"{path.name} does not exist") from None
        try:
            path.mkdir(parents=False, exist_ok=True)
        except OSError as exc:
            raise MigrateError(f"cannot create {path.name}: {exc}") from None
        st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise MigrateError(f"{path.name} is not a plain directory")


def _chain(home: Path, *parts: str, create: bool) -> Path:
    """`home/parts...`, each component lstat-checked. `home` itself is the
    operator's choice and is not checked."""
    path = Path(home)
    for part in parts:
        path = path / part
        _plain_dir(path, create=create)
    return path


# --- render (§12 step 2) ----------------------------------------------------

def _already_rendered(to_fleet: Path, done: Path, name: str) -> bool:
    """True when mailman has not yet filed the render, or has (the filed copy
    keeps the name, possibly with a `.<sha12>` collision suffix)."""
    if os.path.lexists(to_fleet / name):
        return True
    try:
        if not stat.S_ISDIR(os.lstat(done).st_mode):
            return False
        stem = name[:-len(".mail")]
        return any(n == name or (n.startswith(stem + ".") and n.endswith(".mail"))
                   for n in os.listdir(done))
    except FileNotFoundError:
        return False


def render_to_fleet(store: core.Store, env: dict) -> str:
    """Render `env` (to `interface`) into `mailbox/to-fleet/`. Returns
    `rendered` or `duplicate`.

    Crash-safe with no deletion: the mail is first written durably under
    `state/msg/render/<name>` (tmp, fsync, `link()`, the store's own
    primitive), then hard-linked into `to-fleet/`, so the mail appears whole
    or not at all. A crash between the two steps leaves the staged copy, and
    the retry links it. A retry after mailman filed the mail finds it in
    `done/` and writes nothing.
    """
    core.validate(env)
    if core.split_qualified(env["to"])[0] != INTERFACE:
        raise MigrateError(f"refused: render is for messages to {INTERFACE!r}")
    data = render_text(env).encode("utf-8")
    if len(data) > MAIL_MAX_BYTES:
        raise MigrateError("refused: rendered mail over the mailman bound")
    Path(store.home).mkdir(parents=True, exist_ok=True)
    mailbox = _chain(store.home, "mailbox", create=True)
    to_fleet = _chain(mailbox, "to-fleet", create=True)
    name = mail_name(env["id"])
    staged = store.root / "render" / name
    store._write_new(store.root / "render" / "tmp", staged, data, env["id"])
    store.fault("render-staged")
    if _already_rendered(to_fleet, mailbox / "done", name):
        return "duplicate"
    store._require_regular_or_absent(staged)
    try:
        os.link(str(staged), str(to_fleet / name))
    except FileExistsError:
        return "duplicate"
    store.fault("render-linked")
    store.fsync_dir(to_fleet)
    return "rendered"


# --- import (§12 step 3, §8) ------------------------------------------------

@dataclass
class ImportResult:
    imported: list = field(default_factory=list)    # (file, id) sent now
    duplicate: list = field(default_factory=list)   # (file, id) already stored
    skipped: list = field(default_factory=list)     # (file, reason) left alone


def legacy_sender(label: str, site: str) -> str:
    """The envelope `from` for a mailman `from` label: lowercase, `[a-z0-9-]`,
    must start with a letter, at most 40 characters; else `legacy`."""
    name = _FROM_STRIP_RE.sub("-", label.lower().split("@")[0]).strip("-")[:40]
    if not core.valid_name(name):
        name = LEGACY_SENDER
    return f"{name}@{site}"


def legacy_id(filename: str, raw: bytes) -> str:
    """Deterministic id of an imported file: the same bytes under the same
    name always give the same id, so a re-run is a `duplicate`."""
    digest = hashlib.sha256()
    digest.update(b"fleet-msg-import\0" + filename.encode("utf-8", "replace")
                  + b"\0" + raw)
    return digest.hexdigest()[:32]


def _candidates(directory: Path) -> list:
    try:
        names = sorted(os.listdir(directory))
    except FileNotFoundError:
        raise MigrateError(f"{directory} does not exist") from None
    except OSError as exc:
        raise MigrateError(f"cannot list {directory}: {exc}") from None
    return [n for n in names if not n.startswith(".") and not n.endswith(".tmp")]


def _read_mail(path: Path) -> "tuple[bytes | None, str | None]":
    try:
        st = os.lstat(path)
    except OSError as exc:
        return None, f"unreadable: {type(exc).__name__}"
    if not stat.S_ISREG(st.st_mode):
        return None, "not a regular file"
    if st.st_size > MAIL_MAX_BYTES:
        return None, "over the mailman bound"
    try:
        raw = core._read_regular(path, MAIL_MAX_BYTES)
    except core.StoreError:
        return None, "not a regular file"
    if raw is None:
        return None, "vanished"
    if len(raw) > MAIL_MAX_BYTES:
        return None, "over the mailman bound"
    return raw, None


def _envelope_for(store: core.Store, name: str, raw: bytes, to: str) -> dict:
    mail = parse_mail(raw)
    headers = mail["headers"]
    declared = (headers.get("msg-id") or [""])[0].lower()
    msg_id = declared if core.ID_RE.fullmatch(declared) else legacy_id(name, raw)
    label = (headers.get("from") or [LEGACY_SENDER])[0]
    sent_at = core.iso_utc(store.clock())
    return core.make_draft(
        legacy_sender(label, store.site), to, mail["body"],
        from_auth={"method": "legacy-unverified", "detail": "import"},
        sent_at=sent_at, kind="note", needs_answer=mail["needs_answer"],
        msg_id=msg_id)


def import_dir(store: core.Store, directory, to: str, *,
               rules=None) -> ImportResult:
    """Send each mailman-format file of `directory` to `to` (`name@site`).

    Idempotent: ids come from `legacy_id` (or a `msg-id` header), and
    `core.enqueue` returns `duplicate` for an id already stored, so a crash at
    any point and a second run send each file at most once. A file that is not
    a regular file, is oversize, malformed, or has a body over the envelope
    bounds is skipped and left in place with its reason. The source is never
    moved or deleted; retiring the directory is the operator's step.
    """
    core.split_qualified(to)
    directory = Path(directory)
    try:
        if not stat.S_ISDIR(os.lstat(directory).st_mode):
            raise MigrateError(f"{directory} is not a plain directory")
    except FileNotFoundError:
        raise MigrateError(f"{directory} does not exist") from None
    result = ImportResult()
    for name in _candidates(directory):
        path = directory / name
        raw, problem = _read_mail(path)
        if problem is not None:
            result.skipped.append((name, problem))
            continue
        try:
            draft = _envelope_for(store, name, raw, to)
        except (MigrateError, core.EnvelopeError) as exc:
            result.skipped.append((name, str(exc) or type(exc).__name__))
            continue
        try:
            status, env = core.enqueue(store, draft, rules=rules)
        except core.Refused as exc:
            result.skipped.append((name, f"refused: {exc}"))
            continue
        bucket = result.imported if status in ("delivered", "queued") else result.duplicate
        bucket.append((name, draft["id"]))
        if status in ("delivered", "queued"):
            store.ledger("imported", id=draft["id"], to=to, source=name[:64])
    return result


# --- receipt-store fold reader (§12 step 5) ---------------------------------

@dataclass(frozen=True)
class Folded:
    """What the message store knows of one id."""
    id: str
    state: str                      # new|read|acked|queued|sent|rejected|marked
    where: "str | None"
    envelope: "dict | None"
    events: tuple                   # ((ts, event), ...) from the ledger, oldest first
    reason: "str | None" = None     # reject reason

    @property
    def verified(self) -> bool:
        """True only for a stored envelope whose method is not unverified."""
        env = self.envelope
        return bool(env) and env["from_auth"]["method"] not in core.UNVERIFIED_METHODS


_STATE_OF = {"new": "new", "cur": "read", "done": "acked"}


def _spool_hit(store: core.Store, msg_id: str):
    spool = store.root / "spool"
    try:
        names = sorted(os.listdir(spool))
    except OSError:
        return None
    for name in names:
        if not core.valid_name(name):
            continue
        for state in ("new", "cur", "done"):
            path = spool / name / state / f"{msg_id}.json"
            try:
                raw = core._read_regular(path, core.ENVELOPE_MAX_BYTES)
                if raw is not None:
                    return f"spool/{name}/{state}", state, core.parse(raw)
            except (core.StoreError, core.EnvelopeError):
                continue
    return None


def _rejected_hit(store: core.Store, msg_id: str):
    try:
        names = sorted(os.listdir(store.rejected_dir))
    except OSError:
        return None
    for name in names:
        if name.startswith(msg_id + "-") and name.endswith(".json"):
            try:
                raw = core._read_regular(store.rejected_dir / name, core.ENVELOPE_MAX_BYTES * 2)
                data = json.loads(raw.decode("utf-8")) if raw else None
            except (core.StoreError, OSError, UnicodeError, ValueError):
                return name, None
            reason = data.get("reason") if isinstance(data, dict) else None
            return name, reason if isinstance(reason, str) else None
    return None


def _events(store: core.Store, msg_id: str) -> tuple:
    out = []
    try:
        st = os.lstat(store.ledger_path)
        if not stat.S_ISREG(st.st_mode):
            return ()
        with open(store.ledger_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if msg_id not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("id") == msg_id:
                    out.append((str(record.get("ts")), str(record.get("event"))))
    except OSError:
        return ()
    return tuple(out)


def fold(store: core.Store, msg_id: str) -> "Folded | None":
    """Fold spool, outbox, rejected, marker and ledger into one record of
    `msg_id`; None when the store has never seen it. Read-only: no lock, no
    write, no registry."""
    if not (isinstance(msg_id, str) and core.ID_RE.fullmatch(msg_id)):
        return None
    events = _events(store, msg_id)
    hit = _spool_hit(store, msg_id)
    if hit is not None:
        where, state, env = hit
        return Folded(msg_id, _STATE_OF[state], where, env, events)
    try:
        sites = sorted(os.listdir(store.root / "outbox"))
    except OSError:
        sites = []
    for site in sites:
        if not core.valid_name(site):
            continue
        try:
            found = core._outbox_find(store, site, msg_id)
        except core.StoreError:
            continue
        if found is not None:
            try:
                env = core.parse(found[1])
            except core.EnvelopeError:
                continue
            return Folded(msg_id, "queued" if found[0] == "q" else "sent",
                          f"outbox/{site}/{found[0]}", env, events)
    rejected = _rejected_hit(store, msg_id)
    if rejected is not None:
        return Folded(msg_id, "rejected", f"rejected/{rejected[0]}", None, events,
                      reason=rejected[1])
    if os.path.lexists(store.marker(msg_id)):
        return Folded(msg_id, "marked", None, None, events)
    return Folded(msg_id, "ledger", None, None, events) if events else None
