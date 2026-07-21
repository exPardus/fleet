"""Autoclean tests (docs/specs/autoclean.md): ownership discriminator
(fault-injected), husk sweep gates, tier isolation, tier-3 default-off,
clean tiering split, scheduler install/remove/doctor."""
import argparse
import json
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime.now(timezone.utc)

SID_LIVE = "aaaa1111-1111-2222-3333-444455556666"
SID_RETIRED = "bbbb2222-1111-2222-3333-444455556666"
SID_TOMB = "cccc3333-1111-2222-3333-444455556666"
SID_EVENTS = "dddd4444-1111-2222-3333-444455556666"
SID_ARCHDIR = "eeee5555-1111-2222-3333-444455556666"
SID_FOREIGN = "ffff6666-1111-2222-3333-444455556666"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    fleet.save_registry({"workers": {}})
    return tmp_path


def seed_worker(name, sid, *, status="idle", archived_at=None, retired=(), **overrides):
    rec = fleet.new_worker_record(sid, "C:/proj", "task", "accept", dispatch_kind="bg")
    rec["status"] = status
    rec["archived_at"] = archived_at
    rec["retired_sids"] = list(retired)
    rec["last_activity"] = _iso(NOW - timedelta(minutes=5))
    rec.update(overrides)
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def roster_dead(sid, name="fleet|w|t"):
    return {"id": sid[:8], "sessionId": sid, "name": name, "kind": "background",
            "state": "done"}


def roster_live(sid, name="fleet|w|t"):
    return {"id": sid[:8], "sessionId": sid, "name": name, "kind": "background",
            "state": "working", "status": "busy", "pid": 4242}


def fake_run_factory(roster, calls=None, rm_rc=0):
    stdout = json.dumps(roster)

    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        if len(argv) >= 2 and argv[1] == "agents":
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        return types.SimpleNamespace(returncode=rm_rc, stdout="", stderr="")
    return fake_run


def rm_targets(calls):
    return [argv[2] for argv in calls if len(argv) >= 3 and argv[1] == "rm"]


def read_events(home):
    path = home / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


class TestOwnershipDiscriminator:
    def test_registry_sets(self, home):
        seed_worker("live", SID_LIVE, retired=[SID_RETIRED])
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        data = fleet.load_registry()
        owned, protected = fleet._registry_owned_and_protected_sids(data["workers"])
        assert owned == {SID_LIVE, SID_RETIRED, SID_TOMB}
        assert protected == {SID_LIVE, SID_RETIRED}

    def test_registry_shape_drift_tolerated(self, home):
        workers = {"a": "not-a-dict",
                   "b": {"session_id": 42, "retired_sids": "bare-string"},
                   "c": {"session_id": SID_LIVE, "retired_sids": [7, SID_RETIRED]}}
        owned, protected = fleet._registry_owned_and_protected_sids(workers)
        assert owned == {SID_LIVE, SID_RETIRED}
        assert protected == {SID_LIVE, SID_RETIRED}

    def test_archive_dir_sids(self, home):
        d = fleet.archive_root() / "oldworker"
        d.mkdir(parents=True)
        (d / f"{SID_ARCHDIR}.jsonl").write_text("{}", encoding="utf-8")
        (d / "journal.md").write_text("j", encoding="utf-8")
        (d / "task.md").write_text("t", encoding="utf-8")
        assert fleet._archive_dir_sids() == {SID_ARCHDIR}

    def test_archive_dir_missing(self, home):
        assert fleet._archive_dir_sids() == set()

    def test_events_sids(self, home):
        fleet.append_event("turn_started", "w1", session_id=SID_EVENTS)
        fleet.append_event("spawned", "w1")  # no sid field
        with open(fleet.events_path(), "a", encoding="utf-8") as f:
            f.write("not json\n")
        assert SID_EVENTS in fleet._events_sids()

    def test_events_missing_file(self, home):
        assert fleet._events_sids() == set()


