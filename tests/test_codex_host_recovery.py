import hashlib
import json
import os
import stat

import pytest

from test_codex_host_ipc import _ensure, _shutdown


def _module():
    try:
        import fleet_codex
    except ModuleNotFoundError:
        pytest.fail("bin/fleet_codex.py is not implemented")
    return fleet_codex


def _host_module():
    try:
        import fleet_codex_host
    except ModuleNotFoundError:
        pytest.fail("bin/fleet_codex_host.py is not implemented")
    return fleet_codex_host


def _mutation(operation_id="turn-op", public_method="turn/start", value=1):
    return {
        "operation_id": operation_id,
        "method": "rpc",
        "payload": {
            "method": public_method,
            "params": {"threadId": "thread-1", "input": [{"value": value}]},
        },
        "recovery": {
            "kind": public_method,
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "canonical_cwd": "/project",
            "history_watermark": 2,
        },
    }


def _operation_file(client, operation_id):
    return client.state_dir / "operations" / f"{operation_id}.json"


def _app_requests(log, method):
    return [row for row in (json.loads(line) for line in log.read_text().splitlines())
            if row.get("event") == "request" and row.get("method") == method]


def test_same_operation_replays_observed_result_without_second_mutation(tmp_path):
    module, client, log = _ensure(tmp_path)
    operation = _mutation()
    try:
        first = client.call(operation, timeout=2)
        second = client.call(operation, timeout=2)

        assert first.result == second.result == {
            "turn": {"id": "turn-1", "status": "inProgress"}}
        assert len(_app_requests(log, "turn/start")) == 1
        record = json.loads(_operation_file(client, "turn-op").read_text())
        assert record["state"] == "observed"
        assert record["operation_id"] == "turn-op"
        assert record["payload_digest"] == first.payload_digest

        client.commit("turn-op")
        assert json.loads(_operation_file(client, "turn-op").read_text())["state"] == "committed"
    finally:
        _shutdown(client)
        assert client.wait_for_exit(2)


def test_provider_acceptance_with_lost_response_is_uncertain_and_never_replayed(
        tmp_path, monkeypatch):
    module, client, log = _ensure(
        tmp_path, env_overrides={"FAKE_DROP_TURN_RESPONSE": "1"})
    operation = _mutation("lost-provider-response", "turn/start")
    try:
        with pytest.raises(module.HostRejected, match="outcome is uncertain"):
            client.call(operation, timeout=2)
        record = json.loads(_operation_file(client, operation["operation_id"])
                            .read_text())
        assert record["state"] == "uncertain"
        assert "outcome unknown" in record["reason"]
    finally:
        _shutdown(client)
        assert client.wait_for_exit(2)

    # A replacement host classifies the accepted intent before it publishes
    # readiness. Retrying the same operation must remain blocked and must not
    # issue a second provider turn.
    monkeypatch.setattr(module, "HOST_HEARTBEAT_STALE_SECONDS", 0.0)
    _module_value, replacement, _replacement_log = _ensure(
        tmp_path, home=client.home)
    try:
        record = json.loads(_operation_file(
            replacement, operation["operation_id"]).read_text())
        assert record["state"] == "uncertain"
        with pytest.raises(module.HostRejected, match="uncertain"):
            replacement.call(operation, timeout=2)
        assert _app_requests(log, "turn/start") == [
            {"event": "request", "method": "turn/start"}]
    finally:
        _shutdown(replacement)


@pytest.mark.parametrize("state", ["observed", "uncertain"])
def test_exact_handoff_turn_evidence_commits_original_operation(tmp_path, state):
    module = _module()
    home = tmp_path / state
    (home / "state").mkdir(parents=True)
    journal = module.OperationJournal(home.resolve(), "generation-1")
    operation = {
        "operation_id": "handoff-turn",
        "method": "rpc",
        "payload": {"method": "turn/start", "params": {
            "threadId": "thread-1", "input": [{"text": "boot"}],
        }},
        "recovery": {
            "kind": "supervisor/handoff-turn-start",
            "fleet_name": "sup|inc-next|successor",
            "incarnation_id": "inc-next", "thread_id": "thread-1",
            "canonical_cwd": str(home.resolve()), "history_watermark": 0,
        },
    }
    journal.prepare(operation)
    journal.accept(operation["operation_id"])
    if state == "observed":
        journal.observe(operation["operation_id"], {
            "turn": {"id": "turn-1", "status": "inProgress"}})
    else:
        journal.uncertain(operation["operation_id"], "response lost")

    record = journal.commit_handoff_turn_start(
        operation["operation_id"], fleet_name="sup|inc-next|successor",
        incarnation_id="inc-next", thread_id="thread-1",
        turn_id="turn-1", canonical_cwd=str(home.resolve()),
        history_watermark=0)

    assert record["state"] == "committed"
    assert record["result"]["threadId"] == "thread-1"
    assert record["result"]["turnId"] == "turn-1"
    assert journal.unresolved_predecessor("next-operation") is None


