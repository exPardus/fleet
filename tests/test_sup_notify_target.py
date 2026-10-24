"""`sup-notify` target resolution when --tmux-session is not given."""
import subprocess
from types import SimpleNamespace

import pytest

import fleet


class Tmux:
    def __init__(self, listing="", rc=0):
        self.listing, self.rc, self.calls = listing, rc, []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = self.listing if argv[:2] == ["tmux", "list-windows"] else ""
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
