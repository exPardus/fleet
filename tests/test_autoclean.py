"""Autoclean tests (docs/specs/autoclean.md): ownership discriminator
(fault-injected), husk sweep gates, tier isolation, tier-3 default-off,
clean tiering split, scheduler install/remove/doctor."""
import argparse
import ast
import inspect
import json
import os
import pathlib
import textwrap
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# --- pathlib stand-ins for cross-dialect ownership fixtures ----------------
#
# `_fleet_task_is_ours` calls `Path(FLEET_HOME).resolve()`. Several ownership
# fixtures are inherently one dialect's shape -- the live Windows scheduled
# task is a real Windows artifact; the crontab false-MATCH cases are about
# POSIX filesystem semantics -- and ambient `pathlib.Path` is whichever
# flavour the HOST runs. That mismatch is what made the Windows-shaped
# fixtures fail on Linux (a `C:\...` literal is a RELATIVE posix path, so
# `.resolve()` prepended the cwd and no verdict could ever match).
#
# Pinning the dialect explicitly lets every one of those cases run on BOTH
# operating systems instead of being skipped off its home platform. The
# identity `resolve()` is exact for these fixtures specifically: every
# literal is absolute, symlink-free and `..`-free, so real resolution would
# be a no-op anyway. These stand in for pathlib, never for the filesystem --
# no test that actually depends on resolution behaviour may use them.
class _PurePosixPathStandIn(pathlib.PurePosixPath):
    def resolve(self):
        return self


