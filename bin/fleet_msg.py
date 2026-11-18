"""`fleet msg` in one home (docs/specs/messaging.md §3, §6, §8, §10; plan PR 2).

The verbs `init`, `send`, `inbox`, `ack`, `status`, `queue`, `ids` and
`whois` over the store primitives in `fleet_msg_core`. Lane, supervisor and
interface identities are implicit: a lane is a registry row, `supervisor` is
the claim holder, `interface` is the current registration. Fleet helpers come
in as an injected `MsgPrims`, so this module never imports `fleet.py`.

Doctrine: stdlib only, Python 3.10. No `fleet.lock`, no registry write, no
steer. `status`, `queue`, `ids`, `whois` and `inbox --peek` write nothing.
Rules, the fs transport and the notice are wired in plan PR 6, not here.
"""
from __future__ import annotations

import json
import math
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import fleet_msg_core as core

SUPERVISOR, INTERFACE = "supervisor", "interface"
OUTBOX_WARN_S = 900
WAIT_POLL_S = 1.0
EXIT_TIMEOUT = 3
# A caller proof is (identity name, method, detail). Order is preference when
# the caller names no `--from`: a live nonce first, the plain sid last.
PROOF_ORDER = ("supervisor-nonce", "lane-registry", "supervisor-sid",
               "interface-registration")
UNVERIFIED_METHODS = ("unverified", "legacy-unverified")


class MsgError(Exception):
    """A refusal printed as one line; `code` is the exit status."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class MsgPrims:
    """Fleet helpers, injected so this module never imports `fleet.py`.
    Every callable is read-only."""
    fleet_home: Path
    workers: Callable[[], "dict | None"]
    """The registry's `workers` map, read lock-free; None when unreadable."""
    is_supervisor_shaped: Callable[[str], bool]
    lane_sender: Callable[[], "str | None"]
    """Fleet's `_registered_lane_mail_sender()`."""
    interface_source: Callable[[], "dict | None"]
    """Fleet's `_registered_interface_mail_source()`."""
    caller_sid: Callable[[], "str | None"]
    codex_thread: Callable[[], "str | None"]
    claim: Callable[[], "dict | None"]
    """Fleet's `read_incarnation()`."""
    nonce_presentation: Callable[[dict, str], "str | None"]
    nonce_digest: Callable[[str], str]
    homes: Callable[[], list]
    """Members of the machine homes list (paths)."""
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep


# --- store and config -------------------------------------------------------

def _root(home: Path) -> Path:
    return Path(home) / "state" / "msg"


