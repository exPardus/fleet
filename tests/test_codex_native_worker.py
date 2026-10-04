from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
NEXT_THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
NEXT_TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106ba"


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        json.dumps({
            "permissions": {"allow": []},
            "hooks": {"Stop": [{"hooks": [{"type": "command",
                                               "command": "true"}]}]},
        }), encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    mcx = stub_bin / "mcx"
    mcx.write_text("#!/bin/sh\necho 'mcx must not run in native tests' >&2\nexit 97\n",
                   encoding="utf-8")
    mcx.chmod(0o700)
    monkeypatch.setenv("PATH", f"{stub_bin}{os.pathsep}{os.environ['PATH']}")
    lane = tmp_path / "lane"
    lane.mkdir()
    return tmp_path, lane.resolve()


def _args(lane, **updates):
    values = dict(
        name="cx-native", dir=str(lane), task="implement the bounded change",
        mode="accept", model="codex:gpt-5.6-luna", codex_adapter="native",
        max_budget_usd=None, setting_sources=None, token_ceiling=None,
        category=None, nonce=None, force_band=False, context=None,
    )
    values.update(updates)
    return SimpleNamespace(**values)


class FakeClient:
    generation = "host-generation-1"

    def __init__(self, home, lane, *, mutate_on_thread=None, fail_thread=None,
                 thread_cwd=None, fail_commit_number=None, thread_fields=None):
        self.home = home
        self.lane = lane
        self.mutate_on_thread = mutate_on_thread
        self.fail_thread = fail_thread
        self.thread_cwd = str(thread_cwd or lane)
        self.fail_commit_number = fail_commit_number
        self.thread_fields = thread_fields or {}
        self.operations = []
        self.commits = []
        self.lock_depth = lambda: 0

    def call(self, operation, timeout):
        assert self.lock_depth() == 0, "provider call occurred under fleet.lock"
        self.operations.append(operation)
        method = operation["payload"]["method"]
        record = fleet.load_registry()["workers"]["cx-native"]
        if method == "thread/start":
            assert record["adapter_state"] == "preclaim"
            assert record["codex_thread_id"] is None
            if self.mutate_on_thread is not None:
                self.mutate_on_thread()
            if self.fail_thread is not None:
                raise self.fail_thread
            result = {
                "thread": {"id": THREAD_ID, "cwd": self.thread_cwd},
                "cwd": self.thread_cwd,
                "model": "gpt-5.6-luna",
                "approvalPolicy": "on-request",
                "approvalsReviewer": "user",
                "sandbox": {"type": "workspaceWrite"},
            }
            result.update(self.thread_fields)
        elif method == "turn/start":
            assert record["adapter_state"] == "bound"
            assert record["codex_thread_id"] == THREAD_ID
            assert record["cwd"] == str(self.lane)
            result = {"turn": {"id": TURN_ID, "status": "inProgress",
                               "items": []}}
        else:
            raise AssertionError(f"unexpected public method: {method}")
        digest = "a" * 64
        return SimpleNamespace(
            operation_id=operation["operation_id"], generation=self.generation,
            payload_digest=digest, result=result)

    def commit(self, operation_id):
        assert self.lock_depth() == 0, "journal commit occurred under fleet.lock"
        self.commits.append(operation_id)
        if len(self.commits) == self.fail_commit_number:
            raise OSError("journal commit lost")


def _track_lock(monkeypatch):
    original = fleet.fleet_lock
    depth = {"value": 0}

    @contextmanager
    def tracked(*args, **kwargs):
        with original(*args, **kwargs):
            depth["value"] += 1
            try:
                yield
            finally:
                depth["value"] -= 1

    monkeypatch.setattr(fleet, "fleet_lock", tracked)
    return lambda: depth["value"]


