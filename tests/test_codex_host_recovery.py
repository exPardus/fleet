import json
import os
import stat

import pytest

from test_codex_host_ipc import _ensure, _shutdown


def test_restart_recovery_pages_complete_turn_history_without_items():
    import fleet_codex_host

    host = fleet_codex_host.Host.__new__(fleet_codex_host.Host)
    turns = [{"id": f"018f22d3-9b4a-7cc3-8a0e-{index:012x}",
              "status": "completed", "items": []}
             for index in range(65)]
    calls = []

    def request(method, params, _deadline):
        calls.append((method, dict(params)))
        start = int(params.get("cursor", "0"))
        end = start + params["limit"]
        return {"data": turns[start:end],
                "nextCursor": str(end) if end < len(turns) else None}

    host._recovery_request = request
    assert host._recovery_turns("thread-id", 1) == turns
    assert [params["limit"] for _, params in calls] == [32, 32, 32]
    assert all(method == "thread/turns/list"
               and params["itemsView"] == "notLoaded"
               and params["sortDirection"] == "desc"
               for method, params in calls)


def _module():
    try:
        import fleet_codex
    except ModuleNotFoundError:
        pytest.fail("bin/fleet_codex.py is not implemented")
    return fleet_codex


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
            "canonical_cwd": "/project",
            "history_watermark": 4,
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


