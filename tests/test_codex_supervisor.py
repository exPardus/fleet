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
WAKE_TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106ba"
ITEM_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106bb"
NEWER_TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106bc"


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
    (tmp_path / "supervisor" / "briefs").mkdir()
    (tmp_path / "supervisor" / "briefs" / "wake.md").write_text(
        "Review queued work and continue the campaign.\n", encoding="utf-8")
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


class FakeLifecycleClient:
    generation = "host-generation-1"
    schema_digest = "schema-digest"

    def __init__(self, home, *, thread_status="active",
                 turn_status="inProgress", active_flags=None,
                 result_text="campaign complete", items_view="full",
                 newer_turn=None):
        self.home = Path(home).resolve()
        self.thread_status = thread_status
        self.turn_status = turn_status
        self.active_flags = list(active_flags or [])
        self.result_text = result_text
        self.items_view = items_view
        self.newer_turn = newer_turn
        self.turn_id = TURN_ID
        self.operations = []
        self.commits = []

    def call(self, operation, timeout):
        self.operations.append(operation)
        method = operation["payload"]["method"]
        if method == "thread/read":
            items = []
            if self.turn_status == "completed" and self.result_text is not None:
                items = [{"id": ITEM_ID, "type": "agentMessage",
                          "text": self.result_text}]
            turns = [{"id": self.turn_id,
                      "status": self.turn_status,
                      "itemsView": self.items_view,
                      "items": items}]
            if self.newer_turn is not None:
                turns.append(self.newer_turn)
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="c" * 64,
                result={"thread": {
                    "id": THREAD_ID, "cwd": str(self.home),
                    "status": {"type": self.thread_status,
                               "activeFlags": self.active_flags},
                    "turns": turns,
                }})
        if method == "turn/steer":
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="d" * 64,
                result={"turnId": self.turn_id})
        if method == "turn/start":
            self.turn_id = WAKE_TURN_ID
            self.thread_status = "active"
            self.turn_status = "inProgress"
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="e" * 64,
                result={"turn": {"id": self.turn_id,
                                 "status": "inProgress"}})
        raise AssertionError(f"unexpected method {method}")

    def commit(self, operation_id):
        self.commits.append(operation_id)


def _seed_native_supervisor(home, *, stale=False, cwd=None):
    incarnation_id = "inc-20260921T000000Z-abcd"
    name = f"sup|{incarnation_id}|boot"
    record = fleet.new_worker_record(
        None, Path(cwd or home).resolve(), "coordinate", "bypass",
        model="codex:gpt-5.6-luna", dispatch_kind="codex-app-server",
        substrate="codex")
    record.update({
        "adapter_state": "active", "codex_thread_id": THREAD_ID,
        "codex_turn_id": TURN_ID,
        "codex_host_generation": FakeLifecycleClient.generation,
        "codex_protocol_version": 2,
        "codex_schema_digest": FakeLifecycleClient.schema_digest,
        "supervisor_incarnation_id": incarnation_id,
        "provider_status": "active", "last_operation_id": "boot-turn",
    })
    data = fleet.load_registry()
    data["workers"] = {name: record}
    fleet.save_registry(data)
    heartbeat = "2000-01-01T00:00:00Z" if stale else fleet.now_iso()
    fleet.write_incarnation({
        "incarnation_id": incarnation_id, "lineage_id": "lin-native",
        "state": "held", "provider": "codex",
        "holder": {"provider": "codex", "thread_id": THREAD_ID},
        "current_turn_id": TURN_ID,
        "host_generation": FakeLifecycleClient.generation,
        "claimed_at": heartbeat, "heartbeat_at": heartbeat,
    })
    return name, incarnation_id


def _send_args(name="supervisor", message="new direction"):
    return SimpleNamespace(
        name=name, message=message, nonce=None, force_band=False)


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


def test_native_sup_status_projects_authenticated_provider_binding_without_probe(
        supervisor_home, monkeypatch, capsys):
    _seed_native_supervisor(supervisor_home)
    monkeypatch.setattr(
        fleet, "_codex_existing_client",
        lambda _home: pytest.fail("sup-status must remain a file-only view"))

    assert fleet.cmd_sup_status(SimpleNamespace(json=True)) == 0

    info = json.loads(capsys.readouterr().out)
    assert info["incarnation"]["holder"] == {
        "provider": "codex", "thread_id": THREAD_ID}
    assert info["body"]["provider"] == "codex"
    assert info["body"]["thread_id"] == THREAD_ID
    assert info["body"]["provider_status"] == "active"
    assert info["provider_binding"] == {
        "ok": True, "provider": "codex",
        "name": f"sup|inc-20260921T000000Z-abcd|boot",
        "thread_id": THREAD_ID, "turn_id": TURN_ID,
        "home": str(supervisor_home.resolve()),
    }


def test_native_guard_reads_public_active_thread_and_never_uses_claude_roster(
        supervisor_home, monkeypatch, capsys):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(
        SimpleNamespace(do=False, json=True),
        roster_fn=lambda: pytest.fail("native guard must not read Claude roster")) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"] == "OK"
    assert output["provider_status"] == "active"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_native_guard_wakes_stale_idle_thread_without_creating_second_body(
        supervisor_home, monkeypatch, capsys):
    name, _inc = _seed_native_supervisor(supervisor_home, stale=True)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0

    output = json.loads(capsys.readouterr().out)
    methods = [op["payload"]["method"] for op in client.operations]
    assert output["sent"] is True
    assert methods[-1] == "turn/start"
    assert "thread/start" not in methods and "thread/resume" not in methods
    claim = fleet.read_incarnation()
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == WAKE_TURN_ID
    assert "pending_operation" not in claim
    assert fleet.load_registry()["workers"][name]["codex_turn_id"] == WAKE_TURN_ID
    assert len(client.commits) == 1


