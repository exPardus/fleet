"""M-B native-substrate tests: registry v2 fields, outcome store, dispatch
helper, discriminator, limit rehome, steering, stop/tombstones, archival."""
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)

REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_OUTCOME_HOOK = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"
PY_CMD = ["py", "-3.13"]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def native_home(tmp_path, monkeypatch):
    """Sandboxed FLEET_HOME with state/ and a rendered instance settings file."""
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "worker-settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def make_roster_entry(sid, *, name="fleet|w1|task", state="working",
                      status="busy", pid=1234, kind="background"):
    """Roster entry per the contract field-presence table. Pass status=None /
    pid=None to model dead entries (keys OMITTED, not null)."""
    entry = {"id": sid[:8], "sessionId": sid, "name": name, "cwd": "C:/proj",
             "startedAt": 1783986489446, "kind": kind, "state": state}
    if status is not None:
        entry["status"] = status
    if pid is not None:
        entry["pid"] = pid
    return entry


def seed_native_worker(home, name="w1", sid="aaaabbbb-1111-2222-3333-444455556666",
                       status="working", last_dispatch_at=None, **overrides):
    rec = fleet.new_worker_record(sid, "C:/proj", "do the thing", "accept",
                                  dispatch_kind="bg")
    rec["status"] = status
    rec["native_short_id"] = sid[:8]
    rec["last_dispatch_at"] = last_dispatch_at or _iso(NOW - timedelta(minutes=5))
    rec.update(overrides)
    data = {"workers": {name: rec}}
    fleet.save_registry(data)
    return rec


class TestRegistryV2:
    def test_new_record_native_fields_default_off(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept")
        assert rec["dispatch_kind"] is None
        assert rec["category"] is None
        assert rec["native_short_id"] is None
        assert rec["last_dispatch_at"] is None
        assert rec["retired_sids"] == []
        assert rec["archived_at"] is None

    def test_new_record_bg_kind(self, native_home):
        rec = fleet.new_worker_record("sid-1", "C:/p", "t", "accept",
                                      dispatch_kind="bg", category="camp5")
        assert rec["dispatch_kind"] == "bg" and rec["category"] == "camp5"

    def test_is_native_discriminates_on_dispatch_kind(self, native_home):
        assert fleet.is_native({"dispatch_kind": "bg"}) is True
        assert fleet.is_native({"session_id": "old"}) is False  # pre-pivot shape

    @pytest.mark.parametrize("bad", [None, "junk", [], 42])
    def test_is_native_non_dict_returns_false(self, native_home, bad):
        assert fleet.is_native(bad) is False


class TestOutcomeStore:
    def test_append_and_read_roundtrip(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1",
                                    "kind": "result", "result_text": "done ✓"})
        recs = fleet.read_outcomes("w1")
        assert recs[0]["result_text"] == "done ✓"

    def test_read_merges_sid_fallback_file_and_skips_junk(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        fleet.append_outcome("s1", {"ts": _iso(NOW + timedelta(seconds=9)),
                                    "session_id": "s1", "kind": "result"})
        fleet.outcome_path("w1").open("a", encoding="utf-8").write("{not json\n")
        recs = fleet.read_outcomes("w1", sid="s1")
        assert len(recs) == 2
        assert recs[-1]["ts"] > recs[0]["ts"]  # sorted by ts

    def test_read_filters_by_sid(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-sid", "kind": "result"})
        assert fleet.read_outcomes("w1", sid="new-sid") == []

    def test_has_fresh_outcome_boundary_and_slack(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        # record 3s OLDER than since still counts (5s slack)
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=3)))
        assert not fleet.has_fresh_outcome("w1", "s1", _iso(NOW + timedelta(seconds=30)))
        assert not fleet.has_fresh_outcome("w1", "other", _iso(NOW))

    def test_tombstone_shape(self, native_home):
        fleet.write_tombstone_outcome("w1", "s1", "interrupted")
        rec = fleet.read_outcomes("w1", sid="s1")[-1]
        assert rec["kind"] == "interrupted" and rec["result_text"] is None
        with pytest.raises(ValueError):
            fleet.write_tombstone_outcome("w1", "s1", "exploded")

    def test_has_fresh_outcome_malformed_since_iso_returns_false(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        assert fleet.has_fresh_outcome("w1", "s1", "not-a-date") is False

    def test_has_fresh_outcome_skips_malformed_record_ts(self, native_home):
        # ts is an int (not a string) -- must be skipped, not raise.
        fleet.append_outcome("w1", {"ts": 12345, "session_id": "s1", "kind": "result"})
        # ts is missing entirely -- must be skipped, not raise.
        fleet.append_outcome("w1", {"session_id": "s1", "kind": "result"})
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW)) is False

    def test_append_outcome_truncates_result_text(self, native_home):
        long_text = "x" * (fleet.OUTCOME_RESULT_TEXT_MAX + 500)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1",
                                    "kind": "result", "result_text": long_text})
        rec = fleet.read_outcomes("w1")[0]
        assert len(rec["result_text"]) == fleet.OUTCOME_RESULT_TEXT_MAX

    def test_append_outcome_short_result_text_untouched(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1",
                                    "kind": "result", "result_text": "short"})
        rec = fleet.read_outcomes("w1")[0]
        assert rec["result_text"] == "short"

    def test_atomic_append_partial_write_raises_not_silently_truncates(
            self, native_home, tmp_path, monkeypatch):
        # Roll-up item 4: WriteFile returning success (ok=True) with
        # written < len(data) -- a partial write -- must raise OSError, not
        # silently truncate. A torn JSONL line is exactly what
        # read_outcomes silently skips, the same silent-loss failure class
        # T1's CRITICAL fix existed to kill.
        import ctypes
        kernel32 = ctypes.windll.kernel32

        def short_write_file(handle, data, size, written_ptr, overlapped):
            written_ptr._obj.value = 1   # claims success, only 1 byte written
            return 1                      # nonzero == TRUE (ok)

        monkeypatch.setattr(kernel32, "WriteFile", short_write_file)
        target = tmp_path / "out.jsonl"
        with pytest.raises(OSError):
            fleet._atomic_append_bytes(target, b"hello world\n")

    # T5 fix wave (Critical C1): has_fresh_outcome's default `kinds`
    # argument must exclude tombstones -- see task-5-adversarial.md's C1
    # repro. A fresh tombstone must never be read as "the turn finished".
    def test_has_fresh_outcome_result_kind_still_vouches(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result"})
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW)) is True

    @pytest.mark.parametrize("kind", fleet.TOMBSTONE_KINDS)
    def test_has_fresh_outcome_default_ignores_every_tombstone_kind(self, native_home, kind):
        fleet.write_tombstone_outcome("w1", "s1", kind)
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW)) is False

    def test_has_fresh_outcome_kinds_param_can_opt_in_to_tombstones(self, native_home):
        # The default excludes tombstones, but a caller that genuinely
        # wants to match one can still widen the match set explicitly.
        fleet.write_tombstone_outcome("w1", "s1", "killed")
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW), kinds=("killed",)) is True
        assert fleet.has_fresh_outcome("w1", "s1", _iso(NOW)) is False


class TestOutcomeConcurrency:
    def test_concurrent_appends_lose_no_records(self, native_home):
        """4 threads x 250 records each -> exactly 1000 parseable records,
        zero torn/lost lines. Regression test for the buffered text-mode
        `open(..., 'a')` record-loss bug (adversarial CRITICAL finding #1)."""
        n_writers = 4
        n_per_writer = 250

        def writer(tag):
            for i in range(n_per_writer):
                fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": tag,
                                            "kind": "result", "seq": i,
                                            "result_text": tag * 50})

        threads = [threading.Thread(target=writer, args=(f"tag{t}",))
                   for t in range(n_writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        text = fleet.outcome_path("w1").read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        parsed = []
        bad = 0
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except json.JSONDecodeError:
                bad += 1

        assert bad == 0
        assert len(parsed) == n_writers * n_per_writer
        counts = {}
        for rec in parsed:
            counts[rec["session_id"]] = counts.get(rec["session_id"], 0) + 1
        assert counts == {f"tag{t}": n_per_writer for t in range(n_writers)}


class TestRenderNativeName:
    def test_format_and_hint_clip(self):
        n = fleet.render_native_name("camp5", "w1", "port the parser\nto rust " + "x" * 60)
        cat, name, hint = n.split("|", 2)
        assert (cat, name) == ("camp5", "w1")
        assert "\n" not in hint and len(hint) <= 40

    def test_defaults(self):
        assert fleet.render_native_name(None, "w1", "") == "fleet|w1|"

    def test_category_and_hint_pipes_sanitized(self):
        # A pipe in either field must not corrupt the cat|name|hint split.
        n = fleet.render_native_name("a|b", "w1", "x|y")
        assert n.count("|") == 2
        cat, name, hint = n.split("|", 2)
        assert (cat, name, hint) == ("a/b", "w1", "x/y")


class TestParseBgShortId:
    def test_parses_backgrounded_line(self):
        out = "some hint\nbackgrounded · deadbeef · fleet|w1|task\nattach hint\n"
        assert fleet._parse_bg_short_id(out) == "deadbeef"

    def test_missing_line_returns_none(self):
        assert fleet._parse_bg_short_id("error: whatever") is None

    def test_strips_ansi_color_codes_around_short_id(self):
        # T12 fix wave (finding 3): a color-forcing env var (FORCE_COLOR)
        # makes the daemon wrap the short id in ANSI CSI codes even though
        # stdout is piped, not a tty -- live-confirmed repr:
        # 'backgrounded \xb7 \x1b[36m8e4a79bb\x1b[39m \xb7 timing-probe\n...'
        out = ("backgrounded \xb7 \x1b[36mdeadbeef\x1b[39m \xb7 fleet|w1|task\n"
               "\x1b[2m  claude agents             list sessions\x1b[22m\n")
        assert fleet._parse_bg_short_id(out) == "deadbeef"


def _fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n", rc=0, calls=None):
    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        import types
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return fake_run


SID = "aaaabbbb-1111-2222-3333-444455556666"


def _roster_with(sid=SID, **kw):
    """Call-count-aware: the 1st call (dispatch_bg's pre-dispatch snapshot)
    reports the session doesn't exist yet -- realistic, since the daemon
    hasn't minted it. The 2nd+ call (the join poll, post-dispatch) reports
    the entry present."""
    state = {"n": 0}
    def fetch(**_):
        state["n"] += 1
        if state["n"] == 1:
            return True, []
        return True, [make_roster_entry(sid, **kw)]
    return fetch


def _roster_sequence(*results):
    """Returns `results[0]` on the 1st call, `results[1]` on the 2nd, ...
    and repeats the LAST result for every call beyond `len(results)`. Used
    where a single test drives MULTIPLE distinct `_fetch_agents_roster`
    call sites in order (e.g. cmd_send's own verdict fetch, THEN
    dispatch_bg's pre-dispatch snapshot, THEN its join-poll)."""
    state = {"n": 0}
    def fetch(**_):
        i = min(state["n"], len(results) - 1)
        state["n"] += 1
        return results[i]
    return fetch


class _FakeClock:
    """Injectable monotonic clock for join-loop tests -- no real sleeping."""
    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestDispatchBg:
    def test_happy_path_returns_sid_and_writes_task_file(self, native_home):
        calls = []
        out = fleet.dispatch_bg("w1", "C:/proj", "BODY-1234", "accept",
                                model="haiku", category="camp5", hint="port it",
                                run=_fake_run_factory(calls=calls),
                                which=lambda _: "claude",
                                sleep=lambda s: None, roster_fetch=_roster_with())
        assert out["session_id"] == SID and out["short_id"] == "aaaabbbb"
        assert fleet.task_file_path("w1").read_text(encoding="utf-8") == "BODY-1234"
        argv, kwargs = calls[0]
        assert argv[:2] == ["claude", "--bg"]
        assert "--resume" not in argv
        assert argv[argv.index("-n") + 1].startswith("camp5|w1|")
        assert argv[-1] == f"Read {fleet.task_file_path('w1').as_posix()} and follow it exactly."
        assert "--model" in argv and "haiku" in argv
        assert kwargs["env"].get("FLEET_WORKER")
        assert "CLAUDE_CODE_SESSION_ID" not in kwargs["env"]
        assert kwargs["cwd"] == "C:/proj"

    def test_argv_pre_authorizes_tasks_dir_via_add_dir(self, native_home):
        # T12 fix wave (finding 1): the task file lives under
        # FLEET_HOME/tasks, outside the worker's own --dir cwd -- without
        # --add-dir the worker's first Read on it hangs forever under any
        # non-bypass mode. Pin the exact flag + posix path (tasks_dir()
        # only, never FLEET_HOME wholesale -- least privilege).
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                          run=_fake_run_factory(calls=calls), which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv = calls[0][0]
        assert argv[argv.index("--add-dir") + 1] == fleet.tasks_dir().as_posix()

    def test_resume_sid_inserts_resume_flag(self, native_home):
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "steer", "accept", resume_sid="old-sid",
                          run=_fake_run_factory(calls=calls), which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv = calls[0][0]
        assert argv[argv.index("--resume") + 1] == "old-sid"

    def test_nonzero_exit_raises(self, native_home):
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(rc=1), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_unparseable_stdout_raises(self, native_home):
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(stdout="garbage"),
                              which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_join_window_expiry_raises_with_short_id(self, native_home):
        # Fake clock + sleep-advances-clock -- exercises the full 60s verify
        # window with zero real wall-clock time (was ~60s of real sleep).
        clock = _FakeClock()

        def empty_fetch(**_):
            return True, []

        def fast_sleep(s):
            clock.advance(s)

        with pytest.raises(fleet.NativeDispatchError, match="aaaabbbb") as exc_info:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=fast_sleep, roster_fetch=empty_fetch, clock=clock)
        # T4 fix wave (Critical C1): the join-expiry raise is the primary
        # place dispatch_bg knows the short id -- cmd_spawn's
        # fast-completion recovery depends on this attribute being set (see
        # _fast_completion_sid).
        assert exc_info.value.short_id == "aaaabbbb"

    def test_pre_snapshot_filters_hostile_sessionid_value(self, native_home):
        # Roll-up item 3: a dict-valued sessionId in the pre-dispatch roster
        # snapshot (CLI drift / hostile roster) must not raise TypeError from
        # an unhashable value landing in the exclusion set.
        state = {"n": 0}
        def roster_fetch(**_):
            state["n"] += 1
            if state["n"] == 1:
                return True, [{"sessionId": {"nested": "hostile"}}]
            return True, [make_roster_entry(SID, status="idle")]
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                                run=_fake_run_factory(), which=lambda _: "claude",
                                sleep=lambda s: None, roster_fetch=roster_fetch)
        assert out["session_id"] == SID

    def test_other_dispatch_errors_leave_short_id_none(self, native_home):
        # Failure causes before a short id is ever parsed (bad name, missing
        # exe, task-file write failure, nonzero exit, unparseable stdout)
        # must not fabricate one.
        with pytest.raises(fleet.NativeDispatchError) as exc_info:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(rc=1), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())
        assert exc_info.value.short_id is None

    def test_ctrlc_mid_join_adds_short_id_note(self, native_home):
        # T4 fix wave (Ctrl-C short-id loss): a KeyboardInterrupt (or any
        # BaseException) escaping the join-verify wait -- AFTER the --bg
        # dispatch itself already succeeded -- must carry the short id as
        # an exception note so cmd_spawn's BaseException handler can still
        # recover it (dispatch_bg stays opaque otherwise: no other channel
        # exists once the join call itself never returns).
        def empty_fetch(**_):
            return True, []

        def sleep(s):
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt) as exc_info:
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=sleep, roster_fetch=empty_fetch)
        notes = getattr(exc_info.value, "__notes__", None) or []
        assert any(n == "fleet_short_id=aaaabbbb" for n in notes)

    def test_setting_sources_forwarded_after_settings_flag(self, native_home):
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "b", "accept", setting_sources="user,project",
                          run=_fake_run_factory(calls=calls), which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv = calls[0][0]
        assert argv[argv.index("--setting-sources") + 1] == "user,project"
        assert argv.index("--setting-sources") > argv.index("--settings")

    def test_setting_sources_omitted_when_none(self, native_home):
        calls = []
        fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                          run=_fake_run_factory(calls=calls), which=lambda _: "claude",
                          sleep=lambda s: None, roster_fetch=_roster_with())
        argv = calls[0][0]
        assert "--setting-sources" not in argv

    def test_dispatch_timeout_raises(self, native_home):
        def timeout_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=fleet.NATIVE_DISPATCH_TIMEOUT_SECONDS)

        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=timeout_run, which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_join_matches_done_entry_fast_completion(self, native_home):
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                                run=_fake_run_factory(), which=lambda _: "claude",
                                sleep=lambda s: None,
                                roster_fetch=_roster_with(state="done", status=None, pid=None))
        assert out["session_id"] == SID

    def test_missing_claude_exe_raises_native_dispatch_error(self, native_home):
        # resolve_claude_executable raises ClaudeNotFoundError -- the contract
        # requires NativeDispatchError uniformly across all four failure causes.
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: None,
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_task_file_mkdir_failure_raises_native_dispatch_error(self, native_home):
        # A regular FILE occupying tasks_dir()'s path makes mkdir(exist_ok=True)
        # raise FileExistsError -- must surface as NativeDispatchError, not a
        # raw OSError, so callers' `except NativeDispatchError` rollback fires.
        (native_home / "state" / "tasks").write_text("blocker", encoding="utf-8")
        with pytest.raises(fleet.NativeDispatchError, match="task-file write failed"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())

    def test_invalid_name_raises_before_any_file_created(self, native_home):
        with pytest.raises(fleet.NativeDispatchError):
            fleet.dispatch_bg("..\\evil", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=_roster_with())
        # No task file created anywhere -- neither inside tasks_dir() nor via
        # traversal outside it.
        assert not (native_home / "state" / "tasks").exists()
        assert not (native_home / "evil.md").exists()
        assert not (native_home.parent / "evil.md").exists()

    def test_pre_existing_foreign_sid_excluded_from_join(self, native_home):
        # Roundtrip through dispatch_bg's automatic pre-dispatch snapshot: a
        # foreign session sharing the short-id prefix is already on the
        # roster BEFORE this dispatch -- it must never be joined, even though
        # it's still present (and listed first) on every subsequent poll.
        foreign = "aaaabbbb-9999-8888-7777-666655554444"
        real = "aaaabbbb-1111-2222-3333-444455556666"
        state = {"n": 0}

        def roster_fetch(**_):
            state["n"] += 1
            entries = [make_roster_entry(foreign, name="someone-elses-worker")]
            if state["n"] > 1:
                # Only visible from the join poll onward -- the real session
                # doesn't exist yet at pre-dispatch-snapshot time.
                entries.append(make_roster_entry(real))
            return True, entries

        out = fleet.dispatch_bg(
            "w1", "C:/proj", "b", "accept",
            run=_fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n"),
            which=lambda _: "claude", sleep=lambda s: None,
            roster_fetch=roster_fetch)
        assert out["session_id"] == real


class TestJoinRosterByShortId:
    def test_multi_poll_miss_then_match(self):
        """Fetch misses twice, matches on the 3rd poll -- regression test for
        the join loop's retry structure (previously zero coverage per the
        adversarial review's fault-injection finding)."""
        clock = _FakeClock()
        calls = {"fetch": 0}
        sleeps = []

        def fetch(**_):
            calls["fetch"] += 1
            if calls["fetch"] < 3:
                return True, []
            return True, [make_roster_entry(SID)]

        def sleep(s):
            sleeps.append(s)
            clock.advance(s)

        sid = fleet._join_roster_by_short_id("aaaabbbb", fetch, sleep, clock=clock)
        assert sid == SID
        assert calls["fetch"] == 3
        assert sleeps == [fleet.NATIVE_JOIN_POLL_SECONDS, fleet.NATIVE_JOIN_POLL_SECONDS]

    def test_exclude_sids_skips_foreign_prefix_match(self):
        foreign = "aaaabbbb-9999-8888-7777-666655554444"
        real = "aaaabbbb-1111-2222-3333-444455556666"

        def fetch(**_):
            return True, [make_roster_entry(foreign), make_roster_entry(real)]

        sid = fleet._join_roster_by_short_id("aaaabbbb", fetch, lambda s: None,
                                             exclude_sids={foreign})
        assert sid == real

    def test_exclude_sids_only_foreign_present_expires(self):
        foreign = "aaaabbbb-9999-8888-7777-666655554444"
        clock = _FakeClock()

        def fetch(**_):
            return True, [make_roster_entry(foreign)]

        def sleep(s):
            clock.advance(s)

        sid = fleet._join_roster_by_short_id("aaaabbbb", fetch, sleep,
                                             exclude_sids={foreign}, clock=clock)
        assert sid is None


class TestFastCompletionSid:
    """T4 fix wave (Critical C1): _fast_completion_sid must locate the Stop
    hook's sid-keyed fallback outcome file, not just a name-keyed one --
    the fallback file is what the real hook actually writes during the
    fast-completion race (see the end-to-end subprocess test below, which
    reproduces the adversarial review's Trap 1)."""

    def test_short_id_scan_finds_sid_keyed_file(self, native_home):
        # No name-keyed file at all -- only the sid-keyed fallback the real
        # hook would have written.
        fleet.append_outcome(SID, {"ts": _iso(NOW), "session_id": SID,
                                   "kind": "result", "result_text": "done"})
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)),
                                           short_id="aaaabbbb")
        assert found == SID

    def test_short_id_scan_ignores_non_matching_prefix(self, native_home):
        other_sid = "ffffffff-1111-2222-3333-444455556666"
        fleet.append_outcome(other_sid, {"ts": _iso(NOW), "session_id": other_sid,
                                         "kind": "result"})
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)),
                                           short_id="aaaabbbb")
        assert found is None

    def test_short_id_scan_respects_freshness_window(self, native_home):
        fleet.append_outcome(SID, {"ts": _iso(NOW - timedelta(minutes=10)),
                                   "session_id": SID, "kind": "result"})
        found = fleet._fast_completion_sid("w1", _iso(NOW), short_id="aaaabbbb")
        assert found is None

    def test_no_short_id_does_not_scan_outcomes_dir(self, native_home):
        # short_id=None (the default) -- behavior-identical to the
        # pre-fix-wave function: name-keyed only.
        fleet.append_outcome(SID, {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)))
        assert found is None

    # T5 fix wave (Critical C1 audit): a tombstone can't mean fast
    # completion -- only a Stop-hook-written kind=="result" record should
    # ever be returned.
    @pytest.mark.parametrize("kind", fleet.TOMBSTONE_KINDS)
    def test_tombstone_kind_is_never_a_fast_completion_sid(self, native_home, kind):
        fleet.write_tombstone_outcome(SID, SID, kind)
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)),
                                           short_id="aaaabbbb")
        assert found is None

    def test_result_kind_still_found_alongside_tombstone(self, native_home):
        # A tombstone is present too, but must not shadow/confuse the
        # genuine result-kind match.
        fleet.write_tombstone_outcome(SID, SID, "interrupted")
        fleet.append_outcome(SID, {"ts": _iso(NOW), "session_id": SID,
                                   "kind": "result", "result_text": "done"})
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)),
                                           short_id="aaaabbbb")
        assert found == SID

    def test_prefers_freshest_across_both_sources(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-name-keyed",
                                    "kind": "result"})
        fleet.append_outcome(SID, {"ts": _iso(NOW + timedelta(seconds=5)),
                                   "session_id": SID, "kind": "result"})
        found = fleet._fast_completion_sid("w1", _iso(NOW - timedelta(seconds=1)),
                                           short_id="aaaabbbb")
        assert found == SID

    def test_end_to_end_real_stop_hook_writes_sid_keyed_fallback(self, native_home, monkeypatch):
        """Adversarial Trap 1 repro, pinned as a regression test: cmd_spawn
        pre-claims a record (session_id=None). Mid-join-poll, the REAL
        `bin/hooks/stop_outcome.py` fires as a subprocess against this same
        temp FLEET_HOME with the true final sid -- at that exact instant
        the registry still has session_id=None, so the hook's own
        _resolve_name scan cannot match it, and the hook falls back to
        writing outcomes/<real-sid>.jsonl (sid-keyed), never
        outcomes/w1.jsonl (name-keyed). The join itself then expires
        (never observes the session on the roster). cmd_spawn's
        fast-completion recovery must still find the hook's sid-keyed
        file via the short id and commit idle with the real sid -- NOT
        roll back and discard the already-completed task."""
        # Roster never reports the session -- models a daemon that never
        # registers it on the roster despite the worker finishing, forcing
        # the join to run out the clock.
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        def fake_run(argv, **kwargs):
            # Fires INSIDE dispatch_bg, after cmd_spawn's real pre-claim
            # lock has already written the registry record with
            # session_id=None (exactly the production sequence) -- models
            # the real Stop hook firing mid-join-poll, with the true final
            # sid, at the exact instant the registry cannot yet resolve a
            # name for it.
            assert fleet.load_registry()["workers"]["w1"]["session_id"] is None
            payload = json.dumps({"session_id": SID,
                                  "last_assistant_message": "already done -- fast completion"})
            env = dict(os.environ)
            env["FLEET_HOME"] = str(native_home)
            proc = subprocess.run([*PY_CMD, str(STOP_OUTCOME_HOOK)], input=payload,
                                  capture_output=True, text=True, env=env, timeout=15)
            assert proc.returncode == 0
            import types
            return types.SimpleNamespace(returncode=0,
                stdout="backgrounded · aaaabbbb · fleet|w1|t\n", stderr="")

        clock = _FakeClock()
        rc = fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=fake_run,
                             which=lambda _: "claude",
                             sleep=lambda s: clock.advance(s), clock=clock)
        assert rc == 0

        sid_keyed = native_home / "state" / "outcomes" / f"{SID}.jsonl"
        name_keyed = native_home / "state" / "outcomes" / "w1.jsonl"
        assert sid_keyed.exists()
        assert not name_keyed.exists()  # confirms the hook's actual fallback shape

        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle"
        assert rec["session_id"] == SID  # never rolled back -- the completed task is preserved


