"""Messaging contracts and primitives (spec docs/specs/messaging.md §4, §5, §7;
plan docs/plans/messaging-plan.md PR 1, tests T1-T6 and the core part of T15d).
"""
import ast
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import fleet_msg_core as core
import fleet_msg_transport as transport

BIN = Path(__file__).resolve().parents[1] / "bin"
MODULES = ("fleet_msg_core.py", "fleet_msg_transport.py")
NOW = 1_800_000_000.0
AUTH = {"method": "unverified", "detail": None}


class Crash(Exception):
    pass


def make_store(tmp_path, site="a", **kw):
    kw.setdefault("clock", lambda: NOW)
    return core.Store(tmp_path / "home", site, **kw)


def draft(frm="lane-1@a", to="lane-2@a", body="hello", **kw):
    kw.setdefault("from_auth", AUTH)
    kw.setdefault("sent_at", core.iso_utc(NOW))
    return core.make_draft(frm, to, body, **kw)


def envelope(seq=1, **kw):
    return core.validate(dict(draft(**kw), seq=seq))


def ledger(store):
    try:
        text = store.ledger_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines()]


def places(store, name, msg_id):
    return [s for s in ("new", "cur", "done")
            if (store.spool(name, s) / f"{msg_id}.json").exists()]


# --- envelope (§4) ----------------------------------------------------------

def test_envelope_canonical_round_trip_and_random_id():
    env = envelope()
    raw = core.canonical(env)
    assert raw == json.dumps(env, sort_keys=True, separators=(",", ":")).encode()
    assert core.parse(raw) == env
    assert len(env["id"]) == 32 and env["id"] != envelope()["id"]
    assert env["thread"] == env["id"] and env["hop"] == 0 and env["re"] is None
    assert env["path"] == ["lane-1@a"]


def test_reply_threading_fields():
    parent = envelope()
    reply = core.make_draft("lane-2@a", "lane-1@a", "ok", from_auth=AUTH,
                            sent_at=core.iso_utc(NOW), parent=parent)
    assert reply["re"] == parent["id"] and reply["thread"] == parent["thread"]
    assert reply["hop"] == 1 and reply["path"] == ["lane-1@a", "lane-2@a"]


@pytest.mark.parametrize("mutate, reason", [
    (lambda e: e.update(extra=1), "schema"),
    (lambda e: e.pop("kind"), "schema"),
    (lambda e: e.update(schema=2), "schema"),
    (lambda e: e.update(schema=True), "schema"),
    (lambda e: e.update(id="ABC"), "schema"),
    (lambda e: e.update(to="Lane@a"), "schema"),
    (lambda e: e.update(to="lane"), "schema"),
    (lambda e: e.update(kind="question"), "schema"),
    (lambda e: e.update(needs_answer=1), "schema"),
    (lambda e: e.update(seq=0), "schema"),
    (lambda e: e.update(hop=1), "schema"),
    (lambda e: e.update(sent_at="yesterday"), "schema"),
    (lambda e: e.update(from_auth={"method": "root", "detail": None}), "schema"),
    (lambda e: e.update(from_auth={"method": "unverified", "detail": "x\n"}), "schema"),
    (lambda e: e.update(body="changed"), "corrupt"),
])
def test_validate_rejects(mutate, reason):
    env = envelope()
    mutate(env)
    with pytest.raises(core.EnvelopeError) as err:
        core.validate(env)
    assert err.value.reason == reason


def test_body_bounds_words_and_bytes():
    draft(body=" ".join(["w"] * 120))
    with pytest.raises(core.EnvelopeError, match="size"):
        draft(body=" ".join(["w"] * 121))
    draft(body="x" * 8192)
    with pytest.raises(core.EnvelopeError, match="size"):
        draft(body="x" * 8193)


def test_parse_rejects_non_canonical_and_bad_json():
    env = envelope()
    with pytest.raises(core.EnvelopeError) as err:
        core.parse(json.dumps(env, indent=1).encode())
    assert err.value.reason == "corrupt"
    with pytest.raises(core.EnvelopeError) as err:
        core.parse(b"{")
    assert err.value.reason == "corrupt"


