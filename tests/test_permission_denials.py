"""w56: a permission-DENIED worker is loud (incident 2026-09-09).

Three workers dispatched at the shipped `fleet spawn` default `--mode dontask`
were born unable to act, and every fleet view rendered them exactly as it
renders a worker that finished a fast task: `idle` on turn 1 with an outcome
record. These tests pin the signal that closes that, end to end -- the Stop
hook's count of the harness's own `toolDenialKind` field, the outcome record it
lands in, the bounded reader, `status_snapshot`'s row field, both tables, and
the `fleet doctor` row.

TWO DISTINCTIONS CARRY MOST OF THE FILE, because getting either wrong turns the
signal back into the silence it replaces:

  * UNKNOWN IS NOT ZERO. An absent field means nothing measured; `0` means a
    transcript was read and held no denial. A reader that answers `0` for
    "unknown" vouches for a worker nobody looked at.
  * A COUNT IS NOT A VERDICT. Every surface here reports the number the harness
    recorded. Nothing infers "this worker is broken" from it, so nothing here
    can fire falsely -- the soak file's rule (`a rule that fires falsely is
    worse than a rule that is absent`) is satisfied by having no rule at all.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import fleet


REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_OUTCOME_HOOK = REPO_ROOT / "bin" / "hooks" / "stop_outcome.py"

NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fleet, "FLEET_HOME", tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "mailbox").mkdir()
    return tmp_path


def _transcript(tmp_path, *records, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return p


def _assistant(text="done", msg_id="m1"):
    return {"type": "assistant",
            "message": {"id": msg_id, "model": "claude-opus-5",
                        "content": [{"type": "text", "text": text}],
                        "usage": {"input_tokens": 1, "output_tokens": 2}}}


def _denial(kind="permission-rule", tool="Bash"):
    """The shape measured on this host: the DENIAL is recorded on the
    `type:"user"` record that answers the tool call, not on an assistant
    record. `toolDenialKind` is the harness's own typed field."""
    return {"type": "user", "toolDenialKind": kind,
            "message": {"content": [{"type": "tool_result", "is_error": True,
                                     "content": f"Permission to use {tool} has been "
                                                f"denied because Claude Code is "
                                                f"running in don't ask mode."}]}}