def _spawn_args(name="w1", d="C:/proj", task="do it", **kw):
    from types import SimpleNamespace
    base = dict(name=name, dir=d, task=task, mode="accept", model=None,
                max_budget_usd=None, setting_sources=None, token_ceiling=None,
                category=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestCmdSpawnNative:
    # cmd_spawn validates --dir is a real directory (unlike dispatch_bg,
    # which never touches the filesystem for cwd) -- every call here passes
    # d=str(native_home) so the brief's placeholder "C:/proj" (never created
    # on a real machine) doesn't trip that check before reaching the code
    # under test.
    def test_spawn_native_stamps_sid_and_short_id(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        rc = fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=_fake_run_factory(),
                             which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["dispatch_kind"] == "bg"
        assert rec["session_id"] == SID and rec["native_short_id"] == "aaaabbbb"
        assert rec["status"] == "working" and rec["turns"] == 1
        assert rec["last_dispatch_at"] is not None

    def test_spawn_stamps_category_and_writes_ceiling_file(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        rc = fleet.cmd_spawn(_spawn_args(d=str(native_home), category="camp5", token_ceiling=5000),
                             run=_fake_run_factory(), which=lambda _: "claude",
                             sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["category"] == "camp5"
        assert fleet.ceiling_file_path(SID).exists()

    def test_spawn_refuses_usd_budget(self, native_home):
        with pytest.raises(fleet.FleetCliError, match="token-ceiling"):
            fleet.cmd_spawn(_spawn_args(d=str(native_home), max_budget_usd=5.0),
                            run=_fake_run_factory(), which=lambda _: "claude",
                            sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}

    def test_dispatch_failure_rolls_back_preclaim(self, native_home, monkeypatch):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=_fake_run_factory(rc=1),
                            which=lambda _: "claude", sleep=lambda s: None)
        assert fleet.load_registry()["workers"] == {}

    def test_join_expiry_with_fast_completion_outcome_commits_idle(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        fleet.append_outcome("w1", {"ts": fleet.now_iso(),
                                    "session_id": SID, "kind": "result",
                                    "result_text": "already done"})
        clock = _FakeClock()
        rc = fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=_fake_run_factory(),
                             which=lambda _: "claude",
                             sleep=lambda s: clock.advance(s), clock=clock)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle" and rec["session_id"] == SID

    def test_join_expiry_without_outcome_is_doa_rollback(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        clock = _FakeClock()
        with pytest.raises(fleet.FleetCliError, match="aaaabbbb"):
            fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=_fake_run_factory(),
                            which=lambda _: "claude",
                            sleep=lambda s: clock.advance(s), clock=clock)
        assert fleet.load_registry()["workers"] == {}

    def test_spawn_events_written_under_same_lock_as_mutation(self, native_home, monkeypatch):
        # F4: append_event calls happen for "spawned" (pre-claim) and
        # "turn_started" (post-stamp) -- both present, in order.
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with())
        events_path = native_home / "state" / "events.jsonl"
        fleet.cmd_spawn(_spawn_args(d=str(native_home)), run=_fake_run_factory(),
                        which=lambda _: "claude", sleep=lambda s: None)
        kinds = [json.loads(ln)["kind"] for ln in
                events_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert kinds == ["spawned", "turn_started"]


# ---------------------------------------------------------------------------
# M-B Task 5: outcome discriminator, epoch freeze, status/wait integration
# ---------------------------------------------------------------------------

def _fixed_roster(ok=True, entries=None):
    """Unlike _roster_with (dispatch_bg's two-phase pre/post snapshot), T5's
    callers (cmd_status/wait_for_workers) each do exactly ONE fetch per
    invocation -- every call gets the same fixed answer."""
    def fetch(**_):
        return ok, ([] if entries is None else entries)
    return fetch


def _status_args(name=None, **kw):
    from types import SimpleNamespace
    base = dict(name=name, json=False, stale_ok=False)
    base.update(kw)
    return SimpleNamespace(**base)


def _wait_args(names, any=False, timeout=None):
    from types import SimpleNamespace
    return SimpleNamespace(names=names, any=any, timeout=timeout)


def _events_kinds(home):
    path = home / "state" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln)["kind"] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


SID2 = "ccccdddd-1111-2222-3333-444455556666"


def _wedge_env(second_healthy=True, calls=None):
    """Coupled run/roster fakes for the never-attach wedge (live finding #2,
    2026-07-16). Attempt 1's session (SID, short aaaabbbb) joins the roster
    but stays state-only FOREVER -- the wedge shape. Attempt 2's session
    (SID2, short ccccdddd) is live (status+pid) when `second_healthy`, else
    wedged the same way."""
    state = {"bg": 0}

    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append(argv)
        import types
        if "--bg" in argv:
            state["bg"] += 1
            short = "aaaabbbb" if state["bg"] == 1 else "ccccdddd"
            return types.SimpleNamespace(
                returncode=0, stdout=f"backgrounded · {short} · fleet|w1|t\n",
                stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def fetch(**_):
        entries = []
        if state["bg"] >= 1:
            entries.append({"id": "aaaabbbb", "sessionId": SID,
                            "name": "fleet|w1|t", "kind": "background",
                            "state": "working"})  # wedged: state-only forever
        if state["bg"] >= 2:
            e = {"id": "ccccdddd", "sessionId": SID2, "name": "fleet|w1|t",
                 "kind": "background", "state": "working"}
            if second_healthy:
                e["status"] = "busy"
                e["pid"] = 4242
            entries.append(e)
        return True, entries

    return fake_run, fetch


class TestAwaitAttach:
    def _clocked(self):
        clock = _FakeClock()
        return clock, (lambda s: clock.advance(s))

    def test_status_or_pid_is_attached(self, native_home):
        clock, sleep = self._clocked()
        fetch = lambda **_: (True, [make_roster_entry(SID, status="busy")])  # noqa: E731
        assert fleet._await_attach("w1", SID, fetch, sleep, clock) is True

    def test_state_only_then_live_attaches(self, native_home):
        clock, sleep = self._clocked()
        seq = _roster_sequence(
            (True, [make_roster_entry(SID, status=None, pid=None, state="working")]),
            (True, [make_roster_entry(SID, status="busy")]),
        )
        assert fleet._await_attach("w1", SID, seq, sleep, clock) is True

    def test_entry_gone_after_join_is_not_a_wedge(self, native_home):
        clock, sleep = self._clocked()
        assert fleet._await_attach("w1", SID, lambda **_: (True, []),
                                   sleep, clock) is True

    @pytest.mark.parametrize("literal", ["done", "failed", "stopped", "blocked"])
    def test_terminal_state_literal_means_it_ran(self, native_home, literal):
        clock, sleep = self._clocked()
        entry = make_roster_entry(SID, status=None, pid=None, state=literal)
        assert fleet._await_attach("w1", SID, lambda **_: (True, [entry]),
                                   sleep, clock) is True

    def test_outcome_record_means_it_completed(self, native_home):
        clock, sleep = self._clocked()
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID,
                                    "kind": "result"})
        entry = make_roster_entry(SID, status=None, pid=None, state="working")
        assert fleet._await_attach("w1", SID, lambda **_: (True, [entry]),
                                   sleep, clock) is True

    def test_state_only_forever_is_the_wedge(self, native_home):
        clock, sleep = self._clocked()
        entry = make_roster_entry(SID, status=None, pid=None, state="working")
        assert fleet._await_attach("w1", SID, lambda **_: (True, [entry]),
                                   sleep, clock) is False
        assert clock.t >= fleet.NATIVE_ATTACH_VERIFY_SECONDS

    def test_fetch_failure_retried_never_a_wedge_verdict_early(self, native_home):
        clock, sleep = self._clocked()
        seq = _roster_sequence(
            (False, "transient"),
            (True, [make_roster_entry(SID, status="busy")]),
        )
        assert fleet._await_attach("w1", SID, seq, sleep, clock) is True


class TestDispatchWedgeRetry:
    def _dispatch(self, run, fetch, clock=None):
        clock = clock or _FakeClock()
        return fleet.dispatch_bg(
            "w1", "C:/proj", "b", "accept", run=run, which=lambda _: "claude",
            sleep=lambda s: clock.advance(s), roster_fetch=fetch, clock=clock)

    def test_wedge_then_healthy_retries_once_returns_second_sid(self, native_home):
        calls = []
        run, fetch = _wedge_env(second_healthy=True, calls=calls)
        out = self._dispatch(run, fetch)
        assert out["session_id"] == SID2 and out["short_id"] == "ccccdddd"
        bg = [a for a in calls if "--bg" in a]
        assert len(bg) == 2
        # the wedged session was stopped AND removed, by short id
        assert ["claude", "stop", "aaaabbbb"] in calls
        assert ["claude", "rm", "aaaabbbb"] in calls
        kinds = _events_kinds(native_home)
        assert kinds.count("dispatch_wedged") == 1
        assert kinds.count("dispatch_retried") == 1

    def test_wedge_then_wedge_gives_up_loudly(self, native_home):
        calls = []
        run, fetch = _wedge_env(second_healthy=False, calls=calls)
        with pytest.raises(fleet.NativeDispatchError, match="never attached") as exc:
            self._dispatch(run, fetch)
        assert exc.value.short_id == "ccccdddd"
        assert len([a for a in calls if "--bg" in a]) == 2  # EXACTLY once retried
        for short in ("aaaabbbb", "ccccdddd"):
            assert ["claude", "stop", short] in calls
            assert ["claude", "rm", short] in calls
        kinds = _events_kinds(native_home)
        assert kinds.count("dispatch_wedged") == 2
        assert kinds.count("dispatch_retried") == 1

    def test_healthy_dispatch_never_retries_no_wedge_events(self, native_home):
        calls = []
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                                run=_fake_run_factory(calls=calls),
                                which=lambda _: "claude", sleep=lambda s: None,
                                roster_fetch=_roster_with())
        assert out["session_id"] == SID
        assert len([a for a, _kw in calls if "--bg" in a]) == 1
        kinds = _events_kinds(native_home)
        assert "dispatch_wedged" not in kinds and "dispatch_retried" not in kinds

    def test_fresh_presnapshot_excludes_foreign_prefix_collision(self, native_home):
        """M1 (review): the real reason each attempt takes a FRESH
        pre-snapshot. The wedged sid itself can never collide (join is
        short-id-prefix based; attempt 2 gets a different prefix) -- the
        hazard is a FOREIGN session appearing DURING attempt 1 whose sid
        happens to share attempt 2's short-id prefix. A stale (attempt-1)
        snapshot predates it and would bind the foreign session; the fresh
        snapshot excludes it."""
        foreign = "ccccdddd-ffff-ffff-ffff-ffffffffffff"
        state = {"bg": 0}

        def fake_run(argv, **kwargs):
            import types
            if "--bg" in argv:
                state["bg"] += 1
                short = "aaaabbbb" if state["bg"] == 1 else "ccccdddd"
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=f"backgrounded · {short} · fleet|w1|t\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def fetch(**_):
            entries = []
            if state["bg"] >= 1:
                # foreign session, minted during attempt 1, FIRST in the
                # roster -- a stale snapshot would let join bind it
                entries.append({"id": "ccccdddd", "sessionId": foreign,
                                "name": "operator session",
                                "kind": "background", "state": "working",
                                "status": "busy", "pid": 999})
                entries.append({"id": "aaaabbbb", "sessionId": SID,
                                "name": "fleet|w1|t", "kind": "background",
                                "state": "working"})  # wedged
            if state["bg"] >= 2:
                entries.append({"id": "ccccdddd", "sessionId": SID2,
                                "name": "fleet|w1|t", "kind": "background",
                                "state": "working", "status": "busy",
                                "pid": 4242})
            return True, entries

        clock = _FakeClock()
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                                which=lambda _: "claude",
                                sleep=lambda s: clock.advance(s),
                                roster_fetch=fetch, clock=clock)
        assert out["session_id"] == SID2  # never the foreign prefix-collider

    def test_c1_stop_failure_and_live_recheck_refuses_retry(self, native_home):
        """C1 CRITICAL (review injection 3b): stop/rm exit 1 on the wedge
        path while the 'wedged' session comes alive -- redispatching would
        put two live sessions on one task file with only sid2 tracked.
        The retry must be REFUSED: check the stop/rm booleans, re-fetch
        the roster, and raise unless the entry is verifiably gone or still
        status/pid-free."""
        state = {"bg": 0, "stop_attempted": False}

        def fake_run(argv, **kwargs):
            import types
            if "--bg" in argv:
                state["bg"] += 1
                return types.SimpleNamespace(
                    returncode=0,
                    stdout="backgrounded · aaaabbbb · fleet|w1|t\n", stderr="")
            if len(argv) >= 2 and argv[1] in ("stop", "rm"):
                state["stop_attempted"] = True
                return types.SimpleNamespace(returncode=1, stdout="",
                                             stderr="daemon busy")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def fetch(**_):
            if state["bg"] == 0:
                return True, []
            entry = {"id": "aaaabbbb", "sessionId": SID, "name": "fleet|w1|t",
                     "kind": "background", "state": "working"}
            if state["stop_attempted"]:
                # came alive under the same overload that failed the stop
                entry["status"] = "busy"
                entry["pid"] = 31337
            return True, [entry]

        clock = _FakeClock()
        with pytest.raises(fleet.NativeDispatchError, match="refus"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                              which=lambda _: "claude",
                              sleep=lambda s: clock.advance(s),
                              roster_fetch=fetch, clock=clock)
        assert state["bg"] == 1  # retry NEVER dispatched
        kinds = _events_kinds(native_home)
        assert "dispatch_retried" not in kinds

    def test_c1_stop_failure_but_still_unattached_recheck_allows_retry(self, native_home):
        """Companion: stop/rm failed but the recheck shows the entry still
        status/pid-free -- the reviewer's prescribed safe condition; the
        single retry proceeds."""
        state = {"bg": 0}

        def fake_run(argv, **kwargs):
            import types
            if "--bg" in argv:
                state["bg"] += 1
                short = "aaaabbbb" if state["bg"] == 1 else "ccccdddd"
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=f"backgrounded · {short} · fleet|w1|t\n", stderr="")
            if len(argv) >= 2 and argv[1] in ("stop", "rm"):
                return types.SimpleNamespace(returncode=1, stdout="",
                                             stderr="daemon busy")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def fetch(**_):
            entries = []
            if state["bg"] >= 1:
                entries.append({"id": "aaaabbbb", "sessionId": SID,
                                "name": "fleet|w1|t", "kind": "background",
                                "state": "working"})  # still unattached
            if state["bg"] >= 2:
                entries.append({"id": "ccccdddd", "sessionId": SID2,
                                "name": "fleet|w1|t", "kind": "background",
                                "state": "working", "status": "busy",
                                "pid": 4242})
            return True, entries

        clock = _FakeClock()
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                                which=lambda _: "claude",
                                sleep=lambda s: clock.advance(s),
                                roster_fetch=fetch, clock=clock)
        assert out["session_id"] == SID2
        assert state["bg"] == 2

    def test_c1_stop_failure_and_recheck_blackout_refuses_retry(self, native_home):
        """Stop failed AND the verification re-fetch itself fails: cannot
        verify => cannot retry."""
        state = {"bg": 0, "stop_attempted": False}

        def fake_run(argv, **kwargs):
            import types
            if "--bg" in argv:
                state["bg"] += 1
                return types.SimpleNamespace(
                    returncode=0,
                    stdout="backgrounded · aaaabbbb · fleet|w1|t\n", stderr="")
            if len(argv) >= 2 and argv[1] in ("stop", "rm"):
                state["stop_attempted"] = True
                return types.SimpleNamespace(returncode=1, stdout="", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def fetch(**_):
            if state["stop_attempted"]:
                return False, "roster unavailable"
            if state["bg"] == 0:
                return True, []
            return True, [{"id": "aaaabbbb", "sessionId": SID,
                           "name": "fleet|w1|t", "kind": "background",
                           "state": "working"}]

        clock = _FakeClock()
        with pytest.raises(fleet.NativeDispatchError, match="refus"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                              which=lambda _: "claude",
                              sleep=lambda s: clock.advance(s),
                              roster_fetch=fetch, clock=clock)
        assert state["bg"] == 1

    def test_h1_full_attach_blackout_aborts_never_stops(self, native_home):
        """H1 HIGH (review): a full-window roster blackout during attach
        verification is CANNOT-VERIFY, not a wedge -- stopping a session we
        cannot see could kill it mid-tool-run. Abort the dispatch loudly;
        zero stop/rm calls."""
        state = {"bg": 0, "post_join": False}
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            import types
            if "--bg" in argv:
                state["bg"] += 1
                return types.SimpleNamespace(
                    returncode=0,
                    stdout="backgrounded · aaaabbbb · fleet|w1|t\n", stderr="")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        def fetch(**_):
            if state["bg"] == 0:
                return True, []
            if not state["post_join"]:
                state["post_join"] = True  # the join sighting
                return True, [{"id": "aaaabbbb", "sessionId": SID,
                               "name": "fleet|w1|t", "kind": "background",
                               "state": "working"}]
            return False, "roster blackout"

        clock = _FakeClock()
        with pytest.raises(fleet.NativeDispatchError, match="verif"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept", run=fake_run,
                              which=lambda _: "claude",
                              sleep=lambda s: clock.advance(s),
                              roster_fetch=fetch, clock=clock)
        assert not any(len(a) >= 2 and a[1] in ("stop", "rm") for a in calls)
        assert state["bg"] == 1
        assert "dispatch_wedged" not in _events_kinds(native_home)


class TestNativeRecompute:
    def _rec(self, native_home, status="working", **kw):
        return seed_native_worker(native_home, status=status, **kw)

    def test_roster_busy_stays_working(self, native_home):
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="busy")])
        assert out["status"] == "working"

    def test_roster_waiting_stays_working_and_flags_permission(self, native_home):
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="waiting")])
        assert out["status"] == "working"
        assert out["waiting_for_permission"] is True

    def test_roster_idle_with_fresh_outcome_goes_idle(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "idle"

    def test_roster_idle_without_outcome_is_dead_suspected(self, native_home):
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"

    def test_stale_outcome_from_prior_dispatch_does_not_vouch(self, native_home):
        rec = self._rec(native_home, last_dispatch_at=_iso(NOW))
        fleet.append_outcome("w1", {"ts": _iso(NOW - timedelta(hours=2)),
                                    "session_id": SID, "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"

    def test_predecessor_sid_record_does_not_vouch(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "old-dead-sid",
                                    "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "dead-suspected"

    def test_roster_gone_with_fresh_outcome_is_completed(self, native_home):
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "idle"

    def test_roster_dead_entry_state_only_is_not_live(self, native_home):
        # state-only entry (no status/pid key) -- contract: not live, treated
        # the same as roster-gone, never inspect `state` alone.
        rec = self._rec(native_home)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        entry = make_roster_entry(SID, status=None, pid=None, state="done")
        out = fleet.recompute_worker_native("w1", rec, [entry])
        assert out["status"] == "idle"

    def test_sticky_statuses_pass_through(self, native_home):
        for sticky in ("dead", "limited", "over_ceiling", "interrupted", "attached", "over_budget"):
            rec = self._rec(native_home, status=sticky)
            out = fleet.recompute_worker_native("w1", rec, [])
            assert out["status"] == sticky

    def test_dead_suspected_is_reversible(self, native_home):
        rec = self._rec(native_home, status="dead-suspected",
                        last_dispatch_at=_iso(NOW - timedelta(minutes=5)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "idle"

    def test_no_fresh_outcome_with_limit_scan_hook_parks_limited(self, native_home, monkeypatch):
        monkeypatch.setattr(fleet, "_limit_scan_hook",
                            lambda sid, **kw: (True, "2026-07-16T00:00:00Z", "session_5h"))
        rec = self._rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "limited"
        assert out["limit_reset_at"] == "2026-07-16T00:00:00Z"
        assert out["limit_kind"] == "session_5h"

    def test_in_flight_preclaim_stays_working_until_claim_expires(self, native_home):
        rec = self._rec(native_home, session_id=None, last_activity=fleet.now_iso())
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "working"

    def test_in_flight_preclaim_expires_to_dead(self, native_home):
        stale = _iso(NOW - timedelta(hours=1))
        rec = self._rec(native_home, session_id=None, last_activity=stale)
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "dead"

    # T5 fix wave (Critical C1): task-5-adversarial.md's exact laundering
    # repro. A fresh fleet-written tombstone for the CURRENT sid, landed
    # (e.g. by a future T8 cmd_kill) before the registry status flip
    # caught up, must never make the discriminator vouch "idle" -- it
    # should fall through to _investigate_no_outcome (dead-suspected),
    # honestly uncertain rather than falsely "done". Roster still reports
    # idle (models the race window: the process is gone/idle on the
    # roster, but the ONLY outcome record is the tombstone, not a result).
    @pytest.mark.parametrize("kind", fleet.TOMBSTONE_KINDS)
    def test_fresh_tombstone_never_launders_to_idle(self, native_home, kind):
        rec = self._rec(native_home, status="working",
                        last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        fleet.write_tombstone_outcome("w1", SID, kind)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] != "idle"
        assert out["status"] == "dead-suspected"

    @pytest.mark.parametrize("kind", fleet.TOMBSTONE_KINDS)
    def test_fresh_tombstone_never_launders_to_idle_roster_gone(self, native_home, kind):
        # Same trap via the roster-gone branch (recompute_worker_native's
        # OTHER has_fresh_outcome call site).
        rec = self._rec(native_home, status="working",
                        last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        fleet.write_tombstone_outcome("w1", SID, kind)
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] != "idle"
        assert out["status"] == "dead-suspected"


class TestDispatchGraceWindow:
    """Live finding 2026-07-16 (pin suite RED 3/6): a freshly dispatched
    --bg session's roster entry carries STATE ONLY ({'state':'working'},
    no status/pid) for its first seconds -- status+pid appear only once
    the process attaches. The field-presence rule reads state-only as
    dead, so the no-outcome investigation verdicted a healthy 1.5s-old
    worker dead-suspected and `fleet wait` returned instantly (the pin
    repro). Within the dispatch grace window (same principle and constant
    as the sid=None pre-claim guard, anchored on last_dispatch_at) the
    verdict must stay `working`."""

    def _fresh_rec(self, native_home, seconds_ago=2, **kw):
        return seed_native_worker(
            native_home, status="working",
            last_dispatch_at=_iso(
                datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)),
            **kw)

    def test_state_only_entry_within_grace_stays_working(self, native_home):
        rec = self._fresh_rec(native_home)
        entry = make_roster_entry(SID, status=None, pid=None, state="working")
        out = fleet.recompute_worker_native("w1", rec, [entry])
        assert out["status"] == "working"

    def test_roster_gone_within_grace_stays_working(self, native_home):
        rec = self._fresh_rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "working"

    def test_state_only_past_grace_no_outcome_dead_suspected(self, native_home):
        # existing behavior pinned: past the window, today's verdict holds
        rec = self._fresh_rec(native_home,
                              seconds_ago=fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS + 60)
        entry = make_roster_entry(SID, status=None, pid=None, state="working")
        out = fleet.recompute_worker_native("w1", rec, [entry])
        assert out["status"] == "dead-suspected"

    def test_state_only_with_fresh_outcome_goes_idle(self, native_home):
        # turn completed during the window: the fresh-outcome check runs
        # BEFORE the grace check, so completion is never masked as working
        rec = self._fresh_rec(native_home)
        fleet.append_outcome("w1", {"ts": fleet.now_iso(), "session_id": SID,
                                    "kind": "result"})
        entry = make_roster_entry(SID, status=None, pid=None, state="done")
        out = fleet.recompute_worker_native("w1", rec, [entry])
        assert out["status"] == "idle"

    def test_limit_park_wins_over_grace(self, native_home, monkeypatch):
        # a limit wall detected in the transcript parks limited even inside
        # the window -- grace only guards the dead-suspected demotion
        monkeypatch.setattr(fleet, "_limit_scan_hook",
                            lambda sid, **kw: (True, "2026-07-17T00:00:00Z", "session_5h"))
        rec = self._fresh_rec(native_home)
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "limited"


class TestEpochFreeze:
    def test_fetch_failure_is_suspicious(self):
        assert fleet.native_epoch_suspicious(False, "no claude", {}) is True

    def test_empty_roster_with_live_native_worker_is_suspicious(self, native_home):
        rec = seed_native_worker(native_home)
        assert fleet.native_epoch_suspicious(True, [], {"w1": rec}) is True

    def test_empty_roster_with_no_native_workers_is_fine(self):
        assert fleet.native_epoch_suspicious(True, [], {}) is False

    def test_nonempty_roster_is_never_suspicious(self, native_home):
        rec = seed_native_worker(native_home)
        assert fleet.native_epoch_suspicious(True, [make_roster_entry("other-sid")], {"w1": rec}) is False

    def test_limited_worker_is_native_but_never_the_suspicion_signal(self, native_home):
        # limited is sticky (never demoted by the freeze) -- it must not be
        # what trips the "any native worker still working" check either.
        rec = seed_native_worker(native_home, status="limited")
        assert fleet.native_epoch_suspicious(True, [], {"w1": rec}) is False


class TestWorkerFlagsNative:
    def test_dead_suspected_flag(self, native_home):
        rec = seed_native_worker(native_home, status="dead-suspected")
        assert "investigate: no outcome record" in fleet._worker_flags(rec)

    def test_waiting_for_permission_flag(self, native_home):
        rec = seed_native_worker(native_home, status="working")
        rec["waiting_for_permission"] = True
        assert "waiting-permission" in fleet._worker_flags(rec)

    def test_no_flag_when_not_waiting(self, native_home):
        rec = seed_native_worker(native_home, status="working")
        assert "waiting-permission" not in fleet._worker_flags(rec)


class TestNativeTokenSummary:
    def test_summary_from_latest_outcome(self, native_home):
        seed_native_worker(native_home, status="working")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "input_tokens": 111, "output_tokens": 22})
        rec = fleet.load_registry()["workers"]["w1"]
        assert fleet._native_token_summary("w1", rec) == "tokens:in=111 out=22"

    def test_empty_without_outcome(self, native_home):
        rec = seed_native_worker(native_home, status="working")
        assert fleet._native_token_summary("w1", rec) == ""


class TestCmdStatusNative:
    def test_native_busy_stays_working(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="busy")]))

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "working"

    def test_epoch_freeze_prints_warning_and_freezes_native_write(self, native_home, monkeypatch, capsys):
        rec = seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _fixed_roster(False, None))

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "EPOCH: roster suspicious -- verdicts frozen (G9)" in out
        assert fleet.load_registry()["workers"]["w1"] == rec

    def test_dead_suspected_event_fires_once_not_per_rerun(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))

        fleet.cmd_status(_status_args())
        fleet.cmd_status(_status_args())

        kinds = _events_kinds(native_home)
        assert kinds.count("dead_suspected") == 1
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead-suspected"

    def test_dead_suspected_flips_back_to_idle_on_later_outcome(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        fleet.cmd_status(_status_args())
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead-suspected"

        fleet.append_outcome("w1", {"ts": fleet.now_iso(), "session_id": SID, "kind": "result"})
        fleet.cmd_status(_status_args())
        assert fleet.load_registry()["workers"]["w1"]["status"] == "idle"

    def test_limited_suspected_event_and_horizon_fields(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        monkeypatch.setattr(fleet, "_limit_scan_hook",
                            lambda sid, **kw: (True, "2026-07-16T00:00:00Z", "session_5h"))

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "limited"
        assert rec["limit_reset_at"] == "2026-07-16T00:00:00Z"
        assert rec["limit_kind"] == "session_5h"
        assert "limited_suspected" in _events_kinds(native_home)

    def test_limited_is_sticky_never_demoted_by_epoch_freeze(self, native_home, monkeypatch):
        rec = seed_native_worker(native_home, status="limited", limit_reset_at=None, limit_kind=None)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _fixed_roster(False, None))

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "limited"

    # T5 fix wave (Important I1): waiting_for_permission is transient --
    # recomputed fresh from the roster every call -- and must never land in
    # the persisted registry (new_worker_record's baseline schema doesn't
    # enumerate it, unlike every other optional field).
    def test_waiting_for_permission_not_persisted_to_registry(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="waiting")]))
        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        raw = json.loads((native_home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert "waiting_for_permission" not in raw["workers"]["w1"]

    def test_waiting_for_permission_still_shown_in_printed_table(self, native_home, monkeypatch, capsys):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="waiting")]))
        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "waiting-permission" in out

    def test_waiting_for_permission_does_not_survive_a_second_call_either(self, native_home, monkeypatch):
        # Two consecutive calls -- self-heal isn't the only requirement
        # now: it must never have persisted in the first place.
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="waiting")]))
        fleet.cmd_status(_status_args())
        fleet.cmd_status(_status_args())
        raw = json.loads((native_home / "state" / "fleet.json").read_text(encoding="utf-8"))
        assert "waiting_for_permission" not in raw["workers"]["w1"]