def _read_json(path: Path):
    """A regular JSON file's value, or None when absent. A symlink or a
    non-regular entry is refused, never followed."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise MsgError(f"{path.name} is not a regular file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MsgError(f"{path.name} unreadable: {type(exc).__name__}") from None


def read_site(home: Path) -> "str | None":
    data = _read_json(_root(home) / "site.json")
    if data is None:
        return None
    if not (isinstance(data, dict) and set(data) == {"site"} and core.valid_name(data["site"])):
        raise MsgError("site.json is not {\"site\": LABEL}")
    return data["site"]


def open_store(prims: MsgPrims) -> core.Store:
    site = read_site(prims.fleet_home)
    if site is None:
        raise MsgError(f"no site label: run fleet --fleet-home {prims.fleet_home} "
                       "msg init --site LABEL")
    return core.Store(prims.fleet_home, site, clock=prims.clock, sleep=prims.sleep)


def _config(store: core.Store) -> dict:
    data = _read_json(store.root / "config.json")
    return data if isinstance(data, dict) else {}


def _peers(store: core.Store) -> dict:
    data = _read_json(store.root / "peers.json")
    return data if isinstance(data, dict) else {}


# --- identities (§3) --------------------------------------------------------

def _lane_holder(record: dict) -> "str | None":
    thread = record.get("codex_thread_id")
    if isinstance(thread, str) and thread:
        return f"codex-thread:{thread}"
    sid = record.get("session_id")
    if isinstance(sid, str) and sid:
        return f"session:{sid}"
    return None


def resolve(prims: MsgPrims, store: core.Store, name: str) -> "dict | None":
    """A local identity: {name, kind, holder, retired}, or None if unknown.
    Read-only: the registry is read lock-free and nothing is written."""
    if name == SUPERVISOR:
        claim = prims.claim()
        holder = None
        if isinstance(claim, dict) and claim.get("state") != "released":
            if claim.get("provider") == "codex":
                thread = (claim.get("holder") or {}).get("thread_id")
                holder = f"codex-thread:{thread}" if thread else None
            elif claim.get("session_id"):
                holder = f"session:{claim['session_id']}"
        return {"name": name, "kind": "supervisor", "holder": holder, "retired": False}
    if name == INTERFACE:
        return {"name": name, "kind": "interface", "holder": "registration",
                "retired": False}
    workers = prims.workers() or {}
    record = workers.get(name) if isinstance(workers, dict) else None
    if isinstance(record, dict) and not prims.is_supervisor_shaped(name):
        return {"name": name, "kind": "lane", "holder": _lane_holder(record),
                "retired": record.get("archived_at") is not None,
                "epoch": record.get("created")}
    role = _read_json(store.root / "ids" / f"{name}.json")
    if isinstance(role, dict):
        return {"name": name, "kind": "role", "holder": role.get("binding"),
                "retired": False}
    return None


def _reader_body(prims: MsgPrims) -> str:
    """The reading body for the ledger. Never a nonce."""
    thread = prims.codex_thread()
    if thread:
        return f"codex-thread:{thread}"
    sid = prims.caller_sid()
    if sid:
        return f"session:{sid}"
    pane = os.environ.get("TMUX_PANE")
    return f"pane:{pane}" if pane else "shell"


def _supervisor_sid(prims: MsgPrims, claim) -> bool:
    """The caller's sid (or Codex thread) equals the claim holder's."""
    if not isinstance(claim, dict) or claim.get("state") == "released":
        return False
    if claim.get("provider") == "codex":
        thread = prims.codex_thread()
        return bool(thread) and thread == (claim.get("holder") or {}).get("thread_id")
    sid = prims.caller_sid()
    return bool(sid) and sid == claim.get("session_id")


def caller_proofs(prims: MsgPrims, nonce: "str | None" = None) -> list:
    """Every identity the caller proves, as (name, method, detail), best first
    (§10). A presented nonce that does not match the live claim refuses."""
    proofs = []
    claim = prims.claim()
    if nonce:
        held = (isinstance(claim, dict) and claim.get("state") != "released"
                and ("nonce_hash" in claim or "state" in claim))
        presented = prims.nonce_presentation(claim, nonce) if held else None
        if presented == "pending":
            raise MsgError("--nonce is a pending generation: run a gated verb first")
        if presented != "live":
            raise MsgError("--nonce does not match the current supervisor generation")
        detail = (f"nonce_seq={claim.get('nonce_seq', '?')} "
                  f"sha={prims.nonce_digest(nonce)[:8]}")
        proofs.append((SUPERVISOR, "supervisor-nonce", detail))
    lane = prims.lane_sender()
    if lane is not None:
        proofs.append((lane, "lane-registry", None))
    if _supervisor_sid(prims, claim):
        proofs.append((SUPERVISOR, "supervisor-sid", None))
    source = prims.interface_source()
    if source is not None:
        proofs.append((INTERFACE, "interface-registration",
                       str(source.get("kind", ""))[:core.DETAIL_MAX] or None))
    return proofs


def _proof_for(proofs: list, name: str):
    for proof in proofs:
        if proof[0] == name:
            return proof
    return None


def _require_holder(prims: MsgPrims, name: str) -> tuple:
    """§10: non-peek reads and acks need the caller to hold `name`."""
    proof = _proof_for(caller_proofs(prims), name)
    if proof is None:
        raise MsgError(f"refused: the caller does not hold {name!r} "
                       "(use --peek to look without reading)")
    return proof


def _default_name(prims: MsgPrims) -> str:
    proofs = caller_proofs(prims)
    if not proofs:
        raise MsgError("cannot resolve the caller's identity; name one")
    return proofs[0][0]


# --- envelopes on disk -------------------------------------------------------

def _load(store: core.Store, name: str, state: str, msg_id: str) -> "dict | None":
    try:
        raw = core._read_regular(store.spool(name, state) / f"{msg_id}.json",
                                 core.ENVELOPE_MAX_BYTES)
        return core.parse(raw) if raw is not None else None
    except (core.EnvelopeError, core.StoreError):
        return None


def _spool_names(store: core.Store) -> list:
    try:
        return sorted(n for n in os.listdir(store.root / "spool") if core.valid_name(n))
    except FileNotFoundError:
        return []


def _find(store: core.Store, msg_id: str):
    """(where, envelope) for a stored id: `spool/<name>/<state>` or
    `outbox/<site>/<q|sent>`; None when absent."""
    for name in _spool_names(store):
        for state in ("new", "cur", "done"):
            env = _load(store, name, state, msg_id)
            if env is not None:
                return f"spool/{name}/{state}", env
    try:
        sites = sorted(os.listdir(store.root / "outbox"))
    except FileNotFoundError:
        sites = []
    for site in sites:
        if not core.valid_name(site):
            continue
        found = core._outbox_find(store, site, msg_id)
        if found is not None:
            try:
                return f"outbox/{site}/{found[0]}", core.parse(found[1])
            except core.EnvelopeError:
                continue
    return None


def _ledger(store: core.Store):
    """Ledger records, streamed line by line (the ledger only grows)."""
    try:
        st = os.lstat(store.ledger_path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode):
        raise MsgError("ledger.jsonl is not a regular file")
    with open(store.ledger_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def _readers(store: core.Store) -> dict:
    return {r.get("id"): r.get("reader") for r in _ledger(store)
            if r.get("event") == "read" and r.get("reader")}


def direction(store: core.Store, env: dict) -> str:
    """§10: a task is direction only from the local supervisor with a nonce,
    the configured Interface site, or a `direct: true` peer; else
    `remote-task`. Other kinds pass through."""
    if env["kind"] != "task":
        return env["kind"]
    method = env["from_auth"]["method"]
    _name, site = core.split_qualified(env["from"])
    if site == store.site and method == "supervisor-nonce":
        return "task"
    if method == "interface-registration" and site == _config(store).get(
            "interface_site", store.site):
        return "task"
    peer = _peers(store).get(site)
    if site != store.site and isinstance(peer, dict) and peer.get("direct") is True:
        return "task"
    return "remote-task"


def _verified_line(store: core.Store, env: dict) -> str:
    method = env["from_auth"]["method"]
    if method in UNVERIFIED_METHODS:
        return f"UNVERIFIED {method}"
    _name, site = core.split_qualified(env["from"])
    via = f"local/{store.site}" if site == store.site else f"peer/{site}"
    return f"VERIFIED {env['from']} {method} via {via}"


GAP_RANGES_MAX = 20


def _gaps(store: core.Store, name: str) -> list:
    """Missing seqs per sender across new|cur|done (§6: shown, blocks nothing),
    as `[first, last]` ranges: cost is O(messages), never O(max seq). At most
    GAP_RANGES_MAX ranges per sender are kept."""
    seqs: dict = {}
    for state in ("new", "cur", "done"):
        for msg_id in core.list_spool(store, name, state):
            env = _load(store, name, state, msg_id)
            if env is not None:
                seqs.setdefault(env["from"], set()).add(env["seq"])
    out = []
    for sender in sorted(seqs):
        missing, prev = [], 0
        for seq in sorted(seqs[sender]):
            if seq > prev + 1:
                missing.append([prev + 1, seq - 1])
                if len(missing) >= GAP_RANGES_MAX:
                    break
            prev = seq
        if missing:
            out.append((sender, missing))
    return out


def _range_text(span: list) -> str:
    return str(span[0]) if span[0] == span[1] else f"{span[0]}-{span[1]}"


# --- verbs ------------------------------------------------------------------

def cmd_init(prims: MsgPrims, args, out) -> int:
    label = args.site
    if not core.valid_name(label):
        raise MsgError(f"bad site label {label!r}: use {core.NAME_RE.pattern}")
    current = read_site(prims.fleet_home)
    if current is not None:
        if current != label:
            raise MsgError(f"site is already {current!r}; a label is never changed")
        print(f"SITE {label} (unchanged)", file=out)
        return 0
    own = Path(prims.fleet_home).resolve()
    for member in prims.homes():
        other = Path(member)
        try:
            if other.resolve() == own:
                continue
            used = read_site(other)
        except (OSError, MsgError):
            continue                     # an unreadable peer label is not a clash
        if used == label:
            raise MsgError(f"site label {label!r} is used by listed home {other}")
    store = core.Store(prims.fleet_home, label, clock=prims.clock, sleep=prims.sleep)
    store._ensure_dir(store.root)
    if not store._write_new(store.root / "tmp", store.root / "site.json",
                            core.canonical({"site": label}), "site"):
        return cmd_init(prims, args, out)      # lost a race; re-read and compare
    store.ledger("init", site=label)
    print(f"SITE {label}", file=out)
    return 0


def _read_body(text: str) -> str:
    cap = core.BODY_MAX_BYTES + 1            # one byte over: make_draft refuses it
    if text == "-":
        return sys.stdin.buffer.read(cap).decode("utf-8", errors="replace")
    if text.startswith("@"):
        try:
            with open(text[1:], "rb") as handle:
                return handle.read(cap).decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise MsgError(f"cannot read {text[1:]}: {type(exc).__name__}") from None
    return text


def cmd_send(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    proofs = caller_proofs(prims, args.nonce)
    if args.sender:
        if not core.valid_name(args.sender):
            raise MsgError(f"bad --from name {args.sender!r}")
        proof = _proof_for(proofs, args.sender) or (args.sender, "unverified", None)
    elif proofs:
        proof = proofs[0]
    else:
        raise MsgError("cannot resolve the caller's identity; pass --from NAME "
                       "(the message is then stamped unverified)")
    frm, method, detail = proof
    if args.kind == "task" and frm == SUPERVISOR and method != "supervisor-nonce":
        raise MsgError("refused: a task from the supervisor needs --nonce")
    if "@" in args.to:
        to_name, to_site = core.split_qualified(args.to)
    else:
        to_name, to_site = args.to, store.site
        if not core.valid_name(to_name):
            raise MsgError(f"bad identity name {to_name!r}")
    if to_site == store.site:
        ident = resolve(prims, store, to_name)
        if ident is None:
            raise MsgError(f"unknown identity {to_name!r} on site {store.site!r}")
        if ident["retired"]:
            raise MsgError(f"rejected: retired ({to_name!r} is an archived lane)")
    elif to_site not in _peers(store):
        raise MsgError(f"unknown site {to_site!r}: not in peers.json")
    parent = None
    if args.re:
        found = _find(store, args.re) if core.ID_RE.fullmatch(args.re) else None
        if found is None:
            raise MsgError(f"--re {args.re}: no such message in this home")
        parent = found[1]
    try:
        draft = core.make_draft(
            f"{frm}@{store.site}", f"{to_name}@{to_site}", _read_body(args.text),
            from_auth={"method": method, "detail": detail},
            sent_at=core.iso_utc(prims.clock()), kind=args.kind,
            needs_answer=bool(args.needs_answer), parent=parent)
        status, env = core.enqueue(store, draft)
    except core.EnvelopeError as exc:
        raise MsgError(f"refused: {exc.reason}: {exc}") from None
    except core.Refused as exc:
        raise MsgError(f"refused: {exc}") from None
    seq = env["seq"] if env else "?"
    print(f"{status.upper()} {draft['id']} seq {seq} from {frm} ({method})", file=out)
    return 0


def _entry(store: core.Store, env: dict, state: str, reader=None) -> dict:
    return {"id": env["id"], "state": state, "from": env["from"], "to": env["to"],
            "kind": env["kind"], "shown_as": direction(store, env), "seq": env["seq"],
            "method": env["from_auth"]["method"], "verified": _verified_line(store, env),
            "sent_at": env["sent_at"], "needs_answer": env["needs_answer"],
            "re": env["re"], "thread": env["thread"], "body": env["body"],
            "reader": reader}


def cmd_inbox(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    name = args.name or _default_name(prims)
    if not core.valid_name(name) or resolve(prims, store, name) is None:
        raise MsgError(f"unknown identity {name!r}")
    if args.wait is not None and not (math.isfinite(args.wait) and args.wait >= 0):
        raise MsgError("--wait must be a finite number of seconds >= 0")
    proof = None if args.peek else _require_holder(prims, name)
    if args.wait is not None:
        deadline = prims.clock() + args.wait
        while not core.list_spool(store, name, "new"):
            if prims.clock() >= deadline:
                print("TIMEOUT", file=out)
                return EXIT_TIMEOUT
            prims.sleep(WAIT_POLL_S)
    states = ("new", "cur") if args.all else ("new",)
    readers = _readers(store) if args.all else {}
    entries, corrupt = [], []
    for state in states:
        for msg_id in core.list_spool(store, name, state):
            env = _load(store, name, state, msg_id)
            if env is not None:
                entries.append(_entry(store, env, state, readers.get(msg_id)))
            else:
                corrupt.append(f"{state}/{msg_id}")
    entries.sort(key=lambda e: (e["from"], e["seq"], e["id"]))
    if proof is not None:
        reader = f"{proof[1]}/{_reader_body(prims)}"
        for entry in entries:
            if entry["state"] == "new" and core.move(store, name, entry["id"], "new", "cur",
                                                     reader=reader):
                entry["reader"] = reader
    gaps = _gaps(store, name)
    if args.json:
        print(json.dumps({"identity": f"{name}@{store.site}", "messages": entries,
                          "gaps": [{"from": s, "missing": m} for s, m in gaps],
                          "corrupt": corrupt},
                         sort_keys=True), file=out)
        return 0
    if not entries and not corrupt:
        print(f"EMPTY {name}@{store.site}", file=out)
    for item in corrupt:
        print(f"CORRUPT {item} (unreadable envelope; queue counts it)", file=out)
    for entry in entries:
        flags = " needs-answer" if entry["needs_answer"] else ""
        flags += f" re={entry['re']}" if entry["re"] else ""
        print(f"MSG {entry['id']} [{entry['state']}] seq={entry['seq']} "
              f"kind={entry['shown_as']} from={entry['from']} sent={entry['sent_at']}{flags}",
              file=out)
        print(entry["verified"], file=out)
        print(entry["body"], file=out)
        if entry["state"] == "cur" and entry["reader"]:
            print(f"READ BY {entry['reader']}", file=out)
        print("", file=out)
    for sender, missing in gaps:
        print(f"GAP from {sender}: seq {','.join(map(_range_text, missing))} missing", file=out)
    return 0


def cmd_ack(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    proofs = caller_proofs(prims)
    if not proofs:
        raise MsgError("refused: the caller holds no identity")
    failed = 0
    for msg_id in args.ids:
        if not core.ID_RE.fullmatch(msg_id):
            print(f"NOT-FOUND {msg_id}", file=out)
            failed += 1
            continue
        done = False
        for name, method, _detail in proofs:
            reader = f"{method}/{_reader_body(prims)}"
            core.move(store, name, msg_id, "new", "cur", reader=reader)
            if core.move(store, name, msg_id, "cur", "done", reader=reader):
                print(f"ACKED {msg_id} {name}@{store.site}", file=out)
                done = True
                break
        if not done:
            print(f"NOT-FOUND {msg_id} (not unacked in a queue the caller holds)", file=out)
            failed += 1
    return 1 if failed else 0


def cmd_status(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    if not core.ID_RE.fullmatch(args.id):
        raise MsgError(f"bad message id {args.id!r}")
    found = _find(store, args.id)
    events = [r for r in _ledger(store) if r.get("id") == args.id]
    if found is None and not events:
        print(f"UNKNOWN {args.id}", file=out)
        return 1
    if found is not None:
        where, env = found
        print(f"STATUS {args.id} {where} from={env['from']} to={env['to']} "
              f"kind={env['kind']} seq={env['seq']} method={env['from_auth']['method']}",
              file=out)
    else:
        print(f"STATUS {args.id} not stored", file=out)
    for record in events:
        extra = f" reader={record['reader']}" if record.get("reader") else ""
        extra += f" reason={record['reason']}" if record.get("reason") else ""
        print(f"  {record.get('ts')} {record.get('event')}{extra}", file=out)
    return 0


def _age(path: Path, now: float) -> "float | None":
    try:
        return max(0.0, now - os.lstat(path).st_mtime)
    except FileNotFoundError:
        return None


def cmd_queue(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    now = prims.clock()
    warn_s = _config(store).get("outbox_warn_s", OUTBOX_WARN_S)
    rows = []
    for name in _spool_names(store):
        new, cur = core.list_spool(store, name, "new"), core.list_spool(store, name, "cur")
        needs, ages = 0, []
        for state, ids in (("new", new), ("cur", cur)):
            for msg_id in ids:
                env = _load(store, name, state, msg_id)
                needs += bool(env and env["needs_answer"])
                age = _age(store.spool(name, state) / f"{msg_id}.json", now)
                if age is not None:
                    ages.append(age)
        rows.append({"identity": f"{name}@{store.site}", "unread": len(new),
                     "unacked": len(cur), "needs_answer": needs,
                     "oldest_s": int(max(ages)) if ages else None})
    peers = []
    try:
        sites = sorted(os.listdir(store.root / "outbox"))
    except FileNotFoundError:
        sites = []
    for site in sites:
        if not core.valid_name(site):
            continue
        entries = core.outbox_entries(store, site)
        ages = [a for a in (_age(p, now) for p in sorted(store.outbox(site, "q").glob("*.json")))
                if a is not None]
        oldest = int(max(ages)) if ages else None
        peers.append({"site": site, "depth": len(entries), "oldest_s": oldest,
                      "warn": oldest is not None and oldest > warn_s})
    if args.json:
        print(json.dumps({"site": store.site, "identities": rows, "outbox": peers},
                         sort_keys=True), file=out)
        return 0
    print(f"SITE {store.site}", file=out)
    for row in rows:
        print(f"{row['identity']} unread={row['unread']} unacked={row['unacked']} "
              f"needs-answer={row['needs_answer']} oldest={row['oldest_s']}s", file=out)
    for peer in peers:
        warn = f" WARN older than {warn_s}s" if peer["warn"] else ""
        print(f"outbox {peer['site']} depth={peer['depth']} oldest={peer['oldest_s']}s{warn}",
              file=out)
    return 0


def _ident_line(store: core.Store, ident: dict) -> str:
    retired = " RETIRED" if ident["retired"] else ""
    return (f"{ident['name']}@{store.site} {ident['kind']} "
            f"holder={ident['holder'] or '-'}{retired}")


def cmd_whois(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    ident = resolve(prims, store, args.name) if core.valid_name(args.name) else None
    if ident is None:
        print(f"UNKNOWN {args.name}", file=out)
        return 1
    print(_ident_line(store, ident), file=out)
    return 0


def cmd_ids(prims: MsgPrims, args, out) -> int:
    store = open_store(prims)
    names = [SUPERVISOR, INTERFACE]
    workers = prims.workers() or {}
    if isinstance(workers, dict):
        names += sorted(n for n in workers if isinstance(n, str) and core.valid_name(n)
                        and n not in names and not prims.is_supervisor_shaped(n))
    try:
        names += sorted(p.name[:-5] for p in (store.root / "ids").glob("*.json")
                        if core.valid_name(p.name[:-5]) and p.name[:-5] not in names)
    except OSError:
        pass
    for name in names:
        ident = resolve(prims, store, name)
        if ident is not None:
            print(_ident_line(store, ident), file=out)
    return 0


VERBS = {"init": cmd_init, "send": cmd_send, "inbox": cmd_inbox, "ack": cmd_ack,
         "status": cmd_status, "queue": cmd_queue, "ids": cmd_ids, "whois": cmd_whois}


def run(args, prims: MsgPrims, out=None) -> int:
    """Dispatch one `fleet msg` verb. A refusal prints one line and exits 1."""
    out = sys.stdout if out is None else out
    try:
        return VERBS[args.msg_command](prims, args, out)
    except MsgError as exc:
        print(f"fleet msg {args.msg_command}: {exc}", file=sys.stderr)
        return exc.code
    except core.StoreError as exc:
        print(f"fleet msg {args.msg_command}: store error: {exc}", file=sys.stderr)
        return 1
