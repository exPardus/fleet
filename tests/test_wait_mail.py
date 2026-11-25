"""`fleet wait --mail`: a supervisor park that also wakes on Interface mail.

The supervisor used to park in `fleet wait` on its lanes and miss Interface
direction that arrived meanwhile. With `--mail` the wait also returns when a
new verified Interface-mail receipt appears, names become optional (a pure
park), and the wait never exceeds ten minutes.
"""
import json
from types import SimpleNamespace

import pytest

import fleet

INTERFACE_SID = "abcd0000-1111-2222-3333-444455556666"
SUPERVISOR = "sup|inc-mail|boot"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for name in ("state", "mailbox", "supervisor"):
        (tmp_path / name).mkdir()
    (tmp_path / "state" / "fleet.json").write_text(
        json.dumps({"workers": {}}), encoding="utf-8")
    (tmp_path / "state" / "interface-session").write_text(
        INTERFACE_SID + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", INTERFACE_SID)
    for name in ("CODEX_THREAD_ID", "MCX_WORKER", "FLEET_WORKER", "TMUX_PANE"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _issue(body="land the reviewed lane"):
    _notice, mail_id = fleet._issue_verified_supervisor_mail(SUPERVISOR, body)
    assert mail_id is not None
    return mail_id


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def _args(names=(), **over):
    base = dict(names=list(names), any=False, all=False, timeout=None, mail=True)
    base.update(over)
    return SimpleNamespace(**base)


def test_a_pure_park_returns_on_new_verified_mail(home, capsys):
    clock = Clock()
    arrived = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not arrived:
            arrived.append(_issue())

    assert fleet.cmd_wait(_args(), sleep=sleep, clock=clock) == 0
    out = capsys.readouterr().out
    assert f"MAIL {arrived[0]}" in out
    assert f"fleet mail verify {arrived[0]}" in out
    assert clock.now < fleet.MAIL_WAIT_CAP_SECONDS


def test_mail_present_before_the_park_does_not_wake_it(home, capsys):
    _issue("old direction")
    clock = Clock()
    assert fleet.cmd_wait(_args(), sleep=clock.sleep, clock=clock) == 1
    assert "no new verified Interface mail" in capsys.readouterr().out
    assert clock.now == pytest.approx(fleet.MAIL_WAIT_CAP_SECONDS, abs=3.0)


@pytest.mark.parametrize("timeout, expected", [(None, 600), (3600, 600), (30, 30)])
def test_the_park_is_capped_at_ten_minutes(home, timeout, expected):
    clock = Clock()
    fleet.cmd_wait(_args(timeout=timeout), sleep=clock.sleep, clock=clock)
    assert expected <= clock.now < expected + 3.1


def test_an_unverifiable_receipt_does_not_wake_the_park(home):
    clock = Clock()
    forged = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not forged:
            path = fleet.mail_receipts_dir()
            path.mkdir(parents=True, exist_ok=True)
            mail_id = "11111111-2222-4333-8444-555555555555"
            (path / f"{mail_id}.json").write_text(json.dumps({"id": mail_id}))
            forged.append(mail_id)

    assert fleet.cmd_wait(_args(), sleep=sleep, clock=clock) == 1


def test_mail_wakes_a_wait_on_a_working_lane(home, monkeypatch, capsys):
    monkeypatch.setattr(fleet, "load_registry",
                        lambda: {"workers": {"w1": {"status": "working",
                                                    "session_id": "s1"}}})
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda: (True, []))
    monkeypatch.setattr(fleet, "native_epoch_suspicious", lambda *a: False)
    monkeypatch.setattr(fleet, "recompute_worker",
                        lambda n, rec, entries: {"status": "working"})
    clock = Clock()
    arrived = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not arrived:
            arrived.append(_issue())

    assert fleet.cmd_wait(_args(["w1"]), sleep=sleep, clock=clock) == 0
    out = capsys.readouterr().out
    assert f"MAIL {arrived[0]}" in out and "w1: still working" in out


def test_without_mail_a_name_is_still_required(home):
    with pytest.raises(fleet.FleetCliError, match="--mail"):
        fleet.cmd_wait(_args(mail=False))


def test_the_parser_accepts_a_pure_park():
    args = fleet.build_parser().parse_args(["wait", "--mail"])
    assert args.mail is True and args.names == []


# Review w598 of a21621b7 (P3s).
def test_each_receipt_is_verified_at_most_once(home, monkeypatch):
    for _ in range(5):
        _issue("old direction")
    calls = []
    real = fleet.cmd_mail_verify

    def counting(args):
        calls.append(args.mail_id)
        return real(args)

    monkeypatch.setattr(fleet, "cmd_mail_verify", counting)
    clock = Clock()
    forged_id = "11111111-2222-4333-8444-555555555555"

    def sleep(seconds):
        clock.sleep(seconds)
        if clock.now == 3.0:
            path = fleet.mail_receipts_dir() / f"{forged_id}.json"
            path.write_text(json.dumps({"id": forged_id}))

    assert fleet.cmd_wait(_args(timeout=30), sleep=sleep, clock=clock) == 1
    # The old ones never; the forged one once, then once per recheck interval.
    assert calls and set(calls) == {forged_id}
    assert len(calls) <= 1 + int(27 // fleet.MAIL_RECHECK_SECONDS)


def test_mail_and_a_finishing_lane_in_one_poll_are_both_reported(
        home, monkeypatch, capsys):
    state = {"status": "working"}
    monkeypatch.setattr(fleet, "load_registry",
                        lambda: {"workers": {"w1": {"status": state["status"],
                                                    "session_id": "s1"}}})
    monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda: (True, []))
    monkeypatch.setattr(fleet, "native_epoch_suspicious", lambda *a: False)
    monkeypatch.setattr(fleet, "recompute_worker",
                        lambda n, rec, entries: {"status": state["status"]})
    monkeypatch.setattr(fleet, "save_registry", lambda data: None)
    monkeypatch.setattr(fleet, "latest_outcome", lambda *a: None)
    clock = Clock()
    arrived = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not arrived:
            arrived.append(_issue())
            state["status"] = "idle"  # the lane ends in the same poll

    assert fleet.cmd_wait(_args(["w1"]), sleep=sleep, clock=clock) == 0
    out = capsys.readouterr().out
    assert f"MAIL {arrived[0]}" in out
    assert "w1: idle" in out


def test_a_receipt_that_failed_once_is_rechecked(home, monkeypatch, capsys):
    """Review w598 of df29dea9 (P3): a False verdict was cached for the whole
    wait, so mail whose first check hit a short-lived failure never woke it."""
    clock = Clock()
    real = fleet.cmd_mail_verify
    flaky = {"left": 1}

    def verify(args):
        if flaky["left"]:
            flaky["left"] -= 1
            return 1  # e.g. an OSError reading the registration token
        return real(args)

    monkeypatch.setattr(fleet, "cmd_mail_verify", verify)
    arrived = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not arrived:
            arrived.append(_issue())

    assert fleet.cmd_wait(_args(timeout=120), sleep=sleep, clock=clock) == 0
    assert f"MAIL {arrived[0]}" in capsys.readouterr().out
    assert clock.now < 120

