import base64
import hashlib
import json
import multiprocessing.connection
import os
import socket
import stat
import struct
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


def _modules():
    try:
        import fleet_codex
    except ModuleNotFoundError:
        pytest.fail("bin/fleet_codex.py is not implemented")
    return fleet_codex


FAKE_APP_SERVER = r'''#!{python}
import json
import os
import signal
import sys

log = os.environ["FAKE_APP_SERVER_LOG"]
with open(log, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({{"event": "started",
                             "inherited_claude_sid": "CLAUDE_CODE_SESSION_ID" in os.environ}}) + "\n")

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

first = json.loads(sys.stdin.readline())
if os.environ.get("FAKE_INITIALIZE_PUBLIC_SHAPE") == "1":
    initialize_result = {{
        "userAgent": "fleet/0.155.1 (test)",
        "codexHome": os.environ.get(
            "FAKE_INITIALIZE_CODEX_HOME", os.environ["CODEX_HOME"]),
        "platformFamily": "unix", "platformOs": "linux",
    }}
else:
    initialize_result = {{"serverInfo": {{
        "name": "fake-codex", "version": "0.155.1"}}}}
send({{"id": first["id"], "result": initialize_result}})
initialized = json.loads(sys.stdin.readline())
if initialized != {{"method": "initialized"}}:
    raise SystemExit(31)
for line in sys.stdin:
    message = json.loads(line)
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({{"event": "request", "method": message.get("method")}}) + "\n")
    if message.get("method") == "test/echo":
        send({{"id": message["id"], "result": message.get("params")}})
    elif message.get("method") == "test/emit-lifecycle":
        params = message.get("params", {{}})
        thread_id = params["threadId"]
        turn_id = params["turnId"]
        item_id = params["itemId"]
        send({{"method": "item/completed", "params": {{
            "completedAtMs": 1, "threadId": thread_id, "turnId": turn_id,
            "item": {{"id": item_id, "type": "agentMessage",
                     "text": "durable result"}},
        }}}})
        send({{"method": "thread/tokenUsage/updated", "params": {{
            "threadId": thread_id, "turnId": turn_id,
            "tokenUsage": {{"last": {{
                "cachedInputTokens": 3, "inputTokens": 11,
                "outputTokens": 7, "reasoningOutputTokens": 2,
                "totalTokens": 18, "cacheWriteInputTokens": 0}},
                "total": {{"cachedInputTokens": 3, "inputTokens": 11,
                "outputTokens": 7, "reasoningOutputTokens": 2,
                "totalTokens": 18, "cacheWriteInputTokens": 0}}}},
        }}}})
        send({{"method": "turn/completed", "params": {{
            "threadId": thread_id,
            "turn": {{"id": turn_id, "status": "completed", "items": [
                {{"id": item_id, "type": "agentMessage",
                 "text": "durable result"}}]}},
        }}}})
        send({{"id": message["id"], "result": {{"emitted": True}}}})
    elif message.get("method") == "thread/start":
        send({{"id": message["id"], "result": {{"thread": {{"id": "thread-1"}},
              "cwd": message.get("params", {{}}).get("cwd")}}}})
    elif message.get("method") == "thread/resume":
        if os.environ.get("FAKE_CRASH_HOST_ON_THREAD_RESUME") == "1":
            os.kill(os.getppid(), signal.SIGKILL)
            raise SystemExit(42)
        send({{"id": message["id"], "result": {{
            "thread": {{"id": message.get("params", {{}}).get("threadId"),
                       "cwd": "/project"}},
            "cwd": "/project", "model": "gpt-5.6-luna",
            "approvalPolicy": "on-request", "approvalsReviewer": "user",
            "sandbox": {{"type": "workspaceWrite"}},
        }}}})
    elif message.get("method") == "thread/read":
        send({{"id": message["id"], "result": {{"thread": {{
            "id": message.get("params", {{}}).get("threadId"),
            "cwd": "/project", "status": {{"type": "idle"}},
            "turns": [
                {{"id": "turn-0", "status": "completed", "items": []}},
                {{"id": "turn-1", "status": "completed", "items": []}},
            ],
        }}}}}})
    elif message.get("method") in ("turn/start", "turn/steer", "turn/interrupt"):
        if (message.get("method") == "turn/start"
                and os.environ.get("FAKE_DROP_TURN_RESPONSE") == "1"):
            raise SystemExit(42)
        send({{"id": message["id"], "result": {{"turn": {{"id": "turn-1",
              "status": "inProgress"}}}}}})
'''


def _fake_app_server(tmp_path, version="0.155.1"):
    script = tmp_path / "fake-app-server"
    source = FAKE_APP_SERVER.replace("0.155.1", version)
    script.write_text(source.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o700)
    return script


def _fake_schema_command(tmp_path, version, schema_bytes):
    script = tmp_path / f"codex-schema-{version}"
    script.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"VERSION = {version!r}\n"
        f"SCHEMA = {schema_bytes!r}\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('codex-cli ' + VERSION)\n"
        "elif sys.argv[1:3] == ['app-server', 'generate-json-schema']:\n"
        "    out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "    out.mkdir(parents=True, exist_ok=True)\n"
        "    (out / 'codex_app_server_protocol.v2.schemas.json').write_bytes(SCHEMA)\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8")
    script.chmod(0o700)
    return script


def _home(tmp_path, name="home"):
    home = tmp_path / name
    (home / "state").mkdir(parents=True)
    return home.resolve()