class TestHuskSweep:
    def test_fault_inject_foreign_session_never_selected(self, home):
        """THE ownership test: a roster session fleet has no record of --
        the operator's own interactive session -- must never be rm'd. A
        genuine husk beside it IS rm'd, so removing the owned-set filter
        makes this test fail (the foreign sid would join rm_targets)."""
        fleet.append_event("turn_started", "gone-worker", session_id=SID_EVENTS)
        calls = []
        run = fake_run_factory([roster_dead(SID_FOREIGN, name="operator session"),
                                roster_dead(SID_EVENTS)], calls=calls)
        removed, _deferred = fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        targets = rm_targets(calls)
        assert removed == [SID_EVENTS]
        assert SID_FOREIGN[:8] not in targets and SID_FOREIGN not in targets
        assert SID_EVENTS.split("-", 1)[0] in targets

    def test_foreign_only_roster_no_rm_at_all(self, home):
        calls = []
        run = fake_run_factory([roster_dead(SID_FOREIGN)], calls=calls)
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []
        assert rm_targets(calls) == []

    def test_protected_current_and_retired_sids_spared(self, home):
        seed_worker("live", SID_LIVE, retired=[SID_RETIRED])
        calls = []
        run = fake_run_factory([roster_dead(SID_LIVE), roster_dead(SID_RETIRED)],
                               calls=calls)
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []
        assert rm_targets(calls) == []

    def test_startup_transient_state_only_entry_never_selected(self, home):
        """Live finding 2026-07-16: a freshly dispatched session's roster
        entry is state-only for its first seconds -- the same shape the
        sweep's liveness test reads as dead. Must never be rm'd: its sid
        is the current session_id of a non-archived record, so the
        PROTECTED set covers it regardless of the roster transient (and a
        pre-registry-stamp sid is unowned => default-deny). Pinned
        explicitly so the protection isn't accidental."""
        seed_worker("justborn", SID_LIVE, status="working")
        transient = {"id": SID_LIVE[:8], "sessionId": SID_LIVE,
                     "name": "fleet|justborn|t", "kind": "background",
                     "state": "working"}  # no status, no pid
        calls = []
        run = fake_run_factory([transient], calls=calls)
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []
        assert rm_targets(calls) == []

    def test_tombstone_sid_is_a_husk(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        run = fake_run_factory([roster_dead(SID_TOMB)])
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == [SID_TOMB]

    def test_archive_dir_sid_is_a_husk(self, home):
        d = fleet.archive_root() / "oldworker"
        d.mkdir(parents=True)
        (d / f"{SID_ARCHDIR}.jsonl").write_text("{}", encoding="utf-8")
        run = fake_run_factory([roster_dead(SID_ARCHDIR)])
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == [SID_ARCHDIR]

    def test_live_roster_entry_never_rmd(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        calls = []
        run = fake_run_factory([roster_live(SID_TOMB)], calls=calls)
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []
        assert rm_targets(calls) == []

    def test_pending_mail_spares_husk(self, home):
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        (fleet.mailbox_dir() / f"{SID_EVENTS}.md").write_text("mail!", encoding="utf-8")
        run = fake_run_factory([roster_dead(SID_EVENTS)])
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []

    def test_dry_run_rms_nothing_events_nothing(self, home):
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        events_before = len(read_events(home))
        calls = []
        run = fake_run_factory([roster_dead(SID_EVENTS)], calls=calls)
        assert fleet._sweep_husks(True, run=run, which=lambda _: "claude")[0] == []
        assert rm_targets(calls) == []
        assert len(read_events(home)) == events_before

    def test_rm_failure_reported_not_counted(self, home):
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        run = fake_run_factory([roster_dead(SID_EVENTS)], rm_rc=1)
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []
        assert not any(e["kind"] == "husk_removed" for e in read_events(home))

    def test_husk_removed_event_appended(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        run = fake_run_factory([roster_dead(SID_TOMB)])
        fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        evs = [e for e in read_events(home) if e["kind"] == "husk_removed"]
        assert len(evs) == 1 and evs[0]["session_id"] == SID_TOMB

    def test_roster_failure_raises(self, home):
        def bad_run(argv, **kwargs):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")
        with pytest.raises(fleet.FleetCliError):
            fleet._sweep_husks(False, run=bad_run, which=lambda _: "claude")

    def test_epoch_suspicious_refuses(self, home):
        seed_worker("busy", SID_LIVE, status="working")
        run = fake_run_factory([])  # empty roster while a record claims a live turn
        with pytest.raises(fleet.FleetCliError, match="G9"):
            fleet._sweep_husks(False, run=run, which=lambda _: "claude")


class TestRegistryFailOpen:
    """F1 (adversarial review, HIGH): a quarantined/missing registry must
    never empty the protected set while events/archive evidence still
    vouches sids as fleet-owned -- that combination rm'd resumable
    idle/limited/interrupted workers' sessions in the reviewer's repro."""

    def _seed(self, home):
        seed_worker("idleworker", SID_LIVE, status="idle")
        fleet.append_event("turn_started", "idleworker", session_id=SID_LIVE)
        return [roster_dead(SID_LIVE)]

    def test_run_a_intact_registry_spares_protected(self, home):
        roster = self._seed(home)
        calls = []
        rc = fleet.cmd_autoclean(_autoclean_args(),
                                 run=fake_run_factory(roster, calls=calls),
                                 which=lambda _: "claude")
        assert rc == 0 and rm_targets(calls) == []

    def test_run_b_corrupt_registry_aborts_whole_run_zero_rm(self, home):
        roster = self._seed(home)
        (home / "state" / "fleet.json").write_text("{corrupt", encoding="utf-8")
        calls = []
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.cmd_autoclean(_autoclean_args(),
                                run=fake_run_factory(roster, calls=calls),
                                which=lambda _: "claude")
        assert rm_targets(calls) == []

    def test_run_c_missing_registry_with_evidence_refuses_zero_rm(self, home):
        roster = self._seed(home)
        (home / "state" / "fleet.json").unlink()
        calls = []
        rc = fleet.cmd_autoclean(_autoclean_args(),
                                 run=fake_run_factory(roster, calls=calls),
                                 which=lambda _: "claude")
        assert rc == 1  # loud refusal, not a silent empty sweep
        assert rm_targets(calls) == []

    def test_sweep_refuses_missing_registry_with_events_evidence(self, home):
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        (home / "state" / "fleet.json").unlink()
        with pytest.raises(fleet.FleetCliError, match="registry"):
            fleet._sweep_husks(False, run=fake_run_factory([roster_dead(SID_EVENTS)]),
                               which=lambda _: "claude")

    def test_sweep_refuses_missing_registry_with_archive_evidence(self, home):
        d = fleet.archive_root() / "oldworker"
        d.mkdir(parents=True)
        (d / f"{SID_ARCHDIR}.jsonl").write_text("{}", encoding="utf-8")
        (home / "state" / "fleet.json").unlink()
        with pytest.raises(fleet.FleetCliError, match="registry"):
            fleet._sweep_husks(False, run=fake_run_factory([roster_dead(SID_ARCHDIR)]),
                               which=lambda _: "claude")

    def test_sweep_fresh_home_missing_registry_no_evidence_proceeds(self, home):
        (home / "state" / "fleet.json").unlink()
        run = fake_run_factory([roster_dead(SID_FOREIGN)])
        assert fleet._sweep_husks(False, run=run, which=lambda _: "claude")[0] == []


class TestQuarantineArtifactGuard:
    """NEW-1 (re-review, MED): the F1 refusal keyed solely on registry-file
    ABSENCE. Two repro'd bypasses: (D) a routine spawn recreates fleet.json
    with one record -> next tick rm's the OLD idle worker's session; (F) an
    operator follows the old message's own 'or recreate' advice with an
    empty registry -> same rm. Tier 2 must refuse while any
    state/fleet.json.corrupt.* artifact exists, regardless of whether a
    fleet.json is present."""

    def _quarantine(self, home):
        (home / "state" / "fleet.json").write_text("{corrupt", encoding="utf-8")
        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()
        artifacts = list((home / "state").glob("fleet.json.corrupt.*"))
        assert artifacts, "quarantine rename did not happen"

    def test_probe_d_spawn_recreated_registry_refuses(self, home):
        fleet.append_event("turn_started", "oldworker", session_id=SID_EVENTS)
        self._quarantine(home)
        seed_worker("newworker", SID_LIVE, status="working")  # fresh registry, one record
        calls = []
        run = fake_run_factory([roster_dead(SID_EVENTS), roster_live(SID_LIVE)],
                               calls=calls)
        with pytest.raises(fleet.FleetCliError, match="quarantine"):
            fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert rm_targets(calls) == []

    def test_probe_f_recreated_empty_registry_refuses(self, home):
        fleet.append_event("turn_started", "oldworker", session_id=SID_EVENTS)
        self._quarantine(home)
        fleet.save_registry({"workers": {}})  # operator "recreates"
        calls = []
        run = fake_run_factory([roster_dead(SID_EVENTS)], calls=calls)
        with pytest.raises(fleet.FleetCliError, match="quarantine"):
            fleet._sweep_husks(False, run=run, which=lambda _: "claude")
        assert rm_targets(calls) == []

    def test_artifact_cleared_and_registry_restored_sweep_resumes(self, home):
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        self._quarantine(home)
        for p in (home / "state").glob("fleet.json.corrupt.*"):
            p.unlink()
        fleet.save_registry({"workers": {}})
        run = fake_run_factory([roster_dead(SID_EVENTS)])
        assert fleet._sweep_husks(False, run=run,
                                  which=lambda _: "claude")[0] == [SID_EVENTS]

    def test_refusal_messages_never_advise_recreate(self, home):
        # artifact-present refusal
        fleet.append_event("turn_started", "w", session_id=SID_EVENTS)
        self._quarantine(home)
        fleet.save_registry({"workers": {}})
        with pytest.raises(fleet.FleetCliError) as exc1:
            fleet._sweep_husks(False, run=fake_run_factory([roster_dead(SID_EVENTS)]),
                               which=lambda _: "claude")
        # missing-registry refusal (artifact cleared, registry gone)
        for p in (home / "state").glob("fleet.json.corrupt.*"):
            p.unlink()
        (home / "state" / "fleet.json").unlink()
        with pytest.raises(fleet.FleetCliError) as exc2:
            fleet._sweep_husks(False, run=fake_run_factory([roster_dead(SID_EVENTS)]),
                               which=lambda _: "claude")
        assert "recreate" not in str(exc1.value)
        assert "recreate" not in str(exc2.value)


class TestFleetHomeValidation:
    """NEW-2 (re-review, LOW): --fleet-home was used verbatim -- a relative
    path operated on a cwd-relative phantom home (System32 under Task
    Scheduler) and a nonexistent home was silently mkdir'd."""

    def test_nonexistent_home_refused_nothing_created(self, home):
        phantom = home / "no-such-home"
        with pytest.raises(fleet.FleetCliError, match="fleet-home"):
            fleet.cmd_autoclean(_autoclean_args(fleet_home=str(phantom)),
                                run=fake_run_factory([]), which=lambda _: "claude")
        assert not phantom.exists()

    def test_nonexistent_home_refused_even_dry_run(self, home):
        phantom = home / "no-such-home"
        with pytest.raises(fleet.FleetCliError, match="fleet-home"):
            fleet.cmd_autoclean(_autoclean_args(fleet_home=str(phantom), dry_run=True),
                                run=fake_run_factory([]), which=lambda _: "claude")
        assert not phantom.exists()

    def test_relative_home_resolved_before_use(self, home, monkeypatch, tmp_path_factory):
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        monkeypatch.chdir(elsewhere)
        # relative name that exists under neither cwd -> refused, no phantom
        with pytest.raises(fleet.FleetCliError, match="fleet-home"):
            fleet.cmd_autoclean(_autoclean_args(fleet_home="phantom-rel"),
                                run=fake_run_factory([]), which=lambda _: "claude")
        assert not (elsewhere / "phantom-rel").exists()

    def test_existing_home_still_accepted(self, home, tmp_path_factory):
        other = tmp_path_factory.mktemp("other-home")
        (other / "state").mkdir()
        rc = fleet.cmd_autoclean(_autoclean_args(fleet_home=str(other)),
                                 run=fake_run_factory([]), which=lambda _: "claude")
        assert rc == 0
        assert (other / "state" / "autoclean-last-run.json").exists()


class TestExpireTombstones:
    def test_expired_tombstone_dropped_files_kept(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=100)))
        d = fleet.archive_root() / "tomb"
        d.mkdir(parents=True)
        (d / "journal.md").write_text("history", encoding="utf-8")
        expired = fleet._expire_tombstones(72.0, False)
        assert [n for n, _ in expired] == ["tomb"]
        assert "tomb" not in fleet.load_registry()["workers"]
        assert (d / "journal.md").exists()  # NO file deletion, ever
        assert any(e["kind"] == "tombstone_expired" for e in read_events(home))

    def test_fresh_tombstone_kept(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=1)))
        assert fleet._expire_tombstones(72.0, False) == []
        assert "tomb" in fleet.load_registry()["workers"]

    def test_pending_move_tombstone_never_expired(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=100)))
        # evidence file still at its pre-move location -> resume territory
        fleet.journals_dir().mkdir(parents=True, exist_ok=True)
        (fleet.journals_dir() / "tomb.md").write_text("j", encoding="utf-8")
        assert fleet._expire_tombstones(72.0, False) == []
        assert "tomb" in fleet.load_registry()["workers"]

    def test_unparseable_archived_at_kept(self, home):
        seed_worker("tomb", SID_TOMB, archived_at="garbage")
        assert fleet._expire_tombstones(0.1, False) == []
        assert "tomb" in fleet.load_registry()["workers"]

    def test_non_archived_never_touched(self, home):
        seed_worker("live", SID_LIVE, status="idle",
                    last_activity=_iso(NOW - timedelta(hours=999)))
        assert fleet._expire_tombstones(0.1, False) == []
        assert "live" in fleet.load_registry()["workers"]

    def test_dry_run_mutates_nothing(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=100)))
        assert fleet._expire_tombstones(72.0, True) == []
        assert "tomb" in fleet.load_registry()["workers"]