def test_native_spawn_preclaims_binds_real_ids_and_never_holds_fleet_lock(
        native_home, monkeypatch):
    home, lane = native_home
    depth = _track_lock(monkeypatch)
    client = FakeClient(home, lane)
    client.lock_depth = depth
    requested_homes = []
    monkeypatch.setattr(
        fleet, "_codex_native_client",
        lambda target: requested_homes.append(Path(target).resolve()) or client,
        raising=False)

    assert fleet.cmd_spawn(_args(lane)) == 0

    record = fleet.load_registry()["workers"]["cx-native"]
    assert requested_homes == [home.resolve()]
    assert record["dispatch_kind"] == "codex-app-server"
    assert record["substrate"] == "codex"
    assert record["session_id"] is None
    assert record["mcx_id"] is None
    assert record["codex_thread_id"] == THREAD_ID
    assert record["codex_turn_id"] == TURN_ID
    assert record["codex_host_generation"] == client.generation
    assert record["adapter_state"] == "active"
    assert record["status"] == "working"
    assert record["turns"] == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/start", "turn/start"]
    assert client.commits == [op["operation_id"] for op in client.operations]
    turn_params = client.operations[1]["payload"]["params"]
    assert turn_params["threadId"] == THREAD_ID
    assert turn_params["input"] == [{
        "type": "text",
        "text": "Read " + fleet.task_file_path("cx-native").as_posix()
                + " and follow it exactly.",
        "text_elements": [],
    }]


@pytest.mark.parametrize("mode,approval,sandbox", [
    ("bypass", "never", "danger-full-access"),
    ("accept", "on-request", "workspace-write"),
    ("dontask", "never", "workspace-write"),
    ("plan", "never", "read-only"),
    ("omit", None, None),
])
def test_native_permission_profile_is_exact(mode, approval, sandbox):
    assert fleet._codex_permission_profile(mode) == {
        "approvalPolicy": approval, "sandbox": sandbox}


def test_lost_thread_start_response_freezes_preclaim_without_retry(
        native_home, monkeypatch):
    home, lane = native_home
    import fleet_codex
    client = FakeClient(
        home, lane, fail_thread=fleet_codex.HostUnavailable("response lost"))
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client,
                        raising=False)

    with pytest.raises(fleet.FleetCliError, match="uncertain"):
        fleet.cmd_spawn(_args(lane))

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["adapter_state"] == "uncertain"
    assert record["status"] == "dead-suspected"
    assert record["codex_thread_id"] is None
    assert len(client.operations) == 1


def test_wrong_provider_cwd_freezes_without_starting_a_turn(
        native_home, monkeypatch):
    home, lane = native_home
    client = FakeClient(home, lane, thread_cwd=home)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client,
                        raising=False)

    with pytest.raises(fleet.FleetCliError, match="cwd"):
        fleet.cmd_spawn(_args(lane))

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["adapter_state"] == "uncertain"
    assert record["status"] == "dead-suspected"
    assert record["codex_thread_id"] is None
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/start"]


@pytest.mark.parametrize("field,value,error", [
    ("model", "different-model", "model"),
    ("approvalPolicy", "never", "approval"),
    ("approvalsReviewer", "client", "reviewer"),
    ("sandbox", {"type": "dangerFullAccess"}, "sandbox"),
])
def test_mismatched_effective_configuration_freezes_before_body_start(
        native_home, monkeypatch, field, value, error):
    home, lane = native_home
    client = FakeClient(home, lane, thread_fields={field: value})
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client,
                        raising=False)

    with pytest.raises(fleet.FleetCliError, match=error):
        fleet.cmd_spawn(_args(lane))

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["adapter_state"] == "uncertain"
    assert record["codex_thread_id"] is None
    assert [op["payload"]["method"] for op in client.operations] == ["thread/start"]


def test_known_local_failure_before_provider_acceptance_rolls_back_preclaim_and_files(
        native_home, monkeypatch):
    home, lane = native_home
    monkeypatch.setattr(
        fleet, "_codex_native_client",
        lambda _home: (_ for _ in ()).throw(OSError("host start failed")),
        raising=False)

    with pytest.raises(fleet.FleetCliError, match="before provider acceptance"):
        fleet.cmd_spawn(_args(lane))

    assert "cx-native" not in fleet.load_registry()["workers"]
    assert not fleet.brief_file_path("cx-native").exists()
    assert not fleet.task_file_path("cx-native").exists()


