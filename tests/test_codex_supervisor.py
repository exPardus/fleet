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
SUCCESSOR_TURN_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106bd"
SUCCESSOR_HANDOFF_THREAD_ID = "018f22d3-9b4a-7cc3-8a0e-36d4f59106be"


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
                 newer_turn=None, generation=None, fail_method=None,
                 reject_turn_start=False,
                 reject_successor_read_after_start=False,
                 interrupt_leaves_active=False):
        self.home = Path(home).resolve()
        self.generation = generation or type(self).generation
        self.thread_status = thread_status
        self.turn_status = turn_status
        self.active_flags = list(active_flags or [])
        self.result_text = result_text
        self.items_view = items_view
        self.newer_turn = newer_turn
        self.fail_method = fail_method
        self.reject_turn_start = reject_turn_start
        self.reject_successor_read_after_start = \
            reject_successor_read_after_start
        self.interrupt_leaves_active = interrupt_leaves_active
        self.predecessor_interrupted = False
        self.interrupt_calls = 0
        self.turn_id = TURN_ID
        self.successor_thread_id = SUCCESSOR_HANDOFF_THREAD_ID
        self.successor_initial_turns = []
        self.successor_after_turns = None
        self.successor_created = False
        self.successor_started = False
        self.operations = []
        self.commits = []
        self.handoff_commits = []

    def call(self, operation, timeout):
        self.operations.append(operation)
        method = operation["payload"]["method"]
        if method == self.fail_method:
            raise TimeoutError(f"lost {method} response")
        if method == "thread/read":
            requested_thread = operation["payload"]["params"]["threadId"]
            if requested_thread == self.successor_thread_id and self.successor_created:
                if (self.successor_started
                        and self.reject_successor_read_after_start):
                    from fleet_codex import HostRejected
                    raise HostRejected("successor verification rejected")
                turns = (self.successor_after_turns
                         if self.successor_started
                         and self.successor_after_turns is not None else
                         ([{"id": SUCCESSOR_TURN_ID, "status": "inProgress",
                            "itemsView": "full", "items": []}]
                          if self.successor_started else
                          list(self.successor_initial_turns)))
                return SimpleNamespace(
                    operation_id=operation["operation_id"],
                    generation=self.generation, payload_digest="2" * 64,
                    result={"thread": {
                        "id": self.successor_thread_id,
                        "cwd": str(self.home),
                        "status": {"type": ("active" if self.successor_started
                                              else "idle"),
                                   "activeFlags": []},
                        "turns": turns,
                    }})
            predecessor_after_handoff = (
                requested_thread == THREAD_ID and self.successor_created)
            observed_turn_id = (TURN_ID if predecessor_after_handoff
                                else self.turn_id)
            observed_turn_status = (
                "interrupted" if predecessor_after_handoff
                and self.predecessor_interrupted else self.turn_status)
            observed_thread_status = (
                "idle" if predecessor_after_handoff
                and self.predecessor_interrupted else self.thread_status)
            items = []
            if observed_turn_status == "completed" and self.result_text is not None:
                items = [{"id": ITEM_ID, "type": "agentMessage",
                          "text": self.result_text}]
            turns = [{"id": observed_turn_id,
                      "status": observed_turn_status,
                      "itemsView": self.items_view,
                      "items": items}]
            if self.newer_turn is not None:
                turns.append(self.newer_turn)
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="c" * 64,
                result={"thread": {
                    "id": THREAD_ID, "cwd": str(self.home),
                    "status": {"type": observed_thread_status,
                               "activeFlags": self.active_flags},
                    "turns": turns,
                }})
        if method == "thread/resume":
            resumed_thread = operation["payload"]["params"]["threadId"]
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="f" * 64,
                result={
                    "thread": {"id": resumed_thread, "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-5.6-luna",
                    "approvalPolicy": "never", "approvalsReviewer": "user",
                    "sandbox": {"type": "dangerFullAccess"},
                })
        if method == "thread/start":
            self.successor_created = True
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="1" * 64,
                result={
                    "thread": {"id": self.successor_thread_id,
                               "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-5.6-luna",
                    "approvalPolicy": "never", "approvalsReviewer": "user",
                    "sandbox": {"type": "dangerFullAccess"},
                })
        if method == "turn/steer":
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="d" * 64,
                result={"turnId": self.turn_id})
        if method == "turn/interrupt":
            params = operation["payload"]["params"]
            assert params == {"threadId": THREAD_ID, "turnId": TURN_ID}
            self.interrupt_calls += 1
            if not self.interrupt_leaves_active:
                self.predecessor_interrupted = True
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="9" * 64,
                result={})
        if method == "turn/start":
            if self.reject_turn_start:
                from fleet_codex import HostRejected
                raise HostRejected("successor turn rejected")
            target = operation["payload"]["params"]["threadId"]
            self.turn_id = (SUCCESSOR_TURN_ID
                            if target == self.successor_thread_id
                            else WAKE_TURN_ID)
            if target == self.successor_thread_id:
                self.successor_started = True
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

    def commit_handoff_turn_start(self, operation_id, **evidence):
        self.handoff_commits.append((operation_id, evidence))


