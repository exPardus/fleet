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
                 resume_policy=None,
                 requirements=None,
                 reject_turn_start=False,
                 reject_successor_read_after_start=False,
                 interrupt_leaves_active=False):
        self.home = Path(home).resolve()
        self.generation = generation or type(self).generation
        self.host_pid = 111
        self.host_process_identity = "host-identity-111"
        self.app_server_pid = 222
        self.app_server_process_identity = "app-identity-222"
        self.host_live = True
        self.app_live = True
        self.metadata_stale = False
        self._launched_process = None
        self.thread_status = thread_status
        self.turn_status = turn_status
        self.active_flags = list(active_flags or [])
        self.result_text = result_text
        self.items_view = items_view
        self.newer_turn = newer_turn
        self.fail_method = fail_method
        self.resume_policy = resume_policy
        self.requirements = requirements
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
        self.paging_operations = []
        self.commits = []
        self.handoff_commits = []

    def config_requirements(self):
        return {"requirements": self.requirements}

    def _owner_live(self):
        return self.host_live

    def _app_server_live(self):
        return self.app_live

    def _metadata_stale(self):
        return self.metadata_stale

    def call(self, operation, timeout):
        method = operation["payload"]["method"]
        if method in {"thread/turns/list", "thread/items/list"}:
            self.paging_operations.append(operation)
            params = operation["payload"]["params"]
            turns = self._last_thread["turns"]
            if method == "thread/turns/list":
                data = list(reversed(turns))[:params["limit"]]
                result = {"data": data, "nextCursor": None}
            else:
                turn = next((turn for turn in turns
                             if turn["id"] == params["turnId"]), None)
                if turn is None or turn.get("itemsView") != "full":
                    from fleet_codex import HostRejected
                    raise HostRejected("item history is incomplete")
                result = {"data": [{"turnId": turn["id"], "item": item}
                                   for item in turn["items"]],
                          "nextCursor": None}
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="a" * 64,
                result=result)
        self.operations.append(operation)
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
                self._last_thread = {"turns": turns}
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
            self._last_thread = {"turns": turns}
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
            policy = self.resume_policy or {
                "approvalPolicy": "never", "approvalsReviewer": "user",
                "sandbox": {"type": "dangerFullAccess"},
            }
            return SimpleNamespace(
                operation_id=operation["operation_id"],
                generation=self.generation, payload_digest="f" * 64,
                result={
                    "thread": {"id": resumed_thread, "cwd": str(self.home)},
                    "cwd": str(self.home), "model": "gpt-5.6-luna",
                    **policy,
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
        if (predecessor is not None
                and not self.journal.permits_observed_resume_policy_restore(
                    operation_id, operation["payload"],
                    operation.get("recovery", {}))
                and not self.journal.permits_restored_supervisor_continuation(
                    operation_id, operation["payload"],
                    operation.get("recovery", {}))):
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


class PolicyRestoreLifecycleClient(JournalLifecycleClient):
    """Journal-backed public resume that applies explicit wire overrides."""

    def __init__(self, home, *, apply_override=True,
                 restored_active_profile=None, **kwargs):
        super().__init__(home, **kwargs)
        self.apply_override = apply_override
        self.restored_active_profile = restored_active_profile

    def call(self, operation, timeout):
        payload = operation.get("payload", {})
        params = payload.get("params", {})
        if (payload.get("method") == "thread/resume"
                and "sandbox" in params and self.apply_override):
            self.resume_policy = {
                "approvalPolicy": params["approvalPolicy"],
                "approvalsReviewer": params["approvalsReviewer"],
                "sandbox": {"type": "dangerFullAccess"},
            }
            if self.restored_active_profile is not None:
                self.resume_policy["activePermissionProfile"] = \
                    self.restored_active_profile
        return super().call(operation, timeout)


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


def _assert_unverified_queued_mail(home, body):
    queued = (home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip()
    assert queued.startswith("FLEET UNVERIFIED INTERFACE MAIL\n")
    assert queued.endswith("UNVERIFIED BODY\n" + body)


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

    assert fleet.cmd_sup_spawn(_args(codex_adapter=None)) == 0

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


@pytest.mark.parametrize("terminal_state", ["done", "stopped"])
def test_retired_legacy_claim_allows_normal_native_sup_spawn_with_active_lane(
        supervisor_home, monkeypatch, terminal_state):
    old_sid = "11111111-2222-4333-8444-555555555555"
    inc = "inc-20260101T000000Z-abcd"
    name = f"sup|{inc}|boot"
    claim = {"incarnation_id": inc, "session_id": old_sid,
             "lineage_id": "lin-20260101T000000Z-abcd", "claimed_via": "fresh",
             "claimed_at": "2026-01-01T00:00:00Z",
             "heartbeat_at": "2026-01-01T00:00:00Z"}
    fleet.write_incarnation(claim)
    old = fleet.new_worker_record(old_sid, supervisor_home, "old supervisor",
                                  "bypass", dispatch_kind="bg")
    active = fleet.new_worker_record(
        None, supervisor_home, "live lane", "accept",
        model="codex:gpt-5.6-luna", substrate="codex",
        dispatch_kind="codex-app-server")
    active.update({"status": "working", "codex_thread_id": SUCCESSOR_THREAD_ID})
    fleet.save_registry({"workers": {name: old, "live-lane": active}})
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "interface-test"})
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda: (True, [{"sessionId": old_sid,
                                         "name": name, "state": terminal_state}]))
    client = FakeSupervisorClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)
    assert fleet.cmd_sup_retire_legacy(SimpleNamespace(
        expect_inc=inc, expect_sid=old_sid, _fleet_home_explicit=True),
        roster_fn=lambda: (True, [{"sessionId": old_sid,
                                   "name": name, "state": terminal_state}])) == 0
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda: (True, [{"sessionId": old_sid,
                                         "name": name, "state": "working",
                                         "pid": 42}]))
    with pytest.raises(fleet.FleetCliError, match="liveness"):
        fleet.cmd_sup_spawn(_args())
    assert client.operations == []
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda: (True, [{"sessionId": old_sid,
                                         "name": name, "state": "stopped",
                                         "pid": False}]))
    with pytest.raises(fleet.FleetCliError, match="liveness"):
        fleet.cmd_sup_spawn(_args())
    assert client.operations == []
    for state in ("done", "stopped"):
        for status in ("idle", "working"):
            monkeypatch.setattr(fleet, "_fetch_agents_roster",
                                lambda state=state, status=status: (True, [{
                                    "sessionId": old_sid, "name": name,
                                    "state": state, "status": status}]))
            with pytest.raises(fleet.FleetCliError, match="liveness"):
                fleet.cmd_sup_spawn(_args())
            assert client.operations == []
    monkeypatch.setattr(fleet, "_fetch_agents_roster",
                        lambda: (True, [{"sessionId": old_sid,
                                         "name": name, "state": terminal_state}]))
    assert fleet.cmd_sup_spawn(_args()) == 0
    assert fleet.read_incarnation()["holder"] == {
        "provider": "codex", "thread_id": THREAD_ID}
    rows = fleet.read_registry_no_repair()["workers"]
    assert rows[name]["status"] == "dead"
    assert rows["live-lane"] == active
    assert len(client.operations) == 2


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