def test_preprovider_rollback_cannot_clobber_a_concurrent_same_name_claimant(
        native_home, monkeypatch):
    _home, lane = native_home
    restore_entered = threading.Event()
    successor_done = threading.Event()
    original_restore = fleet.restore_brief

    def delayed_restore(name, snapshot):
        restore_entered.set()
        successor_done.wait(0.25)
        original_restore(name, snapshot)

    def successor():
        assert restore_entered.wait(2)
        with fleet.fleet_lock():
            data = fleet.load_registry()
            assert "cx-native" not in data["workers"]
            data["workers"]["cx-native"] = {
                "last_operation_id": "successor-generation",
                "adapter_state": "preclaim", "status": "working",
            }
            fleet.save_registry(data)
            fleet.briefs_dir().mkdir(parents=True, exist_ok=True)
            fleet.tasks_dir().mkdir(parents=True, exist_ok=True)
            fleet.brief_file_path("cx-native").write_text(
                "successor brief", encoding="utf-8")
            fleet.task_file_path("cx-native").write_text(
                "successor prompt", encoding="utf-8")
        successor_done.set()

    monkeypatch.setattr(fleet, "restore_brief", delayed_restore)
    monkeypatch.setattr(
        fleet, "_codex_native_client",
        lambda _home: (_ for _ in ()).throw(OSError("host start failed")),
        raising=False)
    claimant = threading.Thread(target=successor)
    claimant.start()
    with pytest.raises(fleet.FleetCliError, match="before provider acceptance"):
        fleet.cmd_spawn(_args(lane))
    claimant.join(timeout=2)

    assert successor_done.is_set()
    assert fleet.load_registry()["workers"]["cx-native"][
        "last_operation_id"] == "successor-generation"
    assert fleet.brief_file_path("cx-native").read_text() == "successor brief"
    assert fleet.task_file_path("cx-native").read_text() == "successor prompt"


def test_preprovider_rollback_requires_the_original_claim_ownership(
        native_home, monkeypatch):
    _home, lane = native_home

    def replace_claim(_home):
        with fleet.fleet_lock():
            data = fleet.load_registry()
            replacement = data["workers"]["cx-native"]
            replacement["spawned_by"] = "successor-caller"
            replacement["spawned_by_lineage"] = ["successor-caller"]
            fleet.save_registry(data)
            fleet.brief_file_path("cx-native").write_text(
                "successor brief", encoding="utf-8")
            fleet.task_file_path("cx-native").write_text(
                "successor prompt", encoding="utf-8")
        raise OSError("host start failed")

    monkeypatch.setattr(fleet, "_codex_native_client", replace_claim,
                        raising=False)
    with pytest.raises(fleet.FleetCliError, match="before provider acceptance"):
        fleet.cmd_spawn(_args(lane))

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["spawned_by"] == "successor-caller"
    assert fleet.brief_file_path("cx-native").read_text() == "successor brief"
    assert fleet.task_file_path("cx-native").read_text() == "successor prompt"


def test_concurrent_preclaim_change_never_binds_or_starts_the_body(
        native_home, monkeypatch):
    home, lane = native_home

    def supersede():
        with fleet.fleet_lock():
            data = fleet.load_registry()
            data["workers"]["cx-native"]["last_operation_id"] = "successor-op"
            fleet.save_registry(data)

    client = FakeClient(home, lane, mutate_on_thread=supersede)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client,
                        raising=False)

    assert fleet.cmd_spawn(_args(lane)) == 1

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["last_operation_id"] == "successor-op"
    assert record["codex_thread_id"] is None
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/start"]
    assert client.commits == []


@pytest.mark.parametrize("commit_number,provider_calls", [(1, 1), (2, 2)])
def test_journal_commit_failure_freezes_the_bound_row(
        native_home, monkeypatch, commit_number, provider_calls):
    home, lane = native_home
    client = FakeClient(home, lane, fail_commit_number=commit_number)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client,
                        raising=False)

    with pytest.raises(fleet.FleetCliError, match="journal commit"):
        fleet.cmd_spawn(_args(lane))

    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["adapter_state"] == "uncertain"
    assert record["status"] == "dead-suspected"
    assert len(client.operations) == provider_calls


