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
