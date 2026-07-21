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
POSTCOMPACT = HOOKS_DIR / "postcompact_journal.py"
STOP_OUTCOME = HOOKS_DIR / "stop_outcome.py"
TEMPLATE = REPO_ROOT / "worker-settings.template.json"

# The running interpreter, not a hardcoded `py -3.13` launcher: the hooks
# under test are stdlib-only and version-agnostic, and `py` exists only on
# Windows -- sys.executable keeps this tier green on every platform.
PY_CMD = [sys.executable]


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


def make_registry(fleet_home, workers):
    """Write state/fleet.json with {name: {session_id, ...}} entries."""
    state = Path(fleet_home) / "state"
    state.mkdir(parents=True, exist_ok=True)
    path = state / "fleet.json"
    path.write_text(json.dumps({"workers": workers}), encoding="utf-8")
    return path


def make_transcript(fleet_home, name_or_records, usages=None):
    """Write a JSONL transcript.

    Two call shapes:
    - make_transcript(fleet_home, name, usages) -- `usages` is a list of
      (input, output) token pairs, one assistant record per pair.
    - make_transcript(fleet_home, records) -- `records` is a list of raw
      JSONL-record dicts written verbatim, one per line (auto-named).

    Returns the transcript path.
    """
    tdir = Path(fleet_home) / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    if usages is None:
        records = name_or_records
        path = tdir / "t.jsonl"
        lines = [json.dumps(rec) for rec in records]
    else:
        name = name_or_records
        path = tdir / f"{name}.jsonl"
        lines = [json.dumps({
            "type": "assistant",
            "message": {"usage": {"input_tokens": inp, "output_tokens": out}},
        }) for inp, out in usages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_ceiling(fleet_home, session_id, value):
    """Write state/ceilings/<sid> with an integer token ceiling (or raw text)."""
    cdir = Path(fleet_home) / "state" / "ceilings"
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / session_id
    path.write_text(str(value), encoding="utf-8")
    return path


class _HookErrorLines(list):
    """A list of log lines whose `in` also matches as a substring of any
    line (on top of normal exact-element membership), so callers can do
    either `"X" in lines[0]` (existing per-line checks) or `"X" in lines`
    (does any line mention X) without losing len()/indexing."""

    def __contains__(self, item):
        if list.__contains__(self, item):
            return True
        return any(item in line for line in self)


def read_hook_errors(fleet_home):
    path = Path(fleet_home) / "state" / "hook-errors.log"
    if not path.exists():
        return _HookErrorLines()
    return _HookErrorLines(
        ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    )


def journal_path(fleet_home, key):
    return Path(fleet_home) / "state" / "journals" / f"{key}.md"


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

    def test_session_id_traversal_is_silent_and_leaves_target_untouched(self, tmp_path):
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)
        target = tmp_path / "evil.md"
        target.write_text("do not touch\n", encoding="utf-8")
        sid = "../evil"

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "do not touch\n"

    def test_session_id_absolute_path_is_silent_and_leaves_target_untouched(self, tmp_path):
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)
        target = tmp_path / "outside_secret.md"
        target.write_text("do not touch\n", encoding="utf-8")
        sid = str(tmp_path / "outside_secret")

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "do not touch\n"

    def test_whitespace_only_mailbox_is_silent_and_consumed(self, tmp_path):
        sid = "sess-whitespace"
        mailbox = make_mailbox(tmp_path, sid, "   \n\t  \n")

        proc = run_hook(POSTTOOLUSE, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert not mailbox.exists()
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

    def test_session_id_traversal_is_silent_and_leaves_target_untouched(self, tmp_path):
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)
        target = tmp_path / "evil.md"
        target.write_text("do not touch\n", encoding="utf-8")
        sid = "../evil"

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "do not touch\n"

    def test_session_id_absolute_path_is_silent_and_leaves_target_untouched(self, tmp_path):
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)
        target = tmp_path / "outside_secret.md"
        target.write_text("do not touch\n", encoding="utf-8")
        sid = str(tmp_path / "outside_secret")

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "do not touch\n"

    def test_whitespace_only_mailbox_is_silent_and_consumed(self, tmp_path):
        sid = "sess-whitespace"
        mailbox = make_mailbox(tmp_path, sid, "   \n\t  \n")

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert not mailbox.exists()
        assert list((tmp_path / "mailbox").iterdir()) == []


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


