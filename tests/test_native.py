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
    def test_native_busy_stays_working_and_never_pid_probed(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="busy")]))

        def _boom(*a, **k):
            raise AssertionError("recompute_worker (PID probe) must not run for a native record")
        monkeypatch.setattr(fleet, "recompute_worker", _boom)

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        assert fleet.load_registry()["workers"]["w1"]["status"] == "working"

    def test_legacy_worker_still_uses_pid_probe(self, native_home):
        rec = fleet.new_worker_record("legacy-sid-0000", "C:/proj", "do it", "accept")
        rec["status"] = "working"
        rec["turn_pid"] = 4242
        rec["turn_pid_ctime"] = fleet.now_iso()
        data = fleet.load_registry()
        data["workers"]["legacy1"] = rec
        fleet.save_registry(data)

        rc = fleet.cmd_status(_status_args(), get_process_info=lambda pid: None)
        assert rc == 0
        assert fleet.load_registry()["workers"]["legacy1"]["status"] == "dead"

    def test_mixed_native_and_legacy_split_correctly(self, native_home, monkeypatch):
        seed_native_worker(native_home, status="working")
        legacy = fleet.new_worker_record("legacy-sid-0001", "C:/proj", "do it", "accept")
        legacy["status"] = "working"
        legacy["turn_pid"] = 4242
        legacy["turn_pid_ctime"] = fleet.now_iso()
        data = fleet.load_registry()
        data["workers"]["legacy1"] = legacy
        fleet.save_registry(data)
        monkeypatch.setattr(fleet, "_fetch_agents_roster",
                            _fixed_roster(True, [make_roster_entry(SID, status="busy")]))

        rc = fleet.cmd_status(_status_args(), get_process_info=lambda pid: None)
        assert rc == 0
        workers = fleet.load_registry()["workers"]
        assert workers["w1"]["status"] == "working"
        assert workers["legacy1"]["status"] == "dead"

    def test_epoch_freeze_prints_warning_and_freezes_native_write(self, native_home, monkeypatch, capsys):
        rec = seed_native_worker(native_home, status="working")
        monkeypatch.setattr(fleet, "_fetch_agents_roster", _fixed_roster(False, None))

        rc = fleet.cmd_status(_status_args())
        assert rc == 0
        out = capsys.readouterr().out
        assert "EPOCH: roster suspicious -- native verdicts frozen (G9); legacy rows only" in out
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