def test_host_allows_only_linked_explicit_restore_after_observed_resume(
        tmp_path, monkeypatch):
    module, old_client, log = _ensure(tmp_path)
    assert old_client._owner_live()
    assert old_client._app_server_live()
    home = old_client.home
    journal = module.OperationJournal(home, old_client.generation)
    original = {
        "operation_id": "supervisor-reconcile-original", "method": "rpc",
        "payload": {"method": "thread/resume", "params": {
            "threadId": "thread-1", "excludeTurns": True}},
        "recovery": {
            "kind": "supervisor/thread-resume", "fleet_name": "sup|inc-1|boot",
            "incarnation_id": "inc-1", "thread_id": "thread-1",
            "previous_host_generation": "old-generation",
            "canonical_cwd": str(home),
        },
    }
    journal.prepare(original)
    journal.accept(original["operation_id"])
    journal.observe(original["operation_id"], {
        "thread": {"id": "thread-1", "cwd": str(home)},
        "cwd": str(home), "model": "gpt-5.6-luna",
        "approvalPolicy": "never", "approvalsReviewer": "user",
        "sandbox": {"type": "workspaceWrite", "writableRoots": []},
    })
    _shutdown(old_client)
    assert old_client.wait_for_exit(2)
    assert not old_client._owner_live()
    assert not old_client._app_server_live()
    monkeypatch.setattr(module, "HOST_HEARTBEAT_STALE_SECONDS", 0.0)
    _module_value, client, _new_log = _ensure(tmp_path, home=home)
    assert client.generation != old_client.generation
    restored = {
        "operation_id": "supervisor-restore-policy-next", "method": "rpc",
        "payload": {"method": "thread/resume", "params": {
            "threadId": "thread-1", "excludeTurns": True,
            "cwd": str(home), "model": "gpt-5.6-luna",
            "approvalPolicy": "never", "approvalsReviewer": "user",
            "sandbox": "danger-full-access",
        }},
        "recovery": {
            "kind": "supervisor/resume-policy-restore",
            "fleet_name": "sup|inc-1|boot", "incarnation_id": "inc-1",
            "thread_id": "thread-1", "turn_id": "turn-1",
            "previous_host_generation": "old-generation",
            "observed_resume_generation": old_client.generation,
            "original_resume_operation_id": original["operation_id"],
            "canonical_cwd": str(home),
        },
    }
    try:
        wrong = json.loads(json.dumps(restored))
        wrong["operation_id"] = "supervisor-restore-policy-wrong"
        wrong["recovery"]["original_resume_operation_id"] = "other-original"
        with pytest.raises(module.HostRejected, match="unresolved predecessor"):
            client.call(wrong, timeout=2)
        assert journal.load(wrong["operation_id"])["state"] == "failed"
        assert _app_requests(log, "thread/resume") == []

        response = client.call(restored, timeout=2)
        assert response.result["sandbox"] == {"type": "dangerFullAccess"}
        assert journal.load(original["operation_id"])["state"] == "observed"
        assert journal.load(restored["operation_id"])["state"] == "observed"
        assert len(_app_requests(log, "thread/resume")) == 1
        before_commit = {
            "operation_id": "supervisor-send-before-restore-commit",
            "method": "rpc",
            "payload": {"method": "turn/start", "params": {
                "threadId": "thread-1", "input": [{"text": "too early"}]}},
            "recovery": {"kind": "supervisor/turn/start",
                         "fleet_name": "sup|inc-1|boot",
                         "incarnation_id": "inc-1", "thread_id": "thread-1",
                         "previous_turn_id": "turn-1",
                         "canonical_cwd": str(home),
                         "restored_predecessor": {"uncommitted": True}},
        }
        with pytest.raises(module.HostRejected, match="unresolved predecessor"):
            client.call(before_commit, timeout=2)
        assert _app_requests(log, "turn/start") == []
        client.commit(restored["operation_id"])
        link = journal.restored_policy_link(
            fleet_name="sup|inc-1|boot", incarnation_id="inc-1",
            thread_id="thread-1")
        assert link["restore_operation_id"] == restored["operation_id"]
        mail = "first normal mail after policy restoration"
        next_turn = {
            "operation_id": "supervisor-send-next", "method": "rpc",
            "payload": {"method": "turn/start", "params": {
                "threadId": "thread-1",
                "input": [{"type": "text", "text": mail,
                           "text_elements": []}]}},
            "recovery": {
                "kind": "supervisor/turn/start",
                "fleet_name": "sup|inc-1|boot", "incarnation_id": "inc-1",
                "thread_id": "thread-1", "previous_turn_id": "turn-1",
                "canonical_cwd": str(home), "restored_predecessor": link,
            },
        }
        for index, changed in enumerate((
                {"restored_predecessor": None},
                {"restored_predecessor": {**link,
                                          "original_digest": "0" * 64}},
                {"incarnation_id": "wrong-incarnation"},
                {"canonical_cwd": "/wrong/home"},
        )):
            bad = json.loads(json.dumps(next_turn))
            bad["operation_id"] = f"supervisor-send-bad-link-{index}"
            bad["recovery"].update(changed)
            with pytest.raises(module.HostRejected, match="unresolved predecessor"):
                client.call(bad, timeout=2)
        assert _app_requests(log, "turn/start") == []
        next_result = client.call(next_turn, timeout=2)
        assert next_result.result["turn"]["status"] == "inProgress"
        assert len(_app_requests(log, "turn/start")) == 1
        client.commit(next_turn["operation_id"])
        assert journal.load(original["operation_id"])["state"] == "observed"
        assert journal.load(restored["operation_id"])["state"] == "committed"
        assert journal.load(next_turn["operation_id"])["state"] == "committed"
        _shutdown(client)
        assert client.wait_for_exit(2)
        monkeypatch.setattr(module, "HOST_HEARTBEAT_STALE_SECONDS", 0.0)
        _module_value, continued, _log = _ensure(tmp_path, home=home)
        try:
            reattach = {
                "operation_id": "supervisor-continuation-next",
                "method": "rpc",
                "payload": {"method": "thread/resume", "params": {
                    "threadId": "thread-1", "excludeTurns": True,
                    "cwd": str(home), "model": "gpt-5.6-luna",
                    "approvalPolicy": "never", "approvalsReviewer": "user",
                    "sandbox": "danger-full-access"}},
                "recovery": {
                    "kind": "supervisor/restored-continuation-reattach",
                    "fleet_name": "sup|inc-1|boot",
                    "incarnation_id": "inc-1", "thread_id": "thread-1",
                    "turn_id": "turn-1",
                    "previous_host_generation": client.generation,
                    "canonical_cwd": str(home), "restored_predecessor": link,
                },
            }
            assert continued.call(reattach, timeout=2).result["sandbox"] == {
                "type": "dangerFullAccess"}
            continued.commit(reattach["operation_id"])
            after_reattach = json.loads(json.dumps(next_turn))
            after_reattach["operation_id"] = "supervisor-send-after-reattach"
            assert continued.call(after_reattach, timeout=2).result[
                "turn"]["status"] == "inProgress"
            assert len(_app_requests(log, "turn/start")) == 2
            assert journal.load(original["operation_id"])["state"] == "observed"
            other = json.loads(json.dumps(after_reattach))
            other["operation_id"] = "other-accepted-predecessor"
            journal.prepare(other)
            journal.accept(other["operation_id"])
            blocked = json.loads(json.dumps(after_reattach))
            blocked["operation_id"] = "supervisor-send-with-other-accepted"
            with pytest.raises(module.HostRejected, match="unresolved predecessor"):
                continued.call(blocked, timeout=2)
            assert len(_app_requests(log, "turn/start")) == 2
        finally:
            _shutdown(continued)
    finally:
        _shutdown(client)
        assert client.wait_for_exit(2)


def test_provider_acceptance_with_lost_response_is_uncertain_and_never_replayed(
        tmp_path, monkeypatch):
    module, client, log = _ensure(
        tmp_path, env_overrides={"FAKE_DROP_TURN_RESPONSE": "1"})
    operation = _mutation("lost-provider-response", "turn/start")
    try:
        with pytest.raises(module.HostUnavailable, match="outcome is uncertain"):
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