class JournalLifecycleClient(FakeLifecycleClient):
    """Lifecycle fake with the production OperationJournal mutation gate."""

    def __init__(self, home, **kwargs):
        super().__init__(home, **kwargs)
        from fleet_codex import OperationJournal
        self.journal = OperationJournal(self.home, self.generation)

    def call(self, operation, timeout):
        from fleet_codex import HostRejected
        method = operation["payload"]["method"]
        if method not in {
                "thread/start", "thread/resume", "turn/start", "turn/steer",
                "turn/interrupt"}:
            return super().call(operation, timeout)
        operation_id = operation["operation_id"]
        record = self.journal.prepare(operation)
        state = record["state"]
        if state in {"observed", "committed"}:
            return SimpleNamespace(
                operation_id=operation_id, generation=self.generation,
                payload_digest=record["payload_digest"],
                result=record["result"])
        if state != "prepared":
            raise HostRejected("operation acceptance is uncertain")
        predecessor = self.journal.unresolved_predecessor(operation_id)
        if predecessor is not None:
            self.journal.fail(operation_id, "blocked by unresolved predecessor")
            raise HostRejected(
                f"unresolved predecessor operation {predecessor['operation_id']}")
        self.journal.accept(operation_id)
        try:
            observation = super().call(operation, timeout)
        except BaseException as exc:
            self.journal.uncertain(operation_id, str(exc))
            raise
        self.journal.observe(operation_id, observation.result)
        return observation

    def commit(self, operation_id):
        self.journal.commit(operation_id)
        super().commit(operation_id)

    def commit_handoff_turn_start(self, operation_id, **evidence):
        self.journal.commit_handoff_turn_start(operation_id, **evidence)
        super().commit_handoff_turn_start(operation_id, **evidence)


class EvidenceLifecycleClient(FakeLifecycleClient):
    def __init__(self, home, *, usage=None, error_code=None,
                 durable_result=True, include_result_truncated=True, **kwargs):
        super().__init__(home, **kwargs)
        self.usage = usage
        self.error_code = error_code
        self.durable_result = durable_result
        self.include_result_truncated = include_result_truncated

    def call(self, operation, timeout):
        if operation.get("method") == "public-evidence/read":
            self.operations.append(operation)
            payload = operation["payload"]
            assert payload == {"thread_id": THREAD_ID, "turn_id": TURN_ID}
            evidence = {
                "schema": 1, "thread_id": THREAD_ID, "turn_id": TURN_ID,
                "turn_status": self.turn_status,
            }
            if self.usage is not None:
                evidence["usage"] = dict(self.usage)
            if self.result_text is not None and self.durable_result:
                evidence.update({
                    "result_text": self.result_text,
                    "result_item_id": ITEM_ID,
                })
                if self.include_result_truncated:
                    evidence["result_truncated"] = False
            if self.error_code is not None:
                evidence["error_code"] = self.error_code
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="8" * 64,
                result=evidence)
        return super().call(operation, timeout)


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
    usage = ({"input_tokens": 11, "output_tokens": 7,
              "cached_input_tokens": 3, "reasoning_output_tokens": 2,
              "cache_write_input_tokens": 0, "total_tokens": 18}
             if turn_status == "completed" else None)
    client = EvidenceLifecycleClient(
        supervisor_home, thread_status=thread_status,
        turn_status=turn_status, result_text=result_text, usage=usage)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_result(SimpleNamespace(name="supervisor")) == expected_rc

    captured = capsys.readouterr()
    assert expected in captured.out + captured.err
    assert [(op.get("method"), op["payload"].get("method"))
            for op in client.operations] == (
        [("rpc", "thread/read"), ("public-evidence/read", None)]
        if turn_status != "inProgress" else [("rpc", "thread/read")])


