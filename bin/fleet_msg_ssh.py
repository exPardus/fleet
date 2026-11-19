"""ssh transport: two machines, one dials (docs/specs/messaging.md §7.2).

The reachable machine runs `fleet --fleet-home H msg serve --peer SITE` as the
forced command of the client's key; the client runs `msg sync --peer SERVER`,
which dials with `ssh` and speaks length-prefixed frames on the pipe.

Frame: one header line `{"len":N,"op":OP,"sha256":HEX}` then exactly N bytes.
Ops: `hello`, `push`, `result`, `pull`, `batch`, `commit`, `bye`. Payloads are
JSON; envelope bytes ride base64 inside it, so the canonical bytes (and their
`body_sha256`) arrive untouched. Any short, oversized, non-canonical or
checksum-failing frame ends the session with `FrameError`; nothing of a frame
is acted on before it is complete and verified.

Session: `hello` both ways, `push` client outbox, `result` per id, `pull`,
`batch`, client publishes, `commit(ids)` (answered by a `result`), `bye`.
The server takes the client's site from `--peer`, never from the client, and
refuses a `hello` that names another site. A push that carries an id the
server cannot ingest never blocks the rest: each id has its own result.

Doctrine: stdlib only, Python 3.10. Never imports `fleet.py` or `fleet_lock`,
takes no `fleet.lock`, writes no registry, unlinks no message. Fleet helpers
(`ingest` with its admit/notify, `hosted`) arrive as injected callables.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

import fleet_msg_core as core
import fleet_msg_fs as fsx
import fleet_msg_transport as transport

OPS = ("hello", "push", "result", "pull", "batch", "commit", "bye")
HEADER_MAX = 256
FRAME_MAX = 8 * 1024 * 1024            # one frame; 64 base64 envelopes fit with room
BATCH_MAX_ENTRIES = 64                 # per push or batch; the rest waits for the next session
SESSION_TIMEOUT_S = 120.0
DEFAULT_MAX_FAILURES = 5
CONNECT_TIMEOUT_S = 15
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:\[\]-]{0,252}$")
_HEADER_KEYS = {"op", "len", "sha256"}


class FrameError(transport.TransportError):
    """A frame is short, oversized, malformed or fails its checksum."""


# --- frame codec ---------------------------------------------------------------

def encode_frame(op: str, payload: bytes = b"") -> bytes:
    if op not in OPS:
        raise FrameError(f"unknown op {op!r}")
    if len(payload) > FRAME_MAX:
        raise FrameError("frame payload too large")
    header = json.dumps({"op": op, "len": len(payload),
                         "sha256": hashlib.sha256(payload).hexdigest()},
                        sort_keys=True, separators=(",", ":"))
    return header.encode("ascii") + b"\n" + payload


def write_frame(stream: BinaryIO, op: str, payload: bytes = b"") -> None:
    try:
        stream.write(encode_frame(op, payload))
        stream.flush()
    except (OSError, ValueError) as exc:
        raise FrameError(f"cannot write {op} frame: {exc}") from None


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks, left = [], size
    while left:
        chunk = stream.read(left)
        if not chunk:
            raise FrameError("peer closed mid-frame")
        chunks.append(chunk)
        left -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO, expect: Iterable[str] | None = None) -> tuple[str, bytes]:
    """The next whole, verified frame. `expect` names the ops allowed here."""
    try:
        line = stream.readline(HEADER_MAX + 1)
    except (OSError, ValueError) as exc:
        raise FrameError(f"cannot read frame header: {exc}") from None
    if not line:
        raise FrameError("peer closed before a frame")
    if len(line) > HEADER_MAX or not line.endswith(b"\n"):
        raise FrameError("bad frame header")
    try:
        header = json.loads(line.decode("ascii"))
    except (ValueError, UnicodeError):
        raise FrameError("frame header is not JSON") from None
    if type(header) is not dict or set(header) != _HEADER_KEYS:
        raise FrameError("frame header keys")
    op, size, digest = header["op"], header["len"], header["sha256"]
    if op not in OPS or type(size) is not int or isinstance(size, bool) \
            or not 0 <= size <= FRAME_MAX or type(digest) is not str:
        raise FrameError("frame header values")
    if expect is not None and op not in tuple(expect):
        raise FrameError(f"unexpected {op} frame")
    payload = _read_exact(stream, size)
    if hashlib.sha256(payload).hexdigest() != digest:
        raise FrameError("frame checksum mismatch")
    return op, payload


def _id_of(raw: bytes) -> str | None:
    """The id of an envelope: parsed when it parses, else sniffed (so a peer
    can still reject and commit an envelope it cannot parse)."""
    try:
        return core.parse(raw)["id"]
    except core.EnvelopeError:
        return core._sniff_id(raw)


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def loads(payload: bytes, what: str):
    try:
        return json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise FrameError(f"{what} payload is not JSON") from None


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text, what: str) -> bytes:
    if type(text) is not str:
        raise FrameError(f"{what}: not a string")
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        raise FrameError(f"{what}: bad base64") from None


def _ids(value, what: str) -> list:
    if type(value) is not list or len(value) > BATCH_MAX_ENTRIES * 4 \
            or not all(type(i) is str and core.ID_RE.fullmatch(i) for i in value):
        raise FrameError(f"{what}: bad id list")
    return value


def _object(payload: bytes, keys: set, what: str) -> dict:
    data = loads(payload, what)
    if type(data) is not dict or set(data) != keys:
        raise FrameError(f"{what}: expected exactly {sorted(keys)}")
    return data


# --- client ---------------------------------------------------------------------

def ssh_argv(peer: dict) -> list:
    """`ssh -p PORT ALIAS fleet --fleet-home HOME msg serve` from a `peers.json`
    entry (`alias`, `port`, `home`; optional `fleet`, default `fleet`). The
    server's forced command ignores the remote words and adds `--peer`."""
    alias, port, home = peer.get("alias"), peer.get("port"), peer.get("home")
    if not (isinstance(alias, str) and _ALIAS_RE.fullmatch(alias)):
        raise transport.TransportError("ssh peer needs a plain \"alias\" in peers.json")
    if type(port) is not int or not 1 <= port <= 65535:
        raise transport.TransportError("ssh peer needs an integer \"port\" in peers.json")
    if not (isinstance(home, str) and home and not home.startswith("-")
            and "\0" not in home and "\n" not in home):
        raise transport.TransportError("ssh peer needs the server \"home\" in peers.json")
    binary = peer.get("fleet", "fleet")
    if not (isinstance(binary, str) and binary and not binary.startswith("-")):
        raise transport.TransportError("ssh peer \"fleet\" is not a command name")
    return ["ssh", "-p", str(port), "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={CONNECT_TIMEOUT_S}", "--", alias,
            binary, "--fleet-home", home, "msg", "serve"]