def _ensure(tmp_path, home=None, env_overrides=None):
    module = _modules()
    home = home or _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    env = dict(os.environ)
    env["FAKE_APP_SERVER_LOG"] = str(log)
    env["CLAUDE_CODE_SESSION_ID"] = "must-not-reach-host"
    if env_overrides:
        env.update(env_overrides)
    client = module.CodexHostClient.ensure(
        home,
        app_server_command=[str(_fake_app_server(tmp_path))],
        env=env,
        # Readiness is polled, so a wide bound costs nothing when the host is
        # quick; 5s timed out once under a loaded full-suite run (w105).
        ready_timeout=20,
        idle_timeout=30,
    )
    return module, client, log


def _operation(operation_id="op-1", method="ping", payload=None):
    return {"operation_id": operation_id, "method": method,
            "payload": {} if payload is None else payload}


def test_connect_existing_never_ensures_or_launches_a_host(tmp_path, monkeypatch):
    module = _modules()
    home = _home(tmp_path)
    sentinel = object()
    monkeypatch.setattr(
        module.CodexHostClient, "_existing",
        classmethod(lambda cls, exact_home: sentinel))
    monkeypatch.setattr(
        module, "_reviewed_schema_manifest",
        lambda *args, **kwargs: pytest.fail(
            "attaching to a reviewed live host must not inspect installed Codex"))
    monkeypatch.setattr(
        module.CodexHostClient, "ensure",
        classmethod(lambda cls, *args, **kwargs: pytest.fail(
            "connect_existing must not ensure or launch a host")))

    assert module.connect_existing(home) is sentinel


def _shutdown(client):
    try:
        client.call(_operation("shutdown", "host/shutdown"), timeout=2)
    except Exception:
        pass


def test_two_concurrent_starters_share_one_host_and_one_app_server(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    app = _fake_app_server(tmp_path)
    log = tmp_path / "app-server.jsonl"
    env = dict(os.environ, FAKE_APP_SERVER_LOG=str(log),
               CLAUDE_CODE_SESSION_ID="must-not-reach-host")
    barrier = threading.Barrier(2)
    clients = []
    failures = []

    def start():
        try:
            barrier.wait()
            clients.append(module.CodexHostClient.ensure(
                home, app_server_command=[str(app)], env=env,
                ready_timeout=5, idle_timeout=30))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)
    try:
        assert failures == []
        assert len(clients) == 2
        assert clients[0].generation == clients[1].generation
        assert clients[0].call(_operation(), timeout=1).result["generation"] == clients[0].generation
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        assert rows == [{"event": "started", "inherited_claude_sid": False}]
    finally:
        if clients:
            _shutdown(clients[0])


def _raw_call(client, envelope, *, authkey=None):
    module = _modules()
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    family = metadata["transport"]
    address = metadata["endpoint"]
    key = base64.b64decode(client.key_path.read_text(encoding="ascii"))
    assert family == "AF_UNIX"
    deadline = time.monotonic() + 1
    connection = module._connect_authenticated(
        address, key if authkey is None else authkey, deadline)
    try:
        module._send_frame(
            connection, json.dumps(envelope, sort_keys=True).encode("utf-8"), deadline)
        return json.loads(module._recv_frame(connection, deadline).decode("utf-8"))
    finally:
        connection.close()


def _envelope(client, operation_id, method="ping", payload=None):
    payload = {} if payload is None else payload
    digest = hashlib.sha256(json.dumps(
        {"method": method, "payload": payload},
        separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    return {
        "protocol_version": 1,
        "host_generation": client.generation,
        "operation_id": operation_id,
        "method": method,
        "fleet_home": str(client.home),
        "payload": payload,
        "payload_digest": digest,
        "secret": client.key_path.read_text(encoding="ascii").strip(),
        "operation_timeout": 1.0,
    }


@pytest.mark.parametrize("mutation,error", [
    (lambda envelope: envelope.__setitem__("fleet_home", "/wrong/home"), "home"),
    (lambda envelope: envelope.__setitem__("host_generation", "wrong-generation"), "generation"),
    (lambda envelope: envelope.__setitem__("payload_digest", "0" * 64), "digest"),
])
def test_host_rejects_wrong_home_generation_and_digest(tmp_path, mutation, error):
    _, client, _ = _ensure(tmp_path)
    try:
        envelope = _envelope(client, f"bad-{error}")
        mutation(envelope)
        response = _raw_call(client, envelope)
        assert response["ok"] is False
        assert error in response["error"]
        assert client.call(_operation(f"after-{error}"), timeout=1).result["generation"] == client.generation
    finally:
        _shutdown(client)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"),
                                      float("-inf"), 0, -1, True])
def test_client_rejects_nonfinite_or_nonpositive_operation_timeout(
        tmp_path, timeout):
    _, client, _ = _ensure(tmp_path)
    try:
        with pytest.raises(ValueError, match="positive finite"):
            client.call(_operation("invalid-timeout"), timeout=timeout)
        assert client.call(_operation("after-invalid-timeout"), timeout=1).result[
            "generation"] == client.generation
    finally:
        _shutdown(client)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"),
                                      float("-inf"), 0, -1, True, 121])
def test_host_rejects_invalid_authenticated_operation_timeout(tmp_path, timeout):
    _, client, _ = _ensure(tmp_path)
    try:
        envelope = _envelope(client, "invalid-operation-timeout")
        envelope["operation_timeout"] = timeout
        response = _raw_call(client, envelope)
        assert response["ok"] is False
        assert "operation timeout" in response["error"]
        assert client.call(_operation("after-invalid-operation-timeout"), timeout=1).result[
            "generation"] == client.generation
    finally:
        _shutdown(client)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"),
                                      float("-inf"), 0, -1, True, "30"])
