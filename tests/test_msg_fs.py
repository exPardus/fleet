"""fs transport (spec docs/specs/messaging.md §7.1; plan PR 4, test T11)."""
import ast
import json
import os
from pathlib import Path

import pytest

import fleet_msg_core as core
import fleet_msg_fs as fs
import fleet_msg_transport as transport

BIN = Path(__file__).resolve().parents[1] / "bin"
NOW = 1_800_000_000.0
AUTH = {"method": "unverified", "detail": None}
HOSTED = {"alpha": ["lane-1", "supervisor"], "beta": ["lane-2"]}


class Prims:
    def __init__(self, homes):
        self.homes = {Path(h): names for h, names in homes.items()}

    def hosted(self, home):
        return self.homes[Path(home)]


class Pair:
    """Two homes on one machine, labelled alpha and beta."""

    def __init__(self, tmp_path):
        self.a = core.Store(tmp_path / "alpha", "alpha", clock=lambda: NOW)
        self.b = core.Store(tmp_path / "beta", "beta", clock=lambda: NOW)
        for store in (self.a, self.b):
            store._ensure_dir(store.root)
            (store.root / "site.json").write_text(json.dumps({"site": store.site}))
        self.prims = Prims({self.a.home: HOSTED["alpha"], self.b.home: HOSTED["beta"]})

    def link(self, local):
        """The transport the `local` home uses to reach the other one."""
        peer = self.b if local is self.a else self.a
        return fs.FsTransport(local, peer.home, peer.site, self.prims)

    def info(self, store):
        return transport.SiteInfo(store.site, (1,), core.iso_utc(NOW), tuple(HOSTED[store.site]))


def draft(frm="lane-1@alpha", to="lane-2@beta", body="hello", **kw):
    kw.setdefault("from_auth", AUTH)
    kw.setdefault("sent_at", core.iso_utc(NOW))
    return core.make_draft(frm, to, body, **kw)


def sync(pair, local, admit=None, link=None):
    """One driver pass: hello, pull, ingest each entry, commit the ids."""
    link = link or pair.link(local)
    peer_info = link.hello(pair.info(local))
    ids, results = [], {}
    for qseq, raw in link.pull(0):
        result = core.ingest(local, raw, peer_site=link.peer_site,
                             hosted=peer_info.hosted, admit=admit)
        msg_id = link.entry_id(qseq)
        results[msg_id] = result
        ids.append(msg_id)
    link.commit(ids)
    return results


def listing(path):
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return []


def snapshot(home):
    out = {}
    for root, _dirs, files in os.walk(home):
        for name in files:
            p = Path(root) / name
            st = os.lstat(p)
            out[str(p.relative_to(home))] = (st.st_mtime_ns, p.read_bytes())
    return out


@pytest.fixture
def pair(tmp_path):
    return Pair(tmp_path)


# --- hello, push -------------------------------------------------------------

def test_conforms_to_the_transport_protocol(pair):
    assert isinstance(pair.link(pair.a), transport.Transport)


def test_hello_reads_site_json_and_hosted_names(pair):
    info = pair.link(pair.a).hello(pair.info(pair.a))
    assert (info.site, info.hosted, info.schemas) == ("beta", ("lane-2",), (1,))


def test_hello_refuses_a_peer_that_labels_itself_otherwise(pair):
    (pair.b.root / "site.json").write_text(json.dumps({"site": "gamma"}))
    with pytest.raises(transport.TransportError, match="labels itself"):
        pair.link(pair.a).hello(pair.info(pair.a))


def test_hello_refuses_the_local_label(pair):
    (pair.b.root / "site.json").write_text(json.dumps({"site": "alpha"}))
    with pytest.raises(transport.TransportError):
        fs.FsTransport(pair.a, pair.b.home, "alpha", pair.prims)