def _run_hook(home_dir, sid, transcript_path, last_message="done"):
    payload = {"session_id": sid, "last_assistant_message": last_message}
    if transcript_path is not None:
        payload["transcript_path"] = str(transcript_path)
    proc = subprocess.run(
        [sys.executable, str(STOP_OUTCOME_HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env={"FLEET_HOME": str(home_dir), "PATH": "", "SYSTEMROOT": ""},
    )
    assert proc.returncode == 0, proc.stderr.decode()
    return proc


def _records(home_dir, key):
    path = home_dir / "state" / "outcomes" / f"{key}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class TestTheStopHookCountsDenials:
    """The hook already reads the transcript once per turn for the usage
    numbers; the count comes out of that same pass."""

    def test_a_denied_session_lands_a_count_and_its_kinds(self, home, tmp_path):
        tp = _transcript(tmp_path, _denial(), _assistant(), _denial(tool="Write"))
        _run_hook(home, "sid-1", tp)
        rec = _records(home, "sid-1")[-1]
        assert rec["permission_denials"] == 2
        assert rec["permission_denial_kinds"] == {"permission-rule": 2}

    def test_denials_are_read_from_user_records_not_assistant_ones(self, home, tmp_path):
        """The regression this guards: the transcript loop filters to
        `type == "assistant"`, and every denial record is a `type:"user"` one.
        Reading the field after that filter counts zero, forever."""
        tp = _transcript(tmp_path, _denial(), _denial(), _denial())
        _run_hook(home, "sid-1", tp)
        assert _records(home, "sid-1")[-1]["permission_denials"] == 3

    def test_a_clean_session_records_a_measured_zero(self, home, tmp_path):
        tp = _transcript(tmp_path, _assistant())
        _run_hook(home, "sid-1", tp)
        rec = _records(home, "sid-1")[-1]
        assert rec["permission_denials"] == 0
        assert rec["permission_denial_kinds"] == {}

    def test_an_unreadable_transcript_writes_NO_count_rather_than_zero(self, home, tmp_path):
        """Unknown is not zero. A transcript the hook could not open has
        measured nothing, and publishing `0` would make it vouch for a worker
        nobody looked at."""
        _run_hook(home, "sid-1", tmp_path / "does-not-exist.jsonl")
        rec = _records(home, "sid-1")[-1]
        assert "permission_denials" not in rec
        assert "permission_denial_kinds" not in rec

    def test_a_payload_with_no_transcript_path_writes_no_count(self, home, tmp_path):
        _run_hook(home, "sid-1", None)
        assert "permission_denials" not in _records(home, "sid-1")[-1]

    def test_an_unknown_denial_kind_is_counted_not_dropped(self, home, tmp_path):
        """A kind this fleet has never seen is still a denial. Dropping it is
        how a signal goes missing the day the harness adds a second kind."""
        tp = _transcript(tmp_path, _denial(kind="hook-deny"), _denial())
        _run_hook(home, "sid-1", tp)
        rec = _records(home, "sid-1")[-1]
        assert rec["permission_denials"] == 2
        assert rec["permission_denial_kinds"] == {"hook-deny": 1, "permission-rule": 1}

    def test_a_non_string_kind_survives_as_its_repr(self, home, tmp_path):
        tp = _transcript(tmp_path, {"type": "user", "toolDenialKind": 7})
        _run_hook(home, "sid-1", tp)
        assert _records(home, "sid-1")[-1]["permission_denials"] == 1

    def test_the_usage_fields_are_unchanged_by_the_new_field(self, home, tmp_path):
        """The count is NOT subject to the usage fields' proof-of-lastness
        gate, and adding it must not disturb that gate either way."""
        tp = _transcript(tmp_path, _denial(), _assistant(text="done"))
        _run_hook(home, "sid-1", tp, last_message="done")
        rec = _records(home, "sid-1")[-1]
        assert rec["input_tokens"] == 1 and rec["output_tokens"] == 2
        assert rec["permission_denials"] == 1


class TestTheBoundedTailReader:
    """`status_snapshot` refires after every assistant message and an outcome
    file grows without bound, so the snapshot's reader is bounded by
    construction rather than by hoping the file stays small."""

    def test_an_absent_file_reads_as_no_records(self, home):
        assert fleet._tail_outcome_records("nobody") == []

    def test_a_whole_small_file_is_read(self, home):
        fleet.append_outcome("w1", {"ts": "2026-09-09T00:00:00Z", "kind": "result"})
        fleet.append_outcome("w1", {"ts": "2026-09-09T00:00:01Z", "kind": "killed"})
        assert len(fleet._tail_outcome_records("w1")) == 2

    def test_only_the_tail_is_read_when_the_file_is_larger_than_the_window(self, home):
        for i in range(50):
            fleet.append_outcome("w1", {"ts": f"2026-09-09T00:00:{i:02d}Z",
                                        "kind": "result", "pad": "x" * 4000})
        recs = fleet._tail_outcome_records("w1", max_bytes=20000)
        assert 0 < len(recs) < 50
        # The NEWEST record is what the field lives in, and it is never the one
        # the window loses -- the loss is always at the far end.
        assert recs[-1]["ts"] == "2026-09-09T00:00:49Z"

    def test_the_partial_first_line_of_a_window_is_discarded_not_parsed(self, home):
        fleet.append_outcome("w1", {"ts": "2026-09-09T00:00:00Z", "kind": "result",
                                    "pad": "x" * 4000})
        fleet.append_outcome("w1", {"ts": "2026-09-09T00:00:01Z", "kind": "result"})
        recs = fleet._tail_outcome_records("w1", max_bytes=200)
        assert [r["ts"] for r in recs] == ["2026-09-09T00:00:01Z"]

    def test_a_torn_line_is_skipped_exactly_as_read_outcomes_skips_it(self, home):
        fleet.outcomes_dir().mkdir(parents=True, exist_ok=True)
        fleet.outcome_path("w1").write_text(
            '{"ts":"a","kind":"result"\n{"ts":"b","kind":"result"}\n', encoding="utf-8")
        assert [r["ts"] for r in fleet._tail_outcome_records("w1")] == ["b"]

    def test_it_never_raises_on_a_directory_where_a_file_belongs(self, home):
        fleet.outcomes_dir().mkdir(parents=True, exist_ok=True)
        fleet.outcome_path("w1").mkdir()
        assert fleet._tail_outcome_records("w1") == []


class TestTheCountReader:
    def test_a_missing_field_is_unknown_not_zero(self, home):
        assert fleet._outcome_denial_count({"kind": "result"}) is None

    @pytest.mark.parametrize("bogus", [True, False, -1, "3", 2.0, None, [3]])
    def test_a_value_that_is_not_a_count_is_unknown(self, home, bogus):
        assert fleet._outcome_denial_count({"permission_denials": bogus}) is None

    def test_a_real_count_reads_through(self, home):
        assert fleet._outcome_denial_count({"permission_denials": 0}) == 0
        assert fleet._outcome_denial_count({"permission_denials": 11}) == 11

    def test_a_later_tombstone_does_not_hide_the_count(self, home):
        """The measured shape of the incident: a `result` record carrying the
        count, then the operator's `killed` tombstone, which carries no
        transcript and so no count. Reading only the LAST record answers
        "unknown" for the one worker in three that actually reported."""
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:27:23Z", "session_id": "s1",
                                    "kind": "result", "permission_denials": 11})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:30:29Z", "session_id": "s1",
                                    "kind": "killed", "result_text": None})
        assert fleet._session_permission_denials("w1", "s1") == 11

    def test_the_newest_measured_turn_wins(self, home):
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "s1",
                                    "kind": "result", "permission_denials": 4})
        fleet.append_outcome("w1", {"ts": "2026-09-09T07:00:00Z", "session_id": "s1",
                                    "kind": "result", "permission_denials": 9})
        assert fleet._session_permission_denials("w1", "s1") == 9

    def test_a_predecessor_sids_denials_do_not_leak_into_this_body(self, home):
        """A respawn under a fixed mode must CLEAR the signal, not inherit it."""
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "old",
                                    "kind": "result", "permission_denials": 11})
        assert fleet._session_permission_denials("w1", "new") is None

    def test_the_sid_keyed_fallback_file_is_read_too(self, home):
        """`read_outcomes`' dual-file shape: a hook that could not resolve the
        worker name writes `outcomes/<sid>.jsonl` instead."""
        fleet.append_outcome("s1", {"ts": "2026-09-09T06:00:00Z", "session_id": "s1",
                                    "kind": "result", "permission_denials": 3})
        assert fleet._session_permission_denials("w1", "s1") == 3

    def test_no_sid_is_unknown(self, home):
        assert fleet._session_permission_denials("w1", None) is None
        assert fleet._session_permission_denials("w1", "") is None