def test_native_completed_result_persists_public_usage_and_result(
        supervisor_home, monkeypatch, capsys):
    name, _ = _seed_native_supervisor(supervisor_home)
    usage = {
        "input_tokens": 101, "output_tokens": 23,
        "cached_input_tokens": 17, "reasoning_output_tokens": 5,
        "cache_write_input_tokens": 0, "total_tokens": 124,
    }
    client = EvidenceLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        result_text="campaign complete", usage=usage)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_result(SimpleNamespace(name="supervisor")) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "campaign complete"
    assert "tokens in=101 out=23" in captured.err
    record = fleet.load_registry()["workers"][name]
    assert record["status"] == "idle"
    assert record["adapter_state"] == "idle"
    assert record["usage"] == usage
    assert record["result_text"] == "campaign complete"
    assert record["result_item_id"] == ITEM_ID
    assert record["result_turn_id"] == TURN_ID


@pytest.mark.parametrize(
    "client_options",
    [
        {"durable_result": False},
        {"include_result_truncated": False},
    ],
    ids=["no-durable-item", "missing-truncation-marker"],
)
def test_native_completed_result_requires_complete_durable_item_evidence(
        supervisor_home, monkeypatch, capsys, client_options):
    name, _ = _seed_native_supervisor(supervisor_home)
    usage = {
        "input_tokens": 101, "output_tokens": 23,
        "cached_input_tokens": 17, "reasoning_output_tokens": 5,
        "cache_write_input_tokens": 0, "total_tokens": 124,
    }
    client = EvidenceLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed",
        result_text="live-only result", usage=usage, **client_options)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_result(SimpleNamespace(name="supervisor")) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "durable item or usage evidence is incomplete" in captured.err
    record = fleet.load_registry()["workers"][name]
    assert record["status"] == "idle"
    assert record["usage"] == usage
    assert "result_text" not in record
    assert "result_item_id" not in record


@pytest.mark.parametrize(
    "thread_status,turn_status,error_code,expected_status,expected_adapter",
    [
        ("active", "inProgress", None, "working", "active"),
        ("idle", "failed", "usageLimitExceeded", "limited", "idle"),
        ("idle", "failed", "internalServerError", "dead", "idle"),
        ("idle", "interrupted", None, "interrupted", "idle"),
        ("notLoaded", "failed", None, "dead-suspected", "uncertain"),
        ("systemError", "failed", None, "dead-suspected", "uncertain"),
    ],
)
def test_native_result_persists_busy_idle_limit_and_dead_distinctions(
        supervisor_home, monkeypatch, thread_status, turn_status, error_code,
        expected_status, expected_adapter):
    name, _ = _seed_native_supervisor(supervisor_home)
    client = EvidenceLifecycleClient(
        supervisor_home, thread_status=thread_status, turn_status=turn_status,
        result_text=None, error_code=error_code)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_result(SimpleNamespace(name="supervisor")) == 1

    record = fleet.load_registry()["workers"][name]
    assert record["status"] == expected_status
    assert record["adapter_state"] == expected_adapter
    if error_code == "usageLimitExceeded":
        assert record["limit_kind"] == "usageLimitExceeded"


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


