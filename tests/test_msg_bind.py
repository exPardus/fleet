"""Named roles: `fleet msg bind` / `retire` (spec docs/specs/messaging.md §3,
§8, §10; plan PR 8, T17)."""
import ast
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet
import fleet_msg
import fleet_msg_bind as bind

BIN = Path(__file__).resolve().parents[1] / "bin"
SID_OLD, SID_NEW, SID_OTHER = "sid-lane-old", "sid-lane-new", "sid-other"
SUP_SID, NONCE = "sid-supervisor", "nonce-value-not-for-the-ledger"


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lane(sid=SID_OLD, **over):
    row = {"session_id": sid, "dispatch_kind": "bg", "cwd": "/w", "created": _iso()}
    row.update(over)
    return row


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "state").mkdir(parents=True)
    (h / "supervisor").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    for var in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "MCX_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    registry(h, {"lane-a": _lane(), "lane-b": _lane(SID_OTHER)})
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


def ledger(h):
    path = h / "state" / "msg" / "ledger.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def role(h, name="ops"):
    return json.loads((h / "state" / "msg" / "ids" / f"{name}.json").read_text())


def sent_id(capsys):
    out = capsys.readouterr().out.split()
    assert out[0] in ("DELIVERED", "QUEUED"), out
    return out[1]


def bound(home, monkeypatch, binding, name="ops"):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "bind", name, "--binding", binding, "--nonce", NONCE) == 0


# --- T17: who may bind ---------------------------------------------------------

def test_t17_bind_without_nonce_is_refused(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a") != 0
    assert not (home / "state" / "msg" / "ids" / "ops.json").exists()
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a", "--nonce", "wrong") != 0
    assert not (home / "state" / "msg" / "ids" / "ops.json").exists()


def test_t17_bind_with_no_claim_and_no_proof_is_refused(home, monkeypatch, capsys):
    as_body(monkeypatch)
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a") == 1
    assert "cannot bind" in capsys.readouterr().err


def test_t17_worker_turn_bind_is_refused(home, monkeypatch, capsys):
    as_body(monkeypatch, sid=SID_OLD)                       # a registered lane
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a") == 1
    assert "a worker turn cannot bind" in capsys.readouterr().err
    claim(home)                                             # also under a fresh claim
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a") == 1
    assert msg(home, "retire", "ops") == 1
    assert not (home / "state" / "msg" / "ids").exists()


def test_bind_by_the_registered_interface(home, monkeypatch, capsys):
    (home / "state" / "interface-session").write_text("sid-iface\n", encoding="utf-8")
    as_body(monkeypatch, sid="sid-iface")
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a") == 0
    assert role(home)["bound_by"] == "interface-registration"


# --- T17: epoch and ledger -----------------------------------------------------

def test_t17_epoch_increments_on_rebind_with_a_ledger_line(home, monkeypatch, capsys):
    bound(home, monkeypatch, "session:sid-x")
    assert "BOUND ops@alpha session:sid-x epoch=1" in capsys.readouterr().out
    first = role(home)
    assert set(first) == {"schema", "name", "role", "binding", "epoch", "bound_at", "bound_by"}
    assert first["bound_by"] == "supervisor-nonce" and first["epoch"] == 1
    assert msg(home, "bind", "ops", "--binding", "session:sid-y", "--nonce", NONCE) == 0
    assert "epoch=2" in capsys.readouterr().out
    assert role(home)["binding"] == "session:sid-y" and role(home)["epoch"] == 2
    lines = [r for r in ledger(home) if r["event"] == "bound"]
    assert [(r["epoch"], r["binding"], r["previous"]) for r in lines] == [
        (1, "session:sid-x", None), (2, "session:sid-y", "session:sid-x")]
    assert NONCE not in (home / "state" / "msg" / "ledger.jsonl").read_text()
    assert NONCE not in (home / "state" / "msg" / "ids" / "ops.json").read_text()


def test_concrete_binding_needs_a_rebind_after_a_body_swap(home, monkeypatch, capsys):
    bound(home, monkeypatch, "session:sid-x")
    as_body(monkeypatch, sid=SID_OTHER)
    assert msg(home, "send", "ops", "hello", "--from", "lane-b") == 0
    as_body(monkeypatch, sid="sid-x")
    assert msg(home, "inbox", "ops") == 0
    assert "hello" in capsys.readouterr().out
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "bind", "ops", "--binding", "session:sid-y", "--nonce", NONCE) == 0
    as_body(monkeypatch, sid="sid-x")
    assert msg(home, "inbox", "ops") == 1
    assert "does not hold 'ops'" in capsys.readouterr().err
    as_body(monkeypatch, sid="sid-y")
    assert msg(home, "inbox", "ops") == 0


# --- T17: lane binding follows the registry ------------------------------------