def test_host_rejects_invalid_nested_rpc_timeout_without_crashing(
        tmp_path, timeout):
    _, client, _ = _ensure(tmp_path)
    try:
        envelope = _envelope(
            client, "invalid-rpc-timeout", "rpc",
            {"method": "test/echo", "params": {"value": 7},
             "timeout": timeout})
        response = _raw_call(client, envelope)
        assert response["ok"] is False
        assert "timeout" in response["error"]
        assert client.call(_operation("after-invalid-rpc-timeout"), timeout=1).result[
            "generation"] == client.generation
    finally:
        _shutdown(client)


def test_nested_rpc_timeout_is_capped_by_authenticated_operation_deadline():
    import fleet_codex_host

    deadline = time.monotonic() + 10
    bounded = fleet_codex_host._bounded_rpc_timeout(
        {"timeout": 10_000_000}, 0.25, deadline)
    assert 0 < bounded <= 0.25


def test_transport_rejects_wrong_authentication_key(tmp_path):
    _, client, _ = _ensure(tmp_path)
    try:
        with pytest.raises(Exception):
            _raw_call(client, _envelope(client, "bad-auth"), authkey=b"wrong-key")
        assert client.call(_operation("after-auth"), timeout=1).result["generation"] == client.generation
    finally:
        _shutdown(client)


def test_rpc_runs_through_the_single_owned_app_server(tmp_path):
    _, client, _ = _ensure(tmp_path)
    try:
        observation = client.call(_operation(
            "rpc-1", "rpc", {"method": "test/echo", "params": {"value": 7}}),
            timeout=2)
        assert observation.result == {"value": 7}
        assert observation.operation_id == "rpc-1"
        assert observation.generation == client.generation
    finally:
        _shutdown(client)


def test_notification_drain_durably_freezes_non_object_request_params(tmp_path):
    module = _modules()
    import fleet_codex_host as host_module

    host = host_module.Host.__new__(host_module.Host)
    host.home = _home(tmp_path)
    host.approvals = module.CodexApprovalStore(host.home, "generation-1")

    class Client:
        @staticmethod
        def notifications():
            return [{
                "id": "request-1",
                "method": "item/permissions/requestApproval",
                "params": [],
            }]

    host.client = Client()
    host._drain_notifications()

    record = host.approvals.records()[0]
    assert record["request_id"] == "request-1"
    assert record["state"] == "unknown"
    assert record["params"] == []


def test_interface_claim_authorizes_current_peer_and_refuses_stale_sources(
        tmp_path, monkeypatch):
    import fleet_codex_host as host_module

    host = host_module.Host.__new__(host_module.Host)
    host.home = _home(tmp_path)
    claim = {"schema": 1, "home": str(host.home), "thread_id": "thread-current",
             "claim_id": "c1705ad1-8530-4e90-a8fc-869a7450d77b",
             "ancestor_pid": 41, "ancestor_start_identity": "100", "uid": 1000}
    monkeypatch.setattr(host_module, "read_interface_claim", lambda _home: claim)
    monkeypatch.setattr(host_module.os, "getuid", lambda: 1000)
    source = {"thread_id": "thread-current", "ancestor_pid": 41,
              "ancestor_start_identity": "100", "ancestor_cwd": str(host.home),
              "uid": 1000}
    monkeypatch.setattr(host_module, "codex_process_source",
                        lambda _pid: dict(source))

    class Peer:
        def getsockopt(self, *_args):
            return struct.pack("3i", 99, 1000, 1000)

    host._authorize_public_mutation(
        Peer(), "turn/start", {"params": {"threadId": "worker-thread"}})

    for changed in (
            {"thread_id": "thread-wrong"},
            {"ancestor_pid": 42},
            {"ancestor_start_identity": "101"}):
        original = dict(source)
        source.update(changed)
        with pytest.raises(host_module.HostRejected, match="current Interface"):
            host._authorize_public_mutation(
                Peer(), "turn/start", {"params": {"threadId": "worker-thread"}})
        source.clear()
        source.update(original)


def test_identity_invalid_unknown_request_freezes_all_provider_mutations(
        tmp_path, monkeypatch):
    module = _modules()
    import fleet_codex_host as host_module

    host = host_module.Host.__new__(host_module.Host)
    host.home = _home(tmp_path)
    host.approvals = module.CodexApprovalStore(host.home, "generation-1")
    record = host.approvals.record_request({
        "id": "request-1",
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": "invalid-thread-id",
            "turnId": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8",
            "itemId": "item-1", "startedAtMs": 1,
        },
    })
    assert record["state"] == "unknown"
    assert record["thread_id"] == "invalid-thread-id"
    monkeypatch.setattr(
        host_module, "read_interface_claim",
        lambda _home: pytest.fail("unknown request did not freeze before authorization"))

    with pytest.raises(host_module.HostRejected, match="freezes provider mutations"):
        host._authorize_public_mutation(
            object(), "turn/start", {"params": {
                "threadId": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7",
            }})