def test_spawn_parser_keeps_mcx_default_and_allows_explicit_native():
    parser = fleet.build_parser()
    common = ["spawn", "cx", "--dir", "/tmp", "--task", "brief",
              "--model", "codex:gpt-5.6-luna"]
    assert parser.parse_args(common).codex_adapter == "mcx"
    assert parser.parse_args(common + ["--codex-adapter", "native"]).codex_adapter \
        == "native"


def test_wave_close_mixed_codex_row_never_reaches_mcx(tmp_path, monkeypatch):
    row = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": "real-looking-mcx-id",
        "codex_thread_id": THREAD_ID, "adapter_state": "active",
    }
    monkeypatch.setattr(
        fleet, "_read_registry_readonly",
        lambda: (True, None, {"workers": {"mixed": row}}))
    monkeypatch.setattr(
        fleet, "_mcx_run",
        lambda *_args, **_kwargs: pytest.fail("mixed row reached mcx stop"))

    stopped, errors = fleet._wave_stop_landed_sessions(["mixed"])

    assert stopped == []
    assert errors == [
        "mixed: invalid mixed Codex record; refusing wave-close stop"]


def _native_record(lane, **updates):
    record = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "cwd": str(lane),
        "codex_thread_id": THREAD_ID, "codex_turn_id": TURN_ID,
        "codex_host_generation": "host-generation-1",
        "adapter_state": "active", "status": "working",
        "model": "codex:gpt-5.6-luna", "mode": "accept",
        "turns": 1, "last_operation_id": "committed-spawn",
        "last_activity": "2026-09-20T00:00:00Z",
        "last_dispatch_at": "2026-09-20T00:00:00Z",
    }
    record.update(updates)
    return record


def _install_record(lane, **updates):
    record = _native_record(lane, **updates)
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["cx-native"] = record
        fleet.save_registry(data)
    return record


class WorkerVerbClient:
    generation = "host-generation-1"
    schema_digest = "reviewed-schema"

    def __init__(self, lane, *, provider_status="active",
                 turn_status="inProgress", active_flags=None,
                 error_code=None, evidence=None, fail_method=None,
                 rate_result=None):
        self.lane = str(lane)
        self.provider_status = provider_status
        self.turn_status = turn_status
        self.active_flags = list(active_flags or [])
        self.error_code = error_code
        self.evidence = evidence
        self.fail_method = fail_method
        self.rate_result = (rate_result if rate_result is not None else {
            "ordinaryUsageAllowed": True,
            "primary": {"resetsAt": 4070908800},
        })
        self.operations = []
        self.commits = []

    def _thread(self):
        turn = {
            "id": TURN_ID, "status": self.turn_status,
            "itemsView": "full", "items": [],
        }
        if self.evidence and self.evidence.get("result_text") is not None:
            turn["items"] = [{
                "id": self.evidence["result_item_id"],
                "type": "agentMessage", "text": self.evidence["result_text"],
            }]
        if self.error_code:
            turn["error"] = {"codexErrorInfo": self.error_code}
        return {
            "thread": {
                "id": THREAD_ID, "cwd": self.lane,
                "status": {"type": self.provider_status,
                           "activeFlags": self.active_flags},
                "turns": [turn],
            },
        }

    def call(self, operation, timeout):
        self.operations.append(operation)
        public = operation.get("payload", {}).get("method")
        if self.fail_method is not None and public == self.fail_method:
            from fleet_codex import HostUnavailable
            raise HostUnavailable("response lost")
        if public == "thread/read":
            result = self._thread()
        elif operation["method"] == "public-evidence/read":
            result = self.evidence
        elif public == "turn/steer":
            result = {"turnId": TURN_ID}
        elif public == "turn/start":
            result = {"turn": {"id": NEXT_TURN_ID, "status": "inProgress",
                               "items": []}}
        elif public == "turn/interrupt":
            self.provider_status = "idle"
            self.turn_status = "interrupted"
            result = {}
        elif public == "thread/start":
            result = {
                "thread": {"id": NEXT_THREAD_ID, "cwd": self.lane},
                "cwd": self.lane, "model": "gpt-5.6-luna",
                "approvalPolicy": "on-request", "approvalsReviewer": "user",
                "sandbox": {"type": "workspaceWrite"},
            }
        elif public == "account/rateLimits/read":
            result = self.rate_result
        else:
            raise AssertionError(f"unexpected operation: {operation}")
        return SimpleNamespace(
            operation_id=operation["operation_id"], generation=self.generation,
            payload_digest="a" * 64, result=result)

    def commit(self, operation_id):
        self.commits.append(operation_id)


