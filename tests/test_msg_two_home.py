"""`fleet msg` wiring across two homes (spec docs/specs/messaging.md §8.1, §9,
§10, §11; plan PR 6, T13, T14, T14b, T14c, T10b and the PR 2 review
deferrals)."""
import inspect
import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet
import fleet_msg

SID_A, SID_B, SUP_SID = "sid-lane-a", "sid-lane-b", "sid-supervisor"
NONCE = "nonce-value-not-for-the-ledger"


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lane(sid, **over):
    row = {"session_id": sid, "dispatch_kind": "bg", "cwd": "/w", "created": _iso()}
    row.update(over)
    return row


def _codex_lane(thread):
    return {"session_id": None, "substrate": "codex", "dispatch_kind": "codex-app-server",
            "codex_thread_id": thread, "cwd": "/w", "created": _iso()}


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


def outbox(h, site, state):
    d = h / "state" / "msg" / "outbox" / site / state
    return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []


def peers(h, site, other, **extra):
    (h / "state" / "msg" / "peers.json").write_text(
        json.dumps({site: {"transport": "fs", "home": str(other), **extra}}), encoding="utf-8")


def config(h, **values):
    (h / "state" / "msg" / "config.json").write_text(json.dumps(values), encoding="utf-8")


def inbox_json(h, name, capsys):
    capsys.readouterr()
    assert msg(h, "inbox", name, "--peek", "--json") == 0
    return json.loads(capsys.readouterr().out)


def tree_bytes(*homes):
    out = b""
    for h in homes:
        for p in sorted((h / "state").rglob("*")):
            if p.is_file() and "msg" in p.parts or p.name.endswith("rejections.jsonl"):
                out += p.read_bytes()
    return out


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Home A (site alpha) and home B (site beta), each other's fs peer."""
    homes = {}
    for key, site in (("a", "alpha"), ("b", "beta")):
        h = tmp_path / site
        (h / "state").mkdir(parents=True)
        (h / "supervisor").mkdir()
        homes[key] = h
    monkeypatch.setattr(fleet, "FLEET_HOME", homes["a"])
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "MCX_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    registry(homes["a"], {"lane-a": _lane(SID_A), "lane-b": _lane(SID_B)})
    registry(homes["b"], {"lane-x": _lane("sid-lane-x")})
    assert msg(homes["a"], "init", "--site", "alpha") == 0
    assert msg(homes["b"], "init", "--site", "beta") == 0
    peers(homes["a"], "beta", homes["b"])
    peers(homes["b"], "alpha", homes["a"])
    return homes["a"], homes["b"]


# --- T13 ---------------------------------------------------------------------

def test_t13_two_homes_delivery_receipt_outbox_drains_fifo_gaps(two, monkeypatch, capsys):
    a, b = two
    as_body(monkeypatch, sid=SID_A)
    ids = []
    for text in ("one", "two", "three"):
        assert msg(a, "send", "supervisor@beta", text) == 0
        out = capsys.readouterr().out
        assert out.startswith("QUEUED")
        ids.append(out.split()[1])
    assert len(outbox(a, "beta", "q")) == 3
    # The second envelope is lost in transit: B must show the gap, not block.
    lost = next(p for p in (a / "state/msg/outbox/beta/q").iterdir() if ids[1] in p.name)
    held = lost.read_bytes()
    lost.unlink()                                   # test-only: simulate loss
    assert msg(b, "sync", "--peer", "alpha") == 0
    assert "accepted=2" in capsys.readouterr().out
    shown = inbox_json(b, "supervisor", capsys)
    assert [m["seq"] for m in shown["messages"]] == [1, 3]       # FIFO per sender
    assert shown["gaps"] == [{"from": "lane-a@alpha", "missing": [[2, 2]]}]
    # The receipts flow back; A's outbox drains for the delivered ones.
    assert msg(a, "sync", "--peer", "beta") == 0
    capsys.readouterr()
    assert len(outbox(a, "beta", "q")) == 0 and len(outbox(a, "beta", "sent")) == 2
    receipts = [json.loads(p.read_text()) for p in
                (a / "state/msg/spool/lane-a/new").glob("*.json")]
    assert {r["body"] for r in receipts} == {"delivered"}
    assert all(r["kind"] == "receipt" and r["from"] == "supervisor@beta" for r in receipts)
    # The lost one is re-sent, arrives, and the gap closes.
    lost.write_bytes(held)
    assert msg(b, "sync", "--peer", "alpha") == 0
    capsys.readouterr()
    assert inbox_json(b, "supervisor", capsys)["gaps"] == []
    assert msg(a, "sync", "--peer", "beta") == 0
    capsys.readouterr()
    assert outbox(a, "beta", "q") == []


