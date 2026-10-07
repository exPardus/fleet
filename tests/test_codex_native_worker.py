from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
NEXT_THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"
NEXT_TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106ba"


QUEUE_RECOVERY_APP_SERVER = r'''#!__PYTHON__
import json
import os
from pathlib import Path
import sys
import time

state_path = Path(os.environ["FAKE_QUEUE_RECOVERY_STATE"])
log_path = Path(os.environ["FAKE_QUEUE_RECOVERY_LOG"])

def load():
    return json.loads(state_path.read_text()) if state_path.exists() else {}

def save(value):
    state_path.write_text(json.dumps(value, sort_keys=True))

def log(method):
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"method": method}) + "\n")

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

def public_thread(state):
    thread = state["thread"]
    turns = state.get("turns", [])
    return {
        "id": thread["id"], "cwd": thread["cwd"],
        "threadSource": thread["threadSource"], "turns": turns,
        "status": {"type": "active" if turns else "idle", "activeFlags": []},
    }

first = json.loads(sys.stdin.readline())
send({"id": first["id"], "result": {
    "serverInfo": {"name": "fake-codex", "version": "0.155.1"}}})
if json.loads(sys.stdin.readline()) != {"method": "initialized"}:
    raise SystemExit(31)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    params = message.get("params", {})
    log(method)
    state = load()
    if method == "configRequirements/read":
        send({"id": message["id"], "result": {"requirements": None}})
    elif method == "thread/start":
        if os.environ.get("FAKE_QUEUE_RECOVERY_CREATE_THREAD", "1") == "1":
            sandbox = {"danger-full-access": "dangerFullAccess",
                       "workspace-write": "workspaceWrite",
                       "read-only": "readOnly"}[params["sandbox"]]
            state = {"thread": {
                "id": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7",
                "cwd": params["cwd"], "threadSource": params["threadSource"],
                "model": params["model"],
                "approvalPolicy": params["approvalPolicy"],
                "sandbox": {"type": sandbox},
            }, "turns": []}
            save(state)
        # With a queue bound of one, the second notification makes the stdio
        # response unknowable while the provider-side state above survives.
        send({"method": "thread/status/changed", "params": {"seq": 1}})
        send({"method": "thread/status/changed", "params": {"seq": 2}})
        time.sleep(0.1)
        send({"id": message["id"], "result": {}})
    elif method == "thread/list":
        data = [public_thread(state)] if "thread" in state else []
        send({"id": message["id"], "result": {"data": data,
                                                "nextCursor": None}})
    elif method == "thread/resume":
        thread = state["thread"]
        send({"id": message["id"], "result": {
            "thread": public_thread(state), "cwd": thread["cwd"],
            "model": thread["model"],
            "approvalPolicy": thread["approvalPolicy"],
            "approvalsReviewer": "user", "sandbox": thread["sandbox"],
        }})
    elif method == "turn/start":
        state["turns"] = [{
            "id": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8",
            "status": "inProgress", "items": [], "itemsView": "full",
        }]
        save(state)
        send({"method": "thread/status/changed", "params": {"seq": 3}})
        send({"method": "turn/started", "params": {"seq": 4}})
        time.sleep(0.1)
        send({"id": message["id"], "result": {}})
    elif method == "thread/read":
        send({"id": message["id"], "result": {
            "thread": public_thread(state)}})
    else:
        send({"id": message["id"], "error": {
            "code": -32601, "message": "unsupported fake method"}})
'''


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
        mode="accept", model="codex:gpt-5.6-luna",
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
        elif method == "thread/read":
            result = {"thread": {
                "id": THREAD_ID, "cwd": str(self.lane),
                "status": {"type": "idle", "activeFlags": []},
                "turns": [],
            }}
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


def _queue_recovery_client(home, tmp_path, *, create_thread=True):
    import fleet_codex

    app_server = tmp_path / "queue-recovery-app-server"
    app_server.write_text(
        QUEUE_RECOVERY_APP_SERVER.replace("__PYTHON__", sys.executable),
        encoding="utf-8")
    app_server.chmod(0o700)
    state = tmp_path / "provider-state.json"
    log = tmp_path / "provider-requests.jsonl"
    env = dict(os.environ)
    env.update({
        "FAKE_QUEUE_RECOVERY_STATE": str(state),
        "FAKE_QUEUE_RECOVERY_LOG": str(log),
        "FAKE_QUEUE_RECOVERY_CREATE_THREAD": "1" if create_thread else "0",
        "FLEET_CODEX_EVENT_QUEUE_MAX": "1",
    })
    client = fleet_codex.CodexHostClient.ensure(
        home, app_server_command=[str(app_server)], env=env,
        ready_timeout=20, idle_timeout=30)
    return client, log