@pytest.mark.parametrize("provider_status,turn_status,error_code,expected", [
    ("active", "inProgress", None, "working"),
    ("idle", "completed", None, "idle"),
    ("idle", "failed", "internalServerError", "dead"),
    ("idle", "interrupted", None, "interrupted"),
    ("idle", "failed", "usageLimitExceeded", "limited"),
])
def test_native_worker_transition_matrix_uses_exact_public_turn(
        native_home, monkeypatch, provider_status, turn_status, error_code,
        expected):
    _home, lane = native_home
    record = _install_record(lane)
    client = WorkerVerbClient(
        lane, provider_status=provider_status, turn_status=turn_status,
        error_code=error_code)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    updated = fleet.recompute_worker_codex("cx-native", record)

    assert updated["status"] == expected
    assert [op["payload"]["method"] for op in client.operations][:1] == [
        "thread/read"]


def test_native_worker_host_down_is_dead_suspected_without_mcx(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(lane)
    from fleet_codex import HostUnavailable
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: (_ for _ in ()).throw(HostUnavailable("host down")))
    monkeypatch.setattr(
        fleet, "_mcx_probe",
        lambda *_args, **_kwargs: pytest.fail("native row reached mcx"))

    assert fleet.recompute_worker_codex("cx-native", record)["status"] \
        == "dead-suspected"


@pytest.mark.parametrize("provider_status,active_flags,expected_status,expected_adapter", [
    ("active", ["waitingOnApproval"], "working", "waiting"),
    ("active", ["waitingOnUserInput"], "working", "waiting"),
    ("notLoaded", [], "dead-suspected", "uncertain"),
    ("systemError", [], "dead-suspected", "uncertain"),
])
def test_native_worker_wait_and_uncertain_public_states(
        native_home, monkeypatch, provider_status, active_flags,
        expected_status, expected_adapter):
    _home, lane = native_home
    record = _install_record(lane)
    client = WorkerVerbClient(
        lane, provider_status=provider_status, active_flags=active_flags)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    updated = fleet.recompute_worker_codex("cx-native", record)

    assert updated["status"] == expected_status
    assert updated["adapter_state"] == expected_adapter


def test_native_worker_result_requires_matching_durable_item_and_usage(
        native_home, monkeypatch, capsys):
    home, lane = native_home
    record = _install_record(lane, status="idle", adapter_state="idle")
    evidence = {
        "thread_id": THREAD_ID, "turn_id": TURN_ID,
        "turn_status": "completed", "result_item_id": "item-final",
        "result_text": "bounded final", "result_truncated": False,
        "usage": {
            "cache_write_input_tokens": 0, "cached_input_tokens": 2,
            "input_tokens": 10, "output_tokens": 3,
            "reasoning_output_tokens": 1, "total_tokens": 16,
        },
    }
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="completed",
        evidence=evidence)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps(evidence), encoding="utf-8")

    assert fleet._cmd_result_codex("cx-native", record) == 0
    captured = capsys.readouterr()
    assert captured.out == "bounded final\n"
    assert "tokens in=10 out=3" in captured.err
    assert client.operations == []
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert "result_item_id" not in stored
    assert "usage" not in stored


def test_native_worker_peek_reads_only_matching_durable_item(
        native_home, capsys):
    home, lane = native_home
    record = _install_record(lane, status="idle", adapter_state="idle")
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps({
            "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
            "turn_status": "completed", "result_item_id": "item-final",
            "result_text": "durable peek text", "result_truncated": False,
        }), encoding="utf-8")

    assert fleet._cmd_peek_codex("cx-native", record, 20) == 0

    assert "[text] durable peek text" in capsys.readouterr().out


