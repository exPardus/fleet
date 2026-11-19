"""Migration hooks: `msg import`, `relay-ack`, `mail verify` and the verified
mail envelope, the mailman bridge seed (docs/specs/messaging.md §12; plan PR 9b)."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
import fleet_mailman
import fleet_msg_core as core
import fleet_msg_migrate as mig

IFACE_SID = "abcd0000-1111-2222-3333-444455556666"
LANE_SID = "sid-lane-a"
SUPERVISOR = "sup|inc-mail|boot"
SUP_SID, NONCE = "sid-supervisor", "nonce-value-not-for-the-ledger"
MAIL = "from: Old Bridge\nkind: status\nneeds-answer: no\n\nlegacy body\n"


def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for name in ("state", "mailbox/to-fleet", "supervisor"):
        (h / name).mkdir(parents=True)
    (h / "state" / "fleet.json").write_text(json.dumps({"workers": {"lane-a": {
        "session_id": LANE_SID, "dispatch_kind": "bg", "cwd": "/w", "created": _iso()}}}))
    (h / "state" / "interface-session").write_text(IFACE_SID + "\n")
    monkeypatch.setattr(fleet, "FLEET_HOME", h)
    for var in ("CODEX_THREAD_ID", "MCX_WORKER", "FLEET_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", IFACE_SID)
    assert msg(h, "init", "--site", "alpha") == 0
    return h


def msg(h, *argv):
    return fleet.main(["--fleet-home", str(h), "msg", *argv])


def as_sid(monkeypatch, sid):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", sid)


def store(h):
    return core.Store(h, "alpha")


def outbound(tmp_path, **files):
    d = tmp_path / "outbound"
    d.mkdir()
    for name, text in files.items():
        (d / name).write_text(text)
    return d


def spool(h, name, state):
    d = h / "state" / "msg" / "spool" / name / state
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


# --- msg import ---------------------------------------------------------------

def test_import_is_disruptive_and_has_a_parser():
    args = fleet.build_parser().parse_args(
        ["msg", "import", "--dir", "d", "--to", "interface@alpha"])
    assert fleet.verb_effect_tier("msg", args) == "disruptive"


def test_import_by_the_interface_moves_files_to_done(home, tmp_path, capsys):
    d = outbound(tmp_path, **{"a.mail": MAIL, "bad.mail": "no headers at all"})
    capsys.readouterr()
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") == 0
    out = capsys.readouterr().out
    assert "IMPORTED 1 DUPLICATE 0 MOVED 1 SKIPPED 1" in out and "SKIPPED bad.mail" in out
    assert sorted(os.listdir(d)) == ["bad.mail", "done"]
    assert os.listdir(d / "done") == ["a.mail"]
    assert (d / "done" / "a.mail").read_text() == MAIL
    (name,) = spool(home, "interface", "new")
    env = json.loads((home / "state/msg/spool/interface/new" / name).read_text())
    assert env["from_auth"]["method"] == "legacy-unverified" and env["body"] == "legacy body"
    # a second run finds nothing new; the done/ directory is not reported
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") == 0
    again = capsys.readouterr().out
    assert "IMPORTED 0" in again and "SKIPPED 1" in again and "done" not in again.replace("MOVED", "")


def test_import_empty_directory_says_retire(home, tmp_path, capsys):
    d = outbound(tmp_path)
    capsys.readouterr()
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") == 0
    assert "EMPTY" in capsys.readouterr().out


def test_import_never_overwrites_a_filed_name(home, tmp_path, capsys):
    d = outbound(tmp_path, **{"a.mail": MAIL})
    (d / "done").mkdir()
    (d / "done" / "a.mail").write_text("older")
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") == 0
    assert (d / "done" / "a.mail").read_text() == "older"
    assert sorted(os.listdir(d / "done")) == sorted(
        ["a.mail", next(n for n in os.listdir(d / "done") if n.startswith("a.mail."))])
    assert not (d / "a.mail").exists()


def test_import_refused_for_a_worker_turn(home, tmp_path, monkeypatch, capsys):
    d = outbound(tmp_path, **{"a.mail": MAIL})
    as_sid(monkeypatch, LANE_SID)
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") == 1
    assert "worker turn cannot import" in capsys.readouterr().err
    assert os.listdir(d) == ["a.mail"] and spool(home, "interface", "new") == []


def test_import_refused_without_any_proof_or_nonce(home, tmp_path, monkeypatch, capsys):
    d = outbound(tmp_path, **{"a.mail": MAIL})
    as_sid(monkeypatch, "sid-nobody")
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") != 0
    assert os.listdir(d) == ["a.mail"]


def test_import_with_a_live_nonce(home, tmp_path, monkeypatch, capsys):
    (home / "supervisor" / "INCARNATION").write_text(json.dumps({
        "incarnation_id": "inc-1", "lineage_id": "lin-1", "session_id": SUP_SID,
        "state": "held", "nonce_hash": fleet.nonce_digest(NONCE), "nonce_seq": 7,
        "heartbeat_at": _iso()}))
    (home / "state" / "interface-session").unlink()
    d = outbound(tmp_path, **{"a.mail": MAIL})
    as_sid(monkeypatch, SUP_SID)
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha") != 0
    assert msg(home, "import", "--dir", str(d), "--to", "interface@alpha",
               "--nonce", NONCE) == 0
    assert os.listdir(d / "done") == ["a.mail"]
    assert NONCE not in (home / "state/msg/ledger.jsonl").read_text()


def test_import_missing_directory_is_a_one_line_refusal(home, tmp_path, capsys):
    assert msg(home, "import", "--dir", str(tmp_path / "nope"), "--to", "interface@alpha") == 1
    assert "does not exist" in capsys.readouterr().err


# --- relay-ack acks rendered mail ---------------------------------------------

def _rendered(home, monkeypatch, capsys):
    as_sid(monkeypatch, LANE_SID)
    assert msg(home, "send", "interface", "please look") == 0
    msg_id = capsys.readouterr().out.split()[1]
    env = json.loads((home / f"state/msg/spool/interface/new/{msg_id}.json").read_text())
    assert mig.render_to_fleet(store(home), env) == "rendered"
    as_sid(monkeypatch, IFACE_SID)
    return msg_id, home / "mailbox" / "to-fleet" / mig.mail_name(msg_id)


def _relay(mail):
    return fleet.main(["relay-ack", "--mail", str(mail), "--line", "RELAY x"])


def test_relay_ack_acks_the_rendered_message(home, monkeypatch, capsys):
    msg_id, mail = _rendered(home, monkeypatch, capsys)
    assert _relay(mail) == 0
    assert not mail.exists() and (home / "mailbox/done" / mail.name).exists()
    assert spool(home, "interface", "new") == [] and spool(home, "interface", "cur") == []
    assert spool(home, "interface", "done") == [f"{msg_id}.json"]


def test_relay_ack_without_interface_proof_still_relays_and_leaves_the_message(
        home, monkeypatch, capsys):
    msg_id, mail = _rendered(home, monkeypatch, capsys)
    (home / "state" / "interface-session").unlink()
    assert _relay(mail) == 0
    assert (home / "mailbox/done" / mail.name).exists()
    assert spool(home, "interface", "new") == [f"{msg_id}.json"]


def test_relay_ack_of_plain_mail_is_unchanged(home, monkeypatch, capsys):
    mail = home / "mailbox" / "to-fleet" / "msg-note.mail"
    mail.write_text("from: x\n\nhi\n")
    assert _relay(mail) == 0 and (home / "mailbox/done/msg-note.mail").exists()


def test_relay_ack_ignores_a_name_whose_header_id_differs(home, monkeypatch, capsys):
    msg_id, mail = _rendered(home, monkeypatch, capsys)
    other = mail.with_name(mig.mail_name("0" * 32))
    mail.rename(other)
    assert _relay(other) == 0
    assert spool(home, "interface", "new") == [f"{msg_id}.json"]


# --- the verified supervisor mail envelope and `mail verify` -------------------

def _issue(body="land the reviewed lane"):
    _notice, mail_id = fleet._issue_verified_supervisor_mail(SUPERVISOR, body)
    assert mail_id is not None
    return mail_id


def _verify(mail_id):
    return fleet.cmd_mail_verify(SimpleNamespace(mail_id=mail_id))


def test_issue_writes_an_envelope_under_the_receipt_id(home):
    mail_id = _issue()
    (name,) = spool(home, "supervisor", "new")
    assert name == f"{mail_id.replace('-', '')}.json"
    env = json.loads((home / "state/msg/spool/supervisor/new" / name).read_text())
    assert (env["from"], env["to"], env["body"]) == (
        "interface@alpha", "supervisor@alpha", "land the reviewed lane")
    assert env["from_auth"]["method"] == "interface-registration"
    assert (home / "state" / "mail-receipts" / f"{mail_id}.json").exists()


def test_issue_without_a_site_or_with_an_oversize_body_keeps_only_the_receipt(
        home, tmp_path):
    big = _issue("word " * 400)
    assert spool(home, "supervisor", "new") == []
    assert (home / "state" / "mail-receipts" / f"{big}.json").exists()
    (home / "state" / "msg" / "site.json").unlink()
    _issue()
    assert spool(home, "supervisor", "new") == []


def test_verify_with_both_stores_still_checks_the_receipt(home, capsys):
    mail_id = _issue("act on this")
    capsys.readouterr()
    assert _verify(mail_id) == 0
    assert "VERIFIED" in capsys.readouterr().out
    (home / "state" / "interface-session").write_text("someone-else\n")
    assert _verify(mail_id) == 1
    assert "Interface registration does not match" in capsys.readouterr().out


def test_verify_reads_the_message_store_first(home, capsys):
    mail_id = _issue("act on this")
    (home / "state" / "mail-receipts" / f"{mail_id}.json").unlink()
    capsys.readouterr()
    assert _verify(mail_id) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"VERIFIED {mail_id}")
    assert "SOURCE registered-interface/claude-session" in out
    assert "TARGET supervisor" in out and out.rstrip().endswith("act on this")


def test_verify_refuses_an_envelope_that_is_not_interface_mail(home, capsys):
    mail_id = "11111111-2222-4333-8444-555555555555"
    draft = core.make_draft(
        "legacy@alpha", "supervisor@alpha", "do the thing",
        from_auth={"method": "legacy-unverified", "detail": "import"},
        sent_at=_iso(), msg_id=mail_id.replace("-", ""))
    core.enqueue(store(home), draft)
    capsys.readouterr()
    assert _verify(mail_id) == 1
    assert "UNVERIFIED" in capsys.readouterr().out


def test_verify_falls_through_for_unknown_ids_and_no_site(home, capsys):
    unknown = "11111111-2222-4333-8444-555555555555"
    assert _verify(unknown) == 1
    assert "no Fleet receipt" in capsys.readouterr().out
    mail_id = _issue("old store")
    (home / "state" / "msg" / "site.json").unlink()
    capsys.readouterr()
    assert _verify(mail_id) == 0 and "VERIFIED" in capsys.readouterr().out


def test_verify_uses_the_old_store_for_a_compacted_id(home, capsys):
    mail_id = _issue("compacted away")
    for path in (home / "state" / "msg").rglob(f"{mail_id.replace('-', '')}*"):
        path.unlink()
    capsys.readouterr()
    assert _verify(mail_id) == 0 and "compacted away" in capsys.readouterr().out


# --- the mailman seed bridge argv ---------------------------------------------

def test_mailman_init_seeds_the_sync_argv_when_the_home_has_a_site(home):
    assert fleet.main(["--fleet-home", str(home), "mailman", "init"]) == 0
    cfg = json.loads((home / "mailman.json").read_text())
    cmd = cfg["bridge"]["command"]
    assert cmd[2:] == ["--fleet-home", home.as_posix(), "msg", "sync", "--once"]
    assert cmd[0] == sys.executable and cmd[1].endswith("bin/fleet.py")
    assert fleet_mailman.load_config(home)[1] is None
    cfg["bridge"]["command"] = []
    assert cfg == fleet_mailman.SEED_CONFIG


def test_mailman_init_without_a_site_keeps_the_empty_bridge(home):
    (home / "state" / "msg" / "site.json").unlink()
    assert fleet.main(["--fleet-home", str(home), "mailman", "init"]) == 0
    assert json.loads((home / "mailman.json").read_text()) == fleet_mailman.SEED_CONFIG
