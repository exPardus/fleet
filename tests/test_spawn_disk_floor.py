"""`fleet spawn` refuses below a free-disk floor on the lane dir's filesystem.

A full disk stalls every lane on the host at once (ENOSPC in tests, git and
docker). The default floor is 6 GB, 8 GB for a docker-heavy lane
(`--disk-heavy` or `--category docker`); `state/config.json` "gc" can change
or disable either.
"""
import json
from types import SimpleNamespace

import pytest

import fleet


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    monkeypatch.setattr(fleet, "DISK_FLOOR_GB_DEFAULT", 6)
    monkeypatch.setattr(fleet, "DISK_FLOOR_HEAVY_GB_DEFAULT", 8)
    (tmp_path / "state").mkdir()
    return tmp_path


def _free(monkeypatch, gb):
    seen = []
    monkeypatch.setattr(fleet, "_watch_free_disk_gb",
                        lambda path: seen.append(path) or gb)
    return seen


def _config(home, **gc):
    (home / "state" / "config.json").write_text(json.dumps({"gc": gc}))


@pytest.mark.parametrize("free, heavy, refused", [
    (5.9, False, True), (6.0, False, False), (7.5, False, False),
    (7.5, True, True), (8.0, True, False)])
def test_the_default_floors(home, monkeypatch, free, heavy, refused):
    _free(monkeypatch, free)
    text = fleet._disk_floor_refusal(home, heavy=heavy)
    assert (text is not None) is refused
    if refused:
        key = "min_free_disk_gb_heavy" if heavy else "min_free_disk_gb"
        assert f"gc.{key}" in text and f"{free:.1f} GB free" in text


def test_the_floor_is_measured_on_the_lane_dir_filesystem(home, monkeypatch,
                                                          tmp_path):
    seen = _free(monkeypatch, 100)
    lane = tmp_path / "lanes" / "w1" / "not-yet-created"
    (tmp_path / "lanes").mkdir()
    fleet._disk_floor_refusal(lane)
    assert seen == [tmp_path / "lanes"]


def test_config_changes_or_disables_the_floors(home, monkeypatch):
    _free(monkeypatch, 3)
    _config(home, min_free_disk_gb=2, min_free_disk_gb_heavy=0)
    assert fleet._disk_floor_refusal(home) is None
    assert fleet._disk_floor_refusal(home, heavy=True) is None
    _config(home, min_free_disk_gb=4)
    assert fleet._disk_floor_refusal(home) is not None


def test_an_unreadable_measurement_never_refuses(home, monkeypatch):
    _free(monkeypatch, None)
    assert fleet._disk_floor_refusal(home, heavy=True) is None


def _spawn_args(lane, **over):
    base = dict(name="w1", dir=str(lane), task="t", mode="accept", model=None,
                effort="medium", codex_adapter=None, max_budget_usd=None,
                setting_sources=None, token_ceiling=None, category=None,
                nonce=None, force_band=False, context=None, spec=None,
                slice=None, disk_heavy=False)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("over, free, refused", [
    ({}, 7.0, False),
    ({"disk_heavy": True}, 7.0, True),
    ({"category": "docker"}, 7.0, True),
    ({"category": "research"}, 7.0, False),
    ({}, 5.0, True),
])
def test_spawn_applies_the_floor_before_any_dispatch(home, monkeypatch, tmp_path,
                                                     over, free, refused):
    _free(monkeypatch, free)
    lane = tmp_path / "lane"
    lane.mkdir()
    dispatched = []

    class PastTheFloor(Exception):
        pass

    def stop_here():
        dispatched.append("past-floor")
        raise PastTheFloor

    monkeypatch.setattr(fleet, "_require_instance_settings", stop_here)
    monkeypatch.setattr(fleet, "_memory_budget_refusal", lambda **k: None)
    monkeypatch.setattr(fleet, "_ceiling_refuses_dispatch", lambda *a, **k: None)
    monkeypatch.setattr(fleet, "_supervisor_gate", lambda *a, **k: None)
    if refused:
        with pytest.raises(fleet.FleetCliError, match="min_free_disk_gb"):
            fleet.cmd_spawn(_spawn_args(lane, **over))
        assert dispatched == []
    else:
        with pytest.raises(PastTheFloor):
            fleet.cmd_spawn(_spawn_args(lane, **over))
        assert dispatched == ["past-floor"]


def test_the_parser_ships_the_heavy_flag():
    args = fleet.build_parser().parse_args(
        ["spawn", "w1", "--dir", ".", "--task", "t", "--disk-heavy"])
    assert args.disk_heavy is True