def test_inbox_pulls_from_fs_peers_but_peek_writes_nothing(two, monkeypatch, capsys):
    a, b = two
    as_body(monkeypatch, sid=SID_A)
    assert msg(a, "send", "lane-x@beta", "hello") == 0
    capsys.readouterr()
    as_body(monkeypatch, sid="sid-lane-x")
    assert msg(b, "inbox", "lane-x", "--peek") == 0
    assert "EMPTY" in capsys.readouterr().out and spool(b, "lane-x", "new") == []
    assert msg(b, "inbox", "lane-x") == 0
    assert "hello" in capsys.readouterr().out
    assert len(spool(b, "lane-x", "cur")) == 1


def test_sync_of_a_missing_peer_home_fails_loudly(two, capsys):
    a, b = two
    peers(a, "beta", a.parent / "nowhere")
    assert msg(a, "sync", "--peer", "beta") == 1
    assert "FAILED beta" in capsys.readouterr().out


# --- rules, notice, drain block ---------------------------------------------

def test_rules_run_inside_send(two, monkeypatch, capsys):
    a, _b = two
    as_body(monkeypatch, sid=SID_A)
    config(a, rate=2)
    assert msg(a, "send", "lane-b", "1") == 0
    assert msg(a, "send", "lane-b", "2") == 0
    capsys.readouterr()
    assert msg(a, "send", "lane-b", "3") == 1
    assert "rate:" in capsys.readouterr().err
    assert len(spool(a, "lane-b", "new")) == 2
    assert fleet_msg.core.Store(a, "alpha").last_seq("lane-a@alpha", "lane-b@alpha") == 2
    assert msg(a, "send", "lane-b", " ".join(["w"] * 121)) == 1
    assert "size" in capsys.readouterr().err


def test_notice_reaches_a_claude_lane_without_a_body(two, monkeypatch, capsys):
    a, _b = two
    as_body(monkeypatch, sid=SID_A)
    assert msg(a, "send", "lane-b", "secret body text") == 0
    msg_id = sent_id(capsys)
    note = (a / "mailbox" / f"{SID_B}.md").read_text()
    assert f"FLEET MSG {msg_id} from lane-a@alpha (lane-registry)" in note
    assert f"--fleet-home {a} msg inbox" in note and "secret body text" not in note
    assert msg(a, "send", "lane-b", "again") == 0                  # one pending notice
    assert (a / "mailbox" / f"{SID_B}.md").read_text() == note


def test_drain_block_lists_unread_for_a_codex_lane_and_marks_nothing(two, monkeypatch,
                                                                     capsys, tmp_path):
    a, _b = two
    registry(a, {"lane-a": _lane(SID_A), "lane-c": _codex_lane("thread-c")})
    as_body(monkeypatch, sid=SID_A)
    assert msg(a, "send", "lane-c", "hi codex") == 0
    msg_id = sent_id(capsys)
    assert not (a / "mailbox").exists()                           # drain-only adapter
    prompt, _claim, _mail = fleet.compose_prompt("lane-c", str(tmp_path), "do the task", None)
    assert "## MESSAGES" in prompt and msg_id in prompt and "hi codex" not in prompt
    assert prompt.index("## MESSAGES") < prompt.index("do the task")
    assert spool(a, "lane-c", "new") == [msg_id]                  # nothing read
    other, _c, _m = fleet.compose_prompt("lane-a", str(tmp_path), "t", None)
    assert "## MESSAGES" not in other


def test_no_message_store_means_no_drain_block(tmp_path, monkeypatch):
    h = tmp_path / "bare"
    (h / "state").mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    prompt, _c, _m = fleet.compose_prompt("lane-a", str(tmp_path), "t", None)
    assert "## MESSAGES" not in prompt


# --- T14 / T14b / T14c --------------------------------------------------------

def test_t14_task_needs_a_nonce_zombie_sid_sends_a_labelled_note(two, monkeypatch, capsys):
    a, _b = two
    claim(a)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(a, "send", "lane-a", "do x", "--kind", "task") == fleet.SUPERVISOR_CONTINUITY_RC
    capsys.readouterr()
    assert spool(a, "lane-a", "new") == []
    assert msg(a, "send", "lane-a", "fyi") == 0                  # same sid, no nonce: a note
    assert "(supervisor-sid)" in capsys.readouterr().out
    shown = inbox_json(a, "lane-a", capsys)["messages"][0]
    assert shown["method"] == "supervisor-sid" and shown["shown_as"] == "note"