def _stop_queue_recovery_client(client):
    from test_codex_host_ipc import _shutdown

    _shutdown(client)
    client.wait_for_exit(2)


def test_native_spawn_adopts_queue_overflows_through_production_journal(
        native_home, monkeypatch):
    home, lane = native_home
    client, log = _queue_recovery_client(home, home)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    try:
        assert fleet.cmd_spawn(_args(lane)) == 0
        record = fleet.load_registry()["workers"]["cx-native"]
        assert record["adapter_state"] == "active"
        assert record["codex_thread_id"] == THREAD_ID
        assert record["codex_turn_id"] == TURN_ID

        operations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (home / "state" / "codex" / "operations").glob(
                "worker-cx-native-*.json")
        ]
        assert len(operations) == 2
        assert {item["state"] for item in operations} == {"committed"}
        assert all(item["result"].get("adoptedFromQueueOverflow") is True
                   for item in operations)
        recovery_operations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (home / "state" / "codex" / "operations").glob(
                "queue-recovery-*.json")
        ]
        assert len(recovery_operations) == 1
        assert recovery_operations[0]["state"] == "committed"
        assert recovery_operations[0]["public_method"] == "thread/resume"
        methods = [json.loads(line)["method"]
                   for line in log.read_text(encoding="utf-8").splitlines()]
        assert methods.count("thread/start") == 1
        assert methods.count("turn/start") == 1
        assert methods.count("thread/list") == 1
        assert methods.count("thread/resume") == 1
        assert methods.count("thread/read") == 1
    finally:
        _stop_queue_recovery_client(client)


def test_native_spawn_refuses_unprovable_queue_overflow_without_replay(
        native_home, monkeypatch):
    home, lane = native_home
    client, log = _queue_recovery_client(home, home, create_thread=False)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    try:
        with pytest.raises(
                fleet.FleetCliError,
                match="mutation was not replayed.*public recovery failed"):
            fleet.cmd_spawn(_args(lane))
        record = fleet.load_registry()["workers"]["cx-native"]
        assert record["adapter_state"] == "uncertain"
        assert record["status"] == "dead-suspected"
        methods = [json.loads(line)["method"]
                   for line in log.read_text(encoding="utf-8").splitlines()]
        assert methods.count("thread/start") == 1
        assert methods.count("thread/list") == 1
        operation = next(
            json.loads(path.read_text(encoding="utf-8"))
            for path in (home / "state" / "codex" / "operations").glob(
                "worker-cx-native-thread-*.json"))
        assert operation["state"] == "uncertain"
    finally:
        _stop_queue_recovery_client(client)


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


def test_kill_fences_a_delayed_initial_turn_start(native_home, monkeypatch):
    home, lane = native_home
    client = FakeClient(home, lane)
    monkeypatch.setattr(
        fleet, "_codex_native_client", lambda _home: client, raising=False)
    original_commit = fleet._commit_codex_journal
    killed = {"done": False}

    def kill_after_thread_bind(client_arg, name, journal_operation_id,
                               record_operation_id):
        original_commit(
            client_arg, name, journal_operation_id, record_operation_id)
        if killed["done"]:
            return
        killed["done"] = True
        bound = dict(fleet.load_registry()["workers"][name])
        assert bound["adapter_state"] == "bound"
        assert fleet._cmd_kill_codex_native(
            name, bound, connect=lambda _home: client) == 0

    monkeypatch.setattr(fleet, "_commit_codex_journal", kill_after_thread_bind)

    assert fleet.cmd_spawn(_args(lane)) == 1

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/start", "thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "dead"
    assert stored["adapter_state"] == "idle"
    assert "pending_operation" not in stored


