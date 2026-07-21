"""Destructive-command guard (SPEC §5.1).

Origin: on 2026-07-09 a `claude -p "/fleet:status"` probe, granted `Bash(fleet:*)`
by a read-only slash command, killed a WORKING worker and swept five journals.
It never exceeded its permissions. Narrowing the grant fixed that one command;
these tests pin the CLI-level guard, which holds even for a session running
under `bypassPermissions` (where no permission prompt is ever shown).

Rule: a worker you spawned is yours. A worker spawned by another session -- or
whose owner is unknown -- needs `--yes`. Foreign + no --yes = refuse, exit 1.
A human at a plain shell (no CLAUDE_CODE_SESSION_ID) is never guarded.

There is deliberately no interactive prompt: an agent's Bash tool has no stdin,
and `isatty()` cannot distinguish the cases on Windows -- Git Bash's /dev/null
is NUL, a character device, so `fleet kill x < /dev/null` reports a tty.
"""
import argparse
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "mailbox", "logs"):
        (tmp_path / sub).mkdir()
    return tmp_path


def _rec(spawned_by=None, status="dead", **over):
    base = {
        "session_id": "sid-1", "cwd": "C:/proj", "task": "t", "mode": "dontask",
        "model": None, "max_budget_usd": None, "setting_sources": None,
        "token_ceiling": None, "spawned_by": spawned_by,
        "created": "2026-07-09T12:00:00Z", "status": status,
        "attached_since": None,
        "limit_reset_at": None, "limit_kind": None, "turns": 1,
        "cost_baseline": 0.0, "cost_usd": 1.0,
        "last_activity": "2026-07-09T12:00:00Z",
        "dispatch_kind": "bg", "category": None, "native_short_id": None,
        "last_dispatch_at": None, "retired_sids": [], "archived_at": None,
    }
    base.update(over)
    return base


