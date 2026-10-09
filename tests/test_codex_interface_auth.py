"""Process evidence for claim-bound native Codex Interface authority."""

import ctypes
import os
import struct
import sys
from pathlib import Path

import pytest
from types import SimpleNamespace

import fleet_codex
import fleet_platform


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
    monkeypatch.setattr(fleet_platform, "PLATFORM", SimpleNamespace(is_linux=True))
    monkeypatch.setattr(fleet_codex, "_linux_process_environment",
                        lambda pid: {"CODEX_THREAD_ID": THREAD})
    monkeypatch.setattr(fleet_codex, "_linux_process_record", records.get)

    assert fleet_codex.codex_process_source(30, THREAD) == {
        "thread_id": THREAD, "ancestor_pid": 20,
        "ancestor_start_identity": "boot-20", "ancestor_cwd": "/fleet",
        "uid": 1000,
    }


def test_wrong_thread_and_same_user_unrelated_process_refuse(monkeypatch):
    monkeypatch.setattr(fleet_platform, "PLATFORM", SimpleNamespace(is_linux=True))
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
    monkeypatch.setattr(fleet_platform, "PLATFORM", SimpleNamespace(is_linux=True))
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
    monkeypatch.setattr(fleet_platform, "PLATFORM", SimpleNamespace(is_linux=False))
    with pytest.raises(fleet_codex.HostRejected, match="unsupported"):
        fleet_codex.codex_process_source(30, THREAD)


def test_darwin_record_reads_kernel_fields_and_rechecks_start(monkeypatch, tmp_path):
    monkeypatch.setattr(fleet_platform, "PLATFORM",
                        SimpleNamespace(is_linux=False, is_darwin=True))
    identities = iter(["darwin:1.000001", "darwin:1.000001"])
    monkeypatch.setattr(fleet_codex, "_darwin_process_identity",
                        lambda _pid: next(identities))

    def fake_info(pid, flavor, buffer):
        assert pid == 30
        if flavor == 3:
            buffer.pid = 30
            buffer.ppid = 20
            buffer.uid = 501
            buffer.comm = b"codex"
        else:
            assert flavor == 9
            buffer.cwd.path = os.fsencode(tmp_path)
        return True

    monkeypatch.setattr(fleet_codex, "_darwin_proc_pidinfo", fake_info)
    assert fleet_codex._darwin_process_record(30) == {
        "pid": 30, "ppid": 20, "start_identity": "darwin:1.000001",
        "uid": 501, "comm": "codex", "cwd": str(tmp_path),
    }
    identities = iter(["darwin:1.000001", "darwin:1.000002"])
    assert fleet_codex._darwin_process_record(30) is None


def test_darwin_environment_parses_procargs2_only_for_same_uid(monkeypatch):
    monkeypatch.setattr(fleet_platform, "PLATFORM",
                        SimpleNamespace(is_linux=False, is_darwin=True))

    def fake_info(pid, flavor, buffer):
        assert (pid, flavor) == (30, 3)
        buffer.pid = pid
        buffer.uid = 501
        return True

    monkeypatch.setattr(fleet_codex, "_darwin_proc_pidinfo", fake_info)
    payload = (struct.pack("=i", 2) + b"/usr/bin/codex\0\0"
               + b"codex\0arg\0CODEX_THREAD_ID=" + THREAD.encode()
               + b"\0PATH=/usr/bin\0")

    def fake_sysctl(mib, length, oldp, oldlenp, newp, newlen):
        assert list(mib) == [1, 49, 30] and length == 3
        oldlenp._obj.value = len(payload)
        if oldp is not None:
            ctypes.memmove(oldp, payload, len(payload))
        return 0

    result = fleet_codex._darwin_process_environment(
        30, sysctl=fake_sysctl, owner_uid=501)
    assert result == {"CODEX_THREAD_ID": THREAD, "PATH": "/usr/bin"}
    assert fleet_codex._darwin_process_environment(
        30, sysctl=fake_sysctl, owner_uid=502) is None


def test_darwin_source_rechecks_process_after_environment(monkeypatch):
    monkeypatch.setattr(fleet_platform, "PLATFORM",
                        SimpleNamespace(is_linux=False, is_darwin=True))
    records = iter([_record(30, 20, start="darwin:1.000001"),
                    _record(30, 20, start="darwin:1.000002")])
    monkeypatch.setattr(fleet_codex, "_darwin_process_record",
                        lambda _pid: next(records))
    monkeypatch.setattr(fleet_codex, "_darwin_process_environment",
                        lambda _pid: {"CODEX_THREAD_ID": THREAD})
    with pytest.raises(fleet_codex.HostRejected, match="changed during authentication"):
        fleet_codex.codex_process_source(30, THREAD)


def test_darwin_source_binds_nearest_codex_ancestor(monkeypatch):
    monkeypatch.setattr(fleet_platform, "PLATFORM",
                        SimpleNamespace(is_linux=False, is_darwin=True))
    records = {30: _record(30, 20),
               20: _record(20, 1, comm="codex", start="darwin:1.000001")}
    monkeypatch.setattr(fleet_codex, "_darwin_process_record", records.get)
    monkeypatch.setattr(fleet_codex, "_darwin_process_environment",
                        lambda _pid: {"CODEX_THREAD_ID": THREAD})
    assert fleet_codex.codex_process_source(30, THREAD) == {
        "thread_id": THREAD, "ancestor_pid": 20,
        "ancestor_start_identity": "darwin:1.000001",
        "ancestor_cwd": "/fleet", "uid": 1000,
    }


@pytest.mark.skipif(sys.platform != "darwin", reason="requires Darwin kernel")
def test_darwin_current_process_smoke():
    record = fleet_codex._darwin_process_record(os.getpid())
    environment = fleet_codex._darwin_process_environment(os.getpid())
    assert record is not None
    assert record["pid"] == os.getpid()
    assert record["uid"] == os.getuid()
    assert Path(record["cwd"]).resolve() == Path.cwd().resolve()
    assert environment is not None and environment["PATH"]