def test_native_checkpoint_commits_only_against_exact_observed_holder(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    before = fleet.read_incarnation()["heartbeat_at"]

    assert fleet.cmd_sup_checkpoint(SimpleNamespace(
        body="durable native checkpoint", kind="CHECKPOINT",
        sid=None, nonce=None,
        expect_inc="inc-20260921T000000Z-abcd")) == 0

    claim = fleet.read_incarnation()
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == TURN_ID
    assert claim["heartbeat_at"] >= before
    assert "durable native checkpoint" in fleet.supervisor_journal_path().read_text()
    assert [op["payload"]["method"] for op in client.operations] == ["thread/read"]


def test_native_release_is_durable_and_stale_holder_loses_mutation(
        supervisor_home, monkeypatch):
    name, incarnation_id = _seed_native_supervisor(supervisor_home)
    data = fleet.load_registry()
    data["workers"][name].update({
        "status": "limited", "limit_reset_at": "2099-01-01T00:00:00Z",
        "usage": {"input_tokens": 17}, "result_text": "keep result",
    })
    fleet.save_registry(data)
    old_binding = fleet._codex_supervisor_binding()
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_release(SimpleNamespace(
        reason="planned stop", sid=None, nonce=None,
        expect_inc=incarnation_id)) == 0

    claim = fleet.read_incarnation()
    assert claim["state"] == "releasing"
    assert claim["incarnation_id"] == incarnation_id
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    record = fleet.load_registry()["workers"][name]
    assert record["adapter_state"] == "releasing"
    assert record["status"] == "limited"
    assert record["limit_reset_at"] == "2099-01-01T00:00:00Z"
    assert record["usage"] == {"input_tokens": 17}
    assert record["result_text"] == "keep result"
    with pytest.raises(fleet.FleetCliError, match="no longer holds"):
        fleet._call_codex_supervisor_claimed(
            client, old_binding.incarnation_id, old_binding.authority,
            {"operation_id": "stale-after-release", "method": "rpc",
             "payload": {"method": "turn/steer", "params": {}}}, timeout=1)


def test_native_handoff_transfers_before_start_and_stales_predecessor(
        supervisor_home, monkeypatch):
    old_name, _old_inc = _seed_native_supervisor(supervisor_home)
    old_binding = fleet._codex_supervisor_binding()
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    assert fleet.cmd_sup_handoff_begin(SimpleNamespace(
        model="codex:gpt-5.6-luna", permission_mode="bypass",
        sid=None, nonce=None,
        expect_inc=old_binding.incarnation_id)) == 0

    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["holder"] == {
        "provider": "codex", "thread_id": SUCCESSOR_HANDOFF_THREAD_ID}
    assert claim["current_turn_id"] == SUCCESSOR_TURN_ID
    assert claim["predecessor"]["thread_id"] == THREAD_ID
    workers = fleet.load_registry()["workers"]
    successor = [r for n, r in workers.items() if n != old_name][0]
    assert successor["codex_thread_id"] == SUCCESSOR_HANDOFF_THREAD_ID
    assert successor["codex_turn_id"] == SUCCESSOR_TURN_ID
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start",
        "thread/read"]
    with pytest.raises(fleet.FleetCliError, match="no longer holds"):
        fleet._call_codex_supervisor_claimed(
            client, old_binding.incarnation_id, old_binding.authority,
            {"operation_id": "stale-handoff", "method": "rpc",
             "payload": {"method": "turn/steer", "params": {}}}, timeout=1)


def test_native_host_restart_reconciles_same_ids_without_new_body_or_turn(
        supervisor_home, monkeypatch):
    name, _inc = _seed_native_supervisor(supervisor_home)
    data = fleet.load_registry()
    data["workers"][name].update({
        "status": "limited", "limit_reset_at": "2099-01-01T00:00:00Z",
        "usage": {"input_tokens": 31}, "result_text": "preserve me",
    })
    fleet.save_registry(data)
    fleet.append_mailbox(THREAD_ID, "queued across restart")
    client = FakeLifecycleClient(supervisor_home, generation="host-generation-2")
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    claim = fleet.read_incarnation()
    record = fleet.load_registry()["workers"][name]
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == TURN_ID
    assert claim["host_generation"] == "host-generation-2"
    assert record["codex_host_generation"] == "host-generation-2"
    assert record["status"] == "limited"
    assert record["limit_reset_at"] == "2099-01-01T00:00:00Z"
    assert record["usage"] == {"input_tokens": 31}
    assert record["result_text"] == "preserve me"
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "queued across restart"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume", "thread/read"]


