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


def test_watch_rejects_nonpositive_interval(tmp_path):
    with pytest.raises(SystemExit):
        fleet.build_parser().parse_args(
            ["watch", "--fleet-home", str(_home(tmp_path)), "--interval", "0"]
        )


def test_watch_keeps_lane_cursor_when_registry_unreadable(tmp_path, capsys):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    cursor_path.write_text(json.dumps({"mail": [], "lanes": {"lane-a": "working"}, "mcx": {}}))
    (home / "state" / "fleet.json").write_text("{broken", encoding="utf-8")
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 3
    assert capsys.readouterr().out == ""
    assert json.loads(cursor_path.read_text())["lanes"] == {"lane-a": "working"}


def test_watch_keeps_mcx_cursor_when_mcx_is_missing(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    cursor_path.write_text(json.dumps({"mail": [], "lanes": {"lane-a": "working"}, "mcx": {"abcd": "running"}}))
    monkeypatch.setattr(fleet.shutil, "which", lambda _name: None)
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--mcx-dir", str(tmp_path / ".mcx"), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 3
    assert capsys.readouterr().out == ""
    assert json.loads(cursor_path.read_text())["mcx"] == {"abcd": "running"}


def test_watch_keeps_mcx_cursor_when_mcx_fails(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    cursor_path.write_text(json.dumps({"mail": [], "lanes": {"lane-a": "working"}, "mcx": {"abcd": "running"}}))
    monkeypatch.setattr(fleet.shutil, "which", lambda _name: "/fake/mcx")

    class Proc:
        returncode = 1
        stdout = ""

    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--mcx-dir", str(tmp_path / ".mcx"), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 3
    assert capsys.readouterr().out == ""
    assert json.loads(cursor_path.read_text())["mcx"] == {"abcd": "running"}


def test_watch_announces_unsupported_memory_platform(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)

    class FakePlatform:
        def memory_available_mb(self):
            raise fleet.UnsupportedPlatformError("memory unavailable")

    monkeypatch.setattr(fleet, "PLATFORM", FakePlatform())
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 3
    assert "LOWMEM unsupported on this platform" in capsys.readouterr().out


def test_watch_checks_disk_for_every_home(tmp_path, capsys, monkeypatch):
    home_a = _home(tmp_path / "a")
    home_b = _home(tmp_path / "b")
    checked = []

    def free_disk(path):
        checked.append(Path(path))
        return 10 if Path(path) == home_a else 1

    monkeypatch.setattr(fleet, "_watch_free_disk_gb", free_disk)
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home_a), "--fleet-home", str(home_b), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip() == "LOWDISK 1"
    assert checked == [home_a, home_b]


def test_watch_registry_baseline_waits_for_first_valid_observation(tmp_path, capsys):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    (home / "state" / "fleet.json").write_text("{broken", encoding="utf-8")
    (home / "mailbox" / "to-fleet" / "note.md").write_text("mail", encoding="utf-8")
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )

    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip().startswith("MAIL ")
    first = json.loads(cursor_path.read_text())
    assert first["lanes_valid"] is False

    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"lane-a": {"status": "working"}}}), encoding="utf-8"
    )
    assert fleet.cmd_watch(args) == 3
    assert capsys.readouterr().out == ""
    second = json.loads(cursor_path.read_text())
    assert second["lanes_valid"] is True

    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"lane-a": {"status": "idle"}}}), encoding="utf-8"
    )
    assert fleet.cmd_watch(args) == 0
    assert capsys.readouterr().out.strip() == "LANE lane-a working->idle"


def test_watch_mcx_baseline_waits_for_first_valid_observation(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    mcx_dir = tmp_path / ".mcx"
    monkeypatch.setattr(fleet.shutil, "which", lambda _name: "/fake/mcx")
    state = {"returncode": 1, "stdout": ""}

    class Proc:
        @property
        def returncode(self):
            return state["returncode"]

        @property
        def stdout(self):
            return state["stdout"]

    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--mcx-dir", str(mcx_dir), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 3
    assert capsys.readouterr().out == ""
    first = json.loads(cursor_path.read_text())
    assert first["mcx_valid"] is False

    state.update(returncode=0, stdout="abcd\trunning\n")
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 3
    assert capsys.readouterr().out == ""
    second = json.loads(cursor_path.read_text())
    assert second["mcx_valid"] is True

    state["stdout"] = "abcd\tdone\n"
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 0
    assert capsys.readouterr().out.strip() == "LANE abcd running->done"


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_watch_rejects_nonfinite_interval_and_timeout(tmp_path, value):
    home = _home(tmp_path)
    with pytest.raises(SystemExit):
        fleet.build_parser().parse_args(
            ["watch", "--fleet-home", str(home), "--interval", value]
        )
    with pytest.raises(SystemExit):
        fleet.build_parser().parse_args(
            ["watch", "--fleet-home", str(home), "--timeout", value]
        )


@pytest.mark.parametrize("row", [None, ["working"]])
def test_watch_rejects_schema_invalid_registry_rows(tmp_path, capsys, row):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    cursor_path.write_text(json.dumps({
        "mail": [], "lanes": {"lane-a": "working"}, "mcx": {},
        "lanes_valid": True, "mcx_valid": True,
    }))
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": {"lane-a": row}}), encoding="utf-8"
    )
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args) == 3
    assert capsys.readouterr().out == ""
    assert json.loads(cursor_path.read_text())["lanes"] == {"lane-a": "working"}


def test_watch_rejects_malformed_mcx_line(tmp_path, capsys, monkeypatch):
    home = _home(tmp_path)
    cursor_path = home / "state" / "interface" / "watch-cursor.json"
    cursor_path.write_text(json.dumps({
        "mail": [], "lanes": {"lane-a": "working"}, "mcx": {"abcd": "running"},
        "lanes_valid": True, "mcx_valid": True,
    }))
    monkeypatch.setattr(fleet.shutil, "which", lambda _name: "/fake/mcx")

    class Proc:
        returncode = 0
        stdout = "malformed-line\n"

    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--mcx-dir", str(tmp_path / ".mcx"), "--timeout", "0"]
    )
    assert fleet.cmd_watch(args, run=lambda *a, **k: Proc()) == 3
    assert capsys.readouterr().out == ""
    assert json.loads(cursor_path.read_text())["mcx"] == {"abcd": "running"}
