"""The interface pane registration verb."""

import subprocess
import json
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
OTHER_THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106c2"


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


class CodexReadClient:
    def __init__(self, thread_id=CODEX_THREAD):
        self.thread_id = thread_id
        self.operations = []

    def call(self, operation, timeout):
        self.operations.append(operation)
        return SimpleNamespace(result={"thread": {"id": self.thread_id}})


def _source(thread_id=CODEX_THREAD, *, pid=500, start="17"):
    return {"thread_id": thread_id, "ancestor_pid": pid,
            "ancestor_start_identity": start, "ancestor_cwd": "/fleet",
            "uid": 1000}


def test_codex_interface_registers_same_genuine_source_in_three_explicit_homes(
        tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", CODEX_THREAD)
    import fleet_codex
    monkeypatch.setattr(fleet_codex, "codex_process_source",
                        lambda _pid, thread: _source(thread))
    clients = {}

    def client(home):
        return clients.setdefault(str(home), CodexReadClient())

    monkeypatch.setattr(fleet, "_codex_existing_client", client)

    for name in ("fleet", "pm", "tap"):
        home = tmp_path / name
        state = home / "state"
        state.mkdir(parents=True)
        monkeypatch.setattr(fleet, "FLEET_HOME", home)

        assert fleet.cmd_interface_register(_codex_args()) == 0

        claim = json.loads((state / "interface-codex.json").read_text())
        assert claim["home"] == str(home.resolve())
        assert claim["thread_id"] == CODEX_THREAD
        assert claim["ancestor_pid"] == 500
        assert [op["payload"]["method"] for op in clients[str(home.resolve())].operations] \
            == ["thread/read"]


def test_codex_interface_wrong_uuid_refuses_before_membership_read(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", CODEX_THREAD)
    import fleet_codex
    monkeypatch.setattr(
        fleet_codex, "codex_process_source",
        lambda _pid, thread: (_ for _ in ()).throw(
            fleet_codex.HostRejected("Codex caller thread does not match process evidence")))
    monkeypatch.setattr(fleet, "_codex_existing_client",
                        lambda _home: pytest.fail("must fail before public read"))

    with pytest.raises(fleet.FleetCliError, match="does not match process evidence"):
        fleet.cmd_interface_register(_codex_args(OTHER_THREAD))
    assert not (tmp_path / "state/interface-codex.json").exists()


def test_codex_interface_reregister_rotates_claim_and_disarms_predecessor(
        tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(fleet, "_codex_existing_client",
                        lambda _home: CodexReadClient())
    import fleet_codex
    source = _source()
    monkeypatch.setattr(fleet_codex, "codex_process_source",
                        lambda _pid, _thread: dict(source))
    assert fleet.cmd_interface_register(_codex_args()) == 0
    first = json.loads((tmp_path / "state/interface-codex.json").read_text())
    source.update(ancestor_pid=700, ancestor_start_identity="29")
    assert fleet.cmd_interface_register(_codex_args()) == 0
    second = json.loads((tmp_path / "state/interface-codex.json").read_text())
    assert second["claim_id"] != first["claim_id"]
    assert second["ancestor_pid"] == 700


def test_codex_interface_refuses_implicit_home_before_membership_read(
        tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("implicit home must fail before provider read"))

    with pytest.raises(fleet.FleetCliError, match="explicit --fleet-home"):
        fleet.cmd_interface_register(_codex_args(explicit=False))

    assert not (tmp_path / "state/interface-codex.json").exists()
