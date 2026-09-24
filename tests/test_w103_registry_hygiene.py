"""w103 registry hygiene pins, one group per defect measured on the PM home.

1. Idle finished rows counted as live lanes: 63 of them refused dispatch under
   the lane cap and pushed the supervisor boot bundle past its 20,000-character
   cap. A lane is live only while its turn runs, it is attached, or it has
   unread mail; idle rows are a separate count and the bundle lists a bounded
   number of them.
2. Native Codex rows (`dispatch_kind == "codex-app-server"`) could not be
   killed or archived, so a finished lane stayed `working` forever once its
   host was gone.
3. `fleet clean --dead-only` raised `TypeError: unsupported operand type(s)
   for /: 'PosixPath' and 'NoneType'` on a dead row whose session id is null.

Each pin fails at base 04ef7b9 and passes after the fix.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
GENERATION = "3f0e8a52-5d1c-4a51-9f4e-4c1b9a0d7e21"
NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    # Tests run inside Claude sessions; the destructive-verb acknowledgement
    # and the §7 gate must not read the developer's own session id.
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    return tmp_path


def _seed(name, rec):
    data = fleet.load_registry()
    data["workers"][name] = rec
    fleet.save_registry(data)
    return rec


def _native_codex_row(status="working", age_hours=0.0, **extra):
    rec = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "cwd": "/tmp/lane",
        "codex_thread_id": THREAD_ID, "codex_turn_id": TURN_ID,
        "codex_host_generation": GENERATION, "adapter_state": "active",
        "status": status, "model": "codex:gpt-5.6-luna", "turns": 1,
        "last_activity": _iso(NOW - timedelta(hours=age_hours)),
        "archived_at": None,
    }
    rec.update(extra)
    return rec


# --- 1. idle rows are not live lanes -------------------------------------

def _board_run(argv, **kwargs):
    if argv[:2] == ["git", "worktree"]:
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    if argv[:2] == ["git", "rev-parse"]:
        out = "/tmp/repo\n" if argv[-1] == "--show-toplevel" else "abc123\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    if argv[:2] == ["git", "symbolic-ref"]:
        return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
    if argv[:2] in (["git", "status"], ["git", "rev-list"]):
        return SimpleNamespace(returncode=0, stdout="0 0\n" if argv[1] == "rev-list" else "",
                               stderr="")
    if argv[:1] == ["free"]:
        return SimpleNamespace(returncode=0, stdout="Mem: 100 20 80 1 2 77\n", stderr="")
    raise AssertionError(argv)


def _row(name, status, mail=0, stale=60.0):
    return {"name": name, "status": status, "turns": 3, "cost_usd": 1.25,
            "mail": mail, "stale_seconds": stale, "tier": "worker",
            "branch": name, "cwd": None, "archived_at": None}


def _pm_snapshot(idle=63):
    """The PM home's measured shape: 63 idle finished rows beside real lanes."""
    rows = [_row(f"pm-finished-lane-with-a-long-descriptive-name-{i:02d}", "idle",
                 stale=3600.0 + i) for i in range(idle)]
    rows.append(_row("pm-running", "working"))
    rows.append(_row("pm-idle-with-mail", "idle", mail=1))
    rows.append(_row("pm-attached", "attached"))
    rows.append(_row("pm-dead", "dead"))
    rows.append(dict(_row("sup|inc-x|boot", "working"), tier="supervisor"))
    return {"ok": True, "workers": rows,
            "totals": {"workers": len(rows), "mail": 1, "cost_usd": 0.0}}


