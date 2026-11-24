"""`fleet exclusive -- CMD`: one box-wide run at a time, never a stuck waiter.

Lanes coordinated "one full pytest / buf / docker DB run box-wide" with
background waiters that pgrep'd each other; one lane sat for hours on a run
that had ended long before. The fleet-owned lock names its holder, takes a
dead or over-TTL holder over, waits in the foreground for a capped time,
releases on every exit path, and doctor reports a stale holder.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet
import fleet_exclusive as ex

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def lock(tmp_path, monkeypatch):
    path = tmp_path / "fleet-exclusive.json"
    monkeypatch.setenv("FLEET_EXCLUSIVE_LOCK", str(path))
    return path


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _record(**over):
    base = {"schema": 1, "token": "other", "holder": "w583", "pid": os.getpid(),
            "identity": None, "child_pid": None, "child_identity": None,
            "started_at_epoch": time.time(), "ttl_seconds": 3600,
            "label": "full pytest", "command": "pytest"}
    base.update(over)
    return base


def _hold(lock, **over):
    record = _record(**over)
    lock.write_text(json.dumps(record))
    return record


def test_the_lock_path_is_redirected_in_tests():
    assert "fleet-exclusive.json" in os.environ["FLEET_EXCLUSIVE_LOCK"]
    assert ex.lock_path() != Path.home() / ".claude" / "fleet-exclusive.json"


def test_a_free_lock_is_held_named_and_released(lock):
    seen = []

    class Child:
        pid = os.getpid()

        def wait(self):
            seen.append(json.loads(lock.read_text()))
            return 0

        def poll(self):
            return 0

    rc = ex.run(["true"], holder_name="w582", label="full pytest", path=lock,
                popen=lambda cmd: Child())
    assert rc == 0
    assert seen[0]["holder"] == "w582" and seen[0]["label"] == "full pytest"
    assert seen[0]["pid"] == os.getpid() and seen[0]["child_pid"] == os.getpid()
    assert not lock.exists()


def test_a_live_holder_makes_the_waiter_wait_then_fail_naming_it(lock, capsys):
    _hold(lock)
    clock = Clock()
    rc = ex.run(["true"], holder_name="w582", wait_max=60, path=lock,
                sleep=clock.sleep, clock=clock,
                popen=lambda cmd: pytest.fail("must not run while held"))
    assert rc == ex.WAIT_TIMEOUT_EXIT
    err = capsys.readouterr().err
    assert "waiting (at most 60 s)" in err and "held by w583" in err
    assert "gave up after 60 s" in err
    assert 60 <= clock.now <= 60 + ex.POLL_SECONDS
    assert json.loads(lock.read_text())["holder"] == "w583"  # untouched


def test_the_wait_is_capped(lock):
    _hold(lock)
    clock = Clock()
    ex.run(["true"], holder_name="w582", wait_max=10 ** 9, path=lock,
           sleep=clock.sleep, clock=clock, popen=lambda cmd: pytest.fail("held"))
    assert clock.now <= ex.MAX_WAIT_SECONDS + ex.POLL_SECONDS


@pytest.mark.parametrize("stale", ["dead-pid", "past-ttl", "garbage"])
def test_a_stale_holder_is_taken_over(lock, capsys, stale):
    if stale == "dead-pid":
        _hold(lock, pid=_dead_pid())
    elif stale == "past-ttl":
        _hold(lock, started_at_epoch=time.time() - 7200, ttl_seconds=3600)
    else:
        lock.write_text("not json")
    ran = []

    class Child:
        pid = os.getpid()

        def wait(self):
            ran.append(json.loads(lock.read_text())["holder"])
            return 0

        def poll(self):
            return 0

    assert ex.run(["true"], holder_name="w582", path=lock,
                  popen=lambda cmd: Child()) == 0
    assert ran == ["w582"]
    assert "taking over a stale lock" in capsys.readouterr().err
    assert not lock.exists()


def test_a_live_child_keeps_the_lock_after_its_runner_died(lock):
    _hold(lock, pid=_dead_pid(), child_pid=os.getpid())
    assert ex.stale_reason(ex.read_holder(lock)) is None


def test_only_one_waiter_wins_a_takeover(lock):
    stale = _hold(lock, pid=_dead_pid())
    assert ex._take_over(lock, stale) is True
    assert ex._write_new(lock, _record(token="first-winner"))
    # A second waiter that judged the same stale holder must not move the
    # first winner's fresh lock aside.
    assert ex._take_over(lock, stale) is False
    assert json.loads(lock.read_text())["token"] == "first-winner"


def test_release_removes_only_its_own_lock(lock):
    _hold(lock, token="someone-else")
    assert ex.release(lock, "mine") is False
    assert lock.exists()
    assert ex.release(lock, "someone-else") is True
    assert not lock.exists()


def test_the_lock_is_released_when_the_command_fails_or_is_interrupted(lock):
    terminated = []

    class Child:
        pid = os.getpid()

        def wait(self, timeout=None):
            raise SystemExit(143)  # SIGTERM to the runner

        def poll(self):
            return None

        def terminate(self):
            terminated.append(True)

        def kill(self):
            terminated.append("kill")

    with pytest.raises(SystemExit):
        ex.run(["sleep", "100"], holder_name="w582", path=lock,
               popen=lambda cmd: Child())
    assert terminated and not lock.exists()


def test_two_real_runs_never_overlap(tmp_path, lock):
    log = tmp_path / "log"
    script = ("import sys, time; open(sys.argv[1], 'a').write('start\\n'); "
              "time.sleep(1.5); open(sys.argv[1], 'a').write('end\\n')")
    env = dict(os.environ, FLEET_EXCLUSIVE_LOCK=str(lock))
    command = [sys.executable, str(ROOT / "bin" / "fleet.py"), "exclusive",
               "--label", "probe", "--", sys.executable, "-c", script, str(log)]
    first = subprocess.Popen(command, env=env)
    time.sleep(0.5)
    second = subprocess.Popen(command, env=env, stderr=subprocess.PIPE, text=True)
    assert first.wait(60) == 0
    _out, err = second.communicate(timeout=60)
    assert second.returncode == 0
    assert log.read_text().splitlines() == ["start", "end", "start", "end"]
    assert "waiting" in err and "probe" in err
    assert not lock.exists()


def test_status_and_exit_codes(lock, capsys):
    args = SimpleNamespace(status=True)
    assert fleet.cmd_exclusive(args) == 0
    assert "free" in capsys.readouterr().out
    _hold(lock)
    assert fleet.cmd_exclusive(args) == 0
    assert "held by w583" in capsys.readouterr().out
    _hold(lock, pid=_dead_pid())
    assert fleet.cmd_exclusive(args) == 1
    assert "STALE" in capsys.readouterr().out


def test_a_command_is_required(lock):
    with pytest.raises(fleet.FleetCliError, match="after --"):
        fleet.cmd_exclusive(fleet.build_parser().parse_args(["exclusive"]))


def test_the_command_exit_status_passes_through(lock):
    rc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "fleet.py"), "exclusive", "--",
         sys.executable, "-c", "raise SystemExit(7)"],
        env=dict(os.environ, FLEET_EXCLUSIVE_LOCK=str(lock))).returncode
    assert rc == 7 and not lock.exists()


def test_doctor_reports_a_stale_holder(lock):
    assert fleet._doctor_check_exclusive_lock()[1] is True
    _hold(lock)
    assert fleet._doctor_check_exclusive_lock()[1] is True
    _hold(lock, pid=_dead_pid())
    name, ok, message = fleet._doctor_check_exclusive_lock()
    assert (name, ok) == ("exclusive-lock", False)
    assert "w583" in message and "stale" in message


def test_the_preamble_tells_lanes_to_use_it_instead_of_pgrep(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    prompt, _claim, _mail = fleet.compose_prompt("w1", "/x", "t", None)
    assert "fleet exclusive --label TEXT -- <command>" in prompt
    assert "Never wait on other lanes with `pgrep` loops" in prompt
