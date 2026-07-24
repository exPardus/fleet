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

    def test_default_fleet_home_is_repo_root(self):
        # Without the env override, FLEET_HOME must be derived from __file__:
        # parent.parent of bin/fleet.py == repo root.
        got = _fleet_home_in_fresh_interpreter(env_override=None)
        assert got == str(fleet.Path(fleet.__file__).resolve().parent.parent)

    def test_template_and_instance_settings_paths_derive_from_fleet_home(self, isolated_home):
        assert fleet.template_settings_path() == isolated_home / "worker-settings.template.json"
        assert fleet.instance_settings_path() == isolated_home / "state" / "worker-settings.json"


def _fleet_home_in_fresh_interpreter(env_override):
    """str(fleet.FLEET_HOME) as a FRESH interpreter derives it at import.

    Debt roll-up item 7: these tests used importlib.reload(fleet) to
    re-exercise the import-time read, which rebound every class/function in
    the shared module object mid-suite -- any test ordering that held a
    pre-reload reference (an exception class in a raises(), a fixture-cached
    callable) could break, and a failure between reload and restore left
    FLEET_HOME env-derived for whoever imported next. A subprocess observes
    the same import-time logic with zero in-process mutation."""
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k != "FLEET_HOME"}
    if env_override is not None:
        env["FLEET_HOME"] = env_override
    out = subprocess.run(
        [sys.executable, "-c", "import fleet; print(fleet.FLEET_HOME)"],
        capture_output=True, text=True, env=env, timeout=60,
        cwd=str(fleet.Path(fleet.__file__).resolve().parent))
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


