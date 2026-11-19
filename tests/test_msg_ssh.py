"""ssh transport on a pipe (docs/specs/messaging.md §7.2; plan PR 7, T15, T15b-e).

`ssh` is replaced by `python bin/fleet.py --fleet-home B msg serve --peer a`;
a wrapper drops, corrupts, duplicates and replays bytes between the two ends.
"""
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import fleet
import fleet_msg
import fleet_msg_core as core
import fleet_msg_ssh as sshx
import fleet_msg_transport as transport

BIN = Path(__file__).resolve().parents[1] / "bin"
FLEET_PY = str(BIN / "fleet.py")


def _iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lane(sid):
    return {"session_id": sid, "dispatch_kind": "bg", "cwd": "/w", "created": _iso()}


def registry(h, workers):
    (h / "state" / "fleet.json").write_text(json.dumps({"workers": workers}), encoding="utf-8")


def msg(h, *argv):
    return fleet.main(["--fleet-home", str(h), "msg", *argv])


def spool(h, name, state):
    d = h / "state" / "msg" / "spool" / name / state
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def outbox(h, site, state):
    d = h / "state" / "msg" / "outbox" / site / state
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


def enqueue(h, site, frm, to, body="hi", **over):
    store = core.Store(h, site)
    draft = core.make_draft(frm, to, body, from_auth={"method": "lane-registry", "detail": "t"},
                            sent_at=core.iso_utc(time.time()), **over)
    return core.enqueue(store, draft)[1]


def server_argv(home, peer):
    return [sys.executable, FLEET_PY, "--fleet-home", str(home), "msg", "serve", "--peer", peer]


class Pipe:
    """A Popen-like to the real `msg serve` process, with byte faults.

    `up(data) -> bytes` rewrites client->server bytes, `down(data)` the other
    way; `rec` collects the client->server bytes (for a replay).
    """

    def __init__(self, argv, up=None, down=None, rec=None, env=None):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env or _env())
        self.up_fn, self.down_fn, self.rec = up, down, rec
        self.stdin = self
        self.stdout = io.BufferedReader(_Down(self))
        self._closed = False

    # stdin side
    def write(self, data):
        if self.rec is not None:
            self.rec.append(bytes(data))
        out = self.up_fn(bytes(data)) if self.up_fn else bytes(data)
        if out and not self._closed:
            try:
                self.proc.stdin.write(out)
                self.proc.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
        if len(out) < len(data):
            self.close()                    # the link dropped: the server sees EOF

    def flush(self):
        try:
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass

    def close(self):
        self._closed = True
        try:
            self.proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    def kill(self):
        self.proc.kill()

    def wait(self, timeout=None):
        rc = self.proc.wait(timeout=timeout)
        self.proc.stdout.close()
        self.stderr_text = self.proc.stderr.read().decode()
        self.proc.stderr.close()
        return rc


class _Down(io.RawIOBase):
    def __init__(self, pipe):
        self.pipe = pipe

    def readable(self):
        return True

    def readinto(self, buf):
        data = self.pipe.proc.stdout.read1(len(buf)) if hasattr(self.pipe.proc.stdout, "read1") \
            else self.pipe.proc.stdout.read(len(buf))
        if data and self.pipe.down_fn:
            data = self.pipe.down_fn(data)
        buf[:len(data)] = data
        return len(data)