def test_hello_refuses_missing_or_bad_site_json(pair):
    (pair.b.root / "site.json").write_text("{not json")
    with pytest.raises(transport.TransportError):
        pair.link(pair.a).hello(pair.info(pair.a))
    (pair.b.root / "site.json").unlink()
    with pytest.raises(transport.TransportError, match="no readable site.json"):
        pair.link(pair.a).hello(pair.info(pair.a))


def test_hello_reports_the_machine_clock_so_one_machine_never_warns(pair):
    link = pair.link(pair.a)
    info = link.hello(pair.info(pair.a))
    assert info.clock == core.iso_utc(NOW) and link.warnings == []


def test_push_is_a_no_op_that_leaves_envelopes_in_the_local_outbox(pair):
    core.enqueue(pair.a, draft())
    before = snapshot(pair.a.home)
    link = pair.link(pair.a)
    raws = [raw for _q, raw in core.outbox_entries(pair.a, "beta")]
    assert link.push(raws) == {}
    assert snapshot(pair.a.home) == before and snapshot(pair.b.home) == {
        "state/msg/site.json": snapshot(pair.b.home)["state/msg/site.json"]}


# --- pull ---------------------------------------------------------------------

def test_pull_lists_every_entry_ascending_and_the_hint_never_filters(pair):
    envs = [core.enqueue(pair.a, draft(body=f"m{i}"))[1] for i in range(3)]
    pulled = pair.link(pair.b).pull(0)
    assert [core.parse(raw)["id"] for _q, raw in pulled] == [e["id"] for e in envs]
    assert [q for q, _ in pulled] == [1, 2, 3]
    assert [q for q, _ in pair.link(pair.b).pull(99)] == [1, 2, 3]


def test_pull_reads_only_the_outbox_addressed_to_this_site(pair):
    core.enqueue(pair.a, draft(to="lane-2@beta"))
    core.enqueue(pair.a, draft(to="lane-9@gamma"))
    assert len(pair.link(pair.b).pull(0)) == 1


def test_pull_with_no_peer_outbox_is_empty(pair):
    assert pair.link(pair.b).pull(0) == []


def test_pull_and_commit_write_nothing_in_the_peer_home(pair):
    env = core.enqueue(pair.a, draft())[1]
    before = snapshot(pair.a.home)
    sync(pair, pair.b)                       # pull, ingest, commit by beta
    assert snapshot(pair.a.home) == before   # alpha's tree is untouched
    assert core.list_spool(pair.b, "lane-2", "new") == [env["id"]]


def test_pull_refuses_a_symlinked_peer_directory(pair, tmp_path):
    core.enqueue(pair.a, draft())
    q = pair.a.outbox("beta", "q")
    elsewhere = tmp_path / "elsewhere"
    q.rename(elsewhere)
    q.symlink_to(elsewhere)
    with pytest.raises(transport.TransportError, match="plain directory"):
        pair.link(pair.b).pull(0)


def test_pull_refuses_a_symlinked_peer_entry(pair, tmp_path):
    env = core.enqueue(pair.a, draft())[1]
    entry = next(pair.a.outbox("beta", "q").iterdir())
    target = tmp_path / "target.json"
    target.write_bytes(core.canonical(env))
    entry.unlink()
    entry.symlink_to(target)
    with pytest.raises(transport.TransportError):
        pair.link(pair.b).pull(0)


# --- T11: duplicate after crash before receipt ---------------------------------

def q_ids(store, site):
    return [core.parse(raw)["id"] for _q, raw in core.outbox_entries(store, site)]


def sent_ids(store, site):
    return sorted(n.split("-")[1][:-5] for n in listing(store.outbox(site, "sent")))