def test_native_restart_adopts_exact_activating_turn_without_replay(
        supervisor_home, monkeypatch):
    old_name, _inc = _seed_native_supervisor(supervisor_home)
    lost = FakeLifecycleClient(
        supervisor_home, reject_successor_read_after_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: lost)
    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))

    data = fleet.load_registry()
    workers = data["workers"]
    successor_name = [name for name in workers if name != old_name][0]
    workers[successor_name].update({
        "status": "limited", "limit_reset_at": "2099-01-01T00:00:00Z",
        "usage": {"input_tokens": 41}, "result_text": "retain adoption",
    })
    fleet.save_registry(data)
    fleet.append_mailbox(SUCCESSOR_HANDOFF_THREAD_ID, "queued on activation")

    restarted = FakeLifecycleClient(
        supervisor_home, generation="host-generation-2")
    restarted.successor_created = True
    restarted.successor_started = True
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: restarted)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    claim = fleet.read_incarnation()
    record = fleet.load_registry()["workers"][successor_name]
    assert claim["state"] == "held"
    assert claim["holder"] == {
        "provider": "codex", "thread_id": SUCCESSOR_HANDOFF_THREAD_ID}
    assert claim["current_turn_id"] == SUCCESSOR_TURN_ID
    assert claim["host_generation"] == "host-generation-2"
    assert record["codex_turn_id"] == SUCCESSOR_TURN_ID
    assert record["codex_host_generation"] == "host-generation-2"
    assert record["status"] == "limited"
    assert record["limit_reset_at"] == "2099-01-01T00:00:00Z"
    assert record["usage"] == {"input_tokens": 41}
    assert record["result_text"] == "retain adoption"
    assert (supervisor_home / "mailbox" /
            f"{SUCCESSOR_HANDOFF_THREAD_ID}.md").read_text(
                encoding="utf-8").strip() == "queued on activation"
    assert [op["payload"]["method"] for op in restarted.operations] == [
        "thread/read", "thread/resume", "thread/read"]
    assert restarted.handoff_commits[0][1]["turn_id"] == SUCCESSOR_TURN_ID
    assert all(op["payload"]["method"] not in {"thread/start", "turn/start"}
               for op in restarted.operations)

    restarted.predecessor_interrupted = True
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert restarted.interrupt_calls == 0
    assert all(op["payload"]["method"] not in {"thread/start", "turn/start"}
               for op in restarted.operations)


def test_native_restart_refuses_ambiguous_activating_history_without_replay(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    lost = FakeLifecycleClient(
        supervisor_home, reject_successor_read_after_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: lost)
    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))

    restarted = FakeLifecycleClient(
        supervisor_home, generation="host-generation-2")
    restarted.successor_created = True
    restarted.successor_started = True
    restarted.successor_after_turns = [
        {"id": SUCCESSOR_TURN_ID, "status": "inProgress",
         "itemsView": "full", "items": []},
        {"id": NEWER_TURN_ID, "status": "completed",
         "itemsView": "full", "items": []},
    ]
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: restarted)

    for _ in range(2):
        with pytest.raises(fleet.FleetCliError, match="restart is uncertain"):
            fleet.cmd_sup_reconcile(SimpleNamespace())

    claim = fleet.read_incarnation()
    assert claim["state"] == "activating"
    assert claim["pending_operation"]["kind"] == "handoff-turn/start"
    assert all(op["payload"]["method"] not in {"thread/start", "turn/start"}
               for op in restarted.operations)


def test_native_restart_commits_original_journal_before_new_generation_resume(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    original = JournalLifecycleClient(
        supervisor_home, reject_successor_read_after_start=True)
    monkeypatch.setattr(
        fleet, "_codex_existing_client", lambda _home: original)
    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))
    operation_id = fleet.read_incarnation()["pending_operation"]["operation_id"]
    assert original.journal.load(operation_id)["state"] == "observed"

    restarted = JournalLifecycleClient(
        supervisor_home, generation="host-generation-2")
    restarted.successor_created = True
    restarted.successor_started = True
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: restarted)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    assert restarted.journal.load(operation_id)["state"] == "committed"
    assert restarted.journal.unresolved_predecessor("later-operation") is None
    assert [op["payload"]["method"] for op in restarted.operations] == [
        "thread/read", "thread/resume", "thread/read"]


def test_native_same_generation_adoption_unblocks_one_predecessor_interrupt(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = JournalLifecycleClient(
        supervisor_home, reject_successor_read_after_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))
    operation_id = fleet.read_incarnation()["pending_operation"]["operation_id"]
    client.reject_successor_read_after_start = False
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert client.journal.load(operation_id)["state"] == "committed"

    client.operations.clear()
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert client.interrupt_calls == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/interrupt", "thread/read"]
    client.operations.clear()
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert client.interrupt_calls == 1


