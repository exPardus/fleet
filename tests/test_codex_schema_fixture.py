import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "codex_app_server" / "0.155.1"


def _generator():
    try:
        from tools.codex_schema_fixture import generate_contract
    except ModuleNotFoundError:
        pytest.fail("tools.codex_schema_fixture is not implemented")
    return generate_contract


def _request(method, definition=None):
    params = ({"$ref": f"#/definitions/{definition}"}
              if definition else {"type": "null"})
    required = ["id", "method"] + (["params"] if definition else [])
    return {
        "properties": {
            "id": {"type": "integer"},
            "method": {"enum": [method]},
            "params": params,
        },
        "required": required,
        "type": "object",
    }


def _notification(method):
    return {
        "properties": {"method": {"enum": [method]}},
        "required": ["method"],
        "type": "object",
    }


def _fake_schema_bundle():
    definitions = {
        "InitializeParams": {"properties": {"clientInfo": {"type": "object"}},
                             "required": ["clientInfo"], "type": "object"},
        "ThreadStartParams": {
            "properties": {
                "cwd": {"type": ["string", "null"]},
                "model": {"type": ["string", "null"]},
                "approvalPolicy": {"$ref": "#/definitions/AskForApproval"},
                "approvalsReviewer": {"$ref": "#/definitions/ApprovalsReviewer"},
                "sandbox": {"$ref": "#/definitions/SandboxMode"},
            },
            "type": "object",
        },
        "ThreadReadParams": {"properties": {"threadId": {"type": "string"}},
                             "required": ["threadId"], "type": "object"},
        "ThreadListParams": {"properties": {"cursor": {"type": ["string", "null"]}},
                             "type": "object"},
        "ThreadResumeParams": {"properties": {"threadId": {"type": "string"}},
                               "required": ["threadId"], "type": "object"},
        "ThreadTurnsListParams": {
            "properties": {"threadId": {"type": "string"},
                           "cursor": {"type": ["string", "null"]}},
            "required": ["threadId"], "type": "object"},
        "ThreadItemsListParams": {
            "properties": {"threadId": {"type": "string"},
                           "cursor": {"type": ["string", "null"]}},
            "required": ["threadId"], "type": "object"},
        "TurnStartParams": {
            "properties": {"threadId": {"type": "string"},
                           "input": {"type": "array"}},
            "required": ["threadId", "input"], "type": "object"},
        "TurnSteerParams": {
            "properties": {"threadId": {"type": "string"},
                           "expectedTurnId": {"type": "string"},
                           "input": {"type": "array"}},
            "required": ["threadId", "expectedTurnId", "input"],
            "type": "object"},
        "TurnInterruptParams": {
            "properties": {"threadId": {"type": "string"},
                           "turnId": {"type": "string"}},
            "required": ["threadId", "turnId"], "type": "object"},
        "ThreadStatus": {"oneOf": [
            {"properties": {"type": {"enum": [value]}}}
            for value in ["notLoaded", "idle", "systemError", "active"]
        ]},
        "ThreadActiveFlag": {"enum": ["waitingOnApproval", "waitingOnUserInput"]},
        "TurnStatus": {"enum": ["completed", "interrupted", "failed", "inProgress"]},
        "CodexErrorInfo": {"oneOf": [
            {"enum": ["contextWindowExceeded", "sessionBudgetExceeded",
                      "usageLimitExceeded", "rateLimitExceeded", "serverOverloaded",
                      "cyberPolicy", "misalignmentPolicyViolation",
                      "internalServerError", "unauthorized", "badRequest",
                      "threadRollbackFailed", "sandboxError", "other"]},
            {"properties": {"activeTurnNotSteerable": {"type": "object"}},
             "required": ["activeTurnNotSteerable"]},
        ]},
        "AskForApproval": {"oneOf": [{"enum": ["untrusted", "on-request", "never"]}]},
        "ApprovalsReviewer": {"enum": ["user", "auto_review", "guardian_subagent"]},
        "SandboxMode": {"enum": ["read-only", "workspace-write", "danger-full-access"]},
        "ThreadStartResponse": {
            "properties": {name: {"type": "string"} for name in
                           ["thread", "cwd", "model", "approvalPolicy",
                            "approvalsReviewer", "sandbox"]},
            "required": ["thread", "cwd", "model", "approvalPolicy",
                         "approvalsReviewer", "sandbox"],
        },
    }
    methods = [
        ("initialize", "InitializeParams"),
        ("thread/start", "ThreadStartParams"),
        ("thread/read", "ThreadReadParams"),
        ("thread/list", "ThreadListParams"),
        ("thread/resume", "ThreadResumeParams"),
        ("thread/turns/list", "ThreadTurnsListParams"),
        ("thread/items/list", "ThreadItemsListParams"),
        ("turn/start", "TurnStartParams"),
        ("turn/steer", "TurnSteerParams"),
        ("turn/interrupt", "TurnInterruptParams"),
        ("configRequirements/read", None),
    ]
    full = {"$schema": "http://json-schema.org/draft-07/schema#",
            "definitions": definitions, "title": "CodexAppServerProtocolV2"}
    requests = {"definitions": definitions,
                "oneOf": [_request(method, definition) for method, definition in methods]}
    notifications = {"oneOf": [_notification("initialized")]}
    server_notifications = {"oneOf": [
        _notification(name) for name in
        ["thread/status/changed", "thread/tokenUsage/updated", "turn/started",
         "turn/completed", "item/completed", "account/rateLimits/updated"]
    ]}
    return {
        "codex_app_server_protocol.v2.schemas.json": full,
        "ClientRequest.json": requests,
        "ClientNotification.json": notifications,
        "ServerRequest.json": {"oneOf": []},
        "ServerNotification.json": server_notifications,
    }


