"""Claude workspace trust is accepted only at native launch boundaries."""
import json
import os
import pytest

import fleet

REAL_HOME = os.path.realpath(os.path.expanduser("~"))


def test_new_directory_trusted_and_existing_data_preserved(tmp_path, monkeypatch):
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    path = config_dir / ".claude.json"
    path.write_text(json.dumps({"other": {"keep": 1}, "projects": {
        "/already": {"hasTrustDialogAccepted": True, "x": 2}}}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    target = tmp_path / "new-lane"
    target.mkdir()

    fleet._ensure_claude_directory_trusted(target)

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["other"] == {"keep": 1}
    assert result["projects"]["/already"] == {"hasTrustDialogAccepted": True, "x": 2}
    assert result["projects"][str(target.resolve())] == {"hasTrustDialogAccepted": True}


def test_trust_write_is_idempotent(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    target = tmp_path / "lane"
    target.mkdir()
    fleet._ensure_claude_directory_trusted(target)
    path = config_dir / ".claude.json"
    first = path.read_bytes()
    fleet._ensure_claude_directory_trusted(target)
    assert path.read_bytes() == first


def test_corrupt_config_is_untouched_and_reports_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    path = config_dir / ".claude.json"
    path.write_text('{"broken":', encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    with pytest.raises(fleet.FleetCliError, match="cannot accept Claude workspace trust"):
        fleet._ensure_claude_directory_trusted(tmp_path)
    assert path.read_bytes() == before


def test_default_config_uses_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "workspace"
    target.mkdir()

    fleet._ensure_claude_directory_trusted(target)

    assert json.loads((tmp_path / ".claude.json").read_text())["projects"][
        str(target.resolve())]["hasTrustDialogAccepted"] is True


def test_pytest_trust_writer_cannot_resolve_real_home(tmp_path, monkeypatch):
    """The suite fixture redirects both Claude config and HOME before writes."""
    config_dir = os.path.realpath(os.environ["CLAUDE_CONFIG_DIR"])
    assert config_dir != REAL_HOME
    assert os.path.commonpath((config_dir, REAL_HOME)) != REAL_HOME
    target = tmp_path / "guarded-workspace"
    target.mkdir()
    real_replace = os.replace

    def guarded_replace(source, destination):
        destination = os.path.realpath(destination)
        assert destination != os.path.join(REAL_HOME, ".claude.json")
        assert os.path.commonpath((destination, str(tmp_path.resolve()))) == str(tmp_path.resolve())
        return real_replace(source, destination)

    monkeypatch.setattr(fleet.os, "replace", guarded_replace)
    fleet._ensure_claude_directory_trusted(target)
    assert os.path.exists(os.path.join(config_dir, ".claude.json"))
