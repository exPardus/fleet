"""w68: the interface role is durable home state, not session context."""

import io
import json
import subprocess
from datetime import datetime, timezone

import pytest

import fleet
import fleet_keeper


TEMPLATE = '{"hooks": {}}\n'


def _prepare_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fleet.template_settings_path().write_text(TEMPLATE, encoding="utf-8")
    monkeypatch.delenv("TMUX_PANE", raising=False)


def _plant_fresh_claim(home):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    supervisor = home / "supervisor"
    supervisor.mkdir(parents=True, exist_ok=True)
    (supervisor / "INCARNATION").write_text(json.dumps({
        "incarnation_id": "inc-test",
        "session_id": "supervisor-session",
        "claimed_at": stamp,
        "heartbeat_at": stamp,
        "claimed_via": "fresh",
        "nonce_hash": fleet.nonce_digest("test-generation"),
        "nonce_seq": 1,
        "lineage_id": "lineage-test",
    }), encoding="utf-8")


def test_bare_init_in_unrelated_repo_ignores_claim_in_other_home(
        tmp_path, monkeypatch, capsys):
    claimed_home = tmp_path / "claimed-home"
    claimed_home.mkdir()
    _plant_fresh_claim(claimed_home)
    target = tmp_path / "new-repo"
    target.mkdir()
    _prepare_repo(target, monkeypatch)
    monkeypatch.setattr(fleet, "FLEET_HOME", claimed_home)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "new-interface")

    assert fleet.main(["init"]) == 0
    assert (target / "state/interface-session").read_text() == \
        "new-interface\n"
    assert "startup ritual" in capsys.readouterr().out


def test_bare_init_in_claimed_home_keeps_continuity_gate(
        tmp_path, monkeypatch, capsys):
    _prepare_repo(tmp_path, monkeypatch)
    _plant_fresh_claim(tmp_path)
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "different-session")

    assert fleet.main(["init"]) == fleet.SUPERVISOR_CONTINUITY_RC
    assert "claim-nonce §7" in capsys.readouterr().err
    assert not (tmp_path / "state/fleet.json").exists()


def test_bare_init_registers_caller_and_prints_startup_ritual(
        tmp_path, monkeypatch, capsys):
    _prepare_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "interface-session")

    assert fleet.main(["init"]) == 0

    assert (tmp_path / "state" / "interface-session").read_text() == \
        "interface-session\n"
    assert (tmp_path / "state/interface/board.md").exists()
    assert (tmp_path / "state/interface/log.md").exists()
    output = capsys.readouterr().out
    for marker in ("startup ritual", "board:", "sup-status:",
                   "inbox:", "rulings:"):
        assert marker in output


def test_second_init_is_registration_noop(tmp_path, monkeypatch, capsys):
    _prepare_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "interface-session")

    assert fleet.main(["init"]) == 0
    capsys.readouterr()
    log = tmp_path / "state/interface/log.md"
    before = log.read_text(encoding="utf-8")

    assert fleet.main(["init"]) == 0

    assert log.read_text(encoding="utf-8") == before
    assert "already initialized" in capsys.readouterr().out


def test_outside_tmux_uses_session_id_and_pane_path_still_refuses(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "session-outside")

    assert fleet.cmd_interface_register(fleet.SimpleNamespace()) == 0
    assert (tmp_path / "state/interface-session").read_text() == \
        "session-outside\n"

    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    with pytest.raises(fleet.FleetCliError, match="TMUX_PANE"):
        fleet.cmd_interface_register(fleet.SimpleNamespace())


def test_keeper_pages_unregistered_interface_without_creating_window(
        tmp_path, monkeypatch):
    interface = tmp_path / "state/interface"
    interface.mkdir(parents=True)
    (interface / "board.md").write_text("# board\n", encoding="utf-8")
    (interface / "log.md").write_text("", encoding="utf-8")
    monkeypatch.setattr(fleet_keeper.fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(fleet_keeper, "collect", lambda *a, **kw: {
        "goals_active": False, "claim_state": "none", "hook_error_lines": 0})
    calls = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = io.StringIO()
    assert fleet_keeper.main(
        ["--once", "--fleet-home", str(tmp_path)], run=runner,
        now_fn=lambda: 1_800_000_000.0, out=out) == 0

    assert "interface is not registered" in out.getvalue()
    sends = [argv for argv in calls if argv[:2] == ["tmux", "send-keys"]]
    assert sends and "interface is not registered" in sends[0][-1]
    assert not any(argv[1] == "new-window" for argv in calls)


def test_board_lists_only_unruled_non_lens_tasks(tmp_path):
    tasks = tmp_path / "state" / "tasks"
    (tasks / "lens").mkdir(parents=True)
    (tasks / "pending.md").write_text("# Question\n", encoding="utf-8")
    (tasks / "answered.md").write_text("# Question\nRULED: yes\n", encoding="utf-8")
    (tasks / "lens" / "brief.md").write_text("# Research\n", encoding="utf-8")

    assert fleet._interface_pending_rulings(tmp_path) == "state/tasks/pending.md"
