"""sup-spawn build -- fix wave 1 (dual-lens gate findings, 2026-07-24).

CRIT-1  pipe-name crashes in EVERY name-keyed fs path (WinError 123), not just
        task files -> one helper `name_fs_stem`, used by every consumer.
CRIT-2  respawn/kill of the resolved supervisor CLAIM-HOLDER fail CLOSED until
        three-tier §10.4 is built (council rejected the bare body swap 4-0).
        Interrupt stays allowed: turn-kill, transcript survives, no claim
        transition (rb MIN-2 scope call, disclosed).
CRIT-3  the resolver's no-claim/released arm is PINNED (FI-4 for real).
MAJ-2   boot ritual follows the class-4 nonce doctrine (redirect to file,
        grep -- never read a secret off the stream tail) + MIN-4 verdict table.
rb MIN-3 sup-spawn success print echoes CLAUDE_CODE_SUBAGENT_MODEL.

Fault-injection targets (mutate -> confirm red -> restore, tt-build convention):
  FI-6 resolver no-claim/released arm    (TestResolverNoClaimArmPin)
  FI-7 kill/respawn fail-closed guard    (TestSupervisorLifecycleFailClosed)
"""
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
SID = "aaaabbbb-1111-2222-3333-444455556666"
HOLDER_SID = "99998888-7777-6666-5555-444433332222"
NEW_SID = "eeeeffff-1111-2222-3333-444455556666"
SUP_PIPE = "sup|inc-1|boot"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="sup|inc|boot", state="working",
                      status="busy", pid=1234, kind="background"):
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def _fake_run_factory(stdout="backgrounded · aaaabbbb · sup\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


def _roster_sequence(*results):
    state = {"n": 0}
    def fetch(**_):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        return results[i]
    return fetch


def _roster_with(sid=SID, **kw):
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [make_roster_entry(sid, **kw)]
    return fetch


def _sup_args(**kw):
    base = dict(task="run the campaign", model=None, permission_mode=None, nonce=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _happy_spawn(native_home, monkeypatch, args=None, calls=None):
    monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
    return fleet.cmd_sup_spawn(args or _sup_args(),
                               run=_fake_run_factory(calls=calls),
                               which=lambda _: "claude", sleep=lambda s: None)


def _the_one_worker():
    workers = fleet.load_registry()["workers"]
    assert len(workers) == 1, workers
    name = next(iter(workers))
    return name, workers[name]


def _held_claim(sid=HOLDER_SID, **extra):
    claim = {"incarnation_id": "inc-held", "session_id": sid,
             "claimed_at": fleet.now_iso(), "heartbeat_at": fleet.now_iso(),
             "claimed_via": "fresh", "nonce_hash": "deadbeef", "nonce_seq": 1,
             "lineage_id": "lin-x"}
    claim.update(extra)
    (fleet.FLEET_HOME / "supervisor").mkdir(exist_ok=True)
    fleet.write_incarnation(claim)
    return claim


def _seed_pipe_worker(sid=SID, name=SUP_PIPE, status="idle", **over):
    rec = fleet.new_worker_record(sid, "C:/x", "campaign", "bypass",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
    rec.update(over)
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _events_kinds():
    path = fleet.FLEET_HOME / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["kind"]
            for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# CRIT-1: one helper, every consumer.
# ---------------------------------------------------------------------------
class TestNameFsStem:
    def test_maps_pipe_to_tilde(self):
        assert fleet.name_fs_stem(SUP_PIPE) == "sup~inc-1~boot"

    def test_plain_names_pass_through(self):
        assert fleet.name_fs_stem("w1") == "w1"

    def test_task_file_path_routes_through_the_helper(self):
        # CRIT-1's centralization contract: the pre-existing inline mapping in
        # task_file_path is refactored ONTO the one helper, not duplicated.
        assert "name_fs_stem" in inspect.getsource(fleet.task_file_path)


class TestPipeNameOutcomeStore:
    """CRIT-1 consumer class: outcomes/tombstones. Pre-fix,
    write_tombstone_outcome appended to state/outcomes/sup|<id>|boot.jsonl ->
    WinError 123 mid-kill, leaving the registry `working` for a stopped
    session."""

    def test_outcome_path_maps_a_name_key(self, native_home):
        assert fleet.outcome_path(SUP_PIPE).name == "sup~inc-1~boot.jsonl"

    def test_outcome_path_sid_keys_unchanged(self, native_home):
        assert fleet.outcome_path(SID).name == f"{SID}.jsonl"

    def test_tombstone_roundtrip_with_pipe_name(self, native_home):
        fleet.write_tombstone_outcome(SUP_PIPE, SID, "killed")
        recs = fleet.read_outcomes(SUP_PIPE, sid=SID)
        assert [r["kind"] for r in recs] == ["killed"]


class TestPipeNameJournalPath:
    """CRIT-1 consumer class: journals (rb MIN-1 -- compose_prompt's
    journal-duty path told the body to write a `|` path it never could)."""

    def test_journal_file_path_maps(self, native_home):
        assert fleet.journal_file_path(SUP_PIPE).name == "sup~inc-1~boot.md"
        assert fleet.journal_file_path("w1").name == "w1.md"

    def test_compose_prompt_journal_target_is_mapped(self, native_home):
        prompt, _ = fleet.compose_prompt(SUP_PIPE, "C:/x", "task", None)
        assert "sup~inc-1~boot.md" in prompt
        assert "sup|inc-1|boot.md" not in prompt


class TestPipeNameArchivePaths:
    """CRIT-1 consumer class: archive dest dirs + _archive_file_pairs
    (MAJ-1/rs-MIN)."""

    def test_archive_dest_dir_mapped(self, native_home):
        assert fleet._archive_dest_dir(SUP_PIPE).name == "sup~inc-1~boot"

    def test_archive_dest_dir_collision_suffix_mapped(self, native_home):
        fleet.archive_root().mkdir(parents=True, exist_ok=True)
        (fleet.archive_root() / "sup~inc-1~boot").mkdir()
        assert fleet._archive_dest_dir(SUP_PIPE).name == "sup~inc-1~boot.1"

    def test_archive_file_pairs_all_pipe_free(self, native_home):
        for src, dest in fleet._archive_file_pairs(SUP_PIPE, SID, ["r-sid"]):
            assert "|" not in src.name, src
            assert "|" not in dest, dest


class TestPipeNameCleanSweep:
    """CRIT-1 consumer class: _remove_worker_files must sweep the MAPPED
    artifacts (pre-fix it unlinked raw `|` paths -- OSError swallowed, files
    survived as permanent litter)."""

    def test_sweeps_mapped_artifacts(self, native_home):
        fleet.journals_dir().mkdir(parents=True, exist_ok=True)
        fleet.outcomes_dir().mkdir(parents=True, exist_ok=True)
        fleet.tasks_dir().mkdir(parents=True, exist_ok=True)
        journal = fleet.journals_dir() / "sup~inc-1~boot.md"
        journal.write_text("j", encoding="utf-8")
        outcome = fleet.outcomes_dir() / "sup~inc-1~boot.jsonl"
        outcome.write_text("{}", encoding="utf-8")
        task = fleet.tasks_dir() / "sup~inc-1~boot.md"
        task.write_text("t", encoding="utf-8")
        removed = fleet._remove_worker_files(SUP_PIPE, SID)
        assert not journal.exists()
        assert not outcome.exists()
        assert not task.exists()
        assert len(removed) == 3

    def test_sweeps_mapped_archive_dirs_and_suffixes(self, native_home):
        base = fleet.archive_root() / "sup~inc-1~boot"
        base.mkdir(parents=True)
        (fleet.archive_root() / "sup~inc-1~boot.1").mkdir()
        fleet._remove_worker_files(SUP_PIPE, SID)
        assert not base.exists()
        assert not (fleet.archive_root() / "sup~inc-1~boot.1").exists()


class TestSupervisorShapedLifecycleChoreography:
    """CRIT-1's completion contract: kill/interrupt/respawn --force must run
    to completion (registry marked, event written, tombstone durable) for a
    supervisor-shaped name -- pre-fix each crashed at its
    write_tombstone_outcome site (:4652 interrupt, :4836 respawn --force,
    kill's own)."""

    def test_kill_nonholder_husk_completes(self, native_home, monkeypatch):
        # A supervisor-shaped husk that does NOT hold the claim is killable
        # by its real name (also CRIT-2's fourth red test).
        _held_claim(session_id=HOLDER_SID)
        _seed_pipe_worker(sid=HOLDER_SID, name="sup|inc-2|successor",
                          status="working")     # the real holder
        _seed_pipe_worker(sid=SID, status="dead-suspected")   # the husk
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        rc = fleet.cmd_kill(SimpleNamespace(name=SUP_PIPE, yes=True, nonce=None))
        assert rc == 0
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert rec["status"] == "dead"
        assert any(r["kind"] == "killed"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=SID))
        assert "killed" in _events_kinds()

    def test_interrupt_supervisor_shaped_completes(self, native_home, monkeypatch):
        _seed_pipe_worker(status="working")
        monkeypatch.setattr(fleet, "_stop_native_session", lambda *a, **k: True)
        rc = fleet.cmd_interrupt(SimpleNamespace(name=SUP_PIPE, nonce=None))
        assert rc == 0
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert rec["status"] == "interrupted"
        assert any(r["kind"] == "interrupted"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=SID))
        assert "interrupted" in _events_kinds()

    def test_interrupt_of_claim_holder_stays_allowed(self, native_home, monkeypatch):
        # CRIT-2 scope call (rb MIN-2, disclosed): interrupt is a turn-kill --
        # transcript survives, no claim transition -- so it is NOT gated on
        # the unbuilt §10.4 choreography.
        _held_claim(session_id=SID)
        _seed_pipe_worker(sid=SID, status="working")
        monkeypatch.setattr(fleet, "_stop_native_session", lambda *a, **k: True)
        rc = fleet.cmd_interrupt(SimpleNamespace(name="supervisor", nonce=None))
        assert rc == 0
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "interrupted"

    def test_respawn_force_completes_with_pipe_name(self, native_home, monkeypatch):
        # No claim held: the husk respawn path itself (CRIT-1 site :4836).
        old_sid = SID
        journal = fleet.journals_dir() / "sup~inc-1~boot.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("JOURNAL-SENTINEL-77", encoding="utf-8")
        _seed_pipe_worker(sid=old_sid, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, [make_roster_entry(old_sid)]),
            (True, []),
            (True, []),
            (True, [make_roster_entry(NEW_SID, status="idle")]),
        ))
        rc = fleet.cmd_respawn(
            SimpleNamespace(name=SUP_PIPE, task=None, force=True, yes=True,
                            nonce=None, max_budget_usd=None,
                            setting_sources=None, token_ceiling=None),
            run=_fake_run_factory(stdout="backgrounded · eeeeffff · sup\n"),
            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert rec["session_id"] == NEW_SID
        assert old_sid in rec["retired_sids"]
        assert any(r["kind"] == "stopped"
                   for r in fleet.read_outcomes(SUP_PIPE, sid=old_sid))
        # The respawn prompt carried the MAPPED journal's content.
        task_text = fleet.task_file_path(SUP_PIPE).read_text(encoding="utf-8")
        assert "JOURNAL-SENTINEL-77" in task_text


# ---------------------------------------------------------------------------
# CRIT-2: kill/respawn of the supervisor claim-holder FAIL CLOSED. FI-7.
# ---------------------------------------------------------------------------
class TestSupervisorLifecycleFailClosed:
    def _holder(self, sid=HOLDER_SID):
        _held_claim(session_id=sid)
        return _seed_pipe_worker(sid=sid, status="working")

    def test_respawn_supervisor_refused(self, native_home):
        self._holder()
        with pytest.raises(fleet.FleetCliError, match=r"10\.4.*not built"):
            fleet.cmd_respawn(SimpleNamespace(
                name="supervisor", task=None, force=True, yes=True, nonce=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None))
        # Nothing was retired: record untouched.
        rec = fleet.load_registry()["workers"][SUP_PIPE]
        assert rec["session_id"] == HOLDER_SID
        assert rec["status"] == "working"

    def test_kill_supervisor_refused(self, native_home):
        self._holder()
        with pytest.raises(fleet.FleetCliError, match=r"10\.4.*not built"):
            fleet.cmd_kill(SimpleNamespace(name="supervisor", yes=True, nonce=None))
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "working"
        assert "killed" not in _events_kinds()

    def test_kill_holder_by_real_name_also_refused(self, native_home):
        """FI-7 (recorded fault injection): a guard keyed on the LITERAL
        'supervisor' target instead of the resolved claim-holder record goes
        red here -- addressing the holder by its pipe name would bare-swap it
        straight past the refusal. Injection: condition the refusal on
        `args.name == SUPERVISOR_BODY_NAME` checked before resolution;
        confirmed red 2026-07-24; restored."""
        self._holder()
        with pytest.raises(fleet.FleetCliError, match=r"10\.4.*not built"):
            fleet.cmd_kill(SimpleNamespace(name=SUP_PIPE, yes=True, nonce=None))

    def test_kill_ordinary_worker_unaffected(self, native_home, monkeypatch):
        self._holder()
        _seed_pipe_worker(sid=NEW_SID, name="w1", status="idle")
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        rc = fleet.cmd_kill(SimpleNamespace(name="w1", yes=True, nonce=None))
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"

    def test_refusal_names_the_escape_hatches(self, native_home):
        self._holder()
        with pytest.raises(fleet.FleetCliError, match="sup-release"):
            fleet.cmd_kill(SimpleNamespace(name="supervisor", yes=True, nonce=None))

    def test_indeterminate_holder_fails_toward_refusal_for_sup_shaped(self, native_home):
        """The guard's asymmetric None arm (claim held, holder sid
        unreadable): fail TOWARD refusal, but only for supervisor-shaped
        names. FI-7b (recorded fault injection): deleting the
        `holder is None and ...` conjunct from
        _refuse_unbuilt_supervisor_lifecycle left every other FailClosed
        test green; THIS test went red (the maybe-holder body was killed on
        an unreadable INCARNATION). Confirmed red 2026-07-24; restored."""
        _held_claim(session_id="")          # claim with no readable holder sid
        _seed_pipe_worker(sid=SID, status="working")
        with pytest.raises(fleet.FleetCliError, match=r"10\.4.*not built"):
            fleet.cmd_kill(SimpleNamespace(name=SUP_PIPE, yes=True, nonce=None))

    def test_indeterminate_holder_never_freezes_ordinary_kills(self, native_home, monkeypatch):
        _held_claim(session_id="")          # unreadable holder sid
        _seed_pipe_worker(sid=NEW_SID, name="w1", status="idle")
        monkeypatch.setattr(fleet, "_stop_native_session_status",
                            lambda *a, **k: (True, "gone"))
        rc = fleet.cmd_kill(SimpleNamespace(name="w1", yes=True, nonce=None))
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"


# ---------------------------------------------------------------------------
# CRIT-3: pin the resolver's no-claim/released arm (FI-4 for real). FI-6.
# ---------------------------------------------------------------------------
class TestResolverNoClaimArmPin:
    def test_released_claim_squatting_husk_refusal_names_the_claim(self, native_home):
        """FI-6 (recorded fault injection): fault-injecting a shape-guessing
        fallback into the no-claim/released arm (scan load_registry() for the
        first `_is_supervisor_shaped` name and return it) left the whole
        pre-wave suite green -- the squatting DEAD husk would have been
        killed. THIS test goes red under that injection: the husk resolves,
        `kill` proceeds, and the asserted released-claim refusal never
        raises. Injection re-run against this test 2026-07-24: red as
        required; restored."""
        (native_home / "supervisor").mkdir(exist_ok=True)
        fleet.write_incarnation({"incarnation_id": "inc-rel", "state": "released",
                                 "released_at": fleet.now_iso()})
        _seed_pipe_worker(sid=SID, status="dead")      # the squatting husk
        with pytest.raises(fleet.FleetCliError) as ei:
            fleet.cmd_kill(SimpleNamespace(name="supervisor", yes=True, nonce=None))
        msg = str(ei.value)
        assert "released" in msg
        assert "inc-rel" in msg          # the refusal NAMES the released claim
        # The husk was never touched.
        assert fleet.load_registry()["workers"][SUP_PIPE]["status"] == "dead"
        assert fleet.read_outcomes(SUP_PIPE, sid=SID) == []

    def test_empty_registry_no_claim_arm_pinned(self, native_home):
        """Same pin for the empty-registry arm: no claim, no workers at all --
        the refusal must state no claim exists, never fall through to a shape
        guess (under FI-6's injection this becomes `unknown worker` instead
        and goes red)."""
        with pytest.raises(fleet.FleetCliError, match="no supervisor claim"):
            fleet.cmd_kill(SimpleNamespace(name="supervisor", yes=True, nonce=None))


# ---------------------------------------------------------------------------
# MAJ-2 + MIN-4: class-4 nonce doctrine + full verdict enumeration.
# ---------------------------------------------------------------------------
class TestBootRitualNonceDoctrine:
    def _task_text(self, native_home, monkeypatch, **kw):
        assert _happy_spawn(native_home, monkeypatch, **kw) == 0
        name, _ = _the_one_worker()
        return name, fleet.task_file_path(name).read_text(encoding="utf-8")

    def test_sup_boot_redirected_to_file(self, native_home, monkeypatch):
        name, text = self._task_text(native_home, monkeypatch)
        assert "sup-boot > " in text
        # Fix wave 2 NEW-2 quoted the redirect target; the pin follows.
        assert 'boot-bundle.txt" 2>&1' in text
        # The redirect target is the MAPPED (pipe-free) stem -- a `|` in the
        # rendered command would be a shell pipe, not a filename.
        assert fleet.name_fs_stem(name) in text

    def test_nonce_read_by_grep_never_stream_tail(self, native_home, monkeypatch):
        _, text = self._task_text(native_home, monkeypatch)
        assert "grep" in text
        assert "NONCE" in text
        assert "LAST line" not in text          # the class-4 violation, gone

    def test_all_verdicts_enumerated_with_reactions(self, native_home, monkeypatch):
        _, text = self._task_text(native_home, monkeypatch)
        for verdict in ("claim", "seize", "limit-transfer"):
            assert verdict in text, verdict
        assert "exit 2" in text and "SUP-BOOT-REFUSED" in text
        assert "exit 3" in text and "SUP-BOOT-FROZEN" in text


# ---------------------------------------------------------------------------
# rb MIN-3: sup-spawn success print echoes CLAUDE_CODE_SUBAGENT_MODEL the way
# cmd_spawn does (design §6: print the resolution).
# ---------------------------------------------------------------------------
class TestSupSpawnSubagentModelEcho:
    def test_env_echoed_on_success(self, native_home, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "claude-echo-test")
        assert _happy_spawn(native_home, monkeypatch) == 0
        out = capsys.readouterr().out
        assert "CLAUDE_CODE_SUBAGENT_MODEL=claude-echo-test" in out

    def test_absent_env_prints_plain_model_line(self, native_home, monkeypatch, capsys):
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
        assert _happy_spawn(native_home, monkeypatch) == 0
        out = capsys.readouterr().out
        assert "model:" in out
        assert "CLAUDE_CODE_SUBAGENT_MODEL" not in out