def test_t11_duplicate_after_crash_before_receipt(pair):
    env = core.enqueue(pair.a, draft())[1]
    # beta ingests, then crashes before it commits: no receipt exists yet
    link_b = pair.link(pair.b)
    [(qseq, raw)] = link_b.pull(0)
    assert core.ingest(pair.b, raw, peer_site="alpha", hosted=["lane-1"]) == "accepted"
    assert q_ids(pair.b, "alpha") == []
    # next pass: the envelope is still in alpha's q/; ingest says duplicate and
    # commit re-emits `delivered`
    assert sync(pair, pair.b) == {env["id"]: "duplicate"}
    [receipt] = [core.parse(raw) for _q, raw in core.outbox_entries(pair.b, "alpha")]
    assert (receipt["kind"], receipt["re"], receipt["body"]) == ("receipt", env["id"], "delivered")
    assert (receipt["from"], receipt["to"]) == ("lane-2@beta", "lane-1@alpha")
    assert core.list_spool(pair.b, "lane-2", "new") == [env["id"]]      # one copy only
    # alpha pulls the receipt, publishes it, commits: its envelope drains to sent/
    assert sync(pair, pair.a) == {receipt["id"]: "accepted"}
    assert q_ids(pair.a, "beta") == [] and sent_ids(pair.a, "beta") == [env["id"]]
    assert core.list_spool(pair.a, "lane-1", "new") == [receipt["id"]]
    # beta's next pull settles the receipt entry into sent/
    sync(pair, pair.b)
    assert q_ids(pair.b, "alpha") == [] and sent_ids(pair.b, "alpha") == [receipt["id"]]


def test_receipt_entry_stays_until_the_source_leaves_the_peer_q(pair):
    core.enqueue(pair.a, draft())
    sync(pair, pair.b)
    sync(pair, pair.b)                       # alpha has not pulled the receipt yet
    assert len(q_ids(pair.b, "alpha")) == 1 and sent_ids(pair.b, "alpha") == []


def test_re_emitted_delivered_makes_one_receipt(pair):
    env = core.enqueue(pair.a, draft())[1]
    link = pair.link(pair.b)
    sync(pair, pair.b, link=link)
    link.commit([env["id"]])
    link.commit([env["id"]])
    assert len(listing(pair.b.outbox("alpha", "q"))) == 1
    assert fs.receipt_id(env["id"]) in q_ids(pair.b, "alpha")


def test_a_receipt_is_never_receipted(pair):
    core.enqueue(pair.a, draft())
    sync(pair, pair.b)
    sync(pair, pair.a)                       # alpha commits beta's receipt
    assert q_ids(pair.a, "beta") == []       # nothing new queued toward beta


def test_commit_of_an_unknown_or_already_moved_id_is_a_no_op(pair):
    link = pair.link(pair.b)
    link.commit([core.new_id()])
    assert listing(pair.b.outbox("alpha", "q")) == []


def test_commit_rejects_a_malformed_id(pair):
    with pytest.raises(transport.TransportError):
        pair.link(pair.b).commit(["not-an-id"])


def test_rejected_envelope_gets_a_rejected_receipt(pair):
    env = core.enqueue(pair.a, draft())[1]
    assert sync(pair, pair.b, admit=lambda e: "retired") == {env["id"]: "rejected:retired"}
    [receipt] = [core.parse(raw) for _q, raw in core.outbox_entries(pair.b, "alpha")]
    assert receipt["body"] == "rejected: retired" and receipt["kind"] == "receipt"
    assert core.list_spool(pair.b, "lane-2", "new") == []
    sync(pair, pair.a)
    assert sent_ids(pair.a, "beta") == [env["id"]]


def test_unhandled_id_gets_no_receipt(pair):
    env = core.enqueue(pair.a, draft())[1]
    pair.link(pair.b).commit([env["id"]])     # never ingested, never rejected
    assert listing(pair.b.outbox("alpha", "q")) == []


def test_a_receipt_never_exceeds_the_envelope_bounds(pair):
    core.enqueue(pair.a, draft())
    sync(pair, pair.b)
    [receipt] = [core.parse(raw) for _q, raw in core.outbox_entries(pair.b, "alpha")]
    assert receipt["from_auth"] == fs.RECEIPT_AUTH
    assert receipt["hop"] == 1 and receipt["path"] == ["lane-1@alpha", "lane-2@beta"]


