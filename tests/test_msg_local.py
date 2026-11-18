"""`fleet msg` in one home (spec docs/specs/messaging.md §3, §6, §8, §10;
plan PR 2, T7-T10)."""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet
import fleet_msg

BIN = Path(__file__).resolve().parents[1] / "bin"
SID_OLD, SID_NEW = "sid-lane-old", "sid-lane-new"
SUP_SID, NONCE = "sid-supervisor", "nonce-value-not-for-the-ledger"
THREAD_OLD, THREAD_NEW = "thread-old", "thread-new"


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lane(sid=SID_OLD, **over):
    row = {"session_id": sid, "dispatch_kind": "bg", "cwd": "/w", "created": _iso()}
    row.update(over)
    return row


def _codex_lane(thread):
    return {"session_id": None, "substrate": "codex", "dispatch_kind": "codex-app-server",
            "codex_thread_id": thread, "cwd": "/w", "created": _iso()}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "state").mkdir(parents=True)
    (h / "supervisor").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "MCX_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    registry(h, {"lane-a": _lane()})
    assert msg(h, "init", "--site", "alpha") == 0
    return h


def registry(h, workers):
    (h / "state" / "fleet.json").write_text(json.dumps({"workers": workers}), encoding="utf-8")


def claim(h, sid=SUP_SID):
    (h / "supervisor" / "INCARNATION").write_text(json.dumps({
        "incarnation_id": "inc-1", "lineage_id": "lin-1", "session_id": sid,
        "state": "held", "nonce_hash": fleet.nonce_digest(NONCE), "nonce_seq": 7,
        "heartbeat_at": _iso()}), encoding="utf-8")


def msg(h, *argv):
    return fleet.main(["--fleet-home", str(h), "msg", *argv])


def as_body(monkeypatch, sid=None, thread=None):
    for var, value in (("CLAUDE_CODE_SESSION_ID", sid), ("CODEX_THREAD_ID", thread)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)


def sent_id(capsys):
    out = capsys.readouterr().out.split()
    assert out[0] in ("DELIVERED", "QUEUED"), out
    return out[1]


def spool(h, name, state):
    d = h / "state" / "msg" / "spool" / name / state
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def ledger(h):
    path = h / "state" / "msg" / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def tree(h):
    root = h / "state" / "msg"
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


# --- T7 / T8: the lane identity follows the registry row ----------------------

def test_t7_fork_steer_new_sid_holds_old_body_fails(home, monkeypatch, capsys):
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "please rebase", "--from", "operator") == 0
    msg_id = sent_id(capsys)
    registry(home, {"lane-a": _lane(SID_NEW)})          # fork-steer restamps the row
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "lane-a") == 1
    assert "does not hold 'lane-a'" in capsys.readouterr().err
    assert spool(home, "lane-a", "new") == [msg_id]
    as_body(monkeypatch, sid=SID_NEW)
    assert msg(home, "inbox") == 0                      # default NAME = own lane
    assert "please rebase" in capsys.readouterr().out
    assert spool(home, "lane-a", "cur") == [msg_id]


def test_t8_respawn_and_codex_thread_rotation_follow_with_no_rebind(home, monkeypatch, capsys):
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "one", "--from", "operator") == 0
    registry(home, {"lane-a": _lane(SID_NEW, created=_iso())})    # respawn
    as_body(monkeypatch, sid=SID_NEW)
    assert msg(home, "inbox", "lane-a") == 0
    capsys.readouterr()
    registry(home, {"lane-a": _codex_lane(THREAD_OLD)})
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "two", "--from", "operator") == 0
    capsys.readouterr()
    registry(home, {"lane-a": _codex_lane(THREAD_NEW)})           # thread rotation
    as_body(monkeypatch, thread=THREAD_OLD)
    assert msg(home, "inbox", "lane-a") == 1
    as_body(monkeypatch, thread=THREAD_NEW)
    assert msg(home, "inbox", "lane-a") == 0
    assert "two" in capsys.readouterr().out
    assert msg(home, "whois", "lane-a") == 0
    assert f"holder=codex-thread:{THREAD_NEW}" in capsys.readouterr().out


# --- T9: restart and reboot -------------------------------------------------