class TestWaitForWorkersNative:
    def test_native_busy_stays_pending_until_timeout(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="busy")]))
        clock = _FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["w1"], timeout=1.0, poll_interval=0.5,
            sleep=lambda s: clock.advance(s), clock=clock)
        assert pending == {"w1"}
        assert finished == {}

    def test_native_idle_with_fresh_outcome_finishes(self, native_home, monkeypatch):
        seed_native_worker(native_home, last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        finished, pending = fleet.wait_for_workers(["w1"], timeout=1.0, poll_interval=0.1,
                                                    sleep=lambda s: None)
        assert pending == set()
        assert finished == {"w1": "idle"}

    def test_native_dead_suspected_is_terminal_for_wait(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        finished, pending = fleet.wait_for_workers(["w1"], timeout=1.0, poll_interval=0.1,
                                                    sleep=lambda s: None)
        assert pending == set()
        assert finished == {"w1": "dead-suspected"}

    def test_epoch_frozen_native_stays_pending(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _fixed_roster(False, None))
        clock = _FakeClock()
        finished, pending = fleet.wait_for_workers(
            ["w1"], timeout=1.0, poll_interval=0.5,
            sleep=lambda s: clock.advance(s), clock=clock)
        assert pending == {"w1"}
        assert finished == {}

    def test_one_roster_fetch_per_poll_shared_across_names(self, native_home, monkeypatch):
        seed_native_worker(native_home, name="w1", status="working")
        seed_native_worker(native_home, name="w2", status="working",
                           sid="bbbbcccc-1111-2222-3333-444455556666")
        calls = []

        def fetch(**_):
            calls.append(1)
            return True, [make_roster_entry(SID, status="busy"),
                          make_roster_entry("bbbbcccc-1111-2222-3333-444455556666", status="busy")]
        monkeypatch.setattr(fleet, "_fetch_agents_roster", fetch)
        clock = _FakeClock()
        fleet.wait_for_workers(["w1", "w2"], timeout=0.1, poll_interval=0.1,
                               sleep=lambda s: clock.advance(s), clock=clock)
        # exactly one fetch per poll iteration, not one per pending name
        assert len(calls) <= 2


class TestCmdWaitNative:
    def test_persists_dead_suspected_and_event(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        rc = fleet.cmd_wait(_wait_args(["w1"]), sleep=lambda s: None, clock=_FakeClock())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead-suspected"
        assert "dead_suspected" in _events_kinds(native_home)

    def test_persists_idle_with_fresh_outcome(self, native_home, monkeypatch):
        seed_native_worker(native_home, last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))
        rc = fleet.cmd_wait(_wait_args(["w1"]), sleep=lambda s: None, clock=_FakeClock())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "idle"

    # T5 fix wave (Minor: print-vs-persist race, task-5-review.md M1):
    # wait_for_workers's poll loop and cmd_wait's own persist-step fetch
    # each do their own independent roster fetch. If they disagree (a
    # fresh outcome record lands, or the roster changes, in the narrow
    # window between the two), the summary line printed at the end must
    # reflect what actually got persisted to fleet.json, never the
    # earlier (now-stale) poll verdict.
    def test_printed_summary_matches_persisted_status_not_stale_poll_verdict(
            self, native_home, monkeypatch, capsys):
        seed_native_worker(native_home, status="working",
                           last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        # Stub wait_for_workers directly: models its poll loop having
        # concluded "dead-suspected" (no outcome record was visible yet at
        # poll time).
        monkeypatch.setattr(fleet, "wait_for_workers",
                            lambda *a, **k: ({"w1": "dead-suspected"}, set()))
        # Between that poll and cmd_wait's own persist-step roster fetch, a
        # fresh outcome record lands -- the persist step's recompute now
        # correctly resolves "idle", diverging from the stale poll verdict.
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="idle")]))

        rc = fleet.cmd_wait(_wait_args(["w1"]), sleep=lambda s: None, clock=_FakeClock())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "idle"
        out = capsys.readouterr().out
        assert "w1: idle" in out
        assert "dead-suspected" not in out

    def test_persist_step_epoch_freeze_prints_notice_and_persists_nothing(
            self, native_home, monkeypatch, capsys):
        # Debt roll-up item 9 (T5-era residual): when the persist step's own
        # roster fetch is suspicious (G9), the summary rows can only show the
        # pre-freeze poll verdict and nothing is written -- the output must
        # say so (same convention as cmd_status/cmd_clean's freeze line)
        # instead of letting the stale verdict read as current-and-committed.
        seed_native_worker(native_home, status="working",
                           last_dispatch_at=_iso(NOW - timedelta(minutes=1)))
        monkeypatch.setattr(fleet, "wait_for_workers",
                            lambda *a, **k: ({"w1": "dead-suspected"}, set()))
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(False, "roster fetch failed"))
        rc = fleet.cmd_wait(_wait_args(["w1"]), sleep=lambda s: None, clock=_FakeClock())
        assert rc == 0
        out = capsys.readouterr().out
        assert "w1: dead-suspected" in out
        assert "EPOCH" in out and "nothing persisted" in out
        # frozen: the record was left untouched, not demoted
        assert fleet.load_registry()["workers"]["w1"]["status"] == "working"


class TestSnapshotTableNative:
    """T5 fix wave (Minor: task-5-review.md M2) -- `_print_snapshot_table`/
    `status_snapshot` (`fleet status --stale-ok`) must render native rows'
    cost as "-" like `_print_status_table`'s G3 convention, never a stale/
    always-zero dollar figure. Nativeness is derived from the row's own
    `dispatch_kind` field -- no roster fetch (this view is file-only, per
    CLAUDE.md's view-isolation rule)."""

    def test_status_snapshot_row_carries_dispatch_kind(self, native_home):
        seed_native_worker(native_home, status="idle")
        row = fleet.status_snapshot()["workers"][0]
        assert row["dispatch_kind"] == "bg"

    def test_print_snapshot_table_native_row_renders_dash_cost(self, native_home, capsys):
        seed_native_worker(native_home, status="idle")
        snap = fleet.status_snapshot()
        fleet._print_snapshot_table(snap)
        out = capsys.readouterr().out
        row_line = next(l for l in out.splitlines() if l.startswith("w1"))
        assert "0.00" not in row_line

    def test_print_snapshot_table_legacy_row_still_renders_cost(self, native_home, capsys):
        rec = fleet.new_worker_record("legacy-sid-0000", "C:/proj", "do it", "accept")
        rec["status"] = "idle"
        rec["cost_usd"] = 1.23
        data = fleet.load_registry()
        data["workers"]["legacy1"] = rec
        fleet.save_registry(data)

        snap = fleet.status_snapshot()
        fleet._print_snapshot_table(snap)
        out = capsys.readouterr().out
        row_line = next(l for l in out.splitlines() if l.startswith("legacy1"))
        assert "1.23" in row_line

    def test_via_cmd_status_stale_ok_native_row_renders_dash_cost(self, native_home, capsys):
        seed_native_worker(native_home, status="idle")
        rc = fleet.cmd_status(_status_args(stale_ok=True))
        assert rc == 0
        out = capsys.readouterr().out
        row_line = next(l for l in out.splitlines() if l.startswith("w1"))
        assert "0.00" not in row_line


# ---------------------------------------------------------------------------
# M-B Task 6: usage-limit continuity -- transcript-tail scan, park,
# fork-steer resume (spec 5.1.1)
# ---------------------------------------------------------------------------

def _write_native_transcript(home, sid, records):
    proj = home / ".claude" / "projects" / "C--proj"
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return p


# Real observed G7 evidence shape (spike/m0/VERDICTS.md transcript record
# 201) -- binding fixture per task-6-brief.md.
LIMIT_RECORD = {
    "type": "assistant",
    "message": {"model": "<synthetic>", "role": "assistant",
                "content": [{"type": "text",
                             "text": "You've hit your session limit — resets 4:40am (Asia/Qyzylorda)"}]},
    "error": "rate_limit", "isApiErrorMessage": True, "apiErrorStatus": 429,
}


class TestTranscriptLimitScan:
    def test_synthetic_429_record_detected(self, native_home, tmp_path):
        t = _write_native_transcript(tmp_path, SID, [{"type": "user"}, LIMIT_RECORD])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert is_limit is True
        assert reset_at is None  # observed text is local-format, not ISO
        assert kind == "session_5h"

    def test_iso_reset_in_text_is_parsed(self, native_home, tmp_path):
        rec = json.loads(json.dumps(LIMIT_RECORD))
        rec["message"]["content"][0]["text"] = \
            "Weekly limit reached. It resets at 2026-07-16T09:00:00Z."
        t = _write_native_transcript(tmp_path, SID, [rec])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert (is_limit, reset_at, kind) == (True, "2026-07-16T09:00:00Z", "weekly")

    # The load-bearing negatives (port of TestFix2): conversation text about
    # rate limits, MCP-tool 429s, infra errors -- none carry isApiErrorMessage.
    @pytest.mark.parametrize("rec", [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "the API returned 429 rate limit, retrying"}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "usage limit exceeded on disk quota EDQUOT"}]}},
        {"type": "system", "subtype": "error", "text": "try again later"},
    ])
    def test_non_synthetic_shapes_do_not_park(self, native_home, tmp_path, rec):
        t = _write_native_transcript(tmp_path, SID, [rec])
        assert fleet.transcript_limit_scan(SID, transcript_path=t)[0] is False

    def test_missing_transcript_is_not_limit(self, native_home):
        assert fleet.transcript_limit_scan("no-such-sid")[0] is False

    def test_malformed_json_line_is_skipped_not_raised(self, native_home, tmp_path):
        proj = tmp_path / ".claude" / "projects" / "C--proj"
        proj.mkdir(parents=True)
        p = proj / f"{SID}.jsonl"
        p.write_text("{not json\n" + json.dumps(LIMIT_RECORD) + "\n", encoding="utf-8")
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=p)
        assert is_limit is True

    def test_newest_first_stops_at_first_match(self, native_home, tmp_path):
        older = json.loads(json.dumps(LIMIT_RECORD))
        older["message"]["content"][0]["text"] = "resets at 2026-07-15T00:00:00Z"
        newer = json.loads(json.dumps(LIMIT_RECORD))
        newer["message"]["content"][0]["text"] = "resets at 2026-07-16T00:00:00Z"
        t = _write_native_transcript(tmp_path, SID, [older, newer])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert reset_at == "2026-07-16T00:00:00Z"


class TestFindTranscriptPath:
    def test_prefers_outcome_store_transcript_path(self, native_home, tmp_path):
        real = tmp_path / "real.jsonl"
        real.write_text("{}\n", encoding="utf-8")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "transcript_path": str(real)})
        assert fleet.find_transcript_path("w1", SID) == real

    def test_skips_tombstone_null_transcript_path(self, native_home, tmp_path):
        # A tombstone carries transcript_path=None -- must never be mistaken
        # for a path donor even though it is the newer record.
        real = tmp_path / "real.jsonl"
        real.write_text("{}\n", encoding="utf-8")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "transcript_path": str(real)})
        fleet.write_tombstone_outcome("w1", SID, "killed")
        assert fleet.find_transcript_path("w1", SID) == real

    def test_falls_back_to_glob_when_no_outcome_path(self, native_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        t = _write_native_transcript(tmp_path, SID, [{"type": "user"}])
        assert fleet.find_transcript_path("w1", SID) == t

    def test_no_name_skips_outcome_lookup_globs_instead(self, native_home, tmp_path, monkeypatch):
        real = tmp_path / "real.jsonl"
        real.write_text("{}\n", encoding="utf-8")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "transcript_path": str(real)})
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        t = _write_native_transcript(tmp_path, SID, [{"type": "user"}])
        assert fleet.find_transcript_path(None, SID) == t

    def test_missing_sid_returns_none(self, native_home):
        assert fleet.find_transcript_path("w1", None) is None

    def test_nothing_found_returns_none(self, native_home, monkeypatch, tmp_path):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        assert fleet.find_transcript_path("w1", SID) is None


