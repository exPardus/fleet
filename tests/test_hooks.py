"""Tests for bin/hooks/*.py mailbox hook scripts (see docs/SPEC.md sec 7).

Each hook is a standalone script Claude Code invokes as a subprocess with
JSON on stdin. These tests exercise it the same way: real subprocess,
synthetic stdin, and FLEET_HOME pointed at a scratch tmp_path so the
repo's real mailbox/ is never touched.

A second layer of tests loads the hook modules directly (without running
their __main__ block) to pin down the internal claim-retry behavior
(PermissionError retry-once, FileNotFoundError race-loser) that is hard
to provoke reliably by spawning real concurrent processes.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "bin" / "hooks"
POSTTOOLUSE = HOOKS_DIR / "posttooluse_mailbox.py"
STOP = HOOKS_DIR / "stop_mailbox.py"

PY_CMD = ["py", "-3.13"]


def run_hook(script, stdin_text, fleet_home):
    env = dict(os.environ)
    env["FLEET_HOME"] = str(fleet_home)
    return subprocess.run(
        [*PY_CMD, str(script)],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def make_mailbox(fleet_home, session_id, content):
    mailbox_dir = Path(fleet_home) / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    path = mailbox_dir / f"{session_id}.md"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    return path


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def posttooluse_module():
    return _load_module(POSTTOOLUSE, "posttooluse_mailbox_under_test")


@pytest.fixture(scope="module")
def stop_module():
    return _load_module(STOP, "stop_mailbox_under_test")


# ---------------------------------------------------------------------
# PostToolUse hook -- subprocess-level behavior
# ---------------------------------------------------------------------

class TestPostToolUseSubprocess:
    def test_delivers_and_consumes_nonempty_mailbox(self, tmp_path):
        sid = "sess-1"
        mailbox = make_mailbox(tmp_path, sid, "do the thing\n")

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stderr == ""
        out = json.loads(proc.stdout)
        assert out == {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "<MANAGER MESSAGE>\ndo the thing\n",
            }
        }
        # mailbox consumed, no claimed-file litter left behind
        assert not mailbox.exists()
        assert list((tmp_path / "mailbox").iterdir()) == []

    def test_missing_mailbox_file_is_silent(self, tmp_path):
        sid = "sess-missing"
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_missing_mailbox_dir_is_silent(self, tmp_path):
        sid = "sess-nodir"

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_empty_mailbox_is_silent(self, tmp_path):
        sid = "sess-empty"
        mailbox = make_mailbox(tmp_path, sid, "")

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_malformed_stdin_exits_zero(self, tmp_path):
        proc = run_hook(POSTTOOLUSE, "not json{", tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_empty_stdin_exits_zero(self, tmp_path):
        proc = run_hook(POSTTOOLUSE, "", tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_missing_session_id_is_silent(self, tmp_path):
        proc = run_hook(POSTTOOLUSE, json.dumps({}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_concurrent_claims_deliver_exactly_once(self, tmp_path):
        sid = "sess-race"
        make_mailbox(tmp_path, sid, "only once\n")
        env = dict(os.environ)
        env["FLEET_HOME"] = str(tmp_path)
        cmd = [*PY_CMD, str(POSTTOOLUSE)]

        p1 = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env)
        p2 = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env)
        payload = json.dumps({"session_id": sid})
        out1, err1 = p1.communicate(payload, timeout=15)
        out2, err2 = p2.communicate(payload, timeout=15)

        assert p1.returncode == 0 and p2.returncode == 0
        assert err1 == "" and err2 == ""
        delivered = [o for o in (out1, out2) if o.strip()]
        assert len(delivered) == 1
        parsed = json.loads(delivered[0])
        assert parsed["hookSpecificOutput"]["additionalContext"] == "<MANAGER MESSAGE>\nonly once\n"
        # no leftover claimed-file litter regardless of who won
        assert list((tmp_path / "mailbox").iterdir()) == []


# ---------------------------------------------------------------------
# Stop hook -- subprocess-level behavior
# ---------------------------------------------------------------------

class TestStopSubprocess:
    def test_blocks_with_nonempty_mailbox(self, tmp_path):
        sid = "sess-1"
        mailbox = make_mailbox(tmp_path, sid, "keep going\n")

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stderr == ""
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "keep going\n"}
        assert not mailbox.exists()

    def test_allows_stop_when_mailbox_missing(self, tmp_path):
        sid = "sess-missing"
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_allows_stop_when_mailbox_empty(self, tmp_path):
        sid = "sess-empty"
        make_mailbox(tmp_path, sid, "")

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_malformed_stdin_exits_zero(self, tmp_path):
        proc = run_hook(STOP, "{not valid", tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""

    def test_stop_hook_active_still_delivers_mail(self, tmp_path):
        """No custom loop counter: mail present -> block regardless of
        stop_hook_active. Native 8-block force-allow is what caps runaway
        loops, per SPEC sec 7."""
        sid = "sess-active"
        make_mailbox(tmp_path, sid, "again\n")

        proc = run_hook(
            STOP,
            json.dumps({"session_id": sid, "stop_hook_active": True}),
            tmp_path,
        )

        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "again\n"}


# ---------------------------------------------------------------------
# Unit-level: claim/retry internals, loaded directly (no subprocess)
# ---------------------------------------------------------------------

class TestClaimInternals:
    def test_claim_returns_none_when_file_missing(self, tmp_path, posttooluse_module):
        target = tmp_path / "nope.md"

        assert posttooluse_module._claim(str(target)) is None

    def test_claim_retries_once_on_permission_error_then_succeeds(
        self, tmp_path, posttooluse_module, monkeypatch
    ):
        target = tmp_path / "sid.md"
        target.write_text("hi", encoding="utf-8")
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("locked")
            return real_replace(src, dst)

        monkeypatch.setattr(posttooluse_module.os, "replace", flaky_replace)

        claimed = posttooluse_module._claim(str(target))

        assert claimed is not None
        assert calls["n"] == 2
        assert Path(claimed).exists()

    def test_claim_gives_up_after_one_retry(self, tmp_path, posttooluse_module, monkeypatch):
        target = tmp_path / "sid.md"
        target.write_text("hi", encoding="utf-8")

        def always_locked(src, dst):
            raise PermissionError("locked")

        monkeypatch.setattr(posttooluse_module.os, "replace", always_locked)

        assert posttooluse_module._claim(str(target)) is None

    def test_claim_race_loser_exits_cleanly(self, tmp_path, posttooluse_module, monkeypatch):
        """Second hook process loses the os.replace race because the
        winner already renamed the source file away underneath it."""
        target = tmp_path / "sid.md"
        target.write_text("hi", encoding="utf-8")

        def vanished(src, dst):
            raise FileNotFoundError(src)

        monkeypatch.setattr(posttooluse_module.os, "replace", vanished)

        assert posttooluse_module._claim(str(target)) is None

    def test_stop_module_shares_same_claim_semantics(self, tmp_path, stop_module):
        target = tmp_path / "sid.md"
        target.write_text("payload", encoding="utf-8")

        claimed = stop_module._claim(str(target))

        assert claimed is not None
        assert not target.exists()
        assert Path(claimed).exists()


# ---------------------------------------------------------------------
# FLEET_HOME resolution
# ---------------------------------------------------------------------

class TestFleetHomeResolution:
    def test_defaults_to_repo_root_two_parents_up(self, posttooluse_module, monkeypatch):
        monkeypatch.delenv("FLEET_HOME", raising=False)

        assert Path(posttooluse_module._fleet_home()) == REPO_ROOT

    def test_env_var_overrides_default(self, tmp_path, posttooluse_module, monkeypatch):
        monkeypatch.setenv("FLEET_HOME", str(tmp_path))

        assert posttooluse_module._fleet_home() == str(tmp_path)