class SshTransport:
    """The client end: one session over a spawned `ssh` (or a test pipe).

    `argv` is the command to run; `spawn` defaults to `subprocess.Popen` and
    returns an object with binary `stdin` and `stdout`. A watchdog kills a
    session that outlives `timeout`. `warnings` collects `hello` skew notes.
    """

    def __init__(self, store: core.Store, peer_site: str, argv: list, *,
                 spawn: Callable = subprocess.Popen, timeout: float = SESSION_TIMEOUT_S):
        if not core.valid_name(peer_site):
            raise transport.TransportError(f"bad peer site label {peer_site!r}")
        if peer_site == store.site:
            raise transport.TransportError("peer uses the local site label")
        self.store = store
        self.peer_site = peer_site
        self.argv = list(argv)
        self.spawn = spawn
        self.timeout = timeout
        self.warnings: list[str] = []
        self.more = False
        self._proc = None
        self._timer = None
        self._ids: dict[int, str] = {}
        self._pulled: dict[str, bytes] = {}
        self._receipts = None

    # --- session plumbing ------------------------------------------------------

    def _open(self) -> None:
        if self._proc is not None:
            return
        try:
            self._proc = self.spawn(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        except OSError as exc:
            raise transport.TransportError(f"cannot start ssh: {exc}") from None
        self._timer = threading.Timer(self.timeout, self._kill)
        self._timer.daemon = True
        self._timer.start()

    def _kill(self) -> None:
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except (OSError, AttributeError):
                pass

    def _send(self, op: str, payload: bytes = b"") -> None:
        self._open()
        write_frame(self._proc.stdin, op, payload)

    def _recv(self, *expect: str) -> bytes:
        self._open()
        return read_frame(self._proc.stdout, expect)[1]

    # --- Transport ---------------------------------------------------------------

    def hello(self, local: transport.SiteInfo) -> transport.SiteInfo:
        self._send("hello", dumps(local.to_json()))
        remote = transport.SiteInfo.from_json(loads(self._recv("hello"), "hello"))
        if remote.site != self.peer_site:
            raise transport.TransportError(
                f"peer labels itself {remote.site!r}, expected {self.peer_site!r}")
        self.warnings = transport.check_hello(local, remote, self.store.clock())
        return remote

    def push(self, envelopes: list[bytes]) -> dict[str, str]:
        """Send up to BATCH_MAX_ENTRIES envelopes; ids without a result stay
        queued. An envelope that does not parse is not sent."""
        items, sent = [], []
        for raw in envelopes[:BATCH_MAX_ENTRIES]:
            msg_id = _id_of(raw)
            if msg_id is None:
                continue
            items.append({"id": msg_id, "raw": _b64(raw)})
            sent.append(msg_id)
        if not items:
            return {}
        self._send("push", dumps({"items": items}))
        data = _object(self._recv("result"), {"results"}, "result")
        results = data["results"]
        if type(results) is not dict:
            raise FrameError("result: not an object")
        out = {}
        for msg_id, value in results.items():
            if msg_id not in sent:
                raise FrameError("result names an id that was not pushed")
            transport.parse_push_result(value)          # raises on a bad value
            out[msg_id] = value
        return out

    def pull(self, hint_qseq: int) -> list[tuple[int, bytes]]:
        self._send("pull", dumps({"hint": int(hint_qseq)}))
        data = _object(self._recv("batch"), {"items", "more"}, "batch")
        items = data["items"]
        if type(items) is not list or len(items) > BATCH_MAX_ENTRIES or type(data["more"]) is not bool:
            raise FrameError("batch: bad shape")
        self.more = data["more"]
        out, self._ids, self._pulled = [], {}, {}
        for item in items:
            if type(item) is not dict or set(item) != {"qseq", "id", "raw"} \
                    or type(item["qseq"]) is not int or isinstance(item["qseq"], bool) \
                    or type(item["id"]) is not str or not core.ID_RE.fullmatch(item["id"]):
                raise FrameError("batch: bad entry")
            raw = _unb64(item["raw"], "batch entry")
            self._ids[item["qseq"]] = item["id"]
            self._pulled[item["id"]] = raw
            out.append((item["qseq"], raw))
        out.sort(key=lambda pair: pair[0])
        return out

    def entry_id(self, qseq: int) -> str | None:
        return self._ids.get(qseq)

    def commit(self, ids: list[str]) -> None:
        """Receipt each pulled envelope locally, settle the local envelope a
        pulled receipt answers, then tell the server exactly these ids were
        published. The server's `result` must follow."""
        ids = _ids(list(ids), "commit")
        answered = []
        shim = fsx.FsTransport(self.store, self.store.home, self.peer_site,
                               _NoHosts())   # only `_emit_receipt`, which reads none of its paths
        try:
            for msg_id in ids:
                raw = self._pulled.get(msg_id)
                if raw is None:
                    continue
                try:
                    env = core.parse(raw)
                except core.EnvelopeError:
                    continue
                if env["id"] != msg_id:
                    continue
                if env["kind"] == "receipt":
                    answered.append(env["re"])
                else:
                    shim._emit_receipt(env)
            if answered:
                core.outbox_commit(self.store, self.peer_site, answered)
        except core.StoreError as exc:
            raise transport.TransportError(str(exc)) from None
        self._send("commit", dumps({"ids": ids}))
        data = _object(self._recv("result"), {"committed"}, "commit result")
        _ids(data["committed"], "commit result")

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if self._timer is not None:
            self._timer.cancel()
        if proc is None:
            return
        try:
            try:
                write_frame(proc.stdin, "bye")
            except transport.TransportError:
                pass
            for stream in (proc.stdin, proc.stdout):
                try:
                    stream.close()
                except (OSError, ValueError, AttributeError):
                    pass
            try:
                proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, AttributeError):
                proc.kill()
                proc.wait()
        except OSError:
            pass


