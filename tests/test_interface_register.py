"""The interface pane registration verb."""

import subprocess
from types import SimpleNamespace

import pytest

import fleet


class Tmux:
    def __init__(self, window="old", rc=0):
        self.window = window
        self.rc = rc
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[1] == "display-message":
            return subprocess.CompletedProcess(argv, self.rc,
                                               self.window if self.rc == 0 else "",
                                               "")
        return subprocess.CompletedProcess(argv, self.rc, "", "")


def _args():
    return SimpleNamespace()


CODEX_THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106c1"


def _codex_args(thread_id=CODEX_THREAD, explicit=True):
    return SimpleNamespace(
        codex_thread=thread_id, session_id=None,
        _fleet_home_explicit=explicit)


def test_register_renames_and_writes_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setenv("TMUX_PANE", "%42")
    tmux = Tmux(window="manual-name")

    assert fleet.cmd_interface_register(_args(), run=tmux) == 0

    assert tmux.calls == [
        ["tmux", "display-message", "-p", "-t", "%42", "#{window_name}"],
        ["tmux", "rename-window", "-t", "%42", "fleet"],
    ]
    assert (tmp_path / "state/interface-pane").read_text() == "%42\n"
    assert "registered" in capsys.readouterr().out


def test_register_is_noop_when_registration_and_window_are_correct(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setenv("TMUX_PANE", "%42")
    path = tmp_path / "state/interface-pane"
    path.parent.mkdir()
    path.write_text("%42\n")
    tmux = Tmux(window="fleet")

    assert fleet.cmd_interface_register(_args(), run=tmux) == 0
    assert len(tmux.calls) == 1
    assert tmux.calls[0][1] == "display-message"


@pytest.mark.parametrize("value", [None, "fleet", "%bad"])
def test_register_refuses_without_a_keeper_shape(tmp_path, monkeypatch, value):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    if value is None:
        monkeypatch.delenv("TMUX_PANE", raising=False)
    else:
        monkeypatch.setenv("TMUX_PANE", value)

    with pytest.raises(fleet.FleetCliError, match="TMUX_PANE"):
        fleet.cmd_interface_register(_args(), run=Tmux())

    assert not (tmp_path / "state/interface-pane").exists()


def test_register_refuses_when_tmux_pane_lookup_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setenv("TMUX_PANE", "%42")

    with pytest.raises(fleet.FleetCliError, match="lookup failed"):
        fleet.cmd_interface_register(_args(), run=Tmux(rc=1))

    assert not (tmp_path / "state/interface-pane").exists()


def test_codex_interface_refuses_all_three_explicit_homes_without_authenticator(
        tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", CODEX_THREAD)
    monkeypatch.setenv("CODEX_SESSION_ID", CODEX_THREAD)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("membership read cannot authenticate caller"))

    for name in ("fleet", "pm", "tap"):
        home = tmp_path / name
        state = home / "state"
        state.mkdir(parents=True)
        sentinel = state / "interface-codex.json"
        sentinel.write_text('{"existing":true}\n', encoding="utf-8")
        before = sentinel.read_bytes()
        monkeypatch.setattr(fleet, "FLEET_HOME", home)

        with pytest.raises(fleet.FleetCliError, match="does not authenticate"):
            fleet.cmd_interface_register(_codex_args())

        assert sentinel.read_bytes() == before


def test_codex_interface_refuses_implicit_home_before_membership_read(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("implicit home must fail before provider read"))

    with pytest.raises(fleet.FleetCliError, match="explicit --fleet-home"):
        fleet.cmd_interface_register(_codex_args(explicit=False))

    assert not (tmp_path / "state/interface-codex.json").exists()
