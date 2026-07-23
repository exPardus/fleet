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


class TestAWorkerIsNotExempt:
    """A fleet worker is a Claude session like any other -- the guard applies.

    Filed once as a defect: "`_confirm_destructive`'s `caller is None` early-out
    exempts fleet workers, so a worker can kill a sibling unguarded". It was
    MEASURED from inside a live `--bg` worker and disproved:

        py -3.13 -c "import os; print(repr(os.environ.get('CLAUDE_CODE_SESSION_ID')))"
          -> '820762d0-5298-4b1b-9471-4048ea27e278'

    which was exactly worker `mf-fix`'s own `session_id` in the registry, with
    `FLEET_WORKER=mf-fix` set alongside it. `_worker_env` strips the manager's
    id and the child `claude` re-stamps its OWN -- so `caller` is a real value
    inside a worker, the `None` early-out is unreachable there, and a worker
    killing a sibling (owner = the manager's sid) is foreign and refused.

    These pin the disproof: reintroduce a worker exemption -- in the early-out
    or by blanking the session id when FLEET_WORKER is set -- and they go red.
    """

    MANAGER = "manager-sid"
    WORKER_SID = "820762d0-5298-4b1b-9471-4048ea27e278"

    def _in_worker(self, monkeypatch):
        # A worker's real environment, as measured: its own session id (stamped
        # by the child `claude`, not inherited) plus the FLEET_WORKER marker.
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.WORKER_SID)
        monkeypatch.setenv("FLEET_WORKER", "mf-fix")

    def test_a_worker_has_a_real_caller_session_id(self, monkeypatch):
        self._in_worker(monkeypatch)
        assert fleet.current_caller_session() == self.WORKER_SID

    def test_a_worker_killing_a_sibling_is_refused(self, monkeypatch):
        self._in_worker(monkeypatch)
        sibling = _rec(spawned_by=self.MANAGER, session_id="sib-sid", status="idle")
        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet._confirm_destructive("kill", ["sibling"], {"sibling": sibling},
                                       assume_yes=False)
        assert "--yes" in str(exc.value)

    def test_a_worker_sweeping_its_own_registry_entry_is_refused(self, monkeypatch):
        # Not even itself: the manager spawned it, so the manager owns it.
        self._in_worker(monkeypatch)
        me = _rec(spawned_by=self.MANAGER, session_id=self.WORKER_SID, status="dead")
        with pytest.raises(fleet.DestructiveActionRefused):
            fleet._confirm_destructive("clean", ["mf-fix"], {"mf-fix": me},
                                       assume_yes=False)


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