def test_native_worker_wait_reports_durable_result_summary(
        native_home, monkeypatch, capsys):
    home, lane = native_home
    depth = _track_lock(monkeypatch)
    _install_record(lane, status="working", adapter_state="active")
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps({
            "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
            "turn_status": "completed", "result_item_id": "item-final",
            "result_text": "wait durable result", "result_truncated": False,
        }), encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="completed")
    original_call = client.call

    def unlocked_call(operation, timeout):
        assert depth() == 0, "provider call occurred under fleet.lock"
        return original_call(operation, timeout)

    client.call = unlocked_call
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_wait(SimpleNamespace(
        names=["cx-native"], any=False, timeout=0)) == 0

    assert "cx-native: idle -- wait durable result" in capsys.readouterr().out


@pytest.mark.parametrize("provider_status,expected_method,expected_turn", [
    ("active", "turn/steer", TURN_ID),
    ("idle", "turn/start", NEXT_TURN_ID),
])
def test_native_worker_send_steers_busy_or_wakes_idle_same_thread(
        native_home, monkeypatch, provider_status, expected_method,
        expected_turn):
    _home, lane = native_home
    turn_status = "inProgress" if provider_status == "active" else "completed"
    _install_record(lane, status=("working" if provider_status == "active" else "idle"),
                    adapter_state=provider_status)
    client = WorkerVerbClient(
        lane, provider_status=provider_status, turn_status=turn_status)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet._cmd_send_codex("cx-native", "continue safely") == 0

    methods = [op["payload"]["method"] for op in client.operations]
    assert methods == ["thread/read", expected_method]
    mutation = client.operations[-1]["payload"]["params"]
    assert mutation["threadId"] == THREAD_ID
    if expected_method == "turn/steer":
        assert mutation["expectedTurnId"] == TURN_ID
    record = fleet.load_registry()["workers"]["cx-native"]
    assert record["codex_turn_id"] == expected_turn
    assert record["status"] == "working"


@pytest.mark.parametrize("verb", ["send", "interrupt"])
@pytest.mark.parametrize("updates,error", [
    ({"status": "dead-suspected"}, "dead-suspected"),
    ({"status": "unknown"}, "unknown"),
    ({"pending_operation": {
        "operation_id": "unresolved-op", "kind": "turn/start",
        "at": "2026-09-20T00:00:00Z",
    }}, "pending"),
    ({"adapter_state": "uncertain"}, "uncertain"),
    ({"adapter_state": "waiting"}, "waiting"),
])
def test_native_worker_mutations_refuse_non_actionable_rows_before_ipc(
        native_home, monkeypatch, verb, updates, error):
    _home, lane = native_home
    record = _install_record(lane, **updates)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("non-actionable row reached provider IPC"))

    with pytest.raises(fleet.FleetCliError, match=error):
        if verb == "send":
            fleet._cmd_send_codex("cx-native", "must not be delivered")
        else:
            fleet._cmd_interrupt_codex("cx-native", record)

    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored.get("pending_operation") == updates.get("pending_operation")


@pytest.mark.parametrize("verb", ["send", "interrupt"])
def test_native_worker_host_down_never_reserves_a_mutation(
        native_home, monkeypatch, verb):
    _home, lane = native_home
    record = _install_record(lane)
    from fleet_codex import HostUnavailable
    reserve_calls = []
    original_reserve = fleet._reserve_codex_worker_operation

    def tracked_reserve(*args, **kwargs):
        reserve_calls.append((args, kwargs))
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(fleet, "_reserve_codex_worker_operation", tracked_reserve)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: (_ for _ in ()).throw(HostUnavailable("host down")))

    with pytest.raises(HostUnavailable, match="host down"):
        if verb == "send":
            fleet._cmd_send_codex("cx-native", "must not be delivered")
        else:
            fleet._cmd_interrupt_codex("cx-native", record)

    assert reserve_calls == []
    assert "pending_operation" not in fleet.load_registry()["workers"]["cx-native"]


