"""B's protocol through an injected socket, plus an isolated Unix wire probe.

The fixture is deliberately NOT a live-model proof. It checks framing, retry
and watchdog behavior through the production keeper, not a model substitute.
"""
import io
import json
import socket
import threading

import pytest

import fleet
import fleet_keeper as k
from test_keeper_main import Runner

SID = "11111111-2222-3333-4444-555555555555"
OTHER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NOW = 1_800_000_000.0
IDENTITY = ["inc-test", SID]
TARGET = {"short": "1234abcd", "session_id": SID, "pid": 123}
JOB = {"short": "1234abcd", "sessionId": SID, "pid": 123}
LIST = {"ok": True, "op": "list", "jobs": [JOB]}


def status(**over):
    result = {"goals_active": True, "incarnation": {
        "incarnation_id": IDENTITY[0], "session_id": SID, "state": None,
        "nonce_present": True, "pending_present": False,
        "handoff_pending_count": 0}, "claim_sids": [SID, OTHER],
        "heartbeat_age_seconds": 4000, "pending_decision": None,
        "handshake": None, "abort_flag": False}
    result.update(over)
    return result


def observation(**over):
    result = {"wake_identity": IDENTITY, "registry_ok": True,
              "agents_ok": True, "goals_active": True, "claim_state": "held",
              "claim_sid": SID, "sid_union_ok": True,
              "claim_rows": {SID: "idle", OTHER: "idle"},
              "heartbeat_age_seconds": 4000, "hook_error_lines": 0}
    result.update(over)
    return result


def test_two_samples_then_quarter_hour_retries_including_refusal():
    due, record = k.wake_due(observation(), None, NOW)
    assert not due
    assert not k.wake_due(observation(), record, NOW + 899)[0]
    assert k.wake_due(observation(), record, NOW + 900)[0]
    record.update(attempt_at=NOW + 900, result="refused")
    assert not k.wake_due(observation(), record, NOW + 1799)[0]
    assert k.wake_due(observation(), record, NOW + 1800)[0]


@pytest.mark.parametrize("over", [
    {"registry_ok": False}, {"agents_ok": False}, {"goals_active": False},
    {"claim_state": "released"}, {"claim_state": "unknown"},
    {"wake_identity": None}, {"sid_union_ok": False},
    {"claim_rows": {SID: "busy"}}, {"claim_rows": {SID: "waiting"}},
    {"claim_rows": {SID: "idle", OTHER: "busy"}},
    {"claim_rows": {SID: "idle", OTHER: "waiting"}},
    {"claim_rows": {OTHER: "idle"}}, {"claim_rows": {SID: None}},
])
def test_uncertain_busy_or_retired_only_body_is_never_woken(over):
    assert k.wake_due(observation(**over), {}, NOW) == (False, None)


def test_busy_or_claim_change_requires_a_new_idle_window():
    _, previous = k.wake_due(observation(), None, NOW)
    assert k.wake_due(observation(claim_rows={SID: "busy"}), previous, NOW + 900) == (False, None)
    due, record = k.wake_due(observation(wake_identity=["new-inc", SID]), previous, NOW + 900)
    assert not due and record["idle_since"] == NOW + 900


@pytest.mark.parametrize("previous", [None, [], {"identity": IDENTITY, "idle_since": "bad"},
    {"identity": IDENTITY, "idle_since": NOW + 100},
    {"identity": IDENTITY, "idle_since": float("nan")},
    {"identity": IDENTITY, "idle_since": NOW - 1000, "attempt_at": "bad"}])
def test_corrupt_or_future_state_restarts_observation_window(previous):
    assert k.wake_due(observation(), previous, NOW) == (
        False, {"identity": IDENTITY, "idle_since": NOW})


def test_fresh_heartbeat_defers_but_missing_heartbeat_can_wake():
    previous = {"identity": IDENTITY, "idle_since": NOW - 900}
    assert not k.wake_due(observation(heartbeat_age_seconds=30), previous, NOW)[0]
    assert k.wake_due(observation(heartbeat_age_seconds=None), previous, NOW)[0]


@pytest.mark.parametrize("field,value", [
    ("nonce_present", False), ("pending_present", True),
    ("handoff_pending_count", 1), ("session_id", OTHER + "\n"),
    ("state", "released"), ("session_id", {}),
])
def test_unsettled_claim_cannot_authorize_wake(field, value):
    data = status()
    data["incarnation"][field] = value
    assert k._wake_identity(data) is None


