"""`fleet msg compact` and the `purge` seam (spec §6; plan PR 10)."""
import ast
import json
import os
import time
from pathlib import Path

import pytest

import fleet
import fleet_msg
import fleet_msg_core as core

BIN = Path(__file__).resolve().parents[1] / "bin"
DAY = 86400.0
NOW = 1_800_000_000.0     # fixed "now"; files are aged by os.utime


def make_store(tmp_path, **over):
    return core.Store(tmp_path / "home", "alpha", clock=lambda: NOW, **over)


def env(n=1, frm="lane-a@alpha", to="lane-b@alpha"):
    draft = core.make_draft(frm, to, f"body {n}", from_auth={"method": "lane-registry", "detail": "t"},
                            sent_at=core.iso_utc(NOW))
    return core.validate(dict(draft, seq=n))


def age(path, days):
    t = NOW - days * DAY
    os.utime(path, (t, t))


def deliver(store, n=1, days_old=0, acked=False):
    e = env(n)
    core.publish(store, "lane-b", e)
    if acked:
        core.move(store, "lane-b", e["id"], "new", "cur")
        core.move(store, "lane-b", e["id"], "cur", "done")
    for p in (store.spool("lane-b", "done") / f"{e['id']}.json",
              store.spool("lane-b", "new") / f"{e['id']}.json", store.marker(e["id"])):
        if p.exists():
            age(p, days_old)
    return e["id"]


def tree_files(store):
    """Every regular file under state/msg, by name, excluding locks and tmp."""
    out = []
    for root, _dirs, files in os.walk(store.root):
        if "locks" in Path(root).relative_to(store.root).parts:
            continue
        out += [Path(root) / f for f in files]
    return out


def copies(store, msg_id):
    return [p for p in tree_files(store) if p.name == f"{msg_id}.json"]


def test_old_acked_message_moves_to_archive_and_keeps_marker(tmp_path):
    store = make_store(tmp_path)
    old = deliver(store, 1, days_old=30 + 100 / DAY, acked=True)   # past `days`, inside the marker bound
    fresh = deliver(store, 2, days_old=1, acked=True)
    counts = core.compact(store)
    assert counts["done"] == 1
    [copy] = copies(store, old)
    assert "archive" in copy.parts and "done" in copy.parts
    assert store.marker(old).exists()          # dedup proof outlives the message
    assert [p for p in copies(store, fresh)][0].parent == store.spool("lane-b", "done")


def test_done_without_marker_is_not_archived(tmp_path):
    store = make_store(tmp_path)
    mid = deliver(store, 1, days_old=60, acked=True)
    os.unlink(store.marker(mid))               # test fixture, not product code
    core.compact(store)
    [copy] = copies(store, mid)
    assert copy.parent == store.spool("lane-b", "done")


def test_unread_and_unacked_stay_put(tmp_path):
    store = make_store(tmp_path)
    unread = deliver(store, 1, days_old=90)
    read = deliver(store, 2, days_old=90)
    core.move(store, "lane-b", read, "new", "cur")
    age(store.spool("lane-b", "cur") / f"{read}.json", 90)
    core.compact(store)
    assert copies(store, unread)[0].parent == store.spool("lane-b", "new")
    assert copies(store, read)[0].parent == store.spool("lane-b", "cur")
    assert store.marker(unread).exists() and store.marker(read).exists()


def test_old_marker_archived_only_when_message_is_in_no_spool(tmp_path):
    store = make_store(tmp_path)
    mid = deliver(store, 1, days_old=60, acked=True)
    core.compact(store)                        # done first, then the marker, same run
    assert not store.marker(mid).exists()
    archived = [p for p in tree_files(store) if p.name == mid and "seen" in p.parts]
    assert len(archived) == 1 and "archive" in archived[0].parts


def test_rejected_and_outbox_sent_archived(tmp_path):
    store = make_store(tmp_path)
    raw = b"not json"
    path = core.reject(store, raw, "schema")
    age(path, 45)
    q = store.outbox("beta", "q")
    q.mkdir(parents=True)
    entry = f"{1:012d}-{core.new_id()}.json"
    (q / entry).write_bytes(b"{}")
    core.outbox_commit(store, "beta", [entry.split("-")[1][:-5]])
    age(store.outbox("beta", "sent") / entry, 45)
    counts = core.compact(store)
    assert counts["rejected"] == 1 and counts["sent"] == 1
    assert not path.exists()
    assert list((store.root / "archive").rglob(path.name))
    assert list((store.root / "archive").rglob(entry))