def test_journal_failure_cannot_downgrade_a_concurrent_terminal_kill(
        native_home, monkeypatch):
    home, lane = native_home
    client = FakeClient(home, lane)
    monkeypatch.setattr(
        fleet, "_codex_native_client", lambda _home: client, raising=False)
    commit_attempted = {"done": False}

    def kill_then_fail_commit(operation_id):
        assert not commit_attempted["done"]
        commit_attempted["done"] = True
        client.commits.append(operation_id)
        bound = dict(fleet.load_registry()["workers"]["cx-native"])
        assert bound["adapter_state"] == "bound"
        assert fleet._cmd_kill_codex_native(
            "cx-native", bound, connect=lambda _home: client) == 0
        raise OSError("journal commit lost after terminal kill")

    client.commit = kill_then_fail_commit

    with pytest.raises(fleet.FleetCliError, match="journal commit failed"):
        fleet.cmd_spawn(_args(lane))

    assert commit_attempted["done"] is True
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/start", "thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "dead"
    assert stored["adapter_state"] == "idle"
    assert "pending_operation" not in stored


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


def test_spawn_parser_defaults_codex_models_to_native_and_allows_explicit_mcx():
    parser = fleet.build_parser()
    common = ["spawn", "cx", "--dir", "/tmp", "--task", "brief",
              "--model", "codex:gpt-5.6-luna"]
    assert parser.parse_args(common).codex_adapter == "native"
    assert parser.parse_args(common + ["--codex-adapter", "mcx"]).codex_adapter \
        == "mcx"


def test_spawn_help_names_native_default_and_mcx_fallback():
    help_text = fleet.build_parser()._subparsers._group_actions[0].choices[
        "spawn"].format_help()

    assert "default: native" in help_text
    assert "--codex-adapter {native,mcx}" in help_text


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
                 rate_result=None, generation=None):
        self.lane = str(lane)
        if generation is not None:
            self.generation = generation
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
        elif public == "thread/resume":
            result = {
                "thread": {"id": THREAD_ID, "cwd": self.lane},
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


class BlockingResumeClient(WorkerVerbClient):
    def __init__(self, lane, **kwargs):
        super().__init__(lane, **kwargs)
        self.resume_entered = threading.Event()
        self.resume_release = threading.Event()

    def call(self, operation, timeout):
        if operation.get("payload", {}).get("method") == "thread/resume":
            self.resume_entered.set()
            if not self.resume_release.wait(timeout=5):
                raise AssertionError("test did not release thread/resume")
        return super().call(operation, timeout)


class TerminalDuringResumeClient(WorkerVerbClient):
    def commit(self, operation_id):
        super().commit(operation_id)
        operation = next(
            op for op in self.operations
            if op["operation_id"] == operation_id)
        if operation.get("payload", {}).get("method") != "thread/resume":
            return
        with fleet.fleet_lock():
            data = fleet.load_registry()
            record = data["workers"]["cx-native"]
            record["status"] = "dead"
            record["adapter_state"] = "idle"
            record["dead_reason"] = "concurrent terminal action"
            fleet.save_registry(data)


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


@pytest.mark.parametrize("provider_status", ["notLoaded", "systemError"])
def test_native_worker_completed_evidence_and_live_turn_agree_on_completion(
        native_home, monkeypatch, provider_status, capsys):
    home, lane = native_home
    record = _install_record(lane)
    evidence = {
        "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
        "turn_status": "completed", "result_item_id": "item-final",
        "result_text": "durably finished", "result_truncated": False,
        "usage": {
            "cache_write_input_tokens": 0, "cached_input_tokens": 2,
            "input_tokens": 10, "output_tokens": 3,
            "reasoning_output_tokens": 1, "total_tokens": 16,
        },
    }
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps(evidence), encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status=provider_status, turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    # This is the same exact-turn evidence accepted by the file-only result
    # surface; liveness must not contradict it merely because the live host no
    # longer has an actionable provider thread.
    assert fleet._cmd_result_codex("cx-native", record) == 0
    capsys.readouterr()
    updated = fleet.recompute_worker_codex("cx-native", record)

    assert client.generation == record["codex_host_generation"]
    assert updated["status"] == "idle"
    assert updated["adapter_state"] == "idle"
    assert updated["provider_status"] == provider_status
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


@pytest.mark.parametrize("provider_status", ["notLoaded", "systemError"])
@pytest.mark.parametrize("turn_status", ["inProgress", "failed", "interrupted"])
def test_native_worker_completed_evidence_cannot_override_live_noncompletion(
        native_home, monkeypatch, provider_status, turn_status):
    home, lane = native_home
    record = _install_record(lane)
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps({
            "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
            "turn_status": "completed",
        }), encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status=provider_status, turn_status=turn_status)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    updated = fleet.recompute_worker_codex("cx-native", record)

    assert updated["status"] == "dead-suspected"
    assert updated["adapter_state"] == "uncertain"
    assert updated["provider_status"] == provider_status
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_native_worker_status_persists_completed_evidence_as_idle(
        native_home, monkeypatch, capsys):
    home, lane = native_home
    _install_record(lane)
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps({
            "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
            "turn_status": "completed", "result_item_id": "item-final",
            "result_text": "status-visible completion",
            "result_truncated": False,
            "usage": {
                "cache_write_input_tokens": 0, "cached_input_tokens": 2,
                "input_tokens": 10, "output_tokens": 3,
                "reasoning_output_tokens": 1, "total_tokens": 16,
            },
        }), encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status="notLoaded", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    notifications = []
    monkeypatch.setattr(
        fleet, "notify_lane_done",
        lambda name, status, **_kwargs: notifications.append((name, status)))

    assert fleet.cmd_status(SimpleNamespace(
        name="cx-native", all=False, stale_ok=False, json=True)) == 0

    rendered = json.loads(capsys.readouterr().out)
    assert rendered["workers"][0]["status"] == "idle"
    assert fleet.load_registry()["workers"]["cx-native"]["status"] == "idle"
    assert notifications == [("cx-native", "idle")]


