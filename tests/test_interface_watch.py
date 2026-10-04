import json
from pathlib import Path

import fleet
import pytest


def _home(tmp_path):
    home = tmp_path / "home"
    (home / "state" / "interface").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"lane-a": {"status": "working"}}}),
        encoding="utf-8",
    )
    (home / "mailbox" / "to-fleet").mkdir(parents=True)
    return home


def test_watch_reports_mail_and_persists_cursor(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    (home / "mailbox" / "to-fleet" / "note.md").write_text("hello", encoding="utf-8")
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip() == f"MAIL {fleet.home_tag(home)} note.md"
    cursor = json.loads((home / "state" / "interface" / "watch-cursor.json").read_text())
    assert cursor["mail"] == ["note.md"]

    assert fleet.cmd_watch(args) == 3
    assert capsys.readouterr().out == ""


def test_relay_ack_refusal_is_byte_identical(tmp_path, monkeypatch):
    home = _home(tmp_path)
    mail = home / "mailbox" / "other.md"
    mail.write_text("mail", encoding="utf-8")
    log = home / "state" / "interface" / "log.md"
    before = (mail.read_bytes(), log.read_bytes() if log.exists() else None)
    args = fleet.build_parser().parse_args(
        ["relay-ack", "--mail", str(mail), "--line", "RELAY x"]
    )
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_relay_ack(args)
    assert (mail.read_bytes(), log.read_bytes() if log.exists() else None) == before


def test_watch_reports_lane_transition_without_holding_lock(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    cursor = home / "state" / "interface" / "watch-cursor.json"
    cursor.write_text(json.dumps({"mail": [], "lanes": {"lane-a": "working"}, "mcx": {}}))
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"lane-a": {"status": "idle"}}}), encoding="utf-8"
    )
    seen = []
    monkeypatch.setattr(fleet, "fleet_lock", lambda: (_ for _ in ()).throw(AssertionError()))
    args = fleet.build_parser().parse_args(["watch", "--fleet-home", str(home), "--timeout", "0"])
    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip() == "LANE lane-a working->idle"


def test_watch_reports_mcx_transition_from_list(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    (home / "state" / "interface" / "watch-cursor.json").write_text(
        json.dumps({"mail": [], "lanes": {"lane-a": "working"},
                    "mcx": {"abcd1234": "running"}})
    )
    class Proc:
        returncode = 0
        stdout = "ID\tSTATE\tMODEL\tEFFORT\tTASK\nabcd1234\tdone\tx\tx\tx\n"
    monkeypatch.setattr(fleet.shutil, "which", lambda name: "/fake/mcx")
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--mcx-dir", str(tmp_path / ".mcx"), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 0
    assert capsys.readouterr().out.strip() == "LANE abcd1234 running->done"


def test_relay_ack_moves_mail_and_mirrors(tmp_path, monkeypatch):
    home = _home(tmp_path)
    mail = home / "mailbox" / "to-fleet" / "note.md"
    mail.write_text("mail", encoding="utf-8")
    mirror = tmp_path / "mirror.log"
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    args = fleet.build_parser().parse_args(
        ["relay-ack", "--mail", str(mail), "--line", "RELAY x", "--mirror-log", str(mirror)]
    )
    assert fleet.cmd_relay_ack(args) == 0
    assert not mail.exists()
    assert (home / "mailbox" / "done" / "note.md").read_text() == "mail"
    assert "RELAY x" in (home / "state" / "interface" / "log.md").read_text()
    assert "RELAY x" in mirror.read_text()


def test_watch_reports_low_resources(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    monkeypatch.setattr(fleet, "_watch_mem_available_mb", lambda: 12)
    monkeypatch.setattr(fleet, "_watch_free_disk_gb", lambda path: 1.25)
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip() == "LOWMEM 12"