def _registry(home, **workers):
    data = {"workers": {}}
    for name, over in workers.items():
        rec = {"session_id": f"sid-{name}", "cwd": str(home), "task": "t",
               "mode": "dontask", "model": None, "status": "idle", "turns": 1,
               "created": "2026-09-09T06:00:00Z",
               "last_activity": "2026-09-09T06:00:00Z", "dispatch_kind": "bg"}
        rec.update(over)
        data["workers"][name] = rec
    (home / "state" / "fleet.json").write_text(json.dumps(data), encoding="utf-8")
    return data


class TestTheSnapshotCarriesIt:
    """Soak item S-2's chosen layer: `status_snapshot`, 'where every view would
    get it'. S-2 names the permission STALL, which can never live here (the
    roster is its only witness); a DENIAL leaves an artifact, so for a denial
    the layer S-2 picked is exactly right."""

    def test_a_denied_row_carries_the_count(self, home):
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        row, = fleet.status_snapshot(now=NOW)["workers"]
        assert row["permission_denials"] == 11

    def test_a_measured_clean_row_carries_zero(self, home):
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 0})
        row, = fleet.status_snapshot(now=NOW)["workers"]
        assert row["permission_denials"] == 0

    def test_a_row_nothing_has_measured_carries_None(self, home):
        _registry(home, w1={})
        row, = fleet.status_snapshot(now=NOW)["workers"]
        assert row["permission_denials"] is None

    def test_a_record_written_before_the_field_existed_reads_as_unknown(self, home):
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "result_text": "hi"})
        row, = fleet.status_snapshot(now=NOW)["workers"]
        assert row["permission_denials"] is None

    def test_the_snapshot_still_takes_no_lock_and_never_quarantines(self, home, monkeypatch):
        """Views doctrine D1/D4 (root CLAUDE.md): the new read must not have
        smuggled in a lock, a probe, or the loader that quarantines."""
        def boom(*a, **k):  # pragma: no cover -- the point is that it never runs
            raise AssertionError("status_snapshot must not reach this")
        monkeypatch.setattr(fleet, "fleet_lock", boom)
        monkeypatch.setattr(fleet, "load_registry", boom)
        monkeypatch.setattr(fleet, "_quarantine_registry", boom)
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        assert fleet.status_snapshot(now=NOW)["workers"][0]["permission_denials"] == 11


