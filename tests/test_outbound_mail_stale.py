"""Outbound mail nobody picks up is reported, once, by watch and doctor.

A home's `mailbox/to-<peer>/` outboxes (every `to-*` but the inbound
`to-fleet`) are polled by the receiving side, which moves handled files out.
A file still there after 30 minutes means the receiver stopped polling; the
sender kept queueing work behind it for hours. `fleet watch` now reports
`STALEOUT` once per such file and `fleet doctor` fails `outbound-mail`.
"""
import json
import os
import time

import pytest

import fleet


@pytest.fixture(autouse=True)
def _stable_watch_resources(monkeypatch):
    monkeypatch.setattr(fleet.PLATFORM, "memory_available_mb", lambda: 100_000)
    monkeypatch.setattr(fleet, "_watch_free_disk_gb", lambda _path: 100.0)


def _home(tmp_path):
    home = tmp_path / "home"
    (home / "state" / "interface").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(json.dumps({"workers": {}}))
    (home / "mailbox" / "to-fleet").mkdir(parents=True)
    (home / "mailbox" / "to-hub").mkdir(parents=True)
    return home


def _put(home, rel, minutes_old):
    path = home / "mailbox" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("from: fleet\n")
    stamp = time.time() - minutes_old * 60
    os.utime(path, (stamp, stamp))
    return path


def test_only_old_files_in_outboxes_are_stale(tmp_path):
    home = _home(tmp_path)
    _put(home, "to-hub/old.md", 45)
    _put(home, "to-hub/fresh.md", 5)
    _put(home, "to-hub/.hidden.md", 90)
    _put(home, "to-hub/writing.md.tmp", 90)
    _put(home, "to-fleet/inbound.md", 90)
    _put(home, "done/handled.md", 90)
    _put(home, "to-hub/done/archived.md", 90)
    stale = fleet._outbound_mail_stale(home, 30 * 60)
    assert [name for name, _age in stale] == ["to-hub/old.md"]
    assert 44 * 60 < stale[0][1] < 46 * 60


def _watch(home, *extra):
    args = fleet.build_parser().parse_args(
        ["watch", "--fleet-home", str(home), "--timeout", "0", *extra])
    return fleet.cmd_watch(args)


def test_watch_reports_each_stale_file_once(tmp_path, capsys):
    home = _home(tmp_path)
    _put(home, "to-hub/a.md", 40)
    _put(home, "to-hub/b.md", 50)
    assert _watch(home) == 0
    first = capsys.readouterr().out.strip()
    assert first.startswith(f"STALEOUT {fleet.home_tag(home)} to-hub/a.md 40m")
    assert _watch(home) == 0
    assert "to-hub/b.md" in capsys.readouterr().out
    assert _watch(home) == 3  # nothing new: no repeated event, no busy loop
    assert capsys.readouterr().out == ""


def test_a_picked_up_file_leaves_the_cursor_and_can_report_again(tmp_path, capsys):
    home = _home(tmp_path)
    path = _put(home, "to-hub/a.md", 40)
    assert _watch(home) == 0
    capsys.readouterr()
    path.unlink()
    assert _watch(home) == 3
    cursor = json.loads((home / "state" / "interface" / "watch-cursor.json").read_text())
    assert cursor["stale_out"] == []
    _put(home, "to-hub/a.md", 40)
    assert _watch(home) == 0


def test_the_threshold_is_configurable_and_can_be_off(tmp_path, capsys):
    home = _home(tmp_path)
    _put(home, "to-hub/a.md", 20)
    assert _watch(home) == 3
    assert _watch(home, "--outbound-stale-min", "10") == 0
    assert "STALEOUT" in capsys.readouterr().out
    other = _home(tmp_path / "other")
    _put(other, "to-hub/a.md", 600)
    assert _watch(other, "--outbound-stale-min", "0") == 3


def test_inbound_mail_still_wins_over_a_stale_outbox(tmp_path, capsys):
    home = _home(tmp_path)
    _put(home, "to-hub/a.md", 40)
    (home / "mailbox" / "to-fleet" / "note.md").write_text("hi")
    assert _watch(home) == 0
    assert capsys.readouterr().out.startswith("MAIL ")


def test_doctor_notes_stale_outbound_mail_without_failing(tmp_path, monkeypatch):
    """A receiver outside fleet being offline is not broken fleet
    infrastructure: the row is a NOTE, so `fleet doctor` still exits 0."""
    home = _home(tmp_path)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    _put(home, "to-hub/fresh.md", 5)
    name, ok, message = fleet._doctor_check_outbound_mail()
    assert ok is True and not message.startswith("NOTE")
    _put(home, "to-hub/old.md", 95)
    name, ok, message = fleet._doctor_check_outbound_mail()
    assert (name, ok) == ("outbound-mail", True)
    assert message.startswith("NOTE") and "to-hub/old.md" in message
    assert "95m" in message


def test_a_stale_file_is_not_lost_behind_another_event(tmp_path, capsys):
    """Review w598 of 06ecd2e0: a STALEOUT that loses to MAIL in the same pass
    must still be reported by a later watch, not recorded as reported."""
    home = _home(tmp_path)
    assert _watch(home) == 3  # seed the cursor
    _put(home, "to-hub/x.md", 40)
    (home / "mailbox" / "to-fleet" / "new.mail").write_text("hi")
    assert _watch(home) == 0
    assert capsys.readouterr().out.startswith("MAIL ")
    cursor = json.loads((home / "state" / "interface" / "watch-cursor.json").read_text())
    assert cursor["stale_out"] == []
    assert _watch(home) == 0
    assert capsys.readouterr().out.startswith("STALEOUT")
    assert _watch(home) == 3