@pytest.mark.parametrize("over", [
    {"handshake": {"incarnation_id": "successor"}}, {"abort_flag": True},
    {"pending_decision": {"question": "Approve?", "answer": None}},
    {"goals_active": False}, {"incarnation": []},
])
def test_handoff_decision_or_unreadable_claim_prevents_wake(over):
    assert k._wake_identity(status(**over)) is None


class WakeRunner(Runner):
    def __init__(self, data=None, rows=None):
        super().__init__()
        self.data = status() if data is None else data
        self.rows = ([{"sessionId": SID, "id": "1234abcd", "status": "idle",
                       "kind": "background", "state": "working", "pid": 123}]
                     if rows is None else rows)

    def __call__(self, argv, **kw):
        import subprocess
        if "sup-status" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.data), "")
        if argv[:2] == ["claude", "agents"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.rows), "")
        return super().__call__(argv, **kw)


def test_revalidation_selects_exact_current_sid_not_name_or_retired_sid(tmp_path):
    runner = WakeRunner()
    assert k._wake_target(tmp_path, IDENTITY, runner) == TARGET
    runner.rows[0]["sessionId"] = OTHER
    assert k._wake_target(tmp_path, IDENTITY, runner) is None


@pytest.mark.parametrize("field,value", [("kind", "interactive"), ("state", "done"),
    ("pid", None), ("pid", True), ("status", "busy"), ("id", "--option"), ("id", None)])
def test_revalidation_rejects_non_running_or_malformed_target(tmp_path, field, value):
    runner = WakeRunner()
    runner.rows[0][field] = value
    assert k._wake_target(tmp_path, IDENTITY, runner) is None


def test_revalidation_rejects_changed_claim_and_busy_retired_session(tmp_path):
    runner = WakeRunner()
    runner.data["incarnation"]["incarnation_id"] = "changed"
    assert k._wake_target(tmp_path, IDENTITY, runner) is None
    runner.data = status()
    runner.rows.append({"sessionId": OTHER, "status": "busy"})
    assert k._wake_target(tmp_path, IDENTITY, runner) is None


@pytest.fixture
def real_daemon(tmp_path):
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix daemon transport")
    path = tmp_path / "control.sock"
    key = tmp_path / "control.key"
    key.write_text("test-auth-never-log\n")
    threads = []
    servers = []

    def start(reply):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(path))
        except PermissionError:
            server.close()
            pytest.skip("sandbox denies AF_UNIX bind (EPERM); live wire unmeasured")
        server.listen(1)
        server.settimeout(3)
        servers.append(server)
        received = []
        def serve():
            for response in ((json.dumps(LIST) + "\n").encode(), reply):
                with server.accept()[0] as conn:
                    conn.settimeout(3)
                    raw = b""
                    while b"\n" not in raw:
                        raw += conn.recv(4096)
                    received.append(json.loads(raw))
                    conn.sendall(response)
        thread = threading.Thread(target=serve)
        thread.start()
        threads.append(thread)
        return path, key, received
    yield start
    for thread in threads:
        thread.join(4)
        assert not thread.is_alive()
    for server in servers:
        server.close()


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    key = tmp_path / "control.key"
    key.write_text("test-auth-never-log\n")
    def start(reply):
        received = []
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def settimeout(self, value):
                assert 0 < value <= k.WAKE_TIMEOUT_SECONDS
            def connect(self, path):
                assert path == str(tmp_path / "control.sock")
            def sendall(self, raw):
                assert raw.endswith(b"\n") and raw.count(b"\n") == 1
                received.append(json.loads(raw))
                self.response = ((json.dumps(LIST) + "\n").encode()
                                 if received[-1]["op"] == "list" else reply)
            def recv(self, size):
                result, self.response = self.response[:min(size, 7)], self.response[min(size, 7):]
                return result
        monkeypatch.setattr(k.socket, "socket", lambda *a: Connection())
        return tmp_path / "control.sock", key, received
    return start


def test_real_unix_wire_when_host_permits_it(real_daemon):
    path, key, received = real_daemon(b'{"ok":true,"op":"reply"}\n')
    assert k.wake_existing(path, key, TARGET) == "accepted"
    assert [r["op"] for r in received] == ["list", "reply"]