def _write_fake_codex(tmp_path, bundle, version="0.155.1"):
    payload = json.dumps(bundle, sort_keys=True)
    script = tmp_path / "codex-fake"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"BUNDLE = json.loads({payload!r})\n"
        f"VERSION = {version!r}\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli ' + VERSION)\n"
        "elif sys.argv[1:3] == ['app-server', 'generate-json-schema']:\n"
        "    out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    for name, value in BUNDLE.items():\n"
        "        (out / name).write_text(json.dumps(value, sort_keys=True) + '\\n')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def test_generate_contract_pins_methods_enums_permissions_and_digest(tmp_path):
    bundle = _fake_schema_bundle()
    codex = _write_fake_codex(tmp_path, bundle)
    destination = tmp_path / "fixture"

    manifest = _generator()(str(codex), destination)

    raw = (json.dumps(bundle["codex_app_server_protocol.v2.schemas.json"],
                      sort_keys=True) + "\n").encode()
    assert manifest.codex_version == "0.155.1"
    assert manifest.schema_sha256 == hashlib.sha256(raw).hexdigest()
    contract = json.loads((destination / "v2-contract.json").read_text())
    assert sorted(contract["client_methods"]) == [
        "configRequirements/read", "initialize", "thread/items/list", "thread/list",
        "thread/read", "thread/resume", "thread/start", "thread/turns/list",
        "turn/interrupt", "turn/start", "turn/steer",
    ]
    assert contract["client_notifications"] == ["initialized"]
    assert contract["client_methods"]["turn/steer"]["params_required"] == [
        "expectedTurnId", "input", "threadId"]
    assert contract["client_methods"]["turn/interrupt"]["params_required"] == [
        "threadId", "turnId"]
    assert contract["enums"]["thread_status"] == [
        "active", "idle", "notLoaded", "systemError"]
    assert contract["enums"]["thread_active_flags"] == [
        "waitingOnApproval", "waitingOnUserInput"]
    assert contract["enums"]["turn_status"] == [
        "completed", "failed", "inProgress", "interrupted"]
    assert "activeTurnNotSteerable" in contract["enums"]["codex_error_codes"]
    assert contract["enums"]["approval_policy"] == ["never", "on-request", "untrusted"]
    assert contract["enums"]["sandbox_mode"] == [
        "danger-full-access", "read-only", "workspace-write"]
    assert sorted(contract["thread_start_effective_fields"]) == [
        "approvalPolicy", "approvalsReviewer", "cwd", "model", "sandbox", "thread"]


def test_generate_contract_is_deterministic(tmp_path):
    codex = _write_fake_codex(tmp_path, _fake_schema_bundle())
    first = tmp_path / "first"
    second = tmp_path / "second"

    _generator()(str(codex), first)
    _generator()(str(codex), second)

    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "v2-contract.json").read_bytes() == (second / "v2-contract.json").read_bytes()


def test_generate_contract_rejects_oversized_public_schema(tmp_path):
    bundle = _fake_schema_bundle()
    bundle["codex_app_server_protocol.v2.schemas.json"] = {"padding": "x" * 9_000_000}
    codex = _write_fake_codex(tmp_path, bundle)

    with pytest.raises(ValueError, match="exceeds"):
        _generator()(str(codex), tmp_path / "fixture")


def test_checked_fixture_pins_reviewed_public_contract():
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    contract_bytes = (FIXTURE / "v2-contract.json").read_bytes()
    contract = json.loads(contract_bytes)

    assert manifest["codex_version"] == "0.155.1"
    assert manifest["protocol_version"] == 2
    assert manifest["contract_sha256"] == hashlib.sha256(contract_bytes).hexdigest()
    assert contract["client_methods"]["turn/steer"]["params_required"] == [
        "expectedTurnId", "input", "threadId"]
    assert contract["client_methods"]["turn/interrupt"]["params_required"] == [
        "threadId", "turnId"]
    assert {"thread/start", "thread/read", "thread/list", "thread/resume",
            "thread/turns/list", "thread/items/list", "turn/start", "turn/steer",
            "turn/interrupt"}.issubset(contract["client_methods"])


def test_checked_fixture_contains_no_private_codex_path():
    for path in FIXTURE.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "/.codex/" not in text
        assert "\\.codex\\" not in text
        assert "rollout" not in text.lower()
        assert "sqlite" not in text.lower()