@pytest.mark.parametrize("verb", ["send", "checkpoint", "guard"])
def test_long_supervisor_history_uses_bounded_public_pages(
        supervisor_home, monkeypatch, capsys, verb):
    _seed_native_supervisor(supervisor_home)

    class LongHistoryClient(FakeLifecycleClient):
        def call(self, operation, timeout):
            if operation["payload"]["method"] == "thread/read":
                # A full-history app-server response would overflow host IPC.
                full_history = {"turns": [{"items": [{"text": "x" *
                                 (1024 * 1024 + 1)}]}]}
                assert len(json.dumps(full_history).encode()) > 1024 * 1024
                assert operation["payload"]["params"]["includeTurns"] is False
            return super().call(operation, timeout)

    client = LongHistoryClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    if verb == "send":
        assert fleet.cmd_send(_send_args()) == 0
    elif verb == "checkpoint":
        assert fleet.cmd_sup_checkpoint(SimpleNamespace(
            body="paged checkpoint", kind="CHECKPOINT", sid=None, nonce=None,
            expect_inc="inc-20260921T000000Z-abcd")) == 0
    else:
        assert fleet.cmd_sup_guard(SimpleNamespace(do=False, json=True)) == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "OK"
    methods = [op["payload"]["method"] for op in client.paging_operations]
    assert methods == ["thread/turns/list", "thread/items/list",
                       "thread/turns/list"]
    assert client.paging_operations[0]["payload"]["params"]["limit"] == 2
    assert client.paging_operations[1]["payload"]["params"]["limit"] == 16


def test_supervisor_item_page_shrinks_after_explicit_oversize(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)

    class OversizePageClient(FakeLifecycleClient):
        def call(self, operation, timeout):
            if (operation["payload"]["method"] == "thread/items/list"
                    and operation["payload"]["params"]["limit"] > 1):
                self.paging_operations.append(operation)
                from fleet_codex import HostRejected
                raise HostRejected(
                    "host response exceeds MAX_IPC_BYTES; page the request")
            return super().call(operation, timeout)

    client = OversizePageClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    assert fleet.cmd_sup_guard(SimpleNamespace(do=False, json=True)) == 0
    limits = [op["payload"]["params"]["limit"]
              for op in client.paging_operations
              if op["payload"]["method"] == "thread/items/list"]
    assert limits == [16, 8, 4, 2, 1]


def test_native_guard_reports_parked_idle_claim_without_wake(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    claim = fleet.read_incarnation()
    claim.update(parked_at=fleet.now_iso(),
                 parked_reason="waiting for the external batch",
                 parked_wake_condition="batch request arrives")
    fleet.write_incarnation(claim)
    client = FakeLifecycleClient(supervisor_home, thread_status="idle",
                                 turn_status="completed")
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    observed = fleet._codex_sup_guard_observe()

    assert observed["verdict"] == "PARKED"
    assert observed["parked_reason"] == "waiting for the external batch"
    assert observed["parked_active"] is True


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
    _assert_unverified_queued_mail(supervisor_home, "preserve me")
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
    _assert_unverified_queued_mail(
        supervisor_home, "keep incomplete evidence")
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
    _assert_unverified_queued_mail(supervisor_home, "keep stale turn mail")


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


def test_sup_spawn_codex_model_defaults_to_native(supervisor_home):
    parser = fleet.build_parser()
    common = ["sup-spawn", "--task", "campaign",
              "--model", "codex:gpt-5.6-luna"]
    # Omission is resolved after model policy so non-Codex supervisors retain
    # the Claude route while codex:<model> selects native in cmd_sup_spawn.
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


def test_native_handoff_uses_persisted_model_for_tier_policy(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    (supervisor_home / "supervisor" / "GOALS.md").write_text(
        "<!-- fleet-tier-policy\n"
        "forbid-default: true\n"
        "supervisor-tier-chain: top\n"
        "-->\n", encoding="utf-8")
    binding = fleet._codex_supervisor_binding()
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    # The persisted codex:gpt-5.6-luna model is explicit provider policy even
    # when handoff omits --model; the native path must not be rejected first.
    assert fleet.cmd_sup_handoff_begin(SimpleNamespace(
        model=None, permission_mode="bypass", sid=None, nonce=None,
        expect_inc=binding.incarnation_id)) == 0


def test_native_handoff_refuses_missing_predecessor_permission_mode(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    data = fleet.load_registry()
    record = next(iter(data["workers"].values()))
    record.pop("mode")
    fleet.save_registry(data)
    binding = fleet._codex_supervisor_binding()
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="permission mode is unresolved"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model=None, permission_mode=None, setting_sources=None,
            sid=None, nonce=None, expect_inc=binding.incarnation_id))
    assert [op["payload"]["method"] for op in client.operations] == ["thread/read"]


def test_native_handoff_refuses_missing_predecessor_setting_sources(
        supervisor_home, monkeypatch):
    _seed_native_supervisor(supervisor_home)
    data = fleet.load_registry()
    record = next(iter(data["workers"].values()))
    record.pop("setting_sources")
    fleet.save_registry(data)
    binding = fleet._codex_supervisor_binding()
    client = FakeLifecycleClient(supervisor_home)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="setting sources are unresolved"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model=None, permission_mode="bypass", setting_sources=None,
            sid=None, nonce=None, expect_inc=binding.incarnation_id))
    assert [op["payload"]["method"] for op in client.operations] == ["thread/read"]


def test_claude_handoff_refuses_unknown_predecessor_model_before_tier_default(
        supervisor_home):
    (supervisor_home / "supervisor" / "GOALS.md").write_text(
        "<!-- fleet-tier-policy\n"
        "forbid-default: true\n"
        "supervisor-tier-chain: top\n"
        "-->\n", encoding="utf-8")
    fleet.write_incarnation({
        "incarnation_id": "inc-claude", "state": "held",
        "provider": "claude", "session_id": "sid-claude",
    })
    data = fleet.load_registry()
    data["workers"]["sup|inc-claude|boot"] = fleet.new_worker_record(
        "sid-claude", supervisor_home, "campaign", "bypass", model=None,
        setting_sources=None, dispatch_kind="bg", category=None)
    fleet.save_registry(data)
    with pytest.raises(
            fleet.FleetCliError,
            match=r"predecessor launch settings are unresolved.*model \(pass --model\)"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model=None, permission_mode="bypass", sid=None, nonce=None))


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
    assert client.operations[0]["payload"]["params"]["excludeTurns"] is True


