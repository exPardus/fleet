"""Unit tests for steering surfaces that survived the native-substrate
pivot: append_mailbox, release, and the platform-adapter boundary lint
(SPEC §5, §9, §14). The legacy Popen send/interrupt/attach state machines
were deleted with the legacy dispatch path (pivot spec §6, M-C); their
native counterparts are covered in test_native.py.

Every test monkeypatches fleet.FLEET_HOME to a pytest tmp_path.
"""
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    # SPEC §14: cmd_send's idle-resume path now refuses to launch a turn
    # unless the worker-settings.json instance has been rendered (`fleet
    # init`). Pre-provision a stub instance here so existing send tests
    # don't need to know about that precondition; the dedicated
    # missing-instance test deletes this file first.
    settings = tmp_path / "state" / "worker-settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("{}", encoding="utf-8")
    return tmp_path


def _parse(ctime_iso):
    return datetime.strptime(ctime_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


ALIVE_CTIME = "2026-07-07T12:00:00Z"


# ---------------------------------------------------------------------------
# append_mailbox
# ---------------------------------------------------------------------------

class TestAppendMailbox:
    def test_creates_mailbox_file(self, isolated_home):
        fleet.append_mailbox("sid-1", "hello")
        content = (fleet.mailbox_dir() / "sid-1.md").read_text(encoding="utf-8")
        assert "hello" in content

    def test_accumulates_multiple_sends(self, isolated_home):
        fleet.append_mailbox("sid-1", "first")
        fleet.append_mailbox("sid-1", "second")
        content = (fleet.mailbox_dir() / "sid-1.md").read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content
        assert content.index("first") < content.index("second")


def _seed_worker(name, status=None):
    """Save a single native-shaped worker registry record."""
    sid = str(uuid.uuid4())
    rec = fleet.new_worker_record(sid, str(fleet.FLEET_HOME), "some task",
                                  "dontask", dispatch_kind="bg")
    if status is not None:
        rec["status"] = status
    fleet.save_registry({"workers": {name: rec}})
    return sid, rec


# ---------------------------------------------------------------------------
# fleet release
# ---------------------------------------------------------------------------

class TestCmdRelease:
    def test_attached_to_idle_clears_attached_since(self, isolated_home):
        _seed_worker("probe-1", status="attached")
        data = fleet.load_registry()
        data["workers"]["probe-1"]["attached_since"] = fleet.now_iso()
        fleet.save_registry(data)

        args = fleet.build_parser().parse_args(["release", "probe-1"])
        rc = fleet.cmd_release(args)

        assert rc == 0
        rec = fleet.load_registry()["workers"]["probe-1"]
        assert rec["status"] == "idle"
        assert rec["attached_since"] is None

    def test_not_attached_warns_noop(self, isolated_home, capsys):
        _seed_worker("probe-1", status="idle")
        args = fleet.build_parser().parse_args(["release", "probe-1"])
        rc = fleet.cmd_release(args)
        assert rc == 0
        assert "not attached" in capsys.readouterr().out
        assert fleet.load_registry()["workers"]["probe-1"]["status"] == "idle"

    def test_unknown_worker_raises(self, isolated_home):
        args = fleet.build_parser().parse_args(["release", "nope"])
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_release(args)


# ---------------------------------------------------------------------------
# Platform adapter boundary (SPEC §14)
# ---------------------------------------------------------------------------

class TestPlatformAdapterBoundary:
    def test_no_os_branches_outside_adapter_block(self):
        source = Path(fleet.__file__).read_text(encoding="utf-8")
        start = source.index("# === PLATFORM ADAPTER START")
        end = source.index("# === PLATFORM ADAPTER END") + len("# === PLATFORM ADAPTER END ===")
        assert start != -1 and end != -1
        outside = source[:start] + source[end:]
        # F7: broadened beyond os.name/sys.platform to also reject every
        # other OS-branching surface an adapter method could smuggle in.
        for needle in (
            "os.name", "sys.platform", "platform.system",
            "sys.getwindowsversion", "os.uname", "os.sep",
        ):
            assert needle not in outside, f"found {needle!r} outside the platform adapter block"

    def test_new_surface_scripts_have_no_os_branches(self):
        # Phase 1.6: invariant 8 stays lint-enforced as the file set grows.
        root = Path(fleet.__file__).resolve().parent.parent
        for rel in ("bin/fleet_statusline.py", "bin/hooks/sessionstart_fleet.py"):
            path = root / rel
            if not path.exists():
                continue  # added by a later task in the terminal-surface plan
            source = path.read_text(encoding="utf-8")
            for needle in ("os.name", "sys.platform", "platform.system",
                           "sys.getwindowsversion", "os.uname", "os.sep"):
                assert needle not in source, f"found {needle!r} in {rel}"

    def test_correct_adapter_selected_on_this_machine(self):
        expected = (fleet._WindowsPlatform if os.name == "nt"
                    else fleet._PosixPlatform)
        assert isinstance(fleet.PLATFORM, expected)

    def test_unsupported_platform_error_is_not_implemented_error(self):
        assert issubclass(fleet.UnsupportedPlatformError, NotImplementedError)