class TestOwnership:
    def test_a_worker_you_spawned_is_yours(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        assert fleet._worker_is_foreign(_rec(spawned_by="sess-A"), fleet.current_caller_session()) is False

    def test_another_sessions_worker_is_foreign(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        assert fleet._worker_is_foreign(_rec(spawned_by="sess-B"), fleet.current_caller_session()) is True

    def test_unknown_owner_is_foreign_not_mine(self, monkeypatch):
        # Every record written before `spawned_by` existed has no owner. The
        # guard must fail toward ASKING, never toward "must be mine".
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        assert fleet._worker_is_foreign(_rec(spawned_by=None), fleet.current_caller_session()) is True
        assert fleet._worker_is_foreign({}, fleet.current_caller_session()) is True

    def test_a_human_shell_has_no_session_id(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert fleet.current_caller_session() is None

    def test_a_human_shell_is_never_guarded(self, monkeypatch):
        # The guard exists to stop an over-helpful AGENT, not to interpose
        # friction in a human's script. A human typing `fleet clean` meant it.
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        fleet._confirm_destructive("kill", ["w"], {"w": _rec(spawned_by="sess-B")},
                                   assume_yes=False)


class TestConfirmDestructive:
    def test_own_workers_pass_silently(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        fleet._confirm_destructive("kill", ["w"], {"w": _rec(spawned_by="sess-A")},
                                   assume_yes=False)

    def test_foreign_worker_refuses(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet._confirm_destructive("kill", ["w"], {"w": _rec(spawned_by="sess-B")},
                                       assume_yes=False)
        assert "--yes" in str(exc.value)

    def test_foreign_worker_with_yes_proceeds(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        fleet._confirm_destructive("kill", ["w"], {"w": _rec(spawned_by="sess-B")},
                                   assume_yes=True)

    def test_an_agent_is_never_prompted(self, monkeypatch):
        # An agent's Bash tool has no stdin: input() raises EOFError and the
        # traceback, not a clean refusal, is what the operator would see.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        def no_input(*a, **k):
            raise AssertionError("the guard must never call input()")
        monkeypatch.setattr("builtins.input", no_input)
        with pytest.raises(fleet.DestructiveActionRefused):
            fleet._confirm_destructive("kill", ["w"], {"w": _rec(spawned_by="sess-B")},
                                       assume_yes=False)

    def test_a_mixed_batch_refuses_naming_only_the_foreign_ones(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        workers = {"mine": _rec(spawned_by="sess-A"), "theirs": _rec(spawned_by="sess-B")}
        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet._confirm_destructive("clean", ["mine", "theirs"], workers, assume_yes=False)
        msg = str(exc.value)
        assert "theirs" in msg and "mine" not in msg

    def test_refusal_names_the_workers_and_their_owners(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet._confirm_destructive("clean", ["victim"], {"victim": _rec(spawned_by="sess-BBBBBBBB")},
                                       assume_yes=False)
        msg = str(exc.value)
        assert "victim" in msg and "sess-BBB" in msg

    def test_unknown_owner_message_explains_itself(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet._confirm_destructive("kill", ["old"], {"old": _rec(spawned_by=None)},
                                       assume_yes=False)
        assert "unknown owner" in str(exc.value)


class TestProvenanceRecorded:
    def test_spawn_records_the_calling_session(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        rec = fleet.new_worker_record("sid", "C:/p", "t", "dontask",
                                      spawned_by=fleet.current_caller_session())
        assert rec["spawned_by"] == "sess-A"

    def test_record_defaults_to_no_owner(self):
        assert fleet.new_worker_record("sid", "C:/p", "t", "dontask")["spawned_by"] is None

    def test_worker_env_strips_the_inherited_session_id(self, monkeypatch):
        # Otherwise a worker running `fleet kill` looks exactly like the
        # manager that spawned it, and can retire its siblings silently.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "manager-session")
        env = fleet._worker_env("pmbot")
        assert "CLAUDE_CODE_SESSION_ID" not in env
        assert env["FLEET_WORKER"] == "pmbot"


class TestCliIntegration:
    def _write(self, home, workers):
        (home / "state" / "fleet.json").write_text(
            json.dumps({"workers": workers}), encoding="utf-8")

    # posix-port campaign, Class 3 [TEST DEFECT -- stale seam].
    #
    # These three cases monkeypatched `fleet._stop_native_session`. That seam
    # has been DEAD since the M5/T12 fix wave taught `_cmd_kill_native` to
    # call `_stop_native_session_status` directly (it needs the outcome
    # string, not just the bool). The patch bound a name nothing under test
    # calls, so `cmd_kill` ran with `run=subprocess.run` and
    # `which=shutil.which` defaults and REALLY SHELLED OUT to the operator's
    # `claude` binary. Verified on Windows: `_stop_native_session_status`
    # executed `['C:\\Users\\...\\claude.EXE', 'stop', 'sess']`. It passed
    # only because a real `claude` happened to be on PATH and answered `No
    # job matching 'sess'`, which `_classify_native_cli_result` reads as
    # "gone" -> success. On a box without the CLI (the Linux box this
    # campaign ran on) it resolved to `(False, "no-claude")` and `cmd_kill`
    # returned 1.
    #
    # So this is NOT a posix gap and NOT an environment problem to guard
    # around: it is a unit test that silently depended on a live external
    # binary, on every platform, and the missing `claude` merely made the
    # dependency visible. Fixed at the root -- `run` and `which` are injected
    # through `cmd_kill`'s own parameters, which is the real seam, so nothing
    # here can reach a subprocess at all. Strictly more coverage than before:
    # the stop is now asserted to have HAPPENED (and the foreign-refusal
    # tripwire, which could never have fired, now can).

    @staticmethod
    def _stop_ok_run(stops):
        """A `subprocess.run` stand-in that answers every `claude stop` with a
        clean exit (which `_classify_native_cli_result` reads as "ok")."""
        def run(argv, **kw):
            stops.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return run

    @staticmethod
    def _tripwire_run(*a, **k):
        raise AssertionError("kill must be refused before any session is stopped")

    _WHICH = staticmethod(lambda _name: "/usr/bin/claude")

    def test_kill_refuses_a_foreign_worker_non_interactively(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        self._write(home, {"victim": _rec(spawned_by="sess-B", status="idle")})

        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_kill(argparse.Namespace(name="victim", yes=False),
                           run=self._tripwire_run, which=self._WHICH)

        # Untouched.
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"]["victim"]["status"] == "idle"

    def test_kill_proceeds_on_your_own_worker(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        self._write(home, {"mine": _rec(spawned_by="sess-A", status="idle")})

        stops = []
        rc = fleet.cmd_kill(argparse.Namespace(name="mine", yes=False),
                            run=self._stop_ok_run(stops), which=self._WHICH)

        assert rc == 0
        assert [argv[1] for argv in stops] == ["stop"], stops
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"]["mine"]["status"] == "dead"

    def test_kill_foreign_with_yes_proceeds(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        self._write(home, {"victim": _rec(spawned_by="sess-B", status="idle")})

        stops = []
        rc = fleet.cmd_kill(argparse.Namespace(name="victim", yes=True),
                            run=self._stop_ok_run(stops), which=self._WHICH)
        assert rc == 0
        assert [argv[1] for argv in stops] == ["stop"], stops

    def test_kill_never_resolves_a_claude_executable_off_path(self, home, monkeypatch):
        """The regression guard for the stale seam itself. `cmd_kill` must
        route its stop through the `run`/`which` it was GIVEN -- if a future
        refactor moves the call to another helper that ignores them, this
        test goes red instead of quietly shelling out to a real `claude`
        again. `which` returning None is the shape of a box with no CLI: the
        stop cannot be verified, so kill still marks the worker dead (kill is
        terminal) and reports 1 -- which is the correct behaviour there, and
        was the actual Linux symptom."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        self._write(home, {"mine": _rec(spawned_by="sess-A", status="idle")})

        rc = fleet.cmd_kill(argparse.Namespace(name="mine", yes=False),
                            run=self._tripwire_run, which=lambda _name: None)

        assert rc == 1
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"]["mine"]["status"] == "dead"

    def test_clean_refuses_to_sweep_foreign_dead_workers(self, home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        monkeypatch.setattr(fleet, "recompute_worker_native", lambda n, r, entries: dict(r, status="dead"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [{"sessionId": "sid-1", "status": "idle", "state": "idle"}]))
        self._write(home, {"victim": _rec(spawned_by="sess-B", status="dead")})

        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_clean(argparse.Namespace(yes=False))

        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert "victim" in data["workers"], "clean must not delete a refused worker"

    def test_clean_sweeps_your_own_dead_workers_without_asking(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        monkeypatch.setattr(fleet, "recompute_worker_native", lambda n, r, entries: dict(r, status="dead"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [{"sessionId": "sid-1", "status": "idle", "state": "idle"}]))
        self._write(home, {"mine": _rec(spawned_by="sess-A", status="dead")})

        rc = fleet.cmd_clean(argparse.Namespace(yes=False))

        assert rc == 0
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"] == {}

    def test_clean_refuses_the_whole_batch_when_one_worker_is_foreign(self, home, monkeypatch):
        # A batch that mixes yours and theirs must not half-delete.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        monkeypatch.setattr(fleet, "recompute_worker_native", lambda n, r, entries: dict(r, status="dead"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [{"sessionId": "s1", "status": "idle", "state": "idle"}]))
        self._write(home, {"mine": _rec(spawned_by="sess-A", status="dead", session_id="s1"),
                           "theirs": _rec(spawned_by="sess-B", status="dead", session_id="s2")})

        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_clean(argparse.Namespace(yes=False))

        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert set(data["workers"]) == {"mine", "theirs"}

    def test_clean_with_nothing_dead_never_prompts(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        monkeypatch.setattr(fleet, "recompute_worker_native", lambda n, r, entries: dict(r, status="idle"))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, [{"sessionId": "sid-1", "status": "idle", "state": "idle"}]))
        self._write(home, {"theirs": _rec(spawned_by="sess-B", status="idle")})

        assert fleet.cmd_clean(argparse.Namespace(yes=False)) == 0


class TestRespawnDoesNotLaunderOwnership:
    def test_respawn_carries_the_original_owner_forward(self):
        # Respawning someone else's worker must not make it yours -- otherwise
        # `respawn --force` then `kill` is a two-step laundering of the guard.
        old = _rec(spawned_by="sess-B", status="idle")
        new = fleet.new_worker_record("new-sid", old["cwd"], old["task"], old["mode"])
        new["spawned_by"] = old.get("spawned_by")
        assert new["spawned_by"] == "sess-B"

    def test_respawn_refuses_a_foreign_worker_non_interactively(self, home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        monkeypatch.setattr(fleet, "_require_instance_settings", lambda: None)
        (home / "state" / "fleet.json").write_text(
            json.dumps({"workers": {"victim": _rec(spawned_by="sess-B", status="idle")}}),
            encoding="utf-8")

        args = argparse.Namespace(name="victim", task=None, force=False, yes=False)
        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_respawn(args, sleep=lambda s: None)


class TestRealCliRefusesCleanly:
    """Drive the actual CLI as an agent would: subprocess, no stdin, exit code.

    The first cut of this guard prompted when it thought it was interactive.
    Under Git Bash, `< /dev/null` opens NUL -- a character device -- so
    `isatty()` said True, `input()` hit EOF, and the operator got an
    EOFError traceback instead of a refusal. The worker survived, but only
    by accident of the crash."""

    def _seed(self, tmp_path, spawned_by):
        for sub in ("state", "mailbox", "logs"):
            (tmp_path / sub).mkdir(exist_ok=True)
        (tmp_path / "state" / "fleet.json").write_text(json.dumps(
            {"workers": {"victim": _rec(spawned_by=spawned_by, status="idle")}}), encoding="utf-8")

    def _run(self, tmp_path, *argv, session="an-agent"):
        import os
        import subprocess
        env = {**os.environ, "FLEET_HOME": str(tmp_path), "CLAUDE_CODE_SESSION_ID": session}
        return subprocess.run(
            [sys.executable, str(Path(fleet.__file__)), *argv],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)

    def test_agent_killing_a_foreign_worker_exits_1_with_a_clean_message(self, tmp_path):
        self._seed(tmp_path, spawned_by="a-different-session")
        out = self._run(tmp_path, "kill", "victim")
        assert out.returncode == 1
        assert "Traceback" not in out.stderr, out.stderr
        assert "EOFError" not in out.stderr
        assert "--yes" in (out.stdout + out.stderr)
        survivor = json.loads((tmp_path / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert survivor["workers"]["victim"]["status"] == "idle"

    def test_agent_killing_its_own_worker_succeeds(self, tmp_path):
        # session_id=None with a long-expired claim: the real CLI proceeds
        # straight to the terminal dead mark without shelling out a
        # `claude stop` (no live session for this fabricated worker).
        self._seed(tmp_path, spawned_by="an-agent")
        data = json.loads((tmp_path / "state" / "fleet.json").read_text(encoding="utf-8"))
        data["workers"]["victim"]["session_id"] = None
        (tmp_path / "state" / "fleet.json").write_text(json.dumps(data), encoding="utf-8")
        out = self._run(tmp_path, "kill", "victim")
        assert out.returncode == 0, out.stderr
        data = json.loads((tmp_path / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"]["victim"]["status"] == "dead"


class TestParserFlags:
    @pytest.mark.parametrize("argv", [
        ["kill", "w", "--yes"],
        ["clean", "--yes"],
        ["respawn", "w", "--yes"],
    ])
    def test_yes_flag_parses(self, argv):
        assert fleet.build_parser().parse_args(argv).yes is True

    @pytest.mark.parametrize("argv", [["kill", "w"], ["clean"], ["respawn", "w"]])
    def test_yes_defaults_off(self, argv):
        assert fleet.build_parser().parse_args(argv).yes is False

    def test_interrupt_has_no_yes_flag(self):
        # interrupt kills a TURN, not a worker; the transcript survives. It is
        # deliberately exempt from the guard.
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["interrupt", "w", "--yes"])
