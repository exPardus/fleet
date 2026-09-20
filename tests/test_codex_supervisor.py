from contextlib import contextmanager
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import fleet


THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7"
TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b8"
SUCCESSOR_THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106b9"


@pytest.fixture
def supervisor_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text(
        json.dumps({"hooks": {}}), encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    (tmp_path / "supervisor").mkdir()
    (tmp_path / "supervisor" / "GOALS.md").write_text(
        "# Goals\n\nBypass acknowledgement.\n", encoding="utf-8")
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    for executable in ("mcx", "claude"):
        stub = stub_bin / executable
        stub.write_text(
            f"#!/bin/sh\necho '{executable} must not run' >&2\nexit 97\n",
            encoding="utf-8")
        stub.chmod(0o700)
    monkeypatch.setenv("PATH", f"{stub_bin}{os.pathsep}{os.environ['PATH']}")
    return tmp_path


def _args(**updates):
    values = dict(
        task="coordinate the bounded campaign", model="codex:gpt-5.6-luna",
        permission_mode="bypass", nonce=None, force_band=False,
        setting_sources=None, codex_adapter="native",
    )
    values.update(updates)
    return SimpleNamespace(**values)


class FakeSupervisorClient:
    generation = "host-generation-1"
    schema_digest = "schema-digest"

    def __init__(self, home, *, mutate_after_thread=None):
        self.home = Path(home).resolve()
        self.operations = []
        self.commits = []
        self.mutate_after_thread = mutate_after_thread
        self.lock_depth = lambda: 0

    def call(self, operation, timeout):
        assert self.lock_depth() == 0
        self.operations.append(operation)
        method = operation["payload"]["method"]
        if method == "thread/start":
            if self.mutate_after_thread:
                self.mutate_after_thread()
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="a" * 64,
                result={
                    "thread": {"id": THREAD_ID, "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-5.6-luna",
                    "approvalPolicy": "never", "approvalsReviewer": "user",
                    "sandbox": {"type": "dangerFullAccess"},
                })
        if method == "turn/start":
            claim = fleet.read_incarnation()
            assert claim["state"] == "pending"
            assert claim["holder"] == {
                "provider": "codex", "thread_id": THREAD_ID}
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="b" * 64,
                result={"turn": {"id": TURN_ID, "status": "inProgress"}})
        raise AssertionError(f"unexpected method {method}")

    def commit(self, operation_id):
        assert self.lock_depth() == 0
        self.commits.append(operation_id)


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


def test_explicit_native_sup_spawn_binds_genuine_holder_and_boot_turn(
        supervisor_home, monkeypatch):
    depth = _track_lock(monkeypatch)
    client = FakeSupervisorClient(supervisor_home)
    client.lock_depth = depth
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_spawn(_args()) == 0

    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == TURN_ID
    assert "session_id" not in claim and "nonce_hash" not in claim
    workers = fleet.load_registry()["workers"]
    assert len(workers) == 1
    name, record = next(iter(workers.items()))
    assert name.startswith("sup|")
    assert record["dispatch_kind"] == "codex-app-server"
    assert record["session_id"] is None and record["mcx_id"] is None
    assert record["codex_thread_id"] == THREAD_ID
    assert record["codex_turn_id"] == TURN_ID
    assert record["adapter_state"] == "active"
    assert [item["payload"]["method"] for item in client.operations] == [
        "thread/start", "turn/start"]
    assert client.commits == [item["operation_id"] for item in client.operations]


def test_changed_claim_after_thread_creation_never_starts_boot_turn(
        supervisor_home, monkeypatch):
    def handoff():
        with fleet.fleet_lock():
            claim = fleet.read_incarnation()
            claim.update({
                "state": "held",
                "holder": {"provider": "codex",
                           "thread_id": SUCCESSOR_THREAD_ID},
                "incarnation_id": "inc-successor",
            })
            fleet.write_incarnation(claim)

    client = FakeSupervisorClient(supervisor_home, mutate_after_thread=handoff)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_spawn(_args()) == 1
    assert [item["payload"]["method"] for item in client.operations] == [
        "thread/start"]
    assert fleet.read_incarnation()["holder"]["thread_id"] == SUCCESSOR_THREAD_ID


def test_thread_journal_failure_freezes_bound_claim_without_booting(
        supervisor_home, monkeypatch):
    client = FakeSupervisorClient(supervisor_home)

    def fail_commit(_operation_id):
        raise OSError("durability unavailable")

    client.commit = fail_commit
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="journal commit failed"):
        fleet.cmd_sup_spawn(_args())

    claim = fleet.read_incarnation()
    assert claim["state"] == "uncertain"
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    record = next(iter(fleet.load_registry()["workers"].values()))
    assert record["adapter_state"] == "uncertain"
    assert [item["payload"]["method"] for item in client.operations] == [
        "thread/start"]


def test_stale_predecessor_cannot_authorize_mutation_after_handoff(
        supervisor_home):
    client = FakeSupervisorClient(supervisor_home)
    authority = fleet.ProviderIdentity("codex", THREAD_ID)
    fleet.write_incarnation({
        "state": "held", "incarnation_id": "inc-successor",
        "holder": {"provider": "codex", "thread_id": SUCCESSOR_THREAD_ID},
    })
    operation = {
        "operation_id": "stale-steer", "method": "rpc",
        "payload": {"method": "turn/steer", "params": {
            "threadId": THREAD_ID, "expectedTurnId": TURN_ID,
            "input": [{"type": "text", "text": "stale", "text_elements": []}],
        }},
    }

    with pytest.raises(fleet.FleetCliError, match="no longer holds"):
        fleet._call_codex_supervisor_claimed(
            client, "inc-predecessor", authority, operation, timeout=1)

    assert client.operations == []


def test_sup_spawn_native_is_explicit_and_legacy_default_is_unchanged():
    parser = fleet.build_parser()
    common = ["sup-spawn", "--task", "campaign",
              "--model", "codex:gpt-5.6-luna"]
    assert parser.parse_args(common).codex_adapter is None
    assert parser.parse_args(common + [
        "--codex-adapter", "native"]).codex_adapter == "native"