class TestIdleRowsAreNotLiveLanes:
    def test_dispatch_gates_count_only_running_attached_or_mailed_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        gates = fleet._supervisor_dispatch_gates(_pm_snapshot(), run=_board_run)
        assert "live_lane_count=3" in gates, gates
        assert "idle_lane_count=63" in gates, gates

    def test_boot_bundle_lists_a_bounded_number_of_idle_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        text = fleet._render_boot_bundle([], _pm_snapshot(), [], run=_board_run)
        listed = [ln for ln in text.splitlines()
                  if ln.startswith("  pm-finished-lane-with")]
        assert len(listed) == fleet.SUPERVISOR_IDLE_ROWS_LISTED == 12
        assert f"+{63 - 12} idle" in text
        # Live, attached, mailed and dead rows are always listed.
        for name in ("pm-running", "pm-idle-with-mail", "pm-attached", "pm-dead"):
            assert f"  {name}:" in text

    def test_idle_row_pile_no_longer_scales_the_bundle(self, tmp_path, monkeypatch):
        # MEASURED: 63 idle rows produced a 20,359-character bundle. The size
        # must not grow with idle rows past the listed bound.
        monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
        small = fleet._render_boot_bundle([], _pm_snapshot(idle=20), [], run=_board_run)
        large = fleet._render_boot_bundle([], _pm_snapshot(idle=400), [], run=_board_run)
        assert len(large) - len(small) < 20, (len(small), len(large))


# --- 2. native Codex rows can be killed and archived ---------------------

class _FakeHost:
    generation = GENERATION
    host_pid = 4242

    def __init__(self, alive=True):
        self.alive = alive
        self.calls = []
        self.commits = []

    def _owner_live(self):
        return self.alive

    def call(self, operation, timeout):
        self.calls.append(operation)
        return SimpleNamespace(result={}, generation=self.generation)

    def commit(self, operation_id):
        self.commits.append(operation_id)


class TestNativeCodexKill:
    def test_kill_with_host_gone_marks_dead_with_reason(self, home, monkeypatch):
        from fleet_codex import HostUnavailable
        _seed("cx-native", _native_codex_row())

        def gone(_home):
            raise HostUnavailable("no ready Codex host exists for this Fleet home")
        monkeypatch.setattr(fleet, "_codex_existing_client", gone)

        rc = fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None))

        assert rc == 0
        row = fleet.load_registry()["workers"]["cx-native"]
        assert row["status"] == "dead"
        assert "host gone" in row["dead_reason"]

    def test_kill_with_host_pid_dead_marks_dead_without_calling_it(self, home, monkeypatch):
        host = _FakeHost(alive=False)
        _seed("cx-native", _native_codex_row())
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: host)

        assert fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None)) == 0
        row = fleet.load_registry()["workers"]["cx-native"]
        assert row["status"] == "dead" and "4242 gone" in row["dead_reason"]
        assert host.calls == []

    def test_kill_with_live_host_interrupts_the_turn_then_marks_dead(self, home, monkeypatch):
        host = _FakeHost()
        _seed("cx-native", _native_codex_row())
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: host)

        assert fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None)) == 0

        [op] = host.calls
        assert op["payload"] == {"method": "turn/interrupt", "params": {
            "threadId": THREAD_ID, "turnId": TURN_ID}}
        assert host.commits == [op["operation_id"]]
        assert fleet.load_registry()["workers"]["cx-native"]["status"] == "dead"

    def test_kill_with_a_newer_host_generation_does_not_touch_the_new_host(self, home, monkeypatch):
        host = _FakeHost()
        host.generation = "another-generation"
        _seed("cx-native", _native_codex_row())
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: host)

        assert fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None)) == 0
        row = fleet.load_registry()["workers"]["cx-native"]
        assert row["status"] == "dead" and "generation" in row["dead_reason"]
        assert host.calls == []

    def test_unverified_interrupt_still_marks_dead_and_exits_1(self, home, monkeypatch):
        host = _FakeHost()

        def refuse(operation, timeout):
            raise fleet.FleetCliError("Codex IPC peer does not hold the current Interface")
        host.call = refuse
        _seed("cx-native", _native_codex_row())
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: host)

        assert fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None)) == 1
        row = fleet.load_registry()["workers"]["cx-native"]
        assert row["status"] == "dead" and "unverified" in row["dead_reason"]

    def test_kill_in_the_bound_window_is_refused_as_launch_in_flight(self, home, monkeypatch):
        # Spawn binds the thread, then runs turn/start, then commits only while
        # adapter_state is still "bound". A kill in that window would be undone
        # by the commit, so it must wait like a preclaimed launch does.
        _seed("cx-native", _native_codex_row(adapter_state="bound", codex_turn_id=None))
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: _FakeHost())

        with pytest.raises(fleet.FleetCliError, match="launch in flight for cx-native"):
            fleet.cmd_kill(argparse.Namespace(name="cx-native", yes=True, nonce=None))
        row = fleet.load_registry()["workers"]["cx-native"]
        assert row["status"] == "working" and row["adapter_state"] == "bound"