def test_handoff_turn_evidence_mismatch_keeps_operation_unresolved(tmp_path):
    module = _module()
    home = tmp_path / "mismatch"
    (home / "state").mkdir(parents=True)
    journal = module.OperationJournal(home.resolve(), "generation-1")
    operation = {
        "operation_id": "handoff-turn",
        "method": "rpc",
        "payload": {"method": "turn/start", "params": {
            "threadId": "thread-1", "input": [{"text": "boot"}],
        }},
        "recovery": {
            "kind": "supervisor/handoff-turn-start",
            "fleet_name": "sup|inc-next|successor",
            "incarnation_id": "inc-next", "thread_id": "thread-1",
            "canonical_cwd": str(home.resolve()), "history_watermark": 0,
        },
    }
    journal.prepare(operation)
    journal.accept(operation["operation_id"])
    journal.observe(operation["operation_id"], {
        "turn": {"id": "turn-other", "status": "inProgress"}})

    with pytest.raises(module.HostRejected, match="turn evidence"):
        journal.commit_handoff_turn_start(
            operation["operation_id"],
            fleet_name="sup|inc-next|successor",
            incarnation_id="inc-next", thread_id="thread-1",
            turn_id="turn-1", canonical_cwd=str(home.resolve()),
            history_watermark=0)

    assert journal.load(operation["operation_id"])["state"] == "observed"


def test_reused_operation_id_with_changed_payload_is_refused_before_rpc(tmp_path):
    module, client, log = _ensure(tmp_path)
    try:
        client.call(_mutation(value=1), timeout=2)
        with pytest.raises(module.HostRejected, match="digest"):
            client.call(_mutation(value=2), timeout=2)
        assert len(_app_requests(log, "turn/start")) == 1
    finally:
        _shutdown(client)


def _prepared_record(tmp_path, public_method, stage):
    module = _module()
    home = tmp_path / public_method.replace("/", "-") / stage
    (home / "state" / "codex").mkdir(parents=True, mode=0o700)
    journal = module.OperationJournal(home.resolve(), "generation-1")
    operation = _mutation(f"{public_method.replace('/', '-')}-{stage}", public_method)
    record = journal.prepare(operation)
    if stage in {"after-send", "after-response", "before-fleet-commit"}:
        record = journal.accept(record["operation_id"])
    if stage in {"after-response", "before-fleet-commit"}:
        record = journal.observe(record["operation_id"], {
            "threadId": "thread-1", "turnId": "turn-1"})
    return module, home.resolve(), journal, operation, record


def _exact_observation(_record):
    return {
        "verdict": "observed",
        "result": {"threadId": "thread-1", "turnId": "turn-1"},
        "schema_matches": True,
        "cwd_matches": True,
        "thread_status": "idle",
        "new_turns": 1,
        "read_complete": True,
        "turns_complete": True,
        "items_complete": True,
    }


@pytest.mark.parametrize("public_method", [
    "thread/start", "thread/resume", "turn/start", "turn/steer",
    "turn/interrupt"])
@pytest.mark.parametrize("stage", [
    "before-send", "after-send", "after-response", "before-fleet-commit"])
def test_crash_boundaries_never_blindly_retry_mutations(
        tmp_path, public_method, stage):
    module, home, _journal, operation, _record = _prepared_record(
        tmp_path, public_method, stage)

    report = module.reconcile_home(home, observer=_exact_observation)

    record = json.loads((home / "state" / "codex" / "operations"
                         / f"{operation['operation_id']}.json").read_text())
    if stage == "before-send":
        assert record["state"] == "failed"
    elif stage == "after-send" and public_method == "thread/start":
        assert record["state"] == "uncertain"
    else:
        assert record["state"] == "observed"
    assert report.retried_operations == 0