def _task_to_beta(a, monkeypatch, capsys, *, as_interface=False):
    if as_interface:
        (a / "state" / "interface-session").write_text("sid-iface\n", encoding="utf-8")
        as_body(monkeypatch, sid="sid-iface")
        argv = ["send", "lane-x@beta", "do it", "--kind", "task"]
    else:
        claim(a)
        as_body(monkeypatch, sid=SUP_SID)
        argv = ["send", "lane-x@beta", "do it", "--kind", "task", "--nonce", NONCE]
    assert msg(a, *argv) == 0
    return sent_id(capsys)


def _shown_in_b(a, b, capsys):
    assert msg(b, "sync", "--peer", "alpha") == 0
    capsys.readouterr()
    return inbox_json(b, "lane-x", capsys)["messages"][-1]


def test_t14b_remote_task_direction_is_decided_by_the_receiver(two, monkeypatch, capsys):
    a, b = two
    _task_to_beta(a, monkeypatch, capsys)
    first = _shown_in_b(a, b, capsys)
    assert first["method"] == "supervisor-nonce" and first["shown_as"] == "remote-task"
    # The same, from a peer the receiver marks direct.
    peers(b, "alpha", a, direct=True)
    _task_to_beta(a, monkeypatch, capsys)
    assert _shown_in_b(a, b, capsys)["shown_as"] == "task"
    # From the Interface of the configured interface site.
    peers(b, "alpha", a)
    config(b, interface_site="alpha")
    _task_to_beta(a, monkeypatch, capsys, as_interface=True)
    assert msg(b, "sync", "--peer", "alpha") == 0
    capsys.readouterr()
    last = next(m for m in inbox_json(b, "lane-x", capsys)["messages"]
                if m["method"] == "interface-registration")
    assert last["shown_as"] == "task"


def test_t14c_no_nonce_value_in_any_envelope_or_ledger(two, monkeypatch, capsys):
    a, b = two
    msg_id = _task_to_beta(a, monkeypatch, capsys)
    assert msg(b, "sync", "--peer", "alpha") == 0
    assert msg(a, "sync", "--peer", "beta") == 0
    capsys.readouterr()
    assert NONCE.encode() not in tree_bytes(a, b)
    env = json.loads(next((a / "state/msg/outbox/beta/sent").glob(f"*{msg_id}.json")).read_text())
    assert re.fullmatch(r"nonce_seq=7 sha=[0-9a-f]{8}", env["from_auth"]["detail"])


# --- PR 2 review deferrals ---------------------------------------------------

def test_unverified_from_has_its_own_seq_gap_and_rule_namespace(two, monkeypatch, capsys):
    a, _b = two
    config(a, rate=2)
    as_body(monkeypatch, sid=SID_B)
    assert msg(a, "send", "lane-a", "real") == 0
    as_body(monkeypatch, sid=SID_A)                              # lane-a spoofs lane-b
    assert msg(a, "send", "lane-a", "spoof 1", "--from", "lane-b") == 0
    assert msg(a, "send", "lane-a", "spoof 2", "--from", "lane-b") == 0
    capsys.readouterr()
    store = fleet_msg.core.Store(a, "alpha")
    assert store.last_seq("lane-b@alpha", "lane-a@alpha") == 1            # real, untouched
    assert store.last_seq("lane-b@alpha", "lane-a@alpha", unverified=True) == 2
    shown = inbox_json(a, "lane-a", capsys)
    assert shown["gaps"] == []
    # The spoof used up its own bound, not lane-b's.
    assert msg(a, "send", "lane-a", "spoof 3", "--from", "lane-b") == 1
    assert "rate:" in capsys.readouterr().err
    as_body(monkeypatch, sid=SID_B)
    assert msg(a, "send", "lane-a", "real 2") == 0
    # A lost spoof is a gap in the spoof namespace, never in the real one.
    capsys.readouterr()
    spoof = next(p for p in (a / "state/msg/spool/lane-a/new").glob("*.json")
                 if json.loads(p.read_text())["seq"] == 1
                 and json.loads(p.read_text())["from_auth"]["method"] == "unverified")
    spoof.unlink()
    gaps = inbox_json(a, "lane-a", capsys)["gaps"]
    assert gaps == [{"from": "lane-b@alpha (unverified)", "missing": [[1, 1]]}]


