"""Native-default migration remains record-local and reversible for new rows."""

from types import SimpleNamespace

import pytest

import fleet


def _native_row(**updates):
    row = {
        "substrate": "codex", "dispatch_kind": "codex-app-server",
        "session_id": None, "mcx_id": None,
        "codex_thread_id": "018f22d3-9b4a-7cc3-8a0e-36d4f59106b7",
        "adapter_state": "idle", "status": "idle",
    }
    row.update(updates)
    return row


def _mcx_row(**updates):
    row = {
        "substrate": "codex", "dispatch_kind": "mcx",
        "session_id": None, "mcx_id": "1234abcd", "status": "idle",
    }
    row.update(updates)
    return row


def test_adapter_route_is_persisted_per_row_not_the_new_default():
    assert fleet._codex_record_route(_native_row()) == "native"
    assert fleet._codex_record_route(_mcx_row()) == "mcx"


def test_mixed_row_refuses_before_either_adapter_runs(monkeypatch):
    row = _native_row(mcx_id="1234abcd")
    monkeypatch.setattr(
        fleet, "_codex_worker_binding",
        lambda *_args, **_kwargs: pytest.fail("mixed row reached native"))
    monkeypatch.setattr(
        fleet, "_mcx_run",
        lambda *_args, **_kwargs: pytest.fail("mixed row reached mcx"))

    with pytest.raises(fleet.FleetCliError, match="invalid mixed Codex record"):
        fleet._cmd_result_codex("mixed", row)


def test_doctor_censuses_both_adapters_without_cross_routing():
    workers = {"native": _native_row(), "legacy": _mcx_row()}

    name, ok, detail = fleet._doctor_check_codex_adapters(
        workers, which=lambda helper: f"/bin/{helper}")

    assert name == "codex-adapters"
    assert ok is True
    assert "native=1" in detail
    assert "mcx=1" in detail
    assert "invalid=0" in detail
    assert fleet._doctor_check_legacy_mix(workers) == (
        "legacy-mix", True, "no pre-pivot workers")


def test_doctor_fails_on_mixed_rows_and_missing_required_helper():
    workers = {
        "native": _native_row(),
        "mixed": _native_row(mcx_id="1234abcd"),
        "legacy": _mcx_row(),
    }

    name, ok, detail = fleet._doctor_check_codex_adapters(
        workers, which=lambda helper: None if helper == "mcx" else "/bin/codex")

    assert name == "codex-adapters"
    assert ok is False
    assert "mixed" in detail
    assert "mcx helper unavailable" in detail


def test_doctor_reports_missing_native_helper_for_native_rows():
    name, ok, detail = fleet._doctor_check_codex_adapters(
        {"native": _native_row()},
        which=lambda helper: None if helper == "codex" else "/bin/mcx")

    assert name == "codex-adapters"
    assert ok is False
    assert "codex helper unavailable" in detail


def test_doctor_check_is_registered_in_the_cli(monkeypatch, capsys):
    seen = []

    def check(workers, which=None):
        seen.append(dict(workers))
        return "codex-adapters", True, "native=0 mcx=0 invalid=0"

    monkeypatch.setattr(fleet, "_doctor_check_codex_adapters", check)
    monkeypatch.setattr(
        fleet, "read_registry_no_repair", lambda **_kwargs: {"workers": {}})
    monkeypatch.setattr(
        fleet, "_doctor_check_claude_version",
        lambda **_kwargs: ("claude-on-path", True, "stub"))

    fleet.cmd_doctor(SimpleNamespace(repair=False), which=lambda _name: None)

    assert seen == [{}]
    assert "[PASS] codex-adapters:" in capsys.readouterr().out
