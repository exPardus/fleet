import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest


def _protocol():
    try:
        import fleet_codex_protocol
    except ModuleNotFoundError:
        pytest.fail("bin/fleet_codex_protocol.py is not implemented")
    return fleet_codex_protocol


FAKE_SERVER = r'''#!{python}
import json
import os
import sys
import time

events = os.environ.get("FAKE_EVENTS")

def record(value):
    if events:
        with open(events, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")

def send(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()

first = json.loads(sys.stdin.readline())
record({{"first": first, "inherited_claude_sid": "CLAUDE_CODE_SESSION_ID" in os.environ}})
if first.get("method") != "initialize":
    raise SystemExit(40)
send({{"id": first["id"], "result": {{"serverInfo": {{"name": "fake"}}}}}})
second = json.loads(sys.stdin.readline())
record({{"second": second}})
if second.get("method") != "initialized" or "id" in second:
    raise SystemExit(41)

pending = []
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "echo":
        send({{"id": message["id"], "result": message.get("params")}})
    elif method == "reverse":
        pending.append(message)
        if len(pending) == 2:
            for item in reversed(pending):
                send({{"id": item["id"], "result": item["params"]["value"]}})
    elif method == "server/request":
        send({{"id": "server-1", "method": "item/commandExecution/requestApproval",
              "params": {{"threadId": "t", "turnId": "u", "itemId": "i"}}}})
        send({{"id": message["id"], "result": {{"queued": True}}}})
    elif method == "malformed":
        sys.stdout.write("{{not-json\n")
        sys.stdout.flush()
    elif method == "oversized":
        sys.stdout.write(json.dumps({{"method": "x", "params": "y" * 8192}}) + "\n")
        sys.stdout.flush()
    elif method == "conflicting-shape":
        send({{"id": "server-2", "method": "server/request", "result": {{}}}})
    elif method == "hang":
        time.sleep(2)
    elif method == "stderr":
        sys.stderr.write("secret=super-secret prompt=private-prompt " + "z" * 8192)
        sys.stderr.flush()
        send({{"id": message["id"], "result": {{"ok": True}}}})
    elif method == "remote/error":
        send({{"id": message["id"], "error": {{"code": -32000,
              "message": "request failed", "data": {{"secret": "super-secret",
              "input": "private-prompt"}}}}}})
    elif method == "eof":
        raise SystemExit(0)
    elif "result" in message and message.get("id") == "server-1":
        record({{"response": message}})
'''


def _server(tmp_path):
    script = tmp_path / "fake-app-server"
    script.write_text(FAKE_SERVER.format(python=sys.executable), encoding="utf-8")
    script.chmod(0o700)
    return script


def _start(tmp_path, **kwargs):
    module = _protocol()
    events = tmp_path / "events.jsonl"
    env = dict(os.environ)
    env["FAKE_EVENTS"] = str(events)
    env["CLAUDE_CODE_SESSION_ID"] = "must-not-leak"
    client = module.AppServerClient.start(
        [str(_server(tmp_path))], env=env,
        initialize_params={"clientInfo": {"name": "fleet-test", "version": "1"}},
        **kwargs)
    return module, client, events


def test_start_initializes_before_initialized_and_strips_claude_identity(tmp_path):
    _, client, events = _start(tmp_path)
    try:
        deadline = time.monotonic() + 1
        while len(events.read_text().splitlines()) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        rows = [json.loads(line) for line in events.read_text().splitlines()]
        assert rows == [
            {"first": {"id": 1, "method": "initialize",
                       "params": {"clientInfo": {"name": "fleet-test", "version": "1"}}},
             "inherited_claude_sid": False},
            {"second": {"method": "initialized"}},
        ]
    finally:
        client.close()


def test_response_ids_correlate_concurrent_requests(tmp_path):
    _, client, _ = _start(tmp_path)
    results = {}

    def call(value):
        results[value] = client.request("reverse", {"value": value}, timeout=2)

    threads = [threading.Thread(target=call, args=(value,)) for value in ("a", "b")]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        assert results == {"a": "a", "b": "b"}
    finally:
        client.close()


def test_server_request_is_exposed_and_can_be_answered(tmp_path):
    _, client, events = _start(tmp_path)
    try:
        assert client.request("server/request", {}, timeout=1) == {"queued": True}
        inbound = list(client.notifications())
        assert inbound == [{
            "id": "server-1",
            "method": "item/commandExecution/requestApproval",
            "params": {"threadId": "t", "turnId": "u", "itemId": "i"},
        }]
        client.respond("server-1", {"decision": "decline"})
        deadline = time.monotonic() + 1
        while len(events.read_text().splitlines()) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert json.loads(events.read_text().splitlines()[-1]) == {
            "response": {"id": "server-1", "result": {"decision": "decline"}}}
    finally:
        client.close()


@pytest.mark.parametrize("method, exception", [
    ("malformed", "ProtocolViolation"),
    ("oversized", "ProtocolViolation"),
    ("conflicting-shape", "ProtocolViolation"),
    ("eof", "TransportLost"),
])
def test_transport_faults_fail_the_waiting_request(tmp_path, method, exception):
    module, client, _ = _start(tmp_path, max_frame_bytes=1024)
    try:
        with pytest.raises(getattr(module, exception)):
            client.request(method, {}, timeout=1)
    finally:
        client.close()


def test_timeout_does_not_retry_or_reuse_request_id(tmp_path):
    _, client, _ = _start(tmp_path)
    try:
        with pytest.raises(TimeoutError):
            client.request("hang", {"input": "once"}, timeout=0.05)
        # The fake server is still sleeping, so this proves timeout is local and
        # does not synthesize a second mutation or silently reuse the request id.
        assert client.next_request_id > 2
    finally:
        client.close()


def test_stderr_is_bounded_and_sensitive_values_are_redacted(tmp_path):
    _, client, _ = _start(tmp_path, max_stderr_bytes=256)
    try:
        assert client.request("stderr", {}, timeout=1) == {"ok": True}
        deadline = time.monotonic() + 1
        while not client.stderr_tail() and time.monotonic() < deadline:
            time.sleep(0.01)
        diagnostic = client.stderr_tail()
        assert len(diagnostic.encode()) <= 256
        assert "super-secret" not in diagnostic
        assert "private-prompt" not in diagnostic
        assert "<redacted>" in diagnostic
    finally:
        client.close()


def test_remote_error_never_echoes_secret_or_prompt(tmp_path):
    module, client, _ = _start(tmp_path)
    try:
        with pytest.raises(module.ProtocolViolation) as caught:
            client.request("remote/error", {"secret": "outbound-secret"}, timeout=1)
        rendered = str(caught.value)
        assert "super-secret" not in rendered
        assert "private-prompt" not in rendered
        assert "outbound-secret" not in rendered
        assert "request failed" in rendered
    finally:
        client.close()