class TestLimitParkViaDiscriminator:
    """End-to-end through the REAL installed `_limit_scan_hook`
    (transcript_limit_scan) -- no hook monkeypatch here, unlike
    TestNativeRecompute's synthetic-hook tests above."""

    def test_idle_no_outcome_limit_transcript_parks_limited(self, native_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        rec = seed_native_worker(native_home)
        _write_native_transcript(tmp_path, SID, [LIMIT_RECORD])
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "limited"
        assert out["limit_kind"] == "session_5h"
        assert out["limit_reset_at"] is None

    def test_limited_stays_parked_never_dead_suspected(self, native_home):
        rec = seed_native_worker(native_home, status="limited")
        out = fleet.recompute_worker_native("w1", rec, [])
        assert out["status"] == "limited"

    def test_no_transcript_falls_to_dead_suspected(self, native_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        rec = seed_native_worker(native_home)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"


class TestNativeResumeLimited:
    def test_resume_fork_steers_and_restamps_sid(self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z", limit_kind="session_5h")
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with(new_sid))
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(
            args, run=_fake_run_factory(
                stdout="backgrounded · ccccdddd · fleet|w1|resume\n", calls=calls),
            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert old_sid in rec["retired_sids"]
        assert rec["status"] == "working"
        assert rec["limit_reset_at"] is None
        assert rec["limit_kind"] is None
        assert rec["native_short_id"] == "ccccdddd"
        assert rec["turns"] == 1
        # dispatch_bg's argv carries --resume <old_sid> (fork-steer, G2(b))
        dispatch_call = next(c for c in calls if "--resume" in c[0])
        argv = dispatch_call[0]
        assert argv[argv.index("--resume") + 1] == old_sid

    def test_resume_failure_rolls_back_to_limited(self, native_home):
        seed_native_worker(native_home, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z", limit_kind="session_5h")
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        # Mirrors TestFix1's legacy-path launch-failure test (test_resilience.py):
        # dispatch_bg's failure propagates out of cmd_resume_limited uncaught
        # (never swallowed into a false "success") -- the rollback is what
        # matters, not a clean return.
        with pytest.raises(fleet.NativeDispatchError):
            fleet.cmd_resume_limited(args, run=_fake_run_factory(rc=1),
                                     which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "limited"
        assert rec["session_id"] == SID
        assert rec["limit_reset_at"] == "2026-07-15T00:00:00Z"

    def test_resume_appends_limit_resumed_event(self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with(new_sid))
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        fleet.cmd_resume_limited(
            args, run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|resume\n"),
            which=lambda _: "claude", sleep=lambda s: None)
        assert "limit_resumed" in _events_kinds(native_home)

    def test_horizon_gate_still_fronts_native_branch(self, native_home):
        # Reset horizon in the future -- cmd_resume_limited's gate must skip
        # BEFORE ever reaching _resume_one_limited_native (no dispatch call).
        seed_native_worker(native_home, status="limited",
                           limit_reset_at="2099-01-01T00:00:00Z")
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(args, run=_fake_run_factory(),
                                      which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "limited"

    def test_resume_removes_old_ceiling_file(self, native_home, monkeypatch):
        # T7 fix wave (Minor, ceiling-file leak): mirrors send's fork-steer
        # cleanup for resume-limited's own native branch.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z", token_ceiling=5000)
        fleet._write_ceiling_file(old_sid, 5000)
        assert fleet.ceiling_file_path(old_sid).exists()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with(new_sid))
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(
            args, run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|resume\n"),
            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert not fleet.ceiling_file_path(old_sid).exists()
        assert fleet.ceiling_file_path(new_sid).exists()

    def test_resume_migrates_residual_old_sid_mailbox_at_commit(self, native_home, monkeypatch):
        # T7 fix wave (CRITICAL-2 fix 2c): resume-limited's own fork-steer
        # commit must also migrate a residual OLD-sid mailbox onto the new
        # fork, mirroring send's own commit -- exercised directly here
        # (rather than a full concurrent-actor race) by monkeypatching in
        # a spy that records the call.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with(new_sid))
        migrate_calls = []
        real_migrate = fleet._migrate_residual_mailbox

        def spy_migrate(old, new):
            migrate_calls.append((old, new))
            return real_migrate(old, new)

        monkeypatch.setattr(fleet, "_migrate_residual_mailbox", spy_migrate)
        from types import SimpleNamespace
        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(
            args, run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|resume\n"),
            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert migrate_calls == [(old_sid, new_sid)]

    def test_resume_commit_orphaned_when_record_changed_during_dispatch(
            self, native_home, monkeypatch, capsys):
        # S2 fix (final wave): mirrors send's own guard -- a concurrent
        # actor that moves session_id off old_sid during the resume's
        # dispatch window must not have its record silently restamped back
        # to the fork's new sid.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        other_sid = "eeeeffff-0000-1111-2222-333344445555"
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_with(new_sid))
        from types import SimpleNamespace

        def run(argv, **kw):
            if "--bg" in argv:
                data = fleet.load_registry()
                data["workers"]["w1"]["session_id"] = other_sid
                fleet.save_registry(data)
            import types
            return types.SimpleNamespace(
                returncode=0, stdout="backgrounded · ccccdddd · fleet|w1|resume\n", stderr="")

        args = SimpleNamespace(name="w1", force_now=False)
        rc = fleet.cmd_resume_limited(args, run=run, which=lambda _: "claude",
                                      sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == other_sid
        assert old_sid not in rec.get("retired_sids", [])
        events = _events_kinds(native_home)
        assert "limit_resumed" not in events
        assert "steer_orphaned" in events
        out = capsys.readouterr().out
        assert "changed during dispatch" in out


# ---------------------------------------------------------------------------
# M-B Task 6 fix wave (task-6-adversarial.md): C1 OSError-proof scan, C2
# last-substantive-record scanning discipline, High mtime transcript pick,
# Medium native respawn guard.
# ---------------------------------------------------------------------------

class TestFixC1LockedTranscriptFailsSoft:
    """C1 (Critical): transcript_limit_scan must never raise on a locked/
    unreadable transcript -- the ENTIRE access path (exists check, open,
    read) is OSError-guarded and falls soft to (False, None, None)."""

    def test_locked_exists_check_fails_soft(self, native_home, tmp_path, monkeypatch):
        t = _write_native_transcript(tmp_path, SID, [LIMIT_RECORD])

        class SharingViolation(PermissionError):
            def __init__(self):
                super().__init__(13, "used by another process")
                self.winerror = 32

        def boom(self):
            raise SharingViolation()

        monkeypatch.setattr(fleet.Path, "exists", boom)
        assert fleet.transcript_limit_scan(SID, transcript_path=t) == (False, None, None)

    def test_locked_read_fails_soft(self, native_home, tmp_path, monkeypatch):
        t = _write_native_transcript(tmp_path, SID, [LIMIT_RECORD])

        def boom(path):
            raise PermissionError(13, "used by another process")

        monkeypatch.setattr(fleet, "_read_tail_lines", boom)
        assert fleet.transcript_limit_scan(SID, transcript_path=t) == (False, None, None)

    def test_recompute_worker_native_no_crash_on_locked_transcript(
            self, native_home, tmp_path, monkeypatch):
        # Integration-shape: idle-no-outcome native worker whose transcript
        # exists but is momentarily locked (e.g. the --bg daemon's own
        # write) must resolve to dead-suspected, not raise, all the way
        # through recompute_worker_native -> _investigate_no_outcome ->
        # the REAL installed transcript_limit_scan hook.
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        rec = seed_native_worker(native_home)
        _write_native_transcript(tmp_path, SID, [LIMIT_RECORD])

        real_exists = fleet.Path.exists

        def flaky_exists(self):
            if self.name == f"{SID}.jsonl":
                raise PermissionError(13, "used by another process")
            return real_exists(self)

        monkeypatch.setattr(fleet.Path, "exists", flaky_exists)
        out = fleet.recompute_worker_native("w1", rec, [make_roster_entry(SID, status="idle")])
        assert out["status"] == "dead-suspected"


class TestFixC2LastSubstantiveRecordGate:
    """C2 (Critical): the scan stops at the FIRST record (newest-first)
    that is either API-error-shaped or substantive (assistant/user with
    real content) -- a stale older 429 sitting behind a newer non-matching
    record must never win. Bookkeeping records are transparently skipped."""

    def test_newer_529_after_older_429_does_not_park(self, native_home, tmp_path):
        older_429 = json.loads(json.dumps(LIMIT_RECORD))
        newer_529 = {
            "type": "assistant",
            "message": {"model": "<synthetic>", "role": "assistant",
                        "content": [{"type": "text", "text": "upstream overloaded"}]},
            "isApiErrorMessage": True, "apiErrorStatus": 529,
        }
        t = _write_native_transcript(tmp_path, SID, [older_429, newer_529])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert (is_limit, reset_at, kind) == (False, None, None)

    def test_newer_assistant_text_after_older_429_does_not_park(self, native_home, tmp_path):
        older_429 = json.loads(json.dumps(LIMIT_RECORD))
        newer_chat = {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "sure, let's keep going with the refactor"}]}}
        t = _write_native_transcript(tmp_path, SID, [older_429, newer_chat])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert (is_limit, reset_at, kind) == (False, None, None)

    def test_wall_as_last_substantive_record_with_trailing_bookkeeping_parks(
            self, native_home, tmp_path):
        # G7-evidence ordering: the limit wall IS the last substantive
        # thing that happened; only bookkeeping (attachment/system/
        # summary-shaped) records trail it and must be skipped over, not
        # treated as the stopping record.
        bookkeeping_1 = {"type": "attachment", "name": "some-file.txt"}
        bookkeeping_2 = {"type": "summary", "summary": "session summary"}
        t = _write_native_transcript(tmp_path, SID, [LIMIT_RECORD, bookkeeping_1, bookkeeping_2])
        is_limit, reset_at, kind = fleet.transcript_limit_scan(SID, transcript_path=t)
        assert is_limit is True
        assert kind == "session_5h"


class TestFixHTranscriptGlobPicksFreshestMtime:
    """High: find_transcript_path's glob fallback picks the freshest
    st_mtime among candidates, not the lexicographically-first path
    string (which is pure alphabetical accident of the project-dir
    name)."""

    def test_older_lexicographic_dir_loses_to_fresher_mtime_dir(
            self, native_home, tmp_path, monkeypatch):
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        old_path = _write_native_transcript_in(tmp_path, SID, [{"type": "user"}], "C--aaa-old")
        import time
        time.sleep(0.05)
        new_path = _write_native_transcript_in(tmp_path, SID, [LIMIT_RECORD], "C--zzz-new")
        chosen = fleet.find_transcript_path(None, SID)
        assert chosen == new_path
        assert chosen != old_path


def _write_native_transcript_in(home, sid, records, proj_name):
    proj = home / ".claude" / "projects" / proj_name
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{sid}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return p


def _send_args(name="w1", message="go"):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, message=message)


def _respawn_args(name="w1", task=None, force=False, yes=True,
                  max_budget_usd=None, setting_sources=None, token_ceiling=None):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, task=task, force=force, yes=yes,
                           max_budget_usd=max_budget_usd,
                           setting_sources=setting_sources,
                           token_ceiling=token_ceiling)


# ---------------------------------------------------------------------------
# M-B Task 7: send fork-steer + native respawn.
# ---------------------------------------------------------------------------

class TestNativeJobRef:
    def test_first_hyphen_segment(self, native_home):
        assert fleet._native_job_ref("aaaabbbb-1111-2222-3333-444455556666") == "aaaabbbb"

    def test_no_hyphen_returns_whole_sid(self, native_home):
        assert fleet._native_job_ref("plainsid") == "plainsid"

    def test_empty_returns_empty(self, native_home):
        assert fleet._native_job_ref("") == ""


class TestStopNativeSession:
    def test_true_on_rc_zero_short_id(self, native_home):
        calls = []
        assert fleet._stop_native_session(
            "sid-1", run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude"
        ) is True
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert argv == ["claude", "stop", "sid"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert kwargs["timeout"] == 30

    def test_retries_once_with_full_sid_on_short_id_failure(self, native_home):
        calls = []
        rcs = iter([1, 0])

        def run(argv, **kw):
            calls.append((argv, kw))
            return subprocess.CompletedProcess(argv, next(rcs))
        assert fleet._stop_native_session(
            "sid-1", run=run, which=lambda _: "claude"
        ) is True
        assert [c[0] for c in calls] == [["claude", "stop", "sid"], ["claude", "stop", "sid-1"]]

    def test_false_on_nonzero_rc_both_attempts(self, native_home):
        assert fleet._stop_native_session(
            "sid-1", run=_fake_run_factory(rc=1), which=lambda _: "claude"
        ) is False

    def test_false_when_claude_not_found(self, native_home):
        def boom_run(*a, **kw):
            raise AssertionError("must not run when claude cannot be resolved")
        assert fleet._stop_native_session("sid-1", run=boom_run, which=lambda _: None) is False

    def test_false_on_oserror(self, native_home):
        def run(argv, **kw):
            raise OSError("boom")
        assert fleet._stop_native_session("sid-1", run=run, which=lambda _: "claude") is False

    def test_false_on_timeout(self, native_home):
        def run(argv, **kw):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=30)
        assert fleet._stop_native_session("sid-1", run=run, which=lambda _: "claude") is False


class TestRmNativeSession:
    def test_true_on_rc_zero_short_id(self, native_home):
        calls = []
        assert fleet._rm_native_session(
            "sid-1", run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude"
        ) is True
        assert len(calls) == 1
        argv, kwargs = calls[0]
        assert argv == ["claude", "rm", "sid"]
        assert kwargs["timeout"] == 30

    def test_retries_once_with_full_sid_on_short_id_failure(self, native_home):
        calls = []
        rcs = iter([1, 0])

        def run(argv, **kw):
            calls.append((argv, kw))
            return subprocess.CompletedProcess(argv, next(rcs))
        assert fleet._rm_native_session(
            "sid-1", run=run, which=lambda _: "claude"
        ) is True
        assert [c[0] for c in calls] == [["claude", "rm", "sid"], ["claude", "rm", "sid-1"]]

    def test_false_on_nonzero_rc_both_attempts(self, native_home):
        assert fleet._rm_native_session(
            "sid-1", run=_fake_run_factory(rc=1), which=lambda _: "claude"
        ) is False

    def test_false_when_claude_not_found(self, native_home):
        def boom_run(*a, **kw):
            raise AssertionError("must not run when claude cannot be resolved")
        assert fleet._rm_native_session("sid-1", run=boom_run, which=lambda _: None) is False

    def test_false_on_oserror(self, native_home):
        def run(argv, **kw):
            raise OSError("boom")
        assert fleet._rm_native_session("sid-1", run=run, which=lambda _: "claude") is False


class TestRestampAfterSteer:
    def test_mutates_in_place(self, native_home):
        rec = seed_native_worker(native_home, sid="old-sid")
        rec["turns"] = 3
        fleet._restamp_after_steer(rec, "new-sid", "newshort")
        assert rec["session_id"] == "new-sid"
        assert rec["native_short_id"] == "newshort"
        assert rec["retired_sids"] == ["old-sid"]
        assert rec["turns"] == 4
        assert rec["last_dispatch_at"] is not None

    def test_none_session_id_never_lands_in_retired_sids(self, native_home):
        # S2 fix (final wave), defense-in-depth: a respawn --force's fresh
        # pre-claim record has session_id=None -- _restamp_after_steer must
        # never append that None into retired_sids (it would later reach
        # _cmd_kill_native's sweep and crash on `run([exe, "stop", None])`,
        # a TypeError outside the caught (OSError, SubprocessError) tuple).
        rec = seed_native_worker(native_home, sid="old-sid")
        rec["session_id"] = None
        fleet._restamp_after_steer(rec, "new-sid", "newshort")
        assert rec["session_id"] == "new-sid"
        assert None not in rec["retired_sids"]
        assert rec["retired_sids"] == []

    def test_appends_to_existing_retired_sids(self, native_home):
        rec = seed_native_worker(native_home, sid="s2")
        rec["retired_sids"] = ["s0", "s1"]
        fleet._restamp_after_steer(rec, "s3", "s3short")
        assert rec["retired_sids"] == ["s0", "s1", "s2"]


class TestNativeCumulativeTokens:
    def test_sums_result_records_across_sids(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result",
                                    "input_tokens": 100, "output_tokens": 50})
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s2", "kind": "result",
                                    "input_tokens": 10, "output_tokens": 5})
        assert fleet._native_cumulative_tokens("w1") == 165

    def test_ignores_tombstones_and_bogus_values(self, native_home):
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "s1", "kind": "result",
                                    "input_tokens": True, "output_tokens": -5})
        fleet.write_tombstone_outcome("w1", "s1", "killed")
        assert fleet._native_cumulative_tokens("w1") == 0

    def test_no_records_is_zero(self, native_home):
        assert fleet._native_cumulative_tokens("nope") == 0


class TestCmdSendNative:
    def test_busy_native_appends_mailbox(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(old_sid, status="busy")]))

        def run(*a, **kw):
            raise AssertionError("must not dispatch while the turn is busy")

        rc = fleet.cmd_send(_send_args(message="check the logs"),
                           run=run, which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        mailbox = fleet.mailbox_dir() / f"{old_sid}.md"
        assert "check the logs" in mailbox.read_text(encoding="utf-8")
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "working"
        assert rec["session_id"] == old_sid

    def test_waiting_native_appends_mailbox_never_persists_transient_flag(
            self, native_home, monkeypatch):
        # S5 fix (final wave): T5's I1 pattern (strip waiting_for_permission
        # before any registry save) was replicated in cmd_status/cmd_wait/
        # cmd_clean but missed in send's own working-branch persist -- a
        # roster "waiting" verdict leaked the transient key straight into
        # fleet.json.
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(old_sid, status="waiting")]))

        def run(*a, **kw):
            raise AssertionError("must not dispatch while the turn is waiting")

        rc = fleet.cmd_send(_send_args(message="check the logs"),
                           run=run, which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "working"
        assert "waiting_for_permission" not in rec

    def test_idle_native_fork_steers_and_restamps(self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        calls = []
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),                                          # cmd_send's own verdict fetch
            (True, []),                                          # dispatch_bg pre-dispatch snapshot
            (True, [make_roster_entry(new_sid, status="idle")]),  # join poll
        ))
        rc = fleet.cmd_send(
            _send_args(message="go do X"),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|go do X\n", calls=calls),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert old_sid in rec["retired_sids"]
        assert rec["status"] == "working"
        assert rec["native_short_id"] == "ccccdddd"
        assert rec["turns"] == 1
        dispatch_call = next(c for c in calls if "--resume" in c[0])
        argv = dispatch_call[0]
        assert argv[argv.index("--resume") + 1] == old_sid
        # message rides the mailbox drain -- old sid's mailbox is claimed+finalized
        assert not (fleet.mailbox_dir() / f"{old_sid}.md").exists()
        assert "steered" in _events_kinds(native_home)

    def test_fork_steer_commit_survives_event_append_oserror(self, native_home,
                                                             monkeypatch, capsys):
        # Fix-wave F1: _commit_launched_turn retries OSError, so an
        # append_event OSError escaping AFTER save_registry made the restamp
        # durable used to re-run the non-idempotent commit body -- the retry
        # reloaded, saw session_id already == new_sid, fell into the orphaned
        # branch, misreported a COMMITTED steer as "left for manual adoption"
        # and skipped the ceiling write. Post-save event appends are now
        # best-effort (_append_event_quiet): commit stands, steer reported
        # normally, ceiling written, failure named on stderr.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="idle", token_ceiling=500)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),                                          # cmd_send's own verdict fetch
            (True, []),                                          # dispatch_bg pre-dispatch snapshot
            (True, [make_roster_entry(new_sid, status="idle")]),  # join poll
        ))
        real_append = fleet.append_event
        state = {"raised": False}

        def poisoned_append(kind, name, **fields):
            if kind == "steered" and not state["raised"]:
                state["raised"] = True
                raise OSError(28, "No space left on device")
            return real_append(kind, name, **fields)

        monkeypatch.setattr(fleet, "append_event", poisoned_append)
        rc = fleet.cmd_send(
            _send_args(message="go do X"),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|go do X\n"),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        assert state["raised"]  # the poison genuinely fired
        captured = capsys.readouterr()
        assert "left for manual adoption" not in captured.out
        assert "fork-steered" in captured.out
        assert "not recorded" in captured.err  # loud best-effort note
        # Fix-wave micro: the note must carry the fields payload -- the sid
        # is what the lost forensics line existed to preserve.
        assert new_sid in captured.err
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid          # durable commit stands
        assert old_sid in rec["retired_sids"]
        assert fleet.ceiling_file_path(new_sid).exists()  # ceiling write not skipped
        assert "steer_orphaned" not in _events_kinds(native_home)

    def test_idle_native_over_ceiling_refuses_no_dispatch(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="idle", token_ceiling=100)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result",
                                    "input_tokens": 80, "output_tokens": 40})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        def run(*a, **kw):
            raise AssertionError("must not dispatch when over the token ceiling")

        with pytest.raises(fleet.FleetCliError, match="over_ceiling"):
            fleet.cmd_send(_send_args(), run=run, which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "over_ceiling"
        assert rec["session_id"] == old_sid

    def test_dead_suspected_refuses(self, native_home, monkeypatch, tmp_path):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="idle")
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.FleetCliError, match="dead-suspected"):
            fleet.cmd_send(_send_args(message="ping"), which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "dead-suspected"

    def test_limited_refuses(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="limited",
                           limit_reset_at="2026-07-15T00:00:00Z", limit_kind="session_5h")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.FleetCliError, match="resume-limited"):
            fleet.cmd_send(_send_args(), which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "limited"

    def test_dead_refuses_with_respawn_hint(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="dead")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.FleetCliError, match="fleet respawn"):
            fleet.cmd_send(_send_args(), which=lambda _: "claude", sleep=lambda s: None)

    def test_epoch_suspicious_roster_refuses(self, native_home, monkeypatch):
        # G9: a roster fetch FAILURE must never be treated as "safe to act
        # on" -- refuse rather than risk a wrong verdict against frozen data.
        seed_native_worker(native_home, sid=SID, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "no claude"))
        with pytest.raises(fleet.FleetCliError, match="G9"):
            fleet.cmd_send(_send_args(), which=lambda _: "claude", sleep=lambda s: None)

    def test_fork_steer_rolls_back_to_idle_on_dispatch_failure(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.NativeDispatchError):
            fleet.cmd_send(_send_args(message="go"), run=_fake_run_factory(rc=1),
                           which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle"
        assert rec["session_id"] == old_sid
        # the message must survive the rollback, not be lost
        mailbox = fleet.mailbox_dir() / f"{old_sid}.md"
        assert "go" in mailbox.read_text(encoding="utf-8")

    def test_fork_steer_rollback_restores_last_dispatch_at_too(self, native_home, monkeypatch):
        # S3 fix (final wave): the pre-claim advances last_dispatch_at to
        # "now" before dispatch; a failed dispatch's rollback used to
        # restore only status="idle", leaving the anchor advanced. The next
        # recompute then anchors has_fresh_outcome on the ADVANCED
        # timestamp, so the worker's genuinely-fresh (but now stale-looking)
        # outcome record no longer vouches for it -- permanently stranding
        # an idle worker as dead-suspected. Restoring last_dispatch_at
        # verbatim is what keeps the next recompute landing on idle.
        old_sid = SID
        original_anchor = _iso(NOW - timedelta(minutes=5))
        seed_native_worker(native_home, sid=old_sid, status="idle",
                           last_dispatch_at=original_anchor)
        # Outcome genuinely finished AFTER the original anchor, BEFORE this
        # failed steer attempt's own pre-claim timestamp.
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        with pytest.raises(fleet.NativeDispatchError):
            fleet.cmd_send(_send_args(message="go"), run=_fake_run_factory(rc=1),
                           which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle"
        assert rec["last_dispatch_at"] == original_anchor
        # The real proof: the NEXT recompute (empty roster -- sid reaped)
        # must land on idle, not dead-suspected.
        verdict = fleet.recompute_worker_native("w1", rec, [])
        assert verdict["status"] == "idle"

    # -----------------------------------------------------------------
    # T7 fix wave (task-7-adversarial.md CRITICAL-1): send during an
    # in-flight dispatch (session_id is None) must refuse loudly, never
    # silently swallow the message into mailbox/None.md.
    # -----------------------------------------------------------------
    def test_send_during_dispatch_window_refuses_no_mailbox_none(self, native_home, monkeypatch):
        seed_native_worker(native_home, sid=SID, status="working",
                           session_id=None, last_activity=fleet.now_iso())
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        def run(*a, **kw):
            raise AssertionError("must not dispatch while a launch-claim is in flight")

        with pytest.raises(fleet.FleetCliError, match="dispatch in flight"):
            fleet.cmd_send(_send_args(message="hello"), run=run,
                           which=lambda _: "claude", sleep=lambda s: None)
        assert not (fleet.mailbox_dir() / "None.md").exists()
        # no other mailbox file was created either -- the message was
        # refused outright, not queued anywhere.
        assert list(fleet.mailbox_dir().glob("*.md")) == []

    # -----------------------------------------------------------------
    # T7 fix wave (task-7-adversarial.md CRITICAL-2): a second, fully
    # independent `fleet send` landing while the first's fork-steer
    # dispatch is still in flight must queue to the mailbox instead of
    # double-forking the same idle worker.
    # -----------------------------------------------------------------
    def test_reentrant_second_send_during_dispatch_queues_not_double_forks(
            self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        # The outcome from old_sid's ACTUAL last turn -- fixed, in the past
        # relative to real wall-clock test execution, so it looks fresh
        # against the ORIGINAL last_dispatch_at (5 minutes before NOW) but
        # stale against a freshly-restamped one (FIX-2a).
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})

        # old_sid stays "idle" in the roster throughout -- the NEW fork
        # landing under a brand-new sid is invisible to old_sid's own
        # roster entry. new_sid only appears once dispatch_bg's join poll
        # goes looking for it (call #4+).
        roster_answers = _roster_sequence(
            (True, [make_roster_entry(old_sid, status="idle")]),  # 1: outer verdict fetch
            (True, [make_roster_entry(old_sid, status="idle")]),  # 2: dispatch_bg pre-dispatch snapshot
            (True, [make_roster_entry(old_sid, status="idle")]),  # 3: inner send's own verdict fetch
            (True, [make_roster_entry(old_sid, status="idle"),
                    make_roster_entry(new_sid, status="idle")]),  # 4+: outer's join poll
        )
        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster_answers)

        real_getpid = os.getpid
        dispatch_calls = []
        inner_rc = {}

        def inner_run(*a, **kw):
            raise AssertionError("the reentrant (inner) send must not dispatch at all")

        def run(argv, **kw):
            dispatch_calls.append(argv)
            if len(dispatch_calls) == 1:
                # Simulate a second, fully independent `fleet send` OS
                # process landing while the first's dispatch subprocess is
                # in flight -- distinct pid so the two mailbox claims can
                # never collide on the same claimed-filename.
                monkeypatch.setattr(os, "getpid", lambda: real_getpid() + 1)
                try:
                    inner_rc["rc"] = fleet.cmd_send(
                        _send_args(message="inner"), run=inner_run,
                        which=lambda _: "claude", sleep=lambda s: None,
                    )
                finally:
                    monkeypatch.setattr(os, "getpid", real_getpid)
            import types
            return types.SimpleNamespace(
                returncode=0, stdout="backgrounded · ccccdddd · fleet|w1|outer\n", stderr="")

        rc = fleet.cmd_send(_send_args(message="outer"), run=run,
                            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert inner_rc["rc"] == 0

        # Exactly ONE real "claude --bg" dispatch happened.
        bg_dispatches = [c for c in dispatch_calls if "--bg" in c]
        assert len(bg_dispatches) == 1

        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert rec["retired_sids"] == [old_sid]
        events = _events_kinds(native_home)
        assert events.count("steered") == 1

        # The inner message raced into old_sid's mailbox AFTER
        # compose_prompt had already claimed/drained it for the outer
        # dispatch -- FIX-2c must migrate it onto the new sid at commit,
        # not strand it under a sid the registry will never reference again.
        assert not (fleet.mailbox_dir() / f"{old_sid}.md").exists()
        new_mailbox = fleet.mailbox_dir() / f"{new_sid}.md"
        assert new_mailbox.exists()
        assert "inner" in new_mailbox.read_text(encoding="utf-8")

    # -----------------------------------------------------------------
    # T7 fix wave 2 (NEW CRITICAL, re-review of eef84ae): the raw-status
    # in-flight check must not treat every "on-disk working, recompute
    # disagrees" mismatch as a live concurrent pre-claim -- that shape is
    # ALSO the routine, non-racing case of a worker whose turn genuinely
    # finished with nothing having persisted the demotion yet.
    # -----------------------------------------------------------------
    def test_send_recomputes_past_stale_working_label_when_turn_actually_finished(
            self, native_home, monkeypatch):
        """Genuinely-finished worker: fresh result outcome for its sid,
        roster alive (an unrelated other worker present) but no longer
        carries this sid (reaped -- not an empty roster, so G9 does not
        intervene), and a stale on-disk "working" label nothing has
        recomputed since. `send` must NOT queue mail against the dead sid
        and freeze the stale label -- it must recompute to idle, persist
        it, and proceed through the normal fork-steer path exactly once."""
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        other_sid = "eeeeffff-0000-1111-2222-333344445555"
        stale_anchor = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        seed_native_worker(native_home, sid=old_sid, status="working",
                           last_dispatch_at=stale_anchor)
        # Genuinely fresh completion outcome -- the turn really did finish,
        # AFTER the stale last_dispatch_at anchor above.
        fleet.append_outcome("w1", {"ts": fleet.now_iso(), "session_id": old_sid,
                                    "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, [make_roster_entry(other_sid, status="busy")]),  # outer verdict fetch
            (True, [make_roster_entry(other_sid, status="busy")]),  # dispatch_bg pre-dispatch snapshot
            (True, [make_roster_entry(other_sid, status="busy"),
                    make_roster_entry(new_sid, status="idle")]),    # join poll
        ))
        calls = []
        rc = fleet.cmd_send(
            _send_args(message="go do X"),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|go do X\n", calls=calls),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        bg_dispatches = [c[0] for c in calls if "--bg" in c[0]]
        assert len(bg_dispatches) == 1

        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert rec["status"] == "working"
        assert rec["retired_sids"] == [old_sid]
        # nothing stranded on the dead sid's mailbox -- claimed+drained,
        # not misrouted into a queue nobody will ever read.
        assert not (fleet.mailbox_dir() / f"{old_sid}.md").exists()
        assert "steered" in _events_kinds(native_home)

    def test_send_on_expired_crashed_claim_does_not_queue_to_dead_mailbox(
            self, native_home, monkeypatch, tmp_path):
        """A stale "working" label with NO fresh outcome and a pre-claim
        that's aged past LAUNCH_CLAIM_MAX_AGE_SECONDS (a crashed steer,
        never a live one) must not be treated as in-flight either -- it
        falls through to the normal verdict path (dead-suspected, since
        there's no outcome to vouch for it), never queuing mail against a
        sid nothing will ever read again."""
        monkeypatch.setattr(fleet.Path, "home", staticmethod(lambda: tmp_path))
        old_sid = SID
        other_sid = "eeeeffff-0000-1111-2222-333344445555"
        expired_anchor = _iso(datetime.now(timezone.utc)
                              - timedelta(seconds=fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS + 60))
        seed_native_worker(native_home, sid=old_sid, status="working",
                           last_dispatch_at=expired_anchor)
        # No outcome record at all for old_sid -- nothing vouches for it.
        # Roster alive (unrelated other worker present, old_sid reaped) so
        # G9's epoch-suspicious freeze does not intervene -- entries is
        # non-empty, and native_epoch_suspicious only trips on either a
        # fetch failure or an EMPTY roster.
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(other_sid, status="busy")]))

        def run(*a, **kw):
            raise AssertionError("must not dispatch on a dead-suspected verdict")

        with pytest.raises(fleet.FleetCliError, match="dead-suspected"):
            fleet.cmd_send(_send_args(message="ping"), run=run,
                           which=lambda _: "claude", sleep=lambda s: None)

        rec = fleet.load_registry()["workers"]["w1"]
        # recomputed verdict WAS persisted (self-healed), not frozen.
        assert rec["status"] == "dead-suspected"
        # message was never queued against the dead/expired sid.
        assert not (fleet.mailbox_dir() / f"{old_sid}.md").exists()
        events = _events_kinds(native_home)
        assert "mail_sent" not in events

    def test_fork_steer_removes_old_ceiling_file(self, native_home, monkeypatch):
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="idle", token_ceiling=5000)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        fleet._write_ceiling_file(old_sid, 5000)
        assert fleet.ceiling_file_path(old_sid).exists()
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []), (True, [make_roster_entry(new_sid, status="idle")]),
        ))
        rc = fleet.cmd_send(
            _send_args(message="go"),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|go\n"),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        assert not fleet.ceiling_file_path(old_sid).exists()
        assert fleet.ceiling_file_path(new_sid).exists()

    def test_steered_event_only_appended_when_record_still_present(self, native_home, monkeypatch):
        # T7 fix wave (Minor, event-append symmetry): a concurrent
        # kill/clean racing the post-dispatch commit window must not leave
        # a "steered" event behind when no registry mutation happened.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []), (True, [make_roster_entry(new_sid, status="idle")]),
        ))

        def run(argv, **kw):
            if "--bg" in argv:
                # Model a concurrent kill/clean: the worker record vanishes
                # entirely between dispatch and the post-dispatch commit.
                data = fleet.load_registry()
                data["workers"].pop("w1", None)
                fleet.save_registry(data)
            import types
            return types.SimpleNamespace(
                returncode=0, stdout="backgrounded · ccccdddd · fleet|w1|go\n", stderr="")

        rc = fleet.cmd_send(_send_args(message="go"), run=run,
                            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        assert fleet.load_registry()["workers"] == {}
        assert "steered" not in _events_kinds(native_home)

    def test_fork_steer_commit_orphaned_when_record_changed_during_dispatch(
            self, native_home, monkeypatch, capsys):
        # S2 fix (final wave): the success commit used to guard only `r is
        # not None`, unconditionally restamping over whatever a concurrent
        # kill/interrupt/respawn --force did during the dispatch window.
        # Model a concurrent actor that replaces session_id with an
        # unrelated sid (e.g. a respawn --force's own fresh dispatch)
        # between this call's pre-claim and its post-dispatch commit.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        other_sid = "eeeeffff-0000-1111-2222-333344445555"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result"})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []), (True, []), (True, [make_roster_entry(new_sid, status="idle")]),
        ))

        def run(argv, **kw):
            if "--bg" in argv:
                data = fleet.load_registry()
                data["workers"]["w1"]["session_id"] = other_sid
                fleet.save_registry(data)
            import types
            return types.SimpleNamespace(
                returncode=0, stdout="backgrounded · ccccdddd · fleet|w1|go\n", stderr="")

        rc = fleet.cmd_send(_send_args(message="go"), run=run,
                            which=lambda _: "claude", sleep=lambda s: None)
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        # NOT restamped to the fork's new sid -- the concurrent actor wins.
        assert rec["session_id"] == other_sid
        assert old_sid not in rec.get("retired_sids", [])
        events = _events_kinds(native_home)
        assert "steered" not in events
        assert "steer_orphaned" in events
        out = capsys.readouterr().out
        assert "changed during dispatch" in out
        assert new_sid[:8] in out