def test_external_interface_thread_is_observe_only(tmp_path, monkeypatch):
    import fleet_codex_host as host_module

    host = host_module.Host.__new__(host_module.Host)
    host.home = _home(tmp_path)
    claim = {"thread_id": "external", "ancestor_pid": 41,
             "ancestor_start_identity": "100", "uid": 1000}
    source = {"thread_id": "external", "ancestor_pid": 41,
              "ancestor_start_identity": "100", "uid": 1000}
    monkeypatch.setattr(host_module, "read_interface_claim", lambda _home: claim)
    monkeypatch.setattr(host_module, "codex_process_source", lambda _pid: source)
    monkeypatch.setattr(host_module.os, "getuid", lambda: 1000)

    class Peer:
        def getsockopt(self, *_args):
            return struct.pack("3i", 99, 1000, 1000)

    with pytest.raises(host_module.HostRejected, match="observe-only"):
        host._authorize_public_mutation(
            Peer(), "turn/steer", {"params": {"threadId": "external"}})


def test_current_supervisor_source_requires_exact_home_cwd(tmp_path, monkeypatch):
    import fleet_codex_host as host_module

    host = host_module.Host.__new__(host_module.Host)
    host.home = _home(tmp_path)
    (host.home / "supervisor").mkdir()
    (host.home / "supervisor/INCARNATION").write_text(json.dumps({
        "state": "held", "provider": "codex",
        "holder": {"provider": "codex", "thread_id": "supervisor-thread"},
    }))
    interface_claim = {"thread_id": "interface-thread", "ancestor_pid": 41,
                       "ancestor_start_identity": "100", "uid": 1000}
    source = {"thread_id": "supervisor-thread", "ancestor_pid": 55,
              "ancestor_start_identity": "200", "ancestor_cwd": str(host.home),
              "uid": 1000}
    monkeypatch.setattr(host_module, "read_interface_claim",
                        lambda _home: interface_claim)
    monkeypatch.setattr(host_module, "codex_process_source", lambda _pid: source)
    monkeypatch.setattr(host_module.os, "getuid", lambda: 1000)

    class Peer:
        def getsockopt(self, *_args):
            return struct.pack("3i", 99, 1000, 1000)

    host._authorize_public_mutation(
        Peer(), "turn/steer", {"params": {"threadId": "worker-thread"}})
    source["ancestor_cwd"] = str(tmp_path / "foreign")
    with pytest.raises(host_module.HostRejected, match="exact-home supervisor"):
        host._authorize_public_mutation(
            Peer(), "turn/steer", {"params": {"threadId": "worker-thread"}})


def test_public_turn_evidence_survives_store_and_host_restart(tmp_path):
    module, client, _ = _ensure(tmp_path)
    thread_id = "018f22d3-9b4a-7cc3-8a0e-36d4f59106d1"
    turn_id = "018f22d3-9b4a-7cc3-8a0e-36d4f59106d2"
    item_id = "item-final-1"
    try:
        emitted = client.call(_operation(
            "emit-lifecycle", "rpc", {
                "method": "test/emit-lifecycle",
                "params": {"threadId": thread_id, "turnId": turn_id,
                           "itemId": item_id},
            }), timeout=2)
        assert emitted.result == {"emitted": True}

        evidence = None
        for _ in range(40):
            evidence = client.call(_operation(
                "read-evidence", "public-evidence/read",
                {"thread_id": thread_id, "turn_id": turn_id}), timeout=1).result
            if evidence and evidence.get("usage"):
                break
            time.sleep(0.025)
        assert evidence["turn_status"] == "completed"
        assert evidence["result_text"] == "durable result"
        assert evidence["result_item_id"] == item_id
        assert evidence["usage"] == {
            "cache_write_input_tokens": 0,
            "cached_input_tokens": 3,
            "input_tokens": 11,
            "output_tokens": 7,
            "reasoning_output_tokens": 2,
            "total_tokens": 18,
        }
    finally:
        _shutdown(client)

    restarted = module.CodexPublicEvidenceStore(client.home)
    assert restarted.read(thread_id, turn_id) == evidence


def test_public_turn_evidence_store_survives_process_restart_without_provider(
        tmp_path):
    module = _modules()
    home = _home(tmp_path)
    thread_id = "018f22d3-9b4a-7cc3-8a0e-36d4f59106d3"
    turn_id = "018f22d3-9b4a-7cc3-8a0e-36d4f59106d4"
    item_id = "item-final-2"
    store = module.CodexPublicEvidenceStore(home)
    store.record({"method": "item/completed", "params": {
        "completedAtMs": 1, "threadId": thread_id, "turnId": turn_id,
        "item": {"id": item_id, "type": "agentMessage",
                 "text": "restart-safe result"},
    }})
    store.record({"method": "thread/tokenUsage/updated", "params": {
        "threadId": thread_id, "turnId": turn_id,
        "tokenUsage": {"last": {
            "cachedInputTokens": 2, "inputTokens": 13,
            "outputTokens": 5, "reasoningOutputTokens": 1,
            "totalTokens": 18, "cacheWriteInputTokens": 0},
            "total": {}},
    }})
    store.record({"method": "turn/completed", "params": {
        "threadId": thread_id,
        "turn": {"id": turn_id, "status": "completed", "items": [
            {"id": item_id, "type": "agentMessage",
             "text": "restart-safe result"}]},
    }})

    evidence = module.CodexPublicEvidenceStore(home).read(thread_id, turn_id)
    assert evidence["turn_status"] == "completed"
    assert evidence["result_text"] == "restart-safe result"
    assert evidence["usage"]["input_tokens"] == 13
    assert evidence["usage"]["output_tokens"] == 5