def _autoclean_args(**kw):
    kw.setdefault("ttl_hours", None)
    kw.setdefault("expire_tombstones_hours", None)
    kw.setdefault("dry_run", False)
    kw.setdefault("fleet_home", None)
    return argparse.Namespace(**kw)


class TestCmdAutoclean:
    def test_tier_isolation_archive_crash_husks_still_swept(self, home, monkeypatch):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))

        def boom(*a, **k):
            raise RuntimeError("tier-1 exploded")
        monkeypatch.setattr(fleet, "cmd_archive", boom)
        calls = []
        run = fake_run_factory([roster_dead(SID_TOMB)], calls=calls)
        rc = fleet.cmd_autoclean(_autoclean_args(), run=run, which=lambda _: "claude")
        assert rc == 1  # the failure is loud...
        assert SID_TOMB.split("-", 1)[0] in rm_targets(calls)  # ...but tier 2 ran

    def test_tier3_default_off(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=9999)))
        run = fake_run_factory([])
        rc = fleet.cmd_autoclean(_autoclean_args(), run=run, which=lambda _: "claude")
        assert rc == 0
        assert "tomb" in fleet.load_registry()["workers"]  # ancient, still kept

    def test_tier3_with_flag(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW - timedelta(hours=9999)))
        run = fake_run_factory([])
        rc = fleet.cmd_autoclean(_autoclean_args(expire_tombstones_hours=72.0),
                                 run=run, which=lambda _: "claude")
        assert rc == 0
        assert "tomb" not in fleet.load_registry()["workers"]

    def test_stamp_and_summary_event_written(self, home):
        run = fake_run_factory([])
        rc = fleet.cmd_autoclean(_autoclean_args(), run=run, which=lambda _: "claude")
        assert rc == 0
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["husks_removed"] == 0 and stamp["errors"] == []
        assert any(e["kind"] == "autoclean_run" for e in read_events(home))

    def test_dry_run_writes_no_stamp(self, home):
        run = fake_run_factory([])
        rc = fleet.cmd_autoclean(_autoclean_args(dry_run=True),
                                 run=run, which=lambda _: "claude")
        assert rc == 0
        assert not fleet.autoclean_stamp_path().exists()