def test_t17_lane_binding_follows_fork_steer_and_respawn(home, monkeypatch, capsys):
    bound(home, monkeypatch, "lane:lane-a")
    capsys.readouterr()
    as_body(monkeypatch, sid=SID_OTHER)
    assert msg(home, "send", "ops", "first", "--from", "lane-b") == 0
    first = sent_id(capsys)
    # fork-steer restamps the row: no rebind
    registry(home, {"lane-a": _lane(SID_NEW), "lane-b": _lane(SID_OTHER)})
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "ops") == 1                   # retired body fails
    assert "does not hold 'ops'" in capsys.readouterr().err
    as_body(monkeypatch, sid=SID_NEW)
    assert msg(home, "inbox", "ops") == 0                   # live body passes
    assert "first" in capsys.readouterr().out
    assert role(home)["epoch"] == 1                         # no rebind happened
    assert msg(home, "ack", first) == 0
    # respawn: a fresh session on the same row
    registry(home, {"lane-a": _lane("sid-respawned"), "lane-b": _lane(SID_OTHER)})
    as_body(monkeypatch, sid=SID_OTHER)
    assert msg(home, "send", "ops", "second", "--from", "lane-b") == 0
    as_body(monkeypatch, sid="sid-respawned")
    assert msg(home, "inbox", "ops") == 0
    assert "second" in capsys.readouterr().out
    assert msg(home, "whois", "ops") == 0
    assert "holder=session:sid-respawned" in capsys.readouterr().out
    assert [r["event"] for r in ledger(home)].count("bound") == 1


def test_lane_binding_follows_a_codex_thread_rotation(home, monkeypatch, capsys):
    codex = {"session_id": None, "substrate": "codex", "dispatch_kind": "codex-app-server",
             "codex_thread_id": "t-1", "cwd": "/w", "created": _iso()}
    registry(home, {"lane-a": codex})
    bound(home, monkeypatch, "lane:lane-a")
    registry(home, {"lane-a": dict(codex, codex_thread_id="t-2")})
    as_body(monkeypatch, thread="t-2")
    assert msg(home, "inbox", "ops") == 0
    as_body(monkeypatch, thread="t-1")
    assert msg(home, "inbox", "ops") == 1


def test_a_bound_holder_sends_as_the_role(home, monkeypatch, capsys):
    bound(home, monkeypatch, "session:sid-x")
    as_body(monkeypatch, sid="sid-x")
    assert msg(home, "send", "lane-a", "from ops", "--from", "ops") == 0
    assert msg(home, "ids") == 0
    capsys.readouterr()
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "lane-a") == 0
    assert "VERIFIED ops@alpha bound-holder" in capsys.readouterr().out


# --- refusals ------------------------------------------------------------------

@pytest.mark.parametrize("name,binding,fragment", [
    ("lane-a", "session:sid-x", "never bound"),
    ("supervisor", "session:sid-x", "never bound"),
    ("interface", "session:sid-x", "never bound"),
    ("ops", "lane:nope", "not a live lane"),
    ("ops", "lane:supervisor", "not a live lane"),
    ("ops", "bogus", "a binding is lane"),
    ("ops", "session:", "a binding is lane"),
    ("Bad Name", "session:sid-x", "bad name"),
])
def test_bind_refusals(home, monkeypatch, capsys, name, binding, fragment):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "bind", name, "--binding", binding, "--nonce", NONCE) == 1
    assert fragment in capsys.readouterr().err
    assert not (home / "state" / "msg" / "ids").exists()


def test_bind_refuses_an_archived_lane(home, monkeypatch, capsys):
    registry(home, {"lane-a": _lane(archived_at=_iso())})
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "bind", "ops", "--binding", "lane:lane-a", "--nonce", NONCE) == 1
    assert "not a live lane" in capsys.readouterr().err


def test_unbound_role_queues_and_an_archived_bound_lane_leaves_no_holder(home, monkeypatch, capsys):
    bound(home, monkeypatch, "lane:lane-a")
    registry(home, {"lane-a": _lane(archived_at=_iso())})
    assert msg(home, "whois", "ops") == 0
    assert "holder=-" in capsys.readouterr().out
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "inbox", "ops") == 1


# --- retire --------------------------------------------------------------------

def test_retire_keeps_the_record_and_a_bind_revives_it(home, monkeypatch, capsys):
    bound(home, monkeypatch, "session:sid-x")
    assert msg(home, "retire", "ops", "--nonce", NONCE) == 0
    assert "RETIRED ops@alpha epoch=2" in capsys.readouterr().out
    record = role(home)
    assert record["binding"] is None and record["retired_at"] and record["epoch"] == 2
    as_body(monkeypatch, sid=SID_OLD)
    assert msg(home, "send", "ops", "late", "--from", "lane-a") == 1
    assert "retired" in capsys.readouterr().err
    as_body(monkeypatch, sid="sid-x")
    assert msg(home, "inbox", "ops") == 1                   # a retired role has no holder
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "retire", "ops", "--nonce", NONCE) == 0   # idempotent
    assert msg(home, "bind", "ops", "--binding", "session:sid-z", "--nonce", NONCE) == 0
    assert role(home)["epoch"] == 3 and "retired_at" not in role(home)
    assert [r["event"] for r in ledger(home) if r["event"] in ("bound", "retired")] == [
        "bound", "retired", "bound"]


def test_retire_unknown_role_is_refused(home, monkeypatch, capsys):
    claim(home)
    as_body(monkeypatch, sid=SUP_SID)
    assert msg(home, "retire", "ghost", "--nonce", NONCE) == 1
    assert "not a named role" in capsys.readouterr().err


# --- doctrine ------------------------------------------------------------------

def test_module_imports_only_core_and_the_stdlib():
    tree = ast.parse((BIN / "fleet_msg_bind.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    local = {p.stem for p in BIN.glob("*.py")}
    assert imported & local == {"fleet_msg_core"}
    assert "fleet_lock" not in imported


def test_module_deletes_nothing():
    tree = ast.parse((BIN / "fleet_msg_bind.py").read_text())
    attrs = {(n.attr) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"unlink", "remove", "rmdir", "rmtree", "rename", "truncate"}
    assert bind.role_names  # the module under test imported