# ---------------------------------------------------------------------
# Kernel 1 -- swallowed-hook exception log (item 1)
# ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def postcompact_module():
    return _load_module(POSTCOMPACT, "postcompact_journal_under_test")


class TestKernel1HookErrorLog:
    def test_malformed_stdin_logs_one_line_and_exits_zero(self, tmp_path):
        """A swallowed exception (JSONDecodeError) still exits 0, emits no
        stdout, and appends exactly ONE diagnostic line to hook-errors.log."""
        proc = run_hook(POSTTOOLUSE, "not json{", tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        lines = read_hook_errors(tmp_path)
        assert len(lines) == 1
        # single line: timestamp + session_id-or-? + exception repr
        assert "JSONDecodeError" in lines[0] or "Expecting value" in lines[0]

    def test_stop_hook_also_logs_swallowed_exception(self, tmp_path):
        proc = run_hook(STOP, "not json{", tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""
        assert proc.stderr == ""
        assert len(read_hook_errors(tmp_path)) == 1

    def test_log_helper_writes_single_line_with_sid(self, tmp_path, posttooluse_module):
        posttooluse_module._log_hook_error("sess-x", ValueError("boom"), str(tmp_path))

        lines = read_hook_errors(tmp_path)
        assert len(lines) == 1
        assert "sess-x" in lines[0]
        assert "boom" in lines[0]
        # exactly one physical line (repr newlines flattened)
        assert "\n" not in lines[0]

    def test_log_helper_appends_never_truncates(self, tmp_path, posttooluse_module):
        posttooluse_module._log_hook_error("s1", ValueError("one"), str(tmp_path))
        posttooluse_module._log_hook_error("s2", ValueError("two"), str(tmp_path))

        lines = read_hook_errors(tmp_path)
        assert len(lines) == 2
        assert "s1" in lines[0] and "s2" in lines[1]

    def test_log_helper_missing_sid_uses_placeholder(self, tmp_path, posttooluse_module):
        posttooluse_module._log_hook_error(None, ValueError("x"), str(tmp_path))

        lines = read_hook_errors(tmp_path)
        assert len(lines) == 1
        assert lines[0].split()[1] == "?"

    def test_log_helper_swallows_own_write_failure(self, tmp_path, posttooluse_module):
        # point hook-errors.log at a DIRECTORY so the append open() raises;
        # the helper must swallow it and never propagate.
        badhome = tmp_path / "badhome"
        (badhome / "state").mkdir(parents=True, exist_ok=True)
        (badhome / "state" / "hook-errors.log").mkdir()

        # must not raise
        posttooluse_module._log_hook_error("s", ValueError("x"), str(badhome))


# ---------------------------------------------------------------------
# Kernel 3 -- fail-silent PostCompact journal landmark (item 3 + F11)
# ---------------------------------------------------------------------

class TestKernel3PostCompact:
    def test_resolves_sid_to_name_and_appends_landmark(self, tmp_path):
        sid = "abc-123"
        make_registry(tmp_path, {"worker-a": {"session_id": sid}})
        tp = make_transcript(tmp_path, "worker-a", [(10, 20), (30, 40)])

        proc = run_hook(
            POSTCOMPACT,
            json.dumps({"session_id": sid, "transcript_path": str(tp),
                        "trigger": "auto"}),
            tmp_path,
        )

        assert proc.returncode == 0
        assert proc.stderr == ""
        jpath = journal_path(tmp_path, "worker-a")
        assert jpath.exists()
        body = jpath.read_text(encoding="utf-8")
        assert "context compacted here" in body
        assert "turns=2" in body
        assert "trigger=auto" in body
        # NOT written to a sid-keyed path when the name resolved
        assert not journal_path(tmp_path, sid).exists()

    def test_appends_never_truncates_existing_journal(self, tmp_path):
        sid = "abc-123"
        make_registry(tmp_path, {"worker-a": {"session_id": sid}})
        jpath = journal_path(tmp_path, "worker-a")
        jpath.parent.mkdir(parents=True, exist_ok=True)
        jpath.write_text("# existing journal\n", encoding="utf-8")

        run_hook(POSTCOMPACT, json.dumps({"session_id": sid}), tmp_path)

        body = jpath.read_text(encoding="utf-8")
        assert body.startswith("# existing journal\n")
        assert "context compacted here" in body

    def test_unresolved_sid_falls_back_to_sid_keyed_journal(self, tmp_path):
        sid = "loose-sid"
        # registry present but does not contain this sid
        make_registry(tmp_path, {"other": {"session_id": "different"}})

        proc = run_hook(POSTCOMPACT, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert journal_path(tmp_path, sid).exists()
        body = journal_path(tmp_path, sid).read_text(encoding="utf-8")
        assert "context compacted here" in body

    def test_no_registry_falls_back_to_sid_keyed_journal(self, tmp_path):
        sid = "no-reg-sid"

        proc = run_hook(POSTCOMPACT, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert journal_path(tmp_path, sid).exists()

    @pytest.mark.parametrize("doc", [
        [1, 2, 3],                        # top-level list
        "just a string",                  # top-level string
        {"workers": [1, 2]},              # workers not a dict
        {"workers": {"w": ["not", "a", "dict"]}},  # record not a dict
    ])
    def test_wrong_shape_registry_falls_back_to_sid_journal(self, tmp_path, doc):
        # Debt roll-up item 1: T2's wrong-shape defense (see
        # stop_outcome.py::_resolve_name) was missing here -- a
        # syntactically-valid but non-dict fleet.json raised AttributeError
        # out of _resolve_name, unwound into __main__'s handler, and skipped
        # the landmark write entirely (silent loss). Must instead resolve to
        # None and fall back to the sid-keyed journal, no swallowed crash.
        sid = "wrongshape-sid"
        state = tmp_path / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "fleet.json").write_text(json.dumps(doc), encoding="utf-8")

        proc = run_hook(POSTCOMPACT, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        assert proc.stderr == ""
        # a genuine fallback, not an exception logged by the outer handler
        assert len(read_hook_errors(tmp_path)) == 0
        body = journal_path(tmp_path, sid).read_text(encoding="utf-8")
        assert "context compacted here" in body

    def test_invalid_sid_skips_and_writes_nothing(self, tmp_path):
        (tmp_path / "state" / "journals").mkdir(parents=True, exist_ok=True)
        target = tmp_path / "evil.md"
        target.write_text("do not touch\n", encoding="utf-8")

        proc = run_hook(POSTCOMPACT, json.dumps({"session_id": "../evil"}), tmp_path)

        assert proc.returncode == 0
        assert proc.stderr == ""
        assert target.read_text(encoding="utf-8") == "do not touch\n"
        # nothing landed in journals/
        assert list((tmp_path / "state" / "journals").iterdir()) == []

    def test_missing_session_id_skips(self, tmp_path):
        proc = run_hook(POSTCOMPACT, json.dumps({}), tmp_path)

        assert proc.returncode == 0
        assert proc.stdout == ""

    def test_malformed_stdin_exits_zero_and_logs(self, tmp_path):
        proc = run_hook(POSTCOMPACT, "not json{", tmp_path)

        assert proc.returncode == 0
        assert proc.stderr == ""
        assert len(read_hook_errors(tmp_path)) == 1

    def test_unreadable_transcript_still_writes_landmark(self, tmp_path):
        sid = "abc-123"
        make_registry(tmp_path, {"worker-a": {"session_id": sid}})

        proc = run_hook(
            POSTCOMPACT,
            json.dumps({"session_id": sid,
                        "transcript_path": str(tmp_path / "nope.jsonl")}),
            tmp_path,
        )

        assert proc.returncode == 0
        body = journal_path(tmp_path, "worker-a").read_text(encoding="utf-8")
        assert "context compacted here" in body
        assert "turns=?" in body


# ---------------------------------------------------------------------
# Kernel 10 -- Stop-hook token-ceiling read (item 10, hook-side half)
# ---------------------------------------------------------------------

class TestKernel10TokenCeiling:
    def test_over_ceiling_allows_stop_with_mail_pending(self, tmp_path):
        sid = "sess-ceil"
        mailbox = make_mailbox(tmp_path, sid, "keep going\n")
        make_ceiling(tmp_path, sid, 100)
        tp = make_transcript(tmp_path, sid, [(200, 300)])  # 500 >= 100

        proc = run_hook(
            STOP,
            json.dumps({"session_id": sid, "transcript_path": str(tp)}),
            tmp_path,
        )

        assert proc.returncode == 0
        assert proc.stderr == ""
        # ALLOW stop: no block decision emitted
        assert proc.stdout == ""
        # mail preserved (not claimed/drained) -> visible via idle+mail next launch
        assert mailbox.exists()
        assert mailbox.read_text(encoding="utf-8") == "keep going\n"
        assert list((tmp_path / "mailbox").iterdir()) == [mailbox]

    def test_under_ceiling_blocks_with_mail(self, tmp_path):
        sid = "sess-ceil"
        mailbox = make_mailbox(tmp_path, sid, "keep going\n")
        make_ceiling(tmp_path, sid, 10000)
        tp = make_transcript(tmp_path, sid, [(20, 30)])  # 50 < 10000

        proc = run_hook(
            STOP,
            json.dumps({"session_id": sid, "transcript_path": str(tp)}),
            tmp_path,
        )

        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "keep going\n"}
        assert not mailbox.exists()

    def test_no_ceiling_file_preserves_existing_block(self, tmp_path):
        sid = "sess-noceil"
        make_mailbox(tmp_path, sid, "onward\n")

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "onward\n"}

    def test_ceiling_but_no_transcript_is_conservative_block(self, tmp_path):
        """Ceiling set but transcript unreadable -> cannot prove over-ceiling
        -> fall through to existing block-on-mail (hook never wrongly allows)."""
        sid = "sess-ceil"
        make_mailbox(tmp_path, sid, "still here\n")
        make_ceiling(tmp_path, sid, 100)

        proc = run_hook(STOP, json.dumps({"session_id": sid}), tmp_path)

        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "still here\n"}

    def test_garbage_ceiling_value_is_conservative_block(self, tmp_path):
        sid = "sess-ceil"
        make_mailbox(tmp_path, sid, "hi\n")
        make_ceiling(tmp_path, sid, "not-a-number")
        tp = make_transcript(tmp_path, sid, [(999, 999)])

        proc = run_hook(
            STOP,
            json.dumps({"session_id": sid, "transcript_path": str(tp)}),
            tmp_path,
        )

        assert proc.returncode == 0
        out = json.loads(proc.stdout)
        assert out == {"decision": "block", "reason": "hi\n"}

    def test_over_ceiling_with_no_mail_still_allows_stop(self, tmp_path):
        sid = "sess-ceil"
        (tmp_path / "mailbox").mkdir(parents=True, exist_ok=True)
        make_ceiling(tmp_path, sid, 100)
        tp = make_transcript(tmp_path, sid, [(200, 300)])

        proc = run_hook(
            STOP,
            json.dumps({"session_id": sid, "transcript_path": str(tp)}),
            tmp_path,
        )

        assert proc.returncode == 0
        assert proc.stdout == ""


# ---------------------------------------------------------------------
# Stop-hook outcome writer (M-B T2)
# ---------------------------------------------------------------------

class TestStopOutcome:
    def _payload(self, home, sid="sid-1", last_msg="All done.", transcript=None):
        p = {"session_id": sid, "hook_event_name": "Stop"}
        if transcript is not None:
            p["transcript_path"] = str(transcript)
        if last_msg is not None:
            p["last_assistant_message"] = last_msg
        return json.dumps(p)

    def test_writes_result_record_named_by_registry(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        t = make_transcript(tmp_path, [
            {"type": "assistant",
             "message": {"model": "claude-haiku-4-5-20251001",
                         "usage": {"input_tokens": 11, "output_tokens": 7},
                         "content": [{"type": "text", "text": "All done."}]}},
            {"type": "system", "subtype": "bookkeeping"},
        ])
        run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=t), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["kind"] == "result"
        assert rec["session_id"] == "sid-1"
        assert rec["result_text"] == "All done."
        assert rec["output_tokens"] == 7 and rec["input_tokens"] == 11
        assert rec["model"] == "claude-haiku-4-5-20251001"

    def test_missing_last_assistant_message_falls_back_to_transcript(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        t = make_transcript(tmp_path, [
            {"type": "assistant",
             "message": {"content": [{"type": "text", "text": "from transcript"}]}},
            {"type": "attachment"},
        ])
        run_hook(STOP_OUTCOME, self._payload(tmp_path, last_msg=None, transcript=t), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert rec["result_text"] == "from transcript"

    def test_unresolvable_name_falls_back_to_sid_key(self, tmp_path):
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)  # no registry
        run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=None), tmp_path)
        assert (tmp_path / "state" / "outcomes" / "sid-1.jsonl").exists()

    def test_truncates_huge_result_text(self, tmp_path):
        make_registry(tmp_path, {"w1": {"session_id": "sid-1"}})
        run_hook(STOP_OUTCOME, self._payload(tmp_path, last_msg="x" * 50000), tmp_path)
        rec = json.loads((tmp_path / "state" / "outcomes" / "w1.jsonl")
                         .read_text(encoding="utf-8").strip())
        assert len(rec["result_text"]) == 20000

    def test_garbage_stdin_logs_error_and_exits_zero(self, tmp_path):
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        proc = run_hook(STOP_OUTCOME, "{not json", tmp_path)
        assert proc.returncode == 0
        assert "stop_outcome" in read_hook_errors(tmp_path)

    # -- fix wave: registry-shape guards (adversarial trap 6, CRITICAL) --

    def test_registry_workers_list_falls_back_to_sid_key(self, tmp_path):
        """A syntactically-valid but wrong-shaped fleet.json ("workers" is a
        list, not a dict) must not blow up _resolve_name -- the record for
        this Stop event must still be written, keyed by sid."""
        state = tmp_path / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "fleet.json").write_text(json.dumps({"workers": [1, 2]}), encoding="utf-8")
        proc = run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=None), tmp_path)
        assert proc.returncode == 0
        assert (state / "outcomes" / "sid-1.jsonl").exists()

    def test_registry_top_level_list_falls_back_to_sid_key(self, tmp_path):
        """Same as above but the whole registry document is a list, not a
        dict at all."""
        state = tmp_path / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "fleet.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        proc = run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=None), tmp_path)
        assert proc.returncode == 0
        assert (state / "outcomes" / "sid-1.jsonl").exists()

    # -- fix wave: path-safety parity with postcompact_journal.py --

    def test_unsafe_session_id_writes_nothing_and_logs(self, tmp_path):
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        payload = self._payload(tmp_path, sid="..\\..\\pwn", transcript=None)
        proc = run_hook(STOP_OUTCOME, payload, tmp_path)
        assert proc.returncode == 0
        outcomes = tmp_path / "state" / "outcomes"
        assert not outcomes.exists() or not any(outcomes.iterdir())
        # no traversal outside the outcomes dir either
        assert not (tmp_path / "pwn.jsonl").exists()
        assert "stop_outcome" in read_hook_errors(tmp_path)

    def test_registry_name_with_path_separator_falls_back_to_sid_key(self, tmp_path):
        make_registry(tmp_path, {"w1/evil": {"session_id": "sid-1"}})
        proc = run_hook(STOP_OUTCOME, self._payload(tmp_path, transcript=None), tmp_path)
        assert proc.returncode == 0
        assert (tmp_path / "state" / "outcomes" / "sid-1.jsonl").exists()
        assert not (tmp_path / "state" / "outcomes" / "w1").exists()

    # -- fix wave: session_id coerced to str before validation/matching --

    def test_non_str_session_id_coerced_to_str(self, tmp_path):
        payload = json.dumps({
            "session_id": 12345, "hook_event_name": "Stop",
            "last_assistant_message": "All done.",
        })
        proc = run_hook(STOP_OUTCOME, payload, tmp_path)
        assert proc.returncode == 0
        out = tmp_path / "state" / "outcomes" / "12345.jsonl"
        assert out.exists()
        rec = json.loads(out.read_text(encoding="utf-8").strip())
        assert rec["session_id"] == "12345"
        assert isinstance(rec["session_id"], str)

    def test_falsy_session_id_still_silent_no_write(self, tmp_path):
        payload = json.dumps({"session_id": "", "hook_event_name": "Stop"})
        proc = run_hook(STOP_OUTCOME, payload, tmp_path)
        assert proc.returncode == 0
        assert not (tmp_path / "state" / "outcomes").exists()

    def test_atomic_append_helper_matches_fleet_pattern(self):
        """Structural pin: the hook must use the same Win32
        FILE_APPEND_DATA-only atomic-append approach as bin/fleet.py's
        _atomic_append_bytes (T1 fix-wave lesson), not plain open(..., "a")
        buffered writes, which lose records under concurrent Stop-hook
        invocations on Windows."""
        source = STOP_OUTCOME.read_text(encoding="utf-8")
        assert "_atomic_append_bytes" in source
        assert "FILE_APPEND_DATA" in source
        assert "CreateFileW" in source
        assert "WriteFile" in source