def _env():
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    return env


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Home A (site alpha, the client) and home B (site beta, the server)."""
    homes = {}
    for key, site in (("a", "alpha"), ("b", "beta")):
        h = tmp_path / site
        (h / "state").mkdir(parents=True)
        (h / "supervisor").mkdir()
        homes[key] = h
    monkeypatch.setattr(fleet, "FLEET_HOME", homes["a"])
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "MCX_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    registry(homes["a"], {"lane-a": _lane("sid-a"), "lane-b": _lane("sid-b")})
    registry(homes["b"], {"lane-x": _lane("sid-x")})
    assert msg(homes["a"], "init", "--site", "alpha") == 0
    assert msg(homes["b"], "init", "--site", "beta") == 0
    a, b = homes["a"], homes["b"]
    (a / "state/msg/peers.json").write_text(json.dumps({"beta": {
        "transport": "ssh", "alias": "beta-host", "port": 2222, "home": str(b),
        "max_failures": 2}}))
    (b / "state/msg/peers.json").write_text(json.dumps({"alpha": {"transport": "ssh"}}))
    pipes = []

    def connect(up=None, down=None, rec=None):
        def spawn(argv, **kw):
            pipe = Pipe(server_argv(b, "alpha"), up=up, down=down, rec=rec)
            pipes.append(pipe)
            return pipe
        monkeypatch.setattr(fleet_msg, "_ssh_spawn", spawn)
    connect()
    return a, b, connect, pipes


def sync(a, capsys):
    capsys.readouterr()
    rc = msg(a, "sync", "--peer", "beta")
    return rc, capsys.readouterr().out


def no_torn(h):
    """No half-written file is visible in any spool, outbox or seen dir."""
    root = h / "state" / "msg"
    for path in root.rglob("*.json"):
        if "tmp" in path.parts:
            continue
        json.loads(path.read_text())


# --- frame codec ---------------------------------------------------------------

def _stream(data):
    return io.BytesIO(data)


def test_frame_roundtrip_and_strictness():
    data = sshx.encode_frame("push", b'{"items":[]}')
    assert sshx.read_frame(_stream(data)) == ("push", b'{"items":[]}')
    assert sshx.read_frame(_stream(sshx.encode_frame("bye"))) == ("bye", b"")
    with pytest.raises(sshx.FrameError):
        sshx.read_frame(_stream(data), expect=("pull",))                 # wrong op here
    with pytest.raises(sshx.FrameError, match="mid-frame"):
        sshx.read_frame(_stream(data[:-3]))                              # short payload
    with pytest.raises(sshx.FrameError, match="checksum"):
        sshx.read_frame(_stream(data[:-1] + b"X"))                       # corrupt byte
    with pytest.raises(sshx.FrameError):
        sshx.read_frame(_stream(b""))
    big = json.dumps({"op": "push", "len": sshx.FRAME_MAX + 1, "sha256": "0" * 64}).encode() + b"\n"
    with pytest.raises(sshx.FrameError, match="values"):
        sshx.read_frame(_stream(big))                                    # oversized, refused before reading
    extra = json.dumps({"op": "push", "len": 0, "sha256": "0" * 64, "x": 1}).encode() + b"\n"
    with pytest.raises(sshx.FrameError, match="keys"):
        sshx.read_frame(_stream(extra))
    with pytest.raises(sshx.FrameError):
        sshx.read_frame(_stream(b"x" * 1000))                            # no newline in header bound
    bad = json.dumps({"op": "evil", "len": 0, "sha256": "0" * 64}).encode() + b"\n"
    with pytest.raises(sshx.FrameError):
        sshx.read_frame(_stream(bad))
    boolean = json.dumps({"op": "push", "len": True, "sha256": "0" * 64}).encode() + b"\n"
    with pytest.raises(sshx.FrameError):
        sshx.read_frame(_stream(boolean))


def test_ssh_argv_validates_the_peer_entry():
    peer = {"alias": "beta-host", "port": 2222, "home": "/srv/fleet"}
    argv = sshx.ssh_argv(peer)
    assert argv[:3] == ["ssh", "-p", "2222"]
    assert argv[-5:] == ["fleet", "--fleet-home", "/srv/fleet", "msg", "serve"]
    assert "--fleet-home" in argv and "--" in argv
    for bad in ({**peer, "alias": "-oProxyCommand=x"}, {**peer, "port": "22"},
                {**peer, "port": 0}, {**peer, "home": "-x"}, {**peer, "home": ""},
                {k: v for k, v in peer.items() if k != "alias"}):
        with pytest.raises(transport.TransportError):
            sshx.ssh_argv(bad)


# --- T15: sessions on a pipe -----------------------------------------------------

def test_t15_both_directions_deliver_once_with_receipts(two, monkeypatch, capsys):
    a, b, _connect, _pipes = two
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "send", "supervisor@beta", "to the server") == 0
    out_id = capsys.readouterr().out.split()[1]
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "to the client")
    rc, out = sync(a, capsys)
    assert rc == 0 and "SYNC beta pulled=2 accepted=2" in out
    assert [json.loads((b / "state/msg/spool/supervisor/new" / f"{out_id}.json").read_text())["body"]] \
        == ["to the server"]
    assert len(outbox(a, "beta", "sent")) == 1             # settled by the push result
    assert len(outbox(a, "beta", "q")) == 1                # A's own receipt, pushed next pass
    assert len(spool(a, "lane-a", "new")) == 2             # the message and B's `delivered` receipt
    # The server drains its outbox on commit already.
    assert outbox(b, "alpha", "q") == [] and len(outbox(b, "alpha", "sent")) == 2
    rc, out = sync(a, capsys)
    assert rc == 0
    assert outbox(a, "beta", "q") == []
    assert len(spool(b, "lane-x", "new")) == 1             # A's receipt for lane-x's message
    rc, out = sync(a, capsys)
    assert rc == 0 and "accepted=0" in out
    assert len(spool(a, "lane-a", "new")) == 2 and len(spool(b, "supervisor", "new")) == 1
    no_torn(a), no_torn(b)


@pytest.mark.parametrize("limit", [0, 5, 40, 200, 600])
def test_t15_drop_mid_session_loses_and_duplicates_nothing(two, monkeypatch, capsys, limit):
    a, b, connect, _ = two
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "send", "supervisor@beta", "one") == 0
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "back")
    sent = [0]

    def drop_up(data):
        keep = max(0, limit - sent[0])
        sent[0] += len(data)
        return data[:keep]
    connect(up=drop_up)
    rc, out = sync(a, capsys)
    assert rc == 1 and "FAILED beta" in out
    no_torn(a), no_torn(b)
    connect()                                              # the link heals
    rc, out = sync(a, capsys)
    assert rc == 0
    rc, out = sync(a, capsys)
    assert rc == 0
    assert len(spool(b, "supervisor", "new")) == 1         # exactly one copy
    assert len([i for i in spool(a, "lane-a", "new")]) == 2
    assert outbox(a, "beta", "q") == [] and outbox(b, "alpha", "q") == []


def test_t15_corrupt_byte_ends_the_session_and_publishes_nothing_torn(two, monkeypatch, capsys):
    a, b, connect, _ = two
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "send", "supervisor@beta", "intact") == 0
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "reply")
    seen = [0]

    def flip(data):
        out = bytearray(data)
        if seen[0] < 400 <= seen[0] + len(out):
            out[400 - seen[0]] ^= 0x01
        seen[0] += len(data)
        return bytes(out)
    connect(down=flip)
    rc, out = sync(a, capsys)
    assert rc == 1 and "FAILED beta" in out
    assert spool(a, "lane-a", "new") == []                 # nothing from the bad frame
    no_torn(a), no_torn(b)
    connect()
    assert sync(a, capsys)[0] == 0 and sync(a, capsys)[0] == 0
    assert len(spool(b, "supervisor", "new")) == 1 and len(spool(a, "lane-a", "new")) == 2


def test_t15_duplicated_frame_is_refused_without_a_second_copy(two, monkeypatch, capsys):
    a, b, connect, _ = two
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "send", "supervisor@beta", "once") == 0
    frames = [0]

    def dup(data):
        frames[0] += 1
        return data + data if data.startswith(b'{"len"') and b'"op":"push"' in data else data
    connect(up=dup)
    rc, out = sync(a, capsys)
    assert rc == 1                                         # the doubled push desyncs the session
    connect()
    assert sync(a, capsys)[0] == 0
    assert len(spool(b, "supervisor", "new")) == 1


def test_t15_replayed_session_commits_nothing_new(two, monkeypatch, capsys):
    a, b, connect, _ = two
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "send", "supervisor@beta", "m1") == 0
    first = enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "b1")
    rec = []
    connect(rec=rec)
    assert sync(a, capsys)[0] == 0
    later = enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "b2")
    before = (outbox(b, "alpha", "q"), outbox(b, "alpha", "sent"), spool(b, "supervisor", "new"))
    replay = subprocess.run(server_argv(b, "alpha"), input=b"".join(rec), capture_output=True,
                            env=_env(), timeout=60)
    assert replay.returncode in (0, 1)
    assert spool(b, "supervisor", "new") == before[2]      # the push is `duplicate`, not stored again
    assert outbox(b, "alpha", "sent") == before[1]         # the forged commit moved nothing new
    assert any(later["id"] in n for n in outbox(b, "alpha", "q"))
    assert first["id"] not in "".join(outbox(b, "alpha", "q"))


# --- T15b: clocks, late entries --------------------------------------------------

def test_t15b_hello_warns_on_skew_and_pull_never_filters_by_hint(two, monkeypatch):
    a, b, connect, _ = two
    prims = fleet._msg_prims()
    store = fleet_msg.open_store(prims)
    # A 10 minute slow client clock only warns; the receiver's bounds hold.
    slow = core.Store(a, "alpha", clock=lambda: time.time() - 600)
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "one")
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "two")
    pipes = []

    def spawn(argv, **kw):
        pipes.append(Pipe(server_argv(b, "alpha")))
        return pipes[-1]
    ssh = sshx.SshTransport(slow, "beta", ["x"], spawn=spawn)
    local = transport.SiteInfo(site="alpha", schemas=(core.SCHEMA,),
                               clock=core.iso_utc(time.time() - 600), hosted=("lane-a",))
    remote = ssh.hello(local)
    assert remote.site == "beta" and any("clock skew" in w for w in ssh.warnings)
    got = ssh.pull(10 ** 9)                                # a hint above every qseq filters nothing
    assert len(got) == 2
    ids = [ssh.entry_id(q) for q, _raw in got]
    ssh.commit(ids[:1])                                    # commit by id, not by mark
    ssh.close()
    assert len(outbox(b, "alpha", "q")) == 1 and len(outbox(b, "alpha", "sent")) == 1
    assert store is not None


def test_t15b_an_entry_enqueued_after_the_pull_is_sent_next_pass(two, monkeypatch, capsys):
    a, b, connect, _ = two
    enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "early")
    late = []

    def delay_commit(data):
        if b'"op":"commit"' in data and not late:
            late.append(enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "late"))
            time.sleep(0.2)
        return data
    connect(up=delay_commit)
    assert sync(a, capsys)[0] == 0
    assert len(late) == 1 and len(outbox(b, "alpha", "q")) == 1     # only `late` waits, by id
    connect()
    assert sync(a, capsys)[0] == 0
    assert outbox(b, "alpha", "q") == [] and len(spool(a, "lane-a", "new")) == 2


# --- T15c: auth ---------------------------------------------------------------------

def test_t15c_envelope_from_a_name_the_peer_does_not_host_is_rejected_auth(two, capsys):
    a, b, _c, _p = two
    forged = enqueue(a, "alpha", "ghost@alpha", "supervisor@beta", "i am not hosted")
    rc, out = sync(a, capsys)
    assert rc == 0 and "rejected=1" not in out             # counts are of what A pulled
    assert spool(b, "supervisor", "new") == []
    rejected = list((b / "state/msg/rejected").glob(f"{forged['id']}-*.json"))
    assert len(rejected) == 1 and json.loads(rejected[0].read_text())["reason"] == "auth"
    assert outbox(a, "beta", "q") == []
    ledger = (a / "state/msg/ledger.jsonl").read_text()
    assert "rejected-by-peer" in ledger and forged["id"] in ledger


def test_t15c_serve_refuses_without_peer_and_with_its_own_label(two):
    a, b, _c, _p = two
    run = subprocess.run([sys.executable, FLEET_PY, "--fleet-home", str(b), "msg", "serve"],
                         capture_output=True, env=_env(), timeout=60, input=b"")
    assert run.returncode == 2 and b"requires --peer" in run.stderr and run.stdout == b""
    own = subprocess.run(server_argv(b, "beta"), capture_output=True, env=_env(), timeout=60,
                         input=b"")
    assert own.returncode == 2 and b"own site label" in own.stderr


def test_t15c_the_server_pins_the_client_site_from_peer_not_from_hello(two):
    a, b, _c, _p = two
    hello = transport.SiteInfo(site="mallory", schemas=(core.SCHEMA,),
                               clock=core.iso_utc(time.time()), hosted=("supervisor",))
    run = subprocess.run(server_argv(b, "alpha"), capture_output=True, env=_env(), timeout=60,
                         input=sshx.encode_frame("hello", sshx.dumps(hello.to_json())))
    assert run.returncode == 1 and run.stdout == b"" and b"pinned to 'alpha'" in run.stderr


def test_t15c_same_label_on_both_ends_is_refused_by_hello(two, capsys, monkeypatch):
    a, b, _c, _p = two
    (b / "state/msg/site.json").write_text(json.dumps({"site": "alpha"}))
    rc, out = sync(a, capsys)
    assert rc == 1 and "FAILED beta" in out


# --- T15d: no skipped entry, qseq order ----------------------------------------------

def test_t15d_two_senders_pulled_between_are_never_skipped(two, capsys):
    a, b, _c, _p = two
    first = enqueue(b, "beta", "lane-x@beta", "lane-a@alpha", "x1")
    assert sync(a, capsys)[0] == 0
    second = enqueue(b, "beta", "lane-x@beta", "lane-b@alpha", "x2")
    third = enqueue(b, "beta", "supervisor@beta", "lane-a@alpha", "s1")
    assert sync(a, capsys)[0] == 0
    names = outbox(b, "alpha", "sent")
    order = [n.split("-")[1][:32] for n in sorted(names)]
    assert order == [first["id"], second["id"], third["id"]] + [
        r for r in order[3:]]                                # then receipts, in qseq order
    assert outbox(b, "alpha", "q") == []


# --- T15e: ingest cap -----------------------------------------------------------------

def test_t15e_the_201st_envelope_from_a_peer_in_an_hour_is_rejected_rate(two, capsys):
    a, b, _c, _p = two
    lanes = {f"lane-{i:02d}": _lane(f"sid-{i:02d}") for i in range(21)}
    registry(a, lanes)
    total = 0
    for lane in lanes:
        for n in range(10):
            enqueue(a, "alpha", f"{lane}@alpha", "supervisor@beta", f"{lane} {n}")
            total += 1
    assert total == 210
    for _ in range(4):
        assert sync(a, capsys)[0] == 0
    accepted = len(spool(b, "supervisor", "new"))
    rejected = [json.loads(p.read_text())["reason"] for p in (b / "state/msg/rejected").glob("*.json")]
    assert accepted == 200 and rejected == ["rate"] * 10
    assert outbox(a, "beta", "q") == []


# --- exit 4 -----------------------------------------------------------------------------

def test_sync_exits_4_after_max_failures_and_a_clean_pass_resets(two, monkeypatch, capsys):
    a, b, connect, _ = two

    def refuse(argv, **kw):
        raise OSError("ssh: not found")
    monkeypatch.setattr(fleet_msg, "_ssh_spawn", refuse)
    rc, out = sync(a, capsys)
    assert rc == 1 and "failure 1 of 2" in out
    rc, out = sync(a, capsys)
    assert rc == 4 and "failure 2 of 2" in out             # max_failures reached
    connect()
    assert sync(a, capsys)[0] == 0
    monkeypatch.setattr(fleet_msg, "_ssh_spawn", refuse)
    assert sync(a, capsys)[0] == 1                         # the counter restarted


def test_inbox_never_dials_an_ssh_peer(two, monkeypatch, capsys):
    a, _b, _c, _p = two

    def never(argv, **kw):
        raise AssertionError("inbox dialed ssh")
    monkeypatch.setattr(fleet_msg, "_ssh_spawn", never)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sid-a")
    assert msg(a, "inbox", "lane-a") == 0


def test_serve_writes_only_frames_to_stdout(two):
    a, b, _c, _p = two
    hello = transport.SiteInfo(site="alpha", schemas=(core.SCHEMA,),
                               clock=core.iso_utc(time.time()), hosted=("lane-a",))
    run = subprocess.run(server_argv(b, "alpha"), capture_output=True, env=_env(), timeout=60,
                         input=sshx.encode_frame("hello", sshx.dumps(hello.to_json()))
                         + sshx.encode_frame("bye"))
    assert run.returncode == 0
    op, payload = sshx.read_frame(io.BytesIO(run.stdout))
    assert op == "hello" and json.loads(payload)["site"] == "beta"