def test_t9_new_cur_and_outbox_survive_a_restart(home, monkeypatch, capsys):
    (home / "state" / "msg" / "peers.json").write_text(
        json.dumps({"beta": {"transport": "fs"}}), encoding="utf-8")
    as_body(monkeypatch, sid=SID_OLD)
    for text in ("first", "second"):
        assert msg(home, "send", "supervisor", text) == 0
    assert msg(home, "send", "lane-a", "self note") == 0
    assert msg(home, "inbox") == 0                       # lane-a: new -> cur
    assert msg(home, "send", "hub@beta", "remote") == 0
    assert capsys.readouterr().out.count("QUEUED") == 1
    before = tree(home)
    # A restart or reboot keeps nothing in memory: every fact is on disk.
    assert msg(home, "queue", "--json") == 0
    q = json.loads(capsys.readouterr().out)
    rows = {r["identity"]: r for r in q["identities"]}
    assert rows["supervisor@alpha"]["unread"] == 2
    assert rows["lane-a@alpha"]["unacked"] == 1
    assert q["outbox"] == [{"site": "beta", "depth": 1, "oldest_s": q["outbox"][0]["oldest_s"],
                            "warn": False}]
    assert tree(home) == before                          # queue writes nothing


def test_send_to_unknown_site_or_identity_refused(home, monkeypatch, capsys):
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "hub@beta", "x") == 1
    assert msg(home, "send", "nobody", "x") == 1
    err = capsys.readouterr().err
    assert "unknown site 'beta'" in err and "unknown identity 'nobody'" in err


# --- T10: holder check on read and ack; ledger names the reader ------------------

def test_t10_lane_cannot_read_supervisor_queue_but_may_peek(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "supervisor", "done: PR open") == 0
    msg_id = sent_id(capsys)
    assert msg(home, "inbox", "supervisor") == 1
    assert "does not hold 'supervisor'" in capsys.readouterr().err
    before = tree(home)
    assert msg(home, "inbox", "supervisor", "--peek") == 0
    assert "done: PR open" in capsys.readouterr().out
    assert tree(home) == before                          # peek moves and logs nothing
    assert msg(home, "ack", msg_id) == 1                 # lane holds no such message
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "inbox") == 0
    out = capsys.readouterr().out
    assert f"VERIFIED lane-a@alpha lane-registry via local/alpha" in out
    reads = [r for r in ledger(home) if r["event"] == "read"]
    assert reads == [dict(reads[0], id=msg_id, reader=f"supervisor-sid/session:{SUP_SID}")]
    assert msg(home, "inbox", "--all", "--json") == 0
    entries = json.loads(capsys.readouterr().out)["messages"]
    assert [(e["id"], e["state"], e["reader"]) for e in entries] == [
        (msg_id, "cur", f"supervisor-sid/session:{SUP_SID}")]
    assert msg(home, "ack", msg_id) == 0
    assert spool(home, "supervisor", "done") == [msg_id]
    assert [r["event"] for r in ledger(home) if r.get("id") == msg_id] == [
        "delivered", "read", "acked"]
    assert msg(home, "status", msg_id) == 0
    assert "spool/supervisor/done" in capsys.readouterr().out


def test_t10_two_bodies_one_identity_only_the_registry_holder_reads(home, monkeypatch, capsys):
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "x", "--from", "operator") == 0
    msg_id = sent_id(capsys)
    as_body(monkeypatch, sid="sid-impostor")
    assert msg(home, "inbox", "lane-a") == 1
    assert msg(home, "ack", msg_id) == 1
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "ack", msg_id) == 0                 # ack from new: read then acked
    assert [r["event"] for r in ledger(home) if r.get("id") == msg_id] == [
        "delivered", "read", "acked"]


# --- caller methods (§10) ---------------------------------------------------

def test_supervisor_task_needs_a_live_nonce_and_never_stores_it(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "send", "lane-a", "do x", "--kind", "task") == 1
    assert "needs --nonce" in capsys.readouterr().err
    assert msg(home, "send", "lane-a", "do x", "--kind", "task", "--nonce", "wrong") == 1
    assert msg(home, "send", "lane-a", "do x", "--kind", "task", "--nonce", NONCE) == 0
    msg_id = sent_id(capsys)
    raw = (home / "state" / "msg" / "spool" / "lane-a" / "new" / f"{msg_id}.json").read_bytes()
    env = json.loads(raw)
    assert env["from"] == "supervisor@alpha"
    assert env["from_auth"] == {"method": "supervisor-nonce",
                                "detail": f"nonce_seq=7 sha={fleet.nonce_digest(NONCE)[:8]}"}
    store_bytes = b"".join(v for v in tree(home).values() if v)
    assert NONCE.encode() not in store_bytes
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "--json") == 0
    assert json.loads(capsys.readouterr().out)["messages"][0]["shown_as"] == "task"


