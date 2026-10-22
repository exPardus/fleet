"""Observable file-only behavior of the Codex footer adapter."""

import importlib.util
import sys
from pathlib import Path


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))


def _helper():
    spec = importlib.util.spec_from_file_location(
        "fleet_codex_statusline", BIN / "fleet_codex_statusline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explicit_home_uses_only_snapshot_and_plain_renderer(tmp_path, monkeypatch, capsys):
    helper = _helper()
    seen = []

    def snapshot():
        seen.append(("snapshot", helper.fleet.FLEET_HOME))
        return {"ok": False, "reason": "missing"}

    def render(value, *, color):
        seen.append(("render", value, color))
        return "[fleet] safe\nignored"

    monkeypatch.setattr(helper.fleet, "status_snapshot", snapshot)
    monkeypatch.setattr(helper.fleet_statusline, "render_statusline", render)
    assert helper.main(["--fleet-home", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "[fleet] safe\n"
    assert seen == [("snapshot", tmp_path), ("render", {"ok": False, "reason": "missing"}, False)]
    assert list(tmp_path.iterdir()) == []


def test_no_implicit_install_home_and_corrupt_state_degrades(tmp_path, monkeypatch, capsys):
    helper = _helper()
    monkeypatch.delenv("FLEET_HOME", raising=False)
    assert helper.main([]) == 0
    assert capsys.readouterr().out == "fleet unavailable\n"

    corrupt = tmp_path / "state"
    corrupt.mkdir()
    registry = corrupt / "fleet.json"
    registry.write_text("{broken", encoding="utf-8")
    before = registry.read_bytes()
    assert helper.main(["--fleet-home", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip()
    assert registry.read_bytes() == before
    assert sorted(p.name for p in corrupt.iterdir()) == ["fleet.json"]


def test_bad_snapshot_is_bounded_and_exits_zero(tmp_path, monkeypatch, capsys):
    helper = _helper()
    def bad_snapshot():
        raise RuntimeError("private state path and traceback must not leak")
    monkeypatch.setattr(helper.fleet, "status_snapshot", bad_snapshot)
    assert helper.main(["--fleet-home", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "fleet unavailable\n"


def test_malformed_cli_input_degrades_without_touching_home(tmp_path, capsys):
    helper = _helper()
    assert helper.main(["--fleet-home", str(tmp_path), "--unexpected"]) == 0
    assert capsys.readouterr().out == "fleet unavailable\n"
    assert list(tmp_path.iterdir()) == []
