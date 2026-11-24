"""The statusline is a hot path: one refresh must not parse a registry twice.

Views may not write (tests/test_views_doctrine.py), so the statusline cannot
cache across refreshes. These pins hold the in-process savings: each
registry is parsed once per refresh, the sid lookup runs once, and the Codex
wait summary does not import the Codex adapter when its store is absent.
"""
import json
import os

import pytest

import fleet
import fleet_statusline


@pytest.fixture
def restore_fleet(monkeypatch):
    monkeypatch.setattr(fleet, "read_registry_at", fleet.read_registry_at)
    monkeypatch.setattr(fleet, "lookup_home_for_sid", fleet.lookup_home_for_sid)


def _home(tmp_path, name, workers):
    home = tmp_path / name
    (home / "state").mkdir(parents=True)
    (home / "state" / "fleet.json").write_text(
        json.dumps({"workers": workers}), encoding="utf-8")
    return home


def test_each_registry_is_parsed_once_per_refresh(tmp_path, monkeypatch,
                                                  restore_fleet):
    home = _home(tmp_path, "a", {"w1": {"session_id": "sid-1"}})
    calls = []
    real = fleet.read_registry_at
    monkeypatch.setattr(fleet, "read_registry_at",
                        lambda h: calls.append(h) or real(h))
    fleet_statusline.memoize_registry_reads()
    first = fleet.read_registry_at(home)
    second = fleet.read_registry_at(home)
    assert first == second and first[0] is True
    assert len(calls) == 1


def test_a_registry_rewritten_mid_refresh_is_read_again(tmp_path, restore_fleet):
    home = _home(tmp_path, "a", {"w1": {"session_id": "sid-1"}})
    fleet_statusline.memoize_registry_reads()
    assert list(fleet.read_registry_at(home)[2]["workers"]) == ["w1"]
    path = home / "state" / "fleet.json"
    path.write_text(json.dumps({"workers": {"w2": {"session_id": "sid-2"}}}),
                    encoding="utf-8")
    stamp = path.stat().st_mtime_ns + 1_000_000
    os.utime(path, ns=(stamp, stamp))
    assert list(fleet.read_registry_at(home)[2]["workers"]) == ["w2"]


def test_the_sid_lookup_runs_once_and_hands_out_copies(tmp_path, monkeypatch,
                                                      restore_fleet):
    home_a = _home(tmp_path, "a", {"w1": {"session_id": "sid-1"}})
    home_b = _home(tmp_path, "b", {})
    population = {"homes": [str(home_a), str(home_b)], "legacy": str(home_b),
                  "list_ok": True, "list_reason": None}
    calls = []
    real = fleet.lookup_home_for_sid
    monkeypatch.setattr(fleet, "lookup_home_for_sid",
                        lambda *a, **k: calls.append(a) or real(*a, **k))
    fleet_statusline.memoize_registry_reads()
    first = fleet.lookup_home_for_sid("sid-1", population=population)
    first["hits"].append("mutated")
    second = fleet.lookup_home_for_sid("sid-1", population=population)
    assert len(calls) == 1
    assert second["state"] == "hit" and "mutated" not in second["hits"]
    fleet.lookup_home_for_sid("sid-other", population=population)
    assert len(calls) == 2


def test_memoizing_twice_does_not_stack_wrappers(restore_fleet):
    fleet_statusline.memoize_registry_reads()
    inner = fleet.read_registry_at.__wrapped__
    fleet_statusline.memoize_registry_reads()
    assert fleet.read_registry_at.__wrapped__ is inner


NATIVE = {"substrate": "codex", "dispatch_kind": "codex-app-server",
          "session_id": None, "codex_thread_id": "thread-1",
          "codex_turn_id": "turn-1"}


def test_absent_wait_store_skips_the_codex_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    import fleet_codex
    monkeypatch.setattr(fleet_codex, "read_pending_requests",
                        lambda *a, **k: pytest.fail("adapter must not be read"))
    store = {}
    assert fleet._codex_wait_summaries(dict(NATIVE), store) == []
    assert fleet._codex_wait_summaries(dict(NATIVE), store) == []


def test_present_wait_store_is_still_read_per_row(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state" / "codex" / "approvals").mkdir(parents=True)
    import fleet_codex
    seen = []
    monkeypatch.setattr(fleet_codex, "read_pending_requests",
                        lambda *a, **k: seen.append(a) or [])
    assert fleet._codex_wait_summaries(dict(NATIVE), {}) == []
    assert len(seen) == 1


@pytest.mark.skipif(os.name == "nt", reason="symlink creation")
def test_a_symlinked_home_still_reaches_the_adapter_check(tmp_path, monkeypatch):
    """The adapter refuses a home path with a symlink; never hide that."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setattr(fleet, "FLEET_HOME", link)
    summaries = fleet._codex_wait_summaries(dict(NATIVE), {})
    assert summaries and summaries[0]["state"] == "unreadable"


def _approvals(tmp_path, mode=0o700):
    directory = tmp_path / "state" / "codex" / "approvals"
    directory.mkdir(parents=True)
    directory.chmod(mode)
    return directory


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_an_empty_safe_wait_store_skips_the_codex_adapter(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    _approvals(tmp_path)
    import fleet_codex
    monkeypatch.setattr(fleet_codex, "read_pending_requests",
                        lambda *a, **k: pytest.fail("adapter must not be read"))
    assert fleet._codex_wait_summaries(dict(NATIVE), {}) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
@pytest.mark.parametrize("unsafe", ["mode", "entry"])
def test_an_unsafe_or_nonempty_wait_store_still_reaches_the_adapter(
        tmp_path, monkeypatch, unsafe):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    directory = _approvals(tmp_path, 0o755 if unsafe == "mode" else 0o700)
    if unsafe == "entry":
        (directory / "k.json").write_text("{}", encoding="utf-8")
    import fleet_codex
    seen = []
    monkeypatch.setattr(fleet_codex, "read_pending_requests",
                        lambda *a, **k: seen.append(a) or [])
    fleet._codex_wait_summaries(dict(NATIVE), {})
    assert len(seen) == 1