def test_done_gap_high_water_mark_survives_acked_history_leaving(two, monkeypatch, capsys):
    a, _b = two
    as_body(monkeypatch, sid=SID_A)
    for n in range(4):
        assert msg(a, "send", "lane-b", f"m{n}") == 0
    ids = []
    capsys.readouterr()
    as_body(monkeypatch, sid=SID_B)
    assert msg(a, "inbox") == 0
    capsys.readouterr()
    ids = spool(a, "lane-b", "cur")
    assert msg(a, "ack", *ids) == 0
    capsys.readouterr()
    hwm = json.loads((a / "state/msg/hwm/lane-b.json").read_text())
    assert hwm == {"lane-a@alpha": {"above": [], "upto": 4}}
    for p in (a / "state/msg/spool/lane-b/done").glob("*.json"):
        p.unlink()                                   # test-only: acked history leaves
    as_body(monkeypatch, sid=SID_A)
    assert msg(a, "send", "lane-b", "m4") == 0
    capsys.readouterr()
    assert inbox_json(a, "lane-b", capsys)["gaps"] == []
    # A hole above the mark is still shown.
    store = fleet_msg.core.Store(a, "alpha")
    env = fleet_msg.core.parse(next((a / "state/msg/spool/lane-b/new").glob("*.json")).read_bytes())
    assert env["seq"] == 5
    marks = {}
    fleet_msg._hwm_apply(marks, "lane-a@alpha", 1)
    fleet_msg._hwm_apply(marks, "lane-a@alpha", 3)
    assert marks == {"lane-a@alpha": {"upto": 1, "above": [3]}}
    assert store.site == "alpha"


def test_hwm_is_bounded_and_read_only_verbs_write_no_mark(two, monkeypatch, capsys):
    a, _b = two
    marks = {}
    for seq in range(2, 2 * fleet_msg.HWM_ABOVE_MAX + 2, 2):         # every other seq
        fleet_msg._hwm_apply(marks, "k", seq)
    assert len(marks["k"]["above"]) <= fleet_msg.HWM_ABOVE_MAX
    # One past the bound with a hole after every seq: must terminate (P1-1).
    marks = {}
    for seq in range(2, 2 * (fleet_msg.HWM_ABOVE_MAX + 2) + 2, 2):
        fleet_msg._hwm_apply(marks, "k", seq)
    assert len(marks["k"]["above"]) <= fleet_msg.HWM_ABOVE_MAX
    assert all(s > marks["k"]["upto"] for s in marks["k"]["above"])
    as_body(monkeypatch, sid=SID_A)
    assert msg(a, "send", "lane-b", "x") == 0
    msg_id = sent_id(capsys)
    for argv in (("queue",), ("ids",), ("inbox", "lane-b", "--peek"), ("whois", "lane-b"),
                 ("status", msg_id)):
        assert msg(a, *argv) == 0
    assert not (a / "state/msg/hwm").exists()


@pytest.mark.parametrize("which,kind", [("wrong", "refused"),
                                        ("prior", "superseded-pending"),
                                        ("pending", None)])
def test_refused_nonce_presentation_is_logged_for_doctor(two, monkeypatch, capsys, which, kind):
    a, _b = two
    claim(a)
    data = json.loads((a / "supervisor" / "INCARNATION").read_text())
    prior = "the-prior-pending-nonce"
    if which == "prior":
        data["prior_pending_hash"] = fleet.nonce_digest(prior)
        (a / "supervisor" / "INCARNATION").write_text(json.dumps(data), encoding="utf-8")
    presented = prior if which == "prior" else "wrong-nonce-value"
    log = a / "state" / "supervisor-nonce-rejections.jsonl"
    if which == "pending":
        pending = "the-pending-generation-nonce"
        data["pending_nonce_hash"] = fleet.nonce_digest(pending)
        (a / "supervisor" / "INCARNATION").write_text(json.dumps(data), encoding="utf-8")
        presented = pending
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(a, "send", "lane-a", "x", "--nonce", presented) == 1
    capsys.readouterr()
    if kind is None:                     # a pending generation is not second-body evidence
        assert not log.exists() or presented not in log.read_text()
        assert not log.exists() or '"refused"' not in log.read_text()
        assert spool(a, "lane-a", "new") == []
        return
    record = json.loads(log.read_text().splitlines()[-1])
    assert record["kind"] == kind and record["verb"] == "msg"
    assert record["presented_prefix"] == fleet.nonce_digest(presented)[:8]
    assert presented not in log.read_text()
    assert spool(a, "lane-a", "new") == []