class TestNativeCodexArchive:
    def _archive(self, name=None, ttl_hours=None):
        return fleet.cmd_archive(argparse.Namespace(
            name=name, ttl_hours=ttl_hours, dry_run=False, reap=False, nonce=None),
            run=lambda *a, **k: pytest.fail("a Codex-only archive ran a subprocess"),
            which=lambda _: "claude")

    def test_a_finished_native_row_past_ttl_is_tombstoned(self, home):
        _seed("cx-done", _native_codex_row(status="dead", age_hours=30))
        (home / "mailbox" / f"{THREAD_ID}.md").write_text("", encoding="utf-8")

        assert self._archive() == 0

        row = fleet.load_registry()["workers"]["cx-done"]
        assert row["archived_at"] is not None
        assert (fleet.archive_root() / "cx-done" / f"{THREAD_ID}.md").exists()

    def test_ttl_and_running_and_unread_mail_still_protect(self, home):
        _seed("cx-young", _native_codex_row(status="idle", age_hours=1))
        _seed("cx-running", _native_codex_row(status="working", age_hours=30))
        _seed("cx-mailed", _native_codex_row(
            status="idle", age_hours=30,
            codex_thread_id="018f22d3-9b4a-7cc3-8a0e-36d4f59106c9"))
        (home / "mailbox" / "018f22d3-9b4a-7cc3-8a0e-36d4f59106c9.md").write_text(
            "unread\n", encoding="utf-8")

        assert self._archive() == 0

        workers = fleet.load_registry()["workers"]
        assert all(workers[n]["archived_at"] is None
                   for n in ("cx-young", "cx-running", "cx-mailed"))

    def test_a_short_ttl_retires_an_idle_native_row(self, home):
        _seed("cx-idle", _native_codex_row(status="idle", age_hours=2))
        assert self._archive(ttl_hours=1.0) == 0
        assert fleet.load_registry()["workers"]["cx-idle"]["archived_at"] is not None


# --- 3. clean tolerates null sid fields ----------------------------------

class TestCleanToleratesNullSid:
    def test_dead_only_sweep_removes_a_null_sid_row_and_reports_it(self, home, capsys):
        _seed("cx-dead", _native_codex_row(status="dead"))
        rec = fleet.new_worker_record(None, "/tmp/proj", "t", "accept", dispatch_kind="bg")
        rec["status"] = "dead"
        rec["retired_sids"] = None
        _seed("bg-dead-null", rec)

        rc = fleet.cmd_clean(argparse.Namespace(yes=True, dead_only=True, tombstones=False),
                             run=lambda argv, **k: SimpleNamespace(
                                 returncode=0, stdout=json.dumps([]), stderr=""),
                             which=lambda _: "claude")

        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert "cx-dead" not in workers and "bg-dead-null" not in workers
        out = capsys.readouterr().out
        assert "removed cx-dead (no session id recorded" in out
        assert "removed bg-dead-null (no session id recorded" in out

    def test_remove_worker_files_never_builds_a_path_from_none(self, home):
        (home / "mailbox" / "None.md").write_text("someone else's\n", encoding="utf-8")
        fleet._remove_worker_files("w", None, retired_sids=[None, 7])
        assert (home / "mailbox" / "None.md").exists()