class TestBothTablesRenderTheSameNumber:
    def test_the_stale_ok_table_flags_a_denied_worker(self, home, capsys):
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        fleet._print_snapshot_table(fleet.status_snapshot(now=NOW))
        assert "permission-denied:11" in capsys.readouterr().out

    def test_the_stale_ok_table_says_nothing_for_a_measured_zero(self, home, capsys):
        _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 0})
        fleet._print_snapshot_table(fleet.status_snapshot(now=NOW))
        assert "permission-denied" not in capsys.readouterr().out

    def test_the_probed_table_prints_the_same_number(self, home, capsys):
        """Two views, one worker, one story -- the failure this guards is the
        `cost_usd` one W15 documents, where two tables disagreed about the
        same record."""
        data = _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        fleet._print_status_table(data, ["w1"])
        assert "permission-denied:11" in capsys.readouterr().out


class TestTheDoctorRow:
    def test_it_names_the_worker_its_mode_and_the_count(self, home):
        data = _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        name, ok, msg = fleet._doctor_check_permission_denials(data["workers"])
        assert name == "permission-denials"
        assert "w1 (mode=dontask): 11 denied" in msg

    def test_it_is_note_only_and_never_flips_the_exit_code(self, home):
        """Deliberately NOT a FAIL, unlike `permission-stalls`. That row earned
        its exit code on being unable to go stale-red; this one reads a durable
        record and would stay red until the operator archives the worker, which
        is the permanently-red-doctor failure the standing doctrine forbids."""
        data = _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        assert fleet._doctor_check_permission_denials(data["workers"])[1] is True

    def test_a_clean_fleet_does_not_claim_more_than_it_checked(self, home):
        data = _registry(home, w1={})
        _, ok, msg = fleet._doctor_check_permission_denials(data["workers"])
        assert ok is True
        assert "measured" in msg

    def test_an_archived_row_is_history_and_is_skipped(self, home):
        data = _registry(home, w1={"archived_at": "2026-09-09T07:00:00Z"})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "permission_denials": 11})
        assert "w1" not in fleet._doctor_check_permission_denials(data["workers"])[2]

    def test_an_unmeasured_worker_is_not_reported_as_clean_or_denied(self, home):
        data = _registry(home, w1={})
        fleet.append_outcome("w1", {"ts": "2026-09-09T06:00:00Z", "session_id": "sid-w1",
                                    "kind": "result", "result_text": "hi"})
        assert "w1" not in fleet._doctor_check_permission_denials(data["workers"])[2]

    def test_it_is_registered_in_cmd_doctors_check_list(self, home):
        import inspect
        src = inspect.getsource(fleet.cmd_doctor)
        assert "_doctor_check_permission_denials" in src


class TestTheSignalIsAMeasurementNotAVerdict:
    def test_nothing_in_the_detector_infers_a_mode_from_a_count(self):
        """`a rule that fires falsely is worse than a rule that is absent`
        (docs/operator/keeper-soak-2026-09.md). This detector reports the
        number the harness recorded and draws no conclusion from it, so there
        is no rule here to fire at all -- the operator does the inferring, with
        the mode printed next to the count to infer from."""
        import inspect
        for fn in (fleet._session_permission_denials, fleet._outcome_denial_count,
                   fleet._tail_outcome_records):
            src = inspect.getsource(fn)
            assert "dontask" not in src
            assert "result_text" not in src