class _PureWindowsPathStandIn(pathlib.PureWindowsPath):
    def resolve(self):
        return self


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
    """The check answers WHEN DID `autoclean` LAST RUN (2026-07-27: the timer
    was retired, so "is the task installed" stopped being a question anyone
    can ask). Note-only in every arm -- a fleet nobody is running is a fact
    about the operator's day, not broken plumbing."""

    def test_no_run_recorded_yet(self, home):
        name, ok, msg = fleet._doctor_check_autoclean()
        assert (name, ok) == ("autoclean", True)
        assert "no run recorded yet" in msg
        # Even here it must name who was supposed to run it.
        assert "watchtower beat" in msg and "startup ritual" in msg

    def test_fresh_run_is_quiet(self, home):
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW)}), encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "last run 0.0h ago" in msg
        assert "BEAT IS NOT BEATING" not in msg

    def test_just_inside_the_window_is_quiet(self, home):
        """The boundary, so the threshold cannot drift silently. Anchored to a
        real `now` rather than the module's NOW: the check reads the wall
        clock, so a stamp written at exactly NOW - threshold is already
        threshold-plus-epsilon old by the time it is read, and the test would
        be measuring test-suite latency instead of the threshold."""
        just_inside = datetime.now(timezone.utc) - timedelta(
            hours=fleet.AUTOCLEAN_STALE_RUN_HOURS - 0.05)
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(just_inside)}), encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok and "BEAT IS NOT BEATING" not in msg

    def test_aged_out_says_the_beat_is_not_beating(self, home):
        """THE ARM THIS SLICE EXISTS FOR. On 2026-07-27 the sweep did not run
        for 18h and no surface said so. An aged stamp now means one thing --
        neither tier has beaten -- and the message says which tiers those
        are, because "stale" is only actionable if you know whose job it was."""
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW - timedelta(
                hours=fleet.AUTOCLEAN_STALE_RUN_HOURS + 1))}), encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok, "note-only: a quiet fleet is not broken plumbing"
        assert "BEAT IS NOT BEATING" in msg
        assert "watchtower beat" in msg and "startup ritual" in msg
        assert f"{fleet.AUTOCLEAN_STALE_RUN_HOURS:.0f}h beat window" in msg

    def test_threshold_comes_from_the_beat_not_the_retired_timer(self):
        """The old 48h threshold was sized for a 6-hourly Scheduled Task. A
        supervisor must keep its heartbeat younger than 60 min and sweeps once
        per beat, so the window is a few beats -- not a few timer periods. If
        someone re-widens this to timer scale, the 18h hole reads green again."""
        assert fleet.AUTOCLEAN_STALE_RUN_HOURS <= 6.0

    def test_stamp_errors_surfaced(self, home):
        """LOW advisory (confirmation pass): a bricked run must not read as
        green-and-fresh -- the stamp's errors array reaches the note."""
        fleet.autoclean_stamp_path().write_text(
            json.dumps({"ts": _iso(NOW),
                        "errors": ["husks: FleetCliError: boom"]}),
            encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok  # still note-only
        assert "error" in msg and "boom" in msg

    def test_quarantine_artifact_surfaced(self, home):
        """LOW advisory: a present fleet.json.corrupt.* means tier 2 is
        refusing itself -- doctor must say so whatever the stamp says."""
        (home / "state" / "fleet.json.corrupt.20260716T000000Z").write_text(
            "{", encoding="utf-8")
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok  # still note-only
        assert "quarantine artifact" in msg

    def test_check_takes_no_run_injection_and_shells_out_to_nothing(self):
        """It reads a file. A `run=` parameter would mean it still shells out
        to a scheduler somewhere, which is the thing that was retired."""
        params = inspect.signature(fleet._doctor_check_autoclean).parameters
        assert list(params) == [], params


class TestSchedulerSurfaceIsRetired:
    """2026-07-27 operator ruling: the autoclean timer is RETIRED, not fixed.

    A timer sweeps when the clock says so, which on a machine that loses power
    means it does not sweep at all -- `StartWhenAvailable=False` dropped the
    08:22Z occurrence across a 9h14m power cut, nothing caught up at boot, and
    an 18-hour hole opened in a 6-hourly guard. Setting that flag was the
    smaller fix and the worse one: a beat sweeps when the FLEET IS ALIVE.

    These pin the DELETION. The failure mode they exist against is a partial
    revival -- one helper, one flag, one adapter method quietly coming back and
    reintroducing machine-local install state nobody re-verifies."""

    RETIRED_NAMES = [
        "AUTOCLEAN_TASK_NAME", "AUTOCLEAN_INTERVAL_HOURS_DEFAULT",
        "AutocleanTaskQueryError", "_install_autoclean_task",
        "_remove_autoclean_task", "_autoclean_task_is_ours",
        "_fleet_task_is_ours", "_autoclean_task_command",
        "_autoclean_script_path", "_normalize_task_token",
        "_task_command_tokens", "_home_guard_problems",
    ]

    @pytest.mark.parametrize("name", RETIRED_NAMES)
    def test_no_install_path_survives_in_the_module(self, name):
        assert not hasattr(fleet, name), (
            f"fleet.{name} is scheduled-task machinery and was retired on "
            f"2026-07-27 -- if it came back, so did the timer")

    @pytest.mark.parametrize("method", ["autoclean_task_install",
                                        "autoclean_task_query",
                                        "autoclean_task_remove"])
    @pytest.mark.parametrize("backend", ["_WindowsPlatform", "_PosixPlatform"])
    def test_no_platform_backend_can_touch_a_scheduler(self, backend, method):
        # Both backends, because the defect was never Windows-specific: cron
        # has no catch-up concept at all, so the POSIX side could not have been
        # given the missed-run behaviour the Windows task lacked.
        assert not hasattr(getattr(fleet, backend)(), method)

    @pytest.mark.parametrize("flag", ["--autoclean", "--autoclean-interval-hours",
                                      "--autoclean-remove"])
    def test_init_rejects_the_retired_flags(self, flag):
        """Rejected, NOT accepted-as-a-no-op. A flag that silently does nothing
        is how an operator believes a sweep is installed when none is."""
        with pytest.raises(SystemExit):
            fleet.build_parser().parse_args(["init", flag])

    def test_no_scheduler_tool_is_named_anywhere_in_the_module(self):
        """Source scan, because an adapter method is not the only way to
        shell out to a scheduler -- the point is that fleet installs no
        OS-scheduler state on any platform."""
        src = pathlib.Path(fleet.__file__).read_text(encoding="utf-8")
        code = [ln for ln in src.splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]
        for tool in ("schtasks", "crontab", "launchctl", "systemd-run"):
            offenders = [ln for ln in code if tool in ln and '"""' not in ln
                         and not ln.lstrip().startswith(("*", "-"))]
            # Prose inside docstrings still mentions the retired surface on
            # purpose (the record is kept); executable lines must not.
            assert not [ln for ln in offenders if "(" in ln and "=" in ln], (
                f"{tool} appears in what looks like executable code: {offenders}")

    def test_the_autoclean_verb_itself_is_untouched(self):
        """The verb stays exactly as it was -- only its DRIVERS changed."""
        args = fleet.build_parser().parse_args(
            ["autoclean", "--ttl-hours", "12", "--expire-tombstones-hours", "72",
             "--dry-run"])
        assert args.ttl_hours == 12.0
        assert args.expire_tombstones_hours == 72.0
        assert args.dry_run is True
        assert callable(fleet.cmd_autoclean)

    def test_cmd_autoclean_itself_never_calls_the_gate(self):
        """A source fact about ONE FRAME, and that is all it has ever been.

        CORRECTED 2026-07-28. This test used to be named
        `test_the_verb_keeps_its_section_7_claim_gate_exemption` and its
        docstring claimed it proved *"both tiers must be able to sweep with no
        `--nonce` while a claim is held"*. It proved no such thing. It reads
        the source of a single function; the sweep is a call GRAPH, and tier 1
        delegates to `cmd_archive`, which DOES call `_supervisor_gate`. The
        exemption is not transitive, and the very failure the old docstring
        described as averted -- *"retiring the timer would have gated the sweep
        behind the very claim it exists to clean up around"* -- is exactly what
        shipped, measured one hour after the merge.

        Kept, because the fact is still true and still worth pinning: the
        exemption must live in the sweep's own frame, not be smuggled in by a
        `--nonce` the beat cannot source. What proves the sweep actually sweeps
        is `TestTheSweepUnderAHeldClaim` below, which holds a fresh claim --
        the condition that was never in this test."""
        assert "_supervisor_gate" not in inspect.getsource(fleet.cmd_autoclean)


class TestTheSweepUnderAHeldClaim:
    """REGRESSION PIN (2026-07-28, `fix/autoclean-archive-gate`). The whole
    defect is that THE CONDITION WAS NEVER IN THE TEST.

    Every pre-existing autoclean test runs with no supervisor claim, or (in
    `tests/test_gate_arm_wedge.py::test_scheduled_autoclean_still_runs_under_a
    _wedge`) with `CLAUDE_CODE_SESSION_ID` explicitly deleted -- the retired
    Scheduled Task's shape. Both pass against the broken tree. The condition
    that matters is the one under which the sweep is now DRIVEN: a session
    with a sid, calling while a supervisor claim is HELD and FRESH. That is
    not an edge case for the new callers -- it is the only state in which the
    supervisor's watchtower beat runs at all.

    Measured on `main` @ `f10f055`, `fleet autoclean` from a beat holding a
    fresh claim:

        autoclean: archive tier failed: archive: refusing -- a supervisor
        claim (inc-20260727T184603Z-f054) is held and fresh, and this call did
        not prove continuity on it (claim-nonce §7).
        autoclean: husks_removed=0 husks_deferred=0 tombstones_expired=0 errors=1

    ...and `fleet autoclean` has no `--nonce` flag, so there is no caller-side
    workaround: the refusal names a remedy the caller cannot execute.
    """

    HOLDER_SID = "11110000-0000-4000-8000-000000000001"
    INTERFACE_SID = "22220000-0000-4000-8000-000000000002"
    STALE_SID = "99990000-0000-4000-8000-000000000009"

    @pytest.fixture
    def claimed_home(self, home, monkeypatch):
        """A fresh, held, non-legacy claim -- the state the beat runs in."""
        (home / "supervisor").mkdir(exist_ok=True)
        beat = fleet.now_iso()
        fleet.write_incarnation(
            {"incarnation_id": "inc-acgate", "session_id": self.HOLDER_SID,
             "lineage_id": "lin-acgate", "claimed_at": beat, "heartbeat_at": beat,
             "claimed_via": "fresh", "state": "active", "nonce_seq": 1,
             "nonce_hash": fleet.nonce_digest("the-live-generation")})
        return home

    def _seed_archivable(self, name="stale"):
        """A worker that passes every `_archive_eligible` gate against an empty
        roster. If tier 1 runs, this record ends up with `archived_at` set; if
        tier 1 is refused, it does not. That is the behavioural difference the
        source-scan test above could not see."""
        rec = seed_worker(name, self.STALE_SID, status="idle")
        rec["last_activity"] = _iso(NOW - timedelta(
            hours=fleet.ARCHIVE_TTL_HOURS_DEFAULT + 1))
        data = fleet.load_registry()
        data["workers"][name] = rec
        fleet.save_registry(data)
        fleet.append_outcome(self.STALE_SID,
                             {"ts": _iso(NOW), "session_id": self.STALE_SID,
                              "kind": "result", "result_text": "done"})
        return rec

    def _sweep(self):
        return fleet.cmd_autoclean(_autoclean_args(),
                                   run=fake_run_factory([]),
                                   which=lambda _: "claude")

    def test_the_supervisor_beat_sweeps_tier_one_holding_its_own_claim(
            self, claimed_home, monkeypatch):
        """CALLER 1 -- the watchtower beat. Its sid IS the claim holder's, and
        that does not disarm the gate: `_supervisor_gate` arms on the PRESENCE
        of a sid under a fresh claim, holder included. The beat holds a
        generation but has nowhere to put it, so this must pass without one."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.HOLDER_SID)
        self._seed_archivable()
        rc = self._sweep()
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["errors"] == [], stamp["errors"]
        assert stamp["archive_rc"] == 0
        assert rc == 0
        assert fleet.load_registry()["workers"]["stale"]["archived_at"] is not None

    def test_the_interface_ritual_sweeps_tier_one_with_no_nonce_to_present(
            self, claimed_home, monkeypatch):
        """CALLER 2 -- the interface tier's startup ritual, and the reason a
        `--nonce` flag on `autoclean` could only ever have fixed HALF of this.

        The interface holds no nonce BY DESIGN (claim-nonce §7.1, the same seam
        that forced the `send`-to-the-holder carve-out). There is no value it
        could pass, so its sweep has to work with none."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.INTERFACE_SID)
        self._seed_archivable()
        rc = self._sweep()
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["errors"] == [], stamp["errors"]
        assert rc == 0
        assert fleet.load_registry()["workers"]["stale"]["archived_at"] is not None

    def test_no_gate_refusal_can_reach_the_sweeps_error_channel(
            self, claimed_home, monkeypatch):
        """The general form, so this cannot regress for a tier nobody wrote a
        fixture for: NO tier of the sweep may report a §7 refusal, whatever the
        caller's sid. Named by class, not by message, so a reworded refusal
        still trips it."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.INTERFACE_SID)
        self._seed_archivable()
        self._sweep()
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert not [e for e in stamp["errors"]
                    if fleet.SupervisorClaimGateError.__name__ in e], stamp["errors"]

    def test_the_archive_verb_itself_stays_gated(self, claimed_home, monkeypatch):
        """THE OTHER HALF, and the one that makes this a fix rather than a
        narrowing of an operator-owned section. §7 is the operator's; the
        supervisor may not weaken its arming. `fleet archive` invoked as a verb
        by a sid-bearing caller under a fresh claim is refused exactly as
        before -- only the sweep's own internal tier call is exempt, which is
        what the ratified decision already said `autoclean` was."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.INTERFACE_SID)
        self._seed_archivable()
        args = fleet.build_parser().parse_args(["archive"])
        with pytest.raises(fleet.SupervisorClaimGateError):
            fleet.cmd_archive(args, run=fake_run_factory([]),
                              which=lambda _: "claude")
        assert fleet.load_registry()["workers"]["stale"]["archived_at"] is None

    def test_the_exemption_is_explicit_and_not_an_accident_of_call_order(self):
        """The brief's condition on this shape: *"the exemption must be
        explicit and pinned, not an accident of which function calls which."*
        The old exemption WAS such an accident -- it held only because
        `cmd_autoclean` happened not to name the gate, while the function it
        delegates to did. Pin the named parameter, so deleting it is a test
        failure and not a silent re-arming.

        Parsed with `ast`, NOT matched as a substring. The first cut of this
        test asserted `"as_autoclean_tier=True" in
        inspect.getsource(fleet.cmd_autoclean)` and **survived the fault
        injection that removed the keyword from the call** -- because the
        comment sitting above that call explains the flag by name, so the
        string was still there with the code gone. A source-substring test
        that a comment can satisfy is the same failure this whole branch is
        about, one level up: the check read text near the thing instead of
        the thing."""
        params = inspect.signature(fleet.cmd_archive).parameters
        assert "as_autoclean_tier" in params
        assert params["as_autoclean_tier"].default is False

        tree = ast.parse(textwrap.dedent(inspect.getsource(fleet.cmd_autoclean)))
        exempted = [
            call for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and getattr(call.func, "id", None) == "cmd_archive"
            and any(kw.arg == "as_autoclean_tier"
                    and isinstance(kw.value, ast.Constant) and kw.value.value is True
                    for kw in call.keywords)]
        assert len(exempted) == 1, (
            "the sweep's cmd_archive call does not pass as_autoclean_tier=True "
            "-- tier 1 is gated again")

    def test_a_real_tier_failure_still_reaches_the_stamp_and_the_doctor_note(
            self, claimed_home, monkeypatch):
        """END-TO-END on the one thing that WORKED and must not break. The
        branch's own "a fresh timestamp alone can lie" confirmation pass is why
        this bug was caught in one run instead of in eighteen hours: the
        stamp's `errors` array is appended to the doctor note, so a bricked
        sweep never reads green-and-fresh.

        `TestDoctorAutoclean::test_stamp_errors_surfaced` pins the note against
        a HAND-WRITTEN stamp. This pins the whole path -- a tier really fails,
        `cmd_autoclean` really records it, doctor really surfaces it -- because
        the fix touches the tier-1 call site the note reports on."""
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.HOLDER_SID)

        def boom(*a, **k):
            raise RuntimeError("tier-1 exploded")
        monkeypatch.setattr(fleet, "cmd_archive", boom)
        assert self._sweep() == 1
        stamp = json.loads(fleet.autoclean_stamp_path().read_text(encoding="utf-8"))
        assert stamp["errors"] == ["archive: RuntimeError: tier-1 exploded"]
        _, ok, msg = fleet._doctor_check_autoclean()
        assert ok, "note-only: doctor stays report-only"
        assert "last run 0.0h ago" in msg          # fresh...
        assert "tier-1 exploded" in msg            # ...and NOT green


class TestParser:
    def test_init_still_parses_its_surviving_flags(self):
        args = fleet.build_parser().parse_args(["init", "--statusline", "--force"])
        assert args.statusline is True and args.force is True