def test_native_reconcile_interrupts_and_retires_exact_handoff_predecessor(
        supervisor_home, monkeypatch):
    old_name, _inc = _seed_native_supervisor(supervisor_home)
    old_binding = fleet._codex_supervisor_binding()
    data = fleet.load_registry()
    data["workers"][old_name].update({
        "status": "limited", "limit_reset_at": "2099-01-01T00:00:00Z",
        "usage": {"input_tokens": 23}, "result_text": "retain predecessor",
    })
    fleet.save_registry(data)
    fleet.append_mailbox(THREAD_ID, "retain predecessor mail")
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    assert fleet.cmd_sup_handoff_begin(SimpleNamespace(
        model="codex:gpt-5.6-luna", permission_mode="bypass",
        sid=None, nonce=None,
        expect_inc=old_binding.incarnation_id)) == 0
    client.operations.clear()
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    claim = fleet.read_incarnation()
    predecessor = claim["predecessor"]
    old_record = fleet.load_registry()["workers"][old_name]
    assert predecessor["retirement_status"] == "interrupted"
    assert predecessor["retired_at"]
    assert old_record["adapter_state"] == "retired"
    assert old_record["status"] == "limited"
    assert old_record["limit_reset_at"] == "2099-01-01T00:00:00Z"
    assert old_record["usage"] == {"input_tokens": 23}
    assert old_record["result_text"] == "retain predecessor"
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "retain predecessor mail"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/interrupt", "thread/read"]
    assert client.interrupt_calls == 1
    with pytest.raises(fleet.FleetCliError, match="no longer holds"):
        fleet._call_codex_supervisor_claimed(
            client, old_binding.incarnation_id, old_binding.authority,
            {"operation_id": "retired-predecessor", "method": "rpc",
             "payload": {"method": "turn/steer", "params": {}}}, timeout=1)

    client.operations.clear()
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert client.interrupt_calls == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_native_predecessor_interrupt_ambiguity_never_replays(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(
        supervisor_home, interrupt_leaves_active=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    assert fleet.cmd_sup_handoff_begin(SimpleNamespace(
        model="codex:gpt-5.6-luna", permission_mode="bypass",
        sid=None, nonce=None,
        expect_inc="inc-20260921T000000Z-abcd")) == 0
    client.operations.clear()
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="retirement is uncertain"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert client.interrupt_calls == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "turn/interrupt", "thread/read"]

    client.operations.clear()
    with pytest.raises(fleet.FleetCliError, match="retirement is uncertain"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert client.interrupt_calls == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]

    client.predecessor_interrupted = True
    client.operations.clear()
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert client.interrupt_calls == 1
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_native_predecessor_retirement_refuses_newer_turn_without_interrupt(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    assert fleet.cmd_sup_handoff_begin(SimpleNamespace(
        model="codex:gpt-5.6-luna", permission_mode="bypass",
        sid=None, nonce=None,
        expect_inc="inc-20260921T000000Z-abcd")) == 0
    client.operations.clear()
    client.newer_turn = {
        "id": NEWER_TURN_ID, "status": "completed",
        "itemsView": "full", "items": [],
    }
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="retirement is uncertain"):
        fleet.cmd_sup_reconcile(SimpleNamespace())

    assert client.interrupt_calls == 0
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]
    assert fleet.read_incarnation()["state"] == "held"


def test_native_handoff_lost_activation_never_retries_or_restores_blindly(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home, fail_method="turn/start")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))

    assert fleet.read_incarnation()["state"] == "activating"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start"]
    with pytest.raises(fleet.FleetCliError, match="no current held claim"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None))
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start"]


def test_native_handoff_definitive_turn_rejection_restores_predecessor(
        supervisor_home, monkeypatch):
    old_name, _inc = _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home, reject_turn_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))

    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert list(fleet.load_registry()["workers"]) == [old_name]
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start"]


def test_native_handoff_post_acceptance_rejection_keeps_predecessor_disarmed(
        supervisor_home, monkeypatch):
    old_name, _inc = _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(
        supervisor_home, reject_successor_read_after_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))

    claim = fleet.read_incarnation()
    assert claim["state"] == "activating"
    assert claim["holder"] == {
        "provider": "codex", "thread_id": SUCCESSOR_HANDOFF_THREAD_ID}
    assert claim["predecessor"]["name"] == old_name
    workers = fleet.load_registry()["workers"]
    assert workers[old_name]["adapter_state"] == "retiring"
    successor = [row for name, row in workers.items() if name != old_name][0]
    assert successor["adapter_state"] == "uncertain"
    assert successor["codex_turn_id"] is None
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start",
        "thread/read"]

    with pytest.raises(fleet.FleetCliError, match="no current held claim"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start",
        "thread/read"]


