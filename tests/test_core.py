"""Unit tests for the claude-fleet core logic layer (bin/fleet.py).

No real claude process, no real state/ dirs are touched: every test
monkeypatches the module-global fleet.FLEET_HOME to a pytest tmp_path.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point fleet.FLEET_HOME at a scratch dir so no test touches real state."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

class TestPaths:
    def test_dirs_derive_from_fleet_home(self, isolated_home):
        assert fleet.state_dir() == isolated_home / "state"
        assert fleet.logs_dir() == isolated_home / "logs"
        assert fleet.mailbox_dir() == isolated_home / "mailbox"
        assert fleet.journals_dir() == isolated_home / "state" / "journals"
        assert fleet.knowledge_dir() == isolated_home / "knowledge"

    def test_dirs_not_created_on_read(self, isolated_home):
        # Paths module says "create dirs lazily on write" -- merely asking
        # for the path must not create it.
        fleet.state_dir()
        assert not (isolated_home / "state").exists()

    def test_default_fleet_home_is_repo_root(self, monkeypatch):
        # Without monkeypatching, FLEET_HOME must be derived from __file__:
        # parent.parent of bin/fleet.py == repo root.
        monkeypatch.delenv("FLEET_HOME", raising=False)
        import importlib
        importlib.reload(fleet)
        assert fleet.FLEET_HOME == fleet.Path(fleet.__file__).resolve().parent.parent

    def test_template_and_instance_settings_paths_derive_from_fleet_home(self, isolated_home):
        assert fleet.template_settings_path() == isolated_home / "worker-settings.template.json"
        assert fleet.instance_settings_path() == isolated_home / "state" / "worker-settings.json"


class TestFleetHomeEnvOverride:
    """SPEC §14: env var FLEET_HOME wins over the __file__-derived default,
    read once at import into the module-global (same discipline as
    bin/hooks/*.py's own _fleet_home()). Reloads the module to exercise the
    import-time read; the next test's isolated_home autouse fixture
    monkeypatches FLEET_HOME again regardless, so no explicit restore is
    needed here (matches the existing test_default_fleet_home_is_repo_root
    pattern above)."""

    def test_env_var_wins_when_set(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))
        import importlib
        importlib.reload(fleet)
        assert fleet.FLEET_HOME == tmp_path

    def test_env_var_absent_falls_back_to_file_derived_default(self, monkeypatch):
        monkeypatch.delenv("FLEET_HOME", raising=False)
        import importlib
        importlib.reload(fleet)
        assert fleet.FLEET_HOME == fleet.Path(fleet.__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Registry: CRUD, lock, atomic save, name validation
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_load_missing_registry_returns_empty_workers(self):
        data = fleet.load_registry()
        assert data == {"workers": {}}

    def test_save_then_load_roundtrip(self, isolated_home):
        data = {"workers": {"probe-1": _worker_record()}}
        fleet.save_registry(data)
        loaded = fleet.load_registry()
        assert loaded == data

    def test_save_is_atomic_no_leftover_temp_files(self, isolated_home):
        fleet.save_registry({"workers": {"probe-1": _worker_record()}})
        files = list((isolated_home / "state").iterdir())
        assert files == [isolated_home / "state" / "fleet.json"]

    def test_save_creates_state_dir_lazily(self, isolated_home):
        assert not (isolated_home / "state").exists()
        fleet.save_registry({"workers": {}})
        assert (isolated_home / "state").exists()

    def test_registry_schema_fields_present(self, isolated_home):
        rec = _worker_record()
        expected_fields = {
            "session_id", "cwd", "task", "mode", "model", "created",
            "status", "turn_pid", "turn_pid_ctime", "attached_since",
            "turns", "cost_usd", "last_activity",
        }
        assert set(rec.keys()) == expected_fields

    def test_new_worker_record_matches_schema_and_defaults(self):
        rec = fleet.new_worker_record("sid-1", r"C:\proga\x", "x" * 300, "bypass")
        assert set(rec.keys()) == {
            "session_id", "cwd", "task", "mode", "model", "created",
            "status", "turn_pid", "turn_pid_ctime", "attached_since",
            "turns", "cost_usd", "last_activity",
        }
        assert rec["session_id"] == "sid-1"
        assert rec["cwd"] == r"C:\proga\x"
        assert len(rec["task"]) == 200  # truncated to first ~200 chars (SPEC §4)
        assert rec["mode"] == "bypass"
        assert rec["model"] is None
        assert rec["status"] == "working"
        assert rec["turn_pid"] is None
        assert rec["turn_pid_ctime"] is None
        assert rec["attached_since"] is None
        assert rec["turns"] == 0
        assert rec["cost_usd"] == 0.0
        assert rec["last_activity"] == rec["created"]

    def test_corrupt_registry_file_is_quarantined_and_raises(self, isolated_home):
        state = isolated_home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()

        assert not (state / "fleet.json").exists()
        quarantined = [p for p in state.iterdir() if p.name.startswith("fleet.json.corrupt.")]
        assert len(quarantined) == 1

    def test_corrupt_registry_quarantine_appends_registry_corrupt_event(self, isolated_home):
        state = isolated_home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()

        lines = (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["kind"] == "registry_corrupt"
        assert record["name"] == "fleet"
        assert "fleet.json.corrupt." in record["path"]
        # (missing-file -> {"workers": {}} is already covered by
        # test_load_missing_registry_returns_empty_workers above.)

    def test_crud_add_update_remove_worker(self, isolated_home):
        with fleet.fleet_lock():
            data = fleet.load_registry()
            data["workers"]["probe-1"] = _worker_record()
            fleet.save_registry(data)

        with fleet.fleet_lock():
            data = fleet.load_registry()
            data["workers"]["probe-1"]["turns"] = 5
            fleet.save_registry(data)
        assert fleet.load_registry()["workers"]["probe-1"]["turns"] == 5

        with fleet.fleet_lock():
            data = fleet.load_registry()
            del data["workers"]["probe-1"]
            fleet.save_registry(data)
        assert fleet.load_registry()["workers"] == {}


class TestNameValidation:
    @pytest.mark.parametrize("name", ["probe-1", "abc", "a-b-c-123", "z"])
    def test_valid_names_pass(self, name):
        fleet.validate_name(name, existing=set())  # must not raise

    @pytest.mark.parametrize("name", ["Probe", "probe_1", "probe 1", "", "PROBE-1", "probe.1"])
    def test_invalid_names_raise(self, name):
        with pytest.raises(ValueError):
            fleet.validate_name(name, existing=set())

    def test_duplicate_name_raises(self):
        with pytest.raises(ValueError):
            fleet.validate_name("probe-1", existing={"probe-1"})

    def test_unique_name_ok(self):
        fleet.validate_name("probe-2", existing={"probe-1"})  # must not raise


class TestLockContention:
    def test_second_acquirer_blocks_then_succeeds_after_release(self, isolated_home):
        order = []
        first_acquired = threading.Event()
        release_first = threading.Event()

        def holder():
            with fleet.fleet_lock():
                order.append("first_acquired")
                first_acquired.set()
                release_first.wait(timeout=2)
                order.append("first_about_to_release")

        t = threading.Thread(target=holder)
        t.start()
        assert first_acquired.wait(timeout=2)
        time.sleep(0.05)  # make sure the holder is settled inside the lock

        second_acquired = threading.Event()

        def contender():
            with fleet.fleet_lock(timeout=2):
                order.append("second_acquired")
                second_acquired.set()

        t2 = threading.Thread(target=contender)
        t2.start()
        time.sleep(0.15)
        assert not second_acquired.is_set(), "second acquirer must still be blocked"

        release_first.set()
        t.join(timeout=3)
        t2.join(timeout=3)

        assert order == ["first_acquired", "first_about_to_release", "second_acquired"]

    def test_timeout_raises_when_lock_held(self, isolated_home):
        lock_path = fleet.state_dir() / "fleet.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("held", encoding="utf-8")
        with pytest.raises(fleet.FleetLockTimeout):
            with fleet.fleet_lock(timeout=0.2):
                pass  # pragma: no cover

    def test_stale_lock_is_broken(self, isolated_home):
        lock_path = fleet.state_dir() / "fleet.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("stale", encoding="utf-8")
        old = time.time() - (fleet.LOCK_STALE_SECONDS + 5)
        import os
        os.utime(lock_path, (old, old))

        acquired = []
        with fleet.fleet_lock(timeout=1):
            acquired.append(True)
        assert acquired == [True]

    def test_normal_release_deletes_lock_file(self, isolated_home):
        lock_path = fleet.state_dir() / "fleet.lock"
        with fleet.fleet_lock():
            assert lock_path.exists()
        assert not lock_path.exists()

    def test_release_is_ownership_checked_does_not_delete_successors_lock(self, isolated_home):
        # Simulate a successor stealing the lock file (e.g. it broke a
        # falsely-stale lock) while we still believe we hold it: overwrite
        # the lock file's contents with a different token before our
        # context exits. Our release must see the mismatched token and
        # leave the file alone (F1) -- deleting it here would cascade by
        # freeing a lock the successor believes it owns.
        lock_path = fleet.state_dir() / "fleet.lock"
        with fleet.fleet_lock():
            assert lock_path.exists()
            lock_path.write_text("someone-elses-token", encoding="utf-8")
        assert lock_path.exists()
        assert lock_path.read_text(encoding="utf-8") == "someone-elses-token"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
    def test_append_event_writes_one_json_line(self, isolated_home):
        fleet.append_event("spawned", "probe-1", cwd="C:/x")
        path = isolated_home / "state" / "events.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["kind"] == "spawned"
        assert record["name"] == "probe-1"
        assert record["cwd"] == "C:/x"
        assert "ts" in record

    def test_append_event_appends_multiple_lines(self, isolated_home):
        fleet.append_event("spawned", "probe-1")
        fleet.append_event("turn_started", "probe-1")
        lines = (isolated_home / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# PID liveness
# ---------------------------------------------------------------------------

class TestPidLiveness:
    def test_alive_and_ctime_matches(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("claude.exe", _parse(ctime_iso))
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True

    def test_alive_but_ctime_within_tolerance(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        drifted = _parse(ctime_iso) + timedelta(seconds=1)
        info = lambda pid: ("claude.exe", drifted)
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True

    def test_alive_but_ctime_mismatch_is_pid_reuse_not_alive(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        different = _parse(ctime_iso) + timedelta(minutes=5)
        info = lambda pid: ("claude.exe", different)
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is False

    def test_missing_pid_not_alive(self):
        info = lambda pid: None
        assert fleet.pid_alive(12345, "2026-07-07T12:30:00Z", get_process_info=info) is False

    def test_pid_none_not_alive(self):
        info = lambda pid: ("claude.exe", _parse("2026-07-07T12:30:00Z"))
        assert fleet.pid_alive(None, "2026-07-07T12:30:00Z", get_process_info=info) is False

    def test_non_claude_image_not_alive(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("notepad.exe", _parse(ctime_iso))
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is False

    # -----------------------------------------------------------------
    # F-CMD: the npm/claude.cmd shim launches via cmd.exe (whose child is
    # node), so the recorded pid's image name is "cmd" or "node", not
    # "claude" -- the accepted image-name set must be broadened to catch
    # these, while the ctime guard still rejects unrelated processes.
    # -----------------------------------------------------------------

    def test_cmd_image_name_is_alive(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("cmd", _parse(ctime_iso))
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True

    def test_node_image_name_is_alive(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("node", _parse(ctime_iso))
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is True

    def test_unrelated_image_name_still_not_alive(self):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("explorer", _parse(ctime_iso))
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is False

    def test_broadened_name_with_ctime_mismatch_still_not_alive(self):
        """The ctime +/-2s guard is what actually prevents false positives
        from the broadened name set (not the substring test) -- it must
        stay intact for cmd/node too."""
        ctime_iso = "2026-07-07T12:30:00Z"
        different = _parse(ctime_iso) + timedelta(seconds=10)
        info = lambda pid: ("cmd", different)
        assert fleet.pid_alive(12345, ctime_iso, get_process_info=info) is False

    def test_recompute_status_working_when_alive(self, isolated_home, tmp_path):
        ctime_iso = "2026-07-07T12:30:00Z"
        info = lambda pid: ("claude.exe", _parse(ctime_iso))
        log = tmp_path / "w.jsonl"
        log.write_text("", encoding="utf-8")
        assert fleet.recompute_status(1, ctime_iso, log, get_process_info=info) == "working"

    def test_recompute_status_idle_when_stale_pid_and_result_line(self, tmp_path):
        info = lambda pid: None
        log = tmp_path / "w.jsonl"
        log.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}\n'
            '{"type":"result","subtype":"success","result":"done","total_cost_usd":0.1}\n',
            encoding="utf-8",
        )
        assert fleet.recompute_status(1, "2026-07-07T12:30:00Z", log, get_process_info=info) == "idle"

    def test_recompute_status_dead_when_stale_pid_and_no_result_line(self, tmp_path):
        info = lambda pid: None
        log = tmp_path / "w.jsonl"
        log.write_text('{"type":"assistant","message":{"content":[]}}\n', encoding="utf-8")
        assert fleet.recompute_status(1, "2026-07-07T12:30:00Z", log, get_process_info=info) == "dead"

    def test_recompute_status_idle_with_bom_prefixed_log(self, tmp_path):
        # Same BOM concern (F6) exercised through _last_line_type via the
        # public recompute_status surface.
        info = lambda pid: None
        log = tmp_path / "w.jsonl"
        line = '{"type":"result","subtype":"success","result":"done"}\n'
        log.write_bytes(b"\xef\xbb\xbf" + line.encode("utf-8"))
        assert fleet.recompute_status(1, "2026-07-07T12:30:00Z", log, get_process_info=info) == "idle"

    def test_recompute_status_dead_when_log_missing(self, tmp_path):
        info = lambda pid: None
        log = tmp_path / "missing.jsonl"
        assert fleet.recompute_status(1, "2026-07-07T12:30:00Z", log, get_process_info=info) == "dead"

    def test_recompute_status_attached_is_not_clobbered_by_dead_pid(self, tmp_path):
        # An operator-attached worker must stay "attached" even though the
        # pid is dead and the log ends on a result event (which would
        # otherwise compute "idle") -- F7.
        info = lambda pid: None
        log = tmp_path / "w.jsonl"
        log.write_text('{"type":"result","subtype":"success","result":"done"}\n', encoding="utf-8")
        status = fleet.recompute_status(
            1, "2026-07-07T12:30:00Z", log, current_status="attached", get_process_info=info
        )
        assert status == "attached"

    def test_ctime_to_iso_round_trips_through_parse_iso(self):
        dt = datetime(2026, 7, 7, 12, 30, 0, tzinfo=timezone.utc)
        assert fleet._parse_iso(fleet.ctime_to_iso(dt)) == dt

    def test_recompute_status_working_launch_in_flight_not_demoted(self, tmp_path):
        """F1 required test (b): a pre-claimed record (status="working",
        turn_pid=None -- what spawn/send-idle/respawn write atomically
        before the turn process actually exists) must not be demoted by a
        concurrent recompute, the same way "attached" already isn't (F7).
        Without this guard, a racing reader would see idle/dead and launch
        a second live turn onto the same session."""
        log = tmp_path / "missing.jsonl"
        assert fleet.recompute_status(None, None, log, current_status="working") == "working"

    def test_recompute_status_still_demotes_working_with_dead_real_pid(self, tmp_path):
        """F1 required test (c) -- regression guard: the launch-in-flight
        guard must be scoped to pid is None only. A "working" record with a
        real (non-None) pid that is actually dead must still demote
        normally (here to "idle" thanks to the trailing result line)."""
        info = lambda pid: None
        log = tmp_path / "w.jsonl"
        log.write_text('{"type":"result","subtype":"success","result":"done"}\n', encoding="utf-8")
        status = fleet.recompute_status(
            111, "2026-07-07T12:30:00Z", log, current_status="working", get_process_info=info
        )
        assert status == "idle"


# ---------------------------------------------------------------------------
# Stream-jsonl parsing (tail_events)
# ---------------------------------------------------------------------------

class TestTailEvents:
    def test_missing_file_returns_empty(self, tmp_path):
        assert fleet.tail_events(tmp_path / "nope.jsonl", 20) == []

    def test_skips_junk_lines(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text(
            "not json at all\n"
            "\n"
            '{"type":"assistant","message":{"content":[{"type":"text","text":"hello there"}]}}\n'
            "{broken json\n",
            encoding="utf-8",
        )
        entries = fleet.tail_events(log, 20)
        assert len(entries) == 1
        assert entries[0]["kind"] == "assistant_text"
        assert "hello there" in entries[0]["text"]

    def test_handles_truncated_last_line(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text(
            '{"type":"assistant","message":{"content":[{"type":"text","text":"first"}]}}\n'
            '{"type":"assistant","message":{"content":[{"type":"tex',  # truncated, no newline
            encoding="utf-8",
        )
        entries = fleet.tail_events(log, 20)
        assert len(entries) == 1
        assert entries[0]["text"] == "first"

    def test_extracts_tool_call(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text(
            '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
            '"input":{"command":"ls -la"}}]}}\n',
            encoding="utf-8",
        )
        entries = fleet.tail_events(log, 20)
        assert entries[0]["kind"] == "tool_call"
        assert entries[0]["name"] == "Bash"
        assert "ls -la" in entries[0]["input"]

    def test_extracts_result_event(self, tmp_path):
        log = tmp_path / "w.jsonl"
        log.write_text(
            '{"type":"result","subtype":"success","result":"all done",'
            '"total_cost_usd":0.42,"usage":{"input_tokens":10,"output_tokens":20}}\n',
            encoding="utf-8",
        )
        entries = fleet.tail_events(log, 20)
        assert entries[-1]["kind"] == "result"
        assert entries[-1]["text"] == "all done"
        assert entries[-1]["cost_usd"] == 0.42
        assert entries[-1]["tokens"]["input_tokens"] == 10

    def test_n_limits_to_last_n_entries(self, tmp_path):
        log = tmp_path / "w.jsonl"
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"msg{i}"}]}})
            for i in range(5)
        ]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        entries = fleet.tail_events(log, 2)
        assert len(entries) == 2
        assert entries[-1]["text"] == "msg4"

    def test_bom_prefixed_log_parses_first_event(self, tmp_path):
        # PowerShell `>` redirection emits a UTF-8 BOM at the start of the
        # file; it must not swallow the first line's event (F6).
        log = tmp_path / "w.jsonl"
        line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}})
        log.write_bytes(b"\xef\xbb\xbf" + (line + "\n").encode("utf-8"))
        entries = fleet.tail_events(log, 20)
        assert len(entries) == 1
        assert entries[0]["text"] == "hi"

    def test_long_text_is_truncated(self, tmp_path):
        log = tmp_path / "w.jsonl"
        long_text = "x" * 2000
        log.write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": long_text}]}}) + "\n",
            encoding="utf-8",
        )
        entries = fleet.tail_events(log, 20)
        assert len(entries[0]["text"]) < 2000


# ---------------------------------------------------------------------------
# Prompt composition + mailbox drain
# ---------------------------------------------------------------------------

class TestClaimMailbox:
    def test_claim_missing_mailbox_returns_empty(self, isolated_home):
        content, claim = fleet.claim_mailbox("sid-1")
        assert content == ""
        assert claim is None

    def test_claim_renames_to_claimed_path_and_returns_content(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("please stop and check X", encoding="utf-8")

        content, claim = fleet.claim_mailbox("sid-1")

        assert content == "please stop and check X"
        assert claim is not None
        assert claim.name.startswith("sid-1.md.claimed.")
        assert claim.exists()
        assert not (mbox / "sid-1.md").exists()

    def test_claim_twice_second_call_empty(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("hello", encoding="utf-8")
        fleet.claim_mailbox("sid-1")
        content, claim = fleet.claim_mailbox("sid-1")
        assert content == ""
        assert claim is None


class TestFinalizeMailboxClaim:
    def test_finalize_deletes_claimed_file(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("hello", encoding="utf-8")
        _, claim = fleet.claim_mailbox("sid-1")

        fleet.finalize_mailbox_claim(claim)

        assert not claim.exists()

    def test_finalize_none_is_noop(self, isolated_home):
        fleet.finalize_mailbox_claim(None)  # must not raise


class TestRestoreMailboxClaim:
    def test_restore_none_is_noop(self, isolated_home):
        fleet.restore_mailbox_claim(None)  # must not raise

    def test_restore_puts_content_back_at_original_mailbox_path(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("please stop and check X", encoding="utf-8")
        _, claim = fleet.claim_mailbox("sid-1")
        assert not (mbox / "sid-1.md").exists()

        fleet.restore_mailbox_claim(claim)

        assert (mbox / "sid-1.md").exists()
        assert (mbox / "sid-1.md").read_text(encoding="utf-8") == "please stop and check X"
        assert not claim.exists()

    def test_restore_merges_with_newer_mail_claimed_content_first(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("older message", encoding="utf-8")
        _, claim = fleet.claim_mailbox("sid-1")
        # Simulate newer mail arriving while our claim was in flight.
        (mbox / "sid-1.md").write_text("newer message", encoding="utf-8")

        fleet.restore_mailbox_claim(claim)

        merged = (mbox / "sid-1.md").read_text(encoding="utf-8")
        assert merged.index("older message") < merged.index("newer message")
        assert not claim.exists()

    def test_compose_prompt_mail_survives_simulated_failed_launch(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("also check the logs", encoding="utf-8")

        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1")
        assert "also check the logs" in prompt

        fleet.restore_mailbox_claim(claim)  # simulated failed launch

        prompt2, claim2 = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1")
        assert "also check the logs" in prompt2


class TestComposePrompt:
    def test_preamble_mentions_name_cwd_and_rules(self, isolated_home):
        prompt, claim = fleet.compose_prompt("probe-1", r"C:\proga\polymarket", "do the thing", "sid-1")
        assert claim is None
        assert "probe-1" in prompt
        assert r"C:\proga\polymarket" in prompt
        assert "MANAGER MESSAGE" in prompt
        assert "state/journals/probe-1.md" in prompt.replace("\\", "/")
        assert "do the thing" in prompt

    def test_empty_mailbox_is_noop(self, isolated_home):
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1")
        # The preamble explains the <MANAGER MESSAGE> convention (in backticks);
        # what must NOT appear is an actual injected mail block.
        assert "<MANAGER MESSAGE>\n" not in prompt
        assert claim is None

    def test_pending_mailbox_is_claimed_into_prompt(self, isolated_home):
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("also check the logs", encoding="utf-8")
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1")
        assert "<MANAGER MESSAGE>\n" in prompt
        assert "also check the logs" in prompt
        assert not (mbox / "sid-1.md").exists()  # claimed, not left in place
        assert claim is not None
        assert claim.exists()  # not destroyed -- caller decides finalize vs restore

    def test_journal_contents_included_when_respawning(self, isolated_home, tmp_path):
        journal = tmp_path / "probe-1.md"
        journal.write_text("## goal\ndo the thing\n## done\nstep 1", encoding="utf-8")
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1", journal_path=journal)
        assert "do the thing" in prompt
        assert "step 1" in prompt

    def test_no_journal_path_means_no_journal_section(self, isolated_home):
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1")
        assert "## Journal" not in prompt

    def test_empty_task_emits_no_blank_task_section(self, isolated_home):
        """F6: cmd_send's idle-resume path now calls compose_prompt with an
        empty task (the triggering message travels through the mailbox
        drain instead) -- this must not leave a stray blank line/section
        where the task text would have gone."""
        mbox = fleet.mailbox_dir()
        mbox.mkdir(parents=True)
        (mbox / "sid-1.md").write_text("do the thing", encoding="utf-8")
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "", "sid-1")
        assert "do the thing" in prompt  # the mail still comes through
        assert not prompt.endswith("\n\n")  # no trailing blank task section
        assert "\n\n\n" not in prompt

    def test_journal_with_invalid_utf8_bytes_does_not_raise(self, isolated_home, tmp_path):
        journal = tmp_path / "probe-1.md"
        journal.write_bytes(b"## goal\ndo the thing \xff\xfe invalid bytes\n")
        prompt, claim = fleet.compose_prompt("probe-1", "C:/x", "task text", "sid-1", journal_path=journal)
        assert "do the thing" in prompt


# ---------------------------------------------------------------------------
# Portability: worker-settings template render + instance freshness (SPEC §14)
# ---------------------------------------------------------------------------

class TestRenderWorkerSettingsTemplate:
    """Golden tests for the pure `fleet init` render step: {{PYTHON}} and
    {{FLEET_HOME}} substituted with absolute, forward-slash paths; any
    leftover {{...}} placeholder is a loud ValueError, never a silently
    broken settings file."""

    _TEMPLATE = """{
  "hooks": {
    "PostToolUse": [{ "hooks": [{ "type": "command",
      "command": "\\"{{PYTHON}}\\" \\"{{FLEET_HOME}}/bin/hooks/posttooluse_mailbox.py\\"" }] }]
  }
}
"""

    def test_renders_python_and_fleet_home_with_forward_slashes(self, tmp_path):
        python_exe = r"C:\Python313\python.exe"
        rendered = fleet.render_worker_settings_template(self._TEMPLATE, python_exe, tmp_path)

        assert "{{" not in rendered  # no unrendered placeholder markers remain
        assert fleet.Path(python_exe).resolve().as_posix() in rendered
        assert fleet.Path(tmp_path).resolve().as_posix() in rendered
        data = json.loads(rendered)  # still valid JSON after substitution

        # Check the *parsed* command value (not the raw JSON text, which
        # legitimately contains backslash-escaped quotes now that the
        # command wraps each path in double quotes): no Windows-style
        # backslash path separator should have leaked into the command.
        command = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        assert "\\" not in command

    def test_renders_using_sys_executable(self, tmp_path):
        import sys
        rendered = fleet.render_worker_settings_template(self._TEMPLATE, sys.executable, tmp_path)
        assert fleet.Path(sys.executable).resolve().as_posix() in rendered

    def test_raises_on_leftover_placeholder(self, tmp_path):
        template = '{"x": "{{PYTHON}} {{NOT_A_REAL_PLACEHOLDER}}"}'
        with pytest.raises(ValueError):
            fleet.render_worker_settings_template(template, "python.exe", tmp_path)

    def test_no_placeholders_is_a_noop_passthrough(self, tmp_path):
        template = '{"hooks": {}}'
        assert fleet.render_worker_settings_template(template, "python.exe", tmp_path) == template

    def test_command_paths_are_double_quoted_for_spaces(self, tmp_path):
        """HIGH adversarial finding: an unquoted {{PYTHON}}/{{FLEET_HOME}}
        substitution word-splits under Git Bash `sh -c` (exit 127) whenever
        the python interpreter path or fleet home path contains a space --
        silently killing the hook. Both placeholder usages in the template
        must be wrapped in double quotes so the rendered command survives
        `sh -c` word-splitting regardless of spaces in either path."""
        python_exe = "C:/Program Files/Python313/python.exe"
        spaced_home = tmp_path / "space dir"
        spaced_home.mkdir()

        rendered = fleet.render_worker_settings_template(self._TEMPLATE, python_exe, spaced_home)
        data = json.loads(rendered)  # still valid JSON after substitution

        python_path = fleet.Path(python_exe).resolve().as_posix()
        home_path = fleet.Path(spaced_home).resolve().as_posix()

        command = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        assert f'"{python_path}"' in command
        assert f'"{home_path}/bin/hooks/posttooluse_mailbox.py"' in command


class TestInstanceFreshnessInfo:
    """Pure read-only probe for Task 5's `fleet doctor` freshness check
    (not wired into any command in this task) -- template mtime vs
    instance mtime + a missing flag."""

    def test_missing_instance_is_stale(self, isolated_home):
        info = fleet.instance_freshness_info()
        assert info["instance_exists"] is False
        assert info["stale"] is True

    def test_missing_template_with_instance_present_is_not_stale(self, isolated_home):
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text("{}", encoding="utf-8")

        info = fleet.instance_freshness_info()
        assert info["template_exists"] is False
        assert info["instance_exists"] is True
        assert info["stale"] is False

    def test_instance_newer_than_template_is_fresh(self, isolated_home):
        template = fleet.template_settings_path()
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("{}", encoding="utf-8")
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text("{}", encoding="utf-8")
        # Explicit mtimes (not a real-clock sleep) -- deterministic, immune
        # to filesystem timestamp-resolution flakiness.
        os.utime(template, (1_000_000, 1_000_000))
        os.utime(instance, (2_000_000, 2_000_000))

        info = fleet.instance_freshness_info()
        assert info["stale"] is False

    def test_template_newer_than_instance_is_stale(self, isolated_home):
        template = fleet.template_settings_path()
        template.parent.mkdir(parents=True, exist_ok=True)
        template.write_text("{}", encoding="utf-8")
        instance = fleet.instance_settings_path()
        instance.parent.mkdir(parents=True, exist_ok=True)
        instance.write_text("{}", encoding="utf-8")
        os.utime(instance, (1_000_000, 1_000_000))
        os.utime(template, (2_000_000, 2_000_000))

        info = fleet.instance_freshness_info()
        assert info["stale"] is True


# ---------------------------------------------------------------------------
# Mode mapping
# ---------------------------------------------------------------------------

class TestModeFlags:
    def test_bypass(self):
        assert fleet.mode_flags("bypass") == ["--dangerously-skip-permissions"]

    def test_accept(self):
        assert fleet.mode_flags("accept") == ["--permission-mode", "acceptEdits"]

    def test_dontask(self):
        assert fleet.mode_flags("dontask") == ["--permission-mode", "dontAsk"]

    def test_plan(self):
        assert fleet.mode_flags("plan") == ["--permission-mode", "plan"]

    def test_omit(self):
        assert fleet.mode_flags("omit") == []

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            fleet.mode_flags("yolo")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _parse(ctime_iso):
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _worker_record():
    return {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "cwd": "C:\\proga\\polymarket_experimenting",
        "task": "first ~200 chars of original task",
        "mode": "bypass",
        "model": None,
        "created": "2026-07-07T12:00:00Z",
        "status": "working",
        "turn_pid": 12345,
        "turn_pid_ctime": "2026-07-07T12:30:00Z",
        "attached_since": None,
        "turns": 3,
        "cost_usd": 1.23,
        "last_activity": "2026-07-07T12:34:56Z",
    }