def test_native_restart_observed_narrower_policy_freezes_without_replay(
        supervisor_home, monkeypatch):
    name, incarnation_id = _seed_native_supervisor(supervisor_home)
    before = fleet.read_incarnation()
    fleet.append_mailbox(THREAD_ID, "preserve policy mismatch mail")
    client = JournalLifecycleClient(
        supervisor_home, generation="host-generation-2",
        thread_status="idle", turn_status="completed",
        resume_policy={
            "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": {
                "type": "workspaceWrite", "writableRoots": [],
                "networkAccess": False, "excludeSlashTmp": False,
                "excludeTmpdirEnvVar": False,
            },
        })
    monkeypatch.setattr(fleet, "_codex_native_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="restart reconciliation is uncertain"):
        fleet.cmd_sup_reconcile(SimpleNamespace())

    claim = fleet.read_incarnation()
    operation_id = claim["pending_operation"]["operation_id"]
    row = fleet.load_registry()["workers"][name]
    journal = client.journal.load(operation_id)
    assert claim["incarnation_id"] == incarnation_id
    assert claim["holder"] == before["holder"]
    assert claim["current_turn_id"] == before["current_turn_id"]
    assert claim["host_generation"] == before["host_generation"]
    assert claim["state"] == "uncertain"
    assert claim["pending_operation"]["kind"] == "thread/resume"
    assert "thread/resume effective sandbox mismatch" in claim["uncertainty"]
    assert row["adapter_state"] == "uncertain"
    assert row["codex_host_generation"] == before["host_generation"]
    assert journal["state"] == "observed"
    assert journal["public_method"] == "thread/resume"
    assert journal["result"]["sandbox"]["type"] == "workspaceWrite"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume"]
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "preserve policy mismatch mail"

    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    with pytest.raises(fleet.FleetCliError, match="thread/resume is unresolved"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/resume"]


def _seed_observed_workspace_resume(home):
    from fleet_codex import OperationJournal

    name, incarnation_id = _seed_native_supervisor(home)
    data = fleet.load_registry()
    data["workers"][name]["permission_effective"] = {
        "approvalPolicy": "never", "approvalsReviewer": "user",
        "sandbox": {"type": "dangerFullAccess"},
    }
    fleet.save_registry(data)
    binding = fleet._codex_supervisor_binding()
    old_operation_id = "supervisor-reconcile-observed-workspace"
    fleet._reserve_codex_supervisor_operation(
        binding, old_operation_id, "thread/resume", allowed_states={"held"})
    fleet._freeze_codex_supervisor_preclaim(
        name, incarnation_id, old_operation_id,
        "Codex thread/resume effective sandbox mismatch")
    journal = OperationJournal(home, "host-generation-2")
    operation = {
        "operation_id": old_operation_id, "method": "rpc",
        "payload": {"method": "thread/resume", "params": {
            "threadId": THREAD_ID, "excludeTurns": True}},
        "recovery": {
            "kind": "supervisor/thread-resume", "fleet_name": name,
            "incarnation_id": incarnation_id, "thread_id": THREAD_ID,
            "previous_host_generation": binding.host_generation,
            "canonical_cwd": str(home.resolve()),
        },
    }
    journal.prepare(operation)
    journal.accept(old_operation_id)
    journal.observe(old_operation_id, {
        "thread": {"id": THREAD_ID, "cwd": str(home.resolve())},
        "cwd": str(home.resolve()), "model": "gpt-5.6-luna",
        "approvalPolicy": "never", "approvalsReviewer": "user",
        "sandbox": {"type": "workspaceWrite", "writableRoots": [],
                    "networkAccess": False, "excludeSlashTmp": False,
                    "excludeTmpdirEnvVar": False},
        "activePermissionProfile": {"id": ":workspace", "extends": None},
        "runtimeWorkspaceRoots": [str(home.resolve())],
    })
    return name, incarnation_id, old_operation_id, journal


def _restore_args(incarnation_id, old_operation_id, **updates):
    values = {
        "restore_recorded_policy": True, "_fleet_home_explicit": True,
        "prepare_recorded_policy_restore": False,
        "expect_inc": incarnation_id, "expect_thread": THREAD_ID,
        "expect_turn": TURN_ID, "expect_resume_op": old_operation_id,
        "expect_new_generation": "host-generation-2",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _prepare_args(incarnation_id, old_operation_id, **updates):
    return _restore_args(
        incarnation_id, old_operation_id,
        restore_recorded_policy=False,
        prepare_recorded_policy_restore=True, **updates)


def _cold_restore_clients(home, monkeypatch, *, apply_override=True,
                          restore_policy=None, restored_active_profile=None):
    old = PolicyRestoreLifecycleClient(
        home, generation="host-generation-2",
        thread_status="idle", turn_status="completed")
    new = PolicyRestoreLifecycleClient(
        home, generation="host-generation-3",
        thread_status="idle", turn_status="completed",
        apply_override=apply_override, resume_policy=restore_policy,
        restored_active_profile=restored_active_profile)
    new._launched_process = object()
    current = {"client": old}
    monkeypatch.setattr(fleet, "_codex_existing_client",
                        lambda _home: current["client"])

    def ensure_new(_home):
        assert not old.host_live and not old.app_live and old.metadata_stale
        current["client"] = new
        return new

    monkeypatch.setattr(fleet, "_codex_native_client", ensure_new)
    return old, new, current


def _prove_then_stop_cold_host(incarnation_id, old_op, old):
    assert fleet.cmd_sup_reconcile(_prepare_args(incarnation_id, old_op)) == 0
    old.host_live = False
    old.app_live = False
    old.metadata_stale = True


def test_observed_resume_restores_recorded_policy_with_distinct_intent(
        supervisor_home, monkeypatch):
    name, incarnation_id, old_op, journal = _seed_observed_workspace_resume(
        supervisor_home)
    fleet.append_mailbox(THREAD_ID, "preserve exact mail")
    unrelated = {"status": "working", "adapter_state": "active",
                 "codex_thread_id": SUCCESSOR_THREAD_ID,
                 "codex_turn_id": NEWER_TURN_ID}
    data = fleet.load_registry()
    data["workers"]["unrelated-product-worker"] = dict(unrelated)
    fleet.save_registry(data)
    old_client, client, _current = _cold_restore_clients(
        supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    assert fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op)) == 0

    claim = fleet.read_incarnation()
    row = fleet.load_registry()["workers"][name]
    assert claim["state"] == "held"
    assert claim["incarnation_id"] == incarnation_id
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == TURN_ID
    assert claim["host_generation"] == "host-generation-3"
    assert row["mode"] == "bypass"
    assert row["permission_effective"]["sandbox"] == {
        "type": "dangerFullAccess"}
    assert fleet.load_registry()["workers"]["unrelated-product-worker"] == unrelated
    assert journal.load(old_op)["state"] == "observed"
    new_op = claim["last_operation_id"]
    assert new_op != old_op
    assert journal.load(new_op)["state"] == "committed"
    mutations = [op for op in client.operations
                 if op["payload"]["method"] == "thread/resume"]
    assert len(mutations) == 1
    assert mutations[0]["operation_id"] == new_op
    assert mutations[0]["payload"]["params"] == {
        "threadId": THREAD_ID, "excludeTurns": True,
        "cwd": str(supervisor_home.resolve()), "model": "gpt-5.6-luna",
        "approvalPolicy": "never", "approvalsReviewer": "user",
        "sandbox": "danger-full-access",
    }
    assert all(op["payload"]["method"] not in {"thread/start", "turn/start",
                                                 "turn/steer"}
               for op in client.operations)
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "preserve exact mail"


def test_linked_restoration_wakes_with_one_normal_mail_and_same_holder(
        supervisor_home, monkeypatch):
    from fleet_codex import OperationJournal

    name, incarnation_id, old_op, _ = _seed_observed_workspace_resume(
        supervisor_home)
    old_client, client, _current = _cold_restore_clients(
        supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    assert fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op)) == 0
    before = fleet.read_incarnation()
    assert fleet.load_registry()["workers"][name]["adapter_state"] == "active"
    assert fleet._cmd_send_codex_supervisor(name, "first normal mail") == 0
    after = fleet.read_incarnation()
    journal = OperationJournal(supervisor_home, client.generation)
    sends = [op for op in client.operations
             if op["payload"]["method"] == "turn/start"]
    assert len(sends) == 1
    assert sends[0]["recovery"]["restored_predecessor"] == \
        journal.restored_policy_link(
            fleet_name=name, incarnation_id=incarnation_id,
            thread_id=THREAD_ID)
    assert journal.load(sends[0]["operation_id"])["state"] == "committed"
    assert after["incarnation_id"] == before["incarnation_id"]
    assert after["holder"] == before["holder"]
    assert after["current_turn_id"] == WAKE_TURN_ID
    assert after["state"] == "held"
    assert not list((supervisor_home / "mailbox").glob(
        f"{THREAD_ID}.md.claimed.*"))


def _seed_restored_predecessor_rejected_send(home, monkeypatch):
    from fleet_codex import OperationJournal
    import fleet_codex

    name, incarnation_id, old_op, journal = _seed_observed_workspace_resume(home)
    old_client, client, _current = _cold_restore_clients(home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    assert fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op)) == 0
    binding = fleet._codex_supervisor_binding()
    operation_id = "supervisor-send-post-restore-rejected"
    fleet._reserve_codex_supervisor_operation(binding, operation_id,
                                              "observe-send")
    fleet.append_mailbox(THREAD_ID, "preserve this rejected normal mail")
    _queued, claimed = fleet.claim_mailbox(THREAD_ID)
    assert claimed is not None
    send_journal = OperationJournal(home, client.generation)
    send_journal.prepare({
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": "turn/start", "params": {
            "threadId": THREAD_ID, "input": [{"type": "text",
                                           "text": "preserve this rejected normal mail",
                                           "text_elements": []}]}},
        "recovery": {
            "kind": "supervisor/turn/start", "fleet_name": name,
            "incarnation_id": incarnation_id, "thread_id": THREAD_ID,
            "previous_turn_id": TURN_ID, "canonical_cwd": str(home.resolve()),
        },
    })
    send_journal.fail(operation_id,
                      "blocked by unresolved predecessor operation")
    fleet._freeze_codex_supervisor_preclaim(
        name, incarnation_id, operation_id,
        f"unresolved predecessor operation {old_op} blocks mutation")
    return name, old_op, journal, claimed, send_journal, operation_id, client


