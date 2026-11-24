"""An archived lane's refusal names the exact next command.

`fleet send` (and respawn, kill, interrupt, ...) to an archived lane used to
say only "archived -- history only (fleet clean to delete)", and the
supervisor had to work out what to do. Every mutating verb, respawn
included, refuses an archived row, so the useful next step is a new lane
from the archived record: the refusal now prints that `fleet spawn` command
with the row's dir, mode, model, category and saved brief, under a free name.
"""
import json
import shlex

import pytest

import fleet


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    return tmp_path


def _archived(**over):
    rec = {"session_id": "s1", "status": "idle", "cwd": "/work/lane a",
           "mode": "accept", "model": "claude-sonnet-5-5", "category": "w",
           "archived_at": "2026-11-25T00:00:00Z", "dispatch_kind": "bg"}
    rec.update(over)
    return rec


def _command(message):
    start = message.index("`fleet spawn")
    return message[start + 1:message.index("`", start + 1)]


def test_send_to_an_archived_lane_names_the_spawn_command(home):
    fleet.save_registry({"workers": {"w583": _archived()}})
    fleet.brief_file_path("w583").parent.mkdir(parents=True, exist_ok=True)
    fleet.brief_file_path("w583").write_text("the brief")
    with pytest.raises(fleet.FleetCliError) as exc:
        fleet.refuse_if_archived("w583", _archived(), "send")
    message = str(exc.value)
    assert message.startswith("w583: archived -- history only, so `send` refuses it.")
    argv = shlex.split(_command(message))
    assert argv[:3] == ["fleet", "spawn", "w583-2"]
    assert argv[argv.index("--dir") + 1] == "/work/lane a"
    assert argv[argv.index("--mode") + 1] == "accept"
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--category") + 1] == "w"
    assert argv[argv.index("--task") + 1] == "@" + fleet.brief_file_path("w583").as_posix()
    assert argv[-2:] == ["--nonce", "<NONCE>"]
    # The printed command parses as a real spawn invocation.
    parsed = fleet.build_parser().parse_args(argv[1:])
    assert parsed.command == "spawn" and parsed.name == "w583-2"


def test_the_suggested_name_is_free(home):
    fleet.save_registry({"workers": {"w583": _archived(), "w583-2": {"status": "idle"},
                                     "w583-3": {"status": "idle"}}})
    with pytest.raises(fleet.FleetCliError) as exc:
        fleet.refuse_if_archived("w583-3", _archived(), "respawn")
    assert "`fleet spawn w583-4 " in str(exc.value)
    assert "so `respawn` refuses it" in str(exc.value)


def test_without_a_saved_brief_the_task_is_a_placeholder(home):
    fleet.save_registry({"workers": {}})
    with pytest.raises(fleet.FleetCliError) as exc:
        fleet.refuse_if_archived("w9", _archived(model=None, category=None), "kill")
    command = _command(str(exc.value))
    assert "--task <task>" in command and "--model" not in command


def test_an_unarchived_row_is_not_refused(home):
    fleet.refuse_if_archived("w1", {"status": "idle"}, "send")


def test_cmd_send_surfaces_the_hint(home, monkeypatch):
    fleet.save_registry({"workers": {"w583": _archived()}})
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    monkeypatch.setattr(fleet, "_ceiling_refuses_dispatch", lambda *a, **k: None)
    monkeypatch.setattr(fleet, "_require_instance_settings", lambda: None)
    from types import SimpleNamespace
    with pytest.raises(fleet.FleetCliError, match="`fleet spawn w583-2 "):
        fleet.cmd_send(SimpleNamespace(name="w583", message="hi", nonce=None,
                                       force_band=False))