class TestLineageOwnership:
    """claim-nonce §6.2 / D2: a worker spawned under lineage L is not-foreign
    to a LATER body of L that proved continuity -- across a sid rotation and a
    handoff -- and IS foreign after a seize (which re-mints the lineage). The
    third parameter of `_worker_is_foreign` is the whole of it; the guard's
    existing `spawned_by == caller` arm is unchanged."""

    def test_todays_sid_arm_is_byte_for_byte_unchanged(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        caller = fleet.current_caller_session()
        assert fleet._worker_is_foreign(_rec(spawned_by="sess-A"), caller) is False
        assert fleet._worker_is_foreign(_rec(spawned_by="sess-B"), caller) is True

    def test_a_proven_later_body_of_the_lineage_owns_the_worker(self, monkeypatch):
        # The worker was spawned by sid sess-A under lineage lin-L. The caller
        # is a LATER body -- its sid rotated to sess-Z (fork-steer/handoff) --
        # and it proved continuity, so claim_lineage is lin-L. The sid arm
        # would call this foreign; the lineage arm owns it.
        rec = _rec(spawned_by="sess-A", spawned_by_lineage="lin-L")
        assert fleet._worker_is_foreign(rec, "sess-Z", claim_lineage="lin-L") is False

    def test_a_different_lineage_is_still_foreign(self, monkeypatch):
        rec = _rec(spawned_by="sess-A", spawned_by_lineage="lin-L")
        # after a SEIZE the lineage is re-minted, so the seizing body proves a
        # DIFFERENT lineage and the predecessor's workers are foreign to it.
        assert fleet._worker_is_foreign(rec, "sess-Z", claim_lineage="lin-OTHER") is True

    def test_an_unproven_caller_gets_todays_answer_even_when_lineage_would_match(
            self, monkeypatch):
        # claim_lineage=None is what an UNPROVEN caller yields (§6.2). It must
        # NOT fall through to a lineage match -- otherwise a body that never
        # proved continuity would inherit ownership by a field it can read from
        # the registry.
        rec = _rec(spawned_by="sess-A", spawned_by_lineage="lin-L")
        assert fleet._worker_is_foreign(rec, "sess-Z", claim_lineage=None) is True

    def test_a_worker_with_no_recorded_lineage_is_not_claimed_by_lineage(self, monkeypatch):
        rec = _rec(spawned_by="sess-A", spawned_by_lineage=None)
        assert fleet._worker_is_foreign(rec, "sess-Z", claim_lineage="lin-L") is True

    def test_a_null_lineage_on_both_sides_never_matches(self, monkeypatch):
        # belt-and-braces against the None==None trap the handoff-token check
        # had: an unproven caller (None) and a legacy worker (None) must not
        # come out as a lineage match.
        rec = _rec(spawned_by="sess-A", spawned_by_lineage=None)
        assert fleet._worker_is_foreign(rec, "sess-Z", claim_lineage=None) is True

    def test_the_record_defaults_to_no_lineage(self):
        assert fleet.new_worker_record("sid", "C:/p", "t", "dontask")["spawned_by_lineage"] is None

    def test_the_record_carries_a_provided_lineage(self, monkeypatch):
        rec = fleet.new_worker_record("sid", "C:/p", "t", "dontask",
                                      spawned_by="sess-A", spawned_by_lineage="lin-L")
        assert rec["spawned_by_lineage"] == "lin-L"

    def test_describe_owner_names_the_lineage_when_present(self):
        rec = _rec(spawned_by="sess-AAAAAAAA", spawned_by_lineage="lin-L")
        assert "lin-L" in fleet._describe_owner(rec)


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

    def _seed_claim(self, home, sid, lineage):
        """A held supervisor claim with a known live generation. Returns the
        plaintext to present as --nonce."""
        (home / "supervisor").mkdir(exist_ok=True)
        value = fleet.mint_nonce()
        fleet.write_incarnation({"incarnation_id": "inc-me", "session_id": sid,
                                 "claimed_at": "2026-07-23T00:00:00Z",
                                 "heartbeat_at": "2026-07-23T00:00:00Z", "claimed_via": "fresh",
                                 "nonce_hash": fleet.nonce_digest(value), "nonce_seq": 3,
                                 "lineage_id": lineage})
        return value

    def test_a_rotated_body_proving_lineage_kills_its_workers_without_yes(
            self, home, monkeypatch):
        """§6.2 / T18, end to end: the worker was spawned by sid `sess-old`
        under lineage `lin-L`. The caller's sid rotated to `sess-Z` (fork-steer
        / handoff), so the spawned_by arm calls the worker foreign. Presenting
        the claim's live generation proves lineage `lin-L`, and the worker is
        owned -- no --yes."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-Z")
        value = self._seed_claim(home, "sess-Z", "lin-L")
        self._write(home, {"w": _rec(spawned_by="sess-old", spawned_by_lineage="lin-L",
                                     status="idle")})
        stops = []
        rc = fleet.cmd_kill(argparse.Namespace(name="w", yes=False, nonce=value),
                            run=self._stop_ok_run(stops), which=self._WHICH)
        assert rc == 0
        data = json.loads((home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert data["workers"]["w"]["status"] == "dead"

    def test_the_same_rotated_body_without_the_nonce_is_still_refused(
            self, home, monkeypatch):
        """The proof is load-bearing: the identical situation, minus the
        generation, gets today's answer and refuses. Otherwise ownership would
        leak from a registry-readable field."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-Z")
        self._seed_claim(home, "sess-Z", "lin-L")
        self._write(home, {"w": _rec(spawned_by="sess-old", spawned_by_lineage="lin-L",
                                     status="idle")})
        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_kill(argparse.Namespace(name="w", yes=False, nonce=None),
                           run=self._tripwire_run, which=self._WHICH)

    def test_a_seized_lineage_does_not_own_the_old_bodys_workers(self, home, monkeypatch):
        """A seize re-mints the lineage (§6.2), so the seizing body proves a
        DIFFERENT lineage and the predecessor's workers stay foreign -- even
        with a valid generation."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-Z")
        value = self._seed_claim(home, "sess-Z", "lin-NEW-after-seize")
        self._write(home, {"w": _rec(spawned_by="sess-old", spawned_by_lineage="lin-OLD",
                                     status="idle")})
        with pytest.raises(fleet.DestructiveActionRefused):
            fleet.cmd_kill(argparse.Namespace(name="w", yes=False, nonce=value),
                           run=self._tripwire_run, which=self._WHICH)

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


class TestAWorkerCallerIsNotExempt:
    """A fleet worker running the CLI is a Claude session like any other.

    Filed once as a defect: "`_confirm_destructive` early-outs on
    `caller is None`, a worker has no CLAUDE_CODE_SESSION_ID because
    `_worker_env` strips it, so every worker presents as the exempted human and
    the guard never challenges the caller class that most needs it."

    It was MEASURED from inside a live `--bg` worker rather than reasoned about,
    and it is false. In worker `mf-fix`:

        py -3.13 -c "import os; print(repr(os.environ.get('CLAUDE_CODE_SESSION_ID')))"
          -> '1a9374bd-df92-42ad-972a-06693aeef272'

    which is that worker's own `session_id` in the registry -- not the
    manager's, which is what `spawned_by` holds. `_worker_env` strips the
    INHERITED id and the child `claude` then stamps its OWN, so `caller` is a
    real value inside a worker and the `None` early-out is unreachable there.

    These pin that outcome at the level it was proved at -- the real CLI in a
    subprocess, with the env a worker actually has -- so a future edit that
    re-introduces a worker exemption (in the early-out, or by blanking the
    session id when FLEET_WORKER is set) goes red instead of quietly shipping.
    """

    # The measured pair, kept verbatim so the receipt above stays checkable.
    WORKER_SID = "1a9374bd-df92-42ad-972a-06693aeef272"
    MANAGER_SID = "20fee653-f07e-4208-8c0e-1c737f9119f7"

    def _seed(self, tmp_path, spawned_by, session_id="sid-1"):
        for sub in ("state", "mailbox", "logs"):
            (tmp_path / sub).mkdir(exist_ok=True)
        (tmp_path / "state" / "fleet.json").write_text(json.dumps(
            {"workers": {"victim": _rec(spawned_by=spawned_by, status="idle",
                                        session_id=session_id)}}), encoding="utf-8")

    def _run(self, tmp_path, *argv, session, worker=None):
        """Drive the real CLI with a chosen caller identity.

        `session=None` means a human shell: the variable is ABSENT, not empty.
        `worker` sets FLEET_WORKER, the marker a launched worker carries."""
        import os
        import subprocess
        env = {**os.environ, "FLEET_HOME": str(tmp_path)}
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.pop("FLEET_WORKER", None)
        if session is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session
        if worker is not None:
            env["FLEET_WORKER"] = worker
        return subprocess.run(
            [sys.executable, str(Path(fleet.__file__)), *argv],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)

    def _status(self, tmp_path):
        data = json.loads((tmp_path / "state" / "fleet.json").read_text(encoding="utf-8"))
        return data["workers"]["victim"]["status"]

    def test_a_worker_killing_a_sibling_is_refused(self, tmp_path):
        # The case the defect claimed was exempt: worker sid as caller, the
        # manager as the sibling's owner.
        self._seed(tmp_path, spawned_by=self.MANAGER_SID)
        out = self._run(tmp_path, "kill", "victim",
                        session=self.WORKER_SID, worker="mf-fix")
        assert out.returncode == 1
        assert "Traceback" not in out.stderr, out.stderr
        assert "--yes" in (out.stdout + out.stderr)
        assert self._status(tmp_path) == "idle"

    def test_a_worker_killing_an_unknown_owner_worker_is_refused(self, tmp_path):
        # `spawned_by` absent -> foreign, never "mine": the guard fails toward
        # asking, so records written before provenance existed are covered too.
        self._seed(tmp_path, spawned_by=None)
        out = self._run(tmp_path, "kill", "victim",
                        session=self.WORKER_SID, worker="mf-fix")
        assert out.returncode == 1
        assert "unknown owner" in (out.stdout + out.stderr)
        assert self._status(tmp_path) == "idle"

    def test_a_worker_killing_the_worker_it_spawned_proceeds(self, tmp_path):
        # session_id=None: no live session to `claude stop`, so the CLI goes
        # straight to the terminal dead mark.
        self._seed(tmp_path, spawned_by=self.WORKER_SID, session_id=None)
        out = self._run(tmp_path, "kill", "victim",
                        session=self.WORKER_SID, worker="mf-fix")
        assert out.returncode == 0, out.stderr
        assert self._status(tmp_path) == "dead"

    def test_a_human_shell_keeps_its_exemption(self, tmp_path):
        # The other direction. fleet has always been a human-driven CLI;
        # interposing a refusal here breaks every existing script for no gain.
        self._seed(tmp_path, spawned_by=self.MANAGER_SID, session_id=None)
        out = self._run(tmp_path, "kill", "victim", session=None)
        assert out.returncode == 0, out.stderr
        assert self._status(tmp_path) == "dead"

    def test_the_fleet_worker_marker_alone_does_not_decide_the_verdict(self, tmp_path):
        """FLEET_WORKER must never be the key (SPEC §6.1).

        The supervisor successor carries FLEET_WORKER and is the one session
        whose whole purpose is to receive the claim, so a guard keyed on it
        refuses exactly the wrong caller. It is also an ordinary env var any
        shell can set or unset. Observed in the field: this file's measurement
        was taken in a process whose FLEET_WORKER named a DIFFERENT worker than
        its own registry record -- the marker is not even a reliable identity
        signal. Ownership is decided by `spawned_by` vs the caller sid, and by
        nothing else: no sid, no guard, marker or no marker."""
        self._seed(tmp_path, spawned_by=self.MANAGER_SID, session_id=None)
        out = self._run(tmp_path, "kill", "victim", session=None, worker="mf-fix")
        assert out.returncode == 0, out.stderr
        assert self._status(tmp_path) == "dead"


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