def test_native_worker_completed_evidence_cannot_clear_pending_operation(
        native_home, monkeypatch):
    home, lane = native_home
    record = _install_record(lane, pending_operation={
        "operation_id": "unresolved-op", "kind": "turn/start",
        "at": "2026-09-20T00:00:00Z",
    })
    evidence_dir = home / "state" / "codex" / "public-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / f"{THREAD_ID}.{TURN_ID}.json").write_text(
        json.dumps({
            "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
            "turn_status": "completed",
        }), encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status="notLoaded", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    updated = fleet.recompute_worker_codex("cx-native", record)

    assert updated["status"] == "dead-suspected"
    assert updated["adapter_state"] == "uncertain"


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


def test_native_worker_send_resumes_live_thread_after_host_generation_change(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(
        lane, status="dead-suspected", adapter_state="uncertain")
    client = WorkerVerbClient(lane, generation="host-generation-2")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet._cmd_send_codex("cx-native", "continue after restart") == 0

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume", "thread/read", "turn/steer"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["codex_thread_id"] == THREAD_ID
    assert stored["codex_turn_id"] == TURN_ID
    assert stored["codex_host_generation"] == "host-generation-2"
    assert stored["status"] == "working"
    assert stored["adapter_state"] == "active"
    assert "pending_operation" not in stored


def test_native_worker_lost_restart_resume_freezes_without_replaying_turn(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(lane)
    client = WorkerVerbClient(
        lane, generation="host-generation-2", fail_method="thread/resume")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="restart reconciliation"):
        fleet._cmd_send_codex("cx-native", "must not be replayed")

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["codex_host_generation"] == "host-generation-1"
    assert stored["status"] == "dead-suspected"
    assert stored["adapter_state"] == "uncertain"
    assert stored["pending_operation"]["kind"] == "thread/resume"


def test_native_worker_kill_refuses_while_restart_resume_is_pending(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(lane)
    client = BlockingResumeClient(lane, generation="host-generation-2")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    kill_connect_entered = threading.Event()
    kill_connect_release = threading.Event()
    send_outcome = {}
    kill_outcome = {}

    def send_after_restart():
        try:
            send_outcome["rc"] = fleet._cmd_send_codex(
                "cx-native", "continue after restart")
        except BaseException as exc:  # surfaced in the test thread below
            send_outcome["error"] = exc

    def connect_during_kill(_home):
        kill_connect_entered.set()
        if not kill_connect_release.wait(timeout=5):
            raise AssertionError("test did not release kill host lookup")
        return client

    def kill_old_generation():
        try:
            kill_outcome["rc"] = fleet._cmd_kill_codex_native(
                "cx-native", record, connect=connect_during_kill)
        except BaseException as exc:  # surfaced in the test thread below
            kill_outcome["error"] = exc

    killer = threading.Thread(target=kill_old_generation)
    killer.start()
    assert kill_connect_entered.wait(timeout=5)
    sender = threading.Thread(target=send_after_restart)
    sender.start()
    try:
        assert client.resume_entered.wait(timeout=5)
        kill_connect_release.set()
        killer.join(timeout=5)
    finally:
        kill_connect_release.set()
        client.resume_release.set()
        killer.join(timeout=5)
        sender.join(timeout=5)

    assert not killer.is_alive()
    assert not sender.is_alive()
    assert isinstance(kill_outcome.get("error"), fleet.FleetCliError)
    assert "thread/resume" in str(kill_outcome["error"])
    assert "refusing kill" in str(kill_outcome["error"])
    assert send_outcome == {"rc": 0}
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "working"
    assert stored["codex_host_generation"] == "host-generation-2"
    assert "pending_operation" not in stored


def test_native_worker_resume_adoption_preserves_concurrent_terminal_state(
        native_home, monkeypatch):
    _home, lane = native_home
    _install_record(lane)
    client = TerminalDuringResumeClient(
        lane, generation="host-generation-2")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="changed during host restart"):
        fleet._cmd_send_codex("cx-native", "must not continue after kill")

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume", "thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "dead"
    assert stored["adapter_state"] == "idle"
    assert stored["codex_host_generation"] == "host-generation-1"
    assert stored["pending_operation"]["kind"] == "thread/resume"


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


def test_native_worker_respawn_resumes_old_generation_before_fresh_thread(
        native_home, monkeypatch):
    _home, lane = native_home
    record = _install_record(
        lane, status="dead-suspected", adapter_state="uncertain")
    fleet.write_brief("cx-native", "preserve the restart-safe brief")
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="completed",
        generation="host-generation-2")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    args = SimpleNamespace(
        name="cx-native", task=None, force=False, setting_sources=None,
        token_ceiling=None, max_budget_usd=None, force_band=False)

    assert fleet._cmd_respawn_codex(args, record) == 0

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume", "thread/read", "thread/start", "turn/start"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["codex_thread_id"] == NEXT_THREAD_ID
    assert stored["codex_turn_id"] == NEXT_TURN_ID
    assert stored["codex_host_generation"] == "host-generation-2"
    assert stored["retired_codex_threads"] == [{
        "thread_id": THREAD_ID, "turn_id": TURN_ID,
        "terminal_status": "completed",
    }]
    assert "preserve the restart-safe brief" in \
        fleet.task_file_path("cx-native").read_text(encoding="utf-8")


