"""`sup-notify` target resolution when --tmux-session is not given."""
import subprocess
from types import SimpleNamespace

import pytest

import fleet
import fleet_codex


@pytest.fixture(autouse=True)
def no_interface_settle(monkeypatch):
    monkeypatch.setattr(fleet.time, "sleep", lambda _seconds: None)


class Tmux:
    def __init__(self, listing="", rc=0, panes=""):
        self.listing, self.rc, self.panes, self.calls = listing, rc, panes, []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ["tmux", "list-windows"]:
            out = self.listing
        elif argv[:2] == ["tmux", "list-panes"]:
            out = self.panes
        else:
            out = ""
        return subprocess.CompletedProcess(argv, self.rc, out, "")


def test_unique_match_elsewhere():
    run = Tmux("0:fleet\n0:other\n")
    assert fleet._resolve_notify_session(None, "fleet", run) == "0"
    assert run.calls[0][:3] == ["tmux", "list-windows", "-a"]


def test_work_preferred_over_other_matches():
    run = Tmux("0:fleet\nwork:fleet\nzz:fleet\n")
    assert fleet._resolve_notify_session(None, "fleet", run) == "work"


def test_zero_matches_fail_closed():
    with pytest.raises(fleet.FleetCliError, match="candidates: none"):
        fleet._resolve_notify_session(None, "fleet", Tmux("0:other\n"))


def test_tmux_failure_fails_closed():
    with pytest.raises(fleet.FleetCliError):
        fleet._resolve_notify_session(None, "fleet", Tmux("0:fleet\n", rc=1))


def test_ambiguous_names_candidates():
    with pytest.raises(fleet.FleetCliError) as exc:
        fleet._resolve_notify_session(None, "fleet", Tmux("a:fleet\nb:fleet\n"))
    assert "a:fleet" in str(exc.value) and "b:fleet" in str(exc.value)


def test_explicit_session_untouched_no_tmux_call():
    run = Tmux("0:fleet\n")
    assert fleet._resolve_notify_session("mine", "fleet", run) == "mine"
    assert run.calls == []


def test_dry_run_uses_resolved_target(capsys):
    run = Tmux("0:fleet\n")
    args = SimpleNamespace(text="hi", tmux_session=None, window="fleet",
                           dry_run=True)
    assert fleet.cmd_sup_notify(args, run=run) == 0
    assert "into 0:fleet:" in capsys.readouterr().out


# --- registered interface discovery (no tmux window needed) ---------------

@pytest.fixture
def reg_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "supervisor"):
        (tmp_path / sub).mkdir(exist_ok=True)
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    fleet.save_registry({"workers": {}})
    return tmp_path


def _hold():
    value = fleet.mint_nonce()
    fleet.write_incarnation({
        "incarnation_id": "inc-20260909T000000Z-aaaa", "session_id": "sid-sup",
        "state": "active", "nonce_hash": fleet.nonce_digest(value),
        "nonce_seq": 3, "lineage_id": "lin-x",
        "heartbeat_at": fleet.now_iso()})
    return value


def _nargs(**over):
    ns = dict(text="handoff", tmux_session=None, window="fleet",
              dry_run=False, sid="sid-sup", nonce=None)
    ns.update(over)
    return SimpleNamespace(**ns)


def test_registered_claude_session_without_drain_fails_closed(reg_home):
    (reg_home / "state" / "interface-session").write_text("sid-int\n")
    run = Tmux("")
    with pytest.raises(fleet.FleetCliError, match="interface has NOT been told") as exc:
        fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run)
    assert "mailbox" in str(exc.value) and "not drained" in str(exc.value)
    assert run.calls == []
    assert not (reg_home / "mailbox" / "sid-int.md").exists()
    assert not fleet.interface_log_path().exists()


def test_registered_codex_thread_without_drain_fails_closed(reg_home, monkeypatch):
    (reg_home / "state" / "interface-codex.json").write_text("{}")
    monkeypatch.setattr(fleet_codex, "read_interface_claim",
                        lambda _home: {"thread_id": "thread-int"})
    run = Tmux("")
    with pytest.raises(fleet.FleetCliError, match="mailbox is not drained"):
        fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run)
    assert run.calls == []
    assert not (reg_home / "mailbox" / "thread-int.md").exists()
    assert not fleet.interface_log_path().exists()


def test_registered_pane_targets_that_pane(reg_home):
    (reg_home / "state" / "interface-pane").write_text("%7\n")
    (reg_home / "state" / "interface-session").write_text("sid-int\n")
    run = Tmux("", panes="%7 claude 0\n")
    assert fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run) == 0
    paste = [c for c in run.calls if "paste-buffer" in c][0]
    assert paste[paste.index("-t") + 1] == "%7"
    assert not (reg_home / "mailbox").exists()


@pytest.mark.parametrize("panes, reason", [
    ("%7 bash 0\n", "runs bash"),
    ("%7 claude 1\n", "dead"),
    ("%8 claude 0\n", "absent"),
])
def test_registered_pane_is_not_typed_when_not_live_claude(reg_home, panes, reason):
    (reg_home / "state" / "interface-pane").write_text("%7\n")
    run = Tmux("work:fleet\n", panes=panes)
    with pytest.raises(fleet.FleetCliError, match="interface has NOT been told") as exc:
        fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run)
    assert reason in str(exc.value)
    assert not any("paste-buffer" in call or "send-keys" in call
                   for call in run.calls)
    assert not fleet.interface_log_path().exists()


def test_registered_pane_scan_failure_does_not_type(reg_home):
    (reg_home / "state" / "interface-pane").write_text("%7\n")
    run = Tmux("work:fleet\n", rc=1, panes="%7 claude 0\n")
    with pytest.raises(fleet.FleetCliError, match="pane scan failed"):
        fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run)
    assert not any("paste-buffer" in call or "send-keys" in call
                   for call in run.calls)
    assert not fleet.interface_log_path().exists()


def test_tmux_path_unchanged_when_nothing_registered(reg_home):
    run = Tmux("work:fleet\n")
    assert fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run) == 0
    paste = [c for c in run.calls if "paste-buffer" in c][0]
    assert paste[paste.index("-t") + 1] == "work:fleet"


def test_explicit_tmux_session_overrides_registration(reg_home):
    (reg_home / "state" / "interface-session").write_text("sid-int\n")
    run = Tmux("")
    fleet.cmd_sup_notify(_nargs(nonce=_hold(), tmux_session="s2"), run=run)
    paste = [c for c in run.calls if "paste-buffer" in c][0]
    assert paste[paste.index("-t") + 1] == "s2:fleet"
    assert not (reg_home / "mailbox").exists()


def test_nothing_registered_fails_closed_and_logs_nothing(reg_home):
    run = Tmux("0:other\n")
    with pytest.raises(fleet.FleetCliError, match="has NOT been told"):
        fleet.cmd_sup_notify(_nargs(nonce=_hold()), run=run)
    assert not (reg_home / "mailbox").exists()
    log = fleet.interface_log_path()
    assert not log.exists() or " RELAY " not in log.read_text()


def test_dry_run_rejects_undrained_registered_target(reg_home):
    (reg_home / "state" / "interface-session").write_text("sid-int\n")
    run = Tmux("")
    with pytest.raises(fleet.FleetCliError, match="mailbox is not drained"):
        fleet.cmd_sup_notify(_nargs(dry_run=True), run=run)
    assert run.calls == [] and not (reg_home / "mailbox").exists()
