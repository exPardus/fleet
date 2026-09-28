"""w105 defect-sweep pins.

1. `fleet clean --dead-only` on a dead row whose path AND sid are null (a
   hand-edited or half-written row: `cwd`, `session_id`, `task`,
   `retired_sids` all null). w103 fixed the null-sid half; this pins the
   whole-row case so a later path-keyed sweep cannot regress it.
"""
import argparse
import json
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    for sub in ("state", "logs", "mailbox"):
        (tmp_path / sub).mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    fleet.save_registry({"workers": {}})
    monkeypatch.setattr(fleet, "current_caller_session", lambda: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    return tmp_path


def test_clean_dead_only_survives_a_row_with_null_path_and_sid(home, capsys):
    data = fleet.load_registry()
    data["workers"]["null-row"] = {
        "status": "dead", "session_id": None, "cwd": None, "task": None,
        "retired_sids": None, "archived_at": None, "dispatch_kind": "bg",
        "last_activity": None, "branch": None,
    }
    fleet.save_registry(data)

    rc = fleet.cmd_clean(
        argparse.Namespace(yes=True, dead_only=True, tombstones=False),
        run=lambda argv, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps([]), stderr=""),
        which=lambda _: "claude")

    assert rc == 0
    assert "null-row" not in fleet.load_registry()["workers"]
    assert "removed null-row" in capsys.readouterr().out