def _unsafe_state(tmp_path, kind):
    home = _home(tmp_path, kind)
    directory = home / "state" / "codex"
    directory.mkdir(mode=0o700)
    host = directory / "host.json"
    key = directory / "host.key"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("{}", encoding="utf-8")
        host.symlink_to(target)
    elif kind == "mode":
        key.write_text(base64.b64encode(b"x" * 32).decode(), encoding="ascii")
        key.chmod(0o644)
    elif kind == "type":
        host.mkdir()
    elif kind == "hostile-json":
        host.write_text("{not json", encoding="utf-8")
        host.chmod(0o600)
    elif kind == "oversized":
        host.write_text("{" + "x" * 70_000, encoding="utf-8")
        host.chmod(0o600)
    return home


def test_host_key_is_not_visible_until_fully_written(tmp_path, monkeypatch):
    module = _modules()
    path = tmp_path / "host.key"
    original_write = module.os.write
    observed = []

    def write(fd, data):
        observed.append((path.exists(), stat.S_IMODE(os.fstat(fd).st_mode)))
        return original_write(fd, data)

    monkeypatch.setattr(module.os, "write", write)
    encoded, decoded = module._create_key(path)
    assert observed == [(False, 0o600)]
    assert module._read_key(path) == (encoded, decoded)
    assert not list(tmp_path.glob(".host.key.*.tmp"))


def test_codex_host_platform_decisions_use_fleet_adapter(tmp_path, monkeypatch):
    module = _modules()
    import fleet_platform

    monkeypatch.setattr(fleet_platform, "PLATFORM",
                        SimpleNamespace(is_windows=True, is_linux=False))
    assert module._linux_process_record(os.getpid()) is None
    with pytest.raises(module.HostUnavailable, match="Windows"):
        module._endpoint_for(tmp_path, tmp_path)


@pytest.mark.parametrize("kind", ["symlink", "mode", "type", "hostile-json", "oversized"])
def test_unsafe_fixed_state_refuses_without_starting_a_replacement(tmp_path, kind):
    module = _modules()
    home = _unsafe_state(tmp_path, kind)
    log = tmp_path / "must-not-start.jsonl"
    env = dict(os.environ, FAKE_APP_SERVER_LOG=str(log))

    with pytest.raises(module.UnsafeHostState):
        module.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path))], env=env,
            ready_timeout=1)

    assert not log.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink mode assertion")
def test_symlinked_state_directory_is_not_followed_or_chmodded(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    target = tmp_path / "foreign"
    target.mkdir(mode=0o755)
    mode_before = stat.S_IMODE(target.stat().st_mode)
    (home / "state" / "codex").symlink_to(target, target_is_directory=True)

    with pytest.raises(module.UnsafeHostState, match="symlink"):
        module.CodexHostClient.ensure(home, ready_timeout=1)

    assert stat.S_IMODE(target.stat().st_mode) == mode_before


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink confinement")
def test_symlinked_state_parent_is_rejected_without_creating_foreign_state(tmp_path):
    module = _modules()
    home = tmp_path / "home"
    home.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (home / "state").symlink_to(foreign, target_is_directory=True)

    with pytest.raises(module.UnsafeHostState, match="symlink"):
        module.CodexHostClient.ensure(home, ready_timeout=0.2)

    assert not (foreign / "codex").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner check")
def test_wrong_owner_refuses_without_starting_a_replacement(tmp_path, monkeypatch):
    module = _modules()
    home = _home(tmp_path)
    directory = home / "state" / "codex"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(module.os, "getuid", lambda: os.stat(directory).st_uid + 1)
    log = tmp_path / "must-not-start.jsonl"

    with pytest.raises(module.UnsafeHostState, match="owner"):
        module.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path))],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)), ready_timeout=1)

    assert not log.exists()


def test_host_state_is_owner_only_and_pid_does_not_decide_identity(tmp_path):
    _, client, _ = _ensure(tmp_path)
    try:
        metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
        assert metadata["home"] == str(client.home)
        assert metadata["schema_digest"] == "f0402dc8ce8d278108f1e68e9d46ec7e59ddd9d153f5e70668d84d56f258dda3"
        if os.name != "nt":
            assert stat.S_IMODE(client.state_dir.stat().st_mode) == 0o700
            assert stat.S_IMODE(client.key_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(client.metadata_path.stat().st_mode) == 0o600
            assert stat.S_IMODE(Path(metadata["endpoint"]).stat().st_mode) == 0o600

        metadata["pid"] = 999_999_999
        temporary = client.metadata_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(metadata), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, client.metadata_path)
        again = client.__class__.ensure(client.home, ready_timeout=2)
        assert again.generation == client.generation
    finally:
        _shutdown(client)


@pytest.mark.parametrize("field,value", [
    ("generation", "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"),
    ("endpoint", "/tmp/not-the-derived-endpoint"),
    ("transport", "AF_PIPE"),
    ("ipc_protocol_version", 999),
    ("codex_protocol_version", 999),
    ("codex_version", "9.9.9"),
    ("schema_digest", "0" * 64),
    ("process_identity", None),
    ("app_server_process_identity", None),
])
def test_existing_host_metadata_must_match_the_exact_reviewed_contract(
        tmp_path, field, value):
    module, client, _ = _ensure(tmp_path)
    original = client.metadata_path.read_bytes()
    metadata = json.loads(original)
    metadata[field] = value
    client.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    client.metadata_path.chmod(0o600)
    try:
        with pytest.raises(module.UnsafeHostState):
            module.CodexHostClient.ensure(client.home, ready_timeout=0.2)
    finally:
        client.metadata_path.write_bytes(original)
        client.metadata_path.chmod(0o600)
        _shutdown(client)