@pytest.mark.parametrize("reuse", ["predecessor", "registered-row"])
def test_native_handoff_rejects_reused_successor_thread_before_transfer(
        supervisor_home, monkeypatch, reuse):
    old_name, _inc = _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    if reuse == "predecessor":
        client.successor_thread_id = THREAD_ID
    else:
        data = fleet.load_registry()
        row = fleet.new_worker_record(
            None, supervisor_home, "existing", "bypass",
            model="codex:gpt-5.6-luna", dispatch_kind="codex-app-server",
            substrate="codex")
        row.update({"codex_thread_id": SUCCESSOR_HANDOFF_THREAD_ID,
                    "codex_turn_id": NEWER_TURN_ID,
                    "codex_host_generation": client.generation})
        data["workers"]["existing-native-row"] = row
        fleet.save_registry(data)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="thread acceptance is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None))

    claim = fleet.read_incarnation()
    assert claim["state"] == "uncertain"
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert all(op["payload"]["method"] != "turn/start"
               for op in client.operations)
    assert old_name in fleet.load_registry()["workers"]


def test_native_handoff_rejects_nonempty_successor_before_claim_transfer(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    client.successor_initial_turns = [{
        "id": NEWER_TURN_ID, "status": "completed", "itemsView": "full",
        "items": [{"id": ITEM_ID, "type": "agentMessage", "text": "old"}],
    }]
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="thread acceptance is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None))

    assert fleet.read_incarnation()["state"] == "uncertain"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read"]
    assert len(fleet.load_registry()["workers"]) == 1


@pytest.mark.parametrize("after_turns", [
    [{"id": NEWER_TURN_ID, "status": "inProgress",
      "itemsView": "full", "items": []}],
    [{"id": SUCCESSOR_TURN_ID, "status": "inProgress",
      "itemsView": "full", "items": []},
     {"id": NEWER_TURN_ID, "status": "completed",
      "itemsView": "full", "items": []}],
])
def test_native_handoff_requires_exact_single_turn_proof_before_held(
        supervisor_home, monkeypatch, after_turns):
    _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    client.successor_after_turns = after_turns
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None))

    assert fleet.read_incarnation()["state"] == "activating"
    successor = [r for r in fleet.load_registry()["workers"].values()
                 if r.get("codex_thread_id") == SUCCESSOR_HANDOFF_THREAD_ID][0]
    assert successor["adapter_state"] == "uncertain"
    assert successor["codex_turn_id"] is None
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start",
        "thread/read"]
    with pytest.raises(fleet.FleetCliError, match="no current held claim"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd"))
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read", "thread/start", "thread/read", "turn/start",
        "thread/read"]


def test_native_restart_ambiguous_history_freezes_without_replay(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    fleet.append_mailbox(THREAD_ID, "retain ambiguous restart mail")
    newer = {"id": NEWER_TURN_ID, "status": "completed",
             "itemsView": "full", "items": []}
    client = FakeLifecycleClient(
        supervisor_home, generation="host-generation-2", newer_turn=newer)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="uncertain"):
        fleet.cmd_sup_reconcile(SimpleNamespace())

    assert fleet.read_incarnation()["state"] == "uncertain"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume", "thread/read"]
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "retain ambiguous restart mail"
    assert all(op["payload"]["method"] not in {"thread/start", "turn/start"}
               for op in client.operations)


def test_native_reconcile_finalizes_release_only_after_terminal_public_proof(
        supervisor_home, monkeypatch, capsys):
    name, _inc = _seed_native_supervisor(supervisor_home)
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    assert fleet.cmd_sup_release(SimpleNamespace(
        reason="done", sid=None, nonce=None,
        expect_inc="inc-20260921T000000Z-abcd")) == 0
    client.thread_status = "idle"
    client.turn_status = "completed"
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    claim = fleet.read_incarnation()
    assert claim["state"] == "released"
    assert claim["released_holder"] == {
        "provider": "codex", "thread_id": THREAD_ID,
        "turn_id": TURN_ID, "host_generation": client.generation}
    assert fleet.load_registry()["workers"][name]["adapter_state"] == "released"
    client.operations.clear()
    assert fleet.cmd_sup_guard(SimpleNamespace(do=True, json=True)) == 0
    output = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert output["verdict"] == "DISPATCH"
    assert output["sent"] is False
    assert client.operations == []
