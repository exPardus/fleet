"""Linux process evidence for claim-bound native Codex Interface authority."""

import pytest

import fleet_codex


THREAD = "018f22d3-9b4a-7cc3-8a0e-36d4f59106c1"


def _record(pid, ppid, *, comm="zsh", start=None, cwd="/fleet"):
    return {"pid": pid, "ppid": ppid, "start_identity": start or str(pid),
            "uid": 1000, "comm": comm, "cwd": cwd}


def test_source_binds_thread_to_nearest_codex_ancestor(monkeypatch):
    records = {
        30: _record(30, 20),
        20: _record(20, 10, comm="codex", start="boot-20"),
        10: _record(10, 1, comm="codex", start="boot-10"),
    }
    monkeypatch.setattr(fleet_codex.sys, "platform", "linux")
    monkeypatch.setattr(fleet_codex, "_linux_process_environment",
                        lambda pid: {"CODEX_THREAD_ID": THREAD})
    monkeypatch.setattr(fleet_codex, "_linux_process_record", records.get)

    assert fleet_codex.codex_process_source(30, THREAD) == {
        "thread_id": THREAD, "ancestor_pid": 20,
        "ancestor_start_identity": "boot-20", "ancestor_cwd": "/fleet",
        "uid": 1000,
    }


def test_wrong_thread_and_same_user_unrelated_process_refuse(monkeypatch):
    monkeypatch.setattr(fleet_codex.sys, "platform", "linux")
    monkeypatch.setattr(fleet_codex, "_linux_process_environment",
                        lambda pid: {"CODEX_THREAD_ID": THREAD})
    monkeypatch.setattr(fleet_codex, "_linux_process_record",
                        lambda pid: _record(pid, 1))

    with pytest.raises(fleet_codex.HostRejected, match="thread does not match"):
        fleet_codex.codex_process_source(30, THREAD[:-1] + "2")
    with pytest.raises(fleet_codex.HostRejected, match="no verifiable"):
        fleet_codex.codex_process_source(30, THREAD)


def test_forked_codex_after_claim_and_reused_pid_do_not_match(monkeypatch):
    records = {
        31: _record(31, 20, comm="codex", start="fork-after-claim"),
        20: _record(20, 1, comm="codex", start="original"),
    }
    monkeypatch.setattr(fleet_codex.sys, "platform", "linux")
    monkeypatch.setattr(fleet_codex, "_linux_process_environment",
                        lambda pid: {"CODEX_THREAD_ID": THREAD})
    monkeypatch.setattr(fleet_codex, "_linux_process_record", records.get)
    source = fleet_codex.codex_process_source(31, THREAD)
    claim = {"thread_id": THREAD, "ancestor_pid": 20,
             "ancestor_start_identity": "original", "uid": 1000}
    assert not fleet_codex.interface_source_matches(claim, source)

    reused = dict(source, ancestor_pid=20,
                  ancestor_start_identity="replacement")
    assert not fleet_codex.interface_source_matches(claim, reused)


def test_unsupported_platform_fails_closed(monkeypatch):
    monkeypatch.setattr(fleet_codex.sys, "platform", "win32")
    with pytest.raises(fleet_codex.HostRejected, match="unsupported"):
        fleet_codex.codex_process_source(30, THREAD)