def test_restored_predecessor_failed_send_settles_without_mail_loss(
        supervisor_home, monkeypatch):
    name, old_op, old_journal, claimed, send_journal, operation_id, client = \
        _seed_restored_predecessor_rejected_send(supervisor_home, monkeypatch)
    claim = fleet.read_incarnation()
    # The deployed PR33 restoration left this field uncertain. It does not
    # change the committed restoration, current row, or failed-send journal.
    claim["pending_operation"]["previous_adapter_state"] = "uncertain"
    fleet.write_incarnation(claim)
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    settled = fleet.read_incarnation()
    row = fleet.load_registry()["workers"][name]
    assert settled["state"] == "held"
    assert "pending_operation" not in settled
    assert row["adapter_state"] == "active"
    assert row["status"] == "idle"
    assert claimed.exists() is False
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "preserve this rejected normal mail"
    assert send_journal.load(operation_id)["state"] == "failed"
    assert old_journal.load(old_op)["state"] == "observed"
    assert [op["payload"]["method"] for op in client.operations].count(
        "turn/start") == 0


@pytest.mark.parametrize("case", [
    "accepted", "digest", "new-inbox", "newer-turn", "source",
    "old-journal", "restore-journal", "wrong-turn",
])
def test_restored_failed_send_ambiguous_evidence_preserves_claim_and_mail(
        supervisor_home, monkeypatch, case):
    name, old_op, old_journal, claimed, send_journal, operation_id, client = \
        _seed_restored_predecessor_rejected_send(supervisor_home, monkeypatch)
    if case in {"accepted", "digest"}:
        record = send_journal.load(operation_id)
        if case == "accepted":
            record["state"] = "accepted"
            record["accepted_at"] = 1.0
        else:
            record["payload_digest"] = "0" * 64
        send_journal.path(operation_id).write_text(
            json.dumps(record), encoding="utf-8")
    elif case == "new-inbox":
        fleet.append_mailbox(THREAD_ID, "later queued mail")
    elif case == "newer-turn":
        client.newer_turn = {"id": NEWER_TURN_ID, "status": "completed",
                             "itemsView": "notLoaded", "items": []}
    elif case == "source":
        monkeypatch.setattr(
            fleet, "_registered_interface_mail_source",
            lambda: {"kind": "claude-session", "session_id": "wrong"})
    elif case == "old-journal":
        record = old_journal.load(old_op)
        record["result"]["model"] = "different-model"
        old_journal.path(old_op).write_text(
            json.dumps(record), encoding="utf-8")
    elif case == "restore-journal":
        claim = fleet.read_incarnation()
        restore_id = claim["pending_operation"]["previous_claim_operation_id"]
        record = send_journal.load(restore_id)
        record["state"] = "observed"
        send_journal.path(restore_id).write_text(
            json.dumps(record), encoding="utf-8")
    else:
        claim = fleet.read_incarnation()
        claim["pending_operation"]["previous_turn_id"] = NEWER_TURN_ID
        fleet.write_incarnation(claim)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert claimed.exists()
    assert fleet.load_registry()["workers"][name]["adapter_state"] == "uncertain"
    assert [op["payload"]["method"] for op in client.operations].count(
        "turn/start") == 0


def _restored_continuation_setup(home, monkeypatch):
    name, incarnation_id, old_op, old_journal = \
        _seed_observed_workspace_resume(home)
    old_client, client, current = _cold_restore_clients(home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    assert fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op)) == 0
    claim = fleet.read_incarnation()
    args = SimpleNamespace(
        _fleet_home_explicit=True, prepare_restored_continuation=True,
        reattach_restored_continuation=False,
        expect_inc=incarnation_id, expect_thread=THREAD_ID,
        expect_turn=TURN_ID, expect_resume_op=old_op,
        expect_restore_op=claim["last_operation_id"],
        expect_new_generation=client.generation)
    return name, old_op, old_journal, client, current, args


def test_restored_continuation_cold_reattaches_without_turn_or_policy_change(
        supervisor_home, monkeypatch):
    from fleet_codex import OperationJournal

    name, old_op, old_journal, old_client, current, args = \
        _restored_continuation_setup(supervisor_home, monkeypatch)
    with pytest.raises(fleet.FleetCliError, match="explicit policy-bound"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    fleet.append_mailbox(THREAD_ID, "mail held across cold boundary")
    assert fleet.cmd_sup_reconcile(args) == 0
    assert fleet.cmd_sup_reconcile(args) == 0  # refresh while same old host lives
    old_client.host_live = False
    old_client.app_live = False
    old_client.metadata_stale = True
    next_client = PolicyRestoreLifecycleClient(
        supervisor_home, generation="host-generation-4",
        thread_status="idle", turn_status="completed")
    next_client._launched_process = object()
    next_client.host_pid = 333
    next_client.app_server_pid = 444
    next_client.host_process_identity = "host-identity-333"
    next_client.app_server_process_identity = "app-identity-444"

    def ensure_new(_home):
        assert not old_client.host_live and not old_client.app_live
        current["client"] = next_client
        return next_client

    monkeypatch.setattr(fleet, "_codex_native_client", ensure_new)
    args.prepare_restored_continuation = False
    args.reattach_restored_continuation = True
    assert fleet.cmd_sup_reconcile(args) == 0
    claim = fleet.read_incarnation()
    assert claim["state"] == "held"
    assert claim["host_generation"] == next_client.generation
    assert claim["holder"] == {"provider": "codex", "thread_id": THREAD_ID}
    assert claim["current_turn_id"] == TURN_ID
    assert fleet.load_registry()["workers"][name]["adapter_state"] == "active"
    assert old_journal.load(old_op)["state"] == "observed"
    new_journal = OperationJournal(supervisor_home, next_client.generation)
    assert new_journal.load(claim["last_operation_id"])["state"] == "committed"
    writes = [op for op in next_client.operations
              if op["payload"]["method"] in {"thread/resume", "turn/start"}]
    assert len(writes) == 1
    assert writes[0]["payload"]["method"] == "thread/resume"
    assert writes[0]["payload"]["params"]["sandbox"] == "danger-full-access"
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "mail held across cold boundary"
    assert fleet._cmd_send_codex_supervisor(name, "first normal turn") == 0
    assert len([op for op in next_client.operations
                if op["payload"]["method"] == "turn/start"]) == 1
    assert old_journal.load(old_op)["state"] == "observed"


def test_restored_continuation_lost_resume_reply_never_replays(
        supervisor_home, monkeypatch):
    from fleet_codex import OperationJournal

    _name, old_op, old_journal, old_client, current, args = \
        _restored_continuation_setup(supervisor_home, monkeypatch)
    fleet.append_mailbox(THREAD_ID, "mail must remain")
    assert fleet.cmd_sup_reconcile(args) == 0
    old_client.host_live = False
    old_client.app_live = False
    old_client.metadata_stale = True
    next_client = PolicyRestoreLifecycleClient(
        supervisor_home, generation="host-generation-4",
        thread_status="idle", turn_status="completed",
        fail_method="thread/resume")
    next_client._launched_process = object()
    monkeypatch.setattr(fleet, "_codex_native_client",
                        lambda _home: current.update(client=next_client)
                        or next_client)
    args.prepare_restored_continuation = False
    args.reattach_restored_continuation = True
    with pytest.raises(fleet.FleetCliError, match="uncertain"):
        fleet.cmd_sup_reconcile(args)
    pending = fleet.read_incarnation()["pending_operation"]
    new_journal = OperationJournal(supervisor_home, next_client.generation)
    assert new_journal.load(pending["operation_id"])["state"] == "uncertain"
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert old_journal.load(old_op)["state"] == "observed"
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert len([op for op in next_client.operations
                if op["payload"]["method"] == "thread/resume"]) == 1
    assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
        encoding="utf-8").strip() == "mail must remain"