@pytest.mark.parametrize("observation,reason", [
    ({"verdict": "observed", "schema_matches": False}, "schema"),
    ({"verdict": "observed", "schema_matches": True, "cwd_matches": False}, "cwd"),
    ({"verdict": "observed", "schema_matches": True, "cwd_matches": True,
      "thread_status": "systemError"}, "system"),
    ({"verdict": "observed", "schema_matches": True, "cwd_matches": True,
      "thread_status": "idle", "new_turns": 2}, "multiple"),
    ({"verdict": "unknown_transport"}, "transport"),
])
def test_ambiguous_public_recovery_freezes_and_pages(tmp_path, observation, reason):
    module, home, _journal, operation, _record = _prepared_record(
        tmp_path, "turn/start", "after-send")

    report = module.reconcile_home(home, observer=lambda _record: observation)

    record = json.loads((home / "state" / "codex" / "operations"
                         / f"{operation['operation_id']}.json").read_text())
    assert record["state"] == "uncertain"
    assert reason in record["reason"].lower()
    assert report.page is True
    assert report.retried_operations == 0


def test_recovery_requires_complete_read_and_paged_turn_item_history(tmp_path):
    module, home, _journal, operation, _record = _prepared_record(
        tmp_path, "turn/interrupt", "after-send")
    incomplete = _exact_observation({})
    incomplete["items_complete"] = False

    report = module.reconcile_home(home, observer=lambda _record: incomplete)

    record = json.loads((home / "state" / "codex" / "operations"
                         / f"{operation['operation_id']}.json").read_text())
    assert record["state"] == "uncertain"
    assert "paged" in record["reason"].lower()
    assert report.page is True


def test_recovery_without_public_observer_freezes_accepted_operation(tmp_path):
    module, home, _journal, operation, _record = _prepared_record(
        tmp_path, "turn/steer", "after-send")

    report = module.reconcile_home(home)

    record = json.loads((home / "state" / "codex" / "operations"
                         / f"{operation['operation_id']}.json").read_text())
    assert record["state"] == "uncertain"
    assert "observer unavailable" in record["reason"]
    assert report.page is True


def test_journal_redacts_prompts_but_keeps_public_ids(tmp_path):
    module, home, journal, operation, _record = _prepared_record(
        tmp_path, "turn/start", "after-send")
    journal.observe(operation["operation_id"], {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "input": "private prompt",
        "message": {"text": "private answer"},
    })

    text = (home / "state" / "codex" / "operations"
            / f"{operation['operation_id']}.json").read_text()
    assert "private prompt" not in text
    assert "private answer" not in text
    assert "thread-1" in text
    assert "turn-1" in text


def _resume_result(*, item_text="small result"):
    return {
        "thread": {
            "id": "thread-1", "cwd": "/project", "model": "gpt-5.6-luna",
            "threadSource": "fleet-test-source",
            "status": {"type": "idle", "activeFlags": []},
            "turns": [
                {"id": "turn-0", "status": "completed", "items": []},
                {"id": "turn-1", "status": "completed", "items": [{
                    "id": "item-1", "type": "agentMessage", "text": item_text,
                }]},
            ],
        },
        "cwd": "/project", "model": "gpt-5.6-luna",
        "approvalPolicy": "on-request", "approvalsReviewer": "user",
        "sandbox": {"type": "workspaceWrite"},
    }


def _queue_recovery_resume(home, journal, parent_operation_id):
    operation_id = "queue-recovery-" + hashlib.sha256(
        parent_operation_id.encode("utf-8")).hexdigest()
    operation = {
        "operation_id": operation_id,
        "method": "rpc",
        "payload": {"method": "thread/resume", "params": {
            "threadId": "thread-1",
        }},
        "recovery": {
            "kind": "queue-overflow-thread-resume",
            "parent_operation_id": parent_operation_id,
            "thread_id": "thread-1",
            "canonical_cwd": str(home),
            "history_watermark": 0,
        },
    }
    journal.prepare(operation)
    journal.accept(operation_id)
    result = _resume_result()
    result["thread"]["cwd"] = result["cwd"] = str(home)
    result["thread"]["turns"] = []
    return operation_id, result


