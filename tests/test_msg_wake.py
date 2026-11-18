"""Notice wake and drain block (spec docs/specs/messaging.md §9; plan PR 5, T12)."""
import ast
import os
from pathlib import Path

import pytest

import fleet_msg_core as core
import fleet_msg_wake as wake

BIN = Path(__file__).resolve().parents[1] / "bin"
NOW = 1_800_000_000.0
BODY = "SECRET-BODY-TEXT do the thing"
AUTH = {"method": "lane-registry", "detail": None}


class Prims:
    def __init__(self, adapters=None, sids=None):
        self.adapters = adapters or {}
        self.sids = sids or {}
        self.mail = []
        self.p = wake.WakePrims(
            fleet_home="/h", adapter_of=lambda n: self.adapters.get(n, wake.UNBOUND),
            holder_sid=lambda n: self.sids.get(n),
            append_mailbox=lambda sid, text: self.mail.append((sid, text)))


def make(tmp_path, adapters=None, sids=None):
    store = core.Store(tmp_path / "home", "a", clock=lambda: NOW)
    return store, Prims(adapters, sids)


def env(frm="w1@a", to="w2@a", n=0):
    d = core.make_draft(frm, to, BODY, from_auth=AUTH,
                        sent_at=core.iso_utc(NOW + n), msg_id=f"{n:032x}")
    d["seq"] = n + 1
    return d


def send(store, prims, e, name="w2"):
    core.publish(store, name, e, notify=wake.make_notify(store, prims.p))


def test_notice_line_exact_no_body():
    e = env()
    line = wake.notice_line(e, "/h")
    assert line == f"FLEET MSG {e['id']} from w1@a (lane-registry). Run fleet --fleet-home /h msg inbox."
    assert "SECRET" not in line


def test_claude_gets_notice_without_body(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE}, {"w2": "sid-2"})
    send(store, pr, env())
    assert len(pr.mail) == 1 and pr.mail[0][0] == "sid-2"
    assert "SECRET" not in pr.mail[0][1] and "FLEET MSG" in pr.mail[0][1]


@pytest.mark.parametrize("adapter", [wake.CODEX, wake.PI, wake.INTERFACE, wake.UNBOUND])
def test_other_adapters_drain_only(tmp_path, adapter):
    store, pr = make(tmp_path, {"w2": adapter}, {"w2": "sid-2"})
    send(store, pr, env())
    assert pr.mail == []
    assert "SECRET" not in wake.drain_block(store, pr.p, "w2")
    assert wake.drain_block(store, pr.p, "w2").startswith("## MESSAGES")


def test_claude_without_holder_is_drain_only(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE})
    send(store, pr, env())
    assert pr.mail == []


def test_one_pending_notice_per_sender(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE}, {"w2": "s"})
    send(store, pr, env(n=0))
    send(store, pr, env(n=1))
    assert len(pr.mail) == 1
    send(store, pr, env("w3@a", n=2))      # other sender: own notice
    assert len(pr.mail) == 2


def test_notice_again_after_read(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE}, {"w2": "s"})
    e0 = env(n=0)
    send(store, pr, e0)
    core.move(store, "w2", e0["id"], "new", "cur", reader="w2")
    send(store, pr, env(n=1))
    assert len(pr.mail) == 2


def test_wake_failure_logged_not_raised(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE}, {"w2": "s"})
    pr.p.append_mailbox = lambda sid, text: (_ for _ in ()).throw(OSError("x"))
    e = env()
    assert core.publish(store, "w2", e, notify=wake.make_notify(store, pr.p)) == "delivered"
    assert "notice-failed" in store.ledger_path.read_text()
    assert core.list_spool(store, "w2", "new") == [e["id"]]


def test_drain_block_lists_without_marking_read(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CODEX})
    es = [env(n=i) for i in range(3)]
    for e in es:
        send(store, pr, e)
    block = wake.drain_block(store, pr.p, "w2")
    for e in es:
        assert f"- {e['id']} from w1@a (lane-registry)" in block
    assert "msg inbox." in block and "SECRET" not in block
    assert core.list_spool(store, "w2", "new") == sorted(e["id"] for e in es)
    assert core.list_spool(store, "w2", "cur") == []


def test_drain_block_empty_and_capped(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.PI})
    assert wake.drain_block(store, pr.p, "w2") == ""
    for i in range(wake.DRAIN_MAX_LINES + 3):
        send(store, pr, env(n=i))
    block = wake.drain_block(store, pr.p, "w2")
    assert block.count("\n- ") == wake.DRAIN_MAX_LINES + 1
    assert "- ... 3 more" in block


def test_unparseable_spool_entry_skipped(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CODEX})
    send(store, pr, env(n=0))
    (store.spool("w2", "new") / ("f" * 32 + ".json")).write_bytes(b"not json")
    assert len(wake.unread(store, "w2")) == 1


def test_wake_takes_no_lock_steer_or_registry(tmp_path):
    store, pr = make(tmp_path, {"w2": wake.CLAUDE}, {"w2": "s"})
    e = env()
    core.publish(store, "w2", e)       # no notify: isolate the wake
    locks = set(os.listdir(store.root / "locks"))
    wake.wake(store, pr.p, "w2", e)
    wake.drain_block(store, pr.p, "w2")
    assert set(os.listdir(store.root / "locks")) == locks
    assert not (store.home / "state" / "registry.json").exists()
    assert not (store.home / "fleet.lock").exists()


def test_unknown_adapter_raises(tmp_path):
    store, pr = make(tmp_path, {"w2": "bogus"})
    with pytest.raises(ValueError):
        wake.wake(store, pr.p, "w2", env())


def test_module_isolation():
    tree = ast.parse((BIN / "fleet_msg_wake.py").read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert "fleet" not in mods
    assert mods <= {"__future__", "dataclasses", "typing", "fleet_msg_core"}