def test_clock_check_future_and_stale_by_receiver_clock():
    env = envelope()
    assert core.clock_check(env, NOW) is None
    assert core.clock_check(env, NOW - 301) == "future"
    assert core.clock_check(env, NOW - 300) is None
    assert core.clock_check(env, NOW + 30 * 86400 + 1) == "stale"


# --- T1: crash injection in publish between every step ----------------------

PUBLISH_POINTS = ("tmp-written", "linked", "dir-synced")


@pytest.mark.parametrize("point", PUBLISH_POINTS)
def test_t1_crash_at_each_publish_step_then_rerun(tmp_path, point):
    notices = []

    def fault(at):
        if at == point and not fired:
            fired.append(at)
            raise Crash(at)

    fired = []
    store = make_store(tmp_path, fault=fault)
    env = envelope()
    with pytest.raises(Crash):
        core.publish(store, "lane-2", env, notify=lambda n, e: notices.append(e["id"]))
    marker = store.marker(env["id"]).exists()
    held = places(store, "lane-2", env["id"])
    assert len(held) <= 1
    assert not marker or held, "a marker never exists without a message"

    result = core.publish(store, "lane-2", env,
                          notify=lambda n, e: notices.append(e["id"]))
    assert places(store, "lane-2", env["id"]) == ["new"]
    assert store.marker(env["id"]).exists()
    delivered = [r for r in ledger(store) if r["event"] == "delivered"]
    assert len(delivered) == 1, "the delivered ledger line is written exactly once"
    assert notices == [env["id"]], "the notice runs exactly once"
    if point == "tmp-written":
        assert result == "delivered"
    else:
        assert result == "duplicate" and delivered[0].get("repaired") is True
    # A third ingest is a plain duplicate: no new ledger line, no notice.
    assert core.publish(store, "lane-2", env,
                        notify=lambda n, e: notices.append(e["id"])) == "duplicate"
    assert len([r for r in ledger(store) if r["event"] == "delivered"]) == 1
    assert notices == [env["id"]]


@pytest.mark.parametrize("point, lines", [("marked", 0), ("ledgered", 1)])
def test_t1_crash_after_marker_is_a_known_residual(tmp_path, point, lines):
    """Spec §5 orders marker, then ledger, then notice. A crash after the
    marker leaves the message delivered exactly once; it can lose the
    ledger line (an operational log, spec §13) or the notice (a wake; the
    drain rule still shows the message, spec §9). It never duplicates."""
    fired = []

    def fault(at):
        if at == point and not fired:
            fired.append(at)
            raise Crash(at)

    notices = []
    store = make_store(tmp_path, fault=fault)
    env = envelope()
    with pytest.raises(Crash):
        core.publish(store, "lane-2", env, notify=lambda n, e: notices.append(n))
    assert places(store, "lane-2", env["id"]) == ["new"]
    assert store.marker(env["id"]).exists()
    assert core.publish(store, "lane-2", env,
                        notify=lambda n, e: notices.append(n)) == "duplicate"
    assert len([r for r in ledger(store) if r["event"] == "delivered"]) == lines
    assert notices == []


def test_t1_repair_after_file_without_marker(tmp_path):
    store = make_store(tmp_path)
    env = envelope()
    new = store.spool("lane-2", "new")
    new.mkdir(parents=True)
    (new / f"{env['id']}.json").write_bytes(core.canonical(env))
    notices = []
    assert core.publish(store, "lane-2", env,
                        notify=lambda n, e: notices.append(n)) == "duplicate"
    assert store.marker(env["id"]).exists()
    assert [r["event"] for r in ledger(store)] == ["delivered"]
    assert notices == ["lane-2"]


