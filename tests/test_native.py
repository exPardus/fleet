"""M-B native-substrate tests: registry v2 fields, outcome store, dispatch
helper, discriminator, limit rehome, steering, stop/tombstones, archival."""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fleet


NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


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
    def fetch(**_):
        return True, [make_roster_entry(sid, **kw)]
    return fetch


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
        def empty_fetch(**_):
            return True, []
        with pytest.raises(fleet.NativeDispatchError, match="aaaabbbb"):
            fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                              run=_fake_run_factory(), which=lambda _: "claude",
                              sleep=lambda s: None, roster_fetch=empty_fetch)

    def test_join_matches_done_entry_fast_completion(self, native_home):
        out = fleet.dispatch_bg("w1", "C:/proj", "b", "accept",
                                run=_fake_run_factory(), which=lambda _: "claude",
                                sleep=lambda s: None,
                                roster_fetch=_roster_with(state="done", status=None, pid=None))
        assert out["session_id"] == SID