# ---------------------------------------------------------------------
# Template -- parses, forward slashes, PostCompact registered (F11a)
# ---------------------------------------------------------------------

class TestTemplate:
    def _render(self):
        raw = TEMPLATE.read_text(encoding="utf-8")
        return raw.replace("{{PYTHON}}", "py -3.13").replace(
            "{{FLEET_HOME}}", "C:/proga/claude-fleet")

    def test_template_renders_and_parses(self):
        parsed = json.loads(self._render())
        hooks = parsed["hooks"]
        assert "PostToolUse" in hooks
        assert "Stop" in hooks
        assert "PostCompact" in hooks

    def test_postcompact_registered_pointing_at_new_hook(self):
        parsed = json.loads(self._render())
        cmd = parsed["hooks"]["PostCompact"][0]["hooks"][0]["command"]
        assert "postcompact_journal.py" in cmd

    def test_stop_array_order_outcome_then_mailbox(self):
        parsed = json.loads(self._render())
        stop_hooks = parsed["hooks"]["Stop"][0]["hooks"]
        assert len(stop_hooks) == 2
        assert "stop_outcome.py" in stop_hooks[0]["command"]
        assert "stop_mailbox.py" in stop_hooks[1]["command"]

    def test_all_hook_commands_use_forward_slashes(self):
        parsed = json.loads(self._render())
        for event in ("PostToolUse", "PostCompact"):
            cmd = parsed["hooks"][event][0]["hooks"][0]["command"]
            # path portion must not contain backslashes (Git-Bash sh -c eats them)
            assert "\\" not in cmd, f"{event} command has a backslash: {cmd}"
        for cmd in (h["command"] for h in parsed["hooks"]["Stop"][0]["hooks"]):
            assert "\\" not in cmd, f"Stop command has a backslash: {cmd}"

    def test_raw_template_is_valid_json_with_placeholders(self):
        # placeholders live inside string values, so the raw file still parses
        parsed = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        assert "PostCompact" in parsed["hooks"]