def test_publish_refuses_a_spool_other_than_to(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(core.StoreError):
        core.publish(store, "lane-3", envelope())
    with pytest.raises(core.StoreError):
        core.publish(store, "lane-2", envelope(to="lane-2@b"))
    assert not store.root.joinpath("spool").exists()


def test_notice_failure_is_logged_not_raised(tmp_path):
    store = make_store(tmp_path)

    def boom(name, env):
        raise RuntimeError("wake down")

    assert core.publish(store, "lane-2", envelope(), notify=boom) == "delivered"
    assert [r["event"] for r in ledger(store)] == ["delivered", "notice-failed"]


# --- T2: concurrent publish of one id ----------------------------------------

def test_t2_concurrent_publish_threads(tmp_path):
    store = make_store(tmp_path)
    env = envelope()
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()
        results.append(core.publish(store, "lane-2", env))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["delivered"] + ["duplicate"] * 7
    assert core.list_spool(store, "lane-2", "new") == [env["id"]]


_PUBLISH_CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
import fleet_msg_core as core
store = core.Store(sys.argv[2], "a")
raw = open(sys.argv[3], "rb").read()
start = float(sys.argv[4])
while time.time() < start:
    time.sleep(0.001)
print(core.publish(store, "lane-2", core.parse(raw)))
"""


def test_t2_concurrent_publish_processes(tmp_path):
    store = make_store(tmp_path)
    env = envelope()
    raw_path = tmp_path / "env.json"
    raw_path.write_bytes(core.canonical(env))
    start = time.time() + 1.0
    procs = [subprocess.Popen(
        [sys.executable, "-c", _PUBLISH_CHILD, str(BIN), str(store.home),
         str(raw_path), str(start)], stdout=subprocess.PIPE, text=True)
        for _ in range(4)]
    outs = sorted(p.communicate(timeout=60)[0].strip() for p in procs)
    assert all(p.returncode == 0 for p in procs)
    assert outs == ["delivered", "duplicate", "duplicate", "duplicate"]
    assert core.list_spool(store, "lane-2", "new") == [env["id"]]


# --- T3: reader moves new -> cur during a second ingest ----------------------

def test_t3_read_during_ingest_never_reappears_in_new(tmp_path):
    store = make_store(tmp_path)
    env = envelope()
    assert core.publish(store, "lane-2", env) == "delivered"
    stop = threading.Event()
    results = []

    def ingest():
        while not stop.is_set():
            results.append(core.publish(store, "lane-2", env))

    thread = threading.Thread(target=ingest)
    thread.start()
    try:
        assert core.move(store, "lane-2", env["id"], "new", "cur", reader="lane-2@a")
        time.sleep(0.05)
    finally:
        stop.set()
        thread.join()
    assert set(results) <= {"duplicate"}
    assert places(store, "lane-2", env["id"]) == ["cur"]
    assert core.move(store, "lane-2", env["id"], "cur", "done")
    assert core.publish(store, "lane-2", env) == "duplicate"
    assert places(store, "lane-2", env["id"]) == ["done"]


def test_t3_repair_path_sees_cur_and_done(tmp_path):
    """Without a marker, a file in cur/ or done/ still counts as held."""
    store = make_store(tmp_path)
    for state in ("cur", "done"):
        env = envelope()
        d = store.spool("lane-2", state)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{env['id']}.json").write_bytes(core.canonical(env))
        assert core.publish(store, "lane-2", env) == "duplicate"
        assert places(store, "lane-2", env["id"]) == [state]


def test_move_rejects_other_transitions(tmp_path):
    store = make_store(tmp_path)
    env = envelope()
    core.publish(store, "lane-2", env)
    with pytest.raises(core.StoreError):
        core.move(store, "lane-2", env["id"], "new", "done")
    assert not core.move(store, "lane-2", env["id"], "cur", "done")


# --- T4: concurrent senders on one (from, to) --------------------------------

def test_t4_concurrent_senders_get_distinct_gap_free_seqs(tmp_path):
    store = make_store(tmp_path)
    seqs = []
    lock = threading.Lock()
    barrier = threading.Barrier(6)

    def sender():
        barrier.wait()
        for _ in range(5):
            _, env = core.enqueue(store, draft())
            with lock:
                seqs.append(env["seq"])

    threads = [threading.Thread(target=sender) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(seqs) == list(range(1, 31))
    assert store.last_seq("lane-1@a", "lane-2@a") == 30


_ENQUEUE_CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
import fleet_msg_core as core
store = core.Store(sys.argv[2], "a")
for _ in range(10):
    d = core.make_draft("lane-1@a", sys.argv[3], "x",
                        from_auth={"method": "unverified", "detail": None},
                        sent_at=core.iso_utc(store.clock()))
    print(core.enqueue(store, d)[1]["seq"])
"""


@pytest.mark.parametrize("to", ["lane-2@a", "lane-2@b"])
def test_t4_concurrent_sender_processes(tmp_path, to):
    store = make_store(tmp_path)
    procs = [subprocess.Popen(
        [sys.executable, "-c", _ENQUEUE_CHILD, str(BIN), str(store.home), to],
        stdout=subprocess.PIPE, text=True) for _ in range(3)]
    seqs = [int(x) for p in procs for x in p.communicate(timeout=60)[0].split()]
    assert all(p.returncode == 0 for p in procs)
    assert sorted(seqs) == list(range(1, 31))
    if to.endswith("@b"):
        qseqs = [q for q, _ in core.outbox_entries(store, "b")]
        assert qseqs == list(range(1, 31))


# --- T5: refusal leaves no gap; crash after allocation shows a gap -----------

def test_t5_refusal_allocates_nothing(tmp_path):
    store = make_store(tmp_path)
    core.enqueue(store, draft())
    with pytest.raises(core.Refused) as err:
        core.enqueue(store, draft(), rules=lambda d: "rate")
    assert err.value.reason == "rate"
    _, env = core.enqueue(store, draft(), rules=lambda d: None)
    assert env["seq"] == 2
    assert not (store.root / "seq" / "lane-1@a__lane-9@a").exists()


def test_t5_crash_after_seq_allocation_leaves_a_visible_gap(tmp_path):
    fired = []

    def fault(at):
        if at == "seq-allocated" and not fired:
            fired.append(at)
            raise Crash(at)

    store = make_store(tmp_path, fault=fault)
    with pytest.raises(Crash):
        core.enqueue(store, draft())
    _, env = core.enqueue(store, draft())
    assert env["seq"] == 2, "the gap at seq 1 is permanent and blocks nothing"
    assert core.list_spool(store, "lane-2", "new") == [env["id"]]


def test_rules_run_under_the_sender_lock_before_allocation(tmp_path):
    store = make_store(tmp_path)
    seen = []

    def rules(d):
        seen.append((d["seq"], store.last_seq(d["from"], d["to"])))
        return None

    core.enqueue(store, draft(), rules=rules)
    assert seen == [(None, 0)]


def test_enqueue_refuses_non_local_sender(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(core.EnvelopeError) as err:
        core.enqueue(store, draft(frm="lane-1@b"))
    assert err.value.reason == "auth"


# --- T6: fsync of file and directory -----------------------------------------

def test_t6_publish_fsyncs_file_and_directory_before_returning(tmp_path):
    events = []

    def fsync(fd):
        events.append(("file", os.readlink(f"/proc/self/fd/{fd}")
                       if os.path.exists("/proc/self/fd") else fd))
        os.fsync(fd)

    def fsync_dir(path):
        events.append(("dir", str(path)))

    store = make_store(tmp_path, fsync=fsync, fsync_dir=fsync_dir)
    env = envelope()
    new = store.spool("lane-2", "new")
    store._ensure_dir(new)  # setup only; count the publish's own calls below
    events.clear()
    core.publish(store, "lane-2", env)
    kinds = [k for k, _ in events]
    assert kinds.count("file") >= 2, "envelope tmp file and marker are fsynced"
    assert ("dir", str(new)) in events, "new/ is fsynced after link()"
    marker_dir = str(store.marker(env["id"]).parent)
    assert ("dir", marker_dir) in events
    assert events.index(("dir", str(new))) < events.index(("dir", marker_dir))


def test_t6_seq_and_outbox_writes_fsync(tmp_path):
    dirs = []
    store = make_store(tmp_path, fsync_dir=lambda p: dirs.append(str(p)))
    core.enqueue(store, draft(to="lane-2@b"))
    assert str(store.root / "seq") in dirs
    assert str(store.outbox("b", "q")) in dirs
    assert str(store.root / "outbox" / "b") in dirs  # qseq counter


# --- outbox and the per-outbox lock (§5, §7; core part of T15d) --------------

def test_remote_enqueue_writes_outbox_file_named_by_qseq(tmp_path):
    store = make_store(tmp_path)
    status, env = core.enqueue(store, draft(to="lane-2@b"))
    assert status == "queued"
    entries = core.outbox_entries(store, "b")
    assert entries == [(1, core.canonical(env))]
    assert sorted(os.listdir(store.outbox("b", "q"))) == [
        f"{1:012d}-{env['id']}.json"]
    assert [r["event"] for r in ledger(store)] == ["queued"]


def test_t15d_core_visibility_order_equals_qseq_order(tmp_path):
    """Two concurrent remote senders; the first is delayed inside its write.
    The second cannot become visible first, and a pull between them never
    skips an entry."""
    gate = threading.Event()
    in_first = threading.Event()
    first_thread = []

    def fault(at):
        if at == "qseq-allocated" and threading.current_thread() in first_thread:
            in_first.set()
            gate.wait(5)

    store = make_store(tmp_path, fault=fault)
    out = {}

    def send(key, frm):
        out[key] = core.enqueue(store, draft(frm=frm, to="hub@b"))[1]

    a = threading.Thread(target=send, args=("a", "lane-1@a"))
    b = threading.Thread(target=send, args=("b", "lane-3@a"))
    first_thread.append(a)
    a.start()
    assert in_first.wait(5)
    b.start()
    time.sleep(0.1)
    assert core.outbox_entries(store, "b") == [], "nothing visible mid-write"
    gate.set()
    a.join()
    b.join()
    entries = core.outbox_entries(store, "b", hint_qseq=2)
    assert [q for q, _ in entries] == [1, 2], "the hint never filters"
    assert [core.parse(raw)["id"] for _, raw in entries] == [out["a"]["id"], out["b"]["id"]]


def test_outbox_commit_moves_exact_ids_only(tmp_path):
    store = make_store(tmp_path)
    envs = [core.enqueue(store, draft(to="hub@b"))[1] for _ in range(3)]
    moved = core.outbox_commit(store, "b", [envs[2]["id"], envs[0]["id"]])
    assert sorted(moved) == sorted([envs[0]["id"], envs[2]["id"]])
    assert [core.parse(r)["id"] for _, r in core.outbox_entries(store, "b")] == [envs[1]["id"]]
    assert len(os.listdir(store.outbox("b", "sent"))) == 2
    assert core.outbox_commit(store, "b", [envs[0]["id"]]) == []


def test_reject_keeps_original_bytes(tmp_path):
    store = make_store(tmp_path)
    path = core.reject(store, b"not json", "corrupt")
    record = json.loads(path.read_bytes())
    import base64
    assert base64.b64decode(record["raw_b64"]) == b"not json"
    assert record["reason"] == "corrupt"
    with pytest.raises(core.StoreError):
        core.reject(store, b"x", "because")


def test_lock_families_are_disjoint_for_every_name():
    store = core.Store("/nonexistent", "a")
    paths = {store.lock_path(kind, name)
             for kind in ("from", "spool", "outbox")
             for name in ("spool-x", "x", "from-x", "outbox-x")}
    assert len(paths) == 12


def test_names_cannot_escape_the_store(tmp_path):
    store = make_store(tmp_path)
    for bad in ("../x", "x/y", "", "X", "a" * 41):
        with pytest.raises(core.StoreError):
            store.spool(bad, "new")
    with pytest.raises(core.StoreError):
        store.marker("../../etc")


def test_fails_closed_without_a_lock_backend(tmp_path, monkeypatch):
    import fleet_mailman
    monkeypatch.setattr(fleet_mailman, "_fcntl", None)
    monkeypatch.setattr(fleet_mailman, "_msvcrt", None)
    with pytest.raises(core.StoreError, match="lock"):
        core.publish(make_store(tmp_path), "lane-2", envelope())


def test_lock_timeout_raises(tmp_path):
    clock = iter(range(1000))
    store = make_store(tmp_path, monotonic=lambda: next(clock),
                       sleep=lambda s: None, lock_timeout=3)
    with store.locked("spool", "lane-2"):
        with pytest.raises(core.StoreError, match="timeout"):
            with store.locked("spool", "lane-2"):
                pass


# --- Transport contract (§7) --------------------------------------------------

class FakeTransport:
    def hello(self, local):
        return local

    def push(self, envelopes):
        return {}

    def pull(self, hint_qseq):
        return []

    def commit(self, ids):
        return None

    def close(self):
        return None


def test_transport_protocol_has_exactly_five_methods():
    assert isinstance(FakeTransport(), transport.Transport)
    methods = {n for n, v in vars(transport.Transport).items()
               if callable(v) and not n.startswith("_")}
    assert methods == {"hello", "push", "pull", "commit", "close"}


def test_push_result_vocabulary():
    assert transport.parse_push_result("accepted") == ("accepted", None)
    assert transport.parse_push_result("duplicate") == ("duplicate", None)
    assert transport.parse_push_result(transport.rejected("auth")) == ("rejected", "auth")
    for bad in ("rejected:why", "ok", None):
        with pytest.raises(transport.TransportError):
            transport.parse_push_result(bad)


def test_hello_refuses_same_label_and_warns_on_skew():
    local = transport.SiteInfo("a", (1,), core.iso_utc(NOW), ("supervisor",))
    same = transport.SiteInfo("a", (1,), core.iso_utc(NOW), ())
    with pytest.raises(transport.TransportError, match="local site label"):
        transport.check_hello(local, same, NOW)
    old = transport.SiteInfo("b", (2,), core.iso_utc(NOW), ())
    with pytest.raises(transport.TransportError, match="schema"):
        transport.check_hello(local, old, NOW)
    skewed = transport.SiteInfo("b", (1,), core.iso_utc(NOW - 600), ())
    assert transport.check_hello(local, skewed, NOW) == ["clock skew -600 s with site b"]
    assert transport.SiteInfo.from_json(local.to_json()) == local
    with pytest.raises(transport.TransportError):
        transport.SiteInfo.from_json({"site": "a"})


# --- doctrine pins (plan §4) ----------------------------------------------------

def _source(name):
    return (BIN / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", MODULES)
def test_no_fleet_or_fleet_lock_import_and_stdlib_only(name):
    tree = ast.parse(_source(name))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "fleet" not in imported and "fleet_lock" not in imported
    local = {p.stem for p in BIN.glob("*.py")}
    assert imported & local <= {"fleet_mailman", "fleet_platform",
                                "fleet_msg_core", "fleet_errors"}
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
                  and n.body and isinstance(n.body[0], ast.Expr)}
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]
    assert not [v for v in literals if "fleet.lock" in v]
    for needle in ("registry.json", "load_registry", "save_registry"):
        assert needle not in _source(name)


@pytest.mark.parametrize("name", MODULES)
def test_unlink_only_of_private_tmp_names(name):
    """No unlink of a message, marker or ledger outside a purge seam."""
    tree = ast.parse(_source(name))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Attribute)
                        and inner.attr in ("unlink", "remove", "rmdir", "rmtree")):
                    sites.append(node.name)
    allowed = {"_write_new"} if name == "fleet_msg_core.py" else set()
    assert set(sites) <= allowed, sites


def test_modules_import_under_python_310_floor():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "import fleet_msg_core, fleet_msg_transport")
    subprocess.run([sys.executable, "-c", code, str(BIN)], check=True)
    for name in MODULES:
        ast.parse(_source(name), name, feature_version=(3, 10))