@pytest.mark.parametrize("state", ["observed", "uncertain"])
def test_queue_recovery_resume_finalizes_without_replaying_mutation(
        tmp_path, state):
    module = _module()
    host_module = _host_module()
    home = (tmp_path / state).resolve()
    (home / "state").mkdir(parents=True)
    journal = module.OperationJournal(home, "generation-1")
    parent_operation_id = f"parent-{state}"
    operation_id, result = _queue_recovery_resume(
        home, journal, parent_operation_id)
    if state == "observed":
        journal.observe(operation_id, result)
    else:
        journal.uncertain(operation_id, "injected projection write failure")

    requests = []

    def recovery_request(method, params, _deadline):
        requests.append((method, params))
        assert state == "uncertain"
        assert method == "thread/read"
        assert params == {"threadId": "thread-1", "includeTurns": True}
        return result

    host = object.__new__(host_module.Host)
    host.journal = journal
    host._recovery_request = recovery_request
    resumed = host._resume_recovery_thread(
        parent_operation_id, "thread-1", str(home), 1.0)

    assert resumed["thread"]["id"] == "thread-1"
    assert journal.load(operation_id)["state"] == "committed"
    assert requests == ([] if state == "observed" else [
        ("thread/read", {"threadId": "thread-1", "includeTurns": True})])


def test_queue_recovery_resume_settles_observe_persistence_failure(
        tmp_path, monkeypatch):
    module = _module()
    host_module = _host_module()
    home = tmp_path.resolve()
    (home / "state").mkdir()
    journal = module.OperationJournal(home, "generation-1")
    parent_operation_id = "parent-observe-failure"
    operation_id = "queue-recovery-" + hashlib.sha256(
        parent_operation_id.encode("utf-8")).hexdigest()
    result = _resume_result()
    result["thread"]["cwd"] = result["cwd"] = str(home)
    result["thread"]["turns"] = []
    requests = []

    def recovery_request(method, params, _deadline):
        requests.append((method, params))
        return result

    real_atomic_json = module._atomic_json
    failed = False

    def fail_observed_once(path, value):
        nonlocal failed
        if (not failed and path == journal.path(operation_id)
                and value.get("state") == "observed"):
            failed = True
            raise OSError("injected observed persistence failure")
        return real_atomic_json(path, value)

    monkeypatch.setattr(module, "_atomic_json", fail_observed_once)
    host = object.__new__(host_module.Host)
    host.journal = journal
    host._recovery_request = recovery_request

    resumed = host._resume_recovery_thread(
        parent_operation_id, "thread-1", str(home), 1.0)

    assert resumed["thread"]["id"] == "thread-1"
    assert journal.load(operation_id)["state"] == "committed"
    assert [method for method, _params in requests] == [
        "thread/resume", "thread/read"]


def test_large_resume_result_persists_as_a_bounded_projection_and_commits(tmp_path):
    module, home, journal, operation, _record = _prepared_record(
        tmp_path, "thread/resume", "after-send")

    observed = journal.observe(
        operation["operation_id"], _resume_result(item_text="x" * (96 * 1024)))
    committed = journal.commit(operation["operation_id"])

    assert observed["result"] == {
        "thread": {
            "id": "thread-1", "cwd": "/project", "model": "gpt-5.6-luna",
            "threadSource": "fleet-test-source",
            "status": {"type": "idle", "activeFlags": []},
        },
        "cwd": "/project", "model": "gpt-5.6-luna",
        "approvalPolicy": "on-request", "approvalsReviewer": "user",
        "sandbox": {"type": "workspaceWrite"},
        "turnCount": 2,
        "newestTurn": {"id": "turn-1", "status": "completed"},
    }
    assert committed["state"] == "committed"
    path = journal.path(operation["operation_id"])
    assert path.stat().st_size < module.MAX_METADATA_BYTES
    assert "x" * 100 not in path.read_text()