class _NoHosts:
    def hosted(self, home: Path):
        return ()


# --- server ---------------------------------------------------------------------

def serve_session(store: core.Store, peer_site: str, rfile: BinaryIO, wfile: BinaryIO, *,
                  local: transport.SiteInfo, ingest: Callable[[bytes, tuple], str],
                  after_ingest: Callable[[bytes], None] | None = None) -> dict:
    """The server end of one session, for the client pinned as `peer_site`.

    `ingest(raw, hosted)` is the §7 receiver path (`core.ingest` with the
    caller's admit and notify); `after_ingest(raw)` emits the receipt for a
    pushed envelope. Returns counts. Raises `TransportError` (a `FrameError`
    included) when the session must end non-zero.
    """
    if not core.valid_name(peer_site):
        raise transport.TransportError("serve needs a valid --peer site label")
    remote = transport.SiteInfo.from_json(loads(read_frame(rfile, ("hello",))[1], "hello"))
    if remote.site != peer_site:
        raise transport.TransportError(
            f"client says it is {remote.site!r}; this key is pinned to {peer_site!r}")
    warnings = transport.check_hello(local, remote, store.clock())
    write_frame(wfile, "hello", dumps(local.to_json()))
    counts = {"pushed": 0, "served": 0, "committed": 0, "warnings": warnings}
    served: dict[str, int] = {}
    while True:
        op, payload = read_frame(rfile, ("push", "pull", "commit", "bye"))
        if op == "bye":
            return counts
        if op == "push":
            data = _object(payload, {"items"}, "push")
            items = data["items"]
            if type(items) is not list or len(items) > BATCH_MAX_ENTRIES:
                raise FrameError("push: bad items")
            results = {}
            for item in items:
                if type(item) is not dict or set(item) != {"id", "raw"} \
                        or type(item["id"]) is not str or not core.ID_RE.fullmatch(item["id"]):
                    raise FrameError("push: bad item")
                raw = _unb64(item["raw"], "push item")
                results[item["id"]] = _ingest_one(item["id"], raw, remote.hosted, ingest,
                                                  after_ingest)
            counts["pushed"] += len(results)
            write_frame(wfile, "result", dumps({"results": results}))
        elif op == "pull":
            _object(payload, {"hint"}, "pull")      # advisory only; never filters
            entries = core.outbox_entries(store, peer_site)
            items, more = [], False
            for qseq, raw in entries:
                msg_id = _id_of(raw)
                if msg_id is None:
                    continue                        # unsendable local file: stays, visible as queue age
                if len(items) >= BATCH_MAX_ENTRIES:
                    more = True
                    break
                items.append({"qseq": qseq, "id": msg_id, "raw": _b64(raw)})
                served[msg_id] = qseq
            counts["served"] += len(items)
            write_frame(wfile, "batch", dumps({"items": items, "more": more}))
        else:                                       # commit
            ids = _ids(_object(payload, {"ids"}, "commit")["ids"], "commit")
            # Only ids this session served: a replayed or forged commit moves nothing.
            wanted = [i for i in ids if i in served]
            try:
                moved = core.outbox_commit(store, peer_site, wanted) if wanted else []
            except core.StoreError as exc:
                raise transport.TransportError(str(exc)) from None
            counts["committed"] += len(moved)
            write_frame(wfile, "result", dumps({"committed": moved}))