def test_note_from_supervisor_sid_and_lane_task_is_not_direction(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "send", "lane-a", "fyi") == 0
    assert "(supervisor-sid)" in capsys.readouterr().out
    registry(home, {"lane-a": _lane(), "lane-b": _lane("sid-b")})
    as_body(monkeypatch, sid="sid-b")
    assert msg(home, "send", "lane-a", "do y", "--kind", "task") == 0
    capsys.readouterr()
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "--json") == 0
    shown = {e["from"]: e["shown_as"] for e in json.loads(capsys.readouterr().out)["messages"]}
    assert shown == {"supervisor@alpha": "note", "lane-b@alpha": "remote-task"}


def test_interface_registration_and_unverified_from(home, monkeypatch, capsys):
    (home / "state" / "interface-session").write_text("sid-iface\n", encoding="utf-8")
    as_body(monkeypatch, sid="sid-iface")
    assert msg(home, "send", "lane-a", "hi") == 0
    assert "from interface (interface-registration)" in capsys.readouterr().out
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "lane-a", "spoof", "--from", "interface") == 0
    assert "(unverified)" in capsys.readouterr().out
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "anon") == 1      # no identity, no --from


def test_reply_threads_and_size_bound(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "supervisor", "question") == 0
    root = sent_id(capsys)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "send", "lane-a", "answer", "--re", root) == 0
    reply = sent_id(capsys)
    env = json.loads((home / "state" / "msg" / "spool" / "lane-a" / "new"
                      / f"{reply}.json").read_text())
    assert (env["re"], env["thread"], env["hop"]) == (root, root, 1)
    assert env["path"] == ["lane-a@alpha", "supervisor@alpha"]
    assert msg(home, "send", "lane-a", " ".join(["w"] * 121)) == 1
    assert "refused: size" in capsys.readouterr().err


def test_send_to_archived_lane_is_rejected_retired(home, monkeypatch, capsys):
    registry(home, {"lane-a": _lane(archived_at=_iso())})
    as_body(monkeypatch)
    assert msg(home, "send", "lane-a", "x", "--from", "operator") == 1
    assert "rejected: retired" in capsys.readouterr().err


# --- init, views, doctrine ---------------------------------------------------

def test_init_is_idempotent_and_never_relabels(home, capsys):
    assert msg(home, "init", "--site", "alpha") == 0
    assert msg(home, "init", "--site", "other") == 1
    assert json.loads((home / "state" / "msg" / "site.json").read_text()) == {"site": "alpha"}


def test_init_refuses_a_label_another_listed_home_uses(home, tmp_path, monkeypatch, capsys):
    other = tmp_path / "other"
    (other / "state").mkdir(parents=True)
    registry(other, {})
    listed = tmp_path / "fleet-homes.list"
    listed.write_text(f"{home}\n{other}\n", encoding="utf-8")
    monkeypatch.setattr(fleet, "homes_list_path", lambda: listed)
    assert fleet.read_homes_list()["members"]
    assert fleet.main(["--fleet-home", str(other), "msg", "init", "--site", "alpha"]) == 1
    assert "used by listed home" in capsys.readouterr().err
    assert not (other / "state" / "msg" / "site.json").exists()


def test_verbs_need_a_site_and_an_explicit_home(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "bare"
    (bare / "state").mkdir(parents=True)
    registry(bare, {})
    assert fleet.main(["msg", "queue"]) == 1
    assert "explicit --fleet-home" in capsys.readouterr().err
    assert fleet.main(["--fleet-home", str(bare), "msg", "queue"]) == 1
    assert "msg init --site" in capsys.readouterr().err


def test_read_verbs_write_nothing(home, monkeypatch, capsys):
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "supervisor", "x") == 0
    msg_id = sent_id(capsys)
    before = tree(home)
    for argv in (("status", msg_id), ("queue",), ("ids",), ("whois", "lane-a"),
                 ("inbox", "supervisor", "--peek", "--all")):
        assert msg(home, *argv) == 0
    assert tree(home) == before


def test_inbox_wait_times_out_with_exit_3(home, monkeypatch, capsys):
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "--wait", "0") == 3
    assert "TIMEOUT" in capsys.readouterr().out


def test_fleet_msg_imports_no_fleet_and_no_lock():
    tree_ = ast.parse((BIN / "fleet_msg.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not imported & {"fleet", "fleet_lock"}
    source = (BIN / "fleet_msg.py").read_text(encoding="utf-8")
    assert "fleet_lock" not in source and "save_registry" not in source
    assert "unlink(" not in source