@pytest.mark.parametrize("case", [
    "active-worker", "claim", "row", "mail", "journal", "source",
    "expired", "host-live", "child-live", "wrong-expect",
])
def test_restored_continuation_drift_refuses_before_host_creation(
        supervisor_home, monkeypatch, case):
    import time

    name, old_op, old_journal, old_client, _current, args = \
        _restored_continuation_setup(supervisor_home, monkeypatch)
    if case == "active-worker":
        data = fleet.load_registry()
        data["workers"]["active-product"] = {
            "model": "codex:gpt-5.6-luna", "status": "working",
            "codex_thread_id": SUCCESSOR_THREAD_ID}
        fleet.save_registry(data)
        with pytest.raises(fleet.FleetCliError, match="worker"):
            fleet.cmd_sup_reconcile(args)
        assert "restored_continuation_preflight" not in fleet.read_incarnation()
        return
    assert fleet.cmd_sup_reconcile(args) == 0
    old_client.host_live = False
    old_client.app_live = False
    old_client.metadata_stale = True
    args.prepare_restored_continuation = False
    args.reattach_restored_continuation = True
    if case == "claim":
        claim = fleet.read_incarnation()
        claim["heartbeat_at"] = "2026-10-09T03:00:00Z"
        fleet.write_incarnation(claim)
    elif case == "row":
        data = fleet.load_registry()
        data["workers"][name]["last_activity"] = "2026-10-09T03:00:00Z"
        fleet.save_registry(data)
    elif case == "mail":
        fleet.append_mailbox(THREAD_ID, "new mail after preparation")
    elif case == "journal":
        original = old_journal.load(old_op)
        original["result"]["sandbox"]["type"] = "dangerFullAccess"
        old_journal.path(old_op).write_text(json.dumps(original), encoding="utf-8")
    elif case == "source":
        monkeypatch.setattr(
            fleet, "_registered_interface_mail_source",
            lambda: {"kind": "codex", "claim_id": "other-interface"})
    elif case == "expired":
        claim = fleet.read_incarnation()
        claim["restored_continuation_preflight"]["prepared_at"] = \
            time.time() - 301
        fleet.write_incarnation(claim)
    elif case == "host-live":
        old_client.host_live = True
    elif case == "child-live":
        old_client.app_live = True
    else:
        args.expect_restore_op = "wrong-restoration"
    monkeypatch.setattr(
        fleet, "_codex_native_client",
        lambda _home: pytest.fail("stale continuation created a host"))
    with pytest.raises((fleet.FleetCliError, ValueError)):
        fleet.cmd_sup_reconcile(args)
    assert fleet.read_incarnation()["state"] == "held"
    assert fleet.read_incarnation().get("pending_operation") is None
    assert old_journal.load(old_op)["state"] == "observed"


@pytest.mark.parametrize("changed", [
    {"_fleet_home_explicit": False},
    {"expect_inc": "another-incarnation"},
    {"expect_thread": SUCCESSOR_THREAD_ID},
    {"expect_turn": NEWER_TURN_ID},
    {"expect_resume_op": "another-operation"},
    {"expect_new_generation": "another-generation"},
])
def test_policy_restore_rejects_stale_expectations_before_provider(
        supervisor_home, monkeypatch, changed):
    _name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    client = PolicyRestoreLifecycleClient(
        supervisor_home, generation="host-generation-2",
        thread_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op, **changed))

    assert fleet.read_incarnation()["state"] == "uncertain"
    assert fleet.read_incarnation()["pending_operation"]["operation_id"] == old_op
    assert journal.load(old_op)["state"] == "observed"
    assert not any(op["payload"]["method"] == "thread/resume"
                   for op in client.operations)


@pytest.mark.parametrize("case", ["newer-turn", "active-thread",
                                   "managed-policy", "source", "row",
                                   "ambiguous-journal"])