def _ingest_one(msg_id: str, raw: bytes, hosted, ingest, after_ingest) -> str:
    try:
        parsed = core.parse(raw)
    except core.EnvelopeError:
        parsed = None
    if parsed is not None and parsed["id"] != msg_id:
        return transport.rejected("corrupt")       # the pushed id is not the envelope's own
    result = ingest(raw, tuple(hosted))
    if parsed is not None and parsed["kind"] != "receipt" and after_ingest is not None:
        after_ingest(raw)
    transport.parse_push_result(result)
    return result


def make_receipter(store: core.Store, peer_site: str) -> Callable[[bytes], None]:
    """`after_ingest` for `serve_session`: the same receipt `fs` writes on
    `commit` (docs/specs/messaging.md §7.1.1), derived ids, so a re-push finds it."""
    shim = fsx.FsTransport(store, store.home, peer_site, _NoHosts())

    def emit(raw: bytes) -> None:
        try:
            env = core.parse(raw)
        except core.EnvelopeError:
            return
        shim._emit_receipt(env)
    return emit


# --- client failure counter (exit 4) ----------------------------------------------

def _fail_path(store: core.Store, site: str) -> Path:
    return store.root / "ssh-fails" / site


def failures(store: core.Store, site: str) -> int:
    try:
        text = _fail_path(store, site).read_text(encoding="ascii")
        return int(text) if re.fullmatch(r"[0-9]{1,9}\n?", text) else 0
    except (OSError, ValueError):
        return 0


def record_failure(store: core.Store, site: str) -> int:
    with store.locked("outbox", site):
        return store._counter_next(_fail_path(store, site))


def record_success(store: core.Store, site: str) -> None:
    path = _fail_path(store, site)
    if failures(store, site) == 0 and not path.exists():
        return
    with store.locked("outbox", site):
        tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
        tmp.write_text("0\n", encoding="ascii")
        os.replace(str(tmp), str(path))       # the failure counter only, never a message


def max_failures(peer: dict) -> int:
    value = peer.get("max_failures", DEFAULT_MAX_FAILURES)
    return value if type(value) is int and value >= 1 else DEFAULT_MAX_FAILURES
