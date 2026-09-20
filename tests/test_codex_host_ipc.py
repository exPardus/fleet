import base64
import hashlib
import json
import multiprocessing.connection
import os
import stat
import sys
import threading
import time
from pathlib import Path

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
import sys

log = os.environ["FAKE_APP_SERVER_LOG"]
with open(log, "a", encoding="utf-8") as stream:
    stream.write(json.dumps({{"event": "started",
                             "inherited_claude_sid": "CLAUDE_CODE_SESSION_ID" in os.environ}}) + "\n")

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

first = json.loads(sys.stdin.readline())
send({{"id": first["id"], "result": {{"serverInfo": {{
    "name": "fake-codex", "version": "0.155.1"}}}}}})
initialized = json.loads(sys.stdin.readline())
if initialized != {{"method": "initialized"}}:
    raise SystemExit(31)
for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "test/echo":
        send({{"id": message["id"], "result": message.get("params")}})
'''


def _fake_app_server(tmp_path):
    script = tmp_path / "fake-app-server"
    script.write_text(FAKE_APP_SERVER.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o700)
    return script


def _home(tmp_path, name="home"):
    home = tmp_path / name
    (home / "state").mkdir(parents=True)
    return home.resolve()


def _ensure(tmp_path, home=None):
    module = _modules()
    home = home or _home(tmp_path)
    log = tmp_path / "app-server.jsonl"
    env = dict(os.environ)
    env["FAKE_APP_SERVER_LOG"] = str(log)
    env["CLAUDE_CODE_SESSION_ID"] = "must-not-reach-host"
    client = module.CodexHostClient.ensure(
        home,
        app_server_command=[str(_fake_app_server(tmp_path))],
        env=env,
        ready_timeout=5,
        idle_timeout=30,
    )
    return module, client, log


def _operation(operation_id="op-1", method="ping", payload=None):
    return {"operation_id": operation_id, "method": method,
            "payload": {} if payload is None else payload}


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
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    family = metadata["transport"]
    address = metadata["endpoint"]
    key = base64.b64decode(client.key_path.read_text(encoding="ascii"))
    connection = multiprocessing.connection.Client(
        address, family=family, authkey=key if authkey is None else authkey)
    try:
        connection.send_bytes(json.dumps(envelope, sort_keys=True).encode("utf-8"))
        return json.loads(connection.recv_bytes(1024 * 1024).decode("utf-8"))
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
    (home / "state" / "codex").symlink_to(target, target_is_directory=True)

    with pytest.raises(module.UnsafeHostState, match="symlink"):
        module.CodexHostClient.ensure(home, ready_timeout=1)

    assert stat.S_IMODE(target.stat().st_mode) == 0o755


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


def test_host_rejects_oversized_and_non_json_ipc_frames(tmp_path):
    _, client, _ = _ensure(tmp_path)
    metadata = json.loads(client.metadata_path.read_text(encoding="utf-8"))
    key = base64.b64decode(client.key_path.read_text(encoding="ascii"))
    try:
        connection = multiprocessing.connection.Client(
            metadata["endpoint"], family=metadata["transport"], authkey=key)
        try:
            connection.send_bytes(b"{not json")
            response = json.loads(connection.recv_bytes(1024 * 1024).decode())
            assert response["ok"] is False
        finally:
            connection.close()

        connection = multiprocessing.connection.Client(
            metadata["endpoint"], family=metadata["transport"], authkey=key)
        try:
            with pytest.raises((BrokenPipeError, EOFError, OSError)):
                connection.send_bytes(b"x" * (1024 * 1024 + 1))
                connection.recv_bytes(1024 * 1024)
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