def test_policy_restore_rejects_changed_evidence_before_provider(
        supervisor_home, monkeypatch, case):
    name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    client = PolicyRestoreLifecycleClient(
        supervisor_home, generation="host-generation-2",
        thread_status="idle", turn_status="completed")
    source = {"kind": "codex", "claim_id": "current-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: source)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
    if case == "newer-turn":
        client.newer_turn = {"id": NEWER_TURN_ID, "status": "completed",
                             "itemsView": "notLoaded", "items": []}
    elif case == "active-thread":
        client.thread_status = "active"
        client.turn_status = "inProgress"
    elif case == "managed-policy":
        client.requirements = {"allowedSandboxModes": ["workspace-write"]}
    elif case == "source":
        source = {"kind": "claude", "claim_id": "other-interface"}
    elif case == "row":
        data = fleet.load_registry()
        data["workers"][name]["permission_effective"]["sandbox"] = {
            "type": "workspaceWrite"}
        fleet.save_registry(data)
    else:
        other = {"operation_id": "other-unresolved", "method": "rpc",
                 "payload": {"method": "turn/start", "params": {
                     "threadId": THREAD_ID}}, "recovery": {}}
        journal.prepare(other)
        journal.accept(other["operation_id"])

    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(_prepare_args(incarnation_id, old_op))

    assert fleet.read_incarnation()["state"] == "uncertain"
    assert journal.load(old_op)["state"] == "observed"
    assert not any(op["payload"]["method"] == "thread/resume"
                   for op in client.operations)


@pytest.mark.parametrize("case", [
    "live-owner", "live-child", "fresh-heartbeat", "expired-proof",
    "changed-source", "changed-claim", "changed-row", "already-new-host",
])
def test_policy_restore_requires_exact_cold_boundary(
        supervisor_home, monkeypatch, case):
    name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, current = _cold_restore_clients(supervisor_home, monkeypatch)
    source = {"kind": "codex", "claim_id": "current-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: source)
    _prove_then_stop_cold_host(incarnation_id, old_op, old)
    if case == "live-owner":
        old.host_live = True
    elif case == "live-child":
        old.app_live = True
    elif case == "fresh-heartbeat":
        old.metadata_stale = False
    elif case == "expired-proof":
        claim = fleet.read_incarnation()
        claim["pending_operation"]["policy_restore_preflight"][
            "observed_at"] -= 301
        fleet.write_incarnation(claim)
    elif case == "changed-source":
        source = {"kind": "codex", "claim_id": "different-interface"}
    elif case == "changed-claim":
        claim = fleet.read_incarnation()
        claim["current_turn_id"] = NEWER_TURN_ID
        fleet.write_incarnation(claim)
    elif case == "changed-row":
        data = fleet.load_registry()
        data["workers"][name]["permission_effective"]["sandbox"] = {
            "type": "workspaceWrite"}
        fleet.save_registry(data)
    else:
        current["client"] = new

    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    assert journal.load(old_op)["state"] == "observed"
    assert not any(op["payload"]["method"] == "thread/resume"
                   for op in new.operations)


@pytest.mark.parametrize("drift", [
    "new-mail", "claimed-mail", "supervisor-row", "claim-heartbeat",
    "row-working",
])
def test_policy_restore_rejects_post_preflight_supervisor_progress(
        supervisor_home, monkeypatch, drift):
    name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, _current = _cold_restore_clients(supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old)
    if drift == "new-mail":
        fleet.append_mailbox(THREAD_ID, "arrived after preflight")
        mail = (supervisor_home / "mailbox" / f"{THREAD_ID}.md")
        before = mail.read_bytes()
    elif drift == "claimed-mail":
        mail = (supervisor_home / "mailbox"
                / f"{THREAD_ID}.md.claimed.456")
        mail.write_bytes(b"claimed after preflight\n")
        before = mail.read_bytes()
    elif drift in {"supervisor-row", "row-working"}:
        data = fleet.read_registry_no_repair()
        data["workers"][name]["last_activity"] = "changed-after-proof"
        if drift == "row-working":
            data["workers"][name]["status"] = "working"
        fleet.save_registry(data)
        before = fleet.read_registry_no_repair()["workers"][name]
    else:
        claim = fleet.read_incarnation()
        claim["heartbeat_at"] = "changed-after-proof"
        fleet.write_incarnation(claim)
        before = fleet.read_incarnation()

    with pytest.raises(fleet.FleetCliError, match="prepared claim"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))

    assert fleet.read_incarnation()["state"] == "uncertain"
    assert journal.load(old_op)["state"] == "observed"
    assert new.operations == []
    if drift in {"new-mail", "claimed-mail"}:
        assert mail.read_bytes() == before
    elif drift in {"supervisor-row", "row-working"}:
        assert fleet.read_registry_no_repair()["workers"][name] == before
    else:
        assert fleet.read_incarnation() == before


def test_policy_restore_allows_unrelated_product_progress_after_preflight(
        supervisor_home, monkeypatch):
    _name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, _current = _cold_restore_clients(supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old)
    data = fleet.read_registry_no_repair()
    unrelated = {"status": "working", "last_activity": "product-progress",
                 "codex_thread_id": SUCCESSOR_THREAD_ID}
    data["workers"]["unrelated-product-worker"] = dict(unrelated)
    fleet.save_registry(data)

    assert fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op)) == 0
    assert fleet.read_registry_no_repair()["workers"][
        "unrelated-product-worker"] == unrelated
    assert journal.load(old_op)["state"] == "observed"
    assert len([op for op in new.operations
                if op["payload"]["method"] == "thread/resume"]) == 1