class TestMigrateResidualMailbox:
    """T7 fix wave (CRITICAL-2 fix 2c): a steering message that raced into
    the OLD sid's mailbox after compose_prompt already claimed/drained it
    must follow the worker onto the NEW sid at the steer-restamp commit."""

    def test_moves_content_and_unlinks_old(self, native_home):
        fleet.append_mailbox("old-sid", "residual message")
        fleet._migrate_residual_mailbox("old-sid", "new-sid")
        assert not (fleet.mailbox_dir() / "old-sid.md").exists()
        new_mailbox = fleet.mailbox_dir() / "new-sid.md"
        assert "residual message" in new_mailbox.read_text(encoding="utf-8")

    def test_appends_to_existing_new_mailbox(self, native_home):
        fleet.append_mailbox("new-sid", "already queued")
        fleet.append_mailbox("old-sid", "residual message")
        fleet._migrate_residual_mailbox("old-sid", "new-sid")
        content = (fleet.mailbox_dir() / "new-sid.md").read_text(encoding="utf-8")
        assert "already queued" in content
        assert "residual message" in content
        assert content.index("already queued") < content.index("residual message")

    def test_noop_when_old_absent(self, native_home):
        fleet._migrate_residual_mailbox("old-sid", "new-sid")
        assert not (fleet.mailbox_dir() / "new-sid.md").exists()

    def test_unlinks_whitespace_only_old_without_creating_new(self, native_home):
        path = fleet.mailbox_dir() / "old-sid.md"
        fleet.mailbox_dir().mkdir(parents=True, exist_ok=True)
        path.write_text("   \n\n  ", encoding="utf-8")
        fleet._migrate_residual_mailbox("old-sid", "new-sid")
        assert not path.exists()
        assert not (fleet.mailbox_dir() / "new-sid.md").exists()


class TestCmdRespawnNative:
    def test_fresh_dispatch_carries_journal_no_resume(self, native_home, monkeypatch, tmp_path):
        old_sid = "deadbeef-0000-1111-2222-333344445555"
        seed_native_worker(native_home, sid=old_sid, status="idle", category="camp5")
        journal = fleet.journals_dir() / "w1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("prior session left off here", encoding="utf-8")
        # 1st call: respawn's own liveness check (old sid gone from roster).
        # 2nd call: dispatch_bg's pre-dispatch snapshot (new sid not minted yet).
        # 3rd+ call: dispatch_bg's join poll (new sid present).
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, []),
            (True, []),
            (True, [make_roster_entry(SID, status="idle")]),
        ))
        calls = []
        rc = fleet.cmd_respawn(
            _respawn_args(),
            run=_fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n", calls=calls),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        dispatch_call = next(c for c in calls if "--bg" in c[0])
        argv = dispatch_call[0]
        assert "--resume" not in argv
        task_file = fleet.task_file_path("w1")
        assert "prior session left off here" in task_file.read_text(encoding="utf-8")
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == SID
        assert rec["session_id"] != old_sid
        assert old_sid in rec["retired_sids"]
        assert rec["dispatch_kind"] == "bg"
        assert rec["category"] == "camp5"
        assert rec["status"] == "working"
        assert rec["turns"] == 1

    def test_live_native_without_force_refuses(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(old_sid, status="busy")]))

        def run(*a, **kw):
            raise AssertionError("must not stop/dispatch without --force")

        with pytest.raises(fleet.FleetCliError, match="--force"):
            fleet.cmd_respawn(_respawn_args(force=False), run=run, which=lambda _: "claude",
                              sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == old_sid

    def test_force_stops_old_and_tombstones(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="working")
        # 1st roster fetch (liveness check): old sid live. 2nd (T7 fix wave:
        # post-stop re-verify, ALWAYS run now, even on a reported-successful
        # stop): old sid gone. 3rd (dispatch_bg's pre-dispatch snapshot):
        # still gone. 4th+ (join poll): new sid present.
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _roster_sequence(
            (True, [make_roster_entry(old_sid, status="busy")]),
            (True, []),
            (True, []),
            (True, [make_roster_entry(new_sid, status="idle")]),
        ))
        stop_calls = []
        rc = fleet.cmd_respawn(
            _respawn_args(force=True),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|t\n", calls=stop_calls),
            which=lambda _: "claude", sleep=lambda s: None,
        )
        assert rc == 0
        stop_call = next(c for c in stop_calls if c[0][:2] == ["claude", "stop"])
        assert stop_call[0] == ["claude", "stop", fleet._native_job_ref(old_sid)]
        outcomes = fleet.read_outcomes("w1", sid=old_sid)
        assert any(o["kind"] == "stopped" for o in outcomes)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert old_sid in rec["retired_sids"]

    def test_force_aborts_when_stop_fails_and_still_live(self, native_home, monkeypatch):
        # Trap #3: _stop_native_session returns False AND a re-fetch still
        # shows the old sid live -- must ABORT, never proceed to dispatch a
        # second live session under the same name.
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(old_sid, status="busy")]))

        def run(argv, **kw):
            import types
            if argv[:2] == ["claude", "stop"]:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="failed")
            raise AssertionError("must not dispatch after an unverified stop on a still-live sid")

        with pytest.raises(fleet.FleetCliError, match="never two live sessions"):
            fleet.cmd_respawn(_respawn_args(force=True), run=run, which=lambda _: "claude",
                              sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == old_sid

    def test_max_budget_usd_refused(self, native_home):
        seed_native_worker(native_home, sid=SID, status="idle")
        with pytest.raises(fleet.FleetCliError, match="G3"):
            fleet.cmd_respawn(_respawn_args(max_budget_usd=5.0), which=lambda _: "claude")

    def test_force_aborts_when_stop_succeeds_but_roster_still_live_after_retry(
            self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="working")
        # Every roster fetch (liveness check, post-stop re-verify, and the
        # grace-window retry re-fetch) reports the old sid still live --
        # models a `claude stop` that acknowledges (rc=0) before the daemon
        # has actually torn the session down.
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(old_sid, status="busy")]))
        sleeps = []

        def run(argv, **kw):
            if argv[:2] == ["claude", "stop"]:
                import types
                return types.SimpleNamespace(returncode=0, stdout="", stderr="")
            raise AssertionError(
                "must not dispatch a second session while the old one is still live")

        with pytest.raises(fleet.FleetCliError, match="never two live sessions"):
            fleet.cmd_respawn(_respawn_args(force=True), run=run, which=lambda _: "claude",
                              sleep=lambda s: sleeps.append(s))
        assert 2 in sleeps  # the grace-window retry actually happened
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == old_sid

    def test_force_succeeds_once_roster_confirms_gone_on_retry(self, native_home, monkeypatch):
        # The mirror-image happy path: a reported-successful stop that
        # STILL shows live on the immediate re-check, but the grace-window
        # retry re-fetch confirms it's actually gone -- respawn proceeds.
        old_sid = SID
        new_sid = "ccccdddd-9999-8888-7777-666655554444"
        calls = {"n": 0}

        def roster(**_):
            calls["n"] += 1
            n = calls["n"]
            if n <= 2:
                # 1: liveness check. 2: immediate post-stop re-verify --
                # both still show the old sid live (daemon lag).
                return True, [make_roster_entry(old_sid, status="busy")]
            if n == 3:
                # 3: the grace-window retry re-fetch -- now gone.
                return True, []
            if n == 4:
                # 4: dispatch_bg's pre-dispatch snapshot.
                return True, []
            # 5+: dispatch_bg's join poll.
            return True, [make_roster_entry(new_sid, status="idle")]

        seed_native_worker(native_home, sid=old_sid, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster)
        sleeps = []
        rc = fleet.cmd_respawn(
            _respawn_args(force=True),
            run=_fake_run_factory(stdout="backgrounded · ccccdddd · fleet|w1|t\n"),
            which=lambda _: "claude", sleep=lambda s: sleeps.append(s),
        )
        assert rc == 0
        assert 2 in sleeps
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == new_sid
        assert old_sid in rec["retired_sids"]

    # -----------------------------------------------------------------
    # T7 fix wave (task-7-review.md concern (a)): the two previously
    # untested roster-fetch-failure refusal branches in respawn.
    # -----------------------------------------------------------------
    def test_roster_fetch_failure_refuses(self, native_home, monkeypatch):
        seed_native_worker(native_home, sid=SID, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "no claude"))
        with pytest.raises(fleet.FleetCliError, match="could not fetch the native roster"):
            fleet.cmd_respawn(_respawn_args(), which=lambda _: "claude", sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == SID

    def test_post_stop_roster_fetch_failure_refuses(self, native_home, monkeypatch):
        old_sid = SID
        seed_native_worker(native_home, sid=old_sid, status="working")
        calls = {"n": 0}

        def roster(**_):
            calls["n"] += 1
            if calls["n"] == 1:
                return True, [make_roster_entry(old_sid, status="busy")]
            return False, "no claude"

        monkeypatch.setattr(fleet, "_fetch_agents_roster", roster)

        def run(argv, **kw):
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with pytest.raises(fleet.FleetCliError, match="never two live sessions"):
            fleet.cmd_respawn(_respawn_args(force=True), run=run, which=lambda _: "claude",
                              sleep=lambda s: None)
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == old_sid

    # -----------------------------------------------------------------
    # T7 fix wave (task-7-review.md concern (b)): respawn's join-expiry
    # handler must reuse cmd_spawn's fast-completion check instead of
    # unconditionally rolling back a legitimately-finished turn.
    # -----------------------------------------------------------------
    def test_join_expiry_fast_completion_sid_keyed_outcome_commits_idle(
            self, native_home, monkeypatch):
        old_sid = "deadbeef-0000-1111-2222-333344445555"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        # 1st call: liveness check (old sid gone -- respawn proceeds
        # unforced). Every call after that: empty (the daemon never
        # registers the new session on the roster, forcing the join to run
        # out the clock).
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        # Sid-keyed fallback (outcomes/<SID>.jsonl) -- the realistic shape
        # the REAL Stop hook writes when the registry's session_id is still
        # None at the instant it fires (see _fast_completion_sid's
        # docstring) -- not the simpler name-keyed shape.
        fleet.append_outcome(SID, {"ts": fleet.now_iso(), "session_id": SID,
                                   "kind": "result", "result_text": "already done"})
        clock = _FakeClock()
        rc = fleet.cmd_respawn(
            _respawn_args(),
            run=_fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n"),
            which=lambda _: "claude", sleep=lambda s: clock.advance(s), clock=clock,
        )
        assert rc == 0
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "idle"
        assert rec["session_id"] == SID
        assert old_sid in rec["retired_sids"]
        events = _events_kinds(native_home)
        assert "turn_started" in events
        assert "respawn_failed" not in events

    def test_join_expiry_without_fast_completion_rolls_back_to_before(
            self, native_home, monkeypatch):
        old_sid = "deadbeef-0000-1111-2222-333344445555"
        seed_native_worker(native_home, sid=old_sid, status="idle")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        clock = _FakeClock()
        with pytest.raises(fleet.FleetCliError, match="native respawn failed"):
            fleet.cmd_respawn(
                _respawn_args(),
                run=_fake_run_factory(stdout="backgrounded · aaaabbbb · fleet|w1|t\n"),
                which=lambda _: "claude", sleep=lambda s: clock.advance(s), clock=clock,
            )
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["session_id"] == old_sid
        assert rec["status"] == "idle"
        assert "respawn_failed" in _events_kinds(native_home)


def _kill_args(name="w1", yes=True):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, yes=yes)


def _interrupt_args(name="w1"):
    from types import SimpleNamespace
    return SimpleNamespace(name=name)


def _attach_args(name="w1", force=False):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, force=force)


def _peek_args(name="w1", lines=20):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, lines=lines)


def _result_args(name="w1"):
    from types import SimpleNamespace
    return SimpleNamespace(name=name)


def _clean_args(yes=True):
    from types import SimpleNamespace
    return SimpleNamespace(yes=yes)