def test_ledger_rotated_whole_and_recent_lines_kept(tmp_path):
    clock = {"t": NOW - 40 * DAY}
    store = make_store(tmp_path)
    old_store = core.Store(store.home, "alpha", clock=lambda: clock["t"])
    old_store.ledger("delivered", id="a" * 32)
    clock["t"] = NOW - DAY
    old_store.ledger("delivered", id="b" * 32)
    core.compact(store)
    live = store.ledger_path.read_text().splitlines()
    assert any("b" * 32 in line for line in live)
    assert not any("a" * 32 in line for line in live if '"compacted"' not in line)
    segs = list((store.root / "archive").rglob("ledger-*.jsonl"))
    assert len(segs) == 1
    text = segs[0].read_text()
    assert "a" * 32 in text and "b" * 32 in text       # nothing dropped
    core.compact(store)                                 # idempotent: no second rotation
    assert len(list((store.root / "archive").rglob("ledger-*.jsonl"))) == 1


class Crash(Exception):
    pass


@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_crash_mid_compact_leaves_every_message_in_exactly_one_place(tmp_path, fail_at):
    calls = {"n": 0, "armed": True}

    def fault(point):
        if point == "compact-move" and calls["armed"]:
            calls["n"] += 1
            if calls["n"] == fail_at:
                raise Crash

    store = make_store(tmp_path, fault=fault)
    ids = [deliver(store, n, days_old=50, acked=True) for n in range(1, 4)]
    with pytest.raises(Crash):
        core.compact(store)
    for mid in ids:
        assert len(copies(store, mid)) == 1
    calls["armed"] = False
    core.compact(store)
    for mid in ids:
        [copy] = copies(store, mid)
        assert "archive" in copy.parts


def test_crash_after_ledger_rotation_is_finished_by_next_compact(tmp_path):
    clock = {"t": NOW - 40 * DAY}
    writer = core.Store(tmp_path / "home", "alpha", clock=lambda: clock["t"])
    writer.ledger("delivered", id="a" * 32)
    clock["t"] = NOW - DAY
    writer.ledger("delivered", id="b" * 32)

    def fault(point):
        if point == "compact-seeded":
            raise Crash

    with pytest.raises(Crash):
        core.compact(make_store(tmp_path, fault=fault))
    seg = next((tmp_path / "home" / "state" / "msg" / "archive").rglob("ledger-*.jsonl"))
    assert not seg.with_name(seg.name + ".seeded").exists()
    core.compact(make_store(tmp_path))                  # finishes the seeding
    assert seg.with_name(seg.name + ".seeded").exists()
    assert writer.ledger_path.read_text().count("b" * 32) == 1     # never twice


def test_compact_refuses_bad_days(tmp_path):
    with pytest.raises(core.StoreError):
        core.compact(make_store(tmp_path), days=0)


# --- purge ------------------------------------------------------------------

def _archived_month(store, month):
    d = store.root / "archive" / month
    d.mkdir(parents=True)
    (d / "x.json").write_text("{}")
    return d


@pytest.mark.parametrize("config", [
    {}, {"purge_enabled": False, "purge_after_days": 30},
    {"purge_enabled": "yes", "purge_after_days": 30}, {"purge_enabled": 1, "purge_after_days": 30},
    {"purge_enabled": True}, {"purge_enabled": True, "purge_after_days": 0},
    {"purge_enabled": True, "purge_after_days": True},
])
def test_purge_refuses_unless_enabled(tmp_path, config):
    store = make_store(tmp_path)
    d = _archived_month(store, "200001")
    with pytest.raises(core.StoreError):
        core.purge(store, config=config)
    assert (d / "x.json").exists()


def test_purge_removes_only_old_whole_months_when_enabled(tmp_path):
    store = make_store(tmp_path)
    old = _archived_month(store, "200001")
    cur = _archived_month(store, time.strftime("%Y%m", time.gmtime(NOW)))
    (store.root / "archive" / "spool-x-1").mkdir()
    removed = core.purge(store, config={"purge_enabled": True, "purge_after_days": 90})
    assert removed == ["200001"] and not old.exists() and cur.exists()
    assert (store.root / "archive" / "spool-x-1").exists()


def test_compact_and_status_never_purge(tmp_path):
    store = make_store(tmp_path)
    d = _archived_month(store, "200001")
    core.compact(store)
    assert (d / "x.json").exists()