@pytest.mark.parametrize("reply,expected", [
    (b'{"ok":true,"op":"reply"}\n', "accepted"),
    (b'{"ok":false,"code":"ENOJOB"}\n', "refused"),
    (b'{"ok":false,"code":"ERESPAWNING"}\n', "refused"),
    (b'{"ok":false,"code":"ENOREPLY"}\n', "refused"),
    (b'{"ok":false,"code":"EPROTO"}\n', "refused"),
    (b'{"ok":true,"op":"spawn"}\n', "refused"),
    (b'{"ok":true}', "transport-unavailable"),
    (b'[]\n', "transport-unavailable"),
    (b'bad json\n', "transport-unavailable"),
    (b'x' * k.WAKE_REPLY_LIMIT, "transport-unavailable"),
])
def test_socket_framing_and_no_dispatch_fallback(daemon, reply, expected):
    path, key, received = daemon(reply)
    assert k.wake_existing(path, key, TARGET) == expected
    assert len(received) == 2
    assert received[0] == {"proto": 1, "op": "list"}
    request = received[1]
    assert request.keys() == {"proto", "op", "short", "text", "auth"}
    assert request["proto"] == 1 and request["op"] == "reply"
    assert request["short"] == "1234abcd" and request["auth"] == "test-auth-never-log"
    assert "verify this session still holds" in request["text"]


def test_missing_daemon_is_not_started_and_invalid_target_not_contacted(tmp_path):
    key = tmp_path / "key"
    key.write_text("test-key")
    assert k.wake_existing(tmp_path / "absent", key, TARGET) == "transport-unavailable"
    assert k.wake_existing(tmp_path / "absent", key, "bad") == "invalid-target"