def test_policy_restore_rechecks_row_at_provider_dispatch(
        supervisor_home, monkeypatch):
    name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, _current = _cold_restore_clients(supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old)
    original_call = fleet._call_codex_supervisor_claimed

    def drift_before_dispatch(*args, **kwargs):
        data = fleet.read_registry_no_repair()
        data["workers"][name]["status"] = "working"
        fleet.save_registry(data)
        return original_call(*args, **kwargs)

    monkeypatch.setattr(fleet, "_call_codex_supervisor_claimed",
                        drift_before_dispatch)
    with pytest.raises(fleet.FleetCliError, match="uncertain"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    assert fleet.read_registry_no_repair()["workers"][name]["status"] == "working"
    assert journal.load(old_op)["state"] == "observed"
    assert not any(op["payload"]["method"] == "thread/resume"
                   for op in new.operations)


def test_policy_restore_settlement_preserves_post_acceptance_row_progress(
        supervisor_home, monkeypatch):
    name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, _current = _cold_restore_clients(supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old)
    original_call = new.call

    def accept_then_progress(operation, timeout):
        observed = original_call(operation, timeout)
        if (operation["payload"]["method"] == "thread/resume"
                and "sandbox" in operation["payload"]["params"]):
            data = fleet.read_registry_no_repair()
            data["workers"][name]["status"] = "working"
            data["workers"][name]["last_activity"] = "after-acceptance"
            fleet.save_registry(data)
        return observed

    monkeypatch.setattr(new, "call", accept_then_progress)
    with pytest.raises(fleet.FleetCliError, match="reserved claim"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    pending = fleet.read_incarnation()["pending_operation"]
    assert pending["kind"] == "resume-policy-restore"
    assert journal.load(old_op)["state"] == "observed"
    assert journal.load(pending["operation_id"])["state"] == "observed"
    assert fleet.read_registry_no_repair()["workers"][name]["status"] == "working"
    with pytest.raises(fleet.FleetCliError, match="reserved claim"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert len([op for op in new.operations
                if op["payload"]["method"] == "thread/resume"]) == 1


def test_cold_restore_refuses_workspace_profile_even_with_full_access_sandbox(
        supervisor_home, monkeypatch):
    _name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old, new, _current = _cold_restore_clients(
        supervisor_home, monkeypatch,
        restored_active_profile={"id": ":workspace", "extends": None})
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old)

    with pytest.raises(fleet.FleetCliError, match="workspace profile"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    pending = fleet.read_incarnation()["pending_operation"]
    assert pending["kind"] == "resume-policy-restore"
    assert journal.load(old_op)["state"] == "observed"
    assert journal.load(pending["operation_id"])["state"] == "observed"
    assert len([op for op in new.operations
                if op["payload"]["method"] == "thread/resume"]) == 1


def test_observed_restore_policy_mismatch_stays_uncertain_without_replay(
        supervisor_home, monkeypatch):
    _name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old_client, client, _current = _cold_restore_clients(
        supervisor_home, monkeypatch, apply_override=False,
        restore_policy={
            "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": {"type": "workspaceWrite", "writableRoots": []},
        })
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    with pytest.raises(fleet.FleetCliError, match="effective sandbox mismatch"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    pending = fleet.read_incarnation()["pending_operation"]
    assert pending["kind"] == "resume-policy-restore"
    assert journal.load(old_op)["state"] == "observed"
    assert journal.load(pending["operation_id"])["state"] == "observed"
    before = len([op for op in client.operations
                  if op["payload"]["method"] == "thread/resume"])
    with pytest.raises(fleet.FleetCliError, match="effective sandbox mismatch"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert len([op for op in client.operations
                if op["payload"]["method"] == "thread/resume"]) == before == 1


def test_observed_restore_settles_read_only_after_public_turn_recovers(
        supervisor_home, monkeypatch):
    _name, incarnation_id, old_op, journal = \
        _seed_observed_workspace_resume(supervisor_home)
    old_client, client, _current = _cold_restore_clients(
        supervisor_home, monkeypatch)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    original_header = fleet._codex_idle_restoration_header
    observations = []

    def interrupted_second_header(binding, observed_client):
        observations.append(1)
        if len(observations) == 2:
            raise fleet.FleetCliError("public header temporarily unavailable")
        return original_header(binding, observed_client)

    monkeypatch.setattr(fleet, "_codex_idle_restoration_header",
                        interrupted_second_header)
    _prove_then_stop_cold_host(incarnation_id, old_op, old_client)
    with pytest.raises(fleet.FleetCliError, match="temporarily unavailable"):
        fleet.cmd_sup_reconcile(_restore_args(incarnation_id, old_op))
    pending = fleet.read_incarnation()["pending_operation"]
    assert pending["kind"] == "resume-policy-restore"
    assert journal.load(pending["operation_id"])["state"] == "observed"
    mutation_count = len([op for op in client.operations
                          if op["payload"]["method"] == "thread/resume"])
    monkeypatch.setattr(fleet, "_codex_idle_restoration_header", original_header)
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert fleet.read_incarnation()["state"] == "held"
    assert journal.load(pending["operation_id"])["state"] == "committed"
    assert len([op for op in client.operations
                if op["payload"]["method"] == "thread/resume"]) == mutation_count == 1


def _seed_rejected_supervisor_send(home, *, method="turn/steer"):
    from fleet_codex import OperationJournal

    name, incarnation_id = _seed_native_supervisor(home)
    binding = fleet._codex_supervisor_binding()
    operation_id = "supervisor-send-rejected-test"
    fleet._reserve_codex_supervisor_operation(
        binding, operation_id, "observe-send")
    fleet.append_mailbox(THREAD_ID, "claimed before provider rejection")
    _queued, claimed = fleet.claim_mailbox(THREAD_ID)
    assert claimed is not None
    fleet._freeze_codex_supervisor_preclaim(
        name, incarnation_id, operation_id, "authentication rejected")
    journal = OperationJournal(home, binding.host_generation)
    operation = {
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": method, "params": {"threadId": THREAD_ID}},
        "recovery": {
            "kind": f"supervisor/{method}", "fleet_name": name,
            "incarnation_id": incarnation_id, "thread_id": THREAD_ID,
            "previous_turn_id": TURN_ID, "canonical_cwd": str(home.resolve()),
        },
    }
    journal.prepare(operation)
    return name, claimed, journal, operation_id


def test_uncertain_send_reconciles_only_failed_intent_and_restores_mail(
        supervisor_home, monkeypatch):
    import fleet_codex

    name, claimed, journal, operation_id = _seed_rejected_supervisor_send(
        supervisor_home)
    journal.fail(operation_id, "authentication rejected before provider acceptance")
    client = FakeLifecycleClient(
        supervisor_home, generation="host-generation-2")
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    source = {"kind": "codex", "claim_id": "current-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: source)

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0

    claim = fleet.read_incarnation()
    row = fleet.load_registry()["workers"][name]
    assert claim["state"] == "held"
    assert claim["current_turn_id"] == TURN_ID
    assert claim["host_generation"] == "host-generation-1"
    assert "pending_operation" not in claim
    assert row["adapter_state"] == "active"
    assert row["codex_turn_id"] == TURN_ID
    assert claimed.exists() is False
    inbox = (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text()
    assert "claimed before provider rejection" in inbox
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_legacy_host_auth_refusal_settles_prepared_without_restart_or_replay(
        supervisor_home, monkeypatch):
    import fleet_codex

    _name, claimed, journal, operation_id = _seed_rejected_supervisor_send(
        supervisor_home)
    claim = fleet.read_incarnation()
    claim["uncertainty"] = fleet._CODEX_PREACCEPT_AUTH_REJECTION
    fleet.write_incarnation(claim)
    client = FakeLifecycleClient(
        supervisor_home, thread_status="idle", turn_status="completed")
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert journal.load(operation_id)["state"] == "failed"
    assert fleet.read_incarnation()["state"] == "held"
    assert fleet.load_registry()["workers"][_name]["status"] == "idle"
    assert not claimed.exists()
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


def test_rejected_send_reads_no_item_history_even_if_items_are_oversized(
        supervisor_home, monkeypatch):
    import fleet_codex

    _name, _claimed, journal, operation_id = _seed_rejected_supervisor_send(
        supervisor_home)
    journal.fail(operation_id, "authentication rejected before provider acceptance")
    client = FakeLifecycleClient(supervisor_home, items_view="notLoaded")
    original = client.call

    def no_item_read(operation, timeout):
        if operation["payload"]["method"] == "thread/items/list":
            raise fleet.FleetCliError("single history item exceeds IPC bound")
        return original(operation, timeout)

    client.call = no_item_read
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert all(op["payload"]["method"] != "thread/items/list"
               for op in client.paging_operations)


def test_rejected_send_after_host_change_keeps_thread_for_separate_resume(
        supervisor_home, monkeypatch):
    import fleet_codex

    name, _claimed, journal, operation_id = _seed_rejected_supervisor_send(
        supervisor_home)
    journal.fail(operation_id, "prepared operation was never accepted")
    client = FakeLifecycleClient(
        supervisor_home, generation="host-generation-2",
        thread_status="notLoaded", turn_status="completed")
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    claim = fleet.read_incarnation()
    row = fleet.load_registry()["workers"][name]
    assert claim["state"] == "held"
    assert claim["host_generation"] == "host-generation-1"
    assert row["codex_host_generation"] == "host-generation-1"
    assert row["status"] == "dead-suspected"
    assert [op["payload"]["method"] for op in client.operations] == [
        "thread/read"]


@pytest.mark.parametrize("failure", ["unaccepted", "accepted", "wrong-source",
                                      "stale-generation", "newer-turn",
                                      "oversized-history", "changed-claim",
                                      "changed-source",
                                      "missing-mail", "new-inbox"])
def test_uncertain_send_keeps_claim_and_mail_on_ambiguous_evidence(
        supervisor_home, monkeypatch, failure):
    import fleet_codex

    _name, claimed, journal, operation_id = _seed_rejected_supervisor_send(
        supervisor_home)
    if failure not in {"unaccepted", "accepted", "stale-generation"}:
        journal.fail(operation_id, "authentication rejected before provider acceptance")
    if failure == "accepted":
        journal.accept(operation_id)
    if failure == "stale-generation":
        claim = fleet.read_incarnation()
        claim["uncertainty"] = fleet._CODEX_PREACCEPT_AUTH_REJECTION
        fleet.write_incarnation(claim)
    source = {"kind": "codex", "claim_id": "current-interface"}
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: None if failure == "wrong-source" else dict(source))
    newer = ({"id": NEWER_TURN_ID, "status": "completed",
              "itemsView": "full", "items": []}
             if failure == "newer-turn" else None)
    client = FakeLifecycleClient(
        supervisor_home, newer_turn=newer,
        generation=("host-generation-2" if failure == "stale-generation"
                    else None))
    monkeypatch.setattr(fleet_codex, "connect_existing", lambda _home: client)
    if failure == "missing-mail":
        claimed.unlink()
    if failure == "new-inbox":
        fleet.append_mailbox(THREAD_ID, "arrived during uncertainty")
    if failure == "oversized-history":
        monkeypatch.setattr(
            fleet, "_codex_paged_thread_read",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                fleet.FleetCliError("single public history item exceeds IPC bound")))
    if failure == "changed-claim":
        original = fleet._codex_rejected_send_public_header

        def change_claim(*args, **kwargs):
            observation = original(*args, **kwargs)
            changed = fleet.read_incarnation()
            changed["heartbeat_at"] = "2026-10-09T03:00:00Z"
            fleet.write_incarnation(changed)
            return observation

        monkeypatch.setattr(fleet, "_codex_rejected_send_public_header", change_claim)
    if failure == "changed-source":
        original = fleet._codex_rejected_send_public_header

        def change_source(*args, **kwargs):
            observation = original(*args, **kwargs)
            source["claim_id"] = "new-interface"
            return observation

        monkeypatch.setattr(fleet, "_codex_rejected_send_public_header", change_source)
    with pytest.raises(fleet.FleetCliError):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    assert fleet.read_incarnation()["state"] == "uncertain"
    assert claimed.exists() is (failure != "missing-mail")
    if failure == "new-inbox":
        assert (supervisor_home / "mailbox" / f"{THREAD_ID}.md").read_text(
            encoding="utf-8").strip() == "arrived during uncertainty"
    assert [op["payload"]["method"] for op in client.operations] in (
        [], ["thread/read"])


def test_rejected_preclaim_retires_without_inventing_thread(
        supervisor_home, monkeypatch):
    from fleet_codex import OperationJournal

    name, incarnation_id = _seed_native_supervisor(supervisor_home)
    operation_id = f"supervisor-{incarnation_id}-thread-rejected"
    claim = fleet.read_incarnation()
    claim.update({"state": "uncertain", "holder": None,
                  "preclaim_id": operation_id})
    claim.pop("current_turn_id", None)
    claim.pop("host_generation", None)
    claim.pop("last_operation_id", None)
    fleet.write_incarnation(claim)
    data = fleet.load_registry()
    data["workers"][name].update({
        "adapter_state": "uncertain", "codex_thread_id": None,
        "codex_turn_id": None, "codex_host_generation": None,
        "last_operation_id": operation_id,
    })
    fleet.save_registry(data)
    journal = OperationJournal(supervisor_home, "host-generation-1")
    journal.prepare({
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": "thread/start", "params": {
            "cwd": str(supervisor_home.resolve())}},
        "recovery": {"kind": "supervisor/thread-start", "fleet_name": name,
                     "incarnation_id": incarnation_id,
                     "canonical_cwd": str(supervisor_home.resolve())},
    })
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})
    with pytest.raises(fleet.FleetCliError, match="not proved rejected"):
        fleet.cmd_sup_reconcile(SimpleNamespace())
    journal.fail(operation_id, "authentication rejected before provider acceptance")
    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert fleet.read_incarnation()["state"] == "released"
    row = fleet.load_registry()["workers"][name]
    assert row["status"] == "dead"
    assert row["codex_thread_id"] is None


def test_legacy_host_preclaim_auth_refusal_settles_prepared(
        supervisor_home, monkeypatch):
    import fleet_codex

    name, incarnation_id = _seed_native_supervisor(supervisor_home)
    operation_id = f"supervisor-{incarnation_id}-thread-auth-refused"
    claim = fleet.read_incarnation()
    claim.update({"state": "uncertain", "holder": None,
                  "preclaim_id": operation_id,
                  "uncertainty": fleet._CODEX_PREACCEPT_AUTH_REJECTION})
    claim.pop("current_turn_id", None)
    claim.pop("host_generation", None)
    claim.pop("last_operation_id", None)
    fleet.write_incarnation(claim)
    data = fleet.load_registry()
    data["workers"][name].update({
        "adapter_state": "uncertain", "codex_thread_id": None,
        "codex_turn_id": None, "codex_host_generation": None,
        "last_operation_id": operation_id,
    })
    fleet.save_registry(data)
    journal = fleet_codex.OperationJournal(
        supervisor_home, "host-generation-1")
    journal.prepare({
        "operation_id": operation_id, "method": "rpc",
        "payload": {"method": "thread/start", "params": {
            "cwd": str(supervisor_home.resolve())}},
        "recovery": {"kind": "supervisor/thread-start", "fleet_name": name,
                     "incarnation_id": incarnation_id,
                     "canonical_cwd": str(supervisor_home.resolve())},
    })
    monkeypatch.setattr(fleet_codex, "connect_existing",
                        lambda _home: FakeLifecycleClient(supervisor_home))
    monkeypatch.setattr(fleet, "_registered_interface_mail_source",
                        lambda: {"kind": "codex", "claim_id": "current-interface"})

    assert fleet.cmd_sup_reconcile(SimpleNamespace()) == 0
    assert journal.load(operation_id)["state"] == "failed"
    assert fleet.read_incarnation()["state"] == "released"


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


def test_oversize_accepted_turn_reply_keeps_handoff_activating(
        supervisor_home, monkeypatch):
    """Exercise provider, host, journal, client, and handoff as one path."""
    import fleet_codex
    from test_codex_host_ipc import _ensure, _shutdown

    old_name, _inc = _seed_native_supervisor(supervisor_home)
    _module, real_client, log = _ensure(
        supervisor_home, home=supervisor_home,
        env_overrides={"FAKE_OVERSIZE_TURN_RESULT": "1"})
    try:
        claim = fleet.read_incarnation()
        claim["host_generation"] = real_client.generation
        fleet.write_incarnation(claim)
        data = fleet.load_registry()
        data["workers"][old_name]["codex_host_generation"] = real_client.generation
        fleet.save_registry(data)

        class Hybrid(FakeLifecycleClient):
            def call(self, operation, timeout):
                if operation["payload"]["method"] == "turn/start":
                    return real_client.call(operation, timeout)
                return super().call(operation, timeout)

        client = Hybrid(supervisor_home, generation=real_client.generation)
        monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)
        with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
            fleet.cmd_sup_handoff_begin(SimpleNamespace(
                model="codex:gpt-5.6-luna", permission_mode="bypass",
                sid=None, nonce=None))

        live = fleet.read_incarnation()
        assert live["state"] == "activating"
        assert live["holder"]["thread_id"] == SUCCESSOR_HANDOFF_THREAD_ID
        assert live["predecessor"]["name"] == old_name
        operation_id = live["pending_operation"]["operation_id"]
        journal = fleet_codex.OperationJournal(
            supervisor_home, real_client.generation).load(operation_id)
        assert journal["state"] == "uncertain"
        assert "post-acceptance" in journal["reason"]
        requests = [json.loads(line) for line in log.read_text().splitlines()]
        assert sum(row.get("method") == "turn/start" for row in requests) == 1
        workers = fleet.load_registry()["workers"]
        assert old_name in workers and len(workers) == 2
    finally:
        _shutdown(real_client)
        assert real_client.wait_for_exit(5)


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


def test_native_handoff_rollback_preserves_adopted_lineages(
        supervisor_home, monkeypatch):
    old_name, incarnation_id = _seed_native_supervisor(supervisor_home)
    claim = fleet.read_incarnation()
    claim["adopted_lineages"] = ["lin-old", "lin-older"]
    fleet.write_incarnation(claim)
    client = FakeLifecycleClient(supervisor_home, reject_turn_start=True)
    monkeypatch.setattr(fleet, "_codex_existing_client", lambda _home: client)

    with pytest.raises(fleet.FleetCliError, match="activation is uncertain"):
        fleet.cmd_sup_handoff_begin(SimpleNamespace(
            model="codex:gpt-5.6-luna", permission_mode="bypass",
            sid=None, nonce=None, expect_inc=incarnation_id))

    restored = fleet.read_incarnation()
    assert restored["state"] == "held"
    assert restored["adopted_lineages"] == ["lin-old", "lin-older"]
    assert list(fleet.load_registry()["workers"]) == [old_name]


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
