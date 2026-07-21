"""Unit tests for steering surfaces that survived the native-substrate
pivot: append_mailbox, release, and the platform-adapter boundary lint
(SPEC §5, §9, §14). The legacy Popen send/interrupt/attach state machines
were deleted with the legacy dispatch path (pivot spec §6, M-C); their
native counterparts are covered in test_native.py.

Every test monkeypatches fleet.FLEET_HOME to a pytest tmp_path.
"""
import ast
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet


def _blank_out_function(source: str, func_name: str) -> str:
    """`source` with the body of top-level `func_name` replaced by blank
    lines. Used by the platform-adapter lint to excise its ONE sanctioned
    exemption without exempting the whole file.

    Parsed with `ast` rather than matched with a regex: an indentation-based
    text scan would mis-slice on a decorator, a multi-line signature or a
    docstring containing `def `, and this excision is what decides whether a
    real OS branch is reported. Raises if the function is absent, so a
    renamed exemption is a loud failure, not a silent no-op."""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            lines = source.splitlines(keepends=True)
            # ast line numbers are 1-based and inclusive on both ends.
            for i in range(node.lineno - 1, node.end_lineno):
                lines[i] = "\n"
            return "".join(lines)
    raise AssertionError(f"no top-level def {func_name}() to exempt")


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

    # Invariant 8 (SPEC §16.8): OS branching lives in the platform adapter,
    # and nowhere else.
    #
    # posix-port campaign, follow-up 1: this lint used to name TWO files by
    # hand (`bin/fleet_statusline.py`, `bin/hooks/sessionstart_fleet.py`) and
    # `continue` past a missing one. It therefore did not scan `bin/hooks/`
    # as a directory at all, nor `tools/`. `bin/hooks/stop_outcome.py`
    # already carries its own `os.name` branch -- legitimately: a hook may
    # not import `fleet.py` (standalone doctrine), so it cannot reach
    # `PLATFORM` and must duplicate the two-branch atomic append. That makes
    # it a SANCTIONED SECOND SITE, but nothing stopped a THIRD from
    # appearing in any hook the list did not happen to name.
    #
    # Now every product `.py` under `bin/` and `tools/` is scanned by glob,
    # so a new file is covered the moment it lands. `bin/fleet.py` is
    # excluded here only because the fence-based test above covers it more
    # precisely. `tests/` is deliberately out of scope: a test may branch on
    # the host it runs on -- that is how the adapter's two declarations get
    # exercised on both platforms.

    _OS_BRANCH_NEEDLES = ("os.name", "sys.platform", "platform.system",
                          "sys.getwindowsversion", "os.uname", "os.sep")

    # The single named exemption. Scoped to ONE function in ONE file, not to
    # the whole file, so a second branch elsewhere in stop_outcome.py still
    # fails.
    _SANCTIONED_SECOND_SITE = ("bin/hooks/stop_outcome.py", "_atomic_append_bytes")

    @staticmethod
    def _repo_root():
        return Path(fleet.__file__).resolve().parent.parent

    @classmethod
    def _scanned_files(cls):
        root = cls._repo_root()
        paths = sorted(set(root.glob("bin/**/*.py")) | set(root.glob("tools/**/*.py")))
        return [p for p in paths if p != (root / "bin" / "fleet.py")]

    def test_lint_actually_covers_the_hook_and_tool_directories(self):
        """A lint that silently scans nothing passes. Pin the file set, so
        deleting the glob (or moving the hooks) fails here rather than
        quietly disarming every assertion below."""
        root = self._repo_root()
        scanned = {p.relative_to(root).as_posix() for p in self._scanned_files()}
        assert {"bin/fleet_statusline.py",
                "bin/hooks/sessionstart_fleet.py",
                "bin/hooks/stop_outcome.py",
                "bin/hooks/stop_mailbox.py",
                "bin/hooks/posttooluse_mailbox.py",
                "bin/hooks/postcompact_journal.py",
                "tools/verify_receipts.py"} <= scanned, scanned

    def test_no_os_branches_in_bin_or_tools_outside_the_one_exemption(self):
        root = self._repo_root()
        exempt_rel, exempt_func = self._SANCTIONED_SECOND_SITE
        for path in self._scanned_files():
            rel = path.relative_to(root).as_posix()
            source = path.read_text(encoding="utf-8")
            if rel == exempt_rel:
                source = _blank_out_function(source, exempt_func)
            for needle in self._OS_BRANCH_NEEDLES:
                assert needle not in source, (
                    f"found {needle!r} in {rel} -- OS branching belongs in "
                    f"bin/fleet.py's PLATFORM adapter (SPEC §16.8). The only "
                    f"sanctioned second site is {exempt_rel}::{exempt_func}, "
                    f"which cannot import fleet.py.")

    def test_the_exemption_is_still_a_real_function_that_still_branches(self):
        """An exemption that no longer matches anything is dead weight that
        reads as coverage. Three ways it can go stale, all caught here:
        `_atomic_append_bytes` is renamed or removed (`_blank_out_function`
        raises), the file stops branching at all (first assert -- the
        exemption should then be DELETED, not left standing), or the branch
        moves out of the exempted function (second assert)."""
        root = self._repo_root()
        exempt_rel, exempt_func = self._SANCTIONED_SECOND_SITE
        source = (root / exempt_rel).read_text(encoding="utf-8")
        blanked = _blank_out_function(source, exempt_func)
        assert "os.name" in source, (
            f"{exempt_rel} no longer branches on os.name at all -- delete the "
            f"exemption rather than leaving it to exempt nothing")
        assert "os.name" not in blanked, (
            f"{exempt_rel} branches on os.name OUTSIDE {exempt_func} -- the "
            f"exemption covers that one function only, by design")

    def test_correct_adapter_selected_on_this_machine(self):
        expected = (fleet._WindowsPlatform if os.name == "nt"
                    else fleet._PosixPlatform)
        assert isinstance(fleet.PLATFORM, expected)

    def test_unsupported_platform_error_is_not_implemented_error(self):
        assert issubclass(fleet.UnsupportedPlatformError, NotImplementedError)