def test_live_old_host_remains_reachable_after_installed_version_change(
        tmp_path, monkeypatch):
    module = _modules()
    home = _home(tmp_path)
    schemas = {
        version: (json.dumps({"reviewed": version}, sort_keys=True) + "\n").encode()
        for version in ("0.155.1", "0.160.0")
    }
    manifests = dict(module.REVIEWED_SCHEMA_MANIFESTS)
    for version, schema_bytes in schemas.items():
        value = json.loads(manifests[version].read_text(encoding="utf-8"))
        value["schema_sha256"] = hashlib.sha256(schema_bytes).hexdigest()
        manifest = tmp_path / f"manifest-{version}.json"
        manifest.write_text(json.dumps(value), encoding="utf-8")
        manifests[version] = manifest
    monkeypatch.setattr(module, "REVIEWED_SCHEMA_MANIFESTS", manifests)
    log = tmp_path / "app-server.jsonl"
    old_client = module.CodexHostClient.ensure(
        home,
        app_server_command=[str(_fake_app_server(tmp_path, "0.155.1"))],
        schema_command=[str(_fake_schema_command(
            tmp_path, "0.155.1", schemas["0.155.1"]))],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
        ready_timeout=5,
        idle_timeout=0,
    )
    try:
        new_client = module.CodexHostClient.ensure(
            home,
            app_server_command=[str(tmp_path / "must-not-start")],
            schema_command=[str(_fake_schema_command(
                tmp_path, "0.160.0", schemas["0.160.0"]))],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
            ready_timeout=2,
            idle_timeout=0,
        )

        metadata = json.loads(new_client.metadata_path.read_text(encoding="utf-8"))
        assert new_client.generation == old_client.generation
        assert metadata["codex_version"] == "0.155.1"
        assert [json.loads(line) for line in log.read_text().splitlines()] == [
            {"event": "started", "inherited_claude_sid": False},
        ]
    finally:
        _shutdown(old_client)


def test_silent_and_disconnected_clients_cannot_wedge_or_crash_host(tmp_path):
    _, client, _ = _ensure(tmp_path)
    endpoint = json.loads(client.metadata_path.read_text())["endpoint"]
    silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        silent.connect(endpoint)
        time.sleep(1.2)
        silent.close()
        disconnected = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        disconnected.connect(endpoint)
        disconnected.close()
        assert client.call(_operation("after-hostile-peers"), timeout=2).result[
            "generation"] == client.generation
    finally:
        silent.close()
        _shutdown(client)


def test_busy_host_is_not_replaced_when_ping_deadline_expires(tmp_path):
    module, client, log = _ensure(tmp_path)
    endpoint = json.loads(client.metadata_path.read_text())["endpoint"]
    silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        silent.connect(endpoint)
        started = time.monotonic()
        with pytest.raises(module.HostUnavailable, match="refusing replacement"):
            module.CodexHostClient.ensure(client.home, ready_timeout=0.7)
        assert time.monotonic() - started < 1.5
        assert [json.loads(line) for line in log.read_text().splitlines()] == [
            {"event": "started", "inherited_claude_sid": False}]
    finally:
        silent.close()
        time.sleep(1.1)
        _shutdown(client)


def test_live_stale_lock_is_never_stolen_and_dead_lock_is_recoverable(tmp_path):
    module = _modules()
    path = tmp_path / "host.lock"
    live = {"pid": os.getpid(), "identity": module._process_identity(os.getpid()),
            "nonce": "live"}
    path.write_text(json.dumps(live), encoding="ascii")
    path.chmod(0o600)
    old = time.time() - module.HOST_LOCK_STALE_SECONDS - 2
    os.utime(path, (old, old))
    with pytest.raises(module.HostUnavailable):
        with module._host_lock(path, 0.05):
            pass
    assert json.loads(path.read_text())["nonce"] == "live"

    dead = {"pid": 999_999_999, "identity": "dead", "nonce": "dead"}
    path.write_text(json.dumps(dead), encoding="ascii")
    path.chmod(0o600)
    os.utime(path, (old, old))
    with module._host_lock(path, 0.2):
        assert json.loads(path.read_text())["pid"] == os.getpid()


def test_linux_process_identity_still_reads_proc_stat_field_22(monkeypatch):
    module = _modules()
    import fleet_platform

    monkeypatch.setattr(
        fleet_platform, "PLATFORM",
        SimpleNamespace(is_windows=False, is_linux=True))
    fields = [str(index) for index in range(1, 25)]
    monkeypatch.setattr(
        module.Path, "read_text",
        lambda self, encoding=None: " ".join(fields))

    assert module._process_identity(1234) == fields[21]