def test_fifo_per_pair_survives_the_round_trip(pair):
    envs = [core.enqueue(pair.a, draft(body=f"m{i}"))[1] for i in range(4)]
    sync(pair, pair.b)
    assert [core.parse((pair.b.spool("lane-2", "new") / f"{e['id']}.json").read_bytes())["seq"]
            for e in envs] == [1, 2, 3, 4]


# --- corrupt files: retried, then rejected after three passes -------------------

def plant(store, site, qseq, raw):
    msg_id = core.new_id()
    q = store.outbox(site, "q")
    store._ensure_dir(q)
    (q / f"{qseq:012d}-{msg_id}.json").write_bytes(raw)
    return msg_id


def test_corrupt_file_is_withheld_twice_then_rejected_corrupt(pair):
    bad = plant(pair.a, "beta", 1, b'{"id": "torn')
    assert pair.link(pair.b).pull(0) == []                  # pass 1
    assert pair.link(pair.b).pull(0) == []                  # pass 2: a new instance, same counter
    [(qseq, raw)] = pair.link(pair.b).pull(0)               # pass 3: handed to ingest
    assert raw == b'{"id": "torn'
    link = pair.link(pair.b)
    link.pull(0)
    assert link.entry_id(qseq) == bad
    assert core.ingest(pair.b, raw, peer_site="alpha", hosted=["lane-1"]) == "rejected:corrupt"
    assert any(n.startswith("sha-") for n in listing(pair.b.rejected_dir))


def test_sha_mismatch_is_corrupt_and_retried(pair):
    env = core.enqueue(pair.a, draft(body="hi"))[1]
    path = next(pair.a.outbox("beta", "q").iterdir())
    path.write_bytes(core.canonical(dict(env, body="tampered")))
    assert pair.link(pair.b).pull(0) == []


def test_a_valid_file_is_never_struck(pair):
    core.enqueue(pair.a, draft())
    for _ in range(4):
        assert len(pair.link(pair.b).pull(0)) == 1
    assert not (pair.b.root / "fs-strikes").exists()


def test_a_non_corrupt_failure_passes_through_at_once(pair):
    env = core.enqueue(pair.a, draft())[1]
    path = next(pair.a.outbox("beta", "q").iterdir())
    path.write_bytes(core.canonical(dict(env, kind="bogus")))
    [(_q, raw)] = pair.link(pair.b).pull(0)
    assert core.ingest(pair.b, raw, peer_site="alpha", hosted=["lane-1"]) == "rejected:schema"


def test_strike_pass_count_is_a_setting(pair):
    plant(pair.a, "beta", 1, b"junk")
    link = fs.FsTransport(pair.b, pair.a.home, "alpha", pair.prims, strike_passes=1)
    assert len(link.pull(0)) == 1


# --- doctrine pins ----------------------------------------------------------------

def _tree(name):
    return ast.parse((BIN / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["fleet_msg_fs.py", "fleet_msg_rules.py"])
def test_no_fleet_import_no_destructive_call_stdlib_only(name):
    tree = _tree(name)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    local = {p.stem for p in BIN.glob("*.py")}
    assert not ({"fleet", "fleet_lock", "fleet_mailman", "fleet_platform"} & imported)
    assert imported & local <= {"fleet_msg_core", "fleet_msg_transport"}
    destructive = {"unlink", "remove", "rmdir", "rmtree", "replace", "rename",
                   "removedirs", "truncate", "write_text", "write_bytes"}
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (destructive & names)
    text = (BIN / name).read_text(encoding="utf-8")
    for needle in ("registry.json", "load_registry", "save_registry", "fleet.lock"):
        assert needle not in text.replace("`fleet.lock`", "").replace("no `fleet.lock`", "")