def test_native_worker_respawn_cannot_resurrect_a_concurrent_kill(
        native_home, monkeypatch):
    home, lane = native_home
    record = _install_record(lane, status="idle", adapter_state="idle")
    fleet.write_brief("cx-native", "preserve the terminal worker brief")
    mailbox = home / "mailbox" / f"{THREAD_ID}.md"
    mailbox.write_text("preserve this queued direction", encoding="utf-8")
    client = WorkerVerbClient(
        lane, provider_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    original_reserve = fleet._reserve_codex_worker_operation
    killed = {"done": False}

    def kill_before_respawn_reservation(binding, operation_id, kind, **kwargs):
        if kind == "respawn/thread-start" and not killed["done"]:
            killed["done"] = True
            current = dict(fleet.load_registry()["workers"][binding.name])
            assert fleet._cmd_kill_codex_native(
                binding.name, current, connect=lambda _home: client) == 0
        return original_reserve(binding, operation_id, kind, **kwargs)

    monkeypatch.setattr(
        fleet, "_reserve_codex_worker_operation",
        kill_before_respawn_reservation)
    args = SimpleNamespace(
        name="cx-native", task=None, force=False, setting_sources=None,
        token_ceiling=None, max_budget_usd=None, force_band=False)

    with pytest.raises(fleet.FleetCliError, match="changed concurrently"):
        fleet._cmd_respawn_codex(args, record)

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]
    stored = fleet.load_registry()["workers"]["cx-native"]
    assert stored["status"] == "dead"
    assert stored["adapter_state"] == "idle"
    assert "pending_operation" not in stored
    assert mailbox.read_text(encoding="utf-8") == \
        "preserve this queued direction"
    assert list(mailbox.parent.glob(f"{THREAD_ID}.md.claimed.*")) == []