def test_darwin_process_identity_reads_kern_proc_pid_start_time(monkeypatch):
    module = _modules()
    import fleet_platform

    monkeypatch.setattr(
        fleet_platform, "PLATFORM",
        SimpleNamespace(is_windows=False, is_linux=False))
    prefix = module._DarwinKinfoProcPrefix()
    prefix.kp_proc.p_starttime.tv_sec = 1_800_000_001
    prefix.kp_proc.p_starttime.tv_usec = 2345
    payload = bytes(prefix) + b"\0" * 64
    calls = []

    def fake_sysctl(mib, length, oldp, oldlenp, newp, newlen):
        calls.append((list(mib), length, oldp is None, newp, newlen))
        oldlenp._obj.value = len(payload)
        if oldp is not None:
            module.ctypes.memmove(oldp, payload, len(payload))
        return 0

    sysctl_identity = module._darwin_sysctl_process_identity
    monkeypatch.setattr(
        module, "_darwin_sysctl_process_identity",
        lambda pid: sysctl_identity(pid, sysctl=fake_sysctl))
    monkeypatch.setattr(
        module, "_darwin_ps_process_identity",
        lambda pid: pytest.fail("ps fallback must not run after sysctl succeeds"))

    assert module._process_identity(4321) == "darwin:1800000001.002345"
    assert calls == [
        ([1, 14, 1, 4321], 4, True, None, 0),
        ([1, 14, 1, 4321], 4, False, None, 0),
    ]


def test_darwin_process_identity_falls_back_to_ps_lstart(monkeypatch):
    module = _modules()
    import fleet_platform

    monkeypatch.setattr(
        fleet_platform, "PLATFORM",
        SimpleNamespace(is_windows=False, is_linux=False))
    monkeypatch.setattr(
        module, "_darwin_sysctl_process_identity", lambda pid: None)
    observed = {}

    def fake_run(argv, **kwargs):
        observed.update({"argv": argv, **kwargs})
        return SimpleNamespace(
            returncode=0, stdout="Thu Oct  8 12:34:56 2026\n")

    ps_identity = module._darwin_ps_process_identity
    monkeypatch.setattr(
        module, "_darwin_ps_process_identity",
        lambda pid: ps_identity(pid, run=fake_run))

    assert module._process_identity(4321) == "darwin-ps:2026-10-08T12:34:56"
    assert observed["argv"] == ["ps", "-o", "lstart=", "-p", "4321"]
    assert observed["env"]["LC_ALL"] == "C"
    assert observed["env"]["LC_TIME"] == "C"


def test_darwin_identity_source_change_does_not_make_live_lock_stealable(
        tmp_path, monkeypatch):
    module = _modules()
    path = tmp_path / "host.lock"
    path.write_text(json.dumps({
        "pid": 4321,
        "identity": "darwin:1800000001.002345",
        "nonce": "live",
    }), encoding="ascii")
    monkeypatch.setattr(
        module, "_process_identity",
        lambda pid: "darwin-ps:2027-01-15T08:00:01")
    kill_calls = []
    monkeypatch.setattr(
        module.os, "kill", lambda pid, signal: kill_calls.append((pid, signal)))

    assert module._lock_holder_is_live(path) is True
    assert kill_calls == [(4321, 0)]


def test_darwin_identity_source_change_does_not_replace_live_host(monkeypatch):
    module = _modules()
    owner = SimpleNamespace(
        _pid=4321,
        _process_identity="darwin-ps:2027-01-15T08:00:01",
    )
    monkeypatch.setattr(
        module, "_process_identity",
        lambda pid: "darwin:1800000001.002345")
    kill_calls = []
    monkeypatch.setattr(
        module.os, "kill", lambda pid, signal: kill_calls.append((pid, signal)))

    assert module.CodexHostClient._owner_live(owner) is True
    assert kill_calls == [(4321, 0)]


@pytest.mark.parametrize("version", ["0.155.1", "0.160.0"])
def test_installed_reviewed_codex_versions_select_their_manifest(
        tmp_path, monkeypatch, version):
    module = _modules()
    selected = module.REVIEWED_SCHEMA_MANIFESTS[version]
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=f"codex-cli {version}\n"))

    assert module._reviewed_schema_manifest(
        ["codex"], env={}, cwd=tmp_path) == selected
    assert json.loads(selected.read_text(encoding="utf-8"))["codex_version"] == version


@pytest.mark.parametrize("version", ["0.155.1", "0.160.0"])
def test_each_reviewed_codex_version_can_publish_a_matching_host(
        tmp_path, monkeypatch, version):
    module = _modules()
    home = _home(tmp_path)
    schema_bytes = (json.dumps({"reviewed": version}, sort_keys=True) + "\n").encode()
    manifest = tmp_path / f"manifest-{version}.json"
    value = json.loads(
        module.REVIEWED_SCHEMA_MANIFESTS[version].read_text(encoding="utf-8"))
    value["schema_sha256"] = hashlib.sha256(schema_bytes).hexdigest()
    manifest.write_text(json.dumps(value), encoding="utf-8")
    manifests = dict(module.REVIEWED_SCHEMA_MANIFESTS)
    manifests[version] = manifest
    monkeypatch.setattr(module, "REVIEWED_SCHEMA_MANIFESTS", manifests)
    log = tmp_path / "app-server.jsonl"
    client = module.CodexHostClient.ensure(
        home,
        app_server_command=[str(_fake_app_server(tmp_path, version))],
        schema_command=[str(_fake_schema_command(
            tmp_path, version, schema_bytes))],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
        ready_timeout=5, idle_timeout=30)
    try:
        metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
        assert metadata["codex_version"] == version
        assert metadata["schema_digest"] == value["schema_sha256"]
    finally:
        _shutdown(client)


def test_unreviewed_installed_codex_version_is_refused(tmp_path, monkeypatch):
    module = _modules()
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="codex-cli 9.9.9\n"))

    with pytest.raises(module.HostUnavailable, match="no reviewed schema"):
        module._reviewed_schema_manifest(["codex"], env={}, cwd=tmp_path)