class TestCmdKillNative:
    def test_launch_in_flight_refuses(self, native_home):
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        fleet.save_registry({"workers": {"w1": rec}})

        def boom_run(*a, **kw):
            raise AssertionError("must not attempt a stop with no real sid yet")

        with pytest.raises(fleet.FleetCliError, match="launch in flight"):
            fleet.cmd_kill(_kill_args(), run=boom_run, which=lambda _: "claude")
        assert fleet.load_registry()["workers"]["w1"]["status"] == "working"

    def test_expired_launch_claim_is_not_refused(self, native_home):
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        rec["last_activity"] = _iso(
            datetime.now(timezone.utc) - timedelta(seconds=fleet.LAUNCH_CLAIM_MAX_AGE_SECONDS + 1))
        fleet.save_registry({"workers": {"w1": rec}})

        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(), which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"

    def test_stops_current_sid_writes_tombstone_marks_dead(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        calls = []
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")

        assert rc == 0
        assert "killed" in capsys.readouterr().out
        stop_call = next(c for c in calls if c[0][:2] == ["claude", "stop"])
        assert stop_call[0] == ["claude", "stop", fleet._native_job_ref(SID)]
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["status"] == "dead"
        outcomes = fleet.read_outcomes("w1", sid=SID)
        assert any(o["kind"] == "killed" for o in outcomes)
        assert "killed" in _events_kinds(native_home)

    def test_stops_retired_sids_best_effort(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["retired_sids"] = ["retired1-a", "retired2-b"]
        fleet.save_registry({"workers": {"w1": rec}})
        calls = []
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")
        stopped = {c[0][2] for c in calls if c[0][:2] == ["claude", "stop"]}
        assert stopped == {fleet._native_job_ref(SID), "retired1", "retired2"}

    # T8 fix wave (adv I1, Important) -- retired-sid sweep wall-time bound.

    def test_retired_sid_stops_use_short_timeout_primary_keeps_full_budget(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["retired_sids"] = ["retired1-a", "retired2-b"]
        fleet.save_registry({"workers": {"w1": rec}})
        calls = []
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")
        stop_calls = {c[0][2]: c[1] for c in calls if c[0][:2] == ["claude", "stop"]}
        assert stop_calls[fleet._native_job_ref(SID)]["timeout"] == 30
        assert stop_calls["retired1"]["timeout"] == fleet._RETIRED_SID_SWEEP_TIMEOUT_SECONDS
        assert stop_calls["retired2"]["timeout"] == fleet._RETIRED_SID_SWEEP_TIMEOUT_SECONDS
        assert fleet._RETIRED_SID_SWEEP_TIMEOUT_SECONDS == 5

    def test_retired_sid_sweep_capped_at_20_most_recent(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["retired_sids"] = [f"retired{i:02d}-x" for i in range(50)]
        fleet.save_registry({"workers": {"w1": rec}})
        calls = []
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")
        stopped_retired = [c[0][2] for c in calls
                           if c[0][:2] == ["claude", "stop"] and c[0][2] != fleet._native_job_ref(SID)]
        assert len(stopped_retired) == 20
        # the 20 MOST RECENT (last 20 of the list), not the first 20.
        assert set(stopped_retired) == {f"retired{i:02d}" for i in range(30, 50)}

    def test_retired_sid_sweep_prints_one_progress_line_per_sid(self, native_home, capsys):
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["retired_sids"] = ["retired1sid", "retired2sid"]
        fleet.save_registry({"workers": {"w1": rec}})
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=0), which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "stopping retired session retired1... ok" in err
        assert "stopping retired session retired2... ok" in err

    def test_kill_stops_by_the_captured_short_id_not_a_derived_ref(self, native_home, capsys):
        """ND-1 (re-review MD-CONTRACT-REVIEW-2026-07-17.md), the mirror of
        `test_sweep_passes_the_rosters_own_id_not_a_derived_ref`.

        The M5 commit gave `stop` the inference "gone == success"; the m1 commit
        taught `rm` never to trust a DERIVED ref for exactly that inference --
        and hardened both rm sites and neither stop site. Repro'd: with a CLI
        that answers only to its own short id, `fleet kill` derived
        sid.split("-")[0], read `No job matching` as `gone`, printed "killed",
        exited 0, stamped interrupt_outcome=True and marked the worker dead --
        while the session kept running, untracked, skipped by every husk sweep
        forever because it is status/pid-live.

        `native_short_id` here is deliberately NOT the derived prefix."""
        import types as _t
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["native_short_id"] = "zz9qk7xd"          # NOT SID.split("-")[0]
        fleet.save_registry({"workers": {"w1": rec}})

        refs = []

        def only_own_id(argv, **kwargs):
            ref = argv[2] if len(argv) > 2 else None
            refs.append(ref)
            if ref == "zz9qk7xd":
                return _t.SimpleNamespace(returncode=0, stdout=f"stopped {ref}",
                                          stderr="")
            return _t.SimpleNamespace(returncode=1,
                                      stdout=f"No job matching '{ref}'", stderr="")

        rc = fleet.cmd_kill(_kill_args(), run=only_own_id, which=lambda _: "claude")
        assert refs and refs[0] == "zz9qk7xd", (
            f"kill must stop by the CAPTURED short id, not a derived one: {refs}")
        assert rc == 0

    def test_kill_on_an_already_gone_sid_succeeds_as_gone(self, native_home, capsys):
        """M5 fix wave (review MD-CONTRACT-REVIEW-2026-07-17.md): `claude stop`
        on an already-gone sid exits 1 with "No job matching" (live receipt,
        findings §Q3). Read as failure, `fleet kill` exited 1 and told the
        operator to "investigate the session manually" about a session that is
        verifiably, correctly gone -- while the rm half of the same contract
        now reports a clean `gone`. The two halves disagreed about one fact.

        The realistic trigger: archive removes a worker's roster entry, then
        the operator kills the stale record."""
        import types as _t
        seed_native_worker(native_home, sid=SID, status="working")

        def gone_run(argv, **kwargs):
            return _t.SimpleNamespace(
                returncode=1,
                stdout="No job matching 'aaaabbbb'. Run 'claude agents' to "
                       "list running sessions.",
                stderr="")

        rc = fleet.cmd_kill(_kill_args(), run=gone_run, which=lambda _: "claude")
        out, err = capsys.readouterr()
        assert rc == 0, f"kill on an already-gone sid must not exit 1: {err}"
        assert "investigate" not in err.lower(), (
            f"must not send the operator after a session that is gone: {err}")
        assert "w1: killed" in out

    def test_kill_on_an_already_gone_sid_stamps_outcome_true(self, native_home):
        """The durable half of the same defect: `interrupt_outcome=False` was a
        WRONG DATUM in the event log, not just a console message."""
        import types as _t
        seed_native_worker(native_home, sid=SID, status="working")
        fleet.cmd_kill(_kill_args(),
                       run=lambda *a, **k: _t.SimpleNamespace(
                           returncode=1, stdout="No job matching 'aaaabbbb'.",
                           stderr=""),
                       which=lambda _: "claude")
        events = [json.loads(ln) for ln in
                  fleet.events_path().read_text(encoding="utf-8").splitlines() if ln]
        killed = [e for e in events if e.get("kind") == "killed"]
        assert killed and killed[-1]["interrupt_outcome"] is True, killed
        # G10 tombstone obligation is unconditional -- unchanged by any of this.
        assert any(o.get("kind") == "killed"
                   for o in fleet.read_outcomes("w1", sid=SID))

    def test_retired_sid_sweep_reports_outcome_on_stop_failure(self, native_home, capsys):
        """M5 fix wave (review MD-CONTRACT-REVIEW-2026-07-17.md): this test
        used to pin `... timeout` for ANY non-zero stop. That was a specific
        and wrong diagnosis -- a retired sid is an abandoned fork, so
        "already gone" is the common case, and naming it "timeout" invited
        the operator to hunt a hung daemon that was never there. The sweep
        now prints the classified outcome. This stub emits a bare rc=1 with
        no message, which classifies as the unknown-failure case."""
        rec = seed_native_worker(native_home, sid=SID, status="working")
        rec["retired_sids"] = ["retired1sid"]
        fleet.save_registry({"workers": {"w1": rec}})
        fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=1), which=lambda _: "claude")
        err = capsys.readouterr().err
        assert "stopping retired session retired1... failed" in err
        assert "timeout" not in err, (
            f"'timeout' names a mechanism that did not occur: {err}")

    # T8 fix wave (adv M1, Minor) -- cross-worker ownership check on a
    # corrupted/hand-edited registry.

    def test_retired_sid_matching_another_workers_current_sid_is_skipped(self, native_home, capsys):
        victim_sid = "victim-live-sid"
        attacker = fleet.new_worker_record(SID, "C:/proj", "t", "accept", dispatch_kind="bg")
        attacker["status"] = "working"
        attacker["native_short_id"] = SID[:8]
        attacker["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
        attacker["retired_sids"] = [victim_sid]
        victim = fleet.new_worker_record(victim_sid, "C:/proj", "t", "accept", dispatch_kind="bg")
        victim["status"] = "working"
        victim["native_short_id"] = victim_sid[:8]
        victim["last_dispatch_at"] = _iso(NOW - timedelta(minutes=1))
        fleet.save_registry({"workers": {"attacker": attacker, "victim": victim}})

        calls = []
        rc = fleet.cmd_kill(_kill_args(name="attacker"),
                            run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")
        assert rc == 0
        stopped = {c[0][2] for c in calls if c[0][:2] == ["claude", "stop"]}
        assert victim_sid not in stopped
        assert fleet._native_job_ref(victim_sid) not in stopped
        assert stopped == {fleet._native_job_ref(SID)}
        err = capsys.readouterr().err
        assert "skipping" in err
        # victim's own registry record is untouched.
        assert fleet.load_registry()["workers"]["victim"] == victim

    def test_stop_failure_still_marks_dead_but_warns_and_nonzero(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        rc = fleet.cmd_kill(_kill_args(), run=_fake_run_factory(rc=1), which=lambda _: "claude")

        assert rc != 0
        combined = "".join(capsys.readouterr())
        assert "w1" in combined
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"

    def test_unknown_worker_raises(self, native_home):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_kill(_kill_args(name="nope"), which=lambda _: "claude")

class TestCmdInterruptNative:
    def test_marks_interrupted_not_idle(self, native_home):
        seed_native_worker(native_home, sid=SID, status="working")
        rc = fleet.cmd_interrupt(_interrupt_args(), run=_fake_run_factory(rc=0), which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "interrupted"

    def test_stops_and_writes_tombstone(self, native_home):
        seed_native_worker(native_home, sid=SID, status="working")
        calls = []
        fleet.cmd_interrupt(_interrupt_args(), run=_fake_run_factory(rc=0, calls=calls), which=lambda _: "claude")
        stop_call = next(c for c in calls if c[0][:2] == ["claude", "stop"])
        assert stop_call[0] == ["claude", "stop", fleet._native_job_ref(SID)]
        outcomes = fleet.read_outcomes("w1", sid=SID)
        assert any(o["kind"] == "interrupted" for o in outcomes)
        assert "interrupted" in _events_kinds(native_home)

    def test_prints_respawn_hint(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        fleet.cmd_interrupt(_interrupt_args(), run=_fake_run_factory(rc=0), which=lambda _: "claude")
        out = capsys.readouterr().out
        assert "stopped via claude stop" in out
        assert "marked interrupted" in out
        assert "fleet respawn w1" in out

    def test_commits_even_when_stop_fails(self, native_home):
        # G10/respawn's own precedent: the tombstone + status flip commit
        # regardless of the stop's own exit code -- an operator-initiated
        # stop was genuinely attempted either way.
        seed_native_worker(native_home, sid=SID, status="working")
        rc = fleet.cmd_interrupt(_interrupt_args(), run=_fake_run_factory(rc=1), which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "interrupted"

    def test_launch_in_flight_refuses(self, native_home):
        # T8 fix wave (adv C1): a dispatch pre-claim (no real sid yet) now
        # refuses loudly (exit 1) rather than a silent friendly no-op --
        # a dispatch may still land any moment and the operator should
        # know interrupt did nothing, not assume it succeeded.
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        fleet.save_registry({"workers": {"w1": rec}})

        def boom_run(*a, **kw):
            raise AssertionError("must not attempt a stop with no real sid yet")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 1
        assert fleet.load_registry()["workers"]["w1"]["status"] == "working"

    # T8 fix wave (adv C1, CRITICAL) -- status guard: interrupt only ever
    # fires `claude stop` + tombstone + status flip on a `working` verdict.
    # Every other status either friendly-no-ops or refuses loudly, and
    # NEVER touches the registry or fires a stop call.

    def test_dead_is_a_noop_never_un_terminals(self, native_home):
        # Trap: pre-fix, this silently overwrote a sticky `dead` status to
        # `interrupted` with rc==0 and fired a live `claude stop` against a
        # sid fleet's own registry already called gone.
        seed_native_worker(native_home, sid=SID, status="dead")

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop a sid already marked dead")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead"

    def test_already_interrupted_is_a_noop(self, native_home):
        seed_native_worker(native_home, sid=SID, status="interrupted")

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop an already-interrupted sid")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "interrupted"

    def test_idle_is_a_noop(self, native_home):
        seed_native_worker(native_home, sid=SID, status="idle")

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop a finished (idle) sid")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "idle"

    def test_limited_refuses_and_is_preserved_for_resume_limited(self, native_home, capsys):
        # Adversarial doc's own named repro: interrupting a `limited`
        # worker used to silently drop it out of `resume-limited`'s
        # `status == "limited"` filter forever, permanently breaking
        # usage-limit auto-continuity (spec Sec5.1.1) with rc==0 and no
        # signal. Must now refuse loudly and leave status untouched.
        rec = seed_native_worker(native_home, sid=SID, status="limited")
        rec["limit_reset_at"] = _iso(NOW + timedelta(hours=1))
        rec["limit_kind"] = "plan_usage"
        fleet.save_registry({"workers": {"w1": rec}})

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop a parked (limited) sid")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 1
        err = capsys.readouterr().err
        assert "limited" in err and "resume-limited" in err
        workers = fleet.load_registry()["workers"]
        assert workers["w1"]["status"] == "limited"
        assert {n for n, r in workers.items() if r["status"] == "limited"} == {"w1"}

    def test_dead_suspected_refuses_with_investigate_hint(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="dead-suspected")

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop a dead-suspected sid")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 1
        err = capsys.readouterr().err
        assert "dead-suspected" in err
        assert "peek" in err or "result" in err
        assert fleet.load_registry()["workers"]["w1"]["status"] == "dead-suspected"

    def test_other_sticky_status_refuses_generically(self, native_home, capsys):
        # attached/over_ceiling/over_budget: not explicitly named by the
        # contract, but none of them is a plain live turn either -- the
        # generic default branch must still refuse rather than silently
        # overwrite.
        seed_native_worker(native_home, sid=SID, status="attached")

        def boom_run(*a, **kw):
            raise AssertionError("must not claude-stop an attached sid")

        rc = fleet.cmd_interrupt(_interrupt_args(), run=boom_run, which=lambda _: "claude")
        assert rc == 1
        assert fleet.load_registry()["workers"]["w1"]["status"] == "attached"

    def test_tombstone_prevents_dead_suspected_on_next_recompute(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="working")
        fleet.cmd_interrupt(_interrupt_args(), run=_fake_run_factory(rc=0), which=lambda _: "claude")

        after_interrupt = fleet.load_registry()["workers"]["w1"]
        assert after_interrupt["status"] == "interrupted"

        # Roster shows the sid gone entirely (as a real `claude stop` would
        # leave it) -- a non-sticky verdict would investigate and land on
        # dead-suspected; `interrupted` is in _NATIVE_STICKY, so it must not.
        verdict = fleet.recompute_worker_native("w1", after_interrupt, [])
        assert verdict["status"] == "interrupted"

class TestCmdResultNative:
    def test_prints_result_text_and_token_line(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "result_text": "all done", "input_tokens": 10,
                                    "output_tokens": 20, "model": "claude-haiku-4-5"})
        rc = fleet.cmd_result(_result_args())
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "all done"
        assert "in=10" in captured.err
        assert "out=20" in captured.err
        assert "claude-haiku-4-5" in captured.err

    def test_no_record_exit_1(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        rc = fleet.cmd_result(_result_args())
        assert rc == 1
        assert "no outcome record" in capsys.readouterr().err

    def test_tombstone_no_result_exit_1(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="interrupted")
        fleet.write_tombstone_outcome("w1", SID, "interrupted")
        rc = fleet.cmd_result(_result_args())
        assert rc == 1
        assert "interrupted" in capsys.readouterr().err

    def test_null_result_text_treated_as_no_result(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result",
                                    "result_text": None})
        rc = fleet.cmd_result(_result_args())
        assert rc == 1
        assert capsys.readouterr().out == ""

    def test_only_current_sid_outcome_counts(self, native_home, capsys):
        old_sid = "old-sid-0000"
        seed_native_worker(native_home, sid=SID, status="idle", retired_sids=[old_sid])
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": old_sid, "kind": "result",
                                    "result_text": "stale from a prior fork"})
        rc = fleet.cmd_result(_result_args())
        assert rc == 1
        assert "stale from a prior fork" not in capsys.readouterr().out

    def test_launch_in_flight_exit_1(self, native_home, capsys):
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        fleet.save_registry({"workers": {"w1": rec}})
        rc = fleet.cmd_result(_result_args())
        assert rc == 1
        assert "no outcome record" in capsys.readouterr().err

    def test_unknown_worker_raises(self, native_home):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_result(_result_args(name="nope"))

class TestCmdPeekNative:
    def _write_transcript(self, home, sid, records):
        path = home / "transcript.jsonl"
        lines = []
        for r in records:
            lines.append(r if isinstance(r, str) else json.dumps(r))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": sid, "kind": "result",
                                    "transcript_path": str(path), "result_text": "ok"})
        return path

    def test_renders_assistant_tool_and_user_lines(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        self._write_transcript(native_home, SID, [
            {"type": "system", "message": {}},
            "not valid json {{{",
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Hello world"},
                {"type": "tool_use", "name": "Bash"},
            ]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "do the thing"}]},
             "isMeta": False},
            {"type": "user", "message": {"content": [{"type": "text", "text": "synthetic reminder"}]},
             "isMeta": True},
        ])
        rc = fleet.cmd_peek(_peek_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "[text] Hello world" in out
        assert "[tool] Bash" in out
        assert "[user] do the thing" in out
        assert "[user:meta] synthetic reminder" in out

    def test_no_transcript_exit_1(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        rc = fleet.cmd_peek(_peek_args())
        assert rc == 1
        assert capsys.readouterr().err

    def test_launch_in_flight_exit_1(self, native_home, capsys):
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        fleet.save_registry({"workers": {"w1": rec}})
        rc = fleet.cmd_peek(_peek_args())
        assert rc == 1
        assert capsys.readouterr().err

    def test_works_mid_turn(self, native_home, capsys):
        # Peek's whole point: no completed-turn outcome required, just a
        # transcript to tail.
        seed_native_worker(native_home, sid=SID, status="working")
        path = native_home / "transcript.jsonl"
        path.write_text(json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "still working"}]}}) + "\n", encoding="utf-8")
        import fleet as fleet_mod
        orig = fleet_mod.find_transcript_path
        try:
            fleet_mod.find_transcript_path = lambda name, sid: path
            rc = fleet.cmd_peek(_peek_args())
        finally:
            fleet_mod.find_transcript_path = orig
        assert rc == 0
        assert "[text] still working" in capsys.readouterr().out

    def test_unknown_worker_raises(self, native_home):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_peek(_peek_args(name="nope"))

class TestCmdAttachNative:
    def test_refuses_with_hint(self, native_home):
        seed_native_worker(native_home, sid=SID, status="idle")
        with pytest.raises(fleet.FleetCliError, match="native worker"):
            fleet.cmd_attach(_attach_args())

    def test_message_names_the_sid(self, native_home):
        seed_native_worker(native_home, sid=SID, status="idle")
        with pytest.raises(fleet.FleetCliError, match=SID):
            fleet.cmd_attach(_attach_args())

    def test_registry_untouched(self, native_home):
        seed_native_worker(native_home, sid=SID, status="idle")
        before = fleet.load_registry()["workers"]["w1"]
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_attach(_attach_args())
        assert fleet.load_registry()["workers"]["w1"] == before

    def test_refuses_even_with_force(self, native_home):
        seed_native_worker(native_home, sid=SID, status="working")
        with pytest.raises(fleet.FleetCliError, match="native worker"):
            fleet.cmd_attach(_attach_args(force=True))

    def test_unknown_worker_raises(self, native_home):
        with pytest.raises(fleet.FleetCliError):
            fleet.cmd_attach(_attach_args(name="nope"))


class TestCmdCleanNative:
    def test_deletes_dead_and_sweeps_files(self, native_home, monkeypatch):
        # T8 fix wave (review CRITICAL): native clean is dead-ONLY, exact
        # legacy parity -- idle and interrupted are proven NOT deleted by
        # the dedicated regression tests below.
        data = {"workers": {}}
        for name, status in (("dead-w1", "dead"), ("dead-w2", "dead")):
            rec = fleet.new_worker_record(f"{name}-sid", "C:/proj", "do it", "accept", dispatch_kind="bg")
            rec["status"] = status
            rec["native_short_id"] = f"{name}-sid"[:8]
            rec["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
            data["workers"][name] = rec
        fleet.save_registry(data)
        for name, _status in (("dead-w1", "dead"), ("dead-w2", "dead")):
            fleet.append_outcome(name, {"ts": _iso(NOW), "session_id": f"{name}-sid",
                                        "kind": "result", "result_text": "done"})
            task_file = fleet.task_file_path(name)
            task_file.parent.mkdir(parents=True, exist_ok=True)
            task_file.write_text("the task", encoding="utf-8")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        rc = fleet.cmd_clean(_clean_args())
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert workers == {}
        for name in ("dead-w1", "dead-w2"):
            assert not fleet.outcome_path(name).exists()
            assert not fleet.outcome_path(f"{name}-sid").exists()
            assert not fleet.task_file_path(name).exists()

    def test_never_deletes_idle(self, native_home, monkeypatch):
        # T8 fix wave (review CRITICAL): an earlier revision swept `idle`
        # native workers on a false "matches today's legacy semantics"
        # premise -- legacy is dead-only (confirmed against 8e79dbe).
        # `idle` means finished-and-still-steerable; a native worker's own
        # `claude --resume` survives regardless, but fleet's OWN
        # bookkeeping (registry entry, outcomes, task file) must not
        # vanish out from under an operator who can still `fleet send` it.
        #
        # Roll-up item 6: the original version of this test seeded an idle
        # worker with an EMPTY roster and no outcome record --
        # recompute_worker_native derives dead-suspected for that shape
        # (itself also non-deletable), so the test never actually exercised
        # a genuine `idle` verdict against the clean sweep. Force one: a
        # live roster entry (status="idle") plus a fresh outcome record for
        # the same sid, dispatched before the outcome's ts.
        last_dispatch_at = _iso(NOW - timedelta(minutes=5))
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_dispatch_at=last_dispatch_at)
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        roster = [make_roster_entry(SID, status="idle")]
        # Sanity: the seeded shape genuinely recomputes to idle, not
        # dead-suspected -- otherwise this test would silently degrade back
        # into the same test-theater it replaces.
        assert fleet.recompute_worker_native("w1", rec, roster)["status"] == "idle"
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, roster))
        fleet.cmd_clean(_clean_args())
        assert "w1" in fleet.load_registry()["workers"]

    def test_never_deletes_interrupted(self, native_home, monkeypatch):
        # T8 fix wave (binding contract): `interrupted` is respawn-eligible
        # by design -- an operator who wants to abandon it kills it first
        # (which recomputes to `dead`, then IS swept). `clean` sweeping
        # `interrupted` directly would remove that explicit choice.
        seed_native_worker(native_home, sid=SID, status="interrupted")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        fleet.cmd_clean(_clean_args())
        assert "w1" in fleet.load_registry()["workers"]

    def test_sweeps_retired_sid_outcome_and_ceiling_files(self, native_home, monkeypatch):
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="dead",
                                 retired_sids=["old-1", "old-2"])
        for s in ["old-1", "old-2", SID]:
            fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": s, "kind": "result"})
            fleet.ceiling_file_path(s).parent.mkdir(parents=True, exist_ok=True)
            fleet.ceiling_file_path(s).write_text("100", encoding="utf-8")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))

        fleet.cmd_clean(_clean_args())
        for s in ["old-1", "old-2", SID]:
            assert not fleet.outcome_path(s).exists()
            assert not fleet.ceiling_file_path(s).exists()

    def test_never_deletes_dead_suspected(self, native_home, monkeypatch):
        seed_native_worker(native_home, sid=SID, status="dead-suspected")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        fleet.cmd_clean(_clean_args())
        assert "w1" in fleet.load_registry()["workers"]

    def test_never_deletes_limited(self, native_home, monkeypatch):
        seed_native_worker(native_home, sid=SID, status="limited")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (True, []))
        fleet.cmd_clean(_clean_args())
        assert "w1" in fleet.load_registry()["workers"]

    def test_never_deletes_working(self, native_home, monkeypatch):
        seed_native_worker(native_home, sid=SID, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            lambda **_: (True, [make_roster_entry(SID, status="busy")]))
        fleet.cmd_clean(_clean_args())
        assert "w1" in fleet.load_registry()["workers"]

    def test_epoch_frozen_refuses_all_cleaning(self, native_home, monkeypatch, capsys):
        seed_native_worker(native_home, name="native-w", sid=SID, status="dead")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "roster fetch failed"))

        rc = fleet.cmd_clean(_clean_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "EPOCH" in out
        workers = fleet.load_registry()["workers"]
        assert "native-w" in workers  # frozen -- untouched

    def test_empty_registry_never_fetches_roster(self, native_home):
        fleet.save_registry({"workers": {}})

        def boom_roster(**kw):
            raise AssertionError("must not fetch the roster with no worker in the registry")

        import fleet as fleet_mod
        monkeypatch_target = fleet_mod._fetch_agents_roster
        fleet_mod._fetch_agents_roster = boom_roster
        try:
            rc = fleet.cmd_clean(_clean_args())
        finally:
            fleet_mod._fetch_agents_roster = monkeypatch_target
        assert rc == 0


# ---------------------------------------------------------------------------
# M-B Task 9: auto-archival (spec §5.1.2).
# ---------------------------------------------------------------------------

def _archive_args(name=None, ttl_hours=None, dry_run=False):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, ttl_hours=ttl_hours, dry_run=dry_run)