def _clean_args(**kw):
    kw.setdefault("yes", True)
    kw.setdefault("dead_only", False)
    kw.setdefault("tombstones", False)
    return argparse.Namespace(**kw)


class TestCleanTieringSplit:
    def test_default_sweeps_tombstones(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        rc = fleet.cmd_clean(_clean_args(), run=fake_run_factory([]),
                             which=lambda _: "claude")
        assert rc == 0
        assert "tomb" not in fleet.load_registry()["workers"]

    def test_dead_only_spares_tombstones(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        rc = fleet.cmd_clean(_clean_args(dead_only=True), run=fake_run_factory([]),
                             which=lambda _: "claude")
        assert rc == 0
        assert "tomb" in fleet.load_registry()["workers"]

    def test_tombstones_only_touches_nothing_else(self, home):
        seed_worker("tomb", SID_TOMB, archived_at=_iso(NOW))
        seed_worker("idleworker", SID_LIVE, status="idle")
        calls = []
        rc = fleet.cmd_clean(_clean_args(tombstones=True),
                             run=fake_run_factory([roster_dead(SID_LIVE)], calls=calls),
                             which=lambda _: "claude")
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert "tomb" not in workers and "idleworker" in workers
        # --tombstones never probes: no roster fetch, no recompute persisted
        assert not any(len(a) >= 2 and a[1] == "agents" for a in calls)
        assert workers["idleworker"]["status"] == "idle"

    def test_flags_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["clean", "--dead-only", "--tombstones"])


@pytest.fixture
def platform_stub(monkeypatch):
    state = {"query": None, "installs": [], "removes": [],
             "install_ok": (True, ""), "remove_ok": (True, "")}
    monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                        lambda task_name, run=None: state["query"])
    monkeypatch.setattr(
        fleet.PLATFORM, "autoclean_task_install",
        lambda task_name, command, interval_hours, run=None:
            state["installs"].append((task_name, command, interval_hours))
            or state["install_ok"])
    monkeypatch.setattr(
        fleet.PLATFORM, "autoclean_task_remove",
        lambda task_name, run=None:
            state["removes"].append(task_name) or state["remove_ok"])
    return state