class TestFleetHomeEnvOverride:
    """SPEC §14: env var FLEET_HOME wins over the __file__-derived default,
    read once at import into the module-global (same discipline as
    bin/hooks/*.py's own _fleet_home()). Exercised in a fresh subprocess
    interpreter -- see _fleet_home_in_fresh_interpreter's docstring for why
    the old importlib.reload approach was fragile."""

    def test_env_var_wins_when_set(self, tmp_path):
        got = _fleet_home_in_fresh_interpreter(env_override=str(tmp_path))
        assert got == str(tmp_path)

    def test_env_var_absent_falls_back_to_file_derived_default(self):
        got = _fleet_home_in_fresh_interpreter(env_override=None)
        assert got == str(fleet.Path(fleet.__file__).resolve().parent.parent)


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
            "status", "attached_since",
            "turns", "cost_usd", "last_activity",
        }
        assert set(rec.keys()) == expected_fields

    def test_new_worker_record_matches_schema_and_defaults(self):
        rec = fleet.new_worker_record("sid-1", r"C:\proga\x", "x" * 300, "bypass")
        assert set(rec.keys()) == {
            "session_id", "cwd", "task", "mode", "model", "created",
            "status", "attached_since",
            "turns", "cost_usd", "cost_baseline", "last_activity",
            # Phase1 kernel item 7 (F13/M5): budget/setting-sources persistence.
            "max_budget_usd", "setting_sources",
            # Kernel 10 (F12=M24): fleet-side token ceiling.
            "token_ceiling",
            # UL1 (item 11 / F31): usage-limit park horizon fields.
            "limit_reset_at", "limit_kind",
            # §5.1: provenance for the destructive-command guard.
            "spawned_by",
            # claim-nonce §6.2: the spawning claim's lineage, for lineage-based
            # ownership across a sid rotation.
            "spawned_by_lineage",
            # M-B native-substrate fields (spec §5).
            "dispatch_kind", "category", "native_short_id",
            "last_dispatch_at", "retired_sids", "archived_at",
        }
        assert rec["session_id"] == "sid-1"
        assert rec["cwd"] == r"C:\proga\x"
        assert len(rec["task"]) == 200  # truncated to first ~200 chars (SPEC §4)
        assert rec["mode"] == "bypass"
        assert rec["model"] is None
        assert rec["status"] == "working"
        assert rec["attached_since"] is None
        assert rec["turns"] == 0
        assert rec["cost_usd"] == 0.0
        # Task 5 fix wave, Finding 4: cost_baseline defaults to 0.0 for a
        # brand-new worker -- recompute_worker adds it to the log's own
        # trailing result cost, so a fresh spawn behaves exactly as before.
        assert rec["cost_baseline"] == 0.0
        # F13/M5: budget/setting-sources default to None (recorded at spawn).
        assert rec["max_budget_usd"] is None
        assert rec["setting_sources"] is None
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

    @pytest.mark.parametrize("workers_value", [[1, 2, 3], "x", 42, [], "", 0])
    def test_workers_wrong_shape_is_quarantined_and_raises(self, isolated_home, workers_value):
        """Fuzz-report Finding F2 (HIGH): `data.setdefault("workers", {})`
        is a no-op when "workers" is PRESENT with the wrong type (a list,
        string, or int) -- such a registry is valid JSON and a valid
        top-level dict, so it used to sail through unquarantined and crash
        every downstream subcommand (dict.keys()/.get()/.pop()/`in`/
        sorted() all raise on a non-dict). Must be treated exactly like a
        decode failure: quarantined + RegistryCorruptError, for both
        obviously-wrong shapes (list/string/int) and the falsy-but-still-
        wrong ones ([], "", 0) that a truthiness check alone would miss."""
        state = isolated_home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json").write_text(json.dumps({"workers": workers_value}), encoding="utf-8")

        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()

        assert not (state / "fleet.json").exists()
        quarantined = [p for p in state.iterdir() if p.name.startswith("fleet.json.corrupt.")]
        assert len(quarantined) == 1

    def test_worker_record_wrong_shape_is_quarantined_and_raises(self, isolated_home):
        """Same finding, narrower case: "workers" is itself a dict (the
        right shape), but one of ITS values (a worker record) is not --
        e.g. a hand-edited or corrupted registry where a single record
        became a bare string/int/list. Every downstream consumer calls
        dict(record)/record.get(...) on each worker record, so this must be
        caught here too, not just at the top-level "workers" shape."""
        state = isolated_home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json").write_text(
            json.dumps({"workers": {"probe-1": "not-a-record"}}), encoding="utf-8",
        )

        with pytest.raises(fleet.RegistryCorruptError):
            fleet.load_registry()

        assert not (state / "fleet.json").exists()

    def test_workers_missing_key_still_defaults_to_empty_dict(self, isolated_home):
        """Regression guard: a valid top-level object with no "workers" key
        at all must still degrade to {"workers": {}}, not be treated as
        malformed."""
        state = isolated_home / "state"
        state.mkdir(parents=True)
        (state / "fleet.json").write_text(json.dumps({}), encoding="utf-8")

        assert fleet.load_registry() == {"workers": {}}

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

    def test_reserved_supervisor_name_refused_by_ordinary_path(self):
        # three-tier-command.md §10.3 (2026-07-24 ruling): `supervisor` is the
        # supervisor's LOGICAL name -- the claim-resolved send/kill/respawn
        # target -- and no verb mints a record by it; the ordinary worker
        # creation path (spawn/respawn) must refuse it at the choke point.
        assert fleet.SUPERVISOR_BODY_NAME == "supervisor"
        with pytest.raises(ValueError, match="reserved"):
            fleet.validate_name(fleet.SUPERVISOR_BODY_NAME, existing=set())

    def test_reserved_name_refused_even_when_absent_from_existing(self):
        # The reservation is a name-SHAPE refusal (like the F6 uuid rule), not a
        # duplicate check: it must fire whether or not a record already holds it.
        with pytest.raises(ValueError, match="reserved"):
            fleet.validate_name(fleet.SUPERVISOR_BODY_NAME, existing={"other"})

    def test_reservation_is_unconditional_no_bypass_parameter(self):
        # sup-spawn choreography design §5: the old `allow_reserved` bypass was
        # dead for sup-spawn (the pipe name fails NAME_RE before the reserved
        # check) and had zero callers -- retired. The reservation itself stays:
        # the logical-name resolver depends on no worker squatting the literal.
        import inspect
        assert "allow_reserved" not in inspect.signature(fleet.validate_name).parameters


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

    def test_failed_token_write_closes_fd_and_removes_lock_file(self, isolated_home, monkeypatch):
        # Debt roll-up item 6: an ENOSPC during the token write used to leak
        # the fd and strand a token-less lock file that blocked every
        # acquirer until the stale-break window.
        import os as _os
        lock_path = fleet.state_dir() / "fleet.lock"
        opened = []
        real_open, real_write = _os.open, _os.write

        def recording_open(*a, **kw):
            fd = real_open(*a, **kw)
            opened.append(fd)
            return fd

        def enospc_write(fd, data):
            if fd in opened:
                raise OSError(28, "No space left on device")
            return real_write(fd, data)

        monkeypatch.setattr(fleet.os, "open", recording_open)
        monkeypatch.setattr(fleet.os, "write", enospc_write)
        with pytest.raises(OSError, match="No space left"):
            with fleet.fleet_lock():
                pass  # pragma: no cover
        monkeypatch.undo()
        assert len(opened) == 1
        with pytest.raises(OSError):
            _os.fstat(opened[0])  # fd was closed on the error path
        assert not lock_path.exists()  # no token-less lock file stranded

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

    def test_concurrent_appends_lose_no_records(self, isolated_home):
        """4 threads x 250 records each -> exactly 1000 parseable records.

        events.jsonl has genuinely concurrent writers (the manager, the
        scheduled autoclean task, and any worker invoking the CLI), and a
        plain buffered `open(..., "a")` does NOT append atomically on
        Windows: the CRT's O_APPEND emulation seeks-then-writes, so whole
        clean records are dropped with zero JSON-decode errors -- silent
        loss, not corruption. This is the same 4x250 shape that already
        pins `append_outcome` (tests/test_native.py::TestOutcomeConcurrency).
        """
        n_writers = 4
        n_per_writer = 250

        def writer(tag):
            for i in range(n_per_writer):
                fleet.append_event("turn_started", "probe-1", session_id=tag, seq=i)

        threads = [threading.Thread(target=writer, args=(f"tag{t}",))
                   for t in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = (isolated_home / "state" / "events.jsonl").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        parsed = []
        bad = 0
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except json.JSONDecodeError:
                bad += 1

        assert bad == 0
        assert len(parsed) == n_writers * n_per_writer
        seen = {(rec["session_id"], rec["seq"]) for rec in parsed}
        assert seen == {(f"tag{t}", i)
                        for t in range(n_writers) for i in range(n_per_writer)}


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

    @pytest.mark.skipif(os.name != "nt",
                        reason="Windows path semantics under test: a "
                               "backslashed C:\\ input path cannot exist on "
                               "POSIX (test_renders_using_sys_executable "
                               "covers the portable path)")
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
        "attached_since": None,
        "turns": 3,
        "cost_usd": 1.23,
        "last_activity": "2026-07-07T12:34:56Z",
    }