def test_native_worker_mailbox_io_failure_releases_mutation_reservation(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(lane)
    client = WorkerVerbClient(lane)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(
        fleet, "append_mailbox",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("mailbox full")))

    with pytest.raises(fleet.FleetCliError, match="mailbox"):
        fleet._cmd_send_codex("cx-native", "continue safely")

    assert [op["payload"]["method"] for op in client.operations] == ["thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert "pending_operation" not in stored
    assert stored["status"] == "working"
    assert stored["adapter_state"] == "active"


def test_native_worker_snapshot_counts_mail_by_thread_id(native_home):
    home, lane = native_home
    _install_record(lane)
    (home / "mailbox" / f"{THREAD_ID}.md").write_text(
        "pending direction", encoding="utf-8")

    snapshot = fleet.status_snapshot()

    assert snapshot["workers"][0]["mail"] == 1
    assert snapshot["totals"]["mail"] == 1


def test_native_worker_live_status_counts_mail_by_thread_id(
        native_home, capsys):
    home, lane = native_home
    record = _install_record(
        lane, status="idle", adapter_state="idle", cost_usd=0.0,
        last_activity=fleet.now_iso())
    (home / "mailbox" / f"{THREAD_ID}.md").write_text(
        "pending direction", encoding="utf-8")

    fleet._print_status_table({"workers": {"cx-native": record}}, ["cx-native"])

    row = capsys.readouterr().out.splitlines()[-1].split()
    assert row[5] == "1"


def test_native_worker_interrupt_requires_terminal_public_proof(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(lane)
    client = WorkerVerbClient(lane)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet._cmd_interrupt_codex("cx-native", record) == 0

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/interrupt", "thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "interrupted"
    assert stored["adapter_state"] == "idle"


def test_native_worker_interrupt_lost_response_is_uncertain_and_not_retried(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(lane)
    client = WorkerVerbClient(lane, fail_method="turn/interrupt")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="uncertain"):
        fleet._cmd_interrupt_codex("cx-native", record)

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/interrupt"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "dead-suspected"
    assert stored["adapter_state"] == "uncertain"


def test_native_worker_resume_limited_records_provider_horizon_and_starts_one_turn(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(
        lane, status="limited", adapter_state="idle",
        limit_kind="usageLimitExceeded", limit_reset_at=None)
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="failed",
        error_code="usageLimitExceeded")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet._resume_one_limited(
        "cx-native", lambda *_: None, lambda *_: None) is True

    methods = [op["payload"]["method"] for op in client.operations]
    assert methods == ["account/rateLimits/read", "thread/read", "turn/start"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["limit_reset_at"] == "2099-01-01T00:00:00Z"
    assert stored["codex_turn_id"] == NEXT_TURN_ID
    assert stored["status"] == "working"


def test_native_worker_resume_limited_obeys_public_denial_without_starting_turn(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(
        lane, status="limited", adapter_state="idle",
        limit_kind="usageLimitExceeded", limit_reset_at=None)
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="failed",
        error_code="usageLimitExceeded",
        rate_result={"ordinaryUsageAllowed": False,
                     "primary": {"resetsAt": 4070908800}})
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="not allowed"):
        fleet._resume_one_limited(
            "cx-native", lambda *_: None, lambda *_: None)

    assert [op["payload"]["method"] for op in client.operations] == [
        "account/rateLimits/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "limited"
    assert stored["ordinary_usage_allowed"] is False
    assert stored["limit_reset_at"] == "2099-01-01T00:00:00Z"


def test_native_worker_respawn_uses_fresh_thread_after_old_terminal_proof(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(lane, status="idle", adapter_state="idle")
    fleet.write_brief("cx-native", "preserve the full worker brief")
    fleet.journals_dir().mkdir(parents=True, exist_ok=True)
    fleet.journal_file_path("cx-native").write_text(
        "checkpoint from the previous thread", encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    args = SimpleNamespace(
        name="cx-native", task=None, force=False, setting_sources=None,
        token_ceiling=None, max_budget_usd=None, force_band=False)

    assert fleet._cmd_respawn_codex(args, record) == 0

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "turn/start"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["codex_thread_id"] == NEXT_THREAD_ID
    assert stored["codex_turn_id"] == NEXT_TURN_ID
    assert stored["retired_codex_threads"] == [{
        "thread_id": THREAD_ID, "turn_id": TURN_ID,
        "terminal_status": "completed",
    }]
    prompt = fleet.task_file_path("cx-native").read_text(encoding="utf-8")
    assert "preserve the full worker brief" in prompt
    assert "checkpoint from the previous thread" in prompt