@pytest.fixture
def canonical_install(home, monkeypatch):
    """Make the sandboxed home look canonical (F2): the resolved fleet.py
    sits under it, so the home-guards pass and install paths can be tested."""
    script = home / "bin" / "fleet.py"
    monkeypatch.setattr(fleet, "_autoclean_script_path", lambda: script,
                        raising=False)
    return script


class TestInstallHomeGuards:
    """F2 (adversarial review, HIGH): Task Scheduler runs without operator
    env, so the task command must carry FLEET_HOME explicitly, and an
    install whose fleet.py is not the target home's copy (worktree!) must
    refuse -- otherwise the task sweeps a wrong/soon-deleted home forever
    while doctor stays green."""

    def test_task_command_embeds_fleet_home(self, home, canonical_install):
        cmd = fleet._autoclean_task_command()
        assert "--fleet-home" in cmd
        assert str(Path(home).resolve()) in cmd

    def test_autoclean_honors_fleet_home_flag(self, home, tmp_path_factory):
        other = tmp_path_factory.mktemp("other-home")
        (other / "state").mkdir()
        rc = fleet.cmd_autoclean(_autoclean_args(fleet_home=str(other)),
                                 run=fake_run_factory([]), which=lambda _: "claude")
        assert rc == 0
        assert (other / "state" / "autoclean-last-run.json").exists()
        assert not (home / "state" / "autoclean-last-run.json").exists()

    def test_install_refuses_script_outside_home(self, home, platform_stub):
        # no canonical_install: the real _autoclean_script_path (this repo's
        # bin/fleet.py) is NOT under the sandboxed home
        with pytest.raises(fleet.FleetCliError, match="F2"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_install_refuses_linked_worktree_home(self, home, platform_stub,
                                                  canonical_install):
        (home / ".git").write_text("gitdir: C:/somewhere/.git/worktrees/x",
                                   encoding="utf-8")
        with pytest.raises(fleet.FleetCliError, match="worktree"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_install_allows_canonical_repo_home(self, home, platform_stub,
                                                canonical_install):
        (home / ".git").mkdir()  # a real repo: .git is a DIRECTORY
        fleet._install_autoclean_task(None, force=False)
        assert len(platform_stub["installs"]) == 1

    def test_install_refuses_marker_mismatch(self, home, platform_stub,
                                             canonical_install, tmp_path_factory):
        marker = fleet.fleet_home_marker_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(tmp_path_factory.mktemp("real-home")), encoding="utf-8")
        # exact guard phrase, not bare "marker" -- tmp_path embeds the test
        # name into interpolated paths (see the F2-guard test's comment)
        with pytest.raises(fleet.FleetCliError, match="marker points at"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_install_passes_matching_marker(self, home, platform_stub,
                                            canonical_install):
        marker = fleet.fleet_home_marker_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(Path(home).resolve().as_posix() + "\n", encoding="utf-8")
        fleet._install_autoclean_task(None, force=False)
        assert len(platform_stub["installs"]) == 1

    def test_force_overrides_home_guards(self, home, platform_stub):
        fleet._install_autoclean_task(None, force=True)
        assert len(platform_stub["installs"]) == 1

    def test_doctor_flags_missing_pinned_path(self, home, monkeypatch):
        gone = str(home / "gone-worktree" / "bin" / "fleet.py")
        monkeypatch.setattr(
            fleet.PLATFORM, "autoclean_task_query",
            lambda task_name, run=None: f'"C:/py.exe" "{gone}" autoclean')
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "missing" in msg.lower()


_INIT_TEMPLATE = '{"hooks": {}}'
_CANONICAL = "C:/canonical/fleet-home"


@pytest.fixture
def init_home(home):
    """home + the worker-settings template cmd_init requires."""
    fleet.template_settings_path().write_text(_INIT_TEMPLATE, encoding="utf-8")
    return home


def _seed_canonical_marker():
    marker = fleet.fleet_home_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(_CANONICAL + "\n", encoding="utf-8")
    return marker


class TestInitMarkerGuards:
    """N1 (re-review, MED): cmd_init stamped ~/.claude/fleet-home BEFORE the
    autoclean home-guards ran -- a worktree `fleet init` repointed the
    marker (SessionStart/statusline then read the worktree's empty
    registry), and the F2 marker-mismatch guard compared against a marker
    the worktree itself had just written, so it could never fire on the
    real init path."""

    def test_worktree_plain_init_leaves_marker_untouched(self, init_home):
        marker = _seed_canonical_marker()
        (init_home / ".git").write_text("gitdir: C:/x/.git/worktrees/y",
                                        encoding="utf-8")
        rc = fleet.cmd_init(fleet.build_parser().parse_args(["init"]))
        assert rc == 0  # plain init still renders the worktree's own settings
        assert fleet.instance_settings_path().exists()
        assert marker.read_text(encoding="utf-8").strip() == _CANONICAL

    def test_worktree_init_autoclean_refuses_before_any_write(self, init_home,
                                                              platform_stub):
        marker = _seed_canonical_marker()
        (init_home / ".git").write_text("gitdir: C:/x/.git/worktrees/y",
                                        encoding="utf-8")
        fleet.instance_settings_path().unlink()  # prove nothing gets written
        with pytest.raises(fleet.FleetCliError, match="N1"):
            fleet.cmd_init(fleet.build_parser().parse_args(["init", "--autoclean"]))
        assert marker.read_text(encoding="utf-8").strip() == _CANONICAL
        assert not fleet.instance_settings_path().exists()
        assert platform_stub["installs"] == []

    def test_canonical_home_init_still_stamps(self, init_home):
        rc = fleet.cmd_init(fleet.build_parser().parse_args(["init"]))
        assert rc == 0
        stamped = fleet.fleet_home_marker_path().read_text(encoding="utf-8").strip()
        assert stamped == Path(init_home).resolve().as_posix()

    def test_force_restamps_from_worktree(self, init_home):
        _seed_canonical_marker()
        (init_home / ".git").write_text("gitdir: C:/x/.git/worktrees/y",
                                        encoding="utf-8")
        rc = fleet.cmd_init(fleet.build_parser().parse_args(["init", "--force"]))
        assert rc == 0
        stamped = fleet.fleet_home_marker_path().read_text(encoding="utf-8").strip()
        assert stamped == Path(init_home).resolve().as_posix()

    def test_f2_marker_guard_fires_after_attempted_worktree_init(
            self, init_home, canonical_install, platform_stub):
        _seed_canonical_marker()
        (init_home / ".git").write_text("gitdir: C:/x/.git/worktrees/y",
                                        encoding="utf-8")
        fleet.cmd_init(fleet.build_parser().parse_args(["init"]))
        # the marker survived plain init, so the install guard now sees the
        # mismatch instead of a marker the worktree just wrote. Match the
        # guard's exact phrase, not the bare word "marker" -- pytest's
        # tmp_path embeds this TEST'S OWN NAME in the refusal message's
        # interpolated home path, which made a bare-word match vacuously
        # green pre-fix.
        with pytest.raises(fleet.FleetCliError, match="marker points at"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []


class TestSchedulerInstall:
    def test_fresh_install_default_interval(self, home, canonical_install,
                                            platform_stub, capsys):
        fleet._install_autoclean_task(None, force=False)
        (task_name, command, hours), = platform_stub["installs"]
        assert task_name == fleet.AUTOCLEAN_TASK_NAME
        assert hours == fleet.AUTOCLEAN_INTERVAL_HOURS_DEFAULT
        assert ' autoclean --fleet-home "' in command and "fleet.py" in command
        assert "uninstall" in capsys.readouterr().out

    def test_refuses_foreign_task(self, home, canonical_install, platform_stub):
        platform_stub["query"] = '"C:/other/backup.exe" nightly'
        with pytest.raises(fleet.FleetCliError, match="fleet-owned"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_force_overwrites_foreign_task(self, home, canonical_install, platform_stub):
        platform_stub["query"] = '"C:/other/backup.exe" nightly'
        fleet._install_autoclean_task(None, force=True)
        assert len(platform_stub["installs"]) == 1

    def test_idempotent_reinstall_of_own_task(self, home, canonical_install, platform_stub):
        platform_stub["query"] = fleet._autoclean_task_command()
        fleet._install_autoclean_task(12, force=False)
        (_, _, hours), = platform_stub["installs"]
        assert hours == 12

    def test_foreign_task_containing_word_autoclean_refused(self, home,
                                                            canonical_install,
                                                            platform_stub):
        """F4: ownership must be our exact fleet.py path, never the
        substring 'autoclean' -- a third-party C:/tools/autoclean.exe task
        was silently overwritten pre-fix."""
        platform_stub["query"] = '"C:/tools/autoclean.exe" nightly --quiet'
        with pytest.raises(fleet.FleetCliError, match="fleet-owned"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_own_task_recognized_slash_and_case_insensitive(self, home,
                                                            canonical_install,
                                                            platform_stub):
        cmd = fleet._autoclean_task_command()
        platform_stub["query"] = cmd.replace("\\", "/").upper()
        fleet._install_autoclean_task(None, force=False)
        assert len(platform_stub["installs"]) == 1

    # --- F4 ownership is FULL identity, not just the interpreter target ---
    #
    # Pre-fix the predicate was `str(_autoclean_script_path()) in command`, so
    # it said "ours" for ANY scheduled task running this fleet.py. The moment a
    # second fleet-owned task exists -- the three-tier adjudication's
    # `fleet init --supervisor-beat` is the concrete near-term case --
    # `fleet init --autoclean` would silently overwrite it. Ownership is now
    # script path AND subcommand AND --fleet-home value.

    def test_same_fleet_py_different_subcommand_is_not_ours(self, home,
                                                            canonical_install,
                                                            platform_stub):
        """THE defect: a second fleet-owned scheduled task running the very
        same fleet.py with a DIFFERENT verb must not be overwritten."""
        script = fleet._autoclean_script_path()
        platform_stub["query"] = (
            f'"C:/py.exe" "{script}" supervisor-beat --fleet-home '
            f'"{Path(home).resolve()}"')
        with pytest.raises(fleet.FleetCliError, match="fleet-owned"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_same_script_and_verb_different_fleet_home_is_not_ours(
            self, home, canonical_install, platform_stub, tmp_path_factory):
        """Two fleets on one machine share a fleet.py path only when one is a
        checkout of the other, but they never share a --fleet-home. A task
        pinned to a different home is somebody else's sweep."""
        script = fleet._autoclean_script_path()
        other = tmp_path_factory.mktemp("other-fleet-home")
        platform_stub["query"] = (
            f'"C:/py.exe" "{script}" autoclean --fleet-home "{other.resolve()}"')
        with pytest.raises(fleet.FleetCliError, match="fleet-owned"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_ownership_predicate_all_four_directions(self, home, canonical_install,
                                                     tmp_path_factory):
        """The predicate itself, platform-neutral (it takes a command string):
        ours / foreign / same-script-other-verb / same-verb-other-home."""
        script = fleet._autoclean_script_path()
        other = tmp_path_factory.mktemp("other-fleet-home").resolve()
        me = Path(home).resolve()
        assert fleet._autoclean_task_is_ours(fleet._autoclean_task_command()) is True
        assert fleet._autoclean_task_is_ours(
            '"C:/tools/autoclean.exe" nightly --quiet') is False
        assert fleet._autoclean_task_is_ours(
            f'"C:/py.exe" "{script}" supervisor-beat --fleet-home "{me}"') is False
        assert fleet._autoclean_task_is_ours(
            f'"C:/py.exe" "{script}" autoclean --fleet-home "{other}"') is False

    def test_spec_states_full_identity_ownership(self):
        """SPEC §11 used to promise "ownership by exact normalized path",
        which described the defect. Keep the doc true about what ships."""
        spec = (Path(__file__).resolve().parents[1] / "docs" / "SPEC.md"
                ).read_text(encoding="utf-8")
        section = spec.split("## 11. Archive + autoclean", 1)[1].split("\n## 12.", 1)[0]
        assert "ownership by exact normalized path" not in section
        assert "ownership by full identity" in section
        assert "--fleet-home" in section and "subcommand" in section

    def test_ownership_requires_an_explicit_fleet_home(self, home, canonical_install):
        """F2 embeds --fleet-home in every task fleet installs; a command
        without it was installed by something else (or by a pre-F2 fleet) and
        cannot be proven ours."""
        script = fleet._autoclean_script_path()
        assert fleet._autoclean_task_is_ours(f'"C:/py.exe" "{script}" autoclean') is False

    @pytest.mark.parametrize("bad", [0, 24, -3])
    def test_interval_validated(self, home, canonical_install, platform_stub, bad):
        with pytest.raises(fleet.FleetCliError, match="1..23"):
            fleet._install_autoclean_task(bad, force=False)
        assert platform_stub["installs"] == []

    def test_install_failure_raises(self, home, canonical_install, platform_stub):
        platform_stub["install_ok"] = (False, "access denied")
        with pytest.raises(fleet.FleetCliError, match="access denied"):
            fleet._install_autoclean_task(None, force=False)

    def test_remove(self, platform_stub):
        fleet._remove_autoclean_task()
        assert platform_stub["removes"] == [fleet.AUTOCLEAN_TASK_NAME]

    def test_remove_failure_raises(self, platform_stub):
        platform_stub["remove_ok"] = (False, "no such task")
        with pytest.raises(fleet.FleetCliError, match="no such task"):
            fleet._remove_autoclean_task()


class TestQueryFailClosed:
    """F3 (adversarial review, MED): a query that ERRORS (timeout, access
    denied, schtasks failure) must never read as "task absent" -- that
    licensed /Create /F over a foreign task on a transient hiccup."""

    def test_listing_failure_raises_not_none(self):
        def run(argv, **kw):
            return types.SimpleNamespace(returncode=1, stdout="", stderr="Access is denied.")
        with pytest.raises(fleet.AutocleanTaskQueryError):
            fleet._WindowsPlatform().autoclean_task_query("t", run=run)

    def test_listing_exception_raises_not_none(self):
        def run(argv, **kw):
            raise OSError("schtasks vanished")
        with pytest.raises(fleet.AutocleanTaskQueryError):
            fleet._WindowsPlatform().autoclean_task_query("t", run=run)

    def test_xml_step_failure_raises_not_none(self):
        def run(argv, **kw):
            if "/XML" in argv:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="denied")
            return types.SimpleNamespace(returncode=0, stdout='"\\t","Ready"', stderr="")
        with pytest.raises(fleet.AutocleanTaskQueryError):
            fleet._WindowsPlatform().autoclean_task_query("t", run=run)

    def test_definitively_missing_is_none(self):
        def run(argv, **kw):
            assert "/XML" not in argv  # no targeted query for an absent task
            return types.SimpleNamespace(
                returncode=0, stdout='"TaskName","Status"\n"\\OtherTask","Ready"', stderr="")
        assert fleet._WindowsPlatform().autoclean_task_query("t", run=run) is None

    def test_install_refuses_on_query_error(self, home, canonical_install,
                                            platform_stub, monkeypatch):
        def raiser(task_name, run=None):
            raise fleet.AutocleanTaskQueryError("transient")
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query", raiser)
        with pytest.raises(fleet.FleetCliError, match="cannot determine"):
            fleet._install_autoclean_task(None, force=False)
        assert platform_stub["installs"] == []

    def test_install_force_proceeds_on_query_error(self, home, canonical_install,
                                                   platform_stub, monkeypatch):
        def raiser(task_name, run=None):
            raise fleet.AutocleanTaskQueryError("transient")
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query", raiser)
        fleet._install_autoclean_task(None, force=True)
        assert len(platform_stub["installs"]) == 1

    def test_doctor_query_error_is_note_only(self, home, monkeypatch):
        def raiser(task_name, run=None):
            raise fleet.AutocleanTaskQueryError("transient")
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query", raiser)
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "query failed" in msg


class TestWindowsAdapterSchtasks:
    @staticmethod
    def _run_two_step(xml, listing='"TaskName","Status"\n"\\t","Ready"'):
        def run(argv, **kw):
            assert argv[:2] == ["schtasks", "/Query"]
            if "/XML" in argv:
                return types.SimpleNamespace(returncode=0, stdout=xml, stderr="")
            return types.SimpleNamespace(returncode=0, stdout=listing, stderr="")
        return run

    def test_query_parses_xml_and_unescapes(self):
        xml = ('<Task><Exec><Command>&quot;C:\\py.exe&quot;</Command>'
               '<Arguments>&quot;C:\\fleet.py&quot; autoclean</Arguments></Exec></Task>')
        out = fleet._WindowsPlatform().autoclean_task_query("t", run=self._run_two_step(xml))
        assert out == '"C:\\py.exe" "C:\\fleet.py" autoclean'

    def test_install_argv_shape(self):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        ok, _ = fleet._WindowsPlatform().autoclean_task_install("t", "cmdline", 6, run=run)
        assert ok
        argv, = seen
        assert argv == ["schtasks", "/Create", "/F", "/TN", "t", "/TR", "cmdline",
                        "/SC", "HOURLY", "/MO", "6"]

    def test_remove_argv_shape(self):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        ok, _ = fleet._WindowsPlatform().autoclean_task_remove("t", run=run)
        assert ok and seen == [["schtasks", "/Delete", "/TN", "t", "/F"]]


class TestUuidShapedNames:
    """F6 (adversarial review, LOW): a worker NAMED exactly a foreign
    session's uuid would, after archival, plant logs/archive/<name>/
    <name>.jsonl whose sid-shaped stem widens the owned set -- making that
    foreign session rm-eligible. Fixed at the creation choke point: names
    can never be uuid-shaped, so the conflation is unrepresentable."""

    def test_validate_name_refuses_uuid_shape(self):
        with pytest.raises(ValueError, match="uuid"):
            fleet.validate_name(SID_FOREIGN)

    def test_validate_name_refuses_uuid_shape_any_case(self):
        with pytest.raises(ValueError, match="uuid"):
            fleet.validate_name(SID_FOREIGN.lower())

    def test_dispatch_bg_refuses_uuid_shape(self, home):
        def forbid(argv, **kw):
            raise AssertionError(f"no subprocess may run for a refused name: {argv}")
        with pytest.raises(fleet.NativeDispatchError, match="uuid"):
            fleet.dispatch_bg(SID_FOREIGN, home, "task", "accept",
                              run=forbid, which=lambda _: "claude",
                              roster_fetch=lambda: (False, "forbidden"))

    def test_ordinary_names_still_pass(self):
        fleet.validate_name("mc-autoclean")
        fleet.validate_name("w1")


class TestDoctorAutoclean:
    def test_not_installed_is_note_only(self, home, monkeypatch):
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: None)
        name, ok, msg = fleet._doctor_check_autoclean()
        assert (name, ok) == ("autoclean", True) and "fleet init --autoclean" in msg

    def test_installed_no_stamp(self, home, monkeypatch):
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: "py fleet.py autoclean")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "no run recorded yet" in msg

    def test_installed_stale_stamp(self, home, monkeypatch):
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: "py fleet.py autoclean")
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW - timedelta(hours=60))}), encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "stale" in msg

    def test_installed_fresh_stamp(self, home, monkeypatch):
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: "py fleet.py autoclean")
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW)}), encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "task installed" in msg

    def test_stamp_errors_surfaced(self, home, monkeypatch):
        """LOW advisory (confirmation pass): a bricked run must not read as
        green-and-fresh -- the stamp's errors array reaches the note."""
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: "py fleet.py autoclean")
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW),
                        "errors": ["husks: FleetCliError: boom"]}),
            encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok  # still note-only
        assert "error" in msg and "boom" in msg

    def test_quarantine_artifact_surfaced(self, home, monkeypatch):
        """LOW advisory: a present fleet.json.corrupt.* means tier 2 is
        refusing itself -- doctor must say so even with no task installed."""
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query",
                            lambda task_name, run=None: None)
        (home / "state" / "fleet.json.corrupt.20260716T000000Z").write_text(
            "{", encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok  # still note-only
        assert "quarantine artifact" in msg

    def test_unsupported_platform_skipped(self, home, monkeypatch):
        def raiser(task_name, run=None):
            raise fleet.UnsupportedPlatformError("posix stub")
        monkeypatch.setattr(fleet.PLATFORM, "autoclean_task_query", raiser)
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "skipped" in msg


class TestParser:
    def test_autoclean_parses(self):
        args = fleet.build_parser().parse_args(
            ["autoclean", "--ttl-hours", "12", "--expire-tombstones-hours", "72",
             "--dry-run"])
        assert args.ttl_hours == 12.0
        assert args.expire_tombstones_hours == 72.0
        assert args.dry_run is True

    def test_init_autoclean_flags_parse(self):
        args = fleet.build_parser().parse_args(
            ["init", "--autoclean", "--autoclean-interval-hours", "4"])
        assert args.autoclean is True and args.autoclean_interval_hours == 4