def seed_archive_ready_worker(home, name="w1", sid=SID, status="idle",
                              retired_sids=(), age_hours=25.0, **overrides):
    """A native record that passes every `_archive_eligible` gate against an
    empty roster: terminal status, last_activity `age_hours` in the REAL
    past (cmd_archive's own `now` is real wall-clock, un-injectable, like
    every other recompute path in this module), and a matching outcome
    record for its current sid."""
    overrides.setdefault(
        "last_activity",
        _iso(datetime.now(timezone.utc) - timedelta(hours=age_hours)),
    )
    overrides.setdefault("retired_sids", list(retired_sids))
    rec = seed_native_worker(home, name=name, sid=sid, status=status, **overrides)
    fleet.append_outcome(name, {"ts": _iso(NOW), "session_id": sid, "kind": "result",
                                "result_text": "done"})
    return rec


def seed_archived_worker(home, name="w1", sid=SID, status="idle", **overrides):
    overrides.setdefault("archived_at", _iso(NOW))
    return seed_native_worker(home, name=name, sid=sid, status=status, **overrides)


def _archive_fake_run(rc=0, calls=None, roster_stdout="[]"):
    """Unlike `_fake_run_factory` (one fixed stdout for every argv), a real
    `cmd_archive` non-dry-run invocation drives TWO distinct `claude`
    subcommands in one call: `agents --json --all` (the roster fetch,
    which needs valid JSON or `native_epoch_suspicious` freezes the whole
    command) and `rm <sid>` (the archival primitive, whose exit code this
    fake controls via `rc`). Discriminates on argv[1]."""
    import types

    def fake_run(argv, **kwargs):
        if calls is not None:
            calls.append((argv, kwargs))
        if len(argv) >= 2 and argv[1] == "agents":
            return types.SimpleNamespace(returncode=0, stdout=roster_stdout, stderr="")
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")
    return fake_run


class TestArchiveEligible:
    def test_eligible_all_gates_pass(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW) == (True, "eligible")

    @pytest.mark.parametrize("status", ["working", "attached", "over_ceiling", "over_budget", "dead-suspected"])
    def test_ineligible_bad_status(self, native_home, status):
        rec = seed_native_worker(native_home, sid=SID, status=status,
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, f"status:{status}")

    def test_ineligible_limited(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="limited",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "status:limited")

    def test_ineligible_legacy_record(self, native_home):
        rec = fleet.new_worker_record(SID, "C:/proj", "t", "accept")  # dispatch_kind None
        rec["status"] = "idle"
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "not-native")

    def test_ineligible_already_archived(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)),
                                 archived_at=_iso(NOW))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "already-archived")

    def test_ineligible_roster_live_entry(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        entries = [make_roster_entry(SID, status="busy")]
        assert fleet._archive_eligible("w1", rec, entries, NOW) == (False, "roster-live")

    def test_roster_state_only_dead_entry_does_not_block(self, native_home):
        # A roster entry carrying only `state` (no status/pid keys) is DEAD
        # per contract -- must never block eligibility.
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        entries = [make_roster_entry(SID, status=None, pid=None)]
        assert fleet._archive_eligible("w1", rec, entries, NOW) == (True, "eligible")

    def test_ineligible_no_outcome_record(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "no-outcome-record")

    def test_ineligible_no_outcome_record_dead_suspected_never_auto_archived(self, native_home):
        # Trap named in advance (task-9-brief.md): roster-gone with NO
        # outcome record is dead-suspected territory, never auto-archived,
        # even once the roster entry is confirmed gone.
        rec = seed_native_worker(native_home, sid=SID, status="dead",
                                 last_activity=_iso(NOW - timedelta(hours=100)))
        ok, reason = fleet._archive_eligible("w1", rec, [], NOW)
        assert (ok, reason) == (False, "no-outcome-record")

    def test_ineligible_ttl_not_elapsed(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=1)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "ttl-not-elapsed")

    def test_ttl_boundary_exact_elapsed_is_eligible(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=24)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW) == (True, "eligible")

    def test_custom_ttl_hours_param(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=2)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW, ttl_hours=1.0) == (True, "eligible")
        assert fleet._archive_eligible("w1", rec, [], NOW, ttl_hours=3.0) == (False, "ttl-not-elapsed")

    def test_malformed_last_activity_fails_safe(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle", last_activity="not-a-date")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "last-activity-unparseable")

    def test_missing_last_activity_fails_safe(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="idle")
        del rec["last_activity"]
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "last-activity-unparseable")

    def test_no_session_id_ineligible(self, native_home):
        rec = fleet.new_worker_record(None, "C:/proj", "t", "accept", dispatch_kind="bg")
        rec["status"] = "dead"
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "no-session-id")

    def test_default_ttl_constant_is_24_hours(self):
        assert fleet.ARCHIVE_TTL_HOURS_DEFAULT == 24.0

    # T9 fix wave (spec review Minor: gate-precedence not test-locked) --
    # pin which reason wins when a record independently violates two gates.
    def test_gate_precedence_already_archived_beats_bad_status(self, native_home):
        rec = seed_native_worker(native_home, sid=SID, status="working",
                                 last_activity=_iso(NOW - timedelta(hours=25)),
                                 archived_at=_iso(NOW))
        assert fleet._archive_eligible("w1", rec, [], NOW) == (False, "already-archived")

    def test_gate_precedence_roster_live_beats_no_outcome_record(self, native_home):
        # status is idle (gate 2 would pass) and NO outcome record exists
        # (would independently fail gate 4) -- roster-live (gate 3) must
        # still be the reported reason, since it is checked first.
        rec = seed_native_worker(native_home, sid=SID, status="idle",
                                 last_activity=_iso(NOW - timedelta(hours=25)))
        entries = [make_roster_entry(SID, status="busy")]
        assert fleet._archive_eligible("w1", rec, entries, NOW) == (False, "roster-live")


class TestCmdArchive:
    def test_archive_dry_run_mutates_nothing(self, native_home, capsys):
        seed_archive_ready_worker(native_home)
        before = fleet.load_registry()
        calls = []

        rc = fleet.cmd_archive(_archive_args(dry_run=True), run=_archive_fake_run(calls=calls),
                               which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry() == before
        assert "w1: eligible" in capsys.readouterr().out
        assert fleet.outcome_path("w1").exists()
        assert not any(c[0][1] == "rm" for c in calls)

    def test_dry_run_prints_skip_reason(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="working")
        # A "working" record needs a LIVE roster entry or an empty roster
        # trips G9 (empty roster + a record claiming "working" is exactly
        # the epoch-suspicious shape) -- irrelevant to the gate under test
        # (status fails before roster is ever consulted).
        roster = json.dumps([make_roster_entry(SID, status="busy")])
        rc = fleet.cmd_archive(_archive_args(dry_run=True),
                               run=_archive_fake_run(roster_stdout=roster),
                               which=lambda _: "claude")
        assert "w1: skipped -- status:working" in capsys.readouterr().out

    def test_archive_moves_files_and_rms_all_sids(self, native_home):
        seed_archive_ready_worker(native_home, retired_sids=["retired1-a", "retired2-b"])
        # sid-keyed outcome files (the Stop hook's fallback key) for the
        # current sid AND each retired sid -- these are separate FILES
        # (outcome_path(sid)), not the name-keyed one seed_archive_ready_worker
        # already wrote.
        fleet.append_outcome(SID, {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        for s in ["retired1-a", "retired2-b"]:
            fleet.append_outcome(s, {"ts": _iso(NOW), "session_id": s, "kind": "result"})
        task_file = fleet.task_file_path("w1")
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text("the task", encoding="utf-8")
        journal = fleet.journals_dir() / "w1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("journal text", encoding="utf-8")
        calls = []

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0, calls=calls),
                               which=lambda _: "claude")
        assert rc == 0

        rm_sids = {c[0][2] for c in calls if c[0][:2] == ["claude", "rm"]}
        assert rm_sids == {fleet._native_job_ref(SID), "retired1", "retired2"}

        dest = fleet.archive_root() / "w1"
        assert (dest / "journal.md").read_text(encoding="utf-8") == "journal text"
        assert (dest / "task.md").exists()
        assert (dest / "w1.jsonl").exists()          # name-keyed outcome file
        assert (dest / f"{SID}.jsonl").exists()       # current sid's outcome file
        assert (dest / "retired1-a.jsonl").exists()
        assert (dest / "retired2-b.jsonl").exists()
        assert not task_file.exists()
        assert not journal.exists()
        assert not fleet.outcome_path("w1").exists()

        rec_after = fleet.load_registry()["workers"]["w1"]
        assert rec_after["archived_at"] is not None
        assert rec_after["session_id"] == SID  # tombstoned overlay -- history readable
        assert "w1" in fleet.load_registry()["workers"]  # registry entry SURVIVES
        assert "archived" in _events_kinds(native_home)

    # T9 fix wave (finding C1, CRITICAL): a retired sid abandoned by a
    # fork-steer can still be genuinely live in the roster at archive-time
    # -- gate 3 of _archive_eligible only ever checked the CURRENT sid, so
    # the un-gated rm loop swept a live retired sid's roster entry (and its
    # backing ~/.claude/jobs/<short>/ dir) out from under a still-running
    # session. The rm loop must now skip any sid (current OR retired) the
    # roster shows live, report it, and still archive everything else.
    def test_rm_skips_a_live_retired_sid_but_rms_current_sid(self, native_home, capsys):
        seed_archive_ready_worker(native_home, retired_sids=["retired-1"])
        calls = []
        roster = json.dumps([make_roster_entry("retired-1", status="busy")])

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0, calls=calls,
                                                                       roster_stdout=roster),
                               which=lambda _: "claude")
        assert rc == 0

        rm_sids = {c[0][2] for c in calls if c[0][:2] == ["claude", "rm"]}
        assert rm_sids == {fleet._native_job_ref(SID)}  # only the (dead-per-roster) current sid was rm'd
        err = capsys.readouterr().err
        assert "skipping rm" in err and "session live in roster" in err
        # the archive itself still proceeds -- the live retired sid is
        # skipped, not a reason to block the whole worker.
        assert fleet.load_registry()["workers"]["w1"]["archived_at"] is not None

    def test_archive_prints_summary_counts(self, native_home, capsys):
        busy_sid = "busybusy-1111-2222-3333-444455556666"
        ready = seed_archive_ready_worker(native_home, name="ready", sid=SID)
        busy = fleet.new_worker_record(busy_sid, "C:/proj", "t", "accept", dispatch_kind="bg")
        busy["status"] = "working"
        busy["native_short_id"] = "busybusy"
        busy["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
        fleet.save_registry({"workers": {"ready": ready, "busy": busy}})
        # "busy" claims status=="working" -- give it a LIVE roster entry so
        # G9's epoch check doesn't read an empty roster as suspicious.
        roster = json.dumps([make_roster_entry(busy_sid, status="busy")])

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0, roster_stdout=roster),
                               which=lambda _: "claude")
        assert rc == 0
        assert "archived 1 worker(s), skipped 1" in capsys.readouterr().out

    def test_named_worker_archives_alone(self, native_home):
        seed_archive_ready_worker(native_home, name="w1", sid=SID)
        w2_sid = "22222222-1111-2222-3333-444455556666"
        w2 = fleet.new_worker_record(w2_sid, "C:/proj", "t", "accept", dispatch_kind="bg")
        w2["status"] = "working"
        w2["native_short_id"] = "22222222"
        w2["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
        data = fleet.load_registry()
        data["workers"]["w2"] = w2
        fleet.save_registry(data)
        # G9's epoch check reads the WHOLE registry, not just the named
        # worker -- w2 claims "working", so it needs a live roster entry
        # or an empty roster would (correctly) freeze this invocation.
        roster = json.dumps([make_roster_entry(w2_sid, status="busy")])

        rc = fleet.cmd_archive(_archive_args(name="w1"),
                               run=_archive_fake_run(rc=0, roster_stdout=roster),
                               which=lambda _: "claude")
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert workers["w1"]["archived_at"] is not None
        assert workers["w2"]["archived_at"] is None

    def test_custom_ttl_hours_flows_through(self, native_home, capsys):
        seed_native_worker(native_home, sid=SID, status="idle",
                           last_activity=_iso(
                               datetime.now(timezone.utc) - timedelta(hours=2)))
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        rc = fleet.cmd_archive(_archive_args(dry_run=True, ttl_hours=1.0),
                               run=_archive_fake_run(), which=lambda _: "claude")
        assert rc == 0
        assert "w1: eligible" in capsys.readouterr().out

    def test_unknown_worker_raises(self, native_home):
        with pytest.raises(fleet.FleetCliError, match="unknown worker"):
            fleet.cmd_archive(_archive_args(name="nope"))

    def test_already_archived_named_worker_refuses(self, native_home):
        seed_archived_worker(native_home)
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_archive(_archive_args(name="w1"))

    def test_already_archived_is_silently_skipped_in_bulk_sweep(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_archive(_archive_args())
        assert rc == 0
        assert "archived 0 worker(s), skipped 1" in capsys.readouterr().out

    def test_missing_files_skipped_silently_no_crash(self, native_home):
        # No journal/task file ever created on disk -- move is a silent no-op.
        seed_archive_ready_worker(native_home)
        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0), which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["archived_at"] is not None

    def test_rm_failure_is_non_fatal_still_archives(self, native_home, capsys):
        seed_archive_ready_worker(native_home)
        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=1), which=lambda _: "claude")
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["archived_at"] is not None
        # 2.1.212 contract change [PENDING-RATIFICATION]: rm failures are now
        # reported as "deferred (<outcome>)" with the reason spelled out --
        # rc=1 alone no longer means "failed" (it can mean already-gone, or a
        # transient dead daemon). Evidence: docs/reviews/
        # CLAUDE-2.1.212-CONTRACT-2026-07-17.md §Q3. This stub emits a bare
        # rc=1 with no message, so it classifies as the unknown-failure case.
        # Unchanged, and the point of this test: non-fatal, still archives.
        assert "rm aaaabbbb... deferred (failed)" in capsys.readouterr().err

    def test_collision_suffixes_existing_archive_dir(self, native_home):
        fleet.archive_root().mkdir(parents=True, exist_ok=True)
        (fleet.archive_root() / "w1").mkdir()
        seed_archive_ready_worker(native_home)
        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0), which=lambda _: "claude")
        assert rc == 0
        assert (fleet.archive_root() / "w1.1").exists()


class TestCmdArchiveEpochFreeze:
    def test_epoch_frozen_refuses_entirely_zero_mutations(self, native_home, monkeypatch, capsys):
        seed_archive_ready_worker(native_home)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "roster down"))
        before = fleet.load_registry()

        rc = fleet.cmd_archive(_archive_args())
        assert rc == 1
        assert fleet.load_registry() == before
        assert "EPOCH" in "".join(capsys.readouterr())

    def test_epoch_frozen_blocks_dry_run_too(self, native_home, monkeypatch, capsys):
        seed_archive_ready_worker(native_home)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "roster down"))
        rc = fleet.cmd_archive(_archive_args(dry_run=True))
        assert rc == 1
        combined = "".join(capsys.readouterr())
        assert "EPOCH" in combined
        assert "eligible" not in combined

    def test_no_native_workers_never_fetches_roster(self, native_home):
        rec = fleet.new_worker_record("legacy-sid", "C:/proj", "t", "accept")
        rec["status"] = "idle"
        fleet.save_registry({"workers": {"legacy1": rec}})

        def boom_roster(**kw):
            raise AssertionError("must not fetch roster with no native worker in the registry")

        import fleet as fleet_mod
        prev = fleet_mod._fetch_agents_roster
        fleet_mod._fetch_agents_roster = boom_roster
        try:
            rc = fleet.cmd_archive(_archive_args())
        finally:
            fleet_mod._fetch_agents_roster = prev
        assert rc == 0


class TestCmdArchiveForeignRosterUntouched:
    def test_only_this_workers_own_sids_reach_rm(self, native_home, monkeypatch):
        seed_archive_ready_worker(native_home, retired_sids=["retired-1"])
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": "retired-1", "kind": "result"})
        calls = []
        monkeypatch.setattr(
            fleet, "_fetch_agents_roster",
            lambda **_: (True, [make_roster_entry("foreign-sid-999", status="busy",
                                                   name="someone else's session")]),
        )
        rc = fleet.cmd_archive(_archive_args(), run=_fake_run_factory(rc=0, calls=calls),
                               which=lambda _: "claude")
        assert rc == 0
        rm_sids = {c[0][2] for c in calls if c[0][:2] == ["claude", "rm"]}
        assert "foreign-sid-999" not in rm_sids
        assert rm_sids == {fleet._native_job_ref(SID), fleet._native_job_ref("retired-1")}


class TestRefuseIfArchived:
    def test_raises_when_archived(self):
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.refuse_if_archived("w1", {"archived_at": _iso(NOW)}, "send")

    def test_noop_when_not_archived(self):
        fleet.refuse_if_archived("w1", {"archived_at": None}, "send")  # no raise

    def test_noop_on_non_dict(self):
        fleet.refuse_if_archived("w1", None, "send")  # no raise


class TestArchivedRefusesMutation:
    def test_send_refuses(self, native_home):
        seed_archived_worker(native_home)
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_send(_send_args())

    def test_respawn_refuses(self, native_home):
        seed_archived_worker(native_home)
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_respawn(_respawn_args())

    def test_kill_refuses(self, native_home):
        seed_archived_worker(native_home)
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_kill(_kill_args())

    def test_interrupt_refuses(self, native_home):
        seed_archived_worker(native_home, status="idle")
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_interrupt(_interrupt_args())

    def test_resume_limited_named_refuses(self, native_home):
        seed_archived_worker(native_home, status="limited")
        from types import SimpleNamespace
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_resume_limited(SimpleNamespace(name="w1", force_now=False))

    def test_archive_again_refuses(self, native_home):
        seed_archived_worker(native_home)
        with pytest.raises(fleet.FleetCliError, match="archived"):
            fleet.cmd_archive(_archive_args(name="w1"))