def test_idle_host_shuts_down_without_killing_or_signaling_provider_pid(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    client = module.CodexHostClient.ensure(
        home,
        app_server_command=[str(_fake_app_server(tmp_path))],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
        ready_timeout=5,
        idle_timeout=0.5,
    )
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 3
    endpoint = Path(metadata["endpoint"]) if metadata["transport"] == "AF_UNIX" else None
    while endpoint is not None and endpoint.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if endpoint is not None:
        assert not endpoint.exists()
    assert client.wait_for_exit(2)


def test_unreviewed_app_server_version_never_publishes_ready(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    app = _fake_app_server(tmp_path)
    app.write_text(
        app.read_text(encoding="utf-8").replace(
            '"version": "0.155.1"', '"version": "9.9.9"'),
        encoding="utf-8",
    )
    log = tmp_path / "app-server.jsonl"
    client = None
    try:
        with pytest.raises(module.HostUnavailable):
            client = module.CodexHostClient.ensure(
                home,
                app_server_command=[str(app)],
                env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)),
                ready_timeout=1,
            )
    finally:
        if client is not None:
            _shutdown(client)
    assert not (home / "state" / "codex" / "host.json").exists()


def test_reviewed_public_initialize_shape_publishes_ready(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    log = tmp_path / "app-server.jsonl"
    client = module.CodexHostClient.ensure(
        home, app_server_command=[str(_fake_app_server(tmp_path))],
        env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log),
                 FAKE_INITIALIZE_PUBLIC_SHAPE="1",
                 CODEX_HOME=str(codex_home)),
        ready_timeout=5, idle_timeout=30)
    try:
        assert client.call(_operation("public-init"), timeout=1).result[
            "schema_digest"] == json.loads(
                module.REVIEWED_SCHEMA_MANIFESTS["0.155.1"].read_text())[
                    "schema_sha256"]
        metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
        assert metadata["pid"] == client.host_pid
        assert metadata["process_identity"] == client.host_process_identity
        assert metadata["app_server_pid"] == client.app_server_pid
        assert (metadata["app_server_process_identity"]
                == client.app_server_process_identity)
        assert metadata["started_at"] == client.started_at
        assert metadata["app_server_started_at"] == client.app_server_started_at
    finally:
        _shutdown(client)


def test_public_initialize_wrong_codex_home_never_publishes_ready(tmp_path):
    module = _modules()
    home = _home(tmp_path)
    codex_home = tmp_path / "codex-home"
    wrong_home = tmp_path / "wrong-codex-home"
    codex_home.mkdir()
    wrong_home.mkdir()
    log = tmp_path / "app-server.jsonl"

    with pytest.raises(module.HostUnavailable):
        module.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path))],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log),
                     FAKE_INITIALIZE_PUBLIC_SHAPE="1",
                     FAKE_INITIALIZE_CODEX_HOME=str(wrong_home),
                     CODEX_HOME=str(codex_home)),
            ready_timeout=1, idle_timeout=30)

    assert not (home / "state" / "codex" / "host.json").exists()


def test_installed_schema_digest_mismatch_never_publishes_ready(
        tmp_path, monkeypatch):
    module = _modules()
    home = _home(tmp_path)
    manifest = tmp_path / "manifest.json"
    value = json.loads(
        module.REVIEWED_SCHEMA_MANIFESTS["0.155.1"].read_text())
    value["schema_sha256"] = "0" * 64
    manifest.write_text(json.dumps(value), encoding="utf-8")
    manifests = dict(module.REVIEWED_SCHEMA_MANIFESTS)
    manifests["0.155.1"] = manifest
    monkeypatch.setattr(module, "REVIEWED_SCHEMA_MANIFESTS", manifests)
    log = tmp_path / "app-server.jsonl"

    with pytest.raises(module.HostUnavailable):
        module.CodexHostClient.ensure(
            home, app_server_command=[str(_fake_app_server(tmp_path))],
            env=dict(os.environ, FAKE_APP_SERVER_LOG=str(log)), ready_timeout=1)

    assert not log.exists()
    assert not (home / "state" / "codex" / "host.json").exists()


def test_host_rejects_oversized_and_non_json_ipc_frames(tmp_path):
    module = _modules()
    _, client, _ = _ensure(tmp_path)
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    key = base64.b64decode(client.key_path.read_text(encoding="ascii"))
    try:
        deadline = time.monotonic() + 1
        connection = module._connect_authenticated(metadata["endpoint"], key, deadline)
        try:
            module._send_frame(connection, b"{not json", deadline)
            response = json.loads(module._recv_frame(connection, deadline).decode())
            assert response["ok"] is False
        finally:
            connection.close()

        deadline = time.monotonic() + 1
        connection = module._connect_authenticated(metadata["endpoint"], key, deadline)
        try:
            connection.sendall((1024 * 1024 + 1).to_bytes(4, "big"))
            response = json.loads(module._recv_frame(connection, deadline).decode())
            assert response["ok"] is False
            assert "exceeds" in response["error"]
        finally:
            connection.close()
        assert client.call(_operation("after-hostile"), timeout=1).result["generation"] == client.generation
    finally:
        _shutdown(client)


def test_host_modules_do_not_import_registry_or_claim_writer():
    root = Path(__file__).resolve().parents[1] / "bin"
    for name in ("fleet_codex.py", "fleet_codex_host.py"):
        path = root / name
        if not path.exists():
            pytest.fail(f"{name} is not implemented")
        text = path.read_text(encoding="utf-8")
        assert "from fleet import" not in text
        assert "import fleet\n" not in text
        assert "fleet_lock(" not in text
