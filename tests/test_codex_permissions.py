import argparse
import json
import os
import sys
from types import SimpleNamespace

import pytest

import fleet
import fleet_codex


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"


def _home(tmp_path):
    home = tmp_path / "home"
    (home / "state").mkdir(parents=True)
    return home.resolve()


def _request(request_id="request-1", method="item/commandExecution/requestApproval"):
    params = {
        "threadId": THREAD_ID, "turnId": TURN_ID, "itemId": "item-1",
        "startedAtMs": 1,
    }
    if method == "item/commandExecution/requestApproval":
        params["command"] = "git status"
    elif method == "item/tool/requestUserInput":
        params.update({
            "isBlocking": True,
            "questions": [{
                "header": "Choice", "id": "choice", "question": "Continue?",
                "options": [{"label": "Yes", "description": "continue"}],
            }],
        })
    elif method == "item/permissions/requestApproval":
        params.update({
            "cwd": "/project",
            "permissions": {"network": {"enabled": True}},
        })
    elif method == "mcpServer/elicitation/request":
        params.pop("itemId")
        params.update({"serverName": "example", "message": "choose"})
    return {"id": request_id, "method": method, "params": params}


@pytest.mark.parametrize("mode,approval,sandbox", [
    ("bypass", "never", "danger-full-access"),
    ("accept", "on-request", "workspace-write"),
    ("dontask", "never", "workspace-write"),
    ("plan", "never", "read-only"),
    ("omit", None, None),
])
def test_permission_mode_map_is_exact(mode, approval, sandbox):
    assert fleet._codex_permission_profile(mode) == {
        "approvalPolicy": approval, "sandbox": sandbox}


def test_managed_requirements_refuse_disallowed_policy():
    profile = fleet._codex_permission_profile("accept")
    with pytest.raises(fleet.FleetCliError, match="disallows.*approval"):
        fleet._validate_codex_managed_requirements({"requirements": {
            "allowedApprovalPolicies": ["never"],
            "allowedSandboxModes": ["workspace-write"],
        }}, profile)

    assert fleet._validate_codex_managed_requirements({"requirements": {
        "allowedApprovalPolicies": ["on-request"],
        "allowedSandboxModes": ["workspace-write"],
    }}, profile) == {
        "allowedApprovalPolicies": ["on-request"],
        "allowedSandboxModes": ["workspace-write"],
    }


def _spawn_home(tmp_path, monkeypatch):
    home = _home(tmp_path)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    (home / "state" / "worker-settings.json").write_text(
        json.dumps({"permissions": {"allow": []}, "hooks": {}}),
        encoding="utf-8")
    (home / "logs").mkdir()
    (home / "mailbox").mkdir()
    lane = home / "lane"
    lane.mkdir()
    args = argparse.Namespace(
        name="cx", dir=str(lane), task="bounded task", mode="accept",
        model="codex:gpt-5.6-luna", codex_adapter="native",
        max_budget_usd=None, setting_sources=None, token_ceiling=None,
        category=None, nonce=None, force_band=False, context=None,
        effort="medium")
    return home, lane.resolve(), args


def test_spawn_reads_managed_requirements_before_thread_start(tmp_path, monkeypatch):
    _home_path, _lane, args = _spawn_home(tmp_path, monkeypatch)

    class Client:
        def config_requirements(self, timeout):
            assert timeout == 10
            return {"requirements": {
                "allowedApprovalPolicies": ["never"],
                "allowedSandboxModes": ["workspace-write"],
            }}

        def call(self, *_args, **_kwargs):
            pytest.fail("thread/start ran after managed-policy rejection")

    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: Client())
    with pytest.raises(fleet.FleetCliError, match="disallows.*approval"):
        fleet.cmd_spawn(args)
    assert "cx" not in fleet.load_registry()["workers"]


def test_spawn_records_returned_effective_permission_tuple(tmp_path, monkeypatch):
    _home_path, lane, args = _spawn_home(tmp_path, monkeypatch)

    class Client:
        generation = "generation-1"
        schema_digest = "reviewed"

        def __init__(self):
            self.methods = []

        def config_requirements(self, timeout):
            self.methods.append("configRequirements/read")
            return {"requirements": {
                "allowedApprovalPolicies": ["on-request"],
                "allowedSandboxModes": ["workspace-write"],
            }}

        def call(self, operation, timeout):
            method = operation["payload"]["method"]
            self.methods.append(method)
            if method == "thread/start":
                result = {
                    "thread": {"id": THREAD_ID, "cwd": str(lane)},
                    "cwd": str(lane), "model": "gpt-5.6-luna",
                    "approvalPolicy": "on-request", "approvalsReviewer": "user",
                    "sandbox": {"type": "workspaceWrite"},
                }
            else:
                result = {"turn": {"id": TURN_ID, "status": "inProgress"}}
            return SimpleNamespace(result=result, generation=self.generation)

        def commit(self, _operation_id):
            return None

    client = Client()
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    assert fleet.cmd_spawn(args) == 0
    record = fleet.load_registry()["workers"]["cx"]
    assert client.methods == [
        "configRequirements/read", "thread/start", "turn/start"]
    assert record["permission_effective"] == {
        "approvalPolicy": "on-request", "approvalsReviewer": "user",
        "sandbox": {"type": "workspaceWrite"},
    }
    assert record["permission_requirements"] == {
        "allowedApprovalPolicies": ["on-request"],
        "allowedSandboxModes": ["workspace-write"],
    }