def setup_main(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    obs = observation()
    monkeypatch.setattr(k, "collect", lambda *a, **kw: obs)
    args = ["--once", "--fleet-home", str(tmp_path), "--wake-socket", "/unused/socket",
            "--wake-key", "/unused/key"]
    path = tmp_path / "state/keeper/last-page.json"
    return obs, args, path


def test_main_wake_refusal_survives_and_c_still_pages(tmp_path, monkeypatch):
    obs, args, path = setup_main(tmp_path, monkeypatch)
    calls = []
    def refused(*args):
        # Intent is durable BEFORE the transport, and never claims progress.
        assert json.loads(path.read_text())[k.WAKE_STATE_KEY]["result"] == "attempting"
        calls.append(args)
        return "refused"
    runner = WakeRunner()
    for delta in (0, 900, 901, 1800):
        assert k.main(args, run=runner, now_fn=lambda: NOW + delta,
                      out=io.StringIO(), wake_fn=refused) == 0
    assert len(calls) == 2
    state = json.loads(path.read_text())
    assert state[k.WAKE_STATE_KEY]["result"] == "refused"
    assert "supervisor-stalled" in state
    assert k.rule_supervisor_stalled(obs, NOW) is not None
    obs["heartbeat_age_seconds"] = 10
    assert k.rule_supervisor_stalled(obs, NOW) is None


def test_wake_operates_even_when_interface_registration_is_broken(tmp_path, monkeypatch):
    obs, args, path = setup_main(tmp_path, monkeypatch)
    k.save_state(path, {k.WAKE_STATE_KEY: {"identity": IDENTITY, "idle_since": NOW - 900}})
    (tmp_path / "state/interface-pane").write_text("broken")
    calls = []
    assert k.main(args, run=WakeRunner(), now_fn=lambda: NOW, out=io.StringIO(),
                  wake_fn=lambda *a: calls.append(a) or "accepted") == 0
    assert len(calls) == 1
    assert json.loads(path.read_text())[k.WAKE_STATE_KEY]["result"] == "accepted"


def test_dry_run_and_default_do_not_contact_daemon(tmp_path, monkeypatch):
    obs, args, path = setup_main(tmp_path, monkeypatch)
    k.save_state(path, {k.WAKE_STATE_KEY: {"identity": IDENTITY, "idle_since": NOW - 900}})
    before = path.read_bytes()
    def forbidden(*a):
        pytest.fail("daemon contacted")
    output = io.StringIO()
    k.main(args + ["--dry-run"], run=WakeRunner(), now_fn=lambda: NOW,
           out=output, wake_fn=forbidden)
    assert path.read_bytes() == before
    assert "supervisor wake due" in output.getvalue()
    k.main(args[:3], run=WakeRunner(), now_fn=lambda: NOW, out=io.StringIO(), wake_fn=forbidden)
    assert k.WAKE_STATE_KEY not in json.loads(path.read_text())


@pytest.mark.parametrize("flag", ["--wake-socket", "--wake-key"])
def test_opt_in_requires_both_paths(flag):
    with pytest.raises(SystemExit) as exc:
        k.main(["--once", flag, "/unused"], out=io.StringIO())
    assert exc.value.code == 2


@pytest.mark.parametrize("change", [{"sessionId": OTHER}, {"pid": 999},
                                    {"outcome": "done"}, {"dying": True}])
def test_wrong_daemon_or_retiring_target_never_gets_reply(tmp_path, monkeypatch, change):
    calls = []
    def request(path, payload, limit):
        calls.append(payload)
        return {"ok": True, "op": "list", "jobs": [{**JOB, **change}]}
    monkeypatch.setattr(k, "_daemon_request", request)
    assert k.wake_existing("unused", "unused", TARGET) == "target-changed-or-unavailable"
    assert calls == [{"proto": 1, "op": "list"}]


def test_claim_released_during_roster_probe_is_not_woken(tmp_path):
    runner = WakeRunner()
    def changing(argv, **kw):
        result = runner(argv, **kw)
        if argv[:2] == ["claude", "agents"]:
            runner.data["incarnation"]["state"] = "released"
        return result
    assert k._wake_target(tmp_path, IDENTITY, changing) is None


def test_accepted_wake_does_not_claim_model_progress(tmp_path, monkeypatch):
    obs, args, path = setup_main(tmp_path, monkeypatch)
    k.save_state(path, {k.WAKE_STATE_KEY: {"identity": IDENTITY, "idle_since": NOW - 900}})
    k.main(args, run=WakeRunner(), now_fn=lambda: NOW, out=io.StringIO(),
           wake_fn=lambda *a: "accepted")
    result = json.loads(path.read_text())
    assert result[k.WAKE_STATE_KEY]["result"] == "accepted"
    assert "supervisor-stalled" in result


def test_oversized_key_is_not_read_or_delivered(tmp_path, monkeypatch):
    key = tmp_path / "key"
    key.write_text("x" * 4097)
    calls = []
    def request(path, payload, limit):
        calls.append(payload)
        return LIST
    monkeypatch.setattr(k, "_daemon_request", request)
    assert k.wake_existing("unused", key, TARGET) == "invalid-key"
    assert calls == [{"proto": 1, "op": "list"}]


def test_timeout_is_throttled_and_does_not_expose_auth(tmp_path, monkeypatch):
    obs, args, path = setup_main(tmp_path, monkeypatch)
    k.save_state(path, {k.WAKE_STATE_KEY: {"identity": IDENTITY, "idle_since": NOW - 900}})
    calls = []
    def request(*a):
        calls.append(a)
        raise TimeoutError("secret must not appear")
    monkeypatch.setattr(k, "_daemon_request", request)
    output = io.StringIO()
    for delta in (0, 1):
        k.main(args, run=WakeRunner(), now_fn=lambda: NOW + delta,
               out=output, wake_fn=k.wake_existing)
    assert len(calls) == 1
    assert "secret" not in output.getvalue()
    assert json.loads(path.read_text())[k.WAKE_STATE_KEY]["result"] == "transport-unavailable"


def test_real_collect_to_main_wakes_existing_claim_holder(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    runner = WakeRunner()
    snapshot = {"ok": True, "workers": [], "supervisor": {
        "state": "held", "goals_active": True, "incarnation_id": IDENTITY[0]}}
    calls = []
    args = ["--once", "--fleet-home", str(tmp_path), "--wake-socket", "/unused/socket",
            "--wake-key", "/unused/key"]
    for delta in (0, 900):
        k.main(args, run=runner, snapshot_fn=lambda: snapshot,
               now_fn=lambda: NOW + delta, out=io.StringIO(),
               wake_fn=lambda *a: calls.append(a) or "accepted")
    assert calls == [(k.Path("/unused/socket"), k.Path("/unused/key"), TARGET)]
    assert k.load_state(tmp_path / "state/keeper/last-page.json")[k.WAKE_STATE_KEY]["result"] == "accepted"


def test_collect_does_not_authorize_two_different_claim_snapshots(tmp_path):
    snapshot = {"ok": True, "workers": [], "supervisor": {
        "state": "held", "goals_active": True, "incarnation_id": "different"}}
    obs = k.collect(tmp_path, now=NOW, run=WakeRunner(),
                    snapshot_fn=lambda: snapshot, out=io.StringIO())
    assert obs["wake_identity"] is None
    assert k.wake_due(obs, None, NOW) == (False, None)