def test_native_send_steers_only_the_claimed_active_turn(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_send(_send_args()) == 0

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/steer"]
    params = client.operations[-1]["payload"]["params"]
    assert params["threadId"] == THREAD_ID
    assert params["expectedTurnId"] == TURN_ID
    assert "pending_operation" not in fleet.read_incarnation()
    assert len(client.commits) == 1
    assert not (supervisor_home / "mailbox" / f"{THREAD_ID}.md").exists()


def test_stale_native_predecessor_cannot_wake_or_steer(
        supervisor_home, monkeypatch):
    name, _inc = _seed_native_supervisor(supervisor_home)
    claim = fleet.read_incarnation()
    claim.update({
        "incarnation_id": "inc-successor", "state": "held",
        "holder": {"provider": "codex", "thread_id": SUCCESSOR_THREAD_ID},
        "current_turn_id": WAKE_TURN_ID,
    })
    fleet.write_incarnation(claim)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="current claim"):
        fleet.cmd_send(_send_args(name=name))

    assert client.operations == []
    assert not (supervisor_home / "mailbox" / f"{THREAD_ID}.md").exists()


def test_ambiguous_native_recovery_queues_mail_without_resume_or_duplicate_turn(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home, stale=True)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="notLoaded", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="notLoaded"):
        fleet.cmd_send(_send_args(message="preserve me"))

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "preserve me"
    assert "pending_operation" not in fleet.read_incarnation()
    record = next(iter(fleet.load_registry()["workers"].values()))
    assert record["adapter_state"] == "active"
    assert record["last_operation_id"] == "boot-turn"


@pytest.mark.parametrize("items_view", ["notLoaded", "summary"])
def test_native_send_refuses_incomplete_items_and_preserves_queued_mail(
        supervisor_home, monkeypatch, items_view):
    _seed_native_supervisor(supervisor_home, stale=True)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        items_view=items_view)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="item history is incomplete"):
        fleet.cmd_send(_send_args(message="keep incomplete evidence"))

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]
    assert client.commits == []
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "keep incomplete evidence"
    assert fleet.read_incarnation()["current_turn_id"] == TURN_ID
    assert "pending_operation" not in fleet.read_incarnation()


@pytest.mark.parametrize("items_view", ["notLoaded", "summary"])
def test_native_guard_pages_on_incomplete_items_without_waking(
        supervisor_home, monkeypatch, capsys, items_view):
    _seed_native_supervisor(supervisor_home, stale=True)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        items_view=items_view)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"].startswith("PAGE ")
    assert "item history is incomplete" in output["reason"]
    assert output["sent"] is False
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_native_send_refuses_newer_turn_and_preserves_claim_and_mail(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home, stale=True)
    newer = {"id": NEWER_TURN_ID, "status": "completed",
             "itemsView": "full", "items": []}
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        newer_turn=newer)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="newer turn"):
        fleet.cmd_send(_send_args(message="keep stale turn mail"))

    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]
    assert client.commits == []
    assert fleet.read_incarnation()["current_turn_id"] == TURN_ID
    assert "pending_operation" not in fleet.read_incarnation()
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "keep stale turn mail"


def test_native_guard_pages_when_bound_turn_is_not_newest(
        supervisor_home, monkeypatch, capsys):
    _seed_native_supervisor(supervisor_home, stale=True)
    newer = {"id": NEWER_TURN_ID, "status": "completed",
             "itemsView": "full", "items": []}
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        newer_turn=newer)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"].startswith("PAGE ")
    assert "newer turn" in output["reason"]
    assert output["sent"] is False
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_pending_native_operation_pages_without_read_or_second_writer(
        supervisor_home, monkeypatch, capsys):
    _seed_native_supervisor(supervisor_home, stale=True)
    claim = fleet.read_incarnation()
    claim["pending_operation"] = {
        "operation_id": "unsettled", "kind": "turn/start",
        "previous_turn_id": TURN_ID,
    }
    fleet.write_incarnation(claim)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"].startswith("PAGE ")
    assert "operation pending" in output["reason"]
    assert output["sent"] is False
    assert client.operations == []


@pytest.mark.parametrize(
    "thread_status,turn_status,result_text,expected_rc,expected",
    [
        ("active", "inProgress", None, 1, "still running"),
        ("idle", "completed", "campaign complete", 0, "campaign complete"),
        ("idle", "failed", None, 1, "ended by failed"),
    ],
)
def test_native_result_distinguishes_active_completed_and_failed(
        supervisor_home, monkeypatch, capsys, thread_status, turn_status,
        result_text, expected_rc, expected):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(
        supervisor_home, thread_status=thread_status,
        turn_status=turn_status, result_text=result_text)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_result(SimpleNamespace(name="supervisor")) == expected_rc

    captured = capsys.readouterr()
    assert expected in captured.out + captured.err
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_wrong_home_native_binding_pages_without_provider_call(
        supervisor_home, tmp_path, monkeypatch, capsys):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    _seed_native_supervisor(supervisor_home, cwd=foreign)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["verdict"].startswith("PAGE ")
    assert "home" in output["reason"]
    assert output["sent"] is False
    assert client.operations == []


def test_sup_spawn_native_is_explicit_and_legacy_default_is_unchanged(
        supervisor_home):
    parser = fleet.build_parser()
    common = ["sup-spawn", "--task", "campaign",
              "--model", "codex:gpt-5.6-luna"]
    assert parser.parse_args(common).codex_adapter is None
    assert parser.parse_args(common + [
        "--codex-adapter", "native"]).codex_adapter == "native"