def test_pending_request_survives_host_generation_change_and_becomes_stale(tmp_path):
    home = _home(tmp_path)
    first = fleet_codex.CodexApprovalStore(home, "generation-1")
    stored = first.record_request(_request())
    assert stored["state"] == "pending"

    rows = fleet_codex.read_pending_requests(
        home, THREAD_ID, TURN_ID, current_generation="generation-2")
    assert [(row["request_id"], row["state"], row["stale"])
            for row in rows] == [("request-1", "pending", True)]

    replacement = fleet_codex.CodexApprovalStore(home, "generation-2")
    with pytest.raises(fleet_codex.HostRejected, match="stale"):
        replacement.begin_response("request-1", THREAD_ID, TURN_ID, "accept")


def test_response_is_explicit_validated_and_consumed_once(tmp_path):
    home = _home(tmp_path)
    store = fleet_codex.CodexApprovalStore(home, "generation-1")
    store.record_request(_request())

    with pytest.raises(fleet_codex.HostRejected, match="not offered"):
        store.begin_response("request-1", THREAD_ID, TURN_ID, "approve-everything")
    with pytest.raises(fleet_codex.HostRejected, match="missing"):
        store.begin_response("request-1", THREAD_ID, THREAD_ID, "accept")

    record, response = store.begin_response(
        "request-1", THREAD_ID, TURN_ID, "acceptForSession")
    assert response == {"decision": "acceptForSession"}
    assert store.mark_responded(record)["state"] == "responded"
    with pytest.raises(fleet_codex.HostRejected, match="already consumed"):
        store.begin_response("request-1", THREAD_ID, TURN_ID, "decline")

    resolved = store.resolve({
        "method": "serverRequest/resolved",
        "params": {"requestId": "request-1", "threadId": THREAD_ID},
    })
    assert resolved["state"] == "resolved"
    assert fleet_codex.read_pending_requests(home, THREAD_ID, TURN_ID) == []


@pytest.mark.parametrize("method,decision,expected", [
    ("item/commandExecution/requestApproval", "accept", {"decision": "accept"}),
    ("item/fileChange/requestApproval", "decline", {"decision": "decline"}),
    ("item/tool/requestUserInput",
     {"answers": {"choice": {"answers": ["Yes"]}}},
     {"answers": {"choice": {"answers": ["Yes"]}}}),
    ("mcpServer/elicitation/request", {"action": "decline"},
     {"action": "decline"}),
    ("item/permissions/requestApproval",
     {"permissions": {"network": {"enabled": True}}, "scope": "turn"},
     {"permissions": {"network": {"enabled": True}}, "scope": "turn"}),
])
def test_each_reviewed_blocking_request_requires_an_explicit_valid_response(
        tmp_path, method, decision, expected):
    home = _home(tmp_path)
    store = fleet_codex.CodexApprovalStore(home, "generation-1")
    assert store.record_request(_request(method=method))["state"] == "pending"
    record, response = store.begin_response(
        "request-1", THREAD_ID, TURN_ID, decision)
    assert response == expected
    if method == "item/tool/requestUserInput":
        assert "Yes" not in json.dumps(record["response"])


def test_unknown_request_kind_is_durably_frozen(tmp_path):
    home = _home(tmp_path)
    store = fleet_codex.CodexApprovalStore(home, "generation-1")
    request = _request(method="item/tool/call")
    record = store.record_request(request)
    assert record["state"] == "unknown"
    assert record["offered_decisions"] == []
    with pytest.raises(fleet_codex.HostRejected, match="unknown"):
        store.begin_response("request-1", THREAD_ID, TURN_ID, "accept")


def _native_record(cwd):
    return {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "cwd": str(cwd),
        "codex_thread_id": THREAD_ID, "codex_turn_id": TURN_ID,
        "codex_host_generation": "generation-1",
        "adapter_state": "waiting", "status": "working", "turns": 1,
        "last_activity": "2026-09-20T00:00:00Z",
    }