def test_hosted_names_ignores_a_symlinked_peer_fleet_json(two, tmp_path):   # P2-3
    a, b = two
    prims = fleet._msg_prims()
    registry(b, {"lane-b": _lane(SID_B)})
    assert "lane-b" in fleet_msg.hosted_names(prims, b)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"workers": {"lane-evil": {}}}), encoding="utf-8")
    (b / "state" / "fleet.json").unlink()
    (b / "state" / "fleet.json").symlink_to(outside)
    names = fleet_msg.hosted_names(prims, b)
    assert "lane-evil" not in names and "lane-b" not in names
    assert {"supervisor", "interface"} <= set(names)


# --- T10b --------------------------------------------------------------------

def test_t10b_archive_moves_the_spool_and_a_reused_name_starts_empty(two, monkeypatch, capsys):
    a, _b = two
    as_body(monkeypatch, sid=SID_B)
    assert msg(a, "send", "lane-a", "for the old lane") == 0
    msg_id = sent_id(capsys)
    old = fleet_msg.archive_spool(fleet._msg_prims(), "lane-a")
    assert old is not None and "archive" in old.parts
    assert (old / "new" / f"{msg_id}.json").is_file()              # kept, never deleted
    assert not (a / "state/msg/spool/lane-a").exists()
    registry(a, {"lane-a": _lane(SID_A, archived_at=_iso()), "lane-b": _lane(SID_B)})
    assert msg(a, "send", "lane-a", "late") == 1
    assert "rejected: retired" in capsys.readouterr().err
    registry(a, {"lane-a": _lane("sid-lane-a-new"), "lane-b": _lane(SID_B)})   # name reused
    as_body(monkeypatch, sid="sid-lane-a-new")
    assert msg(a, "inbox") == 0
    assert "EMPTY" in capsys.readouterr().out
    assert fleet_msg.archive_spool(fleet._msg_prims(), "lane-a") is None   # nothing to move


def test_archive_spool_same_second_collision_is_uniquified(two, monkeypatch, capsys):
    a, _b = two
    targets, frozen = [], None
    for text in ("first", "second"):
        as_body(monkeypatch, sid=SID_B)
        assert msg(a, "send", "lane-a", text) == 0
        capsys.readouterr()
        base = fleet._msg_prims()               # FLEET_HOME is set by the msg call
        frozen = frozen or base.clock()
        prims = dataclasses.replace(base, clock=lambda: frozen)
        t = fleet_msg.archive_spool(prims, "lane-a")
        assert t is not None, text
        targets.append(t)
        assert not (a / "state/msg/spool/lane-a").exists()
    assert targets[0] != targets[1] and all(t.is_dir() for t in targets)


def test_cmd_archive_moves_the_spool_after_each_move_phase():
    src = inspect.getsource(fleet.cmd_archive)
    assert src.count("_archive_move_and_rm(") == 2
    assert src.count("_archive_msg_spool(n)") == 2
    for chunk in src.split("_archive_move_and_rm(")[1:]:
        assert "_archive_msg_spool(n)" in chunk.split("\n\n")[0] or "_archive_msg_spool(n)" in chunk[:600]


def test_archive_spool_without_a_store_is_a_no_op(tmp_path, monkeypatch):
    h = tmp_path / "bare"
    (h / "state").mkdir(parents=True)
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    assert fleet_msg.archive_spool(fleet._msg_prims(), "lane-a") is None


# --- the gate ----------------------------------------------------------------

def test_msg_is_in_the_nonce_gate_set():
    assert "msg" in fleet.GATE_VERBS_ACCEPTING_NONCE


def test_sync_rejects_mail_for_a_retired_role_and_names_the_reason(two, monkeypatch, capsys):
    a, b = two                                      # w508 P2-1: retired roles, not only lanes
    claim(a)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(a, "bind", "ops", "--binding", "session:sid-x", "--nonce", NONCE) == 0
    assert msg(a, "retire", "ops", "--nonce", NONCE) == 0
    as_body(monkeypatch)
    assert msg(b, "send", "ops@alpha", "late", "--from", "lane-x") == 0
    capsys.readouterr()
    assert msg(a, "sync", "--peer", "beta") == 0
    assert "rejected=1" in capsys.readouterr().out
    assert spool(a, "ops", "new") == []
    assert list((a / "state" / "msg" / "rejected").glob("*.json"))
    assert fleet_msg._retired_names(fleet._msg_prims()) == ["ops"]
    assert msg(b, "sync", "--peer", "alpha") == 0   # the sender learns the verdict
    capsys.readouterr()
    receipts = [json.loads(p.read_text()) for p in
                (b / "state/msg/spool/lane-x/new").glob("*.json")]
    assert [r["body"] for r in receipts] == ["rejected: retired"]
