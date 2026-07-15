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

    def test_is_native_and_legacy_refusal(self, native_home):
        native = {"dispatch_kind": "bg"}
        legacy = {"session_id": "old"}  # pre-pivot record: key absent entirely
        assert fleet.is_native(native) is True
        assert fleet.is_native(legacy) is False
        with pytest.raises(fleet.FleetCliError, match="pre-pivot"):
            fleet.refuse_if_legacy("w1", legacy, "send")
        fleet.refuse_if_legacy("w1", native, "send")  # no raise

    @pytest.mark.parametrize("bad", [None, "junk", [], 42])
    def test_is_native_non_dict_returns_false(self, native_home, bad):
        assert fleet.is_native(bad) is False

    @pytest.mark.parametrize("bad", [None, "junk", [], 42])
    def test_refuse_if_legacy_non_dict_raises_fleet_cli_error(self, native_home, bad):
        with pytest.raises(fleet.FleetCliError, match="pre-pivot"):
            fleet.refuse_if_legacy("w1", bad, "send")


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
