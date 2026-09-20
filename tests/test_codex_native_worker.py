from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"


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


@pytest.mark.parametrize("invoke", [
    lambda rec: fleet._cmd_peek_codex("cx-native", rec, 20),
    lambda rec: fleet._cmd_result_codex("cx-native", rec),
    lambda rec: fleet._cmd_send_codex("cx-native", "later work"),
    lambda rec: fleet._cmd_interrupt_codex("cx-native", rec),
    lambda rec: fleet._cmd_respawn_codex(
        SimpleNamespace(name="cx-native", task=None, force=False), rec),
    lambda rec: fleet._cmd_kill_codex("cx-native", rec),
])
def test_unimplemented_native_verbs_never_fall_through_to_mcx(
        native_home, monkeypatch, invoke):
    _home, lane = native_home
    rec = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "cwd": str(lane),
        "codex_thread_id": THREAD_ID, "codex_turn_id": TURN_ID,
        "adapter_state": "active", "status": "working",
        "model": "codex:gpt-5.6-luna",
    }
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["cx-native"] = rec
        fleet.save_registry(data)
    monkeypatch.setattr(
        fleet, "_mcx_run",
        lambda *_args, **_kwargs: pytest.fail("native row reached mcx run"))
    monkeypatch.setattr(
        fleet, "_mcx_probe",
        lambda *_args, **_kwargs: pytest.fail("native row reached mcx probe"))

    with pytest.raises(fleet.FleetCliError, match="not yet supported"):
        invoke(rec)

    assert fleet.load_registry()["workers"]["cx-native"] == rec


def test_resume_limited_refuses_native_row_before_mutation_or_dispatch(
        native_home, monkeypatch):
    _home, lane = native_home
    rec = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None, "cwd": str(lane),
        "codex_thread_id": THREAD_ID, "adapter_state": "active",
        "status": "limited", "last_activity": "2026-09-20T00:00:00Z",
    }
    with fleet.fleet_lock():
        data = fleet.load_registry()
        data["workers"]["cx-native"] = rec
        fleet.save_registry(data)
    monkeypatch.setattr(
        fleet, "_resume_one_limited_native",
        lambda *_args, **_kwargs: pytest.fail("native row reached Claude dispatch"))

    with pytest.raises(fleet.FleetCliError, match="not yet supported"):
        fleet._resume_one_limited("cx-native", lambda *_: None, lambda *_: None)

    assert fleet.load_registry()["workers"]["cx-native"] == rec


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