class TestStatusHidesArchived:
    def test_status_hides_archived_by_default(self, native_home):
        seed_archived_worker(native_home)
        assert fleet.status_snapshot()["workers"] == []

    def test_snapshot_all_includes_archived_flagged(self, native_home):
        seed_archived_worker(native_home)
        snap = fleet.status_snapshot(include_archived=True)
        assert len(snap["workers"]) == 1
        assert snap["workers"][0]["archived_at"] is not None

    def test_cmd_status_stale_ok_hides_by_default(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_status(_status_args(stale_ok=True))
        assert rc == 0
        assert "w1" not in capsys.readouterr().out

    def test_cmd_status_stale_ok_all_shows_flagged(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_status(_status_args(stale_ok=True, all=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "w1" in out and "archived" in out

    def test_cmd_status_stale_ok_explicit_name_finds_archived_without_all(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_status(_status_args(name="w1", stale_ok=True))
        assert rc == 0
        assert "w1" in capsys.readouterr().out

    def test_cmd_status_full_recompute_hides_and_never_touches_archived(self, native_home, capsys):
        seed_archived_worker(native_home)

        def boom_roster(**kw):
            raise AssertionError("must not fetch roster for an archived-only bulk query")

        import fleet as fleet_mod
        prev = fleet_mod._fetch_agents_roster
        fleet_mod._fetch_agents_roster = boom_roster
        try:
            rc = fleet.cmd_status(_status_args())
        finally:
            fleet_mod._fetch_agents_roster = prev
        assert rc == 0
        assert "w1" not in capsys.readouterr().out
        assert fleet.load_registry()["workers"]["w1"]["archived_at"] is not None

    def test_cmd_status_full_recompute_all_shows_frozen_flagged(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_status(_status_args(all=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "w1" in out and "archived" in out
        # frozen -- never recomputed, no roster fetch attempted (would have
        # raised if it tried, since no _fetch_agents_roster stub is installed
        # and none is needed).
        assert fleet.load_registry()["workers"]["w1"]["archived_at"] is not None

    def test_cmd_status_explicit_name_full_recompute_shows_frozen(self, native_home, capsys):
        seed_archived_worker(native_home)
        rc = fleet.cmd_status(_status_args(name="w1"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "w1" in out and "archived" in out


class TestCmdCleanArchived:
    def test_deletes_archived_and_sweeps_archive_dir(self, native_home):
        seed_archived_worker(native_home, status="idle")
        dest = fleet.archive_root() / "w1"
        dest.mkdir(parents=True)
        (dest / "journal.md").write_text("j", encoding="utf-8")

        def boom_roster(**kw):
            raise AssertionError("an archived-only registry must never trigger a roster fetch")

        import fleet as fleet_mod
        prev = fleet_mod._fetch_agents_roster
        fleet_mod._fetch_agents_roster = boom_roster
        try:
            rc = fleet.cmd_clean(_clean_args())
        finally:
            fleet_mod._fetch_agents_roster = prev

        assert rc == 0
        assert "w1" not in fleet.load_registry()["workers"]
        assert not dest.exists()

    def test_epoch_freeze_does_not_block_archived_deletion(self, native_home, monkeypatch, capsys):
        archived = seed_archived_worker(native_home, name="archived-w", sid=SID, status="dead")
        active = fleet.new_worker_record("active-sid-1111-2222-3333-444455556666", "C:/proj", "t",
                                         "accept", dispatch_kind="bg")
        active["status"] = "working"
        active["native_short_id"] = "active-s"
        active["last_dispatch_at"] = _iso(NOW - timedelta(minutes=5))
        fleet.save_registry({"workers": {"archived-w": archived, "active-w": active}})
        monkeypatch.setattr(fleet, "_fetch_agents_roster", lambda **_: (False, "roster down"))

        rc = fleet.cmd_clean(_clean_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "EPOCH" in out
        workers = fleet.load_registry()["workers"]
        assert "active-w" in workers      # frozen -- untouched (native, non-archived)
        assert "archived-w" not in workers  # archived deletion proceeds despite freeze


# T9 fix wave (finding C2, CRITICAL): a concurrent `fleet send` fork-steer
# landing between cmd_archive's eligibility snapshot and its per-worker
# commit must never have its live turn stomped by a stale `archived_at`
# commit -- the commit is now conditional on the record still matching the
# eligibility snapshot exactly (mirroring cmd_status/cmd_clean's own
# "spare a concurrently-mutated record" doctrine).
class TestCmdArchiveConcurrentMutation:
    def test_concurrent_mutation_between_snapshot_and_commit_is_skipped(self, native_home,
                                                                        monkeypatch, capsys):
        seed_archive_ready_worker(native_home)
        real_load = fleet.load_registry
        call_count = {"n": 0}
        new_sid = "newsid01-1111-2222-3333-444455556666"

        def flaky_load():
            call_count["n"] += 1
            if call_count["n"] == 2:
                # Simulate a concurrent fork-steer landing in the window
                # between cmd_archive's eligibility snapshot (call #1) and
                # its per-worker commit (this call): a real fork-steer
                # restamps session_id to a brand-new live sid and flips
                # status to "working".
                data = real_load()
                data["workers"]["w1"]["session_id"] = new_sid
                data["workers"]["w1"]["status"] = "working"
                fleet.save_registry(data)
            return real_load()

        monkeypatch.setattr(fleet, "load_registry", flaky_load)

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0), which=lambda _: "claude")
        assert rc == 0
        err = capsys.readouterr().err
        assert "changed during archive -- skipped" in err

        rec = fleet.load_registry()["workers"]["w1"]
        # the concurrent mutation is respected untouched -- NOT clobbered
        # with a stale archived_at commit on top of the live turn.
        assert rec["archived_at"] is None
        assert rec["status"] == "working"
        assert rec["session_id"] == new_sid
        assert "archived" not in _events_kinds(native_home)


# T9 fix wave (findings C2/3b, CRITICAL+Important): a crash between the
# (now-first) archived_at commit and the file-move phase finishing must
# leave a fully-consistent tombstone -- never a false dead-suspected verdict
# (3b) -- and a re-run of `fleet archive` must RESUME the move into the
# SAME dest dir rather than creating a split-history collision sibling (3a).
class TestCmdArchiveCrashResume:
    def _seed_full_worker(self, native_home, retired_sids=("retired-1",)):
        seed_archive_ready_worker(native_home, retired_sids=list(retired_sids))
        fleet.append_outcome(SID, {"ts": _iso(NOW), "session_id": SID, "kind": "result"})
        for s in retired_sids:
            fleet.append_outcome(s, {"ts": _iso(NOW), "session_id": s, "kind": "result"})
        task_file = fleet.task_file_path("w1")
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text("the task", encoding="utf-8")
        journal = fleet.journals_dir() / "w1.md"
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("journal text", encoding="utf-8")
        mailbox_file = fleet.mailbox_dir() / f"{SID}.md"
        mailbox_file.write_text("pending mail", encoding="utf-8")
        return task_file, journal, mailbox_file

    def test_crash_mid_move_resumes_cleanly_on_rerun(self, native_home, monkeypatch, capsys):
        self._seed_full_worker(native_home)
        real_move = fleet._archive_move
        real_fetch_roster = fleet._fetch_agents_roster
        call_count = {"n": 0}

        def flaky_move(src, dest, name):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("simulated hard crash mid-move")
            return real_move(src, dest, name)

        monkeypatch.setattr(fleet, "_archive_move", flaky_move)

        with pytest.raises(OSError):
            fleet.cmd_archive(_archive_args(name="w1"), run=_archive_fake_run(rc=0),
                              which=lambda _: "claude")

        # The tombstone landed BEFORE the crash (commit-first reorder) --
        # registry is already consistent, no rm attempted yet.
        rec = fleet.load_registry()["workers"]["w1"]
        assert rec["archived_at"] is not None
        assert rec["status"] == "idle"
        assert _events_kinds(native_home).count("archived") == 1

        # 3b: the archived tombstone must never be misread as dead-suspected
        # regardless of which evidence files are mid-move -- cmd_status
        # never recomputes an archived_at record, so this never even
        # touches the roster.
        def boom_roster(**kw):
            raise AssertionError("an archived record must never trigger a roster fetch")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", boom_roster)
        rc = fleet.cmd_status(_status_args(name="w1"))
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "idle"

        # Restore both patched seams before driving the resume run below --
        # it legitimately needs a working _archive_move AND a real roster
        # fetch (the rm phase's live-sid check, finding C1).
        monkeypatch.setattr(fleet, "_archive_move", real_move)
        monkeypatch.setattr(fleet, "_fetch_agents_roster", real_fetch_roster)

        # Re-run: resumes into the SAME dest dir (no ".1" collision sibling)
        # and finishes every pending move + the never-attempted rm calls.
        calls = []
        rc = fleet.cmd_archive(_archive_args(name="w1"), run=_archive_fake_run(rc=0, calls=calls),
                               which=lambda _: "claude")
        assert rc == 0
        err = capsys.readouterr().err
        assert "resuming archive" in err

        dest = fleet.archive_root() / "w1"
        assert not (fleet.archive_root() / "w1.1").exists()
        assert (dest / "journal.md").exists()
        assert (dest / "task.md").exists()
        assert (dest / "w1.jsonl").exists()
        assert (dest / f"{SID}.jsonl").exists()
        assert (dest / "retired-1.jsonl").exists()
        assert (dest / f"{SID}.md").read_text(encoding="utf-8") == "pending mail"

        rm_sids = {c[0][2] for c in calls if c[0][:2] == ["claude", "rm"]}
        assert rm_sids == {fleet._native_job_ref(SID), fleet._native_job_ref("retired-1")}
        # exactly one "archived" event total -- the resume never appends a second.
        assert _events_kinds(native_home).count("archived") == 1


class TestDoctorArchivedMailbox:
    # T9 fix wave (finding M-4b): mailbox files are now part of the archive
    # move inventory ("stranded mail is history too") -- this erases the
    # doctor noise at the source, with no separate doctor-side exclusion
    # needed.
    def test_archived_workers_mailbox_moved_produces_no_doctor_noise(self, native_home):
        seed_archive_ready_worker(native_home)
        mailbox_file = fleet.mailbox_dir() / f"{SID}.md"
        mailbox_file.write_text("pending mail", encoding="utf-8")

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0), which=lambda _: "claude")
        assert rc == 0
        assert not mailbox_file.exists()

        workers = fleet.load_registry()["workers"]
        _name, ok, msg = fleet._doctor_check_mailboxes(workers)
        assert ok is True
        assert "w1" not in msg
        assert (fleet.archive_root() / "w1" / f"{SID}.md").read_text(encoding="utf-8") == "pending mail"


class TestRemoveWorkerFilesArchiveSweep:
    # T9 fix wave (finding M-3a): collision-suffixed archive dirs (left
    # behind by a crash mid-move, or an archive/clean/archive cycle) must
    # not survive `fleet clean` forever.
    def test_sweeps_collision_suffixed_dirs_but_not_unrelated_names(self, native_home):
        (fleet.archive_root() / "w1").mkdir(parents=True)
        (fleet.archive_root() / "w1.1").mkdir(parents=True)
        (fleet.archive_root() / "w1.2").mkdir(parents=True)
        (fleet.archive_root() / "w10").mkdir(parents=True)  # different worker -- must survive

        fleet._remove_worker_files("w1", SID)

        assert not (fleet.archive_root() / "w1").exists()
        assert not (fleet.archive_root() / "w1.1").exists()
        assert not (fleet.archive_root() / "w1.2").exists()
        assert (fleet.archive_root() / "w10").exists()


class TestCleanConfirmArchivedWording:
    # T9 fix wave (finding M-6, Minor): the confirm-prompt line for an
    # archived target names what is actually being destroyed.
    def test_archived_target_confirm_message_mentions_archived_history(self, native_home, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-A")
        rec = seed_archived_worker(native_home, status="dead")
        rec = dict(fleet.load_registry()["workers"]["w1"])
        rec["spawned_by"] = "sess-B"  # foreign -- forces the confirm path
        fleet.save_registry({"workers": {"w1": rec}})

        with pytest.raises(fleet.DestructiveActionRefused) as exc:
            fleet.cmd_clean(_clean_args(yes=False))
        assert "archived history" in str(exc.value)


class TestWaitArchived:
    # T9 fix wave (finding I-4a, Important): an archived native record is
    # frozen history -- `wait_for_workers` must resolve it from its last-
    # committed status alone (never recompute_worker_native), and cmd_wait's
    # persist step must never write over it or append spurious events.
    def test_wait_for_workers_resolves_archived_immediately_without_recompute(self, native_home,
                                                                              monkeypatch):
        seed_archived_worker(native_home, status="idle")

        def boom_roster(**kw):
            raise AssertionError("an archived worker must never trigger a roster fetch in wait")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", boom_roster)

        finished, pending = fleet.wait_for_workers(["w1"], sleep=lambda s: None)
        assert finished == {"w1": "idle"}
        assert pending == set()

    def test_cmd_wait_on_archived_worker_leaves_registry_byte_identical(self, native_home,
                                                                        monkeypatch, capsys):
        seed_archived_worker(native_home, status="idle")
        before = fleet.load_registry()

        def boom_roster(**kw):
            raise AssertionError("an archived worker must never trigger a roster fetch in wait")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", boom_roster)

        rc = fleet.cmd_wait(_wait_args(["w1"]), sleep=lambda s: None)
        assert rc == 0
        assert fleet.load_registry() == before
        assert _events_kinds(native_home) == []
        assert "w1: idle" in capsys.readouterr().out


class TestMainUtf8Reconfigure:
    def test_main_reconfigures_stdout_and_stderr(self, native_home, monkeypatch):
        calls = []

        class FakeStream:
            def __init__(self, real):
                self._real = real
            def reconfigure(self, **kw):
                calls.append(kw)
            def __getattr__(self, item):
                return getattr(self._real, item)

        import sys
        fake_out, fake_err = FakeStream(sys.stdout), FakeStream(sys.stderr)
        monkeypatch.setattr(sys, "stdout", fake_out)
        monkeypatch.setattr(sys, "stderr", fake_err)

        rc = fleet.main(["status", "--stale-ok"])
        assert rc == 0
        assert len(calls) == 2
        for kw in calls:
            assert kw == {"encoding": "utf-8", "errors": "replace"}

    def test_reconfigure_failure_is_swallowed(self, native_home, monkeypatch):
        class BoomStream:
            def reconfigure(self, **kw):
                raise ValueError("no can do")
            def __getattr__(self, item):
                import sys
                return getattr(sys.__stdout__, item)

        import sys
        monkeypatch.setattr(sys, "stdout", BoomStream())
        # Must not raise -- the reconfigure failure is swallowed and main()
        # proceeds normally.
        rc = fleet.main(["status", "--stale-ok"])
        assert rc == 0

    def test_subprocess_smoke_unicode_result_survives_default_codepage(self, native_home):
        sid = SID
        seed_native_worker(native_home, sid=sid, status="idle")
        fleet.append_outcome("w1", {"ts": _iso(NOW), "session_id": sid, "kind": "result",
                                    "result_text": "✓ 完了 émoji",
                                    "input_tokens": 1, "output_tokens": 1})
        env = dict(os.environ)
        env["FLEET_HOME"] = str(native_home)
        env.pop("PYTHONIOENCODING", None)
        proc = subprocess.run(
            [*PY_CMD, str(REPO_ROOT / "bin" / "fleet.py"), "result", "w1"],
            capture_output=True, env=env, timeout=15,
        )
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
        stdout_text = proc.stdout.decode("utf-8")
        assert "✓ 完了 émoji" in stdout_text
        stderr_text = proc.stderr.decode("utf-8", errors="replace")
        assert "UnicodeEncodeError" not in stderr_text


# ---------------------------------------------------------------------------
# M-B T11: doctor pin-version gate, legacy-mix + dead-suspected advisories,
# native-skip retrofits (docs/specs/native-substrate.md, Re-verification)
# ---------------------------------------------------------------------------

class _FakeVersionResult:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


class TestPinPassStore:
    def test_record_then_read_roundtrip(self, native_home):
        fleet.record_pin_pass("2.1.207")
        pin = fleet.read_pin_pass()
        assert pin["claude_version"] == "2.1.207"
        assert "passed_at" in pin

    def test_read_missing_file_returns_none(self, native_home):
        assert fleet.read_pin_pass() is None

    def test_read_corrupt_file_returns_none(self, native_home):
        fleet.pin_pass_path().parent.mkdir(parents=True, exist_ok=True)
        fleet.pin_pass_path().write_text("not json{", encoding="utf-8")
        assert fleet.read_pin_pass() is None

    def test_read_tolerates_unknown_extra_fields(self, native_home):
        fleet._write_json_atomic(fleet.pin_pass_path(),
                                 {"claude_version": "2.1.207", "passed_at": _iso(NOW),
                                  "future_field": "whatever"})
        pin = fleet.read_pin_pass()
        assert pin["claude_version"] == "2.1.207"
        assert pin["future_field"] == "whatever"


class TestDoctorCheckPinVersion:
    def test_no_pin_file_passes_with_hint(self, native_home):
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd",
                                                         run=lambda *a, **k: _FakeVersionResult())
        assert ok is True
        assert "no pin-test pass recorded" in msg
        assert "tests/integration/test_native_pin.py" in msg

    def test_matching_version_passes(self, native_home):
        fleet.record_pin_pass("2.1.207")
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "pin-test pass current" in msg
        assert "2.1.207" in msg

    def test_mismatched_version_fails(self, native_home):
        fleet.record_pin_pass("2.1.207")
        run = lambda *a, **k: _FakeVersionResult(stdout="2.2.0")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is False
        assert "2.2.0 != 2.1.207" in msg
        assert "native-substrate.md" in msg

    def test_claude_not_on_path_passes_with_note(self, native_home):
        fleet.record_pin_pass("2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: None,
                                                         run=lambda *a, **k: _FakeVersionResult())
        assert ok is True
        assert "not resolvable" in msg

    def test_version_subprocess_failure_passes_with_note(self, native_home):
        fleet.record_pin_pass("2.1.207")
        def boom(*a, **k):
            raise OSError("nope")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=boom)
        assert ok is True
        assert "not resolvable" in msg

    # M-B T11 fix wave (HIGH #2): pin-side normalization symmetry.
    def test_raw_stdout_shaped_pin_matches_identical_live_version(self, native_home):
        # The adversarial repro: a naive caller stores the raw, unparsed
        # `claude --version` stdout capture (trailing paren text + \n).
        # Comparing against the SAME, unchanged live version must PASS,
        # not FAIL on formatting alone.
        fleet.record_pin_pass("2.1.207 (Claude Code)\n")
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207 (Claude Code)\n")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "pin-test pass current" in msg
        assert "2.1.207" in msg

    def test_genuine_mismatch_still_fails_after_normalization(self, native_home):
        fleet.record_pin_pass("2.1.207 (Claude Code)\n")
        run = lambda *a, **k: _FakeVersionResult(stdout="2.2.0 (Claude Code)\n")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is False
        assert "2.2.0 != 2.1.207" in msg
        assert "native-substrate.md" in msg

    # M-B T11 fix wave (MEDIUM x2 + review Minor): field-corrupt pin file.
    @pytest.mark.parametrize("bad_version", [None, 42, ["nested"], {"nested": "dict"}])
    def test_non_str_claude_version_is_pass_note_not_fail(self, native_home, bad_version):
        fleet._write_json_atomic(fleet.pin_pass_path(),
                                 {"claude_version": bad_version, "passed_at": _iso(NOW)})
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "pin record unreadable" in msg

    def test_missing_claude_version_key_is_pass_note_not_fail(self, native_home):
        fleet._write_json_atomic(fleet.pin_pass_path(), {"passed_at": _iso(NOW)})
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "pin record unreadable" in msg

    def test_non_version_shaped_string_is_pass_note_not_fail(self, native_home):
        fleet._write_json_atomic(fleet.pin_pass_path(),
                                 {"claude_version": "not-a-version", "passed_at": _iso(NOW)})
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "pin record unreadable" in msg

    def test_echoed_version_string_clamped_to_40_chars(self, native_home):
        # A pinned claude_version with a pathologically long digit run
        # still parses (valid \d+.\d+.\d+ match) but must not blow up the
        # FAIL message into an unbounded single line.
        huge = ("9" * 100) + ".1.1"
        fleet._write_json_atomic(fleet.pin_pass_path(),
                                 {"claude_version": huge, "passed_at": _iso(NOW)})
        run = lambda *a, **k: _FakeVersionResult(stdout="2.1.207")
        name, ok, msg = fleet._doctor_check_pin_version(which=lambda n: "claude.cmd", run=run)
        assert ok is False
        # the clamped echo (<=40 chars plus "...") appears, not the raw 104-char string
        assert huge not in msg
        assert len(msg) < 300


class TestDoctorCheckLegacyMix:
    def test_no_workers_passes_silent(self, native_home):
        name, ok, msg = fleet._doctor_check_legacy_mix({})
        assert ok is True
        assert "no pre-pivot" in msg

    def test_all_native_workers_passes_silent(self, native_home):
        rec = seed_native_worker(native_home, name="w1", status="idle")
        name, ok, msg = fleet._doctor_check_legacy_mix({"w1": rec})
        assert ok is True
        assert "no pre-pivot" in msg

    def test_legacy_worker_named_advisory(self, native_home):
        legacy = fleet.new_worker_record(SID, "C:/proj", "t", "accept")
        name, ok, msg = fleet._doctor_check_legacy_mix({"old-worker": legacy})
        assert ok is True
        assert "1 pre-pivot worker(s)" in msg
        assert "old-worker" in msg
        assert "unmanageable by this build" in msg

    def test_archived_native_worker_not_counted_as_legacy(self, native_home):
        rec = seed_native_worker(native_home, name="w1", status="idle", archived_at=_iso(NOW))
        name, ok, msg = fleet._doctor_check_legacy_mix({"w1": rec})
        assert ok is True
        assert "no pre-pivot" in msg


class TestDoctorCheckDeadSuspected:
    def test_none_passes_silent(self, native_home):
        rec = seed_native_worker(native_home, name="w1", status="idle")
        name, ok, msg = fleet._doctor_check_dead_suspected({"w1": rec})
        assert ok is True
        assert "no dead-suspected" in msg

    def test_dead_suspected_worker_named_advisory(self, native_home):
        rec = seed_native_worker(native_home, name="w1", status="dead-suspected")
        name, ok, msg = fleet._doctor_check_dead_suspected({"w1": rec})
        assert ok is True
        assert "1 dead-suspected worker(s)" in msg
        assert "w1" in msg
        assert "fleet peek/result" in msg

    def test_does_not_recompute_uses_raw_snapshot_status(self, native_home):
        # A record whose live process would actually resolve differently
        # today still gets named -- this check never touches the roster or
        # any liveness probe, only the snapshot's own `status` field.
        rec = seed_native_worker(native_home, name="w1", status="dead-suspected")
        name, ok, msg = fleet._doctor_check_dead_suspected({"w1": rec})
        assert "w1" in msg


class TestDoctorClaudeAgentsRetiredSids:
    def test_retired_sid_counted_as_known(self, native_home):
        old_sid = "aaaaaaaa-0000-0000-0000-000000000000"
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="idle",
                                 retired_sids=[old_sid])

        def run(argv, **kw):
            return _FakeVersionResult(stdout=json.dumps([{"session_id": old_sid}]))
        name, ok, msg = fleet._doctor_check_claude_agents(
            {"w1": rec}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "no fleet-unknown" in msg

    def test_still_reports_a_truly_unknown_session(self, native_home):
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="idle")

        def run(argv, **kw):
            return _FakeVersionResult(stdout=json.dumps([{"session_id": "totally-unknown"}]))
        name, ok, msg = fleet._doctor_check_claude_agents(
            {"w1": rec}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "totally-unknown" in msg

    # M-B T11 fix wave (HIGH #1): retired_sids shape tolerance.
    @pytest.mark.parametrize("bad_retired_sids", [True, 42, "not-a-list-just-a-sid-string"])
    def test_non_list_retired_sids_shapes_do_not_crash_or_char_spread(self, native_home, bad_retired_sids):
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="idle",
                                 retired_sids=bad_retired_sids)

        def run(argv, **kw):
            return _FakeVersionResult(stdout=json.dumps([{"session_id": "totally-unknown"}]))
        name, ok, msg = fleet._doctor_check_claude_agents(
            {"w1": rec}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "totally-unknown" in msg
        # the malformed retired_sids value must never spread into known_sids
        # (e.g. a string char-spreading via set.update(str))
        assert "not-a-list" not in msg

    def test_missing_session_id_does_not_raise_key_error(self, native_home):
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="idle")
        del rec["session_id"]
        data = {"workers": {"w1": rec}}
        fleet.save_registry(data)

        def run(argv, **kw):
            return _FakeVersionResult(stdout=json.dumps([{"session_id": "totally-unknown"}]))
        name, ok, msg = fleet._doctor_check_claude_agents(
            {"w1": rec}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "totally-unknown" in msg

    def test_non_dict_record_is_skipped_not_crashed(self, native_home):
        rec = seed_native_worker(native_home, name="w1", sid=SID, status="idle")

        def run(argv, **kw):
            return _FakeVersionResult(stdout=json.dumps([{"session_id": "totally-unknown"}]))
        name, ok, msg = fleet._doctor_check_claude_agents(
            {"w1": rec, "corrupt": "not-a-dict-record"}, which=lambda n: "claude.cmd", run=run)
        assert ok is True
        assert "totally-unknown" in msg


class TestDoctorOrphanedClaimsArchivedRegression:
    # M-B T11: T9's mailbox-move-on-archive fix (finding M-4b) already
    # erases this check's noise too, since an orphaned-mailbox scan can
    # only flag a *.md file that still exists under mailbox_dir() -- no
    # separate doctor-side exclusion is needed here either.
    def test_archived_workers_mailbox_moved_produces_no_orphan_noise(self, native_home):
        seed_archive_ready_worker(native_home)
        mailbox_file = fleet.mailbox_dir() / f"{SID}.md"
        mailbox_file.write_text("pending mail", encoding="utf-8")

        rc = fleet.cmd_archive(_archive_args(), run=_archive_fake_run(rc=0), which=lambda _: "claude")
        assert rc == 0

        workers = fleet.load_registry()["workers"]
        _name, ok, msg = fleet._doctor_check_orphaned_claims(workers=workers)
        assert ok is True
        assert SID not in msg


class TestCmdDoctorRegistersNewChecks:
    def test_new_checks_run_and_appear_in_output(self, native_home, capsys):
        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(
            args, which=lambda n: None,
            run=lambda *a, **k: _FakeVersionResult(),
        )
        out = capsys.readouterr().out
        assert "pin-version" in out
        assert "legacy-mix" in out
        assert "dead-suspected" in out
        # pin-version registered right after claude-on-path, per the T11 brief.
        assert out.index("claude-on-path") < out.index("pin-version") < out.index("worker-settings-instance")


# ---------------------------------------------------------------------------
# M-B T11 fix wave: CRITICAL -- per-check isolation in cmd_doctor.
# ---------------------------------------------------------------------------

class TestCmdDoctorCheckIsolation:
    def test_raising_check_yields_own_fail_line_others_still_print(self, native_home, monkeypatch, capsys):
        def _doctor_check_claude_agents(*a, **k):
            raise TypeError("'int' object is not iterable")
        monkeypatch.setattr(fleet, "_doctor_check_claude_agents", _doctor_check_claude_agents)

        args = fleet.build_parser().parse_args(["doctor"])
        rc = fleet.cmd_doctor(
            args, which=lambda n: None,
            run=lambda *a, **k: _FakeVersionResult(),
        )
        out = capsys.readouterr().out
        assert "[FAIL] _doctor_check_claude_agents: check crashed: TypeError: " \
               "'int' object is not iterable" in out
        # checks registered AFTER the crashing one still ran and printed.
        assert "autoclean" in out
        assert "fleet-home marker" in out
        assert "supervisor" in out
        assert rc == 1

    def test_register_order_intact_when_an_earlier_check_crashes(self, native_home, monkeypatch, capsys):
        def _doctor_check_legacy_mix(*a, **k):
            raise ValueError("boom")
        monkeypatch.setattr(fleet, "_doctor_check_legacy_mix", _doctor_check_legacy_mix)

        args = fleet.build_parser().parse_args(["doctor"])
        fleet.cmd_doctor(
            args, which=lambda n: None,
            run=lambda *a, **k: _FakeVersionResult(),
        )
        out = capsys.readouterr().out
        assert "[FAIL] _doctor_check_legacy_mix: check crashed: ValueError: boom" in out
        # order preserved around the crashed check: claude-on-path and
        # pin-version still precede it; dead-suspected (registered right
        # after legacy-mix) still follows it.
        assert (out.index("claude-on-path") < out.index("pin-version")
                < out.index("_doctor_check_legacy_mix") < out.index("dead-suspected"))

    def test_crash_message_clamped_to_200_chars(self, native_home, monkeypatch, capsys):
        def _doctor_check_dead_suspected(*a, **k):
            raise ValueError("x" * 500)
        monkeypatch.setattr(fleet, "_doctor_check_dead_suspected", _doctor_check_dead_suspected)

        args = fleet.build_parser().parse_args(["doctor"])
        fleet.cmd_doctor(
            args, which=lambda n: None,
            run=lambda *a, **k: _FakeVersionResult(),
        )
        out = capsys.readouterr().out
        assert ("x" * 500) not in out
        assert ("x" * 200) in out