def test_observe_persistence_failure_moves_accepted_operation_to_uncertain(
        tmp_path, monkeypatch):
    module, _home, journal, operation, _record = _prepared_record(
        tmp_path, "thread/resume", "after-send")
    real_atomic_json = module._atomic_json

    def fail_result_persistence(path, value):
        if value.get("state") in {"observed", "uncertain"} \
                and "result" in value:
            raise OSError("injected observed persistence failure")
        return real_atomic_json(path, value)

    monkeypatch.setattr(module, "_atomic_json", fail_result_persistence)

    with pytest.raises(OSError, match="injected observed persistence failure"):
        journal.observe(operation["operation_id"], _resume_result())

    record = journal.load(operation["operation_id"])
    assert record["state"] == "uncertain"
    assert "result persistence failed" in record["reason"]
    assert "result" not in record


def test_uncertain_resume_settles_from_exact_public_thread_and_unblocks_mutation(
        tmp_path):
    _module_value, _home, journal, operation, _record = _prepared_record(
        tmp_path, "thread/resume", "after-send")
    journal.uncertain(operation["operation_id"], "provider response lost")

    adopted = journal.adopt_thread_read(
        operation["operation_id"], _resume_result(item_text="public read body"))
    assert adopted["state"] == "observed"
    assert adopted["result"]["newestTurn"] == {
        "id": "turn-1", "status": "completed"}
    journal.commit(operation["operation_id"])

    next_operation = _mutation("next-operation", "turn/start")
    journal.prepare(next_operation)
    assert journal.unresolved_predecessor("next-operation") is None
    assert journal.accept("next-operation")["state"] == "accepted"


@pytest.mark.parametrize("mismatch", ["turn-count", "newest-turn"])
def test_uncertain_resume_refuses_mismatched_public_thread_history(
        tmp_path, mismatch):
    module, _home, journal, operation, _record = _prepared_record(
        tmp_path, "thread/resume", "after-send")
    journal.uncertain(operation["operation_id"], "provider response lost")
    result = _resume_result()
    if mismatch == "turn-count":
        result["thread"]["turns"].append({
            "id": "turn-2", "status": "completed", "items": []})
        match = "history"
    else:
        result["thread"]["turns"][-1]["id"] = "turn-other"
        match = "newest"

    with pytest.raises(module.HostRejected, match=match):
        journal.adopt_thread_read(operation["operation_id"], result)

    assert journal.load(operation["operation_id"])["state"] == "uncertain"


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner-only mode assertion")
def test_operation_journal_is_owner_only(tmp_path):
    _module_value, home, journal, operation, _record = _prepared_record(
        tmp_path, "turn/start", "before-send")

    assert stat.S_IMODE(journal.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(journal.path(operation["operation_id"]).stat().st_mode) \
        == 0o600


def test_authenticated_raw_mutation_without_prepared_intent_is_rejected_safely(
        tmp_path):
    from test_codex_host_ipc import _envelope, _raw_call

    _module_value, client, log = _ensure(tmp_path)
    payload = {
        "method": "turn/start",
        "params": {"threadId": "thread-1", "input": [{"text": "secret"}]},
    }
    try:
        response = _raw_call(client, _envelope(
            client, "unprepared-operation", "rpc", payload))

        assert response["ok"] is False
        assert "prepared intent" in response["error"]
        assert client.call({"operation_id": "still-alive", "method": "ping",
                            "payload": {}}, timeout=1).result["generation"] \
            == client.generation
        assert _app_requests(log, "turn/start") == []
    finally:
        _shutdown(client)


def test_replacement_host_conservatively_reconciles_accepted_intent_before_ready(
        tmp_path):
    module = _module()
    home = tmp_path / "restart-home"
    (home / "state").mkdir(parents=True)
    journal = module.OperationJournal(home.resolve(), "old-generation")
    operation = _mutation("accepted-before-restart", "turn/steer")
    journal.prepare(operation)
    journal.accept(operation["operation_id"])

    _module_value, client, log = _ensure(tmp_path, home=home.resolve())
    try:
        record = json.loads(_operation_file(
            client, operation["operation_id"]).read_text())
        assert record["state"] == "uncertain"
        assert "observer unavailable" in record["reason"]
        assert _app_requests(log, "turn/steer") == []
        with pytest.raises(module.HostRejected, match="unresolved predecessor"):
            client.call(_mutation("must-not-bypass", "turn/start"), timeout=1)
        assert _app_requests(log, "turn/start") == []
        assert client.call({"operation_id": "restart-ping", "method": "ping",
                            "payload": {}}, timeout=1).result["generation"] \
            == client.generation
    finally:
        _shutdown(client)
