"""A quarantined fleet must not read as a fleet that was never set up.

`_quarantine_registry` RENAMES rather than deletes, so from the moment
`fleet doctor --repair` runs, the only thing on disk that distinguishes *"this
box carried an incident five seconds ago"* from *"this box has never run `fleet
init`"* is the `state/fleet.json.corrupt.<ts>` artifact. Three surfaces read the
absence and describe it, and none of them consulted the artifact:

    fleet status --stale-ok   -> "fleet: not initialized"      (P1-13)
    statusline                -> "[fleet]: not initialized"    (P1-13)
    fleet doctor              -> "[PASS] registry: ...fleet.json is readable"  (P1-12)

MEASURED BEFORE THE FIX, 2026-07-31, on a fully-initialised sandbox home whose
registry held w1 and w2 and was then truncated and repaired the sanctioned way:

    fleet doctor --repair          rc 1  [FAIL] registry: ... quarantined to ...corrupt.<ts>
    fleet doctor  (the next run)   rc 0  NO [FAIL] rows at all
                                         [PASS] registry: ...\\state\\fleet.json is readable
    fleet status --stale-ok              "fleet: not initialized"
    statusline                           "[fleet]: not initialized"

    ...and the fresh-install control, same home minus the artifact, printed the
    two view strings BYTE-IDENTICALLY. The two states were not distinguishable
    from the read surface at all.

THE SEPARATE DEFECT ON THE SAME ROW (P1-7 == P2-8). `_doctor_check_registry`
keyed its *"has been quarantined"* wording on the `--repair` FLAG the operator
typed rather than on whether a rename happened, so `load_registry`'s OSError arm
-- which raises WITHOUT quarantining -- was announced as repaired:

    [FAIL] registry: registry was corrupt and has been quarantined --
           registry unreadable: ...\\state\\fleet.json
    registry still present: True        artifacts: []

WHY THE OUTCOME IS CARRIED ON THE EXCEPTION AND NOT SNIFFED FROM THE GLOB. The
obvious fix -- and the one both review sections propose -- is *"check
`_quarantine_artifacts()`"*. It is wrong: the glob is not empty on a home that
already carries an artifact from an EARLIER incident, so an OSError arm that
renamed nothing would still find an artifact and still claim success. That is
`test_a_prior_artifact_does_not_make_a_failed_quarantine_look_successful`, and
it is the reason `RegistryCorruptError` carries `.quarantined`.

WHY A BARE ABSENCE STILL PASSES `doctor`. `fleet init` does not create
`state/fleet.json` -- no `save_registry` call exists in `cmd_init` -- so a
correctly-initialised fleet that has never spawned a worker has no registry
file. Grading every absence as FAIL (which is what P1-12's own proposed fix
says: *"a plain `not initialized -- run `fleet init`` note otherwise"*, with
`ok=False`) would make `doctor` permanently red on a healthy fresh install. The
operator's 2026-07-27 ruling on the handoff-aborted flag names that exact cost:
*"leaving a resolved flag standing makes `doctor` permanently red, which trains
everyone to ignore a red `doctor`"*. So absence FAILs only when an artifact
stands beside it; a bare absence stays a PASS and merely stops calling a
nonexistent path *"readable"*.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import fleet  # noqa: E402


ARTIFACT = "fleet.json.corrupt.2026-07-31T000000Z"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME. Never the live fleet."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox", "supervisor", "knowledge"):
        (tmp_path / sub).mkdir(exist_ok=True)
    monkeypatch.delenv("FLEET_WORKER", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return tmp_path


@pytest.fixture
def statusline():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
    import fleet_statusline
    return fleet_statusline


def _quarantined(home, name=ARTIFACT):
    """The post-`--repair` shape: an artifact stands, `fleet.json` is gone."""
    (home / "state" / name).write_text(
        json.dumps({"workers": {"w1": {"name": "w1"}}})[:20], encoding="utf-8")
    assert not fleet.registry_path().exists()
    return home / "state" / name


# --------------------------------------------------------------------------
# P1-13 -- the two view surfaces
# --------------------------------------------------------------------------

class TestAQuarantinedFleetIsNotAFreshInstall:
    """`_read_registry_readonly` is the single derivation every view consumes.
    It classified a missing registry as a fresh install with no further test.

    The fix is a `Path.glob` -- read-only, no lock, no probe, no write, and
    `_quarantine_artifacts` swallows OSError into `[]` -- so the views doctrine
    (root `CLAUDE.md`; `docs/specs/terminal-surface.md` D4) is preserved. D4
    already permits a view to REPORT corruption; it simply had no word for the
    state the rename leaves behind."""

    def test_readonly_read_distinguishes_a_quarantine_from_a_fresh_install(self, home):
        _quarantined(home)
        assert fleet._read_registry_readonly() == (
            False, "quarantined", {"workers": {}})

    def test_a_bare_absence_is_still_not_initialized(self, home):
        assert fleet._read_registry_readonly() == (
            False, "not_initialized", {"workers": {}})

    def test_status_snapshot_carries_the_distinction(self, home):
        _quarantined(home)
        snap = fleet.status_snapshot()
        assert snap["ok"] is False
        assert snap["reason"] == "quarantined"

    def test_the_status_table_names_the_artifact(self, home, capsys):
        _quarantined(home)
        fleet._print_snapshot_table(fleet.status_snapshot())
        out = capsys.readouterr().out
        assert "not initialized" not in out
        assert "quarantined" in out
        assert ARTIFACT in out

    def test_the_statusline_says_quarantined(self, home, statusline):
        _quarantined(home)
        line = statusline.render_statusline(fleet.status_snapshot(), color=False)
        assert line == "[fleet]: registry quarantined"

    def test_the_two_states_are_actually_distinguishable(self, home, statusline, capsys):
        """The whole point. Same home, artifact present vs absent."""
        _quarantined(home)
        fleet._print_snapshot_table(fleet.status_snapshot())
        incident_table = capsys.readouterr().out
        incident_line = statusline.render_statusline(fleet.status_snapshot(), color=False)

        (home / "state" / ARTIFACT).unlink()
        fleet._print_snapshot_table(fleet.status_snapshot())
        fresh_table = capsys.readouterr().out
        fresh_line = statusline.render_statusline(fleet.status_snapshot(), color=False)

        assert incident_table != fresh_table
        assert incident_line != fresh_line
        assert fresh_line == "[fleet]: not initialized"

    def test_the_view_never_writes(self, home):
        """D4: a view reports; it does not repair itself."""
        art = _quarantined(home)
        before = sorted(p.name for p in (home / "state").iterdir())
        fleet.status_snapshot()
        fleet._read_registry_readonly()
        assert sorted(p.name for p in (home / "state").iterdir()) == before
        assert art.exists()
        assert not fleet.registry_path().exists()

    def test_sup_release_no_longer_calls_a_quarantine_a_fresh_install(self, home, capsys):
        """`cmd_sup_release`'s `if reason != "not_initialized"` arm swallowed the
        quarantined case silently AND, if reached, would have told the operator
        the registry `was NOT quarantined`. Both are false after a rename."""
        _quarantined(home)
        ok, reason, _ = fleet._read_registry_readonly()
        assert (ok, reason) == (False, "quarantined")


# --------------------------------------------------------------------------
# P1-12 -- the doctor row
# --------------------------------------------------------------------------

class TestDoctorDoesNotCallANonexistentPathReadable:

    def test_absent_registry_with_an_artifact_is_a_FAIL(self, home):
        _quarantined(home)
        name, ok, msg = fleet._doctor_check_registry(None, False)
        assert name == "registry"
        assert ok is False
        assert "is readable" not in msg
        assert ARTIFACT in msg

    def test_a_bare_absence_still_PASSES_but_is_not_called_readable(self, home):
        """A fresh `fleet init` writes no registry. Grading that FAIL would make
        doctor permanently red on a healthy new fleet -- the regression P1-12's
        own proposed fix would have shipped."""
        name, ok, msg = fleet._doctor_check_registry(None, False)
        assert ok is True
        assert "is readable" not in msg

    def test_a_present_readable_registry_is_unchanged(self, home):
        fleet.save_registry({"workers": {}})
        name, ok, msg = fleet._doctor_check_registry(None, False)
        assert ok is True
        assert msg == f"{fleet.registry_path()} is readable"

    def test_doctor_exits_nonzero_after_its_own_repair(self, home, capsys):
        """End to end, on the sequence the operator actually walks: corrupt ->
        `--repair` -> the next `doctor`. Measured rc 0 with zero FAIL rows."""
        (home / "state" / "worker-settings.json").write_text(
            '{"hooks": {}}', encoding="utf-8")
        fleet.save_registry({"workers": {"w1": {"name": "w1", "cwd": "C:/x",
                                                "status": "idle"}}})
        fleet.registry_path().write_text("{ truncated", encoding="utf-8")
        fleet.cmd_doctor(SimpleNamespace(repair=True))
        capsys.readouterr()
        assert not fleet.registry_path().exists()
        assert fleet._quarantine_artifacts()

        fleet.cmd_doctor(SimpleNamespace())
        rows = [l for l in capsys.readouterr().out.splitlines()
                if l.startswith(("[PASS] registry:", "[FAIL] registry:"))]
        assert len(rows) == 1
        assert rows[0].startswith("[FAIL] registry:")
        assert "is readable" not in rows[0]


# --------------------------------------------------------------------------
# P1-7 == P2-8 -- one defect, one line, two ids
# --------------------------------------------------------------------------

class TestRepairReportsWhatHappenedNotWhatWasAsked:
    """`load_registry` has three raise arms and only TWO of them quarantine.
    The OSError arm (`registry unreadable`) renames nothing -- and the doctor row
    announced a quarantine for it anyway, because it keyed on the flag."""

    def _unreadable(self, home):
        # `Path.exists()` is True, `open()` raises IsADirectoryError/PermissionError
        # -- both OSError subclasses, the same arm a deny-read ACL or a win32
        # sharing violation reaches.
        (home / "state" / "fleet.json").mkdir()

    def test_a_failed_open_is_not_announced_as_a_quarantine(self, home, capsys):
        self._unreadable(home)
        fleet.cmd_doctor(SimpleNamespace(repair=True))
        row = [l for l in capsys.readouterr().out.splitlines()
               if "registry:" in l][0]
        assert "has been quarantined" not in row
        assert "registry unreadable" in row
        assert fleet.registry_path().exists()
        assert fleet._quarantine_artifacts() == []

    def test_a_real_quarantine_is_still_announced_as_one(self, home, capsys):
        fleet.registry_path().write_text("{ this is not json", encoding="utf-8")
        fleet.cmd_doctor(SimpleNamespace(repair=True))
        row = [l for l in capsys.readouterr().out.splitlines()
               if "registry:" in l][0]
        assert "has been quarantined" in row
        assert not fleet.registry_path().exists()
        assert len(fleet._quarantine_artifacts()) == 1

    def test_a_prior_artifact_does_not_make_a_failed_quarantine_look_successful(
            self, home, capsys):
        """The refutation of the fix both review sections propose. A home that
        already carries an artifact would satisfy a `_quarantine_artifacts()`
        check even though THIS run renamed nothing."""
        (home / "state" / ARTIFACT).write_text("old incident", encoding="utf-8")
        self._unreadable(home)
        fleet.cmd_doctor(SimpleNamespace(repair=True))
        row = [l for l in capsys.readouterr().out.splitlines()
               if "registry:" in l][0]
        assert "has been quarantined" not in row
        assert fleet.registry_path().exists()

    def test_quarantine_registry_reports_a_rename_it_could_not_perform(
            self, home, monkeypatch):
        """One level down: `_quarantine_registry` swallowed `OSError` from the
        rename and returned the destination path regardless, so `load_registry`
        said `quarantined to <path>` for a file that never moved."""
        fleet.registry_path().write_text("{ this is not json", encoding="utf-8")

        def _boom(self, target):
            raise OSError(32, "sharing violation")
        monkeypatch.setattr(Path, "rename", _boom)

        assert fleet._quarantine_registry(fleet.registry_path()) is None
        with pytest.raises(fleet.RegistryCorruptError) as exc:
            fleet.load_registry()
        assert exc.value.quarantined is None
        assert "could NOT be quarantined" in str(exc.value)
        assert fleet.registry_path().exists()

    def test_the_exception_carries_the_outcome(self, home):
        fleet.registry_path().write_text("{ this is not json", encoding="utf-8")
        with pytest.raises(fleet.RegistryCorruptError) as exc:
            fleet.load_registry()
        assert exc.value.quarantined is not None
        assert exc.value.quarantined.name.startswith("fleet.json.corrupt.")

    def test_the_unreadable_arm_carries_no_quarantine(self, home):
        self._unreadable(home)
        with pytest.raises(fleet.RegistryCorruptError) as exc:
            fleet.load_registry()
        assert exc.value.quarantined is None


# --------------------------------------------------------------------------
# P1-6 -- already fixed by `7be7d14`; pinned so it stays fixed
# --------------------------------------------------------------------------

class TestKillRespawnPreflightDoesNotQuarantine:
    """P1-6 was filed against `d019066`, where `_supervisor_lifecycle_target`
    read through `load_registry()` ahead of either verb's `fleet_lock`, so the
    rename was a lock-free write AND it stole the quarantine from the lock-held
    read designed to perform it -- leaving `unknown worker: 'w1'` as the whole
    of the operator's diagnosis. Fixed on `main` at `7be7d14` (2026-07-30), two
    days after the reviewed tree. This is the regression pin that finding never
    got."""

    def test_the_preflight_read_leaves_a_corrupt_registry_where_it_is(self, home):
        fleet.registry_path().write_text(
            '{"workers": {"w1": {"name": "w1"}}', encoding="utf-8")
        assert fleet._supervisor_lifecycle_target("kill", "w1") is None
        assert fleet.registry_path().exists()
        assert fleet._quarantine_artifacts() == []

    def test_kill_surfaces_the_corruption_instead_of_unknown_worker(self, home):
        fleet.registry_path().write_text(
            '{"workers": {"w1": {"name": "w1", "cwd": "C:/x", "status": "idle"},'
            ' "w2": {"name": "w2", "cwd": "C:/y", "status": "idle"}}',
            encoding="utf-8")
        with pytest.raises(fleet.RegistryCorruptError) as exc:
            fleet.cmd_kill(SimpleNamespace(name="w1", force=True, yes=True,
                                           nonce=None, reason=None))
        assert "unknown worker" not in str(exc.value)
        assert "quarantined" in str(exc.value)