def test_purge_is_the_only_delete_seam():
    """Source scan: unlink/remove/rmtree/rmdir appear only in `_write_new`
    (the private tmp name of a hard-linked file) and `purge`."""
    deleters = {"unlink", "remove", "rmdir", "rmtree", "removedirs", "truncate"}
    found = set()
    for path in sorted(BIN.glob("fleet_msg*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Attribute) and node.attr in deleters:
                        found.add((path.name, fn.name, node.attr))
    assert {(n, f) for n, f, _ in found} <= {("fleet_msg_core.py", "_write_new"),
                                             ("fleet_msg_core.py", "purge")}, found
    assert ("fleet_msg_core.py", "purge", "rmtree") in found


# --- the verb and the windowed history ---------------------------------------

def test_verb_compact_runs_and_prints_counts(tmp_path, monkeypatch, capsys):
    h = tmp_path / "vhome"
    (h / "state").mkdir(parents=True)
    (h / "state" / "fleet.json").write_text('{"workers": {}}')
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    assert fleet.main(["--fleet-home", str(h), "msg", "init", "--site", "alpha"]) == 0
    capsys.readouterr()
    assert fleet.main(["--fleet-home", str(h), "msg", "compact"]) == 0
    assert capsys.readouterr().out.startswith("COMPACTED ")


def test_history_reads_the_tail_not_the_whole_ledger(tmp_path):
    store = make_store(tmp_path)
    store._ensure_dir(store.root)
    stale = core.iso_utc(NOW - 10 * DAY)
    lines = [json.dumps({"ts": stale, "event": "delivered", "from": "lane-a@alpha",
                         "to": "lane-b@alpha", "kind": "note", "i": i}) + "\n"
             for i in range(20000)]
    recent = core.iso_utc(NOW - 60)
    lines.append(json.dumps({"ts": recent, "event": "delivered", "from": "lane-a@alpha",
                             "to": "lane-b@alpha", "kind": "note"}) + "\n")
    store.ledger_path.write_text("".join(lines))
    tail = list(fleet_msg._ledger_tail(store, NOW - 3600))
    assert len(tail) < 2000 and tail[-1]["ts"] == recent       # a block, not 20000 lines
    sends = list(fleet_msg._ledger_sends(store, NOW))
    assert len(sends) == 1


def test_ledger_tail_handles_lines_across_block_boundaries(tmp_path):
    store = make_store(tmp_path)
    store._ensure_dir(store.root)
    ts = core.iso_utc(NOW - 10)
    lines = [json.dumps({"ts": ts, "event": "delivered", "n": i, "pad": "x" * 97}) + "\n"
             for i in range(2000)]
    store.ledger_path.write_text("".join(lines))
    got = [r["n"] for r in fleet_msg._ledger_tail(store, NOW - 3600)]
    assert got == list(range(2000))


# --- w509: review of PR 79 ----------------------------------------------------

def _outside(tmp_path, *names):
    out = tmp_path / "outside"
    out.mkdir()
    for name in names:
        (out / name).write_text("{}")
        age(out / name, 60)
    return out


def _archive_files(store):
    return [p for p in (store.root / "archive").rglob("*") if p.is_file()]


def test_p1_symlinked_rejected_dir_is_skipped(tmp_path):
    store = make_store(tmp_path)
    store.root.mkdir(parents=True)
    out = _outside(tmp_path, "important.json")
    os.symlink(out, store.rejected_dir)
    counts = core.compact(store)
    assert (out / "important.json").exists() and not _archive_files(store)
    assert counts["skipped_symlink"] >= 1


def test_p1_symlinked_spool_done_dir_is_skipped(tmp_path):
    store = make_store(tmp_path)
    mid = deliver(store, 1, days_old=50, acked=True)
    done = store.spool("lane-b", "done")
    out = tmp_path / "outside"
    os.rename(done, out)
    os.symlink(out, done)
    counts = core.compact(store)
    assert (out / f"{mid}.json").exists() and not _archive_files(store)
    assert counts["skipped_symlink"] >= 1


def test_p1_symlinked_outbox_sent_dir_is_skipped(tmp_path):
    store = make_store(tmp_path)
    entry = f"{1:012d}-{core.new_id()}.json"
    out = _outside(tmp_path, entry)
    site_dir = store.root / "outbox" / "beta"
    site_dir.mkdir(parents=True)
    os.symlink(out, site_dir / "sent")
    counts = core.compact(store)
    assert (out / entry).exists() and not _archive_files(store)
    assert counts["skipped_symlink"] >= 1


def test_p1_symlinked_seen_shard_is_skipped(tmp_path):
    store = make_store(tmp_path)
    msg_id = core.new_id()
    out = _outside(tmp_path, msg_id)
    (store.root / "seen").mkdir(parents=True)
    os.symlink(out, store.root / "seen" / msg_id[:2])
    counts = core.compact(store)
    assert (out / msg_id).exists() and not _archive_files(store)
    assert counts["skipped_symlink"] >= 1


def test_p2_1_ledger_lock_is_held_across_rotation_and_reseed(tmp_path):
    clock = {"t": NOW - 40 * DAY}
    writer = core.Store(tmp_path / "home", "alpha", clock=lambda: clock["t"])
    writer.ledger("delivered", id="a" * 32)
    clock["t"] = NOW - DAY
    writer.ledger("delivered", id="b" * 32)
    seen = {}

    def fault(point):
        if point == "compact-rotated":      # between rotation and reseed
            with pytest.raises(core.StoreError, match="lock timeout"):
                core.Store(tmp_path / "home", "alpha", lock_timeout=0).ledger("delivered", id="c" * 32)
            seen["held"] = True

    core.compact(make_store(tmp_path, fault=fault))
    assert seen == {"held": True}
    assert writer.ledger_path.read_text().count("b" * 32) == 1


def test_p2_1_rename_failure_reports_not_rotated(tmp_path, monkeypatch):
    clock = {"t": NOW - 40 * DAY}
    writer = core.Store(tmp_path / "home", "alpha", clock=lambda: clock["t"])
    writer.ledger("delivered", id="a" * 32)
    real = os.replace

    def replace(src, dst):
        if Path(dst).name.startswith("ledger-"):
            raise PermissionError("in use")
        return real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    counts = core.compact(make_store(tmp_path))
    assert counts["ledger_rotated"] == 0
    assert "a" * 32 in writer.ledger_path.read_text()


def test_p2_2_reseed_keeps_the_live_ledger_ordered_for_the_tail(tmp_path):
    clock = {"t": NOW - 40 * DAY}
    writer = core.Store(tmp_path / "home", "alpha", clock=lambda: clock["t"])
    writer.ledger("delivered", id="a" * 32)
    for n in range(200):                              # 5 days old: recent to compact, old to the tail
        clock["t"] = NOW - 5 * DAY + n
        writer.ledger("delivered", id=f"{n:032x}", pad="x" * 500,
                      **{"from": "lane-a@alpha", "to": "lane-old@alpha"})

    def crash(point):
        if point == "compact-rotated":
            raise Crash

    with pytest.raises(Crash):
        core.compact(make_store(tmp_path, fault=crash))
    clock["t"] = NOW - 60
    writer.ledger("delivered", id="f" * 32, **{"from": "lane-a@alpha", "to": "lane-new@alpha"})
    core.compact(make_store(tmp_path))                # reseeds the old lines
    store = make_store(tmp_path)
    assert [row[2] for row in fleet_msg._ledger_sends(store)] == ["lane-new@alpha"]
    stamps = [json.loads(line)["ts"] for line in store.ledger_path.read_text().splitlines()]
    assert stamps == sorted(stamps)


def test_p2_3_compact_writes_the_hwm_mark_before_emptying_done(tmp_path):
    store = make_store(tmp_path)
    for n, days in ((1, 50), (2, 50), (3, 1)):
        deliver(store, n, days_old=days, acked=True)
    assert not (store.root / "hwm" / "lane-b.json").exists()
    core.compact(store, seed_marks=fleet_msg.hwm_seed_locked)
    assert (store.root / "hwm" / "lane-b.json").exists()
    assert fleet_msg._gaps(store, "lane-b") == []


def _purge(store):
    return core.purge(store, config={"purge_enabled": True, "purge_after_days": 90})


def test_p2_4_purge_skips_month_with_unread_or_unacked_archived_spool(tmp_path):
    store = make_store(tmp_path)
    for state in ("new", "cur"):
        month = store.root / "archive" / ("200001" if state == "new" else "200002")
        (month / "spool-x-1" / state).mkdir(parents=True)
        (month / "spool-x-1" / state / "m.json").write_text("{}")
    safe = store.root / "archive" / "200003"
    (safe / "spool-y-1" / "done").mkdir(parents=True)
    (safe / "spool-y-1" / "new").mkdir()
    (safe / "spool-y-1" / "done" / "m.json").write_text("{}")
    assert _purge(store) == ["200003"]
    assert (store.root / "archive" / "200001").exists()
    assert (store.root / "archive" / "200002").exists() and not safe.exists()


def test_p2_4_purge_skips_month_with_unseeded_ledger_segment(tmp_path):
    store = make_store(tmp_path)
    for month, seeded in (("200001", False), ("200002", True)):
        d = store.root / "archive" / month
        d.mkdir(parents=True)
        seg = d / "ledger-20000101000000-0123abcd.jsonl"
        seg.write_text("{}\n")
        if seeded:
            seg.with_name(seg.name + ".seeded").write_text("")
    assert _purge(store) == ["200002"]
    assert (store.root / "archive" / "200001").exists()


def test_p2_4_purge_refuses_symlinked_archive(tmp_path):
    store = make_store(tmp_path)
    out = tmp_path / "elsewhere"
    (out / "200001").mkdir(parents=True)
    (out / "200001" / "x.json").write_text("{}")
    store.root.mkdir(parents=True)
    os.symlink(out, store.root / "archive")
    with pytest.raises(core.StoreError, match="archive"):
        _purge(store)
    assert (out / "200001" / "x.json").exists()