def test_file_only_status_surfaces_durable_wait_without_host_probe(
        tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    (home / "state" / "fleet.json").write_text(json.dumps({
        "workers": {"cx": _native_record(home)},
    }), encoding="utf-8")
    fleet_codex.CodexApprovalStore(home, "generation-1").record_request(_request())
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("file-only status started a Codex host"))

    snap = fleet.status_snapshot()
    assert snap["workers"][0]["codex_waits"] == [{
        "request_id": "request-1",
        "kind": "item/commandExecution/requestApproval",
        "state": "pending", "item_id": "item-1",
        "offered_decisions": [
            "accept", "acceptForSession", "decline", "cancel"],
        "stale": False,
    }]
    fleet._print_snapshot_table(snap)
    assert "codex-wait:request-1:pending" in capsys.readouterr().out


def test_codex_respond_routes_only_to_exact_current_native_binding(
        tmp_path, monkeypatch, capsys):
    home = _home(tmp_path)
    monkeypatch.setattr(fleet, "FLEET_HOME", home)
    (home / "state" / "fleet.json").write_text(json.dumps({
        "workers": {"cx": _native_record(home)},
    }), encoding="utf-8")
    calls = []

    class Client:
        generation = "generation-1"

        def respond_approval(self, request_id, thread_id, turn_id, decision, timeout):
            calls.append((request_id, thread_id, turn_id, decision, timeout))
            return {"state": "resolved"}

    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: Client())
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *_args, **_kwargs: None)
    args = argparse.Namespace(
        name="cx", request_id="request-1", decision="accept", nonce=None)

    assert fleet.cmd_codex_respond(args) == 0
    assert calls == [("request-1", THREAD_ID, TURN_ID, "accept", 10)]
    assert "consumed once (resolved)" in capsys.readouterr().out


def test_codex_respond_parser_is_a_one_shot_explicit_verb():
    args = fleet.build_parser().parse_args([
        "codex-respond", "cx", "request-1", "decline"])
    assert (args.name, args.request_id, args.decision, args.nonce) == (
        "cx", "request-1", "decline", None)


APPROVAL_SERVER = r'''#!__PYTHON__
import json
import os
import sys

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

first = json.loads(sys.stdin.readline())
send({"id": first["id"], "result": {
    "serverInfo": {"name": "fake", "version": "0.155.1"}}})
assert json.loads(sys.stdin.readline()) == {"method": "initialized"}
for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "test/emit-approval":
        send({"id": "approval-1",
              "method": "item/commandExecution/requestApproval",
              "params": {"threadId": os.environ["THREAD_ID"],
                         "turnId": os.environ["TURN_ID"],
                         "itemId": "item-1", "startedAtMs": 1,
                         "command": "git status"}})
        send({"id": message["id"], "result": {"emitted": True}})
    elif message.get("id") == "approval-1":
        with open(os.environ["APPROVAL_LOG"], "a", encoding="utf-8") as stream:
            stream.write(json.dumps(message, sort_keys=True) + "\n")
        send({"method": "serverRequest/resolved",
              "params": {"requestId": "approval-1",
                         "threadId": os.environ["THREAD_ID"]}})
'''


def test_host_persists_and_resolves_only_an_explicit_one_shot_response(tmp_path):
    home = _home(tmp_path)
    script = tmp_path / "approval-server"
    script.write_text(
        APPROVAL_SERVER.replace("__PYTHON__", sys.executable), encoding="utf-8")
    script.chmod(0o700)
    log = tmp_path / "approval.jsonl"
    env = dict(os.environ, THREAD_ID=THREAD_ID, TURN_ID=TURN_ID,
               APPROVAL_LOG=str(log))
    client = fleet_codex.CodexHostClient.ensure(
        home, app_server_command=[str(script)], env=env,
        ready_timeout=20, idle_timeout=30)
    try:
        emitted = client.call({
            "operation_id": "emit", "method": "rpc",
            "payload": {"method": "test/emit-approval", "params": {}},
        }, timeout=2)
        assert emitted.result == {"emitted": True}
        assert client.pending_approvals(THREAD_ID, TURN_ID)[0]["state"] == "pending"

        result = client.respond_approval(
            "approval-1", THREAD_ID, TURN_ID, "decline", timeout=3)
        assert result["state"] == "resolved"
        assert json.loads(log.read_text(encoding="utf-8")) == {
            "id": "approval-1", "result": {"decision": "decline"}}
        with pytest.raises(fleet_codex.HostRejected, match="missing|consumed"):
            client.respond_approval(
                "approval-1", THREAD_ID, TURN_ID, "accept", timeout=2)
    finally:
        try:
            client.call({"operation_id": "shutdown", "method": "host/shutdown",
                         "payload": {}}, timeout=2)
        except Exception:
            pass
        client.wait_for_exit(2)
